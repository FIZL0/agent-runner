# Setting it up

How to install agent-runner, add it to a repo, keep a project's own CLI for its tools, move a repo that has its
own copy over to it, and what a version number promises.

- [Installing](#installing)
- [Other providers](#other-providers)
- [Provider logins: run login](#provider-logins-run-login)
- [A new repo from scratch](#a-new-repo-from-scratch)
- [Your own CLI for tools only](#your-own-cli-for-tools-only)
- [Migrating a repo that carries its own copy](#migrating-a-repo-that-carries-its-own-copy)
- [Worktrees: why a global install](#worktrees-why-a-global-install)
- [Versions](#versions)

## Installing

It is stdlib-only Python 3.11+, so it installs as a plain tool with nothing beside it.

```sh
uv tool install git+https://github.com/FIZL0/agent-runner
# or
pipx install git+https://github.com/FIZL0/agent-runner

agent-runner --version          # agent-runner 0.6.18
```

That puts `agent-runner` on your PATH. It is the same CLI as `./run` in a clone: `agent-runner plan`,
`agent-runner done`, `agent-runner run`, `agent-runner stop`. `python3 -m agent_runner` works too.

**Windows:** Python 3.11+ from python.org (not the Store's `python3` alias), Git for Windows (Claude Code runs hooks and
Bash calls in its Git Bash). Each slot runs hidden: in a ConPTY pseudo-console with no window (Windows 10 1809 and
later), or before that in a console whose window starts hidden. Run `agent-runner run 3` from any terminal;
`agent-runner attach s2` puts this terminal on the session's own (1809 and later; Ctrl-b d leaves it running), and
`winget install tsl0922.ttyd` is what lets the run page show sessions, and `agent-runner setup` offers to run it.

**Linux and macOS** need nothing more for the run (it uses no tmux). The slots run hidden, in a
pseudo-terminal with no window, their output in `.runner/slotN.log`. `agent-runner attach` is the run view
(its log, live, and its keys), `agent-runner attach s2` puts this terminal on slot 2's own terminal (Ctrl-b d
leaves it running), and `status`, `ui`, control sessions and `plan tell` watch and steer them.
`[run] links` need no Developer Mode: without it they become junctions and hard links. The run page needs ttyd to show
sessions, and `agent-runner setup` offers to install it. See the reference's
[Terminals, and Windows](REFERENCE.md#terminals-and-windows).

**Latest, or a tag.** Without `@…` it installs `main`, which is always the latest release (every commit
there is one). To hold a machine at a version, name its tag instead: `…/agent-runner@v0.6.18`.

**Upgrade every repo at once.** There is one install per machine, so one command upgrades every repo
that uses it:

```sh
uv tool upgrade agent-runner
pipx upgrade agent-runner
```

Both fetch `main` again (a tag install stays on its tag). A run says when `main` has a newer version and
which of these to type. A run up at the time restarts itself on the new version (with `[run] auto_upgrade` on, the default) once no merge is going,
and adopts its sessions, merges and gates like any restart. It does not on Windows, nor across a major
version: read [CHANGELOG.md](../CHANGELOG.md) and restart it yourself, as a new major version may rename a config key.

**Roll back** the same way, naming the older tag: `uv tool install --force …@v0.2.0`.

**From a clone,** for hacking on the runner itself: `git clone https://github.com/FIZL0/agent-runner`
and call `~/agent-runner/run …`. A clone needs no install. `uv tool install --editable ~/agent-runner`
makes the `agent-runner` command run the clone's code.

## Other providers

Claude Code is the default and needs nothing here. To run a task's session on another provider (GitHub Copilot,
enterprise Copilot, Codex, Gemini, Ollama, or your own `[models.providers.<name>]`), name its model in `[models]` as
`<provider>:<model>`:

```toml
[models]
code = "copilot:<model>"  # a model your account lists; a bare name or claude:<model> stays on Claude Code
```

`[models] control` can name a provider too; a control session on it then runs on the harness loop as well.

To move everything at once, set the provider for every model written as a bare name (Provider, the first row of
Models in the run app's Settings, does the same):

```toml
[models]
provider = "copilot"      # opus, sonnet and haiku become Copilot's (see [models.tiers] in REFERENCE.md)
code = "claude:opus"      # a model that names its provider keeps it
```

The session runs on the [harness loop](REFERENCE.md#the-harness-loop), a Node program that needs Node.js 22 or later
on PATH. Log in once with `agent-runner login copilot` (for enterprise Copilot, `--enterprise company.ghe.com`; see
[Provider logins](#provider-logins-run-login)). `agent-runner login` with no argument lists the providers the repo
names and whether each has a login. `agent-runner setup` asks for this too, and writes the model for the provider you pick (see [A new repo from scratch](#a-new-repo-from-scratch)).

`NODE_USE_SYSTEM_CA=1` uses the OS certificate trust store for corporate TLS interception; it requires Node.js
22.19+ and does not disable certificate verification. Set it in the environment before starting the run if Node
reports an issuer-certificate error.

From a clone on Windows, use `python -m agent_runner run once`; an installed runner uses
`agent-runner run once`. Normal terminal selection, parallel worktrees, `done`, test gates, and merging
are unchanged.

### With no Claude Code at all

A project needs no Claude Code when no session can run on it. That is when every one of these names another
provider: `[models] code`, `review`, `fix`, `control` and `feed`; every kind in `[models.kinds]`;
and the model given to `run --model`. `[models] docs` does not count: it is a
subagent of a Claude Code task session, so with none it never runs. A Claude entry in `[models] fallback` counts only
while Claude Code is on the machine; a cap passes over it otherwise. If any of the others is left on its
default (opus, sonnet or haiku), the project still needs Claude Code, and a missing `claude` holds new
sessions as before.

```toml
[models]
code = "codex:<model>"
fix = "codex:<model>"
review = "codex:<model>"
control = "codex:<model>"
feed = "codex:<model>"
kinds = { F = "codex:<model>", B = "codex:<model>", T = "codex:<model>", V = "codex:<model>", K = "codex:<model>", D = "codex:<model>", C = "codex:<model>", R = "codex:<model>" }
```

Then there is no missing-`[run] agent` line or hold. The run also shows no Claude login line (in status, on the
run page, on Home, or as a push), reads no usage and applies no cap (`session_max`, `weekly_max`), makes no API
check and has no headroom usage limit, except for a task on a claude model that waits to start (below). A removed
value such as `agent = "pi"` is still said.

A task given its own Claude model (`plan add --model opus`) still waits alone, blocked under Needs you, when
Claude Code is not on the machine. With Claude Code on the machine, such a task does not start past `session_max`
or `weekly_max` (it alone waits, or starts on the first free `[models] fallback` provider), and waits alone while
the Claude API is unreachable, unless the cap moves it to such a provider. Other tasks start as before. When nothing else can start, the alarm names the held task
and says it cannot start until the reset; `force` lifts the cap. The usage and the API are read only while such
a task is waiting to start.

## Provider logins: run login

`run login` gives a provider its login. It serves a role in `[models]` that names a provider other than claude,
such as `copilot:gpt-x`; those sessions run on the [harness loop](REFERENCE.md#the-harness-loop). Its logins are kept
in Pi's own `auth.json`, the login package's store. It needs Node on PATH.

From the repo's folder, `agent-runner login` (or `./run login`) with no argument lists each provider that
`[models]` names (its roles, `[models.kinds]` and `[models.providers]`), with where its login is kept. It
never prints the secret:

```
copilot  ✓ OAuth in /home/you/.pi/agent/auth.json (github-copilot, GitHub Enterprise corp.ghe.com)
claude   ✓ Claude Code's own login (claude /login), not checked here
gemini   ✗ no login: agent-runner login gemini
acme     ✓ env ACME_KEY
lab      ✓ needs none (a local model)
```

`agent-runner login <provider>` adds one, through Pi's login package (`@earendil-works/pi-ai`, installed once
by the harness loop into `~/.cache/agent-runner`):

- **copilot** shows a GitHub device code: open the URL it prints and enter the code. It first asks
  "GitHub Enterprise domain (blank for github.com)"; `--enterprise company.ghe.com` answers that (the domain may also be written `https://company.ghe.com/`, trimmed to the host), and
  `--enterprise ""` means github.com.
- **codex** signs in with ChatGPT, in a browser page.
- **gemini** asks for a Gemini API key (hidden input). `GEMINI_API_KEY` in the environment counts as its login.
- **a custom provider** from `[models.providers.<name>]` with `key_env` asks for its key and stores it under
  the provider's name. The harness loop uses the stored key before the `key_env` variable; that variable set
  in the environment also counts as a login.
- **claude** runs on Claude Code's own login (`claude /login`). **ollama**, and a local custom provider
  without `key_env`, need none.

Every login lands in Pi's `auth.json` (`$PI_CODING_AGENT_DIR`, else `~/.pi/agent/auth.json`), mode 0600.

When a task's session would run on a provider with no login, the run does not start it. It blocks the task
with ``BLOCKED: `agent-runner login <provider>` `` so it lists under Needs you.
Running that login on the run's machine reopens the tasks it held back: it unblocks them in the plan.

## A new repo from scratch

The short way is `agent-runner setup` in the repo's folder (a folder with no git becomes a repository):

1. It saves what is there: uncommitted edits and untracked files are committed to a new branch,
   `runner-setup-backup-<date>` (`-2`, `-3` … when one exists), and it prints the name. Your checkout, its
   index and its branch are not changed: the files stay uncommitted where they are.
2. It writes `runner.toml` when there is none, with the gate guessed from `package.json`, `Cargo.toml`,
   `go.mod`, a Makefile `test`/`check` target or a `tests/` folder. An existing one is left as it is, except for step 5's answer.
3. When ttyd is not found, it asks in one line to install it, naming this machine's command, before the
   Claude session. The run page needs ttyd to show sessions. Yes runs the command in
   this terminal. On no, with no terminal or no package manager, or when the install fails, it says the command
   or what failed and goes on. It asks also on a repo already set up, and `--yes` does not answer it.
4. At a terminal it asks which providers to use. It lists Claude Code, GitHub Copilot, Codex, Gemini and
   Ollama, each with whether it is found (Claude Code, Ollama) and whether it is logged in. Pick by number or name, several at
   once if you like; Enter changes nothing. Each pick that is not logged in is logged in there:
   `claude auth login` for Claude Code, `agent-runner login PROVIDER` for the others. Copilot first asks for
   a GitHub Enterprise domain (blank for github.com); one already logged in can log in again, on another domain.
   The first pick runs the tasks. Its model goes to
   `[models] code` and `fix` in `runner.local.toml`. With no Claude Code here, the pick also takes `review`,
   `control`, `feed` and `docs` where those were on Claude. Claude Code needs no model id; another provider asks for
   one, and Ollama also sets `local = true`. A kind in `[models.kinds]` on another provider moves to the
   pick too, because a kind wins over `code`. A failed login is said, and the models are still written: the pick's tasks wait for the login. With no terminal it
   asks nothing and prints the login commands. `--yes` does not answer it.
5. At a terminal it asks once who can reach the run page: `Who can reach the run page: other devices too (default) or only
   this machine? [Everywhere/here]`. Enter takes the default, everywhere; `here` keeps the page on this machine; any
   other answer asks again.
   The answer goes to `[run] web_open` in runner.local.toml (this machine only), so it is not asked again, nor
   when `web_open` is set already. Ctrl-C or Ctrl-D writes nothing and goes on; with no terminal it is not asked.
   Settings > Run page opens on changes it later, from the next run.
6. At a terminal it asks once whether the run audits by itself, `Audit by itself … [y/N]`, default no. Yes writes
   `auto_audit = { every = 50 }` to the project's settings file (runner.toml), no writes `auto_audit = false`, so it
   is not asked again. It is not asked when `auto_audit` is already set in runner.toml or runner.local.toml. Ctrl-C
   or Ctrl-D writes nothing and goes on. With no terminal it is not asked, and `--yes` does not answer it.
7. It starts one full Claude session in the repo (your normal tools, settings and CLAUDE.md, not a slot's
   lean brief) that reads the repo, checks the gate, writes the goal and a first task list with
   `agent-runner plan goal` and `plan add`, adds a short `## Agent notes` section to CLAUDE.md or AGENTS.md,
   and commits it all. With no Claude Code here, setup does not fail. If no role or kind needs Claude
   Code, the session runs on the harness loop instead, in chat mode on `[models] control` (Ctrl-D ends it). That
   needs Node.js and the provider's login; if either is missing, setup says so in one line and starts no session.
   If a role still needs Claude Code, setup says in one line what cannot run yet (the setup session, chats, spec
   reviews, tasks on a claude model) and starts no session.
8. It prints what it set up; `agent-runner` then opens the run picker, where `s` starts the run.

Run again on a repo that has a plan, it asks before the session touches it (`--yes`: go on without asking).

By hand:

```sh
cd your-repo
mkdir plan
```

**plan/TODO.md**, one line per task, in sections:

```markdown
## Now

- [ ] **A1** Add a --json flag to `report` · `src/report.py`, `tests/test_report.py`
- [ ] **A2** Cache the parsed config · `src/config.py` · after A1
```

The id is bold, the files after a `·` are what the task may touch (the run keeps two slots off the same
file), and `after X` holds a task until X is ticked. `plan/A1.md`, if present, is the long brief. See the
[reference](REFERENCE.md#the-task-list) for the full format.

**plan/DONE.md** can start empty; finished tasks move there.

**runner.toml** (every key is optional; see the [reference](REFERENCE.md#runnertoml)):

```toml
[run]
test = "make test"        # the gate: `done` and every merge run it
rules = "AGENTS.md"       # what every session reads first
notes = ".runner"

[git]
master_branch = "main"    # optional: explicit local shared branch; it must exist and be checked out
```

**AGENTS.md** (or CLAUDE.md): the repo's rules for an agent. It holds how to build and test, what not to
touch, and where things live. The runner's prompt already covers the task and the bookkeeping (the
brief, `done`, `--blocked`), so this file is only about the repo.

Git-ignore the notes folder, commit the rest, then try one task before a full run:

```sh
echo .runner/ >> .gitignore
git add plan runner.toml AGENTS.md .gitignore && git commit -m "agent-runner plan"
agent-runner plan                 # what it sees
agent-runner plan brief A1        # what the session will be handed
agent-runner run --dry-run 3      # what three slots would start
agent-runner run once             # one task, one session; watch it
agent-runner run 3                # three slots, in this terminal (bare agent-runner: the picker, then s, in the background)
```

## Your own CLI for tools only

A project with its own CLI (`./kit`, `make`, `just`) keeps it for the project's tools, and runs agent-runner
directly: `agent-runner run`, `stop`, `plan`, `done`, `status` and the rest. The settings are the project's
committed `runner.toml` at the root, and every way of starting a run (the picker, the run page, a terminal)
finds the same settings. Nothing wraps agent-runner, so the CLI has no `done` or `plan` of its own.

`AGENT_RUNNER_CONFIG=<file>` still works for a project that keeps its settings in another file: that file is
read in place of `runner.toml`.

The sessions finish with agent-runner's `done`, as in any repo. What a kit used to do around `done` (the audit
first, a custom conflict join, a program per slot) is a setting now: see the hooks below.

### The hooks a project can set

| hook | what it does |
|---|---|
| `[run] test` | the gate run by `done` and after every merge |
| `[run] done_test` | a command `done` runs before its commit in place of `test`, on a docs-only diff too (a build, an audit); a merge still runs `test` / `test_since`, and `--no-test` skips it |
| `[run.join]` | `"glob" = "command"`: the project joins a conflict in that file itself. `{ours} {base} {theirs} {union} {out} {file}`; exit 0 keeps `{out}`, non-zero sends it to a fix session |
| `[run] suspect` | a regex; a `BLOCKED` line a merge adds to the plan that matches it is flagged `SUSPECT, recheck` in the ledger |
| `[run] slot_env` | `NAME=value` per slot, with `{n}` (slot) and `{slots}` (how many) |
| `[run] pass_env` | names of the runner's environment variables handed on to every slot |
| `[run] on_exit` | a command run in the slot's worktree, with the slot's env, when its session ends (both parallel and `once`), also when a drop, `plan change --restart`, a take back, a cancel or `s!` stops it (with `s!` it runs detached: the run does not wait for it, and the next run holds the slot until it has ended, stopping it past `[run] command_timeout`); the slot starts nothing until it has ended |
| `[run] prompt_extra` | a paragraph added to the prompt; takes the prompt's placeholders (`{n}`, `{id}`, `{runner}`, …) |
| `[run] command` | what the prompt and the brief tell sessions to type |
| `[run] links` | git-ignored paths symlinked into every worktree |
| `[run] copies` | git-ignored files copied into each new worktree once (a local config) |
| `[plan] journal` | per-task journal folders; the newest entry goes into the brief |
| `[plan] brief_extra` | a command (`{id}`) whose output ends the brief |
| `[plan] outline` | a command (`{file}`) printing one file's outline, shown under each file the task line names over 300 lines; 2 KB for the whole brief |
| `[run] untested` | globs of files the gate can't see (`!glob` takes one back); a merge differing only in them isn't retested |
| `[run] failures`, `retest` | a regex naming failed tests in the gate output, and the gate for just `{names}`: rerun alone, then on the base |
| `[run] flaky` | a regex naming tests a *passing* gate passed only on its own rerun; each (and each `retest` pass) gets a critical T follow-up to make it robust |
| `[plan] kinds` | id prefix -> kind of work; listed in the prompt, and `plan add` refuses any other prefix |
| `[plan] glossary` | the project's glossary file (`GLOSSARY.md`): the first control session seeds it, sessions add terms with `agent-runner glossary add`, every brief names it; `false` = off (no file written, briefs skip it) |
| `[plan] need_files` | `plan add` refuses a line with no `files:` and no `test:` field (without it, a warning), so the run can keep it apart from the running tasks |
| `[run] before_start` | a check that must pass before any session starts |
| `[run] command_timeout` | seconds the gate, a retest, a `[run.join]` command, or `before_start` may run before it is stopped and counts as failed (3600) |
| `[run.tools.<name>]` | a shared tool, one task at a time (a test phone, a device): `check` exits 0 free, 75 busy (first line: the holder), 69 missing; optional `label`, `connect`, `description`, `page`, `start` and `buttons`. See [Shared tools](REFERENCE.md#shared-tools) |
| `[run.checks.<name>]` | a command a blocked task can wait on (an until check): exits 0 passed, 75 not yet, anything else cannot run, within 10 s; optional `label`. See [Until checks](REFERENCE.md#until-checks) |
| `[run] not_attempt` | a regex on the last commit subject (`{id}`): that session was a phase, not the run's one attempt |

The brief already holds the task line, `plan/tasks/<ID>.md`, the newest journal entry, and the git log of the
files the task names. `brief_extra` is for anything else.

### Worked example: a kit that keeps only its tools

This is how a kit such as ps2-decomp-kit would be set up. It is an example of the shape, not a record: the kit
has not been moved.

The kit's commands stay tools: `./kit extract`, `elf`, `ghidra`, `pcsx2`, `pine`, `oracle`, `check`, `audit`,
`journal`, `setup` and `doctor`. agent-runner does the run, the plan and the gate: `run`, `stop`, `plan`,
`done`, `status`, `control` and `take`. This committed `runner.toml` at the root sets it up:

```toml
# runner.toml (an example kit)
[plan]
dir = "plan"
journal = "research/journal"
need_files = true

[run]
test = "./kit check --all"
test_since = "./kit check --since {base}"
done_test = "./kit check --build && ./kit audit"   # done's check before each commit, docs-only diffs too
notes = "context/notes"
links = ["context", "*.iso"]
copies = ["kit.toml"]
slot_env = ["KIT_PCSX2={n}", "KIT_RUN=1"]
on_exit = "./kit pcsx2 stop"

[run.join]
"research/oracle.txt" = "./kit oracle join {union} {out}"

[git]
push = "origin"
push_merge = true
```

`done` runs `./kit check --build && ./kit audit` before each commit, so a session that only edits docs still gets
the audit. A merge runs `./kit check --all`, or `--since {base}` for what changed since a passing commit.
`KIT_PCSX2` and `KIT_RUN` reach each slot, and the slot's emulator is stopped when its session ends. The
`research/oracle.txt` address lists are joined by the kit's own subcommand, which exits 1 on a clash.

### Worked example: opentennis

opentennis runs `agent-runner run` directly, with this `runner.toml` and no wrapper script.
Conflicts go to a fix session each, and merges never stash the main checkout.

```toml
# runner.toml (opentennis)
[plan]
dir = "plan"
journal = "research/journal"
brief_extra = "tools/cleanroom.py {id}"   # a spec/port phase; also writes the .cleanroom lock

[run]
test = "tools/check.sh"
slots = 5
weekly_max = 94
notes = "context/notes"
rules = "AGENT.md"
prompt = "tools/runner-prompt.md"   # sessions finish with tools/done.sh (audit, tests, --spec / --blocked)
links = ["context", "mods", "replacements", "*.iso"]
shared_files = ["play.rs"]
joinable = ["research/journal/*", "RELEASE_NOTES.md"]
slot_env = ["HST_PCSX2={n}", "HST_BG=1", "RUSTC_WRAPPER=sccache", "SCCACHE_CACHE_SIZE=60G"]
pass_env = ["HST_PCSX2_MAX_HOLD"]
on_exit = "tools/pcsx2.sh tools/pcsx2-hst.sh stop"
before_start = "ls /run/user/$(id -u)/wayland-[0-9]* >/dev/null 2>&1"   # PCSX2 needs a desktop session
untested = ["*.md", ".github/*", "tools/*", "!tools/check.sh"]
failures = '^---- (\S+) stdout ----'
retest = "tools/check.sh -- --exact {names}"
not_attempt = '^{id} spec:'        # a clean-room spec phase; its port phase starts once it merges
suspect = 'BLOCKED:.*(pcsx2|pine|capture|record|screenshot|save state|unattended)'
```

| `tools/parallel.py` | agent-runner |
|---|---|
| tmux `hst` panes, `HST_PCSX2=N` per slot, PCSX2 stopped when a session ends | `slot_env`, `on_exit` |
| no new tasks without a Wayland session (bell, log once) | `before_start` |
| the clean-room phase pasted into the prompt (and its `.cleanroom` lock) | `[plan] brief_extra` |
| `tested_by_cargo` | `untested` |
| net:: flakes rerun once; "already failing on main → merge anyway" | `failures` + `retest` |
| WAITING/LANDED batch merges | `batch_max` (on by default; 1 = none) |
| spec commits aren't an attempt | `not_attempt` |
| "(split into …)" parents wait, then tick themselves | built in |
| adopting running sessions after a restart; a slot held while an untracked session runs; one runner at a time | built in |
| the prompt through a file (a long command line is refused) | built in |
| master session stashing main around merges | gone: a merge worktree, then a fast-forward-or-merge into main that waits for a human's edits instead of stashing them |

What it gets that it didn't have: a fix session per conflict instead of one master that knows every
merge, `--after` reopening blocked tasks once their blocker lands, `wip/<ID>` parking pushed off the
disk, `run once` / `--dry-run`, and the tests.

## Migrating a repo that carries its own copy

openmx and ps2-decomp-kit each have their own runner (`tools/kit/run.py`, `plan.py`, `done.py`). Moving
one over:

1. **Install** a pinned tag (above).
2. **Move the settings into runner.toml.** Write the `[plan]`, `[run]` and `[git]` tables at the project root,
   taking each value from the old code: the gate, the slot env, the prompt paragraph (`prompt_extra`), the links,
   the notes folder. The hooks table above names the key for each.
3. **Move the special cases into settings.** The audit that ran before `done.main` becomes `done_test`; a custom
   join becomes a `[run.join]` command; a transcript check becomes `suspect`.
4. **Remove the wrapper commands** (`kit plan`, `kit done`, `kit run`, `kit stop`) and any `AGENT_RUNNER_CONFIG`
   set-up. The kit keeps its tools; sessions and people run agent-runner directly.
5. **Check parity on a scratch copy of the plan,** never on the live one. `old/` is the pre-switch copy of the kit:

   ```sh
   git worktree add --detach /tmp/parity HEAD
   cp kit.toml /tmp/parity/            # git-ignored config doesn't travel
   cd /tmp/parity
   old/kit plan > /tmp/old.txt;  agent-runner plan > /tmp/new.txt;  diff /tmp/old.txt /tmp/new.txt
   for id in A1 A2 A3; do diff <(old/kit plan brief $id) <(agent-runner plan brief $id); done   # a few open ids
   agent-runner run --dry-run 3        # the same picks as the old runner's --dry-run
   agent-runner done SOME_ID "parity" --no-test    # ticks and commits on the scratch branch only
   git log -1 --stat; cd -; git worktree remove --force /tmp/parity
   ```

   The plan listing, the briefs and the dry-run picks should match. A brief may differ in the
   runner's wording only.
6. **Delete** the old runner modules (`run.py`, `plan.py`, `done.py`) and their tests. Keep the kit's
   own tools, `runner.toml`, `plan/`, the journal and the notes folder: the
   ledger, the logs and the `wip/<ID>` branches carry over as they are.
7. <a id="switch-between-runs"></a>**Switch between runs, never while slots are working.** Stop the old
   runner (`./kit stop` or `s` + Enter) and wait until it exits. Then commit the switch on main and
   start the new one. A session that started under the old runner would call `done` from its worktree,
   and its branch might still have the old code: that is the one mix that breaks.

## Worktrees: why a global install

Every slot is a git worktree, and the runner in the main checkout and the sessions in the worktrees call
each other: the session's Stop hook calls `run hook`, and `done` in a worktree writes the files the
runner then merges. They must be **one copy of one version**.

- A **global install** (uv tool, pipx) is one copy at one absolute path, shared by every checkout,
  every worktree and every repo on the machine. The hooks call it by that path.
- A **git submodule** is per checkout. Each worktree has its own copy at whatever commit its branch
  points to. A task branch made before a bump runs the old runner, and the main checkout runs the
  new one. Bumping it is a commit that every in-flight branch then conflicts with at merge.
- A **vendored copy** (what the repos have now) has the same problem, plus the drift between repos that
  this package exists to end.

The only thing per repo is the config, and the worktrees read the main checkout's config when theirs is
git-ignored.

## Versions

[Semantic versioning](https://semver.org). The version is in `agent_runner.__version__` and
`agent-runner --version`. Every release is a tag `vX.Y.Z` with an entry in [CHANGELOG.md](../CHANGELOG.md):
the `release` workflow tags and releases each new version pushed to `main`.

**Breaking (a major bump; minor while 0.x)** is anything that makes a repo's existing setup stop working:

- the **task-line format** in TODO.md / DONE.md (ids, `·` files, `after`, `BLOCKED`, sections);
- the **CLI**: command names, flags, exit codes, and the output a wrapper or the prompt relies on;
- **config keys**: renaming or removing one, or changing what a value means;
- the names in a module's `__all__`.

**Not breaking (minor or patch):** new keys with defaults that keep the old behaviour, new commands or
flags, the prompt's wording, log and ledger wording, and anything not in `__all__`.

While the version is 0.x, a breaking change bumps the minor version (0.1 → 0.2), so pin a tag.
