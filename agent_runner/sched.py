"""Picking the next task: the open tasks in order, what clashes with what is running (files, sections,
siblings), claims other runners hold, and tasks parked too often."""

from __future__ import annotations

import json
import re
import time
from contextlib import ExitStack
from typing import NamedTuple

from agent_runner import plan as P, plansync
from agent_runner.state import (alarm, C, commit_plan, edited, FETCHED, git, log, MERGE, note, plan_rel, plan_text,
    queued, ROOT, SLOTS_DIR)


# --- picking the next task -----------------------------------------------------

def open_tasks(branch: str) -> set[str]:
    """Ids of the open ([ ]) top-level tasks in `branch`'s TODO.md."""
    return {tid for _, box, tid, _, _ in P.iter_tasks(plan_text(branch)) if box == ' '}


def blocked_tasks(branch: str) -> set[str]:
    """Ids of the blocked ([~]) top-level tasks in `branch`'s TODO.md."""
    return {tid for _, box, tid, _, _ in P.iter_tasks(plan_text(branch)) if box == '~'}


def tasks(branch: str) -> list[tuple[str, str, set[str], set[str]]]:
    """Open tasks in TODO.md order: (id, section, its `files:`, its `after:`)."""
    ls = plan_text(branch)
    # open and blocked: neither is done, so a split parent or an `after:` still waits on a blocked X
    open_ids = {tid for _, box, tid, _, _ in P.iter_tasks(ls) if box != 'x'}
    out = []
    for section, box, tid, _, i in P.iter_tasks(ls):
        if box != ' ' or section.startswith(P.SKIPPED):
            continue
        l = ls[i]
        f = P.fields(l)
        if P.LAST in f.get('after', []):  # `after: all above`, resolved afresh on every pick (F43)
            f['after'] = P.waits_on(ls, i)
        # a split parent: its subtasks run first, blocked ones included, then it runs (or `archive` ticks it).
        # Read by id and by its `(split into …)` list, never by the words alone, so prose that happens to say
        # "split into" is not taken for a split
        if P.subtasks(tid, l, open_ids):
            continue
        after = set(f.get('after', [])) - {tid}
        if after & open_ids:
            continue
        out.append((tid, section, set(f.get('files', [])), after))
    return by_waiters(ls, out)


def by_waiters(ls: list[str], out: list[tuple]) -> list[tuple]:
    """`out` with each task a waiting one depends on moved up to where that one stands: a task in a Next
    section with `after: S281` on a Follow-up would otherwise wait for every task between them, and
    so would everything waiting on it. Transitive; Stretch and Parked lines pull nothing up."""
    rank, waits = {}, {}
    for section, box, tid, _, n in P.iter_tasks(ls):
        if box == 'x':
            continue
        rank.setdefault(tid, len(rank))
        if not section.startswith(P.SKIPPED):
            l = ls[n]
            waits[tid] = set(P.fields(l).get('after', [])) | {
                i for a in P.WAITS.findall(l) for i in P.TASK_ID.findall(a)}  # and a block's `(after X)`
    for _ in range(len(waits)):  # each pass moves a rank one link down a chain
        moved = False
        for w, deps in waits.items():
            for dep in deps:
                if dep in rank and rank[w] < rank[dep]:
                    rank[dep], moved = rank[w], True
        if not moved:
            break
    order = {t[0]: (rank.get(t[0], len(rank)), k) for k, t in enumerate(out)}
    return sorted(out, key=lambda t: order[t[0]])


def ahead(branch: str) -> list[str]:
    """Ids whose task/<ID> has commits `branch` lacks, in one `git for-each-ref` rather than a call per branch."""
    refs = git('for-each-ref', f'--no-merged={branch}', '--format=%(refname)', 'refs/heads/task/').stdout.split()
    return [r.removeprefix('refs/heads/task/') for r in refs]


def family(tid: str) -> str:
    """L3a, L3b, L3 -> L3; A11k4 -> A11. Siblings share it and never run side by side."""
    m = re.match(r'[A-Za-z]*\d*', tid)
    return m.group() if m else tid


def ordered(section: str) -> bool:
    """A section whose heading says its tasks run in sequence ("Next (in this order)", "… one at a time") runs
    one task at a time: its second task usually depends on the first having landed, whatever the files say.
    A plain "Next" or "(in order)" is a priority order: its tasks start side by side, by files."""
    return 'in this order' in section or 'one at a time' in section



