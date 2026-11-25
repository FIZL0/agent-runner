"""The run itself: the keys typed into its terminal, halts and tells, CI, finishing a task and the loop
(`cmd_run`)."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import signal
import sys
import threading
import time
import traceback
import webbrowser
from contextlib import ExitStack
from pathlib import Path

from agent_runner import agent_hold, brief_arrives, claude_use, exit_hook, fallback as FB, freeze, settings_live, ci, file_split, gitops, loop_upgrade, no_commits, no_push, plan as P, plansync, plat, pr, shared_tools, stack, stop_now, undo, working_branch
from agent_runner.config import RUNNER, ensure_local, finished_mark, shown_cmd
from agent_runner.done import TESTED
from agent_runner.gitops import missing_remote, push
from agent_runner.state import (alarm, ask_stop, C, clean, clear_stop, commit_plan, default_branch, FORCED, forced,
    git, HIDDEN, IDLE, init, KEYS, KEYS_LOCK, LANDING, log, MERGE, note, PAUSED, plan_rel, plan_text, POWER, queued,
    READING, ROOT, share, SLOTS_DIR, stop_note, STOP_SAID, stopped_by, stopping, WAKE, EV_DEFERRED, EV_DROPPED, EV_IDLE, EV_LEFT, EV_NO_COMMITS, EV_PARKED, EV_RUN_UP,
    EV_STALLED, EV_STOP_ASKED, EV_STOP_BACK, EV_STOPPED, EV_CONTEXT)
from agent_runner.autorelease import auto_release, auto_release_of, AUTO_RELEASE_SEEN, landed_since_release
from agent_runner.brief import no_remote_line
from agent_runner.sched import agent_held, blocked_by_edits, forgive_park, keep_claims, note_committed, PARK_LIMIT, parked_attempts, pick, splitting, tasks
from agent_runner.tools import take_end
from agent_runner.login import retry_held, unlogged
from agent_runner.asks import block_asks, EV_FINISHED, no_slot, park_asked, unblocked_asks
from agent_runner.slots import (adopt, backend, DISK_AT, DISK_SAID, du, free_branch,
    free_gb, GB, hidden_line, HiddenMux, MUX, remote_any, remote_line, REMOTE_URL, resume, save_leftovers,
    single_run, slot_env, slot_shim, SLOTS, start, transcript, trim, unmerged, budget_mark, budgets, SPENT)
from agent_runner.teardown import close_page, end_own, PAGE, RUN_LOCK, wait_last_run
from agent_runner.watch import (_account, api_down, auto_upgrade, code_start, context_over, cut_off, drop_session_tmp,
    end_orphans, memory_watch, queue_cut_off, queue_resume, ask_restart, restart_if_upgraded, resumes, RESUMES_MAX, stalled,
    START_TRIES, state_line, stats, stop_hook, stop_waiter, sweep_tmp, update_watch, upgrade, usage_pct, watch_code, weekly)
from agent_runner.join import EDITED, EDITS_POLL, ELSEWHERE, REMIND_EVERY, TASK_SID, WAITING
from agent_runner.land import drop_wips, idle_line, prune_wips, reopen_landed, REOPENED, retry_reopened, wip_main, no_gate_line
from agent_runner.merge import (AHEAD_BUSY, AHEADS, before_start_fails, FIX_DIRS, FIX_DIRS_LOCK, FIXED, gate_runs,
    HELD, last_words, left_merging, merge)
from agent_runner.control import hand_hook, rc_sweep_start, start_control, start_control_server
from agent_runner.feed import rc_sweep_stop


def nap(s: float) -> None:
    WAKE.wait(s)  # set by a key typed here, or by `stop_now.watch` for one a command left
    WAKE.clear()


def read_keys() -> None:
    """A daemon thread's loop: every line typed into the run's terminal (`run N` in the foreground) is acted on at once (`take_keys`), and
    the loop is woken for what only it can do (ending sessions, a new slot).

    A thread rather than select() on stdin, which only works on POSIX. Started only when stdin is a tty.
    """
    for line in sys.stdin:
        KEYS.append(line.strip().lower())
        take_keys()
        WAKE.set()


def keys_help(view: bool = False) -> str:
    """The `?` block, shaped like `agent-runner help`, ruled off so it stands out from the log. `view`: as the
    run view (`attach`, another process) prints it, where Ctrl-C leaves the view and this process's state
    line would not be the run's."""
    rule = '-' * 78
    ctrl_c = ('Ctrl-C leaves this view; the run keeps going.' if view else
              'Ctrl-C ends the runner only: sessions keep running, and the next run adopts them.')
    now = '' if view else f'now: {state_line()}\n'
    return f"""{rule}
runner keys: type one here and press Enter

    s        stop gently: no new tasks, the running ones finish and merge, then the run exits
             (its run page stays up)
    s!       stop now: end the agent sessions (each resumes where it was in the next run) and the
             merges under way (the next run makes them again), and exit at once (its run page stays up)
    p        pause: no new tasks, and the run stays up
    u        upgrade agent-runner now (the run restarts on it); restart: only restart, for the settings that apply on the next run
    f        force: start tasks past the session and weekly usage caps (as --force)
    +        one slot more
    -        one slot fewer (a running task in it finishes first)
    slots N  N slots (+N, -N: that many more or fewer)
    z        suspend the computer once the run stops, or when it goes idle
    x        shut the computer down once the run stops, or when it goes idle
    Enter    open the control sessions at claude.ai/code (with [run] remote)
    ?        this help

    s, p, f, z and x take themselves back when typed again.
    {ctrl_c}

{now}{rule}"""


def take_keys() -> None:
    """Act on the lines typed into the run's terminal or the run view (see `keys_help`), and on a power choice `./run stop
    --suspend|--shutdown` left. Logged at once; ending sessions and adding a slot happen on the loop's next
    pass, which a key wakes."""
    global POWER, SLOTS
    with KEYS_LOCK:
        if power := P.take(C, 'POWER'):  # `stop --suspend|--shutdown`: the last one asked
            POWER = power[-1]
            share(POWER=POWER)
        KEYS.extend(cli_keys())
        while KEYS:
            k, _, want = KEYS.pop(0).partition(' ')
            if not k or k == 'remote':  # Enter here, or in the run view (C26: it posts 'remote')
                if remote_any():
                    open_remote()
                elif k:
                    log(f'Remote Control is off ([run] remote): nothing to open at {REMOTE_URL}')
                continue
            on = {'s': stopping, 'p': lambda: PAUSED[0], 'f': lambda: FORCED[0],
                  'z': lambda: POWER == 'suspend', 'x': lambda: POWER == 'shutdown'}.get(k)
            if on and want in ('on', 'off') and on() == (want == 'on'):
                log(f'{k} {want}: already so ({state_line()})')
                continue
            if k == 'slots':
                try:
                    n = SLOTS + int(want) if want[:1] in '+-' else int(want)
                except ValueError:
                    log(f'slots wants a number, +N or -N, not {want!r}')
                    continue
                if n < 1:
                    log('one slot is the fewest; s stops the run')
                    continue
                was, SLOTS = SLOTS, n
                share(SLOTS=SLOTS)
                log(f'slots: {SLOTS}' + (f' (slots past {SLOTS} close once their tasks end)' if n < was else ''))
                continue
            if k == 's' and stopping():
                clear_stop()
                STOP_SAID[0] = False  # F42: said here, so the loop does not say it again
                log('stop taken back: starting tasks again', EV_STOP_BACK)
            elif k == 's':
                ask_stop('s')
                log('stopping: no new tasks; the running ones finish and merge, then the run ends (s again: undo)')
            elif k == 's!':
                ask_stop('s!', force=True)
                log('stopping now: ending the agent sessions (each resumes in the next run) and the merges under way (the '
                    'next run makes them again)')
            elif k == 'p':
                PAUSED[0] = not PAUSED[0]
                log('paused: no new tasks; the run stays up (p again: go on)' if PAUSED[0] else
                    'pause taken back: starting tasks again')
            elif k == 'f':
                FORCED[0] = not FORCED[0]
                log('forced: starting tasks past the usage caps (f again: undo)' if FORCED[0] else
                    'force taken back: the usage caps hold new tasks again')
            elif k in ('u', 'restart'):  # the loop restarts on what it installs; F97: or to read its settings again
                (ask_restart if k == 'restart' else threading.Thread(target=upgrade, daemon=True).start)()
            elif k in ('+', '-'):
                if k == '-' and SLOTS == 1:
                    log('one slot is the fewest; s stops the run')
                    continue
                SLOTS += 1 if k == '+' else -1
                share(SLOTS=SLOTS)
                log(f'slots: {SLOTS}' + (f' (slot {SLOTS + 1} closes once its task ends)' if k == '-' else ''))
            elif k in ('z', 'x'):
                want = 'suspend' if k == 'z' else 'shutdown'
                POWER = '' if POWER == want else want
                share(POWER=POWER)
                log(f'{want} once the run stops, or when it goes idle ({k} again: undo)' if POWER else
                    f'{want} taken back: the computer stays on')
            elif k in ('?', 'h', 'help'):
                print(keys_help(), flush=True)
            else:
                print(f'unknown key {k!r}\n{keys_help()}', flush=True)


