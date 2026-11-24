"""Picking the next task: the open tasks in order, what clashes with what is running (files, sections,
siblings), claims other runners hold, and tasks parked too often."""

from __future__ import annotations

import json
import re
import threading
import time
from contextlib import ExitStack
from pathlib import Path
from typing import NamedTuple

from agent_runner import plan as P, plansync, shared_tools, stack
from agent_runner.state import (alarm, C, commit_plan, edited, FETCHED, git, log, MERGE, note, plan_rel, plan_text,
    queued, ROOT, SLOTS_DIR)
from agent_runner.state import EV_LEFT


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
    # B107: an `after: all` release passes over a task taken by hand or claimed by another runner (live claims),
    # as over a needs-you one: its work lands in the next release
    me = plansync.owner(C)
    away = set(taken()) | {t for t, cl in plansync.claims(C).items() if cl.owner != me and not plansync.stale(cl)}
    first = parents_first(ls, open_ids)
    later = {k for kids in first.values() for k in kids}
    out = []
    for section, box, tid, _, i in P.iter_tasks(ls):
        if box != ' ' or section.startswith(P.SKIPPED) or tid in later:
            continue
        l = ls[i]
        f = P.fields(l)
        if {P.LAST, P.ALL} & set(f.get('after', [])):  # `all above` (F43), `all` (F35): afresh on every pick
            f['after'] = P.waits_on(ls, i)
            named = set(P.fields(l).get('after', []))
            if P.release(tid) and P.ALL in named:  # B107: taken by hand, its work lands in the next release
                f['after'] = [a for a in f['after'] if a not in away or a in named]
        # a split parent: its subtasks run first, blocked ones included, then it runs (or `archive` ticks it).
        # Read by id and by its `(split into …)` list, never by the words alone, so prose that happens to say
        # "split into" is not taken for a split
        if tid not in first and P.subtasks(tid, l, open_ids):
            continue
        after = set(f.get('after', [])) - {tid}
        if after & open_ids:
            continue
        out.append((tid, section, set(f.get('files', [])), after))
    return by_waiters(ls, out)


def parents_first(ls: list[str], open_ids: set[str]) -> dict[str, set[str]]:
    """B185: {task: its open subtasks} for each task not done that goes before them: its session filed them, then
    failed (it has a wip/<ID>) with its first part, which they build on, not landed. Not one that says `(split
    into …)`: its subtasks are all its work. Nor one no run starts (Stretch, Parked), nor one that waits on a
    subtask itself, so neither waits for the other for ever. Blocked, it still holds them."""
    kids = {tid: k for section, box, tid, _, i in P.iter_tasks(ls)
            if box != 'x' and not section.startswith(P.SKIPPED) and not P.SPLIT.search(ls[i])
            and (k := P.subtasks(tid, ls[i], open_ids))}
    if not kids:
        return {}
    waits = {}
    for _, box, tid, _, i in P.iter_tasks(ls):
        if box != 'x':
            waits[tid] = set(P.waits_on(ls, i))
            if box == '~':  # and a block's `(after X)`
                waits[tid] |= {t for a in P.WAITS.findall('\n'.join(P._item_block(ls, i))) for t in P.TASK_ID.findall(a)}
    out = {}
    for tid, k in kids.items():
        if not wip_of(tid):
            continue
        seen, todo = set(), [tid]
        while todo:  # everything it waits on, down the whole chain
            new = waits.get(todo.pop(), set()) - seen
            seen |= new
            todo += new
        if not k & seen:
            out[tid] = k
            for t in k:  # held from here on: a later parent waiting on one of these waits on `tid` too
                waits.setdefault(t, set()).add(tid)
    return out


def wip_of(tid: str) -> bool:
    """An earlier attempt at `tid` is on wip/<ID> (or wip/<ID>-N), counted to PARK_LIMIT or not, here or pushed by
    another machine's run."""
    return bool(git('for-each-ref', '--format=%(refname)', *(f'{at}/wip/{tid}{n}' for at in (
        'refs/heads', 'refs/remotes/*') for n in ('', '-*'))).stdout.strip())


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
    ids = [r.removeprefix('refs/heads/task/') for r in refs]
    return [t for t in ids if stack.has_own(t, branch)]  # F198: not for the merge it was started on alone


