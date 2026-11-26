"""The run page: a pressed run control shows its result in the same frame (B851a, 033-control.logic.js).

    python3 tests/test_web_control_press.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from _check import check, eq, has, report

from agent_runner import web as W

DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8');
const logic = page.split('<script id="logic">')[1].split('</script>')[0];
const m = new Function(logic.replace(/if\(typeof module[^\n]*/g, '') + ';return {ctlWant, ctlSettle, ctlHold}')();
const snap = (o) => ({up: true, slots: 2, run: {paused: false, stopping: false, forced: false, state: 'Running'},
  card: ['slot_remove', 'slot_add', 'pause', 'stop'], shown: ['force', 'pause'], ...o});
const out = {};
const press = (key, s, at, n) => ({key, cid: 'c-' + key, at, n, want: m.ctlWant(key, s, n), say: key});
// a press of Pause: drawn at once
let s = snap(), held = [press('pause', s, 0)];
let h = m.ctlSettle(s, held, [{cid: 'c-pause', state: 'sending'}], 10); m.ctlHold(s, h.held);
out.now = {card: s.card, state: s.run.state, mark: s.run.mark, held: h.held.length};
// drawn again with no new snapshot: still held (the run's own values are kept)
h = m.ctlSettle(s, h.held, [], 20); m.ctlHold(s, h.held);
out.again = {held: h.held.length, card: s.card};
// a late snapshot that does not say it yet
s = {...s, ...snap()}; h = m.ctlSettle(s, h.held, [], 5000); m.ctlHold(s, h.held);
out.late = {held: h.held.length, state: s.run.state};
// one that agrees
s = {...s, ...snap({run: {paused: true, state: 'Paused'}, card: ['slot_remove', 'slot_add', 'go_on', 'stop']})};
h = m.ctlSettle(s, h.held, [], 6000); m.ctlHold(s, h.held);
out.agrees = {held: h.held.length, card: s.card, mark: s.run.mark || ''};
// a failure puts it back at once
s = snap(); held = [press('stop', s, 0)];
h = m.ctlSettle(s, held, [{cid: 'c-stop', state: 'failed'}], 10); m.ctlHold(s, h.held);
out.failed = {held: h.held.length, card: s.card, state: s.run.state};
// 15 s with no snapshot agreeing: what the run says, with an error
s = snap(); held = [press('force', s, 0)];
h = m.ctlSettle(s, held, [], 100); m.ctlHold(s, h.held); out.forced = {shown: s.shown, state: s.run.state};
s = {...s, ...snap()}; h = m.ctlSettle(s, h.held, [], 15000); m.ctlHold(s, h.held);
out.timeout = {held: h.held.length, err: h.err, shown: s.shown, state: s.run.state};
// slots
s = snap(); held = [press('slot_add', s, 0), press('slots_set', s, 0, '5')];
h = m.ctlSettle(s, held, [], 10); m.ctlHold(s, h.held); out.slots = s.slots;
out.down = m.ctlWant('pause', {up: false});
console.log(JSON.stringify(out));
"""


def test_control_press_b851a() -> None:
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
    eq(o['now'], {'card': ['slot_remove', 'slot_add', 'go_on', 'stop'], 'state': 'Paused', 'mark': 'Pausing…',
                  'held': 1}, 'Pause turns into Go on at once, the pill says Paused, with a quiet mark')
    eq(o['again'], {'held': 1, 'card': ['slot_remove', 'slot_add', 'go_on', 'stop']}, 'a redraw keeps it')
    eq(o['late'], {'held': 1, 'state': 'Paused'}, 'an older snapshot does not undo it')
    eq(o['agrees'], {'held': 0, 'card': ['slot_remove', 'slot_add', 'go_on', 'stop'], 'mark': ''},
       'a snapshot that agrees ends the hold')
    eq(o['failed'], {'held': 0, 'card': ['slot_remove', 'slot_add', 'pause', 'stop'], 'state': 'Running'},
       'a failure puts it back at once')
    eq(o['forced'], {'shown': ['caps_on', 'pause'], 'state': 'Caps forced'}, 'Force turns into Caps back on')
    eq(o['timeout']['held'], 0, 'after 15 s the hold ends')
    eq([o['timeout']['shown'], o['timeout']['state']], [['force', 'pause'], 'Running'], 'and shows what the run says')
    has(o['timeout']['err'], 'has not shown', 'with a plain error')
    eq(o['slots'], 5, 'Slot +1 and Set slots change the count')
    eq(o['down'], None, 'nothing is held with no run up')


def test_wired_b851a() -> None:
    page = W.PAGE.read_text(encoding='utf-8')
    check('ctlHold(S.snap,S.held)' in page, 'obHide lays the presses over the snapshot')
    check('data-k="heldmark"' in page and 'data-k="heldErr"' in page, 'the Run card draws the mark and the error')


if __name__ == '__main__':
    raise SystemExit(report([test_control_press_b851a, test_wired_b851a]))
