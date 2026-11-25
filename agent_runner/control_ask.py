"""B809b: what explains a control session's question, kept with it when the run files it under Needs you
(`control.file_control_ask`): the text of the message it ended, the pictures that names, the session's name and project.

It is kept in the item's ask file (`asks.keep_explained`; `need_detail` reads it). `fill` does so once for the items an
older run filed without it.

Not one of the FAMILY modules `share` reaches, so the run's settings are read through `state` at call time."""

from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import unquote

from agent_runner import asks, control_settled, need_detail, plan as P, state as S
from agent_runner.plan import cut_question, decide_question, on_a_line

TEXT_MAX = 12_000  # characters: below need_detail.FILE_MAX in any script
TYPES = '|'.join(re.escape(x) for x in need_detail.SHOT_TYPES)
PICTURE = re.compile(rf'\[(?P<alt>[^\]\n]*)\]\(<?(?P<md>[^)>\n]+?(?:{TYPES}))>?(?:\s+"[^"\n]*")?\)'  # ![alt](path)
                     rf'|`(?P<code>[^`\n]+?(?:{TYPES}))`'
                     rf'|(?<![^\s("\'*<\[])(?P<bare>[^\s`()\[\]<>"\'*]+?(?:{TYPES}))(?![\w/])', re.I)
# the question as `control.file_control_ask` words it in the task, and the session
FILED = re.compile(r'\*\* \([^)]*\) Control session (\d+) asked the person: "(.*?)" Carry on from their answer ')
RESUME = re.compile(r'--resume ([0-9a-f]{8}-[0-9a-f-]{27})\b')
FILLED: set[str] = set()  # the plans this process has looked through (`fill`)


def _above(text: str) -> str:
    """`text` without its DECIDE line, if it ends on one; '' when no words are left."""
    text = text.strip()
    if decide_question(text):
        text = '\n'.join(text.splitlines()[:-1]).rstrip()
    return text if re.search(r'\w', text) else ''


def explained(rows: list, q: str) -> tuple[str, str]:
    """(the text that explains question `q` in transcript entries `rows`, the folder its session worked in): what the
    message that ended on `q` says above its DECIDE line, else the message shown before it. ('', '') without `q`."""
    from agent_runner.control import message_text
    said = [(d, t) for d in rows if isinstance(d, dict) and d.get('type') == 'assistant' and not d.get('isSidechain')
            and not d.get('isApiErrorMessage') and (d.get('message') or {}).get('model') != '<synthetic>'
            and (t := message_text(d).strip())]
    q = on_a_line(q)  # B840: one filed before may hold its marks, and be cut

    def asks_q(t: str) -> bool:
        asked = decide_question(t)
        return bool(asked) and q in (asked, cut_question(asked))
    at = next((i for i in range(len(said) - 1, -1, -1) if asks_q(said[i][1])), -1)
    for d, t in reversed(said[:at + 1]):
        if text := _above(t):
            return text, str(d.get('cwd') or '')
    return '', ''


def _inside(f: Path, sid: str) -> bool:
    """Whether the real path `f` is in this project, or in the scratchpad Claude Code gave session `sid`."""
    if f.is_relative_to(os.path.realpath(S.ROOT)):
        return True
    from agent_runner.slots import tmp_roots
    if not any(f.is_relative_to(os.path.realpath(r)) for r in (*tmp_roots(), Path.home() / '.cache')):
        return False
    parts = f.parts
    return bool(sid) and any(parts[i] == sid and parts[i + 1] == 'scratchpad' and re.fullmatch(r'claude(-\w+)?', parts[i - 2])
                             for i in range(2, len(parts) - 2))


