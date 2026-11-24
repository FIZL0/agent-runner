"""F158: run speech: the voices this machine has, the worker that makes clips, the run's /speech route, and the page
that plays them in one audio element (a tap on the speaker unlocks it; the browser's own voice is the fallback)."""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from _check import FAILED, check, eq

HOME = Path(tempfile.mkdtemp(prefix='agent-runner-speech-'))
os.environ['AGENT_RUNNER_SPEECH'] = str(HOME)  # never the person's own

from agent_runner import speech as Sp, web as W  # noqa: E402

# --- what is installed -------------------------------------------------------------------------------------------
eq(Sp.voices(), {'ok': True, 'voices': [], 'default': ''}, 'nothing installed: no voices')
try:
    Sp.Speaker().make('hello')
    check(False, 'no engine: no clip')
except Sp.SpeechError as e:
    check('no voice is installed' in str(e), 'no engine: no clip, and why', str(e))


def put(f: Path, data: bytes = b'x') -> None:
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(data)


put(Sp.venv_python())
for name, _, _ in Sp.ENGINES['piper'][1]:
    put(HOME / 'piper' / name)
eq(Sp.voices()['default'], '', 'files without the mark an install leaves last: not installed')
put(HOME / 'piper' / 'installed')
eq(Sp.voices()['default'], Sp.LIGHT, 'Piper alone: its voice is the default')
b = io.BytesIO()
with zipfile.ZipFile(b, 'w') as z:
    for n in ('bf_emma', 'af_heart', 'af_bella'):
        z.writestr(n + '.npy', b'')
put(HOME / 'kokoro' / 'voices-v1.0.bin', b.getvalue())
put(HOME / 'kokoro' / 'kokoro-v1.0.onnx')
put(HOME / 'kokoro' / 'installed')
got = Sp.voices()
eq([v['id'] for v in got['voices']], ['kokoro:af_bella', 'kokoro:af_heart', 'kokoro:bf_emma', 'piper:en_US-lessac-medium'],
   'every voice in the Kokoro file, and Piper')
eq(got['default'], 'kokoro:af_heart', 'the default')
eq(got['voices'][2]['lang'], 'British English', 'with its language')

# --- the worker --------------------------------------------------------------------------------------------------
FAKE = HOME / 'fake.py'
FAKE.write_text('''import json, os, sys, time
out = sys.stdout.buffer
for line in sys.stdin:
    r = json.loads(line)
    if r['text'] == 'hang': time.sleep(60)
    if r['text'] == 'die': sys.exit(1)
    if r['text'] == 'bad': out.write(b'{"ok": false, "out": "no such word"}\\n')
    else:
        data = json.dumps([os.getpid(), r['voice'], r['text']]).encode()
        out.write(json.dumps({'ok': True, 'bytes': len(data)}).encode() + b'\\n' + data)
    out.flush()
''', encoding='utf-8')


def fake(**kw) -> Sp.Speaker:
    return Sp.Speaker(argv=lambda: [sys.executable, str(FAKE)], **kw)


def why(sp: Sp.Speaker, text: str) -> str:
    try:
        sp.make(text)
        return ''
    except Sp.SpeechError as e:
        return str(e)


sp = fake()
one, two = json.loads(sp.make(' Hi\nthere. ')), json.loads(sp.make('x', 'kokoro:bf_emma'))
eq(one[1:], ['kokoro:af_heart', 'Hi there.'], "no voice named: the default; the text on one line")
eq(two[:2], [one[0], 'kokoro:bf_emma'], 'the same worker makes the next one, in the voice asked for')
eq(json.loads(sp.make('x', 'kokoro:../../etc'))[1], 'kokoro:af_heart', 'a voice that is not listed: the default')
eq(why(sp, 'bad'), 'no such word', "the engine's reason")
check('did not answer' in why(sp, 'die') or 'ended' in why(sp, 'die'), 'a worker that died')
check(json.loads(sp.make('x'))[0] != one[0], 'and the next clip starts another')
check('1 to' in why(sp, 'x' * (Sp.TEXT_MAX + 1)) and '1 to' in why(sp, ' '), 'too long or empty')
proc = sp.proc
sp.rest()
check(proc.poll() is not None and sp.proc is None, 'idle: the worker goes')
check(sp.make('x'), 'and comes back')
proc = sp.proc
sp.close()
check(proc.poll() is not None and why(sp, 'x') == 'the run is stopping', 'the run stops: so does it, for good')
slow = fake(timeout=1.0)
check(why(slow, 'hang'), 'a stuck engine is ended')
check(json.loads(slow.make('x')), 'and the next clip is made')
slow.close()

# --- the route ---------------------------------------------------------------------------------------------------
srv = W.serve('tok', 0, '127.0.0.1', snap=lambda: {})
srv.speaker = fake()
base = f'http://127.0.0.1:{srv.server_address[1]}/speech'


def call(query: str = '?t=tok', body=None):
    data = None if body is None else body if isinstance(body, bytes) else json.dumps(body).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(base + query, data=data), timeout=20) as r:
            return r.status, r.headers['Content-Type'], r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers['Content-Type'], e.read()


