#!/usr/bin/env python3
"""B97: `upgrade_argv` picks the upgrade command by where agent_runner itself lives, not by sys.prefix.

    python3 tests/test_watch.py        (no network; a temp folder; well under a second)

A wrapper (openmx's ./kit) runs the system python3 with uv's site-packages on sys.path: sys.prefix is /usr,
and the old test fell through to `git -C …/site-packages pull`, which fails with exit 128. Now a clone (a .git
beside agent_runner/) pulls, a pipx install upgrades with pipx, and any other install with uv tool, wherever
UV_TOOL_DIR put it.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

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


def test_breaking() -> None:
    """C28: 0.60.0 dropped tmux, so a run below it never restarts (or auto-upgrades) onto 0.60+."""
    eq(W.breaking('0.59.3', '0.60.0'), True, '0.59 -> 0.60 refused: its tmux sessions cannot be adopted')
    eq(W.breaking('0.41.0', '0.62.1'), True, 'from further back across 0.60 too')
    eq(W.breaking('0.60.0', '0.61.0'), False, '0.60 -> 0.61 restarts by itself')
    eq(W.breaking('0.58.0', '0.59.1'), False, '0.58 -> 0.59 restarts by itself')
    eq(W.breaking('0.61.0', '1.0.0'), True, 'a major version still breaks')
    eq(W.auto_upgrade_due('0.60.0', '0.59.0', '0.59.0', False, ''), False, 'no auto upgrade from 0.59 onto 0.60')
    eq(W.auto_upgrade_due('0.61.0', '0.60.0', '0.60.0', False, ''), True, 'auto upgrade from 0.60 onto 0.61')


def test_claude_login() -> None:
    """F126: an ending, ended or missing Claude login, from a fake credentials file."""
    from agent_runner import status as R, tui as T, ui_model as U
    now, day = 1_800_000_000.0, 86400
    off = ('ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_BASE_URL', 'CLAUDE_CODE_OAUTH_TOKEN',
           'CLAUDE_CODE_USE_BEDROCK', 'CLAUDE_CODE_USE_VERTEX', 'CLAUDE_CODE_USE_FOUNDRY')
    with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {'CLAUDE_CONFIG_DIR': d}), \
            mock.patch.object(sys, 'platform', 'linux'), mock.patch.object(W, 'C', mock.Mock(run={'agent': 'claude'})):
        for k in off:
            os.environ.pop(k, None)
        f = Path(d) / '.credentials.json'

        def given(left: float | None, **kw) -> str:
            o = {'accessToken': 'a', 'refreshToken': 'r', 'expiresAt': (now - day) * 1000, **kw}
            if left is not None:
                o['refreshTokenExpiresAt'] = int((now + left) * 1000)
            f.write_text(json.dumps({'claudeAiOauth': o}), encoding='utf-8')
            return W.claude_login(now)

        none = 'No Claude login: log in'
        eq(W.claude_login(now), none, 'no file')
        eq(given(7 * day), '', 'far away, the access token past: nothing')
        eq(given(3 * day), '', '3 days: not under 3 days')
        eq(given(3 * day - 1), 'Claude login expires in 2 days: log in again', 'under 3 days')
        eq(given(1.5 * day), 'Claude login expires in 1 day: log in again', 'one day')
        eq(given(5 * 3600), 'Claude login expires in 5 hours: log in again', 'hours')
        eq(given(60), 'Claude login expires in under 1 hour: log in again', 'minutes')
        eq(given(0), 'Claude login has expired: log in again', 'now')
        eq(given(-day), 'Claude login has expired: log in again', 'past')
        eq(given(None), '', 'no refreshTokenExpiresAt: cannot tell')
        eq(given(7 * day, refreshToken=''), none, 'no token')
        for bad in ('{}', 'null', 'no json', '{"claudeAiOauth": null}'):
            f.write_text(bad, encoding='utf-8')
            eq(W.claude_login(now), none, f'missing: {bad}')
        with mock.patch.object(sys, 'platform', 'darwin'):
            f.unlink()
            eq(W.claude_login(now), '', 'macOS: in the Keychain')

        given(-day)
        for k in ('ANTHROPIC_API_KEY', 'CLAUDE_CODE_OAUTH_TOKEN'):
            with mock.patch.dict(os.environ, {k: 'x'}):
                eq(W.claude_login(now), '', f'{k}: no login to renew')
        eq(W.claude_login(now, agent='other'), '', 'another agent')
        (Path(d) / 'settings.json').write_text('{"apiKeyHelper": "key"}', encoding='utf-8')
        eq(W.claude_login(now), '', 'an apiKeyHelper')
        (Path(d) / 'settings.json').unlink()

        with mock.patch.object(W.time, 'time', lambda: now):
            line = W.claude_login_line()
            eq(line, 'Claude login has expired: log in again (claude auth login)', 'the line names the command')
            with mock.patch.object(U, 'no_settings', lambda **kw: ''), \
                    mock.patch.object(U, 'unpushed_line', lambda: ''):
                check(line in U.status_rows(False, {}, ''), 'the TUI status pane has it')
                eq(T.RunPage.row(None, 1, line)[0][1], 'yellow', 'as a warning')
                given(7 * day)
                check(not any('login' in x for x in U.status_rows(False, {}, '')), 'far away: no line')
            eq(W.claude_login_line(), '', 'far away: nothing for status')
        with mock.patch.object(R, 'no_gate_line', lambda: ''), mock.patch.object(R.pitch, 'waiting_line', lambda: ''), \
                mock.patch('agent_runner.control_held.lines', lambda: []):
            eq(R.status_text(False, {}, [], {}, 0.0, login=line), f'no run is up\n{line}', 'status has it')


if __name__ == '__main__':
    sys.exit(report([test_by_file, test_breaking, test_claude_login]))
