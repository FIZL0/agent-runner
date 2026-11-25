"""F437b: no key row with an open question card, unless the keyboard button opens it there.

    python3 tests/test_web_question_keys.py
"""
from __future__ import annotations

from pathlib import Path

from _check import check, eq, report
from _web import in_tmp

import test_web_question_minimize as M
from agent_runner import web as W  # noqa: E402

# the chats script's own lines, from the key row's buttons to its state, and sessRow, on top of the card's driver
STUBS = """const FEED_KEYS = [['up', '↑'], ['left', '←']], TOUCH = () => true, modelOf = () => model, sessionOf = () => null, feedNow = () => state;
let model = '', state = 'session';
const sessionChips = () => [], sessWorks = () => false, slimDraw = () => {}, I = {};
globalThis.kbFocus = () => {};
const keys = () => (sessRow(S.thread) + keysRow()).split('class="keys"').length - 1;
"""


def run(tmp: Path, steps: str) -> list | None:
    js = (W.PAGE_DIR / '090-chats.js').read_text(encoding='utf-8')
    row = js[js.index('const keyButtons='):js.index('/* the screen\'s text in a sheet')]
    sess = js[js.index('const sessUp='):]
    return M.run(tmp, STUBS + row + sess[:sess.index('\n}\n') + 3] + steps)


def test_open(tmp: Path) -> None:
    out = run(tmp, """
      FD.foot = {}; say(keys()); keysFlip(); say(keys()); live(ASK); say(keys(), keysShown(), S.keys);
      keysFlip(); say(keys(), keysShown()); keysFlip(); say(keys(), S.keys); keysFlip();
      live({...ASK, id: 'u2'}); say(keys()); live(null); say(keys());
      live(ASK); say(keys()); S.keys = false; live(null); say(keys());""")
    if out is None:
        return
    eq(out[:2], [[0], [1]], 'with no card, the keyboard button opens the key row')
    eq(out[2], [0, False, True], 'a card takes it away, and what it was is kept')
    eq(out[3:5], [[1, True], [0, True]], 'the button opens it with the card, and closes it')
    eq(out[5:7], [[0], [1]], 'a new question is without it; it is back once the card is gone')
    eq(out[7:], [[1], [0]], 'one opened with the card stays while that is asked; closed before, it is closed after')


def test_ways_back(tmp: Path) -> None:
    out = run(tmp, """
      FD.foot = {}; S.keys = true; live(ASK); say(keys());
      mini(); say(keys()); now += 600; show(); say(keys()); now += 600;
      tap({qchat: 'u1'}); say(keys()); now += 600; tap({qunchat: 'c1'}); say(keys()); now += 600;
      pick(0); say(keys()); now += 600; undo(); say(keys()); now += 600;
      pick(0); await pass(6000); say(keys());""")
    if out is None:
        return
    eq(out[0], [0], 'not with the card')
    eq(out[1:3], [[1], [0]], 'back while it is minimized')
    eq(out[3:5], [[1], [0]], 'and while the question is marked above the box')
    eq(out[5:7], [[0], [0]], 'an answer that waits is not given yet, and Undo moves no key row')
    eq(out[7], [1], 'back once it is answered')


def test_menu(tmp: Path) -> None:
    out = run(tmp, """
      FD.whole = true; say(keys()); live(ASK); say(keys()); keysFlip(); say(keys()); keysFlip(); S.keys = true; say(keys());
      state = 'ended'; say(keys()); state = 'session'; S.thread = FD.n = 's1'; say(keys());""")
    if out is None:
        return
    eq(out[:2], [[1], [0]], 'nor the row that stands in place of the chips')
    eq(out[2:4], [[1], [0]], 'the button opens one row')
    eq(out[4:], [[1], [1]], 'with no card drawn, and in a slot, it is as before')


def test_called(tmp: Path) -> None:
    page = W.PAGE.read_text(encoding='utf-8')
    toggle = page[page.index('function keysToggle('):]
    toggle = toggle[:toggle.index('\n}\n')]
    check('keysFlip()' in toggle and 'S.keys' not in toggle, 'the keyboard button goes by what is shown', toggle)
    check('aria-expanded="${keysShown()}" aria-label="Keys for the session"' in page, 'and says so')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(f) for f in (test_open, test_ways_back, test_menu, test_called)]))
