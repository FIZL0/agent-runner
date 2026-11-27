"""F466a: logins, the website and account logins (an Apple ID, a store account) a project's agents may use.

A login is kept like a device's secrets (devices.py): its facts (name, what it is for, username, where 2FA codes go,
the projects that may use it) in logins.json in `devices.state_dir()`, never in devices.json; its password in the OS
keyring when an unattended run can read it, else one 0600 file in state_dir()/secrets. Never in a repo, a worktree or
a synced folder (`devices.unsafe_dir`). The password never goes on argv or into an environment: `run login use` gives
it on stdin or through the askpass helper over a socket in a 0700 folder, and what the command prints passes
`devices.Redactor`. Agents run as the same OS user, so this keeps secrets out of chats; it is no wall against an agent
that goes looking (docs/REFERENCE.md, ### Devices and logins).
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import subprocess as sp
import sys
from pathlib import Path

from agent_runner import devices
from agent_runner.devices import Refused

RUNNER = 'run'
SUBCOMMANDS = ('set', 'use', 'type', 'list', 'show', 'code')
ALL = '*'


def _file() -> Path:
    return devices.state_dir() / 'logins.json'


def load() -> dict:
    """{name: login}: no secret in it."""
    try:
        d = json.loads(_file().read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def _save(d: dict) -> None:
    devices._folder()
    devices._write(_file(), json.dumps(d, indent=1).encode())


def _key(name: str) -> str:
    """The name its password is kept under, apart from any device's."""
    return f'login-{name}'


def project_here() -> str:
    """The project of the current folder: its main checkout's folder name ('' outside a repo)."""
    try:
        top = sp.run(['git', 'rev-parse', '--show-toplevel'], capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, sp.SubprocessError):
        return ''
    return Path(devices._main(top)).name if top else ''


def may_use(lg: dict, project: str) -> bool:
    ps = lg.get('projects') or []
    return ALL in ps or (bool(project) and project in ps)


def put(name: str, password: str, *, purpose: str = '', user: str = '', twofa: str = '',
        projects: list[str] | None = None) -> dict:
    """Add or change a login; facts left empty keep their old value."""
    if not devices.NAME.fullmatch(name or ''):
        raise Refused(f'a login name is letters, digits, - and _, 40 at most: {name!r}')
    d = load()
    old = d.get(name) or {}
    lg = {'purpose': purpose or old.get('purpose', ''), 'user': user or old.get('user', ''),
          'twofa': twofa or old.get('twofa', ''),
          'projects': projects if projects is not None else old.get('projects', []),
          'password': old.get('password')}
    if password:
        devices._folder('secrets')
        lg['password'] = {'store': devices._keep(_key(name), 'password', password, old.get('password'))}
    d[name] = lg
    _save(d)
    return lg


def get(name: str) -> dict:
    lg = load().get(name)
    if lg is None:
        raise Refused(f'no login {name}: `{RUNNER} login list` names them; `{RUNNER} login set {name}` adds it')
    return lg


def password(name: str, lg: dict, project: str) -> str:
    """The password, for `use` and `type` alone; refused for a project the login is not for."""
    if not may_use(lg, project):
        raise Refused(f'login {name} is not for project {project or "(none)"}: '
                      f'`{RUNNER} login set {name} --project NAME` allows one')
    pw = devices._secret(_key(name), 'password', {'secrets': {'password': lg.get('password')}})
    if not pw:
        raise Refused(f'login {name} has no password: `{RUNNER} login set {name}`')
    return pw


def lines(name: str, lg: dict) -> list[str]:
    """What `show` prints: never the password."""
    return [f'{name}: {lg.get("purpose") or "(no purpose given)"}',
            f'  username: {lg.get("user") or "-"}',
            f'  password: {"set" if lg.get("password") else "not set"}',
            *([f'  2FA goes to: {lg["twofa"]}'] if lg.get('twofa') else []),
            f'  projects: {", ".join(lg.get("projects") or []) or "none"}']


def run_with(name: str, cmd: list[str], *, askpass: bool = False, project: str | None = None,
             out=None) -> int:
    """CMD with $LOGIN_USER, the password on stdin (or through the askpass helper), its output redacted."""
    lg = get(name)
    project = project_here() if project is None else project
    pw = password(name, lg, project)
    out = out or sys.stdout.buffer
    env = {**os.environ, 'LOGIN_USER': lg.get('user') or '', 'LOGIN_NAME': name}
    red = devices.Redactor([pw])
    with devices._tmp() as tmp:
        asker = None
        if askpass:
            devices.need_sockets()
            asker = devices.Asker(tmp, 'password', pw)
            env.update(SSH_ASKPASS=str(asker.script), SSH_ASKPASS_REQUIRE='force', SUDO_ASKPASS=str(asker.script),
                       GIT_ASKPASS=str(asker.script), LOGIN_ASKPASS=str(asker.script))
        try:
            p = sp.Popen(cmd, stdin=sp.DEVNULL if askpass else sp.PIPE, stdout=sp.PIPE, stderr=sp.STDOUT, env=env)
        except OSError as e:
            raise Refused(f'cannot run {cmd[0]}: {e.strerror}') from None
        try:
            if not askpass:
                try:
                    p.stdin.write(pw.encode() + b'\n')
                    p.stdin.close()
                except OSError:
                    pass
            while b := p.stdout.read1(65536):
                out.write(red.feed(b))
                out.flush()
            out.write(red.end())
            out.flush()
            return p.wait()
        finally:
            if asker:
                asker.close()


