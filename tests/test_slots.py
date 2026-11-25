"""F170: a slot's and a control session's settings name the run's own theme, and their jobs say so."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest import mock

from _check import check, eq, report
from agent_runner import brief as B, control as K, inbox_lock, plat, session_theme as T, slots, state as S, web as W


def test_theme(tmp: Path) -> None:
    subprocess.run(['git', 'init', '-q', str(tmp)], check=True)
    (tmp / 'plan').mkdir()
    (tmp / 'plan' / 'TODO.md').write_text('# TODO\n', encoding='utf-8')
    S.init(tmp)
    want = {'theme': 'custom:agent-runner', 'spinnerTipsEnabled': False, 'prefersReducedMotion': True,
            'bashEditDiffEnabled': False}
    flags = slots.Claude().flags('sid', 'opus', 90, False, False)
    got = json.loads(flags[flags.index('--settings') + 1])
    eq({k: got.get(k) for k in want}, want, 'a slot')
    eq({k: K.control_settings_data().get(k) for k in want}, want, 'a control session')
    check(T.theme_file().is_file(), 'the theme file is there for them')
    with mock.patch.object(K.plat, 'spawn_detached', side_effect=OSError('no')):
        K.hidden_shim('control7', ['x'])
    S.C.notes('control7.live').write_text('1', encoding='utf-8')
    eq(W.frame_look('c7'), 'page', "a chat's frame follows the page")
    with mock.patch.object(T, 'theme_file', lambda: tmp / 'plan' / 'TODO.md' / 'x.json'), \
            mock.patch.object(K.plat, 'spawn_detached', side_effect=OSError('no')):
        S.C.notes('control7.live').unlink()
        K.hidden_shim('control7', ['x'])
    S.C.notes('control7.live').write_text('1', encoding='utf-8')
    check(W.frame_look('c7') != 'page', 'not without the theme file')


def test_artifact_c48(tmp: Path) -> None:
    """C48: only a concept task's session loads the Artifact tool."""
    def tools(**kw):
        got = slots.lean(**kw)
        return got[got.index('--tools') + 1].split(',')
    check('Artifact' not in tools(), 'a slot has no Artifact tool')
    check('Artifact' in tools(artifact=True), 'a concept has it')
    for a in (False, True):
        fl = slots.Claude().flags('sid', 'opus', 90, True, False, a)
        eq('Artifact' in fl[fl.index('--tools') + 1].split(','), a, f'a resumed session keeps what it had ({a})')
    eq(B.concept_at(None), False, 'no worktree')
    with mock.patch.object(B, 'git', return_value=mock.Mock(stdout='task/K5\n')), \
            mock.patch.object(B.P, 'concept', lambda t: t.startswith('K')):
        eq(B.concept_at(tmp), True, 'a K branch')
    with mock.patch.object(B, 'git', return_value=mock.Mock(stdout='task/C48\n')), \
            mock.patch.object(B.P, 'concept', lambda t: t.startswith('K')):
        eq(B.concept_at(tmp), False, 'a C branch')


def test_one_sender_b161(tmp: Path) -> None:
    """B161: senders at once (threads and another process) each type a whole prompt: a paste, then its Enter."""
    if plat.WINDOWS:
        return
    inbox = tmp / 'control7.in'
    os.mkfifo(inbox)
    fd = os.open(inbox, os.O_RDONLY | os.O_NONBLOCK)
    ok = []
    try:
        other = subprocess.Popen([sys.executable, '-c', 'import sys; from pathlib import Path; from agent_runner import slots; '
                                  'sys.exit(not slots.send_fifo(Path(sys.argv[1]), "three"))', str(inbox)],
                                 cwd=Path(slots.__file__).parents[1])
        first = threading.Thread(target=lambda: ok.append(slots.send_fifo(inbox, 'one')))
        first.start()
        end = time.monotonic() + 10
        got = b''
        while b'one' not in got and time.monotonic() < end:  # 'one' has its paste in: 'two' must wait for its Enter
            try:
                got += os.read(fd, 65536)
            except BlockingIOError:
                pass
            time.sleep(0.01)
        ts = [first, threading.Thread(target=lambda: ok.append(slots.send_fifo(inbox, 'two'))),
              threading.Thread(target=lambda: ok.append(slots.send_fifo_raw(inbox, b'\x1b')))]
        for t in ts[1:]:
            t.start()
        for t in ts:
            t.join(40)
        eq(other.wait(60), 0, 'the other process sent')
        try:
            got += os.read(fd, 65536)
        except BlockingIOError:
            pass
        eq(ok, [True] * 3, 'all sent')
        left = got
        for w in (b'one', b'two', b'three'):
            whole = slots.PASTE % w + b'\r'
            check(whole in left, f'{w} is a paste and its own Enter', got)
            left = left.replace(whole, b'', 1)
        eq(left, b'\x1b', 'and the key on its own')
        check(got.index(b'one') < got.index(b'two'), 'in order', got)
        with mock.patch.object(inbox_lock, 'LOCK_WAIT', 0.1), plat.lock(tmp / 'control7.in.lock'):
            eq(slots.send_fifo(inbox, 'x'), False, 'not typed while another sender has it')
    finally:
        os.close(fd)


def run() -> None:
    with tempfile.TemporaryDirectory() as d:
        test_theme(Path(d))
        test_artifact_c48(Path(d))
    with tempfile.TemporaryDirectory() as d:
        test_one_sender_b161(Path(d))


if __name__ == '__main__':
    raise SystemExit(report([run]))
