# agent-runner

<p align="center">
  <a href="https://github.com/FIZL0/agent-runner/releases/latest"><img alt="Latest version" src="https://img.shields.io/badge/dynamic/regex?url=https%3A%2F%2Fraw.githubusercontent.com%2FFIZL0%2Fagent-runner%2Fmain%2Fagent_runner%2F__init__.py&search=__version__%20%3D%20%27(.*)%27&replace=v%241&label=version&color=2ea44f"></a>
</p>

agent-runner runs N terminal coding agents unattended against a git repository with a markdown task list.
By default every session is Claude Code (Opus), with its hooks and permission setup: no configuration needed.
Each session gets one task in its own git worktree and terminal (a tmux pane; on Windows a Windows
Terminal tab or console window). When a session finishes, the runner merges the branch, runs the test
gate, pushes, and starts the next task. It is independent of what the repository contains.

**Setting it up:** installing, adding it to a repo, wrapping it from your own CLI, and migrating a repo
that has its own copy are all in [docs/SETUP.md](docs/SETUP.md). Changes: [CHANGELOG.md](CHANGELOG.md).

- Python 3.11+ standard library only. Install it as a tool, or clone it and call `./run`.
- One CLI: `agent-runner plan …`, `agent-runner done …`, `agent-runner run …`, `agent-runner stop`
  (`./run …` in a clone is the same).
- One optional config file in your repo: `runner.toml`, or a table in your own config file.

