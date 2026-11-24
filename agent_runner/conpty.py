"""Windows: a ConPTY pseudo-console for a hidden session (`slots.run_conpty`), and the named pipe its typed input
comes in by. Standard library only (`ctypes`); Windows 10 1809 and later (`plat.has_conpty`).

There is no os.mkfifo on Windows, so `<notes>/slotN.in` is a small file that holds the name of a named pipe. The
pipe's access list names this user alone, it refuses other machines, and its name is random. `InPipe` is the
shim's end of it; `pipe_send` is a sender's (`slots.send_fifo`).

Windows-only modules are imported inside the functions, so this module imports anywhere.
"""
from __future__ import annotations

import os
import queue
import secrets
import subprocess as sp
import threading
import time
from pathlib import Path

SEND_WAIT = 10.0  # s a sender waits for the shim to take its bytes, as `send_fifo` does


def _kernel32():
    import ctypes
    from ctypes import wintypes as w
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    H, P, D = w.HANDLE, ctypes.c_void_p, w.DWORD
    for name, res, args in (
            ('CloseHandle', w.BOOL, [H]),
            ('CreatePipe', w.BOOL, [P, P, P, D]),
            ('ReadFile', w.BOOL, [H, P, D, P, P]),
            ('WriteFile', w.BOOL, [H, P, D, P, P]),
            ('CreatePseudoConsole', ctypes.c_long, [w._COORD, H, H, D, P]),
            ('ResizePseudoConsole', ctypes.c_long, [H, w._COORD]),
            ('ClosePseudoConsole', None, [H]),
            ('InitializeProcThreadAttributeList', w.BOOL, [P, D, D, P]),
            ('UpdateProcThreadAttribute', w.BOOL, [P, D, ctypes.c_size_t, P, ctypes.c_size_t, P, P]),
            ('DeleteProcThreadAttributeList', None, [P]),
            ('CreateProcessW', w.BOOL, [w.LPCWSTR, P, P, P, w.BOOL, D, P, w.LPCWSTR, P, P]),
            ('WaitForSingleObject', D, [H, D]),
            ('GetExitCodeProcess', w.BOOL, [H, P]),
            ('GetCurrentProcess', H, []),
            ('OpenThread', H, [D, w.BOOL, D]),
            ('CancelSynchronousIo', w.BOOL, [H]),
            ('CreateNamedPipeW', H, [w.LPCWSTR, D, D, D, D, D, D, P]),
            ('ConnectNamedPipe', w.BOOL, [H, P]),
            ('DisconnectNamedPipe', w.BOOL, [H]),
            ('LocalFree', P, [P])):
        f = getattr(k, name)
        f.restype, f.argtypes = res, args
    return k


def _error() -> OSError:
    import ctypes
    return ctypes.WinError(ctypes.get_last_error())


def _read(k, h) -> bytes:
    """What a pipe holds next, waiting for it; b'' once its other end is closed (or the wait is cancelled)."""
    import ctypes
    from ctypes import wintypes
    buf, n = ctypes.create_string_buffer(65536), wintypes.DWORD()
    return buf.raw[:n.value] if k.ReadFile(h, buf, len(buf), ctypes.byref(n), None) else b''


def _join(k, t: threading.Thread, seconds: float) -> bool:
    """End thread `t`, which may be waiting in a read: its wait is cancelled until it has ended. False when it
    still runs after `seconds`."""
    end = time.monotonic() + seconds
    while t.is_alive() and time.monotonic() < end:
        if h := k.OpenThread(0x0001, False, t.ident):  # THREAD_TERMINATE, which CancelSynchronousIo asks for
            k.CancelSynchronousIo(h)
            k.CloseHandle(h)
        t.join(0.05)
    return not t.is_alive()