def whole_dir(f: str) -> bool:
    """A `files:` entry that names a whole directory (`tests/**`, `dir/*`): a guess, not a file list."""
    return (f.endswith('/**') or f.endswith('/*')) and '*' not in f.rsplit('/', 1)[0]


def file_overlap(files, b: tuple, shared: set) -> set[str]:
    """The entries of a waiting task's `files` that meet busy task `b`'s. A whole-directory glob (`tests/**`) is a
    guess, not a lock: it meets only another whole-directory glob, both ways. The waiting task's other entries
    meet `b`'s files (`b[2]`: its line's and those it has touched) minus its line's whole-directory globs; its
    whole-directory globs meet only the whole-directory globs on `b`'s line (`b[4]`, when given, is its line's
    files). So a big rewrite (`native/**`) neither waits for nor holds every task naming a file under that dir,
    only the files it has touched, while two rewrites of one dir still exclude each other (T6, B62)."""
    files = set(files) - shared
    line = set(b[4]) if len(b) > 4 else set(b[2])
    dirs = {f for f in files if whole_dir(f)}
    held = {f for f in b[2] if not whole_dir(f)}
    return P.overlap(files - dirs, held) | P.overlap(dirs, {f for f in line if whole_dir(f)})


def clash(t: tuple, b: tuple, shared: set[str]) -> bool:
    """Task `t` may not run beside `b` (running here, waiting to merge, or claimed by another runner): siblings,
    a shared ordered section, or overlapping files (`shared_files` aside; see `file_overlap`)."""
    tid, section, files, _ = t
    if family(tid) == family(b[0]):
        return True
    return (ordered(section) and section == b[1]) or bool(file_overlap(files, b, shared))


def clash_why(t: tuple, b: tuple, shared: set) -> tuple[str, str]:
    """Why `clash(t, b)`: (the kind of wait, what holds it), for the dry run."""
    if family(t[0]) == family(b[0]):
        return 'waiting for a sibling', b[0]
    if ordered(t[1]) and t[1] == b[1]:
        return f'one at a time in "{t[1]}"', b[0]
    return 'waiting for files', f'{", ".join(sorted(file_overlap(t[2], b, shared))[:3])} held by {b[0]}'


def claimed_elsewhere(cls: dict, todo: list) -> list[tuple]:
    """Other runners' live claims as busy tasks: the claimed line's section, files and named ids, plus the
    files its claim says its session has touched. A stale claim (a crashed run's) holds only its own task."""
    me, lines = plansync.owner(C), {t[0]: t for t in todo}
    out = []
    for tid, cl in cls.items():
        if cl.owner == me or plansync.stale(cl):
            continue
        t = lines.get(tid, (tid, '', set(), set()))
        out.append((tid, t[1], set(t[2]) | set(cl.files), t[3], set(t[2])))
    return out


def pick(running: dict, tried: set, branch: str, claim: bool = False, why: dict | None = None):
    """The next task a free slot may take, or None. See the module docstring for the rules.

    `claim` (a run about to start it): with a remote to share claims through, the task is claimed and the claim pushed first;
    one another runner has, or got just now, is passed over for the next. Another runner's live claim counts
    as a task running here, so its files, ordered section and family wait for it too. A task parked
    PARK_LIMIT times is blocked on a person first (`block_parked`), here, not inside `choose`.

    `why` (the dry run): pick nothing, and fill it with every open task's reason instead (`explain`), as
    {tid: (kind, detail)}; a task free to start gets ('free', '')."""
    if why is not None:
        why.update(explain(running, tried, branch))
        return None
    h = held(running, branch)
    if claim:
        for tid in parked_now(tried, h):
            block_parked(tid, h.parked[tid], branch)
    return choose(h, tried, branch, claim)


class Held(NamedTuple):
    """What holds the open tasks back, read once per pick: `todo` (tasks()), `busy` (running, merge-waiting,
    claimed and taken tasks, as clash() tuples), `busy_ids`, `mine` (finished here, waiting to merge),
    `finished` (mine and another runner's), `parked` ({tid: its parked branches}) and `shared` (shared_files)."""
    todo: list
    busy: list
    busy_ids: set
    mine: set
    finished: set
    parked: dict
    shared: set


