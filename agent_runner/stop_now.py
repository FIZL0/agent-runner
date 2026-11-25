"""B827: a stop now (`stop --force`, `s!`, X X in the terminal UI, Stop now on the page): the whole run ends within
seconds. Sessions, merges and gates under way are ended and nothing is waited for but a git command that moves the main
checkout. Each ended session resumes in the next run, and each ended merge is made again by it: task/<ID> stays as it is.

In the run: `stop`, on the loop's next tick (`watch` wakes it), or in `watch`'s own thread when the loop is busy or hung.
From a command: `command` asks, waits until the run's process is gone, and ends it and does the rest itself when it hangs."""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess as sp
import sys
import threading
import time
from pathlib import Path

from agent_runner import exit_hook, freeze, plat
from agent_runner import state as S

TAKE = 3.0  # s the loop has to begin the stop, before `watch` does it without the loop
QUIET = 3.0  # s a git command that moves the main checkout gets to end
OWN = 5.0  # s the run's own processes and its page's handover get
HANG = 12.0  # s the whole stop may take: past it the run exits as it is
BEGIN = 5.0  # s a command waits for the run to begin the stop, before it ends the run
TERM = 2.0  # s the run gets after SIGTERM, before SIGKILL
FROM = 'AGENT_RUNNER_ACT_OF'  # the pid of the process whose action a command is
LANDS = re.compile(r'\S+: the tested merge, onto commits ')  # what `land` calls a merge in the main checkout


# --- in the run ------------------------------------------------------------------------------------------------

def begin() -> None:
    """A run's start, run.lock held: what a stop now from another process goes by."""
    freeze.RECORD[:] = [S.C.notes('merge.procs')]
    freeze.RECORD[0].unlink(missing_ok=True)
    say_pid()


def say_pid(stopping: bool = False) -> None:
    f = S.C.notes('run.pid')
    tmp = f.with_name('run.pid.tmp')
    try:
        tmp.write_text(json.dumps({'pid': os.getpid(), 'start': plat.started(os.getpid()), 'stopping': stopping}),
                       encoding='utf-8')
        os.replace(tmp, f)
    except OSError:  # Windows: a command has it open this instant
        pass


def watch(run) -> None:
    """A daemon thread's loop: wake the loop for a stop now (and for any key a command left); stop without it when it
    does not begin, and exit as it is when the stop itself hangs."""
    while True:
        time.sleep(0.25)
        if S.C.notes('KEYS').exists():
            S.WAKE.set()
        if not S.forced():
            continue
        S.WAKE.set()
        end = time.monotonic() + TAKE
        while not freeze.STOPPER and S.forced() and time.monotonic() < end:
            time.sleep(0.1)
        if not freeze.STOPPER and not S.forced():
            continue  # taken back
        threading.Thread(target=_hung, daemon=True).start()
        if freeze.STOPPER:
            return
        os._exit(stop(run))


def _hung() -> None:
    time.sleep(HANG)
    os._exit(0)


def stop(run) -> int:
    """End everything the run has under way and say `run stopped`; 0. The caller ends the process at once after it."""
    from agent_runner import loop, teardown
    if not freeze.stop():
        while True:  # another thread does it, and ends the process
            time.sleep(60)
    say_pid(stopping=True)
    how = S.stopped_by()
    S.log(f'stopping now ({how}): the sessions and the merges under way are ended')
    ending = threading.Thread(target=end_merges_soon, daemon=True)
    ending.start()
    procs = {n: p for n, p in list(run.procs.items()) if n in run.running}
    running = dict(run.running)
    if any(re.fullmatch(r's\d+', k) and plat.alive(pid) and pid not in {p[0] for p in procs.values()}
           for k, (_, pid) in loop.MUX.panes().items()):
        for n, (p, task) in loop.adopt(run.branch).items():  # the loop was just starting it
            procs.setdefault(n, p)
            running.setdefault(n, task)
    loop.end_sessions(procs, running)
    run.procs.clear()
    run.running.clear()
    ending.join(QUIET + 4)
    clear_merges()
    record_landed(run.branch)
    own = threading.Thread(target=teardown.end_own, args=(loop.rc_sweep_stop, S.log),
                           kwargs={'keep_page': not loop.POWER}, daemon=True)
    own.start()
    own.join(OWN)
    S.clear_stop()
    S.log(f'run stopped ({how}); tried this run: {", ".join(sorted(run.tried)) or "none"}', S.EV_STOPPED)
    if loop.POWER:
        loop.power_now()
    return 0


