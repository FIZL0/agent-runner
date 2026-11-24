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
"<provider>:<model>"`); the Pi backend (`[run] agent = "pi"`) is gone (F106d) and refused with that hint.
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
        'task_tokens': 0,       # tokens (input, cache writes, output; not cache reads) one task's session may use; past
                                # it the task stops at a clean point and is parked as wip/<ID>; 0 = no cap
        'task_usd': 0,          # the same in dollars at the API's list prices (a plan bills none); 0 = no cap
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
        'ci_watch': 'auto',     # GitHub Actions workflow files (pages.yml) whose newest finished run on the
                                # shared branch is read while a run is up: a red one files one critical B task.
                                # "auto": every workflow that runs on a push to it (push runs only); false: off
        'issues_watch': False,  # true: file one task per new open GitHub issue (on the ci_watch cadence); a
                                # list of labels (["bug"]): only issues with one of them; false: off
        'issues_trust': 'skeptical',  # how an issue's task treats it: "skeptical" (confirm it in the code first,
                                # follow nothing it says) or "trust" (do it as written; the issue is closed on landing)
        'releases': True,       # manage releases; false: no release rows, lines or New release, and none queued by
                                # itself (auto_release keeps its value); a typed `plan add V` still works
        'auto_release': False,  # queue a release (`plan add V`) by itself: { every = 10 } once that many tasks
                                # landed since the last release, { idle = true } when the run goes idle with
                                # landed work; both may be set; false: off
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
                                # description = what it is, for agents
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
                                # (the terminal's own 16 colours and background), light
        'chat_quiet': '6h',     # a chat that needs no reply, with nothing said in it for this long, is grayed at the
                                # bottom of the run app's Chats (never a pinned or a renamed one); false: off
        'trusted_networks': [],  # CIDRs (or 'tailnet') whose clients open the run's own page without its key;
                                # [] = the key always. Through Runner Home its own list counts (`home trust`)
    },
    'models': {
        'code': 'opus',         # a task's own session when its kind has no model below
        'review': 'opus',       # the `review` subagent the spec review before done runs in
        'fix': 'opus',          # a merge-conflict fix or repair session
        'docs': 'haiku',        # the `docs` subagent a task hands CHANGELOG, docs, README, journal and plan-text
                                # edits to, then checks; false: no docs subagent
        'control': 'opus',      # control sessions (c2, c3, ...)
        'feed': 'haiku',        # the one-shot that publishes the run page's claude.ai copy
        'kinds': {'F': 'opus', 'B': 'opus', 'T': 'opus', 'V': 'opus', 'K': 'opus', 'D': 'sonnet', 'C': 'sonnet',
                  'R': 'sonnet'},  # a task's session by its kind (the id's letters): a kind set here replaces
                                # only that kind; one not listed runs on `code`; `plan add --model` wins for a task
        'local': False,         # allow a local provider (ollama, or a provider url on localhost or a private
                                # address) in a role; off, a role naming one is refused
        'providers': {},        # the repo's own providers, [models.providers.<name>]: kind = "openai" or
                                # "anthropic" (a compatible API), url, key_env (the env var holding its key, never
                                # the key itself); a role names one as "<name>:<model>"
        'fallback': [],         # F106g: a list of '<provider>:<model>' a task goes on with when its provider
                                # hits its cap (a Claude usage limit, a provider's quota error), in order; new
                                # tasks go back to their own model once the cap resets. Empty: a task waits
                                # for the reset
    },
}

# the providers a [models] role may name as '<provider>:<model>' without defining them; a bare name is claude's
PROVIDERS = ('claude', 'copilot', 'codex', 'gemini', 'ollama')
LOCAL_PROVIDERS = ('ollama',)
PROVIDER_KINDS = ('openai', 'anthropic')
# the [models] keys that are not roles
MODEL_SETTINGS = ('kinds', 'local', 'providers', 'fallback')

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
When: a run reads both files when it starts, so most keys apply on the next run (a run that is up keeps what
it read until it stops); `{cmd} slots N`, `pause` and `force` change the run that is up now.
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
    if head not in PROVIDERS and head not in providers:
        raise SystemExit(f'agent-runner: {where} = {value!r}: unknown provider {head!r}; use one of '
                         f'{", ".join([*PROVIDERS, *providers])}, or define it in [models.providers.{head}]')
    if not rest:
        raise SystemExit(f'agent-runner: {where} = {value!r}: no model after {head}:')
    if not local and (head in LOCAL_PROVIDERS or providers.get(head, {}).get('local')):
        raise SystemExit(f'agent-runner: {where} = {value!r}: {head} is a local provider, refused unless '
                         '[models] local = true')
    return head, rest


# F106c: the roles that run as Claude Code itself (its subagents, Remote Control's control sessions, the page
# copy's one-shot), so only on claude; a task's session (code, [models.kinds], plan add --model, run --model) and a fix
# session run on any provider, another than claude through the harness loop (agent_runner/harness.mjs)
CLAUDE_ONLY_ROLES = ('review', 'docs', 'control', 'feed')


def claude_model(value: str, providers: dict[str, dict] | None = None, local: bool = False,
                 where: str = '[models]', claude_only: bool = False) -> str:
    """`parse_model`, then the model as a session runs it: claude's as the bare name ('opus'), another
    provider's as '<provider>:<model>', which the harness loop runs (F106c). With `claude_only` (a role in
    CLAUDE_ONLY_ROLES) another provider is refused (SystemExit), saying why."""
    provider, model = parse_model(value, providers, local, where)
    if provider == 'claude':
        return model
    if claude_only:
        raise SystemExit(f'agent-runner: {where} = {value!r}: this role runs as Claude Code itself (a subagent, a '
                         'control session or the page copy), so only a claude model; the harness loop runs the '
                         f'{provider} provider for task and fix sessions ([models] code, fix, [models.kinds])')
    return f'{provider}:{model}'


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
# added it to .git/info/exclude) and the runner changes a key only when you set it in the run app's Settings.
# Uncomment and edit; any key runner.toml takes works here, in the same tables.

# [run]
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
        if isinstance(self.run['remote_slots'], bool):
            self.warnings.append('[run] remote_slots is now "open" (a slot is listed once you open it) or "always"')
        self.run['remote_slots'] = slots_in_apps(self.run['remote_slots'], old_sessions(sessions))
        agent_stem = Path(str(self.run['agent']).replace('\\', '/')).stem.lower()
        if agent_stem == 'copilot':
            raise SystemExit('agent-runner: [run] agent = "copilot" is gone (GitHub Copilot CLI support was '
                             'removed); use the harness loop\'s copilot provider: [models] code = "copilot:<model>"')
        if agent_stem == 'pi':
            raise SystemExit(f'agent-runner: [run] agent = {self.run["agent"]!r}: {PI_GONE}')
        if not isinstance(self.run['include_task_id_in_commit'], bool):
            raise SystemExit('agent-runner: [run] include_task_id_in_commit must be a boolean')
        for k in ('approve', 'approve_wait', 'approve_batch', 'releases'):  # F98, F193
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
        self.run['backend'] = 'claude'  # not a setting: `slots.backend()` reads it; the only one since F106d
        self.models = self.resolve_models(given_models)

    def resolve_models(self, given: dict) -> dict:
        """F101: `[models]`, each role settled: a role the files set wins, else the default. `C.run['model']` and
        `C.run['fix_model']` are kept equal to `code` and `fix`, so code that reads them sees the role."""
        m, r = self.raw['models'], self.run
        # F106a: [models] local and [models.providers] are settings, not roles: kept apart from self.models
        self.models_local = m.pop('local', False)
        if not isinstance(self.models_local, bool):
            raise SystemExit(f'agent-runner: [models] local must be true or false, not {self.models_local!r}')
        self.providers = model_providers(m.pop('providers', {}))
        # F106g: [models] fallback, each entry settled as a role is (claude's a bare name)
        chain = m.pop('fallback', [])
        if not isinstance(chain, list) or not all(isinstance(v, str) and v for v in chain):
            raise SystemExit(f'agent-runner: [models] fallback is a list of "<provider>:<model>", not {chain!r}')
        self.fallback = [claude_model(v, self.providers, self.models_local, '[models] fallback') for v in chain]
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
        # F106a: each role as '<provider>:<model>'; claude's are kept as the bare name the agent takes, another
        # provider's as '<provider>:<model>' for the harness loop (F106c), but not in a Claude-only role
        refs = {f'[models] {role}': role for role in m if role != 'kinds' and isinstance(m[role], str)}
        refs.update({f'[models.kinds] {k}': k for k in m['kinds']})
        for where, key in refs.items():
            table = m['kinds'] if where.startswith('[models.kinds]') else m
            table[key] = claude_model(table[key], self.providers, self.models_local, where,
                                      claude_only=table is m and key in CLAUDE_ONLY_ROLES)
        r['model'], r['fix_model'] = m['code'], m['fix']
        return m

    def task_model(self, tid: str, own: str = '') -> str:
        """F105: the model a task's own session runs on: its own (`plan add --model`, `own`), else its kind's in
        `[models.kinds]` (the id's letters: 'P17a' is P), else `[models] code`."""
        if own:  # F106a: 'claude:<model>' runs as the bare name; F106c: another provider's as '<provider>:<model>'
            provider, model = parse_model(own, self.providers, True, 'model') \
                if own.partition(':')[0] in (*PROVIDERS, *self.providers) else ('claude', own)
            return model if provider == 'claude' else f'{provider}:{model}'
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
    def approve(self) -> bool:
        """F98: `[run] approve` with a push remote: only an approved pitch is pushed."""
        return bool(self.run['approve']) and bool(self.push_remote)

    @property
    def land_edited(self) -> str:
        v = str(self.raw['git'].get('land_edited', 'wait')).lower()
        return v if v in ('wait', 'wip') else 'wait'


@cache
def _cfg(root: Path) -> Config:
    return Config(root)


def cfg(cwd: Path | str | None = None) -> Config:
    return _cfg(toplevel(cwd))


def finished_mark(slot: str | int | None = None, c: Config | None = None) -> Path | None:
    """The file a slot's successful `done` leaves (`AGENT_RUNNER_SLOT`); the slot clears it when it starts a task,
    and the stop waiter stops protecting the session's leftover background commands once it exists. `c` is the run's
    config (the run passes its own); left out, the one of the folder this runs in: code that clears a mark passes it,
    or a test's run, whose working directory is the real worktree, clears the real slot's (B172)."""
    slot = slot if slot is not None else os.environ.get('AGENT_RUNNER_SLOT')
    return (c or cfg()).notes(f'slot{slot}.finished') if slot not in (None, '') else None


# --- F97: the settings, read and written by the run app's Settings view ---------------------------------------

# keys whose value is one of a few: the choices, the default's type aside
SETTING_CHOICES: dict[tuple[str, str], tuple] = {
    ('plan', 'journal_layout'): ('dated', 'id'),
    ('run', 'engine'): ('terminal', 'stream'),
    ('run', 'remote'): ('auto', True, False),
    ('run', 'remote_slots'): ('open', 'always'),
    ('run', 'grill'): ('ask', 'big', 'off'),
    ('run', 'voice_learn'): ('ask', 'off'),
    ('run', 'issues_trust'): ('skeptical', 'trust'),
    ('run', 'needs_order'): ('oldest', 'newest', 'plan'),
    ('git', 'land_edited'): ('wait', 'wip'),
}
# keys that take more than their default's type: the other types ('off': false, 'bool', 'number', 'text', 'list',
# 'table')
SETTING_ALSO: dict[tuple[str, str], tuple[str, ...]] = {
    ('plan', 'glossary'): ('off',), ('run', 'control_idle'): ('off',), ('run', 'control_ask'): ('off',), ('run', 'ci_watch'): ('off', 'list'),
    ('run', 'issues_watch'): ('list',), ('run', 'auto_release'): ('table',), ('run', 'proc_max_gb'): ('number',),
    ('git', 'push'): ('off',), ('ui', 'chat_quiet'): ('off',),
    ('models', 'docs'): ('off',), ('run', 'task_tokens'): ('float',), ('run', 'task_usd'): ('float',),
    ('run', 'weekly_max'): ('float',), ('run', 'session_max'): ('float',),
}
SETTING_DURATIONS = {('run', 'control_idle'), ('run', 'control_ask'), ('ui', 'chat_quiet')}
SETTING_NOW = {('run', 'slots')}  # a change reaches the run that is up (through `slots N`); the rest wait for the next


def setting_type(table: str, key: str) -> str:
    """The control a setting gets: 'choice', 'switch', 'number', 'list', 'table' or 'text'."""
    if setting_choices(table, key):
        return 'choice'
    v = DEFAULTS[table][key]
    if SETTING_ALSO.get((table, key)) == ('table',):
        return 'table'
    return ('switch' if isinstance(v, bool) and not SETTING_ALSO.get((table, key)) else
            'number' if isinstance(v, (int, float)) and not isinstance(v, bool) else
            'list' if isinstance(v, list) else 'table' if isinstance(v, dict) else 'text')


def setting_choices(table: str, key: str) -> tuple:
    if (table, key) == ('ui', 'theme'):
        from agent_runner.theme import NAMES
        return tuple(NAMES)
    return SETTING_CHOICES.get((table, key), ())


def setting_problem(table: str, key: str, v) -> str:
    """Why `v` cannot be `[table] key` ('' when it can): its type, its choices, its range."""
    if table not in DEFAULTS or key not in DEFAULTS[table]:
        return f'[{table}] {key} is not a setting'
    where, d, also = f'[{table}] {key}', DEFAULTS[table][key], SETTING_ALSO.get((table, key), ())
    if choices := setting_choices(table, key):
        ok = any(v == c and isinstance(v, bool) == isinstance(c, bool) for c in choices)
        return '' if ok else f'{where} must be one of {", ".join(_toml_value(c) for c in choices)}, not {v!r}'
    num = isinstance(v, (int, float)) and not isinstance(v, bool)
    ok = (isinstance(v, bool) if isinstance(d, bool) else
          isinstance(v, int) and not isinstance(v, bool) if isinstance(d, int) else
          isinstance(v, str) if isinstance(d, str) else
          isinstance(v, list) and all(isinstance(x, str) for x in v) if isinstance(d, list) else isinstance(v, dict))
    ok = ok or (v is False and 'off' in also) or (num and ('number' in also or 'float' in also)) \
        or (isinstance(v, str) and 'text' in also) or (isinstance(v, dict) and 'table' in also) \
        or (isinstance(v, list) and 'list' in also and all(isinstance(x, str) for x in v))
    if not ok:
        kind = {'switch': 'true or false', 'number': 'a whole number', 'list': 'a list of words',
                'table': 'a table'}.get(setting_type(table, key), 'text')
        return f'{where} must be {kind}{" or false" if "off" in also else ""}, not {v!r}'
    if (table, key) == ('run', 'tools') and (problem := tools_problem(v)):  # F168
        return problem
    if (table, key) == ('ui', 'trusted_networks'):  # F136
        from agent_runner.trust import network_problem
        if problem := next((p for x in v if (p := network_problem(x))), ''):
            return f'{where}: {problem}'
    if num and v < 0:
        return f'{where} cannot be below 0, not {v!r}'
    if (table, key) == ('run', 'slots') and v < 1:
        return f'{where} must be at least 1, not {v!r}'
    if (table, key) == ('run', 'web_port') and not 0 < v < 65536:
        return f'{where} must be a port number, not {v!r}'
    if (table, key) in SETTING_DURATIONS and isinstance(v, str):
        import re
        if not re.fullmatch(r'\s*\d+(?:\.\d+)?\s*[smhd]?\s*', v):
            return f'{where} must be a time like "6h" or "30m", or false, not {v!r}'
    return ''


def tools_problem(v) -> str:
    """F168: why `v` cannot be `[run] tools` ('' when it can): {name: {check, label, connect, description}}, all text."""
    import re
    if not isinstance(v, dict):
        return f'[run] tools is a table of shared tools ([run.tools.iphone15]), not {v!r}'
    for name, t in v.items():
        where = f'[run.tools.{name}]'
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', str(name)):
            return f'{where}: a name is letters, digits, - and _ (iphone15)'
        if name == 'memory':
            return f'{where}: memory is built in (`run wait-for memory`); name the tool otherwise'
        if not isinstance(t, dict) or not isinstance(t.get('check'), str) or not t['check'].strip():
            return f'{where} needs check, the command that says whether it is free'
        if bad := [k for k in t if k not in ('check', 'label', 'connect', 'description')]:
            return f'{where}: {bad[0]} is not one of check, label, connect, description'
        if bad := [k for k, x in t.items() if not isinstance(x, str)]:
            return f'{where}: {bad[0]} must be text'
    return ''


def toml_value(v) -> str:
    """`v` as TOML source for one line (strings as written, not \\u escapes)."""
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, list):
        return '[' + ', '.join(toml_value(x) for x in v) + ']'
    if isinstance(v, dict):
        return '{ ' + ', '.join(f'{json.dumps(str(k), ensure_ascii=False)} = {toml_value(x)}'
                                for k, x in v.items()) + ' }' if v else '{}'
    return _toml_value(v)


def _toml_span(lines: list[str], i: int) -> int:
    """How many of `lines` the key at `i` takes (a list or string over several lines), 0 when it never parses."""
    for n in range(1, len(lines) - i + 1):
        try:
            tomllib.loads('\n'.join(lines[i:i + n]))
            return n
        except tomllib.TOMLDecodeError:
            continue
    return 0


def _toml_comment(line: str) -> str:
    """The comment that ends a `key = value` (with the spaces before it), '' for none."""
    at = line.find('#')
    while at >= 0:
        head = line[:at]
        try:
            tomllib.loads(head)
            return head[len(head.rstrip()):] + line[at:]
        except tomllib.TOMLDecodeError:
            at = line.find('#', at + 1)
    return ''


def _toml_inner(lines: list[str]) -> list[str]:
    """The comments inside a value over several `lines` (not the one that ends it), as lines of their own."""
    out = []
    want = tomllib.loads('\n'.join(lines))
    for i, l in enumerate(lines[:-1]):
        at = l.find('#')
        while at >= 0:
            try:
                if tomllib.loads('\n'.join([*lines[:i], l[:at], *lines[i + 1:]])) == want:
                    out.append(l[at:].strip())
                    break
            except tomllib.TOMLDecodeError:
                pass
            at = l.find('#', at + 1)
    return out


def toml_edit(text: str, table: str, key: str, value=None, unset: bool = False) -> str:
    """F97: `text` (a settings file) with `[table] key` set to `value` (`unset`: taken out), every other line
    and comment as it was. ValueError when it cannot be done on its own line (a key written as a [table.key]
    section, an inline table); the result is read back, and only that key may differ."""
    import re
    before = tomllib.loads(text)
    wrapped = isinstance(before.get('agent-runner'), dict)
    name = f'agent-runner.{table}' if wrapped else table
    lines = text.split('\n')
    # real headers and keys only: not a look-alike inside a multi-line string, which parses as no prefix
    head = re.compile(r'\s*\[\s*' + r'\s*\.\s*'.join(f'["\']?{re.escape(p)}["\']?' for p in name.split('.'))
                      + r'\s*\]\s*(#.*)?$')
    any_head = re.compile(r'\s*\[')
    key_re = re.compile(rf'\s*["\']?{re.escape(key)}["\']?\s*=')
    i, at, end, where, last = 0, None, None, None, 0  # last: the line after the section's last key
    while i < len(lines):
        l = lines[i]
        if not l.strip() or l.lstrip().startswith('#'):
            i += 1
            continue
        if any_head.match(l):
            if at is not None and end is None:
                end = i
            if head.match(l):
                at, end, last = i, None, i + 1
            i += 1
            continue
        n = _toml_span(lines, i) or 1
        if at is not None and end is None and key_re.match(l):
            where = (i, n)
        i += n
        if at is not None and end is None:
            last = i
    if unset:
        if where is None:
            return text if key not in _table_of(before, table, wrapped) else _toml_refuse(table, key)
        lines[where[0]:where[0] + where[1]] = _toml_inner(lines[where[0]:where[0] + where[1]])
    else:
        new = f'{key} = {toml_value(value)}'
        if where is not None:
            old = lines[where[0]]
            indent = old[:len(old) - len(old.lstrip())]
            was = lines[where[0]:where[0] + where[1]]
            lines[where[0]:where[0] + where[1]] = [indent + c for c in _toml_inner(was)] + [
                indent + new + _toml_comment('\n'.join(was))]
        elif at is not None:
            lines[last:last] = [new]
        else:
            while lines and not lines[-1].strip():
                lines.pop()
            lines += ([''] if lines else []) + [f'[{name}]', new, '']
    out = '\n'.join(lines)
    try:
        after = tomllib.loads(out)
    except tomllib.TOMLDecodeError:
        return _toml_refuse(table, key)
    want = json.loads(json.dumps(before, default=str))
    t = want.setdefault('agent-runner', {}).setdefault(table, {}) if wrapped else want.setdefault(table, {})
    if not isinstance(t, dict):
        return _toml_refuse(table, key)
    if unset:
        t.pop(key, None)
    else:
        t[key] = value
    if json.loads(json.dumps(after, default=str)) != json.loads(json.dumps(want, default=str)):
        return _toml_refuse(table, key)
    return out


def _table_of(raw: dict, table: str, wrapped: bool) -> dict:
    t = (raw.get('agent-runner') or {}).get(table) if wrapped else raw.get(table)
    return t if isinstance(t, dict) else {}


def _toml_refuse(table: str, key: str) -> str:
    raise ValueError(f'[{table}] {key} is not on a line of its own in {LOCAL}: change it there by hand')


def local_settings_file(root: Path) -> Path:
    return local_file(root) or main_checkout(root) / LOCAL


def setting_check(root: Path, table: str, key: str, v) -> str:
    """`setting_problem`, and for [models] whether each model named is one the runner takes ('' when all is well)."""
    if (problem := setting_problem(table, key, v)) or table != 'models':
        return problem
    snap = {(t['table'], k['key']): k['value'] for t in settings_snapshot(root)['tables'] for k in t['keys']}
    snap[(table, key)] = v
    try:
        providers, local = model_providers(snap['models', 'providers']), bool(snap['models', 'local'])
        named = v.values() if key == 'kinds' else v if key == 'fallback' else \
            [v] if key not in MODEL_SETTINGS and isinstance(v, str) else []
        for m in named:
            if not isinstance(m, str) or not m:
                return f'[models] {key}: {m!r} is not a model name'
            claude_model(m, providers, local, f'[models] {key}',
                         claude_only=key in CLAUDE_ONLY_ROLES)
    except SystemExit as e:
        return str(e).removeprefix('agent-runner: ')
    return ''


def setting_edit(data: bytes, table: str, key: str, value=None, unset: bool = False, name: str = LOCAL) -> bytes:
    """A settings file's bytes with one key set (or `unset`), its comments and line ends kept. An old key that still
    sets this one goes with it (F166). ValueError says why not; `name` is the file it names."""
    raw = data.decode('utf-8')
    crlf = '\r\n' in raw
    try:
        out = toml_edit(raw.replace('\r\n', '\n'), table, key, value, unset)
        for (t, k), (nt, nk, _, _) in MOVED.items():
            got = tomllib.loads(out)
            got = got['agent-runner'] if isinstance(got.get('agent-runner'), dict) else got
            if (nt, nk) == (table, key) and isinstance(got.get(t), dict) and k in got[t]:
                out = toml_edit(out, t, k, unset=True)
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f'{name} does not read as TOML ({e}): fix it there first') from None
    except ValueError as e:
        raise ValueError(str(e).replace(LOCAL, name)) from None
    return (out.replace('\n', '\r\n') if crlf else out).encode('utf-8')


def save_local_setting(root: Path, table: str, key: str, value=None, unset: bool = False) -> Path:
    """F97: set (or `unset`) one key in this machine's runner.local.toml, in place; ValueError says why not."""
    if problem := ('' if unset else setting_check(root, table, key, value)):
        raise ValueError(problem)
    if unset and (table not in DEFAULTS or key not in DEFAULTS[table]):
        raise ValueError(f'[{table}] {key} is not a setting')
    f = local_settings_file(root)
    if not f.exists():
        if unset:
            return f
        ensure_local(f.parent)
    f = f.resolve()
    out = setting_edit(f.read_bytes(), table, key, value, unset, f.name)
    tmp = f.with_name(f.name + '.tmp')
    tmp.write_bytes(out)
    os.chmod(tmp, f.stat().st_mode & 0o777)
    os.replace(tmp, f)
    keep_local_ignored(f.parent)
    return f


def _table_for(key: str) -> str:
    """The table line a key written at the top of a file misses."""
    return next((f'[{t}]' for t, keys in DEFAULTS.items() if key in keys), '[table]')


def settings_snapshot(root: Path) -> dict:
    """F97: every setting for the run app's Settings view, read from the files now: {'ok', 'project', 'device' (the
    two files' names), 'tables': [{'table', 'keys': [...]}], 'unknown': [...]}. A key: its type, choices, default,
    help, its value in each file (`project`, `device`, with `has_…`), the one in force (`value`), where that comes from
    (`source`: 'device', 'project' or 'default') and when a change applies (`applies`: 'now' or 'next run')."""
    raws, errors = {}, []
    files = {'project': config_file(root), 'device': local_file(root)}
    for side, f in files.items():
        try:
            raws[side] = _load(f) if f else {}
        except (OSError, tomllib.TOMLDecodeError) as e:
            raws[side] = {}
            errors.append(f'{f.name}: {e}')
    unknown = []
    for side, f in files.items():
        for t, keys in raws[side].items():
            gone = {k for (tt, k) in (*REMOVED, *MOVED) if tt == t}
            if not isinstance(keys, dict) or (t not in DEFAULTS and not gone):
                if f.name in ('runner.toml', LOCAL) and not (isinstance(keys, dict) and keys.get('agent-runner')):
                    unknown.append({'table': t if isinstance(keys, dict) else '', 'key': '' if isinstance(keys, dict) else t,
                                    'value': toml_value(keys), 'file': f.name, 'side': side,
                                    'why': f'[{t}] is not a table the runner reads, ignored' if isinstance(keys, dict)
                                    else f'no {_table_for(t)} line is above it, ignored'})
                continue
            for k, v in keys.items():
                if k in DEFAULTS.get(t, {}) or (t not in DEFAULTS and k not in gone):
                    continue
                said = migrate({t: {k: v}}, f.name)
                unknown.append({'table': t, 'key': k, 'value': toml_value(v), 'file': f.name, 'side': side,
                                'why': said[0].partition(': ')[2] if said else 'not a setting'})
    sessions = old_sessions([raws[side] for side in files])
    for side in files:
        move_keys(raws[side])
    from agent_runner import setting_words as W
    tables = []
    for t, keys in DEFAULTS.items():
        rows = []
        for k, d in keys.items():
            row = {'key': k, 'type': setting_type(t, k), 'choices': list(setting_choices(t, k)), 'default': d,
                   'off': 'off' in SETTING_ALSO.get((t, k), ()), 'also': list(SETTING_ALSO.get((t, k), ())),
                   'name': W.name(t, k), 'desc': W.desc(t, k), 'group': W.group(t, k), 'home': W.home(t, k),
                   'parent': W.parent(t, k), 'words': W.words(t, k), 'parts': W.parts(t, k), 'unit': W.unit(t, k), 'order': W.order(t, k),
                   'applies': 'now' if (t, k) in SETTING_NOW else 'next run', 'value': d, 'source': 'default'}
            for side in ('project', 'device'):
                have = raws[side].get(t)
                row[f'has_{side}'] = isinstance(have, dict) and k in have
                if row[f'has_{side}']:
                    row[side] = slots_in_apps(have[k], sessions) if (t, k) == ('run', 'remote_slots') else have[k]
                    row['value'] = {**d, **have[k]} if (t, k) == ('models', 'kinds') and isinstance(have[k], dict) \
                        else row[side]
                    row['source'] = side
            rows.append(row)
        tables.append({'table': t, 'keys': rows})
    return {'ok': not errors, 'out': '; '.join(errors), 'tables': tables, 'unknown': unknown,
            'groups': [list(g) for g in W.GROUPS],
            'project': files['project'].name if files['project'] else 'runner.toml',
            'device': files['device'].name if files['device'] else LOCAL}


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
