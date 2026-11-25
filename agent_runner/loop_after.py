"""The end of each tick of the run (`Run.after`): reopened tasks, finished merges, upgrades, CI, control sessions,
claims, and the sweep of branches that finished outside the slots."""

from __future__ import annotations

import threading
import time

from agent_runner import exit_hook, no_commits, stack, undo
from agent_runner.state import log, queued, stopping
from agent_runner.autorelease import auto_release
from agent_runner.sched import keep_claims
from agent_runner.asks import block_asks
from agent_runner.slots import unmerged
from agent_runner.watch import auto_upgrade, restart_if_upgraded, watch_code
from agent_runner.land import REOPENED, retry_reopened
from agent_runner.loop_watch import watch_ci, watch_issues


def after(run) -> None:
    """The end of a tick of `run` (a loop.Run): reopened tasks, finished merges, upgrades, CI, control sessions, claims."""
    from agent_runner.loop import take_keys
    branch = run.branch
    retry_reopened(run.tried, run.closed, branch)
    if REOPENED:
        run.tried -= REOPENED  # a task reopened by a merge is a new attempt, not the one that blocked
        REOPENED.clear()
    run.merging = [t for t in run.merging if t.is_alive()]
    if not stopping():
        auto_upgrade(bool(run.merging))
        watch_code(bool(run.merging))  # F149
    if not run.merging and not stopping() and not exit_hook.busy():  # B801: a restart forgets which slot it holds
        restart_if_upgraded()
    watch_ci(branch)
    watch_issues(branch)
    if not stopping():
        auto_release(branch)  # F63: { every = N }
    if not stopping():
        from agent_runner.control_held import controls_tick
        controls_tick(branch)  # B26, B53, B170
        from agent_runner.page_copy import page_copy_tick
        page_copy_tick()  # F68: the claude.ai copy of the run page (B122: a one-shot, never c1)
    if not stopping():
        sweep_unmerged(branch, run.merging)
    undo.tick(branch, run.merging)  # F98
    keep_claims(run.running, branch)
    no_commits.tick(branch)  # B774
    block_asks(branch, run.tried)  # F102: an ask whose block could not be committed when it was parked
    take_keys()
    # an exit may have queued one
    run.waiting = {n: q for n, q in queued().items() if n in run.free_at and n <= run.slots}


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
