"""F192a3: a chat's question filed under Needs you and its question card are one question.

    python3 tests/test_chat_question_need.py
"""
from __future__ import annotations

import json
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

from _check import check, eq, git, report  # noqa: F401 (sets the suite's own environment first)
from _ui_model import chat, fake_run, in_tmp
from test_chat_question import ASK, say, you

import test_web_question as Q
from test_web_question_chat import run as chat_run
from agent_runner import control as K, control_settled as Z, plan as P, session_now as N, state as S, ui_model as U

LATER = 'DECIDE: Which size? [Big / Little]'


class World:
    """A fake run with chat c6, its transcript and its filed question."""

    def __init__(self, tmp: Path, env: ExitStack):
        fake_run(tmp)
        self.rows = [say(ASK)]
        self.path = chat(6, 'sid-6', self.rows)
        for name, get in (('record', lambda n: {'status': 'idle', 'sessionId': 'sid-6'}),
                          ('transcript', lambda n, r: self.path)):
            env.enter_context(mock.patch.object(N, name, get))
        env.enter_context(mock.patch.object(K, 'entries', lambda sid, skip_bad=False: iter(self.rows)))

    def add(self, *rows: dict) -> None:
        self.rows += rows
        with open(self.path, 'a', encoding='utf-8') as f:
            f.writelines(json.dumps(r) + '\n' for r in rows)

    def file(self, text: str = ASK) -> str:
        return K.file_control_ask(6, 'sid-6', P.decide_question(text), 'https://claude.ai/code/session_01AbC')

    def ask(self) -> dict:
        return N.live('c6')['ask']

    def waits(self) -> set[str]:
        return {a[1] for a in P.asks(S.C.todo) if a[0] == 'DECIDE'}


def world(f):
    def go(tmp: Path) -> None:
        with ExitStack() as env:
            f(World(tmp, env))
    go.__name__ = f.__name__
    return in_tmp(go)


def test_card_settles(w: World) -> None:
    check('need' not in w.ask(), 'not filed: a card as before')
    eq(U.question_answer('c6', 'u1', 'Full')['ok'], False, 'nor is there an item to settle')
    tid = w.file()
    eq((w.ask()['id'], w.ask().get('need'), N.live('c6')['answered']), ('u1', tid, []), 'filed: the card knows its item')
    r = U.act('question_answer', chat='c6', id='u1', text='Full')
    eq((r['ok'], r.get('gone')), (True, tid), 'an option settles it')
    check(f'- [ ] **{tid}**' in S.C.todo.read_text(encoding='utf-8'), 'the item is reopened, as by its answer button')
    check('Full' in ' '.join(P.section(S.C.todo, tid)), 'with the answer in its note')
    eq((tid in w.waits(), w.ask(), N.live('c6')['answered']), (False, None, ['u1']), 'both are closed')
    r = U.question_answer('c6', 'u1', 'Small')
    check(not r['ok'] and 'no longer needs you' in r['out'], 'answered already: refused', r)
    check('Small' not in S.C.todo.read_text(encoding='utf-8').split(f'**{tid}**')[1].split('your answer')[-1].split('): ')[-1],
          'and no second answer is noted')


def test_needs_you_closes(w: World) -> None:
    tid = w.file()
    eq(U.answer(tid, 'Small', button=True)['ok'], True, 'answered under Needs you')
    eq(w.ask(), None, 'the card goes')
    N._TASKS.clear()
    eq((w.ask(), N.live('c6')['answered']), (None, ['u1']), 'also after a restart: the files say it')
    eq(U.question_answer('c6', 'u1', 'Full')['ok'], False, 'an option sent late is refused')


def test_dropped_and_shelved(w: World) -> None:
    tid = w.file()
    P.shelve(tid, todo=S.C.todo)
    eq(w.ask()['need'], tid, 'shelved: still asked')
    P.drop(tid, 'not needed', todo=S.C.todo)
    eq(w.ask(), None, 'dropped: closed')


