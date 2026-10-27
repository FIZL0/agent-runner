#!/usr/bin/env python3
"""The task list: every mutator as a round trip in a temporary directory, read back as text.

    python3 tests/test_plan.py          (no network, no agent, under a second)

Why these: plan.py edits files in place, and a bug there does not raise — it quietly eats a task line,
and nobody notices until a "finished" task turns out never to have been done.
"""
from __future__ import annotations

import os
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

        a = plan.add('D', 'the parser → src/parse.py', **kw)
        b = plan.add('D', 'the printer → src/print.py · docs/API.md', **kw)
        c = plan.add('F', 'the formatter → src/fmt.py', **kw)
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

        (d / 'D1.md').write_text('# D1\n\n- [ ] **D1** the parser\n', encoding='utf-8')
        eq(plan.tick('D1', todo=todo, done=done, plan_dir=d), 1, 'tick archives the ticked line')
        check('**D1**' not in Path(todo).read_text(), 'the ticked task is gone from TODO.md')
        has(Path(done).read_text(), r'- \[x\] \*\*D1\*\* the parser', 'with its text intact in DONE.md')
        has((d / 'D1.md').read_text(), r'- \[x\] \*\*D1\*\*', 'and ticked in its own plan/<ID>.md')
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
        for text in ('the menu → menu.py', 'the settings → settings.py', 'the lobby → lobby.py', 'a demo → d.py'):
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
            '- [ ] **R1** the parser → src/parse.py · API.md | t: tests/test_parse.py | j: r1-parser',
            '  - a sub-line that belongs to R1',
            '- [~] **R2** the printer → src/print.py BLOCKED: needs R1',
            '', '### Stretch', '', '- [ ] **K1** a web page → web/index.html', '']), encoding='utf-8')
        eq(plan.index(todo), ['# TODO', '### Next (in this order)', '[ ] R1', '[~] R2', '### Stretch', '[ ] K1'],
           'index is headings and ids only — the whole backlog in a screenful')
        eq(plan.section(todo, 'R1'),
           ['- [ ] **R1** the parser → src/parse.py · API.md | t: tests/test_parse.py | j: r1-parser',
            '  - a sub-line that belongs to R1'], 'a task by id brings its sub-lines with it')
        eq(plan.section(todo, 'Stretch'), ['### Stretch', '', '- [ ] **K1** a web page → web/index.html'],
           'a section by heading substring')
        eq(plan.section(todo, 'nope'), [], 'an unknown name is empty, not an error')
        eq(plan.files_on_line('→ src/parse.py · API.md | t: tests/test_parse.py', root=root),
           ['src/parse.py', 'docs/API.md'],
           'files_on_line resolves a bare name against the repo, and stops at the tests')
        eq(plan.files_on_line('mentions notes.py in prose → new.py', root=root), ['new.py'],
           'a new top-level file after the → counts; one named only in prose does not')


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
            '# TODO\n\n### Next\n\n- [ ] **D3** the printer → docs/API.md · src/new.py | t: none | j: d3-printer\n',
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
        r = run(root, 'plan', 'brief', 'D3')
        check(r.returncode == 0 and '## Task D3' in r.stdout, '`run plan brief` works from the repo', r.stderr)
        r = run(root / 'docs', 'plan', 'block', 'D3', '--after', 'X9', 'waits on X9')
        has((root / 'plan/TODO.md').read_text(), r'BLOCKED: \(after X9\) waits on X9',
            '`run plan block --after` from a subdirectory edits the repo\'s plan')


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
            eq(plan.add_default(), 'bottom', "a running agent's follow-up goes to the bottom")
            del os.environ['AGENT_RUNNER']
            eq(plan.add_default(), 'top', "a person's task goes to the top")
        finally:
            if old is not None:
                os.environ['AGENT_RUNNER'] = old


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


def test_similar():
    print('plan: add names an open task that looks like the same work, and stays quiet otherwise')
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp) / 'plan'
        todo, done = plan.ensure(d / 'TODO.md', d / 'DONE.md')
        kw = dict(todo=todo, done=done)
        plan.add('V', "the radar's map names go inside the minimap → src/hud.rs", **kw)
        plan.add('V', 'world tiles pop in at once; stream them nearest first → src/tiles.rs · src/main.rs', **kw)
        plan.add('P', 'the menu sound plays when a slider moves → src/menu.rs · src/main.rs', **kw)
        plan.add('P', 'the garage shows each bike in its own colours → src/garage.rs · src/main.rs', **kw)
        plan.add('S', 'a done one about the radar and its minimap names → src/hud.rs', **kw)
        plan.tick('S1', **kw)
        got = plan.similar("show the map names inside the radar's minimap → src/hud.rs", todo=todo)
        eq([g.split(':')[0] for g in got], ['V1'], 'the same work is named, and a done task is not')
        has(got[0], r"^V1: the radar's map names go inside the minimap$", 'as its id and the start of its text')
        eq(plan.similar('the rider leans too far in a berm → src/rider.rs', todo=todo), [],
           'unrelated work prints nothing, so an agent pays nothing for it')
        eq([g.split(':')[0] for g in plan.similar('stream tiles nearest first, they pop in → src/tiles.rs', todo=todo)],
           ['V2'], 'a shared rare file and some of the words is enough')
        eq(plan.similar('the main menu → src/main.rs', todo=todo, skip='P1'), [],
           'a file every task names is not a match by itself')


if __name__ == '__main__':
    sys.exit(report([test_plan_roundtrip, test_plan_reopen, test_plan_index_and_sections, test_brief,
                     test_split_parents, test_add_bottom, test_hand_edits_commit, test_similar]))
