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
key, table by table: one person's settings on one machine (`weekly_max`, `slots`) without editing the
file everyone shares. It may wrap its tables in `[agent-runner]` too. `run` creates it in the main checkout
(all comments, so it changes nothing) when it is missing and changes it only as the run app's Settings view asks (F97), and keeps it out of git by
adding it to the clone's `.git/info/exclude`.

Every session runs on Claude Code, or on the harness loop for another provider's model (`[models] code =
"<provider>:<model>"`); the Pi backend (`[run] agent = "pi"`) is gone (F106d): `Config.agent_problem` says so (B764b).
"""
from __future__ import annotations

import copy
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
from agent_runner.whole_write import write_whole

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
                                # the path. The brief shows it under each file over 300 lines the task line names
        'lessons': False,       # <dir>/LESSONS.md, what agents learned per file, shown in briefs (`plan lesson`)
        'kinds': {},            # id prefix -> the kind of work it marks (`plan kinds`); empty = plan.KINDS
        'need_files': False,    # `plan add` refuses a line with no files: or test: field
        'lookup': [],           # more markdown files `plan <name>` searches for a heading (after TODO, REFERENCE,
                                # HUMAN, DONE and [run] rules), e.g. ["PLAN.md", "plan/*.md"]; globs allowed
        'context_kb': 12,       # budget for what every session loads (rules, CLAUDE.md, AGENTS.md, @-imports):
                                # `agent-runner context` reports it, `run` warns past it; 0 = no warning
        'glossary': 'GLOSSARY.md',  # the project's glossary (`agent-runner glossary`), seeded by the first control
                                # session and named in every brief; false = off: no file written, briefs skip it
    },
    'run': {
        'test': '',             # the gate: `done` and every merge run it; empty means no gate
        'test_since': '',       # a merge's gate on what changed since {base} (a commit that passed the gate);
                                # '' = the whole `test` every time
        'done_test': '',        # what `done` runs before its commit in place of `test`, on a docs-only diff
                                # too (a build, an audit); a merge still runs `test` / `test_since`. '' = `test`
        'full_every_hours': 24, # with test_since: the whole `test` again once none has passed for this long; 0 = never
        'slots': 3,             # tasks (agent sessions) at once; `agent-runner slots N` changes a running run
        'agent': 'claude',      # the Claude Code executable that runs a session (or a wrapper around it)
        'engine': 'terminal',   # F106b: how a slot runs Claude Code. terminal = an interactive session in a
                                # hidden pty; stream = headless `claude -p` with stream-json in and out
        'include_task_id_in_commit': True,  # agents start each commit subject with the task id
        'lean': True,           # agents get Bash/Read/Edit/Write/Artifact only, no MCP, no user settings
        'remote': 'auto',       # control sessions on Remote Control, and a control server there to start more:
                                # the run, watched and steered from claude.ai/code and the Claude apps; auto = on
                                # when it can work (Claude Code on a claude.ai login), true/false force it
        'remote_slots': 'open', # the slots in the Claude apps. open = a slot is listed only once opened from the run
                                # page, and the run keeps a claude.ai copy of the run page;
                                # always = every slot its own entry, "<task title> · <repo> s2 · B646", and no copy
        'web': True,            # the run page on the web, served by the run from this machine on web_port for the
                                # LAN/Tailscale (its address, with the token it needs, in `status` and the run log)
        'web_port': 8770,       # where the run page is served (its ttyds take the next ports); with Home, only if set (F165)
        'web_open': 'everywhere',  # F454a: who opens a page Runner Home does not: everywhere = every interface
                                # (LAN, Tailscale), here = this machine only (127.0.0.1, its localhost link; no
                                # Tailscale Serve rule). Per machine: set it in runner.local.toml
        'web_https': True,      # an https address for it on the tailnet, by Tailscale Serve on web_port + 1 (F96)
        'silent': False,        # phone pushes from the run's Remote Control sessions: true = none after each
                                # one's start push (that one cannot be stopped), false = Claude Code's usual
        'control': True,        # the run reopens the control sessions a shutdown cut off and, with remote, keeps the
                                # control server up; it opens none of its own (F176). false: neither
        'control_idle': '3h',   # the run closes control sessions quiet this long with Claude
                                # last and nothing running in them; transcripts kept. false: none closed idle
        'control_ask': '2h',    # quiet this long on a question marked with a last line `DECIDE: …` (F135):
                                # filed under Needs you as a DECIDE item, then closed. false: such a session stays open
        'auto_upgrade': True,   # upgrade agent-runner by itself when a newer release is out, once no merge runs,
                                # and restart the run on it (as `u` does, without the key), also when a source
                                # checkout's agent_runner code changed on main; false: only `u` or a restart does
        'install_skill': True,  # keep the `agent-runner guide` skill in ~/.claude/skills, for sessions a person starts
        'rules_pointer': True,  # a run adds one line to the rules file (`rules`, AGENTS.md, CLAUDE.md) pointing at it
        'questionnaires': True, # a DECIDE with more than one question is asked as a pick sheet (<notes>/sheets/<ID>.json, a
                                # page with `agent-runner sheet <ID>`); Needs you shows one line and its link
        'grill': 'ask',         # control sessions ask rounds of numbered questions before queueing:
                                # ask = when the person says grill me / poke holes; big = also big vague asks; off
        'voice': '',            # the person's wording file (`agent-runner voice`), read by control sessions
                                # and task agents; '' = ~/.config/agent-runner/voice.md; a
                                # .runner/voice.md with lines overrides it for this project
        'voice_learn': 'ask',   # ask = a session that had to say something again offers one wording line to add;
                                # off = lines are added only when the person says so
        'review': True,         # before done, a fresh subagent reads the diff against the task's brief (spec
                                # only: missing, unasked, wrong); the commit ends 'review: …'; false: no review
        'review_min_lines': 50, # a diff smaller than this (changed lines) skips the review, unless the task has a
                                # long form (plan/tasks/<ID>.md)
        'context_warn': 150,    # k tokens: a slot session whose context peaks past this says so, and what filled
                                # it, in its exit line and `since`, and is told once, at a turn's end, to finish and
                                # file the rest as a part (soft only: nothing is stopped); 0 = off
        'task_size': 10,        # a task bigger than this is split: its code files, plus 2 per numbered outcome, plus 1 per
                                # 400 characters of text; `plan` says so and its session splits it first; 0 = off
        'split_files': True,    # free slots that start nothing while 3 or more ready tasks wait for one file: the run queues
                                # one critical (alone) task that splits it; false: off
        'task_tokens': 0,       # tokens (input, cache writes, output; not cache reads) one task's session may use; past
                                # it the task stops at a clean point and is parked as wip/<ID>; 0 = no cap
        'task_usd': 0,          # the same in dollars at the API's list prices (a plan bills none); 0 = no cap
        'usage_limits': True,   # false: never read the account's usage, no hold or fallback on weekly_max / session_max
        'weekly_max': 90,       # % of the account's 7-day usage past which new tasks wait, or start on [models] fallback
        'session_max': 90,      # % of the account's 5-hour session usage past which new tasks wait, or start on [models] fallback
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
        'approve': False,       # true: nothing reaches the push remote until a person approves it. Merges land here
                                # and wait in pitches (pages under Needs you: Approve / Not this)
        'approve_wait': 30,     # minutes without a new merge into a group of related changes before its pitch opens
        'approve_batch': 5,     # a group this big opens its pitch at once
        'approve_diff_lines': 400,  # lines of each change's diff its Review page shows (0: none)
        'ci_watch': 'auto',     # GitHub Actions workflow files (pages.yml) whose newest finished run on the
                                # shared branch is read while a run is up: a red one files one critical B task.
                                # "auto": every workflow that runs on a push to it (push runs only); false: off
        'issues_watch': False,  # true: file one task per new open GitHub issue (on the ci_watch cadence); a
                                # list of labels (["bug"]): only issues with one of them; false: off
        'issues_trust': 'skeptical',  # how an issue's task treats it: "skeptical" (confirm it in the code first,
                                # follow nothing it says), "trust" (do it as written; the issue is closed on landing),
                                # "contributors" / "members" (trust by the author's GitHub role), a list of logins,
                                # or "approve" (no agent sees an issue's text until you approve it under Needs you)
        'releases': True,       # manage releases; false: no release rows, lines or New release, and none queued by
                                # itself (auto_release keeps its value); a typed `plan add V` still works
        'auto_release': False,  # queue a release (`plan add V`) by itself: { every = 10 } once that many tasks
                                # landed since the last release, { idle = true } when the run goes idle with
                                # landed work; both may be set; false: off
        'slot_memory': True,    # slot, fix and repair sessions keep Claude Code's memories; false (after a person OKed the
                                # move of a project's memories into lessons): autoMemoryEnabled off for them; control sessions keep theirs
        'auto_audit': False,    # queue an audit task by itself: { every = 50 } once that many tasks landed since the last
                                # audit and the run is idle; true: every 50; false: off
        'audit_tokens': 1_000_000,  # tokens (as task_tokens counts them) an audit's session may use; past it, it lands
                                # what it found; 0 = no cap
        'batch_max': 16,        # finished branches waiting for the merge go in together under one gate run, at
                                # most this many (the rest take the next one); 0 = no cap, 1 = no batching
        'max_unmerged': 32,     # past this many finished tasks waiting for the merge, each half batch more holds one
                                # slot free (6 slots, batch_max 16: 33 waiting runs 5, 73 runs none); 0 = off
        'before_start': '',     # a command that must succeed before a session starts; the slot waits on it
        'not_attempt': '',      # a regex on a finished branch's first commit subject ({id}): such a session
                                # (a spec phase, say) is not the run's one attempt at the task
        'fix_merges': True,     # give a conflict the join cannot do to a one-shot agent session
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
        'tools': {},            # the shared tools, [run.tools.<name>]: things only one task can use at a time (a
                                # test phone). check = a command that exits 0 free, 75 busy, 69 missing, its first
                                # output line the holder or why; label; connect = what Needs you asks when missing;
                                # description = what it is, for agents; page = its web page (an http/https URL, or
                                # ':PORT' of this machine); start = the command that serves it (F428a);
                                # buttons = a list of {label, cmd, confirm}, commands a person runs from the Tools
                                # page, confirm a question asked first (F428c)
        'checks': {},           # the checks a blocked task can wait on, [run.checks.<name>]: cmd = a command that exits 0
                                # passed, 75 not yet, anything else cannot run (main checkout, 10 s); label
        'command_timeout': 3600,  # seconds the gate, a retest or a hook command (join, before_start, on_exit,
                                # `done`'s gate) may run before it is stopped and counts as failed
        'needs_order': 'oldest',  # what waits on a person (Needs you): oldest first; "newest" first; "plan":
                                # the order TODO.md has them in
    },
    'git': {
        'master_branch': '',    # explicit local branch for tasks and tested merges; empty discovers it as before
        'push': 'origin',       # where finished work goes; false turns every push off
        'no_push': False,       # the no-push policy: no push by the runner, and `git push` refused in every session
                                # it starts, in any repository; applies from the next run
        'push_merge': True,     # push the shared branch after each merge that passed the gate
        'pr': False,            # PR mode: each finished task is a pull request on GitHub that a person merges; the runner
                                # never merges and never pushes the shared branch. Needs [plan] repo and branch
                                # protection there that its token cannot bypass; refused with [run] approve. Next run
        'pr_max': 5,            # PR mode: no new task starts while this many pull requests are open; 0: no limit
        'land_edited': 'wait',  # a tested merge blocked by uncommitted edits in the main checkout: "wait" for them,
                                # or "wip": after LAND_WAIT_WIP move them to a wip/main-checkout-<time> branch and land
    },
    'ui': {
        'theme': 'ryha',        # the Run page's colours, in the terminal (`ui`) and on the web: ryha (black, red
                                # accent), omarchy (the current Omarchy theme's colors.toml, else ryha), terminal
                                # (the terminal's own 16 colours and background), light
        'chat_quiet': '6h',     # a chat that needs no reply, with nothing said in it for this long, is grayed at the
                                # bottom of the run app's Chats (never a pinned or a renamed one); false: off
        'trusted_networks': [],  # CIDRs (or 'tailnet') whose clients open the run's own page without its key;
                                # [] = the key always. Through Runner Home its own list counts (`home trust`)
    },
    'models': {
        'provider': 'claude',   # the provider of every model below written as a bare name (opus, sonnet, haiku
                                # or the provider's own id): claude, copilot, codex, gemini, ollama or one of
                                # [models.providers]. One written '<provider>:<model>' keeps its own provider
        'code': 'opus',         # a task's own session when its kind has no model below
        'review': 'opus',       # the `review` subagent the spec review before done runs in; a one-shot (`run
                                # review`) when it, or the task's session, is another provider's
        'fix': 'opus',          # a merge-conflict fix or repair session
        'docs': 'haiku',        # the `docs` subagent a task hands CHANGELOG, docs, README, journal and plan-text
                                # edits to, then checks; false, or another provider's model: no docs subagent
        'control': 'opus',      # control sessions (c2, c3, ...); another provider's runs on the harness loop, with no
                                # Remote Control, push or Artifact
        'feed': 'haiku',        # the one-shot that publishes the run page's claude.ai copy; another
                                # provider's has no claude.ai page: the local copy stands
        'audit': 'opus',        # an audit task's session ([run] auto_audit, or one added by hand)
        'kinds': {'F': 'opus', 'B': 'opus', 'T': 'opus', 'V': 'opus', 'K': 'opus', 'D': 'sonnet', 'C': 'sonnet',
                  'R': 'sonnet'},  # a task's session by its kind (the id's letters): a kind set here replaces
                                # only that kind; one not listed runs on `code`; `plan add --model` wins for a task
        'sizes': {},            # a task's session by its size (`plan add --size simple`), e.g. simple = "sonnet";
                                # empty: sizes are ignored. Over [models.kinds]; `--model` wins for a task. A
                                # simple task that fails or blocks retries once on its kind's model
        'local': False,         # allow a local provider (ollama, or a provider url on localhost or a private
                                # address) in a role; off, a role naming one is refused
        'providers': {},        # the repo's own providers, [models.providers.<name>]: kind = "openai" or
                                # "anthropic" (a compatible API), url, key_env (the env var holding its key, never
                                # the key itself); a role names one as "<name>:<model>"
        'fallback': [],         # F106g: a list of '<provider>:<model>' a task goes on with when its provider
                                # hits its cap (a Claude usage limit, a provider's quota error), in order; new
                                # tasks go back to their own model once the cap resets. Empty: a task waits
                                # for the reset
        'tiers': {},            # [models.tiers.<provider>]: what opus, sonnet and haiku mean on a provider other
                                # than claude, e.g. copilot = { opus = "claude-opus-5.5" }; laid over the built-in
                                # ones (TIERS) name by name. A bare name with none goes to the provider as it is
    },
}

