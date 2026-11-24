"""The run page, chats area: a tap on the slim message box during a momentum scroll ends the scroll and opens the box (B218b1).

    python3 tests/test_web_chats_fling.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from _check import check, eq, report
from _web import in_tmp

from agent_runner import web as W  # noqa: E402

DRIVER = r"""
const els = {}, El = () => ({on: {}, addEventListener(t, f) { (this.on[t] = this.on[t] || []).push(f) }, getBoundingClientRect: () => ({left: 0, top: 0}),
  fire(t, e) { for (const f of this.on[t] || []) f(e) }});
const $ = id => els[id] = els[id] || El();
let frames = new Map(), ids = 0, clock = 0, now = 1000;
const requestAnimationFrame = f => { frames.set(++ids, f); return ids }, cancelAnimationFrame = id => frames.delete(id);
const performance = {now: () => clock}, matchMedia = () => ({matches: false});
Date.now = () => now;
const setTimeout = () => 0, clearTimeout = () => {};
let SW = null, steps = 0, FEED_LINES = 1, opened = 0;
const feedScreen = () => ({cell: 17}), feedScroll = px => { steps++; return px }, feedSteps = () => [1, 0], feedWheel = () => {}, feedClick = () => {}, feedText = () => {}, feedTake = () => {};
BLOCK
const layer = $('feedtouch'), slim = $('slimbox');
const run = n => { for (let i = 0; i < n; i++) { clock += 16; const f = [...frames.values()]; frames.clear(); for (const g of f) g(clock) } };
const Button = () => { const b = Object.assign(El(), {closest: s => s === '[data-slimbox]' ? b : null, click() { opened++; slim.fire('click', {target: b}) }}); b.addEventListener = (t, f) => { b.on[t] = [f] }; return b };
let button = Button(), here = button;
const other = Object.assign(El(), {closest: () => null});
slim.querySelector = () => here;
const ev = (target, x, y, t) => ({target, touches: [{clientX: x, clientY: y}], changedTouches: [{clientX: x, clientY: y}], timeStamp: t, cancelable: true, prevented: 0, preventDefault() { this.prevented++ }});
function fling() {
  layer.fire('touchstart', ev(other, 100, 100, 0));
  for (let i = 1; i <= 6; i++) layer.fire('touchmove', ev(other, 100, 100 + i * 30, i * 16));
  const end = ev(other, 100, 280, 100); end.touches = []; layer.fire('touchend', end);
  run(3); steps = 0; opened = 0;
}
const going = () => { steps = 0; run(5); return steps > 0 };
function press(target, o = {}) {
  slim.fire('touchstart', ev(target, 50, 700, 0)); const on = going();
  now += o.hold || 60;
  const e = ev(target, 50, 700 + (o.move || 0), 60); e.type = o.cancel ? 'touchcancel' : 'touchend'; target.fire(e.type, e);
  return [on, opened, e.prevented, going()];
}
const out = {};
fling(); out.glides = going();
fling(); out.tap = press(button);
fling(); out.other = press(other);
fling(); out.held = press(button, {hold: 600});
fling(); out.moved = press(button, {move: 20});
fling(); here = Button(); out.redrawn = press(button); here = button;
fling(); out.cancel = press(button, {cancel: true});
fling(); slim.fire('click', {target: button}); out.click = going();
opened = 0; out.rest = press(button);
fling(); out.again = going();
console.log(JSON.stringify(out));
"""


def test_tap_in_a_fling_b218b1(tmp: Path) -> None:
    """B218b1: the press on the slim message box ends the glide at the touch; the tap's end makes the click (the browser
    gives none after a fling), once. A press elsewhere in the row, a long press and a swipe open nothing."""
    page = W.PAGE.read_text(encoding='utf-8')
    if not shutil.which('node'):
        print('  (no node here: the fling test is skipped)')
        return
    block = page[page.index('{let G=null, glide=0;'):]
    block = block[:block.index('/* --- F170')]
    f = tmp / 'fling.js'
    f.write_text(DRIVER.replace('BLOCK', block), encoding='utf-8')
    r = subprocess.run(['node', str(f)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs the touch layer', r.stderr[-800:])
    o = json.loads(r.stdout or '{}')
    # each: [glides while pressed, clicks, the browser's own click prevented, glides after]
    eq(o.get('glides'), True, 'a fling glides on')
    eq(o.get('tap'), [False, 1, 1, False], 'a tap on the slim message box: the scroll ends at the touch, one click')
    eq(o.get('other'), [True, 0, 0, True], 'a press on another control of the row is left alone')
    eq(o.get('held'), [False, 0, 0, False], 'a long press ends the scroll and clicks nothing')
    eq(o.get('moved'), [False, 0, 0, False], 'a swipe too')
    eq(o.get('redrawn'), [False, 1, 1, False], 'the row drawn again under the finger: the tap still opens the box')
    eq(o.get('cancel'), [False, 0, 0, False], 'a touch the system took too')
    eq(o.get('click'), False, 'a click alone (a mouse, Enter) ends the scroll')
    eq(o.get('rest'), [False, 1, 1, False], 'from rest: one click')
    eq(o.get('again'), True, 'a new touch scroll glides again')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_tap_in_a_fling_b218b1)]))
