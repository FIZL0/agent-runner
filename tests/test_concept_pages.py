#!/usr/bin/env python3
"""F457: Concepts lists every page served at /concept/<ID> whose task is still open, not only concepts."""
from __future__ import annotations

import datetime as dt
import sys
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _check import check, eq, report  # noqa: E402

from agent_runner import ui_model as U  # noqa: E402
from agent_runner import web as W  # noqa: E402

TODO = """# TODO
- [ ] **F1** Film the videos to watch | files: a.py
- [x] **F2** An old report
- [~] **K3** Pick a layout
- [ ] **F4** No page at all
"""


class Fake:
    def __init__(self, d: Path):
        self.d, self.todo = d, d / 'TODO.md'

    def notes(self, *parts):
        return self.d.joinpath('notes', *parts)


def test_pages_are_listed():
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        (d / 'TODO.md').write_text(TODO, encoding='utf-8')
        (d / 'notes' / 'concepts').mkdir(parents=True)
        for tid in ('F1', 'F2', 'K3'):
            (d / 'notes' / 'concepts' / f'{tid}.html').write_text('<h2>Option A</h2>', encoding='utf-8')
        waiting = [('CONCEPT', 'K3', 'K3', 'waiting for your OK', '/concept/K3', 'Pick a layout', False, '')]
        with mock.patch.object(U.S, 'C', Fake(d)), mock.patch.object(U.need_detail, 'task_lines', lambda: {}):
            needs, cs = U.needs_rows(waiting, dt.datetime.now())
            eq([c['id'] for c in cs], ['K3', 'F1'], 'the concept once, the open task\'s page, not the done one')
            f1 = cs[1]
            check(f1['page'] and f1['title'].startswith('Film the videos') and f1['copy'].endswith('F1.html')
                  and not f1['waits'], 'the page row has its title and local copy, with no .url file', f1)
            check(not cs[0].get('page'), 'the concept row is unchanged', cs[0])
            snap = W.with_extras({'concepts': cs})
            eq(snap['concepts'][1]['options'], [], 'no Pick/OK on a page row')
            waiting.append(('CONFIRM', 'F1', '', 'watch them', '', 'Film', False, ''))
            _, cs = U.needs_rows(waiting, dt.datetime.now())
            check(cs[1]['waits'], 'a page whose task has a Needs you item says so', cs)


def test_chat_pages_are_listed():
    """B875: a page a chat published has no task, and is listed while recent."""
    import os
    import time
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        (d / 'TODO.md').write_text(TODO, encoding='utf-8')
        c = d / 'notes' / 'concepts'
        c.mkdir(parents=True)
        (c / 'chat1abc.html').write_text('<title>One Work page</title>', encoding='utf-8')
        (c / 'chat1def.html').write_text('<p>no title</p>', encoding='utf-8')
        old = c / 'chat1old.html'
        old.write_text('<title>Old</title>', encoding='utf-8')
        os.utime(old, (time.time() - 30 * 86400,) * 2)
        with mock.patch.object(U.S, 'C', Fake(d)), mock.patch.object(U.need_detail, 'task_lines', lambda: {}):
            _, cs = U.needs_rows([], dt.datetime.now())
        eq([(r['id'], r['title']) for r in cs], [('chat1abc', 'One Work page'), ('chat1def', 'A page from a chat')],
           'recent chat pages listed, with their title; an old one not')
        check(all(r['page'] and r['copy'].endswith('.html') for r in cs), 'they are page rows', cs)


if __name__ == '__main__':
    raise SystemExit(report([test_pages_are_listed, test_chat_pages_are_listed]))
