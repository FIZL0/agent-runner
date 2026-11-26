"""The run page: pressing a run control twice (B851b, 033-control.logic.js, 183-click.js).

    python3 tests/test_web_control_twice.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from _check import check, eq, report

from agent_runner import web as W

DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8');
const logic = page.split('<script id="logic">')[1].split('</script>')[0];
const m = new Function(logic.replace(/if\(typeof module[^\n]*/g, '') + ';return {ctlWant, ctlSettle, ctlHold, ctlTwice}')();
const snap = () => ({up: true, slots: 2, run: {paused: false, stopping: false, forced: false, state: 'Running'},
  card: ['slot_remove', 'slot_add', 'pause', 'stop'], shown: ['force', 'pause']});
const out = {};
// the page's own path: outbox() keeps one held press per thing, a later one in place of the earlier
let held = [], sent = [];
const press = (s, key, n) => {
  if (m.ctlTwice(key, held)) return;
  const w = m.ctlWant(key, s, n); sent.push(key);
  held = held.filter(p => !Object.keys(p.want).some(k => k in w)).concat([{key, cid: 'c' + sent.length, at: 0, want: w}]);
  m.ctlHold(s, m.ctlSettle(s, held, [], 1).held);
};
let s = snap(); press(s, 'pause'); press(s, 'pause');
out.pause = {sent: [...sent], paused: s.run.paused};
press(s, 'go_on'); out.goOn = {sent, paused: s.run.paused, card: s.card};
s = snap(); held = []; sent = []; press(s, 'slot_add'); press(s, 'slot_add'); press(s, 'slot_add');
out.slots = {sent: sent.length, slots: s.slots};
s = snap(); held = []; sent = []; press(s, 'stop'); press(s, 'stop'); out.stop = sent;
console.log(JSON.stringify(out));
"""


def test_control_twice_b851b() -> None:
    if not shutil.which('node'):
        print('  (no node here: the run control test is skipped)')
        return
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / 'page.html').write_text(W.PAGE.read_text(encoding='utf-8'), encoding='utf-8')
        (Path(d) / 'd.js').write_text(DRIVER, encoding='utf-8')
        r = subprocess.run(['node', str(Path(d) / 'd.js'), str(Path(d) / 'page.html')], capture_output=True, text=True,
                           timeout=60)
    check(r.returncode == 0, 'node runs', r.stderr[-800:])
    o = json.loads(r.stdout)
    eq(o['pause'], {'sent': ['pause'], 'paused': True}, 'a second Pause while one is pending is not sent')
    eq(o['goOn'], {'sent': ['pause', 'go_on'], 'paused': False,
                   'card': ['slot_remove', 'slot_add', 'pause', 'stop']}, 'Go on after Pause goes, in order')
    eq(o['slots'], {'sent': 3, 'slots': 5}, 'quick Slot +1 presses each count')
    eq(o['stop'], ['stop'], 'a second Stop is not sent')


def test_wired_b851b() -> None:
    page = W.PAGE.read_text(encoding='utf-8')
    check('ctlTwice(c.key,S.held)' in page, 'the click checks for a pending press before the outbox')


if __name__ == '__main__':
    raise SystemExit(report([test_control_twice_b851b, test_wired_b851b]))
