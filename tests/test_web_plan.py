"""The run page, plan area (agent_runner/page/*-plan.*): split from test_web.py (C41b), tests unchanged.

    python3 tests/test_web_plan.py
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
from test_web_sheet import DOM  # noqa: E402
from _web import TODO, fake_repo, get, post, LOGIC_DRIVER, logic_js, in_tmp  # noqa: E402


def test_real_action(tmp: Path) -> None:
    """One action through the real runner: plan add lands in TODO.md."""
    repo = fake_repo(tmp)
    token = W.web_token()
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {})
    try:
        code, out = post(f'http://127.0.0.1:{srv.server_address[1]}/act?t={token}', {
            'name': 'plan_add', 'args': {'kind': 'F', 'text': 'Run page shows usage', 'files': 'web.py'}})
        check(out.get('ok'), 'the real plan add ran', out)
        check('Run page shows usage' in (repo / 'plan' / 'TODO.md').read_text(encoding='utf-8'),
              'and the task is in TODO.md')
    finally:
        srv.stop()


def test_run_controls(tmp: Path) -> None:
    """F82: the run controls on the web: the page builds each control's request from the snapshot's one list
    (ui_model.RUN_CONTROLS), the server runs its runner command, and stop now runs only with the page's own
    confirm (no browser dialog)."""
    fake_repo(tmp)
    page = W.PAGE.read_text(encoding='utf-8')
    for part in ('controlsCard()', 'Run controls', 'data-ctl=', 'data-tid=', 'data-sure', 'data-unsure',
                 'data-slots-n', 'controlReq(c,'):
        check(part in page, f'the page has {part}')
    for gone in ('confirm(', 'alert(', 'prompt('):
        check(gone not in page, f'the page uses no {gone}) dialog')
    want = {'slot_add': ['slots', '+1'], 'slot_remove': ['slots', '-1'], 'slots_set': ['slots', '4'],
            'pause': ['pause'], 'go_on': ['pause', '--off'], 'force': ['force'], 'caps_on': ['force', '--off'],
            'stop': ['stop'], 'stop_now': ['stop', '--force'], 'stop_undo': ['stop', '--undo'],
            'task_drop': ['plan', 'drop', 'F1', U.TASK_DROP_WHY],
            'upgrade': ['key', 'u'], 'suspend': ['key', 'z'], 'shutdown': ['key', 'x'],  # C26
            'restart': ['key', 'restart'], 'start': [], 'resume': ['resume', 'F1'],  # F124
            'unclaim': ['plan', 'unclaim', 'F1'], 'wip_show': ['wip', 'show', 'main-checkout-1'],
            'wip_restore': ['wip', 'restore', 'main-checkout-1'], 'wip_drop': ['wip', 'drop', 'main-checkout-1']}
    tid = lambda c: 'main-checkout-1' if c['fix'] == 'wip' else 'F1'  # noqa: E731
    cs = [c for c in U.controls() if c['where'] in ('run', 'task')]  # C34: the row actions: test_row_actions
    if shutil.which('node'):
        reqs = logic_js([['controlReq', c, {'n': ' 4', 'tid': tid(c), 'sure': True}] for c in cs] +
                        [['controlReq', U.run_control_of('stop_now') | {'needs': '', 'confirm': U.STOP_NOW_ASK},
                          {'tid': 'F1'}]])
    else:
        print('  (no node here: the page requests are built in Python instead)')
        reqs = [{'name': 'run_control', 'args': {'key': c['key'], **({'n': '4'} if c['needs'] == 'n' else {}),
                                                  **({'tid': tid(c)} if c['needs'] in ('id', 'pick') else {}),
                                                  **({'confirm': True} if c['confirm'] else {})}} for c in cs] + \
            [{'name': 'run_control', 'args': {'key': 'stop_now'}}]
    if shutil.which('node'):
        stop_now = next(c for c in cs if c['key'] == 'stop_now')
        got = logic_js([['controlClick', stop_now, {}], ['controlClick', stop_now, {'sure': 'yes'}],
                        ['controlClick', stop_now, {'sure': True}],
                        ['controlClick', next(c for c in cs if c['key'] == 'stop'), {}],
                        *[['taskControlsOn', {**r, 'task_controls': U.task_controls_on(r)}] for r in (
                            {'name': 's1', 'task': 'F1', 'state': 'running'},
                            {'name': 's2', 'task': 'B2', 'state': 'merging'}, {'name': 's3', 'task': ''})]])
        eq(got[:4], [{'ask': True}, {'ask': True},
                     {'name': 'run_control', 'args': {'key': 'stop_now', 'confirm': True}},
                     {'name': 'run_control', 'args': {'key': 'stop'}}],
           "Stop now's button asks in the page first; only its Yes sends it, confirmed; Stop goes at once")
        eq(got[4:], [True, False, False], "a slot's Take back and Drop show while it works, not while it lands")
    ran, sent = [], []
    token = W.web_token()
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {})
    url = f'http://127.0.0.1:{srv.server_address[1]}/act?t={token}'
    try:
        with mock.patch.object(U, 'RUN', [lambda argv: (ran.append(argv), (0, 'sent to the run'))[1]]), \
                mock.patch.object(U, 'SEND', [lambda text: (sent.append(text), {'ok': True, 'code': 0,
                                                                                 'out': 'sent', 'argv': []})[1]]):
            for c, rq in zip(cs, reqs):
                ran.clear()
                code, out = post(url, rq)
                if c['key'] == 'task_take':
                    eq((out.get('ok'), sent, ran), (True, [], [['control', '--new', '--ask', 'do F1 here', '--no-feed']]),
                       'B139: Take back asks a new control session "do F1 here", not c1')
                else:
                    eq((code, out.get('ok'), ran), (200, True, [want[c['key']]]),
                       f'{c["label"]} runs {" ".join(want[c["key"]])}')
            ran.clear()
            code, out = post(url, reqs[-1])
            eq((out.get('ok'), ran, out.get('confirm')), (False, [], U.STOP_NOW_ASK),
               "stop now without the page's confirm runs nothing and returns the question")
    finally:
        srv.stop()


def test_row_actions(tmp: Path) -> None:
    """C34: the page draws a Queue row's actions and the release tab's from the snapshot's `acts` and sends each
    as one run_control request through the one data-ctl handler; the server runs it (replaces the per-button
    Unpark and Release tests)."""
    fake_repo(tmp)
    page = W.PAGE.read_text(encoding='utf-8')
    for part in ('actBtns(acts,q.id)', 'actSure(acts,q.id)', 'S.snap.release_acts', 'if(c.chat){',
                 'ansBtns(n)', 'restBtns(n)', 'actSure(n.acts,n.id)', 'actBtns(acts,c.id)', 'actSure(acts,c.id)'):
        check(part in page, f'the page has {part}')
    for gone in ('data-unpark', "outbox('unpark'", 'data-rel=', "outbox('release'", 'data-later=', 'data-needdrop=',
                 'data-needchat=', 'data-cchat=', "outbox('shelve'", "outbox('need_drop'", 'data-ans=', 'answerArgs'):  # F180
        check(gone not in page, f'the page has no {gone}: one handler')
    cs = [c for c in U.controls() if c['where'] in ('queue', 'shelved', 'release', 'need', 'concept')]
    opts = [f'Option {j}' for j in range(1, U.ANSWER_MAX + 1)]
    text = lambda c: c['label'].replace('Answer', 'Option') if c['answer'] else ''  # noqa: E731
    eq(len(cs), 15 + U.ANSWER_MAX, 'the row actions the page draws (C35: Needs you and Concepts too)')
    if shutil.which('node'):
        reqs = logic_js([['controlReq', c, {'tid': 'F83', 'sure': True, 'text': text(c), 'note': ' '}] for c in cs])
    else:
        print('  (no node here: the page requests are built in Python instead)')
        reqs = [{'name': 'run_control', 'args': {'key': c['key'], **({'text': text(c)} if c['answer'] else {}), **({'tid': 'F83'} if c['needs'] == 'id' else {}),
                                                  **({'confirm': True} if c['confirm'] else {})}} for c in cs]
    ran = []
    token = W.web_token()
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {})
    url = f'http://127.0.0.1:{srv.server_address[1]}/act?t={token}'
    try:
        chat = lambda tid, wait: U.call(['control', '--new', tid])  # noqa: E731
        with mock.patch.object(U, 'RUN', [lambda argv: (ran.append(argv), (0, 'ok'))[1]]), \
                mock.patch.dict(U.ROW_FNS, {'need_chat': chat, 'concept_chat': chat}), \
                mock.patch.object(U, 'need_label', lambda tid: 'CONFIRM'), \
                mock.patch.object(U, 'row_of', lambda where, tid: {'id': tid, 'pri': 'normal', 'state': 'parked', 'ask': 'Look',
                                                                   'label': 'CONFIRM', 'concept': tid, 'options': opts}):
            for c, rq in zip(cs, reqs):
                ran.clear()
                code, out = post(url, rq)
                # the stand-in row is parked: priority does not fit; its answers are options: not Yes and No
                fits = c['key'] not in ('queue_priority', 'need_yes', 'need_no')
                eq((code, out.get('ok')), (200, fits), f'{c["label"]} sent from the page: {"runs" if fits else "refused"}')
                eq(bool(ran), fits, f'{c["label"]}: its command ran or not, as the row allows')
    finally:
        srv.stop()


def test_start(tmp: Path) -> None:
    fake_repo(tmp)
    eq(CF.DEFAULTS['run']['web'], True, '[run] web is on by default')
    eq(CF.DEFAULTS['run']['web_port'], 8770, 'on port 8770')
    with mock.patch.dict(W.os.environ, {'AGENT_RUNNER_NO_WEB': ''}), mock.patch.dict(S.C.run, {'web': False}):
        eq(W.start_web(), None, '[run] web = false serves nothing')
    eq(W.page_line(), '', 'and status prints no address')
    with mock.patch.dict(W.os.environ, {'AGENT_RUNNER_NO_WEB': ''}), mock.patch.object(W, 'lan_ip', lambda: '10.0.0.5'), \
            mock.patch.dict(S.C.run, {'web': True, 'web_port': 0}), mock.patch.object(S, 'log') as lg:
        srv = W.start_web()
    try:
        check(srv is not None, 'web = true serves the page')
        url, by_ip = W.url_file().read_text(encoding='utf-8').split()
        tail = f':{srv.server_address[1]}/?t={W.web_token()}'
        check(url.endswith(tail), 'its address carries the token', url)
        eq(by_ip, f'http://10.0.0.5{tail}', 'and its LAN address, for a phone that cannot resolve the hostname')
        check(any(url in str(c) for c in lg.call_args_list), 'the run log has the address', lg.call_args_list)
        with mock.patch.object(S, 'run_up', return_value=True):
            eq(W.page_line(), f'run page: {url} (or {by_ip})', 'status prints it while the run is up')
        eq(U.SEND[0], U.to_new, "the run's chat goes through ui_model.to_new, a new chat each")
        eq(srv.server_address[0], '0.0.0.0', 'F165: no Home: on every interface')
    finally:
        srv.stop()
    # F165: with Home installed it is on 127.0.0.1, and nothing shown names its port
    with mock.patch.dict(W.os.environ, {'AGENT_RUNNER_NO_WEB': ''}), mock.patch.object(W, 'home_port', lambda: 8770), \
            mock.patch.object(W, 'site_urls', lambda root=None: ['http://box:8770/p/proj/?t=HT']), \
            mock.patch.object(W, 'tailscale_https_urls', lambda port, t: []), mock.patch.object(S, 'log') as lg:
        srv = W.start_web()
        try:
            own = srv.server_address[1]
            eq((srv.server_address[0], srv.terms.bind), ('127.0.0.1', '127.0.0.1'), 'Home installed: 127.0.0.1 only')
            logged = ' '.join(str(c) for c in lg.call_args_list)
            check('http://box:8770/p/proj/?t=HT' in logged and str(own) not in logged, "the run log has Home's link only", logged)
            with mock.patch.object(S, 'run_up', return_value=True):
                eq(W.page_line(), 'run page: http://box:8770/p/proj/?t=HT', 'and so has status')
        finally:
            srv.stop()


def test_diff(tmp: Path) -> None:
    """F75: /diff/s1 is slot s1's work so far against the shared branch, committed or not."""
    repo = fake_repo(tmp)
    home = tmp / 'runs'
    home.mkdir()
    git(repo, 'worktree', 'add', '-q', '--detach', str(home / 's1'), 'HEAD')
    (home / 's1' / 'a.py').write_text('x = 1\n', encoding='utf-8')
    git(home / 's1', 'add', 'a.py')
    git(home / 's1', 'commit', '-qm', 'a')
    (home / 's1' / 'b.py').write_text('y = 2\n', encoding='utf-8')
    git(home / 's1', 'add', 'b.py')
    token = W.web_token()
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {})
    base = f'http://127.0.0.1:{srv.server_address[1]}'
    try:
        with mock.patch.object(S, 'SLOTS_DIR', home):
            r = json.loads(get(f'{base}/diff/s1?t={token}')[1])
            check(r['ok'] and '+x = 1' in r['text'] and '+y = 2' in r['text'], 'the diff has the commit and the staged file', r)
            r = json.loads(get(f'{base}/diff/s2?t={token}')[1])
            check(not r['ok'] and 'no worktree' in r['out'], 'a slot with no worktree says so', r)
            r = json.loads(get(f'{base}/diff/c1?t={token}')[1])
            check(not r['ok'] and 'not a slot' in r['out'], 'a control session has no diff', r)
        eq(get(f'{base}/diff/s1')[0], 403, 'and only with the token')
    finally:
        srv.stop()


