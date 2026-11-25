#!/usr/bin/env python3
"""F424: Home clears old build output by itself in a project whose run is off, and nothing else.

    python3 tests/test_build_clean.py      (temp folders)
"""
from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from types import SimpleNamespace

from _check import check, eq, git, report
from test_build_output import CARGO, TAG, cmake, fixture, link, write

from agent_runner import build_clean as C  # noqa: E402
from agent_runner import vitals as V  # noqa: E402

DAY = 24 * 3600.0
ELSEWHERE = [os.sep + 'elsewhere']  # processes there are, none in a worktree


def age(top: Path, days: float = 4) -> None:
    at = (time.time() - days * DAY,) * 2
    for d, _, files in os.walk(top, topdown=False):
        for f in files:
            if not os.path.islink(os.path.join(d, f)):
                os.utime(os.path.join(d, f), at)
            elif os.utime in os.supports_follow_symlinks:
                os.utime(os.path.join(d, f), at, follow_symlinks=False)
        os.utime(d, at)


def profile(p: Path) -> Path:
    write(p / '.fingerprint' / 'a')
    write(p / 'deps' / 'a.rlib', 'z' * 1000)
    return p


def project(root: Path, d: Path) -> V.Project:
    return V.Project(root, d.parent, root / '.runner', 'main', up=False, busy=set(), resume=set())


def run(root: Path, d: Path, off=lambda p: True, cwds=lambda: ELSEWHERE, rm=shutil.rmtree) -> list:
    return C.clean_builds([project(root, d)], off, cwds, time.time(), V.du, rm)


def built(aged: bool = True) -> tuple[Path, Path, Path]:
    """A worktree with one CMake build folder, 4 days old."""
    root, d = fixture()
    cmake(d / 'build' / 'linux', d)
    if aged:
        age(d)
    return root, d, d / 'build' / 'linux'


def test_removed():
    print('old build output goes; every other file stays')
    root, d, b = built()
    write(d / '.cache' / 'CACHEDIR.TAG', TAG)
    write(d / 'build' / 'check.log')
    write(d / 'build' / 'fco' / 'out.txt')
    write(d / 'notes.txt')
    write(d / 'modding' / 'a.py')
    t = d / 'target'
    write(t / 'CACHEDIR.TAG', CARGO)
    write(t / '.rustc_info.json')
    gone = [b, d / '.cache', profile(t / 'debug'), profile(t / 'wasm32-wasip1' / 'release'),
            profile(t / 'platforms' / 'release')]
    write(t / 'platforms' / 'CACHEDIR.TAG', CARGO)
    own = t / 'm157-ps2-float'  # a hand-made checkout, with no .git
    kept = [write(own / 'src' / 'lib.rs'), write(own / 'Cargo.toml'), write(t / 'apk' / 'base.apk'),
            write(t / 'game.ipa'), d / 'build' / 'check.log', d / 'build' / 'fco' / 'out.txt', d / 'notes.txt',
            d / 'modding' / 'a.py', write(d / 'false' / 'x')]
    profile(own / 'target' / 'debug')
    write(own / 'target' / 'CACHEDIR.TAG', CARGO)
    age(d)
    got = run(root, d)
    eq([str(f.relative_to(d)) for f in gone if f.exists()], [], 'a CMake folder, a cache, Cargo profiles: gone')
    eq([str(f.relative_to(d)) for f in kept if not f.exists()], [], 'logs, notes, a checkout in target: kept')
    check((own / 'target' / 'debug').is_dir(), 'nothing in the checkout is looked at')
    eq([(w, n) for w, n, _ in got], [(d, len(gone))], 'it says what went')
    check(got and got[0][2] >= 3000, 'and the bytes', got)
    eq(run(root, d), [], 'nothing left for the next walk')


def test_when():
    print('only when the run is off, nobody works there, and 3 days are quiet')
    root, d, b = built()
    eq(run(root, d, off=lambda p: False), [], 'a run up')
    eq(run(root, d, cwds=lambda: [str(b)]), [], 'a process in it')
    eq(run(root, d, cwds=lambda: [str(d)]), [], 'a process in the worktree')
    eq(run(root, d, cwds=lambda: []), [], 'no /proc to tell')
    age(b, 2)
    eq(run(root, d), [], 'written 2 days ago')
    age(d)
    cmake(d / 'cm', d)
    eq(run(root, d), [], 'a fresh build beside it: the worktree is still used')
    age(d)
    check(b.exists() and (d / 'cm').exists(), 'all still there')
    eq(len(run(root, d)), 1, 'then both go')

    print('looked at again just before each removal')
    for what in ('run', 'process', 'write'):
        root, d, b = built()
        cmake(d / 'cm', d)
        age(d)
        state = {'off': True, 'cwds': ELSEWHERE}
        went = []

        def rm(p):
            went.append(p)
            shutil.rmtree(p)
            if what == 'run':
                state['off'] = False
            elif what == 'process':
                state['cwds'] = [str(d)]
            else:
                write(d / 'cm' / 'new.o')
        run(root, d, lambda p: state['off'], lambda: state['cwds'], rm)
        eq(went, [b], f'a {what} since the first: the second stays')

    print('a folder that cannot be removed')
    root, d, b = built()

    def refuse(p):
        raise OSError('busy')
    eq(run(root, d, rm=refuse), [], 'freed nothing')


