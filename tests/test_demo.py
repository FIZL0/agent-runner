#!/usr/bin/env python3
"""F194a: `agent-runner demo` makes the example project, and `demo --remove` takes only that away.

    python3 tests/test_demo.py        (temp folders, a bare remote in them, a wheel built; no agent; seconds)
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from unittest import mock

from _check import ROOT, RUN, check, eq, git, report

from agent_runner import demo as D  # noqa: E402
from agent_runner import plan as P  # noqa: E402
from agent_runner import plat  # noqa: E402

os.environ.pop('AGENT_RUNNER_CONFIG', None)
TMP = Path(tempfile.mkdtemp()).resolve()
# nothing here touches the person's own folders: runs, Runner Home's registry, Claude Code's settings
os.environ['AGENT_RUNNER_HOME'] = str(TMP / 'runs' / '{repo}')
os.environ['AGENT_RUNNER_HOME_CONFIG'] = str(TMP / 'home-config')
ENV = {**os.environ, 'CLAUDE_CONFIG_DIR': str(TMP / 'claude'), 'PYTHONDONTWRITEBYTECODE': '1'}


def refused(fn, *a) -> str:
    try:
        fn(*a)
    except D.DemoError as e:
        return str(e)
    return ''


def run(root: Path, *a: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(RUN), *a], cwd=root, capture_output=True, text=True,
                          encoding='utf-8', env=ENV, timeout=120)


def said(*a: str) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        rc = D.main(list(a))
    return rc, out.getvalue()


def test_make() -> None:
    print('demo makes the example project')
    root = TMP / 'made by demo'
    rc, text = said(str(root))
    eq(rc, 0, 'it is made')
    check('Nothing has started' in text and f'cd {plat.quote(str(root))}' in text, 'it prints the next step', text)
    check(D.is_demo(root), 'it is known as the example project')
    eq(git(root, 'status', '--porcelain'), '', 'everything is committed')
    origin = Path(git(root, 'remote', 'get-url', 'origin'))
    check(origin.resolve().is_relative_to(root), 'origin is a folder of its own', str(origin))
    eq(git(origin, 'rev-parse', 'main'), git(root, 'rev-parse', 'HEAD'), 'main is pushed there')
    check(not (root / '.runner').exists(), 'no run was started')
    files = {p.relative_to(D.source()).as_posix() for p in D.source().rglob('*')
             if p.is_file() and '__pycache__' not in p.parts}
    eq(set(git(root, 'ls-files').splitlines()), files, 'the files are the example\'s')

    gate = subprocess.run([sys.executable, '-m', 'unittest', '-q'], cwd=root, capture_output=True, text=True, env=ENV)
    eq(gate.returncode, 0, 'its gate passes')
    check('Ran 5 tests' in gate.stderr, 'the gate runs its tests', gate.stderr)
    toml = D.Config(root)
    eq(toml.run['test'], 'python3 -m unittest -q || python -m unittest -q', 'the gate in its settings is that one')

    ls = P.lines(root / 'plan' / 'TODO.md')
    eq(P.open_ids(ls), {'F3', 'F4', 'T1', 'F5', 'F6', 'F7', 'D1', 'F8'}, 'the plan parses')
    at = P._open_at(ls)
    eq(P.waits_on(ls, at['F5']), ['F3'], 'a task waits for another')
    (ask,) = P.asks(root / 'plan' / 'TODO.md')
    eq((ask[0], ask[1]), ('DECIDE', 'F7'), 'one item needs you')
    check('F7' in P.asked_at(root / 'plan' / 'TODO.md'), 'it is asked when the project is made')
    check(P.long_form(root / 'plan', 'F5').is_file(), 'a task has a long form')
    eq(sum(l.startswith('- [x]') for l in P.lines(root / 'plan' / 'DONE.md')), 3, 'some tasks are done')
    dry = run(root, 'run', '--dry-run', '3')
    for n, tid in enumerate(('F3', 'F4', 'T1'), 1):
        check(f'slot {n}: {tid} ' in dry.stdout, f'{tid} can start beside the others', dry.stdout + dry.stderr)


def test_never_over() -> None:
    print('demo never makes it over something')
    root = TMP / 'mine'
    root.mkdir()
    (root / 'note').write_text('keep', encoding='utf-8')
    check('is there already' in refused(D.make, root), 'a folder that exists is refused')
    eq([p.name for p in root.iterdir()], ['note'], 'and left as it is')
    check('not made by' in refused(D.remove, root), 'and never removed')
    check((root / 'note').is_file(), 'it is still there')
    check('no example project' in refused(D.remove, TMP / 'nowhere'), 'removing nothing says so')
    demo = D.make(TMP / 'one')
    check(f'--remove {plat.quote(str(demo))}' in refused(D.make, demo), 'a second demo there is refused')
    copy = TMP / 'copy'
    shutil.copytree(demo, copy)
    check(refused(D.remove, copy) != '', 'a copy a person made of it is theirs')
    with mock.patch.object(D, '_git', side_effect=D.DemoError('git init failed')):
        check('git init' in refused(D.make, TMP / 'half'), 'a failure says why')
    with mock.patch.object(D, '_git', side_effect=KeyboardInterrupt):
        try:
            D.make(TMP / 'half')
        except KeyboardInterrupt:
            pass
    check(not (TMP / 'half').exists(), 'and leaves nothing half made')


def test_git_env() -> None:
    print('demo inside a git hook makes its own repository')
    other = TMP / 'other'
    other.mkdir()
    git(other, 'init', '-q')
    with mock.patch.dict(os.environ, {'GIT_DIR': str(other / '.git')}):
        root = D.make(TMP / 'hooked')
    check((root / '.git' / 'HEAD').is_file() and D.is_demo(root), 'in its own folder')
    eq(subprocess.run(['git', 'remote'], cwd=other, capture_output=True, text=True).stdout, '', 'not the other one')


def test_no_identity() -> None:
    print('demo works with no git identity on the machine')
    blank = TMP / 'blank-gitconfig'
    blank.write_text('', encoding='utf-8')
    with mock.patch.dict(os.environ, {'GIT_CONFIG_GLOBAL': str(blank)}):
        root = D.make(TMP / 'nobody')
        eq(git(root, 'config', '--local', 'user.name'), 'agent-runner demo', 'it has one of its own')
    eq(git(root, 'log', '-1', '--format=%s'), 'The example project', 'and its commit')
    r = D.make(TMP / 'somebody')
    local = subprocess.run(['git', 'config', '--local', 'user.name'], cwd=r, capture_output=True, text=True).stdout
    eq(local, '', 'the person\'s own identity is used when there is one')


def test_remove() -> None:
    print('demo --remove takes it away')
    root = D.make(TMP / 'gone')
    runs = TMP / 'runs' / 'gone'
    git(root, 'worktree', 'add', '-q', '-b', 'task/F3', str(runs / 's1'))
    elsewhere = TMP / 'elsewhere'
    git(root, 'worktree', 'add', '-q', '-b', 'task/F4', str(elsewhere))
    (runs / 'tmp').mkdir()
    notes = root / '.runner'
    notes.mkdir()
    lock = plat.lock(notes / 'run.lock')
    check('a run is up' in refused(D.remove, root), 'not while a run is up')
    lock.close()
    (notes / 'control2.live').write_text(str(os.getpid()), encoding='utf-8')
    check('control2' in refused(D.remove, root), 'nor a control session')
    (notes / 'control2.live').unlink()
    check((runs / 's1').is_dir() and (root / 'greet.py').is_file(), 'and nothing was removed')
    check(str(elsewhere) in refused(D.remove, root), 'nor with a worktree of it that is not a run\'s')
    git(root, 'worktree', 'remove', str(elsewhere))
    git(root, 'worktree', 'add', '-q', str(runs / 'take-F4'), 'task/F4')
    check('take-F4' in refused(D.remove, root) and (runs / 's1').is_dir(), 'nor with a take of a task')
    git(root, 'worktree', 'remove', str(runs / 'take-F4'))
    (TMP / 'home-config').mkdir(exist_ok=True)
    reg = TMP / 'home-config' / 'home.json'
    reg.write_text(json.dumps({'projects': [str(root)], 'scan': []}), encoding='utf-8')
    rc, _ = said('--remove', str(root))
    eq(rc, 0, 'it is removed')
    check(not root.exists() and not runs.exists(), 'with the run\'s worktrees of it')
    eq(json.loads(reg.read_text(encoding='utf-8'))['projects'], [], 'Runner Home no longer lists it')

    root = D.make(TMP / 'kept')
    runs = TMP / 'runs' / 'kept'
    git(root, 'worktree', 'add', '-q', '-b', 'task/F3', str(runs / 's1'))
    (runs / 'mine.txt').write_text('keep', encoding='utf-8')
    _, left = D.remove(root)
    eq(left, [runs], 'a runs folder with something else in it is left')
    check((runs / 'mine.txt').is_file() and not (runs / 's1').exists(), 'only the worktree went')


def test_cli() -> None:
    print('the command is there')
    r = run(TMP, 'demo', str(TMP / 'cli'))
    eq(r.returncode, 0, 'agent-runner demo DIR makes it')
    check((TMP / 'cli' / 'runner.toml').is_file(), 'there', r.stdout + r.stderr)
    eq(run(TMP, 'demo', '--remove', str(TMP / 'cli')).returncode, 0, 'agent-runner demo --remove DIR removes it')
    check(not (TMP / 'cli').exists(), 'it is gone')
    check('agent-runner demo' in run(TMP, '--help').stdout, 'it is in the usage')


@contextlib.contextmanager
def in_dir(d: Path):
    was = Path.cwd()
    os.chdir(d)
    try:
        yield
    finally:
        os.chdir(was)


def test_hint() -> None:
    print('F194c: a first agent-runner in a folder that is not set up names demo, in one line')
    from agent_runner import cli, cmds
    bare, repo = TMP / 'bare', TMP / 'repo'
    for d in (bare, repo):
        d.mkdir()
    git(repo, 'init', '-q')
    r = run(bare)
    lines = [l for l in r.stderr.splitlines() if ' demo' in l]
    check(r.returncode == 2 and len(lines) == 1 and 'not set up' in lines[0], 'outside a repository', r.stderr)
    line = D.hint(None)
    check(line and '\n' not in line and 'demo' in line, 'one line', line)
    eq(D.hint(repo), line, 'in a repository with no settings and no plan')
    eq(cmds.picker_text([], 0, None, line).count(line), 1, 'the run picker shows it')
    from agent_runner import theme as TH
    check(line in cmds.picker_text([], 0, cmds.PickerPaint(TH.get(TH.DEFAULT), 256), line), 'in colour too')
    for rows in ([], [{'name': 'a', 'root': 'a', 'run': {'up': True}, 'here': False}]):
        seen = []
        with mock.patch.object(cmds, 'picker_rows', lambda *a: rows):
            cmds.cmd_pick(None, lambda: 'q', seen.append, sessions=list, hint=line)
        eq(line in seen[0], not rows, f'outside a repository the picker says it only with no run up ({len(rows)})')
    for tty in (True, False):
        out, got = io.StringIO(), []
        with in_dir(repo), contextlib.redirect_stderr(out), \
                mock.patch.object(cli, 'skill'), mock.patch.object(cli, 'user_hook'), \
                mock.patch.object(cmds, 'picker_wanted', lambda: tty), \
                mock.patch.object(cmds, 'cmd_pick', lambda here, **k: got.append(k.get('hint')) or 0), \
                mock.patch('agent_runner.runner.cmd_background', lambda a: got.append('run') or 0):
            cli.main([])
        eq((got, out.getvalue().count(line)), ([line], 0) if tty else (['run'], 1), f'bare agent-runner (terminal {tty})')
    (repo / '.runner').mkdir()
    (repo / '.runner' / 'run.log').write_text('x', encoding='utf-8')
    eq(D.hint(repo), '', 'not once a run was there')
    (repo / '.runner' / 'run.log').unlink()
    (repo / 'runner.toml').write_text('', encoding='utf-8')
    eq(D.hint(repo), '', 'nor in one set up')
    (repo / 'runner.toml').unlink()
    (repo / 'plan').mkdir()
    (repo / 'plan' / 'TODO.md').write_text('# TODO\n', encoding='utf-8')
    eq(D.hint(repo), '', 'nor in one with a plan')


def test_wheel() -> None:
    print('a built wheel holds the example project')
    src, dist = TMP / 'src', TMP / 'dist'
    src.mkdir()
    dist.mkdir()
    for f in ('pyproject.toml', 'README.md', 'LICENSE'):
        shutil.copy(ROOT / f, src)
    for d in ('agent_runner', 'examples'):
        shutil.copytree(ROOT / d, src / d, ignore=shutil.ignore_patterns('__pycache__', '.runner'))
    if importlib.util.find_spec('setuptools'):
        cmd = [sys.executable, '-c', 'import sys; from setuptools import build_meta; build_meta.build_wheel(sys.argv[1])',
               str(dist)]
    elif shutil.which('uv'):
        cmd = ['uv', 'build', '-q', '--wheel', '-o', str(dist), '.']
    else:
        cmd = [sys.executable, '-m', 'pip', 'wheel', '-q', '--no-deps', '-w', str(dist), '.']  # fetches setuptools
    r = subprocess.run(cmd, cwd=src, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=300)
    built = list(dist.glob('*.whl'))
    check(r.returncode == 0 and len(built) == 1, 'the wheel builds', (r.stdout + r.stderr)[-2000:])
    if not built:
        return
    site = TMP / 'site'
    with zipfile.ZipFile(built[0]) as z:
        z.extractall(site)
    want = {p.relative_to(ROOT / 'examples' / 'hello').as_posix() for p in (ROOT / 'examples' / 'hello').rglob('*')
            if p.is_file() and not {'__pycache__', '.runner'} & set(p.parts)}
    example = site / 'agent_runner' / 'example'
    eq({p.relative_to(example).as_posix() for p in example.rglob('*') if p.is_file()}, want, 'every file, dotfiles too')
    made = subprocess.run([sys.executable, '-m', 'agent_runner', 'demo', str(TMP / 'installed')], cwd=TMP,
                          env={**ENV, 'PYTHONPATH': str(site)}, capture_output=True, text=True, encoding='utf-8')
    check(made.returncode == 0 and D.is_demo(TMP / 'installed'), 'the installed command makes it',
          made.stdout + made.stderr)


if __name__ == '__main__':
    sys.exit(report([test_make, test_never_over, test_git_env, test_no_identity, test_remove, test_cli, test_hint, test_wheel]))
