"""F114: `attach sN|cN` on Windows: this console on a hidden session's pseudo-console (`attach.attach_session`).
Standard library only (`ctypes`). What is typed is read as UTF-16 (ReadConsoleW), with the console giving keys as
VT sequences, and sent as UTF-8; its size is looked at every POLL s, as a console sends no signal for it."""
from __future__ import annotations

import os
import threading

from agent_runner.attach import TERM_RESET, Typed, attach_input_frames, attach_size_frame

POLL = 0.2  # s between two looks at the console's size
IN_RAW = 0x0200  # ENABLE_VIRTUAL_TERMINAL_INPUT alone: no line input, no echo, Ctrl-C is a byte
OUT_VT = 0x0001 | 0x0004 | 0x0008  # processed output, VT sequences, no newline added to a line feed


def attach_console(s, name: str) -> int:
    """Attach this console to the session on the connection `s` until Ctrl-b d (it keeps running) or it ends."""
    import ctypes
    from ctypes import wintypes as w
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.GetStdHandle.restype, k.GetStdHandle.argtypes = w.HANDLE, [w.DWORD]
    k.GetConsoleMode.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
    k.SetConsoleMode.argtypes = [w.HANDLE, w.DWORD]
    k.ReadConsoleW.argtypes = [w.HANDLE, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD), ctypes.c_void_p]
    hin, hout = k.GetStdHandle(0xFFFFFFF6), k.GetStdHandle(0xFFFFFFF5)  # STD_INPUT_HANDLE, STD_OUTPUT_HANDLE
    was_in, was_out, was_cp = w.DWORD(), w.DWORD(), k.GetConsoleOutputCP()
    console = bool(k.GetConsoleMode(hin, ctypes.byref(was_in)))
    shown = bool(k.GetConsoleMode(hout, ctypes.byref(was_out)))
    why = [f'detached from {name} ({name} keeps running)']
    over = threading.Event()
    send = threading.Lock()  # a frame is sent whole

    def put(data: bytes) -> None:
        with send:
            s.sendall(data)

    def end(said: str) -> None:
        if not over.is_set():
            why[0] = said
            over.set()

    def size() -> tuple[int, int] | None:
        try:
            cols, rows = os.get_terminal_size(1)
            return rows, cols
        except OSError:
            return None

    def read_keys() -> bytes:
        if not console:
            return os.read(0, 4096)
        buf, n = ctypes.create_unicode_buffer(1024), w.DWORD()
        if not k.ReadConsoleW(hin, buf, 1023, ctypes.byref(n), None):
            return b''
        return buf[:n.value].encode('utf-16-le', 'surrogatepass').decode('utf-16-le', 'replace').encode('utf-8')

    def keys() -> None:
        typed = Typed()
        try:
            while data := read_keys():
                go, detach = typed.feed(data)
                if go:
                    put(attach_input_frames(go))
                if detach:
                    return end(why[0])
        except OSError:
            pass
        end(f'input ended: detached from {name} ({name} keeps running)')

    def output() -> None:
        try:
            while data := s.recv(65536):
                while data:
                    data = data[os.write(1, data):]
        except OSError:
            pass
        end(f'{name} ended')

    try:
        if console:
            k.SetConsoleMode(hin, IN_RAW)
        if shown:
            k.SetConsoleOutputCP(65001)
            k.SetConsoleMode(hout, OUT_VT)
        at = size()
        if at:  # once: the shim itself draws the screen again for a client that just came (`Viewers.fit`)
            put(attach_size_frame(*at))
        for f in (keys, output):
            threading.Thread(target=f, daemon=True).start()
        while not over.wait(POLL):
            if (now := size()) and now != at:
                at = now
                put(attach_size_frame(*now))
    except OSError:
        end(f'{name}: the connection to its terminal broke')
    finally:
        s.close()
        if shown:
            os.write(1, TERM_RESET)
        os.write(1, f'\r\n[{why[0]}]\r\n'.encode())
        if shown:
            k.SetConsoleMode(hout, was_out.value)
            k.SetConsoleOutputCP(was_cp)
        if console:
            k.SetConsoleMode(hin, was_in.value)
    return 0