PARKED_TODO = TODO + """
### Parked
- [ ] **F83** Big future work for a person to schedule | files: p.py
"""


def test_parked(tmp: Path) -> None:
    """B118: a parked task (level later, TODO.md's Parked section) is in its own Parked group on the run app and
    never says Ready, and Unpark (plan edit ID --pri normal) moves it out of Parked."""
    repo = fake_repo(tmp)
    todo = repo / 'plan' / 'TODO.md'
    todo.write_text(PARKED_TODO, encoding='utf-8')
    q = {t['id']: t for t in U.queue_rows(todo.read_text(encoding='utf-8').splitlines())}
    eq(q['F83']['state'], 'parked', 'the model gives a task under Parked state parked')
    app = W.page_html().decode()
    for part in ('<div class="sec">Parked<span class="ln"></span></div>', "Parked: a run won't start it",
                 '${actBtns(acts,q.id)}${chatBtn(q)}</div>'):
        check(part in app, f'the run app has {part}')
    token = W.web_token()
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {})
    try:
        code, out = post(f'http://127.0.0.1:{srv.server_address[1]}/act?t={token}',
                         {'name': 'run_control', 'args': {'key': 'queue_unpark', 'tid': 'F83'}})
    finally:
        srv.stop()
    check(code == 200 and out.get('ok'), 'the unpark act ran plan edit', out)
    eq(out.get('argv', [])[-4:], ['edit', 'F83', '--pri', 'normal'], 'unpark is plan edit ID --pri normal')
    after = todo.read_text(encoding='utf-8')
    parked = after.split('### Parked', 1)[1] if '### Parked' in after else ''
    check('F83' in after and 'F83' not in parked, 'F83 is out of Parked', after)
    q = {t['id']: t for t in U.queue_rows(after.splitlines())}
    eq((q['F83']['state'], q['F83']['pri']), ('ready', 'normal'), 'and is ready, at level normal')
    eq(U.run_control('queue_unpark', tid='not an id')['ok'], False, 'unpark takes a queued task only')
    if not shutil.which('node'):
        print('  (no node here: the Parked group script test is skipped)')
        return
    rows = [{'id': 'F83', 'state': 'parked'}, {'id': 'F1', 'state': 'ready'}, {'id': 'B2', 'state': 'after'}]
    got = logic_js([['planWords', {'id': 'F83', 'state': 'parked'}, []], ['queueGroups', rows]])
    eq(got[0], "Parked: a run won't start it", 'a parked row says so on the run app')
    check('Ready' not in got[0], 'and never Ready')
    eq([[r['id'] for r in g] for g in got[1]], [['F1', 'B2'], ['F83']], 'the Queue, then the Parked group')