# the providers a [models] role may name as '<provider>:<model>' without defining them; a bare name is claude's
PROVIDERS = ('claude', 'copilot', 'codex', 'gemini', 'ollama')
LOCAL_PROVIDERS = ('ollama',)
PROVIDER_KINDS = ('openai', 'anthropic')
SIZES = ('simple', 'complex')  # F470: a task's `size:` field
# the [models] keys that are not roles
MODEL_SETTINGS = ('kinds', 'sizes', 'local', 'providers', 'fallback', 'provider', 'tiers')
# F443: the claude model names a bare role value may use on any provider, and what each means on a built-in one
TIER_NAMES = ('opus', 'sonnet', 'haiku')
TIERS: dict[str, dict[str, str]] = {
    'copilot': {'opus': 'claude-opus-5.5', 'sonnet': 'claude-sonnet-5.5', 'haiku': 'claude-haiku-5.5'},
    'codex': {'opus': 'gpt-6.2-sol', 'sonnet': 'gpt-6.1-terra', 'haiku': 'gpt-6-luna'},
    'gemini': {'opus': 'gemini-pro-latest', 'sonnet': 'gemini-flash-latest', 'haiku': 'gemini-flash-lite-latest'},
}

# the [models] roles that run as Claude Code subagents of a task session (`--agents`), not sessions of their own
SUBAGENT_ROLES = ('review', 'docs')


