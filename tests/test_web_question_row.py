"""F192b2: several questions, the row: one card each in a sideways swipe row with a count; answering or dismissing one
moves to the next; one question looks as before.

    python3 tests/test_web_question_row.py
"""
from __future__ import annotations

from pathlib import Path

from _check import check, eq, report
from _web import in_tmp

import test_web_question_dismiss as D
from agent_runner import chat_question as CQ

LOOK = r"""
const A = {...ASK, id: 'u7', question: 'Which look?'}, B = {...ASK, id: 'u7#2', question: 'Which size?', options: [{name: 'Big'}, {name: 'Little'}]},
  C = {...ASK, id: 'u7#3', question: 'Which tone?'};
const lives = l => { FD.live = {ok: true, ask: l[0] || null, asks: l}; questionSee('c1'); render() };
const cards = () => (dock.match(/class="card qcard qone"/g) || []).length, count = () => (dock.match(/class="qcount[^"]*"[^>]*>([^<]*)</) || [])[1] || '';
const gone = id => tap({qgone: id});
"""


def run(tmp: Path, steps: str, kept: dict | None = None) -> list | None:
    return D.run(tmp, LOOK + steps, kept)


def test_row(tmp: Path) -> None:
    out = run(tmp, """
      lives([A, B, C]); say(dock, cards(), count());
      lives([A]); say(cards(), kind(), dock.includes('data-qgone'), dock.includes('qmany'));""")
    if out is None:
        return
    row = out[0][0]
    check('class="qswipe"' in row and 'Which look?' in row and 'Which size?' in row and 'Which tone?' in row, 'the row holds a card each', row)
    eq(out[0][1:], [3, '1 of 3'], 'three cards, and the count')
    check('data-qgone="u7#2" aria-label="Dismiss question"' in row, 'each card has its ✕', row)
    eq(out[1], [0, 'card', False, False], 'one question: the card as before')


def test_answer(tmp: Path) -> None:
    out = run(tmp, """
      lives([A, B, C]); pick(0, 'u7#2'); say(kind()); await pass(5100);
      say(cards(), count(), dock.includes('Which size?'), sent.map(x => x.args.text));
      lives([A, C]); say(cards(), count());""")
    if out is None:
        return
    eq(out[0], ['held'], 'a tap holds it, with Undo, as before')
    eq(out[1][:3], [2, '1 of 2', False], 'then the row moves on, the others stay')
    eq(out[1][3], [CQ.answered_with('Which size?', 'Big')], 'the answer names its question, as the run reads it')
    check(CQ.answer_to(out[1][3][0]) == 'Which size?', 'answer_to reads it', out[1][3])
    eq(out[2], [2, '1 of 2'], '/live drops it: the same two')


def test_dismiss(tmp: Path) -> None:
    out = run(tmp, """
      lives([A, B, C]); gone('u7'); say(cards(), count(), {...kept}); now += 600; gone('u7#3'); say(cards(), kind(), dock.includes('Which size?'));
      now += 600; lives([A, B, C, {...C, id: 'u9', question: 'Later?'}]); say(cards(), dock.includes('Later?'));""")
    if out is None:
        return
    eq(out[0][:2], [2, '1 of 2'], 'a ✕ moves to the next')
    check('c1 u7' in out[0][2].get('ar-qgone:t', ''), 'kept per question id', out[0][2])
    eq(out[1], [0, 'card', True], 'one left: the card as before')
    eq(out[2], [2, True], 'a later new question still shows')