def held(running: dict, branch: str) -> Held:
    """The Held for `branch` with `running` ({slot: task}) in the slots."""
    shared = set(C.run['shared_files'])
    todo = tasks(branch)
    busy = claimed_elsewhere(plansync.claims(C), todo)  # [] with no remote to claim through
    lines_ = {t[0]: t for t in todo}
    for tid, d in taken().items():  # `take`: a person's session or subagent has it, in its own worktree
        t = lines_.get(tid, (tid, '', set(), set()))
        busy.append((tid, t[1], set(t[2]) | touched(tid, branch, d), t[3], set(t[2])))
    busy_ids = {b[0] for b in busy} | {q[0] for q in queued().values()}  # one waiting to resume is running
    mine = set(ahead(branch)) if todo else set()  # finished here, waiting to be merged
    finished = mine | plansync.taken(C)  # another runner's: on its slots
    lines = {t[0]: t for t in todo}
    # A running task holds the files it has touched as well as its line's (a line can name too few). A finished
    # one holds only the files it changed, until its merge lands: its line's names were a guess, and a broad
    # one (`tests/**`) would keep dozens of tasks from starting while the merges catch up
    slots = {t[0]: SLOTS_DIR / f's{n}' for n, t in running.items() if isinstance(n, int)}
    live = {t[0] for t in running.values()}
    for tid, t in {**{f: lines.get(f, (f, '', set(), set())) for f in mine},
                   **{t[0]: t for t in running.values()}}.items():
        files = touched(tid, branch, slots.get(tid))
        done_ = tid in mine and tid not in busy_ids and tid not in live and files  # finished, not running
        busy.append((tid, t[1], files if done_ else set(t[2]) | files, t[3], set() if done_ else set(t[2])))
    busy_ids |= {b[0] for b in busy if b[0] not in mine}
    parked = parked_attempts() if todo else {}
    return Held(todo, busy, busy_ids, mine, finished, parked, shared)


def holds(t: tuple, tried: set, h: Held) -> tuple[str, tuple | None] | None:
    """Why open task `t` may not start now, first reason only: ('finished', None), ('tried', None),
    ('busy', None), ('parked', None) or ('clash', the busy task it clashes with); None when it is free."""
    tid = t[0]
    if tid not in h.busy_ids and tid in h.finished:
        return 'finished', None  # its branch is waiting to be merged: restarting it would reset the branch
    if tid in tried:
        return 'tried', None
    if tid in h.busy_ids:
        return 'busy', None
    if len(h.parked.get(tid, [])) >= PARK_LIMIT:  # B32: failed its merge that often; a person decides
        return 'parked', None
    if b := next((b for b in h.busy if clash(t, b, h.shared)), None):
        return 'clash', b  # a running or merge-waiting task's sibling, ordered-section mate or file neighbour
    return None


def parked_now(tried: set, h: Held) -> list[str]:
    """The open tasks held back only for being parked PARK_LIMIT times: the ones `pick` blocks on a person."""
    return [t[0] for t in h.todo if holds(t, tried, h) == ('parked', None)]


def explain(running: dict, tried: set, branch: str) -> dict[str, tuple[str, str]]:
    """The dry run: every open task's reason it does not start, as {tid: (kind, detail)}; ('free', '') for one
    that may. Changes nothing."""
    h = held(running, branch)
    claimed = {t: cl.who for t, cl in plansync.claims(C).items()}
    why = {}
    for t in h.todo:
        tid = t[0]
        kind, b = holds(t, tried, h) or ('free', None)
        if kind == 'finished':
            why[tid] = ('claimed by another runner', claimed.get(tid, '')) if tid not in h.mine else \
                ('finished, waiting to merge', '')
        elif kind == 'tried':
            why[tid] = ('tried this run', '')
        elif kind == 'busy':
            why[tid] = ('running', f'claimed by {claimed[tid]}' if tid in claimed else
                        'taken by hand (`take`)' if tid in taken() else '')
        elif kind == 'parked':
            why[tid] = (f'parked {len(h.parked[tid])} times, needs a person', ', '.join(sorted(h.parked[tid])))
        elif kind == 'clash':
            why[tid] = clash_why(t, b, h.shared)
        else:
            why[tid] = ('free', '')
    return why


def choose(h: Held, tried: set, branch: str, claim: bool = False):
    """The first open task nothing holds back (`holds`), claimed first when `claim` (see `claim_task`), or None.
    Parked tasks are skipped, not blocked: that is `pick`'s part."""
    for t in h.todo:
        if holds(t, tried, h):
            continue
        tid = t[0]
        if got := claim_task(t, h, branch) if claim else t:
            PASSED.discard(tid)
            return got
        if tid not in PASSED:
            PASSED.add(tid)
            log(f'{tid}: claimed by another runner, closed since the pick read the plan, the claim did not push, '
                'or a clashing claim came first; passed over')
    return None


