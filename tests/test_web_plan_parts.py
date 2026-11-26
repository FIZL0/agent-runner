#!/usr/bin/env python3
"""F453: a split task's parts in the Plan queue, under its card (agent_runner/page/079-plan-parts.*).

    python3 tests/test_web_plan_parts.py        (the real page at phone width, in headless Chromium; skipped without it)
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
    t = lambda i, title='', **k: {'id': i, 'title': title or f'Task {i}', 'state': 'ready', 'section': 'Next', 'acts': [],  # noqa: E731
                                  'menu': MENU, 'grip': True, 'after': [], 'after_title': '', 'blocked': False, **k}
    split = {'parts': 4, 'landed': 1, 'words': 'Split: 1 of 4 parts landed', 'open': [],
             'list': [{'id': 'F440a', 'title': 'The first part', 'landed': True}, {'id': 'F440b', 'title': 'b', 'landed': False},
                      {'id': 'F440c', 'title': 'c', 'landed': False}, {'id': 'F440d', 'title': 'd', 'landed': False},
                      {'id': 'X9', 'title': 'x', 'landed': False}]}
    inner = {'parts': 1, 'landed': 0, 'words': 'Split: 0 of 1 part landed', 'open': [], 'list': [{'id': 'F440c1', 'title': 'c1', 'landed': False}]}
    return {'up': True, 'project': 'p', 'boot': 'b', 'status': [], 'needs': [], 'concepts': [], 'log': [], 'sessions': [], 'release_acts': [],
            'controls': U.controls(), 'releases': [],
            'queue': [t('B2'), t('F440b', state='running s1 2m', menu=[]), t('F441'), t('F440', state='split', split=split),
                      t('F440c', state='split', split=inner), t('F440c1', state='after', after=['F440b'], after_title='F440b b'),
                      t('F440d', state='parked', section='Parked', menu=[], grip=False)],
            'shelved': [{'id': 'X9', 'title': 'Shelved part', 'section': 'Next', 'ask': 'why', 'state': 'shelved'}]}


STUB = """<script>
const FAKE = JSON.parse(document.currentScript.dataset.snap), posts = [];
window.fetch = async (u, o) => {
  if (String(u).includes('act') && o && o.body) { const b = JSON.parse(o.body); posts.push([b.name, b.args]); return {ok: true, status: 200, json: async () => ({ok: true, out: 'said'})} }
  if (String(u).includes('snapshot')) return {ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(FAKE))};
  return new Promise(() => {}) };
