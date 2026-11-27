#!/usr/bin/env python3
"""C56: the run page model: a concept item framed on its card.

    python3 tests/test_ui_model_concept.py
"""
from __future__ import annotations
import datetime as dt
import json
from pathlib import Path
from unittest import mock
from _check import check, eq, report
from agent_runner import state as S  # noqa: E402
from agent_runner import ui_model as U  # noqa: E402
from _ui_model import in_tmp,TODO, NOW, fake_run, ran_by, chat, said  # noqa: E402


def test_concept_frame_f463(tmp: Path) -> None:
    """F463: a concept item carries the path of the run page's own copy of its options page, and its card frames it."""
    copy = tmp / 'K20.html'
    copy.write_text('<h1>Menu</h1><h2>Tabs</h2>', encoding='utf-8')
    eq(U.concept_frame({'label': 'CONCEPT', 'id': 'F462', 'concept': 'K20', 'copy': str(copy)}), 'concept/K20', 'its page path')
    with mock.patch.object(U, 'concept_copy', lambda k: str(copy) if k == 'K20' else ''):
        eq(U.concept_frame({'label': 'CONCEPT', 'id': 'F462', 'concept': 'K20'}), 'concept/K20', 'found by its K id')
        eq(U.concept_frame({'label': 'CONCEPT', 'id': 'F9', 'concept': 'K9'}), '', 'no copy: no frame')
        eq(U.concept_frame({'label': 'DECIDE', 'id': 'F462', 'concept': 'K20'}), '', 'not a concept: no frame')
        rows, _ = U.needs_rows([('CONCEPT', 'F462', 'K20', 'pick one', '', 'T', False)], dt.datetime.now())
        eq(rows[0].get('frame'), 'concept/K20', 'the snapshot row carries it')
    import subprocess
    from agent_runner import web as W
    PAGE_TEXT = W.PAGE.read_text(encoding='utf-8')
    fn = 'function conceptFrame(' + PAGE_TEXT.split('function conceptFrame(', 1)[1].split('\n/*', 1)[0]
    js = ("const S={frameFull:{}},I={ext:''},T='tok',esc=s=>String(s),tq=p=>p+'?t='+T;" + fn +
          ";console.log(JSON.stringify([conceptFrame({id:'F462',title:'Menu',frame:'concept/K20',url:'https://claude.ai/x'}),"
          "conceptFrame({id:'F1'}),(S.frameFull.F462=true,conceptFrame({id:'F462',frame:'concept/K20'}))]))")
    r = subprocess.run(['node', '-e', js], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs conceptFrame', r.stderr[-500:])
    card, none, full = json.loads(r.stdout)
    for want in ('<iframe src="concept/K20?t=tok"', 'sandbox="allow-scripts"', 'loading="lazy"', 'data-framefull="F462"',
                 '>Expand<', 'Open in claude.ai', 'href="https://claude.ai/x"'):
        check(want in card, f'the card frames it: {want}', card)
    eq(none, '', 'no page: no frame')
    check('cframe full' in full and '>Shrink<' in full and 'claude.ai' not in full, 'expanded, no claude.ai page', full)


def test_concept_opened_f197a(tmp: Path) -> None:
    """F197a: a concept row is New until its details popup is opened (the `concept_opened` action, the row's version),
    Updated after `plan concept-updated`, and cleared again by the next opening, on any device."""
    from agent_runner import concept_news
    fake_run(tmp)
    row = lambda: U.snapshot(up=True, now=NOW, links={})['concepts'][0]  # noqa: E731
    first = row()
    eq((first['concept'], first['news']), ('K5', 'new'), 'never opened: New')
    eq(U.act('concept_opened', concept='K5', version=first['version'])['ok'], True, 'the popup opened on one device')
    eq(row()['news'], '', 'opened: neither New nor Updated')
    concept_news.updated(S.C, 'K5', 'a fourth option')
    now = row()
    eq((now['news'], now['news_words']), ('updated', 'a fourth option'), 'updated after: Updated, with its words')
    eq(U.act('concept_opened', concept='K5', version=first['version'])['ok'], True, 'a stale popup on another device')
    eq(row()['news'], 'updated', 'an older version opened clears nothing newer')
    U.act('concept_opened', concept='K5', version=now['version'])
    eq(row()['news'], '', 'opened again: cleared for every device')
    eq(U.act('concept_opened', concept='../x', version='1')['ok'], False, 'a bad id is refused')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_concept_frame_f463), in_tmp(test_concept_opened_f197a)]))
