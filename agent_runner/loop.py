"""The run itself: the keys typed into its pane, halts and tells, CI, finishing a task, the sequential run
and the parallel loop (`cmd_run`)."""

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
import uuid
import webbrowser
from contextlib import ExitStack
from pathlib import Path

from agent_runner import ci, gitops, plan as P, plansync, plat
from agent_runner.config import RUNNER, ensure_local, finished_mark, shown_cmd
from agent_runner.done import TESTED
from agent_runner.gitops import missing_remote, push
from agent_runner.state import (alarm, ask_stop, C, clean, clear_stop, commit_plan, default_branch, FORCED, forced,
    git, HIDDEN, hook, IDLE, init, KEYS, KEYS_LOCK, LANDING, log, MERGE, note, PAUSED, plan_rel, plan_text, POWER, queued,
    READING, ROOT, RUN_TAG, share, SLOTS_DIR, stop_note, STOP_SAID, stopped_by, stopping, WAKE)
from agent_runner.brief import no_remote_line, prompt_for
from agent_runner.sched import blocked_by_edits, keep_claims, PARK_LIMIT, parked_attempts, pick, tasks
from agent_runner.slots import (adopt, agent_argv, agent_cmd, backend, DISK_AT, DISK_SAID, du, env_vars, free_branch,
    free_gb, GB, MUX, remote_any, remote_line, REMOTE_URL, resume, run_session, save_leftovers, send_to_pane,
    ShimMux, single_run, slot_env, slot_shim, SLOTS, start, tmux, TmuxMux, transcript, trim, unmerged)
from agent_runner.watch import (_account, agent_failed, api_down, AUTO_UPGRADE, auto_upgrade, cut_off,
    drop_session_tmp, end_orphans, installed_version, memory_watch, queue_cut_off, queue_resume, restart_if_upgraded,
    RESUME_AFTER, resume_failed, RESUME_MAX, resumes, RESUMES_MAX, stalled, START_TRIES, state_line, stats,
    stop_hook, stop_waiter, sweep_tmp, update_watch, upgrade, usage_pct, weekly)
from agent_runner.join import EDITED, EDITS_POLL, ELSEWHERE, REMIND_EVERY, TASK_SID, WAITING
from agent_runner.land import drop_wips, idle_line, prune_wips, reopen_landed, REOPENED, retry_reopened, wip_main
from agent_runner.merge import (AHEAD_BUSY, AHEADS, before_start_fails, FIX_DIRS, FIX_DIRS_LOCK, FIXED, gate_runs,
    HELD, last_words, left_merging, MASTER_PANE, merge)
from agent_runner.control import (close_controls, control_ok, end_closed_controls, hand_hook, rc_sweep_start,
    start_control, start_control_server)
from agent_runner.feed import rc_sweep_stop, start_board


def nap(s: float) -> None:
    if READING[0]:
        WAKE.wait(s)
        WAKE.clear()
    else:
        time.sleep(s)


def read_keys() -> None:
    """A daemon thread's loop: every line typed into the runner's pane is acted on at once (`take_keys`), and
    the loop is woken for what only it can do (ending sessions, a new slot).

    A thread rather than select() on stdin, which only works on POSIX. Started only when stdin is a tty, and
    never by the sequential run, whose agent session reads the same terminal.
    """
    for line in sys.stdin:
        KEYS.append(line.strip().lower())
        take_keys()
        WAKE.set()


def keys_help() -> str:
    """The `?` block, shaped like `agent-runner help`, ruled off so it stands out from the log."""
    rule = '-' * 78
    return f"""{rule}
runner keys: type one in this pane and press Enter

    s        stop gently: no new tasks, the running ones finish and merge, then the run exits
    s!       stop now: end the agent sessions (each resumes where it was in the next run),
             finish the merges under way, then exit
    p        pause: no new tasks, and the run stays up
    u        upgrade agent-runner now; the run restarts on the new version by itself
    f        force: start tasks past the session and weekly usage caps (as --force)
    +        one slot more
    -        one slot fewer (a running task in it finishes first)
    z        suspend the computer once the run stops, or when it goes idle
    x        shut the computer down once the run stops, or when it goes idle
    Enter    open the control sessions at claude.ai/code (with [run] remote)
    ?        this help

    s, p, f, z and x take themselves back when typed again.
    Ctrl-C ends the runner only: sessions keep running, and the next run adopts them.

now: {state_line()}
{rule}"""


