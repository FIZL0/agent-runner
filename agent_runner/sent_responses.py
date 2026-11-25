"""F425a: the sent responses: what the person answered in Needs you with no chat opened for it, kept so they can still
open one about it.

Each is a file of its own, <notes>/responses/<ns>-<pid>.json: {'id', 'item', 'title', 'question' (what its card asked),
'ask' (its whole ask), 'answer', 'note', 'at'}. Never a secret's value. `ui_model` keeps one when an answer settled the
item (`answer`, `need_give`, `pitch_no`), the snapshot carries them (`responses`), and `response_chat` takes one off as
it starts the chat about it. Nothing here starts a session or fails the answer it keeps."""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import time
from pathlib import Path

from agent_runner import state as S

KEEP = 30  # ponytail: a count alone, no age; the oldest go first
RID = re.compile(r'\d+-\d+')


def folder(c=None) -> Path:
    return (c or S.C).notes('responses', 'x').parent


def _file(rid: str) -> Path:
    return folder() / f'{rid}.json'


def _save(d: dict) -> None:
    f = _file(d['id'])
    tmp = f.with_suffix('.tmp')
    with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w', encoding='utf-8') as out:
        json.dump(d, out)
    os.replace(tmp, f)


def _files() -> list[Path]:
    """The kept ones, newest first."""
    try:
        fs = [f for f in folder().glob('*.json') if RID.fullmatch(f.stem)]
    except (OSError, AttributeError):  # no project
        return []
    return sorted(fs, key=lambda f: [int(x) for x in f.stem.split('-')], reverse=True)


def _one_line(s) -> str:
    return ' '.join(str(s or '').split())


def keep(item: str, title: str, question: str, ask: str, answer: str, note: str = '') -> str:
    """Keep one response: its id, '' when it could not. Never raises: the answer it records is done already."""
    rid = f'{time.time_ns()}-{os.getpid()}'
    try:
        _save({'id': rid, 'item': item, 'title': _one_line(title), 'question': question,
               'ask': ask, 'answer': answer, 'note': _one_line(note), 'at': time.time()})
        for f in _files()[KEEP:]:
            f.unlink(missing_ok=True)
        return rid
    except Exception as e:  # noqa: BLE001
        try:
            S.log(f'{item}: the answer is sent; it could not be kept as a sent response: {type(e).__name__}')
        except Exception:  # noqa: BLE001
            pass
        return ''


def recent() -> list[dict]:
    """The kept responses, newest first."""
    out = []
    for f in _files()[:KEEP]:
        try:
            d = json.loads(f.read_text(encoding='utf-8'))
        except (OSError, ValueError):  # taken meanwhile
            continue
        if isinstance(d, dict) and d.get('id') == f.stem and d.get('item'):
            out.append(d)
    return out


def take(rid: str) -> dict | None:
    """Take response `rid` off the list, for the one caller that gets it (None: gone, or no such id)."""
    if not isinstance(rid, str) or not RID.fullmatch(rid):
        return None
    f = _file(rid)
    mine = f.with_suffix('.taken')
    try:
        os.replace(f, mine)  # of two sends at once, one gets it
        d = json.loads(mine.read_text(encoding='utf-8'))
        mine.unlink(missing_ok=True)
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def put_back(d: dict) -> None:
    """The chat about `d` did not start."""
    try:
        _save(d)
    except OSError as e:
        S.log(f'{d.get("item")}: its sent response could not be put back: {e}')


def first_message(d: dict, state: str, words: str) -> str:
    """The first message of the chat about response `d`. Its start is what `control_settled.OPENED` reads the item from."""
    at = dt.datetime.fromtimestamp(d.get('at') or 0).strftime('%Y-%m-%d %H:%M')
    title = _one_line(d.get('title'))
    out = [f"About {d['item']}{f' ({title})' if title else ''}: I answered this in Needs you, and have more to say."]
    if q := d.get('question'):
        out.append(f'The question: {q}')
    if (ask := d.get('ask') or '') and ask != q:
        out.append(f'The whole ask: {ask}')
    out.append(f"My answer ({at}): {d.get('answer') or ''}")
    if d.get('note'):
        out.append(f"My note with it: {d['note']}")
    out.append(f'Its state now: {state}')
    out.append('The answer is sent already, so this message is no answer to the item. Settle or change nothing unless '
               'my words below ask for it.')
    out.append(f'My words:\n{words.strip()}')
    return '\n\n'.join(out)


def note_message(item: str, title: str, question: str, ask: str, answer: str, note: str) -> str:
    """F452: the first message of the chat about the `note` of an answer that closed `item`. Its start is what
    `control_settled.OPENED` reads the item from."""
    title = _one_line(title)
    out = [f"About {item}{f' ({title})' if title else ''}: my answer in Needs you closed this task, and it came with a "
           'note.']
    if question:
        out.append(f'The question: {question}')
    if ask and ask != question:
        out.append(f'The whole ask: {ask}')
    out.append(f'My answer: {answer}')
    out.append(f'My note with it: {note}')
    out.append('The task is closed, so no agent of it gets the note: act on the note now, in this chat.')
    return '\n\n'.join(out)
