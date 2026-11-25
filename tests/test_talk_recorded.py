"""Talk, Recorded, the page: the mic's sound goes to the run and its words are sent (F161b).

    python3 tests/test_talk_recorded.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from _check import check, eq, report
from agent_runner import recorded as R  # noqa: E402
from agent_runner import web as W  # noqa: E402
from _web import in_tmp  # noqa: E402
from test_web_talk import READ_DRIVER  # noqa: E402

# the recorder stubbed: a stream of given pieces of sound, and the run's /recorded route
REC_DRIVER = (READ_DRIVER.split('(async () => {')[0].replace('const window = {', 'const window = {isSecureContext: true, AudioWorkletNode: 1, ', 1)
              .replace("const fetch = async (p, o) => { if (!o)", "const fetch = async (p, o) => { if (p === 'recorded') return route(o); if (!o)", 1)
              .replace('class Audio {', r"""
let engine = {ok: true, engine: true, why: '', model: 'm', seconds: 120}, answer = 'hello run', posts = [], asks = 0, deny = '', hold = null, ctxs = [], gets = 0;
const route = async o => { if (!o) { gets++; return {ok: true, json: async () => engine} }
  posts.push(o.body); const a = typeof answer === 'function' ? answer() : answer;
  if (a === 'net') throw new TypeError('Load failed');
  if (a === 'hang') return new Promise((y, no) => o.signal.addEventListener('abort', () => no(Object.assign(new Error('x'), {name: 'AbortError'}))));
  if (a && a.status) return {ok: false, status: a.status, json: async () => ({ok: false, out: a.out})};
  return {ok: true, status: 200, json: async () => ({ok: true, words: a})} };
class Track { constructor() { this.readyState = 'live'; this.enabled = true } stop() { this.readyState = 'ended' } }
class AudioContext { constructor() { this.sampleRate = 48000; this.state = 'running'; this.audioWorklet = {addModule: async () => {}}; ctxs.push(this); this.destination = {} }
  async resume() { this.state = 'running' } async suspend() { this.state = 'suspended' } async close() { this.state = 'closed' }
  createMediaStreamSource() { return {connect() {}} } }
