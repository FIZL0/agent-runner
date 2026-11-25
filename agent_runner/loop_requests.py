"""Requests the run answers each tick: halts (drop, change, take back), tells and restyles."""

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

from agent_runner import agent_hold, brief_arrives, claude_use, exit_hook, fallback as FB, settings_live, ci, file_split, gitops, no_commits, no_push, plan as P, plansync, plat, shared_tools, stack, undo
from agent_runner.config import claude_model, RUNNER, ensure_local, finished_mark, shown_cmd
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
        finished_mark(n, C).unlink(missing_ok=True)
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
    so its wip branches stay and no EV_DROPPED event is recorded. B801: `[run] on_exit` runs as at any session's
    end; a short wait lets it end first, and a slower one holds the slot: a changed task then starts later."""
    for tid, how in halt_requests().items():
        verb = {'drop': 'dropped', 'take': 'took'}.get(how, 'changed')
        n = next((m for m, t in running.items() if t[0] == tid), None)
        q = next((m for m, x in queued().items() if x[0] == tid), None)
        sid = ''
        if n is not None:
            pid, sid, _ = procs.pop(n)
            running.pop(n)
            exit_hook.end_session(pid)
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
        if n is not None:
            end_orphans()
            if n not in procs:  # B801: for a queued resume too: a run that died ended its session without it
                if n not in exit_hook.busy():  # else the one its own exit started
                    exit_hook.start(n)
                exit_hook.wait(n)
        did = discard_task(tid, n, sid) if n is not None else []
        if n is not None:
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
            if n is not None and task and n <= slots and n not in exit_hook.busy() and not agent_held() and (p := start(n, task, branch, model, idle, slots)):
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
    the slot's session through its shim's FIFO (F40). No live session (a hidden console, the
    session ended, a cut-off one waiting to resume): told false, and `plan change` falls back to the B19 halt.
    B770: while the slot's end mark says its agent ran `run ask`, the request waits: its session is ending and would
    never read the text. Once `reap` has parked the ask no slot runs the task, and the command says what it asks."""
    for tid, req in tell_requests().items():
        n = next((m for m, t in running.items() if t[0] == tid), None)
        if n is None:
            tell_answer(tid, False, no_slot(tid, req))
        elif not P.ending_ask(C, tid, f's{n}'):
            why = type_into(n, procs, P.tell_text(req['how'], req['text']))
            if why is not None:
                tell_answer(tid, False, why.replace(f's{n}:', f's{n} ({tid}):', 1))
            elif not P.ending_ask(C, tid, f's{n}'):  # else it asked as the text was typed: not read either
                tell_answer(tid, True, f'told s{n} ({tid})')


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
    if not (commits := git('log', '--format=%s', f'{stack.fork(tid, branch)}..task/{tid}').stdout.splitlines()):
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