def end_merges_soon() -> None:
    freeze.quiet(QUIET)
    end_merges()


def end_merges() -> None:
    """End the gates and what else the merges wait for (fix sessions, retests), with their records: the next run builds
    those merges again."""
    from agent_runner import merge
    gates = merge.gate_runs()
    try:
        more = json.loads(S.C.notes('merge.procs').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        more = []
    live = [s['pid'] for s in [*gates, *more] if merge.gate_alive(s)]
    for pid in live:
        plat.terminate(pid) if plat.WINDOWS else merge.end_group(pid)
    end = time.monotonic() + 1.5
    while any(map(plat.alive, live)) and time.monotonic() < end:
        time.sleep(0.05)
    for pid in live:
        plat.kill_tree(pid)  # what ignored SIGTERM; its group may outlive the shell it started in
    for s in gates:
        Path(s['rec']).unlink(missing_ok=True)
        Path(s['out']).with_suffix('.rc').unlink(missing_ok=True)  # the kill's own exit code is no result


def _there(d: Path, ref: str) -> bool:
    return not S.git('rev-parse', '-q', '--verify', ref, cwd=d).returncode


def clear_merges() -> None:
    """No half merge is left in the main checkout (only one that `land` began there; a person's stays) or in the merge
    worktrees, which belong to the runner."""
    def gitdir(d: Path) -> Path:
        return Path(S.git('rev-parse', '--absolute-git-dir', cwd=d).stdout.strip() or d / '.git')
    main = gitdir(S.ROOT)
    end = time.monotonic() + QUIET
    while (main / 'index.lock').exists() and time.monotonic() < end:
        time.sleep(0.05)  # a git command there goes on when its run has ended
    if _there(S.ROOT, 'MERGE_HEAD'):
        try:
            ours = LANDS.match((main / 'MERGE_MSG').read_text(encoding='utf-8', errors='replace'))
        except OSError:
            ours = None
        if ours:
            S.git('merge', '--abort')
            S.log(f'the merge into {S.ROOT.name} under way was taken back; the next run makes it again')
    for d in S.SLOTS_DIR.glob('*') if S.SLOTS_DIR.is_dir() else []:
        if not re.fullmatch(r'merge2?|fix\d+', d.name) or not (d / '.git').exists():
            continue
        (gitdir(d) / 'index.lock').unlink(missing_ok=True)  # of a git that was ended with its fix session
        for head, what in (('MERGE_HEAD', 'merge'), ('CHERRY_PICK_HEAD', 'cherry-pick')):
            if _there(d, head):
                S.git(what, '--abort', cwd=d)
                S.clean(d)


def record_landed(branch: str) -> None:
    """The tasks of a batch that landed, which had not had their turn to record it."""
    from agent_runner import land, merge
    for tid, (base, merged) in list(merge.LANDED.items()):
        try:
            land.record_landed(tid, branch, base, merged, merge)
        except Exception as e:  # noqa: BLE001 - the stop goes on
            S.log(f'{tid}: landed, but could not be recorded: {e!r}')
        merge.LANDED.pop(tid, None)


# --- from another process --------------------------------------------------------------------------------------

def the_run() -> dict:
    """The process of the run that is up, as its start wrote it: {} when none is there by that record."""
    try:
        rec = json.loads(S.C.notes('run.pid').read_text(encoding='utf-8'))
        ok = plat.alive(rec['pid']) and rec.get('start') == plat.started(rec['pid'])
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {}
    return rec if ok else {}


def say(text: str, err: bool = False) -> None:
    try:
        print(text, file=sys.stderr if err else sys.stdout, flush=True)
    except OSError:  # who asked is gone with the run
        pass


def command(power: str = '') -> int:
    """`stop --force`: ask, wait until the run's process is gone (end it when it hangs), then say so."""
    from agent_runner import plan as P
    if not S.run_up():
        say('no run is up here: nothing to stop', err=True)
        return 1
    rec = the_run()
    if rec and os.environ.get(FROM) == str(rec['pid']):  # the page's: the run answers it, so it cannot wait for its end
        from agent_runner.config import runner_cmd
        plat.spawn_detached([*runner_cmd(), 'stop', '--force', *([f'--{power}'] if power else [])], cwd=S.ROOT,
                            env={k: v for k, v in os.environ.items() if k != FROM})
        say('stopping the run now')
        return 0
    if power:
        P.post(S.C, 'POWER', power)
    S.ask_stop(f'{S.C.command} stop --force', force=True)
    if not rec:
        end = time.monotonic() + HANG
        while S.run_up() and time.monotonic() < end:
            time.sleep(0.2)
        if S.run_up():
            say('asked the run to stop now, but it is still up, and which process it is cannot be told (a run started '
                'by an older version): stop it there', err=True)
            return 1
        say('run stopped')
        return 0
    if gone(rec, time.monotonic()):
        say('run stopped')
        return 0
    say('the run did not stop by itself; ending it')
    for sig in (signal.SIGTERM, getattr(signal, 'SIGKILL', signal.SIGTERM)):
        kill(rec, sig)
        if ended(rec, TERM):
            break
    if not ended(rec, TERM):
        say(f'the run (pid {rec["pid"]}) could not be ended', err=True)
        return 1
    clean_up()
    say('run stopped')
    if power and P.take(S.C, 'POWER'):  # the run never took it
        S.log(f'run stopped: {"suspending" if power == "suspend" else "shutting down"} the computer', S.EV_STOPPED)
        (plat.suspend if power == 'suspend' else plat.power_off)()
    return 0


def kill(rec: dict, sig) -> None:
    if plat.WINDOWS:  # the run alone: what it started is not under way for it (control sessions)
        sp.run(['taskkill', '/F', '/PID', str(rec['pid'])], capture_output=True)
        return
    try:
        os.kill(rec['pid'], sig)
    except OSError:
        pass


def ended(rec: dict, seconds: float) -> bool:
    end = time.monotonic() + seconds
    while (up := plat.alive(rec['pid']) and plat.started(rec['pid']) == rec.get('start')) and time.monotonic() < end:
        time.sleep(0.1)
    return not up


def gone(rec: dict, t0: float) -> bool:
    """Wait for the run to end by itself: BEGIN for it to begin the stop, HANG and a little for the whole of it."""
    while not ended(rec, 0):
        begun = the_run().get('stopping')
        if time.monotonic() - t0 > (HANG + 1 if begun else BEGIN):
            return False
        time.sleep(0.1)
    return True


def clean_up() -> None:
    """The run was ended: do what its own stop would have done. run.lock is held, so no run starts meanwhile."""
    from agent_runner import loop, page_only
    lock = plat.lock(S.C.notes('run.lock'))
    try:
        procs, running = {}, {}
        for n, (p, task) in loop.adopt(loop.default_branch()).items():
            procs[n], running[n] = p, task
        end_merges()
        loop.end_sessions(procs, running)
        clear_merges()
        S.clear_stop()
        S.log('run stopped (stop --force): it did not stop by itself and was ended', S.EV_STOPPED)
    finally:
        if lock:
            lock.close()
    try:
        if page_only.kept():  # the page went with the run
            page_only.start(S.ROOT, wait=0)
    except (Exception, SystemExit):  # noqa: BLE001
        pass
