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
from test_chat_question import ASK, LINK, LONG, LONG_Q, say, you

import test_web_question as Q
from test_web_question_chat import run as chat_run
from agent_runner import control as K, control_ask, control_settled as Z, need_detail, plan as P, session_now as N, state as S, ui_model as U

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


def test_closed_chat(w: World) -> None:
    tid = w.file()
    S.C.notes('control6.pid').unlink()
    eq(U.question_answer('c5', 'u1', 'Full')['ok'], False, 'another chat number has no such question')
    eq(U.question_answer('c6', 'u1', 'Full').get('gone'), tid, 'filing ended the chat in the hold: its option still settles the item')
    P.block(tid, P.decide_question(ASK) and 'DECIDE: ' + P.decide_question(ASK), todo=S.C.todo, after=[])
    check(tid in w.waits(), 'asked again in the same words')
    eq(U.question_answer('c6', 'u1', 'Small')['ok'], False, 'the old card does not settle it')


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


def test_long_b840(w: World) -> None:
    w.rows[:] = []
    w.add(say(LONG))
    tid = w.file(LONG)
    what, url = next((a[3], a[4]) for a in P.asks(S.C.todo) if a[1] == tid)
    line = next(x for x in S.C.todo.read_text(encoding='utf-8').splitlines() if f'**{tid}**' in x)
    opts, question = need_detail.decide_options(tid, what, line)
    eq((url, w.ask()['need']), (LINK, tid), 'the link is kept, and the card knows its item')
    check(question.startswith(LONG_Q) and '…' not in question, 'the item reads the whole question', question)
    eq([o['name'] for o in opts], ['Attach both videos', 'Leave the item as it is'], 'and has both options')
    eq(w.ask()['question'], LONG_Q, 'as the card does')
    eq(U.question_answer('c6', 'u1', 'Attach both videos')['ok'], True, 'an option settles it')


def test_marks_b840(w: World) -> None:
    text = 'Both work.\n\nDECIDE: Keep it — as a BLOCKED: line — or not? [Keep — as it is / Drop] https://example.com/a'
    w.rows[:] = []
    w.add(say(text))
    tid = w.file(text)
    what, url = next((a[3], a[4]) for a in P.asks(S.C.todo) if a[1] == tid)
    opts, question = need_detail.decide_options(tid, what, '')
    eq((question.split(' http')[0], url), (w.ask()['question'], 'https://example.com/a'), "a task line's own marks in it cost the item no word")
    eq([o['name'] for o in opts], [o['name'] for o in w.ask()['options']], 'nor an option')
    eq(w.ask()['need'], tid, 'and the card knows its item')
    eq(control_ask.explained(w.rows, 'Keep it — as a BLOCKED: line — or not? [Keep — as it is / Drop] https://example.com/a')[0],
       'Both work.', 'one filed before is still found')


def test_filed_cut_b840(w: World) -> None:
    w.rows[:] = []
    w.add(say(LONG))
    cut = P.cut_question(P.decide_question(LONG))
    with mock.patch.object(control_ask, 'filed'):
        tid = K.file_control_ask(6, 'sid-6', cut, 'https://claude.ai/code/session_01AbC')
    check(cut in S.C.todo.read_text(encoding='utf-8'), 'filed by the version before, cut', cut)
    eq((w.file(LONG), w.ask()['need']), (tid, tid), 'it is not filed twice, and the card is its')
    eq(control_ask.explained(w.rows, cut)[0], 'Both are ready.', 'what explains it is still found')
    eq(control_ask.explained(w.rows, '')[0], '', 'and nothing for no question')
    eq(U.question_answer('c6', 'u1', 'Attach both videos')['ok'], True, "the card's option settles it")
    check('Attach both videos' in ' '.join(P.section(S.C.todo, tid)).split('your answer')[-1], 'with the answer in its note')
    eq((w.ask(), N.live('c6')['answered']), (None, ['u1']), 'and the card closes')


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
      S.ob[0].args.key = 'need_later'; render(); say(what()); S.ob[0].args.key = 'need_answer1';
      S.ob[0].state = 'failed'; render(); say(what()); S.ob = []; render();
      pick(0); outbox('run_control', {key: 'need_yes'}, {need: 'F9'}); await pass(6000); say(sent.map(x => x.name), toasts.length);
      S.ob = []; FD.live = null; live(need); await pass(600); chat(); say(what());
      type('why?'); gone(); live(need); await clear(); say(what(), FD.live.ask.need);
      FD.live = {ok: true, ask: null, answered: ['u1']}; questionSee('c1'); render(); say(what());
      QN.mark.set('c1', need); questionSee('c1'); render(); say(what());""")
    if out is None:
        return
    eq(out[:3:2], [[''], ['card']], 'an answer under Needs you takes the card at once; one that failed does not')
    eq(out[1], ['card'], 'Later answers nothing')
    eq(out[3], [['run_control', 'run_control'], 1], 'and the held option is not sent as well')
    eq(out[4:6], [['mark'], ['card', 'F9']], 'talked about, it is still the item\'s')
    eq(out[6:], [[''], ['']], 'answered there, the card and a mark go too')


def home(w: World) -> list[dict]:
    """B832: Home's Needs you rows of chat c6, read as the snapshot reads them."""
    from agent_runner import slots
    with mock.patch.object(slots, 'transcript', lambda sid: w.path), \
            mock.patch.object(slots, 'entries', lambda sid, skip_bad=False: list(w.rows)):
        return U.chat_needs(U.control_rows({6: 'six'}))


