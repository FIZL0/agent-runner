"""F192c: focusing or typing in the message box shrinks the question card to its minimized line; a tap or an empty box opens it.

    python3 tests/test_web_question_typing.py
"""
from __future__ import annotations

from pathlib import Path
from unittest import mock

from _check import eq, report
from _web import in_tmp

import test_web_question as Q
from agent_runner import web as W  # noqa: E402

# listeners by kind; the box is a [data-in] textarea
MORE = r"""
const on = {};
let coarse = true;
const TOUCH = () => coarse;
const fire = (k, e) => (on[k] || []).forEach(f => f(e));
const ta = {value: '', matches: s => s === '[data-in]', closest: () => null};
const focus = () => fire('focusin', {target: ta}), type = v => { ta.value = v; fire('input', {target: ta}) }, blur = () => fire('focusout', {target: ta});
const look = () => dock.includes('data-qshow') ? 'min' : kind();
"""


def run(tmp: Path, steps: str) -> list | None:
    d = Q.DRIVER.replace('addEventListener: (k, f) => { clicks.push(f) }', "addEventListener: (k, f) => { if (k === 'click') clicks.push(f); else (on[k] = on[k] || []).push(f) }")
    d = d.replace('PAGE', MORE + 'PAGE')
    page = (W.PAGE_DIR / '099-question-typing.js').read_text(encoding='utf-8')
    with mock.patch.object(Q, 'DRIVER', d.replace('(async', page + '(async', 1)):
        return Q.run(tmp, steps)


def test_typing(tmp: Path) -> None:
    out = run(tmp, """
      live(ASK); say(look()); focus(); say(look()); blur(); say(look());
      type('hi'); say(look(), sent.length); blur(); say(look());
      ta.value = ''; focus(); tap({qshow: 'u1'}); render(); say(look()); type('more'); say(look()); ta.value = ''; blur(); say(look());
      QN.min.add(questionKey('c1', 'u1')); render(); focus(); blur(); say(look());
      QN.min.clear(); render(); coarse = false; focus(); say(look()); type('x'); say(look());""")
    if out is None:
        return
    eq(out[0:3], [['card'], ['min'], ['card']], 'focus shrinks it to its line; leaving the box empty opens it')
    eq(out[3:5], [['min', 0], ['min']], 'typing shrinks it, sends nothing, and it stays shrunk while the box holds words')
    eq(out[5:7], [['card'], ['card']], 'a tap on the line opens it, and typing on does not shrink it again')
    eq(out[7], ['card'], 'the box left empty')
    eq(out[8], ['min'], 'one minimized by hand stays minimized')
    eq(out[9:], [['card'], ['min']], 'on a desktop focus alone shrinks nothing; typing does')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_typing)]))
