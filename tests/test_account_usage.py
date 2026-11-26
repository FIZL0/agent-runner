#!/usr/bin/env python3
"""B848a: the last good usage reading is kept per login on disk: a failed fetch (429) keeps it, a fresh process
still has it and the cap holds; a window past its resets_at is dropped; another login reads none."""
from __future__ import annotations

import json
import os
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from _check import check, eq, report

from agent_runner import watch as W

tmp = Path(tempfile.mkdtemp())
home = tmp / 'home'
(home / '.claude').mkdir(parents=True)
(home / '.claude' / '.credentials.json').write_text(json.dumps({'claudeAiOauth': {'accessToken': 'SECRET'}}))
cfg = home / '.claude.json'
cfg.write_text(json.dumps({'oauthAccount': {'accountUuid': 'acct-1'}}))
good = {'five_hour': {'utilization': 40, 'resets_at': '2000-01-01T00:00:00Z'},
        'seven_day': {'utilization': 93, 'resets_at': '2999-01-01T00:00:00+00:00'}}


class Resp:
    def __init__(self, body): self.body = body
    def read(self, *a): return json.dumps(self.body).encode()


def fail(*a, **k):
    raise urllib.error.HTTPError('u', 429, 'Too Many Requests', {'Retry-After': '0'}, None)


env = {'HOME': str(home), 'XDG_STATE_HOME': str(tmp / 'state'), 'CLAUDE_CONFIG_DIR': ''}
with mock.patch.dict(os.environ, env), mock.patch('os.path.expanduser', lambda p: p.replace('~', str(home))):
    os.environ.pop('CLAUDE_CONFIG_DIR')
    W._account[:] = [-1e9, None]
    with mock.patch.object(urllib.request, 'urlopen', lambda *a, **k: Resp(good)):
        eq(W.account_usage()['seven_day']['utilization'], 93, 'a good read')
    kept = list((tmp / 'state' / 'agent-runner').iterdir())
    eq(len(kept), 1, 'one file kept')
    check('SECRET' not in kept[0].read_text(), 'the token is never kept')
    W._account[:] = [-1e9, None]  # a fresh process
    eq(W.known_usage()['seven_day']['utilization'], 93, 'a fresh process has the reading at once')
    with mock.patch.object(urllib.request, 'urlopen', fail):
        got = W.account_usage()
    eq(got['seven_day']['utilization'], 93, 'a 429 keeps the last good reading')
    check('five_hour' not in got, 'a window past its resets_at is dropped')
    eq(W.usage_pct('seven_day'), 93, 'the cap reads it')
    eq(W.usage_pct('five_hour'), None, 'the dropped window reads none')
    cfg.write_text(json.dumps({'oauthAccount': {'accountUuid': 'acct-2'}}))
    W._account[:] = [-1e9, None]
    with mock.patch.object(urllib.request, 'urlopen', fail):
        eq(W.account_usage(), None, 'another login reads none of the old account')
    W._account[:] = [-1e9, None]
raise SystemExit(report([]))
