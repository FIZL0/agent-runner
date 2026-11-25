"""B801: `[run] on_exit`, run once each time a slot's session ends: by itself (`Run.reap`), or stopped by a drop, a
`plan change --restart`, a take back or a cancel (`loop.halts`), or by `s!` (`loop.end_sessions`, B803), after which it goes on without the run (B827). It runs beside the loop, and nothing starts in its slot until it
has ended (`Run.held`): it may free a lock by AGENT_SLOT, which the slot's next task could have just taken."""
from __future__ import annotations

import json
import os
import signal
import subprocess as sp
import threading
import time

from agent_runner import plat, slots, state

GOING: list[tuple[int, sp.Popen, float, str, str]] = []  # (slot, process, when it is stopped, command, why then)
SOON = 5.0  # s a halt waits for it, so a quick one ends before the worktree is reset and the task starts again
FORCED = 2.0  # s a session ended by `s!` gets after SIGTERM


def gone(pid: int, seconds: float) -> bool:
    end = time.monotonic() + seconds
    while plat.alive(pid) and time.monotonic() < end:
        time.sleep(0.2)
    return not plat.alive(pid)


def end_session(pid: int, seconds: float = 10) -> None:
    """End a halted task's session before its `on_exit` starts, which must not free what the session still uses."""
    plat.terminate(pid)
    if gone(pid, seconds):
        return
    for p in [*(plat.descendants(pid) if plat.WINDOWS else []), pid]:  # it ignored SIGTERM: its tree gets one
        plat.terminate(p)
    if not gone(pid, 2) and not plat.WINDOWS:
        try:
            os.kill(pid, signal.SIGKILL)  # what it started is ended after it (watch.end_orphans)
        except OSError:
            pass


def end_all(pids: list[int]) -> None:
    """B803: `s!`: end these sessions side by side, so ones that ignore SIGTERM cost their wait once."""
    ending = [threading.Thread(target=end_session, args=(pid, FORCED), daemon=True) for pid in pids]
    for t in ending:
        t.start()
    end = time.monotonic() + FORCED + 3  # B827: one that will not end does not hold the exit
    for t in ending:
        t.join(max(0, end - time.monotonic()))


def end_forced(procs: dict, orphans) -> None:
    """B803: `s!`: end every session; with an `on_exit`, they and what they left (`orphans`) are gone before it starts."""
    pids = [pid for pid, *_ in procs.values()]
    end_all(pids)
    if pids and state.C.run['on_exit']:
        orphans()


def start_forced(procs: dict) -> None:
    """B803: `s!`: run `on_exit` in the ended sessions' slots (a cut-off session resumes after it too). B827: nothing
    waits for one; the next run holds its slot while it still runs (`adopt`)."""
    for n in procs:
        start(n)
    left = [{'slot': n, 'pid': p.pid, 'start': plat.started(p.pid), 'until': time.time() + end - time.monotonic(),
             'cmd': cmd, 'why': why} for n, p, end, cmd, why in GOING if p.poll() is None]
    if left:
        state.C.notes(LEFT).write_text(json.dumps(left), encoding='utf-8')


LEFT = 'on_exit.json'  # what a stop now left running


class Left:
    """An `on_exit` that an earlier run started, as the Popen the rest of this module reads."""

    def __init__(self, pid: int, start: str | None):
        self.pid, self.start, self.returncode = pid, start, None

    def poll(self) -> int | None:
        if self.returncode is None and not (plat.alive(self.pid) and plat.started(self.pid) == self.start):
            self.returncode = 0
        return self.returncode

    def wait(self, seconds: float) -> None:
        end = time.monotonic() + seconds
        while self.poll() is None and time.monotonic() < end:
            time.sleep(0.05)


def adopt() -> None:
    """B827: a run's start: an `on_exit` a stop now left running holds its slot until it ends, or is past its time."""
    f = state.C.notes(LEFT)
    try:
        for r in json.loads(f.read_text(encoding='utf-8')):
            p = Left(r['pid'], r['start'])
            if p.poll() is None:
                GOING.append((r['slot'], p, time.monotonic() + r['until'] - time.time(), r['cmd'], r['why']))
    except (OSError, ValueError, KeyError, TypeError):
        pass
    f.unlink(missing_ok=True)


def start(n: int) -> None:
    """Run `[run] on_exit` in slot n's worktree with the slot's env, for at most `[run] command_timeout`. Its output
    goes nowhere: a pipe would be held open by whatever it leaves in the background."""
    cmd, d = state.C.run['on_exit'], state.SLOTS_DIR / f's{n}'
    if not cmd or not d.is_dir():
        return
    p = sp.Popen(cmd, shell=True, cwd=str(d), env={**os.environ, **slots.env_vars(slots.slot_env(n))},
                 stdin=sp.DEVNULL, stdout=sp.DEVNULL, stderr=sp.DEVNULL, start_new_session=not plat.WINDOWS)
    limit = state.C.run['command_timeout']
    GOING.append((n, p, time.monotonic() + limit, cmd, f'ran past [run] command_timeout ({limit}s)'))


def busy() -> set[int]:
    """The slots whose `on_exit` still runs; one past its time is stopped here, and logged."""
    for hook in list(GOING):
        n, p, end, cmd, why = hook
        if p.poll() is None and time.monotonic() < end:
            continue
        GOING.remove(hook)
        if p.returncode is None:
            stop(p)
            state.log(f'slot {n}: on_exit: `{cmd}` {why}; stopped')
    return {n for n, *_ in GOING}


def stop(p: sp.Popen) -> None:
    """End the command and what it started."""
    if plat.WINDOWS:
        plat.terminate(p.pid)
    else:
        try:
            os.killpg(p.pid, signal.SIGKILL)  # its own session, so its own group
        except OSError:
            pass
    try:
        p.wait(5)
    except sp.TimeoutExpired:
        pass


def wait(n: int, seconds: float | None = None) -> bool:
    """Wait up to `seconds` (SOON) for slot n's `on_exit`: True when none runs any more."""
    end = time.monotonic() + (SOON if seconds is None else seconds)
    while n in busy():
        if time.monotonic() >= end:
            return False
        time.sleep(0.05)
    return True