def claim_task(t: tuple, h: Held, branch: str):
    """`t` once claimed and the claim pushed, or None when it could not be had (claimed elsewhere, closed
    meanwhile, or a clashing claim came first); `t` as is with no remote to claim through."""
    if not plansync.enabled(C):
        return t
    if not plansync.claim(C, t[0], t[2]):
        return None
    FETCHED[0] = 0.0  # in-repo: the merge that closed it may have landed since the last fetch
    if t[0] not in open_tasks(branch):  # the claim pulled: the pick may have read a plan up to 20 s old
        plansync.release(C, t[0])  # closed meanwhile (ticked or blocked by someone else)
        return None
    # Two runners can claim clashing tasks from plans read seconds apart; both see both claims now, and
    # the later one gives way (claim time, then owner: both sides reach the same verdict).
    now = plansync.claims(C)
    mine = now.get(t[0])
    for b in claimed_elsewhere(now, h.todo):
        cl = now[b[0]]
        if mine and (cl.since, cl.owner) < (mine.since, mine.owner) and clash(t, b, h.shared):
            plansync.release(C, t[0])
            log(f'{t[0]}: {cl.who} claimed {b[0]} first and it clashes; given way')
            return None
    return t


PASSED: set[str] = set()  # tasks `pick` could not claim, said once each


CLAIMS_AT = [0.0]
STALE_SAID: set[str] = set()


def touched(tid: str, branch: str, slot: Path | None) -> set[str]:
    """Files task `tid` has changed so far: its branch's commits past `branch`, and in its slot what is not
    committed yet. A claim carries them, so another runner keeps off them even when the task line lists
    none (or too few)."""
    out = set(git('diff', '--name-only', f'{branch}...task/{tid}').stdout.split())
    if slot and slot.is_dir():
        st = git('status', '--porcelain', '--untracked-files=all', cwd=slot)
        if not st.returncode:
            out |= {l[3:].split(' -> ')[-1].strip('"') for l in st.stdout.splitlines()}
    return out


def keep_claims(running: dict, branch: str) -> None:
    """Every plansync.REFRESH s: re-stamp this run's claims (running, or waiting to merge) with
    the files each holds (the line's and the ones its session has touched), drop its claims on anything else,
    and say once of each other run's claim gone stale (a crashed run's would hold that task for good)."""
    if time.time() - CLAIMS_AT[0] < plansync.REFRESH or not plansync.enabled(C):
        return
    CLAIMS_AT[0] = time.time()
    slots = {t[0]: (SLOTS_DIR / f's{n}', t[2]) for n, t in running.items() if isinstance(n, int)}
    keep = set(slots) | set(ahead(branch)) | {q[0] for q in queued().values()}  # queued: waiting to resume
    lines = {t[0]: t[2] for t in tasks(branch)}
    files = {t: set(slots.get(t, (None, lines.get(t, set())))[1]) | touched(t, branch, slots.get(t, (None,))[0])
             for t in keep}
    plansync.refresh(C, keep, files)
    me = plansync.owner(C)
    for t, cl in plansync.claims(C).items():
        if cl.owner == me:
            continue
        if plansync.stale(cl) and t not in STALE_SAID:
            STALE_SAID.add(t)
            log(f'{t}: claimed by {plansync.label(cl)}, not refreshed since: if that run is gone, '
                f'`{C.command} plan unclaim {t}`')


PARK_LIMIT = 2  # B32: a task parked this many times (wip/<ID>, wip/<ID>-2, …) is blocked on a person, not retried


def parked_attempts() -> dict[str, list[str]]:
    """{task id: its parked branches} (`_finish`'s wip/<ID>, wip/<ID>-2, …), in one `git for-each-ref`. Counted
    across runs and restarts, since the branches outlive both. A wip/<ID> holding only the edits a reset slot
    saved (`save_leftovers`, "<ID> wip: uncommitted …") is no failed merge and does not count, nor do the
    wip/main-checkout-* branches."""
    out: dict[str, list[str]] = {}
    refs = git('for-each-ref', '--format=%(refname:short)%09%(subject)', 'refs/heads/wip/').stdout.splitlines()
    for r in refs:
        name, _, subj = r.partition('\t')
        if not (m := re.fullmatch(r'wip/([A-Za-z]+\d+[a-z0-9]*?)(?:-\d+)?', name)) or name.startswith('wip/main-checkout'):
            continue
        if subj.startswith(f'{m[1]} wip: uncommitted'):
            continue
        out.setdefault(m[1], []).append(name)
    seen = parked_seen()  # attempts a person was already asked about: unblocked, the task gets PARK_LIMIT more
    return {t: left for t, ws in out.items() if (left := [w for w in ws if w not in seen.get(t, ())])}


