"""F169: devices, the machines and test rigs a person adds on the run app's Tools page for agents to reach over SSH or
another way. Every project on this machine may use them; each project says which ones it uses, and a used one is a
shared tool (`shared_tools.specs` takes it in), so it works as a `needs:` name.

They are kept in `state_dir()`, outside every repo: devices.json (no secret in it), and a device's secrets (SSH private
key, its passphrase, password) in the OS keyring when an unattended run can read it, else one 0600 file each.

A secret is write-only: the page sends it (`post`, accepted only over https or loopback, `channel`), `_secret` alone
reads it, and only `session` uses it. ssh gets a key from an ssh-agent of its own and a password from an SSH_ASKPASS
helper that asks this process over a socket in a 0700 folder: never argv, never an environment. What ssh prints passes
`Redactor`. Agents run as the same OS user, so this keeps secrets out of chats; it is no wall against an agent that
goes looking (docs/REFERENCE.md, ### Devices).
"""
from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import ipaddress
import json
import os
import re
import shlex
import shutil
import signal
import socket
import subprocess as sp
import sys
import tempfile
import threading
import time
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from agent_runner import plat

NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,39}')
HOST = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,252}')
USER = re.compile(r'[A-Za-z0-9_][A-Za-z0-9._\\-]{0,63}')
SECRETS = ('key', 'passphrase', 'password')
WORDS = {'key': 'private key', 'passphrase': 'key passphrase', 'password': 'password'}
PINNED = 'agent-runner-device'  # the one host name in a connection's own known_hosts (HostKeyAlias)
HIDDEN = '[secret hidden]'
CONNECT = 5       # s a TCP or SSH connection may take
PROBE = 20        # s a whole Test connection step may take
BODY_MAX = 65536  # bytes a request to /tools may hold
SSH_PORT = 22
PORTS = {'vnc': 5900, 'rdp': 3389, 'ssh': 22, 'http': 80, 'https': 443}
CHANNEL = 'X-Runner-Channel'  # Runner Home's verdict on the browser's connection, for the run behind it


class Refused(Exception):
    """Why something is not done, in words a person may read. Never holds what was typed."""


# --- where devices are kept --------------------------------------------------------------------------------------

def state_dir() -> Path:
    if env := os.environ.get('AGENT_RUNNER_DEVICES'):
        return Path(env).expanduser()
    if sys.platform.startswith('win'):
        base = Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local')
    elif sys.platform == 'darwin':
        base = Path.home() / 'Library' / 'Application Support'
    else:
        base = Path(os.environ.get('XDG_STATE_HOME') or Path.home() / '.local' / 'state')
    return base / 'agent-runner' / 'devices'


SYNCED = re.compile(r'(dropbox|onedrive|google ?drive|googledrive|icloud ?drive|mobile documents|nextcloud|owncloud|'
                    r'pcloud ?drive|syncthing|sync|cloudstorage)\b.*', re.I)


def unsafe_dir(d: Path) -> str:
    """Why secrets may not be kept in `d` ('' when they may): a repo, a worktree or a synced folder."""
    d = d.resolve()
    for p in (d, *d.parents):
        if (p / '.git').exists():
            return f'{d} is inside a git repository'
        if SYNCED.fullmatch(p.name) or any((p / m).exists() for m in ('.stfolder', '.dropbox', '.sync')):
            return f'{d} is in a synced folder'
    return ''


def _folder(*sub: str) -> Path:
    """The state folder (or one under it), made 0700."""
    d = state_dir()
    if why := unsafe_dir(d):
        raise Refused(f'{why}, so no device is kept there. Set AGENT_RUNNER_DEVICES to another folder.')
    for p in (d, d.joinpath(*sub)):
        p.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not plat.WINDOWS:
            os.chmod(p, 0o700)
    return d.joinpath(*sub)


def _write(f: Path, data: bytes) -> None:
    """`data` in `f` at once, 0600."""
    fd, tmp = tempfile.mkstemp(dir=str(f.parent), prefix='.new-')  # mkstemp makes it 0600
    try:
        with os.fdopen(fd, 'wb') as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, f)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


_READ: tuple = ('', {})


def load() -> dict:
    """{'devices': {name: device}, 'uses': {project folder: [names]}}; read again when the file changed."""
    global _READ
    f = state_dir() / 'devices.json'
    try:
        st = f.stat()
        stamp = (str(f), st.st_mtime_ns, st.st_size, st.st_ino)
        if _READ[0] != stamp:
            d = json.loads(f.read_text(encoding='utf-8'))
            _READ = (stamp, d if isinstance(d, dict) else {})
        d = _READ[1]
    except (OSError, ValueError):
        d = {}
    return {'devices': dict(d.get('devices') or {}), 'uses': dict(d.get('uses') or {})}


@contextlib.contextmanager
def _locked():
    """One writer at a time: each run and each `run device` is a process of its own."""
    d, end = _folder(), time.monotonic() + 25  # stopping a page command takes some seconds of it
    while not (held := plat.lock(d / 'lock')):
        if time.monotonic() > end:
            raise Refused('another device is being saved; try again')
        time.sleep(0.05)
    try:
        yield
    finally:
        held.close()


@contextlib.contextmanager
def _edit():
    with _locked():
        d = json.loads(json.dumps(load()))
        yield d
        _write(state_dir() / 'devices.json', json.dumps(d, indent=1).encode())


@lru_cache(maxsize=64)
def _main(root: str) -> str:
    from agent_runner.config import main_checkout
    try:
        return str(main_checkout(root))
    except (SystemExit, OSError):
        return root


def project(c) -> str:
    """The project's key in `uses`: its main checkout."""
    return _main(str(c.root))


def used(c) -> dict[str, dict]:
    """{name: device} of the devices the project uses."""
    d = load()
    if not d['devices'] or not getattr(c, 'root', None):
        return {}
    return {n: d['devices'][n] for n in d['uses'].get(project(c), []) if n in d['devices']}


def specs(c) -> dict[str, dict]:
    """The used devices as `shared_tools.specs` has tools; one in runner.toml with the same name wins."""
    return {n: {'check': '', 'label': n, 'connect': f'Connect {n}', 'description': d.get('description', ''),
                'exclusive': bool(d.get('exclusive')), 'device': True} for n, d in used(c).items()}


# --- secrets -------------------------------------------------------------------------------------------------------

def _account(name: str, what: str) -> str:
    return f'agent-runner/{name}/{what}'


def _tool(argv: list[str], data: str = '') -> sp.CompletedProcess | None:
    """A keyring command as an unattended run would have it: no display, a short time limit, the secret on stdin."""
    env = {k: os.environ[k] for k in ('HOME', 'PATH', 'XDG_RUNTIME_DIR', 'USER', 'LOGNAME', 'LANG') if k in os.environ}
    if 'XDG_RUNTIME_DIR' not in env and hasattr(os, 'getuid'):
        env['XDG_RUNTIME_DIR'] = f'/run/user/{os.getuid()}'
    try:
        return sp.run(argv, input=data, capture_output=True, text=True, timeout=5, env=env)
    except (OSError, sp.SubprocessError):
        return None


def _unlocked() -> bool:
    """Linux: the login keyring is open now (asking a locked one would put a dialog on the person's screen)."""
    r = _tool(['busctl', '--user', 'get-property', 'org.freedesktop.secrets', '/org/freedesktop/secrets/aliases/default',
               'org.freedesktop.Secret.Collection', 'Locked'])
    return bool(r and r.returncode == 0 and r.stdout.split() == ['b', 'false'])


def _ring_put(kind: str, acc: str, value: str) -> bool:
    data = base64.b64encode(value.encode()).decode()
    if kind == 'secret-tool':
        r = _tool(['secret-tool', 'store', '--label', 'agent-runner device', 'service', 'agent-runner', 'account', acc], data)
    else:  # `security -i` reads the command, secret and all, from stdin
        r = _tool(['security', '-i'], f'add-generic-password -U -s agent-runner -a "{acc}" -w {data}\n')
    return bool(r and r.returncode == 0)


