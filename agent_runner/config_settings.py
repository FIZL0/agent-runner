"""The settings the run app's Settings view reads and writes: types, checks, and edits of the toml files (F97).
Split out of config.py (C61); config re-exports every name, so `config.setting_edit` still works."""
from __future__ import annotations

import os
import tomllib
from pathlib import Path

from agent_runner import config as _c
from agent_runner.config import *  # noqa: F401,F403
from agent_runner.config import (Config, LOCAL, DEFAULTS, _cfg, _load, _typed, _toml_value, local_file, ensure_local,
                                 main_checkout, git_path, move_keys, old_sessions)

# --- F97: the settings, read and written by the run app's Settings view ---------------------------------------

# keys whose value is one of a few: the choices, the default's type aside
SETTING_CHOICES: dict[tuple[str, str], tuple] = {
    ('plan', 'journal_layout'): ('dated', 'id'),
    ('run', 'engine'): ('terminal', 'stream'),
    ('run', 'remote'): ('auto', True, False),
    ('run', 'remote_slots'): ('open', 'always'),
    ('run', 'grill'): ('ask', 'big', 'off'),
    ('run', 'web_open'): ('everywhere', 'here'),  # F454a
    ('run', 'voice_learn'): ('ask', 'off'),
    ('run', 'issues_trust'): ('skeptical', 'trust', 'contributors', 'members', 'approve'),
    ('run', 'needs_order'): ('oldest', 'newest', 'plan'),
    ('git', 'land_edited'): ('wait', 'wip'),
}
# keys that take more than their default's type: the other types ('off': false, 'bool', 'number', 'text', 'list',
# 'table')
SETTING_ALSO: dict[tuple[str, str], tuple[str, ...]] = {
    ('plan', 'glossary'): ('off',), ('run', 'control_idle'): ('off',), ('run', 'control_ask'): ('off',), ('run', 'ci_watch'): ('off', 'list'),
    ('run', 'issues_watch'): ('list',), ('run', 'issues_trust'): ('list',), ('run', 'auto_release'): ('table',), ('run', 'auto_audit'): ('table',), ('run', 'audit_tokens'): ('float',), ('run', 'proc_max_gb'): ('number',),
    ('git', 'push'): ('off',), ('ui', 'chat_quiet'): ('off',),
    ('models', 'docs'): ('off',), ('run', 'task_tokens'): ('float',), ('run', 'task_usd'): ('float',),
    ('run', 'weekly_max'): ('float',), ('run', 'session_max'): ('float',),
}
SETTING_DURATIONS = {('run', 'control_idle'), ('run', 'control_ask'), ('ui', 'chat_quiet')}
# F202a: what a run that is up cannot change: the run page's server, and where its files, plan and worktrees are and
# which branch it merges into (its lock, state and sessions are there already), the no-push policy: the sessions that
# are up would not be under it, and PR mode, which the start checks. Every other key applies live.
SETTING_NEXT = {('run', 'web'), ('run', 'web_port'), ('run', 'web_https'), ('run', 'web_open'), ('run', 'home'), ('run', 'notes'),
                ('plan', 'dir'), ('plan', 'repo'), ('git', 'master_branch'), ('git', 'no_push'), ('git', 'pr')}


def setting_type(table: str, key: str) -> str:
    """The control a setting gets: 'choice', 'switch', 'number', 'list', 'table' or 'text'."""
    if setting_choices(table, key):
        return 'choice'
    v = DEFAULTS[table][key]
    if SETTING_ALSO.get((table, key)) == ('table',):
        return 'table'
    return ('switch' if isinstance(v, bool) and not SETTING_ALSO.get((table, key)) else
            'number' if isinstance(v, (int, float)) and not isinstance(v, bool) else
            'list' if isinstance(v, list) else 'table' if isinstance(v, dict) else 'text')


def setting_choices(table: str, key: str) -> tuple:
    if (table, key) == ('ui', 'theme'):
        from agent_runner.theme import NAMES
        return tuple(NAMES)
    return SETTING_CHOICES.get((table, key), ())


