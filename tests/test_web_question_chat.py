"""F192a2: Chat about this on the question card: the mark above the box, the send, the card's return.

    python3 tests/test_web_question_chat.py
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

from _check import check, eq, report
from _web import in_tmp

import test_web_question as Q
from agent_runner import web as W  # noqa: E402

ABOUT = 'About your question “Which <look>?” (not my answer): '

# on top of the question card's own driver: the box, what is kept of the tab, and a send as send() makes it
MORE = r"""
let focused = 0, tab = TAB, box = {};
document.querySelector = s => s === '[data-in]' ? box : null;
const kbFocus = t => { if (t === box) focused++ };
tabStore.get = () => tab; tabStore.set = (k, v) => { tab = v };
for (const x of questionMarks(tab)) QN.mark.set(...x);
const chat = (id = 'u1') => tap({qchat: id}), unchat = () => tap({qunchat: 'c1'});
const what = () => dock.includes('data-qunchat') ? 'mark' : kind();
const type = (text, to = 'c1') => questionOn.send(to, text, (words, more) => outbox('chat_to', {text: words, to}, more));
const gone = () => { const x = S.ob.at(-1); S.ob = []; S.sent.c1 = {at: now, pending: [{text: x.args.text, state: 'sent'}]}; render() };
const clear = async () => { await pass(20000); if (S.sent.c1) S.sent.c1.pending = []; render() };
"""


def run(tmp: Path, steps: str, tab: str = '') -> list | None:
    with mock.patch.object(Q, 'DRIVER', Q.DRIVER.replace('(async', MORE.replace('TAB', json.dumps(tab)) + '(async', 1)):
        return Q.run(tmp, steps)


def test_mark(tmp: Path) -> None:
    out = run(tmp, """
      live(ASK); say(dock); chat('other'); say(what()); chat(); say(what(), focused, sent.length, dock);
      unchat(); say(what()); await pass(600); unchat(); say(what(), tab); chat(); say(what());
      await pass(600); chat(); say(what()); await pass(600); S.thread = FD.n = 'c2'; FD.live = null; render(); say(what()); S.thread = FD.n = 'c1'; render(); say(what());""")
    if out is None:
        return
    check('data-qchat="u1">Chat about this<' in out[0][0], 'the card has Chat about this', out[0][0])
    eq(out[1], ['card'], 'a tap meant for another question does nothing')
    eq(out[2][:3], ['mark', 1, 0], 'a tap marks the question and focuses the box; nothing is sent')
    check('Which &lt;look>?' in out[2][3] and 'data-qpick' not in out[2][3], 'the mark says the question, and has no options', out[2][3])
    eq(out[3], ['mark'], 'a double tap does not take the mark away')
    eq(out[4], ['card', ''], 'its ✕ brings the card back')
    eq(out[5], ['card'], 'nor does a double tap on it mark again')
    eq([x[0] for x in out[6:]], ['mark', '', 'mark'], 'the mark is its own chat\'s')


def test_send(tmp: Path) -> None:
    out = run(tmp, """
      live(ASK); chat(); type('why?'); say(sent[0].args, sent[0].about.id, what(), tab);
      gone(); say(what()); live(ASK); say(what()); await clear(); say(what());
      pick(1); say(what()); await pass(6000); say(sent.map(x => x.args.text), toasts.length, what());
      gone(); await clear(); live(null); say(what()); live({...ASK, id: 'u2'}); say(what());""")
    if out is None:
        return
    eq(out[0], [{'text': ABOUT + 'why?', 'to': 'c1'}, 'u1', 'card', ''], 'the words go as a message about the question, and the card is back')
    eq([x[0] for x in out[1:4]], ['card'] * 3, 'it stays: sent, in the chat, and while /live says it')
    eq(out[4], ['held'], 'an option of it can be picked then')
    eq(out[5], [[ABOUT + 'why?', 'Small & flat'], 0, ''], 'and goes as the answer')
    eq([x[0] for x in out[6:]], ['', 'card'], 'then the card is gone, until another question')


def test_other_question(tmp: Path) -> None:
    out = run(tmp, """
      live(ASK); chat(); type('why?'); gone(); live({...ASK, id: 'u2', question: 'Second?'}); say(dock);
      live(null); say(what());
      live(ASK); await pass(600); chat(); live(null); type('and?'); gone(); await clear(); say(what(), sent.at(-1).args.text);""")
    if out is None:
        return
    check('Second?' in out[0][0], 'a new question takes the place of the one talked about', out[0][0])
    eq(out[1], [''], 'which does not come back after it')
    eq(out[2], ['', ABOUT + 'and?'], 'a question answered elsewhere while marked: its card does not come back')


def test_typed(tmp: Path) -> None:
    out = run(tmp, """
      live(ASK); chat(); type('why?'); gone(); live(ASK); await clear();
      type('blue'); say(what(), sent.at(-1).args.text); gone(); live(null); await clear(); say(what());""")
    if out is None:
        return
    eq(out, [['', 'blue'], ['']], 'a message typed with no mark is the answer, as before, and the card stays gone')


def test_command(tmp: Path) -> None:
    out = run(tmp, """
      live(ASK); chat(); type('/compact'); say(sent[0].args.text, what());
      gone(); await clear(); say(what()); type('why?'); gone(); await clear(); say(what());
      await pass(600); chat(); type('/etc/hosts is it?'); say(sent.at(-1).args.text); await pass(600); chat(); type('!important'); say(sent.at(-1).args.text);""")
    if out is None:
        return
    eq(out[:3], [['/compact', 'mark'], ['mark'], ['card']], 'a command goes as it is, the mark stays, and the card still comes back after the send')
    eq(out[3:], [[ABOUT + '/etc/hosts is it?'], [ABOUT + '!important']], 'words that only look like one are about the question')


def test_reload(tmp: Path) -> None:
    tab = json.dumps([['c1', Q.ASK], ['s1', Q.ASK], ['c2', {'id': 1}]])
    out = run(tmp, "live(null); say(what()); type('why?'); say(sent[0].args.text); say([...QN.mark.keys()]);", tab)
    if out is None:
        return
    eq(out, [['mark'], [ABOUT + 'why?'], [[]]], 'a reload keeps the mark, as it keeps the draft; a broken one is left out')


def test_talked_about(tmp: Path) -> None:
    """F430: /live is the one word on it."""
    out = run(tmp, """
      say(what()); live(ASK); say(what()); pick(0); await pass(6000); say(sent.map(x => x.args.text));
      S.ob = []; S.sent = {}; QN.sent.clear(); live(ASK); chat(); type('why?'); gone(); live(ASK); await clear(); say(what());
      live(null); say(what()); await pass(20000); say(what());""")
    if out is None:
        return
    eq(out[:3], [[''], ['card'], [['Full']]], 'a page just loaded has the card from /live, and its option is sent')
    eq(out[3:], [['card'], [''], ['']], 'talked about here and answered elsewhere: the card goes')


def test_called(tmp: Path) -> None:
    page = W.PAGE.read_text(encoding='utf-8')
    send = page[page.index('async function send(by)'):]
    check('questionOn.send(to,msg,' in send[:send.index('\n}\n')], 'the box sends through the mark')
    back = page[page.index('function obEditBack('):]
    check('questionMark(t,x.about)' in back[:back.index('\n}\n')], 'a message taken back into the box is still about its question')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(f) for f in (test_mark, test_send, test_other_question, test_typed, test_command, test_reload, test_talked_about, test_called)]))