class ConPty:
    """`argv` started in a pseudo-console of `size` (rows, columns). `pid` is its process; `on_output` gets what
    the console prints, on a thread of its own. OSError when it cannot be started."""

    def __init__(self, argv: list[str], cwd: str, env: dict, size: tuple[int, int], on_output) -> None:
        import ctypes
        from ctypes import wintypes as w

        class STARTUPINFOEXW(ctypes.Structure):
            _fields_ = [('cb', w.DWORD), ('lpReserved', w.LPWSTR), ('lpDesktop', w.LPWSTR), ('lpTitle', w.LPWSTR),
                        ('dwX', w.DWORD), ('dwY', w.DWORD), ('dwXSize', w.DWORD), ('dwYSize', w.DWORD),
                        ('dwXCountChars', w.DWORD), ('dwYCountChars', w.DWORD), ('dwFillAttribute', w.DWORD),
                        ('dwFlags', w.DWORD), ('wShowWindow', w.WORD), ('cbReserved2', w.WORD),
                        ('lpReserved2', ctypes.c_void_p), ('hStdInput', w.HANDLE), ('hStdOutput', w.HANDLE),
                        ('hStdError', w.HANDLE), ('lpAttributeList', ctypes.c_void_p)]

        class PROCESS_INFORMATION(ctypes.Structure):
            _fields_ = [('hProcess', w.HANDLE), ('hThread', w.HANDLE), ('dwProcessId', w.DWORD),
                        ('dwThreadId', w.DWORD)]

        k = self.k = _kernel32()
        in_r, in_w, out_r, out_w = (w.HANDLE() for _ in range(4))
        self.pc = w.HANDLE()
        attrs, pi = None, PROCESS_INFORMATION()
        try:
            if not k.CreatePipe(ctypes.byref(in_r), ctypes.byref(in_w), None, 0) or \
                    not k.CreatePipe(ctypes.byref(out_r), ctypes.byref(out_w), None, 0):
                raise _error()
            rows, cols = size
            if hr := k.CreatePseudoConsole(w._COORD(cols, rows), in_r, out_w, 0, ctypes.byref(self.pc)):
                raise OSError(f'CreatePseudoConsole failed (0x{hr & 0xffffffff:08x})')
            n = ctypes.c_size_t()
            k.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(n))
            buf = ctypes.create_string_buffer(n.value)
            if not k.InitializeProcThreadAttributeList(buf, 1, 0, ctypes.byref(n)):
                raise _error()
            attrs = buf
            # 0x20016: PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE
            if not k.UpdateProcThreadAttribute(attrs, 0, 0x20016, self.pc, ctypes.sizeof(w.HANDLE), None, None):
                raise _error()
            si = STARTUPINFOEXW(cb=ctypes.sizeof(STARTUPINFOEXW), lpAttributeList=ctypes.addressof(attrs))
            si.dwFlags = 0x100  # STARTF_USESTDHANDLES with none given: else it gets this process's redirected ones
            block = ctypes.create_unicode_buffer(
                ''.join(f'{a}={b}\0' for a, b in sorted(env.items(), key=lambda kv: kv[0].upper())) + '\0')
            line = ctypes.create_unicode_buffer(sp.list2cmdline(argv))
            # 0x80000 EXTENDED_STARTUPINFO_PRESENT, 0x400 CREATE_UNICODE_ENVIRONMENT
            if not k.CreateProcessW(None, line, None, None, False, 0x80400, block, str(cwd), ctypes.byref(si),
                                    ctypes.byref(pi)):
                raise _error()
            k.CloseHandle(pi.hThread)
        except BaseException:
            for h in (out_r, in_w):  # before the pseudo-console, whose close waits for its output to be read
                if h:
                    k.CloseHandle(h)
            if self.pc:
                k.ClosePseudoConsole(self.pc)
            raise
        finally:
            if attrs is not None:
                k.DeleteProcThreadAttributeList(attrs)
            for h in (in_r, out_w):  # the console host has its own copies
                if h:
                    k.CloseHandle(h)
        self.pid, self.proc, self.inw, self.out = int(pi.dwProcessId), pi.hProcess, in_w, out_r
        self.typed: queue.Queue = queue.Queue()
        self.lock, self.closed = threading.Lock(), False  # no resize of a console that is being closed
        self.reader = threading.Thread(target=self._pump, args=(on_output,), daemon=True)
        self.writer = threading.Thread(target=self._type, daemon=True)
        self.reader.start()
        self.writer.start()

    def _pump(self, on_output) -> None:
        while data := _read(self.k, self.out):
            try:
                on_output(data)
            except (OSError, ValueError):
                pass  # the log cannot be written: read on, or the session stops at a full pipe

    def _type(self) -> None:
        import ctypes
        from ctypes import wintypes
        n = wintypes.DWORD()
        while data := self.typed.get():
            while data:
                if not self.k.WriteFile(self.inw, data, len(data), ctypes.byref(n), None):
                    return
                data = data[n.value:]

    def write(self, data: bytes) -> None:
        """Type `data` into the session; returns at once."""
        if data:
            self.typed.put(data)

    def resize(self, rows: int, cols: int) -> None:
        """F114: the console's size (an attached terminal's)."""
        from ctypes import wintypes
        with self.lock:
            if self.closed:
                return
            if hr := self.k.ResizePseudoConsole(self.pc, wintypes._COORD(cols, rows)):
                raise OSError(f'ResizePseudoConsole failed (0x{hr & 0xffffffff:08x})')

    def wait(self, seconds: float) -> int | None:
        """The exit code once the process has ended, None when it has not within `seconds`."""
        import ctypes
        from ctypes import wintypes
        if self.k.WaitForSingleObject(self.proc, int(seconds * 1000)):
            return None
        code = wintypes.DWORD()
        if not self.k.GetExitCodeProcess(self.proc, ctypes.byref(code)):
            raise _error()
        return int(code.value)

    def close(self, seconds: float = 8.0) -> None:
        """End the pseudo-console and read what it still prints, for `seconds` at most: closing it ends what
        still runs in it, and a process that will not end must not hold the shim."""
        k = self.k
        with self.lock:
            self.closed = True
        # its own thread: before Windows 11 24H2 the call waits for every process in the console to end
        closer = threading.Thread(target=k.ClosePseudoConsole, args=(self.pc,), daemon=True)
        closer.start()
        end = time.monotonic() + seconds
        for t in (closer, self.reader):
            t.join(max(0.0, end - time.monotonic()))
        self.typed.put(b'')
        for t, h in ((self.reader, self.out), (self.writer, self.inw)):
            if _join(k, t, 2.0):
                k.CloseHandle(h)  # else left to the process's end: closing a handle in use could wait for ever
        k.CloseHandle(self.proc)


