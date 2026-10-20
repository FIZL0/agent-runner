"""`./run run`: keep N agent sessions working through the task list, for as long as the work lasts.

Most of a long project is small, checkable steps that need no human in the loop: they need the backlog,
the tests and a commit. This is the loop that does that. It picks the next task nobody is on, opens a git
worktree and a tmux pane for it, and starts an agent session with the task's brief already pasted into
the first turn. It waits for the session to finish, merges and tests the branch, pushes it, and starts the
next task.

    ./run run once            one task, then stop (the way to try it the first time)
    ./run run                 [run] slots agents (3), mode d (different files), in tmux
    ./run run 5 --mode p      5 agents, strictly in TODO.md order, files may overlap
    ./run run 1               one at a time, in this checkout (also what you get without tmux)
    ./run run --dry-run 4     print what 4 free slots would start now, and start nothing
    ./run stop                finish what is running, start nothing new, then exit (or type s + Enter
                              in the runner's pane; s again takes it back)
    (every form but `once` stays up when the work runs out: it logs `run idle` and waits for more)

The README explains each mechanism and the night that made it necessary. In short:

* **picking** (`tasks`, `pick`) goes down TODO.md in order and skips
  - blocked tasks and split parents,
  - tasks with an open `(after X, Y)`,
  - tasks whose line names a running task,
  - the Stretch section, anything tried this run, and branches waiting to be merged.

  Siblings never run together. An ordered section runs one task at a time. Mode d keeps tasks off each
  other's files.
* **one worktree per slot**, kept warm between tasks, with `[run] links` symlinked in;
* **an idle stop** (the Stop hook): a finished session is ended once its transcript is quiet;
* **a usage limit is not a failed task**: the transcript is dropped and the slot sleeps to the reset;
* **a stall watchdog**: belled and logged, with the pane to attach to;
* **merges in a merge worktree**: tested before the shared branch moves, so the main checkout never
  holds an untested merge and nobody's edits are stashed;
* **a fix session per conflict** that a line join cannot do;
* **blocks reopen themselves** when what they waited on lands;
* **a tested merge is pushed**;
* **it stays up**: out of work, it logs `run idle` and keeps reading TODO.md (`retry_reopened` puts a
  tried task a human unblocked back in the pool). Scripts watch run.log for `run idle`, not the exit.

Internal modes (used by the sessions it starts, not by you):
    --stop-hook            Stop hook: arm the idle timer for the session that is stopping
    --stop-waiter P T N S  the detached timer itself
"""
from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import glob
import json
import os
import re
import shlex
import shutil
import signal
import subprocess as sp
import sys
import threading
import time
import uuid
from pathlib import Path

from agent_runner import plan as P
from agent_runner.config import RUNNER, Config, cfg, main_checkout
from agent_runner.done import gate
from agent_runner.gitops import drop_if_merged, push

TASK = re.compile(r'^- \[ \] \*\*([^*\s]+)\*\*(.*)')
ANY_TASK = re.compile(r'^- \[.\] \*\*([^*\s]+)\*\*')
TAG = '@runner'  # the tmux pane option a slot's pane is found by

ROOT = Path('.')       # the main checkout; set by `init`
SLOTS_DIR = Path('.')  # <repo>-slots/ beside it: s1, s2, …, and `merge`
C: Config


def init(root=None) -> Config:
    """Point the runner at the repository around `root` (default: the current directory)."""
    global ROOT, SLOTS_DIR, C
    ROOT = main_checkout(root)
    SLOTS_DIR = ROOT.parent / f'{ROOT.name}-slots'
    C = cfg(ROOT)
    return C


PROMPT = """Unattended run: nobody will answer questions, so never ask one — decide, write down why, and go on.

Do task {tid} and nothing else. You are in a git worktree on branch task/{tid}: commit here only. Never \
touch the main checkout, and never merge, rebase or push the main branch. When your session ends, the \
runner merges your branch, tests the merge and publishes it. `{runner} done` pushes task/{tid} for you, \
which is the one copy of your work that is not on this disk.
{others}{earlier}
Rules: {rules}. {test}
{journal}
Finish with `{runner} done {tid} "<commit message>"`. It runs the test gate, ticks the task, commits and \
pushes, and it refuses to tick when the gate fails.

If you are stuck (a tool hangs, the same fix fails twice, it needs a human, about 20 minutes with no \
progress), commit what is solid and run `{runner} done {tid} "<msg>" --blocked "<why + what would unblock \
it>"`, then stop. If all it waits on is another task landing (its code is not on the main branch yet), add \
`--after <ID>[,<ID>]`, and the run reopens it the moment those merge.

A usage limit is not being stuck: do not block the task. The session waits for the reset and carries on.

The task list is a tool, not a file to read whole: `{runner} plan` lists the tasks, `{runner} plan <ID>` \
shows one, and `{runner} plan add <PREFIX> "<text>"` files a follow-up you find but must not do now. Never \
hand-edit a checkbox.
{extra}
The task's brief (`{runner} plan brief {tid}`) follows, so don't gather it again.

{brief}"""

OTHERS = ('Other agents are working on other tasks at the same time, in other worktrees. Keep your changes '
          'local: add functions and new files, and don\'t move, rename or reformat code you did not come '
          'for, so the merges stay clean.\n')


# --- small helpers -------------------------------------------------------------

