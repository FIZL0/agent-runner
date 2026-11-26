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


BACK_DRIVER = SCROLL_DRIVER.split('eval(logic')[0].replace('talkBack = () => {}, talkLate = () => true, talkAway = () => {}, ', 'talkAway = () => { S.aways = (S.aways || 0) + 1 }, ') \
    .replace("store = {get: () => '', set() {}}", "kept = {}, store = {get: k => kept[k] || '', set(k, v) { kept[k] = v }}") \
    .replace("boxKey = () => S.thread || 'home'", "boxKey = () => S.thread || (S.view === 'talk' ? 'talk' : 'home')") + r"""
const feedHTML = () => CHAT, feedEnd = () => '', sessRow = feedEnd, keysRow = feedEnd, isNew = () => false, modelOf = () => '';
const tab = {}, tabStore = {get: k => tab[k] || '', set: (k, v) => { tab[k] = v }}, ears = {}, hear = (t, f) => { (ears[t] = ears[t] || []).push(f) };
const fire = (t, e) => (ears[t] || []).forEach(f => f(e || {})), DK = {rec: null, key: ''}, MIC = {rec: null, next: null}, TM_KEY = 'ar-talkmode'; let TALK_FOR = ':a run';
let why = '', now = 1e6; const micWhy = () => why, kbFocus = t => { document.activeElement = t }; Date.now = () => now;
document.addEventListener = hear; window.addEventListener = hear; HI.key = '';
ta.matches = s => s === '[data-in]'; ta.blur = () => { document.activeElement = null }; ta.focus = () => { document.activeElement = ta };
const slice = (a, z) => page.slice(page.indexOf(a), page.indexOf(z, page.indexOf(a)));
""" + 'eval(logic' + SCROLL_DRIVER.split('eval(logic')[1].split("+ grab('async function send(')")[0] + r"""
  + slice('const talkTyping=', '/* F157: the Talk chats left') + `
const talkDraw = () => $('dock').classList.toggle('typing', talkTyping());
const out = {}, at = () => [$('dock').cls.has('typing'), document.activeElement === ta, kept.talk || ''];
const go = (v, t) => { S.view = v; S.thread = t || null; render(true) };
const type = () => { go('talk'); talkMode('type'); ta.value = 'half a mess'; kept.talk = ta.value };
const hide = ms => { document.hidden = true; fire('visibilitychange'); now += ms; document.hidden = false; fire('visibilitychange') };
type(); out.typing = at();
render(); CHAT += ' m3:40'; render(); render(true); out.redrawn = at();
go('home'); go('talk'); out.view = at(); out.put = ta.value;
const left = (v, t) => { go('talk'); S.aways = 0; render(); S.sheet = 'talk'; render(); S.sheet = ''; const on = S.aways; go(v, t); return [on, S.aways > 0] };
out.ways = [left('home'), left('plan'), left('talk', 'c1'), left('talk', '@s1')]; type();

talkMode('type'); out.again = [...at(), ta.value];
type(); go('talk', 'c1'); document.activeElement = ta; go('talk'); out.chat = at();
go('talk', 'c1'); document.activeElement = ta; go('talk'); out.chatBox = at();
type(); hide(59999); out.moment = at();
hide(60000); out.hidden = at();
type(); fire('pagehide'); now += 60000; fire('pageshow', {persisted: true}); out.bfcache = at();
const reload = ms => { type(); fire('pagehide'); now += ms; lastPlace = null; go('talk'); return at() };
out.refresh = reload(2000); out.reopened = reload(60000);
type(); fire('pagehide'); TALK_FOR = ':b'; lastPlace = null; go('home'); fire('pagehide'); TALK_FOR = ':a run'; lastPlace = null; go('talk'); out.project = at();
type(); lastPlace = null; go('talk'); out.noStamp = at();
type(); hide(1000); hide(59999); out.twice = at()[0];
let stops = 0; DK.key = 'talk'; DK.rec = MIC.rec = {stop() { stops++ }}; go('home'); go('talk'); out.dictation = [stops, DK.put]; DK.rec = MIC.rec = null;
why = 'no mic'; go('talk', 'c1'); document.activeElement = ta; go('talk'); out.noMic = at();
console.log(JSON.stringify(out));`);
"""


