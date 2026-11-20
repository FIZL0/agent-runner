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

Then `runner.local.toml` (the checkout's, else the main checkout's), if there is one, is laid over it key by
key, table by table: one person's settings on one machine (`weekly_max`, `slots`, `model`) without editing the
file everyone shares. It may wrap its tables in `[agent-runner]` too. `run` creates it in the main checkout
(all comments, so it changes nothing) when it is missing and never rewrites it, and keeps it out of git by
adding it to the clone's `.git/info/exclude`.

`AGENT_RUNNER_BACKEND=claude|pi` runs on that backend whatever the file says (its `agent`, `model` and
`fix_model` then fall back to the backend's defaults), e.g. to try a task on Pi with the repo's own config.
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
        'dir': 'plan',          # TODO.md and DONE.md live here; plan/tasks/<ID>.md is a task's long form. Outside
                                # the repo (~/…, /…) every checkout and worktree shares that one copy
        'repo': '',             # a git URL or path: the plan in its own repo, cloned to `dir` (default
                                # [run] home/plan) and pulled/pushed on every edit (plansync)
        'journal': '',          # optional: a directory of per-task journal folders, pasted into briefs
        'journal_layout': 'dated',  # 'dated': <journal>/<date>-<id>-<slug>/; 'id': <journal>/<ID>/notes.md, a
                                # repeat attempt in <journal>/<ID>/<date>-<slug>/notes.md
        'brief_extra': '',      # a command whose output ends the brief; {id} is the task id
        'outline': '',          # a command printing one file's outline (its symbols, sections); {file} is
                                # the path. The brief shows it under each file the task line names
        'kinds': {},            # id prefix -> the kind of work it marks (`plan kinds`); empty = plan.KINDS
        'need_files': False,    # `plan add` refuses a line with no files: or test: field
        'lookup': [],           # more markdown files `plan <name>` searches for a heading (after TODO, REFERENCE,
                                # HUMAN, DONE and [run] rules), e.g. ["PLAN.md", "plan/*.md"]; globs allowed
        'context_kb': 12,       # budget for what every session loads (rules, CLAUDE.md, AGENTS.md, @-imports):
                                # `agent-runner context` reports it, `run` warns past it; 0 = no warning
    },
    'run': {
        'test': '',             # the gate: `done` and every merge run it; empty means no gate
        'test_since': '',       # a merge's gate on what changed since {base} (a commit that passed the gate);
                                # '' = the whole `test` every time
        'full_every_hours': 24, # with test_since: the whole `test` again once none has passed for this long; 0 = never
        'slots': 3,
        'mux': '',              # terminal per slot: tmux, wt, console, none; '' = tmux (Windows: wt, else console)
        'agent': 'claude',      # the CLI that runs a session: claude, or copilot (GitHub Copilot CLI)
        'include_task_id_in_commit': True,
        'comment_policy': 'normal',
        'backend': '',          # '' = Claude Code (or pi when `agent` is a pi executable); pi = other providers
        'model': 'opus',
        'lean': True,           # agents get Bash/Read/Edit/Write/Artifact only, no MCP, no user settings
        'remote': 'auto',       # control sessions on Remote Control, and a control server there to start more:
                                # the run, watched and steered from claude.ai/code and the Claude apps; auto = on
                                # when it can work (Claude Code on a claude.ai login), true/false force it
        'remote_slots': False,  # the slots on Remote Control too, each "<repo> · s2 · B646"
        'control': True,        # a run opens control session c1 beside it (`agent-runner control`); false: none
        'auto_upgrade': False,  # upgrade agent-runner by itself when a newer release is out, once no merge runs,
                                # and restart the run on it (as `u` does, without the key)
        'install_skill': True,  # keep the `agent-runner guide` skill in ~/.claude/skills, for sessions a person starts
        'rules_pointer': True,  # a run adds one line to the rules file (`rules`, AGENTS.md, CLAUDE.md) pointing at it
        'idle': 30,             # seconds a finished session sits at its prompt before it is ended
        'stall': 1200,          # seconds of quiet at a prompt that count as stalled
        'pause': 60,            # seconds between one session ending and the next starting in that slot
        'weekly_max': 90,       # % of the account's 7-day usage past which no new task starts
        'session_max': 90,      # % of the account's 5-hour session usage past which no new task starts
        'notes': '.runner',     # logs and the ledger; keep it git-ignored
        'links': [],            # git-ignored paths symlinked into every worktree (data, big files)
        'copies': [],           # git-ignored files copied into a new worktree once (a local config)
        'slot_env': ['AGENT_SLOT={n}'],  # extra environment per slot; {n} is the slot, {slots} how many
        'pass_env': [],         # names of the runner's own environment variables handed on to every slot
        'on_exit': '',          # a command run in the slot's worktree when its session ends
        'rules': '',            # the repo's rules file the prompt points at (AGENTS.md, CLAUDE.md, …)
        'prompt': '',           # path to a prompt template replacing the built-in one (see docs/REFERENCE.md)
        'prompt_extra': '',     # a paragraph added to the built-in prompt (what each slot owns, …)
        'shared_files': [],     # files nearly every task names; not counted as an overlap
        'joinable': [],  # record-per-line files a conflict may be joined in (the task list merges by task anyway)
        'join': {},             # glob -> a command that joins a conflict in that file (see runner.custom_join)
        'suspect': '',          # a regex: a block line a merge adds that matches it is flagged in the ledger
        'command': '',          # what the prompt tells sessions to call (default: this runner); e.g. ./kit
        'untested': ['*.md', 'LICENSE*', 'COPYING*'],   # globs of files the gate cannot see (`!glob` takes one back): a merge that
                                # differs from what was tested only in these is not tested again
        'failures': '',         # a regex whose group 1 names a failing test in the gate's output
        'retest': '',           # the gate for just some tests; {names} is those `failures` found. A failure
                                # that passes alone was load; one the branch's base fails too is merged anyway
        'flaky': '',            # a regex whose group 1 names tests (comma/space separated) a passing gate says
                                # passed only on a rerun; each, like a `retest` pass, gets a critical follow-up
        'flaky_kind': 'T',      # the id prefix those follow-ups get (see [plan] kinds)
        'ci_watch': 'auto',     # GitHub Actions workflow files (pages.yml) whose newest finished run on the
                                # shared branch is read while a run is up: a red one files one critical task.
                                # "auto": every workflow that runs on a push to it (push runs only); false: off
        'ci_kind': 'B',         # the id prefix that task gets
        'batch': True,          # finished branches waiting for the merge go in together under one gate run
        'merge_ahead': True,    # tasks finishing during a batch's gate are merged on it and tested beside it
        'batch_max': 16,        # at most this many tasks in one batch (the rest take the next one); 0 = no cap
        'max_unmerged': 32,     # past this many finished tasks waiting for the merge, each half batch more holds one
                                # slot free (6 slots, batch_max 16: 33 waiting runs 5, 73 runs none); 0 = off
        'before_start': '',     # a command that must succeed before a session starts; the slot waits on it
        'not_attempt': '',      # a regex on a finished branch's first commit subject ({id}): such a session
                                # (a spec phase, say) is not the run's one attempt at the task
        'fix_merges': True,     # give a conflict the join cannot do to a one-shot agent session
        'fix_model': 'opus',
        'fix_timeout': 1800,
        'fix_ahead_max': 2,     # conflicts fixed before the merge lock at once, each in a fix worktree (fix1…)
                                # while other merges go on; 0 = fix them under the lock, in the merge worktree
        'build': '',            # a quick build, not the gate: a fix session runs it before it commits, so a
                                # clash git merged without a conflict (one name defined twice) is caught there
        'repair_merges': True,  # a merge (or a batch) that fails the gate gets one session to repair it first
        'home': '~/runs/{repo}',  # the runner's own files for this project, outside the repos folder: the
                                # worktrees (s1, s2, …, merge) and a `[plan] repo` clone (plan/). {repo} is
                                # the main checkout's folder name; AGENT_RUNNER_HOME overrides it on one machine
        'slot_max_gb': 50,      # a worktree (slot or merge) bigger than this loses its stalest build output
                                # before its next task (runner.trim); 0 = never
        'min_free_gb': 10,      # less free disk than this: free worktrees are cleaned, and no new task starts
                                # until there is room again; 0 = never
        'proc_max_gb': 'auto',  # a process of the run's (a session's tool, a gate's test) resident past this
                                # is ended, so a runaway eats one test and not the machine; 'auto': a quarter
                                # of the memory; 0 = never
        'min_free_mem_gb': 4,   # less memory available than this: the run's biggest process is ended; 0 = never
        'slot_clean': '',       # a project's own clean, run instead of the trim and of the low-disk
                                # `git clean -ffdXq` (every git-ignored file; `links` come back on their own)
        'timeout': 3600,        # seconds the gate, a retest or a hook command (join, before_start, on_exit) may
                                # run before it is stopped and counts as failed
    },
    'git': {
        'master_branch': '',    # explicit local branch for tasks and tested merges; empty discovers it as before
        'push': 'origin',       # where finished work goes; false turns every push off
        'push_merge': True,     # push the shared branch after each merge that passed the gate
        'land_edited': 'wait',  # a tested merge blocked by uncommitted edits in the main checkout: "wait" for them,
                                # or "wip": after LAND_WAIT_WIP move them to a wip/main-checkout-<time> branch and land
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


LOCAL = 'runner.local.toml'


def local_file(root: Path) -> Path | None:
    """This machine's `runner.local.toml`: the checkout's, else the main checkout's (a git-ignored file is
    only there), or None."""
    return next((f for f in (root / LOCAL, main_checkout(root) / LOCAL) if f.is_file()), None)


def keep_local_ignored(root: Path) -> None:
    """Add `runner.local.toml` to the clone's `.git/info/exclude` unless git ignores it already: it is one
    person's settings, and a `git add` of the folder must not share it."""
    if not subprocess.run(['git', 'check-ignore', '-q', LOCAL], cwd=str(root), capture_output=True).returncode:
        return
    r = subprocess.run(['git', 'rev-parse', '--git-common-dir'], cwd=str(root), capture_output=True, text=True)
    if r.returncode:
        return
    ex = (root / r.stdout.strip()).resolve() / 'info' / 'exclude'
    try:
        ex.parent.mkdir(parents=True, exist_ok=True)
        old = ex.read_text(encoding='utf-8') if ex.exists() else ''
        ex.write_text(old + ('' if not old or old.endswith('\n') else '\n') + f'/{LOCAL}\n', encoding='utf-8')
    except OSError:
        pass


LOCAL_TEMPLATE = """\
# This machine's agent-runner settings, laid over runner.toml key by key. Git ignores this file (the runner
# added it to .git/info/exclude) and the runner never rewrites it: what you set here stays yours.
# Uncomment and edit; any key runner.toml takes works here, in the same tables.

# [run]
# weekly_max = 90        # % of the account's 7-day usage past which no new task starts
# session_max = 90       # % of the account's 5-hour session usage past which no new task starts
# slots = 3              # parallel sessions on this machine
# model = "opus"
# min_free_gb = 10       # below this free disk space no new task starts
"""


def ensure_local(root: Path) -> Path:
    """Create `root`/runner.local.toml from LOCAL_TEMPLATE if it is missing (never rewrite one), and keep it
    out of git. The path."""
    f = root / LOCAL
    if not f.exists():
        try:
            f.write_text(LOCAL_TEMPLATE, encoding='utf-8')
        except OSError:
            return f
    keep_local_ignored(root)
    return f


# A key renamed in a release: (table, old) -> new. A config with the old name still works; the run log says
# to rename it. Add an entry with every rename, so an upgrade never needs anyone to edit a config first.
RENAMED: dict[tuple[str, str], str] = {}

# A key a release removed: (table, key) -> what to do instead. Ignored, and the run log says so.
REMOVED: dict[tuple[str, str], str] = {
    ('run', 'mode'): 'a run never starts two tasks on the same files (0.32.0); delete it',
    ('run', 'fix_ahead'): '`fix_ahead_max = 0` is what `fix_ahead = false` was (0.32.0)',
    ('run', 'precommit'): 'chain the check into `[run] test` (0.32.0)',
    ('run', 'ci_rerun'): "a red CI run's failed jobs are always run once more (0.32.0); delete it",
    ('run', 'batch_wait'): 'removed in 0.32.0; delete it',
    ('run', 'batch_min'): 'removed in 0.32.0; delete it',
    ('plan', 'brief'): 'use `brief_extra` and `outline` (0.32.0)',
}


def migrate(raw: dict, where: str) -> list[str]:
    """Apply RENAMED to `raw` in place; what the run log should say about old, removed or unknown keys in the
    tables the runner reads (another table in a wrapper's file is its own business)."""
    import difflib
    said = []
    for (t, old), new in RENAMED.items():
        if isinstance(tab := raw.get(t), dict) and old in tab:
            v = tab.pop(old)
            tab.setdefault(new, v)
            said.append(f'{where}: [{t}] {old} is now {new}; rename it')
    for t, keys in DEFAULTS.items():
        for k in raw.get(t, {}) if isinstance(raw.get(t), dict) else ():
            if k in keys:
                continue
            if hint := REMOVED.get((t, k)):
                said.append(f'{where}: [{t}] {k} is ignored: {hint}')
            else:
                near = difflib.get_close_matches(k, keys, 1)
                said.append(f'{where}: [{t}] {k} is not a setting, ignored' + (f'; did you mean {near[0]}?' if near else ''))
    return said


def _load(f: Path) -> dict:
    with open(f, 'rb') as fh:
        raw = tomllib.load(fh)
    return raw['agent-runner'] if isinstance(raw.get('agent-runner'), dict) else raw


class Config:
    def __init__(self, root: Path):
        self.root = root
        raw: dict = {}
        self.warnings: list[str] = []  # old, removed or unknown keys; the run logs them at its start
        self.file = config_file(root)
        if self.file:
            raw = _load(self.file)
            self.warnings += migrate(raw, self.file.name)
        self.local = local_file(root)
        if self.local:
            try:
                mine = _load(self.local)
            except tomllib.TOMLDecodeError as e:
                raise SystemExit(f'agent-runner: {self.local}: {e}')
            self.warnings += migrate(mine, self.local.name)
            raw = {**raw, **{k: ({**raw.get(k, {}), **v} if isinstance(v, dict) and isinstance(raw.get(k), dict)
                                 else v) for k, v in mine.items()}}
            keep_local_ignored(self.local.parent)
        supplied = dict(raw.get('run', {}))
        infer = lambda run: run.get('backend') or (
            'pi' if Path(run.get('agent', 'claude').replace('\\', '/')).stem.lower() == 'pi' else 'claude')
        if (env := os.environ.get('AGENT_RUNNER_BACKEND')) and env != infer(supplied):
            # one run on another agent with the repo's config: its agent and models are the other backend's
            supplied = {k: v for k, v in supplied.items() if k not in ('agent', 'model', 'fix_model')}
            supplied['backend'] = env
        raw = {**raw, 'run': supplied}
        self.raw = {k: {**v, **raw.get(k, {})} for k, v in DEFAULTS.items()}
        if self.raw['plan']['repo'] and 'dir' not in raw.get('plan', {}):
            self.raw['plan']['dir'] = str(self.home / 'plan')
        self.run = self.raw['run']
        if not isinstance(self.run['include_task_id_in_commit'], bool):
            raise SystemExit('agent-runner: [run] include_task_id_in_commit must be a boolean')
        if not (isinstance(self.run['remote'], bool) or self.run['remote'] == 'auto'):
            raise SystemExit(f"agent-runner: [run] remote must be 'auto', true or false, not {self.run['remote']!r}")
        if self.run['comment_policy'] not in ('normal', 'minimal'):
            raise SystemExit("agent-runner: [run] comment_policy must be 'normal' or 'minimal'")
        backend = infer(self.run)
        if backend not in ('claude', 'pi'):
            raise SystemExit(f'agent-runner: unknown [run] backend {backend!r}; choose claude or pi')
        self.run['backend'] = backend
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
        return self.root / Path(self.raw['plan']['dir']).expanduser()

    @property
    def plan_repo(self) -> str:
        """`[plan] repo`; a relative path (`../plan.git`) is the main checkout's, wherever git runs."""
        r = self.raw['plan']['repo']
        return str((main_checkout(self.root) / r).resolve()) if r.startswith(('./', '../')) else r

    @property
    def home(self) -> Path:
        """`[run] home` (or AGENT_RUNNER_HOME): where this project's worktrees and plan clone live."""
        main = main_checkout(self.root)
        t = os.environ.get('AGENT_RUNNER_HOME') or self.raw['run']['home']
        return main / Path(t.replace('{repo}', main.name)).expanduser()

    @property
    def slots_dir(self) -> Path:
        """The worktrees: `home`."""
        return self.home

    @property
    def plan_external(self) -> bool:
        """The plan is not in the code repo: one copy for every worktree, never committed with the code."""
        return not self.plan_dir.is_relative_to(self.root)

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
    def master_branch(self) -> str | None:
        value = self.raw['git']['master_branch']
        if not isinstance(value, str):
            raise SystemExit('[git] master_branch must be a branch name string (or empty for automatic discovery)')
        if value != value.strip():
            raise SystemExit('[git] master_branch must not have leading or trailing whitespace')
        return value or None

    @property
    def push_merge(self) -> bool:
        return bool(self.raw['git']['push_merge']) and bool(self.push_remote)

    @property
    def land_edited(self) -> str:
        v = str(self.raw['git'].get('land_edited', 'wait')).lower()
        return v if v in ('wait', 'wip') else 'wait'


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
