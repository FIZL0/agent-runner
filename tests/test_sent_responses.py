#!/usr/bin/env python3
"""F425a: the sent responses: what is kept of a Needs you answer that opened no chat, and the chat started about one.

    python3 tests/test_sent_responses.py        (a temp repo, no agent, no network)

The fake run and the helpers are in tests/_ui_model.py.
"""
from __future__ import annotations
import json
from pathlib import Path
from unittest import mock
from _check import check, eq, report
from agent_runner import control_settled, pitch, sent_responses as R  # noqa: E402
from agent_runner import ui_model as U  # noqa: E402
from _ui_model import in_tmp, TODO, NOW, fake_run, ran_by  # noqa: E402

PLAN = TODO.replace('- [ ] **B2** Fix the merge retry | files: b.py | after: F1',
                    '- [~] **B2** Fix the merge retry | files: b.py BLOCKED: CONFIRM: look at it').replace(
    '- [ ] **F1** Board page for the run | files: a.py, tests/test_a.py',
    '- [~] **F1** Board page for the run | files: a.py BLOCKED: BLOCKED: log in to the store')


def plan(tmp: Path) -> Path:
    repo = fake_run(tmp)
    (repo / 'plan' / 'TODO.md').write_text(PLAN, encoding='utf-8')
    return repo


def sends(out: list, ok: bool = True):
    return mock.patch.object(U, 'SEND', [lambda t: (out.append(t), {'ok': ok, 'code': 0 if ok else 1, 'out': 'no room', 'argv': []})[1]])


def said() -> list:
    return [(r['item'], r['answer'], r['note']) for r in R.recent()]


def test_answers(tmp: Path) -> None:
    """Each kind of answer leaves one record, and starts no session."""
    plan(tmp)
    ran, sent = [], []
    with ran_by(ran), sends(sent):
        eq(U.act('answer', tid='B2', text='Yes', button=True, note=' on  wifi ')['ok'], True, 'a button')
        eq(U.act('run_control', key='need_answer1', tid='F1', text='Done')['ok'], True, 'an answer control')
        eq(U.act('answer', tid='D3', text='the lazy one')['ok'], True, 'words typed for a DECIDE')
        eq(U.act('answer', tid='F4', text='Option A', button=True)['ok'], True, "a concept's pick")
        eq(U.act('answer', tid='B2', text='no', button=True)['ok'], True, 'a No')
    eq(said(), [('B2', 'no', ''), ('F4', 'Option A', ''), ('D3', 'the lazy one', ''), ('F1', 'Done', ''),
                ('B2', 'Yes', 'on wifi')], 'one record each, newest first')
    eq((sent, [a for a in ran if a[0] == 'control']), ([], []), 'no session, no chat')
    eq(ran[0], ['plan', 'confirm', 'B2', 'Yes: on wifi'], "the note still goes into the task's")
    with ran_by([]):
        snap = U.snapshot(up=False, now=NOW, links={})
    eq([r['item'] for r in snap['responses']], [x[0] for x in said()], 'the snapshot carries them')
    need = {n['id']: n for n in snap['needs']}
    d3 = next(r for r in snap['responses'] if r['item'] == 'D3')
    eq((d3['title'], d3['question'], d3['ask']), (need['D3']['title'], need['D3']['detail']['summary'], need['D3']['ask']),
       'its title and the question as its card shows them')
    check(d3['question'] and d3['at'] > 0, 'a question and a time', d3)


