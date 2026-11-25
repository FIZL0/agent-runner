"""F448a: what a save of a 'file' group setting (commands, files, patterns, rules) is refused for on the Settings page: a
value that would stop the run or lose the plan. Only a save is checked; a value written by hand loads as it always did.

`problem` is asked by `config.setting_check`, `reset_problem` by the saves that take a key out, `locked` by the page."""
from __future__ import annotations

import copy
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from agent_runner import config as CF
from agent_runner import plat

PLAN_AT = (('plan', 'dir'), ('plan', 'repo'), ('run', 'home'))  # where the plan and the worktrees are
COMMANDS = {('run', k) for k in ('test', 'done_test', 'test_since', 'retest', 'build', 'docs_check', 'before_start', 'on_exit',
                                 'slot_clean', 'command')} | {('plan', 'brief_extra'), ('plan', 'outline')}
REGEXES = {('run', k) for k in ('failures', 'flaky', 'suspect', 'not_attempt')}
GLOBS = {('run', k) for k in ('untested', 'docs_files', 'findings', 'shared_files', 'joinable')}
FILLED = {('plan', 'brief_extra'): {'id': 'F1'}, ('plan', 'outline'): {'file': 'a.py'}}  # the placeholders of a command
JOIN = {k: 'x' for k in ('ours', 'base', 'theirs', 'union', 'out', 'file')}
PROMPT = ('tid', 'n', 'runner', 'branch', 'publish', 'others', 'earlier', 'rules', 'test', 'journal', 'extra', 'brief', 'followups')
PLAN_FILES = ('TODO.md', 'DONE.md', 'REFERENCE.md', 'HUMAN.md')
NOTES = 'The page you are on works in the log folder, so it can only be moved by hand while no run and no page is up'


def locked(root: Path, table: str, key: str) -> str:
    """Why this setting cannot be changed on the page now, in a sentence; '' when it can."""
    if (table, key) == ('run', 'notes'):
        return NOTES
    if (table, key) in PLAN_AT and _run_up(root):
        what = 'its worktrees are in this folder' if key == 'home' else 'the run and its sessions would work on two task lists'
        return f'It cannot be moved while the run is up, as {what}: stop the run, then set it here'
    return ''


def _run_up(root: Path) -> bool:
    c = CF.Config(root)
    f = CF.main_checkout(root) / c.run['notes'] / 'run.lock'
    if not f.is_file():
        return False
    if got := plat.lock(f):
        got.close()
        return False
    return True


def problem(root: Path, table: str, key: str, v) -> str:
    """Why `v`, of the right type, cannot be saved as `[table] key` here; '' when it can."""
    at = table, key
    try:
        if at == ('run', 'notes') or at in PLAN_AT:
            return _moved(root, table, key, v)
        return (_file(root, table, key, v) or _value(root, table, key, v)).replace('\n', ' ')
    except SystemExit as e:  # another setting the files hold is refused
        return str(e).removeprefix('agent-runner: ')
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as e:  # a path no system takes, ~nobody, a git that hangs
        return f'[{table}] {key} = {v!r}: {e}'


def reset_problem(root: Path, side: str, table: str, key: str) -> str:
    """Why `[table] key` cannot be taken out of `side`'s file; '' when it can."""
    at = table, key
    if at not in PLAN_AT and at not in (('run', 'notes'), ('models', 'providers')):
        return ''
    row = next(k for t in CF.settings_snapshot(root)['tables'] if t['table'] == table for k in t['keys'] if k['key'] == key)
    other = 'device' if side == 'project' else 'project'
    if not row[f'has_{side}'] or (side == 'project' and row['has_device']):  # nothing changes here
        return ''
    v = row[other] if row[f'has_{other}'] else row['default']
    if at == ('models', 'providers'):
        return CF.setting_check(root, table, key, v)
    try:
        return _moved(root, table, key, v, given=row[f'has_{other}'])
    except SystemExit as e:
        return str(e).removeprefix('agent-runner: ')
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as e:
        return f'[{table}] {key}: {e}'


