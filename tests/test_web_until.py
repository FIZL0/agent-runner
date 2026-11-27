#!/usr/bin/env python3
"""F427d: the Tools page lists each check a blocked task waits on (`--until`): its label, last result and time, the
tasks that wait, and Check now; nothing when none waits.

    python3 tests/test_web_until.py        (node for the page part; a second)
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from _check import check, eq, report

from agent_runner import ui_model as M, until as U, until_watch as W, state as S  # noqa: E402

PLAN = '''# TODO

- [~] **T1** one BLOCKED: (until check:vm) wait for the vm
- [~] **T2** two BLOCKED: (until check:vm, version:0.1.0) both
- [ ] **T4** open
'''.splitlines()


def test_rows():
    print('one row per check a task waits on, with what the last round said and the tasks that wait')
    old = W.read, U.label
    W.read = lambda c=None: {'check:vm': {'at': 1700000000.0, 'state': U.NOT_YET, 'said': 'down', 'tasks': ['T1', 'T2']},
                             'check:gone': {'state': U.PASSED, 'tasks': []}}
    U.label = lambda t, c=None: 'L:' + t
    try:
        rows = M.until_rows(PLAN, {'T1': 'one', 'T2': 'two'})
        eq([r['check'] for r in rows], ['check:vm', 'version:0.1.0'], 'only the checks some task waits on')
        vm = rows[0]
        eq((vm['label'], vm['state'], vm['said']), ('L:check:vm', U.NOT_YET, 'down'), 'its label and last result')
        check(vm['at'].startswith('20'), 'its time, as an ISO stamp')
        eq(vm['tasks'], [{'id': 'T1', 'title': 'one'}, {'id': 'T2', 'title': 'two'}], 'the tasks that wait, id and title')
        eq((rows[1]['state'], rows[1]['at']), ('', ''), 'not checked yet')
        eq(M.until_rows(['# TODO', '- [ ] **T4** open'], {}), [], 'none when no task waits')
    finally:
        W.read, U.label = old


def test_check_now():
    print('Check now runs one round at once and says what it found')
    old = W.round_, W.read, U.label, S.default_branch
    W.round_ = lambda b: ['T1']
    W.read = lambda c=None: {'check:vm': {'state': U.PASSED, 'said': 'up'}}
    U.label = lambda t, c=None: 'the vm'
    S.default_branch = lambda: 'main'
    try:
        r = M.act('until_check', check='check:vm')
        check(r['ok'], 'it answers ok')
        eq(r['out'], 'the vm: passed, up. Reopened T1.', 'what it says')
        W._BUSY.acquire()
        try:
            check(not M.act('until_check', check='check:vm')['ok'], 'not while a round runs')
        finally:
            W._BUSY.release()
    finally:
        W.round_, W.read, U.label, S.default_branch = old


DRIVER = r"""
const src = require('fs').readFileSync(process.argv[2], 'utf8'), cut = (a, b) => src.slice(src.indexOf(a), src.indexOf(b, src.indexOf(a)));
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => '&#' + c.charCodeAt(0) + ';');
const card = (h, cls = '', attr = '') => `<div class="card ${cls}" ${attr}>${h}</div>`, agoWords = () => '5 min ago', S = {};
const f = new Function('S', 'esc', 'card', 'agoWords', cut('const UNTIL_STATE=', 'async function untilCheck') + '; return untilsHTML')(S, esc, card, agoWords);
console.log(JSON.stringify({none: f([]), undef: f(undefined), one: f(JSON.parse(process.argv[3]))}));
"""


def test_page():
    print('the page: a card per check, nothing when none waits')
    if not shutil.which('node'):
        print('  (no node: skipped)')
        return
    js = Path(__file__).resolve().parent.parent / 'agent_runner/page/130-tools.js'
    rows = [{'check': 'check:vm', 'label': 'The <vm>', 'state': 'cannot run', 'said': 'no ssh', 'at': '2026-01-01T00:00:00',
             'tasks': [{'id': 'T1', 'title': 'one'}]},
            {'check': 'version:0.1.0', 'label': 'version 0.1.0', 'state': '', 'said': '', 'at': '', 'tasks': []}]
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp) / 'd.js'
        d.write_text(DRIVER, encoding='utf-8')
        out = json.loads(subprocess.run(['node', str(d), str(js), json.dumps(rows)], capture_output=True, text=True, check=True).stdout)
    eq((out['none'], out['undef']), ('', ''), 'nothing when none waits')
    h = out['one']
    check('Tasks wait on' in h, 'its section')
    check('The &#60;vm&#62;' in h, 'the label, escaped')
    check('class="v-bad">Cannot run</span> · 5 min ago: no ssh' in h, 'the last result, its age and words')
    check('<b>T1</b> one' in h, 'the task that waits')
    check('Not checked yet' in h, 'a check not run yet')
    eq(h.count('data-tool="untilcheck"'), 2, 'Check now on each')
    check('Add' not in h, 'no way to add a check here')


if __name__ == '__main__':
    raise SystemExit(report([test_rows, test_check_now, test_page]))