try:
    eq((call('')[0], call('', {'text': 'x'})[0]), (403, 403), 'both want the token')
    eq(json.loads(call()[2])['default'], 'kokoro:af_heart', 'GET: the voices')
    code, kind, data = call(body={'text': 'Hello.', 'voice': 'piper:en_US-lessac-medium'})
    eq((code, kind, json.loads(data)[1:]), (200, 'audio/wav', ['piper:en_US-lessac-medium', 'Hello.']), 'POST: the clip')
    code, _, data = call(body={'text': 'bad'})
    eq((code, json.loads(data)['out']), (503, 'no such word'), 'no clip: why')
    eq([call(body=x)[0] for x in (b'nope', b'[]', {}, b'x' * (Sp.TEXT_MAX * 9))], [400] * 4, 'a bad request')
finally:
    srv.stop()

# --- the page ----------------------------------------------------------------------------------------------------
DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const grab = s => { const i = page.indexOf(s); if (i < 0) throw new Error(s); return page.slice(i, page.indexOf('\n}\n', i) + 2) + '\n' };
const line = s => { const i = page.indexOf(s); if (i < 0) throw new Error(s); return page.slice(i, page.indexOf('\n', i)) + '\n' };
const logic = page.split('<script id="logic">')[1].split('</script>')[0];
const said = [], notes = [], asked = [], plays = [], esc = String, tq = p => p, HOME_PAGE = false;
let allow = false, status = 200, els = 0, listens = 0, tells = null;
const window = {speechSynthesis: {cancel() {}, speak(u) { if (u.text) said.push(u.text) }}}, speechSynthesis = window.speechSynthesis;
class SpeechSynthesisUtterance { constructor(t) { this.text = t } }
class Audio { constructor(src) { if (src) this.src = src; else els++; this.paused = true; this.ended = false }  // one with a source: the silence (B178)
  play() { if (this.loop) { this.paused = false; return Promise.resolve() } plays.push(this.src); if (!allow) return Promise.reject(Object.assign(new Error('no'), {name: 'NotAllowedError'}));
    this.paused = false; this.ended = false; return Promise.resolve() }
  pause() { this.paused = true; const f = this.onpause; if (f) f() }
  finish() { this.paused = true; this.ended = true; if (this.onpause) this.onpause(); if (this.onended) this.onended() } }
let urls = 0; URL.createObjectURL = b => b.size === 844 ? 'silence' : b.size === 40044 ? 'hold' : 'clip' + (++urls); URL.revokeObjectURL = () => {};
const VOICES = {voices: [{id: 'kokoro:af_heart', name: 'af_heart', lang: 'American English', engine: 'Kokoro'}, {id: 'piper:p', name: 'p', lang: '', engine: 'Piper'}], default: 'kokoro:af_heart'};
const fetch = async (p, o) => { if (!o) return {ok: true, json: async () => VOICES};
  asked.push(JSON.parse(o.body)); return {ok: status === 200, status, blob: async () => new Blob(['x']), json: async () => ({out: 'it broke'})} };
