"""B161: one sender at a time types into a session's inbox."""

from __future__ import annotations

import functools
import time
from pathlib import Path

from agent_runner import plat

LOCK_WAIT = 30.0  # s a sender waits for the one before it to finish


def one_sender(send):
    """`send(inbox, …)` under a lock of that inbox, so a paste and its Enter are never split by another sender (the
    run page, the TUI and the feed are separate processes: a file lock). False when the sender before has it for
    LOCK_WAIT s. Windows needs none: the inbox is a pipe that takes one sender at a time (`conpty.pipe_send`)."""
    @functools.wraps(send)
    def locked(inbox: Path, *args) -> bool:
        if plat.WINDOWS:
            return send(inbox, *args)
        end = time.monotonic() + LOCK_WAIT
        try:
            while not (f := plat.lock(inbox.with_name(inbox.name + '.lock'))):
                if time.monotonic() >= end:
                    return False
                time.sleep(0.02)
        except OSError:  # no such directory: the session has ended
            return False
        with f:
            return send(inbox, *args)
    return locked
