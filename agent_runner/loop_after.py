"""The end of each tick of the run (`Run.after`): reopened tasks, finished merges, upgrades, CI, control sessions,
claims, and the sweep of branches that finished outside the slots."""

from __future__ import annotations

from agent_runner import audit, no_commits, pr, undo
from agent_runner.state import queued, stopping
from agent_runner.autorelease import auto_release
from agent_runner.sched import keep_claims, taken
from agent_runner.asks import block_asks
from agent_runner.loop_sweep import sweep_unmerged, SWEPT, SWEEP_AT  # noqa: F401
from agent_runner.loop_upgrade import upgrade_tick
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
    upgrade_tick(run)  # C53: loop_upgrade.py
    watch_ci(branch)
    watch_issues(branch)
    if not stopping():
        auto_release(branch)  # F63: { every = N }
        audit.tick(run)  # F417
        from agent_runner import until_watch
        until_watch.tick(branch)  # F427c: until checks, on a thread of their own
    if not stopping():
        from agent_runner.control_held import controls_tick
        controls_tick(branch)  # B26, B53, B170
        from agent_runner.page_copy import page_copy_tick
        page_copy_tick()  # F68: the claude.ai copy of the run page (B122: a one-shot, never c1)
    if not stopping():
        if not run.restart_due:  # B227: a restarted run finds them as it starts
            sweep_unmerged(branch, run.merging)
    undo.tick(branch, run.merging, run.restart_due)  # F98
    pr.tick(branch, {t[0] for t in run.running.values()} | {q[0] for q in queued().values()} | set(taken()) |
            {t.name.removeprefix('merge:') for t in run.merging if t.is_alive()} | {m[0] for m in run.held_merges})  # F419, F423
    keep_claims(run.running, branch)
    no_commits.tick(branch)  # B774
    block_asks(branch, run.tried)  # F102: an ask whose block could not be committed when it was parked
    take_keys()
    # an exit may have queued one
    run.waiting = {n: q for n, q in queued().items() if n in run.free_at and n <= run.slots}