def setting_problem(table: str, key: str, v) -> str:
    """Why `v` cannot be `[table] key` ('' when it can): its type, its choices, its range."""
    if table not in DEFAULTS or key not in DEFAULTS[table]:
        return f'[{table}] {key} is not a setting'
    where, d, also = f'[{table}] {key}', DEFAULTS[table][key], SETTING_ALSO.get((table, key), ())
    if choices := setting_choices(table, key):
        ok = any(v == c and isinstance(v, bool) == isinstance(c, bool) for c in choices)
        return '' if ok else f'{where} must be one of {", ".join(_toml_value(c) for c in choices)}, not {v!r}'
    num = isinstance(v, (int, float)) and not isinstance(v, bool)
    ok = (isinstance(v, bool) if isinstance(d, bool) else
          isinstance(v, int) and not isinstance(v, bool) if isinstance(d, int) else
          isinstance(v, str) if isinstance(d, str) else
          isinstance(v, list) and all(isinstance(x, str) for x in v) if isinstance(d, list) else isinstance(v, dict))
    ok = ok or (v is False and 'off' in also) or (num and ('number' in also or 'float' in also)) \
        or (isinstance(v, str) and 'text' in also) or (isinstance(v, dict) and 'table' in also) \
        or (isinstance(v, list) and 'list' in also and all(isinstance(x, str) for x in v))
    if not ok:
        kind = {'switch': 'true or false', 'number': 'a whole number', 'list': 'a list of words',
                'table': 'a table'}.get(setting_type(table, key), 'text')
        return f'{where} must be {kind}{" or false" if "off" in also else ""}, not {v!r}'
    if (table, key) == ('run', 'tools') and (problem := tools_problem(v)):  # F168
        return problem
    if (table, key) == ('run', 'checks') and (problem := checks_problem(v)):  # F427a
        return problem
    if (table, key) == ('ui', 'trusted_networks'):  # F136
        from agent_runner.trust import network_problem
        if problem := next((p for x in v if (p := network_problem(x))), ''):
            return f'{where}: {problem}'
    if (table, key) == ('run', 'agent') and (problem := agent_value_problem(v)):  # B764a
        return problem
    if num and v < 0:
        return f'{where} cannot be below 0, not {v!r}'
    if (table, key) == ('run', 'slots') and v < 1:
        return f'{where} must be at least 1, not {v!r}'
    if (table, key) == ('run', 'web_port') and not 0 < v < 65536:
        return f'{where} must be a port number, not {v!r}'
    if (table, key) in SETTING_DURATIONS and isinstance(v, str):
        import re
        if not re.fullmatch(r'\s*\d+(?:\.\d+)?\s*[smhd]?\s*', v):
            return f'{where} must be a time like "6h" or "30m", or false, not {v!r}'
    return ''


def agent_value_problem(v: str) -> str:
    """B764a: why `v` cannot be `[run] agent` on any machine ('' when it can): nothing, or a backend that is gone."""
    if not v.strip():
        return '[run] agent is empty: name the Claude Code program, "claude" or a wrapper around it'
    stem = Path(v.strip().replace('\\', '/')).stem.lower()
    if stem == 'copilot':
        return (f'[run] agent = {v!r}: GitHub Copilot CLI support was removed. Name the model in [models] as '
                '"<provider>:<model>", e.g. [models] code = "copilot:<model>"')
    return f'[run] agent = {v!r}: {PI_GONE}' if stem == 'pi' else ''


def agent_missing(root: Path, v: str) -> str:
    """B764a: why this machine cannot start `[run] agent` = `v` ('' when it can): it is neither on PATH nor a file (a
    relative path is from the main checkout)."""
    if Path(v).name == v and shutil.which(v):  # the usual one, with no git call: every snapshot asks (B764b)
        return ''
    at = Path(v) if Path(v).is_absolute() else main_checkout(root) / v
    if at.is_file() or shutil.which(str(at)):
        return ''
    return f'[run] agent = {v!r}: no such command on PATH on this machine, and no such file'


def agent_problem(root: Path, v, used: bool = True) -> str:
    """B764b: `Config.agent_problem` of the value `v`. Short, as a status line: the fix must not be cut off. F406h: not
    `used` (no role runs on it, claude_use.uses), a missing program is no problem."""
    if isinstance(v, str) and v.strip() and agent_value_problem(v):
        return f'[run] agent = {v!r} was removed: set it to "claude"; other models go in [models] as "<provider>:<model>"'
    if problem := setting_problem('run', 'agent', v):
        return problem if isinstance(v, str) else f'{problem}: set it to "claude"'
    if used and agent_missing(root, v):
        return f'[run] agent = {v!r} is not on this machine: install it, or set it to the path of Claude Code'
    return ''


