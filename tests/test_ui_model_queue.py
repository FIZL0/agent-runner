#!/usr/bin/env python3
"""B866: an approved concept stays in Concepts, with its build's state, until its build task lands."""
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

TODO = """# TODO
- [ ] **F473** (follow-up, normal) Build the option a person approves on concept K23's page: Keyboard layout — approved (/concept/K23): option B
- [~] **F474** Build the option a person approves on concept K24's page: Themes
  - blocked: needs the person's go
- [~] **F475** Build the option a person approves on concept K25's page: Waiting
  - blocked: waiting for your OK on /concept/K25
"""


class Fake:
    def __init__(self, d: Path):
        self.d, self.todo = d, d / 'TODO.md'

    def notes(self, *parts):
        return self.d.joinpath('notes', *parts)


def test_approved_concept_stays():
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        (d / 'TODO.md').write_text(TODO, encoding='utf-8')
        (d / 'notes' / 'concepts').mkdir(parents=True)
        for tid in ('K23', 'K24', 'K25'):
            (d / 'notes' / 'concepts' / f'{tid}.html').write_text('<h2>Option A</h2>', encoding='utf-8')
        with mock.patch.object(U.S, 'C', Fake(d)), mock.patch.object(U.need_detail, 'task_lines', lambda: {}):
            _, cs = U.needs_rows([], dt.datetime.now())
            eq([(c['id'], c['build'], c['building']) for c in cs], [('K23', 'F473', 'building'), ('K24', 'F474', 'parked')],
               'approved concepts listed with their build; the one still waiting for an OK is not')
            check(cs[0]['copy'].endswith('K23.html') and cs[0]['title'].endswith('(approved: building F473)')
                  and cs[0]['approved'] == 'approved: building F473', 'page link and mark', cs[0])
            (d / 'TODO.md').write_text(TODO.replace('[ ] **F473**', '[x] **F473**'), encoding='utf-8')
            _, cs = U.needs_rows([], dt.datetime.now())
            eq([c['id'] for c in cs], ['K24'], 'gone once its build lands')


if __name__ == '__main__':
    raise SystemExit(report([test_approved_concept_stays]))
