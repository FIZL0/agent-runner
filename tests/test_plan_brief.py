#!/usr/bin/env python3
"""`plan brief`: what a session starts from.

    python3 tests/test_plan_brief.py          (no network, no agent, under a second)

Split out of tests/test_plan.py (C52), with the same checks.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from _check import check, git, has, report, run

from agent_runner import plan  # noqa: E402

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

if __name__ == '__main__':
    sys.exit(report([test_brief, test_brief_outline]))
