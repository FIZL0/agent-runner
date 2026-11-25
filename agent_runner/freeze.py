"""B827: what a stop now (`stop --force`) holds still, so it can end a merge at any moment and leave nothing half done.

Once `STOPPER` names the thread that stops the run, every thread that merges (and the loop's own, when another one stops
it) waits for ever at its next git command (`git_step`): a gate the stop ended must not read as one that failed, with
a repair session or a parked branch after it. A thread in a `held()` part (moving the main checkout and recording it)
goes on to that part's end, which `quiet` waits for. `run` starts what a merge waits for (a fix session, a retest, a
join) so that the stop can end it, also from another process: `RECORD` lists them."""
from __future__ import annotations

import json
import subprocess as sp
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from agent_runner import plat

STOPPER: list[int] = []  # the ident of the thread that stops the run now
RECORD: list[Path] = []  # where a run lists what `run` started: [] outside a run, where `run` is subprocess.run
NET = {'push', 'fetch', 'pull', 'ls-remote'}  # git's own network commands: nothing waits for one
CV = threading.Condition()
BUSY: dict[int, int] = {}  # thread -> how many git commands and held parts it is in
IN = threading.local()  # .held: this thread is in a held part
PROCS: dict[int, sp.Popen] = {}


def _merges() -> bool:
    t = threading.current_thread()
    return t is threading.main_thread() or t.name.startswith(('merge:', 'undo', 'pull requests'))


def point() -> None:
    """A merge's thread waits here for ever once the run stops now, unless it is in a held part."""
    while STOPPER and threading.get_ident() not in STOPPER and not getattr(IN, 'held', 0) and _merges():
        time.sleep(60)  # the process ends under it


@contextmanager
def _busy():
    """Counted for `quiet`. Entered under the lock `stop` takes, so no step starts unseen between the two."""
    me = threading.get_ident()
    while True:
        point()
        with CV:
            if not STOPPER or me in STOPPER or getattr(IN, 'held', 0) or not _merges():
                BUSY[me] = BUSY.get(me, 0) + 1
                break
    try:
        yield
    finally:
        with CV:
            BUSY[me] -= 1
            if not BUSY[me]:
                del BUSY[me]
            CV.notify_all()


@contextmanager
def held():
    """A part that a stop now lets go on to its end: short, with no test and no network in it."""
    with _busy():
        IN.held = getattr(IN, 'held', 0) + 1
        try:
            yield
        finally:
            IN.held -= 1


def pause(seconds: float) -> None:
    """Sleep in a held part where nothing is half done: a stop now need not wait for it, and does not go on after it."""
    me, was = threading.get_ident(), getattr(IN, 'held', 0)
    with CV:
        n = BUSY.pop(me, 0)
        CV.notify_all()
    IN.held = 0
    try:
        time.sleep(seconds)
        with _busy():
            with CV:
                BUSY[me] = BUSY[me] + n
    finally:
        IN.held = was


@contextmanager
def git_step(args: tuple):
    words = list(args)
    while words[:1] == ['-c']:
        del words[:2]
    if not _merges() or words[:1] and words[0] in NET:
        point()
        yield
        return
    with _busy():
        yield


def stop() -> bool:
    """This thread stops the run now; False when another one does already."""
    with CV:
        if STOPPER:
            return threading.get_ident() in STOPPER
        STOPPER.append(threading.get_ident())
        return True


def quiet(seconds: float) -> bool:
    """Wait until no other thread is in a git command or a held part, at most `seconds`."""
    end, me = time.monotonic() + seconds, threading.get_ident()
    with CV:
        while any(t != me for t in BUSY):
            if (left := end - time.monotonic()) <= 0:
                return False
            CV.wait(left)
    return True


def _record() -> None:
    try:
        RECORD[0].write_text(json.dumps([{'pid': p, 'start': plat.started(p)} if plat.started(p) else {'pid': p}
                                         for p in PROCS]), encoding='utf-8')
    except OSError:
        pass


def run(cmd, timeout: float | None = None, **kw) -> sp.CompletedProcess:
    """subprocess.run; in a run, in a process group of its own that a stop now can end."""
    if not RECORD:
        return sp.run(cmd, timeout=timeout, **kw)
    if kw.pop('capture_output', False):
        kw.update(stdout=sp.PIPE, stderr=sp.PIPE)
    with _busy():  # never started and not yet listed
        p = sp.Popen(cmd, start_new_session=not plat.WINDOWS, **kw)
        with CV:
            PROCS[p.pid] = p
            _record()
    try:
        out, err = p.communicate(timeout=timeout)
    except BaseException:
        plat.kill_tree(p.pid)
        p.wait()
        for f in (p.stdout, p.stderr):
            if f:
                f.close()
        raise
    finally:
        with CV:
            PROCS.pop(p.pid, None)
            _record()
    point()
    return sp.CompletedProcess(cmd, p.returncode, out, err)