def take_keys() -> None:
    """Act on the lines typed into the runner's pane (see `keys_help`), and on a power choice `./run stop
    --suspend|--shutdown` left. Logged at once; ending sessions and adding a slot happen on the loop's next
    pass, which a key wakes."""
    global POWER, SLOTS
    with KEYS_LOCK:
        if (f := C.notes('POWER')).exists():
            POWER = f.read_text(encoding='utf-8').strip()
            share(POWER=POWER)
            f.unlink(missing_ok=True)
        KEYS.extend(cli_keys())
        while KEYS:
            k, _, want = KEYS.pop(0).partition(' ')
            if not k:
                if remote_any():
                    open_remote()
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
                log('stop taken back: starting tasks again')
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
    f = C.notes('KEYS')
    taken = f.with_name(f'KEYS.{os.getpid()}')
    try:
        f.replace(taken)
    except OSError:
        return []
    try:
        return [k for l in taken.read_text(encoding='utf-8').splitlines() if (k := l.strip().lower())]
    finally:
        taken.unlink(missing_ok=True)


def open_remote() -> None:
    """Enter in the runner's pane, with `[run] remote`: the sessions page, in the default browser (a claude.ai
    link the desktop app is set to take opens there). No browser here (ssh): the link, to open elsewhere."""
    try:
        ok = webbrowser.open(REMOTE_URL)
    except Exception:  # noqa: BLE001 - a broken browser setup must not take the key reader down
        ok = False
    log(f'opening {REMOTE_URL}' if ok else f'no browser here: open {REMOTE_URL} on any device, or the Claude app')


def send_key(*keys: str) -> None:
    """What a typed key does, from any terminal or a remote session: the run takes it on its next pass."""
    with open(C.notes('KEYS'), 'a', encoding='utf-8') as f:
        f.write(''.join(f'{k}\n' for k in keys))


RUNNING_SINCE: dict[tuple[str, str], float] = {}  # (slot, task) -> when write_state first saw it running


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
                                   'running': work, 'since': since, 'merging': merging, 'usage': use,
                                   'idle': IDLE[0], 'paused': PAUSED[0], 'stopping': stopping()}),
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
    """{task: 'drop' | 'change'}: what `plan drop` / `plan change` asked of this run (see plan.halt)."""
    out = {}
    for f in P.halt_dir(C).glob('*.json'):
        try:
            how = json.loads(f.read_text(encoding='utf-8'))['how']
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if how in ('drop', 'change'):
            out[f.stem] = how
    return out