def type_cmd() -> list[str]:
    """The command that types its stdin into the focused field."""
    if sys.platform == 'darwin':
        return ['osascript', '-e', 'set t to do shell script "cat"',
                '-e', 'tell application "System Events" to keystroke t']
    if os.environ.get('WAYLAND_DISPLAY') and shutil.which('wtype'):
        return ['wtype', '-']
    if shutil.which('xdotool'):
        return ['xdotool', 'type', '--clearmodifiers', '--file', '-']
    raise Refused('nothing here can type into a field: install xdotool (X11) or wtype (Wayland)')


def type_field(name: str, field: str, project: str | None = None) -> None:
    lg = get(name)
    project = project_here() if project is None else project
    pw = password(name, lg, project)  # the project check also guards the username
    value = pw if field == 'password' else lg.get('user') or ''
    r = sp.run(type_cmd(), input=value.encode(), capture_output=True, timeout=60)
    if r.returncode:
        raise Refused('typing failed: ' + devices.Redactor([pw]).all(r.stderr).decode('utf-8', 'replace').strip())


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog=f'{RUNNER} login', description=(
        'Website and account logins agents may use, kept out of repos and chats.'))
    sub = ap.add_subparsers(dest='op', required=True)
    s = sub.add_parser('set', help='add or change a login; the password is asked hidden')
    s.add_argument('name')
    s.add_argument('--purpose', default='', help='what it is for')
    s.add_argument('--user', default='', help='the username')
    s.add_argument('--twofa', default='', help='where 2FA codes go (a note)')
    s.add_argument('--project', action='append', default=None,
                   help=f'a project that may use it (repeat; {ALL} for all); the current one when first set')
    s.add_argument('--keep-password', action='store_true', help='change the facts only')
    u = sub.add_parser('use', help='run CMD with $LOGIN_USER and the password on stdin')
    u.add_argument('name')
    u.add_argument('--askpass', action='store_true',
                   help='give the password through an askpass helper (SSH_ASKPASS, SUDO_ASKPASS, GIT_ASKPASS, '
                        'LOGIN_ASKPASS) instead of stdin')
    u.add_argument('cmd', nargs=argparse.REMAINDER)
    t = sub.add_parser('type', help='type a field into the focused field, printing nothing')
    t.add_argument('name')
    t.add_argument('--field', choices=('password', 'username'), default='password')
    sub.add_parser('list', help='every login: name, purpose, password set or not')
    sh = sub.add_parser('show', help='a login: purpose, username, set or not; never the password')
    sh.add_argument('name')
    c = sub.add_parser('code', help='where its 2FA codes go')
    c.add_argument('name')
    a = ap.parse_args(argv)
    try:
        if a.op == 'set':
            pw = ''
            if not a.keep_password:
                pw = getpass.getpass(f'password for {a.name} (hidden): ') if sys.stdin.isatty() \
                    else sys.stdin.readline().rstrip('\n')
            projects = a.project
            if projects is None and a.name not in load():
                projects = [p] if (p := project_here()) else []
            lg = put(a.name, pw, purpose=a.purpose, user=a.user, twofa=a.twofa, projects=projects)
            print('\n'.join(lines(a.name, lg)))
        elif a.op == 'use':
            cmd = a.cmd[1:] if a.cmd[:1] == ['--'] else a.cmd
            if not cmd:
                ap.error('login use NAME -- CMD: no command')
            return run_with(a.name, cmd, askpass=a.askpass)
        elif a.op == 'type':
            type_field(a.name, a.field)
        elif a.op == 'list':
            d = load()
            for n in sorted(d):
                print(f'{n}: {d[n].get("purpose") or "-"} (password {"set" if d[n].get("password") else "not set"})')
            if not d:
                print(f'no logins: `{RUNNER} login set NAME` adds one')
        elif a.op == 'show':
            print('\n'.join(lines(a.name, get(a.name))))
        elif a.op == 'code':
            lg = get(a.name)
            print(f'{a.name}: 2FA codes go to {lg["twofa"]}; ask the person for the code' if lg.get('twofa')
                  else f'{a.name}: no 2FA note; `{RUNNER} login set {a.name} --keep-password --twofa WHERE`')
    except Refused as e:
        print(f'{RUNNER} login: {e}', file=sys.stderr)
        return 1
    return 0
