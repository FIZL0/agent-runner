"""B807: two writers of one file at the same moment each have a temp file of their own, and a change of the voice
file or of Home's registry is never lost to another one."""
from __future__ import annotations

import contextlib
import json
import os
import tempfile
import threading
from pathlib import Path
from unittest import mock

from _check import check, eq, git, report

from agent_runner import config as CF, home as H, plansync as PS, plat, status as ST, voice as V, web as W
from agent_runner import whole_write as WW

STAMPS = ('2026-11-25T10:00:00+00:00', '2026-11-25T11:00:00+00:00')


def left(f: Path) -> list[str]:
    return [p.name for p in f.parent.iterdir() if p.name.startswith(f.name + '.') and p.name.endswith('.tmp')]


def two(f: Path, first, second) -> None:
    """`second` runs whole between `first`'s write of its temp file and its move; then a move that fails."""
    real, tmps = os.replace, []

    def replace(src, dst):
        if Path(dst) != f:
            return real(src, dst)
        tmps.append(Path(src))
        if len(tmps) == 1:
            second()
        return real(src, dst)

    with mock.patch.object(os, 'replace', replace):
        try:
            first()
            got = None
        except FileNotFoundError as e:
            got = e
    eq(got, None, f'{f.name}: the first writer does not crash')
    eq(len(set(tmps)), 2, f'{f.name}: each wrote a temp file of its own')
    eq({t.parent for t in tmps}, {f.parent}, f'{f.name}: in the same directory')
    eq(left(f), [], f'{f.name}: no temp file is left')


def fails(f: Path, write) -> None:
    before = f.read_bytes()
    said = ''
    with mock.patch.object(os, 'replace', side_effect=PermissionError('held')):
        try:
            write()
        except PermissionError as e:
            said = str(e)
    eq(said, 'held', f'{f.name}: a move that fails still says so')
    eq(left(f), [], f'{f.name}: and its temp file is removed')
    eq(f.read_bytes(), before, f'{f.name}: which stays as it was')


@contextlib.contextmanager
def folder():
    """A project of its own, and a config folder of its own."""
    from agent_runner import runner as R
    with tempfile.TemporaryDirectory(prefix='agent-runner-temp-names-') as t:
        d = Path(t).resolve()
        repo = d / 'repo'
        repo.mkdir()
        git(repo, 'init', '-q')
        with mock.patch.dict(os.environ, {'XDG_CONFIG_HOME': str(d / 'config'),
                                          'AGENT_RUNNER_HOME_CONFIG': str(d / 'home')}):
            R.init(repo)
            yield d, repo


def test_two_writers():
    print('B807: two writers of one file at the same moment both end well')
    with folder() as (d, repo):
        f = d / 'config' / 'agent-runner' / 'voice.md'
        two(f, lambda: V._write(f, 'one\n'), lambda: V._write(f, 'two\n'))
        eq(f.read_text(encoding='utf-8'), 'one\n', 'the voice file is whole')
        fails(f, lambda: V._write(f, 'three\n'))

        f = W.chat_order_path()
        two(f, lambda: W.save_chat_order(pins=['c1']), lambda: W.save_chat_order(pins=['c2', 'c1']))
        eq(json.loads(f.read_text(encoding='utf-8')), {'pins': ['c1']}, 'the chat order is whole')
        fails(f, lambda: W.save_chat_order(pins=['c3']))

        f = ST.since_mark_file()
        f.unlink(missing_ok=True)
        two(f, lambda: ST.move_since_mark(STAMPS[0]), lambda: ST.move_since_mark(STAMPS[0]))
        eq(f.read_text(encoding='utf-8'), STAMPS[0] + '\n', 'the mark is whole')
        fails(f, lambda: ST.move_since_mark(STAMPS[1]))

        f = H.registry_file()
        two(f, lambda: H.save_registry({'port': 1}), lambda: H.save_registry({'port': 2}))
        eq(json.loads(f.read_text(encoding='utf-8')), {'port': 1}, 'the registry is whole')
        fails(f, lambda: H.save_registry({'port': 3}))

        f = d / 'shared.toml'
        f.write_bytes(b'x\n')
        f.chmod(0o640)
        mode = f.stat().st_mode
        two(f, lambda: PS._write(f, b'one\n'), lambda: PS._write(f, b'two\n'))
        eq(f.read_bytes(), b'one\n', 'the shared file is whole')
        eq(f.stat().st_mode, mode, 'and keeps its mode')
        fails(f, lambda: PS._write(f, b'three\n'))

        f = CF.local_settings_file(repo)
        save = lambda key, v: CF.save_local_setting(repo, 'run', key, v)  # noqa: E731
        save('slots', 2)
        f = f.resolve()
        f.chmod(0o600)
        mode = f.stat().st_mode
        two(f, lambda: save('slots', 3), lambda: save('slots', 4))
        check('slots = 3' in f.read_text(encoding='utf-8'), 'the settings file is whole')
        eq(f.stat().st_mode, mode, 'and keeps its mode')
        fails(f, lambda: save('slots', 5))


