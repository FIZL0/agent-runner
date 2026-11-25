#!/usr/bin/env python3
"""`plan drop` and `plan restore`.

    python3 tests/test_plan_drop.py          (no network, no agent, under a second)

Split out of tests/test_plan.py (C52), with the same checks.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from _check import check, eq, has, report

from agent_runner import plan  # noqa: E402

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
        out, real = io.StringIO(), plan.drop
        x = SimpleNamespace(say=lambda s: print(s) or 0)
        try:
            plan.drop = lambda *a: real(*a, **kw)
            with redirect_stdout(out):
                plan._p_drop(SimpleNamespace(id='U1a', rest=['no']), x)
        finally:
            plan.drop = real
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

if __name__ == '__main__':
    sys.exit(report([test_drop_parts, test_restore]))
