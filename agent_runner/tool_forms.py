"""F466b: the Tools page's other two 'Add…' forms, beside the SSH machine (devices.op_save).

Login: a website or account login (secret_logins.py) set from the page. Write-only: the page gets its facts, whether
the password is set and when it changed, never the value. It rides POST /tools, so it is saved only over https or
loopback with the page token (`devices.channel`, checked by web.py before any op runs).

Custom tool: a device reached another way, plus 'Describe it': plain words on what the tool is and how agents use it.
The device is saved as today; the words queue a task in the asking project that turns them into a tool entry
(command, page, buttons, `needs:` name, a test), which the person approves before it is saved.
"""
from __future__ import annotations

import re
import subprocess as sp
import sys
from pathlib import Path

from agent_runner import devices, secret_logins as L
from agent_runner.devices import Refused

DESCRIBE_MAX = 4000


def shown(name: str, lg: dict) -> dict:
    """A Login's card: never the password."""
    pw = lg.get('password') or {}
    return {'name': name, 'purpose': lg.get('purpose', ''), 'user': lg.get('user', ''), 'twofa': lg.get('twofa', ''),
            'projects': lg.get('projects') or [], 'set': bool(pw), 'changed': lg.get('changed', '')}


def logins() -> list[dict]:
    return [shown(n, lg) for n, lg in sorted(L.load().items())]


def _projects(v) -> list[str]:
    ps = v.split(',') if isinstance(v, str) else v if isinstance(v, list) else []
    return [p for p in (devices._text(x, 100) for x in ps) if p]


def op_login_save(a: dict, c) -> dict:
    """Add a Login or replace its facts; a password left empty keeps the old one (a new Login needs one)."""
    name = a.get('name') if isinstance(a.get('name'), str) else ''
    pw = a.get('password') if isinstance(a.get('password'), str) else ''
    if len(pw) > 1024:
        raise Refused('that password is too long')
    old = L.load().get(name)
    if not pw and not (old and old.get('password')):
        raise Refused('the password is empty')
    L.put(name, pw, purpose=devices._text(a.get('purpose'), 500), user=devices._text(a.get('user'), 200),
          twofa=devices._text(a.get('twofa'), 200),
          projects=_projects(a['projects']) if 'projects' in a else None)
    d = L.load()
    if pw:
        d[name]['changed'] = devices.today()
    L._save(d)
    return {'out': f'login {name} is saved', 'login': shown(name, d[name])}


def op_login_remove(a: dict, c) -> dict:
    d = L.load()
    name = a.get('name')
    if not isinstance(name, str) or name not in d:
        raise Refused('there is no such login')
    devices._drop(L._key(name), 'password', d[name].get('password'))
    del d[name]
    L._save(d)
    return {'out': f'login {name} is removed, its password too'}


def task_text(name: str, words: str) -> str:
    return (f'Turn the custom tool {name} into a tool entry in runner.toml ([run.tools.{name}]): its command, web '
            f'page, buttons, the `needs: {name}` name tasks use, and a test that checks it. The person described it '
            f'on the Tools page: "{words}". Show the person the entry and have them approve it (DECIDE) before it is '
            f'saved. | files: runner.toml')


def add_task(c, text: str) -> str:
    """`plan add F` in the project's own checkout, as a person would: its id."""
    pkg = str(Path(__file__).resolve().parent.parent)
    r = sp.run([sys.executable, '-c', 'import sys; sys.path.insert(0, sys.argv[1]); from agent_runner.cli import main; '
                'sys.argv = ["run", *sys.argv[2:]]; sys.exit(main())', pkg, 'plan', 'add', 'F', text,
                '--files', 'runner.toml', '--pri', 'normal'],
               cwd=str(c.root), capture_output=True, text=True, timeout=120)
    if r.returncode:
        raise Refused('the task could not be queued: ' + ((r.stderr or r.stdout).strip().splitlines() or ['?'])[-1])
    m = re.search(r'added (\S+)', r.stdout)
    return m.group(1) if m else ''


QUEUE = add_task  # tests swap it


def op_custom(a: dict, c) -> dict:
    """Save a custom tool (a device reached another way) and queue the task that turns its description into a tool
    entry. With no description it is today's 'Another way' device alone."""
    words = devices._text(a.pop('describe', ''), DESCRIBE_MAX)
    got = devices.op_save({**a, 'kind': 'other'}, c)
    if not words:
        return got
    tid = QUEUE(c, task_text(a.get('name', ''), words.replace('\n', ' ').replace('"', "'")))
    return {**got, 'task': tid, 'out': f'{got.get("out", "saved")}; task {tid} turns it into a tool entry, '
                                       f'for you to approve'}


OPS = {'login_save': op_login_save, 'login_remove': op_login_remove, 'custom': op_custom}
