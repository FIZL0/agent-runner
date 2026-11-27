# agent-runner reference

Everything the [README](../README.md) leaves out: how a task runs end to end, picking, merging, fix sessions,
disk and memory, stopping, the prompt, every command and every `runner.toml` key. Setup is in
[SETUP.md](SETUP.md).

## How it works

```
plan/TODO.md ──pick──▶ slot N: git worktree ~/runs/<repo>/sN on task/<ID>
                         hidden terminal sN: claude "<prompt + the task's brief>"
                         …the session works, then `agent-runner done <ID> "msg"` (test gate → tick → commit → push task/<ID>)
                         Stop hook: quiet for 30 seconds → the session is ended
               ◀─merge── merge worktree ~/runs/<repo>/merge: merge main + task/<ID>, join line-records,
                         a fix session for real conflicts, the test gate on the merge
                         → land in the main checkout → reopen what it unblocked → push main
```

1. **Pick.** It reads `plan/TODO.md` *on the shared branch* (what is committed, not what you're
   editing) and walks it top to bottom. See [Picking](#picking) for what it skips.
2. **Start.** Slot N gets a git worktree in `~/runs/<repo>/sN` (`[run] home`) on branch `task/<ID>`, and a hidden terminal
   (see [Terminals, and Windows](#terminals-and-windows)) whose output goes to `.runner/slotN.log`. It runs
   `claude --session-id … --model … "<prompt>"`, with Claude Code's Stop hook set to the runner's idle
   timer. The prompt includes the task's brief (`agent-runner plan brief <ID>`): its line, its `plan/tasks/<ID>.md`
   long form, the files it names (or "missing: this task creates it"), and the newest journal entry.
3. **Finish.** The session ends with `agent-runner done <ID> "msg"`. That runs the test gate, ticks the task
   (`[x]`, and the line moves to DONE.md), commits, and pushes `task/<ID>`. If the gate fails, nothing is
   ticked or committed. A session that's stuck runs `done --blocked "why"` instead.
   A file its own output goes to (`done … > done.log 2>&1`) is left out of the commit.
   Before the gate, `done` runs the [removal check](#the-removal-check) on what the diff deletes or renames.
   Failed gates are counted per task (a pass or a block resets the count), each with a hash of
   the worktree's content (uncommitted and untracked files too, not ignored ones). After three, `done` runs one more gate only if
   that changed since the last failure; unchanged, it refuses without running, and a changed one that fails
   refuses until the task is blocked. Until that gate has run, `--blocked "CONFIRM: …"` is refused, since a
   person cannot confirm a gate, and the refusals ask for the failing test's or check's name in the block.
4. **End the session.** The session goes quiet at its prompt. The Stop hook's detached timer sees no new
   transcript entries for 5 s once `done` has succeeded, or 30 seconds when it stopped without it, and ends it. If a human typed in it (`attach sN`), or a usage
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
   - a conflict in the glossary file (`[plan] glossary`) is joined by term entry, not by line, with no
     setting: terms added on either side are both kept, an entry changed on one side takes that side; one
     changed differently on both sides, or a side that does not parse, goes to a fix session. As with
     `joinable`, one other conflicted file that cannot be joined sends the whole conflict there;
   - any other conflict goes to a one-shot fix session (`claude -p`);
   - the gate runs again if the merged code differs from what `done` tested.
   Only then is the main checkout moved to the tested merge. That takes seconds, it never stashes, and it
   waits if someone has uncommitted edits to the files involved.
6. **After the merge.** `plan reopen` unblocks tasks whose `BLOCKED: (after X)` just landed and commits that.
   Then `main` is pushed (`[git] push_merge`), and the remote `task/<ID>` is deleted once the remote `main`
   contains it.
7. **Repeat** until nothing can start. Then the run [goes idle](#it-stays-up) and waits for new tasks.

### Terminals, and Windows

Every session the run starts (each slot, each control session) runs hidden: a terminal with no
window, the same way on every OS (0.60.0 removed tmux and `[run] mux`; a leftover `mux` key is ignored with one
warning). You watch and steer it through `agent-runner attach` (the run view), `attach sN` (the session's own terminal),
`agent-runner ui` and the run page, Remote Control (claude.ai/code and the Claude apps, with `[run] remote_slots`),
`agent-runner status`, the slot's log `.runner/slotN.log` and control sessions; `plan tell <ID> "…"` types into it. On
Linux and macOS it is a pseudo-terminal from Python's standard library (`pty`), 200 columns by 50 rows, and its output
goes to the slot log. On Windows 10 1809 and later it is a ConPTY pseudo-console (stdlib `ctypes`), also 200 by 50, and
its output goes to the slot log. `plan tell`, budget stops, a typed `/rename` and the run page's send and keys reach it
through `.runner/slotN.in`, a small file that names a named pipe only this user can open, from this machine. When the session
ends its pseudo-console closes, which ends what it left running there. Before 1809
(no ConPTY) it is a console of its own whose window starts hidden (`attach s2` shows it); nothing captures its output
there, and `plan tell` cannot type into it. One slot, and `once`, run like any other count: a worktree, a session, a tested merge.

A hidden slot runs through a small shim, `run --slot-shim`, started detached so the session outlives a restarted runner.
It starts the agent and keeps its pid in `.runner/slotN.live` while it runs (and reads `.runner/slotN.in` for what `plan
tell` types: a FIFO on Linux and macOS, a pipe's name on Windows). The loop, a restarted run's adopt and the Stop hook
read that file; how the agent ended goes to `.runner/slotN.exit`. The rest of the Windows differences are in
`agent_runner/plat.py`: the run lock is `msvcrt.locking`, process checks go through kernel32 (stdlib `ctypes`, no
psutil), an ended session's windowed processes (an emulator, say) get WM_CLOSE and up to 10 s to exit before `taskkill
/T /F`, and `[run] links` become a junction (directory) or hard link (file) when symlinks need Developer Mode. A prompt
over 24,000 characters (a Windows command line holds 32,767) is handed over as a file the session is told to read.
`[run] test`, `on_exit`, `before_start` and the other commands run in the platform's shell, which on Windows is
`cmd.exe`.

### In the background

At a terminal, bare `agent-runner` opens the run picker: one row per run on this device, the current folder's project first. Picking a row opens its launcher, the second screen, and never starts a run by itself; a run that is not up shows `not running · N tasks left`, and `s` there starts it as the background run below, from that project's checkout (logged as started by picker). The launcher then shows the run up with its link, or the error. No pick, and none of `w`, `t`, `c` or Enter, starts a run. For a run not up, `w` opens its run page through the page-only process (see The run app): it starts that process if none serves, and starts no run. `c` copies the page's link while one serves (Runner Home's /p/KEY/ when Home routes the project, else its own address), else it says `no run page yet`. Where there is no TUI (Windows; also no tmux, `tui.refusal`) the launcher has no `t`, shows the reason in a dim line and the link, and Enter opens the run page as `w` does (its key line says `⏎ open the run page`); elsewhere Enter is the terminal UI.

Without a terminal (and in a slot), bare `agent-runner` starts the run where no terminal shows it and returns within seconds: a detached process
(`plat.spawn_detached`: `agent-runner run`, its output in `.runner/background.out`), its slots hidden (see above). The
launch waits for the run's start line in `run.log`, then prints the slot count and the commands: `status`, `attach`,
`stop`, and claude.ai/code with `[run] remote`. If the run fails within that time, it prints the end of its output. If a
run is already up it says so and starts nothing. In a folder that is not set up, a bare `agent-runner` (and the run picker) names `agent-runner demo` in one line (F194c). `agent-runner run 3` is the same run in the foreground of this
terminal, its log printed there and its keys read from it. On Windows each slot gets a ConPTY pseudo-console with no
window (before 1809, a console that starts hidden, `STARTUPINFO.wShowWindow = SW_HIDE`); either way the agent has a TTY.

`agent-runner attach` (or `attach run`) is the run view, from any terminal and over ssh: the end of `.runner/run.log`,
then each new line as the run logs it, and the runner keys typed there (`s`, `s!`, `p`, `f`, `+`, `-`, `slots N`, `z`,
`x`, `u`, `?`, and an empty line for Remote Control), each posted to the run through `.runner/KEYS` as `agent-runner
key` does. `?` lists them (they print once as the view opens too). Ctrl-C leaves the view; the run keeps going.
A hidden session (`attach s2`, `attach c3`, or the session tab of `agent-runner ui`, which shows it beside
its panels) is attached to its own terminal, the way dtach does it, on Linux, macOS and Windows 1809 and later. On Linux
and macOS the shim listens on a Unix socket beside its marker (`.runner/slotN.sock`, `controlN.sock`, mode 0600, gone
when the session ends). On Windows it listens on a free 127.0.0.1 port, and that `.sock` file is a small file holding the
port and a token, readable by this user only and gone when the session ends; `attach_windows.py` is the client, and it
sends the token first. A client that does not send it within 5 s, or sends a wrong one, is dropped with nothing sent to
it. Either way the shim sends what the session prints to every attached
terminal and types in what you type. The session takes the smallest size of its viewers (each attached terminal, each
connected session frame of the run app), 200 by 50 when there are none, and a new viewer makes it redraw. A viewer that
takes its output slowly gets a queue of 256 KB, then a redraw of the whole screen once it catches up, so it neither stalls
the session nor is dropped; one that takes nothing for 60 s is dropped. This holds for sessions started after the upgrade. Detach with Ctrl-b d
(Ctrl-b Ctrl-b types one Ctrl-b); the session keeps running. The run app's session frame has no detach key: with
`AGENT_RUNNER_WEB` set, Ctrl-b goes to the session, and leaving the chat only hangs up its connection. Before 1809 on Windows,
`attach s2` shows the hidden console and raises its window; minimize it to hide it again, and closing it ends that
session, which resumes in the next run. A headless stream slot, or a session with no socket (one started before this),
has no terminal to attach: `attach s2` says where its log is.

With `[run] remote` (or `remote_slots`), Claude Code asks once, at a terminal, "Enable Remote Control? (y/n)".
In a hidden session that question would hold every session. So before going to the background the launch checks `remoteDialogSeen` in
`~/.claude.json` (or `$CLAUDE_CONFIG_DIR/.claude.json`). If it is not set, the launch asks the question in this
terminal and records the yes there. A no, or no terminal to ask in, starts nothing. Under `remote = "auto"`
(and no `remote_slots`) it starts the run anyway, with Remote Control off and the reason in `run.log`.

### Control sessions

A control session is an interactive Claude Code session in the main checkout where a person runs the run, at
the terminal or from claude.ai/code and the Claude apps: "status?", "pause", "one slot more", "stop", "add a
task to fix X" (it files it with `plan add`), "do X now" (it uses `take`, never edits the main checkout).

- **No kept chat** (F176). The run opens no control session of its own and resumes none. `[run] control = true` (the
  default; false: none) means the run reopens the control sessions a shutdown cut off (B121: the self-restart on
  `upgrade` or `auto_upgrade`, a crash or a kill, a stop that never logged its end) and, with `[run] remote`, keeps the
  control server up. A session that ended while the machine was up is forgotten. Each control session runs in a
  terminal with no window, through the same shim as a hidden slot, its output in `.runner/controlN.log` (before 1809 on
  Windows, a console of its own that starts hidden); `attach cN` goes there (on Windows 1809 and later too). Its session
  id is kept in `.runner/controlN.sid` for `control N --reopen`; a run start deletes an older `.runner/control.sid`.
  Numbers start at 2 (`FIRST_CONTROL`). 1 was the kept session's and is retired, so a c1 an older runner left running is a
  chat like any other: it lists, idles closed, can be deleted, renamed and resumed.
- **Every prompt opens one**: the run app's Home box, a Status quick ask, Say what to change (a chat edit), a concept
  change, a typed reply under Needs you (not a DECIDE's, see below) each open a new control session
  (`control --new --ask`), named for its ask (its first words; `control --title` sets another name). From the run app and
  `agent-runner ui` it starts without waiting for its link. A message in an open chat goes to that chat. In the run app no
  chat is protected: any can be deleted or go Quiet.
- **More of them**: `agent-runner control` opens a new session in this terminal, blank, with no opening summary (ask for
  one to get it); the next free number from 2, `.runner/controlN.pid`.
- **A new one from inside one** (the phone apps have no new-session button): `agent-runner control --new [N]` opens the
  next free control session without taking focus: hidden through the slot shim, its output in `.runner/control<N>.log`
  (Windows: a ConPTY pseudo-console, or before 1809 a hidden console); `attach cN` shows it (on Windows 1809 and later too). On Windows the first message still goes on the command line. A name it takes
  (`control --title`) is kept in `.runner/control<N>.title`, where `list`, `agent-runner ui` and the run page read it.
  `control --rename N NAME` (the run app's Rename, r in `agent-runner ui`) is the person's own name for it: typed in as
  `/rename NAME`, so the session is never closed when idle and `control --title` leaves it. With `[run] remote` it
  watches that log for up to 90 s and prints its `claude.ai/code/session_…` link, so the control session that ran it
  answers with a link to tap. Tell a control session "new", "new session", "/new" or type `/control`: its brief maps
  those to `control --new`. `/control` is a skill only control sessions get, in
  `.runner/control-skills/.claude/skills/control/SKILL.md`, added with `--add-dir` and the settings'
  `permissions.additionalDirectories`, never in your repo's files. It is not named `/new` because Claude Code's `/new`
  is an alias of `/clear`, which would wipe the session instead. Whether the phone app passes a typed `/control` through
  to the session is still to be checked by a person; "new" works either way.
- **Held messages**: a person's messages to a control session whose reply was only a usage-limit error are held, all in a
  row, with their images. The reset is read from the transcript error's own fields (`rate_limit` and `resetsAt`), else
  from the reset its words name, else 1 h (doubling with each try that meets the limit again, to 8 h at most). `status` shows one line
  per chat (how many asks, which chat, when it resets), the run log says it once, and such a session is not closed as
  idle. After the reset (+1 min) the run types them in as one message marked `[agent-runner: held by the usage limit]`,
  in order, reopening the ended session hidden and resuming its transcript (under another number if its number is in
  use; only with `[run] control = true`). A try that meets the limit again, or is cut off by it, leaves them held till the new reset. The
  records in `<notes>/held/<sid>.json` survive restarts. Ones the person sent again (the same words, more than
  three, and the same files) and got answered in any session of the checkout are left out, and a turn begun by a person's message that gets answered counts as answering the earlier
  ones (Claude Code sends them along). They are dropped when the person closes the session on the run page or the TUI,
  sends `/exit` or `/clear`, archives it in the apps, or interrupts it while it is being answered. After 3 failures (the
  session will not come up, or another API error) `status` says to send them again. Limits: a session ended by Ctrl-C or
  Ctrl-D, a closed terminal or a kill leaves no sign of purpose, so it is reopened; a session live in a terminal with no
  hidden shim cannot be typed into and waits till it ends (`status` says so); sessions started from the apps' control
  server have no number and are not covered; a message whose reply had begun before the limit is not held. Not tried
  against a real limit yet: it was checked against transcripts only (the real ones of 2026-11-22 were read).
- **Items settled elsewhere**: a control session about a task or a Needs you item (its title starts with the id, or it was
  opened from that item: the first message of the chat gives it; or it filed the item itself: a concept, with its build task, by
  `plan concept`, a restyle, with its build task, by `plan restyle`, a `plan block ID "DECIDE: …"`, or its own open question, which the run filed when it
  closed the chat, once that is open again; kept per session id in `<notes>/settled/<session id>.filed`, so another
  session that gets the same number is not it) is told, once per change, when a command settles or changes
  that item: plan drop, change, edit, confirm, approve, revise, shelve, unshelve, restore or unblock; a tick of an item under
  Needs you; `sheet`; pitch approve or no; or the run's undo. That holds whether the command runs from the run page, the TUI
  or a terminal. The run types one line into the session: `From the runner, not the person: R81 was dropped at 13:28 by c4:
  <reason>. Re-read it before asking the person anything for it.` (`by` names who ran the command, c4 or a slot's agent; the
  reason is the one the command gave, if any). Not told: the session that ran the command, sessions that only mention the id,
  sessions ended or closed online, and conversations begun after the change. Each change leaves one event in
  `<notes>/settled/`, marked there before it is typed, so a restarted run does not type it twice. A session with a question
  dialog up, held messages or one just starting waits; a turn running queues the line in Claude Code. The line is not a
  person's message: it is never held and not counted for the idle close (Claude's reply to it is activity,
  as any turn is; a `DECIDE:` line that still stands is repeated in it, as the needs guide says). An ordinary landing says nothing. An item a live
  chat waits on under Needs you (`waits.json`) that leaves Needs you with no command is told about two minutes after, as are
  changes no command announces (a pulled plan, a hand edit). When a concept and its build task leave Needs you with no command,
  one line is typed, not two. Limits: sessions open in a terminal with no hidden shim, and
  those started from the apps' control server, are not told; events older than a day are dropped; a run must be up. Not tried
  with real Claude sessions: typed-in delivery, a message arriving mid-turn, and how the transcript records it were tested
  only against made-up transcripts.
- **Decided chats close** (F209b): when the person settles an item for good from the run page, the TUI or a pick link
  (plan drop, confirm or approve, so also an answer or option button and `sheet`), the chats about it are closed in place
  of being told: the process ends, the transcript stays (listed as closed, Resume brings it back), and run.log says
  `control 4: closed, R81 was dropped by the person`. Shelve, revise, change (a No) and the rest type the line as before, as
  does a decision made in a chat, by an agent or by the run. A chat stays open and is told when the person spoke last,
  its last message asks another DECIDE, a background task or a take it started runs, a message is held, a question
  dialog is up, it is about another item still under Needs you, or the person renamed it (run.log: `kept open, … but
  <why>`); a chat whose turn is under way is looked at again once the turn ends. The event is marked before the close,
  so a restarted run closes nothing twice.
- **Their settings**: every control session, and the control server, gets `.runner/control-settings.json`
  with `--settings`: a SessionStart hook that runs `agent-runner control --brief`, which prints the control
  brief (so a resumed or compacted session gets it again). They run on `[models] control` with every tool
  (`[run] lean` is for slots) and in bypassPermissions mode, as the slots do: driven from a phone or the web,
  a permission prompt would stall them.
- **The opening**: the first message has the session run `agent-runner status` only and say, in plain bullets
  under headings, what the run is doing now: the headline, then the groups Running, Landed and Stuck, then one line
  of hints: `/run · /since · /follow · /control · /pause · /stop · /slots · or just describe a bug or idea to queue
  it`. Later answers are bullets too, each task id with its short title. A session a prompt opens takes the prompt as its first message, not this opening; a blank one (`agent-runner control`) has none until asked.
- **Blocked and Needs you items**: left alone. A control session does not mention, list, count or ask about them,
  in an answer, the opening or a status, unless they bear on what you are discussing or you ask ("what needs me?",
  "what is blocked?"); the run page and `agent-runner ui` show them. A status starts with its headline, and a
  `DECIDE:` line is only a question of the session's own, never an existing item restated. The brief asks for the answer
  bracket on that line; a question is kept whole up to 2000 characters, and a longer one is cut before its bracket (and the links after it), so the bracket survives when it is filed under Needs you. A reply that answers an
  item still settles it.
- **Needs you, unasked**: no control session starts a watch on its own. The run page, `agent-runner ui` and `status` show what needs you (a run held, a task left for a human, a task waiting on your answer, a device alert, a pitch), and nothing pushes it to a phone unasked. When a person asks ("notify me when something needs me", `guide watch`), the session runs `agent-runner since --follow --needs-you` under the Monitor tool and posts each line as one plain bullet, sent with PushNotification so a phone hears it. The watch starts with `timeout_ms 1800000` (the Monitor tool's cap); when it times out with nothing printed the session starts it again silently, with no "still watching" line, so a quiet run posts nothing.
- **Following**: say "follow" (or "live", "/follow") and the session runs `agent-runner since --follow` under
  the Monitor tool and posts each line it prints as a bullet; "stop following" ends it (see [status and
  since](#status-and-since)). It is the full feed, so the needs-you watch stops while it runs and starts again
  after.
- **With `[run] remote`** each control session starts with `--remote-control "<repo> · control N"`, and the
  run keeps `claude remote-control --spawn same-dir --no-create-session-in-dir --name "<repo> · control" --settings <file>` running in
  the main checkout (output in `.runner/control-server.log`, errors in `.runner/control-server.err`; one that
  quits within a minute puts its last error line in `run.log`), restarted when it exits (Remote Control quits
  after about 10 minutes offline; 30 s, doubling to 10 minutes while it keeps failing), so new control
  sessions can be started from the app. The server starts with `--no-create-session-in-dir` too, when `claude remote-control --help`
  lists it: found on Claude Code 2.1.330, the session `same-dir` pre-creates is not archived on SIGTERM ("Skipping archive+deregister to allow resume") and every later server in that folder adopted it, after a clean stop and after SIGKILL, which is how an old "<folder> · control" chat kept coming back. With the flag nothing is kept: a stop deregisters, and each start gets a new environment. Right after an upgrade from an older server the new one can be refused ("This folder is already served…") for up to about five minutes; the run retries it. `--settings` goes in only when `claude remote-control --help` lists
  it (asked once a run): an older Claude Code starts without it, so its app sessions get no control brief,
  and `run.log` says to update. The run's end ends it. A slot's listing in the apps follows `[run] remote_slots` (see Slots in the Claude apps below): `"always"` starts each as "<task title> · <repo> s2 · B646". That is not the default and not
  recommended: every slot start pushes to the phone (see Phone pushes below). Watch hidden slots through
  status and control sessions instead.
- **Slots in the Claude apps (`[run] remote_slots`).** `"open"`, the default, lists a slot in the apps only once it is opened, and no slot starts on Remote Control by itself. `agent-runner ui`'s Sessions panel opens one (its session tab, "open sN in the Claude apps"; the run app has no such button): the run types `/remote-control <name>` into that slot's session, which is listed from then on until it ends, and its claude.ai/code link shows in the page. For when this machine is not reachable, the run keeps a claude.ai copy of the run page: on a run event (a
  task starts, lands or blocks, a needs-you item, a concept, the release; at most every 10 minutes, and only
  when the page changed apart from its clock, log and minutes) the run writes `.runner/run-page-copy.html` and
  publishes it with a one-shot headless `claude -p` that has only the Artifact and Read tools (Artifact refuses to publish a file when Read is off, B180), to the URL kept in
  `.runner/run-page-copy.url`; never through a control session. After 3 failed publishes in a row
  the copy stops for that run. The copy is read-only, with each chat as a session link.
  `"always"` lists every slot as its own entry, "<task title> · <repo> s2 · B646", and keeps no copy. An old `remote_slots = true` with `sessions = "each"` reads as `"always"`, any other old `true` as `"open"`.
- **`remote = "auto"`, the default**, is on when Remote Control can work: Claude Code on a claude.ai login.
  It is off, with one `run.log` line saying why (`remote control off: …`), when
  `ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN` is set, `CLAUDE_CODE_USE_BEDROCK`, `_VERTEX` or
  `_FOUNDRY` is set, `ANTHROPIC_BASE_URL` names a host other than api.anthropic.com, or Claude Code's
  "Enable Remote Control?" has not been answered yes. `true` forces it on, `false`
  keeps it off; any other value is refused.
- **Phone pushes.** Each Remote Control session the run starts (a control session, the control server, a slot
  with `remote_slots`) pushes to the phone as it starts: Remote Control's "session ready" push goes out as the
  session registers, and no setting or environment variable in Claude Code (checked up to 2.1.330) stops it,
  short of turning off the Claude app's notifications on the phone. `[run] silent` (true/false, default
  false) is about the pushes after that. `false`: Claude Code pushes as it would for any session. `true`:
  each session gets `CLAUDE_CLIENT_PRESENCE_FILE` naming a file kept for good (`.runner/quiet-c<N>`,
  `.runner/quiet-server`, `.runner/quiet-slots`; while it exists Claude Code sends no mobile push, 2.1.181+),
  so nothing pushes after the start; slots also get `agentPushNotifEnabled: false` in their `--settings` (no
  PushNotification tool). The old `silent = "launch"` (quiet only while a session started, which never
  stopped the start push) reads as `false`, with one `run.log` line.

### Runner Home

`agent-runner home install` is the recommended setup, part of the default one (README Quick start, right after
`setup`), not an optional extra. It installs one always-on page for every project on this device and prints its
link and a QR code. With several projects on one device it is what keeps every run's page reachable: one link,
each run at `/p/<project>/`. Without it, the first run up serves its own page on port 8770 (and when it stops, the page-only process serves that page at the same address, see The run app); a
second run (its port taken) serves on every interface on the next free port (8772, 8774, …), and its status and run log list its links. `home status` shows whether it is installed and serving;
`home add PATH` lists a project outside `~/repos`. See the README's Runner Home section.

With no projects, Home's page offers Try the example project beside Add a project (`POST /example`). It makes `~/agent-runner-demo` (or takes the one already there), lists it and opens its page; nothing starts.

Trusted networks (F136): `home trust add NETWORK` (remove NETWORK: stop) lets a client on a CIDR, or on `tailnet`
(100.64.0.0/10 and fd7a:115c:a1e0::/48), open Home or a run's page without `?t=`. The list is Home's `trusted_networks`
in `home.json`, and `home status` lists it; it takes effect with no restart. Through Home a run's page uses that list,
and Home fills the run's own key on `/p/<project>/`. A run's own page (not through Home) reads `[ui] trusted_networks`
at the run's start. Loopback is never trusted; a bad network is an error that names it. Printed links drop `?t=` only
when every address their host resolves to is trusted. Anyone on a trusted network can do everything the page does (one exception: with no key, opening an off project's page starts no page-only process; it shows the off page with Start run),
including type into sessions, so with no key a request must come from the page itself (another site's page is refused),
at an IP address, a `*.ts.net` name or a local one (a bare name, .local, .lan, .home, .home.arpa, .internal,
.localdomain); at any other name the key is needed. Behind a proxy on this machine (Tailscale Serve) the client is the
last address in `X-Forwarded-For`, read from a loopback peer only, so another program on this machine can fake it.

Home's links put the https address first, and only while `tailscale status --json` says BackendState Running; otherwise the plain http links are given, with no error. `home status`, `home install` (and its QR code, which holds the https
link when there is one) and a run's link through Home (`/p/<project>/`) list a Tailscale Serve https address for
Home's port first, then http by hostname and LAN address; Talk's mic and dictation need https. With no Tailscale
Serve for Home, `home install` runs `tailscale serve --bg --https=8771 http://127.0.0.1:8770` (Home's port plus
one) without asking, as runs do, when Tailscale is connected and port 8771 is free; otherwise it prints
`http only (<why>)` (F461). Then, in a terminal only (skipped when stdin is no tty, or `tailnet` is trusted
already), it asks once, y/N, default No, whether devices on the tailnet may open Home and run pages without the key
(`home trust add tailnet`), warning that anyone on the tailnet can then do everything the page does. Home's page
is now the run app itself: at `/` it is the Overview, Needs you over all projects, then a card per project with one
main button (Start run or Open) and a … sheet for the rest (Pause or Go on, Slots, Stop and Unlist; the last two ask first), plus
a + Project button and Devices. Projects with a run up (running, idle or paused) come first, then
those off, by name in each group. Through Home, a run's app (`/p/<project>/`) has an "All projects" row at the top of
the sidebar, with a count of what needs you in other projects; tapping it turns the sidebar into the project list
(Overview, Running, Idle, Off, Devices), and each project in it moves to `/p/<project>/` on the same Home address. Another project opens at its Home view (also from a card); coming back down to the project you were in restores what was open. An
off project's page has Start run; a page load of `/p/<project>/` with Home's key starts the page-only process, and the page turns into the run's app once it answers (see The run app).

The run app's page is sent gzipped when the browser accepts gzip, compressed once per page version and project, with an
ETag and `private, no-cache`, so a switch back to a project gets a 304 with no body; the key is still checked first.
This is the same on the run page, through Runner Home's `/p/KEY/`, on Home's own page and on the page Home shows for a
project with no run up. The run page's other answers stay `no-store`, and `/events` is never compressed.

`/events` sends a snapshot (`data:` only) when it changes and, after 15 s with no change, a ping (`event: ping`, data
`1`), which Runner Home passes as it comes. The page counts both as heard: with nothing heard for 33 s (about two pings,
a socket that died quietly) it closes that stream and dials again, showing the lost-connection bar if no answer comes in
8 s; shown again, back from the browser's page cache or online, it dials at once unless something came in the last 5 s.
One stream is open at a time. An error drawing a snapshot is logged in the browser console (B838).

On a phone's Home Screen: add the app from Home's link. Home's root is the app's scope, so a move between projects stays in it. It opens on the project it was added
from, or on the Overview if it was added from Home. An icon added before this change: remove it and add it again once,
since iOS may keep the old scope. The manifest and icon hold the token the link has, so whoever has the manifest has it
already. A run's own address (no Home, or its own `web_port`) is an app of its own; its project name leads to Home's
address, another origin, which iOS opens outside the app.

Runner Home restarts itself when agent-runner's package files change on disk (an upgrade or a clone's pull, same
version or not), once the change holds over two 5 s looks. It re-execs in place, never while a request or terminal
tunnel is open; runs' event streams end when only those are left, and pages reconnect by themselves. On Windows, which
has no exec, a detached helper waits for the old Home to exit and starts the scheduled task again (`schtasks /End`,
`/Run`, up to three times until Home answers); `home uninstall` disables the task first, so a restart under way cannot
bring it back. It does so only when the scheduled task runs Home (`pythonw.exe`): a `home serve` typed in a terminal,
or a Home run with `python.exe` because there is no `pythonw.exe`, does not restart itself. Windows Home writes its
output to `home.log` in Home's config folder. A Home started before this needs one restart by hand; unlike a run, it
also restarts across a breaking version. Home has no `auto_upgrade` setting. Its page (`/projects`) shows the same popup, from `page` and `restart_needed`: where Home cannot restart itself, "A new version is ready. Restart Runner Home to use it." with Later.

### The run app

With `[run] web` (on by default) a run serves the run app from this machine on `[run] web_port` (8770), bound
to every interface so a phone on the LAN or Tailscale reaches it. With Runner Home installed, the run listens on
127.0.0.1 only, on a free port that only Home opens (its session frames too, which Home's tunnel carries), and no link,
log line or status names that port: one address for every project. A `web_port` the person sets (not the
default) stays open on every interface, unless it is Home's own port, which is kept for Home (with Home installed, a taken one is on 127.0.0.1 instead). Without Home, a
second run (its port taken) serves on every interface on the next free port: every second port after `web_port` (8772, 8774, …; the port after each is kept for its https address; a pair that Tailscale Serve or a recorded rule uses for something else is skipped), up to 20 tries, then any free port. Its run log says `port 8770 is taken (...), so it is on port 8772`. The Serve rule of the run or page holding `web_port` is left alone. The address, with the token every request
needs (made once per project in `.runner/web.token`), is in `status` and the run log. It is a chat app over
the run page: the same snapshot as `agent-runner ui` and most of its actions (not opening a slot), laid out for a phone (the sidebar becomes a
drawer) and a desktop. It follows the browser's light or dark setting; `[ui] theme` is the terminal UI's only.

With no run up and the page-only process serving the page, Home opens with a Start card at its top: Not running, with one Start the run button (Starting the run… while it starts; after a failure, Not started: why, with Retry and Discard in its place). Talk is then a plain button, and the card goes once the run is up. A bar under the top bar says The run is not running, with one Start the run button; it shows on every view but Home and Status (on those two only while a chat is open), not on Runner Home's page or All projects, and only from a fresh snapshot. Runner Home's off page is only the fallback for when the page-only process cannot start. The open page's event stream, when an error answer ends it for good (Runner Home or Tailscale Serve answer that while a stop or a start hands the page over), is dialled again by itself after 1, 2, 4 … 15 s; the view, chats, drafts and outbox stay as they were, and a feed request answered with a 5xx error leaves a chat's words as they were. When Runner Home answers that nothing serves the page (502 with `closed: true`), the lost-connection bar shows after about 8 s The run page is closed with Reload: a page load with Home's key, which starts the page-only process again (through the off page, then the run page) and keeps what is typed, as Refresh does. Nothing starts by itself, so an open page does not undo `page-only stop`; the bar goes once the page answers again.

While no run is up, the run page is served by a **page-only process**: `agent-runner page-only` (foreground; the launcher's `w` starts it detached and opens its page, one at most per project, Linux and Windows). It serves the project's full run page, so new chats, messages, Resume and the plan actions work there, but it starts no slot, task, merge or push, and `status` says no run is up. It ends after 10 minutes with no page open only where Runner Home can start it again (Home opens this project's page, answers, and lists the project); with no Home, or a `web_port` of its own, it stays up until a run takes it over or `agent-runner page-only stop` ends it (that command exits 0 also when none serves, and 1 if the process does not end in 20 s; it asks through `page.stop`, the note a starting run leaves too). A run that starts takes the page over (same key, same port; an open page reconnects by itself), and no chat ends with it. A run's stop hands its page to one the same way, before it says `run stopped` (same address, port and key; `up` stays false); if the handover fails, the run stops and the page closes. No page stays after a stop with suspend or shutdown, or with `[run] web = false`. `[run] web = false` means none. It serves on `web_port`, or, when that port is taken and there is no Runner Home, on every interface on the next free port, as a run does (above), and keeps that port when a run takes it over (`web.fell` in the notes folder records `web_port` and that port). Its files in the notes folder: `page.lock` (held while it serves), `page.live` (once its page answers), `page.out` (its output), `page.stop` (a starting run's or `page-only stop`'s ask that it end) and `page.hand` (what a stopping run hands over, gone once done). What still needs a run's loop: closing idle chats, ending ones closed online, and bringing back chats a shutdown cut off (a run's start does that; Resume works by hand). Messages a chat held for a usage limit are put in by the page-only process too. Runner Home routes `/p/KEY/` to it while it serves, and starts it when a page load of `/p/KEY/` with Home's key finds no run up (in the background, one start at a time per project; a fetch, frame or prefetch starts nothing); if it cannot start, Home's off page stays and the next opening tries again. Started by Runner Home's systemd service, it (and a run Home starts) runs in a systemd scope of its own (where `systemd-run --user --scope` works), so stopping or restarting the service does not end it.

The browser gives the microphone (Talk) only to https or localhost, so a run on every interface with Tailscale connected also gets an https address (the Tailnet address): it runs `tailscale serve --bg --https=<port+1> http://127.0.0.1:<port>`, where port is the port the page serves on (`web_port`, or the port it fell to) and prints `https://<host>.<tailnet>.ts.net:8771/?t=…` first in `status` and the run log. `[run] web_https = false` makes none. The rule is recorded in `serve/<port>.json` in Home's config folder; the run turns it off at its stop, and the next start of that project, or of a run on that port, takes over or turns off a rule a crashed run left; rules the runner did not make are left alone. Behind Home the run makes none (Home has its own https). Without tailscale, when not connected, when HTTPS certificates are not enabled on the tailnet, when the next port is taken, or when serve is refused (e.g. it needs `sudo tailscale set --operator=$USER`), the run log says `run page: http only, <why>`. So `web_port`'s next port is used by default; another project's `web_port` should not be that port. A Tailnet address is offered only while `tailscale status --json` says BackendState Running; otherwise the plain http links are given, with no error, and the saved rule is left alone.

The run's printed addresses (the run log and `agent-runner status`) end with a localhost link, `http://localhost:<port>/?t=…`, for this machine's own browser, whenever the run page listens on every interface. It keeps its token even where a network is trusted, since loopback is never trusted, and localhost is a secure context, so Talk's mic works there without https. Behind Runner Home it is Home's link, `http://localhost:<Home's port>/p/<project>/?t=…`, and the 127.0.0.1 port only Home opens is never linked. Other addresses stay ahead of it, so with Tailscale connected the https one is still first; the launcher's `w` and the page-only process open the localhost link here, `c` still copies the ordinary link for other devices, and with no browser here the ordinary link is named instead.

- **Talk.** The first view in the sidebar, for running the run hands-free: tap the mic, speak, and the
  reply is read aloud (the browser's own speech recognition; the reading is run speech when an engine is installed, else the browser's own). The speaker button left of the
  mic turns reading aloud on and off; while a reply is read it is the stop (stop icon, "Stop speaking"), and a tap ends that
  reading, while replies still waiting keep their play buttons. The mic button keeps its mic icon and is never a stop: a press
  on it while a reply is read cuts the sound at once and listens in that same press (Tap and Hold), and a reply cut that way
  does not start again by itself. The line over the mic says "Speaking…" while a reply is read, and the typing mode's box row
  shows the same stop. The keyboard button swaps the mic for the
  message box; coming to Talk from another view, chat or project, or back to its tab after a minute or more, shows the mic again, unsent words stay the box's draft, and the mic or box is kept per browser tab; where the mic cannot be used the box stays. Each reply has a play button. Leaving Talk for another view, chat or project stops the reply being read aloud (run speech or the browser's own voice, also one started with a play button): the rest of it and the replies waiting to be read are not read, then or on coming back, and a reply that lands while Talk is left is not read either; each keeps its play button. A sheet or the drawer over Talk, or the page hidden, is not leaving Talk, and a person back before any of the reply lands hears it. The gear opens Talk settings, kept per
  browser: read replies aloud, the voice (Kokoro af_heart by default; every Kokoro voice, Piper or the device's own), tap or hold to talk, and auto listen (listen
  again once a reply was read, until one silent turn). Hold listens while the mic is pressed and sends on release, on every device: silence does not end it, only the release or a real failure (the mic refused, no mic) does. With the browser's recognition it is one continuous recognizer (rec.continuous) that stays through pauses until the release; if it ends by itself while held it is started again, the talk line says "The mic is off, wait until it is on again" until the mic is on, and after 3 s with no speech begun "Nothing is heard. Let go and press again" (with ", these words are kept" when words came before); text repeated, dropped or begun anew in one Hold is joined once, and a hold the system takes (touchcancel) stops after 5 s with no new words. If the mic restarted after words and nothing more was heard by a release a second or more later, or the restart failed, those words are not sent: the talk line keeps them with Send as it is, and the next listen goes on from them. Tap does not send at a short pause: the mic listens on and sends when 2 seconds bring no more words, while a tap sends at once; words are kept in Tap too when the restart failed, or speech began and no words came. A typed message leaves kept words; New Talk chat drops them. Talk has its own control session, titled Talk and reused while it is live, told to answer in short
  spoken sentences with no task IDs, paths, commands, links or markdown. New Talk chat (top bar) stays in Talk, stops listening, reading aloud or waiting for a reply, clears the shown conversation, and the next message opens a fresh Talk session; this also holds after a reload in that browser. The mic needs Chrome, Edge or Safari
  on https or localhost (a plain http LAN address gets no mic); without one it says so and the box still works. An abort before any words is retried once by itself; if it fails again, Talk's status line says what to try. While the mic starts, its line says "Starting the mic…" until sound is really captured, then "Listening…". A listen that heard no words, or a reply whose sound went wrong, shows "Copy mic report" (Talk settings has it too): the events from press to end with their times and what happened to the sound, no words, to copy and send (shown on screen to copy by hand where the clipboard is refused). Talk settings' Mic test… sheet runs four mic tries, one press each (about 5 seconds once the mic is on), with an Earbuds choice (Not said, Off, On; picked before the first try) and no message sent: words with the sound setting left as it is, words with it set to play and record, words right after a silent sound, and sound level only with no recognizer. Copy mic test copies a report of the tries so far (the last 12: times, letter counts, sound levels, the earbuds choice, never words or device names). A try is refused while a reply is read or the mic is in use, and ends when the sheet closes or the page hides. The mic report also starts with what the page did before the press: time since load, sounds started (clips, the browser's own voice, silent), and listens with and without words. The mic report also names the open page (the fingerprint of the page as loaded, 12 hex digits) beside the run's version, and says whether it is the same as the page the run serves now, or not (with that one's fingerprint: not reloaded since it changed). Each try's line says continuous or not continuous. A listen that sent words is in the report too, with a line saying what ended it. Errors in toasts are plain words, never "Load failed". A reload keeps Talk's own chat, per project and per browser tab (a new tab takes the browser's last one), and never starts the mic or reads an old reply aloud. Its words show you and the replies, no tool steps, and follow the newest unless you scrolled up; there is no jump button.
- **Run speech.** Talk's replies are made into sound on the run's own machine by an engine installed there, and the run
  app plays the clips; nothing leaves the machine. Install one with `agent-runner speech install [kokoro|piper]` (a
  person can also ask a chat to install it). Kokoro, the default and the natural voice, is 354 MB of files plus about
  200 MB of Python packages. Piper (en_US-lessac-medium) is the light one, 63 MB. Both need uv, or Python 3.10 to 3.13
  to make their own Python. Piper's package is GPL-3.0; it is installed separately and not shipped. The folder is one
  per machine: $AGENT_RUNNER_SPEECH, else $XDG_DATA_HOME/agent-runner/speech or ~/.local/share/agent-runner/speech (on
  Windows %LOCALAPPDATA%\agent-runner\speech). It holds the engines' packages (venv) and their voice files. The worker
  that makes the clips ends after 10 idle minutes and starts again on the next one. Sound plays after a tap on the
  speaker, a play button, Send or the mic (its press, Hold's release, Tap's second tap) has let the browser play it; if
  the browser blocks it, the talk line says to tap the speaker, and the reply is held for that tap. While the mic listens or is held, no reply sound starts; a reply that lands
  then plays by itself once the mic has ended (words sent or nothing heard) if read-aloud is on, several in order, and one that
  lands while another is read waits for it. iOS can skip a sound's end event, so once a second while a reply is read the page
  checks that sound is really playing (run speech, the browser's voice, and again when the page is shown) and clears the
  speaking state when it is not: the browser's voice quiet for 2 checks (4 if it never began) or with no start in 10 s, or a clip paused or not moving for 10 s; the next waiting reply is then read. A reply is read in few clips: its first sentence alone, then about 200 letters, then 400 each. While a reply is read, a second element plays silence so a Bluetooth route stays open between clips; the audio session is play-and-record for the mic and playback once it ended (browsers with navigator.audioSession, iOS). A pause nobody asked for (a call, a route change) is undone once per reply, unless a mic listens; a second one ends the reply, and the lock screen's or the earbuds' pause stops it. A clip request with no answer is tried again twice (after 0.5 s and 2 s; once when none came in 25 s); what was fetched plays on, then the phone's voice reads the rest of that reply, so it is heard to its end, and a toast says "No connection to the run; reading with the phone's voice" (the next reply tries run speech again). An engine's own failure is not retried. With no engine installed, or when one fails, the browser's own speech reads.
- **Recorded.** Talk settings has Speech to words: The browser's recognition (default) or Recorded, kept per browser. With Recorded the page records (getUserMedia and an AudioWorklet), posts the clip as WAV and sends the words, with the same Tap, Hold and auto listen: a 2 s pause after words ends a Tap or auto listen, 8 s of nobody speaking ends it with no clip posted, and Hold only ends when let go. A recording one second short of the run's limit goes out by itself, and a toast says so. The post is retried once on no connection and waits 50 s for an answer; failures are said. With no engine, no secure page (https or localhost), no recording support or a refused mic, Talk settings says why and the browser's recognition is used; a refusal stands until a reload or the setting is picked again. The mic is asked for once and the stream is kept (the open mic). It is not listened to until the mic is pressed: with no listen on every piece of sound is dropped at once, so a clip has none from before its press; only a mic held again while the last words are made keeps the sound of that hold. At rest the talk line says `Tap to talk, the mic is open, not listening`. The stream is released when Talk is left or hidden, for the Mic test, and for the browser's recognizer (dictation). On Safari the settings say how to allow it for good. The run's side: `POST /recorded?t=TOKEN` takes a
  16 kHz mono 16-bit WAV clip (at most 120 s) and answers `{"ok": true, "words": ...}`, with `""` when nobody spoke.
  `GET /recorded?t=TOKEN` says `{"ok", "engine", "why", "model", "seconds"}`, so the page can fall back to the browser's
  own recognition when `engine` is false. A clip refused for its size or format answers 400 or 413; no engine, no model
  or a busy engine answers 503 with `ok` false and the why in `out`. Like every request it needs the page's token. The
  engine is whisper.cpp and optional: `agent-runner speech install whisper` builds whisper.cpp v1.9.6 (it needs git,
  cmake and a C++ compiler; a `whisper-cli` already on PATH is used instead) into the speech folder's `whisper/`. It
  takes `large-v3-turbo-q5_0` (574 MB) where whisper-cli really uses a GPU (the Vulkan build needs the Vulkan and SPIR-V
  headers and glslc; rerun install after adding them), else `base.en` (148 MB), which is always fetched. Each clip is
  read with a prompt of the open task ids, the project's name and its glossary's terms, one clip at a time and 45 s at
  most. The clip is a private temporary file, deleted once read and also on failure; its words are never logged or kept,
  and nothing leaves the machine.
- **Sidebar.** All projects (through Runner Home), Talk, Home (with the Needs you count), Status, Plan, History, Concepts, Tools and Settings. On the example project only, a Walkthrough row brings back the walkthrough of seven cards that point at a run's parts. Chats are the
  control sessions: a dot marks one that needs your reply (an open question, or it spoke after you last opened it),
  and one that needs none with nothing said for `[ui] chat_quiet` is gray at the bottom under Quiet (a pinned or a renamed one is left alone by the run; by hand any chat can go Quiet or be deleted). Opening a quiet chat does not move it; it comes up again only when something new is said in it, or it is pinned or renamed. A sent response (F425a) is a dim row in Quiet with "new" until it is opened once; opening it shows what was answered and starts no session, and words sent there start a control session and replace the row (F425b). A Yes with words that closes its task keeps one only when its chat cannot start (F452). The Chats list (the top and Quiet) runs newest to oldest by last activity, after the pins: pinned chats stay on top in their own order and are the only ones that drag to reorder (mouse at once, touch after a hold). A chat still starting shows first under the pins and keeps that place when it comes up. No row moves while one is pressed (15 s at most), dragged or renamed. Double-click a chat's name (on a phone: its ⋯ in the row, then Rename) to rename it; the name is yours, so the
  run neither closes that chat when idle nor renames it. Agents working are the slots on a task. On a phone the
  sidebar is a drawer: swipe right anywhere to open it, left to close it, and its button has a dot while Home or
  Concepts has a count. On touch, pulling down past the top of the main view or the sidebar refreshes the page, as on a normal site, since the locked document leaves the browser's own pull-to-refresh nothing to fire and an installed Home Screen app has none: a spinner follows the finger with resistance, is ready past 70px, and letting go does what the Refresh button does (typed text is kept; held during recording, an upload or a typed secret), and it springs back if the pull is held, short or cancelled; it is not over a sheet, popup or concept, in a text box, or in a chat's session, which keeps its own scroll, and the mouse and wheel are unchanged. A reload opens what was open: the view (Home, Talk, Status, Plan, History, Concepts, Tools, Settings or All
  projects) and the open chat or slot, kept per project and per browser tab. A chat with no transcript that the run no
  longer lists, or a view that is not there, opens Home. A link may name a view or a chat (`#plan`, `#c3` or `#s1` at
  the end of the address); it wins over what was kept, and the # then leaves the address. When storage is blocked the
  page opens on Home.
- **Title switcher.** A chat's title in the top bar, with a down chevron, opens the chats in the sidebar's order, each with its
  last line, a dot when it needs your reply and a check on the open one; Rename this chat is at its foot. A tap on the title
  opens it and no longer renames.
- **State.** Every page's top bar has the run's state: Running, Paused, Stopping, Caps forced or Not up. A tap on it
  opens Status.
- **New version.** When the run serves another page than the open one (the snapshot's `page` is the page's fingerprint, `PAGE_PRINT`), the page, the project pages and Home alike, reloads by itself (`selfReload()`, F207) once nothing would be lost or cut off: no finger or pointer down, no scroll or animation under way, no sheet, popup or selection open, nothing read aloud, no text box in focus, no message in the outbox, and nothing Refresh would wait for. It comes back to the same view, chat and scroll place, with no toast, and it reloads by itself once per page fingerprint in a tab, so it never loops; a hidden tab reloads as it is shown again. Until then a popup (`newsDraw()`) says "A new version of this page is ready" with Refresh and Later; Later holds for that page in this tab, and it does not reload by itself. Refresh keeps drafts, the outbox, setting fields, attachments and the concept box, and waits, saying why, while the mic listens, an attachment uploads, a device form is open or the browser cannot keep what is written. When a person must restart the run on newer code (`restart_needed`: `[run] auto_upgrade` off, a breaking version, Windows), the popup says "A new version is ready. Restart the run to use it." with Restart the run (asks first) and Later; on Windows there is no control, so stop the run and start it again. A run from a source checkout (a clone with `.git` beside `agent_runner/`) with `[run] auto_upgrade` on restarts itself as soon as main's `agent_runner` tree differs from the one it started on, at the first tick with no merge under way and no `on_exit` running. While that restart is due, no new merge starts (see Stopping a run below). It keeps its slots and adopts its sessions. It does not while the checkout is on another branch than main or master, or has uncommitted edits to `agent_runner`; never for a breaking version, never on Windows, and not while stopping.
- **Status.** One scroll of four sections: Run (the Run card: state, notices and the everyday controls; slots change there), Working (a row per slot, idle ones too), Merging (the tasks that merge now, also after their slot went on) and Usage. Landed lately, releases, the run log with its Since chips and the + Slot button are not on it (History has the landed tasks and the log, Plan the releases). Each agent row opens in place, one open row per list (`S.taskOpen.working`, `.merging`; the options are in STYLE.md's Agent row). The Run card has the everyday controls (slots,
  pause, stop); More… opens a sheet of every run control shown now, each with its icon on the left and its key in
  `agent-runner ui` on the right (B763b): Stop (stop or take the stop back, stop now, suspend, shut down), Run (slot +1
  and -1, set slots, pause or go on, force, upgrade, restart; Start the run while none is up) and, while there is something to fix, Fix up (resume a cut-off task,
  release stale claims, the main-checkout edits a merge moved aside). Stop now, suspend, shut down, upgrade, restart
  and dropping edits ask first, in place; in `agent-runner ui` the key is pressed twice. Restart (`key restart`)
  re-execs the run between merges so that it reads the settings that apply on the next run again; its tasks keep going.
  The snapshot (`ui_model.snapshot`) says which controls show: `shown` (from `ui_model.controls_shown`; with no run up only
  Start the run and Fix up, Force and Caps back on by run state, Fix up only with something to fix) and `card` (the Run
  card's everyday keys). Each session row has `task_controls` (`ui_model.task_controls_on`, off while merging or in a
  control session). The TUI's control rows are `ui_model.CONTROL_ROWS`.
- **Settings.** The run app's Settings page: about 24 everyday settings in Speed and limits, Landing work, Models and Chats, each with its control on its row. The rest sit behind Advanced, and commands, paths, patterns and rules behind Project file, under Project only, each edited on its row too (F448b): a list or table is a text box as wide as the row, one item per line; a risky key says what a change does once changed, and a key that cannot change now (F448a's checks) shows its value and the reason instead of a control. Every open row has More… and "Ask a chat to change it". Each setting has a home: this device saves to `runner.local.toml`, or everyone saves to `runner.toml`, when Save is pressed. The changes for everyone are committed alone on the shared branch and pushed as a plan edit is; it never queues a task. It waits up to 60 s for a merge landing in the main checkout (not one still in its test gate). Saves that come together are one commit. Nothing is changed, and it says so, when runner.toml has uncommitted edits, another branch is out in the main checkout, or a merge or rebase is under way there. A failed push says `saved here, not pushed: why`. With `[run] approve` it is pushed with the next approved change. A runner.toml that git ignores, or one outside the repo (`AGENT_RUNNER_CONFIG`), is written without a commit; with no runner.toml, one is made. Changes do not save as they are made: each changed row says "Not saved yet", and the Settings bar at the foot of the page says "N changes not saved" with Undo (drops them) and Save (writes them all). After a Save it says "N changes saved" with Undo (puts the earlier values back, unset ones included; one changed since by something else is left and said) and a close x. Unsaved changes are kept per browser when the page is left or reloaded. Typed text counts as it is typed. When this device's runner.local.toml overrides the key, the row says "This device overrides everyone's (value)" and the run is not told. The other home is in the row's More…. A value set on this device wins and is what the row edits. Changed lists what differs from its default, with Reset, and the lines the run ignores or moved. Dependent rows show with their parent (`approve_wait` and `approve_batch` with `approve` on). Release by itself has two controls on a line under its description: Every (Off, 5, 10, 20 tasks; a count of your own already set is kept and shown) and When idle (a switch). Changing one keeps the other, and both off writes `false`. Audit by itself has an On switch, and while it is on, Every (25, 50, 100 tasks; a count of your own is kept and shown; `true` shows as 50); off writes `false`. Search finds names, descriptions and code names. Find a setting is cleared when Settings is left for 5 minutes or more (another view, a thread, or the page hidden; the time away goes on over a Refresh of the page), and a shorter trip keeps it; the Changed filter and unsaved words in other fields stay (F204b). A "N changes wait for a restart" card counts only the settings that apply on the next run (`[run] web`, `web_port`, `web_https`, `home`, `notes`; `[plan] dir`, `repo`; `[git] master_branch`, `no_push`, `pr`) and has Restart the run; the others apply now. `agent-runner settings` still prints the developer notes. The words the page shows are in `agent_runner/setting_words.py`. Under Advanced > This machine, Claude Code program (`[run] agent`) is a picker of the Claude Code programs found on this machine (PATH, then ~/.local/bin, ~/.claude/local, /opt/homebrew/bin, /usr/local/bin; a link to the same file is listed once), each with its name, version and path, and a pick waits in the Settings bar until Save. A kept value that is wrong stays listed, marked not found, with the reason; Other path… takes a wrapper, checked by the save as before (a wrapper is not started to ask its version). Below it, Providers lists claude, copilot, codex, gemini, ollama and those in `[models.providers]`, each with its login (logged in and where it is kept, or the `run login` command; claude's own login is not checked; never a secret) and a Log in or Log in again button (claude's opens the existing Log in again sheet; ollama and local ones have none), and says Provider in Models picks one for every model, and a model set as provider:model keeps its own; "Show the model settings" lists those settings. In Landing work, Working branch (`[git] master_branch`, the branch finished work is applied to and tasks start from) is a pick of the local branches, with Found by itself (the branch it finds) first; a pick that cannot be saved says why under it, a changed pick says what Save does and that it applies once the run restarts (F447a).
- **Home.** The person's view, in this order: a greeting; Talk, one full-width accent button (at least 56px) that opens Talk in the page without a reload and never starts the mic; the message box, with no dictation button (open chats and new chat views keep theirs; F196f: what it sends starts a new chat the way + does: `new_control` through the outbox without waiting, one stand-in opened in place that reads Starting the chat…, and the answer's name turns that row into the chat's own); a ttyd notice when there is one; shortcut chips: Last chat (the chat with the newest activity, pinned or not; absent with no chat), Add a task, Pause or Go on (the one that fits; none with no run up; while being sent it shows busy, with its outbox stand-in under the chips) and Since my last look; then
  Needs you (B832: first, each live chat whose last answer ends on a DECIDE line, at once, before the run files it:
  its question, the chat's name and how long ago, its option buttons (none for a question without a bracket), an answer box
  and Chat, which opens the chat; an option waits 5 s with Undo and goes to the chat as its question card sends it, typed
  words go as a message; the row goes once answered or the chat moves on, a message about the question keeps it, and once
  the run files it only the filed item shows. Counted in Home's count; snapshot `chat_needs`, read from the transcript read
  each chat's row makes. Nothing is written to the plan. Then each item is one short card: what is wanted and where, in everyday words, its title, at most two lines of
  what to do, and Press for details; a DECIDE's heading is its question, its task's title small under it, then its
  background: two lines on the card, whole paragraphs in the sheet and `agent-runner ui`; its answer buttons sit below
  it, Later to shelve it, Chat to open a new chat that shows the
  question and its answers, Drop to drop the task after a confirm). Pressing the card's words opens a popup with the whole ask: what to
  do as numbered steps, what you should see, notes, pictures, a link to its page, Why it waits, the agent's last words (`GET /why/ID`, shown only when the agent left a session with words of its own), and the
  full task (`GET /task/ID`, always shown for a task item), and at the foot a one-line reply box with the answer buttons (an item with inputs has their fields and Done instead). The reply's words go with the answer
  (Yes is `plan confirm ID "Yes: words"`, No is `plan change ID "No: words"`, a concept option likewise; a pick sheet's go or
  picks is `sheet ID … --note "words"`, Not this on a PITCH is `pitch no ID --why "words"`, and the words beside its Approve go
  to a new chat once it is approved; if that chat cannot start, the toast and the run log say them). A Yes with words on a CONFIRM that closes its task also starts a new control session with them (F452): its first message names the item, its question, the answer and the note, and says the task is closed and the note is to be acted on; it lists at the top of Chats like any new chat and keeps no sent response. The answer is settled first and never fails because of the chat; its result waits at most 3 s to hear whether the chat started (toast "B2 ticked. Your note opened a chat", or "... A chat with your note is starting" when not yet known), and a chat that cannot start keeps the sent response (Quiet in Chats; also when it fails later than 3 s), with the toast and the run log saying so. Yes with no words, and answers that reopen or resume a task (its agent gets the note), are unchanged. An item with no
  answer buttons, and a DECIDE, STUCK or PITCH, has a Reply button. A DECIDE's words are its answer and run at once with no session (`plan confirm ID "<words>"`; on an item with a pick sheet, `go` or `recommended` is `sheet ID --go` and a pasted `ID picks: ...` line is `sheet ID --picks`), and Chat stays for asking about a DECIDE. A STUCK's or PITCH's words go to a new chat, as does a typed reply to any other label. The popup is a sheet on
  a phone and a centred dialog from 760px wide, and closes when the item is answered or leaves Needs you. It takes keyboard focus when it opens, and Esc gives focus back to the card, also when the card was redrawn meanwhile. Each item's answers come from `ui_model.need_answers` (in each snapshot needs row as `answers`): Yes and No on a
  CONFIRM or a yes/no ask, a concept's options (A/B/C when its copy has none), a pitch's options, a DECIDE's options, a pick sheet's recommended picks (and its answers, when it has exactly one question), and Done on a BLOCKED item,
  on both pages; `agent-runner ui` draws the same, adding only the key letters, and `need_chat_text` uses them too. Each answer is a `need_yes`, `need_no` or `need_answerN` entry of RUN_CONTROLS (at most `ANSWER_MAX`, 12, drawn per item); which one a row's button is comes from `ui_model.answer_of` over its answers. A TOOL or PR row has no answers.
  An answer button runs the plan command itself, with no AI session (except a Yes with words that closes its task, which also starts a control session, above): Yes on a CONFIRM or a picked
  answer runs `plan confirm ID "<reply>"`, No on a CONFIRM runs `plan change ID "No: the check failed"` (which reopens it), and a pick sheet's go runs `sheet ID --go` and its answer buttons run `sheet ID --picks "ID picks: q=b"`. The button shows it is working, a toast says what was done (e.g. "R13 ticked") and the item leaves Needs you at once; on a failure the toast says why and the item stays. Words typed in a reply open a new control session with them (`control --new --ask`, named for the ask), except a DECIDE's, which are its answer as above. `agent-runner ui`'s answer tab does the same. Then one card of two one-line rows (44px high, with an ellipsis) that open Status and Plan: the run's state and work, e.g. "2 working, 1 merging" (the state comes first when not Running: "Paused · 1 working", "No run is up", "No agent is working"), and the queue, e.g. "2 left, next release waits for 6" (parked tasks and releases are not counted; "The queue is empty"; nothing about releases with Manage releases off). Agent cards, queue rows, the release card, What needs me and New concept are gone from Home.
- **The session.** A chat or slot shows the real Claude Code session, not a thread the page draws: its own terminal
  through ttyd (`attach NAME` shows the same one), in one frame between the header and the message box. A chat has no
  bubbles or folded steps. A drag or a wheel up over it scrolls its history (`GET /history/NAME`, drawn over the live
  screen), and its jump button (Jump to bottom) glides back to the live session. The frame is served at `/t/TOKEN/NAME/` on the run's own address, so
  https and Runner Home both work. ttyd listens on 127.0.0.1 only, on a free port of its own. The frame is made the first time a session is opened and kept
loaded out of sight after that; only the open chat is connected, and its ttyd socket never closes, so ttyd's own Reconnect
words never show. `/terminal/NAME` says
  whether there is a session to show, and if not, why. On a computer you click and type in the session directly; only a
  mouse press in it gives it the keyboard, and ttyd's focus on connect never does. With the mouse, a drag selects words in it and copies them at once (as Shift+drag did, Option+drag on a Mac), Ctrl+C or Cmd+C copies a selection without interrupting, and a right click is not sent to it but opens the browser's menu. A file dropped on it is attached. On
  a phone a touch layer over it scrolls it on a drag (a wheel steps it, and it glides; a drag scrolls the history first,
  while it stands in), a tap clicks in it without
  opening the keyboard, a long press selects the word under the finger, at the live end too (no sheet; where no history can be drawn it does nothing), and the key row's Text opens a sheet with the screen's text to select and
  copy; a horizontal swipe still opens the drawer. The message box's keyboard button folds out the key row (Esc, Tab, ↑,
  Enter, Ctrl-C, Text, ←, ↓, →) for the session's menus; touch only, and while a question card is open only under that card, for that question. The session's text is 12px on touch and 13px
  otherwise, drawn by ttyd's DOM renderer (its canvas is wrong at 2x). The terminal page is gzip-compressed (about 196 KB,
  from 740 KB) and the browser keeps it (an ETag, `private, no-cache`, a 304 when unchanged), never without the token. Its ground is dark unless the person's agent
  `theme` (in `~/.claude/settings.json` or `~/.claude.json`) starts with light. A session the run starts (control sessions and
  slots) takes the run's own theme, `agent-runner`, whose colours each browser fills from the page's light or dark.
  The states are cards: starting (says so, with the waiting message); loading; ended (the claude.ai/code link, and
  Resume where there is one: `resume_chat`, `control N --reopen`); a slot with no session (Resume when its task
  was cut off); no terminal (a headless stream slot, a slot with no socket, or Windows before 1809); no ttyd (TTYD_INSTALL
  says how to install it). The state is checked every 3 s.
  The chat's connection ends when the chat is left, or the page has been hidden for 15 s, so the session gets its other
  viewers' size back; the frame stays loaded out of sight. Each chat's screen is kept as it was last drawn (the last 12 chats,
  in the page's memory, gone on reload): a switch to a kept chat shows it at once, slightly dimmed, under a thin moving line,
  until the terminal has drawn, so there is no blank frame; a chat not seen in this page shows its latest messages from its
  feed in that place. A dropped connection leaves the text in place and dials again by itself (after 250 ms, doubling to
  15 s); after 5 s it says Reconnecting… (Connecting to the session… the first time). An ended chat keeps its last screen,
  with its Resume card above the message box; with nothing kept, the card is in the body. A refresh never moves the page, and never redraws the frame. Stop sends one Ctrl+C while Claude works (`stop_session`); Esc only
  leaves the box, then goes back (B116).
  Its bottom lines (the update notice, status line, mode, background shells and agents) are past the frame's edge, so the
  message box has their controls: a chip row above it (Working, mode, N shells, N agents, Update; a chip shows only when
  there is something to say). Its sheets: Working (Stop), mode (Shift+Tab, one press at a time), shells (what runs, its
  output tail, Stop through `/tasks`), agents (Open through `/tasks`), Update (the command, run on the run's machine: only
  known update commands; Restart chat, `restart_chat`, for an idle c2 and up). The status comes from `/live/NAME` (Claude
  Code's status, mode and background work). Its `queued` counts the messages sent that Claude Code has not taken in yet, read from its queue entries in the transcript (background events are not counted; 0 when idle); `chat_to` with `force` and no text sends one Escape, so Claude Code takes them in as its next turn, and does nothing with nothing queued. The `/` button's commands come from `/commands?s=NAME`: the runner's, Claude
  Code's own, the project's and the person's, and the skills named in that chat's transcript. While Claude works the
  box's send arrow is the plain Send, the same size, with words or an attachment; it sends without force, so Claude Code queues the message. With the box empty and a sent message still queued, the arrow is Force send (`.send.force`, labelled Force send): a press sends what is queued at once, with `chat_to` with `force` and no text (one Escape, so Claude Code takes the queued messages in as its next turn). Only a press on the arrow forces, never Enter in the box; after each send and each force the arrow is disabled for about 1 s while the session works and the box is empty, so a double tap never forces. Stop is the way to interrupt otherwise. `chat_to` with `force` and words (no page control) interrupts with Escape, waits until Claude Code's status is at rest, then sends once. Scrolling up hides the chips,
  box and top bar and leaves a thin strip that says Working; scrolling down, at the end, a tap on the strip or typing
  brings them back.
- **Message box.** On a computer Enter sends and Shift+Enter starts a new line; on a touch phone or tablet Enter starts a new line and only Send (or Ctrl/Cmd+Enter on a hardware keyboard) sends. A composing input method never sends. In the slash menu Return picks the highlighted command, on touch too. Each chat keeps its own draft and unsent attachments. Messages that never landed are listed in the Outbox popup as not delivered, with Retry and Discard. A message to a control session still starting stays pending in the Outbox, which says it waits for the chat to start, until the session takes input; then it is sent, or after 2 minutes fails as not sent. Attachments are uploaded to the run (`POST /upload`), kept under
  `.runner/uploads` (`<notes>/uploads`, git-ignored with the rest of the notes folder), and handed to the
  session as paths on this machine. On a computer, a file dropped on the session is attached the same way.
- **New chat view.** Chat on a plan task, a concept or a setting ("Ask a chat to change it"), Add a task, and New concept open an
  empty chat at once, over the view pressed in, titled with what it is about, its box focused. It says "The chat starts
  with your first message." Nothing is sent until the first message, which starts the session once (`new_control`:
  for a concept, `ui_model.concept_chat_text` (its page link, local copy, guide concepts, build nothing until a plain go) plus the person's words; otherwise the About text, or "Concept: " for New concept). Leaving it unsent leaves no session; its draft is kept per thing. Back or Esc returns to the
  view. A reload reopens it without focus, and it has no session keys or interrupt.
- **Plan.** The queue in plain words (a row folds open to `plan ID`'s text, with Chat), a Parked group (the parked tasks, then the shelved ones with Bring back and Drop; shown when there is either), and Add a task. A Find a task field at its top (Plan search, `GET /plan-search?q=WORDS`, read-only) finds tasks by words or task id over open, parked and done tasks, in any case and order; all words must match, and with text in it the matches replace the groups, best first, until the x clears it. Tasks are not
  edited here directly: ask in a chat. A task that waits for a shared tool reads `waits for iPhone 15, held by F389, 12 min` on its row (### Shared tools). With no run up, a queued task that nothing else keeps reads `Waits for the run to start` on its row (`goes first` when critical). A task no slot runs but which is under way reads `Taken by the chat <name>` (a button that opens that chat), `Taken by a chat that has ended`, `Taken by hand`, `Merging` or `Waits to resume` on its row; the record is `taken-by.json` in the take worktree's git folder (agent_runner/taken_by.py), removed with the worktree, and a chat counts as the same one after /clear and after a reopen, but a later chat with the same number is not it. Tasks taken before this version, from a terminal or by a slot's agent, read `Taken by hand`. A queue row's three dots open its menu: hold, to the top, and remove with Undo.
- **History.** The NAV row's History (`#history`, right after Plan): one scroll with a sticky Find in history field (`.planq`). Typing filters the page's own rows at once (id and title, and run log lines) and asks `plan-search` for done tasks older than those: one the event log says landed is under Landed or Releases with its time (`at`, `release` on the hit), any other under Done with no time. Landed: up to the newest 60 `lately` rows that are landings, a task once with its newest landing, "part landed" said for a part. Releases: the past ones, newest 20 (`past_releases`); with Manage releases off the section goes and a release landing is an ordinary landed row. Run log: newest first, with the Since my last look and Since yesterday chips. A Landed or Releases row opens in place (one per list) to when it landed and its whole text, then What changed (starts a new chat at once that reads the task's commits), Report a problem (a new chat view whose first message names the landed task and asks for the cause and a bug task) and Chat last. Older links (`#status`, `#agents`, `#activity`) open what they did.
- **Concepts.** Each concept with a button per option (taken from its page's headings, by `ui_model.concept_options`; `ui_model.concept_page` builds the page), plus Chat and View, with no New chat button (the TUI's N still starts one at once). A concept's page itself has no answer buttons: the guide and the K brief (`brief.CONCEPT_PROMPT`) no longer have an agent run `pick-links` (the Claude app's buttons did not work; the command is gone, and an old concept link on a published page answers with a short page saying to pick in Concepts, changing nothing; /pick still answers a pick sheet's Send, also through Runner Home); the person picks here, in Needs you, or in the chat. The New concept button (also on Home, beside Add a task) opens an empty New chat view for a new concept.

How the app looks, moves and speaks is in [STYLE.md](STYLE.md); a change to it follows those rules.

The app does not open slots in the Claude apps; `agent-runner ui` still does (see `[run] remote_slots` above).

`agent-runner ui` (the terminal UI) has no chat of its own: nothing is typed into a session from it, and Ctrl+C
always quits. Selecting a session row (cN or sN) shows the real Claude Code session. A pane split
off beside the UI runs `agent-runner attach cN` (respawned when another session row is selected, killed when
another row or the UI quits); l, Enter or Ctrl-l moves focus into it, and Ctrl-h comes back. A session with no
terminal socket says so with its link (o open, y copy; Enter opens the link). One whose session pane closed itself
(Ctrl-b d there) says so, and Enter (⏎ show it beside) shows it again. `agent-runner ui` always runs inside tmux: started
outside it, it re-execs itself in the project's tmux session (named for the folder, or a new window in it); without
tmux, or on Windows, it refuses with exit 2 (the install line, or the run page's link). Ctrl-f makes the session
full-screen between the UI's top and bottom bars, and again for side by side. In Sessions, n starts a new control session without waiting for its link; `c` (anywhere) starts a new chat, and `d` closes any control session. In the example project the walkthrough shows here too: the same seven steps as the page, worded for keys, with `<` back, `>` next and `/` to skip it and show it again; where you are is kept in the project's `.runner/walk.json`, and a step focuses and marks its panel.
- **Tools.** The devices and shared tools: add, edit or remove a device, Used here per project, Test connection, and
  its secrets (### Devices). The shared tools of runner.toml show here too, and are edited there; one with a `page` has its web page's card (### Shared tools).

### Adding a row action

`ui_model.RUN_CONTROLS` is the one list of actions for the TUI and the run page. Besides the run and slot-task controls it holds a Queue row's actions (`where: 'queue'`: `queue_priority`, `queue_unpark`, `queue_take`, `queue_drop`), the release tab's (`where: 'release'`: `release_wait`, `release_now`), a Needs you item's (`where: 'need'`: its fixed answers `need_yes`, `need_no`, `need_answer1` to `need_answer12`, and `need_later`, `need_chat`, `need_drop`, its confirm asked in both TUI and page), a concept's (`where: 'concept'`: `concept_chat`, which only the TUI's N runs, since the page's Chat opens the new chat view, and `concept_drop`), a shelved task's (`where: 'shelved'`: `shelved_back`, `shelved_drop`), and a control session's (`where: 'session'`: `session_close`, TUI only).

An entry has `key`, `label`, `tui` (the TUI key), `tui_also` (a second key that works while the panel, not the main pane, has focus; `tui_main` False means the key works only then), `where` (the panel), `argv` (the runner command: `{id}` the row's task, `{why}`, `{pri}` the next level after the task's (normal, critical, high, then normal again; low goes to critical), `{n}`), `ask` (starts a new control session with that message) or `fn` (a `ui_model.ROW_FNS` function run with the row's id: `need_chat`, `concept_chat`, `session_close`; `chat: true` opens a new chat), `fits` (a function of the row: the rows it is allowed on), `confirm` (the question the page asks first; the TUI asks too unless `tui_sure` is False), `confirm_of` (a function of the row giving that row's own confirm question, '' for none, which then replaces `confirm`; the snapshot row carries them as `asks`, `ui_model.row_asks`, and the TUI and the page both ask it, as `queue_drop` does per release), `why` (the default reason for a drop) and `help` (the keys-list wording, if not the label; '' keeps it out of the keys list), with `help_keys` (the keys the list shows for it). While a release is open, `ui_model.controls` fills `confirm` and `seen` on the `where: 'release'` entries: `seen` is the ids the question names, which `run_control` takes as `text` on the Yes, so a Yes asks again if other releases are open by then. An answer entry also has `answer` (`run_control` runs `ui_model.answer` with its label), `label_of` (a function of the row giving that label; the snapshot row carries them all as `labels`, `ui_model.row_labels`) and `tab` (its TUI key works only in that main-pane tab: `answer`). `run_control` takes `text` (the label pressed) and `note` (the words beside it); when `text` is no longer the row's answer under that key, it is refused with "answers changed: look again". TUI keys are y, n and a to g, and answers past the seventh have none. The page draws them with `ansBtns` and `restBtns`, so a pitch draws Approve alone and Not this… holds the rest. The old `data-ans` handler and the TUI answer branches are gone; `/act` `answer` stays for typed replies and the concepts' option buttons.

Each snapshot row of queue, needs, concepts, shelved and sessions has `acts`, the keys allowed on it now (`ui_model.row_acts`); the snapshot has `shelved` (`ui_model.shelved_rows`, apart from `queue`), `controls` (the list as data) and `release_acts`. `run_control` re-checks the row (`ui_model.row_of`) before it runs.
The snapshot's `lately` rows have `id`, `kind` (`landed`, `part` or empty) and `title` for those two; up to 60 rows. `past_releases` lists the past releases for History, newest 20. The snapshot's `kinds` is the kind table (`theme.kind_table`): each id letter with its `word` and `color` (F195b), which the page's kind chips read.

The TUI takes its hint keys, buttons, panel key branches and the Queue lines of the keys list (`tui.action_help`) from the list. The page draws the needs and concepts buttons from `acts` (`actBtns`, `actSure`) and sends them through the one `data-ctl` click handler (`controlReq`), with the confirm asked in place; the old per-button actions `need_drop`, `shelve` and `take` and the TUI `dropping` state are gone. So a new row action is one entry in RUN_CONTROLS and nothing in `tui.py` or `web_page.html`. Open (a link), pitch Approve / Not this, the typed boxes, chat edit, direct edit and reorder (J/K) are still hand-written.

The test: `tests/test_ui_model_controls.py` `test_row_actions` goes over the list (every entry has an action, and no two share a TUI key on a panel); the TUI and web tests run and draw them.

`ui_model.unpark` and `ui_model.release` (and their `/act` names) are gone: use `run_control` with `queue_unpark`, `release_wait` or `release_now`.

### status and since

`agent-runner status` names each task by its kind's word and id, then a short title: the first sentence of its line
cut to about 60 characters, without its fields, quotes, dates or file lists (F195b): `s1  feature F5 Control session experience  12 min`.
Its slot, merging and lately lines use the same form, as in `10:02 landed: bug B215 Run page chats`. The words
come from the one kind table (`theme.KINDS`); a project's own `[plan] kinds` name gets its meaning's first word and
gray, and the same word under another letter keeps its colour. `agent-runner since` and `--follow` are unchanged: the
id stays in brackets last.

`agent-runner since [WHEN]` lists what happened, oldest first, one line each: started, landed, part landed
with the rest stuck (`done --blocked`), stuck and not merged (parked on `wip/`), needs you (left for a human,
or the run held by a stoppage only you can clear), looks stuck (stalled), a session whose context peaked past
`[run] context_warn` (`B32 peaked 168k (over 150k): runner.py 61k, test_runner.py 22k`), run idle, run stopped. With no
WHEN it starts where the last `since` left off (`.runner/since.last`; a day back the first time) and moves
that mark forward, so asking twice in a row shows nothing new the second time. WHEN is `2h`, `30m`, `1d`,
`today`, `yesterday` or a date/time (`2026-11-19T14:00`); it moves the mark too, never back.

By default `since` prints that as a digest, short enough for a phone (B88): a headline count, then one line per
task with its last state under Started, Landed (newest first) and Stuck, then the run's own lines (releases, a
hold, its last state); repeated run idle / run stopped lines and restarts fold away. Past 10 task lines, Landed
names the rest by id only and the digest ends `more: ask for the full list` (B89: an ask, not a command,
since the person may be on a phone). In a control session, /since always runs `since --all` and hands the whole
list over as a private page, with its link and a one-line gist; `status` stays the short summary. `since --all` prints every event, one line each, as above.

`since --follow` stays running and prints one line per new event as run.log gets it (a landed task with the
first sentence of its `done` message), from now on, moving the mark as it prints: the control session's
"follow", and fine in any terminal. `since --follow --needs-you` prints only what needs you (the run held,
with what holds it; left for a human; looks stuck; `needs you:` a task or concept that landed or blocked
asking for your answer, in plain words with the link), skips landed, started and idle, and leaves
the mark where it is: it is the watch every control session keeps.

Both print **Needs you** first when a concept's build or a task waits for you (below), however old: per item
one line in everyday words, what is asked and what to reply, its age first and its [id] last, then its link
on a line of its own, oldest first:

    iFizBox needs you:
       2h  Pick an option for settings page layout - reply A/B/C [K7]
        https://claude.ai/code/artifact/…
      35m  Check the push reached your phone - reply yes/no [F1]

Every Needs you line names its project (the main checkout's folder), so a person who runs several knows which
control session to answer in: the heading reads `iFizBox needs you:`, a `--needs-you` line `iFizBox needs you: … [R43]` or `iFizBox: looks stuck: …`, and
the desktop notice of a held run `iFizBox needs you: run stopped: …`.

**Claude Code changes.** A few things agent-runner reads are Claude Code's internals, not a documented
interface: its session transcripts, the claude.ai/code link a Remote Control session shows in its terminal, and
`remoteDialogSeen` in `~/.claude.json`. When the shape it expects is gone (a live session's transcript has 20
entries and none of type user or assistant; Remote Control on and an open `control --new` session's log shows no link in
90 s; a session came up on Remote Control yet `~/.claude.json` has no `remoteDialogSeen`), the run says so once
per Claude Code version, as a `--needs-you` line: `iFizBox needs you: Claude Code 2.1.400 changed its
transcript entries (…); stall detection, resuming a cut-off session and session stats no longer works`. It is a
local warning only (nothing is filed); `.runner/claude-drift.json` keeps which version each was said for.

The CONCEPT/CONFIRM/DECIDE/BLOCKED labels stay in TODO.md and `plan waiting`; the person does not see them.
The age comes from the `(asked YYYY-MM-DD HH:MM)` stamp `plan block` adds to a block on a person (older
blocks have none and sort first). `[run] needs_order` changes the order:

    [run]
    needs_order = "oldest"  # "newest" first, or "plan": TODO.md's order

### Tasks waiting on a person

A block whose why starts with a caps label waits on a person, not a task: `CONFIRM:` (check something by
hand and say what you saw), `DECIDE:` (answer a question or a choice), `BLOCKED:` (access, a login, or a fix
only a person can make). An agent files one with `done R1 "msg" --blocked "CONFIRM: watch a phone for a push
when a task lands"`; such a block never takes an `(after …)`. It lists under Needs you beside the
concept pages, and takes one of three answers (a control session maps what the person
says to the item's id, a reply that names no item, "yes", "B", "later", included, and asks which one when it
cannot tell):

- `plan confirm R1 "the push came"`: a CONFIRM is ticked with that noted; a DECIDE or BLOCKED reopens with
  the answer noted; a concept is approved.
- `plan change R1 "do X instead"`: noted and reopened (a concept: `revise`).
- `plan shelve R1`: stays blocked (`BLOCKED: shelved: …`) but leaves the list; `plan waiting --all` still
  shows it, and `plan unshelve R1` brings it back. Concepts shelve the same way. The run page's Plan view lists a shelved task under Parked, after the parked ones, with Bring back and Drop (asks first); the TUI's Queue panel shows it last. Display only: the task stays where it is in TODO.md.

Answers stay in their own project: `confirm`, `change` and `shelve` read and change only this project's plan,
never another's. An id only another project has gets `nothing needs you here about 'R43' in <project>`, and is
answered in that project's control session; a project that needs another's state checks it itself.

The card and popup of a Needs you item say what the ask is in short. Optionally, `<notes>/asks/ID.json` gives them
their own words, each field standing in for what the ask's text gives: `summary` (the card's line), `where`, `steps`
(What to do; each a words string, or `{text, link, cmd, on}`: `link` a web address, `cmd` a command for the machine
`on` names, this one when none is named), `expect` (What you should see), `shots` (pictures or videos, each with a `caption`) and
`inputs` (below). A BLOCKED item's steps, links, commands and inputs all go here, and a secret in `<notes>/asks/ID.env`;
an old script left in `<notes>/wizards/ID.sh` shows as text steps in the detail and is never run:

```json
{"summary": "Open the pay page on the phone", "where": "iPhone, Safari", "steps": ["Open the shop", "Tap Pay"],
 "expect": ["A green tick"], "shots": [{"file": "uploads/pay.png", "caption": "The pay button"}]}
```

A DECIDE's answer buttons come from `options`, a list of `{name, rec}` with `rec` true on at most one: 2 to 12 names, unique, at most 80 characters, none starting with `-`. The briefs ask for them: a slot's `run ask` writes `options` in `<notes>/asks/ID.json` and must do so, since a bracket there gives no buttons (the run appends words after the question); the slot and control briefs otherwise ask for a bracket. Without a good `options`, they come from a bracket that ends the question, before any link, with the names separated by ` / `, e.g. `DECIDE: Which look? [Full (recommended) / Small / No change] https://…`. A control session's question is kept whole up to 2000 characters; a longer one is cut before its bracket (and the links after it), so the bracket survives when it is filed under Needs you. One DECIDE per question; several DECIDE lines may end one answer (the /live asks), each filed as its own item and answered one by one. A good bracket is not shown in the question; a malformed one stays in it and gives no buttons, and a malformed `options` falls back to the bracket. Each option is one button, the recommended first and marked "(recommended)". A press sends the bare name at once, with the popup's note; an item with inputs has no option buttons (Done answers it) and keeps its bracket.

A DECIDE is a question, not steps: its heading is the question (the last sentence ending in a question mark, else the ask file's `summary`, else its first sentence), so the question wins over the ask file's `summary` on the card. A `steps` list in the ask file is still shown as steps, and then the rest of its words, the background, is left out.

A missing, broken or over 64 KB file is ignored. Without one, the ask is split by rule (at sentences, numbered steps,
`;`, `then` and colons), with nothing lost and no AI. A `file` is relative to `<notes>/asks`, or `uploads/NAME`, or an
absolute path inside one of those two folders. A picture is png, jpg, gif or webp, and a video is mp4 or webm (same 50 MB limit, content checked against its suffix), served by a token-checked
`GET /shot/uploads/…` or `/shot/asks/…` and never from anywhere else, answering Range requests (206, 416; several ranges or a malformed one get the whole file), which Safari needs; a picture under `<notes>/uploads` that the task's
line names shows too, but only a picture. The TUI's Needs you pane shows the same steps, expected list, picture paths and, under Videos, video paths with their captions.

A control session's filed question also gets `text` in its ask file (the lines kept, cut at 12000 characters), `session` and `project`, written by the run for that question and cleared with the file. `need_detail.detail` returns them, `''` when absent. Its local pictures are copied to `<notes>/asks/ID/explained-N.*` and added to `shots`, allowed types only (png, jpg, gif, webp).

A BLOCKED item split this way also takes its `why`: the statements that say why it stopped, shown as a Why section above What to do (never under What you should see, and left out on the page when the heading already says it). Steps are orders to the person, and `After that: …` notes say what the run or an agent does next; only words after a step's colon that report no failure become What you should see, and nothing is lost. CONFIRM and DECIDE are unchanged, and the TUI's Needs you pane shows the why as `Why: …`.

`inputs` asks the person to enter something. Each is `{key, label, kind, hint, match, confirm, env}`: `kind` is `text`
(500 characters at most), `link` (a web address, 1000 at most) or `secret` (4096 at most), and a secret's `env` is its
NAME, the key in capitals by default. `match` is a regex the whole value must match (200 characters at most), `hint`
says what is wrong when it does not, and `confirm` is a question asked before anything is sent. A value is one line,
every input must be filled, and with a malformed one, or more than 12, the item has none and keeps its plain answers. Only CONFIRM, DECIDE, BLOCKED and
stuck items take inputs. `ui_model.need_give` checks each value and sends nothing when one fails, naming that input.
Text and links go quoted as data in the answer the task reopens with; a CONFIRM with inputs reopens rather than ticks.
The run page sends them with `POST /give` {tid, values, confirm}. Whether it may hold a secret is worked out from the
connection (https, also through Tailscale Serve or Runner Home, or localhost), never from what the page sends: over
plain http text and links are still sent, and an item with a secret is refused. The claude.ai copy has no fields.
A secret goes only to `<notes>/asks/ID.env` as `NAME='value'`, owner-only (on Windows, as its folder is) and kept out of git, and the answer names its
NAME and that path. It is kept while the task is open and removed when it lands or is dropped (a drop keeps it 1 day, see below), and is taken only over
https or from this computer or the terminal UI:

```json
{"steps": [{"text": "Add the Install Switch shortcut", "link": "https://www.icloud.com/shortcuts/example"},
 "Share > Copy iCloud Link"],
 "inputs": [{"key": "link", "label": "iCloud link", "kind": "link", "match": "https://www\\.icloud\\.com/shortcuts/\\S+",
 "hint": "paste the link that Share > Copy iCloud Link gives", "confirm": "Is this the link you copied?"}]}
```

The TUI's Needs you pane (`agent-runner ui`) draws the same. An item with inputs has no plain answers and no reply box:
its steps show the link and the command ("Run on <machine>"), one field per input (a secret as dots) with its hint under
it (and the refusal, in red, when refused), and one Done. Tab and Shift+Tab go over links, commands and fields.
Enter opens the link (here in the browser; over ssh it copies the link and shows it to Cmd-click), copies the command,
or types in the field; Enter inside a field stays in it and never sends. Ctrl+S is Done from anywhere in the
pane: an input's `confirm` question is shown first, and Ctrl+S again sends, while any other key does not. The TUI counts
as this computer, so it takes secrets. A typed secret is kept only in memory: it is forgotten once sent or when another
item is selected, and is never in the drafts a restart hands on (an upgrade restart waits while one is typed).

The file is optional, and the brief asks for it only for length: a CONFIRM, DECIDE or BLOCKED line, and a `run ask`
question, stays one short sentence (about 100 characters at most), and the rest goes in `<notes>/asks/ID.json` with
pictures under `<notes>/asks/ID/`. The line starts with what the person does, in words a person who never saw the task
understands, the reason comes second, and no task id appears without its title. `done --blocked` refuses, before its
gate runs and with nothing blocked, a CONFIRM or BLOCKED over 200 characters with no ask file (an ask file an earlier
block took does not count), and a CONFIRM or BLOCKED that says it waits for an open task or release ("release V5 …", "once F4 lands") with
no `--after`; a wait a check can read goes with `--until`. With neither, it also refuses a BLOCKED that says it reruns,
reopens or waits for a command to exit 0 or pass, or for a tool, device or lock that is held, busy or in use ("rerun when
tools/ui-15.sh state exits 0"): it says to use `run wait-for NAME` or `--until tool:NAME`/`check:NAME`, listing the
project's tools and checks, or, when it has none, to file a task that adds one and block `--after` it. A line that starts
with what a person does (plug in, unlock, sign in) passes. A BLOCKED with `--after` or `--until` asks the person nothing, so
neither refusal applies; a CONFIRM with one can still be too long. A DECIDE over 200 characters with no ask file is not
refused: it says so once, names the file, and blocks. The file and its pictures are removed when the item
is answered (confirm, change, unblock), the task is ticked or dropped (a drop keeps a copy, see below), it blocks again (any block but `done --blocked`
and `run ask`, which may have written it), or a new session starts on the task. A block that waits on a task first and
then returns to the person keeps the file. `plan confirm ID` and `plan change ID` also settle an ask the run has not blocked yet (its block is held, e.g. by a merge): the answer is noted, the item never shows under Needs you, and the session resumes with the answer.

The task's pick sheet (`<notes>/sheets/ID.json`, with its published URL in `sheets/ID.url` and its copy `sheets/ID.html`) goes in the same cases, so a later `sheet ID --go` cannot run an old one; one written just before its own block (`done --blocked`, `run ask`) is kept, and a second `done --blocked` while still blocked removes a sheet not written since the last block, whether or not the ask file goes, and a block that waits on a task first keeps it.

A drop keeps a copy in `<notes>/dropped/ID` (git-ignored, on this machine only): the task's ask file and pictures, its pick sheet, its secrets file (1 day; the rest 30 days), and which tasks were blocked `(after ID)` on it. `plan restore ID` of a dropped blocked task puts it back blocked, with its BLOCKED text, and its ask and secrets back in place; the tasks the drop freed wait on it again as they were, except one changed since it reopened or one something works on. On another machine, or after 30 days, it still comes back blocked, without the ask file and the freed tasks. A ticked task comes back open as before.

### Approve to push

Off by default: a merge is pushed as soon as it is tested (`[git] push_merge`). With `[run] approve = true`, and a push
remote, a merge still passes the gate and lands on the local shared branch, but nothing reaches the push remote until a
person approves it. Nothing is pushed while it is on: not main, not the task/ or wip/ branches, not the plan edits'
commits, not claims. So two machines do not see each other's claims unless `[plan] repo` is used. It needs a push
remote and `push_merge`.

Each task that lands is a change in `.runner/pitches.json`. Changes are grouped into one pitch when one follows the
other with `--after`, or when they share a file, a module (`tests/test_x.py` counts as `x`), or a directory (not the
repo root, `tests/` or `docs/`; `shared_files` do not count). A group opens as a pitch after `approve_wait` minutes
with no new merge into it, or at once when it reaches `approve_batch` tasks.

A pitch is a page for the person, rendered from what each task's agent wrote in `.runner/pitches/<ID>.json`: what it
does, why, how to try it, the risk, and before and after when they help. In a slot, `done` refuses without the first
four. It also names the commits that would go out with it and are no task's change (one made by hand, a repair,
what was unpushed when `approve` was turned on). The page is published to claude.ai by a one-shot and shown at `/concept/pitchN`. It is a Needs you item; nothing pushes it to the phone unasked.

Approve (the button, or `agent-runner pitch approve pitch1`) pushes exactly up to the pitch's last tested merge.
Merges that landed in one gate run share that commit. If an earlier merge is not approved yet, the approval says which
pitch it waits for and is kept; both are pushed once that one is approved.

Not this (`agent-runner pitch no pitch1 [--reopen F1] [--drop F2] [--why "..."]`; with neither flag all its tasks are
reopened, and `--drop all` drops them all) makes an undo commit per task on local main, through the gate. Plan files
are left out of the undo. The task is reopened, or left closed as dropped. A conflict goes to a fix session. What
cannot be undone returns to Needs you with the reason. An undone change never goes out without its undo commit. With
no run up, the command does the undo itself.
The run app and `agent-runner ui` offer the same choices per change.

The pitch's page is its Review page (F444). Each change also shows its diff, folded, cut at `[run] approve_diff_lines`
lines (400 by default; 0 shows none). Plan files are not in it. While the change waits, the page also says how to answer it:

- `agent-runner pitch ask pitch1 F1 "why this way?"`: a fresh one-shot on `[models] review` answers from the change's
  diff (at least 400 lines of it, whatever `approve_diff_lines` says) and what its agent wrote. The question and answer are kept (`<notes>/pitches/<ID>@<merge>.asked.json`, so a reopened task's next change starts with none), and the page
  shows them under You asked.
- `agent-runner pitch better pitch1 F1 --why "what you want instead"`: Not this for that change. Its task is reopened
  with "asked for a better way: …" as the reason.
- `agent-runner pitch approve pitch1`.

The change waits after landing, on the local shared branch. A change that waits on its task branch, or as a pull
request (PR mode), has a Review page too (F444d): `agent-runner review F1 --page` writes it to
`<notes>/review/F1.html` and prints the path. It shows where the change waits (task/F1, or the pull request's link),
what its agent wrote, its diff (from where the branch leaves the shared branch, or from the pull request's base to
its tested commit) and the questions asked. `agent-runner review F1 --ask "why this way?"` asks one, the same
one-shot as `pitch ask`, and writes the page again. For a better way: `agent-runner plan note F1 "…"` on a branch;
say so on the pull request in PR mode.

`agent-runner status` and the run page say "3 changes wait to be pushed (1 pitch for you to approve)". Release tasks
(V) do not start while anything waits. If the remote moved, the next merge takes it in, and the approved work goes out
with that merge once it is approved.

### PR mode

Off by default. `[git] pr = true` turns it on, from the next run. It is for a repository on GitHub where a person
must review each change. It is refused with `[run] approve`, and it refuses `approve`: the config does not load with
both on, and Settings refuses the second one set. GitHub only.

It needs:

- A push remote on github.com (`[git] push`).
- `[plan] repo`, outside this repository and not this repository. Plan commits would otherwise reach main.
- Main protected on GitHub, so this machine's `gh` token cannot bypass it. Use either a ruleset that requires a pull
  request, with `current_user_can_bypass` set to `never`, or classic branch protection that requires a pull request,
  holds for admins and has no bypass for the token. Only an admin token can read classic protection, so for any other
  token use a ruleset.

The check reads gh's token, not git's push credentials. `agent-runner setup` and the run's start check it, and refuse
with why. What GitHub cannot be asked about counts as refused, so a start needs the network.

What happens to a task:

- `done` refuses without `.runner/pitches/<ID>.json` (what, why, try, risk). With `[run] review` on, it also refuses
  without a last line `review: …`. Concept tasks are exempt from the review line.
- The task is not ticked yet. Main is merged into `task/<ID>` in the merge worktree, with conflict fix and repair
  sessions as for a merge, and the gate runs on the result.
- The branch is pushed, never by force, and one pull request is opened, ready for review. Its body holds each task's
  what, why, how to try it and risk, its spec review, its text and the gate.
- The parts of a split task share the branch `pr/<KEY>` and one pull request, which opens once the last part
  finishes. A part started after another begins on that branch.
- Parts filed while that pull request is open share one of their own, `pr/<KEY>-2`.
- A part that waits for another task, where that task waits for these parts, or that is blocked on one of them, gets
  a pull request of its own.
- A blocked task opens no pull request. Its commits stay on `wip/<ID>`.
- A session that never passed `done` opens none. It is parked.

After that, every 60 s the run asks gh about each pull request. A pull request merged by merge commit, squash or
rebase ticks its tasks with that commit and removes their branches, once the local main has followed. A commit that was
not in the merged pull request stays on `leftover/<ID>`. Local main
moves fast-forward only. If uncommitted edits or local commits on main stop it, an alarm says so. A pull request
closed without a merge goes to Needs you, with who closed it and the last thing a person with write access wrote there.
The answer resumes the session, and a new pull request opens after it. The
answer, or any note given with `plan unblock`, is told to the session. Opening the pull request again on GitHub takes
the ask away. Or drop the task. If GitHub or the push cannot be reached, the run tries again.

Feedback on an open pull request resumes the task's session on its branch:

- A review comment on a line, a review with changes requested, or a comment review with text, by someone with write
  access on GitHub (permission write, maintain or admin). Everyone else's comments are ignored, as are plain
  conversation comments and approvals. The text reaches the session as quoted review input, never as other
  instructions.
- Red CI, or a conflict with main.

The session commits on top and runs `done` again. The runner takes main in, runs the gate, pushes (never by force) and
posts the session's replies, each on its thread; a review without a thread gets a comment on the pull request. Replies
start with a hidden mark, so they are never read as feedback.

Review comments that get neither a reply nor a change are tried again. Each kind (review, red CI, conflict) has at most
3 tries; then the task goes to Needs you, and the answer starts new tries. The count starts again when the checks that
were red passed, or when GitHub can merge the pull request. A round whose gate fails leaves the pull request as it was;
its commits are kept on `wip/<ID>`, and the try counts. A round running when a person merges ticks its tasks once its
session has ended.

Limits and display:

- `[git] pr_max` (default 5; 0: no limit; applies live; Settings > Merging > Open pull requests, shown while Pull
  requests is on): while that many pull requests are open on GitHub, no new task starts. Closed, merged and
  not-yet-opened (collecting) ones do not count. Tasks already running finish and open theirs, so there can be more
  than `pr_max`.
- Sessions that go on are not new tasks: feedback on an open pull request, an answered ask, a wait for a shared tool
  that ended.
- A task `after` one with an open pull request waits until that is merged; it never starts on its branch (parts of one
  split task sharing a not-yet-opened pull request are as before).
- Each open pull request shows with its link and state: `agent-runner status` (a "pull requests:" list), the run page's
  Status section Pull requests (a row opens it on GitHub), the terminal UI's Status panel (the selected line wraps to
  show the link) and its Needs you (label `PR`, id `pr-<number>`, nothing to answer, clears once merged or closed), and
  `plan waiting`.
- A state (`pr_rows.state_of`) is "CI red", "changes asked", "conflicts with the main branch" (joined by commas when several), else
  "approved, waits to be merged" (GitHub's review decision is approved), else "waits for review". It is from the run's
  last look, every 60 s.
- Status and the Run card say "5 pull requests are open: no new task starts until you merge or close one". A Plan queue
  row a pull request keeps says which, or that it waits for an open pull request to be merged; the dry run says why.

Nothing on main is pushed or committed by the runner. Settings for everyone are refused (this device's still save),
and the rules pointer is not added. A task never starts on an unmerged task's merge. The state is in
`.runner/prs.json`.

### No-push policy

Off by default. `[git] no_push = true` is for a project that must not publish: the runner pushes nothing, and git
refuses a push in every session the runner starts, in any repository. Settings > Merging shows it as "Never push". It
applies from the next run; sessions already up and the control server keep what they started with.

The runner pushes nothing: not main, not the task/ or wip/ branches, not plan edits, not claims (so two machines do
not see each other's claims), not remote branch deletes. Plan repo commits are made in the clone and not pushed.
Approve to push has nothing to push.

Each session the runner starts (task, repair/fix, control, one-shot; on Linux, macOS and Windows, with any provider)
gets git config in its environment through `GIT_CONFIG_COUNT`: a `push.recurseSubmodules` value that git refuses.
Other config there is kept. So `git push` fails in any repository with git's message, which quotes "blocked by the
no-push policy ([git] no_push)". `--no-verify`, `-c`, aliases, push URLs, repository config and child processes do
not get around it. fetch, pull, clone and commit work. Runner commands run in such a session (`done`, `plan add`)
push nothing in any project either. The session sets `AGENT_RUNNER_NO_PUSH=1`.

This differs from `[git] push = false`: that stops the runner's pushes, and the git fence refuses `git push` in Bash
calls of slots only. `no_push` also covers control sessions and child processes.

A run or control session refuses to start when this machine's git does not hold the policy (git 2.31 or newer).

It is a guard, not a sandbox. Not stopped: a process that clears or changes its environment (`env -i`, sudo, WSL, ssh
to another machine, a container); a git older than 2.31 at another path; `git send-pack`; git-svn, p4 and git-lfs
uploads; tools with their own git code (libgit2, jj, JGit); gh and API calls; package uploads; release commands. A
session opened by hand (not started by the runner) and `agent-runner setup`'s session are not covered. The test gate that `done` runs in a session
inherits the policy, so tests that push, even to a local remote, fail there (the merge gate does not have it; a test
may unset `GIT_CONFIG_COUNT` for its own temp repos). For a guarantee, remove the credentials or use branch protection
or read-only deploy keys on the remote.

A run started from a session under the policy keeps it, in any project; start it from your own terminal or Runner Home
to follow that project's own setting. An `env` in Claude Code's settings (or a shell profile) that sets
`GIT_CONFIG_COUNT` can displace the policy. The setting is a file, so an agent could edit `runner.toml` for a later run; `runner.local.toml` can override it. Claude.ai page publishing and
GitHub issue comments are not git pushes and are unchanged. The person's own terminal is unaffected.

### Concept tasks

A task of kind `K` (concept; one of the default kinds) builds nothing. Its session researches the repo and
publishes one Artifact page laying out the options, usually two or three, each with what it looks like or
does, the files it touches and its trade-off, plus a recommendation. It publishes that page with
`agent-runner publish-page <file>` (see below), then finishes with `done K7 "msg"`. `done` takes the URL that
`publish-page` recorded as its `--artifact` and the copy as its `--page`, and refuses a K task with neither
(unless `--blocked`); `done K7 "msg" --artifact <url> --page <file>` still works for a page published some
other way. Then
`done` notes the link on K7 (and in its journal, when `[plan] journal` is set), ticks K7, and files the build
task right after it, `- [~] **F12** Build the option a person approves on concept K7's page: … BLOCKED:
waiting for your OK on <url>`. That block names no task, so no run starts it and `plan reopen` never frees it.

- **Approve**: tell a control session "go with option B" (or "approve" for the recommendation). It runs
  `plan approve K7 "option B: …"` (K7 or F12 both work): F12 opens with `approved (<url>): option B: …` on its
  line, and a run picks it up.
- **Changes or a no**: `plan revise K7 "what to change"` reopens K7 (back from DONE.md) with the request
  noted and drops F12; the next round's `done` files a new build task.
- `plan waiting` lists what waits for an OK.
- **New and Updated** (F197a): the run app's concept rows carry `news` (`new`, `updated` or ''),
  `news_words` and `version`, from `<notes>/concepts/news.json`, one record every device shares. A concept is
  New until its details popup is opened (the run app's `concept_opened` action, `{concept, version}` with the
  version the popup shows, or `plan concept-opened K7 <version>`), and
  Updated when its page changed after that. A page published again at the same link is invisible to the run, so
  the chat that updated it runs `plan concept-updated K7 "<what changed>" [--file <the page>]`; `--file`
  replaces the run's local copy. A local copy changed with no command reads as Updated with no words.
- The build gets `F` where the kinds have it, else their first non-K letter. A repo whose `[plan] kinds`
  lack `K` has no concepts: a K-lettered id there is an ordinary task.

**A style for the future too** (F19). When a person approves a concept's style and says it holds from now on
("the future too", "make everything look like this"), the control session runs `plan restyle "<style>" --dry`
(the queued and running tasks that touch the interface: their `files:` meet the interface patterns, `*.html`,
`*.css`, `*.tsx`, `templates/**` and the like, or `--ui 'glob,…'`; a line naming no files by its words; or
exactly `--tasks ID,…`), publishes a restyle page itself (each current page or screen that changes to match,
before and after), then `plan restyle "<style>" --page <url> --from K7`:

- the restyle is filed as a concept already shown: `K9` ticked with its page, its build waiting for an OK;
- every queued interface task is held on it, kept in TODO.md: `BLOCKED: held for restyle K9 (style: …):
  reopens …` (no `(after …)`, so `reopen` never frees it, and it is not listed as stuck);
- a task a slot runs is held too, and the run is asked to park it: one whose `done` already passed (it was
  in its test gate) or that is merging lands, and is noted on the restyle's build (`landed in the old style
  while the restyle waits: ID`) for the page to list; any other is told in its session to stop at a clean
  point, commit and write its journal, and when its session ends its branch is parked as `wip/<ID>` (not
  counted as a failed merge), so its next attempt starts from there. No session is held open while the
  person decides;
- approving the restyle (`plan approve K9`, or yes on Needs you) opens its build and reopens every task held
  on it with `style to use (restyle K9 approved): …` noted.

### Research tasks

A research task changes no product: it finds out, measures or checks, writes its findings and queues the
changes they call for with `plan add`; its brief says so. Which tasks those are is read from what the kind
means, not its letter: `R` in the default kinds, and any letter whose meaning in a repo's own `[plan] kinds`
starts with "research" (`Q = "research: …"`). The merge lands such a branch only when every file it changes
is findings: the plan directory, the journal (`[plan] journal`) or `[run] findings` (default
`docs/research/**` and `research/**`; `!glob` takes one back), and the audits folder (see Auto audit; an audit is the exception, its diff is judged by its fix limit instead). A research diff that touches any other file
is not merged: the branch is parked on `wip/<ID>` and the task
blocks under Needs you with a DECIDE that says what the change does (the first line of `release-notes/<ID>.md`
on the branch, else the done message, else the title), that it is finished but held because the task was
research, and what each answer does. It ends in two buttons: `Ship these changes? [Ship them (recommended) /
Queue them as their own task]`. The file names and `wip/<ID>` are in the detail after ` — ` on the task's
line. `Ship them` (a plain yes, or `merge anyway`): the next attempt brings the code over and its merge lands
it. `Queue them as their own task` (`follow-up`): the next attempt files the code as its own task and commits
only the findings. The last answer decides; anything unclear is asked again. Only the answer's own words are
read, so a note that quotes the question does not count, but with no clear answer a plain note that
says `merge anyway` still lands the code (F36). The question is not asked at all when the person's own words asked for the code: the
brief has the agent put a line `asked for: "<their exact words>"` (three or more words) in the commit
message, and the merge checks that those words stand in the task's request (its line or long form, unless an
agent filed it as a follow-up), a person's change or answer, or a `plan tell` (kept in `<notes>/told/<ID>.txt`).
An unmatched quote is ignored and the person is asked.
At the merge, a file the branch adds that is empty (0 bytes) and is not findings does not count as code: a commit on
top takes it off the branch before the merge, so the findings land without it and the person is not asked. When the
diff has real code too, the empty files count with it and the question is asked as before; an existing file emptied is
still code. Tasks that are not research are unchanged.

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
  part of `P13`, and P13 and P13a are *family*, so they never run at the same time. Two parts (P13a, P13b)
  run side by side when both name `files:` that do not meet and neither is `after:` the other; a part with no `files:` waits for every other part, and they for it.
- The prefix says the kind of work. `[plan] kinds` names each letter (`B = "bug"`, `N = "netplay"`, …);
  the prompt lists them so an agent picks the right one, `plan kinds` prints them, and `plan add` refuses
  a letter the table lacks. With no table, the generic `B F T D R C K V` (bug, feature, tests and tooling,
  docs, research, cleanup, concept, release) are suggested but not enforced. `K` is the concept flow (above).
- `V` is a **release** (F38): the run treats every `V…` id so, so a repo with its own `[plan] kinds` lists `V`
  to file releases (and keeps the letter for nothing else). `plan add V` files it at the end of
  Next, and with no text it gets the default brief: bump the version per the project's versioning rules
  (docs/SETUP.md#versions here), move CHANGELOG Unreleased under it, commit to main, check the release
  workflow and `gh release view`. `plan add V` adds `after: all`, so it waits for everything ahead of it
  (or `--after` ids of its own) to land; then it starts, even with other tasks running in slots, and other
  tasks start beside it (F99). While it is busy (running in a slot, or finished and waiting to merge) the
  merge step holds every other merge and push: the tasks keep working, and their finished work waits to
  merge until the release has landed, so the release holds exactly what was on main when it started. The
  run log and the dry run say why a merge waits (`T5: waits to merge: V10 is releasing`). A release lands
  alone: no other task rides in its batch. A release taken by hand (`take`) holds no merges.
  Tagged `(alone)` (`plan add V --alone`, or `plan edit V7 --alone`) it **runs alone** instead: the run starts it
  only when no other task is running or waiting to merge, and starts nothing beside it. `plan add V --now` (or `--pri critical`) is an interim release: filed at the top, critical, with
  no `after: all`. A release is never refused as a duplicate of another release, and needs no `--files`.
  Two releases never run side by side (F195a): one starts only when no other release is releasing.
- **Alone tag** (F130): `(alone)` in a task's description, after its level tag if any: `plan add KIND "text" --alone`
  writes it, `plan edit ID --alone` sets it on an existing task and `--no-alone` clears it (an edit with new text or
  fields keeps it). Any kind of task can carry it, e.g. a major rewrite whose `files: native/**` would not hold the
  other tasks under that directory: a tagged task runs alone, so the run starts it only when nothing else runs or
  waits to merge in this run, and starts nothing beside it. Tasks taken by hand (`take`) or claimed by another runner
  do not hold it (B107), unless they are tagged `(alone)` too. The dry run and the TUI say
  `T1 runs alone`. While a critical tagged task is ready and only this run's running or merging tasks hold it, the run
  starts only critical tasks (non-alone critical ones still start) until those have ended and merged, then it runs
  alone; no such hold when a task in the way will not end by itself, or the alone task is tried this run, parked too
  often, being split, or its shared tool is missing (F208). A release (kind V) without the tag runs beside other tasks as above. A runner.toml that still sets
  the old `[plan]` key for this (removed in F130) gets one warning in the run log and is ignored.
- **Manage releases** (F193, on by default): `[run] releases = false` hides releases in a project that needs none. Off, the snapshot's `manage_releases` is false, its `releases` and `release_acts` are empty, its `release` and `release_said` are '' ('last:' lines of other tasks stay in `status`); an open V task stays in the queue as an ordinary task with its ordinary actions; `status` has no `release:` line and `agent-runner plan` no Releases group; auto release queues nothing and keeps its value; a New release from a stale page is refused with "Manage releases is off in Settings: no release was queued"; a typed `plan add V` still works. Settings shows it as Manage releases, above Release by itself; off, Settings hides Release by itself, also from the search, the Changed list and its count (its value is kept), and the 'Features, fixes, tests' row no longer names releases, while the Manage releases switch always shows and a save is followed at once (F193b2). `agent-runner ui` shows none of it either: no release tab or release line in Status, no release row in the Queue, R does nothing there and is left out of the key hints and the `?` keys list.
- **Auto release** (F63, off by default): `[run] auto_release` has the run queue a release by itself. `auto_release = { every = 10 }` cuts one once 10 tasks have landed since the last release (the later of a release task's landing and the newest version tag): it starts at once with what has landed (critical, at the top, no `after:`, as `plan add V --now`), not after the queue. A release that only waits in the queue for open tasks (`after: all` alone, with the default brief or queued by auto release) is cut instead of a new one queued; any other waiting release (a person's own text or explicit `after:` ids) is left as it is and a new one is queued. Such a waiting release does not stop the count, and the dimmed count shows beside it (F195c, see Release row). No cut while a release may start, is releasing, is taken by hand or by another runner, is blocked, shelved or in Parked/Stretch, and no second cut until 10 more land after the cut release landed. `{ idle = true }` queues one as `plan add V` with no text does when the run goes idle with nothing left it may start (tasks blocked on the person don't count), at most once per idle spell, never while a release is open. The release it queues has `| ahead: T1, T2` on its line (`none` for none), written by auto release alone; its `after: all` counts only those tasks and their parts (T1's T1a), still skipping what `after: all` skips (needs you, held, shelved, taken by hand); a move, or an edit of its `after:`, removes the list, and a count cut removes both fields. `plan ID` says `V7 waits for what was ahead when it was queued (2 open)`. Both may be set, and either fires; with both on they never queue two for the same landed work (a release dropped before it lands may be queued again), and Settings' row sets both. Nothing is cut or queued with nothing landed since the last release: release tasks are not counted, and nothing counts when only the plan changed since the version tag. `[run] releases = false` queues and cuts none. The run log and `status`'s lately say `queued V7 (auto_release: 10 landed)` or `(auto_release: idle)`.
- **Moved and removed releases** (F429a): `plan move` of a release task makes it wait for the tasks above its new place (`after: all`, and any critical or high tag is removed). That changes that cut only: the setting and the next cuts are unchanged. When the moved release is the next cut (it had no `after:`, has the default brief, or auto release queued it) its line gets `| moved: yes`, which only `move` writes; the automatic count neither cuts it early nor queues another beside it until it lands. A task that is running, taken, claimed, or waiting to resume or to merge can be moved before or after another (its slot, work and `after:` stay); `top`, `bottom`, `in` and a place under Parked are refused, and a started release cannot be moved (`V8 cannot be moved: s2 is on it`). `plan drop` of a release that auto release queued skips that cut: only tasks landed after the removal count toward the next one, and `plan restore` undoes it so the count is as before. A release a person filed does not change the count when dropped. The Next release row is named `next-release` in `plan hold|unhold|move|drop|restore`: held, no release is cut by count or on idle; `drop next-release WHY` skips that cut, `restore next-release` undoes it, and `move next-release after T2` makes it a release task at that place. Refused when auto release is off or an open release already is the next cut. Its hold and the removals are run events in `events.jsonl` (kinds `cut held`, `cut unheld`, `cut removed`, `cut restored`), local to the machine's run log, as the count is.
- **File split** (F200b, on by default): when a free slot could start no task (no usage limit in effect) and at least 3 ready tasks wait only for files, with one tracked file among them holding 3 or more, the run queues a file split by itself: one critical (alone) C task, or the kinds' first when there is no C, naming that file and its test files. The task splits the file by area with no behaviour change, then runs `plan edit <ID> --files` on each open task that names it. It queues none while a split of that file is open or blocked, nor within 7 days of the last one queued; that is read off the plan, so every machine's run sees it. Never for `shared_files`, lock files, docs (`docs_files`, `.md`, `.rst`, `.adoc`, `docs/`), the plan, generated files (linguist-generated, a generated header in the first 5 lines, names such as `*.min.js`), or files that are not text. It looks at most once a minute, not in `run once`, and waits while the plan has uncommitted edits or a merge holds the turn. The run log and `status`'s lately say `queued C9 to split a.py: 3 ready tasks wait for it (T2, T3, T4)`. Off: `[run] split_files = false`, or Settings "Split busy files".
- **Auto audit** (F417, off by default): `[run] auto_audit = { every = 50 }` queues an audit task once 50 tasks have landed since the last audit landed or was queued (audits are not counted). It is turned on in Settings > Advanced > Tasks and sessions (Audit by itself, Audit model, Token cap per audit); it is saved for everyone in runner.toml, and a run that is up takes it live. It queues only when the run is idle: nothing running, waiting to resume, merging or startable, and not paused, stopping or `run once`. At most one audit is open at a time (a blocked one counts). It looks once a minute, and a dropped audit is not queued again for the same work. The run log and `status`'s lately say `queued R5 (auto_audit: 50 landed)`. The task is a research-kind one at normal level, tagged `(audit)`. One can be added by hand, with or without the setting: `plan add R "(audit) what to look at most" --files 'plan/audits/**'`. It looks for stale and duplicate tasks (also about something a done task removed, or whose runs keep ending with no commits), asks unanswered over 7 days, dead docs, lessons, unused code and tests, and waste in run cost, only in what changed since the last audit: from the commit the last findings file's `Audited: A..B` line names (else the commit before the one that added the file) up to the branch point. The first audit looks at everything, newest first. Its findings go to `plan/audits/<ID>.md`, or `docs/audits/<ID>.md` when the plan is outside the repository or is its root; that folder counts as findings at the merge. By itself an audit changes only its findings file and dead references in docs, the glossary and lessons; `done` refuses a diff past that fix limit, and the merge puts one to a person. Anything else it finds goes on one pick sheet of at most 10 questions (`audit.ASKED`), each with a recommendation, why and a keep answer; findings past 10 go under `## Not asked` in the findings file. The audit blocks on that sheet, and the answer reopens the task so its next session carries out the answers (`plan drop`, `plan edit`, `plan note`, `plan add`) and writes what it did under `## Answered`. With `[run] questionnaires = false` it asks nothing and the recommendations stay in the file. Its cap is `[run] audit_tokens`: at the cap it is told to stop and run `done` with what it has; one that goes on to 1.25 times the cap is ended and parked as `wip/<ID>`. `task_tokens` holds too when it is smaller.
- **Release row** (F131, F185, F195c): each open release is its own row, shown once, in the Queue at its place in the plan order (`queue` carries `release`, and `ui_model.pin_releases` no longer moves it last); there is no Releases group or heading. The run page's Plan view draws it with `queueCard()`, the TUI's queue panel with `queue_with_releases`. `agent-runner plan` keeps its `## Releases` group (its id not listed again below), and the claude.ai copy's queue box is unchanged. A release row is in the Queue's list, so opening one closes an open task there and the other way round; J and K do not move a release, it stays at its place, and no task moves past one. A row reads `V17 Release · waits for 2: F1 one, F2 two` in status, `agent-runner plan` and the TUI (the first 5 named, then `, and 3 more`; all of them in `agent-runner plan` and on an opened or selected row, which also says what it is not waiting on; the run page's shut row never names them, see below), `next` when nothing is left before it, `releasing now` when a slot has it or it is merging (listed first), or `blocked` when it waits on a person. No start time is shown. On the run page New release is its own card above the Queue (`newReleaseCard()`, `release_wait`, `release_now`) that says what is open (the snapshot's `release_said`). With any release open, New release asks first: `ui_model.new_release` returns `confirm` ("V17 is already queued. Queue another release?") and `seen` (the ids open then) instead of queuing, and the Yes sends `seen` back as `text`. A queue row carries `started` (a slot runs it, it merges or a person took it) and, when it can be dropped, `asks` (`{key: question}`, from `confirm_of` on `queue_drop`: "Drop V17? It leaves the plan, and nothing is released."); a started release has no Drop. After the open ones comes the newest landed release, `V16 Release 0.62.0 · released 17:06` (the date too on another day), on status, `agent-runner plan` and the claude.ai copy; the TUI's queue panel and the run page's Plan view have no landed release row (the TUI's release tab and status still say it). On the run page's Plan view an open release folds to its row, which says `Waits for everything above` (`after: all` or `all above`, and at once for one just moved by its grip, the Next release row too), `Waits for 3 tasks` / `Waits for 1 task` (one whose `after:` names tasks, or that lists what was ahead when queued, `| ahead:`, F435), or `next` when dragged where nothing it would wait for is above; the row never names its tasks. Opened, it says `waits for 2` with its not-waiting-on note and lists the tasks it waits for, each opening in place, and one that waits for none opens to its text. With `auto_release` on, the dimmed `Next release · auto at 10 landed: 6/10` is there (` · when the run goes idle` added for `idle = true`, both when both are set). It stands before the task its `before` names: after as many open tasks (not blocked or parked) as it still needs to land, or at the end of the queue when that is past them or not counted. It shows also while open releases only wait for open tasks (F195a; then without the idle words, as idle queues none while one is open), and it is hidden while a release is next, releasing, blocked, taken by a person, shelved or in Parked. On the run page it is a dimmed dashed card (`.card.relph`); in the TUI a dimmed row. With `auto_release` off and no V open, the only row is the newest landed release, if any (none on the run page's Plan view, where New release alone is left). Enter on the dimmed row opens the release tab. `agent-runner status` has one `release:` line per release, the same words, in place of `last: V5 waits for everything before it`, keeping its `not waiting on` notes; once the release lands, `lately` reads `landed: Release 1.2.0 [V5]` and the count starts again at 0/N.
- `plan add` also refuses (exit 3, nothing written, the task named, even with `--force`) an add whose text and
  fields equal an open or blocked task's (B817). Whitespace, id and kind letter, level, the `(alone)` tag, order
  within comma-list fields, notes and BLOCKED do not count; split parts are not exempt; the check runs
  under the plan lock and reads the other git worktrees' TODO.md too, so another slot's unmerged follow-up counts.
  Done tasks are no obstacle, and releases (kind V) are exempt. Text that merely looks like an open task's work
  is refused too, naming it: `plan note` that task instead, or `--force` for different work. A task's own split
  (`plan add P13 …`) is never refused for looking like P13. `plan drop ID WHY` closes a task nobody will do (a duplicate,
  overtaken): archived with `dropped: WHY`, so its id stays used. What waits on it (`BLOCKED: (after ID)`) depends on why (B772): dropped as not wanted (the default, and the run page's and the TUI's Drop) each such task is held under Needs you with one question, `DECIDE: Still wanted, now that ID (title) it waited on was dropped as not wanted? [Keep / Drop]`; one that also waits on other open tasks asks now and says so (on Keep, block it `--after` them). `plan drop ID --duplicate-of X WHY` or `--overtaken-by X` (or a WHY that says `duplicate of X` / `overtaken by X`) lets them go on: they wait on X in ID's place while X is open, else reopen as before. A task waiting `(after all)` and a release are never held: the drop frees them as before. `plan restore ID` puts the held tasks back as they were. Dropping every part of a `(split into …)` task does not tick it: see A12 below.
- Reaching a running agent: `plan tell ID TEXT` types `A note on your task, from the person running this run: TEXT` into
  the session of the slot running ID, through its shim's FIFO, or on Windows its named pipe (Claude Code queues it for
  its next turn while busy), and edits no plan. It fails when no slot of a run here runs ID, and then drops nothing: if the task asks the person (its `run ask` parked in `<notes>/ID.ask`, the block committed or not, or any block waiting on a person) it prints the question and the exact `plan confirm ID "TEXT"` or `plan change ID "TEXT"` to run if the text answers it; otherwise the `plan note ID` to run. A tell never answers by itself, and one the run found no slot for is kept in the run log (`ID: not told: TEXT`). While a slot's agent has just run `run ask` (its end mark `<notes>/slotN.end` is written), nothing is typed: a tell waits until the ask is parked, then fails (exit 1) with the question and the commands above, or after 30 s, if the session has not ended, says to run the command once it has. `plan change` then notes the change, prints the same, and does not stop the slot, so the parked work is kept. `plan change ID TEXT` on a
  running task notes the change in the plan as usual, then types `Your task changed: TEXT` into it, and the agent works
  on. Both print `told s1 (ID)` once the text is in. They go through the run like a halt: a request in
  `<notes>/tell/<ID>.json`, answered in `<notes>/tell/<ID>.done`. With no live session (Windows before 1809 or a stream
  slot on Windows, a session that ended, a cut-off one waiting to resume, a finished branch merging), `change` says so
  and falls back to stopping the slot and starting the task again from the new text, which `plan change ID --restart
  TEXT` asks for outright.
- A note one side adds to a task the other side ticks is kept: the tick wins in TODO.md, and the runner
  appends the note to the task's line in DONE.md after the merge.
- After the prose come keyed fields, each ` | key: a, b` (comma-separated), in any order; a ` — note` or
  `BLOCKED: …` may follow them. **Prose is never parsed** for files or ids: only the fields count.
  - `files:` the files the task will touch. The run keeps two running tasks off the same file, and the brief
    pastes them in. Files that don't exist yet count, and so do patterns: `dir/**` and `dir/*.rs`. A path
    meets its own tail (`src/menu.rs` meets `app/src/menu.rs`).
  - `needs:` the shared tools the task uses (`### Shared tools`), e.g. `needs: iphone15`. The task waits while one is
    busy or missing, and the run never runs two tasks with the same tool at once.
  - `after:` ids that must be done first. **Every id** listed counts. `after: all above` (what `plan add
    --last` writes, filing the task at the end of Next) is no list: the run resolves it on every pick to each
    task above it in its own section that is not done, ones added later included, so a release waits for the
    whole section without a list going stale. Tasks blocked on a person don't hold it until they reopen;
    nor does a task whose unfinished `after:` chain reaches one blocked on a person, shelved, or in Parked or Stretch, through a split task's unfinished subtasks too (B207, B209);
    Follow-ups never do. `plan reopen`, `plan waiting` and `status` say what it still waits on.
    `after: all` (`plan add/edit/block --after all`, any kind) waits for **everything before it**: each open
    or blocked task above it in TODO.md, in any section, resolved afresh on every pick, so a task queued above
    it later holds it too. Parked (`--pri later`) and Stretch tasks and shelved ones don't count, or it would
    never run; nor does a task whose unfinished `after:` chain reaches one blocked on a person, shelved, or in
    Parked or Stretch, through a split task's unfinished subtasks too (B207, B209). On a block it reads `BLOCKED: (after all) why`, and `plan reopen` frees it once nothing is left
    before it. `plan ID`, `plan reopen` and `plan waiting` show it as `T5 waits for everything before
    it (12 open)`, not an id list; `status` does too for a task that is not a release (a queued release shows
    its row instead, see Auto release).
  - `model:` the model the task's own session runs on (`plan add/edit --model M`), which wins over its kind's
    `[models.kinds]` entry; `plan ID` shows it. See Models per kind.
  - `split-by:` the time (UTC) before which a task too big for one session may not start, so its author can split it (B196). Only `plan add` writes it, from the size check; it is not set by hand, and it ends early as the splitting paragraph below says.
  - `test:` the tests that prove it. `journal:` its journal folder.
  - `plan add P "text" --files a,b --after X --test name` writes them; `--model M` writes `model:`; `--needs T` writes `needs:`.
- `BLOCKED: (after X, Y) why` is what `plan block`/`done --blocked` write. The `(after …)` list is what
  lets the run reopen the task by itself. `BLOCKED: (until CHECK, …) why` is what `--until` writes; see ### Until checks.
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
  running there: a task sharing its files or its ordered section waits for it, and so does its family (a task and its own part always; two parts only as the Picking rule says). The claim
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
  claims would otherwise hold those tasks for good. A claim not refreshed in 2 h (`plansync.TAKEOVER`) is a gone
  run's: it holds nothing, and the next run to pick its task takes it over, re-claiming it as its own (a push
  race as with any claim) and logging `took over <ID> from <who> (claim not refreshed since <time>)`. The old run,
  when it comes back, sees the claim is no longer its own, logs it and gives the task up; a `task/<ID>` branch it
  pushed is kept, not deleted. A claim from a runner older than 0.14 shows `pre-0.14`,
  and every other run warns once: that runner does not keep off their files, so upgrade every machine. The same
  checkout takes its own back on its next run; for anyone else's, `plan unclaim <ID>`.
- **Tick on landing.** `done` in a slot leaves the task open and the run ticks it once the merge lands,
  noting `landed <sha>`; a merge left for a human leaves it open, as in-repo. `done` outside a run (a
  person's session) ticks at once. `--blocked` blocks at once either way.
- `tasks/<ID>.md` long forms, `REFERENCE.md` and `HUMAN.md` live in the plan repo; `[plan] journal` stays in the
  code repo, since journals describe code and travel with it.
- `dir` outside the repo without `repo` (a synced folder) shares one copy the same way, without git.
- Moving an existing plan over, keeping its history: `plan repo-setup [URL|path]` (F460). With no argument it
  makes a bare repo at `[run] home`/plan.git; a path that is not there yet is made the same way. An empty
  repo gets the plan folder's history (`git subtree split`) plus any edits not yet committed; one that
  already holds a plan is joined (open tasks only this checkout had are named, to add again). Either way
  `[plan] repo` is set in runner.toml (an in-repo `[plan] dir` taken out), the plan folder leaves the code
  repo in one commit on the current branch, and it prints the line for the other machine: `git pull`, then
  the same command (on a checkout already in plan repo mode it only clones and pulls). A local path suits
  one machine; for two, give a URL both can reach.
- `status` says once (marked in the notes as `plan-repo-hint`) when claims come from another host while the
  plan is still in the code repo: plan repo mode would share the plan itself, not only the claims.

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
`plan move ID after ID` puts it where you want it. Ready critical tasks are tried first, then high ones, wherever their lines stand.

`plan hold ID` keeps a queued task, or a release, at its place in the queue, and no run starts it until `plan unhold ID` ends the hold. It is the field `| held: yes` on the task's line, written only by hold (edit and move keep it, add ignores it). A task that is running, taken by hand, merging, finished and waiting to merge, or claimed by another runner cannot be held (refused, exit 1). A held task is not under Needs you, and an `after: all` or `all above` release does not wait for it or for one that waits on it; a held release is not cut while tasks land. Unlike a parked task (later, in the Parked section) or a shelved one (a Needs you item), it is skipped until the person ends the hold. The queue row says held, and the dry run says `held`. A release moved with `plan move` (F429a) waits for the tasks above its new place, and the Next release row can be held, moved or dropped the same way: see Moved and removed releases under Auto release.

`plan edit ID --wait-for X,Y` (the flag alone, with nothing else on the command) sets what a queued task waits for to exactly those tasks, replacing its `after:`; for a task blocked on `(after …)` it replaces that list and drops a separate `after:`. `--wait-for none` clears the waits; a blocked task reopens with its notes kept, and a person's check (CONFIRM and the like) that waited goes back to Needs you. Other fields, place, notes and hold stay. It is refused (exit 1, nothing changed, the reason printed) for an unknown or done task (itself or one of the waits), itself, its own parent or subtask, a wait that makes a circle (the chain is named), a release, a task that has started (running, taken by hand, merging, waiting to merge or resume, claimed by another run), one that asks the person, a shelved one, one that waits on an until check, or one waiting on anything but tasks. The run app's action is `set_waits` (task id and a list of ids; an empty list clears).

`plan cancel ID` stops a running task (or one cut off and waiting to resume) without removing it. Without `--yes` it stops nothing: it prints the question with the minutes worked and exits 3. With `--yes` the run ends the agent's session, commits its uncommitted edits and renames task/ID to wip/ID (wip/ID-2, … when one exists; pushed; with nothing done there is no branch), and frees the slot. The command then holds the task in its place (as `plan hold`, F480) with a note naming the branch, so no run starts it. End the hold with Unhold on the Plan or `plan unhold ID`: its next agent is pointed at that work. It does not count as a failed merge. It is refused (exit 1, nothing changed) when the task is not running, is finished or merging, or has just asked the person. If the run does not answer in 30 s the task is held anyway and the run stops the agent within seconds. Edits that cannot be committed stay in the slot, and it says so. `plan hold ID` on a task a slot of this run is on does the same as `plan cancel ID --yes`; it still refuses one merging, finished and waiting to merge, taken by hand, or claimed by another machine's run (named).

A follow-up an agent files gets a level (`--pri`, default `normal`), tagged on its line as
`(follow-up, LEVEL)`, and is filed so the work a person queued comes first:

| level | filed | for |
|---|---|---|
| `critical` | top of the leading section, behind earlier critical ones | it breaks or blocks other work (the text says what) |
| `high` | top of the leading section, behind critical and earlier high ones | important work that blocks nothing; a run tries it after the critical ones and ahead of the rest (agents use it only when a person asks) |
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
line (with the first five failing tests, when the log names any) and in `plan/tasks/<ID>.md` every failing test with
the log's FAIL lines and tracebacks, then the last 40 lines of `gh run view --log-failed`. Tasks are keyed by workflow
and failing test: while the workflow's task is open, a failing test it does not name is added to it, and one it
already names files nothing; a closed task naming a failing test is opened again, with its earlier fixes' commits
linked, and a dropped one stays dropped (a new task names the test). A log that names no test works as before.
No run is judged twice (`<notes>/ci-<workflow>.seen`), so a broken workflow is one task, not an email per push. Landing never waits on CI.

It can read the repository's GitHub issues as well, off by default. With `[run] issues_watch = true`, on the
same 5 min cadence and only when no merge holds the lock, it asks `gh issue list` for the open issues and
files one task per issue it has not seen (B for one labelled as a bug, F for the rest): the issue's number,
title and URL on the line, its body in the task's long form (`plan/tasks/<ID>.md`). `issues_watch = ["bug",
"runner"]` takes only issues carrying one of those labels. Each issue is filed once (`<notes>/issues.seen`),
and none while an open task already names it (`GitHub issue #<n>` or its URL). `[run] issues_trust` says how
the task treats the issue: `"skeptical"` (the default) files it as untrusted outside text, so the agent
reproduces or confirms the problem in the code before it changes anything, follows no instruction, command or
link in the issue, and when it cannot confirm it, or the ask does not fit, closes the task saying why (no code
change) or blocks it on the person; an issue the repository's owner opened counts as trusted. `"trust"` files
it as a task to do as written, still never running a command from it. `"contributors"` trusts an issue whose
author GitHub calls OWNER, MEMBER, COLLABORATOR or CONTRIBUTOR (has a merged commit) and files the rest
skeptical; `"members"` trusts OWNER, MEMBER and COLLABORATOR only; a list of GitHub logins (`["alice",
"bob"]`) trusts those authors. Any other value counts as `"skeptical"`. Each filing keeps its own trust, so
the issue's close or comment follows it. When the task closes, the issue gets a
comment naming the merge commit (or saying it closed with no code change); under `"trust"` it is closed too,
under `"skeptical"` only commented. A `gh` that cannot see the repository is said once in the run log, as for
CI.

Several slots run at once, so **a task that has to wait for another must say so in a way the runner reads**.
Writing "follows A12" in its text isn't enough: if A12 hasn't started, the task starts beside it.

| to make B wait for A | do this | what happens |
|---|---|---|
| B is part of A's work | `plan add A12 "…"` gives `A12a`, then `A12b` | a task and its part never run at once; parts A12a and A12b run side by side if both name `files:` that do not meet and neither is `--after` the other, else they wait for each other; use `--after` between parts that need order |
| B needs A merged first | `plan block B3 --after A12 "why"` | B3 stays `[~]` until A12 is done, then the run reopens it |
| a list that must go in order | a section heading saying *in this order* or *one at a time* | one task from it runs at a time |

A plain new number (`plan add A "…"`) is an independent task and may run beside anything. `agent-runner help order`
prints this summary; `agent-runner run --dry-run N` shows what N free slots would start now, and why the rest wait.

A task over `[run] task_size` is split the same way: `plan add A12 "…"` per part (A12a, A12b, …), then `plan edit A12 "<title> (split into A12a, A12b)"`. `plan add`, `edit`, `note` and an approval say when a task is too big and how to split it, and a run that starts an unsplit one has its session split it before it does the first part (F177). A12 ticks itself once its parts land. Once its last open part closes it ticks only if at least one part landed; if every part was dropped (each one's `dropped: WHY` note), it stays open as one whole task: its `(split into …)` is taken off, a BLOCKED on it stays, and `plan drop` says so and to edit the task if its text lacks the work the parts held.

When `plan add` says a task is too big, it also writes `| split-by: <UTC time, 5 minutes ahead>` on the task line, and no run starts it before that time (B196), so its author can file the parts first. The hold ends at once when the first part is filed (`plan add A12 …`), when `(split into …)` is written or the task is brought under the size, or on `plan move ID top`; `take` starts it any time. An edit that leaves it too big keeps the same end time. A task a run's own agent files behaves the same. Only `add` sets `split-by`; a note, edit or approval that makes a task too big does not hold it. While one is held, `status`, `plan` and the queue say `waits to be split, starts in 4 min if it is not`, the dry run says `waiting to be split`, and the run does not show idle.

## Picking

`pick` walks TODO.md in order and starts the first task that passes all of these checks. The order is the
file's, except that a task a waiting one depends on (`after: X` on an open line, `BLOCKED: (after X)` on a
blocked one) moves up to where that one stands, down the whole chain: a Next task blocked on a Follow-up
does not wait behind every task between them. The plan read is the shared branch's, or its remote's when a
push from outside the run has put that ahead (fetched at most once a minute).

| skipped | why |
|---|---|
| `[~]` blocked, and split parents (a task with open subtasks) | the subtasks are the work |
| the open subtasks of a task with a `wip/<ID>` branch (not `(split into ...)`, not in Stretch or Parked, and not waiting on one of them, directly or down the chain) | the parked attempt's first part is what they build on, so the task goes first (B185); they wait until it lands, also while it is tried this run or blocked |
| an open id in `after:`, for **any** id listed | every listed dependency must be done |
| a part of a running split task (same family), when their `files:` meet or one names none; a task and its own part always | the parts edit the same thing, or one could touch anything |
| a task in a section whose heading says *in this order* or *one at a time*, while another task from that section runs | an ordered section runs one task at a time |
| `### Stretch`, `### Parked` | never unattended |
| tried this run | one attempt per run: if it failed, a human looks next |
| a bug (B) task whose `files:` meet those of a task under Needs you with CONFIRM (not shelved); critical and high tasks pass | a fix waits for the person's check of the earlier one on the same files, so fixes do not pile up on unchecked ones; `run --dry-run` says which check it waits for (F415) |
| `task/<ID>` has commits not yet merged | it's finished and waiting for the merge |
| a `files:` entry meets one of a running or finished-unmerged task's (its line's, and the files its branch has touched), minus `[run] shared_files`; a whole-directory entry (`tests/**`) is a guess, not a lock: it meets only another whole-directory entry, so a named file under it meets only what that task has touched | keeps merges clean. Exception: a task that clashes only with finished tasks all in one merge under way starts on top of that merge (F198, Behaviour) |

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
Two runs in a row that end a task's slot session with no commits, its plan text unchanged, block it the same way: `<notes>/no-commits.json` counts them across restarts, and a task told, reopened or edited in between counts afresh (`no_commits.py`, B774).

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
the 7-day usage, no new task starts unless `--force` is given (or `f` typed in the run view); hitting one raises the STOPPED alarm with that hint. With `[models] fallback` set, a new task whose model is claude's starts on the chain's first free provider instead, until the reset (see Fallback chain); a task with no free provider waits. `[run] usage_limits = false` switches both caps off: the runner never reads the account's usage, never holds or falls back a task on them, and status hides them.

**A cut-off session resumes.** A session whose turn ended on an API error (the network dropped, the
API was down, the account hit its usage limit) is not finished, though the idle stop ends it. Its worktree is left as it is, and once the
API answers again it is resumed in the same slot (`claude --resume`, with its whole conversation) and told
it was cut off. While the API cannot be reached, no session resumes or starts. At startup, a slot still on
`task/<ID>` whose session stopped mid-turn while no run was up (a reboot, the runner killed) is resumed
the same way. A request the API refused is not a cut-off (it would fail again), and one session is resumed at
most 3 times. `agent-runner resume <ID>` resumes a task's last session by hand, for one the run already ended:
when its slot is free, the edits it left come back from `wip/<ID>` (kept as `resumed/<ID>`).

**Finish and ask (F102).** After `done`, the agent runs `agent-runner finish "<summary>"`: the summary goes to
the run log (`slot N: T4 finished: …`, event `finished`) and the Stop hook ends the session at once, with no
idle wait. Mid-task, a question only a person can answer goes through `agent-runner ask "<question>"`: the
session ends, its work (commits and uncommitted edits) is kept on `asked/<ID>`, never merged, and the task is
blocked `DECIDE: <question>` under Needs you. The answer (`plan confirm` or `plan change`) reopens it, and the
next slot resumes that same session (`--resume`) on the kept work, the answer as its next message. Claude Code's
AskUserQuestion tool stays off.

**Publish a page (F106f).** `agent-runner publish-page <file> [--id ID]` publishes a concept's options page. ID
defaults to the worktree's `task/<ID>` branch. It copies the HTML to `<notes>/concepts/<ID>.html` (the run page
shows it at `/concept/<ID>`), then starts a one-shot headless `claude -p` with only the Artifact and Read tools to publish
that copy to claude.ai: a new artifact with icon "options", or the URL already recorded for ID, so a second
publish updates the same page. The URL is printed and kept in `<notes>/concepts/<ID>.url`. Exit 1 when the
one-shot did not publish (the copy is still on the run page); exit 2 for a missing file or no task id.
With no Claude Code program on this machine, or `[models] feed` on another provider (its one-shot cannot publish), the
command exits 0, says there is no claude.ai page, and records `/concept/<ID>` in `<notes>/concepts/<ID>.url`, which
`done` takes as the concept's page. In the TUI, O on such a concept opens the local copy. A one-shot that ran and
failed still exits 1.

**Publish a pick sheet (F411).** `agent-runner sheet ID --publish` checks and renders the task's pick sheet, then has the
runner publish it to claude.ai with the same one-shot as `publish-page`, with the page's db capability so Send still writes
the picks there, and prints the URL. The URL is kept in `<notes>/sheets/ID.url`, so a second publish updates the same page.
A slot runs this from SHEET_PROMPT in its brief and needs no Artifact tool. With no Claude Code program on this machine, or
`[models] feed` on another provider, the command exits 0 and the run page keeps the sheet at `/concept/ID_sheet`: its Needs you
item has Open (O in the TUI opens the copy), the DECIDE line has no link, and Send there gives its Pick link (https) or a line
to paste, since there is no db. A one-shot that ran and failed exits 1. `--html FILE` still writes the page, to look at.

**Spec review one-shot (F406e).** `agent-runner review [ID] [--base BRANCH]` runs the spec review before `done` as a
fresh one-shot on `[models] review`, given only `git diff BASE...HEAD` (BASE: `--base`, default the shared branch)
and the task's brief, and prints its findings (exit 0). It is Read only and gets 900 s. Exit 1 with
`run review: no review: <why>` when the one-shot did not run or the diff is empty (commit the work first); exit 2
with no task. A claude model runs as a headless `claude -p`; another provider's runs in the harness loop with
`--once --tools read`. A Claude Code task with a claude review model is unchanged: its `review` subagent does it.

**Git fence (F102).** Every Claude Code slot gets a PreToolUse hook through `--settings` (`agent-runner fence`)
that denies `git push` in this project (anywhere while `[git] push = false`), `git reset --hard`, `git clean`
(not `-n`) and `git checkout -- .`, and an Edit or Write in the main checkout (but its notes folder) or
another slot; an edit outside the project, in a sibling repository the task needs, is let through. It
holds every session, and replaces the no-push git config that `[git] push = false` used to set. With `[git] no_push = true`
the refusal covers every repository and every session the runner starts (### No-push policy).

**Idle stop.** The Stop hook starts a detached timer; a session quiet for 30 seconds is ended.
The timer does not fire on a session a human has typed into, or one waiting out a usage limit. Nor on
one whose agent still has a child process (a background command), until it ends or
`AGENT_RUNNER_IDLE_MAX` (10800 s) has passed since the stop.

**Nothing uncommitted is lost.** When a session ends with edits it never committed, the runner commits
them onto `wip/<ID>` if the task has no commits (the next attempt is told to read it), or onto
`leftover/<ID>` otherwise, so the merge never takes in untested edits; both are pushed. Only then is
the slot reset.

**Stall watchdog.** A session quiet at a prompt with no tool running for 1200 seconds (20 min),
or quiet for over 65 minutes with a tool running, is logged with the terminal to look at, and the bell
rings.

### The removal check

Before the gate, `done` looks at what the task's diff removes (F416): the commits past the shared branch, or past
the merge the worktree was started on, plus uncommitted and untracked files. When it deletes or renames a file, test,
setting or command, `done` searches for each name (two words or more, or a file name with an uncommon extension) in
code, config, CI workflows, docs, the glossary, lessons, open tasks and their long forms (its own task left out), and
the project's Claude Code memories (main checkout and worktree). History is exempt: DONE.md, CHANGELOG,
docs/research, `[run] findings`, the journal and closed tasks' long forms.

A dead path (the removed file's full path, a Python import of it, or in config and CI a folder with no file left)
in code, config or CI refuses `done`, and no answer helps; code that must
name it, such as a fixture or migration, can build the path from its parts. The other mentions are a numbered list.
`done` refuses (exit 2, nothing ticked, no failed gate counted) until each is answered once: fix it (it leaves the
list), or `--named "1 filed B12; 2-3 kept because <why>"` (no number or `all` means all; `fixed` is accepted only when
it is gone; a filed ID must be an open task). Answers are kept per task in the worktree's git dir. An answer given
before the list was shown counts for nothing, and a new mention is asked about on its own.

A file now git-ignored counts as made, not removed; a test, setting or command moved to another file is not removed,
but one gone from code is, even when a config file still sets it. A command's `--flag` counts as a setting.
An open auto-filed CI task for a removed test or workflow is listed too. It runs on docs-only diffs and with
`--no-test`, not with `--blocked`. It reads text only: no model call.

### Shared tools

Some things only one task can use at a time: a test phone, a device. Each is named under `[run.tools.<name>]` in
runner.toml, with a `check` command:

```toml
[run.tools.iphone15]
check = "tools/ui-15.sh state"   # exit 0 free, 75 busy (first line: the holder), 69 missing (first line: why)
label = "iPhone 15"              # what the screens say; default: the name
connect = "Connect iPhone 15"    # the Needs you wording while it is missing; default: "Connect <label>"
description = "the phone on the shelf, for app tests"  # what it is, for agents; default: none
page = ":8080"                   # optional: its web page (A web page, below)
start = "tools/serve.sh"         # optional: the command that serves it

[[run.tools.iphone15.buttons]]   # optional, any number: tool buttons (Buttons, below)
label = "Reset app"              # the button's text: 60 characters, unique in the tool (ignoring case)
cmd = "tools/ui-15.sh reset"     # one line, 1000 characters: runs once and ends
confirm = "Reset the app on the phone?"  # optional: a question asked first, 300 characters
```

- **The check** runs in the main checkout. Exit 0 is free, 75 busy, 69 missing; any other status, or a run past
  10 s, is unknown. A busy check's first line names the holder and should carry the task's id (`F389`), so a task
  that holds the tool itself is not held by it. A missing check's first line says why.
- **When it runs.** One thread per tool checks it every 120 s, every 15 s while a task waits for it, and again right
  before a tagged task starts. A change to or from missing or unknown counts after 2 readings in a row; free and
  busy change at once.
- **Unknown does not hold for ever.** It is logged once, and tagged tasks wait for it at most 5 min, then start
  anyway. So does a check that fails only now and then: its failing holds a start at most 5 min, counted until 2 good
  readings in a row. A broken check must not stop the work for ever. The agent still takes the lock itself.
- **Never two at once.** The run never has two running tasks with the same tool.
- **Tagging.** `plan add --needs iphone15` writes `| needs: iphone15` on the task's line, and `plan edit --needs`
  sets it on an existing one. A name the project does not name is refused. The TUI's direct edit (`e`) has the field
  too, in projects that name tools.
- **Waiting.** An agent that finds its tool busy or missing runs `run wait-for iphone15`. Its session ends, its
  commits and uncommitted edits are kept on `waiting/<ID>` (never merged, and no park count), and the session's
  record is in `<notes>/<ID>.wait`. Once the tool is free, the same session goes on ahead of other tasks, longest
  wait first, and this survives a run restart. `wait-for` is refused while the session itself holds a tool; when the
  tool is free after all it says so, and the agent takes it and goes on.
- **Idle.** A run waiting on a busy tool, or on one whose check still holds its tasks as unknown, is not idle: it does not power off or auto release while it waits. A
  missing tool does not keep it up.
- **What shows.** A Tools line on `status`, the TUI Status panel and the Run card: `Tools: iPhone 15: held by F389,
  12 min`. A task that waits reads `waits for iPhone 15, held by F389, 12 min` on its queue row, and in `plan`,
  `needs` and `status`.
- **Needs you.** A missing tool with tasks waiting for it is one Needs you item (label `TOOL`) after 3 min, and
  clears by itself when the tool is back. A busy tool never is one.
- **Without the setting** no tool is checked and nothing else changes; a command stopped for low memory still waits
  (### Waiting for memory). The run keeps its readings in `.runner/TOOLS.json`, so a restart goes on
  with them (a file older than 10 min is not used).
- **A web page.** `page` is an http or https address, with no sign-in in it, or `:PORT` for this machine, at the host
  the run page was opened on. `start` needs a page: one line of shell text, 1000 characters at most. It runs in the
  project's main checkout, read fresh from that checkout's runner.toml only (not a worktree's, not runner.local.toml,
  not AGENT_RUNNER_CONFIG's file, and never text the page sends). Start, stop, state, output and the https, token and
  same-origin rule are as for a device's web page (### Devices). A change to `start` does not stop what runs: Stop (or
  `run device stop NAME`) still ends the old command, also when `start` or the tool itself was taken out (once the tool
  is gone it has no card, so stop it with the command). While runner.toml does not read, no `run` command works, but
  POST /tools still stops it. The next start uses the new one. `run device start|stop|show
  NAME` take it and `run device list` lists it; when a device has the same name, these commands take the runner.toml
  tool. POST /tools ops `start` and `stop` take an optional `"source"` (`"device"` or `"runner.toml"`), the device when
  not given. GET /tools gives `page`, `start` and `run` (its state). On the Tools page such a tool's card shows its address and state and has Start, Use and Stop as a device's does (### Devices), Use alone with no start command; a Needs you item whose task names it in `needs:` has Use LABEL, or Open LABEL in Tools while it is not running. Without `page` the card is unchanged.
- **Buttons.** A tool's buttons are read fresh from the main checkout's runner.toml only, and each runs there, one at a time per tool, with a 30 s limit (then its process group is ended, and also when it prints over 16 MB). A press is POST /tools `{"op":"press","name","button":label,"source"(optional, as start/stop),"confirm","holder"}`, under the https, token and same-origin rule of the Tools page. It answers `{ok,out,exit,lines}` (exit null when stopped; `lines` is the last 20 output lines, stored secrets hidden, none shown if a secret cannot be read). `{ok:false,ask:question}` when the button has a `confirm` and the request's `confirm` is not that exact text; `{ok:false,busy:{holder,key}}` when someone has the tool (its check, run then, says busy, or a running task needs it). Sending `holder` = `key` runs it anyway, only for that same holder; a new holder asks again, so a check's first line should stay the same for one holder. A missing or unknown tool is not busy. GET /tools gives `buttons` (`[{label,cmd,confirm}]`) when there are some. The Tools page shows them on the tool's card, in a row of their own, and over plain http they are disabled: a button is busy while its command runs (the tool's others wait), a question is asked in its place, then Yes or No, and the result or failure with its last output lines stays at the foot of the card until that tool's next press (F428d).

### Devices

A device is a machine or test rig agents reach over SSH or another way: a phone's address, a board on the LAN, a
command on this machine. A person adds it on the run app's Tools page. Each project says which devices it uses
(**Used here**, a switch per project), and a used device is a shared tool: a task names it in `needs:` like any other
(### Shared tools). Tools in runner.toml show on the same page with their source; they are edited in runner.toml.

- **The Tools page.** Add a device: a name (letters, digits, - and _, 40 at most), its kind (SSH or other), the host or
  a `~/.ssh/config` alias, the user and port of a host of its own, a description (what agents see), and whether one task at a time may use
  it. Edit… (a new name too: a task's `needs:` keeps the old one), Remove (its secrets go too) and Test connection, which checks it now and, for SSH, shows the host key for
  a person to accept. An other device takes the address or command agents use. The same sheet sets the device's buttons: each one's label, command and, if it needs one, a question asked first (see **Buttons.** below).
- **The check.** A device is free, busy, missing or unknown, as a shared tool is, and a missing one with tasks waiting
  for it is a Needs you item. The default check uses no secret. An SSH host is a TCP connection to its host and port
  (22 by default); an alias behind a ProxyJump or ProxyCommand is probed with ssh, as TCP cannot see through it. An
  other device with an address is a TCP connection to its port (vnc, rdp, http and https have their own); with a
  command, it is free when that command is on this machine.
- **A web page.** An other device can have a web page: an http or https address, with no sign-in in it, and, with it, an
  optional start command (one line of shell text) and its working directory (an absolute or `~` path;
  the home folder by default), all set in the Add/Edit sheet. A page with no start command has no start, stop
  or state. Only the saved command runs, and saving follows the Tools page's rule (https or the machine itself, with the
  token and a same-origin request). `run device start NAME` runs the command detached, outside the run and any session
  and, on Linux, out of Runner Home's systemd service, so it outlives them; a second start says it is running already,
  and a command that ends within a second is reported at once with exit 1. `run device stop NAME` ends the whole process
  group it started (SIGTERM, then killed after 4 s) and nothing else. A small keeper process holds a lock, so running is
  never guessed from a reused pid; a process that leaves the group itself is not followed. The state is running, stopped
  (never started, stopped, ended with exit 0, or the machine restarted) or failed (ended with another exit code: the
  last 20 output lines are shown with every device's stored secrets hidden; if a stored secret cannot be read, no output
  is shown). The output is kept raw in `pages/` in the state folder, bounded at 1 MB. Removing the device, or changing
  its command, working directory or kind, stops it first, and the change is refused if it does not stop; a rename or a
  new address does not. On the Tools page a device with a web page shows its address and state (running, stopped or failed):
  stopped has Start; running has Use (the page opens in a new tab) and Stop; failed has Start and the last output lines. With no
  start command it has Use only. Over plain http Start and Stop are disabled, Use works. A Needs you item whose task names such a
  device in `needs:` (one this project uses) shows Use NAME on its card and sheet or, while it is stopped or failed, Open NAME in
  Tools, which goes to the device's Tools card.
- **Buttons.** A device has buttons too, the same as a tool's (### Shared tools), kept in devices.json: `op save`'s `buttons` list sets them (absent keeps them, `[]` removes them). A button runs in the device's working directory, the home folder by default; only a one-task device can be busy.
- **One task at a time.** A device marked so is held by one task. An agent's first `run device ssh` or `run device copy`
  (or `run device take NAME`, for a device reached another way) takes it, until that task's session ends or `run device release NAME`. The hold covers every project on this
  machine: another project's running task that names the device in `needs:` holds it too. An agent that finds it held
  gets exit 75 and runs `run wait-for NAME`.
- **Where it is kept.** `devices.json` and the secret files are in the state folder: ~/.local/state/agent-runner/devices
  on Linux, ~/Library/Application Support/agent-runner/devices on macOS, %LOCALAPPDATA%\agent-runner\devices on Windows.
  `AGENT_RUNNER_DEVICES` names another folder. It is refused inside a git repo, a worktree or a synced folder, so no
  secret is kept there.
- **Secrets.** The SSH private key, its passphrase and a password are write-only: the page takes them and never shows
  them again. It shows `set, changed <date>`, the key's fingerprint and its public key. A key pair can be made on the
  machine (Keys and password…); only its public key is shown, to add to `~/.ssh/authorized_keys` on the device. A
  secret is kept in the OS keyring only when an unattended run can read it: the macOS keychain, or secret-tool on Linux
  when the login keyring is open now, the run can read it with no display, and the user has no systemd linger (else
  the run starts before the person logs in). Otherwise it is a 0600 file in a 0700 folder. `AGENT_RUNNER_KEYRING=off`
  forces files. Windows does not support a stored secret: pick a `~/.ssh/config` alias there.
- **Saving.** The page saves only over https, or on the machine itself, with the run app's token and a same-origin
  request. That holds for any change on the Tools page, not only secrets. Over plain http the page is read only and
  gives the https link to open (Tailscale Serve gives one).
- **The commands.** `run device list` shows the devices this project uses, how each is reached and, for one with a web
  page, its state; `show NAME` one of them, with its page and state; `link` prints the Tools page's address.
  - `run device ssh NAME -- CMD`: one word is shell text for the device; several words go each as they are. The runner
    signs in itself: with a key from an ssh-agent of its own (the key held one minute), or a password through an
    SSH_ASKPASS helper. Neither is on the command line or in the environment.
  - `run device copy FROM TO`: one side is `NAME:path`, the other a local path; `-r` for a folder.
  - `run device take NAME`: has a one-task device until the task's session ends; `run device release NAME`: frees a one-task device before its task ends.
  - `run device start NAME` and `run device stop NAME`: start or stop an other device's web page command (see A web page), or a runner.toml tool's (### Shared tools); by agents of a project that uses the device.
- **Output.** What the command prints has each stored secret replaced by `[secret hidden]`, so a chat, a log or a
  transcript does not carry it. Only the exact bytes are caught: an encoded or transformed copy of a secret is not.
- **Host key.** The first host key an SSH device shows is accepted only by a person, on the page, from its fingerprint.
  A later change is refused and said so, and a person checks it on the Tools page before the device is used again.
  Changing a device's host, port, user or kind forgets the accepted key. A `~/.ssh/config` alias signs in with the config's own
  keys (its host key is accepted on the page too) and no secret of this runner's; nothing is copied.
- **Not a wall.** Agents run as the same OS user as the person. This keeps secrets out of chats, logs and transcripts
  by default, but it does not stop an agent that goes looking: it could read the secret file or keyring, or ask the
  ssh-agent while a connection is made. What would: run the agents as a separate OS user, with the secrets and a small
  service that signs in kept under the person's own user.

### Until checks

An until check is something this machine can read by itself, with no agent session and no model call, that a blocked
task can wait on. Written `kind:value`; four kinds, and anything else is refused: a free command is never taken.

- **`version:X.Y.Z`** is passed when the agent-runner serving this run is at least that. With no run up, the installed
  one counts.
- **`login:PROVIDER`** is passed when that login works, read from this machine's files and environment only. For
  `claude` that is Claude Code's credentials file: missing or expired is not yet, and an API key or token in the
  environment counts as passed. A login kept in the macOS Keychain, behind a wrapper as `[run] agent`, from an
  apiKeyHelper or with another provider (Bedrock) cannot be read, so the check cannot run. The others are read as `run login` lists them; an OAuth login that has expired and cannot be renewed is
  not yet.
- **`tool:NAME`** is passed when a shared tool or device is free; busy, held by a running task or missing is not yet; unknown cannot run.
- **`check:NAME`** is `[run.checks.NAME]` in runner.toml: exit 0 is passed, 75 not yet, anything else or a run past
  10 s cannot run. It runs in the main checkout, and its first output line is the words shown.

```toml
[run.checks.vm]
cmd = "tools/vm-ready.sh"   # exit 0 passed, 75 not yet, anything else cannot run
label = "the test VM"       # what the screens say; default: the name
```

Each answers passed, not yet or cannot run, with a few words saying why. An unknown kind or name is refused with what
there is, and a bad `[run.checks]` is named when the config loads.

**Blocking on one.** `done ID "msg" --blocked WHY --until CHECK[,CHECK]` and `plan block ID --until CHECK[,CHECK] WHY` block a task on until checks. Several are comma-separated, and all must pass. It is written `BLOCKED: (until version:0.66.0, login:codex) why`, and it is kept through the plan merge and sync. A bad check is refused before anything is blocked (`done` refuses it before its gate runs). `--until` with `--after`, and `--until` without `--blocked`, are refused too.

Such a task is not under Needs you, and no slot takes it. Plan, `plan`, `status` and the terminal UI say `waits for version 0.66.0`. `plan unblock` frees it at any time.

If the block holds a CONFIRM or DECIDE, the question is kept in the block, and the task comes back under Needs you when the checks pass. A `BLOCKED:` label is dropped, and it reopens for an agent.

Neither it nor a task that waits on it holds an `after: all` or `all above` task, since a release must not wait for a task that waits for that release's version. A task that names it in `after:` does wait.

A check that `[run.checks]` names only on the branch, or only in the main checkout, is taken.

**The run reads them by itself** (`until_watch.py`). While a run is up, every 2 min and off the scheduling thread,
each distinct check some blocked task waits on runs once, however many tasks wait on it; none runs with no task
waiting. When all of a task's checks pass it is reopened with a note of what passed (`plan.until_passed`), committed
in the main checkout as a merge's reopening is: holding the merge turn, left alone while TODO.md has edits nobody
committed, and tried again next round. It is logged once. With several machines on one plan, the plan is pulled
first, so the one machine where a version, login or tool passes reopens it once.

A check that cannot run for 30 min, or has not passed for 3 days, is one Needs you item (`until-<check>`) saying which
check, its last words and the tasks it holds, which `plan unblock` frees. It goes by itself once the check passes.
No agent session and no model call is made for any of this.

### Waiting for memory

Claude Code stops a background command when memory is low, and tells the agent not to start it again unless
asked. The slot's brief holds the person's standing go-ahead to run it again: the agent never asks, it commits what is
solid and runs `run wait-for memory`. `memory` is built in, so it needs no `[run.tools]` entry (a tool may not be
named `memory`).

- **The first stop.** With memory free again by then, the session keeps its slot and runs the command again.
- **Otherwise** the session ends and its work is kept on `waiting/<ID>`, as for a shared tool. The same session goes
  on first once MemAvailable is 2 GB over `min_free_mem_gb` (on a small machine 60% of total, when that is lower but
  still over the floor), and a pause of 1 min per stop (10 min at most) is over. Its message says memory is free and
  to run the command again. Where memory cannot be read (not Linux) only the pause counts.
- **What shows.** `waits for memory, 5.0 GB free, goes on at 6.0 GB` on the queue row, in `plan`, `needs` (below the
  needs list) and `status`. It is never a Needs you item. After 3 stops of one task, or a wait of 30 min, the run
  says so once in the log. The run is not idle meanwhile, and a restart keeps the wait. Stops are counted in
  `<notes>/<ID>.mem`.
- **One at a time.** Two waiting sessions go on at least 1 min apart.
- **New sessions.** Under `min_free_mem_gb`, or under what a waiting task goes on at (for its first 30 min), no new
  session starts (logged once per spell), and a slot's `done` gate
  waits for memory, at most 10 min, then runs all the same.

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

A run trims only before a task or a merge, so Runner Home also clears old build output of a project whose run is off, on its regular footprint walk (every 10 min): a runner worktree (`sN`, `merge`, `fixN`) that no process works in and whose build output nothing wrote for 3 days loses only recognised build output: folders git ignores as a whole with no tracked file, no symlink, marked by a `CACHEDIR.TAG` (not a venv or `node_modules`: installed, not built) or a `CMakeCache.txt` (sources not inside it); in a Cargo `target` folder only the profile folders (straight in it, in a target-triple folder, or in a `target` folder nested directly in it). A folder that holds a git repository stays (but for a CMake folder's `_deps` ones with no local change or commit), and so does one with a notes file (`.md`, `.txt`, `.diff` …) straight in a CMake or profile folder, or with a Cargo `target` folder in it that holds more than Cargo's own. The worktree, uncommitted files and every other ignored file stay. Each folder is looked at again just before it goes; this needs `/proc` (Linux) and what it freed is logged in Home's service log. There is no setting; the Clean button stays.

Memory is watched the same way (Linux), every 10 s, over the run's own processes: anything working in one
of its worktrees or started from a slot, the agents themselves aside.

- **A process past `proc_max_gb`** (`"auto"`: a quarter of the machine's memory) is killed, that process
  alone: its gate or session sees one test die and goes on, and the run logs `ended pid …` with the
  command. A test walking a looping tree held 52 GB in each of three gates at once before this. When the
  process was a test binary, the test it was running gets a `critical` task at the next merge.
- **Under `min_free_mem_gb` (4) available**, the run's biggest process (if it holds a GB) is killed instead, and no new session starts until there is more (### Waiting for memory).

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
the run view** (`agent-runner attach`, or the terminal you started `agent-runner run` in), or run `agent-runner stop` from anywhere. Either way
nothing new starts, the running tasks finish and merge, and then the run logs `run stopped (s)` (or
`run stopped (./run stop)`) and exits with 0. Typing `s` again before then takes the stop back, and tasks
start again. The run's page stays up after it exits: the page-only process takes it over (see The run app), except after a stop with suspend or shutdown, or with `[run] web = false`; `agent-runner page-only stop` ends that page.

`s!` + Enter (or `agent-runner stop --force`, Stop now on the run page, or `X` pressed twice in `agent-runner ui`) ends the whole run at once: every agent session, merge and merge gate or fix session under way is ended, and the run exits within a few seconds without waiting for any of them. Each ended session is queued to resume in its slot when a run next starts (its worktree stays as it was, nothing of it is merged). A merge ended leaves main, its checkout and the merge worktree as they were: a half merge the run began in the main checkout is taken back, a person's own merge there stays, and `task/ID` stays so the next run merges it again. The run waits only, for a few seconds at most, for a git command that is already moving the main checkout and for recording what landed. `[run] on_exit` still runs in each ended session's slot, but detached: the run does not wait for it or stop it, and the next run holds that slot until it has ended, stopping it past `[run] command_timeout`. `agent-runner stop --force` waits until the run's process is gone and prints `run stopped`; if the run has not begun the stop in 5 s (or is not gone in about 19 s), the command ends it itself (SIGTERM, then SIGKILL 2 s later), ends its sessions and gates, says so, and prints `run stopped`. With no run up it prints `no run is up here: nothing to stop` and exits 1. Asked from the run's own page the answer comes at once (`stopping the run now`), and a detached command does the stop.

The other keys, listed by `?` + Enter (and printed when the run starts), ruled off from the log:

| key | what it does |
|---|---|
| `p` | pause: no new tasks, and the run stays up; `p` again goes on |
| `u` | upgrade agent-runner now (`uv tool upgrade`, `pipx upgrade`, or a pull in a clone); the run restarts on the new version as with any upgrade. `[run] auto_upgrade` (on by default) presses it for you: when the update check (at the start, then every 6 h) sees a newer release, the run upgrades once no merge is under way, logs it, and restarts on the new version keeping what the keys set; never across a major version, nor on Windows, and with it off nothing restarts by itself. It works the same in a run started in a terminal (`agent-runner run`) and in the background (bare `agent-runner`) |
| `f` | force: start tasks past the session and weekly usage caps, as `--force`; `f` again: the caps hold |
| `+` / `-` | one slot more / fewer; a slot taken away finishes its running task first |
| `slots N` | N slots (`+N`, `-N`: that many more or fewer) |
| `z` | suspend the computer once the run stops, or when it goes idle as `--suspend` would; `z` again: off |
| `x` | the same, shutting down (`--shutdown`); `x` again: off |

With no run up, the TUI shows only the Start the run and Fix up controls, as the page does; Force and Caps back on show by run state (`ui_model.controls_shown`).

After a stop, power goes off at once, with no idle grace. `agent-runner stop --suspend` (or `--shutdown`) does
the same from anywhere, through `.runner/POWER`. A line the runner does not know is echoed back with
the key list. Each key is acted on as it is typed; ending sessions and adding a slot wake the loop at once.

**The same from any terminal, or a remote session.** Each key has a command, so nothing needs the run view:
`agent-runner pause` (`--off` goes on), `force` (`--off`), `slots 4` (or `+1`, `-1`), `stop --undo` (takes a
gentle stop back), and `key <k>` for any other (`key z`, `key u`). Unlike a typed key, `pause`, `force` and
`stop` say which way they go, so asking twice does not undo them. They append to `.runner/KEYS`, which the
run reads every quarter second, also in a long pass, so it acts and rewrites `.runner/STATE` within a second; with no run up they say so and exit 1.
`agent-runner status` is short enough for a phone: whether a run is up and what the keys have set, each
slot's task id, title and minutes running (from `.runner/STATE`, rewritten every pass), what is merging, the
last five merged, blocked or parked tasks from `run.log`, and the account's usage as the caps last read it.
A Claude login under 3 days from its end, ended, or missing adds one line, here and in `agent-runner ui`, naming `claude auth login` (not with an API key or token in the environment, on Bedrock, Vertex or Foundry, with another ANTHROPIC_BASE_URL or an apiKeyHelper, or for a `[run]` agent other than claude; on macOS, where the login is in the Keychain, a missing file is no warning). With Runner Home running, the same warning is also pushed once a day per machine (local date) as a device alert in the events of each running claude project, and `since --follow --needs-you` sends it; the day is kept over a Home restart, and nothing is pushed once the login is renewed. The run page and Runner Home (All projects too) show the same warning as a banner under the top bar, with one button, Log in again (F126b). It opens a sheet that runs `claude auth login` in ttyd on 127.0.0.1, served at `/t/TOKEN/login/` by the run page and, with no run up, by Runner Home (its `/terminal/login`); the command is fixed and the key is required even on a trusted network. The sheet has the sign-in link as `1. Open the sign-in page` and a field `2. The code the sign-in page gives you` with Send code. The login stays up 10 minutes after the last browser leaves (one held socket to ttyd, `login_hold.LoginHold`), so the code matches, and Home does not restart on an upgrade during it. When the command ends the sheet says `Start again`; without ttyd it says how to install it. The banner clears by itself after a new login, and the sheet closes with the toast 'The login is renewed': the run page for its run (`[run] agent` claude only), Home for its machine (only when one of its projects has `[run] agent` claude).
`-n 30` adds the end of `run.log`.

Both write `.runner/STOP` (with who asked; `.runner/STOP.force` for a stop now), and the loop checks that
file on every pass, so `s` can take back a `agent-runner stop` and the reverse. A daemon thread reads the runner's terminal (it works on Windows
consoles too) and only starts when stdin is a terminal. A STOP
file left behind by a run that was killed is cleared when the next run starts.

A merge a run was in the middle of is adopted by the next run too, like the slots' sessions. Its gate
runs in a session of its own (`.runner/gates/<key>.json`), and a fix or repair session an older run left
in its master window recorded itself in `.runner/master.json`; both outlive the runner. The restarted run waits for them,
keeps what they made (a passing gate per tree and gate command in `.runner/gates/`, a session's commit
under `refs/agent-runner/held/<ID>/`), builds the merge again and reuses them instead of doing that
work a second time. The startup log says `<ID>: its merge was under way when the last run ended;
adopting it`, or `<ID>: finished, not merged yet; merging it now` for a branch that only waited its
turn.

While a restart on changed code is due (see New version), no new merge starts: a finished task, a branch finished outside the slots, or an undo waits, and the merges under way finish. The restarted run takes the held ones up. They start at once instead when the run is stopping, main is not checked out or has `agent_runner` edits under way, or a merge under way waits for a person (edits in the main checkout, a wrong `[run] agent`). A release (a merge under way may wait for it) and a task with no commits are not held; a drop, change or restyle of a held task starts its merge, which answers it.

### Fix sessions

A conflict the line join cannot resolve goes to one fresh session, run with the conflict in place. By
default (`[run] fix_ahead_max`, 2) that happens before the merge lock is taken: the task's branch is merged
into the shared branch's head in a fix worktree of its own (`fix1`, `fix2`, … under `[run] home`, kept so their
builds stay warm; at most `fix_ahead_max` at once, the others waiting a turn, and each waiting on
`before_start` as a slot does), the session commits the resolution there, and the runner keeps it as
`refs/agent-runner/fixed/<ID>/<sha>`. Other tasks merge and gate meanwhile. The task then takes the lock with
that merge, which goes in clean unless the shared branch touched the same lines again in the meantime: then
it goes back out for another, smaller fix. Its third try fixes under the lock, in the merge worktree. It runs as
`claude -p`. Its prompt (`FIXER` in `runner.py`) includes the tail of the ledger. It either
commits the resolution or runs `git merge --abort` and states why; its output goes to
`.runner/fixer.log`. It is capped at 30 minutes; ahead of the lock that holds up only
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

When a batch (`batch_max` above 1) fails the gate, the runner first looks for the task that breaks it by
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

Tasks that finish while a batch is in its gate do not wait for it to end (always on). They are
merged on top of the merge under test in a second worktree (`merge2` under `[run] home`) and their gate starts
beside that one. When the first batch lands, the next one's turn finds the same merge built ahead and
waits for the gate already under way on that exact tree, so two batches cost about one gate's wait. If
the first batch fails or the branch moves another way, the merge built ahead is dropped and its gate
stopped. Its conflicts get only the line join: one that needs a fix session waits for its own turn. The
first gate in merge2 builds from cold, and merge2 has a build directory of its own.

A task that clashes with finished tasks only by files, and only with ones that are all in one merge under way
(the one under test, or a merge built ahead on it whose own gate has not failed), starts at once on top of
that merge in its own worktree, instead of waiting for the gate (F198). Not for an `(alone)` task, a release,
a part held back by the sibling rule (a part that clashes with a sibling), a task in an ordered section, an `after:` wait, a task resuming after `run ask` or a shared-tool
wait, or one that also clashes with a running task, or one filed on main after that merge when the merge's plan has no line for it (a merge built ahead that has the line will do). A finished task not yet in any merge still holds its
files. Which merge it started on is in `<notes>/<ID>.stacked`, which survives a restart; its brief says so
and which diff is its own. It lands only after that merge is on main: when it finishes it waits (log: "S2:
finished; it lands after S1, on whose merge it was started"), then merges as any task. If that merge is
refused, or built again as another commit, once those tasks' merges are over its own commits are moved onto
main alone (`git rebase --onto`; when they do not apply, as one commit, joined or given to a fix session) in
a fix worktree, and its remote task branch replaced. If they cannot be moved it is parked as `wip/<ID>`
whole, and its next attempt is told which of those commits are its own. No unlanded task's commit reaches main. If the run stops first, `task/<ID>` waits for the next run.

A tested merge that cannot land because of uncommitted edits in the main checkout to files it changes (or
anything staged there, which git refuses to merge onto) waits 10 minutes, then gives the merge lock back
and stays `task/<ID>`; it is merged again once those files are committed. It is never parked for that.
With `[git] land_edited = "wip"` the edits go to a `wip/main-checkout-<time>` branch (and a stash) after 3
minutes instead; the log line names the files and `take --here`, and `plan claims` and `run --dry-run` list
those branches until someone deletes them.

A merge skips the gate only when `task/<ID>` is the very tree `done`'s gate passed on (recorded as
`refs/agent-runner/tested/<ID>`) and the merge differs from it only in `[run] untested` files. After `done
--no-test`, commits made after `done`, or a session that never ran it, the merge is tested. With `[run]
done_test` set, the commit `done` made is also marked `refs/agent-runner/done-test/<ID>`, which a merge does
not count as a gate pass: the merge runs `test` (or `test_since`) even on that exact tree.

Docs-only changes skip the gate, decided by the diff and not the task's letter (a D task that touches code is
tested; a B fix that only edits the README is not). When every file a merge changes on the shared branch (all
its tasks, the plan's archive commit, a remote's commits taken in) matches `[run] docs_files` (default `*.md`
and `docs/**`; `!glob` takes one back; a `pyproject.toml`, `package.json` or `Cargo.toml` whose every changed
line is its `description` counts too, F494), the merge runs `[run] docs_check` instead, if one is set (a link or
anchor check), and the log says `docs only, gate skipped`; a failing docs check fails the merge. `done` does
the same with the files its worktree changes since the shared branch (commits, edits and new files): it prints
`docs only, gate skipped`, so a session that only edited docs or the plan needs no `--no-test`. It records no
tested ref then; the merge decides by its own diff. With `[run] done_test` set, a docs-only `done` runs it in
place of skipping (then `docs_check`, if set) and prints `done_test passed`; it still records no tested ref,
so a docs-only merge skips the gate as before.

## Keeping sessions lean

Whatever `[run] rules`, CLAUDE.md, AGENTS.md and their `@` imports hold is
re-read on every turn of every session, and agents keep adding to it (opentennis's grew to 28 KB, half of it a
code map each task appended a line to). Leave the rules there; put code maps, how-tos and background in
`[plan] lookup` files, one `## section` each, with a one-line pointer in the rules (`agent-runner plan hst-base`,
`agent-runner plan "Driving the game"`). A heading named exactly that wins over one that only contains it.
`agent-runner context` shows what every session loads, biggest sections first, against `[plan] context_kb` (12 KB);
`run` warns at start when it's over, and the prompt tells agents where new reference material goes.
Big files get a map too: `[plan] outline` runs only for files on the task line that are over 300 lines, and all the outlines in one brief stay within 2 KB. When they don't fit, each file gets an even share and shows lines picked evenly through the file, labelled `outline (trimmed evenly: N of M lines)`; a note after the files gives the command for a whole one and how many have none. `tools/outline.py` (stdlib only) lists functions, classes, methods, section comments and headings, with line numbers, for Python, .js, .mjs and Markdown.

### Lessons

With `[plan] lessons = true`, `<plan dir>/LESSONS.md` holds what a project's agents learned, one line each: an id
taken from the text, at most 200 characters, and the files or globs it applies to. `plan lesson add "TEXT" --files
a,dir/**` adds one, `plan lesson list` lists them, and `plan lesson drop ID "why"` drops one: any agent shown a
wrong lesson may, with a reason. A brief shows the lessons whose files meet the task's `files:`, a plain path
before a glob and a longer one before a shorter, at most 8. A lesson whose files are all gone from the tree drops
itself when a brief is made, and says so. Dropped lessons move under `## Dropped` with the date and the reason.
Two branches that each add a lesson get different ids, so list the file in `[run] joinable` and their adds join
by line, as this repo does.

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
  When those commits are all the runner's own merges (each passed its gate) and touch none of the merge's
  files nor `runner.toml`, nothing is tested again ("moved only by gated work on other files"); a hand
  commit on the shared branch is always tested.
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

The built-in prompt is the same text for every task up to its last part (F103): the fixed runner brief comes
first and says `<ID>` where the task's id goes, then the task's id, an earlier attempt and `prompt_extra`,
then the task's own paragraphs (concept, review, …) and policies, and the task's brief last. So every slot's
first turn starts with the same words and the model's prompt cache is reused across slots and tasks. A custom
template (`[run] prompt`) keeps the order it gives.

Each session also gets `AGENT_RUNNER=1`, `AGENT_SLOT=<n>` and anything `[run] slot_env` adds in its
environment, so your tools can tell slots apart, for example to give each one its own port or emulator
instance. `AGENT_RUNNER_WORKTREE` names the slot's worktree: while it is set, plan writes (`plan add`,
`note`, `tick` and the other edits) and `done` refuse, with nothing written, when the current directory is in
another project, and say to run the command from that worktree (B103). One exception (B785): when a
control session's question (its `DECIDE:` line, filed as a task when the run closed the session) names another
project by its folder name and the person's answer is a yes (a word of yes, or one of the question's options that is not a no), the slot on that task may run `plan add` in that
project's checkout. A project that only the options name counts only when the answer names it. The other plan writes and `done` there stay refused, as do any other task's slot and any
project the question does not name; a later "do this instead" from the person withdraws it.

`include_task_id_in_commit = false` tells sessions to omit the task ID from the commit subject; `done` also
removes a leading `<ID>:` if a session includes one anyway. The default is `true`. An old `comment_policy` is ignored: write its wording in `prompt_extra`.
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
4. `.runner/run.log` is the full timeline. `.runner/slotN.log` is what each slot's terminal showed, and
   `.runner/fixer.log` is what the fix sessions decided.
5. The `journal/` entries' **Not verified** lists tell you what to check yourself.
6. `agent-runner cost` shows where the workers' tokens went: each kind of tool call (`git log`, `sed`,
   `python3 tools/x.py`, `read`), by its results' size times the turns they stayed in context, since that is
   what a session pays for. A command that tops it is worth an outline (`[plan] outline`), a quieter
   flag, or a line in the prompt. It reads the last 7 days of this repo's slot and merge sessions, Claude
   and Pi (`--days N`, or name transcripts). `agent-runner cost --files` counts the same way per file read
   (a Read, or the files a `cat`, `head`, `tail`, `sed`, `grep` or `rg` printed), with how many of those
   reads were re-reads in the same session, so the top rows name a file worth splitting or an outline worth
   adding; below it, what exact-repeat commands (the same Bash line run again in one session) added after
   their first run. A file counts under its bare name (two `__init__.py` share a row), a read of another
   range of a file already read counts as a re-read, and a line that printed several files shares its
   result among them evenly.


## Filing tasks from a chat

A Claude Code session in your main checkout, beside a run, can feed it: you say what you saw, it finds the files
and files the task, and a slot picks it up. Put the rule in your `CLAUDE.md` so every session follows it:

```markdown
## New asks go to the plan

When I report a bug or ask for a feature, don't fix it here. File it with `agent-runner plan add`:
- the kind letter from `agent-runner plan kinds`, and my words quoted with the date;
- `--files` naming every file the fix will touch (look them up first), `--after` if it needs another task;
- what "done" looks like, so the agent can test it. Long context goes in plan/tasks/<ID>.md.
If `plan add` says it looks like an open task, `plan note` that task instead.
Only do the work here when I say "do it here".
```

The run app's chats (control sessions) follow this rule already.

## Commands

```
agent-runner                           the run in the background (a detached process, its slots hidden), the
                                       prompt straight back; `help` prints the usage
agent-runner attach [run|sN|cN]        the run view (its log, live, and its keys; Ctrl-C leaves it), or a
                                       session's own terminal (Ctrl-b d detaches; Windows 1809 and later too;
                                       before 1809 the hidden console)
agent-runner control [N]               a new control session in this terminal, blank (no opening summary)
agent-runner control --new [N]         another one beside the run, without taking focus; prints its claude.ai/code link
agent-runner control --new --no-wait   the same, returning once it starts ("control N is starting in a hidden terminal"),
                                       without waiting for its claude.ai/code link
agent-runner wip [show|restore|drop NAME]  your main-checkout edits a merge moved aside (wip/main-checkout-*): look at one, put it in a take worktree, or delete it
agent-runner pitch [approve|no PITCH]  landed work that waits for a yes to be pushed (### Approve to push): approve
                                       it, or undo it with `no`
agent-runner since [WHEN] [--all|--follow]  what landed, started or got stuck since the last look (or WHEN:
                                       2h, yesterday), as a digest; --all every event; --follow each new one live
agent-runner plan [...]                the task list as a tool (agent-runner plan help)
agent-runner done ID "MSG" [--blocked WHY [--after X,Y | --until CHECK,…]] [--artifact URL] [--no-test] [--named ANSWERS]
                                       --artifact: a concept's page (a K task without it takes the URL that
                                       `publish-page` recorded; --page FILE names its copy)
                                       --named: answers the removal check's list (**The removal check** above)
agent-runner review [ID] [--base BRANCH]
                                       the spec review before `done`, a fresh one-shot on [models] review
                                       (**Spec review one-shot** above); its findings print
agent-runner run [N|once] [--dry-run] [--model M] [--idle S] [--stall S] [--pause S] [--force] [--shutdown|--suspend]
agent-runner stop [--force] [--suspend|--shutdown]
                                       finish what's running, start nothing new, exit (or s + Enter in the
                                       run view); --force ends the whole run now (sessions and merges
                                       under way; see Stopping a run), the sessions to resume next run
agent-runner take ID [--merge|--drop]  one task in your own session or a subagent: a worktree on task/ID
                                       and its prompt; a run keeps off it. --merge after `done` there
agent-runner take "TEXT" --kind K [--files A,B] [--here]
                                       queue it (as `plan add`) and take it in one step; --here (also with
                                       an ID) moves the main checkout's uncommitted edits into the worktree
agent-runner resume ID...              continue each task's last session in its slot, once that slot is free
run wait-for TOOL                      a slot's agent, when a shared tool is busy or missing, or a command was stopped
                                       for low memory (`memory`): its session ends and its work is kept; the same
                                       session goes on once it is free (### Shared tools, ### Waiting for memory)
run device list                        the devices this project uses, with how each is reached and a page's state
run device show NAME                   one device: its description, how it is reached, its page and state
run device ssh NAME -- CMD             run CMD on a device (SSH; the runner signs in); exit 75 while it is held
run device copy FROM TO                copy to or from a device (one side NAME:path; -r for a folder)
run device take NAME                   have a one-task device until this task's session ends
run device release NAME                a one-task device is free for other tasks again, before its task ends
run device start NAME                  start a device's or a runner.toml tool's web page command, detached; a second start says it is running
run device stop NAME                   stop what `run device start` began (its whole process group)
run device link                        the Tools page's address (a run app must be up)
agent-runner cost [--days N] [--files] where the workers' tokens went, by kind of tool call (--files: by
                                       file read, and exact-repeat commands)
agent-runner home [slots|plan]         where this project's worktrees and plan clone live
agent-runner speech [install [kokoro|piper|whisper]]
                                       run speech's voices (Talk reads with them), or installs one; whisper is Recorded's engine
agent-runner context [--check]         what every session loads, by file and section; --check fails over budget
agent-runner help order                how to make one task wait for another
agent-runner --version
```

`./run …` in a clone is the same CLI. `--no-test` skips the gate and `[run] done_test`.
`--shutdown` powers the computer off once no task is running or merging and no open task can start, after
120 s idle; new work in that window cancels it. On Linux it runs `systemctl poweroff`, which needs the
logged-in session's polkit permission; if the command is refused the run stays up.
`--suspend` is the same but puts the computer to sleep (`systemctl suspend`, `pmset sleepnow` on macOS,
`SetSuspendState` on Windows, which hibernates instead where hibernation is on). The run stays: when the
computer wakes it carries on, and it suspends again only after it has had work and gone idle again.

`plan` and `done` work on the checkout you're in (the agent's worktree). `run` always merges into the
main checkout. Set `AGENT_RUNNER_REPO` to use a repo from outside it.

## runner.toml

Every key is optional. Without a `runner.toml` you get the plan in `plan/`, no gate, 3 slots, and merges that
stay local: with no gate, `[git] push_merge` pushes a merge only when a settings file sets it. A worktree
without its own `runner.toml` (because it's git-ignored) reads the main checkout's.

With no settings file at all (no `runner.toml`, no `AGENT_RUNNER_CONFIG` file, and no gate or `push_merge` in
`runner.local.toml`), the run picker and its launcher, the run page's Run card, Home's Overview and the
TUI's Status panel say "no settings found, so no test gate and nothing is pushed". A run that is up says what
it itself found (its STATE).

A `[run] agent` that is wrong in a settings file (a removed `pi` or `copilot`, empty, not text, or a command not found on this machine) does not stop the run app or Home: the settings load, and the places above say the problem and its fix in one line. While it is wrong, in a settings file or in what the run itself loaded, the run stays up and starts no agent session: no task, no resume of a cut-off one, no fix or repair session, no control session, control server or one-shot page publish, and never another agent instead, also when the run still has a good agent loaded from before the wrong value was saved. Running sessions, a control server that is up included, go on. A run that is up says what it itself found (its STATE), and a wrong value saved by hand is said then too; the run log says it once, and once more when it is right. `run control`, `control --new`, and + Chat and Resume on the run page answer with the problem and its fix. Finished work still merges; a merge that needs a fix or repair session waits as `task/<ID>` (not parked, so it stays for the next run if the run stops) and goes on once fixed. Control sessions a shutdown cut off and messages held for a usage limit wait too. Everything starts again on the next tick once the value is fixed or the program installed, with no restart.

If `AGENT_RUNNER_CONFIG` names a file, the settings come from that file instead: from its
`[agent-runner]` table (`[agent-runner.run]`, …) if it has one, else from its top level. This lets a
project keep them in its own config file (see [docs/SETUP.md](SETUP.md#your-own-cli-for-tools-only)).

**`runner.local.toml` is one machine's settings.** Laid over the shared file key by key, table by table, it
changes what one person needs without editing what everyone shares: a lower `weekly_max` for a smaller
plan, fewer `slots` on a laptop, another `model`. `run` creates it in the main checkout when it is missing,
all comments so it changes nothing, and changes it only when a person saves a This device value in the run app's
Settings (one key on its own line; its comments stay); it keeps it out of git through the
clone's `.git/info/exclude`, so neither a `git add` nor another person sees it. Worktrees read the main
checkout's.

```toml
# runner.local.toml
[run]
weekly_max = 50
slots = 2
```

A run that is up reads `runner.toml` and `runner.local.toml` again when either changes, from the run page's Settings or by hand, between its ticks (about every 10 s), with no restart. Running tasks keep their own model and budget caps (`[run] task_tokens`, `task_usd`). A file that does not parse, or a bad value, changes nothing: the run keeps the old settings and the run log says why. `[run] remote` or `control` off ends the control server and on starts it; `slots`, the usage caps, `silent` (also for control sessions and the control server that are up) and `auto_upgrade` apply at once. `run once` keeps its one slot and `run --model` its model. Nothing is read while a merge is moving the main checkout. The keys that apply on the next run only are listed under Restart the run above.

```toml
[plan]
dir = "plan"              # TODO.md, DONE.md, tasks/<ID>.md; outside the repo, one copy for every worktree
repo = ""                 # the plan in its own git repo (see "The plan in its own repo")
journal = ""              # e.g. "journal": per-task folders, the newest pasted into the brief
journal_layout = "dated"  # or "id": one folder per task, journal/<ID>/, a retry dated one folder down
brief_extra = ""          # a command whose output ends the brief; {id} is the task id
outline = ""              # a command printing one file's outline; {file} is the path, e.g.
                          # "python3 tools/outline.py {file}": the brief shows it under each file the line names over 300 lines
lessons = false           # plan/LESSONS.md: what agents learned per file, shown in briefs (`plan lesson`; see "Lessons")
kinds = {}                # id prefix -> kind of work, e.g. { B = "bug", N = "netplay" }; `plan add` keeps to it
need_files = false        # `plan add` refuses a line with no files: and no test: field (else it warns)
lookup = []               # more files `plan <name>` searches for a heading, e.g. ["PLAN.md", "plan/guide/*.md"]
context_kb = 12           # budget for what every session loads (`context`); `run` warns past it, 0 = never
glossary = "GLOSSARY.md"  # the project's glossary (`agent-runner glossary`): seeded by the first control session,
                          # named in every brief; false = off (no file written, briefs skip it)
                          # a conflict in it is joined by entry on its own (Merge, step 5); a [run.join] entry for it wins

[git]
master_branch = ""        # optional local shared branch; must exist and be checked out
# empty uses remote HEAD, then main/master/trunk, then the current branch
push = "origin"           # where finished work goes; false turns every push off
push_merge = true         # push the shared branch after each tested merge
# with `[run] test` empty (no gate) only when set here: the default never pushes untested merges
land_edited = "wait"      # a tested merge held by uncommitted edits in the main checkout: "wait" for them, or
                          # "wip": move them to a wip/main-checkout-<time> branch and land (see Stopping a run)
pr = false                # true: a finished task is a pull request on GitHub that a person merges (### PR mode)
pr_max = 5                # PR mode: no new task starts while this many pull requests are open; 0: no limit
no_push = false           # true: the runner pushes nothing and git refuses a push in every session (### No-push policy)

[ui]
theme = "ryha"            # the terminal UI's (`ui`) colours: ryha (black, red accent), omarchy
                          # (~/.config/omarchy/current/theme/colors.toml, else ryha), terminal (the terminal's own
                          # 16 colours and background), light. The run app ignores it: it follows the browser's
                          # light or dark setting
chat_quiet = "6h"         # a chat that needs no reply, with nothing said in it for this long, is grayed at the bottom
                          # of the run app's Chats (a pinned or a renamed one is left alone); false: off
trusted_networks = []     # CIDRs, or `tailnet`, whose devices open the run's page without its key (?t=); [] (default): the key is always needed

[models]                  # the model each type of work runs on (see Models per role below)
provider = "claude"       # the provider of every model here written as a bare name; see Model providers
code = "opus"             # a task's own session when its kind has no model below
review = "opus"           # the spec review before done: the `review` subagent (Claude Code tasks on claude); else a one-shot (`run review`)
fix = "opus"              # merge-conflict fix and repair sessions
docs = "haiku"            # the `docs` subagent: CHANGELOG, docs, README, journal and plan-text edits; false or another provider's: none, the task's session writes them
control = "opus"          # control sessions (c2, c3, …)
feed = "haiku"            # the run page's claude.ai copy (the one-shot that publishes it); another provider's: the local copy only
audit = "opus"            # an audit task's session ([run] auto_audit, or one added by hand); see Auto audit
kinds = { F = "opus", B = "opus", T = "opus", V = "opus", K = "opus", D = "sonnet", C = "sonnet", R = "sonnet" }
                          # a task's own session by its kind (the id's letters: F105 is F); see Models per kind
sizes = {}                # a task's session by its size (`plan add --size simple`), e.g. { simple = "sonnet" }; empty: sizes ignored; see Models per kind
local = false             # allow a local provider (ollama, or a provider url on localhost or a private address); see Model providers
providers = {}            # the repo's own providers, [models.providers.<name>]; see Model providers
fallback = []             # '<provider>:<model>' to go on with when a provider hits its cap, in order; see Fallback chain
tiers = {}                # [models.tiers.<provider>]: what opus, sonnet and haiku mean there, over the built-in ones; see Model providers

[run]
test = ""                 # the gate, run by `done` and on every merge, e.g. "make test"
test_since = ""           # a merge's gate on what changed since {base}, e.g. "make test-since REV={base}"
done_test = ""            # what `done` runs before its commit in place of `test`, on a docs-only diff too, e.g. "make build && make audit"; a merge still runs `test`; "" = `test`
full_every_hours = 24     # with test_since: the whole `test` once none has passed for this long; 0 = never
slots = 3
include_task_id_in_commit = true
agent = "claude"          # the Claude Code executable a session runs: claude, or a wrapper around it
engine = "terminal"       # terminal = an interactive session in a hidden terminal (the default for now); stream = headless claude -p, stream-json in and out
lean = true               # sessions get Bash/Read/Edit/Write/Artifact only, no MCP servers or user settings
remote = "auto"           # control sessions on Remote Control, and a control server to start more from claude.ai/code or the Claude apps; Enter in the run view opens it. auto: on where it can work (see Control sessions); true/false force it
remote_slots = "open"     # the slots in the Claude apps. open: listed once opened from `agent-runner ui` (Sessions, session tab),
                          # the run keeps a claude.ai copy of the run page. always: every slot its own
                          # entry ("<task title> · <repo> s2 · B646"), no copy
web = true                # the run app (see The run app), served by the run on web_port for the LAN/Tailscale, or on
                          # 127.0.0.1 only behind Home; its address, with the token it needs, is in `status` and the run
                          # log; false: off
web_port = 8770           # where the run app is served; a port set here stays open on every interface (unless it is
                          # Home's own port)
web_open = 'everywhere'   # who opens a run app Runner Home does not: everywhere = every interface (LAN, Tailscale); here =
                          # this machine only (127.0.0.1): its localhost link with its key, and no Tailscale Serve rule.
                          # Per machine (runner.local.toml); another value stops the load. With Home, Home's address rules
                          # (F454a)
web_https = true          # the run app's https address on Tailscale (see The run app), on web_port+1 through `tailscale serve`; false: none
silent = false            # phone pushes from those sessions after each one's start push (that one cannot be stopped): true = none, false = Claude Code's usual
control = true            # the run opens no control session of its own; true: it reopens the ones a shutdown cut off and, with remote, keeps the control server up; false: neither (`agent-runner control` still works)
control_idle = "3h"       # close idle control sessions (none is protected) once quiet this long, Claude spoke last, its last message does not end on a `DECIDE:` line (that one waits for `control_ask`), and nothing runs in it (a background task or Monitor; the needs-you watch does not count): process ended, controlN.pid removed, transcript kept (`claude --resume <sid>`); false: none closed idle
control_ask = "2h"        # a last message ending on a line `DECIDE: <question>` (the brief asks the session for one only when work waits on the answer): after this long it is filed under Needs you as a DECIDE item (an F task with the question + the session link; answering it reopens the task for a run to carry on), then closed; false: such a session stays open and nothing is filed
auto_upgrade = true       # upgrade by itself when a newer release is out, as `u` does, once no merge runs; the run restarts on it, and a source checkout restarts as soon as its agent_runner code changes, holding new merges meanwhile (false: nothing restarts by itself, not even on an installed version; `u`, `agent-runner upgrade` and Restart the run still do)
install_skill = true      # keep the `agent-runner guide` skill in ~/.claude/skills and the user-level SessionStart hook (the control brief in a runner repo's main checkout) in Claude Code's user settings, from every agent-runner command, for sessions a person starts; false: neither is written
rules_pointer = true      # a run adds one line to the rules file (`rules`, else AGENTS.md or CLAUDE.md, never created) pointing every session at the agent-runner skill, committed on its own; never into a file with uncommitted edits or mid-merge; false: never
questionnaires = true     # a choice with more than one question, or whose answers each need a why, is asked as a pick sheet (<notes>/sheets/<ID>.json, a page made with `agent-runner sheet <ID>`); Needs you shows one line and its link; false: a plain DECIDE
grill = "ask"             # control sessions ask rounds of numbered questions before queueing: "ask" = when the person says grill me / poke holes; "big" = also on big vague asks; "off"
voice = ""                # the person's wording file (`agent-runner voice`), read by control sessions and task agents; "" = ~/.config/agent-runner/voice.md (a .runner/voice.md with lines overrides it for this project)
voice_learn = "ask"       # "ask": a session that had to say something again offers one wording line to add; "off": lines are added only when the person says so
review = true             # before done, a fresh subagent (or `run review`, a one-shot, on another provider's model) reads the diff against the task's brief (spec only: missing, unasked, wrong); the commit ends "review: …"; false: no review
review_min_lines = 50     # a diff smaller than this (changed lines) skips the review, unless the task has a long form (plan/tasks/<ID>.md)
context_warn = 150        # k tokens: a slot session whose context peaked past this says so in its exit line and in `since`, with what filled it ("B32 peaked 168k (over 150k): runner.py 61k, test_runner.py 22k"), and is told once, as a turn ends, to commit what is solid, file the rest as a part and finish; soft only, nothing is stopped; 0 = off.
split_files = true        # free slots that start nothing while 3 or more ready tasks wait for one file: the run queues one critical (alone) task that splits it; false = off (F200b)
task_size = 10            # a task bigger than this is split: its size is its code files (`docs_files` not counted) + 2 per numbered outcome + 1 per 400 characters of text (a long form is not read); `plan add`, `edit`, `note` and an approval say so, and its session splits it first; 0 = off (F177)
task_tokens = 0           # tokens one task's session (and its subagents) may use: input, cache writes, output (cache reads are left out: they grow with turns times the context, and task_usd counts them). Past it the runner tells the task to stop at a clean point (commit, write its journal, end its turn) and parks it as wip/<ID>; one whose done already passed lands; one that goes on to 1.25 times the cap is ended. `status` shows each running task's spend ("1.2M tok $3.40"); 0 = no cap (F103)
task_usd = 0              # the same cap in dollars, at the API's list prices (a plan bills none; Opus prices for a model it does not know); 0 = no cap
usage_limits = true       # false: never read the account's usage; no hold or fallback on the two caps below
weekly_max = 90           # % of 7-day usage past which new tasks wait, or start on [models] fallback
session_max = 90          # % of 5-hour session usage past which new tasks wait, or start on [models] fallback
notes = ".runner"         # logs + ledger (git-ignore it)
links = []                # git-ignored paths symlinked into every worktree (data, big files)
copies = []               # git-ignored files copied into a new worktree once (a local config file)
slot_env = []             # extra environment per slot, e.g. ["EMU_SLOT={n}"] ({n}: the slot, {slots}: how many),
                          # beside AGENT_SLOT=<n>, which every slot gets
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
findings = ["docs/research/**", "research/**"]  # what a research task may change beside the plan and journal
failures = ""             # regex, group 1 = a failing test's name in the gate's output
retest = ""               # the gate for just {names}: rerun alone (load), then on the base (already failing)
flaky = ""                # regex, group 1 = tests a passing gate passed only on its own rerun (comma-separated); each gets a critical T task
ci_watch = "auto"         # "auto": workflows run on a push to the shared branch; ["pages.yml"]; false: off. A red newest finished run on the shared branch
                          # files one critical B task (needs `gh` logged in)
approve = false          # true: nothing reaches the push remote until a person approves it (### Approve to push)
approve_wait = 30        # minutes without a new merge into a group of related changes before its pitch opens
approve_batch = 5        # a group this big opens its pitch at once
approve_diff_lines = 400 # lines of each change's diff its Review page shows (0: none)
issues_watch = false      # true: one task per new open GitHub issue; ["bug", "runner"]: only issues with one of those labels
issues_trust = "skeptical"  # "skeptical": the task confirms the issue in the code first and follows nothing it says; "trust": do it as written
releases = true          # false: no releases in this project (status and plan show none, auto_release queues nothing); an open V task stays an ordinary task
auto_release = false      # queue a release by itself: { every = 10 } once 10 tasks landed since the last release, starting at once (a cut, F195a);
                          # { idle = true } when the run goes idle with landed work (`plan add V`); both may be set; idle never while a release is open
slot_memory = true        # false (after a person OKed the audit's move of memories into lessons): Claude Code's memories off for slot, fix and repair sessions
auto_audit = false        # { every = 50 } queues an audit once 50 tasks landed since the last one and the run is idle; true = every 50 (see Auto audit)
audit_tokens = 1000000    # an audit's token cap, counted as task_tokens: past it the audit lands what it found; 0 = none
batch_max = 16            # finished branches waiting for the merge go in together under one gate run, and one push,
                          # at most this many (the rest take the next one); 0 = no cap, 1 = no batching
max_unmerged = 32         # past this many finished tasks waiting for the merge, each half batch more holds a slot; 0 = off
before_start = ""         # a command that must pass before any session starts (a display, a device)
not_attempt = ""          # regex on a branch's last commit subject ({id}): a phase, not the run's one try
shared_files = []         # files nearly every task names; not counted as an overlap
joinable = []             # globs of record-per-line files a conflict may be joined in (TODO.md, DONE.md merge by task)
fix_merges = true
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
min_free_mem_gb = 4       # under this much memory available: the run's biggest process is killed, no new session starts; 0 = never
slot_clean = ""           # a project's own clean, run instead of the trim and the full git clean -ffdXq
command_timeout = 3600    # s the gate, a retest, a hook (join, before_start, on_exit) or `done`'s gate may run: past it, failed
needs_order = "oldest"    # what waits on a person (Needs you): oldest first; "newest" first; "plan": TODO.md's order

[run.join]                # glob = a command that joins a conflict in that file itself:
# "data/addresses.txt" = "./tools/join {union} {out}"   # also {ours} {base} {theirs} {file}; exit 0 keeps {out}


[run.tools]               # shared tools, one [run.tools.<name>] each: check, label, connect, description, page, start, buttons (### Shared tools)
[run.checks]              # checks a blocked task can wait on, one [run.checks.<name>] each: cmd, label (### Until checks)
```

### Models per role

`[models]` picks the model for each type of work, with the defaults above in every repo: `code` (the task's
session), `fix`, `control` and `feed` start sessions of their own; `review` and `docs` are Claude Code subagents
of the task session, passed in with `--agents` and a model each, so all of it is plan usage. The task's brief
names them: the spec review runs in the `review` subagent, and CHANGELOG, docs, README, journal and plan-text
edits go to the `docs` subagent, whose result the task then checks. A lean session gets the Agent tool whenever
one of them is on (`[run] review = false` drops `review`, `[models] docs = false` drops `docs`).

`audit` is the model of an audit task's own session (see Auto audit), on any provider. It alone does not make a project need Claude Code: only that audit task waits for one.

Another provider changes that. A `review` on another provider, or any `review` on a task on the harness loop, has
no subagent, so the spec review is a one-shot instead, `agent-runner review` (above): the brief tells the task to run
it before `done`, and the task reviews itself if it did not run. A `docs` on another provider has no subagent: the
task's own session writes those edits. A `feed` on another provider runs its one-shot on the harness loop, which
cannot publish to claude.ai, so the run page keeps the local copy.

`[run] model` and `[run] fix_model` moved to `[models] code` and `fix`: an old file that sets them still works, filling those roles when `[models]` does not (the run log has a note), and `run --model M` still picks the task model for one run. A role
`[models]` sets wins over them.

### Models per kind

`[models.kinds]` picks the model for a task's own session by its kind, the letters of its id (`F105` is F, `P17a`
is P). The defaults are `opus` for F, B, T, V and K, and `sonnet` for D, C and R; a repo's table is laid over them
kind by kind, so `D = "haiku"` changes only D. A kind not listed runs on `[models] code`. A task names its own
model with `model:` on its line (`plan add D "text" --files a.md --model haiku`, or `plan edit ID --model M`),
which wins over the kind. A task session's model is chosen in this order: the task's own `model:`; `run --model X`
given on the command line (it sets every task without its own); `[models] audit` for an audit; the
`[models.kinds]` entry for its kind; `[models] code`. A resumed session (cut off, failed, or answered after
`run ask`) goes on on the same model. A kind's value must be a model name (a string), or
the run refuses to start with a `[models.kinds]` error. A repo that sets `[models] code` still gets
the default kinds for F, B, T, V, K, D, C and R; to run every kind on one model, set those kinds in `[models.kinds]`.

`[models] sizes` picks the model by a task's size (F470): `plan add … --size simple` (or `complex`, or `plan edit ID
--size simple`) writes `size: simple` on its line, and `sizes = { simple = "sonnet" }` runs simple tasks on that
model. Empty, the default, sizes are ignored; a size with no entry (complex, above) keeps its kind's model. The order
is then: the task's own `model:`; `run --model`; `[models] audit`; its size's in `[models] sizes`; its kind's;
`[models] code`. Guard: a simple task that ran on its size's model and whose `done` did not pass (it failed, or
blocked) is tried once more on its kind's model; a block it left is opened again for that attempt. Settings shows
it under Models, as Model for each size.

### Model providers

Any `[models]` role value, and any `[models.kinds]` value, may be `<provider>:<model>`. A bare name like `opus`
means `claude:opus`. Built-in providers: `claude`, `copilot`, `codex`, `gemini`, `ollama`. Only the first colon
splits, so `ollama:llama3:8b` is provider `ollama`, model `llama3:8b`.

A repo defines its own provider in `[models.providers.<name>]` with `kind = "openai"` or `"anthropic"` (any API
compatible with that one), `url` (http or https), and `key_env` (the name of the env var holding its key). Keys
never go in runner.toml: a `key`, `api_key`, `token` or `secret` field is refused. `key_env` may be left out only
for a local url. A provider may not reuse a built-in name. Example:

    [models.providers.acme]
    kind = "openai"
    url = "https://api.acme.example/v1"
    key_env = "ACME_KEY"

and then `review = "acme:gpt-x"`.

`[models] provider` (default `claude`) is the provider of every role, kind, fallback entry, task `model:` and
`run --model` written as a bare name, so one key moves a whole repo to another provider:

    [models]
    provider = "copilot"

A bare `opus`, `sonnet` or `haiku` becomes that provider's model for it, from `[models.tiers.<provider>]` laid over the
built-in ones name by name: copilot `claude-opus-5.5`, `claude-sonnet-5.5`, `claude-haiku-5.5`; codex `gpt-6.2-sol`,
`gpt-6.1-terra`, `gpt-6-luna`; gemini `gemini-pro-latest`, `gemini-flash-latest`, `gemini-flash-lite-latest`. Ollama
and your own providers have none, so set theirs:

    [models.tiers.ollama]
    opus = "qwen3-coder:30b"

Any other bare name goes to the provider as it is (`review = "gpt-6-sol"` with copilot is `copilot:gpt-6-sol`). A value
that names its provider keeps it whatever `provider` says, so single roles are still set by hand: `code = "claude:opus"`
stays on Claude Code. A local provider needs `[models] local = true` here too. In the run app it is Provider, the first
row of Models in Settings (Claude Code, GitHub Copilot, Codex, Gemini, Ollama; a provider of your own is set in the
file), saved for everyone; its More… saves it for this device. A provider with no login says so on the row, with Log in.
`[models.tiers]` is under Advanced > More models.

Local providers (ollama, or a provider whose url is `localhost`, `*.local`, or a loopback, private or link-local
address) are refused unless `[models] local = true` (off by default). Host names are not resolved. `local` can go
in runner.local.toml to allow it on one machine.

An unknown provider prefix is refused at start.

`claude:<model>` runs as the bare model name on Claude Code. A role naming another provider runs its sessions
in the [harness loop](#the-harness-loop).

Task sessions (`[models] code`, `[models.kinds]`, a task's own `plan add --model`, `run --model`), fix sessions
(`[models] fix`), and `review`, `docs`, `feed`, `audit` and `control` can name another provider. A control session on one runs on the harness
loop in chat mode (see [Control sessions](#the-harness-loop)).

### Several Claude logins

`run login claude --as NAME` adds a Claude login of its own: its own `CLAUDE_CONFIG_DIR` (beside this machine's logins
file, `~/.config/agent-runner/claude-logins.json`, or `$AGENT_RUNNER_LOGINS`), signed in by `claude /login`. Logins are
kept per machine, not per project. The first is the default login: the first time, Claude Code's own login is kept
first as `default`, so tasks run on it as before. `run login` lists them under claude.

Each login must be a separate real account (a work or Team account beside a personal one, or a pay-as-you-go API key).
Holding extra subscriptions only to get past usage limits breaks Anthropic's terms (and OpenAI's and GitHub's), and the
accounts can be banned.

Caps are kept per login (F503): `<notes>/capped.json` keys the default login as `claude` and another as
`claude@NAME`. A task whose login hits a cap goes on in its worktree on the next free login of the same provider
(same model, a new session told to read the work), then down `[models] fallback`; claude counts as capped only when
every login is. A local model (ollama) is a chain entry like any other, normally the last. `[run] session_max` /
`weekly_max` hold the login whose usage they read (the default login's), so new tasks start on another login. With
every login and provider capped and no local model, the task waits for the earliest reset.

### Fallback chain

`[models] fallback` is a list of models a task goes on with when its provider hits a cap, in order:

    fallback = ["copilot:gpt-5", "gemini:gemini-2.5-pro"]

Each is written as a role value is (`<provider>:<model>`, a bare name is claude's), and checked at start like one: an
unknown provider, or a local provider without `local = true`, is refused.

A cap is a Claude usage limit, or a provider's quota error (429, rate limit, quota, resource exhausted, "usage limit
reached").

A Claude Code task that hits a cap while it runs is told to stop at a clean point (commit what is solid, write its
journal), as a budget stop is (`[run] task_tokens`/`task_usd`), and its session is ended after 120 s. A session that
already ended on a cap is taken as it is. Either way the task goes on in the same slot: its worktree stays as the
session left it (commits and uncommitted edits), and a new session starts on the next model in the chain, told why
and to read `git log`, `git status` and its journal before carrying on. The run log says "stopped because claude hit
its cap ...; it goes on in this slot with <model>".

The next model is the first entry after the session's model in the chain (the first entry, when the session's model
is not in the chain) on another provider that is not capped and has its login (`run login`).

On the harness loop the switch happens within the same session: the runner passes it the chain entries after its
model up to the first claude one (`--fallback`); at a cap it goes on with the next with the whole conversation so
far, noting it in the transcript. When none is left it ends on the error, and the runner goes on with the next entry
(a claude one) in a new Claude Code session as above.

Capped providers are kept in `<notes>/capped.json` (provider -> until): till the reset time the error names (Claude
Code's `usage limit reached|<epoch>`, or "resets 3pm"), else one hour. While a provider is capped, a new task whose model is on it
starts on the chain's first free model; once the cap has reset, new tasks go back to their own model.

Past a `[run] session_max` or `weekly_max` cap (not forced), a new task whose model is claude's starts on the chain's
first free provider the same way, instead of waiting for the reset; the run log says once "session usage 92% >= 90%:
new tasks start on the first free provider in [models] fallback until the reset". A task whose own model is on an
uncapped provider starts on its own model. A task with no free provider waits, and STOPPED is raised only when such a
task is all that could start. Nothing is written to `capped.json` for these caps, and running tasks are untouched;
`--force` starts tasks on their own model. A task resumed with the person's answer (`run ask`) whose session's agent
(Claude Code or the harness loop) differs from what the chain gives now gets a new session on the kept work instead
of a resume.

With no fallback set (the default), nothing changes: a task waits for the reset as before (a cut-off session
resumes).

If every provider in the chain is capped, the task waits for the reset as with no chain.

### The harness loop

The harness loop is `agent_runner/harness.mjs`, a Node program (Node 22 or later on PATH as `node`), with one
session per process. The runner starts it instead of Claude Code for any session whose model is
`<provider>:<model>` with a provider other than claude: copilot, codex, gemini, ollama (needs `[models] local = true`;
`OLLAMA_HOST` or http://localhost:11434) and custom `[models.providers.<name>]` (kind openai or anthropic, url, key
from the env var `key_env` names). This holds whichever `[run] agent` is set.

Models come from `@earendil-works/pi-ai` 1.6.0, the provider and login package Pi uses. It is not bundled. The first
session runs `npm install` of that pinned version into `~/.cache/agent-runner/harness-1.6.0` (override with
`AGENT_RUNNER_HARNESS_MODULES`). Built-in provider names map: copilot -> github-copilot, codex -> openai-codex,
gemini -> google.

Logins are Pi's. The loop reads and refreshes `~/.pi/agent/auth.json` (or `$PI_CODING_AGENT_DIR/auth.json`), taking
Pi's lock on it, so log in once with `agent-runner login <provider>` (see SETUP.md). API keys from the providers' usual env vars also work (e.g.
GEMINI_API_KEY, COPILOT_GITHUB_TOKEN). A model id the provider does not list is refused with the ids it has. On a GitHub Enterprise domain (`enterpriseUrl` in the login), refresh and login go to the domain and `api.<domain>`, and the model list and calls to `copilot-api.<domain>`, unless the token names another address on that domain. The models are those the domain lists for the account (that the login package knows).

Tools: bash (each call starts in the worktree; timeout default 120 s, at most 3600 s; output over 30000 characters
is cut in the middle), read, edit, write, finish (runs `run finish`), ask (runs `run ask`; the task is parked under
Needs you and the answer resumes the same session), and publish_page (writes the HTML to
`<notes>/harness-pages/<task>/<name>.html`, then runs `run publish-page` on it, up to 420 s, and returns its
output, the URL included; with no Claude Code program here, no URL: the run page keeps the copy). A
`run finish` or `run ask` typed through bash ends the session the same way (it watches the slot's end mark).

One-shots: `--once` answers one message and ends. `--tools a,b` (a comma between) limits the session to the tools named:
a tool outside the list is not offered to the model, and a call to it returns an error. Its system text says nothing
of finish, ask or a worktree change. `run review` on another provider, and the feed one-shot, run this way (read only).

The git fence: before every tool call it runs `run fence`, with the same rules as Claude Code sessions' PreToolUse
hook: no git push, reset --hard, clean, or checkout -- .; no edit or write outside the worktree in the main checkout
or another slot. A denied call returns the reason to the model and does not run.

Budgets: before every model call it holds what the session has spent, counted as for `[run] task_tokens` and
`task_usd`: tokens without cache reads; dollars from the provider's own cost when it gives one. Past a cap it stops,
writes the task's budget mark, and the run parks the branch as wip/<ID> as it does for any session over budget. Fix
sessions have no cap (the fixed 30 minute timeout holds them).

Tells: a person's `plan tell` (text typed into the hidden slot's terminal) is read from stdin and goes in as the next
user message.

Ending: at finish or ask; or after `idle` seconds at the end of a turn with nothing told; a fix session (`--once`)
ends with its first answer. A transient model error is tried 3 more times. A lasting one ends the session with an
API-error entry, which the run resumes as it would Claude's. With `[models] fallback` set, a quota or usage-limit error switches the session to the chain's next model instead (see Fallback chain). A control session (chat mode) is not ended by a failed model call: it is shown and the session waits (see Control sessions).

Control sessions: `control N` on a `[models] control` of another provider starts `harness.mjs --chat`: many turns, waiting for
the person between them, the control brief as its system text, rewritten at every start. Tools: bash, read, edit, write,
publish_page. Escape (or the run app's Stop) interrupts a turn; Ctrl-C at the prompt, Ctrl-D, /exit or a closed terminal ends
it. A failed model call is shown and the session waits. No budgets. Its title is set by `control --title` in state only
(no /rename typed). A Claude session cannot be resumed on the harness loop, nor a harness one under Claude Code: a reopen
after a shutdown passes it by. `control --resume SID` goes on by session id. The git fence is `run fence … control`, asked
before every tool call: no push, no commit or merge in the main checkout, no edit of tracked files; ignored files (like
runner.local.toml, the notes dir and `take` worktrees) may be edited. publish_page in a chat gets the id `chat1<hash>`, one
per session and name. No Remote Control, so no control server, push, Artifact or Monitor; pages go through publish-page,
and `plan concept --page` takes `/concept/ID` for one with no claude.ai link.

In the run app a chat on the harness loop opens as a Claude Code one does: one frame with its terminal, and a chip row that
holds only Working and the model (`Codex · gpt-5.6-sol`). Stop and Force send send Escape, never Ctrl-C; Force send with no
text sends what is queued. While it runs, `<notes>/SID.now` holds JSON (pid, sessionId, status busy or idle, statusUpdatedAt,
startedAt, queued); it is removed at exit, and `/live/cN` reads it as `status`, `since`, `queued` and `harness: true`.
`<notes>/SID.model` holds the model it runs on, written at start and after a fallback switch. In the snapshot the chat's row
has `model` (the provider's name and model, only for a harness loop chat), and the snapshot's `chat_model` is what a new chat
runs on (`''` on Claude Code). The new chat card says "The chat starts with your first message, on Codex · …". The read tool
shows an image (PNG, JPEG, GIF, WebP, up to 5 MB) to the model for every harness loop session, when the model
takes images (one on ollama or in `[models.providers]` is told the image was left out); the transcript keeps only its
path, and an image since deleted is said to be gone. The terminal is drawn again from the last 32,000 characters printed when
a viewer comes or the size changes, and a resumed chat's terminal starts with the words of its last messages. `/commands` is
`[]` for it. An ended chat of the other kind than `[models] control` names has no Resume, says why, and is not restarted.
Questions (DECIDE), attachments, Talk and Resume work as before.

Transcript: `<notes>/harness-sessions/<session id>.jsonl`, in Claude Code's entry shape (type user/assistant, content
blocks text/tool_use/tool_result, usage in Claude's keys), so status, spend, the exit line's stats and resume read it
as Claude's. Each entry also keeps the provider's message as sent (`harness` field), which a resume reads back, so a
resumed session keeps its whole history.

Not there yet: no Remote Control, no subagents (the review and docs subagents). A fix session starts fresh rather
than as a copy of the task's session.

### Provider logins in the run app

`GET /logins` (on the run page and on Runner Home) lists each provider a role can name: the built-ins and those in
`[models.providers]`. Each row has `name`, `ok` and `where` (where its login is kept), `terminal` (what opens its login,
'' if none), `why` (then), and `login`: the state of its Provider login, '' (none), `running`, `done` or `failed`, with
`said` and `reopened`. It never shows a secret.

`GET /terminal/login-PROVIDER` opens a ttyd at `/t/TOKEN/login-PROVIDER/` running `run login PROVIDER`. Copilot on a
GitHub Enterprise domain is `login-copilot~company.ghe.com`, running `run login copilot --enterprise=company.ghe.com`;
`login-copilot` means github.com. The provider must be a known name and the domain a bare host name. Both are checked
on the server and passed as arguments, never through a shell; a bad one is refused with the reason, which never repeats
what was sent. API keys are typed only in that terminal. The key is required even on a trusted network, as for the
Claude login. The terminal is held 10 minutes after the last browser leaves. There is one per provider: another domain
for Copilot ends the one before.

When it ends, `/logins` says `done` or `failed` with why, and the tasks parked for that login reopen. Runner Home
serves it with no run up: at `/logins` for the built-in providers, under `/p/KEY` for a project's own. A login there
reopens the tasks parked for it in every project. Home does not restart on an upgrade during a login.

The run page's Settings uses the same logins. A `[models]` role, kind or fallback that names a provider with no login says
so on its row, with Log in; the Save is kept, and the Settings bar says that tasks on it wait for the login (a
role other than `code`, or a fallback: that the provider has no login yet). Log in (in
Advanced > This machine > Providers, per provider) opens one login sheet for claude and every provider. Copilot first asks
for github.com or a GitHub Enterprise domain; then the terminal opens, with Open the sign-in page and the device code in
words. A typed secret is a password field whose words go only to that terminal, and the field is emptied. Done says which
tasks start again, and the rows say logged in; failed says why, with Start again; closed midway, the row says Login under
way, with Show the login. The terminal hides once done. Without the page's key the `run login` command is shown, as before.

### The stream engine

`[run] engine = "stream"` runs each slot's Claude Code session headless: `claude -p --input-format stream-json
--output-format stream-json --verbose`, on the same claude.ai login. ANTHROPIC_API_KEY is removed from its
environment, so its usage stays plan usage.

The brief (on a resume, the resume message, with `--resume <session id>`) is the first stream-json user message
on its stdin, so a brief of any length goes in whole.

No idle Stop hook: the session ends at its result event. Its Stop hook ends nothing; it only gives the once-only context-full message (F177). Its stdin closes at once when nothing was sent during
that turn, otherwise when no next turn starts within 5 s. So `run finish` (then stopping), or a turn that ends
with nothing more to do, ends it. While the agent still runs a background command (a `done` waiting on the gate),
its stdin stays open, as the Stop hook's waiter does, until that command ends, `done` or `run finish` has run, or
`AGENT_RUNNER_IDLE_MAX` (10800 s) has passed.

`plan tell`, budget stops and typing from the Run page go in as its next user message, through the slot's FIFO: typed
text becomes a message at its Enter, and keys such as Escape are dropped. On Windows a stream session takes no tells: it
runs in a hidden console, which takes no typed text (ConPTY is for the other sessions).

Its event stream goes to the slot log, to `<notes>/streams/<session id>.jsonl` (the spend for `[run] task_tokens`
and `task_usd` is read from there), and to `attach sN`; the run app shows a stream slot as a card with no terminal (see The session).

No Remote Control: `remote_slots` does not apply, and Open a slot on the Run page says the slot runs headless;
the Run page shows it.

Sessions on another provider's model still run in the Harness loop. The default stays `"terminal"` until task
F106h flips it after the end-to-end check.

### Renamed and removed keys

An old key still in a runner.toml or runner.local.toml is no error: the run's start logs it with what to
write instead. A renamed or folded key still applies under its new name (where a file sets both, the new one
wins); a removed one is ignored.

Renamed or folded in 0.58.0 (the config trim):

- `[run] timeout` is renamed `command_timeout`.
- `[needs] order` moved to `[run] needs_order`.
- `[run] control_ask_idle` is renamed `control_ask` (`"2h"`, or false to keep such a session open).
- `[run] control_close` is folded into `control_idle`: `control_close = false` is read as `control_idle = false`.
- `[run] batch` is folded into `batch_max`: `batch = false` is read as `batch_max = 1`.
- `[run] backend` is ignored, with a warning to delete it, and the Pi backend it could name is gone (F106d, see the CHANGELOG):
  `backend = "pi"` and `AGENT_RUNNER_BACKEND=pi` fail at start; `agent = "pi"` no longer does: it loads and the line is said (B764b). Name the model in `[models]` as
  `<provider>:<model>` instead.
- `[run] slot_env` keeps its name but defaults to `[]`: every slot gets `AGENT_SLOT=<n>` whatever it says, so
  a `slot_env` no longer needs to repeat it.

Folded or fixed by the settings cut (F166, unreleased):

- `[run] comment_policy` is ignored: write its wording in `prompt_extra`.
- `[run] idle`, `[run] stall`, `[run] pause`, `[run] fix_timeout`, `[run] control_idle_quick`,
  `[run] control_idle_talked` and `[run] merge_ahead` are fixed
  (30 s, 1200 s, 60 s, 1800 s, 5 min, 12 h, on); a file that sets one is ignored. `run --idle`, `--stall` and `--pause`
  still set one run.
- `[run] control_open` is fixed: its phrases are the built-in ones.
- `[run] model` and `[run] fix_model` moved to `[models] code` and `fix`.
- `[run] sessions` is folded into `remote_slots`: an old `true` with `"each"` reads as `"always"`, any other old
  boolean as `"open"`.

Removed since 0.58.0:

- `[plan] release_alone` is ignored, with one warning: tag the release `(alone)` instead (`plan edit V7
  --alone`); any task can run alone that way (F130).
- `[run] wizards` is removed (C37), ignored with one warning: a task that needs a person writes its steps in an ask
  file; delete the key.

Removed in 0.58.0 (the config trim):

- `[run] control_file_asks`: an open question is always filed before its session closes; `control_ask = false`
  keeps such a session open instead.
- `[run] control_ask_kind`, `[run] flaky_kind`, `[run] ci_kind`: a control session's open question is always an
  F task, a flaky test a T task, a red CI run a B task.
- `[needs] heading` (always "Needs you") and `[needs] ages` (each item always shows its age); with
  `[needs] order` moved, the `[needs]` table is gone.

Removed earlier:

- 0.60.0: `[run] mux` (and `run --mux`): every run is hidden on every OS, with no tmux; `agent-runner attach`
  shows the run view and `attach sN` a session's own terminal.
- 0.52.0: `[needs] map_replies` (sessions map a reply to its item themselves).
- 0.32.0: `[run] mode` (a run never starts two tasks on the same files), `[run] fix_ahead` (`fix_ahead_max = 0`
  is what `fix_ahead = false` was), `[run] precommit` (chain the check into `[run] test`), `[run] ci_rerun` (a
  red CI run's failed jobs are always run once more), `[run] batch_wait`, `[run] batch_min`, `[plan] brief`
  (use `brief_extra` and `outline`).

## What it leaves out

Nothing project-specific is built in. A project supplies it through hooks: a program per slot
(`slot_env`, `on_exit`), a check on new block reasons (`suspect`), a custom conflict join
(`[run.join]`), and extra brief text (`brief_extra`, `outline`). A kit that keeps only its tools is in
[docs/SETUP.md](SETUP.md#worked-example-a-kit-that-keeps-only-its-tools).

## A program per slot

Some tasks need a running program of their own: an emulator to record from, a browser, a device, a dev
server on a port. Give each slot its own copy and let the runner tell it which:

- `slot_env` hands every slot its number, so the project's tools pick their copy: a port, a profile
  directory, a lock file. `EMU_SLOT={n}` and a launcher that reads it is all it takes.
- `pass_env` passes on what the whole run shares (a cap on how long one session may hold the program).
- `on_exit` closes the slot's copy when its session ends, with that slot's env. It also runs when a drop, `plan change --restart`, a take back, a cancel or `s!` stops the session (with `s!` it runs detached: the run does not wait for it, and the next run holds the slot until it has ended, stopping it past `[run] command_timeout`, see above), and the slot starts nothing until it has ended.
- `before_start` holds new sessions while the program cannot run (no display, device unplugged). The run
  logs it once, rings the bell, and resumes once the check passes.
- `prompt_extra` tells the session it has its own copy and how to drive it (`{n}` is the slot).
- `links` symlinks the program's big git-ignored inputs into every worktree.

opentennis runs one PCSX2 per slot this way. Its mapping is in
[docs/SETUP.md](SETUP.md#worked-example-opentennis).

## Library

`from agent_runner import plan, done, runner` and the names in each module's `__all__` are a stable API,
so a project's own code can call them (`plan.main(argv)`, `done.main(argv)`, `runner.cmd_run(argv)`).
A project's CLI keeps its tools only: see [docs/SETUP.md](SETUP.md#your-own-cli-for-tools-only).

## Tests

```sh
python3 tests/test_plan.py      # the plan tool
python3 tests/test_home.py      # [run] home: default, overrides, the pre-0.13 places
python3 tests/test_disk.py      # slot_max_gb, min_free_gb, extra slots removed
python3 tests/test_cost.py      # agent-runner cost: kinds of call, size × turns, Claude and Pi transcripts
python3 tests/test_plansync.py  # [plan] repo: two checkouts on one plan repo, merges, claims, tick on landing
python3 tests/test_stale.py     # the removal check (F416): what still names a removed name, answers, ignored files
python3 tests/test_runner.py    # picking, done, merge/join/land/push, fix sessions, wip parking,
                                # retry after unblock, prompt, Stop hook, resume, adopt,
                                # batches, flaky/inherited failures, the platform layer and the
                                # Windows slot shim (temp repos, fake agent)
```

### Windows CI for a task branch

Windows-only code (ConPTY, attach) cannot run on Linux, and the GitHub ci workflow is disabled since 2026-11-24 (too
many emails; its file stays), so a run of it by hand with gh fails. Before the merge, and before a plain `run done`,
run the Windows tests on this machine's Windows VM as a background command and wait for it to end: `tools/windows_vm.sh
<test files the change touches>`, or `tools/windows_vm.sh --all` for every `tests/test_*.py`. It tests the worktree,
uncommitted changes included, so there is no push, no gh and no block needed. With `--all`, it prints after each file
`-- FILE: passed|failed, N.Ns`; the last line is `windows_vm: all N files passed`, or `windows_vm: N of M files failed:
FILE FILE`, or `windows_vm: did not finish: see the output above` when the VM or its ssh was cut off. A failing file:
fix it and run again. A file that also fails without the change is not yours: file it if no task covers it. Once the
files pass, plain `done`, then `finish`. Without a VM (exit 2 and only a line like `windows_vm: … no Windows VM to
use`, with no test run) the task is blocked and says so: `run done <ID> "<msg>" --blocked "BLOCKED: no Windows VM on
this machine to run its Windows tests: <the script's line>"`.

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

### Windows code from a Linux slot

A slot on Linux cannot run the Windows tests itself. Run `tools/windows_vm.sh [--keep] [test file ...]` (default
`tests/test_windows.py`), or `tools/windows_vm.sh [--keep] --all` for every `tests/test_*.py` (it takes no file names):
it runs them on the Windows VM, of this worktree with uncommitted changes included, starting the Docker container
named by `WINDOWS_VM` (default `windows-vm`) if it is stopped and stopping it again if it started it (`--keep` leaves
it up). The output and exit code come back, and two callers wait on a lock. Without the container or the ssh key it
says so in one line and exits 2 without creating a VM; then the task is blocked as in
[Windows CI for a task branch](#windows-ci-for-a-task-branch). That run is the proof before the merge. The settings by
environment are in the script's header.
