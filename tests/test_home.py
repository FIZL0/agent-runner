"""[run] home: where a project's worktrees and plan clone live, its override, and the pre-0.13 places."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from _check import FAILED, eq, git

from agent_runner.config import Config

tmp = Path(tempfile.mkdtemp(prefix='agent-runner-home-'))
repo = tmp / 'proj'
repo.mkdir()
git(repo, 'init', '-q')
git(repo, 'commit', '-q', '--allow-empty', '-m', 'start')
env = os.environ.pop('AGENT_RUNNER_HOME')

print('home defaults to ~/runs/<repo>, and the worktrees and plan clone go in it')
(repo / 'runner.toml').write_text('[plan]\nrepo = "https://example.invalid/proj-plan.git"\n', encoding='utf-8')
c = Config(repo)
eq(c.home, Path('~/runs/proj').expanduser(), 'the default home is ~/runs/<repo>')
eq(c.slots_dir, c.home, 'the worktrees live in it')
eq(c.plan_dir, c.home / 'plan', 'and so does the plan clone')

print('[run] home and AGENT_RUNNER_HOME override it')
home = (tmp / 'mine/{repo}').as_posix()
(repo / 'runner.toml').write_text(f'[run]\nhome = "{home}"\n', encoding='utf-8')
eq(Config(repo).home, tmp / 'mine/proj', '[run] home, with {repo} filled in')
os.environ['AGENT_RUNNER_HOME'] = str(tmp / 'machine/{repo}')
eq(Config(repo).home, tmp / 'machine/proj', 'AGENT_RUNNER_HOME wins: one machine, without editing the shared config')

print('worktrees a run before 0.13 left beside the checkout keep being used until they are moved')
(tmp / 'proj-slots/s1').mkdir(parents=True)
eq(Config(repo).slots_dir, tmp / 'proj-slots', 'the old <repo>-slots/ is used while home has none')
(tmp / 'machine/proj/s1').mkdir(parents=True)
eq(Config(repo).slots_dir, tmp / 'machine/proj', 'once home has them, home it is')

print('`agent-runner home` answers scripts from the same settings')
from _check import run  # noqa: E402
eq(run(repo, 'home').stdout.strip(), str(tmp / 'machine/proj'), '`home` prints it')
eq(run(repo, 'home', 'slots').stdout.strip(), str(tmp / 'machine/proj'), '`home slots` prints the worktrees')
eq(run(repo, 'home', 'bogus').returncode, 2, 'anything else is a usage error')

os.environ['AGENT_RUNNER_HOME'] = env
raise SystemExit(1 if FAILED else print('\nall checks passed'))