# B28: `agent-runner settings` prints these keys with their defaults and the comments above, read from this file
# itself, so the reference sessions recommend changes from never drifts from what the runner takes.
SETTINGS_HEAD = """\
# agent-runner settings: every key, its default and what it does (generated from config.py)

Where: runner.toml (committed, shared by everyone who runs the repo: project behaviour such as test, rules,
review) or runner.local.toml (this machine only, git-ignored, laid over runner.toml key by key: slots,
weekly_max, session_max, remote, silent, control_idle). Both sit at the main checkout's root; set a key
in its table ([run], [plan], ...) with the value written as below.
How: a runner.toml change is a commit, so make it through `{cmd} take "set [TABLE] KEY = VALUE: why" --kind C
--files runner.toml` (its own worktree, then `take ID --merge`), never as an edit in the main checkout.
runner.local.toml is git-ignored, so it holds no merge: edit it in place (`{cmd} run` creates it, all
comments).
When: a run that is up reads both files again when they change, so most keys apply within seconds (running
tasks keep their own; a file that does not parse or a bad value keeps the old settings, and run.log says why). A
few apply on the next run: {next_run}. `{cmd} slots N`, `pause` and `force`
change the run that is up now without a file.
"""


def local_url(url: str) -> bool:
    """True when a provider url points at this machine or a private network (localhost, *.local, a loopback,
    private or link-local address); a public host name is taken as remote, never resolved."""
    import ipaddress
    from urllib.parse import urlsplit
    host = (urlsplit(url).hostname or '').lower()
    if host in ('localhost', '') or host.endswith(('.localhost', '.local')):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_unspecified


def model_providers(given: object) -> dict[str, dict]:
    """`[models.providers]`, each checked: {name: {kind, url, key_env, local}}. Refuses (SystemExit) a provider
    without a known kind or an http(s) url, one that shadows a built-in name, one holding a key itself, and a
    remote one without key_env."""
    if not isinstance(given, dict):
        raise SystemExit(f'agent-runner: [models.providers] is a table of providers, not {given!r}')
    out = {}
    for name, p in given.items():
        where = f'agent-runner: [models.providers.{name}]'
        if name in PROVIDERS:
            raise SystemExit(f'{where}: {name} is a built-in provider; give yours another name')
        if not isinstance(p, dict):
            raise SystemExit(f'{where} must be a table (kind, url, key_env), not {p!r}')
        if held := [k for k in p if k in ('key', 'api_key', 'token', 'secret')]:
            raise SystemExit(f'{where}: {held[0]} holds a key in the config; keys never go in runner.toml: set '
                             'key_env to the name of the env var that holds it')
        if p.get('kind') not in PROVIDER_KINDS:
            raise SystemExit(f'{where}: kind must be one of {", ".join(PROVIDER_KINDS)}, not {p.get("kind")!r}')
        url = p.get('url')
        if not (isinstance(url, str) and url.startswith(('http://', 'https://'))):
            raise SystemExit(f'{where}: url must be an http(s) address, not {url!r}')
        key_env = p.get('key_env', '')
        if not isinstance(key_env, str) or (key_env and not key_env.replace('_', 'A').isalnum()):
            raise SystemExit(f'{where}: key_env must be the name of an env var (MY_API_KEY), not {key_env!r}')
        local = local_url(url)
        if not key_env and not local:
            raise SystemExit(f'{where}: key_env is missing: name the env var that holds its key')
        out[name] = {'kind': p['kind'], 'url': url, 'key_env': key_env, 'local': local}
    return out