def halt_answer(tid: str, msg: str) -> None:
    """Tell the waiting `plan drop`/`change` what happened, log it, and take its request away."""
    d = P.halt_dir(C)
    tmp = d / f'{tid}.done.tmp'
    tmp.write_text(msg + '\n', encoding='utf-8')
    os.replace(tmp, d / f'{tid}.done')
    (d / f'{tid}.json').unlink(missing_ok=True)
    log(msg)
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
    text. A finished branch waiting to merge is deleted unmerged (by `_finish`, which checks first)."""
    for tid, how in halt_requests().items():
        verb = 'dropped' if how == 'drop' else 'changed'
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
        msg = f'{verb} {tid}; {stopped}' + (f', removed its work ({", ".join(did)})' if did else '')
        if how == 'drop':
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
        halt_answer(tid, msg)


def tell_requests() -> dict[str, dict]:
    """{task: request}: what `plan tell` / `plan change` asked this run to pass on (see plan.tell)."""
    out = {}
    for f in P.tell_dir(C).glob('*.json'):
        try:
            req = json.loads(f.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if isinstance(req, dict) and req.get('how') in ('tell', 'change') and isinstance(req.get('text'), str):
            out[f.stem] = req
    return out


def tell_answer(tid: str, told: bool, msg: str) -> None:
    d = P.tell_dir(C)
    tmp = d / f'{tid}.done.tmp'
    tmp.write_text(json.dumps({'told': told, 'msg': msg}), encoding='utf-8')
    os.replace(tmp, d / f'{tid}.done')
    (d / f'{tid}.json').unlink(missing_ok=True)
    log(msg)
    if told:
        note(msg)


def tells(procs: dict, running: dict) -> None:
    """F16: pass each `plan tell` / `plan change` message on to the slot running its task, by typing it into
    the slot's tmux pane. No live pane (not tmux, the session ended, a cut-off one waiting to resume): told
    false, and `plan change` falls back to the B19 halt."""
    reqs = tell_requests()
    if not reqs:
        return
    tagged = MUX.panes() if isinstance(MUX, TmuxMux) else {}
    for tid, req in reqs.items():
        n = next((m for m, t in running.items() if t[0] == tid), None)
        if n is None:
            tell_answer(tid, False, f'no slot runs {tid} now')
            continue
        hit = tagged.get(f's{n}')
        if not isinstance(MUX, TmuxMux):
            why = f'no live pane for s{n} ({tid}): its terminal ({MUX.name}) takes no typed text'
        elif not hit or not plat.alive(hit[1]) or (n in procs and not plat.alive(procs[n][0])):
            why = f'no live pane for s{n} ({tid}): its session has ended'
        elif not send_to_pane(hit[0], P.tell_text(req['how'], req['text'])):
            why = f'no live pane for s{n} ({tid}): tmux could not type into {hit[0]}'
        else:
            tell_answer(tid, True, f'told s{n} ({tid})')
            continue
        tell_answer(tid, False, why)


def power_now() -> None:
    """After a stop, with `z`, `x`, --suspend or --shutdown: suspend or power off now, no idle grace."""
    log(f'run stopped: {"suspending" if POWER == "suspend" else "shutting down"} the computer')
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
            tid = P.add(C.run['ci_kind'], text, todo=ROOT / rel, pri='critical')
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
        log(f'{tid}: LEFT FOR A HUMAN — the merge crashed: {e!r}')

def _finish(tid: str, n: int, sid: str, branch: str) -> bool:
    """False when task/<tid> waits for the next run to merge it."""
    if tid in halt_requests():  # B19: dropped or changed before its merge: never lands
        did = discard_task(tid, None)
        DISCARDED[tid] = 'its finished branch never merged' + (f' ({", ".join(did)})' if did else '')
        return True
    commits = git('log', '--format=%s', f'{branch}..task/{tid}').stdout.splitlines()
    if not commits:
        git('branch', '-D', f'task/{tid}')
        git('update-ref', '-d', TESTED + tid)
        note(f'{tid}: no commits — nothing to merge')
        log(f'{tid}: no commits — nothing to merge')
        return True
    if sid and sid != '(unknown)':
        TASK_SID[tid] = sid  # its repair, if the merge fails the gate, starts from this session
    while (why := merge(tid, branch)) and why.startswith((EDITED, ELSEWHERE)):
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
                log(f'{tid}: the run stops; task/{tid} waits for the next run to merge it')
                return False
            if time.time() - since > REMIND_EVERY:  # still nobody: say it again, as loud
                since = time.time()
                alarm(f'{tid} is still not merging', f'{why}. task/{tid} has waited since '
                      f'{dt.datetime.fromtimestamp(since - REMIND_EVERY):%H:%M} or earlier.')
            time.sleep(EDITS_POLL)
        log(f'{tid}: the main checkout is clear again; merging task/{tid} now')
    if not why:
        return True
    # Parked as wip/<ID>: a task/<ID> ahead of the branch reads as finished-and-waiting to `pick`, which
    # would then skip the task for good. As wip/ the task can start again, with the old attempt to read.
    if git('branch', '-M', f'task/{tid}', wip := free_branch(f'wip/{tid}')).returncode:
        note(f'{tid}: LEFT FOR A HUMAN — {why}; task/{tid} could not be parked, so nothing restarts it')
        log(f'{tid}: LEFT FOR A HUMAN — {why}. task/{tid} could not be renamed to {wip}, so no run restarts the '
            f'task until it is merged, renamed or deleted by hand. Its {len(commits)} commits: {" / ".join(commits)[:300]}')
        return True
    git('update-ref', '-d', TESTED + tid)
    for h in git('for-each-ref', '--format=%(refname)', f'{HELD}{tid}/', f'{FIXED}{tid}/').stdout.split():
        git('update-ref', '-d', h)
    note(f'{tid}: not merged, parked as {wip} — {why}')
    log(f'{tid}: not merged, parked as {wip} — {why}. Its {len(commits)} commits are kept there. The task stays '
        f'open and starts again by itself in the next run (in this one once its line is edited: '
        f'`{C.command} plan note {tid} "..."`), its next attempt pointed at {wip}')
    if out := push(ROOT, wip):  # the one copy of that work: get it off this disk
        log(f'{tid}: {out}')
    if len(parked_attempts().get(tid, [])) >= PARK_LIMIT:
        log(f'{tid}: parked {PARK_LIMIT} times now; the next pick blocks it on a person instead of starting it again')
    return True


# --- sequential run ------------------------------------------------------------

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


def sequential(branch: str, model: str, idle: int, pause: int, force: bool, once: bool = False) -> int:
    """`--no-tmux`, or no terminal for panes: one session at a time, in this checkout, on the branch it has out.

    No worktree: so a task commits straight onto the branch you are on and no merge
    happens. `done` ran the gate before it committed, so with `push_merge` the branch is pushed after each
    task. `once` stops after the first task, which is how to try the runner on a single task. With nothing to
    start it does not exit: it logs `run idle` once and looks at TODO.md again every 30 s.
    """
    here = git('branch', '--show-current').stdout.strip() or branch
    log(f'sequential run on {here} ({"one task, then stop" if once else "one session at a time"}, '
        f'committing in this checkout)')
    tried: set[str] = set()
    closed: set[str] = set()
    idle_said, idle_at = False, 0.0
    while not stopping():
        retry_reopened(tried, closed, here)
        if not (task := pick({}, tried, here, claim=True)):
            if once:
                break
            if not idle_said:
                log(idle_line())
                idle_said, idle_at = True, time.time()
            if shut_down(idle_at):
                return 0
            time.sleep(30)
            continue
        if idle_said:
            log(f'run busy: new work ({task[0]})')
            idle_said = False
        if low_disk([]):
            time.sleep(30)
            continue
        if (w := capped(force)) is not None:
            log(f'{w}: waiting for the reset (--force to go on)')
            time.sleep(300)
            continue
        tid = task[0]
        sid = str(uuid.uuid4())
        before = git('rev-parse', 'HEAD').stdout.strip()
        log(f'{tid}: starting ({task[1]})')
        env = env_vars(slot_env(1))
        if plat.WINDOWS:  # no sh to read the prompt file; the marker is how the Stop hook finds the agent
            code = run_session(agent_argv(prompt_for(tid, 1, 1, ROOT, here), sid, model, idle, 'slot1'),
                               str(ROOT), env, C.notes('slot1.live'))
        else:
            code = sp.run(agent_cmd(prompt_for(tid, 1, 1, ROOT, here), sid, model, idle, 'slot1'), shell=True,
                          cwd=str(ROOT), env={**os.environ, **env}).returncode
        log(f'{tid}: session ended ({stats(sid)})')
        end_orphans()
        drop_session_tmp(sid)
        if C.run['on_exit']:
            hook('on_exit', C.run['on_exit'], ROOT, {**os.environ, **env})
        if backend().report_exit and code:
            log(f'{tid}: {C.run["backend"]} failed (exit {code}): {last_words(sid) or "see terminal output"}')
            plansync.release(C, tid)
            return code
        tried.add(tid)
        plansync.release(C, tid)  # committed here, ticked by its `done`: nothing left to hold
        if git('rev-parse', 'HEAD').stdout.strip() != before:
            note(f'{tid}: committed on {here}')
            with MERGE:
                reopen_landed(here, tid)
            tried -= REOPENED
            REOPENED.clear()
            if C.push_merge and (out := push(ROOT, here, shared=True)):
                log(f'{tid}: {out}')
        if once:
            log(f'{tid}: done (once)')
            return 0
        time.sleep(pause)
    asked = stopping()
    clear_stop()
    take_keys()  # no keys here, but `./run stop --suspend|--shutdown` leaves its choice the same way
    log('sequential run done: ' + ('nothing it may start (once)' if once else 'stop asked for'))
    if asked and POWER:
        power_now()
    return 0


def dry_run(slots: int, branch: str) -> int:
    """What `slots` free slots would start right now, in order, and why the rest of the open tasks wait."""
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


def session_env_masks(sess: str = '') -> list[list[str]]:
    """The tmux commands that keep SESSION_ENV out of every process a session starts later. `-r`, not `-u`: a
    tmux server first started from a Claude Code Bash tool holds the markers in its global environment, which
    shows through a session where they are merely unset; `-r` removes them from each new window's env."""
    return [['set-environment', *(['-t', f'={sess}'] if sess else []), '-r', k] for k in SESSION_ENV]


