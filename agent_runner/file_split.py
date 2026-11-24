"""File split (F200b, `[run] split_files`): when free slots start nothing because ready tasks wait for one file, the run
queues a critical (alone) task that splits that file, and its test, by area.

The run's settings (ROOT, C) are read from `state` when used, not imported, so `init` reaches this module too."""
from __future__ import annotations

import fnmatch
import posixpath
import re
import time
from contextlib import ExitStack

from agent_runner import ci, plan as P, plansync, sched, state as S
from agent_runner.done import docs_only
from agent_runner.state import EV_FILE_SPLIT, MERGE

WAITERS = 3  # ready tasks that wait for one file before it is split
LOOK_EVERY = 60  # seconds between looks: every free slot's pick of every tick asks
LOOKED = [0.0]

LOCKS = ('*.lock', '*.lockb', '*.lockfile', '*-lock.json', '*-lock.yaml', '*-lock.yml', 'npm-shrinkwrap.json', 'go.sum',
         'Package.resolved', 'pubspec.lock')
DOCS = ('*.md', '*.rst', '*.adoc', 'docs/*')
MADE = ('*.min.js', '*.min.css', '*.map', '*_pb2.py', '*_pb2_grpc.py', '*.pb.go', '*.g.dart', '*.generated.*',
        '*.gen.*', 'generated/*', '*/generated/*', '__generated__/*', '*/__generated__/*')
MADE_HEAD = re.compile(r'@generated\b|\bdo not edit\b|\bauto[- ]?generated\b|\bthis file (?:is|was) generated\b', re.I)


def waiting_for(h: sched.Held, tried: set, tracked: set[str]) -> dict[str, list[str]]:
    """{file: the ready tasks that wait for it}, for the tasks of `h` that only files hold back. {} when a task may
    start: then the slot is not free for want of a file."""
    out: dict[str, list[str]] = {}
    for t in h.todo:
        why = sched.holds(t, tried, h)
        if why is None:
            return {}
        if why[0] != 'clash':
            continue
        files: set[str] = set()
        for b in h.busy:
            if not sched.clash(t, b, h.shared, h.alone) or sched.passes(t, b, h):
                continue
            if sched.clash_why(t, b, h.shared, h.alone)[0] != 'waiting for files':
                files = set()  # it waits for this one whatever its files are: a split would not free it
                break
            for e in sched.file_overlap(t[2], b, h.shared):
                if sched.whole_dir(e):
                    continue  # it meets only another such glob: no one file holds the task
                hits = {e} if '*' not in e else P.overlap({f for f in b[2] if '*' not in f}, {e})
                files |= {p for f in hits if (p := path_of(f, tracked))}
        for f in files:
            out.setdefault(f, []).append(t[0])
    return out


def path_of(f: str, tracked: set[str]) -> str:
    """The tracked file a `files:` entry names: itself, or the one path it is the tail of ('' for none or several)."""
    if f in tracked:
        return f
    tails = [p for p in tracked if p.endswith('/' + f)]
    return tails[0] if len(tails) == 1 else ''


def unsplittable(f: str, branch: str) -> bool:
    """`f` is never split: a shared, lock, docs, plan or generated file (or one that is not text), or a name a
    `files:` list cannot hold."""
    c = S.C
    if re.search(r'[\s,`|*]', f) or P.overlap({f}, set(c.run['shared_files'])):
        return True
    name = posixpath.basename(f)
    if any(fnmatch.fnmatch(name, g) for g in LOCKS) or any(fnmatch.fnmatch(f, g) for g in DOCS + MADE):
        return True
    if docs_only([f], c.run['docs_files']):
        return True
    plan = S.plan_rel('').rstrip('/')
    if not c.plan_external and plan not in ('', '.') and f.startswith(plan + '/'):
        return True
    attr = S.git('check-attr', 'linguist-generated', '--', f).stdout.strip().rsplit(': ', 1)[-1]
    if attr in ('set', 'true'):
        return True
    text = S.git('show', f'{branch}:{f}').stdout
    return '\0' in text or bool(MADE_HEAD.search('\n'.join(text.splitlines()[:5])))


