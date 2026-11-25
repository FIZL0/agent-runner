"""F429d: a finger moves a Plan queue row: hold until it lifts, then drag (agent_runner/page/076-plan-lift.*).

    python3 tests/test_web_plan_lift.py        (a temp repo; the script part needs node)
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from _check import check, eq, report

from agent_runner import ui_model as U  # noqa: E402
from agent_runner import web as W  # noqa: E402
from _web import in_tmp  # noqa: E402
from test_web_plan_grip import DRIVER as GRIP  # noqa: E402
from test_web_plan_menu import HOLD, REMOVE, TOP  # noqa: E402

LIFT = Path(W.__file__).parent / 'page' / '076-plan-lift.js'

# the grip test's page, with the lift's script and touches that bubble from the pressed element
DRIVER = GRIP.split("(async () => {\n  const out = {}; S.planMenu")[0] \
    .replace('const setTimeout = f => { later.push(f) };', 'const setTimeout = f => { later.push(f); return f }, clearTimeout = f => { const i = later.indexOf(f); if (i >= 0) later.splice(i, 1) };') \
    .replace("addEventListener: (t, f) => (on[t] = on[t] || []).push(f)};", "addEventListener: (t, f, o) => { (on[t] = on[t] || []).push(f); (how[t] = how[t] || []).push(o) }};") \
    .replace(', scrolled = 0;', ', glides = 0;').replace('scrolled++', 'glides++') \
    .replace('let noClick = false', 'const how = {}, HINT = {down: 1}, scrollers = () => [root.scrollTop], scrolled = a => a[0] !== root.scrollTop; let SW = null; let noClick = false', 1) \
    .replace('contains: c => s.has(c)', 'contains: c => s.has(c) || cls(this, c)') \
    .replace('+ "const cutsOff', "+ require('fs').readFileSync(process.argv[4], 'utf8') + \"const cutsOff") \
    .replace('{render, openTask,', '{render, openTask, LF, LIFT_MS, liftRow, setSW: x => SW = x, getSW: () => SW,') + r"""
const cls = (e, s) => (e.getAttribute('class') || '').split(' ').includes(s);
const opens = id => cardOf(id).all.find(e => e.nodeName === 'b');
Node.prototype.closest = function (s) { for (let x = this; x && x.getAttribute; x = x.parentNode) if (s.split(',').some(p => p[0] === '.' ? cls(x, p.slice(1)) : p[0] === '[' ? x.hasAttribute(p.slice(1, -1)) : x.nodeName === p)) return x; return null };
Object.defineProperty(Node.prototype, 'children', {get() { return this.childNodes.filter(c => c.nodeType === 1) }});
Node.prototype.addEventListener = function (t, f) { ((this.ears = this.ears || {})[t] = this.ears[t] || []).push(f) };
Node.prototype.removeEventListener = function (t, f) { const a = this.ears && this.ears[t] || []; if (a.includes(f)) a.splice(a.indexOf(f), 1) };
// a finger: its events go to the element it went down on, and to the document while that is in the page
let el = null, kept = false;
const touch = (type, pts, more) => { kept = false; const ev = {type, target: el, cancelable: true, touches: pts.map((y, i) => ({identifier: i, clientX: 50, clientY: y})), preventDefault() { kept = true }, stopImmediatePropagation() {}, ...more};
  for (const f of [...(el.ears && el.ears[type] || [])]) f(ev); if (el.isConnected) for (const f of on[type] || []) f(ev); return kept };