def test_shelved_f184(tmp: Path) -> None:
    """F184: the Plan view's Parked group lists the shelved tasks after the parked ones, also when there are only
    shelved ones; a press keeps its card off and shows the stand-in there."""
    fake_repo(tmp)
    app = W.page_html().decode()
    for part in ('pk.length||sh.length||shOb', "${pk.map(q=>parkedCard(q)).join('')}${shOb}${sh.map(q=>shelvedCard(q)).join('')}",
                 '${actBtns(acts,q.id)}${chatBtn(q)}</div>${actSure(acts,q.id)}', 'S.snap.queue.concat(S.snap.shelved||[])', "obHidden(S.ob,'shelved')",
                 'if(S.gone)delete S.gone[it.shelved]', "c.confirm.split('{id}').join(tid||'')"):
        check(part in app, f'the run app has {part}')
    if not shutil.which('node'):
        print('  (no node here: the shelved script test is skipped)')
        return
    got = logic_js([['planWords', {'id': 'D3', 'state': 'shelved'}, []]])
    eq(got, ['Shelved until you bring it back'], 'a shelved row says so')


def test_concepts_view(tmp: Path) -> None:
    """F87: the sidebar has Concepts (after Plan, with a count); its view lists the snapshot's concepts with their
    buttons (an option each, Chat, View), says no concept waits when none does, and its New concept button
    opens a new chat (F183); the Plan view no longer lists concepts."""
    fake_repo(tmp)
    app = W.page_html().decode()
    for part in ("['plan','Plan'],['history','History'],['concepts','Concepts']", 'count={home:needs,concepts:cn}',
                 'concepts:conceptsHTML', "concepts:'Concepts'", 'cs.map(conceptCard)'):
        check(part in app, f'the run app has {part}')
    for gone in ('data-kadd', 'kform', '[data-kin]', 'newConceptReq', 'growKin', 'S.kOpen', 'S.kText', 'S.kSaid', 'x.kq'):
        check(gone not in app, f'the inline new concept box is gone: {gone}')
    plan = app.split('function planHTML(){', 1)[1].split('\n}', 1)[0]
    check('concept' not in plan.lower(), 'the Plan view lists no concepts', plan)
    if not shutil.which('node'):
        print('  (no node here: the Concepts view script test is skipped)')
        return
    c = {'id': 'K5', 'concept': 'K5', 'title': 'Lazy layout', 'copy': '/n/K5.html',
         'options': [{'name': 'A: tabs', 'rec': False}, {'name': 'B: drawer (recommended)', 'rec': True}]}
    got = logic_js([['conceptButtons', c], ['conceptButtons', {'id': 'K6', 'options': []}],
                    ['newPh', {'kind': 'newconcept'}], ['newPh', {'kind': 'new'}], ['newPh', {'kind': 'plan'}], ['newPh', None],
                    ['compose', {'kind': 'newconcept'}, ' a dark mode ', ['/up/p.png']],
                    ['compose', {'kind': 'concept', 'id': 'K5', 'lead': 'About it.'}, ' wider ', ['/up/p.png']],
                    ['compose', {'kind': 'concept', 'id': 'K5', 'lead': 'About it.'}, '', ['/up/p.png']]])
    eq(got[7:], ['About it.\n\nwider\n\nAttached: /up/p.png', 'About it.\n\nAttached: /up/p.png'],
       "B219a: a concept's first message: what it is about, then the words and attachments")
    eq([b['label'] for b in got[0]], ['A: tabs', 'B: drawer', 'Chat', 'View'],
       "a concept's buttons: its options (no '(recommended)'), Chat, View")
    eq([b.get('rec', False) for b in got[0]], [False, True, False, False], 'the recommended option stands out')
    eq([b['label'] for b in got[1]], ['Chat'], 'no copy and no page: no options and no View')
    eq(got[2:6], ['What should the concept show?', 'Describe the task in your own words', 'Write your first message',
                  'Write your first message'], "a new chat view's placeholder")
    check('box(agent?`Message ${threadTitle(n)}`:isNew(n)?newPh(S.ctx):' in app, 'its box shows it')
    eq(got[6], 'Concept: a dark mode\n\nAttached: /up/p.png', "a new concept's first message")
    check("NO_CONCEPT='No concept waits for a pick.'" in app and '${NO_CONCEPT}' in app,
          'the empty state says no concept waits')


def test_release_row_f131(tmp: Path) -> None:
    """F131, F185, F195c: the releases, each open one once in its row's words, then the rows that are no task; the Queue
    has them at their place, the auto release's count dimmed."""
    page = W.PAGE.read_text(encoding='utf-8')
    check('qs=gripRows(menuRows(planRows(S.snap)))' in page and '.card.relph{opacity' in page, 'the Plan view draws planRows, a placeholder dimmed')
    if not shutil.which('node'):
        print('  (no node here: the release row script test is skipped)')
        return
    task, parked = {'id': 'F1', 'state': 'ready'}, {'id': 'F9', 'state': 'parked'}
    ph = {'id': '', 'title': 'Next release', 'words': 'auto at 10 landed: 6/10', 'placeholder': True}
    done = {'id': 'V4', 'title': 'Release 1.2.0', 'words': 'released 10:00', 'state': 'released', 'placeholder': True}
    row = lambda t, w: {'id': t, 'title': 'Release', 'words': w, 'placeholder': False}  # noqa: E731
    r5, r6 = row('V5', 'releasing now'), row('V6', 'waits for 1: V5 Release')
    v5, v6 = {'id': 'V5', 'state': 'running s2 6m', 'release': r5}, {'id': 'V6', 'state': 'after', 'release': r6}
    two = {'queue': [task, parked, v6, v5], 'releases': [r5, r6, done]}
    got = logic_js([['planReleases', {'queue': [task], 'releases': []}], ['planReleases', {'queue': [task]}],
                    ['planReleases', {'queue': [task], 'releases': [ph]}],
                    ['planReleases', {'queue': [task, v5], 'releases': [r5]}],
                    ['planReleases', two], ['planQueue', two], ['planWords', v5, []]])
    eq(got, [[], [], [ph], [v5], [v5, v6, done], [task], 'releasing now'],
       'none, none from an older run, auto, one running, two; the Queue without them (Parked is its own group)')
    f2, at = {'id': 'F2', 'state': 'ready'}, dict(ph, before='F2')
    got = logic_js([['planRows', {'queue': [task, v6, f2, parked, v5], 'releases': [r5, r6, done]}], ['planRows', {'queue': [task, f2], 'releases': [at]}],
                    ['planRows', {'queue': [task, v6, f2], 'releases': [r6, at]}], ['planRows', {'queue': [task], 'releases': [ph]}],
                    ['planRows', {'queue': [task], 'releases': [dict(at, before='F9')]}], ['planRows', {'queue': [task, f2], 'releases': [at], 'manage_releases': False}], ['planRows', {}]])
    eq(got, [[task, v6, f2, v5], [task, at, f2], [task, v6, at, f2], [task, ph], [task, dict(at, before='F9')], [task, f2], []],
       'plan order, no landed one; the count before its task, beside a waiting release too, else last; releases off: none; no plan yet')