def _ring_get(kind: str, acc: str) -> str | None:
    if kind == 'secret-tool':
        if not _unlocked():
            return None
        r = _tool(['secret-tool', 'lookup', 'service', 'agent-runner', 'account', acc])
    else:
        r = _tool(['security', 'find-generic-password', '-s', 'agent-runner', '-a', acc, '-w'])
    try:
        return base64.b64decode(r.stdout.strip(), validate=True).decode() if r and r.returncode == 0 and r.stdout else None
    except ValueError:
        return None


def _ring_del(kind: str, acc: str) -> None:
    if kind == 'secret-tool':
        _tool(['secret-tool', 'clear', 'service', 'agent-runner', 'account', acc])
    else:
        _tool(['security', 'delete-generic-password', '-s', 'agent-runner', '-a', acc])


def keyring() -> str:
    """The OS keyring's command when an unattended run can read it, else '' (a file it is): it is open, what is put in
    comes back with no display to ask on, and no run starts here before the person logs in (systemd linger)."""
    if os.environ.get('AGENT_RUNNER_KEYRING') == 'off' or plat.WINDOWS:
        return ''
    if sys.platform == 'darwin':
        kind = 'security'
    else:
        kind = 'secret-tool'
        user = os.environ.get('USER') or ''
        if not shutil.which('busctl') or (user and Path('/var/lib/systemd/linger', user).exists()) or not _unlocked():
            return ''
    if not shutil.which(kind):
        return ''
    acc, value = _account('probe', os.urandom(4).hex()), os.urandom(2500).hex()
    try:
        return kind if _ring_put(kind, acc, value) and _ring_get(kind, acc) == value else ''
    finally:
        _ring_del(kind, acc)


def _file(name: str, what: str) -> Path:
    return state_dir() / 'secrets' / f'{name}.{what}'


def _keep(name: str, what: str, value: str, old: dict | None) -> str:
    """Keep one secret over the `old` one; where it is."""
    was = (old or {}).get('store') or 'file'
    if (ring := keyring()) and _ring_put(ring, _account(name, what), value):
        _file(name, what).unlink(missing_ok=True)
        return ring
    _write(_folder('secrets') / f'{name}.{what}', value.encode())
    if was != 'file':
        _ring_del(was, _account(name, what))
    return 'file'


def _drop(name: str, what: str, meta: dict | None) -> None:
    _file(name, what).unlink(missing_ok=True)
    if meta and meta.get('store') not in ('', 'file', None):
        _ring_del(meta['store'], _account(name, what))


def _secret(name: str, what: str, dev: dict) -> str:
    """A secret's value, '' when it is not set. Only for a connection of the runner's own (`session`)."""
    meta = (dev.get('secrets') or {}).get(what)
    if not meta:
        return ''
    if meta.get('store') == 'file':
        try:
            return _file(name, what).read_text(encoding='utf-8')
        except OSError:
            got = None
    else:
        got = _ring_get(meta.get('store') or '', _account(name, what))
    if not got:
        raise Refused(f'the {WORDS[what]} of {name} cannot be read here '
                      f'({"its file is gone" if meta.get("store") == "file" else "the keyring is locked"}): '
                      f'replace it on the Tools page')
    return got


# --- what may be saved -----------------------------------------------------------------------------------------------

def _text(v, most: int) -> str:
    s = str(v if v is not None else '').replace('\r\n', '\n').replace('\r', '\n').strip()
    if len(s) > most:
        raise Refused(f'that is longer than {most} characters')
    return re.sub(r'[\x00-\x09\x0b-\x1f\x7f]', ' ', s)


def aliases() -> list[str]:
    """The hosts ~/.ssh/config names, for the page to pick from."""
    base = Path(os.environ.get('AGENT_RUNNER_SSH_CONFIG') or Path.home() / '.ssh' / 'config')
    out: list[str] = []

    def read(f: Path, deep: int) -> None:
        try:
            lines = f.read_text(encoding='utf-8', errors='replace').splitlines()
        except OSError:
            return
        for l in lines:
            m = re.match(r'\s*(Host|Include)[\s=]+(.+)', l, re.I)
            if not m:
                continue
            for w in m[2].split('#')[0].replace('"', ' ').split():
                if m[1].lower() == 'host':
                    if HOST.fullmatch(w):
                        out.append(w)
                elif deep:
                    p = Path(w).expanduser()
                    p = p if p.is_absolute() else base.parent / p
                    for g in sorted(p.parent.glob(p.name)):
                        read(g, deep - 1)
    read(base, 2)
    return sorted(set(out))


def _page_fields(a: dict) -> dict:
    """F407: {page, start, folder} of an other device, those that are set: its web page, the command that starts it
    and that command's working directory."""
    url, cmd, folder = (str(a.get(k) or '').strip(' ') for k in ('page', 'start', 'folder'))
    if not url:
        if cmd:
            raise Refused('a start command needs the web page it starts')
        return {}
    try:
        u = urlsplit(url)
        ok = u.scheme in ('http', 'https') and u.hostname and (u.port is None or u.port > 0)
    except ValueError:
        ok = False
    if not ok or len(url) > 2000 or not re.fullmatch(r'[hH][^\x00-\x20\x7f"\'<>\\`]+', url):
        raise Refused('the web page is an address that starts with http:// or https://')
    if '@' in u.netloc:
        raise Refused('leave the sign-in out of the web page address: agents see it')
    if not cmd:
        return {'page': url}
    if len(cmd) > 1000 or len(folder) > 1000 or re.search(r'[\x00-\x1f\x7f]', cmd + folder):
        raise Refused('the start command and its working directory are one line each, 1000 characters at most')
    if folder:
        try:
            d = Path(folder).expanduser()
            ok = d.is_absolute()  # one that is gone is said at the start, and blocks no other edit
        except (OSError, RuntimeError, ValueError):
            ok = False
        if not ok:
            raise Refused('the working directory is a whole path, from / or ~')
    return {'page': url, 'start': cmd, **({'folder': folder} if folder else {})}


PORT_PAGE = re.compile(r':([0-9]{1,5})')


def tool_fields(t: dict) -> dict:
    """F428a: {page, start} of a [run.tools.<name>], those that are set, under a device's rules; its page may also be
    ':PORT' of this machine, at the host the run page was opened on."""
    page, start = (str(t.get(k) or '').strip(' ') for k in ('page', 'start'))
    if page.startswith(':'):
        m = PORT_PAGE.fullmatch(page)
        if not m or not 0 < int(m[1]) < 65536:
            raise Refused("the web page is an http:// or https:// address, or ':PORT' with a port from 1 to 65535")
        return {**_page_fields({'page': 'http://localhost', 'start': start}), 'page': page}
    return _page_fields({'page': page, 'start': start})


def checked(a: dict) -> dict:
    """The fields of a device as they may be saved. A refusal names the field, never what was typed in it."""
    kind = a.get('kind')
    if kind not in ('ssh', 'other'):
        raise Refused('the kind is SSH or other')
    dev = {'kind': kind, 'description': _text(a.get('description'), 2000), 'exclusive': a.get('exclusive') is True}
    if kind == 'other':
        dev['reach'] = _text(a.get('reach'), 500).replace('\n', ' ')
        if not dev['reach']:
            raise Refused('say the command or address agents use to reach it')
        return {**dev, **_page_fields(a)}
    if alias := str(a.get('alias') or ''):
        if alias not in aliases():
            raise Refused('that host is not in ~/.ssh/config')
        return {**dev, 'alias': alias}
    host, user, port = (str(a.get(k) or '').strip(' ') for k in ('host', 'user', 'port'))
    if not HOST.fullmatch(host):
        raise Refused('the host is a name or an address: letters, digits, dots, colons and dashes, not a dash first')
    if user and not USER.fullmatch(user):
        raise Refused('the user is letters, digits, dots, underscores and dashes, not a dash first')
    if port and (not re.fullmatch(r'[0-9]{1,5}', port) or not 0 < int(port) < 65536):
        raise Refused('the port is a number from 1 to 65535')
    return {**dev, 'host': host, 'user': user, 'port': int(port or SSH_PORT)}


WHERE = ('kind', 'alias', 'host', 'user', 'port')


def fingerprint(blob: str) -> str:
    """'SHA256:…' of a public key's base64."""
    return 'SHA256:' + base64.b64encode(hashlib.sha256(base64.b64decode(blob)).digest()).decode().rstrip('=')


