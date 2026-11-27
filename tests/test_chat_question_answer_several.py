"""F192b1c: of several questions, an answer that names its question closes only that one; any other message closes all;
an item answered under Needs you closes only its own question.

    python3 tests/test_chat_question_answer_several.py
"""
from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path

from _check import check, eq, report  # noqa: F401 (sets the suite's own environment first)
from _ui_model import in_tmp
from test_chat_question import say, you
from test_chat_question_need import World

from agent_runner import chat_question as Q, session_now as N, ui_model as U

TWO = 'Two things.\n\nDECIDE: Which look? [Small / Full (recommended)]\n\nDECIDE: Which size? [Big / Little]'


def world(f):
    def go(tmp: Path) -> None:
        with ExitStack() as env:
            f(World(tmp, env))
    go.__name__ = f.__name__
    return in_tmp(go)


def ids() -> list[str]:
    N._TASKS.clear()
    return [a['id'] for a in N.live('c6')['asks']]


def test_words(w: World) -> None:
    eq(Q.answer_to(Q.answered_with('Which size?', 'Big')), 'Which size?', 'the answer names its question')
    eq((Q.answer_to('Big'), Q.answer_to(None)), (None, None), 'other words name none')


def test_named(w: World) -> None:
    w.rows[:] = []
    w.add(say(TWO, 'u7'))
    eq(ids(), ['u7', 'u7#2'], 'both open')
    w.add(you(Q.ABOUT + 'Which look?' + Q.NOT + 'what is Full?'), say('Full is wider.', 'u9'))
    eq(ids(), ['u7', 'u7#2'], 'a Marked question leaves both open')
    w.add(you(Q.answered_with('Which size? [Big / Little]', 'Big')), say('Noted: big.', 'u8'))
    eq(ids(), ['u7'], 'only the named one closes')
    eq(N.live('c6')['ask']['id'], 'u7', 'the other stays ask')
    w.add(you(Q.answered_with('Which look?', 'Full')))
    eq(ids(), [], 'both named: none open')


def test_other(w: World) -> None:
    w.rows[:] = []
    w.add(say(TWO, 'u7'))
    w.add(you(Q.answered_with('Something else?', 'x')))
    eq(ids(), [], 'a name of no open question closes all')
    w.rows[:] = []
    Path(w.path).write_text('', encoding='utf-8')
    w.add(say(TWO, 'u7'), you('both small'))
    eq(ids(), [], 'any other message closes all')


def test_need(w: World) -> None:
    from agent_runner import control_settled, plan as P, state as S
    w.rows[:] = []
    w.add(say(TWO, 'u7'))
    first = w.file(TWO.split('\n\nDECIDE: Which size')[0])
    eq(Q.need_of('c6', 'u7', 'sid-6'), first, 'the first found by its id')
    second = P.add('F', 'Control session 6 asked the person: "Which size?"', todo=S.C.todo, pri='normal')
    P.block(second, 'DECIDE: Which size? [Big / Little]', todo=S.C.todo, after=[])
    what = next(a[3] for a in P.asks(S.C.todo, all=True) if a[1] == second)
    control_settled.filed(S.C, [second], {'n': 6, 'sid': 'sid-6'})
    control_settled.filed_question(S.C, 'sid-6', second, 'u7#2', what)
    eq(Q.need_of('c6', 'u7#2', 'sid-6'), second, 'the second found by its id')
    r = U.question_answer('c6', 'u7#2', 'Big')
    eq(r['ok'], True, 'its option settles the second')
    eq(ids(), ['u7'], 'only that question closes')


if __name__ == '__main__':
    raise SystemExit(report([world(f) for f in (test_words, test_named, test_other, test_need)]))
