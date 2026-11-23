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

import json
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
WEB_VIEWS = ('app', 'terminal')  # [ui] web: the run app, or the terminal-style page


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
    if Path(sys.argv[0]).name == 'agent-runner' and shutil.which('agent-runner'):
        return 'agent-runner'  # typed from PATH (an editable install of a clone too): echo that, not the clone's path
    if CLONE_ENTRY.exists():
        return str(CLONE_ENTRY)
    return shutil.which('agent-runner') or shlex.join(runner_cmd())


RUNNER = _typed()  # for a prompt or a log line


def shown_cmd() -> str:
    """C15: the command as a line a person reads names it (start hints, run log tips, control hints). On Windows
    RUNNER is the full C:/Users/.../agent-runner.EXE path, so slot shells always find it; when `agent-runner` is
    on PATH a person types just that. Prompts and hooks keep RUNNER."""
    if plat.WINDOWS and shutil.which('agent-runner'):
        return 'agent-runner'
    return RUNNER

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
        'glossary': 'GLOSSARY.md',  # the project's glossary (`agent-runner glossary`), seeded by the first control
                                # session and named in every brief; false = off: no file written, briefs skip it
        'release_alone': False,  # a release (kind V) waits for every task ahead of it (`plan add V` writes
                                # `after: all`) and runs alone; false = it starts like any other task (F100)
    },
    'run': {
        'test': '',             # the gate: `done` and every merge run it; empty means no gate
        'test_since': '',       # a merge's gate on what changed since {base} (a commit that passed the gate);
                                # '' = the whole `test` every time
        'full_every_hours': 24, # with test_since: the whole `test` again once none has passed for this long; 0 = never
        'slots': 3,             # tasks (agent sessions) at once; `agent-runner slots N` changes a running run
        'agent': 'claude',      # the CLI that runs a session: claude, or a pi executable (an executable named
                                # pi runs on the Pi backend; AGENT_RUNNER_BACKEND=claude|pi overrides it)
        'include_task_id_in_commit': True,  # agents start each commit subject with the task id
        'comment_policy': 'normal',  # 'minimal': agents add code comments only for non-obvious intent
        'model': 'opus',        # the model the task sessions run on
        'lean': True,           # agents get Bash/Read/Edit/Write/Artifact only, no MCP, no user settings
        'remote': 'auto',       # control sessions on Remote Control, and a control server there to start more:
                                # the run, watched and steered from claude.ai/code and the Claude apps; auto = on
                                # when it can work (Claude Code on a claude.ai login), true/false force it
        'remote_slots': False,  # the slots on Remote Control too, each "<task title> · <repo> s2 · B646"
        'sessions': 'one',      # what the Claude apps list for a project. one = c1 is the project's chat;
                                # a slot goes on Remote Control only when opened from the run page, and c1
                                # keeps a claude.ai copy of the run page. each = every slot its own entry
                                # (with remote_slots), as before
        'web': True,            # the run page on the web, served by the run from this machine on web_port for the
                                # LAN/Tailscale (its address, with the token it needs, in `status` and the run log)
        'web_port': 8770,       # where the run page is served; its terminal tab's ttyd processes take the next ports
        'silent': False,        # phone pushes from the run's Remote Control sessions: true = none after each
                                # one's start push (that one cannot be stopped), false = Claude Code's usual
        'control': True,        # a run opens control session c1 beside it (`agent-runner control`); false: none
        'control_idle': '3h',   # the run closes control sessions 2, 3, … (never c1) quiet this long with Claude
                                # last and nothing running in them; transcripts kept. false: none closed idle
        'control_idle_quick': '5m',  # a session opened for one ask (a feed reply) that queued a task, the
                                # person's only message that ask and no open question: closed this soon (false: control_idle)
        'control_idle_talked': '12h',  # a session the person sent a second message in: kept this long
                                # (false: control_idle)
        'control_ask': '2h',    # quiet this long on an open question: filed under Needs you as a DECIDE item,
                                # then closed. false: a session waiting on its question stays open
        'control_open': ['?', 'want me to', 'should i', 'shall i', 'would you like', 'do you want'],
                                # what makes Claude's last message an open question or offer (case ignored;
                                # one of punctuation only must end it, any other may stand anywhere in its last paragraph)
        'auto_upgrade': True,   # upgrade agent-runner by itself when a newer release is out, once no merge runs,
                                # and restart the run on it (as `u` does, without the key); false: only `u` does
        'install_skill': True,  # keep the `agent-runner guide` skill in ~/.claude/skills, for sessions a person starts
        'rules_pointer': True,  # a run adds one line to the rules file (`rules`, AGENTS.md, CLAUDE.md) pointing at it
        'wizards': True,        # an agent blocking with BLOCKED: (a login, cert, secret) writes a bash wizard
                                # to <notes>/wizards/<ID>.sh; Needs you shows `agent-runner wizard <ID>` to run it
        'questionnaires': True, # a DECIDE with options is asked as a pick sheet (<notes>/sheets/<ID>.json, a
                                # page with `agent-runner sheet <ID>`); Needs you shows one line and its link
        'grill': 'ask',         # control sessions ask rounds of numbered questions before queueing:
                                # ask = when the person says grill me / poke holes; big = also big vague asks; off
        'voice': '',            # the person's wording file (`agent-runner voice`), read by control sessions
                                # the runner feed and task agents; '' = ~/.config/agent-runner/voice.md; a
                                # .runner/voice.md with lines overrides it for this project
        'voice_learn': 'ask',   # ask = a session that had to say something again offers one wording line to add;
                                # off = lines are added only when the person says so
        'review': True,         # before done, a fresh subagent reads the diff against the task's brief (spec
                                # only: missing, unasked, wrong); the commit ends 'review: …'; false: no review
        'review_min_lines': 50, # a diff smaller than this (changed lines) skips the review, unless the task has a
                                # long form (plan/tasks/<ID>.md)
        'idle': 30,             # seconds a finished session sits at its prompt before it is ended
        'stall': 1200,          # seconds of quiet at a prompt that count as stalled
        'context_warn': 150,    # k tokens: a slot session whose context peaks past this says so, and what filled
                                # it, in its exit line and `since` (soft only: nothing is stopped); 0 = off
        'pause': 60,            # seconds between one session ending and the next starting in that slot
        'weekly_max': 90,       # % of the account's 7-day usage past which no new task starts
        'session_max': 90,      # % of the account's 5-hour session usage past which no new task starts
        'notes': '.runner',     # logs and the ledger; keep it git-ignored
        'links': [],            # git-ignored paths symlinked into every worktree (data, big files)
        'copies': [],           # git-ignored files copied into a new worktree once (a local config)
        'slot_env': [],         # extra environment per slot, beside AGENT_SLOT=<n> every slot gets; {n} is the
                                # slot, {slots} how many
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
        'docs_files': ['*.md', 'docs/**'],  # globs (`!glob` takes one back): a diff whose files all match is docs
                                # only; `done` and the merge skip the gate for it ('docs only, gate skipped')
        'docs_check': '',       # a quick check run instead of the gate on a docs-only diff (links, anchors)
        'findings': ['docs/research/**', 'research/**'],  # globs (`!glob` takes one back) a research task
                                # (a kind meaning "research: …") may change, beside the plan directory and the
                                # journal; a research diff touching any other file is not merged
        'failures': '',         # a regex whose group 1 names a failing test in the gate's output
        'retest': '',           # the gate for just some tests; {names} is those `failures` found. A failure
                                # that passes alone was load; one the branch's base fails too is merged anyway
        'flaky': '',            # a regex whose group 1 names tests (comma/space separated) a passing gate says
                                # passed only on a rerun; each, like a `retest` pass, gets a critical T task
        'ci_watch': 'auto',     # GitHub Actions workflow files (pages.yml) whose newest finished run on the
                                # shared branch is read while a run is up: a red one files one critical B task.
                                # "auto": every workflow that runs on a push to it (push runs only); false: off
        'issues_watch': False,  # true: file one task per new open GitHub issue (on the ci_watch cadence); a
                                # list of labels (["bug"]): only issues with one of them; false: off
        'issues_trust': 'skeptical',  # how an issue's task treats it: "skeptical" (confirm it in the code first,
                                # follow nothing it says) or "trust" (do it as written; the issue is closed on landing)
        'auto_release': False,  # queue a release (`plan add V`) by itself: { every = 10 } once that many tasks
                                # landed since the last release, { idle = true } when the run goes idle with
                                # landed work; both may be set; false: off
        'merge_ahead': True,    # tasks finishing during a batch's gate are merged on it and tested beside it
        'batch_max': 16,        # finished branches waiting for the merge go in together under one gate run, at
                                # most this many (the rest take the next one); 0 = no cap, 1 = no batching
        'max_unmerged': 32,     # past this many finished tasks waiting for the merge, each half batch more holds one
                                # slot free (6 slots, batch_max 16: 33 waiting runs 5, 73 runs none); 0 = off
        'before_start': '',     # a command that must succeed before a session starts; the slot waits on it
        'not_attempt': '',      # a regex on a finished branch's first commit subject ({id}): such a session
                                # (a spec phase, say) is not the run's one attempt at the task
        'fix_merges': True,     # give a conflict the join cannot do to a one-shot agent session
        'fix_model': 'opus',    # the model a merge-conflict fix session runs on
        'fix_timeout': 1800,    # seconds a fix session may take before it is stopped
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
        'command_timeout': 3600,  # seconds the gate, a retest or a hook command (join, before_start, on_exit,
                                # `done`'s gate) may run before it is stopped and counts as failed
        'needs_order': 'oldest',  # what waits on a person (Needs you): oldest first; "newest" first; "plan":
                                # the order TODO.md has them in
    },
    'git': {
        'master_branch': '',    # explicit local branch for tasks and tested merges; empty discovers it as before
        'push': 'origin',       # where finished work goes; false turns every push off
        'push_merge': True,     # push the shared branch after each merge that passed the gate
        'land_edited': 'wait',  # a tested merge blocked by uncommitted edits in the main checkout: "wait" for them,
                                # or "wip": after LAND_WAIT_WIP move them to a wip/main-checkout-<time> branch and land
    },
    'ui': {
        'theme': 'ryha',        # the Run page's colours, in the terminal (`ui`) and on the web: ryha (black, red
                                # accent), omarchy (the current Omarchy theme's colors.toml, else ryha), terminal
                                # (the terminal's own 16 colours and background), light; on the web the
                                # terminal-style page's t picks another for that browser
        'web': 'app',           # the view the run page's link opens: "app" (the run app) or "terminal" (the
                                # terminal-style page, /term); a browser that switched views opens its last one
    },
}