def today() -> str:
    return time.strftime('%Y-%m-%d')


# --- connecting -------------------------------------------------------------------------------------------------------

class Redactor:
    """A stream with every secret in it replaced, whole or cut across two reads."""

    def __init__(self, secrets: list[str]):
        want = set()
        for s in secrets:
            for part in {s, s.strip(), *(l for l in s.splitlines() if len(l) >= 8 and '-----' not in l)}:
                if part:
                    want.add(part.encode())
        self.want = sorted(want, key=len, reverse=True)
        self.pat = re.compile(b'|'.join(re.escape(w) for w in self.want)) if want else None
        self.held = b''

    def _sub(self, b: bytes) -> bytes:
        return self.pat.sub(HIDDEN.encode(), b) if self.pat else b

    def feed(self, data: bytes) -> bytes:
        if not self.pat:
            return data
        buf = self.held + data
        cut = len(buf)
        for n in range(min(len(buf), len(self.want[0]) - 1), 0, -1):  # the longest end that may be a secret's start
            if any(len(w) > n and w.startswith(buf[-n:]) for w in self.want):
                cut = len(buf) - n
                break
        for m in self.pat.finditer(buf):
            if m.start() < cut < m.end():
                cut = m.start()
        self.held = buf[cut:]
        return self._sub(buf[:cut])

    def end(self) -> bytes:
        out, self.held = self._sub(self.held), b''
        return out

    def all(self, b: bytes) -> bytes:
        return self.feed(b) + self.end()


HELPER = '''#!/bin/sh
exec {py} -I -c 'import socket,sys
s=socket.socket(socket.AF_UNIX);s.connect(sys.argv[1]);s.sendall(sys.argv[2].encode()[:500]);s.shutdown(socket.SHUT_WR)
d=b""
while True:
    b=s.recv(4096)
    if not b: break
    d+=b
if not d: sys.exit(1)
sys.stdout.buffer.write(d+b"\\n")' {sock} "$1"
'''


class Asker:
    """SSH_ASKPASS: ssh runs the helper script, which asks this process. Answers once, and only a prompt that asks for
    `word`."""

    def __init__(self, tmp: Path, word: str, value: str):
        self.word, self.value, self.left = word, value, 1
        sock, self.script = tmp / f'{word}.sock', tmp / f'{word}.sh'
        self.s = socket.socket(socket.AF_UNIX)
        self.s.bind(str(sock))
        os.chmod(sock, 0o600)
        self.s.listen(2)
        self.script.write_text(HELPER.format(py=shlex.quote(sys.executable), sock=shlex.quote(str(sock))))
        os.chmod(self.script, 0o700)
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self) -> None:
        while True:
            try:
                conn, _ = self.s.accept()
            except OSError:
                return
            with conn, contextlib.suppress(OSError):
                conn.settimeout(5)
                prompt = b''
                while b := conn.recv(1024):
                    prompt += b
                if self.left and self.word in prompt.decode('utf-8', 'replace').lower():
                    self.left -= 1
                    conn.sendall(self.value.encode())

    def close(self) -> None:
        self.s.close()


def _env(asker: Asker | None, **more: str) -> dict:
    return {**os.environ, 'SSH_ASKPASS': str(asker.script) if asker else shutil.which('false') or '/bin/false',
            'SSH_ASKPASS_REQUIRE': 'force', **more}


def need_sockets() -> None:
    if plat.WINDOWS:
        raise Refused('a stored secret cannot be used on Windows; pick a host of ~/.ssh/config instead')


@contextlib.contextmanager
def _tmp():
    """A 0700 folder on a short path (a socket's path has a length limit)."""
    d = Path(tempfile.mkdtemp(prefix='ar-dev-', dir=None if plat.WINDOWS else '/tmp'))
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


@contextlib.contextmanager
def _agent(tmp: Path, key: str, passphrase: str):
    """An ssh-agent of this connection's own, with `key` for one minute: (its socket, the public key). Refused when
    the key does not open."""
    need_sockets()
    sock = tmp / 'agent.sock'
    asker = Asker(tmp, 'passphrase', passphrase) if passphrase else None
    try:
        p = sp.Popen(['ssh-agent', '-D', '-a', str(sock)], stdin=sp.DEVNULL, stdout=sp.DEVNULL, stderr=sp.DEVNULL)
    except OSError:
        raise Refused('ssh-agent is not installed on this machine') from None
    try:
        end = time.monotonic() + 5
        while not sock.exists() and time.monotonic() < end and p.poll() is None:
            time.sleep(0.02)
        env = _env(asker, SSH_AUTH_SOCK=str(sock))
        try:
            r = sp.run(['ssh-add', '-q', '-t', '60', '-'], input=key.encode(), capture_output=True, env=env, timeout=PROBE)
            pub = sp.run(['ssh-add', '-L'], capture_output=True, text=True, env=env, timeout=PROBE) if not r.returncode else None
        except (OSError, sp.SubprocessError):
            raise Refused('ssh-add did not take the key') from None
        bits = pub.stdout.split() if pub and not pub.returncode else []
        if len(bits) < 2:
            raise Refused('the private key does not open: it is not a private key, or its passphrase is missing or wrong')
        yield sock, f'{bits[0]} {bits[1]}'
    finally:
        p.terminate()
        with contextlib.suppress(sp.TimeoutExpired):
            p.wait(5)
        if asker:
            asker.close()


def _base(dev: dict) -> list[str]:
    """The options every connection has. An alias keeps the person's own config for where and how; nothing in it may
    widen what the connection does."""
    out = [] if dev.get('alias') else ['-F', 'none' if not plat.WINDOWS else 'NUL']
    opts = {'ConnectTimeout': CONNECT, 'HostKeyAlias': PINNED, 'GlobalKnownHostsFile': 'none' if not plat.WINDOWS else 'NUL',
            'CheckHostIP': 'no', 'VerifyHostKeyDNS': 'no', 'UpdateHostKeys': 'no', 'HashKnownHosts': 'no',
            'ForwardAgent': 'no', 'ForwardX11': 'no', 'ClearAllForwardings': 'yes', 'PermitLocalCommand': 'no',
            'ControlMaster': 'no', 'ControlPath': 'none', 'LogLevel': 'ERROR'}
    if not dev.get('alias'):
        opts['Port'] = dev['port']
        if dev.get('user'):
            opts['User'] = dev['user']
    for k, v in opts.items():
        out += ['-o', f'{k}={v}']
    return out


def _dest(dev: dict) -> str:
    return dev.get('alias') or dev['host']


@contextlib.contextmanager
def session(name: str, dev: dict):
    """What one connection to device `name` needs: (its options, its environment, the secrets to hide)."""
    if dev['kind'] != 'ssh':
        raise Refused(f'{name} is not an SSH device. Reach it with: {dev.get("reach", "")}')
    hk = dev.get('hostkey')
    if not hk:
        raise Refused(f'the host key of {name} is not accepted yet: a person tests and accepts it on the Tools page'
                      + (f': {u}' if (u := tools_link()) else ''))
    key, phrase, pw = (_secret(name, w, dev) for w in SECRETS)
    with _tmp() as tmp, contextlib.ExitStack() as st:
        (tmp / 'known').write_text(f'{PINNED} {hk["type"]} {hk["blob"]}\n')
        opts = [*_base(dev), '-o', 'StrictHostKeyChecking=yes', '-o', f'UserKnownHostsFile={tmp / "known"}']
        asker = None
        if key:
            sock, pub = st.enter_context(_agent(tmp, key, phrase))
            (tmp / 'key.pub').write_text(pub + '\n')
            opts += ['-o', f'IdentityAgent={sock}', '-o', 'IdentitiesOnly=yes', '-o', f'IdentityFile={tmp / "key.pub"}']
        if pw:
            need_sockets()
            asker = Asker(tmp, 'password', pw)
            st.callback(asker.close)
            opts += ['-o', 'NumberOfPasswordPrompts=1', '-o', 'PreferredAuthentications='
                     + ('publickey,' if key else '') + 'password,keyboard-interactive']
            if not key:
                opts += ['-o', 'PubkeyAuthentication=no', '-o', 'IdentityAgent=none']
        else:
            opts += ['-o', 'BatchMode=yes']
        yield opts, _env(asker), [x for x in (key, phrase, pw) if x]


