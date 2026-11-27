"""F197a: a concept's New and Updated, one record shared by every device that opens the run app.

A concept is New until its details popup is first opened, and Updated (with a few words on what changed) when its
page changed after that. The record lives in <notes>/concepts/news.json, keyed by the concept's id:
{'n': how many times its page was updated, 'what': the words of the last update, 'opened': the version last opened}.
A version is the update count and a short hash of the local page copy, so a copy changed with no `plan
concept-updated` still reads as Updated (with no words).
"""
from __future__ import annotations
import hashlib
import json
import shutil
from pathlib import Path

NEW, UPDATED = 'new', 'updated'


def _file(c) -> Path:
    return c.notes('concepts', 'news.json')


def _read(c) -> dict:
    try:
        got = json.loads(_file(c).read_text(encoding='utf-8'))
        return got if isinstance(got, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(c, data: dict) -> None:
    from agent_runner.plan import write_atomic
    write_atomic(_file(c), json.dumps(data, indent=1, sort_keys=True) + '\n')


def version(c, cid: str, copy: str = '') -> str:
    """Concept `cid`'s version as the run sees it now: '<updates>-<copy hash>' ('-' with no copy)."""
    n = (_read(c).get(cid) or {}).get('n', 0)
    try:
        h = hashlib.sha1(Path(copy).read_bytes()).hexdigest()[:8] if copy else ''
    except OSError:
        h = ''
    return f'{n}-{h}'


def news(c, cid: str, copy: str = '') -> dict:
    """{'version', 'news': 'new' | 'updated' | '', 'news_words'} for a concept row."""
    rec, v = _read(c).get(cid) or {}, version(c, cid, copy)
    if 'opened' not in rec:
        return {'version': v, 'news': NEW, 'news_words': ''}
    if rec['opened'] == v:
        return {'version': v, 'news': '', 'news_words': ''}
    seen_n = str(rec['opened']).partition('-')[0]
    words = rec.get('what', '') if seen_n != str(rec.get('n', 0)) else ''
    return {'version': v, 'news': UPDATED, 'news_words': words}


def opened(c, cid: str, ver: str) -> None:
    """Concept `cid`'s details popup was opened showing version `ver`: it is no longer New, nor Updated up to `ver`."""
    data = _read(c)
    data.setdefault(cid, {})['opened'] = ver
    _write(c, data)


def updated(c, cid: str, what: str, page: str = '') -> str:
    """A chat updated concept `cid`'s page (`what`: what changed). `page`: an updated local file, copied over the
    run's copy when given. Returns the new version."""
    if page:
        shutil.copyfile(page, c.notes('concepts', f'{cid}.html'))
    data = _read(c)
    rec = data.setdefault(cid, {})
    rec['n'], rec['what'] = rec.get('n', 0) + 1, ' '.join(what.split())[:200]
    _write(c, data)
    copy = c.notes('concepts', f'{cid}.html')
    return version(c, cid, str(copy) if copy.is_file() else '')
