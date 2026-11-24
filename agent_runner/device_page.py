"""F407: the start command of a device's web page: started detached, stopped, and whether it is running.

`start` leaves a keeper (`keep`), a process of its own that runs the command in a process group of the command's own,
and holds `lock` in the command's folder for as long as any of that group is left. So the lock, not a pid, says it is
running, whichever run or session asks, and `stop` asks the keeper (the file `stop`): it ends the group it started
itself, never one found by a pid on disk. Only when a keeper was killed is the group reached by the pid in run.json,
and then only when that process is proven to be the one it started (`_orphan`).

A folder holds lock, stop, run.json and log, all of one device's command. This module knows no device and no secret:
devices.py says which command, has one caller at a time, and hides stored secrets in what `tail` gives.
"""
from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess as sp
import sys
import time
from pathlib import Path

from agent_runner import plat

TICK = 0.2        # s between a keeper's looks
TERM = 4          # s a group has to end by itself before it is killed
UP = 7            # s a keeper may take to start the command
SETTLE = 1        # s a command must live for its start to have worked
LOG_MAX, LOG_KEEP = 1 << 20, 1 << 16  # bytes the log may have, and what is kept of a longer one
KEEPER = ('import sys; sys.path.insert(0, sys.argv[1]); from pathlib import Path; from agent_runner import device_page; '
          'device_page.keep(Path(sys.argv[2]))')


