#!/usr/bin/env python3
"""B879: cut-off gates don't count toward done's failed-gate cap, and a capped --blocked done whose gate passes ends done."""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace

from _check import eq, check, report


def test_cut_offs_then_pass_ends_done():
    print('B879: 2 cut-off + 2 failed gates, then a pass on a --blocked done, ends done')
    from agent_runner.done import MAX_FAILS, cut_off, fails, fails_file, last_fail, unblock_on_pass
    with tempfile.TemporaryDirectory() as t:
        cwd = Path(t)
        subprocess.run(['git', 'init', '-q'], cwd=cwd, check=True)
        for rc in (124, -9, 1, 1):
            if not cut_off(rc):
                fails(cwd, 'X1', add=True, content='h')
        eq(last_fail(fails_file(cwd, 'X1'))[0], 2, 'only the two real failures count')
        check(not cut_off(1) and cut_off(None) and cut_off(137), 'cut-off exits told apart')
        fails(cwd, 'X1', add=True, content='h')
        capped = last_fail(fails_file(cwd, 'X1'))[0] >= MAX_FAILS
        check(capped, 'three real failures reach the cap')
        a = SimpleNamespace(blocked='gate failed 3 times', after=None, until=None)
        check(unblock_on_pass(a, capped, 'test', False), 'a passing gate drops the block')
        eq(a.blocked, None, 'marked done, not blocked')
        d = SimpleNamespace(blocked='DECIDE: which? [A / B]', after=None, until=None)
        check(not unblock_on_pass(d, capped, 'test', False), 'a DECIDE block stays')
        u = SimpleNamespace(blocked='waits', after=None, until=None)
        check(not unblock_on_pass(u, False, 'test', False), 'an uncapped block stays')


if __name__ == '__main__':
    raise SystemExit(report([test_cut_offs_then_pass_ends_done]))
