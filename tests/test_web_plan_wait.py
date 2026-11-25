"""F442: Wait for… in a Plan queue task's row menu (agent_runner/page/078-plan-wait.*).

    python3 tests/test_web_plan_wait.py        (the real page at phone width, in headless Chromium; skipped without it)
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from _check import check, eq, report

from agent_runner import ui_model as U  # noqa: E402
from agent_runner import web as W  # noqa: E402
from _web import in_tmp  # noqa: E402

MENU = ['menu_hold', 'menu_top', 'menu_remove']


def snapshot() -> dict:
    t = lambda i, title='', **k: {'id': i, 'title': title or f'Task {i}: more', 'state': 'ready', 'section': 'Next', 'acts': [],  # noqa: E731
                                  'menu': MENU, 'grip': True, 'after': [], 'after_title': '', 'blocked': False, **k}
    rel = {'id': 'V9', 'title': 'Release', 'state': 'waits', 'words': 'waits for 1', 'waits': [{'id': 'F1', 'title': 'x'}], 'note': '', 'placeholder': False, 'everything': True}
    ph = {'id': '', 'title': 'Next release', 'state': 'auto', 'words': 'auto at 3 landed: 1/3', 'before': '', 'placeholder': True, 'menu': MENU, 'grip': True}
    return {'up': True, 'project': 'p', 'boot': 'b', 'status': [], 'needs': [], 'concepts': [], 'log': [], 'sessions': [], 'release_acts': [], 'controls': U.controls(),
            'releases': [rel, ph],
            'queue': [t('F1', 'A task with a rather long title that a phone has to cut short: more', after=['B2', 'C0'], after_title='B2 Task B2', state='after'), t('B2'),
                      t('F3', state='running s1 2m', menu=[]), t('F1a'), t('F4', after=['F1'], after_title='F1', state='after'),
                      t('F5', after=['F4'], after_title='F4', state='after'), t('D6', state='blocked', blocked=True, no_hold=True),
                      t('V9', release=rel), t('F7', split={'parts': 2, 'open': [{'id': 'X1', 'title': 'x'}], 'words': 'Split'}), t('X1'),
                      t('P8', state='parked', section='Parked', menu=[], grip=False)],
            'shelved': [{'id': 'S1', 'title': 'Shelved one', 'section': 'Next', 'ask': 'why', 'state': 'shelved'}]}


STUB = """<script>
const FAKE = JSON.parse(document.currentScript.dataset.snap), posts = []; let refuse = '';
window.fetch = async (u, o) => {
  if (String(u).includes('act') && o && o.body) { const b = JSON.parse(o.body); posts.push([b.name, b.args]); const j = refuse ? {ok: false, out: refuse} : {ok: true, out: 'said'}; return {ok: true, status: 200, json: async () => j} }
  if (String(u).includes('snapshot')) return {ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(FAKE))};
  return new Promise(() => {}) };
