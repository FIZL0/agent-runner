"""F192b: Dismiss on the question card: it stays gone, sends nothing, and a later question has its card.

    python3 tests/test_web_question_dismiss.py
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

from _check import check, eq, report
from _web import in_tmp

import test_web_question as Q
from agent_runner import web as W  # noqa: E402

# on top of the question card's own driver: what the browser keeps, and the page's other tab
MORE = r"""
let kept = KEPT, others = [], box = {focus: () => { box.on = (box.on || 0) + 1 }};
const store = {get: k => kept[k] || '', set: (k, v) => { kept[k] = v }};
const addEventListener = (k, f) => { if (k === 'storage') others.push(f) };
document.querySelector = s => s === '[data-in]' ? box : null;
DISMISS
const dismiss = (id = 'u1', detail = 1) => tap({qdismiss: id}, detail);
"""


def run(tmp: Path, steps: str, kept: dict | None = None) -> list | None:
    more = MORE.replace('KEPT', json.dumps(kept or {})).replace('DISMISS', (W.PAGE_DIR / '096-dismiss.js').read_text(encoding='utf-8'))
    with mock.patch.object(Q, 'DRIVER', Q.DRIVER.replace('(async', more + '(async', 1)):
        return Q.run(tmp, steps)


def test_dismiss(tmp: Path) -> None:
    out = run(tmp, """
      live(ASK); say(dock); dismiss('other'); say(kind()); dismiss(); say(dock, sent.length, toasts.length, {...kept});
      await pass(20000); live({...ASK, need: 'F9'}); say(dock, sent.length, S.ob.length);
      live({...ASK, id: 'u2'}); say(kind()); pick(0, 'u2'); dismiss('u2'); say(kind()); await pass(6000); say(sent.map(x => x.args.text));""")
    if out is None:
        return
    check('data-qdismiss="u1" aria-label="Dismiss question"' in out[0][0], 'the card has its ✕, named', out[0][0])
    eq(out[1], ['card'], 'a tap meant for another question dismisses nothing')
    eq(out[2], ['', 0, 0, {'ar-qgone:t': '["c1 u1"]'}], 'a tap hides the card, kept in the browser; nothing is sent')
    eq(out[3], ['', 0, 0], 'it stays hidden once it is filed under Needs you, which is not answered')
    eq(out[4], ['card'], 'a later question has its card')
    eq(out[5], ['held'], 'an answer that waits has Undo, not Dismiss')
    eq(out[6], [['Full']], 'and goes')


def test_kept(tmp: Path) -> None:
    out = run(tmp, """
      live(ASK); say(kind()); S.thread = FD.n = 'c2'; live(ASK); say(kind());
      S.thread = FD.n = 'c1'; live({...ASK, id: 'u2'}); say(kind());
      dismiss('u2'); say(JSON.parse(kept['ar-qgone:t']));
      live({...ASK, id: 'u3'}); kept['ar-qgone:t'] = '["c1 u3"]'; others.forEach(f => f({key: 'ar-qgone:t'})); say(kind());""",
              {'ar-qgone:t': '["c1 u1"]'})
    if out is None:
        return
    eq(out[0], [''], 'over a reload it stays dismissed')
    eq(out[1:3], [['card'], ['card']], 'another chat\'s question, or a new one, shows')
    eq(out[3], [['c1 u1', 'c1 u2']], 'each is kept')
    eq(out[4], [''], 'dismissed in another tab, it goes here too')
    eq(run(tmp, 'live(ASK); say(kind());', {'ar-qgone:t': '{broken'}), [['card']], 'what does not read dismisses nothing')


def test_presses(tmp: Path) -> None:
    out = run(tmp, """
      live(ASK); pick(0); now += 600; undo(); dismiss(); say(kind()); await pass(600);
      dismiss('u1', 0); say(kind(), box.on);""")
    if out is None:
        return
    eq(out[0], ['card'], 'a double tap on Undo does not dismiss')
    eq(out[1], ['', 1], 'pressed with a key: the focus goes to the message box')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(f) for f in (test_dismiss, test_kept, test_presses)]))