def parse_model(value: str, providers: dict[str, dict] | None = None, local: bool = False,
                where: str = '[models]') -> tuple[str, str]:
    """A [models] role's value as (provider, model): '<provider>:<model>' for a built-in or `providers` name, a
    bare name ('opus') as ('claude', 'opus'). Refuses (SystemExit) an unknown provider, an empty model, and a
    local provider (ollama, or a url on localhost or a private address) unless `local`."""
    providers = providers or {}
    head, sep, rest = value.partition(':')
    if not sep:
        return 'claude', value
    head, at, login = head.partition('@')  # F504: 'claude@work:opus' pins claude's login 'work'
    if at and (head != 'claude' or not login or not login.replace('-', 'a').replace('_', 'a').isalnum()):
        raise SystemExit(f'agent-runner: {where} = {value!r}: only claude has logins to pin, as claude@<login>:<model>')
    if head not in PROVIDERS and head not in providers:
        raise SystemExit(f'agent-runner: {where} = {value!r}: unknown provider {head!r}; use one of '
                         f'{", ".join([*PROVIDERS, *providers])}, or define it in [models.providers.{head}]')
    if not rest:
        raise SystemExit(f'agent-runner: {where} = {value!r}: no model after {head}:')
    if not local and (head in LOCAL_PROVIDERS or providers.get(head, {}).get('local')):
        raise SystemExit(f'agent-runner: {where} = {value!r}: {head} is a local provider, refused unless '
                         '[models] local = true')
    return head, rest


# F106c: every role runs on any provider, another than claude through the harness loop (agent_runner/harness.mjs),
# F406f: control sessions too. F406e: a
# feed or review model there is a one-shot (feed.harness_once); a docs model there leaves docs to the task's session


def claude_model(value: str, providers: dict[str, dict] | None = None, local: bool = False,
                 where: str = '[models]') -> str:
    """`parse_model`, then the model as a session runs it: claude's as the bare name ('opus'), another
    provider's as '<provider>:<model>', which the harness loop runs (F106c)."""
    provider, model = parse_model(value, providers, local, where)
    if provider == 'claude':
        _, login = pinned_login(value)
        return f'claude@{login}:{model}' if login else model
    return f'{provider}:{model}'


def pinned_login(model: str) -> tuple[str, str | None]:
    """F504: a model with a pinned login ('claude@work:opus') as (the model Claude Code runs, 'opus'; the login,
    'work'); any other model as (model, None)."""
    head, sep, rest = (model or '').partition(':')
    prov, at, login = head.partition('@')
    if sep and at and prov == 'claude' and login:
        return rest, login
    return model, None


def model_provider(given: object, providers: dict[str, dict] | None = None, local: bool = False) -> str:
    """F443: `[models] provider`, checked: a built-in or `providers` name, a local one only with `local`."""
    providers = providers or {}
    if not isinstance(given, str) or given not in (*PROVIDERS, *providers):
        raise SystemExit(f'agent-runner: [models] provider must be one of {", ".join([*PROVIDERS, *providers])}, '
                         f'not {given!r}')
    if not local and (given in LOCAL_PROVIDERS or providers.get(given, {}).get('local')):
        raise SystemExit(f'agent-runner: [models] provider = {given!r} is a local provider, refused unless '
                         '[models] local = true')
    return given


def model_tiers(given: object, providers: dict[str, dict] | None = None) -> dict[str, dict[str, str]]:
    """F443: `[models.tiers]` laid over TIERS provider by provider, name by name; refuses (SystemExit) an unknown
    provider, a name other than opus, sonnet or haiku, and an empty model."""
    if not isinstance(given, dict):
        raise SystemExit(f'agent-runner: [models.tiers] is a table of providers, not {given!r}')
    out = {p: dict(t) for p, t in TIERS.items()}
    for p, t in given.items():
        where = f'agent-runner: [models.tiers.{p}]'
        if p == 'claude' or p not in (*PROVIDERS, *(providers or {})):
            raise SystemExit(f'{where}: not a provider other than claude')
        if not isinstance(t, dict) or not all(k in TIER_NAMES and isinstance(v, str) and v and ':' not in v
                                              for k, v in t.items()):
            raise SystemExit(f'{where} maps opus, sonnet or haiku to a model id (opus = "x"), not {t!r}')
        out[p] = {**out.get(p, {}), **t}
    return out


def on_provider(value: str, provider: str = 'claude', tiers: dict[str, dict[str, str]] | None = None) -> str:
    """F443: a bare model name as `provider`'s ('<provider>:<model>', opus/sonnet/haiku through its `tiers`); a
    value that names its provider, and any value on claude, is left as it is."""
    if provider == 'claude' or ':' in value:
        return value
    return f'{provider}:{(tiers or {}).get(provider, {}).get(value, value)}'


