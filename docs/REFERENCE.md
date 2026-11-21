# agent-runner reference

Everything the [README](../README.md) leaves out: how a task runs end to end, picking, merging, fix sessions,
disk and memory, stopping, the prompt, every command and every `runner.toml` key. Setup is in
[SETUP.md](SETUP.md).

## How it works

```
plan/TODO.md ──pick──▶ slot N: git worktree ~/runs/<repo>/sN on task/<ID>
                         tmux pane sN: claude "<prompt + the task's brief>"
                         …the session works, then `agent-runner done <ID> "msg"` (test gate → tick → commit → push task/<ID>)
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
   timer. The prompt includes the task's brief (`agent-runner plan brief <ID>`): its line, its `plan/tasks/<ID>.md`
   long form, the files it names (or "missing: this task creates it"), and the newest journal entry.
3. **Finish.** The session ends with `agent-runner done <ID> "msg"`. That runs the test gate, ticks the task
   (`[x]`, and the line moves to DONE.md), commits, and pushes `task/<ID>`. If the gate fails, nothing is
   ticked or committed. A session that's stuck runs `done --blocked "why"` instead.
4. **End the session.** The session goes quiet at its prompt. The Stop hook's detached timer sees no new
   transcript entries for 5 s once `done` has succeeded, or `[run] idle` seconds (30) when it stopped without it, and ends it. If a human typed in the pane, or a usage
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
6. **After the merge.** `plan reopen` unblocks tasks whose `BLOCKED: (after X)` just landed and commits that.
   Then `main` is pushed (`[git] push_merge`), and the remote `task/<ID>` is deleted once the remote `main`
   contains it.
7. **Repeat** until nothing can start. Then the run [goes idle](#it-stays-up) and waits for new tasks.

### Terminals, and Windows

Each slot's session runs in one of two places, `[run] mux` (or `--mux`):

- **`hidden`**: a terminal with no window, on every OS. You watch and steer it through Remote Control
  (claude.ai/code and the Claude apps, with `[run] remote_slots`), `agent-runner status`, the slot's log
  `.runner/slotN.log` and control sessions; `plan tell <ID> "…"` types into it. On Linux and macOS it is a
  pseudo-terminal from Python's standard library (`pty`), 200 columns by 50 rows, and its output goes to the slot
  log. On Windows it is a console of its own whose window starts hidden (`attach s2` shows it); nothing
  captures its output there, so the slot log has only the header lines, and `plan tell` cannot type into it.
- **`tmux`** (Linux and macOS): a pane each in the window "agents-<repo>", to attach to and type into (`s` and
  the pane keys). Runners for different repos can share one tmux session, each finding only its own panes.

The default (`mux = ""`) is tmux when it is installed and the run is inside a tmux session (the background run
always is), else hidden: without tmux the run is hidden, not an error. Asking for tmux outside a tmux session
says to start the run in one; asking for it where tmux isn't installed runs hidden. Windows is hidden only.
One slot, and `once`, run like any other count: a worktree, a session, a tested merge. (The old sequential run
of `--no-tmux` / `mux = "none"`, which committed in your checkout with no worktree and no merge gate, is gone,
and so are Windows Terminal tabs and visible console windows: `wt`, `console` and `none` now read as hidden.)

A hidden slot runs through a small shim, `run --slot-shim`, started detached so the session outlives a
restarted runner. It starts the agent and keeps its pid in `.runner/slotN.live` while it runs (and, on Linux
and macOS, reads the FIFO `.runner/slotN.in` for what `plan tell` types). The loop, a restarted run's adopt
and the Stop hook read that file; how the agent ended goes to `.runner/slotN.exit`. The rest of the Windows
differences are in `agent_runner/plat.py`: the run lock is
`msvcrt.locking`, process checks go through kernel32 (stdlib `ctypes`, no psutil), an ended session's
windowed processes (an emulator, say) get WM_CLOSE and up to 10 s to exit before `taskkill /T /F`, and `[run] links` become a junction (directory) or hard link (file) when symlinks
need Developer Mode. A
prompt over 24,000 characters (a Windows command line holds 32,767) is handed over as a file the session
is told to read. `[run] test`, `on_exit`, `before_start` and the other commands run in the platform's
shell, which on Windows is `cmd.exe`.

### In the background

Bare `agent-runner` starts the run where no terminal shows it and returns within seconds. On Linux and macOS
that is a detached tmux session `ar-<repo>` (`tmux new-session -d`) whose window `runner-<repo>` runs
`agent-runner run`. The slots' window `agents-<repo>` opens in the same session. The new session gets this
shell's `PATH`, the `AGENT_RUNNER*`, `CLAUDE_*` and `ANTHROPIC_*` variables and `[run] pass_env`. The launch
waits for the run's start line in `run.log`, then prints the slot count and the commands: `status`, `attach`,
`stop`, and claude.ai/code with `[run] remote`. If the run fails within that time, its window is kept long
enough to print the pane's last lines, and then it is closed. If a run is already up it says so and starts
nothing. If the session is still there from an earlier run
(its slots' window still open), the run starts in a new window of that session and adopts those panes.

On Windows, and on Linux and macOS without tmux, the runner is a detached process (`run --hidden`, its output in
`.runner/background.out`) and its slots run hidden (see above). On Windows each slot gets a console that
starts hidden (`STARTUPINFO.wShowWindow = SW_HIDE`); it's still a real console, so the agent has a TTY.

`agent-runner attach` goes to the runner's pane: it is tagged `@runner-run` = the main checkout, so this works
for a run started with `agent-runner run` in a tmux session too. `attach s2` goes to slot 2's pane, and
`attach master` to a fix session. Inside tmux it switches the client; outside, it attaches this terminal.
Detach with Ctrl-b d. On Windows, `attach s2` shows and raises slot 2's console window. Minimize it to hide it
again: closing it ends that session, which resumes in the next run. The runner has no window there, so
`agent-runner status` and `.runner/run.log` show it. On Linux and macOS a hidden slot has no pane to attach:
`attach s2` says where its log is.

With `[run] remote` (or `remote_slots`), Claude Code asks once, at a terminal, "Enable Remote Control? (y/n)".
In a hidden pane that question would hold every session. So before going to the background the launch checks `remoteDialogSeen` in
`~/.claude.json` (or `$CLAUDE_CONFIG_DIR/.claude.json`). If it is not set, the launch asks the question in this
terminal and records the yes there. A no, or no terminal to ask in, starts nothing. Under `remote = "auto"`
(and no `remote_slots`) it starts the run anyway, with Remote Control off and the reason in `run.log`.

### Control sessions

A control session is an interactive Claude Code session in the main checkout where a person runs the run, at
the terminal or from claude.ai/code and the Claude apps: "status?", "pause", "one slot more", "stop", "add a
task to fix X" (it files it with `plan add`), "do X now" (it uses `take`, never edits the main checkout).

- **c1 comes with the run** (`[run] control = true`, the default; false: none). A run in a terminal splits a
  pane under its own for it; the background run opens it in window `control-<repo>` of `ar-<repo>`; on Windows
  it gets a console of its own, hidden in the background mode. `agent-runner attach c1` goes there. c1 keeps
  its session id in `.runner/control.sid` and resumes it in every run while the transcript is there. It has no
  Stop hook, is never ended on idle, and outlives a stopped run: a run that finds c1 still up opens no other.
- **More of them**: `agent-runner control` starts one in this terminal (c1 when it is not running, else the
  next free number, `.runner/control<N>.pid`). In the background session every new pane or window a person
  opens is one: the run sets that session's tmux `default-command` to `cd <main checkout> && agent-runner
  control` (a shell stays if it cannot start). A run in your own tmux session leaves its default-command alone.
- **A new one from inside one** (the phone apps have no new-session button): `agent-runner control --new [N]`
  opens the next free control session without taking focus, in window `controlN-<repo>` of the tmux session
  it runs in (else `ar-<repo>`, while the run is up; Windows: a hidden console), tagged `cN` for `attach cN`.
  With `[run] remote` it watches the new pane for up to 90 s and prints its `claude.ai/code/session_…` link,
  so the control session that ran it answers with a link to tap. Tell a control session "new", "new
  session", "/new" or type `/control`: its brief maps those to `control --new`. `/control` is a skill only
  control sessions get, in `.runner/control-skills/.claude/skills/control/SKILL.md`, added with `--add-dir`
  and the settings' `permissions.additionalDirectories`, never in your repo's files. It is not named `/new`
  because Claude Code's `/new` is an alias of `/clear`, which would wipe the session instead. Whether the
  phone app passes a typed `/control` through to the session is still to be checked by a person; "new"
  works either way.
- **Their settings**: every control session, and the control server, gets `.runner/control-settings.json`
  with `--settings`: a SessionStart hook that runs `agent-runner control --brief`, which prints the control
  brief (so a resumed or compacted session gets it again). They run on `[run] model` with every tool
  (`[run] lean` is for slots) and in bypassPermissions mode, as the slots do: driven from a phone or the web,
  a permission prompt would stall them.
- **The opening**: the first message has the session run `agent-runner status` and `agent-runner since` and
  say, in plain bullets, what the run is doing now (each running task by its short title, no ids) and what
  landed, got stuck or needs you since you last looked, then one line of hints: `status · since · follow ·
  new (or /control) · pause · stop · more slots · or just describe a bug or idea to queue it`. Later answers are bullets too, ids
  only when you ask or the session acts on one.
- **Needs you, unasked**: every control session starts the Monitor tool on `agent-runner since --follow
  --needs-you` on its first turn (control 1's opening message names it; a blank session starts it before
  answering your first message). It prints only what needs you: the run held (`STOPPED`: uncommitted edits or
  a mid-merge in the main checkout, staged changes, a usage cap), a task left for a human, one that looks
  stalled, and a task waiting on your answer (`CONFIRM:`/`DECIDE:`/`BLOCKED:`, a concept page waiting for your
  OK). On each line the session posts one plain bullet, what is held and the one thing to do, and sends it
  with PushNotification so a phone hears it: the runner's pane, tmux message and `notify-send` are seen by
  nobody when the run is driven from the web or a phone. The watch starts with `timeout_ms 1800000` (the
  Monitor tool's cap); when it times out with nothing printed the session starts it again silently, with no
  "still watching" line, so a quiet run posts nothing. The runner feed's own Monitor does the same.
- **Following**: say "follow" (or "live", "/follow") and the session runs `agent-runner since --follow` under
  the Monitor tool and posts each line it prints as a bullet; "stop following" ends it (see [status and
  since](#status-and-since)). It is the full feed, so the needs-you watch stops while it runs and starts again
  after.
- **With `[run] remote`** each control session starts with `--remote-control "<repo> · control N"`, and the
  run keeps `claude remote-control --spawn same-dir --name "<repo> · control" --settings <file>` running in
  the main checkout (output in `.runner/control-server.log`, errors in `.runner/control-server.err`; one that
  quits within a minute puts its last error line in `run.log`), restarted when it exits (Remote Control quits
  after about 10 minutes offline; 30 s, doubling to 10 minutes while it keeps failing), so new control
  sessions can be started from the app. `--settings` goes in only when `claude remote-control --help` lists
  it (asked once a run): an older Claude Code starts without it, so its app sessions get no control brief,
  and `run.log` says to update. The run's end ends it. The slots stay local unless `[run]
  remote_slots = true`, which starts each as "<task title> · <repo> s2 · B646". That is off by default and not
  recommended: every slot start pushes to the phone (see Quiet launch below). Watch hidden slots through
  status and control sessions instead.
- **`remote = "auto"`, the default**, is on when Remote Control can work: Claude Code on a claude.ai login.
  It is off, with one `run.log` line saying why (`remote control off: …`), when the backend is pi,
  `ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN` is set, `CLAUDE_CODE_USE_BEDROCK`, `_VERTEX` or
  `_FOUNDRY` is set, `ANTHROPIC_BASE_URL` names a host other than api.anthropic.com, or Claude Code's
  "Enable Remote Control?" has not been answered yes. `true` forces it on (never for pi), `false`
  keeps it off; any other value is refused.
- **Quiet launch.** Every Remote Control session the run starts gets `CLAUDE_CLIENT_PRESENCE_FILE` (while that
  file exists Claude Code sends no mobile push; 2.1.181+). A control session's `.runner/quiet-c<N>` is made
  as it starts and removed once its claude.ai/code link shows in its pane (`control N --unquiet`, a small
  detached helper, watches; without tmux, after 30 s); the control server's `.runner/quiet-server` once a link
  shows in its log. Slots with `remote_slots` keep `.runner/quiet-slots` for good and get
  `agentPushNotifEnabled: false` in their `--settings` (no PushNotification tool). Known limit: Remote
  Control's "session ready" push goes out as a session registers, before the presence file can count, so
  each Remote Control slot start, and most likely each control session start, still pushes. No setting or
  environment variable stops it, short of turning off the Claude app's notifications on the phone.
  `[run] silent` sets this: `"launch"` (the default) as above; `true` keeps every file for good, so no
  session the run starts ever pushes; `false` sets none, and Claude Code pushes as it would anyway.

### status and since

`agent-runner status` and `agent-runner since` name each task by a short title, the first sentence of its line
cut to about 60 characters, without its fields, quotes, dates or file lists, with the id in brackets at the
end: `s1  Control session experience [F5]  12 min`.

`agent-runner since [WHEN]` lists what happened, oldest first, one line each: started, landed, part landed
with the rest stuck (`done --blocked`), stuck and not merged (parked on `wip/`), needs you (left for a human,
or the run held by a stoppage only you can clear), looks stuck (stalled), run idle, run stopped. With no
WHEN it starts where the last `since` left off (`.runner/since.last`; a day back the first time) and moves
that mark forward, so asking twice in a row shows nothing new the second time. WHEN is `2h`, `30m`, `1d`,
`today`, `yesterday` or a date/time (`2026-11-19T14:00`); it moves the mark too, never back.

`since --follow` stays running and prints one line per new event as run.log gets it (a landed task with the
first sentence of its `done` message), from now on, moving the mark as it prints: the control session's
"follow", and fine in any terminal. `since --follow --needs-you` prints only what needs you (the run held,
with what holds it; left for a human; looks stuck; `needs you:` a task or concept that landed or blocked
asking for your answer, in plain words with the link), skips landed, started and idle, and leaves
the mark where it is: it is the watch every control session keeps.

Both print **Needs you** first when a concept's build or a task waits for you (below), however old: per item
one line in everyday words, what is asked and what to reply, its age first and its [id] last, then its link
on a line of its own, oldest first:

    Needs you:
       2h  Pick an option for settings page layout - reply A/B/C [K7]
        https://claude.ai/code/artifact/…
      35m  Check the push reached your phone - reply yes/no [F1]

The CONCEPT/CONFIRM/DECIDE/BLOCKED labels stay in TODO.md and `plan waiting`; the person does not see them.
The age comes from the `(asked YYYY-MM-DD HH:MM)` stamp `plan block` adds to a block on a person (older
blocks have none and sort first). `[needs]` in runner.toml changes it:

    [needs]
    heading = "Needs you"   # the heading in status, since and the control sessions' opening
    ages = true             # show each item's age
    order = "oldest"        # "newest" first, or "plan": TODO.md's order

### Tasks waiting on a person

A block whose why starts with a caps label waits on a person, not a task: `CONFIRM:` (check something by
hand and say what you saw), `DECIDE:` (answer a question or a choice), `BLOCKED:` (access, a login, or a fix
only a person can make). An agent files one with `done R1 "msg" --blocked "CONFIRM: watch a phone for a push
when a task lands"`; such a block never takes an `(after …)`. It lists under Needs you beside the
concept pages, and takes one of three answers (the control session or the runner feed maps what the person
says to the item's id, a reply that names no item, "yes", "B", "later", included, and asks which one when it
cannot tell):

