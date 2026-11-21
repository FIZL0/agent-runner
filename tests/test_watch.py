#!/usr/bin/env python3
"""B97: `upgrade_argv` picks the upgrade command by where agent_runner itself lives, not by sys.prefix.

    python3 tests/test_watch.py        (no network, no repo; well under a second)

A wrapper (openmx's ./kit) runs the system python3 with uv's site-packages on sys.path: sys.prefix is /usr,
and the old test fell through to `git -C …/site-packages pull`, which fails with exit 128.
"""
from __future__ import annotations

import sys
from pathlib import Path

from _check import check, eq, report

from agent_runner import watch as W  # noqa: E402

UV = '/home/u/.local/share/uv/tools/agent-runner/lib/python3.13/site-packages/agent_runner/watch.py'
PIPX = '/home/u/.local/share/pipx/venvs/agent-runner/lib/python3.13/site-packages/agent_runner/watch.py'
CLONE = '/home/u/repos/agent-runner/agent_runner/watch.py'


def test_by_file() -> None:
    real = sys.prefix
    sys.prefix = '/usr'  # the wrapper: system python3, whatever site-packages it put on sys.path
    try:
        eq(W.upgrade_argv(UV), ['uv', 'tool', 'upgrade', 'agent-runner'], 'uv tool install under a wrapper')
        eq(W.upgrade_argv(PIPX), ['pipx', 'upgrade', 'agent-runner'], 'pipx install under a wrapper')
        eq(W.upgrade_argv(CLONE), ['git', '-C', '/home/u/repos/agent-runner', 'pull', '-q', '--ff-only'],
           'a clone pulls in its own root')
    finally:
        sys.prefix = real
    sys.prefix = '/home/u/.local/share/uv/tools/agent-runner'
    try:
        eq(W.upgrade_argv(CLONE)[0], 'git', 'a clone run by a uv python still pulls')
    finally:
        sys.prefix = real
    here = W.upgrade_argv()
    check(here[0] == 'git' and here[2] == str(Path(W.__file__).resolve().parents[1]),
          f'this checkout pulls in itself: {here}')


if __name__ == '__main__':
    sys.exit(report([test_by_file]))
