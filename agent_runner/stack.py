"""F198: a task started on top of a merge that has not landed yet (the merge under test, or one built ahead), so a
finished task's files hold no slot during its gate. `<notes>/<ID>.stacked` says which merge and whose work is in
it. The branch lands only after those tasks; when their merge is refused or built again, its own commits alone are
replayed on the shared branch, so it never carries an unlanded task's commits there."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from agent_runner import gitops, plan as P, pr, state as S

CHOSEN: dict[str, dict] = {}  # task -> the merge `sched.choose` picked for it to start on: {'on', 'tids'}
POLL = 5  # seconds between looks whether the merge a finished task started on has landed

TOLD = """

This branch starts on the merge of {tids} ({on}), finished work that is still in its merge gate and not on {branch} \
yet. That work is not yours: read it, build on it, and leave it as it is. Your own diff is `git diff {on}...HEAD`, \
wherever this brief says `git diff {branch}...HEAD`. Your branch lands after it; if that merge is refused, the runner \
moves your commits onto {branch} without it, so commit only your own work and never merge or rebase. If the gate fails \
only on what that merge brought, run `done` with `--blocked "<the failing test>: waits on {tids}" --after {tids}`."""

TOLD_PR = """

This branch starts on {tids} ({on}): finished parts of the same task, which share its pull request and are not on \
{branch} yet. That work is not yours: read it, build on it, and leave it as it is. Your own diff is `git diff \
{on}...HEAD`, wherever this brief says `git diff {branch}...HEAD`. Commit only your own work and never merge or rebase."""

WARNED = """

Careful with the earlier attempt on {wip}: it was made on the merge of {tids}, which did not land, so it holds their \
commits too. Its own work is `git log -p {on}..{one}` only. Take from it by hand, or by cherry-picking commits of that \
range; never merge the branch or pick from before {on}."""

MOVE = """Task {tid}'s branch was started on the merge of {tids}, which did not land on {branch} as it was. The \
runner is moving {tid}'s own changes onto {branch} without it (a `git cherry-pick` of them as one commit, half-done in \
this checkout), and git could not finish that by itself. Finish it. Nobody will answer questions: decide, and say what \
you decided.

Conflicted files:
{files}

