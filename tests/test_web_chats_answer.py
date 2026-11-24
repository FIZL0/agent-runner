"""The run page, chats area, answer buttons and picks (C46: split from test_web_chats.py), tests unchanged.

    python3 tests/test_web_chats_answer.py
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from _check import check, eq, git, report
from _trust import asked, trusted_checks

from agent_runner import config as CF  # noqa: E402
from agent_runner import state as S  # noqa: E402
from agent_runner import ui_model as U  # noqa: E402
from agent_runner import web as W  # noqa: E402
from _web import TODO, fake_repo, get, post, LOGIC_DRIVER, logic_js, in_tmp  # noqa: E402



def test_answer_button_b138(tmp: Path) -> None:
    """B138: a Needs you button through /act runs the plan command itself, never an AI session (SEND fails if
    called), and its ok result names the item gone; the page drops that item at once and keeps it off while a
    snapshot taken before the answer still lists it; a failed answer keeps it."""
    from agent_runner import plan as P
    fake_repo(tmp)
    P.block('F1', 'CONFIRM: check the board loads on your phone', todo=S.C.todo)

    def no_send(text):
        raise AssertionError(f'an answer button reached an AI session: {text!r}')
    ran = []
    token = W.web_token()
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {})
    url = f'http://127.0.0.1:{srv.server_address[1]}/act?t={token}'
    try:
        with mock.patch.object(U, 'RUN', [lambda argv: (ran.append(argv), (0, 'confirmed and ticked F1'))[1]]), \
                mock.patch.object(U, 'SEND', [no_send]):
            code, yes = post(url, {'name': 'run_control', 'args': {'key': 'need_yes', 'tid': 'F1', 'text': 'Yes'}})
            code, no = post(url, {'name': 'run_control', 'args': {'key': 'need_no', 'tid': 'F1', 'text': 'No'}})
    finally:
        srv.stop()
    eq(ran, [['plan', 'confirm', 'F1', 'Yes'], ['plan', 'change', 'F1', 'No: the check failed']],
       'Yes is plan confirm, No is plan change (reopened)')
    eq((yes['ok'], yes['said'], yes['gone']), (True, 'F1 ticked', 'F1'), 'the result says what was done')
    eq(no['said'], 'F1 reopened: the check failed', "No's words")
    page = W.PAGE.read_text(encoding='utf-8')
    check("if(S.f&&(it.args.note||it.args.why||(it.name==='answer'&&!it.args.button)))delete S.f['askre:'+it.need]" in page,
          'F162a: the reply box is emptied only of words that were sent', '')
    check("obCards(x=>x.need)" in page, 'the answer stands in Needs you while it is sent (F137)', '')
    if not shutil.which('node'):
        print('  (no node here: the page script test is skipped)')
        return
    needs = [{'id': 'F1'}, {'id': 'R6'}]
    got = logic_js([
        ['goneMark', {}, yes, 1000],
        ['needsShown', needs, {'F1': 1000}, 2000],
        ['needsShown', needs, {'F1': 1000}, 1000 + 31000],
        ['goneMark', {}, {'ok': False, 'out': 'plan: F1 is not waiting'}, 1000],
        ['answerSaid', yes, 'F1', 'Yes'],
    ])
    eq(got[0], {'F1': 1000}, 'an ok result marks the item answered')
    eq(got[1], [{'id': 'R6'}], 'the page drops it at once, and a stale snapshot keeps it off')
    eq(got[2], needs, 'a while later the run\'s own list counts again')
    eq(got[3], {}, 'a failed answer marks nothing: the item stays')
    eq(got[4], 'F1 ticked', 'the toast says what was done')


def test_pick_f138(tmp: Path) -> None:
    """F138: an option button's /pick link answers the item with no AI session and no page token: a good code
    confirms it (`plan confirm ID "go with B: <its name>"`) and is burnt; a reused, wrong or missing code is
    refused, and so is an item settled already. pick-links prints one link per option, with no token in them;
    with no https address it says so and prints none."""
    import io
    from contextlib import redirect_stderr, redirect_stdout
    from agent_runner import cmds, plan as P
    fake_repo(tmp)
    token = W.web_token()
    off = mock.patch.dict(os.environ, {'AGENT_RUNNER_HOME_CONFIG': str(tmp / 'no-home')})  # F167: not this machine's Home
    off.start()
    https = lambda port, t: [f'https://box.tail.ts.net:8771/?t={t}']
    cid, build = P.concept_shown('tabs or a drawer', 'https://claude.ai/artifact/k1', ['a.py'],
                                 todo=S.C.todo, done=S.C.done)
    copy = S.C.notes('concepts', f'{cid}.html')
    copy.parent.mkdir(parents=True, exist_ok=True)
    copy.write_text('<h1>Menu</h1><h2>A: tabs</h2><p>x</p><h2>B: drawer (recommended)</h2><p>y</p>', encoding='utf-8')
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.object(W, 'tailscale_https_urls', https), mock.patch.object(cmds, 'init', lambda: None), \
            redirect_stdout(out):
        rc = cmds.cmd_pick_links([cid, 'A,B,C'])
    eq(rc, 0, 'pick-links prints the links')
    lines = out.getvalue().split()
    eq(len(lines), 6, 'one link per option')
    eq([lines[0], lines[2], lines[4]], ['A', 'B', 'C'], 'each line names its option')
    link = lines[3]
    check(link.startswith(f'https://box.tail.ts.net:8771/pick?id={cid}&k=') and link.endswith('&o=B'),
          'a link is the run page https base /pick?id&k&o', link)
    check(token not in out.getvalue() and 't=' not in out.getvalue(), 'no page token in the links', out.getvalue())
    code = re.search(r'&k=([^&]+)', link)[1]
    eq(json.loads(W.pick_file(cid).read_text())['code'], code, 'the code is kept in .runner/pick-codes')
    check(code != token, 'the code is not the page token')
    with mock.patch.object(W, 'tailscale_https_urls', lambda port, t: []), mock.patch.object(cmds, 'init', lambda: None), \
            redirect_stdout(out), redirect_stderr(err):
        rc = cmds.cmd_pick_links([cid, 'A,B'])
    eq(rc, 1, 'no https address: no links')
    check('no https address' in err.getvalue(), 'and it says so', err.getvalue())
    ran = []
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {})
    base = f'http://127.0.0.1:{srv.server_address[1]}'

    def fake_run(argv):
        ran.append(argv)
        return 0, 'approved'
    try:
        with mock.patch.object(U, 'RUN', [fake_run]):
            c1, wrong = get(f'{base}/pick?id={cid}&o=B&k=nope')
            c2, tok = get(f'{base}/pick?id={cid}&o=B&k={token}')
            c3, ok = get(f'{base}{link[link.index("/pick"):]}')
            c4, again = get(f'{base}{link[link.index("/pick"):]}')
    finally:
        srv.stop()
    eq((c1, c2), (403, 403), 'a wrong code, or the page token, is refused')
    check(b'unknown' in wrong, 'and says the link is unknown', wrong)
    eq(c3, 200, 'the good code answers')
    eq(ran, [['plan', 'confirm', cid, 'go with B: drawer']], 'it runs plan confirm with the option name')
    check(b'Approved B (drawer)' in ok and f'the run starts {build}'.encode() in ok, 'and says what it did', ok)
    eq(c4, 409, 'the code is burnt: a second tap is refused')
    check(b'used already' in again, 'and says it was used', again)
    check(json.loads(W.pick_file(cid).read_text()).get('used'), 'the code file is marked used')
    # an item settled already
    P.block('F1', 'DECIDE: which colour', todo=S.C.todo)
    code1 = W.pick_code('F1')
    with mock.patch.object(U, 'need_label', lambda tid: ''):
        eq(W.pick('F1', 'A', code1)[0], 409, 'an item settled already is refused')
    eq(W.pick_code('F1'), code1, 'an unused code is kept for the next links')
    with mock.patch.object(U, 'RUN', [fake_run]):
        eq(W.pick('F1', 'A', code1)[0], 200, 'a DECIDE answers too')
    eq(ran[-1], ['plan', 'confirm', 'F1', 'go with A'], 'with its option')
    check(W.pick_code('F1') != code1, 'once used, new links get a new code')
    eq(W.pick('../x', 'A', code1)[0], 403, 'a bad id is unknown')
    eq(W.pick('F1', '', '')[0], 403, 'no code: unknown')
    off.stop()


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_answer_button_b138), in_tmp(test_pick_f138)]))