**Other providers, through Pi:** for a model Claude Code doesn't serve (GitHub Copilot on github.com or an
enterprise host, Codex, other provider logins), sessions can run on
[Pi](https://www.npmjs.com/package/@earendil-works/pi-coding-agent) instead: `backend = "pi"` in `[run]`, or
`AGENT_RUNNER_BACKEND=pi agent-runner run once` to try it for one run without editing the config. A Pi session
runs the repo's Claude Code PreToolUse hooks (`.claude/settings.json`) too, so its guards hold. Pi on an
Anthropic model bills that account's extra usage, not the plan, so keep Claude models on Claude Code. Setup:
[Pi and enterprise Copilot](docs/SETUP.md#pi-and-enterprise-copilot). Which other terminal agents could become
backends, and the tests that decide it, are in [docs/AGENTS-EVAL.md](docs/AGENTS-EVAL.md).

```sh
uv tool install git+https://github.com/FIZL0/agent-runner    # latest; or pipx install …
cd your-repo
agent-runner plan                  # what the runner sees in plan/TODO.md
agent-runner run --dry-run 3       # what three slots would start right now
agent-runner run once              # one task, one session, then stop: try it like this first
tmux new -s runner agent-runner run 3
```

`examples/demo.sh` copies `examples/hello` (a tiny repo with a plan) to a temp dir, gives it a bare
"origin", and shows `plan`, `plan brief` and `run --dry-run` without starting any agent.
`examples/demo.sh --run` also runs `run once` there, which does start a real `claude` session.

## Why: the same tasks in a fifth of the context

Measured in opentennis. **Before:** each session loads the full Claude Code setup and reads the plan
itself to find its task.

```
prefix ............  50k
TODO.md ...........   8k
REFERENCE.md ......   9k
DONE.md ........... 150k
                   ─────
                    217k  ✗ over a 200k window before any work starts
```

**After:** each session gets a lean prefix plus a brief of its own task (its line, files and newest
journal entry).

```
lean prefix .......  17k
task brief ........   1k
                   ─────
                    ~20k  ✓ 180k (90%) left for the work
```

Medians over about 1,000 real sessions:

|                          | before  | after      |
|--------------------------|---------|------------|
| context at the first turn | ~48k    | **~20k**   |
| peak context             | 165k    | **~100k**  |
| tokens re-read per session | 9–18M   | **5.5–7M** |

In opentennis that came to about 1B fewer tokens re-read over its first week on the lean setup (about 390
sessions), with five sessions in parallel and every merge tested before it reaches the shared branch.

## Used by

- **[ps2-decomp-kit](https://github.com/FIZL0/ps2-decomp-kit-linux)**: a PS2 decompilation kit (`./kit run`).
- **[openmx](https://github.com/FIZL0/openmx)**: a PS2 game port built on the kit.
- **[opentennis](https://github.com/FIZL0/opentennis)**: a PS2 game remaster (`agent-runner run` directly; settings in `runner.toml`).

Project-specific behaviour is configuration: the test gate is a command, per-slot environment is a list,
and the files a conflict may be joined in are a glob list.

## How it works

```
plan/TODO.md ──pick──▶ slot N: git worktree ~/runs/<repo>/sN on task/<ID>
                         tmux pane sN: claude "<prompt + the task's brief>"
                         …the session works, then `./run done <ID> "msg"` (test gate → tick → commit → push task/<ID>)
                         Stop hook: quiet for [run] idle seconds → the session is ended
               ◀─merge── merge worktree ~/runs/<repo>/merge: merge main + task/<ID>, join line-records,
                         a fix session for real conflicts, the test gate on the merge
                         → land in the main checkout → reopen what it unblocked → push main
```

1. **Pick.** It reads `plan/TODO.md` *on the shared branch* (what is committed, not what you're
   editing) and walks it top to bottom. See [Picking](#picking) for what it skips.
2. **Start.** Slot N gets a git worktree in `~/runs/<repo>/sN` (`[run] home`) on branch `task/<ID>`, and a tmux pane in
   the window `agents-<repo>`. The pane's output is piped to `.runner/slotN.log`. The pane runs
   `claude --session-id … --model … "<prompt>"`, with Claude Code's Stop hook set to the runner's idle
   timer. The prompt includes the task's brief (`./run plan brief <ID>`): its line, its `plan/tasks/<ID>.md`
   long form, the files it names (or "missing: this task creates it"), and the newest journal entry.
3. **Finish.** The session ends with `./run done <ID> "msg"`. That runs the test gate, ticks the task
   (`[x]`, and the line moves to DONE.md), commits, and pushes `task/<ID>`. If the gate fails, nothing is
   ticked or committed. A session that's stuck runs `done --blocked "why"` instead.
4. **End the session.** The session goes quiet at its prompt. The Stop hook's detached timer sees no new
   transcript entries for `[run] idle` seconds (90) and ends it. If a human typed in the pane, or a usage
   limit is being waited out, the timer leaves the session alone. A session still running a background
   command (a `done` queued behind other test runs) is left alone until that command ends, up to 3 h.
   Whatever a session leaves uncommitted is saved on `wip/<ID>` (or `leftover/<ID>` when it has commits)
   before the slot is reset.
5. **Merge.** In a separate merge worktree, the runner merges `main` and `task/<ID>`:
   - TODO.md and DONE.md merge by section and task, not by line: git's merge driver for them
     (`agent-runner merge-plan`, set up by `run` in `.git/config` and `.git/info/attributes`) merges each
     task's box, text, notes and BLOCKED against the base, so a task one side ticked stays ticked, a
     heading one side moved comes out once, and two notes on one line are both kept;
   - conflicts in other record-per-line files (`[run] joinable`, e.g. a CHANGELOG) are joined, keeping
     both sides' lines;
   - any other conflict goes to a one-shot fix session (in the tmux window "master-<repo>", or `claude -p`);
   - the gate runs again if the merged code differs from what `done` tested.
   Only then is the main checkout moved to the tested merge. That takes seconds, it never stashes, and it
   waits if someone has uncommitted edits to the files involved.
6. **After the merge.** `plan reopen` unblocks tasks whose `(after X)` just landed and commits that.
   Then `main` is pushed (`[git] push_merge`), and the remote `task/<ID>` is deleted once the remote `main`
   contains it.
7. **Repeat** until nothing can start. Then the run [goes idle](#it-stays-up) and waits for new tasks.

### Terminals, and Windows

Each slot's session runs in a terminal you can watch and type into. Which one is `[run] mux` (or
`--mux`): `tmux` panes in the window "agents-<repo>" (the default on Linux and macOS; start the run inside tmux;
runners for different repos can share one tmux session, each finding only its own panes),
`wt` (a Windows Terminal tab per slot, in a window named "agents", the default on Windows), or `console`
(a console window per slot, Windows' fallback when `wt.exe` isn't installed). `none` (`--no-tmux`) is
the sequential run below. One slot, and `once`, run like any other count: a worktree, a pane, a tested merge.

On Windows the runner can't get the session's pid back from `wt.exe` (it only asks the running terminal
to open a tab), so every slot runs through a small shim, `run --slot-shim`. It starts the agent and keeps
its pid in `.runner/slotN.live` while it runs. The loop, a restarted run's adopt and the Stop hook read
that file. The rest of the Windows differences are in `agent_runner/plat.py`: the run lock is
`msvcrt.locking`, process checks go through kernel32 (stdlib `ctypes`, no psutil), an ended session's
windowed processes (an emulator, say) get WM_CLOSE and up to 10 s to exit before `taskkill /T /F`, and `[run] links` become a junction (directory) or hard link (file) when symlinks
need Developer Mode. Two things work differently there. Nothing captures a console's output, so
`.runner/slotN.log` has only the header lines and a usage limit is read from the transcript alone. A
prompt over 24,000 characters (a Windows command line holds 32,767) is handed over as a file the session
is told to read. `[run] test`, `on_exit`, `before_start` and the other commands run in the platform's
shell, which on Windows is `cmd.exe`.

`--no-tmux` (or no tmux / Windows Terminal installed) is the sequential run. It's one session at a time,
in your checkout, on the branch you have out. There's no worktree and no merge: `done` already ran the gate, and
the branch is pushed after each task.

## The task list

`plan/TODO.md` is ordinary markdown. The runner only looks at task lines under `###` headings:

```markdown
### Next (in this order)

- [ ] **P12** the parser reads nested lists → src/parse.py · tests/test_parse.py | t: tests/test_parse.py
- [ ] **P13** maps too → src/parse.py (after P12)
  - [ ] **P13a** the empty map
- [~] **P14** a fuzz harness → tools/fuzz.py BLOCKED: (after P12, P13) needs both grammars landed

### Later

- [x] **P10** …ticked lines move to plan/DONE.md under the same heading

### Stretch

- [ ] **P99** nice to have: a run never starts this section
```

- `- [ ]` is open, `- [x]` is done, `- [~]` is blocked. **Only the tool changes a box** (`plan tick`,
  `plan block`, `done`). A box edited by hand is how a task ends up done in one file and open in the
  other.
- `**ID**` is any token (`P12`, `bug-3`, `S41`). `plan add PREFIX` picks the next free one. `P13a` is a
  subtask of `P13`, and P13 and P13a are *family*, so they never run at the same time.
- The prefix says the kind of work. `[plan] kinds` names each letter (`B = "bug"`, `N = "netplay"`, …);
  the prompt lists them so an agent picks the right one, `plan kinds` prints them, and `plan add` refuses
  a letter the table lacks. With no table, the generic `B F T D R C` (bug, feature, tests and tooling,
  docs, research, cleanup) are suggested but not enforced.
- `plan add` also refuses (exit 3, nothing written) text that looks like an open task's work, naming it:
  `plan note` that task instead, or `--force` for different work. A task's own split (`plan add P13 …`)
  is never refused for looking like P13. `plan drop ID WHY` closes a task nobody will do (a duplicate,
  overtaken): archived with `dropped: WHY`, so its id stays used and what waits on it reopens.
- A note one side adds to a task the other side ticks is kept: the tick wins in TODO.md, and the runner
  appends the note to the task's line in DONE.md after the merge.
- `→ files…` lists the files the task will touch, separated by `·`, spaces or commas. Mode d uses this
  list to keep two running tasks off the same file, and the brief pastes those files in. Files that don't
  exist yet still count, and so do patterns: `dir/**` (everything under it) and `dir/*.rs`.
- `| t: tests` names the tests that prove it. `| j: dir` names its journal folder.
- `(after X, Y)` means don't start until X and Y are done. **Every id** in the parentheses counts.
- `BLOCKED: (after X, Y) why` is what `plan block`/`done --blocked` write. The `(after …)` list is what
  lets the run reopen the task by itself.
- `plan/tasks/<ID>.md`, if it exists, is the task's long form. The brief uses it instead of the one-line text.
  Long forms sit in `tasks/` so the plan's top level is TODO.md, DONE.md and the overviews a person reads
  (REFERENCE.md, HUMAN.md, batch briefs). A long form left at `plan/<ID>.md` still counts; move it with
  `git mv plan/<ID>.md plan/tasks/`.

`./run plan help` lists every subcommand: `next`, `<ID>`, `brief`, `tick`, `block`, `unblock`, `reopen`,
`add`, `move`, `note`, `newid` and `archive`.

### The plan in its own repo

By default the plan lives in the code repo, so every branch and clone has its own copy: two people (or two
machines running `run`) see each other's edits only after a code merge, which nearly always conflicts on
TODO.md. Give the plan its own git repo instead:

```toml
[plan]
repo = "git@github.com:you/project-plan.git"   # or a local path
# dir = "~/runs/<repo>/plan"     # where the clone goes (this is the default: `[run] home`/plan)
```

- One clone, outside the code, shared by the main checkout and every slot. Reads pull it (at most every
  20 s), every edit (`plan add/tick/block/…`, `done`, a run's reopens and filed tasks) locks it, pulls,
  commits and pushes. A rejected push pulls and pushes again; TODO.md and DONE.md merge by section and
  task (the same merge driver as in a repository), other `*.md` as `union`.
- **Claims: two people can run at once.** The moment a run picks a task (parallel or sequential), it
  pushes `claims/<ID>` (host and checkout) before anything starts. Other runs skip a claimed task and treat it as
  running there: a task sharing its files, its ordered section or its family waits for it. The claim
  holds the line's files and, refreshed as the session works, every file it has touched, so a task whose
  line lists too few is still kept clear. Two that claim one task at once conflict on push, and the later
  moves on; two that claim clashing tasks from plans read seconds apart both push, see each other, and the
  later claim gives way. A claim that cannot be pushed (offline) starts nothing, since nobody else would
  see it. The claim goes when the task merges or is left for a human, and a run drops any of its own
  claims on a task it neither runs nor holds a branch for. A blocked task's finished branch (a concept
  round handing over) is merged like an open one's, journal and all.
- **Who has what.** `plan` marks each claimed task, `[ ] B12  [alex@laptop 14:02 v0.14.0]`; `plan claims`
  lists them all. A live run re-stamps its claims every 15 min, so a claim not refreshed in 90 min shows
  `STALE` and holds only its own task, not its files, and every other run logs it once: a crashed run's
  claims would otherwise hold those tasks for good. A claim from a runner older than 0.14 shows `pre-0.14`,
  and every other run warns once: that runner does not keep off their files, so upgrade every machine. The same
  checkout takes its own back on its next run; for anyone else's, `plan unclaim <ID>`.
- **Tick on landing.** `done` in a slot leaves the task open and the run ticks it once the merge lands,
  noting `landed <sha>`; a merge left for a human leaves it open, as in-repo. `done` outside a run (a
  person's session) ticks at once. `--blocked` blocks at once either way.
- `tasks/<ID>.md` long forms, `REFERENCE.md` and `HUMAN.md` live in the plan repo; `[plan] journal` stays in the
  code repo, since journals describe code and travel with it.
- `dir` outside the repo without `repo` (a synced folder) shares one copy the same way, without git.
- Moving an existing plan over, keeping its history: `git subtree split -P plan -b plan-only`, push that
  branch to the new repo as `main`, set `[plan] repo`, then `git rm -r plan` in the code repo.

## What runs when

Each free slot reads `plan/TODO.md` from the top and starts the first task it's allowed to, so the order of the
lines is the order of the work. `plan add` puts a person's new task at the top; `plan add PREFIX TEXT @ after ID` or
`plan move ID after ID` puts it where you want it.

A follow-up an agent files gets a level (`--pri`, default `normal`), tagged on its line as
`(follow-up, LEVEL)`, and is filed so the work a person queued comes first:

| level | filed | for |
|---|---|---|
| `critical` | top of the leading section, behind earlier critical ones | it breaks or blocks other work (the text says what) |
| `normal` | `### Follow-ups`, made after the person's sections (before Stretch/Parked) | the usual follow-up |
| `low` | the same section, behind every normal one | a check, a small tidy-up |
| `later` | `### Parked`, which a run never starts | big future work, for a person to schedule |

A test that fails under load and passes alone (a `retest` pass, or a name `[run] flaky` finds in a passing
gate's output) gets a `critical` follow-up to make it robust when the merge lands, unless an open task
names it already. So does a test the memory watch ended (below): the runner names it from the killed
process's thread names and the binary's `--list`, and the task says how much it held and where.

The run reads GitHub Actions too. By default (`[run] ci_watch = "auto"`) it watches every workflow in
`.github/workflows/` that runs on a push to the shared branch, and only those workflows' push runs, so a
nightly, release or manual run never files a task; `ci_watch = ["pages.yml"]` names workflows instead (any
event), and `ci_watch = false` turns it off. Every 5 min (and only when no merge holds the lock) it asks
`gh` for the newest finished run of each workflow on the shared branch. A `gh` that cannot see the repository
(not installed, not logged in, the wrong account) is said once in the run log rather than read as "no runs". A red one
(a cancelled run says nothing; the one before it decides; while a newer run is under way, nothing is judged)
is first run again, its failed jobs only (`gh run rerun --failed`, `[run] ci_rerun`), since a runner GitHub
never handed the job or a network outage reads as red too; only a red second attempt gets a single `critical` task, its failed jobs on the
line and the last 40 lines of `gh run view --log-failed` in `plan/tasks/<ID>.md`. No second one while that task
is open, and no run is judged twice (`<notes>/ci-<workflow>.seen`), so a broken workflow is one task, not
an email per push. Landing never waits on CI.

Several slots run at once, so **a task that has to wait for another must say so in a way the runner reads**.
Writing "follows A12" in its text isn't enough: if A12 hasn't started, the task starts beside it.

| to make B wait for A | do this | what happens |
|---|---|---|
| B is part of A's work | `plan add A12 "…"` gives `A12a`, then `A12b` | one family (A12, A12a, A12b) never runs two tasks at once, so they go one at a time, top to bottom |
| B needs A merged first | `plan block B3 --after A12 "why"` | B3 stays `[~]` until A12 is done, then the run reopens it |
| a list that must go in order | a section heading starting with *Next* or saying *in this order* | one task from it runs at a time (mode d only) |

A plain new number (`plan add A "…"`) is an independent task and may run beside anything. `agent-runner help order`
prints this summary; `./run run --dry-run N` shows what N free slots would start now, and why the rest wait.

## Picking

`pick` walks TODO.md in order and starts the first task that passes all of these checks. The order is the
file's, except that a task a waiting one depends on (`(after X)` on an open line, `BLOCKED: (after X)` on a
blocked one) moves up to where that one stands, down the whole chain: a Next task blocked on a Follow-up
does not wait behind every task between them. The plan read is the shared branch's, or its remote's when a
push from outside the run has put that ahead (fetched at most once a minute).

| skipped | why |
|---|---|
| `[~]` blocked, and split parents (a task with open subtasks) | the subtasks are the work |
| an open `(after X, Y)`, for **any** id listed | every listed dependency must be done |
| a line that names a running task's id | prose such as "uses P36's menu" is treated as a dependency |
| a sibling of a running task (same family) | P13 and P13a edit the same thing |
| a task in a section whose heading starts with *Next* or says *in this order*, while another task from that section runs | an ordered section runs one task at a time |
| `### Stretch`, `### Parked` | never unattended |
| tried this run | one attempt per run: if it failed, a human looks next |
| `task/<ID>` has commits not yet merged | it's finished and waiting for the merge |
| mode d: names a file a running task names (minus `[run] shared_files`) | keeps merges clean |

A line's files are its `→` list when it has one; the prose's file names count only on a line without one, so
"uses what race.rs has" before `→ src/menu.rs` does not hold the task off `race.rs`. With `[plan] need_files`,
each merge also gives a line written into TODO.md by hand (not through `plan add`) its prose's files, and logs
one naming none.

Mode **d** (the default) runs tasks in parallel on different files. Mode **p** follows strict plan order
and lets files overlap, which is useful when the order matters more than clean merges.
`./run run --dry-run N` prints what N free slots would start, and what's waiting and why.

## Behaviour

**Blocks reopen themselves.** `done --blocked WHY` records the open task ids that WHY names (or
`--after X,Y`) as `BLOCKED: (after X, Y)`. After every merge, `plan reopen` sets the task back to `[ ]`
once all of those ids are done, and the run picks it up again.

**Unmergeable branches are parked.** A conflict the line join cannot resolve goes to a fix session
(below). A branch the fix session gives up on is renamed `wip/<ID>` and pushed; the task is open again,
and its next prompt points at the earlier attempt.

**Merges happen in a merge worktree.** The merge is built and tested in `~/runs/<repo>/merge`; the main
checkout moves only to a tested commit, and nothing in it is stashed. Nor is its branch ever switched: while
it has another branch than `main` out, a tested merge stays `task/<ID>` and lands once `main` is out again.

**Commit your own edits in the main checkout.** A merge lands only when no uncommitted edit there touches
a file it changes, and nearly every merge changes `TODO.md`. `run plan add/note/move/tick/block/unblock/
reopen`, run by hand in the main checkout, therefore commits the plan immediately (not mid-merge, and not
in a worktree, where `done` commits). For code work alongside a run, use your own worktree
(`git worktree add ../<repo>-<slug>`, or `claude -w <slug>`) and merge it when done; never use a slot's
worktree, which the runner reuses.

**The shared branch is pushed only after a merge passes the gate.** `done` pushes `task/<ID>` and
refuses to push `main`.

**A usage limit is not a failed task.** When a session's only outcome is the usage limit (its transcript
or slot log says "resets 3pm"), the transcript is dropped, the task returns to the pool, and the slot
sleeps until the reset. Past `[run] weekly_max`% of the 7-day usage, no new task starts unless `--force`
is given.

**A cut-off session resumes.** A session whose turn ended on an API error (the network dropped, the
API was down) is not finished, though the idle stop ends it. Its worktree is left as it is, and once the
API answers again it is resumed in the same slot (`claude --resume`, with its whole conversation) and told
it was cut off. While the API cannot be reached, no session resumes or starts. At startup, a slot still on
`task/<ID>` whose session stopped mid-turn while no run was up (a reboot, the runner killed) is resumed
the same way. A usage limit or a request the API refused is not a cut-off, and one session is resumed at
most 3 times. `./run resume <ID>` resumes a task's last session by hand, for one the run already ended:
when its slot is free, the edits it left come back from `wip/<ID>` (kept as `resumed/<ID>`).

**Idle stop.** The Stop hook starts a detached timer; a session quiet for `[run] idle` seconds is ended.
The timer does not fire on a session a human has typed into, or one waiting out a usage limit. Nor on
one whose agent still has a child process (a background command), until it ends or
`AGENT_RUNNER_IDLE_MAX` (10800 s) has passed since the stop.

**Nothing uncommitted is lost.** When a session ends with edits it never committed, the runner commits
them onto `wip/<ID>` if the task has no commits (the next attempt is told to read it), or onto
`leftover/<ID>` otherwise, so the merge never takes in untested edits; both are pushed. Only then is
the slot reset.

**Stall watchdog.** A session quiet at a prompt with no tool running for `[run] stall` seconds (20 min),
or quiet for over 65 minutes with a tool running, is logged with the terminal to look at, and the bell
rings.

**A line that names a running task waits.** A task whose line mentions a running task's id is not
started alongside it.

### Disk

Each slot, and the merge worktree, keeps its git-ignored build output between tasks, since a warm build is
faster than a cold one. That is one full copy of the project's builds per worktree, and a task that builds
into a folder of its own leaves another behind every time. So, by default:

- **A worktree over `slot_max_gb` (50) is trimmed** before its next task, never while a session works in it:
  its least recently written git-ignored parts go until it is at half the cap. Big folders are looked into
  (`target/debug/incremental`, old-hash libraries in `deps/`, `build/<old task>`), nothing under 1/500 of
  the cap (100 MB) goes, so the builds recent tasks used stay warm and stray small files stay put.
- **Under `min_free_gb` (10) free on the disk**, every free worktree is cleaned whole, and while the disk
  stays that full no new task starts: the run logs why and waits for room.
- **Slots past the count are removed.** Lower `slots` and the next run deletes the extra `sN` worktrees
  (an adopted session there finishes first; one with uncommitted work is kept and logged).

The whole clean is `git clean -ffdXq`: everything git ignores goes, and `links` are put back. A project that
knows its layout better sets `slot_clean`, which then runs in both cases instead, e.g. one that drops only
per-task build folders and keeps the shared ones: `slot_clean = "rm -rf build/task-* out/runs"`.

Memory is watched the same way (Linux), every 10 s, over the run's own processes: anything working in one
of its worktrees or started from a slot, the agents themselves aside.

- **A process past `proc_max_gb`** (`"auto"`: a quarter of the machine's memory) is killed, that process
  alone: its gate or session sees one test die and goes on, and the run logs `ended pid …` with the
  command. A test walking a looping tree held 52 GB in each of three gates at once before this. When the
  process was a test binary, the test it was running gets a `critical` task at the next merge.
- **Under `min_free_mem_gb` (4) available**, the run's biggest process (if it holds a GB) is killed instead.

### It stays up

The parallel run never exits on its own. Only `once` ends by itself; otherwise use Ctrl-C or
`./run stop`. When there's nothing it may start and nothing running or merging, it logs this once:

    run idle: no task it may start; waiting for TODO.md to change (Ctrl-C or ./run stop to end it)

It keeps re-reading TODO.md on the shared branch every few seconds, so tasks you commit later start
without a restart. When it starts work again it logs `run busy: new work (<ID>)`. The sequential run does
the same thing, checking every 30 s.

A tried task normally stays tried for the rest of the run. But if its line closes (`[~]`) and later
opens again (a human ran `plan unblock`), that's a new attempt, so it goes back in the pool and the log
says `<ID>: open again since it was tried; back in the pool`.

A script waiting on a run should watch `.runner/run.log` for a `run idle` line written after it started
waiting, not for the process to exit. `run busy` means work started again.

### Stopping a run

Ctrl-C ends the run at once and cuts every session off mid-task. To stop gently, **type `s` + Enter in
the runner's pane** (the one you started `./run run` in), or run `./run stop` from anywhere. Either way
nothing new starts, the running tasks finish and merge, and then the run logs `run stopped (s)` (or
`run stopped (./run stop)`) and exits with 0. Typing `s` again before then takes the stop back, and tasks
start again.

Both write `.runner/STOP` (with who asked), and the loop checks that file on every pass, so `s` can take
back a `./run stop` and the reverse. A daemon thread reads the runner's terminal (it works on Windows
consoles too) and only starts when stdin is a terminal. The sequential run has no `s` key, because its
agent session reads the same terminal; use `./run stop` there, which takes effect between tasks. A STOP
file left behind by a run that was killed is cleared when the next run starts.

A merge a run was in the middle of is adopted by the next run too, like the slots' sessions. Its gate
runs in a session of its own (`.runner/gates/<key>.json`), and a fix or repair session in the master window
records itself in `.runner/master.json`; both outlive the runner. The restarted run waits for them,
keeps what they made (a passing gate per tree and gate command in `.runner/gates/`, a session's commit
under `refs/agent-runner/held/<ID>/`), builds the merge again and reuses them instead of doing that
work a second time. The startup log says `<ID>: its merge was under way when the last run ended;
adopting it`, or `<ID>: finished, not merged yet; merging it now` for a branch that only waited its
turn.

### Fix sessions

A conflict the line join cannot resolve goes to one fresh session, run with the conflict in place. With
`[run] fix_ahead` (the default) that happens before the merge lock is taken: the task's branch is merged
into the shared branch's head in a fix worktree of its own (`.runner/slots/fix1`, `fix2`, …, kept so their
builds stay warm; at most `fix_ahead_max`, 2, at once, the others waiting a turn, and each waiting on
`before_start` as a slot does), the session commits the resolution there, and the runner keeps it as
`refs/agent-runner/fixed/<ID>/<sha>`. Other tasks merge and gate meanwhile. The task then takes the lock with
that merge, which goes in clean unless the shared branch touched the same lines again in the meantime: then
it goes back out for another, smaller fix. Its third try fixes under the lock, in the merge worktree. Under tmux it is an interactive session in a window of its own, "master", so you can
watch it or take it over by typing; its Stop hook ends it once it has been idle 90 s after its answer
(without tmux, where there is no window for it: `claude -p`). Its prompt (`FIXER` in `runner.py`) includes the tail of the ledger. It either
commits the resolution or runs `git merge --abort` and states why; its output goes to
`.runner/fixer.log`. It is capped at `[run] fix_timeout` (30 min); ahead of the lock that holds up only
its own task. Set `fix_merges = false` to park every such conflict as `wip/<ID>` instead. With `[run] build`
set, the fix session runs it before it commits and fixes what the two sides broke between them: git
merges the files it did not stop on without reading them, so a function both sides added under one name
builds on neither side's branch and breaks only the merge.

A merge that fails the gate (and not because of load, or a failure its base has too) gets one repair
session before it is parked: the same kind of session, in the merge worktree on the committed merge, with
the gate's output (`.runner/merge-gate.log`). It commits a fix on top, or nothing and says why. The gate
then runs once more; a second failure parks the branch as before. A repair is replayed onto the merge when
the shared branch moves during the tests and the merge is built again. `repair_merges = false` parks at
the first failure.

A batch (`batch = true`) is repaired the same way, as a whole: when the branches merged together fail the
gate, one repair session sees every merge in the batch (`REPAIR_BATCH`) and fixes where they clash, and the
gate runs once more for all of them. Only if that fails too is the batch split, each branch merged on its
own. A rider whose conflict the line join cannot do waits for its own turn, where it is fixed ahead of the
lock; with `fix_ahead = false` it gets its fix session inside the batch and shares the batch's gate run.

Tasks that finish while a batch is in its gate do not wait for it to end (`merge_ahead = true`). They are
merged on top of the merge under test in a second worktree (`.runner/slots/merge2`) and their gate starts
beside that one. When the first batch lands, the next one's turn finds the same merge built ahead and
waits for the gate already under way on that exact tree, so two batches cost about one gate's wait. If
the first batch fails or the branch moves another way, the merge built ahead is dropped and its gate
stopped. Its conflicts get only the line join: one that needs a fix session waits for its own turn. The
first gate in merge2 builds from cold, and merge2 has a build directory of its own.

A tested merge that cannot land because of uncommitted edits in the main checkout to files it changes (or
anything staged there, which git refuses to merge onto) waits 10 minutes, then gives the merge lock back
and stays `task/<ID>`; it is merged again once those files are committed. It is never parked for that.

A merge skips the gate only when `task/<ID>` is the very tree `done`'s gate passed on (recorded as
`refs/agent-runner/tested/<ID>`) and the merge differs from it only in `[run] untested` files. After
`done --no-test`, commits made after `done`, or a session that never ran it, the merge is tested.

## Working with it well

- **Small tasks that name their files.** One session, one task, one commit is the unit. A task line that
  says `→ src/a.py · tests/test_a.py` lets mode d run tasks side by side and gives the brief the right
  files. A task that would take a human more than an afternoon should be split into subtasks first.
- **Write dependencies as `(after X)`, not prose.** The run reads ids, not sentences.
- **Keep an ordered "Next" section.** `### Next (in this order)` runs strictly one task at a time, top
  down. Put the critical path there and the independent work under other headings, so other slots stay
  busy.
- **One task per session.** The prompt says "do task X and nothing else". Follow-ups go in with
  `./run plan add`, not into the same branch.
- **Journal and notes.** Set `[plan] journal` and each session writes `journal/<date>-<id>-<slug>/` (or, with
  `journal_layout = "id"`, `journal/<ID>/notes.md` and a retry's `journal/<ID>/<date>-<slug>/notes.md`): what
  it did, what failed, and a **Not verified** list. The newest entry for a task goes into the next brief,
  so a retry starts from what the last attempt learned.
- **A real test gate.** `[run] test` is the only thing between an unattended session and `main`. Make it
  fast enough to run on every `done` and every merge, and strict enough that you trust it.
- **Slots.** Start with `once`, then 2 or 3. More slots only help if the plan has that many tasks on
  different files. Past that, slots sit idle or the merges get harder. Usage limits are per account, so
  five slots use them up five times faster.
- **`shared_files` and `joinable`.** A CHANGELOG every task appends to should be in both lists:
  `shared_files` so mode d doesn't treat it as overlap, and `joinable` so a conflict in it is joined
  rather than sent to a fix session.

### The prompt

The first turn of every session is `PROMPT` in `agent_runner/runner.py`, filled in for the task. It says:
nobody will answer questions, do this task only, commit only on `task/<ID>`, read the rules file, pass
the gate, keep a journal, finish with `done` (or `done --blocked … --after …` when stuck), a usage limit
isn't being stuck, use `plan` as a tool rather than reading TODO.md, and never hand-edit a box. Then
comes the brief.

You can customise it in three ways, from smallest to largest:

- `[run] rules = "AGENTS.md"` sets the file the prompt tells the session to read first.
- `[run] prompt_extra = "…"` adds one paragraph, for example "slot 1 owns the UI, slot 2 the engine".
- `[run] prompt = "tools/prompt.txt"` replaces the whole template. Placeholders: `{tid} {n} {runner}
  {branch} {others} {earlier} {rules} {test} {journal} {extra} {brief}`. Any other `{name}` is left as it
  is.

Each session also gets `AGENT_RUNNER=1` and `[run] slot_env` (default `AGENT_SLOT={n}`) in its
environment, so your tools can tell slots apart, for example to give each one its own port or emulator
instance.

`include_task_id_in_commit = false` tells sessions to omit the task ID from the commit subject; `done` also
removes a leading `<ID>:` if a session includes one anyway. The default is `true`. `comment_policy = "minimal"`
asks sessions to add comments only when they explain non-obvious intent or constraints. The default is `"normal"`.
These policy instructions are appended to built-in and custom prompts.

### After a run

To end the run first, type `s` + Enter in its terminal ([Stopping a run](#stopping-a-run)) and let
the running tasks merge. A run left up keeps picking up whatever you commit to TODO.md.

1. `.runner/ledger.md` has one line per branch: merged, blocked, reopened, or **LEFT FOR A HUMAN, and
   why**.
2. `git branch --list 'wip/*'` lists branches that couldn't be merged. Merge one by hand, or delete it and
   let the task run again.
3. `./run plan` shows what's blocked (`[~]`). Each block says what would unblock it. `./run plan unblock
   ID "decided: …"` puts a task back, and a run that's still up picks it up again.
4. `.runner/run.log` is the full timeline. `.runner/slotN.log` is what each pane showed, and
   `.runner/fixer.log` is what the fix sessions decided.
5. The `journal/` entries' **Not verified** lists tell you what to check yourself.
6. `agent-runner cost` shows where the workers' tokens went: each kind of tool call (`git log`, `sed`,
   `python3 tools/x.py`, `read`), by its results' size times the turns they stayed in context, since that is
   what a session pays for. A command that tops it is worth an outline (`[plan] outline`), a quieter
   flag, or a line in the prompt. It reads the last 7 days of this repo's slot and merge sessions, Claude
   and Pi (`--days N`, or name transcripts).

## Commands

```
./run plan [...]                       the task list as a tool (./run plan help)
./run done ID "MSG" [--blocked WHY [--after X,Y]] [--no-test] [--skip-check]
./run run [N|once] [--mode d|p] [--dry-run] [--no-tmux] [--mux tmux|wt|console|none] [--model M] [--idle S] [--stall S] [--pause S] [--force] [--shutdown]
./run stop                             finish what's running, start nothing new, exit (or s + Enter in the runner's pane)
./run resume ID...                     continue each task's last session in its slot, once that slot is free
./run --version
```

`agent-runner` is the same CLI. `--no-test` skips the gate, and `--skip-check` skips `[run] precommit`.
`--shutdown` powers the computer off once no task is running or merging and no open task can start, after
120 s idle; new work in that window cancels it. On Linux it runs `systemctl poweroff`, which needs the
logged-in session's polkit permission; if the command is refused the run stays up.

`plan` and `done` work on the checkout you're in (the agent's worktree). `run` always merges into the
main checkout. Set `AGENT_RUNNER_REPO` to use a repo from outside it.

## runner.toml

Every key is optional. Without a `runner.toml` you get the plan in `plan/`, no gate, 3 slots, and pushes
to origin. A worktree without its own `runner.toml` (because it's git-ignored) reads the main checkout's.

If `AGENT_RUNNER_CONFIG` names a file, the settings come from that file instead: from its
`[agent-runner]` table (`[agent-runner.run]`, …) if it has one, else from its top level. This lets a
project keep them in its own config file (see [docs/SETUP.md](docs/SETUP.md#wrapping-it-from-your-own-cli)).

**`runner.local.toml` is one machine's settings.** Laid over the shared file key by key, table by table, it
changes what one person needs without editing what everyone shares: a lower `weekly_max` for a smaller
plan, fewer `slots` on a laptop, another `model`. `run` creates it in the main checkout when it is missing,
all comments so it changes nothing, and never rewrites it after that; it keeps it out of git through the
clone's `.git/info/exclude`, so neither a `git add` nor another person sees it. Worktrees read the main
checkout's.

```toml
# runner.local.toml
[run]
weekly_max = 50
slots = 2
```

```toml
[plan]
dir = "plan"              # TODO.md, DONE.md, tasks/<ID>.md; outside the repo, one copy for every worktree
repo = ""                 # the plan in its own git repo (see "The plan in its own repo")
journal = ""              # e.g. "journal": per-task folders, the newest pasted into the brief
journal_layout = "dated"  # or "id": one folder per task, journal/<ID>/, a retry dated one folder down
brief_extra = ""          # a command whose output ends the brief; {id} is the task id
outline = ""              # a command printing one file's outline; {file} is the path, e.g.
                          # "python3 tools/outline.py {file}": the brief shows it under each file the line names
brief = ""                # a command whose output *is* the brief (the project's own brief tool); {id}
kinds = {}                # id prefix -> kind of work, e.g. { B = "bug", N = "netplay" }; `plan add` keeps to it
need_files = false        # `plan add` refuses a line naming no file and no test; prose files become its → list

[git]
master_branch = ""        # optional local shared branch; must exist and be checked out
# empty uses remote HEAD, then main/master/trunk, then the current branch
push = "origin"           # where finished work goes; false turns every push off
push_merge = true         # push the shared branch after each tested merge

[run]
test = ""                 # the gate, run by `done` and on every merge, e.g. "make test"
slots = 3
mux = ""                  # tmux, wt, console or none; "" = tmux (Windows: wt, else console)
mode = "p"                # p: plan order; d: different files
include_task_id_in_commit = true
comment_policy = "normal"
agent = "claude"
backend = ""              # claude or pi; empty detects pi from the agent executable's name
model = "opus"
lean = true               # sessions get Bash/Read/Edit/Write only, no MCP servers or user settings
idle = 90                 # s quiet after finishing before a session is ended
stall = 1200              # s quiet at a prompt that counts as stalled
pause = 60                # s between one session ending and the next starting in that slot
weekly_max = 90           # % of 7-day usage past which nothing new starts
notes = ".runner"         # logs + ledger (git-ignore it)
links = []                # git-ignored paths symlinked into every worktree (data, big files)
copies = []               # git-ignored files copied into a new worktree once (a local config file)
slot_env = ["AGENT_SLOT={n}"]   # {n}: the slot, {slots}: how many
pass_env = []             # the runner's own environment variables handed on to every slot
on_exit = ""              # command run in a slot's worktree, with its env, when its session ends
rules = ""                # "AGENTS.md", "CLAUDE.md", …
prompt = ""               # a template file replacing the built-in prompt
prompt_extra = ""         # added to the prompt; takes its placeholders ({n}, {id}, {runner}, …)
command = ""              # what sessions are told to type (default: this runner), e.g. "./kit"
precommit = ""            # a second check `done` runs before it ticks; `done --skip-check` skips it
suspect = ""              # regex: a BLOCKED line a merge adds that matches it is flagged in the ledger
untested = ["*.md"]       # globs the gate can't see ("!glob" takes one back): no retest for these alone
failures = ""             # regex, group 1 = a failing test's name in the gate's output
retest = ""               # the gate for just {names}: rerun alone (load), then on the base (already failing)
flaky = ""                # regex, group 1 = tests a passing gate passed only on its own rerun (comma-separated)
flaky_kind = "T"          # the prefix of the critical "make <test> robust" follow-ups
ci_watch = "auto"         # "auto": workflows run on a push to the shared branch; ["pages.yml"]; false: off. A red newest finished run on the shared branch
                          # files one critical task (needs `gh` logged in)
ci_kind = "B"             # the prefix of that task
ci_rerun = true           # a red run's failed jobs are run once more before a task is filed (GitHub's own outages)
batch = true              # finished branches waiting for the merge go in together under one gate run, and one push
merge_ahead = true        # tasks finishing during a batch's gate are merged on it and tested beside it
before_start = ""         # a command that must pass before any session starts (a display, a device)
not_attempt = ""          # regex on a branch's last commit subject ({id}): a phase, not the run's one try
shared_files = []         # files nearly every task names; mode d ignores them
joinable = []             # globs of record-per-line files a conflict may be joined in (TODO.md, DONE.md merge by task)
fix_merges = true
fix_model = "opus"
fix_timeout = 1800
fix_ahead = true          # fix a conflict before the merge lock, in a fix worktree: other merges go on meanwhile
fix_ahead_max = 2         # fixes ahead at once (and so fix worktrees, fix1…): the rest wait their turn
build = ""                # a quick build a fix or repair session runs before it commits (not the gate)
repair_merges = true      # a merge failing the gate gets one repair session before it is parked
home = "~/runs/{repo}"    # the worktrees (s1…, merge) and a [plan] repo clone (plan/), outside your
                          # repos folder; {repo} = the checkout's folder name. AGENT_RUNNER_HOME overrides
                          # it on one machine. Worktrees still in the old <repo>-slots/ are used until moved
                          # Scripts ask `agent-runner home [slots|plan]` rather than rebuild the path
slot_max_gb = 50          # a worktree over this loses its stalest build output before its next task; 0 = never
min_free_gb = 10          # under this much free disk: free worktrees cleaned, no new task starts; 0 = never
proc_max_gb = "auto"      # a process of the run's resident past this is killed; "auto": a quarter of RAM; 0 = never
min_free_mem_gb = 4       # under this much memory available: the run's biggest process is killed; 0 = never
slot_clean = ""           # a project's own clean, run instead of the trim and the full git clean -ffdXq
timeout = 3600            # s the gate, a retest or a hook (join, before_start, on_exit) may run: past it, failed

[run.join]                # glob = a command that joins a conflict in that file itself:
# "data/addresses.txt" = "./tools/join {union} {out}"   # also {ours} {base} {theirs} {file}; exit 0 keeps {out}

[git]
push = "origin"           # false: never push
push_merge = true         # push the shared branch after each tested merge
```

## What it leaves out

Nothing project-specific is built in. A project supplies it through hooks: a program per slot
(`slot_env`, `on_exit`), a check on new block reasons (`suspect`), a custom conflict join
(`[run.join]`), and an extra pre-commit check (`precommit`). The ps2-decomp-kit mapping is in
[docs/SETUP.md](docs/SETUP.md#worked-mapping-ps2-decomp-kit).

## A program per slot

Some tasks need a running program of their own: an emulator to record from, a browser, a device, a dev
server on a port. Give each slot its own copy and let the runner tell it which:

- `slot_env` hands every slot its number, so the project's tools pick their copy: a port, a profile
  directory, a lock file. `EMU_SLOT={n}` and a launcher that reads it is all it takes.
- `pass_env` passes on what the whole run shares (a cap on how long one session may hold the program).
- `on_exit` closes the slot's copy when its session ends, with that slot's env.
- `before_start` holds new sessions while the program cannot run (no display, device unplugged). The run
  logs it once, rings the bell, and resumes once the check passes.
- `prompt_extra` tells the session it has its own copy and how to drive it (`{n}` is the slot).
- `links` symlinks the program's big git-ignored inputs into every worktree.

opentennis runs one PCSX2 per slot this way. Its mapping is in
[docs/SETUP.md](docs/SETUP.md#worked-example-opentennis).

## Library

`from agent_runner import plan, done, runner` and the names in each module's `__all__` are a stable API,
so a project's CLI can be thin wrappers (`plan.main(argv)`, `done.main(argv)`, `runner.cmd_run(argv)`).
See [docs/SETUP.md](docs/SETUP.md#wrapping-it-from-your-own-cli).

## Tests

```sh
python3 tests/test_plan.py      # the plan tool
python3 tests/test_home.py      # [run] home: default, overrides, the pre-0.13 places
python3 tests/test_disk.py      # slot_max_gb, min_free_gb, extra slots removed
python3 tests/test_cost.py      # agent-runner cost: kinds of call, size × turns, Claude and Pi transcripts
python3 tests/test_plansync.py  # [plan] repo: two checkouts on one plan repo, merges, claims, tick on landing
python3 tests/test_runner.py    # picking, done, merge/join/land/push, fix sessions, wip parking,
                                # retry after unblock, prompt, Stop hook, usage limits, adopt,
                                # batches, flaky/inherited failures, the platform layer and the
                                # Windows slot shim (temp repos, fake agent)
python3 tests/test_pi.py        # Pi configuration, prompts, sessions, errors, and merge fixers (no network)
python3 tests/agent_matrix.py   # which terminal agents are installed and have the flags a backend needs;
                                # --live runs tiny real tasks (needs a login, spends tokens)
```

## License

MIT
