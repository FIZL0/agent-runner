#!/usr/bin/env python3
"""The task list: every mutator as a round trip in a temporary directory, read back as text.

    python3 tests/test_plan.py          (no network, no agent, under a second)

Why these: plan.py edits files in place, and a bug there does not raise — it quietly eats a task line,
and nobody notices until a "finished" task turns out never to have been done.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from _check import ROOT, check, eq, git, has, report, run

from agent_runner import plan  # noqa: E402


def test_plan_roundtrip():
    print('plan: add / next / move / note / block / unblock / tick / archive')
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp) / 'plan'
        todo, done = plan.ensure(d / 'TODO.md', d / 'DONE.md')
        check(os.path.exists(todo) and os.path.exists(done), 'ensure creates both files in a fresh checkout')
        kw = dict(todo=todo, done=done)

        a = plan.add('D', 'the parser | files: src/parse.py', **kw)
        b = plan.add('D', 'the printer | files: src/print.py, docs/API.md', **kw)
        c = plan.add('F', 'the formatter | files: src/fmt.py', **kw)
        eq((a, b, c), ('D1', 'D2', 'F1'), 'add hands out the next free id per prefix')
        eq(plan.next_task(todo=todo), 'F1', 'add puts a new task at the top, so next_task is the newest')

        plan.move('D1', 'top', todo=todo)
        eq(plan.next_task(todo=todo), 'D1', 'move <ID> top makes it the next task')
        plan.move('F1', 'after', 'D1', todo=todo)
        eq([l[4:] for l in plan.index(todo) if l.startswith('[ ] ')], ['D1', 'F1', 'D2'],
           'move <ID> after <ID> puts it straight behind')

        plan.note('D2', 'the API doc is the contract: keep it in step', todo=todo)
        has(Path(todo).read_text(), r'\*\*D2\*\*.*keep it in step', 'note appends to the task line')

        plan.block('F1', 'needs a style guide from a human', todo=todo)
        has(Path(todo).read_text(), r'- \[~\] \*\*F1\*\*.*BLOCKED: needs a style guide',
            'block marks [~] and says what would unblock it')
        eq(plan.next_task(todo=todo), 'D1', 'a blocked task is not the next task')
        plan.unblock('F1', 'guide written', todo=todo)
        text = Path(todo).read_text()
        check('BLOCKED' not in text, 'unblock drops the BLOCKED note')
        has(text, r'- \[ \] \*\*F1\*\*.*guide written', 'unblock keeps the line and notes why')

        (d / 'tasks').mkdir()
        (d / 'tasks' / 'D1.md').write_text('# D1\n\n- [ ] **D1** the parser\n', encoding='utf-8')
        eq(plan.tick('D1', todo=todo, done=done, plan_dir=d), 1, 'tick archives the ticked line')
        check('**D1**' not in Path(todo).read_text(), 'the ticked task is gone from TODO.md')
        has(Path(done).read_text(), r'- \[x\] \*\*D1\*\* the parser', 'with its text intact in DONE.md')
        has((d / 'tasks' / 'D1.md').read_text(), r'- \[x\] \*\*D1\*\*', 'and ticked in its own plan/tasks/<ID>.md')
        (d / 'L1.md').write_text('# L1\n', encoding='utf-8')
        eq(plan.long_form(d, 'L1'), d / 'L1.md', 'a long form still at plan/<ID>.md counts')
        eq(plan.long_form(d, 'L2'), d / 'tasks' / 'L2.md', 'a new one goes in plan/tasks/')
        eq(plan.next_id('D', [todo, done]), 'D3', 'ids are never reused: D1 is archived, the next is D3')
        eq(plan.next_id('D1', [todo, done]), 'D1a', "a task's id gives its first subtask")
        eq(plan.next_id('D1a', [todo, done]), 'D1a1', "and a subtask's its own")

        Path(todo).write_text(Path(todo).read_text().replace('- [ ] **D2**', '- [x] **D2**'), encoding='utf-8')
        eq(plan.archive(todo, done), 1, 'archive picks up a tick nobody moved (a hand edit, a merge)')
        eq(plan.archive(todo, done), 0, 'archive is a no-op the second time')
        eq([l[4:] for l in plan.index(todo) if l.startswith('[ ] ')], ['F1'], 'one open task left')
        check(not list(d.glob('*.tmp')), 'no .tmp files left behind by the atomic writes')

        before = os.stat(todo).st_mtime_ns
        plan._write(todo, plan.lines(todo))
        eq(os.stat(todo).st_mtime_ns, before, '_write is a no-op when the content is identical')

        missing = subprocess.run([sys.executable, '-c', 'import sys;sys.path.insert(0,%r);'
                                  'from agent_runner import plan;plan._find(["x"],"ZZ9")' % str(ROOT)],
                                 capture_output=True, text=True)
        check(missing.returncode != 0 and 'no task' in missing.stderr,
              'an unknown id fails loudly instead of silently doing nothing', missing.stderr[-300:])


def test_plan_reopen():
    print('plan: a block that waits on a task reopens when that task is done')
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp) / 'plan'
        todo, done = plan.ensure(d / 'TODO.md', d / 'DONE.md')
        kw = dict(todo=todo, done=done)
        for text in ('the menu | files: menu.py', 'the settings | files: settings.py', 'the lobby | files: lobby.py', 'a demo | files: d.py'):
            plan.add('P', text, **kw)
        plan.block('P2', "needs P1's menu (in flight) and V22's split, done long ago", todo=todo)
        has(Path(todo).read_text(), r'\*\*P2\*\*.* BLOCKED: \(after P1\) needs',
            'block reads the open ids off WHY, and leaves the done or unknown ones out')
        plan.block('P3', 'waits on two', todo=todo, after=['P1', 'P2'])
        plan.block('P4', 'needs a human to record a demo (P1 is unrelated)', todo=todo, after=[])
        has(Path(todo).read_text(), r'\*\*P4\*\*.* BLOCKED: needs a human', 'after=[] records no dependency')
        eq(plan.reopen(todo), [], 'nothing reopens while what it waits on is open')
        plan.tick('P1', **kw)
        eq(plan.reopen(todo), [('P2', ['P1'])], 'a block whose tasks are all done reopens')
        text = Path(todo).read_text()
        has(text, r'^- \[ \] \*\*P2\*\*.*reopened: P1 landed$', 'as [ ], its BLOCKED gone, and says why')
        has(text, r'^- \[~\] \*\*P3\*\*', 'one that also waits on a reopened task stays blocked')
        plan.tick('P2', **kw)
        eq([t for t, _ in plan.reopen(todo)], ['P3'], 'and reopens once the last of its list is done')
        has(Path(todo).read_text(), r'^- \[~\] \*\*P4\*\*', 'a block that names no task is never reopened')
        eq(plan.reopen(todo), [], 'reopen is idempotent')
        # B40: prose that quotes the block marker keeps its files, through block and unblock
        plan.add('P', 'fields() cuts at " BLOCKED: " in prose | files: q.py, r.py', **kw)
        def line():
            return next(l for l in plan.lines(todo) if '**P5**' in l)
        eq(plan.files_on_line(line()), ['q.py', 'r.py'], 'a quoted marker keeps the files')
        plan.block('P5', 'needs a human', todo=todo, after=[])
        eq(plan.files_on_line(line()), ['q.py', 'r.py'], 'and keeps them once blocked')
        plan.unblock('P5', 'back', todo=todo)
        last = line()
        check(last.endswith('| files: q.py, r.py — back') and 'needs a human' not in last,
              'unblock drops only the real block, not the quoted marker: ' + last)


def test_plan_index_and_sections():
    print('plan: index, section lookup, files on a line')
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        git(root, 'init', '-q')
        (root / 'docs').mkdir()
        (root / 'docs/API.md').write_text('x\n', encoding='utf-8')
        (root / 'README.md').write_text('x\n', encoding='utf-8')
        git(root, 'add', '-A')
        d = root / 'plan'
        todo, _ = plan.ensure(d / 'TODO.md', d / 'DONE.md')
        Path(todo).write_text('\n'.join([
            '# TODO', '', '### Next (in this order)', '',
            '- [ ] **R1** the parser | files: src/parse.py, API.md | test: tests/test_parse.py | journal: r1-parser',
            '  - a sub-line that belongs to R1',
            '- [~] **R2** the printer | files: src/print.py BLOCKED: needs R1',
            '', '### Stretch', '', '- [ ] **K1** a web page | files: web/index.html', '']), encoding='utf-8')
        eq(plan.index(todo), ['# TODO', '### Next (in this order)', '[ ] R1', '[~] R2', '### Stretch', '[ ] K1'],
           'index is headings and ids only — the whole backlog in a screenful')
        eq(plan.section(todo, 'R1'),
           ['- [ ] **R1** the parser | files: src/parse.py, API.md | test: tests/test_parse.py | journal: r1-parser',
            '  - a sub-line that belongs to R1'], 'a task by id brings its sub-lines with it')
        eq(plan.section(todo, 'Stretch'), ['### Stretch', '', '- [ ] **K1** a web page | files: web/index.html'],
           'a section by heading substring')
        eq(plan.section(todo, 'nope'), [], 'an unknown name is empty, not an error')
        eq(plan.fields('- [ ] **R1** a — b | files: src/parse.py, `API.md` | after: R0 | test: t1 — a note BLOCKED: x'),
           {'files': ['src/parse.py', 'API.md'], 'after': ['R0'], 'test': ['t1']},
           'keyed fields are comma lists; a value ends at the next field, a note or a BLOCKED')
        eq(plan.files_on_line('mentions notes.py in prose | files: new.py'), ['new.py'],
           'the files are the `files:` field; prose names none')
        eq(plan.files_on_line('mentions notes.py in prose'), [], 'and a line without one names none')


def test_brief():
    print('plan: brief')
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        git(root, 'init', '-q')
        (root / 'plan').mkdir()
        (root / 'docs').mkdir()
        (root / 'docs/API.md').write_text('a\nb\nc\n', encoding='utf-8')
        (root / 'runner.toml').write_text('[plan]\njournal = "journal"\n', encoding='utf-8')
        (root / 'plan/TODO.md').write_text(
            '# TODO\n\n### Next\n\n- [ ] **D3** the printer | files: docs/API.md, src/new.py | test: none | journal: d3-printer\n',
            encoding='utf-8')
        (root / 'plan/DONE.md').write_text('# DONE\n', encoding='utf-8')
        (root / 'plan/D3.md').write_text('# D3 — the printer\n\nThe long form.\n', encoding='utf-8')
        j = root / 'journal/2026-01-02-d3-printer'
        j.mkdir(parents=True)
        (j / '1-FIRST.md').write_text('# first pass\n', encoding='utf-8')
        (j / '2-SECOND.md').write_text('# needs the human\n\nthe newest word.\n', encoding='utf-8')
        git(root, 'add', '-A')
        out = '\n'.join(plan.brief('D3', root=root))
        has(out, r'## Task D3', 'brief leads with the task')
        has(out, r'\*\*D3\*\* the printer', 'brief pastes the task line')
        has(out, r'The long form\.', 'brief pastes the long form')
        has(out, r'1-FIRST\.md · 2-SECOND\.md', 'brief lists the journal files ([plan] journal)')
        has(out, r'the newest word\.', 'brief pastes the NEWEST journal entry (whose move it is)')
        check('first pass' not in out, 'brief does not paste the older entries')
        has(out, r'`docs/API\.md` \(3 lines\)', 'brief gives each file its length')
        has(out, r'`src/new\.py` \(missing — this task creates it\)', 'brief says when a file does not exist yet')
        cut = plan.JOURNAL_MAX
        (j / '3-LONG.md').write_text('x' * (cut + 500), encoding='utf-8')
        out = '\n'.join(plan.brief('D3', root=root))
        has(out, rf'first {cut} chars', 'a huge journal entry is capped, and says so')
        check(len(out) < cut + 4000, 'and the whole brief stays bounded')
        k = root / 'journal/K4'  # the `id` layout: notes.md, then a repeat attempt one folder down
        (k / '2026-03-04-retry').mkdir(parents=True)
        (k / 'notes.md').write_text('first attempt\n', encoding='utf-8')
        (k / '2026-03-04-retry/notes.md').write_text('the retry word\n', encoding='utf-8')
        with open(root / 'plan/TODO.md', 'a', encoding='utf-8') as f:
            f.write('- [ ] **K4** another\n')
        out = '\n'.join(plan.brief('K4', root=root))
        has(out, r'Journal journal/K4/: 2026-03-04-retry/notes\.md · notes\.md', 'a journal/<ID>/ folder is found')
        has(out, r'the retry word', 'and its newest (dated) attempt is pasted')
        check('first attempt' not in out, 'not the first one')
        r = run(root, 'plan', 'brief', 'D3')
        check(r.returncode == 0 and '## Task D3' in r.stdout, '`run plan brief` works from the repo', r.stderr)
        r = run(root / 'docs', 'plan', 'block', 'D3', '--after', 'X9', 'waits on X9')
        has((root / 'plan/TODO.md').read_text(), r'BLOCKED: \(after X9\) waits on X9',
            '`run plan block --after` from a subdirectory edits the repo\'s plan')


def test_brief_outline():
    print('plan: brief with [plan] outline')
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        git(root, 'init', '-q')
        (root / 'plan').mkdir()
        (root / 'src').mkdir()
        (root / 'src/ab.py').write_text('def one():\n    pass\n\ndef two():\n    pass\n', encoding='utf-8')
        (root / 'outline.py').write_text('import sys\nfor l in open(sys.argv[1]):\n'
                                          '    print(l.rstrip()) if l.startswith("def ") else None\n')
        (root / 'runner.toml').write_text('[plan]\noutline = "python3 outline.py {file}"\n', encoding='utf-8')
        (root / 'plan/TODO.md').write_text('# TODO\n\n### Next\n\n- [ ] **D1** both | files: src/ab.py, src/new.py\n',
                                           encoding='utf-8')
        (root / 'plan/DONE.md').write_text('# DONE\n', encoding='utf-8')
        git(root, 'add', '-A')
        out = '\n'.join(plan.brief('D1', root=root))
        has(out, r'`src/ab\.py` \(5 lines\)\n  outline:\n    def one\(\):\n    def two\(\):',
            "each file's outline goes under it")
        check(out.count('outline:') == 1, 'a file the task creates gets none')


def test_split_parents():
    print('plan: a split parent is ticked once its subtasks are all done')
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp) / 'plan'
        todo, done = plan.ensure(d / 'TODO.md', d / 'DONE.md')
        Path(todo).write_text('\n'.join([
            '# TODO', '', '### Later', '',
            '- [ ] **P1** the importer (split into P1a, X2)',
            '- [x] **P1a** the header',
            '- [~] **X2** the body BLOCKED: a sample',
            '- [ ] **R1** the parser',
            '- [x] **R1a** a part of it', '']), encoding='utf-8')
        eq(plan.archive(todo, done), 2, 'P1a and R1a archive; P1 waits on X2 (blocked is not done)')
        has(Path(todo).read_text(), r'- \[ \] \*\*P1\*\*', 'P1 is still open')
        plan.unblock('X2', todo=todo)
        plan.tick('X2', todo=todo, done=done, plan_dir=d)
        txt = Path(todo).read_text()
        check('**P1**' not in txt, 'once X2 is ticked, P1 is ticked and archived with it')
        has(txt, r'- \[ \] \*\*R1\*\*', 'R1 says no "(split into …)", so it is left to its own session')


def test_add_bottom():
    print("plan: an agent's follow-up files behind the queued work; a person's goes first")
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp) / 'plan'
        todo, done = plan.ensure(d / 'TODO.md', d / 'DONE.md')
        kw = dict(todo=todo, done=done)
        for t in ('one', 'two'):
            plan.add('D', t, 'bottom', **kw)
        plan.add('D', 'three', 'bottom', **kw)
        eq([l[4:] for l in plan.index(todo) if l.startswith('[ ] ')], ['D1', 'D2', 'D3'],
           'add @ bottom files each behind the last')
        old = os.environ.pop('AGENT_RUNNER', None)
        try:
            os.environ['AGENT_RUNNER'] = '1'
            eq(plan.add_default(), 'normal', "a running agent's follow-up is filed at level normal")
            del os.environ['AGENT_RUNNER']
            eq(plan.add_default(), None, "a person's task has no level, so it goes to the top")
        finally:
            if old is not None:
                os.environ['AGENT_RUNNER'] = old


def test_add_pri():
    print('plan: follow-ups file by level, behind the sections a person queued')
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp) / 'plan'
        d.mkdir()
        todo, done = d / 'TODO.md', d / 'DONE.md'
        todo.write_text('\n'.join(['# TODO', '', '### Next', '', '- [ ] **A1** queued first', '',
                                    '### Phase 2', '', '- [ ] **A2** a person asked for this', '',
                                    '### Stretch', '', '- [ ] **A3** some day', '']), encoding='utf-8')
        kw = dict(todo=todo, done=done)
        plan.add('T', 'a check', pri='low', **kw)
        plan.add('T', 'the usual', pri='normal', **kw)
        plan.add('T', 'the build is red on main', pri='critical', **kw)
        plan.add('T', 'second critical', pri='critical', **kw)
        plan.add('T', 'a rewrite', pri='later', **kw)
        plan.add('T', 'another usual', pri='normal', **kw)
        plan.add('A', 'a person, now', **kw)
        eq(plan.index(todo), ['# TODO', '### Next', '[ ] A4', '[ ] T3', '[ ] T4', '[ ] A1', '### Phase 2', '[ ] A2',
                              '### Follow-ups', '[ ] T2', '[ ] T6', '[ ] T1', '### Stretch', '[ ] A3',
                              '### Parked', '[ ] T5'],
           'critical leads (in order, behind a person\'s newest); normal then low after the person\'s sections; '
           'later at the end')
        text = todo.read_text()
        has(text, r'\*\*T1\*\* \(follow-up, low\) a check', 'the level is tagged on the line')
        has(text, r'### Phase 2\n\n- \[ \] \*\*A2\*\* a person asked for this\n\n### Follow-ups\n\n- \[ \] \*\*T2',
            'the new section keeps the blank lines around it')
        plan.add('T', 'placed by hand', pri='low', where='top', **kw)
        eq(plan.next_task(todo=todo), 'T7', '@ WHERE still overrides the level\'s place')
        eq(plan.similar('(follow-up, normal) the rider leans', todo=todo), [], 'the tag is no word to match on')
        crit = d / 'CRIT.md'
        crit.write_text('\n'.join(['# TODO', '', '### Critical: beside the rest', '', '- [ ] **B1** red', '',
                                    '### Next (in this order)', '', '- [ ] **B2** queued', '']), encoding='utf-8')
        plan.add('T', 'flaky test', pri='critical', todo=crit, done=done)
        eq(plan.index(crit), ['# TODO', '### Critical: beside the rest', '[ ] B1', '[ ] T1',
                              '### Next (in this order)', '[ ] B2'],
           'a plan\'s own Critical section takes critical follow-ups, in order, not the ordered Next')
        try:
            plan.add('T', 'x', pri='urgent', **kw)
            check(False, 'an unknown level is refused')
        except SystemExit as e:
            has(str(e), 'critical | normal | low | later', 'an unknown level is refused, naming the four')


def test_add_subtask():
    print('plan: an agent\'s split of a task stays with it, not behind the follow-ups')
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        git(root, 'init', '-q')
        (root / 'plan').mkdir()
        todo = root / 'plan' / 'TODO.md'
        todo.write_text('\n'.join(['# TODO', '', '### Next', '', '- [ ] **A1** a person asked for this',
                                    '- [ ] **A2** and this', '', '### Follow-ups', '',
                                    '- [ ] **A3** (follow-up, low) a check', '']), encoding='utf-8')
        env = {**os.environ, 'AGENT_RUNNER_REPO': str(root), 'AGENT_RUNNER': '1'}
        for args in (['A1', 'the first part'], ['A1', 'the second part'], ['A3', 'part of the check'],
                     ['A', 'something else'], ['A2', 'urgent part', '--pri', 'critical']):
            eq(run(root, 'plan', 'add', *args, env=env).returncode, 0, f'add {args[0]}')
        eq(plan.index(todo), ['# TODO', '### Next', '[ ] A2a', '[ ] A1', '[ ] A1a', '[ ] A1b', '[ ] A2',
                              '### Follow-ups', '[ ] A4', '[ ] A3', '[ ] A3a'],
           'subtasks follow their family; a plain add is a normal follow-up; --pri still places it')
        text = todo.read_text()
        has(text, r'\*\*A1a\*\* the first part', 'a person\'s task\'s subtask carries no follow-up tag')
        has(text, r'\*\*A3a\*\* \(follow-up, low\) part of the check', 'a follow-up\'s subtask keeps its level')
        r = run(root, 'plan', 'add', 'A1', 'a third part', env=env)
        has(r.stderr, r'A1c never runs beside A1', 'a subtask id comes with a note to use a fresh letter if it could start now')
        has(run(root, 'plan', 'add', 'A', 'unrelated work', env=env).stderr, r'^$', 'a fresh id gets no note')
        eq(run(root, 'plan', 'add', 'A3a', 'measure the cache warmup', env=env).returncode, 0, 'add A3a')
        eq(run(root, 'plan', 'move', 'A3', 'top', env=env).returncode, 0, 'move A3 top')
        eq(plan.index(todo)[:5], ['# TODO', '### Next', '[ ] A3', '[ ] A3a', '[ ] A3a1'],
           "a subtask's subtask files after it, and a moved parent takes its subtasks along")
        for args in (['A', 'big future work', '--pri', 'later'], ['A', 'more future work', '--pri', 'later']):
            run(root, 'plan', 'add', *args, '--force', env=env)
        run(root, 'plan', 'move', 'A6', 'top', env=env)
        for p in ('A6', 'A7'):
            eq(run(root, 'plan', 'add', p, f'split of {p}', '--force', env=env).returncode, 0, f'add {p}')
        ix, text = plan.index(todo), todo.read_text()
        eq(ix[:4], ['# TODO', '### Next', '[ ] A6', '[ ] A6a'], 'a parked parent moved to the top takes its new subtask')
        has(text, r'\*\*A6a\*\* split of A6', 'which is not tagged later, so a run starts it')
        eq(ix[-3:], ['### Parked', '[ ] A7', '[ ] A7a'], 'a parent still parked parks its subtask with it')
        has(text, r'\*\*A7a\*\* \(follow-up, later\)', 'tagged later like its parent')


def test_kinds():
    print('plan: id letters name a kind of work; a repo that names its own refuses others')
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        git(root, 'init', '-q')
        env = {**os.environ, 'AGENT_RUNNER_REPO': str(root)}
        env.pop('AGENT_RUNNER', None)
        r = run(root, 'plan', 'kinds', env=env)
        has(r.stdout, r'B  bug', 'with none set, the defaults are shown')
        has(r.stdout, r'set \[plan\] kinds', 'and how to set them')
        r = run(root, 'plan', 'add', 'Q', 'anything', env=env)
        eq(r.returncode, 0, 'the defaults do not refuse a letter')
        (root / 'runner.toml').write_text('[plan.kinds]\nU = "the UI"\nN = "netplay"\n', encoding='utf-8')
        r = run(root, 'plan', 'add', 'B', 'a bug', env=env)
        eq(r.returncode, 2, 'a letter the repo does not name is refused')
        has(r.stderr, r'U  the UI\n\s*N  netplay', 'and the refusal lists the kinds to pick from')
        r = run(root, 'plan', 'add', 'U', 'the menu', '--pri', 'low', env=env)
        has(r.stdout, r'added U1 \(low\)', 'a named letter is fine, and --pri anywhere in the words is read')
        r = run(root, 'plan', 'add', 'Q1', 'a subtask', env=env)
        has(r.stdout, 'added Q1a', "a task's id is a subtask, whatever the kinds")
        r = run(root, 'plan', 'add', 'Q1a', 'a subtask of a subtask', env=env)
        has(r.stdout, 'added Q1a1', 'an open task id ending in a letter is a subtask too')
        r = run(root, 'plan', 'add', 'Q9z', 'no such task', env=env)
        eq(r.returncode, 2, 'a letter-ending id that is no open task is refused')


def test_need_files():
    print('plan: add writes --files/--after/--test as fields; a line without files: warns, or with need_files is refused')
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        git(root, 'init', '-q')
        (root / 'a.txt').write_text('', encoding='utf-8')
        git(root, 'add', '-A'); git(root, 'commit', '-qm', 'start')
        env = {**os.environ, 'AGENT_RUNNER_REPO': str(root)}
        env.pop('AGENT_RUNNER', None)
        r = run(root, 'plan', 'add', 'S', 'the gates', env=env)
        eq(r.returncode, 0, 'off by default, a bare line is added')
        has(r.stderr, r'warning: the line has no `files:`', 'with a warning')
        r = run(root, 'plan', 'add', 'S', 'the race walk', '--files', 'src/race.rs,src/menu.rs', '--after', 'S1',
                '--test', 'walk', env=env)
        check(r.returncode == 0 and 'warning' not in r.stderr, 'flags name the fields', r.stderr)
        has((root / 'plan' / 'TODO.md').read_text(encoding='utf-8'),
            r'the race walk \| files: src/race\.rs, src/menu\.rs \| after: S1 \| test: walk$', 'in KEYS order')
        (root / 'runner.toml').write_text('[plan]\nneed_files = true\n', encoding='utf-8')
        r = run(root, 'plan', 'add', 'S', 'port the gate walk of race.rs', env=env)
        eq(r.returncode, 2, 'with need_files a line naming no files: and no test: is refused, prose or not')
        r = run(root, 'plan', 'add', 'S', 'prove the finish', '--test', 'finish_width', env=env)
        check(r.returncode == 0, 'a test: is enough', r.stderr)


def test_add_stray_args():
    print('plan: add refuses arguments folded into the text: an unquoted --files dir/* or a second text (B43)')
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        git(root, 'init', '-q')
        git(root, 'commit', '-q', '--allow-empty', '-m', 'start')
        env = {**os.environ, 'AGENT_RUNNER_REPO': str(root)}
        env.pop('AGENT_RUNNER', None)
        eq(run(root, 'plan', 'add', 'R', 'the parser', '--files', 'p.py', env=env).returncode, 0, 'a first add')
        todo = root / 'plan' / 'TODO.md'
        before, head = todo.read_text(encoding='utf-8'), git(root, 'rev-parse', 'HEAD')
        for args, what in ((['x', '--files', 'a', 'b', 'c'], 'an unquoted --files a b c'),
                           (['x', '--files', 'journal/1.md', 'journal/2.md'], 'a shell-expanded journal/*'),
                           (['the whole text', 'more'], 'a second text argument'),
                           (['x', 'journal/1.md', '--files', 'a'], 'a path where text goes on'),
                           (['x', '--files'], 'a flag with no value'),
                           (['x', '--file', 'a'], 'an unknown flag')):
            r = run(root, 'plan', 'add', 'R', *args, env=env)
            eq(r.returncode, 2, f'{what} is refused')
            has(r.stderr, r'quote', f'{what}: the message says to quote')
        eq(todo.read_text(encoding='utf-8'), before, 'TODO.md is unchanged')
        eq(git(root, 'rev-parse', 'HEAD'), head, 'and nothing was committed')
        r = run(root, 'plan', 'add', 'R', 'the lexer', '--files', 'a,b', '--pri', 'low', '@', 'after', 'R1', env=env)
        check(r.returncode == 0, 'a quoted --files a,b still works', r.stderr)
        has(todo.read_text(encoding='utf-8'), r'the lexer \| files: a, b$', 'with its fields')
        r = run(root, 'plan', 'add', 'R', 'tidy', 'the', 'tokens', '--files', 'c', env=env)
        check(r.returncode == 0, 'bare words before any flag still make the text', r.stderr)
        has(todo.read_text(encoding='utf-8'), r'tidy the tokens \| files: c$', 'joined')


def test_hand_edits_commit():
    print('plan: a hand edit in the main checkout commits at once; mid-merge it waits')
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        git(root, 'init', '-q')
        git(root, 'commit', '-q', '--allow-empty', '-m', 'start')
        r = run(root, 'plan', 'add', 'R', 'the parser')
        check(r.returncode == 0, '`run plan add` works', r.stderr)
        has(git(root, 'log', '-1', '--format=%s'), r'^plan: add R the parser', 'the add is its own commit')
        eq(git(root, 'status', '--porcelain', '--', 'plan'), '', 'and nothing in plan/ is left uncommitted')
        (root / '.git/MERGE_HEAD').write_text(git(root, 'rev-parse', 'HEAD') + '\n', encoding='utf-8')
        run(root, 'plan', 'note', 'R1', 'mid-merge')
        has(git(root, 'status', '--porcelain', '--', 'plan'), r'TODO\.md', 'mid-merge the edit stays uncommitted')
        (root / '.git/MERGE_HEAD').unlink()
        run(root, 'plan', 'note', 'R1', 'now')
        eq(git(root, 'status', '--porcelain', '--', 'plan'), '', 'after the merge the next edit commits both')
        run(root, 'plan', 'note', 'R1', 'by a script', env={**os.environ, 'AGENT_RUNNER_NOCOMMIT': '1'})
        has(git(root, 'status', '--porcelain', '--', 'plan'), r'TODO\.md', 'AGENT_RUNNER_NOCOMMIT leaves it for the caller')
        (root / 'runner.toml').write_text('[plan]\nlookup = ["NOTES.md"]\n', encoding='utf-8')
        (root / 'NOTES.md').write_text('# Notes\n\n## When blocked\n\nmove on\n', encoding='utf-8')
        has(run(root, 'plan', 'when blocked').stdout, r'move on', '[plan] lookup adds files that name lookups search')
        (root / 'runner.toml').write_text('[plan]\nlookup = ["NOTES.md", "guide/*.md"]\n', encoding='utf-8')
        (root / 'guide').mkdir()
        (root / 'guide/MAP.md').write_text('# Map\n\n## app-core\n\ncore\n\n## app\n\nthe app\n', encoding='utf-8')
        has(run(root, 'plan', 'app').stdout, r'the app', 'a heading named exactly that wins over one containing it')
        has(run(root, 'plan', 'core').stdout, r'^## app-core', 'a substring still finds a heading, through a glob')
        (root / 'CLAUDE.md').write_text('rules\n@guide/BIG.md\n', encoding='utf-8')
        (root / 'guide/BIG.md').write_text('## Huge\n' + 'x' * 13000 + '\n', encoding='utf-8')
        out = run(root, 'context', check=False)
        has(out.stdout, r'OVER', 'context counts CLAUDE.md and what it @-imports against the budget')
        has(out.stdout, r'12\.7 KB  Huge', 'and names the biggest section')
        eq(run(root, 'context', '--check', check=False).returncode, 1, '--check fails over budget')


def test_hand_edits_push():
    print('plan: a hand edit in the main checkout pushes main (B73)')
    from agent_runner import plat
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        git(tmp, 'init', '-q', '--bare', '-b', 'main', 'origin.git')
        root, other = tmp / 'main', tmp / 'other'
        git(tmp, 'init', '-q', '-b', 'main', 'main')
        git(root, 'commit', '-q', '--allow-empty', '-m', 'start')
        git(root, 'remote', 'add', 'origin', str(tmp / 'origin.git'))
        git(root, 'push', '-q', '-u', 'origin', 'main')
        (root / 'runner.toml').write_text('[run]\ntest = "true"\n', encoding='utf-8')  # a gate: merges push
        origin = lambda: git(tmp / 'origin.git', 'log', '-1', '--format=%s', 'main')  # noqa: E731
        def add(what):
            r = run(root, 'plan', 'add', 'R', what, '--files', 'x.py')
            r.warn = ''.join(ln for ln in r.stderr.splitlines(True) if ln.startswith('!'))
            return r
        r = add('the parser')
        eq(r.warn, '', 'a plan add pushes without a word')
        has(origin(), r'^plan: add R the parser', 'and reaches origin')
        git(tmp, 'clone', '-q', str(tmp / 'origin.git'), 'other')
        (other / 'plan/NOTES.md').write_text('notes\n', encoding='utf-8')
        git(other, 'add', '.')
        git(other, '-c', 'user.name=o', '-c', 'user.email=o@x', 'commit', '-q', '-m', 'plan notes elsewhere')
        git(other, 'push', '-q')
        r = add('the lexer')
        eq(r.warn, '', 'origin ahead: no warning')
        has(origin(), r'^plan: add R the lexer', 'it rebases onto origin and pushes')
        check((root / 'plan/NOTES.md').exists(), 'and the checkout has origin\'s change')
        (root / '.runner').mkdir(exist_ok=True)
        lock = plat.lock(root / '.runner/run.lock')  # a run is up here
        git(other, 'pull', '-q')
        (other / 'plan/NOTES.md').write_text('more notes\n', encoding='utf-8')
        git(other, '-c', 'user.name=o', '-c', 'user.email=o@x', 'commit', '-qam', 'more notes')
        git(other, 'push', '-q')
        head = git(root, 'rev-parse', 'HEAD')
        r = add('the printer')
        has(r.warn, r'^! plan edit committed here but not pushed: .*a run is up here', 'a run up: it warns')
        eq(git(root, 'rev-parse', 'HEAD~1'), head, 'and does not rebase the run\'s checkout')
        lock.close()
        (root / '.git/rebase-merge').mkdir()
        head = git(root, 'rev-parse', 'HEAD')
        r = add('the linker')
        has(r.warn, r'^! plan edit left uncommitted and unpushed: a rebase is in progress', 'a rebase: it warns')
        eq(r.warn.count('\n'), 1, 'in one line')
        eq(git(root, 'rev-parse', 'HEAD'), head, 'and leaves HEAD alone')
        (root / '.git/rebase-merge').rmdir()
        git(root, 'commit', '-qam', 'the linker by hand')
        (root / 'runner.toml').write_text('[git]\npush = false\n', encoding='utf-8')
        before = git(tmp / 'origin.git', 'rev-parse', 'main')
        r = add('the loader')
        eq(r.warn, '', '[git] push = false: no warning')
        eq(git(tmp / 'origin.git', 'rev-parse', 'main'), before, 'and nothing is pushed')
        # B86: with no test gate, a run keeps its untested merges local; a hand edit must not publish them
        (root / 'runner.toml').write_text('', encoding='utf-8')
        r = add('the archiver')
        has(r.warn, r'^! plan edit committed here but not pushed: no test gate .*merges stay local.*'
                    r'git push origin main', 'no gate: it says the merges stay local (B86)')
        check('next merge' not in r.warn, 'and never that a merge publishes main')
        eq(git(tmp / 'origin.git', 'rev-parse', 'main'), before, 'and nothing is pushed')
        (root / 'runner.toml').write_text('[run]\ntest = "true"\n[git]\npush_merge = false\n', encoding='utf-8')
        r = add('the bundler')
        has(r.warn, r'push_merge is off: merges stay local', 'push_merge off: the same')
        eq(git(tmp / 'origin.git', 'rev-parse', 'main'), before, 'and nothing is pushed')
        (root / 'runner.toml').write_text('[git]\npush_merge = true\n', encoding='utf-8')
        r = add('the stripper')
        eq(r.warn, '', 'no gate but push_merge set: pushed without a word')
        has(origin(), r'^plan: add R the stripper', 'and reaches origin')


def test_similar():
    print('plan: add names an open task that looks like the same work, and stays quiet otherwise')
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp) / 'plan'
        todo, done = plan.ensure(d / 'TODO.md', d / 'DONE.md')
        kw = dict(todo=todo, done=done)
        plan.add('V', "the radar's map names go inside the minimap | files: src/hud.rs", **kw)
        plan.add('V', 'world tiles pop in at once; stream them nearest first | files: src/tiles.rs, src/main.rs', **kw)
        plan.add('P', 'the menu sound plays when a slider moves | files: src/menu.rs, src/main.rs', **kw)
        plan.add('P', 'the garage shows each bike in its own colours | files: src/garage.rs, src/main.rs', **kw)
        plan.add('S', 'a done one about the radar and its minimap names | files: src/hud.rs', **kw)
        plan.tick('S1', **kw)
        got = plan.similar("show the map names inside the radar's minimap | files: src/hud.rs", todo=todo)
        eq([g.split(':')[0] for g in got], ['V1'], 'the same work is named, and a done task is not')
        has(got[0], r"^V1: the radar's map names go inside the minimap$", 'as its id and the start of its text')
        eq(plan.similar('the rider leans too far in a berm | files: src/rider.rs', todo=todo), [],
           'unrelated work prints nothing, so an agent pays nothing for it')
        eq([g.split(':')[0] for g in plan.similar('stream tiles nearest first, they pop in | files: src/tiles.rs', todo=todo)],
           ['V2'], 'a shared rare file and some of the words is enough')
        eq(plan.similar('the main menu | files: src/main.rs', todo=todo, skip='P1'), [],
           'a file every task names is not a match by itself')
    # C5: a second _words (plan answer's) shadowed this one, so ids, fields and stop words were matched on
    eq(plan._words('**B12** the radar minimap | files: src/hud.rs, docs/guide.md'), {'radar', 'minimap'},
       'C5: _words drops the id and the files field')
    eq(plan._words('about which those through radar'), {'radar'}, 'C5: _words drops stop words')
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp) / 'plan'
        todo, done = plan.ensure(d / 'TODO.md', d / 'DONE.md')
        kw = dict(todo=todo, done=done)
        plan.add('V', 'the radar shows names | files: src/hud.rs', **kw)
        plan.add('V', 'the garage paints bikes | files: src/garage.rs', **kw)
        plan.add('V', 'stream tiles nearest first | files: src/tiles.rs', **kw)
        eq(plan.similar('about which those through every would | files: src/hud.rs, src/garage.rs, src/tiles.rs',
                        todo=todo), [], 'C5: similar matches no task on stop words, file paths or ids alone')
        eq(plan.similar('V1 V2 V3 should those | files: x.rs', todo=todo), [], 'C5: nor on the ids it names')
    # B42: sweep tasks share a template's wording but cover different pages
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp) / 'plan'
        todo, done = plan.ensure(d / 'TODO.md', d / 'DONE.md')
        kw = dict(todo=todo, done=done)
        sweep = 'sweep the page: replace hardcoded colours with theme tokens and check contrast'
        plan.add('F', f'{sweep} | files: pages/about.html', **kw)
        plan.add('F', 'the garage paints bikes | files: src/garage.rs', **kw)
        plan.add('F', 'stream tiles nearest first | files: src/tiles.rs', **kw)
        eq(plan.similar(f'{sweep} | files: pages/contact.html', todo=todo), [],
           'B42: same words, disjoint files: different work')
        eq([g.split(':')[0] for g in plan.similar(f'{sweep} | files: pages/about.html', todo=todo)], ['F1'],
           'B42: same words, the same file: still a match')
        eq([g.split(':')[0] for g in plan.similar(f'{sweep} | files: pages/**', todo=todo)], ['F1'],
           'B42: a pattern that meets the other\'s file overlaps')
        eq([g.split(':')[0] for g in plan.similar(sweep, todo=todo)], ['F1'],
           'B42: a new task naming no files still matches on words')


def test_add_refuses_a_duplicate():
    print('plan: add refuses what looks like an open task (nothing written); --force adds; drop closes one')
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        git(root, 'init', '-q')
        env = {**os.environ, 'AGENT_RUNNER_REPO': str(root)}
        env.pop('AGENT_RUNNER', None)
        for text in ("the radar's map names go inside the minimap | files: src/hud.rs",
                     'world tiles pop in at once; stream them nearest first | files: src/tiles.rs, src/main.rs',
                     'the menu sound plays when a slider moves | files: src/menu.rs, src/main.rs'):
            eq(run(root, 'plan', 'add', 'V', text, env=env).returncode, 0, 'the first adds')
        before = (root / 'plan' / 'TODO.md').read_text(encoding='utf-8')
        r = run(root, 'plan', 'add', 'B', "show the map names inside the radar's minimap | files: src/hud.rs", env=env)
        eq(r.returncode, 3, 'the same work again is refused')
        has(r.stderr, r'V1: the radar', 'naming the open task')
        has(r.stderr, r'note <ID> TEXT.*--force', 'and what to do instead')
        eq((root / 'plan' / 'TODO.md').read_text(encoding='utf-8'), before, 'with nothing written')
        r = run(root, 'plan', 'add', 'B', "show the map names inside the radar's minimap | files: src/hud.rs", '--force',
                env=env)
        has(r.stdout, r'added B1', '--force adds it')
        r = run(root, 'plan', 'drop', 'B1', 'the same as V1', env=env)
        has(r.stdout, r'dropped B1', 'drop closes it')
        check('**B1**' not in (root / 'plan' / 'TODO.md').read_text(encoding='utf-8'), 'gone from the list')
        has((root / 'plan' / 'DONE.md').read_text(encoding='utf-8'), r'- \[x\] \*\*B1\*\*.* — dropped: the same as V1',
            'and archived saying why, so its id stays used')
        eq(run(root, 'plan', 'newid', 'B', env=env).stdout.strip(), 'B2', 'B1 is not handed out again')
        r = run(root, 'plan', 'add', 'V1', 'the map names part of it', env=env)
        has(r.stdout, 'added V1a', "a split of a task is not refused for looking like it")


def test_carry_notes():
    print('plan: a note added to a task the other side ticked goes onto it in DONE.md')
    base = ['### A', '- [ ] **A1** a — old', '- [ ] **A2** b']
    noted = ['### A', '- [ ] **A1** a — old — a person\'s note', '- [ ] **A2** b — another']
    ticked = ['### A', '- [ ] **A2** b']
    done = ['# DONE', '', '### A', '- [x] **A1** a — old — landed abc', '- [x] **Z1** z']
    eq(plan.carry_notes(done, base, [ticked, noted]),
       ['# DONE', '', '### A', "- [x] **A1** a — old — landed abc — a person's note", '- [x] **Z1** z'],
       'the new note only, not one the base had, nor one on a task still open')
    eq(plan.carry_notes(plan.carry_notes(done, base, [ticked, noted]), base, [ticked, noted]),
       plan.carry_notes(done, base, [ticked, noted]), 'and carried once')


def test_merge3():
    print('plan: a task list merges by section and task, each part against the base')
    m = lambda o, b, t, own=None: plan.merge3(o.split('\n'), b.split('\n'), t.split('\n'), own)
    base = '### Critical\n\n### Next (in order)\n- [ ] **M1** first\n- [ ] **M2** then\n- [ ] **K2** another\n'
    main = '### Critical\n- [ ] **K2** another\n\n### Next (in order)\n- [ ] **M1** first\n- [ ] **M2** then\n'
    branch = '### Critical\n\n### Next (in order)\n- [ ] **M1** first — a note\n- [ ] **M2** then\n- [ ] **K2** another\n'
    eq(m(main, base, branch, 'M1'),
       ['### Critical', '- [ ] **K2** another', '', '### Next (in order)', '- [ ] **M1** first — a note',
        '- [ ] **M2** then', ''],
       'a task main moved and a note beside it on the branch: each heading once, the move and the note both '
       '(the union doubled the heading here, K33)')
    base = '### A\n- [ ] **A1** a\n- [ ] **A2** b\n'
    eq(m('### A\n- [ ] **A1** a — main\'s note\n- [ ] **A2** b\n', base, '### A\n- [ ] **A2** b\n', 'A1'),
       ['### A', '- [ ] **A2** b', ''], 'a task one side ticked (gone to DONE.md) stays gone, though the other noted it')
    eq(m('### A\n- [ ] **A1** a — one\n- [ ] **A2** b\n', base, '### A\n- [ ] **A1** a — two\n- [ ] **A2** b\n'),
       ['### A', '- [ ] **A1** a — one — two', '- [ ] **A2** b', ''], 'two notes on one line: both')
    eq(m('### A\n- [ ] **A1** a — a note\n- [ ] **A2** b\n', base,
         '### A\n- [~] **A1** a BLOCKED: needs X\n- [ ] **A2** b\n', 'A1'),
       ['### A', '- [~] **A1** a — a note BLOCKED: needs X', '- [ ] **A2** b', ''],
       'a block and a note: the block mark, the note, then BLOCKED last')
    eq(m('### A\n- [ ] **A2** b\n- [ ] **A1** a\n', base, '### A\n- [ ] **A1** a\n- [ ] **A2** b\n- [ ] **A3** c\n'),
       ['### A', '- [ ] **A2** b', '- [ ] **A3** c', '- [ ] **A1** a', ''],
       'a re-sort on one side and a task added on the other: both, the new one after the task it followed')
    eq(m('### A\n- [ ] **A1** a\n- [ ] **A2** b\n- [ ] **A4** d\n', base,
         '### A\n- [ ] **A1** a\n- [ ] **A3** c\n- [ ] **A2** b\n'),
       ['### A', '- [ ] **A1** a', '- [ ] **A3** c', '- [ ] **A2** b', '- [ ] **A4** d', ''],
       'tasks added on both sides, each where its side put it')
    eq(m('### A\n- [ ] **A1** a\n- [ ] **A2** b\n- [ ] **A3** mine\n', base,
         '### A\n- [ ] **A1** a\n- [ ] **A2** b\n- [ ] **A3** theirs\n'),
       ['### A', '- [ ] **A1** a', '- [ ] **A2** b', '- [ ] **A3** mine', '- [ ] **A3** theirs', ''],
       'one id both sides handed out: both tasks, for `tick` to refuse rather than one to vanish')
    eq(m('### A (in order)\n- [ ] **A1** a\n- [ ] **A2** b\n', base, '### A\n- [ ] **A1** a\n- [ ] **A2** b\n- [ ] **A3** c\n'),
       ['### A (in order)', '- [ ] **A1** a', '- [ ] **A2** b', '- [ ] **A3** c', ''],
       'a heading one side renamed: the other side\'s new task goes under the new name')
    base = '### A\nsome words\n- [ ] **A1** a\n'
    eq(m('### A\nmain\'s words\n- [ ] **A1** a\n', base, '### A\nthe branch\'s words\n- [ ] **A1** a\n'), None,
       'prose both sides rewrote is not for it to choose: git\'s own merge, which conflicts')


def test_concurrent_add():
    print('plan: two `plan add` at once on an in-repo plan each land, with distinct ids')
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        git(root, 'init', '-q')
        git(root, 'commit', '-q', '--allow-empty', '-m', 'start')
        fails = []
        for i in range(20):
            ps = [subprocess.Popen([sys.executable, str(ROOT / 'run'), 'plan', 'add', 'F',
                                    f'round {i} filer {k} work', '--files', f'src/r{i}k{k}.py', '--force'],
                                   cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                  for k in (0, 1)]
            for p in ps:
                out, err = p.communicate(timeout=120)
                if p.returncode:
                    fails.append(err.strip())
        eq(fails, [], 'every add exits 0')
        ids = [l[4:] for l in plan.index(root / 'plan' / 'TODO.md') if l.startswith('[ ] ')]
        eq(len(ids), 40, 'all 40 tasks are in TODO.md')
        eq(len(set(ids)), 40, 'each with its own id')
        eq(git(root, 'status', '--porcelain', '--', 'plan'), '', 'and every add committed')


def test_concepts():
    print('plan: a concept (K) finishes only with --artifact, its build waits for an OK, approve/revise answer it')
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        git(root, 'init', '-q')
        (root / 'runner.toml').write_text('[plan]\njournal = "journal"\n', encoding='utf-8')
        git(root, 'add', '-A'); git(root, 'commit', '-qm', 'start')
        env = {**os.environ, 'AGENT_RUNNER_REPO': str(root)}
        env.pop('AGENT_RUNNER', None)
        todo, done = root / 'plan' / 'TODO.md', root / 'plan' / 'DONE.md'
        has(run(root, 'plan', 'kinds', env=env).stdout, r'^K  concept', 'K is one of the default kinds')
        r = run(root, 'plan', 'add', 'K', 'settings page layout', '--files', 'src/settings.py', env=env)
        has(r.stdout, 'added K1', 'a concept is filed like any task')

        r = run(root, 'done', 'K1', 'K1: three layouts', '--no-test', env=env)
        eq(r.returncode, 2, 'a K task cannot be done without --artifact')
        has(r.stderr, r'concept task.*\n.*--artifact', 'and the refusal says how to finish it')
        has(todo.read_text(encoding='utf-8'), r'^- \[ \] \*\*K1\*\*', 'nothing ticked')
        eq(run(root, 'done', 'K1', 'K1: x', '--no-test', '--artifact', 'the page', env=env).returncode, 2,
           '--artifact must be a URL')

        url = 'https://claude.ai/code/artifact/aaa'
        r = run(root, 'done', 'K1', 'K1: three layouts', '--no-test', '--artifact', url, env=env)
        check(r.returncode == 0, 'with --artifact it goes through', r.stdout + r.stderr)
        has(r.stdout, r'F1 filed to build it', 'and says which build task it filed')
        has(done.read_text(encoding='utf-8'), r'- \[x\] \*\*K1\*\* .*concept page: ' + re.escape(url),
            'the concept is ticked with its page noted')
        t = todo.read_text(encoding='utf-8')
        has(t, r'^- \[~\] \*\*F1\*\* Build the option a person approves on concept K1\'s page: settings page layout '
               r'\| files: src/settings\.py BLOCKED: waiting for your OK on ' + re.escape(url)
               + r' \(asked \d{4}-\d\d-\d\d \d\d:\d\d\)$',
            'the build task is blocked with the link, on the concept\'s files')
        notes = list((root / 'journal').glob('*-k1-concept/notes.md'))
        check(len(notes) == 1 and url in notes[0].read_text(encoding='utf-8'), 'the link is in the task\'s journal',
              notes)
        eq(git(root, 'status', '--porcelain'), '', 'all of it committed')
        has(run(root, 'plan', 'reopen', env=env).stdout, 'nothing to reopen', 'reopen never frees a build waiting for an OK')
        has(run(root, 'plan', 'waiting', env=env).stdout, r'^CONCEPT  F1  settings page layout  ' + re.escape(url) + r'  \(concept K1\)',
            'plan waiting lists it')

        r = run(root, 'plan', 'revise', 'K1', 'add a dark one', env=env)
        check(r.returncode == 0, 'revise goes through', r.stderr)
        t = todo.read_text(encoding='utf-8')
        has(t, r'^- \[ \] \*\*K1\*\* .*changes asked on ' + re.escape(url) + ': add a dark one', 'revise reopens the concept, noted')
        check('**F1**' not in t, 'and drops the waiting build', t)
        has(done.read_text(encoding='utf-8'), r'- \[x\] \*\*F1\*\* .*dropped: concept K1 sent back', 'archived as dropped')
        check('**K1**' not in done.read_text(encoding='utf-8'), 'the concept left DONE.md')

        url2 = 'https://claude.ai/code/artifact/bbb'
        eq(run(root, 'done', 'K1', 'K1: four layouts', '--no-test', '--artifact', url2, env=env).returncode, 0,
           'the next round finishes the same way')
        r = run(root, 'plan', 'approve', 'K1', 'option B: tabs', env=env)
        has(r.stdout, r'approved: F2 is open', 'approve names the build task it opened')
        has(todo.read_text(encoding='utf-8'),
            r'^- \[ \] \*\*F2\*\* .*\| files: src/settings\.py — approved \(' + re.escape(url2) + r'\): option B: tabs$',
            'approve unblocks the build with the choice noted')
        eq(run(root, 'plan', 'approve', 'K1', env=env).returncode, 1, 'nothing waits any more: refused')
        eq(git(root, 'status', '--porcelain'), '', 'approve and revise commit themselves in the main checkout')

        (root / 'runner.toml').write_text('[plan.kinds]\nF = "feature"\nB = "bug"\n', encoding='utf-8')
        with open(todo, 'a', encoding='utf-8') as f:
            f.write('- [ ] **K9** kitchen sink\n')
        r = run(root, 'done', 'K9', 'K9: sink', '--no-test', env=env)
        check(r.returncode == 0, 'a repo whose kinds lack K has no concepts: K9 is done as any task', r.stderr)


def test_needs_you():
    print('plan: B27 Needs you: plain words for each ask, ages, and replies that name no id')
    eq(plan.plain_ask('CONFIRM', 'check the push reached your phone', 'push notices'),
       'Check the push reached your phone - reply yes/no', 'a check: what to check, reply yes/no')
    eq(plan.plain_ask('CONCEPT', 'pick an option on the page', 'The new menu'),
       'Pick an option for the new menu - reply A/B/C', 'a concept page: pick an option, reply A/B/C')
    eq(plan.plain_ask('DECIDE', 'Postgres or SQLite?', 'db'), 'Postgres or SQLite? - reply with your answer',
       'a decision')
    eq(plan.plain_ask('BLOCKED', 'add the deploy key, see', 'deploy'),
       'Add the deploy key - reply done once it is', 'a block: what to do, reply done; no dangling "see"')
    now = __import__('datetime').datetime(2026, 11, 20, 15, 0)
    eq([plan.age(s, now) for s in ('2026-11-20 15:00', '2026-11-20 14:25', '2026-11-20 13:00', '2026-11-17 15:00',
                                   '')], ['now', '35m', '2h', '3d', ''], 'ages read short')
    for gone in ('reply_kind', 'answered', 'answer', 'SHELVE_REPLY', 'PICK_REPLY', 'DONE_REPLY'):
        check(not hasattr(plan, gone), f'C5: plan.{gone} is gone (sessions map replies to ids)')
    with tempfile.TemporaryDirectory() as tmp:
        todo = Path(tmp) / 'plan' / 'TODO.md'
        plan.ensure(todo)
        for text in ('push notices | files: a.py', 'pick a database | files: b.py', 'deploy key | files: c.py',
                     'menu layout | files: m.py'):
            plan.add('F', text, todo=todo)
        plan.block('F1', 'CONFIRM: check the push reached your phone', todo=todo)
        plan.block('F2', 'DECIDE: Postgres or SQLite for the database?', todo=todo)
        plan.block('F3', 'BLOCKED: add the deploy key on the server', todo=todo)
        check(set(plan.asked_at(todo)) == {'F1', 'F2', 'F3'}, 'each block on a person is stamped', plan.asked_at(todo))
        plan.block('F4', 'needs F1 first', todo=todo)
        check('(asked' not in todo.read_text(encoding='utf-8').split('**F4**')[1].split('\n')[0],
              'a plain block is not stamped')
        eq(sorted(a[1] for a in plan.asks(todo)), ['F1', 'F2', 'F3'], 'the three asks wait under Needs you')
        has(plan.confirm('F2', 'SQLite', todo=todo), 'F2', 'a reply mapped to its id is answered with confirm')
        has(todo.read_text(encoding='utf-8'), r'\*\*F2\*\* .*your answer \(DECIDE Postgres or SQLite for the database\?\)'
            r': SQLite$', 'the decision is unblocked with the answer noted (no stamp in the note)')
        check('plan answer' not in plan.HELP, 'C5: plan help no longer offers plan answer')
        stamps = {'F2': '2026-11-20 14:00', 'F3': '2026-11-20 09:00'}
        a = [('X', 'F2'), ('X', 'F3'), ('X', 'F9')]
        eq([x[1] for x in plan.in_order(a, stamps)], ['F9', 'F3', 'F2'], 'oldest first, unstamped first of all')
        eq([x[1] for x in plan.in_order(a, stamps, 'newest')], ['F2', 'F3', 'F9'], 'newest first')
        eq([x[1] for x in plan.in_order(a, stamps, 'plan')], ['F2', 'F3', 'F9'], 'or the plan\'s order')


def test_needs_own_project():
    print('plan: F33 confirm/change/shelve answer only this project: an id only another project has needs nothing here')
    with tempfile.TemporaryDirectory() as tmp:
        here, other = Path(tmp) / 'iFizBox', Path(tmp) / 'other'
        for r in (here, other):
            r.mkdir()
            git(r, 'init', '-q')
        mine, theirs = here / 'plan' / 'TODO.md', other / 'plan' / 'TODO.md'
        for todo in (mine, theirs):
            plan.ensure(todo)
            plan.add('F', 'push notices | files: a.py', todo=todo)
        plan.add('F', 'pick a database | files: b.py', todo=theirs)
        plan.block('F2', 'DECIDE: Postgres or SQLite?', todo=theirs)
        before = theirs.read_text(encoding='utf-8')
        old = os.environ.get('AGENT_RUNNER_REPO')
        os.environ['AGENT_RUNNER_REPO'] = str(here)
        try:
            for name, call in (('confirm', lambda: plan.confirm('F2', 'SQLite', todo=mine)),
                               ('change', lambda: plan.change('F2', 'use SQLite', todo=mine)),
                               ('shelve', lambda: plan.shelve('F2', todo=mine))):
                try:
                    call()
                    check(False, f'{name} F2 here answers nothing')
                except SystemExit as e:
                    has(str(e), r"nothing needs you here about 'F2' in iFizBox", f'{name}: nothing needs you here')
        finally:
            if old is None:
                os.environ.pop('AGENT_RUNNER_REPO', None)
            else:
                os.environ['AGENT_RUNNER_REPO'] = old
        eq(theirs.read_text(encoding='utf-8'), before, 'the other project\'s plan is left as it was')
        eq([a[1] for a in plan.asks(theirs)], ['F2'], 'and its F2 still waits there')


def test_needs_config():
    print('config: C14 Needs you\'s order is [run] needs_order; [needs] heading/ages are gone (C5: map_replies too)')
    from agent_runner.config import Config
    with tempfile.TemporaryDirectory() as tmp:
        r = Path(tmp)
        git(r, 'init', '-q')
        eq(Config(r).run['needs_order'], 'oldest', 'the default')
        check('needs' not in Config(r).raw, 'no [needs] table')
        (r / 'runner.toml').write_text('[needs]\nheading = "For you"\nages = false\norder = "plan"\n', encoding='utf-8')
        c = Config(r)
        eq(c.run['needs_order'], 'plan', 'an old [needs] order still maps to [run] needs_order')
        eq(len(c.warnings), 3, f'each old key warns: {c.warnings}')
        check(any('[needs] order is gone, folded into [run] needs_order' in w for w in c.warnings), 'order: where', c.warnings)
        check(any('[needs] heading is ignored' in w for w in c.warnings), 'heading: ignored, said why', c.warnings)
        (r / 'runner.toml').write_text('[needs]\nmap_replies = true\n', encoding='utf-8')
        c = Config(r)
        check(any('map_replies is ignored' in w for w in c.warnings), 'C5: an old map_replies is ignored, said why',
              c.warnings)


def test_merge_driver():
    print('plan: git merges the task list through merge3 once install_driver ran')
    with tempfile.TemporaryDirectory() as tmp:
        r = Path(tmp)
        git(r, 'init', '-q', '-b', 'main')
        (r / 'plan').mkdir()
        todo = r / 'plan' / 'TODO.md'
        todo.write_text('### Critical\n\n### Next\n- [ ] **M1** first\n- [ ] **K2** another\n', encoding='utf-8')
        git(r, 'add', '-A'); git(r, 'commit', '-qm', 'base')
        git(r, 'checkout', '-qb', 'task/M1')
        todo.write_text('### Critical\n\n### Next\n- [ ] **M1** first — a note\n- [ ] **K2** another\n', encoding='utf-8')
        git(r, 'commit', '-qam', 'note')
        git(r, 'checkout', '-q', 'main')
        todo.write_text('### Critical\n- [ ] **K2** another\n\n### Next\n- [ ] **M1** first\n', encoding='utf-8')
        git(r, 'commit', '-qam', 'move')
        plan.install_driver(r, ['plan/TODO.md'])
        plan.install_driver(r, ['plan/TODO.md'])
        att = (r / '.git' / 'info' / 'attributes').read_text(encoding='utf-8')
        eq(att.count('merge=agent-runner-plan'), 1, 'installed twice, listed once')
        p = subprocess.run(['git', 'merge', '-q', '--no-edit', 'task/M1'], cwd=r, capture_output=True, text=True,
                           env={**os.environ, 'AGENT_RUNNER_TASK': 'M1'})
        eq(p.returncode, 0, 'the edits beside each other merge without a conflict: ' + p.stdout + p.stderr)
        eq(todo.read_text(encoding='utf-8'),
           '### Critical\n- [ ] **K2** another\n\n### Next\n- [ ] **M1** first — a note\n', 'by task')


def test_goal():
    print('plan goal: prints and replaces only the Goal: paragraph; title, fields line, headings, tasks untouched')
    head = '# TODO: open tasks, in order\n\n'
    old = 'Goal: the old aim,\nover two lines.\nRules: `AGENTS.md`.\n'
    fmt = '\nTask lines end in keyed fields: `| files: a, dir/** | after: ID` (only the fields are parsed).\n'
    body = ('\n### Next\n\n- [ ] **F1** first | files: a.py\n  - sub-item\n- [~] **B2** second — BLOCKED: why\n'
            '\n## Later\n\nGoal: not this one, it is below a heading\n- [ ] **D3** third\n')
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        todo = root / 'TODO.md'
        todo.write_text(head + old + fmt + body, encoding='utf-8')
        eq(plan.goal(todo=todo), old.rstrip('\n'), 'goal() reads the paragraph above the first heading')
        plan.goal('A new aim: ship it.', todo=todo)
        eq(todo.read_text(encoding='utf-8'), head + 'Goal: A new aim: ship it.\n' + fmt + body,
           'only the paragraph changes (prefixed Goal:), every other byte stays')
        plan.goal('Goal: two\nlines', todo=todo)
        eq(todo.read_text(encoding='utf-8'), head + 'Goal: two\nlines\n' + fmt + body, 'a multi-line goal')
        eq(plan.goal(todo=todo), 'Goal: two\nlines', 'and reads back')

        todo.write_text(head + fmt.lstrip('\n') + body, encoding='utf-8')
        eq(plan.goal(todo=todo), '', 'no Goal: paragraph: empty, the fields line is not a goal')
        plan.goal('first aim', todo=todo)
        eq(todo.read_text(encoding='utf-8'), head + 'Goal: first aim\n\n' + fmt.lstrip('\n') + body,
           'a new goal goes after the title, before the fields line')
        todo.write_text('# TODO\n### Next\n- [ ] **F1** x\n', encoding='utf-8')
        plan.goal('aim', todo=todo)
        eq(todo.read_text(encoding='utf-8'), '# TODO\n\nGoal: aim\n\n### Next\n- [ ] **F1** x\n',
           'blank lines around a goal added to a tight file')

        git(root, 'init', '-q')
        git(root, 'commit', '-q', '--allow-empty', '-m', 'start')
        run(root, 'plan', 'add', 'R', 'the parser')
        r = run(root, 'plan', 'goal', check=False)
        eq(r.returncode, 1, '`plan goal` with no goal fails, and says how to set one')
        has(r.stderr, r'plan goal "TEXT"', 'the hint')
        r = run(root, 'plan', 'goal', 'parse', 'everything')
        has(git(root, 'log', '-1', '--format=%s'), r'^plan: goal parse everything', 'plan goal TEXT commits like other edits')
        eq(git(root, 'status', '--porcelain', '--', 'plan'), '', 'nothing left uncommitted')
        eq(run(root, 'plan', 'goal').stdout.strip(), 'Goal: parse everything', '`plan goal` prints it')
        has(run(root, 'plan', 'R1').stdout, r'the parser', 'the task is still there')
    from agent_runner import guide
    has(guide.CONTROL_TOPICS['queue'], r'plan goal "TEXT"',  # B98: in `guide queue`, which the brief names
        'the control brief says to reword a stale goal with plan goal')


def test_plan_last():
    print('plan: add --last files at the end of Next with `after: all above`, resolved to what is above it now')
    t, where, keyed, _, _ = plan.add_args(['the release', '--files', 'CHANGELOG.md', '--last'])
    eq((t, where, keyed), ('the release', 'bottom', ' | files: CHANGELOG.md | after: all above'),
       '--last: the bottom of the leading section, `after: all above`')
    eq(plan.add_args(['r', '--after', 'X1,Y2', '--last'])[2], ' | after: X1, Y2, all above',
       'beside --after ids, the marker comes last')
    eq(plan.add_args(['r', '--last', '@', 'top'])[1], 'top', '@ WHERE still overrides the place')
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp) / 'plan'
        todo, done = plan.ensure(d / 'TODO.md', d / 'DONE.md')
        kw = dict(todo=todo, done=done)
        plan.add('F', 'one | files: a.py', 'bottom', **kw)
        plan.add('F', 'two | files: b.py', 'bottom', **kw)
        rel = plan.add('T', 'release' + keyed, where, **kw)
        plan.add('B', 'a follow-up | files: c.py', pri='normal', **kw)
        plan.add('C', 'a person asks | files: d.py', 'before', rel, **kw)
        plan.block('C1', 'DECIDE: which one?', todo=todo)
        eq([l[4:] for l in plan.index(todo) if l[:4] in ('[ ] ', '[~] ')], ['F1', 'F2', 'C1', 'T1', 'B1'],
           'the last task sits at the end of Next, the follow-up in its own section below')
        eq(plan.last_waits(todo), [('T1', ['F1', 'F2'])],
           'it waits on every task above it in Next, not on one blocked on a person, nor on Follow-ups')
        plan.add('F', 'three | files: e.py', **kw)  # a person's task: the top of Next
        eq(plan.last_waits(todo), [('T1', ['F3', 'F1', 'F2'])], 'a task added above it later holds it too')
        has('\n'.join(plan.last_lines(todo)), r'T1 waits on all above: F3, F1, F2 \(3 open\)', 'last_lines says so')
        for tid in ('F1', 'F2', 'F3'):
            plan.tick(tid, **kw)
        eq(plan.last_waits(todo), [('T1', [])], 'once they are done it waits on nothing')
        plan.unblock('C1', 'answered: the first', todo=todo)
        eq(plan.last_waits(todo), [('T1', ['C1'])], 'a person-blocked task reopened holds it again')
        plan.block('C1', 'needs F9 first', todo=todo, after=[])
        eq(plan.last_waits(todo), [('T1', ['C1'])], 'a task blocked on something other than a person still holds it')


def test_after_all():
    print('plan: --after all waits for every open task before it in TODO.md, worked out live (F35)')
    eq(plan.add_args(['the release', '--files', 'CHANGELOG.md', '--after', 'all'])[2],
       ' | files: CHANGELOG.md | after: all', '--after all writes `after: all`')
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp) / 'plan'
        todo, done = plan.ensure(d / 'TODO.md', d / 'DONE.md')
        kw = dict(todo=todo, done=done)
        plan.add('F', 'one | files: a.py', 'bottom', **kw)
        plan.add('C', 'asks a person | files: d.py', 'bottom', **kw)
        plan.block('C1', 'DECIDE: which one?', todo=todo)
        plan.add('B', 'shelved one | files: e.py', 'bottom', **kw)
        plan.block('B1', 'DECIDE: maybe later?', todo=todo)
        plan.shelve('B1', todo=todo)
        plan.add('B', 'a follow-up | files: c.py', pri='normal', **kw)
        rel = plan.add('R', 'release | files: CHANGELOG.md | after: all', pri='normal', **kw)
        plan.add('F', 'big future | files: z.py', pri='later', **kw)
        eq(plan.last_waits(todo), [(rel, ['F1', 'B2'])],
           'every open or blocked task above it, any section; not blocked for the person (B101), shelved, Parked')
        eq(plan.last_lines(todo), [f'{rel} waits for everything before it (2 open); not waiting on: C1 (needs you)'],
           'said as a count, then the tasks blocked for the person it skips (B101), not the shelved')
        from agent_runner import status as S
        has(S.release_line(list(plan.lines(todo))), rf'waits for everything before it \(2 open\); not waiting on: '
            rf'C1 \(needs you\)', "status's release line names them as not waited on (B101)")
        plan.add('F', 'queued later | files: q.py', **kw)  # the top of Next
        eq(plan.last_waits(todo), [(rel, ['F3', 'F1', 'B2'])], 'a task queued above it later holds it too')
        for tid in ('F1', 'F3', 'B2'):
            plan.tick(tid, **kw)
        eq(plan.last_lines(todo), [f'{rel} waits for everything before it: nothing left; not waiting on: C1 '
                                   '(needs you)'], 'nothing an agent can do is left: it is free to run')
        plan.unblock('C1', 'chose the first', todo=todo)
        eq(plan.last_waits(todo), [(rel, ['C1'])], 'once the person answers and it reopens, it holds it again')
        plan.block('C1', 'needs a tool first', todo=todo, after=[])
        eq(plan.last_waits(todo), [(rel, ['C1'])], 'a task blocked on something other than a person still holds it')
        plan.drop('C1', 'not wanted', **kw)
        plan.drop('B1', 'not wanted', **kw)
        eq(plan.last_lines(todo), [f'{rel} waits for everything before it: nothing left'], 'and then nothing')
        # on a block: `(after all)`, freed by reopen only once nothing is left before it
        plan.add('F', 'another | files: a.py', **kw)
        plan.add('T', 'last of all | files: t.py', 'bottom', **kw)
        plan.block('T1', 'cut once the rest lands', todo=todo, after=['all'])
        has('\n'.join(plan.section(todo, 'T1')), r'BLOCKED: \(after all\) cut once', 'block writes (after all)')
        eq(plan.reopen(todo), [], 'held while a task before it is open')
        eq(dict(plan.last_waits(todo))['T1'], ['F4'], 'a blocked (after all) task lists too, not what is below it')
        plan.tick('F4', **kw)
        eq(plan.reopen(todo), [('T1', ['everything before it'])], 'reopened once nothing is before it')
        has(plan.section(todo, 'T1')[0], r'^- \[ \] ', 'open again')


def test_release_kind():
    print('plan: add V files a release: `after: all` at the end of Next, the default brief, no duplicate refusal (F38)')
    eq(plan.kinds()[0].get(plan.RELEASE, '')[:8], 'release:', 'V is a kind of task, the release')
    check(plan.release('V3') and plan.release('V3a') and not plan.release('F3') and not plan.release(''),
          'release() reads the id letter')
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        git(root, 'init', '-q')
        (root / 'plan').mkdir()
        todo = root / 'plan' / 'TODO.md'
        todo.write_text('\n'.join(['# TODO', '', '### Next', '', '- [ ] **F1** a feature | files: a.py',
                                    '- [ ] **F2** another | files: b.py', '', '### Follow-ups', '',
                                    '- [ ] **B1** (follow-up, normal) a follow-up | files: c.py', '']), encoding='utf-8')
        env = {**os.environ, 'AGENT_RUNNER_REPO': str(root), 'AGENT_RUNNER': '1'}
        r = run(root, 'plan', 'add', 'V', env=env)
        eq((r.returncode, r.stderr), (0, ''), 'plan add V needs no text, no --after and no --files')
        line = plan.section(todo, 'V1')[0]
        has(line, r'\*\*V1\*\* Release: bump the version .* \| after: all$', 'the default brief, `after: all`')
        has(line, r'docs/SETUP\.md#versions.*CHANGELOG.*gh release view', 'the brief says what a release does')
        eq(plan.index(todo)[2:5], ['[ ] F1', '[ ] F2', '[ ] V1'], 'at the end of Next, not a follow-up, even from an agent')
        eq(plan.last_waits(todo), [('V1', ['F1', 'F2'])], 'it waits on the earlier open tasks')
        r = run(root, 'plan', 'add', 'V', 'Release: cut the next version | files: CHANGELOG.md', env=env)
        eq(r.returncode, 0, 'a second release is not refused as a duplicate of the first: ' + r.stderr)
        r = run(root, 'plan', 'add', 'V', '--now', env=env)
        eq(r.returncode, 0, 'add V --now: ' + r.stderr)
        line = plan.section(todo, 'V3')[0]
        check('after:' not in line and '(follow-up, critical)' in line, '--now: critical, no `after: all`', line)
        eq(plan.index(todo)[2], '[ ] V3', 'and at the top: an interim release')
        run(root, 'plan', 'add', 'V', '--pri', 'critical', '--force', env=env)
        check('after:' not in plan.section(todo, 'V4')[0], '--pri critical: no `after: all` either')
        run(root, 'plan', 'add', 'V', '--after', 'F1', '--force', env=env)
        has(plan.section(todo, 'V5')[0], r'\| after: F1$', 'an --after of its own replaces `all`')
        eq(run(root, 'plan', 'add', 'V', '--now', '--pri', 'low', env=env).returncode, 2, '--now with another level is refused')
        eq(run(root, 'plan', 'add', 'F', 'the minimap radar', '--files', 'm.py', env=env).returncode, 0, 'a build, F3')
        r = run(root, 'plan', 'add', 'V', 'a release after the minimap radar', '--after', 'F3', env=env)
        eq((r.returncode, r.stderr), (0, ''), 'a release naming the work it waits for is not its duplicate (B99)')
        eq(run(root, 'plan', 'add', 'F', 'x', '--now', '--force', env=env).returncode, 2, '--now is for a release only')


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


def test_unlabelled_block():
    print('plan: B35 a block with no caps label and no task to wait on lists under Needs you, and the watch says so')
    from agent_runner import runner as R
    with tempfile.TemporaryDirectory() as tmp:
        todo, done = plan.ensure(Path(tmp) / 'plan' / 'TODO.md', Path(tmp) / 'plan' / 'DONE.md')
        for text in ('flaky tests | files: a.py', 'waits on F1 | files: b.py', 'stale wait | files: c.py'):
            plan.add('F', text, todo=todo)
        plan.block('F1', 'tests flake, unclear why — see https://x.invalid/log', todo=todo)
        plan.block('F2', 'needs F1 first', todo=todo)
        plan.block('F3', 'waits on Z9', todo=todo)  # names no open task: nothing would ever free it
        eq(plan.reopen(todo=todo), [], 'reopen frees none of them')
        a = {x[1]: x for x in plan.asks(todo)}
        eq(sorted(a), ['F1', 'F3'], 'the two blocks waiting on no task are asks; F2 waits on F1, which is listed')
        eq((a['F1'][0], a['F1'][3]), (plan.STUCK, 'tests flake, unclear why (holds F2 too)'),
           'label STUCK, what it says, and the task waiting on it')
        eq(a['F3'][3], 'waits on Z9', 'one nothing waits on says only what it says')
        check(set(plan.asked_at(todo)) >= {'F1', 'F3'}, 'and stamped, so Needs you shows its age', plan.asked_at(todo))
        eq(plan.plain_ask(*[a['F1'][i] for i in (0, 3, 5)]),
           'Stuck: tests flake, unclear why (holds F2 too) - reply with what to do', 'in plain words, no caps label')
        now = __import__('datetime').datetime(2026, 11, 20, 15, 0)
        line = '=== 2026-11-20T14:35:00 F1: merged, blocked'
        nl = R.needs_you_line(line, {}, now, [(*x, '') for x in plan.asks(todo, all=True)])
        eq(nl, '14:35  needs you: Stuck: tests flake, unclear why (holds F2 too) - reply with what to do [F1]',
           'since --follow --needs-you prints a line for the unlabelled block')
        plan.shelve('F3', todo=todo)
        eq([x[1] for x in plan.asks(todo)], ['F1'], 'shelve takes it off')
        eq([x[1] for x in plan.asks(todo, all=True) if x[6]], ['F3'], 'and waiting --all still has it')
        has(plan.change('F1', 'mark the flaky test skip', todo=todo, done=done), 'F1 is open again',
            'change reopens it')
        has(Path(todo).read_text(encoding='utf-8'), r'- \[ \] \*\*F1\*\* .*do this instead: mark the flaky test skip$',
            'with the person\'s words noted')


def test_edit():
    print('plan: F45 edit rewrites a task\'s description in place, keeping id, status and fields')
    with tempfile.TemporaryDirectory() as tmp:
        todo, done = plan.ensure(Path(tmp) / 'plan' / 'TODO.md', Path(tmp) / 'plan' / 'DONE.md')
        kw = dict(todo=todo)
        plan.add('A', 'a person first', todo=todo)
        plan.add('F', 'build ifizbox on arm | files: box.py, b/** | after: A1 | test: test_box', pri='normal', todo=todo)
        plan.note('F1', 'use the cache', **kw)
        plan.block('F1', 'DECIDE: which board?', after=[], **kw)
        before = Path(todo).read_text(encoding='utf-8')
        line = plan.edit('F1', 'build ifizbox, not on arm', **kw)
        eq(line.split(' BLOCKED: ')[0],
           '- [~] **F1** (follow-up, normal) build ifizbox, not on arm | files: box.py, b/** | after: A1 | test: test_box',
           'the description and its notes are replaced; checkbox, tag and fields kept')
        has(line, r' BLOCKED: DECIDE: which board\? \(asked \d{4}-\d\d-\d\d \d\d:\d\d\)$', 'and the BLOCKED text')
        check('use the cache' not in Path(todo).read_text(encoding='utf-8'), 'the stale note is gone')
        eq([x for x in plan.index(todo) if 'F1' in x], ['[~] F1'], 'same id, still blocked')
        eq(len(Path(todo).read_text(encoding='utf-8').splitlines()), len(before.splitlines()), 'no line added or lost')
        line = plan.edit('F1', 'build it | test: test_board', ' | files: c.py | after: A1, F9', **kw)
        has(line, r'build it \| files: c\.py \| after: A1, F9 \| test: test_board BLOCKED: DECIDE',
            'fields in the text or flags replace those keys, in the usual order')
        line = plan.edit('F1', '', ' | journal: j', **kw)
        has(line, r'\*\* \(follow-up, normal\) build it \| files: c\.py .* \| journal: j BLOCKED',
            'no text: the description stays, only the field changes')
        plan.edit('F1', 'park it', pri='later', **kw)
        eq(plan.index(todo)[-2:], ['### Parked', '[~] F1'], '--pri moves it where add files that level')
        has(Path(todo).read_text(encoding='utf-8'), r'\*\*F1\*\* \(follow-up, later\) park it \|', 'and retags it')
        for bad in ('Z9', 'F'):
            try:
                plan.edit(bad, 'x', **kw)
                check(False, f'edit of unknown id {bad} errors')
            except SystemExit as e:
                has(str(e), 'no task', f'edit of unknown id {bad} errors')
        try:
            plan.edit('A1', 'x', pri='urgent', **kw)
            check(False, 'an unknown level is refused')
        except SystemExit as e:
            has(str(e), 'critical \\| normal', 'an unknown level is refused')
        t, _, keyed, pri, _ = plan.add_args(['new words', '--files', 'x.py,y/**', '--pri', 'low'])
        plan.edit('A1', t, keyed, pri, **kw)
        has(Path(todo).read_text(encoding='utf-8'), r'- \[ \] \*\*A1\*\* \(follow-up, low\) new words \| files: x\.py, y/\*\*',
            'the CLI flags parse as add\'s do')
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        git(root, 'init', '-q')
        git(root, 'commit', '-q', '--allow-empty', '-m', 'start')
        run(root, 'plan', 'add', 'R', 'the parser on arm', '--files', 'p.py')
        r = run(root, 'plan', 'edit', 'R1', 'the parser, not on arm', '--after', 'R0')
        check(r.returncode == 0, '`run plan edit` works', r.stderr)
        has(git(root, 'log', '-1', '--format=%s'), r'^plan: edit R1 ', 'and commits as plan: edit ID')
        has((root / 'plan/TODO.md').read_text(encoding='utf-8'),
            r'- \[ \] \*\*R1\*\* the parser, not on arm \| files: p\.py \| after: R0\n', 'the line, rewritten')
        r = run(root, 'plan', 'edit', 'R9', 'x', check=False)
        check(r.returncode != 0 and 'no task' in r.stderr, 'an unknown id errors on the command line', r.stderr)
        r = run(root, 'plan', 'edit', 'R1', 'x', '@', 'top', check=False)
        eq(r.returncode, 2, 'edit refuses a place (move does that)')
        told, cwd, real = [], os.getcwd(), plan.tell
        plan.tell = lambda c, tid, text, how='tell', wait=None: (told.append((tid, text, how)), (True, 'told s1'))[1]
        try:
            os.chdir(root)
            eq(plan.main(['edit', 'R1', '--test', 'test_p']), 0, 'a field-only edit')
        finally:
            os.chdir(cwd)
            plan.tell = real
        eq(told, [('R1', 'it now reads: the parser, not on arm | files: p.py | after: R0 | test: test_p', 'change')],
           'a slot running it is told the line as it now reads ("Your task changed: …"), fields included')
    with tempfile.TemporaryDirectory() as tmp:
        todo = Path(tmp) / 'TODO.md'
        todo.write_text('\n'.join(['# TODO', '', '### Next', '',
                                   '- [ ] **M1** old words | files: m.py',
                                   '  more old words — a stale note',
                                   '- [ ] **M2** keeps its sub-item',
                                   '  - [ ] **M2a** the sub-item — its note',
                                   '- [~] **M3** blocked | files: q.py',
                                   '  continued BLOCKED: DECIDE: which? (asked 2026-11-20 10:00)', '']), encoding='utf-8')
        plan.edit('M1', 'new words', todo=todo)
        plan.edit('M2', 'new two', todo=todo)
        plan.edit('M3', 'new three', todo=todo)
        eq(Path(todo).read_text(encoding='utf-8').splitlines()[4:],
           ['- [ ] **M1** new words | files: m.py', '- [ ] **M2** new two', '  - [ ] **M2a** the sub-item — its note',
            '- [~] **M3** new three | files: q.py BLOCKED: DECIDE: which? (asked 2026-11-20 10:00)'],
           'a multi-line task loses its old continuation lines and the note on them; sub-items and BLOCKED stay')


def test_iter_tasks_and_titles():
    print('plan: iter_tasks reads top-level task lines with their section; titles maps ids to short titles')
    ls = ['# TODO', '- [ ] **A1** before any section', '### Next (in this order)  ', '',
          '- [ ] **A2** Fix the menu flicker | files: a.py', '  - [ ] **A2a** a sub-item is not top-level',
          '- [~] **A3** blocked one BLOCKED: x', '### Parked', '- [x] **A4.** done, with a dot', 'prose - [ ] **A5** no']
    eq(list(plan.iter_tasks(ls)),
       [('', ' ', 'A1', ' before any section', 1),
        ('Next (in this order)', ' ', 'A2', ' Fix the menu flicker | files: a.py', 4),
        ('Next (in this order)', '~', 'A3', ' blocked one BLOCKED: x', 6),
        ('Parked', 'x', 'A4.', ' done, with a dot', 8)],
       '(section, box, id, rest, index) for each top-level task; sub-items and prose skipped, the heading stripped')
    eq(list(plan.iter_tasks([])), [], 'no lines, no tasks')
    with tempfile.TemporaryDirectory() as tmp:
        todo, done = Path(tmp) / 'TODO.md', Path(tmp) / 'DONE.md'
        todo.write_text('### Next\n- [ ] **B1** (follow-up, normal) Fix the menu flicker | files: a.py\n'
                        '- [ ] **B2** Keep the cache warm. Then more words\n', encoding='utf-8')
        done.write_text('- [x] **B1** an older wording\n- [x] **B0** Landed long ago — note\n', encoding='utf-8')
        eq(plan.titles(done, todo), {'B1': 'Fix the menu flicker', 'B0': 'Landed long ago', 'B2': 'Keep the cache warm'},
           'DONE.md then TODO.md: the later file wins; short titles drop tags, fields, notes and later sentences')
        eq(plan.titles(todo, width=12)['B2'], 'Keep the…', 'width cuts at a word')
        eq(plan.titles(Path(tmp) / 'missing.md'), {}, 'a missing file adds nothing')


def test_hook():
    print('state.hook: runs a project command with [run] command_timeout, logs one that runs past')
    import types
    from agent_runner import state
    saved = state.C
    with tempfile.TemporaryDirectory() as tmp:
        state.C = types.SimpleNamespace(run={'command_timeout': 5}, notes=lambda name: Path(tmp) / name)
        try:
            rc, out = state.hook('t', f'"{sys.executable}" -c "import sys; print(1); sys.exit(3)"', tmp)
            eq((rc, out.strip()), (3, '1'), 'its exit code and output')
            rc, out = state.hook('t', f'"{sys.executable}" -c "import os; print(os.environ[\'HOOK_X\'])"', tmp,
                                 {**os.environ, 'HOOK_X': 'yes'})
            eq((rc, out.strip()), (0, 'yes'), 'the env it is given')
            state.C.run['command_timeout'] = 0.5
            rc, out = state.hook('T9: the retest', f'"{sys.executable}" -c "import time; time.sleep(5)"', tmp)
            eq((rc, out), (None, ''), 'one that runs past [run] command_timeout reads as (None, "")')
            has((Path(tmp) / 'run.log').read_text(encoding='utf-8'), 'T9: the retest: `', 'and is logged under its name')
            has((Path(tmp) / 'run.log').read_text(encoding='utf-8'), re.escape('ran past [run] command_timeout (0.5s)'), 'with the limit')
        finally:
            state.C = saved


def test_refusals():
    print('plan: every refusal and usage line, and its exit code, word for word as before argparse (C12)')
    nothing = lambda w: (1, f"./run plan: nothing named '{w}' — run `./run plan` for the index\n")
    quote = ('quote the text and each flag value: ./run plan add KIND "the text" --files \'a,dir/**\' '
             '(a bare dir/* is expanded by the shell)\n')
    cases = [  # taken from the hand-rolled parser's output before C12
        (['add', 'R'], nothing('add')), (['drop', 'R1'], nothing('drop')), (['block', 'R1'], nothing('block')),
        (['reopen', 'x'], nothing('reopen')), (['unblock'], nothing('unblock')), (['move', 'R1'], nothing('move')),
        (['approve'], nothing('approve')), (['revise', 'R1'], nothing('revise')),
        (['waiting', '--x'], nothing('waiting')), (['waiting', '--al'], nothing('waiting')),
        (['confirm'], nothing('confirm')), (['change', 'R1'], nothing('change')),
        (['shelve', 'a', 'b'], nothing('shelve')), (['unshelve'], nothing('unshelve')), (['kinds', 'x'], nothing('kinds')),
        (['note', 'R1'], nothing('note')), (['edit', 'R1'], nothing('edit')), (['newid', 'R', 'x'], nothing('newid')),
        (['brief'], nothing('brief')), (['claims', 'x'], nothing('claims')), (['unclaim'], nothing('unclaim')),
        (['nosuch'], nothing('nosuch')), (['--all'], nothing('--all')),
        (['add', 'R', 'x', '--file', 'a'], (2, './run plan: not added: unknown flag --file\n' + quote)),
        (['add', 'R', 'x', '--files'], (2, './run plan: not added: --files needs a value\n' + quote)),
        (['edit', 'R1', '--force'], (2, './run plan: edit takes no --force (`./run plan move ID WHERE` moves a task)\n')),
        (['edit', 'R1', '@'], (2, './run plan: edit takes no @ (`./run plan move ID WHERE` moves a task)\n')),
        (['edit', 'R1', '--files'], (2, './run plan: not edited: --files needs a value\n' + quote)),
        (['edit', 'R1', ''], (2, './run plan edit <ID> "new text" [--files A,B] [--after X,Y] [--test T] [--journal D] '
                                 '[--pri LEVEL]\n')),
        (['goal'], (1, './run plan: no `Goal:` paragraph above the first heading in TODO.md; '
                       '`./run plan goal "TEXT"` writes one\n')),
        (['unclaim', 'Z9'], (1, './run plan: no claim on Z9\n')),
        (['-f'], (2, './run plan -f FILE <name>\n')), (['-f', 'x'], (2, './run plan -f FILE <name>\n')),
        (['tell'], (2, './run plan tell <ID> TEXT\n')), (['tell', 'X'], (2, './run plan tell <ID> TEXT\n')),
        (['tell', 'Z9', 'hi'], (1, './run plan: Z9 is not running: no slot of a run here is on it '
                                   '(`./run plan note Z9 TEXT` notes it for the next attempt)\n')),
        (['tick', 'Z99'], (1, "./run plan: no task 'Z99' (./run plan for the index)\n")),
        (['drop', 'Z99', 'x'], (1, "./run plan: no task 'Z99' (./run plan for the index)\n")),
        (['approve', 'R1'], (1, "./run plan: nothing waits for an OK on 'R1': `./run plan waiting` lists what does\n")),
        (['add', 'R', 'the parser', '--files', 'p.py'],
         (3, './run plan: not added: already open, and may be the same work:\n  R1: the parser\n'
             '`./run plan note <ID> TEXT` it there; if it is different work, add it again with --force\n')),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        git(root, 'init', '-q')
        git(root, 'commit', '-q', '--allow-empty', '-m', 'start')
        env = {**os.environ, 'AGENT_RUNNER_REPO': str(root)}
        env.pop('AGENT_RUNNER', None)
        env.pop('AGENT_RUNNER_SLOT', None)
        eq(run(root, 'plan', 'add', 'R', 'the parser', '--files', 'p.py', env=env).returncode, 0, 'a first task, R1')
        eq(run(root, 'plan', 'add', 'R', 'the lexer', '--files', 'l.py', env=env).returncode, 0, 'and R2')
        todo = root / 'plan' / 'TODO.md'
        before = todo.read_text(encoding='utf-8')
        for args, (rc, err) in cases:
            r = run(root, 'plan', *args, env=env)
            eq((r.returncode, r.stderr, r.stdout), (rc, err, ''), f'plan {" ".join(args)!r}')
        eq(todo.read_text(encoding='utf-8'), before, 'no refusal edits TODO.md')
        r = run(root, 'plan', 'tick', env=env)
        check(r.returncode == 0 and r.stdout.startswith('# DONE'), 'a command short of words is a lookup, as before',
              r.stdout + r.stderr)
    parse = plan._parse_command
    eq(parse(['note', 'B1', '--', 'x']).rest, ['--', 'x'], 'a literal -- stays in the text (argparse drops it)')
    eq(parse(['tick', '-x']).id, '-x', 'no word reads as an option')
    eq((parse(['tick', '--']).id, parse(['drop', '--', 'why']).id), ('--', '--'), 'not even a -- in the id slot')
    eq(parse(['block', 'B1', '--after', 'B2', 'why']).rest, ['--after', 'B2', 'why'], 'block reads its own --after')
    eq([parse(a) for a in (['tick'], ['reopen', 'x'], ['add', 'R'], [], ['B12'])], [None] * 5,
       'wrong counts, no command and an id are lookups')
    from agent_runner import cli
    import importlib
    eq([n for n, (m, f) in cli.COMMANDS.items() if not callable(getattr(importlib.import_module(f'agent_runner.{m}'), f, None))],
       [], "every cli.COMMANDS entry names a function that exists")



def test_done_gate():
    print('done.gate: runs [run] test through gitops.shell, a run past [run] command_timeout counted as failing (124)')
    from agent_runner import done
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        git(root, 'init', '-q')
        py = sys.executable.replace('\\', '/')
        (root / 'runner.toml').write_text(
            f'[run]\ncommand_timeout = 0.5\ntest = \'"{py}" -c "print(1); print(2); raise SystemExit(4)"\'\n'
            f'slow = \'"{py}" -c "import time; time.sleep(5)"\'\n', encoding='utf-8')
        eq(done.gate(root), (4, '1\n2'), 'its exit code and output, stripped')
        rc, out = done.gate(root, 'slow')
        eq(rc, 124, 'one that runs past fails')
        has(out, re.escape('ran past [run] command_timeout (0.5s): counted as failing'), 'and says so')


def test_channel():
    print('C11 channels: request waits for the answer, requests lists, respond takes it away; post and take')
    import threading
    import time
    P = plan

    class Notes:
        def __init__(self, root):
            self.root = root

        def notes(self, *parts):
            p = self.root.joinpath(*parts)
            p.parent.mkdir(parents=True, exist_ok=True)
            return p

    with tempfile.TemporaryDirectory() as tmp:
        c = Notes(Path(tmp))
        eq(P.request(c, 'ask', 'X1', {'how': 'drop'}, 0), None, 'no answer in time: None')
        eq(P.requests(c, 'ask')['X1']['how'], 'drop', 'the request stays for the run')
        (P.channel(c, 'ask') / 'BAD.json').write_text('[1]', encoding='utf-8')
        eq(sorted(P.requests(c, 'ask')), ['X1'], 'one not a JSON object is skipped')

        def run():
            while 'X2' not in P.requests(c, 'ask'):
                time.sleep(0.05)
            P.respond(c, 'ask', 'X2', 'done X2\n')
        t = threading.Thread(target=run, daemon=True)
        t.start()
        eq(P.request(c, 'ask', 'X2', {'how': 'change'}, 10), 'done X2\n', 'the answer, as the run wrote it')
        t.join(10)
        check('X2' not in P.requests(c, 'ask') and not (P.channel(c, 'ask') / 'X2.done').exists(),
              'request and answer both gone')
        eq(P.take(c, 'KEYS'), [], 'nothing posted: nothing taken')
        P.post(c, 'KEYS', 'p on', ' ', 'S off ')
        eq(P.take(c, 'KEYS'), ['p on', 'S off'], 'posted lines, stripped, blanks left out')
        eq(P.take(c, 'KEYS'), [], 'taken once')


if __name__ == '__main__':
    sys.exit(report([test_refusals, test_iter_tasks_and_titles, test_hook, test_done_gate, test_channel,test_edit, test_unlabelled_block, test_restore, test_plan_last, test_after_all, test_release_kind,test_goal,test_plan_roundtrip, test_plan_reopen, test_plan_index_and_sections, test_brief, test_brief_outline,
                     test_split_parents, test_add_bottom, test_add_pri, test_add_subtask, test_kinds, test_need_files, test_add_stray_args, test_hand_edits_commit, test_hand_edits_push, test_similar, test_add_refuses_a_duplicate, test_carry_notes,
                     test_merge3, test_concurrent_add, test_merge_driver, test_concepts, test_needs_you,
                     test_needs_own_project, test_needs_config]))
