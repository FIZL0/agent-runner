"""The run page, Home's Start card: no run is up, so Home starts one in one tap (F402c).

    python3 tests/test_web_home_start.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from _check import check, eq, report

from agent_runner import ui_model as U
from agent_runner import web as W
from _web import fake_repo, in_tmp, logic_js

DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const line = a => page.slice(page.indexOf(a), page.indexOf('\n', page.indexOf(a)) + 1);
const grab = a => page.slice(page.indexOf(a), page.indexOf('\n}\n', page.indexOf(a)) + 3);
const logic = page.split('<script id="logic">')[1].split('</script>')[0].split('if(typeof module').join('if(false&&typeof module');
const S = {ob: [], atts: {}, f: {}, view: 'home', thread: null, snap: null};
const no = () => '', env = {S, I: {}, DK: {}, LOGO: no, greeting: no, keysLine: no, ttydLine: no, needsSec: no, dictWhy: no, micWhy: no, shownSession: no, busy: no,
  sessWorks: no, modelOf: no, enterHint: no, boxKey: () => 'home', homeChips: no, homeSums: no, homeBox: no};
const names = ['const esc=', 'const card=', 'const controlOf=', 'const ctlBusy=', 'const obBtns='];
const src = logic + names.map(line).join('') + ['box', 'homeHTML', 'homeStart'].map(f => grab(`function ${f}(`)).join('');
const home = new Function('env', 'with(env){' + src.replace(/^const /gm, 'var ') + '; return homeHTML}')(env);
console.log(JSON.stringify(JSON.parse(require('fs').readFileSync(0, 'utf8')).map(([snap, ob]) => { S.snap = snap; S.ob = ob || []; return home() })));
"""


def test_home_start_f402c(tmp: Path) -> None:
    """F402c: with no run up Home's first card says Not running, with the one accent button; what a start does stands there."""
    if not shutil.which('node'):
        print('  (no node here: the Start card test is skipped)')
        return
    fake_repo(tmp)
    def snap(up, boot='b1'):
        return {'up': up, 'boot': boot, 'sessions': [], 'needs': [], 'queue': [], 'controls': U.controls(), **U.controls_shown(up, {}, {})}
    start = {'cid': 'x1', 'ctl': 'start:', 'name': 'run_control', 'args': {'key': 'start'}}
    cases = [[snap(False)], [snap(False), [{**start, 'state': 'sending'}]],
             [snap(False), [{**start, 'state': 'failed', 'err': 'port <8000> is taken'}]], [snap(True)], [snap(False, '')],
             [snap(True), [{**start, 'state': 'failed', 'err': 'late'}]]]
    (tmp / 'd.js').write_text(DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'd.js'), str(W.PAGE)], input=json.dumps(cases), capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node draws Home', r.stderr[-1500:])
    if r.returncode:
        return
    off, busy, bad, up, old, late = json.loads(r.stdout)
    check(0 <= off.find('data-k="start"') < off.find('class="greet"'), 'the Start card is at the top', off)
    check('<b>Not running</b>' in off, 'Not running')
    eq((off.count('data-ctl="start"'), off.count('btn acc')), (1, 1), 'one Start button, the one accent')
    check('data-form' in off, 'the message box is there')
    for k in ('pause', 'stop', 'slot_add'):
        check(f'data-ctl="{k}"' not in off, f'no {k}')
    check('Starting the run…' in busy and 'btn acc busy' in busy and 'livedot' in busy, 'starting, in place', busy)
    check('Not started: port &lt;8000&gt; is taken' in bad and 'data-obretry="x1"' in bad and 'data-obdrop="x1"' in bad, 'a failure, in place, with Retry', bad)
    check('data-ctl="start"' not in bad, 'Retry stands in for Start')
    for h, what in ((up, 'a run is up'), (old, 'a kept snapshot'), (late, 'a run that came up after a failed start')):
        check('data-k="start"' not in h and 'btn acc talkbig' in h, f'{what}: no Start card, Talk is the accent', h)


def test_banner_f402c(tmp: Path) -> None:
    """F402c: the run-off banner is not on Home, whose Start card says it; every other view but Status has it."""
    if not shutil.which('node'):
        return
    s = {'up': False, 'boot': 'b', 'shown': U.controls_shown(False, {}, {})['shown']}
    got = logic_js([['runOff', s, {'view': v}] for v in ('home', 'status', 'plan', 'talk')]
                   + [['runOff', s, {'view': 'home', 'thread': 'c1'}], ['runStarts', s], ['runStarts', {**s, 'up': True}]])
    eq(got, [False, False, True, True, True, True, False], 'where the banner shows')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_home_start_f402c), in_tmp(test_banner_f402c)]))
