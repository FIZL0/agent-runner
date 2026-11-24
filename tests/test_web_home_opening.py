"""The run page, home area: a pressed project is marked as opening until its page comes (B769b).

    python3 tests/test_web_home_opening.py
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from _check import check, eq, report

from agent_runner import web as W
from _web import in_tmp

DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const cut = (a, b) => page.slice(page.indexOf(a), page.indexOf(b, page.indexOf(a)));
const line = s => cut(s, '\n');
const H = {projects: [], tab: ''}, on = {}, timers = [], gone = [], said = [];
let HKEY = 'one', HB = '/', T = '', EX = {}, I = {}, S = {snap: {}}, all = true, seen = true, errs = 0, draws = 0, ended = 0;
const NAV = {}, window = {navigation: 1}, navigation = {addEventListener: (n, f) => { on[n] = f }};
const location = {set href(v) { gone.push([v, H.opening, draws]); if (errs) on.navigateerror() }};
const addEventListener = (n, f) => { on[n] = f }, setTimeout = (f, ms) => { timers.push([f, ms]); return timers.length }, clearTimeout = i => { if (i) timers[i - 1][0] = () => {} };
const innerWidth = 400, innerHeight = 800, document = {querySelectorAll: () => seen ? [{getBoundingClientRect: () => ({width: 9, left: 0, right: 9, top: 0, bottom: 9})}] : []};
const esc = s => String(s), render = () => { draws++ }, toast = m => said.push(m), atAll = () => all, goDown = () => gone.push('down');
const PGROUPS = [['running', 'Running'], ['off', 'Off']], projectGroup = p => p.state, projectState = p => p.state, projectWords = p => '2 queued', projectMain = p => p.state === 'off' ? null : {open: 1};
const rowsNow = () => H.projects.map(p => ({key: p.key, name: p.name, href: '/p/' + p.key, on: p.key === HKEY, group: p.state, said: p.state, needs: 0}));
const homeNeeds = () => 0, meRow = () => '', projectHref = k => '/p/' + k, dotsBtn = () => '', landedLine = () => '', projectWarn = () => '', hobOf = () => '';
const card = (h, c, a) => `<div class="card ${c}" ${a}>${h}</div>`, oneProject = () => false, needsOf = () => 0, brand = () => '';
const projectOf = k => H.projects.find(p => p.key === k);
H.alerts = []; H.projects = [{key: 'one', name: 'One', state: 'running'}, {key: 'two', name: 'Two', state: 'running', left: 2}, {key: 'off', name: 'Off', state: 'off', left: 0}];
eval([cut('function allRow()', 'function allSide'), cut('function allSide()', '/* a project with no run up'), cut('function goProject(', '/* B153'),
  cut('function mainBtn', 'const dotsBtn'), cut('function projectCard', '/* a thing that waits')].join('\n').replace(/^const /gm, 'var '));
const out = {}, marks = () => [/<a class="prow opening running"/.test(allSide()) && allSide().split('Opening…').length - 1, projectCard(H.projects[1]).includes('pcard tap opening') && projectCard(H.projects[1]).includes('Opening…') && projectCard(H.projects[1]).includes('class="btn busy"'), allRow().includes('Opening Two…')];
out.before = marks();
goProject({key: 'two', href: '/p/two'});
out.pressed = marks(); out.gone = gone.slice(); out.quiet = said.slice();
out.other = projectCard(H.projects[0]).includes('pening');
for (const [f, ms] of timers) if (!ms) f();
on.pageshow(); out.back = marks();
// a newer press ends the load before it: its navigateerror leaves the newer mark
openProject('one', '/p/one'); errs = 1; openProject('two', '/p/two'); out.newer = H.opening; errs = 0;
for (const [f, ms] of timers) if (!ms) f();
on.navigateerror(); out.failed = H.opening;
openProject('off', '/p/off'); out.offCard = projectCard(H.projects[2]).includes('Opening…');
for (const [f, ms] of timers) if (ms === OPEN_MS) f();
out.late = H.opening;
seen = false; all = false; openProject('two', '/p/two'); out.said = said;
openingEnd(); gone.length = 0; all = true; goProject({key: 'one', on: true}); out.same = [gone, H.opening];
// a press on a row, a card's name and Open (links), and the card itself; with Ctrl the link is the browser's own
const i = page.indexOf("if((x=q('a[data-pkey]'))&&!("), j = page.indexOf('\n  if(slashOpen()', i);
const press = new Function('q', 'e', 'openProject', 'location', 'let x;' + page.slice(i, j));
const go = (sel, el, ev = {}) => { const got = []; let stopped = 0;
  press(s => (s === sel ? el : null), {preventDefault() { stopped++ }, ...ev}, (k, h) => got.push(k, h), {set href(v) { got.push('plain', v) }}); return [...got, stopped] };
out.link = go('a[data-pkey]', {dataset: {pkey: 'two'}, href: '/p/two'});
out.ctrl = go('a[data-pkey]', {dataset: {pkey: 'two'}, href: '/p/two'}, {ctrlKey: true});
out.card = go('[data-pgo]', {dataset: {pkey: 'two', pgo: '/p/two'}});
out.device = go('[data-pgo]', {dataset: {pgo: '/device'}});
console.log(JSON.stringify(out));
"""


def test_opening_b769b(tmp: Path) -> None:
    """B769b: a press marks the project's row, card and Open before the load starts; the mark goes when the page comes
    back, the load fails or OPEN_MS is over, and a newer press keeps its own."""
    (tmp / 'page.html').write_bytes(W.page_html())
    (tmp / 'd.js').write_text(DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'd.js'), str(tmp / 'page.html')], capture_output=True, text=True, encoding='utf-8', timeout=60)
    check(r.returncode == 0, 'node runs the page script', r.stderr[-800:])
    o = json.loads(r.stdout)
    eq(o['before'], [False, False, False], 'nothing is marked before a press')
    eq(o['pressed'], [1, True, True], 'the row, the card with its Open, and the project level say it')
    eq(o['gone'], [['/p/two', 'two', 1]], 'it was drawn before the load started')
    eq((o['quiet'], o['other']), ([], False), 'no toast beside a mark on screen; no other card is marked')
    eq(o['back'], [False, False, False], 'pageshow takes the mark away')
    eq((o['newer'], o['failed'], o['late']), ('two', '', ''), 'a newer press keeps its mark; a failed or late load loses it')
    eq(o['offCard'], True, 'an off project with nothing queued says it too')
    eq(o['said'], ['Opening Two…'], 'with no mark on screen a toast says it')
    eq(o['same'], [['down'], ''], 'the open project is not loaded again')
    eq(o['link'], ['two', '/p/two', 1], 'a link marks it')
    eq(o['ctrl'], [0], 'a link in a new tab does not')
    eq(o['card'], ['two', '/p/two', 0], 'a card marks it')
    eq(o['device'], ['plain', '/device', 0], 'a device is no project')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_opening_b769b)]))
