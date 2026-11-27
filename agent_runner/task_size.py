"""F470: a task's size (`plan add --size simple`) picks its session's model from `[models] sizes`, and the guard:
a simple task that fails or blocks on that model retries once on its kind's model."""
from __future__ import annotations

from pathlib import Path

from agent_runner import plan as P

RETRY = 'retry on its kind\'s model'


def mark(c, tid: str) -> Path:
    """Its presence: the task's size model was tried and it failed or blocked; the size is ignored from now on.
    It holds 'due' until the retry is set up after the merge, then 'done'."""
    return c.notes(f'{tid}.size-retry')


def field(ls: list[str], tid: str) -> str:
    """The task's `size:` field, '' when it has none."""
    return next((P.fields(rest).get('size', [''])[0] for _, _, t, rest, _ in P.iter_tasks(ls) if t == tid), '')


def size_for(c, tid: str, size: str) -> str:
    """The size its model goes by: '' when it already retried (or retries) on its kind's model."""
    return '' if size and mark(c, tid).exists() else size


def size_of(c, tid: str, ls: list[str]) -> str:
    """The size `tid`'s model goes by now (`size_for` of its `size:` field)."""
    return size_for(c, tid, field(ls, tid))


def on_size_model(c, tid: str, ls: list[str]) -> bool:
    """Its session ran on a model `[models] sizes` picked for a simple task, other than its kind's, own `model:`
    unset, and it has not retried yet."""
    size = field(ls, tid)
    if size != 'simple' or mark(c, tid).exists():
        return False
    if next((P.fields(rest).get('model', [''])[0] for _, _, t, rest, _ in P.iter_tasks(ls) if t == tid), ''):
        return False
    return c.task_model(tid, '', size) != c.task_model(tid)


def retry_due(c, tid: str, ls: list[str], passed: bool) -> bool:
    """At its session's end: a simple task on its size model whose `done` did not pass gets one more attempt on
    its kind's model. True: the mark is written, so the next start goes by its kind."""
    if passed or not on_size_model(c, tid, ls):
        return False
    mark(c, tid).write_text('due')
    return True


def reopen_blocked(c, tid: str, todo=None) -> bool:
    """After its merge: a due retry whose session blocked the task opens it again for that attempt."""
    m = mark(c, tid)
    if not m.exists() or m.read_text() != 'due':
        return False
    m.write_text('done')
    todo = todo or c.todo
    ls = P.lines(todo)
    if any(t == tid and box == '~' for _, box, t, _, _ in P.iter_tasks(ls)):
        P.unblock(tid, RETRY, todo)
        return True
    return False
