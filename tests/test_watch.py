#!/usr/bin/env python3
"""B97: `upgrade_argv` picks the upgrade command by where agent_runner itself lives, not by sys.prefix.

    python3 tests/test_watch.py        (no network; a temp folder; well under a second)

A wrapper (openmx's ./kit) runs the system python3 with uv's site-packages on sys.path: sys.prefix is /usr,
and the old test fell through to `git -C …/site-packages pull`, which fails with exit 128. Now a clone (a .git
beside agent_runner/) pulls, a pipx install upgrades with pipx, and any other install with uv tool, wherever
UV_TOOL_DIR put it.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from _check import check, eq, report

from agent_runner import watch as W  # noqa: E402

UV = ['uv', 'tool', 'upgrade', 'agent-runner']


def make(root: Path, rel: str, git: bool = False) -> Path:
    """agent_runner/watch.py at `rel` under `root`, with a .git beside agent_runner/ when `git`."""
    f = root / rel / 'agent_runner' / 'watch.py'
    f.parent.mkdir(parents=True)
    f.write_text('', encoding='utf-8')
    if git:
        (root / rel / '.git').mkdir()
    return f


def test_by_file() -> None:
    real = sys.prefix
    sys.prefix = '/usr'  # the wrapper: system python3, whatever site-packages it put on sys.path
    try:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            uv = make(root, '.local/share/uv/tools/agent-runner/lib/python3.13/site-packages')
            moved = make(root, 'tools/agent-runner/lib/python3.13/site-packages')
            pipx = make(root, '.local/share/pipx/venvs/agent-runner/lib/python3.13/site-packages')
            clone = make(root, 'repos/uv/agent-runner', git=True)
            eq(W.upgrade_argv(uv), UV, 'uv tool install under a wrapper')
            eq(W.upgrade_argv(moved), UV, 'uv tool install under UV_TOOL_DIR, no uv in its path')
            eq(W.upgrade_argv(pipx), ['pipx', 'upgrade', 'agent-runner'], 'pipx install under a wrapper')
            eq(W.upgrade_argv(clone), ['git', '-C', str((root / 'repos/uv/agent-runner').resolve()), 'pull', '-q',
                                       '--ff-only'], 'a clone pulls in its own root, even under a folder named uv')
    finally:
        sys.prefix = real
    here = Path(W.__file__).resolve().parents[1]
    if (here / '.git').exists():
        eq(W.upgrade_argv()[:3], ['git', '-C', str(here)], 'this checkout pulls in itself')
    check(W.upgrade_argv()[0] != 'git' or 'site-packages' not in W.upgrade_argv()[2], 'never a pull in site-packages')


if __name__ == '__main__':
    sys.exit(report([test_by_file]))
