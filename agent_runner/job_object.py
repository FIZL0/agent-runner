"""B798: runs one command in a Windows job object, so ending this process ends all the command started.

    python -I -S job_object.py COMMAND [ARG ...]

`taskkill /T` follows parent pids, and an MSYS (Git Bash) child whose Windows parent is gone has none to follow. Every
process of the command is in the job, which Windows ends with the job's last handle, that is when this process is
killed. When the call ends by itself the job lets go first, so what it left in the background goes on.

The harness loop (harness.mjs) starts it by its path, for a bash tool call on Windows; nothing here imports the rest
of the runner."""
from __future__ import annotations

import os
import shutil
import subprocess as sp
import sys
import time

KILL_ON_JOB_CLOSE = 0x2000
NO_JOB = 47798  # exit code: no job could be made, so nothing was started (harness.mjs then runs the command itself)
EXTENDED_LIMITS = 9  # JobObjectExtendedLimitInformation


def quoted(args: list[str]) -> str:
    """`args` as one command line, every one in quotes: MSYS expands an unquoted `*`, which `list2cmdline` leaves so."""
    out = []
    for a in args:
        s, slashes = '', 0
        for c in a:
            if c == '\\':
                slashes += 1
                continue
            s += '\\' * (slashes * 2 + 1 if c == '"' else slashes) + c
            slashes = 0
        out.append('"' + s + '\\' * (slashes * 2) + '"')
    return ' '.join(out)


class Job:
    """A job object this process is in, and so is all it starts; `ok` is False where Windows would not make one."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes

        class Limits(ctypes.Structure):  # JOBOBJECT_EXTENDED_LIMIT_INFORMATION
            _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64), ('flags', wintypes.DWORD),
                        ('min_set', ctypes.c_size_t), ('max_set', ctypes.c_size_t), ('processes', wintypes.DWORD),
                        ('affinity', ctypes.c_size_t), ('priority', wintypes.DWORD), ('scheduling', wintypes.DWORD),
                        ('io', ctypes.c_uint64 * 6), ('process_memory', ctypes.c_size_t),
                        ('job_memory', ctypes.c_size_t), ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]

        self._limits, self._ctypes = Limits, ctypes
        k = self._k = ctypes.WinDLL('kernel32', use_last_error=True)
        k.CreateJobObjectW.restype = wintypes.HANDLE
        k.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        k.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k.GetCurrentProcess.restype = wintypes.HANDLE
        self._h = k.CreateJobObjectW(None, None)  # not inheritable: this process has the one handle
        self.ok = bool(self._h and self._set(KILL_ON_JOB_CLOSE)
                       and k.AssignProcessToJobObject(self._h, k.GetCurrentProcess()))

    def _set(self, flags: int) -> bool:
        limits = self._limits(flags=flags)
        return bool(self._k.SetInformationJobObject(self._h, EXTENDED_LIMITS, self._ctypes.byref(limits),
                                                    self._ctypes.sizeof(limits)))

    def let_go(self):
        """What is left in the job goes on when this process ends."""
        self._set(0)


def main(argv: list[str]) -> int:
    exe = shutil.which(argv[0])  # on PATH: CreateProcess would look in System32 first, where `bash` is WSL's
    if not exe:
        print(f'{argv[0]}: not found on PATH', file=sys.stderr)
        return 127
    job = Job()
    if not job.ok:
        return NO_JOB
    p = sp.Popen(quoted(argv), executable=exe, stdin=0, stdout=sp.PIPE, stderr=sp.STDOUT)
    # read to its end, not the command's: a background child with the output holds the call, so a stop must reach it too
    while data := os.read(p.stdout.fileno(), 65536):
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()
    code = p.wait()
    if code == 1:  # maybe taskkill's, on its way up a tree this process is in (a chat closed from outside): its turn is next
        time.sleep(0.3)
    job.let_go()
    return code - 2 ** 32 if code >= 2 ** 31 else code


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
