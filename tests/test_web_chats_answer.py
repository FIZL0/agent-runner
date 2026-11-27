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
    refused. C40b: a concept's link changes nothing and says to pick in Concepts."""
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
    code = W.pick_code(cid)
    link = f'/pick?id={cid}&k={code}&o=B'
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
    eq(c3, 410, 'C40b: an old concept link answers with a short page')
    check(b'pick in Concepts' in ok, 'saying to pick in Concepts', ok)
    eq(ran, [], 'and changes nothing')
    eq(c4, 410, 'again')
    check(not json.loads(W.pick_file(cid).read_text()).get('used'), 'the code is not burnt')
    eq(W.pick('../x', 'A', code)[0], 403, 'a bad id is unknown')
    eq(W.pick('F1', '', '')[0], 403, 'no code: unknown')
    off.stop()


def test_option_queue_f192d1(tmp: Path) -> None:
    """F192d1: /live gives each option's count of stored tasks; POST /queue adds the chosen option's tasks once, a
    double tap adds nothing, one chat line says what was queued, and nothing goes to Claude."""
    from agent_runner import option_tasks, session_now
    from agent_runner import plan as P
    fake_repo(tmp)
    q = 'Which board layout should the run app use?'
    option_tasks.store(q, {'Wide': [['F', 'wide board', '--files', 'a.py'], ['T', 'wide board tests']], 'Narrow': []}, 'q1')
    ask = {'id': 'x1', 'question': q, 'options': [{'name': 'Wide', 'rec': True}, {'name': 'Narrow', 'rec': False}]}
    added = []

    def no_send(text):
        raise AssertionError(f'a tap reached Claude: {text!r}')
    token = W.web_token()
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {})
    base = f'http://127.0.0.1:{srv.server_address[1]}'
    try:
        with mock.patch.object(session_now, 'live', lambda n: {'ok': True, 'ask': ask, 'asks': [ask]}), \
                mock.patch.object(P, 'main', lambda a: added.append(a) or 0), \
                mock.patch.object(U, 'SEND', [no_send]):
            code, live = get(f'{base}/live/c3?t={token}')
            live = json.loads(live)
            body = {'chat': 'c3', 'question': q, 'option': 'Wide'}
            c1, one = post(f'{base}/queue?t={token}', body)
            c2, two = post(f'{base}/queue?t={token}', body)
            c3, bad = post(f'{base}/queue?t={token}', {'chat': 'nope', 'question': q, 'option': 'Wide'})
    finally:
        srv.stop()
    eq(code, 200, '/live answers')
    eq(live['ask']['tasks'], {'Wide': 2}, 'the counts: an option without tasks is left out')
    eq(live['asks'][0]['tasks'], {'Wide': 2}, 'each of asks too')
    eq((c1, one['ok'], one['queued']), (200, True, 2), 'a tap queues the tasks')
    eq(len(added), 2, 'both added')
    eq((c2, two['ok']), (200, False), 'a double tap adds nothing')
    eq(len(added), 2, 'still two')
    eq(bad['ok'], False, 'not a chat: refused')
    lines = U.queued_lines('c3')
    eq(len(lines), 1, 'one chat line')
    check('queued 2 tasks' in lines[0]['text'] and 'wide board' in lines[0]['text'], 'it says what was queued', lines)


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_answer_button_b138), in_tmp(test_pick_f138), in_tmp(test_option_queue_f192d1)]))
