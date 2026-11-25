"""F429b: the menu on a Plan queue row: hold, to the top, remove with Undo (agent_runner/page/072-plan-menu.*).

    python3 tests/test_web_plan_menu.py        (a temp repo; the script part needs node)
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from unittest import mock

from _check import RUN, check, eq, git, report

from agent_runner import plan as P, release_moves as M, row_hold as H, state as S  # noqa: E402
from agent_runner import ui_model as U  # noqa: E402
from agent_runner import web as W  # noqa: E402
from _web import in_tmp  # noqa: E402
from test_web_sheet import DOM  # noqa: E402

TODO = """# TODO

## Now

### Next

- [ ] **F1** Board | files: a.py
- [ ] **B2** Retry | files: b.py
- [ ] **F3** Third | files: c.py
- [~] **D4** Pick | files: d.py
  BLOCKED: DECIDE: which?
- [~] **F5** Waits | files: e.py
  BLOCKED: (after F1) its code
- [ ] **V6** Release | after: all

### Other

- [ ] **F7** Elsewhere | files: f.py

### Parked

- [ ] **F8** Later | files: g.py
"""
HOLD, TOP, REMOVE = 'menu_hold', 'menu_top', 'menu_remove'


def repo(tmp: Path) -> Path:
    r = tmp / 'proj'
    (r / 'plan').mkdir(parents=True)
    git(r, 'init', '-q')
    (r / '.gitignore').write_text('.runner/\n')
    (r / 'runner.toml').write_text('[run]\ntest = "true"\nremote = false\nauto_release = { every = 3 }\n')
    (r / 'plan' / 'TODO.md').write_text(TODO, encoding='utf-8')
    (r / 'plan' / 'DONE.md').write_text('# DONE\n', encoding='utf-8')
    git(r, 'add', '-A')
    git(r, 'commit', '-qm', 'start')
    S.init(r)
    return r


def real(argv: list[str]) -> tuple[int, str]:
    r = subprocess.run([sys.executable, str(RUN), *argv], cwd=S.ROOT, capture_output=True, text=True, encoding='utf-8',
                       env={**os.environ, 'AGENT_RUNNER_REPO': str(S.ROOT)})
    return r.returncode, (r.stdout + r.stderr).strip()


def order() -> list[str]:
    return [tid for _, _, tid, _, _ in P.iter_tasks(P.lines(S.C.todo))]


def menus(st: dict | None = None) -> dict[str, list[str]]:
    ls = P.lines(S.C.todo)
    return {q['id']: q['menu'] for q in U.pin_releases(U.queue_rows(ls, st or {}), U.release_rows(ls, st or {}, landed=0))}


def place(tid: str) -> str:
    """As the page's menuPlace()."""
    rows = U.queue_rows(P.lines(S.C.todo))
    me = next(q for q in rows if q['id'] == tid)
    ids = [q['id'] for q in rows if q['section'] == me['section']]
    i = ids.index(tid)
    return json.dumps({'up': ids[:i], 'down': ids[i + 1:], 'in': me['section']})


def test_rows(tmp: Path) -> None:
    """Which row has which acts: none that is under way or parked; the existing row acts are as they were."""
    repo(tmp)
    eq(menus(), {'F1': [HOLD, TOP, REMOVE], 'B2': [HOLD, TOP, REMOVE], 'F3': [HOLD, TOP, REMOVE], 'D4': [TOP], 'F5': [HOLD, TOP],
                 'V6': [HOLD, TOP, REMOVE], 'F7': [HOLD, TOP, REMOVE], 'F8': []},
       'a task and a release; blocked: no remove, as Undo would open it; on the person: no hold, as plan hold refuses it')
    got = menus({'running': {'1': 'F1', '2': 'V6'}, 'merging': ['B2']})
    eq([got[t] for t in ('F1', 'V6', 'B2', 'F3')], [[], [], [], [HOLD, TOP, REMOVE]], 'running, releasing, merging: none')
    with mock.patch('agent_runner.sched.taken', lambda: {'F3': tmp}), mock.patch.object(S, 'queued', lambda: {1: ('B2', 's', 'w')}):
        eq([menus()[t] for t in ('F3', 'B2')], [[], []], 'taken by hand, waiting to resume: none')
    H.hold_task('F1', S.C.todo)
    eq(menus()['F1'], ['menu_unhold', TOP, REMOVE], 'held: the hold ends')
    q = next(q for q in U.queue_rows(P.lines(S.C.todo)) if q['id'] == 'F1')
    eq((q['state'], U.row_acts('queue', q)), ('held', ['queue_priority', 'queue_take', 'queue_drop']), 'it says held; its row acts stay')
    eq([(c['tui'], c['confirm']) for c in U.controls() if c['where'] == 'queuemenu'], [('', '')] * 5, 'no TUI key, no question')