def harness_model(value: str, providers: dict | None = None) -> bool:
    """F106c: `value` is a settled model (`claude_model`'s) the harness loop runs: '<provider>:<model>' with a
    provider other than claude, built in or one of `providers`."""
    head, sep, _ = (value or '').partition(':')
    return bool(sep) and head != 'claude' and (head in PROVIDERS or head in (providers or {}))


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
    from agent_runner.config_settings import SETTING_NEXT
    docs = default_docs()
    out = [SETTINGS_HEAD.format(cmd=cmd or RUNNER, next_run=', '.join(f'[{t}] {k}' for t, k in sorted(SETTING_NEXT)))]
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
    key = str(Path(cwd or Path.cwd()).resolve())
    if key in _TOPS and (_TOPS[key] / '.git').exists():  # a deleted checkout (a test's temp repo) is asked again
        return _TOPS[key]
    r = subprocess.run(['git', 'rev-parse', '--show-toplevel'], cwd=str(cwd or Path.cwd()),
                       capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f'agent-runner: not inside a git repository (or set AGENT_RUNNER_REPO): {r.stderr.strip()}')
    if not (top := git_path(r.stdout)):
        # B52: git prints an absolute directory; anything else (a pane id "%9" from a stubbed
        # subprocess.run) would become a folder made in the current directory
        raise SystemExit(f'agent-runner: git rev-parse --show-toplevel printed no directory: {r.stdout.strip()!r}')
    _TOPS[key] = top.resolve()
    return _TOPS[key]


# B885: a checkout's top and main checkout never change, and each git rev-parse costs ~100 ms on Windows
_TOPS: dict[str, Path] = {}
_MAINS: dict[Path, Path] = {}


def clear_git_cache() -> None:
    """Forget the memoized toplevel()/main_checkout() answers (for tests that move or make repos)."""
    _TOPS.clear()
    _MAINS.clear()


def git_path(out: str) -> Path | None:
    """The absolute, existing directory git printed in `out`, or None for anything else (B52)."""
    p = Path(out.strip()) if out and out.strip() else None
    return p if p and p.is_absolute() and p.is_dir() else None


def main_checkout(cwd: Path | str | None = None) -> Path:
    """The main checkout of the repo around `cwd`, even when `cwd` is one of its worktrees."""
    top = toplevel(cwd)
    if top in _MAINS and (_MAINS[top] / '.git').exists():
        return _MAINS[top]
    r = subprocess.run(['git', 'rev-parse', '--path-format=absolute', '--git-common-dir'], cwd=str(top),
                       capture_output=True, text=True)
    common = (not r.returncode and git_path(r.stdout)) or top / '.git'
    main = common.parent.resolve() if common.name == '.git' else top
    if not r.returncode:
        _MAINS[top] = main
    return main


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
# added it to .git/info/exclude) and the runner changes a key only when you set it in the run app's Settings.
# Uncomment and edit; any key runner.toml takes works here, in the same tables.

# [run]
# usage_limits = true    # false: never read the account's usage, no hold or fallback on the two caps below
# weekly_max = 90        # % of the account's 7-day usage past which new tasks wait, or start on [models] fallback
# session_max = 90       # % of the account's 5-hour session usage past which new tasks wait, or start on [models] fallback
# slots = 3              # parallel sessions on this machine
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
    ('run', 'wizards'): 'removed (C37): a task that needs a person writes its steps in an ask file; delete it',
    ('run', 'fix_ahead'): '`fix_ahead_max = 0` is what `fix_ahead = false` was (0.32.0)',
    ('run', 'precommit'): 'chain the check into `[run] test` (0.32.0)',
    ('run', 'ci_rerun'): "a red CI run's failed jobs are always run once more (0.32.0); delete it",
    ('run', 'batch_wait'): 'removed in 0.32.0; delete it',
    ('run', 'batch_min'): 'removed in 0.32.0; delete it',
    ('plan', 'brief'): 'use `brief_extra` and `outline` (0.32.0)',
    ('plan', 'release_alone'): "tag the release '(alone)' instead (`plan edit ID --alone`, F130): any task "
                               'tagged so runs alone; delete it',
    ('needs', 'map_replies'): 'sessions map a reply to its item themselves; `plan answer` is gone (0.52.0); delete it',
    # C14, the config trim
    ('run', 'control_file_asks'): 'an open question is always filed before its session closes; '
                                  '`control_ask = false` keeps such a session open instead; delete it',
    ('run', 'control_ask_kind'): "a control session's open question is always filed as an F task; delete it",
    ('run', 'flaky_kind'): 'a flaky test is always filed as a T task; delete it',
    ('run', 'ci_kind'): 'a red CI run is always filed as a B task; delete it',
    ('needs', 'heading'): 'the heading is always "Needs you"; delete it',
    ('needs', 'ages'): 'each item always shows its age; delete it',
    ('run', 'mux'): 'every run is hidden on every OS (0.60.0: no tmux; `attach` shows the run and its sessions); '
                    'delete it',
    ('run', 'comment_policy'): 'write it in `prompt_extra`; delete it',
    ('run', 'idle'): "always 30 seconds (`run --idle N` for one run); delete it",
    ('run', 'stall'): 'always 1200 seconds (`run --stall N` for one run); delete it',
    ('run', 'pause'): 'always 60 seconds (`run --pause N` for one run); delete it',
    ('run', 'merge_ahead'): 'always on; delete it',
    ('run', 'fix_timeout'): 'always 1800 seconds; delete it',
    ('run', 'control_idle_quick'): 'always 5 minutes; delete it',
    ('run', 'control_idle_talked'): 'always 12 hours; delete it',
    ('run', 'control_open'): 'what reads as an offer is fixed; delete it',
    ('run', 'backend'): 'every session runs on Claude Code or, for another provider\'s model, the harness loop '
                        '(F106d); delete it',
}

# F106d: what a file that still names the removed Pi backend is told (`[run] agent = "pi"`, `backend = "pi"`,
# AGENT_RUNNER_BACKEND=pi)
PI_GONE = ('the Pi backend is gone (F106d): the harness loop runs other providers\' models. Delete it, and name the '
           'model in [models] as "<provider>:<model>", e.g. [models] code = "copilot:<model>" (providers: '
           f'{", ".join(p for p in PROVIDERS if p != "claude")}, or your own [models.providers.<name>]); '
           '`run login <provider>` adds its login')

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
    ('run', 'model'): ('models', 'code', lambda v: v, 'move it to `[models] code`'),
    ('run', 'fix_model'): ('models', 'fix', lambda v: v, 'move it to `[models] fix`'),
    ('run', 'sessions'): ('run', 'remote_slots', lambda v: None,  # `slots_in_apps` takes its value
                          'write `remote_slots = "always"` for "each" with remote_slots = true, else delete both'),
}

# F166: values that were settings, fixed now; the run reads them in `C.run` as before
FIXED: dict[str, object] = {'idle': 30, 'stall': 1200, 'pause': 60, 'merge_ahead': True, 'fix_timeout': 1800}


