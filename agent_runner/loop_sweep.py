"""C53: the sweep of branches that finished outside the slots, split from loop_after."""

from __future__ import annotations

import threading
import time

from agent_runner import stack
from agent_runner.state import log
from agent_runner.slots import unmerged

SWEPT: set[str] = set()  # tasks sweep_unmerged started a merge of: once each per run
SWEEP_AT = [0.0]


def sweep_unmerged(branch: str, merging: list) -> None:
    """Every 30 s: merge a task/<ID> that finished outside this run's slots (`take --merge`), as a run
    start merges what finished while no run was up. Once per task per run: a merge that crashes is said once."""
    from agent_runner.loop import finish
    if time.time() - SWEEP_AT[0] < 30:
        return
    SWEEP_AT[0] = time.time()
    live = {t.name for t in merging if t.is_alive()}
    for tid in sorted(unmerged(branch, []), key=lambda t: bool(stack.stacked(t, branch))):  # after what it is on
        if tid in SWEPT or f'merge:{tid}' in live:
            continue
        SWEPT.add(tid)
        log(f'{tid}: finished outside the slots; merging it now')
        t = threading.Thread(target=finish, args=(tid, 0, '(unknown)', branch), name=f'merge:{tid}')
        t.start()
        merging.append(t)
