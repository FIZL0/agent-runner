#!/usr/bin/env python3
"""B850a: a key a command leaves in KEYS is taken within about a second, while the loop naps and while it is in a long
pass, once only, and STATE says so right after.

    python3 tests/test_key_wake.py          (a temp repo; seconds)
"""
from __future__ import annotations

import json
import sys
import subprocess
import tempfile
import threading
import time
from types import SimpleNamespace

from _check import check, eq, report

from agent_runner import loop, state as S, stop_now  # noqa: E402
from agent_runner import runner as R  # noqa: E402


def state() -> dict:
    try:
        return json.loads(S.C.notes('STATE').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def until(test, limit: float = 1.0) -> float | None:
    t0 = time.monotonic()
    while time.monotonic() - t0 < limit:
        if test():
            return time.monotonic() - t0
        time.sleep(0.02)
    return None


def test_keys() -> None:
  with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
    subprocess.run(['git', 'init', '-q', d], check=True)
    R.init(d)
    S.C.notes('x').parent.mkdir(parents=True, exist_ok=True)
    run = SimpleNamespace(running={}, held_merges=[])
    stop_now.ON_KEYS[:] = [lambda: (loop.take_keys(), loop.write_state(dict(run.running), []), loop.WAKE.set())]
    threading.Thread(target=stop_now.watch, args=(run,), daemon=True).start()

    # in its nap: the key is taken and STATE written within a second
    loop.send_key('p on')
    took = until(lambda: state().get('paused') is True)
    check(took is not None, f'p on while napping: paused in STATE in {took}s')
    eq(S.C.notes('KEYS').read_text(encoding='utf-8').strip() if S.C.notes('KEYS').exists() else '', '',
       'the key is taken once: KEYS is empty after')

    # in a long pass (the loop's thread busy, not napping): still taken
    busy = threading.Event()

    def long_pass():
        busy.set()
        time.sleep(2)

    threading.Thread(target=long_pass, daemon=True).start()
    busy.wait(1)
    loop.send_key('p off')
    took = until(lambda: state().get('paused') is False)
    check(took is not None, f'p off in a busy pass: unpaused in STATE in {took}s')
    loop.send_key('f on')
    check(until(lambda: state().get('forced') is True) is not None, 'f on: forced in STATE')
    loop.send_key('slots 3')
    check(until(lambda: state().get('slots') == 3) is not None, 'slots 3: in STATE')
    check(stop_now.waiting() is False, 'nothing left waiting')

sys.exit(report([test_keys]))
