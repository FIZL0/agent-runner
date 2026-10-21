# agent-runner

agent-runner runs N Claude Code sessions unattended against a git repository with a markdown task list.
Each session gets one task in its own git worktree and terminal (a tmux pane; on Windows a Windows
Terminal tab or console window). When a session finishes, the runner merges the branch, runs the test
gate, pushes, and starts the next task. It is independent of what the repository contains.

**Setting it up:** installing, adding it to a repo, wrapping it from your own CLI, and migrating a repo
that has its own copy are all in [docs/SETUP.md](docs/SETUP.md). Changes: [CHANGELOG.md](CHANGELOG.md).

- Python 3.11+ standard library only. Install it as a tool, or clone it and call `./run`.
- One CLI: `agent-runner plan …`, `agent-runner done …`, `agent-runner run …`, `agent-runner stop`
  (`./run …` in a clone is the same).
- One optional config file in your repo: `runner.toml`, or a table in your own config file.

```sh
uv tool install git+https://github.com/FIZL0/agent-runner@v0.3.1    # or pipx install …
cd your-repo
agent-runner plan                  # what the runner sees in plan/TODO.md
agent-runner run --dry-run 3       # what three slots would start right now
agent-runner run once              # one task, one session, then stop: try it like this first
tmux new -s runner agent-runner run 3
```

`examples/demo.sh` copies `examples/hello` (a tiny repo with a plan) to a temp dir, gives it a bare
"origin", and shows `plan`, `plan brief` and `run --dry-run` without starting any agent.
`examples/demo.sh --run` also runs `run once` there, which does start a real `claude` session.

## Used by

