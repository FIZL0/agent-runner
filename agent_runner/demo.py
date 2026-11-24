"""F194a: `agent-runner demo [DIR]`: the example project, made in a folder of its own; `--remove` takes it away.

The files are examples/hello in a clone, and the package's own `example` folder once installed (pyproject.toml maps
the one onto the other, so there is one copy). The project is a git repository whose `origin` is a bare one inside
its .git folder: a run merges and pushes as anywhere, and nothing goes online. Making it starts no agent.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

from agent_runner import plat
from agent_runner.config import RUNNER, Config, main_checkout, shown_cmd

DEFAULT = '~/agent-runner-demo'
MARK = 'agent-runner-demo.json'  # in the project's .git: this folder was made by `demo`
ORIGIN = 'demo-origin.git'       # in the project's .git too, so it is never committed and goes with the folder

RUN_WORKTREE = re.compile(r'(s|merge|fix)\d*')  # a run's own worktrees in [run] home


class DemoError(Exception):
    """Why the example project was not made or removed, for the person."""


def source() -> Path:
    """The example project's files: the installed package's, else the clone's."""
    here = Path(__file__).resolve().parent
    for d in (here / 'example', here.parent / 'examples' / 'hello'):
        if (d / 'runner.toml').is_file():
            return d
    raise DemoError('the example project is missing from this install of agent-runner: reinstall it')


def is_demo(root: Path) -> bool:
    """Was this main checkout made by `demo`, at this path?"""
    f = Path(root) / '.git' / MARK
    try:
        return Path(json.loads(f.read_text(encoding='utf-8'))['path']) == Path(root).resolve()
    except (OSError, ValueError, KeyError, TypeError):
        return False


def _git(root: Path, *a: str, may_fail: bool = False) -> str:
    """git in `root`, whatever repository a hook around us names (GIT_DIR); `may_fail`: '' when it does."""
    env = {k: v for k, v in os.environ.items() if k not in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GIT_COMMON_DIR',
                                                              'GIT_OBJECT_DIRECTORY', 'GIT_PREFIX', 'GIT_NAMESPACE')}
    r = subprocess.run(['git', *a], cwd=str(root), capture_output=True, text=True, encoding='utf-8',
                       errors='replace', env=env)
    if r.returncode and not may_fail:
        raise DemoError(f'git {a[0]} failed: {(r.stderr or r.stdout).strip()}')
    return r.stdout.strip()


def make(path: str | Path | None = None) -> Path:
    """Make the example project at `path` (DEFAULT) and return it; DemoError when something is there already."""
    root = Path(path or DEFAULT).expanduser().resolve()
    src = source()
    if not shutil.which('git'):
        raise DemoError('git is missing: install it first')
    try:
        root.parent.mkdir(parents=True, exist_ok=True)
        root.mkdir()  # fails on an existing one, so what follows is in a folder of our own
    except FileExistsError:
        raise DemoError(f'{root} is there already' + (
            f': open it, or take it away with `{shown_cmd()} demo --remove {plat.quote(str(root))}`' if is_demo(root) else
            ', and it is not the example project: name another folder')) from None
    except OSError as e:
        raise DemoError(f'cannot make {root}: {e.strerror or e}') from None
    try:
        _fill(root, src)
    except BaseException as e:  # Ctrl-C too: half a project would be refused as existing, and never removed
        _rmtree(root)
        if isinstance(e, (OSError, DemoError)):
            raise DemoError(str(e)) from None
        raise
    return root


def _fill(root: Path, src: Path) -> None:
    shutil.copytree(src, root, dirs_exist_ok=True, ignore=shutil.ignore_patterns('__pycache__', '.runner'))
    from agent_runner.plan import stamp_ask
    todo = root / 'plan' / 'TODO.md'  # the item that waits on the person is asked now, not when it was written
    ls = [head + sep + stamp_ask(why) if sep else head
          for head, sep, why in (l.partition('BLOCKED: ') for l in todo.read_text(encoding='utf-8').splitlines())]
    todo.write_text('\n'.join(ls) + '\n', encoding='utf-8', newline='\n')
    _git(root, 'init', '-q')
    _git(root, 'symbolic-ref', 'HEAD', 'refs/heads/main')
    (root / '.git' / MARK).write_text(json.dumps({'path': str(root)}) + '\n', encoding='utf-8')
    taken = _home(root)
    if taken and taken.is_dir() and any(taken.iterdir()) and not os.environ.get('AGENT_RUNNER_HOME'):
        raise DemoError(f'{taken} holds another {root.name}\'s runner files: name another folder')
    for key, value in (('user.name', 'agent-runner demo'), ('user.email', 'demo@example.invalid')):
        if not _git(root, 'config', key, may_fail=True):  # no identity on this machine: a run commits here too
            _git(root, 'config', key, value)
    origin = root / '.git' / ORIGIN
    _git(root, 'init', '-q', '--bare', str(origin))
    _git(root, '--git-dir', str(origin), 'symbolic-ref', 'HEAD', 'refs/heads/main')
    _git(root, 'remote', 'add', 'origin', str(origin))
    _git(root, 'add', '-A')
    _git(root, '-c', 'commit.gpgsign=false', 'commit', '-q', '--no-verify', '-m', 'The example project')
    _git(root, 'push', '-q', '--no-verify', '-u', 'origin', 'main')


