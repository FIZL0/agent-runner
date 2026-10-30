# Setting it up

How to install agent-runner, add it to a repo, wrap it from a project's own CLI, move a repo that has its
own copy over to it, and what a version number promises.

- [Installing](#installing)
- [Pi and enterprise Copilot](#pi-and-enterprise-copilot)
- [A new repo from scratch](#a-new-repo-from-scratch)
- [Wrapping it from your own CLI](#wrapping-it-from-your-own-cli)
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

**Windows:** Python 3.11+ from python.org (not the Store's `python3` alias), Git for Windows (Claude Code
runs hooks and Bash calls in its Git Bash), and Windows Terminal for a tab per slot. Without Windows
Terminal each slot gets a console window. tmux isn't needed. Run `agent-runner run 3` from any terminal.
`[run] links` need no Developer Mode: without it they become junctions and hard links. See the README's
[Terminals, and Windows](../README.md#terminals-and-windows).

**Latest, or a tag.** Without `@…` it installs `main`, which is always the latest release (every commit
there is one). To hold a machine at a version, name its tag instead: `…/agent-runner@v0.6.18`.

**Upgrade every repo at once.** There is one install per machine, so one command upgrades every repo
that uses it:

```sh
uv tool upgrade agent-runner
pipx upgrade agent-runner
```

Both fetch `main` again (a tag install stays on its tag). A run says when `main` has a newer version and
which of these to type. Do it between runs (see [below](#switch-between-runs)). Read [CHANGELOG.md](../CHANGELOG.md) first: a
new major version may rename a config key.

**Roll back** the same way, naming the older tag: `uv tool install --force …@v0.2.0`.

**From a clone,** for hacking on the runner itself: `git clone https://github.com/FIZL0/agent-runner`
and call `~/agent-runner/run …`. A clone needs no install. `uv tool install --editable ~/agent-runner`
makes the `agent-runner` command run the clone's code.

## Pi and enterprise Copilot

Pi 1.4.0 or newer is supported alongside Claude Code. Install it with Node.js 22.19+:

```powershell
npm install --global --ignore-scripts @earendil-works/pi-coding-agent
pi
```

Inside Pi, run `/login`, choose **GitHub Copilot**, enter your full enterprise hostname, and complete
the device authorization in your browser. Run `/model` to choose a model. Authentication remains in
Pi's private user directory, never in `runner.toml`.

Check authentication and the account's models without printing credentials:

```powershell
pi auth check --provider github-copilot --json
pi --offline --list-models github-copilot
```

Configure the repository:

```toml
[run]
agent = "pi"
backend = "pi"            # optional for an executable named pi; required for a differently named wrapper
model = "github-copilot/claude-sonnet-5.5"
fix_model = "github-copilot/claude-sonnet-5.5"
slots = 1
slot_env = ["AGENT_SLOT={n}", "NODE_USE_SYSTEM_CA=1"]
```

Choose an ID your account lists. Provider-qualified IDs prevent ambient AWS or other provider
credentials from selecting the wrong service. If `model` is omitted, Pi uses its own model selection;
an omitted `fix_model` follows `model`. Other Pi providers work through their own qualified IDs and login.
`NODE_USE_SYSTEM_CA=1` uses the OS certificate trust store for corporate TLS interception; it requires a
Node.js release supporting that setting (Node.js 22.19+). It does not disable certificate verification.
If Pi itself reports an issuer-certificate error, set `$env:NODE_USE_SYSTEM_CA = "1"` before starting it.

From a clone on Windows, use `python -m agent_runner run once`; an installed runner uses
`agent-runner run once`. Normal terminal selection, parallel worktrees, `done`, test gates, and merging
are unchanged.

Other terminal agents (Copilot CLI, Codex, opencode, …) are evaluated in [AGENTS-EVAL.md](AGENTS-EVAL.md);
`python tests/agent_matrix.py --auth pi` checks that Pi is installed and logged in.

Pi sessions are interactive, like Claude's: each slot's pane (and the `master-<repo>` window for fix
sessions) shows Pi's interface, and you can take a session over by typing. The bundled extension
`pi_idle.ts`, loaded with `-e` even under `lean`, does what Claude's Stop hook does: once Pi has settled at
its prompt for `idle` seconds with nothing in the editor, it exits. Fix sessions without tmux use print
mode. Prompts are passed as files (`@file`), at any size, including on Windows. Sessions are retained under
`.runner/pi-sessions` for `agent-runner resume ID`, restart adoption, usage statistics, and stall checks.
Transient network/server errors can resume up to the existing resume limit in worktree mode. Pi's own
provider retries apply, but Claude-specific weekly caps and usage-reset detection do not apply to Pi;
authentication, billing, and other non-transient errors are reported for a human rather than retried.
In sequential mode a failed Pi process returns its nonzero exit code.

With `lean = true` (the default), Pi gets read/edit/write and a shell (`powershell` on Windows, `bash`
elsewhere), with extensions, MCP, skills, prompt templates, and themes disabled. Repository context
files remain available. Set `lean = false` to use Pi's normal resource configuration. Fix/repair sessions
also use Pi print mode and the non-slot-specific environment from `slot_env`.

## A new repo from scratch

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

The id is bold, the files after a `·` are what the task may touch (mode `d` keeps two slots off the same
file), and `after X` holds a task until X is ticked. `plan/A1.md`, if present, is the long brief. See the
[README](../README.md#the-task-list) for the full format.

**plan/DONE.md** can start empty; finished tasks move there.

**runner.toml** (every key is optional; see the [README](../README.md#runnertoml)):

```toml
[run]
test = "make test"        # the gate: `done` and every merge run it
rules = "AGENTS.md"       # what every session reads first
notes = ".runner"
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
tmux new -s runner agent-runner run 3
```

## Wrapping it from your own CLI

A project with its own CLI (`./kit`, `make`, `just`) can keep it as the one front door. The agents
type `./kit done …`, and the CLI hands off to agent-runner. There are two parts to that.

**The config** lives in the project's own config file, under an `[agent-runner]` table, named by
`AGENT_RUNNER_CONFIG`:

```toml
# kit.toml
[git]                      # the kit's own; agent-runner does not read it
remote = "upstream"

[agent-runner.run]
test = "./kit check"
command = "./kit"          # what the prompt tells sessions to type

[agent-runner.git]
push = "origin"
```

Settings come from exactly one place: the file `AGENT_RUNNER_CONFIG` names (its `[agent-runner]` table
if it has one, else its top level), else `runner.toml`. A relative path is read against the main
checkout. The runner hands `AGENT_RUNNER_CONFIG` on to every slot and every Stop hook, so the sessions
read the same file.

**The code** is thin wrappers over the library, which keep the project's exact CLI:

```python
import os
os.environ.setdefault('AGENT_RUNNER_CONFIG', 'kit.toml')

from agent_runner import plan, done, runner
from agent_runner.config import cfg

plan.PROG = './kit plan'                 # how its messages name the command
done.PROG = './kit done'

def kit_plan(argv): return plan.main(argv)
def kit_done(argv):
    argv = ['--skip-check' if a == '--skip-audit' else a for a in argv]   # the kit's old flag
    rc = done.main(argv)
    print('journal: ./kit journal finish', file=sys.stderr)              # anything extra after
    return rc
def kit_run(argv):
    os.environ['KIT_CHECK_SLOTS'] = '3'   # forwarded through [run] pass_env
    return runner.cmd_run(argv)
def kit_stop(argv): return runner.cmd_stop(argv)
```

`cfg()` is cached per checkout, so a wrapper can also adjust a setting in code before calling in:
`cfg().run['links'].append('context')`.

The names in each module's `__all__` are the stable API (see [Versions](#versions)): `plan.main`,
`plan.brief`, `plan.tick`, `plan.open_ids` …, `done.main`, `done.gate`, `done.check`, `runner.cmd_run`,
`runner.cmd_stop`, `runner.pick`, `runner.tasks`, `runner.ask_stop`, `runner.PROMPT`, …

### The hooks a wrapping project gets

| hook | what it does |
|---|---|
| `[run] test` | the gate run by `done` and after every merge |
| `[run] precommit` | a second check `done` runs after the gate, before it ticks or commits; `done --skip-check` skips it |
| `[run.join]` | `"glob" = "command"`: the project joins a conflict in that file itself. `{ours} {base} {theirs} {union} {out} {file}`; exit 0 keeps `{out}`, non-zero sends it to a fix session |
| `[run] suspect` | a regex; a `BLOCKED` line a merge adds to the plan that matches it is flagged `SUSPECT, recheck` in the ledger |
| `[run] slot_env` | `NAME=value` per slot, with `{n}` (slot) and `{slots}` (how many) |
| `[run] pass_env` | names of the runner's environment variables handed on to every slot |
| `[run] on_exit` | a command run in the slot's worktree, with the slot's env, when its session ends (both parallel and `once`) |
| `[run] prompt_extra` | a paragraph added to the prompt; takes the prompt's placeholders (`{n}`, `{id}`, `{runner}`, …) |
| `[run] command` | what the prompt and the brief tell sessions to type (`./kit`) |
| `[run] links` | git-ignored paths symlinked into every worktree |
| `[plan] journal` | per-task journal folders; the newest entry goes into the brief |
| `[plan] brief_extra` | a command (`{id}`) whose output ends the brief |
| `[plan] brief` | a command (`{id}`) whose output is the whole brief, for a project with its own brief tool |
| `[run] untested` | globs of files the gate can't see (`!glob` takes one back); a merge differing only in them isn't retested |
| `[run] failures`, `retest` | a regex naming failed tests in the gate output, and the gate for just `{names}`: rerun alone, then on the base |
| `[run] flaky`, `flaky_kind` | a regex naming tests a *passing* gate passed only on its own rerun; each (and each `retest` pass) gets a critical `flaky_kind` follow-up to make it robust |
| `[plan] kinds` | id prefix -> kind of work; listed in the prompt, and `plan add` refuses any other prefix |
| `[run] before_start` | a check that must pass before any session starts |
| `[run] timeout` | seconds the gate, a retest, a `[run.join]` command, `before_start` or the sequential run's `on_exit` may run before it is stopped and counts as failed (3600) |
| `[run] not_attempt` | a regex on the last commit subject (`{id}`): that session was a phase, not the run's one attempt |

The brief already holds the task line, `plan/<ID>.md`, the newest journal entry, and the git log of the
files the task names. `brief_extra` is for anything else.

### Worked mapping: ps2-decomp-kit

What each `./kit` feature becomes:

| ps2 kit feature | agent-runner |
|---|---|
| `./kit check` (tests + lint) as the gate | `test = "./kit check"` |
| the address audit, `./kit done --skip-audit` | `precommit = "./kit audit --quiet"`; the wrapper maps `--skip-audit` to `--skip-check` |
| joining `research/oracle.txt` address lists, refusing when one name gets two addresses | `[agent-runner.run.join] "research/oracle.txt" = "./kit oracle join {union} {out}"` (a kit subcommand that reuses its address parser and exits 1 on a clash) |
| the SUSPECT check on blocks that blame the emulator | `suspect = 'BLOCKED:.*(pcsx2\|pine\|capture\|record\|screenshot\|save state\|unattended)'` |
| `KIT_PCSX2=<slot>`, `KIT_RUN=1` | `slot_env = ["KIT_PCSX2={n}", "KIT_RUN=1"]` |
| `KIT_CHECK_SLOTS` | the wrapper exports it and lists it in `pass_env = ["KIT_CHECK_SLOTS"]` (or `slot_env` with `{slots}`) |
| stopping the slot's PCSX2 when its session ends | `on_exit = "./kit pcsx2 stop"` (it runs with `KIT_PCSX2={n}`) |
| the emulator paragraph in the prompt | `prompt_extra = "Your emulator is slot {n}: ./kit pcsx2 start …"` |
| agents typing `./kit plan`, `./kit done` | `command = "./kit"`, and `plan.PROG` / `done.PROG` |
| `research/journal` | `[agent-runner.plan] journal = "research/journal"` |
| `context/notes` (logs, ledger) | `notes = "context/notes"` |
| `context/` and `*.iso` in every worktree | `links = ["context", "*.iso"]` |
| the long-lived master session and master.md | gone: one fix session per conflict, and the ledger (`notes/ledger.md`) |
| the journal hint after `done` | printed by the wrapper after `done.main` |

The rest of `./kit` (Ghidra, PCSX2, PINE, the state tools) stays in the kit. agent-runner never needs to
know about it.

### Worked example: opentennis

opentennis runs `agent-runner run` directly, with this `runner.toml` and no wrapper script.
Conflicts go to a fix session each, and merges never stash the main checkout.

```toml
# runner.toml (opentennis)
[plan]
dir = "plan"
journal = "research/journal"
brief = "tools/ctx.py brief {id}"   # also writes the .cleanroom lock for a port phase

[run]
test = "tools/check.sh"
slots = 5
mode = "p"
weekly_max = 94
notes = "context/notes"
rules = "AGENT.md"
prompt = "tools/runner-prompt.md"   # sessions finish with tools/done.sh (audit, tests, --spec / --blocked)
links = ["context", "mods", "replacements", "*.iso"]
shared_files = ["play.rs"]
joinable = ["plan/*.md", "research/journal/*", "RELEASE_NOTES.md"]
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
| `ctx.py brief` pasted into the prompt (and its `.cleanroom` lock) | `[plan] brief` |
| `tested_by_cargo` | `untested` |
| net:: flakes rerun once; "already failing on main → merge anyway" | `failures` + `retest` |
| WAITING/LANDED batch merges | `batch = true` |
| spec commits aren't an attempt | `not_attempt` |
| "(split into …)" parents wait, then tick themselves | built in |
| adopting running sessions after a restart; a slot held while an untracked pane runs; one runner at a time | built in |
| the prompt through a file (tmux's ~16 KB limit) | built in |
| master session stashing main around merges | gone: a merge worktree, then a fast-forward-or-merge into main that waits for a human's edits instead of stashing them |

What it gets that it didn't have: a fix session per conflict instead of one master that knows every
merge, `--after` reopening blocked tasks once their blocker lands, `wip/<ID>` parking pushed off the
disk, `run once` / `--dry-run`, and the tests.

## Migrating a repo that carries its own copy

openmx and ps2-decomp-kit each have their own runner (`tools/kit/run.py`, `plan.py`, `done.py`). Moving
one over:

1. **Install** a pinned tag (above).
2. **Move the config.** Write the `[agent-runner]` table into the project's config file, taking each
   value from the old code: the gate, the slot env, the prompt paragraph, the links, the notes folder.
   Use the mapping table above. Set `AGENT_RUNNER_CONFIG` where the CLI starts.
3. **Move the special cases into hooks.** A custom join becomes a `[run.join]` command; an audit
   becomes `precommit`; a transcript check becomes `suspect`.
4. **Replace the commands with wrappers** (above), keeping the old flags as aliases.
5. **Check parity on a scratch copy of the plan,** never on the live one:

   ```sh
   git worktree add --detach /tmp/parity HEAD
   cp kit.toml /tmp/parity/            # git-ignored config doesn't travel
   cd /tmp/parity
   old/kit plan > /tmp/old.txt;  ./kit plan > /tmp/new.txt;  diff /tmp/old.txt /tmp/new.txt
   for id in A1 A2 A3; do diff <(old/kit plan brief $id) <(./kit plan brief $id); done   # a few open ids
   ./kit run --dry-run 3               # the same picks as the old runner's --dry-run
   ./kit done SOME_ID "parity" --no-test    # ticks and commits on the scratch branch only
   git log -1 --stat; cd -; git worktree remove --force /tmp/parity
   ```

   The plan listing, the briefs and the dry-run picks should match. A brief may differ in the
   runner's wording only.
6. **Delete** the old runner modules (`run.py`, `plan.py`, `done.py`) and their tests. Keep the kit's
   own commands, the hook commands you just wrote, `plan/`, the journal and the notes folder: the
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
`agent-runner --version`. Every release is a tag `vX.Y.Z` with an entry in [CHANGELOG.md](../CHANGELOG.md).

**Breaking (a major bump; minor while 0.x)** is anything that makes a repo's existing setup stop working:

- the **task-line format** in TODO.md / DONE.md (ids, `·` files, `after`, `BLOCKED`, sections);
- the **CLI**: command names, flags, exit codes, and the output a wrapper or the prompt relies on;
- **config keys**: renaming or removing one, or changing what a value means;
- the names in a module's `__all__`.

**Not breaking (minor or patch):** new keys with defaults that keep the old behaviour, new commands or
flags, the prompt's wording, log and ledger wording, and anything not in `__all__`.

While the version is 0.x, a breaking change bumps the minor version (0.1 → 0.2), so pin a tag.