def scan(dev: dict) -> dict:
    """The host key the device shows now: {type, blob, fp}. Refused, in words, when it cannot be reached."""
    with _tmp() as tmp:
        f = tmp / 'known'
        argv = ['ssh', *_base(dev), '-o', 'StrictHostKeyChecking=accept-new', '-o', f'UserKnownHostsFile={f}',
                '-o', 'PreferredAuthentications=none', '-o', 'PubkeyAuthentication=no', '-o', 'BatchMode=yes',
                '-T', '--', _dest(dev), 'exit']
        try:
            r = sp.run(argv, stdin=sp.DEVNULL, capture_output=True, timeout=PROBE, env=_env(None))
        except FileNotFoundError:
            raise Refused('ssh is not installed on this machine') from None
        except (OSError, sp.SubprocessError):
            raise Refused('it did not answer in time') from None
        try:
            bits = f.read_text(encoding='utf-8').split()
            return {'type': bits[1], 'blob': bits[2], 'fp': fingerprint(bits[2])}
        except (OSError, IndexError, ValueError):
            raise Refused(said(r.stderr) or 'it did not answer') from None


PLAIN = (('could not resolve', 'the host name is not known'), ('connection refused', 'nothing answers on that port'),
         ('timed out', 'it did not answer in time'), ('no route to host', 'it is not on the network'),
         ('network is unreachable', 'it is not on the network'), ('permission denied', 'it did not accept the sign-in'),
         ('too many authentication', 'it did not accept the sign-in'),
         ('host key verification failed', 'its host key changed'), ('connection closed', 'it closed the connection'),
         ('connection reset', 'it closed the connection'))


def said(err: bytes) -> str:
    """ssh's error in plain words."""
    text = err.decode('utf-8', 'replace')
    for have, plain in PLAIN:
        if have in text.lower():
            return plain
    last = next((l.strip() for l in reversed(text.splitlines()) if l.strip()), '')
    return last[:160]


def test(name: str, dev: dict) -> dict:
    """Test connection: {ok, out, hostkey} (hostkey: a fingerprint that waits for the person, `was` the accepted one)."""
    if dev['kind'] != 'ssh':
        state, why = reach(dev)
        return {'ok': state == 'free', 'out': f'{name} can be reached' if state == 'free' else f'{name}: {why}'}
    try:
        seen = scan(dev)
    except Refused as e:
        return {'ok': False, 'out': f'Not connected: {e}'}
    was = dev.get('hostkey')
    if not was or (was['type'], was['blob']) != (seen['type'], seen['blob']):
        return {'ok': False, 'hostkey': {'fp': seen['fp'], 'type': seen['type'], 'was': was['fp'] if was else ''}, 'seen': seen,
                'out': f'Refused: the host key of {name} changed. It may be another machine.' if was else
                f'{name} answers. Compare its fingerprint with the device, then accept it.'}
    try:
        with session(name, dev) as (opts, env, hide):
            try:
                r = sp.run(['ssh', *opts, '-T', '--', _dest(dev), 'exit'], stdin=sp.DEVNULL, capture_output=True,
                           timeout=PROBE, env=env)
            except (OSError, sp.SubprocessError):
                return {'ok': False, 'out': 'Not connected: it did not answer in time'}
            if r.returncode == 255:
                return {'ok': False, 'out': 'Not connected: ' + said(Redactor(hide).all(r.stderr))}
    except Refused as e:
        return {'ok': False, 'out': f'Not connected: {e}'}
    return {'ok': True, 'out': f'Connected to {name}'}


def _tcp(host: str, port: int) -> tuple[str, str]:
    try:
        with socket.create_connection((host, port), timeout=CONNECT):
            return 'free', ''
    except socket.gaierror:
        return 'missing', 'the host name is not known'
    except ConnectionRefusedError:
        return 'missing', 'nothing answers on its port'
    except (OSError, UnicodeError):
        return 'missing', 'cannot be reached'


def reach(dev: dict) -> tuple[str, str]:
    """The default reachability check: ('free', '') or ('missing', why). No secret is used."""
    if dev['kind'] == 'ssh':
        if not dev.get('alias'):
            return _tcp(dev['host'], dev['port'])
        try:
            r = sp.run(['ssh', '-G', '--', dev['alias']], stdin=sp.DEVNULL, capture_output=True, text=True, timeout=CONNECT)
        except (OSError, sp.SubprocessError):
            return 'unknown', 'ssh does not read its config'
        got = dict(l.split(' ', 1) for l in r.stdout.splitlines() if ' ' in l)
        if got.get('proxyjump', 'none') != 'none' or got.get('proxycommand', 'none') != 'none':
            try:
                scan(dev)
                return 'free', ''
            except Refused as e:
                return 'missing', str(e)
        return _tcp(got.get('hostname') or dev['alias'], int(got.get('port') or SSH_PORT))
    where = dev['reach']
    m = re.fullmatch(r'(?:([a-z]+)://)?(?:[^@/\s]*@)?(\[[0-9a-fA-F:]+\]|[A-Za-z0-9][A-Za-z0-9.-]*)(?::(\d{1,5}))?(/\S*)?', where)
    if m and (m[1] or m[3]):
        port = int(m[3] or PORTS.get(m[1] or '', 0))
        return _tcp(m[2].strip('[]'), port) if 0 < port < 65536 else ('unknown', 'its address names no port to check')
    try:
        first = shlex.split(where)[0]
    except (ValueError, IndexError):
        return 'unknown', 'its command cannot be read'
    if shutil.which(os.path.expanduser(first)):
        return 'free', ''
    if m and not first.startswith(('/', '~', '.')) and '.' in first:
        return 'unknown', 'its address names no port to check'
    return 'missing', f'{first[:60]} is not on this machine'


# --- a device's web page (F407, device_page.py) ----------------------------------------------------------------------

PAGE_LINES, PAGE_WIDTH = 20, 300  # what is shown of a failed command's output


def _page_dir(dev: dict) -> Path:
    """The folder of its start command: named by an id, so it stays with a renamed device."""
    return state_dir() / 'pages' / dev['page_id']


def page_state(dev: dict) -> dict | None:
    """{'state': running, stopped or failed, 'lines': what a failed one printed last}; None with no start command."""
    from agent_runner import device_page
    if not dev.get('page_id'):
        return None
    s = device_page.state(d := _page_dir(dev))
    return {'state': s, 'lines': _page_lines(d) if s == 'failed' else []}


_LINES: dict[str, tuple[tuple, list[str]]] = {}  # by log: a Tools page that is open asks every 10 s, and the keyring is slow


def _page_lines(d: Path) -> list[str]:
    """The last lines, every device's stored secrets hidden in them. None are shown when one cannot be read."""
    from agent_runner import device_page
    try:
        saved = state_dir() / 'devices.json'  # none where only runner.toml has a tool
        stamp = tuple((s.st_mtime_ns, s.st_size) for s in (d.joinpath('log').stat(), *([saved.stat()] if saved.exists() else [])))
        if (hit := _LINES.get(str(d))) and hit[0] == stamp:
            return hit[1]
        hide = _all_secrets()
    except OSError:
        return []
    except Refused:
        return [NOT_SHOWN]
    got = _clean_lines(device_page.tail(d), hide)
    _LINES[str(d)] = stamp, got
    return got


NOT_SHOWN = '(the output is not shown: a stored secret that may be in it cannot be read now)'


def _all_secrets() -> list[str]:
    return [v for n, dev in load()['devices'].items() for w in dev.get('secrets') or {} if w in SECRETS
            and (v := _secret(n, w, dev))]


def _clean_lines(data: bytes, hide: list[str]) -> list[str]:
    text = Redactor(hide).all(data)
    text = re.sub(rb'\x1b\[[0-9;?]*[A-Za-z]|[\x00-\x08\x0b-\x1f\x7f]', b'', text)
    text = Redactor(hide).all(text).decode('utf-8', 'replace')  # again: colours may have stood inside one
    got = [l[:PAGE_WIDTH] for l in text.split('\n') if l.strip()]
    return got[-PAGE_LINES:]


