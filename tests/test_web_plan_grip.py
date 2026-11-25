"""F429c: the grip of a Plan queue row: a mouse drag and the arrow keys move it (agent_runner/page/074-plan-grip.*).

    python3 tests/test_web_plan_grip.py        (a temp repo; the script part needs node)
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from unittest import mock

from _check import check, eq, report

from agent_runner import plan as P, state as S  # noqa: E402
from agent_runner import ui_model as U  # noqa: E402
from agent_runner import web as W  # noqa: E402
from _web import in_tmp  # noqa: E402
from test_web_plan_menu import DRIVER as MENU, HOLD, REMOVE, TOP, order, real, repo  # noqa: E402


def test_moves(tmp: Path) -> None:
    """What the grip sends does move the row: a task, a release (it waits for what is above it), the Next release row."""
    repo(tmp)
    with mock.patch.object(U, 'RUN', [real]):
        go = lambda *a: U.act('move', tid=a[0], where=a[1], other=a[2])  # noqa: E731
        check(go('F3', 'before', 'F1')['ok'] and order()[:3] == ['F3', 'F1', 'B2'], 'a task', order())
        check(go('V6', 'after', 'F1')['ok'] and order()[:3] == ['F3', 'F1', 'V6'], 'a release among the tasks', order())
        check('after: all' in next(l for l in P.lines(S.C.todo) if '**V6**' in l), 'it waits for the tasks above it')
        check(go('F7', 'after', 'B2')['ok'] and order()[4] == 'F7', 'from another section', order())
        check(not go('F1', 'after', 'ZZ9')['ok'], 'next to no row: refused')
        P.drop('V6', 'no', S.C.todo, S.C.done)
        check(go('next-release', 'after', 'F3')['ok'] and P.release(order()[1]), 'the Next release row is a release there', order())


def test_grips(tmp: Path) -> None:
    """Which row has a grip: each, a running or under-way task's too; not a parked row or a started release."""
    repo(tmp)

    def grips(st: dict | None = None) -> str:
        ls = P.lines(S.C.todo)
        rows = U.pin_releases(U.queue_rows(ls, st or {}), U.release_rows(ls, st or {}, landed=0))
        return ' '.join(q['id'] for q in rows if q['grip'])
    tasks = 'F1 B2 F3 D4 F5 F7'
    eq(grips(), 'F1 B2 F3 D4 F5 V6 F7', 'a blocked one and a waiting release too; not the parked one')
    eq(grips({'running': {'1': 'F1', '2': 'V6'}, 'merging': ['B2']}), tasks, 'running, merging; not the release that runs')
    eq(grips({'merging': ['V6']}), tasks, 'nor one that merges')
    with mock.patch('agent_runner.sched.taken', lambda: {'F3': tmp, 'V6': tmp}):
        eq(grips(), tasks, 'taken by hand')
    with mock.patch.object(S, 'queued', lambda: {1: ('B2', 's', 'w'), 2: ('V6', 's', 'w')}):
        eq(grips(), tasks, 'waiting to resume')
    P.drop('V6', 'no', S.C.todo, S.C.done)
    ls = P.lines(S.C.todo)
    rows = U.release_rows(ls, {}, landed=1)
    U.pin_releases(U.queue_rows(ls), rows)
    eq([r['grip'] for r in rows if r['state'] == 'auto'], [True], 'the Next release row')


