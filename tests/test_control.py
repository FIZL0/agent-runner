"""B94: the background session's default-command and environment target '=sess:', which tmux 3.8's set-option
accepts (a bare '=sess' it rejects with "no such session", so new panes opened a plain shell)."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from unittest import mock

from _check import check, eq, git, report

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
        for args in K.background_session_options('ar-demo', Path('/tmp/repo'), ['B94_X=1']):
            r = subprocess.run([*t, *args], capture_output=True, text=True, timeout=20)
            eq(r.returncode, 0, f'tmux {args[0]} succeeds ({r.stderr.strip()})')
        out = subprocess.run([*t, 'show-options', '-v', '-t', 'ar-demo', 'default-command'],
                             capture_output=True, text=True, timeout=20).stdout.strip()
        eq(out, K.control_default_command(Path('/tmp/repo')), 'show-options prints the control command')
    finally:
        subprocess.run([*t, 'kill-server'], capture_output=True, timeout=20)


def test_handed_ask_as_c1_starts_fresh():
    print('B96: control --new --ask that gets number 1 starts fresh, named; the kept c1 session stays kept')
    from agent_runner import runner as R
    d = Path(tempfile.mkdtemp(prefix='agent-runner-control-'))
    git(d, 'init', '-q')
    (d / '.gitignore').write_text('.runner/\n')
    (d / 'README.md').write_text('demo\n')
    git(d, 'add', '-A')
    git(d, 'commit', '-qm', 'start')
    R.init(d)
    kept = str(uuid.uuid4())
    sidf = R.C.notes('control.sid')
    sidf.write_text(kept + '\n', encoding='utf-8')
    R.C.notes('control1.title').unlink(missing_ok=True)
    ask = 'install IPAS looks wrong'
    with mock.patch.object(R.Claude, 'find_transcript', lambda self, s: '/x.jsonl'), \
            mock.patch.object(K, 'remote_on', lambda: True), mock.patch.object(K, 'ask_waiting', lambda: ''):
        eq(K.control_sid(1), (kept, True), 'c1 with no ask still resumes its kept session')
        sid, resume, argv = K.control_open(1, ask=ask)
        check(not resume and sid != kept, 'the ask starts a new session', (sid, resume))
        check('--resume' not in argv, 'no --resume', argv)
        eq(argv[argv.index('--session-id') + 1], sid, 'started with --session-id <new uuid>')
        check(uuid.UUID(sid).version == 4, 'the new id is a uuid')
        eq(argv[1], K.control_ask(ask), 'the ask is its first message')
        eq(argv[argv.index('--remote-control') + 1], K.control_name(1, ask), 'Remote Control gets the ask\'s name')
        eq(K.control_given(1), K.control_name(1, ask), 'control_give recorded that name')
        check(K.control_one_ask(1, sid), 'marked as opened for one ask')
        eq(sidf.read_text(encoding='utf-8').strip(), kept, 'control.sid still holds the run\'s own c1')
        eq(K.control_sid(1), (kept, True), 'and the run\'s c1 resumes it afterwards')
        files_only = K.control_open(1, images=['/tmp/shot.png'])
        check(not files_only[1] and files_only[0] not in (kept, sid), 'a files-only ask starts fresh too')


if __name__ == '__main__':
    raise SystemExit(report([test_background_session_options_target, test_real_tmux_takes_the_option,
                             test_handed_ask_as_c1_starts_fresh]))