const down = (e, y = 125) => { el = e; touch('touchstart', [y]); return y };
const hold = () => later.splice(0).forEach(f => f());
const clear = () => { LF.now = null; SW = null; land() };
const yOf = id => 125 + 60 * at(id), ears = () => el.ears ? Object.values(el.ears).flat().length : 0;
// the browser gives a click only when the touch's end was not kept
const lift = async (id, by, e = opens(id)) => { const n = sent.length, y = down(e, yOf(id)); hold(); const up = !!GR.d; let held = true; if (by) held = touch('touchmove', [y + by]); const end = touch('touchend', []); hold(); if (!end) await tap(opens(id)); return [up, held, end, rows(), sent.slice(n), opened(), GR.d, LF.now] };
(async () => {
  const out = {}; S.planMenu = ''; render();
  out.ms = LIFT_MS; out.how = ['touchstart', 'touchmove', 'touchend', 'touchcancel'].map(t => how[t].map(o => o.passive));
  out.down = await lift('F1', 130); clear();
  out.up = await lift('V6', -190); clear();
  out.next = await lift('next-release', -190); clear();
  out.grip = await lift('F1', 130, grip('F1')); clear();
  out.still = await lift('F1', 0); clear();
  // a tap, then the same row shut again
  down(opens('F1')); out.tap = [touch('touchend', []), LF.now, later.length]; await tap(opens('F1')); out.tap.push(opened());
  const deep = cardOf('F1').all.find(e => cls(e, 'foldin')); out.details = [!!deep, liftRow(deep), liftRow(deep.all[0]), liftRow(opens('F1'))];
  await tap(opens('F1')); out.shut = opened();
  // not a lift
  out.wobble = (() => { const y = down(opens('F1')); const k = touch('touchmove', [y + 5]); hold(); const r = [k, !!GR.d]; touch('touchend', []); return r })(); clear();
  const no = f => { const n = sent.length, y = down(opens('F1')); f(y); hold(); const k = touch('touchmove', [y + 130]); const r = [!!GR.d, k, LF.now, ears()]; touch('touchend', []); return [...r, sent.length - n, rows().join()] };
  out.swipe = no(y => touch('touchmove', [y + 9])); out.side = no(y => touch('touchmove', [y], {touches: [{identifier: 0, clientX: 70, clientY: y}]}));
  out.native = no(y => touch('touchmove', [y + 1], {cancelable: false})); out.glided = no(() => { root.scrollTop += 4 }); root.scrollTop = 0;
  out.two = no(y => { touch('touchstart', [y, y + 50]); }); out.gone = no(() => touch('touchcancel', [])); out.drawer = no(() => setSW({on: true})); setSW(null);
  out.where = [['F3', 'b'], ['F8', 'b']].map(([id]) => { down(opens(id), yOf(id)); hold(); const r = !!GR.d; touch('touchend', []); return r });
  down(dots('F1')); hold(); out.dots = !!GR.d; touch('touchend', []);
  S.sheet = 'x'; down(opens('F1')); hold(); out.sheet = !!GR.d; touch('touchend', []); S.sheet = null;
  // lifted: the touch is the row's
  let y = down(opens('F1')); setSW({on: false}); hold(); out.own = [getSW(), HINT.down]; touch('touchmove', [y + 130]);
  out.room = els().map(e => e.style.transform || '');
  const n0 = sent.length; touch('touchstart', [y, 300]); out.second = [GR.d, touch('touchmove', [y + 130, 300]), touch('touchend', [300]), !!LF.now, touch('touchend', []), sent.length - n0, rows().join()]; clear();
  y = down(opens('F1')); hold(); touch('touchmove', [y + 130]); const n1 = sent.length; touch('touchcancel', []); out.cancel = [GR.d, LF.now, sent.length - n1, rows().join()]; clear();
  y = down(opens('F1')); hold(); out.menu = fire('contextmenu', {target: el}); touch('touchend', []); out.menuAfter = fire('contextmenu', {target: el}); clear();
  y = down(opens('F1')); hold(); touch('touchmove', [y + 130]); S.snap.queue[4].title = 'Changed'; render(); out.off = el.isConnected; const k = touch('touchmove', [y + 131]); const e2 = touch('touchend', []); out.redrawn = [k, e2, rows().join(), last(), ears()]; clear();
  y = down(opens('F1')); hold(); touch('touchmove', [y + 130]); S.snap.queue[0] = {...S.snap.queue[0], state: 'running s1 1m', menu: []}; S.snap.queue[3] = {...S.snap.queue[3], started: true, grip: false, menu: []}; render(); const n2 = sent.length; out.started = [touch('touchmove', [y + 131]), !!GR.d, touch('touchend', []), last()]; clear();
  down(opens('V6')); hold(); out.release = [!!GR.d, sent.length - n2]; touch('touchend', []);
  console.log(JSON.stringify(out));
})();
"""


def test_page(tmp: Path) -> None:
    """A hold lifts a row and its drag moves it, opening nothing; a tap opens it; a swipe scrolls and never lifts."""
    page = W.PAGE.read_text(encoding='utf-8')
    check(LIFT.read_text(encoding='utf-8').strip() in page.replace('\r\n', '\n'), 'the script is in the page')
    check(re.search(r'\.card:has\(>\.grip\)>:is\(\.fold,\.row\)\{[^{}]*user-select:none', page), 'a hold selects no words of the head')
    if not shutil.which('node'):
        print('  (no node here: the lift script test is skipped)')
        return
    menu = [HOLD, TOP, REMOVE]
    row = {'id': 'V6', 'title': 'Release', 'words': 'next', 'waits': [], 'note': '', 'placeholder': False}
    t = lambda i, **k: {'id': i, 'title': 'T' + i, 'state': 'ready', 'section': 'Next', 'acts': [], 'menu': menu, 'grip': True, **k}  # noqa: E731
    ph = {'id': '', 'title': 'Next release', 'state': 'auto', 'words': 'auto at 3 landed: 1/3', 'before': 'F7', 'placeholder': True, 'menu': menu, 'grip': True}
    snap = {'queue': [t('F1'), t('B2'), t('F3', state='running s1 2m', menu=[]), t('V6', release=row), t('F7'), t('F8', state='parked', section='Parked', menu=[], grip=False)],
            'shelved': [], 'releases': [row, ph], 'release_acts': [], 'sessions': [], 'controls': U.controls()}
    (tmp / 'lift.js').write_text(DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'lift.js'), str(W.PAGE), json.dumps(snap), str(LIFT)], capture_output=True, text=True, encoding='utf-8', timeout=60)
    check(r.returncode == 0, 'node lifts the rows', r.stderr[-1500:])
    if r.returncode:
        return
    o = json.loads(r.stdout)
    mv = lambda tid, where, other: {'tid': tid, 'where': where, 'other': other}  # noqa: E731
    start = ['F1', 'B2', 'F3', 'V6', 'rel:next', 'F7', 'F8']
    same = ','.join(start)
    eq(o['how'], [[True], [False], [False], [True]], 'passive, but the move that keeps the page still and the end that makes no click')
    moved = ['B2', 'F3', 'F1', *start[3:]]
    eq(o['down'], [True, True, True, moved, [mv('F1', 'after', 'F3')], [], None, None], 'held and dragged down: moved, no scroll, no details')
    eq(o['up'][3:6], [['V6', 'F1', 'B2', 'F3', *start[4:]], [mv('V6', 'before', 'F1')], []], 'a release, up')
    eq(o['next'][3:6], [['F1', 'rel:next', 'B2', 'F3', 'V6', 'F7', 'F8'], [mv('next-release', 'after', 'F1')], []], 'the Next release row')
    eq(o['grip'][3:5], [moved, [mv('F1', 'after', 'F3')]], 'from the grip too')
    eq(o['still'], [True, True, True, start, [], [], None, None], 'lifted and let go: nothing sent, nothing opened')
    eq(o['tap'], [False, None, 0, ['F1']], 'a tap opens the details')
    eq((o['details'], o['shut']), ([True, '', '', 'F1'], []), "its details' words can be held; its head still lifts")
    eq(o['wobble'], [False, True], 'a finger that wobbles still lifts it')
    for k in ('swipe', 'side', 'native', 'glided', 'gone', 'drawer', 'two'):
        eq(o[k], [False, False, None, 0, 0, same], f'{k}: no lift in that touch, and the page may scroll')
    eq((o['where'], o['dots'], o['sheet']), ([True, False], False, False), 'a running row too; not a parked row, the dots, or under a sheet')
    eq(o['own'], [None, None], 'lifted: no drawer swipe, no Hint')
    eq(o['room'][:3], ['translateY(130px)', 'translateY(-60px)', 'translateY(-60px)'], 'the others make room')
    eq(o['second'], [None, True, True, True, True, 0, same], 'a second finger puts it back, and nothing scrolls until both lift')
    eq(o['cancel'], [None, None, 0, same], 'a touch the browser took puts it back')
    eq((o['menu'], o['menuAfter']), (True, False), "the browser's long-press menu stays away while held")
    eq((o['off'], o['redrawn']), (False, [True, True, ','.join(moved), mv('F1', 'after', 'F3'), 0]), 'a redraw midway: the drag goes on')
    eq(o['started'], [True, True, True, mv('F1', 'after', 'F3')], 'a task that started meanwhile goes on')
    eq(o['release'], [False, 1], 'a release that started never lifts')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_page)]))
