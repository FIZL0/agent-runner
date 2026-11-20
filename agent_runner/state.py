"""The run's shared state and small helpers: the repository it works on (`init`), the log, git, the plan file
and the stop request. Every other runner module imports from here; this one imports none of them."""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import subprocess as sp
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from agent_runner import gitops, plan as P, plansync, plat
from agent_runner.config import Config, cfg, main_checkout
from agent_runner.gitops import _net, shared_name


TASK = re.compile(r'^- \[(.)\] \*\*([^*\s]+)\*\*(.*)')  # a top-level task line: its box, its id, the rest
TAG = '@runner'  # the tmux pane option a slot's pane is found by
RUN_TAG = '@runner-run'  # set on the runner's own pane to the main checkout it runs for: `attach` goes there
HIDDEN = [False]  # `run --hidden` on Windows: slot consoles start hidden (the background run)
REPO_TAG = '@runner-repo'  # the main checkout a pane's runner works for: two repos' runners share a tmux session
BOARD_TAG = '@runner-board'  # on the board's pane: "feed/run" (the runner feed) or "text/run" (since --board);
# "/run": it ends with the run (B13), so a board of an earlier version (plain "feed"/"text") is replaced

ROOT = Path('.')       # the main checkout; set by `init`
SLOTS_DIR = Path('.')  # `[run] home` (~/runs/<repo>/): s1, s2, …, and `merge`
C: Config = None  # type: ignore[assignment]  # its config; set by `init` (C3: a name the other modules import)
C: Config


# C3: the modules runner.py was split into. Each imports the settings above by name (`from agent_runner.state
# import ROOT`), so a module-level setting one of them changes (ROOT, SLOTS, POWER, MUX, …) goes to all through
# `share`; runner.py sends its own attribute writes (a test's stand-in, a wrapping project's PROMPT) the same way.
FAMILY = ('runner', 'state', 'brief', 'sched', 'slots', 'watch', 'join', 'land', 'merge', 'control', 'status',
          'feed', 'loop', 'cmds')


def share(**values) -> None:
    """Set each module-level name in every runner module that holds it."""
    for m in FAMILY:
        if (mod := sys.modules.get(f'agent_runner.{m}')) is not None:
            space = vars(mod)
            for k, v in values.items():
                if k in space:
                    space[k] = v


def init(root=None) -> Config:
    """Point the runner at the repository around `root` (default: the current directory)."""
    global ROOT, SLOTS_DIR, C
    ROOT = main_checkout(root)
    C = cfg(ROOT)
    SLOTS_DIR = C.slots_dir
    share(ROOT=ROOT, C=C, SLOTS_DIR=SLOTS_DIR)
    if not C.plan_external:  # the task list merges by task, in every merge of this repository
        P.install_driver(ROOT, [plan_rel('TODO.md'), plan_rel('DONE.md')])
    return C


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


def stop_note(asked: bool, left: int, by: str = '') -> str | None:
    """F42: the run.log line when a stop is newly asked for ('stop asked for: …, N left before the run exits')
    or taken back ('stop taken back: …'), once each (`STOP_SAID`); None when nothing changed. `left`: the
    tasks still running, waiting to resume or merging, which the stopping run waits for. A stop by a key
    already logged what it does, so its line carries only the count."""
    if asked == STOP_SAID[0]:
        return None
    STOP_SAID[0] = asked
    if not asked:
        return 'stop taken back: starting tasks again'
    what = '' if by in ('s', 's!') else 'no new tasks; exiting once the running ones are merged; '
    return f'stop asked for: {what}{left} left before the run exits'


KEYS: list[str] = []  # lines typed into the runner's pane
KEYS_LOCK = threading.Lock()  # the reader thread and the loop both take keys
WAKE = threading.Event()  # set by a key, so the loop acts on it now instead of after its 10 s nap
READING = [False]  # the reader thread is up: the loop naps on WAKE
PAUSED = [False]  # `p`: no new tasks, and the run stays up
STOP_SAID = [False]  # F42: the loop logged 'stop asked for: … N left' for the stop now asked for
FORCED = [False]  # `f`: the usage caps no longer hold new tasks, as with --force
IDLE = [False]  # the run said `run idle` and has started nothing since: STATE carries it, for the board's hold


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


def edited() -> set[str]:
    """Files with uncommitted edits in the main checkout, new ones (not ignored) included."""
    return set(git('diff', '--name-only', 'HEAD').stdout.split()) | \
        set(git('ls-files', '--others', '--exclude-standard').stdout.split())


def commit_plan(msg: str, *rels: str) -> bool:
    """Commit a runner's plan edit: in the main checkout, or, for a plan outside it, in the plan's clone."""
    if C.plan_external:
        if out := plansync.publish(C, msg):
            log(out)
        return True
    return not git('commit', '-qm', msg, '--', *rels).returncode


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


POWER = ''  # 'shutdown' or 'suspend' (--shutdown, --suspend): what the machine does once the run has nothing left to do


def run_up() -> bool:
    """A run holds `<notes>/run.lock` in this repository."""
    if f := plat.lock(C.notes('run.lock')):
        f.close()
        return False
    return True


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