def test_home_b832(w: World) -> None:
    rows = home(w)
    eq([(r['chat'], r['id'], r['title'], r['question']) for r in rows], [('c6', 'u1', 'six', 'Which look?')],
       'a fresh DECIDE is a row at once, with its chat, question and name')
    eq([o['name'] for o in rows[0]['options']], ['Full', 'Small', 'No change'], 'and its options, the recommended first')
    check(rows[0]['at'] > 0, 'and when it was asked', rows[0])
    w.rows[:] = []
    w.add(say('Done.\n\nDECIDE: Ship it now, or wait for the review?', 'u2'))
    eq([(r['id'], r['options']) for r in home(w)], [('u2', [])], 'one with no options is a row too')
    w.add(you('wait'))
    eq(home(w), [], 'answered, it goes')
    w.add(say('Waiting. Anything else?', 'u3'))
    eq(home(w), [], 'an offer without a DECIDE line is no row')
    w.add(you('no'), say(ASK, 'u4'), you('About your question “Which look?” (not my answer): why?'), say('Because.', 'u5'))
    eq([r['id'] for r in home(w)], ['u4'], 'a message about the question (F430) keeps it')
    S.C.notes('control6.name').write_text(json.dumps({'name': 'Re-sign', 'was': ''}), encoding='utf-8')
    eq([r['title'] for r in home(w)], ['Re-sign'], 'a renamed chat: its name')


def test_home_filed_once_b832(w: World) -> None:
    eq(len(home(w)), 1, 'before it is filed, the chat row')
    w.file()
    eq(home(w), [], 'once filed, only the filed item shows')


