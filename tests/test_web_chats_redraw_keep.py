"""B884: after a harness redraw that clears the scrollback, a chat view scrolled up a few lines keeps its distance from
the end (the same lines), and a view at its end stays at its end; neither lands at the top."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from _check import check, eq, report

SRC = (Path(__file__).resolve().parent.parent / 'agent_runner/page/090-chats.js').read_text(encoding='utf-8')

FAKE = r'''
function fake(){
  const h={csi:null,parsed:[],scroll:[]};
  const b={baseY:100,viewportY:100};
  const t={buffer:{active:b},
    parser:{registerCsiHandler:(id,f)=>{h.csi=f}},
    onWriteParsed:f=>h.parsed.push(f),onScroll:f=>h.scroll.push(f),
    scrollToBottom(){b.viewportY=b.baseY;h.scroll.forEach(f=>f())},
    scrollToLine(y){b.viewportY=y;h.scroll.forEach(f=>f())}};
  return {t,b,h};
}
function redraw(s,lines){
  s.h.csi([3]);s.b.baseY=0;s.b.viewportY=0;s.h.scroll.forEach(f=>f());
  for(let i=0;i<lines;i+=10){s.b.baseY+=10;s.h.parsed.forEach(f=>f())}
}
const out={};
let s=fake();feedRedrawPin(s.t);s.b.viewportY=95;redraw(s,80);out.up=[s.b.baseY,s.b.viewportY];
s=fake();feedRedrawPin(s.t);redraw(s,80);out.end=[s.b.baseY,s.b.viewportY];
console.log(JSON.stringify(out));
'''


def test_scrolled_up_view_keeps_offset():
    print('B884: a view scrolled up 5 lines is 5 lines from the end after a scrollback-clearing redraw')
    if not shutil.which('node'):
        print('  (no node: skipped)')
        return
    m = re.search(r'const REDRAW_PIN_MS=.*?\nfunction feedRedrawPin\(t\)\{.*?\n\}\n', SRC, re.S)
    check(bool(m), 'feedRedrawPin is found')
    r = subprocess.run(['node', '-e', m.group(0) + FAKE], capture_output=True, text=True, timeout=60)
    eq(r.returncode, 0, r.stderr)
    out = json.loads(r.stdout)
    eq(out['up'], [80, 75], 'scrolled-up view keeps 5 lines from the end, not the top')
    eq(out['end'], [80, 80], 'a view at its end stays at its end')


if __name__ == '__main__':
    raise SystemExit(report([test_scrolled_up_view_keeps_offset]))
