"""B859: control sessions closed for being idle stay in the chat list, grayed under Quiet, until chat_quiet
passes since their last activity: `close_controls` marks each (`<notes>/controlN.closed`: "at sid") and keeps
its title; `end_control` (a close the person asked for) drops the mark at once."""
from __future__ import annotations

import re
import time

from agent_runner.state import C


def idle_closed(n: int, sid: str, at: float) -> None:
    """Mark control session `n` (conversation `sid`, last active at `at`) as closed for being idle."""
    try:
        C.notes(f'control{n}.closed').write_text(f'{int(at)} {sid}\n', encoding='utf-8')
    except OSError:
        pass


def idle_closed_chats(quiet: float, now: float | None = None) -> dict[int, tuple[float, str]]:
    """{N: (last active, sid)} of the control sessions closed for being idle (`idle_closed`) that are not live
    again and whose last activity is under `quiet` s ago. A read only: an old mark is left (`end_control` drops it)."""
    from agent_runner.control import control_live
    now = time.time() if now is None else now
    out = {}
    for f in C.notes().glob('control*.closed'):
        if not (m := re.fullmatch(r'control(\d+)\.closed', f.name)):
            continue
        n = int(m[1])
        try:
            at_s, _, sid = f.read_text(encoding='utf-8').strip().partition(' ')
            at = float(at_s)
        except (OSError, ValueError):
            continue
        if not control_live(n) and quiet > 0 and now - at < quiet and sid:
            out[n] = (at, sid.strip())
    return out
