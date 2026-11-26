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
from test_web_talk import HOLD_DRIVER, MIC_DRIVER, DICT_DRIVER  # noqa: E402
from _web import TODO, fake_repo, get, post, LOGIC_DRIVER, logic_js, in_tmp  # noqa: E402


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
const listen = () => {}, micWhy = () => '', store = {get: () => ''}, tabStore = store, TM_KEY = 'tm';
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
let TS; const micWhy = () => '', TM_KEY = 'tm', store = {get: k => kept[k] || ''}, tabStore = store, talkWaitName = () => 'c5', talkSet = (k, v) => { TS = {...TS, [k]: v} };
const RUN_VERSION = '', DK = {};
// a send waits for its reply, as talkSend does
const talkSend = async t => { sent.push(t); if (TK.state !== 'speaking') TK.state = 'thinking'; awaitReply() };
const awaitReply = () => { TK.wait = {n: 'c5', since: 0, at: now, last: '', said: ''}; S.feeds.c5 = {entries: []} };
const lands = t => { if (!TK.wait) awaitReply(); S.feeds.c5.entries = [{kind: 'you', text: 'x'}, {kind: 'say', text: t}]; talkHear('c5'); talkHear('c5') };
const press = k => { const b = {}, e = {target: {closest: s => s === k ? b : null}, button: 0, pointerId: 1, pointerType: 'touch', detail: 1}; return e };
eval(logic + `TS = talkSetParse('');` + page.slice(page.indexOf('/* F158: run speech:'), page.indexOf('const talkTyping='))
 + line('const chatShown=') + grab('function talkAway(') + line('const talkTyping=') + line('function setHTML(') + line('const MIC=')
 + ['micWhenFree', 'micFree', 'talkDraw', 'talkHear', 'speak', 'listen', 'hear', 'micSent', 'keptSend', 'earEnd', 'micStop'].map(f => grab('function ' + f + '(')).join('') + line('function hush(')
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


AWAY_DRIVER = READ_DRIVER.split('(async () => {')[0].replace('addEventListener = () => {};', 'addEventListener = document.addEventListener;') + r"""
` + line("addEventListener('pagehide',talkAway)") + `
const go = (v, t) => { S.view = v; S.thread = t || null; ` + line('  if(!HOME_PAGE&&!chatShown())talkAway()') + ` };
(async () => {
  const out = {}; await settle(); const run = AU.got; AU.ok = true;
  for (const kind of ['own', 'run']) {
    AU.got = kind === 'run' ? run : null; const o = out[kind] = {ways: []};
    const begin = async () => { if (kind === 'run') await settle(); else { us[0].onstart(); ss.speaking = true } };
    const count = () => kind === 'run' ? plays.length : us.length;
    for (const [v, t] of [['home'], ['plan'], ['talk', 'c1']]) {
      over(); TS.auto = true; lands('One here. Two.'); await begin(); lands('Second reply.'); const n = count(), starts = recs.length; order.length = 0;
      go(v, t); const quiet = kind === 'run' ? AU.el.paused !== false : order.includes('cancel'); ss.speaking = false;
      if (kind === 'own') us[0].onend({type: 'end'});
      await settle(); await look(4); const away = [TK.state, TK.later.length, count() - n];
      go('talk'); await settle(); await look(4); o.ways.push([quiet, ...away, TK.state, count() - n, recs.length - starts]); TS.auto = false;
    }
    // a clip on its way when Talk is left is not played
    over(); lands('One here. Two.'); go('home'); await settle(); await look(3); o.early = [TK.state, kind === 'run' ? plays.length : order.includes('cancel')]; go('talk');
    // a reply that lands while away: not read, nor on the way back; seen away once and then back: the same
    over(); go('home'); lands('Late reply.'); await settle(); const at = [TK.state, count()]; go('talk'); await settle(); await look(3); o.late = [...at, TK.state, count(), TK.wait];
    over(); go('home'); awaitReply(); S.feeds.c5.entries = [{kind: 'you', text: 'x'}, {kind: 'say', text: 'Late.'}]; talkHear('c5'); go('talk'); talkHear('c5'); await settle(); o.seen = [TK.state, count()];
    // gone and back before it lands: read; and a play button's reading stops too
    over(); awaitReply(); go('home'); go('talk'); lands('In time.'); await begin(); o.inTime = TK.state;
    over(); speak('By hand.', 'k'); await begin(); go('home'); o.hand = [TK.playing, kind === 'run' ? AU.el.paused !== false : order.includes('cancel')]; go('talk');
    over(); lands('One here. Two.'); await begin(); order.length = 0; fire('pagehide', {}); o.page = [TK.state, kind === 'run' ? AU.el.paused !== false : order.includes('cancel')];
    // nothing is read: leaving does not touch the browser's voice (B132)
    over(); go('home'); o.none = order.length; go('talk');
  }
  console.log(JSON.stringify(out));
})();`);
"""


def test_talk_left_b836(tmp: Path) -> None:
    """B836: leaving Talk for another view or chat stops the reply being read, by the run's clips or the browser's voice;
    the rest of it, what waits and what lands while away are not read, then or on the way back."""
    if not shutil.which('node'):
        print('  (no node here: the leaving Talk script test is skipped)')
        return
    (tmp / 'driver.js').write_text(AWAY_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs the way out of Talk', r.stderr[-900:])
    got = json.loads(r.stdout or '{}')
    for kind in ('own', 'run'):
        o = got.get(kind) or {}
        eq(o.get('ways'), [[True, '', 0, 0, '', 0, 0]] * 3, f'{kind}: to a view or a chat: the sound stops, nothing more is read, nor back in Talk, and no auto listen')
        eq(o.get('early'), ['', 0 if kind == 'run' else True], f'{kind}: nor a sound not begun yet')
        eq(o.get('late'), ['', 0, '', 0, None], f'{kind}: a reply that lands while away is not read')
        eq(o.get('seen'), ['', 0], f'{kind}: nor one first seen while away')
        eq(o.get('inTime'), 'speaking', f'{kind}: back before it lands: it is read')
        eq(o.get('hand'), ['', True], f"{kind}: a play button's reading stops too")
        eq(o.get('page'), ['', True], f"{kind}: another project's page stops it too")
        eq(o.get('none'), 0, f'{kind}: with nothing read, leaving makes no speechSynthesis call')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_sound_b178), in_tmp(test_stop_speaking_b174), in_tmp(test_talk_settings_f124), in_tmp(test_talk_left_b836)]))
