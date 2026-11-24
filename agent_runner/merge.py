"""Merging a finished branch in the merge worktree: the turn lock's users, fix and repair sessions, the merge
gate, merges built ahead, `merge_batch`."""

from __future__ import annotations

import datetime as dt
import fnmatch
import hashlib
import json
import os
import re
import shlex
import signal
import subprocess as sp
import threading
import time
import uuid
from pathlib import Path

from contextlib import ExitStack

from agent_runner import pitch, plan as P, plat, plansync, stack
from agent_runner.brief import findings_globs, research_task
from agent_runner.done import DOCS_SKIP, PARTIAL, TESTED, docs_only, gate, gate_passed_on
from agent_runner.gitops import _net
from agent_runner.sched import agent_held, AgentHeld
from agent_runner.strays import drop_strays, new_empty
from agent_runner.state import C, clean, git, hook, LANDING, log, MERGE, note, plan_rel, plan_text, ROOT, SLOTS_DIR
from agent_runner.state import commit_plan, EV_LANDED, EV_LEFT, EV_PART
from agent_runner.slots import (backend, entries, env_vars, merge_env, MUX, slot_env, trim, worktree)
from agent_runner.join import joined, LANDED, merge_into, renumber_doubles, task_env, TASK_SID, WAITING
from agent_runner.land import (announce_release, BROKEN, flaky, land, land_tick, published, push_landed,
    reopen_landed, UNPUSHED)


def left_merging() -> set[str]:
    """The tasks whose fix or repair session or gate run an earlier run left going (`adopt_merge`)."""
    out = set()
    try:
        runs = [json.loads(C.notes('master.json').read_text(encoding='utf-8'))]
    except (OSError, ValueError):
        runs = []
    for s in runs + (gate_runs() if C.notes(GATES).is_dir() else []):
        if gate_alive(s) and Path(s.get('cwd', '')).name != 'merge2':
            out.add(s['tid'])
    return out


FIXER = """A merge of task/{tid} into {branch} is half-done in this checkout and git could not finish it \
by itself. Finish it. Nobody will answer questions: decide, and say what you decided.

Conflicted files:
{files}

What this is: an unattended run gave several agents a task each, on their own branch, and is merging them \
one at a time. The runner joins conflicts in record-per-line files itself; this one needs reading, which is \
why you are here instead of a human.

1. `git status` and `git diff` to see it, and `git log {branch}..task/{tid}` for what the task did. Resolve \
every conflict so that **both sides' intent survives** — two agents each did work somebody wanted, and a \
resolution that silently drops one of them is the worst outcome available. Watch for one side being simply \
older: a branch that predates a paragraph on {branch} must not revert it. Where they genuinely cannot both \
hold, keep the one that matches {branch}'s current direction and say so.
2. Change nothing the merge did not touch. You are not reviewing the code and you are not doing task \
{tid}'s work: a conflict is all that is in front of you. Never hand-edit a task checkbox; if a side ticked \
or blocked a task by hand, keep the plan tool's form of it.
{build_step}3. Then `git commit --no-edit` to land the merge, and stop. Leave the test suite to the runner: it \
runs it as soon as you are done. That commit is your only git change: no push, no other merge, rebase or delete, no \
`git stash`, and the other worktrees under {slots_dir} left as they are.
4. If it cannot be resolved honestly — the two sides contradict each other and picking needs a human — run \
`git merge --abort` and say why in one line. That is a real answer, not a failure.

What happened on earlier merges in this run (the ledger's tail):
{history}
"""


BUILD_STEP = """3a. Before you commit, run `{build}` (a build, not the tests). Git merged every file it did not stop on \
without reading it, so the two sides can clash there too: a function or item both added under one name, a \
caller of something the other side renamed or removed. Fix what the build reports that the merge caused, \
in the fewest lines and keeping both sides, and build again until it passes. An error {branch} already has \
is not yours: leave it.
"""

REPAIR = """[[The merge of task/{tid} into {branch} is|The merges of {tasks} into {branch} are]] committed in this \
checkout[[ (as {merge})|, one after another on top of {base}]], and the test gate fails on [[it. task/{tid}|the \
result. Each branch]] may or may not have passed the gate on its own (where a run leaves the testing to the \
gate, it never ran it), so the cause is [[its own change, or |]]a clash between [[the two sides|them]] that git \
merged without a conflict: an item [[both|two of them]] added under one name, a caller of something [[the other \
side|another]] renamed or removed, a test that checks what [[the other side|another]] changed on purpose. Repair \
it[[|, so all of them land after one more gate run]]. Nobody will answer questions: decide, and say what you \
decided.

The gate's output ends with this (all of it is in {log}):

{tail}

1. [[`git diff {merge}^1 {merge} --stat` (what task/{tid} brought) and `git diff {merge}^2 {merge} --stat` \
(what {branch} brought) show the two sides|`git log --first-parent --format='%h %s' {base}..HEAD` lists the \
merges; `git diff <merge>^1 <merge> --stat` shows what each one brought]]. Find where they meet.
2. Fix the clash in the fewest lines, so that **[[both sides'|every branch's]] intent survives**. Change nothing \
the clash does not need. You are not reviewing the code and you are not redoing [[task {tid}|any task]]. A test \
one [[side wrote for behaviour the other side|branch wrote for behaviour another]] changed on purpose is updated \
to the merged behaviour, and you say so.
3. {check}Then commit the fix on top[[ of the merge|]]: `git add` what you changed and `git commit -m "{tid}: \
repair the [[merge|batch merge of {ids}]] into {branch}: <what clashed>"`. That commit is your only git \
change: the merge[[|s]] stay[[s|]] as committed (no amend or reset), no push, no other merge, rebase or delete, no \
`git stash`, and the other worktrees under {slots_dir} left as they are. The runner runs the whole gate again \
when you are done.
4. If you cannot fix it honestly (the failure is {branch}'s own, [[the two sides contradict|one branch is broken by \
itself, two branches contradict]] each other and picking needs a human), commit nothing and say why in one line. [[|The runner then merges each branch on its own. ]]That is a real answer.
5. If it is a flaky test (it passes when you rerun it, and nothing [[the merge|these merges]] changed touches what it checks), commit nothing and make your last line `FLAKE: <test name>[, <test name>…]`: one name per test, commas only between tests, and a name that has spaces or commas in double quotes (`FLAKE: LogPanelTest, "the watch, restarted"`). The runner runs the gate once more and files the flake to be fixed.
"""  # [[one merge|a batch]]: `repair_prompt` keeps one side


OWN = """This is a copy of your own session from task {tid}, picked up again by the runner: task/{tid} is \
finished and merged into {branch}, and the merge fails the test gate. You know the change, so you repair it. \
You are in another checkout now, {cwd}: work only there. Your old worktree belongs to another task, and the paths \
you used before are under another folder.

"""  # put before a one-task REPAIR when the repair session is a copy of the task's own (`fork_flags`)


def repair_prompt(batch: bool, **vals) -> str:
    text = re.sub(r'\[\[(.*?)\|(.*?)\]\]', lambda m: m.group(2 if batch else 1), REPAIR, flags=re.S)
    return text.format(**vals)


def last_words(sid: str) -> str:
    """The last thing session `sid` said, for fixer.log: why it committed what it did, or nothing."""
    said = ''
    for d in entries(sid):
        if d.get('type') == 'assistant':
            text = [c.get('text', '') for c in d.get('message', {}).get('content', []) if isinstance(c, dict)]
            said = '\n'.join(t for t in text if t) or said
    return said.strip()


def fix_session(prompt: str, cwd: Path, fh, keep: dict | None = None, fork: str = '') -> int:
    """Run one fix or repair session in `cwd` to its end; its exit code. Raises what `sp.run` raises for a
    missing agent or a timeout.

    It is `-p`, its output in `fh` (C26: no longer a session in a window of its own; `keep`
    is what it was started on, kept for the callers, and `adopt_merge` still reads a master.json an older
    run left). With `fork` (a session id), it starts as a copy of that session (`fork_flags`), knowing what
    it did.
    """
    timeout = C.run['fix_timeout']
    more = backend().fork_flags(fork) if fork else []
    env = {**os.environ, **env_vars(slot_env(None))}
    return sp.run(fix_cmd(prompt) + more, cwd=str(cwd), stdout=fh, stderr=sp.STDOUT, stdin=sp.DEVNULL,
                  env=env, timeout=timeout).returncode


def wait_session(pid: int, until: float) -> bool:
    """Wait for the session `pid` to end: False when it ran to `until` and was ended."""
    while plat.alive(pid):
        if time.time() >= until:
            for p in [*plat.children(pid), pid]:
                plat.terminate(p)
            return False
        time.sleep(5)
    return True


HELD = 'refs/agent-runner/held/'  # + <ID>/<start>[-<ref>]: what a fix or repair session made from there


def held(tid: str, start: str, ref: str = '') -> str:
    return f'{HELD}{tid}/{start}' + (f'-{ref}' if ref else '')


def kept(tid: str, start: str, ref: str, d: Path, kind: str) -> bool:
    """A fix (`ref` merged onto `start`) or repair (commits on `start`) session made the same thing in an
    earlier run, or before a rebuild: `d` is moved to what it made, and no session runs again."""
    if not (h := git('rev-parse', '-q', '--verify', held(tid, start, ref)).stdout.strip()):
        return False
    git('merge', '--abort', cwd=d)
    clean(d, h)
    log(f'{tid}: reused what the {kind} session made of this merge before ({h[:12]})')
    return True