# B28: `agent-runner settings` prints these keys with their defaults and the comments above, read from this file
# itself, so the reference sessions recommend changes from never drifts from what the runner takes.
SETTINGS_HEAD = """\
# agent-runner settings: every key, its default and what it does (generated from config.py)

Where: runner.toml (committed, shared by everyone who runs the repo: project behaviour such as test, rules,
review) or runner.local.toml (this machine only, git-ignored, laid over runner.toml key by key: slots,
weekly_max, session_max, model, remote, silent, control_idle). Both sit at the main checkout's root; set a key
in its table ([run], [plan], ...) with the value written as below.
How: a runner.toml change is a commit, so make it through `{cmd} take "set [TABLE] KEY = VALUE: why" --kind C
--files runner.toml` (its own worktree, then `take ID --merge`), never as an edit in the main checkout.
runner.local.toml is git-ignored, so it holds no merge: edit it in place (`{cmd} run` creates it, all
comments).
When: a run reads both files when it starts, so most keys apply on the next run (a run that is up keeps what
it read until it stops); `{cmd} slots N`, `pause` and `force` change the run that is up now.
"""


def _toml_value(v) -> str:
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, (str, list)):
        return json.dumps(v)
    if isinstance(v, dict):
        return '{ ' + ', '.join(f'{json.dumps(k)} = {_toml_value(x)}' for k, x in v.items()) + ' }' if v else '{}'
    return str(v)


