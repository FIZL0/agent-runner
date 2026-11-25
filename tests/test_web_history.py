"""The run page, the session history (F191b): the lines it draws, where they meet the screen, the swap to it and back,
its button, and where the session scrolls as before.

    python3 tests/test_web_history.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from _check import check, eq, report
from _web import in_tmp, logic_js

from agent_runner import session_history as H
from agent_runner import web as W

PART = Path(W.__file__).parent / 'page' / '092-history.js'
NODE = bool(shutil.which('node'))


def texts(entries: list[dict], cols: int = 48) -> list[str]:
    return [x['t'] for x in logic_js([['pastLines', entries, cols]])[0]]


def say(t: str) -> dict:
    return {'kind': 'say', 'text': t}


def test_lines(tmp: Path) -> None:
    """The lines, word for word as Claude Code 2.1.331 draws them at 48 columns (captured from it)."""
    if not NODE:
        print('  (no node here: skipped)')
        return
    eq(texts([{'kind': 'you', 'text': 'Message 0: please look at this and tell me what you think, in a line that is long enough to wrap around'}]),
       ['', '❯ Message 0: please look at this and tell me', '  what you think, in a line that is long enough', '  to wrap around'], 'your words')
    eq(texts([say('Answer 0. Here is a paragraph with **bold words**, *italic words*, `inline code` and a [link](https://x.y), long enough to wrap over several lines of a phone.\n\n'
                  '# Heading one\n\nText.\n\n## Heading two\n- first bullet that is long enough to wrap around on the narrow phone screen\n- second with `code`\n'
                  '  - nested bullet also long enough that it must wrap on a narrow screen\n\n1. one\n2. two, long enough to wrap around on the narrow phone screen here\n   - sub\n10. ten')]),
       ['', '● Answer 0. Here is a paragraph with bold words,', '  italic words, inline code and a link, long', '  enough to wrap over several lines of a phone.', '',
        '  Heading one', '', '  Text.', '', '  Heading two', '', '  - first bullet that is long enough to wrap', '    around on the narrow phone screen',
        '  - second with code', '    - nested bullet also long enough that it', '      must wrap on a narrow screen', '', '  1. one',
        '  2. two, long enough to wrap around on the', '     narrow phone screen here', '     - sub', '  3. ten'], 'markdown')
    eq(texts([say('```python\ndef f(x):\n    return x + 1  # a comment that is long enough to wrap around on a phone\n```\n\n> a quote that is long enough to wrap around on the narrow phone screen\n\n'
                  '| Name | Value | Note |\n|---|---|---|\n| a | 1 | short |\n| bb | 22 | a somewhat longer note here |\n\n---\n\nLast.')])[1:],
       ['● def f(x):', '      return x + 1  # a comment that is long', '  enough to wrap around on a phone', '', '  ▎ a quote that is long enough to wrap around',
        '  ▎ on the narrow phone screen', '', '  ┌──────┬───────┬───────────────────────────┐', '  │ Name │ Value │           Note            │',
        '  ├──────┼───────┼───────────────────────────┤', '  │ a    │ 1     │ short                     │', '  ├──────┼───────┼───────────────────────────┤',
        '  │ bb   │ 22    │ a somewhat longer note    │', '  │      │       │ here                      │', '  └──────┴───────┴───────────────────────────┘', '', '  ---', '', '  Last.'],
       'code, a quote, a table')
    tool = lambda name, arg, **kw: {'kind': 'tool', 'name': name, 'arg': arg, 'state': 'ok', **kw}
    diff = {'file': 'a.py', 'added': 2, 'removed': 1, 'cut': 0, 'hunks': [
        {'old': 9, 'new': 9, 'lines': [' def f():', '-    return a', '+    return b  # changed to something long enough to wrap', ' x = 1']},
        {'old': 99, 'new': 99, 'lines': [' y', '+z']}]}
    eq(texts([tool('Read', 'a', group='read'), tool('Search', 'b', group='search'), say('x'), tool('Bash', 'ls -la'), say('y'),
              tool('Bash', 'false', state='error'), tool('Update', 'agent_runner/a.py', summary='Added 2 lines, removed 1 line', diff=[diff]),
              tool('Write', 'n.txt', summary='Wrote 14 lines to /r/n.txt', text='\n'.join(f'line {i}' for i in range(14)), show=10, lines=14)]),
       ['', '  Searched for 1 pattern, read 1 file', '', '● x', '', '  Listed 1 directory', '', '● y', '', '  Ran 1 shell command · 1 failed', '',
        '● Update(agent_runner/a.py)', '  ⎿  Added 2 lines, removed 1 line', '       9  def f():', '      10 -    return a', '      10 +    return b  # changed to some',
        '         +thing long enough to wrap', '      11  x = 1', '     ...', '       99  y', '      100 +z', '', '● Write(n.txt)', '  ⎿  Wrote 14 lines to n.txt',
        *[f'      {i + 1:2d} line {i}'[0:] for i in range(10)], '     … +4 lines'], 'calls folded, a diff, a new file')
    got = texts([{'kind': 'note', 'what': 'event', 'text': 'Background command "a &gt; b" done'}, {'kind': 'note', 'what': 'turn', 'ms': 83000},
                 {'kind': 'you', 'text': '/model opus', 'command': True}, {'kind': 'note', 'what': 'output', 'text': 'Set model to opus'},
                 {'kind': 'note', 'what': 'interrupted', 'text': 'Interrupted'}])
    eq(got, ['', '● Background command "a > b" done', '', '✻ Worked for 1m 23s', '', '❯ /model opus', '  ⎿  Set model to opus', '  ⎿  Interrupted'], 'notes')
    eq(texts([say('see /home/me/a-path-that-is-much-longer-than-one-line-of-a-phone/and-more/of-it.txt')])[1:],
       ['● see /home/me/a-path-that-is-much-longer-than-o', '  ne-line-of-a-phone/and-more/of-it.txt'], 'a word longer than a line')
    eq(texts([say('日本語の長い文がここにあります日本語の長い文がここにあります')])[1:],
       ['● 日本語の長い文がここにあります日本語の長い文が', '  ここにあります'], 'wide letters take two cells')
    html = logic_js([['pastLines', [say('a <b>&</b> `x<y`'), {'kind': 'you', 'text': '<script>alert(1)</script>'}], 48]])[0]
    check(not any('<script' in x['h'] or '<b>&' in x['h'] for x in html) and any('&lt;script&gt;' in x['h'] for x in html), 'words are never markup', html)


def test_join(tmp: Path) -> None:
    """Where the screen meets the lines; what is not in them yet is taken from the screen."""
    if not NODE:
        return
    ln = lambda *ts: [{'t': t, 'h': t} for t in ts]
    hist = [x for i in range(50) for x in ('', f'● answer {i}', '', '  Ran 1 shell command')]
    screen = [*hist[180:], '', '● being written now', '✻ Working… (3s)']
    cases = [['pastJoin', ln(*hist), ln(*screen)],
             ['pastJoin', ln(*hist), ln('● being written', '  nothing of this is there')],
             ['pastJoin', ln(*hist[:8]), ln('  banner', '', *hist[:8])],
             ['pastJoin', ln(*hist), ln('  other mark', *hist[181:])],
             ['pastJoin', ln('● a', '✻ Worked for 1m 2s · done 9:00 AM'), ln('✻ Baked for 1m 2s · done 9:00 AM', '', 'x')],
             ['pastJoin', ln('● once', 'same', 'same', 'same'), ln('same', 'new one')]]
    eq(logic_js(cases), [180, -1, 0, 180, 1, 3], 'its first line; none; a screen with a banner; a line that differs; a turn\'s end, in other words; the last of many')
    old = [{'kind': 'tool', 'call': 'a', 'name': 'Bash', 'state': 'open'}]
    got = logic_js([['pastMerge', old, [{'kind': 'result', 'call': 'a', 'id': 'r', 'state': 'ok', 'text': 'x'}, say('done'), {'kind': 'result', 'call': 'zz', 'state': 'ok'}]]])[0]
    eq([(e['kind'], e.get('state'), e.get('text')) for e in got], [('tool', 'ok', 'x'), ('say', None, 'done')], 'a result goes in its call')
    ink = logic_js([['pastInk', [163, 161, 153], [38, 38, 36], 4.5], ['pastInk', [175, 215, 255], [250, 249, 245], 4.5]])
    eq(ink[0], [163, 161, 153], 'a colour that reads stays')
    check(all(a < b for a, b in zip(ink[1], [175, 215, 255])), 'one that does not is drawn darker, as the terminal does', ink[1])


def test_own_folder(tmp: Path) -> None:
    """A file of the session's own folder is named as Claude Code names it."""
    row = {'type': 'assistant', 'uuid': 'u', 'cwd': '/r', 'message': {'content': [
        {'type': 'tool_use', 'id': 'a', 'name': 'Edit', 'input': {'file_path': p}} for p in ('/r/a/b.py', '/rest/c.py')]}}
    eq([e['arg'] for e in H.row_entries(row, 0)], ['a/b.py', '/rest/c.py'], 'its own, and another')


DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const logic = page.split('<script id="logic">')[1].split('</script>')[0].replace(/if\(typeof module[^\n]*/, '');
const code = require('fs').readFileSync(process.argv[3], 'utf8');
const CELL = 20, ROWS = 40, VIEW = 800;
let timers = [], now = 0, calmNow = false, pages = {}, asked = [], clicks = 0, sheets = 0, wheels = 0;
const cls = () => { const s = new Set(); return {s, toggle(k, on) { on ? s.add(k) : s.delete(k) }, contains: k => s.has(k)} };
function El() {
  const e = {on: {}, kids: [], style: {setProperty(k, v) { this[k] = v }}, classList: cls(), attrs: {}, hidden: false, _top: 0, _html: '', offsetHeight: 180, isConnected: true,
    addEventListener(t, f) { (e.on[t] = e.on[t] || []).push(f) }, fire(t, ev = {}) { for (const f of e.on[t] || []) f({target: e, type: t, touches: [], changedTouches: [{clientX: 9, clientY: 9}], cancelable: true, preventDefault() { e.stopped = true }, closest: () => null, ...ev}) },
    setAttribute(k, v) { e.attrs[k] = v }, getAttribute: k => e.attrs[k], removeAttribute(k) { delete e.attrs[k] }, getBoundingClientRect: () => ({left: 0, top: 0, width: 390, height: VIEW}),
    appendChild(k) { e.kids.push(k); k.parent = e }, insertBefore(k, n) { const i = n ? e.kids.indexOf(n) : e.kids.length; e.kids.splice(i, 0, k); k.parent = e }, remove() { e.parent.kids = e.parent.kids.filter(k => k !== e) }, contains: () => false,
    get children() { return e.kids }, get lastChild() { return e.kids[e.kids.length - 1] }, get firstElementChild() { return e.kids[0] },
    set textContent(v) { e.kids = [] }, get innerHTML() { return e._html }, set innerHTML(v) { e._html = v }, querySelectorAll: () => spans(e), querySelector: () => null, clientHeight: VIEW};
  return e;
}
const els = {}, $ = k => els[k] = els[k] || El();
const jump = El(); $('pastjump').kids = [jump];
const past = $('feedpast');
Object.defineProperty(past, 'scrollTop', {get: () => past._top, set(v) { past._top = Math.max(0, Math.min(v, past.scrollHeight - VIEW)) }});
Object.defineProperty(past, 'scrollHeight', {get: () => Math.max(VIEW, parseFloat($('pastrows').style.height) || 0)});
const document = {hidden: false, createElement: El, head: El(), querySelector: s => s === '.dockwrap' ? $('dockwrap') : null};
const window = {}, getSelection = () => null, setTimeout = (f, ms) => timers.push(f), clearTimeout = () => {}, Date = {now: () => now};
const run = () => { const t = timers; timers = []; t.forEach(f => f()) };
const S = {snap: {}}, SW = null, MO = {scroll: new Map()}, calm = () => calmNow, tq = p => p, slimRow = () => 56, feedSkinOf = () => 'page-dark', feedLook = () => 'dark', moAnim = () => {};
let glides = []; const scrollGlide = (el, to) => { glides.push(to()); }, scrollStop = () => {}, feedClick = () => clicks++, feedText = () => sheets++;
const FD = {n: 'c6', shown: true, up: true, drawn: true, whole: false, foot: {top: 36, text: '', bash: false}, jump: false, off: 0, short: 0, t: -100, bar: 60, above: 600, run: 0, slim: false, info: {}};
const feedSlim = on => { FD.slim = on };
const rowEl = t => ({textContent: t, innerHTML: '<span>' + t + '</span>', getBoundingClientRect: () => ({})});
let screen = [];
let tint = '';  // the contrast colour the terminal puts inline on its rows
const term = {cols: 48, rows: ROWS, options: {}, element: {className: 'xterm', querySelector: () => ({style: {}, children: screen.map((t, y) => ({textContent: t, innerHTML: '<span' + (tint && ` style="color:${tint}"`) + '>' + t + '</span>', getBoundingClientRect: () => ({top: 12 + y * CELL})}))})}};
const feedTerm = () => term, feedScreen = () => ({t: term, cell: CELL, el: {getBoundingClientRect: () => ({left: 14, top: 12, width: 346}), querySelectorAll: () => [{textContent: sheet}]}, win: {document: {styleSheets: []}, getComputedStyle: () => ({color: ink})}});
// the terminal's sheet and computed colour; a row's one span, as the page computes its colours
let sheet = '.x{color:#f3f1ea}', ink = '#f3f1ea';
const getComputedStyle = s => ({color: s.color, backgroundColor: 'rgba(0, 0, 0, 0)'});
const spans = box => box.kids.flatMap(d => { const m = /style="color:([^"]+)"/.exec(d.innerHTML); return m ? [{color: m[1], style: {set color(v) { d.innerHTML = d.innerHTML.replace(m[1], v) }}}] : [] });
const fetch = async q => { asked.push(q); const j = pages[q.replace(/history\/c\d/, "")]; return {ok: true, status: 200, json: async () => j || {ok: false}} };
const settle = async () => { for (let i = 0; i < 30; i++) await null };
const msgs = (a, b) => Array.from({length: b - a}, (x, i) => ({kind: 'say', text: `message ${a + i}`}));
const show = (last, extra = []) => { const l = []; for (let i = last - 30; i < last; i++) l.push('', `● message ${i}`); screen = [...l, ...extra].slice(-36).concat(['rule', '❯', 'rule', 'foot']) };
(async () => {
eval(logic + code + `
/* where a line stands on screen now: in the history when it is drawn, else in the session */
const where = t => { if (HX.st) { const i = HX.L.findLastIndex(x => x.t.trim() === t); return i < 0 ? null : HX.pad + i * HX.cell - past.scrollTop } const y = screen.findIndex(x => x.trim() === t); return FD.t + 12 + y * CELL };
const scroll = by => { past.scrollTop += by; pastScrolled() };
const drawn = () => $('pastrows').kids.reduce((n, k) => n + k.kids.length, 0);
(async () => {
const out = {};
pages[''] = {ok: true, entries: msgs(100, 200), before: 'f:9', since: 'f:99', reset: false, more: false};
pages['?before=f%3A9&n=200'] = {ok: true, entries: msgs(0, 100), before: '', since: 'f:99'};
pages['?since=f%3A99'] = {ok: true, entries: [], since: 'f:99'};
show(200); pastSee(); out.loading = [HX.n, histMay0()]; await settle();
out.loaded = [HX.none, HX.pages.length, past.hidden, past.classList.contains('armed')];
run(); await settle(); out.key = [pastPress({key: 'PageUp'}), HX.st, pastPress({key: 'End', ctrlKey: true}), HX.st, pastPress({key: 'x'}), pastPress({key: 'Home'})]; out.rest = [HX.st, past.scrollTop === pastEnd(), jump.attrs['aria-label'], $('pastjump').inert];
// the swap: every line where it was, at each step
const w0 = where('● message 199'), m0 = where('● message 190');
past.fire('touchstart', {touches: [{clientX: 9, clientY: 9}]}); out.armed = [HX.st, where('● message 199') - w0, where('● message 190') - m0, past.classList.contains('armed'), past.classList.contains('up')];
const path = []; for (let i = 0; i < 5; i++) { scroll(-7); path.push(where('● message 199') - w0) } out.path = path;
out.up = [HX.st, FD.slim, past.classList.contains('up'), past.attrs['aria-hidden'], past.tabIndex];
past.fire('touchend'); out.stays = [HX.st, clicks];
scroll(-200); out.button = [$('pastjump').classList.contains('on'), $('pastjump').inert, $('pastjump').style.bottom, $('pastjump').style['--up']];
// new words while reading: nothing on screen moves
const r0 = where('● message 170'); show(204); pastSee(); out.newer = [where('● message 170') - r0, HX.news, jump.attrs['aria-label'], HX.L[HX.L.length - 1].t];
show(204, ['', '● being written']); pastSee(); out.writing = [where('● message 170') - r0, HX.L[HX.L.length - 1].t, HX.L.filter(x => x.t === '● message 203').length];
show(204, ['', '● being written, more']); pastSee(); out.more = [where('● message 170') - r0, HX.L[HX.L.length - 1].t, HX.L.filter(x => /being/.test(x.t)).length];
// a menu comes: the reader stays, and is told
HX.news = false; FD.whole = true; FD.foot = null; pastSee(); out.menu = [HX.st, HX.news, where('● message 170') - r0]; FD.whole = false; FD.foot = {top: 36, text: '', bash: false};
// older pages go in over the others, with nothing moved
await settle(); run(); await settle(); run();
out.older = [HX.before, HX.pages.length, HX.L.filter(x => /^● message 5$/.test(x.t)).length, where('● message 170') - r0];
out.drawn = [HX.L.length > 400, drawn() < 400];
// its end again: the live session, in the same frame
const e0 = where('● being written, more'); scroll(pastEnd() - past.scrollTop - 30); const e1 = where('● being written, more'); scroll(30);
out.back = [HX.st, past.classList.contains('armed'), FD.slim, $('pastjump').classList.contains('on'), where('● being written, more') - e1 + 30];
// a wheel
out.wheel = [pastWheel(-60), HX.st, pastWheel(-60), pastEnd() - past.scrollTop, pastWheel(120), HX.st, pastWheel(60)];
// the button glides, at once under calm()
pastWheel(-400); jump.fire('click'); out.glide = [glides.length, glides[0] === pastEnd(), HX.st]; calmNow = true; jump.fire('click'); out.calm = [glides.length, HX.st, past.scrollTop === pastEnd()]; calmNow = false;
// the tap that ends a fling has no click of its own
pastWheel(-400); glides = []; jump.fire('touchstart', {touches: [{clientX: 9, clientY: 9}]}); jump.fire('touchend'); out.fling = [glides.length, jump.stopped]; pastDown();
// a tap and a long press at rest are the session's
run(); clicks = 0; past.fire('touchstart', {touches: [{clientX: 9, clientY: 9}]}); past.fire('touchend'); out.tap = [clicks, HX.st];
timers = []; past.fire('touchstart', {touches: [{clientX: 9, clientY: 9}]}); run(); past.fire('touchend'); out.press = [sheets, clicks, HX.st];
// where it cannot stand in, the session scrolls as it did
const may = o => { const was = {...FD}; Object.assign(FD, o); pastClass(); const r = [past.hidden, pastWheel(-60), HX.st]; Object.assign(FD, was); pastClass(); return r };
out.whole = may({whole: true}); out.words = may({foot: {top: 36, text: 'draft', bash: false}}); out.jumped = may({jump: true}); out.down = may({drawn: false});
HX.none = true; out.none = may({}); HX.none = false;
FD.n = 'c7'; pastReset(); pages[''] = null; pastSee(); pastClass(); await settle(); pages[''] = {ok: true, entries: msgs(0, 5), before: '', since: 'g:1'}; pastSee(); out.soon = HX.none; now += 6000; pastSee(); await settle(); out.late = [HX.none, HX.pages.length]; FD.n = 'c8'; pages[''] = null; pastSee(); await settle(); pastClass(); out.notranscript = [HX.none, past.hidden];
// B786: a new chat that works, resting under the top bar: the history on the same pixels, nothing to scroll
FD.n = 'c9'; FD.t = FD.bar; FD.short = FD.gap = 3; pages[''] = {ok: true, entries: [{kind: 'you', text: 'hello'}], before: '', since: 'h:1'};
screen = ['', '❯ hello', '● on it', ...Array(31).fill(''), '● Churning… (7s)', '', 'rule', '❯', 'rule', 'foot']; pastSee(); await settle(); run(); pastPlace();
const g0 = [where('❯ hello'), where('● Churning… (7s)')]; past.fire('touchstart', {touches: [{clientX: 9, clientY: 9}]}); scroll(-50); pastPlace();
out.gap = [HX.st, where('❯ hello') - g0[0], where('● Churning… (7s)') - g0[1], pastEnd(), $('pastjump').classList.contains('on')]; past.fire('touchend');
FD.t = 20; pastPlace(); out.gapOver = [HX.st, past.scrollTop === pastEnd(), $('pastjump').classList.contains('on')];
// B787: the look; two sheets of the same length
const look = (css, c, bg, own) => { sheet = css; ink = c; tint = own; term.options = {theme: {background: bg, foreground: c}} }, LIGHT = ['.x{color:#141413}', '#141413', '#faf9f5', 'rgb(20, 20, 19)'], DARK = ['.x{color:#f3f1ea}', '#f3f1ea', '#262624', 'rgb(243, 241, 234)'];
const inks = () => [$('pastrows').style.color, $('pastcss')._css, [...new Set(HX.L.filter(l => l.own != null).map(l => (/color:([^"]+)/.exec(l.h) || [])[1]))].map(c => c.match(/[0-9]+/g).map(Number)).every(c => (c[0] > 120) === (ink === '#f3f1ea'))];
FD.n = 'c1'; FD.t = -100; FD.short = FD.gap = 0; pages[''] = {ok: true, entries: msgs(100, 200), before: '', since: 'i:1'}; show(200);
look(...LIGHT); pastSee(); await settle(); run(); out.restLight = inks(); look(...DARK); pastSee(); run(); out.restDark = inks();
pastWheel(-400); show(204); pastSee();
const l0 = where('● message 170'), y0 = past.scrollTop; out.upOld = HX.L.filter((l, i) => l.own != null && i < HX.at).length > 0;
out.flips = []; for (const to of [LIGHT, DARK, LIGHT]) { look(...to); pastSee(); out.flips.push([...inks(), where('● message 170') - l0, past.scrollTop - y0, HX.st]) }
FD.whole = true; FD.foot = null; look(...DARK); pastSee(); out.flipMenu = [...inks(), where('● message 170') - l0];
console.log(JSON.stringify(out));
})().catch(e => { console.error(e); process.exit(1) });
function histMay0() { return pastMay() }
`);
})();
"""


def test_swap(tmp: Path) -> None:
    """The swap to the history and back, recorded at each step; its button; what is new; where it does not stand in."""
    if not NODE:
        print('  (no node here: skipped)')
        return
    (tmp / 'd.js').write_text(DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'd.js'), str(W.PAGE), str(PART)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0 and r.stdout, 'node runs the history', r.stderr[-1500:])
    if not r.stdout:
        return
    o = json.loads(r.stdout)
    eq(o['loading'], ['c6', True], 'it stands in from the first draw, its page asked for')
    eq(o['loaded'], [False, 1, False, False], 'loaded: there, and see-through')
    eq(o['rest'], ['', True, 'Jump to bottom', True], 'at rest: the live session, no button')
    eq(o['armed'], ['armed', 0, 0, True, False], 'a touch draws it over the session, every line where it was')
    eq(o['path'], [7, 14, 21, 28, 35], 'a line goes with the finger, from the first pixel')
    eq(o['up'], ['up', True, True, None, 0], 'scrolled up: the bars away, and it is there for a reader and the keyboard')
    eq(o['stays'], ['up', 0], 'the finger lifts: it stays, and it was no tap')
    eq(o['button'], [True, False, '56px', '124px'], 'the button, just over the slim box, higher over the full one')
    eq(o['newer'], [0, True, 'Jump to bottom: there is something new', '● message 203'], 'new words move nothing, and it says so')
    eq(o['writing'], [0, '● being written', 1], 'a reply being written, from the screen, each line once')
    eq(o['more'], [0, '● being written, more', 1], 'as it goes on')
    eq(o['menu'], ['up', True, 0], 'a menu or a question: the reader stays, and is told')
    eq(o['older'], ['', 2, 1, 0], 'an older page goes in, and nothing moves')
    eq(o['drawn'], [True, True], 'a long chat: only the lines near the view are in the page')
    eq(o['back'], ['', False, False, False, 0], 'back at its end: the live session, the bars back, no line moved')
    eq(o['wheel'], [True, 'up', True, 120, True, '', True], 'a wheel up opens it, scrolls it, and down to its end; none goes to the session')
    eq((o['glide'], o['calm']), ([1, True, 'up'], [1, '', True]), 'the button glides to the end; at once under calm()')
    eq(o['fling'], [1, True], 'a tap that ends a fling is one press')
    eq((o['tap'], o['press']), ([1, ''], [1, 1, '']), "at rest a tap clicks in the session, a long press gives its text")
    for k in ('whole', 'words', 'jumped', 'down', 'none'):
        eq(o[k], [True, False, ''], f'{k}: the session scrolls as before')
    eq(o['key'], [True, 'up', True, '', False, False], 'PageUp and Ctrl+End scroll it, other keys are the session\'s')
    eq((o['soon'], o['late']), (True, [False, 1]), 'a transcript that comes later is found')
    eq((o['gap'], o['gapOver']), (['armed', 0, 0, 0, False], ['', True, False]), 'B786: a new chat that works rests the same, with no up and no button')
    light, dark = ['#141413', '.x{color:#141413}', True], ['#f3f1ea', '.x{color:#f3f1ea}', True]
    eq((o['restLight'], o['restDark']), (light, dark), 'B787: a look whose sheet is as long as the last one\'s is taken whole')
    check(o['upOld'], 'lines of an earlier screen are drawn')
    eq(o['flips'], [[*x, 0, 0, 'up'] for x in (light, dark, light)], 'B787: scrolled up, a look change draws every line anew, and nothing moves')
    eq(o['flipMenu'], [*dark, 0], 'and under a menu')
    eq(o['notranscript'], [True, True], 'a session with no transcript: as before')


def test_page(tmp: Path) -> None:
    page = W.PAGE.read_text(encoding='utf-8')
    css = page[page.index('.feedpast{'):page.index('.pastjump svg')]
    for part in ('overscroll-behavior:none', 'touch-action:pan-y pinch-zoom', 'overflow:hidden scroll', '.feedpast.up{pointer-events:auto;-webkit-user-select:text',
                 '@media (pointer:coarse){.feedpast{pointer-events:auto}}', 'width:var(--tap);height:var(--tap)', '.main.still .pastjump{transition:none}'):
        check(part in css, f'the scroller has {part}')
    wrap, button = (css.split(sel + '{', 1)[1].split('}', 1)[0] for sel in ('\n.pastjump', '\n.pastjump button'))
    check('background' not in wrap and 'pointer-events:none' in wrap, 'the jump button floats: nothing drawn beside it, and a press there is the text\'s (B788)', wrap)
    check(all(x in button for x in ('background:var(--surface)', 'border:1px solid', 'pointer-events:auto')), 'its button has its own fill and border, and takes the press', button)
    check('.feedpast:not(.up) #pastterm{pointer-events:none}' in css, 'at rest the touch is on the scroller, never on a row that is drawn again')
    check('if(pastWheel(px))return true;' in page.split('function feedTake(', 1)[1][:60], 'a wheel over the frame is the history\'s first')
    check('pastStop()}return el}' in page, 'a press on the slim message box ends a fling (B218b1)')
    check('(pastUp()||FD.jump&&FD.far>8)' in page, 'the bars go away over the history')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(t) for t in (test_lines, test_join, test_own_folder, test_swap, test_page)]))