- `plan confirm R1 "the push came"`: a CONFIRM is ticked with that noted; a DECIDE or BLOCKED reopens with
  the answer noted; a concept is approved.
- `plan change R1 "do X instead"`: noted and reopened (a concept: `revise`).
- `plan shelve R1`: stays blocked (`BLOCKED: shelved: …`) but leaves the list; `plan waiting --all` still
  shows it, and `plan unshelve R1` brings it back. Concepts shelve the same way.

### Concept tasks

A task of kind `K` (concept; one of the default kinds) builds nothing. Its session researches the repo and
publishes one Artifact page laying out the options, usually two or three, each with what it looks like or
does, the files it touches and its trade-off, plus a recommendation. It finishes with
`done K7 "msg" --artifact <url>`; `done` refuses a K task without `--artifact` (unless `--blocked`). Then
`done` notes the link on K7 (and in its journal, when `[plan] journal` is set), ticks K7, and files the build
task right after it, `- [~] **F12** Build the option a person approves on concept K7's page: … BLOCKED:
waiting for your OK on <url>`. That block names no task, so no run starts it and `plan reopen` never frees it.

- **Approve**: tell a control session "go with option B" (or "approve" for the recommendation). It runs
  `plan approve K7 "option B: …"` (K7 or F12 both work): F12 opens with `approved (<url>): option B: …` on its
  line, and a run picks it up.
