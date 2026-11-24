"""Talk: the mic button's press lets the browser play a reply (B166).

    python3 tests/test_talk_unlock.py
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

# Safari as read: an element plays only once a tap called its play() or load(); pointerdown of a touch is no tap
UNLOCK_DRIVER = (READ_DRIVER.split('(async () => {')[0] + r"""
let tap = false, deny = '', made = 0;
const inTap = f => { tap = true; try { f() } finally { tap = false } };
Audio.prototype.load = function () { order.push('load'); if (tap && deny !== 'load') this.free = true };
Audio.prototype.play = function () {
  order.push(this.loop ? 'hold' : 'play'); if (tap && deny !== 'play') this.free = true;
  if (!this.free) return Promise.reject(Object.assign(new Error('no'), {name: 'NotAllowedError'}));
  if (!this.loop) plays.push(this.src); this.paused = false; this.ended = false; return Promise.resolve() };
for (const k of ['cancel', 'speak']) { const f = ss[k]; ss[k] = u => { order.push('voice'); f(u) } }
const plain0 = SR.prototype.stop; SR.prototype.stop = function () { order.push('stop'); plain0.call(this) };
const micClick = () => { click('[data-mic]'); fire('click', press('[data-mic]')) };
const up = () => { const e = press('[data-mic]');
  inTap(() => fire('pointerup', e)); inTap(() => fire('touchend', e)); inTap(micClick) };