# --- commands, patterns, lists ---------------------------------------------------------------------------------

def _value(root: Path, table: str, key: str, v) -> str:
    at, where = (table, key), f'[{table}] {key}'
    if at in COMMANDS:
        return _command(root, where, v, FILLED.get(at))
    if at in REGEXES:
        return _regex(where, v, key)
    if at in GLOBS:
        bad = next((x for x in v if not x.strip().lstrip('!')), None)
        return '' if bad is None else f'{where} has an empty entry: take it out'
    if at in (('run', 'links'), ('run', 'copies')):
        return next((why for x in v if (why := _inside(where, x))), '')
    if at == ('run', 'slot_env'):
        return next((why for x in v if (why := _env(where, x))), '')
    if at == ('run', 'pass_env'):
        bad = next((x for x in v if not re.fullmatch(r'[A-Za-z_]\w*', x)), None)
        return '' if bad is None else f'{where}: {bad!r} is not the name of a variable'
    if at == ('run', 'join'):
        for g, cmd in v.items():
            if not g.strip() or not isinstance(cmd, str) or not cmd.strip():
                return f'{where}: each entry is a file pattern and the command that joins it'
            if why := _command(root, f'{where}, {g}', cmd, JOIN):
                return why
        return ''
    if at == ('run', 'tools'):
        cmds = [(f'[run.tools.{n}] {k}', t[k]) for n, t in v.items() for k in ('check', 'start') if t.get(k)]
        cmds += [(f'[run.tools.{n}] button {b["label"]}', b['cmd']) for n, t in v.items() for b in t.get('buttons', [])]
        return next((why for w, cmd in cmds if (why := _syntax(w, cmd))), '')
    if at == ('run', 'checks'):
        return next((why for n, t in v.items() if (why := _syntax(f'[run.checks.{n}]', t['cmd']))), '')
    if at == ('plan', 'kinds'):
        bad = next((k for k, x in v.items() if not re.fullmatch(r'[A-Za-z]+', k) or not isinstance(x, str) or not x.strip()), None)
        return '' if bad is None else f'{where}: {bad!r} must be letters, with what they mean'
    if at == ('run', 'prompt_extra'):
        return _prompt(where, v)
    if at == ('git', 'push'):
        return _push(root, where, v)
    return ''


def _command(root: Path, where: str, cmd: str, fill: dict | None = None) -> str:
    if not cmd:
        return ''
    if not cmd.strip():
        return f'{where} is only spaces, which would run as a command that passes: make it empty'
    if fill:
        try:
            cmd = cmd.format_map(fill)
        except (KeyError, IndexError, ValueError, AttributeError) as e:
            return (f'{where}: its placeholders are {", ".join("{" + k + "}" for k in fill)}, and any other brace is written '
                    f'twice ({e!r})')
    return _syntax(where, cmd) or _program(root, where, cmd)


def _syntax(where: str, cmd: str) -> str:
    if plat.WINDOWS:
        return ''
    r = subprocess.run(['sh', '-n', '-c', cmd], capture_output=True, text=True, timeout=10)
    return f'{where} is not a command the shell can read: {" ".join(r.stderr.split())[-160:]}' if r.returncode else ''


def _program(root: Path, where: str, cmd: str) -> str:
    """The first word of `cmd`, when it is plain: a command, builtin or keyword here, or a file of the main checkout."""
    word = cmd.split()[0]
    if plat.WINDOWS or not re.fullmatch(r'[\w./+-]+', word):
        return ''
    r = subprocess.run(['sh', '-c', 'command -v "$0"', word], cwd=CF.main_checkout(root), capture_output=True, timeout=10)
    return f'{where}: there is no command {word} on this machine, so it would always fail' if r.returncode else ''


