#!/usr/bin/env python3
"""B776: what git ignores in a worktree that is no build output (`held_files`), and Clean's list with it.

    python3 tests/test_build_output.py      (temp folders)
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from _check import check, eq, git, report

from agent_runner import build_output as B  # noqa: E402
from agent_runner import vitals as V  # noqa: E402

TAG = B.CACHEDIR_SIGNATURE.decode() + '\n'
CARGO = TAG + '# This file is a cache directory tag created by cargo.\n'


def write(p: Path, text: str = 'x') -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding='utf-8')
    return p


def link(p: Path, to: Path) -> bool:
    try:
        os.symlink(to, p)
    except OSError:
        return False  # Windows without the right to make links
    return True


def fixture() -> tuple[Path, Path]:
    """A repository that ignores a lot, and a worktree of it with its commits merged."""
    t = Path(tempfile.mkdtemp(prefix='build-output-')).resolve()
    root, d = t / 'proj', t / 'runs' / 's1'
    root.mkdir()
    git(root, 'init', '-q', '-b', 'main')
    write(root / '.gitignore', '*.pyc\n/notes.txt\n/modding/\n/build/\n/target/\n/mods\n/.venv/\n/node_modules/\n'
                               '/.cache/\n/cm/\n/empty/\n')
    git(root, 'add', '-A')
    git(root, 'commit', '-q', '-m', 'base')
    d.parent.mkdir()
    git(root, 'worktree', 'add', '-q', '--detach', str(d), 'main')
    return root, d


def cmake(d: Path, home: Path) -> None:
    write(d / 'CMakeCache.txt', f'# x\nCMAKE_HOME_DIRECTORY:INTERNAL={home.as_posix()}\n')
    write(d / 'CMakeFiles' / 'a.o')


def test_build_output():
    print('build output and links are not held')
    root, d = fixture()
    eq(B.held_files(d), [], 'nothing ignored')
    write(d / 'pkg' / '__pycache__' / 'a.cpython-314.pyc')
    write(d / '.cache' / 'CACHEDIR.TAG', TAG)
    write(d / '.cache' / 'v' / 'x')
    write(d / '.venv' / 'pyvenv.cfg')
    write(d / '.venv' / 'bin' / 'python')
    write(d / 'node_modules' / 'a' / 'index.js')
    cmake(d / 'build' / 'linux', d)
    write(d / 'target' / 'CACHEDIR.TAG', CARGO)
    write(d / 'target' / '.rustc_info.json')
    for prof in ('debug', 'wasm32-wasip1/release'):
        write(d / 'target' / prof / '.fingerprint' / 'a')
        write(d / 'target' / prof / 'deps' / 'a.rlib')
    write(d / 'target' / 'wasm32-wasip1' / 'CACHEDIR.TAG', CARGO)
    (d / 'empty').mkdir()
    link(d / 'mods', root)
    eq(B.held_files(d), [], 'cache tags, a venv, node_modules, CMake and Cargo folders, .pyc, a link, an empty folder')


def test_held():
    print('everything else is held')
    root, d = fixture()
    write(d / 'notes.txt')
    write(d / 'modding' / 'a' / 'b.txt')
    eq(B.held_files(d), ['modding/', 'notes.txt'], 'a notes file, and a plain folder as one')
    cmake(d / 'build' / 'linux', d)
    write(d / 'build' / 'check.log')
    write(d / 'target' / 'CACHEDIR.TAG', CARGO)
    write(d / 'target' / 'debug' / '.fingerprint' / 'a')
    write(d / 'target' / 'debug' / 'deps' / 'a')
    write(d / 'target' / 'm157-float' / 'src' / 'main.rs')
    write(d / '.cache' / 'CACHEDIR.TAG', 'not the signature')
    eq(B.held_files(d), ['.cache/', 'build/check.log', 'modding/', 'notes.txt', 'target/m157-float/'],
       'a log beside a CMake folder, a checkout in a Cargo target folder, a false cache tag')

    eq(B.held_names(['a/b', 'n']), 'a/b, n', 'a few are named whole')
    eq(B.held_names(['a/b', 'a/c', 'm/', 'n', 'o/p', 'q'], most=3), 'a/, m/, n and 2 more', 'many by their top folder')
    _, d = fixture()
    write(d / 'pkg' / '__pycache__' / 'a.pyc')
    git(d, 'init', '-q', str(d / 'modding'))
    cmake(d / 'cm', d / 'cm')
    eq(B.held_files(d), ['cm/', 'modding/'],
       'a repository of its own, and a folder built where its sources are')
    eq(B.held_files(d / 'no-such'), None, 'git could not tell')


def test_repo_in_build():
    print('a repository in a build folder: only a CMake-fetched one with nothing of its own')
    root, d = fixture()
    cmake(d / 'build', d)
    dep = d / 'build' / '_deps' / 'lib-src'
    dep.parent.mkdir()
    git(d, 'clone', '-q', str(root), str(dep))
    eq(B.held_files(d), [], 'a fetched dependency')
    write(dep / 'a.c')
    eq(B.held_files(d), ['build/_deps/lib-src/'], 'with a local change')
    git(dep, 'add', '-A')
    git(dep, 'commit', '-q', '-m', 'mine')
    eq(B.held_files(d), ['build/_deps/lib-src/'], 'with a local commit')
    _, d = fixture()
    cmake(d / 'build', d)
    git(d, 'clone', '-q', str(root), str(d / 'build' / 'mine'))
    eq(B.held_files(d), ['build/mine/'], 'one outside _deps, even with nothing of its own')


def clean_list(root: Path, d: Path) -> list[dict]:
    p = V.Project(root, d.parent, root / '.runner', 'main', up=False, busy=set(), resume=set())
    return V.clean_plan([(p, d, 10)], [], [], set(), 0, cwds=[])


def test_clean():
    print('Clean: a merged worktree with only build output comes ticked and goes')
    root, d = fixture()
    cmake(d / 'build', d)
    safe = clean_list(root, d)
    eq([i['ask'] for i in safe], [False], 'ticked')
    write(d / 'notes.txt', 'mine')
    res = V.clean([safe[0]['id']], safe)
    check(not res['ok'] and (d / 'notes.txt').is_file(), 'a notes file that came since the list keeps it', res)

    print('one with a notes file: named, unticked, removed only when ticked')
    held = clean_list(root, d)
    eq([i['ask'] for i in held], [True], 'unticked')
    check('notes.txt' in held[0]['why'] and 'build' not in held[0]['why'].replace('build output', ''),
          'it says what it holds', held[0]['why'])
    res = V.clean([safe[0]['id']], held)
    check(not res['ok'] and (d / 'notes.txt').is_file(), 'a tick on the list from before it held the file does not count')
    res = V.clean([held[0]['id']], held)
    check(res['ok'] and not d.exists(), 'ticked, it goes', res)

    root, d = fixture()
    cmake(d / 'build', d)
    safe = clean_list(root, d)
    res = V.clean([safe[0]['id']], safe)
    check(res['ok'] and not d.exists(), 'only build output: removed', res)


if __name__ == '__main__':
    raise SystemExit(report([test_build_output, test_held, test_repo_in_build, test_clean]))
