"""F168: shared tools, things only one task can use at a time (a test phone, a device).

`[run.tools.<name>]` in runner.toml names each with a `check` command, whose exit status says whether it is free (0),
busy (75, its first output line names the holder) or missing (69, the line says why); any other status, or a check
past CHECK_TIMEOUT, is unknown. A task says what it needs with `needs: <name>` on its line (`plan add --needs`).

A thread per tool checks it while the run is up, off the scheduling thread (`start`); `sched.holds` keeps a tagged
task waiting while its tool is not to be had (`hold`), and `sched.choose` has it checked once more right before the
task starts (`ready`). A slot's agent that finds its tool busy runs `run wait-for TOOL` (`cmd_wait_for`): its session
ends, its work is kept on waiting/<ID> (`park`), and the same session goes on, ahead of other tasks, once the tool is
free (`slots.start`). The pages read `rows` and `wait_words`; a tool missing while tasks wait for it is one Needs you
item (`asks`).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import signal
import subprocess as sp
import sys
import tempfile
import threading
import time
from pathlib import Path

from agent_runner import plan as P, plat
from agent_runner import state as S
from agent_runner.state import git, log

FREE, BUSY, MISSING, UNKNOWN = 'free', 'busy', 'missing', 'unknown'
EXITS = {0: FREE, 75: BUSY, 69: MISSING}  # sysexits' TEMPFAIL and UNAVAILABLE: a check that crashes is neither
CHECK_TIMEOUT = 10.0  # s a check may take; past it the tool is unknown
EVERY = 120.0         # s between two checks of a tool no task waits for
EVERY_WAITED = 15.0   # s while one does
SOON = 5.0            # s to the next check after a reading not confirmed yet
CONFIRM = 2           # readings in a row before a change to or from missing or unknown counts: a blip changes nothing
UNKNOWN_HOLD = 300.0  # s a check that fails holds the tasks that need the tool; then they start all the same
MISSING_ASK = 180.0   # s a tool is missing, with tasks waiting for it, before it is a Needs you item
FRESH_WAIT = CHECK_TIMEOUT + 1  # s a start waits for its own check, run off the scheduling thread: a check is quick
FRESH_FOR = 15.0      # s an answer a start asked for may be old
FILE_AGE = 600.0      # s past which TOOLS.json is an ended run's
LABEL = 'TOOL'        # the Needs you label
EV_TOOL = 'tool missing'   # a missing tool is put under Needs you (text: the ask)
EV_WAITS = 'tool waited'   # task `id` gave up its slot to wait for a tool


def specs(c=None) -> dict[str, dict]:
    """{name: {check, label, connect}} of the project's shared tools; {} without the setting."""
    c = c or S.C
    out = {}
    for name, t in ((c.run.get('tools') if c else None) or {}).items():
        label = t.get('label') or name
        out[name] = {'check': t['check'], 'label': label, 'connect': t.get('connect') or f'Connect {label}'}
    return out


def unknown_names(names, c=None) -> str:
    """Why `names` (a line's `needs:`) are refused, or ''."""
    known = specs(c)
    if not (bad := [n for n in names if n not in known]):
        return ''
    return (f'no shared tool named {", ".join(bad)}; ' +
            (f'the project has: {", ".join(known)}' if known else 'this project names none ([run.tools] in runner.toml)'))


def needs_of(line: str, c=None) -> list[str]:
    """The shared tools a task line says it needs, those the project (still) names."""
    known = specs(c)
    return [n for n in P.fields(line).get('needs', []) if n in known]


# --- the check ------------------------------------------------------------------------------------------------

