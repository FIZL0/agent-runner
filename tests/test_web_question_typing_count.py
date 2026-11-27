"""F192c1: with several questions, the minimized line (shrunk by typing or by scrolling) shows the count, e.g. 1 of 3.

    python3 tests/test_web_question_typing_count.py
"""
from __future__ import annotations

from pathlib import Path
from unittest import mock

from _check import eq, report
from _web import in_tmp

import test_web_question as Q
import test_web_question_row as R
import test_web_question_typing as T
from agent_runner import web as W  # noqa: E402


def run(tmp: Path, steps: str) -> list | None:
    d = Q.DRIVER.replace('addEventListener: (k, f) => { clicks.push(f) }', "addEventListener: (k, f) => { if (k === 'click') clicks.push(f); else (on[k] = on[k] || []).push(f) }")
    d = d.replace('PAGE', T.MORE + 'PAGE')
    page = (W.PAGE_DIR / '099-question-typing.js').read_text(encoding='utf-8')
    with mock.patch.object(Q, 'DRIVER', d.replace('(async', page + '(async', 1)):
        return R.run(tmp, steps)


def test_count(tmp: Path) -> None:
    out = run(tmp, """
      lives([A, B, C]); say(look(), count());
      focus(); type('hi'); say(look(), count()); ta.value = ''; blur(); say(look(), count());
      QN.auto.add(questionKey('c1', 'u7')); render(); say(look(), count()); QN.auto.clear(); render();
      lives([A]); focus(); type('x'); say(look(), count());""")
    if out is None:
        return
    eq(out[0], ['card', '1 of 3'], 'the row, counted')
    eq(out[1], ['min', '1 of 3'], 'shrunk while typing: the line shows the count')
    eq(out[2], ['card', '1 of 3'], 'open again: the row counts')
    eq(out[3], ['min', '1 of 3'], 'shrunk by scrolling: the line shows the count')
    eq(out[4], ['min', ''], 'one question: the line has no count')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_count)]))
