"""B144: a run's stop leaves nothing for the next run to meet. The stop ends the run's own processes (feed,
control server, board) and closes its page before it says `run stopped`. A start that finds a run still
stopping waits for it instead of adopting what it left or meeting its port (R14,
docs/research/R14-restart-after-stop.md)."""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Callable

from agent_runner import plat
from agent_runner.slots import marker_pid, single_run
from agent_runner import state as S
from agent_runner.state import EV_STOPPED, log, stopping

RUN_LOCK: list = []  # run.lock's open file, held until run() has returned
PAGE: list = []  # the run page server `start_web` returned, closed by the stop before it says so
LAST_RUN_WAIT = 30  # s a start waits for a run that is stopping to be gone
OWN_WAIT = 10  # s the stop gives its board and control server to end after SIGTERM


def last_event_stopped() -> bool:
    """Is the run log's last event `run stopped`? (the run holding run.lock is on its way out)"""
    try:
        with open(S.C.notes('events.jsonl'), 'rb') as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - 4096))
            tail = fh.read().decode('utf-8', errors='replace').splitlines()
    except OSError:
        return False
    for line in reversed(tail):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if isinstance(d, dict) and d.get('kind'):
            return d['kind'] == EV_STOPPED
    return False


def wait_last_run(limit: float = LAST_RUN_WAIT) -> object:
    """Take run.lock. A start right after a stop waits up to `limit` s for that run to be gone (it holds the
    lock until its teardown is over, and says `run stopped` only once its board, control server and page are
    gone), so it never adopts the old run's leftovers or meets its port. A run that is up and not stopping is
    refused at once, as before (`single_run`)."""
    f, said = S.C.notes('run.lock'), False
    end = time.monotonic() + limit
    while time.monotonic() < end:
        if got := plat.lock(f):
            return got
        if not (stopping() or last_event_stopped()):
            break
        if not said:
            print('waiting for the run that is stopping to end…', file=sys.stderr, flush=True)
            said = True
        time.sleep(0.5)
    return single_run()


def end_own(sweep: Callable[[], None], say: Callable[[str], None] = log) -> None:
    """The stop's teardown, before it says `run stopped`: the feed and control server end and archive their
    entries (`sweep`, the loop's `rc_sweep_stop`), the board ends, and the run page stops serving, so a run
    started right after finds none of them. Control sessions are the person's and stay up (one outlives a
    stopped run)."""
    sweep()
    from agent_runner.control import control_server_live
    ending = [p for p in (marker_pid(S.C.notes('board.live')), control_server_live()) if p and plat.alive(p)]
    for p in ending:
        plat.terminate(p)
    end = time.monotonic() + OWN_WAIT
    while (ending := [p for p in ending if plat.alive(p)]) and time.monotonic() < end:
        time.sleep(0.25)
    for p in ending:
        say(f'stop: pid {p} did not end within {OWN_WAIT} s of SIGTERM; left running')
    while PAGE:
        try:
            PAGE.pop().stop()
        except Exception as e:  # noqa: BLE001 - the stop goes on
            say(f'run page: could not stop serving: {e}')