def tools_problem(v) -> str:
    """F168: why `v` cannot be `[run] tools` ('' when it can): {name: {check, label, connect, description,
    page, start}}, all text, and buttons (F428c), a list of {label, cmd, confirm}."""
    import re
    from agent_runner import devices, tool_buttons
    if not isinstance(v, dict):
        return f'[run] tools is a table of shared tools ([run.tools.iphone15]), not {v!r}'
    for name, t in v.items():
        where = f'[run.tools.{name}]'
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', str(name)):
            return f'{where}: a name is letters, digits, - and _ (iphone15)'
        if name == 'memory':
            return f'{where}: memory is built in (`run wait-for memory`); name the tool otherwise'
        if not isinstance(t, dict) or not isinstance(t.get('check'), str) or not t['check'].strip():
            return f'{where} needs check, the command that says whether it is free'
        if bad := [k for k in t if k not in ('check', 'label', 'connect', 'description', 'page', 'start', 'buttons')]:
            return f'{where}: {bad[0]} is not one of check, label, connect, description, page, start, buttons'
        if bad := [k for k, x in t.items() if k != 'buttons' and not isinstance(x, str)]:
            return f'{where}: {bad[0]} must be text'
        try:
            devices.tool_fields(t)  # F428a
            tool_buttons.checked(t.get('buttons', []))
        except devices.Refused as e:
            return f'{where}: {e}'
    return ''


def checks_problem(v) -> str:
    """F427a: why `v` cannot be `[run] checks` ('' when it can): {name: {cmd, label}}, all text."""
    import re
    if not isinstance(v, dict):
        return f'[run] checks is a table of checks ([run.checks.vm]), not {v!r}'
    for name, t in v.items():
        where = f'[run.checks.{name}]'
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', str(name)):
            return f'{where}: a name is letters, digits, - and _ (vm)'
        if not isinstance(t, dict) or not isinstance(t.get('cmd'), str) or not t['cmd'].strip():
            return f'{where} needs cmd, the command that says whether it passes'
        if bad := [k for k in t if k not in ('cmd', 'label')]:
            return f'{where}: {bad[0]} is not one of cmd, label'
        if bad := [k for k, x in t.items() if not isinstance(x, str)]:
            return f'{where}: {bad[0]} must be text'
    return ''


def toml_value(v) -> str:
    """`v` as TOML source for one line (strings as written, not \\u escapes)."""
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, list):
        return '[' + ', '.join(toml_value(x) for x in v) + ']'
    if isinstance(v, dict):
        return '{ ' + ', '.join(f'{json.dumps(str(k), ensure_ascii=False)} = {toml_value(x)}'
                                for k, x in v.items()) + ' }' if v else '{}'
    return _toml_value(v)


def _toml_span(lines: list[str], i: int) -> int:
    """How many of `lines` the key at `i` takes (a list or string over several lines), 0 when it never parses."""
    for n in range(1, len(lines) - i + 1):
        try:
            tomllib.loads('\n'.join(lines[i:i + n]))
            return n
        except tomllib.TOMLDecodeError:
            continue
    return 0


def _toml_comment(line: str) -> str:
    """The comment that ends a `key = value` (with the spaces before it), '' for none."""
    at = line.find('#')
    while at >= 0:
        head = line[:at]
        try:
            tomllib.loads(head)
            return head[len(head.rstrip()):] + line[at:]
        except tomllib.TOMLDecodeError:
            at = line.find('#', at + 1)
    return ''


def _toml_inner(lines: list[str]) -> list[str]:
    """The comments inside a value over several `lines` (not the one that ends it), as lines of their own."""
    out = []
    want = tomllib.loads('\n'.join(lines))
    for i, l in enumerate(lines[:-1]):
        at = l.find('#')
        while at >= 0:
            try:
                if tomllib.loads('\n'.join([*lines[:i], l[:at], *lines[i + 1:]])) == want:
                    out.append(l[at:].strip())
                    break
            except tomllib.TOMLDecodeError:
                pass
            at = l.find('#', at + 1)
    return out