RELEASE_DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const line = a => page.slice(page.indexOf(a), page.indexOf('\n', page.indexOf(a)) + 1);
const slice = (a, b) => page.slice(page.indexOf(a), page.indexOf(b, page.indexOf(a)));
const grab = a => page.slice(page.indexOf(a), page.indexOf('\n}\n', page.indexOf(a)) + 3);
const [controls, v5, v6] = JSON.parse(process.argv[3]);
const S = {ob: [], taskOpen: {}, sure: null, snap: {controls, queue: [v5, v6], releases: [v5.release, v6.release], release_acts: ['release_wait', 'release_now'], release_said: 'V6 is already queued'}};
const working_ = () => [{}], cutsOff = () => '', taskRow = (q, t, more) => q.id + more, obCards = () => '', toast = () => {}, obChange = f => { S.ob = f(S.ob) }, obDrop = (b, c) => b.filter(x => x.cid !== c);
globalThis.fetch = async () => { throw 0 };
const src = ['const esc=', 'const card=', 'const controlsOf=', 'const controlOf=', 'const ctlBusy=', 'const sureHTML=', 'const ctlSure=', 'const obActs=', 'const actBtns=', 'const actSure=', 'const relDrop=', 'const chatBtn=', 'const planQueue='].map(line).join('')
  + slice('/* F429b: the menu on a Plan', 'function rowMenuOpen(') + slice('/* F429c: the grip of a Plan queue row (a', '/* the drag: the row goes') + slice('const taskBtns=', '/* F186: a release') + slice('/* F426b: an open release', '/* F131: the auto') + slice('const queueGroups=', '/* F185') + line('const releasesOn=') + slice('const planReleases=', 'const planQueue=') + grab('function relCard(') + slice('function newReleaseCard(', '/* F124: the Status') + grab('function obDone(').replace('toast(j.confirm,true);', '')
  + grab('function controlReq(') + line('function controlClick(');
new Function('env', 'with(env){' + src.replace(/const /g, 'var ') + `
  const out = {rel: relCard(), v5: releaseCard(env.v5), v6: releaseCard(env.v6)};
  S.sure = 'release_wait'; out.sure = newReleaseCard();
  S.sure = 'queue_drop:V6'; out.drop = releaseCard(env.v6); out.relDrop = relCard();
  out.click = [controlClick(controlOf('release_wait'), {}), controlClick(controlOf('release_wait'), {sure: true})];
  for (const c of controlsOf('release')) { c.confirm = ''; c.seen = '' }
  S.sure = null; S.ob = [{cid: 'a'}];
  obDone({cid: 'a', ctl: 'release_now:', name: 'run_control', args: {}}, {ok: false, confirm: 'V7 is already queued. Queue another release?', seen: 'V7'});
  out.stale = [S.ob, S.sure, newReleaseCard(), controlClick(controlOf('release_now'), {sure: true})];
  console.log(JSON.stringify(out))}`)({S, taskChip: id => `<kind ${id}>`, working_, cutsOff, taskRow, obCards, toast, obChange, obDrop, v5, v6, tq: p => p, takeSnap: () => {}});
"""


def test_new_drop_release_f186(tmp: Path) -> None:
    """F186: New release says which release is open and asks before another; Drop stands on a release that has not
    started, not on one that runs; a release the page had not heard of is asked about, not failed."""
    if not shutil.which('node'):
        print('  (no node here: the New release script test is skipped)')
        return
    ask, drop = 'V6 is already queued. Queue another release?', 'Drop V6? It leaves the plan, and nothing is released.'
    row = lambda t, w: {'id': t, 'title': 'Release', 'words': w, 'placeholder': False}  # noqa: E731
    v5 = {'id': 'V5', 'acts': ['queue_take'], 'release': row('V5', 'releasing now')}
    v6 = {'id': 'V6', 'acts': ['queue_take', 'queue_drop'], 'asks': {'queue_drop': drop}, 'release': row('V6', 'next')}
    (tmp / 'driver.js').write_text(RELEASE_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE), json.dumps([U.controls({'ask': ask, 'seen': 'V6'}), v5, v6])],
                       capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs the page script', r.stderr[-800:])
    o = json.loads(r.stdout)
    check('New release' in o['rel'] and 'V6 is already queued.' in o['rel'] and '<kind V5>' in o['rel'] and '>releasing now' in o['rel'], 'says so and shows it', o['rel'])
    eq((o['rel'].count('data-ctl="queue_drop"'), 'data-tid="V6"' in o['rel'], 'data-tid="V5"' in o['rel']), (1, True, False), 'Drop on V6 only')
    check('queue_drop' not in o['v5'] and 'queue_drop' in o['v6'], "the Plan view's cards: the same", o['v5'])
    check(ask in o['sure'] and 'data-sure' in o['sure'], 'New release asks in place', o['sure'])
    check(all(drop in o[k] for k in ('drop', 'relDrop')), 'Drop asks in its own words', o['drop'])
    eq(o['click'], [{'ask': True}, {'name': 'run_control', 'args': {'key': 'release_wait', 'confirm': True, 'text': 'V6'}}],
       'a press asks; its Yes names the open release')
    eq(o['stale'][:2], [[], 'release_now'], 'one just queued elsewhere: the press asks, with nothing failed')
    check('V7 is already queued' in o['stale'][2], 'about it', o['stale'][2])
    eq(o['stale'][3]['args'], {'key': 'release_now', 'confirm': True, 'text': 'V7'}, 'and its Yes names it')


def test_task_text_f85(tmp: Path) -> None:
    """F85: a queue row folds open to the task's whole text (plan ID)."""
    fake_repo(tmp)
    page = W.page_html().decode()
    for part in ('data-task="${esc(q.id)}" data-list="${esc(list)}" aria-expanded="${open}"', "fetch(tq('task/'", '<pre class="tasktext"', "const planCard=(q,"):
        check(part in page, f'the page has {part}')
    token = W.web_token()
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {})
    base = f'http://127.0.0.1:{srv.server_address[1]}'
    try:
        code, body = get(f'{base}/task/B2?t={token}')
        got = json.loads(body)
        check(code == 200 and got['ok'] and 'Fix the merge retry' in got['text'] and 'after: F1' in got['text'], 'its whole text', got)
        eq(json.loads(get(f'{base}/task/--x?t={token}')[1])['ok'], False, 'a task id only')
        eq(get(f'{base}/task/B2')[0], 403, 'and only with the token')
    finally:
        srv.stop()


def test_need_heading_b793a(tmp: Path) -> None:
    """B793a: a Needs you card is headed by what is asked, whole, its task's title small under it unless it is the same;
    no ellipsis or line clamp on either, nor on what to do."""
    if not shutil.which('node'):
        print('  (no node here: the heading script test is skipped)')
        return
    none = {k: [] for k in ('lead', 'expect', 'notes', 'shots')}
    ask = 'Release V5 and run `agent-runner upgrade`, then ' + 'look at it again ' * 12 + 'once'
    title = 'Check F170 on the iPhone 15: ' + 'the hidden lines stay hidden ' * 4 + 'in Safari'
    row = {'id': 'R17', 'label': 'BLOCKED', 'age': '20m', 'ask': ask, 'ask_short': 'Release…',
           'detail': {**none, 'said': 'Do this', 'where': '', 'title': title, 'summary': ask, 'question': '', 'steps': [ask, 'This reruns']}}
    same = {**row, 'detail': {**row['detail'], 'title': ask.replace('`', '')}}  # a title comes without its quote marks
    untitled = {**row, 'detail': {**row['detail'], 'title': 'R17'}}
    got = logic_js([['needTap', r] for r in (row, same, untitled, {k: v for k, v in row.items() if k != 'detail'})])
    head = '<b class="q">' + ask.replace('`agent-runner upgrade`', '<code>agent-runner upgrade</code>') + '</b>'
    foot = '<span class="small">Press for details'
    check(head + f'<span class="small">{title}</span>' + foot in got[0], 'the whole ask, then the whole title', got[0])
    for g, why in zip(got[1:], ('a title that says the same', 'no title', 'no detail: the ask, not ask_short')):
        check(head + foot in g, f'{why}: the ask alone', g)
    css = W.PAGE.read_text(encoding='utf-8')
    rules = [m for m in re.findall(r'[^{}]*\{[^{}]*\}', css) if re.search(r'ellipsis|line-clamp', m)]
    cut = [m for m in rules if re.search(r'\.asktap|\.asktop|\.askbody|\bh2\b|\.q(?![\w-])|\.small(?![\w-])|(?<!\.card>)\.askdo', m.split('{')[0])]
    eq(cut, [], 'no rule cuts the heading, the title or what to do')


