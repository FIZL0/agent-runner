"""`[plan] repo`: the task list in its own git repo, so every clone and every runner reads one queue.

Inside the code repo every branch carries its own TODO.md, and two coordinators see each other's edits only
after a code merge, which nearly always conflicts on TODO.md. With `repo` set, the plan is one clone outside
the code (`[plan] dir`, default `[run] home`/plan), shared by the main checkout and every worktree:

* a read pulls first (at most every PULL_EVERY s), so a pick sees everybody's edits;
* an edit holds `locked`, pulls, edits, commits and pushes; a rejected push pulls and pushes again;
* a pull that diverged merges the task list and its archive by section and task (`plan.merge3`, git's
  merge driver for them in the clone), and other *.md with `merge=union`;
* `claim`: a runner pushes claims/<ID> before it starts a task, so two runners never take the same task.
  A claim file has no .md, so two runners claiming one task conflict, and the later one backs off.

Claims work for a plan inside the code repo too: refs on the code's remote (`_Refs`).

A `[plan] dir` outside the code repo without `repo` (a synced folder) gets the lock and nothing else.
"""
from __future__ import annotations

import getpass
import os
import re
import socket
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import NamedTuple

from agent_runner import plat
from agent_runner.gitops import _net, git
from agent_runner.whole_write import write_whole

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
    drive(c)


def drive(c) -> None:
    """The clone merges its task list and archive through `plan.merge3` (later lines in its attributes win
    over `*.md merge=union`); run on every pull, so a clone made before it gets it too."""
    from agent_runner import plan as P
    P.install_driver(c.plan_dir, [p.relative_to(c.plan_dir).as_posix() for p in (c.todo, c.done)])


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
        drive(c)
        from agent_runner import join  # it reads this module
        was = g('rev-parse', 'HEAD').stdout.strip()
        renumbered = join.renumber_plan(c, c.plan_dir, up)
        if g('merge', '-q', '--no-edit', up).returncode:
            g('merge', '--abort')
            if renumbered:
                g('reset', '-q', '--keep', was)  # a renumbering goes with the merge it was for
            return False
        for then in renumbered:
            then()
        return True


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
        if c.no_push:  # F400
            return ''
        for _ in range(3):
            if not _net(c.plan_dir)('push', '-q', 'origin', f'HEAD:{_branch(c)}').returncode:
                return ''
            if not pull(c, force=True):
                return f'! plan: {msg}: merging the remote conflicts; committed in {c.plan_dir}, not pushed'
        return f'! plan: {msg}: not pushed (offline?); committed in {c.plan_dir}, the next edit pushes it'


# --- F173: one file committed on the shared branch ----------------------------------------------

def commit_file(root: Path, f: Path, edit, branch: str) -> tuple[bool, str]:
    """Change `f` with `edit` (its bytes -> its new bytes and the commit message) and commit only it in the main checkout
    `root`, so it is never left dirty; the caller holds state.LANDING. (True, '') committed, (True, note) when there was
    nothing to commit, (False, why) with nothing changed. A file outside the repo, or one git ignores, is written
    and not committed."""
    g = lambda *a: git(*a, cwd=root)  # noqa: E731
    try:
        rel = f.resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        rel = ''
    tracked = bool(rel) and not g('ls-files', '--error-unmatch', '--', rel).returncode
    new = not f.exists()
    outside = not rel or not tracked and not g('check-ignore', '-q', '--', rel).returncode
    if not outside:
        from agent_runner.config import cfg
        if cfg(root).pr:  # F419: a commit here would reach main without a pull request, or never
            return False, f'PR mode is on, so a change to {f.name} goes in a pull request. Nothing was changed'
        st = g('status', '--porcelain', '--', rel)
        if st.returncode:
            return False, f'git could not read {f.name}: {st.stderr.strip()}'
        if st.stdout.strip():
            return False, f'{f.name} has uncommitted edits in {root}: commit or undo them first. Nothing was changed'
        cur = g('branch', '--show-current').stdout.strip()
        if cur != branch:
            return False, f'{root} has {cur or "a detached HEAD"} out, not {branch}. Nothing was changed'
        for what in ('MERGE_HEAD', 'rebase-merge', 'rebase-apply', 'CHERRY_PICK_HEAD', 'REVERT_HEAD'):
            at = g('rev-parse', '--path-format=absolute', '--git-path', what).stdout.strip()
            if at and os.path.exists(at):
                return False, f'a merge or rebase is under way in {root}: finish it first. Nothing was changed'
    path = f.resolve()
    old = b'' if new else path.read_bytes()
    data, msg = edit(old)
    if data == old:
        return True, 'nothing to change'
    _write(path, data, new)
    if outside:
        return True, f'{f.name} is not in git here, so there is no commit'
    try:
        why = g('add', '-N', '--', rel).stderr.strip() if new else ''
        for _ in range(20):  # another git command in this checkout holds the index for a moment
            r = g('commit', '-q', '-m', msg, '--', rel)
            if not r.returncode:
                return True, ''
            why = r.stderr.strip() or r.stdout.strip() or why
            if 'index.lock' not in why:
                break
            time.sleep(0.25)
    except BaseException:
        _undo(path, old, new, g, rel)
        raise
    _undo(path, old, new, g, rel)
    return False, f'{f.name} could not be committed ({why[-200:]}). Nothing was changed'


