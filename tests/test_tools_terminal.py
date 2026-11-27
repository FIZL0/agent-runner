#!/usr/bin/env python3
"""F466d: the Tools page's terminal: refused without the token or over plain http from another host, runs a command,
ends on idle and with 'End every terminal', and nothing typed is written anywhere (run.log included).

    python3 tests/test_tools_terminal.py        (a temp repo, real shells; a few seconds)
"""
from __future__ import annotations

import http.client
import json
import os
import sys
import tempfile
import time
from pathlib import Path

from _check import check, eq, git, report

os.environ['AGENT_RUNNER_KEYRING'] = 'off'
from agent_runner import devices as D, runner as R, state as S, tools_terminal as TT, web as W  # noqa: E402

MARK = 'zq' + 'secret466d'  # never in this file's text as one word, so a search of the disk finds only a leak


def op(op_: str, **a) -> dict:
    return D.post(json.dumps({'op': op_, **a}).encode(), S.C)[1]


def read_until(tid: str, want: str, at: int = 0, wait: float = 20) -> tuple[str, int]:
    got, end = '', time.monotonic() + wait
    while time.monotonic() < end:
        j = op('term_read', id=tid, at=at)
        if not j.get('ok'):
            break
        got += j['data']
        at = j['at']
        if want in got:
            break
        time.sleep(0.1)
    return got, at


def test_runs(tmp: Path) -> None:
    print('opens in the project or home, runs a command, ends')
    j = op('term_open', where='project')
    check(j.get('ok') and j.get('id'), 'opens', j)
    eq(Path(j['cwd']).resolve(), S.C.root.resolve(), 'in the main checkout')
    op('term_send', id=j['id'], data='pwd; echo $((40+2))\n')
    got, _ = read_until(j['id'], '42')
    check('42' in got and str(S.C.root.resolve()) in got, 'its output comes back', got[-300:])
    op('term_send', id=j['id'], data=f'echo {MARK[:2]}""{MARK[2:]}\n')
    got, _ = read_until(j['id'], MARK)
    check(MARK in got, 'what is typed runs')
    h = op('term_open', where='home')
    eq(Path(h['cwd']), Path.home(), 'or in $HOME')
    eq(D.page(S.C)['terminals'], 2, 'the page counts the open terminals')
    eq(op('term_close_all')['out'], '2 terminals ended', 'one button ends them all')
    eq(TT.count(), 0, 'none left')
    check(not op('term_read', id=j['id']).get('ok'), 'an ended terminal answers no more')
    print('nothing typed is written anywhere')
    leaks = []
    for d in (tmp, S.C.root):
        for f in d.rglob('*'):
            if f.is_file() and '.git' not in f.parts:
                try:
                    if MARK.encode() in f.read_bytes():
                        leaks.append(str(f))
                except OSError:
                    pass
    eq(leaks, [], 'not in run.log or any file')


def test_idle() -> None:
    print('ends on idle, or when its page stops asking')
    j = op('term_open', where='home')
    now = time.monotonic()
    eq(TT.sweep(now + 10), [], 'kept while in use')
    eq(TT.sweep(now + TT.GONE + 5), [j['id']], 'the tab closed: it ends')
    j = op('term_open', where='home')
    t = TT._terms[j['id']]
    t.seen = time.monotonic() + TT.IDLE  # the page still asks, but nothing is typed
    eq(TT.sweep(time.monotonic() + TT.IDLE + 5), [j['id']], '15 min with nothing typed: it ends')
    eq(TT.count(), 0, 'none left')


def test_rules() -> None:
    print('refused without the token, over plain http from another host, from another page')
    srv = W.serve('tok', 0, '127.0.0.1')
    port = srv.server_address[1]
    origin = f'http://127.0.0.1:{port}'

    def post(path: str, **h) -> tuple[int, dict]:
        c = http.client.HTTPConnection('127.0.0.1', port, timeout=30)
        c.request('POST', path, body=json.dumps({'op': 'term_open', 'where': 'home'}),
                  headers={'Content-Type': 'application/json', **{k.replace('_', '-'): v for k, v in h.items()}})
        r = c.getresponse()
        return r.status, json.loads(r.read() or b'{}')
    try:
        for path, h in (('/tools', dict(Origin=origin)), ('/tools?t=tok', dict(Origin='http://evil.example')),
                        ('/tools?t=tok', dict(Origin=origin, X_Forwarded_For='8.8.8.8')),
                        ('/tools?t=tok', dict(Host='box:80', Origin='http://box:80'))):
            eq((post(path, **h)[0], TT.count()), (403, 0), f'refused: {path} {h}')
        code, j = post('/tools?t=tok', Origin=origin)
        eq((code, j.get('ok'), TT.count()), (200, True, 1), 'the page on loopback may')
    finally:
        srv.stop()
        op('term_close_all')


def main() -> int:
    if os.name != 'posix':
        print('skipped: the terminal is POSIX only')
        return 0
    with tempfile.TemporaryDirectory() as tmp_:
        tmp = Path(tmp_).resolve()
        os.environ['AGENT_RUNNER_DEVICES'] = str(tmp / 'state')
        os.environ['AGENT_RUNNER_HOME_CONFIG'] = str(tmp / 'homecfg')
        repo = tmp / 'proj'
        (repo / 'plan').mkdir(parents=True)
        git(repo, 'init', '-q', '-b', 'main')
        (repo / 'plan/TODO.md').write_text('# TODO\n\n### Next\n\n- [ ] **T1** x | files: a.py\n', encoding='utf-8')
        (repo / 'plan/DONE.md').write_text('# DONE\n', encoding='utf-8')
        (repo / 'runner.toml').write_text('[run]\ntest = "true"\nmin_free_gb = 0\nremote = false\n', encoding='utf-8')
        git(repo, 'add', '-A')
        git(repo, 'commit', '-qm', 'start')
        R.init(repo)
        try:
            return report([lambda: test_runs(tmp), test_idle, test_rules])
        finally:
            TT.op_close_all({}, None)


if __name__ == '__main__':
    sys.exit(main())
