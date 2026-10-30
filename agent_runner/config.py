"""`runner.toml`: everything the runner needs to know about the repository it works on.

The runner is a tool you point at a repo, not a library the repo vendors, so it keeps two roots apart:

* **the repo** — the git checkout whose task list is being worked through. Found from the current
  directory (or `AGENT_RUNNER_REPO`), and inside a worktree, from the worktree: `plan` and `done` run in
  the agent's own worktree and must edit *its* files, while `run` merges into the main checkout.
* **the runner** — this package, wherever it is installed. The Stop hook and the agents' `done` call it
  by absolute path, so the repo needs nothing installed.

Every key has a default, and a repo with no `runner.toml` at all works: plan in `plan/`, no test gate,
three slots, push to origin.

Where the settings come from, first match wins:

1. `AGENT_RUNNER_CONFIG=<file>`: a TOML file a wrapping project names (its own `kit.toml`, say). If the
   file has an `[agent-runner]` table, that table is the config (`[agent-runner.run]`, …), so the
   project's own `[git]` or `[run]` never collide with ours. Otherwise its top level is. A relative path
   is relative to the main checkout.
2. `runner.toml` at the root of the checkout, else the main checkout's (a git-ignored one is only there).
"""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import tomllib
from functools import cache
from pathlib import Path

from agent_runner import plat

HERE = Path(__file__).resolve().parent
CLONE_ENTRY = HERE.parent / 'run'  # `./run` in a clone; an installed package has no such file


def runner_cmd() -> list[str]:
    """How the runner calls itself from a hook or a detached timer: this interpreter, and either the
    clone's `run` or `-m agent_runner` (installed, `sys.executable` is the env that has the package)."""
    if CLONE_ENTRY.exists():
        return [sys.executable, str(CLONE_ENTRY)]
    return [sys.executable, '-m', 'agent_runner']


def _typed() -> str:
    """What a session types: the clone's `run` (it has a shebang), else the installed `agent-runner`.
    Windows has no shebangs, so there it is the interpreter and the script (or the installed .exe)."""
    if plat.WINDOWS:
        exe = shutil.which('agent-runner')
        return plat.command_text([exe] if exe else runner_cmd())
    if CLONE_ENTRY.exists():
        return str(CLONE_ENTRY)
    return shutil.which('agent-runner') or shlex.join(runner_cmd())


RUNNER = _typed()  # for a prompt or a log line