def tests_of(f: str, tracked: set[str]) -> list[str]:
    """The test files named after `f` (test_x.py, x_test.go, x.test.ts, XTests.swift); [] when `f` is one."""
    stem, ext = posixpath.splitext(posixpath.basename(f))
    names = {n + ext for n in (f'test_{stem}', f'{stem}_test', f'{stem}.test', f'{stem}.spec', f'{stem}_spec',
                               f'{stem}Test', f'{stem}Tests')}
    return sorted(p for p in tracked if posixpath.basename(p) in names)[:3]


def key_of(f: str) -> str:
    return f'Split `{f}` by area'


def seen(f: str) -> bool:
    """A split of `f` is open (blocked too), or one was queued within `ci.REPEAT_DAYS` days. Read off the plan, so
    every machine's run sees it."""
    key = key_of(f)
    if any(box != 'x' and key in rest for _, box, _, rest, _ in P.iter_tasks(P.lines(S.ROOT / S.plan_rel('TODO.md')))):
        return True
    done = P.lines(S.ROOT / S.plan_rel('DONE.md')) + P.lines(S.ROOT / S.plan_rel('TODO.md'))
    return bool(ci.closed_repeats(done, key))


def task_text(f: str, waiters: list[str], tests: list[str]) -> str:
    """The split task's line, its fields included."""
    also = f' and its test ({", ".join(f"`{t}`" for t in tests)})' if tests else ' and its test, if it has one,'
    return (f'{key_of(f)}: {len(waiters)} ready tasks waited for it ({", ".join(waiters[:8])}'
            f'{", …" if len(waiters) > 8 else ""}) while slots were free. Move its areas{also} into files of their own, '
            'by what the open tasks change, with no behaviour change. Then narrow the open tasks\' files: '
            '`plan edit <ID> --files …` on each that names it, to the new files it needs. Check: the gate passes. '
            f'{ci.filed_stamp()} | files: {", ".join([f, *tests])}')


def kind() -> str:
    k = S.C.raw['plan'].get('kinds') or P.KINDS
    return 'C' if 'C' in k else next((p for p in k if p not in ('K', P.RELEASE)), 'C')


def queue_file_split(running: dict, tried: set, branch: str, force: bool = False) -> str:
    """Queue one file split when the slot that is free now has nothing to start for want of a file; the id, or ''.
    Committed in the main checkout as `loop.watch_issues` commits its tasks, only when MERGE is free."""
    if S.C.run['split_files'] is not True or not force and time.time() - LOOKED[0] < LOOK_EVERY:
        return ''
    LOOKED[0] = time.time()
    tracked = set(S.git('-c', 'core.quotePath=false', 'ls-tree', '-r', '--name-only', branch).stdout.splitlines())
    waits = {f: ids for f, ids in waiting_for(sched.held(running, branch), tried, tracked).items() if len(ids) >= WAITERS}
    waits = {f: ids for f, ids in waits.items() if not unsplittable(f, branch)}
    if not waits or not MERGE.acquire(blocking=False):
        return ''
    hold = ExitStack()
    try:
        rel = S.plan_rel('TODO.md')
        if S.C.plan_external:
            hold.enter_context(plansync.locked(S.C))
            plansync.pull(S.C, force=True)
        elif S.git('branch', '--show-current').stdout.strip() != branch or \
                S.git('status', '--porcelain', '--', S.plan_rel('')).stdout.strip():
            return ''
        for f in sorted(waits, key=lambda f: (-len(waits[f]), f)):
            if seen(f):
                continue
            ids = waits[f]
            tid = P.add(kind(), task_text(f, ids, tests_of(f, tracked)), todo=S.ROOT / rel, pri='critical', alone_=True)
            if not S.commit_plan(f'Plan: {tid}, split {f}', rel):
                S.git('checkout', '-q', '--', rel)
                return ''
            S.log(f'queued {tid} to split {f}: {len(ids)} ready tasks wait for it ({", ".join(ids)})', EV_FILE_SPLIT,
                  tid, file=f, waiters=len(ids))
            return tid
        return ''
    finally:
        hold.close()
        MERGE.release()