const navigator = {language: 'en-US'}, toast = t => notes.push(t), render = () => {}, voices = () => [];
const MIC = {rec: null, next: null}, S = {view: 'talk', thread: null, sheet: ''}, TK = {state: '', playing: '', note: '', held: '', later: [], ear: null, unlocked: true};
let TS;
const listen = () => { listens++ }, talkSet = (k, v) => { TS[k] = v }, micWhy = () => '', store = {get: () => ''}, TM_KEY = 'tm';
const tick = () => new Promise(r => setTimeout(r, 5));
eval(logic + `TS = talkSetParse('');` + page.slice(page.indexOf('/* F158: run speech:'), page.indexOf('const talkTyping='))
 + line('const talkTyping=') + grab('function unlockSpeech(') + grab('function speak(') + line('function hush(')
 + 'const spk=()=>{const q=s=>s==="[data-spk]";' + line("  if(q('[data-spk]'))") + '};' + `
(async () => {
  const out = {};
  await tick();
  out.opts = voiceOpts();
  // a reply before any tap: the browser refuses, and the talk line says to tap
  speak('First one is here. Second.'); out.begin = TK.state; await tick();
  out.blocked = [TK.state, TK.held, TK.note.includes('Tap the speaker'), said.length];
  allow = true; plays.length = 0; spk(); out.tapNow = plays.slice(); await tick();
  out.tapped = [TK.state, TK.held + TK.note, TS.read, AU.ok, plays.length];
  out.asked = asked.slice(-2);
  AU.el.finish(); await tick(); out.second = [TK.state, plays.length];
  AU.el.finish(); await tick(); out.done = [TK.state, els, said.length];
  // a later reply plays by itself; auto listen after it
  TS.auto = true; speak('Later.'); await tick(); AU.el.finish(); await tick(); out.auto = [TK.state, listens]; TS.auto = false;
  // refused after it had played: the speaker's tap unlocks again
  allow = false; speak('Again.'); await tick(); allow = true; plays.length = 0; spk(); out.again = plays.slice(); await tick(); AU.el.finish(); await tick();
  // stopped by hand, and by the phone
  speak('Stop me.'); await tick(); hush(); out.hush = [TK.state, AU.el.paused];
  speak('A call.'); await tick(); AU.el.pause(); out.call = [TK.state]; await new Promise(r => setTimeout(r, 700)); AU.el.pause(); out.call.push(TK.state);
  speak('Old one.'); speak('New one.'); await tick(); out.newer = [TK.state, plays.length]; AU.el.finish(); await tick(); out.newerDone = TK.state;
  // a play button
  speak('Button.', 'k1'); await tick(); out.key = [TK.playing, TK.state]; AU.el.finish(); await tick(); out.keyDone = TK.playing;
  // the speaker toggles, and unlocks in that tap only when it must
  plays.length = 0; spk(); out.off = [TS.read, plays.length]; AU.ok = false; spk(); await tick(); out.on = [TS.read, plays.slice(), AU.ok];
  AU.ok = false; TK.ear = {}; plays.length = 0; unlockAudio(); out.mic = plays.length; TK.ear = null;
  // the run fails: the browser's own voice
  status = 503; speak('Fall back.'); await tick(); out.fall = [said.slice(), TK.state, notes[notes.length - 1]]; status = 200; hush();
  said.length = 0; const n = asked.length; TS.voice = 'system'; speak('Own.'); await tick(); out.system = [said.slice(), asked.length - n]; hush();
  said.length = 0; TS.voice = ''; AU.got = {voices: [], default: ''}; speak('None.'); await tick(); out.none = [said.slice(), asked.length - n, voiceOpts()];
  console.log(JSON.stringify(out));
})();`);
"""
if not shutil.which('node'):
    print('  (no node here: the page script test is skipped)')
else:
    (HOME / 'driver.js').write_text(DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(HOME / 'driver.js'), str(W.PAGE)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs run speech', r.stderr[-900:])
    o = json.loads(r.stdout or '{}')
    check('value="" selected>Default (af_heart)' in o['opts'] and 'label="Kokoro"' in o['opts']
          and 'label="Piper, light"' in o['opts'] and 'value="system"' in o['opts'], 'the Voice setting lists them', o['opts'])
    eq(o['begin'], 'speaking', 'speaking at once')
    eq(o['blocked'], ['', 'First one is here. Second.', True, 0], 'refused before a tap: held, and it says what to do')
    eq(o['tapNow'], ['silence'], 'the tap itself plays the silent clip, before anything is awaited')
    eq(o['tapped'], ['speaking', '', True, True, 2], 'and reads the held reply, read aloud staying on')
    eq(o['asked'], [{'text': t, 'voice': 'kokoro:af_heart'} for t in ('First one is here.', 'Second.')], 'clip by clip')
    eq((o['second'], o['done']), (['speaking', 3], ['', 1, 0]), 'one audio element plays them all')
    eq(o['auto'], ['', 1], 'a later reply plays by itself, then auto listen')
    eq(o['again'], ['silence'], 'refused later: the tap unlocks again')
    eq((o['hush'], o['call']), (['', True], ['speaking', '']), 'stopped by a tap, or by a second pause of the phone')
    eq((o['newer'][0], o['newerDone']), ('speaking', ''), 'a newer reply takes the place of one')
    eq((o['key'], o['keyDone']), (['k1', ''], ''), 'a play button')
    eq((o['off'], o['on']), ([False, 0], [True, ['silence'], True]), 'the speaker toggles, and its tap unlocks')
    eq(o['mic'], 0, 'nothing plays while the mic listens')
    check(o['fall'][0] == ['Fall back.'] and o['fall'][1] == 'speaking' and 'it broke' in o['fall'][2], 'the run fails', o['fall'])
    eq(o['system'], [['Own.'], 0], "System voice: the browser's own")
    eq(o['none'], [['None.'], 0, '<option value="">System voice</option>'], 'no engine: as before')
    clips = subprocess.run(['node', '-e', (W.PAGE.read_text(encoding='utf-8').split('<script id="logic">', 1)[1]
                            .split('</script>', 1)[0] + ';console.log(JSON.stringify([speechClips("Hi. Version 0.13 is out. " + "Word. ".repeat(60)),'
                            'runVoice({voices:[{id:"kokoro:a"}],default:"kokoro:a"},"kokoro:gone"),'
                            'runVoice({voices:[{id:"kokoro:a"}],default:"kokoro:a"},"Ava")]))')],
                           capture_output=True, text=True, timeout=60)
    c, gone, device = json.loads(clips.stdout or '[[], "", ""]')
    check(c and c[0].startswith('Hi. Version 0.13 is out.') and all(len(x) < 201 for x in c), 'sentences are kept whole', c)
    eq((gone, device), ('kokoro:a', ''), 'a voice that is gone: the default; a device voice: the browser')

shutil.rmtree(HOME, ignore_errors=True)
raise SystemExit(1 if FAILED else print('\nall checks passed'))
