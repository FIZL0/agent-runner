"""The run page, talk area (agent_runner/page/*-talk.*): split from test_web.py (C41b), then by area (C58).

    python3 tests/test_web_talk.py
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from _check import check, eq, git, report
from _trust import asked, trusted_checks

from agent_runner import config as CF  # noqa: E402
from agent_runner import state as S  # noqa: E402
from agent_runner import ui_model as U  # noqa: E402
from agent_runner import web as W  # noqa: E402
from test_web_live import SCROLL_DRIVER  # noqa: E402
from _web import TODO, fake_repo, get, post, LOGIC_DRIVER, logic_js, in_tmp  # noqa: E402


def test_talk_f93(tmp: Path) -> None:
    """F93: Talk is the first view in the sidebar; a Talk send opens its own control session titled Talk whose
    first message carries the spoken-reply instruction, and later sends to it carry the reminder; the page finds
    that session, says why the mic cannot listen, shows the person's words alone and reads the reply aloud."""
    from agent_runner import control as CT
    fake_repo(tmp)
    page = W.page_html().decode()
    check('const nav=NAV;' in page.split('function side(){', 1)[1].split('\nfunction ', 1)[0],
          'the sidebar draws its views from NAV')
    check("act('talk',{text:msg,to})" in page and 'data-mic' in page and 'webkitSpeechRecognition' in page
          and 'speechSynthesis.speak' in page, 'the Talk view: a mic, Web Speech, the talk action, read aloud')
    ask = CT.talk_ask('what is going on?')
    for words in ('short plain sentences', 'Never say task IDs, branch names, file paths, commands, links',
                  'no markdown', 'lists, tables', 'round numbers', 'one thing at a time'):
        check(words in ask, f'the Talk brief says: {words}')
    eq(CT.control_title(ask), 'Talk', 'a Talk session is titled Talk')
    eq(CT.control_title('Talk mode: what now'), 'Talk mode: what now', 'a typed "Talk mode:" ask is not Talk')
    eq(U.given_title(CT.control_name(7, ask), 7), 'Talk', 'and the run page lists it as Talk')
    token = W.web_token()
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {})
    url = f'http://127.0.0.1:{srv.server_address[1]}/act?t={token}'
    calls, typed = [], []
    try:
        with mock.patch.object(U, 'RUN', [lambda argv: (calls.append(argv), (0, 'control 7 is up in a hidden terminal'))[1]]):
            code, out = post(url, {'name': 'talk', 'args': {'text': ' what is going on? ', 'to': ''}})
            eq((code, out.get('ok'), out.get('session')), (200, True, 'c7'), 'the first Talk send opens c7')
            eq(calls, [['control', '--new', '--ask', ask, '--no-feed']], 'with the spoken-reply instruction as its first message')
            with mock.patch.object(U, 'chat_to', lambda text, to: (typed.append((to, text)),
                                                                   {'ok': True, 'code': 0, 'out': '', 'argv': []})[1]):
                code, out = post(url, {'name': 'talk', 'args': {'text': 'and the merge?', 'to': 'c7'}})
            eq((out.get('ok'), out.get('session')), (True, 'c7'), 'a later send goes to the live Talk session')
            eq(typed, [('c7', CT.TALK_TAG + 'and the merge?')], 'with the spoken-reply reminder')
            with mock.patch.object(U, 'chat_to', lambda text, to: {'ok': False, 'code': 1, 'out': 'gone', 'argv': []}):
                code, out = post(url, {'name': 'talk', 'args': {'text': 'hello', 'to': 'c7'}})
            eq((out.get('ok'), calls[-1]), (True, ['control', '--new', '--ask', CT.talk_ask('hello'), '--no-feed']),
               'a Talk session that is gone: a new one opens')
            code, out = post(url, {'name': 'talk', 'args': {'text': '  '}})
            eq(out.get('ok'), False, 'nothing said: nothing sent')
    finally:
        srv.stop()
    if not shutil.which('node'):
        print('  (no node here: the Talk script test is skipped)')
        return
    live = [{'name': 'c1', 'title': 'control session', 'state': 'live'}, {'name': 'c4', 'title': 'Talk', 'state': 'live'},
            {'name': 'c6', 'title': 'Site deploy', 'state': 'live'}, {'name': 'c8', 'title': 'Talk', 'state': 'ended'}]
    feed = [{'kind': 'you', 'text': 'old'}, {'kind': 'say', 'text': 'Old.'}, {'kind': 'you', 'text': 'now?'},
            {'kind': 'tool', 'text': 'Bash(run status)'}, {'kind': 'say', 'text': 'Two agents are **working**.'},
            {'kind': 'tool', 'text': 'Bash(x)'}, {'kind': 'say', 'text': 'Nothing needs you.'}]
    got = logic_js([['talkSession', live, 'c6'], ['talkSession', live, 'c8'],
                    ['talkSession', live[:1], ''], ['micProblem', False, True], ['micProblem', True, False],
                    ['micProblem', True, True], ['micProblem', False, False], ['talkShown', ask], ['talkShown', CT.talk_message('and you?')],
                    ['talkShown', 'plain words'], ['talkReply', feed, 2], ['talkReply', feed[:6], 2],
                    ['talkReply', feed, 7]])
    eq(got[:3], ['c6', 'c4', ''], 'the remembered live session, else a live chat titled Talk, else none')
    check('https or localhost' in got[3] and 'Type below' in got[3], 'plain http: the mic says it needs https', got[3])
    check('cannot turn speech into text' in got[4], 'no speech recognition: the mic says so', got[4])
    eq(got[5], '', 'https with recognition: the mic listens')
    check('https link' in got[6] and 'cannot turn speech' not in got[6],
          'B130: plain http without recognition (Safari hides it there): the mic points at the https link', got[6])
    del got[6]
    eq(got[6:9], ['what is going on?', 'and you?', 'plain words'], "the person's words show without the brief")
    eq(got[9], 'Two agents are working. Nothing needs you.', 'the reply since the send, in plain words, read aloud')
    eq(got[10:12], ['', ''], 'nothing is read while it still works, or before it says anything new')
    js = W.PAGE.read_text(encoding='utf-8').split('<script id="logic">', 1)[1].split('</script>', 1)[0]
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / 'logic.js').write_text(js, encoding='utf-8')
        r = subprocess.run(['node', '-e', 'process.stdout.write(JSON.stringify(require(process.argv[1]).NAV))',
                            str(Path(d) / 'logic.js')], capture_output=True, text=True, timeout=60)
    nav = json.loads(r.stdout or '[]')
    eq([k for k, _ in nav][:2], ['talk', 'home'], 'Talk is the top view in the sidebar, above Home')


LISTEN_DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');  // a Windows checkout is CRLF
const grab = (start) => { const i = page.indexOf(start); return page.slice(i, page.indexOf('\n}\n', i) + 2); };
const logic = page.split('<script id="logic">')[1].split('</script>')[0];
let spoke = 0, sent = [];
const window = {speechSynthesis: {cancel() { spoke++ }, speak() { spoke++ }}};
const speechSynthesis = window.speechSynthesis;
class SpeechSynthesisUtterance {}
let rec = null;
class SR { constructor() { rec = this } start() { this.started = spoke } stop() {} }
const navigator = {language: 'en-US'};
const TK = {rec: null, heard: '', state: '', wait: null, said: '', unlocked: false, note: '', later: []};
const micWhy = () => '', toast = () => {}, render = () => {}, talkSend = t => { sent.push(t) };
const I = {stop: '', talk: '', speak: '', mute: ''};
const line = s => { const i = page.indexOf(s); return page.slice(i, page.indexOf('\n', i)) + '\n' };
const S = {view: 'talk', thread: null}, document = {hidden: false};
const el = {}, $ = k => el[k] = el[k] || {classList: {toggle() {}}, setAttribute() {}, removeAttribute() {}, textContent: '', className: ''};
const setHTML = () => true, talkTyping = () => false, talkDock = () => (talkDraw(), $('talkline').textContent);
let TS = {read: true, voice: '', mic: 'tap', auto: false};
eval(logic.replace('const TALK_SET', 'var TALK_SET') + grab('function unlockSpeech(') + grab('function talkDraw(') + line('const MIC=') + grab('function micWhenFree(') + grab('function micFree(') + 'const AU={el:null,got:null,ok:false};' + grab('function shush(') + grab('function unlockAudio(') + grab('function listen(') + grab('function hear(') + grab('function micSent(') + grab('function earEnd(') + grab('function micStop(') + `
  Date.now = () => 1000;
  listen();
  const before = rec.started;
  Date.now = () => 3000; rec.onerror({error: 'no-speech'}); rec.onend();
  const said = talkDock();
  listen();
  const cleared = talkDock();
  rec.onresult({resultIndex: 0, results: [Object.assign([{transcript: 'hello'}], {isFinal: true})]}); listen(); rec.onend();
  TK.state = 'speaking'; rec = null; spoke = 0;
  listen();
  const stopped = {state: TK.state, before: rec.started, cancelled: spoke};
  console.log(JSON.stringify({before, line: said, cleared, sent, stopped}));`);