def toml_edit(text: str, table: str, key: str, value=None, unset: bool = False) -> str:
    """F97: `text` (a settings file) with `[table] key` set to `value` (`unset`: taken out), every other line
    and comment as it was; a table written as [table.key] sections keeps them (F448a). ValueError when it cannot be
    done on its own line (a dotted key, an inline table); the result is read back, and only that key may differ."""
    import re
    from agent_runner import toml_sections
    before = tomllib.loads(text)
    wrapped = isinstance(before.get('agent-runner'), dict)
    name = f'agent-runner.{table}' if wrapped else table
    lines = text.split('\n')
    # real headers and keys only: not a look-alike inside a multi-line string, which parses as no prefix
    head = re.compile(r'\s*\[\s*' + r'\s*\.\s*'.join(f'["\']?{re.escape(p)}["\']?' for p in name.split('.'))
                      + r'\s*\]\s*(#.*)?$')
    any_head = re.compile(r'\s*\[')
    key_re = re.compile(rf'\s*["\']?{re.escape(key)}["\']?\s*=')
    i, at, end, where, last = 0, None, None, None, 0  # last: the line after the section's last key
    while i < len(lines):
        l = lines[i]
        if not l.strip() or l.lstrip().startswith('#'):
            i += 1
            continue
        if any_head.match(l):
            if at is not None and end is None:
                end = i
            if head.match(l):
                at, end, last = i, None, i + 1
            i += 1
            continue
        n = _toml_span(lines, i) or 1
        if at is not None and end is None and key_re.match(l):
            where = (i, n)
        i += n
        if at is not None and end is None:
            last = i
    path = (*(('agent-runner',) if wrapped else ()), table, key)
    if where is None and toml_sections.written(lines, path):  # F448a
        if unset:
            lines = toml_sections.drop(lines, path)
        elif isinstance(value, dict) and value:
            lines = toml_sections.change(lines, path, _table_of(before, table, wrapped).get(key) or {}, value)
        else:  # an empty table is said on a line
            return toml_edit('\n'.join(toml_sections.drop(lines, path)), table, key, value)
    elif unset:
        if where is None:
            return text if key not in _table_of(before, table, wrapped) else _toml_refuse(table, key)
        lines[where[0]:where[0] + where[1]] = _toml_inner(lines[where[0]:where[0] + where[1]])
    else:
        new = f'{key} = {toml_value(value)}'
        if where is not None:
            old = lines[where[0]]
            indent = old[:len(old) - len(old.lstrip())]
            was = lines[where[0]:where[0] + where[1]]
            lines[where[0]:where[0] + where[1]] = [indent + c for c in _toml_inner(was)] + [
                indent + new + _toml_comment('\n'.join(was))]
        elif at is not None:
            lines[last:last] = [new]
        else:
            while lines and not lines[-1].strip():
                lines.pop()
            lines += ([''] if lines else []) + [f'[{name}]', new, '']
    out = '\n'.join(lines)
    try:
        after = tomllib.loads(out)
    except tomllib.TOMLDecodeError:
        return _toml_refuse(table, key)
    want = json.loads(json.dumps(before, default=str))
    t = want.setdefault('agent-runner', {}).setdefault(table, {}) if wrapped else want.setdefault(table, {})
    if not isinstance(t, dict):
        return _toml_refuse(table, key)
    if unset:
        t.pop(key, None)
    else:
        t[key] = value
    if json.loads(json.dumps(after, default=str)) != json.loads(json.dumps(want, default=str)):
        return _toml_refuse(table, key)
    return out


def _table_of(raw: dict, table: str, wrapped: bool) -> dict:
    t = (raw.get('agent-runner') or {}).get(table) if wrapped else raw.get(table)
    return t if isinstance(t, dict) else {}


def _toml_refuse(table: str, key: str) -> str:
    raise ValueError(f'[{table}] {key} is not on a line of its own in {LOCAL}: change it there by hand')


def local_settings_file(root: Path) -> Path:
    return local_file(root) or main_checkout(root) / LOCAL


