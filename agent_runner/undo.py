"""F98: undoing a landed change the person did not approve (`pitch.refuse`): a commit on the shared branch, built in
the merge worktree under the merge lock, through the gate."""

from __future__ import annotations

import os
import threading
from pathlib import Path

from agent_runner import merge as M, pitch, plan as P, plansync
from agent_runner import state as S
from agent_runner.land import REOPENED
from agent_runner.sched import agent_held, AgentHeld

UNDO_FIXER = """This checkout is half way through undoing what task {tid} changed (a `git revert`), and git could not \
finish it: {files}

Nobody will answer questions: decide. See what {tid} did with `git diff {before} {after}`. Resolve each conflict so that \
{tid}'s change is gone and everything other tasks did since stays. Change nothing else. Then `git add` the files and \
stop: no commit, no push, no reset. If it cannot be undone without breaking other work, leave the conflicts and say why."""


def _undo_one(x: dict, d: Path) -> str:
    """Take change `x` (`pitch`) back out of the checkout `d`, staged and not committed; why it could not, or ''.
    The plan's own files stay as they are: the caller edits them."""
    if not x['before']:
        return 'its merge could not be told apart from the others it landed with'
    tid, plan_dir = x['id'], '' if S.C.plan_external else S.plan_rel('').rstrip('/')
    g = lambda *a, **kw: S.git(*a, cwd=d, **kw)
    idx = {'env': {**os.environ, 'GIT_INDEX_FILE': str(S.C.notes('undo.index'))}}
    S.C.notes('undo.index').unlink(missing_ok=True)
    g('read-tree', x['after'], **idx)
    if plan_dir:  # its plan edits are not undone: read as if it had made none
        g('rm', '-r', '-q', '--cached', '--ignore-unmatch', '--', plan_dir, **idx)
        if not g('rev-parse', '-q', '--verify', f'{x["before"]}:{plan_dir}').returncode:
            g('read-tree', f'--prefix={plan_dir}/', f'{x["before"]}:{plan_dir}', **idx)
    tree = g('write-tree', **idx).stdout.strip()
    one = g('commit-tree', tree, '-p', x['before'], '-m', f'{tid} as one commit').stdout.strip() if tree else ''
    if not one:
        return 'git could not rebuild its change'
    if tree == g('rev-parse', f'{x["before"]}^{{tree}}').stdout.strip() or \
            not (r := g('revert', '--no-commit', one)).returncode:
        g('revert', '--quit')
        return ''
    files = g('diff', '--name-only', '--diff-filter=U').stdout.split()
    if files and S.C.run['fix_merges']:
        S.log(f'{tid}: undoing it conflicts in {", ".join(files)}; handing it to a fix session')
        if why := M.fixer(f'{tid} undo {", ".join(files)}', UNDO_FIXER.format(
                tid=tid, files=', '.join(files), before=x['before'], after=x['after']), d, 'fix', 'undo it')[1]:
            return why
        files = g('diff', '--name-only', '--diff-filter=U').stdout.split()
        if not files and not g('diff', 'HEAD', '--check').stdout.count('leftover conflict marker'):
            g('revert', '--quit')
            return ''
    return f'it conflicts with later work in {", ".join(files)}' if files else \
        (r.stderr.strip().splitlines() or ['git revert failed'])[-1][:200]


def _undo_plan(x: dict, todo: Path, done: Path) -> None:
    """The plan's side of an undo: the task reopens, or stays closed as dropped, with the person's why."""
    tid, live = x['id'], P.open_ids(P.lines(todo))
    said = 'not approved, its merge was undone' + (f': {x["why"]}' if x['why'] else '')
    if x['how'] == 'drop':
        if tid in live:
            P.drop(tid, said, todo=todo, done=done)
        elif tid in {t for _, _, t, _, _ in P.iter_tasks(P.lines(done))}:
            P.note(tid, f'dropped: {said}', todo=done)
        return
    if tid not in live:
        P.restore(tid, todo=todo, done=done)
        P.note(tid, said, todo=todo)
    else:
        P.unblock(tid, said, todo=todo)