def cli_keys() -> list[str]:
    """The keys `agent-runner pause|force|slots|key` left in `<notes>/KEYS`, one a line, taken once. Moved
    aside before it is read, so a key written meanwhile goes in a new file for the next pass."""
    return [k.lower() for k in P.take(C, 'KEYS')]


def open_remote() -> None:
    """Enter in the run's terminal or the run view, with `[run] remote`: the sessions page, in the default browser (a claude.ai
    link the desktop app is set to take opens there). No browser here (ssh): the link, to open elsewhere."""
    try:
        ok = webbrowser.open(REMOTE_URL)
    except Exception:  # noqa: BLE001 - a broken browser setup must not take the key reader down
        ok = False
    log(f'opening {REMOTE_URL}' if ok else f'no browser here: open {REMOTE_URL} on any device, or the Claude app')


def send_key(*keys: str) -> None:
    """What a typed key does, from any terminal or a remote session: the run takes it on its next pass."""
    P.post(C, 'KEYS', *keys)


RUNNING_SINCE: dict[tuple[str, str], float] = {}  # (slot, task) -> when write_state first saw it running


def run_version() -> str:
    """F90: the version this run's code is, for STATE: an open TUI or run page restarts or reloads on a newer one."""
    from agent_runner import __version__
    return __version__


def write_state(running: dict, held=()) -> None:
    """`<notes>/STATE`, for `agent-runner status`: what the keys have set, what each slot is on and since when,
    what is merging, and the account's usage (as the cap reads it, at most every 5 minutes)."""
    work = {str(n): t[0] for n, t in running.items()}
    now = time.time()
    for k in [k for k in RUNNING_SINCE if work.get(k[0]) != k[1]]:
        RUNNING_SINCE.pop(k)
    since = {n: RUNNING_SINCE.setdefault((n, tid), now) for n, tid in work.items()}
    # B834: merge:ahead is the helper that builds a merge ahead, no task; its name has the prefix for `freeze._merges`
    merging = sorted({t.name[6:] for t in threading.enumerate()
                      if t.name.startswith('merge:') and t.name != 'merge:ahead' and t.is_alive()} | set(held))
    # what the cap last read (`capped`, the start line); never a fetch of its own from here
    got = _account[1] if isinstance(_account[1], dict) and claude_use.account(C) else {}
    use = {k: got[k].get('utilization') for k in ('five_hour', 'seven_day') if isinstance(got.get(k), dict)}
    tmp = C.notes('STATE.tmp')
    from agent_runner.ui_model import agent_problem, no_settings
    try:
        tmp.write_text(json.dumps({'at': dt.datetime.now().isoformat(timespec='seconds'), 'state': state_line(),
                                   'slots': SLOTS, 'running': work, 'since': since, 'merging': merging, 'usage': use,
                                   'spend': {n: SPENT[n] for n in work if n in SPENT},  # F103
                                   'idle': IDLE[0], 'paused': PAUSED[0], 'stopping': stopping(),
                                   'forced': FORCED[0], 'power': POWER, 'version': run_version(),
                                   'agent_problem': agent_problem(C), 'no_settings': bool(no_settings(C))}),  # B764b, F178
                       encoding='utf-8')
        os.replace(tmp, C.notes('STATE'))
    except OSError:  # Windows: `status` has STATE open this instant; the next pass writes it
        pass


def kept_keys() -> dict:
    """What the run before an upgrade restart had set with its keys (`restart_if_upgraded`), once."""
    try:
        return json.loads(os.environ.pop('AGENT_RUNNER_KEEP', '') or '{}')
    except ValueError:
        return {}


def drop_earlier_stop(keep: dict) -> None:
    """B137: a stop belongs to the run it was asked of. `Run.end` clears it as that run exits; one still on disk
    when a run starts was left by a run that ended another way (killed, crashed), and is dropped. Only an upgrade
    restart keeps it (`keep['stop']`): that is the same run, carrying on."""
    if stopping() and not keep.get('stop'):
        clear_stop()
        log('cleared a stop request left by an earlier run')


def end_sessions(procs: dict, running: dict) -> None:
    """`s!`: end every agent session now, each queued to resume in its slot when a run next starts. Its
    worktree stays as the session left it; nothing it did is merged. B803: `[run] on_exit` runs once they ended."""
    for n, (pid, sid, _) in list(procs.items()):
        tid = running[n][0]
        if not transcript(sid):  # it never started (held at a dialog): `--resume` would find no session and sit
            log(f'slot {n}: {tid} ended (s!) before its session began; it starts afresh in the next run')
            continue
        queue_resume(tid, n, sid, 'stopped with s!')
        log(f'slot {n}: {tid} ended (s!); it resumes in this slot in the next run')
    exit_hook.end_forced(procs, end_orphans)
    exit_hook.start_forced(procs)
    procs.clear()
    running.clear()


from agent_runner.loop_requests import (DISCARDED, halt_requests, halt_answer, discard_task, halts, tell_requests, tell_answer, tells, restyle_requests, restyle_mark, type_into, park_for_restyle, restyle_landed, restyles)  # noqa: F401


def power_now() -> None:
    """After a stop, with `z`, `x`, --suspend or --shutdown: suspend or power off now, no idle grace."""
    log(f'run stopped: {"suspending" if POWER == "suspend" else "shutting down"} the computer', EV_STOPPED)
    if rc := (plat.suspend if POWER == 'suspend' else plat.power_off)():
        log(f'the {POWER} command failed (exit {rc})')


