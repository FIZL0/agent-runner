#!/usr/bin/env python3
"""F488: [run] usage_limits = false switches the usage caps off: usage at 100% starts tasks with no hold, no
fallback and no ask, status hides the caps, and settings lists the key."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _check import eq, check, report  # noqa: E402

from agent_runner import cap_hold, config, fallback as FB, loop, state, status  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix='ar-caphold-'))
FULL = {'five_hour': {'utilization': 100}, 'seven_day': {'utilization': 100}}


def run_cfg(on: bool) -> dict:
    return {'usage_limits': on, 'session_max': 90, 'weekly_max': 90}


def test_switch():
    check(cap_hold.limits_on({}), 'default: on')
    check(not cap_hold.limits_on({'usage_limits': False}), 'false: off')
    eq(config.DEFAULTS['run']['usage_limits'], True, 'the default is on')
    check('usage_limits = true' in config.settings_reference('run'), 'settings lists the key')


def test_loop_no_hold():
    old = state.C
    try:
        for on, want in ((True, True), (False, False)):
            loop.C = state.C = SimpleNamespace(run=run_cfg(on))
            with mock.patch('agent_runner.loop.usage_pct', lambda k: 100), \
                    mock.patch('agent_runner.claude_use.account', lambda c: True):
                eq(loop.capped(False) is not None, want, f'usage_limits={on}: held at 100%')
    finally:
        loop.C = state.C = old


def test_status_hidden():
    old = state.C
    st = {'usage': {'five_hour': 100, 'seven_day': 100}}
    try:
        state.C = SimpleNamespace(run=run_cfg(True))
        check(status.cap_held_line(st, 0), 'on: the held line shows')
        state.C = SimpleNamespace(run=run_cfg(False))
        eq(status.cap_held_line(st, 0), '', 'off: no held line')
    finally:
        state.C = old


def test_fallback_no_login_hold():
    logins = TMP / 'logins.json'
    logins.write_text(json.dumps({'logins': [{'name': 'work', 'dir': ''}, {'name': 'home', 'dir': str(TMP / 'h')}]}))
    old = state.C
    try:
        state.C = SimpleNamespace(run=run_cfg(False), notes=lambda n: TMP / n, fallback=[], command='run')
        with mock.patch.dict(os.environ, {'AGENT_RUNNER_LOGINS': str(logins)}), \
                mock.patch('agent_runner.watch.login_usage', lambda d: FULL):
            eq(FB.usage_held_logins(), frozenset(), 'off: no login held by its usage')
            state.C.run = run_cfg(True)
            eq(FB.usage_held_logins(), frozenset({'claude@home'}), 'on: the login at 100% is held')
    finally:
        state.C = old


if __name__ == '__main__':
    try:
        sys.exit(report([test_switch, test_loop_no_hold, test_status_hidden, test_fallback_no_login_hold]))
    finally:
        shutil.rmtree(TMP, True)
