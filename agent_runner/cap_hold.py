"""F468: the run held by the usage caps (`[run] session_max`, `weekly_max`), said plainly, and force for one task.

`run force` lets every task start past the caps; `run force ID` lets just that task start (FORCE_IDS, kept until
the run ends or it starts)."""

from __future__ import annotations

import datetime as dt

FORCE_IDS: set[str] = set()  # tasks `run force ID` lets start past the usage caps
CAPS = (('five_hour', '5-hour', 'session_max'), ('seven_day', 'weekly', 'weekly_max'))


def held_caps(use: dict, caps: dict) -> list[tuple[str, float, float, str]]:
    """The caps reached: [(its name, usage %, cap %, the window's key)]."""
    out = []
    for key, name, cap_key in CAPS:
        u, cap = use.get(key), caps.get(cap_key)
        if u is not None and cap is not None and u >= cap:
            out.append((name, u, cap, key))
    return out


def lifts_words(at: str, now: float) -> str:
    """'lifts 14:05' (today) or 'lifts Fri 09:00', from the endpoint's ISO `resets_at`; '' when unknown."""
    try:
        t = dt.datetime.fromisoformat(str(at).replace('Z', '+00:00'))
    except ValueError:
        return ''
    local = t.astimezone() if t.tzinfo else t
    today = dt.datetime.fromtimestamp(now).date() if now else dt.date.today()
    return 'lifts ' + local.strftime('%H:%M' if local.date() == today else '%a %H:%M')


def held_line(st: dict, caps: dict, now: float = 0) -> str:
    """The status headline when the usage caps hold new tasks, '' when they do not (or force is on)."""
    if st.get('forced'):
        return ''
    hit = held_caps(st.get('usage') or {}, caps)
    if not hit:
        return ''
    resets = st.get('resets') or {}
    parts = []
    for name, u, cap, key in hit:
        lifts = lifts_words(resets.get(key, ''), now)
        parts.append(f'{name} usage {u:.0f}% (cap {cap:.0f}%)' + (f', {lifts}' if lifts else ''))
    ids = st.get('force_ids') or []
    return ('HELD by usage caps: ' + '; '.join(parts) + '. New tasks wait; `force` starts them all, `force ID` one'
            + (f' (forced: {", ".join(ids)})' if ids else ''))


def force_key(want: str) -> str:
    """The log line for `f <want>` when `want` is a task id: it joins FORCE_IDS ('' when it is not an id)."""
    tid = want.strip()
    if not tid or tid in ('on', 'off'):
        return ''
    FORCE_IDS.add(tid)
    return f'forced: {tid} may start past the usage caps'


def only_forced(open_ids: set[str], forced: set[str]) -> set[str]:
    """What a pick passes over while the caps hold: every open task but the forced ones."""
    return set(open_ids) - set(forced)
