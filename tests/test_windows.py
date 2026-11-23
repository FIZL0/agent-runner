#!/usr/bin/env python3
"""Windows behaviour that runs anywhere: the slot tab's shim, and UTF-8 task-list merges.

    python3 tests/test_windows.py        (no network, no real agent; runs on Windows too)
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from _check import ROOT, check, eq, git, has, report

from agent_runner import ci  # noqa: E402
from agent_runner import cmds  # noqa: E402
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
    has(marker.with_suffix('.exit').read_text(), r'^exit code 1 \(pid \d+\)$', 'how the agent ended (and its pid) is left for the runner')
    job.write_text(json.dumps({'argv': [str(tmp / 'no-such-agent.exe')], 'cwd': str(repo), 'env': {},
                               'marker': str(marker)}), encoding='utf-8')
    eq(R.slot_shim(str(job)), 0, 'an agent that cannot start still ends the tab cleanly')
    check(marker.with_suffix('.exit').read_text().startswith('could not start'), 'and says it could not start')


def test_run_log_utf8(repo: Path):
    print('windows: run.log is UTF-8 whatever the console code page (B100: a Remote Control name\'s "·")')
    R.init(repo)
    R.log('control: control server up as "hello · control" — “quoted”')
    raw = R.C.notes('run.log').read_bytes()
    check('hello · control'.encode('utf-8') in raw, 'the "·" is written as UTF-8 (C2 B7), not as cp1252 or cp437')
    check(not raw.startswith(b'\xef\xbb\xbf'), 'no BOM: readers take the first line as a run.log line')


def test_ci_workflow(tmp: Path):
    print('windows: ci.yml runs on push and pull request, and on request for one system and some test files (T13)')
    text = (ROOT / '.github/workflows/ci.yml').read_text(encoding='utf-8')
    on = text.split('\non:\n', 1)[1].split('\npermissions:', 1)[0]
    blocks = dict(re.findall(r'^  (\w+):\n((?:    .*\n?)*)', on, re.M))
    eq(sorted(blocks), ['pull_request', 'push', 'workflow_dispatch'], 'the three triggers')
    check(ci.runs_on_push(text, 'main') and not ci.runs_on_push(text, 'task/T13'), 'push still means main only')
    for name in ('push', 'pull_request'):
        has(blocks[name], r"paths-ignore: \['plan/\*\*', '\*\*\.md'\]", f'{name} still skips the plan and Markdown')
    has(blocks['workflow_dispatch'], r'options: \[both, windows, linux\]\n +default: both', 'which system, by default both')
    has(text, r'\|\| \'\["ubuntu-latest", "windows-latest"\]\'\) \}\}', 'with no input (push, pull request) both run')
    script = text.split('- name: Test gate', 1)[1].split('run: |\n', 1)[1]
    runs = [x for x in re.split(r'\n {6}- ', text) if 'run: |' in x]
    check(all('${{' not in x.split('run: |', 1)[1] for x in runs), 'no expression is written into a script')
    has(text, r'TESTS: \$\{\{ inputs\.tests \}\}', 'the list of test files is an environment variable')

    d = tmp / 'ci'
    (d / 'tests').mkdir(parents=True)
    for n in ('test_a.py', 'test_b.py'):
        (d / 'tests' / n).write_text('', encoding='utf-8')
    script = 'python() { echo "RAN $1"; }\n' + re.sub(r'^ {10}', '', script, flags=re.M)

    def gate(tests: str):
        r = subprocess.run([cmds.bash_exe(), '--noprofile', '--norc', '-eo', 'pipefail', '-c', script], cwd=d,
                           env={**os.environ, 'TESTS': tests}, capture_output=True, encoding='utf-8')
        return r.returncode, re.findall(r'^RAN (\S+)$', r.stdout, re.M)

    both = ['tests/test_a.py', 'tests/test_b.py']
    eq(gate(''), (0, both), 'no list: every test file')
    eq(gate('  '), (0, both), 'nor a blank one')
    eq(gate('tests/test_b.py'), (0, both[1:]), 'one test file')
    eq(gate('tests/test_b.py tests/test_a.py'), (0, both[::-1]), 'two')
    for bad in ('tests/test_none.py', 'tests/*.py', '-c', 'tests/test_a.py;touch pwned', '$(touch pwned)'):
        eq(gate(bad), (1, []), f'{bad!r} fails the run and runs nothing')
    check(not (d / 'pwned').exists(), 'and nothing in the list is run as shell')


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix='agent-runner-windows-'))
    repo = make_repo(tmp)
    return report([lambda: test_shim_once(repo, tmp), lambda: test_utf8_merge(tmp), lambda: test_run_log_utf8(repo),
                   lambda: test_ci_workflow(tmp)])


if __name__ == '__main__':
    sys.exit(main())
