"""B809b: a control session's question is filed with what explains it.

    python3 tests/test_control_ask_context.py
"""
from __future__ import annotations

import json
import os
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

from _check import check, eq, report  # sets the suite's own environment first
from _ui_model import fake_run, in_tmp
from test_chat_question import say, you

from agent_runner import asks, control as K, control_ask as A, need_detail as D, plan as P, state as S

SID = '69186700-ad60-44ae-b5be-1a8bfb24f2dc'
PNG = b'\x89PNG\r\n\x1a\n' + b'0' * 20
Q = 'Build On Cellular like this? [Build it (recommended) / No]'
TEXT = 'The concept is ready: **[On Cellular](https://claude.ai/artifact/abc)**.\n\n- **Install:** asks first.\n- It closes.'
MSG = f'{TEXT}\n\nDECIDE: {Q}'


class World:
    def __init__(self, tmp: Path, env: ExitStack):
        self.tmp, self.root, self.rows = tmp, fake_run(tmp), []
        A.FILLED.clear()
        env.enter_context(mock.patch.object(K, 'entries', lambda sid, skip_bad=False: iter(self.rows)))
        env.enter_context(mock.patch.object(K, 'transcript', lambda sid: 'there' if self.rows else None))

    def file(self, *rows: dict) -> str:
        self.rows = list(rows)
        return K.file_control_ask(6, SID, Q, '')

    def detail(self, tid: str) -> dict:
        a = next(x for x in P.asks(S.C.todo) if x[1] == tid)
        return D.detail(a[0], tid, a[3], a[5], D.task_lines()[tid])

    def picture(self, *at: str, data: bytes = PNG) -> Path:
        f = self.tmp.joinpath(*at)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data)
        return f


def world(f):
    def go(tmp: Path) -> None:
        with ExitStack() as env:
            f(World(tmp, env))
    go.__name__ = f.__name__
    return in_tmp(go)


def test_text_and_clearing(w: World) -> None:
    title = {'type': 'custom-title', 'customTitle': 'proj · 6 · Cellular installs'}
    tid = w.file(title, you('make it'), say('Looking.', 'u0'), say(MSG))
    d = w.detail(tid)
    eq(d['text'], TEXT, 'the text above the DECIDE line, its lines and its link')
    eq((d['session'], d['project']), ('Cellular installs', 'proj'), "the session's name and project")
    eq((d['question'], d['shots']), ('Build On Cellular like this?', []), 'the question as before')
    eq([A.session_name(6, f'proj · {x}') for x in ('6', 'control 6', 'R43 · site')], ['', '', 'R43 · site'], 'no name of its own')
    P.unblock(tid, 'yes', todo=S.C.todo)
    check(not asks.ask_file(tid, S.C).exists(), 'answered: gone')
    d = D.detail('DECIDE', 'D3', 'which layout', 'Write', '')
    eq((d['text'], d['session'], d['project']), ('', '', ''), 'an item of no chat has none')


def test_bare(w: World) -> None:
    tid = w.file(say(TEXT, 'u0'), you('so?'), say(f'DECIDE: {Q}'))
    eq(w.detail(tid)['text'], TEXT, 'only the DECIDE line: the message shown before it')
    rows = [say('DECIDE: Other? [A / B]'), say('API Error', isApiErrorMessage=True), say('sub', isSidechain=True)]
    eq(A.explained([say(TEXT, 'u0'), *rows, say(f'DECIDE: {Q}')], Q)[0], TEXT, 'past bare questions and what is no message')
    eq(A.explained([say(f'DECIDE: {Q}')], Q), ('', ''), 'nothing before it')
    eq(A.explained([say(TEXT)], Q), ('', ''), 'not its question')
    eq(len(A.explained([say('x ' * 20000 + f'\n\nDECIDE: {Q}')], Q)[0]) > A.TEXT_MAX, True, 'a very long one')
    tid = w.file(say('ab ' * 20000 + f'\n\nDECIDE: {Q}', 'u9'))
    check(w.detail(tid)['text'].endswith(' …'), 'is cut, and still read')


