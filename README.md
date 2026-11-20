# agent-runner

<p align="center">
  <a href="https://github.com/FIZL0/agent-runner/releases/latest"><img alt="Latest version" src="https://img.shields.io/github/v/release/FIZL0/agent-runner?label=version&amp;color=2ea44f"></a>
  <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11%2B-3776ab">
  <img alt="No dependencies" src="https://img.shields.io/badge/dependencies-none-lightgrey">
  <a href="LICENSE"><img alt="MIT license" src="https://img.shields.io/badge/license-MIT-blue"></a>
</p>

<p align="center"><b>Write a task list. Go to bed. Wake up to tested, merged commits.</b></p>

agent-runner runs several coding agents at once, unattended, against a git repository and a plain markdown
task list. Each agent gets one task, in its own git worktree and terminal. When it finishes, the runner
tests its branch, merges it, pushes, and starts the next task. Sessions run on Claude Code by default, on
[Pi](#other-providers) for other providers, or on [Copilot CLI](docs/SETUP.md#copilot-cli).

- **Parallel without chaos.** Tasks that touch different files run side by side; tasks that share files,
  or wait on each other, never do.
- **Nothing untested reaches `main`.** Every finish and every merge goes through your test gate. A
  conflict gets a fix session; a broken merge gets a repair session; anything else waits for a human.
- **Lean sessions.** Each agent starts from a ~1k-token brief of its own task, not the whole plan: about
  [40% less context and half the tokens](#results) of a session that reads the plan itself.
- **Hands-off.** Usage limits, network drops, reboots and runaway tests are all handled: work is paused,
  resumed or adopted, never lost.
- **Zero setup.** Python 3.11 standard library only, one optional `runner.toml`, and nothing for the repo
  to install.

<p align="center">
  <img src="docs/img/run-log.svg" alt="A real run log: four slots start tasks, a fix session resolves a conflict, and each finished task is merged, ticked and pushed">
</p>

## Quick start

```sh
uv tool install git+https://github.com/FIZL0/agent-runner    # tracks main; or: pipx install git+https://…
cd your-repo
agent-runner plan                  # what the runner sees in plan/TODO.md
agent-runner run --dry-run 3       # what three slots would start right now, and why the rest wait
agent-runner run once              # one task, one session, then stop: try it like this first
agent-runner                       # the run in the background; the prompt comes straight back
agent-runner status                # is it up, each slot's task and minutes, what merged lately
agent-runner attach                # watch it (attach s2: slot 2; c1: the control session); Ctrl-b d to detach again
agent-runner control               # a control session here: "status?", "pause", "add a task to fix X"
agent-runner stop                  # finish the running tasks, then end it
```

Bare `agent-runner` starts the run in a detached tmux session `ar-<repo>`, with the slots' window in it, so
no terminal is taken and nothing pops up. `agent-runner run 3` is the same run in this terminal (inside tmux).
Either way the run opens a control session, c1, beside it: a Claude Code session in the main checkout that
you ask for status, to pause, to add slots or stop, to queue a task, or to do one now; it posts a line when
a task merges or is parked. Any new pane in the `ar-<repo>` session is another one. With `[run] remote` the
control sessions are on Remote Control, so you run the run from claude.ai/code or the Claude apps
([docs/REFERENCE.md](docs/REFERENCE.md#control-sessions)).

> [!TIP]
> No repo handy? `examples/demo.sh` builds a tiny one with a plan in a temp dir and shows `plan`,
> `plan brief` and `run --dry-run` without starting an agent. `examples/demo.sh --run` also does one real task.

Upgrade with `uv tool upgrade agent-runner` (or `pipx upgrade`) any time: a running run restarts itself on the
new version and adopts its sessions (not on Windows, nor across a major version). Or pin a
[release](https://github.com/FIZL0/agent-runner/releases/latest): `uv tool install git+https://github.com/FIZL0/agent-runner@v<version>`.
On Windows, bare `agent-runner` runs the runner as a hidden process and each slot in a console window that
starts hidden (`agent-runner attach s2` shows one); `agent-runner run 3` in a terminal gives each slot a
Windows Terminal tab instead of a tmux pane.
Adding it to an existing repo and wrapping it from your own CLI are in [docs/SETUP.md](docs/SETUP.md).

## How it works

The runner keeps a number of **slots** busy (3 by default). A slot is one agent on one task, in its own git
worktree and terminal.

```
plan/TODO.md
   │  pick the first task that may start
   ▼
slot N: worktree on task/<ID>, a terminal running the agent
   │  the agent runs `agent-runner done <ID> "msg"`: tests → tick → commit → push task/<ID>
   ▼
merge worktree: main + task/<ID> (+ other finished branches)
   │  a conflict → fix session · tests fail → repair session · tests pass ↓
   ▼
main moves and is pushed; the slot picks its next task
```

1. **Pick.** A free slot reads `plan/TODO.md` from the top and takes the first task that may start. A task
   waits while it is blocked, while a task in its `after:` is not done, while it shares `files:` with a
   task that is running or not merged yet, or while another task of its family is running.
2. **Work.** The slot gets a worktree on branch `task/<ID>` and a terminal (a tmux pane; a Windows Terminal
   tab on Windows). The agent starts from a short brief: the task's line, its long form, the files it
   names, and its newest journal entry.
3. **Finish.** The agent runs `done`. It runs your test gate, ticks the task, commits and pushes the
   branch, and refuses while the tests fail. A stuck agent runs `done --blocked "why"` instead. Once the
   session goes quiet, the runner ends it.
4. **Merge.** Merges are built in a separate worktree, one at a time, so your checkout never holds an
   untested merge.
   - Other finished branches waiting their turn ride along: one test run covers them all.
   - The task list merges task by task, and files you list as `joinable` (a changelog) join line by line.
   - A conflict that needs reading goes to a short **fix session**. It runs ahead of the queue, so it
     holds up nobody else. Two fixes on the same files take turns, so neither is done twice.
   - The test gate runs on the merge. If it fails, a **repair session** gets one try. A batch that still
     fails is split, and each task tries alone.
   - Only a passing merge moves `main`, and then `main` is pushed.
   - A task that can't land in three tries is parked as `wip/<ID>` for a human, with the reason in
     `.runner/ledger.md`.
5. **Repeat.** Tasks the merge unblocked open up. When nothing can start, the run logs `run idle` and
   waits: whatever you add to TODO.md later starts without a restart.

**One task by hand.** `agent-runner take B646` gives B646 a worktree of its own and prints its prompt, for
your own session or a subagent, while a run goes on (the run keeps off it and its files). Finish with
`agent-runner done B646 "..."` there, then `agent-runner take B646 --merge`: the runner tests and merges it.
Work not queued yet: `agent-runner take "what, why, how to check" --kind B --files a.py` queues and takes it
in one step. Edits already made in the main checkout: add `--here`, and they move into the new worktree.

**Stopping.** Type `s` + Enter in the runner's pane, or run `agent-runner stop`. Nothing new starts; the
running tasks finish and merge, then the run exits (`s` again takes it back). `s!` (`stop --force`) ends the
sessions now instead, each to resume in the next run. `p` pauses, `u` upgrades agent-runner (the run restarts on it; `run --upgrade` does it at launch), `f` starts tasks past the usage caps (as `--force`), `+`/`-` change the slot count, and `z` or
`x` suspend or shut the computer down once the run stops (or goes idle); `?` lists the keys. To leave the
machine to it from the start, run with `--shutdown` or `--suspend`.

## The task list

`plan/TODO.md` is ordinary markdown. The runner reads task lines under `###` headings:

```markdown
### Next (in this order)

- [ ] **P12** the parser reads nested lists | files: src/parse.py, tests/test_parse.py | test: test_parse
- [ ] **P13** maps too | files: src/parse.py | after: P12
  - [ ] **P13a** the empty map
- [~] **P14** a fuzz harness | files: tools/fuzz.py BLOCKED: (after P12, P13) needs both grammars

### Stretch

- [ ] **P99** nice to have: a run never starts this section
```

- `[ ]` open, `[x]` done (moved to `DONE.md`), `[~]` blocked. Only the tool changes a box: use
  `agent-runner plan add|tick|block|note|move …`, never edit one by hand.
- `files:` lets two tasks run side by side when they don't overlap, and puts those files in the brief.
  `after:` holds a task until every id listed is done. Prose is never parsed for either.
- `P13a` is a subtask of `P13`: a family never runs two tasks at once.
- A long description goes in `plan/tasks/<ID>.md`, which the brief uses in place of the line.

To make one task wait for another, say it in a way the runner reads:

| to make B wait for A | do this |
|---|---|
| B is part of A's work | `plan add A12 "…"` gives subtask `A12a` |
| B needs A merged first | `after: A12` on B's line, or `plan block B3 --after A12 "why"` |
| a list that must go in order | a section heading containing *in this order* or *one at a time* |

The plan can also live in [its own git repo](docs/REFERENCE.md#the-plan-in-its-own-repo), shared by every
machine, with claims so two people can run against it at once.

## Configuration

Every key is optional. A typical `runner.toml` for a parallel project:

```toml
[plan]
journal = "journal"           # per-task notes; the newest goes into a retry's brief

[run]
test = "make test"            # the gate: run by every `done` and every merge
slots = 3
rules = "AGENTS.md"           # the file every session is told to read first
shared_files = ["CHANGELOG.md"]   # every task touches it: don't count it as overlap
joinable = ["CHANGELOG.md"]       # and join its conflicts line by line
```

`runner.local.toml`, created for you and kept out of git, overrides it on one machine (fewer slots on a
laptop, a lower usage cap). Every key is in the [reference](docs/REFERENCE.md#runnertoml).

### Other providers

For models Claude Code doesn't serve (GitHub Copilot, Codex, other provider logins), set `backend = "pi"`
to run sessions on [Pi](https://www.npmjs.com/package/@earendil-works/pi-coding-agent), or try it once with
`AGENT_RUNNER_BACKEND=pi agent-runner run once`. Pi sessions still run the repo's Claude Code PreToolUse
hooks. See [Pi and enterprise Copilot](docs/SETUP.md#pi-and-enterprise-copilot).

> [!NOTE]
> Pi on an Anthropic model bills that account's extra usage, not the plan, so keep Claude models on
> Claude Code.

## Results

Measured over every slot session in opentennis and partyboard. **Before:** each
session loaded the full Claude Code setup (MCP servers, user settings) and read the plan itself to find
its task. **After:** a lean session (`[run] lean`, the default) starts from its own brief.

| median per session | before | after |
|---|---|---|
| context at the first turn | 38k | **24k** |
| peak context | 165k | **107k** |
| tokens re-read over the session | 16.3M | **7.4M** |

<sub>Before: opentennis, 212 sessions, 7–11 Oct 2026. After: opentennis and partyboard, 497 sessions,
19 Oct–16 Nov 2026.</sub>

On opentennis, five slots in parallel against a 200k window, that is the difference between sessions that
ran out of room mid-task and sessions that finish with half the window to spare. `agent-runner cost` shows
where the remaining tokens go, by kind of tool call.

## Working with it well

- **Small tasks that name their files.** One session, one task, one commit. Anything bigger than an
  afternoon of human work should be split into subtasks first.
- **A real test gate.** `[run] test` is the only thing between an unattended agent and `main`: fast enough
  to run on every finish and merge, strict enough that you trust it.
- **Keep the rules file small.** Your rules file, CLAUDE.md and AGENTS.md are re-read on every turn of every
  session, and agents keep adding to them. Put code maps and how-tos in `[plan] lookup` files instead, one
  `## section` each, which agents fetch with `agent-runner plan <heading>`. `agent-runner context` shows what
  every session loads against a 12 KB budget (`[plan] context_kb`).
- **Order only what must be ordered.** An *in this order* section runs one task at a time; a plain
  section starts tasks side by side whenever their files don't overlap.
- **Start small.** `once`, then 2 or 3 slots. More only helps when the plan has that many tasks on
  different files, and usage limits are per account: five slots spend them five times as fast.

### Filing tasks from a chat

The easiest way to feed a run is a normal Claude Code session in your main checkout, beside it. You say
what you saw in your own words; the session finds the files, writes the task line and files it. It
doesn't do the fix itself: the run picks the task up like any other. Put the rule in your `CLAUDE.md`
so every session follows it:

```markdown
## New asks go to the plan

When I report a bug or ask for a feature, don't fix it here. File it with `agent-runner plan add`:
- the kind letter from `agent-runner plan kinds`, and my words quoted with the date;
- `--files` naming every file the fix will touch (look them up first), `--after` if it needs another task;
- what "done" looks like, so the agent can test it. Long context goes in plan/tasks/<ID>.md.
If `plan add` says it looks like an open task, `plan note` that task instead.
Only do the work here when I say "do it here".
```

An exchange like the ones that fill [openmx](https://github.com/FIZL0/openmx)'s plan:

> **You:** the buggy and monster truck drive straight through walls and props
>
> **Claude:** *(reads the car code, then runs)*
> ```sh
> agent-runner plan add S "The buggy and the monster truck have no body collision: the body passes \
>   through walls and props (user 2026-11-16 'drive straight through walls and props'). Port the \
>   original's car-vs-world and car-vs-prop contacts; done when a car driven into a wall stops" \
>   --files crates/game-sim/src/car.rs,crates/game-sim/tests/car_props.rs
> ```
> Filed as **S335**, top of the list. The next free slot picks it up.

That puts this line in `plan/TODO.md`:

```markdown
- [ ] **S335** The buggy and the monster truck have no body collision: … | files: crates/game-sim/src/car.rs, crates/game-sim/tests/car_props.rs
```

The same session is handy for the rest of the loop: "status?" (it reads `.runner/run.log` and the
ledger), "move S335 up", "why is P12 blocked?", or "split P40 into steps".

After a run, `.runner/ledger.md` has one line per branch (merged, blocked, or **left for a human, and
why**), `agent-runner plan` shows what's blocked, and `git branch --list 'wip/*'` lists branches that
couldn't be merged.

## Used by

- **[opentennis](https://github.com/FIZL0/opentennis)**: a PS2 game remaster, one PCSX2 per slot.
- **[partyboard](https://github.com/FIZL0/partyboard)**: a Mario Party 4 port with online play.
- **[ps2-decomp-kit](https://github.com/FIZL0/ps2-decomp-kit-linux)**: a PS2 decompilation kit, wrapping it
  as `./kit run`.
- **[openmx](https://github.com/FIZL0/openmx)**: a PS2 game port built on the kit.

## Documentation

| | |
|---|---|
| [docs/SETUP.md](docs/SETUP.md) | installing, Windows, Pi, adding it to a repo, wrapping it from your own CLI |
| [docs/REFERENCE.md](docs/REFERENCE.md) | picking, merging, fix and repair sessions, disk and memory limits, CI, the prompt, every command and config key |
| [docs/AGENTS-EVAL.md](docs/AGENTS-EVAL.md) | which other terminal agents could become backends |
| [CHANGELOG.md](CHANGELOG.md) | what changed in each version |
