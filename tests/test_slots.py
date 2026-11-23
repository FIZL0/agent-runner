"""F170: a slot's and a control session's settings name the run's own theme, and their jobs say so."""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

from _check import check, eq, report
from agent_runner import control as K, session_theme as T, slots, state as S, web as W


def test_theme(tmp: Path) -> None:
    subprocess.run(['git', 'init', '-q', str(tmp)], check=True)
    (tmp / 'plan').mkdir()
    (tmp / 'plan' / 'TODO.md').write_text('# TODO\n', encoding='utf-8')
    S.init(tmp)
    want = {'theme': 'custom:agent-runner', 'spinnerTipsEnabled': False, 'prefersReducedMotion': True}
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


def run() -> None:
    with tempfile.TemporaryDirectory() as d:
        test_theme(Path(d))


if __name__ == '__main__':
    raise SystemExit(report([run]))
