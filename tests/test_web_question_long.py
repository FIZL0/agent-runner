"""B840a: a question card with a long question at phone width, and the rows that draw a DECIDE stay short.

    python3 tests/test_web_question_long.py        (the real page at phone width, in headless Chromium; skipped without it)
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

QUESTION = ('Should I attach both showcase videos to iFizBox\'s "Watch the new showcase video" item in Needs you, so they play there '
            '(on an iPhone too, though that is untested)? This changes only that item\'s attachments in the iFizBox project. '
            'https://example.com/p/iFizBox/concept/F440b')
OPTIONS = [{'name': 'Attach both videos', 'rec': True}, {'name': 'Leave the item as it is', 'rec': False}]
LONG = ('https://example.com/' + 'x' * 180 + ' ' + QUESTION + ' ' + 'Some more words of the question. ' * 60)[:1995] + ' END?'


def ask(qid: str, question: str) -> dict:
    return {'id': qid, 'question': question, 'options': OPTIONS}


def snapshot() -> dict:
    shelved = {'id': 'S1', 'title': 'Shelved one', 'section': 'Next', 'ask': LONG, 'state': 'shelved', 'acts': []}
    return {'up': True, 'project': 'p', 'boot': 'b', 'at': 1, 'status': [], 'needs': [], 'concepts': [], 'log': [], 'release_acts': [], 'releases': [],
            'sessions': [{'name': 'c1', 'title': 'Chat', 'state': 'live'}], 'controls': U.controls(), 'queue': [], 'shelved': [shelved],
            'asks': {'real': ask('u1', QUESTION), 'long': ask('u2', LONG)}}


STUB = """<script>
const FAKE = JSON.parse(document.currentScript.dataset.snap);
window.fetch = async (u, o) => String(u).includes('snapshot') ? {ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(FAKE))} : new Promise(() => {});
window.EventSource = class { addEventListener() {} close() {} };
</script>"""

DRIVER = r"""<script>
(async () => {
  const out = {}, wait = ms => new Promise(r => setTimeout(r, ms || 30)), one = s => document.querySelector(s), app = document.getElementById('app');
  const still = () => document.getAnimations().forEach(a => { try { a.finish() } catch (e) {} });
  const box = e => e.getBoundingClientRect();
  // can a finger get to it: scrolled into the card's view, wholly in the card, and what is under its middle
  const reach = (card, b) => {
    const c = box(card); card.scrollTop += box(b).top - c.top - (c.height - box(b).height) / 2;
    const r = box(b), under = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    return r.left >= c.left - 1 && r.right <= c.right + 1 && r.top >= c.top - 1 && r.bottom <= c.bottom + 1 && r.height >= 44 && !!under && b.contains(under) && b.scrollWidth <= b.clientWidth + 1;
  };
  // is all the question's text drawn inside the card, over its whole scroll
  const whole = (card, q) => {
    const g = document.createRange(); g.selectNodeContents(q);
    const c = box(card), rs = [...g.getClientRects()], top = c.top - card.scrollTop;
    return rs.length > 1 && rs.every(r => r.left >= c.left && r.right <= c.right && r.top >= top && r.bottom <= top + card.scrollHeight);
  };
  const view = () => {
    still();
    const card = one('#dock .qcard'), c = box(card), a = box(app), t = card.querySelector('.q'), room = box(one('#top')).bottom, inbox = box(one('#dock .box'));
    const btns = [...card.querySelectorAll('button')], q = t && t.textContent;
    return {n: btns.map(b => b.getAttribute('aria-label') || b.textContent), reach: btns.map(b => reach(card, b)), side: [card.scrollWidth <= card.clientWidth, c.left >= a.left && c.right <= a.right, app.scrollWidth <= app.clientWidth],
      whole: t && whole(card, t), words: q && Object.values(FAKE.asks).some(x => x.question === q), high: Math.round(c.height), scrolls: card.scrollHeight > card.clientHeight, inView: c.top >= room && c.bottom <= inbox.top + 1 && inbox.bottom <= a.bottom + 1, app: Math.round(a.height)};
  };
  try {
    app.style.width = '390px';
    takeSnap(JSON.parse(JSON.stringify(FAKE)));
    S.thread = 'c1'; render(true); await wait();
    const put = a => { FD.n = 'c1'; FD.shown = true; FD.foot = null; FD.whole = false; FD.live = {ok: true, ask: a, tasks: []}; one('.main').classList.add('sess'); QN.back = 0; QN.marked = 0; render(true) };
    const kb = on => { app.classList.toggle('kb', on); app.style.height = on ? '470px' : '' };
    for (const k of ['real', 'long']) for (const up of [false, true]) {
      put(FAKE.asks[k]); kb(up); await wait(); const o = out[k + (up ? 'Kb' : '')] = {card: view()};
      const c0 = one('#dock .qcard'); c0.scrollTop = 40; c0.dispatchEvent(new Event('scroll')); /* virtual time draws no frame, so the browser sends none */ FD.live = {...FD.live, status: 'busy', since: 1}; render(true); await wait(); kb(up); o.kept = [c0 !== one('#dock .qcard'), one('#dock .qcard').scrollTop];
      if (SHOT === k + (up ? 'Kb' : '')) return;
      one('#dock [data-qmin]').click(); await wait(); kb(up); await wait(); o.min = view();
      QN.back = 0; one('#dock [data-qshow]').click(); await wait(); QN.back = 0;
      one('#dock [data-qchat]').click(); await wait(); kb(up); o.mark = view();
      QN.marked = 0; one('#dock [data-qunchat]').click(); await wait(); o.back = one('#dock [data-qpick]') !== null;
    }
    kb(false); goView('plan'); await wait(); still();
    // Plan's shelved task, and the row of what waits on the person, over all projects
    const div = document.createElement('div'); div.className = 'col'; div.style.width = '358px'; document.getElementById('body').append(div);
    const row = (html, s) => { div.innerHTML = html; const e = div.querySelector(s), c = box(div.firstElementChild); return [Math.round(box(e).height / parseFloat(getComputedStyle(e).lineHeight)), div.scrollWidth <= div.clientWidth, c.height < 240] };
    out.shelved = row(shelvedCard(FAKE.shelved[0]), '.askdo');
    out.home = row(askRow(projectAsks([{key: 'k', name: 'p', asks: ['F9 - ' + FAKE.asks.long.question]}])[0]), '.ell2');
  } catch (e) { out.error = String(e.stack || e) }
  const pre = document.createElement('pre'); pre.id = 'out'; pre.textContent = JSON.stringify(out); document.body.appendChild(pre);
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
    shot = os.environ.get('SHOW', '')  # SHOW=realKb: that state's picture, in question-long.png here
    html = html.replace('<head>', '<head>' + STUB.replace('<script>', f'<script data-snap="{snap}">', 1), 1).replace('</body>', DRIVER.replace('SHOT', json.dumps(shot)) + '</body>', 1)
    f = tmp / 'long.html'
    f.write_text(html, encoding='utf-8')
    cmd = [chrome, '--headless', '--no-sandbox', '--disable-gpu', '--window-size=600,844', f'--user-data-dir={tmp / "chrome"}', '--virtual-time-budget=15000']
    if shot:
        subprocess.run([*cmd, '--screenshot=question-long.png', f.as_uri()], timeout=90)
        return
    r = subprocess.run([*cmd, '--dump-dom', f.as_uri()], capture_output=True, text=True, encoding='utf-8', timeout=120)
    m = re.search(r'<pre id="out">(.*?)</pre>', r.stdout, re.S)
    check(m, 'Chromium runs the page', r.stderr[-800:])
    if not m:
        return
    o = json.loads(m.group(1).replace('&quot;', '"').replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&'))
    if os.environ.get('DUMP'):
        print(json.dumps(o, indent=1))
    check('error' not in o, 'to its end', o.get('error'))
    if 'error' in o:
        return
    for k, v in ((k, o[k]) for k in ('real', 'realKb', 'long', 'longKb')):
        c, kb = v['card'], k.endswith('Kb')
        eq(c['n'], ['Minimize question', 'Attach both videos (recommended)', 'Leave the item as it is', 'Chat about this'], f'{k}: the card')
        eq((c['reach'], c['side'], c['whole'], c['words'], c['scrolls'], c['inView']), ([True] * 4, [True] * 3, True, True, True, True),
           f'{k}: every button can be reached, all the words are drawn by scrolling, nothing sideways, between the top bar and the box')
        check(c['high'] <= c['app'] * (.4 if kb else .45) + 1, f'{k}: the card is bounded', c['high'])
        eq(v['kept'], [True, 40], f'{k}: a redraw keeps its scroll place')
        m, a = v['min'], v['mark']
        eq((m['n'], m['reach'], m['side'], m['inView'], m['high'] < 60), (['Show question'], [True], [True] * 3, True, True), f'{k}: minimized, one line')
        eq((a['n'], a['reach'], a['side'], a['inView'], a['high'] < 60), (['Back to the question'], [True], [True] * 3, True, True), f'{k}: marked, one line (B854a)')
        check(a['high'] <= min(140, a['app'] * .25) + 1, f'{k}: the mark is bounded', (a['high'], a['app']))
        check(v['back'], f'{k}: and back to the card')
    eq((o['shelved'], o['home']), ([2, True, True], [3, True, True]), "Plan's shelved ask is 2 lines, All projects' row 3")


def test_tui() -> None:
    import datetime as dt
    import test_tui as T
    n = U.needs_rows([('DECIDE', 'F9', '', 'Should I ' + 'word ' * 380 + 'END?', '', 'T', False, '')], dt.datetime(2026, 11, 25))[0][0]
    check(len(n['ask_short']) <= U.ASK_SHORT, 'the short ask', n['ask_short'])
    p = T.page(dict(T.SNAP, needs=[n]))
    eq(len(p.row_lines(4, n, 34, True)), 1, "the terminal UI's row is one line, also selected")
    left = [l[:36] for l in T.drawn(p).lines()]
    at = [i for i, l in enumerate(left) if 'F9 ' in l and 'Should I' in l]
    check(len(at) == 1 and 'word' not in left[at[0] + 1], 'drawn cut at the panel', left)


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_page), test_tui]))