def low_disk(free_slots) -> bool:
    """Less free disk than `[run] min_free_gb`: clean the free slots and the merge worktree (at most every 10 min),
    and True while it stays low, so no new task starts and fills the disk up."""
    want = C.run['min_free_gb']
    if not want or free_gb() >= want:
        DISK_SAID[0] = False
        return False
    if time.time() - DISK_AT[0] > 600:
        DISK_AT[0] = time.time()
        why = f'the disk is under [run] min_free_gb ({want} GB free)'
        for n in free_slots:
            if (d := SLOTS_DIR / f's{n}').is_dir():
                trim(d, f'slot {n}', why)
        if (d := SLOTS_DIR / 'merge').is_dir() and MERGE.acquire(blocking=False):
            try:
                trim(d, 'merge worktree', why)
            finally:
                MERGE.release()
        if (d := SLOTS_DIR / 'merge2').is_dir() and not AHEAD_BUSY.locked() and not AHEADS:
            trim(d, 'merge-ahead worktree', why)
        with FIX_DIRS_LOCK:
            idle = [d for d in SLOTS_DIR.glob('fix*') if re.fullmatch(r'fix\d+', d.name) and int(d.name[3:]) not in FIX_DIRS]
            FIX_DIRS.update(int(d.name[3:]) for d in idle)  # held while cleaned, so no fix starts in one
        try:
            for d in idle:
                trim(d, f'fix worktree {d.name[3:]}', why)
        finally:
            with FIX_DIRS_LOCK:
                FIX_DIRS.difference_update(int(d.name[3:]) for d in idle)
                FIX_DIRS_LOCK.notify_all()
        if free_gb() >= want:
            return False
    if not DISK_SAID[0]:
        DISK_SAID[0] = True
        log(f'disk: {free_gb():.1f} GB free, under [run] min_free_gb ({want} GB), even with the free worktrees '
            f'cleaned: no new task starts until there is room')
        print('\a', end='', flush=True)
    return True


def drop_extra_slots(slots: int, busy) -> None:
    """Remove slot worktrees past this run's count (`slots` was lowered) that nothing uses: no session, nothing
    uncommitted. Moved aside at once, deleted in the background; a task branch lives on in the repo."""
    rm = lambda t: threading.Thread(target=shutil.rmtree, args=(t,), kwargs={'ignore_errors': True},
                                    daemon=True).start()
    for t in SLOTS_DIR.glob('.removed-*'):  # what a run that was stopped mid-delete left
        rm(t)
    for d in SLOTS_DIR.glob('s*'):
        if not re.fullmatch(r's\d+', d.name) or int(d.name[1:]) <= slots or int(d.name[1:]) in busy:
            continue
        if git('status', '--porcelain', cwd=d).stdout.strip() or git('rev-parse', cwd=d).returncode:
            log(f'slot {d.name[1:]}: past the {slots} slots, but it has uncommitted work (or is not a worktree): kept')
            continue
        size = du(d)
        trash = SLOTS_DIR / f'.removed-{d.name}-{int(time.time())}'
        d.rename(trash)
        git('worktree', 'prune')
        rm(trash)
        log(f'slot {d.name[1:]}: past the {slots} slots and unused: removed ({size / GB:.1f} GB)')




from agent_runner.loop_watch import (ci_flows, watch_ci, watch_issues, CI_UNSEEN, CI_RERUN, CI_AT, ISSUES_UNSEEN, ISSUES_AT)  # noqa: F401
from agent_runner import loop_after  # noqa: E402
from agent_runner.loop_sweep import SWEPT, SWEEP_AT, sweep_unmerged  # noqa: E402,F401  (C53)

def not_attempt(tid: str, branch: str) -> bool:
    """The session's last commit matches `[run] not_attempt` ({id} = the task): a phase that leaves the task open
    on purpose (a spec written for a later session to port from), so the task may start again once it merges."""
    rx = C.run['not_attempt']
    last = git('log', '-1', '--format=%s', f'{stack.fork(tid, branch)}..task/{tid}').stdout.strip()
    return bool(rx and last and re.search(rx.replace('{id}', re.escape(tid)), last))


ON_EDITS: set[str] = set()  # B227: tasks whose merge waits for a person's edits in the main checkout


def finish(tid: str, n: int, sid: str, branch: str) -> None:
    """After a slot's session: merge its branch, or park it as wip/<ID> and say why."""
    try:
        if _finish(tid, n, sid, branch):
            (plansync.ticks(C) / tid).unlink(missing_ok=True)
            plansync.release(C, tid)
            try:
                prune_wips(branch, force=True)  # F23: ticked by this merge: its wip/<ID> go with it
            except Exception as e:  # never reads as a crashed merge
                log(f'{tid}: could not clear the wip branches of done tasks: {e!r}')
    except Exception as e:  # a merge thread that dies silently leaves the branch unmerged with no word why
        note(f'{tid}: LEFT FOR A HUMAN — the merge crashed: {e!r}')
        log(f'{tid}: LEFT FOR A HUMAN — the merge crashed: {e!r}', EV_LEFT, tid, why=f'the merge crashed: {e!r}')

