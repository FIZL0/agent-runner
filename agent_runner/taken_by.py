"""B846: which chat took a task by hand (`take`), for the task's Plan queue row.

`record` leaves it in the git folder of the take worktree (`.git/worktrees/take-<ID>/`), so it goes with the worktree
and is never an edit in it. A take from a terminal, or by a slot's agent, records nothing: 'Taken by hand'."""

from __future__ import annotations

import json
import os
from pathlib import Path

FILE = 'taken-by.json'


def _file(d: Path) -> Path | None:
    """The record of the take worktree `d`, read without running git; None when `d` is no linked worktree."""
    try:
        kind, _, where = (d / '.git').read_text(encoding='utf-8').strip().partition(': ')
    except (OSError, ValueError):
        return None
    return d / where / FILE if kind == 'gitdir' and where else None


def _pid(c, n: int) -> str:
    try:
        return c.notes(f'control{n}.pid').read_text(encoding='utf-8').strip().partition(' ')[0]
    except OSError:
        return ''


def record(c, d: Path) -> None:
    """Record the control session that runs this command as the one that took worktree `d`, if one does. Never stops the take."""
    from agent_runner.control_settled import author
    try:
        who = author(c)
        pid = _pid(c, who['n']) if who['n'] else ''
        if pid and (f := _file(d)):
            f.write_text(json.dumps({'n': who['n'], 'sid': who['sid'], 'pid': pid}), encoding='utf-8')
    except (OSError, ValueError):
        pass


def chat(c, d: Path, live) -> int | None:
    """The number of the live chat that took worktree `d`; 0 when that chat has ended; None when unknown. `live`: the
    numbers of the live control sessions. A number is used again by a later chat: it is the same one when its process
    is (its session id changes at /clear) or its session id is (a reopened chat is a new process)."""
    from agent_runner.control_settled import pid_sid
    try:
        who = json.loads(f.read_text(encoding='utf-8')) if (f := _file(d)) else None
    except (OSError, ValueError):
        return None
    if not isinstance(who, dict) or not who.get('pid'):
        return None
    for n in live:
        if n == who.get('n') and _pid(c, n) == who['pid'] or who.get('sid') and pid_sid(c, n) == who['sid']:
            now = {'n': n, 'sid': pid_sid(c, n), 'pid': _pid(c, n)}
            if now != who and now['pid']:  # follow it, so that a cleared chat is known once it is reopened too
                try:
                    tmp = f.with_suffix(f'.{os.getpid()}.tmp')
                    tmp.write_text(json.dumps(now), encoding='utf-8')
                    tmp.replace(f)
                except OSError:
                    pass
            return n
    return 0
