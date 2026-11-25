"""F192a1: the run page's question card: its drawing, one tap with its hold, Undo.

    python3 tests/test_web_question.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from _check import check, eq, report
from _web import in_tmp

from agent_runner import web as W  # noqa: E402

ASK = {'id': 'u1', 'question': 'Which <look>?', 'options': [{'name': 'Full', 'rec': True}, {'name': 'Small & flat', 'rec': False}]}

# the page's own two files, around a chat that is open; the clock and its timers are this driver's
DRIVER = r"""
let now = 1e6, timers = [], clicks = [], dock = '';
Date.now = () => now;
setTimeout = (fn, ms) => { const t = {fn, at: now + ms}; timers.push(t); return t };
clearTimeout = t => { timers = timers.filter(x => x !== t) };
const pass = async ms => { const end = now + ms;
  for (let t; t = timers.filter(x => x.at <= end).sort((a, b) => a.at - b.at)[0];) { now = Math.max(now, t.at); clearTimeout(t); await t.fn() }
  now = end };
const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
const document = {querySelector: () => null, addEventListener: (k, f) => { clicks.push(f) }};
const S = {thread: 'c1', ob: [], sent: {}}, SEND_HOLD = 1000, toasts = [], sent = [], holds = [], HKEY = 't', tabStore = {get: () => '', set: () => {}};
const FD = {n: 'c1', shown: true, foot: null, live: null};
const feedTop = () => 0, feedGlide = () => {}, feedRest = () => {}, moAnim = () => {}, liveLoad = async () => {}, threadTitle = n => n;
const toast = t => toasts.push(t), sendHold = k => holds.push(k);
const render = () => { dock = questionCard(S.thread) };
const outbox = (name, args, more) => { const it = {cid: 'k' + sent.length, name, args, ...more}; sent.push(it); S.ob.push(it); render(); return it };
const live = ask => { FD.live = {ok: true, ask}; if (FD.n) questionSee(FD.n); render() };
const tap = (data, detail = 1) => clicks.forEach(f => f({detail, target: {closest: s => Object.keys(data).some(k => s.includes(`[data-${k}]`)) ? {dataset: data} : null}}));
const pick = (i, id = 'u1') => tap({qpick: String(i), q: id}), undo = () => tap({qundo: 'c1'});
const went = text => { S.ob = []; S.sent.c1 = {at: now, pending: [{text}]}; render() };
const kind = () => dock.includes('data-qundo') ? 'held' : dock.includes('data-qpick') ? 'card' : '';
const ASK = JSON.parse(process.argv[2]), out = [];
const say = (...a) => out.push(a);
PAGE
(async () => { STEPS
console.log(JSON.stringify(out)) })();
"""


def run(tmp: Path, steps: str) -> list | None:
    if not shutil.which('node'):
        print('  (no node here: the question card test is skipped)')
        return None
    js = ''.join((W.PAGE_DIR / f).read_text(encoding='utf-8') for f in ('023-question.logic.js', '024-questionchat.logic.js', '095-question.js'))
    f = tmp / 'question.js'
    f.write_text(DRIVER.replace('PAGE', js).replace('STEPS', steps), encoding='utf-8')
    r = subprocess.run(['node', str(f), json.dumps(ASK)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs the card', r.stderr[-800:])
    return json.loads(r.stdout or '[]')


def test_drawing(tmp: Path) -> None:
    out = run(tmp, """
      render(); say(dock); live(ASK); say(dock); live({...ASK, options: []}); say(dock); live(null); say(dock);
      live(ASK); S.thread = FD.n = 's1'; render(); say(dock); S.thread = 'c2'; render(); say(dock);""")
    if out is None:
        return
    none, card, bare, gone, slot, other = (x[0] for x in out)
    eq((none, bare, gone, slot, other), ('',) * 5, 'no card before /live, with no options, once `ask` goes, in a slot, in another chat')
    check('Which &lt;look>?' in card and 'role="group"' in card, 'the question, escaped', card)
    eq([card.count('<button'), card.count('data-qpick'), card.count(' pri')], [4, 2, 1], 'one button per option, one main, Chat about this, and Minimize')
    check('class="btn pri" data-qpick="0" data-q="u1">Full (recommended)<' in card, 'the recommended one is first and marked', card)
    check('class="btn" data-qpick="1" data-q="u1">Small &amp; flat<' in card, 'the other as it is', card)


def test_send(tmp: Path) -> None:
    out = run(tmp, """
      live(ASK); pick(1); say(kind(), sent.length); pick(0); pick(1);
      await pass(4900); say(kind(), sent.length); await pass(200); say(kind(), sent.length, sent[0].name, sent[0].args, holds);
      pick(0); await pass(6000); say(kind(), sent.length);
      went('Small & flat'); say(kind()); S.sent.c1.pending = []; render(); say(kind());
      live({...ASK, id: 'u2'}); say(kind());
      pick(0, 'u1'); say(kind());""")
    if out is None:
        return
    eq(out[0], ['held', 0], 'a tap holds it, with Undo')
    eq(out[1], ['held', 0], 'nothing is sent before the hold ends')
    eq(out[2], ['', 1, 'chat_to', {'text': 'Small & flat', 'to': 'c1'}, ['c1']], 'then the first tap\'s option, as a message: never forced')
    eq(out[3], ['', 1], 'a second tap sends nothing more')
    eq(out[4:6], [[''], ['']], 'the card stays gone once the message went, also when the chat has it')
    eq(out[6], ['card'], 'a new question has its card')
    eq(out[7], ['card'], 'a tap meant for the question before it picks nothing')


def test_undo(tmp: Path) -> None:
    out = run(tmp, """
      live(ASK); pick(0); now += 100; undo(); say(kind()); now += 600; undo(); say(kind()); pick(1); say(kind());
      await pass(20000); say(sent.length); pick(1); await pass(5000); say(sent.map(x => x.args.text));
      S.ob = []; render(); say(kind());""")
    if out is None:
        return
    eq(out[0], ['held'], 'the second tap of a double tap does not undo')
    eq(out[1], ['card'], 'Undo brings the card back')
    eq(out[2], ['card'], 'nor does a double tap on Undo pick an option')
    eq(out[3], [0], 'and nothing is sent')
    eq(out[4], [['Small & flat']], 'the next tap is a new answer')
    eq(out[5], ['card'], 'a message discarded in the outbox brings the card back')


def test_gone_in_hold(tmp: Path) -> None:
    out = run(tmp, """
      live(ASK); pick(0); live(null); say(kind(), toasts.length); await pass(6000); say(sent.length);
      live(ASK); pick(0); live({...ASK, id: 'u2'}); await pass(6000); say(kind(), sent.length);
      pick(0, 'u2'); FD.live = {ok: false, ask: null}; questionSee('c1'); FD.n = S.thread = ''; FD.live = null; await pass(6000); say(sent.map(x => x.args.to));""")
    if out is None:
        return
    eq(out[0], ['', 1], 'a question that goes in the hold takes the answer along, and the page says so')
    eq(out[1], [0], 'nothing is sent')
    eq(out[2], ['card', 0], 'nor to the question that came after')
    eq(out[3], [['c1']], 'a chat that was left, or a run that could not say, still gets its answer')


def test_typed(tmp: Path) -> None:
    out = run(tmp, """
      live(ASK); outbox('chat_to', {text: 'blue', to: 'c1'}); say(kind()); S.ob[0].state = 'failed'; render(); say(kind());
      S.ob = []; pick(0); outbox('chat_to', {text: 'blue', to: 'c1'}); await pass(6000); say(sent.map(x => x.args.text), toasts.length);""")
    if out is None:
        return
    eq(out[:2], [[''], ['card']], 'a typed message takes the card at once; one that failed does not')
    eq(out[2], [['blue', 'blue'], 1], 'typed in the hold: the held answer is not sent as well')


def test_slept(tmp: Path) -> None:
    out = run(tmp, """
      live(ASK); pick(0); document.hidden = true; now += 60000; await pass(0); say(sent.length);
      document.hidden = false; FD.live = {ok: true, ask: null}; await pass(2000); say(sent.length);""")
    if out is None:
        return
    eq(out, [[0], [0]], 'a hold slept through waits for the page to be seen, then goes only if it is still asked')


def test_called(tmp: Path) -> None:
    page = W.PAGE.read_text(encoding='utf-8')
    row = page[page.index('function sessRow('):]
    row = row[:row.index('\n}\n')]
    check('ask=questionCard(n)' in row and row.count('return ask+') == 2, 'the card stands over the chips, in the dock with the message box', row)
    load = page[page.index('async function liveLoad('):]
    check('questionMove(n,first)' in load[:load.index('\n}\n')], '/live brings it and takes it')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(f) for f in (test_drawing, test_send, test_undo, test_gone_in_hold, test_typed, test_slept, test_called)]))