def test_commands(tmp: Path) -> None:
    """Each runs its plan command; one the row does not fit, or another row, runs none."""
    repo(tmp)
    ran: list = []
    with mock.patch.object(U, 'RUN', [lambda a: (ran.append(a), (0, 'ok'))[1]]):
        for key, argv in ((HOLD, ['hold', 'B2']), (TOP, ['move', 'B2', 'top']), (REMOVE, ['drop', 'B2', 'removed from the Plan queue'])):
            ran.clear()
            r = U.act('run_control', key=key, tid='B2')
            eq((r['ok'], ran), (True, [['plan', *argv]]), key)
        check(r['out'] == 'B2 is removed', 'in plain words', r)
        ran.clear()
        for key, tid in (('menu_unhold', 'B2'), (REMOVE, 'D4'), (TOP, 'F8'), (TOP, 'ZZ9'), (TOP, ''), ('menu_restore', 'x')):
            eq((U.act('run_control', key=key, tid=tid)['ok'], ran), (False, []), f'{key} on {tid or "nothing"} is refused')
        with mock.patch.object(H, 'under_way', lambda c, t: 'it is finished and waits to merge'):
            r = U.act('run_control', key=REMOVE, tid='B2')
            check(not r['ok'] and 'waits to merge' in r['out'] and not ran, 'one under way is not removed', r)
        for bad in ('', 'x', '[]', '{"up": 1}'):
            eq((U.act('run_control', key='menu_restore', tid='B2', text=bad)['ok'], ran), (False, []), f'no place: {bad!r}')


def test_undo(tmp: Path) -> None:
    """Undo puts a removed row back where it stood, also after others moved, came or landed."""
    repo(tmp)
    start = order()
    with mock.patch.object(U, 'RUN', [real]):
        for tid in ('F1', 'B2', 'V6', 'F7'):  # first, middle, last, the only one of its section
            line = next(l for l in P.lines(S.C.todo) if f'**{tid}**' in l)
            at = place(tid)
            r = U.act('run_control', key=REMOVE, tid=tid)
            check(r['ok'] and tid not in order(), f'{tid} removed', r)
            r = U.act('run_control', key='menu_restore', tid=tid, text=at)
            check(r['ok'], f'{tid} back', r)
            eq((order(), [l for l in P.lines(S.C.todo) if f'**{tid}**' in l]), (start, [line]), f'{tid}: where it stood, as it was')
        at = place('F3')
        U.act('run_control', key=REMOVE, tid='F3')
        P.move('B2', 'top', todo=S.C.todo)  # its neighbour above moved
        P.tick('F1', S.C.todo, S.C.done)         # and the one before that landed
        U.act('run_control', key='menu_restore', tid='F3', text=at)
        eq(order()[:3], ['B2', 'F3', 'D4'], 'between what is left')
        H.hold_task('V6', S.C.todo)
        at = place('V6')
        U.act('run_control', key=REMOVE, tid='V6')
        U.act('run_control', key='menu_restore', tid='V6', text=at)
        check(H.is_held(next(l for l in P.lines(S.C.todo) if '**V6**' in l)), 'a held one is held again')
        U.act('run_control', key=TOP, tid='F3')
        eq(order()[0], 'F3', 'to the top')


def test_next_release(tmp: Path) -> None:
    """The Next release row: held, removed, put back and moved by its name."""
    repo(tmp)
    P.drop('V6', 'no', S.C.todo, S.C.done)

    def ph():
        ls = P.lines(S.C.todo)
        rows = U.release_rows(ls, {}, landed=1)
        U.pin_releases(U.queue_rows(ls), rows)
        return next(r for r in rows if r['state'] == 'auto')
    with mock.patch.object(U, 'RUN', [real]):
        eq((ph()['menu'], ph()['words']), ([HOLD, TOP, REMOVE], 'auto at 3 landed: 1/3'), 'its menu')
        go = lambda key, text='': U.act('run_control', key=key, tid=M.NEXT, text=text)  # noqa: E731
        eq((go(HOLD)['out'], ph()['menu'][0], ph()['words']), ('Next release is held', 'menu_unhold', 'held · auto at 3 landed: 1/3'), 'held, and says so')
        eq((go(HOLD)['ok'], go('menu_unhold')['ok'], ph().get('held')), (False, True, None), 'no more')
        eq((go(REMOVE)['ok'], bool(M.skipped_at()), go('menu_restore')['ok'], M.skipped_at()), (True, True, True, ''), 'removed and back')
        check(go(TOP)['ok'] and P.release(order()[0]), 'to the top: a release there', order())