WAITS = [False]  # B764c: an undo needs a fix session, and [run] agent is wrong


def undo_changes(branch: str) -> None:
    """F98: undo the changes a person said Not this to (`pitch.undoing`): one commit each on the shared branch,
    newest first, tested and landed like a merge. One that cannot be goes back under Needs you with why."""
    for x in pitch.undoing():
        if M.releasing(x['id'], branch):
            return
        with S.MERGE.turn(lambda: 1):
            try:
                why = _undo(x, branch)
            except AgentHeld as e:  # B764c: it conflicts, and its fix session waits until [run] agent is right
                S.log(f'{x["id"]}: not undone yet: {e}')
                WAITS[0] = True
                return
            except Exception as e:  # noqa: BLE001 - said under Needs you, not lost in a thread
                why = f'{type(e).__name__}: {e}'
        if why:
            S.log(f'{x["id"]}: not undone: {why}')
            pitch.not_undone([x['key']], why)


def _undo(x: dict, branch: str) -> str:
    """`undo_changes` for one change, holding MERGE: why it could not, or ''."""
    tid, d = x['id'], M.worktree('merge', branch)
    M.adopt_merge(d)
    try:
        for attempt in range(3):
            S.git('merge', '--abort', cwd=d)
            S.clean(d)
            base = S.git('rev-parse', branch).stdout.strip()
            S.git('checkout', '-q', '--detach', base, cwd=d)
            if why := _undo_one(x, d):
                return why
            if not S.C.plan_external:
                _undo_plan(x, d / S.plan_rel('TODO.md'), d / S.plan_rel('DONE.md'))
            S.git('add', '-A', cwd=d)
            head = f'{tid}: ' if S.C.run['include_task_id_in_commit'] else ''
            if S.git('commit', '-qm', f'{head}undo, not approved', '--allow-empty', cwd=d).returncode:
                return 'the undo could not be committed'
            merged = S.git('rev-parse', 'HEAD', cwd=d).stdout.strip()
            if why := M.tested(tid, d, base, [tid]):
                M.FAILED.pop(tid, None)
                return why
            if (got := M.caught_up(tid, branch, d, base, merged, [tid])) is None:
                continue
            with S.LANDING:
                why = M.land(tid, branch, got[1])
            if why == 'conflict' and attempt < 2:
                continue
            if why:
                return why
            if S.C.plan_external:
                with plansync.locked(C):
                    plansync.pull(C, force=True)
                    _undo_plan(x, S.C.todo, S.C.done)
                    if out := plansync.publish(C, f'{tid}: undone, not approved'):
                        S.log(out)
            msg = f'{tid}: undone, not approved ({"dropped" if x["how"] == "drop" else "reopened"})'
            S.note(msg)
            S.log(msg)
            REOPENED.add(tid)
            pitch.undone([x['key']], got[1])
            from agent_runner import control_settled  # F160
            control_settled.record(S.C, [tid], 'was dropped' if x['how'] == 'drop' else 'was reopened',
                                   'not approved, its merge was undone' + (f': {x["why"]}' if x['why'] else ''),
                                   who={'by': 'the run', 'n': 0, 'sid': ''})
            return ''
        return 'the undo did not land in three tries'
    finally:
        S.git('revert', '--quit', cwd=d)
        S.git('merge', '--abort', cwd=d)
        S.clean(d)
        S.git('checkout', '-q', '--detach', cwd=d)


def tick(branch: str, merging: list, hold: bool = False) -> None:
    """From the run loop: the pitches' own tick, and an undo, when one waits, in a thread among the merges (`hold`: a restart is due, so none
    starts now)."""
    if not pitch.on():
        return
    pitch.tick()
    if WAITS[0] and agent_held():
        return
    WAITS[0] = False
    if not hold and pitch.undoing() and not S.stopping() and not any(t.name == 'undo' for t in merging):
        t = threading.Thread(target=undo_changes, args=(branch,), name='undo')
        t.start()
        merging.append(t)
