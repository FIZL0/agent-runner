"""Watching sessions: transcripts, stalls, cut-offs and resumes, temp folders, memory, the API and
usage caps, upgrades, and the idle Stop hook."""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import signal
import socket
import subprocess as sp
import sys
import threading
import time
from pathlib import Path

from agent_runner import claude_use, cost, gitops, plat, shared_tools
from agent_runner.config import finished_mark, runner_cmd
from agent_runner.tools import ended
from agent_runner.state import (banner, C, FORCED, forced, git, log, PAUSED, POWER, queued, READING,
    SLOTS_DIR, stopped_by, stopping)
from agent_runner.sched import open_tasks
from agent_runner.slots import entries, GB, marker_pid, MUX, sids, slot_env, SLOTS, tmp_roots, transcript
from agent_runner.slots import claude_drift, remote_off_why


def state_line() -> str:
    """What the keys have set, for `?` and after each key."""
    what = [f'{SLOTS} slot{"s" if SLOTS != 1 else ""}']
    if stopping():
        what.append('stopping now (s!)' if forced() else f'stopping ({stopped_by()})')
    if PAUSED[0]:
        what.append('paused')
    if FORCED[0]:
        what.append('usage caps off (f)')
    if LATEST_SAID[0]:
        what.append(f'agent-runner {LATEST_SAID[0]} is out (u upgrades)')
    if POWER:
        what.append(f'{POWER} when ' + ('it stops' if stopping() else 'idle'))
    return ', '.join(what)


def stats(sid: str) -> str:
    """'N min, N calls, context Nk first, Nk peak' for the exit line. Watch the peak over a run: if it keeps
    creeping up, or more tasks come back blocked, the tasks are too big."""
    calls, ctx, ts = usage(sid)
    if not ctx or not ts:
        return 'no transcript'
    span = (dt.datetime.fromisoformat(ts[-1].replace('Z', '+00:00')) -
            dt.datetime.fromisoformat(ts[0].replace('Z', '+00:00')))
    return f'{int(span.total_seconds()) // 60} min, {calls} calls, context {ctx[0] // 1000}k first, {max(ctx) // 1000}k peak'