def drop_session_env() -> None:
    """Out of this process, and out of the tmux session it runs in: `new-session -e` stores a variable on the
    session, and every window opened in it later (each slot's) inherits it."""
    for k in SESSION_ENV:
        os.environ.pop(k, None)
    if os.environ.get('TMUX') and shutil.which('tmux'):
        for c in session_env_masks():
            tmux(*c)


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
        # minute) so it is not left half-done. Sessions in their panes keep going and the next run adopts
        # them and merges what finished.
        try:
            log('run interrupted: sessions in their panes keep running; the next run adopts them')
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
    ap.add_argument('--upgrade', action='store_true', help='upgrade agent-runner first, then run the new version')
    ap.add_argument('--idle', type=int, default=None, help='seconds of quiet before a session is ended')
    ap.add_argument('--stall', type=int, default=None, help='seconds of quiet that count as stalled')
    ap.add_argument('--pause', type=int, default=None, help='seconds between a session ending and the next')
    ap.add_argument('--model', default=None, help='the agent model (default [run] model)')
    ap.add_argument('--no-tmux', action='store_true', help='force the single sequential session')
    ap.add_argument('--mux', choices=['tmux', 'wt', 'console', 'none'], default=None,
                    help='the terminal per slot (default [run] mux, else tmux; on Windows wt, else console)')
    ap.add_argument('--dry-run', action='store_true', help='print what would start, and start nothing')
    ap.add_argument('--stop-hook', action='store_true', help=argparse.SUPPRESS)
    ap.add_argument('--stop-waiter', nargs=4, metavar=('PID', 'TRANSCRIPT', 'N', 'IDLE'), help=argparse.SUPPRESS)
    ap.add_argument('--slot-shim', metavar='JOB', help=argparse.SUPPRESS)
    ap.add_argument('--hidden', action='store_true', help=argparse.SUPPRESS)  # the background run (Windows: hidden consoles)
    a = ap.parse_args(argv)

    if a.stop_hook:  # these two run inside an agent session and need no repository
        return stop_hook(a.idle or 30)
    if a.stop_waiter:
        pid, t, n, idle = a.stop_waiter
        return stop_waiter(int(pid), t, int(n), int(idle))
    if a.slot_shim:
        return slot_shim(a.slot_shim)

    init()
    if a.upgrade and upgrade() and installed_version() != __import__('agent_runner').__version__ \
            and not plat.WINDOWS:  # Windows has no real exec: the next start runs it
        os.execv(sys.executable, [x for x in sys.orig_argv if x != '--upgrade'])
    r = C.run
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

    branch = default_branch()
    if git('rev-parse', '--verify', '--quiet', branch).returncode:
        print(f'no branch {branch!r} to merge into — commit something first', file=sys.stderr)
        return 2
    if a.dry_run:
        return dry_run(slots, branch)

    lock = single_run()  # noqa: F841 — held until the process ends
    ensure_local(ROOT)  # this machine's runner.local.toml: made once (all comments), never rewritten, git-ignored
    if stopping() and not keep.get('stop'):  # left by a run killed before it saw it; a stop is for the run that is up
        clear_stop()
        log('cleared a stop request left by an earlier run')
    C.notes('POWER').unlink(missing_ok=True)
    want = 'none' if a.no_tmux else (a.mux or r['mux'])
    if a.hidden and plat.WINDOWS:  # the background run: a console per slot that starts hidden, never a wt tab
        HIDDEN[0], want = True, 'console'
    choice = plat.mux_choice(want, shutil.which('tmux') is not None, shutil.which('wt.exe') is not None)
    if choice == 'sequential':
        if want != 'none':
            log((f'{want} is not available here' if want else 'tmux is not installed') +
                ': falling back to one sequential session (install tmux, or Windows Terminal on Windows, '
                'for parallel slots, a terminal per session, and worktrees)')
        return sequential(branch, model, idle, pause, a.force, once)
    global MUX
    MUX = TmuxMux() if choice == 'tmux' else ShimMux(choice)
    global MASTER_PANE
    MASTER_PANE = choice == 'tmux'
    share(MUX=MUX, MASTER_PANE=MASTER_PANE)
    if choice == 'console' and HIDDEN[0]:
        log('in the background: each slot gets a console window that starts hidden (agent-runner attach sN shows it)')
    elif choice == 'console':
        log('Windows Terminal (wt.exe) is not installed: each slot gets a console window of its own')
    if choice == 'tmux' and not os.environ.get('TMUX'):
        print(f'Run me inside tmux, so the sessions get panes you can attach to:\n'
              f'    tmux new -s runner {prog} {a.slots or slots}\n'
              f'or start the run in the background: {shown_cmd()}', file=sys.stderr)
        return 2
    if choice == 'tmux' and os.environ.get('TMUX_PANE'):  # `attach` finds the runner's pane by this
        tmux('set-option', '-p', '-t', os.environ['TMUX_PANE'], RUN_TAG, str(ROOT))
    rc_sweep_start()  # B12: end the feed or control server an earlier run left on Remote Control
    start_control()  # c1 beside the run ([run] control) unless [run] remote, where the control server stands in
    start_control_server()
    start_board()  # the background run's board window: what lands and needs you, no tokens; reopened if closed

    AUTO_UPGRADE[0] = bool(r['auto_upgrade'])
    threading.Thread(target=update_watch, daemon=True).start()
    for w in C.warnings:
        log(w)
    from agent_runner.guide import install, point_rules
    if r['install_skill'] and (said := install()):
        log(said)
    if said := point_rules(C, git):
        log(said)
    if control_ok() and (said := hand_hook(ROOT)):
        log(said)
    if Path('/proc/meminfo').exists() and (r['proc_max_gb'] or r['min_free_mem_gb']):
        threading.Thread(target=memory_watch, daemon=True).start()
    if sys.stdin.isatty():
        READING[0] = True
        threading.Thread(target=read_keys, daemon=True).start()
        print(keys_help(), flush=True)
    running: dict[int, tuple] = {}
    procs: dict[int, tuple] = {}
    tried: set[str] = set()
    closed: set[str] = set()  # see retry_reopened
    idle_said, idle_at = False, 0.0
    free_at = {n: dt.datetime.min for n in range(1, slots + 1)}
    merging: list[threading.Thread] = []
    stall_said: set[str] = set()
    failed_resumes: dict[str, int] = {}  # session id -> times it was resumed after a failed model call
    failed_starts: dict[str, int] = {}  # task -> sessions that did not start
    cap_said = False
    STOP_SAID[0] = False
    held_said = slots  # the slot count `max_unmerged` last held the run to, as logged
    reserve_branch_ids()
    log(f'run: {slots} slots in {MUX.name}, merging into {branch}' +
        (f', session usage {usage_pct("five_hour")}%, weekly usage {weekly()}%' if not a.force and r['agent'] == 'claude' else ''))
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

    foreign = queue_cut_off(branch, [n for n in range(1, slots + 1) if n not in procs])
    sweep_tmp(force=True)
    drop_extra_slots(slots, set(procs) | set(queued()) | set(foreign))
    left = left_merging()
    finished = unmerged(branch, [n for n in free_at if n not in procs and n not in queued() and n not in foreign])
    # the riders of a merge an earlier run gated wait from the start, so its turn finds them and reuses it
    WAITING.update(set(finished) & {t for g in gate_runs() for t in g.get('tids', [])})
    for tid in sorted(finished, key=lambda t: t not in left):  # the merge an earlier run left going first: it adopts that
        log(f'{tid}: ' + ('its merge was under way when the last run ended; adopting it' if tid in left else
                          'finished, not merged yet; merging it now'))
        tried.add(tid)
        t = threading.Thread(target=finish, args=(tid, 0, '(unknown)', branch), name=f'merge:{tid}')
        t.start()
        merging.append(t)
    if not merging:  # blocks freed by merges made while no run was up (a merge started above reopens by itself)
        with MERGE:
            reopen_landed(branch, 'a merge before this run')
    prune_wips(branch, force=True)  # F23: wip/<ID> of tasks ticked or dropped while no run was up

    while True:
        sweep_tmp()
        prune_wips(branch)  # F23: now and then, for tasks ticked or dropped by hand while the run is up
        take_keys()
        IDLE[0] = idle_said
        write_state(running)
        if SLOTS != slots:  # `+` or `-`: a slot past the count is watched to its end, never refilled
            slots = SLOTS
            for m in range(1, slots + 1):
                free_at.setdefault(m, dt.datetime.min)
        if forced() and procs:
            end_sessions(procs, running)
        tells(procs, running)  # F16: plan tell / change, typed into a running slot's pane
        halts(procs, running, free_at, tried, branch, model, idle, slots)  # B19: plan drop / change of a running task
        waiting = {n: q for n, q in queued().items() if n in free_at and n <= slots}
        if said := stop_note(stopping(), len(procs) + len(waiting) + len(foreign) +
                             sum(t.is_alive() for t in merging), stopped_by()):
            log(said)
        tagged = None  # MUX.panes(), looked at once a tick and only for a free slot
        for n in list(free_at):
            if n in procs and plat.alive(procs[n][0]) and (f := agent_failed(procs[n][1])) and \
                    (k := failed_resumes.get(procs[n][1], 0)) < RESUME_MAX and f[1] >= RESUME_AFTER * 2 ** k:
                pid, sid, since = procs[n]
                failed_resumes[sid] = k + 1
                log(f'slot {n}: {running[n][0]} stopped on a failed model call ({f[0][:120]}); resuming its '
                    f'session ({k + 1}/{RESUME_MAX})')
                if new := resume_failed(n, pid, sid, running[n][0], model, idle):
                    procs[n] = (new, sid, since)
                    stall_said.add(sid)  # its transcript is still old until the resumed session writes
            if n in procs and not plat.alive(procs[n][0]):
                (pid, sid, since), task = procs.pop(n), running.pop(n)
                log(f'slot {n}: {task[0]} exited ({stats(sid)})')
                end_orphans()
                if backend().report_exit and (said := last_words(sid)):
                    log(f'slot {n}: {task[0]} {r["backend"]}: {said[:500]}')
                if r['on_exit']:
                    sp.Popen(r['on_exit'], shell=True, cwd=str(SLOTS_DIR / f's{n}'),
                             env={**os.environ, **env_vars(slot_env(n))},
                             stdout=sp.DEVNULL, stderr=sp.DEVNULL)
                if (why := cut_off(sid)) and n <= slots:
                    if resumes(n, sid) < RESUMES_MAX:
                        # its worktree stays as the session left it, on task/<ID>: the resume goes on there
                        queue_resume(task[0], n, sid, why)
                        log(f'slot {n}: {task[0]} was cut off ({why}); it resumes in this slot once the API answers')
                        continue
                    log(f'slot {n}: {task[0]} was cut off again ({why}) after {RESUMES_MAX} resumes; '
                        f'taken as ended')
                drop_session_tmp(sid)  # ended for good: a resume (above) keeps its scratchpad
                if save_leftovers(d := SLOTS_DIR / f's{n}', task[0], branch):
                    clean(d)  # saved: the next start finds the slot clean
                if not not_attempt(task[0], branch):
                    tried.add(task[0])  # one attempt per run: ticked, blocked or failed, a human looks next
                git('checkout', '-q', '--detach', cwd=SLOTS_DIR / f's{n}')
                t = threading.Thread(target=finish, args=(task[0], n, sid, branch), name=f'merge:{task[0]}')
                t.start()
                merging.append(t)
                free_at[n] = dt.datetime.now() + dt.timedelta(seconds=pause)
            if n in procs and procs[n][1] not in stall_said and \
                    (why := stalled(procs[n][0], procs[n][1], stall)):
                stall_said.add(procs[n][1])
                if (m := finished_mark(n)) and m.exists():
                    # its `done` succeeded, so the Stop hook's waiter should have ended it; that waiter can
                    # be lost (two tasks once sat finished for hours), so the run ends it: next tick reaps it
                    log(f'slot {n}: {running[n][0]} finished but {why}; ending it')
                    plat.terminate(procs[n][0])
                else:
                    log(f'slot {n}: {running[n][0]} looks stalled ({why}); look at {MUX.where(n)}')
                    print('\a', end='', flush=True)
            if n not in procs and n in foreign:
                if plat.alive(foreign[n]):
                    continue  # see queue_cut_off: never a second agent in its worktree
                log(f'slot {n}: the session no run knew (pid {foreign.pop(n)}) ended')
                foreign.update(queue_cut_off(branch, [n]))
                continue
            if n not in procs and tagged is None:
                tagged = MUX.panes()  # a session that ended this tick is in it with a dead pid, as before
            if n not in procs and (old := tagged.get(f's{n}')) and plat.alive(old[1]):
                # a session no run tracks still sits in this slot (adopt found no session id, or a second
                # tmux session): never reset the worktree under it; the slot waits until that pane ends
                if f'pid{old[1]}' not in stall_said:
                    stall_said.add(f'pid{old[1]}')
                    log(f'slot {n}: an untracked session (pid {old[1]}, pane {old[0]}) still runs there; slot held')
                continue
            if n > slots:  # an adopted slot past this run's count: watched to the end, never refilled
                if n not in procs and n not in waiting and n not in foreign:
                    free_at.pop(n)
                    drop_extra_slots(slots, set(procs) | set(queued()) | set(foreign))
                continue
            if n not in procs and n in waiting and not forced():  # a running task, not a new one: no stop or usage cap holds it
                if api_down(stall_said):
                    continue
                tid, sid, why = waiting.pop(n)
                C.notes(f'{tid}.resume').unlink(missing_ok=True)
                if p := resume(n, tid, sid, why, branch, model, idle):
                    procs[n] = p
                    running[n] = next((t for t in tasks(branch) if t[0] == tid), (tid, '', set(), set()))
                    tried.add(tid)
                    idle_said = False
                continue
            if n not in procs and dt.datetime.now() >= free_at[n]:
                if stopping():  # said once, with how many are left, by stop_note at the top of the tick
                    continue
                if PAUSED[0]:
                    continue
                if (w := capped(a.force or FORCED[0])) is not None:
                    if not cap_said:
                        alarm(f'{w}: no new tasks', 'the running tasks finish and merge; new ones wait for the '
                              'reset. To go on now: type f + Enter in this pane, or restart with --force.')
                        cap_said = True
                    continue
                cap_said = False
                allowed = backlog_slots(slots, sum(t.is_alive() for t in merging))
                if allowed != held_said:
                    log(backlog_line(slots, allowed, sum(t.is_alive() for t in merging)))
                    held_said = allowed
                if allowed < slots and sum(m <= slots for m in procs) >= allowed:
                    continue
                if api_down(stall_said):
                    continue
                if low_disk([m for m in range(1, slots + 1) if m not in procs and m not in waiting
                             and m not in foreign]):
                    continue
                if r['before_start'] and before_start_fails():
                    if 'before_start' not in stall_said:
                        stall_said.add('before_start')
                        log(f'`{r["before_start"]}` fails: no new session starts until it passes')
                        print('\a', end='', flush=True)
                    continue
                stall_said.discard('before_start')
                if task := pick(running, tried, branch, claim=True):
                    if p := start(n, task, branch, model, idle, slots):
                        procs[n], running[n] = p, task
                        if once:  # one task: nothing new starts, and the run exits once it has merged
                            ask_stop('once')
                        if idle_said:
                            log(f'run busy: new work ({task[0]})')
                            idle_said = False
                    else:
                        failed_starts[task[0]] = failed_starts.get(task[0], 0) + 1
                        plansync.release(C, task[0])  # this start failed; another attempt can claim it
                        if failed_starts[task[0]] >= START_TRIES:
                            tried.add(task[0])
                        else:  # a terminal that was slow to open, or an agent that failed once: again later
                            log(f'slot {n}: {task[0]} will be tried again in {pause} s')
                            free_at[n] = dt.datetime.now() + dt.timedelta(seconds=pause)
        retry_reopened(tried, closed, branch)
        if REOPENED:
            tried -= REOPENED  # a task reopened by a merge is a new attempt, not the one that blocked
            REOPENED.clear()
        merging = [t for t in merging if t.is_alive()]
        if not stopping():
            auto_upgrade(bool(merging))
        if not merging and not stopping():
            restart_if_upgraded()
        watch_ci(branch)
        if not stopping():
            close_controls(branch)  # B26
            end_closed_controls()  # B53
        if not stopping():
            sweep_unmerged(branch, merging)
        keep_claims(running, branch)
        take_keys()
        waiting = {n: q for n, q in queued().items() if n in free_at and n <= slots}  # an exit may have queued one
        # a slot asleep until a usage reset does not hold the stop; a session waiting to resume does
        if stopping() and not procs and (not waiting or forced()) and not merging:
            how = stopped_by()
            clear_stop()
            log(f'run stopped ({how}); tried this run: {", ".join(sorted(tried)) or "none"}')
            rc_sweep_stop()  # B12: its feed and control server archive their entries before it exits
            if POWER:
                power_now()
            return 0
        quiet = not procs and not waiting and not merging and all(dt.datetime.now() >= t for t in free_at.values())
        # Idle, never exit: tasks a human or a session commits later start without anyone restarting the
        # run. Logged once, and only with nothing running or merging, so no slot or finished branch is left
        # behind. A script waiting on the run
        # watches run.log for `run idle`; the process itself ends only on Ctrl-C or `./run stop`.
        # one pick, and only when its answer is needed: to end `once`, to say idle, or to power off
        if quiet and not PAUSED[0] and (once and not stopping() or not idle_said
                                        or power_due(idle_at)) and not pick(running, tried, branch):
            if once and not stopping():
                log('run done: nothing it may start (once)')
                return 0
            if not idle_said:
                log(f'tried this run: {", ".join(sorted(tried)) or "none"}')
                log(idle_line())
                idle_said, idle_at = True, time.time()
            if shut_down(idle_at):
                return 0
        nap(10)


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
