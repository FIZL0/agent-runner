"""F402b1: the page-only process. While no run is up, it serves one project's full run page: the same server, key and
address rules as a run's (`web.start_web`), so chats and the plan work there. It starts no slot, task, merge or push, and
never holds run.lock, so `state.run_up` stays False and `status` says that no run is up.

`agent-runner page-only` is the process; the launcher's w starts it detached and opens its page (`open_page`). One at most
per project: it holds <notes>/page.lock while it serves, and <notes>/page.live is there once its page answers. It ends
when a run starts (`take_over`, called by the run's start_web, which then has the port and web.url), at `agent-runner
page-only stop`, or after IDLE s with no page open where Runner Home can start it again (`home_starts`). Chats are detached processes of their own, so none ends with it.

F402b3a: a run's stop hands its page to one (`hand_over`): the same address, port, key and https rule.

What a run's loop does for chats and nobody does here: closing idle chats, ending ones closed online, and bringing back
those a shutdown cut off (the run's start does). A new chat, a message, Resume and the plan commands need no loop. One
thing a message may need is done here too (`control_held.held_tick`): what a chat held for a usage limit is put in."""

from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from agent_runner import plat
from agent_runner import state as S

IDLE = 600.0  # s with no page open (no request under way; an open page holds its events stream) before it may end
HOME_AGAIN = 30.0  # s between two looks at whether Home can start it again, once idle
LOOK = 0.5  # s between two looks at whether to end
START_WAIT = 40.0  # s the launcher waits for the page to answer (Tailscale Serve may take 15)
TAKE_WAIT = 20.0  # s a run's start waits for it to give up the page (turning Tailscale Serve off may take 10)
READY_WAIT = 10.0  # s a run's stop waits for the process it hands its page to, its own page still up
HAND_WAIT = 8.0  # s it then waits for that process to answer (a start waits LAST_RUN_WAIT for the whole stop)
LAST_ACTS = 120.0 # s it stays, its port already free, for actions that were still running when it ended
HANDED = '--handed'  # the word it is started with by a run's stop
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
        proc = plat.spawn_detached([*plat.service_scope(), *argv()], out=out, cwd=root, env=env)
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
    """A run that is starting wants the page (`take_over`), or a command ends it (`end_page`). A note whose writer is
    gone says nothing."""
    from agent_runner.slots import marker_pid
    pid = marker_pid(S.C.notes('page.stop'))
    return bool(pid and plat.alive(pid))


# --- the run: hand its page over at its stop ---------------------------------------------------------------------

def kept() -> bool:
    """Does a page stay up after this project's run? Not with [run] web = false, also when it was set during the run."""
    from agent_runner.config import Config
    return bool(Config(S.C.root).run.get('web', True))


def hand_note() -> dict | None:
    """What a stopping run hands over: {'pid': the run's, 'bind', 'port'}; None when no live run hands anything over."""
    try:
        d = json.loads(S.C.notes('page.hand').read_text(encoding='utf-8'))
        return d if plat.alive(int(d['pid'])) and d['bind'] and int(d['port']) else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def wait_child(proc, done, wait: float) -> bool:
    """Wait up to `wait` s for `done()`, or until `proc` has ended."""
    end = time.monotonic() + wait
    while not (got := done()) and proc.poll() is None and time.monotonic() < end:
        time.sleep(0.1)
    return bool(got)


def hand_over(srv) -> str:
    """A run's stop: a page-only process takes over what `srv` serves, on its address and with its https rule: '' once it
    answers there, else why not. `srv` has stopped either way, and a handover that failed leaves no process and no rule."""
    note, live, out = (S.C.notes(n) for n in ('page.hand', 'page.live', 'page.out'))
    proc, why, https, closed = None, '', False, False
    try:
        live.unlink(missing_ok=True)  # of one that was killed
        with contextlib.suppress(OSError):  # Windows: one that ended may still have it open (LAST_ACTS)
            out.unlink(missing_ok=True)
        S.C.notes('page.stop').unlink(missing_ok=True)  # this run's own ask, if the one it met was slow to end
        bind, port = srv.server_address[:2]
        note.write_text(json.dumps({'pid': os.getpid(), 'bind': bind, 'port': port}), encoding='utf-8')
        env = {k: v for k, v in os.environ.items() if k not in NOT_OURS}
        proc = plat.spawn_detached([*argv(), HANDED], out=out, cwd=S.C.root, env=env)
        if not wait_child(proc, held, READY_WAIT):
            why = 'the page-only process did not start'
        else:
            https, srv.https = srv.https, False  # its rule stays
            closed = True
            srv.stop()
            if not wait_child(proc, serving, HAND_WAIT):
                why = 'the page-only process did not answer'
    except Exception as e:  # noqa: BLE001 - the stop goes on
        why = f'{type(e).__name__}: {e}'
    with contextlib.suppress(OSError):
        note.unlink(missing_ok=True)  # a process that has not got the port by now ends
    if not why:
        return ''
    if proc is not None:
        end_child(proc)
        with contextlib.suppress(OSError):
            why += f': {said}' if (said := out.read_text(encoding='utf-8', errors='replace').strip()[-300:]) else ''
    if not closed:
        srv.stop()
    elif https:
        from agent_runner import page_https
        page_https.https_off()
    return why