- **[ps2-decomp-kit](https://github.com/FIZL0/ps2-decomp-kit-linux)**: a PS2 decompilation kit (`./kit run`).
- **[openmx](https://github.com/FIZL0/openmx)**: a PS2 game port built on the kit.
- **[opentennis](https://github.com/FIZL0/opentennis)**: a PS2 game remaster (`tools/parallel.py`).

Project-specific behaviour is configuration: the test gate is a command, per-slot environment is a list,
and the files a conflict may be joined in are a glob list.

## How it works

```
plan/TODO.md ──pick──▶ slot N: git worktree <repo>-slots/sN on task/<ID>
                         tmux pane sN: claude "<prompt + the task's brief>"
                         …the session works, then `./run done <ID> "msg"` (test gate → tick → commit → push task/<ID>)
                         Stop hook: quiet for [run] idle seconds → the session is ended
               ◀─merge── merge worktree <repo>-slots/merge: merge main + task/<ID>, join line-records,
                         a fix session for real conflicts, the test gate on the merge
                         → land in the main checkout → reopen what it unblocked → push main
```

1. **Pick.** It reads `plan/TODO.md` *on the shared branch* (what is committed, not what you're
   editing) and walks it top to bottom. See [Picking](#picking) for what it skips.
2. **Start.** Slot N gets a git worktree in `../<repo>-slots/sN` on branch `task/<ID>`, and a tmux pane in
   the window `agents`. The pane's output is piped to `.runner/slotN.log`. The pane runs
   `claude --session-id … --model … "<prompt>"`, with Claude Code's Stop hook set to the runner's idle
   timer. The prompt includes the task's brief (`./run plan brief <ID>`): its line, its `plan/<ID>.md`
   long form, the files it names (or "missing: this task creates it"), and the newest journal entry.
3. **Finish.** The session ends with `./run done <ID> "msg"`. That runs the test gate, ticks the task
   (`[x]`, and the line moves to DONE.md), commits, and pushes `task/<ID>`. If the gate fails, nothing is
   ticked or committed. A session that's stuck runs `done --blocked "why"` instead.
4. **End the session.** The session goes quiet at its prompt. The Stop hook's detached timer sees no new
   transcript entries for `[run] idle` seconds (90) and ends it. If a human typed in the pane, or a usage
   limit is being waited out, the timer leaves the session alone.
5. **Merge.** In a separate merge worktree, the runner merges `main` and `task/<ID>`:
   - conflicts in record-per-line files (`[run] joinable`, by default TODO.md and DONE.md) are joined,
     keeping both sides' lines;
   - any other conflict goes to a one-shot fix session (`claude -p`);
   - the gate runs again if the merged code differs from what `done` tested.
   Only then is the main checkout moved to the tested merge. That takes seconds, it never stashes, and it
   waits if someone has uncommitted edits to the files involved.
6. **After the merge.** `plan reopen` unblocks tasks whose `(after X)` just landed and commits that.
   Then `main` is pushed (`[git] push_merge`), and the remote `task/<ID>` is deleted once the remote `main`
   contains it.
7. **Repeat** until nothing can start. Then the run [goes idle](#it-stays-up) and waits for new tasks.

### Terminals, and Windows

Each slot's session runs in a terminal you can watch and type into. Which one is `[run] mux` (or
`--mux`): `tmux` panes in the window "agents" (the default on Linux and macOS; start the run inside tmux),
`wt` (a Windows Terminal tab per slot, in a window named "agents", the default on Windows), or `console`
(a console window per slot, Windows' fallback when `wt.exe` isn't installed). `none` (`--no-tmux`) is
the sequential run below.

On Windows the runner can't get the session's pid back from `wt.exe` (it only asks the running terminal
to open a tab), so every slot runs through a small shim, `run --slot-shim`. It starts the agent and keeps
its pid in `.runner/slotN.live` while it runs. The loop, a restarted run's adopt and the Stop hook read
that file. The rest of the Windows differences are in `agent_runner/plat.py`: the run lock is
`msvcrt.locking`, process checks go through kernel32 (stdlib `ctypes`, no psutil), an ended session is
`taskkill /T /F`, and `[run] links` become a junction (directory) or hard link (file) when symlinks
need Developer Mode. Two things work differently there. Nothing captures a console's output, so
`.runner/slotN.log` has only the header lines and a usage limit is read from the transcript alone. A
prompt over 24,000 characters (a Windows command line holds 32,767) is handed over as a file the session
is told to read. `[run] test`, `on_exit`, `before_start` and the other commands run in the platform's
shell, which on Windows is `cmd.exe`.

`./run run 1` (or no tmux, or `--no-tmux`) is the sequential run. It's one session at a time, in your
checkout, on the branch you have out. There's no worktree and no merge: `done` already ran the gate, and
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
- `→ files…` lists the files the task will touch, separated by `·`, spaces or commas. Mode d uses this
  list to keep two running tasks off the same file, and the brief pastes those files in. Files that don't
  exist yet still count.
- `| t: tests` names the tests that prove it. `| j: dir` names its journal folder.
- `(after X, Y)` means don't start until X and Y are done. **Every id** in the parentheses counts.
- `BLOCKED: (after X, Y) why` is what `plan block`/`done --blocked` write. The `(after …)` list is what
  lets the run reopen the task by itself.
- `plan/<ID>.md`, if it exists, is the task's long form. The brief uses it instead of the one-line text.

`./run plan help` lists every subcommand: `next`, `<ID>`, `brief`, `tick`, `block`, `unblock`, `reopen`,
`add`, `move`, `note`, `newid` and `archive`.

## Picking

`pick` walks TODO.md in order and starts the first task that passes all of these checks:

| skipped | why |
|---|---|
| `[~]` blocked, and split parents (a task with open subtasks) | the subtasks are the work |
| an open `(after X, Y)`, for **any** id listed | every listed dependency must be done |
| a line that names a running task's id | prose such as "uses P36's menu" is treated as a dependency |
| a sibling of a running task (same family) | P13 and P13a edit the same thing |
| a task in a section whose heading starts with *Next* or says *in this order*, while another task from that section runs | an ordered section runs one task at a time |
| `### Stretch` | never unattended |
| tried this run | one attempt per run: if it failed, a human looks next |
| `task/<ID>` has commits not yet merged | it's finished and waiting for the merge |
| mode d: names a file a running task names (minus `[run] shared_files`) | keeps merges clean |

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

**Merges happen in a merge worktree.** The merge is built and tested in `<repo>-slots/merge`; the main
checkout moves only to a tested commit, and nothing in it is stashed.

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

**Idle stop.** The Stop hook starts a detached timer; a session quiet for `[run] idle` seconds is ended.
The timer does not fire on a session a human has typed into, or one waiting out a usage limit.

**Stall watchdog.** A session quiet at a prompt with no tool running for `[run] stall` seconds (20 min),
or quiet for over 65 minutes with a tool running, is logged with the terminal to look at, and the bell
rings.

**A line that names a running task waits.** A task whose line mentions a running task's id is not
started alongside it.

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

### Fix sessions

A conflict the line join cannot resolve goes to one `claude -p` session, run in the merge worktree with
the conflict in place. Its prompt (`FIXER` in `runner.py`) includes the tail of the ledger. It either
commits the resolution or runs `git merge --abort` and states why; its output goes to
`.runner/fixer.log`. The merge lock is held while it runs, and it is capped at `[run] fix_timeout`
(30 min). Set `fix_merges = false` to park every such conflict as `wip/<ID>` instead.

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
- **Journal and notes.** Set `[plan] journal` and each session writes `journal/<date>-<id>-<slug>/`: what
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

## Commands

```
./run plan [...]                       the task list as a tool (./run plan help)
./run done ID "MSG" [--blocked WHY [--after X,Y]] [--no-test] [--skip-check]
./run run [N|once] [--mode d|p] [--dry-run] [--no-tmux] [--mux tmux|wt|console|none] [--model M] [--idle S] [--stall S] [--pause S] [--force] [--shutdown]
./run stop                             finish what's running, start nothing new, exit (or s + Enter in the runner's pane)
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

```toml
[plan]
dir = "plan"              # TODO.md, DONE.md, <ID>.md
journal = ""              # e.g. "journal": per-task folders, the newest pasted into the brief
brief_extra = ""          # a command whose output ends the brief; {id} is the task id
brief = ""                # a command whose output *is* the brief (the project's own brief tool); {id}

[run]
test = ""                 # the gate, run by `done` and on every merge, e.g. "make test"
slots = 3
mux = ""                  # tmux, wt, console or none; "" = tmux (Windows: wt, else console)
mode = "d"                # d: different files; p: plan order
agent = "claude"
model = "opus"
lean = true               # sessions get Bash/Read/Edit/Write only, no MCP servers or user settings
idle = 90                 # s quiet after finishing before a session is ended
stall = 1200              # s quiet at a prompt that counts as stalled
pause = 60                # s between one session ending and the next starting in that slot
weekly_max = 90           # % of 7-day usage past which nothing new starts
notes = ".runner"         # logs + ledger (git-ignore it)
links = []                # git-ignored paths symlinked into every worktree (data, big files)
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
batch = true              # finished branches waiting for the merge go in together under one gate run
before_start = ""         # a command that must pass before any session starts (a display, a device)
not_attempt = ""          # regex on a branch's last commit subject ({id}): a phase, not the run's one try
shared_files = []         # files nearly every task names; mode d ignores them
joinable = ["plan/TODO.md", "plan/DONE.md"]   # globs of record-per-line files a conflict may be joined in
fix_merges = true
fix_model = "opus"
fix_timeout = 1800

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
python3 tests/test_runner.py    # picking, done, merge/join/land/push, fix sessions, wip parking,
                                # retry after unblock, prompt, Stop hook, usage limits, adopt,
                                # batches, flaky/inherited failures, the platform layer and the
                                # Windows slot shim (temp repos, fake agent)
```

## License

MIT
