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
tests its branch, merges it, pushes, and starts the next task. Sessions run on Claude Code by default, or on
other providers (GitHub Copilot among them) through a `<provider>:<model>` model name, see [Other providers](#other-providers).

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
agent-runner setup                 # a new repo: backs up uncommitted work to a branch, writes runner.toml,
                                   # and a Claude session reads the repo and writes the gate and a first plan
agent-runner home install          # recommended: one always-on page for every project on this device, link + QR code
agent-runner plan                  # what the runner sees in plan/TODO.md
agent-runner run --dry-run 3       # what three slots would start right now, and why the rest wait
agent-runner run once              # one task, one session, then stop: try it like this first
agent-runner                       # the run in the background; the prompt comes straight back
agent-runner --attach              # the same (or the run already up), then the run view here
agent-runner status                # is it up, merged / left counts, each slot's task, what merged lately
agent-runner attach                # the run view: its log, live, and its keys (s, p, +, ?); Ctrl-C leaves it
agent-runner attach s2             # slot 2's own terminal (attach c2: a control session); Ctrl-b d leaves it running
agent-runner ui                    # the run page here: sessions, queue, what needs you; keys act on it
agent-runner control               # a control session here: "status?", "pause", "add a task to fix X"
agent-runner stop                  # finish the running tasks, then end it
```

Bare `agent-runner` starts the run as a detached process, so no terminal is taken and nothing pops up.
`agent-runner run 3` is the same run in the foreground of this terminal. Either way each slot runs hidden, in
a terminal with no window, its output in `.runner/slotN.log`: `agent-runner attach s2` puts this terminal on
it, and you watch and steer the run through `agent-runner attach` (the run view), `status`, `ui`, control
sessions and `plan tell`. The same on Linux, macOS and Windows; the run needs no tmux. The terminal UI (`agent-runner ui`) does: it runs
inside tmux on Linux and macOS, and on Windows the run page stands in for it.
The run opens no control session of its own. Each thing you ask for opens one, c2, c3, … (hidden too: `attach c2`):
a message in the run app's Home box, a Status quick ask, a change to a task, a reply under Needs you. It is named for its
ask, and it is a Claude Code session in the main checkout that you ask for status, to pause, to add slots or stop, to
queue a task, or to do one now. A message in an open chat goes to that chat. `agent-runner control` opens a blank one in
this terminal, with no summary until you ask for one; when you say "follow" it posts each task as it lands. With
`[run] remote` the control sessions are on Remote Control, so you run the run from claude.ai/code or the Claude apps
([docs/REFERENCE.md](docs/REFERENCE.md#control-sessions)). The run closes the quiet ones after 3 hours of quiet once
Claude has answered, so the apps' list stays short; one left on a question marked with a `DECIDE:` line goes under
Needs you first (`[run] control_idle`, `control_ask`).
marked with a `DECIDE:` line goes under Needs you first (`[run] control_idle`, `control_ask`).

### Runner Home: every project from your phone

```sh
agent-runner home install          # an always-on service; prints its link and a QR code to scan
agent-runner home status           # installed? serving? the link again (uninstall: take it away)
agent-runner home add ~/work/proj  # list a project that is not under ~/repos (remove PATH: unlist one)
```

Runner Home is the recommended setup, not an optional extra. With several projects on one device it is what
keeps every run's page reachable: one link, each run at `/p/<project>/`.

Each run serves its own page only while it is up. Runner Home is one page that is always there: every folder
in `~/repos` with a `runner.toml`, plus the ones you add, each shown as running, idle or off with what needs
you, and Start run, Pause, ±1 slot and Stop buttons that run the runner's own commands in that project. Open
takes you to that project's run app through Home, so one link (one bookmark) reaches them all. It runs as a
per-user service that starts at boot: systemd `--user` with linger on Linux, a launchd agent on macOS, a
scheduled task at logon on Windows. It is on once you install it (`home install` in the Quick start). Like the run page it is token-gated and
listens on port 8770 on every interface, for a phone on your network or Tailscale; never expose it to the
internet. With Home on that port, a run serves its own page on 127.0.0.1 only, on a free one that only Home
opens; with Home off, the first run up keeps port 8770 and a second run listens on 127.0.0.1 only, its status
and run log offering `agent-runner home install`. Its projects and token are in `~/.config/agent-runner` (`%APPDATA%\agent-runner`).

#### Trusted networks

The page's key (`?t=`) is always needed by default. To skip it on your tailnet, run `agent-runner home trust add tailnet`
(`home trust remove tailnet` undoes it; `home status` lists the networks). Devices on a trusted network then open Home and
a run's page without the key. Anyone on that network can do everything the page does, including type into sessions, so
run commands on the machine as you; add only networks you trust. Loopback is never trusted, and the key stays on for any
other network.

> [!TIP]
> No repo handy? `examples/demo.sh` builds a tiny one with a plan in a temp dir and shows `plan`,
> `plan brief` and `run --dry-run` without starting an agent. `examples/demo.sh --run` also does one real task.

Upgrade with `uv tool upgrade agent-runner` (or `pipx upgrade`) any time: a running run restarts itself on the new
version and adopts its sessions (not on Windows, nor across a major version; with `[run] auto_upgrade = false` nothing restarts by itself). Or pin a
[release](https://github.com/FIZL0/agent-runner/releases/latest): `uv tool install
git+https://github.com/FIZL0/agent-runner@v<version>`. On Windows each slot runs in a ConPTY pseudo-console with no
window (Windows 10 1809 and later; before that, a console that starts hidden, which `agent-runner attach s2` shows). On
Linux, macOS and Windows 1809 and later `agent-runner attach s2` (or `c2`) puts this terminal on a hidden session's own terminal; Ctrl-b d
detaches and leaves it running. Adding it to an existing repo and keeping your own CLI for its tools are in
[docs/SETUP.md](docs/SETUP.md).

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
2. **Work.** The slot gets a worktree on branch `task/<ID>` and a hidden terminal (a pseudo-terminal with no window; on
   Windows a ConPTY pseudo-console, or a console that starts hidden before 1809). The agent starts from a short brief:
   the task's line, its long form, the files it names, and its newest journal entry.
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
     `.runner/ledger.md`. Once the task is ticked or dropped, the run deletes its `wip/<ID>` branches,
     here and on the remote.
5. **Repeat.** Tasks the merge unblocked open up. When nothing can start, the run logs `run idle` and
   waits: whatever you add to TODO.md later starts without a restart.

**One task by hand.** `agent-runner take B646` gives B646 a worktree of its own and prints its prompt, for
your own session or a subagent, while a run goes on (the run keeps off it and its files). Finish with
`agent-runner done B646 "..."` there, then `agent-runner take B646 --merge`: the runner tests and merges it.
Work not queued yet: `agent-runner take "what, why, how to check" --kind B --files a.py` queues and takes it
in one step. Edits already made in the main checkout: add `--here`, and they move into the new worktree.

**Stopping.** Type `s` + Enter in the run view (`agent-runner attach`, or the terminal `run 3` runs in), or
run `agent-runner stop`. Nothing new starts; the
running tasks finish and merge, then the run exits (`s` again takes it back). `s!` (`stop --force`) ends the
sessions now instead, each to resume in the next run. `p` pauses, `u` upgrades agent-runner (the run restarts on it; `[run] auto_upgrade`, on by default, does it once a release is out, and off, nothing restarts by itself), `f` starts tasks past the usage caps (as `--force`), `+`/`-` change the slot count, and `z` or
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
  `agent-runner plan add|tick|block|note|move …`, never edit one by hand. A mistaken tick or drop comes
  back with `plan restore ID`: open again, same id and fields. A task that needs correcting takes
  `plan edit ID "the corrected text"`: the description and its notes are replaced in place, the id, box,
  BLOCKED text and fields kept (`--files`/`--after`/`--test`/`--pri` change those); `plan note` only adds.
- `files:` lets two tasks run side by side when they don't overlap, and puts those files in the brief.
  `after:` holds a task until every id listed is done. Prose is never parsed for either.
- `P13a` is a subtask of `P13`: a family never runs two tasks at once.
- A long description goes in `plan/tasks/<ID>.md`, which the brief uses in place of the line.

To make one task wait for another, say it in a way the runner reads:

| to make B wait for A | do this |
|---|---|
| B is part of A's work | `plan add A12 "…"` gives subtask `A12a` |
| B needs A merged first | `after: A12` on B's line, or `plan block B3 --after A12 "why"` |
| B goes last (a release) | `plan add T "…" --last`: end of Next, `after: all above` (every task above it there) |
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

For models Claude Code doesn't serve (GitHub Copilot, Codex, other provider logins), name the model in
`[models]` as `<provider>:<model>`, e.g. `code = "copilot:<model>"`, and log in once with
`agent-runner login copilot`. Those sessions run on the harness loop, which replaces the old Pi backend: delete any
`agent = "pi"`, `backend = "pi"` or `AGENT_RUNNER_BACKEND=pi`, or the run refuses to start. See
[Other providers](docs/SETUP.md#other-providers).

> [!NOTE]
> Keep Claude models on Claude Code: a `claude:` or bare model name runs there, not on the harness loop.

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
- **Hand steps go in the ask file.** When an agent blocks on something only you can do (a login, a signing
  certificate, a secret, a dashboard click), it writes the steps, their links and commands, and the inputs it
  needs to `<notes>/asks/<ID>.json`, and a secret goes to `<notes>/asks/<ID>.env`. Needs you shows them as
  steps with buttons and fields, so you need no terminal. An old script left in `<notes>/wizards/` shows as
  text steps and is never run.
- **Choices come as a pick sheet.** When an agent needs you to choose (options, settings to change or keep),
  it publishes a page of plain questions with the recommended answers preselected, and Needs you shows one
  line with its link. Send stores your picks on the page (its artifact db), where the control session reads
  them when you tell it "sent" (where the page cannot store them, Send gives a line to paste instead), or
  reply go for the recommended set; the task reopens with your answers noted (`agent-runner sheet <ID>`). `[run] questionnaires = false`
  turns it off.
- **One word per thing.** The first control session in a repo writes a starter GLOSSARY.md from the app's
  screens and code (10-20 terms), and later sessions add a term as you use it, each with your word, the
  screen's wording, the code names, a plain definition and the words to avoid; they only mention it in
  passing. Agents name new things with its terms. `agent-runner glossary [TERM]` shows it, `glossary add`,
  `forget`, `seed` and `scan` keep it (each commits itself); `[plan] glossary = false` turns it off (after
  [mattpocock/skills](https://github.com/mattpocock/skills) domain-modeling, MIT).
- **Your wording sticks.** Tell a control session "say agent, not slot", "shorter" or "no ids" and it adds
  one line to your voice file, `~/.config/agent-runner/voice.md` (all projects; `.runner/voice.md`, when it
  has lines, overrides it for one project), says which file, and words things that way from then on. When
  you ask "what?" or say back what it said in your words, it says it again plainly and offers one line to
  add, added only on yes. Every control session and the task agents (for the commit
  messages status and since show) read the file. "show my wording" prints it, "forget X" drops
  a line (`agent-runner voice show|add|forget`); `[run] voice` moves the file, `[run] voice_learn = "off"`
  stops the offers.
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
couldn't be merged. Edits of yours that a merge moved off the main checkout (`wip/main-checkout-*`) are
never deleted by the run: they show under Needs you in `status` and `since`, and
`agent-runner wip show|restore|drop NAME` looks at one, puts it in a `take` worktree, or deletes it.

## Used by

- **[opentennis](https://github.com/FIZL0/opentennis)**: a PS2 game remaster, one PCSX2 per slot.
- **[partyboard](https://github.com/FIZL0/partyboard)**: a Mario Party 4 port with online play.
- **[ps2-decomp-kit](https://github.com/FIZL0/ps2-decomp-kit-linux)**: a PS2 decompilation kit, wrapping it
  as `./kit run`.
- **[openmx](https://github.com/FIZL0/openmx)**: a PS2 game port built on the kit.

## Documentation

| | |
|---|---|
| [docs/SETUP.md](docs/SETUP.md) | installing, Windows, other providers and logins, adding it to a repo, wrapping it from your own CLI |
| [docs/STYLE.md](docs/STYLE.md) | how the run app looks, moves and speaks: read it before changing the page |
| [docs/REFERENCE.md](docs/REFERENCE.md) | picking, merging, fix and repair sessions, disk and memory limits, CI, the prompt, every command and config key |
| [CHANGELOG.md](CHANGELOG.md) | what changed in each version |
