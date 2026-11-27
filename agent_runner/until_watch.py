"""F427c: the run reads the until checks its blocked tasks wait on, by itself, and reopens a task once all of its checks
pass. Off the scheduling thread, every EVERY s; each distinct check runs once a round however many tasks wait on it,
and none runs with no task waiting. No agent session and no model call: `until.run` only.

A check that cannot run for CANNOT_ASK s, or has not passed for STALE_ASK s, is one Needs you item (`asks`) that
says which check, its last words and how to free the task; it goes by itself once the check passes or nothing
waits on it."""

from __future__ import annotations

import datetime as dt
import json
import os
import threading
import time

from agent_runner import plan as P, until
from agent_runner import state as S

EVERY = 120.0               # s between rounds
CANNOT_ASK = 30 * 60.0      # s a check cannot run, with tasks waiting, before it is a Needs you item
STALE_ASK = 3 * 86400.0     # s a check has not passed, with tasks waiting, before it is a Needs you item
LABEL = 'UNTIL'             # the Needs you label
PREFIX = 'until-'           # a Needs you item's id: until-<check>
_LOCK = threading.Lock()
_BUSY = threading.Lock()    # one round at a time
_NEXT = [0.0]               # when the next round is due (time.time())


def _file():
    return S.C.notes('until-watch.json')


def read(c=None) -> dict[str, dict]:
    """{check: {'waiting': since, 'cannot': since or 0, 'state', 'said', 'tasks': [ids]}} as the last round left it."""
    try:
        d = json.loads((c or S.C).notes('until-watch.json').read_text(encoding='utf-8'))
    except (OSError, ValueError, AttributeError):
        return {}
    return {k: r for k, r in d.items() if isinstance(r, dict)} if isinstance(d, dict) else {}


def _write(d: dict[str, dict]) -> None:
    tmp = _file().with_suffix('.json-tmp')
    try:
        tmp.write_text(json.dumps(d, indent=1), encoding='utf-8')
        os.replace(tmp, _file())
    except OSError as e:
        S.log(f'could not note the until checks ({e})')


def waiters(ls: list[str]) -> dict[str, list[str]]:
    """{task: its until checks} of TODO.md's lines `ls`."""
    return {tid: got for _, box, tid, _, i in P.iter_tasks(ls) if box == '~' and (got := P.until_of(ls, i))}


def round_(branch: str, now: float | None = None, run=None, reopen=None) -> list[str]:
    """One round: run each check some task waits on once, note what it said, and reopen the tasks whose checks all
    passed (`reopen(branch, ids)` -> the ids it reopened; `land.reopen_until`). The ids reopened."""
    now = time.time() if now is None else now
    run = run or until.run
    if reopen is None:
        from agent_runner.land import reopen_until as reopen
    waits = waiters(S.plan_text(branch))
    checks = sorted({c for cs in waits.values() for c in cs})
    got = {}
    for c in checks:
        try:
            got[c] = run(c)
        except Exception as e:  # noqa: BLE001 - a check never stops the round
            got[c] = (until.CANNOT, str(e) or type(e).__name__)
    with _LOCK:
        old, d = read(), {}
        for c in checks:
            state, said = got[c]
            o = old.get(c, {})
            asked = o.get('cannot') and now - o['cannot'] >= CANNOT_ASK  # a shown item stays until the check passes
            d[c] = {'waiting': o.get('waiting') or now, 'state': state, 'said': ' '.join(str(said).split())[:240],
                    'cannot': 0 if state == until.PASSED else (o.get('cannot') or now) if state == until.CANNOT
                    else o['cannot'] if asked else 0,
                    'tasks': sorted(t for t, cs in waits.items() if c in cs)}
            if state == until.PASSED:
                d[c]['waiting'] = now  # passed: the 3 days count afresh
        _write(d)
    ready = [t for t, cs in waits.items() if all(got[c][0] == until.PASSED for c in cs)]
    return reopen(branch, ready) if ready else []


def tick(branch: str, now: float | None = None) -> bool:
    """Each tick of the run: start a round on a thread of its own when one is due and none is going. True when started."""
    now = time.time() if now is None else now
    if now < _NEXT[0] or not _BUSY.acquire(blocking=False):
        return False
    _NEXT[0] = now + EVERY

    def go():
        try:
            round_(branch)
        except Exception as e:  # noqa: BLE001 - the watch never ends the run
            S.log(f'until checks: {type(e).__name__}: {e}')
        finally:
            _BUSY.release()
    threading.Thread(target=go, name='until-watch', daemon=True).start()
    return True


def ask_text(check: str, r: dict, c=None, cannot: bool = False) -> str:
    name = until.label(check, c)
    ts = ', '.join(r.get('tasks', []))
    how = f'free {ts} with Unblock (plan unblock), or fix it'
    if cannot:
        return f'{name} could not be checked for 30 min: {r.get("said") or "no words"}; {how}'
    return f'{name} has not passed in 3 days: {r.get("said") or "no words"}; {how}'


def asks(c=None, now: float | None = None) -> list[tuple]:
    """The checks that cannot run for CANNOT_ASK, or have not passed for STALE_ASK, as Needs you items in `plan.asks`'s
    shape with the stamp eighth."""
    now = time.time() if now is None else now
    out = []
    try:
        for check, r in sorted(read(c).items()):
            if not r.get('tasks') or r.get('state') == until.PASSED:
                continue
            cannot = r.get('cannot') or 0
            since = cannot if cannot and now - cannot >= CANNOT_ASK else \
                r.get('waiting') if r.get('waiting') and now - r['waiting'] >= STALE_ASK else 0
            if since:
                out.append((LABEL, PREFIX + check, '', ask_text(check, r, c, since == cannot), '', until.label(check, c), False,
                            dt.datetime.fromtimestamp(since).strftime('%Y-%m-%d %H:%M')))
    except (OSError, ValueError, TypeError, AttributeError, SystemExit):
        return []
    return out
