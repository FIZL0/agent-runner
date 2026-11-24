"""Auto release (F63, `[run] auto_release`): the run queues a release by itself, as `plan add V` with no text
does, once `every` tasks have landed since the last release, or when it goes idle with landed work.

The run's settings (ROOT, C) are read from `state` when used, not imported, so `init` reaches this module too."""
from __future__ import annotations

import datetime as dt
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


def auto_release(branch: str, idle: bool = False) -> str:
    """Queue a release, as `plan add V` with no text does, when `every` tasks have landed since the last
    release, or with `idle` (the run just went idle) when anything landed. Never while a release task is open, nor with `[run] releases` off (F193).
    Committed in the main checkout as `loop.watch_issues` commits its tasks. The id queued, or ''."""
    C, git, rel = S.C, S.git, S.plan_rel('TODO.md')
    every, on_idle = auto_release_of(C.run.get('auto_release', False))
    if not releases_on() or not every and not (idle and on_idle):
        return ''
    if not idle:  # the every-tick look: only after a landing, or a change to TODO.md (a release dropped)
        mark = []
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
        if P.open_release(P.lines(S.ROOT / rel)):
            return ''
        landed = landed_since_release(branch)
        why = f'{len(landed)} landed' if every and len(landed) >= every else 'idle' if idle and on_idle and landed else ''
        if not why:
            return ''
        if git('branch', '--show-current').stdout.strip() != branch or \
                git('status', '--porcelain', '--', S.plan_rel('')).stdout.strip():
            AUTO_RELEASE_SEEN[0] = None
            return ''
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
