#!/usr/bin/env python3
"""B80: slots verify before asking.

    python3 tests/test_verify.py        (no network; a second or two, mostly git)

The slot brief tells agents to try ~/.claude/ACCESS.md and the repo CLAUDE.md's `## Tools` section before
handing a check to a person; `setup` adds an empty `## Tools` section to CLAUDE.md once.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from _check import check, eq, git, has, report, run

from agent_runner import runner as R  # noqa: E402
from agent_runner import setup as S  # noqa: E402


def test_brief():
    print('the slot brief names ACCESS.md and the ## Tools section')
    with tempfile.TemporaryDirectory() as t:
        root = Path(t) / 'proj'
        root.mkdir()
        git(root, 'init', '-q')
        (root / 'runner.toml').write_text('[run]\nremote = false\n', encoding='utf-8')
        (root / '.gitignore').write_text('.runner/\n', encoding='utf-8')
        git(root, 'add', '-A')
        git(root, 'commit', '-qm', 'start')
        env = {**os.environ, 'AGENT_RUNNER_REPO': str(root)}
        check(run(root, 'plan', 'add', 'F', 'a check | files: a.py', env=env).returncode == 0, 'added F1')
        R.init(root)
        p = R.prompt_for('F1', 1, 1, root, 'main')
        has(p, r'~/\.claude/ACCESS\.md if it exists \(this machine', 'names ACCESS.md as the machine logins')
        has(p, r'`## Tools` section of the repo\'s CLAUDE\.md', 'names CLAUDE.md\'s ## Tools section')
        has(p, r'physical device, a judgment call', 'and what still goes to a person')


def test_setup_tools():
    print('setup adds an empty ## Tools section to CLAUDE.md once')
    with tempfile.TemporaryDirectory() as t:
        root = Path(t)
        eq(S.ensure_tools(root), 'CLAUDE.md', 'no CLAUDE.md: created with the section')
        eq((root / 'CLAUDE.md').read_text(encoding='utf-8'), S.TOOLS_SECTION, 'holding only the section')
        f = root / 'CLAUDE.md'
        f.write_text('# Rules\n\nBe kind.', encoding='utf-8')
        eq(S.ensure_tools(root), 'CLAUDE.md', 'no heading: added')
        text = f.read_text(encoding='utf-8')
        eq(text, '# Rules\n\nBe kind.\n\n' + S.TOOLS_SECTION, 'after the rules, a blank line between')
        has(text, r'^<!-- .*ssh hosts, preview servers, headless checks', 'with its one-line comment')
        eq(S.ensure_tools(root), None, 'rerun: nothing to do')
        eq(f.read_text(encoding='utf-8'), text, 'and the file unchanged')
        f.write_text('# Rules\n\n## Tools\n\n- ssh box1\n', encoding='utf-8')
        eq(S.ensure_tools(root), None, 'a filled-in section is left alone')
        eq(f.read_text(encoding='utf-8').count('## Tools'), 1, 'one heading')


def test_setup_main():
    print('agent-runner setup adds the section, and a rerun leaves it alone')
    with tempfile.TemporaryDirectory() as t:
        root = Path(t)
        git(root, 'init', '-q')
        (root / 'CLAUDE.md').write_text('# Rules\n', encoding='utf-8')
        git(root, 'add', '-A')
        git(root, 'commit', '-qm', 'start')
        launch = S.launch
        S.launch = lambda r, text: 0  # no Claude session in a test
        try:
            eq(S.main(['--yes'], cwd=root), 0, 'setup ran')
            text = (root / 'CLAUDE.md').read_text(encoding='utf-8')
            eq(text.count('## Tools'), 1, 'CLAUDE.md has the heading')
            eq(S.main(['--yes'], cwd=root), 0, 'setup ran again')
            eq((root / 'CLAUDE.md').read_text(encoding='utf-8'), text, 'and left CLAUDE.md as it was')
        finally:
            S.launch = launch


if __name__ == '__main__':
    raise SystemExit(report([test_brief, test_setup_tools, test_setup_main]))
