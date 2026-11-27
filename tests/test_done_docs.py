#!/usr/bin/env python3
"""F37: `done` skips the slow test gate on a docs-only diff.

    python3 tests/test_done_docs.py        (no network; a few seconds, mostly git)

The gate decides by the diff, not the task's letter: when every file the work changes (commits since the
shared branch, staged, unstaged, untracked) matches `[run] docs_files` (default `*.md`, `docs/**`), `done`
prints 'docs only, gate skipped' and runs `[run] docs_check` instead (if set); a mixed diff runs the gate.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from _check import check, eq, git, has, report, run


def make(tmp: Path) -> tuple[Path, dict, Path, Path]:
    root = tmp / 'proj'
    root.mkdir()
    ran, docs_ran = tmp / 'gate-ran.log', tmp / 'docs-ran.log'
    git(root, 'init', '-q', '-b', 'main')
    (root / 'gate.py').write_text(f'open({str(ran)!r}, "a").write("ran\\n")\n', encoding='utf-8')
    (root / 'check_docs.py').write_text(
        f'import os, sys\nopen({str(docs_ran)!r}, "a").write("ran\\n")\n'
        'sys.exit(3 if os.path.exists("docs/BAD.md") else 0)\n', encoding='utf-8')
    (root / 'a.py').write_text('# a\n', encoding='utf-8')
    (root / 'runner.toml').write_text('[run]\nremote = false\nreview = false\ntest = "python3 gate.py"\n'
                                      'docs_check = "python3 check_docs.py"\n', encoding='utf-8')
    (root / '.gitignore').write_text('.runner/\n', encoding='utf-8')
    git(root, 'add', '-A')
    git(root, 'commit', '-qm', 'start')
    env = {**os.environ, 'AGENT_RUNNER_REPO': str(root)}
    env.pop('AGENT_RUNNER', None)
    for text in ('fix the readme | files: README.md', 'docs and code | files: a.py', 'bad anchor | files: docs/**'):
        check(run(root, 'plan', 'add', 'B', text, env=env).returncode == 0, f'added {text}')
    git(root, 'add', '-A')
    if git(root, 'status', '--porcelain'):  # `plan add` may have committed it already
        git(root, 'commit', '-qm', 'plan')
    check(git(root, 'status', '--porcelain') == '', 'main is clean before the tasks start')
    return root, env, ran, docs_ran


def count(f: Path) -> int:
    return f.read_text().count('ran') if f.exists() else 0


def test_docs_only_skips_gate():
    print('done: a docs-only diff skips the gate (docs check only); a mixed one runs it')
    with tempfile.TemporaryDirectory() as t:
        root, env, ran, docs_ran = make(Path(t))
        git(root, 'checkout', '-q', '-b', 'task/B1')
        (root / 'README.md').write_text('# readme\n', encoding='utf-8')
        git(root, 'add', 'README.md')
        git(root, 'commit', '-qm', 'B1: readme')
        (root / 'docs').mkdir()
        (root / 'docs/guide.txt').write_text('untracked, still docs\n', encoding='utf-8')
        r = run(root, 'done', 'B1', 'B1: the readme', env=env)
        check(r.returncode == 0, 'a B fix that only edits docs finishes', r.stdout + r.stderr)
        has(r.stdout, r'docs only, gate skipped', 'and says the gate was skipped')
        eq(count(ran), 0, 'the gate did not run')
        eq(count(docs_ran), 1, '[run] docs_check ran instead')
        check('gate passed' not in r.stdout, 'no "gate passed" line', r.stdout)
        check(git(root, 'for-each-ref', 'refs/agent-runner/tested/B1') == '',
              'no tested ref: the merge decides by its own diff')
        has((root / 'plan/DONE.md').read_text() + (root / 'plan/TODO.md').read_text(), r'\[x\] \*\*B1\*\*', 'ticked')

        git(root, 'checkout', '-q', '-b', 'task/B2', 'main')
        (root / 'notes.md').write_text('a note\n', encoding='utf-8')
        (root / 'a.py').write_text('# a, changed\n', encoding='utf-8')
        r = run(root, 'done', 'B2', 'B2: docs and code', env=env)
        check(r.returncode == 0, 'a mixed diff finishes', r.stdout + r.stderr)
        check('docs only' not in r.stdout, 'and is not docs only', r.stdout)
        eq(count(ran), 1, 'the gate ran on it')
        has(r.stdout, r'gate passed: python3 gate\.py', 'and passed')

        git(root, 'checkout', '-q', '-b', 'task/B3', 'main')
        (root / 'docs').mkdir(exist_ok=True)
        (root / 'docs/BAD.md').write_text('[x](#gone)\n', encoding='utf-8')
        r = run(root, 'done', 'B3', 'B3: anchors', env=env)
        check(r.returncode == 1, 'a docs-only diff whose docs check fails does not finish', r.stdout + r.stderr)
        has(r.stderr, r'The docs check \(`python3 check_docs.py`\) failed: nothing ticked', 'and ticks nothing')
        eq(count(ran), 1, 'still without the gate')
        check('- [ ] **B3**' in (root / 'plan/TODO.md').read_text(), 'B3 stays open')


def test_description_only_manifest():
    print('F494: a manifest whose only change is its description counts as docs; a version or dependency change does not')
    from agent_runner.done_docs import changed, docs_only
    globs = ['*.md', 'docs/**']
    with tempfile.TemporaryDirectory() as t:
        root = Path(t)
        git(root, 'init', '-q', '-b', 'main')
        (root / 'pyproject.toml').write_text('[project]\nname = "x"\nversion = "1.0"\ndescription = "old"\n'
                                             'dependencies = []\n', encoding='utf-8')
        (root / 'package.json').write_text('{\n  "name": "x",\n  "description": "old",\n  "version": "1.0"\n}\n',
                                           encoding='utf-8')
        git(root, 'add', '-A')
        git(root, 'commit', '-qm', 'start')
        old = os.environ.get('AGENT_RUNNER_REPO')
        os.environ['AGENT_RUNNER_REPO'] = str(root)
        git(root, 'checkout', '-q', '-b', 'task/D1')
        (root / 'README.md').write_text('# x\n', encoding='utf-8')
        (root / 'pyproject.toml').write_text('[project]\nname = "x"\nversion = "1.0"\ndescription = "new"\n'
                                             'dependencies = []\n', encoding='utf-8')
        (root / 'package.json').write_text('{\n  "name": "x",\n  "description": "new",\n  "version": "1.0"\n}\n',
                                           encoding='utf-8')
        check(docs_only(changed(root), globs), 'description-only manifests and a readme: gate skipped',
              changed(root))
        (root / 'pyproject.toml').write_text('[project]\nname = "x"\nversion = "1.1"\ndescription = "new"\n'
                                             'dependencies = []\n', encoding='utf-8')
        check(not docs_only(changed(root), globs), 'description plus a version: gated', changed(root))
        (root / 'pyproject.toml').write_text('[project]\nname = "x"\nversion = "1.0"\ndescription = "new"\n'
                                             'dependencies = ["y"]\n', encoding='utf-8')
        check(not docs_only(changed(root), globs), 'description plus a dependency: gated', changed(root))
        from agent_runner.done_docs import mark_descriptions
        git(root, 'commit', '-qam', 'deps')
        eq(mark_descriptions('main', 'HEAD', ['package.json', 'pyproject.toml'], root),
           ['package.json#description', 'pyproject.toml'], 'a merge diff marks only the description-only one')
        if old is None:
            os.environ.pop('AGENT_RUNNER_REPO', None)
        else:
            os.environ['AGENT_RUNNER_REPO'] = old


def test_concept_brief_page():
    print('F77: the concept brief tells a K task to pass --page <its HTML> to done --artifact')
    from agent_runner import brief as B
    text = B.CONCEPT_PROMPT.format(runner='./run', tid='K7')
    has(text, r'done K7 "<msg>" --artifact <the page\'s URL> --page <the HTML file you published>',
        'done is given the page\'s URL and the file it was published from')
    has(text, r'\.runner/concepts/K7\.html', 'and says where the copy goes')


if __name__ == '__main__':
    raise SystemExit(report([test_docs_only_skips_gate, test_description_only_manifest, test_concept_brief_page]))