def hidden_lines(data: bytes) -> list[str]:
    """The last lines of a command's output, every device's stored secrets hidden in them (F428c)."""
    try:
        return _clean_lines(data, _all_secrets())
    except Refused:
        return [NOT_SHOWN] if data.strip() else []


def _page_end(dev: dict) -> bool:
    """Stop a device's command for good and forget its output; whether it was running. Refused when it does not stop."""
    from agent_runner import device_page
    if not dev.get('page_id'):
        return False
    d = _page_dir(dev)
    was = device_page.state(d) == 'running'
    if not device_page.stop(d):
        raise Refused('its web page is still running and did not stop; try again')
    shutil.rmtree(d, ignore_errors=True)
    return was


TOML = 'runner.toml'  # the `source` of a shared tool of the project's, as GET /tools has it


def _toml_tools(c) -> dict[str, dict]:
    """[run.tools] as the main checkout's runner.toml has it now: no worktree's, no other file's."""
    from agent_runner.config import _load
    try:
        tools = (_load(Path(project(c), TOML)).get('run') or {}).get('tools')
    except (OSError, ValueError, AttributeError):
        return {}
    return {n: t for n, t in tools.items() if isinstance(t, dict)} if isinstance(tools, dict) else {}


def tool_page(c, name: str, t: dict | None = None) -> dict:
    """F428a: the web page of a shared tool in runner.toml, as a device with one has it: {page, start, folder, page_id},
    {} without one. Its folder goes by project and name, so a changed or removed `start` still has its command ended."""
    from agent_runner import device_page
    t, root = _toml_tools(c).get(name) if t is None else t, project(c)
    try:
        from agent_runner.config import tools_problem
        dev = {} if not t or tools_problem({name: t}) else tool_fields(t)
    except Refused:
        dev = {}
    pid = 'toml-' + hashlib.sha256(f'{root}\0{name}'.encode()).hexdigest()[:16]
    if dev.get('start') or device_page.state(state_dir() / 'pages' / pid) == 'running':
        dev = {**dev, 'folder': root, 'page_id': pid}
    return dev


def tool_pages(c) -> dict[str, dict]:
    """{name: `tool_page`} of the shared tools in runner.toml that have a web page, or a command still running."""
    return {n: dev for n, t in _toml_tools(c).items() if (dev := tool_page(c, n, t))}


def _paged(name, source: str, c) -> dict:
    """What has the web page: the device `name`, or the runner.toml tool. With no `source`, the device when there is one."""
    if c and isinstance(name, str) and (source == TOML or (not source and name not in load()['devices'])):
        if dev := tool_page(c, name):
            return dev
        if source == TOML or name in _toml_tools(c):
            raise Refused(f'{name} has no start command')
    return _get(load(), name)


def _page_command(name, source: str, c, key: str) -> dict:
    dev = _paged(name, source, c)
    if not dev.get(key):
        raise Refused(f'{name} has no start command')
    return dev


def page_start(name: str, source: str = '', c=None) -> dict:
    """Start the command a person saved for `name`, once: {ok, out, state, lines}."""
    from agent_runner import device_page
    with _locked():
        dev = _page_command(name, source, c, 'start')
        try:
            cwd = Path(dev.get('folder') or '~').expanduser()
            fresh = device_page.start(_folder('pages', dev['page_id']), dev['start'], cwd)
        except OSError:
            raise Refused(f'the web page of {name} did not start') from None
    if not fresh:
        return {'ok': True, 'out': f'{name} is running already', 'state': 'running', 'lines': []}
    device_page.settled(_page_dir(dev))
    r = page_state(dev)
    return {'ok': r['state'] == 'running', **r,
            'out': f'{name} is running' if r['state'] == 'running' else f'{name} ended at once ({r["state"]})'}


def page_stop(name: str, source: str = '', c=None) -> dict:
    """Stop what `page_start` started, whatever the start command is now."""
    from agent_runner import device_page
    with _locked():
        dev = _page_command(name, source, c, 'page_id')
        was = device_page.state(_page_dir(dev)) == 'running'
        if not device_page.stop(_page_dir(dev)):
            raise Refused(f'{name} did not stop; try again')
    return {'ok': True, 'out': f'{name} is stopped' if was else f'{name} is not running', **page_state(dev)}


def need_pages(line: str, c) -> list[dict]:
    """F408: the devices with a web page that a task's first line needs: [{name, page, state}], '' for a page with no
    start command. No output is read: a snapshot asks this every few seconds."""
    from agent_runner import device_page, shared_tools
    if ' | needs: ' not in line:
        return []
    specs, devs = shared_tools.specs(c), used(c)
    return [{'name': n, 'page': dev['page'], 'state': device_page.state(_page_dir(dev)) if dev.get('start') else ''}
            for n in shared_tools.needs_of(line, c) if specs[n].get('device') and (dev := devs.get(n)) and dev.get('page')]


def _page_words(dev: dict) -> str:
    r = page_state(dev)
    return dev.get('page', 'removed from runner.toml') + (f' ({r["state"]})' if r else '')


# --- who has it ----------------------------------------------------------------------------------------------------------

def _running(root: str) -> dict[str, str]:
    """{slot: task} of the run up at `root`; {} while none is."""
    from agent_runner.config import cfg
    try:
        c = cfg(Path(root))
        f = c.notes('run.lock')
        if not f.exists():
            return {}
        if held := plat.lock(f):
            held.close()
            return {}
        return dict(json.loads(c.notes('STATE').read_text(encoding='utf-8')).get('running') or {})
    except (OSError, ValueError, SystemExit):
        return {}


def _lease(name: str) -> dict:
    try:
        d = json.loads((state_dir() / 'held' / name).read_text(encoding='utf-8'))
        return d if isinstance(d, dict) and d.get('tid') and d.get('root') else {}
    except (OSError, ValueError):
        return {}


def holder(name: str, own: str) -> tuple[str, str] | None:
    """(project folder, task) that has an only-one-task device now: the task that took it with `run device`, while its
    session runs, or another project's running task that needs it."""
    if (h := _lease(name)) and h['tid'] in _running(h['root']).values():
        return h['root'], h['tid']
    from agent_runner import plan as P
    from agent_runner.config import cfg
    for root, names in load()['uses'].items():
        if root == own or name not in names or not (live := set(_running(root).values())):
            continue
        try:
            for _, _, tid, _, i in P.iter_tasks(ls := P.lines(cfg(Path(root)).todo)):
                if tid in live and name in P.fields(ls[i]).get('needs', []):
                    return root, tid
        except (OSError, SystemExit):
            continue
    return None


def check(name: str, c) -> tuple[str, str]:
    """A device's answer to `shared_tools.check`."""
    dev = used(c).get(name)
    if not dev:
        return 'unknown', 'the device is gone'
    if dev.get('exclusive') and (h := holder(name, project(c))):
        # another project's task is named without its id: here that id is another task's
        return 'busy', h[1] if h[0] == project(c) else f'a task of {Path(h[0]).name}'
    return reach(dev)


def take(name: str, dev: dict, c) -> str:
    """An agent's use of an only-one-task device: '' when it has it now, else who does."""
    from agent_runner import plan as P, shared_tools
    from agent_runner.tools import task_here
    if not dev.get('exclusive'):
        return ''
    slot, own = os.environ.get('AGENT_RUNNER_SLOT'), project(c)
    tid = task_here() if slot else ''
    with _locked():
        h = holder(name, own)
        if not h:
            live = set(_running(own).values()) - {tid}
            ls = P.lines(c.todo)
            h = next(((own, t) for _, _, t, _, i in P.iter_tasks(ls)
                      if t in live and (name in shared_tools.needs_of(ls[i], c) or shared_tools.holding(t) == name)), None)
        if h and h != (own, tid):
            return h[1] if h[0] == own else f'a task of {Path(h[0]).name}'
        if tid:
            _write(_folder('held') / name, json.dumps({'root': own, 'tid': tid, 'at': time.time()}).encode())
    return ''


# --- the Tools page --------------------------------------------------------------------------------------------------------