def keep_made(s: dict, d: Path) -> bool:
    """Record what the session `s` (master.json) made in `d`, when it made what its kind should: a fix commits
    the merge of `ref` onto `start`, a repair commits on top of `start` and leaves nothing uncommitted."""
    head = git('rev-parse', 'HEAD', cwd=d).stdout.strip()
    if s['kind'] == 'fix':
        ok = git('rev-parse', '-q', '--verify', 'MERGE_HEAD', cwd=d).returncode != 0 and \
            git('rev-parse', '-q', '--verify', 'HEAD^2', cwd=d).stdout.strip() == s['ref'] and \
            git('rev-parse', '-q', '--verify', 'HEAD^1', cwd=d).stdout.strip() == s['start']
    else:
        ok = head != s['start'] and not git('merge-base', '--is-ancestor', s['start'], head, cwd=d).returncode and \
            not git('status', '--porcelain', '--untracked-files=no', cwd=d).stdout.strip()
    if ok:
        git('update-ref', held(s['tid'], s['start'], s.get('ref', '')), head)
    return ok


def adopt_merge(d: Path) -> None:
    """Before a merge resets the merge worktree `d`: wait out what an earlier run left going in it, a fix or
    repair session in the master window or a gate run, and keep what they made (`held`, `GATES`). The merge
    is then built again as it was, and reuses them instead of doing them again."""
    m = C.notes('master.json')
    try:
        s = json.loads(m.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        s = None
    if s and Path(s.get('cwd', '')) == d:
        if plat.alive(s['pid']) and MUX.session_id(s['pid']) == s['sid']:
            log(f'{s["tid"]}: adopted the {s["kind"]} session an earlier run left going in the master window')
            if not wait_session(s['pid'], s['until']):
                log(f'{s["tid"]}: the adopted {s["kind"]} session ran past its time limit; ended')
        if keep_made(s, d):
            log(f'{s["tid"]}: kept what the {s["kind"]} session made ({git("rev-parse", "--short", "HEAD", cwd=d).stdout.strip()})')
    m.unlink(missing_ok=True)
    for s in sorted(gate_runs(), key=lambda s: Path(s.get('cwd', '')) != d):  # the merge's, then merge2's
        batch = s.get('head') and git('cat-file', '-e', f'{s["head"]}^{{commit}}').returncode == 0 and \
            {'base': s['base'], 'tids': s['tids'], 'merged': s['head']}
        if Path(s.get('cwd', '')) != d:
            if batch:  # built ahead (merge2): its turn reuses it, and `merge_gate` waits for its gate by tree
                AHEADS.append(batch)
            continue
        if gate_alive(s):
            log(f'{s["tid"]}: adopted the gate run an earlier run left going on the merge; waiting for it')
        r = wait_gate(s)
        what = ' and '.join(s.get('tids') or [s['tid']])
        if r is None:
            log(f'{s["tid"]}: the adopted gate on {what} left no exit code; the merge is built and tested again')
            continue
        log(f'{s["tid"]}: the adopted gate on {what} ' + ('passed' if not r[0] else f'failed (exit {r[0]})'))
        if batch:
            AHEADS.insert(0, batch)  # its turn reuses that merge, as it was gated
            key = gate_key(d, s['head'])  # under this version's key too
            if r[0]:
                ADOPTED[key] = r  # the failure is that merge's: retests and repairs go from it, not a new gate
            else:
                (C.notes(GATES) / f'{key}.pass').touch()


ADOPTED: dict[str, tuple[int, str]] = {}  # a failed gate an earlier run left, by key: `merge_gate` answers it once


def gate_alive(s: dict) -> bool:
    """A gate (or session) record's process is still the one it names: its pid is alive and, where the OS
    tells (`plat.started`), started when the record says. After a reboot a days-old record's pid can be
    anyone's. A record without a start time (an older runner's) goes by the pid alone."""
    return plat.alive(s.get('pid')) and ('start' not in s or s['start'] == plat.started(s['pid']))


def end_group(pid: int) -> None:
    """SIGTERM a gate's process group; gone already (or never a group leader) is fine."""
    try:
        os.killpg(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass


def gate_runs() -> list[dict]:
    """The merge gates running, or left by a run that ended: `<notes>/gates/<key>.json`."""
    out = []
    for f in sorted(C.notes(GATES).glob('*.json')) if C.notes(GATES).is_dir() else []:
        try:
            out.append({**json.loads(f.read_text(encoding='utf-8')), 'rec': str(f)})
        except (OSError, ValueError):
            f.unlink(missing_ok=True)
    return out


def wait_gate(s: dict) -> tuple[int, str] | None:
    """Wait for the gate run `s` (another thread's or an earlier run's) to end: `gate_done`'s answer."""
    while gate_alive(s) and time.time() < s['until']:
        time.sleep(5)
    if gate_alive(s):
        end_group(s['pid'])
    r = gate_done(s)
    Path(s['rec']).unlink(missing_ok=True)
    return r


AHEAD_BUSY = threading.Lock()  # held while build_ahead uses merge2
AHEAD_POLL = 30  # seconds between looks for tasks that finished during a gate
AHEADS: list[dict] = []  # merges built and gated already, for later turns: {'base', 'tids', 'merged'}
# (`build_ahead`, or adopted from an earlier run, `adopt_merge`); each turn takes the one on its base


UNDER: list[dict] = []  # the merge under test, until it lands or fails: one {'on': its commit, 'tids'}, or none


def under_way() -> list[dict]:
    """F198: the merges a task may start on, as {'on', 'tids': every task they hold that has not landed}: the one
    under test, then those built ahead on it whose own gate has not failed."""
    return [m for u in UNDER[:] for m in [u, *({'on': a['merged'], 'tids': [*u['tids'], *a['tids']]}
                                               for a in AHEADS[:] if a['base'] == u['on'] and not a.get('failed'))]]


def build_ahead(branch: str, base: str, done: threading.Event, taken: set[str]) -> None:
    """While the merge `base` is in its gate: the tasks that finished since, merged on top of it in a second
    worktree (merge2) and tested there beside it. When `base` lands, their turn reuses that merge, and with
    it the gate run already passed or under way (`merge_gate` goes by tree), instead of a gate from the start.
    A conflict a join cannot do is left for that task's turn (one fix session at a time)."""
    while not done.wait(AHEAD_POLL):
        if ahead_gate_running():  # the gate `base` waits on is merge2's own: checking out there swaps its tree
            continue
        cands = sorted(WAITING - taken - set(LANDED) - ALONE - criticals(branch) - releases(WAITING))
        if cands := [x for x in cands if not research_unasked(x, branch)]:
            break
    else:
        return
    if C.run['batch_max']:
        cands = cands[:C.run['batch_max']]
    with AHEAD_BUSY:
        if not ahead_gate_running():
            _build_ahead(branch, base, cands)


def ahead_gate_running() -> bool:
    """A gate still running in merge2 that no ahead thread holds: one built ahead under an earlier run, which a
    restart adopted and a turn now waits on. A merge built ahead checks out over it, and the gate builds and
    tests a tree that is not the one it reports on (MD168b's gate, 11-17, ran P347's code)."""
    return any(Path(s.get('cwd', '')).name == 'merge2' and gate_alive(s) for s in gate_runs())


def _build_ahead(branch: str, base: str, cands: list[str]) -> None:
    d = worktree('merge2', branch)
    git('merge', '--abort', cwd=d)
    clean(d)
    git('checkout', '-q', '--detach', base, cwd=d)
    tids = []
    for t in cands:
        ref = renumber_doubles(f'task/{t}', 'HEAD', t, d)
        if (files := merge_into(d, ref, merge_message(t, ref), t)) is None or files and not joined(files, t, d):
            git('merge', '--abort', cwd=d)
            continue
        tids.append(t)
    if not tids:
        return
    if not C.plan_external:
        carry_notes(base, d)
        P.archive(d / plan_rel('TODO.md'), d / plan_rel('DONE.md'))
    plan_files = [plan_rel('TODO.md'), plan_rel('DONE.md')]
    if git('status', '--porcelain', '--', *plan_files, cwd=d).stdout.strip():
        git('commit', '-qm', f'{tids[0]}: archive ticked tasks', '--', *plan_files, cwd=d)
    batch = {'base': base, 'tids': tids, 'merged': git('rev-parse', 'HEAD', cwd=d).stdout.strip()}
    AHEADS.append(batch)
    log(f'{", ".join(tids)}: merged ahead on the merge under test; its gate runs beside that one')
    key = gate_key(d)
    rc, text = merge_gate(tids[0], d, merge_env(), {'base': base, 'tids': tids})
    log(f'{", ".join(tids)}: the gate on the merge built ahead ' + ('passed' if not rc else
        f'failed (exit {rc}; {C.notes(GATES) / key}.failed)'))
    if rc:
        batch['failed'] = True
    if rc and batch in AHEADS:  # its turn has not come yet: it goes from this result, not a gate of its own
        ADOPTED[key] = rc, text


def reusable(a: dict, tid: str, base: str) -> bool:
    """Whether the merge `a`, built and gated already, is tid's turn's merge on the branch at `base`: built on
    it (or on a commit the branch moved on from by untested files only), with tid and riders still waiting."""
    return tid in a['tids'] and set(a['tids']) - {tid} <= WAITING - set(LANDED) and (
        a['base'] == base or git('merge-base', '--is-ancestor', a['base'], base).returncode == 0
        and all(map(untestable, git('diff', '--name-only', a['base'], base).stdout.split())))


def drop_ahead() -> None:
    """The batches built ahead are on a merge that will not land as it is: their gates are stopped, and their
    records gone with them (one left behind reads as a gate still to wait on)."""
    AHEADS.clear()
    for s in gate_runs():
        if Path(s.get('cwd', '')).name == 'merge2':
            if gate_alive(s):
                end_group(s['pid'])
            Path(s['rec']).unlink(missing_ok=True)


GATES = 'gates'  # <notes>/gates/<key>.pass: a tree the merge gate passed on (`merge_gate`)


def gate_key(d: Path, rev: str = 'HEAD') -> str:
    """The merge in `d`'s tree, with the gate command: a pass is one of this command on this tree. Files the
    gate does not test (`[run] untested`: the plan, notes) are left out, so a plan commit or a ticked task
    does not make a passed merge new."""
    files = git('ls-tree', '-r', rev, cwd=d).stdout.splitlines()
    tree = hashlib.sha1('\n'.join(f for f in files if not untestable(f.split('\t', 1)[-1])).encode()).hexdigest()
    return f'{tree}-{uuid.uuid5(uuid.NAMESPACE_OID, C.run["test"]).hex[:12]}'


GATE_DONE = threading.Lock()


def gate_done(s: dict) -> tuple[int, str] | None:
    """The finished gate run `s` (gates/<key>.json): (exit code, output), its pass kept; None when it never
    got to the end (ended, or killed with the machine), or another thread read it first."""
    with GATE_DONE:  # the ahead thread and the turn that reuses its merge both wait on merge2's gate
        if s['out'] not in GATE_RESULTS:
            GATE_RESULTS[s['out']] = _gate_done(s)
        return GATE_RESULTS[s['out']]


GATE_RESULTS: dict[str, tuple[int, str] | None] = {}  # what each gate run ended with, read once from its files


def _gate_done(s: dict) -> tuple[int, str] | None:
    out, rc = Path(s['out']), Path(s['out']).with_suffix('.rc')
    if out.with_suffix('.pass').exists():
        return 0, ''
    try:
        code, text = int(rc.read_text().strip()), out.read_text(encoding='utf-8', errors='replace').strip()
    except (OSError, ValueError):
        return None
    finally:
        rc.unlink(missing_ok=True)
    if not code:
        out.with_suffix('.pass').write_text(s['tid'] + '\n', encoding='utf-8')
        out.unlink(missing_ok=True)
        if s.get('full', True):
            (out.parent / FULL_PASS).touch()
    else:  # kept a week, for whoever looks into why it failed
        out.replace(out.with_suffix('.failed'))
    return code, text


FULL_PASS = 'full.last'  # <notes>/gates/full.last: touched when a whole `test` passes on a merge


def gate_cmd(base: str) -> tuple[str, bool]:
    """The command a merge's gate runs, and whether it is the whole `test`. With `[run] test_since`, only what
    changed since `base` is tested: the shared branch only moves on a passed gate, and the merge built ahead
    is on a merge whose own gate is still running (a failure there drops it). The whole `test` runs anyway
    once none has passed for `full_every_hours`, for what a selection misses."""
    since, hours = C.run['test_since'], C.run['full_every_hours']
    last = C.notes(GATES) / FULL_PASS
    if not since or not base or hours and (not last.exists() or last.stat().st_mtime < time.time() - hours * 3600):
        return C.run['test'], True
    return since.replace('{base}', base), False


def merge_gate(tid: str, d: Path, env: dict, batch: dict | None = None) -> tuple[int, str]:
    """`gate(d, full=True)` for a merge, as a run of its own that outlives the runner (a restart adopts it:
    `adopt_merge`), and one a tree it already passed on skips: a gate can take an hour."""
    if not (cmd := C.run['test']):
        return 0, ''
    if plat.WINDOWS:
        return gate(d, full=True, env=env)
    gates = C.notes(GATES)
    gates.mkdir(exist_ok=True)
    for f in gates.iterdir():
        if f.stat().st_mtime < time.time() - 7 * 86400:
            f.unlink(missing_ok=True)
    key = gate_key(d)
    if (gates / f'{key}.pass').exists():
        log(f'{tid}: the gate already passed on this exact merge; not run again')
        return 0, ''
    if r := ADOPTED.pop(key, None):
        log(f'{tid}: the gate failed on this exact merge under an earlier run; going from that result')
        return r
    rec = gates / f'{key}.json'
    for s in gate_runs():
        if s['rec'] == str(rec):
            if running := gate_alive(s):
                log(f'{tid}: a gate on this exact merge is already running (built ahead, or left by an earlier '
                    f'run); waiting for it')
            if (r := wait_gate(s)) is not None:
                if not running:
                    log(f'{tid}: the gate on this exact merge ended with exit {r[0]}; that result counts')
                return r
    out = gates / f'{key}.out'
    timeout = C.run['command_timeout']
    cmd, full = gate_cmd((batch or {}).get('base', ''))
    if not full:
        log(f'{tid}: the gate tests what changed since {batch["base"][:9]} ([run] test_since)')
    out.with_suffix('.rc').unlink(missing_ok=True)  # a gate killed before its end must not read as an old one's
    with GATE_DONE:
        GATE_RESULTS.pop(str(out), None)
    with open(out, 'w', encoding='utf-8') as fh:
        p = sp.Popen(f'({cmd}\n); echo $? > {shlex.quote(str(out.with_suffix(".rc")))}', shell=True, cwd=str(d),
                     env=env, stdout=fh, stderr=sp.STDOUT, stdin=sp.DEVNULL, start_new_session=True)
    s = {'tid': tid, 'pid': p.pid, 'start': plat.started(p.pid), 'out': str(out), 'until': time.time() + timeout, 'cwd': str(d), 'rec': str(rec),
         'full': full, **(batch or {}), 'head': git('rev-parse', 'HEAD', cwd=d).stdout.strip()}
    rec.write_text(json.dumps(s), encoding='utf-8')
    try:
        p.wait(timeout=timeout)
    except sp.TimeoutExpired:
        os.killpg(p.pid, signal.SIGTERM)
        p.wait()
        gate_done(s)
        return 124, f'`{cmd}` ran past [run] command_timeout ({timeout}s): counted as failing'
    finally:
        rec.unlink(missing_ok=True)
    return gate_done(s) or (p.returncode or 1, f'`{cmd}` left no exit code')


def fixer(head: str, prompt: str, cwd: Path, kind: str, to: str, keep: dict | None = None,
          fork: str = '') -> tuple[int | None, str]:
    """`fix_session` under a `head` line in fixer.log: (its exit code, ''), or why it did not run to its end
    (code 0 when there is no agent command, None when it timed out). B764c: AgentHeld while [run] agent is wrong."""
    if bad := agent_held():
        raise AgentHeld(bad)
    with open(C.notes('fixer.log'), 'a', encoding='utf-8') as fh:
        fh.write(f'\n=== {dt.datetime.now().isoformat(timespec="seconds")} {head}\n')
        fh.flush()
        try:
            return fix_session(prompt, cwd, fh, keep, fork), ''
        except FileNotFoundError:
            return 0, f'no agent command to {to} with ([run] agent = {C.run["agent"]!r})'
        except sp.TimeoutExpired:
            return None, f'the {kind} session ran past {C.run["fix_timeout"]}s'


def fix_cmd(prompt: str) -> list[str]:
    """A fix session: one prompt, one answer, no session to keep — `-p`, so nothing types into a pane."""
    return backend().fix_cmd(prompt)


def fix_merge(tid: str, branch: str, files: list[str], cwd: Path, start: str = '', ref: str = '') -> str | None:
    """Give a conflict the join cannot do to a fresh agent session, in `cwd`. None when it landed.

    One session per merge, run to completion while the caller waits: ahead of the merge lock (`fix_ahead`),
    in a fix worktree of its own (fix1…), or under it in the merge worktree on a last try. Each one starts with an empty context and the
    ledger's tail, so the twentieth costs what the first did. (This replaced a long-lived
    "master" session: see `fix_session`.)

    Never fatal. A fixer that fails, times out, aborts or is not installed leaves the merge for the caller
    to abort, and the task is left for a human.
    """
    if not C.run['fix_merges']:
        return 'conflicts a join cannot resolve, and [run] fix_merges is off'
    led = C.notes('ledger.md')
    history = ''.join(led.read_text(encoding='utf-8').splitlines(True)[-12:]) if led.exists() else ''
    prompt = FIXER.format(tid=tid, branch=branch, files='\n'.join(f'  {f}' for f in files),
                          slots_dir=SLOTS_DIR, history=history.strip() or '(nothing yet: this is the first)',
                          build_step=BUILD_STEP.format(build=C.run['build'], branch=branch) if C.run['build'] else '')
    logfile = C.notes('fixer.log')
    log(f'{tid}: conflicts in {", ".join(files)} need reading — handing them to a fix session')
    keep = {'kind': 'fix', 'tid': tid, 'start': start, 'ref': ref, 'cwd': str(cwd)} if start else None
    code, why = fixer(f'{tid} {", ".join(files)}', prompt, cwd, 'fix', 'fix the conflicts', keep)
    if why:
        if code is None:
            note(f'{tid}: the fix session timed out after {C.run["fix_timeout"]}s')
        return why
    if git('rev-parse', '--verify', '-q', 'MERGE_HEAD', cwd=cwd).returncode == 0:
        return f'the fix session did not finish the merge (exit {code}); see {logfile}'
    if git('merge-base', '--is-ancestor', f'task/{tid}', 'HEAD', cwd=cwd).returncode:
        return f'the fix session aborted the merge; its reason is in {logfile}'
    if keep:
        keep_made(keep, cwd)
    note(f'{tid}: conflicts in {", ".join(files)} resolved by a fix session')
    log(f'{tid}: the fix session resolved {", ".join(files)} and committed the merge')
    return None


def repair_merge(tid: str, branch: str, cwd: Path, riders: list[str] = (), base: str = '') -> str | None:
    """Give a committed merge that fails the gate to a fresh agent session in `cwd`. None when it committed
    a repair on top of the merge (the caller runs the gate again), else why not. With `riders`, it is the
    whole batch (task/<tid> and theirs, merged on `base` one after another) that the session repairs.

    Like `fix_merge`: one session, under the merge lock, never fatal. It reads the gate's full output in
    `<notes>/merge-gate.log`, which `tested` wrote; the prompt carries the tail.
    """
    if not C.run['repair_merges']:
        return 'off ([run] repair_merges)'
    gate_log = C.notes('merge-gate.log')
    out = gate_log.read_text(encoding='utf-8') if gate_log.exists() else '(no gate output kept)'
    merge = git('log', '-1', '--merges', '--first-parent', '--format=%h', cwd=cwd).stdout.strip()
    tail = '\n'.join('    ' + l for l in out.splitlines()[-60:])
    r = C.run
    check = (f'Check it with `{r["build"]}` and, if the gate names failing tests, the gate for just those '
             f'({r["retest"] or r["test"]}). ' if r['build'] else
             f'Check it with the failing tests alone if you can; not the whole gate (`{r["test"]}`). ')
    ids = ', '.join([tid, *riders])
    own = ''
    if riders:
        prompt = repair_prompt(True, tid=tid, branch=branch, log=gate_log, tail=tail, check=check, slots_dir=SLOTS_DIR,
                               base=base[:12], ids=ids, tasks=', '.join(f'task/{t}' for t in [tid, *riders]))
        log(f'{tid}: the batch ({ids}) fails the gate — handing it to a repair session')
    else:
        prompt = repair_prompt(False, tid=tid, branch=branch, log=gate_log, tail=tail, check=check, slots_dir=SLOTS_DIR,
                               merge=merge)
        if (own := TASK_SID.get(tid, '')) and backend().fork_flags(own):
            prompt = OWN.format(tid=tid, branch=branch, cwd=cwd) + prompt
            log(f'{tid}: the merge fails the gate — handing it back to the task\'s own session (a copy of {own})')
        else:
            own = ''
            log(f'{tid}: the merge fails the gate — handing it to a repair session')
    before = git('rev-parse', 'HEAD', cwd=cwd).stdout.strip()
    if kept(tid, before, '', cwd, 'repair'):
        return None
    logfile = C.notes('fixer.log')
    keep = {'kind': 'repair', 'tid': tid, 'start': before, 'cwd': str(cwd)}
    if why := fixer(f'{ids} repair (gate failed)', prompt, cwd, 'repair', 'repair it', keep, own)[1]:
        return why
    head = git('rev-parse', 'HEAD', cwd=cwd).stdout.strip()
    if head == before:
        if names := flake_said(logfile):
            return FLAKE + ', '.join(f'`{n}`' for n in names)  # quoted: a name may hold a comma
        return f'the repair session committed nothing; its reason is in {logfile}'
    if git('merge-base', '--is-ancestor', before, head, cwd=cwd).returncode:
        return f'the repair session rewrote the merge instead of committing on top; see {logfile}'
    if git('status', '--porcelain', '--untracked-files=no', cwd=cwd).stdout.strip():
        return f'the repair session left edits uncommitted; see {logfile}'
    keep_made(keep, cwd)
    log(f'{tid}: the repair session committed {git("rev-list", "--count", f"{before}..{head}", cwd=cwd).stdout.strip()} '
        f'fix(es) on the merge: {git("log", "-1", "--format=%s", cwd=cwd).stdout.strip()[:200]}')
    return None


def untestable(f: str) -> bool:
    """A change the test gate cannot see (`[run] untested`; the last glob that matches decides, `!glob` takes
    a file back). A merge that differs from what the branch tested only in these is not retested."""
    hit = False
    for g in C.run['untested']:
        if fnmatch.fnmatch(f, g.lstrip('!')):
            hit = not g.startswith('!')
    return hit


def gated(tid: str) -> bool:
    """task/<tid> is what `done`'s gate passed on: the tree its tested ref records."""
    tree = gate_passed_on(tid, ROOT)
    return bool(tree) and tree == git('rev-parse', '-q', '--verify', f'task/{tid}^{{tree}}').stdout.strip()


def tested(tid: str, d: Path, base: str, tids: list[str] | None = None) -> str | None:
    """Run the gate on the merge checked out in `d`: None when it passes, else why.

    With `[run] failures` and `retest`, a failure gets two more looks before it counts: rerun alone (a test
    that timed out under the other slots' load passes then), and rerun on `base`, the branch it merges into
    (one that already fails there the same way is not this task's doing, so it merges anyway, and says so).
    That one is the shared branch's own failure, though, so a critical task is filed to fix it (`file_flaky`);
    and when the whole `test` found it (`[run] test_since`'s daily run), it counts as that day's whole run:
    the failure is filed, and every later merge running the whole `test` again only to find it again would
    undo what `test_since` saves.
    """
    env = merge_env()
    full = gate_cmd(base)[1]
    rc, out = merge_gate(tid, d, env, {'base': base, 'tids': tids or [tid]})
    if not rc:
        if rx := C.run['flaky']:  # the gate's own rerun of a load flake passed: still a test to fix
            flaky(tid, [n for g in re.findall(rx, out, re.M) for n in re.split(r'[,\s]+', g) if n])
        return None
    C.notes('merge-gate.log').write_text(out + '\n', encoding='utf-8')  # for a repair session
    if rc in (130, -2):  # the run's Ctrl-C reached the gate: the main thread exits the process within moments
        threading.Event().wait(5)  # still here, so it was not the run's: a gate that exits 130 is a failure
    why = 'the tests fail after the merge: ' + ' / '.join(out.splitlines()[-4:])[:400]
    rx, cmd = C.run['failures'], C.run['retest']
    if not (rx and cmd and (names := sorted(set(re.findall(rx, out, re.M))))):
        return why
    FAILED[tid] = names  # for `blame`, if this is a batch that fails
    cmd = cmd.replace('{names}', ' '.join(map(plat.quote, names)))

    def retest() -> tuple[int | None, str]:
        return hook(f'{tid}: the retest of {", ".join(names)} (counted as failing)', cmd, d, env)

    if retest()[0] == 0:
        log(f'{tid}: {", ".join(names)} failed, then passed alone (load); counted as passing')
        flaky(tid, names)
        return None
    head = git('rev-parse', 'HEAD', cwd=d).stdout.strip()
    # the gate may have left files behind, and a checkout that refuses would rerun the tests on the merge
    clean(d)
    if (co := git('checkout', '-q', '--detach', base, cwd=d)).returncode:
        log(f'{tid}: could not check out {base[:12]} to rerun {", ".join(names)} there: {co.stderr.strip()[:200]}')
        return why
    try:
        rc, said = retest()
    finally:
        clean(d)
        git('checkout', '-q', '--detach', head, cwd=d)
    # ponytail: name-level match; a branch that breaks an already-failing test some other way slips through
    old = set(re.findall(rx, said, re.M)) & set(names) if rc else set()
    for n in old:
        BROKEN.setdefault(n, (tid, base, full and bool(C.run['test_since'])))
    if old >= set(names):
        log(f'{tid}: {", ".join(names)} already fail without it; merged anyway')
        if full and C.run['test_since']:
            (C.notes(GATES) / FULL_PASS).touch()
            log(f'{tid}: the whole test ran and found only those; counted as the day\'s whole run')
        return None
    if old:  # only the new failures count against it, or `blame` finds every task of a batch "failing" the old
        FAILED[tid] = [n for n in names if n not in old]
        log(f'{tid}: {", ".join(sorted(old))} already fail without it; only {", ".join(FAILED[tid])} count against it')
    return why


def suspect(base: str, merged: str) -> str:
    """The first line a merge added to TODO.md or DONE.md that matches `[run] suspect`, else ''.

    For blocks a project knows to distrust: a session in a run that can drive the emulator itself saying
    "needs a human at the emulator" is one. The ledger flags it for review.
    """
    if not (pat := C.run['suspect']):
        return ''
    rx = re.compile(pat, re.I)
    diff = git('diff', base, merged, '--', plan_rel('TODO.md'), plan_rel('DONE.md')).stdout.splitlines()
    gone = [l for l in diff if l.startswith('-') and not l.startswith('---')]
    # a line edited elsewhere (its files filled in, a note added) keeps its old block: that is not a new one
    return next((l[1:].strip()[:200] for l in diff if l.startswith('+') and not l.startswith('+++') and
                 (m := rx.search(l)) and not any(m.group(0) in g for g in gone)), '')
ALONE: set[str] = set()  # tasks `blame` found breaking a batch: they merge in a turn of their own
FAILED: dict[str, list[str]] = {}  # the tests `tested` last saw fail on a task's merge, by the task
def blame(tids: list[str], d: Path, base: str, names: list[str]) -> list[str]:
    """The task of a batch whose gate failed `names` that fails them by itself, found by halving: half the batch
    merged on `base` and `[run] retest` of just those; the half that fails is halved again, or, when it passes,
    the other half is. So a batch of 10 costs about 4 retests, not 10. Only a task seen failing alone is
    blamed; a second culprit in the half not searched stays in the batch, whose next gate finds it. [] when
    none fails alone (a clash between them) or there is no retest. Leaves `d` clean, detached at `base`."""
    cmd = C.run['retest'].replace('{names}', ' '.join(map(plat.quote, names)))
    env = merge_env()

    def fails(group: list[str]) -> bool | None:
        """Whether `group` merged on the base fails `names`; None when it will not merge there."""
        git('merge', '--abort', cwd=d)
        clean(d)
        git('checkout', '-q', '--detach', base, cwd=d)
        for t in group:
            if (files := merge_into(d, fixed(t), f'Merge task/{t} alone', t)) is None or files and not joined(files, t, d):
                return None
        rc, said = hook(f'blame: the retest of {", ".join(group)}', cmd, d, env)
        if rc is None:
            return None
        return bool(rc and set(re.findall(C.run['failures'], said, re.M)) & set(names))

    def search(group: list[str], failing: bool) -> list[str]:
        if len(group) == 1:
            return group if failing or fails(group) else []
        half, rest = group[:len(group) // 2], group[len(group) // 2:]
        if (f := fails(half)) is None:  # cannot build the half: each of the group alone
            return next(([t] for t in group if fails([t])), [])
        return search(half, True) if f else search(rest, False)  # `rest` may pass too: a clash across halves

    try:
        return search(tids, False)
    finally:
        git('merge', '--abort', cwd=d)
        clean(d)
        git('checkout', '-q', '--detach', base, cwd=d)


def merge(tid: str, branch: str) -> str | None:
    """Merge task/<tid> into the shared branch: merge, archive ticks, test, land, push, delete the branch.

    The merge is built and tested in its own worktree (`[run] home`/merge), and the shared branch only
    moves once the tests pass. So the main checkout never holds an untested merge: whoever works there keeps
    committing the whole time, nothing is reset under them, and their edits are never stashed.

    Unless `[run] batch_max` is 1, the other finished branches waiting for the lock ride along: one gate run for all of
    them (the gate is often the slow part). A rider that conflicts beyond a join waits for its own turn, and
    a batch that fails the gate is split: this task tries again alone, the riders take their own turns.

    Returns None when it landed, else why it was left alone. The shared branch is then as it was, and the
    task branch is still there.
    """
    if s := stack.stacked(tid, branch):  # F198: `stack.settle` comes first; its branch holds what has not landed
        return f'it was started on the merge of {", ".join(s["tids"])}, which has not landed'
    try:
        return merge_tries(tid, branch)
    finally:
        with FIX_DIRS_LOCK:  # its fixed-ahead files are free for the next fix, which now sees this merge
            if FIXING.pop(tid, None) is not None:
                FIX_DIRS_LOCK.notify_all()


def criticals(branch: str) -> set[str]:
    """The tasks critical in the plan (a `(follow-up, critical)` tag, or a section named Critical): fixes for a
    red shared branch or a flaky test, which every other merge's gate is waiting on. They merge alone, first."""
    return {tid for section, box, tid, rest, _ in P.iter_tasks(plan_text(branch)) if box != 'x' and (
        'critical' in section.lower() or ((t := P.PRI_TAG.search(rest)) and t.group(1) == 'critical'))}


def critical(tid: str, branch: str) -> bool:
    return tid in criticals(branch)


def merge_rank(tid: str, crit: bool) -> int:
    """Who takes MERGE next: a task already landed in a batch (only bookkeeping left), then a critical one (it
    unjams the gate for the rest), then one whose merge is built ahead with its gate under way (another turn
    first would drop that gate), then everyone else in the order they finished."""
    if tid in LANDED:
        return 0
    if crit:
        return 1
    return 2 if any(tid in a['tids'] for a in AHEADS) else 3


def merge_tries(tid: str, branch: str) -> str | None:
    """`merge`'s three tries."""
    yields, tries = True, -1
    if research_task(tid) and tid not in LANDED and tid not in WAITING and not research_code(tid, branch):
        # not one waiting since the start: a merge of it as it is may be gated already
        drop_strays(tid, branch)
    while (tries := tries + 1) < 3:
        if tid not in LANDED and (why := fix_ahead(tid, branch)):
            return why
        hold_for_release(tid, branch)
        WAITING.add(tid)
        crit = critical(tid, branch)
        with MERGE.turn(lambda: merge_rank(tid, crit)):
            WAITING.discard(tid)
            if tid not in LANDED and releasing(tid, branch):  # F99: a release started while it waited
                tries -= 1  # not a try: it waits for the release, then queues again
                continue
            if tid not in LANDED and UNPUSHED:  # a batch whose last task has not taken the lock yet: its
                push_landed(UNPUSHED[-1], branch)  # push goes out now, not after this one's gate
            if tid not in LANDED and (why := research_held(tid, branch)):  # F36: findings only
                forget(tid)
                return why
            if tid not in LANDED:  # else it went in with an earlier task's batch
                if (why := merge_batch(tid, branch, inline=tries == 2, yields=yields)) == LATER:
                    yields, tries = False, tries - 1  # once, and not a try: it queues again behind that batch
                    continue
                if why == AGAIN:
                    log(f'{tid}: {AGAIN}; it is fixed outside the lock again while the others merge')
                    continue
                if why:
                    forget(tid)
                    return why
            base, merged = LANDED.pop(tid)
            forget(tid)
            git('branch', '-d', f'task/{tid}')
            git('update-ref', '-d', TESTED + tid)
            git('update-ref', '-d', PARTIAL + tid)
            for h in git('for-each-ref', '--format=%(refname)', f'{HELD}{tid}/', f'{FIXED}{tid}/').stdout.split():
                git('update-ref', '-d', h)
            land_tick(tid, merged)
            line = next((l for l in plan_text(branch) if f'**{tid}**' in l), '')
            state = 'blocked' if line.startswith('- [~]') else 'part' if line else 'ticked'
            msg = f'{tid}: merged, {state}' + (f'; SUSPECT, recheck: {sus}' if (sus := suspect(base, merged)) else '')
            note(msg)
            log(msg, EV_PART if state == 'blocked' else EV_LANDED, tid)
            reopen_landed(branch, tid)  # before the push, so the reopen goes out with the merge
            published(tid, branch)
            announce_release(base, merged)
            return None
    return f'{tid}: no merge landed in three tries'


RELEASE_POLL = 10  # s: how often a merge held for a release looks whether it has landed (F99)


def releases(tids) -> set[str]:
    """The releases (kind V) among `tids`: they never ride in another task's batch, nor take riders (F99)."""
    return {t for t in tids if P.release(t)}


def releasing(tid: str, branch: str) -> str:
    """The release busy in this run that holds the merge of `tid` (F99), else '': a release (kind V) other than
    `tid` whose task/<ID> branch is there (running in a slot, or finished and waiting to merge) and not done in
    the plan. One taken by hand (`take`) holds nothing. A release's own merge is never held."""
    if P.release(tid):
        return ''
    refs = git('for-each-ref', '--format=%(refname)', 'refs/heads/task/').stdout.split()
    vs = sorted(r.removeprefix('refs/heads/task/') for r in refs if P.release(r.removeprefix('refs/heads/task/')))
    if not vs:
        return ''
    from agent_runner.sched import taken  # sched never imports merge
    live = {t for section, box, t, _, _ in P.iter_tasks(plan_text(branch))
            if box != 'x' and not section.startswith(P.SKIPPED)}
    away = set(taken())
    return next((v for v in vs if v in live and v not in away), '')


def hold_for_release(tid: str, branch: str) -> None:
    """While a release is busy (`releasing`), `tid`'s merge waits, and so does its push: the release then holds
    exactly what was on the shared branch when it started (F99). The task's work is kept; it merges once the
    release has landed (or was parked)."""
    said = ''
    while v := releasing(tid, branch):
        if v != said:
            said = v
            note(f'{tid}: waits to merge: {v} is releasing')
            log(f'{tid}: waits to merge: {v} is releasing; it merges once {v} has landed')
        time.sleep(RELEASE_POLL)
    if said:
        log(f'{tid}: {said} is no longer releasing; merging task/{tid} now')


def forget(tid: str) -> None:
    """Drop what the merge kept about `tid` (`ALONE`, `FAILED`, `TASK_SID`) once its merge is over."""
    ALONE.discard(tid)
    FAILED.pop(tid, None)
    TASK_SID.pop(tid, None)


def research_code(tid: str, branch: str) -> list[str]:
    """F36: the files task/<tid> changes beyond its findings (`brief.findings_globs`, the list its brief names)
    when `tid` is a research task; [] for any other task or a findings-only diff. Files that are new and empty
    (`new_empty`) count only beside real code (B224)."""
    if not research_task(tid):
        return []
    globs = findings_globs()
    files = git('diff', '--name-only', '--no-renames', '-z', f'{branch}...task/{tid}').stdout.split('\0')
    code = [f for f in files if f and not docs_only([f], globs)]
    return code if set(code) - set(new_empty(tid, branch)) else []


def research_says(tid: str, branch: str, title: str) -> str:
    """B221: what task/<tid> changes, in plain words for the question: its release note's first line, else its done
    message, else the task's `title`; without what would end the question early (a link, a bracket, a ` — `)."""
    said = ''
    note_md = git('show', f'task/{tid}:release-notes/{tid}.md')
    if not note_md.returncode:
        said = next((l for l in note_md.stdout.splitlines() if l.strip() and not l.startswith(('#', '---'))), '')
    for s in git('log', '--no-merges', '--format=%s', f'{branch}..task/{tid}').stdout.splitlines():
        if said:
            break
        s = re.sub(rf'^{re.escape(tid)}\b[:\s]*', '', s)
        said = '' if re.match(r'\(?wip\b|.*\(wip\)$', s, re.I) else s
    said = re.sub(r'https?://\S+', '', said or title)
    said = ' '.join(re.sub(r'[\[\]`*]|\bBLOCKED:|\bDECIDE:| [—|] ', ' ', said).split()).lstrip('-— ').rstrip(' .:')
    said = said if len(said) <= 160 else said[:160].rsplit(' ', 1)[0].rstrip(' ,;:-') + '…'
    return said[:1].upper() + said[1:]


def research_asked(tid: str, branch: str, item: str) -> str:
    """B221: the person's own words that asked for `tid`'s code, as its commits quote them (`P.asked_for`); ''."""
    try:
        long = P.long_form(C.plan_dir, tid).read_text(encoding='utf-8')
    except OSError:
        long = ''
    try:
        told = P.told_file(C, tid).read_text(encoding='utf-8')
    except OSError:
        told = ''
    messages = git('log', '--format=%B', f'{branch}..task/{tid}').stdout
    return P.asked_for(messages, P.person_words(item, tid, long, told))


def plan_item(tid: str, branch: str) -> str:
    """`tid`'s item in the plan, with its continuation lines; '' when it has none."""
    ls = plan_text(branch)
    i = next((i for i, l in enumerate(ls) if (m := P.ITEM.match(l)) and m.group(3).rstrip('.') == tid), None)
    return '\n'.join(P._item_block(ls, i)) if i is not None else ''


def research_ok(tid: str, branch: str, item: str) -> str:
    """How the person let `tid`'s code land with its findings, for "as the person …": their answer ships it, or
    their own words asked for it; '' when they did not."""
    if P.research_ships(item, tid):
        return 'answered'
    quote = research_asked(tid, branch, item)
    return f'asked for it: "{quote}"' if quote else ''


def research_unasked(tid: str, branch: str) -> bool:
    """B225: whether `research_held` would hold task/<tid>, without blocking it: such a task is never a rider in
    another task's merge, so its own turn asks the person."""
    return bool(research_code(tid, branch)) and not research_ok(tid, branch, plan_item(tid, branch))


def research_held(tid: str, branch: str) -> str | None:
    """F36: why task/<tid> does not merge: a research task whose diff touches code. It is blocked on a person
    (`DECIDE:`, B221) to ship the code or queue it as its own task; the branch is parked on wip/ by the caller.
    None when it may merge: no research task, findings only, the person's own words asked for the code
    (`research_asked`), or their answer ships it (`P.research_ships`)."""
    if not (code := research_code(tid, branch)):
        return None
    item = plan_item(tid, branch)
    shown = ', '.join(code[:8]) + (f' and {len(code) - 8} more' if len(code) > 8 else '')
    if ok := research_ok(tid, branch, item):
        log(f'{tid}: research that changes code ({shown}); merged, as the person {ok}')
        return None
    why = f'research changes no product, and this diff changes code: {shown}'
    ask = (f'DECIDE: {research_says(tid, branch, P.title_of(item) if item else tid)}. This is finished, but held '
           f'because {tid} was research, which changes no product. "{P.SHIP}" merges it with the findings. '
           f'"{P.QUEUE}" keeps only the findings now and queues the rest. Ship these changes? {P.RESEARCH_BUTTONS}'
           f' — it changes {shown}; the work is kept on wip/{tid}')
    if block_research(tid, branch, ask):
        note(f'{tid}: LEFT FOR A HUMAN — {why}')
        log(f'{tid}: LEFT FOR A HUMAN — {why}; blocked on a person', EV_LEFT, tid, why=why)
        return f'{why}; blocked on a person to ship it or queue it as its own task'
    return f'{why}; it could not be blocked now (TODO.md busy), so it starts again'


def block_research(tid: str, branch: str, ask: str) -> bool:
    """Block `tid` with `ask` in the main checkout's plan and commit it, as `block_parked` does (the caller holds
    the MERGE turn). False when TODO.md has edits or the main checkout is on another branch."""
    hold = ExitStack()
    try:
        if C.plan_external:
            hold.enter_context(plansync.locked(C))
            plansync.pull(C, force=True)
        rel = plan_rel('TODO.md')
        if not C.plan_external and (git('status', '--porcelain', '--', rel).stdout.strip() or branch and
                                    git('branch', '--show-current').stdout.strip() != branch):
            return False
        if tid not in P.open_ids(P.lines(ROOT / rel)):
            return False
        P.block(tid, ask, todo=ROOT / rel, after=[])
        if not commit_plan(f'Plan: block {tid}, research whose diff changes code', rel):
            if not C.plan_external:
                git('checkout', '-q', '--', rel)
            return False
        return True
    finally:
        hold.close()


def refix(tid: str, branch: str, ref: str, files: list[str], d: Path, undo: bool = False, msg: str = '') -> str | None:
    """Start the conflict again from a clean state (a refused join may have written some of its files) and give
    it to a fix session (`fix_merge`): None when it committed the merge, else why not. With `undo`, a merge
    it did not finish is taken back off `d`, so the batch goes on without it."""
    git('merge', '--abort', cwd=d)
    at = git('rev-parse', 'HEAD', cwd=d).stdout.strip()
    sha = git('rev-parse', ref, cwd=d).stdout.strip()
    if kept(tid, at, sha, d, 'fix'):
        return None
    git('merge', '--no-edit', '-m', msg or f"Merge branch 'task/{tid}'", ref, cwd=d, **task_env(tid))
    if (why := fix_merge(tid, branch, files, d, at, sha)) and undo:
        git('merge', '--abort', cwd=d)
        clean(d, at)
    return why


FIX_DIRS: set[int] = set()  # the fix worktrees (fix<k>) in use by a fix ahead of the lock
FIX_DIRS_LOCK = threading.Condition()  # at most `[run] fix_ahead_max` of them at once
FIXING: dict[str, set[str]] = {}  # a task fixed ahead and not merged yet -> its conflicted files (FIX_DIRS_LOCK)
FIXED = 'refs/agent-runner/fixed/'  # + <ID>/<task sha>: a fix session's merge of task/<ID> with the shared branch
AGAIN = 'conflicts again with the shared branch'  # merge_batch's why when a fix ahead of the lock is due
LATER = 'a merge already gated for other tasks goes first'  # merge_batch's why when it gives its turn up


def fixed(tid: str) -> str:
    """task/<tid>, or the merge a fix session made of it with the shared branch ahead of the lock (`fix_ahead`),
    while task/<tid> is still the commit that merge was made from."""
    sha = git('rev-parse', '-q', '--verify', f'task/{tid}').stdout.strip()
    ref = f'{FIXED}{tid}/{sha}'
    return ref if sha and git('rev-parse', '-q', '--verify', ref).returncode == 0 else f'task/{tid}'


def fix_ahead(tid: str, branch: str) -> str | None:
    """A conflict between task/<tid> and the shared branch that the join cannot do, resolved before the merge
    lock is taken: None when there is none, or a fix session resolved it, else why not.

    The session merges task/<tid> into the branch's head in a fix worktree of its own (fix1, fix2, …: kept,
    so their builds stay warm; at most `[run] fix_ahead_max` at once, so the worktrees and their builds never
    outnumber that, and each waits on `[run] before_start` as a slot does), and the merge it commits is kept
    as `fixed(tid)`. The other
    finished tasks merge and gate meanwhile; this one then takes the lock with that merge, which goes in
    clean unless the branch has meanwhile touched the same lines again (another, smaller fix). So
    its time limit (`C.run['fix_timeout']`) holds up nobody but this task.

    A conflict in a file that another task, fixed ahead and not merged yet, had in conflict waits for that
    task's merge to end: fixed side by side, whichever lands second would be fixed again (`FIXING`)."""
    if not (C.run['fix_merges'] and C.run['fix_ahead_max']):
        return None
    said = False
    while True:
        task = git('rev-parse', '-q', '--verify', f'task/{tid}').stdout.strip()
        base = git('rev-parse', branch).stdout.strip()
        if not task or fixed(tid) != f'task/{tid}' and \
                not git('merge-base', '--is-ancestor', base, fixed(tid)).returncode:
            return None
        src = fixed(tid)  # a merge fixed ahead before, which the branch has since moved past: only the new part
        r = git('merge-tree', '--write-tree', '--name-only', '--no-messages', base, src, **task_env(tid))
        if r.returncode != 1:  # 0: it merges clean; else git cannot say, and the locked merge finds out
            return None
        files = {f for f in r.stdout.splitlines()[1:] if f}
        with FIX_DIRS_LOCK:
            def ahead() -> list[str]:
                return sorted(t for t, fs in FIXING.items() if t != tid and fs & files)
            if before := ahead():
                if not said:
                    said = True
                    log(f'{tid}: waits for {", ".join(before)} to merge first: its conflicts are in the same '
                        'files, and fixed side by side one of them would be fixed twice')
                FIX_DIRS_LOCK.wait_for(lambda: not ahead())
                continue  # the branch has moved: look again
            while not (free := set(range(1, max(1, C.run['fix_ahead_max']) + 1)) - FIX_DIRS):
                FIX_DIRS_LOCK.wait()  # each one builds and runs an agent: wait for a turn
            if ahead():
                continue  # one that took a worktree first claimed the same files meanwhile
            k = min(free)
            FIX_DIRS.add(k)
            FIXING[tid] = FIXING.get(tid, set()) | files
        break
    d = SLOTS_DIR / f'fix{k}'
    try:
        while C.run['before_start'] and before_start_fails():  # no room (memory, say): as a slot waits
            time.sleep(60)
        if d.is_dir():
            trim(d, f'fix worktree {k}')
        worktree(f'fix{k}', base)
        git('merge', '--abort', cwd=d)
        clean(d, base)
        git('checkout', '-q', '--detach', base, cwd=d)
        ref = renumber_doubles(src, base, tid, d)
        msg = merge_message(tid, f'task/{tid}' if src != f'task/{tid}' else ref)
        if (files := merge_into(d, ref, msg, tid)) is None:
            return None  # git refused it here: the locked merge says so
        if files and not joined(files, tid, d):
            git('merge', '--abort', cwd=d)
            git('merge', '--no-edit', '-m', msg, ref, cwd=d, **task_env(tid))
            log(f'{tid}: resolving its conflicts with {branch} outside the merge lock, in {d.name}')
            if why := fix_merge(tid, branch, files, d):
                return why
        git('update-ref', f'{FIXED}{tid}/{task}', git('rev-parse', 'HEAD', cwd=d).stdout.strip())
        return None
    finally:
        git('merge', '--abort', cwd=d)
        git('checkout', '-q', '--detach', cwd=d)
        with FIX_DIRS_LOCK:
            FIX_DIRS.discard(k)
            FIX_DIRS_LOCK.notify_all()  # a turn for a worktree, or for files: notify() could wake the wrong one


FLAKE = 'the repair session found a flaky test, no clash: '  # repair_merge's why when its last line is FLAKE: …


def flake_said(logfile: Path) -> list[str]:
    """The tests a repair session named on a last `FLAKE:` line (fixer.log ends with its answer), or []."""
    try:
        tail = logfile.read_text(encoding='utf-8', errors='replace').rsplit('\n=== ', 1)[-1].rstrip().splitlines()[-5:]
    except OSError:
        return []
    m = next((m for l in reversed(tail) if (m := re.match(r'\W*FLAKE:\s*(.+)', l))), None)
    return flake_names(m[1]) if m else []


def flake_names(said: str) -> list[str]:
    """The test names in a `FLAKE:` answer: split on commas only, and never inside quotes or backticks."""
    out = []
    for n in re.findall(r"""(?:`[^`]*`|"[^"]*"|(?<!\w)'[^']*'(?!\w)|[^,])+""", said):
        n = n.strip(' *')
        if m := re.fullmatch(r"""`([^`]*)`|"([^"]*)"|'([^']*)'""", n):  # the quotes are around the whole name
            n = next(g for g in m.groups() if g is not None)
        if n := n.replace('`', '').strip(' *'):  # the task filed puts the name in backticks
            out.append(n)
    return out


def repair_retest(tid: str, branch: str, d: Path, base: str, merged: str,
                  riders: list[str] = ()) -> tuple[str | None, str | None, list[str]]:
    """A repair session on `merged`, which fails the gate (`repair_merge`), then the gate again: (why there is
    no repair, why the repaired merge still fails, the repair's commits). A repair that says the failure is a
    flake commits nothing, and the gate runs once more on the merge as it is before anything is parked; the
    flake is filed to be fixed either way."""
    if not_fixed := repair_merge(tid, branch, d, riders, base):
        if not not_fixed.startswith(FLAKE):
            return not_fixed, None, []
        names = flake_names(not_fixed[len(FLAKE):])
        flaky(tid, names)
        log(f'{tid}: {not_fixed}; running the gate once more before parking it')
        if why := tested(tid, d, base, [tid, *riders]):
            return f'{not_fixed}, and the gate failed again: {why}', None, []
        log(f'{tid}: the gate passed on the rerun; {", ".join(names)} filed to be fixed')
        return None, None, []
    return None, tested(tid, d, base), git('rev-list', '--reverse', f'{merged}..HEAD', cwd=d).stdout.split()


def upstream(branch: str, d: Path) -> str:
    """The remote's `branch`, just fetched, when it has commits the merge in `d` lacks; else ''. Merged into
    the merge before the gate, so the gate tests both and the push after it goes through."""
    remote = C.push_remote
    if not (C.push_merge and remote) or git('remote', 'get-url', remote).returncode:
        return ''
    _net(ROOT)('fetch', '-q', remote, branch)
    ref = f'refs/remotes/{remote}/{branch}'
    if git('rev-parse', '-q', '--verify', ref).returncode or \
            not git('merge-base', '--is-ancestor', ref, 'HEAD', cwd=d).returncode:
        return ''
    return ref


def merge_message(tid: str, ref: str) -> str:
    if C.run['include_task_id_in_commit']:
        return f"Merge branch 'task/{tid}'"
    subject = git('log', '-1', '--format=%s', ref).stdout.strip()
    prefix = f'{tid}:'
    if subject.startswith(prefix):
        subject = subject[len(prefix):].lstrip(' \t')
    return f'Merge: {subject or "task changes"}'


def carry_notes(base: str, d: Path) -> None:
    """Each merge since `base` in `d`: a note one side added to a task the other side ticked goes onto the
    task in DONE.md (`plan.carry_notes`), not lost with the TODO.md line the tick removed."""
    show = lambda rev: git('show', f'{rev}:{plan_rel("TODO.md")}', cwd=d).stdout.splitlines()
    path = d / plan_rel('DONE.md')
    if not path.exists():
        return
    have = path.read_text(encoding='utf-8').splitlines()
    got = have
    for m in git('rev-list', '--merges', f'{base}..HEAD', cwd=d).stdout.split():
        parents = git('rev-parse', f'{m}^1', f'{m}^2', cwd=d).stdout.split()
        mb = git('merge-base', *parents, cwd=d).stdout.strip()
        if len(parents) == 2 and mb:
            got = P.carry_notes(got, show(mb), [show(p) for p in parents])
    if got != have:
        path.write_text('\n'.join(got) + '\n', encoding='utf-8')


def caught_up(tid: str, branch: str, d: Path, base: str, merged: str, tids: list[str]) -> tuple[str, str] | None:
    """The tested merge in `d`, with what `branch` got since `base` during its gate merged in and tested: the
    branch's commit it is on and the commit to land, or None for the caller to build and test the whole merge again. `merged` passed the gate
    and the branch's new commits passed theirs, so only what those commits change is tested again, from
    `merged` (`[run] test_since`): an hour's batch gate is not rerun for a commit main got in its last minutes.
    Commits in `[run] untested` files only are not tested; a conflict or a failure builds it all again."""
    for _ in range(3):
        moved = git('diff', '--name-only', base, branch).stdout.split()
        if all(map(untestable, moved)):
            return base, merged
        new = git('rev-parse', branch).stdout.strip()
        if not C.run['test_since']:
            log(f'{tid}: {branch} got code commits during the tests; testing the merge again')
            return None
        files = merge_into(d, new, f'Merge {branch} into the merge of task/{tid}', tid)
        if files is None or files and not joined(files, tid, d):
            git('merge', '--abort', cwd=d)
            log(f'{tid}: {branch} got commits during the tests that conflict with the merge; building it again')
            return None
        log(f'{tid}: {branch} got code commits during the tests ({", ".join([f for f in moved if not untestable(f)][:5])}); '
            f'testing what they change since the tested merge {merged[:9]}')
        if why := tested(tid, d, merged, tids):
            FAILED.pop(tid, None)  # not the batch's own failure: `blame` must not read it
            log(f'{tid}: the merge with {branch}\'s new commits fails the gate; building it again ({why[:200]})')
            return None
        base, merged = new, git('rev-parse', 'HEAD', cwd=d).stdout.strip()
    log(f'{tid}: {branch} kept moving during the catch-up gates; building the merge again')
    return None


def owed(tid: str, base: str) -> dict | None:
    """A merge built and gated for other tasks, all of them waiting for the lock, that still lands on `base`,
    when `tid` is in none: after a restart `adopt_merge` finds it only once a turn has begun, and that turn's
    own merge would drop a gate that took an hour (P347's turn dropped R38's passed batch, 11-17)."""
    if any(tid in a['tids'] for a in AHEADS):
        return None
    return next((a for a in AHEADS if reusable(a, a['tids'][0], base) and a['tids'][0] in WAITING), None)


BATCH_RETRY = object()  # a merge_batch step's answer: build the merge again, in the next of its three tries


class BatchTurn:
    """One merge_batch turn's state, shared by its steps (`batch_build`, `batch_test`, `batch_land`) and kept
    across its three tries: what the turn is (tid, branch, the merge worktree d, the critical tasks, whether
    a conflict goes to a fix ahead of the lock or to a fix session in the batch), whether it merges alone,
    the repairs to replay, and the try's base, merge commit and riders."""

    def __init__(self, tid: str, branch: str, d: Path, solo: bool, crit: set[str], ahead_fix: bool,
                 batch_fixes: bool):
        self.tid, self.branch, self.d = tid, branch, d
        self.solo, self.crit, self.ahead_fix, self.batch_fixes = solo, crit, ahead_fix, batch_fixes
        self.repairs: list[str] = []  # a repair session's commits, replayed when the merge is built again
        self.repaired_on = ''  # the base the last repair session ran on: one repair per failure, not per task,
        # so a rebuild that fails on commits the shared branch got since that repair gets a repair of its own
        self.batch_repaired = False  # one repair session per batch; a batch that still fails is split
        self.base = ''
        self.merged = ''
        self.riders: list[str] = []


def batch_build(t: BatchTurn):
    """merge_batch's build step: the merge of task/<tid> and its riders on the branch's head, in t.d.

    Reuses a merge already built and gated ahead when it still fits; takes in the remote's commits, replays
    t.repairs and archives ticked tasks. Sets t.base, t.riders and t.merged. Returns None when built,
    BATCH_RETRY to build again, or why it cannot merge (AGAIN for a fix ahead of the lock)."""
    tid, branch, d = t.tid, t.branch, t.d
    UNDER.clear()
    git('merge', '--abort', cwd=d)
    clean(d)
    t.base = base = git('rev-parse', branch).stdout.strip()
    git('checkout', '-q', '--detach', base, cwd=d)
    ahead = next((a for a in AHEADS if reusable(a, tid, base) and  # one adopted may hold research not asked about
                  not any(research_unasked(x, branch) for x in a['tids'] if x != tid)), None)
    if ahead:
        AHEADS.remove(ahead)
        clean(d, ahead['merged'])
        t.riders = riders = [x for x in ahead['tids'] if x != tid]
        log(f'{tid}: reusing the merge already built and gated (ahead, or by an earlier run)' +
            (f' with {", ".join(riders)}' if riders else ''))
        if ahead['base'] != base:  # the branch moved by untested files only: take them in
            if (files := merge_into(d, base, f'Merge {branch} into the merge of task/{tid}')) is None or \
                    files and not joined(files, tid, d):
                git('merge', '--abort', cwd=d)
                log(f'{tid}: {branch} moved and conflicts with it; building the merge again')
                return BATCH_RETRY
    else:
        if AHEADS:
            if a := next((a for a in AHEADS if tid in a['tids']), None):  # say why its gate is thrown away
                moved = [f for f in git('diff', '--name-only', a['base'], base).stdout.split()
                         if not untestable(f)]
                log(f'{tid}: not reusing the merge gated with {", ".join(x for x in a["tids"] if x != tid)}: '
                    + (f'{branch} moved in tested files ({", ".join(moved[:5])}; `[run] untested` leaves '
                       f'them in)' if moved else 'its tasks changed, or it holds research to ask about'))
            drop_ahead()  # the branch moved some other way, or its tasks are gone: not this merge
        own = fixed(tid)
        ref = renumber_doubles(own, base, tid, d)
        msg = merge_message(tid, f'task/{tid}' if own != f'task/{tid}' else ref)
        if (files := merge_into(d, ref, msg, tid)) is None:
            return f'git refused to merge task/{tid} into {branch} (see the merge worktree, {d})'
        if files:
            if joined(files, tid, d):
                log(f'{tid}: joined both sides of {", ".join(files)}')
            elif t.ahead_fix:
                return AGAIN
            elif why := refix(tid, branch, ref, files, d, msg=msg):
                return why
        t.riders = riders = []
        for x in ([] if t.solo else sorted(WAITING - set(LANDED) - ALONE - t.crit - releases(WAITING))):
            if C.run['batch_max'] and len(riders) + 1 >= C.run['batch_max']:
                break  # the rest go in the next batch: a failure here costs fewer tasks a retest
            if research_unasked(x, branch):
                continue  # its own turn asks the person (`research_held`)
            own = fixed(x)
            ref = renumber_doubles(own, 'HEAD', x, d)
            msg = merge_message(x, f'task/{x}' if own != f'task/{x}' else ref)
            if (files := merge_into(d, ref, msg, x)) is None:
                git('merge', '--abort', cwd=d)
                continue
            if files and not joined(files, x, d):
                if not t.batch_fixes or agent_held():  # B764c: no session for a rider now, and it holds nobody else
                    git('merge', '--abort', cwd=d)
                    continue  # it waits for its own turn, where a fix session can take the conflict
                # a fix session takes the conflict here, so the rider shares this gate run
                if refix(x, branch, ref, files, d, undo=True, msg=msg):
                    continue  # it waits for its own turn
            riders.append(x)
        if riders:
            log(f'{tid}: merging together with {", ".join(riders)} (one gate run)')
    if up := upstream(branch, d):  # someone pushed to the remote: take it in, the gate tests it too
        msg = f"Merge {up.removeprefix('refs/remotes/')} into {branch}"
        if (files := merge_into(d, up, msg)) is None:
            return f'git refused to merge {up} into the merge of task/{tid} (see the merge worktree, {d})'
        if files and not joined(files, tid, d) and (why := refix(tid, branch, up, files, d, msg=msg)):
            return f'{up} has moved and conflicts with the merge: {why}'
        log(f'{tid}: {up} had commits {branch} did not; merged in, so the gate tests them together')
    if t.repairs and git('cherry-pick', '--allow-empty', *t.repairs, cwd=d).returncode:
        git('cherry-pick', '--abort', cwd=d)
        log(f'{tid}: the repair no longer applies to the merge; testing it without')
        t.repairs = []
    if not C.plan_external:  # outside, `done` and `land_tick` archive as they tick
        carry_notes(base, d)
        P.archive(d / plan_rel('TODO.md'), d / plan_rel('DONE.md'))
    plan_files = [plan_rel('TODO.md'), plan_rel('DONE.md')]
    if git('status', '--porcelain', '--', *plan_files, cwd=d).stdout.strip():
        git('commit', '-qm', f'{tid}: archive ticked tasks', '--', *plan_files, cwd=d)
    t.merged = git('rev-parse', 'HEAD', cwd=d).stdout.strip()
    return None


def docs_merge(t) -> bool:
    """The merge t.merged changes only `[run] docs_files` on its base (every task in it, the plan's archive
    commit and a remote's commits taken in too): the slow gate need not run on it."""
    files = git('diff', '--name-only', '--no-renames', t.base, t.merged, cwd=t.d).stdout.split()
    return bool(C.run['test']) and docs_only(files, C.run['docs_files'])


def docs_checked(t) -> str | None:
    """A docs-only merge (`docs_merge`): `[run] docs_check` in place of the gate, if there is one. None when
    it may land, else why not."""
    tids = ', '.join([t.tid, *t.riders])
    if not C.run['docs_check']:
        log(f'{tids}: {DOCS_SKIP}')
        return None
    rc, out = hook(f'{tids}: the docs check (counted as failing)', C.run['docs_check'], t.d, merge_env())
    out = out.strip()
    if rc == 0:
        log(f'{tids}: {DOCS_SKIP}; docs check passed')
        return None
    C.notes('merge-gate.log').write_text(out + '\n', encoding='utf-8')
    return 'docs only, and the docs check fails: ' + ' / '.join(out.splitlines()[-4:])[:400]


def batch_test(t: BatchTurn):
    """merge_batch's test step: the gate on t.merged, unless `done` already passed it on the same code.

    A failing batch is split (by blame, or after one batch repair); a failing merge alone gets one repair
    session per base. Returns None when the merge (t.merged, perhaps repaired) may land, BATCH_RETRY to build
    it again (t.solo, t.repairs changed), or why it fails."""
    tid, branch, d, base, riders = t.tid, t.branch, t.d, t.base, t.riders
    # `done` already passed the gate on the branch: rerun it only if the merged code differs
    # from what it tested (`[run] untested` files are not code). Not after `done --no-test`, nor
    # commits made after `done`, nor a session that never ran it: its tested ref is not the branch
    if not (riders or not gated(tid) or
            not all(map(untestable, git('diff', '--name-only', f'task/{tid}', t.merged, cwd=d).stdout.split()))):
        return None
    if docs_merge(t):
        return docs_checked(t)
    UNDER[:] = [{'on': t.merged, 'tids': [tid, *riders]}]
    ahead_done = threading.Event()
    if C.run['merge_ahead']:
        threading.Thread(target=build_ahead, args=(branch, t.merged, ahead_done, {tid, *riders}),
                         daemon=True).start()
    try:
        why = tested(tid, d, base, [tid, *riders])
    finally:
        ahead_done.set()
    if not why:
        return None
    UNDER.clear()
    drop_ahead()  # built on a merge that does not land as it is
    names = FAILED.pop(tid, [])
    if riders and names and (bad := blame([tid, *riders], d, base, names)):
        ALONE.update(bad)
        log(f'{tid}: the batch fails {", ".join(names)}; {", ".join(bad)} '
            f'fail{"s" if len(bad) == 1 else ""} them alone, so '
            f'{"it merges" if len(bad) == 1 else "they merge"} in a turn of {"its" if len(bad) == 1 else "their"} own')
        t.solo, t.repairs = t.solo or tid in bad, []
        return BATCH_RETRY
    if riders and names:
        git('checkout', '-q', '--detach', t.merged, cwd=d)  # blame left it on the base
    if riders and not t.batch_repaired and C.run['repair_merges'] and not agent_held():
        t.batch_repaired = True
        not_fixed, still, fixes = repair_retest(tid, branch, d, base, t.merged, riders)
        if not not_fixed and not still:
            note(f'{tid}: the batch ({", ".join(riders)} with it) failed the gate; ' +
                 ('a repair session fixed it' if fixes else 'a flake, by the repair session: it passed on a rerun'))
            # replayed if the batch is built again because the shared branch moved
            t.repairs, t.merged, why = fixes, git('rev-parse', 'HEAD', cwd=d).stdout.strip(), None
        else:
            note(f'{tid}: no batch repair: {not_fixed or "the repaired batch still fails the gate"}')
    if why and riders:
        log(f'{tid}: the batch fails the gate; {tid} again alone, the others in their own turns')
        t.solo, t.repairs = True, []
        return BATCH_RETRY
    if not why:
        return None
    if t.repaired_on == base:
        return why + (' (after a repair session)' if t.repairs else '')
    if t.repaired_on:
        log(f'{tid}: {branch} moved since the repair ({t.repaired_on[:10]}..{base[:10]}) and the merge '
            f'fails again: a new failure, so a new repair session')
    t.repaired_on, t.solo = base, True  # a rebuild replays the repairs onto this task alone
    not_fixed, still, fixes = repair_retest(tid, branch, d, base, t.merged)
    t.repairs = t.repairs + fixes
    if not_fixed:
        note(f'{tid}: no repair: {not_fixed}')
        return why
    if still:
        return still + ' (after a repair session)'
    t.merged = git('rev-parse', 'HEAD', cwd=d).stdout.strip()
    note(f'{tid}: the merge failed the gate; ' + ('a repair session fixed it' if t.repairs else
                                                  'a flake, by the repair session: it passed on a rerun'))
    return None


def batch_land(t: BatchTurn, last: bool = False):
    """merge_batch's land step: catch t.merged up with the branch and land it; record the tasks in LANDED.

    Returns None when landed, BATCH_RETRY when it did not catch up or (unless `last`) lost a race to land,
    or why it did not land."""
    if (got := caught_up(t.tid, t.branch, t.d, t.base, t.merged, [t.tid, *t.riders])) is None:
        return BATCH_RETRY
    t.base, t.merged = got
    pitch.landing([t.tid, *t.riders], t.base, t.merged)  # F98: nothing unless [run] approve
    with LANDING:
        why = land(t.tid, t.branch, t.merged)
    pitch.landed(t.merged, not why)
    if why == 'conflict' and not last:
        return BATCH_RETRY
    if why:
        return why
    for x in [t.tid, *t.riders]:
        LANDED[x] = (t.base, t.merged)
    return None


def merge_batch(tid: str, branch: str, inline: bool = False, yields: bool = True) -> str | None:
    """`merge`'s part under the lock: build, test and land task/<tid> and its riders; record them in LANDED.

    A conflict of task/<tid> that the join cannot do returns AGAIN, for `fix_ahead` to take outside the lock,
    unless `inline` (its last try) or `fix_ahead_max` is 0: then a fix session takes it here. A rider with one
    waits for its own turn. With `yields`, a merge already gated for other waiting tasks (`owed`) returns
    LATER: those tasks rank ahead now (`merge_rank`), so the caller queues again."""
    ahead_fix = C.run['fix_merges'] and C.run['fix_ahead_max'] and not inline
    d = worktree('merge', branch)
    adopt_merge(d)
    if yields and tid not in criticals(branch) and (a := owed(tid, git('rev-parse', branch).stdout.strip())):
        log(f'{tid}: the merge of {", ".join(a["tids"])} is already gated; it lands first, then this turn')
        return LATER
    if trim(d, 'merge worktree'):
        worktree('merge', branch)
    crit = criticals(branch)
    solo = C.run['batch_max'] == 1 or tid in ALONE or tid in crit or P.release(tid)  # F99: a release lands alone
    batch_fixes = C.run['fix_merges'] and not C.run['fix_ahead_max']  # a rider's conflict: a fix session in the batch
    t = BatchTurn(tid, branch, d, solo, crit, ahead_fix, batch_fixes)
    try:
        for attempt in range(3):
            why = batch_build(t)
            if why is None:
                why = batch_test(t)
            if why is None:
                why = batch_land(t, last=attempt == 2)
                if why is None:
                    return None
            if why is BATCH_RETRY:
                continue
            return why
        return f'{tid}: no merge landed in three tries'
    finally:
        UNDER.clear()
        git('merge', '--abort', cwd=d)
        git('checkout', '-q', '--detach', cwd=d)


# --- the loop ------------------------------------------------------------------

def before_start_fails() -> bool:
    """`[run] before_start` exits non-zero, or runs past `[run] command_timeout` (logged: it holds every start)."""
    return hook('before_start (counted as failing)', C.run['before_start'], ROOT)[0] != 0
