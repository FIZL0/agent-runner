#!/usr/bin/env python3
"""Windows behaviour that runs anywhere: the slot tab's shim, and UTF-8 task-list merges.

    python3 tests/test_windows.py        (no network, no real agent; runs on Windows too)
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from _check import check, eq, git, report

from agent_runner import runner as R  # noqa: E402


def make_repo(tmp: Path) -> Path:
    repo = tmp / 'proj'
    repo.mkdir()
    git(repo, 'init', '-q', '-b', 'main')
    (repo / 'runner.toml').write_text('[run]\nmodel = "m1"\nfix_model = "m2"\n\n[git]\npush = false\n',
                                      encoding='utf-8')
    (repo / '.gitignore').write_text('.runner/\n', encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'start')
    return repo


def test_utf8_merge(tmp: Path):
    print('windows: a TODO.md conflict with non-ASCII text joins (git output is UTF-8, not the ANSI code page)')
    d = tmp / 'utf8'
    d.mkdir()
    git(d, 'init', '-q', '-b', 'main')
    (d / 'plan').mkdir()
    (d / 'runner.toml').write_text('', encoding='utf-8')
    head = '# TODO — “open” tasks\n\n### Later\n\n'
    (d / 'plan/TODO.md').write_text(head + '- [ ] **A1** one → a.py\n', encoding='utf-8')
    (d / 'plan/DONE.md').write_text('# DONE — the archive\n', encoding='utf-8')
    git(d, 'add', '-A'), git(d, 'commit', '-qm', 'base')
    git(d, 'checkout', '-qb', 'task/A2')
    (d / 'plan/TODO.md').write_text(head + '- [ ] **A1** one → a.py\n- [ ] **A2** two · b.py\n', encoding='utf-8')
    git(d, 'commit', '-qam', 'A2')
    git(d, 'checkout', '-q', 'main')
    (d / 'plan/TODO.md').write_text(head + '- [ ] **A1** one → a.py\n- [ ] **A3** three … c.py\n', encoding='utf-8')
    git(d, 'commit', '-qam', 'A3')
    R.init(d)
    base = git(d, 'rev-parse', 'HEAD')
    eq(R.merge_into(d, 'task/A2', 'm'), [], 'the task-list merge driver joins both added lines')
    text = (d / 'plan/TODO.md').read_text(encoding='utf-8')
    check('“open”' in text and '**A2** two ·' in text and '**A3** three …' in text,
          'with both lines and non-ASCII text unchanged', text)
    git(d, 'reset', '--hard', base)

    print('windows: a task id both sides gave away is renumbered, non-ASCII text intact')
    git(d, 'checkout', '-qb', 'task/A4', 'main~1')
    (d / 'plan/TODO.md').write_text(head + '- [ ] **A1** one → a.py\n- [ ] **A3** other “thing” → d.py\n',
                                    encoding='utf-8')
    git(d, 'commit', '-qam', 'A4 files A3')
    git(d, 'checkout', '-q', 'main')
    ref = R.renumber_doubles('task/A4', 'main', 'A4', d)
    check(ref != 'task/A4', 'the branch gets a renumbering commit')
    shown = R.git('show', f'{ref}:plan/TODO.md', cwd=d).stdout
    check('**A4** other “thing” → d.py' in shown or '**A5** other “thing” → d.py' in shown,
          'its A3 has a new id and its text is unchanged', shown)


def test_shim_once(repo: Path, tmp: Path):
    print('windows: a slot tab runs its job once and exits 0, so it closes and Enter cannot restart it')
    R.init(repo)
    marker, job, count = R.C.notes('slot8.live'), R.C.notes('slot8.job'), tmp / 'count'
    argv = [sys.executable, '-c', 'import sys; open(sys.argv[1], "a").write("x"); sys.exit(1)', str(count)]
    job.write_text(json.dumps({'argv': argv, 'cwd': str(repo), 'env': {}, 'marker': str(marker)}), encoding='utf-8')
    eq(R.slot_shim(str(job)), 0, 'exit 0 even when the agent was killed (taskkill leaves exit code 1)')
    eq(R.slot_shim(str(job)), 0, 'a restarted tab exits at once')
    eq(count.read_text(), 'x', 'and the session ran only once')
    eq(marker.with_suffix('.exit').read_text(), 'exit code 1', 'how the agent ended is left for the runner')
    job.write_text(json.dumps({'argv': [str(tmp / 'no-such-agent.exe')], 'cwd': str(repo), 'env': {},
                               'marker': str(marker)}), encoding='utf-8')
    eq(R.slot_shim(str(job)), 0, 'an agent that cannot start still ends the tab cleanly')
    check(marker.with_suffix('.exit').read_text().startswith('could not start'), 'and says it could not start')


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix='agent-runner-windows-'))
    repo = make_repo(tmp)
    return report([lambda: test_shim_once(repo, tmp), lambda: test_utf8_merge(tmp)])


if __name__ == '__main__':
    sys.exit(main())