def old_sessions(raws: list[dict]) -> str:
    """F166: what the files `raws` (the later one wins; before `move_keys`) set the cut `[run] sessions` to, '' for none."""
    return next((str(r['run']['sessions']) for r in reversed(raws)
                 if isinstance(r.get('run'), dict) and 'sessions' in r['run']), '')


def slots_in_apps(v, sessions: str):
    """F166: `[run] remote_slots` = `v` as 'open' or 'always': the old true listed every slot only with
    `sessions = "each"`. Any other value is given back as it is."""
    return ('always' if v and sessions == 'each' else 'open') if isinstance(v, bool) else v


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
        from agent_runner.config_settings import both_problem, checks_problem, setting_problem, tools_problem
        self.root = root
        raw: dict = {}
        sessions: list[dict] = []
        self.warnings: list[str] = []  # old, removed or unknown keys; the run logs them at its start

        def read(f: Path, mine: dict) -> dict:
            if isinstance(mine.get('run'), dict) and mine['run'].get('backend') == 'pi':
                raise SystemExit(f'agent-runner: {f.name}: [run] backend = "pi": {PI_GONE}')
            self.warnings.extend(migrate(mine, f.name))
            sessions.append({'run': dict(mine['run'])} if isinstance(mine.get('run'), dict) else {})
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
        if os.environ.get('AGENT_RUNNER_BACKEND') == 'pi':
            raise SystemExit(f'agent-runner: AGENT_RUNNER_BACKEND=pi: {PI_GONE}')
        raw = {**raw, 'run': supplied}
        given_models = dict(raw['models']) if isinstance(raw.get('models'), dict) else {}
        self.raw = {k: {**v, **raw.get(k, {})} for k, v in DEFAULTS.items()}
        if self.raw['plan']['repo'] and 'dir' not in raw.get('plan', {}):
            self.raw['plan']['dir'] = str(self.home / 'plan')
        self.run = self.raw['run']
        self.run.update(FIXED)
        from agent_runner import working_branch  # F447b: a saved one waits for the run's next start
        self.raw['git']['master_branch'] = working_branch.in_force(root, self.run['notes'], self.raw['git']['master_branch'])
        if isinstance(self.run['remote_slots'], bool):
            self.warnings.append('[run] remote_slots is now "open" (a slot is listed once you open it) or "always"')
        self.run['remote_slots'] = slots_in_apps(self.run['remote_slots'], old_sessions(sessions))
        if not isinstance(self.run['include_task_id_in_commit'], bool):
            raise SystemExit('agent-runner: [run] include_task_id_in_commit must be a boolean')
        if problem := setting_problem('git', 'pr', self.raw['git']['pr']) or both_problem(self.raw) or \
                setting_problem('git', 'pr_max', self.raw['git']['pr_max']):  # F419, F420
            raise SystemExit(f'agent-runner: {problem}')
        for k in ('approve', 'approve_wait', 'approve_batch', 'approve_diff_lines', 'releases', 'split_files', 'auto_audit', 'audit_tokens'):  # F98, F193, F200b, F417
            if problem := setting_problem('run', k, self.run[k]):
                raise SystemExit(f'agent-runner: {problem}')
        if not (isinstance(self.run['remote'], bool) or self.run['remote'] == 'auto'):
            raise SystemExit(f"agent-runner: [run] remote must be 'auto', true or false, not {self.run['remote']!r}")
        if self.run['remote_slots'] not in ('open', 'always'):
            raise SystemExit(f"agent-runner: [run] remote_slots must be 'open' or 'always', not {self.run['remote_slots']!r}")
        if self.run['engine'] not in ('terminal', 'stream'):
            raise SystemExit(f"agent-runner: [run] engine must be 'terminal' or 'stream', not {self.run['engine']!r}")
        if self.run['silent'] == 'launch':  # C20: the quiet launch is gone (it never stopped the start push)
            self.run['silent'] = False
            self.warnings.append("[run] silent = 'launch' is gone (no setting stops a Remote Control session's start "
                                 'push), so it reads as false; set silent = true or false')
        if not isinstance(self.run['silent'], bool):
            raise SystemExit(f"agent-runner: [run] silent must be true or false, not {self.run['silent']!r}")
        if not isinstance(self.run['web'], bool):
            raise SystemExit(f"agent-runner: [run] web must be true or false, not {self.run['web']!r}")
        if self.run['web_open'] not in ('everywhere', 'here'):  # F454a
            raise SystemExit(f"agent-runner: [run] web_open must be 'everywhere' or 'here', not {self.run['web_open']!r}")
        if not isinstance(self.run['web_https'], bool):
            raise SystemExit(f"agent-runner: [run] web_https must be true or false, not {self.run['web_https']!r}")
        if not isinstance(self.run['web_port'], int) or isinstance(self.run['web_port'], bool) \
                or not 0 < self.run['web_port'] < 65536:
            raise SystemExit(f"agent-runner: [run] web_port must be a port number, not {self.run['web_port']!r}")
        from agent_runner.theme import NAMES as THEMES  # F69: the one theme table
        if self.raw['ui']['theme'] not in THEMES:
            raise SystemExit(f"agent-runner: [ui] theme must be one of {', '.join(THEMES)}, not "
                             f"{self.raw['ui']['theme']!r}")
        if problem := setting_problem('ui', 'chat_quiet', self.raw['ui']['chat_quiet']):  # F128
            raise SystemExit(f'agent-runner: {problem}')
        if problem := setting_problem('ui', 'trusted_networks', self.raw['ui']['trusted_networks']):  # F136
            raise SystemExit(f'agent-runner: {problem}')
        if problem := tools_problem(self.run['tools']):  # F168
            raise SystemExit(f'agent-runner: {problem}')
        if problem := checks_problem(self.run['checks']):  # F427a
            raise SystemExit(f'agent-runner: {problem}')
        self.run['backend'] = 'claude'  # not a setting: `slots.backend()` reads it; the only one since F106d
        self.models = self.resolve_models(given_models)
        self.loaded = copy.deepcopy(settled(self))  # F202a: what the files said

    @property
    def agent_problem(self) -> str:
        """B764b: why no session can start with this `[run] agent` on this machine, and the fix, in one line; '' when
        one can. Looked up each time: installing the program mends it too."""
        from agent_runner.claude_use import uses
        from agent_runner.config_settings import agent_problem
        return agent_problem(self.root, self.run['agent'], uses(self))

    def resolve_models(self, given: dict) -> dict:
        """F101: `[models]`, each role settled: a role the files set wins, else the default. `C.run['model']` and
        `C.run['fix_model']` are kept equal to `code` and `fix`, so code that reads them sees the role."""
        m, r = self.raw['models'], self.run
        # F106a: [models] local and [models.providers] are settings, not roles: kept apart from self.models
        self.models_local = m.pop('local', False)
        if not isinstance(self.models_local, bool):
            raise SystemExit(f'agent-runner: [models] local must be true or false, not {self.models_local!r}')
        self.providers = model_providers(m.pop('providers', {}))
        # F443: [models] provider takes every bare name (opus through [models.tiers]); one naming its own keeps it
        self.model_provider = model_provider(m.pop('provider', 'claude'), self.providers, self.models_local)
        self.tiers = model_tiers(m.pop('tiers', {}), self.providers)
        # F106g: [models] fallback, each entry settled as a role is (claude's a bare name)
        chain = m.pop('fallback', [])
        if not isinstance(chain, list) or not all(isinstance(v, str) and v for v in chain):
            raise SystemExit(f'agent-runner: [models] fallback is a list of "<provider>:<model>", not {chain!r}')
        self.fallback = [self.settle(v, '[models] fallback') for v in chain]
        for role, v in given.items():
            if role in DEFAULTS['models'] and role not in MODEL_SETTINGS \
                    and not (isinstance(v, str) or (v is False and role == 'docs')):
                raise SystemExit(f'agent-runner: [models] {role} must be a model name'
                                 + (' or false' if role == 'docs' else '') + f', not {v!r}')
        for role in DEFAULTS['models']:
            if role not in MODEL_SETTINGS:
                m[role] = given.get(role, DEFAULTS['models'][role])
        # F105: [models.kinds] laid over the defaults kind by kind
        kinds = given.get('kinds', {})
        if not isinstance(kinds, dict) or not all(isinstance(k, str) and isinstance(v, str) and v
                                                  for k, v in kinds.items()):
            raise SystemExit(f'agent-runner: [models.kinds] maps a kind to a model name (D = "sonnet"), not {kinds!r}')
        m['kinds'] = {**DEFAULTS['models']['kinds'], **kinds}
        sizes = given.get('sizes', {})  # F470: [models] sizes, simple or complex -> a model
        if not isinstance(sizes, dict) or not all(k in SIZES and isinstance(v, str) and v for k, v in sizes.items()):
            raise SystemExit(f'agent-runner: [models] sizes maps simple or complex to a model name '
                             f'(simple = "sonnet"), not {sizes!r}')
        m.pop('sizes', None)  # F470: a setting, kept apart from the roles as self.sizes
        self.sizes = {k: self.settle(v, f'[models.sizes] {k}') for k, v in sizes.items()}
        # F106a: each role as '<provider>:<model>'; claude's are kept as the bare name the agent takes, another
        # provider's as '<provider>:<model>' for the harness loop (F106c)
        refs = {f'[models] {role}': role for role in m if role != 'kinds' and isinstance(m[role], str)}
        refs.update({f'[models.kinds] {k}': k for k in m['kinds']})
        for where, key in refs.items():
            table = m['kinds'] if where.startswith('[models.kinds]') else m
            table[key] = self.settle(table[key], where)
        r['model'], r['fix_model'] = m['code'], m['fix']
        return m

    def settle(self, value: str, where: str = '[models]') -> str:
        """A model as given (a role, a kind, `--model`) as a session runs it (`claude_model`), a bare name on
        `[models] provider` (F443)."""
        return claude_model(on_provider(value, self.model_provider, self.tiers), self.providers, self.models_local,
                            where)

    def task_model(self, tid: str, own: str = '', size: str = '') -> str:
        """F105: the model a task's own session runs on: its own (`plan add --model`, `own`), else its size's in
        `[models] sizes` (F470, `size`: the task's `size:` field), else its kind's in
        `[models.kinds]` (the id's letters: 'P17a' is P), else `[models] code`."""
        if own:  # F106a: 'claude:<model>' runs as the bare name; F106c: another provider's as '<provider>:<model>'
            if own.partition(':')[0] not in (*PROVIDERS, *self.providers):
                own = on_provider(own, self.model_provider, self.tiers)  # F443: a bare name is the provider's
            provider, model = parse_model(own, self.providers, True, 'model') \
                if own.partition(':')[0] in (*PROVIDERS, *self.providers) else ('claude', own)
            return model if provider == 'claude' else f'{provider}:{model}'
        if size and (by_size := self.sizes.get(size)):
            return by_size
        kind = tid[:len(tid) - len(tid.lstrip('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'))]
        return (self.models.get('kinds') or {}).get(kind) or self.models['code']

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
    def no_push(self) -> bool:
        """F400: the no-push policy: this project's, or the one of the session this process runs in."""
        from agent_runner import no_push
        return bool(self.raw['git']['no_push']) or no_push.active()

    @property
    def push_remote(self) -> str | None:
        if self.no_push:
            return None
        v = self.raw['git']['push']
        return None if v is False else (str(v) if isinstance(v, str) else 'origin')

    @property
    def master_branch(self) -> str | None:
        value = self.raw['git']['master_branch']
        if not isinstance(value, str):
            raise SystemExit('the working branch ([git] master_branch) must be a branch name string (or empty for automatic discovery)')
        if value != value.strip():
            raise SystemExit('the working branch ([git] master_branch) must not have leading or trailing whitespace')
        return value or None

    @property
    def push_merge(self) -> bool:
        return bool(self.raw['git']['push_merge']) and bool(self.push_remote)

    @property
    def approve(self) -> bool:
        """F98: `[run] approve` with a push remote: only an approved pitch is pushed."""
        return bool(self.run['approve']) and bool(self.push_remote)

    @property
    def pr(self) -> bool:
        """F419: PR mode, `[git] pr`: a finished task is a pull request, and nothing merges or pushes the shared branch."""
        return bool(self.raw['git']['pr'])

    @property
    def pr_max(self) -> int:
        """F420: how many open pull requests keep a new task from starting; 0: no limit."""
        return self.raw['git']['pr_max']

    @property
    def land_edited(self) -> str:
        v = str(self.raw['git'].get('land_edited', 'wait')).lower()
        return v if v in ('wait', 'wip') else 'wait'