let node = null, tracks = [], marks = true;
class AudioWorkletNode { constructor() { node = this; this.port = {postMessage(m) { if (m === 'mark' && marks) this.onmessage({data: null}) }, onmessage: null} } connect() {} }
window.AudioContext = AudioContext;
const getUserMedia = async () => { asks++; if (hold) await hold; if (deny) throw Object.assign(new Error('no'), {name: deny}); const t = new Track(); tracks.push(t); return {getTracks: () => [t], getAudioTracks: () => [t]} };
class Audio {""", 1)
              .replace("navigator = {language: 'en-US', userAgent: 'iPhone',", "navigator = {mediaDevices: {getUserMedia}, language: 'en-US', userAgent: 'iPhone Version/27.0 Mobile Safari/604.1',", 1)
              .replace("+ page.slice(page.indexOf(\"document.addEventListener('visibility", "+ page.slice(page.indexOf('/* --- F161b: Recorded'), page.indexOf('/* B162b1: the Mic test')) + page.slice(page.indexOf(\"document.addEventListener('visibility", 1)
              .replace("talkSet = (k, v) => { TS = {...TS, [k]: v} }", "talkSet = (k, v) => { TS = {...TS, [k]: v}; if (k === 'way') recPick() }", 1)
              .replace('const micWhy = () => \'\'', "const micWhy = () => micProblem(window.isSecureContext !== false, true)", 1) + r"""
let may = 'prompt', queries = 0; navigator.permissions = {query: async () => { queries++; return {state: may} }};
// before: sound with no listen
const before = (s, v) => { for (let i = 0; i < s * 48000 / 2048; i++) node.port.onmessage({data: new Float32Array(2048).fill(v)}) };
const shown = async () => { recLook(); await settle(); await settle() };
// s seconds of sound, in the worklet's pieces; loud: somebody speaks
const sound = (s, loud = true) => { for (let i = 0; i < s * 48000 / 2048; i++) if (REC.now) node.port.onmessage({data: new Float32Array(2048).fill(loud ? 0.2 : 0.0005)}) };
const tail = async () => { await tick(200); await tick(20); await settle() };
const down = () => fire('pointerdown', press('[data-mic]')), up = () => fire('pointerup', press('[data-mic]'));
const fresh = () => { if (TK.rec && TK.rec.recorded) TK.rec.abort(); recFree(); hush(); TK.ear = TK.rec = TK.wait = null; MIC.rec = MIC.next = null; TK.state = TK.note = ''; TK.hold = false; sent.length = notes.length = posts.length = recs.length = types.length = 0; asks = 0; deny = ''; hold = null; answer = 'hello run'; REC.no = ''; REC.engine = engine; TS.mic = 'tap'; TS.way = 'recorded'; TS.auto = false; TS.read = true; S.view = 'talk'; AU.got = null; timers = []; may = 'prompt'; REC.shut = REC.query = REC.sign = REC.denied = false; REC.ends = REC.timer = REC.coming = 0; document.hidden = false; kept.tm = '' };
(async () => {
  const out = {}; await settle();
  out.start = TS.way; click('[data-mic]'); out.browser = [recs.length, asks]; mic().end(); await settle(); await tick(250); click('[data-mic]'); mic().end();
  fresh(); click('[data-mic]'); const first = shows()[4]; await settle(); sound(1); out.line = [first, shows()[4], types.slice()]; click('[data-mic]'); await tick(200);
  answer = () => { out.reading = shows()[4]; return 'what is running' }; await tick(20); await settle();
  const b = Buffer.from(posts[0]); out.wav = [b.toString('latin1', 0, 4), b.readUInt32LE(24), b.readUInt16LE(22), b.readUInt16LE(34), b.length - 44 === b.readUInt32LE(40), Math.round(b.length / 3200), Math.round(b.readInt16LE(1000) / 327.67)];
  out.tap = [sent.slice(), TK.state, recs.length, MIC.rec, types[types.length - 1]]; out.rest = [REC.open.track.enabled, REC.open.ctx.state, tracks.length];
  out.report = TK.trail.ev.join(' | ');
  // the kept stream: no second ask
  TK.wait = null; TK.state = ''; click('[data-mic]'); await settle(); sound(1); out.again = [REC.open.track.enabled, asks]; click('[data-mic]'); await tail(); out.two = [sent.length, asks];
  // sound with no listen is kept nowhere
  node.port.onmessage({data: new Float32Array(2048)}); out.stray = posts.length;
  // Tap: a pause ends it; nobody speaks: no clip
  fresh(); click('[data-mic]'); await settle(); sound(1); sound(1.5, false); out.notYet = TK.ear.stopped; sound(1, false); await tail(); out.pause = sent.slice();
  fresh(); click('[data-mic]'); await settle(); sound(9, false); await tail(); out.silent = [posts.length, sent.length, TK.note.includes('no-speech'), TK.state];
  // the run hears no words; a stop before any sound
  fresh(); answer = ''; click('[data-mic]'); await settle(); sound(1); click('[data-mic]'); await tail(); out.noWords = [sent.length, TK.note.startsWith('Heard nothing'), TK.state];
  fresh(); click('[data-mic]'); click('[data-mic]'); await settle(); out.early = [posts.length, TK.state, TK.note.includes('before it was on'), MIC.rec, REC.open.track.enabled];
  // Hold: silence never ends it, the release sends
  fresh(); TS.mic = 'hold'; down(); await settle(); sound(1); sound(12, false); out.held = [TK.state, posts.length]; up(); await tail(); out.hold = sent.slice();
  // auto listen: one silent turn and it stops
  fresh(); TK.again = true; listen(); await settle(); sound(9, false); await tail(); out.auto = [posts.length, TK.state, TK.note];
  fresh(); TS.auto = true; lands('One here.'); us[us.length - 1].onstart(); us[us.length - 1].onend({type: 'end'}); await settle(); out.autoOn = [TK.state, asks, recs.length]; sound(1); sound(3, false); await tail(); out.autoSent = sent.slice();
  // a reply that lands meanwhile waits until the words are sent
  fresh(); TS.mic = 'hold'; down(); await settle(); lands('A reply.'); sound(1); let n = us.length; up(); await tick(200); out.waits = us.length - n; await tick(20); await settle(); await look(); out.read = us.length - n;
  // dropped: nothing is posted; dictation or the browser's recognizer gets the mic
  fresh(); click('[data-mic]'); await settle(); sound(1); const r = TK.rec; TK.ear = TK.rec = null; r.stop(); await tail(); out.dropped = [posts.length, sent.length, MIC.rec];
  fresh(); click('[data-mic]'); await settle(); sound(1); click('[data-mic]'); await tail(); const t0 = REC.open.track; TK.wait = null; TK.state = ''; TS.way = 'browser'; click('[data-mic]'); out.one = [t0.readyState, REC.open, recs.length]; mic().end();
  // the limit
  fresh(); TS.mic = 'hold'; down(); await settle(); sound(125); await tail(); out.limit = [posts.length, posts[0] && posts[0].length, sent.length, notes.length]; up();
  // fallback: no engine, no https, refused, no sound
  fresh(); REC.engine = {engine: false, why: 'no speech recognition is installed'}; const row0 = recRow(); gets = 0; click('[data-mic]'); out.noEngine = [recs.length, asks, row0.includes('not used now: no speech recognition is installed'), gets]; mic().say('x'); click('[data-mic]'); mic().end();
  fresh(); window.isSecureContext = false; out.plain = recRow().includes('needs https'); window.isSecureContext = true;
  fresh(); deny = 'NotAllowedError'; click('[data-mic]'); await settle(); out.refused = [recs.length, TK.state, recRow().includes('did not let the page use the mic'), notes.length]; mic().say('browser words'); click('[data-mic]'); mic().end(); out.refusedSent = sent.slice(); TK.state = ''; TK.wait = null; click('[data-mic]'); out.refusedNext = [asks, recs.length]; mic().end(); await settle(); TK.ear = null; MIC.rec = null;
  fresh(); REC.no = 'x'; talkSet('way', 'recorded'); out.picked = REC.no;
  fresh(); deny = 'NotReadableError'; click('[data-mic]'); await settle(); out.busy = [recs.length, REC.no]; mic().end(); await settle();
  fresh(); click('[data-mic]'); await settle(); await tick(3000); out.mute1 = [asks, recs.length]; await tick(3000); out.mute2 = [asks, recs.length, TK.state]; mic().end();
  // Allow is under way, the listen is stopped and started: one ask
  fresh(); let yes; hold = new Promise(y => yes = y); click('[data-mic]'); click('[data-mic]'); TK.note = ''; click('[data-mic]'); yes(); await settle(); out.oneAsk = [asks, tracks.slice(-1)[0].enabled, TK.state]; sound(1); click('[data-mic]'); await tail(); out.oneAskSent = sent.length;
  // the run: no answer once, twice; busy; late
  let k = 0; fresh(); answer = () => k++ ? 'late words' : 'net'; click('[data-mic]'); await settle(); sound(1); click('[data-mic]'); await tail(); await tick(500); out.retry = sent.slice();
  fresh(); answer = 'net'; click('[data-mic]'); await settle(); sound(1); click('[data-mic]'); await tail(); await tick(500); out.lost = [posts.length, sent.length, TK.state, TK.note, MIC.rec];
  fresh(); answer = {status: 503, out: 'the speech recognition is busy'}; click('[data-mic]'); await settle(); sound(1); click('[data-mic]'); await tail(); out.busyRun = [posts.length, TK.note, recs.length];
  fresh(); answer = 'hang'; click('[data-mic]'); await settle(); sound(1); click('[data-mic]'); await tail(); await tick(5000); out.slow = TK.state; await tick(50000); out.hung = [posts.length, TK.state, TK.note];
  // the mic goes away: what was recorded goes out; Talk left: the same, and the mic is released
  fresh(); click('[data-mic]'); await settle(); sound(1); REC.open.track.onended(); await tail(); out.ended = [sent.slice(), REC.open];
  fresh(); click('[data-mic]'); await settle(); sound(1); const o = REC.open; S.view = 'home'; await tick(500); await tail(); await tick(500); out.left = [sent.length, REC.open, o.track.readyState, o.ctx.state];
  out.rows = [(TS.way = 'browser', recRow().includes('Website Settings')), (TS.way = 'recorded', recRow().includes('Website Settings, Microphone, Allow')), isSafari('Mozilla Chrome/140 Safari/537')];
  out.parse = [talkSetParse('{"way":"recorded"}').way, talkSetParse('{"way":"x"}').way];
  // F161c: the mic is open before the press, where the browser allows it
  fresh(); hush(); TK.state = ''; await shown(); out.noAsk = [queries > 0, asks, REC.open]; click('[data-mic]'); await settle(); sound(1); click('[data-mic]'); await tail(); TK.wait = null; TK.state = ''; out.pressed = [asks, !!REC.open, REC.open.track.enabled];
  fresh(); may = 'granted'; navigator.permissions.query = async () => { throw new TypeError('x') }; await shown(); out.cannotSay = asks; navigator.permissions.query = async () => ({state: may});
  fresh(); may = 'granted'; types.length = 0; await tick(500); await shown(); out.opens = [asks, TK.state, REC.now, types.slice(), shows()[4], shows()[1], els.mic.className, sent.length, posts.length];
  before(3, 0.1); out.kept = [REC.open.kept, REC.open.ring.length]; marks = false; click('[data-mic]'); out.atOnce = [TK.ear.on, shows()[4], asks]; before(0.2, 0.1); marks = true; node.port.onmessage({data: null}); sound(1); click('[data-mic]'); await tail();
  const w = posts[0] && Buffer.from(posts[0]); out.preroll = [w && Math.round((w.length - 44) / 3200), w && Math.round(w.readInt16LE(44 + 3200) / 327.67), w && Math.round(w.readInt16LE(44) / 327.67), REC.open.kept];
  before(1, 0.1); out.after = [REC.open.kept, REC.open.ring.length];
  // F161c2: held again while the last words are made: that hold's sound is kept, none from before it; let go again: dropped
  const heldAgain = async let2 => { fresh(); may = 'granted'; await shown(); before(1, 0.1); TS.mic = 'hold'; let say; answer = () => posts.length > 1 ? 'second' : 'first'; const gate = new Promise(y => say = y); const ask0 = Recorder.prototype.ask; Recorder.prototype.ask = async function (wav) { if (!posts.length) { const a = await ask0.call(this, wav); await gate; return a } return ask0.call(this, wav) };
    down(); sound(1); up(); await tail(); before(1, 0.1); const idle = REC.open.kept; down(); before(0.05, 0.3); before(1, 0.3); const held = Math.round(REC.open.kept / 4800); if (let2) { up(); before(0.1, 0.1) } const let0 = REC.open.kept; say(); await settle(); await settle(); Recorder.prototype.ask = ask0; if (!let2) { sound(1); up(); await tail() }
    const b2 = posts[1] && Buffer.from(posts[1]); return [idle, held, let0 > 0, posts.length, b2 ? Math.round((b2.length - 44) / 3200) : 0, b2 ? Math.round(b2.readInt16LE(44) / 327.67) : 0, sent.slice()] };
  out.heldAgain = await heldAgain(false); out.letAgain = await heldAgain(true);
  fresh(); may = 'granted'; await shown();
  // a reply: released, and open again after it
  TK.wait = null; TK.state = ''; before(1, 0.1); let k1 = REC.open; lands('A reply.'); out.reply = [REC.open === k1, k1.track.readyState, k1.track.enabled, k1.ctx.state, types[types.length - 1], TK.state, recLive()]; await tick(500); await shown(); before(1, 0.1); out.during = [REC.open === k1, k1.rest, k1.kept]; us[us.length - 1].onend({type: 'end'}); await shown(); out.afterReply = [REC.open === k1, recLive(), k1.track.enabled, REC.open.kept, types[types.length - 1]];
  // Talk hides: released at once; shown: open again
  k1 = REC.open; document.hidden = true; fire('visibilitychange', {}); out.hides = [k1.track.readyState, REC.open, types[types.length - 1], REC.sign]; document.hidden = false; fire('visibilitychange', {}); await settle(); out.backOn = !!REC.open;
  for (const [n, on, off] of [['left', () => S.view = 'home', () => S.view = 'talk'], ['thread', () => S.thread = 'c1', () => S.thread = null], ['test', () => S.sheet = 'mictest', () => S.sheet = ''], ['typing', () => kept.tm = 'type', () => kept.tm = '']]) { on(); await tick(500); out['rel_' + n] = REC.open; off(); await shown(); out['back_' + n] = !!REC.open }
  // hidden while it opens: closed; a press joins the opening: one ask
  fresh(); may = 'granted'; hold = new Promise(y => yes = y); await shown(); document.hidden = true; fire('visibilitychange', {}); yes(); await settle(); await settle(); out.hidOpening = [REC.open, tracks[tracks.length - 1].readyState];
  fresh(); may = 'granted'; hold = new Promise(y => yes = y); await shown(); click('[data-mic]'); yes(); await settle(); await settle(); out.joins = [asks, TK.state, TK.ear && TK.rec.on];
  // it cannot open by itself: not again until Talk shows anew, and the press asks
  fresh(); may = 'granted'; deny = 'NotReadableError'; await shown(); await tick(500); await shown(); out.failed = [asks, notes.length, REC.no]; deny = ''; click('[data-mic]'); await settle(); out.failedPress = [asks, recs.length, TK.rec.on];
  fresh(); may = 'granted'; await shown(); const gone = async () => { REC.open.track.readyState = 'ended'; REC.open.track.onended(); await shown() };
  // B804c: the mic taken away between listens: open again, 3 times, until Talk shows anew or a press listens
  k1 = REC.open; await gone(); out.taken = [asks, !!REC.open, REC.open !== k1, REC.shut, sent.length, TK.state]; await gone(); await gone(); out.taken3 = [asks, !!REC.open]; await gone(); await tick(500); await shown(); out.takenOut = [asks, REC.open, REC.shut]; S.view = 'home'; await tick(500); S.view = 'talk'; await shown(); out.takenBack = [asks, !!REC.open];
  await gone(); await gone(); await gone(); await gone(); const at0 = [asks, REC.open]; click('[data-mic]'); await settle(); await settle(); TK.rec.abort(); TK.ear = null; TK.state = ''; await settle(); await gone(); out.takenPress = [...at0, asks, !!REC.open];
  fresh(); may = 'granted'; await shown(); may = 'prompt'; await gone(); await tick(500); out.takenPrompt = [asks, REC.open];
  fresh(); may = 'granted'; await shown(); deny = 'NotReadableError'; await gone(); await tick(500); await shown(); out.takenBusy = [asks, REC.open, notes.length];
  fresh(); may = 'granted'; await shown(); click('[data-mic]'); await settle(); sound(1); await gone(); await tail(); TK.wait = null; TK.state = ''; await tick(500); await shown(); out.takenListen = [asks, REC.open, sent.slice()];
  fresh(); may = 'granted'; await shown(); TK.wait = null; lands('A reply.'); k1 = REC.open.rest; await gone(); const reads = REC.open; us[us.length - 1].onend({type: 'end'}); await shown(); out.takenReply = [k1, reads, asks, REC.open];
  // F161c3: a press that cuts a reply off wakes the same stream in the press, with none of the reply's sound in the clip
  fresh(); may = 'granted'; await shown(); TK.wait = null; lands('A reply.'); k1 = REC.open; before(1, 0.4); const cut0 = REC.open.kept; click('[data-mic]'); out.cutOff = [REC.open === k1, k1.track.enabled, k1.rest, types[types.length - 1]]; await settle(); out.cutOn = [asks, TK.state, !!(REC.now && REC.now.on)]; sound(1); click('[data-mic]'); await tail(); out.cutClip = [posts.length, sent.slice(), asks, cut0]; const cw = posts[0] && Buffer.from(posts[0]); out.cutSecs = cw ? (cw.length - 44) / 32000 : 0;
  // a press opened it and a new stream could ask: the same rest while a reply plays
  fresh(); click('[data-mic]'); await settle(); sound(1); click('[data-mic]'); await tail(); TK.wait = null; TK.state = ''; before(1, 0.1); k1 = REC.open; lands('A reply.'); before(1, 0.1); out.rests = [REC.open === k1, k1.track.enabled, k1.ctx.state, k1.kept, types[types.length - 1], asks]; us[us.length - 1].onend({type: 'end'}); await shown(); out.wakes = [REC.open === k1, k1.track.enabled, k1.ctx.state, asks, types[types.length - 1]];
  // a press with only what came before it sends nothing; the browser's way opens nothing
  fresh(); may = 'granted'; await shown(); before(2, 0.1); answer = 'stray'; click('[data-mic]'); click('[data-mic]'); sound(0.2); await tail(); out.onlyBefore = [posts.length, sent.length];
  fresh(); may = 'granted'; await shown(); REC.engine = {engine: false, why: 'x'}; await tick(500); out.gone = REC.open;
  fresh(); may = 'granted'; TS.way = 'browser'; await shown(); out.wayBrowser = [asks, REC.open];
  // B804a: the mic report says why the mic was not open at a press, what its opening took, and an empty answer
  const why = async () => { TK.wait = null; TK.state = ''; click('[data-mic]'); const t = TK.ear.trail; await settle(); await settle(); if (TK.rec) TK.rec.abort(); await settle(); return t.ev.map(x => x.replace(/^\\d+ ms /, '')).filter(x => /^(mic |permission)/.test(x)) };
  const anew = () => { fresh(); REC.why = REC.perm = ''; REC.took = null; TK.trail = null };
  anew(); hold = new Promise(y => yes = y); click('[data-mic]'); const tr = TK.ear.trail; await settle(); now += 900; yes(); await settle(); await settle(); out.none = tr.ev.join(' | '); answer = ''; sound(1); click('[data-mic]'); await tail(); out.empty = tr.ev.join(' | ');
  anew(); hold = new Promise(y => yes = y); click('[data-mic]'); const tr2 = TK.ear.trail; now += 50; click('[data-mic]'); now += 400; yes(); await settle(); await settle(); out.letGo = tr2.ev.join(' | ');
  anew(); may = 'granted'; await shown(); TK.wait = null; lands('A reply.'); out.whyReply = await why();
  anew(); click('[data-mic]'); await settle(); sound(1); click('[data-mic]'); await tail(); TK.wait = null; TK.state = ''; lands('A reply.'); out.whyRest = await why();
  anew(); may = 'granted'; await shown(); REC.open.track.onended(); out.whyEnded = await why();
  anew(); may = 'granted'; await shown(); REC.open.track.readyState = 'ended'; out.whyDead = await why();
  anew(); may = 'granted'; await shown(); document.hidden = true; fire('visibilitychange', {}); document.hidden = false; out.whyHidden = await why();
  anew(); may = 'granted'; await shown(); REC.open.ctx.state = 'interrupted'; out.whyCtx = await why();
  anew(); may = 'granted'; hold = new Promise(y => yes = y); await shown(); now += 300; TK.wait = null; click('[data-mic]'); const tr3 = TK.ear.trail; now += 100; yes(); await settle(); await settle(); out.whyOpening = tr3.ev.join(' | ');
  anew(); deny = 'NotReadableError'; out.whyFailed = await why();
  anew(); may = 'granted'; hold = new Promise(y => yes = y); deny = 'NotReadableError'; await shown(); now += 300; TK.wait = null; click('[data-mic]'); const tr4 = TK.ear.trail; now += 100; yes(); await settle(); await settle(); out.lost2 = tr4.ev.join(' | ');
  // B804b: the mic still opening is said, and a hold let go before or just after it opened
  const holds = () => { anew(); TS.mic = 'hold'; hold = new Promise(y => yes = y); down(); };
  const opens = async () => { yes(); await settle(); await settle() };
  holds(); await settle(); out.holdOpening = shows()[4]; now += 800; up(); await opens(); out.holdBefore = [TK.note, posts.length, TK.state];
  holds(); await settle(); now += 1500; await opens(); out.noSoundYet = shows()[4]; sound(0.2); out.holdOn = shows()[4]; now += 271; answer = ''; up(); await tail(); out.holdAfter = [TK.note, posts.length, sent.length];
  holds(); await settle(); now += 1500; await opens(); sound(0.2); now += 271; up(); await tail(); out.holdWords = sent.slice();
  holds(); await settle(); await opens(); sound(0.2); now += 2000; answer = ''; up(); await tail(); out.holdLong = TK.note;
  anew(); may = 'granted'; await shown(); before(1, 0.1); TS.mic = 'hold'; down(); out.holdOpen = shows()[4]; sound(0.2); now += 271; answer = ''; up(); await tail(); out.holdShort = TK.note;
  // a stream gone mute is opened afresh in the hold: not Listening meanwhile
  anew(); may = 'granted'; await shown(); before(1, 0.1); TS.mic = 'hold'; hold = new Promise(y => yes = y); down(); const l1 = shows()[4]; await tick(3000); const l2 = shows()[4]; await opens(); const l3 = shows()[4]; sound(0.2); out.afresh = [l1, l2, l3, shows()[4]]; answer = ''; now += 100; up(); await tail(); out.afreshNote = TK.note;
  // F161c1: the press that opens Talk starts the mic inside it; draws: Talk is drawn in the press (else a View Transition does later)
  const goTalk = (draws = true) => { fire('click', press('[data-view="talk"]')); if (draws) S.view = 'talk' };
  const away = () => { anew(); may = 'prompt'; S.view = 'home'; };
  away(); const c0 = ctxs.length; goTalk(); out.tpIn = [asks, ctxs.length - c0, types.slice(-1)[0]]; await settle(); await shown(); await settle(); out.tpOpen = [!!REC.open, TK.state, REC.now, posts.length, sent.length];
  click('[data-mic]'); out.tpMic = [TK.rec.on, asks, ctxs.length - c0]; sound(1); click('[data-mic]'); await tail(); out.tpSent = [sent.slice(), asks];
  TK.wait = null; TK.state = ''; S.view = 'home'; const tpo = REC.open; await tick(500); out.tpLeft = [REC.open, tpo.track.readyState]; goTalk(); await settle(); await shown(); out.tpBack = [asks, !!REC.open]; document.hidden = true; fire('visibilitychange', {}); out.tpHides = REC.open; document.hidden = false;
  away(); navigator.permissions.query = async () => { throw new TypeError('x') }; goTalk(); await settle(); await shown(); out.tpCannotSay = [asks, !!REC.open]; navigator.permissions.query = async () => ({state: may});
  // Talk drawn late; never drawn; hidden meanwhile
  away(); goTalk(false); recLook(); await settle(); const tl = !!(REC.open || REC.asking); S.view = 'talk'; await shown(); out.tpLate = [tl, !!REC.open, asks];
  away(); goTalk(false); await settle(); await settle(); const tn = !!REC.open; now += 1100; recLook(); out.tpNever = [tn, REC.open];
  away(); goTalk(false); await settle(); await settle(); document.hidden = true; fire('visibilitychange', {}); out.tpHidden = REC.open; document.hidden = false;
  // the mic pressed while Allow is under way joins it
  away(); hold = new Promise(y => yes = y); goTalk(); click('[data-mic]'); yes(); await settle(); await settle(); out.tpJoin = [asks, TK.rec && TK.rec.on];
  // refused: not asked again by itself, nor by the next Talk press; the mic asks, and once it listens Talk's press does
  away(); deny = 'NotAllowedError'; goTalk(); await settle(); await tick(500); await shown(); const r1 = [asks, notes.length, REC.no]; S.view = 'home'; await tick(500); goTalk(); await settle(); await shown(); out.tpRefused = [...r1, asks]; deny = ''; click('[data-mic]'); await settle(); await settle(); out.tpRefusedMic = [asks, TK.rec.on]; TK.rec.abort(); TK.ear = null; TK.state = ''; S.view = 'home'; await tick(500); goTalk(); await settle(); await shown(); out.tpRefusedOver = [asks, !!REC.open];
  away(); deny = 'NotAllowedError'; goTalk(); await settle(); deny = ''; may = 'granted'; S.view = 'home'; await tick(500); goTalk(); await shown(); const al = [asks, !!REC.open, REC.denied]; S.view = 'home'; await tick(500); may = 'prompt'; goTalk(); await settle(); await shown(); out.tpAllowed = [...al, asks, !!REC.open];
  away(); goTalk(false); await settle(); await settle(); fire('click', press('[data-view="plan"]')); S.view = 'plan'; await tick(500); out.tpElse = REC.open;
  away(); deny = 'NotAllowedError'; hold = new Promise(y => yes = y); goTalk(); click('[data-mic]'); yes(); await settle(); await settle(); out.tpRefusedJoin = [asks, recs.length, REC.no !== '']; mic().end(); await settle(); TK.ear = null; MIC.rec = null;
  // Talk already shown, a reply read, dictation, the browser's way: the press opens nothing
  anew(); goTalk(); out.tpShown = asks; away(); TK.state = 'speaking'; goTalk(); out.tpReads = asks; away(); DK.rec = {}; goTalk(); out.tpDict = asks; DK.rec = null; away(); TS.way = 'browser'; goTalk(); out.tpBrowser = asks;
  // the permission as it was before the ask, for the mic report
  away(); may = 'granted'; goTalk(); await settle(); await shown(); out.tpMay = REC.perm; away(); goTalk(); await settle(); await shown(); out.tpPrompt = REC.perm;
  console.log(JSON.stringify(out, (k, v) => v === undefined ? null : v));
})();`);
""")


def test_recorded_f161b(tmp: Path) -> None:
    """F161b: with a stubbed mic and route, a recording's words are sent by Tap, Hold and auto listen; what cannot record falls back."""
    page = W.page_html().decode()
    check('${recRow()}' in page.split('  talk(){', 1)[1].split('\n  },', 1)[0], 'Talk settings has the setting')
    check('recFree()' in page.split('function dictate(', 1)[1].split('\n}\n', 1)[0], 'dictation releases the mic first')
    check('recLoad();REC.timer=setTimeout(recLook,0)' in page, 'F161c: a reload on Talk looks whether the mic may open')
    if not shutil.which('node'):
        print('  (no node here: the recording script test is skipped)')
        return
    (tmp / 'driver.js').write_text(REC_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs the recordings', r.stderr[-900:])
    g = json.loads(r.stdout or '{}')
    eq((g.get('start'), g.get('browser')), ('browser', [1, 0]), "the default is the browser's recognition, with no recording")
    eq(g.get('line'), ['Starting the mic…', 'Listening…', ['play-and-record']], 'it says when it listens, in the audio session for the mic')
    eq(g.get('reading'), 'Getting the words…', 'and that the words are on their way')
    eq(g.get('wav'), ['RIFF', 16000, 1, 16, True, 10, 20], 'a 16 kHz mono 16-bit WAV of the second, as loud as it was')
    eq(g.get('tap'), [['what is running'], 'thinking', 0, None, 'play-and-record'], 'Tap: its words are sent, and the session stays the open mic\'s')
    eq(g.get('rest'), [True, 'running', 1], 'between listens the stream stays open')
    check('what is' not in (g.get('report') or 'what is') and 'clip, ' in g['report'], 'the mic report has no words', str(g.get('report')))
    eq((g.get('again'), g.get('two')), ([True, 1], [2, 1]), 'one ask for two listens')
    eq(g.get('stray'), 2, 'sound outside a listen goes nowhere')
    eq((g.get('notYet'), g.get('pause')), (False, ['hello run']), 'a pause of 2 s ends a Tap')
    eq(g.get('silent'), [0, 0, True, ''], 'nobody speaks: no clip leaves the page')
    eq(g.get('noWords'), [0, True, ''], 'no words: the line says so')
    eq(g.get('early'), [0, '', True, None, True], 'stopped before it was on: nothing is posted')
    eq((g.get('held'), g.get('hold')), (['listening', 0], ['hello run']), 'Hold: silence does not end it, letting go sends')
    eq(g.get('auto'), [0, '', 'Tap to talk'], 'auto listen: a silent turn ends it')
    eq((g.get('autoOn'), g.get('autoSent')), (['listening', 1, 0], ['hello run']), 'auto listen records after a reply, and sends')
    eq((g.get('waits'), g.get('read')), (0, 1), 'a reply waits for the words')
    eq(g.get('dropped'), [0, 0, None], 'a dropped listen posts nothing')
    eq(g.get('one'), ['ended', None, 1], "the browser's recognizer starts with the stream released")
    lim = g.get('limit') or [0, 0, 0, 0]
    check(lim[0] == 1 and lim[1] <= R.BYTES_MAX and lim[1] <= R.SECONDS_MAX * R.RATE * 2 and lim[2:] == [1, 1], 'the longest clip goes out, within the run\'s limit, and says so', str(lim))
    eq(g.get('noEngine'), [1, 0, True, 1], "no engine: the setting says why, the browser's recognition hears, and the run is asked again")
    eq(g.get('plain'), True, 'no secure page: the setting says so')
    eq((g.get('refused'), g.get('refusedSent')), ([1, 'listening', True, 1], ['browser words']), 'a refused mic: said, and the browser hears this same listen')
    eq(g.get('refusedNext'), [1, 2], 'no second ask after a refusal')
    eq(g.get('picked'), '', 'until Recorded is picked again')
    eq(g.get('busy'), [1, ''], 'a mic in use: the browser hears this listen, and the next one records')
    eq((g.get('mute1'), g.get('mute2')), ([2, 0], [2, 1, 'listening']), 'a stream with no sound is opened afresh once, then the browser hears')
    eq((g.get('oneAsk'), g.get('oneAskSent')), ([1, True, 'listening'], 1), 'one ask, whatever is pressed while it is open')
    eq(g.get('retry'), ['late words'], 'no answer: the clip is posted once more')
    eq(g.get('lost'), [2, 0, '', 'The run did not answer, so your words are lost. Try again', None], 'and then it says so')
    eq(g.get('busyRun'), [1, 'The run made no words: the speech recognition is busy', 0], "the run's reason, with no new try")
    eq((g.get('slow'), g.get('hung')), ('listening', [1, '', 'The run did not answer, so your words are lost. Try again']), 'a slow answer is waited for, not for ever')
    eq(g.get('ended'), [['hello run'], None], 'a mic that goes away: what was recorded goes out')
    eq(g.get('left'), [1, None, 'ended', 'closed'], 'Talk left: the words go out and the mic is released')
    eq(g.get('rows'), [False, True, False], "Safari's Allow for good, only with Recorded")
    eq(g.get('parse'), ['recorded', 'browser'], 'kept per browser')
    eq((g.get('noAsk'), g.get('pressed'), g.get('cannotSay')), ([True, 0, None], [1, True, True], 0), 'F161c: the page never asks by itself; the first press opens it, and it stays')
    eq(g.get('opens'), [1, '', None, ['play-and-record'], 'Tap to talk, the mic is open, not listening', 'Talk, the mic is open, not listening', 'mic open', 0, 0], 'allowed: open when Talk shows, and it says so; nothing listens or is sent')
    eq((g.get('kept'), g.get('after')), ([0, 0], [0, 0]), 'F161c2: with no listen on, every piece of sound is dropped at once, before a press and after a clip')
    eq(g.get('atOnce'), [True, 'Listening…', 1], 'a press listens in the press itself')
    p = g.get('preroll') or [0, 0, 0, 1]
    check(9 <= p[0] <= 11, 'the clip is the second since the press', str(p))
    eq(p[1:], [20, 20, 0], 'no sound from before the press in it, also what the worklet had in hand; sent sound is not kept for the next')
    h = g.get('heldAgain') or [1]
    check(h[0] == 0 and 9 <= h[1] <= 11 and h[2:4] == [True, 2] and 19 <= h[4] <= 22 and h[5:] == [30, ['first second']], 'held again while the last words are made: that hold is kept, but for the piece that may begin before it', str(h))
    eq((g.get('letAgain') or [])[2:], [False, 1, 0, 0, ['first']], 'let go again before the words came: dropped')
    eq((g.get('reply'), g.get('during')), ([True, 'live', False, 'running', 'playback', 'speaking', False], [True, True, 0]), 'F161c3: a reply: the stream rests, its track off, its context running; no sound is taken')
    eq(g.get('afterReply'), [True, True, True, 0, 'play-and-record'], 'and the same one is live after it, with none of its sound')
    eq((g.get('cutOff'), g.get('cutOn')), ([True, True, False, 'play-and-record'], [1, 'listening', True]), 'F161c3: a press that cuts a reply off wakes the stream in the press, with no new ask')
    eq(g.get('cutClip'), [1, ['hello run'], 1, 0], 'and its words go out')
    check(0.8 <= (g.get('cutSecs') or 0) <= 1.1, 'with only the second since the press in the clip', str(g.get('cutSecs')))
    eq((g.get('hides'), g.get('backOn')), (['ended', None, 'playback', False], True), 'hidden: released at once; shown: open again')
    for n in ('left', 'thread', 'test', 'typing'):
        eq((g.get('rel_' + n), g.get('back_' + n)), (None, True), f'{n}: released, then open again')
    eq((g.get('hidOpening'), g.get('joins')), ([None, 'ended'], [1, 'listening', True]), 'hidden while it opens: closed; a press joins the opening')
    eq((g.get('failed'), g.get('failedPress')), ([1, 0, ''], [2, 0, True]), 'it cannot open: quiet, once, and the press tries itself')
    eq(g.get('taken'), [2, True, True, False, 0, ''], 'B804c: the mic taken away between listens: open again, and nothing listens')
    eq((g.get('taken3'), g.get('takenOut')), ([4, True], [4, None, True]), '3 times, then no more')
    eq((g.get('takenBack'), g.get('takenPress')), ([5, True], [8, None, 10, True]), 'again once Talk shows anew, or after a press that listened')
    eq((g.get('takenPrompt'), g.get('takenBusy')), ([1, None], [2, None, 0]), 'not where a new stream could ask; one that cannot open is not tried again')
    eq(g.get('takenListen'), [1, None, ['hello run']], 'taken away in a listen: its words go out, and the next press opens it')
    eq(g.get('takenReply'), [True, None, 1, None], 'while a reply is read: not opened again')
    eq((g.get('rests'), g.get('wakes')), ([True, False, 'running', 0, 'playback', 1], [True, True, 'running', 1, 'play-and-record']), 'where a new stream could ask: it rests while a reply plays, and wakes')
    eq(g.get('onlyBefore'), [0, 0], 'sound from before a press is not sent alone')
    eq(g.get('gone', 1), None, 'the engine gone: released')
    eq(g.get('wayBrowser'), [0, None], "the browser's recognition: no open mic")
    none, empty = g.get('none') or '', g.get('empty') or ''
    check('mic not open: none yet; permission last seen: not asked; context: none' in none, 'B804a: none yet', none)
    check('permission: prompt' in none and 'mic opened: getUserMedia 900 ms, context start 0 ms' in none, 'its opening, with the ms', none)
    check('no words after' in empty and 'an empty answer' in empty and 'words came' not in empty, 'an empty answer is no words', empty)
    check('getUserMedia 450 ms' in (g.get('letGo') or ''), 'a press let go meanwhile has the ms too', str(g.get('letGo')))
    for k, says in (('whyReply', 'resting; permission last seen: granted; context: running'), ('whyRest', 'resting; permission last seen: prompt; context: running'),
                    ('whyEnded', 'track ended by the browser; permission last seen: granted; context: none'),
                    ('whyDead', 'track ended by the browser; permission last seen: granted; context: running'), ('whyHidden', 'page hidden; permission last seen: granted; context: none'),
                    ('whyCtx', 'its context is interrupted; permission last seen: granted; context: interrupted'), ('whyFailed', 'none yet; permission last seen: not asked; context: none')):
        eq((g.get(k) or [''])[0], 'mic not open: ' + says, k)
    check(any(x.startswith('mic woken: context running after ') for x in g.get('whyRest') or []), 'a resting mic: its wake', str(g.get('whyRest')))
    o = g.get('whyOpening') or ''
    check('mic not open: opening under way, begun by the page; before it: ' in o and 'mic opened: opening begun 300 ms before: getUserMedia 400 ms' in o, "the page's own opening, joined", o)
    o = g.get('lost2') or ''
    check('mic not opened by the page: opening begun 300 ms before: getUserMedia 400 ms, NotReadableError' in o and 'mic not opened: getUserMedia 0 ms' in o, "the page's own opening failed, and the press's", o)
    check(any(x.startswith('mic not opened: getUserMedia 0 ms, NotReadableError') for x in g.get('whyFailed') or []), 'a refused opening', str(g.get('whyFailed')))

    early = 'The mic was still starting. Allow it if the browser asks, hold until this line says Listening…, then speak.'
    eq(g.get('holdOpening'), 'Starting the mic…', 'B804b: while it opens the line says so')
    b = g.get('holdBefore') or ['', 1, '']
    check(b[0].startswith(early) and b[1:] == [0, ''], 'let go before it opened', str(b))
    eq((g.get('noSoundYet'), g.get('holdOn')), ('Starting the mic…', 'Listening…'), 'Listening once sound comes')
    b = g.get('holdAfter') or ['', 0, 1]
    check(b[0].startswith(early) and b[1:] == [1, 0], 'let go just after it opened, with no words', str(b))
    eq(g.get('holdWords'), ['hello run'], 'its words, where there are some, are sent')
    for k in ('holdLong', 'holdShort'):
        check((g.get(k) or '').startswith('Heard nothing'), f'{k}: the mic was on long enough, or open at the press', str(g.get(k)))
    eq((g.get('holdOpen'), g.get('afresh')), ('Listening…', ['Listening…', 'Starting the mic…', 'Starting the mic…', 'Listening…']), 'a stream opened afresh in the hold')
    check((g.get('afreshNote') or '').startswith(early), 'let go just after that', str(g.get('afreshNote')))

    eq(g.get('tpIn'), [1, 1, 'play-and-record'], "F161c1: the press that opens Talk asks and starts the context inside it, where the permission is prompt")
    eq(g.get('tpOpen'), [True, '', None, 0, 0], 'open, and nothing listens or is sent')
    eq((g.get('tpMic'), g.get('tpSent')), ([True, 1, 1], [['hello run'], 1]), 'the first mic press listens in the press: no getUserMedia, no context')
    eq((g.get('tpLeft'), g.get('tpBack'), g.get('tpHides', 1)), ([None, 'ended'], [2, True], None), 'left: released, the next Talk press opens it again; hidden: released')
    eq(g.get('tpCannotSay'), [1, True], 'a browser that cannot say: the same')
    eq((g.get('tpLate'), g.get('tpNever'), g.get('tpHidden', 1)), ([True, True, 1], [True, None], None), 'Talk drawn after the press keeps it; never drawn or hidden: released')
    eq(g.get('tpJoin'), [1, True], 'a mic press during the ask joins it')
    eq(g.get('tpRefused'), [1, 0, '', 1], 'refused: quiet, and not asked again, nor by the next Talk press')
    eq((g.get('tpRefusedMic'), g.get('tpRefusedOver')), ([2, True], [3, True]), 'the mic press asks, and once it listened the Talk press opens it again')
    eq(g.get('tpAllowed'), [2, True, False, 3, True], 'allowed in the browser meanwhile: the refusal is over')
    eq(g.get('tpElse', 1), None, 'another place pressed before Talk is drawn: released at the next look')
    eq(g.get('tpRefusedJoin'), [1, 1, True], 'refused with a mic press waiting: not asked a second time, the browser hears')
    eq([g.get(k) for k in ('tpShown', 'tpReads', 'tpDict', 'tpBrowser')], [0, 0, 0, 0], "Talk shown already, a reply read, dictation or the browser's way: nothing opens")
    eq((g.get('tpMay'), g.get('tpPrompt')), ('granted', 'prompt'), 'the permission from before the ask is kept, for the mic report')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_recorded_f161b)]))