def test_under_way(tmp: Path) -> None:
    """A task that runs moves before or after another: its place alone, its line as it was, `after:` kept, and the slot's
    files not touched. A release that started stays put; to the top, hold and remove are refused as before."""
    repo(tmp)
    P.edit('B2', keyed=' | after: F1', todo=S.C.todo)
    P.edit('F3', keyed=' | after: B2', todo=S.C.todo)
    text = lambda: sorted(P.lines(S.C.todo))  # noqa: E731
    with mock.patch.object(U, 'RUN', [real]):
        go = lambda *a: U.act('move', tid=a[0], where=a[1], other=a[2])  # noqa: E731
        was = text()
        check(go('F1', 'after', 'V6')['ok'] and go('B2', 'before', 'F1')['ok'] and go('F3', 'after', 'F7')['ok'], 'moved, past the tasks they wait for too')
        eq((order(), text()), (['D4', 'F5', 'V6', 'B2', 'F1', 'F7', 'F3', 'F8'], was), "a normal task's move changes no line, so no after:")
        notes = {t: S.C.notes(f'{t}.resume') for t in ('B2', 'V6')}
        for n, (t, f) in enumerate(notes.items(), 1):
            f.write_text(json.dumps({'slot': n, 'sid': t, 'why': 'cut off'}), encoding='utf-8')
        kept = {t: f.read_text(encoding='utf-8') for t, f in notes.items()}
        r = go('B2', 'before', 'D4')
        check(r['ok'] and order()[:2] == ['B2', 'D4'] and text() == was, 'an under-way task moves, its line as it was', r)
        eq({t: f.read_text(encoding='utf-8') for t, f in notes.items()}, kept, 'its session goes on as it would')
        now = order()
        r = go('V6', 'before', 'D4')
        check(not r['ok'] and 'cannot be moved' in r['out'] and order() == now, 'a started release does not', r)
        for a in (('move', 'B2', 'top'), ('hold', 'B2'), ('move', 'B2', 'after', 'F8')):  # F8 is parked
            check(real(['plan', *a])[0] and order() == now and text() == was, f'{a[0]} {a[-1]}: refused as before')
    ran = P._parse_command(['move', 'F1', 'before', 'B2'])
    with mock.patch.object(P, 'run_on', lambda c, t: 's2'), mock.patch.object(P, 'cfg', lambda: S.C):
        P._p_move(ran, mock.Mock(c=S.C, todo=S.C.todo))
    eq((order()[0], text()), ('F1', was), 'in a slot: moved, every line as it was')


