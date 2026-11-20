"""`./run run`: keep N agent sessions working through the task list, for as long as the work lasts.

Most of a long project is small, checkable steps that need no human in the loop: they need the backlog,
the tests and a commit. This is the loop that does that. It picks the next task nobody is on, opens a git
worktree and a terminal for it (a tmux pane; on Windows a Windows Terminal tab or a console window), and
starts an agent session with the task's brief already pasted into the first turn. It waits for the session to finish, merges and tests the branch, pushes it, and starts the
next task.

    ./run run once            one task, then stop (the way to try it the first time)
    ./run run                 [run] slots agents (3), in tmux
    ./run run 5               5 agents
    ./run run 1               one agent, in a worktree and a pane like any count (no tmux: in this checkout)
    ./run run --dry-run 4     print what 4 free slots would start now, and start nothing
    ./run stop                finish what is running, start nothing new, then exit (or type s + Enter
                              in the runner's pane; ? + Enter there lists every key)
    ./run stop --force        end the sessions now (each resumes in the next run), then exit
    (every form but `once` stays up when the work runs out: it logs `run idle` and waits for more)

docs/REFERENCE.md describes each mechanism. In short:

* **picking** (`tasks`, `pick`) goes down TODO.md in order and skips
  - blocked tasks and split parents,
  - tasks whose `| after: X, Y` names a task not done yet,
  - the Stretch and Parked sections, anything tried this run (until its line is edited), and branches waiting to be merged,
  - a task parked twice (wip/<ID>, wip/<ID>-2): the run blocks it on a person instead (`block_parked`).

  Siblings never run together. An ordered section runs one task at a time. Two tasks never run on the same
  files: a line's `| files:` and, for a task running, the files it has touched; a finished one waiting to merge
  holds only the files it changed.
* **one worktree per slot**, kept warm between tasks, with `[run] links` symlinked in;
* **an idle stop** (the Stop hook): a finished session is ended once its transcript is quiet;
* **a usage limit is not a failed task**: the transcript is dropped and the slot sleeps to the reset;
* **a cut-off session resumes**: one ended by an API error (or, at startup, mid-turn) is resumed in its slot;
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
    --slot-shim JOB        run one slot's session in a Windows tab or console, its pid in a marker file

What depends on the OS is in `plat.py`; the terminals are `TmuxMux` and `ShimMux` below.
"""
from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import glob
import hashlib
import io
import json
import os
import re
import shlex
import shutil
import signal
import socket
import subprocess as sp
import sys
import tempfile
import threading
import traceback
import time
import urllib.parse
import uuid
import webbrowser
from contextlib import ExitStack, contextmanager, redirect_stdout
from pathlib import Path

from agent_runner import plan as P
from agent_runner import ci, gitops, plat, plansync

# The library API a wrapping project may call; these change only in a major version. `cmd_run(argv)` and
# `cmd_stop(argv)` are the commands; `PROMPT`, `FIXER` and `OTHERS` may be replaced before `cmd_run`.
__all__ = ['init', 'cmd_run', 'cmd_stop', 'pick', 'tasks', 'prompt_for', 'reopen_landed', 'retry_reopened',
           'ask_stop', 'stopping', 'cmd_resume', 'PROMPT', 'FIXER', 'OTHERS']
from agent_runner.config import RUNNER, Config, cfg, finished_mark, main_checkout, runner_cmd, ensure_local
from agent_runner.done import TESTED, gate
from agent_runner.gitops import _net, drop_if_merged, push, shared_name
from agent_runner.guide import SAFE_SHELL

TASK = re.compile(r'^- \[(.)\] \*\*([^*\s]+)\*\*(.*)')  # a top-level task line: its box, its id, the rest
TAG = '@runner'  # the tmux pane option a slot's pane is found by
RUN_TAG = '@runner-run'  # set on the runner's own pane to the main checkout it runs for: `attach` goes there
HIDDEN = [False]  # `run --hidden` on Windows: slot consoles start hidden (the background run)
REPO_TAG = '@runner-repo'  # the main checkout a pane's runner works for: two repos' runners share a tmux session
BOARD_TAG = '@runner-board'  # on the board's pane: "feed/run" (the runner feed) or "text/run" (since --board);
# "/run": it ends with the run (B13), so a board of an earlier version (plain "feed"/"text") is replaced

ROOT = Path('.')       # the main checkout; set by `init`
SLOTS_DIR = Path('.')  # `[run] home` (~/runs/<repo>/): s1, s2, …, and `merge`
C: Config


def init(root=None) -> Config:
    """Point the runner at the repository around `root` (default: the current directory)."""
    global ROOT, SLOTS_DIR, C
    ROOT = main_checkout(root)
    C = cfg(ROOT)
    SLOTS_DIR = C.slots_dir
    if not C.plan_external:  # the task list merges by task, in every merge of this repository
        P.install_driver(ROOT, [plan_rel('TODO.md'), plan_rel('DONE.md')])
    return C


PROMPT = """Unattended run: nobody will answer questions, so never ask one — decide, write down why, and go on.

Do task {tid} and nothing else. You are in a git worktree on branch task/{tid}: commit this repo's work here only. Never \
touch the main checkout, and never merge, rebase or push the main branch. {publish}
{others}{earlier}
Rules: {rules}. {test}
{journal}
Finish with `{runner} done {tid} "<commit message>"`. It runs the test gate, ticks the task, commits and \
pushes, and it refuses to tick when the gate fails. Run it, and any whole test suite, as a background command \
and wait for it to end: beside the other slots a gate can outlast your own command time limit, and one cut \
off there commits nothing. Never start a second one while the first still runs.

If you are stuck (a tool hangs, the same fix fails twice, it needs a human, about 20 minutes with no \
progress), commit what is solid and run `{runner} done {tid} "<msg>" --blocked "<why + what would unblock \
it>"`, then stop. If all it waits on is another task landing (its code is not on the main branch yet), add \
`--after <ID>[,<ID>]`, and the run reopens it the moment those merge. If it waits on a person, start WHY with \
what you ask of them: `CONFIRM: <what to check by hand>`, `DECIDE: <the question or choice>` or `BLOCKED: \
<the access, login or fix only a person can make>`, then one short line, and the link if there is one; it \
lists under Needs you until they answer. Before a `BLOCKED:` on access, check what this machine already has \
and try it: `gh auth status`, `wrangler whoami`, the service's own CLI login, `ssh -T`, and \
~/.claude/ACCESS.md if it exists; the `BLOCKED:` line then names the exact command that failed and its error \
(e.g. `wrangler OAuth login cannot change Workers Builds settings: Authentication error`).

A usage limit is not being stuck: do not block the task. The session waits for the reset and carries on.

Wait for and stop only processes you started, by the pid you kept (`$!`): `wait` on it, `kill` it. Never \
match processes by a command-line pattern (`pgrep -f`, `pkill -f`, `ps | grep`/`awk`, `killall`): a wait \
loop's pattern matches the loop itself and never ends, and every agent's command line holds this whole \
prompt, so a pattern kill can end the other sessions on this machine. Every wait gets a time limit \
(`timeout 600 <cmd>`, or a deadline in the loop): a loop waiting for a line that a dead process will never \
print runs for ever. Never search the whole disk (`find /`); look where the thing can be.

""" + SAFE_SHELL + """ Delete only inside your worktree.

{followups}
{extra}
The task's brief (`{runner} plan brief {tid}`) follows, so don't gather it again.

{brief}"""

FOLLOWUPS = """\
The task list is a tool, not a file to read whole: `{runner} plan` lists the tasks, `{runner} plan <ID>` \
shows one, and `{runner} plan add <KIND> "<text>" --files a,dir/** [--after ID] [--test name] [--pri LEVEL]` files a \
follow-up you find but must not do now: `--files` the files it will change (the run keeps running tasks apart \
by them), `--after` the ids it must wait for; the text is never read for files or ids. Never hand-edit a checkbox. KIND is the id letter for the kind of work: {kinds}. LEVEL is where it queues: \
`critical` only when it breaks or blocks other work (it goes ahead of everything, so its text says what it \
breaks); `normal`, the default, after the work a person queued; `low` for a check or a small tidy-up, after \
normal; `later` for big future work, parked for a person to schedule and never started by a run. To split \
your own task, give its id as KIND (`plan add P17 …` files P17a, P17b…), which keeps its place in the queue. `plan add` \
refuses (exit 3, nothing filed) when an open task looks like the same work: `plan note` that task instead, or add again \
with `--force` if it really is different work. A test that \
fails under load and passes alone is a bug in the test: if one gets in your way, make it robust (what it \
races, not a longer timeout), or file it as critical.
Reference material you write for later sessions (module lists, how-tos, findings) goes in the files \
`{runner} plan "<section>"` searches, under its own heading, not in the rules file every session loads.
"""

OTHERS = ('Other agents are working on other tasks at the same time, in other worktrees. Keep your changes '
          'local: add functions and new files, and don\'t move, rename or reformat code you did not come '
          'for, so the merges stay clean.\n')

PUBLISH = ('When your session ends, the runner merges your branch, tests the merge and publishes it. `{runner} '
           'done` pushes task/{tid} for you, which is the one copy of your work that is not on this disk. Commits '
           'you make in other repositories (a dependency or sibling repo the task needed) are pushed as usual; '
           'never publish beyond git (releases, uploads, stores) unless the task says to.')
NO_PUSH = ('When your session ends, the runner merges your branch and tests the merge. Pushing is off for this '
           'run: never run `git push`, here or in any other repository, and never publish anything else '
           '(releases, uploads, stores). A human reviews and pushes.')

# With `[git] push = false`, every agent session gets these as git config: any push to a URL of these kinds
# goes to a remote helper that does not exist, so it fails whatever command or repository it comes from.
NO_PUSH_URLS = ('https://', 'http://', 'ssh://', 'git://', 'git@', 'file://')


# --- small helpers -------------------------------------------------------------

# The runner's pane in colour (run.log stays plain): a terminal, not NO_COLOR, and on Windows only Windows Terminal
COLOR = sys.stdout.isatty() and not os.environ.get('NO_COLOR') and (not plat.WINDOWS or bool(os.environ.get('WT_SESSION')))
TONES = [  # first match wins: (regex on the message, SGR colour)
    (re.compile(r'LEFT FOR A HUMAN|STOPPED|fail|refused|error|parked|killed|ended pid|stall', re.I), '31'),  # red
    (re.compile(r'blocked|SUSPECT|conflict|waiting|usage limit|did not push|^!', re.I), '33'),       # yellow
    (re.compile(r'merged|pushed|passed|resolved|landed|run busy'), '32'),                             # green
    (re.compile(r'^slot \d+: \S+ \('), '34'),                                                      # blue: a start
    (re.compile(r'exited|run idle|not run again|dropped'), '90'),                                     # grey
]


def paint(stamp: str, msg: str) -> str:
    """`stamp msg` for a terminal: the time grey, the task id bold, the message in its tone."""
    tone = next((c for rx, c in TONES if rx.search(msg)), '0')
    msg = re.sub(r'^((?:slot \d+: )?)([A-Za-z]+\d+[a-z0-9]*)\b', '\\1\x1b[1m\\2\x1b[22m', msg, count=1)
    return f'\x1b[90m{stamp}\x1b[0m \x1b[{tone}m{msg}\x1b[0m'


def log(msg: str) -> None:
    stamp = dt.datetime.now().isoformat(timespec="seconds")
    line = f'=== {stamp} {msg}'
    print(paint(stamp, msg) if COLOR else line, flush=True)
    try:
        with open(C.notes('run.log'), 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except OSError:
        pass


NOTIFY = not os.environ.get('AGENT_RUNNER_NO_NOTIFY')  # alarm()'s tmux message and desktop notification


def banner(title: str, detail: str, bg: str = '41') -> None:
    """`title: detail` logged, and in colour a block in the runner's pane (red, or `bg`) that stands out."""
    import textwrap
    log(f'{title}: {detail}')
    if COLOR:
        body = [title.upper(), *textwrap.wrap(detail, 96)]
        w = max(map(len, body)) + 4
        bar = lambda t='': f'\x1b[1;97;{bg}m  {t.ljust(w - 2)}\x1b[0m'
        print('\n'.join([bar(), *map(bar, body), bar()]), flush=True)


def alarm(title: str, detail: str) -> None:
    """A stoppage only a person can clear (their uncommitted edits hold a tested merge, a usage cap): a red banner in the
    runner's pane, the bell, a tmux message and a desktop notification, so it is seen from across the room,
    not found in run.log hours later. The log line starts STOPPED."""
    banner(f'STOPPED: {title}', detail)
    print('\a', end='', flush=True)
    try:
        if not NOTIFY:
            return
        if os.environ.get('TMUX'):
            sp.run(['tmux', 'display-message', '-d', '15000', f'agent-runner STOPPED: {title}'],
                   capture_output=True, timeout=5)
        if shutil.which('notify-send'):
            sp.run(['notify-send', '-u', 'critical', '-a', 'agent-runner', f'agent-runner stopped: {title}', detail],
                   capture_output=True, timeout=5)
    except (OSError, sp.TimeoutExpired):
        pass


def git(*a: str, cwd=None, **kw) -> sp.CompletedProcess:
    return gitops.git(*a, cwd=cwd or ROOT, **kw)


def clean(d: Path, to: str = 'HEAD') -> None:
    """Worktree `d` exactly at `to`: no edits, no untracked files (ignored ones, a warm build, stay)."""
    git('reset', '-q', '--hard', to, cwd=d)
    git('clean', '-fdq', cwd=d)


def note(msg: str) -> None:
    """One line in `<notes>/ledger.md`: what happened to each branch. The fix sessions read its tail.

    One file for every path a branch can take, so a branch's history reads in one place.
    """
    try:
        with open(C.notes('ledger.md'), 'a', encoding='utf-8') as f:
            f.write(f'{dt.datetime.now():%m-%d %H:%M} {msg}\n')
    except OSError:
        pass


def plan_rel(name: str) -> str:
    """A plan file's path as git names it: forward slashes on Windows too (`git show`, the union's file list).
    A plan outside the repo is its absolute path: git ignores it there, and `ROOT / rel` still finds it."""
    if C.plan_external:
        return str(C.plan_dir / name)
    return os.path.relpath(C.plan_dir / name, C.root).replace(os.sep, '/')


def default_branch() -> str:
    """The branch worktrees start from and finished work is merged into: configured or discovered shared branch."""
    if branch := C.master_branch:
        if git('check-ref-format', '--branch', branch).returncode:
            raise SystemExit(f'[git] master_branch is not a valid branch name: {branch!r}')
        if git('show-ref', '--verify', '--quiet', f'refs/heads/{branch}').returncode:
            raise SystemExit(f'[git] master_branch {branch!r} does not exist as a local branch')
        current = git('branch', '--show-current').stdout.strip()
        if current != branch:
            raise SystemExit(f'[git] master_branch {branch!r} must be checked out in the main checkout '
                             f'(currently {current or "detached HEAD"!r})')
        return branch
    return (shared_name(ROOT, C.push_remote or 'origin', None)
            or git('branch', '--show-current').stdout.strip() or 'main')


def plan_text(branch: str) -> list[str]:
    """TODO.md as the merge target has it — not a worktree's copy, so a branch mid-task cannot skew picks.
    A plan outside the repo has one copy: pulled (now and then) and read."""
    if C.plan_external:
        plansync.pull(C)
        return P.lines(C.todo)
    r = git('show', f'{newest(branch)}:{plan_rel("TODO.md")}')
    if r.returncode == 0:
        return r.stdout.splitlines()
    return P.lines(C.todo)


FETCHED = [0.0]  # when `newest` last fetched


def newest(branch: str) -> str:
    """`branch`, or the remote's when that is strictly ahead of it (fetched at most once a minute): a push
    from outside the run (a hand merge in another worktree) lands in the shared branch only at the next
    merge, and until then the picks would read a plan where that task is still open and start it again."""
    remote = C.push_remote
    if not (C.push_merge and remote):
        return branch
    if time.time() - FETCHED[0] > 60:
        FETCHED[0] = time.time()
        if git('remote', 'get-url', remote).returncode == 0:
            _net(ROOT)('fetch', '-q', remote, branch)
    ref = f'refs/remotes/{remote}/{branch}'
    if git('rev-parse', '-q', '--verify', ref).returncode or git('rev-parse', ref).stdout == git('rev-parse', branch).stdout \
            or git('merge-base', '--is-ancestor', branch, ref).returncode:
        return branch
    return ref


def stopping() -> bool:
    """`./run stop` (or `s` in the runner's pane) was asked for: start nothing new."""
    return C.notes('STOP').exists()


def forced() -> bool:
    """`s!` or `./run stop --force`: the agent sessions are ended now, each queued to resume in the next run."""
    return C.notes('STOP.force').exists()


def ask_stop(how: str, force: bool = False) -> None:
    """The one stop mechanism: the STOP file, saying who asked (and STOP.force for a stop now). `./run stop`
    and `s` + Enter both write it."""
    C.notes('STOP').write_text(f'{dt.datetime.now().isoformat(timespec="seconds")} {how}\n', encoding='utf-8')
    if force:
        C.notes('STOP.force').touch()


def clear_stop() -> None:
    C.notes('STOP').unlink(missing_ok=True)
    C.notes('STOP.force').unlink(missing_ok=True)


def stopped_by() -> str:
    try:
        return C.notes('STOP').read_text(encoding='utf-8').split(maxsplit=1)[1].strip()
    except (OSError, IndexError):
        return f'{C.command} stop'


KEYS: list[str] = []  # lines typed into the runner's pane
KEYS_LOCK = threading.Lock()  # the reader thread and the loop both take keys
WAKE = threading.Event()  # set by a key, so the loop acts on it now instead of after its 10 s nap
READING = [False]  # the reader thread is up: the loop naps on WAKE
PAUSED = [False]  # `p`: no new tasks, and the run stays up
FORCED = [False]  # `f`: the usage caps no longer hold new tasks, as with --force
IDLE = [False]  # the run said `run idle` and has started nothing since: STATE carries it, for the board's hold


def nap(s: float) -> None:
    if READING[0]:
        WAKE.wait(s)
        WAKE.clear()
    else:
        time.sleep(s)


def read_keys() -> None:
    """A daemon thread's loop: every line typed into the runner's pane is acted on at once (`take_keys`), and
    the loop is woken for what only it can do (ending sessions, a new slot).

    A thread rather than select() on stdin, which only works on POSIX. Started only when stdin is a tty, and
    never by the sequential run, whose agent session reads the same terminal.
    """
    for line in sys.stdin:
        KEYS.append(line.strip().lower())
        take_keys()
        WAKE.set()


def state_line() -> str:
    """What the keys have set, for `?` and after each key."""
    what = [f'{SLOTS} slot{"s" if SLOTS != 1 else ""}']
    if stopping():
        what.append('stopping now (s!)' if forced() else f'stopping ({stopped_by()})')
    if PAUSED[0]:
        what.append('paused')
    if FORCED[0]:
        what.append('usage caps off (f)')
    if LATEST_SAID[0]:
        what.append(f'agent-runner {LATEST_SAID[0]} is out (u upgrades)')
    if POWER:
        what.append(f'{POWER} when ' + ('it stops' if stopping() else 'idle'))
    return ', '.join(what)


def keys_help() -> str:
    """The `?` block, shaped like `agent-runner help`, ruled off so it stands out from the log."""
    rule = '-' * 78
    return f"""{rule}
runner keys: type one in this pane and press Enter

    s        stop gently: no new tasks, the running ones finish and merge, then the run exits
    s!       stop now: end the agent sessions (each resumes where it was in the next run),
             finish the merges under way, then exit
    p        pause: no new tasks, and the run stays up
    u        upgrade agent-runner now; the run restarts on the new version by itself
    f        force: start tasks past the session and weekly usage caps (as --force)
    +        one slot more
    -        one slot fewer (a running task in it finishes first)
    z        suspend the computer once the run stops, or when it goes idle
    x        shut the computer down once the run stops, or when it goes idle
    Enter    open the control sessions at claude.ai/code (with [run] remote)
    ?        this help

    s, p, f, z and x take themselves back when typed again.
    Ctrl-C ends the runner only: sessions keep running, and the next run adopts them.

now: {state_line()}
{rule}"""


def take_keys() -> None:
    """Act on the lines typed into the runner's pane (see `keys_help`), and on a power choice `./run stop
    --suspend|--shutdown` left. Logged at once; ending sessions and adding a slot happen on the loop's next
    pass, which a key wakes."""
    global POWER, SLOTS
    with KEYS_LOCK:
        if (f := C.notes('POWER')).exists():
            POWER = f.read_text(encoding='utf-8').strip()
            f.unlink(missing_ok=True)
        KEYS.extend(cli_keys())
        while KEYS:
            k, _, want = KEYS.pop(0).partition(' ')
            if not k:
                if remote_any():
                    open_remote()
                continue
            on = {'s': stopping, 'p': lambda: PAUSED[0], 'f': lambda: FORCED[0],
                  'z': lambda: POWER == 'suspend', 'x': lambda: POWER == 'shutdown'}.get(k)
            if on and want in ('on', 'off') and on() == (want == 'on'):
                log(f'{k} {want}: already so ({state_line()})')
                continue
            if k == 'slots':
                try:
                    n = SLOTS + int(want) if want[:1] in '+-' else int(want)
                except ValueError:
                    log(f'slots wants a number, +N or -N, not {want!r}')
                    continue
                if n < 1:
                    log('one slot is the fewest; s stops the run')
                    continue
                was, SLOTS = SLOTS, n
                log(f'slots: {SLOTS}' + (f' (slots past {SLOTS} close once their tasks end)' if n < was else ''))
                continue
            if k == 's' and stopping():
                clear_stop()
                log('stop taken back: starting tasks again')
            elif k == 's':
                ask_stop('s')
                log('stopping: no new tasks; the running ones finish and merge, then the run ends (s again: undo)')
            elif k == 's!':
                ask_stop('s!', force=True)
                log('stopping now: ending the agent sessions (each resumes in the next run); the merges under way '
                    'finish, then the run ends')
            elif k == 'p':
                PAUSED[0] = not PAUSED[0]
                log('paused: no new tasks; the run stays up (p again: go on)' if PAUSED[0] else
                    'pause taken back: starting tasks again')
            elif k == 'f':
                FORCED[0] = not FORCED[0]
                log('forced: starting tasks past the usage caps (f again: undo)' if FORCED[0] else
                    'force taken back: the usage caps hold new tasks again')
            elif k == 'u':
                threading.Thread(target=upgrade, daemon=True).start()  # the loop restarts on what it installs
            elif k in ('+', '-'):
                if k == '-' and SLOTS == 1:
                    log('one slot is the fewest; s stops the run')
                    continue
                SLOTS += 1 if k == '+' else -1
                log(f'slots: {SLOTS}' + (f' (slot {SLOTS + 1} closes once its task ends)' if k == '-' else ''))
            elif k in ('z', 'x'):
                want = 'suspend' if k == 'z' else 'shutdown'
                POWER = '' if POWER == want else want
                log(f'{want} once the run stops, or when it goes idle ({k} again: undo)' if POWER else
                    f'{want} taken back: the computer stays on')
            elif k in ('?', 'h', 'help'):
                print(keys_help(), flush=True)
            else:
                print(f'unknown key {k!r}\n{keys_help()}', flush=True)


def cli_keys() -> list[str]:
    """The keys `agent-runner pause|force|slots|key` left in `<notes>/KEYS`, one a line, taken once. Moved
    aside before it is read, so a key written meanwhile goes in a new file for the next pass."""
    f = C.notes('KEYS')
    taken = f.with_name(f'KEYS.{os.getpid()}')
    try:
        f.replace(taken)
    except OSError:
        return []
    try:
        return [k for l in taken.read_text(encoding='utf-8').splitlines() if (k := l.strip().lower())]
    finally:
        taken.unlink(missing_ok=True)


REMOTE_URL = 'https://claude.ai/code'  # every Remote Control session of the account, slots and control alike


def open_remote() -> None:
    """Enter in the runner's pane, with `[run] remote`: the sessions page, in the default browser (a claude.ai
    link the desktop app is set to take opens there). No browser here (ssh): the link, to open elsewhere."""
    try:
        ok = webbrowser.open(REMOTE_URL)
    except Exception:  # noqa: BLE001 - a broken browser setup must not take the key reader down
        ok = False
    log(f'opening {REMOTE_URL}' if ok else f'no browser here: open {REMOTE_URL} on any device, or the Claude app')


def send_key(*keys: str) -> None:
    """What a typed key does, from any terminal or a remote session: the run takes it on its next pass."""
    with open(C.notes('KEYS'), 'a', encoding='utf-8') as f:
        f.write(''.join(f'{k}\n' for k in keys))


RUNNING_SINCE: dict[tuple[str, str], float] = {}  # (slot, task) -> when write_state first saw it running


def write_state(running: dict) -> None:
    """`<notes>/STATE`, for `agent-runner status`: what the keys have set, what each slot is on and since when,
    what is merging, and the account's usage (as the cap reads it, at most every 5 minutes)."""
    work = {str(n): t[0] for n, t in running.items()}
    now = time.time()
    for k in [k for k in RUNNING_SINCE if work.get(k[0]) != k[1]]:
        RUNNING_SINCE.pop(k)
    since = {n: RUNNING_SINCE.setdefault((n, tid), now) for n, tid in work.items()}
    merging = sorted({t.name[6:] for t in threading.enumerate() if t.name.startswith('merge:') and t.is_alive()})
    # what the cap last read (`capped`, the start line); never a fetch of its own from here
    got = _account[1] if isinstance(_account[1], dict) else {}
    use = {k: got[k].get('utilization') for k in ('five_hour', 'seven_day') if isinstance(got.get(k), dict)}
    tmp = C.notes('STATE.tmp')
    try:
        tmp.write_text(json.dumps({'at': dt.datetime.now().isoformat(timespec='seconds'), 'state': state_line(),
                                   'running': work, 'since': since, 'merging': merging, 'usage': use,
                                   'idle': IDLE[0], 'paused': PAUSED[0], 'stopping': stopping()}),
                       encoding='utf-8')
        os.replace(tmp, C.notes('STATE'))
    except OSError:  # Windows: `status` has STATE open this instant; the next pass writes it
        pass


def kept_keys() -> dict:
    """What the run before an upgrade restart had set with its keys (`restart_if_upgraded`), once."""
    try:
        return json.loads(os.environ.pop('AGENT_RUNNER_KEEP', '') or '{}')
    except ValueError:
        return {}


def end_sessions(procs: dict, running: dict) -> None:
    """`s!`: end every agent session now, each queued to resume in its slot when a run next starts. Its
    worktree stays as the session left it; nothing it did is merged."""
    for n, (pid, sid, _) in list(procs.items()):
        tid = running[n][0]
        queue_resume(tid, n, sid, 'stopped with s!')
        plat.terminate(pid)
        log(f'slot {n}: {tid} ended (s!); it resumes in this slot in the next run')
    procs.clear()
    running.clear()


DISCARDED: dict[str, str] = {}  # B19: task -> what `_finish` did with a branch a drop or change got to first


def halt_requests() -> dict[str, str]:
    """{task: 'drop' | 'change'}: what `plan drop` / `plan change` asked of this run (see plan.halt)."""
    out = {}
    for f in P.halt_dir(C).glob('*.json'):
        try:
            how = json.loads(f.read_text(encoding='utf-8'))['how']
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if how in ('drop', 'change'):
            out[f.stem] = how
    return out


def halt_answer(tid: str, msg: str) -> None:
    """Tell the waiting `plan drop`/`change` what happened, log it, and take its request away."""
    d = P.halt_dir(C)
    tmp = d / f'{tid}.done.tmp'
    tmp.write_text(msg + '\n', encoding='utf-8')
    os.replace(tmp, d / f'{tid}.done')
    (d / f'{tid}.json').unlink(missing_ok=True)
    log(msg)
    note(msg)


def discard_task(tid: str, n: int | None, sid: str = '') -> list[str]:
    """Throw away everything of task `tid`'s attempt: its worktree (slot n) reset clean and detached, task/<tid>
    deleted here and on the remote, its tested ref and its session's scratch gone. Nothing is saved: it was
    dropped or changed, so nobody wants this work. Returns what it did, for the message."""
    did = []
    if n is not None and (d := SLOTS_DIR / f's{n}').is_dir():
        if git('symbolic-ref', '-q', '--short', 'HEAD', cwd=d).stdout.strip() == f'task/{tid}':
            clean(d)
            git('checkout', '-q', '--detach', cwd=d)
            did.append(f'reset s{n}')
        finished_mark(n).unlink(missing_ok=True)
    if not git('rev-parse', '--verify', '-q', f'refs/heads/task/{tid}').returncode:
        git('branch', '-D', f'task/{tid}')
        did.append(f'deleted task/{tid}')
    git('update-ref', '-d', TESTED + tid)
    if out := gitops.drop_remote(ROOT, f'task/{tid}'):
        did.append(out)
    (plansync.ticks(C) / tid).unlink(missing_ok=True)  # a `done` it got to: never ticked by a merge now
    if sid:
        drop_session_tmp(sid)
    return did


def halts(procs: dict, running: dict, free_at: dict, tried: set, branch: str, model: str, idle: int,
          slots: int) -> None:
    """B19: act on `plan drop` / `plan change` of a task this run is on. Its session is ended, its work thrown
    away (`discard_task`) and its slot freed at once; a change starts it again in that slot from the new
    text. A finished branch waiting to merge is deleted unmerged (by `_finish`, which checks first)."""
    for tid, how in halt_requests().items():
        verb = 'dropped' if how == 'drop' else 'changed'
        n = next((m for m, t in running.items() if t[0] == tid), None)
        q = next((m for m, x in queued().items() if x[0] == tid), None)
        sid = ''
        if n is not None:
            pid, sid, _ = procs.pop(n)
            running.pop(n)
            plat.terminate(pid)
            end = time.monotonic() + 10
            while alive(pid) and time.monotonic() < end:
                time.sleep(0.2)
            if alive(pid):  # it ignored SIGTERM: its tree gets one, then whatever is left is ended below
                for p in [*plat.descendants(pid), pid]:
                    plat.terminate(p)
            stopped = f'stopped s{n}'
        elif q is not None:
            n, sid = q, queued()[q][1]
            C.notes(f'{tid}.resume').unlink(missing_ok=True)
            stopped = f'took back its resume in s{n}'
        elif any(t.name == f'merge:{tid}' and t.is_alive() for t in threading.enumerate()) and tid not in DISCARDED:
            continue  # its merge thread reads the request before it merges (`_finish`)
        elif tid in DISCARDED:
            stopped = DISCARDED.pop(tid)
        else:
            stopped = 'no slot was on it any more'
        did = discard_task(tid, n, sid) if n is not None else []
        if n is not None:
            end_orphans()
            free_at[n] = dt.datetime.now()
        msg = f'{verb} {tid}; {stopped}' + (f', removed its work ({", ".join(did)})' if did else '')
        if how == 'drop':
            plansync.release(C, tid)
        else:
            tried.discard(tid)  # the new text is a new attempt
            task = next((t for t in tasks(branch) if t[0] == tid), None)
            if n is not None and task and n <= slots and (p := start(n, task, branch, model, idle, slots)):
                procs[n], running[n] = p, task
                tried.add(tid)
                msg += f'; restarted it in s{n} with the new text'
            else:
                plansync.release(C, tid)
                msg += '; it starts again with the new text when a slot is free'
        halt_answer(tid, msg)


def send_to_pane(pane_id: str, text: str) -> bool:
    """F16: type `text` into tmux pane `pane_id` and press Enter: a bracketed paste (so a newline in it does
    not send early) then Enter, which an interactive Claude Code (or Pi) queues for its next turn while busy."""
    buf = f'agent-runner-{os.getpid()}'
    if tmux('load-buffer', '-b', buf, '-', input=text).returncode:
        return False
    if tmux('paste-buffer', '-d', '-p', '-b', buf, '-t', pane_id).returncode:
        tmux('delete-buffer', '-b', buf)
        return False
    time.sleep(0.3)  # let the TUI take the paste before Enter, or Enter lands inside it
    return not tmux('send-keys', '-t', pane_id, 'Enter').returncode


def tell_requests() -> dict[str, dict]:
    """{task: request}: what `plan tell` / `plan change` asked this run to pass on (see plan.tell)."""
    out = {}
    for f in P.tell_dir(C).glob('*.json'):
        try:
            req = json.loads(f.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if isinstance(req, dict) and req.get('how') in ('tell', 'change') and isinstance(req.get('text'), str):
            out[f.stem] = req
    return out


def tell_answer(tid: str, told: bool, msg: str) -> None:
    d = P.tell_dir(C)
    tmp = d / f'{tid}.done.tmp'
    tmp.write_text(json.dumps({'told': told, 'msg': msg}), encoding='utf-8')
    os.replace(tmp, d / f'{tid}.done')
    (d / f'{tid}.json').unlink(missing_ok=True)
    log(msg)
    if told:
        note(msg)


def tells(procs: dict, running: dict) -> None:
    """F16: pass each `plan tell` / `plan change` message on to the slot running its task, by typing it into
    the slot's tmux pane. No live pane (not tmux, the session ended, a cut-off one waiting to resume): told
    false, and `plan change` falls back to the B19 halt."""
    reqs = tell_requests()
    if not reqs:
        return
    tagged = MUX.panes() if isinstance(MUX, TmuxMux) else {}
    for tid, req in reqs.items():
        n = next((m for m, t in running.items() if t[0] == tid), None)
        if n is None:
            tell_answer(tid, False, f'no slot runs {tid} now')
            continue
        hit = tagged.get(f's{n}')
        if not isinstance(MUX, TmuxMux):
            why = f'no live pane for s{n} ({tid}): its terminal ({MUX.name}) takes no typed text'
        elif not hit or not alive(hit[1]) or (n in procs and not alive(procs[n][0])):
            why = f'no live pane for s{n} ({tid}): its session has ended'
        elif not send_to_pane(hit[0], P.tell_text(req['how'], req['text'])):
            why = f'no live pane for s{n} ({tid}): tmux could not type into {hit[0]}'
        else:
            tell_answer(tid, True, f'told s{n} ({tid})')
            continue
        tell_answer(tid, False, why)


def power_now() -> None:
    """After a stop, with `z`, `x`, --suspend or --shutdown: suspend or power off now, no idle grace."""
    log(f'run stopped: {"suspending" if POWER == "suspend" else "shutting down"} the computer')
    if rc := (plat.suspend if POWER == 'suspend' else plat.power_off)():
        log(f'the {POWER} command failed (exit {rc})')


# --- picking the next task -----------------------------------------------------

def open_tasks(branch: str) -> set[str]:
    """Ids of the open ([ ]) top-level tasks in `branch`'s TODO.md."""
    return {m.group(2) for l in plan_text(branch) if (m := TASK.match(l)) and m.group(1) == ' '}


def blocked_tasks(branch: str) -> set[str]:
    """Ids of the blocked ([~]) top-level tasks in `branch`'s TODO.md."""
    return {m.group(2) for l in plan_text(branch) if (m := TASK.match(l)) and m.group(1) == '~'}


def tasks(branch: str) -> list[tuple[str, str, set[str], set[str]]]:
    """Open tasks in TODO.md order: (id, section, its `files:`, its `after:`)."""
    ls = plan_text(branch)
    # open and blocked: neither is done, so a split parent or an `after:` still waits on a blocked X
    open_ids = {m.group(2) for l in ls if (m := TASK.match(l)) and m.group(1) != 'x'}
    out, section = [], ''
    for l in ls:
        if l.startswith('### '):
            section = l[4:]
            continue
        m = TASK.match(l)
        if not m or m.group(1) != ' ' or section.startswith(P.SKIPPED):
            continue
        tid, f = m.group(2), P.fields(l)
        # a split parent: its subtasks run first, blocked ones included, then it runs (or `archive` ticks it).
        # Read by id and by its `(split into …)` list, never by the words alone, so prose that happens to say
        # "split into" is not taken for a split
        if P.subtasks(tid, l, open_ids):
            continue
        after = set(f.get('after', [])) - {tid}
        if after & open_ids:
            continue
        out.append((tid, section, set(f.get('files', [])), after))
    return by_waiters(ls, out)


def by_waiters(ls: list[str], out: list[tuple]) -> list[tuple]:
    """`out` with each task a waiting one depends on moved up to where that one stands: a task in a Next
    section with `after: S281` on a Follow-up would otherwise wait for every task between them, and
    so would everything waiting on it. Transitive; Stretch and Parked lines pull nothing up."""
    rank, waits, section = {}, {}, ''
    for l in ls:
        if l.startswith('### '):
            section = l[4:]
            continue
        m = TASK.match(l)
        if not m or m.group(1) == 'x':
            continue
        rank.setdefault(m.group(2), len(rank))
        if not section.startswith(P.SKIPPED):
            waits[m.group(2)] = set(P.fields(l).get('after', [])) | {
                i for a in P.WAITS.findall(l) for i in P.TASK_ID.findall(a)}  # and a block's `(after X)`
    for _ in range(len(waits)):  # each pass moves a rank one link down a chain
        moved = False
        for w, deps in waits.items():
            for dep in deps:
                if dep in rank and rank[w] < rank[dep]:
                    rank[dep], moved = rank[w], True
        if not moved:
            break
    order = {t[0]: (rank.get(t[0], len(rank)), k) for k, t in enumerate(out)}
    return sorted(out, key=lambda t: order[t[0]])


def ahead(branch: str) -> list[str]:
    """Ids whose task/<ID> has commits `branch` lacks, in one `git for-each-ref` rather than a call per branch."""
    refs = git('for-each-ref', f'--no-merged={branch}', '--format=%(refname)', 'refs/heads/task/').stdout.split()
    return [r.removeprefix('refs/heads/task/') for r in refs]


def family(tid: str) -> str:
    """L3a, L3b, L3 -> L3; A11k4 -> A11. Siblings share it and never run side by side."""
    m = re.match(r'[A-Za-z]*\d*', tid)
    return m.group() if m else tid


def ordered(section: str) -> bool:
    """A section whose heading says its tasks run in sequence ("Next (in this order)", "… one at a time") runs
    one task at a time: its second task usually depends on the first having landed, whatever the files say.
    A plain "Next" or "(in order)" is a priority order: its tasks start side by side, by files."""
    return 'in this order' in section or 'one at a time' in section



def clash(t: tuple, b: tuple, shared: set[str]) -> bool:
    """Task `t` may not run beside `b` (running here, waiting to merge, or claimed by another runner): siblings,
    a shared ordered section, or overlapping files (`shared_files` aside)."""
    tid, section, files, _ = t
    if family(tid) == family(b[0]):
        return True
    return (ordered(section) and section == b[1]) or bool(P.overlap(set(files) - shared, set(b[2])))


def clash_why(t: tuple, b: tuple, shared: set) -> tuple[str, str]:
    """Why `clash(t, b)`: (the kind of wait, what holds it), for the dry run."""
    if family(t[0]) == family(b[0]):
        return 'waiting for a sibling', b[0]
    if ordered(t[1]) and t[1] == b[1]:
        return f'one at a time in "{t[1]}"', b[0]
    return 'waiting for files', f'{", ".join(sorted(P.overlap(set(t[2]) - shared, set(b[2])))[:3])} held by {b[0]}'


def claimed_elsewhere(cls: dict, todo: list) -> list[tuple]:
    """Other runners' live claims as busy tasks: the claimed line's section, files and named ids, plus the
    files its claim says its session has touched. A stale claim (a crashed run's) holds only its own task."""
    me, lines = plansync.owner(C), {t[0]: t for t in todo}
    out = []
    for tid, cl in cls.items():
        if cl.owner == me or plansync.stale(cl):
            continue
        t = lines.get(tid, (tid, '', set(), set()))
        out.append((tid, t[1], set(t[2]) | set(cl.files), t[3]))
    return out


def pick(running: dict, tried: set, branch: str, claim: bool = False, why: dict | None = None):
    """The next task a free slot may take, or None. See the module docstring for the rules.

    `claim` (a run about to start it): with a remote to share claims through, the task is claimed and the claim pushed first;
    one another runner has, or got just now, is passed over for the next. Another runner's live claim counts
    as a task running here, so its files, ordered section and family wait for it too.

    `why` (the dry run): pick nothing, and fill it with every open task's reason instead, as
    {tid: (kind, detail)}; a task free to start gets ('free', '')."""
    shared = set(C.run['shared_files'])
    todo = tasks(branch)

    def pick_(t):
        if not claim or not plansync.enabled(C):
            return t
        if not plansync.claim(C, t[0], t[2]):
            return None
        FETCHED[0] = 0.0  # in-repo: the merge that closed it may have landed since the last fetch
        if t[0] not in open_tasks(branch):  # the claim pulled: the pick may have read a plan up to 20 s old
            plansync.release(C, t[0])  # closed meanwhile (ticked or blocked by someone else)
            return None
        # Two runners can claim clashing tasks from plans read seconds apart; both see both claims now, and
        # the later one gives way (claim time, then owner: both sides reach the same verdict).
        now = plansync.claims(C)
        mine = now.get(t[0])
        for b in claimed_elsewhere(now, todo):
            cl = now[b[0]]
            if mine and (cl.since, cl.owner) < (mine.since, mine.owner) and clash(t, b, shared):
                plansync.release(C, t[0])
                log(f'{t[0]}: {cl.who} claimed {b[0]} first and it clashes; given way')
                return None
        return t

    busy = claimed_elsewhere(plansync.claims(C), todo)  # [] with no remote to claim through
    lines_ = {t[0]: t for t in todo}
    for tid, d in taken().items():  # `take`: a person's session or subagent has it, in its own worktree
        t = lines_.get(tid, (tid, '', set(), set()))
        busy.append((tid, t[1], set(t[2]) | touched(tid, branch, d), t[3]))
    busy_ids = {b[0] for b in busy} | {q[0] for q in queued().values()}  # one waiting to resume is running
    mine = set(ahead(branch)) if todo else set()  # finished here, waiting to be merged
    finished = mine | plansync.taken(C)  # another runner's: on its slots
    lines = {t[0]: t for t in todo}
    # A running task holds the files it has touched as well as its line's (a line can name too few). A finished
    # one holds only the files it changed, until its merge lands: its line's names were a guess, and a broad
    # one (`tests/**`) would keep dozens of tasks from starting while the merges catch up
    slots = {t[0]: SLOTS_DIR / f's{n}' for n, t in running.items() if isinstance(n, int)}
    live = {t[0] for t in running.values()}
    for tid, t in {**{f: lines.get(f, (f, '', set(), set())) for f in mine},
                   **{t[0]: t for t in running.values()}}.items():
        files = touched(tid, branch, slots.get(tid))
        done_ = tid in mine and tid not in busy_ids and tid not in live and files  # finished, not running
        busy.append((tid, t[1], files if done_ else set(t[2]) | files, t[3]))
    busy_ids |= {b[0] for b in busy if b[0] not in mine}
    claimed = {t: cl.who for t, cl in plansync.claims(C).items()} if why is not None else {}
    parked = parked_attempts() if todo else {}
    for t in todo:
        tid = t[0]
        if tid not in busy_ids and tid in finished:
            if why is not None:
                why[tid] = ('claimed by another runner', claimed.get(tid, '')) if tid not in mine else \
                    ('finished, waiting to merge', '')
            continue  # finished, its branch is waiting to be merged: restarting it would reset the branch
        if tid in tried or tid in busy_ids:
            if why is not None:
                why[tid] = ('tried this run', '') if tid in tried else \
                    ('running', f'claimed by {claimed[tid]}' if tid in claimed else
                     'taken by hand (`take`)' if tid in taken() else '')
            continue
        if len(parked.get(tid, [])) >= PARK_LIMIT:  # B32: failed its merge that often; a person decides
            if why is not None:
                why[tid] = (f'parked {len(parked[tid])} times, needs a person', ', '.join(sorted(parked[tid])))
            elif claim:
                block_parked(tid, parked[tid], branch)
            continue
        if b := next((b for b in busy if clash(t, b, shared)), None):
            if why is not None:
                why[tid] = clash_why(t, b, shared)
            continue  # a running or merge-waiting task's sibling, ordered-section mate or file neighbour waits
        if why is not None:
            why[tid] = ('free', '')
            continue

        if got := pick_(t):
            PASSED.discard(tid)
            return got
        if tid not in PASSED:
            PASSED.add(tid)
            log(f'{tid}: claimed by another runner, closed since the pick read the plan, the claim did not push, '
                'or a clashing claim came first; passed over')
    return None


PASSED: set[str] = set()  # tasks `pick` could not claim, said once each


# --- worktrees and panes -------------------------------------------------------

def worktree(n, branch: str) -> Path:
    """Slot n's worktree (or the merge worktree), created once and kept: a warm build is worth more than a
    clean one. `[run] links` — git-ignored data the work needs — are symlinked in, never copied."""
    d = SLOTS_DIR / (f's{n}' if isinstance(n, int) else str(n))
    if not d.is_dir():
        SLOTS_DIR.mkdir(parents=True, exist_ok=True)
        git('worktree', 'prune')
        git('worktree', 'add', '-q', '--detach', str(d), branch)
    for pat in C.run['copies']:  # git-ignored files a worktree needs its own copy of (a local config)
        for src in map(Path, glob.glob(str(ROOT / pat))):
            if src.is_file() and not (dst := d / src.relative_to(ROOT)).exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
    for pat in [*C.run['links'], 'runner.toml']:
        for src in map(Path, glob.glob(str(ROOT / pat))):
            dst = d / src.relative_to(ROOT)
            if src.exists() and not dst.is_symlink() and not dst.exists():
                try:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    plat.link(src, dst)  # a symlink; on Windows without Developer Mode a junction or hard link
                except OSError:
                    pass
    if copilot():
        copilot_trust(d)
    else:
        backend().trust(d)
    return d


def tmux(*a: str, **kw) -> sp.CompletedProcess:
    return sp.run(['tmux', *a], capture_output=True, text=True, **kw)


def window(kind: str) -> str:
    """This repo's window of `kind` ("agents" or "master"): "agents-openmx", so two repos' runners in one
    tmux session neither share a window nor lay out each other's panes."""
    return f"{kind}-{re.sub(r'[^A-Za-z0-9_-]', '-', ROOT.name)}"


def window_id(name: str) -> str | None:
    """The id (@N) of this tmux session's window called exactly `name`: a name as a target also matches a
    longer one by prefix (agents-openmx would find agents-openmx-mods)."""
    for l in tmux('list-windows', '-F', '#{window_id}\t#{window_name}').stdout.splitlines():
        wid, _, wname = l.partition('\t')
        if wname == name:
            return wid
    return None


def pane(name: str, cwd: Path, cmd: str, env=(), logfile: Path | None = None) -> int:
    """Open cmd in a pane of this repo's window "agents-<repo>", tagged @runner=name and @runner-repo=the
    main checkout, in slot order; returns its pid. The fix and repair sessions (name "master") get a
    window of their own, "master-<repo>", so the slots' layout does not squeeze them to a column.

    Panes are found by their tag rather than their position, so you can break them out, join them or swap
    them around while the run goes on. The pane's output is piped to `logfile`, which is where a usage
    limit's "resets 3pm" shows up when the transcript does not have it. Raises RuntimeError when tmux
    will not open it.
    """
    envs = [a for e in env for a in ('-e', e)]
    w = window('master' if name == 'master' else 'agents')
    where = ['new-window', '-n', w]
    if name == 'master':
        pass  # a window per session (fixes ahead of the lock run side by side); it closes with it
    elif wid := window_id(w):
        here = sorted((int(h[1:]), p) for p, h in
                      (l.split('\t') for l in tmux('list-panes', '-t', wid, '-F',
                                                   f'#{{pane_id}}\t#{{{TAG}}}').stdout.splitlines())
                      if re.fullmatch(r's\d+', h))
        k = int(name[1:])
        lower = [p for i, p in here if i < k]
        where = (['split-window', '-h', '-t', lower[-1]] if lower else
                 ['split-window', '-h', '-b', '-t', here[0][1] if here else wid])
    r = tmux(*where, '-d', '-c', str(cwd), *envs, '-P', '-F', '#{pane_id} #{pane_pid} #{window_id}', cmd)
    if r.returncode or not r.stdout.split():
        raise RuntimeError(f'tmux could not open a pane: {r.stderr.strip()}')
    pane_id, pid, w = (r.stdout.split() + [w])[:3]
    tmux('set-option', '-p', '-t', pane_id, TAG, name)
    tmux('set-option', '-p', '-t', pane_id, REPO_TAG, str(ROOT))
    tmux('set-option', '-w', '-t', w, 'pane-border-status', 'top')
    tmux('set-option', '-w', '-t', w, 'pane-border-format', f' #{{{TAG}}} ')
    tmux('select-layout', '-t', w, 'even-horizontal')
    if logfile:
        tmux('pipe-pane', '-t', pane_id, '-o', f'cat >> {shlex.quote(str(logfile))}')
    return int(pid)


alive = plat.alive


def panes() -> dict[str, tuple[str, int]]:
    """{name: (pane id, pid)} of this repo's tagged panes in this tmux session: another repo's runner may
    share the session, with slots of the same names, so a pane is ours only when its @runner-repo is this
    main checkout."""
    out = {}
    for l in tmux('list-panes', '-s', '-F', f'#{{pane_id}}\t#{{pane_pid}}\t#{{{TAG}}}\t#{{{REPO_TAG}}}').stdout.splitlines():
        pane_id, pid, name, repo = (l.split('\t') + [''] * 3)[:4]
        if name and pid.isdigit() and repo and Path(repo) == ROOT:
            out[name] = (pane_id, int(pid))
    return out


def session_id(pid: int) -> str | None:
    """The `--session-id` of the agent running as `pid` or its child (the pane's shell may not exec it)."""
    for p in [pid, *plat.children(pid)]:
        if (args := plat.cmdline(p)) is not None and (named := sids(args)):
            return named[0]
    return None


def sids(args: list[str]) -> list[str]:
    """The session ids an agent command line names: `--session-id`'s, then `--resume`'s."""
    return [args[args.index(f) + 1] for f in ('--session-id', '--resume') if f in args[:-1]]


def adopt(branch: str) -> dict[int, tuple]:
    """Sessions an earlier run left going in panes sN: {n: ((pid, sid, since), task)}. A restarted runner
    watches and merges them as its own instead of resetting their worktrees under them. A slot past this run's count is watched until it ends and never refilled."""
    known = {t[0]: t for t in tasks(branch)}
    out = {}
    for name, (_, pid) in MUX.panes().items():
        if not re.fullmatch(r's\d+', name) or not alive(pid) or not (sid := MUX.session_id(pid)):
            continue
        n = int(name[1:])
        tid = git('branch', '--show-current', cwd=SLOTS_DIR / name).stdout.strip().removeprefix('task/')
        if not tid:
            continue
        logfile = C.notes(f'slot{n}.log')
        out[n] = ((pid, sid, logfile.stat().st_size if logfile.exists() else 0),
                  known.get(tid, (tid, '', set(), set())))
        log(f'slot {n}: adopted the running {tid}')
    return out


def unmerged(branch: str, idle: list[int]) -> list[str]:
    """Open tasks whose task/<ID> has commits `branch` lacks: work that finished, or was merging, when no run
    was up to merge it. The idle
    slots in `idle` are detached first, so a slot whose session ended still on its branch neither hides
    that branch from the scan nor keeps start() from taking it later."""
    for n in idle:
        if (SLOTS_DIR / f's{n}').is_dir():
            git('checkout', '-q', '--detach', cwd=SLOTS_DIR / f's{n}')
    held = {l.removeprefix('branch refs/heads/') for l in
            git('worktree', 'list', '--porcelain').stdout.splitlines() if l.startswith('branch ')}
    # blocked too: a session that ended its task blocked (a concept round handing over) still has its journal
    # to merge, and its claim would otherwise be refreshed for as long as the branch sits
    open_ids = open_tasks(branch) | blocked_tasks(branch)
    return [t for t in ahead(branch) if f'task/{t}' not in held and t in open_ids]


def left_merging() -> set[str]:
    """The tasks whose fix or repair session or gate run an earlier run left going (`adopt_merge`)."""
    out = set()
    try:
        runs = [json.loads(C.notes('master.json').read_text(encoding='utf-8'))]
    except (OSError, ValueError):
        runs = []
    for s in runs + (gate_runs() if C.notes(GATES).is_dir() else []):
        if gate_alive(s) and Path(s.get('cwd', '')).name != 'merge2':
            out.add(s['tid'])
    return out


def single_run() -> object:
    """Hold `<notes>/run.lock` for this process's life, or exit: two runs would share the slot worktrees
    and reset each other's sessions. The lock goes with the process, however it ends."""
    if not (f := plat.lock(C.notes('run.lock'))):
        raise SystemExit(f'another run is going in this repository ({C.notes("run.lock")} is held); '
                         f'wait for it, or `{C.command} stop` it')
    return f


# --- starting a session --------------------------------------------------------

def copilot() -> bool:
    """`[run] agent` is GitHub Copilot CLI rather than Claude Code."""
    return Path(C.run['agent']).stem.lower() == 'copilot'


def copilot_home() -> Path:
    return Path(os.environ.get('COPILOT_HOME') or Path.home() / '.copilot')


def pi() -> bool:
    """`[run] agent` is the Pi coding agent (pi.dev)."""
    return Path(C.run['agent']).stem.lower() == 'pi'


def pi_sessions() -> Path:
    """Where Pi keeps this run's sessions (`--session-dir`), as `<timestamp>_<session id>.jsonl`."""
    return C.notes('pi-sessions', 'x').parent


def pi_argv0() -> list[str]:
    """Pi itself. On Windows its npm `.cmd` shim is skipped: cmd.exe would cut a multi-line prompt short and
    ask "Terminate batch job?" on Ctrl-C, so node runs the CLI the shim names."""
    exe = plat.exe(C.run['agent'])
    if plat.WINDOWS and exe.lower().endswith('.cmd'):
        cli = Path(exe).parent / 'node_modules' / '@earendil-works' / 'pi-coding-agent' / 'dist' / 'bundle' / 'cli.js'
        node = Path(exe).parent / 'node.exe'
        if cli.exists():
            return [str(node) if node.exists() else (shutil.which('node') or 'node'), str(cli)]
    return [exe]


PI_EXTENSION = """// Written by agent-runner for each run: the idle Stop hook and, when pushing is off, no git push.
import { spawn } from "node:child_process";

const HOOK: string[] = %(hook)s;
const NO_PUSH: boolean = %(no_push)s;
const PUSH = /\\bgit(\\s+-[Cc]\\s+\\S+)*\\s+push\\b/;

export default function (pi: any) {
  pi.on("agent_settled", async (_event: any, ctx: any) => {
    if (!process.env.AGENT_RUNNER) return;  // a person's own Pi session: never end it
    const child = spawn(HOOK[0], HOOK.slice(1), { stdio: ["pipe", "ignore", "ignore"], detached: true, windowsHide: true });
    child.on("error", () => {});
    child.stdin.end(JSON.stringify({
      transcript_path: ctx.sessionManager.getSessionFile(),
      session_id: ctx.sessionManager.getSessionId(),
    }));
    child.unref();
  });
  pi.on("tool_call", async (event: any) => {
    if (!NO_PUSH || (event.toolName !== "bash" && event.toolName !== "powershell")) return undefined;
    if (PUSH.test(String(event.input?.command ?? ""))) {
      return { block: true, reason: "Pushing is off for this run: never run git push. A human pushes." };
    }
    return undefined;
  });
}
"""


def pi_extension(idle: int) -> Path:
    """The extension every Pi session of this run loads (`-e`): Pi has no hook settings, only extensions."""
    f = C.notes('agent-runner-pi.ts')
    f.write_text(PI_EXTENSION % {'hook': json.dumps([*runner_cmd(), 'run', '--stop-hook', '--idle', str(idle)]),
                                 'no_push': 'false' if C.push_remote else 'true'}, encoding='utf-8')
    return f


def lean() -> list[str]:
    """Bash/Read/Edit/Write/Artifact and the repo's own settings only: an unattended agent needs no MCP servers, and a
    user-level setting (a status line, a hook that asks) is something nobody is there to answer."""
    if not C.run['lean']:
        return []
    if copilot():
        return ['--disable-builtin-mcps']
    if pi():
        return ['--no-mcp']
    # Artifact: a task can publish a page or screenshots to claude.ai and link it, seen from any device
    return ['--tools', 'Bash,Read,Edit,Write,Artifact', '--setting-sources', 'project,local', '--strict-mcp-config']


ARG_PROMPT_MAX = 96 * 1024  # Linux's MAX_ARG_STRLEN is 128 KiB for one argument; leave room
ARGV_PROMPT_MAX = 24000  # Windows' CreateProcess takes 32 767 characters, flags and paths included
LONG_BRIEF = 'Your instructions for this session are in your system prompt, under "{marker}". Follow them.'


class Claude:
    """Claude Code: an interactive session ended by its Stop hook once `idle` s at the prompt; the brief is
    the first message; transcripts under ~/.claude/projects, in the shape the rest of the runner reads.

    A backend is everything the runner does differently per agent CLI. To add one, subclass this and
    override what differs, then name it in BACKENDS (and `config.py`'s backend check).
    """
    report_exit = False  # log a session's last words at exit, and fail a sequential run on a nonzero exit

    def flags(self, sid: str, model: str, idle: int, resume: bool, once: bool) -> list[str]:
        stop = [{'hooks': [{'type': 'command', 'command': plat.command_text(
            [*runner_cmd(), 'run', '--stop-hook', '--idle', str(idle)])}]}]
        brief = C.notes(f'{sid}.brief')
        return ['--resume' if resume else '--session-id', sid, '--permission-mode', 'bypassPermissions',
                '--disallowedTools', 'AskUserQuestion', '--model', model, *lean(),
                *(['--append-system-prompt-file', str(brief)] if brief.exists() else []),
                # lean() drops user settings, where the bypass dialog's opt-out lives; nobody is there to answer it
                '--settings', json.dumps({'skipDangerousModePermissionPrompt': True,
                                          'hooks': {'Stop': stop, 'StopFailure': stop},
                                          # on Remote Control a slot's own PushNotification tool stays off (R2:
                                          # inputNeededNotifEnabled is not here, as Claude Code only sends it to
                                          # the server from /config, so --settings never reaches the push)
                                          **({'agentPushNotifEnabled': False}
                                             if remote_slots_on() and silent() is not False else {})})]

    def cmd(self, prompt: str, pf: Path, sid: str, flags: list[str]) -> str:
        """sh reads the prompt file into the one argument (tmux refuses a command over about 16 KB). Past
        ARG_PROMPT_MAX bytes even that fails (Linux takes one argument of 128 KB at most, and the agent
        exits at once, "Argument list too long"), so the brief goes in as the system prompt (`long_brief`)."""
        if len(prompt.encode('utf-8')) > ARG_PROMPT_MAX:
            pf = pf.with_suffix('.cmd-prompt')
            pf.write_text(self.long_brief(prompt, sid), encoding='utf-8')
        return shlex.quote(C.run['agent']) + f' "$(cat {shlex.quote(str(pf))})" ' + shlex.join(flags)

    def argv(self, prompt: str, pf: Path, sid: str, flags: list[str]) -> list[str]:
        if len(prompt) > ARGV_PROMPT_MAX:
            prompt = self.long_brief(prompt, sid)
        return [plat.exe(C.run['agent']), prompt, *flags]

    @staticmethod
    def long_brief(prompt: str, sid: str) -> str:
        """Keep a brief too long for a command line in `<notes>/<sid>.brief`, which `flags` hands to every
        start and resume of `sid` as the system prompt (a resumed session does not keep the one it started
        with); the short first message that points at it. Read whole, unlike a file the agent would have to
        page through with its Read tool."""
        marker = 'agent-runner task brief'
        C.notes(f'{sid}.brief').write_text(f'# {marker}\n\n{prompt}', encoding='utf-8')
        return LONG_BRIEF.format(marker=marker)

    @staticmethod
    def trust(d: Path) -> None:
        """Accept Claude Code's "do you trust this folder?" dialog for `d` ahead of time: an interactive session
        in a new worktree otherwise waits on it, and no setting turns it off. The answer lives per folder in
        `~/.claude.json` (or `$CLAUDE_CONFIG_DIR/.claude.json`)."""
        # ponytail: read-modify-replace; a running Claude rewriting the file at the same instant can drop it,
        # and the next start writes it again
        cfg_dir = os.environ.get('CLAUDE_CONFIG_DIR')
        f = Path(cfg_dir) / '.claude.json' if cfg_dir else Path.home() / '.claude.json'
        try:
            data = json.loads(f.read_text(encoding='utf-8')) if f.exists() else {}
        except (OSError, ValueError):
            return  # unreadable or mid-write: leave it; the dialog shows, as before
        proj = data.setdefault('projects', {}).setdefault(str(d.resolve()), {})
        if proj.get('hasTrustDialogAccepted'):
            return
        proj['hasTrustDialogAccepted'] = True
        tmp = f.with_name(f'{f.name}.agent-runner.tmp')
        try:
            f.parent.mkdir(parents=True, exist_ok=True)  # a $CLAUDE_CONFIG_DIR not made yet: Claude makes it too
            tmp.write_text(json.dumps(data, indent=2), encoding='utf-8')
            os.replace(tmp, f)
        except OSError:
            return  # cannot write there: the dialog shows, as before

    def fix_cmd(self, prompt: str) -> list[str]:
        return [plat.exe(C.run['agent']), '-p', prompt, '--permission-mode', 'bypassPermissions',
                '--disallowedTools', 'AskUserQuestion', '--model', C.run['fix_model'], *lean()]

    def find_transcript(self, sid: str) -> str | None:
        return next(iter(glob.glob(os.path.expanduser(f'~/.claude/projects/*/{sid}.jsonl'))), None)

    def fork_flags(self, sid: str) -> list[str]:
        """Added to a fix session's flags: it starts as a copy of session `sid` (a task's own), from any folder,
        under an id of its own. [] where the backend cannot: the session starts fresh."""
        return ['--resume', sid, '--fork-session'] if self.find_transcript(sid) else []

    def entry(self, d: dict) -> dict | None:
        return d

    def limits(self) -> bool:
        """Claude's usage-limit text ("resets 3pm") and its handling (`limit_only`) apply."""
        return True


def pi_argv0() -> list[str]:
    """Run Pi's Node CLI directly on Windows instead of through npm's .cmd shim."""
    exe = plat.exe(C.run['agent'])
    if plat.WINDOWS and exe.lower().endswith('.cmd'):
        cli = Path(exe).parent / 'node_modules' / '@earendil-works' / 'pi-coding-agent' / 'dist' / 'bundle' / 'cli.js'
        node = Path(exe).parent / 'node.exe'
        if cli.exists():
            return [str(node) if node.exists() else (shutil.which('node') or 'node'), str(cli)]
    return [exe]


class Pi(Claude):
    """Pi: interactive too, ended by the bundled `pi_idle.ts` extension after `idle` s settled at the prompt
    with nothing in the editor; `once` is print mode (exits after its turn), for a fix session with no pane.
    `pi_hooks.ts` runs the repo's Claude PreToolUse hooks. Pi reads the prompt file itself (`@file`), at any size. Sessions live in `<notes>/pi-sessions`, their
    entries turned into Claude's shape (`entry`)."""
    report_exit = True

    @staticmethod
    def trust(d):
        pass  # Pi asks no folder question

    def flags(self, sid, model, idle, resume, once):
        if resume and not transcript(sid):
            raise FileNotFoundError(f'Pi session {sid} is missing')
        ext = lambda name: ['-e', str(Path(__file__).with_name(name))]
        flags = ext('pi_hooks.ts')  # the repo's Claude PreToolUse guards, in print mode too
        flags += ['--print'] if once else [*ext('pi_idle.ts'), '--runner-idle', str(idle)]
        flags += ['--session-id', sid, '--session-dir', str(C.notes('pi-sessions')), '--approve']
        if model:
            flags += ['--model', model]
        if C.run['lean']:
            shell = 'powershell' if plat.WINDOWS else 'bash'
            flags += ['--tools', f'read,{shell},edit,write', '--no-extensions', '--no-mcp',
                      '--no-skills', '--no-prompt-templates', '--no-themes']
        return flags

    def cmd(self, prompt, pf, sid, flags):
        return shlex.join([*pi_argv0(), *flags, '--', f'@{pf}'])

    def argv(self, prompt, pf, sid, flags):
        return [*pi_argv0(), *flags, '--', f'@{pf}']

    def fix_cmd(self, prompt):
        return agent_argv(prompt, str(uuid.uuid4()), C.run['fix_model'], MASTER_IDLE, 'master', once=True)

    def find_transcript(self, sid):
        return next((str(p) for p in C.notes('pi-sessions').glob(f'*_{sid}.jsonl')), None)

    def fork_flags(self, sid):
        return []  # ponytail: Pi sessions could be copied under a new id; a repair starts fresh there

    def entry(self, entry):
        """A Pi session record as a Claude one: role -> type, Pi's stop reasons and usage keys, and errors
        marked as API errors (transient ones resumable). None for a message that is neither user nor
        assistant. Pi retries rate limits itself, so one that reaches here is not resumed."""
        if entry.get('type') != 'message':
            return entry
        message = entry.get('message', {})
        role = message.get('role')
        if role not in ('user', 'assistant', 'toolResult'):
            return None
        entry['type'] = 'assistant' if role == 'assistant' else 'user'
        message['stop_reason'] = {'stop': 'end_turn', 'toolUse': 'tool_use',
                                  'length': 'max_tokens'}.get(message.get('stopReason'))
        if usage := message.get('usage'):
            message['usage'] = {
                'input_tokens': usage.get('input', 0),
                'cache_read_input_tokens': usage.get('cacheRead', 0),
                'cache_creation_input_tokens': usage.get('cacheWrite', 0),
            }
        if message.get('stopReason') == 'error':
            text = message.get('errorMessage') or 'Pi model request failed'
            entry['isApiErrorMessage'] = True
            permanent = re.search(
                r'\b(?:400|401|403|404|413|422|429)\b|authentication|unauthorized|'
                r'forbidden|billing|rate.?limit|invalid.?request', text, re.I)
            transient = re.search(
                r'network|fetch failed|ECONN|EAI_AGAIN|ETIMEDOUT|timeout|timed? out|'
                r'connection|\b5\d\d\b|overloaded|unavailable', text, re.I)
            entry['error'] = 'server_error' if transient and not permanent else 'invalid_request'
            message['content'] = [{'type': 'text', 'text': text}]
        return entry

    def limits(self):
        return False  # Claude's reset text and sidecar cleanup do not apply to Pi providers


BACKENDS = {'claude': Claude(), 'pi': Pi()}


def backend() -> Claude:
    """The configured backend: `[run] backend`, settled by `Config`."""
    return BACKENDS[C.run['backend']]


def agent_flags(sid: str, model: str, idle: int, resume: bool = False, once: bool = False) -> list[str]:
    """The session flags after the prompt. `resume` continues the session `sid` instead of starting it (its
    transcript keeps the id); `once` is a session with no pane, which exits after one answer."""
    if copilot():  # its Stop hook is written into the checkout by copilot_hooks
        return ['--session-id', sid, '--allow-all', '--no-ask-user', '--no-auto-update', '--model', model,
                *deny_push(), *lean()]
    return backend().flags(sid, model, idle, resume, once)


def prompt_flag() -> list[str]:
    """What goes before the prompt: Copilot CLI takes it as `-i`, Claude Code as its first argument."""
    return ['-i'] if copilot() else []


def deny_push() -> list[str]:
    """Copilot CLI refuses `git push` itself when `[git] push = false`, so the agent is told why at once."""
    return [] if C.push_remote else ['--deny-tool', 'shell(git push)']


def copilot_hooks(cwd: Path, idle: int) -> None:
    """Copilot CLI has no `--settings`: the Stop hook goes in the checkout's `.github/copilot/settings.local.json`
    (keep it git-ignored), which Copilot reads for a trusted folder. Other keys in that file are kept."""
    f = cwd / '.github' / 'copilot' / 'settings.local.json'
    try:
        cur = json.loads(f.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        cur = {}
    exe, *args = [*runner_cmd(), 'run', '--stop-hook', '--idle', str(idle)]
    cur.setdefault('hooks', {})['Stop'] = [{'type': 'command', 'exec': exe, 'args': args, 'timeoutSec': 30}]
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(cur, indent=2) + '\n', encoding='utf-8')


def copilot_trust(*dirs: Path) -> None:
    """Add `dirs` to Copilot CLI's trusted folders: it asks before working in an untrusted one, and loads no
    repo hooks there, and nobody is there to answer."""
    f = copilot_home() / 'config.json'
    try:
        lines = f.read_text(encoding='utf-8-sig').splitlines(keepends=True)
        n = next((i for i, l in enumerate(lines) if not l.lstrip().startswith('//')), len(lines))
        head = lines[:n]  # Copilot writes `//` comment lines above the JSON
        conf = json.loads(''.join(lines[n:]))
    except (OSError, ValueError):
        log(f'could not read {f}: trust {", ".join(map(str, dirs))} in Copilot CLI by hand')
        return
    have = conf.setdefault('trustedFolders', [])
    norm = lambda p: os.path.normcase(os.path.abspath(p)).rstrip('\\/')  # noqa: E731
    new = [str(d) for d in dirs if not any(norm(d) == norm(t) or norm(d).startswith(norm(t) + os.sep)
                                           for t in have)]
    if not new:
        return
    have += new
    tmp = f.with_name(f.name + '.agent-runner')
    tmp.write_text(''.join(head) + json.dumps(conf, indent=2) + '\n', encoding='utf-8')
    os.replace(tmp, f)
    log(f'Copilot CLI now trusts {", ".join(new)} (trustedFolders in {f})')


REMOTE_ENV_FLAGS = ('CLAUDE_CODE_USE_BEDROCK', 'CLAUDE_CODE_USE_VERTEX', 'CLAUDE_CODE_USE_FOUNDRY')


def remote_off_why(dialog: bool = True) -> str:
    """Why `[run] remote = 'auto'` leaves Remote Control off, or '' when it can work: Remote Control is Claude
    Code on a claude.ai login, so not pi or Copilot CLI, not an API key or token, not Bedrock, Vertex or Foundry,
    not another ANTHROPIC_BASE_URL. `dialog`: also off while Claude Code's one-time "Enable Remote Control?" has
    not been answered yes (`remote_ready` asks it at a terminal), which would hold a session in a hidden pane."""
    if pi():
        return 'backend pi (Remote Control is Claude Code\'s)'
    if copilot():
        return 'agent copilot (Remote Control is Claude Code\'s)'
    for k in ('ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN'):
        if os.environ.get(k):
            return f'{k} is set (Remote Control needs a claude.ai login)'
    for k in REMOTE_ENV_FLAGS:
        if os.environ.get(k, '').strip().lower() not in ('', '0', 'false', 'no', 'off'):
            return f'{k} is set (Remote Control needs a claude.ai login)'
    if (base := os.environ.get('ANTHROPIC_BASE_URL', '').strip()) and \
            urllib.parse.urlsplit(base).hostname != 'api.anthropic.com':
        return f'ANTHROPIC_BASE_URL is {base}, not api.anthropic.com'
    if dialog and not remote_dialog_seen():
        return ('Claude Code has not been told yes to Remote Control yet (run `claude remote-control` once, or '
                f'{RUNNER} at a terminal, and answer y)')
    return ''


def remote_dialog_seen() -> bool:
    try:
        return bool(json.loads(claude_json().read_text(encoding='utf-8')).get('remoteDialogSeen'))
    except (OSError, ValueError, AttributeError):
        return False


def remote_on() -> bool:
    """`[run] remote`, resolved: control sessions and the control server on Remote Control. 'auto' is on when
    `remote_off_why` finds nothing; true forces it (still never for pi or Copilot CLI); false keeps it off."""
    v = C.run['remote']
    if v == 'auto':
        return not remote_off_why()
    return bool(v) and not copilot() and not pi()


def remote_slots_on() -> bool:
    """`[run] remote_slots`: the slots on Remote Control too (never under 'auto' alone, and never pi or Copilot)."""
    return C.run['remote_slots'] is True and not copilot() and not pi()


def remote_any() -> bool:
    return remote_on() or remote_slots_on()


def remote_line() -> str:
    """The run's one log line on Remote Control: what is on it, or (under 'auto') why it is off."""
    on, slots = remote_on(), remote_slots_on()
    if on or slots:
        what = 'control sessions and the slots' if on and slots else 'control sessions' if on else 'slots'
        return f'remote control on: the {what} show at {REMOTE_URL} and in the Claude apps; Enter here opens it'
    if C.run['remote'] == 'auto':
        return f'remote control off: {remote_off_why()}; [run] remote = true forces it'
    return ''  # false: off, as asked, and nothing to say


def remote_flags(name: str, cwd: Path | None) -> list[str]:
    """`[run] remote_slots`: the session shows in claude.ai/code and the Claude apps as "<task title> · <repo> s2 ·
    B646" (the title leads, the id stays for referring to it), where a person can watch it and type to it. Claude
    Code only, and only an interactive session (not Pi, not Copilot).
    (`[run] remote` alone puts only the control sessions there: `control_argv`.)"""
    if not remote_slots_on():
        return []
    tid = git('branch', '--show-current', cwd=cwd).stdout.strip().removeprefix('task/') if cwd else ''
    title = short_title_of(tid, 50) if tid else ''
    return ['--remote-control', ' · '.join(x for x in (title, f"{ROOT.name} {name.replace('slot', 's')}", tid) if x)]


def short_title_of(tid: str, width: int = 60) -> str:
    """Task `tid`'s `short_title` from TODO.md or DONE.md, '' when neither has it."""
    for f in (C.todo, C.done):
        try:
            text = f.read_text(encoding='utf-8')
        except OSError:
            continue
        for l in text.splitlines():
            if (m := TASK.match(l)) and m.group(2) == tid:
                return short_title(m.group(3), width)
    return ''


def agent_cmd(prompt: str, sid: str, model: str, idle: int, name: str, resume: bool = False,
              cwd: Path | None = None) -> str:
    """The agent command line for one task, for sh (tmux, and the POSIX sequential run). The prompt is
    written to `<notes>/<name>.prompt` and goes in from there (`Claude.cmd`, `Pi.cmd`)."""
    pf = C.notes(f'{name}.prompt')
    pf.write_text(prompt, encoding='utf-8')
    if copilot():
        return shlex.join([C.run['agent'], *prompt_flag()]) + f' "$(cat {shlex.quote(str(pf))})" ' + \
            shlex.join(agent_flags(sid, model, idle, resume))
    return backend().cmd(prompt, pf, sid, agent_flags(sid, model, idle, resume) + remote_flags(name, cwd))


def agent_argv(prompt: str, sid: str, model: str, idle: int, name: str, resume: bool = False,
               once: bool = False, cwd: Path | None = None) -> list[str]:
    """The same command as an argv, for Windows, where no POSIX shell stands between us and the agent. The
    prompt is written to `<notes>/<name>.prompt` all the same."""
    pf = C.notes(f'{name}.prompt')
    pf.write_text(prompt, encoding='utf-8')
    if copilot():
        if len(prompt) > ARGV_PROMPT_MAX:
            prompt = (f'Your instructions for this session are in {pf.as_posix()}, too long to pass on a Windows '
                      f'command line. Read that whole file first, then follow it.')
        return [plat.exe(C.run['agent']), *prompt_flag(), prompt, *agent_flags(sid, model, idle, resume, once)]
    return backend().argv(prompt, pf, sid, agent_flags(sid, model, idle, resume, once) +
                          ([] if once else remote_flags(name, cwd)))


def brief_for(tid: str, cwd: Path) -> str:
    try:
        plan_dir = C.plan_dir if C.plan_external else cwd / os.path.relpath(C.plan_dir, C.root)
        return '\n'.join(P.brief(tid, root=cwd, plan_dir=plan_dir))
    except SystemExit as e:
        return f'({C.command} plan brief {tid} produced nothing: {e})'


def prompt_for(tid: str, n: int, slots: int, cwd: Path, branch: str) -> str:
    """The first turn of a task's session: `[run] prompt` (a file) if set, else PROMPT, filled in.

    Placeholders a custom template may use: {tid} {n} {runner} {branch} {others} {earlier} {rules} {test}
    {journal} {extra} {followups} {brief}. Any other `{name}` is left as it is. `[run] prompt_extra` may use them too
    (a slot's own emulator, say: "KIT_PCSX2={n} is set").
    """
    r = C.run
    journal = os.path.relpath(C.journal, C.root).replace(os.sep, '/') if C.journal else ''
    journal_at = (f'{journal}/{tid}/notes.md (if it exists, an earlier attempt wrote it: then '
                  f'{journal}/{tid}/<date>-<slug>/notes.md)' if C.raw['plan']['journal_layout'] == 'id'
                  else f'{journal}/<date>-{tid.lower()}-<slug>/')
    wip = not git('rev-parse', '--verify', '-q', f'refs/heads/wip/{tid}').returncode
    vals = dict(
        tid=tid, n=n, runner=C.command, branch=branch,
        publish=(PUBLISH if C.push_remote else NO_PUSH).format(runner=C.command, tid=tid),
        others=OTHERS if slots > 1 else '',
        earlier=(f'An earlier attempt that could not be merged is on wip/{tid} (`git log {branch}..wip/{tid}`, '
                 f'and the ledger line in {r["notes"]}/ledger.md says why). Read it before starting over.\n'
                 if wip else ''),
        rules=f'read {r["rules"]} first' if r['rules'] else 'the README, and AGENTS.md or CLAUDE.md if there is one',
        test=(f'The test gate is `{r["test"]}`. `done` runs it, and it must pass.' if r['test'] else
              'There is no test gate, so say in the commit message how you checked the work.'),
        journal=(f'\nWrite the task\'s journal as you go, in {journal_at}: what you did, '
                 f'what you tried that failed, and under **Not verified** everything you could not check, with '
                 f'why (or `none`). A skipped check that is written down is useful; a silent one is a bug '
                 f'nobody will find.\n' if journal else ''),
        extra=f'\n{r["prompt_extra"].strip()}\n' if r['prompt_extra'] else '',
        brief=brief_for(tid, cwd),
    )
    kinds, _ = P.kinds()
    vals['followups'] = FOLLOWUPS.format(runner=C.command, kinds='; '.join(f'{k} {v}' for k, v in kinds.items()))
    vals['extra'] = vals['extra'].format_map(_Keep(vals))  # `prompt_extra` may say {n}, {tid}, {runner}
    template = (ROOT / r['prompt']).read_text(encoding='utf-8') if r['prompt'] else PROMPT
    prompt = template.format_map(_Keep(vals))
    policies = []
    if r['include_task_id_in_commit']:
        policies.append(f'Include task ID `{tid}` at the start of the commit subject.')
    else:
        policies.append(f'Do not include task ID `{tid}` in the commit subject; task tracking is separate.')
    if r['comment_policy'] == 'minimal':
        policies.append('Only add comments when necessary to explain non-obvious intent or constraints.')
    if P.concept(tid):
        prompt = f'{prompt.rstrip()}\n\n' + CONCEPT_PROMPT.format(runner=C.command, tid=tid)
    elif wizards_on():
        prompt = f'{prompt.rstrip()}\n\n' + WIZARD_PROMPT.format(
            runner=C.command, tid=tid, template=WIZARD_TEMPLATE, path=C.notes('wizards', f'{tid}.sh'))
    return f'{prompt.rstrip()}\n\nProject policies:\n' + '\n'.join(f'- {policy}' for policy in policies)


CONCEPT_PROMPT = """\
{tid} is a concept task: do not build it. Research the repo (the code, the plan, how similar things are done \
here) and publish one page with the Artifact tool that lays out the options, usually two or three: for each, \
what it looks like or does (a sketch, a mock-up or an example where that says it best), the files it touches, \
and its trade-off; then your recommendation and why. A person picks one from that page, often on a phone, so \
make it short, concrete and readable at a glance. Change no product code; commit only notes you wrote (the \
journal). Finish with `{runner} done {tid} "<msg>" --artifact <the page's URL>`: it is refused without one, and \
it files the build task, blocked until the person approves an option."""


class _Keep(dict):
    def __missing__(self, k: str) -> str:
        return '{' + k + '}'


SLOTS = 1  # how many slots this run has; `cmd_run` sets it, for {slots} in `[run] slot_env`


def shared_env() -> list[str]:
    """`[run] slot_env` entries that are not per slot (no {n}), such as a compiler cache, {slots} filled in."""
    return [e.replace('{slots}', str(SLOTS)) for e in C.run['slot_env'] if '{n}' not in e]


def merge_env() -> dict:
    """The merge worktree's gate environment: ours and `shared_env`, so the merge builds the way the slots do."""
    return {**os.environ, **env_vars(shared_env())}


def slot_env(n: int | None) -> list[str]:
    """A slot's environment, as NAME=value: `AGENT_RUNNER=1`; the config file when it came from
    AGENT_RUNNER_CONFIG and every variable `[run] pass_env` names that is set (a tmux pane does not inherit
    the runner's environment, so a wrapper's own variables must be passed on by name); then `[run]
    slot_env` with {n} (the slot) and {slots} filled in. `n=None` is the master window's: `shared_env` in
    place of `[run] slot_env`, so it builds in the merge worktree the way the gate there does."""
    env = ['AGENT_RUNNER=1'] + ([] if n is None else [f'AGENT_RUNNER_SLOT={n}'])  # `finished_mark`
    env.append(f'CLAUDE_CODE_TMPDIR={session_tmp()}')
    if os.environ.get('AGENT_RUNNER_CONFIG') and C.file:
        env.append(f'AGENT_RUNNER_CONFIG={C.file}')
    env += [f'{k}={os.environ[k]}' for k in C.run['pass_env'] if k in os.environ]
    return env + (shared_env() if n is None else [e.format(n=n, slots=SLOTS) for e in C.run['slot_env']]) + \
        [f'{k}={v}' for k, v in no_push_env().items()] + \
        ([f'{PRESENCE_ENV}={quiet_file("slots")}'] if n is not None and remote_slots_on() and silent() is not False
         else [])


# While the file it names exists, Claude Code pulses "client present" just before each push-triggering state
# (needs input, turn done), so the server skips those pushes. It cannot stop the "session ready" push: the server
# sends that as the session registers, before the first pulse (R2, from the Claude Code 2.1.329 binary).
PRESENCE_ENV = 'CLAUDE_CLIENT_PRESENCE_FILE'


def silent() -> bool | str:
    """`[run] silent`: 'launch' (a Remote Control session is quiet only while it starts), True (quiet for good),
    False (no presence file: Claude Code pushes as it would for any session)."""
    return C.run['silent']


def quiet_file(who: str, on: bool = True) -> Path:
    """`<notes>/quiet-<who>`, the file a Remote Control session's CLAUDE_CLIENT_PRESENCE_FILE names: made (`on`) or
    removed. "slots" is kept for good (a slot's later pushes stay quiet; not its start push, see PRESENCE_ENV);
    a control session's and the control server's are there only while it starts, so its later pushes arrive."""
    f = C.notes(f'quiet-{who}')
    try:
        f.touch() if on else f.unlink(missing_ok=True)
    except OSError:
        pass
    return f


def env_vars(env) -> dict[str, str]:
    """NAME=value entries as a dict."""
    return dict(e.split('=', 1) for e in env)


def no_push_env() -> dict[str, str]:
    """With `[git] push = false`: git config, as environment, that makes every push from an agent session fail."""
    if C.push_remote:
        return {}
    count = int(os.environ.get('GIT_CONFIG_COUNT', '0'))
    env = {f'GIT_CONFIG_{part}_{i}': os.environ[f'GIT_CONFIG_{part}_{i}']
           for i in range(count) for part in ('KEY', 'VALUE')}
    env['GIT_CONFIG_COUNT'] = str(count + len(NO_PUSH_URLS))
    for i, url in enumerate(NO_PUSH_URLS, start=count):
        env[f'GIT_CONFIG_KEY_{i}'] = 'url.agent-runner-no-push:.pushInsteadOf'
        env[f'GIT_CONFIG_VALUE_{i}'] = url
    return env


def save_leftovers(d: Path, tid: str, branch: str) -> str | None:
    """Keep what a slot's session left uncommitted on a branch before anything resets the worktree.

    A session can end before its `done` commits (killed, or stopped mid-gate), and the next `start` resets
    the slot. With no commits of its own the work goes to wip/<tid>, where the task's next attempt is told
    to look; otherwise (or with a wip/<tid> already there) to leftover/<tid>, so the merge never takes in
    untested edits. The branch's own index and files are left as they are. Returns the branch, '' when
    there was nothing to keep, or None when the save failed."""
    if not git('status', '--porcelain', cwd=d).stdout.strip():
        return ''
    fd, idx = tempfile.mkstemp(prefix='agent-runner-index-')
    os.close(fd)
    env = {**os.environ, 'GIT_INDEX_FILE': idx}
    try:
        g = lambda *a: git(*a, cwd=d, env=env)
        if g('read-tree', 'HEAD').returncode or g('add', '-A').returncode:
            return None
        tree = g('write-tree').stdout.strip()
        if tree and tree == git('rev-parse', 'HEAD^{tree}', cwd=d).stdout.strip():
            return ''  # only what a commit can't hold changed (a submodule's own edits, say): nothing to keep
        msg = f'{tid} wip: uncommitted when the session ended (saved by the runner before the slot was reset)'
        c = g('commit-tree', tree, '-p', 'HEAD', '-m', msg).stdout.strip()
    finally:
        os.unlink(idx)
    if not c:
        return None
    mine = git('rev-list', '--count', f'{branch}..HEAD', cwd=d).stdout.strip()
    wip = not git('rev-parse', '--verify', '-q', f'refs/heads/wip/{tid}', cwd=d).returncode
    to = f'wip/{tid}' if mine == '0' and not wip else free_branch(f'leftover/{tid}')
    if git('branch', to, c, cwd=d).returncode:
        return None
    files = git('diff', '--name-only', 'HEAD', c, cwd=d).stdout.split()
    many = f'{len(files)} file{"s" if len(files) != 1 else ""}'
    note(f'{tid}: the session left {many} uncommitted; saved on {to}')
    log(f'{tid}: the session left {many} uncommitted ({", ".join(files)[:200]}); saved on {to}')
    if out := push(ROOT, to):
        log(out)
    return to


def free_branch(name: str) -> str:
    """`name`, or `name-2`, `name-3`, … when an earlier attempt already holds it: a ref is never overwritten."""
    k, out = 1, name
    while not git('rev-parse', '--verify', '-q', f'refs/heads/{out}').returncode:
        k += 1
        out = f'{name}-{k}'
    return out


def edited_elsewhere(files) -> list[str]:
    """Checkouts outside the runner's own slots (the main checkout, a person's or a chat session's worktree)
    with uncommitted edits to any of `files`, as 'path (file, file)'. Work there is invisible to the runner
    until it is committed, so a task started on the same files is likely to redo it or to conflict."""
    files = set(files)
    if not files:
        return []
    out = []
    listed = git('worktree', 'list', '--porcelain', cwd=ROOT).stdout.splitlines()
    for d in (Path(l[len('worktree '):]) for l in listed if l.startswith('worktree ')):
        if d.parent == SLOTS_DIR and re.fullmatch(r's\d+|merge\d*|fix\d+', d.name):
            continue
        if not d.is_dir():  # a worktree whose folder was deleted (git lists it as prunable)
            continue
        st = git('status', '--porcelain', '--untracked-files=no', cwd=d)
        if st.returncode:
            continue
        hit = sorted(files & {l[3:].split(' -> ')[-1] for l in st.stdout.splitlines()})
        if hit:
            out.append(f'{d} ({", ".join(hit[:4])}{", …" if len(hit) > 4 else ""})')
    return out


def vacate(n: int, d: Path, head: str, branch: str, what: str) -> bool:
    """Slot n's worktree `d` (on branch `head`) reset clean, what its session left uncommitted saved first
    (`save_leftovers`); False, and nothing reset, when that save failed."""
    if save_leftovers(d, head.removeprefix('task/') if head.startswith('task/') else f's{n}', branch) is None:
        log(f'slot {n}: uncommitted edits there could not be saved; not resetting it {what}')
        return False
    clean(d)
    return True


def slot_header(n: int, what: str) -> tuple[Path, int]:
    """A session's header line in slot n's log: (the log, its size before the line, where `limit_only` reads from)."""
    logfile = C.notes(f'slot{n}.log')
    since = logfile.stat().st_size if logfile.exists() else 0  # in append mode tell() is not that
    with open(logfile, 'a', encoding='utf-8') as f:
        f.write(f'\n=== {dt.datetime.now().isoformat(timespec="seconds")} {what}\n')
    return logfile, since


# --- disk: worktrees keep their builds warm, within limits ----------------------

GB = 1 << 30
DISK_AT = [0.0]  # when `low_disk` last cleaned
DISK_SAID = [False]


def usage(p: Path) -> tuple[int, float]:
    """(bytes on disk, newest write) under `p`, symlinks not followed (a `links` target is not the slot's)."""
    total, newest = 0, 0.0
    walk = os.walk(p) if p.is_dir() and not p.is_symlink() else [(str(p.parent), [], [p.name])]
    for root, _, files in walk:
        for f in files:
            try:
                st = os.lstat(os.path.join(root, f))
            except OSError:
                continue
            total += getattr(st, 'st_blocks', 0) * 512 or st.st_size
            newest = max(newest, st.st_mtime)
    return total, newest


def du(d: Path) -> int:
    return usage(d)[0]


def stale_first(d: Path, split: int, least: int) -> list[tuple[float, int, Path]]:
    """`d`'s git-ignored files and folders, least recently written first: (newest write, bytes, path). A folder
    bigger than `split` is broken into what is in it (three levels at most), so a build tree's stale parts go
    one by one and its live ones stay: target/debug/incremental before target/debug/deps. Nothing under `least`
    bytes: small ignored files free nothing and may be someone's notes or settings."""
    out: list[tuple[float, int, Path]] = []

    def add(p: Path, depth: int) -> None:
        if p.is_symlink():
            return  # `links`, runner.toml: put there by `worktree`, not build output
        size, newest = usage(p)
        if p.is_dir() and size > split and depth < 3:
            for k in p.iterdir():
                add(k, depth + 1)
        elif size >= least:
            out.append((newest, size, p))

    for rel in git('ls-files', '--others', '--ignored', '--exclude-standard', '--directory', '-z',
                   cwd=d).stdout.split('\0'):
        if rel:
            add(d / rel.rstrip('/'), 0)
    return sorted(out, key=lambda t: t[0])


def trim(d: Path, what: str, why: str = '') -> bool:
    """Shrink worktree `d` when it is over `[run] slot_max_gb`, or clean it whole when `why` says it must be (the
    disk is nearly full). Only ever for a worktree nobody works in: a free slot before its next task, the merge
    worktree under MERGE. True when it removed anything (`worktree` puts `links` back).

    Over the cap, by default the least recently written git-ignored parts go until it is at half the cap: the
    build folders recent tasks used stay warm, the ones old tasks left behind go. `[run] slot_clean`, when set,
    is run instead, in both cases."""
    cap = C.run['slot_max_gb'] * GB
    size = du(d)
    if not why:
        if not cap or size <= cap:
            return False
        why = f'over [run] slot_max_gb ({C.run["slot_max_gb"]} GB)'
        if not C.run['slot_clean']:
            gone, names = 0, []
            for _, n, p in stale_first(d, cap // 4, cap // 500):  # 50 GB: folders over 12 GB split, none under 100 MB
                if size - gone <= cap // 2:
                    break
                if p.is_dir():
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    p.unlink(missing_ok=True)
                for q in p.parents:  # no empty folders left behind
                    if q == d or any(q.iterdir()):
                        break
                    q.rmdir()
                gone += n
                names.append(p.relative_to(d).as_posix())
            more = f' and {len(names) - 5} more' if len(names) > 5 else ''
            log(f'{what}: {size / GB:.1f} GB, {why}: removed the least recently written build output '
                f'({", ".join(names[:5])}{more}), now {du(d) / GB:.1f} GB')
            return bool(names)
    cmd = C.run['slot_clean'] or 'git clean -ffdXq'
    try:
        sp.run(cmd, shell=True, cwd=str(d), capture_output=True, timeout=C.run['timeout'])
    except sp.TimeoutExpired:
        log(f'{what}: `{cmd}` ran past [run] timeout; stopped')
    log(f'{what}: {size / GB:.1f} GB, {why}: cleaned with `{cmd}`, now {du(d) / GB:.1f} GB')
    return True


def free_gb() -> float:
    return shutil.disk_usage(SLOTS_DIR if SLOTS_DIR.is_dir() else ROOT).free / GB


def low_disk(free_slots) -> bool:
    """Less free disk than `[run] min_free_gb`: clean the free slots and the merge worktree (at most every 10 min),
    and True while it stays low, so no new task starts and fills the disk up."""
    want = C.run['min_free_gb']
    if not want or free_gb() >= want:
        DISK_SAID[0] = False
        return False
    if time.time() - DISK_AT[0] > 600:
        DISK_AT[0] = time.time()
        why = f'the disk is under [run] min_free_gb ({want} GB free)'
        for n in free_slots:
            if (d := SLOTS_DIR / f's{n}').is_dir():
                trim(d, f'slot {n}', why)
        if (d := SLOTS_DIR / 'merge').is_dir() and MERGE.acquire(blocking=False):
            try:
                trim(d, 'merge worktree', why)
            finally:
                MERGE.release()
        if (d := SLOTS_DIR / 'merge2').is_dir() and not AHEAD_BUSY.locked() and not AHEADS:
            trim(d, 'merge-ahead worktree', why)
        with FIX_DIRS_LOCK:
            idle = [d for d in SLOTS_DIR.glob('fix*') if re.fullmatch(r'fix\d+', d.name) and int(d.name[3:]) not in FIX_DIRS]
            FIX_DIRS.update(int(d.name[3:]) for d in idle)  # held while cleaned, so no fix starts in one
        try:
            for d in idle:
                trim(d, f'fix worktree {d.name[3:]}', why)
        finally:
            with FIX_DIRS_LOCK:
                FIX_DIRS.difference_update(int(d.name[3:]) for d in idle)
                FIX_DIRS_LOCK.notify_all()
        if free_gb() >= want:
            return False
    if not DISK_SAID[0]:
        DISK_SAID[0] = True
        log(f'disk: {free_gb():.1f} GB free, under [run] min_free_gb ({want} GB), even with the free worktrees '
            f'cleaned: no new task starts until there is room')
        print('\a', end='', flush=True)
    return True


def drop_extra_slots(slots: int, busy) -> None:
    """Remove slot worktrees past this run's count (`slots` was lowered) that nothing uses: no session, nothing
    uncommitted. Moved aside at once, deleted in the background; a task branch lives on in the repo."""
    rm = lambda t: threading.Thread(target=shutil.rmtree, args=(t,), kwargs={'ignore_errors': True},
                                    daemon=True).start()
    for t in SLOTS_DIR.glob('.removed-*'):  # what a run that was stopped mid-delete left
        rm(t)
    for d in SLOTS_DIR.glob('s*'):
        if not re.fullmatch(r's\d+', d.name) or int(d.name[1:]) <= slots or int(d.name[1:]) in busy:
            continue
        if git('status', '--porcelain', cwd=d).stdout.strip() or git('rev-parse', cwd=d).returncode:
            log(f'slot {d.name[1:]}: past the {slots} slots, but it has uncommitted work (or is not a worktree): kept')
            continue
        size = du(d)
        trash = SLOTS_DIR / f'.removed-{d.name}-{int(time.time())}'
        d.rename(trash)
        git('worktree', 'prune')
        rm(trash)
        log(f'slot {d.name[1:]}: past the {slots} slots and unused: removed ({size / GB:.1f} GB)')


def start(n: int, task, branch: str, model: str, idle: int, slots: int):
    tid = task[0]
    finished_mark(n).unlink(missing_ok=True)  # the last task's `done`, not this one's
    d = worktree(n, branch)
    head = git('symbolic-ref', '-q', '--short', 'HEAD', cwd=d).stdout.strip()
    if not vacate(n, d, head, branch, f'for {tid}'):
        return None
    if trim(d, f'slot {n}'):
        worktree(n, branch)  # the `links` the clean took
    co = git('checkout', '-q', '-B', f'task/{tid}', branch, cwd=d)
    if co.returncode:  # e.g. another worktree still holds task/<ID>: never start an agent on the wrong branch
        log(f'slot {n}: checkout task/{tid} failed: {co.stderr.strip()[:200]}')
        return None
    sid = str(uuid.uuid4())
    if copilot():
        copilot_hooks(d, idle)
    prompt = prompt_for(tid, n, slots, d, branch)
    logfile, since = slot_header(n, f'{tid} session {sid}')
    if not (pid := MUX.open(n, d, prompt, sid, model, idle, slot_env(n), logfile)):
        log(f'slot {n}: the session for {tid} did not start in {MUX.where(n)}')
        return None
    log(f'slot {n}: {tid} ({task[1]}; {", ".join(sorted(task[2])) or "no files listed"})')
    for where in edited_elsewhere(task[2]):
        log(f'slot {n}: {tid} heads into uncommitted edits outside the runner, in {where}: '
            f'if that is the same work, stop the slot; if not, commit it before {tid} lands')
    return pid, sid, since


RESUME = """The runner resumed this session: it was cut off ({why}). Whatever you had running in the \
background ended with it, and so did anything `[run] on_exit` stops. Look at `git status` and at what you \
did last, then carry on with task {tid} where you left off and finish it as the first message of this \
session says."""


def resume(n: int, tid: str, sid: str, why: str, branch: str, model: str, idle: int):
    """Continue the session `sid` of task `tid` in slot n, where it ran: its transcript names that worktree's
    paths, so no other slot will do. A slot still on task/<tid> is used as it is; one that moved on gets the
    task back from wip/<tid> (the edits the session left, saved when the slot was reset), uncommitted again.
    """
    d = worktree(n, branch)
    head = git('symbolic-ref', '-q', '--short', 'HEAD', cwd=d).stdout.strip()
    if head != f'task/{tid}':
        if not vacate(n, d, head, branch, f'to resume {tid}'):
            return None
        saved = git('log', '-1', '--format=%s', f'wip/{tid}', '--').stdout.startswith(f'{tid} wip: uncommitted')
        src = f'wip/{tid}' if saved else f'task/{tid}'
        if git('rev-parse', '--verify', '-q', src).returncode:
            log(f'slot {n}: nothing of {tid} to resume from (no task/{tid}, and no wip/{tid} the runner saved)')
            return None
        if git('checkout', '-q', '-B', f'task/{tid}', src, cwd=d).returncode:
            log(f'slot {n}: checkout task/{tid} failed; not resuming it')
            return None
        if saved:
            git('reset', '-q', 'HEAD~1', cwd=d)  # the saved edits are uncommitted again, as the session left them
            git('branch', '-M', src, free_branch(f'resumed/{tid}'))  # kept, but no longer read as an earlier attempt
    logfile, since = slot_header(n, f'{tid} resume {sid} ({why})')
    if not (pid := MUX.open(n, d, RESUME.format(why=why, tid=tid), sid, model, idle, slot_env(n), logfile,
                            resume=True)):
        log(f'slot {n}: the session for {tid} did not resume in {MUX.where(n)}')
        return None
    log(f'slot {n}: {tid} resumed ({why})')
    return pid, sid, since


# --- terminals: one per slot -----------------------------------------------------

class TmuxMux:
    """tmux panes in this repo's window "agents-<repo>", tagged @runner=sN; the pane's output goes to the
    slot log."""
    name = 'tmux'

    def open(self, n: int, cwd: Path, prompt: str, sid: str, model: str, idle: int, env: list[str],
             logfile: Path, resume: bool = False) -> int | None:
        try:
            return pane(f's{n}', cwd, agent_cmd(prompt, sid, model, idle, f'slot{n}', resume, cwd), env, logfile)
        except RuntimeError as e:
            log(f'slot {n}: {e}')
            return None

    def panes(self) -> dict[str, tuple[str, int]]:
        return panes()

    def session_id(self, pid: int) -> str | None:
        return session_id(pid)

    def where(self, n: int) -> str:
        return f'pane s{n}'


class ShimMux:
    """Windows: a Windows Terminal tab per slot (`wt`), or a console window per slot (`console`).

    Neither hands back the agent's pid the way tmux does: `wt.exe` only asks the running terminal to open
    a tab and exits, and the tab gets the terminal's environment, not ours. So each slot runs through a
    shim (`run --slot-shim <job>`, `slot_shim`): it reads the argv, directory and environment from
    `<notes>/slotN.job`, starts the agent, and keeps its pid in `<notes>/slotN.live` while it runs. The
    loop, a restart's adopt and the Stop hook all read that marker. The console window gets the shim too,
    so the two behave the same. Nothing captures a console's output, so the slot log has only the header
    lines here, and a usage limit is read from the transcript alone.
    """

    def __init__(self, name: str):
        self.name = name

    def open(self, n, cwd, prompt, sid, model, idle, env, logfile, resume=False):
        job, marker = C.notes(f'slot{n}.job'), C.notes(f'slot{n}.live')
        ended = marker.with_suffix('.exit')
        marker.unlink(missing_ok=True)
        ended.unlink(missing_ok=True)
        envd = env_vars(env)
        job.write_text(json.dumps({'argv': agent_argv(prompt, sid, model, idle, f'slot{n}', resume, cwd=cwd), 'cwd': str(cwd),
                                   'env': envd, 'marker': str(marker)}), encoding='utf-8')
        shim = [*runner_cmd(), 'run', '--slot-shim', str(job)]
        if self.name == 'wt':
            sp.Popen(['wt.exe', '-w', 'agents', 'new-tab', '--title', f's{n}', '-d', str(cwd), *shim],
                     stdin=sp.DEVNULL, stdout=sp.DEVNULL, stderr=sp.DEVNULL)
        else:
            plat.spawn_console(shim, cwd, {**os.environ, **envd}, hidden=HIDDEN[0])
        for _ in range(100):
            if pid := marker_pid(marker):
                return pid
            if ended.exists():  # the agent ended before the marker was seen, or never started
                log(f'slot {n}: the agent ended at once: {ended.read_text(encoding="utf-8").strip()[:300]}')
                return None
            time.sleep(0.3)
        return None

    def panes(self) -> dict[str, tuple[str, int]]:
        """{sN: (marker, pid)} for every slot whose marker is there; the caller checks the pid is alive."""
        out = {}
        for m in C.notes().glob('slot*.live'):
            if re.fullmatch(r'slot\d+', m.stem) and (pid := marker_pid(m)):
                out[f's{m.stem[4:]}'] = (str(m), pid)
        return out

    def session_id(self, pid: int) -> str | None:
        for m in C.notes().glob('slot*.live'):
            if marker_pid(m) == pid:
                try:
                    args = json.loads(m.with_suffix('.job').read_text(encoding='utf-8'))['argv']
                except (OSError, ValueError, KeyError):
                    return None
                return (sids(args) or [None])[0]
        return None

    def where(self, n: int) -> str:
        return f'the "s{n}" tab' if self.name == 'wt' else f'the console window of slot {n}'


def marker_pid(marker: Path) -> int:
    try:
        return int(marker.read_text(encoding='utf-8').strip() or 0)
    except (OSError, ValueError):
        return 0


def run_session(argv: list[str], cwd: str, env: dict, marker: Path) -> int:
    """Run one agent session in this terminal, its pid in `marker` while it runs (see ShimMux). The agent
    gets AGENT_RUNNER_MARKER, which is how the Stop hook finds the pid to end on Windows."""
    proc = sp.Popen(argv, cwd=cwd, env={**os.environ, **env, 'AGENT_RUNNER_MARKER': str(marker)})
    marker.write_text(str(proc.pid), encoding='utf-8')
    try:
        while True:
            try:
                return proc.wait()
            except KeyboardInterrupt:
                continue  # Ctrl-C in the tab is for the agent (it interrupts a turn), not for the shim
    finally:
        marker.unlink(missing_ok=True)


def slot_shim(job: str) -> int:
    """`run --slot-shim <job>`: what a Windows tab or console window runs (see ShimMux).

    Always exits 0, so Windows Terminal closes the tab; and a job runs once, so a tab restarted with Enter
    does not resume a finished session behind the runner's back."""
    f = Path(job)
    spec = json.loads(f.read_text(encoding='utf-8'))
    if spec.get('started'):
        print('This slot\'s session has ended; the runner starts the next one. Close this tab.')
        return 0
    f.write_text(json.dumps({**spec, 'started': True}), encoding='utf-8')
    ended = Path(spec['marker']).with_suffix('.exit')
    try:
        code = run_session(spec['argv'], spec['cwd'], spec['env'], Path(spec['marker']))
        ended.write_text(f'exit code {code}', encoding='utf-8')
    except OSError as e:
        ended.write_text(f'could not start {spec["argv"][0]}: {e}', encoding='utf-8')
        print(f'could not start the agent: {e}')
    return 0


MUX: TmuxMux | ShimMux = TmuxMux()  # what `cmd_run` picked


# --- merging a finished branch -------------------------------------------------

class TurnLock:
    """A lock whose waiters take it by rank, not in whatever order the scheduler wakes them: `acquire(rank=f)`
    waits until the lock is free and its `f()` (then its arrival) is the lowest of everyone waiting. Ranks are
    read when the lock comes free, so they may change while a waiter waits. A non-blocking acquire, or one
    without a rank, never jumps a waiter."""

    def __init__(self) -> None:
        self._cv = threading.Condition()
        self._held = False
        self._waiters: dict[int, object] = {}  # arrival -> rank function
        self._seq = 0

    def _first(self) -> int:
        return min(self._waiters, key=lambda k: (self._waiters[k](), k))

    def acquire(self, blocking: bool = True, timeout: float = -1, rank=None) -> bool:
        with self._cv:
            if not self._held and not self._waiters:
                self._held = True
                return True
            if not blocking:
                return False
            self._seq += 1
            me = self._seq
            self._waiters[me] = rank or (lambda: 9)
            end = None if timeout is None or timeout < 0 else time.monotonic() + timeout
            try:
                while self._held or self._first() != me:
                    left = None if end is None else end - time.monotonic()
                    if left is not None and left <= 0:
                        return False
                    self._cv.wait(left if left is not None else 5)  # 5 s: a rank may change without a release
                self._held = True
                return True
            finally:
                del self._waiters[me]
                self._cv.notify_all()

    def release(self) -> None:
        with self._cv:
            if not self._held:
                raise RuntimeError('release unlocked TurnLock')
            self._held = False
            self._cv.notify_all()

    def locked(self) -> bool:
        return self._held

    @contextmanager
    def turn(self, rank):
        self.acquire(rank=rank)
        try:
            yield
        finally:
            self.release()

    def __enter__(self) -> bool:
        return self.acquire()

    def __exit__(self, *exc) -> None:
        self.release()


MERGE = TurnLock()  # one merge into the shared branch at a time (`merge_rank` orders who goes next)
LANDING = threading.Lock()  # held while `land` moves the main checkout: an interrupted run waits for it


def joinable(f: str) -> bool:
    """True when the runner may join both sides of a conflict in `f` itself (`[run] joinable`, globs).

    Only for files where a line is a whole record and two agents each added records: a changelog, a
    journal. Not the task list and its archive, whatever the config says: git merges those by task
    (`plan.merge3`), and a conflict left there is in prose. Never prose, even prose that is only appended to. A union joins
    *lines*, and two sides that both reflowed one paragraph give it no line to agree on. It then stitches
    them into something that reads like a sentence and is not one, and a reader believes it. A paragraph
    needs reading, so it goes to a fix session.
    """
    if f in (plan_rel('TODO.md'), plan_rel('DONE.md')):
        return False  # git merged it by task already (`plan.merge3`): what still conflicts there is prose
    return any(fnmatch.fnmatch(f, g) for g in [*C.run['joinable'], *C.run['join']])


def custom_join(f: str, sides: list[str], text: str, tid: str, cwd: Path) -> str | None:
    """`[run.join]`: hand a joined file to the project's own joiner. The text to keep, or None to refuse.

    Some record-per-line files cannot be joined blind: an address list where both sides gave one name two
    different addresses must go to somebody who can pick, not to whichever branch merged first. The
    project knows its own records, so it gets a command per glob, with these placeholders (all paths):

        {ours} {base} {theirs}   the three sides of the conflict
        {union}                  both sides' lines joined (what the runner would keep without this)
        {out}                    where to write the result; it starts as a copy of {union}
        {file}                   the file's path in the repo

    Exit 0 keeps {out}; anything else refuses the join, and the conflict goes to a fix session (its output
    is logged). A command rather than a Python hook, so it can be any language, and so the project's own
    CLI (`./kit oracle-join ...`) is the one place that knows the format.
    """
    cmd = next(c for g, c in C.run['join'].items() if fnmatch.fnmatch(f, g))
    u, out = C.notes(f'union.{tid}.joined'), C.notes(f'union.{tid}.out')  # per task: joins run in threads at once
    u.write_text(text, encoding='utf-8')
    out.write_text(text, encoding='utf-8')
    vals = dict(ours=sides[0], base=sides[1], theirs=sides[2], union=str(u), out=str(out), file=f)
    try:
        r = sp.run(cmd.format_map({k: plat.quote(v) for k, v in vals.items()}), shell=True, cwd=str(cwd),
                   capture_output=True, text=True, errors='replace', timeout=C.run['timeout'])
    except sp.TimeoutExpired:
        log(f'{tid}: the [run.join] command for {f} ran past [run] timeout ({C.run["timeout"]}s); join refused')
        return None
    if r.returncode:
        log(f'{tid}: the [run.join] command for {f} refused the join (exit {r.returncode}): '
            + ' / '.join((r.stdout + r.stderr).strip().splitlines()[-3:])[:300])
        return None
    try:
        return out.read_text(encoding='utf-8')
    finally:
        u.unlink(missing_ok=True)
        out.unlink(missing_ok=True)


def union(files: list[str], tid: str, cwd: Path) -> bool:
    """Join both sides of a conflict in every file `joinable` allows; a file with a `[run.join]` command
    goes through it (`custom_join`), which may refuse."""
    for f in files:
        sides = []
        for stage in (2, 1, 3):  # ours, base, theirs
            t = C.notes(f'union.{tid}.{stage}')  # per task: joins run in threads at once
            t.write_text(git('show', f':{stage}:{f}', cwd=cwd).stdout, encoding='utf-8')
            sides.append(str(t))
        out = git('merge-file', '-p', '--union', *sides, cwd=cwd)
        text = out.stdout if out.returncode >= 0 else None
        if text is not None and any(fnmatch.fnmatch(f, g) for g in C.run['join']):
            text = custom_join(f, sides, text, tid, cwd)
        for t in sides:
            Path(t).unlink(missing_ok=True)
        if text is None:
            return False
        (cwd / f).write_text(text, encoding='utf-8')
        git('add', f, cwd=cwd)
    return True


def _next_free(k: str, taken: set[str]) -> str:
    """The next id of `k`'s kind that `taken` does not hold: P119 -> P124, P118a -> P118c."""
    if m := re.fullmatch(r'(.*\d)([a-z])', k):
        last = max((t[-1] for t in taken if len(t) == len(k) and t.startswith(m.group(1))), default='`')
        return m.group(1) + chr(ord(last) + 1)
    if m := re.fullmatch(r'(.*[^\d])(\d+)', k):
        n = [int(t[len(m.group(1)):]) for t in taken if t.startswith(m.group(1)) and t[len(m.group(1)):].isdigit()]
        return f'{m.group(1)}{max(n, default=0) + 1}'
    return k + 'r'


def renumber_doubles(ref: str, onto: str, tid: str, cwd: Path) -> str:
    """`ref`, or a commit on top of it that renumbers the tasks it added under an id `onto` already uses.

    A branch files a follow-up with the next id its own copy of the plan has free, while main, meanwhile,
    may have handed that id to another task. The merge keeps both lines (`plan.merge3`), but under one id, so a
    tick or a pick would take one for the other: P118's two follow-ups vanished that way. So before a merge the branch's
    new task gets the next id free on both sides, and every line the branch added or changed that names it
    follows; the change is logged. Run before each merge, the tested one and the one onto main."""
    files = [plan_rel('TODO.md'), plan_rel('DONE.md')]
    base = git('merge-base', onto, ref, cwd=cwd).stdout.strip()
    show = lambda rev, f: git('show', f'{rev}:{f}', cwd=cwd).stdout.splitlines() if rev else []

    def ids(rev):
        return {m.group(2).rstrip('.'): re.sub(r'^- \[.\] ', '', l)
                for f in files for l in show(rev, f) if (m := TASK.match(l))}

    old, theirs, ours = ids(base), ids(ref), ids(onto)
    doubled = [k for k in theirs if k not in old and k in ours and k != tid and theirs[k] != ours[k]]
    if not doubled:
        return ref
    taken, new = set(old) | set(theirs) | set(ours) | P.reserved(cwd), {}
    for k in doubled:
        new[k] = _next_free(k, taken)
        taken.add(new[k])
    P.reserve(cwd, *new.values())  # or the next branch's renumber takes the same one (MD175 -> 180 -> 181 -> 182)
    pat = re.compile(r'\b(' + '|'.join(map(re.escape, new)) + r')\b')
    idx = C.notes(f'renumber.{tid}.index')  # one per task: merges of different tasks run in threads at once
    env = {**os.environ, 'GIT_INDEX_FILE': str(idx)}
    g = lambda *a, **kw: git(*a, cwd=cwd, env=env, **kw)
    try:
        g('read-tree', ref)
        for f in files:
            was, now = set(show(base, f)), show(ref, f)
            if not now:
                continue
            text = '\n'.join(l if l in was else pat.sub(lambda m: new[m.group(1)], l) for l in now) + '\n'
            blob = g('hash-object', '-w', '--stdin', input=text).stdout.strip()
            g('update-index', '--cacheinfo', f'100644,{blob},{f}')
        for k, v in new.items():  # the long form the branch wrote for it goes with it
            was, now = plan_rel(f'{P.TASKS}/{k}.md'), plan_rel(f'{P.TASKS}/{v}.md')
            blob = git('rev-parse', '-q', '--verify', f'{ref}:{was}', cwd=cwd).stdout.strip()
            if blob and git('cat-file', '-e', f'{base}:{was}', cwd=cwd).returncode:
                g('update-index', '--force-remove', was)
                g('update-index', '--add', '--cacheinfo', f'100644,{blob},{now}')
        tree = g('write-tree').stdout.strip()
        pairs = ', '.join(f'{k} -> {v}' for k, v in new.items())
        c = g('commit-tree', tree, '-p', ref, '-m',
              f'{tid}: renumber {pairs} ({onto} already uses the id)').stdout.strip()
    finally:
        idx.unlink(missing_ok=True)
    if not c:
        log(f'{tid}: could not renumber {", ".join(doubled)}; the merge may drop a task')
        return ref
    log(f'{tid}: renumbered {pairs}: {onto} gave the id to another task meanwhile')
    note(f'{tid}: renumbered {pairs} before the merge')
    return c


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
{build_step}3. Then `git commit --no-edit` to land the merge, and stop. Do not push. Do not run the test suite: \
the runner runs it as soon as you are done. Do not merge, rebase or delete anything else, do not \
`git stash`, and do not touch the other worktrees under {slots_dir}.
4. If it cannot be resolved honestly — the two sides contradict each other and picking needs a human — run \
`git merge --abort` and say why in one line. That is a real answer, not a failure.

What happened on earlier merges in this run (the ledger's tail):
{history}
"""


BUILD_STEP = """3a. Before you commit, run `{build}` (a build, not the tests). Git merged every file it did not stop on \
without reading it, so the two sides can clash there too: a function or item both added under one name, a \
caller of something the other side renamed or removed. Fix what the build reports that the merge caused, \
in the fewest lines and keeping both sides, and build again until it passes. An error {branch} already has \
is not yours: leave it.
"""

REPAIR = """[[The merge of task/{tid} into {branch} is|The merges of {tasks} into {branch} are]] committed in this \
checkout[[ (as {merge})|, one after another on top of {base}]], and the test gate fails on [[it. task/{tid}|the \
result. Each branch]] may or may not have passed the gate on its own (where a run leaves the testing to the \
gate, it never ran it), so the cause is [[its own change, or |]]a clash between [[the two sides|them]] that git \
merged without a conflict: an item [[both|two of them]] added under one name, a caller of something [[the other \
side|another]] renamed or removed, a test that checks what [[the other side|another]] changed on purpose. Repair \
it[[|, so all of them land after one more gate run]]. Nobody will answer questions: decide, and say what you \
decided.

The gate's output ends with this (all of it is in {log}):

{tail}

1. [[`git diff {merge}^1 {merge} --stat` (what task/{tid} brought) and `git diff {merge}^2 {merge} --stat` \
(what {branch} brought) show the two sides|`git log --first-parent --format='%h %s' {base}..HEAD` lists the \
merges; `git diff <merge>^1 <merge> --stat` shows what each one brought]]. Find where they meet.
2. Fix the clash in the fewest lines, so that **[[both sides'|every branch's]] intent survives**. Change nothing \
the clash does not need. You are not reviewing the code and you are not redoing [[task {tid}|any task]]. A test \
one [[side wrote for behaviour the other side|branch wrote for behaviour another]] changed on purpose is updated \
to the merged behaviour, and you say so.
3. {check}Then commit the fix on top[[ of the merge|]]: `git add` what you changed and `git commit -m "{tid}: \
repair the [[merge|batch merge of {ids}]] into {branch}: <what clashed>"`. Do not amend or reset the merge[[|s]], \
do not push, do not merge, rebase or delete anything else, do not `git stash`, and do not touch the other \
worktrees under {slots_dir}. The runner runs the whole gate again when you are done.
4. If you cannot fix it honestly (the failure is {branch}'s own, [[the two sides contradict|one branch is broken by \
itself, two branches contradict]] each other and picking needs a human), commit nothing and say why in one line. [[|The runner then merges each branch on its own. ]]That is a real answer.
5. If it is a flaky test (it passes when you rerun it, and nothing [[the merge|these merges]] changed touches what it checks), commit nothing and make your last line `FLAKE: <test name>[, <test name>…]`. The runner runs the gate once more and files the flake to be fixed.
"""  # [[one merge|a batch]]: `repair_prompt` keeps one side


OWN = """This is a copy of your own session from task {tid}, picked up again by the runner: task/{tid} is \
finished and merged into {branch}, and the merge fails the test gate. You know the change, so you repair it. \
You are in another checkout now, {cwd}: work only there. Your old worktree belongs to another task, and the paths \
you used before are under another folder.

"""  # put before a one-task REPAIR when the repair session is a copy of the task's own (`fork_flags`)


def repair_prompt(batch: bool, **vals) -> str:
    text = re.sub(r'\[\[(.*?)\|(.*?)\]\]', lambda m: m.group(2 if batch else 1), REPAIR, flags=re.S)
    return text.format(**vals)


MASTER_PANE = False  # `run` sets it under tmux: fix and repair sessions get a window of their own
MASTER_IDLE = 90     # s a master session sits at its prompt, its answer given, before the Stop hook ends it


def last_words(sid: str) -> str:
    """The last thing session `sid` said, for fixer.log: why it committed what it did, or nothing."""
    said = ''
    for d in entries(sid):
        if d.get('type') == 'assistant':
            text = [c.get('text', '') for c in d.get('message', {}).get('content', []) if isinstance(c, dict)]
            said = '\n'.join(t for t in text if t) or said
    return said.strip()


def fix_session(prompt: str, cwd: Path, fh, keep: dict | None = None, fork: str = '') -> int:
    """Run one fix or repair session in `cwd` to its end; its exit code. Raises what `sp.run` raises for a
    missing agent or a timeout.

    Under tmux it is an ordinary session in the window "master-<repo>", so a human can watch it work, or
    take it over by typing; the Stop hook (Pi: `pi_idle.ts`) ends it once it has been idle `MASTER_IDLE`
    seconds, and its last words go to `fh`. Without tmux it is `-p` (Pi: `--print`), its output in `fh`.
    A pane session outlives the runner: `keep` (what it was started on) goes to `<notes>/master.json` with
    its pid, so the next run adopts it (`adopt_merge`) instead of starting the merge over under it.
    With `fork` (a session id), it starts as a copy of that session (`fork_flags`), knowing what it did.
    """
    timeout = C.run['fix_timeout']
    more = backend().fork_flags(fork) if fork else []
    if not MASTER_PANE:
        env = {**os.environ, **env_vars(slot_env(None))}  # as the master pane gets it
        if not copilot():
            return sp.run(fix_cmd(prompt) + more, cwd=str(cwd), stdout=fh, stderr=sp.STDOUT, stdin=sp.DEVNULL,
                          env=env, timeout=timeout).returncode
        for attempt in range(3):  # Copilot CLI gives up on a model call that failed (a network drop): retry
            fh.flush()
            start = os.path.getsize(fh.name)
            r = sp.run(fix_cmd(prompt) + more, cwd=str(cwd), stdout=fh, stderr=sp.STDOUT, stdin=sp.DEVNULL, env=env,
                       timeout=timeout)
            fh.flush()
            with open(fh.name, 'rb') as f:
                f.seek(start)
                said = f.read().decode('utf-8', errors='replace')
            if not r.returncode or attempt == 2 or not COPILOT_FAILED.search(said):
                return r.returncode
            wait = RESUME_AFTER * 2 ** attempt
            log(f'the fix session could not reach the model; trying again in {wait}s')
            time.sleep(wait)
    if not shutil.which(C.run['agent']):
        raise FileNotFoundError(C.run['agent'])
    sid = str(uuid.uuid4())
    fh.write(f'in tmux window "{window("master")}", session {sid}\n')
    fh.flush()
    cmd = agent_cmd(prompt, sid, C.run['fix_model'], MASTER_IDLE, 'master') + (' ' + shlex.join(more) if more else '')
    try:
        pid = pane('master', cwd, cmd, slot_env(None))
    except RuntimeError as e:  # no session ran: the caller reads the merge as one it did not finish
        log(f'the fix session did not start: {e}')
        fh.write(f'{e}\n')
        return 1
    until = time.time() + timeout
    if keep:
        C.notes('master.json').write_text(json.dumps({**keep, 'pid': pid, 'sid': sid, 'until': until}), encoding='utf-8')
    try:
        if not wait_session(pid, until):
            fh.write(last_words(sid) + '\n')
            raise sp.TimeoutExpired(cmd, timeout)
    finally:
        if keep:  # only this session's record: a fix-ahead session (no keep) beside a locked repair leaves its own
            m = C.notes('master.json')
            try:
                if json.loads(m.read_text(encoding='utf-8')).get('sid') == sid:
                    m.unlink()
            except (OSError, ValueError):
                pass
    fh.write(last_words(sid) + '\n')
    return 0


def wait_session(pid: int, until: float) -> bool:
    """Wait for the session `pid` to end: False when it ran to `until` and was ended."""
    while alive(pid):
        if time.time() >= until:
            for p in [*plat.children(pid), pid]:
                plat.terminate(p)
            return False
        time.sleep(5)
    return True


HELD = 'refs/agent-runner/held/'  # + <ID>/<start>[-<ref>]: what a fix or repair session made from there


def held(tid: str, start: str, ref: str = '') -> str:
    return f'{HELD}{tid}/{start}' + (f'-{ref}' if ref else '')


def kept(tid: str, start: str, ref: str, d: Path, kind: str) -> bool:
    """A fix (`ref` merged onto `start`) or repair (commits on `start`) session made the same thing in an
    earlier run, or before a rebuild: `d` is moved to what it made, and no session runs again."""
    if not (h := git('rev-parse', '-q', '--verify', held(tid, start, ref)).stdout.strip()):
        return False
    git('merge', '--abort', cwd=d)
    clean(d, h)
    log(f'{tid}: reused what the {kind} session made of this merge before ({h[:12]})')
    return True


def keep_made(s: dict, d: Path) -> bool:
    """Record what the session `s` (master.json) made in `d`, when it made what its kind should: a fix commits
    the merge of `ref` onto `start`, a repair commits on top of `start` and leaves nothing uncommitted."""
    head = git('rev-parse', 'HEAD', cwd=d).stdout.strip()
    if s['kind'] == 'fix':
        ok = git('rev-parse', '-q', '--verify', 'MERGE_HEAD', cwd=d).returncode != 0 and \
            git('rev-parse', '-q', '--verify', 'HEAD^2', cwd=d).stdout.strip() == s['ref'] and \
            git('rev-parse', '-q', '--verify', 'HEAD^1', cwd=d).stdout.strip() == s['start']
    else:
        ok = head != s['start'] and not git('merge-base', '--is-ancestor', s['start'], head, cwd=d).returncode and \
            not git('status', '--porcelain', '--untracked-files=no', cwd=d).stdout.strip()
    if ok:
        git('update-ref', held(s['tid'], s['start'], s.get('ref', '')), head)
    return ok


def adopt_merge(d: Path) -> None:
    """Before a merge resets the merge worktree `d`: wait out what an earlier run left going in it, a fix or
    repair session in the master window or a gate run, and keep what they made (`held`, `GATES`). The merge
    is then built again as it was, and reuses them instead of doing them again."""
    m = C.notes('master.json')
    try:
        s = json.loads(m.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        s = None
    if s and Path(s.get('cwd', '')) == d:
        if alive(s['pid']) and MUX.session_id(s['pid']) == s['sid']:
            log(f'{s["tid"]}: adopted the {s["kind"]} session an earlier run left going in the master window')
            if not wait_session(s['pid'], s['until']):
                log(f'{s["tid"]}: the adopted {s["kind"]} session ran past [run] fix_timeout; ended')
        if keep_made(s, d):
            log(f'{s["tid"]}: kept what the {s["kind"]} session made ({git("rev-parse", "--short", "HEAD", cwd=d).stdout.strip()})')
    m.unlink(missing_ok=True)
    for s in sorted(gate_runs(), key=lambda s: Path(s.get('cwd', '')) != d):  # the merge's, then merge2's
        batch = s.get('head') and git('cat-file', '-e', f'{s["head"]}^{{commit}}').returncode == 0 and \
            {'base': s['base'], 'tids': s['tids'], 'merged': s['head']}
        if Path(s.get('cwd', '')) != d:
            if batch:  # built ahead (merge2): its turn reuses it, and `merge_gate` waits for its gate by tree
                AHEADS.append(batch)
            continue
        if gate_alive(s):
            log(f'{s["tid"]}: adopted the gate run an earlier run left going on the merge; waiting for it')
        r = wait_gate(s)
        what = ' and '.join(s.get('tids') or [s['tid']])
        if r is None:
            log(f'{s["tid"]}: the adopted gate on {what} left no exit code; the merge is built and tested again')
            continue
        log(f'{s["tid"]}: the adopted gate on {what} ' + ('passed' if not r[0] else f'failed (exit {r[0]})'))
        if batch:
            AHEADS.insert(0, batch)  # its turn reuses that merge, as it was gated
            key = gate_key(d, s['head'])  # under this version's key too
            if r[0]:
                ADOPTED[key] = r  # the failure is that merge's: retests and repairs go from it, not a new gate
            else:
                (C.notes(GATES) / f'{key}.pass').touch()


ADOPTED: dict[str, tuple[int, str]] = {}  # a failed gate an earlier run left, by key: `merge_gate` answers it once


def gate_alive(s: dict) -> bool:
    """A gate (or session) record's process is still the one it names: its pid is alive and, where the OS
    tells (`plat.started`), started when the record says. After a reboot a days-old record's pid can be
    anyone's. A record without a start time (an older runner's) goes by the pid alone."""
    return alive(s.get('pid')) and ('start' not in s or s['start'] == plat.started(s['pid']))


def end_group(pid: int) -> None:
    """SIGTERM a gate's process group; gone already (or never a group leader) is fine."""
    try:
        os.killpg(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass


def gate_runs() -> list[dict]:
    """The merge gates running, or left by a run that ended: `<notes>/gates/<key>.json`."""
    out = []
    for f in sorted(C.notes(GATES).glob('*.json')) if C.notes(GATES).is_dir() else []:
        try:
            out.append({**json.loads(f.read_text(encoding='utf-8')), 'rec': str(f)})
        except (OSError, ValueError):
            f.unlink(missing_ok=True)
    return out


def wait_gate(s: dict) -> tuple[int, str] | None:
    """Wait for the gate run `s` (another thread's or an earlier run's) to end: `gate_done`'s answer."""
    while gate_alive(s) and time.time() < s['until']:
        time.sleep(5)
    if gate_alive(s):
        end_group(s['pid'])
    r = gate_done(s)
    Path(s['rec']).unlink(missing_ok=True)
    return r


AHEAD_BUSY = threading.Lock()  # held while build_ahead uses merge2
AHEAD_POLL = 30  # seconds between looks for tasks that finished during a gate
AHEADS: list[dict] = []  # merges built and gated already, for later turns: {'base', 'tids', 'merged'}
# (`build_ahead`, or adopted from an earlier run, `adopt_merge`); each turn takes the one on its base


def build_ahead(branch: str, base: str, done: threading.Event, taken: set[str]) -> None:
    """While the merge `base` is in its gate: the tasks that finished since, merged on top of it in a second
    worktree (merge2) and tested there beside it. When `base` lands, their turn reuses that merge, and with
    it the gate run already passed or under way (`merge_gate` goes by tree), instead of a gate from the start.
    A conflict a join cannot do is left for that task's turn (one fix session at a time)."""
    while not done.wait(AHEAD_POLL):
        if ahead_gate_running():  # the gate `base` waits on is merge2's own: checking out there swaps its tree
            continue
        if cands := sorted(WAITING - taken - set(LANDED) - ALONE - criticals(branch)):
            break
    else:
        return
    if C.run['batch_max']:
        cands = cands[:C.run['batch_max']]
    with AHEAD_BUSY:
        if not ahead_gate_running():
            _build_ahead(branch, base, cands)


def ahead_gate_running() -> bool:
    """A gate still running in merge2 that no ahead thread holds: one built ahead under an earlier run, which a
    restart adopted and a turn now waits on. A merge built ahead checks out over it, and the gate builds and
    tests a tree that is not the one it reports on (MD168b's gate, 11-17, ran P347's code)."""
    return any(Path(s.get('cwd', '')).name == 'merge2' and gate_alive(s) for s in gate_runs())


def _build_ahead(branch: str, base: str, cands: list[str]) -> None:
    d = worktree('merge2', branch)
    git('merge', '--abort', cwd=d)
    clean(d)
    git('checkout', '-q', '--detach', base, cwd=d)
    tids = []
    for t in cands:
        ref = renumber_doubles(f'task/{t}', 'HEAD', t, d)
        if (files := merge_into(d, ref, merge_message(t, ref), t)) is None or files and not joined(files, t, d):
            git('merge', '--abort', cwd=d)
            continue
        tids.append(t)
    if not tids:
        return
    if not C.plan_external:
        carry_notes(base, d)
        P.archive(d / plan_rel('TODO.md'), d / plan_rel('DONE.md'))
    plan_files = [plan_rel('TODO.md'), plan_rel('DONE.md')]
    if git('status', '--porcelain', '--', *plan_files, cwd=d).stdout.strip():
        git('commit', '-qm', f'{tids[0]}: archive ticked tasks', '--', *plan_files, cwd=d)
    batch = {'base': base, 'tids': tids, 'merged': git('rev-parse', 'HEAD', cwd=d).stdout.strip()}
    AHEADS.append(batch)
    log(f'{", ".join(tids)}: merged ahead on the merge under test; its gate runs beside that one')
    key = gate_key(d)
    rc, text = merge_gate(tids[0], d, merge_env(), {'base': base, 'tids': tids})
    log(f'{", ".join(tids)}: the gate on the merge built ahead ' + ('passed' if not rc else
        f'failed (exit {rc}; {C.notes(GATES) / key}.failed)'))
    if rc and batch in AHEADS:  # its turn has not come yet: it goes from this result, not a gate of its own
        ADOPTED[key] = rc, text


def reusable(a: dict, tid: str, base: str) -> bool:
    """Whether the merge `a`, built and gated already, is tid's turn's merge on the branch at `base`: built on
    it (or on a commit the branch moved on from by untested files only), with tid and riders still waiting."""
    return tid in a['tids'] and set(a['tids']) - {tid} <= WAITING - set(LANDED) and (
        a['base'] == base or git('merge-base', '--is-ancestor', a['base'], base).returncode == 0
        and all(map(untestable, git('diff', '--name-only', a['base'], base).stdout.split())))


def drop_ahead() -> None:
    """The batches built ahead are on a merge that will not land as it is: their gates are stopped, and their
    records gone with them (one left behind reads as a gate still to wait on)."""
    AHEADS.clear()
    for s in gate_runs():
        if Path(s.get('cwd', '')).name == 'merge2':
            if gate_alive(s):
                end_group(s['pid'])
            Path(s['rec']).unlink(missing_ok=True)


GATES = 'gates'  # <notes>/gates/<key>.pass: a tree the merge gate passed on (`merge_gate`)


def gate_key(d: Path, rev: str = 'HEAD') -> str:
    """The merge in `d`'s tree, with the gate command: a pass is one of this command on this tree. Files the
    gate does not test (`[run] untested`: the plan, notes) are left out, so a plan commit or a ticked task
    does not make a passed merge new."""
    files = git('ls-tree', '-r', rev, cwd=d).stdout.splitlines()
    tree = hashlib.sha1('\n'.join(f for f in files if not untestable(f.split('\t', 1)[-1])).encode()).hexdigest()
    return f'{tree}-{uuid.uuid5(uuid.NAMESPACE_OID, C.run["test"]).hex[:12]}'


GATE_DONE = threading.Lock()


def gate_done(s: dict) -> tuple[int, str] | None:
    """The finished gate run `s` (gates/<key>.json): (exit code, output), its pass kept; None when it never
    got to the end (ended, or killed with the machine), or another thread read it first."""
    with GATE_DONE:  # the ahead thread and the turn that reuses its merge both wait on merge2's gate
        if s['out'] not in GATE_RESULTS:
            GATE_RESULTS[s['out']] = _gate_done(s)
        return GATE_RESULTS[s['out']]


GATE_RESULTS: dict[str, tuple[int, str] | None] = {}  # what each gate run ended with, read once from its files


def _gate_done(s: dict) -> tuple[int, str] | None:
    out, rc = Path(s['out']), Path(s['out']).with_suffix('.rc')
    if out.with_suffix('.pass').exists():
        return 0, ''
    try:
        code, text = int(rc.read_text().strip()), out.read_text(encoding='utf-8', errors='replace').strip()
    except (OSError, ValueError):
        return None
    finally:
        rc.unlink(missing_ok=True)
    if not code:
        out.with_suffix('.pass').write_text(s['tid'] + '\n', encoding='utf-8')
        out.unlink(missing_ok=True)
        if s.get('full', True):
            (out.parent / FULL_PASS).touch()
    else:  # kept a week, for whoever looks into why it failed
        out.replace(out.with_suffix('.failed'))
    return code, text


FULL_PASS = 'full.last'  # <notes>/gates/full.last: touched when a whole `test` passes on a merge


def gate_cmd(base: str) -> tuple[str, bool]:
    """The command a merge's gate runs, and whether it is the whole `test`. With `[run] test_since`, only what
    changed since `base` is tested: the shared branch only moves on a passed gate, and the merge built ahead
    is on a merge whose own gate is still running (a failure there drops it). The whole `test` runs anyway
    once none has passed for `full_every_hours`, for what a selection misses."""
    since, hours = C.run['test_since'], C.run['full_every_hours']
    last = C.notes(GATES) / FULL_PASS
    if not since or not base or hours and (not last.exists() or last.stat().st_mtime < time.time() - hours * 3600):
        return C.run['test'], True
    return since.replace('{base}', base), False


def merge_gate(tid: str, d: Path, env: dict, batch: dict | None = None) -> tuple[int, str]:
    """`gate(d, full=True)` for a merge, as a run of its own that outlives the runner (a restart adopts it:
    `adopt_merge`), and one a tree it already passed on skips: a gate can take an hour."""
    if not (cmd := C.run['test']):
        return 0, ''
    if plat.WINDOWS:
        return gate(d, full=True, env=env)
    gates = C.notes(GATES)
    gates.mkdir(exist_ok=True)
    for f in gates.iterdir():
        if f.stat().st_mtime < time.time() - 7 * 86400:
            f.unlink(missing_ok=True)
    key = gate_key(d)
    if (gates / f'{key}.pass').exists():
        log(f'{tid}: the gate already passed on this exact merge; not run again')
        return 0, ''
    if r := ADOPTED.pop(key, None):
        log(f'{tid}: the gate failed on this exact merge under an earlier run; going from that result')
        return r
    rec = gates / f'{key}.json'
    for s in gate_runs():
        if s['rec'] == str(rec):
            if running := gate_alive(s):
                log(f'{tid}: a gate on this exact merge is already running (built ahead, or left by an earlier '
                    f'run); waiting for it')
            if (r := wait_gate(s)) is not None:
                if not running:
                    log(f'{tid}: the gate on this exact merge ended with exit {r[0]}; that result counts')
                return r
    out = gates / f'{key}.out'
    timeout = C.run['timeout']
    cmd, full = gate_cmd((batch or {}).get('base', ''))
    if not full:
        log(f'{tid}: the gate tests what changed since {batch["base"][:9]} ([run] test_since)')
    out.with_suffix('.rc').unlink(missing_ok=True)  # a gate killed before its end must not read as an old one's
    with GATE_DONE:
        GATE_RESULTS.pop(str(out), None)
    with open(out, 'w', encoding='utf-8') as fh:
        p = sp.Popen(f'({cmd}\n); echo $? > {shlex.quote(str(out.with_suffix(".rc")))}', shell=True, cwd=str(d),
                     env=env, stdout=fh, stderr=sp.STDOUT, stdin=sp.DEVNULL, start_new_session=True)
    s = {'tid': tid, 'pid': p.pid, 'start': plat.started(p.pid), 'out': str(out), 'until': time.time() + timeout, 'cwd': str(d), 'rec': str(rec),
         'full': full, **(batch or {}), 'head': git('rev-parse', 'HEAD', cwd=d).stdout.strip()}
    rec.write_text(json.dumps(s), encoding='utf-8')
    try:
        p.wait(timeout=timeout)
    except sp.TimeoutExpired:
        os.killpg(p.pid, signal.SIGTERM)
        p.wait()
        gate_done(s)
        return 124, f'`{cmd}` ran past [run] timeout ({timeout}s): counted as failing'
    finally:
        rec.unlink(missing_ok=True)
    return gate_done(s) or (p.returncode or 1, f'`{cmd}` left no exit code')


def fixer(head: str, prompt: str, cwd: Path, kind: str, to: str, keep: dict | None = None,
          fork: str = '') -> tuple[int | None, str]:
    """`fix_session` under a `head` line in fixer.log: (its exit code, ''), or why it did not run to its end
    (code 0 when there is no agent command, None when it timed out)."""
    with open(C.notes('fixer.log'), 'a', encoding='utf-8') as fh:
        fh.write(f'\n=== {dt.datetime.now().isoformat(timespec="seconds")} {head}\n')
        fh.flush()
        try:
            return fix_session(prompt, cwd, fh, keep, fork), ''
        except FileNotFoundError:
            return 0, f'no agent command to {to} with ([run] agent = {C.run["agent"]!r})'
        except sp.TimeoutExpired:
            return None, f'the {kind} session ran past {C.run["fix_timeout"]}s'


def fix_cmd(prompt: str) -> list[str]:
    """A fix session: one prompt, one answer, no session to keep — `-p`, so nothing types into a pane."""
    if copilot():
        return [plat.exe(C.run['agent']), '-p', prompt, '--allow-all', '--no-ask-user', '--no-auto-update',
                '--model', C.run['fix_model'], *deny_push(), *lean()]
    return backend().fix_cmd(prompt)


def fix_merge(tid: str, branch: str, files: list[str], cwd: Path, start: str = '', ref: str = '') -> str | None:
    """Give a conflict the join cannot do to a fresh agent session, in `cwd`. None when it landed.

    One session per merge, run to completion while the caller waits: ahead of the merge lock (`fix_ahead`),
    in a fix worktree of its own (fix1…), or under it in the merge worktree on a last try. Each one starts with an empty context and the
    ledger's tail, so the twentieth costs what the first did. (This replaced a long-lived
    "master" session. Under tmux it still runs in a window named "master": see `fix_session`.)

    Never fatal. A fixer that fails, times out, aborts or is not installed leaves the merge for the caller
    to abort, and the task is left for a human.
    """
    if not C.run['fix_merges']:
        return 'conflicts a join cannot resolve, and [run] fix_merges is off'
    led = C.notes('ledger.md')
    history = ''.join(led.read_text(encoding='utf-8').splitlines(True)[-12:]) if led.exists() else ''
    prompt = FIXER.format(tid=tid, branch=branch, files='\n'.join(f'  {f}' for f in files),
                          slots_dir=SLOTS_DIR, history=history.strip() or '(nothing yet: this is the first)',
                          build_step=BUILD_STEP.format(build=C.run['build'], branch=branch) if C.run['build'] else '')
    logfile = C.notes('fixer.log')
    log(f'{tid}: conflicts in {", ".join(files)} need reading — handing them to a fix session')
    keep = {'kind': 'fix', 'tid': tid, 'start': start, 'ref': ref, 'cwd': str(cwd)} if start else None
    code, why = fixer(f'{tid} {", ".join(files)}', prompt, cwd, 'fix', 'fix the conflicts', keep)
    if why:
        if code is None:
            note(f'{tid}: the fix session timed out after {C.run["fix_timeout"]}s')
        return why
    if git('rev-parse', '--verify', '-q', 'MERGE_HEAD', cwd=cwd).returncode == 0:
        return f'the fix session did not finish the merge (exit {code}); see {logfile}'
    if git('merge-base', '--is-ancestor', f'task/{tid}', 'HEAD', cwd=cwd).returncode:
        return f'the fix session aborted the merge; its reason is in {logfile}'
    if keep:
        keep_made(keep, cwd)
    note(f'{tid}: conflicts in {", ".join(files)} resolved by a fix session')
    log(f'{tid}: the fix session resolved {", ".join(files)} and committed the merge')
    return None


def repair_merge(tid: str, branch: str, cwd: Path, riders: list[str] = (), base: str = '') -> str | None:
    """Give a committed merge that fails the gate to a fresh agent session in `cwd`. None when it committed
    a repair on top of the merge (the caller runs the gate again), else why not. With `riders`, it is the
    whole batch (task/<tid> and theirs, merged on `base` one after another) that the session repairs.

    Like `fix_merge`: one session, under the merge lock, never fatal. It reads the gate's full output in
    `<notes>/merge-gate.log`, which `tested` wrote; the prompt carries the tail.
    """
    if not C.run['repair_merges']:
        return 'off ([run] repair_merges)'
    gate_log = C.notes('merge-gate.log')
    out = gate_log.read_text(encoding='utf-8') if gate_log.exists() else '(no gate output kept)'
    merge = git('log', '-1', '--merges', '--first-parent', '--format=%h', cwd=cwd).stdout.strip()
    tail = '\n'.join('    ' + l for l in out.splitlines()[-60:])
    r = C.run
    check = (f'Check it with `{r["build"]}` and, if the gate names failing tests, the gate for just those '
             f'({r["retest"] or r["test"]}). ' if r['build'] else
             f'Check it with the failing tests alone if you can; not the whole gate (`{r["test"]}`). ')
    ids = ', '.join([tid, *riders])
    own = ''
    if riders:
        prompt = repair_prompt(True, tid=tid, branch=branch, log=gate_log, tail=tail, check=check, slots_dir=SLOTS_DIR,
                               base=base[:12], ids=ids, tasks=', '.join(f'task/{t}' for t in [tid, *riders]))
        log(f'{tid}: the batch ({ids}) fails the gate — handing it to a repair session')
    else:
        prompt = repair_prompt(False, tid=tid, branch=branch, log=gate_log, tail=tail, check=check, slots_dir=SLOTS_DIR,
                               merge=merge)
        if (own := TASK_SID.get(tid, '')) and backend().fork_flags(own):
            prompt = OWN.format(tid=tid, branch=branch, cwd=cwd) + prompt
            log(f'{tid}: the merge fails the gate — handing it back to the task\'s own session (a copy of {own})')
        else:
            own = ''
            log(f'{tid}: the merge fails the gate — handing it to a repair session')
    before = git('rev-parse', 'HEAD', cwd=cwd).stdout.strip()
    if kept(tid, before, '', cwd, 'repair'):
        return None
    logfile = C.notes('fixer.log')
    keep = {'kind': 'repair', 'tid': tid, 'start': before, 'cwd': str(cwd)}
    if why := fixer(f'{ids} repair (gate failed)', prompt, cwd, 'repair', 'repair it', keep, own)[1]:
        return why
    head = git('rev-parse', 'HEAD', cwd=cwd).stdout.strip()
    if head == before:
        if names := flake_said(logfile):
            return FLAKE + ', '.join(names)
        return f'the repair session committed nothing; its reason is in {logfile}'
    if git('merge-base', '--is-ancestor', before, head, cwd=cwd).returncode:
        return f'the repair session rewrote the merge instead of committing on top; see {logfile}'
    if git('status', '--porcelain', '--untracked-files=no', cwd=cwd).stdout.strip():
        return f'the repair session left edits uncommitted; see {logfile}'
    keep_made(keep, cwd)
    log(f'{tid}: the repair session committed {git("rev-list", "--count", f"{before}..{head}", cwd=cwd).stdout.strip()} '
        f'fix(es) on the merge: {git("log", "-1", "--format=%s", cwd=cwd).stdout.strip()[:200]}')
    return None


def untestable(f: str) -> bool:
    """A change the test gate cannot see (`[run] untested`; the last glob that matches decides, `!glob` takes
    a file back). A merge that differs from what the branch tested only in these is not retested."""
    hit = False
    for g in C.run['untested']:
        if fnmatch.fnmatch(f, g.lstrip('!')):
            hit = not g.startswith('!')
    return hit


def gated(tid: str) -> bool:
    """task/<tid> is what `done`'s gate passed on: the tree its tested ref records."""
    tree = git('rev-parse', '-q', '--verify', f'{TESTED}{tid}^{{tree}}').stdout.strip()
    return bool(tree) and tree == git('rev-parse', '-q', '--verify', f'task/{tid}^{{tree}}').stdout.strip()


def tested(tid: str, d: Path, base: str, tids: list[str] | None = None) -> str | None:
    """Run the gate on the merge checked out in `d`: None when it passes, else why.

    With `[run] failures` and `retest`, a failure gets two more looks before it counts: rerun alone (a test
    that timed out under the other slots' load passes then), and rerun on `base`, the branch it merges into
    (one that already fails there the same way is not this task's doing, so it merges anyway, and says so).
    That one is the shared branch's own failure, though, so a critical task is filed to fix it (`file_flaky`);
    and when the whole `test` found it (`[run] test_since`'s daily run), it counts as that day's whole run:
    the failure is filed, and every later merge running the whole `test` again only to find it again would
    undo what `test_since` saves.
    """
    env = merge_env()
    full = gate_cmd(base)[1]
    rc, out = merge_gate(tid, d, env, {'base': base, 'tids': tids or [tid]})
    if not rc:
        if rx := C.run['flaky']:  # the gate's own rerun of a load flake passed: still a test to fix
            flaky(tid, [n for g in re.findall(rx, out, re.M) for n in re.split(r'[,\s]+', g) if n])
        return None
    C.notes('merge-gate.log').write_text(out + '\n', encoding='utf-8')  # for a repair session
    if rc in (130, -2):  # the run's Ctrl-C reached the gate: the main thread exits the process within moments
        threading.Event().wait(5)  # still here, so it was not the run's: a gate that exits 130 is a failure
    why = 'the tests fail after the merge: ' + ' / '.join(out.splitlines()[-4:])[:400]
    rx, cmd = C.run['failures'], C.run['retest']
    if not (rx and cmd and (names := sorted(set(re.findall(rx, out, re.M))))):
        return why
    FAILED[tid] = names  # for `blame`, if this is a batch that fails
    cmd = cmd.replace('{names}', ' '.join(map(plat.quote, names)))

    def retest() -> sp.CompletedProcess | None:
        try:
            return sp.run(cmd, shell=True, cwd=str(d), capture_output=True, text=True, env=env, timeout=C.run['timeout'])
        except sp.TimeoutExpired:
            log(f'{tid}: the retest of {", ".join(names)} ran past [run] timeout ({C.run["timeout"]}s); counted as failing')
            return None

    if (r := retest()) and not r.returncode:
        log(f'{tid}: {", ".join(names)} failed, then passed alone (load); counted as passing')
        flaky(tid, names)
        return None
    head = git('rev-parse', 'HEAD', cwd=d).stdout.strip()
    # the gate may have left files behind, and a checkout that refuses would rerun the tests on the merge
    clean(d)
    if (co := git('checkout', '-q', '--detach', base, cwd=d)).returncode:
        log(f'{tid}: could not check out {base[:12]} to rerun {", ".join(names)} there: {co.stderr.strip()[:200]}')
        return why
    try:
        r = retest()
    finally:
        clean(d)
        git('checkout', '-q', '--detach', head, cwd=d)
    # ponytail: name-level match; a branch that breaks an already-failing test some other way slips through
    old = set(re.findall(rx, r.stdout + r.stderr, re.M)) & set(names) if r and r.returncode else set()
    for n in old:
        BROKEN.setdefault(n, (tid, base, full and bool(C.run['test_since'])))
    if old >= set(names):
        log(f'{tid}: {", ".join(names)} already fail without it; merged anyway')
        if full and C.run['test_since']:
            (C.notes(GATES) / FULL_PASS).touch()
            log(f'{tid}: the whole test ran and found only those; counted as the day\'s whole run')
        return None
    if old:  # only the new failures count against it, or `blame` finds every task of a batch "failing" the old
        FAILED[tid] = [n for n in names if n not in old]
        log(f'{tid}: {", ".join(sorted(old))} already fail without it; only {", ".join(FAILED[tid])} count against it')
    return why


def suspect(base: str, merged: str) -> str:
    """The first line a merge added to TODO.md or DONE.md that matches `[run] suspect`, else ''.

    For blocks a project knows to distrust: a session in a run that can drive the emulator itself saying
    "needs a human at the emulator" is one. The ledger flags it for review.
    """
    if not (pat := C.run['suspect']):
        return ''
    rx = re.compile(pat, re.I)
    diff = git('diff', base, merged, '--', plan_rel('TODO.md'), plan_rel('DONE.md')).stdout.splitlines()
    gone = [l for l in diff if l.startswith('-') and not l.startswith('---')]
    # a line edited elsewhere (its files filled in, a note added) keeps its old block: that is not a new one
    return next((l[1:].strip()[:200] for l in diff if l.startswith('+') and not l.startswith('+++') and
                 (m := rx.search(l)) and not any(m.group(0) in g for g in gone)), '')


LAND_WAIT = 10 * 60  # how long a tested merge holds MERGE waiting on edits in the main checkout
LAND_WAIT_WIP = 3 * 60  # with [git] land_edited = "wip": how long before those edits go to a wip branch
EDITS_POLL = 60  # then how often its thread looks whether those edits are committed
REMIND_EVERY = 30 * 60  # and how often it raises the alarm again while they are not
EDITED = 'uncommitted edits in the main checkout'  # land()'s why for them; finish() keeps the branch
ELSEWHERE = 'the main checkout has another branch out'  # and for that: never switched under whoever works there

WAITING: set[str] = set()  # finished tasks queued on MERGE: whoever merges next takes them along
LANDED: dict[str, tuple[str, str]] = {}  # a task that landed in another's batch -> (base, merged)
ALONE: set[str] = set()  # tasks `blame` found breaking a batch: they merge in a turn of their own
FAILED: dict[str, list[str]] = {}  # the tests `tested` last saw fail on a task's merge, by the task
TASK_SID: dict[str, str] = {}  # the session that did a task, kept for its repair (`repair_merge`)
def blame(tids: list[str], d: Path, base: str, names: list[str]) -> list[str]:
    """The task of a batch whose gate failed `names` that fails them by itself, found by halving: half the batch
    merged on `base` and `[run] retest` of just those; the half that fails is halved again, or, when it passes,
    the other half is. So a batch of 10 costs about 4 retests, not 10. Only a task seen failing alone is
    blamed; a second culprit in the half not searched stays in the batch, whose next gate finds it. [] when
    none fails alone (a clash between them) or there is no retest. Leaves `d` clean, detached at `base`."""
    cmd = C.run['retest'].replace('{names}', ' '.join(map(plat.quote, names)))
    env = merge_env()

    def fails(group: list[str]) -> bool | None:
        """Whether `group` merged on the base fails `names`; None when it will not merge there."""
        git('merge', '--abort', cwd=d)
        clean(d)
        git('checkout', '-q', '--detach', base, cwd=d)
        for t in group:
            if (files := merge_into(d, fixed(t), f'Merge task/{t} alone', t)) is None or files and not joined(files, t, d):
                return None
        try:
            r = sp.run(cmd, shell=True, cwd=str(d), capture_output=True, text=True, env=env, timeout=C.run['timeout'])
        except sp.TimeoutExpired:
            return None
        return bool(r.returncode and set(re.findall(C.run['failures'], r.stdout + r.stderr, re.M)) & set(names))

    def search(group: list[str], failing: bool) -> list[str]:
        if len(group) == 1:
            return group if failing or fails(group) else []
        half, rest = group[:len(group) // 2], group[len(group) // 2:]
        if (f := fails(half)) is None:  # cannot build the half: each of the group alone
            return next(([t] for t in group if fails([t])), [])
        return search(half, True) if f else search(rest, False)  # `rest` may pass too: a clash across halves

    try:
        return search(tids, False)
    finally:
        git('merge', '--abort', cwd=d)
        clean(d)
        git('checkout', '-q', '--detach', base, cwd=d)


def merge(tid: str, branch: str) -> str | None:
    """Merge task/<tid> into the shared branch: merge, archive ticks, test, land, push, delete the branch.

    The merge is built and tested in its own worktree (`[run] home`/merge), and the shared branch only
    moves once the tests pass. So the main checkout never holds an untested merge: whoever works there keeps
    committing the whole time, nothing is reset under them, and their edits are never stashed.

    With `[run] batch`, the other finished branches waiting for the lock ride along: one gate run for all of
    them (the gate is often the slow part). A rider that conflicts beyond a join waits for its own turn, and
    a batch that fails the gate is split: this task tries again alone, the riders take their own turns.

    Returns None when it landed, else why it was left alone. The shared branch is then as it was, and the
    task branch is still there.
    """
    try:
        return merge_tries(tid, branch)
    finally:
        with FIX_DIRS_LOCK:  # its fixed-ahead files are free for the next fix, which now sees this merge
            if FIXING.pop(tid, None) is not None:
                FIX_DIRS_LOCK.notify_all()


def criticals(branch: str) -> set[str]:
    """The tasks critical in the plan (a `(follow-up, critical)` tag, or a section named Critical): fixes for a
    red shared branch or a flaky test, which every other merge's gate is waiting on. They merge alone, first."""
    out, section = set(), ''
    for l in plan_text(branch):
        if l.startswith('### '):
            section = l[4:]
        elif (m := TASK.match(l)) and m.group(1) != 'x' and ('critical' in section.lower() or
                                       ((t := P.PRI_TAG.search(l)) and t.group(1) == 'critical')):
            out.add(m.group(2))
    return out


def critical(tid: str, branch: str) -> bool:
    return tid in criticals(branch)


def merge_rank(tid: str, crit: bool) -> int:
    """Who takes MERGE next: a task already landed in a batch (only bookkeeping left), then a critical one (it
    unjams the gate for the rest), then one whose merge is built ahead with its gate under way (another turn
    first would drop that gate), then everyone else in the order they finished."""
    if tid in LANDED:
        return 0
    if crit:
        return 1
    return 2 if any(tid in a['tids'] for a in AHEADS) else 3


def merge_tries(tid: str, branch: str) -> str | None:
    """`merge`'s three tries."""
    yields, tries = True, -1
    while (tries := tries + 1) < 3:
        if tid not in LANDED and (why := fix_ahead(tid, branch)):
            return why
        WAITING.add(tid)
        crit = critical(tid, branch)
        with MERGE.turn(lambda: merge_rank(tid, crit)):
            WAITING.discard(tid)
            if tid not in LANDED and UNPUSHED:  # a batch whose last task has not taken the lock yet: its
                push_landed(UNPUSHED[-1], branch)  # push goes out now, not after this one's gate
            if tid not in LANDED:  # else it went in with an earlier task's batch
                if (why := merge_batch(tid, branch, inline=tries == 2, yields=yields)) == LATER:
                    yields, tries = False, tries - 1  # once, and not a try: it queues again behind that batch
                    continue
                if why == AGAIN:
                    log(f'{tid}: {AGAIN}; it is fixed outside the lock again while the others merge')
                    continue
                if why:
                    forget(tid)
                    return why
            base, merged = LANDED.pop(tid)
            forget(tid)
            git('branch', '-d', f'task/{tid}')
            git('update-ref', '-d', TESTED + tid)
            for h in git('for-each-ref', '--format=%(refname)', f'{HELD}{tid}/', f'{FIXED}{tid}/').stdout.split():
                git('update-ref', '-d', h)
            land_tick(tid, merged)
            line = next((l for l in plan_text(branch) if f'**{tid}**' in l), '')
            state = 'blocked' if line.startswith('- [~]') else 'part' if line else 'ticked'
            msg = f'{tid}: merged, {state}' + (f'; SUSPECT, recheck: {sus}' if (sus := suspect(base, merged)) else '')
            note(msg)
            log(msg)
            reopen_landed(branch, tid)  # before the push, so the reopen goes out with the merge
            published(tid, branch)
            return None
    return f'{tid}: no merge landed in three tries'


def forget(tid: str) -> None:
    """Drop what the merge kept about `tid` (`ALONE`, `FAILED`, `TASK_SID`) once its merge is over."""
    ALONE.discard(tid)
    FAILED.pop(tid, None)
    TASK_SID.pop(tid, None)


def task_env(tid: str) -> dict:
    """The environment for a git merge of `tid`'s branch: the task list's merge driver (`plan.merge3`) lets the
    branch's own words win where both sides edited the same part of that task's line."""
    return {'env': {**os.environ, 'AGENT_RUNNER_TASK': tid}} if tid else {}


def merge_into(d: Path, ref: str, msg: str, tid: str = '') -> list[str] | None:
    """`git merge ref` in d: the files left in conflict ([] when it merged), or None when git refused it.

    A failed merge with nothing in conflict is either git rerere having replayed an earlier resolution of
    every file (the merge is still open: committed here) or git refusing to start (e.g. an untracked file
    in the way), which must not pass for a merge."""
    if not git('merge', '--no-edit', '-m', msg, ref, cwd=d, **task_env(tid)).returncode:
        return []
    if files := git('diff', '--name-only', '--diff-filter=U', cwd=d).stdout.split():
        return files
    if git('rev-parse', '-q', '--verify', 'MERGE_HEAD', cwd=d).returncode:
        return None
    git('commit', '-q', '--no-edit', cwd=d)
    return []


def joined(files: list[str], tid: str, d: Path) -> bool:
    """Every conflicted file in `d` is one the runner may join, and joining them worked: committed."""
    if not (all(map(joinable, files)) and union(files, tid, d)):
        return False
    git('commit', '-q', '--no-edit', cwd=d)
    return True


def refix(tid: str, branch: str, ref: str, files: list[str], d: Path, undo: bool = False, msg: str = '') -> str | None:
    """Start the conflict again from a clean state (a refused join may have written some of its files) and give
    it to a fix session (`fix_merge`): None when it committed the merge, else why not. With `undo`, a merge
    it did not finish is taken back off `d`, so the batch goes on without it."""
    git('merge', '--abort', cwd=d)
    at = git('rev-parse', 'HEAD', cwd=d).stdout.strip()
    sha = git('rev-parse', ref, cwd=d).stdout.strip()
    if kept(tid, at, sha, d, 'fix'):
        return None
    git('merge', '--no-edit', '-m', msg or f"Merge branch 'task/{tid}'", ref, cwd=d, **task_env(tid))
    if (why := fix_merge(tid, branch, files, d, at, sha)) and undo:
        git('merge', '--abort', cwd=d)
        clean(d, at)
    return why


FIX_DIRS: set[int] = set()  # the fix worktrees (fix<k>) in use by a fix ahead of the lock
FIX_DIRS_LOCK = threading.Condition()  # at most `[run] fix_ahead_max` of them at once
FIXING: dict[str, set[str]] = {}  # a task fixed ahead and not merged yet -> its conflicted files (FIX_DIRS_LOCK)
FIXED = 'refs/agent-runner/fixed/'  # + <ID>/<task sha>: a fix session's merge of task/<ID> with the shared branch
AGAIN = 'conflicts again with the shared branch'  # merge_batch's why when a fix ahead of the lock is due
LATER = 'a merge already gated for other tasks goes first'  # merge_batch's why when it gives its turn up


def fixed(tid: str) -> str:
    """task/<tid>, or the merge a fix session made of it with the shared branch ahead of the lock (`fix_ahead`),
    while task/<tid> is still the commit that merge was made from."""
    sha = git('rev-parse', '-q', '--verify', f'task/{tid}').stdout.strip()
    ref = f'{FIXED}{tid}/{sha}'
    return ref if sha and git('rev-parse', '-q', '--verify', ref).returncode == 0 else f'task/{tid}'


def fix_ahead(tid: str, branch: str) -> str | None:
    """A conflict between task/<tid> and the shared branch that the join cannot do, resolved before the merge
    lock is taken: None when there is none, or a fix session resolved it, else why not.

    The session merges task/<tid> into the branch's head in a fix worktree of its own (fix1, fix2, …: kept,
    so their builds stay warm; at most `[run] fix_ahead_max` at once, so the worktrees and their builds never
    outnumber that, and each waits on `[run] before_start` as a slot does), and the merge it commits is kept
    as `fixed(tid)`. The other
    finished tasks merge and gate meanwhile; this one then takes the lock with that merge, which goes in
    clean unless the branch has meanwhile touched the same lines again (another, smaller fix). So
    `[run] fix_timeout` holds up nobody but this task.

    A conflict in a file that another task, fixed ahead and not merged yet, had in conflict waits for that
    task's merge to end: fixed side by side, whichever lands second would be fixed again (`FIXING`)."""
    if not (C.run['fix_merges'] and C.run['fix_ahead_max']):
        return None
    said = False
    while True:
        task = git('rev-parse', '-q', '--verify', f'task/{tid}').stdout.strip()
        base = git('rev-parse', branch).stdout.strip()
        if not task or fixed(tid) != f'task/{tid}' and \
                not git('merge-base', '--is-ancestor', base, fixed(tid)).returncode:
            return None
        src = fixed(tid)  # a merge fixed ahead before, which the branch has since moved past: only the new part
        r = git('merge-tree', '--write-tree', '--name-only', '--no-messages', base, src, **task_env(tid))
        if r.returncode != 1:  # 0: it merges clean; else git cannot say, and the locked merge finds out
            return None
        files = {f for f in r.stdout.splitlines()[1:] if f}
        with FIX_DIRS_LOCK:
            def ahead() -> list[str]:
                return sorted(t for t, fs in FIXING.items() if t != tid and fs & files)
            if before := ahead():
                if not said:
                    said = True
                    log(f'{tid}: waits for {", ".join(before)} to merge first: its conflicts are in the same '
                        'files, and fixed side by side one of them would be fixed twice')
                FIX_DIRS_LOCK.wait_for(lambda: not ahead())
                continue  # the branch has moved: look again
            while not (free := set(range(1, max(1, C.run['fix_ahead_max']) + 1)) - FIX_DIRS):
                FIX_DIRS_LOCK.wait()  # each one builds and runs an agent: wait for a turn
            if ahead():
                continue  # one that took a worktree first claimed the same files meanwhile
            k = min(free)
            FIX_DIRS.add(k)
            FIXING[tid] = FIXING.get(tid, set()) | files
        break
    d = SLOTS_DIR / f'fix{k}'
    try:
        while C.run['before_start'] and before_start_fails():  # no room (memory, say): as a slot waits
            time.sleep(60)
        if d.is_dir():
            trim(d, f'fix worktree {k}')
        worktree(f'fix{k}', base)
        git('merge', '--abort', cwd=d)
        clean(d, base)
        git('checkout', '-q', '--detach', base, cwd=d)
        ref = renumber_doubles(src, base, tid, d)
        msg = merge_message(tid, f'task/{tid}' if src != f'task/{tid}' else ref)
        if (files := merge_into(d, ref, msg, tid)) is None:
            return None  # git refused it here: the locked merge says so
        if files and not joined(files, tid, d):
            git('merge', '--abort', cwd=d)
            git('merge', '--no-edit', '-m', msg, ref, cwd=d, **task_env(tid))
            log(f'{tid}: resolving its conflicts with {branch} outside the merge lock, in {d.name}')
            if why := fix_merge(tid, branch, files, d):
                return why
        git('update-ref', f'{FIXED}{tid}/{task}', git('rev-parse', 'HEAD', cwd=d).stdout.strip())
        return None
    finally:
        git('merge', '--abort', cwd=d)
        git('checkout', '-q', '--detach', cwd=d)
        with FIX_DIRS_LOCK:
            FIX_DIRS.discard(k)
            FIX_DIRS_LOCK.notify_all()  # a turn for a worktree, or for files: notify() could wake the wrong one


FLAKE = 'the repair session found a flaky test, no clash: '  # repair_merge's why when its last line is FLAKE: …


def flake_said(logfile: Path) -> list[str]:
    """The tests a repair session named on a last `FLAKE:` line (fixer.log ends with its answer), or []."""
    try:
        tail = logfile.read_text(encoding='utf-8', errors='replace').rsplit('\n=== ', 1)[-1].rstrip().splitlines()[-5:]
    except OSError:
        return []
    m = next((m for l in reversed(tail) if (m := re.match(r'\W*FLAKE:\s*(.+)', l))), None)
    return [n.strip(' `*') for n in re.split(r'[,\s]+', m[1]) if n.strip(' `*')] if m else []


def repair_retest(tid: str, branch: str, d: Path, base: str, merged: str,
                  riders: list[str] = ()) -> tuple[str | None, str | None, list[str]]:
    """A repair session on `merged`, which fails the gate (`repair_merge`), then the gate again: (why there is
    no repair, why the repaired merge still fails, the repair's commits). A repair that says the failure is a
    flake commits nothing, and the gate runs once more on the merge as it is before anything is parked; the
    flake is filed to be fixed either way."""
    if not_fixed := repair_merge(tid, branch, d, riders, base):
        if not not_fixed.startswith(FLAKE):
            return not_fixed, None, []
        names = not_fixed[len(FLAKE):].split(', ')
        flaky(tid, names)
        log(f'{tid}: {not_fixed}; running the gate once more before parking it')
        if why := tested(tid, d, base, [tid, *riders]):
            return f'{not_fixed}, and the gate failed again: {why}', None, []
        log(f'{tid}: the gate passed on the rerun; {", ".join(names)} filed to be fixed')
        return None, None, []
    return None, tested(tid, d, base), git('rev-list', '--reverse', f'{merged}..HEAD', cwd=d).stdout.split()


def upstream(branch: str, d: Path) -> str:
    """The remote's `branch`, just fetched, when it has commits the merge in `d` lacks; else ''. Merged into
    the merge before the gate, so the gate tests both and the push after it goes through."""
    remote = C.push_remote
    if not (C.push_merge and remote) or git('remote', 'get-url', remote).returncode:
        return ''
    _net(ROOT)('fetch', '-q', remote, branch)
    ref = f'refs/remotes/{remote}/{branch}'
    if git('rev-parse', '-q', '--verify', ref).returncode or \
            not git('merge-base', '--is-ancestor', ref, 'HEAD', cwd=d).returncode:
        return ''
    return ref


def merge_message(tid: str, ref: str) -> str:
    if C.run['include_task_id_in_commit']:
        return f"Merge branch 'task/{tid}'"
    subject = git('log', '-1', '--format=%s', ref).stdout.strip()
    prefix = f'{tid}:'
    if subject.startswith(prefix):
        subject = subject[len(prefix):].lstrip(' \t')
    return f'Merge: {subject or "task changes"}'


def carry_notes(base: str, d: Path) -> None:
    """Each merge since `base` in `d`: a note one side added to a task the other side ticked goes onto the
    task in DONE.md (`plan.carry_notes`), not lost with the TODO.md line the tick removed."""
    show = lambda rev: git('show', f'{rev}:{plan_rel("TODO.md")}', cwd=d).stdout.splitlines()
    path = d / plan_rel('DONE.md')
    if not path.exists():
        return
    have = path.read_text(encoding='utf-8').splitlines()
    got = have
    for m in git('rev-list', '--merges', f'{base}..HEAD', cwd=d).stdout.split():
        parents = git('rev-parse', f'{m}^1', f'{m}^2', cwd=d).stdout.split()
        mb = git('merge-base', *parents, cwd=d).stdout.strip()
        if len(parents) == 2 and mb:
            got = P.carry_notes(got, show(mb), [show(p) for p in parents])
    if got != have:
        path.write_text('\n'.join(got) + '\n', encoding='utf-8')


def caught_up(tid: str, branch: str, d: Path, base: str, merged: str, tids: list[str]) -> tuple[str, str] | None:
    """The tested merge in `d`, with what `branch` got since `base` during its gate merged in and tested: the
    branch's commit it is on and the commit to land, or None for the caller to build and test the whole merge again. `merged` passed the gate
    and the branch's new commits passed theirs, so only what those commits change is tested again, from
    `merged` (`[run] test_since`): an hour's batch gate is not rerun for a commit main got in its last minutes.
    Commits in `[run] untested` files only are not tested; a conflict or a failure builds it all again."""
    for _ in range(3):
        moved = git('diff', '--name-only', base, branch).stdout.split()
        if all(map(untestable, moved)):
            return base, merged
        new = git('rev-parse', branch).stdout.strip()
        if not C.run['test_since']:
            log(f'{tid}: {branch} got code commits during the tests; testing the merge again')
            return None
        files = merge_into(d, new, f'Merge {branch} into the merge of task/{tid}', tid)
        if files is None or files and not joined(files, tid, d):
            git('merge', '--abort', cwd=d)
            log(f'{tid}: {branch} got commits during the tests that conflict with the merge; building it again')
            return None
        log(f'{tid}: {branch} got code commits during the tests ({", ".join([f for f in moved if not untestable(f)][:5])}); '
            f'testing what they change since the tested merge {merged[:9]}')
        if why := tested(tid, d, merged, tids):
            FAILED.pop(tid, None)  # not the batch's own failure: `blame` must not read it
            log(f'{tid}: the merge with {branch}\'s new commits fails the gate; building it again ({why[:200]})')
            return None
        base, merged = new, git('rev-parse', 'HEAD', cwd=d).stdout.strip()
    log(f'{tid}: {branch} kept moving during the catch-up gates; building the merge again')
    return None


def owed(tid: str, base: str) -> dict | None:
    """A merge built and gated for other tasks, all of them waiting for the lock, that still lands on `base`,
    when `tid` is in none: after a restart `adopt_merge` finds it only once a turn has begun, and that turn's
    own merge would drop a gate that took an hour (P347's turn dropped R38's passed batch, 11-17)."""
    if any(tid in a['tids'] for a in AHEADS):
        return None
    return next((a for a in AHEADS if reusable(a, a['tids'][0], base) and a['tids'][0] in WAITING), None)


def merge_batch(tid: str, branch: str, inline: bool = False, yields: bool = True) -> str | None:
    """`merge`'s part under the lock: build, test and land task/<tid> and its riders; record them in LANDED.

    A conflict of task/<tid> that the join cannot do returns AGAIN, for `fix_ahead` to take outside the lock,
    unless `inline` (its last try) or `fix_ahead_max` is 0: then a fix session takes it here. A rider with one
    waits for its own turn. With `yields`, a merge already gated for other waiting tasks (`owed`) returns
    LATER: those tasks rank ahead now (`merge_rank`), so the caller queues again."""
    ahead_fix = C.run['fix_merges'] and C.run['fix_ahead_max'] and not inline
    d = worktree('merge', branch)
    adopt_merge(d)
    if yields and tid not in criticals(branch) and (a := owed(tid, git('rev-parse', branch).stdout.strip())):
        log(f'{tid}: the merge of {", ".join(a["tids"])} is already gated; it lands first, then this turn')
        return LATER
    if trim(d, 'merge worktree'):
        worktree('merge', branch)
    crit = criticals(branch)
    solo = not C.run['batch'] or tid in ALONE or tid in crit
    repairs: list[str] = []  # a repair session's commits, replayed when the merge is built again
    repaired_on = ''  # the base the last repair session ran on: one repair per failure, not per task, so a
    # rebuild that fails on commits the shared branch got since that repair gets a repair of its own
    batch_repaired = False  # one repair session per batch; a batch that still fails is split
    batch_fixes = C.run['fix_merges'] and not C.run['fix_ahead_max']  # a rider's conflict: a fix session in the batch
    try:
        for attempt in range(3):
            git('merge', '--abort', cwd=d)
            clean(d)
            base = git('rev-parse', branch).stdout.strip()
            git('checkout', '-q', '--detach', base, cwd=d)
            ahead = next((a for a in AHEADS if reusable(a, tid, base)), None)
            if ahead:
                AHEADS.remove(ahead)
                clean(d, ahead['merged'])
                riders = [t for t in ahead['tids'] if t != tid]
                log(f'{tid}: reusing the merge already built and gated (ahead, or by an earlier run)' +
                    (f' with {", ".join(riders)}' if riders else ''))
                if ahead['base'] != base:  # the branch moved by untested files only: take them in
                    if (files := merge_into(d, base, f'Merge {branch} into the merge of task/{tid}')) is None or \
                            files and not joined(files, tid, d):
                        git('merge', '--abort', cwd=d)
                        log(f'{tid}: {branch} moved and conflicts with it; building the merge again')
                        continue
            else:
                if AHEADS:
                    if a := next((a for a in AHEADS if tid in a['tids']), None):  # say why its gate is thrown away
                        moved = [f for f in git('diff', '--name-only', a['base'], base).stdout.split()
                                 if not untestable(f)]
                        log(f'{tid}: not reusing the merge gated with {", ".join(t for t in a["tids"] if t != tid)}: '
                            + (f'{branch} moved in tested files ({", ".join(moved[:5])}; `[run] untested` leaves '
                               f'them in)' if moved else 'its tasks changed'))
                    drop_ahead()  # the branch moved some other way, or its tasks are gone: not this merge
                own = fixed(tid)
                ref = renumber_doubles(own, base, tid, d)
                msg = merge_message(tid, f'task/{tid}' if own != f'task/{tid}' else ref)
                if (files := merge_into(d, ref, msg, tid)) is None:
                    return f'git refused to merge task/{tid} into {branch} (see the merge worktree, {d})'
                if files:
                    if joined(files, tid, d):
                        log(f'{tid}: joined both sides of {", ".join(files)}')
                    elif ahead_fix:
                        return AGAIN
                    elif why := refix(tid, branch, ref, files, d, msg=msg):
                        return why
                riders = []
                for t in ([] if solo else sorted(WAITING - set(LANDED) - ALONE - crit)):
                    if C.run['batch_max'] and len(riders) + 1 >= C.run['batch_max']:
                        break  # the rest go in the next batch: a failure here costs fewer tasks a retest
                    own = fixed(t)
                    ref = renumber_doubles(own, 'HEAD', t, d)
                    msg = merge_message(t, f'task/{t}' if own != f'task/{t}' else ref)
                    if (files := merge_into(d, ref, msg, t)) is None:
                        git('merge', '--abort', cwd=d)
                        continue
                    if files and not joined(files, t, d):
                        if not batch_fixes:
                            git('merge', '--abort', cwd=d)
                            continue  # it waits for its own turn, where a fix session can take the conflict
                        # a fix session takes the conflict here, so the rider shares this gate run
                        if refix(t, branch, ref, files, d, undo=True, msg=msg):
                            continue  # it waits for its own turn
                    riders.append(t)
                if riders:
                    log(f'{tid}: merging together with {", ".join(riders)} (one gate run)')
            if up := upstream(branch, d):  # someone pushed to the remote: take it in, the gate tests it too
                msg = f"Merge {up.removeprefix('refs/remotes/')} into {branch}"
                if (files := merge_into(d, up, msg)) is None:
                    return f'git refused to merge {up} into the merge of task/{tid} (see the merge worktree, {d})'
                if files and not joined(files, tid, d) and (why := refix(tid, branch, up, files, d, msg=msg)):
                    return f'{up} has moved and conflicts with the merge: {why}'
                log(f'{tid}: {up} had commits {branch} did not; merged in, so the gate tests them together')
            if repairs and git('cherry-pick', '--allow-empty', *repairs, cwd=d).returncode:
                git('cherry-pick', '--abort', cwd=d)
                log(f'{tid}: the repair no longer applies to the merge; testing it without')
                repairs = []
            if not C.plan_external:  # outside, `done` and `land_tick` archive as they tick
                carry_notes(base, d)
                P.archive(d / plan_rel('TODO.md'), d / plan_rel('DONE.md'))
            plan_files = [plan_rel('TODO.md'), plan_rel('DONE.md')]
            if git('status', '--porcelain', '--', *plan_files, cwd=d).stdout.strip():
                git('commit', '-qm', f'{tid}: archive ticked tasks', '--', *plan_files, cwd=d)
            merged = git('rev-parse', 'HEAD', cwd=d).stdout.strip()
            # `done` already passed the gate on the branch: rerun it only if the merged code differs
            # from what it tested (`[run] untested` files are not code). Not after `done --no-test`, nor
            # commits made after `done`, nor a session that never ran it: its tested ref is not the branch
            if riders or not gated(tid) or \
                    not all(map(untestable, git('diff', '--name-only', f'task/{tid}', merged, cwd=d).stdout.split())):
                ahead_done = threading.Event()
                if C.run['merge_ahead']:
                    threading.Thread(target=build_ahead, args=(branch, merged, ahead_done, {tid, *riders}),
                                     daemon=True).start()
                try:
                    why = tested(tid, d, base, [tid, *riders])
                finally:
                    ahead_done.set()
                if why:
                    drop_ahead()  # built on a merge that does not land as it is
                    names = FAILED.pop(tid, [])
                    if riders and names and (bad := blame([tid, *riders], d, base, names)):
                        ALONE.update(bad)
                        log(f'{tid}: the batch fails {", ".join(names)}; {", ".join(bad)} '
                            f'fail{"s" if len(bad) == 1 else ""} them alone, so '
                            f'{"it merges" if len(bad) == 1 else "they merge"} in a turn of {"its" if len(bad) == 1 else "their"} own')
                        solo, repairs = solo or tid in bad, []
                        continue
                    if riders and names:
                        git('checkout', '-q', '--detach', merged, cwd=d)  # blame left it on the base
                    if riders and not batch_repaired and C.run['repair_merges']:
                        batch_repaired = True
                        not_fixed, still, fixes = repair_retest(tid, branch, d, base, merged, riders)
                        if not not_fixed and not still:
                            note(f'{tid}: the batch ({", ".join(riders)} with it) failed the gate; ' +
                                 ('a repair session fixed it' if fixes else 'a flake, by the repair session: it passed on a rerun'))
                            # replayed if the batch is built again because the shared branch moved
                            repairs, merged, why = fixes, git('rev-parse', 'HEAD', cwd=d).stdout.strip(), None
                        else:
                            note(f'{tid}: no batch repair: {not_fixed or "the repaired batch still fails the gate"}')
                    if why and riders:
                        log(f'{tid}: the batch fails the gate; {tid} again alone, the others in their own turns')
                        solo, repairs = True, []
                        continue
                if why:
                    if repaired_on == base:
                        return why + (' (after a repair session)' if repairs else '')
                    if repaired_on:
                        log(f'{tid}: {branch} moved since the repair ({repaired_on[:10]}..{base[:10]}) and the merge '
                            f'fails again: a new failure, so a new repair session')
                    repaired_on, solo = base, True  # a rebuild replays the repairs onto this task alone
                    not_fixed, still, fixes = repair_retest(tid, branch, d, base, merged)
                    repairs = repairs + fixes
                    if not_fixed:
                        note(f'{tid}: no repair: {not_fixed}')
                        return why
                    if still:
                        return still + ' (after a repair session)'
                    merged = git('rev-parse', 'HEAD', cwd=d).stdout.strip()
                    note(f'{tid}: the merge failed the gate; ' + ('a repair session fixed it' if repairs else
                                                                  'a flake, by the repair session: it passed on a rerun'))
            if (got := caught_up(tid, branch, d, base, merged, [tid, *riders])) is None:
                if attempt < 2:
                    continue
                break
            base, merged = got
            with LANDING:
                why = land(tid, branch, merged)
            if why == 'conflict' and attempt < 2:
                continue
            if why:
                return why
            for t in [tid, *riders]:
                LANDED[t] = (base, merged)
            return None
        return f'{tid}: no merge landed in three tries'
    finally:
        git('merge', '--abort', cwd=d)
        git('checkout', '-q', '--detach', cwd=d)


def edited() -> set[str]:
    """Files with uncommitted edits in the main checkout, new ones (not ignored) included."""
    return set(git('diff', '--name-only', 'HEAD').stdout.split()) | \
        set(git('ls-files', '--others', '--exclude-standard').stdout.split())


def here_hint() -> str:
    return (f'Next time, `{C.command} take --here ID` (or `take --here "TEXT" --kind K`) moves edits like these '
            f'into a worktree of their own')


def wip_main() -> list[str]:
    """The wip/main-checkout-* branches `move_edits_aside` made, so they are not forgotten."""
    return git('for-each-ref', '--format=%(refname:short)', 'refs/heads/wip/main-checkout-*').stdout.split()


def move_edits_aside(tid: str) -> str | None:
    """[git] land_edited = "wip": the main checkout's uncommitted edits (new files included) as one commit on
    wip/main-checkout-<time>, on top of HEAD, pushed when the shared branch is; then a stash of them (a second
    copy) clears the checkout so the tested merge can land. The branch name, or None when there was nothing."""
    files = sorted(edited())
    if not files:
        return None
    name = f'wip/main-checkout-{time.strftime("%Y-%m-%d-%H%M%S")}'
    idx = os.path.join(git('rev-parse', '--git-dir').stdout.strip() or '.git', 'agent-runner-wip-index')
    env = {**os.environ, 'GIT_INDEX_FILE': idx}
    try:
        sp.run(['git', 'read-tree', 'HEAD'], cwd=ROOT, env=env, check=True, capture_output=True)
        sp.run(['git', 'add', '-A', '--', *files], cwd=ROOT, env=env, check=True, capture_output=True)
        tree = sp.run(['git', 'write-tree'], cwd=ROOT, env=env, check=True, capture_output=True, text=True).stdout.strip()
    finally:
        try:
            os.remove(idx)
        except OSError:
            pass
    msg = f'Uncommitted edits from the main checkout, moved aside so {tid} could land ({len(files)} files)'
    commit = git('commit-tree', tree, '-p', 'HEAD', '-m', msg).stdout.strip()
    if not commit or git('branch', name, commit).returncode:
        return None
    if git('stash', 'push', '-u', '-q', '-m', f'{name} (agent-runner)', '--', *files).returncode:
        return None
    remote = C.push_remote
    if C.push_merge and remote:
        git('push', '-q', remote, name)
    more = f' and {len(files) - 6} more' if len(files) > 6 else ''
    log(f'{tid}: moved uncommitted edits in the main checkout ({", ".join(files[:6])}{more}) to {name} '
        f'(and a stash) so the tested merge could land: git checkout {name}, or git stash pop. {here_hint()}')
    return name


def land(tid: str, branch: str, merged: str) -> str | None:
    """Move the shared branch in the main checkout to the tested merge: seconds, not a test run.

    None when it landed, 'conflict' when the branch's new commits clash with it (the caller builds it again
    on top), else why it could not. Uncommitted edits there are never moved aside: git refuses, before it
    starts, a merge that would change a file somebody is editing, so this waits LAND_WAIT for them to commit,
    then gives MERGE back with a why starting EDITED: `finish` keeps task/<ID> and tries again once they are.
    A main checkout with another branch out is never switched: the why starts ELSEWHERE, kept the same way.
    """
    t0 = time.time()
    said = False

    while git('diff', '--name-only', '--diff-filter=U').stdout.strip() or \
            git('rev-parse', '--verify', '-q', 'MERGE_HEAD').returncode == 0:
        if time.time() - t0 > 60 * 60:
            return 'the main checkout has a merge or unmerged paths of its own, for 60 min'
        if not said:
            said = True
            alarm(f'{tid} cannot land: {ROOT.name} is mid-merge',
                  f'the main checkout ({ROOT}) is in the middle of a merge of its own; finish or abort it, and '
                  f'{tid} lands on {branch}.')
        time.sleep(10)
    cur = git('branch', '--show-current').stdout.strip()
    if cur != branch:
        return f'{ELSEWHERE} ({cur or "a detached HEAD"}, not {branch})'
    msg = ['-m', f'{tid}: the tested merge, onto commits {branch} got during the tests']
    ref = renumber_doubles(merged, 'HEAD', tid, ROOT)
    while git('merge', '-q', *msg, ref, **task_env(tid)).returncode and \
            git('rev-parse', '--verify', '-q', 'MERGE_HEAD').returncode:
        if C.land_edited == 'wip' and time.time() - t0 > LAND_WAIT_WIP and move_edits_aside(tid):
            continue
        if time.time() - t0 > LAND_WAIT:
            return f'{EDITED} to files the merge changes'
        if not said:
            mine = edited()
            files = sorted(mine & set(git('diff', '--name-only', 'HEAD', ref).stdout.split())) or sorted(mine)
            more = f' and {len(files) - 6} more' if len(files) > 6 else ''
            said = True
            alarm(f'{tid} cannot land: uncommitted edits in {ROOT.name}',
                  f'{tid} is tested and waits to land on {branch}, but the main checkout ({ROOT}) has uncommitted '
                  f'edits to {", ".join(files[:6])}{more}, which the merge changes. Commit them, or move them to a '
                  f'branch, and it lands within a minute. {here_hint()}')
        time.sleep(10)
    if git('rev-parse', '--verify', '-q', 'MERGE_HEAD').returncode == 0:
        files = git('diff', '--name-only', '--diff-filter=U').stdout.split()
        if not joined(files, tid, ROOT):
            git('merge', '--abort')
            return 'conflict'
    if git('merge-base', '--is-ancestor', merged, 'HEAD').returncode:
        return f'the merge did not land in {branch}; merge it again'
    return None


def published(tid: str, branch: str) -> None:
    """After a merge that passed the test gate: push the shared branch, then drop the task's remote branch.

    Pushed here, and only after the gate, which is what makes publishing it unattended defensible. A failed
    push is logged, not fatal: the merge landed locally and the next one pushes both. With `[git] push_merge
    = false` the merge stays local and the `git push` to run is logged instead; `drop_if_merged` then keeps
    the task branch on the remote until the shared branch there has it.

    A batch is pushed once, by the last of its tasks to land: while the others are still waiting for the lock
    to record theirs, this one's push is left to them (each push is a CI run on the shared branch).
    """
    UNPUSHED.append(tid)
    if not (C.push_merge and LANDED and set(LANDED) <= WAITING):
        push_landed(tid, branch)


def push_landed(tid: str, branch: str) -> None:
    """`published`'s push, for `tid` and the tasks of its batch whose push was left to it."""
    if C.push_merge:
        if out := push(ROOT, branch, shared=True):
            log(f'{tid}: {out}' + (f' (with {", ".join(UNPUSHED[:-1])})' if len(UNPUSHED) > 1 else ''))
    elif C.push_remote:
        log(f'{tid}: merged, not pushed ([git] push_merge is off): git push {C.push_remote} {branch}')
    # this batch's branches, and any an earlier failed push left behind (nothing else retries those)
    r = C.push_remote
    left = git('for-each-ref', f'--merged=refs/remotes/{r}/{branch}', '--format=%(refname:lstrip=4)',
               f'refs/remotes/{r}/task/').stdout.split() if C.push_merge and r else []
    for t in dict.fromkeys(UNPUSHED + left):
        if out := drop_if_merged(ROOT, f'task/{t}'):
            log(f'{t}: {out}')
    UNPUSHED.clear()


UNPUSHED: list[str] = []  # tasks landed whose push `published` left to the last of their batch


REOPENED: set[str] = set()  # tasks `reopen_landed` put back to [ ]: `cmd_run` lets them be tried again
def idle_line() -> str:
    return f'run idle: no task it may start; waiting for TODO.md to change (Ctrl-C or {C.command} stop to end it)'


TRIED_TEXT: dict[str, str] = {}  # a tried task's line as it read once it was tried: `retry_reopened` compares


def retry_reopened(tried: set[str], closed: set[str], branch: str) -> None:
    """Put back in the pool every tried task whose line has closed and opened again, or been edited, since it was
    tried.

    `tried` keeps a task from being started twice in a run, which is right for one that ended still open
    (it failed: a human looks next) and wrong once the human has looked: a task blocked and then unblocked by
    hand, or one whose text changed (a `plan note` with what to do differently, a corrected line) carries new
    information, and a run that stays up for days would otherwise never try it again. `closed` is the tried
    tasks seen blocked or gone from TODO.md since; one seen open again after that is retried. An open one is
    retried when its line differs from how it read the first time this saw it tried (moving it doesn't count).
    """
    if not tried:
        TRIED_TEXT.clear()
        return
    lines = {m.group(2): (m.group(1), l.strip()) for l in plan_text(branch) if (m := TASK.match(l))}
    for t in list(TRIED_TEXT):
        if t not in tried:
            del TRIED_TEXT[t]
    for t in list(tried):
        box, text = lines.get(t, (None, ''))
        if box != ' ':
            closed.add(t)
            TRIED_TEXT.pop(t, None)
        elif t in closed:
            tried.discard(t)
            closed.discard(t)
            log(f'{t}: open again since it was tried; back in the pool')
        elif t not in TRIED_TEXT:
            TRIED_TEXT[t] = text
        elif TRIED_TEXT[t] != text:
            tried.discard(t)
            del TRIED_TEXT[t]
            log(f'{t}: its line changed since it was tried; back in the pool')


FLAKY: dict[str, str] = {}  # a test that failed under load and passed alone -> the task whose gate saw it
# a test that failed on the merge and on its base too -> (the task, the base, whether the daily whole test found it)
BROKEN: dict[str, tuple[str, str, bool]] = {}


def flaky(tid: str, names: list[str]) -> None:
    for n in names:
        FLAKY.setdefault(n, tid)


def file_flaky(rel: str) -> list[str]:
    """File a critical follow-up to make each flaky test robust, each runaway one bounded, and each one the
    shared branch already fails passing again, unless an open task names it already.

    A rerun alone lets the merge through, but the flake is still there and costs every later gate a rerun (or a
    red one, when it flakes twice), so it is fixed before the queued work rather than worked around."""
    if not FLAKY and not HOGS and not BROKEN:
        return []
    ls = P.lines(ROOT / rel)
    open_text = '\n'.join(l for l in ls if (m := P.ITEM.match(l)) and m.group(2) != 'x')
    kind, out = C.run['flaky_kind'], []
    for name, (gb, where) in list(HOGS.items()):
        del HOGS[name]
        if name in open_text:
            continue
        out.append(add_test_task(kind, name, f'stop growing: it held {gb} GB in {where} until the run\'s '
                               f'memory watch ended it. Find what it allocates without bound (a walk that loops, '
                               f'a list grown per case) and bound it', rel))
        open_text += '\n' + name
    for name, (tid, base, daily) in list(BROKEN.items()):
        del BROKEN[name]
        if name in open_text:
            continue
        how = (' The daily whole test found it: a selective gate ([run] test_since) let in whatever broke it, so '
               'also make the selection reach this test from what it reads.') if daily else ''
        out.append(add_test_task(kind, name, f'pass again: it fails on the shared branch ({base[:10]}), '
                               f'found by {tid}\'s merge gate, which merged anyway as not its doing. Find the '
                               f'merge that broke it (git bisect from the last gate it passed) and fix the code '
                               f'or the test.{how}', rel))
        open_text += '\n' + name
    for name, tid in list(FLAKY.items()):
        del FLAKY[name]
        if name in open_text:
            continue
        out.append(add_test_task(kind, name, f'robust: it failed under load in {tid}\'s merge gate and '
                               f'passed alone. Find what it races (wall-clock time, shared ports or files, '
                               f'other processes) and remove that, rather than widening a timeout', rel))
        open_text += '\n' + name
    return out


def add_test_task(kind: str, name: str, what: str, rel: str) -> str:
    """`file_flaky`'s task "make the test `name` <what>", critical and stamped with the day it was filed; the
    third within a week for one test (B34, `ci.closed_repeats`) is filed blocked on a person instead."""
    tid = P.add(kind, f'make the test `{name}` {what} {ci.filed_stamp()} | test: {name}', todo=ROOT / rel,
                pri='critical')
    earlier = ci.closed_repeats(P.lines(ROOT / plan_rel('DONE.md')), f'make the test `{name}` ')
    if len(earlier) >= ci.REPEAT_LIMIT - 1:
        P.block(tid, ci.repeat_ask(f'the test `{name}`', earlier), todo=ROOT / rel, after=[])
        log(f'{tid}: the test `{name}` failed again after {", ".join(earlier)} closed; blocked on a person')
    return tid


def land_tick(tid: str, merged: str) -> None:
    """A plan outside the repo: tick what `done` finished, now that its code is on the shared branch, with
    where it landed. Ticked at `done` instead, a merge left for a human would leave the task closed."""
    mark = plansync.ticks(C) / tid
    if not C.plan_external or not mark.exists():
        return
    with plansync.locked(C):
        plansync.pull(C, force=True)
        if tid in P.open_ids(P.lines(C.todo)):
            P.note(tid, f'landed {merged[:10]}', todo=C.todo)
            P.tick(tid, C.todo, C.done)
            if out := plansync.publish(C, f'tick {tid} (landed {merged[:10]})'):
                log(f'{tid}: {out}')
    mark.unlink(missing_ok=True)


def commit_plan(msg: str, *rels: str) -> bool:
    """Commit a runner's plan edit: in the main checkout, or, for a plan outside it, in the plan's clone."""
    if C.plan_external:
        if out := plansync.publish(C, msg):
            log(out)
        return True
    return not git('commit', '-qm', msg, '--', *rels).returncode


def reopen_landed(branch: str, why: str) -> None:
    if not C.plan_external:
        return _reopen_landed(branch, why)
    with plansync.locked(C):
        plansync.pull(C, force=True)
        _reopen_landed(branch, why)


def _reopen_landed(branch: str, why: str) -> None:
    """File the flaky tests the gate met (`file_flaky`), and unblock what a merge freed (`plan.reopen`), each
    committed in the main checkout, holding MERGE.

    Without it, a task blocked on "X is not merged yet" stays blocked until a human reads the prose. Left alone when TODO.md has edits nobody
    committed (somebody mid-edit), so it never commits theirs; the next merge tries again.
    """
    rel = plan_rel('TODO.md')
    if git('branch', '--show-current').stdout.strip() != branch or git('status', '--porcelain', '--', rel).stdout.strip():
        return
    if filed := file_flaky(rel):
        if not commit_plan(f'Plan: {", ".join(filed)} to fix flaky, runaway or failing tests ({why}\'s merge)', rel):
            git('checkout', '-q', '--', rel)
        else:
            for t in filed:
                note(f'{t}: filed, a flaky, runaway or failing test to fix')
                log(f'{t}: filed (critical), a flaky, runaway or failing test to fix')
    if not (got := P.reopen(ROOT / rel)):
        return
    names = ', '.join(t for t, _ in got)
    if not commit_plan(f'Plan: reopen {names} ({why} landed what they waited on)', rel):
        git('checkout', '-q', '--', rel)
        return
    REOPENED.update(t for t, _ in got)
    for t, ids in got:
        note(f'{t}: reopened, {", ".join(ids)} landed')
        log(f'{t}: reopened, {", ".join(ids)} landed')


CLAIMS_AT = [0.0]
STALE_SAID: set[str] = set()


def touched(tid: str, branch: str, slot: Path | None) -> set[str]:
    """Files task `tid` has changed so far: its branch's commits past `branch`, and in its slot what is not
    committed yet. A claim carries them, so another runner keeps off them even when the task line lists
    none (or too few)."""
    out = set(git('diff', '--name-only', f'{branch}...task/{tid}').stdout.split())
    if slot and slot.is_dir():
        st = git('status', '--porcelain', '--untracked-files=all', cwd=slot)
        if not st.returncode:
            out |= {l[3:].split(' -> ')[-1].strip('"') for l in st.stdout.splitlines()}
    return out


def keep_claims(running: dict, branch: str) -> None:
    """Every plansync.REFRESH s: re-stamp this run's claims (running, or waiting to merge) with
    the files each holds (the line's and the ones its session has touched), drop its claims on anything else,
    and say once of each other run's claim gone stale (a crashed run's would hold that task for good)."""
    if time.time() - CLAIMS_AT[0] < plansync.REFRESH or not plansync.enabled(C):
        return
    CLAIMS_AT[0] = time.time()
    slots = {t[0]: (SLOTS_DIR / f's{n}', t[2]) for n, t in running.items() if isinstance(n, int)}
    keep = set(slots) | set(ahead(branch)) | {q[0] for q in queued().values()}  # queued: waiting to resume
    lines = {t[0]: t[2] for t in tasks(branch)}
    files = {t: set(slots.get(t, (None, lines.get(t, set())))[1]) | touched(t, branch, slots.get(t, (None,))[0])
             for t in keep}
    plansync.refresh(C, keep, files)
    me = plansync.owner(C)
    for t, cl in plansync.claims(C).items():
        if cl.owner == me:
            continue
        if plansync.stale(cl) and t not in STALE_SAID:
            STALE_SAID.add(t)
            log(f'{t}: claimed by {plansync.label(cl)}, not refreshed since: if that run is gone, '
                f'`{C.command} plan unclaim {t}`')




def ci_flows(branch: str) -> tuple[list[str], str]:
    """`[run] ci_watch` as (workflow files, event their runs must come from): "auto" (the default) is every
    workflow that runs on a push to `branch`, push runs only; a name or list is just those, any event;
    false, [] or "" is none."""
    w = C.run['ci_watch']
    if w == 'auto':
        return ci.push_workflows(ROOT, branch), 'push'
    if not w:
        return [], ''
    return ([w] if isinstance(w, str) else list(w)), ''


CI_UNSEEN: list[str] = []  # why gh could not see the repository, once it has been said
CI_RERUN = True  # a red run's failed jobs run once more before a task is filed: GitHub's own outages read red too
CI_AT = [0.0]  # when `watch_ci` last asked GitHub


def watch_ci(branch: str, force: bool = False) -> list[str]:
    """`[run] ci_watch`: file one critical task for a red workflow run on the shared branch (see `ci`).

    Every `ci.CI_POLL` s from the run loop, and only when MERGE is free: the task is committed in the main
    checkout like `reopen_landed`'s, and a loop that waited out a gate here would start nothing for an hour.
    Left alone, as there, while TODO.md has edits nobody committed. The ids filed.
    """
    if not force and time.time() - CI_AT[0] < ci.CI_POLL:
        return []
    flows, event = ci_flows(branch)
    if not flows:
        return []
    if not MERGE.acquire(blocking=False):
        return []
    filed: list[str] = []
    hold = ExitStack()
    try:
        CI_AT[0] = time.time()
        if C.plan_external:  # the whole look: a gh call or two, seconds
            hold.enter_context(plansync.locked(C))
            plansync.pull(C, force=True)
        rel = plan_rel('TODO.md')
        if git('branch', '--show-current').stdout.strip() != branch or \
                git('status', '--porcelain', '--', plan_rel('')).stdout.strip():
            return []
        gh = ci.gh_in(ROOT)
        if why := ci.reachable(gh):
            if not CI_UNSEEN:
                CI_UNSEEN.append(why)
                log(f'! ci_watch: gh cannot see this repository ({why}); CI on {branch} is not watched until it '
                    f'can (`gh auth status`; `ci_watch = false` in [run] to stop looking)')
            return []
        CI_UNSEEN.clear()
        for wf in flows:
            ls = P.lines(ROOT / rel)
            open_text = '\n'.join(l for l in ls if (m := P.ITEM.match(l)) and m.group(2) != 'x')
            seen = ci.seen_file(C.notes, wf)
            was = seen.read_text() if seen.exists() else ''
            if not (got := ci.to_file(gh, wf, branch, seen, open_text, event, CI_RERUN, log)):
                continue
            text, long = got
            tid = P.add(C.run['ci_kind'], text, todo=ROOT / rel, pri='critical')
            if len(earlier := ci.closed_repeats(P.lines(ROOT / plan_rel('DONE.md')), ci.marker(wf, branch))) \
                    >= ci.REPEAT_LIMIT - 1:  # B34: the third in a week waits on a person, not ahead of all work
                P.block(tid, ci.repeat_ask(f'`{wf}` on {branch}', earlier), todo=ROOT / rel, after=[])
            own = plan_rel(f'{P.TASKS}/{tid}.md')
            (ROOT / own).parent.mkdir(parents=True, exist_ok=True)
            (ROOT / own).write_text('\n'.join([f'# {tid} — CI: {ci.marker(wf, branch)}', '', *long, '']),
                                    encoding='utf-8')
            git('add', '--', own)
            if not commit_plan(f'Plan: {tid}, {ci.marker(wf, branch)}', rel, own):
                git('reset', '-q', '--', own)
                git('checkout', '-q', '--', rel)
                (ROOT / own).unlink(missing_ok=True)
                seen.write_text(was)  # not filed: the next look tries that run again
                continue
            filed.append(tid)
            how = f'blocked on a person, after {", ".join(earlier)}' if len(earlier) >= ci.REPEAT_LIMIT - 1 else 'critical'
            note(f'{tid}: filed ({how}), {ci.marker(wf, branch)}')
            log(f'{tid}: filed ({how}), {ci.marker(wf, branch)}: {text[:200]}')
    finally:
        hold.close()
        MERGE.release()
    return filed


def not_attempt(tid: str, branch: str) -> bool:
    """The session's last commit matches `[run] not_attempt` ({id} = the task): a phase that leaves the task open
    on purpose (a spec written for a later session to port from), so the task may start again once it merges."""
    rx = C.run['not_attempt']
    last = git('log', '-1', '--format=%s', f'{branch}..task/{tid}').stdout.strip()
    return bool(rx and last and re.search(rx.replace('{id}', re.escape(tid)), last))


def finish(tid: str, n: int, sid: str, branch: str) -> None:
    """After a slot's session: merge its branch, or park it as wip/<ID> and say why."""
    try:
        if _finish(tid, n, sid, branch):
            (plansync.ticks(C) / tid).unlink(missing_ok=True)
            plansync.release(C, tid)
    except Exception as e:  # a merge thread that dies silently leaves the branch unmerged with no word why
        note(f'{tid}: LEFT FOR A HUMAN — the merge crashed: {e!r}')
        log(f'{tid}: LEFT FOR A HUMAN — the merge crashed: {e!r}')

def _finish(tid: str, n: int, sid: str, branch: str) -> bool:
    """False when task/<tid> waits for the next run to merge it."""
    if tid in halt_requests():  # B19: dropped or changed before its merge: never lands
        did = discard_task(tid, None)
        DISCARDED[tid] = 'its finished branch never merged' + (f' ({", ".join(did)})' if did else '')
        return True
    commits = git('log', '--format=%s', f'{branch}..task/{tid}').stdout.splitlines()
    if not commits:
        git('branch', '-D', f'task/{tid}')
        git('update-ref', '-d', TESTED + tid)
        note(f'{tid}: no commits — nothing to merge')
        log(f'{tid}: no commits — nothing to merge')
        return True
    if sid and sid != '(unknown)':
        TASK_SID[tid] = sid  # its repair, if the merge fails the gate, starts from this session
    while (why := merge(tid, branch)) and why.startswith((EDITED, ELSEWHERE)):
        # Tested and only waiting on somebody's edits: parking it would throw the work away for a fresh
        # attempt. The branch stays task/<ID> (`pick` leaves it alone, the next run's `unmerged` takes it).
        alarm(f'{tid} is not merging: ' + ('uncommitted edits in the main checkout' if why.startswith(EDITED)
                                           else f'{branch} is not checked out'),
              f'{why}. task/{tid} stays, tested, and merges again once ' +
              ('they are committed (or moved to a branch).' if why.startswith(EDITED) else
               f'{branch} is checked out in {ROOT} again.'))
        since = time.time()
        while blocked_by_edits(tid, branch):
            if stopping():
                log(f'{tid}: the run stops; task/{tid} waits for the next run to merge it')
                return False
            if time.time() - since > REMIND_EVERY:  # still nobody: say it again, as loud
                since = time.time()
                alarm(f'{tid} is still not merging', f'{why}. task/{tid} has waited since '
                      f'{dt.datetime.fromtimestamp(since - REMIND_EVERY):%H:%M} or earlier.')
            time.sleep(EDITS_POLL)
        log(f'{tid}: the main checkout is clear again; merging task/{tid} now')
    if not why:
        return True
    # Parked as wip/<ID>: a task/<ID> ahead of the branch reads as finished-and-waiting to `pick`, which
    # would then skip the task for good. As wip/ the task can start again, with the old attempt to read.
    if git('branch', '-M', f'task/{tid}', wip := free_branch(f'wip/{tid}')).returncode:
        note(f'{tid}: LEFT FOR A HUMAN — {why}; task/{tid} could not be parked, so nothing restarts it')
        log(f'{tid}: LEFT FOR A HUMAN — {why}. task/{tid} could not be renamed to {wip}, so no run restarts the '
            f'task until it is merged, renamed or deleted by hand. Its {len(commits)} commits: {" / ".join(commits)[:300]}')
        return True
    git('update-ref', '-d', TESTED + tid)
    for h in git('for-each-ref', '--format=%(refname)', f'{HELD}{tid}/', f'{FIXED}{tid}/').stdout.split():
        git('update-ref', '-d', h)
    note(f'{tid}: not merged, parked as {wip} — {why}')
    log(f'{tid}: not merged, parked as {wip} — {why}. Its {len(commits)} commits are kept there. The task stays '
        f'open and starts again by itself in the next run (in this one once its line is edited: '
        f'`{C.command} plan note {tid} "..."`), its next attempt pointed at {wip}')
    if out := push(ROOT, wip):  # the one copy of that work: get it off this disk
        log(f'{tid}: {out}')
    if len(parked_attempts().get(tid, [])) >= PARK_LIMIT:
        log(f'{tid}: parked {PARK_LIMIT} times now; the next pick blocks it on a person instead of starting it again')
    return True


PARK_LIMIT = 2  # B32: a task parked this many times (wip/<ID>, wip/<ID>-2, …) is blocked on a person, not retried


def parked_attempts() -> dict[str, list[str]]:
    """{task id: its parked branches} (`_finish`'s wip/<ID>, wip/<ID>-2, …), in one `git for-each-ref`. Counted
    across runs and restarts, since the branches outlive both. A wip/<ID> holding only the edits a reset slot
    saved (`save_leftovers`, "<ID> wip: uncommitted …") is no failed merge and does not count, nor do the
    wip/main-checkout-* branches."""
    out: dict[str, list[str]] = {}
    refs = git('for-each-ref', '--format=%(refname:short)%09%(subject)', 'refs/heads/wip/').stdout.splitlines()
    for r in refs:
        name, _, subj = r.partition('\t')
        if not (m := re.fullmatch(r'wip/([A-Za-z]+\d+[a-z0-9]*?)(?:-\d+)?', name)) or name.startswith('wip/main-checkout'):
            continue
        if subj.startswith(f'{m[1]} wip: uncommitted'):
            continue
        out.setdefault(m[1], []).append(name)
    seen = parked_seen()  # attempts a person was already asked about: unblocked, the task gets PARK_LIMIT more
    return {t: left for t, ws in out.items() if (left := [w for w in ws if w not in seen.get(t, ())])}


def parked_seen() -> dict[str, list[str]]:
    """{task id: the parked branches `block_parked` already blocked it over}, from `<notes>/parked-seen.json`."""
    try:
        d = json.loads(C.notes('parked-seen.json').read_text(encoding='utf-8'))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def parked_reasons(tid: str) -> list[str]:
    """Why each parked attempt of `tid` did not merge, oldest first, from the ledger's "not merged, parked as" lines."""
    try:
        led = C.notes('ledger.md').read_text(encoding='utf-8', errors='replace').splitlines()
    except OSError:
        return []
    rx = re.compile(rf'{re.escape(tid)}: not merged, parked as (\S+) — (.*)')
    return [f'{m[1]}: {m[2][:160].rstrip()}' for l in led if (m := rx.search(l))]


def block_parked(tid: str, wips: list[str], branch: str) -> bool:
    """B32: block `tid` on a person, its parked attempts and the ledger's reasons in the why, committed as
    `file_control_ask` commits (MERGE free, TODO.md clean). False when it could not be done now (the next pick
    tries again; until then `pick` skips the task all the same)."""
    if not MERGE.acquire(blocking=False):
        return False
    hold = ExitStack()
    try:
        if C.plan_external:
            hold.enter_context(plansync.locked(C))
            plansync.pull(C, force=True)
        rel = plan_rel('TODO.md')
        if tid not in open_tasks(branch):
            return True  # blocked, ticked or dropped meanwhile
        if not C.plan_external and (git('status', '--porcelain', '--', rel).stdout.strip() or branch and
                                    git('branch', '--show-current').stdout.strip() != branch):
            return False
        why = '; '.join(parked_reasons(tid)) or 'the ledger has no reason'
        P.block(tid, f'DECIDE: {tid} failed its merge {len(wips)} times (parked as {", ".join(sorted(wips))}): '
                f'merge one by hand, change the task, or drop it; `plan unblock {tid}` starts it again. Why: {why}',
                todo=ROOT / rel, after=[])
        if not commit_plan(f'Plan: block {tid}, parked {len(wips)} times without merging', rel):
            if not C.plan_external:
                git('checkout', '-q', '--', rel)
            return False
        note(f'{tid}: LEFT FOR A HUMAN — parked {len(wips)} times without merging; blocked on a person')
        log(f'{tid}: LEFT FOR A HUMAN — parked {len(wips)} times without merging ({", ".join(sorted(wips))}); '
            f'blocked on a person instead of starting it again')
        seen = parked_seen()
        seen[tid] = sorted(set(seen.get(tid, [])) | set(wips))
        try:
            C.notes('parked-seen.json').write_text(json.dumps(seen, indent=1), encoding='utf-8')
        except OSError as e:
            log(f'{tid}: could not note its parked attempts as seen ({e}); unblocked, it is blocked again')
        return True
    finally:
        hold.close()
        MERGE.release()


STAGED_SAID: set[str] = set()


def blocked_by_edits(tid: str, branch: str) -> bool:
    """The main checkout has uncommitted edits (or new files) to files task/<tid> changes, or anything
    staged (git merges onto no index but HEAD's), or another branch out than `branch`."""
    if git('branch', '--show-current').stdout.strip() != branch:
        return True
    if git('diff', '--cached', '--quiet').returncode:
        if tid not in STAGED_SAID:
            STAGED_SAID.add(tid)
            alarm(f'{tid} is not merging: staged changes in the main checkout',
                  f'they ({ROOT}) block the merge, whatever files they are; commit them or unstage them')
        return True
    STAGED_SAID.discard(tid)
    return bool(edited() & set(git('diff', '--name-only', f'{branch}...task/{tid}').stdout.split()))


# --- watching a session --------------------------------------------------------

TRANSCRIPTS: dict[str, str] = {}  # sid -> its transcript, once found: `stalled` asks every 10 s per slot


def transcript(sid: str) -> str | None:
    if (t := TRANSCRIPTS.get(sid)) and os.path.exists(t):
        return t
    if copilot():
        f = copilot_home() / 'session-state' / sid / 'events.jsonl'
        t = str(f) if f.exists() else None
    else:
        t = backend().find_transcript(sid)
    if t:
        TRANSCRIPTS[sid] = t
    return t


def entries(sid: str, skip_bad: bool = False):
    """Session `sid`'s transcript entries, in order; none without a transcript. A line that is not JSON ends
    them (the one being written), or with `skip_bad` is passed over. Every backend's come in Claude's shape."""
    shape = backend().entry
    try:
        with open(transcript(sid) or os.devnull, encoding='utf-8', errors='replace') as f:
            for l in f:
                try:
                    d = json.loads(l)
                except ValueError:
                    if skip_bad:
                        continue
                    return
                if (d := shape(d)) is not None:
                    yield d
    except OSError:
        return


def stats(sid: str) -> str:
    """'N min, N calls, context Nk first, Nk peak' for the exit line. Watch the peak over a run: if it keeps
    creeping up, or more tasks come back blocked, the tasks are too big."""
    calls, ctx, ts = 0, [], []
    for d in entries(sid):
        if not isinstance(d, dict):
            continue
        ts += [d['timestamp']] if 'timestamp' in d else []
        if d.get('type') == 'session.usage_record' and (u := d.get('data', {}).get('usage')):  # Copilot
            calls += 1
            ctx.append(u.get('inputTokens', 0))
        elif d.get('type') == 'message' and (m := d.get('message', {})).get('role') == 'assistant' \
                and (u := m.get('usage')):  # Pi
            calls += 1
            ctx.append(u.get('input', 0) + u.get('cacheRead', 0) + u.get('cacheWrite', 0))
        elif d.get('type') == 'assistant' and (u := d.get('message', {}).get('usage')):
            calls += 1
            ctx.append(sum(u.get(k, 0) for k in ('input_tokens', 'cache_read_input_tokens',
                                                 'cache_creation_input_tokens')))
    if not ctx or not ts:
        return 'no transcript'
    span = (dt.datetime.fromisoformat(ts[-1].replace('Z', '+00:00')) -
            dt.datetime.fromisoformat(ts[0].replace('Z', '+00:00')))
    return f'{int(span.total_seconds()) // 60} min, {calls} calls, context {ctx[0] // 1000}k first, {max(ctx) // 1000}k peak'


_busy_at: dict[str, float] = {}  # session id → when stalled() last saw it running a tool


def stalled(pid: int, sid: str, limit: int) -> str | None:
    """Why a live session looks stuck, else None: quiet for `limit` seconds with no tool running (a prompt or
    a dialog the idle hook never sees), or quiet for longer than the Bash timeout even with one (a hung tool).
    A tool's run writes nothing to the transcript, so the prompt's quiet counts from the last look that saw
    one running: a 20-minute test run then a minute's thinking is not 21 minutes at a prompt (openmx's P38).
    """
    t = transcript(sid)
    now = time.time()
    quiet = now - os.path.getmtime(t) if t and os.path.exists(t) else 0
    if busy := bool(plat.children(pid)):
        _busy_at[sid] = now
    idle = min(quiet, now - _busy_at.get(sid, 0))
    if quiet > 65 * 60 or (idle > limit and not busy):
        return f'no transcript activity for {int(quiet // 60)} min' + \
               (' with a tool still running' if busy else ' at a prompt')
    return None


RESUMES_MAX = 3  # resumes of one session before a cut-off is taken for the end of it
NOT_RESUMED = {'invalid_request', 'authentication_failed', 'billing_error', 'rate_limit'}  # would fail again


def cut_off(sid: str, mid_turn: bool = False) -> str | None:
    """Why the session ended without finishing its turn, else None. An API error ends a turn in Claude Code
    and the idle stop then ends the session, though nothing was finished: the network dropped, or the API
    was down. A usage limit or a request the API refused is not that. With `mid_turn`, also a transcript
    that stops inside a turn: the machine went down under it. A finished session ends on a turn it ended."""
    last = None
    for d in entries(sid, skip_bad=True):
        if d.get('type') in ('user', 'assistant') and not d.get('isSidechain') and not d.get('isMeta'):
            last = d
    if not last:
        return None
    m = last.get('message') if isinstance(last.get('message'), dict) else {}
    if last.get('isApiErrorMessage'):
        c = m.get('content')
        text = c if isinstance(c, str) else ' '.join(x.get('text', '') for x in c or [] if isinstance(x, dict))
        text = ' '.join(text.split())
        if LIMIT.search(text) or last.get('error') in NOT_RESUMED:
            return None
        return text[:160] or f'API error {last.get("error")}'
    if mid_turn and (last['type'] == 'user' or m.get('stop_reason') in (None, 'tool_use')):
        return 'its transcript stops mid-turn'
    return None


def queued() -> dict[int, tuple[str, str, str]]:
    """{slot: (task, session, why)}: the sessions waiting to resume, one `<notes>/<ID>.resume` each."""
    out = {}
    for f in C.notes().glob('*.resume'):
        try:
            q = json.loads(f.read_text(encoding='utf-8'))
            out[int(q['slot'])] = (f.stem, q['sid'], q['why'])
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return out


def queue_resume(tid: str, n: int, sid: str, why: str) -> None:
    C.notes(f'{tid}.resume').write_text(json.dumps({'slot': n, 'sid': sid, 'why': why}), encoding='utf-8')


HEADER = re.compile(r'^=== (\S+) (\S+) (?:session|resume) (\S+)')


def resumes(n: int, sid: str) -> int:
    """How often session `sid` has been resumed (its slot log's resume headers)."""
    try:
        with open(C.notes(f'slot{n}.log'), encoding='utf-8', errors='replace') as f:
            return sum(1 for l in f if l.startswith('=== ') and f' resume {sid} ' in l)
    except OSError:
        return 0


def last_session(tid: str) -> tuple[int, str] | None:
    """(slot, session) of task `tid`'s latest session, from the slot logs' headers."""
    best = None
    for f in C.notes().glob('slot*.log'):
        if not re.fullmatch(r'slot\d+', f.stem):
            continue
        with open(f, encoding='utf-8', errors='replace') as fh:
            for l in fh:
                if (m := HEADER.match(l)) and m.group(2) == tid and (not best or m.group(1) >= best[0]):
                    best = (m.group(1), int(f.stem[4:]), m.group(3))
    return best and best[1:]


SESSION_TMP_KEEP = 24 * 3600  # s with no file written before a session's temp folder that nothing runs is swept
SWEEP_EVERY = 6 * 3600        # s between sweeps in a long run
_swept = [-1e9]


def tmp_roots() -> list[Path]:
    """Where Claude Code keeps its per-session temp folders, `<root>/claude-<uid>/<project>/<session>/`
    (the scratchpad and background tasks' output). It never deletes them, and agents build in them: one
    tmpfs with a per-user quota filled to EDQUOT with 40 GB of finished sessions' cargo target dirs."""
    roots = [os.environ.get('CLAUDE_CODE_TMPDIR'), C.home / 'tmp', tempfile.gettempdir(), '/tmp']
    return list(dict.fromkeys(Path(r) for r in roots if r))


def session_tmp() -> Path:
    """The CLAUDE_CODE_TMPDIR a slot's agent gets: the person's own, else `<home>/tmp` on disk. Claude Code's
    default is /tmp, often a small tmpfs: 12 GB of sessions' scratch there filled a 16 GB one and every
    tool call of every agent failed."""
    d = Path(os.environ.get('CLAUDE_CODE_TMPDIR') or C.home / 'tmp')
    d.mkdir(parents=True, exist_ok=True)
    return d


def drop_session_tmp(sid: str) -> None:
    """Delete session `sid`'s temp folder and long brief: it has ended for good (not queued to resume)."""
    if not re.fullmatch(r'[0-9a-f-]{36}', sid or ''):
        return
    C.notes(f'{sid}.brief').unlink(missing_ok=True)
    for root in tmp_roots():
        for d in root.glob(f'claude-*/*/{sid}'):
            shutil.rmtree(d, ignore_errors=True)


def project_slug(p: Path) -> str:
    """Claude Code's folder name for a working directory: every character but [A-Za-z0-9] as '-'."""
    return re.sub(r'[^A-Za-z0-9]', '-', str(p.resolve()))


def live_sessions() -> set[str]:
    """The session ids of every agent process running now (POSIX; empty where /proc is missing)."""
    out = set()
    for f in Path('/proc').glob('[0-9]*/cmdline'):
        try:
            args = f.read_text(errors='replace').split('\0')
        except OSError:
            continue
        out.update(sids(args))
    return out


def end_orphans() -> None:
    """End what ended sessions left running (POSIX). Killing a session leaves its tools' processes behind,
    reparented to init: partyboard collected Gradle daemons and `find /` crawls of an sftp mount that ran
    for 20 h, 5 GB and two cores between them. Each carries AGENT_RUNNER=1 and its session's
    CLAUDE_CODE_SESSION_ID in its environment (a detached daemon too); one whose session no agent runs
    any more gets SIGTERM, then SIGKILL."""
    if plat.WINDOWS:
        return
    live, found = live_sessions(), []
    for f in Path('/proc').glob('[0-9]*/environ'):
        try:
            env = dict(v.split('=', 1) for v in f.read_bytes().decode(errors='replace').split('\0') if '=' in v)
        except OSError:
            continue
        pid = int(f.parent.name)
        if env.get('AGENT_RUNNER') == '1' and (s := env.get('CLAUDE_CODE_SESSION_ID')) and s not in live \
                and pid != os.getpid():
            found.append((pid, s, ' '.join(plat.cmdline(pid) or [])[:80]))
    for pid, s, what in found:
        log(f'ending pid {pid} left by session {s}: {what}')
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    end = time.monotonic() + 5
    while (found := [f for f in found if alive(f[0])]) and time.monotonic() < end:
        time.sleep(0.25)
    for pid, *_ in found:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


def newest_write(d: Path) -> float:
    newest = d.stat().st_mtime
    for top, dirs, files in os.walk(d):
        for name in dirs + files:
            try:
                newest = max(newest, os.lstat(os.path.join(top, name)).st_mtime)
            except OSError:
                pass
    return newest


def sweep_tmp(force: bool = False) -> None:
    """Delete this repository's sessions' temp folders (the slots' and the merge worktree's) that no process
    runs, no resume waits for, and nothing wrote to in SESSION_TMP_KEEP: a session that ended while no run
    was up or under a Ctrl-C'd run. Not the main checkout's: a person's interactive session
    there has no session id on its command line to tell it is still running."""
    if not force and time.monotonic() - _swept[0] < SWEEP_EVERY:
        return
    _swept[0] = time.monotonic()
    if plat.WINDOWS:  # no /proc to tell a live session from a finished one
        return
    end_orphans()
    keep = live_sessions() | {q[1] for q in queued().values()}
    mine = {project_slug(d) for d in SLOTS_DIR.glob('*') if re.fullmatch(r's\d+|merge|fix\d+', d.name)}
    cutoff, freed = time.time() - SESSION_TMP_KEEP, 0
    for root in tmp_roots():
        for proj in root.glob('claude-*/*'):
            if proj.name not in mine:
                continue
            for d in proj.iterdir():
                if not re.fullmatch(r'[0-9a-f-]{36}', d.name) or d.name in keep or not d.is_dir():
                    continue
                try:
                    if newest_write(d) > cutoff:
                        continue
                    freed += sum(f.stat().st_size for f in d.rglob('*') if f.is_file() and not f.is_symlink())
                except OSError:
                    continue
                shutil.rmtree(d, ignore_errors=True)
    if freed:
        log(f'swept {freed / 2**20:,.0f} MB of ended sessions\' temp folders')


MEM_EVERY = 10  # seconds between memory_watch's looks


def runner_procs() -> list[tuple[int, int, str]]:
    """(pid, resident bytes, command) of each process the run started, the agents themselves aside (Linux):
    one working in a worktree of ours (s1…, merge, merge2, fix…) or carrying a slot's AGENT_RUNNER=1."""
    home, out = str(SLOTS_DIR.resolve()), []
    for d in Path('/proc').iterdir():
        if not d.name.isdigit() or int(d.name) == os.getpid():
            continue
        try:
            cwd = os.readlink(d / 'cwd')
            ours = cwd == home or cwd.startswith(home + os.sep) or b'\0AGENT_RUNNER=1\0' in b'\0' + (d / 'environ').read_bytes()
            rss = next(int(l.split()[1]) * 1024 for l in (d / 'status').read_text().splitlines() if l.startswith('VmRSS:'))
        except (OSError, StopIteration, ValueError):
            continue
        if ours and not sids(args := plat.cmdline(int(d.name)) or []):
            out.append((int(d.name), rss, ' '.join(args).strip()[:100]))
    return out


def mem_hogs(procs: list[tuple[int, int, str]], avail: int, total: int) -> list[tuple[int, str]]:
    """Which of `procs` (`runner_procs`) `memory_watch` ends, each with why: any resident past `[run]
    proc_max_gb`; failing that, while less than `[run] min_free_mem_gb` is available, the biggest one (if it
    holds a GB: a leak outside the run is not the gates' to pay for one by one)."""
    cap = C.run['proc_max_gb']
    cap = total // 4 if cap == 'auto' else int(float(cap) * GB)
    out = [(p, f'{rss / GB:.1f} GB resident, past [run] proc_max_gb ({cap / GB:.0f} GB)')
           for p, rss, _ in procs if cap and rss > cap]
    floor = C.run['min_free_mem_gb'] * GB
    if not out and floor and avail < floor and procs:
        p, rss, _ = max(procs, key=lambda x: x[1])
        if rss >= GB:
            out.append((p, f"the run's biggest process ({rss / GB:.1f} GB) with {avail / GB:.1f} GB of memory "
                           f'left, under [run] min_free_mem_gb ({C.run["min_free_mem_gb"]} GB)'))
    return out


def memory_watch() -> None:
    """End a runaway before it takes the machine (Linux): every MEM_EVERY s, `mem_hogs`' picks get SIGKILL,
    that process alone, so its gate or session sees one test die and goes on. A test that walked a looping
    tree in RAM held 52 GB in each of three slots' gates (openmx, 11-10), and the desktop's OOM handling
    ended other work for it."""
    while True:
        time.sleep(MEM_EVERY)
        try:
            info = {l.split(':')[0]: int(l.split()[1]) * 1024 for l in Path('/proc/meminfo').read_text().splitlines()}
            procs = runner_procs()
            hogs = mem_hogs(procs, info['MemAvailable'], info['MemTotal'])
        except (OSError, ValueError, IndexError, KeyError):
            continue
        for pid, why in hogs:
            rss, cmd = next((r, c) for p, r, c in procs if p == pid)
            cut, cwd = thread_names(pid), plat_cwd(pid)
            log(f'ended pid {pid}, {why}: {cmd}')
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
            home = str(SLOTS_DIR.resolve()) + os.sep
            where = cwd[len(home):].split(os.sep)[0] if cwd.startswith(home) else cwd
            for name in test_names(cmd.split(' ')[0], cut, cwd):
                log(f'{name}: the test it was running; a task to fix it is filed at the next merge')
                HOGS.setdefault(name, (f'{rss / GB:.0f}', where))


HOGS: dict[str, tuple[str, str]] = {}  # a test memory_watch ended -> (GB it held, the worktree): `file_flaky` files it


def plat_cwd(pid: int) -> str:
    try:
        return os.readlink(f'/proc/{pid}/cwd')
    except OSError:
        return ''


def thread_names(pid: int) -> set[str]:
    """The names of `pid`'s threads but its main one's: a Rust test binary names each test's thread after the
    test (cut to 15 characters by the kernel)."""
    try:
        main = Path(f'/proc/{pid}/comm').read_text().strip()
        return {n for t in Path(f'/proc/{pid}/task').iterdir() if (n := (t / 'comm').read_text().strip()) != main}
    except OSError:
        return set()


def test_names(exe: str, cut: set[str], cwd: str) -> list[str]:
    """The whole names of the tests whose threads are `cut`, from the binary's own `--list`; none when `exe`
    is not a test binary (a build, a tool) or no test matches."""
    if not cut or not exe:
        return []
    try:
        ls = sp.run([exe, '--list', '--format', 'terse'], capture_output=True, text=True, timeout=60,
                    cwd=cwd or None, stdin=sp.DEVNULL).stdout
    except (OSError, sp.SubprocessError, ValueError):
        return []
    names = [l[:-len(': test')] for l in ls.splitlines() if l.endswith(': test')]
    return sorted({n for c in cut for n in names if n.startswith(c)} if len(names) else set())


def live_session(sid: str) -> int | None:
    """The pid of a process still running session `sid` (its command line names it), or None: a session
    in a pane no run tagged, or another tmux session, is not cut off however its transcript ends. POSIX
    only; the Windows terminals' job files name every session they started."""
    if plat.WINDOWS or not sid:
        return None
    for d in Path('/proc').iterdir():
        if d.name.isdigit() and int(d.name) != os.getpid() and (args := plat.cmdline(int(d.name))) \
                and sid in sids(args) and not any(a.startswith('--stop-') for a in args):
            return int(d.name)
    return None


def queue_cut_off(branch: str, slots: list[int]) -> dict[int, int]:
    """Startup: a slot still on task/<ID> whose session was cut off while no run was up (a reboot, the runner
    killed, the network down at its exit) is queued to resume instead of being reset for a new task.
    Returns {slot: pid} of the slots whose session still runs outside this run's panes (one opened before
    panes carried @runner-repo, say): resuming it would put a second agent in the worktree, so the slot is
    held until that process ends."""
    open_ids = open_tasks(branch)
    waiting = queued()
    held = {}
    for n in slots:
        if n in waiting or not (SLOTS_DIR / f's{n}').is_dir():
            continue
        tid = git('branch', '--show-current', cwd=SLOTS_DIR / f's{n}').stdout.strip().removeprefix('task/')
        if tid not in open_ids or (last_session(tid) or (0,))[0] != n:
            continue
        sid = last_session(tid)[1]
        if pid := live_session(sid):
            held[n] = pid
            log(f'slot {n}: {tid}\'s session still runs (pid {pid}) in a pane this run does not know; slot held '
                f'until it ends (to adopt it, `tmux set-option -p -t <pane> {REPO_TAG} {ROOT}` and restart)')
        elif (why := cut_off(sid, mid_turn=True)) and resumes(n, sid) < RESUMES_MAX:
            queue_resume(tid, n, sid, why)
            log(f'slot {n}: {tid} was cut off while no run was up ({why}); it resumes there')
    return held


_api = [-1e9, True]


def api_down(said: set[str]) -> bool:
    """`api_up` is False: said once (in `said`) until it is up again."""
    if api_up():
        said.discard('api')
        return False
    if 'api' not in said:
        said.add('api')
        log('the API cannot be reached: nothing resumes or starts until it can')
    return True


def api_up() -> bool:
    """Whether the agent's API can be reached (a TCP connect), checked at most every 10 s. A session started
    or resumed while it cannot be dies at its first call. True for another agent, or behind a proxy."""
    if C.run['agent'] != 'claude' or any(os.environ.get(k) for k in ('HTTPS_PROXY', 'https_proxy')):
        return True
    if time.time() - _api[0] >= 10:
        host = re.sub(r'^\w+://|[:/].*$', '', os.environ.get('ANTHROPIC_BASE_URL') or 'api.anthropic.com')
        try:
            socket.create_connection((host, 443), timeout=5).close()
            _api[1] = True
        except OSError:
            _api[1] = False
        _api[0] = time.time()
    return _api[1]


LIMIT = re.compile(r'limit\D{0,12}resets? (\d+(?::\d+)?\s?[ap]m)', re.I)
COPILOT_LIMIT = re.compile(r'"type":"session\.error".*(rate.?limit|quota|usage limit|too many requests)', re.I)
COPILOT_LIMIT_WAIT = 30 * 60  # Copilot does not say when a rate limit resets: try again after this long
COPILOT_FAILED = re.compile(r'Failed to get response from the AI model|could not retrieve the list of available models',
                            re.I)
PROGRESS = ('"type":"user.message"', '"type":"assistant.turn_start"', '"type":"tool.execution_start"')
RESUME_AFTER = 120  # s after a failed model call before the session is resumed; doubles with each resume
RESUME_MAX = 5
START_TRIES = 3  # a task whose session will not start is tried this many times in a run
RESUME_FAILED = ('The connection to the model failed and this session stopped mid-task. Carry on with task {tid} from '
          'where you left off.')


def copilot_failed(sid: str) -> tuple[str, float] | None:
    """(message, age in s) when the session's last word is a model call that failed (a network drop), else None.
    Copilot gives up after a few quick retries and sits at its prompt, and no Stop hook fires."""
    t = transcript(sid)
    if not t:
        return None
    err, ts = '', ''
    for l in open(t, encoding='utf-8', errors='replace'):
        if '"type":"session.error"' in l and COPILOT_FAILED.search(l):
            d = json.loads(l)
            err, ts = d.get('data', {}).get('message', 'a failed model call'), d.get('timestamp', '')
        elif any(p in l for p in PROGRESS):
            err = ''
    if not err or not ts:
        return None
    at = dt.datetime.fromisoformat(ts.replace('Z', '+00:00'))
    return err, (dt.datetime.now(dt.timezone.utc) - at).total_seconds()


def pi_last_error(t: str) -> tuple[str, str]:
    """(error message, timestamp) when a Pi transcript's last turn ended in a failed model call, else ('', '')."""
    err, ts = '', ''
    try:
        for l in open(t, encoding='utf-8', errors='replace'):
            if '"role":"assistant"' in l and '"stopReason":"error"' in l:
                d = json.loads(l)
                err = d.get('message', {}).get('errorMessage') or 'a failed model call'
                ts = d.get('timestamp', '')
            elif any(f'"role":"{r}"' in l for r in ('user', 'toolResult', 'assistant')):
                err = ''
    except (OSError, ValueError):
        return '', ''
    return err, ts


def agent_failed(sid: str) -> tuple[str, float] | None:
    """(message, age in s) when the session stopped on a failed model call and should be resumed."""
    if copilot():
        return copilot_failed(sid)
    if not pi() or not (t := transcript(sid)):
        return None
    err, ts = pi_last_error(t)
    if not err or not ts:
        return None
    at = dt.datetime.fromisoformat(ts.replace('Z', '+00:00'))
    return err, (dt.datetime.now(dt.timezone.utc) - at).total_seconds()


def resume_failed(n: int, pid: int, sid: str, tid: str, model: str, idle: int) -> int | None:
    """End slot n's session and start it again on the same session id, told to carry on; the new pid."""
    plat.terminate(pid)
    marker = C.notes(f'slot{n}.live')
    for _ in range(50):  # the old shim removes its marker as it exits: wait, so it cannot remove the new one
        if not marker.exists():
            break
        time.sleep(0.2)
    return MUX.open(n, SLOTS_DIR / f's{n}', RESUME_FAILED.format(tid=tid), sid, model, idle, slot_env(n),
                    C.notes(f'slot{n}.log'))


def copilot_limit_only(sid: str) -> dt.datetime | None:
    """`limit_only` for Copilot CLI: a session whose only errors are rate limits and that ran no tool."""
    t = transcript(sid)
    text = open(t, encoding='utf-8', errors='replace').read() if t else ''
    if not COPILOT_LIMIT.search(text) or '"type":"tool.execution_complete"' in text:
        return None
    shutil.rmtree(Path(t).parent, ignore_errors=True)
    return dt.datetime.now() + dt.timedelta(seconds=COPILOT_LIMIT_WAIT)


def limit_only(sid: str, slot_log: Path, since: int) -> dt.datetime | None:
    """If the session did nothing but hit the usage limit: discard its transcript, return the reset time.

    A limited session produced no work, so counting it as an attempt would drop the task from the run;
    and keeping its transcript would make the next run resume a session that never started.
    """
    if copilot():
        return copilot_limit_only(sid)
    if not backend().limits():
        return None
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


_account = [-1e9, None]


def account_usage() -> dict | None:
    """The account's usage from the endpoint Claude Code's `/usage` reads (the local login's OAuth token; costs
    no tokens), checked at most every 5 minutes. None when it cannot be read: "don't cap"."""
    if time.time() - _account[0] < 300:
        return _account[1]
    import urllib.request
    try:
        tok = json.load(open(os.path.expanduser('~/.claude/.credentials.json')))['claudeAiOauth']['accessToken']
        req = urllib.request.Request('https://api.anthropic.com/api/oauth/usage',
                                     headers={'Authorization': f'Bearer {tok}',
                                              'anthropic-beta': 'oauth-2025-04-20'})
        _account[1] = json.load(urllib.request.urlopen(req, timeout=10))
    except Exception:
        _account[1] = None
    _account[0] = time.time()
    return _account[1]


def usage_pct(name: str) -> float | None:
    """One window's usage %: 'seven_day' or 'five_hour' (the session limit). None when it cannot be read."""
    try:
        return account_usage()[name]['utilization']
    except (TypeError, KeyError):
        return None


def weekly() -> float | None:
    """The account's 7-day usage %, or None."""
    return usage_pct('seven_day')


LATEST = 'https://raw.githubusercontent.com/FIZL0/agent-runner/main/agent_runner/__init__.py'
VERSION = re.compile(r"""^__version__\s*=\s*['"](\d+(?:\.\d+)+)['"]""", re.M)


LATEST_SAID = ['']  # the newer version update_notice last announced: once per version
UPDATE_EVERY = 6 * 3600  # s between looks at main for a newer version


def update_watch() -> None:
    """A daemon thread for the whole run: `update_notice` at the start and every UPDATE_EVERY s."""
    while True:
        update_notice()
        time.sleep(UPDATE_EVERY)


def update_notice() -> None:
    """A green banner when main has a newer version than this one, once per version, saying how to upgrade
    (`u` when the pane reads keys). Silent when it cannot tell (offline, GitHub down, a clone ahead of main)."""
    import urllib.request
    from agent_runner import __version__
    try:
        text = urllib.request.urlopen(LATEST, timeout=5).read().decode()
        latest = VERSION.search(text)[1]
        newer = tuple(map(int, latest.split('.'))) > tuple(map(int, __version__.split('.')))
    except Exception:
        return
    if newer and latest != LATEST_SAID[0]:
        LATEST_SAID[0] = latest
        how = 'nothing, [run] auto_upgrade does it once no merge runs' if AUTO_UPGRADE[0] and \
            not plat.WINDOWS and not breaking(__version__, latest) else 'type u + Enter in this pane' if READING[0] else \
            f'run `{" ".join(upgrade_argv()[:3]) if upgrade_argv()[0] != "git" else "git pull"}`'
        then = ('the run restarts on it by itself' if not plat.WINDOWS and not breaking(__version__, latest)
                else 'then read CHANGELOG.md and restart the run')
        banner(f'agent-runner {latest} is out', f'this run is {__version__}. To upgrade: {how}; {then}.', '42')


def breaking(old: str, new: str) -> bool:
    """`new` is another major version. ponytail: a 0.x minor may break too (docs/SETUP.md#versions), but most
    are features and the rare breaking one ignores old keys; gate on its CHANGELOG entry if that bites."""
    return old.split('.')[0] != new.split('.')[0]


def upgrade_argv() -> list[str]:
    """The command that upgrades this install: pipx, uv tool, or a pull in the clone it runs from."""
    if 'pipx' in sys.prefix:
        return ['pipx', 'upgrade', 'agent-runner']
    if f'{os.sep}uv{os.sep}' in sys.prefix:
        return ['uv', 'tool', 'upgrade', 'agent-runner']
    return ['git', '-C', str(Path(__file__).resolve().parents[1]), 'pull', '-q', '--ff-only']


def installed_version() -> str | None:
    """The version on disk under this process, which an upgrade changes and the running code does not."""
    try:
        return VERSION.search((Path(__file__).parent / '__init__.py').read_text(encoding='utf-8'))[1]
    except (OSError, TypeError):
        return None


def upgrade() -> bool:
    """`u` in the runner's pane, or `run --upgrade`: run `upgrade_argv`, logged. True when it worked."""
    argv = upgrade_argv()
    log(f'upgrading: {" ".join(argv)}')
    try:
        p = sp.run(argv, capture_output=True, text=True, timeout=300)
    except (OSError, sp.TimeoutExpired) as e:
        log(f'the upgrade failed: {e}')
        return False
    if p.returncode:
        log(f'the upgrade failed (exit {p.returncode}): {(p.stderr or p.stdout).strip()[-300:]}')
        return False
    from agent_runner import __version__
    new = installed_version()
    log(f'upgraded to {new}; the run restarts on it' if new and new != __version__ else
        f'already the latest ({__version__})')
    return True


AUTO_UPGRADE = [False]  # [run] auto_upgrade: the run presses `u` itself when update_notice sees a newer version
AUTO_TRIED = ['']  # the version auto_upgrade last ran the upgrade for: once per version, even when it failed


def vtuple(v: str) -> tuple[int, ...]:
    return tuple(map(int, v.split('.')))


def auto_upgrade_due(latest: str, current: str, installed: str | None, merging: bool, tried: str,
                     windows: bool = False) -> bool:
    """[run] auto_upgrade: upgrade now? Only for a newer release the update check saw, not yet installed
    and not tried already, and only between merges (a merge in flight finishes first, then the next tick
    upgrades). Never across a major version or on Windows, where `restart_if_upgraded` would not restart."""
    try:
        newer = bool(latest) and vtuple(latest) > vtuple(current)
        on_disk = bool(installed) and vtuple(installed) >= vtuple(latest)
    except ValueError:
        return False
    return newer and not on_disk and not merging and latest != tried and not windows \
        and not breaking(current, latest)


def auto_upgrade(merging: bool) -> threading.Thread | None:
    """The run loop's tick: start `upgrade` in a thread when `auto_upgrade_due`. The loop's own
    `restart_if_upgraded` then restarts on what it installed, keeping the keys (AGENT_RUNNER_KEEP)."""
    from agent_runner import __version__
    latest = LATEST_SAID[0]
    if not AUTO_UPGRADE[0] or not auto_upgrade_due(latest, __version__, installed_version(), merging,
                                                   AUTO_TRIED[0], plat.WINDOWS):
        return None
    AUTO_TRIED[0] = latest
    log(f'agent-runner {latest} is out (this run is {__version__}): upgrading by itself ([run] auto_upgrade)')
    t = threading.Thread(target=upgrade, daemon=True)
    t.start()
    return t


_upgrade_seen: str | None = None


def restart_if_upgraded() -> None:
    """Re-exec this run on the version now installed under it (`uv tool upgrade`, a pull in a clone), so the
    loop never runs older code than the `done` and Stop hook the sessions call by path. The new process
    adopts the sessions, merges and gates like any restart. Called only with no merge thread going.

    Not on Windows (no real exec: the console would get a second process), and not across a breaking
    version, whose CHANGELOG a human reads first. The new version must be seen on two ticks, so a restart
    never lands mid-install."""
    global _upgrade_seen
    from agent_runner import __version__
    new = installed_version()
    if not new or new == __version__ or plat.WINDOWS:
        return
    if breaking(__version__, new):
        if _upgrade_seen != new:
            log(f'agent-runner {new} is installed (this run is {__version__}): a breaking version, so no restart '
                f'by itself; read CHANGELOG.md, then restart the run')
        _upgrade_seen = new
        return
    if _upgrade_seen != new:
        _upgrade_seen = new  # once more next tick, then restart
        return
    log(f'agent-runner {new} is installed (this run is {__version__}); restarting on it, keeping {state_line()}')
    sys.stdout.flush()
    # what the keys set lives in this process: the new one takes it over (see `kept_keys`)
    os.environ['AGENT_RUNNER_KEEP'] = json.dumps({'slots': SLOTS, 'paused': PAUSED[0], 'power': POWER,
                                                  'stop': stopping(), 'forced': FORCED[0]})
    os.execv(sys.executable, sys.orig_argv)  # run.lock's fd closes on exec; the new process takes it again


# --- the idle stop hook --------------------------------------------------------

DONE_IDLE = 5  # s a session whose `done` succeeded stays at its prompt: the next task starts that much sooner


def stop_hook(idle: int) -> int:
    """Stop hook for a session this runner started: end it once it has been idle for `idle` seconds.

    A finished agent otherwise sits at its prompt forever, and the loop never starts the next task. "Idle"
    means no new user or tool-result entry in the transcript, so typing into the pane keeps the session
    alive: you can take one over by hand. A session with a background task running gets a much longer
    grace (`AGENT_RUNNER_IDLE_BG`, 1800 s), because a background task normally ends and wakes it. Past the
    grace the waiter still leaves alone a session whose agent has a child process (its background command:
    a `done` queued behind other test runs can take longer than any grace), up to
    `AGENT_RUNNER_IDLE_MAX` (10800 s) after the stop.

    A usage limit is deliberately *not* idleness: Claude Code prints "continuing automatically at <reset>"
    and resumes by itself, so the waiter leaves such a session alone.
    """
    if not os.environ.get('AGENT_RUNNER'):
        return 0  # a hook file in a checkout also fires for a person's own session there: never end that one
    try:
        ev = json.load(sys.stdin)
    except Exception:
        return 0
    t = ev.get('transcript_path') or ev.get('transcriptPath')
    if not t or not os.path.exists(t):
        return 0
    if pi_last_error(t)[0]:
        return 0  # Pi settles after a failed model call too: the run resumes that session instead
    if finished():  # `done` succeeded: nothing left to wait for, and its leftovers get no grace
        idle = min(idle, DONE_IDLE)
    elif ev.get('background_tasks'):
        idle = max(idle, int(os.environ.get('AGENT_RUNNER_IDLE_BG', 1800)))
    # POSIX: the hook's parent is the agent. Windows: the hook runs under Git Bash, whose pid is not the
    # agent's, so the pid comes from the marker the slot's shim keeps (run_session)
    pid = os.getppid()
    if plat.WINDOWS and (m := os.environ.get('AGENT_RUNNER_MARKER')):
        pid = marker_pid(Path(m)) or pid
    try:
        plat.spawn_detached([*runner_cmd(), 'run', '--stop-waiter', str(pid), t, str(_user_entries(t)), str(idle)])
    except Exception:
        pass
    return 0


# Claude Code; Copilot CLI; Pi (a user message or a tool result)
USER_ENTRY = re.compile(r'"type":"(user|user\.message|tool\.execution_complete)"|"role":"(user|toolResult)"')


def _user_entries(t: str) -> int:
    try:
        with open(t, encoding='utf-8', errors='replace') as f:
            return sum(1 for l in f if USER_ENTRY.search(l))
    except OSError:
        return -1


WAITER_POLL = 60  # s between looks at a session whose background command is still running


def finished() -> bool:
    """This slot's `done` has succeeded (`finished_mark`)."""
    return bool((m := finished_mark()) and m.exists())


def stop_waiter(pid: int, t: str, n: int, idle: int) -> int:
    until = time.time() + max(idle, int(os.environ.get('AGENT_RUNNER_IDLE_MAX', 10800)))
    time.sleep(idle)
    while True:
        if _user_entries(t) != n:
            return 0  # the human typed, or a tool came back: the session is alive, leave it
        try:
            text = open(t, encoding='utf-8', errors='replace').read()
        except OSError:
            text = ''
        tail = text[text.rfind('continuing automatically'):] if 'continuing automatically' in text else ''
        if tail and '"tool_use"' not in tail:
            return 0  # waiting out a usage limit; Claude Code resumes it at the reset
        # a child is a command the agent still runs (a `done` that waited 30 min for a test slot was killed
        # with its session, and the work it was about to commit went with it): it ends and wakes the agent.
        # Once `done` has succeeded there is nothing left to protect: a leftover background command (a wait
        # loop that never ends) must not hold the slot for hours
        if not plat.children(pid) or time.time() >= until or finished():
            break
        time.sleep(WAITER_POLL)
    plat.terminate(pid)
    return 0


# --- sequential run ------------------------------------------------------------

def capped(force: bool) -> str | None:
    """Why no new task may start: the 5-hour session usage at or past `[run] session_max`, or the 7-day usage
    at or past `[run] weekly_max` (and not --force). None when neither is."""
    if force or C.run['agent'] != 'claude':
        return None
    for name, what, key in (('five_hour', 'session', 'session_max'), ('seven_day', 'weekly', 'weekly_max')):
        w = usage_pct(name)
        if w is not None and w >= C.run[key]:
            return f'{what} usage {w}% >= {C.run[key]}%'
    return None


POWER = ''  # 'shutdown' or 'suspend' (--shutdown, --suspend): what the machine does once the run has nothing left to do
SHUTDOWN_GRACE = 120  # s the run must stay idle first; new work or a stop in that time cancels it
SLEPT_AT = [-1.0]  # the idle stretch (its idle_at) the machine was suspended in: once per stretch, not on every wake


def power_due(idle_at: float) -> bool:
    """--shutdown or --suspend, and the run has been idle SHUTDOWN_GRACE s, in a stretch not slept through yet."""
    return bool(POWER) and time.time() - idle_at >= SHUTDOWN_GRACE and SLEPT_AT[0] != idle_at


def shut_down(idle_at: float) -> bool:
    """With --shutdown or --suspend, after SHUTDOWN_GRACE s idle: power off, or suspend. The caller checked
    that nothing runs, merges or may start. True once the power-off command has been accepted, so the run
    ends; a refused one is logged and the run stays.

    A suspend returns False: when the machine wakes, the run is still there and carries on, idle. It does not
    suspend again until it has had work and gone idle again, so someone who wakes the machine to use it is
    not put back to sleep two minutes later."""
    if not power_due(idle_at) or stopping():
        return False
    if POWER == 'suspend':
        log('nothing left to do and nothing merging: suspending the computer (--suspend)')
        SLEPT_AT[0] = idle_at
        if rc := plat.suspend():
            log(f'the suspend command failed (exit {rc}); staying awake')
        else:
            log('suspend accepted: on waking the run carries on, and suspends again only after its next work')
        return False
    log('nothing left to do and nothing merging: shutting the computer down (--shutdown)')
    if rc := plat.power_off():
        log(f'the power-off command failed (exit {rc}); staying up')
        return False
    return True


def sequential(branch: str, model: str, idle: int, pause: int, force: bool, once: bool = False) -> int:
    """`--no-tmux`, or no terminal for panes: one session at a time, in this checkout, on the branch it has out.

    No worktree: so a task commits straight onto the branch you are on and no merge
    happens. `done` ran the gate before it committed, so with `push_merge` the branch is pushed after each
    task. `once` stops after the first task, which is how to try the runner on a single task. With nothing to
    start it does not exit: it logs `run idle` once and looks at TODO.md again every 30 s.
    """
    here = git('branch', '--show-current').stdout.strip() or branch
    log(f'sequential run on {here} ({"one task, then stop" if once else "one session at a time"}, '
        f'committing in this checkout)')
    tried: set[str] = set()
    closed: set[str] = set()
    idle_said, idle_at = False, 0.0
    while not stopping():
        retry_reopened(tried, closed, here)
        if not (task := pick({}, tried, here, claim=True)):
            if once:
                break
            if not idle_said:
                log(idle_line())
                idle_said, idle_at = True, time.time()
            if shut_down(idle_at):
                return 0
            time.sleep(30)
            continue
        if idle_said:
            log(f'run busy: new work ({task[0]})')
            idle_said = False
        if low_disk([]):
            time.sleep(30)
            continue
        if (w := capped(force)) is not None:
            log(f'{w}: waiting for the reset (--force to go on)')
            time.sleep(300)
            continue
        tid = task[0]
        sid = str(uuid.uuid4())
        before = git('rev-parse', 'HEAD').stdout.strip()
        log(f'{tid}: starting ({task[1]})')
        env = env_vars(slot_env(1))
        if copilot():
            copilot_hooks(ROOT, idle)
        if plat.WINDOWS:  # no sh to read the prompt file; the marker is how the Stop hook finds the agent
            code = run_session(agent_argv(prompt_for(tid, 1, 1, ROOT, here), sid, model, idle, 'slot1'),
                               str(ROOT), env, C.notes('slot1.live'))
        else:
            code = sp.run(agent_cmd(prompt_for(tid, 1, 1, ROOT, here), sid, model, idle, 'slot1'), shell=True,
                          cwd=str(ROOT), env={**os.environ, **env}).returncode
        log(f'{tid}: session ended ({stats(sid)})')
        end_orphans()
        drop_session_tmp(sid)
        if C.run['on_exit']:
            try:
                sp.run(C.run['on_exit'], shell=True, cwd=str(ROOT), capture_output=True, timeout=C.run['timeout'],
                       env={**os.environ, **env})
            except sp.TimeoutExpired:
                log(f'`{C.run["on_exit"]}` ran past [run] timeout ({C.run["timeout"]}s); stopped')
        if backend().report_exit and code:
            log(f'{tid}: {C.run["backend"]} failed (exit {code}): {last_words(sid) or "see terminal output"}')
            plansync.release(C, tid)
            return code
        if r := limit_only(sid, C.notes('slot1.log'), 0):
            log(f'{tid}: only hit the usage limit; sleeping until {r:%H:%M}')
            time.sleep(max(0, (r - dt.datetime.now()).total_seconds()) + pause)
            continue
        tried.add(tid)
        plansync.release(C, tid)  # committed here, ticked by its `done`: nothing left to hold
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
    asked = stopping()
    clear_stop()
    take_keys()  # no keys here, but `./run stop --suspend|--shutdown` leaves its choice the same way
    log('sequential run done: ' + ('nothing it may start (once)' if once else 'stop asked for'))
    if asked and POWER:
        power_now()
    return 0


# --- the loop ------------------------------------------------------------------

def before_start_fails() -> bool:
    """`[run] before_start` exits non-zero, or runs past `[run] timeout` (logged: it holds every start)."""
    try:
        return bool(sp.run(C.run['before_start'], shell=True, cwd=str(ROOT), capture_output=True,
                           timeout=C.run['timeout']).returncode)
    except sp.TimeoutExpired:
        log(f'`{C.run["before_start"]}` ran past [run] timeout ({C.run["timeout"]}s): counted as failing')
        return True


def dry_run(slots: int, branch: str) -> int:
    """What `slots` free slots would start right now, in order, and why the rest of the open tasks wait."""
    running: dict = {}
    for n in range(1, slots + 1):
        if not (t := pick(running, set(), branch)):
            break
        running[n] = t
        print(f'slot {n}: {t[0]}  ({t[1]}; {", ".join(sorted(t[2])) or "no files listed"})')
    if not running:
        print('nothing to start now; every open task, and why it waits:')
    held: dict = {}
    pick(running, set(), branch, why=held)  # with these slots taken: why each open task does not start
    started = {t[0] for t in running.values()}
    groups: dict[str, list[str]] = {}
    for tid, (kind, detail) in held.items():
        if tid in started:
            continue
        kind = 'next, once a slot is free' if kind == 'free' else kind
        groups.setdefault(kind, []).append(f'{tid} ({detail})' if detail else tid)
    ls = plan_text(branch)
    can = set(held) | started
    groups['waiting on an after:, a subtask, or Stretch/Parked'] = \
        [m.group(2) for l in ls if (m := TASK.match(l)) and m.group(1) == ' ' and m.group(2) not in can]
    groups['blocked'] = [m.group(2) for l in ls if (m := TASK.match(l)) and m.group(1) == '~']
    for kind, ids in groups.items():
        if ids:
            print(f'{kind}: {", ".join(ids)}')
    if wips := wip_main():
        print(f'main-checkout edits moved aside, still to pick up: {", ".join(wips)}')
    return 0


def reserve_branch_ids() -> None:
    """Hold the ids the unmerged task branches added (`plan.reserved`), so ids handed out before the list
    existed, or by a session that wrote its plan line by hand, are not handed out again."""
    files = [plan_rel('TODO.md'), plan_rel('DONE.md')]
    have = P.reserved(C.root) | {m.group(2).rstrip('.') for f in files
                                 for l in git('show', f'HEAD:{f}', cwd=C.root).stdout.splitlines() if (m := TASK.match(l))}
    new = set()
    for b in git('for-each-ref', '--format=%(refname:short)', 'refs/heads/task/', cwd=C.root).stdout.split():
        for f in files:
            new |= {t for l in git('show', f'{b}:{f}', cwd=C.root).stdout.splitlines()
                    if (m := TASK.match(l)) and (t := m.group(2).rstrip('.')) not in have}
    P.reserve(C.root, *sorted(new))


def backlog_slots(slots: int, behind: int) -> int:
    """How many slots may run while `behind` finished tasks wait for the merge: all of them up to
    `[run] max_unmerged`, then one fewer for each half batch (`batch_max` / 2 tasks) past it, so the run eases
    off as the merges fall a few gates behind and picks up again as they land, instead of piling up finished
    work that goes stale (more conflicts, more fix sessions) before the gate can take it."""
    cap, step = C.run['max_unmerged'], max(1, C.run['batch_max'] // 2)
    return slots if not cap else max(0, slots - -(-max(0, behind - cap) // step))


def backlog_line(slots: int, allowed: int, behind: int) -> str:
    if allowed == slots:
        return f'merges caught up ({behind} waiting): all {slots} slots take new tasks again'
    return (f'{behind} finished tasks wait for the merge ([run] max_unmerged {C.run["max_unmerged"]}): '
            f'new tasks start in {allowed} of {slots} slots until it catches up')


# A Claude Code session's own markers, which its Bash commands inherit. A run started from one (a person's
# session, a control session) must not hand them on: CLAUDE_CODE_CHILD_SESSION turns off every slot's
# transcript, and the runner reads a session as dead without one. Config (CLAUDE_CONFIG_DIR, ANTHROPIC_*) stays.
SESSION_ENV = ('CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION', 'CLAUDE_CODE_SESSION_ID', 'CLAUDE_PID', 'CLAUDE_EFFORT',
               'CLAUDE_CODE_ENTRYPOINT', 'CLAUDE_CODE_EXECPATH', 'CLAUDE_CODE_SESSION_ATTENDED',
               'CLAUDE_CODE_CHILD_NOTES_DIR', 'CLAUDE_CODE_MESSAGING_SOCKET', 'CLAUDE_CODE_MESSAGING_TOKEN')


def session_env_masks(sess: str = '') -> list[list[str]]:
    """The tmux commands that keep SESSION_ENV out of every process a session starts later. `-r`, not `-u`: a
    tmux server first started from a Claude Code Bash tool holds the markers in its global environment, which
    shows through a session where they are merely unset; `-r` removes them from each new window's env."""
    return [['set-environment', *(['-t', f'={sess}'] if sess else []), '-r', k] for k in SESSION_ENV]


def drop_session_env() -> None:
    """Out of this process, and out of the tmux session it runs in: `new-session -e` stores a variable on the
    session, and every window opened in it later (each slot's) inherits it."""
    for k in SESSION_ENV:
        os.environ.pop(k, None)
    if os.environ.get('TMUX') and shutil.which('tmux'):
        for c in session_env_masks():
            tmux(*c)


def cmd_run(argv: list[str], prog: str = f'{RUNNER} run') -> int:
    """`prog` is what --help shows; a wrapping CLI passes its own (e.g. './kit run')."""
    drop_session_env()
    if not plat.WINDOWS and threading.current_thread() is threading.main_thread():
        for s in (signal.SIGTERM, signal.SIGHUP):  # a kill, a closed terminal: the same exit as Ctrl-C
            signal.signal(s, _interrupted)
    try:
        return run(argv, prog)
    except KeyboardInterrupt:
        # Exit now: a merge thread would otherwise keep the process up. Its merge worktree is thrown away; the
        # main checkout only ever moves to a tested commit, and a merge open there is waited for (up to a
        # minute) so it is not left half-done. Sessions in their panes keep going and the next run adopts
        # them and merges what finished.
        try:
            log('run interrupted: sessions in their panes keep running; the next run adopts them')
        except Exception:  # Ctrl-C before the config was read
            pass
        if LANDING.locked() and not git('rev-parse', '-q', '--verify', 'MERGE_HEAD').returncode:
            LANDING.acquire(timeout=60)  # mid-merge in the main checkout: let it commit or abort first
        os._exit(130)
    except Exception:  # its window closes with it: run.log is the only place the traceback survives
        try:
            log('run crashed:\n' + traceback.format_exc().rstrip())
        except Exception:
            pass
        raise


def _interrupted(*_) -> None:
    raise KeyboardInterrupt


def run(argv: list[str], prog: str) -> int:
    ap = argparse.ArgumentParser(prog=prog, description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('slots', nargs='?', default=None,
                    help="how many agents at once (default [run] slots), or 'once' for one task then stop")
    ap.add_argument('--mode', help=argparse.SUPPRESS)  # ponytail: gone in 0.31 (always different files); accepted so wrappers passing it still run
    ap.add_argument('--force', action='store_true', help='keep starting tasks past the session and weekly usage caps')
    power = ap.add_mutually_exclusive_group()
    power.add_argument('--shutdown', action='store_true',
                       help=f'power the computer off once nothing is running or merging and no open task may start '
                            f'(after {SHUTDOWN_GRACE} s idle)')
    power.add_argument('--suspend', action='store_true',
                       help='as --shutdown, but suspend (sleep) instead; on waking the run carries on, and '
                            'suspends again only after its next work')
    ap.add_argument('--upgrade', action='store_true', help='upgrade agent-runner first, then run the new version')
    ap.add_argument('--idle', type=int, default=None, help='seconds of quiet before a session is ended')
    ap.add_argument('--stall', type=int, default=None, help='seconds of quiet that count as stalled')
    ap.add_argument('--pause', type=int, default=None, help='seconds between a session ending and the next')
    ap.add_argument('--model', default=None, help='the agent model (default [run] model)')
    ap.add_argument('--no-tmux', action='store_true', help='force the single sequential session')
    ap.add_argument('--mux', choices=['tmux', 'wt', 'console', 'none'], default=None,
                    help='the terminal per slot (default [run] mux, else tmux; on Windows wt, else console)')
    ap.add_argument('--dry-run', action='store_true', help='print what would start, and start nothing')
    ap.add_argument('--stop-hook', action='store_true', help=argparse.SUPPRESS)
    ap.add_argument('--stop-waiter', nargs=4, metavar=('PID', 'TRANSCRIPT', 'N', 'IDLE'), help=argparse.SUPPRESS)
    ap.add_argument('--slot-shim', metavar='JOB', help=argparse.SUPPRESS)
    ap.add_argument('--hidden', action='store_true', help=argparse.SUPPRESS)  # the background run (Windows: hidden consoles)
    a = ap.parse_args(argv)

    if a.stop_hook:  # these two run inside an agent session and need no repository
        return stop_hook(a.idle or 30)
    if a.stop_waiter:
        pid, t, n, idle = a.stop_waiter
        return stop_waiter(int(pid), t, int(n), int(idle))
    if a.slot_shim:
        return slot_shim(a.slot_shim)

    init()
    if a.upgrade and upgrade() and installed_version() != __import__('agent_runner').__version__ \
            and not plat.WINDOWS:  # Windows has no real exec: the next start runs it
        os.execv(sys.executable, [x for x in sys.orig_argv if x != '--upgrade'])
    r = C.run
    once = a.slots == 'once'
    global POWER
    POWER = '' if once else 'shutdown' if a.shutdown else 'suspend' if a.suspend else ''
    try:
        slots = 1 if once else int(a.slots or r['slots'])
    except ValueError:
        ap.error(f"slots must be a number or 'once', not {a.slots!r}")
    global SLOTS
    SLOTS = slots
    if keep := kept_keys():  # restarted on an upgrade: the slot count, pause, power and stop typed before it hold
        SLOTS = slots = keep['slots']
        POWER, PAUSED[0], FORCED[0] = keep['power'], keep['paused'], keep.get('forced', False)
    idle, stall, pause = a.idle or r['idle'], a.stall or r['stall'], a.pause or r['pause']
    model = a.model or r['model']

    branch = default_branch()
    if git('rev-parse', '--verify', '--quiet', branch).returncode:
        print(f'no branch {branch!r} to merge into — commit something first', file=sys.stderr)
        return 2
    if a.dry_run:
        return dry_run(slots, branch)

    lock = single_run()  # noqa: F841 — held until the process ends
    if copilot():
        copilot_trust(ROOT, SLOTS_DIR)
    ensure_local(ROOT)  # this machine's runner.local.toml: made once (all comments), never rewritten, git-ignored
    if stopping() and not keep.get('stop'):  # left by a run killed before it saw it; a stop is for the run that is up
        clear_stop()
        log('cleared a stop request left by an earlier run')
    C.notes('POWER').unlink(missing_ok=True)
    want = 'none' if a.no_tmux else (a.mux or r['mux'])
    if a.hidden and plat.WINDOWS:  # the background run: a console per slot that starts hidden, never a wt tab
        HIDDEN[0], want = True, 'console'
    choice = plat.mux_choice(want, shutil.which('tmux') is not None, shutil.which('wt.exe') is not None)
    if choice == 'sequential':
        if want != 'none':
            log((f'{want} is not available here' if want else 'tmux is not installed') +
                ': falling back to one sequential session (install tmux, or Windows Terminal on Windows, '
                'for parallel slots, a terminal per session, and worktrees)')
        return sequential(branch, model, idle, pause, a.force, once)
    global MUX
    MUX = TmuxMux() if choice == 'tmux' else ShimMux(choice)
    global MASTER_PANE
    MASTER_PANE = choice == 'tmux'
    if choice == 'console' and HIDDEN[0]:
        log('in the background: each slot gets a console window that starts hidden (agent-runner attach sN shows it)')
    elif choice == 'console':
        log('Windows Terminal (wt.exe) is not installed: each slot gets a console window of its own')
    if choice == 'tmux' and not os.environ.get('TMUX'):
        print(f'Run me inside tmux, so the sessions get panes you can attach to:\n'
              f'    tmux new -s runner {prog} {a.slots or slots}\n'
              f'or start the run in the background: {RUNNER}', file=sys.stderr)
        return 2
    if choice == 'tmux' and os.environ.get('TMUX_PANE'):  # `attach` finds the runner's pane by this
        tmux('set-option', '-p', '-t', os.environ['TMUX_PANE'], RUN_TAG, str(ROOT))
    rc_sweep_start()  # B12: end the feed or control server an earlier run left on Remote Control
    start_control()  # c1 beside the run ([run] control) unless [run] remote, where the control server stands in
    start_control_server()
    start_board()  # the background run's board window: what lands and needs you, no tokens; reopened if closed

    AUTO_UPGRADE[0] = bool(r['auto_upgrade'])
    threading.Thread(target=update_watch, daemon=True).start()
    for w in C.warnings:
        log(w)
    from agent_runner.guide import install, point_rules
    if r['install_skill'] and (said := install()):
        log(said)
    if said := point_rules(C, git):
        log(said)
    if Path('/proc/meminfo').exists() and (r['proc_max_gb'] or r['min_free_mem_gb']):
        threading.Thread(target=memory_watch, daemon=True).start()
    if sys.stdin.isatty():
        READING[0] = True
        threading.Thread(target=read_keys, daemon=True).start()
        print(keys_help(), flush=True)
    running: dict[int, tuple] = {}
    procs: dict[int, tuple] = {}
    tried: set[str] = set()
    closed: set[str] = set()  # see retry_reopened
    idle_said, idle_at = False, 0.0
    free_at = {n: dt.datetime.min for n in range(1, slots + 1)}
    merging: list[threading.Thread] = []
    stall_said: set[str] = set()
    failed_resumes: dict[str, int] = {}  # session id -> times it was resumed after a failed model call
    failed_starts: dict[str, int] = {}  # task -> sessions that did not start
    cap_said = stop_said = False
    held_said = slots  # the slot count `max_unmerged` last held the run to, as logged
    reserve_branch_ids()
    log(f'run: {slots} slots in {MUX.name}, merging into {branch}' +
        (f', session usage {usage_pct("five_hour")}%, weekly usage {weekly()}%' if not a.force and r['agent'] == 'claude' else ''))
    if rline := remote_line():
        log(rline)
    from agent_runner import context
    if heavy := context.warning(ROOT, r['rules'], C.raw['plan']['context_kb']):
        log(heavy)

    for n, (proc, task) in adopt(branch).items():
        procs[n], running[n] = proc, task
        free_at.setdefault(n, dt.datetime.min)

    foreign = queue_cut_off(branch, [n for n in range(1, slots + 1) if n not in procs])
    sweep_tmp(force=True)
    drop_extra_slots(slots, set(procs) | set(queued()) | set(foreign))
    left = left_merging()
    finished = unmerged(branch, [n for n in free_at if n not in procs and n not in queued() and n not in foreign])
    # the riders of a merge an earlier run gated wait from the start, so its turn finds them and reuses it
    WAITING.update(set(finished) & {t for g in gate_runs() for t in g.get('tids', [])})
    for tid in sorted(finished, key=lambda t: t not in left):  # the merge an earlier run left going first: it adopts that
        log(f'{tid}: ' + ('its merge was under way when the last run ended; adopting it' if tid in left else
                          'finished, not merged yet; merging it now'))
        tried.add(tid)
        t = threading.Thread(target=finish, args=(tid, 0, '(unknown)', branch), name=f'merge:{tid}')
        t.start()
        merging.append(t)
    if not merging:  # blocks freed by merges made while no run was up (a merge started above reopens by itself)
        with MERGE:
            reopen_landed(branch, 'a merge before this run')

    while True:
        sweep_tmp()
        take_keys()
        IDLE[0] = idle_said
        write_state(running)
        if SLOTS != slots:  # `+` or `-`: a slot past the count is watched to its end, never refilled
            slots = SLOTS
            for m in range(1, slots + 1):
                free_at.setdefault(m, dt.datetime.min)
        if forced() and procs:
            end_sessions(procs, running)
        tells(procs, running)  # F16: plan tell / change, typed into a running slot's pane
        halts(procs, running, free_at, tried, branch, model, idle, slots)  # B19: plan drop / change of a running task
        waiting = {n: q for n, q in queued().items() if n in free_at and n <= slots}
        tagged = None  # MUX.panes(), looked at once a tick and only for a free slot
        for n in list(free_at):
            if n in procs and alive(procs[n][0]) and (f := agent_failed(procs[n][1])) and \
                    (k := failed_resumes.get(procs[n][1], 0)) < RESUME_MAX and f[1] >= RESUME_AFTER * 2 ** k:
                pid, sid, since = procs[n]
                failed_resumes[sid] = k + 1
                log(f'slot {n}: {running[n][0]} stopped on a failed model call ({f[0][:120]}); resuming its '
                    f'session ({k + 1}/{RESUME_MAX})')
                if new := resume_failed(n, pid, sid, running[n][0], model, idle):
                    procs[n] = (new, sid, since)
                    stall_said.add(sid)  # its transcript is still old until the resumed session writes
            if n in procs and not alive(procs[n][0]):
                (pid, sid, since), task = procs.pop(n), running.pop(n)
                log(f'slot {n}: {task[0]} exited ({stats(sid)})')
                end_orphans()
                if backend().report_exit and (said := last_words(sid)):
                    log(f'slot {n}: {task[0]} {r["backend"]}: {said[:500]}')
                if r['on_exit']:
                    sp.Popen(r['on_exit'], shell=True, cwd=str(SLOTS_DIR / f's{n}'),
                             env={**os.environ, **env_vars(slot_env(n))},
                             stdout=sp.DEVNULL, stderr=sp.DEVNULL)
                if (why := cut_off(sid)) and n <= slots:
                    if resumes(n, sid) < RESUMES_MAX:
                        # its worktree stays as the session left it, on task/<ID>: the resume goes on there
                        queue_resume(task[0], n, sid, why)
                        log(f'slot {n}: {task[0]} was cut off ({why}); it resumes in this slot once the API answers')
                        continue
                    log(f'slot {n}: {task[0]} was cut off again ({why}) after {RESUMES_MAX} resumes; '
                        f'taken as ended')
                drop_session_tmp(sid)  # ended for good: a resume (above) keeps its scratchpad
                if save_leftovers(d := SLOTS_DIR / f's{n}', task[0], branch):
                    clean(d)  # saved: the next start finds the slot clean
                if reset := limit_only(sid, C.notes(f'slot{n}.log'), since):
                    git('checkout', '-q', '--detach', cwd=SLOTS_DIR / f's{n}')  # another slot may take the task
                    free_at[n] = reset + dt.timedelta(seconds=pause)
                    log(f'slot {n}: {task[0]} only hit the usage limit; transcript dropped, the task goes '
                        f'back in the pool and the slot sleeps until {reset:%H:%M}')
                else:
                    if not not_attempt(task[0], branch):
                        tried.add(task[0])  # one attempt per run: ticked, blocked or failed, a human looks next
                    git('checkout', '-q', '--detach', cwd=SLOTS_DIR / f's{n}')
                    t = threading.Thread(target=finish, args=(task[0], n, sid, branch), name=f'merge:{task[0]}')
                    t.start()
                    merging.append(t)
                    free_at[n] = dt.datetime.now() + dt.timedelta(seconds=pause)
            if n in procs and procs[n][1] not in stall_said and \
                    (why := stalled(procs[n][0], procs[n][1], stall)):
                stall_said.add(procs[n][1])
                if (m := finished_mark(n)) and m.exists():
                    # its `done` succeeded, so the Stop hook's waiter should have ended it; that waiter can
                    # be lost (two tasks once sat finished for hours), so the run ends it: next tick reaps it
                    log(f'slot {n}: {running[n][0]} finished but {why}; ending it')
                    plat.terminate(procs[n][0])
                else:
                    log(f'slot {n}: {running[n][0]} looks stalled ({why}); look at {MUX.where(n)}')
                    print('\a', end='', flush=True)
            if n not in procs and n in foreign:
                if alive(foreign[n]):
                    continue  # see queue_cut_off: never a second agent in its worktree
                log(f'slot {n}: the session no run knew (pid {foreign.pop(n)}) ended')
                foreign.update(queue_cut_off(branch, [n]))
                continue
            if n not in procs and tagged is None:
                tagged = MUX.panes()  # a session that ended this tick is in it with a dead pid, as before
            if n not in procs and (old := tagged.get(f's{n}')) and alive(old[1]):
                # a session no run tracks still sits in this slot (adopt found no session id, or a second
                # tmux session): never reset the worktree under it; the slot waits until that pane ends
                if f'pid{old[1]}' not in stall_said:
                    stall_said.add(f'pid{old[1]}')
                    log(f'slot {n}: an untracked session (pid {old[1]}, pane {old[0]}) still runs there; slot held')
                continue
            if n > slots:  # an adopted slot past this run's count: watched to the end, never refilled
                if n not in procs and n not in waiting and n not in foreign:
                    free_at.pop(n)
                    drop_extra_slots(slots, set(procs) | set(queued()) | set(foreign))
                continue
            if n not in procs and n in waiting and not forced():  # a running task, not a new one: no stop or usage cap holds it
                if api_down(stall_said):
                    continue
                tid, sid, why = waiting.pop(n)
                C.notes(f'{tid}.resume').unlink(missing_ok=True)
                if p := resume(n, tid, sid, why, branch, model, idle):
                    procs[n] = p
                    running[n] = next((t for t in tasks(branch) if t[0] == tid), (tid, '', set(), set()))
                    tried.add(tid)
                    idle_said = False
                continue
            if n not in procs and dt.datetime.now() >= free_at[n]:
                if not stopping():
                    stop_said = False  # taken back (s again, or the STOP file removed)
                else:
                    if not stop_said and stopped_by() not in ('s', 's!'):  # a key logged its own
                        log('stop asked for: no new tasks; exiting once the running ones are merged')
                    stop_said = True
                    continue
                if PAUSED[0]:
                    continue
                if (w := capped(a.force or FORCED[0])) is not None:
                    if not cap_said:
                        alarm(f'{w}: no new tasks', 'the running tasks finish and merge; new ones wait for the '
                              'reset. To go on now: type f + Enter in this pane, or restart with --force.')
                        cap_said = True
                    continue
                cap_said = False
                allowed = backlog_slots(slots, sum(t.is_alive() for t in merging))
                if allowed != held_said:
                    log(backlog_line(slots, allowed, sum(t.is_alive() for t in merging)))
                    held_said = allowed
                if allowed < slots and sum(m <= slots for m in procs) >= allowed:
                    continue
                if api_down(stall_said):
                    continue
                if low_disk([m for m in range(1, slots + 1) if m not in procs and m not in waiting
                             and m not in foreign]):
                    continue
                if r['before_start'] and before_start_fails():
                    if 'before_start' not in stall_said:
                        stall_said.add('before_start')
                        log(f'`{r["before_start"]}` fails: no new session starts until it passes')
                        print('\a', end='', flush=True)
                    continue
                stall_said.discard('before_start')
                if task := pick(running, tried, branch, claim=True):
                    if p := start(n, task, branch, model, idle, slots):
                        procs[n], running[n] = p, task
                        if once:  # one task: nothing new starts, and the run exits once it has merged
                            ask_stop('once')
                        if idle_said:
                            log(f'run busy: new work ({task[0]})')
                            idle_said = False
                    else:
                        failed_starts[task[0]] = failed_starts.get(task[0], 0) + 1
                        plansync.release(C, task[0])  # this start failed; another attempt can claim it
                        if failed_starts[task[0]] >= START_TRIES:
                            tried.add(task[0])
                        else:  # a terminal that was slow to open, or an agent that failed once: again later
                            log(f'slot {n}: {task[0]} will be tried again in {pause} s')
                            free_at[n] = dt.datetime.now() + dt.timedelta(seconds=pause)
        retry_reopened(tried, closed, branch)
        if REOPENED:
            tried -= REOPENED  # a task reopened by a merge is a new attempt, not the one that blocked
            REOPENED.clear()
        merging = [t for t in merging if t.is_alive()]
        if not stopping():
            auto_upgrade(bool(merging))
        if not merging and not stopping():
            restart_if_upgraded()
        watch_ci(branch)
        if not stopping():
            close_controls(branch)  # B26
        if not stopping():
            sweep_unmerged(branch, merging)
        keep_claims(running, branch)
        take_keys()
        waiting = {n: q for n, q in queued().items() if n in free_at and n <= slots}  # an exit may have queued one
        # a slot asleep until a usage reset does not hold the stop; a session waiting to resume does
        if stopping() and not procs and (not waiting or forced()) and not merging:
            how = stopped_by()
            clear_stop()
            log(f'run stopped ({how}); tried this run: {", ".join(sorted(tried)) or "none"}')
            rc_sweep_stop()  # B12: its feed and control server archive their entries before it exits
            if POWER:
                power_now()
            return 0
        quiet = not procs and not waiting and not merging and all(dt.datetime.now() >= t for t in free_at.values())
        # Idle, never exit: tasks a human or a session commits later start without anyone restarting the
        # run. Logged once, and only with nothing running or merging, so no slot or finished branch is left
        # behind. A script waiting on the run
        # watches run.log for `run idle`; the process itself ends only on Ctrl-C or `./run stop`.
        # one pick, and only when its answer is needed: to end `once`, to say idle, or to power off
        if quiet and not PAUSED[0] and (once and not stopping() or not idle_said
                                        or power_due(idle_at)) and not pick(running, tried, branch):
            if once and not stopping():
                log('run done: nothing it may start (once)')
                return 0
            if not idle_said:
                log(f'tried this run: {", ".join(sorted(tried)) or "none"}')
                log(idle_line())
                idle_said, idle_at = True, time.time()
            if shut_down(idle_at):
                return 0
        nap(10)


def taken() -> dict[str, Path]:
    """Tasks `take` handed to a person's session: {id: its worktree}. The worktree is the claim: while it is
    there, the run starts nothing on the task or its files; once `take --merge` removes it, task/<ID> is
    finished work like a slot's, merged by the run (`sweep_unmerged`) or by `take --merge` itself."""
    return {d.name.removeprefix('take-'): d for d in SLOTS_DIR.glob('take-*') if (d / '.git').exists()}


SWEPT: set[str] = set()  # tasks sweep_unmerged started a merge of: once each per run
SWEEP_AT = [0.0]


def sweep_unmerged(branch: str, merging: list) -> None:
    """Every 30 s: merge a task/<ID> that finished outside this run's slots (`take --merge`), as a run
    start merges what finished while no run was up. Once per task per run: a merge that crashes is said once."""
    if time.time() - SWEEP_AT[0] < 30:
        return
    SWEEP_AT[0] = time.time()
    live = {t.name for t in merging if t.is_alive()}
    for tid in unmerged(branch, []):
        if tid in SWEPT or f'merge:{tid}' in live:
            continue
        SWEPT.add(tid)
        log(f'{tid}: finished outside the slots; merging it now')
        t = threading.Thread(target=finish, args=(tid, 0, '(unknown)', branch), name=f'merge:{tid}')
        t.start()
        merging.append(t)


TAKEN = """

You were handed this task by `{runner} take {tid}`, outside the runner's slots: you are in its worktree {d}. \
After `{runner} done {tid} ...` has committed, run `{runner} take {tid} --merge`: the runner tests and merges \
task/{tid} (or the run that is up does it within a minute). Never merge it yourself."""


def stash_ref(sha: str) -> str:
    """stash@{n} of the stash entry `sha`: `stash pop`/`drop` take no bare commit, and a run may stash meanwhile."""
    shas = git('stash', 'list', '--format=%H').stdout.split()
    return f'stash@{{{shas.index(sha)}}}' if sha in shas else sha


def cmd_take(argv: list[str], prog: str = f'{RUNNER} take') -> int:
    """`take ID`: a worktree on task/<ID> for a person's own session or subagent, beside a run or without one.
    `take "TEXT" --kind K` queues the task first; `--here` carries the main checkout's uncommitted edits along."""
    ap = argparse.ArgumentParser(prog=prog, description='Do one chosen task in your own session (or a subagent) '
                                 'in a worktree of its own; a run that is up leaves the task and its files alone.')
    ap.add_argument('id', metavar='ID|TEXT', help="an open task's id; with --kind, the text of a new task")
    ap.add_argument('--kind', metavar='K', help='queue TEXT as a new task of this kind (`plan kinds`), then take it')
    ap.add_argument('--files', metavar='A,B', help='with --kind: the files it changes, as for `plan add`')
    ap.add_argument('--here', action='store_true', help="move the main checkout's uncommitted edits into the "
                    'new worktree, leaving the main checkout clean')
    what = ap.add_mutually_exclusive_group()
    what.add_argument('--merge', action='store_true', help='after `done`: remove the worktree and merge task/<ID>')
    what.add_argument('--drop', action='store_true', help='give the task back: remove the worktree, keep no commits')
    a = ap.parse_args(argv)
    if (a.merge or a.drop) and (a.kind or a.files or a.here):
        ap.error('--merge and --drop take only an ID')
    init()
    tid, branch = a.id, default_branch()
    d = SLOTS_DIR / f'take-{tid}'
    if a.merge or a.drop:
        if not d.is_dir():
            print(f'{tid}: not taken (no {d})', file=sys.stderr)
            return 1
        if git('status', '--porcelain', cwd=d).stdout.strip():
            print(f'{tid}: {d} has uncommitted edits: `{C.command} done {tid} "..."` there first'
                  + (', or commit or delete them' if a.drop else ''), file=sys.stderr)
            return 1
        ahead_ = git('rev-list', '--count', f'{branch}..task/{tid}').stdout.strip() not in ('', '0')
        if a.drop and ahead_:
            print(f'{tid}: task/{tid} has commits; --merge them, or delete the branch yourself first', file=sys.stderr)
            return 1
        git('worktree', 'remove', str(d))
        if not ahead_:
            git('branch', '-D', f'task/{tid}')
            print(f'{tid}: given back; the run may start it' if a.drop else f'{tid}: no commits, nothing to merge')
            return 0
        if not plat.lock(C.notes('run.lock')):
            print(f'{tid}: the run that is up merges task/{tid} within a minute (see {C.notes("run.log")})')
            return 0
        finish(tid, 0, '', branch)  # no run is up: this process holds run.lock and merges it now
        merged = git('rev-parse', '--verify', '-q', f'refs/heads/task/{tid}').returncode != 0
        print(f'{tid}: merged into {branch}' if merged and tid not in open_tasks(branch) else
              f'{tid}: not merged; {C.notes("run.log")} says why')
        return 0
    stash = ''
    if a.here and edited():  # stashed first, so the plan edit `--kind` commits never meets them
        if git('stash', 'push', '-u', '-q', '-m', 'agent-runner take --here').returncode:
            print('could not stash the main checkout\'s edits; nothing taken', file=sys.stderr)
            return 1
        stash = git('rev-parse', 'stash@{0}').stdout.strip()

    def fail(msg: str) -> int:
        print(msg, file=sys.stderr)
        if stash and git('stash', 'pop', '-q', stash_ref(stash)).returncode:
            print(f'your edits are in the stash ({stash}): `git stash pop` to get them back', file=sys.stderr)
        return 1

    if a.kind:
        out = io.StringIO()
        with redirect_stdout(out):
            rc = P.main(['add', a.kind, tid] + (['--files', a.files] if a.files else []))
        if rc or not (m := re.match(r'added (\S+)', out.getvalue())):
            return fail(out.getvalue().strip() or 'not queued')
        tid = m[1]
        print(f'queued {tid}', file=sys.stderr)
        d = SLOTS_DIR / f'take-{tid}'
        # ponytail: a run polling in the moment between this commit and the worktree below could start tid too
    if tid not in open_tasks(branch):
        return fail(f'{tid}: not an open task on {branch}' + ('' if a.kind else ' (new work: `--kind K "TEXT"`)'))
    held = {l.removeprefix('branch refs/heads/') for l in
            git('worktree', 'list', '--porcelain').stdout.splitlines() if l.startswith('branch ')}
    why = ('taken already, in ' + str(d) if d.is_dir() else
           'running in a slot' if f'task/{tid}' in held or tid in {q[0] for q in queued().values()} else
           'finished, waiting to merge' if tid in ahead(branch) else
           f'claimed by {plansync.claims(C)[tid].who}' if tid in plansync.taken(C) else '')
    if why:
        return fail(f'{tid}: {why}')
    worktree(f'take-{tid}', branch)
    if (co := git('checkout', '-q', '-B', f'task/{tid}', branch, cwd=d)).returncode:
        return fail(f'{tid}: checkout failed: {co.stderr.strip()}')
    if stash:
        if git('stash', 'apply', '-q', '--index', stash, cwd=d).returncode and \
                git('stash', 'apply', '-q', stash, cwd=d).returncode:
            print(f'{tid}: your edits did not apply cleanly in {d}; they are kept in the stash ({stash})',
                  file=sys.stderr)
        else:
            git('stash', 'drop', '-q', stash_ref(stash))
            print(f'{tid}: moved your uncommitted edits from {ROOT} into {d}', file=sys.stderr)
    print(f'{tid} is yours, in {d} (branch task/{tid}); a run leaves it and its files alone.\n'
          f'Give the agent that does it this prompt, with {d} as its working directory:\n')
    print(prompt_for(tid, 0, 2, d, branch) + TAKEN.format(runner=C.command, tid=tid, d=d))
    return 0


def cmd_resume(argv: list[str], prog: str = f'{RUNNER} resume') -> int:
    """`./run resume <ID>…`: continue a task's last session in its own slot, though the run already ended it."""
    ap = argparse.ArgumentParser(prog=prog, description=
        'Continue the last session of each task in the slot it ran in, with its whole conversation: for a '
        'session cut off before the run could resume it by itself (past its resume limit). '
        'The run resumes it once that slot is free; a slot that moved on gets the task back from the wip/<ID> '
        'the runner saved, its edits uncommitted again.')
    ap.add_argument('ids', nargs='+', metavar='ID')
    a = ap.parse_args(argv)
    init()
    branch = default_branch()
    open_ids = open_tasks(branch)
    bad = 0
    for tid in a.ids:
        if tid not in open_ids:
            print(f'{tid}: not an open task on {branch}', file=sys.stderr)
        elif not (last := last_session(tid)):
            print(f'{tid}: no session of it in the slot logs', file=sys.stderr)
        elif not transcript(last[1]):
            print(f'{tid}: the transcript of its session {last[1]} is gone', file=sys.stderr)
        else:
            queue_resume(tid, last[0], last[1], 'resumed by hand')
            print(f'{tid}: session {last[1]} resumes in slot {last[0]} once that slot is free')
            continue
        bad += 1
    if not bad and plat.lock(C.notes('run.lock')):
        print(f'no run is up: it resumes when `{C.command} run` starts')
    return 1 if bad else 0


def run_up() -> bool:
    """A run holds `<notes>/run.lock` in this repository."""
    if f := plat.lock(C.notes('run.lock')):
        f.close()
        return False
    return True


def cmd_key(argv: list[str], prog: str = f'{RUNNER} key') -> int:
    """`pause`, `force`, `slots` and `key`: the runner pane's keys from any terminal, or from a remote session.
    Unlike a typed key, `pause` and `force` say which way (on, or off with --off), so saying it twice is safe."""
    cmd = prog.split()[-1]
    ap = argparse.ArgumentParser(prog=prog, description={
        'pause': 'Start no new tasks; the run stays up (--off: start them again).',
        'force': 'Start tasks past the session and weekly usage caps (--off: the caps hold again).',
        'slots': 'Change the running slot count: N, +N or -N (a slot past the count finishes its task first).',
        'key': 'Send keys to the run as if typed in its pane (? lists them).'}[cmd])
    if cmd == 'slots':
        ap.add_argument('count', help='N, +N or -N')
    elif cmd == 'key':
        ap.add_argument('keys', nargs='+')
    else:
        ap.add_argument('--off', action='store_true')
    a = ap.parse_args(argv)
    init()
    if not run_up():
        print(f'no run is up in this repository: `{C.command} run` starts one', file=sys.stderr)
        return 1
    keys = {'slots': lambda: [f'slots {a.count}'], 'key': lambda: a.keys}.get(
        cmd, lambda: [f'{cmd[0]} {"off" if a.off else "on"}'])()
    send_key(*keys)
    print(f'sent to the run: {", ".join(keys)} (it acts within 10 s; `{C.command} status` shows it)')
    return 0


def cmd_status(argv: list[str], prog: str = f'{RUNNER} status') -> int:
    """`agent-runner status`: is a run up, what its keys have set, each slot's task, and the log's end."""
    ap = argparse.ArgumentParser(prog=prog, description='What the run is doing.')
    ap.add_argument('-n', type=int, default=0, help='also the last N lines of run.log (default none)')
    a = ap.parse_args(argv)
    init()
    up = run_up()
    try:
        st = json.loads(C.notes('STATE').read_text(encoding='utf-8')) if up else {}
    except (OSError, ValueError):
        st = {}
    try:
        lines = C.notes('run.log').read_text(encoding='utf-8', errors='replace').splitlines()
    except OSError:
        lines = []
    print(status_text(up, st, lines, task_titles(), time.time(), waiting=waiting_ok()))
    if lines and a.n:
        print('\nrun.log:\n' + '\n'.join(f'  {l}' for l in lines[-a.n:]))
    return 0


EVENT = re.compile(r'^=== \S*T(\d\d:\d\d)\S* (?:(\S+): (merged, (?:ticked|blocked|part)|not merged, parked as \S+|LEFT FOR A HUMAN)\b'
                   r'|(run stopped|run idle))')  # what `status` lists under "lately"


def task_titles() -> dict[str, str]:
    """{id: its short title (`short_title`)} from TODO.md, and DONE.md for the tasks that landed and moved there."""
    out = {}
    for f in (C.done, C.todo):  # TODO.md last: its line wins
        try:
            text = f.read_text(encoding='utf-8')
        except OSError:
            continue
        for l in text.splitlines():
            if m := TASK.match(l):
                out[m.group(2)] = short_title(m.group(3))
    return out


def _drop_asides(t: str) -> str:
    """`t` without its (…) asides that hold a date, a quote or a file path: "(user 2026-11-19: 'make it…')",
    "(see runner.py, plan/TODO.md)". Nested brackets count; an aside that is plain words stays."""
    out, depth, start = [], 0, 0
    for i, ch in enumerate(t):
        if ch == '(':
            if depth == 0:
                out.append(t[start:i])
                start = i
            depth += 1
        elif ch == ')' and depth:
            depth -= 1
            if depth == 0:
                aside = t[start:i + 1]
                noisy = re.search(r"^\((?:follow-up|user|asked)\b|\d{4}-\d\d-\d\d|['\"`‘’“”]|/|\w\.(?:py|md|toml|json|rs|ts|js|sh|txt|ya?ml)\b", aside)
                out.append('' if noisy else aside)
                start = i + 1
    out.append(t[start:])  # an unclosed ( keeps its tail
    return ''.join(out)


def short_title(rest: str, width: int = 60) -> str:
    """A task's line, after its id, as a few plain words for a person: its first sentence, without the ` | `
    fields, asides with dates, quotes or file lists, quote marks and bold, cut at a word to about `width`."""
    t = _drop_asides(rest.split(' | ')[0])
    t = re.sub(r'\b\d{4}-\d\d-\d\d\b', '', t)
    t = re.sub(r"(?<!\w)(['\"`])\1(?!\w)", 'empty', t)  # `''` read aloud
    t = re.sub(r"[*`\"“”‘’]|(?<!\w)'|'(?!\w)", '', t)
    t = re.sub(r'[\w./-]*\w::(?:\w+::)*(\w+)', r'\1', t)  # a Rust/pytest path a::b::c reads as its name, c
    t = re.split(r'(?<=[.!?;:])\s+(?=[A-Z(\d])|\s+—\s+|\s+--\s+', re.sub(r' ([,.;:])', r'\1', ' '.join(t.split())), maxsplit=1)[0]
    t = t.strip(' .,;:—-')
    if len(t) > width:
        cut = t[:width - 1].rsplit(' ', 1)[0].rstrip(' ,;:—-')
        if len(cut) < width // 2:  # one long word: cut inside it rather than drop it
            cut = t[:width - 1].rstrip(' ,;:—-')
        t = cut + '…'
    return t


# --- since: what happened since the person last looked ----------------------------------------------------

SINCE_LINE = re.compile(r'^=== (\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)\S* (.*)$')
SINCE_EVENTS = [  # (pattern on a run.log line's message, kind); the first that matches names it
    (re.compile(r'^([A-Za-z]+\d+[a-z0-9]*): merged, (?:ticked|part)'), 'landed'),
    (re.compile(r'^([A-Za-z]+\d+[a-z0-9]*): merged, blocked'), 'part landed, rest stuck'),
    (re.compile(r'^([A-Za-z]+\d+[a-z0-9]*): not merged, parked as \S+ — (.*)'), 'stuck, not merged'),
    (re.compile(r'^([A-Za-z]+\d+[a-z0-9]*): LEFT FOR A HUMAN — (.*)'), 'needs you'),
    (re.compile(r'^slot \d+: ([A-Za-z]+\d+[a-z0-9]*) looks stalled'), 'looks stuck'),
    (re.compile(r'^slot \d+: ([A-Za-z]+\d+[a-z0-9]*) \([^;)]*;'), 'started'),
    (re.compile(r'^STOPPED: ([^:]+)'), 'run held, needs you'),
    (re.compile(r'^run idle'), 'run idle: nothing left it may start'),
    (re.compile(r'^run stopped'), 'run stopped'),
]


def since_event(line: str, titles: dict[str, str]) -> tuple[str, str, str] | None:
    """A run.log line as (its ISO stamp, the task id or '', one plain phrase: "landed: <title> [F5]"), or None
    when it is not something a person wants told."""
    if not (m := SINCE_LINE.match(line)):
        return None
    stamp, msg = m.groups()
    for rx, kind in SINCE_EVENTS:
        if e := rx.match(msg):
            if kind.startswith('run '):
                what = f'{kind}: {e.group(1).strip()}' if e.groups() else kind
                return stamp, '', what
            tid = e.group(1)
            why = e.group(2) if rx.groups > 1 else ''
            why = f' ({why.split(". ")[0][:60].rstrip(" .")})' if why else ''
            return stamp, tid, f'{kind}: {titles.get(tid) or tid}{why} [{tid}]'
    return None


def since_start(arg: str | None, mark: str | None, now: dt.datetime) -> dt.datetime:
    """Where `since` starts: `arg` ("2h", "30m", "1d", "today", "yesterday", or a date/time), else the mark
    the last `since` left, else 24 hours back."""
    if not arg:
        try:
            return dt.datetime.fromisoformat(mark) if mark else now - dt.timedelta(hours=24)
        except ValueError:
            return now - dt.timedelta(hours=24)
    a = arg.strip().lower()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if a == 'today':
        return midnight
    if a == 'yesterday':
        return midnight - dt.timedelta(days=1)
    if m := re.fullmatch(r'(\d+(?:\.\d+)?)\s*(m|min|mins|h|hr|hrs|hours?|d|days?|w|weeks?)', a):
        n, u = float(m[1]), m[2][0]
        return now - dt.timedelta(**{{'m': 'minutes', 'h': 'hours', 'd': 'days', 'w': 'weeks'}[u]: n})
    try:
        return dt.datetime.fromisoformat(arg.strip())
    except ValueError:
        raise SystemExit(f'{RUNNER} since: {arg!r} is not a time: 2h, 30m, 1d, today, yesterday, or 2026-11-19T14:00')


def when(stamp: str, now: dt.datetime) -> str:
    """An ISO stamp as a person reads it: "14:05" today, "yesterday 21:02", else "11-17 21:02"."""
    t = dt.datetime.fromisoformat(stamp)
    days = (now.date() - t.date()).days
    return t.strftime('%H:%M') if days == 0 else ('yesterday ' if days == 1 else t.strftime('%m-%d ')) + t.strftime('%H:%M')


def since_text(log_lines: list[str], start: dt.datetime, titles: dict[str, str], now: dt.datetime,
               since_mark: bool = False, waiting=None) -> tuple[str, str | None]:
    """(what `since` prints, the newest stamp it read or None): the concepts waiting for the person's OK first
    (`waiting`, however old), then each event after `start`, oldest first, one short line each; or one line
    saying there is nothing new."""
    text, last = _since_events(log_lines, start, titles, now, since_mark)
    return '\n'.join([*waiting_text(waiting, now=now), text]), last


def _since_events(log_lines: list[str], start: dt.datetime, titles: dict[str, str], now: dt.datetime,
                  since_mark: bool) -> tuple[str, str | None]:
    out, last = [], None
    for l in log_lines:
        if not (m := SINCE_LINE.match(l)):
            continue
        try:
            if dt.datetime.fromisoformat(m[1]) <= start:
                continue
        except ValueError:
            continue
        last = m[1]
        if e := since_event(l, titles):
            out.append(f'  {when(e[0], now)}  {e[2]}')
    head = f'since {when(start.isoformat(timespec="seconds"), now)}' + (' (your last look)' if since_mark else '')
    return (f'{head}:\n' + '\n'.join(out) if out else f'nothing new {head}'), last


def since_mark_file() -> Path:
    return C.notes('since.last')


def move_since_mark(stamp: str) -> None:
    """Move `<notes>/since.last` forward to `stamp` (never back: a `since yesterday` does not show again what
    the last look saw)."""
    f = since_mark_file()
    try:
        old = f.read_text(encoding='utf-8').strip()
        if old and dt.datetime.fromisoformat(old) >= dt.datetime.fromisoformat(stamp):
            return
    except (OSError, ValueError):
        pass
    tmp = f.with_name(f.name + '.tmp')
    tmp.write_text(stamp + '\n', encoding='utf-8')
    os.replace(tmp, f)


def what_changed(tid: str) -> str:
    """The first sentence of the commit subject a task landed with (its `done` message), without the id; ''."""
    r = git('log', '-n', '1', '-E', f'--grep=^{re.escape(tid)}( |:|$)', '--format=%s', 'HEAD')
    subj = r.stdout.strip() if not r.returncode else ''
    subj = re.sub(rf'^{re.escape(tid)}[: ]\s*', '', subj)
    subj = re.split(r'(?<=[.;:])\s|\s—\s|, (?=and |so |which )', subj, maxsplit=1)[0].rstrip(' .;:')
    return subj if len(subj) <= 100 else subj[:99].rsplit(' ', 1)[0] + '…'


NEEDS_YOU = ('needs you', 'looks stuck', 'run held, needs you',
             'stuck, not merged')  # since_event kinds only a person can clear (B32: a parked task too)


def needs_you_line(line: str, titles: dict[str, str], now: dt.datetime, waiting) -> str | None:
    """A run.log line as `since --follow --needs-you` prints it, or None when it does not need the person: the run
    held (STOPPED, with what holds it), a task left for a human, one that looks stalled, and a task that landed
    or blocked waiting on a person's answer (a CONFIRM/DECIDE/BLOCKED ask, or a concept page waiting for an OK:
    `waiting` is `waiting_ok()`'s list, read after the line was logged)."""
    if not (e := since_event(line, titles)):
        return None
    kind = e[2].split(': ', 1)[0]
    if kind in NEEDS_YOU:
        what = e[2]
        if kind == 'run held, needs you' and (m := SINCE_LINE.match(line)):
            held = m[2][len('STOPPED: '):].strip()
            what = f'{kind}: {held if len(held) <= 240 else held[:239].rsplit(" ", 1)[0] + "…"}'
        return f'{when(e[0], now)}  {what}'
    if e[1] and kind in ('landed', 'part landed, rest stuck'):
        for label, tid, k, ask, url, title, shelved, *_ in waiting or []:
            if e[1] in (tid, k) and not shelved:  # B27: in everyday words, no caps label
                return f'{when(e[0], now)}  {ASK_FEED}' + '  '.join(
                    x for x in (f'{P.plain_ask(label, ask, title or titles.get(tid) or tid)} [{tid}]', url) if x)
    return None


ASK_FEED = 'needs you: '  # how a feed line about an item under Needs you starts (B27; was 'waits for you: ')


def follow_lines(chunk: str, titles: dict[str, str], now: dt.datetime, needs_you: bool = False,
                 waiting=None) -> tuple[list[str], str | None]:
    """The lines `since --follow` prints for new run.log text: one plain line per event, a landed task with
    what changed; and the newest stamp read. `needs_you`: only what needs the person (`needs_you_line`)."""
    out, last = [], None
    for l in chunk.splitlines():
        if m := SINCE_LINE.match(l):
            last = m[1]
        if needs_you:
            if nl := needs_you_line(l, titles, now, waiting):
                out.append(nl)
            continue
        if e := since_event(l, titles):
            line = f'{when(e[0], now)}  {e[2]}'
            if e[1] and e[2].startswith('landed: ') and (did := what_changed(e[1])):
                line += f' — {did}'
            out.append(line)
            if waiting and (e[1] and e[2].split(': ', 1)[0] in ('landed', 'part landed, rest stuck')) \
                    and (nl := needs_you_line(l, titles, now, waiting)):
                out.append(nl)  # the full feed carries the asks too: the runner feed is the one watch
    return out, last


def follow(poll: float = 2.0, until: float | None = None, needs_you: bool = False, mark: bool = True,
           hold=None, end=None) -> int:
    """`since --follow`: print one plain line per new event as run.log gets it, moving the since mark as it
    prints; from the log's end, until killed (or `until`, a monotonic deadline, for tests). `needs_you`: only
    what needs the person (`needs_you_line`), and the mark stays put: the landed and started lines it skips
    are still news for the next `since`. `mark=False` (the board): the mark stays put too.
    `hold` (the runner feed, `board_held`): while it says so, nothing is read or printed, so the feed's
    session gets no turn; what was logged meanwhile prints when it lets go. `end`: stop once it says so
    (the board, once its run has ended)."""
    logf = C.notes('run.log')
    try:
        pos = logf.stat().st_size
    except OSError:
        pos = 0
    print(f'watching {logf} for what needs you: the run held, a task left for you, stalled, or waiting on your '
          f'answer' if needs_you else
          f'following {logf}: one line per landed, started or stuck task, and when the run goes idle or stops',
          flush=True)
    buf = ''
    while until is None or time.monotonic() < until:
        if end is not None and end():
            return 0
        if hold is not None and hold():
            try:
                time.sleep(poll)
            except KeyboardInterrupt:
                return 0
            continue
        try:
            size = logf.stat().st_size
            if size < pos:  # the log was cut or replaced: read it again from the top
                pos = 0
            if size > pos:
                with open(logf, 'rb') as f:
                    f.seek(pos)
                    data = f.read()
                pos += len(data)
                buf += data.decode('utf-8', errors='replace')
                chunk, _, buf = buf.rpartition('\n')
                lines, last = follow_lines(chunk, task_titles(), dt.datetime.now(), needs_you,
                                           waiting_ok() if 'merged, ' in chunk else None)
                for l in lines:
                    print(l, flush=True)
                if last and mark and not needs_you:
                    move_since_mark(last)
        except OSError:
            pass
        except KeyboardInterrupt:
            return 0
        try:
            time.sleep(poll)
        except KeyboardInterrupt:
            return 0
    return 0


def cmd_since(argv: list[str], prog: str = f'{RUNNER} since') -> int:
    """`agent-runner since [2h|yesterday|…] [--follow]`: what happened since the last look, one short line each."""
    ap = argparse.ArgumentParser(prog=prog, description='What happened since you last looked (or since WHEN): '
                                 'landed, started, stuck, needs you, run idle or stopped, oldest first.')
    ap.add_argument('when', nargs='?', help='2h, 30m, 1d, today, yesterday, or a date/time; default: the last `since`')
    ap.add_argument('--follow', '-f', action='store_true',
                    help='stay running and print one line per new event as it happens')
    ap.add_argument('--needs-you', action='store_true',
                    help='with --follow: only what needs you (the run held, a task left for you, stalled, or '
                         'waiting on your answer), and the last-look mark stays put')
    ap.add_argument('--keep-mark', action='store_true',
                    help='with --follow: leave the last-look mark where it is, and print nothing while the run '
                         'is idle, or paused or stopping with nothing running (the runner feed)')
    ap.add_argument('--board', action='store_true',
                    help="the board window's feed: a header, the last 6 hours, then --follow; the last-look mark "
                         "stays put, and no tokens are used")
    ap.add_argument('--feed', action='store_true',
                    help='with --board: run the runner feed (the Haiku session on Remote Control) instead, and end '
                         'it with --run-pid')
    ap.add_argument('--run-pid', type=int, default=0, metavar='PID',
                    help='with --board: the run that opened it; the board ends once that process has')
    a = ap.parse_args(argv)
    init()
    if a.needs_you and not a.follow:
        ap.error('--needs-you goes with --follow')
    if (a.feed or a.run_pid) and not a.board:
        ap.error('--feed and --run-pid go with --board')
    if a.board:
        return board_feed(a.run_pid) if a.feed else board(a.run_pid)
    if a.follow:
        return follow(needs_you=a.needs_you, mark=not a.keep_mark, hold=board_held if a.keep_mark else None)
    f = since_mark_file()
    try:
        mark = f.read_text(encoding='utf-8').strip() or None
    except OSError:
        mark = None
    now = dt.datetime.now().replace(microsecond=0)
    start = since_start(a.when, mark, now)
    try:
        lines = C.notes('run.log').read_text(encoding='utf-8', errors='replace').splitlines()
    except OSError:
        lines = []
    text, last = since_text(lines, start, task_titles(), now, since_mark=not a.when and bool(mark),
                            waiting=waiting_ok())
    print(text)
    move_since_mark(last or now.isoformat())
    return 0


def waiting_ok() -> list[tuple]:
    """What waits for the person (`plan.asks`, shelved ones too), from the main checkout's TODO.md: concept pages
    and tasks blocked on a person."""
    try:
        if not C.todo.exists():
            return []
        stamps = P.asked_at(C.todo)
        return [(*a, stamps.get(a[1], '')) for a in P.asks(C.todo, all=True)]
    except (OSError, SystemExit):
        return []


# --- F17: wizards for BLOCKED items a person must do by hand --------------------------------------------------
#
# A slot agent that blocks with `BLOCKED:` on steps only a person can take (a login, a cert, a secret, a
# dashboard click) also writes a bash wizard to `<notes>/wizards/<ID>.sh`, from `wizard_template.sh` (vendored
# from mattpocock/skills, MIT). Needs you then shows `run: agent-runner wizard <ID>` under the item, and that
# command checks it with `bash -n`, runs it in the main checkout, and on exit 0 confirms the item
# (`plan confirm`). `[run] wizards = false` turns it off: no brief paragraph, no run line.

WIZARD_TEMPLATE = Path(__file__).with_name('wizard_template.sh')

WIZARD_PROMPT = """\
When you block with `BLOCKED:` because of steps only a person can take (a login, a certificate or signing key, \
a secret, a click in a third-party dashboard), also write a wizard that walks them through those steps: copy \
{template} to {path} and replace its example with one `stage` per step, in order (`open_url` before asking \
for what that page shows, `ask_secret` for anything secret, `write_env` / `set_secret` where each value \
belongs, `confirm` before anything irreversible); leave the library above its STAGES marker as it is. Check \
it with `bash -n {path}`; do not run it. Say only what you know of each page or command, not guesses. Write \
one only for steps you cannot do yourself, never for a CONFIRM or a DECIDE, and never put a secret in it. \
Needs you shows the person `{runner} wizard {tid}`, and finishing the wizard confirms the item."""


def wizards_on() -> bool:
    try:
        return C.run.get('wizards', True) is not False
    except AttributeError:  # no config loaded
        return False


def wizard_file(tid: str) -> Path | None:
    """`<notes>/wizards/<tid>.sh` when wizards are on and one is there, else None."""
    if not wizards_on():
        return None
    try:
        f = C.notes('wizards', f'{tid}.sh')
    except (OSError, SystemExit):
        return None
    return f if f.is_file() else None


def wizard_cmd(tid: str) -> str:
    """The one command Needs you gives for `tid`'s wizard."""
    return f'{C.command} wizard {tid}'


def cmd_wizard(argv: list[str], prog: str = f'{RUNNER} wizard') -> int:
    """`agent-runner wizard ID`: run the wizard an agent left for a BLOCKED item, then confirm the item."""
    ap = argparse.ArgumentParser(prog=prog, description='Walk through the hand steps a blocked task needs '
                                 '(a login, a cert, a secret), then confirm it.')
    ap.add_argument('id', help='the task id, as Needs you shows it')
    ap.add_argument('--check', action='store_true', help='only check the script (bash -n), run nothing')
    ap.add_argument('--path', action='store_true', help='print where the script is, run nothing')
    a = ap.parse_args(argv)
    init()
    f = C.notes('wizards', f'{a.id}.sh')
    if a.path:
        print(f)
        return 0
    if not f.is_file():
        print(f'{prog}: {a.id} has no wizard ({f})', file=sys.stderr)
        return 1
    chk = sp.run(['bash', '-n', str(f)], capture_output=True, text=True)
    if chk.returncode:
        print(f'{prog}: {f} does not parse, so it was not run:\n{chk.stderr.strip()}', file=sys.stderr)
        return 1
    if a.check:
        print(f'{f}: ok')
        return 0
    r = sp.run(['bash', str(f)], cwd=str(C.root))
    if r.returncode:
        print(f'{prog}: the wizard stopped (exit {r.returncode}); {a.id} still needs you. '
              f'Run `{wizard_cmd(a.id)}` again to carry on.', file=sys.stderr)
        return r.returncode
    from agent_runner import plan
    return plan.main(['confirm', a.id, 'the wizard ran to the end'])


def waiting_text(waiting, width: int = 60, now: dt.datetime | None = None) -> list[str]:
    """B27: '[needs] heading' ('Needs you:') and per ask one line in everyday words, what is asked and what to
    reply, with its age first ('2h', when `[needs] ages`) and its [id] last, then its link on a line of its
    own; in `[needs] order` (oldest first); a count of the shelved ones last. [] for none. `waiting` is
    `waiting_ok()`'s list: asks tuples, an `(asked …)` stamp eighth when there is one. No caps labels."""
    if not waiting:
        return []
    cf = P.needs_cfg()
    now = now or dt.datetime.now()
    stamps = {w[1]: w[7] for w in waiting if len(w) > 7 and w[7]}
    out, shelved = [], 0
    for label, tid, k, what, url, title, sh, *_ in P.in_order(waiting, stamps, cf['order']):
        if sh:
            shelved += 1
            continue
        title = title if len(title) <= width else title[:width - 1].rstrip() + '…'
        old = P.age(stamps.get(tid, ''), now) if cf['ages'] else ''
        out.append('  ' + (f'{old:>3}  ' if old else '') + f'{P.plain_ask(label, what, title)} [{k or tid}]')
        if url:
            out.append(f'    {url}')
        if label != 'CONCEPT' and wizard_file(tid):  # F17: the one command that walks them through it
            out.append(f'    run: {wizard_cmd(tid)}')
    if not out:
        return []  # only shelved ones: they asked to leave this list
    if shelved:
        out.append(f'  ({shelved} shelved: plan waiting --all)')
    return [f'{cf["heading"]}:'] + out


def status_text(up: bool, st: dict, log_lines: list[str], titles: dict[str, str], now: float, width: int = 60,
                waiting=None) -> str:
    """`agent-runner status`, short enough for a phone: concepts waiting for the person's OK first, then the
    run's state, each slot's task, title and minutes, what is merging, the last few merged / blocked / parked,
    and usage."""
    out = waiting_text(waiting, now=dt.datetime.fromtimestamp(now) if now else None)
    out.append(f'run up: {st.get("state", "starting")}' if up else 'no run is up')
    for n, tid in sorted(st.get('running', {}).items(), key=lambda kv: (not kv[0].isdigit(), kv[0].zfill(4))):
        title = titles.get(tid, '')
        title = title if len(title) <= width else title[:width - 1].rstrip() + '…'
        mins = f'{int((now - st["since"][n]) // 60)} min' if n in st.get('since', {}) else ''
        out.append('  ' + '  '.join(x for x in (f's{n}' if n.isdigit() else n, f'{title} [{tid}]' if title else tid,
                                                 mins) if x))
    if up and not st.get('running'):
        out.append('  no task running')
    if st.get('merging'):
        out.append('merging: ' + ', '.join(f'{titles[t]} [{t}]' if titles.get(t) else t for t in st['merging']))
    events = [m for l in log_lines[-2000:] if EVENT.match(l) and (m := since_event(l, titles))]
    if events:
        out.append('lately:')
        out += [f'  {m[0][11:16]} {m[2]}' for m in events[-5:]]
    use = st.get('usage') or {}
    if any(v is not None for v in use.values()):
        out.append('usage: ' + ', '.join(f'{w} {use[k]:.0f}%' for k, w in (('five_hour', 'session'), ('seven_day', 'week'))
                                         if use.get(k) is not None))
    return '\n'.join(out)


def cmd_stop(argv: list[str], prog: str = f'{RUNNER} stop') -> int:
    """`./run stop`: the running sessions finish and merge, nothing new starts, and the run exits."""
    ap = argparse.ArgumentParser(prog=prog, description='Finish the running tasks, start nothing new, then exit.')
    ap.add_argument('--force', action='store_true',
                    help='end the agent sessions now (each resumes in the next run), as s! in the pane')
    power = ap.add_mutually_exclusive_group()
    power.add_argument('--suspend', action='store_true', help='then suspend the computer')
    power.add_argument('--shutdown', action='store_true', help='then shut the computer down')
    power.add_argument('--undo', action='store_true', help='take a gentle stop back: start tasks again')
    a = ap.parse_args(argv)
    init()
    if a.undo:
        if a.force:
            ap.error('--undo takes back a gentle stop; a stop now (--force) is under way already')
        send_key('s off') if run_up() else clear_stop()
        print('stop taken back')
        return 0
    if a.suspend or a.shutdown:
        C.notes('POWER').write_text('suspend' if a.suspend else 'shutdown', encoding='utf-8')
    ask_stop(f'{C.command} stop' + (' --force' if a.force else ''), force=a.force)
    print(f'asked the run to stop ({C.notes("STOP")}); it exits once '
          + ('its sessions are ended and the merges under way are done' if a.force else
             'the running tasks are merged')
          + (f', then {"suspends" if a.suspend else "shuts down"} the computer' if a.suspend or a.shutdown else ''))
    return 0


# --- the run in the background: bare `agent-runner`, and `attach` ----------------------------------------

STARTED = re.compile(r'^=== \S+ (?:run: (\d+) slots? in|sequential run on)')  # the line a run logs once it is up


def background_session() -> str:
    """The detached tmux session bare `agent-runner` starts the run in: "ar-<repo>"."""
    return f"ar-{re.sub(r'[^A-Za-z0-9_-]', '-', ROOT.name)}"


def background_env() -> list[str]:
    """NAME=value for the runner in a new tmux session, which gets the tmux server's environment, not this
    shell's: the PATH the agent and git are found on, the runner's and Claude's own variables, `[run] pass_env`."""
    keep = ('PATH', 'VIRTUAL_ENV', *C.run['pass_env'])
    return [f'{k}={v}' for k, v in sorted(os.environ.items())
            if k in keep or k.startswith(('AGENT_RUNNER', 'CLAUDE_', 'ANTHROPIC_'))]


def tmux_launch_argv(session: str, win: str, root: Path, cmd: str, env: list[str], exists: bool) -> list[str]:
    """The tmux command that starts `cmd` (`agent-runner run`) detached, in the window `win` of `session`: a new
    session, or a new window when the session is already there (the slots' window of a run that ended is
    still in it, and the new run adopts its panes). The window stays after its run exits until the launch
    has seen the run come up (remain-on-exit), so a run that fails at once leaves its message to show."""
    envs = [a for e in env for a in ('-e', e)]
    start = (['new-window', '-d', '-t', f'={session}:'] if exists else ['new-session', '-d', '-s', session])
    return ['tmux', *start, '-n', win, '-c', str(root), *envs, cmd,
            ';', 'set-option', '-w', '-t', f'={session}:{win}', 'remain-on-exit', 'on']


def background_argv() -> list[str]:
    """What bare `agent-runner` starts on Windows, as a detached process: the run, its slot consoles hidden."""
    return [*runner_cmd(), 'run', '--hidden']


def claude_json() -> Path:
    cfg_dir = os.environ.get('CLAUDE_CONFIG_DIR')
    return Path(cfg_dir) / '.claude.json' if cfg_dir else Path.home() / '.claude.json'


def remote_ready(tty: bool | None = None, ask=input) -> bool:
    """With `[run] remote`: will Claude Code start a slot without its one-time "Enable Remote Control? (y/n)"?
    In a hidden pane that question would hold every slot, so it is asked here, in this terminal, and the
    answer kept where Claude Code keeps it (`remoteDialogSeen` in ~/.claude.json). False: start nothing.
    Under `[run] remote = 'auto'` (and no remote_slots) it never stops a run: with no terminal to ask on, or
    answered no, the run starts with Remote Control off, and its log says why."""
    auto = C.run['remote'] == 'auto' and not remote_slots_on()
    if not (remote_slots_on() or (not remote_off_why(dialog=False) if auto else remote_on())):
        return True
    f = claude_json()
    try:
        data = json.loads(f.read_text(encoding='utf-8')) if f.exists() else {}
    except (OSError, ValueError):
        data = None
    if data is not None and data.get('remoteDialogSeen'):
        return True
    if auto and (not (sys.stdin.isatty() if tty is None else tty) or data is None):
        return True  # off for this run: remote_off_why says so in its log
    if not (sys.stdin.isatty() if tty is None else tty) or data is None:
        print(f'[run] remote is on, and Claude Code asks once, at a terminal, before Remote Control starts.\n'
              f'Run `claude remote-control` in a terminal and answer y (it does not ask again), then {RUNNER} again;\n'
              f'or set [run] remote = false (runner.local.toml for this machine). Nothing started.', file=sys.stderr)
        return False
    print('[run] remote is on: sessions start on Remote Control, which Claude Code asks about once.\n'
          'Answered here, the sessions in the background will not stop at the question.')
    try:
        yes = ask('Enable Remote Control? (y/n) ').strip().lower() in ('y', 'yes')
    except EOFError:
        yes = False
    if not yes and auto:
        print('Remote Control stays off for this run. [run] remote = false (runner.local.toml for this machine) '
              'stops this question.')
        return True
    if not yes:
        print(f'Nothing started: the slots would stop at that question. Set [run] remote = false to run '
              f'without Remote Control.', file=sys.stderr)
        return False
    data['remoteDialogSeen'] = True
    tmp = f.with_name(f'{f.name}.agent-runner.tmp')
    tmp.write_text(json.dumps(data, indent=2), encoding='utf-8')
    os.replace(tmp, f)
    return True


def wait_started(since: int, gone, timeout: float = 30.0) -> int | None:
    """Wait for the run's start line in run.log past byte `since`; its slot count (0 for the sequential run),
    or None when `gone()` says the run ended first or `timeout` passed."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            with open(C.notes('run.log'), 'rb') as f:
                f.seek(since)
                new = f.read().decode('utf-8', 'replace')
        except OSError:
            new = ''
        for l in new.splitlines():
            if m := STARTED.match(l):
                return int(m.group(1) or 0)
        if gone():
            return None
        time.sleep(0.3)
    return None


def started_note(slots: int, where: str) -> str:
    attach = ("its pane (attach s2: slot 2's); detach again with Ctrl-b d" if not plat.WINDOWS else
              "slot 2's console window: attach s2 (closing that window ends the session)")
    lines = [f'the run is up in the background: {slots or 1} slot{"s" if slots != 1 else ""}{"" if slots else " (sequential)"}, {where}',
             f'    {RUNNER} status     what it is doing',
             f'    {RUNNER} attach     {attach}',
             f'    {RUNNER} stop       finish the running tasks, then end it (--force: now)']
    if C.run['control'] and control_ok():
        beside = 'c1 runs beside the run: attach c1' + (' (terminal only; the apps start control sessions from '
                                                        'the control server)' if remote_on() else '')
        lines.append(f'    {RUNNER} control    a control session in this terminal ({beside})')
    if remote_on():
        lines.append(f'    {REMOTE_URL}  the control sessions, from any device or the Claude apps')
    elif remote_slots_on():
        lines.append(f'    {REMOTE_URL}  the slots, from any device or the Claude apps')
    return '\n'.join(lines)


def tmux_hint() -> str:
    how = ('brew install tmux' if sys.platform == 'darwin' else
           'sudo apt install tmux, sudo dnf install tmux or sudo pacman -S tmux, as your system has it')
    return (f'tmux is not installed: the background run lives in a detached tmux session. Install it ({how}),\n'
            f'then {RUNNER} again; or run in this terminal: {RUNNER} run. Nothing started.')


def cmd_background(argv: list[str]) -> int:
    """Bare `agent-runner`: start the run where no terminal shows it, and give the prompt back. POSIX: a detached
    tmux session "ar-<repo>" running `agent-runner run`, its slots' window in the same session. Windows: the run
    as a detached process, each slot in a console window that starts hidden."""
    drop_session_env()
    init()
    sess = background_session()
    if run_up():
        print(f'a run is already up in this repository: {RUNNER} status, {RUNNER} attach '
              f'(tmux attach -t {sess} when it was started in the background), {RUNNER} stop')
        return 0
    if not plat.WINDOWS and not shutil.which('tmux'):
        print(tmux_hint(), file=sys.stderr)
        return 1
    if not remote_ready():
        return 1
    log_file = C.notes('run.log')
    since = log_file.stat().st_size if log_file.exists() else 0
    if plat.WINDOWS:
        out = C.notes('background.out')
        proc = plat.spawn_detached(background_argv(), out=out)
        slots = wait_started(since, lambda: proc.poll() is not None)
        if slots is None:
            try:
                said = out.read_text(encoding='utf-8', errors='replace').strip()[-2000:]
            except OSError:
                said = ''
            print(f'the run did not come up' + (f':\n{said}' if said else f'; see {log_file}'), file=sys.stderr)
            return 1
        print(started_note(slots, 'slot consoles hidden'))
        return 0
    win = window('runner')
    exists = not tmux('has-session', '-t', f'={sess}').returncode
    for c in session_env_masks(sess) if exists else ():  # an earlier launch from a Claude session left them
        tmux(*c)
    if exists:  # a dead runner window left from a failed start would take the name
        tmux('kill-window', '-t', f'={sess}:{win}')
    cmd = plat.command_text([*runner_cmd(), 'run'])
    r = sp.run(tmux_launch_argv(sess, win, ROOT, cmd, background_env(), exists), capture_output=True, text=True)
    if r.returncode:
        print(f'tmux could not start the run: {r.stderr.strip()}', file=sys.stderr)
        return 1
    for c in session_env_masks(sess) if not exists else ():  # a new session takes the server's global env
        tmux(*c)
    target = f'={sess}:{win}'

    def gone() -> bool:
        p = tmux('list-panes', '-t', target, '-F', '#{pane_dead}')
        return p.returncode != 0 or p.stdout.strip() == '1'

    slots = wait_started(since, gone)
    settle = time.monotonic() + 3  # a run that fails setting up its first slots does so right after its start line
    while slots is not None and time.monotonic() < settle:
        slots = None if gone() else slots
        time.sleep(0.3)
    if slots is None:
        said = '\n'.join([l for l in tmux('capture-pane', '-p', '-J', '-t', target).stdout.splitlines() if l.strip()][-25:])
        tmux('kill-window', '-t', target)
        print(f'the run did not come up' + (f':\n{said}' if said else f'; see {log_file}'), file=sys.stderr)
        return 1
    tmux('set-option', '-w', '-t', target, 'remain-on-exit', 'off')  # up: when it ends, its window goes with it
    print(started_note(slots, f'in tmux session {sess}'))
    return 0


def attach_target(rows: list[str], root: Path, which: str) -> tuple[str, str] | None:
    """(session, pane id) of the runner's pane (`which` "runner") or a tagged pane (s2, master) of the run for
    `root`, from `tmux list-panes -a` rows of session, pane id, @runner, @runner-repo, @runner-run."""
    for l in rows:
        sess, pane_id, name, repo, run_for = (l.split('\t') + [''] * 5)[:5]
        mine = run_for if which == 'runner' else repo if name == which else ''
        if mine and Path(mine) == root:
            return sess, pane_id
    return None


def attach_argv(sess: str, pane_id: str, inside: bool) -> list[list[str]]:
    """The tmux commands that bring up `pane_id`: select its window and pane, then switch this client to its
    session (inside tmux) or attach this terminal to it."""
    return [['tmux', 'select-window', '-t', pane_id], ['tmux', 'select-pane', '-t', pane_id],
            ['tmux', 'switch-client' if inside else 'attach-session', '-t', sess]]


def cmd_background_attach(argv: list[str]) -> int:
    """`agent-runner --attach`: the background run (started now, or the one already up in this repo), then its
    pane in this terminal, as `attach` shows it; Ctrl-b d sends it back. Inside tmux it switches the client.
    Windows: the run has no pane to attach, so it is bare `agent-runner`, and says so."""
    if argv:
        print(f'{RUNNER} --attach takes nothing more (got {" ".join(argv)})', file=sys.stderr)
        return 2
    init()
    if plat.WINDOWS:
        print(f'on Windows the run has no window to attach: --attach starts it as {RUNNER} does')
        return cmd_background([])
    if not run_up():
        if r := cmd_background([]):
            return r
    return cmd_attach([])


def cmd_attach(argv: list[str], prog: str = f'{RUNNER} attach') -> int:
    """`agent-runner attach [sN]`: the runner's pane, or a slot's; on Windows a slot's console window."""
    ap = argparse.ArgumentParser(prog=prog, description="Show the run's pane, or a slot's (s2, or 2).")
    ap.add_argument('slot', nargs='?', default='', help='s2 (or 2) for slot 2; master for a fix session; board for the board '
                    'window; none: the runner')
    a = ap.parse_args(argv)
    init()
    which = f's{a.slot}' if a.slot.isdigit() else (a.slot or 'runner')
    if plat.WINDOWS:
        if which == 'runner':
            print(f'on Windows the run has no window of its own: {RUNNER} status shows it, and its log is '
                  f'{C.notes("run.log")}. {RUNNER} attach s1 shows slot 1.')
            return 0
        pid = marker_pid(C.notes(f'slot{which[1:]}.live')) if re.fullmatch(r's\d+', which) else 0
        if not (pid and alive(pid)):
            print(f'{which} is not running: {RUNNER} status lists the slots', file=sys.stderr)
            return 1
        if not plat.show_console(pid):
            print(f'{which} runs as pid {pid}, but its console window could not be shown', file=sys.stderr)
            return 1
        print(f'{which}: its console window is up (minimize it to hide it again; closing it ends the session)')
        return 0
    rows = tmux('list-panes', '-a', '-F', f'#{{session_name}}\t#{{pane_id}}\t#{{{TAG}}}\t#{{{REPO_TAG}}}\t#{{{RUN_TAG}}}')
    hit = attach_target(rows.stdout.splitlines(), ROOT, which) if not rows.returncode else None
    if not hit:
        print((f'no pane {which} in tmux for this repository' if which != 'runner' else
               'no run in tmux for this repository') + f': {RUNNER} status; {RUNNER} starts the run', file=sys.stderr)
        return 1
    *select, go = attach_argv(*hit, inside=bool(os.environ.get('TMUX')))
    for c in select:
        sp.run(c, capture_output=True)
    return sp.call(go)


# --- control sessions: a person runs the run from an interactive session in the main checkout -------------

CONTROL_SERVER_WAIT = (30, 600)  # s before the control server restarts after it exits, doubling to the second


def control_ok() -> bool:
    """Control sessions are Claude Code sessions: none for Copilot CLI or pi."""
    return not copilot() and not pi()


def control_brief() -> str:
    """What every control session is told, through its SessionStart hook (`control --brief` prints it)."""
    from agent_runner.guide import CONTROL, CONTROL_ANSWER, CONTROL_FEED_WATCH, CONTROL_NO_ANSWER, CONTROL_WATCH
    notes = Path(C.run['notes']).expanduser()
    logf = (notes / 'run.log').as_posix() if not notes.is_absolute() else str(notes / 'run.log')
    watch = (CONTROL_FEED_WATCH if feed_on() else CONTROL_WATCH).format(repo=ROOT.name, cmd=C.command)
    cf = P.needs_cfg()  # B27: the heading's words, and whether a reply naming no id maps to an item
    answer = (CONTROL_ANSWER if cf['map_replies'] else CONTROL_NO_ANSWER).format(cmd=C.command)
    return CONTROL.format(repo=ROOT.name, cmd=C.command, log=logf, watch=watch, needs=cf['heading'], answer=answer)


def control_settings_data() -> dict:
    """`<notes>/control-settings.json`, given to every control session and the control server with --settings:
    a SessionStart hook (every source: startup, resume, clear, compact) that prints the control brief, so each
    one gets it the same way however it started; and the runner's commands, Read and Monitor allowed without a
    prompt. Control sessions run with bypassPermissions (`control_argv`, `control_server_argv`), so a person on a
    phone never waits on a permission question; the bypass dialog is skipped here for the same reason. No Stop
    hook: a control session is never ended on idle."""
    hook = plat.command_text([*runner_cmd(), 'control', '--brief'])
    return {'hooks': {'SessionStart': [{'hooks': [{'type': 'command', 'command': hook}]}]},
            'skipDangerousModePermissionPrompt': True,
            'permissions': {'additionalDirectories': [str(control_skills_dir())]}}


CONTROL_SKILL = 'control'  # the slash command: Claude Code's /new is /clear's alias, so not that


def control_skills_dir() -> Path:
    """`<notes>/control-skills`: a directory only control sessions add (`--add-dir`, and the settings'
    additionalDirectories), holding `.claude/skills/control/SKILL.md`, the /control slash command that opens
    another control session. Never in the person's repo files."""
    from agent_runner.guide import control_skills  # /control, and the opening hints line's /run /since …
    for name, text in control_skills(C.command, CONTROL_SKILL).items():
        f = C.notes('control-skills', '.claude', 'skills', name, 'SKILL.md')
        try:
            if not f.is_file() or f.read_text(encoding='utf-8') != text:
                f.write_text(text, encoding='utf-8')
        except OSError:
            pass
    return f.parents[3]


def control_settings() -> Path:
    """Write the control settings file when its text changed; its path."""
    f = C.notes('control-settings.json')
    text = json.dumps(control_settings_data(), indent=2) + '\n'
    try:
        if f.read_text(encoding='utf-8') == text:
            return f
    except OSError:
        pass
    tmp = f.with_name(f.name + '.tmp')
    tmp.write_text(text, encoding='utf-8')
    os.replace(tmp, f)
    return f


def control_title(ask: str = '', images: list[str] | tuple = ()) -> str:
    """A short title for a control session opened with `--ask`: the ask's first words (up to 5, trimmed at a word
    to about 40 characters, trailing punctuation dropped); for a files-only ask "screenshot" when they are all
    images, else the first file's name (B30); "" without one."""
    words = (ask or '').split()[:5]
    while len(' '.join(words)) > 40 and len(words) > 1:
        words.pop()
    title = ' '.join(words)
    if len(title) > 40:
        title = title[:39].rstrip() + '…'
    title = title.rstrip(' ,.;:-–—')
    if title or not images:
        return title
    if all(Path(i).suffix.lower() in IMAGE_EXTS for i in images):
        return 'screenshot'
    return attached_name(images[0])[:40]


def control_name(n: int, ask: str = '', images: list[str] | tuple = ()) -> str:
    """Control session `n`'s name in the Claude apps (B25): "<repo> · N · <title>" when opened with an ask
    (`control_title`; N kept so higher is newer and `attach cN` still matches), else "<repo> · control N"."""
    title = control_title(ask, images)
    return f'{ROOT.name} · {n} · {title}' if title else f'{ROOT.name} · control {n}'


CONTROL_N_ENV = 'AGENT_RUNNER_CONTROL'  # F29: a control session's number, in its tools' environment


def control_summary_name(n: int, summary: str) -> str:
    """F29: the name control session `n` takes once it has read its first message: "<repo> · N · <summary>",
    the summary one line trimmed as an ask's title is (`control_title`), so `attach cN` still matches and
    `control_renamed` does not take it for the person's; "" for an empty summary."""
    title = control_title(' '.join(str(summary or '').replace('"', ' ').replace('`', ' ').split()))
    return f'{ROOT.name} · {n} · {title}' if title else ''


def control_pane(n: int) -> str:
    """The tmux pane control session `n` runs in: $TMUX_PANE when the caller is that session's own tool (its
    shells inherit the pane), else the pane tagged c<n> for this repository; '' for none."""
    if pane := os.environ.get('TMUX_PANE', ''):
        return pane
    if not shutil.which('tmux'):
        return ''
    rows = tmux('list-panes', '-a', '-F', f'#{{session_name}}\t#{{pane_id}}\t#{{{TAG}}}\t#{{{REPO_TAG}}}\t#{{{RUN_TAG}}}')
    hit = attach_target(rows.stdout.splitlines(), ROOT, f'c{n}') if not rows.returncode else None
    return hit[1] if hit else ''


def control_set_title(n: int, summary: str) -> int:
    """F29 `control --title SUMMARY`: control session `n` (its own $AGENT_RUNNER_CONTROL) names itself for what
    it is for, once it has read its first message: types `/rename <repo> · N · SUMMARY` into its pane (queued
    until its turn ends) and renames its tmux window. Not over a name the person gave it (B41)."""
    if not n:
        print(f'no control session number: run it from a control session, or give N ({RUNNER} control N --title …)',
              file=sys.stderr)
        return 2
    if not (name := control_summary_name(n, summary)):
        print('--title needs a few words saying what the session is for', file=sys.stderr)
        return 2
    try:
        sid = C.notes(f'control{n}.pid').read_text(encoding='utf-8').strip().partition(' ')[2]
    except OSError:
        sid = ''
    if sid and transcript(sid) and control_renamed(control_state(entries(sid, skip_bad=True)), n):
        print(f'control {n} keeps the name the person gave it')
        return 0
    if not (pane := control_pane(n)) or not send_to_pane(pane, f'/rename {name}'):
        print(f'control {n} has no tmux pane to rename it in; it stays as it is', file=sys.stderr)
        return 1
    tmux('rename-window', '-t', pane, name)
    try:
        C.notes(f'control{n}.title').write_text(name + '\n', encoding='utf-8')
    except OSError:
        pass
    print(f'control {n} is renamed "{name}" when this turn ends')
    return 0


def control_ask(ask: str, images: list[str] | tuple = ()) -> str:
    """The first message a handed-on request opens a control session with: `ask`, and for each `--file PATH`
    (`--image`: an alias) a line saying the person attached that file, by name and saved path, and to Read or open
    it before answering (the runner feed forwards text only, so a screenshot or an upload reaches the new session
    by its saved path, B30)."""
    lines = [ask] if ask else []
    lines += [f'The person attached {attached_name(p)}, saved at "{p}": Read or open it before you answer.'
              for p in images]
    return '\n\n'.join(lines)


UPLOAD_ID_RE = re.compile(r'^[0-9a-f]{8}-(.+)$')
IMAGE_EXTS = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.heic', '.bmp')


def attached_name(path: str) -> str:
    """The name the person gave a file they attached: Claude Code saves an upload as
    ~/.claude/uploads/<sid>/<8-hex id>-<name> (B30), so the id prefix is dropped there; else the base name."""
    p = Path(path)
    m = UPLOAD_ID_RE.match(p.name)
    return m.group(1) if m and 'uploads' in p.parts else p.name


def control_argv(n: int, sid: str, resume: bool, blank: bool = False, ask: str = '', local: bool = False,
                 images: list[str] | tuple = ()) -> list[str]:
    """Control session `n`: interactive, on `[run] model` (no model of its own), the brief from its settings
    file; with `[run] remote` on Remote Control as "<repo> · control N". Control 1 (the kept session the run
    starts) gets a first message asking for the status summary (`status` only: `since` would move the last-look
    mark past updates the person has not seen); any other (`control --new`, /control) gets none and stays blank
    until the person types, its brief still loaded by the SessionStart hook. bypassPermissions, as the slots: it
    is driven from a phone or the web as often as from here, and a permission prompt there stalls it. Not lean: a
    person is there (all tools, so /statusline and the like work). `blank` (`control 1 --blank`: the c1 a run
    with `[run] remote` opens): no first message either, so it costs nothing until the person types. `local`
    (`control 1 --local`, the same c1): not on Remote Control even with `[run] remote` on, so it is in the
    terminal only and its start pushes nothing; the control server is the apps' one entry. `ask`
    (`control --new --ask TEXT`, from the runner feed): TEXT is its first message instead; `images` (`--file
    PATH`, alias `--image`, repeatable) adds a line per attached file to it (`control_ask`)."""
    from agent_runner.guide import CONTROL_START, CONTROL_START_WATCH
    opening = CONTROL_START.format(cmd=C.command, watch_start='' if feed_on() else
                                   CONTROL_START_WATCH.format(cmd=C.command))
    ask_text, ask = ask, control_ask(ask, images)
    first = [ask] if ask else [opening] if n == 1 and not blank else []
    return [plat.exe(C.run['agent']), *first,
            '--resume' if resume else '--session-id', sid, '--model', C.run['model'],
            '--permission-mode', 'bypassPermissions',
            '--settings', str(control_settings()), '--add-dir', str(control_skills_dir()),
            *(['--remote-control', control_name(n, ask_text, images)] if remote_on() and not local else [])]


def control_live(n: int) -> int:
    """The pid control session `n` runs as (`<notes>/control<n>.pid`: "pid sid"), or 0. The sid in its command
    line tells it from a process that got the pid since (where the command line can be read)."""
    try:
        pid_s, _, sid = C.notes(f'control{n}.pid').read_text(encoding='utf-8').strip().partition(' ')
        pid = int(pid_s)
    except (OSError, ValueError):
        return 0
    if not alive(pid) or pid == os.getpid():
        return 0
    args = plat.cmdline(pid)
    return pid if args is None or not sid or sid in args or 'control' in args else 0


def control_number() -> int:
    """The first control number with no live session: 1 (the kept session) when it is free."""
    n = 1
    while control_live(n):
        n += 1
    return n


def control_sid(n: int) -> tuple[str, bool]:
    """(session id, resume?): c1 keeps its id in `<notes>/control.sid` and resumes it across runs while its
    transcript is there; any other control session starts fresh."""
    f = C.notes('control.sid')
    if n == 1:
        try:
            sid = f.read_text(encoding='utf-8').strip()
        except OSError:
            sid = ''
        if sid and backend().find_transcript(sid):
            return sid, True
    sid = str(uuid.uuid4())
    if n == 1:
        f.write_text(sid + '\n', encoding='utf-8')
    return sid, False


def control_env() -> dict:
    """The environment a control session gets: ours, without a slot's marks (`plan add` treats AGENT_RUNNER=1 as
    one of the runner's agents)."""
    return {k: v for k, v in os.environ.items() if k not in ('AGENT_RUNNER', 'AGENT_RUNNER_SLOT', 'AGENT_RUNNER_KEEP')}


def cmd_control(argv: list[str], prog: str = f'{RUNNER} control') -> int:
    """`agent-runner control [N]`: a control session in this terminal, in the main checkout. No N: c1 (the kept
    session, resumed) when it is not running, else the next free number."""
    drop_session_env()
    ap = argparse.ArgumentParser(prog=prog, description='A control session here: ask it for status, pause, '
                                 'slots, stop; it files asks with plan add and does do-it-now work with take.')
    ap.add_argument('n', nargs='?', type=int, help='its number (1 resumes the kept session); default the first free')
    ap.add_argument('--new', action='store_true', help='open another one without taking focus (a window in the '
                    "run's tmux session; Windows: a hidden console) and print its claude.ai/code link")
    ap.add_argument('--brief', action='store_true', help=argparse.SUPPRESS)  # the SessionStart hook
    ap.add_argument('--blank', action='store_true', help=argparse.SUPPRESS)  # c1 under [run] remote: no opening turn
    ap.add_argument('--local', action='store_true', help=argparse.SUPPRESS)  # c1 under [run] remote: not in the apps
    ap.add_argument('--ask', default='', metavar='TEXT', help="its first message (with --new: the runner feed hands "
                    'a person\'s request on this way)')
    ap.add_argument('--file', '--image', dest='file', action='append', default=[], metavar='PATH',
                    help='a file or image the person attached to the --ask message (repeatable): the first message '
                    'names it and its path and says to Read or open it')
    ap.add_argument('--unquiet', action='store_true', help=argparse.SUPPRESS)  # `unquiet_when_up`, for session N
    ap.add_argument('--title', default=None, metavar='SUMMARY', help='from inside control session N, once it has '
                    'read its first message: name it "<repo> · N · SUMMARY" for what it is for')
    a = ap.parse_args(argv)
    init()
    if a.brief:
        print(control_brief(), end='')
        return 0
    if a.title is not None:
        env_n = os.environ.get(CONTROL_N_ENV, '')
        return control_set_title(a.n or (int(env_n) if env_n.isdigit() else 0), a.title)
    if a.unquiet:
        unquiet_when_up(f'c{a.n}', os.environ.get('TMUX_PANE', ''))
        return 0
    if not control_ok():
        print(f'control sessions are Claude Code sessions; [run] agent is {C.run["agent"]}', file=sys.stderr)
        return 1
    if a.new:
        return control_new(a.n, ask=a.ask, images=a.file)
    n = a.n or control_number()
    if pid := control_live(n):
        print(f'control {n} already runs (pid {pid}): {RUNNER} control starts another', file=sys.stderr)
        return 1
    sid, resume = control_sid(n)
    argv = control_argv(n, sid, resume, blank=a.blank, ask=a.ask, local=a.local, images=a.file)
    backend().trust(ROOT)
    os.chdir(ROOT)
    pidf = C.notes(f'control{n}.pid')
    env = control_env()
    env[CONTROL_N_ENV] = str(n)  # F29: `control --title` from its tools knows which session it is
    if '--remote-control' in argv and silent() is not False:  # no push while it starts (silent: ever)
        env[PRESENCE_ENV] = str(quiet_file(f'c{n}'))
        if silent() is True:  # the file stays: this session never pushes
            pass
        elif plat.WINDOWS:
            threading.Thread(target=unquiet_when_up, args=(f'c{n}', ''), daemon=True).start()
        else:
            try:
                sp.Popen([*runner_cmd(), 'control', str(n), '--unquiet'], cwd=str(ROOT), stdin=sp.DEVNULL,
                         stdout=sp.DEVNULL, stderr=sp.DEVNULL, start_new_session=True)
            except OSError:
                quiet_file(f'c{n}', on=False)
                env.pop(PRESENCE_ENV)
    if not plat.WINDOWS:  # exec: the pid in the file is the session's own
        pidf.write_text(f'{os.getpid()} {sid}', encoding='utf-8')
        os.execvpe(argv[0], argv, env)
    p = sp.Popen(argv, env=env)
    pidf.write_text(f'{p.pid} {sid}', encoding='utf-8')
    while True:
        try:
            return p.wait()
        except KeyboardInterrupt:
            continue  # Ctrl-C is the session's (it interrupts a turn)


QUIET_WAIT = 30  # s a starting session stays quiet where its pane cannot be read (no tmux)


def unquiet_when_up(who: str, pane: str = '', log_file: Path | None = None, wait: float | None = None,
                    since: int = 0) -> None:
    """Remove `quiet_file(who)` once its session is up: its claude.ai/code link shows in tmux pane `pane`, or in
    `log_file` past byte `since` (the control server's); or `wait` s (CONTROL_LINK_WAIT) have passed; with
    neither to read, after QUIET_WAIT s."""
    wait = CONTROL_LINK_WAIT if wait is None else wait
    deadline = time.monotonic() + (wait if pane or log_file else QUIET_WAIT)
    while time.monotonic() < deadline:
        if pane:
            shown = tmux('capture-pane', '-p', '-J', '-t', pane, '-S', '-200')
            if shown.returncode or SESSION_LINK.search(shown.stdout or ''):
                break
        elif log_file:
            try:
                with open(log_file, 'rb') as fh:
                    fh.seek(since)
                    if REMOTE_URL.encode() in fh.read():
                        break
            except OSError:
                pass
        time.sleep(1)
    quiet_file(who, on=False)


def control_default_command(root: Path) -> str:
    """tmux's default-command for the run's background session: every pane or window a person opens there
    becomes a control session in the main checkout; a shell stays if one cannot start."""
    return (f'cd {shlex.quote(str(root))} && {plat.command_text([*runner_cmd(), "control"])} '
            f'|| exec "${{SHELL:-/bin/sh}}"')


def control_pane_argv(target: str, background: bool, sess: str, root: Path, cmd: str, env: list[str]) -> list[str]:
    """The tmux command opening c1: a pane split under the runner's pane `target` (a run in a terminal), or a
    window of its own, "control-<repo>", in the background session `sess`."""
    envs = [a for e in env for a in ('-e', e)]
    where = (['new-window', '-d', '-t', f'={sess}:', '-n', window('control')] if background else
             ['split-window', '-v', '-d', '-l', '40%', '-t', target])
    return ['tmux', *where, '-c', str(root), *envs, '-P', '-F', '#{pane_id}', cmd]


def start_control() -> None:
    """The run opens control session c1 beside it, unless `[run] control = false` or c1 already runs (it outlives
    a stopped run). With `[run] remote` it opens blank (no opening summary, so no tokens until the person types)
    and local (`--local`: no Remote Control, so no second app entry beside the control server's "<repo> ·
    control" and no start push; no quiet-c1 presence file either). tmux: under the runner's pane, or in the background session's own window, whose
    default-command makes every new pane a control session. Windows: a console of its own (hidden in the
    background run)."""
    if not C.run['control'] or not control_ok():
        return
    cmd = [*runner_cmd(), 'control', '1', *(['--blank', '--local'] if remote_on() else [])]  # remote: free till you type, terminal only
    here = os.environ.get('TMUX_PANE', '')
    if isinstance(MUX, TmuxMux) and here:
        sess = tmux('display-message', '-p', '-t', here, '#{session_name}').stdout.strip()
        background = sess == background_session()
        env = [e for e in background_env() if not e.startswith(('AGENT_RUNNER=', 'AGENT_RUNNER_SLOT=', 'AGENT_RUNNER_KEEP='))]
        if background:
            tmux('set-option', '-t', f'={sess}', 'default-command', control_default_command(ROOT))
            for e in env:
                tmux('set-environment', '-t', f'={sess}', *e.split('=', 1))
    if pid := control_live(1):
        log(f'control: c1 already runs (pid {pid})')
        return
    if isinstance(MUX, TmuxMux) and here:
        r = sp.run(control_pane_argv(here, background, sess, ROOT, plat.command_text(cmd), env),
                   capture_output=True, text=True)
        if r.returncode or not (pane_id := r.stdout.strip()):
            log(f'control: tmux could not open c1: {r.stderr.strip()}')
            return
        tmux('set-option', '-p', '-t', pane_id, TAG, 'c1')
        tmux('set-option', '-p', '-t', pane_id, REPO_TAG, str(ROOT))
        where = f'window {window("control")}' if background else 'the pane under this one'
        more = '; a new pane in this tmux session is another' if background else ''
    elif plat.WINDOWS:
        plat.spawn_console(cmd, ROOT, control_env(), hidden=HIDDEN[0])
        where, more = 'a console of its own' + (' (hidden)' if HIDDEN[0] else ''), ''
    else:
        return
    log(f'control: c1 is up in {where} ({RUNNER} control opens another{more})')


BOARD_EVERY = 30  # s between the run's checks that the board window is still there


def board_header() -> str:
    """The board's top lines: it only shows, and where to steer the run from."""
    where = (f'claude.ai/code: "{ROOT.name} · control" opens a control session' if remote_on() else
             f'{RUNNER} control (or a new pane in this tmux session)')
    return (f'{ROOT.name} board: what lands and what needs you, no tokens used. Steer from a control session:\n'
            f'    {where}\n' + '-' * 78)


def board(run_pid: int = 0) -> int:
    """`since --board`: the header, the last 6 hours, then the feed; the since mark is left for the person.
    With `run_pid` (the run that opened it) it ends once that process has, however the run ended."""
    print(board_header())
    now = dt.datetime.now().replace(microsecond=0)
    try:
        lines = C.notes('run.log').read_text(encoding='utf-8', errors='replace').splitlines()
    except OSError:
        lines = []
    print(since_text(lines, now - dt.timedelta(hours=6), task_titles(), now, waiting=waiting_ok())[0], flush=True)
    return follow(mark=False, end=(lambda: not plat.alive(run_pid)) if run_pid else None)


def board_held() -> bool:
    """Does the runner feed hold its lines (B13)? While the run is idle, or paused or stopping with nothing
    running or merging, nothing more lands until the run starts something or a task is added: the feed then
    prints nothing, so its Haiku session takes no turn and pushes nothing. No run up: nothing to hold for."""
    try:
        st = json.loads(C.notes('STATE').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return False
    if not isinstance(st, dict):
        return False
    held = bool(st.get('idle') or (st.get('paused') or st.get('stopping'))
                and not st.get('running') and not st.get('merging'))
    return held and run_up()  # STATE first: the lock is only probed when STATE would hold (a stale one, too)


BOARD_POLL = 2.0  # s between the board guard's looks at the run
BOARD_TERM = 10  # s the feed gets to end on SIGTERM before it is killed


def board_feed(run_pid: int = 0, poll: float = BOARD_POLL) -> int:
    """`since --board --feed`: the runner feed (`feed_argv`) as a child, ended once the run that opened it
    (`run_pid`) has: a plain stop once its tasks are done, a force stop, or a crash. The feed then goes
    offline in the apps and the board window closes. The feed ending on its own ends this too (`keep_board`
    opens it again while the run is up). Ctrl-C is the feed's own (it asks before it exits)."""
    sid, resume = feed_session() if run_pid else ('', False)  # B15: the run's feed carries on its one session
    try:
        proc = sp.Popen([*feed_argv(), *feed_session_args(sid, resume)])
    except OSError as e:
        print(f'board: could not start the runner feed: {e}', file=sys.stderr)
        return 1
    t0 = time.monotonic()
    # B12: one by hand is not the run's
    rec = rc_record('feed', feed_name(), proc.pid, run_pid, sid) if run_pid else None
    killed = False
    try:
        old = signal.signal(signal.SIGINT, signal.SIG_IGN)  # after the spawn: the child keeps its own Ctrl-C
    except ValueError:  # not the main thread (tests)
        old = None
    try:
        while True:
            try:
                rc = proc.wait(timeout=poll)
                if resume and rc and time.monotonic() - t0 < FEED_RESUME_FAIL:
                    feed_forget_session()  # its transcript is gone, say: the next start is a fresh session
                    print(f'board: the runner feed could not resume session {sid} (exit {rc}); the next start '
                          f'opens a new one', file=sys.stderr)
                return rc
            except sp.TimeoutExpired:
                pass
            if run_pid and not plat.alive(run_pid):
                proc.terminate()
                try:
                    proc.wait(timeout=BOARD_TERM)
                except sp.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                    killed = True
                return 0
    finally:
        rc_forget(rec, killed=killed)
        if old is not None:
            signal.signal(signal.SIGINT, old)


FEED_SID = 'feed.sid'  # <notes>/remote/feed.sid: the runner feed's Claude session id, kept until a real stop
FEED_RESUME_FAIL = 15  # s: a resumed feed failing sooner than this could not resume; the next start is fresh
SID_RE = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')


def feed_session() -> tuple[str, bool]:
    """(session id, resume) for the run's runner feed (B15). The id is kept in <notes>/remote/ from the feed's
    first start until a real stop (`rc_sweep_stop`), so any restart that is not one (an upgrade's, a board
    window replaced or closed, the feed exiting, a crashed run started again) resumes the same Claude session:
    its history and its app entry carry on. None kept yet: a new id, recorded, and a fresh session."""
    f = C.notes(REMOTE_DIR, FEED_SID)
    try:
        sid = f.read_text(encoding='utf-8').strip()
    except OSError:
        sid = ''
    if SID_RE.fullmatch(sid):
        return sid, True
    sid = str(uuid.uuid4())
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(sid + '\n', encoding='utf-8')
    except OSError:
        pass
    return sid, False


def feed_session_args(sid: str, resume: bool) -> list[str]:
    """The agent flags that start the feed's session `sid`, or resume it."""
    return ['--resume', sid] if resume and sid else ['--session-id', sid] if sid else []


def feed_forget_session() -> None:
    """A real stop (or a resume that failed): the next feed starts a fresh session."""
    C.notes(REMOTE_DIR, FEED_SID).unlink(missing_ok=True)


def board_argv(sess: str, root: Path, cmd: str) -> list[str]:
    """Open the board window in the background session `sess`, without taking focus."""
    return ['tmux', 'new-window', '-d', '-t', f'={sess}:', '-n', window('board'), '-c', str(root),
            '-P', '-F', '#{pane_id}', cmd]


FEED_MODEL = 'haiku'  # ponytail: fixed; the feed only echoes lines and runs one command, a knob if that ever falls short


def feed_name() -> str:
    return f'{ROOT.name} · runner'


def feed_on() -> bool:
    """Does a run here keep the runner feed (the board window, on Remote Control), the one watch that pushes what
    needs the person? Control sessions then start no needs-you watch of their own."""
    # ponytail: a run started with --no-tmux has no feed though tmux is here; its control sessions miss the pushes
    return remote_on() and control_ok() and not plat.WINDOWS and shutil.which('tmux') is not None


def feed_argv() -> list[str]:
    """With `[run] remote`: the runner feed, a lean Claude session on Remote Control as "<repo> · runner" that
    posts what lands (Monitor on `since --follow --keep-mark`), runs status/pause/stop/slots, and hands anything
    else to a new control session; the one watch that pushes what needs the person (PushNotification), so
    control sessions start none. Haiku; Bash (only the runner's command, dontAsk refuses the rest), Monitor;
    its own short system prompt instead of Claude Code's, no settings sources or MCP servers: ~6k tokens a turn.
    `board_feed` adds the session flags: one session from the run's first start to a real stop (`feed_session`)."""
    from agent_runner.guide import FEED_ANSWER, RUNNER_BRIEF, RUNNER_START
    cmd = C.command
    cf = P.needs_cfg()  # B27: a reply to an item under Needs you is answered here, with no id, when it may be
    answer = FEED_ANSWER.format(cmd=cmd, needs=cf['heading']) if cf['map_replies'] else ''
    return [plat.exe(C.run['agent']), RUNNER_START.format(cmd=cmd, repo=ROOT.name),
            '--model', FEED_MODEL, '--system-prompt', RUNNER_BRIEF.format(cmd=cmd, repo=ROOT.name, answer=answer),
            '--tools', 'Bash,Monitor,PushNotification', '--permission-mode', 'dontAsk',
            '--allowedTools', f'Bash({cmd} *)', 'Monitor', 'PushNotification', '--strict-mcp-config',
            '--setting-sources', '', '--settings', json.dumps({'autoMemoryEnabled': False}),  # ~6k tokens a turn
            '--remote-control', feed_name()]


def board_command() -> str:
    """What the board window runs: the runner feed with `[run] remote` (in the apps too), else the free text feed;
    either one ends once this run's process has (B13)."""
    return plat.command_text([*runner_cmd(), 'since', '--board', *(['--feed'] if feed_on() else []),
                              '--run-pid', str(os.getpid())])


def keep_board(sess: str) -> None:
    """Keep the board window up in the background session while the run is: opened again when it is closed or
    its feed exits. It ends with the run (its `--run-pid`), and the next run opens its own."""
    cmd = board_command()
    kind = ('feed' if ' --feed' in cmd else 'text') + '/run'
    said = False
    while True:
        rows = tmux('list-panes', '-s', '-t', f'={sess}', '-F',
                    f'#{{session_name}}\t#{{pane_id}}\t#{{{TAG}}}\t#{{{REPO_TAG}}}\t#{{{RUN_TAG}}}')
        hit = attach_target(rows.stdout.splitlines(), ROOT, 'board') if rows.returncode == 0 else ('', '')
        if hit and hit[1] and tmux('show-options', '-p', '-v', '-t', hit[1], BOARD_TAG).stdout.strip() != kind:
            tmux('kill-pane', '-t', hit[1])  # an earlier run's other kind (remote turned on or off): this run's instead
            hit = None
        if not hit and not RC_ENDING[0]:  # found by tag, not name: a rename keeps it; none once the run ends
            r = sp.run(board_argv(sess, ROOT, cmd), capture_output=True, text=True)
            if pane := r.stdout.strip():  # `attach board` finds it by these
                tmux('set-option', '-p', '-t', pane, TAG, 'board')
                tmux('set-option', '-p', '-t', pane, REPO_TAG, str(ROOT))
                tmux('set-option', '-p', '-t', pane, BOARD_TAG, kind)
            if not said or r.returncode:
                what = f'the runner feed, "{feed_name()}" in the apps too' if kind.startswith('feed') else 'the text feed'
                log(f'board: window {window("board")} is up with {what} ({RUNNER} attach board)' if not r.returncode
                    else f'board: tmux could not open it: {r.stderr.strip()}')
            said = True
        time.sleep(BOARD_EVERY)


def start_board() -> None:
    """The board window, in the tmux session the run is in (the background one, or yours): with `[run] remote`
    it is the runner feed, which must be there however the run was started."""
    here = os.environ.get('TMUX_PANE', '')
    if not (isinstance(MUX, TmuxMux) and here):
        return
    if sess := tmux('display-message', '-p', '-t', here, '#{session_name}').stdout.strip():
        threading.Thread(target=keep_board, args=(sess,), name='board', daemon=True).start()


CONTROL_LINK_WAIT = 90  # s `control --new` watches the new pane for its claude.ai/code link
SESSION_LINK = re.compile(r'https://claude\.ai/code/session_[A-Za-z0-9_-]+')


def control_new_session() -> str:
    """The tmux session `control --new` opens its window in: the one this pane is in (a control session beside
    the run), else the run's background session while it is up; '' when there is none."""
    if here := os.environ.get('TMUX_PANE', ''):
        r = tmux('display-message', '-p', '-t', here, '#{session_name}')
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    sess = background_session()
    return sess if tmux('has-session', '-t', f'={sess}').returncode == 0 else ''


def feed_files() -> list[str]:
    return feed_scan()[0]


def feed_scan() -> tuple[list[str], int, str]:
    """(`feed_files`, images the message shows that no saved path came for, its Claude Code version). The middle
    one is the drift check: when Claude Code changes how it records an image's path again, the new control
    session is told so (`image_drift_note`) instead of the pictures vanishing without a word.

    The files and images attached to the person's latest message in the runner feed, the one being handed on, in
    display order: Claude Code records their saved paths in the feed's transcript (an `inlined_image_paths`
    attachment after the message, since 2.1.329 an isMeta entry with '[Image: source: PATH]' text, B24, and for any
    other file, saved to ~/.claude/uploads/<sid>/<id>-<name> and @-mentioned, an attachment of type file with that
    path as filename, B30). `control --new --ask` passes them on itself, so a feed on an older brief, or a Haiku
    that drops or mangles the @-mention, still forwards them, and a later text-only message forwards none. File
    attachments after a compaction summary are Claude Code re-reading files, not the person attaching them, so
    they are left out. The session is the one running this command (Claude Code's CLAUDE_CODE_SESSION_ID: the
    feed handing the message on), else <notes>/remote/feed.sid (a feed started by an older runner never wrote that
    file, B22)."""
    return feed_latest()[:3]


def feed_latest() -> tuple[list[str], int, str, str | None]:
    """`feed_scan`, plus the text of that latest person message (None: no feed transcript to read), so
    `control_new` can tell whether Claude Code has written the message being handed on yet (B46)."""
    sid = os.environ.get('CLAUDE_CODE_SESSION_ID', '').strip()
    if not SID_RE.fullmatch(sid):
        try:
            sid = C.notes(REMOTE_DIR, FEED_SID).read_text(encoding='utf-8').strip()
        except OSError:
            return [], 0, '', None
    t = transcript(sid) if SID_RE.fullmatch(sid) else None
    if not t:
        return [], 0, '', None
    paths: list[str] = []
    rereads = False
    shown = found = 0  # images in the latest message; image paths recorded for it (B24's two forms count twice)
    version = said = ''
    try:
        with open(t, encoding='utf-8') as f:
            for line in f:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                att = d.get('attachment') or {}
                if att.get('type') == 'inlined_image_paths':
                    got = [p for p in att.get('paths', []) if isinstance(p, str)]
                    found += len(got)
                    paths += [p for p in got if p not in paths]
                elif att.get('type') == 'file':
                    p = att.get('filename')
                    if not rereads and isinstance(p, str) and p and p not in paths:
                        paths.append(p)
                elif d.get('type') == 'user' and d.get('isCompactSummary'):
                    rereads = True
                elif d.get('type') == 'user' and d.get('isMeta'):
                    got = meta_image_paths(d)
                    found += len(got)
                    paths += [p for p in got if p not in paths]
                elif d.get('type') == 'user' and person_message(d):
                    paths, rereads, found = [], False, 0
                    c = (d.get('message') or {}).get('content')
                    shown = sum(isinstance(x, dict) and x.get('type') == 'image' for x in c) if isinstance(c, list) else 0
                    version = str(d.get('version') or '')
                    said = c if isinstance(c, str) else ' '.join(
                        x.get('text', '') for x in c if isinstance(x, dict) and x.get('type') == 'text') \
                        if isinstance(c, list) else ''
    except OSError:
        return [], 0, '', None
    return paths, max(shown - found, 0), version, said


FEED_WAIT = 5.0  # s control --new --ask waits for the feed's transcript to hold the message it hands on (B46)


def same_words(said: str, ask: str) -> bool:
    """The feed hands the person's message on word for word, give or take quoting and spacing: compare letters
    and digits only, either one holding the other."""
    a, b = (re.sub(r'\W+', '', x).lower() for x in (said, ask))
    return bool(a and b) and (a in b or b in a)


def image_drift_note(lost: int, version: str) -> str:
    """Added to a handed-on ask when `lost` attached images came with no saved path (`feed_scan`)."""
    if not lost:
        return ''
    return (f'The person attached {lost} image(s) that could not be passed on: Claude Code '
            f'{version or "(this version)"} no longer records where it saves them in a way agent-runner reads. '
            'Ask them to send the picture(s) here again, and tell them agent-runner needs a fix for this '
            "Claude Code change (its runner feed reads the saved paths from the feed's transcript).")





feed_images = feed_files  # the name before B30


IMAGE_SOURCE_RE = re.compile(r'\[Image: source: ([^\]\n]+?)\]')


def meta_image_paths(d: dict) -> list[str]:
    """The image paths in a Claude Code isMeta companion entry: 2.1.329 records a phone/remote image as
    '[Image: source: /tmp/claude-<uid>/<proj>/<sid>/images/1.png]' text, with no inlined_image_paths attachment (B24)."""
    c = (d.get('message') or {}).get('content')
    texts = [c] if isinstance(c, str) else [x.get('text', '') for x in c or [] if isinstance(x, dict)] \
        if isinstance(c, list) else []
    return [m.strip() for t in texts if isinstance(t, str) for m in IMAGE_SOURCE_RE.findall(t)]


def person_message(d: dict) -> bool:
    """A transcript entry the person typed (not a tool result or a task notification)."""
    if (d.get('origin') or {}).get('kind', 'human') != 'human':
        return False
    c = (d.get('message') or {}).get('content')
    if isinstance(c, str):
        return not c.startswith('<task-notification>')
    return isinstance(c, list) and any(isinstance(x, dict) and x.get('type') in ('text', 'image') for x in c)


def control_new(n: int | None = None, wait: float = CONTROL_LINK_WAIT, ask: str = '',
                images: list[str] | tuple = ()) -> int:
    """`control --new`: another control session, opened without taking focus (a window of its own in the run's
    tmux session; Windows: a hidden console), on Remote Control as "<repo> · control N" with `[run] remote`.
    Prints its claude.ai/code link once its pane shows it, so the session that ran it can answer with a link."""
    n = n or control_number()
    if pid := control_live(n):
        print(f'control {n} already runs (pid {pid})', file=sys.stderr)
        return 1
    images = [str(Path(i).resolve()) for i in images]
    if ask:
        # Claude Code writes the feed's transcript lazily: the message being handed on, and the saved paths of
        # its pictures, can land a moment after this command starts (B46), so wait briefly for them.
        deadline = time.monotonic() + FEED_WAIT
        while True:
            got, lost, version, said = feed_latest()
            if said is None or (same_words(said, ask) and not lost) or time.monotonic() >= deadline:
                break
            time.sleep(0.2)
        images += [i for i in got if i not in images]
        if note := image_drift_note(lost, version):
            ask = f'{ask}\n\n{note}'
    cmd = [*runner_cmd(), 'control', str(n), *(['--ask', ask] if ask else []),
           *[x for i in images for x in ('--file', i)]]
    name = control_name(n, ask, images)
    if plat.WINDOWS:
        plat.spawn_console(cmd, ROOT, control_env(), hidden=True)
        print(f'control {n} is up in a hidden console' +
              (f': "{name}" at {REMOTE_URL}' if remote_on() else f' ({RUNNER} attach c{n} shows it)'))
        return 0
    if not shutil.which('tmux') or not (sess := control_new_session()):
        print(f'no tmux session to open it in (no run is up): start a run with {RUNNER}, or run {RUNNER} control '
              f'in a terminal', file=sys.stderr)
        return 1
    env = [e for e in background_env() if not e.startswith(('AGENT_RUNNER=', 'AGENT_RUNNER_SLOT=', 'AGENT_RUNNER_KEEP='))]
    envs = [x for e in env for x in ('-e', e)]
    win = name if control_title(ask, images) else window(f'control{n}')
    r = tmux('new-window', '-d', '-t', f'={sess}:', '-n', win, '-c', str(ROOT), *envs, '-P', '-F', '#{pane_id}',
             plat.command_text(cmd))
    if r.returncode or not (pane := r.stdout.strip()):
        print(f'tmux could not open control {n}: {r.stderr.strip()}', file=sys.stderr)
        return 1
    tmux('set-option', '-p', '-t', pane, TAG, f'c{n}')
    tmux('set-option', '-p', '-t', pane, REPO_TAG, str(ROOT))
    where = f'window {win} of tmux session {sess} ({RUNNER} attach c{n} goes there)'
    if not remote_on():
        why = remote_off_why() if C.run['remote'] == 'auto' else ''
        print(f'control {n} is up in {where}; it is local' +
              (f' ({why})' if why else ': [run] remote = true puts control sessions on claude.ai/code'))
        return 0
    deadline = time.monotonic() + wait
    while True:
        shown = tmux('capture-pane', '-p', '-J', '-t', pane, '-S', '-200')
        if m := SESSION_LINK.search(shown.stdout or ''):
            print(f'control {n} is up: {m.group(0)}\n("{name}", in {where})')
            return 0
        if shown.returncode or time.monotonic() >= deadline:
            break
        time.sleep(1)
    print(f'control {n} is up in {where}, but showed no link in {wait:g} s: find "{name}" at {REMOTE_URL}')
    return 0


# --- B26: idle control sessions are closed, so the apps' session list stops piling up ----------------------
#
# Every CONTROL_CLOSE_EVERY s the run reads the transcript of each live control session N (not c1, the kept
# one) and closes it (ends its process, removes controlN.pid; the transcript stays, resumable) when Claude
# spoke last, nothing runs in it, and it has been quiet `[run] control_idle`; or, when its last message is an
# open question or offer (`[run] control_open`), quiet `[run] control_ask_idle`: then the question is filed
# under Needs you as a DECIDE item first (`[run] control_file_asks`). `[run] control_close = false` turns it off.

CONTROL_CLOSE_EVERY = 300  # s between looks
CONTROL_CLOSE_AT = [0.0]
CONTROL_WATCH_CMD = 'since --follow --needs-you'  # a control session's standing watch: not work in progress
TASK_STARTED = re.compile(r'Monitor started \(task (\w+)|running in background with ID: (\w+)')
TASK_ENDED = re.compile(r'<task-id>(\w+)</task-id>|\(task (\w+)\)')
EXPIRES = re.compile(r'expires in (\d+)\s*([smh])')
DURATION = re.compile(r'^\s*(\d+(?:\.\d+)?)\s*([smhd]?)\s*$')


def duration(v, default: float = 0.0) -> float:
    """A config time in seconds: a number (seconds) or '90s', '30m', '1h', '2d'; false/0: 0 (off)."""
    if v is True or v is None:
        return default
    if v is False:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    m = DURATION.match(str(v).lower())
    if not m:
        return default
    return float(m[1]) * {'': 1, 's': 1, 'm': 60, 'h': 3600, 'd': 86400}[m[2]]


def _stamp(d: dict) -> float | None:
    try:
        return dt.datetime.fromisoformat(str(d['timestamp']).replace('Z', '+00:00')).timestamp()
    except (KeyError, ValueError, TypeError):
        return None


def _texts(d: dict) -> list[str]:
    """Every piece of text in a transcript entry: its message's text items and tool results, a queued
    notification's content."""
    out = [d['content']] if isinstance(d.get('content'), str) else []
    c = (d.get('message') or {}).get('content')
    if isinstance(c, str):
        return out + [c]
    for x in c if isinstance(c, list) else ():
        if not isinstance(x, dict):
            continue
        if isinstance(x.get('text'), str):
            out.append(x['text'])
        r = x.get('content')
        if isinstance(r, str):
            out.append(r)
        elif isinstance(r, list):
            out += [y['text'] for y in r if isinstance(y, dict) and isinstance(y.get('text'), str)]
    return out


def control_state(rows) -> dict:
    """What a control session's transcript entries `rows` say: {'last': 'person' | 'claude' | 'tool' | '',
    'text': Claude's last message when it spoke last, 'at': when it was last active (epoch s, 0 unknown),
    'running': ids of background tasks and Monitors still live, 'bridge': its Remote Control session id or '',
    'title': the latest name the person gave it in the apps (a custom-title entry, B41) or ''}.
    Activity is a person's message or a turn of Claude's; the standing needs-you watch (CONTROL_WATCH_CMD)
    being re-armed is neither activity nor work in progress, and the events it brings are not activity."""
    st = {'last': '', 'text': '', 'at': 0.0, 'running': set(), 'bridge': '', 'title': ''}
    uses: dict[str, dict] = {}  # tool_use id -> its tool call
    expiry: dict[str, float] = {}  # task id -> when a Monitor with a timeout ends on its own
    for d in rows:
        if not isinstance(d, dict):
            continue
        kind, at = d.get('type'), _stamp(d)
        if kind == 'bridge-session' and isinstance(d.get('bridgeSessionId'), str):
            st['bridge'] = d['bridgeSessionId']
            continue
        if kind == 'custom-title':
            st['title'] = str(d.get('customTitle') or '').strip()
            continue
        texts = _texts(d)
        if any('<status>' in t for t in texts) or any('<task-notification>' in t and 'expired' in t.lower()
                                                      for t in texts):
            for t in texts:
                for m in TASK_ENDED.finditer(t):
                    st['running'].discard(m[1] or m[2])
        if kind == 'assistant':
            items = [x for x in (d.get('message') or {}).get('content') or [] if isinstance(x, dict)]
            said = '\n'.join(x['text'] for x in items if x.get('type') == 'text' and isinstance(x.get('text'), str)
                             and x['text'].strip())
            calls = [x for x in items if x.get('type') == 'tool_use']
            work = False
            for x in calls:
                uses[str(x.get('id'))] = x
                inp = x.get('input') or {}
                if x.get('name') in ('TaskStop', 'KillShell', 'KillBash'):
                    st['running'].discard(str(inp.get('task_id') or inp.get('shell_id') or ''))
                if not (x.get('name') == 'Monitor' and CONTROL_WATCH_CMD in str(inp.get('command', ''))):
                    work = True
            if said:
                st['last'], st['text'] = 'claude', said
            elif work:
                st['last'], st['text'] = 'tool', ''
            if (said or work) and at:
                st['at'] = max(st['at'], at)
        elif kind == 'user':
            c = (d.get('message') or {}).get('content')
            for x in c if isinstance(c, list) else ():
                if not (isinstance(x, dict) and x.get('type') == 'tool_result'):
                    continue
                call = uses.get(str(x.get('tool_use_id')), {})
                if call.get('name') == 'Monitor' and CONTROL_WATCH_CMD in str((call.get('input') or {}).get('command', '')):
                    continue
                for t in _texts({'message': {'content': [x]}}):
                    if m := TASK_STARTED.search(t):
                        tid = m[1] or m[2]
                        persistent = (call.get('input') or {}).get('persistent')
                        if (e := EXPIRES.search(t)) and at and not persistent:
                            expiry[tid] = at + int(e[1]) * {'s': 1, 'm': 60, 'h': 3600}[e[2]]
                        st['running'].add(tid)
            if person_message(d):
                st['last'], st['text'] = 'person', ''
                if at:
                    st['at'] = max(st['at'], at)
    now = time.time()
    st['running'] = {t for t in st['running'] if not (t in expiry and expiry[t] <= now)}
    return st


def control_cfg() -> dict:
    """`[run] control_close`, `control_idle`, `control_ask_idle` (seconds), `control_open` (lowercase),
    `control_file_asks`, `control_ask_kind`."""
    r = C.run
    opens = r.get('control_open', ['?', 'want me to', 'should i'])
    return {'close': r.get('control_close', True) is not False,
            'idle': duration(r.get('control_idle', '1h'), 3600.0),
            'ask_idle': duration(r.get('control_ask_idle', '2h'), 7200.0),
            'open': [str(p).lower() for p in ([opens] if isinstance(opens, str) else opens or [])],
            'file_asks': r.get('control_file_asks', True) is not False,
            'kind': str(r.get('control_ask_kind', 'F') or 'F')}


def open_question(text: str, phrases: list[str]) -> str:
    """The open question or offer Claude's last message `text` ends on, as one line ('' for none): its last
    paragraph, when that ends in a phrase that is only punctuation ('?') or holds any other (`want me to`),
    narrowed to the last sentence that does."""
    paras = [p for p in re.split(r'\n\s*\n', text.strip()) if p.strip()]
    if not paras:
        return ''
    last = ' '.join(paras[-1].split())
    bare = last.rstrip(' *_`"\')]')

    def hit(s: str) -> bool:
        s2, low = s.rstrip(' *_`"\')]'), s.lower()
        return any(s2.endswith(p) if not re.search(r'\w', p) else p in low for p in phrases if p)
    if not hit(bare) and not hit(last):
        return ''
    sentences = [s for s in re.split(r'(?<=[.!?])\s+', last) if s.strip()]
    q = next((s for s in reversed(sentences) if hit(s)), last).strip(' *_')
    return q if len(q) <= 240 else q[:239].rsplit(' ', 1)[0] + '…'


def control_renamed(st: dict, n: int = 0) -> bool:
    """B41: whether the person renamed control session `n` (state `st`): its custom title is set and is not a
    name the runner gives it (`control_name`, with or without an ask's title; the runner's own name writes no
    custom-title entry, so with `n` 0 any custom title counts)."""
    t = st.get('title') or ''
    return bool(t) and not (n and (t == control_name(n) or t.startswith(f'{ROOT.name} · {n} · ')))


def control_verdict(st: dict, cf: dict, now: float, n: int = 0) -> tuple[str, str]:
    """('close' | 'ask' | 'keep', why or the question) for control session `n`'s state `st` (`control_state`).
    One the person renamed is kept (B41): they named it to keep it."""
    if control_renamed(st, n):
        return 'keep', 'renamed by the person'
    if st['last'] != 'claude':
        return 'keep', {'person': 'the person spoke last', 'tool': 'a turn is under way'}.get(st['last'], 'no turn yet')
    if st['running']:
        return 'keep', f'{len(st["running"])} background task(s) still running'
    quiet = now - st['at'] if st['at'] else 0
    if q := open_question(st['text'], cf['open']):
        if cf['ask_idle'] and quiet >= cf['ask_idle']:
            return 'ask', q
        return 'keep', 'its open question is not old enough'
    if cf['idle'] and quiet >= cf['idle']:
        return 'close', f'idle {int(quiet // 60)} min'
    return 'keep', 'active lately'


def control_link(bridge: str) -> str:
    """A Remote Control session id (cse_…) as its claude.ai/code link; '' for none."""
    return f'{REMOTE_URL}/session_{bridge[4:]}' if bridge.startswith('cse_') else ''


def control_live_numbers() -> list[int]:
    """The numbers of the control sessions with a pid file and a live process, c1 left out."""
    out = []
    for f in C.notes().glob('control*.pid'):
        if (m := re.fullmatch(r'control(\d+)\.pid', f.name)) and int(m[1]) > 1 and control_live(int(m[1])):
            out.append(int(m[1]))
    return sorted(out)


def file_control_ask(n: int, sid: str, q: str, link: str, branch: str = '') -> str:
    """File control session `n`'s open question under Needs you: a task blocked `DECIDE: <q> <link>`, committed
    as `watch_ci` commits its tasks (MERGE free, TODO.md clean). Its id, or '' when it could not be filed now."""
    if not MERGE.acquire(blocking=False):
        return ''
    hold = ExitStack()
    try:
        if C.plan_external:
            hold.enter_context(plansync.locked(C))
            plansync.pull(C, force=True)
        rel = plan_rel('TODO.md')
        if not C.plan_external and (git('status', '--porcelain', '--', rel).stdout.strip() or branch and
                                    git('branch', '--show-current').stdout.strip() != branch):
            return ''  # somebody mid-edit, or the main checkout on another branch: the next look files it
        where = link or f'resume it with `{plat.exe(C.run["agent"])} --resume {sid}`'
        tid = P.add(control_cfg()['kind'], f'Control session {n} asked the person: "{q}" Carry on from their '
                    f'answer (the session, closed while it waited: {where})', todo=ROOT / rel, pri='normal')
        P.block(tid, f'DECIDE: {q} {link}'.strip(), todo=ROOT / rel, after=[])
        if not commit_plan(f'Plan: {tid}, control {n} asked the person', rel):
            if not C.plan_external:
                git('checkout', '-q', '--', rel)
            return ''
        return tid
    finally:
        hold.close()
        MERGE.release()


def close_controls(branch: str = '', force: bool = False, now: float | None = None) -> list[tuple[int, str, str]]:
    """B26: close the idle control sessions (see above), every CONTROL_CLOSE_EVERY s from the run loop.
    [(n, 'closed' | 'asked', why or the task id filed)] for those closed."""
    cf = control_cfg()
    if not cf['close'] or not control_ok() or (not force and time.time() - CONTROL_CLOSE_AT[0] < CONTROL_CLOSE_EVERY):
        return []
    CONTROL_CLOSE_AT[0] = time.time()
    now = time.time() if now is None else now
    out = []
    for n in control_live_numbers():
        pidf = C.notes(f'control{n}.pid')
        try:
            pid_s, _, sid = pidf.read_text(encoding='utf-8').strip().partition(' ')
            pid = int(pid_s)
        except (OSError, ValueError):
            continue
        if not sid or not transcript(sid):
            continue
        st = control_state(entries(sid, skip_bad=True))
        verdict, why = control_verdict(st, cf, now, n)
        if verdict == 'keep':
            continue
        link = control_link(st['bridge'])
        if verdict == 'ask' and cf['file_asks']:
            if not (tid := file_control_ask(n, sid, why, link, branch)):
                continue  # TODO.md busy: the next look files it
            log(f'{tid}: filed, control {n} asked "{why}" (DECIDE, under {P.needs_cfg()["heading"]})')
            note(f'{tid}: filed, an open question of control {n}')
            why = tid
        plat.terminate(pid)
        pidf.unlink(missing_ok=True)
        log(f'control {n}: closed, ' + (f'its question filed as {why}' if verdict == 'ask' and cf['file_asks']
                                        else why) + f' (transcript kept: {plat.exe(C.run["agent"])} --resume {sid})')
        out.append((n, 'asked' if verdict == 'ask' else 'closed', why))
    return out


def control_server_argv() -> list[str]:
    """With `[run] remote`: Claude Code's Remote Control server in the main checkout, so new control sessions can
    be started from claude.ai/code and the Claude apps, each with the control settings (its brief)."""
    exe = plat.exe(C.run['agent'])
    return [exe, 'remote-control', '--spawn', 'same-dir', '--name', f'{ROOT.name} · control',
            '--permission-mode', 'bypassPermissions',
            *(['--settings', str(control_settings())] if server_takes_settings(exe) else [])]


_SERVER_SETTINGS: dict[str, bool] = {}


def server_takes_settings(exe: str) -> bool:
    """Whether this agent's `remote-control` takes `--settings` (asked of its --help once a run): an older Claude
    Code exits at once on it, which would crash-loop the control server. An agent whose help cannot be read
    (missing, hangs, prints nothing) is taken to have it, as before."""
    if exe not in _SERVER_SETTINGS:
        try:
            r = sp.run([exe, 'remote-control', '--help'], stdin=sp.DEVNULL, capture_output=True, text=True,
                       errors='replace', timeout=30)
            said = (r.stdout or '') + (r.stderr or '')
            _SERVER_SETTINGS[exe] = '--settings' in said or not said.strip()
        except (OSError, sp.SubprocessError):
            _SERVER_SETTINGS[exe] = True
    return _SERVER_SETTINGS[exe]


def server_last_error(err: Path, since: int) -> str:
    """The last non-blank line the control server wrote to stderr (`err`) after offset `since`, cut to 200."""
    try:
        with open(err, 'rb') as fh:
            fh.seek(since)
            lines = fh.read().decode('utf-8', errors='replace').splitlines()
    except OSError:
        return ''
    lines = [re.sub(r'\x1b\[[0-9;?]*[A-Za-z]', '', x).strip() for x in lines]
    return next((x[:200] for x in reversed(lines) if x), '')


def control_server_live() -> int:
    """The pid of the control server a run started (`<notes>/control-server.pid`), still up, or 0."""
    pid = marker_pid(C.notes('control-server.pid'))
    args = plat.cmdline(pid) if pid and alive(pid) else None
    return pid if pid and alive(pid) and (args is None or 'remote-control' in args) else 0


def keep_control_server() -> None:
    """Keep the control server running while the run is up: restarted when it exits (Remote Control quits after
    about 10 minutes offline), after 30 s, doubling to 10 minutes while it keeps failing at once. One a run
    before an upgrade restart left is adopted; the run's end ends it."""
    import atexit
    pidf, out, err = C.notes('control-server.pid'), C.notes('control-server.log'), C.notes('control-server.err')
    atexit.register(lambda: (pid := control_server_live()) and plat.terminate(pid))
    backend().trust(ROOT)  # it asks to trust a new folder, and has no terminal to ask on
    if '--settings' not in control_server_argv():
        log('control: this Claude Code\'s `remote-control` has no --settings, so the control server starts without '
            'it: sessions started from claude.ai/code will not get the control brief. Update Claude Code '
            '(`claude update`) to give them it')
    wait = CONTROL_SERVER_WAIT[0] // 2  # doubled at the first exit
    if (pid := control_server_live()) and server_stale(plat.cmdline(pid)):
        log(f'control: the control server an earlier run left (pid {pid}) has other flags; restarting it')
        plat.terminate(pid)
    while True:
        proc = None
        if not (pid := control_server_live()):
            since = out.stat().st_size if out.exists() else 0
            err_since = err.stat().st_size if err.exists() else 0
            env = control_env()
            if silent() is not False:  # silent while it starts (silent = true: for good)
                env[PRESENCE_ENV] = str(quiet_file('server'))
            with open(out, 'ab') as fh, open(err, 'ab') as eh:
                try:
                    proc = sp.Popen(control_server_argv(), cwd=str(ROOT), env=env, stdin=sp.DEVNULL,
                                    stdout=fh, stderr=eh, start_new_session=not plat.WINDOWS)
                except OSError as e:
                    quiet_file('server', on=False)
                    log(f'control: the control server did not start: {e}')
                    return
            if silent() == 'launch':
                threading.Thread(target=unquiet_when_up, args=('server',), kwargs={'log_file': out, 'since': since},
                                 daemon=True).start()
            pid = proc.pid
            pidf.write_text(str(pid), encoding='utf-8')
            rc_record('server', f'{ROOT.name} · control', pid, os.getpid())  # B12
            log(f'control: control server up as "{ROOT.name} · control" at {REMOTE_URL} (pid {pid})')
        else:  # adopted from an earlier run: this run's now (B12: the start's sweep leaves it to us)
            rc_record('server', f'{ROOT.name} · control', pid, os.getpid())
        began = time.monotonic()
        while (proc.poll() is None) if proc else alive(pid):
            time.sleep(1 if time.monotonic() - began < 30 else 10)
        rc_forget(C.notes(REMOTE_DIR) / f'server-{pid}.json')
        lasted = time.monotonic() - began
        wait = CONTROL_SERVER_WAIT[0] if lasted > 600 else min(wait * 2, CONTROL_SERVER_WAIT[1])
        said = server_last_error(err, err_since) if proc and lasted < 60 else ''
        if said:  # it quit at once: its error says why (an unknown option, a login)
            said = f'after {lasted:.0f} s: {said}'
        else:
            try:
                said = out.read_text(encoding='utf-8', errors='replace').strip().splitlines()[-1][:200]
            except (OSError, IndexError):
                said = ''
        log(f'control: the control server exited{f" ({said})" if said else ""}; restarting it in {wait} s')
        time.sleep(wait)


def server_stale(args: list[str] | None) -> bool:
    """A running control server's argv (None: unreadable, so kept) started with other flags than this run's:
    `--settings` is read once, and the flags apply to every session it starts, so an adopted one must match."""
    return args is not None and [a for a in args if a][1:] != control_server_argv()[1:]


def start_control_server() -> None:
    if remote_on() and C.run['control'] and control_ok():
        threading.Thread(target=keep_control_server, name='control-server', daemon=True).start()


# --- Remote Control sessions a run started (B12) ---------------------------------
# Claude Code offers no command to end or archive a Remote Control session from outside it, and none to list
# them; it archives its own entry in claude.ai/code and the apps when it exits on SIGTERM, SIGHUP or SIGINT
# (its teardown: "archiving session", "environment deregistered"). An entry stays listed only when its
# process dies without that teardown: SIGKILL, a crash, a reboot, or a power-off right after a stop. So the
# run records each Remote Control process it starts, ends them with SIGTERM and waits for the teardown (on a
# stop, and at the next start for those an earlier run left), and never SIGKILLs one.

REMOTE_DIR = 'remote'  # <notes>/remote/<kind>-<pid>.json: a Remote Control process a run started
RC_TEARDOWN = 20  # s a Remote Control process gets after SIGTERM to archive its entry and exit
RC_RUN_KINDS = ('feed', 'server')  # what a run starts for itself; control sessions are the person's, left up
RC_ENDING = [False]  # set by the stop's sweep: keep_board opens no new feed while the run ends


def run_key(pid: int) -> str:
    """One run's identity: its pid and start time (after it ends, its pid can be anyone's)."""
    return f'{pid}:{plat.started(pid) or ""}'


def rc_record(kind: str, name: str, pid: int, run_pid: int, sid: str = '') -> Path:
    """Record Remote Control process `pid` ("<name>" in the apps), started for the run `run_pid`."""
    d = C.notes(REMOTE_DIR)
    d.mkdir(parents=True, exist_ok=True)
    f = d / f'{kind}-{pid}.json'
    rec = {'kind': kind, 'name': name, 'pid': pid, 'run': run_key(run_pid), 'sid': sid}
    if (start := plat.started(pid)) is not None:
        rec['start'] = start
    f.write_text(json.dumps(rec), encoding='utf-8')
    return f


def rc_records() -> list[dict]:
    """The recorded Remote Control processes, each with its file as 'rec'."""
    d = C.notes(REMOTE_DIR)
    out = []
    for f in sorted(d.glob('*.json')) if d.is_dir() else []:
        try:
            out.append({**json.loads(f.read_text(encoding='utf-8')), 'rec': str(f)})
        except (OSError, ValueError):
            f.unlink(missing_ok=True)
    return out


def rc_forget(rec: dict | Path | None, killed: bool = False) -> None:
    """Drop a record whose process ended (its teardown archived its entry); `killed` (SIGKILL: no teardown)
    keeps it, marked, for the next start to name as possibly still listed."""
    if not rec:
        return
    f = Path(rec['rec'] if isinstance(rec, dict) else rec)
    if not killed:
        f.unlink(missing_ok=True)
        return
    try:
        f.write_text(json.dumps({**json.loads(f.read_text(encoding='utf-8')), 'killed': True}), encoding='utf-8')
    except (OSError, ValueError):
        pass


def rc_sweep(run_pid: int, stopping: bool = False, wait: float = RC_TEARDOWN,
             keep_server: bool = False) -> tuple[list[str], list[str]]:
    """End the Remote Control processes the run owns, so the apps list only live sessions: on a run's start,
    those an earlier run left (its feed, its control server unless `keep_server`: this run adopts it, so no new
    entry); with `stopping`, this run's own as well. Each gets SIGTERM and up to `wait` s for its teardown,
    which archives its entry; one still up then is left (the next start tries again), never SIGKILLed.
    Control sessions are the person's and stay up, and nothing the run did not record (a session the person
    started) is touched. A record whose process is gone is dropped, named in run.log when it died killed
    (no teardown: its entry may still be listed). Returns (names ended, names left running)."""
    mine = run_key(run_pid)
    ending = []
    for s in rc_records():
        if not gate_alive(s):
            if s.get('killed'):
                log(f'remote: "{s.get("name")}" was killed before it could archive itself; if it is still listed '
                    f'at {REMOTE_URL}, archive it there')
            rc_forget(s)
        elif s.get('kind') not in RC_RUN_KINDS or s.get('run') == mine and not stopping:
            continue  # a control session, or this run's own while it runs
        elif s.get('kind') == 'server' and keep_server and s.get('run') != mine:
            continue  # keep_control_server adopts it (or restarts it when its flags differ)
        else:
            ending.append(s)
    for s in ending:
        plat.terminate(s['pid'])
    end = time.monotonic() + wait
    while (up := [s for s in ending if gate_alive(s)]) and time.monotonic() < end:
        time.sleep(0.25)
    gone = [s for s in ending if s not in up]
    for s in gone:
        rc_forget(s)
    if gone:
        names = ', '.join(f'"{s["name"]}"' for s in gone)
        log(f'remote: ended {names} '
            f'({"this run" if stopping else "left by an earlier run"}); their entries are archived')
    for s in up:
        log(f'remote: "{s["name"]}" (pid {s["pid"]}) did not end within {wait:g} s of SIGTERM; left running, '
            f'the next start ends it')
    return [s['name'] for s in gone], [s['name'] for s in up]


def rc_sweep_start() -> None:
    """The run's start: end what an earlier run left on Remote Control, in the background (it can wait)."""
    keep = remote_on() and bool(C.run['control']) and control_ok()
    threading.Thread(target=rc_sweep, args=(os.getpid(),), kwargs={'keep_server': keep},
                     name='remote-sweep', daemon=True).start()


def rc_sweep_stop() -> None:
    """The run's stop: end its feed and control server now and wait for their teardown, so their entries are
    archived before the run exits (and before a suspend or power-off)."""
    RC_ENDING[0] = True
    feed_forget_session()  # B15: a real stop ends the feed's session; any other restart resumes it
    rc_sweep(os.getpid(), stopping=True)
