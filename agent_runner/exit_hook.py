"""B801: `[run] on_exit`, run once each time a slot's session ends: by itself (`Run.reap`), or stopped by a drop, a
`plan change --restart` or a take back (`loop.halts`). It runs beside the loop, and nothing starts in its slot until it
has ended (`Run.held`): it may free a lock by AGENT_SLOT, which the slot's next task could have just taken."""
from __future__ import annotations

import os
import signal
import subprocess as sp
import time

from agent_runner import plat, slots, state

GOING: list[tuple[int, sp.Popen, float, str]] = []  # (slot, process, when it is stopped, command)
SOON = 5.0  # s a halt waits for it, so a quick one ends before the worktree is reset and the task starts again


def start(n: int) -> None:
    """Run `[run] on_exit` in slot n's worktree with the slot's env, for at most `[run] command_timeout`. Its output
    goes nowhere: a pipe would be held open by whatever it leaves in the background."""
    cmd, d = state.C.run['on_exit'], state.SLOTS_DIR / f's{n}'
    if not cmd or not d.is_dir():
        return
    p = sp.Popen(cmd, shell=True, cwd=str(d), env={**os.environ, **slots.env_vars(slots.slot_env(n))},
                 stdin=sp.DEVNULL, stdout=sp.DEVNULL, stderr=sp.DEVNULL, start_new_session=not plat.WINDOWS)
    GOING.append((n, p, time.monotonic() + state.C.run['command_timeout'], cmd))


def busy() -> set[int]:
    """The slots whose `on_exit` still runs; one past its time is stopped here, and logged."""
    for hook in list(GOING):
        n, p, end, cmd = hook
        if p.poll() is None and time.monotonic() < end:
            continue
        GOING.remove(hook)
        if p.returncode is None:
            stop(p)
            state.log(f'slot {n}: on_exit: `{cmd}` ran past [run] command_timeout '
                      f'({state.C.run["command_timeout"]}s); stopped')
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