def _finish(tid: str, n: int, sid: str, branch: str) -> bool:
    """False when task/<tid> waits for the next run to merge it."""
    halted = lambda: tid in halt_requests()  # noqa: E731
    if (unsettled := agent_hold.once_right(tid, lambda: stack.settle(tid, branch, halted), halted)) is False and not halted():
        return False  # F198, B764c
    if halted():  # B19: dropped or changed before its merge: never lands
        did = discard_task(tid, None)
        DISCARDED[tid] = 'its finished branch never merged' + (f' ({", ".join(did)})' if did else '')
        return True
    landed_for = ''
    if rs := restyle_mark(tid):  # F19: a restyle held it while it ran
        passed = (not git('rev-parse', '--verify', '-q', TESTED + tid).returncode
                  or (plansync.ticks(C) / tid).exists())
        if rs.get('how') == 'park' and not passed:  # stopped at a clean point: parked, not merged
            note(f'{tid}: {park_for_restyle(tid, rs["rid"], branch)}')
            return True
        C.notes(f'{tid}.restyle').unlink(missing_ok=True)
        landed_for = rs['rid']  # its done passed (it was in its test gate) or it was merging: it lands
    if not (commits := git('log', '--format=%s', f'{stack.fork(tid, branch)}..task/{tid}').stdout.splitlines()):
        git('branch', '-D', f'task/{tid}')
        git('update-ref', '-d', TESTED + tid)
        note(f'{tid}: no commits — nothing to merge')
        log(f'{tid}: no commits — nothing to merge', EV_NO_COMMITS, tid)
        if n:  # B774: a slot's session, not a `take`
            no_commits.ended(tid, last_words(sid) if sid and sid != '(unknown)' else '', branch)
        return True
    no_commits.forget(tid)
    if sid and sid != '(unknown)':
        TASK_SID[tid] = sid  # its repair, if the merge fails the gate, starts from this session
    over = ''
    if bm := budget_mark(tid):  # F103: stopped over its budget: parked below, unless its done passed
        C.notes(f'{tid}.budget').unlink(missing_ok=True)
        if git('rev-parse', '--verify', '-q', TESTED + tid).returncode and not (plansync.ticks(C) / tid).exists():
            over = f'stopped over its budget: {bm}'
    while (why := over or unsettled or agent_hold.once_right(tid, lambda: merge(tid, branch), halted)) and why.startswith((EDITED, ELSEWHERE)):
        # Tested and only waiting on somebody's edits: parking it would throw the work away for a fresh
        # attempt. The branch stays task/<ID> (`pick` leaves it alone, the next run's `unmerged` takes it).
        alarm(f'{tid} is not merging: ' + ('uncommitted edits in the main checkout' if why.startswith(EDITED)
                                           else f'{branch} is not checked out'),
              f'{why}. task/{tid} stays, tested, and merges again once ' +
              ('they are committed (or moved to a branch).' if why.startswith(EDITED) else
               f'{branch} is checked out in {ROOT} again.'))
        since = time.time()
        ON_EDITS.add(tid)
        while blocked_by_edits(tid, branch):
            if stopping():
                ON_EDITS.discard(tid)
                log(f'{tid}: the run stops; task/{tid} waits for the next run to merge it', EV_DEFERRED, tid)
                return False
            if time.time() - since > REMIND_EVERY:  # still nobody: say it again, as loud
                since = time.time()
                alarm(f'{tid} is still not merging', f'{why}. task/{tid} has waited since '
                      f'{dt.datetime.fromtimestamp(since - REMIND_EVERY):%H:%M} or earlier.')
            time.sleep(EDITS_POLL)
        ON_EDITS.discard(tid)
        log(f'{tid}: the main checkout is clear again; merging task/{tid} now')
    if why is False:  # B764c: it needed a fix session, and the wait for one ended
        return halted() and _finish(tid, n, sid, branch)  # dropped meanwhile: it goes as one dropped before its merge
    if late := restyle_mark(tid):  # F19: a restyle that asked while this merge ran
        landed_for = landed_for or late['rid']
        C.notes(f'{tid}.restyle').unlink(missing_ok=True)
    if not why:
        if landed_for:
            restyle_landed(tid, landed_for)
        return True
    # Parked as wip/<ID>: a task/<ID> ahead of the branch reads as finished-and-waiting to `pick`, which
    # would then skip the task for good. As wip/ the task can start again, with the old attempt to read.
    if git('branch', '-M', f'task/{tid}', wip := free_branch(f'wip/{tid}')).returncode:
        note(f'{tid}: LEFT FOR A HUMAN — {why}; task/{tid} could not be parked, so nothing restarts it')
        log(f'{tid}: LEFT FOR A HUMAN — {why}. task/{tid} could not be renamed to {wip}, so no run restarts the '
            f'task until it is merged, renamed or deleted by hand. Its {len(commits)} commits: {" / ".join(commits)[:300]}',
            EV_LEFT, tid, why=why)
        return True
    git('update-ref', '-d', TESTED + tid)
    for h in git('for-each-ref', '--format=%(refname)', f'{HELD}{tid}/', f'{FIXED}{tid}/').stdout.split():
        git('update-ref', '-d', h)
    note(f'{tid}: not merged, parked as {wip} — {why}')
    log(f'{tid}: not merged, parked as {wip} — {why}. Its {len(commits)} commits are kept there. The task stays '
        f'open and starts again by itself in the next run (in this one once its line is edited: '
        f'`{C.command} plan note {tid} "..."`), its next attempt pointed at {wip}', EV_PARKED, tid, why=why, wip=wip)
    if out := push(ROOT, wip):  # the one copy of that work: get it off this disk
        log(f'{tid}: {out}')
    if len(parked_attempts().get(tid, [])) >= PARK_LIMIT:
        log(f'{tid}: parked {PARK_LIMIT} times now; the next pick blocks it on a person instead of starting it again')
    return True


# --- usage caps and power ------------------------------------------------------

def capped(force: bool, own: bool = False) -> str | None:
    """Why no new task may start: the 5-hour session usage at or past `[run] session_max`, or the 7-day usage
    at or past `[run] weekly_max` (and not --force). None when neither is. `own`: there are tasks it holds alone (claude_use.own_tasks)."""
    if force or not (own or claude_use.account(C)):
        return None
    for name, what, key in (('five_hour', 'session', 'session_max'), ('seven_day', 'weekly', 'weekly_max')):
        w = usage_pct(name)
        if w is not None and w >= C.run[key]:
            return f'{what} usage {w}% >= {C.run[key]}%'
    return None


def cap_stop_detail() -> str:
    """B102: the usage-cap alarm's detail, the remote-friendly way to go on first (a control session,
    `[run] command` force), the run view's f + Enter last."""
    return ('the running tasks finish and merge; new ones wait for the reset. To go on now: say force in '
            f'a control session, or run `{C.command} force`, or type f + Enter in the run view '
            f'({C.command} attach).')
SHUTDOWN_GRACE = 120  # s the run must stay idle first; new work or a stop in that time cancels it
SLEPT_AT = [-1.0]  # the idle stretch (its idle_at) the machine was suspended in: once per stretch, not on every wake


def power_due(idle_at: float) -> bool:
    """--shutdown or --suspend, and the run has been idle SHUTDOWN_GRACE s, in a stretch not slept through yet."""
    return bool(POWER) and time.time() - idle_at >= SHUTDOWN_GRACE and SLEPT_AT[0] != idle_at


def shut_down(idle_at: float) -> bool:
    """With --shutdown or --suspend, after SHUTDOWN_GRACE s idle: power off, or suspend. The caller checked
    that nothing runs, merges or may start. True once the power-off command has been accepted, so the run
    ends; a refused one is logged and the run stays.

    A suspend returns False: when the machine wakes, the run is still there and carries on, idle. It does not
    suspend again until it has had work and gone idle again, so someone who wakes the machine to use it is
    not put back to sleep two minutes later."""
    if not power_due(idle_at) or stopping():
        return False
    if POWER == 'suspend':
        log('nothing left to do and nothing merging: suspending the computer (--suspend)')
        SLEPT_AT[0] = idle_at
        if rc := plat.suspend():
            log(f'the suspend command failed (exit {rc}); staying awake')
        else:
            log('suspend accepted: on waking the run carries on, and suspends again only after its next work')
        return False
    log('nothing left to do and nothing merging: shutting the computer down (--shutdown)')
    if rc := plat.power_off():
        log(f'the power-off command failed (exit {rc}); staying up')
        return False
    return True


def dry_run(slots: int, branch: str) -> int:
    """What `slots` free slots would start right now, in order, and why the rest of the open tasks wait."""
    if nogate := no_gate_line():
        print(nogate)
    running: dict = {}
    for n in range(1, slots + 1):
        if not (t := pick(running, set(), branch)):
            break
        running[n] = t
        print(f'slot {n}: {t[0]}  ({t[1]}; {", ".join(sorted(t[2])) or "no files listed"})')
    if not running:
        print('nothing to start now; every open task, and why it waits:')
    held: dict = {}
    pick(running, set(), branch, why=held)  # with these slots taken: why each open task does not start
    started = {t[0] for t in running.values()}
    groups: dict[str, list[str]] = {}
    for tid, (kind, detail) in held.items():
        if tid in started:
            continue
        kind = 'next, once a slot is free' if kind == 'free' else kind
        groups.setdefault(kind, []).append(f'{tid} ({detail})' if detail else tid)
    ls = plan_text(branch)
    can = set(held) | started
    groups['waiting on an after:, a subtask, or Stretch/Parked'] = \
        [tid for _, box, tid, _, _ in P.iter_tasks(ls) if box == ' ' and tid not in can]
    groups['blocked'] = [tid for _, box, tid, _, _ in P.iter_tasks(ls) if box == '~']
    for kind, ids in groups.items():
        if ids:
            print(f'{kind}: {", ".join(ids)}')
    if wips := wip_main():
        print(f'main-checkout edits moved aside, still to pick up: {", ".join(wips)}')
    return 0


