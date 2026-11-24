"""B121: control sessions that a shutdown or reboot ended come back on run start.

A control session outlives the run, but not the machine. Control session N keeps its conversation in control<N>.sid and its pid file ("pid sid"). On run start each N whose pid
file is still there while its process is gone, and was written before this boot, was live at the shutdown: it is
reopened with `control N --reopen` (--resume <its sid>, under the name it had). One closed on purpose stays
closed: closing it (idle, B26; closed online, B53) removes its pid file, one closed online while the machine was
off is told by its transcript, and one whose process ended during this boot (the person quit it) is forgotten, by
the run loop while it is up (`forget_ended_controls`) and here.

Not one of the FAMILY modules `share` reaches, so the run's settings (ROOT, C, MUX) are read through their
modules at call time."""

from __future__ import annotations

import re
import subprocess as sp
import sys
import time

from agent_runner import control as K, control_harness, control_held, plat, state
from agent_runner.config import runner_cmd


def boot_time() -> float:
    """When this machine last booted (epoch seconds): Linux /proc/stat, macOS kern.boottime, Windows
    GetTickCount64; 0 where unknown."""
    if plat.WINDOWS:
        try:
            import ctypes
            tick = ctypes.windll.kernel32.GetTickCount64
            tick.restype = ctypes.c_ulonglong
            return time.time() - tick() / 1000
        except (OSError, AttributeError):
            return 0.0
    try:
        with open('/proc/stat', encoding='utf-8') as fh:
            for line in fh:
                if line.startswith('btime '):
                    return float(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    if sys.platform == 'darwin':
        try:
            out = sp.run(['sysctl', '-n', 'kern.boottime'], capture_output=True, text=True, timeout=5).stdout
        except (OSError, sp.SubprocessError):
            out = ''
        if m := re.search(r'\bsec\s*=\s*(\d+)', out):
            return float(m[1])
    return 0.0


def ended_control_numbers() -> list[int]:
    """The numbers N with a control<N>.pid whose process is gone."""
    out = []
    for f in state.C.notes().glob('control*.pid'):
        if (m := re.fullmatch(r'control(\d+)\.pid', f.name)) and not K.control_live(int(m[1])):
            out.append(int(m[1]))
    return sorted(out)


def control_shut_down(n: int, booted: float) -> bool:
    """Whether ended control session `n` was live at the last shutdown: its pid file predates this boot (an
    unknown boot time, 0, counts every ended one)."""
    try:
        return not booted or state.C.notes(f'control{n}.pid').stat().st_mtime < booted
    except OSError:
        return False


def forget_control(n: int, why: str) -> None:
    """Control session `n` stays closed: its pid file goes, so `reopen_controls` passes it by."""
    sid = K.control_kept_sid(n)
    control_held.look(n)  # B170: what it holds for a usage limit outlives its pid file
    state.C.notes(f'control{n}.pid').unlink(missing_ok=True)
    state.log(f'control {n}: not reopened, {why}' +
              (f' (transcript kept: {control_harness.resume_hint(sid)})' if sid else ''))


def forget_ended_controls(booted: float | None = None) -> list[int]:
    """Forget the control sessions whose process ended during this boot (the person quit them), so a later
    run start does not reopen them. The numbers forgotten."""
    booted = boot_time() if booted is None else booted
    if not booted:
        return []
    out = [n for n in ended_control_numbers() if not control_shut_down(n, booted)]
    for n in out:
        forget_control(n, 'it ended while the machine was up')
    return out


def controls_to_reopen(booted: float | None = None) -> list[tuple[int, str]]:
    """[(N, sid)] of the control sessions live at the last shutdown, to reopen; the other ended ones are
    forgotten (`forget_control`)."""
    booted = boot_time() if booted is None else booted
    out = []
    for n in ended_control_numbers():
        sid = K.control_kept_sid(n)
        if n < K.FIRST_CONTROL:  # F176
            forget_control(n, 'it was the chat an older runner kept')
        elif not control_shut_down(n, booted):
            forget_control(n, 'it ended while the machine was up')
        elif not sid or not K.transcript(sid):
            forget_control(n, 'its transcript is gone')
        elif K.closed_online(K.entries(sid, skip_bad=True)):
            forget_control(n, 'its Remote Control session was closed online')
        elif not control_harness.resumable(sid):  # F406f
            forget_control(n, '[models] control is another kind of agent now, which cannot read its conversation')
        else:
            out.append((n, sid))
    return out


def reopen_name(n: int, sid: str) -> str:
    """The name a reopened control session `n` (conversation `sid`) gets back: the one the person gave it in the
    apps, else the one the runner last gave it (`control_given`), else "<repo> · control N"."""
    try:
        st = K.control_state(K.entries(sid, skip_bad=True)) if sid and K.transcript(sid) else {}
    except Exception:
        st = {}
    if st and K.control_renamed(st, n):
        return st['title']
    return K.control_given(n) or K.control_name(n)


def reopen_control(n: int, sid: str) -> str:
    """Start `control N --reopen`: a hidden terminal, or a hidden console on Windows
    with no ConPTY. Where it went, or '' when it could not start."""
    if bad := K.agent_held():  # B764c
        state.log(f'control {n}: not reopened: {bad}')
        return ''
    cmd = [*runner_cmd(), 'control', str(n), '--reopen']
    if plat.WINDOWS and not plat.has_conpty():
        plat.spawn_console(cmd, state.ROOT, K.control_env(), hidden=True)
        return 'a hidden console'
    pid, why = K.hidden_control(n, cmd)
    if not pid:
        state.log(f'control {n}: could not reopen it hidden: {why}')
        return ''
    return f'a hidden terminal (its output in {K.hidden_control_log(n)})'


def reopen_controls() -> list[int]:
    """On run start, reopen every control session c2+ a shutdown ended (see above). The numbers reopened."""
    out = []
    for n, sid in controls_to_reopen():
        if where := reopen_control(n, sid):
            state.log(f'control {n}: reopened after a shutdown in {where} (--resume {sid})')
            out.append(n)
    return out
