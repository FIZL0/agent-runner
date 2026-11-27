"""F497: put a freshly written STATE in place, even on Windows while a reader has it open.

On Windows `os.replace` onto a file another process holds open raises PermissionError. The run page and
`status` read STATE many times a second, so one try per pass could fail pass after pass and STATE kept an
old `running` (issue #5). Retry a short while, then write the file in place as a last resort.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

TRIES = 20
PAUSE = 0.025  # s between tries


def put_in_place(tmp: Path, dest: Path, tries: int = TRIES, pause: float = PAUSE, replace=os.replace) -> bool:
    """Move `tmp` onto `dest`; True once `dest` holds its text."""
    for _ in range(max(1, tries)):
        try:
            replace(tmp, dest)
            return True
        except OSError:
            time.sleep(pause)
    try:  # a reader keeps the name busy: write over its content instead (Windows allows that with share-read)
        dest.write_bytes(tmp.read_bytes())
    except OSError:
        return False
    try:
        tmp.unlink()
    except OSError:
        pass
    return True