window.EventSource = class { addEventListener() {} close() {} };
</script>"""

DRIVER = r"""<script>
(async () => {
  const out = {}, wait = ms => new Promise(r => setTimeout(r, ms || 30)), $$ = s => [...document.querySelectorAll('#body ' + s)], one = s => document.querySelector(s);
  try {
    document.getElementById('app').style.width = '390px';
    const fresh = () => { takeSnap(JSON.parse(JSON.stringify(FAKE))) };
    const menu = id => { one(`[data-planmenu="${id}"]`).click(); return [...one('.qacts').children].map(b => b.getAttribute('aria-label')) };
    const start = id => { menu(id); const b = one('[data-waitset]'); if (b) b.click(); return !!b };
    const pick = id => one(`[data-waitpick="${id}"]`), tap = id => pick(id).click();
    const ticks = () => $$('[data-waitpick][aria-checked="true"]').map(e => e.dataset.waitpick), bar = () => { const b = one('#waitbar'); return b.hidden ? '' : b.innerText.replace(/\s+/g, ' ').trim() };
    const words = id => $$(`[data-k="state:${id}"]`)[0].textContent, done = () => one('[data-waitdone]').click(), esc = (o = document.body) => o.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true, cancelable: true}));
    const sets = () => posts.filter(p => p[0] === 'set_waits').map(p => p[1]);
    fresh(); goView('plan'); await wait();
    out.menus = ['F1', 'D6', 'V9', 'next-release'].map(menu); esc();
    out.noDots = ['F3', 'P8'].map(id => !one(`[data-planmenu="${id}"]`));
    const y0 = one('[data-k="task:F1"]').getBoundingClientRect().top;
    start('F1'); await wait(400);
    out.start = [bar(), ticks(), !!one('.card.waitset [data-waitme="F1"]'), document.activeElement.dataset.waitme, $$(':is(.grip,.qmenu,.qacts,[data-task])').length, Math.round(one('[data-k="task:F1"]').getBoundingClientRect().top - y0)];
    out.off = $$('[aria-disabled]').map(e => [e.dataset.waitpick, words(e.dataset.waitpick)]);
    out.ph = one('[data-k="rel:next"]').querySelectorAll('button').length;
    out.roles = [...new Set($$('[data-waitpick]').map(e => e.nodeName + e.getAttribute('role')))];
    document.getAnimations().forEach(a => { try { a.finish() } catch (e) {} });
    const b = one('#waitbar').getBoundingClientRect(), app = document.getElementById('app').getBoundingClientRect();
    out.look = [document.getElementById('body').scrollWidth <= document.getElementById('body').clientWidth, b.width <= 390 && b.bottom <= app.bottom + 1, b.height < 80, [...document.querySelectorAll('#waitbar .btn')].every(x => x.offsetHeight >= 44),
      $$('[data-waitpick]').every(e => e.getBoundingClientRect().right <= 390 && e.querySelector('.waittick').getBoundingClientRect().width >= 20), getComputedStyle(pick('F4').closest('.card')).opacity];
    tap('F4'); tap('F1a'); out.offTap = ticks();
    pick('F3').focus(); tap('F3'); out.picked = [ticks(), document.activeElement.dataset.waitpick, $$('[aria-expanded="true"]').length];
    tap('X1'); FAKE.queue[1].title = 'Changed'; FAKE.queue = FAKE.queue.filter(q => q.id !== 'X1'); fresh(); await wait(); out.redrawn = [ticks(), bar(), document.activeElement.dataset.waitpick, document.body.innerText.includes('Changed')];
    S.f.planq = 'P8'; PQ.got = {q: 'P8', open: [], parked: [{id: 'P8'}], done: [{id: 'Z'}], more: 0}; render(true); out.found = $$('[data-waitpick]').map(e => e.dataset.waitpick); tap('P8'); S.f.planq = ''; render(true);
    goView('status'); out.away = bar(); goView('plan'); out.backHere = bar() !== '';
    const n = posts.length; esc(); out.esc = [bar(), posts.length - n, $$('[data-waitpick]').length, document.activeElement.dataset.planmenu, words('F1')];
    start('F1'); tap('B2'); one('[data-waitcancel]').click(); out.cancel = [posts.length - n, words('F1'), bar()];
    start('F1'); done(); out.same = posts.length - n;
    start('F1'); tap('F3'); tap('P8'); done(); out.now = [words('F1'), bar(), document.activeElement.dataset.planmenu]; await wait(); out.sent = sets();
    await wait(); out.kept = words('F1');
    Object.assign(FAKE.queue[0], {after: ['B2', 'F3', 'P8'], after_title: 'from the snapshot'}); fresh(); await wait(); out.snap = words('F1');
    start('F1'); for (const t of ticks()) tap(t); done(); out.clear = words('F1'); await wait(); out.cleared = sets().pop();
    Object.assign(FAKE.queue[0], {after: [], after_title: '', state: 'ready'}); fresh();
    refuse = 'F1 has started: it runs'; start('F1'); tap('B2'); done(); out.hope = words('F1'); await wait(100); S.obOpen = false; render(true);
    const card = () => $$('.obstand.failed')[0]; out.refused = [words('F1'), card() && card().innerText.includes('F1 has started: it runs'), !!card() && !!card().querySelector('[data-obretry]')];
    refuse = ''; card().querySelector('[data-obretry]').click(); out.again = words('F1'); await wait(100); out.retried = [sets().pop(), !card()];
    start('F1'); FAKE.queue[0].menu = []; fresh(); await wait(); out.started = [bar(), $$('[data-waitpick]').length, one('#toast').textContent];
  } catch (e) { out.error = String(e.stack || e) }
  const pre = document.createElement('pre'); pre.id = 'out'; pre.textContent = JSON.stringify(out); document.body.appendChild(pre);
})();
</script>"""


def test_static(tmp: Path) -> None:
    page = W.PAGE.read_text(encoding='utf-8')
    check('id="waitbar"' in page and "set_waits" in page, 'the bar and the action are in the page')
    check('set_waits' in U.ACTIONS, "F441's action is there")


def test_page(tmp: Path) -> None:
    chrome = next(filter(None, map(shutil.which, ('chromium', 'chromium-browser', 'google-chrome'))), None)
    if not chrome:
        print('  (no Chromium here: the page test is skipped)')
        return
    html = W.page_html().decode()
    snap = json.dumps(snapshot()).replace('&', '&amp;').replace('"', '&quot;')
    html = re.sub(r'<link rel="stylesheet" href="https[^>]*>', '', html)
    html = html.replace('<head>', '<head>' + STUB.replace('<script>', f'<script data-snap="{snap}">', 1), 1).replace('</body>', DRIVER + '</body>', 1)
    f = tmp / 'wait.html'
    f.write_text(html, encoding='utf-8')
    cmd = [chrome, '--headless', '--no-sandbox', '--disable-gpu', '--window-size=600,844', f'--user-data-dir={tmp / "chrome"}', '--virtual-time-budget=15000']
    if os.environ.get('SHOW'):
        (tmp / 'shot.html').write_text(html.replace("out.off =", "if(location.hash){return}out.off ="), encoding='utf-8')
        subprocess.run([*cmd, '--screenshot=' + os.environ['SHOW'], (tmp / 'shot.html').as_uri() + '#x'], timeout=90)
    r = subprocess.run([*cmd, '--dump-dom', f.as_uri()], capture_output=True, text=True, encoding='utf-8', timeout=120)
    m = re.search(r'<pre id="out">(.*?)</pre>', r.stdout, re.S)
    check(m, 'Chromium runs the page', r.stderr[-800:])
    if not m:
        return
    o = json.loads(m.group(1).replace('&quot;', '"').replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&'))
    check('error' not in o, 'to its end', o.get('error'))
    if 'error' in o:
        return
    hold, top, rm = "Hold: a run won't start it", 'To the top', 'Remove'
    eq(o['menus'], [[hold, 'Wait for…', top, rm], [hold, top, rm], [hold, top, rm], [hold, top, rm]], 'a task has it; one on the person, a release and the Next release row do not')
    eq(o['noDots'], [True, True], 'a running row and a parked one have no menu')
    eq(o['start'], ['What should F1 wait for? Cancel Done', ['B2'], True, 'F1', 0, 0], 'the bar, its waits ticked (a landed one is none), the row marked where it was; no drag, no menu, nothing to open')
    eq(o['off'], [['F1a', 'A part of F1'], ['F4', 'Waits for F1 itself'], ['F5', 'Waits for F1 itself'], ['V9', 'Waits for F1 itself']], 'what it cannot wait for is dimmed, through other tasks too')
    eq((o['ph'], o['roles']), (0, ['BUTTONcheckbox']), 'the Next release row is no pick; each row is a checkbox')
    eq(o['look'], [True, True, True, True, True, '0.5'], 'at 390px: nothing sideways, the bar in view, fingers fit')
    eq(o['offTap'], ['B2'], 'a tap on a dimmed row does nothing')
    eq(o['picked'], [['B2', 'F3'], 'F3', 0], 'a running task is picked; the focus stays; nothing opens')
    eq(o['redrawn'], [['B2', 'F3'], 'What should F1 wait for? Cancel Done', 'F3', True], 'a redraw midway: one that landed goes, the rest stays')
    eq((o['found'], o['away'], o['backHere']), (['P8'], '', True), 'a search finds rows to tick; the bar is on Plan alone')
    was = 'Waits for B2 Task B2'
    eq(o['esc'], ['', 0, 0, 'F1', was], 'Esc: nothing sent, the rows are back')
    eq((o['cancel'], o['same']), ([0, was, ''], 0), 'Cancel, and Done with nothing changed, send nothing')
    eq(o['now'], ['Waits for B2 Changed, F3 Task F3, P8 Task P8', '', 'F1'], 'Done: the row says it at once, and has the focus')
    eq(o['sent'], [{'tid': 'F1', 'ids': ['B2', 'F3', 'P8']}], "F441's action")
    eq((o['kept'], o['snap']), (o['now'][0], 'Waits for from the snapshot'), 'until the snapshot has it')
    eq((o['clear'], o['cleared']), ('Ready to start when a slot is free', {'tid': 'F1', 'ids': []}), 'all unticked: cleared')
    eq((o['hope'], o['refused']), ('Waits for B2 Changed', ['Ready to start when a slot is free', True, True]), 'refused: taken back, the reason and Retry')
    eq((o['again'], o['retried']), ('Waits for B2 Changed', [{'tid': 'F1', 'ids': ['B2']}, True]), 'Retry sends it again')
    eq(o['started'][:2], ['', 0], 'a task that started meanwhile is set no more')
    check('F1 has started' in o['started'][2], 'and it says so', o['started'][2])


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_static), in_tmp(test_page)]))