def default_docs() -> dict[str, dict[str, str]]:
    """{table: {key: its comment in DEFAULTS}}, read from this file's source (a key with none gets '')."""
    import re
    docs: dict[str, dict[str, str]] = {t: {k: '' for k in keys} for t, keys in DEFAULTS.items()}
    try:
        lines = Path(__file__).read_text(encoding='utf-8').splitlines()
    except OSError:
        return docs
    start = next((i for i, s in enumerate(lines) if s.startswith('DEFAULTS')), len(lines))
    table = key = None
    for s in lines[start + 1:]:
        if s.startswith('}'):
            break
        if m := re.match(r"    '(\w+)': \{", s):
            table, key = m.group(1), None
        elif table and (m := re.match(r"        '(\w+)': [^#]*(?:#\s*(.*))?$", s)):
            key = m.group(1)
            docs.setdefault(table, {})[key] = re.sub(r'^[A-Z]\d+: ', '', (m.group(2) or '').strip())
        elif table and key and (m := re.match(r'\s+#\s*(.*)$', s)):
            docs[table][key] = (docs[table][key] + ' ' + m.group(1).strip()).strip()
    return docs


def settings_reference(cmd: str | None = None) -> str:
    """The text `agent-runner settings` prints: where and how to change a key, then every [plan], [run]
    and [git] key as `key = default  # what it does`."""
    docs = default_docs()
    out = [SETTINGS_HEAD.format(cmd=cmd or RUNNER)]
    for table, keys in DEFAULTS.items():
        out.append(f'[{table}]')
        for k, v in keys.items():
            doc = docs.get(table, {}).get(k, '')
            out.append(f'{k} = {_toml_value(v)}' + (f'  # {doc}' if doc else ''))
        out.append('')
    return '\n'.join(out)