def pictures(text: str, sid: str, cwd: str = '') -> list[tuple[bytes, str, str]]:
    """(its bytes, its suffix, its caption) of each local picture `text` names, in this project or session `sid`'s
    scratchpad and of a type Needs you shows. A relative path is from `cwd`, else from the project."""
    out: list[tuple[bytes, str, str]] = []
    seen: set[str] = set()
    for m in PICTURE.finditer(text):
        name = (m['md'] or m['code'] or m['bare']).strip()
        name = unquote(name[7:]) if name.lower().startswith('file://') else unquote(name) if m['md'] else name
        if '://' in name or '\0' in name or len(out) >= need_detail.SHOTS_MAX:
            continue
        name = os.path.expanduser(name)
        for base in dict.fromkeys((cwd or str(S.ROOT), str(S.ROOT))):
            try:
                f = Path(os.path.realpath(os.path.join(base, name)))
                if str(f) in seen or not f.is_file() or not _inside(f, sid):
                    continue
                if f.suffix.lower() not in need_detail.SHOT_TYPES or f.stat().st_size > need_detail.SHOT_MAX:
                    continue
                data = f.read_bytes()
            except (OSError, ValueError):
                continue
            if need_detail.image_type(data[:16]):
                seen.add(str(f))
                out.append((data, f.suffix.lower(), ' '.join((m['alt'] or f.stem).split())[:200]))
                break
    return out


def session_name(n: int, title: str) -> str:
    """Control session `n`'s name, without its project and number, from the `title` it goes by; '' for none."""
    words = title.strip()
    for lead in (S.ROOT.name, str(n)):
        words = '' if words == lead else words.removeprefix(f'{lead} · ')
    return '' if words == f'control {n}' else words


def keep(tid: str, sid: str, q: str, rows: list, n: int, title: str) -> bool:
    """Keep what explains question `q` of session `sid` as item `tid`'s. Whether there was a text."""
    text, cwd = explained(rows, q)
    if len(text) > TEXT_MAX:
        text = text[:TEXT_MAX].rsplit(None, 1)[0] + ' …'
    asks.keep_explained(tid, {'text': text, 'session': session_name(n, title), 'project': S.ROOT.name},
                        pictures(text, sid, cwd))
    return bool(text)


def filed(tid: str, sid: str, q: str, rows: list, n: int) -> None:
    """The run filed question `q` of control session `n` as `tid`. Never stops the filing."""
    try:
        from agent_runner import control as K
        from agent_runner.control_names import person_name
        title = K.control_state(rows)['title']
        keep(tid, sid, q, rows, n, person_name(n, title) or title or K.control_given(n))
    except Exception as e:  # noqa: BLE001
        S.log(f'{tid}: what explains its question was not kept: {e}')


def _sid(text: str, tid: str) -> str:
    """The session that asked what item `tid` (its task's `text`) asks; '' when nothing says."""
    if m := RESUME.search(text):
        return m[1]
    for f in control_settled.folder(S.C).glob('*.filed'):
        if tid in control_settled.read_json(f, {}).get('ids', []):
            return f.stem
    return ''


def _fill(tid: str) -> bool:
    """`fill` one waiting DECIDE, `tid`."""
    from agent_runner import control as K
    text = ' '.join(x.strip() for x in P.section(S.C.todo, tid))
    m = FILED.search(text)
    if not m or ' — your answer (' in text or need_detail.asks_file(tid).get('text'):
        return False
    n, q = int(m[1]), m[2]
    task, _, block = text.rpartition(' BLOCKED: ')
    if not re.match(rf'(?:shelved: )?DECIDE: {re.escape(q)}(?=\s|$)', block):
        return False
    sid = _sid(task, tid)
    if not sid or not K.transcript(sid):
        return False
    rows = list(K.entries(sid, skip_bad=True))
    return bool(explained(rows, q)[0]) and keep(tid, sid, q, rows, n, K.control_state(rows)['title'])


def fill() -> list[str]:
    """Once a process: give each control session's question that waits with no text its own, from the session's
    transcript, when that is still there. An item answered since, or that asks something else by now, is left alone."""
    if str(S.C.todo) in FILLED:
        return []
    try:
        waits = [a[1] for a in P.asks(S.C.todo, all=True) if a[0] == 'DECIDE']
    except (OSError, SystemExit):
        return []  # the next look tries again
    FILLED.add(str(S.C.todo))
    out = []
    for tid in waits:
        try:
            if _fill(tid):
                out.append(tid)
        except (Exception, SystemExit) as e:  # noqa: BLE001 - one item never stops the run or the others
            S.log(f'{tid}: what explains its question could not be filled in: {e}')
    if out:
        S.log(f'{", ".join(out)}: what explains the question was filled in from its session')
    return out
