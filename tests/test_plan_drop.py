#!/usr/bin/env python3
"""`plan drop` and `plan restore`.

    python3 tests/test_plan_drop.py          (no network, no agent, under a second)

Split out of tests/test_plan.py (C52), with the same checks.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

from _check import check, eq, git, has, report

from agent_runner import plan, plan_drop, state as S  # noqa: E402

def test_drop_parts():
    print('plan: dropping the last part ticks a split parent only when a part landed')
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp) / 'plan'
        todo, done = plan.ensure(d / 'TODO.md', d / 'DONE.md')
        kw = dict(todo=todo, done=done)
        Path(todo).write_text('\n'.join([
            '# TODO', '', '### Next', '',
            '- [ ] **P1** the importer (split into P1a, P1b) | files: a.py',
            '- [ ] **P1a** the header',
            '- [ ] **P1b** the body',
            '- [ ] **R1** the parser (split into R1a, R1b)',
            '- [ ] **R1a** the words',
            '- [ ] **R1b** the numbers',
            '- [~] **S1** the writer (split into S1a) BLOCKED: DECIDE: which?',
            '- [ ] **S1a** a part',
            '- [ ] **U1** the printer (split into U1a)',
            '- [ ] **U1a** a part',
            '- [x] **T1a** by hand — dropped: no',
            '- [ ] **T1** the reader (split into T1a)', '']), encoding='utf-8')
        plan.archive(todo, done)
        eq(plan.drop('P1a', 'one task', **kw), [], 'P1b is still open, so P1 stays split')
        has(Path(todo).read_text(), r'\(split into P1a, P1b\)', 'and says so')
        has(Path(todo).read_text(), r'- \[ \] \*\*T1\*\* the reader\n', 'a drop ticked by hand counts as one')
        eq(plan.drop('P1b', 'one task', **kw), ['P1'], 'the last part: none landed, and the drop says so')
        has(Path(todo).read_text(), r'- \[ \] \*\*P1\*\* the importer \| files: a\.py\n', 'P1 is one whole task')
        eq(plan.archive(todo, done), 0, 'and stays so')
        plan.tick('R1a', plan_dir=d, **kw)
        eq(plan.drop('R1b', 'overtaken', **kw), [], 'one part of R1 landed')
        check('**R1**' not in Path(todo).read_text(), 'so R1 is ticked')
        has(Path(done).read_text(), r'- \[x\] \*\*R1\*\* the parser \(split into R1a, R1b\)', 'and archived')
        eq(plan.drop('S1a', 'no', **kw), ['S1'], 'a blocked parent is whole again')
        has(Path(todo).read_text(), r'- \[~\] \*\*S1\*\* the writer BLOCKED: DECIDE: which\?', 'still asking')
        plan.restore('P1a', **kw)
        plan.tick('P1a', plan_dir=d, **kw)
        plan.edit('P1', 'the importer (split into P1a, P1b)', todo=todo)
        eq(plan.archive(todo, done), 1, 'a part restored and then ticked has landed, so P1 ticks')

        import io
        from contextlib import redirect_stdout
        from types import SimpleNamespace
        from agent_runner import plan_drop
        out, real = io.StringIO(), plan_drop.drop
        x = SimpleNamespace(say=lambda s: print(s) or 0)
        try:
            plan_drop.drop = lambda *a: real(*a, **kw)
            with redirect_stdout(out):
                plan._p_drop(SimpleNamespace(id='U1a', rest=['no']), x)
        finally:
            plan_drop.drop = real
        has(out.getvalue(), r'^dropped U1a\nno part of U1 landed, so U1 is one whole task again', 'plan drop says it')


def test_restore():
    print('plan: restore brings a ticked or dropped task back open, same id and fields (F47)')
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp) / 'plan'
        todo, done = plan.ensure(d / 'TODO.md', d / 'DONE.md')
        kw = dict(todo=todo, done=done)
        plan.add('F', 'the parser | files: src/parse.py | test: test_parse', **kw)
        plan.add('B', 'the printer | files: src/print.py | after: F1', **kw)
        plan.add('C', 'keep me first | files: x.py', **kw)
        Path(todo).write_text(Path(todo).read_text().replace('after: F1', 'after: F1\n  - [ ] a sub-item'))
        before = {t: plan.section(todo, t) for t in ('F1', 'B1')}
        (d / 'tasks').mkdir()
        (d / 'tasks' / 'F1.md').write_text('# F1\n\n- [ ] **F1** the parser\n', encoding='utf-8')
        plan.tick('F1', plan_dir=d, **kw)
        plan.drop('B1', 'overtaken by C1', **kw)
        check('**F1**' not in Path(todo).read_text() and '**B1**' not in Path(todo).read_text(), 'both archived')

        plan.restore('F1', plan_dir=d, **kw)
        plan.restore('B1', 'after', 'C1', **kw)
        eq({t: plan.section(todo, t) for t in ('F1', 'B1')}, before,
           'restored open, same id, text, fields and sub-items; the dropped note gone')
        eq([l[4:] for l in plan.index(todo) if l.startswith('[ ] ')], ['F1', 'C1', 'B1'],
           'at the top by default, or where WHERE says')
        t = Path(done).read_text()
        check('**F1**' not in t and '**B1**' not in t, 'gone from DONE.md', t)
        has((d / 'tasks' / 'F1.md').read_text(), r'- \[ \] \*\*F1\*\*', 'its plan/tasks/<ID>.md reopened too')

        for tid, why in (('F1', 'still open'), ('Z9', 'no task')):
            try:
                plan.restore(tid, **kw)
                check(False, f'restore {tid} errors')
            except SystemExit as e:
                has(str(e), why, f'restore of a {why} id errors')
        eq([l[4:] for l in plan.index(todo) if l.startswith('[ ] ')], ['F1', 'C1', 'B1'], 'and changes nothing')


def test_restore_blocked():
    print('plan: restore puts a dropped blocked task back blocked, with its ask, and what waited on it waits (B808)')
    with tempfile.TemporaryDirectory() as tmp:
        r = Path(tmp) / 'proj'
        (r / 'plan').mkdir(parents=True)
        git(r, 'init', '-q')
        (r / '.gitignore').write_text('.runner/\n')
        (r / 'runner.toml').write_text('[run]\ntest = "true"\nremote = false\n')
        todo, done = plan.ensure(r / 'plan' / 'TODO.md', r / 'plan' / 'DONE.md')
        Path(todo).write_text('\n'.join([
            '# TODO', '', '### Next', '',
            '- [~] **D1** Pick | files: a.py BLOCKED: DECIDE: which? (asked 2026-11-25 09:00)',
            '- [~] **F2** Waits | files: b.py BLOCKED: (after D1) its code',
            '- [~] **F3** Asks then | files: c.py BLOCKED: (after D1) CONFIRM: look — once it is in',
            '- [~] **F4** Waits too | files: d.py',
            '  - [ ] a part BLOCKED: (after D1, F5) both',
            '- [ ] **F5** Open, says BLOCKED: in its words',
            '- [~] **F6** Changed since | files: f.py BLOCKED: (after D1) x',
            '- [~] **F7** Started since | files: g.py BLOCKED: (after D1) y',
            '- [~] **F8** Person | files: h.py BLOCKED: shelved: DECIDE: later?', '']), encoding='utf-8')
        git(r, 'add', '-A')
        git(r, 'commit', '-qm', 'start')
        S.init(r)
        kw = dict(todo=todo, done=done)
        n = S.C.notes('x').parent
        files = {f: f for f in ('asks/D1.json', 'asks/D1.taken', 'asks/D1/one.png', 'asks/D1.env', 'sheets/D1.json',
                                'sheets/D1.html', 'concepts/D1_sheet.html')}
        for f in files:
            (n / f).parent.mkdir(parents=True, exist_ok=True)
            (n / f).write_text(f, encoding='utf-8')
        here = lambda: {f: (n / f).read_text() for f in files if (n / f).exists()}  # noqa: E731
        start = {t: plan.section(todo, t) for t in ('D1', 'F2', 'F3', 'F4', 'F5', 'F6', 'F7', 'F8')}
        mtime = (n / 'asks/D1.json').stat().st_mtime_ns

        plan.drop('D1', 'no', **kw)
        plan.restore('D1', **kw)
        eq(({t: plan.section(todo, t) for t in start}, here()), (start, files), 'at once: all as it was')
        eq((n / 'asks/D1.json').stat().st_mtime_ns, mtime, 'the ask is still the one its block took')

        plan.drop('D1', 'no', **kw)
        eq(here(), {}, 'dropped: no ask and no secret where they were')
        plan.drop('F5', 'no', **kw)
        eq(sorted(t for t, _ in plan.reopen(todo)), ['F2', 'F3', 'F4', 'F6', 'F7'], 'the drop frees what waited')
        plan.note('F6', 'now do this', todo=todo)
        with mock.patch('agent_runner.row_hold.under_way', lambda c, t: 's1 is on it' if t == 'F7' else ''):
            check(plan.restore('D1', **kw), 'restore says it is blocked')
            check(not plan.restore('F5', 'after', 'F4', **kw), 'and that an open one is not')
        eq({t: plan.section(todo, t) for t in start if t not in ('F6', 'F7')},
           {t: s for t, s in start.items() if t not in ('F6', 'F7')}, 'blocked, and what waited waits again')
        for t in ('F6', 'F7'):
            has(plan.section(todo, t)[0], r'- \[ \]', f'{t}: noted or started since, so it stays open')
        eq(here(), files, 'its ask, pick sheet and secrets are back')
        check(not (n / 'dropped' / 'D1').exists(), 'nothing is left of what was kept')

        plan.drop('F8', 'no', **kw)
        plan.restore('F8', **kw)
        has(Path(todo).read_text(), r'- \[~\] \*\*F8\*\* .* BLOCKED: shelved: DECIDE: later\?\n', 'a shelved one is shelved')

        plan.drop('D1', 'no', **kw)
        env, d = n / 'dropped/D1/asks/D1.env', n / 'dropped/D1'
        check(env.exists(), 'secrets are kept')
        for age, left in ((plan_drop.KEEP_ENV, (True, False)), (plan_drop.KEEP, (False, False))):
            at = time.time() - age - 60
            os.utime(d, (at, at))
            plan_drop.sweep_kept(S.C)
            eq((d.exists(), env.exists()), left, 'a day for secrets, then the rest')
        plan.restore('D1', **kw)
        eq((plan.section(todo, 'D1'), here()), (start['D1'], {}), 'then it comes back blocked, less its ask file')

        import shutil
        for t in ('D1', 'F5'):  # dropped on another machine: no record here
            plan.drop(t, 'no', **kw)
            shutil.rmtree(n / 'dropped' / t)
            eq(plan.restore(t, **kw), t == 'D1', f'{t}: as its line reads, not its prose')
        (n / 'asks/F5.json').write_text('old', encoding='utf-8')
        plan.drop('F5', 'no', **kw)
        Path(done).write_text(Path(done).read_text(encoding='utf-8').replace('in its words', 'changed elsewhere'), encoding='utf-8')
        plan.restore('F5', **kw)
        check(not (n / 'asks/F5.json').exists(), "an older drop's record is not used")


if __name__ == '__main__':
    sys.exit(report([test_drop_parts, test_restore, test_restore_blocked]))
