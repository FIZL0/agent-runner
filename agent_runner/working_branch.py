"""F447b: the working branch ([git] master_branch), the branch tasks start from and finished work lands on: what a save
of it is checked for, and the switch to it.

A save moves nothing. `begin` notes it in <notes>/working-branch.json ({'was': the value in force, 'to': the one saved}),
and while that note is there every process goes on with `was` (`in_force`). The next start of the run switches the main
checkout (`at_start`), unless something holds it (`holds`): then it starts on the branch it was on and says why.

B833: another machine that pulls a save for everyone has no note; what git has of the pull says the same (`pulled`)."""
from __future__ import annotations

import json
import os
import re
import tempfile
import tomllib
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
    if not d or d['to'] != value:
        d = pulled(root, value)
    return d['was'] if d else value


SAVE = re.compile(r'settings: .*\[git\] master_branch\b')  # the commit of a save for everyone
PULL = re.compile(r'(pull|merge|rebase|commit \(merge\))(?!.*\((pick|reword|edit|squash|fixup|continue)\))')


def pulled(root: Path, value) -> dict:
    """{'was', 'to'}, as the note has them, when `value` is a save for everyone that another machine made and a pull
    brought here while the branch before it was out, as it still is; {} otherwise (one changed by hand, say)."""
    if not isinstance(value, str):
        return {}
    main = CF.main_checkout(root)
    cur = _out(main, 'branch', '--show-current')
    if not cur or value == cur:
        return {}
    try:
        f, local = CF.config_file(main), CF.local_file(main)
        mine = (CF._load(local) if local else {}).get('git', {})
        git_ = {**(CF._load(f) if f else {}).get('git', {}), **mine}
    except (OSError, ValueError, TypeError, AttributeError):
        return {}
    if 'master_branch' in mine or f is None or not (rel := _rel(main, f)):
        return {}
    from agent_runner.gitops import found_name
    push = git_.get('push')
    auto = found_name(main, push if isinstance(push, str) else 'origin', None) or cur
    if not value and auto == cur:
        return {}
    log = [l.split('\0') for l in _out(main, 'log', '-g', '-n', '5000', '--format=%H%x00%gs', 'HEAD', '--').splitlines()]
    vals = _values(main, [e[0] for e in log], rel)
    n = next((i for i, v in enumerate(vals) if v != value), 0)  # log[n - 1] is the move that brought the value
    if not n or not PULL.match(log[n - 1][1]):
        return {}
    to = value or auto
    if any(e[1].startswith(f'checkout: moving from {to} to ') for e in log[:n]):
        return {}  # it was switched to, and left by hand
    was = next((v for v in vals[n:] if v == cur or v == '' and auto == cur), None)
    if was is None:  # the branch that is out is not one the setting named
        return {}
    for l in _out(main, 'log', '--format=%H%x00%s', f'{log[n][0]}..{log[n - 1][0]}', '--', rel).splitlines():
        sha, subject = l.split('\0', 1)
        now, *old = _values(main, [sha, f'{sha}^'], rel)
        if now == value and old != [value]:
            there = _out(main, 'for-each-ref', '--contains', sha, '--format=%(refname)', 'refs/remotes/').split()
            return {'was': was, 'to': value} if SAVE.match(subject) and any(r.endswith(f'/{cur}') for r in there) else {}
    return {}


def _values(root: Path, revs: list[str], rel: str) -> list:
    """The working branch that the settings file has in each of `revs`, '' where it sets none, None when unreadable."""
    def value(blob: str):
        try:
            raw = tomllib.loads(_git(root, 'cat-file', 'blob', blob).stdout)
            raw = raw['agent-runner'] if isinstance(raw.get('agent-runner'), dict) else raw
            return raw.get('git', {}).get('master_branch', '')
        except (ValueError, AttributeError):
            return None
    out, seen = [], {}
    for l in _out(root, 'cat-file', '--batch-check=%(objectname)', input=''.join(f'{r}:{rel}\n' for r in revs)).splitlines():
        if l not in seen:
            seen[l] = '' if l.endswith(' missing') else value(l)
        out.append(seen[l])
    return out


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
    to = saved(root)
    d = _read(_file(root, CF.Config(root).run['notes']))
    if not d or d['to'] != to:
        d = pulled(root, to)
    if not d:
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
    return bool(_read(_file(root, CF.Config(root).run['notes'])) or pending(root))


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
    v, note = saved(root), _read(f)
    ours = bool(note) and note['to'] == v and not note.get('pulled')  # saved on this machine
    made = not why and not ours and _fetched(root, to)
    if not why and (bad := problem(root, v)):
        why = [bad]
    newer = None if why or ours else _newer(root, to)
    if not why and (bad := _switch(root, to, newer is None)):
        why = [bad]
    if why:
        if made:
            _git(root, 'branch', '-q', '-D', to, '--')
        S.log(f'working branch: still {now}, not {to}: {"; ".join(why)}. It is tried again at the next start of the run')
        return False
    f.unlink(missing_ok=True)
    S.log(f'working branch: {to} (it was {now})')
    if newer is not None:
        from agent_runner.whole_write import write_whole
        f.parent.mkdir(parents=True, exist_ok=True)
        write_whole(f, json.dumps({'was': to, 'to': newer, 'pulled': True}).encode())
        at_start(root)
    return True


def forget() -> None:
    """The settings read before the switch are of the other branch."""
    CF._cfg.cache_clear()


def _fetched(root: Path, to: str) -> bool:
    """B833: a machine that never had the branch makes it from the remote's, and one behind it takes its commits, the
    setting's own among them. Was it made?"""
    ref, here = f'refs/remotes/{CF.Config(root).push_remote or "origin"}/{to}', f'refs/heads/{to}'
    if not _git(root, 'show-ref', '--verify', '--quiet', here).returncode:
        if to not in _elsewhere(root) and to != _out(root, 'branch', '--show-current') \
                and not _git(root, 'merge-base', '--is-ancestor', here, ref).returncode:
            _git(root, 'update-ref', here, _out(root, 'rev-parse', ref), _out(root, 'rev-parse', here))
        return False
    return not _git(root, 'branch', '-q', '--track', to, ref).returncode


def _newer(root: Path, to: str):
    """B833: the value `to`'s own settings file has when a later save there, after the one that named `to`, changed
    it; None otherwise. That save goes before the one pulled on the old branch."""
    f = CF.config_file(root)
    rel = _rel(root, f) if f else ''
    if not rel or _row(root)['has_device'] or not _has(root, f'refs/heads/{to}', rel):
        return None
    v, *old = _values(root, _out(root, 'log', '-n', '500', '--format=%H', f'refs/heads/{to}', '--', rel).split(), rel)
    return v if isinstance(v, str) and v != to and to in old else None


def _switch(root: Path, to: str, carry: bool = True) -> str:
    """Give `to` the setting (`carry`), then check it out in the main checkout: why not, or ''."""
    if carry and (why := _carry(root, to)):
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