MANAGE_DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const line = a => page.slice(page.indexOf(a), page.indexOf('\n', page.indexOf(a)) + 1);
const slice = (a, b) => page.slice(page.indexOf(a), page.indexOf(b, page.indexOf(a)));
const grab = a => page.slice(page.indexOf(a), page.indexOf('\n}\n', page.indexOf(a)) + 3);
const S = {ob: [], taskOpen: {}, sure: null, snap: null, f: {}};
const no = () => '', env = {S, taskChip: no, landedText: no, planField: no, planWant: no, planAsk: no, obCards: key => S.ob.filter(key).map(x => `[ob ${x.ctl}]`).join(''), taskRow: (q, t) => `${q.id} ${t}`, working_: () => [{}], cutsOff: no,
  ttydLine: no, needsSec: no, controlsCard: no, meterHTML: no, emptyCard: t => t, NO_CONCEPT: '', I: {}, upNext: () => S.snap.queue, LOGO: no, greeting: no, box: no, keysLine: no, homeChips: no, runPill: () => ({text: ''}), esc: no};
const src = ['const esc=', 'const card=', 'const controlsOf=', 'const controlOf=', 'const ctlBusy=', 'const sureHTML=', 'const ctlSure=', 'const obActs=', 'const actBtns=', 'const actSure=', 'const relDrop=', 'const chatBtn=', 'const planCard=', 'const nextReleaseRow=', 'const nextReleaseCard=', 'const queueCard=', 'const planQueue=', 'const releasesOn='].map(line).join('')
  + slice('/* F429b: the menu on a Plan', 'function rowMenuOpen(') + slice('/* F429c: the grip of a Plan queue row (a', '/* the drag: the row goes') + slice('const taskBtns=', '/* F186: a release') + slice('/* F426b: an open release', '/* F131: the auto')
  + slice('const queueGroups=', '/* F193') + slice('const planReleases=', 'const planQueue=') + slice('const planRows=', '/* F87') + ['relCard', 'newReleaseCard', 'statusHTML', 'planHTML', 'homeStatus', 'homePlan', 'homeHTML'].map(f => grab(`function ${f}(`)).join('') + line('const homeSums=');
const draw = new Function('env', 'with(env){' + src.replace(/const /g, 'var ') + '; return () => [planHTML(), statusHTML(), homeHTML()]}')(env);
const out = JSON.parse(require('fs').readFileSync(process.argv[3], 'utf8')).map(([snap, ob]) => { S.snap = snap; S.ob = ob; return draw() });
console.log(JSON.stringify(out));
"""


def test_manage_releases_f193(tmp: Path) -> None:
    """F193: [run] releases off: the Plan and Status views and the run page copy say nothing of releases, an open V
    task is in the Queue; on, they are as before. A New release already sent is still seen to its end."""
    if not shutil.which('node'):
        print('  (no node here: the Manage releases script test is skipped)')
        return
    from agent_runner import page_copy
    fake_repo(tmp)
    todo = S.C.todo
    todo.write_text(todo.read_text(encoding='utf-8') + '- [ ] **V5** Ship 1.2.0 | after: all\n', encoding='utf-8')

    def snap(on: bool) -> dict:
        S.C.run['releases'] = on
        s = U.snapshot(up=True, links={})
        return {**s, 'lately': [], 'log': []}
    on, off = snap(True), snap(False)
    sent = [{'cid': 'a', 'ctl': 'release_now:', 'state': 'failed', 'say': 'Release now'}]
    old = {k: v for k, v in on.items() if k != 'manage_releases'}
    (tmp / 'driver.js').write_text(MANAGE_DRIVER, encoding='utf-8')
    cases = tmp / 'cases.json'  # a file: too long for a Windows command line
    cases.write_text(json.dumps([[on, []], [off, []], [off, sent], [on, []], [old, []]]), encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE), str(cases)],
                       capture_output=True, text=True, encoding='utf-8', timeout=60)
    check(r.returncode == 0, 'node runs the page script', r.stderr[-800:])
    (plan_on, st_on, home_on), (plan_off, st_off, home_off), (plan_sent, st_sent, home_sent), back, older = json.loads(r.stdout)
    check('>Releases<' not in plan_on and '<b>New release</b>' in plan_on and 'data-ctl="release_now"' in plan_on, 'on: Plan has them', plan_on)
    check('>Release<' in st_on and 'data-ctl="release_now"' in st_on and 'V5' in st_on, 'on: Status too', st_on)
    check('data-ctl="release_now"' not in home_on and 'release_take' not in home_on, 'F426a: no release card on Home', home_on)
    queue = plan_on.split('>Queue<', 1)[1]
    eq((plan_on.count('task:V5'), queue.count('task:V5')), (1, 1), 'on: V5 is a row of the Queue')
    for name, html in (('Plan', plan_off), ('Status', st_off), ('Home', home_off)):
        check(not re.search(r'release', html, re.I), f'off: {name} says nothing of releases', html)
    check('V5 Ship 1.2.0' in plan_off.split('>Queue<', 1)[1], 'off: V5 is in the Queue', plan_off)
    for html in (plan_sent, st_sent):
        check('[ob release_now:]' in html and 'New release' not in html, 'off: one already sent shows until settled', html)
    eq((back, older), ([plan_on, st_on, home_on], [plan_on, st_on, home_on]), 'back on, and from an older run: all of it')
    c_on, c_off = page_copy.page_copy_html(on), page_copy.page_copy_html(off)
    check('waits for' in c_on, 'the copy, on: its release row', c_on)
    body = c_off.split('</style>', 1)[1]
    check(not re.search(r'release', body, re.I) and 'Ship 1.2.0' in body, 'the copy, off: an ordinary task, nothing of releases', body)


RUN_CARD_DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const line = a => page.slice(page.indexOf(a), page.indexOf('\n', page.indexOf(a)) + 1);
const grab = a => page.slice(page.indexOf(a), page.indexOf('\n}\n', page.indexOf(a)) + 3);
const icons = page.slice(page.indexOf('const I={'), page.indexOf('const LOGLINE_ICON='));
const S = {ob: [], snap: null};
const env = {S, taskChip: id => `<kind ${id}>`, lastWords: () => '', obCards: () => '[outbox]'};
const src = ['const esc=', 'const ic=', 'const card=', 'const controlsOf=', 'const controlOf=', 'const ctlBusy=', 'const obRun=', 'const slots=',
  'const working_=', 'const taskControlsOn=', 'const CTL_ICON=', 'function cardControls(', 'const toolsWords='].map(line).join('')
  + icons + grab('function slotRow(') + grab('function controlsCard(');
const draw = new Function('env', 'with(env){' + src.replace(/const /g, 'var ') + '; return [controlsCard, I]}')(env);
const out = JSON.parse(require('fs').readFileSync(process.argv[3], 'utf8')).map(([snap, ob]) => { S.snap = snap; S.ob = ob; return draw[0]() });
console.log(JSON.stringify([out, draw[1]]));
"""


