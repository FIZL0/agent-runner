"""F192a: the question a chat's last answer ends on, as /live says it for the question card.

    python3 tests/test_chat_question.py
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

from _check import eq, report  # noqa: F401 (sets the suite's own environment first)
from _ui_model import fake_run, in_tmp
from agent_runner import chat_question as Q, session_now as N

ASK = 'Two ways to draw it.\n\nDECIDE: Which look? [Small / Full (recommended) / No change]'
AT = '2026-11-24T10:00:00.000Z'
SHOWN = [{'name': 'Full', 'rec': True}, {'name': 'Small', 'rec': False}, {'name': 'No change', 'rec': False}]


def you(text: str) -> dict:
    return {'type': 'user', 'timestamp': AT, 'message': {'role': 'user', 'content': text}}


def say(text: str, uuid: str = 'u1', **more) -> dict:
    return {'type': 'assistant', 'uuid': uuid, 'timestamp': AT,
            'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': text}]}, **more}


def tool() -> dict:
    return {'type': 'assistant', 'uuid': 'u2', 'timestamp': AT, 'message': {'role': 'assistant', 'content': [
        {'type': 'tool_use', 'id': 't1', 'name': 'Bash', 'input': {'command': 'ls'}}]}}


def test_options(tmp: Path) -> None:
    fake_run(tmp)
    eq(Q.ask([you('hi'), say(ASK)]), {'id': 'u1', 'question': 'Which look?', 'options': SHOWN},
       'the question, and its options with the recommended one first and marked')
    eq([o['name'] for o in Q.ask([say('**DECIDE: Go on? [Yes / No]**')])['options']], ['Yes', 'No'], 'none recommended: as written')
    eq(Q.ask([say('DECIDE: Which? [A / B] https://claude.ai/x')]),
       {'id': 'u1', 'question': 'Which?', 'options': [{'name': 'A', 'rec': False}, {'name': 'B', 'rec': False}]},
       'a link after the bracket is not in the question')
    think = {'type': 'assistant', 'uuid': 'u4', 'message': {'content': [{'type': 'thinking', 'thinking': 'hm'}]}}
    watch = {'type': 'assistant', 'uuid': 'u5', 'message': {'content': [
        {'type': 'tool_use', 'id': 't2', 'name': 'Monitor', 'input': {'command': './run since --follow --needs-you'}}]}}
    eq(Q.ask([say(ASK), think, watch])['id'], 'u1', 'thinking, or the standing watch set again, after it: the same question')
    a, b = Q.ask_of(ASK), Q.ask_of(ASK.replace('Which look?', 'Which size?'))
    eq((a['id'] == Q.ask_of(ASK)['id'], a['id'] == b['id']), (True, False), 'with no uuid the id is the question\'s own')


def test_none(tmp: Path) -> None:
    fake_run(tmp)
    for why, rows in (
            ('nothing said', []),
            ('no DECIDE line', [say('Which look? [Small / Full]')]),
            ('the DECIDE is not the last line', [say('DECIDE: Which? [A / B]\nI wait.')]),
            ('no options', [say('DECIDE: What should it be called?')]),
            ('one option', [say('DECIDE: Go? [Yes]')]),
            ('two recommended', [say('DECIDE: Which? [A (recommended) / B (recommended)]')]),
            ('a bracket after a link', [say('DECIDE: Which? https://claude.ai/x [A / B]')]),
            ('the person has spoken since', [say(ASK), you('Full')]),
            ('the turn goes on', [say(ASK), tool()]),
            ('it goes on in the same entry', [{**say(ASK), 'message': {'content': say(ASK)['message']['content']
                                                                      + tool()['message']['content']}}]),
            ('a later answer ends on something else', [say(ASK), you('Full'), say('Done.', 'u3')])):
        eq(Q.ask(rows), None, why)


def test_subagent(tmp: Path) -> None:
    fake_run(tmp)
    eq(Q.ask([say(ASK), say('Looked.', 'side', isSidechain=True)])['id'], 'u1', "a subagent's words are not the chat's")


def test_live(tmp: Path) -> None:
    """/live carries it, read again as the transcript grows."""
    fake_run(tmp)
    f = tmp / 't.jsonl'

    def add(d: dict) -> None:
        with open(f, 'a', encoding='utf-8') as o:
            o.write(json.dumps(d) + '\n')
    add(say(ASK))
    with mock.patch.object(N, 'record', lambda n: {'status': 'idle'}), \
            mock.patch.object(N, 'transcript', lambda n, r: str(f)):
        eq([N.live('c2')['ask']['options'] for _ in range(2)], [SHOWN, SHOWN], 'on every read')
    with mock.patch.object(N, 'record', lambda n: {'status': 'busy'}), \
            mock.patch.object(N, 'transcript', lambda n, r: str(f)):
        eq(N.live('c2')['ask']['options'], SHOWN, 'while it works too')
        add({'type': 'queue-operation', 'operation': 'enqueue', 'timestamp': AT, 'content': 'Full'})
        eq((N.live('c2')['ask'], N.live('c2')['queued']), (None, 1), 'an answer that is queued')
        add({'type': 'queue-operation', 'operation': 'dequeue', 'timestamp': AT})
        add(you('Full'))
        eq(N.live('c2')['ask'], None, 'answered')
    g = tmp / 's.jsonl'
    g.write_text(json.dumps(say(ASK)) + '\n', encoding='utf-8')
    with mock.patch.object(N, 'record', lambda n: {'status': 'idle'}), \
            mock.patch.object(N, 'transcript', lambda n, r: str(g)):
        eq(N.live('s2')['ask'], None, 'a slot is no chat')
    with mock.patch.object(N, 'record', lambda n: {}):
        eq(N.live('c9')['ask'], None, 'no such session')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_options), in_tmp(test_none), in_tmp(test_subagent), in_tmp(test_live)]))
