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
let node = null, tracks = [];
class AudioWorkletNode { constructor() { node = this; this.port = {postMessage() {}, onmessage: null} } connect() {} }
window.AudioContext = AudioContext;
const getUserMedia = async () => { asks++; if (hold) await hold; if (deny) throw Object.assign(new Error('no'), {name: deny}); const t = new Track(); tracks.push(t); return {getTracks: () => [t], getAudioTracks: () => [t]} };
class Audio {""", 1)
              .replace("navigator = {language: 'en-US', userAgent: 'iPhone',", "navigator = {mediaDevices: {getUserMedia}, language: 'en-US', userAgent: 'iPhone Version/27.0 Mobile Safari/604.1',", 1)
              .replace("+ page.slice(page.indexOf(\"document.addEventListener('visibility", "+ page.slice(page.indexOf('/* --- F161b: Recorded'), page.indexOf('/* B162b1: the Mic test')) + page.slice(page.indexOf(\"document.addEventListener('visibility", 1)
              .replace("talkSet = (k, v) => { TS = {...TS, [k]: v} }", "talkSet = (k, v) => { TS = {...TS, [k]: v}; if (k === 'way') recPick() }", 1)
              .replace('const micWhy = () => \'\'', "const micWhy = () => micProblem(window.isSecureContext !== false, true)", 1) + r"""
// s seconds of sound, in the worklet's pieces; loud: somebody speaks
const sound = (s, loud = true) => { for (let i = 0; i < s * 48000 / 2048; i++) if (REC.now) node.port.onmessage({data: new Float32Array(2048).fill(loud ? 0.2 : 0.0005)}) };
const tail = async () => { await tick(200); await tick(20); await settle() };
const down = () => fire('pointerdown', press('[data-mic]')), up = () => fire('pointerup', press('[data-mic]'));
const fresh = () => { if (TK.rec && TK.rec.recorded) TK.rec.abort(); recFree(); hush(); TK.ear = TK.rec = TK.wait = null; MIC.rec = MIC.next = null; TK.state = TK.note = ''; TK.hold = false; sent.length = notes.length = posts.length = recs.length = types.length = 0; asks = 0; deny = ''; hold = null; answer = 'hello run'; REC.no = ''; REC.engine = engine; TS.mic = 'tap'; TS.way = 'recorded'; TS.auto = false; TS.read = true; S.view = 'talk'; AU.got = null; timers = [] };
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
  console.log(JSON.stringify(out, (k, v) => v === undefined ? null : v));
})();`);
""")


def test_recorded_f161b(tmp: Path) -> None:
    """F161b: with a stubbed mic and route, a recording's words are sent by Tap, Hold and auto listen; what cannot record falls back."""
    page = W.page_html().decode()
    check('${recRow()}' in page.split('  talk(){', 1)[1].split('\n  },', 1)[0], 'Talk settings has the setting')
    check('recFree()' in page.split('function dictate(', 1)[1].split('\n}\n', 1)[0], 'dictation releases the mic first')
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
    eq(g.get('tap'), [['what is running'], 'thinking', 0, None, 'playback'], 'Tap: its words are sent, and the session is for playing again')
    eq(g.get('rest'), [False, 'suspended', 1], 'between listens the stream is kept and takes no sound')
    check('running' not in (g.get('report') or 'running') and 'clip, ' in g['report'], 'the mic report has no words', str(g.get('report')))
    eq((g.get('again'), g.get('two')), ([True, 1], [2, 1]), 'one ask for two listens')
    eq(g.get('stray'), 2, 'sound outside a listen goes nowhere')
    eq((g.get('notYet'), g.get('pause')), (False, ['hello run']), 'a pause of 2 s ends a Tap')
    eq(g.get('silent'), [0, 0, True, ''], 'nobody speaks: no clip leaves the page')
    eq(g.get('noWords'), [0, True, ''], 'no words: the line says so')
    eq(g.get('early'), [0, '', True, None, False], 'stopped before it was on: nothing, and the mic takes no sound')
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


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_recorded_f161b)]))
