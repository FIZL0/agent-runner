"""`[plan] repo`: the task list in its own git repo, so every clone and every runner reads one queue.

Inside the code repo every branch carries its own TODO.md, and two coordinators see each other's edits only
after a code merge, which nearly always conflicts on TODO.md. With `repo` set, the plan is one clone outside
the code (`[plan] dir`, default ~/.cache/agent-runner/<name>), shared by the main checkout and every worktree:

* a read pulls first (at most every PULL_EVERY s), so a pick sees everybody's edits;
* an edit holds `locked`, pulls, edits, commits and pushes; a rejected push pulls and pushes again;
* a pull that diverged merges with `merge=union` on *.md (the clone's .git/info/attributes): plan files are
  one record per line. Then `tidy` drops an open TODO line whose task DONE.md has ticked;
* `claim`: a runner pushes claims/<ID> before it starts a task, so two runners never take the same task.
  A claim file has no .md, so two runners claiming one task conflict, and the later one backs off.

A `[plan] dir` outside the code repo without `repo` (a synced folder) gets the lock and nothing else.
"""
from __future__ import annotations

import getpass
import re
import socket
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from agent_runner import plat
from agent_runner.gitops import _net, git

PULL_EVERY = 20  # s: reads within this of the last fetch use the clone as it is
LOCK_WAIT = 300  # s an edit waits on another process's plan edit before giving up
_TL = threading.RLock()
_HELD: list = []  # [open lock file, depth] while this process holds the plan


def _lock_path(c) -> Path:
    return c.plan_dir / '.git' / 'agent-runner.lock' if c.plan_repo else c.notes('plan.lock')


@contextmanager
def locked(c):
    """One plan edit at a time across the slots, the runner and people: pull, edit, publish inside it.
    Re-entrant within a process; the file lock goes with the process however it ends."""
    with _TL:
        if not _HELD:
            ensure_clone(c)
            t0 = time.time()
            while not (f := plat.lock(_lock_path(c))):
                if time.time() - t0 > LOCK_WAIT:
                    raise SystemExit(f'agent-runner: the plan in {c.plan_dir} stayed locked {LOCK_WAIT}s')
                time.sleep(0.2)
            _HELD[:] = [f, 0]
        _HELD[1] += 1
        try:
            yield
        finally:
            _HELD[1] -= 1
            if not _HELD[1]:
                _HELD.pop(0).close()
                _HELD.clear()


def ensure_clone(c) -> None:
    if not c.plan_repo or (c.plan_dir / '.git').exists():
        return
    if c.plan_dir.exists() and any(c.plan_dir.iterdir()):
        raise SystemExit(f'agent-runner: [plan] dir {c.plan_dir} has files but is no git clone of {c.plan_repo}')
    c.plan_dir.parent.mkdir(parents=True, exist_ok=True)
    if (r := _net(c.plan_dir.parent)('clone', '-q', c.plan_repo, str(c.plan_dir))).returncode:
        raise SystemExit(f'agent-runner: cannot clone [plan] repo {c.plan_repo}: {r.stderr.strip()}')
    (c.plan_dir / '.git' / 'info').mkdir(exist_ok=True)
    (c.plan_dir / '.git' / 'info' / 'attributes').write_text('*.md merge=union\n')


def _branch(c) -> str:
    return git('branch', '--show-current', cwd=c.plan_dir).stdout.strip() or 'main'


def pull(c, force: bool = False) -> bool:
    """Bring the clone up to its remote. False when a merge conflicted (only a claim can) and was undone."""
    if not c.plan_repo:
        return True
    with locked(c):
        fh = c.plan_dir / '.git' / 'FETCH_HEAD'
        if not force and fh.exists() and time.time() - fh.stat().st_mtime < PULL_EVERY:
            return True
        if _net(c.plan_dir)('fetch', '-q', 'origin').returncode:
            return True  # offline: work on what is here, publish pushes it later
        up = f'refs/remotes/origin/{_branch(c)}'
        g = lambda *a: git(*a, cwd=c.plan_dir)
        if g('rev-parse', '--verify', '-q', up).returncode:
            return True  # an empty plan repo: the first publish creates the branch
        before = g('rev-parse', '-q', 'HEAD').stdout.strip()
        if g('merge', '-q', '--no-edit', up).returncode:
            g('merge', '--abort')
            return False
        if before and g('rev-parse', '-q', 'HEAD^2').stdout.strip():  # a real merge: lines may now repeat
            tidy(c)
            g('commit', '-qam', 'plan: drop lines a merge left open for ticked tasks')
        return True


def tidy(c) -> None:
    """Drop every top-level TODO task (with its sub-lines) that DONE.md has ticked: the union of a tick on
    one side and a note on the other keeps the old open line next to the archived one."""
    from agent_runner import plan as P
    if not (c.todo.exists() and c.done.exists()):
        return
    done = {m.group(3).rstrip('.') for l in P.lines(c.done) if (m := P.ITEM.match(l)) and m.group(2) == 'x'}
    ls, i = list(P.lines(c.todo)), 0
    while i < len(ls):
        m = P.ITEM.match(ls[i])
        if m and not m.group(1) and m.group(3).rstrip('.') in done:
            del ls[i:i + len(P._item_block(ls, i))]
        else:
            i += 1
    P._write(c.todo, ls)