def log(msg: str) -> None:
    line = f'=== {dt.datetime.now().isoformat(timespec="seconds")} {msg}'
    print(line, flush=True)
    try:
        with open(C.notes('run.log'), 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except OSError:
        pass


def git(*a: str, cwd=None) -> sp.CompletedProcess:
    return sp.run(['git', *a], cwd=str(cwd or ROOT), capture_output=True, text=True)


def note(msg: str) -> None:
    """One line in `<notes>/ledger.md`: what happened to each branch. The fix sessions read its tail.

    It is one file whichever path a branch took, because the question asked in the morning is "what
    happened to my eight tasks", not "which part of the runner did it".
    """
    try:
        with open(C.notes('ledger.md'), 'a', encoding='utf-8') as f:
            f.write(f'{dt.datetime.now():%m-%d %H:%M} {msg}\n')
    except OSError:
        pass


def plan_rel(name: str) -> str:
    return os.path.relpath(C.plan_dir / name, C.root)


def default_branch() -> str:
    """The branch worktrees start from and finished work is merged into."""
    remote = C.push_remote or 'origin'
    r = git('symbolic-ref', '--quiet', '--short', f'refs/remotes/{remote}/HEAD')
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip().split('/', 1)[-1]
    for b in ('main', 'master', 'trunk'):
        if git('rev-parse', '--verify', '--quiet', b).returncode == 0:
            return b
    return git('branch', '--show-current').stdout.strip() or 'main'


def plan_text(branch: str) -> list[str]:
    """TODO.md as the merge target has it — not a worktree's copy, so a branch mid-task cannot skew picks."""
    r = git('show', f'{branch}:{plan_rel("TODO.md")}')
    if r.returncode == 0:
        return r.stdout.splitlines()
    return P.lines(C.todo)


def stopping() -> bool:
    """`./run stop` (or `s` in the runner's pane) was asked for: start nothing new."""
    return C.notes('STOP').exists()


def ask_stop(how: str) -> None:
    """The one stop mechanism: the STOP file, saying who asked. `./run stop` and `s` + Enter both write it."""
    C.notes('STOP').write_text(f'{dt.datetime.now().isoformat(timespec="seconds")} {how}\n', encoding='utf-8')


def stopped_by() -> str:
    try:
        return C.notes('STOP').read_text(encoding='utf-8').split(maxsplit=1)[1].strip()
    except (OSError, IndexError):
        return './run stop'


KEYS: list[str] = []  # lines typed into the runner's pane


def read_keys() -> None:
    """A daemon thread's loop: every line typed into the runner's pane goes on KEYS for the loop to read.

    A thread rather than select() on stdin, which only works on POSIX. Started only when stdin is a tty, and
    never by the sequential run, whose agent session reads the same terminal.
    """
    for line in sys.stdin:
        KEYS.append(line.strip().lower())


def take_keys() -> None:
    """`s` + Enter toggles the stop, as opentennis's parallel runner does: nothing new starts, the running
    tasks finish and merge, then the run ends. `s` again takes it back. Ctrl-C cuts sessions off mid-task."""
    while KEYS:
        if KEYS.pop(0) != 's':
            continue
        if stopping():
            C.notes('STOP').unlink(missing_ok=True)
            log('stop taken back: starting tasks again')
        else:
            ask_stop('s')
            log('stopping: no new tasks; the running ones finish and merge, then the run ends (s again: undo)')


# --- picking the next task -----------------------------------------------------

def tasks(branch: str) -> list[tuple[str, str, set[str], set[str]]]:
    """Open tasks in TODO.md order: (id, section, files named on the line, task ids named on it)."""
    ls = plan_text(branch)
    open_ids = {m.group(1) for l in ls if (m := TASK.match(l))}
    every = {m.group(1) for l in ls if (m := ANY_TASK.match(l))}
    out, section = [], ''
    for l in ls:
        if l.startswith('### '):
            section = l[4:]
            continue
        m = TASK.match(l)
        if not m or section.startswith('Stretch') or 'split into' in l:
            continue
        tid, rest = m.group(1), m.group(2)
        # a parent whose own subtasks are open: those run instead of it
        if any(o != tid and o.startswith(tid) and o[len(tid)].isdigit() != tid[-1].isdigit()
               for o in open_ids):
            continue
        # `(after S41, S45, S46)` is every one of them. A one-id pattern once read that as no dependency
        # at all, which is how S48 started before S41 had landed, and then blocked itself
        if any(set(P.TASK_ID.findall(a)) & (open_ids - {tid}) for a in re.findall(r'\(after ([^)]*)\)', l)):
            continue
        named = set(P.TASK_ID.findall(rest)) & every - {tid}
        out.append((tid, section, set(P.files_on_line(rest, C.root)), named))
    return out


def family(tid: str) -> str:
    """L3a, L3b, L3 -> L3; A11k4 -> A11. Siblings share it and never run side by side, in any mode."""
    m = re.match(r'[A-Za-z]*\d*', tid)
    return m.group() if m else tid


def pick(running: dict, tried: set, mode: str, branch: str):
    """The next task a free slot may take, or None. See the module docstring for the rules."""
    busy = list(running.values())
    # A section whose heading says its tasks are ordered ("Next (in this order)") runs one task at a time:
    # its second task usually depends on the first having landed, whatever the files say.
    busy_sections = {b[1] for b in busy}
    busy_ids = {b[0] for b in busy}
    shared = set(C.run['shared_files'])
    for tid, section, files, named in tasks(branch):
        if tid not in busy_ids and git('rev-list', '-1', f'{branch}..task/{tid}').stdout.strip():
            continue  # finished, its branch is waiting to be merged: restarting it would reset the branch
        if any(family(tid) == family(b[0]) for b in busy):
            continue
        if tid in tried or tid in busy_ids:
            continue
        if named & busy_ids:
            continue  # its line names a task that is running now: it is built on that, so it waits for it
        if mode == 'p':
            return tid, section, files, named
        if (section.startswith('Next') or 'in this order' in section) and section in busy_sections:
            continue
        if all(not ((files - shared) & b[2]) for b in busy):
            return tid, section, files, named
    return None


# --- worktrees and panes -------------------------------------------------------

def worktree(n, branch: str) -> Path:
    """Slot n's worktree (or the merge worktree), created once and kept: a warm build is worth more than a
    clean one. `[run] links` — git-ignored data the work needs — are symlinked in, never copied."""
    d = SLOTS_DIR / (f's{n}' if isinstance(n, int) else str(n))
    if not d.is_dir():
        SLOTS_DIR.mkdir(parents=True, exist_ok=True)
        git('worktree', 'prune')
        git('worktree', 'add', '-q', '--detach', str(d), branch)
    for pat in [*C.run['links'], 'runner.toml']:
        for src in map(Path, glob.glob(str(ROOT / pat))):
            dst = d / src.relative_to(ROOT)
            if src.exists() and not dst.is_symlink() and not dst.exists():
                try:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    dst.symlink_to(src)
                except OSError:
                    pass
    return d


def tmux(*a: str, **kw) -> sp.CompletedProcess:
    return sp.run(['tmux', *a], capture_output=True, text=True, **kw)


def pane(name: str, cwd: Path, cmd: str, env=(), logfile: Path | None = None) -> int:
    """Open cmd in a pane of the window "agents", tagged @runner=name, in slot order; returns its pid.

    Panes are found by their tag rather than their position, so you can break them out, join them or swap
    them around while the run goes on. The pane's output is piped to `logfile`, which is where a usage
    limit's "resets 3pm" shows up when the transcript does not have it.
    """
    envs = [a for e in env for a in ('-e', e)]
    w = 'agents'
    where = ['new-window', '-n', w]
    if w in tmux('list-windows', '-F', '#{window_name}').stdout.split():
        here = sorted((int(h[1:]), p) for p, h in
                      (l.split('\t') for l in tmux('list-panes', '-t', w, '-F',
                                                   f'#{{pane_id}}\t#{{{TAG}}}').stdout.splitlines())
                      if re.fullmatch(r's\d+', h))
        k = int(name[1:])
        lower = [p for i, p in here if i < k]
        where = (['split-window', '-h', '-t', lower[-1]] if lower else
                 ['split-window', '-h', '-b', '-t', here[0][1] if here else w])
    r = tmux(*where, '-d', '-c', str(cwd), *envs, '-P', '-F', '#{pane_id} #{pane_pid}', cmd)
    if r.returncode or not r.stdout.split():
        raise SystemExit(f'tmux could not open a pane: {r.stderr.strip()}')
    pane_id, pid = r.stdout.split()[:2]
    tmux('set-option', '-p', '-t', pane_id, TAG, name)
    tmux('set-option', '-w', '-t', w, 'pane-border-status', 'top')
    tmux('set-option', '-w', '-t', w, 'pane-border-format', f' #{{{TAG}}} ')
    tmux('select-layout', '-t', w, 'even-horizontal')
    if logfile:
        tmux('pipe-pane', '-t', pane_id, '-o', f'cat >> {shlex.quote(str(logfile))}')
    return int(pid)


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:  # a zombie answers kill(0) too
        return Path(f'/proc/{pid}/stat').read_text().split(')')[-1].split()[0] != 'Z'
    except OSError:
        return True


# --- starting a session --------------------------------------------------------

def lean() -> list[str]:
    """Bash/Read/Edit/Write and the repo's own settings only: an unattended agent needs no MCP servers, and a
    user-level setting (a status line, a hook that asks) is something nobody is there to answer."""
    return ['--tools', 'Bash,Read,Edit,Write', '--setting-sources', 'project,local', '--strict-mcp-config'] \
        if C.run['lean'] else []


def agent_cmd(prompt: str, sid: str, model: str, idle: int) -> str:
    """The agent command line for one task. The Stop hook is this runner in --stop-hook mode."""
    stop = [{'hooks': [{'type': 'command',
                        'command': shlex.join([sys.executable, str(RUNNER), 'run', '--stop-hook',
                                               '--idle', str(idle)])}]}]
    return shlex.join([C.run['agent'], prompt, '--session-id', sid, '--permission-mode', 'bypassPermissions',
                       '--disallowedTools', 'AskUserQuestion', '--model', model, *lean(),
                       '--settings', json.dumps({'hooks': {'Stop': stop, 'StopFailure': stop}})])


def brief_for(tid: str, cwd: Path) -> str:
    P._cache.clear()
    try:
        return '\n'.join(P.brief(tid, root=cwd, plan_dir=cwd / os.path.relpath(C.plan_dir, C.root)))
    except SystemExit as e:
        return f'({RUNNER} plan brief {tid} produced nothing: {e})'


def prompt_for(tid: str, n: int, slots: int, cwd: Path, branch: str) -> str:
    """The first turn of a task's session: `[run] prompt` (a file) if set, else PROMPT, filled in.

    Placeholders a custom template may use: {tid} {n} {runner} {branch} {others} {earlier} {rules} {test}
    {journal} {extra} {brief}. Any other `{name}` is left as it is.
    """
    r = C.run
    journal = os.path.relpath(C.journal, C.root) if C.journal else ''
    wip = not git('rev-parse', '--verify', '-q', f'refs/heads/wip/{tid}').returncode
    vals = dict(
        tid=tid, n=n, runner=RUNNER, branch=branch,
        others=OTHERS if slots > 1 else '',
        earlier=(f'An earlier attempt that could not be merged is on wip/{tid} (`git log {branch}..wip/{tid}`, '
                 f'and the ledger line in {r["notes"]}/ledger.md says why). Read it before starting over.\n'
                 if wip else ''),
        rules=f'read {r["rules"]} first' if r['rules'] else 'the README, and AGENTS.md or CLAUDE.md if there is one',
        test=(f'The test gate is `{r["test"]}`. `done` runs it, and it must pass.' if r['test'] else
              'There is no test gate, so say in the commit message how you checked the work.'),
        journal=(f'\nWrite the task\'s journal as you go, in {journal}/<date>-{tid.lower()}-<slug>/: what you did, '
                 f'what you tried that failed, and under **Not verified** everything you could not check, with '
                 f'why (or `none`). A skipped check that is written down is useful; a silent one is a bug '
                 f'nobody will find.\n' if journal else ''),
        extra=f'\n{r["prompt_extra"].strip()}\n' if r['prompt_extra'] else '',
        brief=brief_for(tid, cwd),
    )
    template = (ROOT / r['prompt']).read_text(encoding='utf-8') if r['prompt'] else PROMPT
    return template.format_map(_Keep(vals))


class _Keep(dict):
    def __missing__(self, k: str) -> str:
        return '{' + k + '}'


def slot_env(n: int) -> list[str]:
    return ['AGENT_RUNNER=1', *[e.format(n=n) for e in C.run['slot_env']]]


def start(n: int, task, branch: str, model: str, idle: int, slots: int):
    tid = task[0]
    d = worktree(n, branch)
    git('reset', '-q', '--hard', cwd=d)
    git('clean', '-fdq', cwd=d)
    co = git('checkout', '-q', '-B', f'task/{tid}', branch, cwd=d)
    if co.returncode:  # e.g. another worktree still holds task/<ID>: never start an agent on the wrong branch
        log(f'slot {n}: checkout task/{tid} failed: {co.stderr.strip()[:200]}')
        return None
    sid = str(uuid.uuid4())
    prompt = prompt_for(tid, n, slots, d, branch)
    logfile = C.notes(f'slot{n}.log')
    since = logfile.stat().st_size if logfile.exists() else 0  # in append mode tell() is not that
    with open(logfile, 'a', encoding='utf-8') as f:
        f.write(f'\n=== {dt.datetime.now().isoformat(timespec="seconds")} {tid} session {sid}\n')
    pid = pane(f's{n}', d, agent_cmd(prompt, sid, model, idle), slot_env(n), logfile)
    log(f'slot {n}: {tid} ({task[1]}; {", ".join(sorted(task[2])) or "no files listed"})')
    return pid, sid, since


# --- merging a finished branch -------------------------------------------------

MERGE = threading.Lock()  # one merge into the shared branch at a time


def joinable(f: str) -> bool:
    """True when the runner may join both sides of a conflict in `f` itself (`[run] joinable`, globs).

    Only for files where a line is a whole record and two agents each added records: the task list and its
    archive, a changelog, a journal. Never prose, even prose that is only appended to. A union joins
    *lines*, and two sides that both reflowed one paragraph give it no line to agree on. It then stitches
    them into something that reads like a sentence and is not one, and a reader believes it. A paragraph
    needs reading, so it goes to a fix session.
    """
    return any(fnmatch.fnmatch(f, g) for g in C.run['joinable'])


def union(files: list[str], tid: str, cwd: Path) -> bool:
    """Join both sides of a conflict in every file `joinable` allows. Then, in the task list, drop a task
    line that came out twice and any TODO line whose task DONE.md already has."""
    todo, done = plan_rel('TODO.md'), plan_rel('DONE.md')
    for f in sorted(files, key=lambda f: f != done):  # DONE.md first: TODO.md reads it
        sides = []
        for stage in (2, 1, 3):  # ours, base, theirs
            t = C.notes(f'union.{stage}')
            t.write_text(git('show', f':{stage}:{f}', cwd=cwd).stdout, encoding='utf-8')
            sides.append(str(t))
        out = git('merge-file', '-p', '--union', *sides, cwd=cwd)
        if out.returncode < 0:
            return False
        text = out.stdout
        if f in (todo, done):
            gone = {m.group(1).rstrip('.') for l in (cwd / done).read_text(encoding='utf-8').splitlines()
                    if (m := ANY_TASK.match(l)) and '- [x]' in l} if f == todo else set()
            mine = git('show', f'task/{tid}:{f}', cwd=cwd).stdout.splitlines()
            kept, seen = [], {}
            for l in text.split('\n'):
                if m := ANY_TASK.match(l):
                    k = m.group(1).rstrip('.')
                    if k in gone:
                        continue
                    if k in seen:  # keep the branch's copy of its own task, the target's copy of the rest
                        if (k == tid) == (l in mine):
                            kept[seen[k]] = l
                        continue
                    seen[k] = len(kept)
                kept.append(l)
            text = '\n'.join(kept)
        (cwd / f).write_text(text, encoding='utf-8')
        git('add', f, cwd=cwd)
    return True


FIXER = """A merge of task/{tid} into {branch} is half-done in this checkout and git could not finish it \
by itself. Finish it. Nobody will answer questions: decide, and say what you decided.

Conflicted files:
{files}

What this is: an unattended run gave several agents a task each, on their own branch, and is merging them \
one at a time. The runner joins conflicts in record-per-line files itself; this one needs reading, which is \
why you are here instead of a human.

1. `git status` and `git diff` to see it, and `git log {branch}..task/{tid}` for what the task did. Resolve \
every conflict so that **both sides' intent survives** — two agents each did work somebody wanted, and a \
resolution that silently drops one of them is the worst outcome available. Watch for one side being simply \
older: a branch that predates a paragraph on {branch} must not revert it. Where they genuinely cannot both \
hold, keep the one that matches {branch}'s current direction and say so.
2. Change nothing the merge did not touch. You are not reviewing the code and you are not doing task \
{tid}'s work: a conflict is all that is in front of you. Never hand-edit a task checkbox; if a side ticked \
or blocked a task by hand, keep the plan tool's form of it.
3. Then `git commit --no-edit` to land the merge, and stop. Do not push. Do not run the test suite: the \
runner runs it as soon as you are done. Do not merge, rebase or delete anything else, do not `git stash`, \
and do not touch the other worktrees under {slots_dir}.
4. If it cannot be resolved honestly — the two sides contradict each other and picking needs a human — run \
`git merge --abort` and say why in one line. That is a real answer, not a failure.

What happened on earlier merges in this run (the ledger's tail):
{history}
"""


def fix_cmd(prompt: str) -> list[str]:
    """A fix session: one prompt, one answer, no session to keep — `-p`, so nothing types into a pane."""
    return [C.run['agent'], '-p', prompt, '--permission-mode', 'bypassPermissions',
            '--disallowedTools', 'AskUserQuestion', '--model', C.run['fix_model'], *lean()]


def fix_merge(tid: str, branch: str, files: list[str], cwd: Path) -> str | None:
    """Give a conflict the join cannot do to a fresh agent session, in `cwd`. None when it landed.

    One session per merge, run to completion while the caller waits: the merge lock is held anyway, so
    there is nothing to gain from doing it in the background. Each one starts with an empty context and the
    ledger's tail, so the twentieth costs what the first did. (See the README for why this replaced a
    long-lived "master" session.)

    Never fatal. A fixer that fails, times out, aborts or is not installed leaves the merge for the caller
    to abort, and the task is left for a human, which is what used to happen to every conflict.
    """
    if not C.run['fix_merges']:
        return 'conflicts a join cannot resolve, and [run] fix_merges is off'
    led = C.notes('ledger.md')
    history = ''.join(led.read_text(encoding='utf-8').splitlines(True)[-12:]) if led.exists() else ''
    prompt = FIXER.format(tid=tid, branch=branch, files='\n'.join(f'  {f}' for f in files),
                          slots_dir=SLOTS_DIR, history=history.strip() or '(nothing yet: this is the first)')
    logfile = C.notes('fixer.log')
    log(f'{tid}: conflicts in {", ".join(files)} need reading — handing them to a fix session')
    with open(logfile, 'a', encoding='utf-8') as fh:
        fh.write(f'\n=== {dt.datetime.now().isoformat(timespec="seconds")} {tid} {", ".join(files)}\n')
        fh.flush()
        try:
            r = sp.run(fix_cmd(prompt), cwd=str(cwd), stdout=fh, stderr=sp.STDOUT, stdin=sp.DEVNULL,
                       timeout=C.run['fix_timeout'])
        except FileNotFoundError:
            return f'no agent command to fix the conflicts with ([run] agent = {C.run["agent"]!r})'
        except sp.TimeoutExpired:
            note(f'{tid}: the fix session timed out after {C.run["fix_timeout"]}s')
            return f'the fix session ran past {C.run["fix_timeout"]}s'
    if git('rev-parse', '--verify', '-q', 'MERGE_HEAD', cwd=cwd).returncode == 0:
        return f'the fix session did not finish the merge (exit {r.returncode}); see {logfile}'
    if git('merge-base', '--is-ancestor', f'task/{tid}', 'HEAD', cwd=cwd).returncode:
        return f'the fix session aborted the merge; its reason is in {logfile}'
    note(f'{tid}: conflicts in {", ".join(files)} resolved by a fix session')
    log(f'{tid}: the fix session resolved {", ".join(files)} and committed the merge')
    return None


def untestable(f: str) -> bool:
    """A change the test gate cannot see: markdown. A merge that differs from what the branch tested only
    in these is not retested."""
    return f.endswith('.md')


def merge(tid: str, branch: str) -> str | None:
    """Merge task/<tid> into the shared branch: merge, archive ticks, test, land, push, delete the branch.

    The merge is built and tested in its own worktree (`<repo>-slots/merge`), and the shared branch only
    moves once the tests pass. So the main checkout never holds an untested merge: whoever works there keeps
    committing the whole time, nothing is reset under them, and their edits are never stashed (a stash pop
    that clashed once left somebody's work in a stash nobody looked at).

    Returns None when it landed, else why it was left alone. The shared branch is then as it was, and the
    task branch is still there.
    """
    with MERGE:
        d = worktree('merge', branch)
        try:
            for attempt in range(3):
                git('merge', '--abort', cwd=d), git('reset', '-q', '--hard', cwd=d), git('clean', '-fdq', cwd=d)
                base = git('rev-parse', branch).stdout.strip()
                git('checkout', '-q', '--detach', base, cwd=d)
                msg = ['-m', f"Merge branch 'task/{tid}'"]
                if git('merge', '--no-edit', *msg, f'task/{tid}', cwd=d).returncode:
                    files = git('diff', '--name-only', '--diff-filter=U', cwd=d).stdout.split()
                    if all(map(joinable, files)) and union(files, tid, d):
                        git('commit', '-q', '--no-edit', cwd=d)
                        log(f'{tid}: joined both sides of {", ".join(files)}')
                    else:
                        # start the conflict again from a clean state (a refused join may have written some
                        # of its files) and give it to a session that can read it
                        git('merge', '--abort', cwd=d)
                        git('merge', '--no-edit', *msg, f'task/{tid}', cwd=d)
                        if why := fix_merge(tid, branch, files, d):
                            return why
                P._cache.clear()
                P.archive(d / plan_rel('TODO.md'), d / plan_rel('DONE.md'))
                plan_files = [plan_rel('TODO.md'), plan_rel('DONE.md')]
                if git('status', '--porcelain', '--', *plan_files, cwd=d).stdout.strip():
                    git('commit', '-qm', f'{tid}: archive ticked tasks', '--', *plan_files, cwd=d)
                merged = git('rev-parse', 'HEAD', cwd=d).stdout.strip()
                # `done` already passed the gate on the branch: rerun it only if the merged code differs
                # from what it tested (a markdown-only difference is not code)
                if not all(map(untestable, git('diff', '--name-only', f'task/{tid}', merged, cwd=d).stdout.split())):
                    rc, out = gate(d)
                    if rc:
                        return 'the tests fail after the merge: ' + ' / '.join(out.splitlines()[-4:])[:400]
                moved = git('diff', '--name-only', base, branch).stdout.split()
                if attempt < 2 and not all(map(untestable, moved)):
                    log(f'{tid}: {branch} got code commits during the tests; testing the merge again')
                    continue
                why = land(tid, branch, merged)
                if why == 'conflict' and attempt < 2:
                    continue
                if why:
                    return why
                break
        finally:
            git('merge', '--abort', cwd=d)
            git('checkout', '-q', '--detach', cwd=d)
        git('branch', '-d', f'task/{tid}')
        line = next((l for l in plan_text(branch) if f'**{tid}**' in l), '')
        state = 'blocked' if line.startswith('- [~]') else 'part' if line else 'ticked'
        note(f'{tid}: merged, {state}')
        log(f'{tid}: merged, {state}')
        reopen_landed(branch, tid)  # before the push, so the reopen goes out with the merge
        published(tid, branch)
        return None


def land(tid: str, branch: str, merged: str) -> str | None:
    """Move the shared branch in the main checkout to the tested merge: seconds, not a test run.

    None when it landed, 'conflict' when the branch's new commits clash with it (the caller builds it again
    on top), else why it could not. Uncommitted edits there are never moved aside: git refuses, before it
    starts, a merge that would change a file somebody is editing, so this waits for them to commit.
    """
    t0 = time.time()
    while git('diff', '--name-only', '--diff-filter=U').stdout.strip() or \
            git('rev-parse', '--verify', '-q', 'MERGE_HEAD').returncode == 0:
        if time.time() - t0 > 60 * 60:
            return 'the main checkout has a merge or unmerged paths of its own, for 60 min'
        time.sleep(10)
    cur = git('branch', '--show-current').stdout.strip()
    if cur != branch and git('checkout', '-q', branch).returncode:
        return f'the main checkout is on {cur or "a detached HEAD"} and would not switch to {branch}'
    msg = ['-m', f'{tid}: the tested merge, onto commits {branch} got during the tests']
    while git('merge', '-q', *msg, merged).returncode and \
            git('rev-parse', '--verify', '-q', 'MERGE_HEAD').returncode:
        if time.time() - t0 > 60 * 60:
            return 'uncommitted edits in the main checkout to files the merge changes, for 60 min'
        time.sleep(10)
    if git('rev-parse', '--verify', '-q', 'MERGE_HEAD').returncode == 0:
        files = git('diff', '--name-only', '--diff-filter=U').stdout.split()
        if not all(map(joinable, files)) or not union(files, tid, ROOT):
            git('merge', '--abort')
            return 'conflict'
        git('commit', '-q', '--no-edit')
    if git('merge-base', '--is-ancestor', merged, 'HEAD').returncode:
        return f'the merge did not land in {branch}; merge it again'
    return None


def published(tid: str, branch: str) -> None:
    """After a merge that passed the test gate: push the shared branch, then drop the task's remote branch.

    Pushed here, and only after the gate, which is what makes publishing it unattended defensible. A failed
    push is logged, not fatal: the merge landed locally and the next one pushes both. With `[git] push_merge
    = false` the merge stays local and the `git push` to run is logged instead; `drop_if_merged` then keeps
    the task branch on the remote until the shared branch there has it.
    """
    if C.push_merge:
        if out := push(ROOT, branch, shared=True):
            log(f'{tid}: {out}')
    elif C.push_remote:
        log(f'{tid}: merged, not pushed ([git] push_merge is off): git push {C.push_remote} {branch}')
    if out := drop_if_merged(ROOT, f'task/{tid}'):
        log(f'{tid}: {out}')


REOPENED: set[str] = set()  # tasks `reopen_landed` put back to [ ]: `cmd_run` lets them be tried again
BOX = re.compile(r'^- \[(.)\] \*\*([^*\s]+)\*\*')
IDLE = 'run idle: no task it may start; waiting for TODO.md to change (Ctrl-C or ./run stop to end it)'


def retry_reopened(tried: set[str], closed: set[str], branch: str) -> None:
    """Put back in the pool every tried task whose line has closed and opened again since it was tried.

    `tried` keeps a task from being started twice in a run, which is right for one that ended still open
    (it failed: a human looks next) and wrong for one that blocked and was then unblocked by hand — that is
    new information, and a run that stays up for days would otherwise never try it again. `closed` is the
    tried tasks seen blocked or gone from TODO.md since; one seen open again after that is retried.
    """
    if not tried:
        return
    box = {m.group(2): m.group(1) for l in plan_text(branch) if (m := BOX.match(l))}
    for t in list(tried):
        if box.get(t) != ' ':
            closed.add(t)
        elif t in closed:
            tried.discard(t)
            closed.discard(t)
            log(f'{t}: open again since it was tried; back in the pool')


def reopen_landed(branch: str, why: str) -> None:
    """Unblock what a merge freed (`plan.reopen`) and commit it, in the main checkout, holding MERGE.

    Without it, a task blocked on "X is not merged yet" stays blocked until a human reads the prose: on
    2026-10-20 five did, through the very merges that freed them. Left alone when TODO.md has edits nobody
    committed (somebody mid-edit), so it never commits theirs; the next merge tries again.
    """
    rel = plan_rel('TODO.md')
    if git('branch', '--show-current').stdout.strip() != branch or git('status', '--porcelain', '--', rel).stdout.strip():
        return
    P._cache.clear()
    if not (got := P.reopen(ROOT / rel)):
        return
    names = ', '.join(t for t, _ in got)
    if git('commit', '-qm', f'Plan: reopen {names} ({why} landed what they waited on)', '--', rel).returncode:
        git('checkout', '-q', '--', rel)
        return
    REOPENED.update(t for t, _ in got)
    for t, ids in got:
        note(f'{t}: reopened, {", ".join(ids)} landed')
        log(f'{t}: reopened, {", ".join(ids)} landed')


def finish(tid: str, n: int, sid: str, branch: str) -> None:
    """After a slot's session: merge its branch, or park it as wip/<ID> and say why."""
    commits = git('log', '--format=%s', f'{branch}..task/{tid}').stdout.splitlines()
    if not commits:
        git('branch', '-D', f'task/{tid}')
        note(f'{tid}: no commits — nothing to merge')
        log(f'{tid}: no commits — nothing to merge')
        return
    if not (why := merge(tid, branch)):
        return
    note(f'{tid}: LEFT FOR A HUMAN — {why}')
    log(f'{tid}: LEFT FOR A HUMAN — {why}. Its {len(commits)} commits: {" / ".join(commits)[:300]}')
    # Parked as wip/<ID>: a task/<ID> ahead of the branch reads as finished-and-waiting to `pick`, which
    # would then skip the task for good. As wip/ the task can start again, with the old attempt to read.
    if not git('branch', '-M', f'task/{tid}', f'wip/{tid}').returncode:
        log(f'{tid}: its branch is parked as wip/{tid}; the task stays open and can start again')
        if out := push(ROOT, f'wip/{tid}'):  # the one copy of that work: get it off this disk
            log(f'{tid}: {out}')


# --- watching a session --------------------------------------------------------

def transcript(sid: str) -> str | None:
    return next(iter(glob.glob(os.path.expanduser(f'~/.claude/projects/*/{sid}.jsonl'))), None)


def stats(sid: str) -> str:
    """'N min, N calls, context Nk first, Nk peak' for the exit line. Watch the peak over a run: if it keeps
    creeping up, or more tasks come back blocked, the tasks are too big."""
    calls, ctx, ts = 0, [], []
    try:
        for l in open(transcript(sid) or os.devnull, encoding='utf-8', errors='replace'):
            d = json.loads(l)
            ts += [d['timestamp']] if 'timestamp' in d else []
            if d.get('type') == 'assistant' and (u := d.get('message', {}).get('usage')):
                calls += 1
                ctx.append(sum(u.get(k, 0) for k in ('input_tokens', 'cache_read_input_tokens',
                                                     'cache_creation_input_tokens')))
    except (OSError, ValueError, KeyError):
        pass
    if not ctx or not ts:
        return 'no transcript'
    span = (dt.datetime.fromisoformat(ts[-1].replace('Z', '+00:00')) -
            dt.datetime.fromisoformat(ts[0].replace('Z', '+00:00')))
    return f'{int(span.total_seconds()) // 60} min, {calls} calls, context {ctx[0] // 1000}k first, {max(ctx) // 1000}k peak'


def stalled(pid: int, sid: str, limit: int) -> str | None:
    """Why a live session looks stuck, else None: quiet for `limit` seconds with no tool running (a prompt or
    a dialog the idle hook never sees), or quiet for longer than the Bash timeout even with one (a hung tool).
    """
    t = transcript(sid)
    quiet = time.time() - os.path.getmtime(t) if t and os.path.exists(t) else 0
    busy = sp.run(['pgrep', '-P', str(pid)], capture_output=True).returncode == 0
    if quiet > 65 * 60 or (quiet > limit and not busy):
        return f'no transcript activity for {int(quiet // 60)} min' + \
               (' with a tool still running' if busy else ' at a prompt')
    return None


LIMIT = re.compile(r'limit\D{0,12}resets? (\d+(?::\d+)?\s?[ap]m)', re.I)


def limit_only(sid: str, slot_log: Path, since: int) -> dt.datetime | None:
    """If the session did nothing but hit the usage limit: discard its transcript, return the reset time.

    A limited session produced no work, so counting it as an attempt would quietly drop the task from the
    night; and keeping its transcript would make the next run resume a session that never started.
    """
    t = transcript(sid)
    text = open(t, encoding='utf-8', errors='replace').read() if t else ''
    try:
        with open(slot_log, encoding='utf-8', errors='replace') as f:
            f.seek(since)
            text += f.read()
    except OSError:
        pass
    m = LIMIT.findall(text)
    if not m or '"type":"tool_use"' in text:
        return None
    if t:
        os.remove(t)
        shutil.rmtree(t[:-6], ignore_errors=True)  # and its sidecar dir, if this build keeps one
    s = m[-1].replace(' ', '').lower()
    when = dt.datetime.strptime(s, '%I:%M%p' if ':' in s else '%I%p')
    now = dt.datetime.now()
    at = now.replace(hour=when.hour, minute=when.minute, second=0, microsecond=0)
    if at < now - dt.timedelta(minutes=10):
        at += dt.timedelta(days=1)
    return max(at, now)


_weekly = [-1e9, None]


def weekly() -> float | None:
    """The account's 7-day usage %, from the endpoint Claude Code's `/usage` reads (the local login's OAuth
    token; costs no tokens), checked at most every 5 minutes. None when it cannot be read: "don't cap"."""
    if time.time() - _weekly[0] < 300:
        return _weekly[1]
    import urllib.request
    try:
        tok = json.load(open(os.path.expanduser('~/.claude/.credentials.json')))['claudeAiOauth']['accessToken']
        req = urllib.request.Request('https://api.anthropic.com/api/oauth/usage',
                                     headers={'Authorization': f'Bearer {tok}',
                                              'anthropic-beta': 'oauth-2025-04-20'})
        _weekly[1] = json.load(urllib.request.urlopen(req, timeout=10))['seven_day']['utilization']
    except Exception:
        _weekly[1] = None
    _weekly[0] = time.time()
    return _weekly[1]


# --- the idle stop hook --------------------------------------------------------

def stop_hook(idle: int) -> int:
    """Stop hook for a session this runner started: end it once it has been idle for `idle` seconds.

    A finished agent otherwise sits at its prompt forever, and the loop never starts the next task. "Idle"
    means no new user or tool-result entry in the transcript, so typing into the pane keeps the session
    alive: you can take one over by hand. A session with a background task running gets a much longer
    grace (`AGENT_RUNNER_IDLE_BG`, 1800 s), because a background task normally ends and wakes it.

    A usage limit is deliberately *not* idleness: Claude Code prints "continuing automatically at <reset>"
    and resumes by itself, so the waiter leaves such a session alone.
    """
    try:
        ev = json.load(sys.stdin)
    except Exception:
        return 0
    t = ev.get('transcript_path')
    if not t or not os.path.exists(t):
        return 0
    if ev.get('background_tasks'):
        idle = max(idle, int(os.environ.get('AGENT_RUNNER_IDLE_BG', 1800)))
    try:
        sp.Popen([sys.executable, str(RUNNER), 'run', '--stop-waiter', str(os.getppid()), t,
                  str(_user_entries(t)), str(idle)],
                 stdin=sp.DEVNULL, stdout=sp.DEVNULL, stderr=sp.DEVNULL, start_new_session=True)
    except Exception:
        pass
    return 0


def _user_entries(t: str) -> int:
    try:
        with open(t, encoding='utf-8', errors='replace') as f:
            return sum(1 for l in f if '"type":"user"' in l)
    except OSError:
        return -1


def stop_waiter(pid: int, t: str, n: int, idle: int) -> int:
    time.sleep(idle)
    if _user_entries(t) != n:
        return 0  # the human typed, or a tool came back: the session is alive, leave it
    try:
        text = open(t, encoding='utf-8', errors='replace').read()
    except OSError:
        text = ''
    tail = text[text.rfind('continuing automatically'):] if 'continuing automatically' in text else ''
    if tail and '"tool_use"' not in tail:
        return 0  # waiting out a usage limit; Claude Code resumes it at the reset
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass
    return 0


# --- sequential run ------------------------------------------------------------

def capped(force: bool) -> float | None:
    """The weekly usage % when it is at or past `[run] weekly_max` (and not --force), else None."""
    if force or C.run['agent'] != 'claude':
        return None
    w = weekly()
    return w if w is not None and w >= C.run['weekly_max'] else None


def sequential(branch: str, model: str, idle: int, pause: int, force: bool, once: bool = False) -> int:
    """No tmux, or one slot: one session at a time, in this checkout, on the branch it has out.

    Honest about the trade: no worktree, so a task commits straight onto the branch you are on and no merge
    happens. `done` ran the gate before it committed, so with `push_merge` the branch is pushed after each
    task. `once` stops after the first task, which is how to try the runner before a night. With nothing to
    start it does not exit: it logs `run idle` once and looks at TODO.md again every 30 s.
    """
    here = git('branch', '--show-current').stdout.strip() or branch
    log(f'sequential run on {here} ({"one task, then stop" if once else "one session at a time"}, '
        f'committing in this checkout)')
    tried: set[str] = set()
    closed: set[str] = set()
    idle_said = False
    while not stopping():
        retry_reopened(tried, closed, here)
        if not (task := pick({}, tried, 'p', here)):
            if once:
                break
            if not idle_said:
                log(IDLE)
                idle_said = True
            time.sleep(30)
            continue
        if idle_said:
            log(f'run busy: new work ({task[0]})')
            idle_said = False
        if (w := capped(force)) is not None:
            log(f'weekly usage {w}% >= {C.run["weekly_max"]}%: waiting for the reset (--force to go on)')
            time.sleep(300)
            continue
        tid = task[0]
        sid = str(uuid.uuid4())
        before = git('rev-parse', 'HEAD').stdout.strip()
        log(f'{tid}: starting ({task[1]})')
        sp.run(agent_cmd(prompt_for(tid, 1, 1, ROOT, here), sid, model, idle), shell=True, cwd=str(ROOT),
               env={**os.environ, **dict(e.split('=', 1) for e in slot_env(1))})
        log(f'{tid}: session ended ({stats(sid)})')
        if C.run['on_exit']:
            sp.run(C.run['on_exit'], shell=True, cwd=str(ROOT), capture_output=True)
        if r := limit_only(sid, C.notes('slot1.log'), 0):
            log(f'{tid}: only hit the usage limit; sleeping until {r:%H:%M}')
            time.sleep(max(0, (r - dt.datetime.now()).total_seconds()) + pause)
            continue
        tried.add(tid)
        if git('rev-parse', 'HEAD').stdout.strip() != before:
            note(f'{tid}: committed on {here}')
            with MERGE:
                reopen_landed(here, tid)
            tried -= REOPENED
            REOPENED.clear()
            if C.push_merge and (out := push(ROOT, here, shared=True)):
                log(f'{tid}: {out}')
        if once:
            log(f'{tid}: done (once)')
            return 0
        time.sleep(pause)
    C.notes('STOP').unlink(missing_ok=True)
    log('sequential run done: ' + ('nothing it may start (once)' if once else 'stop asked for'))
    return 0


# --- the loop ------------------------------------------------------------------

def dry_run(slots: int, mode: str, branch: str) -> int:
    """What `slots` free slots would start right now, in order, and why the rest of the open tasks wait."""
    running: dict = {}
    for n in range(1, slots + 1):
        if not (t := pick(running, set(), mode, branch)):
            break
        running[n] = t
        print(f'slot {n}: {t[0]}  ({t[1]}; {", ".join(sorted(t[2])) or "no files listed"})')
    if not running:
        print('nothing to start: every open task is blocked, waiting on another, or already finished')
    can = {t[0] for t in tasks(branch)}
    ls = plan_text(branch)
    waits = [m.group(1) for l in ls if (m := TASK.match(l)) and m.group(1) not in can]
    blocked = [m.group(1) for l in ls if (m := ANY_TASK.match(l)) and l.startswith('- [~]')]
    if waits:
        print(f'waiting on an (after …), a subtask or Stretch: {", ".join(waits)}')
    if blocked:
        print(f'blocked: {", ".join(blocked)}')
    return 0


def cmd_run(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog='run run', description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('slots', nargs='?', default=None,
                    help="how many agents at once (default [run] slots), or 'once' for one task then stop")
    ap.add_argument('--mode', choices=['p', 'd'], default=None,
                    help='p = plan order, overlapping files allowed; d = different files (default [run] mode)')
    ap.add_argument('--force', action='store_true', help='keep starting tasks past the weekly usage cap')
    ap.add_argument('--idle', type=int, default=None, help='seconds of quiet before a session is ended')
    ap.add_argument('--stall', type=int, default=None, help='seconds of quiet that count as stalled')
    ap.add_argument('--pause', type=int, default=None, help='seconds between a session ending and the next')
    ap.add_argument('--model', default=None, help='the agent model (default [run] model)')
    ap.add_argument('--no-tmux', action='store_true', help='force the single sequential session')
    ap.add_argument('--dry-run', action='store_true', help='print what would start, and start nothing')
    ap.add_argument('--stop-hook', action='store_true', help=argparse.SUPPRESS)
    ap.add_argument('--stop-waiter', nargs=4, metavar=('PID', 'TRANSCRIPT', 'N', 'IDLE'), help=argparse.SUPPRESS)
    a = ap.parse_args(argv)

    if a.stop_hook:  # these two run inside an agent session and need no repository
        return stop_hook(a.idle or 90)
    if a.stop_waiter:
        pid, t, n, idle = a.stop_waiter
        return stop_waiter(int(pid), t, int(n), int(idle))

    init()
    r = C.run
    once = a.slots == 'once'
    try:
        slots = 1 if once else int(a.slots or r['slots'])
    except ValueError:
        ap.error(f"slots must be a number or 'once', not {a.slots!r}")
    mode = a.mode or r['mode']
    idle, stall, pause = a.idle or r['idle'], a.stall or r['stall'], a.pause or r['pause']
    model = a.model or r['model']

    branch = default_branch()
    if git('rev-parse', '--verify', '--quiet', branch).returncode:
        print(f'no branch {branch!r} to merge into — commit something first', file=sys.stderr)
        return 2
    if a.dry_run:
        return dry_run(slots, mode, branch)

    if stopping():  # left by a run that was killed before it saw it; a stop is for the run that is up
        C.notes('STOP').unlink(missing_ok=True)
        log('cleared a stop request left by an earlier run')
    have_tmux = shutil.which('tmux') is not None
    if once or a.no_tmux or not have_tmux or slots <= 1:
        if not have_tmux and not a.no_tmux:
            log('tmux is not installed: falling back to one sequential session '
                '(install tmux for parallel slots, panes you can attach to, and worktrees)')
        return sequential(branch, model, idle, pause, a.force, once)
    if not os.environ.get('TMUX'):
        print(f'Run me inside tmux, so the sessions get panes you can attach to:\n'
              f'    tmux new -s runner {RUNNER} run {slots} --mode {mode}', file=sys.stderr)
        return 2

    if sys.stdin.isatty():
        threading.Thread(target=read_keys, daemon=True).start()
        log('type s + Enter here to stop gently (the running tasks finish and merge first); s again: undo')
    running: dict[int, tuple] = {}
    procs: dict[int, tuple] = {}
    tried: set[str] = set()
    closed: set[str] = set()  # see retry_reopened
    idle_said = False
    free_at = {n: dt.datetime.min for n in range(1, slots + 1)}
    merging: list[threading.Thread] = []
    stall_said: set[str] = set()
    cap_said = stop_said = False
    log(f'run: {slots} slots, mode {mode}, merging into {branch}' +
        (f', weekly usage {weekly()}%' if not a.force and r['agent'] == 'claude' else ''))

    # branches a previous run never merged (it was stopped, or a session ended while nothing watched)
    held = {l.removeprefix('branch refs/heads/') for l in
            git('worktree', 'list', '--porcelain').stdout.splitlines() if l.startswith('branch ')}
    open_ids = {m.group(1) for l in plan_text(branch) if (m := TASK.match(l))}
    for b in git('branch', '--format=%(refname:short)', '--list', 'task/*').stdout.split():
        tid = b.removeprefix('task/')
        if b in held or tid not in open_ids:
            continue
        if git('log', '--format=%s', f'{branch}..{b}').stdout.strip():
            log(f'{tid}: finished while no run was up; merging it now')
            tried.add(tid)
            t = threading.Thread(target=finish, args=(tid, 0, '(unknown)', branch))
            t.start()
            merging.append(t)
    with MERGE:  # blocks freed by merges made while no run was up
        reopen_landed(branch, 'a merge before this run')
    for n in free_at:  # idle slots must let go of old task/<ID> branches, or start() cannot take them
        if (SLOTS_DIR / f's{n}').is_dir():
            git('checkout', '-q', '--detach', cwd=SLOTS_DIR / f's{n}')

    while True:
        for n in list(free_at):
            if n in procs and not alive(procs[n][0]):
                (pid, sid, since), task = procs.pop(n), running.pop(n)
                log(f'slot {n}: {task[0]} exited ({stats(sid)})')
                if r['on_exit']:
                    sp.Popen(r['on_exit'], shell=True, cwd=str(SLOTS_DIR / f's{n}'),
                             env={**os.environ, **dict(e.split('=', 1) for e in slot_env(n))},
                             stdout=sp.DEVNULL, stderr=sp.DEVNULL)
                if reset := limit_only(sid, C.notes(f'slot{n}.log'), since):
                    free_at[n] = reset + dt.timedelta(seconds=pause)
                    log(f'slot {n}: {task[0]} only hit the usage limit; transcript dropped, the task goes '
                        f'back in the pool and the slot sleeps until {reset:%H:%M}')
                else:
                    tried.add(task[0])  # one attempt per run: ticked, blocked or failed, a human looks next
                    git('checkout', '-q', '--detach', cwd=SLOTS_DIR / f's{n}')
                    t = threading.Thread(target=finish, args=(task[0], n, sid, branch))
                    t.start()
                    merging.append(t)
                    free_at[n] = dt.datetime.now() + dt.timedelta(seconds=pause)
            if n in procs and procs[n][1] not in stall_said and \
                    (why := stalled(procs[n][0], procs[n][1], stall)):
                stall_said.add(procs[n][1])
                log(f'slot {n}: {running[n][0]} looks stalled ({why}); attach to pane s{n} to see')
                print('\a', end='', flush=True)
            if n not in procs and dt.datetime.now() >= free_at[n]:
                if not stopping():
                    stop_said = False  # taken back (s again, or the STOP file removed)
                else:
                    if not stop_said:
                        log('stop asked for: no new tasks; exiting once the running ones are merged')
                        stop_said = True
                    continue
                if (w := capped(a.force)) is not None:
                    if not cap_said:
                        log(f'weekly usage {w}% >= {r["weekly_max"]}%: no new tasks until it resets '
                            f'(restart with --force to go on now)')
                        cap_said = True
                    continue
                cap_said = False
                if task := pick(running, tried, mode, branch):
                    if p := start(n, task, branch, model, idle, slots):
                        procs[n], running[n] = p, task
                        if idle_said:
                            log(f'run busy: new work ({task[0]})')
                            idle_said = False
                    else:
                        tried.add(task[0])
        retry_reopened(tried, closed, branch)
        if REOPENED:
            tried -= REOPENED  # a task reopened by a merge is a new attempt, not the one that blocked
            REOPENED.clear()
        merging = [t for t in merging if t.is_alive()]
        take_keys()
        if stopping() and not procs and not merging:  # a slot asleep until a usage reset does not hold it
            how = stopped_by()
            C.notes('STOP').unlink(missing_ok=True)
            log(f'run stopped ({how}); tried this run: {", ".join(sorted(tried)) or "none"}')
            return 0
        quiet = not procs and not merging and all(dt.datetime.now() >= t for t in free_at.values())
        # Idle, never exit: tasks a human or a session commits later start without anyone restarting the
        # run. Said once, and only with nothing running or merging: on 2026-10-20 a run that exited while
        # idle left two slots running and three finished branches unmerged. A script waiting on the run
        # watches run.log for `run idle`; the process itself ends only on Ctrl-C or `./run stop`.
        if quiet and not idle_said and not pick(running, tried, mode, branch):
            log(f'tried this run: {", ".join(sorted(tried)) or "none"}')
            log(IDLE)
            idle_said = True
        time.sleep(10)


def cmd_stop(argv: list[str]) -> int:
    """`./run stop`: the running sessions finish and merge, nothing new starts, and the run exits."""
    init()
    ask_stop('./run stop')
    print(f'asked the run to stop ({C.notes("STOP")}); it exits once the running tasks are merged')
    return 0