# the menu test's page, with the grip's whole script and its listeners, cards 50px high and 10px apart
DRIVER = MENU.split('(async () => {\n  const out')[0] \
    .replace("'/* the drag: the row goes'", "'I.grip='") \
    .replace('const $ = () => root, document = {body: root, activeElement: null, querySelector: () => null};', r"""
const on = {}, window = {addEventListener: (t, f) => (on[t] = on[t] || []).push(f)}, $ = () => root, frames = [], requestAnimationFrame = f => frames.push(f);
const document = {body: root, get activeElement() { return doc.activeElement }, querySelector: () => null, addEventListener: (t, f) => (on[t] = on[t] || []).push(f)};
const fire = (t, e) => { let kept = false; const ev = {preventDefault() { kept = true }, stopImmediatePropagation() {}, pointerId: 1, pointerType: 'mouse', button: 0, buttons: 1, ...e}; for (const f of on[t] || []) f(ev); return kept };
let noClick = false, scrolled = 0; const getComputedStyle = () => ({rowGap: '10px'}), shiftOf = () => ({m42: 0}), glideTo = () => {}, flying = () => 0, hintHide = () => {}, scrollGlide = () => { scrolled++ }; MO.fly = new Map();
const els = () => root.querySelectorAll('[data-k]').filter(e => /^(task:|rel:next)/.test(e.dataset.k) && e.parentNode.nodeName === 'div');
Object.defineProperties(Node.prototype, {style: {get() { return this._s = this._s || {} }}, parentElement: {get() { return this.parentNode }},
  classList: {get() { const s = this._c = this._c || new Set(); return {add: c => s.add(c), remove: c => s.delete(c), contains: c => s.has(c)} }},
  offsetHeight: {get() { return 50 }}, offsetTop: {get() { const i = els().indexOf(this); return i < 0 ? 0 : 100 + 60 * i }}, offsetParent: {get() { return root }}});
Node.prototype.closest = function (s) { for (let x = this; x; x = x.parentNode) if (x.hasAttribute && x.hasAttribute(s.slice(1, -1))) return x; return null };
Node.prototype.getBoundingClientRect = function () { const t = this.offsetTop - root.scrollTop; return {top: t, bottom: t + 50, height: 50} };
root.classList = new Set(); root.classList.remove = root.classList.delete; root.getBoundingClientRect = () => ({top: 0, bottom: 2000, height: 2000});
""").replace("root.querySelector = s =>", "const all0 = root.querySelectorAll.bind(root); root.querySelectorAll = s => s === '.card' ? els() : all0(s); root.querySelector = s =>") \
    .replace('render = () => { root.innerHTML = planHTML() }', 'render = () => { planDraw(root, planHTML()) }') \
    .replace("let now = 1e6;", "const setHTML = (el, h) => { if (el._h === h) return false; el._h = h; el.innerHTML = h; return true }; let now = 1e6;") \
    .replace('{render, openTask,', '{render, openTask, GR, gripPut, gripOrder,') \
    .replace("+ \"const cutsOff", "+ slice('function fieldHTML(', '/* box\\'s children') + \"const cutsOff") + r"""
const grip = id => cardOf(id).all.find(e => e.dataset.grip);
const key = (id, k, more) => { const g = grip(id); g.focus(); return fire('keydown', {key: k, target: g, ...more}) };
const last = () => sent[sent.length - 1], land = () => { S.ob = []; GR.did.length = 0; PM.did = []; now += 9000; render() };
const at = id => els().indexOf(cardOf(id));
const start = id => { const g = grip(id); fire('pointerdown', {target: g, clientY: 125 + 60 * at(id)}); return 125 + 60 * at(id) };
const move = y => fire('pointermove', {clientY: y, buttons: 1});
const drop = async (id, by) => { const n = sent.length; noClick = false; const y = start(id); if (Math.abs(by) > 5) move(y + Math.sign(by) * 5); move(y + by); fire('pointerup', {clientY: y + by}); const swallowed = noClick; later.splice(0).forEach(f => f()); await tap(grip(id) || cardOf(id)); return [rows(), sent.slice(n), opened(), swallowed, GR.d] };
(async () => {
  const out = {}; S.planMenu = ''; render();
  out.grips = rows().map(r => r === 'rel:next' ? 'next-release' : r).map(id => { const g = grip(id); return [id, g ? g.nodeName + '|' + g.getAttribute('aria-label') : '', !!g && cardOf(id).childNodes.includes(g)] });
  await tap(grip('F1')); out.tapGrip = [opened(), sent.length]; await tap(cardOf('F1').all.find(e => e.nodeName === 'b')); out.tapRow = opened(); await tap(cardOf('F1').all.find(e => e.nodeName === 'b'));
  out.down = [key('F1', 'ArrowDown'), rows(), last(), opened(), doc.activeElement === grip('F1')]; land();
  out.up = [key('B2', 'ArrowUp'), rows(), last(), opened()]; land();
  out.ends = [key('F1', 'ArrowUp'), key('F7', 'ArrowDown'), sent.length];
  out.other = [key('B2', 'ArrowDown', {shiftKey: true}), key('B2', 'ArrowDown', {ctrlKey: true}), key('B2', 'Enter'), sent.length, opened()];
  out.past = [key('V6', 'ArrowDown'), rows(), last()]; land();  // the Next release row between is no place of the plan's
  out.twice = [key('F1', 'ArrowDown'), key('F1', 'ArrowDown'), rows(), sent.slice(-2)]; land();
  key('B2', 'ArrowUp'); S.ob[S.ob.length - 1].state = 'failed'; render(); out.failed = [rows(), planHTML().includes('[failed Move B2 before F1]')]; land();
  out.next = [key('next-release', 'ArrowUp'), rows(), last(), !grip('next-release'), sent.length]; land();
  out.dragDown = await drop('F1', 130); land();
  out.dragUp = await drop('V6', -190); land();
  out.dragNext = await drop('next-release', -190); land();
  out.kids = await drop('B2', 130); out.kidPut = gripPut([{id: 'P1'}, {id: 'P1a'}, {id: 'F2'}, {id: 'P10'}], 'P1', 1).map(x => x.id); land();
  out.little = await drop('F1', 2); out.back = await drop('F1', 20);
  let y = start('F1'); move(y + 130); out.room = [els().map(e => e.style.transform || ''), fire('keydown', {key: 'Escape', target: root}), GR.d, sent.length]; out.esc = rows();
  y = start('F1'); move(y + 130); fire('pointermove', {clientY: y + 130, buttons: 0}); out.lost = [GR.d, rows()];
  fire('pointerdown', {target: grip('F1'), clientY: 125, pointerType: 'touch'}); fire('pointerdown', {target: grip('F1'), clientY: 125, button: 2}); fire('pointerdown', {target: cardOf('F1').all.find(e => e.nodeName === 'b'), clientY: 125}); out.none = GR.d;
  y = start('F1'); move(y + 130); S.snap.queue[4].title = 'Changed'; render(); move(y + 131); fire('pointerup', {}); out.redrawn = [rows(), last()]; land();
  out.runDrag = await drop('F3', -130); out.dots = !!dots('F3'); land();
  out.runKey = [key('F3', 'ArrowDown'), rows(), last()]; land();
  y = start('F1'); move(y + 130); S.snap.queue[0] = {...S.snap.queue[0], state: 'running s1 1m', menu: []}; render(); move(y + 131); fire('pointerup', {}); out.ran = [rows(), last(), !!grip('F1')]; land();
  y = start('V6'); move(y - 130); S.snap.queue[3] = {...S.snap.queue[3], started: true, grip: false, menu: []}; render(); const n = sent.length; move(y - 131); fire('pointerup', {}); out.started = [GR.d, sent.length - n, !!grip('V6'), rows()];
  PM.did = [{id: 'F7', k: 'menu_remove', back: true, cid: 'x', at: now, ms: 9000, q: {...S.snap.queue[4]}, down: []}]; const f7 = S.snap.queue.splice(4, 1); render(); out.undone = [rows().includes('F7'), !!grip('F7')]; S.snap.queue.splice(4, 0, ...f7); render(); out.back = [out.back, !!grip('F7')]; PM.did = [];
  S.f.planq = 'x'; PM.did = []; out.search = planHTML().includes('data-grip');
  console.log(JSON.stringify(out));
})();
"""


