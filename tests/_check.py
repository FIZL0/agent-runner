"""The tests' few helpers: plain prints, no framework, so `python3 tests/test_x.py` is the whole interface."""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'run'
sys.path.insert(0, str(ROOT))

FAILED: list[str] = []

# git that ignores the user's config (signing, hooks, a default branch name) and needs no identity
_gitconfig = tempfile.NamedTemporaryFile('w', prefix='agent-runner-test-gitconfig', delete=False)
_gitconfig.write('[user]\n\tname = test\n\temail = test@example.invalid\n[init]\n\tdefaultBranch = main\n')
_gitconfig.close()
os.environ.update(GIT_CONFIG_GLOBAL=_gitconfig.name, GIT_CONFIG_NOSYSTEM='1')
os.environ.pop('AGENT_RUNNER_REPO', None)
# a gate run by `done` in a slot inherits the slot session's markers: without this the code under test acts
# as a slot's agent (no skill install, a different plan path) and the suites fail only inside a run
os.environ.pop('AGENT_RUNNER_SLOT', None)
os.environ.pop('AGENT_RUNNER', None)
# nor the slot's tmux: code under test would set options on the real pane (tests that need tmux mock these)
os.environ.pop('TMUX', None)
os.environ.pop('TMUX_PANE', None)
os.environ['AGENT_RUNNER_NO_NOTIFY'] = '1'  # an alarm in a test rings no tmux message or desktop notification
os.environ['CLAUDE_CONFIG_DIR'] = tempfile.mkdtemp(prefix='agent-runner-test-claude-')  # never the real ~/.claude
# worktrees and plan clones go under a temp folder, never the real ~/runs
os.environ['AGENT_RUNNER_HOME'] = str(Path(tempfile.mkdtemp(prefix='agent-runner-test-runs-')) / '{repo}')


def check(ok, what, extra=''):
    print(('  ok   ' if ok else '  FAIL ') + what + ('' if ok else f'\n         {extra}'))
    if not ok:
        FAILED.append(what)


def eq(got, want, what):
    check(got == want, what, f'got {got!r}\n         want {want!r}')


def has(text, pat, what):
    check(re.search(pat, text, re.M) is not None, what, f'no /{pat}/ in:\n{text[-800:]}')


def git(cwd, *a) -> str:
    cwd = Path(cwd)
    bare = (cwd / 'HEAD').is_file() and (cwd / 'objects').is_dir() and (cwd / 'refs').is_dir()
    args = ['git', '--git-dir', str(cwd.resolve()), *a] if bare else ['git', *a]
    r = subprocess.run(args, cwd=str(cwd), capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f'git {" ".join(a)}: {r.stderr}')
    return r.stdout.strip()


def run(cwd, *a, **kw) -> subprocess.CompletedProcess:
    """`./run <a>` in cwd, the way an agent session calls it."""
    return subprocess.run([sys.executable, str(RUN), *a], cwd=str(cwd), capture_output=True, text=True, **kw)


def report(tests) -> int:
    for t in tests:
        t()
    print()
    if FAILED:
        print(f'{len(FAILED)} FAILED:')
        for f in FAILED:
            print(f'  - {f}')
        return 1
    print('all checks passed')
    return 0
