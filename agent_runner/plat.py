"""Everything the runner does that depends on the operating system, in one place.

The rest of the runner calls these and never asks which OS it is on. POSIX keeps exactly what the runner
always did (`os.kill`, `/proc`, `pgrep`, `flock`, a new session for a detached process, symlinks); Windows
gets the native equivalent from the standard library and `ctypes` only (no psutil):

    alive / children      OpenProcess + GetExitCodeProcess; a CreateToolhelp32Snapshot of parent pids
    terminate             WM_CLOSE to the windows of the process tree (an emulator saves and exits), a short
                          wait, then `taskkill /T /F` (no SIGTERM; the agent may be a .cmd around node)
    spawn_detached        CREATE_NO_WINDOW + a new process group (+ breakaway from a job when allowed)
    spawn_console         a new console (CREATE_NEW_CONSOLE) whose window starts hidden: a slot, a control session
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
import re
import shlex
import shutil
import signal
import subprocess as sp
import sys
import time
from pathlib import Path

WINDOWS = sys.platform.startswith('win')

# process creation flags (winbase.h)
CREATE_NO_WINDOW = 0x08000000  # a console with no window; children inherit it
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


def started(pid: int) -> str | None:
    """When `pid` started, in clock ticks since boot (Linux /proc), or None where the OS doesn't say: with the
    pid it names one process, which a pid alone stops doing once the pid is reused."""
    try:
        return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]
    except (OSError, IndexError):
        return None


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
    """The argv of `pid` (POSIX from /proc, Windows from the process itself), or None when it cannot be read."""
    if WINDOWS:
        import ctypes
        try:
            return _windows_cmdline(int(pid))
        except (OSError, AttributeError, ValueError, TypeError, ctypes.ArgumentError):
            return None
    try:
        return Path(f'/proc/{pid}/cmdline').read_text().split('\0')
    except OSError:
        return None


def _windows_cmdline(pid: int) -> list[str] | None:
    """The argv of `pid` (Windows 8.1+): NtQueryInformationProcess(ProcessCommandLineInformation) gives the
    command line, split the way the C runtime does by CommandLineToArgvW. None when the process cannot be opened
    (gone, or another user's)."""
    import ctypes
    from ctypes import wintypes

    class UNICODE_STRING(ctypes.Structure):
        _fields_ = [('Length', wintypes.USHORT), ('MaximumLength', wintypes.USHORT), ('Buffer', ctypes.c_void_p)]

    k = ctypes.WinDLL('kernel32', use_last_error=True)
    nt = ctypes.WinDLL('ntdll')
    sh = ctypes.WinDLL('shell32', use_last_error=True)
    k.OpenProcess.restype = wintypes.HANDLE
    k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    k.LocalFree.argtypes = [ctypes.c_void_p]
    nt.NtQueryInformationProcess.restype = ctypes.c_long
    nt.NtQueryInformationProcess.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.ULONG,
                                             ctypes.POINTER(wintypes.ULONG)]
    sh.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
    sh.CommandLineToArgvW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    h = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return None
    try:
        size = wintypes.ULONG(0)
        nt.NtQueryInformationProcess(h, 60, None, 0, ctypes.byref(size))  # ProcessCommandLineInformation
        if not size.value:
            return None
        buf = ctypes.create_string_buffer(size.value)
        if nt.NtQueryInformationProcess(h, 60, buf, size, ctypes.byref(size)) != 0:
            return None
        us = UNICODE_STRING.from_buffer(buf)
        line = ctypes.wstring_at(us.Buffer, us.Length // 2) if us.Buffer and us.Length else ''
    finally:
        k.CloseHandle(h)
    if not line:
        return []
    argc = ctypes.c_int(0)
    argv = sh.CommandLineToArgvW(line, ctypes.byref(argc))
    if not argv:
        return [line]
    try:
        return [argv[i] for i in range(argc.value)]
    finally:
        k.LocalFree(argv)


CLOSE_GRACE = 10.0  # seconds a windowed process in the tree gets to close itself before the force kill


def descendants(pid: int) -> list[int]:
    """Every process below `pid` (Windows), children first."""
    try:
        procs = _snapshot()
    except OSError:
        return []
    out, todo = [], [int(pid)]
    while todo:
        kids = [p for p, parent, _ in procs if parent == todo[0] and p not in out and p != int(pid)]
        out += kids
        todo = todo[1:] + kids
    return out


def _windows_of(pid: int) -> list[int]:
    """Visible top-level window handles owned by `pid` (Windows)."""
    import ctypes
    from ctypes import wintypes
    u = ctypes.WinDLL('user32', use_last_error=True)
    out: list[int] = []
    CB = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def seen(hwnd, _):
        owner = wintypes.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and u.IsWindowVisible(hwnd):
            out.append(int(hwnd))
        return True

    u.EnumWindows(CB(seen), 0)
    return out


def _post_close(hwnd: int) -> None:
    import ctypes
    from ctypes import wintypes
    ctypes.WinDLL('user32').PostMessageW(wintypes.HWND(hwnd), 0x0010, 0, 0)  # WM_CLOSE


def terminate(pid: int) -> None:
    """End a session: SIGTERM on POSIX. Windows has no SIGTERM, so first every process in the tree that has
    a window gets WM_CLOSE (an emulator then saves and shuts down as if its window were closed), the
    tree gets up to CLOSE_GRACE seconds for those to exit, and then `taskkill /T /F` ends whatever is
    left, the session itself included (a console process that is not ours gets no Ctrl+Break)."""
    if WINDOWS:
        closing = []
        for p in [int(pid)] + descendants(pid):
            hwnds = _windows_of(p)
            for h in hwnds:
                _post_close(h)
            if hwnds:
                closing.append(p)
        end = time.monotonic() + CLOSE_GRACE
        while closing and time.monotonic() < end:
            closing = [p for p in closing if alive(p)]
            if closing:
                time.sleep(0.25)
        sp.run(['taskkill', '/T', '/F', '/PID', str(pid)], capture_output=True)
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass


def spawn_detached(argv: list[str], out: Path | None = None) -> sp.Popen:
    """Start a process that outlives this one and every terminal around it (the Stop hook's timer, the
    background run on Windows). `out`: a file its output goes to, else nowhere."""
    f = open(out, 'ab') if out else sp.DEVNULL
    kw: dict = dict(stdin=sp.DEVNULL, stdout=f, stderr=f if out else sp.DEVNULL)
    try:
        if not WINDOWS:
            return sp.Popen(argv, start_new_session=True, **kw)
        # Claude Code may run hooks in a job that is killed with them: break away when the job allows it.
        # Not DETACHED_PROCESS: uv's Scripts\python.exe is a launcher, and the python it starts would get a
        # new console of its own, shown on screen; CREATE_NO_WINDOW's windowless console is inherited instead
        flags = CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
        try:
            return sp.Popen(argv, creationflags=flags | CREATE_BREAKAWAY_FROM_JOB, **kw)
        except OSError:
            return sp.Popen(argv, creationflags=flags, **kw)
    finally:
        if out:
            f.close()


STARTF_USESHOWWINDOW = 0x00000001
SW_HIDE, SW_RESTORE = 0, 9


def hidden_startupinfo():
    """A STARTUPINFO whose window starts hidden (SW_HIDE). The process still gets a real console, so the agent
    in it has a TTY; only the window is not shown. (A stand-in object off Windows, for the tests.)"""
    si = sp.STARTUPINFO() if hasattr(sp, 'STARTUPINFO') else type('STARTUPINFO', (), {'dwFlags': 0, 'wShowWindow': 0})()
    si.dwFlags |= STARTF_USESHOWWINDOW
    si.wShowWindow = SW_HIDE
    return si


def spawn_console(argv: list[str], cwd: Path, env: dict, hidden: bool = False) -> int:
    """Start `argv` in a console window of its own (Windows); returns its pid. `hidden`: the window starts
    hidden (the background run); `show_console` brings it up."""
    kw = {'startupinfo': hidden_startupinfo()} if hidden else {}
    return sp.Popen(argv, cwd=str(cwd), env=env,
                    creationflags=CREATE_NEW_CONSOLE | CREATE_NEW_PROCESS_GROUP, **kw).pid


def show_console(pid: int) -> bool:
    """Show and raise the console window `pid` runs in (Windows); False when there is none to show. A console
    window belongs to its host (conhost), not to the program, so it is found by attaching to that process's
    console. A process can attach to one console only, and giving up our own would break this terminal's
    output, so a helper with no console of its own does it (`_show_console`)."""
    code = (f'import sys; sys.path.insert(0, {str(Path(__file__).resolve().parents[1])!r}); '
            f'from agent_runner import plat; sys.exit(0 if plat._show_console({int(pid)}) else 1)')
    return sp.run([sys.executable, '-c', code], creationflags=CREATE_NO_WINDOW).returncode == 0


def _show_console(pid: int) -> bool:
    import ctypes
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    u = ctypes.WinDLL('user32', use_last_error=True)
    k.GetConsoleWindow.restype = ctypes.c_void_p
    k.FreeConsole()  # its own windowless console (CREATE_NO_WINDOW): one console per process
    if not k.AttachConsole(int(pid)) or not (hwnd := k.GetConsoleWindow()):
        return False
    u.ShowWindow(ctypes.c_void_p(hwnd), SW_RESTORE)
    u.SetForegroundWindow(ctypes.c_void_p(hwnd))
    return True


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
    POSIX single quotes mean nothing to cmd.exe. Only for paths and plain flags, never for free text. Inside
    the quotes `$` and a backtick get a backslash, for Bash (cmd.exe keeps it; a Windows path rarely has either).
    """
    if not WINDOWS:
        return shlex.join(argv)
    return ' '.join('"' + re.sub(r'([$`])', r'\\\1', a) + '"' if any(c in a for c in ' &()^%!\'$`;') else a
                    for a in (x.replace('\\', '/') for x in argv))


def suspend() -> int:
    """Suspend (sleep) the computer now; the command's exit code (non-zero: refused). It returns at once, the
    sleep follows.
    On Windows SetSuspendState hibernates instead where hibernation is on."""
    if WINDOWS:
        cmd = ['rundll32.exe', 'powrprof.dll,SetSuspendState', '0,1,0']
    elif sys.platform == 'darwin':
        cmd = ['pmset', 'sleepnow']
    else:
        cmd = ['systemctl', 'suspend']
    try:
        return sp.run(cmd).returncode
    except OSError:
        return 127


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
