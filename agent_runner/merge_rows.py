"""F426e: the tasks that merge now, for the run page's Status: each with its step, the run log's last words on it, and
its session's link. A task's slot may be on its next task by then, so the slots' rows do not have them."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from agent_runner import state as S

TAIL = 65536  # bytes of the run log looked through for the steps
LINE = re.compile(r'=== \S+ (.*)')
RIDES = re.compile(r'(\S+): merging together with (.+?) \(')
TESTING, WAITS, UNKNOWN = 'Testing the merge', 'Waiting to merge', 'Not merged yet'  # B831: no step logged yet
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
        if m := RIDES.match(line):  # a batch: the log names the task that leads it
            if tid in m[2].split(', '):
                return f'Merging together with {m[1]} (one gate run)'
        if line.startswith(tid + ': '):
            said = re.sub(r'\s+[—–]\s+', ', ', line[len(tid) + 2:]).strip()
            return said[:1].upper() + said[1:]
    return ''


def live_gates() -> list[dict]:
    """The merge gates running now, and the fix or repair session (`kind`), from their records. Never `merge.gate_runs`, which removes a record it cannot
    read: here it may be one the run is just writing."""
    from agent_runner.merge import GATES, gate_alive
    out = []
    for f in [*S.C.notes(GATES).glob('*.json'), S.C.notes('master.json')]:
        try:
            s = json.loads(f.read_text(encoding='utf-8'))
            if gate_alive(s):
                out.append(s)
        except (OSError, ValueError, TypeError, AttributeError):
            pass
    return out


def stage(tid: str, gates: list[dict]) -> str:
    """Where the merge of `tid` is when the run log has no step of it: a running gate holds it, or what runs in the merge
    worktree (one merge at a time) is another task's, so it waits. With neither the run cannot tell."""
    mine = [s for s in gates if tid in (s.get('tids') or [s.get('tid')])]
    if mine:
        return UNKNOWN if all(s.get('kind') for s in mine) else TESTING
    return WAITS if any(Path(s.get('cwd') or '').name == 'merge' for s in gates) else UNKNOWN


def link_of(tid: str, bridge) -> str:
    """Its last session's claude.ai link, '' for none."""
    if tid not in LINKS:
        try:
            from agent_runner.watch import last_session
            last = last_session(tid)
            if link := bridge(last[1]) if last else '':
                LINKS[tid] = link
        except Exception:  # noqa: BLE001 - costs the link, not the snapshot
            pass
    return LINKS.get(tid, '')


def rows(st: dict, titles: dict[str, str], bridge, links=None) -> list[dict]:
    """The merging tasks of STATE `st`: id, title, step, link. `bridge`: a session's link from its id; `links` given
    (as `ui_model.session_rows`): no link is looked up."""
    ids = list(st.get('merging') or [])
    for t in set(LINKS) - set(ids):
        LINKS.pop(t, None)
    lines = log_lines() if ids else []
    gates = live_gates() if ids else []
    return [{'id': t, 'title': titles.get(t, ''), 'step': step(t, lines) or stage(t, gates),
             'link': '' if links is not None else link_of(t, bridge)} for t in ids]
