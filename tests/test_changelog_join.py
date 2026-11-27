#!/usr/bin/env python3
"""C47: runner.toml's `[run] joinable` holds CHANGELOG.md, and the merge joins it on real git merges.

    python3 tests/test_changelog_join.py        (no network; a second of git)

Two branches each add an entry under Unreleased: both stay, once. A branch that wrote its entry before a
release merges under Unreleased, not under the released version.
"""
from __future__ import annotations

import sys
import tempfile
import tomllib
from pathlib import Path

from _check import ROOT, check, eq, git, report

from agent_runner import runner as R  # noqa: E402
from agent_runner import join as J  # noqa: E402
from agent_runner import merge as M  # noqa: E402

BASE = ('# Changelog\n\n## Unreleased\n\n- Added: old unreleased (X1).\n\n'
        '## 0.1.0 (2026-01-01)\n\n- Added: first (X0).\n')


def make_repo(tmp: Path) -> Path:
    repo = tmp / 'proj'
    repo.mkdir(parents=True)
    git(repo, 'init', '-q', '-b', 'main')
    (repo / 'plan').mkdir()
    (repo / 'plan/TODO.md').write_text('# TODO\n', encoding='utf-8')
    (repo / 'plan/DONE.md').write_text('# DONE\n', encoding='utf-8')
    (repo / 'CHANGELOG.md').write_text(BASE, encoding='utf-8')
    # this repo's own runner.toml (joinable and [run.join]) and the joiner it names, over a gate that passes
    real = (ROOT / 'runner.toml').read_text(encoding='utf-8')
    (repo / 'runner.toml').write_text(real.replace('[run]\n', '[run]\nremote = false\nmin_free_gb = 0\n', 1)
                                      .replace('auto_upgrade = true', 'auto_upgrade = false')
                                      .replace('auto_release = { "every" = 10, "idle" = true }', ''),
                                      encoding='utf-8')
    (repo / 'tools').mkdir()
    (repo / 'tools/changelog_join.py').write_text((ROOT / 'tools/changelog_join.py').read_text(encoding='utf-8'),
                                                  encoding='utf-8')
    (repo / '.gitignore').write_text('.runner/\n', encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'start')
    return repo


def branch(repo: Path, name: str, edit):
    git(repo, 'checkout', '-q', '-b', name, 'main')
    p = repo / 'CHANGELOG.md'
    p.write_text(edit(p.read_text(encoding='utf-8')), encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', name)
    git(repo, 'checkout', '-q', 'main')


def add_entry(text: str, entry: str) -> str:
    return text.replace('## Unreleased\n\n', f'## Unreleased\n\n{entry}\n', 1)


def merge(repo: Path, name: str) -> list[str] | None:
    files = M.merge_into(repo, name, f'merge {name}', name)
    if files:
        check(M.joined(files, name, repo), f'{name}: the conflict in {files} is joined')
    return files


def section(text: str, head: str) -> str:
    return text.split(head, 1)[1].split('\n## ', 1)[0]


def test_config():
    print('runner.toml: joinable holds CHANGELOG.md')
    cfg = tomllib.loads((ROOT / 'runner.toml').read_text(encoding='utf-8'))
    check('CHANGELOG.md' in cfg['run'].get('joinable', []), 'joinable holds "CHANGELOG.md"')
    check('CHANGELOG.md' in cfg['run'].get('join', {}), '[run.join] names the changelog joiner')


def test_two_branches(tmp: Path):
    print('two branches add to Unreleased: both entries stay, once')
    repo = make_repo(tmp / 'a')
    R.init(repo)
    branch(repo, 'task/A', lambda t: add_entry(t, '- Added: entry A (A1).'))
    branch(repo, 'task/B', lambda t: add_entry(t, '- Added: entry B (B1).'))
    check(merge(repo, 'task/A') == [], 'the first merges clean')
    files = merge(repo, 'task/B')
    check(files == ['CHANGELOG.md'], 'the second conflicts in the changelog only, and is joined')
    text = (repo / 'CHANGELOG.md').read_text(encoding='utf-8')
    for e in ('entry A (A1)', 'entry B (B1)', 'old unreleased (X1)', 'first (X0)'):
        eq(text.count(e), 1, f'"{e}" once')
    check('<<<<' not in text and '>>>>' not in text, 'no conflict marks')
    un = section(text, '## Unreleased')
    check('entry A' in un and 'entry B' in un, 'both under Unreleased')


def test_before_release(tmp: Path):
    print('an entry written before a release merges under Unreleased, not the released version')
    repo = make_repo(tmp / 'b')
    R.init(repo)
    branch(repo, 'task/A', lambda t: add_entry(t, '- Added: entry A (A1).'))
    # main releases meanwhile: the Unreleased entries move under a new version
    git(repo, 'checkout', '-q', 'main')
    p = repo / 'CHANGELOG.md'
    p.write_text(p.read_text(encoding='utf-8').replace(
        '## Unreleased\n\n', '## Unreleased\n\n## 0.2.0 (2026-02-01)\n\n', 1), encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'release 0.2.0')
    check(merge(repo, 'task/A') == ['CHANGELOG.md'], 'the merge conflicts in the changelog and is joined')
    text = p.read_text(encoding='utf-8')
    eq(text.count('entry A (A1)'), 1, 'the entry once')
    eq(text.count('old unreleased (X1)'), 1, 'the released entry once')
    check('entry A' in section(text, '## Unreleased'), 'entry A is under Unreleased')
    check('entry A' not in section(text, '## 0.2.0'), 'entry A is not under 0.2.0')


def test_main_into_branch(tmp: Path):
    print('the other way: main, which released, merged into the task branch')
    repo = make_repo(tmp / 'c')
    R.init(repo)
    branch(repo, 'task/A', lambda t: add_entry(t, '- Added: entry A (A1).'))
    p = repo / 'CHANGELOG.md'
    p.write_text(p.read_text(encoding='utf-8').replace(
        '## Unreleased\n\n', '## Unreleased\n\n## 0.2.0 (2026-02-01)\n\n', 1), encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'release 0.2.0')
    git(repo, 'checkout', '-q', 'task/A')
    check(merge(repo, 'main') == ['CHANGELOG.md'], 'the merge conflicts in the changelog and is joined')
    text = p.read_text(encoding='utf-8')
    eq(text.count('entry A (A1)'), 1, 'the entry once')
    eq(text.count('## 0.2.0'), 1, 'the release heading once')
    check('entry A' in section(text, '## Unreleased'), 'entry A is under Unreleased')
    check('entry A' not in section(text, '## 0.2.0'), 'entry A is not under 0.2.0')
    check('old unreleased (X1)' in section(text, '## 0.2.0'), 'the released entry stays under 0.2.0')


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        return report([test_config, lambda: test_two_branches(Path(tmp)), lambda: test_before_release(Path(tmp)),
                       lambda: test_main_into_branch(Path(tmp))])


if __name__ == '__main__':
    sys.exit(main())