def test_sheet(tmp: Path) -> None:
    """A pick sheet's reply is kept in words."""
    repo = plan(tmp)
    f = repo / '.runner' / 'sheets' / 'D3.json'
    f.parent.mkdir(exist_ok=True)
    f.write_text(json.dumps({'title': 'T', 'summary': 's', 'groups': [{'heading': 'h', 'questions': [
        {'id': 'port', 'q': 'Which port?', 'answers': ['80', '8080'], 'recommended': 0, 'why': 'w'}]}]}), encoding='utf-8')
    ran = []
    with ran_by(ran), mock.patch('agent_runner.brief.has_sheet', lambda tid: tid == 'D3'):
        U.act('answer', tid='D3', text='go', button=True)
        U.act('answer', tid='D3', text='D3 picks: port=b', note='after Friday')
    eq([a[0] for a in ran], ['sheet', 'sheet'], "the sheet's command")
    eq(said(), [('D3', 'port (Which port?): 8080', 'after Friday'), ('D3', 'port (Which port?): 80 (recommended)', '')], 'spelled out')


def test_pitch(tmp: Path) -> None:
    """A pitch's answers: kept, but not an Approve whose note went to a chat."""
    plan(tmp)
    row = ('PITCH', 'pitch1', '', 'Approve 1 change to push: Board', '', 'Board', False, '2026-11-24 10:00')
    left: list = []
    with mock.patch.object(pitch, 'rows', lambda c=None: [row]), mock.patch.object(pitch, 'changes_of', lambda *a, **k: left):
        sent = []
        with ran_by([]), sends(sent):
            U.answer('pitch1', 'Approve', True, 'and tell the docs')
            eq((len(sent), said()), (1, []), 'its words went to a chat: no record')
            U.answer('pitch1', 'Approve', True)
            eq(said(), [('pitch1', 'Approve', '')], 'without words: kept')
            U.pitch_no('pitch1', 'reopen', confirm=True, why='too soon')
            eq(said()[0], ('pitch1', 'Not this: reopen', 'too soon'), 'a No')
            left.append({'id': 'F1', 'title': 'Board', 'state': 'waiting'})
            U.pitch_no('pitch1', 'drop', 'F1', confirm=True)
            eq(len(said()), 2, 'a No to a part of it settles nothing yet')
        with ran_by([]), sends(sent, ok=False):
            U.answer('pitch1', 'Approve', True, 'lost words')
        eq(said()[0], ('pitch1', 'Approve', 'lost words'), 'words that reached no chat are kept')


def test_give(tmp: Path) -> None:
    """Done with inputs: the values, and of a secret its name only."""
    repo = plan(tmp)
    asks = repo / '.runner' / 'asks'
    asks.mkdir(exist_ok=True)
    (asks / 'D3.json').write_text(json.dumps({'summary': 'Give the token', 'inputs': [
        {'key': 'name', 'label': 'Name'}, {'key': 'tok', 'label': 'Token', 'kind': 'secret', 'env': 'MY_TOKEN'}]}), encoding='utf-8')
    vals = {'name': 'shop', 'tok': 's3cr3t'}
    with mock.patch.object(U, 'RUN', [lambda argv: (1, 'no')]):
        U.need_give('D3', vals, secure=True)
    U.need_give('D3', vals)
    eq(said(), [], 'a failed or refused one leaves none')
    ran: list = []
    with ran_by(ran):
        eq(U.need_give('D3', vals, secure=True)['ok'], True, 'sent')
    eq(said(), [('D3', 'Name: shop; Token: MY_TOKEN (a secret, not shown)', '')], "the secret's name only")
    eq([a[0] for a in ran], ['plan'], 'no session')
    for f in R.folder().iterdir():
        check('s3cr3t' not in f.read_text(encoding='utf-8'), f'not in {f.name}')