def test_run_card_b763a(tmp: Path) -> None:
    """B763a: the Run card's controls stand above the slot rows, under the notices, each with its icon; the
    walkthrough's start step still finds its target."""
    if not shutil.which('node'):
        print('  (no node here: the Run card script test is skipped)')
        return
    fake_repo(tmp)

    def snap(n: int, up: bool = True, **run) -> dict:
        return {'up': up, 'run': run, 'slots': n, 'controls': U.controls(), 'unpushed': 'Not pushed yet',
                'sessions': [{'name': f's{i}', 'task': f'B{i}', 'state': 'working', 'task_controls': True}
                             for i in range(1, n + 1)], **U.controls_shown(up, run, {})}
    busy = [{'ctl': 'pause:', 'state': 'sending'}]
    cases = [(snap(0), []), (snap(1), []), (snap(4), busy), (snap(4, paused=True), []),
             (snap(4, stopping=True), []), (snap(0, up=False), [])]
    (tmp / 'driver.js').write_text(RUN_CARD_DRIVER, encoding='utf-8')
    case_file = tmp / 'cases.json'  # a file: too long for a Windows command line
    case_file.write_text(json.dumps(cases), encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE), str(case_file)],
                       capture_output=True, text=True, encoding='utf-8', timeout=60)
    check(r.returncode == 0, 'node runs the page script', r.stderr[-800:])
    cards, icons = json.loads(r.stdout)
    icon = {'start': 'play', 'go_on': 'play', 'pause': 'pause', 'stop': 'stop', 'stop_undo': 'undo',
            'slot_add': 'plus', 'slot_remove': 'minus'}
    for (s, _), html in zip(cases, cards):
        row = html.split('aria-label="Run controls">', 1)[1].split('</div>', 1)[0]
        for k in s['card']:
            check(re.search(rf'data-ctl="{k}">{re.escape(icons[icon[k]])}\w', row), f'{k}: its icon, then its word', row)
        check(f'data-sheet="run">{icons["dots"]}More…' in row, 'More… too', row)
        eq(row.count('<svg'), len(s['card']) + 1, 'one icon on each')
        at = html.index('Run controls')
        check(html.index('data-k="runsaid"') < html.index('data-k="unpushed"') < html.index('[outbox]') < at,
              'under the state line, the notices and the outbox', html)
        eq(html.count('class="srow"'), len(s['sessions']), 'a row for each slot')
        check(all(at < m.start() for m in re.finditer('class="srow"', html)), 'above every slot row', html)
        walk = logic_js([['walkStep', 'start', {'up': s['up']}]])[0]['at']
        eq(walk[0], '.card:has([data-k="runsaid"])' if s['up'] else '[data-ctl="start"]', "the walk's start target")
        check(html.startswith('<div class="card ') and (s['up'] or 'data-ctl="start"' in html), 'and it is there', html)
    check('class="btn  busy" data-ctl="pause"' in cards[2], 'a control being sent is busy', cards[2])
    for i, k in ((3, 'go_on'), (4, 'stop_undo'), (5, 'start')):
        check(f'class="btn acc" data-ctl="{k}"' in cards[i], f'{k} is the main button', cards[i])


