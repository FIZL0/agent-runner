"""F437c: the question card and its minimized line hide while the reader is scrolled up, in the history or where the
terminal scrolls itself, and are back at the bottom as they were; a held answer stays.

    python3 tests/test_web_question_scroll.py
"""
from __future__ import annotations

import re
from pathlib import Path

from _check import check, eq, report
from _web import in_tmp

import test_web_question_keys as K
from agent_runner import web as W  # noqa: E402

# the history and the terminal, as the scroll sees them: up px from the history's end; what the terminal says is FD.jump
VIEW = """const classes = new Set(), main = {toggle: (k, on) => { on ? classes.add(k) : classes.delete(k) }};
const query = document.querySelector; document.querySelector = s => s === '.main' ? {classList: main} : query(s);
let up = 0, jumps = 0, screen = [], lit = true;
globalThis.pastUp = () => up > 0; globalThis.pastEnd = () => 1000; globalThis.$ = k => ({scrollTop: 1000 - up}); globalThis.pastJumpDraw = () => jumps++;
globalThis.feedTerm = () => ({cols: 48, buffer: {active: {baseY: 0, getLine: () => ({getCell: () => ({isBgDefault: () => !lit})})}}}); globalThis.feedLines = () => screen;
const hid = () => classes.has('qaway'), scroll = px => { up = px; questionOn.scroll() }, jump = on => { FD.jump = on; questionOn.scroll() };
Object.assign(globalThis, {feedCells, FEED_PILL, TOUCH});
Object.assign(FD, {foot: {}, off: 0, jump: false, whole: false});
"""


def run(tmp: Path, steps: str) -> list | None:
    logic = (W.PAGE_DIR / '020-chats.logic.js').read_text(encoding='utf-8')
    pill = logic[logic.index('const feedSeg='):logic.index('// B194: the rule over')] + re.search(r'const FEED_PILL=.*\n', logic).group(0)
    return K.run(tmp, pill + VIEW + steps)


def test_history(tmp: Path) -> None:
    out = run(tmp, """
      live(ASK); questionOn.scroll(); say(hid()); scroll(24); say(hid()); scroll(25); say(hid(), look());
      scroll(10); await pass(1000); say(hid()); scroll(0); say(hid()); await pass(100); scroll(40); await pass(1000); say(hid());
      scroll(0); await pass(200); say(hid(), look()); await pass(2000); say(look());
      mini(); scroll(400); say(hid(), look()); scroll(0); await pass(200); say(hid(), look());
      FD.off = 60; questionOn.scroll(); say(hid()); FD.off = 0; questionOn.scroll(); await pass(200); say(hid());""")
    if out is None:
        return
    eq(out[:3], [[False], [False], [True, 'min']], 'a scroll at the edge hides nothing; one past it shrinks the card to its pill (F511)')
    eq(out[3:6], [[True], [True], [True]], 'it is back only once the end is reached and kept: no flicker at the edge')
    eq(out[6:8], [[False, 'min'], ['card']], 'F511: back at the bottom the pill stays, and grows into the card after 2 s still')
    eq(out[8:10], [[True, 'min'], [False, 'min']], 'the minimized line too')
    eq(out[10:], [[True], [False]], 'and over a frame that is pulled')


def test_terminal(tmp: Path) -> None:
    out = run(tmp, """
      live(ASK); jump(true); say(hid()); jump(false); await pass(100); jump(true); await pass(500); say(hid());
      jump(false); await pass(200); say(hid());
      FD.whole = true; FD.foot = null; screen = ['x', '- Our pa  Jump to bottom (ctrl+End) ↓ lowercase'];
      questionOn.scroll(); say(hid()); lit = false; questionOn.scroll(); await pass(200); say(hid());
      lit = true; screen = ['Jump to bottom (ctrl+End) ↓ is what it says']; questionOn.scroll(); say(hid());
      jump(true); say(hid()); S.thread = FD.n = 'c2'; FD.jump = false; questionOn.scroll(); say(hid());
      S.thread = FD.n = 'c1'; jump(true); FD.shown = false; questionOn.scroll(); say(hid());""")
    if out is None:
        return
    eq(out[:3], [[True], [True], [False]], 'the terminal\'s own scroll hides it, and a pill gone for one draw does not flicker')
    eq(out[3:6], [[True], [False], [False]], 'on a screen too low to find the prompt, by the pill; its words in an answer are none')
    eq(out[6:], [[True], [False], [False]], 'each chat for itself, and not when no session is shown')


def test_held(tmp: Path) -> None:
    out = run(tmp, """
      live(ASK); pick(0); scroll(400); say(kind(), hid()); jump(true); say(kind(), hid());
      await pass(600); undo(); say(kind(), hid()); up = 0; jump(false); await pass(600); say(kind(), hid());
      pick(0); await pass(400); scroll(400); await pass(6000); say(sent.map(x => x.args.text));""")
    if out is None:
        return
    eq(out[:2], [['held', False], ['held', False]], 'a held answer stays, with its Undo')
    eq(out[2:4], [['', True], ['', False]], 'F511: after Undo scrolled up it is the pill, also just back at the bottom')
    eq(out[4], [['Full']], 'and it goes as it would')
    out = run(tmp, "live(ASK); tap({qchat: 'u1'}); scroll(400); say(hid());")
    eq(out, [[False]], 'the marked question stays too')


def test_keys(tmp: Path) -> None:
    out = run(tmp, """
      S.keys = true; live(ASK); say(keys()); scroll(400); say(keys(), classes.has('qkeys')); scroll(0); await pass(200); say(keys(), classes.has('qkeys'));
      S.keys = false; keysFlip(); scroll(400); say(keys(), classes.has('qkeys')); keysFlip(); say(keys(), S.keys); scroll(0); await pass(200); say(keys());
      FD.whole = true; FD.foot = null; live({...ASK, id: 'u2'}); jump(true); say(keys());""")
    if out is None:
        return
    eq(out[:3], [[0], [1, False], [1, False]], 'F511: the key row is back under the pill, which keeps its own room')
    eq(out[3:6], [[1, False], [0, False], [0]], 'opened under the card it stays, with its own room, and the button closes it')
    eq(out[6], [1], 'one row in a menu')


def test_page(tmp: Path) -> None:
    page = W.PAGE.read_text(encoding='utf-8')
    rule = re.search(r'\.main\.sess\.qaway \.qcard:not\(\.qheld,\.qabout,\.qmin\)\{([^}]*)\}', page)
    eq(rule and rule.group(1), 'display:none', 'B854b: hidden with no room left, so the text shows down to the message box')
    check('margin-bottom:calc(var(--s2) - 2*var(--tap) - 14px)' in page and 'gap:6px;max-width:720px;margin:0 auto 8px} .keys' in page, 'the key row takes of the card\'s room what it is high')
    check('const slimMay=()=>!QN.held.has(FD.n)&&' in page, 'the bars, and a held answer with them, stay')
    for f in ('pastScrolled', 'pastSee', 'pastLive', 'pastPlace'):
        body = page[page.index(f'function {f}('):]
        check('questionOn.scroll()' in body[:body.index('\n}\n')], f'{f} says where the reader is')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(f) for f in (test_history, test_terminal, test_held, test_keys, test_page)]))
