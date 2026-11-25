"""F426e: the tasks that merge now, for the run page's Status: each with its step, the run log's last words on it, and
its session's link. A task's slot may be on its next task by then, so the slots' rows do not have them."""
from __future__ import annotations

import os
import re

from agent_runner import state as S

TAIL = 65536  # bytes of the run log looked through for the steps
LINE = re.compile(r'=== \S+ (.*)')
LINKS: dict[str, str] = {}  # {task: its session's link}, while it merges: reading one goes through every slot log


def log_lines() -> list[str]:
    """The run log's last lines, without their time."""
    try:
        with open(S.C.notes('run.log'), 'rb') as f:
            f.seek(max(0, f.seek(0, os.SEEK_END) - TAIL))
            text = f.read().decode('utf-8', 'replace')
    except OSError:
        return []
    return [m[1] for line in text.splitlines() if (m := LINE.match(line))]


def step(tid: str, lines: list[str]) -> str:
    """What the run log last said of the merge of `tid`, in words for the page; '' when it has said nothing since the
    task last left its slot."""
    for line in reversed(lines):
        if re.match(rf'slot \S+: {re.escape(tid)}(?![\w-])', line):
            return ''
        if line.startswith(tid + ': '):
            said = re.sub(r'\s+[—–]\s+', ', ', line[len(tid) + 2:]).strip()
            return said[:1].upper() + said[1:]
    return ''


def link_of(tid: str, bridge) -> str:
    """Its last session's claude.ai link, '' for none."""
    if tid not in LINKS:
        try:
            from agent_runner.watch import last_session
            last = last_session(tid)
            LINKS[tid] = bridge(last[1]) if last else ''
        except Exception:  # noqa: BLE001 - costs the link, not the snapshot
            LINKS[tid] = ''
    return LINKS[tid]


def rows(st: dict, titles: dict[str, str], bridge, links=None) -> list[dict]:
    """The merging tasks of STATE `st`: id, title, step, link. `bridge`: a session's link from its id; `links` given
    (as `ui_model.session_rows`): no link is looked up."""
    ids = list(st.get('merging') or [])
    for t in set(LINKS) - set(ids):
        LINKS.pop(t, None)
    lines = log_lines() if ids else []
    return [{'id': t, 'title': titles.get(t, ''), 'step': step(t, lines),
             'link': '' if links is not None else link_of(t, bridge)} for t in ids]