def _loopback(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr.split('%')[0])
        return (getattr(ip, 'ipv4_mapped', None) or ip).is_loopback
    except ValueError:
        return False


def _local_host(host: str) -> bool:
    name = urlsplit(f'//{host}').hostname or ''
    return name == 'localhost' or name.endswith('.localhost') or _loopback(name)


def channel(peer: str, headers, write: bool = True, behind: bool = False) -> str:
    """Whether a request may carry a secret: '' (it came over https or loopback and, for a write, from this page),
    'http' or 'origin'. `behind`: Runner Home's own verdict is taken, from a loopback peer only."""
    if not _loopback(peer):
        return 'http'
    if behind and (v := headers.get(CHANNEL)) is not None:
        return '' if v == 'ok' else v if v in ('http', 'origin') else 'http'
    proto = (headers.get('X-Forwarded-Proto') or '').strip().lower()
    proxied = any(headers.get(k) for k in ('X-Forwarded-For', 'X-Forwarded-Host', 'Forwarded', 'Via', 'X-Real-Ip'))
    host = (headers.get('Host') or '').lower()
    if proto != 'https' and (proto or proxied or not _local_host(host)):
        return 'http'
    if not write:
        return ''
    origin = urlsplit((headers.get('Origin') or '').lower())
    hosts = {host, (headers.get('X-Forwarded-Host') or host).lower()} if proto == 'https' else {host}
    if origin.scheme != (proto or 'http') or origin.netloc not in hosts:
        return 'origin'
    return '' if (headers.get('Sec-Fetch-Site') or 'same-origin') == 'same-origin' else 'origin'


def https_link() -> str:
    """The run app's https address, on its Tools page; '' when there is none."""
    return next((u for u in _links() if u.startswith('https://')), '')


def _links() -> list[str]:
    from agent_runner import state as S, web
    try:
        us = web.https_first(web.site_urls() or web.own_links(web.url_file().read_text(encoding='utf-8').split()))
        return [u + '#tools' for u in us]
    except (OSError, ValueError, AttributeError):
        return []


def tools_link() -> str:
    """The Tools page's address, an https one when there is one ('' while no run app is up)."""
    us = _links()
    return https_link() or (us[0] if us else '')


def refusal(why: str) -> dict:
    if why == 'origin':
        return {'ok': False, 'out': 'Refused: that did not come from this page. Reload it and try again.'}
    u = https_link()
    return {'ok': False, 'https': u, 'out': 'Devices and secrets are saved only over https or on the machine itself.'
            + (' Open the https link.' if u else ' There is no https link yet: Tailscale Serve gives one.')}


def _shown(name: str, dev: dict, uses: list[str]) -> dict:
    """A device as the page has it: what is set, never a secret."""
    out = {k: dev[k] for k in ('kind', 'description', 'exclusive', 'alias', 'host', 'user', 'port', 'reach', 'page', 'start',
                               'folder', 'buttons') if k in dev}
    hk = dev.get('hostkey')
    return {**out, 'run': page_state(dev), 'name': name, 'label': name, 'source': 'device', 'used': name in uses,
            'hostkey': {'fp': hk['fp'], 'type': hk['type'], 'changed': hk.get('changed', '')} if hk else None,
            'secrets': {w: {k: m[k] for k in ('changed', 'fp', 'pub') if k in m} for w, m in (dev.get('secrets') or {}).items()
                        if w in SECRETS}}


def _tool_shown(dev: dict | None) -> dict:
    return {**{k: dev[k] for k in ('page', 'start') if k in dev}, 'run': page_state(dev)} if dev else {}


def page(c, why: str = '') -> dict:
    """GET /tools: every tool and device, F168's state of each, and whether this page may save."""
    from agent_runner import shared_tools, tool_buttons, tool_forms
    d = load()
    states = {r['name']: r for r in shared_tools.rows(checked=True)}
    toml = c.run.get('tools') or {}
    uses, pages, buttons = d['uses'].get(project(c), []), tool_pages(c), tool_buttons.in_toml(c)
    out = [{'name': n, 'label': t.get('label') or n, 'description': t.get('description', ''), 'source': TOML,
            'check': t['check'], 'exclusive': True, 'used': True, **_tool_shown(pages.get(n)),
            **({'buttons': buttons[n]} if n in buttons else {})} for n, t in toml.items()]
    out += [_shown(n, dev, uses) for n, dev in d['devices'].items()]
    for t in out:
        r = states.get(t['name']) if t['used'] and not (t['source'] == 'device' and t['name'] in toml) else None
        t.update(state=r['state'] if r else '', words=r['words'] if r else '' if t['used'] else 'not used by this project',
                 at=r['at'] if r else 0)
    return {'ok': True, 'tools': out, 'aliases': aliases(), 'secure': not why,
            'https': https_link() if why else '', 'windows': plat.WINDOWS,
            'stored': str(state_dir()), 'logins': tool_forms.logins(), 'terminals': _terminals()}


def _terminals() -> int:
    """F466d: how many Tools page terminals are open."""
    from agent_runner import tools_terminal
    return tools_terminal.count()


def _value(a: dict, what: str) -> str:
    v = a.get(what)
    if not isinstance(v, str) or not v.strip():
        raise Refused(f'the {WORDS[what]} is empty')
    if what == 'key':
        if len(v) > 32768:
            raise Refused('that is too long for a private key')
        v = v.replace('\r\n', '\n').replace('\r', '\n').strip() + '\n'
        if not re.fullmatch(r'-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----\n[^\x00]*\n-----END [A-Z0-9 ]*PRIVATE KEY-----\n', v):
            raise Refused('that is not a private key: paste the whole file, from BEGIN to END')
        return v
    v = v.rstrip('\r\n')
    if len(v) > 1024 or re.search(r'[\x00\r\n]', v):
        raise Refused(f'the {WORDS[what]} is one line, 1024 characters at most')
    return v


def _get(d: dict, name) -> dict:
    dev = d['devices'].get(name) if isinstance(name, str) else None
    if not dev:
        raise Refused('there is no such device')
    return dev


def _put_key(name: str, dev: dict, key: str, phrase: str, pub: str) -> None:
    s = dev.setdefault('secrets', {})
    old = s.get('passphrase')
    s['key'] = {'store': _keep(name, 'key', key, s.get('key')), 'changed': today(), 'fp': fingerprint(pub.split()[1]),
                'pub': pub}
    if phrase:
        s['passphrase'] = {'store': _keep(name, 'passphrase', phrase, old), 'changed': today()}
    elif old:
        _drop(name, 'passphrase', s.pop('passphrase'))


def _free_name(name, d: dict, c, but: str = '') -> None:
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise Refused('the name is letters, digits, - and _, not a dash first, 40 at most')
    if name.lower() == 'memory' or name in (c.run.get('tools') or {}):
        raise Refused('that name is taken by a shared tool')
    if name.lower() in {n.lower() for n in d['devices'] if n != but}:
        raise Refused('there is a device with that name')


def _not_in_use(name: str) -> None:
    if (h := _lease(name)) and h['tid'] in _running(h['root']).values():
        raise Refused(f'a task of {Path(h["root"]).name} uses it now')


def _rename(old: str, new: str, d: dict, c) -> None:
    """The device and its secrets under a new name. A task's `needs:` keeps the name it has."""
    _free_name(new, d, c, old)
    _not_in_use(old)
    dev = d['devices'].pop(old)
    values = {w: _secret(old, w, dev) for w in dev.get('secrets') or {}}
    for w, v in values.items():
        was = dict(dev['secrets'][w])
        dev['secrets'][w]['store'] = _keep(new, w, v, None)
        if _file(old, w) != _file(new, w):
            _drop(old, w, was)
    d['devices'][new] = dev
    d['uses'] = {r: [new if n == old else n for n in ns] for r, ns in d['uses'].items()}
    (state_dir() / 'held' / old).unlink(missing_ok=True)


def _page_id(dev: dict) -> dict:
    return {**dev, 'page_id': os.urandom(8).hex()} if dev.get('start') else dev