def _regex(where: str, v: str, key: str) -> str:
    if not v:
        return ''
    try:
        rx = re.compile(v.replace('{id}', 'F1') if key == 'not_attempt' else v, re.M)
    except (re.error, OverflowError, RecursionError) as e:
        return f'{where} is not a regular expression: {e}'
    if key in ('failures', 'flaky') and rx.groups > 1:
        return f'{where} has {rx.groups} groups: only one may name the test, so write the others as (?:…)'
    return f'{where} matches an empty line, so it would match everything' if rx.search('') else ''


def _inside(where: str, x: str) -> str:
    p = Path(x)
    if not x.strip() or p == Path('.'):
        return f'{where} has an empty entry: take it out'
    if p.is_absolute() or x.startswith('~') or '..' in p.parts or p.parts[0] == '.git':
        return f'{where}: {x!r} is not a path inside the project, so no worktree could have it'
    return ''


def _env(where: str, x: str) -> str:
    try:
        name, eq, _ = x.format(n=1, slots=1).partition('=')
    except (KeyError, IndexError, ValueError, AttributeError) as e:
        return f'{where}: {x!r} may say {{n}} and {{slots}}, and any other brace is written twice ({e!r})'
    if not eq or not re.fullmatch(r'[A-Za-z_]\w*', name):
        return f'{where}: {x!r} is not NAME=value'
    return f'{where}: {name} is set by the runner itself' if name.startswith('AGENT_RUNNER') else ''


def _prompt(where: str, text: str) -> str:
    from agent_runner.brief import _Keep
    try:
        text.format_map(_Keep({k: 1 if k == 'n' else 'x' for k in PROMPT}))
    except (KeyError, IndexError, ValueError, AttributeError) as e:
        return f'{where}: a brace that is no placeholder is written twice ({e!r})'
    return ''


def _push(root: Path, where: str, v) -> str:
    c = CF.Config(root)
    if v is False:
        return f'{where} cannot be off in PR mode: no pull request could be opened' if c.pr else ''
    if not v.strip():
        return f'{where} is empty: name a remote, or turn it off'
    if v.startswith('-') or subprocess.run(['git', 'remote', 'get-url', v], cwd=CF.main_checkout(root), capture_output=True).returncode:
        return f'{where}: this project has no remote {v}, so nothing would be pushed'
    return ''


# --- files -----------------------------------------------------------------------------------------------------

def _file(root: Path, table: str, key: str, v) -> str:
    at, where, main = (table, key), f'[{table}] {key}', CF.main_checkout(root)
    if at == ('plan', 'lookup'):
        return next((why for x in v if (why := _look(main, where, x))), '')
    if at not in (('run', 'rules'), ('run', 'prompt'), ('run', 'voice'), ('plan', 'glossary'), ('plan', 'journal')) or not v:
        return ''
    if not v.strip():
        return f'{where} is only spaces: make it empty'
    if at == ('plan', 'journal'):
        p = main / v
        if p.resolve() == main or main.resolve().is_relative_to(p.resolve()):
            return f'{where}: {v!r} is the whole project: name a folder in it'
        return _folder(where, p)
    p = main / (Path(v) if key in ('rules', 'prompt') else Path(v.strip()).expanduser())
    if p.is_dir():
        return f'{where}: {v} is a folder, not a file'
    if key in ('rules', 'prompt'):
        if not p.is_file():
            return f'{where}: there is no file {v} in the project'
        if key == 'prompt':
            return _prompt(f'{where}, {v}', p.read_text(encoding='utf-8'))
        return ''
    c = CF.Config(root)
    taken = [c.plan_dir / n for n in PLAN_FILES] + [f for f in (c.file, c.local) if f]
    if p.resolve() in [f.resolve() for f in taken]:
        return f'{where}: {v} is the plan or the settings, which it would write over'
    return _folder(where, p.parent)