PAGE = r"""<script>
(async () => {
  const out = {}, wait = ms => new Promise(r => setTimeout(r, ms || 30)), one = s => document.querySelector(s), app = document.getElementById('app');
  try {
    app.style.width = '390px';
    takeSnap(JSON.parse(JSON.stringify(FAKE)));
    S.thread = 'c1'; render(true); await wait();
    const l = ['Which look?', 'Which size?', 'Which tone?'].map((q, i) => ({id: 'u7' + (i ? '#' + (i + 1) : ''), question: q, options: [{name: 'Full', rec: true}, {name: 'Small'}]}));
    FD.n = 'c1'; FD.shown = true; FD.foot = null; FD.whole = false; FD.live = {ok: true, ask: l[0], asks: l, tasks: []}; one('.main').classList.add('sess'); render(true); await wait();
    document.getAnimations().forEach(a => { try { a.finish() } catch (e) {} });
    const r = one('#dock .qswipe'), a = app.getBoundingClientRect(), c = [...r.children].map(x => x.getBoundingClientRect()), d = document.documentElement;
    out.cards = c.length; out.count = one('#dock .qcount').textContent;
    out.edge = c[1].left < r.getBoundingClientRect().right && c[0].right < r.getBoundingClientRect().right;
    out.side = [d.scrollWidth <= d.clientWidth, app.scrollWidth <= app.clientWidth, r.getBoundingClientRect().right <= a.right + 1];
    const x = r.children[1].offsetLeft - r.children[0].offsetLeft; r.scrollLeft = x; r.dispatchEvent(new Event('scroll')); await wait();
    out.count2 = one('#dock .qcount').textContent;
    FD.live = {...FD.live, status: 'busy', since: 1}; render(true); await wait(); await wait();
    out.kept = Math.abs(x - one('#dock .qswipe').scrollLeft) < 2 && x > 0;
    if (SHOT) { one('#dock .qswipe').scrollLeft = 0; return }
  } catch (e) { out.error = String(e.stack || e) }
  const pre = document.createElement('pre'); pre.id = 'out'; pre.textContent = JSON.stringify(out); document.body.appendChild(pre);
})();
</script>"""


def test_page(tmp: Path) -> None:
    """At phone width (390px) in headless Chromium: the row, the next card's edge, no sideways page scroll, the place kept."""
    import json
    import os
    import re
    import shutil
    import subprocess
    import test_web_question_long as L
    from agent_runner import web as W
    chrome = next(filter(None, map(shutil.which, ('chromium', 'chromium-browser', 'google-chrome'))), None)
    if not chrome:
        print('  (no Chromium here: the page test is skipped)')
        return
    html = re.sub(r'<link rel="stylesheet" href="https[^>]*>', '', W.page_html().decode())
    snap = json.dumps(L.snapshot()).replace('&', '&amp;').replace('"', '&quot;')
    shot = os.environ.get('SHOW', '')  # SHOW=1: the picture, in question-row.png here
    html = html.replace('<head>', '<head>' + L.STUB.replace('<script>', f'<script data-snap="{snap}">', 1), 1).replace('</body>', PAGE.replace('SHOT', json.dumps(bool(shot))) + '</body>', 1)
    f = tmp / 'row.html'
    f.write_text(html, encoding='utf-8')
    cmd = [chrome, '--headless', '--no-sandbox', '--disable-gpu', '--window-size=390,844', f'--user-data-dir={tmp / "chrome"}', '--virtual-time-budget=15000']
    if shot:
        subprocess.run([*cmd, f'--screenshot={Path.cwd() / "question-row.png"}', f.as_uri()], timeout=90)
        return
    r = subprocess.run([*cmd, '--dump-dom', f.as_uri()], capture_output=True, text=True, encoding='utf-8', timeout=120)
    m = re.search(r'<pre id="out">(.*?)</pre>', r.stdout, re.S)
    check(m, 'Chromium runs the page', r.stderr[-800:])
    if not m:
        return
    o = json.loads(m.group(1).replace('&quot;', '"').replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&'))
    check('error' not in o, 'to its end', o.get('error'))
    if 'error' in o:
        return
    eq((o['cards'], o['count'], o['edge']), (3, '1 of 3', True), 'three cards, the count, the next card\'s edge showing')
    eq(o['side'], [True] * 3, 'the page never scrolls sideways')
    eq((o['count2'], o['kept']), ('2 of 3', True), 'the count follows the swipe, and a redraw keeps the place')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(f) for f in (test_row, test_answer, test_dismiss, test_page)]))
