#!/usr/bin/env python3
"""T21: a suite that imports _check leaves nothing in its temp folder, however it ends, with its own exit code."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from _check import ROOT, check, eq, report

HEAD = ('import json, os, subprocess, sys, tempfile\nfrom pathlib import Path\n'
        'import _check\nfrom _check import check, report\n'
        'd = Path(tempfile.mkdtemp()); (d / "f").write_text("x")\n')
LEAK = ('f = Path(os.environ["LEAK_FILE"])\n'
        'f.write_text(json.dumps({"projects": {(_check.TMP_ROOT / "s1").as_posix(): {}}}))\n')


def suite(body: str) -> tuple[subprocess.CompletedProcess, list[str]]:
    """Run HEAD + body as a suite of its own; its result, and what it left in its temp folder."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as t:
        tmp, conf = Path(t) / 'tmp', Path(t) / 'conf'
        tmp.mkdir()
        conf.mkdir()
        env = {**os.environ, 'TMPDIR': str(tmp), 'TEMP': str(tmp), 'TMP': str(tmp), 'CLAUDE_CONFIG_DIR': str(conf),
               'LEAK_FILE': str(conf / '.claude.json'), 'PYTHONPATH': str(ROOT / 'tests')}
        r = subprocess.run([sys.executable, '-c', HEAD + body], env=env, cwd=t, capture_output=True, text=True,
                           timeout=60)
        return r, sorted(p.name for p in tmp.iterdir())


def ends(body: str, code: int, what: str) -> subprocess.CompletedProcess:
    r, left = suite(body)
    eq((r.returncode, left), (code, []), f'{what}: exit code {code}, nothing left')
    return r


def test_exit():
    print('T21: _check removes its temp root and git config at exit')
    ends('sys.exit(report([lambda: check(True, "fine")]))', 0, 'a suite that passed')
    ends('sys.exit(report([lambda: check(False, "bad")]))', 1, 'a suite that failed')
    ends('raise RuntimeError("broken")', 1, 'a suite that raised')
    ends('pass', 0, 'a suite without report()')
    r = ends(LEAK + 'sys.exit(report([]))', 1, 'a trust entry leaked')
    check('FAIL the real ~/.claude.json' in r.stdout, 'and the leak is reported', r.stdout + r.stderr)
    r = ends(LEAK, 1, 'a trust entry leaked without report()')
    check('FAIL the real ~/.claude.json' in r.stdout, 'and the leak is reported', r.stdout + r.stderr)
    if os.name != 'nt':
        ends('d.chmod(0o500)\nsys.exit(report([]))', 0, 'a read-only folder')
        ends('p = os.fork()\nif p == 0:\n    sys.exit(0)\nos.waitpid(p, 0)\n'
             'sys.exit(0 if d.exists() else 3)', 0, 'a forked child that ended first')


def test_still_running():
    print('T21: a process still running in the temp root does not change the exit code')
    if os.name != 'nt':  # Windows keeps a running process's current folder
        ends('subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)"], cwd=d, stdin=subprocess.DEVNULL,'
             ' stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\nsys.exit(report([]))', 0,
             'a process in the folder')
    writer = ('import os, sys, time\\nend = time.time() + 2\\nwhile time.time() < end:\\n'
              '    try:\\n        os.makedirs(sys.argv[1], exist_ok=True)\\n'
              '        open(sys.argv[1] + "/w", "w").close()\\n    except OSError:\\n        pass\\n')
    r, _ = suite(f"subprocess.Popen([sys.executable, '-c', '{writer}', str(d / 'sub')], stdin=subprocess.DEVNULL,"
                 ' stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\nsys.exit(report([]))')
    eq((r.returncode, 'Traceback' in r.stderr), (0, False), 'a process still writing there: exit code 0')
    r, _ = suite('import shutil\nshutil.rmtree = lambda *a, **k: None\nsys.exit(report([]))')
    eq((r.returncode, r.stderr), (0, ''), 'a folder that cannot be removed: exit code 0, no error said')


if __name__ == '__main__':
    sys.exit(report([test_exit, test_still_running]))