"""


def test_listen_heard_nothing_b132(tmp: Path) -> None:
    """B132: a listen touches no speechSynthesis before rec.start() (iOS then hears nothing), and one that ends with
    no words says so in the talk line with the last error, instead of going quiet."""
    if not shutil.which('node'):
        print('  (no node here: the listen script test is skipped)')
        return
    (tmp / 'driver.js').write_text(LISTEN_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs listen()', r.stderr[-800:])
    got = json.loads(r.stdout or '{}')
    eq(got.get('before'), 0, 'listen does not touch speechSynthesis before rec.start()')
    eq(got.get('line'), 'Heard nothing (error: no-speech, tap, after 2.0 s)', 'no words and error no-speech: the talk line says so')
    eq(got.get('cleared'), 'Starting the mic…', 'the next listen clears it')
    eq(got.get('sent'), ['hello'], 'words heard are still sent')
    eq(got.get('stopped'), {'state': 'listening', 'before': 0, 'cancelled': 1},
       'B174: a tap during a reply listens, and cuts the voice only after rec.start()')


TALK_HEAR_DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');  // a Windows checkout is CRLF
const grab = (start) => { const i = page.indexOf(start); return page.slice(i, page.indexOf('\n}\n', i) + 2); };
const logic = page.split('<script id="logic">')[1].split('</script>')[0];
const said = []; let cancels = 0;
const window = {speechSynthesis: {cancel() { cancels++ }, speak(u) { if (u.text) said.push(u.text) }}};
const speechSynthesis = window.speechSynthesis;
class SpeechSynthesisUtterance { constructor(t) { this.text = t } }
const navigator = {language: 'en-US'};
const kept = {}, store = {get: k => kept[k] || '', set(k, v) { kept[k] = v }};
const toast = () => {}, render = () => {}, tq = p => p, TALK_KEY = 'ar-talk', TALK_OLD = 'ar-talkold', TALK_START = 'ar-talkstart';
const talkKept = () => store.get(TALK_KEY), talkKeep = v => store.set(TALK_KEY, v);  // B177
const keepSent = () => {}, sessionOf = () => null, newCid = () => 'k';  // B154
const loadVoices = () => {};  // F158
const OB = {offline: false}, drain = () => {};  // F137: takeSnap wakes the outbox
let TS = {read: true, voice: '', mic: 'tap', auto: false}; const voices = () => [], talkTyping = () => false;  // F124
const HOME_PAGE = false, document = {};  // B153: takeSnap sets the window title
const S = {snap: {sessions: [], queue: []}, feeds: {}, sent: {}, waitNew: null};
const chats = () => S.snap.sessions.filter(s => /^c\d+$/.test(s.name)), working_ = () => [];
const feedOf = n => (S.feeds[n] || {}).entries || [];
const chatShown = () => true, toEnd = () => {};
const TK = {rec: null, heard: '', state: '', wait: null, said: '', unlocked: false, note: '', gen: 0, starting: [], later: []};
const MIC = {rec: null, next: null};  // B174
let feeds = {}, actDone = null, actResult = null;
const fetch = async p => ({json: async () => ({ok: true, entries: feeds[decodeURIComponent(p.split('/')[1])] || []})});
const acts = [], act = (name, args) => { acts.push(args); return new Promise(res => { actDone = x => res(x || actResult) }) };
const tick = () => new Promise(r => setTimeout(r, 0));
const c13 = [{name: 'c13', title: 'Talk', state: 'live'}];
const reply = [{kind: 'you', text: 'Talk mode: …\n\nThey said: Hello'}, {kind: 'say', text: "Hi there. I'm listening."}];
const reset = () => { said.length = 0; TK.state = ''; TK.wait = null; TK.starting = []; TK.later = []; acts.length = 0; S.snap.sessions = []; S.feeds = {}; feeds = {};
  for (const k in kept) delete kept[k] };
eval(logic + grab('function talkOld(') + grab('function newTalk(')  // talkOld's reaches to talkFind's end
  + grab('function talkName(') + grab('function talkWaitName(') + grab('async function talkSend(')
  + grab('function talkHear(') + 'const AU={el:null,got:null,ok:false};' + grab('function shush(') + grab('function unlockAudio(')
  + grab('function unlockSpeech(') + grab('function speak(') + grab('function takeSnap(')
  + grab('async function loadFeed(') + grab('function addSent(') + `
(async () => {
  const out = {};
  // the session was just opened and the talk action named none: two snapshots list c13, titled Talk, with its reply
  actResult = {ok: true, session: ''};
  const sent = talkSend('Hello'); actDone(); await sent;
  feeds.c13 = reply;
  for (let i = 0; i < 2; i++) { takeSnap({sessions: c13}); await tick(); await tick() }
  out.unnamed = {state: TK.state, said: said.join(' '), remembered: kept['ar-talk'] || ''};
  const shown = talkName();  // what talkHTML renders: convo of this chat's feed
  out.shown = {name: shown, last: (feedOf(shown).slice(-1)[0] || {}).text || ''};
  // the talk action still waits for the new chat's link while its reply lands: the snapshots hear it meanwhile
  reset(); actResult = {ok: true, session: 'c13'};
  const slow = talkSend('Hello');
  feeds.c13 = reply;
  for (let i = 0; i < 2; i++) { takeSnap({sessions: c13}); await tick(); await tick() }
  out.slow = {state: TK.state, said: said.join(' ')};
  actDone(); await slow; await tick();
  out.slowAfter = {state: TK.state, wait: TK.wait};
  // B134: a feed at its cap (its length stands still, its indexes move): what came after the send is still heard,
  // and a reply that says again what was said before is not cut short
  const old = [];
  for (let i = 0; i < 200; i++) old.push({kind: i % 2 ? 'say' : 'you', text: i % 2 ? 'Okay.' : 'ping', id: 'e' + i});
  const more = [{kind: 'you', text: '(Talk: answer as speech.) Hello', id: 'n0'}, {kind: 'say', text: 'Okay.', id: 'n1'},
                {kind: 'say', text: 'Two agents are running.', id: 'n2'}];
  for (const ids of [true, false]) {
    reset(); actResult = {ok: true, session: 'c13'}; kept['ar-talk'] = 'c13'; S.snap.sessions = c13;
    const strip = es => ids ? es : es.map(({kind, text}) => ({kind, text}));
    const base = ids ? old : old.map((e, i) => ({...e, text: e.text + i}));
    S.feeds.c13 = {entries: strip(base)};
    const cap = talkSend('Hello'); actDone(); await cap;
    feeds.c13 = strip(base.concat(more).slice(-200));
    for (let i = 0; i < 2; i++) { await loadFeed('c13') }
    out['capped' + (ids ? '' : 'NoIds')] = {state: TK.state, said: said.join(' '), len: feedOf('c13').length};
  }
  // the feed was not read yet at the send: only what follows the person's own words is read aloud
  reset(); actResult = {ok: true, session: 'c13'}; kept['ar-talk'] = 'c13'; S.snap.sessions = c13;
  const un = talkSend('Hello'); actDone(); await un;
  feeds.c13 = old.concat(more);
  for (let i = 0; i < 2; i++) { await loadFeed('c13') }
  out.unread = said.join(' ');
  // F124: read replies aloud off: the reply shows, nothing is said
  reset(); actResult = {ok: true, session: 'c13'}; TS.read = false; kept['ar-talk'] = 'c13'; S.snap.sessions = c13;
  S.feeds.c13 = {entries: old}; const mute = talkSend('Hello'); actDone(); await mute;
  feeds.c13 = old.concat(more); for (let i = 0; i < 2; i++) { await loadFeed('c13') }
  out.mute = {state: TK.state, said: said.join(' ')};
  // F157: New Talk chat, with the old chat c13 (titled Talk) live throughout
  TS.read = true;
  const c14 = {name: 'c14', title: 'Talk', state: 'live'}, both = c13.concat([c14]);
  const reload = () => { TK.wait = null; TK.gen = 0; TK.state = ''; TK.starting = talkStartsRead() };  // what a reload forgets
  const start = () => { reset(); kept['ar-talk'] = 'c13'; S.snap.sessions = c13; S.feeds.c13 = {entries: old} };
  const stops = [];
  start(); TK.state = 'listening'; TK.heard = 'half a'; TK.hold = true; TK.ear = {}; TK.rec = {stop() { stops.push('mic') }};
  newTalk();
  out.newListening = [TK.state, TK.heard, TK.hold, TK.ear, TK.rec, stops.length, acts.length];
  start(); TK.state = 'speaking'; cancels = 0; newTalk(); out.newSpeaking = [TK.state, cancels];
  start(); TK.state = 'thinking'; TK.wait = {n: 'c13', at: Date.now()}; cancels = 0; newTalk();
  out.newThinking = [TK.state, TK.wait, talkName(), talkWaitName(), cancels];
  reload(); out.newReload = talkName();
  const go = talkSend('Fresh');
  out.newSend = [acts[0], talkName(), talkWaitName()];
  takeSnap({sessions: c13}); out.newWaiting = talkWaitName();  // the old one is not taken while the new one starts
  actDone({ok: true, session: 'c14'}); await go;
  out.newNamed = [talkName(), kept['ar-talk']];
  takeSnap({sessions: both}); reload(); out.newKept = talkName();
  S.snap.sessions = c13; out.newEnded = talkName();  // the new one ended: not back to the old one
  // the action named no session: the new chat is found by its title, never the old one; also over a reload
  start(); newTalk(); let un2 = talkSend('Fresh'); actDone({ok: true, session: ''}); await un2;
  takeSnap({sessions: c13}); const none = talkWaitName(); takeSnap({sessions: both});
  out.newUnnamed = [none, talkWaitName(), kept['ar-talk']];
  start(); newTalk(); talkSend('Fresh'); reload(); out.newMidReload = [talkName(), (S.snap.sessions = both, talkName())];
  // it failed: the next message still opens a new one
  start(); newTalk(); un2 = talkSend('Fresh'); actDone({ok: false}); await un2;
  out.newFailed = [kept['ar-talk'], talkName()];
  // pressed while a message is on its way: its answer does not bring the old chat back
  start(); un2 = talkSend('Old words'); newTalk(); actDone({ok: true, session: 'c13'}); await un2;
  out.newInFlight = [talkName(), TK.state, S.sent.c13.pending.slice(-1)[0].text];
  // pressed while a chat is still starting: that one is old as soon as it shows, the next is the new one
  reset(); un2 = talkSend('One'); const one = actDone; newTalk();
  const two = talkSend('Two'), twoDone = actDone;
  takeSnap({sessions: c13}); out.newStarting = [talkName(), talkWaitName()];
  one({ok: true, session: 'c13'}); await un2; const during = TK.state; twoDone({ok: true, session: 'c14'}); await two;
  takeSnap({sessions: both}); out.newStarted = [during, acts.map(a => a.to), talkName()];
  // the same over a reload before any of it shows
  reset(); talkSend('One'); newTalk(); reload(); talkSend('Two');
  takeSnap({sessions: c13}); out.newStartReload = [talkName(), (takeSnap({sessions: both}), talkName())];
  // pressed before the first snapshot, and one more press keeps what was left
  reset(); kept['ar-talk'] = 'c13'; newTalk(); newTalk(); takeSnap({sessions: c13}); talkSend('Fresh'); reload();
  out.newEarly = [talkName(), JSON.parse(kept['ar-talkold'])];
  console.log(JSON.stringify(out));
})();`);
"""


