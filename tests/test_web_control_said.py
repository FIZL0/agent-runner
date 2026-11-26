"""The run page: a run control's toast says plain words, never raw output or a path (B851c, 034-said.logic.js).

    python3 tests/test_web_control_said.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from _check import check, eq, report

from agent_runner import web as W

RAW = 'sent to the run: p on (it acts within 10 s; `/home/x/run status` shows it)'
DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8');
const logic = page.split('<script id="logic">')[1].split('</script>')[0];
const m = new Function(logic.replace(/if\(typeof module[^\n]*/g, '') + ';return {ctlSaid, homeSaid}')();
const RAW = process.argv[3], ok = {ok: true, out: RAW}, out = {};
for (const k of ['pause', 'go_on', 'slot_add', 'slot_remove', 'stop', 'force']) out['run_' + k] = m.ctlSaid(k, ok, true);
out.task = m.ctlSaid('Hold: Fix it', ok, false);
out.fail = m.ctlSaid('Pause', {ok: false, out: RAW}, false);
out.failWhy = m.ctlSaid('Pause', {ok: false, out: 'The run is not up'}, false);
for (const [n, a] of [['pause'], ['resume'], ['stop'], ['start'], ['slots', '5'], ['slots', '+1'], ['slots', '-1']])
  out['home_' + n + (a || '')] = m.homeSaid(n, a, n, ok);
out.homeFail = m.homeSaid('pause', '', 'Pause · p', {ok: false, out: RAW});
console.log(JSON.stringify(out));
"""


def test_control_said_b851c() -> None:
    if not shutil.which('node'):
        print('  (no node here: the toast test is skipped)')
        return
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / 'page.html').write_text(W.PAGE.read_text(encoding='utf-8'), encoding='utf-8')
        (Path(d) / 'd.js').write_text(DRIVER, encoding='utf-8')
        r = subprocess.run(['node', str(Path(d) / 'd.js'), str(Path(d) / 'page.html'), RAW], capture_output=True,
                           text=True, timeout=60)
    check(r.returncode == 0, 'node runs', r.stderr[-800:])
    o = json.loads(r.stdout)
    for k in ['pause', 'go_on', 'slot_add', 'slot_remove', 'stop', 'force']:
        eq(o['run_' + k], '', f'run page {k}: the button shows it, no toast')
    eq(o['task'], 'Hold: Fix it: done', 'a task control says plain words')
    eq(o['fail'], 'Not done: Pause', 'a failure hides raw output')
    eq(o['failWhy'], 'Not done: Pause. The run is not up', 'a plain reason is kept')
    for k in ['pause', 'resume', 'stop', 'start', 'slots5']:
        eq(o['home_' + k], '', f'Home {k}: the card shows it, no toast')
    eq([o['home_slots+1'], o['home_slots-1']], ['One more slot', 'One slot less'], 'Home slot steps say plain words')
    eq(o['homeFail'], 'Not done: Pause · p', 'Home failure hides raw output')
    for v in o.values():
        check('/' not in v and '`' not in v, 'no path in a toast', v)


if __name__ == '__main__':
    raise SystemExit(report([test_control_said_b851c]))