DRIVER = DOM + r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const logic = page.split('<script id="logic">')[1].split('</script>')[0].replace(/if\(typeof module[^\n]*/, '');
const line = a => page.slice(page.indexOf(a), page.indexOf('\n', page.indexOf(a)) + 1), slice = (a, b) => page.slice(page.indexOf(a), page.indexOf(b, page.indexOf(a)));
const grab = a => page.slice(page.indexOf(a), page.indexOf('\n}\n', page.indexOf(a)) + 3);
const S = {f: {}, ob: [], taskOpen: {}, tasks: {}, sure: null, snap: JSON.parse(process.argv[3])}, I = {chev: '', x: 'x', dots: '', pause: 'PAUSE', play: 'PLAY', top: 'TOP', trash: 'TRASH'}, MO = {}, FOLD_MO = {}, T = 't', HKEY = '';
let now = 1e6; const Date = {now: () => now}, later = []; const setTimeout = f => { later.push(f) };
const obCards = f => S.ob.filter(f).map(x => `[${x.state} ${x.say}]`).join(''), oldRunHTML = x => x, emptyCard = t => t, taskInView = () => {}, working_ = () => [], render = () => { root.innerHTML = planHTML() };
const calm = () => true, moAnim = () => null, sent = []; root.querySelector = s => { const m = /^([.]\w+)?\s*(.*)$/.exec(s); return null };
const $ = () => root, document = {body: root, activeElement: null, querySelector: () => null};
const outbox = (name, args, more) => { const it = {cid: 'c' + sent.length, name, args, state: 'sending', ...more}; sent.push(args); S.ob.push(it); render(); return it };
const fetch = async () => ({json: async () => ({ok: true, text: 'whole text'})});
eval(logic + ['const esc=', 'const taskChip=', 'const tq=', 'const card=', 'const controlsOf=', 'const controlOf=', 'const ctlBusy=', 'const sureHTML=', 'const ctlSure=', 'const obActs=', 'const obRun=', 'const actBtns=', 'const actSure=', 'const taskIsOpen=', 'const chatBtn=', 'const planCard=', 'const nextReleaseRow=', 'const nextReleaseCard=', 'const queueCard='].map(line).join('')
  + slice('const taskBtns=', '/* F186: a release') + line('const relDrop=') + slice('/* F426b: an open release', '/* F131: the auto') + ['function taskRow(', 'async function openTask(', 'function parkedCard(', 'function shelvedCard(', 'function newReleaseCard('].map(grab).join('')
  + slice('/* F429b: the menu on a Plan', 'I.top=') + slice('/* F212: the search', '/* F87: the Concepts view')
  + "const cutsOff=()=>'';Object.assign(globalThis, {render, openTask, PM, obRun, planFound});");
const opened = () => root.querySelectorAll('[data-task]').filter(e => e.getAttribute('aria-expanded') === 'true').map(e => e.dataset.task);
const rows = () => root.querySelectorAll('[data-k]').map(e => e.dataset.k).filter(k => /^(task:|rel:next)/.test(k)).map(k => k.replace('task:', ''));
const cardOf = id => root.querySelectorAll('[data-k]').find(e => e.dataset.k === (id === 'next-release' ? 'rel:next' : 'task:' + id));
const dots = id => cardOf(id).all.find(e => e.dataset.planmenu), icons = id => cardOf(id).all.filter(e => e.dataset.menuact), icon = (id, k) => icons(id).find(e => e.dataset.menuact === k), undo = id => cardOf(id).all.find(e => e.dataset.menuundo);
// the page's own click lines, closest() from the pressed element up
const up = (e, p = root, way = []) => p === e ? way : p.childNodes ? p.childNodes.map(c => up(e, c, way.concat([p]))).find(Boolean) : null;
const lines = slice('  if(S.planMenu&&!q(', "  if(q('.rowacts'))") + line("  if(x=q('[data-task]'))").replace('openTask(', 'await openTask(');
const tap = async el => { const way = [...up(el), el].reverse(), one = s => s[0] === '[' ? way.find(e => e.hasAttribute && e.hasAttribute(s.slice(1, -1))) : way.find(e => e.hasAttribute && (e.getAttribute('class') || '').split(' ').includes(s.slice(1)));
  const q = s => s.split(',').map(one).find(Boolean); let x; await eval('(async()=>{' + lines + '})()'); later.splice(0).forEach(f => f()) };
const settle = (ok = true) => { const x = S.ob[S.ob.length - 1]; if (ok) S.ob = S.ob.filter(y => y !== x); else x.state = 'failed'; render() };
(async () => {
  const out = {}; render();
  out.shut = rows().map(id => [id === 'rel:next' ? 'next-release' : id]).map(([id]) => [id, !!(cardOf(id) && dots(id)), dots(id) ? cardOf(id).childNodes.includes(dots(id)) : null, dots(id) ? dots(id).nodeName + '|' + dots(id).getAttribute('aria-label') : '']);
  await tap(dots('F1')); out.open = [S.planMenu, opened(), icons('F1').map(e => [e.dataset.menuact, e.text, e.getAttribute('aria-label')]), icons('B2').length];
  await tap(cardOf('F1').all.find(e => e.nodeName === 'b')); out.row = [opened(), S.planMenu]; await tap(cardOf('F1').all.find(e => e.nodeName === 'b'));
  await tap(dots('V6')); await tap(dots('B2')); out.one = [S.planMenu, icons('V6').length, opened()];
  await tap(icon('B2', 'menu_hold')); out.held = [opened(), sent.slice(), cardOf('B2').text, icons('B2').map(e => e.text), S.planMenu, obRun(S.ob[0]), planHTML().includes('[sending')];
  settle(false); out.failed = [cardOf('B2').text.includes('Held'), icons('B2')[0].text, planHTML().includes('[failed Hold: B2]')]; S.ob = []; render();
  await tap(icon('B2', 'menu_hold')); settle(); out.kept = cardOf('B2').text.includes('Held'); S.snap.queue[1] = {...S.snap.queue[1], held: true, state: 'held', menu: ['menu_unhold', 'menu_top', 'menu_remove']}; now += 9000; render();
  await tap(icon('B2', 'menu_unhold')); out.unheld = [sent[sent.length - 1], icons('B2')[0].text, cardOf('B2').text.includes('No longer held') && !cardOf('B2').text.includes('Held:')]; settle();
  now += 9000; await tap(icon('B2', 'menu_top')); out.top = [rows(), sent[sent.length - 1], S.planMenu, opened()]; settle(); now += 9000; render();
  await tap(dots('B2')); await tap(icon('B2', 'menu_remove')); out.twice = rows().includes('B2') && !undo('B2'); now += 600;
  await tap(icon('B2', 'menu_remove')); out.removed = [rows(), sent[sent.length - 1], cardOf('B2').text, planHTML().includes('data-sure'), !!dots('F1'), opened()];
  const n = sent.length; await tap(undo('B2')); out.again = sent.length - n; settle(); S.snap.queue.splice(1, 1); now += 15000; render(); out.stays = rows();
  await tap(undo('B2')); out.undone = [rows(), sent[sent.length - 1], undo('B2') || null, dots('B2') || null]; settle(); S.snap.queue.splice(1, 0, {...JSON.parse(process.argv[3]).queue[1]}); render(); out.back = [rows(), !!dots('B2')];
  now += 9000; await tap(dots('B2')); now += 600; await tap(icon('B2', 'menu_remove')); settle(); S.snap.queue.splice(1, 1); now += 25000; later.splice(0); render(); out.over = rows();
  await tap(dots('next-release')); now += 600; await tap(icon('next-release', 'menu_hold')); out.nextHeld = [sent[sent.length - 1], cardOf('next-release').text];
  await tap(icon('next-release', 'menu_remove')); out.nextGone = [sent[sent.length - 1], cardOf('next-release').text]; now += 600; await tap(undo('next-release')); out.nextBack = [sent[sent.length - 1], !!dots('next-release') || cardOf('next-release').text];
  console.log(JSON.stringify(out));
})();
"""


def test_page(tmp: Path) -> None:
    """The dots and the icons open no row, a tap on the row does, and each press draws at once; a failed one is taken back."""
    page = W.PAGE.read_text(encoding='utf-8')
    for cls in ('.qmenu', '.qacts button'):
        check(re.search(re.escape(cls) + r'[^{}]*\{width:var\(--tap\);height:var\(--tap\)', page), f'{cls}: a finger gets {"--tap"}')
    check("e.key==='Escape'&&S.planMenu" in page, 'Esc closes it')
    if not shutil.which('node'):
        print('  (no node here: the row menu script test is skipped)')
        return
    acts, menu = ['queue_priority', 'queue_take', 'queue_drop'], [HOLD, TOP, REMOVE]
    row = {'id': 'V6', 'title': 'Release', 'words': 'next', 'waits': [], 'note': '', 'placeholder': False}
    t = lambda i, **k: {'id': i, 'title': 'T' + i, 'state': 'ready', 'section': 'Next', 'acts': acts, 'menu': menu, **k}  # noqa: E731
    ph = {'id': '', 'title': 'Next release', 'state': 'auto', 'words': 'auto at 3 landed: 1/3', 'before': '', 'placeholder': True, 'menu': menu}
    snap = {'queue': [t('F1'), t('B2'), t('F3', state='running s1 2m', menu=[]), t('V6', release=row), t('F8', state='parked', section='Parked', menu=[])],
            'shelved': [], 'releases': [row, ph], 'release_acts': [], 'sessions': [], 'controls': U.controls()}
    (tmp / 'menu.js').write_text(DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'menu.js'), str(W.PAGE), json.dumps(snap)], capture_output=True, text=True, encoding='utf-8', timeout=60)
    check(r.returncode == 0, 'node presses the menu', r.stderr[-1500:])
    if r.returncode:
        return
    o = json.loads(r.stdout)
    on = lambda i, n='': [i, True, True, f'button|More for {n or i}']  # noqa: E731
    eq(o['shut'], [on('F1'), on('B2'), ['F3', False, None, ''], on('V6'), on('next-release', 'Next release'), ['F8', False, None, '']],
       'a button beside the head of each row, not on a running or a parked one')
    eq(o['open'], ['F1', [], [['menu_hold', 'PAUSE', "Hold: a run won't start it"], ['menu_top', 'TOP', 'To the top'], ['menu_remove', 'TRASH', 'Remove']], 0],
       'the dots: the icons, with the row shut')
    eq(o['row'], [['F1'], ''], 'a tap on the row opens it, and closes the icons')
    eq(o['one'], ['B2', 0, []], 'one row at a time')
    held = o['held']
    eq((held[0], held[1]), ([], [{'key': 'menu_hold', 'tid': 'B2'}]), 'hold: sent, the row shut')
    check("Held: a run won't start it" in held[2] and held[3] == ['PLAY', 'TOP', 'TRASH'], 'held at once, with play', held)
    eq(held[4:], ['B2', False, False], 'the icons stay; no stand-in of its own, here or on the Run card')
    eq(o['failed'], [False, 'PAUSE', True], 'one that failed is taken back, and says so')
    eq((o['kept'], o['unheld']), (True, [{'key': 'menu_unhold', 'tid': 'B2'}, 'PAUSE', True]), 'until the snapshot has it; play ends it')
    eq(o['top'], [['B2', 'F1', 'F3', 'V6', 'rel:next', 'F8'], {'key': 'menu_top', 'tid': 'B2'}, '', []], 'to the top at once')
    eq(o['twice'], True, 'a double tap on the dots removes nothing')
    gone = o['removed']
    eq((gone[0], gone[1], gone[3:]), (['F1', 'B2', 'F3', 'V6', 'rel:next', 'F8'], {'key': 'menu_remove', 'tid': 'B2'}, [False, True, []]), 'removed with no question, Undo where it stood')
    check('Removed' in gone[2] and 'Undo' in gone[2], 'it says so', gone[2])
    eq((o['again'], o['stays']), (0, gone[0]), 'a double tap on Remove does not undo it; it stays a while')
    place_ = json.dumps({'up': ['F1'], 'down': ['F3', 'V6'], 'in': 'Next'}, separators=(',', ':'))
    eq(o['undone'], [gone[0], {'key': 'menu_restore', 'tid': 'B2', 'text': place_}, None, None], 'Undo: the row where it stood, at once')
    eq(o['back'], [gone[0], True], 'and the snapshot has it again')
    eq(o['over'], ['F1', 'F3', 'V6', 'rel:next', 'F8'], 'Undo goes after a while')
    eq(o['nextHeld'][0], {'key': 'menu_hold', 'tid': 'next-release'}, 'the Next release row by its name')
    check('held · auto at 3' in o['nextHeld'][1], 'held', o['nextHeld'])
    eq(o['nextGone'][0], {'key': 'menu_remove', 'tid': 'next-release'}, 'removed')
    check('Removed' in o['nextGone'][1], 'with Undo', o['nextGone'])
    eq(o['nextBack'], [{'key': 'menu_restore', 'tid': 'next-release', 'text': ''}, True], 'and back')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_rows), in_tmp(test_commands), in_tmp(test_undo), in_tmp(test_next_release), in_tmp(test_page)]))