def publish(c, msg: str) -> str:
    """Commit everything in the clone and push it. '' when pushed (or nothing to do), else one line to print;
    an unpushed commit stays and goes out with the next publish."""
    if not c.plan_repo:
        return ''
    g = lambda *a: git(*a, cwd=c.plan_dir)
    with locked(c):
        g('add', '-A')
        if g('diff', '--cached', '--quiet').returncode:
            g('commit', '-qm', f'plan: {msg}'[:72])
        if g('rev-parse', '-q', '--verify', 'HEAD').returncode:
            return ''
        for _ in range(3):
            if not _net(c.plan_dir)('push', '-q', 'origin', f'HEAD:{_branch(c)}').returncode:
                return ''
            if not pull(c, force=True):
                return f'! plan: {msg}: merging the remote conflicts; committed in {c.plan_dir}, not pushed'
        return f'! plan: {msg}: not pushed (offline?); committed in {c.plan_dir}, the next edit pushes it'


# --- claims: which runner has which task ------------------------------------------------------

def owner(c) -> str:
    from agent_runner.config import main_checkout
    return f'{socket.gethostname()}:{main_checkout(c.root)}'


STALE = 3 * 3600  # s without a refresh after which a claim is reported as probably left by a dead run
REFRESH = 3600  # s between a live run's refreshes of its claims (one commit for all of them)
_STAMP = '%Y-%m-%d %H:%M'


def claims(c) -> dict[str, tuple[str, float, str]]:
    """Every claim: id -> (owner, when last claimed or refreshed, who: user@host)."""
    d = c.plan_dir / 'claims'
    if not c.plan_repo or not d.is_dir():
        return {}
    out = {}
    for f in d.iterdir():
        if f.is_file():
            ls = f.read_text().splitlines() + ['', '', '']
            try:
                at = time.mktime(time.strptime(ls[1], _STAMP))
            except ValueError:
                at = 0.0
            out[f.name] = (ls[0], at, ls[2] or ls[0].split(':')[0])
    return out


def stale(cl: tuple[str, float, str]) -> bool:
    return time.time() - cl[1] > STALE


def label(cl: tuple[str, float, str]) -> str:
    """`alex@laptop 14:02`, the date too when it is not today, and STALE past STALE."""
    at = time.localtime(cl[1])
    when = time.strftime('%H:%M' if at[:3] == time.localtime()[:3] else '%m-%d %H:%M', at)
    return f'{cl[2]} {when}' + (' STALE' if stale(cl) else '')


def taken(c) -> set[str]:
    """Tasks another runner (another machine, or another checkout here) has claimed."""
    me = owner(c)
    return {t for t, cl in claims(c).items() if cl[0] != me}


def _stamp(c, f: Path) -> None:
    f.write_text(f'{owner(c)}\n{time.strftime(_STAMP)}\n{getpass.getuser()}@{socket.gethostname()}\n')


def claim(c, tid: str) -> bool:
    """Push claims/<tid> before starting it. False when another runner has it, got there first, or the claim
    could not be pushed (offline): a claim nobody else can see protects nothing, so the task waits."""
    if not c.plan_repo or not re.fullmatch(r'[\w.-]+', tid):
        return True
    with locked(c):
        if not pull(c, force=True) or tid in taken(c):
            return False
        f = c.plan_dir / 'claims' / tid
        if f.exists():
            return True  # ours already (a restarted run)
        f.parent.mkdir(exist_ok=True)
        _stamp(c, f)
        if publish(c, f'claim {tid}'):  # not pushed: lost the race (a conflict), or no remote to tell
            git('reset', '-q', '--hard', 'HEAD~1', cwd=c.plan_dir)
            pull(c, force=True)
            return False
        return True


def release(c, tid: str) -> None:
    """Drop this runner's claim on `tid` (never another's)."""
    if not c.plan_repo:
        return
    with locked(c):
        pull(c, force=True)
        f = c.plan_dir / 'claims' / tid
        if f.exists() and f.read_text().split('\n')[0] == owner(c):
            f.unlink()
            publish(c, f'release {tid}')


def refresh(c, tids) -> None:
    """Re-stamp this runner's claims on `tids` (running, or waiting to merge), so others can tell a live
    claim from one a crashed run left behind. One commit for all of them."""
    if not c.plan_repo:
        return
    with locked(c):
        pull(c, force=True)
        me = owner(c)
        for t, cl in claims(c).items():
            if t in tids and cl[0] == me:
                _stamp(c, c.plan_dir / 'claims' / t)
        publish(c, 'refresh claims')


def unclaim(c, tid: str) -> bool:
    """Drop the claim on `tid`, whoever's it is: for a run that is gone. False when there is none."""
    with locked(c):
        pull(c, force=True)
        f = c.plan_dir / 'claims' / tid
        if not f.is_file():
            return False
        f.unlink()
        publish(c, f'unclaim {tid}')
        return True


def ticks(c) -> Path:
    """Where `done` in a runner's slot leaves <ID> for the runner to tick once the merge lands."""
    d = c.notes('ticks', '.')
    d.mkdir(parents=True, exist_ok=True)
    return d

