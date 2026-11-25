"""B807: a file written whole, and one change of it at a time, whatever process or thread writes it."""
from __future__ import annotations

import functools
import os
import time
import uuid
from pathlib import Path

from agent_runner import plat

LOCK_WAIT = 10.0  # s a change waits for the one before it; those take milliseconds


def write_whole(path: Path, data: bytes, mode: int | None = None) -> None:
    """Put `data` at `path` by way of a temp file of this call's own beside it, removed when that fails: two writers
    never share one, and a reader never sees half a file. `mode`: the file's permission bits."""
    tmp = path.with_name(f'{path.name}.{uuid.uuid4().hex}.tmp')
    try:
        tmp.write_bytes(data)
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass  # what failed first is the error to show
        raise


def _hold(lock: Path):
    """The open lock file; None when it cannot be had (a folder not writable, or held past LOCK_WAIT): the change
    is then made without it, as a person's command must not fail over the lock."""
    end = time.monotonic() + LOCK_WAIT
    try:
        lock.parent.mkdir(parents=True, exist_ok=True)
        while not (f := plat.lock(lock)):
            if time.monotonic() >= end:
                return None
            time.sleep(0.02)
    except OSError:
        return None
    return f


def one_change(lock_file):
    """A function that reads a file, changes it and writes it, run under the lock `lock_file()` names. Not
    re-entrant: one such function must not call another with the same lock."""
    def wrap(change):
        @functools.wraps(change)
        def locked(*args, **kw):
            f = _hold(lock_file())
            try:
                return change(*args, **kw)
            finally:
                if f:
                    f.close()
        return locked
    return wrap
