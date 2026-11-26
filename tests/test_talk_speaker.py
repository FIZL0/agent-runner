"""Talk: the speaker button and the browser's own voice (B166a).

    python3 tests/test_talk_speaker.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from _check import check, eq, report
from agent_runner import web as W  # noqa: E402
from _web import in_tmp  # noqa: E402
from test_web_talk import READ_DRIVER  # noqa: E402

# speechSynthesis stubbed: each call is in order as 'voice'; an utterance starts only when the test says so
SPEAKER_DRIVER = READ_DRIVER.split('(async () => {')[0] + r"""
const blank = [];
{ const f = ss.speak; ss.speak = u => { order.push('voice'); if (!u.text) blank.push(u); f(u) } }
const fresh = () => { over(); TK.unlocked = false; blank.length = 0; AU.got = null; TS.read = true; TS.mic = 'tap'; S.feeds.c5 = {entries: []} };
(async () => {
  const out = {}; await settle();
  // the unlock counts only once its utterance started
  fresh(); unlockSpeech(); out.noStart = [TK.unlocked, blank.length]; blank[0].onstart(); out.started = TK.unlocked;
  // a voice send: the press starts the mic before any speechSynthesis call (B132), the send itself unlocks nothing
  fresh(); click('[data-mic]'); out.first = order.slice(); mic().say('what runs'); mic().end(); await settle(); out.voice = [TK.unlocked, order.filter(x => x === 'voice').length];
  // the second tap of Tap is a real tap: it may unlock, after the stop
  fresh(); click('[data-mic]'); mic().say('go'); order.length = 0; click('[data-mic]'); out.second = [mic().stopped, order.slice()]; mic().end(); await settle();
  // the speaker off, then on with a reply there: the last reply is read in that tap
  fresh(); S.feeds.c5 = {entries: [{kind: 'you', text: 'x'}, {kind: 'say', text: 'Old reply.'}]}; TS.read = false; us.length = 0;
  click('[data-spk]'); out.on = [TS.read, us.map(u => u.text), TK.state, shows()[3]];
  hush(); click('[data-spk]'); out.off = [TS.read, shows()[3]];
  // no reply there: on reads nothing
  fresh(); TS.read = false; us.length = 0; click('[data-spk]'); out.onEmpty = [TS.read, us.length, TK.state];
  // speech that never starts: the talk line says so and what to do
  fresh(); lands('One here.'); await look(6); out.never = [TK.state, TK.note, shows()[4]];
  // speech that starts: no such words
  fresh(); lands('One here.'); us[us.length - 1].onstart(); ss.speaking = true; await look(2); ss.speaking = false; us[us.length - 1].onend({type: 'end'}); await settle(); out.spoke = [TK.state, TK.note];
  console.log(JSON.stringify(out));
})();`);
"""


def test_speaker_b166a(tmp: Path) -> None:
    """B166a: the speaker is a toggle that speaks when turned on; the browser's voice is unlocked only in taps and once it started."""
    if not shutil.which('node'):
        print('  (no node here: the speaker script test is skipped)')
        return
    (tmp / 'driver.js').write_text(SPEAKER_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs the speaker', r.stderr[-900:])
    got = json.loads(r.stdout or '{}')
    eq(got.get('noStart'), [False, 1], 'an unlock with no start is not counted')
    eq(got.get('started'), True, 'it counts once its utterance started')
    eq((got.get('first') or [''])[0], 'start', 'the mic press starts the recognizer before any speech call')
    check('voice' not in (got.get('first') or []), 'and makes no speech call at all', str(got.get('first')))
    eq(got.get('voice'), [False, 0], 'a recognizer that ends by itself unlocks nothing')
    page = W.PAGE.read_text(encoding='utf-8') if hasattr(W.PAGE, 'read_text') else ''
    check('talkSend(t.words,true)' in page and 'if(!voice)unlockSpeech()' in page, 'a voice send does not unlock the voice')
    eq(got.get('second'), [True, ['voice']], 'the second tap stops the mic, then unlocks the voice')
    eq(got.get('on'), [True, ['Old reply.'], 'speaking', 'Stop speaking'], 'the speaker turned on reads the last reply in that tap')
    eq(got.get('off'), [False, 'Read replies aloud: off'], 'and its next tap turns read aloud off')
    eq(got.get('onEmpty'), [True, 0, ''], 'with no reply there it is only turned on')
    never = got.get('never') or ['', '', '']
    eq(never[0], '', 'speech that never starts ends')
    check('silent switch' in never[1] and 'play' in never[1] and never[2] == never[1], 'and the talk line says what to do', str(never))
    eq(got.get('spoke'), ['', ''], 'speech that started says nothing of the kind')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_speaker_b166a)]))