def _look(main: Path, where: str, x: str) -> str:
    if not x.strip():
        return f'{where} has an empty entry: take it out'
    try:
        if any(ch in x for ch in '*?['):
            for _ in main.glob(x):
                break
        elif (main / x).is_dir():
            return f'{where}: {x} is a folder: name files, such as {x.rstrip("/")}/*.md'
    except (NotImplementedError, ValueError, IndexError) as e:
        return f'{where}: {x!r} is not a file pattern inside the project ({e})'
    return ''


def _folder(where: str, p: Path) -> str:
    """Why `p` cannot be a folder that is written to; '' when it is one or can be made."""
    if p.exists() and not p.is_dir():
        return f'{where}: {p} is a file, not a folder'
    at = p
    while not at.exists() and at != at.parent:
        at = at.parent
    if not at.is_dir():
        return f'{where}: {at} is a file, so {p} cannot be a folder'
    return '' if os.access(at, os.W_OK | os.X_OK) else f'{where}: {at} cannot be written to'


# --- where the plan and the worktrees are ----------------------------------------------------------------------

def _moved(root: Path, table: str, key: str, v, given: bool = True) -> str:
    """Why the plan or the worktrees cannot move to where `[table] key` = `v` puts them (not `given`: to the default)."""
    main, where = CF.main_checkout(root), f'[{table}] {key}'
    c = CF.Config(main)
    if v == c.raw[table][key] and given == (key in c.given.get(table, ())):
        return ''
    if why := locked(main, table, key):
        return f'{where}: {why}'
    if key != 'repo' and not v.strip():
        return f'{where} is empty: name a folder'
    if key == 'repo' and v and (v != v.strip() or not v.strip() or v.startswith('-')):
        return f'{where}: {v!r} is not a git address or path'
    new = _config(c, table, key, v, given)
    # the value's own folder: AGENT_RUNNER_HOME may say another on this machine
    if key == 'home' and (why := _home(main, where, main / Path(v.replace('{repo}', main.name)).expanduser())):
        return why
    if busy := _busy(main, c):
        return f'{where}: {", ".join(busy)} {"is" if len(busy) == 1 else "are"} still in a worktree: let the work finish first'
    if new.plan_dir.resolve() == c.plan_dir.resolve() and new.plan_repo == c.plan_repo:
        return ''
    return _plan(main, where, c, new)


def _config(c: CF.Config, table: str, key: str, v, given: bool) -> CF.Config:
    """`c` as it is once `[table] key` is `v`."""
    new = copy.copy(c)
    new.raw, new.given = copy.deepcopy(c.raw), copy.deepcopy(c.given)
    new.run = new.raw['run']
    new.raw[table][key] = v
    (new.given.setdefault(table, set()).add if given else new.given.setdefault(table, set()).discard)(key)
    if 'dir' not in new.given.get('plan', ()):
        new.raw['plan']['dir'] = str(new.home / 'plan') if new.raw['plan']['repo'] else CF.DEFAULTS['plan']['dir']
    return new


def _busy(main: Path, c: CF.Config) -> list[str]:
    from agent_runner import plan as P
    from agent_runner import working_branch as WB
    todo = P.open_ids(P.lines(str(c.todo))) if c.todo.is_file() else set()
    return sorted({b.removeprefix('task/') for b in WB._elsewhere(main) if b.startswith('task/')} & todo)


def _home(main: Path, where: str, home: Path) -> str:
    home = Path(os.path.normpath(home))
    if main.resolve().is_relative_to(home.resolve()):
        return f'{where}: {home} holds the project itself: name a folder of its own'
    if home.resolve().is_relative_to(main.resolve()) and _git(main, 'check-ignore', '-q', f'{home}/').returncode:
        return f'{where}: {home} is in the project, and git does not ignore it'
    for d in home.iterdir() if home.is_dir() else ():
        if not re.fullmatch(r's\d+|fix\d+|merge\d*', d.name):
            continue
        r = _git(d, 'rev-parse', '--path-format=absolute', '--git-common-dir') if d.is_dir() else None
        if r is None or r.returncode or Path(r.stdout.strip()).resolve() != (main / '.git').resolve():
            return f"{where}: {d} is not one of this project's worktrees, and the run would work in it"
    return _folder(where, home)