def check(name: str, c=None) -> tuple[str, str]:
    """Run tool `name`'s check now, in the main checkout: (its state, who holds it or why it is not to be had)."""
    from agent_runner.config import main_checkout
    c = c or S.C
    # files, not pipes: a daemon the check leaves behind (adb's server) would hold a pipe open past the timeout
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        try:
            p = sp.Popen(specs(c)[name]['check'], shell=True, cwd=str(main_checkout(c.root)), stdin=sp.DEVNULL,
                         stdout=out, stderr=err, start_new_session=not plat.WINDOWS,
                         env={k: v for k, v in os.environ.items()
                              if k not in ('AGENT_RUNNER_SLOT', 'AGENT_RUNNER_WORKTREE')})
        except OSError as e:
            return UNKNOWN, f'its check does not start ({e})'[:120]
        try:
            rc = p.wait(timeout=CHECK_TIMEOUT)
        except sp.TimeoutExpired:
            if plat.WINDOWS:
                plat.terminate(p.pid)
            else:
                try:
                    os.killpg(p.pid, signal.SIGKILL)
                except OSError:
                    pass
            try:
                p.wait(timeout=5)
            except sp.TimeoutExpired:
                pass
            return UNKNOWN, f'its check ran past {CHECK_TIMEOUT:g} s'

        def first(f) -> str:
            f.seek(0)
            ls = f.read(4000).decode('utf-8', 'replace').splitlines()
            return next((l.strip()[:80] for l in ls if l.strip()), '')
        state = EXITS.get(rc, UNKNOWN)
        said = first(out)
        if state == UNKNOWN:
            said = f'its check failed (exit {rc}{": " + why if (why := first(err) or said) else ""})'
        return state, '' if state == FREE else said


# --- what the run knows of each tool -----------------------------------------------------------------------------
# A reading: {state, who, since} as the run counts it (confirmed), {raw, n, raw_since} the last readings, `at` when
# the last check started, `asked` its missing spell is under Needs you already.

READINGS: dict[str, dict] = {}
LOCK = threading.RLock()
THREADS: dict[str, threading.Thread] = {}
WAKES: dict[str, threading.Event] = {}
STOP = threading.Event()
ASKED: dict[str, float] = {}  # tool -> when a start last asked for a check of its own
IGNORED: set[str] = set()     # tools whose failing check no longer holds tasks, said once


def absorb(name: str, got: tuple[str, str], at: float) -> None:
    """Take one check's answer in. Free and busy change at once; a change to or from missing or unknown counts
    once CONFIRM readings in a row say so."""
    state, who = got
    with LOCK:
        r = READINGS.get(name)
        if r is None:
            r = READINGS[name] = {'state': state, 'who': who, 'since': at, 'raw': state, 'n': 1, 'raw_since': at,
                                  'raw_who': who, 'at': at, 'asked': False}
            changed = state in (MISSING, UNKNOWN)
        else:
            if r['raw'] == state:
                r['n'] += 1
            else:
                r.update(raw=state, n=1, raw_since=at)
            r.update(at=at, raw_who=who)
            changed = False
            if state == r['state']:
                if state == BUSY and who != r['who']:
                    r['since'] = at
                r['who'] = who
            elif not {state, r['state']} & {MISSING, UNKNOWN} or r['n'] >= CONFIRM:
                changed = bool({state, r['state']} & {MISSING, UNKNOWN})
                r.update(state=state, who=who, since=r['raw_since'], asked=False)
                IGNORED.discard(name)
        said = dict(r)
    if changed:
        label = specs()[name]['label']
        log(f'{label}: ' + {FREE: 'back, and free', BUSY: f'back, held by {said["who"] or "someone"}',
                            MISSING: said['who'] or 'not connected',
                            UNKNOWN: f'unknown: {said["who"]}; tasks that need it wait for it up to '
                                     f'{UNKNOWN_HOLD / 60:g} min'}[said['state']])
    write()


def write() -> None:
    """`<notes>/TOOLS.json`, what `status` and the pages read outside the run's process."""
    with LOCK:
        f = S.C.notes('TOOLS.json')
        tmp = f.with_suffix('.tmp')
        try:
            tmp.write_text(json.dumps({'at': time.time(), 'tools': READINGS}), encoding='utf-8')
            os.replace(tmp, f)
        except OSError:  # Windows: a reader has it open this instant
            pass