def context_over(sid: str, warn_k) -> tuple[str, dict] | None:
    """F25: when session `sid`'s context peaked past `warn_k` k tokens ([run] context_warn; 0 is off), what
    its exit line adds, 'peaked 168k (over 150k): runner.py 61k, test_runner.py 22k', and the event's fields
    (peak, warn, top); else None. Soft only: the fix is a smaller task or a split file."""
    try:
        warn = int(warn_k or 0)
    except (TypeError, ValueError):
        return None
    ctx = usage(sid)[1]
    if warn <= 0 or not ctx or (peak := max(ctx) // 1000) <= warn:
        return None
    t = transcript(sid)
    top = ', '.join(f'{k} {v}k' for k, v in (cost.filled(t) if t else []))
    return f'peaked {peak}k (over {warn}k)' + (f': {top}' if top else ''), {'peak': peak, 'warn': warn, 'top': top}


def usage(sid: str) -> tuple[int, list[int], list[str]]:
    """Session `sid`'s assistant calls, the context of each (input tokens, cache reads and writes too), and
    its entries' timestamps."""
    calls, ctx, ts = 0, [], []
    for d in entries(sid):
        if not isinstance(d, dict):
            continue
        ts += [d['timestamp']] if 'timestamp' in d else []
        if d.get('type') == 'assistant' and (u := d.get('message', {}).get('usage')):
            calls += 1
            ctx.append(sum(u.get(k, 0) for k in ('input_tokens', 'cache_read_input_tokens',
                                                 'cache_creation_input_tokens')))
    return calls, ctx, ts


_busy_at: dict[str, float] = {}  # session id → when stalled() last saw it running a tool


def stalled(pid: int, sid: str, limit: int) -> str | None:
    """Why a live session looks stuck, else None: quiet for `limit` seconds with no tool running (a prompt or
    a dialog the idle hook never sees), or quiet for longer than the Bash timeout even with one (a hung tool).
    A tool's run writes nothing to the transcript, so the prompt's quiet counts from the last look that saw
    one running: a 20-minute test run then a minute's thinking is not 21 minutes at a prompt (openmx's P38).
    """
    transcript_drift(sid)
    t = transcript(sid)
    now = time.time()
    quiet = now - os.path.getmtime(t) if t and os.path.exists(t) else 0
    if busy := bool(plat.children(pid)):
        _busy_at[sid] = now
    idle = min(quiet, now - _busy_at.get(sid, 0))
    if quiet > 65 * 60 or (idle > limit and not busy):
        return f'no transcript activity for {int(quiet // 60)} min' + \
               (' with a tool still running' if busy else ' at a prompt')
    return None


KNOWN_ENTRIES = ('user', 'assistant')  # the transcript entry types stalls, cut-offs, stats and the feed read
DRIFT_ENTRIES = 20  # entries a live session writes with none of KNOWN_ENTRIES before that is taken for drift (B45)
_shape_seen: set[str] = set()  # sessions whose transcript shape `transcript_drift` has settled


def transcript_drift(sid: str) -> bool:
    """B45 spot 1: a live session's transcript holds DRIFT_ENTRIES entries and none of a type agent-runner
    knows (KNOWN_ENTRIES): Claude Code changed their shape, and stall detection, cut-off resumes and session
    stats would go quiet without a word. Says so once per Claude Code version (`claude_drift`); True when it
    did. Each session is settled once: a known entry, or the warning."""
    if sid in _shape_seen or C is None:
        return False
    n, version, seen = 0, '', set()
    for d in entries(sid, skip_bad=True):
        if not isinstance(d, dict):
            continue
        if d.get('type') in KNOWN_ENTRIES:
            _shape_seen.add(sid)
            return False
        n += 1  # the whole transcript is read: a resumed or compacted session may open with many other entries
        version = version or str(d.get('version') or '')
        seen.add(str(d.get('type')))
    if n < DRIFT_ENTRIES:
        return False
    _shape_seen.add(sid)
    types = sorted(seen)
    return claude_drift('transcript', f"its transcript entries (a live session's {n} are of type "
                        f"{', '.join(types[:5]) or 'none'}, none user or assistant)",
                        'stall detection, resuming a cut-off session and session stats', version)


RESUMES_MAX = 3  # resumes of one session before a cut-off is taken for the end of it
NOT_RESUMED = {'invalid_request', 'authentication_failed', 'billing_error'}  # would fail again


def cut_off(sid: str, mid_turn: bool = False) -> str | None:
    """Why the session ended without finishing its turn, else None. An API error ends a turn in Claude Code
    and the idle stop then ends the session, though nothing was finished: the network dropped, or the API
    was down, or the account hit its usage limit. A request the API refused is not that: it would fail again. With `mid_turn`, also a transcript
    that stops inside a turn: the machine went down under it. A finished session ends on a turn it ended."""
    last = None
    for d in entries(sid, skip_bad=True):
        if d.get('type') in ('user', 'assistant') and not d.get('isSidechain') and not d.get('isMeta'):
            last = d
    if not last:
        return None
    m = last.get('message') if isinstance(last.get('message'), dict) else {}
    if last.get('isApiErrorMessage'):
        c = m.get('content')
        text = c if isinstance(c, str) else ' '.join(x.get('text', '') for x in c or [] if isinstance(x, dict))
        text = ' '.join(text.split())
        if last.get('error') in NOT_RESUMED:
            return None
        return text[:160] or f'API error {last.get("error")}'
    if mid_turn and (last['type'] == 'user' or m.get('stop_reason') in (None, 'tool_use')):
        return 'its transcript stops mid-turn'
    return None


def queue_resume(tid: str, n: int, sid: str, why: str) -> None:
    C.notes(f'{tid}.resume').write_text(json.dumps({'slot': n, 'sid': sid, 'why': why}), encoding='utf-8')


HEADER = re.compile(r'^=== (\S+) (\S+) (?:session|resume|woken) (\S+)')


def resumes(n: int, sid: str) -> int:
    """How often session `sid` has been resumed (its slot log's resume headers)."""
    try:
        with open(C.notes(f'slot{n}.log'), encoding='utf-8', errors='replace') as f:
            return sum(1 for l in f if l.startswith('=== ') and f' resume {sid} ' in l)
    except OSError:
        return 0


def last_session(tid: str) -> tuple[int, str] | None:
    """(slot, session) of task `tid`'s latest session, from the slot logs' headers."""
    best = None
    for f in C.notes().glob('slot*.log'):
        if not re.fullmatch(r'slot\d+', f.stem):
            continue
        with open(f, encoding='utf-8', errors='replace') as fh:
            for l in fh:
                if (m := HEADER.match(l)) and m.group(2) == tid and (not best or m.group(1) >= best[0]):
                    best = (m.group(1), int(f.stem[4:]), m.group(3))
    return best and best[1:]


SESSION_TMP_KEEP = 24 * 3600  # s with no file written before a session's temp folder that nothing runs is swept
SWEEP_EVERY = 6 * 3600        # s between sweeps in a long run
_swept = [-1e9]


def drop_session_tmp(sid: str) -> None:
    """Delete session `sid`'s temp folder and long brief: it has ended for good (not queued to resume)."""
    if not re.fullmatch(r'[0-9a-f-]{36}', sid or ''):
        return
    C.notes(f'{sid}.brief').unlink(missing_ok=True)
    full_mark(sid, C).unlink(missing_ok=True)
    for root in tmp_roots():
        for d in root.glob(f'claude-*/*/{sid}'):
            shutil.rmtree(d, ignore_errors=True)


def project_slug(p: Path) -> str:
    """Claude Code's folder name for a working directory: every character but [A-Za-z0-9] as '-'."""
    return re.sub(r'[^A-Za-z0-9]', '-', str(p.resolve()))


def live_sessions() -> set[str]:
    """The session ids of every agent process running now (POSIX; empty where /proc is missing)."""
    out = set()
    for f in Path('/proc').glob('[0-9]*/cmdline'):
        try:
            args = f.read_text(errors='replace').split('\0')
        except OSError:
            continue
        out.update(sids(args))
    return out


def end_orphans() -> None:
    """End what ended sessions left running (POSIX). Killing a session leaves its tools' processes behind,
    reparented to init: partyboard collected Gradle daemons and `find /` crawls of an sftp mount that ran
    for 20 h, 5 GB and two cores between them. Each carries AGENT_RUNNER=1 and its session's
    CLAUDE_CODE_SESSION_ID in its environment (a detached daemon too); one whose session no agent runs
    any more gets SIGTERM, then SIGKILL."""
    if plat.WINDOWS:
        return
    live, found = live_sessions(), []
    for f in Path('/proc').glob('[0-9]*/environ'):
        try:
            env = dict(v.split('=', 1) for v in f.read_bytes().decode(errors='replace').split('\0') if '=' in v)
        except OSError:
            continue
        pid = int(f.parent.name)
        if env.get('AGENT_RUNNER') == '1' and (s := env.get('CLAUDE_CODE_SESSION_ID')) and s not in live \
                and pid != os.getpid():
            found.append((pid, s, ' '.join(plat.cmdline(pid) or [])[:80]))
    for pid, s, what in found:
        log(f'ending pid {pid} left by session {s}: {what}')
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    end = time.monotonic() + 5
    while (found := [f for f in found if plat.alive(f[0])]) and time.monotonic() < end:
        time.sleep(0.25)
    for pid, *_ in found:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


def newest_write(d: Path) -> float:
    newest = d.stat().st_mtime
    for top, dirs, files in os.walk(d):
        for name in dirs + files:
            try:
                newest = max(newest, os.lstat(os.path.join(top, name)).st_mtime)
            except OSError:
                pass
    return newest


def sweep_tmp(force: bool = False) -> None:
    """Delete this repository's sessions' temp folders (the slots' and the merge worktree's) that no process
    runs, no resume waits for, and nothing wrote to in SESSION_TMP_KEEP: a session that ended while no run
    was up or under a Ctrl-C'd run. Not the main checkout's: a person's interactive session
    there has no session id on its command line to tell it is still running."""
    if not force and time.monotonic() - _swept[0] < SWEEP_EVERY:
        return
    _swept[0] = time.monotonic()
    if plat.WINDOWS:  # no /proc to tell a live session from a finished one
        return
    end_orphans()
    keep = live_sessions() | {q[1] for q in queued().values()}
    mine = {project_slug(d) for d in SLOTS_DIR.glob('*') if re.fullmatch(r's\d+|merge|fix\d+', d.name)}
    cutoff, freed = time.time() - SESSION_TMP_KEEP, 0
    for root in tmp_roots():
        for proj in root.glob('claude-*/*'):
            if proj.name not in mine:
                continue
            for d in proj.iterdir():
                if not re.fullmatch(r'[0-9a-f-]{36}', d.name) or d.name in keep or not d.is_dir():
                    continue
                try:
                    if newest_write(d) > cutoff:
                        continue
                    freed += sum(f.stat().st_size for f in d.rglob('*') if f.is_file() and not f.is_symlink())
                except OSError:
                    continue
                shutil.rmtree(d, ignore_errors=True)
    if freed:
        log(f'swept {freed / 2**20:,.0f} MB of ended sessions\' temp folders')


MEM_EVERY = 10  # seconds between memory_watch's looks


def runner_procs() -> list[tuple[int, int, str]]:
    """(pid, resident bytes, command) of each process the run started, the agents themselves aside (Linux):
    one working in a worktree of ours (s1…, merge, merge2, fix…) or carrying a slot's AGENT_RUNNER=1."""
    home, out = str(SLOTS_DIR.resolve()), []
    for d in Path('/proc').iterdir():
        if not d.name.isdigit() or int(d.name) == os.getpid():
            continue
        try:
            cwd = os.readlink(d / 'cwd')
            ours = cwd == home or cwd.startswith(home + os.sep) or b'\0AGENT_RUNNER=1\0' in b'\0' + (d / 'environ').read_bytes()
            rss = next(int(l.split()[1]) * 1024 for l in (d / 'status').read_text().splitlines() if l.startswith('VmRSS:'))
        except (OSError, StopIteration, ValueError):
            continue
        if ours and not sids(args := plat.cmdline(int(d.name)) or []):
            out.append((int(d.name), rss, ' '.join(args).strip()[:100]))
    return out


def mem_hogs(procs: list[tuple[int, int, str]], avail: int, total: int) -> list[tuple[int, str]]:
    """Which of `procs` (`runner_procs`) `memory_watch` ends, each with why: any resident past `[run]
    proc_max_gb`; failing that, while less than `[run] min_free_mem_gb` is available, the biggest one (if it
    holds a GB: a leak outside the run is not the gates' to pay for one by one)."""
    cap = C.run['proc_max_gb']
    cap = total // 4 if cap == 'auto' else int(float(cap) * GB)
    out = [(p, f'{rss / GB:.1f} GB resident, past [run] proc_max_gb ({cap / GB:.0f} GB)')
           for p, rss, _ in procs if cap and rss > cap]
    floor = C.run['min_free_mem_gb'] * GB
    if not out and floor and avail < floor and procs:
        p, rss, _ = max(procs, key=lambda x: x[1])
        if rss >= GB:
            out.append((p, f"the run's biggest process ({rss / GB:.1f} GB) with {avail / GB:.1f} GB of memory "
                           f'left, under [run] min_free_mem_gb ({C.run["min_free_mem_gb"]} GB)'))
    return out


def memory_watch() -> None:
    """End a runaway before it takes the machine (Linux): every MEM_EVERY s, `mem_hogs`' picks get SIGKILL,
    that process alone, so its gate or session sees one test die and goes on. A test that walked a looping
    tree in RAM held 52 GB in each of three slots' gates (openmx, 11-10), and the desktop's OOM handling
    ended other work for it."""
    while True:
        time.sleep(MEM_EVERY)
        try:
            shared_tools.prune()
            shared_tools.say_memory()  # B184: once, about a task that keeps waiting for memory
        except Exception as e:  # noqa: BLE001 - the next look tries again
            log(f'memory: {e}')
        if not (C.run['proc_max_gb'] or C.run['min_free_mem_gb']):
            continue
        try:
            info = {l.split(':')[0]: int(l.split()[1]) * 1024 for l in Path('/proc/meminfo').read_text().splitlines()}
            procs = runner_procs()
            hogs = mem_hogs(procs, info['MemAvailable'], info['MemTotal'])
        except (OSError, ValueError, IndexError, KeyError):
            continue
        for pid, why in hogs:
            rss, cmd = next((r, c) for p, r, c in procs if p == pid)
            cut, cwd = thread_names(pid), plat_cwd(pid)
            log(f'ended pid {pid}, {why}: {cmd}')
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
            home = str(SLOTS_DIR.resolve()) + os.sep
            where = cwd[len(home):].split(os.sep)[0] if cwd.startswith(home) else cwd
            for name in test_names(cmd.split(' ')[0], cut, cwd):
                log(f'{name}: the test it was running; a task to fix it is filed at the next merge')
                HOGS.setdefault(name, (f'{rss / GB:.0f}', where))


HOGS: dict[str, tuple[str, str]] = {}  # a test memory_watch ended -> (GB it held, the worktree): `file_flaky` files it


def plat_cwd(pid: int) -> str:
    try:
        return os.readlink(f'/proc/{pid}/cwd')
    except OSError:
        return ''


def thread_names(pid: int) -> set[str]:
    """The names of `pid`'s threads but its main one's: a Rust test binary names each test's thread after the
    test (cut to 15 characters by the kernel)."""
    try:
        main = Path(f'/proc/{pid}/comm').read_text().strip()
        return {n for t in Path(f'/proc/{pid}/task').iterdir() if (n := (t / 'comm').read_text().strip()) != main}
    except OSError:
        return set()


def test_names(exe: str, cut: set[str], cwd: str) -> list[str]:
    """The whole names of the tests whose threads are `cut`, from the binary's own `--list`; none when `exe`
    is not a test binary (a build, a tool) or no test matches."""
    if not cut or not exe:
        return []
    try:
        ls = sp.run([exe, '--list', '--format', 'terse'], capture_output=True, text=True, timeout=60,
                    cwd=cwd or None, stdin=sp.DEVNULL).stdout
    except (OSError, sp.SubprocessError, ValueError):
        return []
    names = [l[:-len(': test')] for l in ls.splitlines() if l.endswith(': test')]
    return sorted({n for c in cut for n in names if n.startswith(c)} if len(names) else set())


def live_session(sid: str) -> int | None:
    """The pid of a process still running session `sid` (its command line names it), or None: a session
    no run started (by hand, or by an older agent-runner) is not cut off however its transcript ends. POSIX
    only; the Windows terminals' job files name every session they started."""
    if plat.WINDOWS or not sid:
        return None
    for d in Path('/proc').iterdir():
        if d.name.isdigit() and int(d.name) != os.getpid() and (args := plat.cmdline(int(d.name))) \
                and sid in sids(args) and not any(a.startswith('--stop-') for a in args):
            return int(d.name)
    return None


def queue_cut_off(branch: str, slots: list[int]) -> dict[int, int]:
    """Startup: a slot still on task/<ID> whose session was cut off while no run was up (a reboot, the runner
    killed, the network down at its exit) is queued to resume instead of being reset for a new task.
    Returns {slot: pid} of the slots whose session still runs outside this run's slots (one an older
    agent-runner started, say): resuming it would put a second agent in the worktree, so the slot is
    held until that process ends."""
    open_ids = open_tasks(branch)
    waiting = queued()
    held = {}
    for n in slots:
        if n in waiting or not (SLOTS_DIR / f's{n}').is_dir():
            continue
        tid = git('branch', '--show-current', cwd=SLOTS_DIR / f's{n}').stdout.strip().removeprefix('task/')
        if tid not in open_ids or (last_session(tid) or (0,))[0] != n:
            continue
        sid = last_session(tid)[1]
        if pid := live_session(sid):
            held[n] = pid
            log(f'slot {n}: {tid}\'s session still runs (pid {pid}) outside this run\'s slots; slot held '
                f'until it ends')
        elif (why := cut_off(sid, mid_turn=True)) and resumes(n, sid) < RESUMES_MAX:
            queue_resume(tid, n, sid, why)
            log(f'slot {n}: {tid} was cut off while no run was up ({why}); it resumes there')
    return held


_api = [-1e9, True]


def api_down(said: set[str]) -> bool:
    """`api_up` is False: said once (in `said`) until it is up again."""
    if api_up():
        said.discard('api')
        return False
    if 'api' not in said:
        said.add('api')
        log('the API cannot be reached: nothing resumes or starts until it can')
    return True


def api_up(own: bool = False) -> bool:
    """Whether the agent's API can be reached (a TCP connect), checked at most every 10 s. A session started
    or resumed while it cannot be dies at its first call. True for another agent, with no role
    on Claude Code (F406h; `own`, B791: asked for a task whose own model is claude's, so checked all the same), or
    behind a proxy."""
    if not (own or claude_use.account(C)) or any(os.environ.get(k) for k in ('HTTPS_PROXY', 'https_proxy')):
        return True
    if time.time() - _api[0] >= 10:
        host = re.sub(r'^\w+://|[:/].*$', '', os.environ.get('ANTHROPIC_BASE_URL') or 'api.anthropic.com')
        try:
            socket.create_connection((host, 443), timeout=5).close()
            _api[1] = True
        except OSError:
            _api[1] = False
        _api[0] = time.time()
    return _api[1]


START_TRIES = 3  # a task whose session will not start is tried this many times in a run


_account = [-1e9, None]
_account_login = ['']  # B848a: the login _account[1] was read for


def usage_login() -> str:
    """B848a: which Claude login the kept usage reading belongs to: the account's uuid from Claude Code's config
    (a hash of it, never a token), '' when it cannot be told."""
    import hashlib
    cfg = Path(os.environ.get('CLAUDE_CONFIG_DIR') or Path.home()) / '.claude.json'
    try:
        uid = json.loads(cfg.read_text(encoding='utf-8'))['oauthAccount']['accountUuid']
    except (OSError, ValueError, KeyError, TypeError):
        return ''
    return hashlib.sha256(str(uid).encode()).hexdigest()[:16] if uid else ''


def usage_file(login: str) -> Path:
    """B848a: where this machine keeps the last good usage reading of one login, outside any project."""
    base = Path(os.environ.get('XDG_STATE_HOME') or Path.home() / '.local' / 'state')
    return base / 'agent-runner' / f'usage-{login}.json'


def _resets_passed(w, now: float) -> bool:
    from datetime import datetime
    try:
        return datetime.fromisoformat(str(w['resets_at']).replace('Z', '+00:00')).timestamp() <= now
    except (TypeError, KeyError, ValueError):
        return False


def kept_usage(now: float | None = None) -> dict | None:
    """B848a: the last good usage reading kept for the current login, its windows whose resets_at has passed
    dropped; None when there is none (or the login cannot be told)."""
    login = usage_login()
    if not login:
        return None
    try:
        got = json.loads(usage_file(login).read_text(encoding='utf-8'))['usage']
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not isinstance(got, dict):
        return None
    return live_windows(got, now)


def live_windows(got, now: float | None = None) -> dict | None:
    """B848a: a reading without its windows whose resets_at has passed; None when nothing is left."""
    if not isinstance(got, dict):
        return None
    now = time.time() if now is None else now
    got = {k: v for k, v in got.items() if not (isinstance(v, dict) and _resets_passed(v, now))}
    return got or None


def keep_usage(got: dict) -> None:
    """B848a: store a good reading for the current login, written atomically."""
    login = usage_login()
    if not login:
        return
    f = usage_file(login)
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_name(f'{f.name}.{os.getpid()}.tmp')
        tmp.write_text(json.dumps({'at': time.time(), 'usage': got}), encoding='utf-8')
        os.replace(tmp, f)
    except OSError:
        pass


def known_usage() -> dict | None:
    """B848a: the usage the cap reads with no fetch: this process's last reading, else the kept one."""
    if isinstance(_account[1], dict) and _account_login[0] == usage_login():
        return live_windows(_account[1])
    return kept_usage()


USAGE_EVERY = 300  # s: at most one usage fetch per machine this often (B848b)
USAGE_BACKOFF_MAX = 4 * 3600  # s: the longest wait after repeated 429s


def usage_fetch_file() -> Path:
    """B848b: the machine's usage fetch state (last attempt, next allowed, failures in a row), shared by all runs."""
    return usage_file('x').with_name('usage-fetch.json')


def usage_backoff(fails: int, retry_after: float | None) -> float:
    """B848b: how long to wait after the `fails`-th 429 in a row; Retry-After 0 (or none) counts as none."""
    wait = min(USAGE_EVERY * 2 ** max(fails - 1, 0), USAGE_BACKOFF_MAX)
    return max(wait, retry_after or 0)


def _fetch_usage() -> dict:
    import urllib.request
    tok = json.load(open(os.path.expanduser('~/.claude/.credentials.json')))['claudeAiOauth']['accessToken']
    req = urllib.request.Request('https://api.anthropic.com/api/oauth/usage',
                                 headers={'Authorization': f'Bearer {tok}', 'anthropic-beta': 'oauth-2025-04-20'})
    got = json.load(urllib.request.urlopen(req, timeout=10))
    if not isinstance(got, dict):
        raise ValueError
    return got


def account_usage() -> dict | None:
    """The account's usage from the endpoint Claude Code's `/usage` reads (the local login's OAuth token; costs
    no tokens). B848b: one fetch per machine at most every USAGE_EVERY s, under a lock shared by all runs and
    Runner Home, with backoff after 429s, the state kept on disk; others read the kept reading. A failed fetch
    keeps the last good reading (B848a); None when there never was one: "don't cap"."""
    if time.time() - _account[0] < USAGE_EVERY:
        return _account[1]
    import fcntl
    import urllib.error
    sf = usage_fetch_file()
    try:
        sf.parent.mkdir(parents=True, exist_ok=True)
        lock = open(sf.with_name('usage-fetch.lock'), 'a')
    except OSError:
        lock = None
    try:
        if lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            st = json.loads(sf.read_text(encoding='utf-8'))
            st = st if isinstance(st, dict) else {}
        except (OSError, ValueError):
            st = {}
        now = time.time()
        if st.get('login') != usage_login():  # another login: its own fetch, not the old one's backoff
            st = {'login': usage_login()}
        if now < float(st.get('next') or 0):
            _account[1], _account_login[0] = known_usage_disk(), usage_login()
        else:
            st['at'] = now
            try:
                got = _fetch_usage()
                _account[1], _account_login[0] = got, usage_login()
                keep_usage(got)
                st['fails'], st['next'] = 0, now + USAGE_EVERY
            except Exception as e:
                if isinstance(e, urllib.error.HTTPError) and e.code == 429:
                    st['fails'] = int(st.get('fails') or 0) + 1
                    try:
                        ra = float((e.headers or {}).get('Retry-After') or 0)
                    except (TypeError, ValueError):
                        ra = 0
                    st['next'] = now + usage_backoff(st['fails'], ra)
                else:
                    st['next'] = now + USAGE_EVERY
                _account[1] = known_usage()  # the last good reading: this process's, else the kept one
                _account_login[0] = usage_login()
            try:
                tmp = sf.with_name(f'{sf.name}.{os.getpid()}.tmp')
                tmp.write_text(json.dumps(st), encoding='utf-8')
                os.replace(tmp, sf)
            except OSError:
                pass
    finally:
        if lock:
            lock.close()
    _account[0] = time.time()
    return _account[1]


_login_usage: dict[str, list] = {}  # F514: {config dir: [read at, reading]} of the other logins, in this process


def config_login(cfg: str) -> str:
    """F514: `usage_login` of the Claude login kept in config dir `cfg`, '' when it cannot be told (read from that
    dir alone, the process's environment untouched)."""
    import hashlib
    try:
        uid = json.loads((Path(cfg) / '.claude.json').read_text(encoding='utf-8'))['oauthAccount']['accountUuid']
    except (OSError, ValueError, KeyError, TypeError):
        return ''
    return hashlib.sha256(str(uid).encode()).hexdigest()[:16] if uid else ''


def _fetch_login_usage(cfg: str) -> dict:
    import urllib.request
    tok = json.loads((Path(cfg) / '.credentials.json').read_text(encoding='utf-8'))['claudeAiOauth']['accessToken']
    req = urllib.request.Request('https://api.anthropic.com/api/oauth/usage',
                                 headers={'Authorization': f'Bearer {tok}', 'anthropic-beta': 'oauth-2025-04-20'})
    got = json.load(urllib.request.urlopen(req, timeout=10))
    if not isinstance(got, dict):
        raise ValueError
    return got


def login_usage(cfg: str) -> dict | None:
    """F514: the usage of the Claude login whose credentials are in config dir `cfg` ('' the default login:
    `account_usage`). As `account_usage`: one fetch per login per machine at most every USAGE_EVERY s, under a lock,
    backoff after 429s, the last good reading kept on disk (`usage_file`); None when there never was one."""
    if not cfg:
        return account_usage()
    login = config_login(cfg)
    if not login:
        return None
    had = _login_usage.get(cfg)
    if had and time.time() - had[0] < USAGE_EVERY:
        return had[1]
    import fcntl
    import urllib.error
    sf = usage_fetch_file().with_name(f'usage-fetch-{login}.json')
    kept = usage_file(login)

    def disk() -> dict | None:
        try:
            return live_windows(json.loads(kept.read_text(encoding='utf-8'))['usage'])
        except (OSError, ValueError, KeyError, TypeError):
            return live_windows(had[1]) if had else None
    try:
        sf.parent.mkdir(parents=True, exist_ok=True)
        lock = open(sf.with_name(f'usage-fetch-{login}.lock'), 'a')
    except OSError:
        lock = None
    got = None
    try:
        if lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            st = json.loads(sf.read_text(encoding='utf-8'))
            st = st if isinstance(st, dict) else {}
        except (OSError, ValueError):
            st = {}
        now = time.time()
        if now < float(st.get('next') or 0):
            got = disk()
        else:
            st['at'] = now
            try:
                got = _fetch_login_usage(cfg)
                st['fails'], st['next'] = 0, now + USAGE_EVERY
                try:
                    tmp = kept.with_name(f'{kept.name}.{os.getpid()}.tmp')
                    tmp.write_text(json.dumps({'at': now, 'usage': got}), encoding='utf-8')
                    os.replace(tmp, kept)
                except OSError:
                    pass
            except Exception as e:
                if isinstance(e, urllib.error.HTTPError) and e.code == 429:
                    st['fails'] = int(st.get('fails') or 0) + 1
                    try:
                        ra = float((e.headers or {}).get('Retry-After') or 0)
                    except (TypeError, ValueError):
                        ra = 0
                    st['next'] = now + usage_backoff(st['fails'], ra)
                else:
                    st['next'] = now + USAGE_EVERY
                got = disk()
            try:
                tmp = sf.with_name(f'{sf.name}.{os.getpid()}.tmp')
                tmp.write_text(json.dumps(st), encoding='utf-8')
                os.replace(tmp, sf)
            except OSError:
                pass
    finally:
        if lock:
            lock.close()
    _login_usage[cfg] = [time.time(), got]
    return got


def known_usage_disk() -> dict | None:
    """B848b: the kept reading (another process may have fetched it), else this process's."""
    return kept_usage() or known_usage()


LOGIN_CMD = 'claude auth login'  # F126: what renews the Claude login
LOGIN_WARN = 3 * 86400  # s before its end that the Claude login is warned about


def own_claude_login(agent: str = 'claude') -> bool:
    """F126: do sessions run on the claude.ai login Claude Code keeps on this machine? Not with another agent, an
    API key or token, another provider or base URL, or an apiKeyHelper: there is no login to renew then."""
    from agent_runner.config import user_settings_file
    if agent != 'claude' or os.environ.get('CLAUDE_CODE_OAUTH_TOKEN') or remote_off_why(dialog=False):
        return False
    try:
        return not json.loads(user_settings_file().read_text(encoding='utf-8')).get('apiKeyHelper')
    except (OSError, ValueError, AttributeError):
        return True


def claude_login(now: float | None = None, path: Path | None = None, agent: str = 'claude') -> str:
    """F126: what to say about the Claude login when it ends in under 3 days, has ended, or is missing; '' when it
    is fine or cannot be told. Read from Claude Code's credentials file (`path`): refreshTokenExpiresAt, not
    expiresAt, which is the access token's and renewed by itself. On macOS the login is in the Keychain, so a
    missing file says nothing; a login with no refreshTokenExpiresAt (an older Claude Code's) neither."""
    if not own_claude_login(agent):
        return ''
    path = path or Path(os.environ.get('CLAUDE_CONFIG_DIR') or Path.home() / '.claude') / '.credentials.json'
    missing = '' if sys.platform == 'darwin' else 'No Claude login: log in'
    try:
        oauth = json.loads(path.read_text(encoding='utf-8'))['claudeAiOauth']
        has_token = bool(oauth.get('refreshToken'))
    except FileNotFoundError:
        return missing
    except OSError:  # there, but not readable now
        return ''
    except (ValueError, KeyError, TypeError, AttributeError):
        return missing
    if not has_token:
        return missing
    ends = oauth.get('refreshTokenExpiresAt')
    if not isinstance(ends, (int, float)) or isinstance(ends, bool):
        return ''
    left = ends / 1000 - (time.time() if now is None else now)
    if left <= 0:
        return 'Claude login has expired: log in again'
    if left >= LOGIN_WARN:
        return ''
    n, unit = (int(left // 86400), 'day') if left >= 86400 else (int(left // 3600), 'hour')
    return f'Claude login expires in {f"{n} {unit}" + ("s" if n != 1 else "") if n else "under 1 hour"}: log in again'


def claude_login_line() -> str:
    """F126: `claude_login` and the command that renews it, as `status` and the TUI say it; '' when it is fine, or no role
    runs on it (F406h)."""
    said = claude_login(agent=C.run['agent']) if claude_use.uses(C) else ''
    return f'{said} ({LOGIN_CMD})' if said else ''


def usage_pct(name: str) -> float | None:
    """One window's usage %: 'seven_day' or 'five_hour' (the session limit). None when it cannot be read."""
    try:
        return account_usage()[name]['utilization']
    except (TypeError, KeyError):
        return None


def weekly() -> float | None:
    """The account's 7-day usage %, or None."""
    return usage_pct('seven_day')


LATEST = 'https://raw.githubusercontent.com/FIZL0/agent-runner/main/agent_runner/__init__.py'
VERSION = re.compile(r"""^__version__\s*=\s*['"](\d+(?:\.\d+)+)['"]""", re.M)


LATEST_SAID = ['']  # the newer version update_notice last announced: once per version
UPDATE_EVERY = 6 * 3600  # s between looks at main for a newer version


def update_watch() -> None:
    """A daemon thread for the whole run: `update_notice` at the start and every UPDATE_EVERY s."""
    while True:
        update_notice()
        time.sleep(UPDATE_EVERY)


def update_notice() -> None:
    """A green banner when main has a newer version than this one, once per version, saying how to upgrade
    (`u` when the pane reads keys). Silent when it cannot tell (offline, GitHub down, a clone ahead of main)."""
    import urllib.request
    from agent_runner import __version__
    try:
        text = urllib.request.urlopen(LATEST, timeout=5).read().decode()
        latest = VERSION.search(text)[1]
        newer = tuple(map(int, latest.split('.'))) > tuple(map(int, __version__.split('.')))
    except Exception:
        return
    if newer and latest != LATEST_SAID[0]:
        LATEST_SAID[0] = latest
        how = 'nothing, [run] auto_upgrade does it once no merge runs' if AUTO_UPGRADE[0] and \
            not plat.WINDOWS and not breaking(__version__, latest) else 'type u + Enter in the run view' if READING[0] else \
            f'run `{" ".join(upgrade_argv()[:3]) if upgrade_argv()[0] != "git" else "git pull"}`'
        own = AUTO_UPGRADE[0] or READING[0]  # F149: off, only an upgrade asked of the run restarts it
        then = ('the run restarts on it by itself' if own and not plat.WINDOWS and not breaking(__version__, latest)
                else 'then read CHANGELOG.md and restart the run')
        banner(f'agent-runner {latest} is out', f'this run is {__version__}. To upgrade: {how}; {then}.', '42')


BREAKING_MINORS = ((0, 60),)  # C28: 0.x minors a run cannot restart across (0.60.0 dropped tmux: no adopting)


def breaking(old: str, new: str) -> bool:
    """`new` is another major version, or crosses one of BREAKING_MINORS (a 0.x minor may break too,
    docs/SETUP.md#versions; most are features and the rare breaking one is listed there)."""
    if old.split('.')[0] != new.split('.')[0]:
        return True
    try:
        o, n = vtuple(old)[:2], vtuple(new)[:2]
    except ValueError:
        return False
    return any(min(o, n) < b <= max(o, n) for b in BREAKING_MINORS)


def upgrade_argv(here: str | Path = __file__) -> list[str]:
    """The command that upgrades this install: pipx, uv tool, or a pull in the clone it runs from.
    B97: told apart by where agent_runner itself lives, not sys.prefix: a wrapper (openmx's ./kit) runs the
    system python3 with uv's site-packages on sys.path, so sys.prefix is /usr and a pull ran in site-packages.
    A clone is the one with a .git beside agent_runner/; any other install is pipx (by its path) or else uv tool,
    the one the README installs with, wherever UV_TOOL_DIR put it."""
    path = Path(here).resolve()
    if (path.parents[1] / '.git').exists():
        return ['git', '-C', str(path.parents[1]), 'pull', '-q', '--ff-only']
    if 'pipx' in path.parts:
        return ['pipx', 'upgrade', 'agent-runner']
    return ['uv', 'tool', 'upgrade', 'agent-runner']


def installed_version() -> str | None:
    """The version on disk under this process, which an upgrade changes and the running code does not."""
    try:
        return VERSION.search((Path(__file__).parent / '__init__.py').read_text(encoding='utf-8'))[1]
    except (OSError, TypeError):
        return None


def upgrade() -> bool:
    """`u` in the run view, `agent-runner upgrade` or [run] auto_upgrade: run `upgrade_argv`, logged. True when it worked."""
    argv = upgrade_argv()
    log(f'upgrading: {" ".join(argv)}')
    try:
        p = sp.run(argv, capture_output=True, text=True, timeout=300)
    except (OSError, sp.TimeoutExpired) as e:
        log(f'the upgrade failed: {e}')
        return False
    if p.returncode:
        log(f'the upgrade failed (exit {p.returncode}): {(p.stderr or p.stdout).strip()[-300:]}')
        return False
    from agent_runner import __version__
    new = installed_version()
    UPGRADED[0] = bool(new and new != __version__ and not breaking(__version__, new))
    log(f'upgraded to {new}; the run restarts on it' if new and new != __version__ else
        f'already the latest ({__version__})')
    return True


AUTO_UPGRADE = [True]  # [run] auto_upgrade (on by default): the run presses `u` itself when update_notice sees a newer version
AUTO_TRIED = ['']  # the version auto_upgrade last ran the upgrade for: once per version, even when it failed


def vtuple(v: str) -> tuple[int, ...]:
    return tuple(map(int, v.split('.')))


def auto_upgrade_due(latest: str, current: str, installed: str | None, merging: bool, tried: str,
                     windows: bool = False) -> bool:
    """[run] auto_upgrade: upgrade now? Only for a newer release the update check saw, not yet installed
    and not tried already, and only between merges (a merge in flight finishes first, then the next tick
    upgrades). Never across a major version or on Windows, where `restart_if_upgraded` would not restart."""
    try:
        newer = bool(latest) and vtuple(latest) > vtuple(current)
        on_disk = bool(installed) and vtuple(installed) >= vtuple(latest)
    except ValueError:
        return False
    return newer and not on_disk and not merging and latest != tried and not windows \
        and not breaking(current, latest)


def auto_upgrade(merging: bool) -> threading.Thread | None:
    """The run loop's tick: start `upgrade` in a thread when `auto_upgrade_due`. The loop's own
    `restart_if_upgraded` then restarts on what it installed, keeping the keys (AGENT_RUNNER_KEEP)."""
    from agent_runner import __version__
    latest = LATEST_SAID[0]
    if not AUTO_UPGRADE[0] or not auto_upgrade_due(latest, __version__, installed_version(), merging,
                                                   AUTO_TRIED[0], plat.WINDOWS):
        return None
    AUTO_TRIED[0] = latest
    log(f'agent-runner {latest} is out (this run is {__version__}): upgrading by itself ([run] auto_upgrade)')
    t = threading.Thread(target=upgrade, daemon=True)
    t.start()
    return t


_upgrade_seen: str | None = None
UPGRADED = [False]  # F149: this run installed the version on disk itself (`u`, auto_upgrade): it restarts on it
RESTART_NEEDED = ['']  # F149: which newer code only a person restarts the run on ('': none); the page says so
RESTART = [False]  # F97: the `restart` key was sent: the next tick with no merge going restarts the run


def restart_if_upgraded() -> None:
    """Re-exec this run on the version now installed under it (`uv tool upgrade`, a pull in a clone), so the
    loop never runs older code than the `done` and Stop hook the sessions call by path. The new process
    adopts the sessions, merges and gates like any restart. Called only with no merge thread going.

    Not on Windows (no real exec: the console would get a second process), and not across a breaking
    version, whose CHANGELOG a human reads first. The new version must be seen on two ticks, so a restart
    never lands mid-install."""
    global _upgrade_seen
    from agent_runner import __version__
    if RESTART[0] and not plat.WINDOWS:
        RESTART[0] = False
        log(f'restarting the run, keeping {state_line()}')
        return restart_run()
    new = installed_version()
    if not new or new == __version__ or plat.WINDOWS:
        return
    if breaking(__version__, new):
        if _upgrade_seen != new:
            log(f'agent-runner {new} is installed (this run is {__version__}): a breaking version, so no restart '
                f'by itself; read CHANGELOG.md, then restart the run')
        _upgrade_seen = new
        return
    if not AUTO_UPGRADE[0] and not UPGRADED[0]:  # F149: nothing restarts by itself
        if _upgrade_seen != new:
            log(f'agent-runner {new} is installed (this run is {__version__}): restart the run to use it '
                f'([run] auto_upgrade is off)')
        _upgrade_seen = new
        return
    if _upgrade_seen != new:
        _upgrade_seen = new  # once more next tick, then restart
        return
    log(f'agent-runner {new} is installed (this run is {__version__}); restarting on it, keeping {state_line()}')
    restart_run()


CODE = {'on': None, 'held': False, 'person': ''}  # tree started on; a due restart a merge holds up; the tree a person restarts for


def code_tree(root: str | Path) -> str | None:
    """F149: the committed agent_runner code (its git tree) of the source checkout `root`; None when it is not one."""
    if not (Path(root) / '.git').exists():
        return None
    try:
        return gitops.git('rev-parse', '-q', '--verify', 'HEAD:agent_runner', cwd=root, timeout=20).stdout.strip() or None
    except (OSError, sp.TimeoutExpired):
        return None


def code_on_main(root: str | Path) -> bool:
    """F149: `root` is on its main branch, with no edits to agent_runner's code under way."""
    try:
        on = gitops.git('symbolic-ref', '-q', '--short', 'HEAD', cwd=root, timeout=20).stdout.strip()
        if on not in ('main', 'master'):
            return False
        st = gitops.git('--no-optional-locks', 'status', '--porcelain', '-uno', '--',
                        'agent_runner', cwd=root, timeout=20)
        return not st.returncode and not st.stdout.strip()
    except (OSError, sp.TimeoutExpired):
        return False


def code_start(auto: bool) -> None:
    """F149: as the run starts: [run] auto_upgrade, and the code it runs."""
    AUTO_UPGRADE[0] = auto
    CODE.update(on=code_tree(Path(__file__).resolve().parents[1]), held=False, person='')
    RESTART_NEEDED[0] = ''


def code_restart(changed: bool, auto: bool, merging: bool, current: str, installed: str | None,
                 windows: bool = False) -> str:
    """F149: what changed code on main asks for now: 'restart', 'person' (only a person restarts the run on it:
    auto_upgrade is off, a breaking version, Windows), or '' (nothing, or not yet)."""
    if not changed:
        return ''
    if not auto or windows or not installed or breaking(current, installed):
        return 'person'
    return '' if merging else 'restart'


def watch_code(merging: bool) -> None:
    """F149, B227: the run loop's tick: restart a run from a source checkout once its code changed on main, at the
    first tick with no merge under way; else note for the run page that a person must (`RESTART_NEEDED`)."""
    from agent_runner import __version__
    root, installed = Path(__file__).resolve().parents[1], installed_version()
    tree = code_tree(root) if CODE['on'] else None
    CODE['held'] = False
    if tree and code_on_main(root):  # elsewhere, or edits under way: what a person was asked still holds
        changed = tree != CODE['on']
        what = code_restart(changed, AUTO_UPGRADE[0], merging, __version__, installed, plat.WINDOWS)
        CODE['held'] = changed and not what
        if what == 'restart':
            log(f"agent-runner's code changed on main; restarting on it, keeping {state_line()}")
            return restart_run()
        CODE['person'] = tree if what == 'person' else ''
    newer = installed if installed and installed != __version__ and (
        plat.WINDOWS or breaking(__version__, installed) or not AUTO_UPGRADE[0]) else ''
    RESTART_NEEDED[0] = '' if UPGRADED[0] and not plat.WINDOWS else '-'.join(x for x in (newer, CODE['person']) if x)


def ask_restart() -> None:
    """F97: the `restart` key: the settings that apply on the next run wait for it."""
    RESTART[0] = not plat.WINDOWS
    log('restarting between merges, to take the settings that wait for it; the running tasks keep going' if RESTART[0] else
        'restart: not on Windows; stop the run and start it again')


def restart_run() -> None:
    """Re-exec this run as it was started; the new process reads the settings again and adopts the sessions."""
    sys.stdout.flush()
    from agent_runner.settings_live import KEPT
    # what the keys set lives in this process: the new one takes it over (see `kept_keys`)
    os.environ['AGENT_RUNNER_KEEP'] = json.dumps({'slots': SLOTS, 'paused': PAUSED[0], 'power': POWER,
                                                  'stop': stopping(), 'forced': FORCED[0], **({'kept': KEPT} if KEPT else {})})
    os.execv(sys.executable, sys.orig_argv)  # run.lock's fd closes on exec; the new process takes it again


# --- the idle stop hook --------------------------------------------------------

DONE_IDLE = 5  # s a session whose `done` succeeded stays at its prompt: the next task starts that much sooner


def stop_hook(idle: int) -> int:
    """Stop hook for a session this runner started: end it once it has been idle for `idle` seconds.

    A finished agent otherwise sits at its prompt forever, and the loop never starts the next task. "Idle"
    means no new user or tool-result entry in the transcript, so typing into the pane keeps the session
    alive: you can take one over by hand. A session with a background task running gets a much longer
    grace (`AGENT_RUNNER_IDLE_BG`, 1800 s), because a background task normally ends and wakes it. Past the
    grace the waiter still leaves alone a session whose agent has a child process (its background command:
    a `done` queued behind other test runs can take longer than any grace), up to
    `AGENT_RUNNER_IDLE_MAX` (10800 s) after the stop.

    A usage limit is deliberately *not* idleness: Claude Code prints "continuing automatically at <reset>"
    and resumes by itself, so the waiter leaves such a session alone.
    """
    if not os.environ.get('AGENT_RUNNER'):
        return 0  # a hook file in a checkout also fires for a person's own session there: never end that one
    try:
        ev = json.load(sys.stdin)
    except Exception:
        return 0
    t = ev.get('transcript_path') or ev.get('transcriptPath')
    if not t or not os.path.exists(t):
        return 0
    if ev.get('hook_event_name', 'Stop') == 'Stop' and (said := full_message(t)):  # F177: the turn goes on with it
        print(json.dumps({'decision': 'block', 'reason': said}))
        return 0
    if idle < 0:  # a stream session: `run_stream` ends it
        return 0
    if ended():  # F102: the agent ran `finish` or `ask`: end it now
        idle = 0
    elif finished():  # `done` succeeded: nothing left to wait for, and its leftovers get no grace
        idle = min(idle, DONE_IDLE)
    elif ev.get('background_tasks'):
        idle = max(idle, int(os.environ.get('AGENT_RUNNER_IDLE_BG', 1800)))
    # POSIX: the hook's parent is the agent. Windows: the hook runs under Git Bash, whose pid is not the
    # agent's, so the pid comes from the marker the slot's shim keeps (run_session)
    pid = os.getppid()
    if plat.WINDOWS and (m := os.environ.get('AGENT_RUNNER_MARKER')):
        pid = marker_pid(Path(m)) or pid
    try:
        plat.spawn_detached([*runner_cmd(), 'run', '--stop-waiter', str(pid), t, str(_user_entries(t)), str(idle)])
    except Exception:
        pass
    return 0


def context_peak(t: str) -> int:
    """The biggest context, in tokens, of transcript file `t`'s own calls (as `usage` counts it); 0 unread. For
    the Stop hook, which runs with no run's config loaded."""
    peak = 0
    try:
        with open(t, encoding='utf-8', errors='replace') as f:
            for l in f:
                if '"usage"' not in l:
                    continue
                try:
                    d = json.loads(l)
                    u = d['message']['usage'] if d['type'] == 'assistant' and not d.get('isSidechain') else {}
                    peak = max(peak, sum(u.get(k) or 0 for k in ('input_tokens', 'cache_read_input_tokens',
                                                                  'cache_creation_input_tokens')))
                except (ValueError, KeyError, TypeError, AttributeError):
                    continue
    except OSError:
        pass
    return peak


def full_mark(sid: str, c) -> Path:
    """Left when session `sid` was told its context is full (F177): it is told once, resumed or not."""
    return c.notes(f'{sid}.full')


def full_message(t: str) -> str:
    """F177: what a slot's task session is told once, as a turn of its ends with its context past `[run]
    context_warn`; '' otherwise: not past it, told before, `done` or `finish` ran, no task, or any trouble."""
    if not os.environ.get('AGENT_RUNNER_SLOT') or finished():
        return ''
    try:
        from agent_runner import plan as P
        from agent_runner.brief import CONTEXT_FULL
        from agent_runner.config import cfg
        from agent_runner.tools import task_here
        c = cfg()
        warn = int(c.run.get('context_warn') or 0)
        mark = full_mark(Path(t).stem, c)
        if warn <= 0 or mark.exists() or (peak := context_peak(t) // 1000) <= warn or not (tid := task_here()) \
                or P.concept(tid) or P.release(tid):  # neither is split into parts
            return ''
        mark.write_text(f'{peak}\n', encoding='utf-8')  # before it is said: a mark that cannot be left says nothing
        return CONTEXT_FULL.format(tid=tid, peak=peak, warn=warn, runner=c.command)
    except (Exception, SystemExit):  # noqa: BLE001 - a warning never breaks the hook that ends sessions
        return ''


# a user message or a tool result
USER_ENTRY = re.compile(r'"type":"user"')


def _user_entries(t: str) -> int:
    try:
        with open(t, encoding='utf-8', errors='replace') as f:
            return sum(1 for l in f if USER_ENTRY.search(l))
    except OSError:
        return -1


WAITER_POLL = 60  # s between looks at a session whose background command is still running


def finished() -> bool:
    """This slot's `done` has succeeded (`finished_mark`), or its agent ran `finish` or `ask` (F102)."""
    return bool((m := finished_mark()) and m.exists()) or ended()


def _wait_on(pid: int, seconds: float) -> bool:
    """Sleep up to `seconds`, looking every WAITER_POLL s whether `pid` still runs. False (at once) once it
    is gone: a waiter for an ended session has nothing left to do, and must not linger for hours (B55)."""
    end = time.time() + seconds
    while plat.alive(pid):
        left = end - time.time()
        if left <= 0:
            return True
        time.sleep(min(left, WAITER_POLL))
    return False


def stop_waiter(pid: int, t: str, n: int, idle: int) -> int:
    until = time.time() + max(idle, int(os.environ.get('AGENT_RUNNER_IDLE_MAX', 10800)))
    if not _wait_on(pid, idle):
        return 0  # the session ended by itself during the grace
    while True:
        if not plat.alive(pid):
            return 0
        if _user_entries(t) != n:
            return 0  # the human typed, or a tool came back: the session is alive, leave it
        try:
            text = open(t, encoding='utf-8', errors='replace').read()
        except OSError:
            text = ''
        tail = text[text.rfind('continuing automatically'):] if 'continuing automatically' in text else ''
        if tail and '"tool_use"' not in tail:
            return 0  # waiting out a usage limit; Claude Code resumes it at the reset
        # a child is a command the agent still runs (a `done` that waited 30 min for a test slot was killed
        # with its session, and the work it was about to commit went with it): it ends and wakes the agent.
        # Once `done` has succeeded there is nothing left to protect: a leftover background command (a wait
        # loop that never ends) must not hold the slot for hours
        if not plat.children(pid) or time.time() >= until or finished():
            break
        if not _wait_on(pid, WAITER_POLL):
            return 0
    plat.terminate(pid)
    return 0
