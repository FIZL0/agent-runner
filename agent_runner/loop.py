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
import subprocess as sp
import sys
import threading
import time
import traceback
import webbrowser
from contextlib import ExitStack
from pathlib import Path

from agent_runner import ci, gitops, plan as P, plansync, plat
from agent_runner.config import claude_model, RUNNER, ensure_local, finished_mark, shown_cmd
from agent_runner.done import TESTED
from agent_runner.gitops import missing_remote, push
from agent_runner.state import (alarm, ask_stop, C, clean, clear_stop, commit_plan, default_branch, FORCED, forced,
    git, HIDDEN, IDLE, init, KEYS, KEYS_LOCK, LANDING, log, MERGE, note, PAUSED, plan_rel, plan_text, POWER, queued,
    READING, ROOT, share, SLOTS_DIR, stop_note, STOP_SAID, stopped_by, stopping, WAKE)
from agent_runner.state import (EV_DEFERRED, EV_DROPPED, EV_IDLE, EV_LEFT, EV_NO_COMMITS, EV_PARKED, EV_RUN_UP,
    EV_STALLED, EV_STOP_ASKED, EV_STOP_BACK, EV_STOPPED)
from agent_runner.state import EV_CONTEXT
from agent_runner.autorelease import auto_release, auto_release_of, AUTO_RELEASE_SEEN, landed_since_release
from agent_runner.watch import context_over
from agent_runner.brief import no_remote_line
from agent_runner.sched import blocked_by_edits, keep_claims, PARK_LIMIT, parked_attempts, pick, tasks
from agent_runner.sched import forgive_park, note_committed
from agent_runner.tools import take_end
from agent_runner.login import retry_held, unlogged
from agent_runner.asks import block_asks, EV_FINISHED, park_asked, unblocked_asks
from agent_runner.slots import (adopt, backend, DISK_AT, DISK_SAID, du, env_vars, free_branch,
    free_gb, GB, hidden_line, HiddenMux, MUX, remote_any, remote_line, REMOTE_URL, resume, save_leftovers,
    single_run, slot_env, slot_shim, SLOTS, start, transcript, trim, unmerged)
from agent_runner.slots import budget_mark, budgets, SPENT
from agent_runner import fallback as FB
from agent_runner.teardown import end_own, PAGE, RUN_LOCK, wait_last_run
from agent_runner.watch import (_account, api_down, AUTO_UPGRADE, auto_upgrade, cut_off,
    drop_session_tmp, end_orphans, memory_watch, queue_cut_off, queue_resume, restart_if_upgraded,
    resumes, RESUMES_MAX, stalled, START_TRIES, state_line, stats,
    stop_hook, stop_waiter, sweep_tmp, update_watch, upgrade, usage_pct, weekly)
from agent_runner.join import EDITED, EDITS_POLL, ELSEWHERE, REMIND_EVERY, TASK_SID, WAITING
from agent_runner.land import drop_wips, idle_line, prune_wips, reopen_landed, REOPENED, retry_reopened, wip_main
from agent_runner.land import no_gate_line
from agent_runner.merge import (AHEAD_BUSY, AHEADS, before_start_fails, FIX_DIRS, FIX_DIRS_LOCK, FIXED, gate_runs,
    HELD, last_words, left_merging, merge)
from agent_runner.control import (close_controls, end_closed_controls, hand_hook, rc_sweep_start,
    start_control, start_control_server)
from agent_runner.feed import rc_sweep_stop, start_board


def nap(s: float) -> None:
    if READING[0]:
        WAKE.wait(s)
        WAKE.clear()
    else:
        time.sleep(s)


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
    s!       stop now: end the agent sessions (each resumes where it was in the next run),
             finish the merges under way, then exit
    p        pause: no new tasks, and the run stays up
    u        upgrade agent-runner now; the run restarts on the new version by itself
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
                log('stopping now: ending the agent sessions (each resumes in the next run); the merges under way '
                    'finish, then the run ends')
            elif k == 'p':
                PAUSED[0] = not PAUSED[0]
                log('paused: no new tasks; the run stays up (p again: go on)' if PAUSED[0] else
                    'pause taken back: starting tasks again')
            elif k == 'f':
                FORCED[0] = not FORCED[0]
                log('forced: starting tasks past the usage caps (f again: undo)' if FORCED[0] else
                    'force taken back: the usage caps hold new tasks again')
            elif k == 'u':
                threading.Thread(target=upgrade, daemon=True).start()  # the loop restarts on what it installs
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