def test_only_its_own(w: World) -> None:
    first = w.file()
    w.add(you('tell me more'), say(LATER, 'u2'))
    check('need' not in w.ask(), 'a question asked after it is not filed yet')
    eq(U.question_answer('c6', 'u2', 'Big')['ok'], False, 'so its options settle nothing')
    second = w.file(LATER)
    eq((w.ask()['need'], len({first, second})), (second, 2), 'filed: an item of its own')
    eq(U.question_answer('c6', 'u2', 'Big')['ok'], True, 'its option settles it')
    check({first, 'D3'} <= w.waits() and second not in w.waits(), 'the chat\'s other item, and another\'s, still wait', w.waits())
    w.add(you('again'), say(ASK, 'u3'))
    check(w.ask() and 'need' not in w.ask(), 'the same words asked anew are a new question')
    P.unblock(first, 'yes', todo=S.C.todo)
    check(w.ask(), 'which an answer to the old one does not close')
    P.block(first, 'DECIDE: Which colour? [Red / Blue]', todo=S.C.todo, after=[])
    eq(U.question_answer('c6', 'u1', 'Full')['ok'], False, 'an item that asks something else by now is not settled')
    check(first in w.waits(), 'it still waits')


def test_filed_once(w: World) -> None:
    tid = w.file()
    eq(w.file(), tid, 'resumed and left again: the question that waits is not filed twice')
    Z.filed(S.C, ['T7'], {'n': 6, 'sid': 'sid-6'})
    eq((Z.filed_ids(S.C, 'sid-6'), w.ask()['need']), ([tid, 'T7'], tid), 'another item it files keeps it')
    eq(Z.filed_questions(S.C, 'sid-5'), {}, "another session's is none of its")


NEED = "const need = {...ASK, need: 'F9'}; "


def test_page_sends(tmp: Path) -> None:
    out = Q.run(tmp, NEED + """
      let reads = 0; const asked = {ok: true, ask: need, answered: []};
      live(need); pick(1); await pass(5100); say(kind(), sent.map(x => [x.name, x.args, x.need]), holds);
      S.ob = []; FD.live = {ok: true, ask: null, answered: ['u1']}; render(); say(kind()); await pass(100); say(kind());
      FD.live = asked; QN.sent.clear(); render(); pick(0); await pass(5100); S.ob = []; render(); say(kind()); await pass(100); say(kind());""")
    if out is None:
        return
    eq(out[0], ['', [['question_answer', {'chat': 'c1', 'id': 'u1', 'text': 'Small & flat'}, 'F9']], []],
       'an option settles the item; the chat gets no second answer')
    eq(out[1:3], [[''], ['']], 'the card stays gone')
    eq(out[3:], [[''], ['card']], 'one discarded in the outbox brings the card back, once /live says it is still asked')


def test_page_needs_you(tmp: Path) -> None:
    out = chat_run(tmp, NEED + """
      live(need); outbox('run_control', {key: 'need_answer1', tid: 'F9'}, {need: 'F9'}); say(what());
      S.ob[0].state = 'failed'; render(); say(what()); S.ob = []; render();
      pick(0); outbox('run_control', {}, {need: 'F9'}); await pass(6000); say(sent.map(x => x.name), toasts.length);
      S.ob = []; FD.live = null; live(need); await pass(600); chat(); say(what());
      type('why?'); gone(); live(null); await clear(); say(what(), QN.kept.get('c1').need);
      FD.live = {ok: true, ask: null, answered: ['u1']}; questionSee('c1'); render(); say(what());
      QN.mark.set('c1', need); questionSee('c1'); render(); say(what());""")
    if out is None:
        return
    eq(out[:2], [[''], ['card']], 'an answer under Needs you takes the card at once; one that failed does not')
    eq(out[2], [['run_control', 'run_control'], 1], 'and the held option is not sent as well')
    eq(out[3:5], [['mark'], ['card', 'F9']], 'talked about, it is still the item\'s')
    eq(out[5:], [[''], ['']], 'answered there, the kept card and a mark go too')


if __name__ == '__main__':
    raise SystemExit(report([*(world(f) for f in (test_card_settles, test_needs_you_closes, test_dropped_and_shelved, test_only_its_own,
                                                  test_filed_once)), in_tmp(test_page_sends), in_tmp(test_page_needs_you)]))