def test_talk_back_b802(tmp: Path) -> None:
    """B802: coming back to Talk, or to its tab after a minute, shows the mic and keeps the box's words as its draft;
    a redraw on Talk, a moment in another app or a refresh of the page leaves typing on."""
    if not shutil.which('node'):
        print('  (no node here: the back to Talk script test is skipped)')
        return
    (tmp / 'driver.js').write_text(BACK_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs the way back to Talk', r.stderr[-900:])
    got = json.loads(r.stdout or '{}')
    words = 'half a mess'
    on, box, mic = [True, True, words], [True, words], [False, False, words]
    eq(got.get('ways'), [[0, True]] * 4, "B836: each way out of Talk says it was left, a redraw or a sheet over it does not")
    eq((got.get('typing'), got.get('redrawn')), (on, on), 'a redraw, or a reply landing, leaves typing on and the focus in the box')
    eq((got.get('view'), got.get('put')), (mic, words), 'from another view: the mic, no focus, the words kept')
    eq(got.get('again'), [*on, words], 'and they come back with the keyboard button')
    eq((got.get('chat'), got.get('chatBox')), (mic, mic), "from a chat too, and its box's focus is not handed on")
    eq(got.get('moment'), on, 'a tab hidden for less than a minute is not left')
    eq((got.get('hidden'), got.get('bfcache')), (mic, mic), 'back to the tab after a minute: the mic')
    eq(got.get('refresh'), on, 'a refresh of the page while typing leaves it on')
    eq((got.get('reopened'), got.get('noStamp')), (mic, mic), 'a page opened again later: the mic')
    eq(got.get('project'), mic, "back from another project's page: the mic")
    eq(got.get('twice'), True, 'two short trips are not one long one')
    eq(got.get('dictation'), [1, True], 'dictation into the box stops, and takes no focus')
    eq(got.get('noMic'), on, 'where the mic cannot be used the box stays as it was')


ATTS_DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const grab = s => { const i = page.indexOf(s); return page.slice(i, page.indexOf('\n}\n', i) + 2) + '\n' };
const line = s => { const i = page.indexOf(s); return page.slice(i, page.indexOf('\n', i)) + '\n' };
const sent = [];
const env = {S: {view: 'home', thread: null, atts: {home: [{name: 'a.png', path: '/up/a.png'}]}}, I: {file: ''}, ok: true,
  viewOf: v => v, render: () => {}, esc: s => String(s), TK: {starting: [], gen: 0}, act: async (n, a) => { sent.push(a.text); return {ok: env.ok} }};
env.env = env; env.sent = sent;
const known = new Proxy(env, {has: () => true, get: (t, k) => k === Symbol.unscopables ? undefined : k in t ? t[k] : k in globalThis ? globalThis[k] : () => ''});
new Function('known', 'env', 'sent', 'with (known) {' + line('function goView(') + line('function attsMove(') + grab('function compose(')
  + grab('async function talkSend(') + line('const talkMic=') + 'env.goView=goView;env.talkSend=talkSend;env.talkAtts=talkMic;}')(known, env, sent);
(async () => {
  env.goView('talk');
  const moved = [Object.keys(env.S.atts), env.S.view, env.talkAtts().includes('a.png')];
  env.ok = false; const failed = [await env.talkSend('look'), (env.S.atts.talk || []).length];
  env.ok = true; const went = [await env.talkSend('look'), env.S.atts.talk === undefined];
  console.log(JSON.stringify({moved, failed, went, sent}));
})();
"""


def test_talk_atts_b856(tmp: Path) -> None:
    """B856: Home's attachments go along to Talk, show over the mic, and spoken words send them."""
    if not shutil.which('node'):
        print('  (no node here: the Talk attachments test is skipped)')
        return
    (tmp / 'driver.js').write_text(ATTS_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs Talk with attachments', r.stderr[-900:])
    got = json.loads(r.stdout or '{}')
    eq(got.get('moved'), [['talk'], 'talk', True], "Talk from Home takes Home's attachments, shown over the mic")
    eq(got.get('failed'), [False, 1], 'a send that fails keeps them')
    eq(got.get('went'), [True, True], 'a send that goes takes them')
    check(all('/up/a.png' in m and 'look' in m for m in got.get('sent', [])) and len(got.get('sent', [])) == 2, 'the words carry the path', got)


def test_talk_slow_check_b835(tmp: Path) -> None:
    """B835: the Talk brief says what it checks before a slow check, and keeps commands short."""
    from agent_runner import control as CT
    b = CT.TALK_BRIEF
    check('first say in one short spoken sentence what you are checking' in b, 'says what it checks first', b)
    check('under about twenty seconds' in b and 'in the background' in b, 'short commands, longer ones in the background', b)
    check('reading it out. Before a check' in b, 'the rules sit between whole sentences', b)
    eq(CT.TALK_TAG, '(Talk: answer as speech.) ', 'the reminder is unchanged')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_home_talk_f164), in_tmp(test_mic_test_b162b1), in_tmp(test_talk_back_b802), in_tmp(test_talk_atts_b856), in_tmp(test_talk_slow_check_b835)]))
