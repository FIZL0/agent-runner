"""F429a: releases moved and removed by the person.

A moved release waits for the tasks above its new place (`after: all`). One that is the next cut carries the field
`| moved: yes`, so the automatic count neither cuts it early nor queues another beside it
(`autorelease.waiting_releases`); the count goes on once it has landed. A removed automatic release skips that cut:
the count starts from the removal (`skipped_at`). The Next release row, which is no task, is named NEXT in
`plan hold`, `unhold`, `move`, `drop` and `restore`. Its hold and the removals are run events, beside the landings
they are counted with."""
from __future__ import annotations

import datetime as dt
import json
from typing import NamedTuple

from agent_runner import plan as P, state as S

NEXT = 'next-release'  # the Next release row's name in the plan commands
KEY = 'moved'  # the field of a moved release that is the next cut
EV_CUT_REMOVED = 'cut removed'    # the cut `id` (a release task, or NEXT) was removed
EV_CUT_RESTORED = 'cut restored'  # and is back
EV_CUT_HELD = 'cut held'          # NEXT is held
EV_CUT_UNHELD = 'cut unheld'      # and no more


def is_moved(line: str) -> bool:
    """Is this task line a moved release that is the next cut?"""
    return KEY in P.fields(line)


def cleared(line: str) -> str:
    """The task line without the field."""
    return P.FIELD.sub(lambda m: '' if m.group(1) == KEY else m.group(0), line)


def moved_ids(ls: list[str]) -> set[str]:
    """The moved releases in TODO.md's lines `ls` that are the next cut and not done."""
    return {tid for _, box, tid, _, i in P.iter_tasks(ls) if P.release(tid) and box in ' ~' and is_moved(ls[i])}


# --- the run events ------------------------------------------------------------

class Cuts(NamedTuple):
    """What the run events say of the cuts: `held` (NEXT is), `skips` ([(id, its stamp, NEXT was held)], the removals
    that stand, oldest first)."""
    held: bool
    skips: list


def cuts() -> Cuts:
    """`Cuts` now."""
    from agent_runner.status import read_events
    held, skips = False, []
    for e in read_events():
        kind, tid = e['kind'], e.get('id')
        if kind in (EV_CUT_HELD, EV_CUT_UNHELD):
            held = kind == EV_CUT_HELD
        elif kind == EV_CUT_REMOVED:
            skips.append((tid, e['time'][:19], held))
            if tid == NEXT:
                held = False  # the hold was that cut's
        elif kind == EV_CUT_RESTORED:
            if at := [k for k, s in enumerate(skips) if s[0] == tid]:
                was = skips.pop(at[-1])
                if tid == NEXT:
                    held = was[2]
    return Cuts(held, skips)


def skipped_at() -> str:
    """When the newest removal that stands was made, '' for none: only what landed after it counts."""
    return max((s[1] for s in cuts().skips), default='')


def automatic(tid: str) -> bool:
    """Did auto release queue the release `tid`?"""
    from agent_runner.status import read_events
    return any(e['kind'] == S.EV_AUTO_RELEASE and e.get('id') == tid for e in read_events())


def _ready() -> None:
    if S.C is None:
        S.init()


def _event(kind: str, tid: str, text: str, **fields) -> None:
    """A record in events.jsonl alone: a plan command's output is its own."""
    rec = {'time': dt.datetime.now().isoformat(timespec='seconds'), 'kind': kind, 'id': tid, 'text': text, **fields}
    f = S.C.notes('events.jsonl')
    f.parent.mkdir(parents=True, exist_ok=True)
    with open(f, 'a', encoding='utf-8') as out:
        out.write(json.dumps(rec, ensure_ascii=False) + '\n')


# --- a release task ------------------------------------------------------------

def _is_next_cut(line: str, tid: str) -> bool:
    """Is the release the next cut: it waits for no task, has the default brief, or auto release queued it? Not one a
    person wrote that waits by itself, which the count has always gone on beside."""
    return is_moved(line) or not P.fields(line).get('after') or P.RELEASE_BRIEF in line or automatic(tid)