def _user_sid(k) -> str:
    """This user's SID, as text."""
    import ctypes
    from ctypes import wintypes as w
    a = ctypes.WinDLL('advapi32', use_last_error=True)
    a.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, ctypes.c_void_p]
    a.GetTokenInformation.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.c_void_p]
    a.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    token, n = w.HANDLE(), w.DWORD()
    if not a.OpenProcessToken(k.GetCurrentProcess(), 0x0008, ctypes.byref(token)):  # TOKEN_QUERY
        raise _error()
    try:
        buf = ctypes.create_string_buffer(256)
        if not a.GetTokenInformation(token, 1, buf, len(buf), ctypes.byref(n)):  # TokenUser
            raise _error()
        text = w.LPWSTR()
        if not a.ConvertSidToStringSidW(ctypes.c_void_p.from_buffer(buf), ctypes.byref(text)):
            raise _error()
        try:
            return text.value
        finally:
            k.LocalFree(text)
    finally:
        k.CloseHandle(token)


class InPipe:
    """The shim's end of `inbox` (slotN.in): a named pipe only this user may open, its name in that file. `take`
    gets what senders write, one sender at a time. OSError when the pipe cannot be made."""

    def __init__(self, inbox: Path, take) -> None:
        import ctypes
        from ctypes import wintypes as w

        class SECURITY_ATTRIBUTES(ctypes.Structure):
            _fields_ = [('nLength', w.DWORD), ('lpSecurityDescriptor', ctypes.c_void_p), ('bInheritHandle', w.BOOL)]

        k = self.k = _kernel32()
        a = ctypes.WinDLL('advapi32', use_last_error=True)
        convert = a.ConvertStringSecurityDescriptorToSecurityDescriptorW
        convert.argtypes = [w.LPCWSTR, w.DWORD, ctypes.c_void_p, ctypes.c_void_p]
        sd = ctypes.c_void_p()
        # protected, one entry: all access for this user (GA), nobody else
        if not convert(f'D:P(A;;GA;;;{_user_sid(k)})', 1, ctypes.byref(sd), None):
            raise _error()
        try:
            sa = SECURITY_ATTRIBUTES(ctypes.sizeof(SECURITY_ATTRIBUTES), sd, False)
            name = rf'\\.\pipe\agent-runner-{secrets.token_hex(16)}'
            # PIPE_ACCESS_INBOUND | FILE_FLAG_FIRST_PIPE_INSTANCE; bytes, PIPE_REJECT_REMOTE_CLIENTS; one instance
            h = k.CreateNamedPipeW(name, 0x1 | 0x80000, 0x8, 1, 0, 65536, 0, ctypes.byref(sa))
        finally:
            k.LocalFree(sd)
        if h == w.HANDLE(-1).value:
            raise _error()
        self.h, self.inbox, self.take, self.ended = h, inbox, take, False
        try:
            inbox.write_text(name, encoding='utf-8')
        except OSError:
            k.CloseHandle(h)
            raise
        self.server = threading.Thread(target=self._serve, daemon=True)
        self.server.start()

    def _serve(self) -> None:
        import ctypes
        while not self.ended:
            # ERROR_PIPE_CONNECTED, ERROR_NO_DATA: a sender came (and maybe left) before this call
            if self.k.ConnectNamedPipe(self.h, None) or ctypes.get_last_error() in (535, 232):
                while not self.ended and (data := _read(self.k, self.h)):
                    self.take(data)
                self.k.DisconnectNamedPipe(self.h)
            elif not self.ended:
                time.sleep(0.05)

    def close(self) -> None:
        self.ended = True
        self.inbox.unlink(missing_ok=True)
        if _join(self.k, self.server, 2.0):
            self.k.CloseHandle(self.h)