SEARCH_DRIVER = DOM + r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const logic = page.split('<script id="logic">')[1].split('</script>')[0].replace(/if\(typeof module[^\n]*/, '');
const line = a => page.slice(page.indexOf(a), page.indexOf('\n', page.indexOf(a)) + 1), slice = (a, b) => page.slice(page.indexOf(a), page.indexOf(b, page.indexOf(a)));
const grab = a => page.slice(page.indexOf(a), page.indexOf('\n}\n', page.indexOf(a)) + 3);
const S = {f: {}, ob: [], taskOpen: {}, tasks: {}, sure: null, view: 'plan', snap: JSON.parse(process.argv[3])}, I = {chev: '', x: 'x'}, SHEETS = {};
const card = (h, cls = '', attr = '') => `<div class="card" ${attr}>${h}</div>`, emptyCard = t => card(t), obCards = f => S.ob.filter(f).map(x => card('sent ' + x.say)).join(''), oldRunHTML = esc0 => esc0, releaseCard = () => '', newReleaseCard = () => '', taskInView = () => {};
const controlOf = k => S.snap.controls.find(c => c.key === k), ctlBusy = () => false, ctlSure = () => '', actSure = () => '', MO = {}, HKEY = 'k', T = 't';
const field = () => root.querySelectorAll('[data-f]').find(x => x.dataset.f === 'planq'), x = () => root.querySelectorAll('[data-planqclear]')[0];
const ears = {}, n = null, body = root, document = {get activeElement() { return doc.activeElement }, querySelector: field, createElement: () => ({content: new Node(11, '#fragment'), set innerHTML(h) { this.content.innerHTML = h }}),
  addEventListener: (k, f) => { (ears[k] = ears[k] || []).push(f) }};
const kbFocus = e => e.focus(), $ = () => root, grow = () => {}, calls = []; let press, timers = [];
const setTimeout_ = setTimeout, fetch = url => new Promise((ok, no) => calls.push({url, say: j => ok({json: async () => j}), fail: () => no(Error('down'))}));
{ const setTimeout = f => timers.push(f), clearTimeout = i => { timers[i - 1] = null };
eval(logic + line('const esc=') + line('const taskChip=') + line('const tq=') + slice('const actBtns=', '\n') + '\n' + slice('function setHTML(', '/* F83') + slice('function keepFields(', '/* a press under way')
  + slice('function fieldHTML(', '/* F189b: a press in the sheet') + line('const taskIsOpen=') + grab('function taskRow(').trim() + '\n' + grab('async function openTask(') + line('const chatBtn=') + slice('/* F429b: the menu on a Plan', 'function rowMenuOpen(') + slice('/* F429c: the grip of a Plan queue row (a', '/* the drag: the row goes') + slice('const taskBtns=', '/* F186: a release') + line('const planCard=') + line('const queueCard=') + grab('function parkedCard(') + grab('function shelvedCard(')
  + line('const obActs=') + slice('/* F212: the search', '/* F87: the Concepts view') + grab('function setqClear(') + line("document.addEventListener('input',") + slice("/* F114, F204a", "document.addEventListener('visibilitychange'")
  + "function render() { const keep = keepFields(body), h = planHTML(); " + slice('const drew=', '\n').replace("!n&&S.view==='settings'?settingsDraw(body,h):", '') + " if (drew) keep() }"
  + "press = q => { " + slice("if(q('[data-planqclear]'))", "if(q('[data-setqclear]'))") + " };"
  + "Object.assign(globalThis, {render, openTask, PQ});"); }
const type = v => { field().typed = v; field().writes = 0; field().focused = 0; field().selectionStart = 1; field().matches = s => s === '[data-f]'; ears.input[0]({target: field()}) };
const due = () => { const l = timers.filter(Boolean); timers.fill(null); l.forEach(f => f()); return l.length }, tick = () => new Promise(r => setTimeout_(r, 5));
const secs = () => root.all.filter(e => e.getAttribute('class') === 'sec').map(e => e.text), hit = (id, title, state) => ({id, title, state});
const cards = () => root.querySelectorAll('[data-k]').map(e => e.dataset.k).filter(k => k.startsWith('task:')).map(k => k.slice(5));
const none = {ok: true, open: [], parked: [], done: [], more: 0};
(async () => {
  const out = {}; render(); const f = field(); f.focus(); out.groups = [secs(), cards(), x().hasAttribute('hidden'), calls.length];
  const kept = () => [field() === f, doc.activeElement === f, f.writes, f.focused];
  type('me'); type('merge &'); out.loading = [root.text.includes('Loading…'), kept(), calls.length, due(), calls.map(c => c.url), x().hasAttribute('hidden')];
  type('merge'); due(); calls[1].say({...none, q: 'merge', open: [hit('B2', 'Fix <b>', 'open'), hit('F9', 'New & <i>one</i>', 'open')], parked: [hit('D3', 'Shelf', 'shelved'), hit('F83', 'Later', 'parked')], done: [hit('F0', 'Old <script>', 'done')], more: 2}); await tick();
  calls[0].say({...none, q: 'merge &', open: [hit('F1', 'Late', 'open')]}); await tick();
  out.found = [secs(), cards(), kept(), root.querySelectorAll('[data-ctl]').map(e => e.dataset.ctl + ' ' + e.dataset.tid), root.text, root.all.filter(e => ['script', 'i'].includes(e.nodeName)).length];
  S.snap.at = 'later'; render(); out.same = due();
  S.snap.queue = S.snap.queue.filter(q => q.id !== 'F1'); render(); out.moved = [due(), cards().length]; calls[2].fail(); await tick(); out.kept = [root.text.includes('Could not reach the run page.'), cards().length];
  press(s => s === '[data-planqload]'); calls[3].say({...none, q: 'merge', done: [hit('F0', 'Old', 'done')], more: 1}); await tick(); out.again = [secs(), root.text.includes('1 more done task.'), root.text.includes('Could not')];
  const p = openTask('F0', 'found:done'); out.url = calls[4].url; calls[4].say({ok: true, text: 'whole <text>'}); await p; out.fold = root.text.includes('whole <text>');
  type('zzz'); due(); calls[5].say({...none, q: 'zzz'}); await tick(); out.none = [secs(), root.text];
  S.ob = [{ctl: '', shelved: 'D3', say: 'Drop D3'}]; render(); out.sent = [secs(), root.text]; S.ob = [];
  type('zzzz'); out.next = root.text; type('zzz'); due(); calls[6].say({...none, q: 'zzz'}); await tick();
  type('zz'); due(); calls[7].fail(); await tick(); out.failed = [secs(), root.text];
  press(s => s === '[data-planqclear]'); out.cleared = [secs(), cards(), S.f.planq, kept().slice(0, 2), due(), PQ.got];
  type('q'); type('  '); out.blank = [secs(), due()];
  type('late'); due(); type(''); calls[8].say({...none, q: 'late'}); await tick(); out.lateGone = [secs(), PQ.got];
  console.log(JSON.stringify(out));
})();
"""


def test_search_f212(tmp: Path) -> None:
    """F212: the Plan view's search: matches in place of the groups, the snapshot's own cards, no match, a failed read, a
    late answer dropped, the groups back when it is emptied, and the field the same element through all of it."""
    if not shutil.which('node'):
        print('  (no node here: the Plan search script test is skipped)')
        return
    fake_repo(tmp)
    q = [{'id': 'F1', 'title': 'Board', 'state': 'ready', 'acts': []},
         {'id': 'B2', 'title': 'Fix <b>', 'state': 'ready', 'acts': ['queue_drop']},
         {'id': 'F83', 'title': 'Later', 'state': 'parked', 'acts': ['queue_unpark']}]
    snap = {'queue': q, 'shelved': [{'id': 'D3', 'title': 'Shelf', 'state': 'shelved', 'ask': 'Which?', 'acts': ['shelved_back']}],
            'manage_releases': False, 'sessions': [], 'controls': U.controls()}
    (tmp / 'search.js').write_text(SEARCH_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'search.js'), str(W.PAGE), json.dumps(snap)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node types in the search', r.stderr[-1500:])
    if r.returncode:
        return
    o = json.loads(r.stdout)
    groups = [['Queue', 'Parked'], ['F1', 'B2', 'F83', 'D3']]
    still = [True, True, 0, 0]
    eq(o['groups'], [*groups, True, 0], 'empty: the groups, no x, nothing asked')
    eq(o['loading'], [True, still, 0, 1, ['plan-search?q=merge%20%26&t=t'], False],
       'two words typed fast are one ask, with the words encoded and the key; the field is left alone, and has its x')
    secs, cards, kept, acts, text, tags = o['found']
    eq((secs, cards), (['Open', 'Parked', 'Done'], ['B2', 'F9', 'D3', 'F83', 'F0']), 'the matches, in the order found; a late answer is dropped')
    eq(acts, ['shelved_back D3', 'queue_unpark F83'], "each with the snapshot's actions")
    check('New & <i>one</i>' in text and 'Old <script>' in text and tags == 0, 'titles are escaped', text)
    check(re.search('F0.*Done', text) and re.search('F9.*Open', text) and '2 more done tasks.' in text, 'what each is, and how many more', text)
    eq(kept, still, 'the field is the same one')
    eq(o['same'], 0, 'a refresh with the same tasks asks nothing')
    eq(o['moved'][0], 1, 'one with other tasks asks again')
    eq(o['kept'], [True, 5], 'and when that fails, it says so over what it had')
    eq(o['again'], [['Done'], True, False], 'Try again asks again')
    eq((o['url'], o['fold']), ('task/F0?t=t', True), "a done task's fold opens its text")
    check(o['none'][0] == [] and 'No task matches.' in o['none'][1], 'no match says so', o['none'])
    check(o['sent'][0] == [] and 'sent Drop D3' in o['sent'][1] and 'No task matches.' in o['sent'][1], 'a press under way shows, and is no match', o['sent'])
    check('Loading…' in o['next'] and 'No task' not in o['next'], 'other words are not said to match nothing before their answer', o['next'])
    check(o['failed'][0] == [] and 'Could not reach the run page.' in o['failed'][1] and 'No task' not in o['failed'][1],
          'a failed read says so, not that nothing matches', o['failed'])
    eq(o['cleared'], [['Queue', 'Parked'], ['B2', 'F83', 'D3'], '', [True, True], 0, None], 'the x brings the groups back, with focus')
    eq(o['blank'], [['Queue', 'Parked'], 0], 'and spaces are no search')
    eq(o['lateGone'], [['Queue', 'Parked'], None], 'an answer after the field is emptied changes nothing')


PLAN_DRIVER = DOM + r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const logic = page.split('<script id="logic">')[1].split('</script>')[0].replace(/if\(typeof module[^\n]*/, '');
const line = a => page.slice(page.indexOf(a), page.indexOf('\n', page.indexOf(a)) + 1), slice = (a, b) => page.slice(page.indexOf(a), page.indexOf(b, page.indexOf(a)));
const grab = a => page.slice(page.indexOf(a), page.indexOf('\n}\n', page.indexOf(a)) + 3);
const S = {f: {}, ob: [], taskOpen: {}, tasks: {}, sure: null, snap: JSON.parse(process.argv[3])}, I = {chev: '', x: 'x'}, MO = {}, T = 't', HKEY = '';
const obCards = () => '', oldRunHTML = x => x, emptyCard = t => t, taskInView = () => {}, working_ = () => [], render = () => { root.innerHTML = planHTML() };
const fetch = async () => ({json: async () => ({ok: true, text: 'whole text'})});
eval(logic + ['const esc=', 'const taskChip=', 'const tq=', 'const card=', 'const controlsOf=', 'const controlOf=', 'const ctlBusy=', 'const sureHTML=', 'const ctlSure=', 'const obActs=', 'const actBtns=', 'const actSure=', 'const taskIsOpen=', 'const chatBtn=', 'const planCard=', 'const nextReleaseRow=', 'const nextReleaseCard=', 'const queueCard='].map(line).join('')
  + slice('/* F429b: the menu on a Plan', 'function rowMenuOpen(') + slice('/* F429c: the grip of a Plan queue row (a', '/* the drag: the row goes') + slice('const taskBtns=', '/* F186: a release') + line('const relDrop=') + slice('/* F426b: an open release', '/* F131: the auto') + ['function taskRow(', 'async function openTask(', 'function parkedCard(', 'function shelvedCard(', 'function newReleaseCard('].map(grab).join('')
  + slice('/* F212: the search', '/* F87: the Concepts view') + "const cutsOff=()=>'';Object.assign(globalThis, {render, openTask});");
const opened = () => root.querySelectorAll('[data-task]').filter(e => e.getAttribute('aria-expanded') === 'true').map(e => e.dataset.list + ' ' + e.dataset.task);
const btns = () => root.querySelectorAll('[data-k]').filter(e => e.dataset.k.startsWith('acts:')).map(e => [e.dataset.k, e.all.filter(b => b.nodeName === 'button').map(b => b.text)]);
(async () => {
  const out = {}; render(); out.shut = [opened(), planHTML()];
  await openTask('F1', 'queue'); await openTask('B2', 'queue'); await openTask('D3', 'parked'); await openTask('F83', 'parked'); out.lists = [opened(), btns()];
  await openTask('V5', 'queue'); out.rel = [opened(), btns(), planHTML()];
  await openTask('F7', 'wait:V5'); out.unseen = btns(); await openTask('B2', 'wait:V5'); S.sure = 'queue_drop:B2'; render(); out.waits = [opened(), root.querySelectorAll('[data-k]').map(e => e.dataset.k)];
  await openTask('V6', 'queue'); out.other = [opened(), root.text];
  await openTask('V6', 'queue'); out.closed = opened();
  // F195c: through the page's own click line, closest() from the pressed element up
  const up = (e, p = root, way = []) => p === e ? way : p.childNodes ? p.childNodes.map(c => up(e, c, way.concat([p]))).find(Boolean) : null;
  const tap = async el => { const way = [...up(el), el].reverse(), q = s => way.find(e => e.hasAttribute && e.hasAttribute(s.slice(1, -1))); let x;
    await eval('(async()=>{' + line("  if(x=q('[data-task]'))").replace('openTask(', 'await openTask(') + '})()') };
  const shut = () => { S.taskOpen = {}; render() }, head = id => root.querySelectorAll('[data-task]').find(e => e.dataset.task === id);
  out.taps = {}; for (const id of ['F1', 'V5', 'V6']) { shut(); const h = head(id), words = h.all.find(e => e.nodeName === 'b'); await tap(words); out.taps[id] = [opened(), h.nodeName, h.getAttribute('tabindex'), h.hasAttribute('disabled'), h.all.filter(e => e !== h && ['button', 'a', 'input'].includes(e.nodeName)).length] }
  shut(); out.off = [];
  for (const cls of ['grip', 'rowmenu', 'ico']) for (const id of ['F1', 'V5']) { shut(); const b = new Node(1, 'button'); b.setAttribute('class', cls); const c = root.querySelectorAll('[data-k]').find(e => e.dataset.k === 'task:' + id); c.insertBefore(b, null); await tap(b); out.off.push(opened()) }
  shut(); await tap(head('F1')); for (const b of root.querySelectorAll('[data-ctl]').concat(root.querySelectorAll('[data-about]'))) await tap(b); out.acts = opened();
  console.log(JSON.stringify(out));
})();
"""


def test_plan_lists_f426b(tmp: Path) -> None:
    """F426b, F195c: the Plan view's Queue has the releases at their place; an open release opens to the tasks it waits for, each opening too; one
    row of a list is open; Chat is the last button; the search sticks."""
    page = W.PAGE.read_text(encoding='utf-8')
    plan = page.split('const planField=', 1)[1].split('\n', 1)[0]
    check('<div class="planq">' in plan and re.search(r'\.planq\{position:sticky;top:0;[^}]*background:var\(--bg\)', page), 'the search sticks', plan)
    check('`${planField()}<div class="col">' in page, 'outside the grid, where a sticky row would go with its own cell')
    check('openTask(x.dataset.task,x.dataset.list)' in page, 'a press names its list')
    if not shutil.which('node'):
        print('  (no node here: the Plan lists script test is skipped)')
        return
    row = lambda t, waits, w: {'id': t, 'title': 'Release', 'words': w, 'waits': waits, 'note': ' (not B9)', 'placeholder': False}  # noqa: E731
    waits = [{'id': 'F1', 'title': 'Board'}, {'id': 'B2', 'title': 'Retry'}, {'id': 'F7', 'title': 'Unseen'}]
    r5, r6 = row('V5', waits, 'waits for 3: F1 Board, B2 Retry, F7 Unseen'), row('V6', [], 'next')
    acts = ['queue_priority', 'queue_take', 'queue_drop']
    q = [{'id': 'F1', 'title': 'Board', 'state': 'ready', 'acts': acts},
         {'id': 'V5', 'title': 'Release', 'state': 'after', 'acts': acts, 'release': r5}, {'id': 'B2', 'title': 'Retry', 'state': 'ready', 'acts': acts},
         {'id': 'F83', 'title': 'Later', 'state': 'parked', 'acts': ['queue_unpark', 'queue_drop']},
         {'id': 'V6', 'title': 'Release', 'state': 'running', 'acts': ['queue_take'], 'release': r6}]
    old = {'id': 'V4', 'title': 'Release 1.2.0', 'state': 'released', 'words': 'released 10:00', 'placeholder': True}
    snap = {'queue': q, 'shelved': [{'id': 'D3', 'title': 'Shelf', 'state': 'shelved', 'acts': ['shelved_back']}], 'releases': [r5, r6, old],
            'release_acts': ['release_now'], 'sessions': [], 'controls': U.controls()}
    (tmp / 'plan.js').write_text(PLAN_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'plan.js'), str(W.PAGE), json.dumps(snap)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node opens the rows', r.stderr[-1500:])
    if r.returncode:
        return
    o = json.loads(r.stdout)
    html = o['shut'][1]
    top, queue = html.split('>Queue<', 1)
    eq((o['shut'][0], top.count('class="card'), 'V4' in html), ([], 1, False), 'New release above the Queue, none landed, all shut')
    at = [queue.index(f'data-task="{t}"') for t in ('F1', 'V5', 'B2', 'V6')]
    eq((at, 'queue_drop' in queue.split('>Parked<')[0]), (sorted(at), False), 'the releases at their place')
    eq(o['lists'][0], ['queue B2', 'parked F83'], 'one row open in each list')
    for k, labels in o['lists'][1] + o['rel'][1]:
        eq((labels[-1], labels.count('Chat')), ('Chat', 1), f'{k}: Chat is last')
    drop = {c['key']: c['label'] for c in U.controls()}['queue_drop']
    eq(o['rel'][0], ['queue V5', 'parked F83'], 'the release opens, in the Queue, where it is the one row')
    eq(dict(map(tuple, ((k, tuple(v)) for k, v in o['rel'][1])))['acts:V5'], (drop, 'Chat'), 'a release has Drop, then Chat')
    for t in ('F1', 'B2', 'F7'):
        check(f'data-task="{t}" data-list="wait:V5"' in o['rel'][2], f'it lists {t}')
    check('waits for 3 (not B9)' in o['rel'][2], 'its line is the count, as the list names them')
    eq(o['waits'][0], ['queue V5', 'wait:V5 B2', 'parked F83'], 'and its tasks open, one at a time; a task is open in one list')
    check(not any('F7' in k for k, _ in o['unseen']), 'one the snapshot does not have: its text alone', o['unseen'])
    check('sure' in o['waits'][1], 'its question is asked there')
    eq(len(o['waits'][1]), len(set(o['waits'][1])), 'no key is drawn twice')
    eq(o['other'][0], ['queue V6', 'parked F83'], 'another release shuts the first')
    check('whole text' in o['other'][1], 'one that waits for nothing opens to its text', o['other'][1])
    eq(o['closed'], ['parked F83'], 'a second press shuts it')
    for t in ('F1', 'V5', 'V6'):  # F195c: a <button>: Enter and Space press it
        eq(o['taps'][t], [['queue ' + t], 'button', None, False, 0], f'a tap on the words of {t} opens it; its one focusable control')
    eq(o['off'], [[]] * 6, "a press on a grip, a menu button or an icon beside a task's or release's words opens nothing")
    eq(o['acts'], ['queue F1'], "nor do the actions and Chat change what is open")


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_real_action), in_tmp(test_run_controls), in_tmp(test_row_actions), in_tmp(test_start), in_tmp(test_diff), in_tmp(test_parked), in_tmp(test_shelved_f184), in_tmp(test_concepts_view), in_tmp(test_release_row_f131), in_tmp(test_new_drop_release_f186), in_tmp(test_manage_releases_f193), in_tmp(test_task_text_f85), in_tmp(test_need_heading_b793a), in_tmp(test_run_card_b763a), in_tmp(test_search_f212), in_tmp(test_plan_lists_f426b)]))