def both_problem(raw: dict) -> str:
    """F419: why [git] pr and [run] approve cannot both be on; '' when they are not."""
    return ('[git] pr and [run] approve cannot both be on: either a person merges each pull request, or approves each '
            'push. Turn one off') if raw['git']['pr'] and raw['run']['approve'] else ''


def setting_check(root: Path, table: str, key: str, v, device: bool = False) -> str:
    """`setting_problem`, and for [models] whether each model named is one the runner takes ('' when all is well).
    `device`: a save to this machine's file, so [run] agent must be here too; other machines share the project's."""
    if problem := setting_problem(table, key, v):
        return problem
    if (table, key) in (('git', 'pr'), ('run', 'approve')) and v:  # F419
        snap = {(t['table'], k['key']): k['value'] for t in settings_snapshot(root)['tables'] for k in t['keys']}
        snap[table, key] = v
        return both_problem({'git': {'pr': snap['git', 'pr']}, 'run': {'approve': snap['run', 'approve']}})
    if (table, key) == ('git', 'master_branch'):  # F447b
        from agent_runner import working_branch
        try:
            return working_branch.problem(main_checkout(root), v)
        except SystemExit as e:  # another setting the files hold is refused
            return str(e).removeprefix('agent-runner: ')
    if device and (table, key) == ('run', 'agent'):  # B764a
        return agent_missing(root, v)
    from agent_runner import setting_checks  # F448a
    if problem := setting_checks.problem(root, table, key, v):
        return problem
    if table != 'models':
        return ''
    snap = {(t['table'], k['key']): k['value'] for t in settings_snapshot(root)['tables'] for k in t['keys']}
    snap[(table, key)] = v
    try:
        providers, local = model_providers(snap['models', 'providers']), bool(snap['models', 'local'])
        model_provider(snap['models', 'provider'], providers, local)  # F443
        model_tiers(snap['models', 'tiers'], providers)
        named = v.values() if key in ('kinds', 'sizes') else v if key == 'fallback' else \
            [v] if key not in MODEL_SETTINGS and isinstance(v, str) else []
        for m in named:
            if not isinstance(m, str) or not m:
                return f'[models] {key}: {m!r} is not a model name'
            claude_model(m, providers, local, f'[models] {key}')
        if key == 'providers':  # F448a: a role that still names one that goes would stop the run
            for k, m in ((k, m) for (t, k), m in snap.items() if t == 'models' and k not in ('local', 'providers')):
                for x in m.values() if isinstance(m, dict) else m if isinstance(m, list) else [m]:
                    if isinstance(x, str) and x:
                        claude_model(x, providers, local, f'[models] {k}')
    except SystemExit as e:
        return str(e).removeprefix('agent-runner: ')
    return ''


def setting_edit(data: bytes, table: str, key: str, value=None, unset: bool = False, name: str = LOCAL) -> bytes:
    """A settings file's bytes with one key set (or `unset`), its comments and line ends kept. An old key that still
    sets this one goes with it (F166). ValueError says why not; `name` is the file it names."""
    raw = data.decode('utf-8')
    crlf = '\r\n' in raw
    try:
        out = toml_edit(raw.replace('\r\n', '\n'), table, key, value, unset)
        for (t, k), (nt, nk, _, _) in MOVED.items():
            got = tomllib.loads(out)
            got = got['agent-runner'] if isinstance(got.get('agent-runner'), dict) else got
            if (nt, nk) == (table, key) and isinstance(got.get(t), dict) and k in got[t]:
                out = toml_edit(out, t, k, unset=True)
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f'{name} does not read as TOML ({e}): fix it there first') from None
    except ValueError as e:
        raise ValueError(str(e).replace(LOCAL, name)) from None
    return (out.replace('\n', '\r\n') if crlf else out).encode('utf-8')


def save_local_setting(root: Path, table: str, key: str, value=None, unset: bool = False) -> Path:
    """F97: set (or `unset`) one key in this machine's runner.local.toml, in place; ValueError says why not."""
    if problem := ('' if unset else setting_check(root, table, key, value, device=True)):
        raise ValueError(problem)
    if unset and (table not in DEFAULTS or key not in DEFAULTS[table]):
        raise ValueError(f'[{table}] {key} is not a setting')
    from agent_runner import setting_checks  # F448a
    if unset and (problem := setting_checks.reset_problem(root, 'device', table, key)):
        raise ValueError(problem)
    f = local_settings_file(root)
    if not f.exists():
        if unset:
            return f
        ensure_local(f.parent)
    f = f.resolve()
    out = setting_edit(f.read_bytes(), table, key, value, unset, f.name)
    write_whole(f, out, f.stat().st_mode & 0o777)
    keep_local_ignored(f.parent)
    return f