def write_state(running: dict) -> None:
    """`<notes>/STATE`, for `agent-runner status`: what the keys have set, what each slot is on and since when,
    what is merging, and the account's usage (as the cap reads it, at most every 5 minutes)."""
    work = {str(n): t[0] for n, t in running.items()}
    now = time.time()
    for k in [k for k in RUNNING_SINCE if work.get(k[0]) != k[1]]:
        RUNNING_SINCE.pop(k)
    since = {n: RUNNING_SINCE.setdefault((n, tid), now) for n, tid in work.items()}
    merging = sorted({t.name[6:] for t in threading.enumerate() if t.name.startswith('merge:') and t.is_alive()})
    # what the cap last read (`capped`, the start line); never a fetch of its own from here
    got = _account[1] if isinstance(_account[1], dict) else {}
    use = {k: got[k].get('utilization') for k in ('five_hour', 'seven_day') if isinstance(got.get(k), dict)}
    tmp = C.notes('STATE.tmp')
    try:
        tmp.write_text(json.dumps({'at': dt.datetime.now().isoformat(timespec='seconds'), 'state': state_line(),
                                   'slots': SLOTS, 'running': work, 'since': since, 'merging': merging, 'usage': use,
                                   'spend': {n: SPENT[n] for n in work if n in SPENT},  # F103
                                   'idle': IDLE[0], 'paused': PAUSED[0], 'stopping': stopping(),
                                   'version': run_version()}),
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
    worktree stays as the session left it; nothing it did is merged."""
    for n, (pid, sid, _) in list(procs.items()):
        tid = running[n][0]
        plat.terminate(pid)
        if not transcript(sid):  # it never started (held at a dialog): `--resume` would find no session and sit
            log(f'slot {n}: {tid} ended (s!) before its session began; it starts afresh in the next run')
            continue
        queue_resume(tid, n, sid, 'stopped with s!')
        log(f'slot {n}: {tid} ended (s!); it resumes in this slot in the next run')
    procs.clear()
    running.clear()


DISCARDED: dict[str, str] = {}  # B19: task -> what `_finish` did with a branch a drop or change got to first


def halt_requests() -> dict[str, str]:
    """{task: 'drop' | 'change' | 'take'}: what `plan drop` / `plan change` / a take back (B110) asked of this
    run (see plan.halt, cmds.take_back)."""
    return {tid: r['how'] for tid, r in P.requests(C, 'halt').items()
            if r.get('how') in ('drop', 'change', 'take')}


def halt_answer(tid: str, msg: str, kind: str | None = None) -> None:
    """Tell the waiting `plan drop`/`change` what happened, log it (as event `kind`), and take its request away."""
    P.respond(C, 'halt', tid, msg + '\n')
    log(msg, kind, tid)
    note(msg)


def discard_task(tid: str, n: int | None, sid: str = '') -> list[str]:
    """Throw away everything of task `tid`'s attempt: its worktree (slot n) reset clean and detached, task/<tid>
    deleted here and on the remote, its tested ref and its session's scratch gone. Nothing is saved: it was
    dropped or changed, so nobody wants this work. Returns what it did, for the message."""
    did = []
    if n is not None and (d := SLOTS_DIR / f's{n}').is_dir():
        if git('symbolic-ref', '-q', '--short', 'HEAD', cwd=d).stdout.strip() == f'task/{tid}':
            clean(d)
            git('checkout', '-q', '--detach', cwd=d)
            did.append(f'reset s{n}')
        finished_mark(n).unlink(missing_ok=True)
    if not git('rev-parse', '--verify', '-q', f'refs/heads/task/{tid}').returncode:
        git('branch', '-D', f'task/{tid}')
        did.append(f'deleted task/{tid}')
    git('update-ref', '-d', TESTED + tid)
    if out := gitops.drop_remote(ROOT, f'task/{tid}'):
        did.append(out)
    (plansync.ticks(C) / tid).unlink(missing_ok=True)  # a `done` it got to: never ticked by a merge now
    if sid:
        drop_session_tmp(sid)
    return did


def halts(procs: dict, running: dict, free_at: dict, tried: set, branch: str, model: str, idle: int,
          slots: int) -> None:
    """B19: act on `plan drop` / `plan change` of a task this run is on. Its session is ended, its work thrown
    away (`discard_task`) and its slot freed at once; a change starts it again in that slot from the new
    text. A finished branch waiting to merge is deleted unmerged (by `_finish`, which checks first). B110: a
    take back ('take') stops, discards and frees the same way but is no drop: the task stays in the plan, taken,
    so its wip branches stay and no EV_DROPPED event is recorded."""
    for tid, how in halt_requests().items():
        verb = {'drop': 'dropped', 'take': 'took'}.get(how, 'changed')
        n = next((m for m, t in running.items() if t[0] == tid), None)
        q = next((m for m, x in queued().items() if x[0] == tid), None)
        sid = ''
        if n is not None:
            pid, sid, _ = procs.pop(n)
            running.pop(n)
            plat.terminate(pid)
            end = time.monotonic() + 10
            while plat.alive(pid) and time.monotonic() < end:
                time.sleep(0.2)
            if plat.alive(pid):  # it ignored SIGTERM: its tree gets one, then whatever is left is ended below
                for p in [*plat.descendants(pid), pid]:
                    plat.terminate(p)
            stopped = f'stopped s{n}'
        elif q is not None:
            n, sid = q, queued()[q][1]
            C.notes(f'{tid}.resume').unlink(missing_ok=True)
            stopped = f'took back its resume in s{n}'
        elif any(t.name == f'merge:{tid}' and t.is_alive() for t in threading.enumerate()) and tid not in DISCARDED:
            continue  # its merge thread reads the request before it merges (`_finish`)
        elif tid in DISCARDED:
            stopped = DISCARDED.pop(tid)
        else:
            stopped = 'no slot was on it any more'
        did = discard_task(tid, n, sid) if n is not None else []
        if n is not None:
            end_orphans()
            free_at[n] = dt.datetime.now()
        msg = (f'{verb} {tid}' + (' back to a take' if how == 'take' else '') + f'; {stopped}'
               + (f', removed its work ({", ".join(did)})' if did else ''))
        if how == 'take':
            plansync.release(C, tid)  # the take worktree holds it now: the run passes over it as taken
        elif how == 'drop':
            plansync.release(C, tid)
            if wd := drop_wips(tid):  # F23: dropped, so its parked attempts are read by nobody
                msg += f'; {", ".join(wd)}'
        else:
            tried.discard(tid)  # the new text is a new attempt
            task = next((t for t in tasks(branch) if t[0] == tid), None)
            if n is not None and task and n <= slots and (p := start(n, task, branch, model, idle, slots)):
                procs[n], running[n] = p, task
                tried.add(tid)
                msg += f'; restarted it in s{n} with the new text'
            else:
                plansync.release(C, tid)
                msg += '; it starts again with the new text when a slot is free'
        halt_answer(tid, msg, EV_DROPPED if how == 'drop' else None)


def tell_requests() -> dict[str, dict]:
    """{task: request}: what `plan tell` / `plan change` asked this run to pass on (see plan.tell)."""
    return {tid: r for tid, r in P.requests(C, 'tell').items()
            if r.get('how') in ('tell', 'change') and isinstance(r.get('text'), str)}


def tell_answer(tid: str, told: bool, msg: str) -> None:
    P.respond(C, 'tell', tid, json.dumps({'told': told, 'msg': msg}))
    log(msg)
    if told:
        note(msg)


def tells(procs: dict, running: dict) -> None:
    """F16: pass each `plan tell` / `plan change` message on to the slot running its task, by typing it into
    the slot's session through its shim's FIFO (F40). No live session (a Windows hidden console, the
    session ended, a cut-off one waiting to resume): told false, and `plan change` falls back to the B19 halt."""
    reqs = tell_requests()
    if not reqs:
        return
    tagged = MUX.panes() if MUX.typed else {}
    for tid, req in reqs.items():
        n = next((m for m, t in running.items() if t[0] == tid), None)
        if n is None:
            tell_answer(tid, False, f'no slot runs {tid} now')
            continue
        hit = tagged.get(f's{n}')
        if not MUX.typed:
            why = f'no live pane for s{n} ({tid}): its terminal ({MUX.name}) takes no typed text'
        elif not hit or not plat.alive(hit[1]) or (n in procs and not plat.alive(procs[n][0])):
            why = f'no live pane for s{n} ({tid}): its session has ended'
        elif not MUX.send(hit, P.tell_text(req['how'], req['text'])):
            why = f'no live pane for s{n} ({tid}): {MUX.name} could not type into {hit[0]}'
        else:
            tell_answer(tid, True, f'told s{n} ({tid})')
            continue
        tell_answer(tid, False, why)


def restyle_requests() -> dict[str, dict]:
    """{task: request}: the running interface tasks `plan restyle` asked this run to park (see plan.restyle)."""
    return {tid: r for tid, r in P.requests(C, 'restyle').items() if isinstance(r.get('rid'), str)}


def restyle_mark(tid: str) -> dict:
    """F19: {'rid', 'how': 'park' | 'land'} when restyle `rid` asked about `tid`, for `_finish`; else {}."""
    try:
        got = json.loads(C.notes(f'{tid}.restyle').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return got if isinstance(got, dict) and isinstance(got.get('rid'), str) else {}


def type_into(n: int, procs: dict, text: str) -> str | None:
    """Type `text` into slot n's live session, as `tells` does; None when it went in, else why not."""
    tagged = MUX.panes() if MUX.typed else {}
    hit = tagged.get(f's{n}')
    if not MUX.typed:
        return f'no live pane for s{n}: its terminal ({MUX.name}) takes no typed text'
    if not hit or not plat.alive(hit[1]) or (n in procs and not plat.alive(procs[n][0])):
        return f'no live pane for s{n}: its session has ended'
    if not MUX.send(hit, text):
        return f'no live pane for s{n}: {MUX.name} could not type into {hit[0]}'
    return None


def park_for_restyle(tid: str, rid: str, branch: str) -> str:
    """F19: park task/<tid> as wip/<tid> (the parked-attempt path: its next attempt is pointed there), held for
    restyle `rid` in the plan already; not counted as a failed merge. Returns what it did."""
    C.notes(f'{tid}.restyle').unlink(missing_ok=True)
    if git('rev-parse', '--verify', '-q', f'refs/heads/task/{tid}').returncode:
        return f'nothing committed to park; it stays held for restyle {rid}'
    commits = git('log', '--format=%s', f'{branch}..task/{tid}').stdout.splitlines()
    if not commits:
        git('branch', '-D', f'task/{tid}')
        git('update-ref', '-d', TESTED + tid)
        return f'nothing committed to park (anything left uncommitted the slot saved); it stays held for restyle {rid}'
    if git('branch', '-M', f'task/{tid}', wip := free_branch(f'wip/{tid}')).returncode:
        return f'task/{tid} could not be parked as {wip}; it stays held for restyle {rid}'
    git('update-ref', '-d', TESTED + tid)
    forgive_park(tid, wip)
    log(f'{tid}: parked as {wip} for restyle {rid} — its {len(commits)} commits are kept there; it starts again '
        f'from them, with the style noted, once the restyle is approved', EV_PARKED, tid,
        why=f'held for restyle {rid}', wip=wip)
    if out := push(ROOT, wip):  # the one copy of that work: get it off this disk
        log(f'{tid}: {out}')
    return f'parked as {wip}, held for restyle {rid}'


def restyle_landed(tid: str, rid: str) -> None:
    """F19: `tid` landed in the old style while restyle `rid` waits: noted on the restyle's waiting build, so the
    control session lists it on the restyle page."""
    b = P.restyle_build(rid, todo=ROOT / plan_rel('TODO.md'))
    if not note_committed(b, P.LANDED_OLD + tid, f'Plan: {tid} landed in the old style; list it on restyle {rid}'):
        log(f'{tid}: landed in the old style, but could not note it on restyle {rid} ({b}): list it on its page by hand')


def restyles(procs: dict, running: dict, branch: str) -> None:
    """F19: park each running task `plan restyle` held. One whose `done` already passed (or that is merging)
    lands and is noted on the restyle; any other is told to stop at a clean point, commit and write its journal,
    and `_finish` parks its branch as wip/<ID> when the session ends (a session that takes no typed text is
    ended now). A session cut off and waiting to resume is not resumed: its work is parked at once."""
    for tid, req in restyle_requests().items():
        rid, style = req['rid'], str(req.get('style') or '')
        mark = lambda how: C.notes(f'{tid}.restyle').write_text(json.dumps({'rid': rid, 'how': how}),
                                                                encoding='utf-8')
        n = next((m for m, t in running.items() if t[0] == tid), None)
        q = next((m for m, x in queued().items() if x[0] == tid), None)
        if n is not None and (fm := finished_mark(n)) and fm.exists():
            mark('land')
            msg = f'{tid}: its done in s{n} already passed; it lands in the old style, listed on restyle {rid}'
        elif n is not None:
            mark('park')
            if (why := type_into(n, procs, P.park_text(tid, rid, style, C.command))) is None:
                msg = (f'told s{n} ({tid}) to stop at a clean point, commit and write its journal; its branch is '
                       f'parked as wip/{tid} when the session ends, held for restyle {rid}')
            else:
                plat.terminate(procs[n][0])
                msg = f'{tid}: {why}; ended its session, and what it did is parked as wip/{tid}, held for restyle {rid}'
        elif q is not None:
            C.notes(f'{tid}.resume').unlink(missing_ok=True)
            d = SLOTS_DIR / f's{q}'
            if d.is_dir():
                if save_leftovers(d, tid, branch):
                    clean(d)
                git('checkout', '-q', '--detach', cwd=d)
            msg = f'{tid}: took back its resume in s{q}; ' + park_for_restyle(tid, rid, branch)
        elif any(t.name == f'merge:{tid}' and t.is_alive() for t in threading.enumerate()):
            mark('land')
            msg = f'{tid} is merging: it lands in the old style, listed on restyle {rid}'
        else:
            msg = f'no slot runs {tid} now; it stays held for restyle {rid}'
        P.respond(C, 'restyle', tid, msg + '\n')
        log(msg, None, tid)
        note(msg)


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




def ci_flows(branch: str) -> tuple[list[str], str]:
    """`[run] ci_watch` as (workflow files, event their runs must come from): "auto" (the default) is every
    workflow that runs on a push to `branch`, push runs only; a name or list is just those, any event;
    false, [] or "" is none."""
    w = C.run['ci_watch']
    if w == 'auto':
        return ci.push_workflows(ROOT, branch), 'push'
    if not w:
        return [], ''
    return ([w] if isinstance(w, str) else list(w)), ''


CI_UNSEEN: list[str] = []  # why gh could not see the repository, once it has been said
CI_RERUN = True  # a red run's failed jobs run once more before a task is filed: GitHub's own outages read red too
CI_AT = [0.0]  # when `watch_ci` last asked GitHub


def watch_ci(branch: str, force: bool = False) -> list[str]:
    """`[run] ci_watch`: file one critical task for a red workflow run on the shared branch (see `ci`).

    Every `ci.CI_POLL` s from the run loop, and only when MERGE is free: the task is committed in the main
    checkout like `reopen_landed`'s, and a loop that waited out a gate here would start nothing for an hour.
    Left alone, as there, while TODO.md has edits nobody committed. The ids filed.
    """
    if not force and time.time() - CI_AT[0] < ci.CI_POLL:
        return []
    flows, event = ci_flows(branch)
    if not flows:
        return []
    if not MERGE.acquire(blocking=False):
        return []
    filed: list[str] = []
    hold = ExitStack()
    try:
        CI_AT[0] = time.time()
        if C.plan_external:  # the whole look: a gh call or two, seconds
            hold.enter_context(plansync.locked(C))
            plansync.pull(C, force=True)
        rel = plan_rel('TODO.md')
        if git('branch', '--show-current').stdout.strip() != branch or \
                git('status', '--porcelain', '--', plan_rel('')).stdout.strip():
            return []
        gh = ci.gh_in(ROOT)
        if why := ci.reachable(gh):
            if not CI_UNSEEN:
                CI_UNSEEN.append(why)
                log(f'! ci_watch: gh cannot see this repository ({why}); CI on {branch} is not watched until it '
                    f'can (`gh auth status`; `ci_watch = false` in [run] to stop looking)')
            return []
        CI_UNSEEN.clear()
        for wf in flows:
            ls = P.lines(ROOT / rel)
            open_text = '\n'.join(l for l in ls if (m := P.ITEM.match(l)) and m.group(2) != 'x')
            seen = ci.seen_file(C.notes, wf)
            was = seen.read_text() if seen.exists() else ''
            if not (got := ci.to_file(gh, wf, branch, seen, open_text, event, CI_RERUN, log)):
                continue
            text, long = got
            tid = P.add(ci.CI_KIND, text, todo=ROOT / rel, pri='critical')
            if len(earlier := ci.closed_repeats(P.lines(ROOT / plan_rel('DONE.md')), ci.marker(wf, branch))) \
                    >= ci.REPEAT_LIMIT - 1:  # B34: the third in a week waits on a person, not ahead of all work
                P.block(tid, ci.repeat_ask(f'`{wf}` on {branch}', earlier), todo=ROOT / rel, after=[])
            own = plan_rel(f'{P.TASKS}/{tid}.md')
            (ROOT / own).parent.mkdir(parents=True, exist_ok=True)
            (ROOT / own).write_text('\n'.join([f'# {tid} — CI: {ci.marker(wf, branch)}', '', *long, '']),
                                    encoding='utf-8')
            git('add', '--', own)
            if not commit_plan(f'Plan: {tid}, {ci.marker(wf, branch)}', rel, own):
                git('reset', '-q', '--', own)
                git('checkout', '-q', '--', rel)
                (ROOT / own).unlink(missing_ok=True)
                seen.write_text(was)  # not filed: the next look tries that run again
                continue
            filed.append(tid)
            how = f'blocked on a person, after {", ".join(earlier)}' if len(earlier) >= ci.REPEAT_LIMIT - 1 else 'critical'
            note(f'{tid}: filed ({how}), {ci.marker(wf, branch)}')
            log(f'{tid}: filed ({how}), {ci.marker(wf, branch)}: {text[:200]}')
    finally:
        hold.close()
        MERGE.release()
    return filed


ISSUES_UNSEEN: list[str] = []  # why gh could not see the repository's issues, once it has been said
ISSUES_AT = [0.0]  # when `watch_issues` last asked GitHub


def watch_issues(branch: str, force: bool = False) -> list[str]:
    """`[run] issues_watch`: file one task per new open GitHub issue, and answer the issues whose task closed
    (see `issues`). On the `ci_watch` cadence and only when MERGE is free, committed in the main checkout as
    `watch_ci` commits its tasks. The ids filed."""
    from agent_runner import issues as I
    labels = I.labels_of(C.run.get('issues_watch', False))
    if labels is None or (not force and time.time() - ISSUES_AT[0] < ci.CI_POLL):
        return []
    if not MERGE.acquire(blocking=False):
        return []
    filed: list[str] = []
    hold = ExitStack()
    try:
        ISSUES_AT[0] = time.time()
        if C.plan_external:
            hold.enter_context(plansync.locked(C))
            plansync.pull(C, force=True)
        rel = plan_rel('TODO.md')
        if git('branch', '--show-current').stdout.strip() != branch or \
                git('status', '--porcelain', '--', plan_rel('')).stdout.strip():
            return []
        gh = ci.gh_in(ROOT)
        if why := ci.reachable(gh):
            if not ISSUES_UNSEEN:
                ISSUES_UNSEEN.append(why)
                log(f'! issues_watch: gh cannot see this repository ({why}); its issues are not read until it '
                    f'can (`gh auth status`; `issues_watch = false` in [run] to stop looking)')
            return []
        ISSUES_UNSEEN.clear()
        seen_f, filed_f = C.notes('issues.seen'), C.notes('issues.filed')
        book = I.read_filed(filed_f)
        # the issues whose task has closed: a comment naming the merge commit; closed too under trust
        plan_lines = [*P.lines(ROOT / rel), *P.lines(ROOT / plan_rel('DONE.md'))]

        def commit_of(tid: str) -> str:
            # the merge's own commit (merge.py's message); a task's commits alone could be any id's prefix
            return git('log', '-1', '--format=%h', '-F', f"--grep=Merge branch 'task/{tid}'", branch).stdout.strip()
        for tid, n, trust, sha, line in I.to_answer(book, plan_lines, commit_of):
            if I.answer(gh, n, tid, trust, sha, line):
                book.pop(tid, None)
                I.write_filed(filed_f, book)
                log(f'{tid}: {"closed" if trust == "trust" else "commented on"} {I.marker(n)}'
                    + (f' (landed in {sha})' if sha else ' (no code change)'))
        got = I.open_issues(gh, labels)
        if got is None:
            return []
        seen = I.read_seen(seen_f)
        trust = I.trust_of(C.run.get('issues_trust', 'skeptical'))
        me = I.owner(gh) if trust == 'skeptical' and any(i['number'] not in seen for i in got) else ''
        for issue in got:
            n = issue['number']
            if n in seen:
                continue
            ls = P.lines(ROOT / rel)
            open_text = '\n'.join(l for l in ls if (m := P.ITEM.match(l)) and m.group(2) != 'x')
            if I.named(issue, open_text):
                seen.add(n)
                I.write_seen(seen_f, seen)
                continue
            how = 'trust' if me and (issue.get('author') or {}).get('login') == me else trust
            text, long = I.task(issue, how)
            tid = P.add(I.kind_of(issue), text, todo=ROOT / rel, pri='normal')
            own = plan_rel(f'{P.TASKS}/{tid}.md')
            (ROOT / own).parent.mkdir(parents=True, exist_ok=True)
            (ROOT / own).write_text('\n'.join([f'# {tid} — {I.marker(n)}', '', *long, '']), encoding='utf-8')
            git('add', '--', own)
            if not commit_plan(f'Plan: {tid}, {I.marker(n)}', rel, own):
                git('reset', '-q', '--', own)
                git('checkout', '-q', '--', rel)
                (ROOT / own).unlink(missing_ok=True)
                continue  # not filed: the next look tries it again
            seen.add(n)
            I.write_seen(seen_f, seen)
            book[tid] = {'number': n, 'trust': how}
            I.write_filed(filed_f, book)
            filed.append(tid)
            note(f'{tid}: filed ({how}), {I.marker(n)}')
            log(f'{tid}: filed ({how}), {I.marker(n)}: {text[:200]}')
    finally:
        hold.close()
        MERGE.release()
    return filed


def not_attempt(tid: str, branch: str) -> bool:
    """The session's last commit matches `[run] not_attempt` ({id} = the task): a phase that leaves the task open
    on purpose (a spec written for a later session to port from), so the task may start again once it merges."""
    rx = C.run['not_attempt']
    last = git('log', '-1', '--format=%s', f'{branch}..task/{tid}').stdout.strip()
    return bool(rx and last and re.search(rx.replace('{id}', re.escape(tid)), last))


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
    if tid in halt_requests():  # B19: dropped or changed before its merge: never lands
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
    commits = git('log', '--format=%s', f'{branch}..task/{tid}').stdout.splitlines()
    if not commits:
        git('branch', '-D', f'task/{tid}')
        git('update-ref', '-d', TESTED + tid)
        note(f'{tid}: no commits — nothing to merge')
        log(f'{tid}: no commits — nothing to merge', EV_NO_COMMITS, tid)
        return True
    if sid and sid != '(unknown)':
        TASK_SID[tid] = sid  # its repair, if the merge fails the gate, starts from this session
    over = ''
    if bm := budget_mark(tid):  # F103: stopped over its budget: parked below, unless its done passed
        C.notes(f'{tid}.budget').unlink(missing_ok=True)
        if git('rev-parse', '--verify', '-q', TESTED + tid).returncode and not (plansync.ticks(C) / tid).exists():
            over = f'stopped over its budget: {bm}'
    while (why := over or merge(tid, branch)) and why.startswith((EDITED, ELSEWHERE)):
        # Tested and only waiting on somebody's edits: parking it would throw the work away for a fresh
        # attempt. The branch stays task/<ID> (`pick` leaves it alone, the next run's `unmerged` takes it).
        alarm(f'{tid} is not merging: ' + ('uncommitted edits in the main checkout' if why.startswith(EDITED)
                                           else f'{branch} is not checked out'),
              f'{why}. task/{tid} stays, tested, and merges again once ' +
              ('they are committed (or moved to a branch).' if why.startswith(EDITED) else
               f'{branch} is checked out in {ROOT} again.'))
        since = time.time()
        while blocked_by_edits(tid, branch):
            if stopping():
                log(f'{tid}: the run stops; task/{tid} waits for the next run to merge it', EV_DEFERRED, tid)
                return False
            if time.time() - since > REMIND_EVERY:  # still nobody: say it again, as loud
                since = time.time()
                alarm(f'{tid} is still not merging', f'{why}. task/{tid} has waited since '
                      f'{dt.datetime.fromtimestamp(since - REMIND_EVERY):%H:%M} or earlier.')
            time.sleep(EDITS_POLL)
        log(f'{tid}: the main checkout is clear again; merging task/{tid} now')
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

def capped(force: bool) -> str | None:
    """Why no new task may start: the 5-hour session usage at or past `[run] session_max`, or the 7-day usage
    at or past `[run] weekly_max` (and not --force). None when neither is."""
    if force or C.run['agent'] != 'claude':
        return None
    for name, what, key in (('five_hour', 'session', 'session_max'), ('seven_day', 'weekly', 'weekly_max')):
        w = usage_pct(name)
        if w is not None and w >= C.run[key]:
            return f'{what} usage {w}% >= {C.run[key]}%'
    return None


def cap_stop_detail() -> str:
    """B102: the usage-cap alarm's detail, the remote-friendly way to go on first (the runner feed, a control
    session, `[run] command` force), the run view's f + Enter last."""
    return ('the running tasks finish and merge; new ones wait for the reset. To go on now: say force in the '
            f'runner feed or a control session, or run `{C.command} force`, or type f + Enter in the run view '
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
        return run(argv, prog)
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
    ap.add_argument('--model', default=None, help='the agent model (default [run] model)')
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
    r = C.run
    if a.model and ':' in a.model:  # F125: another provider is refused here, not run as a claude model name
        a.model = claude_model(a.model, C.providers, C.models_local, 'run --model')
    once = a.slots == 'once'
    global POWER
    POWER = '' if once else 'shutdown' if a.shutdown else 'suspend' if a.suspend else ''
    try:
        slots = 1 if once else int(a.slots or r['slots'])
    except ValueError:
        ap.error(f"slots must be a number or 'once', not {a.slots!r}")
    global SLOTS
    SLOTS = slots
    if keep := kept_keys():  # restarted on an upgrade: the slot count, pause, power and stop typed before it hold
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

    RUN_LOCK.append(wait_last_run())  # B144: held until run() returns; a start after a stop waits for it
    ensure_local(ROOT)  # this machine's runner.local.toml: made once (all comments), never rewritten, git-ignored
    drop_earlier_stop(keep)
    C.notes('POWER').unlink(missing_ok=True)
    global MUX
    MUX = HiddenMux()  # C26: every OS runs its slots hidden
    HIDDEN[0] = True  # Windows: c1's console starts hidden too
    share(MUX=MUX)
    log(hidden_line())
    rc_sweep_start()  # B12: end the feed or control server an earlier run left on Remote Control
    start_control()  # c1 beside the run ([run] control) unless [run] remote, where the control server stands in
    start_control_server()
    start_board()  # the runner feed's window ([run] remote); reopened if closed
    from agent_runner.web import start_web
    if srv := start_web():  # F66: the run page on this machine ([run] web), its address in the run log
        PAGE.append(srv)  # B144: the stop closes it before it says `run stopped`

    AUTO_UPGRADE[0] = bool(r['auto_upgrade'])
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
    if Path('/proc/meminfo').exists() and (r['proc_max_gb'] or r['min_free_mem_gb']):
        threading.Thread(target=memory_watch, daemon=True).start()
    if sys.stdin.isatty():
        READING[0] = True
        threading.Thread(target=read_keys, daemon=True).start()
        print(keys_help(), flush=True)
    try:
        return Run(a, slots, once, branch, model, idle, stall, pause).go()
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
        while True:
            if (code := self.tick()) is not None:
                return code
            nap(10)

    def merge_in(self, tid: str, n: int, sid: str) -> None:
        """Merge a finished task in a thread of its own."""
        t = threading.Thread(target=finish, args=(tid, n, sid, self.branch), name=f'merge:{tid}')
        t.start()
        self.merging.append(t)

    def open(self) -> None:
        """Log what the run is, adopt the sessions and finished branches an earlier run left."""
        a, r, slots, branch = self.a, self.r, self.slots, self.branch
        procs, running, free_at = self.procs, self.running, self.free_at
        reserve_branch_ids()
        log(f'run: {slots} slots in {MUX.name}, merging into {branch}' +
            (f', session usage {usage_pct("five_hour")}%, weekly usage {weekly()}%' if not a.force and r['agent'] == 'claude' else ''),
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

        foreign = self.foreign = queue_cut_off(branch, [n for n in range(1, slots + 1) if n not in procs])
        sweep_tmp(force=True)
        drop_extra_slots(slots, set(procs) | set(queued()) | set(foreign))
        left = left_merging()
        finished = unmerged(branch, [n for n in free_at if n not in procs and n not in queued() and n not in foreign])
        # the riders of a merge an earlier run gated wait from the start, so its turn finds them and reuses it
        WAITING.update(set(finished) & {t for g in gate_runs() for t in g.get('tids', [])})
        for tid in sorted(finished, key=lambda t: t not in left):  # the merge an earlier run left going first: it adopts that
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
        self.top()
        self.tagged = None
        for n in list(self.free_at):
            self.slot(n)
        self.after()
        return self.end()

    def top(self) -> None:
        """The start of a tick: keys typed, the slot count, forced stops, tells and halts, the stop note."""
        procs, running = self.procs, self.running
        sweep_tmp()
        prune_wips(self.branch)  # F23: now and then, for tasks ticked or dropped by hand while the run is up
        take_keys()
        IDLE[0] = self.idle_said
        write_state(running)
        if SLOTS != self.slots:  # `+` or `-`: a slot past the count is watched to its end, never refilled
            self.slots = SLOTS
            for m in range(1, self.slots + 1):
                self.free_at.setdefault(m, dt.datetime.min)
        if forced() and procs:
            end_sessions(procs, running)
        tells(procs, running)  # F16: plan tell / change, typed into a running slot's session
        restyles(procs, running, self.branch)  # F19: plan restyle parks a running interface task
        budgets(procs, running, type_into)  # F103: [run] task_tokens / task_usd stop a task at a clean point
        FB.caps(procs, running, type_into)  # F106g: a Claude Code task at a usage cap goes on down the chain
        halts(procs, running, self.free_at, self.tried, self.branch, self.model, self.idle,
              self.slots)  # B19: plan drop / change of a running task
        self.waiting = {n: q for n, q in queued().items() if n in self.free_at and n <= self.slots}
        left = len(procs) + len(self.waiting) + len(self.foreign) + sum(t.is_alive() for t in self.merging)
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
        if n not in self.procs and n in self.waiting and not forced():  # a running task, not a new one: no stop or usage cap holds it
            self.resume_queued(n)
            return
        if n not in self.procs and dt.datetime.now() >= self.free_at[n]:
            self.fill(n)

    def reap(self, n: int) -> bool:
        """The slot's session ended: queue its resume if it was cut off (True: nothing more this tick), else
        save what it left and merge its task."""
        procs, r, branch = self.procs, self.r, self.branch
        if n in procs and not plat.alive(procs[n][0]):
            (pid, sid, since), task = procs.pop(n), self.running.pop(n)
            if over := context_over(sid, r.get('context_warn')):  # F25: soft only, the exit line says it
                log(f'slot {n}: {task[0]} exited ({stats(sid)}); {task[0]} {over[0]}', kind=EV_CONTEXT,
                    tid=task[0], **over[1])
            else:
                log(f'slot {n}: {task[0]} exited ({stats(sid)})')
            end_orphans()
            if backend().report_exit and (said := last_words(sid)):
                log(f'slot {n}: {task[0]} {r["backend"]}: {said[:500]}')
            if r['on_exit']:
                sp.Popen(r['on_exit'], shell=True, cwd=str(SLOTS_DIR / f's{n}'),
                         env={**os.environ, **env_vars(slot_env(n))},
                         stdout=sp.DEVNULL, stderr=sp.DEVNULL)
            end = take_end(n, C)  # F102: the agent's `run finish` or `run ask`
            if end.get('how') == 'finish':
                log(f'slot {n}: {task[0]} finished: {end.get("text", "")[:300]}', EV_FINISHED, task[0],
                    summary=end.get('text', ''))
            if end.get('how') == 'ask' and end.get('tid') == task[0] and \
                    park_asked(n, task[0], sid, end.get('text', ''), branch):
                self.tried.add(task[0])
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
                drop_extra_slots(self.slots, set(procs) | set(queued()) | set(foreign))
            return True
        return False

    def resume_queued(self, n: int) -> None:
        """Resume the session queued for this slot (cut off, or ended on a usage limit) once the API answers."""
        if api_down(self.stall_said):
            return
        tid, sid, why = self.waiting.pop(n)
        fb = FB.queued_model(tid)  # F106g: a new session on the chain's next model, not this one resumed
        C.notes(f'{tid}.resume').unlink(missing_ok=True)
        if p := resume(n, tid, sid, why, self.branch, self.model, self.idle, fallback=fb, slots=self.slots):
            self.procs[n] = p
            self.running[n] = next((t for t in tasks(self.branch) if t[0] == tid), (tid, '', set(), set()))
            self.tried.add(tid)
            self.idle_said = False

    def say_cap(self, w: str) -> None:
        """The usage-cap alarm, once each time a cap is reached."""
        if not self.cap_said:
            alarm(f'{w}: no new tasks', cap_stop_detail())
            self.cap_said = True

    def fill(self, n: int) -> None:
        """Start the next task in the free slot, unless a stop, pause, usage cap, backlog, API outage, low disk
        or failing before_start holds it."""
        procs, running, slots, r = self.procs, self.running, self.slots, self.r
        if stopping():  # said once, with how many are left, by stop_note at the top of the tick
            return
        if PAUSED[0]:
            return
        w, held = capped(self.a.force or FORCED[0]), frozenset()
        if w is None:
            self.cap_said = self.cap_fell = False
        elif C.fallback:
            held = FB.USAGE_HELD  # F142: new tasks start down the chain instead
        else:
            self.say_cap(w)
            return
        allowed = backlog_slots(slots, sum(t.is_alive() for t in self.merging))
        if allowed != self.held_said:
            log(backlog_line(slots, allowed, sum(t.is_alive() for t in self.merging)))
            self.held_said = allowed
        if allowed < slots and sum(m <= slots for m in procs) >= allowed:
            return
        if api_down(self.stall_said):
            return
        if low_disk([m for m in range(1, slots + 1) if m not in procs and m not in self.waiting
                     and m not in self.foreign]):
            return
        if r['before_start'] and before_start_fails():
            if 'before_start' not in self.stall_said:
                self.stall_said.add('before_start')
                log(f'`{r["before_start"]}` fails: no new session starts until it passes')
                print('\a', end='', flush=True)
            return
        self.stall_said.discard('before_start')
        self.tried.difference_update(retry_held())  # F106e: held back for a login, not blocked yet: again
        passed = FB.no_free(self.branch, self.model, held) if held else set()
        task = pick(running, self.tried | passed, self.branch, claim=True)
        if not task and passed and not self.cap_said and \
                (t := pick(running, self.tried, self.branch)) and t[0] in passed:
            self.say_cap(w)  # F142: only the cap holds it: no provider in the chain is free for it
        if task:
            if unlogged(task[0], self.branch, self.model):  # F106e: its provider has no login: Needs you
                plansync.release(C, task[0])
                self.tried.add(task[0])  # the next pick takes another; an unblock or retry_held puts it back
                return
            if held and not self.cap_fell:
                log(f'{w}: new tasks start on the first free provider in [models] fallback until the reset')
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
        branch = self.branch
        retry_reopened(self.tried, self.closed, branch)
        if REOPENED:
            self.tried -= REOPENED  # a task reopened by a merge is a new attempt, not the one that blocked
            REOPENED.clear()
        self.merging = [t for t in self.merging if t.is_alive()]
        if not stopping():
            auto_upgrade(bool(self.merging))
        if not self.merging and not stopping():
            restart_if_upgraded()
        watch_ci(branch)
        watch_issues(branch)
        if not stopping():
            auto_release(branch)  # F63: { every = N }
        if not stopping():
            close_controls(branch)  # B26
            end_closed_controls()  # B53
            from agent_runner.page_copy import page_copy_tick
            page_copy_tick()  # F68: the claude.ai copy of the run page (B122: a one-shot, never c1)
        if not stopping():
            sweep_unmerged(branch, self.merging)
        keep_claims(self.running, branch)
        block_asks(branch)  # F102: an ask whose block could not be committed when it was parked
        take_keys()
        # an exit may have queued one
        self.waiting = {n: q for n, q in queued().items() if n in self.free_at and n <= self.slots}

    def end(self) -> int | None:
        """Stop the run once a stop has drained it; end `once`, say idle, or power off when nothing may start."""
        procs, waiting, merging, tried = self.procs, self.waiting, self.merging, self.tried
        # a slot asleep until a usage reset does not hold the stop; a session waiting to resume does
        if stopping() and not procs and (not waiting or forced()) and not merging:
            how = stopped_by()
            end_own(rc_sweep_stop, log)  # B144: its feed, control server, board and page are gone before it says it stopped
            clear_stop()
            log(f'run stopped ({how}); tried this run: {", ".join(sorted(tried)) or "none"}', EV_STOPPED)
            if POWER:
                power_now()
            return 0
        quiet = not procs and not waiting and not merging and all(dt.datetime.now() >= t for t in self.free_at.values())
        # Idle, never exit: tasks a human or a session commits later start without anyone restarting the
        # run. Logged once, and only with nothing running or merging, so no slot or finished branch is left
        # behind. A script waiting on the run
        # watches run.log for `run idle`; the process itself ends only on Ctrl-C or `./run stop`.
        # one pick, and only when its answer is needed: to end `once`, to say idle, or to power off
        if quiet and not PAUSED[0] and (self.once and not stopping() or not self.idle_said
                                        or power_due(self.idle_at)) and not pick(self.running, tried, self.branch):
            if self.once and not stopping():
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


SWEPT: set[str] = set()  # tasks sweep_unmerged started a merge of: once each per run
SWEEP_AT = [0.0]


def sweep_unmerged(branch: str, merging: list) -> None:
    """Every 30 s: merge a task/<ID> that finished outside this run's slots (`take --merge`), as a run
    start merges what finished while no run was up. Once per task per run: a merge that crashes is said once."""
    if time.time() - SWEEP_AT[0] < 30:
        return
    SWEEP_AT[0] = time.time()
    live = {t.name for t in merging if t.is_alive()}
    for tid in unmerged(branch, []):
        if tid in SWEPT or f'merge:{tid}' in live:
            continue
        SWEPT.add(tid)
        log(f'{tid}: finished outside the slots; merging it now')
        t = threading.Thread(target=finish, args=(tid, 0, '(unknown)', branch), name=f'merge:{tid}')
        t.start()
        merging.append(t)