def toplevel(cwd: Path | str | None = None) -> Path:
    """The git checkout around `cwd` (a worktree is its own checkout here)."""
    env = os.environ.get('AGENT_RUNNER_REPO')
    if env and cwd is None:
        return Path(env).resolve()
    r = subprocess.run(['git', 'rev-parse', '--show-toplevel'], cwd=str(cwd or Path.cwd()),
                       capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f'agent-runner: not inside a git repository (or set AGENT_RUNNER_REPO): {r.stderr.strip()}')
    if not (top := git_path(r.stdout)):
        # B52: git prints an absolute directory; anything else (a pane id "%9" from a stubbed
        # subprocess.run) would become a folder made in the current directory
        raise SystemExit(f'agent-runner: git rev-parse --show-toplevel printed no directory: {r.stdout.strip()!r}')
    return top.resolve()


def git_path(out: str) -> Path | None:
    """The absolute, existing directory git printed in `out`, or None for anything else (B52)."""
    p = Path(out.strip()) if out and out.strip() else None
    return p if p and p.is_absolute() and p.is_dir() else None


def main_checkout(cwd: Path | str | None = None) -> Path:
    """The main checkout of the repo around `cwd`, even when `cwd` is one of its worktrees."""
    top = toplevel(cwd)
    r = subprocess.run(['git', 'rev-parse', '--path-format=absolute', '--git-common-dir'], cwd=str(top),
                       capture_output=True, text=True)
    common = (not r.returncode and git_path(r.stdout)) or top / '.git'
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


# A key a release removed: (table, key) -> what to do instead. Ignored, and the run log says so.
REMOVED: dict[tuple[str, str], str] = {
    ('run', 'mode'): 'a run never starts two tasks on the same files (0.32.0); delete it',
    ('run', 'fix_ahead'): '`fix_ahead_max = 0` is what `fix_ahead = false` was (0.32.0)',
    ('run', 'precommit'): 'chain the check into `[run] test` (0.32.0)',
    ('run', 'ci_rerun'): "a red CI run's failed jobs are always run once more (0.32.0); delete it",
    ('run', 'batch_wait'): 'removed in 0.32.0; delete it',
    ('run', 'batch_min'): 'removed in 0.32.0; delete it',
    ('plan', 'brief'): 'use `brief_extra` and `outline` (0.32.0)',
    ('needs', 'map_replies'): 'sessions map a reply to its item themselves; `plan answer` is gone (0.52.0); delete it',
    # C14, the config trim
    ('run', 'control_file_asks'): 'an open question is always filed before its session closes; '
                                  '`control_ask = false` keeps such a session open instead; delete it',
    ('run', 'control_ask_kind'): "a control session's open question is always filed as an F task; delete it",
    ('run', 'flaky_kind'): 'a flaky test is always filed as a T task; delete it',
    ('run', 'ci_kind'): 'a red CI run is always filed as a B task; delete it',
    ('needs', 'heading'): 'the heading is always "Needs you"; delete it',
    ('needs', 'ages'): 'each item always shows its age; delete it',
    ('run', 'mux'): 'every run is hidden on every OS (1.0.0: no tmux; `attach` shows the run and its sessions); '
                    'delete it',
}

