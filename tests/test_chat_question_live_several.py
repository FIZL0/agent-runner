"""F192b1a: /live says each question a chat's last answer ends on, in order, as 'asks'; 'ask' is the first still open.

    python3 tests/test_chat_question_live_several.py
"""
from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path

from _check import check, eq, report  # noqa: F401 (sets the suite's own environment first)
from _ui_model import in_tmp
from test_chat_question import ASK, say, you
from test_chat_question_need import World

from agent_runner import session_now as N

TWO = 'Two things.\n\nDECIDE: Which look? [Small / Full (recommended)]\n\nDECIDE: Which size? [Big / Little]'


def world(f):
    def go(tmp: Path) -> None:
        with ExitStack() as env:
            f(World(tmp, env))
    go.__name__ = f.__name__
    return in_tmp(go)


def test_one(w: World) -> None:
    live = N.live('c6')
    eq([a['id'] for a in live['asks']], ['u1'], 'one question: a list of one')
    eq(live['asks'][0], live['ask'], 'the same as ask')


def test_several(w: World) -> None:
    w.rows[:] = []
    w.add(say(TWO, 'u7'))
    live = N.live('c6')
    eq([(a['id'], a['question']) for a in live['asks']], [('u7', 'Which look?'), ('u7#2', 'Which size?')], 'both, in order')
    eq([o['name'] for o in live['asks'][1]['options']], ['Big', 'Little'], 'each with its options')
    eq(live['ask']['id'], 'u7', 'ask is the first')
    first = w.file(TWO.split('\n\nDECIDE: Which size')[0]).split(', ')[0]  # F192b1b: files both, the first first
    live = N.live('c6')
    eq(live['asks'][0].get('need'), first, 'a filed one says its item')
    from agent_runner import plan as P, state as S
    P.unblock(first, 'Full', todo=S.C.todo)
    N._TASKS.clear()
    live = N.live('c6')
    eq(([a['id'] for a in live['asks']], live['ask']['id']), (['u7#2'], 'u7#2'), 'answered under Needs you: the next is ask')
    w.add(you('both small'))
    live = N.live('c6')
    eq((live['asks'], live['ask']), ([], None), 'the person spoke: none')


def test_none(w: World) -> None:
    w.add(you('ok'))
    eq((N.live('c6')['asks'], N.live('c6')['ask']), ([], None), 'no question open')


if __name__ == '__main__':
    raise SystemExit(report([world(f) for f in (test_one, test_several, test_none)]))
