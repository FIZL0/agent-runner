#!/usr/bin/env python3
"""F17: wizards for BLOCKED items a person must do by hand.

    python3 tests/test_wizard.py        (no network; a second or two, mostly git)

A BLOCKED item with `<notes>/wizards/<ID>.sh` shows `run: <runner> wizard <ID>` under it in status; the slot
brief tells agents when to write one; `wizard ID` checks it with bash -n, runs it, and confirms the item when
it ends well; `[run] wizards = false` turns all of it off.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from _check import check, eq, git, has, report, run

from agent_runner import plan as P  # noqa: E402
from agent_runner import runner as R  # noqa: E402


def make(tmp: Path, toml: str = '') -> tuple[Path, dict]:
    root = tmp / 'proj'
    root.mkdir()
    git(root, 'init', '-q')
    (root / 'runner.toml').write_text('[run]\nremote = false\n' + toml, encoding='utf-8')
    (root / '.gitignore').write_text('.runner/\n', encoding='utf-8')
    git(root, 'add', '-A')
    git(root, 'commit', '-qm', 'start')
    env = {**os.environ, 'AGENT_RUNNER_REPO': str(root)}
    env.pop('AGENT_RUNNER', None)
    for text in ('signing setup | files: a.py', 'pick a database | files: b.py'):
        check(run(root, 'plan', 'add', 'F', text, env=env).returncode == 0, f'added {text}')
    return root, env


def test_template():
    print('the vendored template parses and says where it comes from')
    t = R.WIZARD_TEMPLATE
    check(t.is_file(), 'agent_runner/wizard_template.sh is there', t)
    if shutil.which('bash'):
        r = subprocess.run(['bash', '-n', str(t)], capture_output=True, text=True)
        eq(r.returncode, 0, 'bash -n passes on it')
    text = t.read_text(encoding='utf-8')
    has(text, r'mattpocock/skills', 'with its source')
    has(text, r'MIT License, Copyright \(c\) 2026 Matt Pocock', 'and its licence')
    has(text, r'^# STAGES: author this section', 'and the STAGES marker agents write under')


def test_status_and_brief():
    print('a BLOCKED item with a wizard shows its run command; the brief says when to write one')
    with tempfile.TemporaryDirectory() as t:
        root, env = make(Path(t))
        R.init(root)
        todo = R.C.todo
        P.block('F1', 'BLOCKED: set up the iOS signing certificate (.p12) and key (.p8)', todo=todo)
        P.block('F2', 'DECIDE: Postgres or SQLite?', todo=todo)
        text = R.status_text(False, {}, [], {}, 0.0, waiting=R.waiting_ok())
        check('wizard' not in text, 'no wizard file: no run line', text)
        f = R.C.notes('wizards', 'F1.sh')
        f.write_text('#!/usr/bin/env bash\necho hi\n', encoding='utf-8')
        eq(R.wizard_file('F1'), f, 'wizard_file finds <notes>/wizards/F1.sh')
        text = R.status_text(False, {}, [], {}, 0.0, waiting=R.waiting_ok())
        lines = text.splitlines()
        i = next((n for n, l in enumerate(lines) if '[F1]' in l), -1)
        check(i >= 0 and lines[i + 1:i + 2] == [f'    run: {R.C.command} wizard F1'],
              'status: the run command on the line under the item', text)
        check(text.count('run: ') == 1, 'and only under the item that has one', text)

        p = R.prompt_for('F1', 1, 1, root, 'main')
        has(p, r'When you block with `BLOCKED:` because of steps only a person can take', 'the brief says when')
        has(p, re.escape(str(f)), 'and where the wizard goes')
        has(p, re.escape(str(R.WIZARD_TEMPLATE)), 'and the template to start from')
        has(p, r'bash -n ', 'and to check it with bash -n')
        has(p, r'only for steps you cannot do yourself', 'only for steps the agent cannot do')
        has(p, re.escape(f'{R.C.command} wizard F1'), 'and the command the person gets')
        check(p.index('When you block with `BLOCKED:`') < p.index('Project policies:'), 'before the policies')
        has(p, r'Before a `BLOCKED:` on access, check what this machine already has', 'F30: check access first')
        for probe in ('`gh auth status`', '`wrangler whoami`', '`ssh -T`', '~/.claude/ACCESS.md'):
            check(probe in p, f'F30: the check-first sentence names {probe}', p)
        has(p, r'names the exact command that failed and its error', 'F30: and BLOCKED: names the failure')

        R.C.run['wizards'] = False
        try:
            check('wizard' not in R.prompt_for('F1', 1, 1, root, 'main'), 'wizards = false: not in the brief')
            text = R.status_text(False, {}, [], {}, 0.0, waiting=R.waiting_ok())
            check('run: ' not in text, 'nor in status', text)
        finally:
            R.C.run['wizards'] = True


def test_wizard_command():
    print('`wizard ID` checks the script, runs it, and confirms the item when it ends well')
    if not shutil.which('bash'):
        print('  skip: no bash here')
        return
    with tempfile.TemporaryDirectory() as t:
        root, env = make(Path(t))
        todo = root / 'plan' / 'TODO.md'
        r = run(root, 'done', 'F1', 'F1: signing', '--no-test', '--blocked',
                'BLOCKED: set up the iOS signing certificate', env=env)
        check(r.returncode == 0, 'blocked with BLOCKED:', r.stdout + r.stderr)
        r = run(root, 'wizard', 'F1', env=env)
        check(r.returncode != 0 and 'has no wizard' in r.stderr, 'no wizard: says so', r.stderr)
        f = Path(run(root, 'wizard', 'F1', '--path', env=env).stdout.strip())
        eq(f, root / '.runner' / 'wizards' / 'F1.sh', '--path: where it goes')
        f.parent.mkdir(parents=True, exist_ok=True)

        f.write_text('#!/usr/bin/env bash\nif then fi (\n', encoding='utf-8')
        r = run(root, 'wizard', 'F1', env=env)
        check(r.returncode != 0 and 'does not parse' in r.stderr, 'a script bash -n refuses is not run', r.stderr)

        f.write_text('#!/usr/bin/env bash\necho step one\nexit 3\n', encoding='utf-8')
        r = run(root, 'wizard', 'F1', env=env)
        check(r.returncode == 3 and 'still needs you' in r.stderr, 'a wizard that stops leaves it waiting',
              r.stdout + r.stderr)
        has(todo.read_text(encoding='utf-8'), r'^- \[~\] \*\*F1\*\* .*BLOCKED: BLOCKED: set up', 'still blocked')

        f.write_text('#!/usr/bin/env bash\necho "ran in $PWD" > wizard.out\n', encoding='utf-8')
        eq(run(root, 'wizard', 'F1', '--check', env=env).returncode, 0, '--check: bash -n only')
        check(not (root / 'wizard.out').exists(), 'and runs nothing')
        r = run(root, 'wizard', 'F1', env=env)
        check(r.returncode == 0, 'a wizard that ends well goes through', r.stdout + r.stderr)
        check((root / 'wizard.out').is_file(), 'it ran in the main checkout')
        has(todo.read_text(encoding='utf-8'),
            r'^- \[ \] \*\*F1\*\* .*your answer \(BLOCKED .*\): the wizard ran to the end$',
            'and confirmed the item: reopened with it noted')


if __name__ == '__main__':
    raise SystemExit(report([test_template, test_status_and_brief, test_wizard_command]))
