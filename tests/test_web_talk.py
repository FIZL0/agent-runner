"""The run page, talk area (agent_runner/page/*-talk.*): split from test_web.py (C41b), tests unchanged.

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
const chatShown = () => false;
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
  console.log(JSON.stringify({listening, interim, after: ta.value, draft: drafts['draft:c3'], stopped: DK.rec === null, sent, toasts}));`);
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
` + grab('function speak(') + line('function hush(') + grab('function playReply(') + line('const MIC=') + grab('function micWhenFree(') + grab('function micFree(') + 'const AU={el:null,got:null,ok:false};' + grab('function shush(') + grab('function unlockAudio(') + grab('function listen(') + grab('function hear(') + grab('function micSent(') + grab('function earEnd(') + grab('function micStop(')
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
const talkSend = t => { sent.push(t); TK.state = '' };
const els = {}, el = () => ({classList: {toggle() {}}, setAttribute(k, v) { this[k] = v }, removeAttribute(k) { delete this[k] }});
let copied = '', sheet = '', RUN_VERSION = '9.9'; const openSheet = n => { sheet = n };
const $ = k => els[k] = els[k] || el();
let micEl = null;  // a redraw of the mic's markup makes a new element
eval(logic + `
function render() { if (setHTML($('talkmic'), talkMic())) els.mic = micEl = {...el(), setPointerCapture(id) { this.cap = id }}; talkDraw() }
let TS = talkSetParse('');
` + line('const MIC=') + line('function setHTML(') + line('const talkMic=') + ['talkDraw', 'micWhenFree', 'micFree', 'dictShow', 'dictate', 'shush', 'unlockAudio', 'speak', 'listen', 'hear', 'micSent', 'earEnd', 'micStop', 'async function micCopy', 'async function micCopyText'].map(f => grab((f.startsWith('async') ? f : 'function ' + f) + '(')).join('')
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
starts = 0; fire('pointerdown', when); last().say('kept'); now += 2000; last().end(); last().fail('audio-capture'); tick(250); out.realWords = [starts, TK.state, sent.splice(0)]; fire('pointerup', when);
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
fire('pointerdown', when); hears(['kept', false]); { const S0 = SR; SR = class { constructor() { throw new Error('none') } }; last().end(); SR = S0 } cut.none = [sent.splice(0), TK.state, ended()]; fire('pointerup', when);
// Tap: a pause does not send; more words, then a silence, and it does
TS.mic = 'tap'; starts = 0; listen(); hears(['so do a', true]); now += 3000; last().end(); cut.pause = [starts, sent.length, TK.state, says()];
now += 1500; hears(['full one', false]); tick(2000); cut.goesOn = [sent.length, !!last().stopped]; hears(['full one', true]); last().end(); cut.again = [starts, sent.length];
now += 2000; tick(2000); cut.silence = !!last().stopped; last().end(); cut.pauseSent = [sent.splice(0), TK.state, ended(), starts];
// speech begun in the wait makes it longer, once
starts = 0; listen(); hears(['so', true]); last().end(); now += 1500; last().onspeechstart(); now += 1000; last().fail('no-speech'); cut.speech = [starts, sent.length];
last().onspeechstart(); now += 1100; last().fail('no-speech'); cut.speechEnd = [starts, sent.splice(0), ended()];
// results that come back empty unsay nothing
listen(); hears(['so do', false]); hears(['', false]); last().onresult({resultIndex: 0, results: []}); listen(); last().end(); cut.empty = sent.splice(0);
// the wait's recognizer ends early, as iOS does: on again until the wait is over, and no longer
starts = 0; listen(); hears(['so', true]); now += 3000; last().end(); now += 300; last().fail('aborted', 'No speech detected'); tick(250); cut.early = [starts, sent.length];
now += 400; last().fail('aborted'); tick(250); cut.failed = [starts, sent.length]; now += 1300; last().end(); cut.over = [starts, sent.splice(0)];
// the wait is over while no recognizer runs
listen(); hears(['so', true]); last().end(); now += 900; last().fail('aborted'); tick(2000); cut.between = [sent.splice(0), TK.state];
// a tap sends at once: in the first listen, and in the wait
listen(); hears(['so', true]); starts = 0; listen(); last().end(); cut.tap = [starts, sent.splice(0)];
listen(); hears(['so', true]); last().end(); listen(); last().end(); cut.tapWait = [sent.splice(0), ended()]; tick(2000); cut.once = sent.length;
// auto listen sends at a silence; a real failure in the wait sends too; left Talk: no wait
starts = 0; TK.again = true; listen(); hears(['yes', true]); last().end(); cut.auto = [starts, sent.splice(0), ended()];
listen(); hears(['so', true]); last().end(); last().fail('network'); cut.network = [sent.splice(0), ended()];
starts = 0; listen(); hears(['so', true]); S.view = 'home'; last().end(); S.view = 'talk'; cut.left = [starts, sent.splice(0)];
// the report: growing results are one line, the line that says what ended it is in a full one too, and no words are
listen(); for (const w of ['s', 'se', 'sec', 'secret']) hears([w, false]); cut.grow = TK.trail.ev.filter(x => /result/.test(x)).length;
for (let i = 0; i < 130; i++) micLog('x'); listen(); last().end(); cut.full = [ended(), TK.trail.ev.join().includes('sec')]; sent.length = 0; cut.most = most; TS.mic = 'hold';
navigator.userAgent = 'UA iPhone'; TK.hold = false; TK.report = TK.trail; let holdReport = '';
navigator.clipboard = {writeText: async t => { holdReport = t }}; micCopy().then(() => { out.holdReport = holdReport });
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
    eq(got.get('reason'), 'The mic was on, but no words reached it before it was stopped. Stop any other app that uses sound or the mic, then try again. '
       '(aborted: No speech detected, hold, after 1.6 s)', "the note has the error's own message")
    eq(got.get('trail'), ['0 ms pointerdown touch id 7', '0 ms listen hold', '0 ms try 1', '0 ms start', '700 ms audiostart', '1600 ms pointerup touch id 7',
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
    eq(got.get('wordsKept'), [4, 'listening', True, 4, 'one', 0], 'words heard stay on the line, unsent')
    eq((got.get('shortWait'), got.get('iosQuiet')), (4, [5, 'listening', True, 5]), "iOS's abort for silence: on again, after a wait when it was short")
    eq((got.get('iosNoStart'), got.get('oneFail')), ([6, 'listening', True, 6], [7, 'listening', True, 7]), 'the message alone says silence; one failed start is tried again')
    eq(got.get('holdWords'), [['one two'], '', 1], 'release sends all the words; never two recognizers')
    eq(got.get('holdNone', [])[:3] + got.get('holdNone', [])[4:], [2, '', 0, True], 'release with none sends nothing')
    check('Heard nothing' in got['holdNone'][3], 'and the line says so, not that the mic was never on', got['holdNone'][3])
    eq(got.get('holdWait'), [1, '', 0], 'released before the next start: none')
    eq(got.get('real'), [[1, '', 0]] * 3, 'permission refused or no mic ends it')
    eq(got.get('realWords'), [2, '', ['kept']], 'and the words so far go out')
    eq(got.get('notHeld'), [1, ''], 'a listen not held ends at a silence')
    b = got.get('b216') or {}
    eq(b.get('line'), 'so do a full one', 'B216: shown as heard')
    eq(b.get('interim'), [['so do a full one'], 'sent 16 letters, ended by a tap'], 'is sent, final or not')
    eq(b.get('release'), [['so do a full one'], True], 'let go, with an abort, the same')
    eq((b.get('blank'), b.get('late')), (['so do a full'], ['so do a full']), 'an empty final unsays nothing; words after the release count')
    eq((b.get('gap'), b.get('gapSent')), ([2, 0], ['so do a full']), 'held: on again at once after words')
    eq(b.get('none'), [['kept'], '', 'sent 4 letters, ended by no recognizer'], 'no recognizer: the words so far go out')
    eq((b.get('pause'), b.get('goesOn'), b.get('again')), ([2, 0, 'listening', 'so do a'], [0, False], [3, 0]), 'Tap: a pause listens on')
    eq((b.get('silence'), b.get('pauseSent')), (True, [['so do a full one'], '', 'sent 16 letters, ended by a pause', 3]), 'and a silence of 2 s sends one message')
    eq((b.get('speech'), b.get('speechEnd')), ([3, 0], [3, ['so'], 'sent 2 letters, ended by error no-speech']), 'speech begun in the wait makes it longer, once')
    eq(b.get('empty'), ['so do'], 'empty results unsay nothing')
    eq((b.get('early'), b.get('failed'), b.get('over')), ([3, 0], [4, 0], [4, ['so']]), 'a recognizer that ends early does not end the wait, nor outlast it')
    eq(b.get('between'), [['so'], ''], 'nor does one that is about to start')
    eq((b.get('tap'), b.get('tapWait'), b.get('once')), ([0, ['so']], [['so'], 'sent 2 letters, ended by a tap'], 0), 'a tap sends at once, and once')
    eq(b.get('auto'), [1, ['yes'], 'sent 3 letters, ended by the recognizer'], 'auto listen ends at a silence')
    eq((b.get('network'), b.get('left')), ([['so'], 'sent 2 letters, ended by error network'], [1, ['so']]), 'a failure, and Talk left, send')
    eq((b.get('grow'), b.get('full'), b.get('most')), (1, ['sent 6 letters, ended by a tap', False], 1), 'the report has its end, and no words')
    check('mic hold, version' in got['holdReport'] and 'works as' not in got['holdReport'], 'the report says hold', got['holdReport'][:300])
    eq(got.get('cap'), 'and 10 more', 'the report has an end')
    eq(got.get('copied')[:2] + got.get('copied')[3:4], ['Mic report', 'the note', 'UA'], 'the copy names the note and the browser')
    check('page open ' in got['holdReport'] and 'without' in got['holdReport'], 'B162b1: the report says what the page did before', got['holdReport'][:400])
    eq(got.get('sheet'), ['out', 'Mic report', True], 'no clipboard: shown to copy by hand')


SOUND_DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const grab = s => { const i = page.indexOf(s); if (i < 0) throw new Error(s); return page.slice(i, page.indexOf('\n}\n', i) + 2) + '\n' };
const line = s => { const i = page.indexOf(s); if (i < 0) throw new Error(s); return page.slice(i, page.indexOf('\n', i)) + '\n' };
const logic = page.split('<script id="logic">')[1].split('</script>')[0];
const said = [], notes = [], types = [], keys = {}, esc = String, tq = p => p, HOME_PAGE = false;
let asked = [], plays = [], answers = [], refuse = null, timers = [];
const window = {speechSynthesis: {cancel() {}, speak(u) { if (u.text) said.push(u.text) }}}, speechSynthesis = window.speechSynthesis;
class SpeechSynthesisUtterance { constructor(t) { this.text = t } }
class Audio { constructor(src) { this.src = src; this.paused = true; this.ended = false }
  play() { if (!this.loop) plays.push(this.src); if (refuse && !this.loop) return Promise.reject(Object.assign(new Error('no'), {name: refuse}));
    this.paused = false; this.ended = false; return Promise.resolve() }
  pause() { this.paused = true; if (this.onpause) this.onpause() }
  finish() { this.paused = true; this.ended = true; this.onended() } }
let urls = 0; URL.createObjectURL = () => 'clip' + (++urls); URL.revokeObjectURL = () => {};
const VOICES = {voices: [{id: 'kokoro:a', name: 'a', engine: 'Kokoro'}], default: 'kokoro:a'};
// answers: one per clip asked for, 'net' (no answer), a status with no JSON, or a reason; then clips
const fetch = async (p, o) => { if (!o) return {ok: true, json: async () => VOICES};
  asked.push(JSON.parse(o.body).text); const a = answers.shift();
  if (a === 'hang') return new Promise((y, no) => o.signal.addEventListener('abort', () => no(Object.assign(new Error('x'), {name: 'AbortError'}))));
  if (a === 'net') throw new TypeError('Load failed');
  return {ok: !a, status: a === 502 ? 502 : 503, blob: async () => new Blob(['x']), json: async () => { if (a === 502) throw new SyntaxError('x'); return {out: a} }} };
const audioSession = {state: 'active', get type() { return types[types.length - 1] || 'auto' }, set type(t) { types.push(t) }};
const navigator = {language: 'en-US', userAgent: 'iPhone', audioSession, mediaSession: {setActionHandler: (k, f) => { keys[k] = f }}};
const toast = t => notes.push(t), render = () => {}, voices = () => [];
const realTimeout = setTimeout, settle = () => new Promise(r => realTimeout(r, 5));
globalThis.setTimeout = (f, ms) => { const t = {f, ms}; timers.push(t); return t }; globalThis.clearTimeout = t => { if (t) t.f = null };
const tick = async ms => { for (const t of timers.splice(0)) if (t.f && t.ms === ms) t.f(); else if (t.f) timers.push(t); await settle() };
const S = {view: 'talk', thread: null, sheet: ''}, MIC = {rec: null, next: null};
const TK = {state: '', playing: '', note: '', held: '', later: [], ear: null, unlocked: true, trail: null, report: ''};
let TS;
const listen = () => {}, micWhy = () => '', store = {get: () => ''}, TM_KEY = 'tm';
eval(logic + `TS = talkSetParse('');` + page.slice(page.indexOf('/* F158: run speech:'), page.indexOf('const talkTyping='))
 + line('const talkTyping=') + grab('function speak(') + line('function hush(') + `
(async () => {
  const out = {}; await settle(); AU.ok = true;  // a tap let it play
  // one fetch with no answer: asked again, and the reply goes on in the run's voice
  answers = ['net']; speak('One secret here. Two.'); await settle(); out.wait = [asked.length, plays.length, TK.state];
  await tick(500); out.again = [asked.slice(0, 2), plays.length, notes.length, said.length]; out.kinds = [types.slice(), AU.holding, AU.hold.loop, AU.hold.paused];
  AU.el.finish(); await settle(); AU.el.finish(); await settle(); out.done = [TK.state, AU.holding, AU.hold.paused, keys.pause];
  // a pause nobody asked for: played again once; a second one ends the reply
  plays = []; speak('Long one here.'); await settle(); AU.el.pause(); out.paused = [TK.state, plays.length];
  await tick(600); out.resumed = [TK.state, plays.length, AU.el.paused]; AU.el.pause(); out.second = [TK.state, AU.hold.paused]; await tick(600); out.after = plays.length;
  // the person's own pause: the lock screen or the earbuds; and a stop by hand before the sound comes back
  plays = []; speak('Long one here.'); await settle(); keys.pause(); await tick(600); out.person = [TK.state, plays.length];
  plays = []; speak('Long one here.'); await settle(); AU.el.pause(); hush(); await tick(600); out.byHand = [TK.state, plays.length];
  // refused when it is played again: held for a tap
  speak('Long one here.'); await settle(); AU.el.pause(); refuse = 'NotAllowedError'; await tick(600); out.refused = [TK.state, TK.held, AU.holding]; refuse = null;
  // a drop in the middle: what was fetched plays to its end, then the phone's voice reads the rest
  AU.ok = true; notes.length = said.length = 0; asked = []; plays = []; answers = [null, 'net', 502, 'net']; speak('First one is here. Second.'); await settle(); await tick(500); await tick(2000);
  out.kept = [plays.length, said.length, notes.length, TK.state, asked.length]; AU.el.finish(); await settle(); out.drop = [said.slice(), notes.slice(), AU.holding]; hush();
  // the engine's own reason is said at once, with no new try
  notes.length = 0; asked = []; answers = ['it broke']; speak('Other.'); await settle(); out.engine = [asked.length, notes.slice()]; hush();
  // no answer in time: asked once more, then the phone's voice
  notes.length = 0; asked = []; answers = ['hang', 'hang']; speak('Hung.'); await settle(); await tick(25000); await tick(500); await tick(25000); out.hang = [asked.length, notes.slice()]; hush();
  // a mic that took the sound (dictation): the reply is not played into it
  plays = []; speak('Long one here.'); await settle(); MIC.rec = {}; AU.el.pause(); await tick(600); out.dict = [TK.state, plays.length]; MIC.rec = null;
  // a mic that is still ending: no playback session and no clip before its end
  types.length = 0; types.push('play-and-record'); plays = []; MIC.rec = {}; speak('After the mic.'); await settle(); out.mic = [types.slice(-1)[0], plays.length];
  MIC.rec = null; await tick(100); out.micOver = [types.slice(-1)[0], plays.length]; hush();
  MIC.rec = {}; types.push('play-and-record'); soundAs('playback'); out.live = types.slice(-1)[0]; MIC.rec = null;
  out.report = [TK.report === TK.trail, TK.trail.ev.join(' | ')];
  out.plain = [new TypeError('Load failed'), Object.assign(new Error('x'), {name: 'AbortError'}), new SyntaxError('x'), new Error('full')].map(plainErr);
  out.sizes = speechClips('First one is here. ' + 'Word. '.repeat(200)).map(x => x.length);
  console.log(JSON.stringify(out));
})();`);
"""


