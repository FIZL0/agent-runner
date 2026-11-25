"""F429: a held task (`plan hold`): it keeps its place in the queue and is skipped until `plan unhold`.

The hold is the field `| held: yes` on the task's line, so the plan's merge and sync carry it. No run starts a held task
(`sched.holds`), an `after: all` release does not wait for it (`plan._split_skipped`), and a held release stops the
automatic count (`autorelease.waiting_releases`)."""
from __future__ import annotations

from agent_runner import plan as P

KEY = 'held'  # the field, and the state a queue row shows


def is_held(line: str) -> bool:
    """Does this task line carry a hold?"""
    return KEY in P.fields(line)


def cleared(line: str) -> str:
    """The task line without its hold."""
    return P.FIELD.sub(lambda m: '' if m.group(1) == KEY else m.group(0), line)


def held_ids(ls: list[str]) -> set[str]:
    """The held tasks of TODO.md's lines `ls` that are not done."""
    return {tid for _, box, tid, _, i in P.iter_tasks(ls) if box in ' ~' and is_held(ls[i])}


def under_way(c, tid: str) -> str:
    """Why `tid` cannot be held now ('s2 is on it', 'it is taken by hand'), '' when nothing works on it."""
    from agent_runner import plansync, sched, state
    if where := P.run_on(c, tid):
        return f'{where} is on it' if where != 'merging' else 'it is merging'
    try:
        if state.C is None:
            state.init()
        if tid in sched.taken():
            return 'it is taken by hand'
        if tid in sched.ahead(state.default_branch()):
            return 'it is finished and waits to merge'
        cl = plansync.claims(c).get(tid)
    except (OSError, SystemExit, ValueError):
        return ''
    return f'{cl.who} has claimed it' if cl and not plansync.stale(cl) else ''


def _open_line(ls: list[str], tid: str) -> int:
    i = P._find(ls, tid)
    if P.ITEM.match(ls[i]).group(2) not in ' ~':
        raise SystemExit(f'{P.PROG}: {tid} is done')
    return i


def hold_task(tid: str, todo=None) -> bool:
    """Hold `tid` where it stands. False when it was held already."""
    todo, _ = P.ensure(todo)
    ls = list(P.lines(todo))
    i = _open_line(ls, tid)
    if is_held(ls[i]):
        return False
    P.edit(tid, keyed=f' | {KEY}: yes', todo=todo)
    return True


def unhold_task(tid: str, todo=None) -> bool:
    """End the hold on `tid`. False when it was not held."""
    todo, _ = P.ensure(todo)
    ls = list(P.lines(todo))
    i = _open_line(ls, tid)
    if not is_held(ls[i]):
        return False
    ls[i] = cleared(ls[i])
    P._write(todo, ls)
    return True
