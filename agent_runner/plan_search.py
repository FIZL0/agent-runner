"""F212: the Plan view's search: which tasks of TODO.md and DONE.md match words or a task id.

A task is searched whole: its id, its line and every line under it. Case never matters, every character stands for
itself, and several words must all be there, in any order. Best first: the task whose id was typed, then ids that
start with it, then titles, then the rest of the text; among equals, open tasks in plan order and done ones newest
first. Reads only.
"""
from __future__ import annotations

from agent_runner import plan as P
from agent_runner import state as S
from agent_runner import ui_model as U

DONE_MAX = 30  # done tasks in one answer; the rest are counted
EXACT, PREFIX, TITLE, TEXT = range(4)


def rank(words: list[str], tid: str, title: str, text: str) -> int | None:
    """How well the task matches the folded `words`, lower is better; None when a word is not in it. Of several words
    only one with a digit counts as an id: a lone letter among words is not asking for a kind."""
    tid, title, text = tid.casefold(), title.casefold(), text.casefold()
    if not all(w in tid or w in text for w in words):
        return None
    ids = words if len(words) == 1 else [w for w in words if any(c.isdigit() for c in w)]
    if tid in ids:
        return EXACT
    if any(tid.startswith(w) for w in ids):
        return PREFIX
    return TITLE if all(w in title or w in tid for w in words) else TEXT


def rows(ls: list[str]) -> list[dict]:
    """Every task of a plan file's lines: its id, title, group ('open', 'parked' or 'done'), state and whole text."""
    out = []
    for section, box, tid, rest, i in P.iter_tasks(ls):
        if box not in ' ~':
            group = 'done'
            state = 'dropped' if P._dropped(ls, i) else 'done'
        elif P._shelved(ls, i):
            group, state = 'parked', 'shelved'
        elif box == ' ' and U.task_pri(rest, section) == 'later':
            group = state = 'parked'
        else:
            group = state = 'open'
        out.append({'id': tid, 'title': P.short_title(rest, 200), 'group': group, 'state': state,
                    'text': '\n'.join([rest, *P._item_block(ls, i)[1:]])})
    return out


def search(query: str, todo=None, done=None) -> dict:
    """{'ok', 'q', 'open', 'parked', 'done': [{'id', 'title', 'state'}], 'more': done tasks left out}. A plan that
    cannot be read is {'ok': False, 'q', 'out'}."""
    out: dict = {'ok': True, 'q': query, 'open': [], 'parked': [], 'done': [], 'more': 0}
    words = query.casefold().split()
    if not words:
        return out
    try:
        todo = todo or S.C.todo
        with open(todo, encoding='utf-8', errors='replace') as f:  # P.lines calls a missing plan an empty one
            first = rows(f.read().splitlines())
        rest = rows(P.lines(done or S.C.done))
    except OSError as e:
        return {'ok': False, 'q': query, 'out': f'The plan could not be read ({type(e).__name__}).'}
    tasks = {t['id']: t for t in first}  # a task reopened by hand is open, whatever the archive says
    tasks |= {t['id']: t for t in rest if t['id'] not in tasks}
    found: dict[str, list] = {'open': [], 'parked': [], 'done': []}
    for at, t in enumerate(tasks.values()):
        r = rank(words, t['id'], t['title'], t['text'])
        if r is not None:
            found[t['group']].append((r, -at if t['group'] == 'done' else at, t))
    for group, hits in found.items():
        out[group] = [{k: t[k] for k in ('id', 'title', 'state')} for _, _, t in sorted(hits, key=lambda h: h[:2])]
    out['more'] = max(0, len(out['done']) - DONE_MAX)
    out['done'] = out['done'][:DONE_MAX]
    return out