def parked_seen() -> dict[str, list[str]]:
    """{task id: the parked branches `block_parked` already blocked it over}, from `<notes>/parked-seen.json`."""
    try:
        d = json.loads(C.notes('parked-seen.json').read_text(encoding='utf-8'))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def parked_reasons(tid: str) -> list[str]:
    """Why each parked attempt of `tid` did not merge, oldest first, from the ledger's "not merged, parked as" lines."""
    try:
        led = C.notes('ledger.md').read_text(encoding='utf-8', errors='replace').splitlines()
    except OSError:
        return []
    rx = re.compile(rf'{re.escape(tid)}: not merged, parked as (\S+) — (.*)')
    return [f'{m[1]}: {m[2][:160].rstrip()}' for l in led if (m := rx.search(l))]


def block_parked(tid: str, wips: list[str], branch: str) -> bool:
    """B32: block `tid` on a person, its parked attempts and the ledger's reasons in the why, committed as
    `file_control_ask` commits (MERGE free, TODO.md clean). False when it could not be done now (the next pick
    tries again; until then `pick` skips the task all the same)."""
    if not MERGE.acquire(blocking=False):
        return False
    hold = ExitStack()
    try:
        if C.plan_external:
            hold.enter_context(plansync.locked(C))
            plansync.pull(C, force=True)
        rel = plan_rel('TODO.md')
        if tid not in open_tasks(branch):
            return True  # blocked, ticked or dropped meanwhile
        if not C.plan_external and (git('status', '--porcelain', '--', rel).stdout.strip() or branch and
                                    git('branch', '--show-current').stdout.strip() != branch):
            return False
        why = '; '.join(parked_reasons(tid)) or 'the ledger has no reason'
        P.block(tid, f'DECIDE: {tid} failed its merge {len(wips)} times (parked as {", ".join(sorted(wips))}): '
                f'merge one by hand, change the task, or drop it; `plan unblock {tid}` starts it again. Why: {why}',
                todo=ROOT / rel, after=[])
        if not commit_plan(f'Plan: block {tid}, parked {len(wips)} times without merging', rel):
            if not C.plan_external:
                git('checkout', '-q', '--', rel)
            return False
        note(f'{tid}: LEFT FOR A HUMAN — parked {len(wips)} times without merging; blocked on a person')
        log(f'{tid}: LEFT FOR A HUMAN — parked {len(wips)} times without merging ({", ".join(sorted(wips))}); '
            f'blocked on a person instead of starting it again')
        seen = parked_seen()
        seen[tid] = sorted(set(seen.get(tid, [])) | set(wips))
        try:
            C.notes('parked-seen.json').write_text(json.dumps(seen, indent=1), encoding='utf-8')
        except OSError as e:
            log(f'{tid}: could not note its parked attempts as seen ({e}); unblocked, it is blocked again')
        return True
    finally:
        hold.close()
        MERGE.release()


STAGED_SAID: set[str] = set()


def blocked_by_edits(tid: str, branch: str) -> bool:
    """The main checkout has uncommitted edits (or new files) to files task/<tid> changes, or anything
    staged (git merges onto no index but HEAD's), or another branch out than `branch`."""
    if git('branch', '--show-current').stdout.strip() != branch:
        return True
    if git('diff', '--cached', '--quiet').returncode:
        if tid not in STAGED_SAID:
            STAGED_SAID.add(tid)
            alarm(f'{tid} is not merging: staged changes in the main checkout',
                  f'they ({ROOT}) block the merge, whatever files they are; commit them or unstage them')
        return True
    STAGED_SAID.discard(tid)
    return bool(edited() & set(git('diff', '--name-only', f'{branch}...task/{tid}').stdout.split()))


def taken() -> dict[str, Path]:
    """Tasks `take` handed to a person's session: {id: its worktree}. The worktree is the claim: while it is
    there, the run starts nothing on the task or its files; once `take --merge` removes it, task/<ID> is
    finished work like a slot's, merged by the run (`sweep_unmerged`) or by `take --merge` itself."""
    return {d.name.removeprefix('take-'): d for d in SLOTS_DIR.glob('take-*') if (d / '.git').exists()}