_LIVE: dict[Path, Config] = {}  # F202a: the run's own config, kept as one object when it is read again
_WAITING: dict[tuple[str, str], object] = {}  # F202a: what the run keeps for changed SETTING_NEXT keys


@cache
def _cfg(root: Path) -> Config:
    if c := _LIVE.get(root):
        return c
    live = next(iter(_LIVE.values()), None)
    try:
        c = Config(root)
        if live and (bad := _problem(live.loaded, c.loaded)):
            raise ValueError(bad)
    except (SystemExit, Exception):  # noqa: BLE001
        if not live:
            raise
        c = Config.__new__(Config)  # a worktree read while a file is bad: the run's settings, as the run itself keeps
        c.__dict__.update(live.__dict__, root=root)
    else:
        _keep(c, _WAITING)
    return c


def _problem(was: dict, now: dict) -> str:
    """Why a value of `now` that is not the one in `was` cannot be taken; '' for none."""
    from agent_runner.config_settings import setting_problem
    return next((p for (t, k), v in now.items() if (v != was[t, k] or type(v) is not type(was[t, k]))
                 and (p := setting_problem(t, k, v))), '')


def cfg(cwd: Path | str | None = None) -> Config:
    return _cfg(toplevel(cwd))


def finished_mark(slot: str | int | None = None, c: Config | None = None) -> Path | None:
    """The file a slot's successful `done` leaves (`AGENT_RUNNER_SLOT`); the slot clears it when it starts a task,
    and the stop waiter stops protecting the session's leftover background commands once it exists. `c` is the run's
    config (the run passes its own); left out, the one of the folder this runs in: code that clears a mark passes it,
    or a test's run, whose working directory is the real worktree, clears the real slot's (B172)."""
    slot = slot if slot is not None else os.environ.get('AGENT_RUNNER_SLOT')
    return (c or cfg()).notes(f'slot{slot}.finished') if slot not in (None, '') else None