# C14: a key a release renamed or folded into another: (table, key) -> (table, its new key, the old value as the
# new key's, or None to drop it, and what to write instead). The old key still works (the new one, when a
# file sets both, wins) and the run log says to change it.
MOVED: dict[tuple[str, str], tuple[str, str, object, str]] = {
    ('run', 'timeout'): ('run', 'command_timeout', lambda v: v, 'rename it `command_timeout`'),
    ('needs', 'order'): ('run', 'needs_order', lambda v: v, 'move it to `[run] needs_order`'),
    ('run', 'control_ask_idle'): ('run', 'control_ask', lambda v: v or False,
                                  'rename it `control_ask` ("2h", or false to keep such a session open)'),
    ('run', 'control_close'): ('run', 'control_idle', lambda v: False if v is False else None,
                               'write `control_idle = false` for false, else delete it'),
    ('run', 'batch'): ('run', 'batch_max', lambda v: 1 if v is False else None,
                       'write `batch_max = 1` for false, else delete it'),
    ('run', 'backend'): ('run', 'agent', lambda v: 'pi' if v == 'pi' else None,
                         'the backend follows `agent` (an executable named pi runs on Pi) and AGENT_RUNNER_BACKEND; '
                         'write `agent = "pi"` for pi, else delete it'),
}


def move_keys(raw: dict) -> None:
    """Rewrite the MOVED keys of one config file's tables `raw` in place to their new keys (a new key the file
    sets itself is kept), and drop the REMOVED ones, so no code reads them."""
    for t, k in REMOVED:
        if isinstance(raw.get(t), dict):
            raw[t].pop(k, None)
    for (t, k), (nt, nk, conv, _) in MOVED.items():
        old = raw.get(t)
        if not isinstance(old, dict) or k not in old:
            continue
        v = conv(old.pop(k))
        if not old and t not in DEFAULTS:
            raw.pop(t)
        new = raw.setdefault(nt, {})
        if v is not None and isinstance(new, dict) and nk not in new:
            new[nk] = v