def test_sound_b178(tmp: Path) -> None:
    """B178: run speech over Bluetooth and a bad connection: a fetch with no answer is asked again and said in plain
    words, an unasked pause is undone once, the audio session follows the mic, and silence holds the route open."""
    page = W.page_html().decode()
    check('${e}`' not in page, "no toast shows an error's own words")
    for f in ('function hear(', 'function dictate('):
        part = page.split(f, 1)[1].split('\n}\n', 1)[0]
        check("soundAs('play-and-record')" in part and part.index("soundAs('play-and-record')") < part.index('rec.start()'), f'{f}: the session is for the mic before it starts')
        check("soundAs('playback')" in part, f'{f}: and for playing once it ended')
    check("soundAs('playback')" in page.split('function earEnd(', 1)[1].split('\n}\n', 1)[0], 'the end of a listen too')
    check('data-micreport' in page.split('  talk(){', 1)[1].split('\n  },', 1)[0], 'Talk settings has the report')
    if not shutil.which('node'):
        print('  (no node here: the sound script test is skipped)')
        return
    (tmp / 'driver.js').write_text(SOUND_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs the sound', r.stderr[-900:])
    got = json.loads(r.stdout or '{}')
    eq(got.get('wait'), [1, 0, 'speaking'], 'no answer: it waits')
    eq(got.get('again'), [['One secret here.'] * 2, 1, 0, 0], 'and asks again, with nothing said about it')
    eq(got.get('kinds'), [['playback'], True, True, False], 'the session is for playing, and silence holds the route')
    eq(got.get('done'), ['', False, True, None], 'until the reply ends')
    eq((got.get('paused'), got.get('resumed')), (['speaking', 1], ['speaking', 2, False]), 'an unasked pause is undone')
    eq((got.get('second'), got.get('after')), (['', True], 2), 'once')
    eq((got.get('person'), got.get('byHand')), (['', 1], ['', 1]), "the person's own stop stands")
    eq(got.get('refused'), ['', 'Long one here.', False], 'refused then: held for a tap')
    eq(got.get('kept'), [1, 0, 0, 'speaking', 4], 'a drop in the middle: the clip that came plays on, the next is tried three times')
    eq(got.get('drop'), [['Second.'], ["No connection to the run; reading with the phone's voice"], False], "then the phone's voice reads the rest")
    eq(got.get('engine'), [1, ['The run could not read this aloud (it broke), so this browser does.']], "the engine's reason: no new try")
    eq(got.get('hang'), [2, ["No connection to the run; reading with the phone's voice"]], 'no answer in time: one more try, and the same plain words')
    eq(got.get('dict'), ['', 1], 'a pause by a mic: not played into it')
    eq((got.get('mic'), got.get('micOver')), (['play-and-record', 0], ['playback', 1]), 'a mic still ending is waited for')
    eq(got.get('live'), 'play-and-record', 'never playback while a mic is on')
    rep = got.get('report') or [False, '']
    check(rep[0] and 'no connection' in rep[1] and 'not by the page' in rep[1] and 'secret' not in rep[1] and 'Second' not in rep[1], 'the report has the events and no words', str(rep))
    eq(got.get('plain'), ['no connection', 'no connection', 'its answer made no sense', 'full'], 'errors in plain words')
    n = got.get('sizes') or [0]
    check(n[0] < 30 and 150 < n[1] < 201 and max(n) > 350 and max(n) < 401, 'few clips, longer as it goes', str(n))


READ_DRIVER = SOUND_DRIVER.split('const S = {view')[0].replace('{cancel() {}, speak(u)', "{cancel() { order.push('cancel') }, speak(u) { if (u.text) us.push(u);").replace('speak(u) { if (u.text) us.push(u); { if', 'speak(u) { if (u.text) us.push(u); if') + r"""
const order = [], us = [], sent = [], recs = [], handlers = {}, els = {}, ss = window.speechSynthesis;
let now = 1000; Date.now = () => now;
const look = async (n = 1) => { for (let i = 0; i < n; i++) { now += 1000; await tick(1000) } };
class SR { constructor() { recs.push(this) } start() { order.push('start') } stop() { this.stopped = true } abort() {}
  say(t) { this.onresult({resultIndex: 0, results: [Object.assign([{transcript: t}], {isFinal: true})]}) } end() { this.onend() } }
const mic = () => recs[recs.length - 1];
const document = {hidden: false, addEventListener(t, f) { (handlers[t] = handlers[t] || []).push(f) }}, addEventListener = () => {};
const fire = (t, e) => (handlers[t] || []).forEach(f => f(e));
const el = () => ({classList: {toggle() {}}, setAttribute(k, v) { this[k] = v }, removeAttribute(k) { delete this[k] }, setPointerCapture() {}});
const $ = k => els[k] = els[k] || el(), I = {stop: 'STOP', talk: 'MIC', speak: 'SPEAKER', mute: 'MUTE', keys: ''};
const S = {view: 'talk', thread: null, sheet: '', feeds: {}}, feedOf = n => (S.feeds[n] || {}).entries || [], kept = {};
const TK = {state: '', playing: '', note: '', held: '', later: [], wait: null, watch: null, heard: '', hold: false, ear: null, unlocked: true, trail: null, report: ''};
let TS; const micWhy = () => '', TM_KEY = 'tm', store = {get: k => kept[k] || ''}, talkWaitName = () => 'c5', talkSet = (k, v) => { TS = {...TS, [k]: v} };
const RUN_VERSION = '', DK = {};
// a send waits for its reply, as talkSend does
const talkSend = async t => { sent.push(t); if (TK.state !== 'speaking') TK.state = 'thinking'; awaitReply() };
const awaitReply = () => { TK.wait = {n: 'c5', since: 0, at: now, last: '', said: ''}; S.feeds.c5 = {entries: []} };
const lands = t => { if (!TK.wait) awaitReply(); S.feeds.c5.entries = [{kind: 'you', text: 'x'}, {kind: 'say', text: t}]; talkHear('c5'); talkHear('c5') };
const press = k => { const b = {}, e = {target: {closest: s => s === k ? b : null}, button: 0, pointerId: 1, pointerType: 'touch', detail: 1}; return e };
eval(logic + `TS = talkSetParse('');` + page.slice(page.indexOf('/* F158: run speech:'), page.indexOf('const talkTyping='))
 + line('const talkTyping=') + line('function setHTML(') + line('const MIC=')
 + ['micWhenFree', 'micFree', 'talkDraw', 'talkHear', 'speak', 'listen', 'hear', 'micSent', 'earEnd', 'micStop'].map(f => grab('function ' + f + '(')).join('') + line('function hush(')
 + page.slice(page.indexOf("document.addEventListener('visibilitychange',()=>{if(TK.ear)"), page.indexOf('/* F124: a swipe right anywhere'))
 + `const click = k => { const e = press(k), q = s => e.target.closest(s); ` + ['data-mic', 'data-spk'].map(k => line("  if(q('[" + k + "]'))").trim()).map(x => '(() => {' + x.replace(/\/\/ F93.*/, '') + '})();').join('') + ` };
const shows = () => { talkDraw(); return [els.mic.innerHTML, els.mic['aria-label'], els.spk.innerHTML, els.spk['aria-label'], els.talkline.textContent, els.spkbox.hidden] };
const over = () => { if (TK.ear) { mic().end() } hush(); TK.wait = null; TK.state = TK.note = ''; TK.hold = false; TK.trail = null; order.length = us.length = said.length = sent.length = 0; plays = []; asked = []; ss.speaking = ss.pending = ss.paused = false };
(async () => {
  const out = {}; await settle(); const run = AU.got; AU.ok = true;
  for (const kind of ['own', 'run']) {
    AU.got = kind === 'run' ? run : null; const o = out[kind] = {}; over();
    const begin = async () => { if (kind === 'run') await settle(); else { us[0].onstart(); ss.speaking = true } };
    const quiet = () => kind === 'run' ? AU.el.paused !== false : order.includes('cancel');
    o.idle = shows();
    // the buttons while a reply is read, and the speaker's tap
    lands('One here. Two.'); await begin(); o.reads = shows(); order.length = 0; click('[data-spk]'); ss.speaking = false;
    o.spk = [quiet(), TK.state, TS.read, order.includes('start'), shows()[2]]; const n = plays.length + us.length; await look(3); o.more = plays.length + us.length - n;
    click('[data-spk]'); o.off = TS.read; click('[data-spk]');
    // a press on the mic cuts it and listens, the voice's cancel only after the start
    over(); lands('One here. Two.'); await begin(); order.length = 0; click('[data-mic]'); o.tap = [TK.state, quiet(), kind === 'run' || order.join()]; ss.speaking = false;
    mic().say('wait'); click('[data-mic]'); mic().end(); await settle(); await look(3); o.cut = [sent.slice(), TK.state, plays.length + us.length];
    // held: the same; a reply that lands meanwhile waits for the end, and two play in order
    over(); TS.mic = 'hold'; lands('One here. Two.'); await begin(); order.length = 0; fire('pointerdown', press('[data-mic]')); o.hold = [TK.state, quiet(), order[0]]; ss.speaking = false;
    const base = plays.length + us.length; lands('Second reply.'); lands('Third reply.'); await settle(); await look(2); o.during = [plays.length + us.length - base, TK.state, TK.later.length];
    const heard0 = asked.length; said.length = 0; mic().say('go'); fire('pointerup', press('[data-mic]')); await settle(); o.ending = plays.length + us.length - base;
    mic().end(); await settle(); await tick(100); o.after = [sent.slice(), TK.state, plays.length + us.length - base];
    if (kind === 'run') { AU.el.finish(); await settle() } else { const u = us[us.length - 1]; u.onstart(); u.onend({type: 'end'}) }
    o.both = kind === 'run' ? asked.slice(heard0) : said.slice();
    if (kind === 'run') { AU.el.finish(); await settle() } else us[us.length - 1].onend({type: 'end'});
    o.waits = [TK.state, TK.later.length];
    // the recognizer ended by itself while the finger is still down: nothing plays before it lifts; nothing heard
    over(); fire('pointerdown', press('[data-mic]')); lands('Fourth reply.'); mic().onerror({error: 'no-speech'}); mic().end(); await settle(); o.down = [TK.later.length, plays.length + us.length];
    fire('pointerup', press('[data-mic]')); await settle(); o.up = [TK.state, TK.later.length];
    // read aloud turned off meanwhile: it stays unread
    over(); fire('pointerdown', press('[data-mic]')); lands('Fifth reply.'); TS.read = false; fire('pointerup', press('[data-mic]')); mic().end(); await settle(); o.mute = [TK.state, TK.later.length, plays.length + us.length]; TS.read = true;
    TS.mic = 'tap';
  }
  // the box row shows the same stop, and it is the speaker's
  over(); kept.tm = 'type'; AU.got = null; lands('One here.'); out.typing = [shows()[5], (click('[data-spk]'), TK.state), shows()[5]]; kept.tm = '';
  // a clip already on its way when the hold starts is not played
  AU.got = run; over(); TS.mic = 'hold'; lands('One here. Two.'); fire('pointerdown', press('[data-mic]')); await settle(); out.clip = [plays.length, TK.state];
  fire('pointerup', press('[data-mic]')); mic().end(); await settle(); await look(2); out.clipAfter = [plays.length, TK.state]; TS.mic = 'tap';
  // the browser's voice: no end comes; no start comes; stuck 'speaking'; the page hidden and shown
  AU.got = null; over(); lands('One here.'); us[0].onstart(); ss.speaking = true; await look(3); out.ownOn = TK.state; ss.speaking = false; await look(2); out.ownEnd = [TK.state, shows()[2]];
  over(); lands('One here.'); ss.pending = true; await look(8); const still = TK.state; await look(4); out.noStart = [still, TK.state];
  over(); lands('One here.'); await look(5); out.silent = TK.state;
  over(); lands('One here.'); us[0].onstart(); ss.speaking = true; await look(14); out.stuck = TK.state;
  over(); TS.auto = true; lands('One here.'); us[0].onstart(); ss.speaking = true; document.hidden = true; fire('visibilitychange', {}); now += 60000; ss.speaking = false; document.hidden = false; fire('visibilitychange', {}); await look(2); out.shown = [TK.state, order.includes('start')];
  over(); lands('One here.'); us[0].onstart(); order.length = 0; await look(2); out.auto = [TK.state, order.join()]; TS.auto = false; over();
  // run speech: the clip's end, its error, a pause and a stand-still with no event
  AU.got = run; const clip = async () => { over(); lands('One sentence is here. Two.'); await settle(); AU.el.currentTime = 0 };
  await clip(); AU.el.ended = true; await look(); out.clipEnd = plays.length; AU.el.ended = true; await look(); out.allEnd = [TK.state, AU.holding];
  await clip(); AU.el.error = {code: 4}; await look(); out.clipErr = said.length; delete AU.el.error;
  await clip(); AU.el.paused = true; await look(2); out.clipPause = TK.state;
  await clip(); for (let i = 0; i < 15; i++) { AU.el.currentTime++; await look() } out.clipOn = TK.state; await look(12); out.clipStill = TK.state;
  // Safari refuses: held for the speaker's tap
  over(); TS.mic = 'hold'; fire('pointerdown', press('[data-mic]')); lands('Sixth reply.'); refuse = 'NotAllowedError'; fire('pointerup', press('[data-mic]')); mic().end(); await settle(); out.refused = [TK.state, TK.held];
  lands('Seventh reply.'); refuse = null; await settle(); await look(2); out.heldWaits = [TK.held, TK.later.length];
  click('[data-spk]'); await settle(); out.heldTap = [asked[asked.length - 1], TK.state, TK.later.length];
  // a sound that ended by itself: the next waiting reply is read; a long first sentence with no start event goes on
  asked = []; AU.el.paused = true; await look(2); await settle(); out.nextUp = [asked[0], TK.state]; TS.mic = 'tap';
  AU.got = null; over(); lands('Word '.repeat(60)); ss.speaking = true; await look(40); out.longOn = TK.state;
  over(); TS.auto = true; lands('One here.'); us[0].onstart(); ss.paused = true; order.length = 0; await look(2); out.pausedVoice = [TK.state, order.join()]; TS.auto = false;
  // the page hidden under a held finger: the mic stops
  over(); TS.mic = 'hold'; fire('pointerdown', press('[data-mic]')); document.hidden = true; fire('visibilitychange', {}); out.hidHold = [TK.hold, !!mic().stopped];
  console.log(JSON.stringify(out));
})();`);
"""


def test_stop_speaking_b174(tmp: Path) -> None:
    """B174: the speaker button is the stop while a reply is read, the mic never; a mic press cuts the reply and listens,
    what lands meanwhile is read once the mic ended, and a reading that makes no sound any more clears."""
    page = W.page_html().decode()
    check('Tap to stop' not in page and '.mic.speaking' not in page, 'the mic is no stop')
    check('id="spkbox" data-spk hidden' in page.split('function box(', 1)[1].split('\n}\n', 1)[0], "Talk's box row has the speaker's stop")
    if not shutil.which('node'):
        print('  (no node here: the stop speaking script test is skipped)')
        return
    (tmp / 'driver.js').write_text(READ_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs the reading', r.stderr[-900:])
    got = json.loads(r.stdout or '{}')
    for kind in ('own', 'run'):
        o = got.get(kind) or {}
        eq(o.get('idle'), ['MIC', 'Talk', 'SPEAKER', 'Read replies aloud: on', 'Tap to talk', True], f'{kind}: at rest')
        eq(o.get('reads'), ['MIC', 'Talk', 'STOP', 'Stop speaking', 'Speaking…', False], f'{kind}: while read, the mic keeps its icon and the speaker is the stop')
        eq((o.get('spk'), o.get('more')), ([True, '', True, False, 'SPEAKER'], 0), f'{kind}: its tap stops the sound, nothing more is read and read aloud stays on')
        eq(o.get('off'), False, f'{kind}: the next tap turns read aloud off')
        eq(o.get('tap'), ['listening', True, True if kind == 'run' else 'start,cancel'], f'{kind}: a mic press cuts it and listens')
        eq(o.get('cut'), [['wait'], 'thinking', 2 if kind == 'own' else 1], f'{kind}: what the mic cut does not start again')
        eq(o.get('hold'), ['listening', True, 'start'], f'{kind}: held, the same')
        eq(o.get('during'), [0, 'listening', 2], f'{kind}: what lands meanwhile waits')
        eq((o.get('ending'), o.get('after')), (0, [['go'], 'speaking', 1]), f'{kind}: until the mic ended, its words sent')
        eq(o.get('both'), ['Second reply.', 'Third reply.'], f'{kind}: two are read in order')
        eq(o.get('waits'), ['thinking', 0], f'{kind}: and then the new reply is awaited')
        eq((o.get('down'), o.get('up')), ([1, 0], ['speaking', 0]), f'{kind}: no sound while the finger is down, nothing heard: read when it lifts')
        eq(o.get('mute'), ['', 0, 0], f'{kind}: read aloud turned off meanwhile: not read')
    eq(got.get('typing'), [False, '', True], 'typing: the stop shows while a reply is read, and stops it')
    eq((got.get('clip'), got.get('clipAfter')), ([0, 'listening'], [0, '']), 'a clip that arrives mid-hold is not played, nor after it')
    eq((got.get('ownOn'), got.get('ownEnd')), ('speaking', ['', 'SPEAKER']), 'no end event: it clears')
    eq(got.get('noStart'), ['speaking', ''], 'a start that never comes')
    eq((got.get('silent'), got.get('stuck')), ('', ''), 'never begun; or says it speaks for ever')
    eq(got.get('shown'), ['', False], 'hidden and shown: it clears, and the mic does not start by itself')
    eq(got.get('auto'), ['listening', 'start'], 'auto listen follows an end with no event, with no speechSynthesis call before it')
    eq((got.get('clipEnd'), got.get('allEnd')), (2, ['', False]), 'a clip that ended with no event: the next one, then the end')
    eq(got.get('clipErr'), 2, "an error with no event: the browser's voice reads the rest")
    eq(got.get('clipPause'), '', 'paused with no event')
    eq((got.get('clipOn'), got.get('clipStill')), ('speaking', ''), 'a clip that moves goes on, one that stands still ends')
    eq(got.get('refused'), ['', 'Sixth reply.'], 'Safari refuses it: held for the speaker')
    eq((got.get('heldWaits'), got.get('heldTap')), (['Sixth reply.', 1], ['Sixth reply.', 'speaking', 1]), 'a later one waits behind it, in order')
    eq(got.get('nextUp'), ['Seventh reply.', 'speaking'], 'a sound that ends by itself: the next waiting reply is read')
    eq(got.get('longOn'), 'speaking', 'a long sentence with no start event is not cut')
    eq(got.get('pausedVoice'), ['', 'cancel'], 'a paused voice is dropped, with no auto listen into it')
    eq(got.get('hidHold'), [False, True], 'the page hidden under a held finger: the mic stops')


def test_talk_settings_f124(tmp: Path) -> None:
    """F124 (F123): Talk's settings and their defaults; hold to talk starts on pointerdown and sends on pointerup; auto
    listen listens again once a reply was read; a play button reads a reply and stops it; mic and speaker are 64px."""
    page = W.page_html().decode()
    for part in ('.mic,.spk{width:64px;height:64px', 'data-spk', 'data-talkmode="type"', 'data-talkmode="mic"', 'data-speak=',
                 'data-sheet="talk"', "'ar-talkset'", "'ar-talkmode'", 'data-ts="read"', 'data-ts="voice"', 'data-ts="mic"',
                 'data-ts="auto"', 'System voice', '.dock.typing .talkbox{opacity:1'):
        check(part in page, f'the Talk view has {part}')
    check('title="Talk settings">${I.settings}</button>' in page, 'Talk settings has the sliders icon')
    check(not re.search(r'\bgear:|I\.gear\b', page), 'no gear icon is left')
    check('Spoken Content' not in page, 'no how-to for voices (dropped)')
    if not shutil.which('node'):
        print('  (no node here: the Talk settings script test is skipped)')
        return
    (tmp / 'driver.js').write_text(HOLD_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, "node runs Talk's settings", r.stderr[-900:])
    got = json.loads(r.stdout or '{}')
    eq(got.get('defaults'), {'read': True, 'voice': '', 'mic': 'tap', 'auto': False, 'way': 'browser'},
       'defaults: replies read aloud, the system voice, tap, no auto listen')
    eq(got.get('parsed'), {'read': False, 'voice': 'Ava', 'mic': 'hold', 'auto': True, 'way': 'browser'}, 'kept per browser')
    eq(got.get('junk'), got.get('defaults'), 'a broken store is the defaults')
    eq(got.get('tapStarts'), 0, 'tap mode: pointerdown starts nothing')
    eq(got.get('holdStarts'), [1, 'listening'], 'hold mode: pointerdown starts listening')
    eq((got.get('before'), got.get('holdSent')), ([], [['what is running'], True]), 'and pointerup stops and sends')
    eq(got.get('voice'), ['Ava', 'en-GB'], 'the picked voice speaks')
    eq(got.get('auto'), [1, 'listening'], 'auto listen: listen() once the reply was read')
    eq(got.get('silent'), [1, '', 'Tap to talk'], 'one silent turn and it stops')
    eq(got.get('stopped'), [1, ''], 'a reply stopped by hand does not listen again')
    eq(got.get('off'), 1, 'off: no auto listen')
    eq(got.get('play'), ['b', 'One thing.', ''], "a reply's play button reads it, with read aloud off too")
    eq(got.get('playStop'), '', 'a second tap stops it')
    eq(got.get('playOver'), [0, None, 'b'], 'playing a reply stops the mic, and sends nothing')
    eq(got.get('micStops'), [1, ''], 'B174: the mic stops the reply and listens')
    eq(got.get('autoHeld'), 'auto', 'holding the mic while it already listens: letting go sends')


HOME_TALK_DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const grab = s => { const i = page.indexOf(s); return page.slice(i, page.indexOf('\n}\n', i) + 2) + '\n' };
const line = s => { const i = page.indexOf(s); return page.slice(i, page.indexOf('\n', i)) + '\n' };
const log = {heard: 0, draws: [], loads: 0, prevented: 0};
/* names the code under test does not need are empty functions */
const env = {S: {snap: {sessions: [], needs: []}, view: 'home', thread: null, sel: []}, TK: {state: ''}, TS: {mic: 'tap', auto: true},
  I: {talk: '', clock: '', ask: '', plus: ''}, working_: () => [], upNext: () => [], tapped: {}, document: {addEventListener: (t, f) => { log.click = f }},
  viewOf: v => v, listen: () => { log.heard++ }, dictate: () => { log.heard++ }, micWhenFree: () => { log.heard++ },
  fetch: () => { log.loads++ }, location: {reload: () => { log.loads++ }, set href(v) { log.loads++ }},
  render: () => { log.draws.push([env.S.view, env.S.thread]) }};
env.env = env;
const known = new Proxy(env, {has: () => true, get: (t, k) => k === Symbol.unscopables ? undefined : k in t ? t[k] : k in globalThis ? globalThis[k] : () => ''});
new Function('known', 'env', 'with (known) {' + grab('function homeHTML(') + line('function goView(') + 'function viewGo(go){go()} env.goView = goView; env.home = homeHTML;'
  + page.slice(page.indexOf("document.addEventListener('click',async e=>{"), page.indexOf("  if(q('[data-home]'))")) + '})}')(known, env);
const html = env.home();
const b = (html.match(/<button[^>]*data-view="talk"[^>]*>[^<]*<\/button>/) || [''])[0], attrs = (b.match(/data-[a-z]+/g) || []).map(a => '[' + a + ']');
const el = {dataset: {view: 'talk'}, closest: s => attrs.includes(s) ? el : null};
log.click({target: el, preventDefault() { log.prevented++ }}).then(() => console.log(JSON.stringify(
  {b, at: [env.S.view, env.S.thread], draws: log.draws, heard: log.heard, loads: log.loads})));
"""


def test_home_talk_f164(tmp: Path) -> None:
    """F164: Home's Talk button opens Talk in the page: no reload, and the mic does not start by itself."""
    if not shutil.which('node'):
        print('  (no node here: the Home Talk button test is skipped)')
        return
    (tmp / 'driver.js').write_text(HOME_TALK_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node presses the button', r.stderr[-1500:])
    if r.returncode:
        return
    o = json.loads(r.stdout)
    check('>Talk</button>' in o['b'], 'Home has one button that says Talk', o['b'])
    eq((o['at'], o['draws']), (['talk', None], [['talk', None]]), 'one press opens Talk, in one draw')
    eq((o['heard'], o['loads']), (0, 0), 'the mic does not start and nothing is loaded again')
    page = W.PAGE.read_text(encoding='utf-8')
    check('class="btn acc talkbig"' in o['b'] and '.btn.talkbig{width:100%;min-height:56px' in page, 'F426a: big, full width, the accent', o['b'])


MICTEST_DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const grab = s => { const i = page.indexOf(s); if (i < 0) throw new Error(s); return page.slice(i, page.indexOf('\n}\n', i) + 2) + '\n' };
const line = s => { const i = page.indexOf(s); if (i < 0) throw new Error(s); return page.slice(i, page.indexOf('\n', i)) + '\n' };
const logic = page.split('<script id="logic">')[1].split('</script>')[0];
let now = 1000, timers = [], recs = [], types = [], notes = [], copied = '', refuse = null, stopped = 0, spoke = 0;
Date.now = () => now;
const setTimeout = (f, ms) => { timers.push({f, at: now + ms}); return timers.length }, clearTimeout = id => { if (timers[id - 1]) timers[id - 1].f = null };
const real = globalThis.setTimeout, settle = () => new Promise(r => real(r, 2));
const go = async ms => { const end = now + ms; for (;;) { const t = timers.filter(t => t.f && t.at <= end).sort((a, b) => a.at - b.at)[0]; if (!t) break;
  now = Math.max(now, t.at); const f = t.f; t.f = null; f(); await settle() } now = end };
class SR { constructor() { recs.push(this) } start() {} stop() { this.stops = (this.stops || 0) + 1 } abort() { this.aborted = true } }
const last = () => recs[recs.length - 1];
let kind = 'playback'; const audioSession = {state: 'active', get type() { return kind }, set type(t) { types.push(kind = t) }};
const track = {label: 'Secret Name AirPods', muted: false, stop() { stopped++ }}, media = {getUserMedia: async () => { if (refuse) throw Object.assign(new Error('x'), {name: refuse}); return {getTracks: () => [track], getAudioTracks: () => [track]} }};
const navigator = {language: 'en-US', userAgent: 'UA', audioSession, mediaDevices: media, clipboard: {writeText: async t => { copied = t }}};
let asleep = false; class AudioContext { constructor() { this.state = asleep ? 'suspended' : 'running' } resume() {} close() {} createMediaStreamSource() { return {connect() {}} }
  createAnalyser() { return {getFloatTimeDomainData(b) { b[0] = 0.25 }} } }
const window = {AudioContext, get speechSynthesis() { spoke++; return null }}, document = {hidden: false};
let plays = 0; const el = {play() { plays++; return Promise.resolve() }};
const audioSrc = () => el, AU = {ok: false}, RUN_VERSION = '9.9', openSheet = () => {}, SHEETS = {}, esc = String;
const S = {view: 'talk', sheet: 'mictest'}, TK = {state: '', later: [], ear: null, trail: null};
const toast = t => notes.push(t), render = () => {}, micWhy = () => '', TS = {read: true};
eval(logic + line('const MIC=') + grab('function micFree(') + grab('async function micCopyText(') + page.slice(page.indexOf('/* B162b1: the Mic test'), page.indexOf('const micTestText=')) + line('const micTestText=') + `
(async () => {
  const out = {}, ran = () => MT.runs[MT.runs.length - 1], evs = () => ran().trail.ev.join(' | ');
  // 1: the session is left alone, words are counted
  micTest('plain'); out.noEar = [MT.run, recs.length]; const old = TK.trail = {at: 0, ev: [], more: 0};
  MT.ear = 'on'; micTest('plain'); micTest('switch'); out.one = [MT.runs.length, types.splice(0), /data-mictest="plain" disabled/.test(micTestSheet()), micTestSheet().includes('Starting the mic')];
  now += 60; last().onaudiostart(); out.live = micTestSheet().includes('one two three');
  now += 300; last().onresult({results: [[{transcript: 'secret words'}]]}); await go(5000); out.stops = last().stops; last().onend();
  out.plain = [ran().says, MIC.rec, MT.run, types.splice(0), PAST.words];
  // 2: the switch; no words; the end never comes
  micTest('switch'); out.sw = types.splice(0); now += 50; last().onaudiostart(); await go(5000); last().onerror({error: 'aborted', message: 'No speech detected'}); await go(3000); out.aborted = last().aborted; await go(1500);
  out.noWords = [ran().says, MIC.rec, MT.run]; out.evs = evs();
  // 3: after the silent sound, with or without its end; a reply that comes first
  let n = recs.length; types = []; micTest('sound'); await settle(); out.before = [recs.length - n, plays, types.slice()]; el.onended(); out.after = [recs.length - n, types.slice()]; last().onstart(); await go(8000); out.slow = last().stops; last().onend();
  out.never = ran().says; n = recs.length; micTest('sound'); await go(1500); out.noEnd = recs.length - n; last().onend();
  n = recs.length; micTest('sound'); TK.state = 'speaking'; el.onended(); out.first = [recs.length - n, MT.run]; micTest('plain'); out.reading = [recs.length - n, notes.length]; TK.state = '';
  // 4: the level, and no recognizer; the mic is let go; the device's name is not kept
  n = recs.length; micTest('level'); await settle(); out.busy = !!MIC.rec; await go(5100); out.level = [recs.length - n, ran().says, stopped, MIC.rec, MT.run]; out.levelEvs = evs();
  refuse = 'NotAllowedError'; micTest('level'); await settle(); out.refused = [ran().says, MIC.rec]; refuse = null;
  // left, and a listen that takes the mic
  micTest('level'); await settle(); S.sheet = ''; await go(400); out.left = [MT.run, stopped]; S.sheet = 'mictest';
  micTest('plain'); document.hidden = true; await go(400); out.hidden = last().stops; last().onend(); document.hidden = false; out.hid = MT.run;
  asleep = true; micTest('level'); await settle(); await go(5100); out.asleep = ran().says; out.trail = TK.trail === old;
  MIC.rec = {}; micTest('plain'); out.inUse = [MT.run, notes.length]; MIC.rec = null;
  micTestSheet(); await micCopyText('Mic test', micTestText()); out.copy = copied; out.toast = notes[notes.length - 1]; out.spoke = spoke;
  console.log(JSON.stringify(out));
})();`);
"""


def test_mic_test_b162b1(tmp: Path) -> None:
    """B162b1: the Mic test: each try sets what it says, ends, lets the mic go, and its report holds no words and no
    device name; a mic report says what the page did before the press."""
    page = W.PAGE.read_text(encoding='utf-8')
    check('data-sheet="mictest">Mic test…<' in page, 'Talk settings opens it')
    if not shutil.which('node'):
        print('  (no node here: the Mic test script test is skipped)')
        return
    (tmp / 'driver.js').write_text(MICTEST_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs the Mic test', r.stderr[-1500:])
    o = json.loads(r.stdout or '{}')
    eq(o.get('one'), [1, [], True, True], 'one try at a time, the session left as it is, and says the mic starts')
    eq((o.get('live'), o.get('stops')), (True, 1), 'speak once the mic is on; 5 s later it stops')
    eq(o.get('plain'), ['Heard 12 letters', None, None, [], 1], 'letters, the mic free, counted')
    eq((o.get('noEar'), o.get('trail')), ([None, 0], True), 'earbuds said first; the last listen keeps its report')
    check('the sound reader was suspended' in o.get('asleep', ''), 'a reader that sleeps is no silence', o.get('asleep'))
    eq((o.get('sw'), o.get('aborted')), (['play-and-record'], True), 'the switch; no end: aborted')
    eq(o.get('noWords'), ['The mic was on, no words (aborted: No speech detected)', None, None], 'and over by force')
    check('50 ms audiostart' in o['evs'] and 'audio session play-and-record' in o['evs'], 'its events with their ms', o['evs'])
    eq((o.get('before'), o.get('after')), ([0, 1, []], [1, ['play-and-record']]), 'the silent sound ends first, then the recognizer')
    eq((o.get('slow'), o.get('never'), o.get('noEnd')), (1, 'The mic did not start (no error)', 1), 'a mic that never starts is stopped; a sound with no end goes on')
    eq((o.get('first'), o.get('reading')), ([0, None], [0, 1]), 'a reply that reads is not listened over')
    eq((o.get('busy'), o.get('level')), (True, [0, 'Loudest 0.250, sound in 100% of the time', 1, None, None]), 'the level, with no recognizer')
    check('another mic' in o['levelEvs'] and 'level 0.250' in o['levelEvs'], 'the input and levels', o['levelEvs'])
    eq(o.get('refused'), ['No sound was read (NotAllowedError)', None], 'refused says so')
    eq((o.get('left'), o.get('hidden'), o.get('hid')), ([None, 2], 1, None), 'the sheet closed or the page hidden ends it')
    eq(o.get('inUse'), [None, 2], 'a mic in use is left alone')
    check('earbuds on' in o['copy'] and 'page open ' in o['copy'] and 'listens before: 0 with words' in o['copy'], 'the report', o['copy'][:400])
    check('secret' not in o['copy'].lower(), 'no words, no device name')
    eq((o.get('toast'), o.get('spoke')), ('Mic test copied: paste it into your reply', 0), 'copied; speechSynthesis not touched')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_mic_test_b162b1),in_tmp(test_talk_f93), in_tmp(test_listen_heard_nothing_b132), in_tmp(test_talk_new_chat_f157), in_tmp(test_talk_reply_heard_b133), in_tmp(test_chat_box_f115), in_tmp(test_mic_aborted_b162), in_tmp(test_sound_b178), in_tmp(test_stop_speaking_b174), in_tmp(test_talk_settings_f124), in_tmp(test_home_talk_f164)]))