def _table_for(key: str) -> str:
    """The table line a key written at the top of a file misses."""
    return next((f'[{t}]' for t, keys in DEFAULTS.items() if key in keys), '[table]')


def settings_snapshot(root: Path) -> dict:
    """F97: every setting for the run app's Settings view, read from the files now: {'ok', 'project', 'device' (the
    two files' names), 'tables': [{'table', 'keys': [...]}], 'unknown': [...]}. A key: its type, choices, default,
    help, its value in each file (`project`, `device`, with `has_…`), the one in force (`value`), where that comes from
    (`source`: 'device', 'project' or 'default') and when a change applies (`applies`: 'now' or 'next run')."""
    raws, errors = {}, []
    files = {'project': config_file(root), 'device': local_file(root)}
    for side, f in files.items():
        try:
            raws[side] = _load(f) if f else {}
        except (OSError, tomllib.TOMLDecodeError) as e:
            raws[side] = {}
            errors.append(f'{f.name}: {e}')
    unknown = []
    for side, f in files.items():
        for t, keys in raws[side].items():
            gone = {k for (tt, k) in (*REMOVED, *MOVED) if tt == t}
            if not isinstance(keys, dict) or (t not in DEFAULTS and not gone):
                if f.name in ('runner.toml', LOCAL) and not (isinstance(keys, dict) and keys.get('agent-runner')):
                    unknown.append({'table': t if isinstance(keys, dict) else '', 'key': '' if isinstance(keys, dict) else t,
                                    'value': toml_value(keys), 'file': f.name, 'side': side,
                                    'why': f'[{t}] is not a table the runner reads, ignored' if isinstance(keys, dict)
                                    else f'no {_table_for(t)} line is above it, ignored'})
                continue
            for k, v in keys.items():
                if k in DEFAULTS.get(t, {}) or (t not in DEFAULTS and k not in gone):
                    continue
                said = migrate({t: {k: v}}, f.name)
                unknown.append({'table': t, 'key': k, 'value': toml_value(v), 'file': f.name, 'side': side,
                                'why': said[0].partition(': ')[2] if said else 'not a setting'})
    sessions = old_sessions([raws[side] for side in files])
    for side in files:
        move_keys(raws[side])
    from agent_runner import setting_words as W
    tables = []
    for t, keys in DEFAULTS.items():
        rows = []
        for k, d in keys.items():
            row = {'key': k, 'type': setting_type(t, k), 'choices': list(setting_choices(t, k)), 'default': d,
                   'off': 'off' in SETTING_ALSO.get((t, k), ()), 'also': list(SETTING_ALSO.get((t, k), ())),
                   'name': W.name(t, k), 'desc': W.desc(t, k), 'group': W.group(t, k), 'home': W.home(t, k),
                   'parent': W.parent(t, k), 'words': W.words(t, k), 'parts': W.parts(t, k), 'unit': W.unit(t, k), 'order': W.order(t, k),
                   'warn': W.warn(t, k),  # F448a
                   'applies': 'next run' if (t, k) in SETTING_NEXT else 'now', 'value': d, 'source': 'default'}
            for side in ('project', 'device'):
                have = raws[side].get(t)
                row[f'has_{side}'] = isinstance(have, dict) and k in have
                if row[f'has_{side}']:
                    row[side] = slots_in_apps(have[k], sessions) if (t, k) == ('run', 'remote_slots') else have[k]
                    row['value'] = {**d, **have[k]} if (t, k) == ('models', 'kinds') and isinstance(have[k], dict) \
                        else row[side]
                    row['source'] = side
            rows.append(row)
        tables.append({'table': t, 'keys': rows})
    return {'ok': not errors, 'out': '; '.join(errors), 'tables': tables, 'unknown': unknown,
            'groups': [list(g) for g in W.GROUPS],
            'project': files['project'].name if files['project'] else 'runner.toml',
            'device': files['device'].name if files['device'] else LOCAL}