DEFAULTS: dict = {
    'plan': {
        'dir': 'plan',          # TODO.md and DONE.md live here; plan/<ID>.md is a task's long form
        'journal': '',          # optional: a directory of per-task journal folders, pasted into briefs
        'brief_extra': '',      # a command whose output ends the brief; {id} is the task id
        'brief': '',            # a command whose output *is* the brief, replacing the built-in one; {id}
        'kinds': {},            # id prefix -> the kind of work it marks (`plan kinds`); empty = plan.KINDS
    },
    'run': {
        'test': '',             # the gate: `done` and every merge run it; empty means no gate
        'slots': 3,
        'mux': '',              # terminal per slot: tmux, wt, console, none; '' = tmux (Windows: wt, else console)
        'mode': 'd',            # d = never two running tasks on the same file; p = strict plan order
        'agent': 'claude',      # the CLI that runs a session
        'backend': '',         # claude or pi; empty infers pi from the executable name, else claude
        'model': 'opus',
        'lean': True,           # agents get Bash/Read/Edit/Write only, no MCP, no user settings
        'idle': 90,             # seconds a finished session sits at its prompt before it is ended
        'stall': 1200,          # seconds of quiet at a prompt that count as stalled
        'pause': 60,            # seconds between one session ending and the next starting in that slot
        'weekly_max': 90,       # % of the account's 7-day usage past which no new task starts
        'notes': '.runner',     # logs and the ledger; keep it git-ignored
        'links': [],            # git-ignored paths symlinked into every worktree (data, big files)
        'slot_env': ['AGENT_SLOT={n}'],  # extra environment per slot; {n} is the slot, {slots} how many
        'pass_env': [],         # names of the runner's own environment variables handed on to every slot
        'on_exit': '',          # a command run in the slot's worktree when its session ends
        'rules': '',            # the repo's rules file the prompt points at (AGENTS.md, CLAUDE.md, …)
        'prompt': '',           # path to a prompt template replacing the built-in one (see README)
        'prompt_extra': '',     # a paragraph added to the built-in prompt (what each slot owns, …)
        'shared_files': [],     # files nearly every task names; mode d ignores them
        'joinable': ['plan/TODO.md', 'plan/DONE.md'],  # record-per-line files a conflict may be joined in
        'join': {},             # glob -> a command that joins a conflict in that file (see runner.custom_join)
        'suspect': '',          # a regex: a block line a merge adds that matches it is flagged in the ledger
        'precommit': '',        # a check `done` runs after the gate, before it ticks (--skip-check skips it)
        'command': '',          # what the prompt tells sessions to call (default: this runner); e.g. ./kit
        'untested': ['*.md'],   # globs of files the gate cannot see (`!glob` takes one back): a merge that
                                # differs from what was tested only in these is not tested again
        'failures': '',         # a regex whose group 1 names a failing test in the gate's output
        'retest': '',           # the gate for just some tests; {names} is those `failures` found. A failure
                                # that passes alone was load; one the branch's base fails too is merged anyway
        'flaky': '',            # a regex whose group 1 names tests (comma/space separated) a passing gate says
                                # passed only on a rerun; each, like a `retest` pass, gets a critical follow-up
        'flaky_kind': 'T',      # the id prefix those follow-ups get (see [plan] kinds)
        'batch': True,          # finished branches waiting for the merge go in together under one gate run
        'before_start': '',     # a command that must succeed before a session starts; the slot waits on it
        'not_attempt': '',      # a regex on a finished branch's first commit subject ({id}): such a session
                                # (a spec phase, say) is not the run's one attempt at the task
        'fix_merges': True,     # give a conflict the join cannot do to a one-shot agent session
        'fix_model': 'opus',
        'fix_timeout': 1800,
        'build': '',            # a quick build, not the gate: a fix session runs it before it commits, so a
                                # clash git merged without a conflict (one name defined twice) is caught there
        'repair_merges': True,  # a merge (or a batch) that fails the gate gets one session to repair it first
        'timeout': 3600,        # seconds the gate, a retest or a hook command (join, before_start, on_exit) may
                                # run before it is stopped and counts as failed
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


def config_file(root: Path) -> Path | None:
    """The file the settings come from (see the module docstring), or None for the defaults."""
    if env := os.environ.get('AGENT_RUNNER_CONFIG'):
        f = Path(env)
        f = f if f.is_absolute() else main_checkout(root) / f
        if not f.exists():
            raise SystemExit(f'agent-runner: AGENT_RUNNER_CONFIG names {f}, which does not exist')
        return f.resolve()
    for f in (root / 'runner.toml', main_checkout(root) / 'runner.toml'):
        if f.exists():  # a git-ignored runner.toml is only in the main checkout, not the worktrees
            return f
    return None


class Config:
    def __init__(self, root: Path):
        self.root = root
        raw: dict = {}
        self.file = config_file(root)
        if self.file:
            with open(self.file, 'rb') as fh:
                raw = tomllib.load(fh)
            if isinstance(raw.get('agent-runner'), dict):
                raw = raw['agent-runner']
        self.raw = {k: {**v, **raw.get(k, {})} for k, v in DEFAULTS.items()}
        self.run = self.raw['run']
        backend = self.run['backend'] or (
            'pi' if Path(self.run['agent'].replace('\\', '/')).stem.lower() == 'pi' else 'claude')
        if backend not in ('claude', 'pi'):
            raise SystemExit(f'agent-runner: unknown [run] backend {backend!r}; choose claude or pi')
        self.run['backend'] = backend
        supplied = raw.get('run', {})
        if 'agent' not in supplied:
            self.run['agent'] = backend
        if backend == 'pi':
            if 'model' not in supplied:
                self.run['model'] = ''
            if 'fix_model' not in supplied:
                self.run['fix_model'] = self.run['model']

    @property
    def command(self) -> str:
        """What a session types to reach the plan tool and `done`: `[run] command`, else this runner."""
        return self.run['command'] or RUNNER

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


def finished_mark(slot: str | int | None = None) -> Path | None:
    """The file a slot's successful `done` leaves (`AGENT_RUNNER_SLOT`); the slot clears it when it starts a task,
    and the stop waiter stops protecting the session's leftover background commands once it exists."""
    slot = slot if slot is not None else os.environ.get('AGENT_RUNNER_SLOT')
    return cfg().notes(f'slot{slot}.finished') if slot not in (None, '') else None
