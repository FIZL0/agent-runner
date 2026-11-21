"""B94: the background session's default-command and environment target '=sess:', which tmux 3.8's set-option
accepts (a bare '=sess' it rejects with "no such session", so new panes opened a plain shell)."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from _check import check, eq, report

from agent_runner import control as K  # noqa: E402


def test_background_session_options_target():
    print('B94: set-option and set-environment for the background session target =<sess>:')
    root = Path('/tmp/repo')
    cmds = K.background_session_options('ar-demo', root, ['FOO=bar=baz'])
    eq(cmds[0][:4], ['set-option', '-t', '=ar-demo:', 'default-command'], 'set-option targets =ar-demo:')
    eq(cmds[0][4], K.control_default_command(root), 'default-command is the control command')
    eq(cmds[1], ['set-environment', '-t', '=ar-demo:', 'FOO', 'bar=baz'], 'set-environment targets =ar-demo:')
    check(all(c[2] == '=ar-demo:' for c in cmds), 'no bare =ar-demo target')


def test_real_tmux_takes_the_option():
    if not shutil.which('tmux'):
        print('  (no tmux: skipped the live check)')
        return
    print('B94: on this tmux, show-options prints the default-command set through that target')
    sock = Path(tempfile.mkdtemp(prefix='b94-tmux-')) / 's'
    t = ['tmux', '-S', str(sock)]
    try:
        r = subprocess.run([*t, 'new-session', '-d', '-s', 'ar-demo'], capture_output=True, text=True, timeout=20)
        if r.returncode:
            print(f'  (tmux could not start a server: {r.stderr.strip()}; skipped)')
            return
        for args in K.background_session_options('ar-demo', Path('/tmp/repo'), []):
            r = subprocess.run([*t, *args], capture_output=True, text=True, timeout=20)
            eq(r.returncode, 0, f'tmux {args[0]} succeeds ({r.stderr.strip()})')
        out = subprocess.run([*t, 'show-options', '-v', '-t', 'ar-demo', 'default-command'],
                             capture_output=True, text=True, timeout=20).stdout.strip()
        eq(out, K.control_default_command(Path('/tmp/repo')), 'show-options prints the control command')
    finally:
        subprocess.run([*t, 'kill-server'], capture_output=True, timeout=20)


if __name__ == '__main__':
    raise SystemExit(report([test_background_session_options_target, test_real_tmux_takes_the_option]))
