"""`runner.toml`: everything the runner needs to know about the repository it works on.

The runner is a tool you point at a repo, not a library the repo vendors, so it keeps two roots apart:

* **the repo** — the git checkout whose task list is being worked through. Found from the current
  directory (or `AGENT_RUNNER_REPO`), and inside a worktree, from the worktree: `plan` and `done` run in
  the agent's own worktree and must edit *its* files, while `run` merges into the main checkout.
* **the runner** — this package, wherever it is installed. The Stop hook and the agents' `done` call it
  by absolute path, so the repo needs nothing installed.

Every key has a default, and a repo with no `runner.toml` at all works: plan in `plan/`, no test gate,
three slots, push to origin.
"""
from __future__ import annotations

import os
import subprocess
import tomllib
from functools import cache
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNNER = HERE.parent / 'run'   # the CLI entry, called by absolute path from hooks and agent sessions

DEFAULTS: dict = {
    'plan': {
        'dir': 'plan',          # TODO.md and DONE.md live here; plan/<ID>.md is a task's long form
        'journal': '',          # optional: a directory of per-task journal folders, pasted into briefs
    },
    'run': {
        'test': '',             # the gate: `done` and every merge run it; empty means no gate
        'slots': 3,
        'mode': 'd',            # d = never two running tasks on the same file; p = strict plan order
        'agent': 'claude',      # the CLI that runs a session
        'model': 'opus',
        'lean': True,           # agents get Bash/Read/Edit/Write only, no MCP, no user settings
        'idle': 90,             # seconds a finished session sits at its prompt before it is ended
        'stall': 1200,          # seconds of quiet at a prompt that count as stalled
        'pause': 60,            # seconds between one session ending and the next starting in that slot
        'weekly_max': 90,       # % of the account's 7-day usage past which no new task starts
        'notes': '.runner',     # logs and the ledger; keep it git-ignored
        'links': [],            # git-ignored paths symlinked into every worktree (data, big files)
        'slot_env': ['AGENT_SLOT={n}'],  # extra environment per slot; {n} is the slot number
        'on_exit': '',          # a command run in the slot's worktree when its session ends
        'rules': '',            # the repo's rules file the prompt points at (AGENTS.md, CLAUDE.md, …)
        'prompt': '',           # path to a prompt template replacing the built-in one (see README)
        'prompt_extra': '',     # a paragraph added to the built-in prompt (what each slot owns, …)
        'shared_files': [],     # files nearly every task names; mode d ignores them
        'joinable': ['plan/TODO.md', 'plan/DONE.md'],  # record-per-line files a conflict may be joined in
        'fix_merges': True,     # give a conflict the join cannot do to a one-shot agent session
        'fix_model': 'opus',
        'fix_timeout': 1800,
    },
    'git': {
        'push': 'origin',       # where finished work goes; false turns every push off
        'push_merge': True,     # push the shared branch after each merge that passed the gate
    },
}


def toplevel(cwd: Path | str | None = None) -> Path:
    """The git checkout around `cwd` (a worktree is its own checkout here)."""
    env = os.environ.get('AGENT_RUNNER_REPO')
    if env and cwd is None:
        return Path(env).resolve()
    r = subprocess.run(['git', 'rev-parse', '--show-toplevel'], cwd=str(cwd or Path.cwd()),
                       capture_output=True, text=True)
    if r.returncode:
        raise SystemExit('agent-runner: not inside a git repository (or set AGENT_RUNNER_REPO)')
    return Path(r.stdout.strip()).resolve()


def main_checkout(cwd: Path | str | None = None) -> Path:
    """The main checkout of the repo around `cwd`, even when `cwd` is one of its worktrees."""
    top = toplevel(cwd)
    r = subprocess.run(['git', 'rev-parse', '--path-format=absolute', '--git-common-dir'], cwd=str(top),
                       capture_output=True, text=True)
    common = Path(r.stdout.strip()) if not r.returncode else top / '.git'
    return common.parent.resolve() if common.name == '.git' else top


class Config:
    def __init__(self, root: Path):
        self.root = root
        raw: dict = {}
        f = root / 'runner.toml'
        if not f.exists():  # a git-ignored runner.toml is only in the main checkout, not the worktrees
            f = main_checkout(root) / 'runner.toml'
        if f.exists():
            with open(f, 'rb') as fh:
                raw = tomllib.load(fh)
        self.raw = {k: {**v, **raw.get(k, {})} for k, v in DEFAULTS.items()}
        self.run = self.raw['run']

    @property
    def plan_dir(self) -> Path:
        return self.root / self.raw['plan']['dir']

    @property
    def todo(self) -> Path:
        return self.plan_dir / 'TODO.md'

    @property
    def done(self) -> Path:
        return self.plan_dir / 'DONE.md'

    @property
    def journal(self) -> Path | None:
        j = self.raw['plan']['journal']
        return self.root / j if j else None

    def notes(self, *parts: str) -> Path:
        """A path under the notes directory of the *main* checkout, so every slot logs to one place."""
        p = main_checkout(self.root) / self.run['notes'] / Path(*parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def push_remote(self) -> str | None:
        v = self.raw['git']['push']
        return None if v is False else (str(v) if isinstance(v, str) else 'origin')

    @property
    def push_merge(self) -> bool:
        return bool(self.raw['git']['push_merge']) and bool(self.push_remote)


@cache
def _cfg(root: Path) -> Config:
    return Config(root)


def cfg(cwd: Path | str | None = None) -> Config:
    return _cfg(toplevel(cwd))
