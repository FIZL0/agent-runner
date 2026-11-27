"""F471: the run page shows the agent-runner version under the chats list and in Settings.

    python3 tests/test_runner_version_page.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _check import check, eq, report  # noqa: E402
from agent_runner import web as W  # noqa: E402

DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8');
const line = page.split('\n').find(l => l.startsWith('const runnerVer='));
const esc = t => String(t).replace(/</g, '&lt;');
let S = {snap: {version: '1.2.3'}};
eval(line.replace('const runnerVer', 'var runnerVer'));
const a = runnerVer(), b = runnerVer('setver small');
S = {snap: {}};
console.log(JSON.stringify([a, b, runnerVer()]));
"""


def test_version():
    page = W.PAGE.read_text(encoding='utf-8')
    check('${runnerVer()}' in page, 'the chats list draws the version line')
    check("runnerVer('setver small')" in page, 'Settings draws the version line')
    check('.runver{' in page and '.setver{' in page, 'both lines are styled')
    if not shutil.which('node'):
        return
    tmp = Path(__file__).resolve().parent / '.runver_driver.js'
    tmp.write_text(DRIVER, encoding='utf-8')
    try:
        r = subprocess.run(['node', str(tmp), str(W.PAGE)], capture_output=True, text=True, timeout=60)
    finally:
        tmp.unlink()
    check(r.returncode == 0, 'node draws the version', r.stderr[-1500:])
    if r.returncode:
        return
    a, b, none = json.loads(r.stdout)
    eq(a, '<div class="runver">agent-runner 1.2.3</div>', 'chats list line')
    eq(b, '<div class="setver small">agent-runner 1.2.3</div>', 'Settings line')
    eq(none, '', 'an older run without a version shows nothing')


if __name__ == '__main__':
    raise SystemExit(report([test_version]))