window.EventSource = class { addEventListener() {} close() {} };
</script>"""

DRIVER = r"""<script>
(async () => {
  const out = {}, wait = ms => new Promise(r => setTimeout(r, ms || 30)), $$ = s => [...document.querySelectorAll('#body ' + s)];
  try {
    document.getElementById('app').style.width = '390px';
    takeSnap(JSON.parse(JSON.stringify(FAKE))); goView('plan'); await wait();
    const parkedSec = () => $$('.sec').find(s => s.textContent.startsWith('Parked'));  // a parked part is in Parked as well
    const queued = c => { const p = parkedSec(); return !p || !!(p.compareDocumentPosition(c) & Node.DOCUMENT_POSITION_PRECEDING) };
    const cards = () => $$('.card[data-k^="task:"]').filter(queued).map(c => c.dataset.k.slice(5) + (c.classList.contains('part') ? '>' + c.style.getPropertyValue('--depth') : ''));
    out.order = cards();
    out.landed = $$('.partdone').map(e => e.dataset.k);
    out.parked = $$('[data-k="state:F440d"]').filter(queued).map(e => e.textContent).concat($$('[data-k="task:X9"]').filter(queued).map(e => e.textContent.includes('Shelved')));
    out.grip = [!!document.querySelector('#body [data-grip="F440c1"]'), gripBlock(GR.rows, 'F440').map(menuId)];
    const b = document.body, wide = b.scrollWidth <= window.innerWidth;
    out.phone = [wide, [...$$('.card.part')].every(c => c.getBoundingClientRect().right <= document.getElementById('app').getBoundingClientRect().right + 1)];
    document.querySelector('#body [data-partsopen="F440"]').click(); await wait();
    out.shut = [cards(), document.querySelector('#body [data-partsopen="F440"]').textContent, $$('.partdone').length];
    takeSnap(JSON.parse(JSON.stringify(FAKE))); render(true); await wait();
    out.still = cards().length;
    S.f.planq = 'c1'; PQ.got = {q: 'c1', open: [{id: 'F440c1'}], parked: [], done: []}; partRows(planRows(S.snap)); S.f.planq = ''; PQ.got = null;
    render(true); await wait();
    out.found = cards().length;
    out.moved = [gripMove('F440c', 0), gripMove('F440', 0)];
    await wait(100);
    out.sent = posts.filter(p => p[0] === 'move').map(p => p[1]);
  } catch (e) { out.error = String(e.stack || e) }
  const pre = document.createElement('pre'); pre.id = 'out'; pre.textContent = JSON.stringify(out); document.body.append(pre);
})();
</script>"""


def test_page(tmp: Path) -> None:
    chrome = next(filter(None, map(shutil.which, ('chromium', 'chromium-browser', 'google-chrome'))), None)
    if not chrome:
        print('  (no Chromium here: the page test is skipped)')
        return
    html = W.page_html().decode()
    snap = json.dumps(snapshot()).replace('&', '&amp;').replace('"', '&quot;')
    html = re.sub(r'<link rel="stylesheet" href="https[^>]*>', '', html)
    html = html.replace('<head>', '<head>' + STUB.replace('<script>', f'<script data-snap="{snap}">', 1), 1).replace('</body>', DRIVER + '</body>', 1)
    f = tmp / 'parts.html'
    f.write_text(html, encoding='utf-8')
    cmd = [chrome, '--headless', '--no-sandbox', '--disable-gpu', '--window-size=390,844', f'--user-data-dir={tmp / "chrome"}', '--virtual-time-budget=15000']
    r = subprocess.run([*cmd, '--dump-dom', f.as_uri()], capture_output=True, text=True, encoding='utf-8', timeout=120)
    if os.environ.get('SHOW'):  # a look at it: SHOW=/tmp/parts.png
        subprocess.run([*cmd, '--screenshot=' + os.environ['SHOW'], f.as_uri()], capture_output=True, timeout=120)
    m = re.search(r'<pre id="out">(.*?)</pre>', r.stdout, re.S)
    check(m, 'Chromium runs the page', r.stderr[-800:])
    if not m:
        return
    o = json.loads(m.group(1).replace('&quot;', '"').replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&'))
    check('error' not in o, 'to its end', o.get('error'))
    if 'error' in o:
        return
    eq(o['order'], ['B2', 'F440', 'F440b>1', 'F440c>1', 'F440c1>2', 'F440d>1', 'X9>1', 'F441'],
       'the group stands where its first open part stands; its parts under it in order, a part split again nested; no row twice')
    eq(o['landed'], ['partdone:F440:F440a'], 'the landed part is in its card')
    eq(o['parked'], ["Parked: a run won't start it", True], 'a parked and a shelved part say so')
    eq(o['grip'], [True, ['F440', 'F440b', 'F440c', 'F440c1', 'F440d', 'X9']], 'a part keeps its grip; the split task moves with its parts')
    eq(o['phone'], [True, True], 'at 390px: nothing sideways')
    eq(o['shut'][0], ['B2', 'F440', 'F441'], 'shut: its parts go')
    check('F440b s1 is on it' in o['shut'][1], 'shut, it says which part runs', o['shut'][1])
    eq(o['shut'][2], 0, 'and no landed list')
    eq(o['still'], 3, 'a new snapshot keeps it shut on this page')
    eq(o['found'], 8, 'a match in Find a task opens its group')
    eq(o['moved'], [True, True], 'a part and the split task can be moved')
    eq([s.get('tid') for s in o['sent']], ['F440c', 'F440'], 'each sends a move')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_page)]))
