#!/usr/bin/env python3
"""F499 (issue #7): a gate that prints a byte that is not UTF-8 neither crashes done nor fails."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from _check import eq, check, report


def test_gate_non_utf8_output():
    print('F499: a passing gate that writes b"ok \\xe9" gives rc 0 and output starting "ok "')
    from agent_runner.gitops import shell
    with tempfile.TemporaryDirectory() as t:
        cmd = f'"{sys.executable}" -c "import sys; sys.stdout.buffer.write(b\'ok \\xe9\\n\')"'
        rc, out = shell(cmd, Path(t), None, 60)
        eq(rc, 0, 'the gate passes')
        check(out.startswith('ok '), f'output kept, the bad byte replaced: {out!r}')


if __name__ == '__main__':
    raise SystemExit(report([test_gate_non_utf8_output]))
