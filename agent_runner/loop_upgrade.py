"""C53: the upgrade and restart part of the end of a tick, split from loop_after; B227: the merges a due restart holds."""

from __future__ import annotations

from agent_runner import exit_hook, plan as P, stack
from agent_runner.sched import agent_held
from agent_runner.state import C, git, log, stopping
from agent_runner.watch import auto_upgrade, CODE, restart_if_upgraded, watch_code


def upgrade_tick(run) -> None:
    """Upgrade, watch the code, and restart onto a new version when no merge is under way. While changed code waits
    for that moment no new merge starts (`hold_merge`), so overlapping merges cannot put it off for ever."""
    stop = stopping()
    if not stop:
        auto_upgrade(bool(run.merging))
        watch_code(bool(run.merging or exit_hook.busy()))  # F149; B801, as below
    run.restart_due = not stop and CODE['held'] and not on_person(run)
    if not run.restart_due:
        start_held(run)
    if not run.merging and not stopping() and not exit_hook.busy():  # B801: a restart forgets which slot it holds
        restart_if_upgraded()


def on_person(run) -> bool:
    """A merge under way waits for a person (edits in the main checkout, a wrong [run] agent), for hours maybe: the
    others are not held for it."""
    from agent_runner.loop import ON_EDITS  # loop reads this module
    return bool(ON_EDITS & {t.name.removeprefix('merge:') for t in run.merging} or run.merging and agent_held())


def hold_merge(run, tid: str, n: int, sid: str) -> bool:
    """Keep finished `tid` for the restarted run, which merges task/<tid> as any finished branch. Not one with no
    commits, which nothing of it would find, and whose end takes a moment; nor a release, which a merge under way
    may wait for (`merge.hold_for_release`): each would wait for the other."""
    if not run.restart_due or P.release(tid) or not git('rev-list', '-n1', f'{stack.fork(tid, run.branch)}..task/{tid}').stdout.strip():
        return False
    run.held_merges.append((tid, n, sid))
    log(f'{tid}: finished; its merge waits for the restart on the changed code')
    return True


def start_held(run, only=None) -> None:
    """Start the held merges (those of the tasks in `only`): no restart is due any more."""
    go = [m for m in run.held_merges if only is None or m[0] in only]
    run.held_merges = [m for m in run.held_merges if m not in go]
    due, run.restart_due = run.restart_due, False
    for m in go:
        run.merge_in(*m)
    run.restart_due = due


def start_asked(run) -> None:
    """A held task that a drop, change or restyle asks about: its merge thread answers that (`_finish`), as ever."""
    from agent_runner.loop_requests import halt_requests  # it reads loop, which reads this module
    if run.held_merges:
        start_held(run, {*halt_requests(), *P.requests(C, 'restyle')})