def op_save(a: dict, c) -> dict:
    """Add a device, or edit one (`edit`: its name). A new place to connect to forgets the accepted host key."""
    from agent_runner import tool_buttons
    name, edit = a.get('name'), a.get('edit')
    new, more = checked(a), {}
    if 'buttons' in a:  # F428c: a page that does not send them leaves them as they are
        more = {'buttons': bs} if (bs := tool_buttons.checked(a['buttons'])) else {}
    with _edit() as d:
        if edit:
            old = _get(d, edit)
            moved = any(old.get(k) != new.get(k) for k in WHERE)
            kept = {k: old[k] for k in ('secrets', 'hostkey', *(() if 'buttons' in a else ('buttons',))) if k in old}
            if moved:
                kept.pop('hostkey', None)
            ended = False
            if all(old.get(k) == new.get(k) for k in ('start', 'folder')):
                kept.update({k: old[k] for k in ('page_id',) if k in old})
            else:  # F407: another command, or none: the old one is stopped first
                if name not in (None, '', edit):  # what would refuse the save comes before that
                    _free_name(name, d, c, edit)
                    _not_in_use(edit)
                ended = _page_end(old)
            if new['kind'] == 'other' or new.get('alias'):
                for w, m in (kept.pop('secrets', None) or {}).items():
                    _drop(edit, w, m)
            d['devices'][edit] = {**_page_id(new), **more, **kept}
            if name not in (None, '', edit):
                _rename(edit, name, d, c)
                edit = name
            return {'out': f'{edit} is saved' + ('; its old command was stopped' if ended else '') + ('; test it to accept its host key' if moved and new['kind'] == 'ssh' else '')}
        _free_name(name, d, c)
        d['devices'][name] = {**_page_id(new), **more}
        d['uses'].setdefault(project(c), []).append(name)
    return {'out': f'{name} is added, and this project uses it'}


def op_remove(a: dict, c) -> dict:
    with _edit() as d:
        dev, name = _get(d, a.get('name')), a['name']
        _not_in_use(name)
        _page_end(dev)
        for w in SECRETS:
            _drop(name, w, (dev.get('secrets') or {}).get(w))
        (state_dir() / 'held' / name).unlink(missing_ok=True)
        del d['devices'][name]
        d['uses'] = {r: ns for r, v in d['uses'].items() if (ns := [n for n in v if n != name])}
    return {'out': f'{name} is removed, its secrets too'}


def op_use(a: dict, c) -> dict:
    with _edit() as d:
        _get(d, a.get('name'))
        name, names = a['name'], d['uses'].setdefault(project(c), [])
        if a.get('on') is True:
            if name in (c.run.get('tools') or {}):
                raise Refused('runner.toml has a shared tool with that name')
            if name not in names:
                names.append(name)
        elif name in names:
            names.remove(name)
        on = name in names
    return {'out': f'This project {"uses" if on else "does not use"} {name}'}


def op_test(a: dict, c) -> dict:
    dev = _get(load(), a.get('name'))
    r = test(a['name'], dev)
    if seen := r.pop('seen', None):
        with _edit() as d:  # what the person may accept: exactly the key they were shown
            now = _get(d, a['name'])
            if any(now.get(k) != dev.get(k) for k in WHERE):
                raise Refused('the device was edited meanwhile; test the connection again')
            now['offered'] = seen
    return r


def op_accept(a: dict, c) -> dict:
    with _edit() as d:
        dev = _get(d, a.get('name'))
        seen = dev.get('offered')
        if not seen or seen['fp'] != a.get('fp'):
            raise Refused('that fingerprint is not the one the device showed; test the connection again')
        dev['hostkey'] = {**seen, 'changed': today()}
        del dev['offered']
    r = test(a['name'], load()['devices'][a['name']])
    r.pop('seen', None)
    return {**r, 'out': 'Fingerprint accepted. ' + r['out']}


def _ssh_own(dev: dict) -> None:
    if dev['kind'] != 'ssh' or dev.get('alias'):
        raise Refused('only an SSH device with its own host has secrets here')
    need_sockets()


def op_secret(a: dict, c) -> dict:
    """Set or replace a secret: key (with its passphrase, if it has one), passphrase, or password."""
    what = a.get('what')
    if what not in SECRETS:
        raise Refused('a secret is a key, a passphrase or a password')
    value = _value(a, what)
    with _edit() as d:
        dev, name = _get(d, a.get('name')), a['name']
        _ssh_own(dev)
        s = dev.setdefault('secrets', {})
        if what == 'password':
            s['password'] = {'store': _keep(name, 'password', value, s.get('password')), 'changed': today()}
        else:
            if what == 'key':
                key, phrase = value, _value(a, 'passphrase') if a.get('passphrase') else ''
            else:
                key, phrase = _secret(name, 'key', dev), value
                if not key:
                    raise Refused('there is no private key to open with it')
            with _tmp() as tmp, _agent(tmp, key, phrase) as (_, pub):
                pass
            if what == 'key':
                _put_key(name, dev, key, phrase, pub)
            else:
                s['passphrase'] = {'store': _keep(name, 'passphrase', phrase, s.get('passphrase')), 'changed': today()}
    return {'out': f'The {WORDS[what]} of {a["name"]} is set'}


def op_unsecret(a: dict, c) -> dict:
    what = a.get('what')
    if what not in SECRETS:
        raise Refused('a secret is a key, a passphrase or a password')
    with _edit() as d:
        dev, name = _get(d, a.get('name')), a['name']
        s = dev.get('secrets') or {}
        for w in ('key', 'passphrase') if what == 'key' else (what,):
            _drop(name, w, s.pop(w, None))
    return {'out': f'The {WORDS[what]} of {a["name"]} is removed'}


def op_keypair(a: dict, c) -> dict:
    """Make a key pair here; only its public key is ever shown."""
    with _edit() as d:
        dev, name = _get(d, a.get('name')), a['name']
        _ssh_own(dev)
        with tempfile.TemporaryDirectory(dir=str(_folder()), prefix='.key-') as t:
            try:
                r = sp.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-C', '', '-f', str(Path(t, 'k'))],
                           stdin=sp.DEVNULL, capture_output=True, timeout=PROBE)
            except (OSError, sp.SubprocessError):
                raise Refused('ssh-keygen did not make a key') from None
            if r.returncode:
                raise Refused('ssh-keygen did not make a key')
            pub = ' '.join(Path(t, 'k.pub').read_text().split()[:2])
            _put_key(name, dev, Path(t, 'k').read_text(), '', pub)
    return {'out': 'A key pair is made. Add its public key to ~/.ssh/authorized_keys on the device.'}


def _source(a: dict) -> str:
    """Which of a device and a runner.toml tool with one name a press is for, as GET /tools names it."""
    if (s := a.get('source') or '') not in ('', 'device', TOML):
        raise Refused('there is no such device')
    return s


def op_start(a: dict, c) -> dict:
    return page_start(a.get('name'), _source(a), c)


def op_stop(a: dict, c) -> dict:
    return page_stop(a.get('name'), _source(a), c)


def op_press(a: dict, c) -> dict:
    from agent_runner import tool_buttons
    return tool_buttons.press(a, c)


OPS = {'save': op_save, 'remove': op_remove, 'use': op_use, 'test': op_test, 'accept': op_accept,
       'start': op_start, 'stop': op_stop, 'press': op_press, 'secret': op_secret, 'unsecret': op_unsecret, 'keypair': op_keypair}


def post(body: bytes, c) -> tuple[int, dict]:
    """POST /tools. The caller has checked the token and `channel`. No answer, and no error, holds what was sent."""
    try:
        from agent_runner import tool_forms  # F466b: the Login and Custom tool forms
        a = json.loads(body)
        from agent_runner import tools_terminal  # F466d: the Tools page's terminal
        op = {**OPS, **tool_forms.OPS, **tools_terminal.OPS}[a.pop('op')]
    except (ValueError, KeyError, TypeError, AttributeError):
        return 400, {'ok': False, 'out': 'bad request'}
    try:
        return 200, {'ok': True, **op(a, c)}
    except Refused as e:
        return 200, {'ok': False, 'out': str(e)}
    except Exception as e:  # noqa: BLE001 - the type alone: an error's text may hold what was sent
        return 200, {'ok': False, 'out': f'that failed on the machine ({type(e).__name__})'}


# --- the agents' command -------------------------------------------------------------------------------------------------