def test_page_b832(tmp: Path) -> None:
    import shutil
    import subprocess
    if not shutil.which('node'):
        print('  (no node here: skipped)')
        return
    from agent_runner import web as W
    js = (W.PAGE_DIR / '023-question.logic.js').read_text(encoding='utf-8')
    home_js = (W.PAGE_DIR / '050-home.js').read_text(encoding='utf-8')
    js += home_js[home_js.index('/* --- B832'):]
    count = (W.PAGE_DIR / '040-chats.js').read_text(encoding='utf-8')
    check('S.snap.needs.length+(S.snap.chat_needs||[]).length' in count, "the side's Home count has them")
    drv = r"""
let now = 1e6, timers = [], on = {click: [], submit: []};
setTimeout = (fn, ms) => { const t = {fn, at: now + ms}; timers.push(t); return t };
clearTimeout = t => { timers = timers.filter(x => x !== t) };
const pass = ms => { now += ms; for (const t of timers.filter(x => x.at <= now)) { clearTimeout(t); t.fn() } };
const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
const document = {addEventListener: (k, f) => on[k] && on[k].push(f)};
const card = (h, cls, attr) => `<div class="card ${cls}" ${attr}>${h}</div>`, agoWords = () => '5 min ago', threadTitle = n => n;
const S = {f: {}, ob: [], snap: {chat_needs: [{chat: 'c9', id: 'u1', title: 'Re-sign', question: 'Ship it?', at: 1,
  options: [{name: 'Yes', rec: true}, {name: 'No', rec: false}]}]}}, sent = [];
const outbox = (name, args, more) => { sent.push([name, args]); const it = {cid: 'k' + sent.length, state: 'sending'}; S.ob.push(it); return it }, render = () => {};
const ev = (k, ds) => ({target: {dataset: ds, closest: s => s.split(',').some(x => Object.keys(ds).some(d => x === `[data-${d}]`)) ? {dataset: ds} : null},
  preventDefault() {}, stopImmediatePropagation() {}});
const out = [], say = (...a) => out.push(a), draw = () => chatNeedsShown().map(chatNeedCard).join('');
PAGE
say(draw(), chatNeedsShown().length);
on.click.forEach(f => f(ev('click', {cnpick: '1', cnchat: 'c9', cnid: 'u1'}))); say(draw().includes('data-cnundo'), sent.length);
on.click.forEach(f => f(ev('click', {cnundo: 'c9'}))); pass(6000); say(draw().includes('data-cnpick'), sent.length);
on.click.forEach(f => f(ev('click', {cnpick: '0', cnchat: 'c9', cnid: 'u1'}))); pass(5100); say(sent.slice(), chatNeedsShown().length);
S.ob[0].state = 'failed'; say(chatNeedsShown().length); S.ob = [];
S.snap.chat_needs = []; chatNeedsShown(); S.snap.chat_needs = [{chat: 'c9', id: 'u2', title: 'x', question: 'Why?', at: 0, options: []}];
S.f['cnsay:c9'] = ' because '; on.submit.forEach(f => f(ev('submit', {cnform: 'c9'}))); say(sent[1], chatNeedsShown().length);
console.log(JSON.stringify(out));
"""
    f = tmp / 'chatneed.js'
    f.write_text(drv.replace('PAGE', js), encoding='utf-8')
    r = subprocess.run(['node', str(f)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs the row', r.stderr[-800:])
    out = json.loads(r.stdout or '[]')
    if not out:
        return
    html, n = out[0]
    eq(n, 1, 'the row counts')
    check('Ship it?' in html and 'Re-sign' in html and 'data-thread="c9">Chat<' in html, 'question, chat name, and Chat opens it', html)
    check('class="btn pri" data-cnpick="0"' in html and 'Yes (recommended)' in html, 'option buttons, the recommended marked', html)
    eq(out[1], [True, 0], 'an option waits with Undo')
    eq(out[2], [True, 0], 'Undo sends nothing')
    eq(out[3], [[['chat_to', {'text': 'Yes', 'to': 'c9'}]], 0], 'after the hold it goes to the chat, and the row goes')
    eq(out[4], [1], 'one that failed in the outbox brings the row back')
    eq(out[5], [['chat_to', {'text': 'because', 'to': 'c9'}], 0], 'typed words go to the chat as a message')



def test_cli_f486(w: World) -> None:
    """F486: the `needs` command and status's Needs you list the chat's DECIDE too, until the run files it."""
    from agent_runner import chat_question as CQ, slots, status
    with mock.patch.object(slots, 'transcript', lambda sid: w.path), \
            mock.patch.object(slots, 'entries', lambda sid, skip_bad=False: list(w.rows)), \
            mock.patch.object(U, 'control_titles', lambda: {6: 'six'}):
        eq(CQ.need_lines(CQ.live_needs()), ['c6 - Which look? [Full (recommended) / Small / No change]'], 'one line, its options')
        check('  c6 - Which look?' in status.status_text(False, {}, [], {}, 0), 'status lists it under Needs you')
        w.file()
        eq(CQ.live_needs(), [], 'once filed, only the filed item')


if __name__ == '__main__':
    raise SystemExit(report([*(world(f) for f in (test_card_settles, test_needs_you_closes, test_closed_chat, test_dropped_and_shelved, test_only_its_own,
                                                  test_filed_once, test_long_b840, test_marks_b840, test_filed_cut_b840, test_home_b832, test_home_filed_once_b832, test_cli_f486)), in_tmp(test_page_sends), in_tmp(test_page_needs_you), in_tmp(test_page_b832)]))