def pipe_send(inbox: Path, chunks: list[bytes], pause: float = 0.0) -> bool:
    """Write `chunks` to the session whose shim serves `inbox` (`InPipe`), `pause` s after each. False when none
    does (the session ended) or it takes nothing for SEND_WAIT s."""
    end = time.monotonic() + SEND_WAIT
    try:
        name = inbox.read_text(encoding='utf-8').strip()
        if not name.startswith('\\\\.\\pipe\\'):
            return False
        while True:
            try:
                fd = os.open(name, os.O_WRONLY | os.O_BINARY | os.O_NOINHERIT)
                break
            except FileNotFoundError:
                return False
            except OSError:  # another sender is in (ERROR_PIPE_BUSY)
                if time.monotonic() > end:
                    return False
                time.sleep(0.05)
    except (OSError, AttributeError):
        return False
    sent = []

    def write() -> None:  # a thread of its own: a write to a shim that reads nothing waits for ever
        try:
            for chunk in chunks:
                while chunk:
                    chunk = chunk[os.write(fd, chunk):]
                time.sleep(pause)
            sent.append(True)
        except OSError:
            pass
        finally:
            os.close(fd)

    t = threading.Thread(target=write, daemon=True)
    t.start()
    t.join(SEND_WAIT + pause * len(chunks))
    return bool(sent)
