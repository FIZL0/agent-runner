"""Everything the runner does that depends on the operating system, in one place.

The rest of the runner calls these and never asks which OS it is on. POSIX keeps exactly what the runner
always did (`os.kill`, `/proc`, `pgrep`, `flock`, a new session for a detached process, symlinks); Windows
gets the native equivalent from the standard library and `ctypes` only (no psutil):

    alive / children      OpenProcess + GetExitCodeProcess; a CreateToolhelp32Snapshot of parent pids
    terminate             `taskkill /T /F` (no SIGTERM, and the agent may be a .cmd wrapper around node)
    spawn_detached        DETACHED_PROCESS + a new process group (+ breakaway from a job when allowed)
    spawn_console         a new console window (CREATE_NEW_CONSOLE), the fallback without Windows Terminal
    lock                  msvcrt.locking on one byte, which goes with the handle however the process ends
    link                  a symlink; failing that (no Developer Mode) a junction for a directory, a hard link
                          for a file
    quote / command_text  cmd.exe-safe quoting instead of POSIX quoting

Windows-only modules (`msvcrt`, `ctypes.wintypes`) are imported inside the functions, so importing this
module on Linux never reaches them, and its POSIX half is what the tests run.

(Not `platform.py`: that name belongs to the standard library.)
"""
from __future__ import annotations

import os
import shlex
import shutil
import signal
import subprocess as sp
import sys
from pathlib import Path

WINDOWS = sys.platform.startswith('win')

# process creation flags (winbase.h)
DETACHED_PROCESS = 0x00000008
CREATE_NEW_CONSOLE = 0x00000010
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_BREAKAWAY_FROM_JOB = 0x01000000


# --- processes ---------------------------------------------------------------

def alive(pid: int | None) -> bool:
    """Is `pid` a live process? A zombie (POSIX) counts as dead."""
    if not pid:
        return False
    if WINDOWS:
        import ctypes
        from ctypes import wintypes
        k = ctypes.WinDLL('kernel32', use_last_error=True)
        k.OpenProcess.restype = wintypes.HANDLE
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        h = k.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return ctypes.get_last_error() == 5  # access denied: it exists, it is somebody else's
        code = wintypes.DWORD()
        try:
            return not k.GetExitCodeProcess(h, ctypes.byref(code)) or code.value == 259  # STILL_ACTIVE
        finally:
            k.CloseHandle(h)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:  # a zombie answers kill(0) too
        return Path(f'/proc/{pid}/stat').read_text().split(')')[-1].split()[0] != 'Z'
    except OSError:
        return True


def _snapshot() -> list[tuple[int, int, str]]:
    """(pid, parent pid, image name) of every process (Windows): `tasklist` cannot give a parent pid."""
    import ctypes
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD),
                    ('th32ProcessID', wintypes.DWORD), ('th32DefaultHeapID', ctypes.c_void_p),
                    ('th32ModuleID', wintypes.DWORD), ('cntThreads', wintypes.DWORD),
                    ('th32ParentProcessID', wintypes.DWORD), ('pcPriClassBase', ctypes.c_long),
                    ('dwFlags', wintypes.DWORD), ('szExeFile', wintypes.WCHAR * 260)]

    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    snap = k.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
    if snap == wintypes.HANDLE(-1).value:
        return []
    e = PROCESSENTRY32W()
    e.dwSize = ctypes.sizeof(e)
    out = []
    try:
        ok = k.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            out.append((int(e.th32ProcessID), int(e.th32ParentProcessID), str(e.szExeFile)))
            ok = k.Process32NextW(snap, ctypes.byref(e))
    finally:
        k.CloseHandle(snap)
    return out


def children(pid: int) -> list[int]:
    """Direct children of `pid`: a session with one is running a tool, not sitting at its prompt."""
    if not pid:
        return []
    if WINDOWS:
        try:
            return [p for p, parent, _ in _snapshot() if parent == int(pid)]
        except OSError:
            return []
    return [int(p) for p in sp.run(['pgrep', '-P', str(pid)], capture_output=True, text=True).stdout.split()]


def cmdline(pid: int) -> list[str] | None:
    """The argv of `pid` (POSIX, from /proc), or None. Windows has no stdlib way to read another process's
    command line; the Windows terminals keep each session's argv in their job file instead."""
    try:
        return Path(f'/proc/{pid}/cmdline').read_text().split('\0')
    except OSError:
        return None


def terminate(pid: int) -> None:
    """End a session: SIGTERM on POSIX; on Windows the whole tree, by force (there is no SIGTERM, and a
    console process that is not ours gets no Ctrl+Break from a detached waiter)."""
    if WINDOWS:
        sp.run(['taskkill', '/T', '/F', '/PID', str(pid)], capture_output=True)
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass


def spawn_detached(argv: list[str]) -> None:
    """Start a process that outlives this one and every terminal around it (the Stop hook's timer)."""
    kw: dict = dict(stdin=sp.DEVNULL, stdout=sp.DEVNULL, stderr=sp.DEVNULL)
    if not WINDOWS:
        sp.Popen(argv, start_new_session=True, **kw)
        return
    # Claude Code may run hooks in a job that is killed with them: break away when the job allows it
    flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    try:
        sp.Popen(argv, creationflags=flags | CREATE_BREAKAWAY_FROM_JOB, **kw)
    except OSError:
        sp.Popen(argv, creationflags=flags, **kw)


def spawn_console(argv: list[str], cwd: Path, env: dict) -> int:
    """Start `argv` in a console window of its own (Windows); returns its pid."""
    return sp.Popen(argv, cwd=str(cwd), env=env,
                    creationflags=CREATE_NEW_CONSOLE | CREATE_NEW_PROCESS_GROUP).pid


def exe(name: str) -> str:
    """The program to start for `name`. Windows' CreateProcess finds only `.exe` on PATH by itself, and an
    npm-installed agent is `claude.cmd`, so it is looked up with PATHEXT; POSIX keeps the bare name."""
    return (shutil.which(name) or name) if WINDOWS else name


# --- files -------------------------------------------------------------------

def lock(path: Path):
    """Take an exclusive lock on `path` without waiting; the open file holds it (keep it), or None when
    another process has it. It goes with the process, however that ends."""
    f = open(path, 'a+')
    try:
        if WINDOWS:
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    return f


def link(src: Path, dst: Path) -> bool:
    """Put `src` at `dst` without copying it; True if something is there now.

    A symlink where the OS allows one. On Windows that takes Developer Mode or an elevated process, which
    an unattended run cannot assume, so a directory gets a junction (`mklink /J`, no privilege needed) and
    a file a hard link (same volume, which a worktree beside the repo is).
    """
    try:
        dst.symlink_to(src)
        return True
    except OSError:
        pass
    if WINDOWS:
        if src.is_dir():
            if not sp.run(['cmd', '/c', 'mklink', '/J', str(dst), str(src)], capture_output=True).returncode:
                return True
        else:
            try:
                os.link(src, dst)
                return True
            except OSError:
                pass
    return dst.exists()


# --- command lines -----------------------------------------------------------

def quote(s: str) -> str:
    """One argument quoted for the shell `shell=True` runs: sh on POSIX, cmd.exe on Windows."""
    return sp.list2cmdline([s]) if WINDOWS else shlex.quote(s)


def command_text(argv: list[str]) -> str:
    """The runner's own command (an interpreter, a script, flags) as text a session or a hook types.

    Windows: every word double-quoted with forward slashes, which both Git Bash (what Claude Code runs
    hooks and Bash calls in) and cmd.exe read the same way. Unquoted backslashes would vanish in Bash, and
    POSIX single quotes mean nothing to cmd.exe. Only for paths and plain flags, never for free text.
    """
    if not WINDOWS:
        return shlex.join(argv)
    return ' '.join(f'"{a}"' if any(c in a for c in ' &()^%!') else a for a in (x.replace('\\', '/') for x in argv))


# --- terminals ---------------------------------------------------------------

def mux_choice(slots: int, want: str, tmux_ok: bool, wt_ok: bool, windows: bool = WINDOWS) -> str:
    """Which terminal a run puts its sessions in: 'sequential', 'tmux', 'wt' or 'console'.

    One slot and `want == 'none'` (`--no-tmux`) are the sequential run whatever is installed. `want` is
    `[run] mux`: '' (auto) picks tmux on POSIX, and on Windows a Windows Terminal tab when wt.exe is
    there, else a console window per slot. Asking for one that is not available falls back to sequential
    rather than to a different terminal than the one asked for.
    """
    if want == 'none' or slots <= 1:
        return 'sequential'
    if want:
        ok = {'tmux': tmux_ok, 'wt': windows and wt_ok, 'console': windows}.get(want, False)
        return want if ok else 'sequential'
    if windows:
        return 'wt' if wt_ok else 'console'
    return 'tmux' if tmux_ok else 'sequential'


def power_off() -> int:
    """Shut the computer down now; the command's exit code (non-zero: refused, e.g. no permission)."""
    if WINDOWS:
        cmd = ['shutdown', '/s', '/t', '0']
    elif sys.platform == 'darwin':
        cmd = ['osascript', '-e', 'tell app "System Events" to shut down']
    else:
        cmd = ['systemctl', 'poweroff']
    try:
        return sp.run(cmd).returncode
    except OSError:
        return 127
