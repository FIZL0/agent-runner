"""F402b1: the page-only process. While no run is up, it serves one project's full run page: the same server, key and
address rules as a run's (`web.start_web`), so chats and the plan work there. It starts no slot, task, merge or push, and
never holds run.lock, so `state.run_up` stays False and `status` says that no run is up.

`agent-runner page-only` is the process; the launcher's w starts it detached and opens its page (`open_page`). One at most
per project: it holds <notes>/page.lock while it serves, and <notes>/page.live is there once its page answers. It ends
when a run starts (`take_over`, called by the run's start_web, which then has the port and web.url), or after IDLE s with
no page open. Chats are detached processes of their own, so none ends with it.

What a run's loop does for chats and nobody does here: closing idle chats, ending ones closed online, and bringing back
those a shutdown cut off (the run's start does). A new chat, a message, Resume and the plan commands need no loop. One
thing a message may need is done here too (`control_held.held_tick`): what a chat held for a usage limit is put in."""

from __future__ import annotations

import contextlib
import json
import os
import signal
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from agent_runner import plat
from agent_runner import state as S

IDLE = 600.0  # s with no page open (no request under way; an open page holds its events stream) before it ends
LOOK = 0.5  # s between two looks at whether to end
START_WAIT = 40.0  # s the launcher waits for the page to answer (Tailscale Serve may take 15)
TAKE_WAIT = 20.0  # s a run's start waits for it to give up the page (turning Tailscale Serve off may take 10)
LAST_ACTS = 120.0  # s it stays, its port already free, for actions that were still running when it ended
NOT_OURS = ('AGENT_RUNNER', 'AGENT_RUNNER_SLOT', 'AGENT_RUNNER_KEEP', 'AGENT_RUNNER_REPO', 'AGENT_RUNNER_CONTROL',
            'AGENT_RUNNER_STARTED_BY')


def notes(root: Path | None, name: str) -> Path:
    if root is None:
        return S.C.notes(name)
    from agent_runner.config import Config
    return Config(root).notes(name)


def held(root: Path | None = None) -> bool:
    """Is a page-only process of the project at `root` (this one's) there? No lock file is made just to look."""
    f = notes(root, 'page.lock')
    if not f.exists():
        return False
    if got := plat.lock(f):
        got.close()
        return False
    return True


def serving(root: Path | None = None) -> bool:
    """Does a page-only process serve the page of the project at `root` (this one's) now?"""
    try:
        return notes(root, 'page.live').exists() and held(root)
    except (OSError, SystemExit, ValueError, KeyError, TypeError):
        return False


def urls(root: Path | None = None) -> list[str]:
    try:
        return notes(root, 'web.url').read_text(encoding='utf-8').split()
    except (OSError, SystemExit, ValueError, KeyError, TypeError):
        return []


def links(root: Path) -> list[str]:
    """The addresses that open the page a page-only process serves for `root`: Home's when it routes the project, else its
    own; the 127.0.0.1 one only where nothing else does (the launcher opens it on this machine). [] while none serves."""
    if not serving(root):
        return []
    from agent_runner import web
    own = urls(root)
    return web.shown_links(web.site_urls(root), web.own_links(own)) or own


# --- the launcher: start it, open it ----------------------------------------------------------------------------

def argv() -> list[str]:
    from agent_runner.config import runner_cmd
    return [*runner_cmd(), 'page-only']


def start(root: Path, wait: float = START_WAIT) -> str:
    """Start the page-only process of the project at `root` unless one serves already: '' once its page answers or a run
    is up, else why it does not."""
    from agent_runner.cmds import run_info
    if serving(root):
        return ''
    out = notes(root, 'page.out')
    with contextlib.suppress(OSError):
        out.unlink(missing_ok=True)  # only its last start's words
    env = {k: v for k, v in os.environ.items() if k not in NOT_OURS}
    try:
        proc = plat.spawn_detached(argv(), out=out, cwd=root, env=env)
    except OSError as e:
        return f'the run page did not start: {e}'
    end = time.monotonic() + wait
    while time.monotonic() < end:
        if serving(root):
            return ''
        if proc.poll() is not None:
            if serving(root) or run_info(root).get('up'):  # another one was first
                return ''
            if not held(root):
                break
        time.sleep(0.2)
    try:
        said = out.read_text(encoding='utf-8', errors='replace').strip()[-1000:]
    except OSError:
        said = ''
    return 'the run page did not start' + (f': {said}' if said else '')


def open_page(root: Path, opener) -> tuple[str, str]:
    """The launcher's w while no run is up: (what to say, the page's link or ''). A run that came up meanwhile has the
    page, and its link is opened."""
    if why := start(root):
        return why, ''
    from agent_runner.cmds import run_facts, run_info
    got = links(root)
    if not got and (run := run_info(root)).get('up'):
        got = [x for x in [run_facts(root, run)['link']] if x]
    return (opener(got[0]), got[0]) if got else ('no run page link to use', '')


