#!/usr/bin/env python3
"""F438: the level high: filed behind the critical tasks, tried after them and ahead of the rest, shown as high.

    python3 tests/test_pri_high.py        (a temp repo, a few seconds)
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from _check import eq, git, has, report

from agent_runner import plan as P, release_moves as M, runner as R, sched as S, tui as T, ui_model as U  # noqa: E402
from _web import logic_js  # noqa: E402


def test_place(tmp: Path) -> None:
    print('high: filed behind the critical and earlier high tasks of the leading section')
    todo, done = tmp / 'TODO.md', tmp / 'DONE.md'
    todo.write_text('# TODO\n\n### Next\n\n- [ ] **A1** queued first\n- [ ] **A2** queued second\n\n### Follow-ups\n\n'
                    '- [ ] **A3** (follow-up, normal) the usual\n', encoding='utf-8')
    kw = dict(todo=todo, done=done)
    h1 = P.add('T', 'important', pri='high', **kw)
    c1 = P.add('T', 'breaks work', pri='critical', **kw)
    h2 = P.add('T', 'important too', pri='high', **kw)
    has(todo.read_text(encoding='utf-8'), rf'\*\*{h1}\*\* \(follow-up, high\) important', 'tagged')
    eq([t for _, _, t, _, _ in P.iter_tasks(P.lines(todo))], [c1, h1, h2, 'A1', 'A2', 'A3'], 'the order')
    P.edit('A3', pri='high', todo=todo)
    eq([t for _, _, t, _, _ in P.iter_tasks(P.lines(todo))], [c1, h1, h2, 'A3', 'A1', 'A2'], 'plan edit --pri high moves it')
    todo.write_text('# TODO\n\n### Critical\n\n- [ ] **B1** red\n\n### Phase 1\n\n- [ ] **B2** queued\n', encoding='utf-8')
    h3 = P.add('T', 'important', pri='high', **kw)
    eq(P.index(todo), ['# TODO', '### Critical', '[ ] B1', '### Phase 1', f'[ ] {h3}', '[ ] B2'],
       'never in a plan\'s own Critical section')
    todo.write_text('# TODO\n\n### Critical\n\n- [ ] **B1** red\n\n### Follow-ups\n\n- [ ] **B2** usual\n', encoding='utf-8')
    h4 = P.add('T', 'important', pri='high', **kw)
    eq(P.index(todo), ['# TODO', '### Critical', '[ ] B1', '### Next', f'[ ] {h4}', '### Follow-ups', '[ ] B2'],
       'with no section of the person\'s own, a Next one is made')


def test_choose(tmp: Path) -> None:
    print('high: the next free slot takes a critical task, then a high one, then the rest, wherever the lines stand')
    repo = tmp / 'choose'
    (repo / 'plan').mkdir(parents=True)
    git(repo, 'init', '-q', '-b', 'main')
    (repo / 'plan/TODO.md').write_text(
        '# TODO\n\n### Next\n\n- [ ] **N1** normal | files: n.py\n- [ ] **V1** (follow-up, high) Release: one | files: v.py\n'
        '- [ ] **C1** (follow-up, critical) (alone) fix | files: c.py\n\n### Follow-ups\n\n'
        '- [ ] **H1** (follow-up, high) important | files: h.py\n- [ ] **H2** (follow-up, high) waits | files: x.py | after: N1\n',
        encoding='utf-8')
    (repo / 'plan/DONE.md').write_text('# DONE\n', encoding='utf-8')
    (repo / 'runner.toml').write_text('[run]\ntest = "true"\nmin_free_gb = 0\nremote = false\n', encoding='utf-8')
    (repo / '.gitignore').write_text('.runner/\n', encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'start')
    R.init(repo)
    M.rewait('V1', R.C.todo)
    has((repo / 'plan/TODO.md').read_text(encoding='utf-8'), r'\*\*V1\*\* Release: one', 'a moved release is no longer high')
    git(repo, 'commit', '-qam', 'moved')
    h = S.held({}, 'main')
    eq((sorted(h.high), sorted(h.critical)), (['H1', 'H2'], ['C1']), 'the levels, apart')
    eq([S.choose(h, t, 'main')[0] for t in (set(), {'C1'}, {'C1', 'H1'})], ['C1', 'H1', 'N1'],
       'critical, high, then the rest; a high one that waits holds nothing back')
    n1 = next(t for t in h.todo if t[0] == 'N1')
    eq(S.choose(S.held({1: n1}, 'main'), set(), 'main'), None, 'a high task does not start while a critical (alone) one takes its turn')
    q = {r['id']: r for r in U.snapshot(up=True, links={})['queue']}
    eq((q['H1']['pri'], q['H1']['state'], q['H2']['state']), ('high', 'ready', 'after'), 'the queue rows')


def test_shown() -> None:
    print('high: its words on the run page and in the terminal UI; the Priority control steps through the levels')
    row = {'id': 'H1', 'pri': 'high', 'state': 'ready'}
    waits = {**row, 'state': 'after', 'after_title': 'N1 normal'}
    eq(logic_js([['planWords', row, []], ['planWords', waits, []]]),
       ['High priority: goes ahead of normal tasks, as soon as a slot is free', 'Waits for N1 normal'], 'the page')
    page = T.RunPage({'queue': [row]}, get_snap=lambda: {'queue': [row]}, attrs={})
    eq((page.queue_tag(row), page.queue_tag(waits)[1]), (('high', 'yellow'), 'dim'), 'the terminal UI')
    eq(page.form(row)['pri'], 'high', 'its direct edit starts at high')
    eq([P.next_pri(p) for p in ('normal', 'high', 'critical', 'low')], ['high', 'critical', 'normal', 'high'], 'the steps')


if __name__ == '__main__':
    with tempfile.TemporaryDirectory() as d:
        sys.exit(report([lambda: test_place(Path(d)), lambda: test_choose(Path(d)), test_shown]))