def how(name: str, dev: dict, runner: str) -> str:
    if dev['kind'] == 'other':
        return dev['reach'] + (f' (first: {runner} device take {name})' if dev.get('exclusive') else '')
    return f'{runner} device ssh {name} -- CMD'


def brief(runner: str, c) -> str:
    """The slot brief's paragraph; '' when the project uses no device."""
    if not (devs := used(c)):
        return ''
    lines = [f'- `{n}`{" (one task at a time)" if d.get("exclusive") else ""}: {d.get("description") or "no description"} '
             f'Reach it with: `{how(n, d, runner)}`' for n, d in devs.items()]
    return ('Devices you may use:\n' + '\n'.join(lines) + '\nThe runner signs in to an SSH device itself: '
            f'`{runner} device ssh NAME -- CMD`, and `{runner} device copy FROM TO` (one of them NAME:path; -r for a '
            f'folder). Never ask for a key or password, look for one, or ssh around it. When you are done with a '
            f'one-task device before your task ends, `{runner} device release NAME`.')


def _run(argv: list[str], env: dict, hide: list[str]) -> tuple[int, bytes]:
    """Run ssh or scp, its output passed on with the secrets hidden: (exit code, the end of its stderr)."""
    p = sp.Popen(argv, env=env, stdout=sp.PIPE, stderr=sp.PIPE)
    tail = [b'']

    def stop(*_):
        p.terminate()
        raise SystemExit(143)
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGTERM, stop)

    def pump(src, dst) -> None:
        red = Redactor(hide)
        while True:
            data = os.read(src.fileno(), 65536)
            out = red.feed(data) if data else red.end()
            if dst is sys.stderr:
                tail[0] = (tail[0] + out)[-4000:]
            with contextlib.suppress(OSError, ValueError):
                dst.buffer.write(out)
                dst.flush()
            if not data:
                return
    ts = [threading.Thread(target=pump, args=x, daemon=True) for x in ((p.stdout, sys.stdout), (p.stderr, sys.stderr))]
    for t in ts:
        t.start()
    try:
        rc = p.wait()
    except KeyboardInterrupt:
        p.terminate()
        rc = 130
    for t in ts:
        t.join(5)
    return rc, tail[0]


def _side(s: str, devs: dict) -> tuple[str, str]:
    """A copy's side: (device, path), or ('', the local path)."""
    n, sep, path = s.partition(':')
    return (n, path) if sep and n in devs else ('', s)


def cmd_device(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog='run device', description='The devices this project uses (the run app\'s Tools page).')
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('list', help='every device this project uses')
    sub.add_parser('link', help="the Tools page's address, where a person adds devices and secrets")
    for n, h in (('show', 'one device'), ('start', "run the start command of a device's web page"),
                 ('stop', 'stop what start started'),
('take', 'have a one-task device until your task ends'), ('release', 'a one-task device is free for other tasks again')):
        sub.add_parser(n, help=h).add_argument('name')
    s = sub.add_parser('ssh', help='run a command on a device')
    s.add_argument('name')
    s.add_argument('words', nargs='*', metavar='-- CMD', help='one word: text for its shell; more: each as it is')
    p = sub.add_parser('copy', help='copy to or from a device')
    p.add_argument('-r', action='store_true', dest='deep', help='a folder')
    p.add_argument('src', metavar='FROM')
    p.add_argument('dst', metavar='TO')
    words = []
    if argv[:1] == ['ssh'] and argv[1:2] not in ([], ['-h'], ['--help']):  # argparse has ideas of its own about --
        argv, words = argv[:2], argv[2:]
        words = words[1:] if words[:1] == ['--'] else words
    a = ap.parse_args(argv)
    from agent_runner import state as S
    from agent_runner.config import RUNNER, cfg, main_checkout
    c = cfg(main_checkout())
    if S.C is None:
        S.init(c.root)
    devs, tools = used(c), tool_pages(c)

    def fail(why: str, rc: int = 2) -> int:
        print(f'run device: {why}', file=sys.stderr)
        return rc
    if a.cmd == 'link':
        if not (u := tools_link()):
            return fail('no run app is up, so there is no Tools page', 1)
        print(u)
        return 0
    if a.cmd == 'list':
        for n, d in devs.items():
            print(f'{n}: {d.get("description") or "no description"} ({how(n, d, RUNNER)})'
                  + (f'; web page {_page_words(d)}' if d.get('page') else ''))
        for n, d in tools.items():
            print(f'{n}: a shared tool in {TOML}; web page {_page_words(d)}')
        if not devs and not tools:
            print('This project uses no device. A person adds one on the Tools page.')
        return 0
    if a.cmd == 'copy':
        (n1, p1), (n2, p2) = _side(a.src, devs), _side(a.dst, devs)
        if bool(n1) == bool(n2):
            return fail('one of FROM and TO is NAME:path, a device this project uses')
        name = n1 or n2
    else:
        name = a.name
    paged = a.cmd in ('show', 'start', 'stop') and (name in tools or (name in _toml_tools(c) and name not in devs))
    if paged or (a.cmd == 'stop' and name not in devs and tool_page(c, name)):  # F428a: as everywhere, over a device
        dev = tools.get(name) or tool_page(c, name)
    elif name not in devs:
        return fail(f'this project uses no device named {name}; it uses: {", ".join(devs) or "none"}')
    else:
        dev = devs[name]
    if a.cmd == 'show':
        if paged:
            print(f'{name}: {_toml_tools(c)[name].get("description") or "no description"}\nA shared tool in {TOML}')
        else:
            print(f'{name}: {dev.get("description") or "no description"}\nReach it with: {how(name, dev, RUNNER)}')
        if dev.get('page') or (paged and dev):
            print('\n'.join([f'Web page: {_page_words(dev)}', *((page_state(dev) or {}).get('lines') or [])]))
        return 0
    if a.cmd in ('start', 'stop'):
        try:
            r = (page_start if a.cmd == 'start' else page_stop)(name, 'device' if dev is devs.get(name) else TOML, c)
        except Refused as e:
            return fail(str(e), 1)
        if not r['ok']:
            return fail('\n'.join([r['out'], *r['lines']]), 1)
        print(r['out'] + (f': {dev["page"]}' if a.cmd == 'start' else ''))
        return 0
    if a.cmd == 'release':
        from agent_runner.tools import task_here
        h = _lease(name)
        if h and (h['root'], h['tid']) != (project(c), task_here()):
            return fail(f'{name} is held by another task', 1)
        (state_dir() / 'held' / name).unlink(missing_ok=True)
        print(f'{name} is free')
        return 0
    if a.cmd == 'take':
        try:
            who = take(name, dev, c)
        except Refused as e:
            return fail(str(e), 1)
        if who:
            return fail(f'{name} is held by {who}: `{RUNNER} wait-for {name}` gives up your slot until it is free', 75)
        print(f'{name} is yours')
        return 0
    if a.cmd == 'ssh' and not words:
        return fail('say the command: run device ssh NAME -- CMD')
    try:
        if who := take(name, dev, c):
            return fail(f'{name} is held by {who}: `{RUNNER} wait-for {name}` gives up your slot until it is free', 75)
        with session(name, dev) as (opts, env, hide):
            if a.cmd == 'ssh':
                argv = ['ssh', *opts, '-T', '--', _dest(dev), words[0] if len(words) == 1 else shlex.join(words)]
            else:
                host = f'[{_dest(dev)}]' if ':' in _dest(dev) else _dest(dev)
                both = [f'{host}:{x}' if n else os.path.abspath(x) for n, x in ((n1, p1), (n2, p2))]
                argv = ['scp', *opts, *(['-r'] if a.deep else []), '--', *both]
            try:
                rc, err = _run(argv, env, hide)
            except OSError:
                return fail(f'{argv[0]} is not installed on this machine', 1)
    except Refused as e:
        return fail(str(e), 1)
    if rc == 255 and b'host key verification failed' in err.lower():
        u = tools_link()
        return fail(f'refused: the host key of {name} is not the one a person accepted ({dev["hostkey"]["fp"]}). It may '
                    f'be another machine. A person looks at it on the Tools page{": " + u if u else ""}.', 255)
    return rc