def test_not_kept(tmp: Path) -> None:
    """A failed answer and one whose words went to a chat leave none; a record that fails leaves the answer as it is."""
    plan(tmp)
    sent: list = []
    with mock.patch.object(U, 'RUN', [lambda argv: (1, 'no')]):
        check(not U.answer('B2', 'Yes', True)['ok'], 'failed')
    with ran_by([]), sends(sent):
        U.answer('B2', 'looks odd')
        U.run_control('need_yes', tid='B2', text='Stale')
        U.answer('ZZ9', 'Yes', True)
    eq((len(sent), said()), (1, []), 'no record')
    with ran_by([]), mock.patch.object(R, '_save', side_effect=OSError('disk full')):
        r = U.answer('B2', 'Yes', True)
    eq((r['ok'], r['gone'], said()), (True, 'B2', []), 'the answer is as ever')
    with ran_by([]), mock.patch.object(U, 'row_of', side_effect=RuntimeError('no plan')):
        eq(U.answer('B2', 'Yes', True)['ok'], True, 'nor does a row that does not read')
    eq(said(), [('B2', 'Yes', '')], 'it is kept without its question')
    (R.folder() / '1-1.json').write_text('{', encoding='utf-8')
    for n in range(R.KEEP + 3):
        R.keep('F1', 't', 'q', 'q', str(n))
    eq([r['answer'] for r in R.recent()], [str(n) for n in range(R.KEEP + 2, 2, -1)], 'capped, newest first')
    eq(len(list(R.folder().iterdir())), R.KEEP, 'the old ones and the broken one are gone')


def test_chat(tmp: Path) -> None:
    """A session starts only with words; its first message names the item, and the response goes."""
    plan(tmp)
    with ran_by([]):
        U.answer('B2', 'Yes', True, 'on wifi')
        U.answer('D3', 'the lazy one')
    rid = {r['item']: r['id'] for r in R.recent()}
    ran: list = []
    with ran_by(ran, 'control 7 starts'):
        for bad in ('', '  ', None):
            check(not U.act('response_chat', rid=rid['B2'], text=bad)['ok'], 'no words: no session', bad)
        for odd in ('', '../../STATE', '1-1', None, 5):
            check(not U.act('response_chat', rid=odd, text='hi')['ok'], f'no such response: {odd!r}')
        eq((ran, len(R.recent())), ([], 2), 'nothing ran, both are kept')
        r = U.act('response_chat', rid=rid['B2'], text='what did the  check say?', wait=False)
        again = U.act('response_chat', rid=rid['B2'], text='twice')
    eq((r['ok'], r['name'], again['ok'], len(ran)), (True, 'c7', False, 1), 'one session')
    eq(ran[0][:4] + ran[0][5:], ['control', '--new', '--no-wait', '--ask', '--no-feed'], 'a new control session')
    msg = ran[0][4]
    m = control_settled.OPENED.match(msg)
    eq(m and (m[1] or m[2]), 'B2', 'control_settled knows the item')
    check(msg.startswith('About B2 (Fix the merge retry): '), 'it starts with the item', msg)
    for part in ('Look at it', '): Yes\n', 'My note with it: on wifi', 'Its state now: it needs me again', 'what did the  check say?',
                 'Settle or change nothing unless my words'):
        check(part in msg, f'it says {part!r}', msg)
    eq([x['item'] for x in R.recent()], ['D3'], 'its response went')
    with mock.patch.object(U, 'RUN', [lambda argv: (1, 'no room')]):
        check(not U.response_chat(rid['D3'], 'hm')['ok'], 'a chat that does not start')
    eq([x['id'] for x in R.recent()], [rid['D3']], 'leaves the response')


def test_state(tmp: Path) -> None:
    """The item's state now."""
    repo = plan(tmp)
    todo = repo / 'plan' / 'TODO.md'
    todo.write_text(TODO, encoding='utf-8')
    check(U.item_state('D3').startswith('it needs me again: '), 'asked again', U.item_state('D3'))
    check(U.item_state('T7').startswith('open in the plan ('), 'reopened', U.item_state('T7'))
    todo.write_text(TODO.replace('- [ ] **B2**', '- [x] **B2**'), encoding='utf-8')
    eq(U.item_state('B2'), 'landed', 'ticked')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(f) for f in (test_answers, test_sheet, test_pitch, test_give, test_not_kept, test_chat, test_state)]))