def family(tid: str) -> str:
    """L3a, L3b, L3 -> L3; A11k4 -> A11. Which of one family may run side by side: `kin_clash`."""
    m = re.match(r'[A-Za-z]*\d*', tid)
    return m.group() if m else tid


def kin_clash(t: tuple, b: tuple, shared: set[str]) -> bool:
    """F199: `t` and busy `b` are of one family and may not run side by side. Parts of one split task may, when
    both lines name `files:` (a busy tuple's `b[5]`: `b[4]` is empty for a finished task) that do not meet, and
    neither waits for the other. A task and its own part (P13 and P13a) never do."""
    if family(t[0]) != family(b[0]):
        return False
    if t[0] == b[0] or P.child(t[0], b[0]) or P.child(b[0], t[0]):
        return True
    if not t[2] or not b[5 if len(b) > 5 else 4 if len(b) > 4 else 2]:
        return True
    return b[0] in t[3] or t[0] in b[3] or bool(file_overlap(t[2], b, shared))


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


def clash(t: tuple, b: tuple, shared: set[str], alone: frozenset = frozenset()) -> bool:
    """Task `t` may not run beside `b` (running here, waiting to merge, or claimed by another runner): siblings
    that must stay apart (`kin_clash`), a shared ordered section, or overlapping files (`shared_files` aside; see `file_overlap`). A release (kind V)
    clashes like any other task: it starts once what it waits for (`after:`) has landed, beside running tasks,
    and tasks start beside it; while it is busy the merge holds every other merge (`merge.hold_for_release`,
    F99), so it still releases exactly what was on the shared branch when it started. A task tagged `(alone)`
    (its id in `alone`, F130; a release or any other) clashes with everything, either way round: it starts only
    when nothing else runs or waits to merge, and nothing starts beside it; `holds` then lets it pass over a task
    taken by hand or claimed by another runner (`passes`, B107): only this run's tasks hold it."""
    tid, section, files, _ = t
    if kin_clash(t, b, shared):
        return True
    if tid in alone or b[0] in alone:  # F130: it runs alone
        return True
    return (ordered(section) and section == b[1]) or bool(file_overlap(files, b, shared))