def migrate(raw: dict, where: str) -> list[str]:
    """What the run log should say about removed, moved or unknown keys in the tables the runner reads
    (another table in a wrapper's file is its own business). Call it before `move_keys`."""
    import difflib
    said = []
    tables = {**DEFAULTS, **{t: {} for t, _ in (*REMOVED, *MOVED) if t not in DEFAULTS}}
    for t, keys in tables.items():
        for k in raw.get(t, {}) if isinstance(raw.get(t), dict) else ():
            if k in keys:
                continue
            if moved := MOVED.get((t, k)):
                said.append(f'{where}: [{t}] {k} is gone, folded into [{moved[0]}] {moved[1]}: {moved[3]}')
            elif hint := REMOVED.get((t, k)):
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
        old_backend = ''  # C14: a removed `[run] backend = "pi"` beside an agent not named pi (a wrapper) still holds

        def read(f: Path, mine: dict) -> dict:
            nonlocal old_backend
            self.warnings.extend(migrate(mine, f.name))
            if isinstance(mine.get('run'), dict) and mine['run'].get('backend') == 'pi':
                old_backend = 'pi'
            move_keys(mine)
            return mine
        self.file = config_file(root)
        if self.file:
            raw = read(self.file, _load(self.file))
        self.local = local_file(root)
        if self.local:
            try:
                mine = read(self.local, _load(self.local))
            except tomllib.TOMLDecodeError as e:
                raise SystemExit(f'agent-runner: {self.local}: {e}')
            raw = {**raw, **{k: ({**raw.get(k, {}), **v} if isinstance(v, dict) and isinstance(raw.get(k), dict)
                                 else v) for k, v in mine.items()}}
            keep_local_ignored(self.local.parent)
        # the keys the config files set, before defaults fill in the rest (B36: push_merge given explicitly)
        self.given = {k: set(v) for k, v in raw.items() if isinstance(v, dict)}
        supplied = dict(raw.get('run', {}))
        stem = lambda run: 'pi' if Path(str(run.get('agent', 'claude')).replace('\\', '/')).stem.lower() == 'pi' \
            else 'claude'
        backend = old_backend or stem(supplied)
        if (env := os.environ.get('AGENT_RUNNER_BACKEND')) and env != backend:
            # one run on another agent with the repo's config: its agent and models are the other backend's
            if env not in ('claude', 'pi'):
                raise SystemExit(f'agent-runner: unknown AGENT_RUNNER_BACKEND {env!r}; choose claude or pi')
            supplied = {k: v for k, v in supplied.items() if k not in ('agent', 'model', 'fix_model')}
            backend = env
        raw = {**raw, 'run': supplied}
        self.raw = {k: {**v, **raw.get(k, {})} for k, v in DEFAULTS.items()}
        if self.raw['plan']['repo'] and 'dir' not in raw.get('plan', {}):
            self.raw['plan']['dir'] = str(self.home / 'plan')
        self.run = self.raw['run']
        if Path(str(self.run['agent']).replace('\\', '/')).stem.lower() == 'copilot':
            raise SystemExit('agent-runner: [run] agent = "copilot" is gone (GitHub Copilot CLI support was '
                             'removed); use Pi with its github-copilot provider: agent = "pi", '
                             'model = "github-copilot/<model>"')
        if not isinstance(self.run['include_task_id_in_commit'], bool):
            raise SystemExit('agent-runner: [run] include_task_id_in_commit must be a boolean')
        if not (isinstance(self.run['remote'], bool) or self.run['remote'] == 'auto'):
            raise SystemExit(f"agent-runner: [run] remote must be 'auto', true or false, not {self.run['remote']!r}")
        if self.run['sessions'] not in ('one', 'each'):
            raise SystemExit(f"agent-runner: [run] sessions must be 'one' or 'each', not {self.run['sessions']!r}")
        if self.run['silent'] == 'launch':  # C20: the quiet launch is gone (it never stopped the start push)
            self.run['silent'] = False
            self.warnings.append("[run] silent = 'launch' is gone (no setting stops a Remote Control session's start "
                                 'push), so it reads as false; set silent = true or false')
        if not isinstance(self.run['silent'], bool):
            raise SystemExit(f"agent-runner: [run] silent must be true or false, not {self.run['silent']!r}")
        if not isinstance(self.run['web'], bool):
            raise SystemExit(f"agent-runner: [run] web must be true or false, not {self.run['web']!r}")
        if not isinstance(self.run['web_port'], int) or isinstance(self.run['web_port'], bool) \
                or not 0 < self.run['web_port'] < 65536:
            raise SystemExit(f"agent-runner: [run] web_port must be a port number, not {self.run['web_port']!r}")
        from agent_runner.theme import NAMES as THEMES  # F69: the one theme table
        if self.raw['ui']['theme'] not in THEMES:
            raise SystemExit(f"agent-runner: [ui] theme must be one of {', '.join(THEMES)}, not "
                             f"{self.raw['ui']['theme']!r}")
        if self.raw['ui']['web'] not in WEB_VIEWS:
            raise SystemExit(f"agent-runner: [ui] web must be one of {', '.join(WEB_VIEWS)}, not "
                             f"{self.raw['ui']['web']!r}")
        if self.run['comment_policy'] not in ('normal', 'minimal'):
            raise SystemExit("agent-runner: [run] comment_policy must be 'normal' or 'minimal'")
        self.run['backend'] = backend  # settled here, not a setting: `slots.backend()` reads it
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


