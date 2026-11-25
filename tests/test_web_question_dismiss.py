"""F192b: a question dismissed before (the card's ✕, until F437a) stays gone, and a later question has its card.

    python3 tests/test_web_question_dismiss.py
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

from _check import eq, report
from _web import in_tmp

import test_web_question as Q
from agent_runner import web as W  # noqa: E402

# on top of the question card's own driver: what the browser keeps, and the page's other tab
MORE = r"""
let kept = KEPT, others = [], box = {};
const store = {get: k => kept[k] || '', set: (k, v) => { kept[k] = v }};
const addEventListener = (k, f) => { if (k === 'storage') others.push(f) };
document.querySelector = s => s.endsWith('.qcard') ? null : {focus: () => { box.on = s }};
const tell = k => others.forEach(f => f({key: k}));
DISMISS
"""


def run(tmp: Path, steps: str, kept: dict | None = None) -> list | None:
    more = MORE.replace('KEPT', json.dumps(kept or {})).replace('DISMISS', (W.PAGE_DIR / '096-dismiss.js').read_text(encoding='utf-8'))
    with mock.patch.object(Q, 'DRIVER', Q.DRIVER.replace('(async', more + '(async', 1)):
        return Q.run(tmp, steps)


def test_kept(tmp: Path) -> None:
    out = run(tmp, """
      live(ASK); say(kind()); live({...ASK, need: 'F9'}); say(kind(), sent.length);
      S.thread = FD.n = 'c2'; live(ASK); say(kind());
      S.thread = FD.n = 'c1'; live({...ASK, id: 'u2'}); say(kind());
      kept['ar-qgone:t'] = '["c1 u2"]'; tell('ar-qgone:t'); say(kind());""",
              {'ar-qgone:t': '["c1 u1"]'})
    if out is None:
        return
    eq(out[:2], [[''], ['', 0]], 'one dismissed before stays gone, also once it is filed under Needs you')
    eq(out[2:4], [['card'], ['card']], 'another chat\'s question, or a new one, shows')
    eq(out[4], [''], 'dismissed in a tab still on the version before, it goes here too')
    eq(run(tmp, 'live(ASK); say(kind());', {'ar-qgone:t': '{broken'}), [['card']], 'what does not read dismisses nothing')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_kept)]))