def test_talk_new_chat_f157(tmp: Path) -> None:
    """F157: New Talk chat stays in Talk: it stops the mic, the speech and the wait, the next message goes out with no
    'to', and the new session is the one Talk keeps, also over a reload, while an old chat titled Talk is live."""
    page = W.page_html().decode()
    top = page.split('function topHTML(){', 1)[1].split('\n}', 1)[0]
    check('${plusBtn()}' in top and "talk:()=>b('data-newtalk','New talk','New Talk chat')" in page
          and "if(q('[data-newtalk]')){newTalk();if(S.live)viewIn(" in page, "in Talk the top bar's button is New Talk chat")
    if not shutil.which('node'):
        print('  (no node here: the New Talk chat script test is skipped)')
        return
    live = [{'name': 'c4', 'title': 'Talk', 'state': 'live'}, {'name': 'c5', 'title': 'Talk', 'state': 'live'}]
    eq(logic_js([['talkSession', live, 'new'], ['talkSession', live, '', ['c4']], ['talkSession', live, 'c9', ['c4', 'c5']]]),
       ['', 'c5', ''], 'no chat once a new one is asked for, and never one that was left')
    (tmp / 'driver.js').write_text(TALK_HEAR_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs newTalk', r.stderr[-800:])
    got = json.loads(r.stdout or '{}')
    eq(got.get('newListening'), ['', '', False, None, None, 1, 0], 'the mic stops and nothing is sent')
    eq(got.get('newSpeaking'), ['', 1], 'the speech stops')
    eq(got.get('newThinking'), ['', None, '', '', 0], 'the wait for a reply ends, and Talk shows no chat')
    eq(got.get('newReload'), '', 'nor after a reload')
    eq(got.get('newSend'), [{'text': 'Fresh', 'to': ''}, '', ''], "the next message goes out with no 'to'")
    eq(got.get('newWaiting'), '', 'the wait does not take the old chat')
    eq(got.get('newNamed'), ['c14', 'c14'], 'the new session is remembered')
    eq(got.get('newKept'), 'c14', 'and kept after a reload')
    eq(got.get('newEnded'), '', 'the new one ended: Talk does not go back to the old one')
    eq(got.get('newUnnamed'), ['', 'c14', 'c14'], 'no name came back: the new chat is found by its title')
    eq(got.get('newMidReload'), ['', 'c14'], 'a reload while it starts: found once it shows')
    eq(got.get('newFailed'), ['new', ''], 'it failed: the next message still opens a new one')
    eq(got.get('newInFlight'), ['', '', 'Old words'], "an old message's answer changes nothing, its chat has it")
    eq(got.get('newStarting'), ['', ''], 'a chat still starting when it was pressed is not taken')
    eq(got.get('newStartReload'), ['', 'c14'], 'also when the page was reloaded meanwhile')
    eq(got.get('newEarly'), ['', ['c13']], 'pressed before the first snapshot: the old chat is still left')
    eq(got.get('newStarted'), ['thinking', ['', ''], 'c14'], 'the one opened after it is')


def test_talk_reply_heard_b133(tmp: Path) -> None:
    """B133: a Talk reply is always shown and read aloud: a talkSend to a just-opened chat (the talk action named no
    session) is heard from the snapshots that list it, so is a reply that lands while the action still waits for the
    new chat's link."""
    if not shutil.which('node'):
        print('  (no node here: the Talk reply script test is skipped)')
        return
    (tmp / 'driver.js').write_text(TALK_HEAR_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs talkSend and the snapshots', r.stderr[-800:])
    got = json.loads(r.stdout or '{}')
    eq(got.get('unnamed'), {'state': 'speaking', 'said': "Hi there. I'm listening.", 'remembered': 'c13'},
       'a just-opened chat, then two snapshots: speaking the reply, and the chat is remembered')
    eq(got.get('slow'), {'state': 'speaking', 'said': "Hi there. I'm listening."},
       'a reply that lands while the talk action still runs is spoken')
    eq(got.get('slowAfter'), {'state': 'speaking', 'wait': None}, 'the action ending later does not wait again')
    eq(got.get('capped'), {'state': 'speaking', 'said': 'Okay. Two agents are running.', 'len': 200},
       'B134: a Talk chat past the feed cap: the whole reply is read, what it says again too')
    eq(got.get('cappedNoIds'), {'state': 'speaking', 'said': 'Okay. Two agents are running.', 'len': 200},
       'B134: and from a transcript without ids')
    eq(got.get('unread'), 'Okay. Two agents are running.', 'B134: a feed not read at the send: only the reply')
    eq(got.get('mute'), {'state': '', 'said': ''}, 'F124: read replies aloud off: nothing is said')
    eq(got.get('shown'), {'name': 'c13', 'last': "Hi there. I'm listening."},
       'the Talk view shows c13, its feed ending with the reply')


DICT_DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const grab = (start) => { const i = page.indexOf(start); return page.slice(i, page.indexOf('\n}\n', i) + 2); };
const logic = page.split('<script id="logic">')[1].split('</script>')[0];
let rec = null, sent = [], toasts = [];
class SR { constructor() { rec = this } start() { this.started = true } stop() { this.onend() } }
const navigator = {language: 'en-US'}, window = {isSecureContext: true};
const ta = {value: 'fix the', focus() {}, setSelectionRange() {}};
const document = {querySelector: s => s === '[data-in]' ? ta : null};
const drafts = {}, store = {set: (k, v) => { drafts[k] = v }, get: k => drafts[k] || ''};
const DRAFT_KEY = k => 'draft:' + k, boxKey = () => 'c3', grow = () => {}, render = () => {};
const toast = t => toasts.push(t), send = () => sent.push(ta.value), TK = {state: ''};
const line = s => { const i = page.indexOf(s); return page.slice(i, page.indexOf('\n', i)) + '\n' };
const micJs = line('const MIC=') + grab('function micWhenFree(') + grab('function micFree(');
eval(logic + 'const DK={rec:null,key:\'\',base:\'\'};const dictWhy=()=>\'\';' + micJs + grab('function dictShow(') + grab('function dictate(') + `
  dictate();
  const listening = !!DK.rec;
  rec.onresult({resultIndex: 0, results: [Object.assign([{transcript: 'merge'}], {isFinal: false})]});
  const interim = ta.value;
  rec.onresult({resultIndex: 0, results: [Object.assign([{transcript: 'merge conflict'}], {isFinal: true})]});
  dictate();
  const after = ta.value;
  ta.value = 'fix the'; dictate();  // B217: final, then interim, then end
  rec.onresult({resultIndex: 0, results: [Object.assign([{transcript: 'merge'}], {isFinal: true})]});
  rec.onresult({resultIndex: 1, results: [Object.assign([{transcript: 'merge'}], {isFinal: true}), Object.assign([{transcript: ' conflict'}], {isFinal: false})]});
  rec.onend();
  console.log(JSON.stringify({listening, interim, after, kept: ta.value, draft: drafts['draft:c3'], stopped: DK.rec === null, sent, toasts}));`);
"""


def test_chat_box_f115(tmp: Path) -> None:
    """F115: the message box has a dictation mic beside attach whose words go into the box to edit (nothing is
    sent), and says why it cannot listen on plain http or without speech recognition; a chat looks like the
    terminal: monospace (the --mono token), the app's terminal colours and a '>' prompt."""
    page = W.PAGE.read_text(encoding='utf-8')
    box = page.split('function box(ph,foot){', 1)[1].split('\n}\n', 1)[0]
    check('data-clip' in box and 'dictButton(dictWhy()' in box and box.index('data-clip') < box.index('dictButton('),
          'the box draws the mic button, right after attach', box[-600:])
    check("if(q('[data-dict]'))return dictate();" in page, 'a tap on it dictates')
    check('.main.term .msgs{font:14px/1.55 var(--mono)' in page and '.main.term .box textarea{font:16px/1.45 var(--mono)}' in page,
          'a chat and its box use the monospace font token (16px: a phone does not zoom)')
    check(".main.term .u::before{content:'>'" in page, "a '>' prompt on your messages in Talk")
    check("main.classList.toggle('term',chatOn)" in page and "fetch('term'" not in page,
          "a chat takes the terminal look with the run app's own colours")
    check('@media (pointer:coarse){.tool{height:40px;min-width:40px}.send{width:40px;height:40px}.box .act{height:40px}}' in page,
          'the box buttons stay touch-sized on a phone')
    if not shutil.which('node'):
        print('  (no node here: the dictation script test is skipped)')
        return
    got = logic_js([['dictProblem', False, True], ['dictProblem', True, False], ['dictProblem', True, True],
                    ['dictButton', '', False, 'MIC'], ['dictButton', '', True, 'MIC'],
                    ['dictButton', 'This browser cannot turn speech into text (Chrome, Edge and Safari can).', False, 'MIC'],
                    ['dictInsert', 'fix the ', ' merge '], ['dictInsert', '', 'hello'], ['dictInsert', 'keep', '']])
    check('https or localhost' in got[0] and 'Type your message instead.' in got[0],
          'plain http: the dictation mic says it needs https', got[0])
    check('cannot turn speech into text' in got[1], 'no speech recognition: the dictation mic says so', got[1])
    eq(got[2], '', 'https with recognition: it dictates')
    check('data-dict' in got[3] and 'class="tool dict"' in got[3] and 'go into the box to edit' in got[3] and 'MIC' in got[3],
          'the mic button says its words go into the box', got[3])
    check('tool dict on' in got[4] and 'Stop dictating' in got[4] and 'aria-pressed="true"' in got[4],
          'while it listens it shows so and stops on a tap', got[4])
    check('dict off' in got[5] and 'title="This browser cannot turn speech into text' in got[5] and 'disabled' not in got[5],
          'one that cannot listen says why in its label and stays tappable (a tap says why)', got[5])
    eq(got[6:9], ['fix the merge', 'hello', 'keep'], 'the words heard go after what the box held')
    (tmp / 'driver.js').write_text(DICT_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs dictate()', r.stderr[-800:])
    d = json.loads(r.stdout or '{}')
    eq((d.get('listening'), d.get('interim'), d.get('after'), d.get('draft'), d.get('stopped')),
       (True, 'fix the merge', 'fix the merge conflict', 'fix the merge conflict', True),
       'dictation fills the box as it hears, keeps it as the draft, and a second tap stops it')
    eq(d.get('kept'), 'fix the merge conflict', 'B217: words heard after a final piece stay when the mic ends')
    eq((d.get('sent'), d.get('toasts')), ([], []), 'nothing is sent: the words wait in the box to edit')


HOLD_DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const grab = (start) => { const i = page.indexOf(start); return page.slice(i, page.indexOf('\n}\n', i) + 2); };
const line = s => { const i = page.indexOf(s); if (i < 0) throw new Error(s); return page.slice(i, page.indexOf('\n', i)) + '\n' };
const logic = page.split('<script id="logic">')[1].split('</script>')[0];
const spoken = [];
const window = {speechSynthesis: {cancel() {}, getVoices: () => [{name: 'Ava', lang: 'en-GB'}], speak(u) { if (u.text) spoken.push(u) }}};
const speechSynthesis = window.speechSynthesis;
class SpeechSynthesisUtterance { constructor(t) { this.text = t } }
let rec = null, starts = 0, sent = [];
class SR { constructor() { rec = this } start() { starts++ } stop() { this.stopped = true; this.onend() } }
const navigator = {language: 'en-US'}, handlers = {};
const document = {hidden: false, addEventListener(t, f) { (handlers[t] = handlers[t] || []).push(f) }};
const fire = (t, e) => (handlers[t] || []).forEach(f => f(e));
const TK = {rec: null, heard: '', state: '', wait: null, said: '', unlocked: false, note: '', playing: '', hold: false, again: false, later: []};
const S = {view: 'talk', thread: null, feeds: {c5: {entries: [{kind: 'you', text: 'hi', id: 'a'}, {kind: 'say', text: 'One **thing**.', id: 'b'}]}}};
const feedOf = n => S.feeds[n].entries, talkName = () => 'c5', micWhy = () => '', toast = () => {}, render = () => {};
const talkDraw = () => {}, talkSend = t => sent.push(t), talkTyping = () => false, voices = () => speechSynthesis.getVoices();
eval(logic + `
let TS = talkSetParse('');
` + grab('function speak(') + line('function hush(') + grab('function playReply(') + line('const MIC=') + grab('function micWhenFree(') + grab('function micFree(') + 'const AU={el:null,got:null,ok:false};' + grab('function shush(') + grab('function unlockAudio(') + grab('function listen(') + grab('function hear(') + grab('function micSent(') + grab('function earEnd(') + grab('function holdLost(') + grab('function micStop(')
  + page.slice(page.indexOf('/* F124: hold to talk'), page.indexOf('/* F124: a swipe right anywhere')) + `
const out = {defaults: TS, parsed: talkSetParse('{"read":false,"voice":"Ava","mic":"hold","auto":true}'), junk: talkSetParse('nope')};
const mic = {target: {closest: s => s === '[data-mic]' ? {} : null}, button: 0};
fire('pointerdown', mic); out.tapStarts = starts;
TS = {...TS, mic: 'hold'};
fire('pointerdown', mic); out.holdStarts = [starts, TK.state];
rec.onresult({resultIndex: 0, results: [Object.assign([{transcript: 'what is running'}], {isFinal: true})]});
out.before = sent.slice(); fire('pointerup', mic); out.holdSent = [sent.slice(), rec.stopped];
// a reply read to its end: auto listen listens again, and one silent turn ends it
TS = {...TS, mic: 'tap', auto: true, voice: 'Ava'}; starts = 0;
speak('Two agents are running.'); out.voice = [spoken[0].voice.name, spoken[0].lang];
spoken[spoken.length - 1].onend(); out.auto = [starts, TK.state];
rec.onend(); out.silent = [starts, TK.state, TK.note];
speak('Stopped early.'); const u = spoken[spoken.length - 1]; hush(); u.onend(); out.stopped = [starts, TK.state];
TS = {...TS, auto: false, read: false}; speak('No more.'); spoken[spoken.length - 1].onend(); out.off = starts;
playReply('b'); out.play = [TK.playing, spoken[spoken.length - 1].text, TK.state];
playReply('b'); out.playStop = TK.playing;
TS = {...TS, mic: 'tap'}; listen(); rec.onresult({resultIndex: 0, results: [Object.assign([{transcript: 'x'}], {isFinal: true})]});
const n0 = sent.length; playReply('b'); out.playOver = [sent.length - n0, TK.rec, TK.playing];
starts = 0; listen(); out.micStops = [starts, TK.playing];
TS = {...TS, mic: 'hold'}; fire('pointerdown', mic); rec.onresult({resultIndex: 0, results: [Object.assign([{transcript: 'auto'}], {isFinal: true})]}); fire('pointerup', mic); out.autoHeld = sent[sent.length - 1];
console.log(JSON.stringify(out));`);
"""


MIC_DRIVER = HOLD_DRIVER.split('let rec = null')[0] + r"""
let live = 0, most = 0, starts = 0, sent = [], recs = [], timers = [], runs = [], now = 1000;
class SR {
  constructor() { recs.push(this) }
  start() { starts++; live++; most = Math.max(most, live) }
  stop() { this.stopped = true }
  abort() { this.aborted = true }
  end() { live--; if (this.onend) this.onend() }
  fail(err, message) { this.onerror({error: err, message}); this.end() }
  say(t) { this.onresult({resultIndex: 0, results: [Object.assign([{transcript: t}], {isFinal: true})]}) }
}
const last = () => recs[recs.length - 1];
const setTimeout = (f, ms) => timers.push({f, ms}), clearTimeout = id => { if (timers[id - 1]) timers[id - 1].f = null };
const tick = ms => { for (const t of timers) if (t.f && t.ms <= ms) { const f = t.f; t.f = null; f() } };
Date.now = () => now;
const navigator = {language: 'en-US'}, handlers = {};
const document = {hidden: false, addEventListener(t, f) { (handlers[t] = handlers[t] || []).push(f) }};
const fire = (t, e) => (handlers[t] || []).forEach(f => f(e));
const TK = {rec: null, heard: '', state: '', note: '', playing: '', hold: false, holdId: null, again: false, ear: null, later: []};
const DK = {rec: null, key: '', base: ''}, I = {stop: '', talk: '', speak: '', mute: '', keys: ''};
const S = {view: 'talk', thread: null};
const ta = {value: ''}, box = {value: ''}; document.querySelector = () => ta; ta.focus = ta.setSelectionRange = () => {};
const micWhy = () => '', dictWhy = () => '', toast = () => {}, voices = () => [], talkTyping = () => false;
const AU = {el: null, got: null, ok: false};  // F158
const boxKey = () => 'c3', DRAFT_KEY = k => k, store = {set() {}}, grow = () => {};
const talkSend = t => { sent.push(t); TK.state = TK.note = '' };
const els = {}, el = () => ({classList: {toggle() {}}, setAttribute(k, v) { this[k] = v }, removeAttribute(k) { delete this[k] }});
let copied = '', sheet = '', RUN_VERSION = '9.9', PAGE_PRINT = 'aaa'; const openSheet = n => { sheet = n };
const $ = k => els[k] = els[k] || el();
let micEl = null;  // a redraw of the mic's markup makes a new element
eval(logic + `
function render() { if (setHTML($('talkmic'), talkMic())) els.mic = micEl = {...el(), setPointerCapture(id) { this.cap = id }}; talkDraw() }
let TS = talkSetParse('');
` + line('const MIC=') + line('function setHTML(') + line('const talkMic=') + ['talkDraw', 'micWhenFree', 'micFree', 'dictShow', 'dictate', 'shush', 'unlockAudio', 'speak', 'listen', 'hear', 'micSent', 'keptSend', 'earEnd', 'holdLost', 'micStop', 'micPage', 'async function micCopy', 'async function micCopyText'].map(f => grab((f.startsWith('async') ? f : 'function ' + f) + '(')).join('')
  + page.slice(page.indexOf('/* B162: the mic report\'s pointer'), page.indexOf('/* F124: a swipe right anywhere')) + `
const out = {}; render();
// two aborts: one retry by itself, then the words
listen(); now += 300; last().fail('aborted'); out.retryWaits = [starts, TK.state];
tick(250); out.retried = [starts, TK.state]; now += 400; last().fail('aborted'); tick(250);
out.twice = [starts, TK.state, TK.note];
// an abort, then words
listen(); last().fail('aborted'); tick(250); last().say('hello'); listen(); last().end(); out.sent = sent.splice(0);
// words, then an abort: they go out, no retry; no retry for a stop by hand, or away from Talk
starts = 0; listen(); last().say('kept'); last().fail('aborted'); tick(250); out.kept = [starts, sent.splice(0)];
starts = 0; listen(); listen(); last().fail('aborted'); tick(250); out.byHand = [starts, TK.note];
starts = 0; listen(); S.view = 'home'; last().fail('aborted'); tick(250); out.away = starts; S.view = 'talk';
starts = 0; listen(); last().fail('aborted'); listen(); tick(250); out.stopInWait = [starts, TK.state];
// a start waits for the end of the one before
TS.read = true; starts = 0; listen(); const a = last(); speak('A reply.', 'k'); out.dropped = [TK.state, a.stopped];
listen(); out.waits = [starts, TK.state]; a.say('old'); a.end(); out.afterEnd = [starts, TK.state, sent.splice(0)];
last().end();
// ended while it waits: the end of the old one starts nothing
listen(); const b = last(); speak('A reply.', 'k'); listen(); listen(); starts = 0; b.end(); out.waitOff = [starts, TK.state];
// dictation still ending
starts = 0; dictate(); const d = last(); listen(); out.dict = [starts, d.stopped]; d.end(); out.dictEnd = [starts, DK.rec, TK.state]; last().end();
// an end that never comes
listen(); const c = last(); speak('A reply.', 'k'); listen(); starts = 0; runs = timers.filter(t => t.f && t.ms === 1500); runs.forEach(t => { const f = t.f; t.f = null; f() });
out.stuckWaits = [starts, c.aborted]; c.end(); out.stuck = [starts, c.aborted, TK.state]; last().end();
out.most = most;
// not even after the abort: taken for gone
listen(); const g = last(); speak('A reply.', 'k'); listen(); starts = 0; tick(1500); tick(1500); out.gone = [starts, g.aborted, TK.state]; live--; last().end(); most = 0;
// a hold: survives a redraw and a cancel; the finger lifting sends
TS.mic = 'hold'; render(); const held = micEl, at = {target: {closest: s => s === '[data-mic]' ? held : null}, button: 0, pointerId: 7};
starts = 0; fire('pointerdown', at); render(); const h = last();
const away = {closest: () => null};
fire('pointercancel', {pointerId: 7, pointerType: 'touch'}); fire('touchcancel', {target: away}); out.held = [starts, TK.hold, !!h.stopped, micEl === held, held.cap, held.className];
fire('pointerup', {pointerId: 8}); fire('touchend', {target: away}); out.other = !!h.stopped;
h.say('still here'); fire('touchend', at); out.lifted = [TK.hold, h.stopped]; h.end(); out.heldSent = sent.splice(0);
// held again before the end: one listen, both parts
fire('pointerdown', at); last().say('first'); const p1 = last(); fire('pointerup', at); fire('pointerdown', at);
p1.end(); out.more = [TK.state, sent.length, last() !== p1]; last().say('second'); fire('pointerup', at); last().end(); out.joined = sent.splice(0);
// a touch the system took: the mic goes on by itself
fire('pointerdown', at); fire('pointercancel', {...at, pointerType: 'touch'}); fire('touchcancel', at); out.taken =[TK.hold, !!last().stopped]; last().say('done'); last().end(); tick(2000); last().end(); out.takenSent = sent.splice(0);
fire('pointerdown', at); fire('pointercancel', {...at, pointerType: 'pen'}); out.pen = [TK.hold, !!last().stopped]; last().end();
// an abort while held is retried, one once let go is not
starts = 0; fire('pointerdown', at); last().fail('aborted'); tick(250); out.holdRetry = starts; now += 100; last().fail('aborted'); out.holdNote = TK.note; fire('pointerup', at);
starts = 0; fire('pointerdown', at); last().fail('aborted'); fire('pointerup', at); tick(250); out.letGo = [starts, TK.state];
out.mostAll = most;
// the mic report: the trail from press to end, who stopped it, and the words on the line
const when = {...at, pointerType: 'touch'}, says = () => els.talkline.textContent;
fire('pointerdown', when); out.starting = says(); last().onstart(); out.begun = says(); now += 700; last().onaudiostart(); out.live = says();
now += 900; fire('pointerup', when); fire('touchend', when); last().fail('aborted', 'No speech detected'); out.reason = TK.note;
fire('lostpointercapture', when); out.button = els.micrep.hidden;
out.trail = TK.report.ev;
TK.hold = false; fire('pointerdown', when); out.cleared = els.micrep.hidden; last().onstart(); fire('pointerup', when); last().end(); out.early = TK.note;
// two fingers on the mic: one lifting is not the hold's end
fire('pointerdown', when); fire('touchend', {...at, targetTouches: [1]}); out.two = !!last().stopped; TK.hold = false; last().end();
// a stop whose end never comes still ends the listen
TS.mic = 'tap'; TK.hold = false; listen(); last().onaudiostart(); const z = last(); listen(); tick(5000); tick(1500); tick(1500); out.noEnd = [TK.state, !!z.aborted, TK.report && TK.report.ev.some(x => / no end came/.test(x))]; live--;
// words heard: counted, never in the trail
listen(); last().say('secret'); out.noWords = [TK.trail.ev.join(' '), TK.trail === TK.report]; listen(); last().end(); out.afterWords = [TK.report, els.micrep.hidden];
// a hold is a hold on every device, iOS too: a press listens, the release sends, the click after it does nothing
const q = s => s === '[data-mic]', e = {detail: 1}, click = new Function('q', 'e', 'TS', 'TK', 'micLog', 'listen', line("  if(q('[data-mic]'))"));
for (const [k, ua, touch] of [['iphone', 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X)', 5], ['ipad', 'Mozilla/5.0 (Macintosh; Intel Mac OS X)', 5], ['mac', 'Mozilla/5.0 (Macintosh; Intel Mac OS X)', 0], ['android', 'Mozilla/5.0 (Linux; Android 16)', 5]]) {
  TS.mic = 'hold'; navigator.userAgent = ua; navigator.maxTouchPoints = touch; TK.hold = false; TK.state = TK.note = ''; TK.ear = null; render(); starts = 0;
  const rest = says(); fire('pointerdown', when); const o = out[k] = [rest, starts, els.mic.className, says()];
  last().say('by ' + k); fire('pointerup', when); o.push(!!last().stopped); last().end(); click(q, e, TS, TK, micLog, listen); o.push(starts, sent.pop(), TK.state);
}
// B162a1: silence never ends a hold: no-speech, an end by itself, iOS's abort for silence; words before and after are one message
const held2 = () => [starts, TK.state, TK.hold, TK.ear && TK.ear.tries];
TS.mic = 'hold'; TK.note = ''; render(); starts = 0; most = live = 0; sent.length = 0; fire('pointerdown', when); last().onaudiostart(); now += 5000; last().fail('no-speech'); out.quiet = held2();
last().onaudiostart(); now += 5000; last().end(); out.ownEnd = held2();
last().say('one'); now += 2000; last().end(); out.wordsKept = [...held2(), says(), sent.length];
last().onaudiostart(); now += 300; last().fail('aborted', 'No speech detected'); out.shortWait = starts; tick(250); out.iosQuiet = held2();
now += 3000; last().fail('aborted', 'No speech detected'); out.iosNoStart = held2();
last().fail('aborted'); tick(250); out.oneFail = held2();
last().say('two'); fire('pointerup', when); last().end(); out.holdWords = [sent.splice(0), TK.state, most];
// nothing said: a release sends nothing, during a listen and while the next one waits
starts = 0; fire('pointerdown', when); last().onaudiostart(); now += 5000; last().fail('no-speech'); fire('pointerup', when); last().end(); tick(250); out.holdNone = [starts, TK.state, sent.length, TK.note, says() === TK.note];
starts = 0; fire('pointerdown', when); last().onaudiostart(); now += 300; last().end(); fire('pointerup', when); tick(250); out.holdWait = [starts, TK.state, sent.length];
// a real failure ends it, and the words so far go out
for (const err of ['not-allowed', 'service-not-allowed', 'audio-capture']) { starts = 0; fire('pointerdown', when); now += 2000; last().fail(err); tick(250); (out.real = out.real || []).push([starts, TK.state, sent.length]); fire('pointerup', when) }
starts = 0; fire('pointerdown', when); last().say('kept'); now += 2000; last().end(); last().fail('audio-capture'); tick(250); out.realWords = [starts, TK.state, sent.splice(0)]; fire('pointerup', when); TK.kept = '';
// a listen that is not held still ends at a silence
starts = 0; listen(); now += 5000; last().fail('no-speech'); tick(250); out.notHeld = [starts, TK.state];
// B216: the end of what was said. hears(): a whole results list, each [words, final]
const hears = (...l) => last().onresult({resultIndex: l.length - 1, results: l.map(([transcript, isFinal]) => Object.assign([{transcript}], {isFinal}))});
const ended = () => TK.trail.ev[TK.trail.ev.length - 1].replace(/^\\d+ ms /, '');
const cut = out.b216 = {}; sent.length = 0; most = live = 0; TK.hold = false;
// final, then interim, then the end: by a stop in Tap, by a release; two interims, an empty final
TS.mic = 'tap'; listen(); hears(['so do a', true], [' full one', false]); cut.line = says(); listen(); last().end(); cut.interim = [sent.splice(0), ended()];
TS.mic = 'hold'; fire('pointerdown', when); hears(['so do a', true], ['full one', false]); fire('pointerup', when); last().fail('aborted'); cut.release = [sent.splice(0), TK.trail.ev.some(x => x.endsWith('sent 16 letters, ended by pointerup'))];
fire('pointerdown', when); hears(['so do', false], [' a full', false]); hears(['', true], [' a full', false]); fire('pointerup', when); last().end(); cut.blank = sent.splice(0);
// words after the release, before its end
fire('pointerdown', when); hears(['so do', false]); fire('pointerup', when); hears(['so do a full', true]); last().end(); cut.late = sent.splice(0);
// held: after words the next one starts at once, however short, with nothing lost between
starts = 0; fire('pointerdown', when); hears(['so', true], [' do', false]); now += 300; last().end(); cut.gap = [starts, sent.length]; hears(['a full', false]); fire('pointerup', when); last().end(); cut.gapSent = sent.splice(0);
// a recognizer that cannot be made again: the words so far go out
fire('pointerdown', when); hears(['kept', false]); { const S0 = SR; SR = class { constructor() { throw new Error('none') } }; last().end(); SR = S0 } cut.none = [sent.splice(0), TK.state, ended()]; fire('pointerup', when); TK.kept = '';
// B216a1: a hold with a long pause. k(): words, the silence, the recognizer's end; its restart runs
const hp = out.b216a1 = {}, keptNow = () => [sent.splice(0), TK.kept || '', TK.state, els.keptsend.hidden];
const k = () => { TK.hold = false; TK.state = ''; TK.kept = ''; starts = 0; fire('pointerdown', when); last().onaudiostart(); hears(['Is there a', true]); now += 4000; last().end() };
// the restart hears: all of it, one message; the line says when the mic is on again
k(); hp.off = says(); last().onaudiostart(); hp.on = says(); now += 3000; hears(['way to do it', true]); hp.line = says(); fire('pointerup', when); last().end(); hp.whole = keptNow();
// it starts and hears nothing: kept, said, not sent; the next hold goes on from it
k(); last().onaudiostart(); now += 3300; fire('pointerup', when); last().fail('aborted', 'No speech detected'); hp.deaf = [...keptNow(), says(), ended(), TK.report === TK.trail, TK.note.includes('Is there')];
fire('pointerdown', when); hp.goOn = says(); last().onaudiostart(); now += 2000; fire('pointerup', when); last().end(); hp.again = keptNow();
fire('pointerdown', when); hears(['way', true]); fire('pointerup', when); last().end(); hp.joined = keptNow();
// Send as it is; not while it listens
k(); now += 3300; fire('pointerup', when); last().end(); fire('pointerdown', when); keptSend(); hp.busy = sent.length; fire('pointerup', when); last().end(); keptSend(); render(); hp.asIs = keptNow();
// let go at once after the words, with nothing begun: sent; speech begun with no words: kept
k(); now += 400; fire('pointerup', when); last().end(); hp.soon = keptNow();
k(); last().onspeechstart(); now += 400; fire('pointerup', when); last().end(); hp.spoke = keptNow();
// silent restarts one after another, and a release between two of them
k(); now += 5000; last().fail('no-speech'); now += 300; last().end(); fire('pointerup', when); hp.between = keptNow(); tick(250);
// words after a release, before the end
k(); now += 3000; fire('pointerup', when); hears(['way', true]); last().end(); hp.late = keptNow();
// the restart is aborted twice, the button still down
k(); now += 100; last().fail('aborted'); tick(250); hp.one = [starts, TK.state]; last().fail('aborted'); hp.two = [starts, ...keptNow()]; fire('pointerup', when); hp.after = keptNow();
// rec.start() throws: once more, then kept
const start0 = SR.prototype.start, bad = n => { SR.prototype.start = function () { if (n-- > 0) throw new Error('busy'); start0.call(this) } };
bad(0); k(); hears(['x', true]); now += 1000; bad(1); last().end(); hp.throw1 = [TK.state, sent.length]; tick(250); hears(['y', true]); fire('pointerup', when); last().end(); hp.thrown = keptNow();
bad(0); k(); hears(['x', true]); now += 1000; bad(2); last().end(); tick(250); hp.throw2 = keptNow(); bad(0); fire('pointerup', when);
// Tap: a restart refused in the wait is tried again, and its silence still sends
TS.mic = 'tap'; TK.hold = false; TK.kept = ''; listen(); hears(['so', true]); bad(1); last().end(); hp.tapThrow = [TK.state, sent.length]; tick(250); hears(['on', true]); listen(); last().end(); hp.tapOn = keptNow(); bad(0);
// Tap: twice refused, kept; a restart that hears silence sends, as silence is its end
listen(); hears(['so', true]); bad(2); last().end(); tick(250); hp.tapFail = keptNow(); bad(0); TK.kept = '';
listen(); hears(['so', true]); last().end(); last().onaudiostart(); now += 2000; tick(2000); last().end(); hp.tapQuiet = keptNow();
// a hold let go at once, its restart failed; a note beside kept words
TS.mic = 'hold'; render(); k(); now += 300; last().fail('aborted'); fire('pointerup', when); hp.failSoon = keptNow(); TK.note = 'Other.'; render(); hp.note = says();
TS.mic = 'tap'; TK.note = TK.kept = '';
// Tap goes on from kept words, an abort first tried again; nothing heard keeps them
TK.kept = 'Is there a'; starts = 0; listen(); last().fail('aborted'); tick(250); hp.tapRetry = starts; listen(); last().end(); hp.tapKept = keptNow(); TK.kept = '';
// one recognizer, continuous: several finals and a long silence, released with the last words not final: all, once
const hc = out.cont = {}, press = () => { TK.hold = false; TK.state = ''; TK.kept = TK.note = ''; starts = 0; sent.length = 0; fire('pointerdown', when); last().onaudiostart() };
const lets = () => { fire('pointerup', when); last().end(); return sent.splice(0) };
TS.mic = 'hold'; render(); press(); hc.one = [last().continuous, TK.trail.ev.some(x => x.endsWith(' try 1, continuous'))];
hears(['Is there a', true]); now += 10000; hears(['Is there a', true], ['way to', false]); now += 900; hears(['Is there a', true], ['way to do it', true], ['please', false]);
fire('pointerup', when); hears(['Is there a', true], ['way to do it', true], ['please now', true]); last().end(); hc.all = [sent.splice(0), starts, TK.kept, TK.state];
// a list that repeats the earlier text, drops it, or begins anew after a silence
press(); hears(['Is there a', true], ['Is there a way', true], ['Is there a way, to do it', false]); hc.repeat = lets();
press(); hears(['Is there a', true], ['is there a', true]); hc.twice = lets();
press(); hears(['Is there a', true]); now += 3000; hears(['way to do it', false]); hears(['Is there a', true], ['way to do it', true]); hc.dropped = lets();
press(); hears(['Is there a', false]); now += 3000; hears(['way', false]); hears(['way to do it', false]); hc.anew = lets();
press(); hears(['Is there a', false]); now += 3000; hears(['way', false]); hears(['Is there a way', true]); hc.whole = lets();
press(); hears(['their is', false]); now += 500; hears(['There is a', true]); hc.better = lets();
press(); hears(['so', true], ['what', false]); hears(['so what', true]); hc.merged = lets();
press(); hears(['no', true], ['no', true]); hears(); hc.own = lets();
press(); hears(['thank you', true], ['thank you', true]); hc.own.push(...lets());
press(); hears(['so do', true], ['what now', true]); hears(['so do what now', true]); hc.more = lets();
press(); hears(['Is there a', false]); now += 3000; hears(['a way to do it', true]); hc.more.push(...lets());
press(); hears(['Is there a', false]); now += 3000; hears(['is it', false]); hc.more.push(...lets());
press(); hears(['one two', true], ['three four', true], ['five six', true], ['three four five six seven', true]); hc.more.push(...lets());
press(); hears(['a b', true], ['c d', false]); hears(['a b', true]); hc.more.push(...lets());
// Recorded, held again before its end: no such line, as it says nothing of speech
{ const S0 = SR; SR = class extends S0 { constructor() { super(); this.recorded = true } }; press(); hc.rec = [!!last().continuous]; fire('pointerup', when); fire('pointerdown', when); last().end(); last().onaudiostart(); tick(3000); hc.rec.push(says(), !!last().continuous); lets(); SR = S0 }
// ends by itself while held: started again, continuous too, the line says the mic is off until it is on
press(); hears(['Is there a', true]); last().end(); hc.off = [starts, last().continuous, says()]; last().onaudiostart(); hc.on = says(); hears(['way', true]); hc.back = [says(), lets()];
// off in the wait between two as well, and with no words yet
press(); last().fail('no-speech'); hc.wait = says(); tick(250); hc.waited = says(); last().onaudiostart(); hc.up = says(); lets();
// the restart hears nothing: said while held, and again not once speech begins
press(); tick(3000); hc.first = says(); hears(['Is there a', true]); last().end(); last().onaudiostart(); hc.yet = says(); tick(3000); hc.deaf = [says(), TK.trail.ev.some(x => x.endsWith('said on the line'))];
last().onspeechstart(); hc.speech = says(); now += 4000; hc.kept = [lets(), TK.kept];
press(); hears(['so', true]); last().end(); last().onaudiostart(); tick(3000); hears(['on', true]); hc.heard = [says(), lets()];
press(); hears(['so', true]); last().end(); last().onaudiostart(); last().onspeechstart(); tick(3000); hc.fine = says(); lets();
press(); last().end(); tick(250); last().onaudiostart(); tick(3000); hc.noWords = says(); lets();
// a touch the system took: it stops at a silence; held again, it does not
press(); hears(['so', true]); fire('touchcancel', when); tick(5000); hc.lost = [!!last().stopped]; last().end(); hc.lost.push(sent.splice(0));
press(); hears(['so', true]); fire('touchcancel', when); fire('pointerdown', when); tick(5000); hc.held = [!!last().stopped, lets()];
press(); fire('touchcancel', when); tick(5000); hc.lostNone = !!last().stopped; last().end();
// Tap and auto listen are not continuous
TS.mic = 'tap'; TK.hold = false; TK.state = ''; TK.kept = ''; listen(); hc.tap = [last().continuous, TK.trail.ev.some(x => x.endsWith(' try 1, not continuous'))]; listen(); last().end();
TK.again = true; listen(); hc.auto = last().continuous; last().end(); TK.note = TK.kept = ''; sent.length = 0;
hp.most = most; sent.length = 0; render();
// Tap: a pause does not send; more words, then a silence, and it does
TS.mic = 'tap'; starts = 0; listen(); hears(['so do a', true]); now += 3000; last().end(); cut.pause = [starts, sent.length, TK.state, says()];
now += 1500; hears(['full one', false]); tick(2000); cut.goesOn = [sent.length, !!last().stopped]; hears(['full one', true]); last().end(); cut.again = [starts, sent.length];
now += 2000; tick(2000); cut.silence = !!last().stopped; last().end(); cut.pauseSent = [sent.splice(0), TK.state, ended(), starts];
// speech begun in the wait makes it longer, once
starts = 0; listen(); hears(['so', true]); last().end(); now += 1500; last().onspeechstart(); now += 1000; last().fail('no-speech'); cut.speech = [starts, sent.length];
last().onspeechstart(); now += 1100; last().fail('no-speech'); cut.speechEnd = [starts, sent.splice(0), ended()]; TK.kept = '';
// results that come back empty unsay nothing
listen(); hears(['so do', false]); hears(['', false]); last().onresult({resultIndex: 0, results: []}); listen(); last().end(); cut.empty = sent.splice(0);
// the wait's recognizer ends early, as iOS does: on again until the wait is over, and no longer
starts = 0; listen(); hears(['so', true]); now += 3000; last().end(); now += 300; last().fail('aborted', 'No speech detected'); tick(250); cut.early = [starts, sent.length];
now += 400; last().fail('aborted'); tick(250); cut.failed = [starts, sent.length]; now += 1300; last().end(); cut.over = [starts, sent.splice(0)];
// the wait is over while no recognizer runs
listen(); hears(['so', true]); last().end(); now += 900; last().fail('aborted'); tick(2000); cut.between = [sent.splice(0), TK.state]; TK.kept = '';
// a tap sends at once: in the first listen, and in the wait
listen(); hears(['so', true]); starts = 0; listen(); last().end(); cut.tap = [starts, sent.splice(0)];
listen(); hears(['so', true]); last().end(); listen(); last().end(); cut.tapWait = [sent.splice(0), ended()]; tick(2000); cut.once = sent.length;
// auto listen sends at a silence; a real failure in the wait sends too; left Talk: no wait
starts = 0; TK.again = true; listen(); hears(['yes', true]); last().end(); cut.auto = [starts, sent.splice(0), ended()];
listen(); hears(['so', true]); last().end(); last().fail('network'); cut.network = [sent.splice(0), ended()]; TK.kept = '';
starts = 0; listen(); hears(['so', true]); S.view = 'home'; last().end(); S.view = 'talk'; cut.left = [starts, sent.splice(0)];
// the report: growing results are one line, the line that says what ended it is in a full one too, and no words are
listen(); for (const w of ['s', 'se', 'sec', 'secret']) hears([w, false]); cut.grow = TK.trail.ev.filter(x => /result/.test(x)).length;
for (let i = 0; i < 130; i++) micLog('x'); listen(); last().end(); cut.full = [ended(), TK.trail.ev.join().includes('sec')]; sent.length = 0; cut.most = most; TS.mic = 'hold';
navigator.userAgent = 'UA iPhone'; TK.hold = false; TK.report = TK.trail; let holdReport = '';
navigator.clipboard = {writeText: async t => { holdReport = t }};
S.snap = {page: 'aaa'}; out.pages = [micPage()]; PAGE_PRINT = '/' + '*PAGE_PRINT*/'; out.pages.push(micPage()); PAGE_PRINT = 'aaa'; S.snap = {}; out.pages.push(micPage());
S.snap = {page: 'bbb'}; micCopy().then(() => { out.holdReport = holdReport });
TS.mic = 'tap'; TK.state = ''; render();
TK.trail = null; for (let i = 0; i < 130; i++) micLog('x'); out.cap = micReport(TK.trail, ['h']).split('\n').slice(-1)[0];
// the copy, and what shows where it is refused
TK.report = TK.trail; TK.note = 'the note'; navigator.userAgent = 'UA'; navigator.clipboard = {writeText: async t => { copied = t }};
micCopy().then(() => { out.copied = copied.split('\n').slice(0, 5); navigator.clipboard = {writeText: async () => { throw new Error('no') }}; return micCopy() })
  .then(() => { out.sheet = [sheet, S.out.title, S.out.text === copied]; console.log(JSON.stringify(out)) });`.replaceAll("split('\n')", "split('\\n')"));
"""


def test_mic_aborted_b162(tmp: Path) -> None:
    """B162: one recognizer at a time (a start waits for the old one's end), one retry on an abort before any words and
    then plain words with the mode and the time, and a hold that survives a redraw and a pointercancel."""
    css = W.PAGE.read_text(encoding='utf-8').split('<style>', 1)[1].split('</style>', 1)[0]
    check('.mic.hold{touch-action:none}' in css, 'a held mic is no scroll, zoom or swipe')
    if not shutil.which('node'):
        print('  (no node here: the mic script test is skipped)')
        return
    (tmp / 'driver.js').write_text(MIC_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs the mic', r.stderr[-900:])
    got = json.loads(r.stdout or '{}')
    words = 'The mic was cut off before it heard anything. Stop any other app that uses sound or the mic, then try again. (aborted, '
    eq((got.get('retryWaits'), got.get('retried')), ([1, 'listening'], [2, 'listening']), 'aborted before any words: one retry')
    eq(got.get('twice'), [2, '', words + 'tap, after 0.4 s, 2 tries)'], 'aborted twice: what to try, with mode and time')
    eq(got.get('sent'), ['hello'], 'the retry hears')
    eq(got.get('kept'), [1, ['kept']], 'words before the abort are sent, with no retry')
    eq(got.get('byHand'), [1, 'The mic was stopped before it was on. Allow it if the browser asks, wait until this line says Listening…, then speak. (aborted, tap, after 0.0 s)'],
       'stopped by hand: no retry')
    eq(got.get('away'), 1, 'no retry once Talk is left')
    eq(got.get('stopInWait'), [1, ''], 'a tap before the retry ends the listen')
    eq(got.get('dropped'), ['', True], "a play button stops the mic")
    eq(got.get('waits'), [1, 'listening'], 'a start waits while the old one ends')
    eq(got.get('afterEnd'), [2, 'listening', []], 'and starts at its onend; its dropped words are not sent')
    eq(got.get('waitOff'), [0, ''], 'a start called off while it waits never starts')
    eq((got.get('dict'), got.get('dictEnd')), ([1, True], [2, None, 'listening']), 'it waits for dictation too')
    eq((got.get('stuckWaits'), got.get('stuck')), ([0, True], [1, True, 'listening']), 'one whose end is late is aborted, and that end still waited for')
    eq(got.get('gone'), [1, True, 'listening'], 'with no end after the abort either, the next starts all the same')
    eq(got.get('pen'), [False, False], 'a cancelled pen leaves no hold behind')
    eq((got.get('most'), got.get('mostAll')), (1, 1), 'never two recognizers')
    eq(got.get('held'), [1, True, False, True, 7, 'mic hold on'], 'a hold survives a redraw and a cancel, its button captured and kept')
    eq(got.get('other'), False, 'another finger does not end it')
    eq((got.get('lifted'), got.get('heldSent')), ([False, True], ['still here']), 'the finger lifting sends')
    eq((got.get('more'), got.get('joined')), (['listening', 0, True], ['first second']), 'held again before the end: one message')
    eq((got.get('taken'), got.get('takenSent')), ([False, False], ['done']), 'a touch the system took: it goes on until a silence')
    eq((got.get('holdRetry'), got.get('holdNote')), (2, words + 'hold, after 0.1 s, 2 tries)'), 'an abort while held is retried')
    eq(got.get('letGo'), [1, ''], 'let go before the retry: none')
    eq((got.get('starting'), got.get('begun'), got.get('live')), ('Starting the mic…', 'Starting the mic…', 'Listening…'), 'Listening only once the mic takes sound')
    eq(got.get('reason'), 'The mic was on, but no sound reached it. Type your message instead, or open Talk settings, run Mic test… and copy its report. '
       '(aborted: No speech detected, hold, after 1.6 s)', "the note has the error's own message")
    eq(got.get('trail'), ['0 ms pointerdown touch id 7', '0 ms listen hold', '0 ms try 1, continuous', '0 ms start', '700 ms audiostart', '1600 ms pointerup touch id 7',
                          '1600 ms stop by pointerup', '1600 ms touchend touch id 7', '1600 ms error aborted: No speech detected', '1600 ms end',
                          '1600 ms lostpointercapture touch id 7'], 'the mic report: each event with its ms, and who stopped it')
    eq((got.get('button'), got.get('cleared')), (False, True), 'the copy button shows with the note, and goes with the next listen')
    eq(got.get('early'), 'The mic was stopped before it was on. Allow it if the browser asks, wait until this line says Listening…, then speak. (hold, after 0.0 s)', 'let go before any sound')
    eq(got.get('two'), False, 'one of two fingers lifting is not the end')
    eq(got.get('noEnd'), ['', True, True], 'a stop with no end still ends the listen, and the report says so')
    check('result, 6 letters, final' in got['noWords'][0] and 'secret' not in got['noWords'][0], 'words are counted, not kept', str(got['noWords']))
    eq(got.get('afterWords'), ['', True], 'words heard: no report button')
    for k in ('iphone', 'ipad', 'mac', 'android'):
        eq(got.get(k), ['Hold to talk', 1, 'mic hold on', 'Starting the mic…', True, 1, f'by {k}', ''], f'{k}: a hold is a hold')
    eq((got.get('quiet'), got.get('ownEnd')), ([2, 'listening', True, 2], [3, 'listening', True, 3]), 'B162a1: no-speech and its own end: the hold listens on')
    eq(got.get('wordsKept'), [4, 'listening', True, 4, 'one … The mic is off, wait until it is on again', 0], 'words heard stay on the line, unsent')
    eq((got.get('shortWait'), got.get('iosQuiet')), (4, [5, 'listening', True, 5]), "iOS's abort for silence: on again, after a wait when it was short")
    eq((got.get('iosNoStart'), got.get('oneFail')), ([6, 'listening', True, 6], [7, 'listening', True, 7]), 'the message alone says silence; one failed start is tried again')
    eq(got.get('holdWords'), [['one two'], '', 1], 'release sends all the words; never two recognizers')
    eq(got.get('holdNone', [])[:3] + got.get('holdNone', [])[4:], [2, '', 0, True], 'release with none sends nothing')
    check('Heard nothing' in got['holdNone'][3], 'and the line says so, not that the mic was never on', got['holdNone'][3])
    eq(got.get('holdWait'), [1, '', 0], 'released before the next start: none')
    eq(got.get('real'), [[1, '', 0]] * 3, 'permission refused or no mic ends it')
    eq(got.get('realWords'), [2, '', []], 'B216a1: and the words before it are not sent as if whole')
    eq(got.get('notHeld'), [1, ''], 'a listen not held ends at a silence')
    b = got.get('b216') or {}
    eq(b.get('line'), 'so do a full one', 'B216: shown as heard')
    eq(b.get('interim'), [['so do a full one'], 'sent 16 letters, ended by a tap'], 'is sent, final or not')
    eq(b.get('release'), [['so do a full one'], True], 'let go, with an abort, the same')
    eq((b.get('blank'), b.get('late')), (['so do a full'], ['so do a full']), 'an empty final unsays nothing; words after the release count')
    eq((b.get('gap'), b.get('gapSent')), ([2, 0], ['so do a full']), 'held: on again at once after words')
    eq(b.get('none'), [[], '', 'kept 4 letters, not sent: nothing heard after them, ended by no recognizer'], 'no recognizer: the words so far are kept')
    g, K = got.get('b216a1') or {}, 'Is there a'
    kept = [[], K, '', False]
    eq((g.get('off'), g.get('on'), g.get('line')), (K + ' … The mic is off, wait until it is on again', K + ' … Listening…', K + ' way to do it'), 'B216a1: the line says when the mic is on again')
    eq(g.get('whole'), [[K + ' way to do it'], '', '', True], 'a pause in a hold: all of it is sent')
    eq(g.get('deaf'), [*kept, f'“{K}” Not sent: nothing was heard after these words. Hold to go on from them, or send them as they are.',
                       'kept 10 letters, not sent: nothing heard after them, ended by pointerup', True, False], 'a restart that hears nothing: said, not sent; no words in the report')
    eq((g.get('goOn'), g.get('again'), g.get('joined')), (K + ' … Starting the mic…', kept, [[K + ' way'], '', '', True]), 'the next hold goes on from the words')
    eq((g.get('busy'), g.get('asIs')), (0, [[K], '', '', True]), 'Send as it is')
    eq(g.get('soon'), [[K], '', '', True], 'let go right after the words: sent')
    eq((g.get('spoke'), g.get('between'), g.get('late')), (kept, kept, [[K + ' way'], '', '', True]), 'speech with no words, a release between two restarts; late words count')
    eq((g.get('one'), g.get('two'), g.get('after')), ([3, 'listening'], [3, *kept], kept), 'a restart aborted twice: kept')
    eq((g.get('throw1'), g.get('thrown')), (['listening', 0], [[K + ' x y'], '', '', True]), 'a start that throws is tried again')
    eq(g.get('throw2'), [[], K + ' x', '', False], 'twice: kept')
    eq((g.get('tapThrow'), g.get('tapOn')), (['listening', 0], [['so on'], '', '', True]), 'Tap: the same')
    eq((g.get('tapFail'), g.get('tapQuiet')), ([[], 'so', '', False], [['so'], '', '', True]), 'Tap: a failed restart keeps, silence sends')
    eq((g.get('failSoon'), g.get('note')), (kept, f'“{K}” Not sent: nothing was heard after these words. Hold to go on from them, or send them as they are. Other.'), 'a failed restart keeps however soon; another note does not hide why')
    eq((g.get('tapRetry'), g.get('tapKept'), g.get('most')), (2, kept, 1), 'Tap goes on from kept words')
    c, OFF, DEAF = got.get('cont') or {}, 'The mic is off, wait until it is on again', 'Nothing is heard. Let go and press again'
    eq((c.get('one'), c.get('tap'), c.get('auto')), ([True, True], [False, True], False), 'a Hold alone is continuous; the report says which')
    eq(c.get('all'), [['Is there a way to do it please now'], 1, '', ''], 'finals and a long silence in one recognizer: all words, once')
    eq((c.get('repeat'), c.get('twice'), c.get('dropped')), ([K + ' way, to do it'], ['is there a'], [K + ' way to do it']), 'text that comes again, or goes, is there once')
    eq((c.get('anew'), c.get('whole')), ([K + ' way to do it'], [K + ' way']), 'a piece begun anew after a silence loses nothing')
    eq((c.get('better'), c.get('merged'), c.get('own')), (['There is a'], ['so what'], ['no no', 'thank you thank you']), 'a better version takes the place; a word or two said twice stay')
    eq(c.get('more'), ['so do what now', 'Is there a a way to do it', 'Is there a is it', 'one two three four five six seven', 'a b c d'], 'finals made one, a new piece that shares a word, part repeated, a piece gone')
    eq(c.get('rec'), [False, 'Listening…', False], 'Recorded stays as it is')
    eq((c.get('off'), c.get('on'), c.get('back')), ([2, True, f'{K} … {OFF}'], f'{K} … Listening…', [K + ' way', [K + ' way']]), 'its own end while held: again, and the line says the mic is off')
    eq((c.get('wait'), c.get('waited'), c.get('up')), (OFF, OFF, 'Listening…'), 'off between two as well')
    eq((c.get('first'), c.get('yet'), c.get('deaf')), ('Listening…', f'{K} … Listening…', [f'{K} … {DEAF}, these words are kept', True]), 'a restart that hears nothing: said while held')
    eq((c.get('speech'), c.get('kept')), (f'{K} … Listening…', [[], K]), 'not once speech begins; words kept')
    eq((c.get('heard'), c.get('fine'), c.get('noWords')), (['so on', ['so on']], 'so … Listening…', DEAF), 'nor once heard; no words, none kept')
    eq((c.get('lost'), c.get('held'), c.get('lostNone')), ([True, ['so']], [False, ['so']], True), 'a touch the system took stops at a silence')
    eq((b.get('pause'), b.get('goesOn'), b.get('again')), ([2, 0, 'listening', 'so do a'], [0, False], [3, 0]), 'Tap: a pause listens on')
    eq((b.get('silence'), b.get('pauseSent')), (True, [['so do a full one'], '', 'sent 16 letters, ended by a pause', 3]), 'and a silence of 2 s sends one message')
    eq((b.get('speech'), b.get('speechEnd')), ([3, 0], [3, [], 'kept 2 letters, not sent: nothing heard after them, ended by error no-speech']), 'speech begun in the wait makes it longer, once; with no words, the first are kept')
    eq(b.get('empty'), ['so do'], 'empty results unsay nothing')
    eq((b.get('early'), b.get('failed'), b.get('over')), ([3, 0], [4, 0], [4, ['so']]), 'a recognizer that ends early does not end the wait, nor outlast it')
    eq(b.get('between'), [[], ''], 'a restart that failed: kept')
    eq((b.get('tap'), b.get('tapWait'), b.get('once')), ([0, ['so']], [['so'], 'sent 2 letters, ended by a tap'], 0), 'a tap sends at once, and once')
    eq(b.get('auto'), [1, ['yes'], 'sent 3 letters, ended by the recognizer'], 'auto listen ends at a silence')
    eq((b.get('network'), b.get('left')), ([[], 'kept 2 letters, not sent: nothing heard after them, ended by error network'], [1, ['so']]), 'a failed restart keeps, Talk left sends')
    eq((b.get('grow'), b.get('full'), b.get('most')), (1, ['sent 6 letters, ended by a tap', False], 1), 'the report has its end, and no words')
    check("mic hold, the run's version 9.9, open page aaa, not the run's (bbb): not reloaded since it changed, audio session" in got['holdReport'],
          "the report names the open page and the run's: a page not reloaded is told apart", got['holdReport'][:300])
    eq(got.get('pages'), ["open page aaa, the same as the run's", "open page not known, the run's page aaa", "open page aaa, the run's page not known"],
       'the open page is the run\'s, or one of the two is not known')
    check('mic hold' in got['holdReport'] and 'works as' not in got['holdReport'], 'the report says hold', got['holdReport'][:300])
    eq(got.get('cap'), 'and 10 more', 'the report has an end')
    eq(got.get('copied')[:2] + got.get('copied')[3:4], ['Mic report', 'the note', 'UA'], 'the copy names the note and the browser')
    check('page open ' in got['holdReport'] and 'without' in got['holdReport'], 'B162b1: the report says what the page did before', got['holdReport'][:400])
    eq(got.get('sheet'), ['out', 'Mic report', True], 'no clipboard: shown to copy by hand')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_talk_f93), in_tmp(test_listen_heard_nothing_b132), in_tmp(test_talk_new_chat_f157), in_tmp(test_talk_reply_heard_b133), in_tmp(test_chat_box_f115), in_tmp(test_mic_aborted_b162)]))
