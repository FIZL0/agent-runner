"""The run page, chats area: one tap on the slim message box opens the full box with the keyboard (B218b).

    python3 tests/test_web_chats_slimtap.py
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
const log = [], dock = {inert: true}, TOUCH = () => true, IOS = process.argv[2] === 'ios';
const ta = {value: 'a draft', style: {}, setSelectionRange() {}, focus(o) { log.push(['focus', dock.inert, o.preventScroll]) }};
const document = {querySelector: () => ta}, requestAnimationFrame = f => f();
const feedSlim = on => { log.push(['slim', on]); dock.inert = on };
const q = s => s === '[data-slimbox]';
async function click(e) { HANDLER
  log.push(['past it']) }
for (const detail of [1, 0]) { click({detail}); log.push(['returned']) }  // a tap, then Enter on the row
console.log(JSON.stringify([log, ta.value, ta.style.opacity || '']));
"""


def test_slim_tap_focuses_b218b(tmp: Path) -> None:
    """B218b: the tap opens the box, then focuses it before the click handler gives way: iOS opens a keyboard for a focus
    in the tap itself only. On touch too; the draft is kept."""
    page = W.PAGE.read_text(encoding='utf-8')
    line = next(x for x in page.splitlines() if "if(q('[data-slimbox]'))" in x)
    check('TOUCH()' not in line, 'a touch is not left out', line)
    if not shutil.which('node'):
        print('  (no node here: the slim box tap test is skipped)')
        return
    kb = page[page.index('function kbFocus('):]
    kb = kb[:kb.index('\n}\n') + 3]
    f = tmp / 'slimtap.js'
    f.write_text(DRIVER.replace('HANDLER', line) + kb, encoding='utf-8')
    for kind in ('ios', 'other'):
        r = subprocess.run(['node', str(f), kind], capture_output=True, text=True, timeout=60)
        check(r.returncode == 0, 'node runs the click handler', r.stderr[-800:])
        log, draft, opacity = json.loads(r.stdout or '[[], "", ""]')
        eq(log, [['slim', False], ['focus', False, True], ['returned']] * 2, f'{kind}: open, then focus, in the tap itself')
        eq((draft, opacity), ('a draft', ''), f'{kind}: the draft stays, the box shows')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_slim_tap_focuses_b218b)]))