def test_page(tmp: Path) -> None:
    """The grip, a drag and the keys move a row and open none; a tap on the row does; a running row too, not a started release."""
    page = W.PAGE.read_text(encoding='utf-8')
    check(re.search(r'\.card>\.grip\{[^{}]*touch-action:pan-y', page), 'a swipe that starts on it scrolls')
    if not shutil.which('node'):
        print('  (no node here: the grip script test is skipped)')
        return
    menu = [HOLD, TOP, REMOVE]
    row = {'id': 'V6', 'title': 'Release', 'words': 'next', 'waits': [], 'note': '', 'placeholder': False}
    t = lambda i, **k: {'id': i, 'title': 'T' + i, 'state': 'ready', 'section': 'Next', 'acts': [], 'menu': menu, 'grip': True, **k}  # noqa: E731
    ph = {'id': '', 'title': 'Next release', 'state': 'auto', 'words': 'auto at 3 landed: 1/3', 'before': 'F7', 'placeholder': True, 'menu': menu, 'grip': True}
    snap = {'queue': [t('F1'), t('B2'), t('F3', state='running s1 2m', menu=[]), t('V6', release=row), t('F7'), t('F8', state='parked', section='Parked', menu=[], grip=False)],
            'shelved': [], 'releases': [row, ph], 'release_acts': [], 'sessions': [], 'controls': U.controls()}
    (tmp / 'grip.js').write_text(DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'grip.js'), str(W.PAGE), json.dumps(snap)], capture_output=True, text=True, encoding='utf-8', timeout=60)
    check(r.returncode == 0, 'node moves the rows', r.stderr[-1500:])
    if r.returncode:
        return
    o = json.loads(r.stdout)
    mv = lambda tid, where, other: {'tid': tid, 'where': where, 'other': other}  # noqa: E731
    on = lambda i, n='': [i, f'button|Move {n or i}: drag, or arrow up and down', True]  # noqa: E731
    eq(o['grips'], [on('F1'), on('B2'), on('F3'), on('V6'), on('next-release', 'Next release'), on('F7'), ['F8', '', False]],
       "a button of the card, outside its head; a running row's too; none on a parked one")
    eq((o['tapGrip'], o['tapRow']), ([[], 0], ['F1']), 'a press on it opens nothing; a tap on the row does')
    start = ['F1', 'B2', 'F3', 'V6', 'rel:next', 'F7', 'F8']
    eq(o['down'], [True, ['B2', 'F1', *start[2:]], mv('F1', 'after', 'B2'), [], True], 'arrow down: one place, at once; the focus stays on it')
    eq(o['up'], [True, ['B2', 'F1', *start[2:]], mv('B2', 'before', 'F1'), []], 'arrow up')
    eq(o['ends'], [True, True, 2], 'at an end nothing is sent')
    eq(o['other'], [False, False, False, 2, []], 'no other key does anything')
    eq(o['past'], [True, ['F1', 'B2', 'F3', 'rel:next', 'F7', 'V6', 'F8'], mv('V6', 'after', 'F7')], 'past the Next release row, which is no place in the plan')
    eq(o['twice'], [True, True, ['B2', 'F3', 'F1', *start[3:]], [mv('F1', 'after', 'B2'), mv('F1', 'after', 'F3')]], 'two presses: two places, past a running one')
    eq(o['failed'], [start, True], 'one that failed is taken back, and says so')
    eq(o['next'][1:], [['F1', 'B2', 'F3', 'rel:next', 'V6', 'F7', 'F8'], mv('next-release', 'after', 'F3'), True, o['next'][4]], 'the Next release row by its name')
    eq(o['next'][4], 7, 'moved, it is a release: no second move by that name')
    eq(o['dragDown'], [['B2', 'F3', 'F1', *start[3:]], [mv('F1', 'after', 'F3')], [], True, None], 'a drag down; its click opens nothing')
    eq(o['dragUp'], [['V6', 'F1', 'B2', 'F3', *start[4:]], [mv('V6', 'before', 'F1')], [], True, None], 'a release dragged to the top')
    eq(o['dragNext'][:2], [['F1', 'rel:next', 'B2', 'F3', 'V6', 'F7', 'F8'], [mv('next-release', 'after', 'F1')]], 'the Next release row dragged')
    eq(o['kids'][1], [mv('B2', 'after', 'V6')], 'among the releases')
    eq(o['kidPut'], ['F2', 'P1', 'P1a', 'P10'], "a task's subtasks go with it")
    eq(o['little'], [start, [], [], False, None], 'a press that hardly moves is no drag')
    eq(o['back'][0], [start, [], [], True, None], 'dropped where it was: nothing sent')
    eq(o['room'][0], ['translateY(130px)', 'translateY(-60px)', 'translateY(-60px)', '', '', '', ''], 'the row goes with the mouse, the others make room')
    eq((o['room'][1:3], o['esc'], o['lost']), ([True, None], start, [None, start]), 'Esc, and a release outside the window, put it back')
    eq(o['none'], None, 'no touch, no other button, no drag from the row itself')
    eq(o['redrawn'], [['B2', 'F3', 'F1', *start[3:]], mv('F1', 'after', 'F3')], 'a redraw midway: the drag goes on')
    eq(o['runDrag'], [['F3', 'F1', 'B2', *start[3:]], [mv('F3', 'before', 'F1')], [], True, None], 'a running row dragged')
    eq((o['dots'], o['runKey']), (False, [True, ['F1', 'B2', 'V6', 'F3', *start[4:]], mv('F3', 'after', 'V6')]), 'and by the keys; no three-dot menu')
    eq(o['ran'], [['B2', 'F3', 'F1', *start[3:]], mv('F1', 'after', 'F3'), True], 'a task that started meanwhile is moved')
    eq(o['started'], [None, 0, False, start], 'a release that started meanwhile is not')
    eq((o['undone'], o['back'][1]), ([True, False], True), 'a row whose Remove is undone: once the plan has it')
    eq(o['search'], False, 'none in a search')