def rewait(tid: str, todo=None) -> None:
    """The release `tid` was moved: it waits for the tasks above it now, whatever it waited for before, and is no
    longer critical, or it would go ahead of its place."""
    _ready()
    todo, _ = P.ensure(todo)
    ls = list(P.lines(todo))
    line = ls[P._find(ls, tid)]
    keyed = f' | after: {P.ALL}' + (f' | {KEY}: yes' if _is_next_cut(line, tid) else '')
    P.edit(tid, keyed=keyed, todo=todo)
    ls = list(P.lines(todo))
    i = P._find(ls, tid)
    ls[i] = P.PRI_TAG.sub(lambda m: '' if m.group(1) == 'critical' else m.group(0), ls[i], count=1).replace('**  ', '** ', 1)
    P._write(todo, ls)


def removed(tid: str) -> bool:
    """The release `tid` was dropped: one auto release queued skips that cut. True when the count starts again."""
    _ready()
    if not automatic(tid):
        return False
    _event(EV_CUT_REMOVED, tid, f'{tid} removed: the count starts from zero')
    return True


def restored(tid: str) -> bool:
    """The release `tid` was restored: its removal no longer counts. False when there was none."""
    _ready()
    if not any(s[0] == tid for s in cuts().skips):
        return False
    _event(EV_CUT_RESTORED, tid, f'{tid} restored: the count is as before')
    return True


# --- the Next release row ------------------------------------------------------

def no_next(todo) -> str:
    """Why there is no Next release row to act on, '' when there is one."""
    from agent_runner import autorelease, ui_model as U
    _ready()
    ls = P.lines(todo)
    if not autorelease.releases_on() or not any(autorelease.auto_release_of(S.C.run.get('auto_release', False))):
        return 'no release is queued by itself here ([run] auto_release)'
    if not U.auto_release_row(ls, 0, U.release_tasks(ls, U._state(S.run_up()))):
        return f'{P.open_release(ls)} is the next release: name it'
    return ''


def _next(todo) -> None:
    if why := no_next(todo):
        raise SystemExit(f'{P.PROG}: there is no {NEXT}: {why}')


def hold_next(todo) -> str:
    """Hold the Next release row's cut; what to say."""
    _next(todo)
    if cuts().held:
        return f'{NEXT} is held already'
    _event(EV_CUT_HELD, NEXT, 'the next release is held')
    return f'held {NEXT}: no release is cut by itself (`{P.PROG} unhold {NEXT}` ends it)'


def unhold_next() -> str:
    """End that hold; what to say."""
    _ready()
    if not cuts().held:
        return f'{NEXT} is not held'
    _event(EV_CUT_UNHELD, NEXT, 'the next release is no longer held')
    return f'{NEXT} is no longer held'


def drop_next(todo) -> str:
    """Skip the Next release row's cut; what to say."""
    _next(todo)
    _event(EV_CUT_REMOVED, NEXT, 'the next release removed: the count starts from zero')
    return f'removed {NEXT}: that cut is skipped, and the count starts from zero (`{P.PROG} restore {NEXT}` undoes it)'


def restore_next() -> str:
    """Undo the last removal of the Next release row's cut; what to say."""
    if not restored(NEXT):
        raise SystemExit(f'{P.PROG}: no {NEXT} was removed: nothing to restore')
    return f'restored {NEXT}: the count is as before'


def move_next(where: str, ref: str | None, todo) -> str:
    """Move the Next release row: that cut is a release task at the place now, which waits for the tasks above it.
    Held, it stays held. Its id."""
    from agent_runner import row_hold
    _next(todo)
    tid = P.add(P.RELEASE, f'{P.RELEASE_BRIEF} | after: {P.ALL}', where, ref, todo=todo)
    rewait(tid, todo)
    _event(S.EV_AUTO_RELEASE, tid, f'queued {tid} (auto_release: moved)', why='moved')
    if cuts().held:
        row_hold.hold_task(tid, todo)
        _event(EV_CUT_UNHELD, NEXT, f'the hold is on {tid} now')
    return tid