def together(f: Path, first, second) -> None:
    """`second` starts while `first` is about to move its file in, and gets as far as it can: it finds the lock
    held, or (with no lock) it is through."""
    real, take = os.replace, plat.lock
    far, threads, errors = threading.Event(), [], []

    def lock(path):
        got = take(path)
        if got is None:
            far.set()
        return got

    def run():
        try:
            second()
        except BaseException as e:  # noqa: BLE001 - said below
            errors.append(e)
        finally:
            far.set()

    def replace(src, dst):
        if Path(dst) == f and not threads:
            threads.append(threading.Thread(target=run))
            threads[0].start()
            check(far.wait(60), 'the second change got to the lock')
        return real(src, dst)

    with mock.patch.object(os, 'replace', replace), mock.patch.object(WW.plat, 'lock', lock), \
            mock.patch.object(WW, 'LOCK_WAIT', 60.0):
        first()
        for t in threads:
            t.join(60)
    eq(errors, [], 'the second change ends well')
    eq(len(threads), 1, 'the two did meet')


def test_no_change_lost():
    print('B807: a change made beside another one is not lost')
    with folder() as (_, repo):
        c = CF.cfg()
        f = V.global_path(c)
        V.add(c, 'old')
        together(f, lambda: V.add(c, 'say agent'), lambda: V.add(c, 'shorter'))
        eq(V.rules(f), ['old', 'say agent', 'shorter'], 'both added lines are there')
        together(f, lambda: V.forget(c, 'old'), lambda: V.add(c, 'no ids'))
        eq(V.rules(f), ['say agent', 'shorter', 'no ids'], 'a line added beside a forget is kept')

        f = H.registry_file()
        together(f, lambda: H.add_project(str(repo)), lambda: H.trust_change('add', '10.0.0.0/8'))
        together(f, lambda: H.mark_installed(True),
                 lambda: H.peer_change('add', 'http://there:8770/?t=abc'))
        reg = H.load_registry()
        eq((reg['projects'], reg['trusted_networks'], reg['installed'], reg['peers']),
           ([str(repo)], ['10.0.0.0/8'], True, ['http://there:8770/?t=abc']), 'every change of the registry is there')
        together(f, lambda: H.remove_project(str(repo)), lambda: H.trust_change('remove', '10.0.0.0/8'))
        reg = H.load_registry()
        eq((reg['projects'], reg['trusted_networks']), ([], []), 'and both removals')


def test_lock_not_had():
    print('B807: a lock that cannot be had does not fail the change')
    with folder():
        with mock.patch.object(WW.plat, 'lock', side_effect=PermissionError('read-only')):
            H.mark_installed(True)
        with mock.patch.object(WW.plat, 'lock', return_value=None), mock.patch.object(WW, 'LOCK_WAIT', 0.0):
            H.trust_change('add', '10.0.0.0/8')
        reg = H.load_registry()
        eq((reg['installed'], reg['trusted_networks']), (True, ['10.0.0.0/8']), 'both changes are made')


if __name__ == '__main__':
    raise SystemExit(report([test_two_writers, test_no_change_lost, test_lock_not_had]))