def _home(root: Path) -> Path | None:
    """Where a run keeps this project's worktrees ([run] home), or None when its settings do not read."""
    try:
        return Config(root).home.resolve()
    except (SystemExit, OSError, ValueError, KeyError, TypeError):
        return None


def hint(top: Path | None) -> str:
    """The one line a first `agent-runner` says in a folder that is not set up (`top`: its git checkout, None
    outside a repository), '' in any other."""
    if top is not None:
        try:
            c = Config(top)
            if c.file or c.todo.exists() or (main_checkout(top) / c.run['notes'] / 'run.log').exists():
                return ''
        except (SystemExit, OSError, ValueError, KeyError, TypeError):
            return ''
    return f'not set up here yet; to try it first: {shown_cmd()} demo (an example project, in a folder of its own)'


def busy(root: Path) -> str:
    """What of agent-runner is up in the project: 'a run', 'a session (control2)', or ''."""
    from agent_runner.slots import marker_pid
    notes = root / '.runner'
    if (notes / 'run.lock').exists():
        if not (held := plat.lock(notes / 'run.lock')):
            return 'a run'
        held.close()
    for m in sorted(notes.glob('*.live')):
        if (pid := marker_pid(m)) and plat.alive(pid):
            return f'a session ({m.stem})'
    return ''


def remove(path: str | Path | None = None) -> tuple[Path, list[Path]]:
    """Take the example project away, its runner worktrees too: (the folder it was, what was left). DemoError,
    and nothing removed, when `demo` did not make it, a run or session is up, or someone has a worktree of it."""
    root = Path(path or DEFAULT).expanduser().resolve()
    if not root.is_dir():
        raise DemoError(f'no example project at {root}')
    if not is_demo(root):
        raise DemoError(f'{root} was not made by `{shown_cmd()} demo`: left as it is')
    if what := busy(root):
        raise DemoError(f'{what} is up in {root}: end it first (there: `{shown_cmd()} stop`)')
    home = _home(root)
    worktrees = [Path(l[len('worktree '):]) for l in _git(root, 'worktree', 'list', '--porcelain').splitlines()
                 if l.startswith('worktree ')]
    own = []
    for w in (w.resolve() for w in worktrees):
        if w == root or not w.is_dir():
            continue
        if not (home and w.parent == home and RUN_WORKTREE.fullmatch(w.name)):  # a take's, or the person's: work
            raise DemoError(f'{w} is a worktree of {root} that is not a run\'s own: remove it first')
        own.append(w)
    if Path.cwd().is_relative_to(root):
        os.chdir(root.parent)  # Windows removes no folder that is a current one
    left = []
    try:
        for w in own:
            _rmtree(w)
        if home and home.is_dir() and home.name == root.name:  # another name: AGENT_RUNNER_HOME, shared
            if not {f.name for f in home.iterdir()} - {'tmp'}:  # tmp: the run's own (slots.py)
                _rmtree(home)
            else:
                left.append(home)
        for f in root.iterdir():  # the mark last: a removal that stopped half way can be run again
            if f.name != '.git':
                _rmtree(f)
        for f in (root / '.git').iterdir():
            if f.name != MARK:
                _rmtree(f)
        _rmtree(root)
    except OSError as e:
        raise DemoError(f'could not remove all of {root}: {e}') from None
    from agent_runner import home as runner_home
    if str(root) in runner_home.load_registry()['projects']:
        runner_home.remove_project(str(root))
    return root, left


def _rmtree(p: Path) -> None:
    """Remove a file or folder; a link is removed itself, never what it points to."""
    if p.is_symlink() or not p.is_dir():
        if os.name == 'nt' and not p.is_symlink():
            p.chmod(stat.S_IWRITE)
        p.unlink()
        return

    def again(func, name, _):  # git's objects are read-only, which Windows does not remove
        os.chmod(name, stat.S_IWRITE)
        func(name)
    shutil.rmtree(p, **({'onerror': again} if os.name == 'nt' else {}))


def main(argv: list[str]) -> int:
    """`agent-runner demo [DIR] [--remove]`."""
    ap = argparse.ArgumentParser(prog=f'{RUNNER} demo', description='Make the example project: a tiny app with a '
                                 'plan, to try agent-runner on. It is a git repo whose remote is on this machine, '
                                 'and no agent starts until you start a run.')
    ap.add_argument('dir', nargs='?', default=DEFAULT, metavar='DIR', help=f'its folder (default {DEFAULT})')
    ap.add_argument('--remove', action='store_true', help='take it away again; only a folder this command made')
    a = ap.parse_args(argv)
    try:
        if a.remove:
            root, left = remove(a.dir)
            print(f'removed the example project at {root}')
            for p in left:
                print(f'left as it is, not the example project\'s own: {p}')
            return 0
        root = make(a.dir)
    except DemoError as e:
        print(f'agent-runner demo: {e}', file=sys.stderr)
        return 1
    cmd = shown_cmd()
    here = plat.quote(str(root))
    print(f'''The example project is at {root}. Nothing has started, and nothing here goes online.

Next:
    cd {here}
    {cmd} plan                 its tasks
    {cmd} run --dry-run 3      what three agents would start; starts none
    {cmd}                      start the run: agents work, on your own Claude usage

Take it away:
    {cmd} demo --remove{'' if a.dir == DEFAULT else ' ' + here}''')
    return 0
