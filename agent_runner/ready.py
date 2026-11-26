"""F445b: a ready item, what a task made for a person to look at or use outside the code (a video, pictures, a post, a
document), put under Needs you once the task lands.

`done ID MSG --ready "Showcase video is ready: watch it" [--ready-link URL]` keeps <notes>/ready/ID.json; the task
ticks as any other, its dependants go on and no release waits. The item, `ready-ID` (label READY), lists only once the
task is ticked in the plan the run reads (it landed), and stays until the person answers:
- Looks good (`plan confirm ready-ID`): it closes.
- Change it (`plan change ready-ID WORDS`): a follow-up is filed with their words; the task stays done.
- Not now (`plan shelve ready-ID`): shelved, off Needs you (`waiting --all` lists it; `unshelve` brings it back).
Its pictures or video: the ask file <notes>/asks/ready-ID.json, as for any item (`need_detail.asks_file`)."""
from __future__ import annotations

import datetime as dt
import json
import re
import time
from pathlib import Path

from agent_runner import plan as P
from agent_runner import state as S

LABEL = 'READY'
PREFIX = 'ready-'
ANSWERS = ('Looks good', 'Change it', 'Not now')


def item_id(tid: str) -> str:
    return PREFIX + tid


def task_of(rid: str) -> str:
    """The task id of item `rid` ('ready-F290': 'F290'); '' for an id that is no ready item's."""
    tid = rid[len(PREFIX):] if (rid or '').startswith(PREFIX) else ''
    return tid if re.fullmatch(r'\w[\w.-]*', tid) else ''


def _file(c, tid: str) -> Path:
    return c.notes('ready', f'{tid}.json')


def keep(c, tid: str, what: str, link: str = '') -> Path:
    """`done --ready`: keep task `tid`'s ready item, waiting for the task to land."""
    f = _file(c, tid)
    f.write_text(json.dumps({'what': ' '.join(what.split()), 'link': (link or '').strip(), 'at': time.time(),
                             'shelved': False}), encoding='utf-8')
    return f


def _read(c, tid: str) -> dict:
    try:
        d = json.loads(_file(c, tid).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def _ticked(c) -> set[str]:
    """The tasks ticked in the plan the run reads."""
    out = set()
    for p in (c.done, c.todo):
        try:
            text = Path(p).read_text(encoding='utf-8')
        except OSError:
            continue
        out |= {m.group(3).rstrip('.') for l in text.splitlines()
                if (m := P.ITEM.match(l)) and not m.group(1) and m.group(2) == 'x'}
    return out


def asks(c=None, all: bool = False) -> list[tuple]:
    """The landed ready items as Needs you items, in `plan.asks`'s shape with the stamp eighth; shelved only with `all`."""
    c = c or S.C
    try:
        d = c.notes('ready', 'x').parent
        files = sorted(d.glob('*.json'))
        if not files:
            return []
        done, titles = _ticked(c), P.titles(c.done, c.todo, width=200)
    except (OSError, SystemExit, AttributeError):
        return []
    out = []
    for f in files:
        tid, r = f.stem, _read(c, f.stem)
        if not r or tid not in done or (r.get('shelved') and not all):
            continue
        at = r.get('at') or 0
        out.append((LABEL, item_id(tid), '', r.get('what') or 'Ready: have a look', r.get('link') or '',
                    titles.get(tid, tid), bool(r.get('shelved')),
                    dt.datetime.fromtimestamp(at).strftime('%Y-%m-%d %H:%M') if at else ''))
    return out


def _own(rid: str, c) -> str:
    tid = task_of(rid)
    if not tid or not _read(c, tid):
        raise SystemExit(f'{P.PROG}: nothing ready to look at here about {rid!r}')
    return tid


def good(rid: str, c=None) -> str:
    """Looks good: the item closes."""
    c = c or S.C
    tid = _own(rid, c)
    _file(c, tid).unlink(missing_ok=True)
    return f'{rid}: looks good, closed'


def shelve(rid: str, on: bool = True, c=None) -> str:
    """Not now: the item leaves Needs you (`waiting --all` still lists it); `on` False brings it back."""
    c = c or S.C
    tid = _own(rid, c)
    r = _read(c, tid)
    r['shelved'] = on
    _file(c, tid).write_text(json.dumps(r), encoding='utf-8')
    return rid


def change(rid: str, words: str, c=None, todo=None, done=None) -> str:
    """Change it: a follow-up with the person's `words`, on the task's files; the task stays done, the item closes."""
    c = c or S.C
    tid = _own(rid, c)
    words = ' '.join((words or '').split())
    if not words:
        raise SystemExit(f'{P.PROG}: say what to change: `{P.PROG} change {rid} "<what>"`')
    todo, done = P.ensure(todo, done)
    line = next((l for p in (done, todo) for l in Path(p).read_text(encoding='utf-8').splitlines()
                 if (m := P.ITEM.match(l)) and m.group(3).rstrip('.') == tid), '')
    title = P.titles(done, todo, width=200).get(tid, tid)
    files = P.files_on_line(line)
    kind = re.match(r'[A-Z]+', tid)
    new = P.add(kind.group(0) if kind else 'F', f'Change what {tid} made ({title}): {words}'
                + (f' | files: {", ".join(files)}' if files else ''), pri='normal', todo=todo, done=done)
    _file(c, tid).unlink(missing_ok=True)
    return f'{new} filed to change what {tid} made; {tid} stays done'
