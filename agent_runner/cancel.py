"""F426d: `plan cancel ID`: the run stops the agent on a running task and keeps its work on wip/ID, then the task is
parked (`--pri later`), so no run starts it again until the person unparks it. Nothing is cancelled while the task lands.

The run's part is `loop_requests.cancels`; it answers each request with JSON: {"cancelled", "msg", "wip"}."""
from __future__ import annotations

import json
import sys
import time

from agent_runner import plan as P

KIND = 'cancel'  # the request's channel. Not 'halt': a merge reads those, and deletes the branch of a halted task
YES = '--yes'
ASK = 'Cancel stops its agent, keeps its work and parks the task: no agent starts it until you unpark it.'


def worked(tid: str, where: str, minutes: int | None) -> str:
    """How long `tid` has been worked on, a sentence ('' when that is not known)."""
    return '' if minutes is None else f'{tid} has worked {minutes} min{f" in {where}" if where else ""}. '


def question(tid: str, where: str = '', minutes: int | None = None) -> str:
    return f'{worked(tid, where, minutes)}{ASK} Cancel {tid}?'


def _state(c) -> dict:
    try:
        st = json.loads(c.notes('STATE').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return st if isinstance(st, dict) else {}


def minutes_in(c, tid: str) -> int | None:
    """The minutes the run's STATE says a slot has been on `tid`."""
    st = _state(c)
    n = next((n for n, t in (st.get('running') or {}).items() if t == tid), None)
    since = (st.get('since') or {}).get(n)
    return int((time.time() - since) // 60) if since else None


def landing(c, tid: str, where: str) -> str:
    """Why `tid` cannot be cancelled now: it lands, or its session ends by itself ('' when it can)."""
    from agent_runner.config import finished_mark
    if where == 'merging' or tid in (_state(c).get('merging') or []):
        return f'{tid} is landing, so it cannot be cancelled'
    if (m := finished_mark(where.removeprefix('s'), c)) and m.exists():
        return f'{tid} is finished and about to land, so it cannot be cancelled'
    if P.ending_ask(c, tid, where):
        return f'{tid} has just asked you a question and waits for your answer: it is not running any more'
    return ''


def stop(c, tid: str, words: list[str], wait: float | None = None) -> tuple[int, str, str]:
    """Ask the run to stop `tid`: (exit code, what to say, the note for its plan line). Code 0: the plan edit parks it."""
    if [w for w in words if w != YES]:
        return 2, f'{P.PROG} cancel <ID> [{YES}]', ''
    if not (where := P.run_on(c, tid)):
        return 1, (f'{P.PROG}: {tid} is not running, so there is nothing to cancel (`{P.PROG} edit {tid} --pri later` '
                   'parks a queued task)'), ''
    if why := landing(c, tid, where):
        return 1, f'{P.PROG}: {why}', ''
    mins = minutes_in(c, tid)
    if YES not in words:
        return 3, f'{question(tid, where, mins)} To go on: {P.PROG} cancel {tid} {YES}', ''
    said = P.request(c, KIND, tid, {'how': 'cancel'}, P.HALT_WAIT if wait is None else wait)
    after = '' if mins is None else f' after {mins} min'
    if said is None:  # it stays asked; parked now, so the run starts it again in no case
        return 0, f'asked the run to stop {where}: within seconds its work is on wip/{tid}, unless it lands first', \
            f'asked to cancel{after}: if it was stopped, what was done is on the newest wip/{tid} branch, go on from there'
    try:
        got = json.loads(said)
    except ValueError:
        got = {}
    if not got.get('cancelled'):
        return 1, f'{P.PROG}: {got.get("msg") or f"the run did not cancel {tid}"}', ''
    wip = got.get('wip') or ''
    return 0, got.get('msg', ''), f'cancelled{after}: ' + (
        f'its work is on {wip}, go on from there' if wip else 'nothing had been done yet')


def park(tid: str, note: str, todo=None) -> None:
    """Park `tid` in the plan, with what its next agent should know as a note."""
    todo, _ = P.ensure(todo)
    P.edit(tid, pri='later', todo=todo)
    if note:
        P.note(tid, note, todo=todo)


def main(c, argv: list[str]) -> tuple[int, list[str]]:
    """`plan cancel`, before its plan edit: (exit code, the edit's words), the code not 0 when there is no edit."""
    if not argv:
        print(f'{P.PROG} cancel <ID> [{YES}]', file=sys.stderr)
        return 2, []
    tid = argv[0]
    rc, said, note = stop(c, tid, argv[1:])
    if said:
        print(said, file=sys.stderr if rc else sys.stdout)
    return rc, [] if rc else ['cancel', tid, note]
