"""F192b1: a chat's answer may end on several DECIDE lines; /live says them all as `asks`.

    python3 tests/test_chat_question_several.py
"""
from __future__ import annotations

from pathlib import Path
from unittest import mock

from _check import check, eq, report  # noqa: F401 (sets the suite's own environment first)
from _ui_model import fake_run, in_tmp
from agent_runner import chat_question as Q

AT = '2026-11-24T10:00:00.000Z'
TWO = 'Two things.\n\nDECIDE: Which look? [Full (recommended) / Small]\n\nDECIDE: Which size? [Big / Tiny]\nDECIDE: Ship it now?'


def say(text: str, uuid: str = 'u1') -> dict:
    return {'type': 'assistant', 'uuid': uuid, 'timestamp': AT,
            'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': text}]}}


def test_parse(tmp: Path) -> None:
    fake_run(tmp)
    eq(Q.decide_questions(TWO), ['Which look? [Full (recommended) / Small]', 'Which size? [Big / Tiny]', 'Ship it now?'],
       'the trailing run, blank lines between allowed')
    eq(Q.decide_questions('DECIDE: Old one? [A / B]\nThe status says so.\nDECIDE: New? [Yes / No]'), ['New? [Yes / No]'],
       'a DECIDE quoted before other words is none')
    eq(Q.decide_questions('It says DECIDE: x\nDone.'), [], 'no DECIDE line at the end: none')


def test_ids(tmp: Path) -> None:
    fake_run(tmp)
    a = Q.asks([say(TWO)])
    eq([x['id'] for x in a], ['u1', 'u1-2', 'u1-3'], 'the first keeps the uuid, each other one its place')
    eq([x['question'] for x in a], ['Which look?', 'Which size?', 'Ship it now?'], 'each question')
    eq(a[2]['options'], [], 'a question with no options is one too')
    one = 'Said.\n\nDECIDE: Which look? [Small / Full (recommended)]'
    eq(Q.asks([say(one)]), [Q.ask_of(one, 'u1')], 'one DECIDE line: as now')
    eq(Q.ask([say(one)]), Q.ask_of(one, 'u1'), 'and ask is that one')
    eq(Q.asks_of(TWO)[0]['id'], Q.ask_of('DECIDE: Which look? [Full (recommended) / Small]')['id'],
       'with no uuid the first has the id ask_of gives')
    eq(len({x['id'] for x in Q.asks_of(TWO)}), 3, 'and each other its own')


def test_joined(tmp: Path) -> None:
    fake_run(tmp)
    a = Q.asks([say(TWO)])
    with mock.patch.object(Q, 'needs', return_value={'u1': '', 'u1-2': 'F7'}):
        j = Q.joined(a, 's')
    eq([(x['id'], x['need']) for x in j['asks']], [('u1-2', 'F7'), ('u1-3', '')], 'an answered one is left out; each its item')
    eq((j['ask']['id'], j['ask']['need']), ('u1-2', 'F7'), 'ask is the first still open with options')
    eq(j['answered'], ['u1'], 'answered')
    with mock.patch.object(Q, 'needs', return_value={}):
        j = Q.joined(a[:1], 's')
    eq(j['ask'], a[0], 'one question, not filed: ask as before')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(t) for t in (test_parse, test_ids, test_joined)]))