def _file() -> dict:
    try:
        d = json.loads(S.C.notes('TOOLS.json').read_text(encoding='utf-8'))
        return d['tools'] if time.time() - d['at'] <= FILE_AGE else {}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def seen() -> dict[str, dict]:
    """{tool: its reading} as the run last had it, checking nothing: the run's own, else its TOOLS.json."""
    if READINGS:
        with LOCK:
            return {n: dict(r) for n, r in READINGS.items() if n in specs()}
    return {n: r for n, r in _file().items() if n in specs()} if S.run_up() else {}


def now(name: str) -> dict | None:
    """Tool `name`'s reading for the scheduler: with no checker up in this process (a dry run) what a run beside it
    has, else a check now; None while the checker has not answered yet."""
    with LOCK:
        if r := READINGS.get(name):
            return dict(r)
    if name in THREADS:
        return None
    if r := _file().get(name):
        return r
    t = time.time()
    absorb_quiet(name, check(name), t)
    return dict(READINGS[name])


def absorb_quiet(name: str, got: tuple[str, str], at: float) -> None:
    """`absorb` outside a run's checker: nothing logged or written."""
    READINGS[name] = {'state': got[0], 'who': got[1], 'since': at, 'raw': got[0], 'n': 1, 'raw_since': at,
                      'raw_who': got[1], 'at': at, 'asked': False}


def start(free: list[int] = ()) -> None:
    """The run's checkers, one thread per tool; nothing without the setting. Readings an earlier run left minutes ago
    (an upgrade's restart) keep their times. `free`: the slots with no session, for `settle_ended`."""
    settle_ended(list(free))
    stop(keep=True)
    STOP.clear()
    READINGS.update({n: r for n, r in _file().items() if n in specs()})
    for name in specs():
        WAKES[name] = threading.Event()
        t = THREADS[name] = threading.Thread(target=_watch, args=(name, WAKES[name]), name=f'tool:{name}', daemon=True)
        t.start()


def stop(keep: bool = False) -> None:
    """End the checkers; `keep` leaves TOOLS.json."""
    STOP.set()
    for w in WAKES.values():
        w.set()
    for t in THREADS.values():
        t.join(1)
    for d in (THREADS, WAKES, READINGS, ASKED):
        d.clear()
    IGNORED.clear()
    if not keep and S.C:
        S.C.notes('TOOLS.json').unlink(missing_ok=True)


def _watch(name: str, wake: threading.Event) -> None:
    while not STOP.is_set():
        wake.clear()
        try:
            once(name)
            prune()
        except Exception as e:  # noqa: BLE001 - the next check looks again; a checker never ends the run
            log(f'shared tool {name}: {e}')
        wake.wait(pause(name))


def once(name: str, at: float | None = None) -> None:
    """One check of `name`, taken in, and its Needs you item said when it is due."""
    at = time.time() if at is None else at
    got = check(name)
    if STOP.is_set() and name in THREADS:
        return
    absorb(name, got, at)
    say_missing(at)


def pause(name: str) -> float:
    """Seconds to the next check of `name`."""
    r = READINGS.get(name)
    if r and r['raw'] != r['state']:
        return SOON
    try:
        return EVERY_WAITED if any(name in ts for ts in waiting().values()) else EVERY
    except (OSError, SystemExit):
        return EVERY


def names_task(who: str, tid: str) -> bool:
    """The holder `who` is task `tid` itself."""
    return bool(re.search(rf'(?<![A-Za-z0-9]){re.escape(tid)}(?![A-Za-z0-9])', who or ''))


def expired(r: dict) -> bool:
    """The tool's check has failed for so long that it holds no task any more."""
    return r['state'] == UNKNOWN and time.time() - r['since'] >= UNKNOWN_HOLD


def _blocks(state: str, who: str, r: dict, tid: str) -> bool:
    if state == UNKNOWN:
        return not expired(r)
    return state == MISSING or state == BUSY and not names_task(who, tid)


