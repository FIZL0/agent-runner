"""B828: a tall question card over a whole session leaves its frame room for Claude Code's prompt, so it is found again.

    python3 tests/test_web_question_low.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from _check import check, eq, report
from _web import in_tmp, logic_js

import test_web_live as L
from agent_runner import web as W  # noqa: E402

# Claude Code 2.1.332 in tmux, 50 columns: what it drew with this many rows (it cuts its lines off at the bottom)
HEAD = [' ▝▝   ▝▝   ~/repos/x', '']
PROMPT = ['  You have used 91% of your weekly limit', '─' * 50, '❯ ', '─' * 50]
FOOT = ['  [PONYTAIL]', '  ⏵⏵ auto mode on (shift+tab to cycle)']
ROWS12 = ['', '  Claude Code v2.1.332', '  Opus 5.5', *HEAD, '', *PROMPT, *FOOT]
ROWS8 = ['  Claude Code v2.1.332', '  Opus 5.5', *HEAD, *PROMPT]
ROWS7 = ROWS8[:-1]


def test_screens(tmp: Path) -> None:
    if not shutil.which('node'):
        print('  (no node here: skipped)')
        return
    twelve, eight, seven = logic_js([['feedFoot', x, None] for x in (ROWS12, ROWS8, ROWS7)])
    eq(len(ROWS12), 12, 'a screen of 12 rows')
    eq([bool(twelve), twelve and twelve['mode'], twelve and twelve['text'], bool(eight)], [True, 'auto', '', True], 'the prompt is found on 12 rows, with its mode, and on 8')
    eq(seven, None, 'under 8 rows its lower rule is cut off: not found')


def test_room(tmp: Path) -> None:
    if not shutil.which('node'):
        print('  (no node here: skipped)')
        return
    head = L.KB_FEED_DRIVER.split('const out = {};')[0]
    (tmp / 'driver.js').write_text(head + """
const out = [], stay = false;
FD.whole = true;
for (const [more, last] of [[0, 31], [300, 12], [400, 12], [560, 12]]) { extra = more; FD.last = last; out.push(at()) }
// the keyboard over it: the same size, its last line on the box
extra = 400; FD.last = 12; out.push(kb(420)[0], kb(0)[0]);
FD.whole = false; FD.foot = {top: 40}; out.push(at()[0]);
console.log(JSON.stringify(out));`);
""", encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node places the frame', r.stderr[-900:])
    got = json.loads(r.stdout or '[]') or [None] * 7
    low = 2 * 12 + 12 * 17
    eq(got[0], [545, 0], 'with no card it fits its room')
    eq(got[1], [245, 0], 'with a card that leaves over 12 rows too')
    eq(got[2:4], [[low, 0], [low, 0]], 'a tall card: never lower than 12 rows, the last line still on the box')
    eq(got[4:6], [[low, 0], [low, 0]], 'the keyboard never resizes it')
    eq(got[6], 812, 'found again, it is its usual size, whatever the card takes')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(f) for f in (test_screens, test_room)]))