def reserve_branch_ids() -> None:
    """Hold the ids the unmerged task branches added (`plan.reserved`), so ids handed out before the list
    existed, or by a session that wrote its plan line by hand, are not handed out again."""
    files = [plan_rel('TODO.md'), plan_rel('DONE.md')]
    have = P.reserved(C.root) | {tid.rstrip('.') for f in files
                                 for _, _, tid, _, _ in P.iter_tasks(git('show', f'HEAD:{f}', cwd=C.root).stdout.splitlines())}
    new = set()
    for b in git('for-each-ref', '--format=%(refname:short)', 'refs/heads/task/', cwd=C.root).stdout.split():
        for f in files:
            new |= {t for _, _, tid, _, _ in P.iter_tasks(git('show', f'{b}:{f}', cwd=C.root).stdout.splitlines())
                    if (t := tid.rstrip('.')) not in have}
    P.reserve(C.root, *sorted(new))


def backlog_slots(slots: int, behind: int) -> int:
    """How many slots may run while `behind` finished tasks wait for the merge: all of them up to
    `[run] max_unmerged`, then one fewer for each half batch (`batch_max` / 2 tasks) past it, so the run eases
    off as the merges fall a few gates behind and picks up again as they land, instead of piling up finished
    work that goes stale (more conflicts, more fix sessions) before the gate can take it."""
    cap, step = C.run['max_unmerged'], max(1, C.run['batch_max'] // 2)
    return slots if not cap else max(0, slots - -(-max(0, behind - cap) // step))


def backlog_line(slots: int, allowed: int, behind: int) -> str:
    if allowed == slots:
        return f'merges caught up ({behind} waiting): all {slots} slots take new tasks again'
    return (f'{behind} finished tasks wait for the merge ([run] max_unmerged {C.run["max_unmerged"]}): '
            f'new tasks start in {allowed} of {slots} slots until it catches up')


# A Claude Code session's own markers, which its Bash commands inherit. A run started from one (a person's
# session, a control session) must not hand them on: CLAUDE_CODE_CHILD_SESSION turns off every slot's
# transcript, and the runner reads a session as dead without one. Config (CLAUDE_CONFIG_DIR, ANTHROPIC_*) stays.
SESSION_ENV = ('CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION', 'CLAUDE_CODE_SESSION_ID', 'CLAUDE_PID', 'CLAUDE_EFFORT',
               'CLAUDE_CODE_ENTRYPOINT', 'CLAUDE_CODE_EXECPATH', 'CLAUDE_CODE_SESSION_ATTENDED',
               'CLAUDE_CODE_CHILD_NOTES_DIR', 'CLAUDE_CODE_MESSAGING_SOCKET', 'CLAUDE_CODE_MESSAGING_TOKEN')


def drop_session_env() -> None:
    """Out of this process, so no session it starts inherits them."""
    for k in SESSION_ENV:
        os.environ.pop(k, None)


def cmd_run(argv: list[str], prog: str = f'{RUNNER} run') -> int:
    """`prog` is what --help shows; a wrapping CLI passes its own (e.g. './kit run')."""
    drop_session_env()
    if not plat.WINDOWS and threading.current_thread() is threading.main_thread():
        for s in (signal.SIGTERM, signal.SIGHUP):  # a kill, a closed terminal: the same exit as Ctrl-C
            signal.signal(s, _interrupted)
    try:
        rc = run(argv, prog)
        if freeze.STOPPER:  # B827: the threads of the merges it ended are still there
            sys.stdout.flush()
            os._exit(rc)
        return rc
    except KeyboardInterrupt:
        # Exit now: a merge thread would otherwise keep the process up. Its merge worktree is thrown away; the
        # main checkout only ever moves to a tested commit, and a merge open there is waited for (up to a
        # minute) so it is not left half-done. The hidden sessions keep going and the next run adopts
        # them and merges what finished.
        try:
            log('run interrupted: the sessions keep running; the next run adopts them')
        except Exception:  # Ctrl-C before the config was read
            pass
        if LANDING.locked() and not git('rev-parse', '-q', '--verify', 'MERGE_HEAD').returncode:
            LANDING.acquire(timeout=60)  # mid-merge in the main checkout: let it commit or abort first
        os._exit(130)
    except Exception:  # its window closes with it: run.log is the only place the traceback survives
        try:
            log('run crashed:\n' + traceback.format_exc().rstrip())
        except Exception:
            pass
        raise


def _interrupted(*_) -> None:
    raise KeyboardInterrupt


def run(argv: list[str], prog: str) -> int:
    ap = argparse.ArgumentParser(prog=prog, description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('slots', nargs='?', default=None,
                    help="how many agents at once (default [run] slots), or 'once' for one task then stop")
    ap.add_argument('--force', action='store_true', help='keep starting tasks past the session and weekly usage caps')
    power = ap.add_mutually_exclusive_group()
    power.add_argument('--shutdown', action='store_true',
                       help=f'power the computer off once nothing is running or merging and no open task may start '
                            f'(after {SHUTDOWN_GRACE} s idle)')
    power.add_argument('--suspend', action='store_true',
                       help='as --shutdown, but suspend (sleep) instead; on waking the run carries on, and '
                            'suspends again only after its next work')
    ap.add_argument('--idle', type=int, default=None, help='seconds of quiet before a session is ended')
    ap.add_argument('--stall', type=int, default=None, help='seconds of quiet that count as stalled')
    ap.add_argument('--pause', type=int, default=None, help='seconds between a session ending and the next')
    ap.add_argument('--model', default=None, help='the agent model (default [models] code and kinds)')
    ap.add_argument('--dry-run', action='store_true', help='print what would start, and start nothing')
    ap.add_argument('--stop-hook', action='store_true', help=argparse.SUPPRESS)
    ap.add_argument('--stop-waiter', nargs=4, metavar=('PID', 'TRANSCRIPT', 'N', 'IDLE'), help=argparse.SUPPRESS)
    ap.add_argument('--slot-shim', metavar='JOB', help=argparse.SUPPRESS)
    ap.add_argument('--hidden', action='store_true', help=argparse.SUPPRESS)  # older launchers' flag; every run is
    a = ap.parse_args(argv)

    if a.stop_hook:  # these two run inside an agent session and need no repository
        return stop_hook(a.idle or 30)
    if a.stop_waiter:
        pid, t, n, idle = a.stop_waiter
        return stop_waiter(int(pid), t, int(n), int(idle))
    if a.slot_shim:
        return slot_shim(a.slot_shim)

    init()
    if not a.dry_run and working_branch.waits(ROOT):  # F447b: the one saved, before anything is read off the branch
        RUN_LOCK.append(wait_last_run())
        if working_branch.at_start(ROOT):
            working_branch.forget()
            init()
    no_push.require(C, ROOT)
    pr.require(C, ROOT)  # F419
    r = settings_live.start()  # F202a: what changes from here on is read by the loop
    if a.model:  # F125: another provider is refused here, not run as a claude model name; F443: a bare one is [models] provider's
        a.model = C.settle(a.model, 'run --model')
    once = a.slots == 'once'
    global POWER
    POWER = '' if once else 'shutdown' if a.shutdown else 'suspend' if a.suspend else ''
    try:
        slots = 1 if once else int(a.slots or r['slots'])
    except ValueError:
        ap.error(f"slots must be a number or 'once', not {a.slots!r}")
    global SLOTS
    SLOTS = slots
    if keep := settings_live.restore(kept_keys()):  # restarted on an upgrade: the slot count, pause, power and stop typed before it hold
        SLOTS = slots = keep['slots']
        POWER, PAUSED[0], FORCED[0] = keep['power'], keep['paused'], keep.get('forced', False)
    share(POWER=POWER, SLOTS=SLOTS)
    idle, stall, pause = a.idle or r['idle'], a.stall or r['stall'], a.pause or r['pause']
    model = a.model or r['model']
    C.run['model_flag'] = a.model or ''  # F105: `run --model M` sets every task without a model of its own

    branch = default_branch()
    if git('rev-parse', '--verify', '--quiet', branch).returncode:
        print(f'no branch {branch!r} to merge into — commit something first', file=sys.stderr)
        return 2
    if a.dry_run:
        return dry_run(slots, branch)

    if not RUN_LOCK:
        RUN_LOCK.append(wait_last_run())  # B144: held until run() returns; a start after a stop waits for it
    stop_now.begin()  # B827
    ensure_local(ROOT)  # this machine's runner.local.toml: made once (all comments), never rewritten, git-ignored
    drop_earlier_stop(keep)
    C.notes('POWER').unlink(missing_ok=True)
    global MUX
    MUX = HiddenMux()  # C26: every OS runs its slots hidden
    HIDDEN[0] = True  # Windows: consoles start hidden
    share(MUX=MUX)
    log(hidden_line())
    rc_sweep_start()  # B12, B195: end the control server an earlier run left, and an older version's feed and board
    start_control()  # F176: no session of an earlier run is picked up, but those a shutdown cut off come back
    start_control_server()
    from agent_runner.web import start_web
    PAGE.extend(filter(None, [start_web()]))  # F66: the run page ([run] web); F402b3a: the stop hands it over

    code_start(bool(r['auto_upgrade']))  # F149
    threading.Thread(target=update_watch, daemon=True).start()
    for w in C.warnings:
        log(w)
    from agent_runner.guide import install, point_rules
    if r['install_skill'] and (said := install()):
        log(said)
    if said := point_rules(C, git):
        log(said)
    if said := hand_hook(ROOT):
        log(said)
    if Path('/proc/meminfo').exists():
        threading.Thread(target=memory_watch, daemon=True).start()
    if sys.stdin.isatty():
        READING[0] = True
        threading.Thread(target=read_keys, daemon=True).start()
        print(keys_help(), flush=True)
    try:
        it = Run(a, slots, once, branch, model, idle, stall, pause)
        threading.Thread(target=stop_now.watch, args=(it,), name='stop-now', daemon=True).start()  # B827
        return it.go()
    finally:
        while RUN_LOCK:  # the run is over (its stop has ended its own processes): the next one may start
            RUN_LOCK.pop().close()


class Run:
    """The parallel run once it is set up (C9): its state, and one method per step of its loop. `go` opens it
    (adopts what an earlier run left) and ticks every 10 s until it stops; `tick` returns the exit code then."""

    def __init__(self, a: argparse.Namespace, slots: int, once: bool, branch: str, model: str, idle: int,
                 stall: int, pause: int):
        self.a, self.r = a, C.run
        self.slots, self.once, self.branch, self.model = slots, once, branch, model
        self.idle, self.stall, self.pause = idle, stall, pause
        self.running: dict[int, tuple] = {}
        self.procs: dict[int, tuple] = {}
        self.tried: set[str] = set()
        self.closed: set[str] = set()  # see retry_reopened
        self.idle_said, self.idle_at = False, 0.0
        self.free_at = {n: dt.datetime.min for n in range(1, slots + 1)}
        self.merging: list[threading.Thread] = []
        self.restart_due = False  # B227: new merges wait for the restart on changed code
        self.held_merges: list[tuple[str, int, str]] = []  # (task, slot, session id) of those
        self.stall_said: set[str] = set()
        self.failed_starts: dict[str, int] = {}  # task -> sessions that did not start
        self.cap_said = False
        self.cap_fell = False  # F142: said that new tasks start down the chain, this time past a cap
        self.held_said = slots  # the slot count `max_unmerged` last held the run to, as logged
        self.foreign: dict[int, int] = {}  # slot -> pid of a session no run knew (see queue_cut_off)
        self.waiting: dict[int, tuple] = {}  # slot -> (task, session id, why) queued to resume there
        self.tagged: dict | None = None  # MUX.panes(), looked at once a tick and only for a free slot

    def go(self) -> int:
        STOP_SAID[0] = False
        self.open()
        while (code := self.tick()) is None:
            nap(10)
        return code

    def merge_in(self, tid: str, n: int, sid: str) -> None:
        """Merge a finished task in a thread of its own; while a restart is due, hold it for the restarted run."""
        if loop_upgrade.hold_merge(self, tid, n, sid):
            return
        t = threading.Thread(target=finish, args=(tid, n, sid, self.branch), name=f'merge:{tid}')
        t.start()
        self.merging.append(t)

    def open(self) -> None:
        """Log what the run is, adopt the sessions and finished branches an earlier run left."""
        a, r, slots, branch = self.a, self.r, self.slots, self.branch
        procs, running, free_at = self.procs, self.running, self.free_at
        reserve_branch_ids()
        log(f'run: {slots} slots in {MUX.name}, merging into {branch}' +
            (f', session usage {usage_pct("five_hour")}%, weekly usage {weekly()}%' if not a.force and claude_use.account(C) else ''),
            EV_RUN_UP, slots=slots)
        if nogate := no_gate_line():
            log(nogate)
        if rline := remote_line():
            log(rline)
        if gone := missing_remote(ROOT):
            log(no_remote_line(gone))
        from agent_runner import context
        if heavy := context.warning(ROOT, r['rules'], C.raw['plan']['context_kb']):
            log(heavy)

        for n, (proc, task) in adopt(branch).items():
            procs[n], running[n] = proc, task
            free_at.setdefault(n, dt.datetime.min)

        exit_hook.adopt()  # B827: what a stop now left running
        shared_tools.start([n for n in range(1, slots + 1) if n not in procs])  # F168: nothing without [run.tools]
        foreign = self.foreign = queue_cut_off(branch, [n for n in range(1, slots + 1) if n not in procs])
        sweep_tmp(force=True)
        drop_extra_slots(slots, set(procs) | set(queued()) | set(foreign))
        left = left_merging()
        finished = unmerged(branch, [n for n in free_at if n not in procs and n not in queued() and n not in foreign])
        # the riders of a merge an earlier run gated wait from the start, so its turn finds them and reuses it
        WAITING.update(set(finished) & {t for g in gate_runs() for t in g.get('tids', [])})
        for tid in sorted(finished, key=lambda t: (bool(stack.stacked(t, branch)), t not in left)):  # the merge an earlier run left going first: it adopts that
            log(f'{tid}: ' + ('its merge was under way when the last run ended; adopting it' if tid in left else
                              'finished, not merged yet; merging it now'))
            self.tried.add(tid)
            self.merge_in(tid, 0, '(unknown)')
        if not self.merging:  # blocks freed by merges made while no run was up (a merge started above reopens by itself)
            with MERGE:
                reopen_landed(branch, 'a merge before this run')
        prune_wips(branch, force=True)  # F23: wip/<ID> of tasks ticked or dropped while no run was up
        block_asks(branch)  # F102: an ask an earlier run parked but could not block yet
        self.tried |= unblocked_asks()  # still not blocked: no slot starts it before its block lands

    def tick(self) -> int | None:
        """One pass of the loop: None to go on after a nap, else the run's exit code."""
        take_keys()
        if not forced():
            self.top()
        if forced():  # B827: with no session left too: merges are ended as well
            return stop_now.stop(self)
        self.tagged = None
        for n in list(self.free_at):
            self.slot(n)
        self.after()
        return self.end()

    def top(self) -> None:
        """The start of a tick: keys typed, the slot count, tells and halts, the stop note."""
        procs, running = self.procs, self.running
        sweep_tmp()
        agent_hold.tick(self)  # F202a, B764c: settings changed, a wrong [run] agent
        prune_wips(self.branch)  # F23: now and then, for tasks ticked or dropped by hand while the run is up
        take_keys()
        IDLE[0] = self.idle_said
        loop_upgrade.start_asked(self)
        write_state(running, [m[0] for m in self.held_merges])
        if SLOTS != self.slots:  # `+` or `-`: a slot past the count is watched to its end, never refilled
            self.slots = SLOTS
            for m in range(1, self.slots + 1):
                self.free_at.setdefault(m, dt.datetime.min)
        tells(procs, running)  # F16: plan tell / change, typed into a running slot's session
        restyles(procs, running, self.branch)  # F19: plan restyle parks a running interface task
        budgets(procs, running, type_into)  # F103: [run] task_tokens / task_usd stop a task at a clean point
        brief_arrives.check(procs, running)  # B775: a session whose brief did not arrive is ended
        FB.caps(procs, running, type_into)  # F106g: a Claude Code task at a usage cap goes on down the chain
        halts(procs, running, self.free_at, self.tried, self.branch, self.model, self.idle,
              self.slots)  # B19: plan drop / change of a running task
        self.waiting = {n: q for n, q in queued().items() if n in self.free_at and n <= self.slots}
        left = len(procs) + len(self.waiting) + len(self.foreign) + len(self.held_merges) + sum(t.is_alive() for t in self.merging)
        if said := stop_note(stopping(), left, stopped_by()):
            if STOP_SAID[0]:
                log(said, EV_STOP_ASKED, left=left)
            else:
                log(said, EV_STOP_BACK)

    def slot(self, n: int) -> None:
        """One slot's turn in a tick: watch its session, reap it when it ended, else fill the free slot."""
        if self.reap(n):
            return
        self.watch_stall(n)
        if self.held(n):
            return
        if n not in self.procs and n in self.waiting:  # a running task, not a new one: no stop or usage cap holds it
            self.resume_queued(n)
            return
        if n not in self.procs and dt.datetime.now() >= self.free_at[n]:
            self.fill(n)

    def reap(self, n: int) -> bool:
        """The slot's session ended: queue its resume if it was cut off (True: nothing more this tick), else
        save what it left and merge its task."""
        procs, r, branch = self.procs, self.r, self.branch
        if n in procs and not plat.alive(procs[n][0]):
            brief_arrives.check(procs, self.running)  # B775: it may have ended since `top` looked
            (pid, sid, since), task = procs.pop(n), self.running.pop(n)
            if over := context_over(sid, r.get('context_warn')):  # F25: soft only, the exit line says it
                log(f'slot {n}: {task[0]} exited ({stats(sid)}); {task[0]} {over[0]}', kind=EV_CONTEXT,
                    tid=task[0], **over[1])
            else:
                log(f'slot {n}: {task[0]} exited ({stats(sid)})')
            end_orphans()
            if backend().report_exit and (said := last_words(sid)):
                log(f'slot {n}: {task[0]} {r["backend"]}: {said[:500]}')
            exit_hook.start(n)  # B801: the slot is held until it has ended
            end = take_end(n, C)  # F102: the agent's `run finish` or `run ask`
            if end.get('how') == 'finish':
                log(f'slot {n}: {task[0]} finished: {end.get("text", "")[:300]}', EV_FINISHED, task[0],
                    summary=end.get('text', ''))
            waits = shared_tools.park_end(n, task[0], sid, end)  # F168: not tried: it goes on by itself
            if waits or end.get('how') == 'ask' and end.get('tid') == task[0] and \
                    park_asked(n, task[0], sid, end.get('text', ''), branch):
                self.tried |= set() if waits else {task[0]}
                self.free_at[n] = dt.datetime.now() + dt.timedelta(seconds=self.pause)
                return False
            if n <= self.slots and not ((m := finished_mark(n)) and m.exists()) and \
                    (fb := FB.fallback_due(task[0], sid)):  # F106g: it hit a cap; the chain names where it goes on
                FB.queue_fallback(task[0], n, sid, fb[1], fb[0])
                log(f'slot {n}: {task[0]} stopped because {fb[1]}; it goes on in this slot with {fb[0]}, '
                    f'the next in [models] fallback')
                return True
            if (why := cut_off(sid)) and n <= self.slots:
                if resumes(n, sid) < RESUMES_MAX:
                    # its worktree stays as the session left it, on task/<ID>: the resume goes on there
                    queue_resume(task[0], n, sid, why)
                    log(f'slot {n}: {task[0]} was cut off ({why}); it resumes in this slot once the API answers')
                    return True
                log(f'slot {n}: {task[0]} was cut off again ({why}) after {RESUMES_MAX} resumes; '
                    f'taken as ended')
            drop_session_tmp(sid)  # ended for good: a resume (above) keeps its scratchpad
            if save_leftovers(d := SLOTS_DIR / f's{n}', task[0], branch):
                clean(d)  # saved: the next start finds the slot clean
            if not not_attempt(task[0], branch):
                self.tried.add(task[0])  # one attempt per run: ticked, blocked or failed, a human looks next
            git('checkout', '-q', '--detach', cwd=SLOTS_DIR / f's{n}')
            self.merge_in(task[0], n, sid)
            self.free_at[n] = dt.datetime.now() + dt.timedelta(seconds=self.pause)
        return False

    def watch_stall(self, n: int) -> None:
        """Say once that the slot's session looks stalled; end it if its `done` already succeeded."""
        procs, running = self.procs, self.running
        if n in procs and procs[n][1] not in self.stall_said and \
                (why := stalled(procs[n][0], procs[n][1], self.stall)):
            self.stall_said.add(procs[n][1])
            if (m := finished_mark(n)) and m.exists():
                # its `done` succeeded, so the Stop hook's waiter should have ended it; that waiter can
                # be lost (two tasks once sat finished for hours), so the run ends it: next tick reaps it
                log(f'slot {n}: {running[n][0]} finished but {why}; ending it')
                plat.terminate(procs[n][0])
            else:
                log(f'slot {n}: {running[n][0]} looks stalled ({why}); look at {MUX.where(n)}', EV_STALLED, running[n][0])
                print('\a', end='', flush=True)

    def held(self, n: int) -> bool:
        """True when the slot is not this run's to fill this tick: a session no run knew or tracks sits in
        it, or it is an adopted slot past the run's count."""
        procs, foreign = self.procs, self.foreign
        if n not in procs and n in exit_hook.busy():
            return True  # B801: what it frees may be the next task's
        if n not in procs and n in foreign:
            if plat.alive(foreign[n]):
                return True  # see queue_cut_off: never a second agent in its worktree
            log(f'slot {n}: the session no run knew (pid {foreign.pop(n)}) ended')
            foreign.update(queue_cut_off(self.branch, [n]))
            return True
        if n not in procs and self.tagged is None:
            self.tagged = MUX.panes()  # a session that ended this tick is in it with a dead pid, as before
        if n not in procs and (old := self.tagged.get(f's{n}')) and plat.alive(old[1]):
            # a session no run tracks still sits in this slot (adopt found no session id): never reset the
            # worktree under it; the slot waits until that session ends
            if f'pid{old[1]}' not in self.stall_said:
                self.stall_said.add(f'pid{old[1]}')
                log(f'slot {n}: an untracked session (pid {old[1]}, {old[0]}) still runs there; slot held')
            return True
        if n > self.slots:  # an adopted slot past this run's count: watched to the end, never refilled
            if n not in procs and n not in self.waiting and n not in foreign:
                self.free_at.pop(n)
                drop_extra_slots(self.slots, set(procs) | set(queued()) | set(foreign) | exit_hook.busy())
            return True
        return False

    def resume_queued(self, n: int) -> None:
        """Resume the session queued for this slot (cut off, or ended on a usage limit) once the API answers."""
        if agent_held() or api_down(self.stall_said) or claude_use.resume_held(self, n):  # B799
            return
        tid, sid, why = self.waiting.pop(n)
        fb = FB.queued_model(tid)  # F106g: a new session on the chain's next model, not this one resumed
        C.notes(f'{tid}.resume').unlink(missing_ok=True)
        if p := resume(n, tid, sid, why, self.branch, self.model, self.idle, fallback=fb, slots=self.slots):
            self.procs[n] = p
            self.running[n] = next((t for t in tasks(self.branch) if t[0] == tid), (tid, '', set(), set()))
            self.tried.add(tid)
            self.idle_said = False

    def say_cap(self, w: str, own: str = '') -> None:
        """The usage-cap alarm, once each time a cap is reached. `own`: the tasks it holds alone (B791)."""
        if not self.cap_said:
            alarm(*claude_use.cap_alarm(w, own, cap_stop_detail()))
            self.cap_said = True

    def fill(self, n: int) -> None:
        """Start the next task in the free slot, unless one of the holds below stops it."""
        procs, running, slots, r = self.procs, self.running, self.slots, self.r
        if stopping():  # said once, with how many are left, by stop_note at the top of the tick
            return
        if PAUSED[0] or agent_held():  # B764c: never another agent instead
            return
        self.tried.difference_update(retry_held())  # F106e: held back for a login, not blocked yet: again
        own = claude_use.own_waiting(self)  # B791: these alone are held
        w, held = capped(self.a.force or FORCED[0], bool(own)), frozenset()
        if w is None:
            self.cap_said = self.cap_fell = False
        elif C.fallback or own:
            held = FB.USAGE_HELD  # F142: new tasks start down the chain instead
        else:
            self.say_cap(w)
            return
        behind = len(self.held_merges) + sum(t.is_alive() for t in self.merging)
        allowed = backlog_slots(slots, behind)
        if allowed != self.held_said:
            log(backlog_line(slots, allowed, behind))
            self.held_said = allowed
        if allowed < slots and sum(m <= slots for m in procs) >= allowed:
            return
        if api_down(self.stall_said):
            return
        if low_disk([m for m in range(1, slots + 1) if m not in procs and m not in self.waiting
                     and m not in self.foreign]) or shared_tools.low_memory():
            return
        if r['before_start'] and before_start_fails():
            if 'before_start' not in self.stall_said:
                self.stall_said.add('before_start')
                log(f'`{r["before_start"]}` fails: no new session starts until it passes')
                print('\a', end='', flush=True)
            return
        self.stall_said.discard('before_start')
        passed, no_api = claude_use.passed_over(self, own, held)
        task = pick(running, self.tried | passed | no_api, self.branch, claim=True) or file_split.no_task(self, held and not own)  # F200b
        if not task and passed and not self.cap_said and \
                (t := pick(running, self.tried, self.branch)) and t[0] in passed:
            self.say_cap(w, t[0] if own else '')  # F142: only the cap holds it: no provider in the chain is free for it
        if task:
            if unlogged(task[0], self.branch, self.model):  # F106e: its provider has no login: Needs you
                plansync.release(C, task[0])
                self.tried.add(task[0])  # the next pick takes another; an unblock or retry_held puts it back
                return
            if held and not self.cap_fell and (not own or task[0] in own):
                log(f'{w}: {"tasks on a claude model" if own else "new tasks"} start on the first free provider in [models] fallback until the reset')
                self.cap_fell = True
            if p := start(n, task, self.branch, self.model, self.idle, slots, held=held):
                procs[n], running[n] = p, task
                if self.once:  # one task: nothing new starts, and the run exits once it has merged
                    ask_stop('once')
                if self.idle_said:
                    log(f'run busy: new work ({task[0]})')
                    self.idle_said = False
            else:
                self.failed_starts[task[0]] = self.failed_starts.get(task[0], 0) + 1
                plansync.release(C, task[0])  # this start failed; another attempt can claim it
                if self.failed_starts[task[0]] >= START_TRIES:
                    self.tried.add(task[0])
                else:  # a terminal that was slow to open, or an agent that failed once: again later
                    log(f'slot {n}: {task[0]} will be tried again in {self.pause} s')
                    self.free_at[n] = dt.datetime.now() + dt.timedelta(seconds=self.pause)

    def after(self) -> None:
        """The end of a tick: reopened tasks, finished merges, upgrades, CI, control sessions, claims."""
        loop_after.after(self)  # C51: the body is in loop_after.py

    def end(self) -> int | None:
        """Stop the run once a stop has drained it; end `once`, say idle, or power off when nothing may start."""
        procs, waiting, merging, tried = self.procs, self.waiting, self.merging, self.tried
        # a slot asleep until a usage reset does not hold the stop; a session waiting to resume does
        if stopping() and not procs and not waiting and not merging and not exit_hook.busy():  # B801; `s!`: stop_now
            how = stopped_by()
            end_own(rc_sweep_stop, log, keep_page=not POWER)  # B144, F402b3a: its own are gone, or its page handed over, before it says so
            clear_stop()
            log(f'run stopped ({how}); tried this run: {", ".join(sorted(tried)) or "none"}', EV_STOPPED)
            if POWER:
                power_now()
            return 0
        quiet = not procs and not waiting and not merging and not exit_hook.busy() and all(dt.datetime.now() >= t for t in self.free_at.values())
        # Idle, never exit: tasks a human or a session commits later start without anyone restarting the
        # run. Logged once, and only with nothing running or merging, so no slot or finished branch is left
        # behind. A script waiting on the run watches run.log for `run idle`; the process itself ends only on Ctrl-C or `./run stop`.
        # one pick, and only when its answer is needed: to end `once`, to say idle, or to power off
        if quiet and not PAUSED[0] and (self.once or not shared_tools.pending(tried)) and (self.once and not stopping() or not self.idle_said
                                        or power_due(self.idle_at)) and not pick(self.running, tried, self.branch) \
                and not splitting(tried, self.branch):  # B196: it starts by itself in minutes
            if self.once and not stopping():
                close_page(True, log)  # F402b3a: the run ends, its page stays
                log('run done: nothing it may start (once)')
                return 0
            if not self.idle_said:
                log(f'tried this run: {", ".join(sorted(tried)) or "none"}')
                log(idle_line(), EV_IDLE)
                self.idle_said, self.idle_at = True, time.time()
                if not stopping() and auto_release(self.branch, idle=True):  # F63: once per idle spell
                    return None  # the release it queued starts on the next tick
            if shut_down(self.idle_at):
                return 0
        return None