def hold(tid: str, needs: list[str], users: dict[str, str], before: dict[str, str]) -> tuple[str, str] | None:
    """Why task `tid` waits for a shared tool it needs: (tool, what it waits on), or None. `users`: {tool: the running
    task that has it}; `before`: {tool: a task that gave up its slot for it and goes first}."""
    for name in needs:
        if (u := users.get(name)) and u != tid:
            return name, f'held by {u}'
        r = now(name)
        if r is None:
            return name, 'not checked yet'
        if _blocks(r['state'], r['who'], r, tid):
            return name, words(r)
        if r['state'] == UNKNOWN and name in THREADS and name not in IGNORED:
            IGNORED.add(name)
            log(f'{specs()[name]["label"]}: its check has failed for {UNKNOWN_HOLD / 60:g} min; tasks that need it '
                f'start without it')
        if w := before.get(name):
            return name, f'{w} goes first'
    return None


def ready(tid: str, needs: list[str]) -> bool:
    """A start of `tid` is about to happen: its tools are checked once more, so no stale answer starts it."""
    return all(_ready(tid, n) for n in needs)


def _ready(tid: str, name: str) -> bool:
    if name not in THREADS:
        got = check(name)
        return not _blocks(*got, READINGS.get(name) or {'state': '', 'since': 0}, tid)
    if (r := READINGS.get(name)) and expired(r):
        return True  # its failing check holds nothing any more, so no start waits for it
    t = time.time()
    asked = ASKED.get(name, 0.0)
    if t - asked > FRESH_FOR:
        asked = ASKED[name] = t
        WAKES[name].set()
        end = time.monotonic() + FRESH_WAIT
        while time.monotonic() < end and (READINGS.get(name) or {}).get('at', 0) < asked:
            time.sleep(0.05)
    r = READINGS.get(name)
    if not r or r['at'] < asked:
        return False  # a slow check: its answer is read on the next tick
    ASKED.pop(name, None)
    return not _blocks(r['raw'], r['raw_who'], r, tid)


# --- tasks that gave up their slot ---------------------------------------------------------------------------------

def mark(tid: str) -> Path:
    return S.C.notes(f'{tid}.wait')


def _read(f: Path) -> dict:
    try:
        d = json.loads(f.read_text(encoding='utf-8'))
        return d if isinstance(d, dict) and d.get('tool') else {}
    except (OSError, ValueError):
        return {}


def parked() -> dict[str, dict]:
    """{task: its wait} for every task that gave up its slot, longest first. A wait: {tool, sid, slot, dirty, at,
    running}, `running` once its session goes on (kept until that ends: it has the tool)."""
    if not specs():
        return {}
    got = {f.stem: w for f in S.C.notes().glob('*.wait') if (w := _read(f))}
    return dict(sorted(((t, w) for t, w in got.items() if not w.get('running')), key=lambda x: x[1].get('at', 0)))


def holding(tid: str) -> str:
    """The tool task `tid`'s running session waited for, else ''."""
    w = _read(mark(tid))
    return w['tool'] if w.get('running') else ''


def waited(tid: str) -> dict:
    """Task `tid`'s wait when its work is there on waiting/<ID>, else {}."""
    w = _read(mark(tid))
    if not w or w.get('running') or git('rev-parse', '--verify', '-q', f'refs/heads/waiting/{tid}').returncode:
        return {}
    return w


def park(n: int, tid: str, sid: str, tool: str) -> bool:
    """Slot n's session ran `run wait-for`: keep its work, commits and uncommitted edits alike, on waiting/<tid>
    (never merged, no park count) and its session in `<notes>/<tid>.wait`, for `slots.start` to go on with. False
    when the work could not be kept: the task ends as any other."""
    d = S.SLOTS_DIR / f's{n}'
    old = _read(mark(tid))
    dirty = bool(git('status', '--porcelain', cwd=d).stdout.strip())
    if dirty and (git('add', '-A', cwd=d).returncode or
                  git('commit', '-qm', f'{tid} wip: uncommitted, waits for {tool}', '--no-verify', cwd=d).returncode):
        log(f'slot {n}: {tid} waits for {tool}, but its edits could not be kept; it ends as any other session')
        return False
    git('checkout', '-q', '--detach', cwd=d)
    mark(tid).write_text(json.dumps(
        {'tool': tool, 'sid': sid, 'slot': n, 'dirty': dirty,
         'at': old['at'] if old.get('tool') == tool and old.get('at') else time.time()}), encoding='utf-8')
    if git('branch', '-M', f'task/{tid}', f'waiting/{tid}').returncode:
        mark(tid).unlink(missing_ok=True)
        log(f'slot {n}: {tid} waits for {tool}, but task/{tid} could not become waiting/{tid}; it ends as any other '
            f'session')
        return False
    r = seen().get(tool)
    log(f'slot {n}: {tid} waits for {specs().get(tool, {}).get("label", tool)}' +
        (f', {words(r)}' if r and r['state'] != FREE else '') +
        f'; its slot is free, its work is on waiting/{tid}, and its session goes on once the tool is free',
        EV_WAITS, tid, tool=tool)
    if tool in WAKES:
        WAKES[tool].set()
    return True