def _write(path: Path, data: bytes, new: bool = False) -> None:
    write_whole(path, data, None if new else path.stat().st_mode & 0o777)


def _undo(path: Path, old: bytes, new: bool, g, rel: str) -> None:
    if not new:
        return _write(path, old)
    path.unlink(missing_ok=True)
    g('reset', '-q', '--', rel)


# --- claims: which runner has which task ------------------------------------------------------

def owner(c) -> str:
    from agent_runner.config import main_checkout
    return f'{socket.gethostname()}:{main_checkout(c.root)}'


REFRESH = 15 * 60  # s between a live run's refreshes of its claims (one commit for all of them)
STALE = 90 * 60  # s without a refresh after which a claim is a dead run's: it holds its task, not its files
_STAMP = '%Y-%m-%d %H:%M'
# The claim file, one field a line:
#   owner (host:checkout) / refreshed (_STAMP) / user@host / version / claimed at (epoch) / files, tab-separated


class Claim(NamedTuple):
    owner: str
    at: float  # when last claimed or refreshed
    who: str  # user@host
    version: str = ''
    since: float = 0.0  # when first claimed: the earlier of two clashing claims keeps its task
    files: frozenset = frozenset()  # the task line's files and the ones its session has touched


class _Files:
    """`[plan] repo`: claims/<ID> files in the plan clone, pushed with the plan. A claim file has no .md, so two
    runners claiming one task conflict, and the later one backs off."""
    def __init__(self, c):
        self.c, self.d = c, c.plan_dir / 'claims'

    def sync(self) -> bool:
        return pull(self.c, force=True)

    def texts(self) -> dict[str, str]:
        return {f.name: f.read_text() for f in self.d.iterdir() if f.is_file()} if self.d.is_dir() else {}

    def put(self, tid: str, text: str, new: bool = False) -> bool:
        self.d.mkdir(exist_ok=True)
        (self.d / tid).write_text(text)
        return True

    def drop(self, tid: str) -> None:
        (self.d / tid).unlink(missing_ok=True)

    def flush(self, msg: str) -> bool:
        return not publish(self.c, msg)

    def undo(self) -> None:  # a claim commit that did not push: lost the race, or no remote to tell
        git('reset', '-q', '--hard', 'HEAD~1', cwd=self.c.plan_dir)
        pull(self.c, force=True)


class _Refs:
    """A plan in the code repo: refs/agent-runner/claims/<ID> on the code's remote, each a commit whose message
    is the claim file. Creating one is a push of a parentless commit, which the remote turns down when the ref
    is there already: two runners claiming one task, on one machine or two, and the later one backs off. A
    re-stamp is a child commit (a fast-forward); a drop deletes the ref only if it is still the one read.
    Outside the branches and tags, so no clone, CI or UI sees them."""
    NS = 'refs/agent-runner/claims/'

    def __init__(self, c, remote: str):
        self.c, self.remote = c, remote
        self.net, self.g = _net(c.root), lambda *a: git(*a, cwd=c.root)

    def sync(self) -> bool:
        self.net('fetch', '-q', '--prune', self.remote, f'+{self.NS}*:{self.NS}*')
        return True  # offline: what was read last; a claim push still has to win

    def texts(self) -> dict[str, str]:
        out = self.g('for-each-ref', f'--format=%(refname:lstrip=3)%00%(contents)%00', self.NS).stdout
        parts = out.split('\0')
        return {parts[i].strip(): parts[i + 1] for i in range(0, len(parts) - 1, 2)}

    def put(self, tid: str, text: str, new: bool = False) -> bool:
        ref = self.NS + tid
        old = '' if new else self.g('rev-parse', '-q', '--verify', ref).stdout.strip()
        tree = git('mktree', cwd=self.c.root, input='').stdout.strip()
        sha = self.g('commit-tree', tree, *(['-p', old] if old else []), '-m', text).stdout.strip()
        if not sha or self.net('push', '-q', self.remote, f'{sha}:{ref}').returncode:
            return False
        self.g('update-ref', ref, sha)
        return True

    def drop(self, tid: str) -> None:
        ref = self.NS + tid
        if old := self.g('rev-parse', '-q', '--verify', ref).stdout.strip():
            self.net('push', '-q', f'--force-with-lease={ref}:{old}', self.remote, f':{ref}')
            self.g('update-ref', '-d', ref)

    def flush(self, msg: str) -> bool:
        return True

    def undo(self) -> None:
        self.sync()


