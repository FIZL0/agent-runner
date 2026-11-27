"""F192b1b: an answer that ends on several questions files each under Needs you, an item each.

    python3 tests/test_chat_question_filing_several.py
"""
from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from unittest import mock

from _check import check, eq, report  # noqa: F401 (sets the suite's own environment first)
from _ui_model import in_tmp
from test_chat_question import say
from test_chat_question_need import World

from agent_runner import chat_question as CQ, control as K, control_settled as Z, plan as P, state as S

TWO = 'Two things.\n\nDECIDE: Which look? [Small / Full (recommended)]\n\nDECIDE: Anything else to add to the page?'


def world(f):
    def go(tmp: Path) -> None:
        with ExitStack() as env:
            w = World(tmp, env)
            w.rows[:] = [say(TWO)]
            f(w)
    go.__name__ = f.__name__
    return in_tmp(go)


def file(w: World) -> str:
    return K.file_control_ask(6, 'sid-6', P.decide_question(TWO), '')


def test_each_filed(w: World) -> None:
    ids = file(w).split(', ')
    eq(len(ids), 2, 'two questions, two items')
    eq(ids[0] in w.waits() and ids[1] in w.waits(), True, 'both wait under Needs you')
    text = S.C.todo.read_text(encoding='utf-8')
    check('DECIDE: Which look?' in text and 'DECIDE: Anything else to add to the page?' in text, 'each its own question', text)
    eq(set(CQ.needs('sid-6')), {'u1', 'u1#2'}, 'each knows its question')
    eq(file(w).split(', '), ids, 'filed again: the same items, none new')
    eq(len(w.waits() - {'D3'}), 2, 'still two')


def test_partial_retry(w: World) -> None:
    ids = file(w).split(', ')
    f = Z.filed_file(S.C, 'sid-6')
    d = Z.read_json(f, {})
    Z.save(f, {**d, 'asked': {ids[0]: d['asked'][ids[0]]}})  # as if only the first was filed
    again = file(w).split(', ')
    eq(again[0], ids[0], 'the first is not filed twice')
    eq(len(again), 2, 'the second is filed')
    eq(sum(1 for a in P.asks(S.C.todo) if a[0] == 'DECIDE' and 'Which look?' in a[3]), 1, 'one item for the first')


def test_not_closed_until_filed(w: World) -> None:
    with mock.patch.object(K, 'commit_plan', lambda *a, **k: False):
        eq(file(w), '', 'not committed: nothing filed, so the session is not closed')
    eq(w.waits() - {'D3'}, set(), 'no item left behind')
    eq(len(file(w).split(', ')), 2, 'the next look files both')


if __name__ == '__main__':
    raise SystemExit(report([world(f) for f in (test_each_filed, test_partial_retry, test_not_closed_until_filed)]))