1. `git status` and `git diff` to see it; `git show {squashed}` is what {tid} did, on top of that merge.
2. Resolve every conflict so that {tid}'s work survives on {branch} as it is now. Leave out what only {tids} brought \
and {branch} does not have: "theirs" in a conflict holds it as context. Change nothing the conflicts do not need.
3. `git add` the files, then `git -c core.editor=true cherry-pick --continue`, and stop. That commit is your only git \
change: no push, merge, rebase or branch, no `git stash`, and leave the other worktrees alone. The runner tests it.
4. If it cannot be done honestly ({tid}'s work makes no sense without {tids}), run `git cherry-pick --abort` and say \
why in one line. That is a real answer, not a failure.
"""


def _file(tid: str) -> Path:
    return S.C.notes(f'{tid}.stacked')


def _old(tid: str) -> Path:
    return S.C.notes(f'{tid}.stacked-before')


def _has(rev: str, commit: str) -> bool:
    return not S.git('merge-base', '--is-ancestor', commit, rev).returncode


def has_line(on: str, tid: str) -> bool:
    """B805: the merge `on` has `tid`'s line in its plan, so a branch started on it can be ticked or blocked there.
    Not one filed on the shared branch after the merge was built. A plan outside the repo has one copy, for all."""
    if S.C.plan_external:
        return True
    r = S.git('show', f'{on}:{S.plan_rel("TODO.md")}')
    return not r.returncode and any(t == tid for _, _, t, _, _ in P.iter_tasks(r.stdout.splitlines()))


def stacked(tid: str, branch: str) -> dict:
    """{'on': the merge task/<tid> was started on, 'tids': whose work it holds} until that merge is on `branch`
    (or task/<tid> no longer has it); else {}."""
    try:
        s = json.loads(_file(tid).read_text(encoding='utf-8'))
        on = s['on'] if isinstance(s['tids'], list) else ''
    except (OSError, ValueError, KeyError, TypeError):
        return {}
    return s if on and _has(f'refs/heads/task/{tid}', on) and not _has(branch, on) else {}


def fork(tid: str, branch: str) -> str:
    """What task/<tid>'s own commits are past: the merge it was started on, or `branch`."""
    return stacked(tid, branch).get('on') or branch


def has_own(tid: str, branch: str) -> bool:
    """task/<tid> has commits past its fork: started on a merge, it is ahead of `branch` before its session has
    committed anything."""
    s = stacked(tid, branch)
    return not s or S.git('rev-list', '--count', f'{s["on"]}..task/{tid}').stdout.strip() not in ('', '0')


def begin(tid: str, branch: str) -> str:
    """The commit a fresh start of `tid` checks out: the merge chosen for it, recorded, else `branch`."""
    c = CHOSEN.pop(tid, None) or pr.start_on(tid, branch)  # F419: the parts its pull request has so far
    if _file(tid).exists():  # an earlier attempt's, which may be on wip/<ID>: `told` warns of it
        os.replace(_file(tid), _old(tid))
    if not c or _has(branch, c['on']):
        return branch
    _file(tid).write_text(json.dumps(c), encoding='utf-8')
    if S.C.pr:
        S.log(f'{tid}: starts on {", ".join(c["tids"])} ({c["on"][:9]}), whose pull request it shares')
        return c['on']
    S.log(f'{tid}: starts on the merge of {", ".join(c["tids"])} ({c["on"][:9]}), which has not landed; it lands '
          f'after {"it" if len(c["tids"]) == 1 else "them"}')
    return c['on']


def told(tid: str, branch: str) -> str:
    """What a task started on a merge is told beside its brief, or ''."""
    s = stacked(tid, branch)
    out = (TOLD_PR if S.C.pr else TOLD).format(tids=','.join(s['tids']), on=s['on'][:12], branch=branch) if s else ''
    try:
        o = json.loads(_old(tid).read_text(encoding='utf-8'))
        on, tids = o['on'], ','.join(o['tids'])
    except (OSError, ValueError, KeyError, TypeError):
        return out
    wips = S.git('for-each-ref', f'--contains={on}', '--format=%(refname:short)', f'refs/heads/wip/{tid}',
                 f'refs/heads/wip/{tid}-*').stdout.split()
    if wips and not _has(branch, on):
        out += WARNED.format(tids=tids, on=on[:12], wip=', '.join(wips), one=wips[0])
    return out


def pending(tid: str) -> bool:
    """`tid`'s merge is still to come in this run: the thread that merges it is alive."""
    return any(t.name == f'merge:{tid}' and t.is_alive() for t in threading.enumerate())


def settle(tid: str, branch: str, halted=lambda: False) -> str | bool | None:
    """Before finished `tid` merges: wait until the merge it was started on landed or every task in it is over, then
    replay its commits on `branch` if the merge is not there. None when it may merge (or has nothing to merge, or
    `halted`), False when the run stops first and task/<tid> waits for the next one, else why it cannot merge."""
    if S.C.pr:  # F419: it was started on its own pull request's branch, and goes back into it
        return None
    said = False
    while (s := stacked(tid, branch)) and has_own(tid, branch) and not halted():
        if not (wait := [t for t in s['tids'] if pending(t)]):
            break
        if not said:
            said = True
            S.log(f'{tid}: finished; it lands after {", ".join(wait)}, on whose merge it was started')
        time.sleep(POLL)
    if not (s := stacked(tid, branch)):  # read again: it may have landed as its thread ended
        _file(tid).unlink(missing_ok=True)
        return None
    if not has_own(tid, branch) or halted():
        return None
    if S.stopping() and (left := [t for t in s['tids'] if not S.git('rev-parse', '-q', '--verify',
                                                                    f'refs/heads/task/{t}').returncode]):
        S.log(f'{tid}: the run stops; task/{tid} waits for {", ".join(left)} in the next run', S.EV_DEFERRED, tid)
        return False
    return replay(tid, branch, s)


def replay(tid: str, branch: str, s: dict) -> str | None:
    """Move task/<tid>'s own commits off the merge `s` onto `branch`, in a fix worktree: None, or why not (the
    branch is then as it was)."""
    from agent_runner import merge as M  # merge reads this module
    tids = ', '.join(s['tids'])
    with M.FIX_DIRS_LOCK:
        while not (free := set(range(1, max(1, S.C.run['fix_ahead_max']) + 1)) - M.FIX_DIRS):
            M.FIX_DIRS_LOCK.wait()
        k = min(free)
        M.FIX_DIRS.add(k)
    d = S.SLOTS_DIR / f'fix{k}'
    g = lambda *a, **kw: S.git(*a, cwd=d, **kw)  # noqa: E731
    try:
        old = S.git('rev-parse', f'task/{tid}').stdout.strip()
        base = S.git('rev-parse', branch).stdout.strip()
        M.worktree(f'fix{k}', base)
        if why := _move(tid, branch, s, old, base, d, M):
            return (f'it was started on the merge of {tids}, which did not land, and its work could not be moved onto '
                    f'{branch}: {why} (its own commits: {s["on"][:12]}..{old[:12]})')
        new = g('rev-parse', 'HEAD').stdout.strip()
        if S.git('update-ref', f'refs/heads/task/{tid}', new, old).returncode:
            return f'task/{tid} moved while its commits were replayed on {branch}'
        _file(tid).unlink(missing_ok=True)
        S.note(f'{tid}: started on the merge of {tids}, which did not land as it was; moved onto {branch}')
        S.log(f'{tid}: the merge of {tids} it was started on did not land as it was; its own commits are now on {branch}')
        gitops.drop_remote(S.ROOT, f'task/{tid}')  # rewritten: the old one is no ancestor of it
        if out := gitops.push(S.ROOT, f'task/{tid}'):
            S.log(f'{tid}: {out}')
        return None
    finally:
        for op in ('rebase', 'cherry-pick', 'merge'):
            g(op, '--abort')
        M.clean(d)
        g('checkout', '-q', '--detach')
        with M.FIX_DIRS_LOCK:
            M.FIX_DIRS.discard(k)
            M.FIX_DIRS_LOCK.notify_all()


def _move(tid: str, branch: str, s: dict, old: str, base: str, d: Path, M) -> str | None:
    """`replay`'s work in `d`: HEAD ends on `base` plus the task's own changes. Its commits as they are when they
    apply; else all of them as one commit, joined or handed to a fix session."""
    on = s['on']
    g = lambda *a, **kw: S.git(*a, cwd=d, **kw)  # noqa: E731
    env = {'env': {**os.environ, 'AGENT_RUNNER_TASK': tid, 'GIT_EDITOR': 'true'}}

    def start(at: str) -> None:
        for op in ('rebase', 'cherry-pick', 'merge'):
            g(op, '--abort')
        M.clean(d)
        g('checkout', '-q', '--detach', at)

    if not g('rev-list', '--merges', f'{on}..{old}').stdout.strip():  # a rebase drops a merge's own resolution
        start(old)
        if not g('rebase', '-q', '--no-update-refs', '--onto', base, on, **env).returncode:
            return _foreign(on, base, d)
    start(base)
    msg = S.git('log', '-1', '--format=%B', old).stdout
    squashed = S.git('commit-tree', f'{old}^{{tree}}', '-p', on, '-m', msg).stdout.strip()
    if not squashed:
        return 'its commits could not be made into one'
    if not g('cherry-pick', squashed, **env).returncode:
        return _foreign(on, base, d)
    files = g('diff', '--name-only', '--diff-filter=U').stdout.split()
    if not files:
        if g('diff', '--cached', '--quiet').returncode:  # git rerere replayed every file
            g('commit', '-q', '--no-edit', **env)
            return _foreign(on, base, d)
        return 'git refused the cherry-pick' if g('rev-parse', '-q', '--verify', 'CHERRY_PICK_HEAD').returncode else \
            f'{branch} already has all of it'
    if M.joined(files, tid, d):
        return _foreign(on, base, d)
    if not S.C.run['fix_merges']:
        return f'conflicts in {", ".join(files)}, and [run] fix_merges is off'
    start(base)  # a refused join may have written some files
    g('cherry-pick', squashed, **env)
    while S.C.run['before_start'] and M.before_start_fails():  # no room: as a slot waits
        time.sleep(60)
    S.log(f'{tid}: its changes conflict with {branch} without the merge of {", ".join(s["tids"])} '
          f'({", ".join(files)}); handing them to a fix session in {d.name}')
    prompt = MOVE.format(tid=tid, tids=', '.join(s['tids']), branch=branch, squashed=squashed[:12],
                         files='\n'.join(f'  {f}' for f in files))
    code, why = M.fixer(f'{tid} moved onto {branch}', prompt, d, 'fix', 'fix the conflicts')
    if why:
        return why
    if not g('rev-parse', '-q', '--verify', 'CHERRY_PICK_HEAD').returncode or \
            g('status', '--porcelain', '--untracked-files=no').stdout.strip():
        return f'the fix session did not finish it (exit {code}); see {S.C.notes("fixer.log")}'
    if g('rev-parse', 'HEAD').stdout.strip() == base:
        return f'the fix session gave it up; its reason is in {S.C.notes("fixer.log")}'
    return _foreign(on, base, d)


def _foreign(on: str, base: str, d: Path) -> str | None:
    """Why HEAD in `d` may not become the task's branch: it is not on `base`, or has a commit of the unlanded merge."""
    if S.git('merge-base', '--is-ancestor', base, 'HEAD', cwd=d).returncode:
        return 'the result is not on top of it'
    mine = set(S.git('rev-list', f'{base}..HEAD', cwd=d).stdout.split())
    if mine & set(S.git('rev-list', f'{base}..{on}', cwd=d).stdout.split()):
        return 'the result still has commits of the merge that did not land'
    return None
