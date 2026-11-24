"""F405: what the Settings view says of the agents on this machine: the Claude Code programs found here (the picker of
`[run] agent`) and the model providers with their logins. Never a secret: `login.login_of` gives none."""
from __future__ import annotations

import os
import re
import shutil
import subprocess as sp
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from agent_runner import config as CF
from agent_runner import login

# where an installer puts Claude Code when PATH does not name it (a run started by a service has a short PATH)
PLACES = ('~/.local/bin', '~/.claude/local', '/opt/homebrew/bin', '/usr/local/bin')
VERSION_WAIT = 5  # s `--version` may take
VERSION_AGAIN = 60  # s until a program that did not answer is asked again
_VERSIONS: dict[tuple, tuple[str, float]] = {}  # (path, its file's mtime and size): its version, when asked


def version(path: str) -> str:
    """'2.1.330' of the Claude Code program at `path`; '' when it does not say. Asked once while its file is the same."""
    try:
        st = os.stat(path)
    except OSError:
        return ''
    key = path, st.st_mtime_ns, st.st_size
    got = _VERSIONS.get(key)
    if got and (got[0] or time.time() - got[1] < VERSION_AGAIN):
        return got[0]
    v = ''
    try:
        r = sp.run([path, '--version'], capture_output=True, text=True, encoding='utf-8', errors='replace',
                   stdin=sp.DEVNULL, timeout=VERSION_WAIT, env={**os.environ, 'DISABLE_AUTOUPDATER': '1'})
        m = re.search(r'\d+(?:\.\d+)+', r.stdout or '') if r.returncode == 0 else None
        v = m.group(0) if m else ''
    except (OSError, sp.TimeoutExpired):
        pass
    _VERSIONS[key] = v, time.time()
    return v


def programs() -> list[dict]:
    """The Claude Code programs on this machine, the one a bare `claude` starts first: {'value' (what [run] agent
    becomes), 'path', 'version'}."""
    first, at, seen = shutil.which('claude'), [], set()
    dirs = [d for d in os.environ.get('PATH', '').split(os.pathsep) if os.path.isabs(d)]
    for p in [first, *(shutil.which('claude', path=d) for d in [*dirs, *map(os.path.expanduser, PLACES)])]:
        if p and (real := os.path.realpath(p)) not in seen:
            seen.add(real)
            at.append(p)
    if not at:
        return []
    with ThreadPoolExecutor(len(at)) as pool:
        said = list(pool.map(version, at))
    return [{'value': 'claude' if p == first else p, 'path': p, 'version': v} for p, v in zip(at, said)]


def picks(root: Path, row: dict) -> list[dict]:
    """The picker of `[run] agent` (`row`: its settings row): the programs found, then each value kept in a settings
    file that is not one of them, with `bad`: what is wrong with it ('' for a wrapper that is there)."""
    out = [{**p, 'found': True, 'bad': ''} for p in programs()]
    for v in (row['value'], row.get('device'), row.get('project')):
        if not isinstance(v, str) or any(p['value'] == v for p in out):
            continue
        real = os.path.realpath(v) if os.path.isabs(v) else ''
        same = next((p for p in out if p['found'] and real and os.path.realpath(p['path']) == real), None)
        bad = CF.agent_problem(root, v)
        out.append({'value': v, 'path': v if real else shutil.which(v) or '', 'version': same['version'] if same and not bad else '',
                    'found': not bad, 'bad': bad})
    return out


def providers(table) -> list[dict]:
    """Each provider a role can name (`table`: [models.providers] as its file has it): {'name', 'state' ('in', 'out',
    'none': needs no login, 'unchecked'), 'says', 'cmd' (what logs it in)}."""
    bad = []
    try:
        own = CF.model_providers(table)
    except SystemExit:  # its words quote the table, which may hold a key: not shown
        own, bad = {}, [{'name': '[models.providers]', 'state': 'unchecked', 'says': 'not valid, so its providers are not listed', 'cmd': ''}]
    creds, out = login.stored(), []
    for name in [*CF.PROVIDERS, *own]:
        ok, where = login.login_of(name, own, creds)
        state = 'unchecked' if name == 'claude' else 'out' if not ok else 'none' if where.startswith('needs none') else 'in'
        out.append({'name': name, 'state': state, 'says': where if ok else '',
                    'cmd': '' if ok else f'{CF.RUNNER} login {name}'})
    return out + bad
