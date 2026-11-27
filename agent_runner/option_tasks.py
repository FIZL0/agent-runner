"""F192d: the tasks each option of a question queues, stored before the question is asked, so one tap on an option
queues its tasks at once, with no reply from Claude.

A control session writes one JSON file per question under the notes' `option-tasks/` (any file name, `.json`):
{"question": <the DECIDE question as written, without its bracket>,
 "options": {<option name>: [[<plan add arguments: KIND, text, --files ..., ...>], ...]}}.
A question is found by its words; an option without tasks sends the answer as before.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

DIR = 'option-tasks'


def _dir(root: Path | None = None) -> Path:
    if root is not None:
        return Path(root)
    from agent_runner.config import cfg
    return cfg.notes(DIR, 'x').parent


def _key(question: str) -> str:
    """The question's words, its bracket of options and spacing left out."""
    q = re.sub(r'\s*\[[^\]]*\]\s*$', '', str(question or '').strip())
    return ' '.join(q.split()).casefold()


def _files(question: str, root=None) -> list[tuple[Path, dict]]:
    d, k, out = _dir(root), _key(question), []
    if not k or not d.is_dir():
        return out
    for p in sorted(d.glob('*.json')):
        try:
            data = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and _key(data.get('question', '')) == k:
            out.append((p, data))
    return out


def store(question: str, options: dict, name: str, root=None) -> Path:
    """Write `options` {option: [plan add arguments, ...]} for `question` as file `name`."""
    p = _dir(root) / (re.sub(r'[^\w.-]', '-', name) + '.json')
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({'question': question, 'options': options}, indent=1))
    return p


def stored(question: str, root=None) -> dict[str, list[list[str]]]:
    """{option: its tasks} stored for `question` (the newest file wins); {} for none, or once queued."""
    out: dict = {}
    for _p, data in _files(question, root):
        if data.get('queued'):
            return {}
        for opt, tasks in (data.get('options') or {}).items():
            if isinstance(tasks, list):
                out[str(opt)] = [[str(a) for a in t] for t in tasks if isinstance(t, list) and t]
    return out


def counts(question: str, root=None) -> dict[str, int]:
    """{option: how many tasks it queues}, options with tasks only."""
    return {o: len(t) for o, t in stored(question, root).items() if t}


def _plan_add(args: list[str]) -> int:
    from agent_runner import plan
    return plan.main(['add', *args])


def queue(question: str, option: str, root=None, add=_plan_add) -> list[list[str]]:
    """Queue `option`'s tasks of `question` once: the files are marked queued first, so a second call (a double tap)
    adds nothing. The tasks queued; [] when none were stored, or they were queued already."""
    files = _files(question, root)
    tasks = stored(question, root).get(option) or []
    if not tasks:
        return []
    for p, data in files:
        p.write_text(json.dumps({**data, 'queued': option}, indent=1))
    for t in tasks:
        add(t)
    return tasks


def drop(question: str, root=None) -> int:
    """Remove what is stored for `question`, once it is answered or replaced; how many files went."""
    n = 0
    for p, _data in _files(question, root):
        p.unlink(missing_ok=True)
        n += 1
    return n