# a row of each kind, shut, opened, and with its menu's icons, as the page draws them
PLACE = DRIVER.split('(async () => {')[0] + r"""
(async () => {
  const out = {}, html = s => { const h = planHTML(); out[s] = h.slice(h.indexOf('<div class="col">')) };
  S.planMenu = ''; render(); html('shut');
  for (const id of ['F1', 'F3', 'V6']) { await tap(cardOf(id).all.find(e => e.nodeName === 'b')); out['opened ' + id] = opened(); html('open ' + id); await tap(cardOf(id).all.find(e => e.nodeName === 'b')) }
  S.planMenu = 'F1'; html('icons');
  console.log(JSON.stringify(out));
})();
"""


def test_place_b830(tmp: Path) -> None:
    """The grip is in the card at the same place on a row with a three-dot menu and one without, shut and open, and a
    press there meets it. Measured in Chromium at phone width."""
    chrome = next(filter(None, map(shutil.which, ('chromium', 'chromium-browser', 'google-chrome'))), None)
    if not chrome or not shutil.which('node'):
        print('  (no node or Chromium here: the grip place test is skipped)')
        return
    menu = [HOLD, TOP, REMOVE]
    row = {'id': 'V6', 'title': 'Release', 'words': 'next', 'waits': [], 'note': '', 'placeholder': False}
    t = lambda i, **k: {'id': i, 'title': 'T' + i, 'state': 'ready', 'section': 'Next', 'acts': [], 'menu': menu, 'grip': True, **k}  # noqa: E731
    ph = {'id': '', 'title': 'Next release', 'state': 'auto', 'words': 'auto at 3 landed: 1/3', 'before': 'F7', 'placeholder': True, 'menu': menu, 'grip': True}
    snap = {'queue': [t('F1'), t('F3', state='running s1 2m', menu=[]), t('V6', release=row), t('F7')],
            'shelved': [], 'releases': [row, ph], 'release_acts': [], 'sessions': [], 'controls': U.controls()}
    (tmp / 'place.js').write_text(PLACE, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'place.js'), str(W.PAGE), json.dumps(snap)], capture_output=True, text=True, encoding='utf-8', timeout=60)
    check(r.returncode == 0, 'node draws the rows', r.stderr[-1500:])
    if r.returncode:
        return
    o = json.loads(r.stdout)
    eq([o.pop(f'opened {i}') for i in ('F1', 'F3', 'V6')], [['F1'], ['F3'], ['V6']], 'each opens')
    css = ''.join(re.findall(r'<style[^>]*>(.*?)</style>', W.page_html().decode(), re.S))
    body = ''.join(f'<section id="{k}">{v}</section>' for k, v in o.items())
    f = tmp / 'place.html'
    f.write_text(f'<!doctype html><meta charset="utf-8"><style>{css}</style><div style="width:390px">{body}</div>'
                 '<style>body{position:static!important;overflow:visible!important;height:auto!important}.card>.grip{pointer-events:auto!important}</style>'
                 '<script>const px=n=>Math.round(n*10)/10;document.title=JSON.stringify([...document.querySelectorAll(".card>.grip")].map(g=>{'
                 'g.scrollIntoView({block:"center"});const a=g.getBoundingClientRect(),c=g.parentElement.getBoundingClientRect(),h=g.parentElement.querySelector(":scope>.fold,:scope>.row").getBoundingClientRect();'
                 'return [g.closest("section").id,g.dataset.grip,!!g.parentElement.querySelector(":scope>.qmenu,:scope>.qacts"),px(a.left-c.left),px(a.width),px(h.left-a.right),'
                 'document.elementFromPoint(a.left+a.width/2,a.top+a.height/2)?.closest(".grip")===g]}))</script>', encoding='utf-8')
    r = subprocess.run([chrome, '--headless', '--no-sandbox', '--disable-gpu', f'--user-data-dir={tmp / "chrome"}', '--dump-dom', f.as_uri()],
                       capture_output=True, text=True, encoding='utf-8', timeout=90)
    m = re.search(r'<title>(.*?)</title>', r.stdout)
    check(m, 'Chromium measures the rows', r.stderr[-800:])
    if not m:
        return
    got = json.loads(m.group(1).replace('&quot;', '"'))
    eq(sorted({(i, menu) for _, i, menu, *_ in got}), [('F1', True), ('F3', False), ('F7', True), ('V6', True), ('next-release', True)], 'a row without a menu among them')
    eq(len(got), 25, 'five rows in each of the five drawings')
    off = [g for g in got if not (0 < g[3] < 4 and g[4] == 16 and g[5] == 0)]
    eq(off, [], "inside the card, in its padding, its right edge at the head's left")
    eq(len({g[3] for g in got}), 1, "all the same from the card's edge")
    eq([g for g in got if not g[6]], [], 'a press in its middle meets it')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_moves), in_tmp(test_grips), in_tmp(test_under_way), in_tmp(test_page), in_tmp(test_place_b830)]))
