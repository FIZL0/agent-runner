"""F192a: the question a chat's last answer ends on, as /live says it for the question card.

    python3 tests/test_chat_question.py
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

from _check import check, eq, report  # noqa: F401 (sets the suite's own environment first)
from _ui_model import fake_run, in_tmp
from agent_runner import chat_question as Q, session_now as N, web as W

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


ABOUT = 'About your question “Which look?” (not my answer): '


def queued(text: str) -> dict:
    return {'type': 'attachment', 'uuid': 'q', 'timestamp': AT,
            'attachment': {'type': 'queued_command', 'prompt': text, 'commandMode': 'prompt'}}


def test_about(tmp: Path) -> None:
    """F430: messages about the question, and the replies to them, leave it open."""
    fake_run(tmp)
    q, why = say(ASK), you(ABOUT + 'why?')
    stop = you('[Request interrupted by user]')
    for what, rows in (
            ('the message', [q, why]),
            ('the reply under way', [q, why, tool()]),
            ('the reply', [q, why, tool(), say('Because.', 'u3')]),
            ('more of them', [q, why, say('Because.', 'u3'), you(ABOUT + 'and?'), say('So.', 'u4')]),
            ('typed in as a paste', [q, you(f'\n\n<pasted_content id="1a2b">\n{ABOUT}why?\n</pasted_content id="1a2b">\n')]),
            ('typed during the reply', [q, why, tool(), queued(ABOUT + 'and?'), say('So.', 'u4')]),
            ('a reply that was stopped', [q, why, tool(), stop]),
            ('a slash command', [q, why, say('Because.', 'u3'), you('<command-name>/compact</command-name>')])):
        eq((Q.ask(rows) or {}).get('id'), 'u1', f'still asked after {what}')
    for what, rows in (
            ('an answer in other words', [q, why, say('Because.', 'u3'), you('blue')]),
            ('one typed during the reply', [q, why, tool(), queued('blue'), say('Blue then.', 'u3')]),
            ('an answer, then words about it', [q, you('Full'), say('Done.', 'u3'), why, say('Because.', 'u4')]),
            ('a paste beside other words', [q, you(f'blue\n<pasted_content id="1">\n{ABOUT}why?\n</pasted_content id="1">\n')]),
            ('the words later in a message', [q, you('I wrote: ' + ABOUT + 'why?')]),
            ('only the first half of them', [q, you('About your question “Which look?”: Full')]),
            ('a question with no options', [q, why, say('DECIDE: What should it be called?', 'u3')])):
        eq(Q.ask(rows), None, f'no longer asked after {what}')
    later = say('DECIDE: Which size? [Big / Little]', 'u5')
    eq(Q.ask([q, why, later])['id'], 'u5', 'another question takes its place')
    eq(Q.ask([q, why, later, you(ABOUT + 'and?'), say('So.', 'u6')])['id'], 'u5', 'and stays in it')


def test_about_live(tmp: Path) -> None:
    """F430: /live says it as the messages go in; a read of the file anew (a reload, another device) says the same."""
    fake_run(tmp)
    f = tmp / 't.jsonl'

    def add(*rows: dict) -> None:
        with open(f, 'a', encoding='utf-8') as o:
            o.writelines(json.dumps(d) + '\n' for d in rows)

    def op(what: str, text: str = '') -> dict:
        return {'type': 'queue-operation', 'operation': what, 'timestamp': AT, **({'content': text} if text else {})}

    def asked() -> tuple:
        N._TASKS.clear()
        d = N.live('c2')
        return (d['ask'] or {}).get('id'), d['queued']
    with mock.patch.object(N, 'transcript', lambda n, r: str(f)):
        with mock.patch.object(N, 'record', lambda n: {'status': 'busy'}):
            add(say(ASK), you(ABOUT + 'why?'), tool(), op('enqueue', ABOUT + 'and?'))
            eq(asked(), ('u1', 1), 'words about it that are queued leave it open')
            add(op('enqueue', 'blue'))
            eq(asked(), (None, 2), 'an answer queued after them does not')
            add(op('remove', 'blue'), op('dequeue'))
            eq(asked(), ('u1', 0), 'the queue is empty: still asked')
        with mock.patch.object(N, 'record', lambda n: {'status': 'busy', 'harness': True, 'queued': 1}):
            eq(asked(), (None, 1), 'the harness loop does not say what is queued: taken as an answer')
        with mock.patch.object(N, 'record', lambda n: {'status': 'idle'}):
            add(say('Because.', 'u3'))
            eq(asked(), ('u1', 0), 'the reply leaves it open')
            add(you('blue'), say('Blue then.', 'u4'))
            eq(asked(), (None, 0), 'answered in the terminal')


def test_about_words(tmp: Path) -> None:
    fake_run(tmp)
    js = (W.PAGE_DIR / '024-questionchat.logic.js').read_text(encoding='utf-8')
    check(f"QUESTION_ABOUT='{Q.ABOUT}', QUESTION_NOT='{Q.NOT}'" in js, 'the page words it as /live reads it')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_options), in_tmp(test_none), in_tmp(test_subagent), in_tmp(test_live),
                             in_tmp(test_about), in_tmp(test_about_live), in_tmp(test_about_words)]))