# --- F202a: a run that is up reads its settings again ---------------------------------------------------------

def settings_print(root: Path) -> tuple:
    """What the settings files of main checkout `root` hold now (their bytes; None: no file), to see a change by."""
    env = os.environ.get('AGENT_RUNNER_CONFIG')
    out = []
    for f in (root / (env or 'runner.toml'), root / LOCAL):
        try:
            out.append(f.read_bytes())
        except OSError:
            out.append(None)
    return tuple(out)


def settled(c: Config) -> dict[tuple[str, str], object]:
    """Every setting as `c` runs on it."""
    out = {(t, k): c.raw[t].get(k) for t, keys in DEFAULTS.items() for k in keys}
    return {**out, ('models', 'local'): c.models_local, ('models', 'providers'): c.providers,
            ('models', 'fallback'): c.fallback, ('models', 'provider'): c.model_provider, ('models', 'tiers'): c.tiers,
            ('models', 'sizes'): c.sizes}


def _keep(c: Config, values: dict) -> None:
    for (t, k), v in values.items():
        c.raw[t][k] = c.loaded[t, k] = v


def read_again(c: Config) -> tuple[Config, dict, list]:
    """The settings files read again for a run on `c`, which is not changed (`reload` does): (the new config, the keys
    that change now as {(table, key): value}, the changed keys that wait for the next run). ValueError says why they
    cannot be taken: a file that does not parse, a bad value."""
    try:
        new = Config(c.root)
        for f in (new.file, new.local):
            for t, v in (_load(f) if f else {}).items():
                if t in DEFAULTS and not isinstance(v, dict):
                    raise ValueError(f'{f.name}: [{t}] is a table, not {v!r}')
    except tomllib.TOMLDecodeError as e:  # runner.local.toml's names its file itself
        raise ValueError(f'{config_file(c.root).name}: {e}') from None
    except SystemExit as e:
        raise ValueError(str(e).removeprefix('agent-runner: ')) from None
    except Exception as e:  # noqa: BLE001 - whatever a file holds, the run goes on with what it has
        raise ValueError(f'{type(e).__name__}: {e}') from None
    was, now = c.loaded, new.loaded
    changed = {k: v for k, v in now.items() if v != was[k] or type(v) is not type(was[k])}
    if problem := _problem(was, now):  # only of the changed ones: what the run started with it goes on with
        raise ValueError(problem)
    from agent_runner.claude_use import uses
    from agent_runner.config_settings import SETTING_NEXT, agent_missing
    if ('run', 'agent') in changed and uses(new) and (problem := agent_missing(c.root, new.run['agent'])):  # B764a: every session would fail
        raise ValueError(problem)
    waits = {k: c.raw[k[0]][k[1]] for k in changed if k in SETTING_NEXT}
    _keep(new, waits)
    for t, k in waits:
        (new.given.setdefault(t, set()).add if k in c.given.get(t, ()) else new.given.get(t, set()).discard)(k)
    if 'model_flag' in c.run:  # `run --model`
        new.run['model_flag'] = c.run['model_flag']
    return new, {k: v for k, v in changed.items() if k not in waits}, sorted(waits)


def reload(c: Config, new: Config, waits: list) -> None:
    """Take `new` (`read_again`) into `c` itself, so whoever holds `c` reads it; code that took `c.run` for what it is
    in the middle of keeps the old values."""
    _WAITING.clear()
    _WAITING.update({(t, k): new.raw[t][k] for t, k in waits})
    c.__dict__.update(new.__dict__)
    _LIVE.clear()
    _LIVE[c.root] = c
    _cfg.cache_clear()  # the worktrees' own


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


def claude_logins_file() -> Path:
    """F502: this machine's Claude logins (`run login claude --as NAME`), kept per machine, outside any project:
    `$AGENT_RUNNER_LOGINS` else ~/.config/agent-runner/claude-logins.json."""
    if p := os.environ.get('AGENT_RUNNER_LOGINS'):
        return Path(p)
    return Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'agent-runner' / 'claude-logins.json'


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


def __getattr__(name: str):
    """C61: the settings area lives in config_settings.py; `config.setting_edit` and the rest still resolve here."""
    from agent_runner import config_settings
    try:
        return getattr(config_settings, name)
    except AttributeError:
        raise AttributeError(f"module 'agent_runner.config' has no attribute {name!r}") from None
