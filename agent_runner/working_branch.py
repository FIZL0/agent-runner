"""F447b: the working branch ([git] master_branch), the branch tasks start from and finished work lands on: what a save
of it is checked for, and the switch to it.

A save moves nothing. `begin` notes it in <notes>/working-branch.json ({'was': the value in force, 'to': the one saved}),
and while that note is there every process goes on with `was` (`in_force`). The next start of the run switches the main
checkout (`at_start`), unless something holds it (`holds`): then it starts on the branch it was on and says why."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from agent_runner import config as CF

NOTE = 'working-branch.json'
RUNNERS = ('task/', 'wip/', 'pr/', 'leftover/')  # branches the runner makes and removes
UNDER_WAY = ('MERGE_HEAD', 'rebase-merge', 'rebase-apply', 'CHERRY_PICK_HEAD', 'REVERT_HEAD')


def _git(root: Path, *a: str, **kw):
    from agent_runner.gitops import git
    return git(*a, cwd=root, **kw)


def _out(root: Path, *a: str, **kw) -> str:
    return _git(root, *a, **kw).stdout.strip()


# --- the saved change that waits for a start -------------------------------------------------------------------

def _file(root: Path, notes: str) -> Path:
    return CF.main_checkout(root) / notes / NOTE


def _read(f: Path) -> dict:
    try:
        d = json.loads(f.read_text(encoding='utf-8'))
        return d if isinstance(d.get('was'), str) and isinstance(d.get('to'), str) else {}
    except (OSError, ValueError, AttributeError):
        return {}


def in_force(root: Path, notes: str, value):
    """The [git] master_branch a config reads: `value` (the files'), or the one before it while its switch waits."""
    d = _read(_file(root, notes))
    return d['was'] if d and d['to'] == value else value


def saved(root: Path, side: str = '', value=None, unset: bool = False) -> str:
    """The value the settings files hold, this device's before everyone's; with `side`, as it is after that save."""
    vals = {}
    row = _row(root)
    for s in ('device', 'project'):
        if row[f'has_{s}']:
            vals[s] = row[s]
    if side:
        vals.pop(side, None)
        if not unset:
            vals[side] = value
    v = vals.get('device', vals.get('project', ''))
    return v if isinstance(v, str) else ''


def _row(root: Path) -> dict:
    return next(k for t in CF.settings_snapshot(root)['tables'] if t['table'] == 'git' for k in t['keys']
                if k['key'] == 'master_branch')


def branch_of(root: Path, value: str) -> str:
    """The branch a value names: itself, or for '' the one found by itself."""
    from agent_runner.gitops import found_name
    return value or found_name(root, CF.Config(root).push_remote or 'origin', None) or _out(root, 'branch', '--show-current') or 'main'


def _now(root: Path) -> str:
    """The value work goes by now: the files', else the run's own (it keeps the one it started with), else the branch
    that is out, as a value naming another branch starts nothing."""
    from agent_runner import state as S
    cur = _out(root, 'branch', '--show-current')
    mine = [CF.Config(root).raw['git']['master_branch']]
    if S.ROOT == root:
        mine.append(S.C.raw['git']['master_branch'])
    return next((v for v in mine if isinstance(v, str) and v in ('', cur)), cur)


def pending(root: Path) -> dict:
    """{'now', 'next'}: the branches a switch that waits goes from and to; {} when none waits."""
    d = _read(_file(root, CF.Config(root).run['notes']))
    if not d or d['to'] != saved(root):
        return {}
    return {'now': branch_of(root, d['was']), 'next': branch_of(root, d['to'])}


# --- a save ----------------------------------------------------------------------------------------------------

def problem(root: Path, value) -> str:
    """Why `value` cannot be the working branch here; '' when it can."""
    if not isinstance(value, str):
        return f'the working branch must be a branch name, not {value!r}'
    if value != value.strip():
        return f'the working branch must not have spaces around it: {value!r}'
    if value and (value.startswith('-') or _git(root, 'check-ref-format', f'refs/heads/{value}').returncode):
        return f'{value!r} is not a valid branch name, so it cannot be the working branch'
    name = branch_of(root, value)
    if name.startswith(RUNNERS):
        return f"{name} is one of the runner's own branches, so it cannot be the working branch"
    if _git(root, 'show-ref', '--verify', '--quiet', f'refs/heads/{name}').returncode:
        return (f'there is no local branch {name}, so it cannot be the working branch' if value else
                f'the working branch found by itself is {name}, and there is no local branch of that name')
    c, now = CF.Config(root), branch_of(root, _now(root))
    if name == now and name == _out(root, 'branch', '--show-current'):
        return ''
    if at := _elsewhere(root).get(name):
        return f'{name} is checked out in {at}, so it cannot be the working branch: leave it there first'
    from agent_runner import plansync, pr
    need = [('the settings', CF.config_file(root)), ('the task list', None if c.plan_external else c.todo)]
    for what, f in need:
        rel = _rel(root, f) if f else ''
        if rel and _has(root, 'HEAD', rel) and not _has(root, f'refs/heads/{name}', rel):
            return f'{name} has no {rel} ({what}), so the run could not work on it'
    if c.pr and (why := pr.branch_problem(c, root, name)):
        return f'PR mode could not go on with {name}: {why}'
    return ''


def _rel(root: Path, f: Path) -> str:
    try:
        return f.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return ''


def _has(root: Path, ref: str, rel: str) -> bool:
    return not _git(root, 'cat-file', '-e', f'{ref}:{rel}').returncode


def _elsewhere(root: Path) -> dict[str, str]:
    """{branch: the worktree, not the main checkout, that has it out}."""
    out, at = {}, ''
    for l in _git(root, 'worktree', 'list', '--porcelain').stdout.splitlines():
        if l.startswith('worktree '):
            at = l.removeprefix('worktree ')
        elif l.startswith('branch refs/heads/') and Path(at).resolve() != root.resolve():
            out[l.removeprefix('branch refs/heads/')] = at
    return out


def begin(root: Path, side: str, value=None, unset: bool = False):
    """A save of the setting is about to be written to `side`'s file: note the switch it asks for, so no process goes by
    the new value before the start. ValueError refuses it. Call what it returns when the write failed."""
    from agent_runner.whole_write import write_whole
    to = saved(root, side, value, unset)
    if to != saved(root) and (why := problem(root, to)):  # a reset too: what is under it may be gone
        raise ValueError(why)
    was, f = _now(root), _file(root, CF.Config(root).run['notes'])
    old = f.read_bytes() if f.is_file() else None

    def put(data: bytes | None) -> None:
        if data is None:
            return f.unlink(missing_ok=True)
        f.parent.mkdir(parents=True, exist_ok=True)
        write_whole(f, data)
    there = branch_of(root, to) == branch_of(root, was) == _out(root, 'branch', '--show-current')
    put(None if to == was or there else json.dumps({'was': was, 'to': to}).encode())
    return lambda: put(old)


def said(root: Path) -> str:
    """What a save says of the switch that waits; '' for none."""
    d = pending(root)
    if not d:
        return ''
    what = (f'{d["next"]} is checked out in the main checkout' if d['next'] != d['now'] else 'the working branch changes')
    held = holds(root, d['now'])
    return (f'the working branch stays {d["now"]} until the run starts again: then {what}, if it has no uncommitted '
            'edits and no task runs or waits to merge' + (f' (now: {"; ".join(held)})' if held else ''))


# --- the switch ------------------------------------------------------------------------------------------------

def holds(root: Path, branch: str) -> list[str]:
    """What keeps the main checkout from moving off `branch` now, in words; [] when nothing does."""
    from agent_runner import plat, pr, sched, slots, state as S
    out = []
    if n := len(S.edited()):
        out.append(f'{n} uncommitted {"edit" if n == 1 else "edits"} in the main checkout')
    for what in UNDER_WAY:
        if os.path.exists(_out(root, 'rev-parse', '--path-format=absolute', '--git-path', what)):
            out.append('a merge or rebase is under way in the main checkout')
            break
    if not _out(root, 'branch', '--show-current'):
        out.append('no branch is checked out in the main checkout')
    todo = sched.open_tasks(branch) | sched.blocked_tasks(branch)
    here = {b.removeprefix('task/') for b in _elsewhere(root) if b.startswith('task/')} & todo
    run = here | set(sched.taken()) | {q[0] for q in S.queued().values()}
    if not run and any(plat.alive(pid) for _, pid in slots.MUX.panes().values()):
        out.append('a session runs in a slot')
    if run:
        out.append(_tasks(run, 'is being worked on', 'are being worked on'))
    if wait := (set(sched.ahead(branch)) & todo) - run:
        out.append(_tasks(wait, 'waits to merge', 'wait to merge'))
    if prs := pr.read():
        out.append(_tasks({x['key'] for x in prs}, 'has a pull request', 'have pull requests'))
    return out


def _tasks(ids: set[str], one: str, many: str) -> str:
    return f'{", ".join(sorted(ids))} {one if len(ids) == 1 else many}'


def waits(root: Path) -> bool:
    """Is there a saved change the run's start has to look at?"""
    return bool(_read(_file(root, CF.Config(root).run['notes'])))


def at_start(root: Path) -> bool:
    """The run starts, and holds run.lock: switch to the working branch that was saved. Was anything changed (the
    settings have to be read again)? A switch that cannot be made is said, and the run starts on the branch it has."""
    from agent_runner import state as S
    f = _file(root, CF.Config(root).run['notes'])
    d = pending(root)
    if not d:  # taken back, or the files were changed by hand since
        f.unlink(missing_ok=True)
        return False
    now, to = d['now'], d['next']
    why = holds(root, now)
    if not why and (bad := problem(root, saved(root))):
        why = [bad]
    if not why and (bad := _switch(root, to)):
        why = [bad]
    if why:
        S.log(f'working branch: still {now}, not {to}: {"; ".join(why)}. It is tried again at the next start of the run')
        return False
    f.unlink(missing_ok=True)
    S.log(f'working branch: {to} (it was {now})')
    return True


def forget() -> None:
    """The settings read before the switch are of the other branch."""
    CF._cfg.cache_clear()


def _switch(root: Path, to: str) -> str:
    """Give `to` the setting, then check it out in the main checkout: why not, or ''."""
    if why := _carry(root, to):
        return why
    if _out(root, 'branch', '--show-current') == to:
        return ''
    r = _git(root, 'checkout', '-q', to, '--')
    return f'git could not check out {to}: {r.stderr.strip()[-200:]}' if r.returncode else ''


def _carry(root: Path, to: str) -> str:
    """Commit the setting to `to`'s own settings file, before it is checked out: without it that branch would say
    another one. A value of this device's file is there on every branch."""
    row, f = _row(root), CF.config_file(root)
    if row['has_device'] or f is None or not (rel := _rel(root, f)) or _out(root, 'branch', '--show-current') == to:
        return ''
    ref = f'refs/heads/{to}'
    if not _has(root, ref, rel):  # git ignores it here: one file for every branch
        return ''
    from agent_runner.gitops import git
    import subprocess
    old = subprocess.run(['git', 'show', f'{ref}:{rel}'], cwd=root, capture_output=True).stdout
    try:
        new = CF.setting_edit(old, 'git', 'master_branch', row.get('project', ''), not row['has_project'], f.name)
    except ValueError as e:
        return f'{f.name} on {to} could not take the setting: {e}'
    if new == old:
        return ''
    if CF.Config(root).pr:  # as `commit_file`: a commit there would miss its pull request
        return f'PR mode is on, so {f.name} on {to} has to get [git] master_branch in a pull request'
    tip = _out(root, 'rev-parse', ref)
    mode = _out(root, 'ls-tree', ref, '--', rel).split(' ')[0] or '100644'
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / 'new').write_bytes(new)
        env = {**os.environ, 'GIT_INDEX_FILE': str(Path(tmp) / 'index')}
        blob = _out(root, 'hash-object', '-w', '--no-filters', str(Path(tmp) / 'new'))
        for a in (('read-tree', tip), ('update-index', '--cacheinfo', f'{mode},{blob},{rel}')):
            if (r := git(*a, cwd=root, env=env)).returncode:
                return f'{f.name} on {to} could not take the setting: {r.stderr.strip()[-200:]}'
        tree = git('write-tree', cwd=root, env=env).stdout.strip()
    r = _git(root, 'commit-tree', tree, '-p', tip, '-m', f'settings: the working branch is {to}')
    if not r.returncode:
        r = _git(root, 'update-ref', ref, r.stdout.strip(), tip)
    return f'{f.name} on {to} could not be committed: {r.stderr.strip()[-200:]}' if r.returncode else ''