def _plan(main: Path, where: str, c: CF.Config, new: CF.Config) -> str:
    """The plan must be at its new place already, the same as now."""
    if c.pr:
        from agent_runner import pr
        if not new.plan_repo or not new.plan_external:
            return f'{where}: PR mode needs a plan repository, with the plan outside the project'
        if pr.slug_of(new.plan_repo) and pr.slug_of(new.plan_repo).lower() == (pr.slug(main, c.push_remote or '') or '').lower():
            return f'{where}: in PR mode the plan repository cannot be this project'
    if why := _folder(where, new.plan_dir):
        return why
    if new.plan_dir.resolve() == main.resolve() / '.git' or (main / '.git').resolve() in new.plan_dir.resolve().parents:
        return f'{where}: the plan cannot be in .git'
    if new.plan_repo and not new.plan_external:
        return f'{where}: a plan repository of its own has to be cloned outside the project'
    if c.plan_repo and (why := _unpushed(c)):
        return f'{where}: {why}'
    if not new.plan_repo:
        tracked = None if new.plan_external else main
        return _same(where, c, new.plan_dir, tracked)
    if (new.plan_dir / '.git').exists():
        url = _git(new.plan_dir, 'remote', 'get-url', 'origin').stdout.strip()
        if url != new.plan_repo:
            return f'{where}: {new.plan_dir} is a clone of {url or "nothing"}, not of {new.plan_repo}'
        return _same(where, c, new.plan_dir)
    if new.plan_dir.is_dir() and any(new.plan_dir.iterdir()):
        return f'{where}: {new.plan_dir} has files but is no git clone of {new.plan_repo}'
    tmp = Path(tempfile.mkdtemp(prefix='agent-runner-plan-'))
    try:
        r = subprocess.run(['git', 'clone', '-q', '--depth', '1', '--', new.plan_repo, str(tmp / 'plan')], capture_output=True,
                           text=True, timeout=60, stdin=subprocess.DEVNULL, env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'})
        if r.returncode:
            return f'{where}: {new.plan_repo} cannot be cloned: {" ".join(r.stderr.split())[-160:]}'
        return _same(where, c, tmp / 'plan', at=new.plan_repo)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _unpushed(c: CF.Config) -> str:
    if not (c.plan_dir / '.git').exists():
        return ''
    if _git(c.plan_dir, 'status', '--porcelain').stdout.strip() or _git(c.plan_dir, 'log', '-1', '--format=%h', '--branches',
                                                                         '--not', '--remotes').stdout.strip():
        return 'the plan has edits that are not pushed yet, which would be lost'
    return ''


def _same(where: str, c: CF.Config, there: Path, tracked: Path | None = None, at: str = '') -> str:
    """Why the plan in `there` is not the one of `c`; `tracked`: the checkout that must have it committed."""
    if not c.todo.is_file():
        return ''
    old = [c.plan_dir / n for n in PLAN_FILES] + sorted((c.plan_dir / 'tasks').rglob('*.md'))
    for f in old:
        if not f.is_file():
            continue
        rel = f.relative_to(c.plan_dir)
        try:
            same = (there / rel).read_text(encoding='utf-8') == f.read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError):
            same = False
        if not same:
            return (f'{where}: {at or there} does not have the same {rel.as_posix()} as the plan now, so tasks would be lost: '
                    f'copy {c.plan_dir} there first')
        if tracked and _git(tracked, 'cat-file', '-e', f'HEAD:{(there / rel).resolve().relative_to(tracked.resolve()).as_posix()}').returncode:
            return f'{where}: {there / rel} is not committed, so no worktree would have it: commit it first'
    return ''


def _git(cwd: Path, *a: str) -> subprocess.CompletedProcess:
    return subprocess.run(['git', *a], cwd=cwd, capture_output=True, text=True, timeout=30)