def clash_why(t: tuple, b: tuple, shared: set, alone: frozenset = frozenset()) -> tuple[str, str]:
    """Why `clash(t, b)`: (the kind of wait, what holds it), for the dry run."""
    if kin_clash(t, b, shared):
        return 'waiting for a sibling', b[0]
    if t[0] in alone:
        return 'runs alone', f'{b[0]} is running or waiting to merge in this run'
    if b[0] in alone:
        return 'runs alone', f'{b[0]} runs alone'
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
    as a task running here, so what clashes with it waits for it too. A task parked
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
    `finished` (mine and another runner's), `parked` ({tid: its parked branches}), `shared` (shared_files) and
    `away` (taken by hand or claimed by another runner: not this run's, so no release waits for them, B107)."""
    todo: list
    busy: list
    busy_ids: set
    mine: set
    finished: set
    parked: dict
    shared: set
    away: frozenset = frozenset()  # B107: busy ids that hold no release: taken by hand, claimed by another runner
    live: frozenset = frozenset()  # B126: the tasks in this run's slots (a running one may be in `mine` too)
    critical: frozenset = frozenset()  # B126: open tasks tagged `(follow-up, critical)` or in a Critical section
    alone: frozenset = frozenset()  # F130: tasks tagged `(alone)`, whatever their box: they run alone
    needs: dict = {}  # F168: {task: the shared tools it needs}
    users: dict = {}  # F168: {shared tool: the task running here that has it}
    splits: dict = {}  # B196: {task held for its author to split it: seconds left}
    waits: dict = {}  # F168: {task that gave up its slot: (its tool, since when)}, longest first


def held(running: dict, branch: str) -> Held:
    """The Held for `branch` with `running` ({slot: task}) in the slots."""
    shared = set(C.run['shared_files'])
    todo = tasks(branch)
    busy = claimed_elsewhere(plansync.claims(C), todo)  # [] with no remote to claim through
    away = frozenset(b[0] for b in busy) | frozenset(taken())
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
        busy.append((tid, t[1], files if done_ else set(t[2]) | files, t[3], set() if done_ else set(t[2]),
                     set(t[2])))  # F199: what its line names, finished or not
    busy_ids |= {b[0] for b in busy if b[0] not in mine}
    parked = parked_attempts() if todo else {}
    return Held(todo, busy, busy_ids, mine, finished, parked, shared, away, frozenset(live),
                critical_tasks(branch) if todo else frozenset(),
                P.alone_ids(plan_text(branch)) if todo else frozenset(),
                splits=split_holds(branch) if todo else {}, **tool_fields(todo, live, branch))


def split_holds(branch: str) -> dict[str, float]:
    """B196: {open task its author is splitting: the seconds it is still held}."""
    ls = plan_text(branch)
    return {tid: left for _, box, tid, _, i in P.iter_tasks(ls) if box == ' ' and (left := P.split_left(ls[i]))}


def splitting(tried: set, branch: str) -> bool:
    """A task no run has tried starts by itself once its author has split it, or had the time to: the run is not
    idle."""
    held_ = split_holds(branch).keys() - tried - taken().keys()
    return bool(held_) and any(t[0] in held_ for t in tasks(branch))


def tool_fields(todo: list, live: set, branch: str) -> dict:
    """F168: Held's `needs`, `users` and `waits`; nothing without shared tools or a wait for memory (B184)."""
    if not shared_tools.specs(C) and not shared_tools.parked():
        return {}
    ls, open_ = plan_text(branch), {t[0] for t in todo}
    waits = {t: (w['tool'], w.get('at', 0)) for t, w in shared_tools.parked().items()
             if t in open_ and (w['tool'] in shared_tools.specs(C) or w['tool'] == shared_tools.MEMORY)}
    needs = {tid: n for _, _, tid, _, i in P.iter_tasks(ls) if (n := shared_tools.needs_of(ls[i], C))}
    for t, (tool, _) in waits.items():
        needs[t] = list(dict.fromkeys([tool, *needs.get(t, [])]))
    users = {}
    for t in live | {q[0] for q in queued().values()}:
        for tool in [*needs.get(t, []), *([x] if (x := shared_tools.holding(t)) else [])]:
            users[tool] = t
    return {'needs': needs, 'users': users, 'waits': waits}


def tool_hold(t: tuple, tried: set, h: Held) -> tuple[str, str] | None:
    """F168: the shared tool task `t` waits for, as (tool, why): one a running task has, or that is busy or missing, or
    that a task which gave up its slot for it earlier takes first."""
    tid = t[0]
    if not (need := h.needs.get(tid)):
        return None
    since = h.waits[tid][1] if tid in h.waits else float('inf')
    first = {}
    for w, (tool, at) in h.waits.items():
        if w != tid and at < since and w not in tried and len(h.parked.get(w, [])) < PARK_LIMIT:
            first.setdefault(tool, w)
    return shared_tools.hold(tid, need, h.users, first)


def critical_tasks(branch: str) -> frozenset:
    """Ids of the open tasks of level critical in `branch`'s TODO.md: tagged `(follow-up, critical)`, or under a
    heading that says critical (a plan's own Critical section)."""
    return frozenset(tid for section, box, tid, rest, _ in P.iter_tasks(plan_text(branch))
                     if box == ' ' and ('critical' in section.lower() or
                                        (m := P.PRI_TAG.search(rest)) and m.group(1) == 'critical'))


def holds(t: tuple, tried: set, h: Held) -> tuple[str, tuple | None] | None:
    """Why open task `t` may not start now, first reason only: ('finished', None), ('tried', None),
    ('busy', None), ('parked', None), ('split', None) (its author is splitting it: B196), ('merging', None) (a release, while a merge holds the turn: F99),
    ('unpushed', None) (a release, while landed changes wait for a person's approval: F98),
    ('clash', the busy task it clashes with), or ('tool', (the shared tool it waits for, why)) (F168); None when it is free. A critical task never holds a slot
    for itself (B140): `choose` only tries it first; but see `turn_of` (F208) for an `(alone)` one."""
    tid = t[0]
    if tid not in h.busy_ids and tid in h.finished:
        return 'finished', None  # its branch is waiting to be merged: restarting it would reset the branch
    if tid in tried:
        return 'tried', None
    if tid in h.busy_ids:
        return 'busy', None
    if len(h.parked.get(tid, [])) >= PARK_LIMIT:  # B32: failed its merge that often; a person decides
        return 'parked', None
    if tid in h.splits:  # B196
        return 'split', None
    if P.release(tid) and MERGE.locked():  # F99: a merge under way lands first, so the release starts from it
        return 'merging', None
    if P.release(tid) and unpushed():  # F98: a release waits until everything before it is approved and pushed
        return 'unpushed', None
    if b := clash_or_stack(t, h)[0]:
        return 'clash', b  # a running or merge-waiting task's sibling, ordered-section mate or file neighbour
    if w := tool_hold(t, tried, h):
        return 'tool', w
    return None


def clash_or_stack(t: tuple, h: Held) -> tuple[tuple | None, dict]:
    """(the busy task that holds `t`, {}), or (None, the merge `t` may start on, {} for none needed). F198: a `t` that
    clashes by files alone, and only with finished tasks all in one merge under way (under test, or built ahead on
    that one), starts on that merge instead of waiting for it to land."""
    clashing = (b for b in h.busy if clash(t, b, h.shared, h.alone) and not passes(t, b, h))
    if not (first := next(clashing, None)):
        return None, {}
    from agent_runner.merge import under_way  # merge reads sched; imported here, not at the top
    if not (merges := under_way()) or t[0] in h.alone or P.release(t[0]) or ordered(t[1]):
        return first, {}
    bs = [first, *clashing]
    for b in bs:
        by_files = family(t[0]) != family(b[0])
        done_ = b[0] in h.mine and b[0] not in h.busy_ids | h.live | h.away | h.alone and not P.release(b[0])
        if not (by_files and done_):
            return b, {}
    if git('for-each-ref', f'refs/heads/asked/{t[0]}', f'refs/heads/waiting/{t[0]}').stdout.strip():
        return first, {}  # its session goes on with the work it has, on the commit it began on
    ids = {b[0] for b in bs}
    for m in merges:
        if ids <= set(m['tids']) and not any(
                git('merge-base', '--is-ancestor', f'refs/heads/task/{x}', m['on']).returncode for x in ids):
            return None, m
    return first, {}


def turn_of(tried: set, h: Held, branch: str) -> str:
    """F208: the critical `(alone)` task whose turn is next, else '': this run's tasks are all that hold it, and each
    will end by itself. Until they have and it has started, `choose` starts only critical tasks (not even one that
    goes on after a wait for a shared tool). Other `(alone)` tasks hold no start:
    they wait for an empty run, as they queue."""
    for t in h.todo:
        if t[0] not in h.alone or t[0] not in h.critical:
            continue
        if (holds(t, tried, h._replace(busy=[], users={})) or ('merging',))[0] != 'merging':
            continue  # more than running and merging tasks holds it
        bs = [b for b in h.busy if clash(t, b, h.shared, h.alone) and not passes(t, b, h)]
        if all(ends(b[0], h, branch) for b in bs):
            return t[0]
    return ''


def ends(tid: str, h: Held, branch: str) -> bool:
    """F208: busy task `tid` ends with nobody's help: it runs in a slot, or its merge is to come. Not one taken by hand
    or of another runner, one that waits for a usage reset, nor a finished branch that waits for a person: a
    closed task's, one checked out elsewhere, one held by edits in the main checkout, or one whose merge crashed."""
    if tid in h.away:
        return False
    if tid in h.live:
        return True
    if tid in h.busy_ids or tid not in open_tasks(branch) | blocked_tasks(branch):
        return False  # queued to resume; or no run merges it (`slots.unmerged`)
    from agent_runner import loop  # loop reads sched; imported here, not at the top
    if not any(x.name == f'merge:{tid}' for x in threading.enumerate()):
        if tid in loop.SWEPT:
            return False  # its merge crashed, or waits for the next run: a sweep tries once
        for wt in git('worktree', 'list', '--porcelain').stdout.split('\n\n'):
            at = Path(wt.partition('\n')[0].removeprefix('worktree '))
            if f'branch refs/heads/task/{tid}' in wt.splitlines() and SLOTS_DIR.resolve() not in at.resolve().parents:
                return False  # checked out in a person's worktree: no sweep merges it
    if git('diff', '--cached', '--quiet').returncode:
        return False  # `blocked_by_edits`' first checks, without its alarm
    return not blocked_by_edits(tid, branch)


def unpushed() -> int:
    """F98: how many landed changes `[run] approve` holds back from the push remote."""
    from agent_runner import pitch
    return len(pitch.unpushed()) if pitch.on() else 0


def passes(t: tuple, b: tuple, h: Held) -> bool:
    """Release `t` passes over busy task `b`, taken by hand or claimed by another runner (B107): a release waits only
    for this run's running and merge-waiting tasks, and `b`'s work lands after, in the next release. A task
    tagged `(alone)` (F130) passes over such a `b` too, as a release did under the old release_alone. A busy `b`
    tagged `(alone)` still holds everything (it runs alone)."""
    if b[0] not in h.away or b[0] in h.alone:
        return False
    return P.release(t[0]) and not P.release(b[0]) or t[0] in h.alone


def passed_over(t: tuple, h: Held) -> list[str]:
    """The busy tasks release `t` does not wait for (`passes`), in order: what explain says of a free release."""
    return list(dict.fromkeys(b[0] for b in h.busy if b[0] != t[0] and passes(t, b, h)))


def parked_now(tried: set, h: Held) -> list[str]:
    """The open tasks held back only for being parked PARK_LIMIT times: the ones `pick` blocks on a person."""
    return [t[0] for t in h.todo if holds(t, tried, h) == ('parked', None)]


def explain(running: dict, tried: set, branch: str) -> dict[str, tuple[str, str]]:
    """The dry run: every open task's reason it does not start, as {tid: (kind, detail)}; ('free', '') for one
    that may. Changes nothing."""
    h = held(running, branch)
    claimed = {t: cl.who for t, cl in plansync.claims(C).items()}
    why = {}
    turn = turn_of(tried, h, branch)
    for t in h.todo:
        tid = t[0]
        kind, b = holds(t, tried, h) or ('free', None)
        if kind == 'finished':
            why[tid] = ('claimed by another runner', claimed.get(tid, '')) if tid not in h.mine else \
                ('finished, waiting to merge', releasing_note(tid, branch))
        elif kind == 'tried':
            why[tid] = ('tried this run', '')
        elif kind == 'busy':
            why[tid] = ('running', f'claimed by {claimed[tid]}' if tid in claimed else
                        'taken by hand (`take`)' if tid in taken() else '')
        elif kind == 'parked':
            why[tid] = (f'parked {len(h.parked[tid])} times, needs a person', ', '.join(sorted(h.parked[tid])))
        elif kind == 'split':
            why[tid] = ('waiting to be split', P.split_in(h.splits[tid]))
        elif kind == 'merging':
            why[tid] = ('waiting for a merge to land', 'a release starts from what has landed')
        elif kind == 'unpushed':
            why[tid] = ('waiting for your approval', f'{unpushed()} of what landed is not pushed yet')
        elif kind == 'clash':
            why[tid] = clash_why(t, b, h.shared, h.alone)
        elif kind == 'tool':
            why[tid] = (f'waiting for {shared_tools.label(b[0], C)}', b[1])
        elif turn and tid not in h.critical:
            why[tid] = ('runs alone', f'{turn} runs alone next')
        elif (P.release(tid) or tid in h.alone) and (over := passed_over(t, h)):
            why[tid] = ('free', away_note(over, set(claimed)))
        else:
            why[tid] = ('free', '')
    return why


def releasing_note(tid: str, branch: str) -> str:
    """'V10 is releasing' when a busy release holds the merge of finished task `tid` (F99), else ''."""
    from agent_runner.merge import releasing  # merge reads sched; imported here, not at the top
    return f'{v} is releasing' if (v := releasing(tid, branch)) else ''


def away_note(ids, claimed: set) -> str:
    """'not waiting on R67 (taken by hand), F9 (claimed by another runner)': what a release passes over (B107)."""
    return 'not waiting on ' + ', '.join(
        f'{t} ({"claimed by another runner" if t in claimed else "taken by hand"})' for t in ids)


def choose(h: Held, tried: set, branch: str, claim: bool = False):
    """The first open task nothing holds back (`holds`), claimed first when `claim` (see `claim_task`), or None.
    Parked tasks are skipped, not blocked: that is `pick`'s part. Critical tasks are tried first, wherever their
    lines stand (B126): one whose blocker has just landed takes the next free slot ahead of the normal ones. One
    still blocked holds nothing back (B140): the free slot goes to the next task that may start. A task that gave up
    its slot for a shared tool goes ahead of them all, the longest wait first (F168), but for this: while a critical `(alone)` task
    waits for its turn, only critical tasks start (F208, `turn_of`)."""
    turn = turn_of(tried, h, branch)
    for t in sorted(h.todo, key=lambda t: (h.waits[t[0]][1] if t[0] in h.waits else float('inf'),
                                           t[0] not in h.critical)):
        if turn and t[0] not in h.critical or holds(t, tried, h):
            continue
        tid = t[0]
        if claim and tid in h.needs and not shared_tools.ready(tid, h.needs[tid]):
            continue  # F168: checked once more, so no stale answer starts it
        b, on = clash_or_stack(t, h)
        if b:
            continue  # the merge it would have started on has just ended
        if got := claim_task(t, h, branch) if claim else t:
            PASSED.discard(tid)
            if claim:
                stack.CHOSEN.pop(tid, None)
                if on:
                    stack.CHOSEN[tid] = on
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
        if mine and (cl.since, cl.owner) < (mine.since, mine.owner) and clash(t, b, h.shared, h.alone) \
                and not P.release(t[0]) and not passes(t, b, h):  # B107: a release does not wait for another runner's task
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
    out = set(git('diff', '--name-only', f'{stack.fork(tid, branch)}...task/{tid}').stdout.split())
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
    keep = set(slots) | set(ahead(branch)) | {q[0] for q in queued().values()} | set(shared_tools.parked())  # queued: waiting to resume
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


def forgive_park(tid: str, wip: str) -> None:
    """F19: a branch parked for a restyle is no failed merge: noted as seen, so it never counts to PARK_LIMIT."""
    seen = parked_seen()
    seen[tid] = sorted(set(seen.get(tid, [])) | {wip})
    try:
        C.notes('parked-seen.json').write_text(json.dumps(seen, indent=1), encoding='utf-8')
    except OSError as e:
        log(f'{tid}: could not note {wip} as a restyle park ({e}); it may count as a failed merge')


def note_committed(tid: str, text: str, msg: str, timeout: float = 600) -> bool:
    """Note `text` on task `tid` in the plan and commit it, as `block_parked` does (MERGE held, TODO.md clean).
    False when it could not be done (the task is gone, the plan has edits, the commit failed)."""
    if not MERGE.acquire(timeout=timeout):
        return False
    hold = ExitStack()
    try:
        if C.plan_external:
            hold.enter_context(plansync.locked(C))
            plansync.pull(C, force=True)
        rel = plan_rel('TODO.md')
        if not C.plan_external and git('status', '--porcelain', '--', rel).stdout.strip():
            return False
        try:
            P.note(tid, text, todo=ROOT / rel)
        except SystemExit:
            return False  # ticked or dropped meanwhile
        if not commit_plan(msg, rel):
            if not C.plan_external:
                git('checkout', '-q', '--', rel)
            return False
        return True
    finally:
        hold.close()


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
            f'blocked on a person instead of starting it again', EV_LEFT, tid,
            why=f'parked {len(wips)} times without merging ({", ".join(sorted(wips))})')
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
