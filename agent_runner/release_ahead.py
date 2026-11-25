"""F435: an auto release waits only for what was ahead of it when it was queued.

`after: all` is read afresh on every pick, so a task later queued above a release would hold it too, and work queued
day after day would keep one waiting for good. The release that auto release queues on idle carries the field
`| ahead: T1, T2` (`none` for none): its `after: all` counts only those tasks and their parts (P17's P17a), and a
later task's work lands in the next release. Every other rule of `after: all` (what it skips) stays. A release a
person queues or moves has no such field: it waits for all above its place, as they said."""
from __future__ import annotations

from agent_runner import plan as P

KEY = 'ahead'  # the field; `P.KEYS` has it before `after`, so a version that does not know it still reads `after: all`
NONE = 'none'


def is_listed(line: str) -> bool:
    """Does this task line list what was ahead of it?"""
    return KEY in P.fields(line)


def cleared(line: str) -> str:
    """The task line without the list."""
    return P.FIELD.sub(lambda m: '' if m.group(1) == KEY else m.group(0), line)


def counted(line: str, tid: str) -> bool:
    """Does the `after: all` of this task line count `tid`, a task above it: no list, or on it, or a part of one."""
    ids = P.fields(line).get(KEY)
    return ids is None or any(tid == t or P.child(t, tid) for t in ids)


def record(tid: str, todo) -> None:
    """List on the line of `tid` what is ahead of it now: each task above it not done, one that needs the person too
    (it holds the release once it reopens), but not those in a section no run starts."""
    ls = list(P.lines(todo))
    i = P._find(ls, tid)
    ids = [t for section, box, t, _, j in P.iter_tasks(ls)
           if j < i and box != 'x' and not section.startswith(P.SKIPPED)]
    ls[i] = cleared(ls[i]).replace(' | after: ', f' | {KEY}: {", ".join(ids) or NONE} | after: ', 1)
    P._write(todo, ls)