def test_kept():
    print('kept: no mark, tracked, not ignored, a link, a repository, a person\'s notes')
    root, d = fixture()
    write(d / 'build' / 'a.o')
    write(d / '.cache' / 'CACHEDIR.TAG', 'not the signature')
    cmake(d / 'cm', d / 'cm')  # built where its sources are
    cmake(d / 'plain', d)  # not ignored: an uncommitted folder
    write(d / '.venv' / 'pyvenv.cfg')
    write(d / '.venv' / 'CACHEDIR.TAG', TAG)  # as uv makes it
    cmake(d / 'node_modules' / 'x' / 'build', d)
    age(d)
    eq(run(root, d), [], 'an ignored folder that is no build, a false tag, sources inside, an uncommitted folder, '
                         'installed packages')

    root, d, b = built()
    write(b / 'kept.c')
    git(d, 'add', '-f', 'build/linux/kept.c')
    age(d)
    eq(run(root, d), [], 'a tracked file in it')
    root, d, b = built()
    write(b / 'notes.md')
    age(d)
    eq(run(root, d), [], 'a notes file straight in it')

    root, d, b = built()
    out = d.parent / 'far'
    cmake(out, d)
    if link(d / 'cm', out) and link(d / 'build' / 'inner', out):
        age(d)
        age(out)
        eq([n for _, n, _ in run(root, d)], [1], 'the build goes')
        check((out / 'CMakeCache.txt').is_file() and (d / 'cm').is_symlink() and (d / 'build' / 'inner').is_symlink(),
              'a link to one stays, and what it leads to')

    root, d, b = built()
    git(d, 'init', '-q', str(d / 'modding'))
    cmake(d / 'modding' / 'out', d)
    git(d, 'clone', '-q', str(root), str(b / 'mine'))
    age(d)
    eq(run(root, d), [], 'one in a repository of its own, and one that holds one')

    print('an uncommitted change')
    root, d, b = built()
    write(d / '.gitignore', (d / '.gitignore').read_text() + '# mine\n')
    write(d / 'new.txt')
    before = git(d, 'status', '--porcelain')
    run(root, d)
    check(not b.exists(), 'does not hold the build')
    check(before and git(d, 'status', '--porcelain') == before, 'and stays')

    print('only a runner worktree of this project')
    root, d, b = built()
    d2 = d.parent / 'mine'
    git(root, 'worktree', 'add', '-q', '--detach', str(d2), 'main')
    cmake(d2 / 'build', d2)
    git(d, 'clone', '-q', str(root), str(d.parent / 's7'))
    cmake(d.parent / 's7' / 'build', d.parent / 's7')
    age(d.parent)
    eq([w for w, _, _ in run(root, d)], [d], 'not another folder, nor a clone')


def test_fetched():
    print('a repository CMake fetched, with nothing of its own, does not hold its build folder')
    for change in (None, 'a.c'):
        root, d, b = built()
        dep = b / '_deps' / 'lib-src'
        dep.parent.mkdir()
        git(d, 'clone', '-q', str(root), str(dep))
        if change:
            write(dep / change)
        age(d)
        run(root, d)
        eq(b.exists(), bool(change), f'local change: {change}')
    root, d, _ = built()
    t = profile(d / 'target' / 'debug')
    write(d / 'target' / 'CACHEDIR.TAG', CARGO)
    git(d, 'clone', '-q', str(root), str(t / '_deps' / 'x'))
    age(d)
    run(root, d)
    check(t.exists(), '_deps outside a CMake folder speaks for nothing')


def test_walk():
    print('Home\'s regular walk does it and logs it; the Clean button\'s fresh list does not')
    root, d, b = built()
    said = []
    proc = d.parent / 'proc'
    (proc / '10').mkdir(parents=True)
    if not link(proc / '10' / 'cwd', root):
        return
    s = SimpleNamespace(proc=proc, disk=root, procs={}, proc_cpu={}, sample=lambda now: {})
    up = {'up': True}
    v = V.Vitals(lambda: [], None, tailscale=False, sampler=s, usage=lambda: {}, registry=d.parent / 'none',
                 info=lambda r: up, log=said.append)
    p = project(root, d)
    v.refresh_footprint([p])
    check(b.exists() and not said, 'a run up since the projects were read: kept')
    up.clear()
    v.refresh_footprint([p])
    check(b.exists(), 'a run that cannot be told: kept')
    up['up'] = False
    v.refresh_footprint([p], auto=False)
    check(b.exists(), 'the Clean button\'s list removes nothing')
    foot = v.refresh_footprint([p])
    check(not b.exists() and d.is_dir(), 'the walk removes it')
    check(len(said) == 1 and 'freed' in said[0] and str(d) in said[0], f'logged: {said}')
    eq(foot['worktrees'], V.du(d), 'the footprint is of what is left')


if __name__ == '__main__':
    raise SystemExit(report([test_removed, test_when, test_kept, test_fetched, test_walk]))