def store(c):
    """Where this repo's claims live: the plan clone, the code's remote, or nowhere (no remote to share them
    through: a local-only run is the only runner)."""
    if c.no_push:  # F400: a claim is a push
        return None
    if c.plan_repo:
        return _Files(c)
    if c.approve:  # F98: nothing reaches the push remote unapproved, a claim neither
        return None
    if not c.plan_external and (r := c.push_remote) and not git('remote', 'get-url', r, cwd=c.root).returncode:
        return _Refs(c, r)
    return None


def enabled(c) -> bool:
    return store(c) is not None


SYNCED: dict = {}  # store kind -> when a read last synced (a claim, release or refresh always does)


def claims(c) -> dict[str, Claim]:
    """Every claim: id -> Claim."""
    if not (st := store(c)):
        return {}
    if isinstance(st, _Refs) and time.time() - SYNCED.get(str(c.root), 0) > PULL_EVERY:
        SYNCED[str(c.root)] = time.time()
        st.sync()  # a plan clone syncs on its own reads (`pull`)
    out = {}
    for tid, text in st.texts().items():
        ls = text.splitlines() + [''] * 6
        try:
            at = time.mktime(time.strptime(ls[1], _STAMP))
        except ValueError:
            at = 0.0
        try:
            since = float(ls[4])
        except ValueError:
            since = at
        out[tid] = Claim(ls[0], at, ls[2] or ls[0].split(':')[0], ls[3], since,
                         frozenset(x for x in ls[5].split('\t') if x))
    return out


def stale(cl: Claim) -> bool:
    return time.time() - cl[1] > STALE


def label(cl: Claim) -> str:
    """`alex@laptop 14:02`, the date too when it is not today, the runner's version, and STALE past STALE."""
    at = time.localtime(cl[1])
    when = time.strftime('%H:%M' if at[:3] == time.localtime()[:3] else '%m-%d %H:%M', at)
    return f'{cl.who} {when} ' + f'v{cl.version}' + (' STALE' if stale(cl) else '')


def taken(c) -> set[str]:
    """Tasks another runner (another machine, or another checkout here) has claimed."""
    me = owner(c)
    return {t for t, cl in claims(c).items() if cl.owner != me}


def _stamp(c, old: str | None, files=None) -> str:
    """A claim of this runner's, new or re-stamped: when it was first claimed is kept; `files` replaces the
    held files when given."""
    from agent_runner import __version__
    old_ls = (old or '').splitlines() + [''] * 6
    since = old_ls[4] or f'{time.time():.3f}'
    held = '\t'.join(sorted(files)) if files is not None else old_ls[5]
    return (f'{owner(c)}\n{time.strftime(_STAMP)}\n{getpass.getuser()}@{socket.gethostname()}\n'
            f'{__version__}\n{since}\n{held}\n')


def _mine(c, text: str | None) -> bool:
    return bool(text) and text.split('\n')[0] == owner(c)


def claim(c, tid: str, files=()) -> bool:
    """Claim `tid` before starting it. False when another runner has it, got there first, or the claim could
    not be published (offline): a claim nobody else can see protects nothing, so the task waits."""
    if not (st := store(c)) or not re.fullmatch(r'[\w.-]+', tid):
        return True
    with locked(c):
        if not st.sync():
            return False
        have = st.texts().get(tid)
        if have is not None:
            return _mine(c, have)  # ours already (a restarted run), or another runner's
        if not (st.put(tid, _stamp(c, None, files), new=True) and st.flush(f'claim {tid}')):
            st.undo()
            return False
        return True


def release(c, tid: str) -> None:
    """Drop this runner's claim on `tid` (never another's)."""
    if not (st := store(c)):
        return
    with locked(c):
        st.sync()
        if _mine(c, st.texts().get(tid)):
            st.drop(tid)
            st.flush(f'release {tid}')


def refresh(c, tids, files=None) -> None:
    """Re-stamp this runner's claims on `tids` (running, or waiting to merge), so others can tell a live
    claim from one a crashed run left behind, and drop the rest of its claims: a task that ended while this
    run was down, or was ticked elsewhere, holds nothing. `files`: id -> the files that claim holds now.
    One commit for all of them (in a plan clone)."""
    if not (st := store(c)):
        return
    files = files or {}
    with locked(c):
        st.sync()
        for t, text in st.texts().items():
            if not _mine(c, text):
                continue
            if t in tids:
                st.put(t, _stamp(c, text, files.get(t)))
            else:
                st.drop(t)
        st.flush('refresh claims')


def unclaim(c, tid: str) -> bool:
    """Drop the claim on `tid`, whoever's it is: for a run that is gone. False when there is none."""
    if not (st := store(c)):
        return False
    with locked(c):
        st.sync()
        if tid not in st.texts():
            return False
        st.drop(tid)
        st.flush(f'unclaim {tid}')
        return True


def ticks(c) -> Path:
    """Where `done` in a runner's slot leaves <ID> for the runner to tick once the merge lands."""
    d = c.notes('ticks', '.')
    d.mkdir(parents=True, exist_ok=True)
    return d