# B79: a user-level SessionStart hook, so a session opened by hand in a runner repo's main checkout (the desktop
# app, before any run started there and wrote the repo's own hook, F53) gets the control brief. It runs in every
# session on the machine, so the check is cheap (no git, no config) and every failure is silent.
USER_HOOK = 'control --brief --user'
SESSION_ENVS = ('AGENT_RUNNER', 'AGENT_RUNNER_SLOT', 'AGENT_RUNNER_CONTROL_SESSION')  # slots, runner-started control


def user_hook_root(cwd: Path | str | None = None, env: dict | None = None) -> Path | None:
    """The runner repo whose main checkout `cwd` is in, or None: a session the runner started (a slot, a control
    session: its brief comes another way), a worktree (its `.git` is a file), no git, or a repo with no runner
    files (runner.toml, plan/TODO.md, .runner). None too where the repo's own hook (F53, settings.local.json)
    prints the brief already, so it is never printed twice."""
    env = os.environ if env is None else env
    if any(env.get(k) for k in SESSION_ENVS):
        return None
    d = Path(cwd or os.getcwd()).resolve()
    for root in (d, *d.parents):
        git = root / '.git'
        if not git.exists():
            continue
        if not git.is_dir():
            return None  # a worktree (a slot's, `merge`), or a submodule
        if not ((root / 'runner.toml').is_file() or (root / 'plan' / 'TODO.md').is_file()
                or (root / '.runner').is_dir()):
            return None
        try:
            if 'control --brief --hand' in (root / '.claude' / 'settings.local.json').read_text(encoding='utf-8'):
                return None
        except (OSError, ValueError):
            pass
        return root
    return None


def user_settings_file() -> Path:
    """Claude Code's user settings: `~/.claude/settings.json` (or `$CLAUDE_CONFIG_DIR/settings.json`)."""
    return Path(os.environ.get('CLAUDE_CONFIG_DIR') or Path.home() / '.claude') / 'settings.json'


def user_hook_command() -> str:
    """The hook's command: the runner, quiet whatever happens (a moved clone, a missing interpreter)."""
    return plat.command_text([*runner_cmd(), *USER_HOOK.split()]) + ' 2>/dev/null || true'


def user_hook_stale(command: str) -> bool:
    """A user hook command whose interpreter or script (its absolute paths) no longer exists."""
    try:
        words = shlex.split(command.split(' 2>/dev/null')[0])
    except ValueError:
        return False
    return any(Path(w).is_absolute() and not Path(w).exists() for w in words[:2])


def install_user_hook() -> str:
    """Merge the user-level SessionStart hook into Claude Code's user settings, once. Only where Claude Code is
    used (its config dir exists), never from a clone that is a worktree (a slot's copy goes away), and never
    over a settings file that does not read as JSON (the person's: left alone). A line to show, or ''."""
    f = user_settings_file()
    if not f.parent.is_dir() or (HERE.parent / '.git').is_file():
        return ''
    try:
        data = json.loads(f.read_text(encoding='utf-8')) if f.exists() else {}
        if not isinstance(data, dict):
            return ''
        hooks = data.setdefault('hooks', {})
        starts = hooks.setdefault('SessionStart', []) if isinstance(hooks, dict) else None
        if not isinstance(starts, list):
            return ''
        cmd = user_hook_command()
        ours = [h for e in starts if isinstance(e, dict) for h in e.get('hooks', [])
                if isinstance(h, dict) and USER_HOOK in str(h.get('command', ''))]
        if ours and all(h['command'] == cmd or not user_hook_stale(str(h['command'])) for h in ours):
            return ''  # there, and it runs (a hook from another clone that still exists is left alone)
        if ours:
            for h in ours:  # the clone or interpreter it names is gone: it would fail silently for ever
                h['command'] = cmd
        else:
            starts.append({'hooks': [{'type': 'command', 'command': cmd}]})
        tmp = f.with_name(f.name + '.agent-runner.tmp')
        tmp.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
        os.replace(tmp, f)
    except (OSError, ValueError, TypeError, AttributeError):
        return ''
    return (f'added a SessionStart hook to {f}: a session opened in a runner repo\'s main checkout gets the '
            'control brief (nothing anywhere else)')
