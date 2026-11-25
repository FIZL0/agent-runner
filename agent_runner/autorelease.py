"""Auto release (F63, `[run] auto_release`): the run queues a release by itself: once `every` tasks have landed since
the last release, one that starts at once with what has landed (F195a: a cut, as `plan add V --now`), or when it goes
idle with landed work, as `plan add V` with no text does.

The run's settings (ROOT, C) are read from `state` when used, not imported, so `init` reaches this module too."""
from __future__ import annotations

import datetime as dt
import time
from contextlib import ExitStack

from agent_runner import plan as P, plansync, state as S
from agent_runner.state import EV_AUTO_RELEASE, EV_LANDED, EV_PART, MERGE


def releases_on() -> bool:
    """F193: `[run] releases` (Manage releases): does this project manage releases? On before `state.init`."""
    return S.C is None or S.C.run.get('releases', True) is not False


def auto_release_of(v) -> tuple[int, bool]:
    """`[run] auto_release` as (every: tasks landed that queue a release, 0 = not by count; idle: queue one when
    the run goes idle). Anything but a table ({ every = 10 }, { idle = true }, both) is off."""
    if not isinstance(v, dict):
        return 0, False
    every = v.get('every', 0)
    every = every if isinstance(every, int) and not isinstance(every, bool) and every > 0 else 0
    return every, v.get('idle') is True


def landed_since_release(branch: str) -> list[str]:
    """The tasks landed since the last release, oldest first: the ids of the run's landed events (a part
    landing too) after the later of the last release task's landing and the newest version tag on `branch`.
    Release tasks are not counted, and none at all when nothing outside the plan changed since that tag
    (plan-only and release commits)."""
    from agent_runner.land import RELEASE_TAG, _vtuple
    from agent_runner.status import read_events
    git = S.git
    since = ''
    tags = [t for t in git('tag', '--merged', branch).stdout.split() if RELEASE_TAG.match(t)]
    tag = max(tags, key=lambda t: _vtuple(RELEASE_TAG.match(t)[1])) if tags else ''
    if tag:
        when = git('log', '-1', '--format=%cI', tag).stdout.strip()
        try:  # event stamps are local time with no zone
            since = dt.datetime.fromisoformat(when).astimezone().replace(tzinfo=None).isoformat(timespec='seconds')
        except ValueError:
            pass
        plan = S.plan_rel('').rstrip('/')
        spec = ['.'] + ([f':(exclude){plan}'] if plan and not S.C.plan_external and plan != '.' else [])
        if git('diff', '--quiet', tag, branch, '--', *spec).returncode == 0:
            return []
    evs = [e for e in read_events() if e['kind'] in (EV_LANDED, EV_PART) and e.get('id')]
    since = max([since, *(e['time'][:19] for e in evs if P.release(e['id']))])
    out: list[str] = []
    for e in evs:
        if e['time'][:19] > since and not P.release(e['id']) and e['id'] not in out:
            out.append(e['id'])
    return out


AUTO_RELEASE_SEEN = [None]  # events.jsonl's and TODO.md's size and mtime at the last count by `every`: neither changed, no new count
LOOK_AGAIN = 600  # s: a release that stopped the count may have let go with no event (a claim gone stale, a take ended)


def waiting_releases(branch: str, ls: list[str]) -> set[str]:
    """F195a: the open releases in `ls` that only wait in the queue for open tasks (`after: all` say), so a count goes
    on beside them. Not one that may start, is releasing, is taken by a person or another runner, is blocked or held
    (F429), or stands in a section no run starts."""
    from agent_runner import merge, row_hold, sched
    ready = {t[0] for t in sched.tasks(branch)}
    busy = {merge.releasing('', branch), *sched.taken(), *(t for t, cl in plansync.claims(S.C).items() if not plansync.stale(cl)),
            *(q[0] for q in S.queued().values())}
    return {tid for section, box, tid, _, _ in P.iter_tasks(ls) if P.release(tid) and box == ' '
            and not section.startswith(P.SKIPPED)} - ready - busy - row_hold.held_ids(ls)


def auto_release(branch: str, idle: bool = False) -> str:
    """Queue a release that starts at once when `every` tasks have landed since the last release (F195a): an open one
    queued the old way (`P.waiting_default`) is made that release. Or, with `idle` (the run just went idle), one as
    `plan add V` with no text does when anything landed, never while a release task is open. By count, one
    that only waits in the queue (`waiting_releases`) is no hindrance; any other open one is. Never with `[run] releases` off (F193).
    Committed in the main checkout as `loop.watch_issues` commits its tasks. The id queued, or ''."""
    C, git, rel = S.C, S.git, S.plan_rel('TODO.md')
    every, on_idle = auto_release_of(C.run.get('auto_release', False))
    if not releases_on() or not every and not (idle and on_idle):
        return ''
    if not idle:  # the every-tick look: only after a landing, or a change to TODO.md (a release dropped), or LOOK_AGAIN later
        mark = [int(time.time() // LOOK_AGAIN)]
        for f in (C.notes('events.jsonl'), S.ROOT / rel):
            try:
                st = f.stat()
                mark += [st.st_size, st.st_mtime]
            except OSError:
                mark += [None, None]
        if mark == AUTO_RELEASE_SEEN[0]:
            return ''
        AUTO_RELEASE_SEEN[0] = mark
    if not MERGE.acquire(blocking=False):
        AUTO_RELEASE_SEEN[0] = None  # look again next tick
        return ''
    hold = ExitStack()
    try:
        if C.plan_external:
            hold.enter_context(plansync.locked(C))
            plansync.pull(C, force=True)
        ls = P.lines(S.ROOT / rel)
        open_ = {t for t in P.open_ids(ls) if P.release(t)}
        if open_ and not every:
            return ''
        waits = waiting_releases(branch, ls) if open_ else set()
        if open_ - waits:
            return ''
        landed = landed_since_release(branch)
        cut = bool(every) and len(landed) >= every
        why = f'{len(landed)} landed' if cut else 'idle' if idle and on_idle and landed and not open_ else ''
        if not why:
            return ''
        if git('branch', '--show-current').stdout.strip() != branch or \
                git('status', '--porcelain', '--', S.plan_rel('')).stdout.strip():
            AUTO_RELEASE_SEEN[0] = None
            return ''
        if cut:
            from agent_runner.status import read_events
            queued = {e.get('id') for e in read_events() if e['kind'] == EV_AUTO_RELEASE} if waits else ()
            tid = P.cut_release(P.waiting_default(ls, waits, queued), todo=S.ROOT / rel)
        else:
            tid = P.add_release(todo=S.ROOT / rel)
        if not S.commit_plan(f'Plan: {tid}, auto release ({why})', rel):
            git('checkout', '-q', '--', rel)
            AUTO_RELEASE_SEEN[0] = None
            return ''
        S.log(f'queued {tid} (auto_release: {why})', EV_AUTO_RELEASE, tid, why=why)
        return tid
    finally:
        hold.close()
        MERGE.release()