# --- the run: take its page over ---------------------------------------------------------------------------------

def take_over(wait: float = TAKE_WAIT) -> int:
    """A run's start: have the page-only process of this project end, and wait for it, so the run has its port and
    web.url. The port it served on (an open page reconnects there), 0 when there was none."""
    if not held():
        return 0
    us, stop = urls(), S.C.notes('page.stop')
    stop.write_text(str(os.getpid()), encoding='utf-8')
    end = time.monotonic() + wait
    while held():
        if time.monotonic() >= end:  # the note stays, so it still ends once it looks
            S.log(f'run page: the page-only process did not end in {wait:g} s')
            return 0
        time.sleep(0.1)
    stop.unlink(missing_ok=True)
    try:
        return urlsplit(us[0]).port or 0
    except (IndexError, ValueError):
        return 0


def asked_to_end() -> bool:
    """A run that is starting wants the page (`take_over`). A note whose run is gone says nothing."""
    from agent_runner.slots import marker_pid
    pid = marker_pid(S.C.notes('page.stop'))
    return bool(pid and plat.alive(pid))


# --- the process ------------------------------------------------------------------------------------------------

class Use:
    """What its page is used for: requests under way (an open page's events stream among them), actions under way,
    and when the last one ended."""

    def __init__(self):
        self.lock = threading.Lock()
        self.open, self.acts, self.at = 0, 0, time.monotonic()

    @contextlib.contextmanager
    def one(self, act: bool):
        with self.lock:
            self.open += 1
            self.acts += act
        try:
            yield
        finally:
            with self.lock:
                self.open -= 1
                self.acts -= act
                self.at = time.monotonic()

    def idle(self) -> float:
        with self.lock:
            return 0.0 if self.open else time.monotonic() - self.at


def counted(srv, use: Use) -> None:
    """Count in `use` what is asked of `srv`. A connection kept open closes after its answer once `srv` stops, so the
    page's next request goes to the run."""
    class Counted(srv.RequestHandlerClass):
        def end_headers(self) -> None:
            if self.server.stopped.is_set():
                self.close_connection = True
            super().end_headers()

        def do_GET(self) -> None:
            with use.one(act=False):
                super().do_GET()

        def do_POST(self) -> None:
            with use.one(act=True):
                super().do_POST()
    srv.RequestHandlerClass = Counted


def held_messages() -> None:
    """B170, as the run's loop does: a message a chat held for a usage limit is put in once it is over."""
    from agent_runner import control_held
    try:
        control_held.held_tick()
    except Exception as e:  # noqa: BLE001 - the page goes on
        S.log(f'run page: the messages chats hold could not be looked at ({type(e).__name__}: {e})')


def only_one():
    """page.lock, held while this process serves; None when another one has it. Tried for a second: a look at whether
    it is held takes it for a moment (`held`)."""
    for _ in range(5):
        if got := plat.lock(S.C.notes('page.lock')):
            return got
        time.sleep(0.2)
    return None


def serve(end: threading.Event) -> int:
    """Serve the page until a run takes it over, it was idle for IDLE s, or `end` is set (a signal). The exit code."""
    lock = only_one()
    if lock is None:
        print('a page-only process serves this project already')
        return 0
    live, srv, use = S.C.notes('page.live'), None, Use()
    try:
        live.unlink(missing_ok=True)  # of one that was killed
        if S.run_up():
            print('a run is up in this repository, and it serves the page')
            return 0
        from agent_runner import web
        srv = web.start_web(only=True)
        if srv is None:
            print('the run page is off here ([run] web), or no port could be had')
            return 1
        counted(srv, use)
        live.write_text(str(os.getpid()), encoding='utf-8')
        why = ''
        while not why:
            held_messages()
            why = 'a run takes it over' if asked_to_end() else f'no page was open for {IDLE:g} s' if use.idle() >= IDLE \
                else 'ended' if end.wait(LOOK) else ''
        S.log(f'run page: the page-only process ends ({why}); chats go on')
    finally:
        live.unlink(missing_ok=True)
        if srv is not None:
            port = srv.server_address[1]
            srv.stop()
            if any(f':{port}/' in u for u in urls()):  # not one a run wrote that did not wait any longer
                web.url_file().unlink(missing_ok=True)
        lock.close()
    until = time.monotonic() + LAST_ACTS
    while use.acts and time.monotonic() < until:  # the start of the run that takes over may be one
        time.sleep(0.1)
    return 0


def main(words: list[str]) -> int:
    """`agent-runner page-only`: the process itself (see above), in the foreground."""
    if words:
        print('agent-runner page-only takes nothing more', file=sys.stderr)
        return 2
    from agent_runner.loop import drop_session_env
    drop_session_env()
    for k in NOT_OURS:
        os.environ.pop(k, None)
    S.init()
    end = threading.Event()
    for s in (signal.SIGTERM, signal.SIGINT):
        signal.signal(s, lambda *_: end.set())
    return serve(end)
