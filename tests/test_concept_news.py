#!/usr/bin/env python3
"""F197a: a concept's New and Updated (agent_runner/concept_news.py) and its plan commands."""
from __future__ import annotations
import contextlib
import io
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _check import check, eq, report  # noqa: E402
from agent_runner import concept_news as N  # noqa: E402


class _C:
    def __init__(self, root: Path):
        self.root = root

    def notes(self, *parts):
        p = self.root.joinpath(*parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p


def test_news(tmp: Path) -> None:
    c = _C(tmp)
    copy = c.notes('concepts', 'K5.html')
    copy.write_text('<h1>A</h1>', encoding='utf-8')
    eq(N.news(c, 'K5', str(copy))['news'], 'new', 'never opened: New')
    v = N.news(c, 'K5', str(copy))['version']
    N.opened(c, 'K5', v)
    eq(N.news(c, 'K5', str(copy)), {'version': v, 'news': '', 'news_words': ''}, 'opened: neither')
    page = tmp / 'new.html'
    page.write_text('<h1>B</h1>', encoding='utf-8')
    v2 = N.updated(c, 'K5', 'option  C added', str(page))
    eq(copy.read_text(encoding='utf-8'), '<h1>B</h1>', 'the local copy is refreshed')
    got = N.news(c, 'K5', str(copy))
    eq((got['news'], got['news_words'], got['version']), ('updated', 'option C added', v2), 'Updated, with words')
    c2 = _C(tmp)  # another device reads the same record
    eq(N.news(c2, 'K5', str(copy))['news'], 'updated', 'the other device sees Updated too')
    N.opened(c2, 'K5', v)  # an old popup's version clears nothing newer
    eq(N.news(c, 'K5', str(copy))['news'], 'updated', 'an older version opened: still Updated')
    N.opened(c2, 'K5', v2)
    eq(N.news(c, 'K5', str(copy))['news'], '', 'opened again on the other device: cleared for both')
    copy.write_text('<h1>C</h1>', encoding='utf-8')
    eq(N.news(c, 'K5', str(copy))['news_words'], '', 'a copy changed with no command: Updated, no words')
    eq(N.news(c, 'K5', str(copy))['news'], 'updated', '... still Updated')


def test_commands(tmp: Path) -> None:
    from agent_runner import plan
    a = plan._parse_command(['concept-updated', 'K7', 'new', 'option'])
    eq((a.cmd, a.id, a.rest), ('concept-updated', 'K7', ['new', 'option']), 'concept-updated parses')
    a = plan._parse_command(['concept-opened', 'K7', '0-abc'])
    eq((a.cmd, a.id, a.version), ('concept-opened', 'K7', '0-abc'), 'concept-opened parses')
    c = _C(tmp)

    class X:
        pass
    x = X()
    x.c, x.say = c, lambda s: (print(s), 0)[1]
    with contextlib.redirect_stdout(io.StringIO()):
        eq(a.run(a, x), 0, 'concept-opened runs')
    eq(N.news(c, 'K7')['news'], 'updated', 'opened 0-abc, now 0-: Updated')
    a = plan._parse_command(['concept-updated', 'K7', 'more'])
    with contextlib.redirect_stdout(io.StringIO()):
        eq(a.run(a, x), 0, 'concept-updated runs')
    eq(N.news(c, 'K7')['news_words'], 'more', 'its words')
    with contextlib.redirect_stderr(io.StringIO()):
        eq(a.run(plan._parse_command(['concept-updated', 'K7', 'x', '--file', str(tmp / 'none')]), x), 2,
           'a missing --file refused')
    check(True, 'done')


for t in (test_news, test_commands):
    with tempfile.TemporaryDirectory() as d:
        t(Path(d))
raise SystemExit(report([]))