# --- the Settings page -----------------------------------------------------------------------------------------

def picks(root: Path, row: dict) -> list[dict]:
    """The picker of the setting (`row`: its settings row): found by itself with the branch that is now, the local
    branches, then each value kept in a settings file that is none of them. 'bad': what is wrong with it."""
    away = _elsewhere(root)
    names = [b for b in _git(root, 'for-each-ref', '--format=%(refname)', 'refs/heads/').stdout.split()]
    names = [b for b in (x.removeprefix('refs/heads/') for x in names) if not b.startswith(RUNNERS)]
    auto = branch_of(root, '')
    out = [{'value': '', 'branch': auto, 'auto': True, 'bad': '' if auto in names else f'there is no local branch {auto}'}]
    out += [{'value': b, 'branch': b, 'auto': False, 'bad': f'checked out in {away[b]}' if b in away else ''} for b in names]
    for v in dict.fromkeys((row['value'], row.get('device'), row.get('project'))):
        if isinstance(v, str) and v and v not in names:
            out.append({'value': v, 'branch': v, 'auto': False, 'bad': problem(root, v) or 'not a branch to pick'})
    return out


def show(root: Path, row: dict) -> dict:
    """What the Settings page has of the setting: {'picks', 'now': the branch that is now, 'next' and 'held' (why it
    waits) while a switch does}."""
    d = pending(root)
    now = d['now'] if d else branch_of(root, _now(root))
    return {'picks': picks(root, row), 'now': now,
            **({'next': d['next'], 'held': holds(root, now)} if d else {})}