- **Changes or a no**: `plan revise K7 "what to change"` reopens K7 (back from DONE.md) with the request
  noted and drops F12; the next round's `done` files a new build task.
- `plan waiting` lists what waits for an OK.
- The build gets `F` where the kinds have it, else their first non-K letter. A repo whose `[plan] kinds`
  lack `K` has no concepts: a K-lettered id there is an ordinary task.

## The task list

`plan/TODO.md` is ordinary markdown. The runner only looks at task lines under `###` headings:

```markdown
### Next (in this order)

- [ ] **P12** the parser reads nested lists | files: src/parse.py, tests/test_parse.py | test: test_parse
- [ ] **P13** maps too | files: src/parse.py | after: P12
  - [ ] **P13a** the empty map
- [~] **P14** a fuzz harness | files: tools/fuzz.py BLOCKED: (after P12, P13) needs both grammars landed

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
  a letter the table lacks. With no table, the generic `B F T D R C K V` (bug, feature, tests and tooling,
  docs, research, cleanup, concept, release) are suggested but not enforced. `K` is the concept flow (above).
- `V` is a **release** (F38): the run treats every `V…` id so, so a repo with its own `[plan] kinds` lists `V`
  to file releases (and keeps the letter for nothing else). `plan add V` files it at the end of
  Next with `after: all`, so it waits for everything ahead of it (no `--after` needed), and with no text it
  gets the default brief: bump the version per the project's versioning rules (docs/SETUP.md#versions here),
  move CHANGELOG Unreleased under it, commit to main, check the release workflow and `gh release view`. It
  **runs alone**: the run starts it only when no other task is running or waiting to merge, and starts
  nothing beside it, so it releases exactly what landed. `plan add V --now` (or `--pri critical`) is an
  interim release: filed at the top, critical, with no `after: all`, still run alone. A release is never
  refused as a duplicate of another release, and needs no `--files`.
- `plan add` also refuses (exit 3, nothing written) text that looks like an open task's work, naming it:
  `plan note` that task instead, or `--force` for different work. A task's own split (`plan add P13 …`)
  is never refused for looking like P13. `plan drop ID WHY` closes a task nobody will do (a duplicate,
  overtaken): archived with `dropped: WHY`, so its id stays used and what waits on it reopens.
- Reaching a running agent: `plan tell ID TEXT` types `A note on your task, from the person running this
  run: TEXT` into the tmux pane of the slot running ID (Claude Code queues it for its next turn while busy)
  and edits no plan; it fails when no slot of a run here runs ID. `plan change ID TEXT` on a running task
  notes the change in the plan as usual, then types `Your task changed: TEXT` into the pane, and the agent
  works on. Both print `told s1 (ID)` once the text is in. They go through the run like a halt: a request in
  `<notes>/tell/<ID>.json`, answered in `<notes>/tell/<ID>.done`. With no live pane (Windows terminals, a
  session that ended, a cut-off one waiting to resume, a finished branch merging), `change` says so and
  falls back to stopping the slot and starting the task again from the new text, which
  `plan change ID --restart TEXT` asks for outright.
- A note one side adds to a task the other side ticks is kept: the tick wins in TODO.md, and the runner
  appends the note to the task's line in DONE.md after the merge.
- After the prose come keyed fields, each ` | key: a, b` (comma-separated), in any order; a ` — note` or
  `BLOCKED: …` may follow them. **Prose is never parsed** for files or ids: only the fields count.
  - `files:` the files the task will touch. The run keeps two running tasks off the same file, and the brief
    pastes them in. Files that don't exist yet count, and so do patterns: `dir/**` and `dir/*.rs`. A path
    meets its own tail (`src/menu.rs` meets `app/src/menu.rs`).
  - `after:` ids that must be done first. **Every id** listed counts. `after: all above` (what `plan add
    --last` writes, filing the task at the end of Next) is no list: the run resolves it on every pick to each
    task above it in its own section that is not done, ones added later included, so a release waits for the
    whole section without a list going stale. Tasks blocked on a person don't hold it until they reopen;
    Follow-ups never do. `plan reopen`, `plan waiting` and `status` say what it still waits on.
    `after: all` (`plan add/edit/block --after all`, any kind) waits for **everything before it**: each open
    or blocked task above it in TODO.md, in any section, resolved afresh on every pick, so a task queued above
    it later holds it too. Parked (`--pri later`) and Stretch tasks and shelved ones don't count, or it would
    never run. On a block it reads `BLOCKED: (after all) why`, and `plan reopen` frees it once nothing is left
    before it. `status`, `plan ID`, `plan reopen` and `plan waiting` show it as `T5 waits for everything before
    it (12 open)`, not an id list.
  - `test:` the tests that prove it. `journal:` its journal folder.
  - `plan add P "text" --files a,b --after X --test name` writes them.
- `BLOCKED: (after X, Y) why` is what `plan block`/`done --blocked` write. The `(after …)` list is what
  lets the run reopen the task by itself.
- `plan/tasks/<ID>.md`, if it exists, is the task's long form. The brief uses it instead of the one-line text.
  Long forms sit in `tasks/` so the plan's top level is TODO.md, DONE.md and the overviews a person reads
  (REFERENCE.md, HUMAN.md, batch briefs). A long form left at `plan/<ID>.md` still counts; move it with
  `git mv plan/<ID>.md plan/tasks/`.

`agent-runner plan help` lists every subcommand: `next`, `<ID>`, `brief`, `tick`, `block`, `unblock`, `reopen`,
`add`, `move`, `note`, `newid`, `archive`, and for concepts `waiting`, `approve` and `revise`.

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
- **Claims: two people can run at once.** The moment a run picks a task, it
  pushes `claims/<ID>` (host and checkout) before anything starts. Other runs skip a claimed task and treat it as
  running there: a task sharing its files, its ordered section or its family waits for it. The claim
  holds the line's files and, refreshed as the session works, every file it has touched, so a task whose
  line lists too few is still kept clear (a whole-directory glob on its line, `dir/**`, holds only another such
  glob, as under Picking). Two that claim one task at once conflict on push, and the later
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

**Claims with the plan in the code repo.** Runs claim tasks the same way without `[plan] repo`, whenever the code
has a remote (`[git] push`): each claim is a ref, `refs/agent-runner/claims/<ID>`, on that remote. The first push
of a claim wins and any later one is turned down, so two runs never take one task, whether they are on two
machines, or on one machine and one account in two clones (a claim's owner is host and checkout). Claims hold
files, go stale, show in `plan` and `plan claims`, and `plan unclaim` drops one, all as above. The refs are
outside branches and tags, so clones, CI and the GitHub UI never see them. A `plan add` in a main checkout
commits there but does not push: another machine sees the task once that commit is pushed (the next merge
the run there pushes does it).

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
is first run again, its failed jobs only (`gh run rerun --failed`), since a runner GitHub
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
| a list that must go in order | a section heading saying *in this order* or *one at a time* | one task from it runs at a time |

A plain new number (`plan add A "…"`) is an independent task and may run beside anything. `agent-runner help order`
prints this summary; `agent-runner run --dry-run N` shows what N free slots would start now, and why the rest wait.

## Picking

`pick` walks TODO.md in order and starts the first task that passes all of these checks. The order is the
file's, except that a task a waiting one depends on (`after: X` on an open line, `BLOCKED: (after X)` on a
blocked one) moves up to where that one stands, down the whole chain: a Next task blocked on a Follow-up
does not wait behind every task between them. The plan read is the shared branch's, or its remote's when a
push from outside the run has put that ahead (fetched at most once a minute).

| skipped | why |
|---|---|
| `[~]` blocked, and split parents (a task with open subtasks) | the subtasks are the work |
| an open id in `after:`, for **any** id listed | every listed dependency must be done |
| a sibling of a running task (same family) | P13 and P13a edit the same thing |
| a task in a section whose heading says *in this order* or *one at a time*, while another task from that section runs | an ordered section runs one task at a time |
| `### Stretch`, `### Parked` | never unattended |
| tried this run | one attempt per run: if it failed, a human looks next |
| `task/<ID>` has commits not yet merged | it's finished and waiting for the merge |
| a `files:` entry meets one of a running or finished-unmerged task's (its line's, and the files its branch has touched), minus `[run] shared_files`; a whole-directory entry (`tests/**`) is a guess, not a lock: it meets only another whole-directory entry, so a named file under it meets only what that task has touched | keeps merges clean |

`plan add` warns of a line with no `files:` and no `test:` (`[plan] need_files` makes that an error).

`agent-runner run --dry-run N` prints what N free slots would start, and what's waiting and why.

## Behaviour

**Blocks reopen themselves.** `done --blocked WHY` records the open task ids that WHY names (or
`--after X,Y`) as `BLOCKED: (after X, Y)`. After every merge, `plan reopen` sets the task back to `[ ]`
once all of those ids are done, and the run picks it up again.

**Unmergeable branches are parked.** A conflict the line join cannot resolve goes to a fix session
(below). A branch the fix session gives up on is renamed `wip/<ID>` and pushed; the task is open again,
and its next prompt points at the earlier attempt. Parked twice (`wip/<ID>`, `wip/<ID>-2`, counted across
runs and restarts; a slot's saved edits do not count), the next pick blocks it `DECIDE:` on a person, with
the ledger's reasons, instead of starting it a third time; `plan unblock <ID>` lets it run again (the attempts it was blocked over, kept in
`.runner/parked-seen.json`, no longer count).

**Merges happen in a merge worktree.** The merge is built and tested in `~/runs/<repo>/merge`; the main
checkout moves only to a tested commit, and nothing in it is stashed. Nor is its branch ever switched: while
it has another branch than `main` out, a tested merge stays `task/<ID>` and lands once `main` is out again.

**Commit your own edits in the main checkout.** A merge lands only when no uncommitted edit there touches
a file it changes, and nearly every merge changes `TODO.md`. `run plan add/note/move/tick/block/unblock/
reopen`, run by hand in the main checkout, therefore commits the plan immediately (not mid-merge, and not
in a worktree, where `done` commits). For code work alongside a run, `agent-runner take "TEXT" --kind K`
(or `take ID`) gives it a worktree and `task/` branch the runner tests and merges; `take --here` moves edits
already made in the main checkout there. Never use a slot's worktree, which the runner reuses.

**The shared branch is pushed only after a merge passes the gate.** `done` pushes `task/<ID>` and
refuses to push `main`.

**Usage caps.** Past `[run] session_max`% of the 5-hour session usage, or `[run] weekly_max`% of
the 7-day usage, no new task starts unless `--force` is given (or `f` typed in the runner's pane); hitting one raises the STOPPED alarm with that hint.

**A cut-off session resumes.** A session whose turn ended on an API error (the network dropped, the
API was down, the account hit its usage limit) is not finished, though the idle stop ends it. Its worktree is left as it is, and once the
API answers again it is resumed in the same slot (`claude --resume`, with its whole conversation) and told
it was cut off. While the API cannot be reached, no session resumes or starts. At startup, a slot still on
`task/<ID>` whose session stopped mid-turn while no run was up (a reboot, the runner killed) is resumed
the same way. A request the API refused is not a cut-off (it would fail again), and one session is resumed at
most 3 times. `agent-runner resume <ID>` resumes a task's last session by hand, for one the run already ended:
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
`agent-runner stop`. When there's nothing it may start and nothing running or merging, it logs this once:

    run idle: no task it may start; waiting for TODO.md to change (Ctrl-C or ./run stop to end it)

It keeps re-reading TODO.md on the shared branch every few seconds, so tasks you commit later start
without a restart. When it starts work again it logs `run busy: new work (<ID>)`.

A tried task normally stays tried for the rest of the run. But if its line closes (`[~]`) and later
opens again (a human ran `plan unblock`), that's a new attempt, so it goes back in the pool and the log
says `<ID>: open again since it was tried; back in the pool`.

A script waiting on a run should watch `.runner/run.log` for a `run idle` line written after it started
waiting, not for the process to exit. `run busy` means work started again.

### Stopping a run

Ctrl-C ends the run at once and cuts every session off mid-task. To stop gently, **type `s` + Enter in
the runner's pane** (the one you started `agent-runner run` in), or run `agent-runner stop` from anywhere. Either way
nothing new starts, the running tasks finish and merge, and then the run logs `run stopped (s)` (or
`run stopped (./run stop)`) and exits with 0. Typing `s` again before then takes the stop back, and tasks
start again.

`s!` + Enter (or `agent-runner stop --force`) stops now: every agent session is ended and queued to resume
in its slot when a run next starts (its worktree stays as it was, nothing of it is merged); the merges
already under way finish, then the run exits.

The other keys, listed by `?` + Enter (and printed when the run starts), ruled off from the log:

| key | what it does |
|---|---|
| `p` | pause: no new tasks, and the run stays up; `p` again goes on |
| `u` | upgrade agent-runner now (`uv tool upgrade`, `pipx upgrade`, or a pull in a clone); the run restarts on the new version as with any upgrade. `[run] auto_upgrade` (on by default) presses it for you: when the update check (at the start, then every 6 h) sees a newer release, the run upgrades once no merge is under way, logs it, and restarts on the new version keeping what the keys set; never across a major version, nor on Windows. It works the same in a run started in a terminal (`agent-runner run`) and in the background (bare `agent-runner`) |
| `f` | force: start tasks past the session and weekly usage caps, as `--force`; `f` again: the caps hold |
| `+` / `-` | one slot more / fewer; a slot taken away finishes its running task first |
| `z` | suspend the computer once the run stops, or when it goes idle as `--suspend` would; `z` again: off |
| `x` | the same, shutting down (`--shutdown`); `x` again: off |

After a stop, power goes off at once, with no idle grace. `agent-runner stop --suspend` (or `--shutdown`) does
the same from outside the pane, through `.runner/POWER`. A line the runner does not know is echoed back with
the key list. Each key is acted on as it is typed; ending sessions and adding a slot wake the loop at once.

**The same from any terminal, or a remote session.** Each key has a command, so nothing needs the pane:
`agent-runner pause` (`--off` goes on), `force` (`--off`), `slots 4` (or `+1`, `-1`), `stop --undo` (takes a
gentle stop back), and `key <k>` for any other (`key z`, `key u`). Unlike a typed key, `pause`, `force` and
`stop` say which way they go, so asking twice does not undo them. They append to `.runner/KEYS`, which the
loop reads on every pass, so the run acts within 10 s; with no run up they say so and exit 1.
`agent-runner status` is short enough for a phone: whether a run is up and what the keys have set, each
slot's task id, title and minutes running (from `.runner/STATE`, rewritten every pass), what is merging, the
last five merged, blocked or parked tasks from `run.log`, and the account's usage as the caps last read it.
`-n 30` adds the end of `run.log`.

Both write `.runner/STOP` (with who asked; `.runner/STOP.force` for a stop now), and the loop checks that
file on every pass, so `s` can take back a `agent-runner stop` and the reverse. A daemon thread reads the runner's terminal (it works on Windows
consoles too) and only starts when stdin is a terminal. A STOP
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

A conflict the line join cannot resolve goes to one fresh session, run with the conflict in place. By
default (`[run] fix_ahead_max`, 2) that happens before the merge lock is taken: the task's branch is merged
into the shared branch's head in a fix worktree of its own (`fix1`, `fix2`, … under `[run] home`, kept so their
builds stay warm; at most `fix_ahead_max` at once, the others waiting a turn, and each waiting on
`before_start` as a slot does), the session commits the resolution there, and the runner keeps it as
`refs/agent-runner/fixed/<ID>/<sha>`. Other tasks merge and gate meanwhile. The task then takes the lock with
that merge, which goes in clean unless the shared branch touched the same lines again in the meantime: then
it goes back out for another, smaller fix. Its third try fixes under the lock, in the merge worktree. Under tmux it is an interactive session in a window of its own, "master", so you can
watch it or take it over by typing; its Stop hook ends it once it has been idle 30 s (`[run] idle`) after its answer
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
the first failure. When the runner still has the session that did the task, the repair session starts as a
copy of it (Claude's `--resume <id> --fork-session`), so it knows the change it is repairing; otherwise it
starts fresh.

When a batch (`batch = true`) fails the gate, the runner first looks for the task that breaks it by
itself (with `failures` and `retest` set), by halving the batch as below. That one merges in a turn of
its own, where its repair goes as above; the rest are built and gated again together. If no branch fails alone, the batch is repaired as a
whole: one repair session sees every merge in the batch (`REPAIR_BATCH`) and fixes where they clash, and the
gate runs once more for all of them. Only if that fails too is the batch split, each branch merged on its
own. A rider whose conflict the line join cannot do waits for its own turn, where it is fixed ahead of the
lock; with `fix_ahead_max = 0` it gets its fix session inside the batch and shares the batch's gate run.

A test the base fails already (checked with `retest` on the base) never counts against a batch: when a
batch fails it and a new test, only the new one counts, and when it fails only tests the base fails too,
it lands.

When a batch fails a new test, the task that breaks it is found by halving: half the batch is merged on
the base and only the failing tests rerun, then the half that fails is halved again (a batch of 16 costs
about 5 retests). That task merges in a turn of its own; the rest are gated again together, and a second
culprit among them is found the same way. A batch takes at most `batch_max` tasks (16); the rest take the
next one.

Critical tasks (an open `(follow-up, critical)` tag, or a plan section whose heading says Critical) merge
alone, never ride in a batch or a merge built ahead, and take the merge lock before anyone else waiting:
they are the fixes every other gate is waiting on. The lock goes next to a merge built ahead whose gate is
under way, then to the rest in the order they finished.

When more than `max_unmerged` finished tasks (32) wait for the merge, each half batch past that keeps one
slot from starting a new task (with 6 slots and `batch_max` 16, 33 waiting run 5 at most, 73 run none).
Sessions under way go on; slots pick up again as merges land. The runner says when it holds slots back
and when it stops.

Tasks that finish while a batch is in its gate do not wait for it to end (`merge_ahead = true`). They are
merged on top of the merge under test in a second worktree (`merge2` under `[run] home`) and their gate starts
beside that one. When the first batch lands, the next one's turn finds the same merge built ahead and
waits for the gate already under way on that exact tree, so two batches cost about one gate's wait. If
the first batch fails or the branch moves another way, the merge built ahead is dropped and its gate
stopped. Its conflicts get only the line join: one that needs a fix session waits for its own turn. The
first gate in merge2 builds from cold, and merge2 has a build directory of its own.

A tested merge that cannot land because of uncommitted edits in the main checkout to files it changes (or
anything staged there, which git refuses to merge onto) waits 10 minutes, then gives the merge lock back
and stays `task/<ID>`; it is merged again once those files are committed. It is never parked for that.
With `[git] land_edited = "wip"` the edits go to a `wip/main-checkout-<time>` branch (and a stash) after 3
minutes instead; the log line names the files and `take --here`, and `plan claims` and `run --dry-run` list
those branches until someone deletes them.

A merge skips the gate only when `task/<ID>` is the very tree `done`'s gate passed on (recorded as
`refs/agent-runner/tested/<ID>`) and the merge differs from it only in `[run] untested` files. After
`done --no-test`, commits made after `done`, or a session that never ran it, the merge is tested.

Docs-only changes skip the gate, decided by the diff and not the task's letter (a D task that touches code
is tested; a B fix that only edits the README is not). When every file a merge changes on the shared branch
(all its tasks, the plan's archive commit, a remote's commits taken in) matches `[run] docs_files` (default
`*.md` and `docs/**`; `!glob` takes one back), the merge runs `[run] docs_check` instead, if one is set (a
link or anchor check), and the log says `docs only, gate skipped`; a failing docs check fails the merge.
`done` does the same with the files its worktree changes since the shared branch (commits, edits and new
files): it prints `docs only, gate skipped`, so a session that only edited docs or the plan needs no
`--no-test`. It records no tested ref then; the merge decides by its own diff.

## Keeping sessions lean

Whatever `[run] rules`, CLAUDE.md, AGENTS.md and their `@` imports hold is
re-read on every turn of every session, and agents keep adding to it (opentennis's grew to 28 KB, half of it a
code map each task appended a line to). Leave the rules there; put code maps, how-tos and background in
`[plan] lookup` files, one `## section` each, with a one-line pointer in the rules (`agent-runner plan hst-base`,
`agent-runner plan "Driving the game"`). A heading named exactly that wins over one that only contains it.
`agent-runner context` shows what every session loads, biggest sections first, against `[plan] context_kb` (12 KB);
`run` warns at start when it's over, and the prompt tells agents where new reference material goes.

## Making it fast

With several slots, the gate is what fills the machine and what holds the queue up: every `done` runs it,
and every merge runs it again. What made one 32-thread, 7-slot setup go from load 120 and two-hour merges
to load 15 and one-hour merges:

- **Run gates under a lock, not one per slot.** A wrapper that lets at most a few gates run at once (a
  `flock` on one of N lock files) and gives each `nproc / N` jobs beats seven gates fighting for every
  core. The merge's gate can take more: the queue waits on it.
- **Workers × threads ≤ jobs.** A test harness that runs several test binaries at once, each with its
  own thread pool the size of the machine, runs jobs² threads. Give the binaries one shared budget of
  threads, each taking no more than it has tests: a binary of three long tests needs three, not thirty.
- **Light debug info in test builds.** Line tables are enough for a backtrace; full debug info made every
  slot's target directory four times the size and every link slower (`[profile.test] debug =
  "line-tables-only"`, and none for dependencies, in Rust).
- **Long commands in the background.** The prompt tells sessions to run `done` and whole suites as a
  background command and wait for it: an agent's own command time limit cuts off a gate that waited for a
  lock, and a cut-off `done` commits nothing.
- **Union merges for append-only files.** A log or index every task appends to conflicts on every merge;
  `path merge=union` in `.gitattributes` joins both sides without a fix session.
- **Split hot test files.** A test file every task adds to is a conflict and a rebuild of that whole
  binary every time. A folder of modules (`tests/x/main.rs` + `tests/x/a.rs`) keeps tasks apart.
- **Test what changed on merges, all of it daily.** With `[run] test_since`, a merge's gate gets
  `{base}`, a commit that already passed: the shared branch only moves on a passed gate. Pick the tests
  that what changed since then can reach (a library change reaches everything that uses it, a test file
  only itself) and the merge of a test-only task takes minutes. The whole `test` still runs once
  `full_every_hours` pass without one, for whatever a selection misses. What that run finds is already on
  the shared branch, so with `failures` and `retest` set the merge it ran on still lands, and a critical
  task is filed to fix the test (and widen the selection). In the selection, a guess at what a slow test
  proves can spare a slot's own check, but the merge's gate should only drop a test that what changed
  cannot reach. When the shared branch gets code commits during a merge's gate, they are merged into the
  tested merge and only what they change is tested, from that merge: an hour's batch gate is not run again
  for a commit that landed in its last minutes. A conflict there, or a failure, builds the merge again.
- **One push per batch.** Each push to the shared branch is a CI run, so the runner pushes a batch once,
  when its last task lands.

## The prompt

The first turn of every session is `PROMPT` in `agent_runner/runner.py`, filled in for the task. It says:
nobody will answer questions, do this task only, commit only on `task/<ID>`, read the rules file, pass
the gate, keep a journal, finish with `done` run in the background (or `done --blocked … --after …` when stuck), a usage limit
isn't being stuck, use `plan` as a tool rather than reading TODO.md, and never hand-edit a box. Then
comes the brief.

It also tells the session to verify before asking: before it turns a check into an F task for a person, it
tries what is already here, `~/.claude/ACCESS.md` (this machine's logins) and the `## Tools`
section of the repo's CLAUDE.md (the repo's reach: ssh hosts, preview servers, headless checks). Only what
truly needs a person (a physical device, a judgment call) goes to one. `agent-runner setup` adds an empty
`## Tools` heading to CLAUDE.md (creating the file if needed), with a one-line comment on what goes there,
when it has none; a rerun leaves it alone. There is no separate TOOLS.md: every agent already loads CLAUDE.md.

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

## After a run

To end the run first, type `s` + Enter in its terminal ([Stopping a run](#stopping-a-run)) and let
the running tasks merge. A run left up keeps picking up whatever you commit to TODO.md.

1. `.runner/ledger.md` has one line per branch: merged, blocked, reopened, **parked as wip/<ID>, and why**,
   or, when even parking failed, LEFT FOR A HUMAN.
2. `git branch --list 'wip/*'` lists parked attempts. Their tasks stay open and start again by themselves in the
   next run (in a run that is up, once the line is edited), each pointed at its wip branch. Merge one by hand
   instead if it is right as it is.
3. `agent-runner plan` shows what's blocked (`[~]`). Each block says what would unblock it. `agent-runner plan unblock
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
agent-runner                           the run in the background (a detached tmux session; without tmux or on
                                       Windows a detached process, its slots hidden), the prompt straight back;
                                       `help` prints the usage
agent-runner attach [sN|c1|master]     the runner's pane, or a slot's (Windows: the slot's hidden console)
agent-runner control [N]               a control session in this terminal (c1: the kept one, resumed)
agent-runner control --new [N]         another one beside the run, without taking focus; prints its claude.ai/code link
agent-runner control --new --forward   the same, with the person's latest runner-feed message as its first
                                       message, read word for word from the feed's transcript (never retyped
                                       in a shell), and the files or images attached to it named with their
                                       paths; the runner feed hands requests on this way
  … --forward --runner                 the same, opened in agent-runner's own checkout (the clone it runs from,
                                       or a worktree under its [run] home) and labelled with this project: the
                                       feed hands asks about agent-runner itself (updates, releases, its bugs)
                                       on this way
agent-runner since [WHEN] [--follow]   what landed, started or got stuck since the last look (or WHEN: 2h,
                                       yesterday); --follow prints each new event as it happens
agent-runner plan [...]                the task list as a tool (agent-runner plan help)
agent-runner done ID "MSG" [--blocked WHY [--after X,Y]] [--artifact URL] [--no-test]
                                       --artifact: a concept's page (required for a K task)
agent-runner run [N|once] [--dry-run] [--mux tmux|hidden] [--model M] [--idle S] [--stall S] [--pause S] [--force] [--shutdown|--suspend]
agent-runner stop [--force] [--suspend|--shutdown]
                                       finish what's running, start nothing new, exit (or s + Enter in the
                                       runner's pane); --force ends the sessions now, to resume next run
agent-runner take ID [--merge|--drop]  one task in your own session or a subagent: a worktree on task/ID
                                       and its prompt; a run keeps off it. --merge after `done` there
agent-runner take "TEXT" --kind K [--files A,B] [--here]
                                       queue it (as `plan add`) and take it in one step; --here (also with
                                       an ID) moves the main checkout's uncommitted edits into the worktree
agent-runner resume ID...              continue each task's last session in its slot, once that slot is free
agent-runner cost [--days N]           where the workers' tokens went, by kind of tool call
agent-runner home [slots|plan]         where this project's worktrees and plan clone live
agent-runner context [--check]         what every session loads, by file and section; --check fails over budget
agent-runner help order                how to make one task wait for another
agent-runner --version
```

`./run …` in a clone is the same CLI. `--no-test` skips the gate.
`--shutdown` powers the computer off once no task is running or merging and no open task can start, after
120 s idle; new work in that window cancels it. On Linux it runs `systemctl poweroff`, which needs the
logged-in session's polkit permission; if the command is refused the run stays up.
`--suspend` is the same but puts the computer to sleep (`systemctl suspend`, `pmset sleepnow` on macOS,
`SetSuspendState` on Windows, which hibernates instead where hibernation is on). The run stays: when the
computer wakes it carries on, and it suspends again only after it has had work and gone idle again.

`plan` and `done` work on the checkout you're in (the agent's worktree). `run` always merges into the
main checkout. Set `AGENT_RUNNER_REPO` to use a repo from outside it.

## runner.toml

Every key is optional. Without a `runner.toml` you get the plan in `plan/`, no gate, 3 slots, and pushes
to origin. A worktree without its own `runner.toml` (because it's git-ignored) reads the main checkout's.

If `AGENT_RUNNER_CONFIG` names a file, the settings come from that file instead: from its
`[agent-runner]` table (`[agent-runner.run]`, …) if it has one, else from its top level. This lets a
project keep them in its own config file (see [docs/SETUP.md](SETUP.md#wrapping-it-from-your-own-cli)).

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
kinds = {}                # id prefix -> kind of work, e.g. { B = "bug", N = "netplay" }; `plan add` keeps to it
need_files = false        # `plan add` refuses a line with no files: and no test: field (else it warns)
lookup = []               # more files `plan <name>` searches for a heading, e.g. ["PLAN.md", "plan/guide/*.md"]
context_kb = 12           # budget for what every session loads (`context`); `run` warns past it, 0 = never

[git]
master_branch = ""        # optional local shared branch; must exist and be checked out
# empty uses remote HEAD, then main/master/trunk, then the current branch
push = "origin"           # where finished work goes; false turns every push off
push_merge = true         # push the shared branch after each tested merge

[run]
test = ""                 # the gate, run by `done` and on every merge, e.g. "make test"
test_since = ""           # a merge's gate on what changed since {base}, e.g. "make test-since REV={base}"
full_every_hours = 24     # with test_since: the whole `test` once none has passed for this long; 0 = never
slots = 3
mux = ""                  # tmux or hidden; "" = tmux inside a tmux session, else hidden (Windows: hidden)
include_task_id_in_commit = true
comment_policy = "normal"
agent = "claude"
backend = ""              # claude or pi; empty detects pi from the agent executable's name
model = "opus"
lean = true               # sessions get Bash/Read/Edit/Write/Artifact only, no MCP servers or user settings
remote = "auto"           # control sessions on Remote Control, and a control server to start more from claude.ai/code or the Claude apps; Enter in the runner's pane opens it. auto: on where it can work (see Control sessions); true/false force it
remote_slots = false      # the slots on Remote Control too ("<task title> · <repo> s2 · B646"); not
                          # recommended: every slot start pushes to the phone
silent = "launch"         # phone pushes from those sessions: launch = none while they start, true = none ever, false = Claude Code's usual
control = true            # a run opens control session c1 beside it; false: none (`agent-runner control` still works)
control_close = true      # close idle control sessions 2, 3, … (never c1): process ended, controlN.pid removed, transcript kept (`claude --resume <sid>`)
control_idle = "3h"       # closed once quiet this long, Claude spoke last, its last message is no open question, and nothing runs in it (a background task or Monitor; the needs-you watch does not count)
control_idle_quick = "5m"   # a session opened for one ask (a feed reply, `control --new --ask`) where the person sent only that message, a task got queued (`plan add` printed "added <ID>") and the last message is no open question: closed after this instead (looked at every 5 min, so 5-10 min); false: control_idle
control_idle_talked = "12h" # a session the person sent a second message in: closed after this instead (an open question still goes by control_ask_idle); false: control_idle. Slash commands (the runner's /rename), hook and system turns are not the person's messages
control_ask_idle = "2h"   # a last message that is an open question: after this long it is filed under Needs you as a DECIDE item (the question + the session link), then closed
control_open = ["?", "want me to", "should i", "shall i", "would you like", "do you want"]  # what makes a last message open (case ignored; "?" must end its last paragraph, the rest may stand anywhere in it)
control_file_asks = true  # false: an open question's session closes after control_ask_idle without filing it
control_ask_kind = "F"    # the id prefix of that DECIDE item's task (answering it reopens the task for a run to carry on)
auto_upgrade = true       # upgrade by itself when a newer release is out, as `u` does, once no merge runs; the run restarts on it (false: only `u` or `agent-runner upgrade`)
idle = 30                 # s quiet after a turn ends before a session without a successful `done` is ended (with one: 5 s)
stall = 1200              # s quiet at a prompt that counts as stalled
pause = 60                # s between one session ending and the next starting in that slot
weekly_max = 90           # % of 7-day usage past which nothing new starts
session_max = 90          # % of 5-hour session usage past which nothing new starts
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
suspect = ""              # regex: a BLOCKED line a merge adds that matches it is flagged in the ledger
untested = ["*.md", "LICENSE*", "COPYING*"]  # globs the gate can't see ("!glob" takes one back): no retest for these alone
docs_files = ["*.md", "docs/**"]  # a diff whose files all match is docs only: done and the merge skip the gate
docs_check = ""           # the quick check a docs-only diff runs instead (links, anchors); "" = none
failures = ""             # regex, group 1 = a failing test's name in the gate's output
retest = ""               # the gate for just {names}: rerun alone (load), then on the base (already failing)
flaky = ""                # regex, group 1 = tests a passing gate passed only on its own rerun (comma-separated)
flaky_kind = "T"          # the prefix of the critical "make <test> robust" follow-ups
ci_watch = "auto"         # "auto": workflows run on a push to the shared branch; ["pages.yml"]; false: off. A red newest finished run on the shared branch
                          # files one critical task (needs `gh` logged in)
ci_kind = "B"             # the prefix of that task
batch = true              # finished branches waiting for the merge go in together under one gate run, and one push
merge_ahead = true        # tasks finishing during a batch's gate are merged on it and tested beside it
batch_max = 16            # at most this many tasks in one batch; 0 = no cap
max_unmerged = 32         # past this many finished tasks waiting for the merge, each half batch more holds a slot; 0 = off
before_start = ""         # a command that must pass before any session starts (a display, a device)
not_attempt = ""          # regex on a branch's last commit subject ({id}): a phase, not the run's one try
shared_files = []         # files nearly every task names; not counted as an overlap
joinable = []             # globs of record-per-line files a conflict may be joined in (TODO.md, DONE.md merge by task)
fix_merges = true
fix_model = "opus"
fix_timeout = 1800
fix_ahead_max = 2         # fixes ahead at once (and so fix worktrees, fix1…): the rest wait their turn; 0 = under the lock
build = ""                # a quick build a fix or repair session runs before it commits (not the gate)
repair_merges = true      # a merge failing the gate gets one repair session before it is parked
home = "~/runs/{repo}"    # the worktrees (s1…, merge) and a [plan] repo clone (plan/), outside your
                          # repos folder; {repo} = the checkout's folder name. AGENT_RUNNER_HOME overrides
                          # it on one machine
                          # Scripts ask `agent-runner home [slots|plan]` rather than rebuild the path
slot_max_gb = 50          # a worktree over this loses its stalest build output before its next task; 0 = never
min_free_gb = 10          # under this much free disk: free worktrees cleaned, no new task starts; 0 = never
proc_max_gb = "auto"      # a process of the run's resident past this is killed; "auto": a quarter of RAM; 0 = never
min_free_mem_gb = 4       # under this much memory available: the run's biggest process is killed; 0 = never
slot_clean = ""           # a project's own clean, run instead of the trim and the full git clean -ffdXq
timeout = 3600            # s the gate, a retest or a hook (join, before_start, on_exit) may run: past it, failed

[run.join]                # glob = a command that joins a conflict in that file itself:
# "data/addresses.txt" = "./tools/join {union} {out}"   # also {ours} {base} {theirs} {file}; exit 0 keeps {out}

```

## What it leaves out

Nothing project-specific is built in. A project supplies it through hooks: a program per slot
(`slot_env`, `on_exit`), a check on new block reasons (`suspect`), a custom conflict join
(`[run.join]`), and extra brief text (`brief_extra`, `outline`). The ps2-decomp-kit mapping is in
[docs/SETUP.md](SETUP.md#worked-mapping-ps2-decomp-kit).

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
[docs/SETUP.md](SETUP.md#worked-example-opentennis).

## Library

`from agent_runner import plan, done, runner` and the names in each module's `__all__` are a stable API,
so a project's CLI can be thin wrappers (`plan.main(argv)`, `done.main(argv)`, `runner.cmd_run(argv)`).
See [docs/SETUP.md](SETUP.md#wrapping-it-from-your-own-cli).

## Tests

```sh
python3 tests/test_plan.py      # the plan tool
python3 tests/test_home.py      # [run] home: default, overrides, the pre-0.13 places
python3 tests/test_disk.py      # slot_max_gb, min_free_gb, extra slots removed
python3 tests/test_cost.py      # agent-runner cost: kinds of call, size × turns, Claude and Pi transcripts
python3 tests/test_plansync.py  # [plan] repo: two checkouts on one plan repo, merges, claims, tick on landing
python3 tests/test_runner.py    # picking, done, merge/join/land/push, fix sessions, wip parking,
                                # retry after unblock, prompt, Stop hook, resume, adopt,
                                # batches, flaky/inherited failures, the platform layer and the
                                # Windows slot shim (temp repos, fake agent)
python3 tests/test_pi.py        # Pi configuration, prompts, sessions, errors, and merge fixers (no network)
```

### Test entries in ~/.claude.json

The suites keep Claude Code's config in a temp `CLAUDE_CONFIG_DIR` (`tests/_check.py`), so the folder-trust entries
`Claude.trust` writes for test worktrees never reach the real `~/.claude.json`; every suite fails if one does (each
suite's temp folders sit under one root of its own, so other sessions' entries are never blamed). Suites from
before 0.41.0 (2026-11-18) other than `test_runner.py` had no such isolation and left entries like
`…/Temp/tmpXXXX/proj-slots/s1` and `…/agent-runner-test-runs-XXXX/proj/s1` behind, on Linux and Windows alike.
`python3 tests/_check.py` lists them (bare trust entries under the system temp folder, never a folder a Claude
session itself ran in); `python3 tests/_check.py --clean` removes them, best with no Claude Code session open.
The `policy-fixture` entries seen only on Windows did not reproduce on Linux (every trust call there goes to the
temp config); if a suite still leaks on Windows, its check names the entries it added.
