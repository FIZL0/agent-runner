#!/usr/bin/env python3
"""Concept tasks: the page, its build, the OK.

    python3 tests/test_plan_concepts.py          (no network, no agent, under a second)

Split out of tests/test_plan.py (C52), with the same checks.
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

from _check import check, eq, git, has, report, run

from agent_runner import plan  # noqa: E402

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


def test_concept_shown():
    print('plan: F108 a concept page shown inline is filed done, waits for an OK, and approve queues its build')
    from agent_runner import state as S
    from agent_runner import status as ST
    from agent_runner import ui_model as U
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        git(root, 'init', '-q')
        (root / '.gitignore').write_text('.runner/\n', encoding='utf-8')
        git(root, 'add', '-A'); git(root, 'commit', '-qm', 'start')
        env = {**os.environ, 'AGENT_RUNNER_REPO': str(root)}
        env.pop('AGENT_RUNNER', None)
        todo, done = root / 'plan' / 'TODO.md', root / 'plan' / 'DONE.md'
        url = 'https://claude.ai/artifact/1CoELB891EqJhHmNGNJgVK'
        eq(run(root, 'plan', 'concept', 'Run picker colours', env=env).returncode, 2, 'no --page: refused')
        eq(run(root, 'plan', 'concept', 'Run picker colours', '--page', 'the page', env=env).returncode, 2,
           '--page must be a URL')
        r = run(root, 'plan', 'concept', 'Run picker colours', '--page', url, '--files', 'web/picker.css', env=env)
        check(r.returncode == 0, 'plan concept goes through', r.stdout + r.stderr)
        has(r.stdout, r'concept K1 filed, done: its build F1 waits for the OK on ' + re.escape(url),
            'it names the concept and its waiting build')
        has(done.read_text(encoding='utf-8'), r'- \[x\] \*\*K1\*\* Run picker colours \| files: web/picker\.css.*'
            r'concept page: ' + re.escape(url), 'the concept is ticked with its page noted')
        has(todo.read_text(encoding='utf-8'), r'^- \[~\] \*\*F1\*\* Build the option a person approves on concept '
            r'K1\'s page: Run picker colours \| files: web/picker\.css BLOCKED: waiting for your OK on ' + re.escape(url),
            'its build waits for the OK, as a finished K task leaves it')
        eq(git(root, 'status', '--porcelain'), '', 'committed')

        S.init(root)
        w = ST.waiting_ok()
        eq([(x[0], x[1], x[2], x[4]) for x in w], [('CONCEPT', 'F1', 'K1', url)], 'waiting_ok lists it with its url')
        needs, concepts = U.needs_rows(w, __import__('datetime').datetime.now())
        eq([(c['id'], c['concept'], c['url'], c['title']) for c in concepts],
           [('F1', 'K1', url, 'Run picker colours')], 'the run page Concepts view shows it')
        eq([n['id'] for n in needs], ['F1'], 'and Needs you')

        r = run(root, 'plan', 'approve', 'K1', 'option B: muted', env=env)
        has(r.stdout, r'approved: F1 is open', 'approve on the concept id opens its build')
        has(todo.read_text(encoding='utf-8'), r'^- \[ \] \*\*F1\*\* .* — approved \(' + re.escape(url)
            + r'\): option B: muted$', 'the build is queued with the choice noted')

        (root / 'runner.toml').write_text('[plan.kinds]\nF = "feature"\nB = "bug"\n', encoding='utf-8')
        r = run(root, 'plan', 'concept', 'Menu', '--page', url, env=env)
        has(r.stdout, r'^F2 filed: its build F2 waits', 'kinds without K: only the waiting build is filed')
        has(todo.read_text(encoding='utf-8'), r'^- \[~\] \*\*F2\*\* .*BLOCKED: waiting for your OK on ', 'blocked on the OK')

if __name__ == '__main__':
    sys.exit(report([test_concepts, test_concept_shown]))