def test_shots(w: World) -> None:
    pad = ('tmp', 'claude-1000', '-proj', SID, 'scratchpad')
    w.picture('proj', 'docs', 'one.png')
    two = w.picture(*pad, 'two.png')
    out = w.picture('out', 'three.png')
    other = w.picture('tmp', 'claude-1000', '-proj', 'f' * 36, 'scratchpad', 'four.png')
    beside = w.picture('tmp', 'claude-1000', '-proj', SID, 'tasks', 'five.png')
    up = w.picture(*pad, 'x', '..', '..', 'six.png') if os.name == 'posix' else beside
    w.picture('proj', 'text.png', data=b'secret')
    w.picture('proj', 'page.html')
    w.picture('proj', 'sp ace.jpg', data=b'\xff\xd8\xff' + b'0' * 20)
    text = (f'See ![the page](docs/one.png), `{two}`, {out}, {other}, {beside}, {up}, text.png, page.html, ../out/three.png, '
            f'[a](<sp ace.jpg>) and https://example.com/docs/one.png. Again docs/one.png')
    if os.name == 'posix':
        (w.root / 'link.png').symlink_to(out)
        text += ' link.png'
    tid = w.file(say(f'{text}\n\nDECIDE: {Q}'))
    shots = w.detail(tid)['shots']
    eq([s['caption'] for s in shots], ['the page', 'two', 'a'],
       'in the project or the scratchpad; one elsewhere, by .. or a link, or no picture is refused')
    two.unlink()
    check(Path(shots[1]['path']).read_bytes() == PNG, 'a copy')
    P.drop(tid, 'no', todo=S.C.todo)
    check(not Path(shots[0]['path']).exists(), 'cleared with the item')


def test_already_waiting(w: World) -> None:
    tid = w.file()
    eq(w.detail(tid)['text'], '', 'filed with no text')
    eq(w.detail(tid)['project'], 'proj', 'but its project')
    asks.clear_ask(tid, S.C.todo)
    eq(A.fill(), [], 'no transcript: nothing')
    w.rows = [{'type': 'custom-title', 'customTitle': 'proj · 6 · Cells'}, say(MSG), you('late'), say('More.', 'u5')]
    eq(A.fill(), [], 'looked through once a process')
    A.FILLED.clear()
    eq((A.fill(), w.detail(tid)['text'], w.detail(tid)['session']), ([tid], TEXT, 'Cells'), 'filled by the session id')
    f = asks.ask_file(tid, S.C)
    f.write_text(json.dumps({'text': 'own'}), encoding='utf-8')
    A.FILLED.clear()
    eq((A.fill(), w.detail(tid)['text']), ([], 'own'), 'one that has a text keeps it')
    f.write_text(json.dumps({'where': 'Phone'}), encoding='utf-8')
    A.FILLED.clear()
    eq((A.fill(), w.detail(tid)['where']), ([tid], 'Phone'), 'its other fields stay')
    P.unblock(tid, 'x — your answer (DECIDE): no', todo=S.C.todo)
    P.block(tid, f'DECIDE: {Q}', todo=S.C.todo, after=[])
    A.FILLED.clear()
    eq(A.fill(), [], 'answered since: what asks now is not that message')


def test_by_filed_record(w: World) -> None:
    w.rows = [say(MSG)]
    tid = K.file_control_ask(6, SID, Q, 'https://claude.ai/code/session_01AbC')
    asks.clear_ask(tid, S.C.todo)
    A.FILLED.clear()
    K.close_controls(force=True)
    eq(w.detail(tid)['text'], TEXT, 'the run fills it in, the session known by its record')


if __name__ == '__main__':
    raise SystemExit(report([world(f) for f in (test_text_and_clearing, test_bare, test_shots, test_already_waiting,
                                                test_by_filed_record)]))