// after a reload: nothing has played, the run may not have said its voices yet
const reload = got => { over(); AU.el = AU.hold = null; AU.ok = false; AU.got = got; TS.read = true; TS.mic = 'tap'; order.length = 0 };
const reply = async () => { AU.got = run; lands('One here.'); await settle(); await settle(); return [TK.state, TK.held, TK.note.includes('wants a tap'), AU.ok] };
let run;
(async () => {
  const out = {}; await settle(); run = AU.got;
  for (const got of ['known', 'asked']) {
    const o = out[got] = {}, g = got === 'known' ? run : null;
    reload(g); TS.mic = 'hold'; fire('pointerdown', press('[data-mic]')); await settle(); o.holdDown = [order.slice(), AU.ok];
    mic().say('go'); order.length = 0; up(); o.holdUp = order.slice(); mic().end(); await settle(); o.hold = [sent.length, ...await reply()];
    reload(g); inTap(micClick); await settle(); o.tapFirst = [order.slice(), AU.ok];
    mic().say('go'); order.length = 0; inTap(micClick); o.tapSecond = order.slice(); mic().end(); await settle(); o.tap = [sent.length, ...await reply()];
    // Tap, and the recognizer ends by itself: the first press was the tap
    reload(g); inTap(micClick); mic().say('go'); mic().onerror({error: 'network'}); mic().end(); await settle(); o.self = [sent.length, ...await reply()];
  }
  // each event alone, with load() no help: the second tap, and each of the release's events
  deny = 'load'; out.alone = [];
  reload(run); inTap(micClick); mic().say('go'); inTap(micClick); mic().end(); await settle(); out.alone.push(...await reply());
  for (const k of ['pointerup', 'touchend', 'click']) {
    reload(run); TS.mic = 'hold'; const e = press('[data-mic]'), ev = t => t === 'click' ? micClick() : fire(t, e); fire('pointerdown', e); mic().say('go');
    for (const t of ['pointerup', 'touchend', 'click']) { if (t === k) inTap(() => ev(t)); else ev(t); await settle() }
    mic().end(); await settle(); out.alone.push(...await reply());
  }
  deny = '';
  // a listen that waits for the last recognizer's end: the press itself loads
  reload(run); MIC.rec = {stop() {}}; inTap(micClick); out.waits = order.slice(); MIC.rec = MIC.next = null; over(); TK.ear = null; TK.state = '';
  // a press again while the silent clip plays stops it before the mic starts; a restart of a held listen loads nothing
  reload(run); TS.mic = 'hold'; fire('pointerdown', press('[data-mic]')); up(); mic().end(); AU.ok = false; let still = null; const s0 = SR.prototype.start;
  AU.el.paused = AU.hold.paused = false; SR.prototype.start = function () { still = [AU.el.paused, AU.hold.paused]; s0.call(this) }; fire('pointerdown', press('[data-mic]')); SR.prototype.start = s0; out.quick = still;
  order.length = 0; mic().say('a'); mic().end(); await tick(250); out.again = order.slice(); up(); mic().end(); await settle();
  // counted only once it played
  reload(run); deny = 'play'; inTap(micClick); AU.el.free = false; mic().say('go'); inTap(micClick); await settle(); out.denied = AU.ok; mic().end(); await settle();
  deny = ''; const was = await reply(); out.deniedHeld = [was[0], was[1], was[3]];
  // once it has played, a press plays and loads nothing more
  reload(run); AU.ok = true; inTap(micClick); mic().say('go'); inTap(micClick); out.once = order.slice(); mic().end();
  // the device's own voice, or a run with none: no silence
  reload(run); TS.voice = 'system'; inTap(micClick); mic().say('go'); inTap(micClick); out.system = order.slice(); mic().end(); TS.voice = '';
  reload({voices: []}); inTap(micClick); mic().say('go'); inTap(micClick); out.none = order.slice(); mic().end();
  // the page hidden during a hold is no tap; a listen that goes on is not played into
  reload(run); TS.mic = 'hold'; fire('pointerdown', press('[data-mic]')); order.length = 0; document.hidden = true; fire('visibilitychange', {}); document.hidden = false; out.hidden = order.slice(); mic().end();
  reload(run); TK.ear = {}; unlockAudio(); out.on = order.slice(); TK.ear = null;
  console.log(JSON.stringify(out));
})();`);
""")


def test_mic_unlocks_b166(tmp: Path) -> None:
    """B166: with play() allowed only after a tap, the reply to a voice send plays with no speaker tap, by Hold and by Tap."""
    if not shutil.which('node'):
        print('  (no node here: the unlock script test is skipped)')
        return
    (tmp / 'driver.js').write_text(UNLOCK_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs the presses', r.stderr[-900:])
    got = json.loads(r.stdout or '{}')
    for k in ('known', 'asked'):
        o = got.get(k) or {}
        eq(o.get('holdDown'), [['start', 'load', 'load'], False], f'{k}: the press starts the mic first and plays nothing')
        eq((o.get('holdUp') or [])[:3], ['stop', 'hold', 'play'], f'{k}: the release stops the recognizer, then plays silence')
        eq(o.get('hold'), [1, 'speaking', '', False, True], f'{k}: the reply to a Hold plays by itself')
        eq(o.get('tapFirst'), [['start', 'load', 'load'], False], f'{k}: so does a Tap')
        eq((o.get('tapSecond') or [])[:3], ['stop', 'hold', 'play'], f'{k}: its second tap')
        eq(o.get('tap'), [1, 'speaking', '', False, True], f'{k}: the reply to a Tap plays by itself')
        eq(o.get('self'), [1, 'speaking', '', False, True], f'{k}: and to one the recognizer ended')
    eq(got.get('alone'), ['speaking', '', False, True] * 4, 'the second tap, pointerup, touchend or click is enough by itself')
    eq(got.get('waits'), ['load', 'load'], 'a press that must wait loads at once')
    eq((got.get('quick'), got.get('again')), ([True, True], ['start']), 'no silence under a new listen, and no load when a held one starts again')
    eq(got.get('denied'), False, 'counted only once play() resolved')
    eq(got.get('deniedHeld'), ['', 'One here.', False], 'and a refused reply still waits for a tap')
    eq((got.get('once'), got.get('system'), got.get('none')), (['start', 'stop'],) * 3, 'nothing when it has played, or no run voice reads')
    eq((got.get('hidden'), got.get('on')), (['stop'], []), 'nor with the page hidden, nor while the mic listens')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_mic_unlocks_b166)]))
