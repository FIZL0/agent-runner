"""B764c: what the run loop does while [run] agent is wrong (`sched.agent_held`): it says so once, and a finished
task's merge that needs a fix or repair session waits.

Not one of the FAMILY modules `share` reaches, so the run's settings are read through their modules."""

from __future__ import annotations

import time

from agent_runner import settings_live, state as S
from agent_runner.sched import agent_held, AgentHeld

AGENT_POLL = 5  # s: how often a merge that needs a fix session looks whether [run] agent is right again
SAID = ['']  # the wrong [run] agent, as logged


def tick(run) -> None:
    """From the loop's tick: `run` takes changed settings; logged once that a wrong [run] agent holds every start, and
    once that it is right again, when the control sessions a shutdown cut off come back."""
    from agent_runner.control import reopen_when_right
    settings_live.take(run)
    bad = agent_held()
    if bad and bad != SAID[0]:
        S.log(f'{bad}. No agent session starts until then; running ones go on')
    elif SAID[0] and not bad:
        S.log('[run] agent is right again: sessions start again')
    SAID[0] = bad
    reopen_when_right()


def once_right(tid: str, step, halted):
    """`step()`, again each time [run] agent is right after it raised AgentHeld. False when the run stops, or the person
    drops or changes `tid` (`halted()`), while it waits."""
    while True:
        try:
            return step()
        except AgentHeld as e:
            S.note(f'{tid}: waits to merge: {e}')
            S.log(f'{tid}: not merged yet: it needs a fix session, and {e}. task/{tid} stays, and merges once it is fixed')
        while agent_held():
            if halted():
                return False
            if S.stopping():
                S.log(f'{tid}: the run stops; task/{tid} waits for the next run to merge it', S.EV_DEFERRED, tid)
                return False
            time.sleep(AGENT_POLL)