def _record(d: Path) -> dict:
    try:
        r = json.loads((d / 'run.json').read_text(encoding='utf-8'))
        return r if isinstance(r, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(d: Path, rec: dict) -> None:
    tmp = d / 'run.json.new'
    with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w', encoding='utf-8') as f:
        json.dump(rec, f)
    os.replace(tmp, d / 'run.json')


def _boot() -> str:
    """This boot of the machine ('' where the OS doesn't say): a pid and its start time name a process of one boot."""
    try:
        return Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    except OSError:
        return ''


def _held(d: Path) -> bool:
    """A keeper has the lock. Another look at it holds it for an instant, so one refusal is not believed."""
    if not (d / 'lock').exists():
        return False
    for _ in range(4):
        if f := plat.lock(d / 'lock'):
            f.close()
            return False
        time.sleep(0.02)
    return True


def _orphan(rec: dict) -> int:
    """The pid of a command whose keeper was killed, when it is surely that command; else 0."""
    pid, start = rec.get('pid'), rec.get('start')
    if 'end' in rec or not pid or not start or rec.get('boot') != _boot():
        return 0
    if plat.alive(pid):
        return pid if plat.started(pid) == start else 0
    return pid if _marked(pid, rec.get('mark') or '') else 0


MARK = 'AGENT_RUNNER_PAGE_MARK'  # in the command's environment: one start's own random word


def _marked(pgid: int, mark: str) -> bool:
    """Some process left in group `pgid`, whose leader is gone, has the mark: the group is that start's (a group id is
    not used again while the group has a process)."""
    for p in Path('/proc').iterdir() if mark else ():
        with contextlib.suppress(OSError, ValueError, IndexError):
            if p.name.isdigit() and int((p / 'stat').read_text().rsplit(')', 1)[1].split()[2]) == pgid \
                    and f'{MARK}={mark}'.encode() in (p / 'environ').read_bytes().split(b'\0'):
                return True
    return False


def state(d: Path) -> str:
    """'running', 'stopped' or 'failed'."""
    if _held(d) or _orphan(rec := _record(d)):
        return 'running'
    if not rec or rec.get('stopped') or rec.get('end') == 0:
        return 'stopped'
    # no end: the keeper was killed, or the machine went down, which is no failure of the command's
    return 'failed' if 'end' in rec or rec.get('boot') == _boot() else 'stopped'


def tail(d: Path) -> bytes:
    """The end of what the command printed, whole lines. Raw: the caller hides secrets in it."""
    try:
        with open(d / 'log', 'rb') as f:
            size = f.seek(0, os.SEEK_END)
            f.seek(max(0, size - LOG_KEEP))
            data = f.read()
    except OSError:
        return b''
    return data if size <= LOG_KEEP else data.partition(b'\n')[2]


# --- start and stop ------------------------------------------------------------------------------------------------

def _scope() -> list[str]:
    """What takes a process out of the service it would be started in (Runner Home's): systemd ends all of a stopped
    service's processes. [] when this is in none, or systemd does not do it."""
    if not sys.platform.startswith('linux'):
        return []
    try:
        if not Path('/proc/self/cgroup').read_text().strip().endswith('.service'):
            return []
        argv = ['systemd-run', '--user', '--scope', '--quiet', '--collect', '--']
        r = sp.run([*argv, 'true'], stdin=sp.DEVNULL, capture_output=True, timeout=2)
        return argv if r.returncode == 0 else []
    except (OSError, sp.SubprocessError):
        return []


def start(d: Path, cmd: str, cwd: Path) -> bool:
    """Start `cmd`, once: False when it is running already. Raises OSError when the keeper does not come up."""
    if state(d) == 'running':
        return False
    (d / 'stop').unlink(missing_ok=True)
    (d / 'log').unlink(missing_ok=True)
    _write(d, {'cmd': cmd, 'cwd': str(cwd), 'boot': _boot(), 'mark': os.urandom(8).hex()})
    p = plat.spawn_detached([*_scope(), sys.executable, '-c', KEEPER, str(Path(__file__).resolve().parents[1]), str(d)],
                            cwd=Path.home())
    end = time.monotonic() + UP
    while not {'pid', 'end'} & _record(d).keys():
        if time.monotonic() > end or p.poll() is not None:
            if {'pid', 'end'} & _record(d).keys():
                break
            (d / 'stop').touch()  # a late keeper starts nothing
            _write(d, {**_record(d), 'stopped': True, 'end': 0})
            raise OSError('the keeper did not start')
        time.sleep(0.05)
    return True


def settled(d: Path) -> str:
    """The state just after a start, once a command that ends at once has ended."""
    end = time.monotonic() + SETTLE
    while (s := state(d)) == 'running' and time.monotonic() < end:
        time.sleep(0.05)
    return s


def _group(pid: int) -> bool:
    """Some process of the group `pid` led is left."""
    try:
        os.killpg(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except OSError:
        return True


def _end(pid: int, left) -> None:
    """End a command's group: asked to, then killed. `left()`: whether some of it is left."""
    if plat.WINDOWS:
        return plat.terminate(pid)
    for sig, wait in ((signal.SIGTERM, TERM), (signal.SIGKILL, 2)):
        if not left():
            return
        with contextlib.suppress(OSError):
            os.killpg(pid, sig)
        end = time.monotonic() + wait
        while left() and time.monotonic() < end:
            time.sleep(0.05)


def stop(d: Path) -> bool:
    """Stop the command; False when it is still running."""
    if not d.is_dir():
        return True
    if _held(d):
        (d / 'stop').touch()
        end = time.monotonic() + TERM + 4
        while _held(d) and time.monotonic() < end:
            time.sleep(0.05)
    elif pid := _orphan(rec := _record(d)):
        _end(pid, lambda: _group(pid))
        if not _group(pid):
            _write(d, {**rec, 'end': 0, 'stopped': True})
    return state(d) != 'running'


# --- the keeper ------------------------------------------------------------------------------------------------------

def _env() -> dict:
    """The command's environment: none of a run's, a slot's or a session's markers, but a no-push policy stays."""
    return {k: v for k, v in os.environ.items() if k == 'AGENT_RUNNER_NO_PUSH'
            or not k.startswith(('AGENT_RUNNER', 'AGENT_SLOT', 'CLAUDECODE', 'CLAUDE_CODE_'))}


def _trim(log: Path) -> None:
    with contextlib.suppress(OSError):
        if log.stat().st_size > LOG_MAX:
            with open(log, 'r+b') as f:  # the command appends, so it goes on at the new end
                f.seek(-LOG_KEEP, os.SEEK_END)
                data = f.read().partition(b'\n')[2]  # whole lines, or half a secret would not be hidden
                f.seek(0)
                f.truncate()
                f.write(data)


def keep(d: Path) -> None:
    """The keeper: run the folder's command until its group is gone, or a stop is asked for."""
    asked: list[int] = []
    for s in ('SIGHUP', 'SIGINT'):
        if hasattr(signal, s):
            signal.signal(getattr(signal, s), signal.SIG_IGN)
    signal.signal(signal.SIGTERM, lambda *_: asked.append(1))
    end = time.monotonic() + 2
    while not (held := plat.lock(d / 'lock')):
        if time.monotonic() > end:
            return
        time.sleep(0.02)
    rec, log = _record(d), d / 'log'
    if (d / 'stop').exists() or 'cmd' not in rec:
        return
    out = open(os.open(log, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600), 'ab', buffering=0)
    argv = rec['cmd'] if plat.WINDOWS else ['/bin/sh', '-c', rec['cmd']]
    kw = {'creationflags': plat.CREATE_NO_WINDOW | plat.CREATE_NEW_PROCESS_GROUP, 'shell': True} if plat.WINDOWS \
        else {'start_new_session': True, 'preexec_fn': _plain_signals}
    try:
        p = sp.Popen(argv, cwd=rec['cwd'], stdin=sp.DEVNULL, stdout=out, stderr=out, env={**_env(), MARK: rec['mark']}, **kw)
    except OSError as e:
        out.write(f'{e.strerror or type(e).__name__}\n'.encode())
        _write(d, {**rec, 'end': 127})
        return
    rec.update(pid=p.pid, start=plat.started(p.pid), boot=_boot())
    _write(d, rec)

    def left() -> bool:
        return p.poll() is None or (not plat.WINDOWS and _group(p.pid))
    while left():
        if asked or (d / 'stop').exists():
            asked.append(1)
            _end(p.pid, left)  # what it cannot end goes on, kept, and is ended again at the next look
        _trim(log)
        time.sleep(TICK)
    _write(d, {**rec, 'end': p.returncode, 'stopped': bool(asked)})
    held.close()


def _plain_signals() -> None:
    """The command takes the signals its keeper ignores."""
    signal.signal(signal.SIGHUP, signal.SIG_DFL)
    signal.signal(signal.SIGINT, signal.SIG_DFL)