def end_child(proc) -> None:
    """End the process of a handover that failed, so the next run meets nothing of it."""
    for end in (lambda: plat.terminate(proc.pid), proc.kill):
        if proc.poll() is None:
            end()
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(3)


def take_page(end: threading.Event):
    """The process a run hands its page to: that page's server, as soon as the run has closed its own; None when the
    handover is off (the run gave it up or is gone, or `end` is set)."""
    from agent_runner import page_https, web
    srv = None
    while (hand := hand_note()) and not end.is_set():
        try:
            srv = web.serve(web.web_token(), hand['port'], hand['bind'])
            break
        except OSError:  # the run still serves there
            end.wait(0.1)
    if srv is None:
        return None
    if not hand_note():
        srv.stop()
        return None
    web.write_urls(srv)
    srv.https = not srv.private() and page_https.made_rule() is not None
    threading.Thread(target=web.HomeWatch(srv).loop, name='run-page-home', daemon=True).start()
    return srv


def end_page(wait: float = TAKE_WAIT) -> tuple[int, str]:
    """`agent-runner page-only stop`: (exit code, what to say)."""
    if not held():
        return 0, 'no page-only process serves this project'
    take_over(wait)
    if held():
        return 1, f'the page-only process did not end in {wait:g} s'
    return 0, 'the page-only process ended: the run page is closed, chats go on'


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


def home_starts() -> bool:
    """F402b3b: can Runner Home start this process again when a person opens the project? Not with no Home, a web_port
    of its own, a Home that does not answer, or one that does not list the project."""
    try:
        from agent_runner import web
        from agent_runner.home import site_links
        return web.home_only() and bool(site_links(S.C.root, https=lambda port, token: []))
    except Exception as e:  # noqa: BLE001 - the page goes on
        S.log(f'run page: looking for Runner Home failed ({type(e).__name__}: {e})')
        return False


class Idle:
    """Is the page in no use, and is that a reason to end? Home is asked only then, every HOME_AGAIN s."""

    def __init__(self, use: Use):
        self.use, self.next = use, 0.0

    def ends(self) -> bool:
        if self.use.idle() < IDLE or time.monotonic() < self.next:
            return False
        self.next = time.monotonic() + HOME_AGAIN
        return home_starts() and self.use.idle() >= IDLE  # Home may take seconds to answer: a page may be open by now


def only_one():
    """page.lock, held while this process serves; None when another one has it. Tried for a second: a look at whether
    it is held takes it for a moment (`held`)."""
    for _ in range(5):
        if got := plat.lock(S.C.notes('page.lock')):
            return got
        time.sleep(0.2)
    return None


def serve(end: threading.Event, handed: bool = False) -> int:
    """Serve the page until it is asked to end (a run takes it over, `end_page`), it was idle for IDLE s where Home can
    start it again, or `end` is set (a signal). The exit code.
    `handed`: a stopping run, still up, hands it its page."""
    lock = only_one()
    if lock is None:
        print('a page-only process serves this project already')
        return 0
    live, srv, use = S.C.notes('page.live'), None, Use()
    try:
        live.unlink(missing_ok=True)  # of one that was killed
        from agent_runner import web
        if handed:
            srv = take_page(end)
            if srv is None:
                print("the run's page was not handed over, or its port could not be had")
                return 1
        elif S.run_up():
            print('a run is up in this repository, and it serves the page')
            return 0
        else:
            srv = web.start_web(only=True)
            if srv is None:
                print('the run page is off here ([run] web), or no port could be had')
                return 1
        counted(srv, use)
        live.write_text(str(os.getpid()), encoding='utf-8')
        why, idle = '', Idle(use)
        while not why:
            held_messages()
            why = 'a run or a command asked' if asked_to_end() else f'no page was open for {IDLE:g} s' if idle.ends() \
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
    """`agent-runner page-only`: the process itself (see above), in the foreground. `stop` ends the one that serves."""
    handed, stop = words == [HANDED], words == ['stop']
    if words and not handed and not stop:
        print('agent-runner page-only takes nothing more than `stop`, which ends the one that serves', file=sys.stderr)
        return 2
    from agent_runner.loop import drop_session_env
    drop_session_env()
    for k in NOT_OURS:
        os.environ.pop(k, None)
    S.init()
    if stop:
        code, said = end_page()
        print(said, file=sys.stderr if code else sys.stdout)
        return code
    end = threading.Event()
    for s in (signal.SIGTERM, signal.SIGINT):
        signal.signal(s, lambda *_: end.set())
    return serve(end, handed)
