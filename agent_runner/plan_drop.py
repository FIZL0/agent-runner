"""C52: `plan drop` and `plan restore`, the two ways a task leaves the plan without landing.

Moved out of plan.py with no change: `plan` re-exports every name here, so `plan.<name>` still works.
Import `agent_runner.plan` first (it imports this module last, once its own names exist)."""
from __future__ import annotations

import os
import re
from pathlib import Path
from agent_runner.plan import (
    ITEM, PROG, SPLIT, _find, _item_block, _mark,
    _place, _write, ensure, iter_tasks, lines, long_form,
    note, open_ids, tick,
)


def _split_ids(todo) -> set[str]:
    """Ids of the tasks in `todo` not done that say `(split into …)`."""
    ls = lines(todo)
    return {tid for _, box, tid, _, i in iter_tasks(ls) if box != 'x' and SPLIT.search(ls[i])}


def drop(tid: str, why: str, todo=None, done=None) -> list[str]:
    """Close a task nobody will do (a duplicate, work another task overtook): noted, then archived as ticked,
    so its id stays used and what waits on it reopens. Returns the split parents it made one whole task again:
    this was their last open part and none landed (B197)."""
    todo, done = ensure(todo, done)
    was = _split_ids(todo)
    note(tid, f'dropped: {why}', todo=todo)
    tick(tid, todo, done)
    from agent_runner.asks import clear_env  # here: asks imports this module
    clear_env(tid, todo)  # F175
    return sorted(was & open_ids(lines(todo)) - _split_ids(todo))


DROPPED = ' — dropped: '


def restore(tid: str, where: str = 'top', ref: str | None = None, todo=None, done=None, plan_dir=None) -> None:
    """Undo a mistaken tick or drop (F47): the task's block goes from DONE.md back to TODO.md as open [ ], same id,
    its text, fields and sub-items kept, less the ` — dropped: WHY` its drop appended; at the top of the leading
    section unless `where` (as `move`) says. A tick made but not archived yet is reopened where it stands."""
    todo, done = ensure(todo, done)
    plan_dir = str(plan_dir or os.path.dirname(todo))
    ls, dl = list(lines(todo)), list(lines(done))
    here = next((i for i, l in enumerate(ls) if (m := ITEM.match(l)) and not m.group(1)
                 and m.group(3).rstrip('.') == tid), None)
    if here is not None and ITEM.match(ls[here]).group(2) != 'x':
        raise SystemExit(f'{PROG}: {tid} is still open in {Path(todo).name}: nothing to restore')
    if here is None:
        try:
            j = _find(dl, tid)
        except SystemExit:
            raise SystemExit(f'{PROG}: no task {tid!r} in {Path(done).name} to restore') from None
        blk = _item_block(dl, j)
        del dl[j:j + len(blk)]
        if j < len(dl) and not dl[j].strip() and j and not dl[j - 1].strip():
            del dl[j]  # don't leave a double blank line behind
        here = _place(ls, where, ref)
        ls[here:here] = blk
    else:
        blk = _item_block(ls, here)
    for k in range(here + len(blk) - 1, here - 1, -1):  # the drop's note is the last one on the block
        if DROPPED in ls[k]:
            ls[k] = ls[k][:ls[k].rindex(DROPPED)]
            break
    _mark(ls, here, ' ')
    _write(todo, ls)
    _write(done, dl)
    own = long_form(plan_dir, tid)
    if os.path.exists(own):
        _write(own, [re.sub(rf'^(\s*)- \[x\] \*\*{re.escape(tid)}\b', rf'\1- [ ] **{tid}', l) for l in lines(own)])