def park_end(n: int, tid: str, sid: str, end: dict) -> bool:
    """Slot n's session ended with the end mark `end`: parked when it waits for a tool (`park`)."""
    return end.get('how') == 'wait' and end.get('tid') == tid and park(n, tid, sid, end.get('text', ''))


def resumed(tid: str, w: dict) -> None:
    """Task `tid`'s session goes on: its kept branch goes, and it has the tool until the session ends."""
    if not w:
        return
    git('branch', '-D', f'waiting/{tid}')
    mark(tid).write_text(json.dumps({**w, 'running': True}), encoding='utf-8')


def forget(tid: str) -> None:
    """Task `tid` waits for no tool and has none: its session ended, or it is dropped."""
    if S.C and _read(mark(tid)):
        mark(tid).unlink(missing_ok=True)
        if not git('rev-parse', '--verify', '-q', f'refs/heads/waiting/{tid}').returncode:
            git('branch', '-D', f'waiting/{tid}')


def settle_ended(slots: list[int]) -> None:
    """A run's start: park what a session that ran `run wait-for` left while no run was up, finish a park a crash
    cut short, and drop the waits of tasks done or dropped since."""
    if not specs():
        return
    from agent_runner.tools import end_mark, take_end
    from agent_runner.watch import last_session
    for n in slots:
        try:
            e = json.loads(end_mark(n, S.C).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        d = S.SLOTS_DIR / f's{n}'
        if not isinstance(e, dict) or e.get('how') != 'wait' or not d.is_dir() or \
                git('branch', '--show-current', cwd=d).stdout.strip() != f'task/{e.get("tid")}':
            continue
        last = last_session(e['tid'])
        if last and last[0] == n:
            take_end(n, S.C)
            park(n, e['tid'], last[1], e.get('text', ''))
    for tid in parked():  # a start that crashed as it woke one: the work is still on waiting/<tid>
        if waited(tid) and not git('rev-parse', '--verify', '-q', f'refs/heads/task/{tid}').returncode:
            at = [n for n in range(1, 100) if (S.SLOTS_DIR / f's{n}').is_dir() and
                  git('branch', '--show-current', cwd=S.SLOTS_DIR / f's{n}').stdout.strip() == f'task/{tid}']
            if at and at[0] not in slots:  # adopted: its session is up
                resumed(tid, _read(mark(tid)))
                continue
            if at:
                S.clean(S.SLOTS_DIR / f's{at[0]}')
                git('checkout', '-q', '--detach', cwd=S.SLOTS_DIR / f's{at[0]}')
            git('branch', '-D', f'task/{tid}')
        elif not waited(tid) and not git('rev-parse', '--verify', '-q', f'refs/heads/task/{tid}').returncode:
            git('branch', '-M', f'task/{tid}', f'waiting/{tid}')
    prune()


def prune() -> None:
    """Drop the waits of tasks ticked or dropped meanwhile (DONE.md holds them)."""
    if not (ws := {f.stem: w for f in S.C.notes().glob('*.wait') if (w := _read(f))}):
        return
    gone = {tid.rstrip('.') for _, box, tid, _, _ in P.iter_tasks(P.lines(S.C.done)) if box == 'x'}
    for tid in ws:
        if tid in gone:
            if not ws[tid].get('running'):
                log(f'{tid}: done or dropped while it waited for {ws[tid]["tool"]}; its kept work is deleted')
            forget(tid)


WOKEN = """{label} is yours to take now ({why}): you gave up your slot for it with `run wait-for`, and the runner \
resumed this session {where}. Whatever you had running in the background ended with the slot. Look at `git status`, \
take the tool's lock as this project says, then carry on with task {tid} as the first message of this session says. \
If another has it again, `run wait-for {tool}` again."""


def woken_prompt(tid: str, w: dict, where: str) -> str:
    r = seen().get(w['tool']) or {}
    why = 'its check fails, so nobody knows whether it is free' if r.get('state') == UNKNOWN else 'it is free'
    return WOKEN.format(label=specs().get(w['tool'], {}).get('label', w['tool']), why=why, where=where, tid=tid,
                        tool=w['tool'])


def wake(n: int, tid: str, d: Path, wait: dict, model: str, idle: int):
    """F168: resume the session that ran `run wait-for` in slot n, its tool free. None when it cannot be resumed."""
    from agent_runner import slots as L  # it reads this module
    sid = wait.get('sid') or ''
    if not sid or sid == '(unknown)' or not L.move_transcript(sid, d) or \
            L.on_harness(model) != bool(L.HARNESS.find_transcript(sid)):
        return None
    logfile, since = L.slot_header(n, f'{tid} woken {sid}')
    prompt = woken_prompt(tid, wait, where_now(n, d, wait.get('slot')))
    if not (pid := L.MUX.open(n, d, prompt, sid, model, idle, L.slot_env(n), logfile, resume=True)):
        log(f'slot {n}: the session for {tid} did not resume in {L.MUX.where(n)}')
        return None
    log(f'slot {n}: {tid} goes on: {wait["tool"]} is free', S.EV_STARTED, tid)
    return pid, sid, since


def where_now(n: int, d: Path, was) -> str:
    """Where a resumed session is, for its prompt: its paths change with the slot."""
    return ('in the same worktree' if was in (None, n) else
            f'in another worktree: {d} (paths you saw under {S.SLOTS_DIR / f"s{was}"} are here now)')


def not_started(tid: str, d: Path, w: dict) -> None:
    """Task `tid`'s session did not start in worktree `d`: its work is on waiting/<tid> still, and no task/<tid> stays
    for a merge to take it half done."""
    if w:
        S.clean(d)
        git('checkout', '-q', '--detach', cwd=d)
        git('branch', '-D', f'task/{tid}')


# --- what the pages say -----------------------------------------------------------------------------------------

def mins(since: float, t: float | None = None) -> str:
    return f'{max(0, int(((time.time() if t is None else t) - since) // 60))} min'


def words(r: dict | None, t: float | None = None) -> str:
    """A reading in words: 'free', 'held by F389, 12 min', 'not connected, 20 min', 'unknown: …, 2 min'."""
    if not r:
        return 'not checked yet'
    if r['state'] == FREE:
        return FREE
    said = {BUSY: f'held by {r["who"]}' if r['who'] else 'busy', MISSING: r['who'] or 'not connected',
            UNKNOWN: f'unknown: {r["who"]}'}[r['state']]
    return f'{said}, {mins(r["since"], t)}'


def _state() -> dict:
    """The run's STATE; {} while none is up."""
    try:
        if not S.run_up():
            return {}
        return json.loads(S.C.notes('STATE').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def waiting(ls: list[str] | None = None, st: dict | None = None) -> dict[str, list[str]]:
    """{task: the tools it needs} for every open task that could start but for them: not running or merging, not set
    aside, and nothing its `after:` names still open. One that gave up its slot counts too."""
    if not specs():
        return {}
    ls = P.lines(S.C.todo) if ls is None else ls
    st = _state() if st is None else st
    busy = {*(st.get('running') or {}).values(), *(st.get('merging') or [])}
    ws, open_, out = parked(), P.open_ids(ls), {}
    for section, box, tid, _, i in P.iter_tasks(ls):
        need = needs_of(ls[i])
        if box != ' ' or tid in busy:
            continue
        if tid in ws:
            need = list(dict.fromkeys([ws[tid]['tool'], *need]))
        elif not need or section.startswith(P.SKIPPED) or {t for t in P.waits_on(ls, i) if t in open_}:
            continue
        out[tid] = [n for n in need if n in specs()]
    return out


def pending(tried=()) -> bool:
    """A task waits for a tool that is busy, or whose failing check holds it a few minutes more: it goes on by itself,
    so the run is not idle (a missing tool may stay so)."""
    rs = seen()
    return bool(rs) and any((r := rs.get(n)) and (r['state'] == UNKNOWN and not expired(r) or
                                                  r['state'] == BUSY and not names_task(r['who'], tid))
                            for tid, ns in waiting().items() if tid not in tried for n in ns)


def used(ls: list[str], st: dict) -> dict[str, tuple[str, float]]:
    """{tool: (the running task that has it, since when or 0)}, by the tasks' lines and waits, not the checks."""
    need = {tid: needs_of(ls[i]) for _, _, tid, _, i in P.iter_tasks(ls)} if specs() else {}
    out: dict[str, tuple[str, float]] = {}
    for n, tid in (st.get('running') or {}).items():
        for name in [*need.get(tid, []), *([h] if (h := holding(tid)) else [])]:
            out.setdefault(name, (tid, (st.get('since') or {}).get(n, 0)))
    return out


def rows(ls: list[str] | None = None, st: dict | None = None, t: float | None = None) -> list[dict]:
    """Each shared tool for status and the pages: {name, label, state, words, waits}; [] without the setting."""
    if not specs():
        return []
    ls = P.lines(S.C.todo) if ls is None else ls
    st = _state() if st is None else st
    ws, rs, us, out = waiting(ls, st), seen(), used(ls, st), []
    for name, spec in specs().items():
        r = rs.get(name)
        said = words(r, t)
        if (u := us.get(name)) and r and r['state'] == FREE:
            said = f'held by {u[0]}' + (f', {mins(u[1], t)}' if u[1] else '')
        n = sum(name in ts for ts in ws.values())
        if n and said != FREE:
            said += f', {n} task{"s wait" if n != 1 else " waits"}'
        out.append({'name': name, 'label': spec['label'], 'state': r['state'] if r else '', 'words': said, 'waits': n})
    return out


def line(tools: list[dict]) -> str:
    """The Tools line: 'Tools: iPhone 15: held by F389, 12 min'; '' without the setting."""
    return 'Tools: ' + ' · '.join(f'{x["label"]}: {x["words"]}' for x in tools) if tools else ''


def wait_words(ls: list[str] | None = None, st: dict | None = None, t: float | None = None) -> dict[str, str]:
    """{task: 'waits for iPhone 15, held by F389, 12 min'} for the tasks a shared tool keeps waiting."""
    if not specs():
        return {}
    ls = P.lines(S.C.todo) if ls is None else ls
    st = _state() if st is None else st
    ws, rs, us, first, out = parked(), seen(), used(ls, st), {}, {}
    for tid, w in ws.items():
        first.setdefault(w['tool'], tid)
    for tid, names in waiting(ls, st).items():
        for name in names:
            r, u = rs.get(name), us.get(name)
            if r and r['state'] != FREE and not expired(r) and not (r['state'] == BUSY and names_task(r['who'], tid)):
                said = words(r, t)
            elif u:
                said = f'held by {u[0]}' + (f', {mins(u[1], t)}' if u[1] else '')
            elif first.get(name, tid) != tid:
                said = f'{first[name]} goes first'
            elif tid in ws and name == ws[tid]['tool']:
                said = 'free: it goes on in the next free slot' if r else 'not checked yet'
            else:
                continue
            out[tid] = f'waits for {specs()[name]["label"]}, {said}'
            break
    return out


def asks(c=None) -> list[tuple]:
    """The missing tools that keep tasks waiting as Needs you items, in `plan.asks`'s shape with the stamp eighth."""
    try:
        if not specs(c) or not S.C:
            return []
        out, t = [], time.time()
        ws = waiting()
        for name, r in seen().items():
            n = sum(name in ts for ts in ws.values())
            if r['state'] == MISSING and n and t - r['since'] >= MISSING_ASK:
                out.append((LABEL, f'tool-{name}', '', ask_text(name, n), '', specs()[name]['label'], False,
                            dt.datetime.fromtimestamp(r['since']).strftime('%Y-%m-%d %H:%M')))
        return out
    except (OSError, SystemExit, ValueError, KeyError, AttributeError):
        return []


def ask_text(name: str, n: int) -> str:
    return f'{specs()[name]["connect"]}: {n} task{"s wait" if n != 1 else " waits"}'


def say_missing(t: float | None = None) -> None:
    """Log a missing tool's Needs you item once per spell, when it is due: the feed and the phone get it then."""
    for _, pid, _, what, *_ in asks():
        with LOCK:
            r = READINGS.get(pid.removeprefix('tool-'))
            if not r or r['asked']:
                continue
            r['asked'] = True
        log(f'{what} [{pid}]', EV_TOOL, text=f'{what} [{pid}]')
        write()


# --- the agent's command ---------------------------------------------------------------------------------------

def cmd_wait_for(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog='run wait-for', description='A shared tool is busy or missing: give up this '
                                 'slot and wait for it. The session ends, its work is kept, and it goes on once the '
                                 'tool is free.')
    ap.add_argument('tool', help='the shared tool, as [run.tools] names it')
    a = ap.parse_args(argv)
    from agent_runner.config import cfg, main_checkout
    from agent_runner.tools import _write_end, task_here
    c = cfg(main_checkout())
    if why := unknown_names([a.tool], c):
        print(f'run wait-for: {why}', file=sys.stderr)
        return 2
    if not os.environ.get('AGENT_RUNNER_SLOT'):
        print('run wait-for: not in a runner slot, so there is no slot to give up', file=sys.stderr)
        return 2
    if not (tid := task_here()):
        print('run wait-for: this worktree is not on a task/<ID> branch, so there is no task to keep', file=sys.stderr)
        return 2
    if S.C is None:
        S.init(c.root)
    got = {n: check(n, c) for n in specs(c)}
    if mine := [n for n, (s, who) in got.items() if s == BUSY and names_task(who, tid)]:
        print(f'run wait-for: refused: {tid} itself holds {", ".join(mine)}. Release it first, or go on and use it.',
              file=sys.stderr)
        return 1
    ahead = [t for t, w in parked().items() if w['tool'] == a.tool and t != tid]
    label, (state, who) = specs(c)[a.tool]['label'], got[a.tool]
    if state == FREE and not ahead:
        print(f'{label} is free: take its lock and go on. This session keeps its slot.')
        return 0
    _write_end('wait', tid, a.tool)
    said = words({'state': state, 'who': who, 'since': time.time()}).removesuffix(', 0 min')
    print(f'{label}: {f"{ahead[0]} goes first" if state == FREE else said}.\nStop now. The session ends and its slot is '
          f'given up; {tid}\'s work is kept as it is (uncommitted edits too), and this same session goes on, ahead of '
          f'other tasks, once {label} is free.')
    return 0


BRIEF = ('Shared tools: only one task at a time can use each of {names}. When you find one busy or missing, do not '
         'wait for its lock in your slot for more than a minute: release whatever tool you hold, commit what is solid, '
         'write the journal if this project keeps one, run `{runner} wait-for <tool>` and stop. Your slot is given up, '
         'your work is kept, and this session goes on, ahead of other tasks, once the tool is free. (It says so when '
         'the tool is free after all: then take it and go on.)')


def brief(runner: str, tid: str = '') -> str:
    """The slot brief's paragraph; '' without the setting."""
    if not (known := specs()):
        return ''
    names = ', '.join(f'`{n}` ({s["label"]})' if s['label'] != n else f'`{n}`' for n, s in known.items())
    ls = P.lines(S.C.todo)
    mine = next((needs_of(ls[i]) for _, _, t, _, i in P.iter_tasks(ls) if t == tid), [])
    return BRIEF.format(names=names, runner=runner) + (
        f' This task is tagged as needing {", ".join(mine)}, so the run starts no other task with that tag beside '
        f'it; still take the lock.' if mine else '')
