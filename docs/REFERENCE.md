# agent-runner reference

Everything the [README](../README.md) leaves out: how a task runs end to end, picking, merging, fix sessions,
disk and memory, stopping, the prompt, every command and every `runner.toml` key. Setup is in
[SETUP.md](SETUP.md).

## How it works

```
plan/TODO.md ──pick──▶ slot N: git worktree ~/runs/<repo>/sN on task/<ID>
                         hidden terminal sN: claude "<prompt + the task's brief>"
                         …the session works, then `agent-runner done <ID> "msg"` (test gate → tick → commit → push task/<ID>)
                         Stop hook: quiet for [run] idle seconds → the session is ended
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
4. **End the session.** The session goes quiet at its prompt. The Stop hook's detached timer sees no new
   transcript entries for 5 s once `done` has succeeded, or `[run] idle` seconds (30) when it stopped without it, and ends it. If a human typed in it (`attach sN`), or a usage
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
   - any other conflict goes to a one-shot fix session (`claude -p`);
   - the gate runs again if the merged code differs from what `done` tested.
   Only then is the main checkout moved to the tested merge. That takes seconds, it never stashes, and it
   waits if someone has uncommitted edits to the files involved.
6. **After the merge.** `plan reopen` unblocks tasks whose `BLOCKED: (after X)` just landed and commits that.
   Then `main` is pushed (`[git] push_merge`), and the remote `task/<ID>` is deleted once the remote `main`
   contains it.
7. **Repeat** until nothing can start. Then the run [goes idle](#it-stays-up) and waits for new tasks.

### Terminals, and Windows

Every session the run starts (each slot, c1 and other control sessions, the runner feed) runs hidden: a terminal with no
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

Bare `agent-runner` starts the run where no terminal shows it and returns within seconds: a detached process
(`plat.spawn_detached`: `agent-runner run`, its output in `.runner/background.out`), its slots hidden (see above). The
launch waits for the run's start line in `run.log`, then prints the slot count and the commands: `status`, `attach`,
`stop`, and claude.ai/code with `[run] remote`. If the run fails within that time, it prints the end of its output. If a
run is already up it says so and starts nothing. `agent-runner run 3` is the same run in the foreground of this
terminal, its log printed there and its keys read from it. On Windows each slot gets a ConPTY pseudo-console with no
window (before 1809, a console that starts hidden, `STARTUPINFO.wShowWindow = SW_HIDE`); either way the agent has a TTY.

`agent-runner attach` (or `attach run`) is the run view, from any terminal and over ssh: the end of `.runner/run.log`,
then each new line as the run logs it, and the runner keys typed there (`s`, `s!`, `p`, `f`, `+`, `-`, `slots N`, `z`,
`x`, `u`, `?`, and an empty line for Remote Control), each posted to the run through `.runner/KEYS` as `agent-runner
key` does. `?` lists them (they print once as the view opens too). Ctrl-C leaves the view; the run keeps going. `attach
feed` and `attach board` open `agent-runner ui`. On Windows there is no attach to a ConPTY session yet: `attach s2` (or
`c1`, `cN`) prints the place of its log and shows no console, as it does for a headless stream slot. Only a session with
a hidden console from before 1809 is shown: `attach s2` shows and raises its console window. Minimize it to hide it
again; closing it ends that session, which resumes in the next run. `agent-runner status` and `.runner/run.log` show the
sessions either way. On Linux and macOS a hidden session (`attach s2`, `attach c3`, or Enter on the session tab of
`agent-runner ui` outside tmux; inside tmux `agent-runner ui` shows it beside its panels) is attached to its own
terminal, the way dtach does it: the shim listens on a Unix socket beside its marker (`.runner/slotN.sock`,
`controlN.sock`, mode 0600, gone when the session ends), sends what the session prints to every attached terminal, types
in what you type, and takes your terminal's size (on attach, and when you resize it). Detach with Ctrl-b d (Ctrl-b
Ctrl-b types one Ctrl-b); the session keeps running. A session started before this has no socket, and `attach s2` says
where its log is.

With `[run] remote` (or `remote_slots`), Claude Code asks once, at a terminal, "Enable Remote Control? (y/n)".
In a hidden session that question would hold every session. So before going to the background the launch checks `remoteDialogSeen` in
`~/.claude.json` (or `$CLAUDE_CONFIG_DIR/.claude.json`). If it is not set, the launch asks the question in this
terminal and records the yes there. A no, or no terminal to ask in, starts nothing. Under `remote = "auto"`
(and no `remote_slots`) it starts the run anyway, with Remote Control off and the reason in `run.log`.

### Control sessions

A control session is an interactive Claude Code session in the main checkout where a person runs the run, at
the terminal or from claude.ai/code and the Claude apps: "status?", "pause", "one slot more", "stop", "add a
task to fix X" (it files it with `plan add`), "do X now" (it uses `take`, never edits the main checkout).

- **c1 comes with the run** (`[run] control = true`, the default; false: none). On Linux, macOS and Windows (ConPTY,
  1809 and later) it runs in a terminal with no window, through the same shim as a hidden slot, its output in
  `.runner/control1.log`; before 1809 on Windows it gets a console of its own that starts hidden. `agent-runner attach
  c1` goes there, except on a ConPTY session on Windows, where it prints the log's place. c1 keeps its session id in
  `.runner/control.sid` and resumes it in every run while the transcript is there. A new run a person starts begins c1
  afresh instead (a new id in `control.sid`) when the kept session's last context is over `[run] context_warn`, and its
  opening summary says so in one line first (`c1 starts a fresh session: the last one reached 160k context …`; with
  `[run] remote`, whose c1 opens blank, that line is in c1's terminal and `run.log` only); the plan, ledger and `since`
  hold the state. A restart always resumes it, whatever its size: the self-restart on `upgrade` or `auto_upgrade`, a run
  after a crash, a kill or Ctrl-C (the last run never logged its stop) within 6 hours, and a run started within 5
  minutes of the last one ending. It has no Stop hook, is never ended on idle, and outlives a stopped run: a run that
  finds c1 still up opens no other.
- **More of them**: `agent-runner control` starts one in this terminal (c1 when it is not running, else the
  next free number, `.runner/control<N>.pid`).
- **A new one from inside one** (the phone apps have no new-session button): `agent-runner control --new [N]` opens the
  next free control session without taking focus: hidden through the slot shim, its output in `.runner/control<N>.log`
  (Windows: a ConPTY pseudo-console, or before 1809 a hidden console); `attach cN` shows it, except on a ConPTY session
  on Windows, which prints the log's place. On Windows the first message still goes on the command line. A name it takes
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
- **Their settings**: every control session, and the control server, gets `.runner/control-settings.json`
  with `--settings`: a SessionStart hook that runs `agent-runner control --brief`, which prints the control
  brief (so a resumed or compacted session gets it again). They run on `[models] control` with every tool
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
  with PushNotification so a phone hears it: the run's terminal and `notify-send` are seen by
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
  recommended: every slot start pushes to the phone (see Phone pushes below). Watch hidden slots through
  status and control sessions instead.
- **One entry per project (`[run] sessions`).** `"one"`, the default, keeps the apps' list to one entry for the
  project, c1, its chat: no slot starts on Remote Control, even with `remote_slots`. `agent-runner ui`'s
  Sessions panel opens one (its session tab, "open sN in the Claude apps"; the run app has no such button):
  the run types `/remote-control <name>` into that slot's session, which is listed from then on until it ends,
  and its claude.ai/code link shows in the page. For when this machine is not reachable, the run keeps a claude.ai copy of the run page: on a run event (a
  task starts, lands or blocks, a needs-you item, a concept, the release; at most every 10 minutes, and only
  when the page changed apart from its clock, log and minutes) the run writes `.runner/run-page-copy.html` and
  publishes it with a one-shot headless `claude -p` that has only the Artifact tool, to the URL kept in
  `.runner/run-page-copy.url`; never through c1 or another control session. After 3 failed publishes in a row
  the copy stops for that run. The copy is read-only, with the terminal and the chat as session links.
  `"each"` is the earlier behaviour: every slot its own entry with `remote_slots`, and no copy.
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
each run at `/p/<project>/`. Without it, each run serves its own page on port 8770 only while it is up, and
the second run's page moves to another port. `home status` shows whether it is installed and serving;
`home add PATH` lists a project outside `~/repos`. See the README's Runner Home section.

Home's links put the https address first. `home status`, `home install` (and its QR code, which holds the https
link when there is one) and a run's link through Home (`/p/<project>/`) list a Tailscale Serve https address for
Home's port first, then http by hostname and LAN address; Talk's mic and dictation need https. With no Tailscale
Serve for Home, `home install` offers (in a terminal, y/n) to run `tailscale serve --bg --https=8771
http://127.0.0.1:8770` (Home's port plus one), or prints that command. Home's page
is now the run app itself: at `/` it is the "All projects" view, one row per project with Start run, Open, Pause or
Go on, −1 slot, +1 slot, Stop and Unlist, plus an add-project box, Needs you alerts and Devices. Through Home, a
run's app (`/p/<project>/`) has a project switcher at the top of the sidebar (the current project's name; tap it to
list every Home project as running, idle, paused or off, with its needs-you count; each moves to `/p/<project>/` on
the same Home address) and an "All projects" item in the sidebar.

Runner Home restarts itself when agent-runner's package files change on disk (an upgrade or a clone's pull, same
version or not), once the change holds over two 5 s looks. It re-execs in place, never while a request or terminal
tunnel is open; runs' event streams end when only those are left, and pages reconnect by themselves. On Windows, which
has no exec, a detached helper waits for the old Home to exit and starts the scheduled task again (`schtasks /End`,
`/Run`, up to three times until Home answers); `home uninstall` disables the task first, so a restart under way cannot
bring it back. It does so only when the scheduled task runs Home (`pythonw.exe`): a `home serve` typed in a terminal,
or a Home run with `python.exe` because there is no `pythonw.exe`, does not restart itself. Windows Home writes its
output to `home.log` in Home's config folder. A Home started before this needs one restart by hand; unlike a run, it
also restarts across a breaking version.

### The run app

With `[run] web` (on by default) a run serves the run app from this machine on `[run] web_port` (8770), bound
to every interface so a phone on the LAN or Tailscale reaches it. Its address, with the token every request
needs (made once per project in `.runner/web.token`), is in `status` and the run log. It is a chat app over
the run page: the same snapshot as `agent-runner ui` and most of its actions (not opening a slot), laid out for a phone (the sidebar becomes a
drawer) and a desktop. It follows the browser's light or dark setting; `[ui] theme` is the terminal UI's only.

- **Talk.** The first view in the sidebar, for running the run hands-free: tap the mic, speak, and the
  reply is read aloud (the browser's own speech recognition and speech, no install). The speaker button left of the
  mic turns reading aloud on and off (while a reply is read, it stops it); the keyboard button swaps the mic for the
  message box and the browser remembers which. Each reply has a play button. The gear opens Talk settings, kept per
  browser: read replies aloud, the voice (the system's own by default), tap or hold to talk, and auto listen (listen
  again once a reply was read, until one silent turn). Talk has its own control session, titled Talk and reused while it is live, told to answer in short
  spoken sentences with no task IDs, paths, commands, links or markdown. New Talk chat (top bar) stays in Talk, stops listening, reading aloud or waiting for a reply, clears the shown conversation, and the next message opens a fresh Talk session; this also holds after a reload in that browser. The mic needs Chrome, Edge or Safari
  on https or localhost (a plain http LAN address gets no mic); without one it says so and the box still works. An abort before any words is retried once by itself; if it fails again, Talk's status line says what to try. While the mic starts, its line says "Starting the mic…" until sound is really captured, then "Listening…". A listen that heard no words shows "Copy mic report", the events from press to end with their times, to copy and send (shown on screen to copy by hand where the clipboard is refused).
- **Sidebar.** New chat, Talk, Home (with the Needs you count), Status, Plan, Concepts and Settings. Chats are the
  control sessions: a dot marks one that needs your reply (an open question, or it spoke after you last opened it),
  and one that needs none with nothing said for `[ui] chat_quiet` is gray at the bottom under Quiet (never c1, a
  pinned or a renamed one). Double-click a chat's name (on a phone: its ⋯) to rename it; the name is yours, so the
  run neither closes that chat when idle nor renames it. Agents working are the slots on a task. On a phone the
  sidebar is a drawer: swipe right anywhere to open it, left to close it, and its button has a dot while Home or
  Concepts has a count.
- **State.** Every page's top bar has the run's state: Running, Paused, Stopping, Caps forced or Not up. A tap on it
  opens Status.
- **Status.** One scroll in `agent-runner ui`'s order: Needs you, the run with its slots and controls, usage, what
  landed lately, the release, and the run log with the Since asks. The Run card has the everyday controls (slots,
  pause, stop); More… opens the rest in a sheet, each with its key in `agent-runner ui`: Stop (stop now, suspend, shut
  down), Run (set slots, force, upgrade, restart) and, while there is something to fix, Fix up (resume a cut-off task,
  release stale claims, the main-checkout edits a merge moved aside). Stop now, suspend, shut down, upgrade, restart
  and dropping edits ask first, in place; in `agent-runner ui` the key is pressed twice. Restart (`key restart`)
  re-execs the run between merges so that it reads its settings again; its tasks keep going.
- **Settings.** Every key `agent-runner settings` lists, with its value, where that comes from, its default and its
  help. This device saves to `runner.local.toml` at once, one key in place, comments kept; Reset takes the key out.
  Project queues a C task on `runner.toml`, which lands through the gate. Each says when it applies (slots: now;
  the rest: the next run, or Restart the run). Keys that are no setting show read-only, flagged.
- **Home.** A greeting, a message box, quick asks (since my last look, what needs me, add a task), then
  Needs you (each item's answer buttons, Later to shelve it, Chat to open a new chat that shows the question and its answers, Drop to
  drop the task after a confirm), Working now (opens
  that agent's thread), Up next (a row folds open to the task's whole text) and Release (when the next one
  lands, or now). An answer button runs the plan command itself, with no AI session: Yes on a CONFIRM or a picked
  answer runs `plan confirm ID "<reply>"`, No on a CONFIRM runs `plan change ID "No: the check failed"` (which reopens it), and a pick sheet's go runs `sheet ID --go`. The button shows it is working, a toast says what was done (e.g. "R13 ticked") and the item leaves Needs you at once; on a failure the toast says why and the item stays. Words typed in a reply still go to c1. `agent-runner ui`'s answer tab does the same.
- **Threads.** A session's feed as a conversation: its replies in serif with no bubble, yours in bubbles,
  tool steps folded as "Ran N steps", and a mark while it works, with a Stop button. Ctrl+C or Stop interrupts it; Esc only leaves the box, then
  goes back (B116). A control
  session's thread talks to that session; an agent's thread messages that agent.
  A chat opens at its newest message and follows it, unless you scrolled up; then a button jumps to the latest. A
  refresh never moves the page, in any view.
- **Message box.** Enter sends, Shift+Enter starts a new line, and each thread keeps its own draft. An About
  line says what the message is about. Attachments are uploaded to the run (`POST /upload`), kept under
  `.runner/uploads` (`<notes>/uploads`, git-ignored with the rest of the notes folder), and handed to the
  session as paths on this machine.
- **Plan.** The queue in plain words (a row folds open to `plan ID`'s text, with Chat), and Add a task. Tasks are not
  edited here directly: ask in a chat.
- **Concepts.** Each concept with a button per option (taken from its page's headings), plus Chat, New chat and View.

How the app looks, moves and speaks is in [STYLE.md](STYLE.md); a change to it follows those rules.

The app does not open slots in the Claude apps; `agent-runner ui` still does (see `[run] sessions` above).

`agent-runner ui` (the terminal UI) has no chat of its own: nothing is typed into a session from it, and Ctrl+C
always quits. Selecting a session row (cN or sN) shows the real Claude Code session. Inside tmux, a pane split
off beside the UI runs `agent-runner attach cN` (respawned when another session row is selected, killed when
another row or the UI quits); l, Enter or Ctrl-l moves focus into it, and Ctrl-h comes back. Outside tmux, or
where a session has no socket (Windows), its tab shows the feed read-only with its link (o open, y copy); Enter
attaches full-screen. Ctrl-f makes the session full-screen between the UI's top and bottom bars, and again for
side by side. N starts a new control session without waiting for its link, and `c` selects c1.

- **Terminal-style page.** The same server also serves the terminal-style page at `/term?t=TOKEN`: the run page
  drawn like `agent-runner ui` (numbered panels, a key for everything), in `[ui] theme` (its `t` picks another
  for that browser). The run app's sidebar (the drawer on a phone) has a Terminal view switch; the page has
  App view in its top bar and the key T. The browser remembers the last view, so the link opens it again;
  `[ui] web` sets the view for a browser that never chose.

### status and since

`agent-runner status` and `agent-runner since` name each task by a short title, the first sentence of its line
cut to about 60 characters, without its fields, quotes, dates or file lists, with the id in brackets at the
end: `s1  Control session experience [F5]  12 min`.

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
concept pages, and takes one of three answers (the control session or the runner feed maps what the person
says to the item's id, a reply that names no item, "yes", "B", "later", included, and asks which one when it
cannot tell):

- `plan confirm R1 "the push came"`: a CONFIRM is ticked with that noted; a DECIDE or BLOCKED reopens with
  the answer noted; a concept is approved.
- `plan change R1 "do X instead"`: noted and reopened (a concept: `revise`).
- `plan shelve R1`: stays blocked (`BLOCKED: shelved: …`) but leaves the list; `plan waiting --all` still
  shows it, and `plan unshelve R1` brings it back. Concepts shelve the same way.

Answers stay in their own project: `confirm`, `change` and `shelve` read and change only this project's plan,
never another's. An id only another project has gets `nothing needs you here about 'R43' in <project>`, and is
answered in that project's control session; a project that needs another's state checks it itself.

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
what was unpushed when `approve` was turned on). The page is published to claude.ai by a one-shot and shown at `/concept/pitchN`. It is a Needs you item, and the
runner feed pushes it to the phone.

Approve (the button, or `agent-runner pitch approve pitch1`) pushes exactly up to the pitch's last tested merge.
Merges that landed in one gate run share that commit. If an earlier merge is not approved yet, the approval says which
pitch it waits for and is kept; both are pushed once that one is approved.

Not this (`agent-runner pitch no pitch1 [--reopen F1] [--drop F2] [--why "..."]`; with neither flag all its tasks are
reopened, and `--drop all` drops them all) makes an undo commit per task on local main, through the gate. Plan files
are left out of the undo. The task is reopened, or left closed as dropped. A conflict goes to a fix session. What
cannot be undone returns to Needs you with the reason. An undone change never goes out without its undo commit. With
no run up, the command does the undo itself.
The run app, `agent-runner ui` and the terminal-style page offer the same choices per change.

`agent-runner status` and the run page say "3 changes wait to be pushed (1 pitch for you to approve)". Release tasks
(V) do not start while anything waits. If the remote moved, the next merge takes it in, and the approved work goes out
with that merge once it is approved.

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
`docs/research/**` and `research/**`; `!glob` takes one back). A research diff that touches any other file
is not merged: the branch is parked on `wip/<ID>` and the task blocks with `DECIDE: R7 is research, but its
diff changes code (a.py, …)`, listed under Needs you. Answer `follow-up` (the next attempt's brief tells it
to file the code from `wip/<ID>` as its own task and commit the findings alone) or `merge anyway`: with those
words in a note on the task (after ` — `, not in its title), its next merge lands the code too (F36).

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
- **Alone tag** (F130): `(alone)` in a task's description, after its level tag if any: `plan add KIND "text" --alone`
  writes it, `plan edit ID --alone` sets it on an existing task and `--no-alone` clears it (an edit with new text or
  fields keeps it). Any kind of task can carry it, e.g. a major rewrite whose `files: native/**` would not hold the
  other tasks under that directory: a tagged task runs alone, so the run starts it only when nothing else runs or
  waits to merge in this run, and starts nothing beside it. Tasks taken by hand (`take`) or claimed by another runner
  do not hold it (B107), unless they are tagged `(alone)` too. The dry run and the TUI say
  `T1 runs alone`. A release (kind V) without the tag runs beside other tasks as above. A runner.toml that still sets
  the old `[plan]` key for this (removed in F130) gets one warning in the run log and is ignored.
- **Auto release** (F63, off by default): `[run] auto_release` has the run queue a release by itself, as
  `plan add V` with no text does. `auto_release = { every = 10 }` queues one once 10 tasks have landed since
  the last release (the later of a release task's landing and the newest version tag); `{ idle = true }`
  queues one when the run goes idle with nothing left it may start (tasks blocked on the person don't count),
  at most once per idle spell; both may be set, and either fires. It never queues one while a release task is
  open, nor with nothing landed since the last release: release tasks are not counted, and nothing counts when
  only the plan changed since the version tag. The run log and `status`'s lately say
  `queued V7 (auto_release: 10 landed)` or `(auto_release: idle)`.
- **Release row** (F131): the run page and the TUI show the release as a row pinned at the end of the queue, and
  J/K move no task past it. With `auto_release` on and no V queued, the row is dimmed and reads
  `Next release · auto at 10 landed: 6/10` (` · when the run goes idle` added for `idle = true`, both when both
  are set). A queued V reads `V5 Release · waits for 24 open ahead`, then `ready` when nothing is left before it,
  `blocked` when it waits on a person, and `building` once a slot has it or it is merging. With `auto_release` off
  and no V, there is no row. Enter on the dimmed row opens the release tab. `agent-runner status` says the same thing as
  `release: <that row>` in place of `last: V5 waits for everything before it`, keeping its `not waiting on` notes;
  once the release lands, `lately` reads `landed: Release 1.2.0 [V5]` and the count starts again at 0/N.
- `plan add` also refuses (exit 3, nothing written) text that looks like an open task's work, naming it:
  `plan note` that task instead, or `--force` for different work. A task's own split (`plan add P13 …`)
  is never refused for looking like P13. `plan drop ID WHY` closes a task nobody will do (a duplicate,
  overtaken): archived with `dropped: WHY`, so its id stays used and what waits on it reopens.
- Reaching a running agent: `plan tell ID TEXT` types `A note on your task, from the person running this run: TEXT` into
  the session of the slot running ID, through its shim's FIFO, or on Windows its named pipe (Claude Code queues it for
  its next turn while busy), and edits no plan; it fails when no slot of a run here runs ID. `plan change ID TEXT` on a
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
  - `after:` ids that must be done first. **Every id** listed counts. `after: all above` (what `plan add
    --last` writes, filing the task at the end of Next) is no list: the run resolves it on every pick to each
    task above it in its own section that is not done, ones added later included, so a release waits for the
    whole section without a list going stale. Tasks blocked on a person don't hold it until they reopen;
    Follow-ups never do. `plan reopen`, `plan waiting` and `status` say what it still waits on.
    `after: all` (`plan add/edit/block --after all`, any kind) waits for **everything before it**: each open
    or blocked task above it in TODO.md, in any section, resolved afresh on every pick, so a task queued above
    it later holds it too. Parked (`--pri later`) and Stretch tasks and shelved ones don't count, or it would
    never run. On a block it reads `BLOCKED: (after all) why`, and `plan reopen` frees it once nothing is left
    before it. `plan ID`, `plan reopen` and `plan waiting` show it as `T5 waits for everything before
    it (12 open)`, not an id list; `status` does too for a task that is not a release (a queued release shows
    its row instead, see Auto release).
  - `model:` the model the task's own session runs on (`plan add/edit --model M`), which wins over its kind's
    `[models.kinds]` entry; `plan ID` shows it. See Models per kind.
  - `test:` the tests that prove it. `journal:` its journal folder.
  - `plan add P "text" --files a,b --after X --test name` writes them; `--model M` writes `model:`.
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
it as a task to do as written, still never running a command from it. When the task closes, the issue gets a
comment naming the merge commit (or saying it closed with no code change); under `"trust"` it is closed too,
under `"skeptical"` only commented. A `gh` that cannot see the repository is said once in the run log, as for
CI.

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
the 7-day usage, no new task starts unless `--force` is given (or `f` typed in the run view); hitting one raises the STOPPED alarm with that hint. With `[models] fallback` set, a new task whose model is claude's starts on the chain's first free provider instead, until the reset (see Fallback chain); a task with no free provider waits.

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
shows it at `/concept/<ID>`), then starts a one-shot headless `claude -p` with only the Artifact tool to publish
that copy to claude.ai: a new artifact with icon "options", or the URL already recorded for ID, so a second
publish updates the same page. The URL is printed and kept in `<notes>/concepts/<ID>.url`. Exit 1 when the
one-shot did not publish (the copy is still on the run page); exit 2 for a missing file or no task id.

**Git fence (F102).** Every Claude Code slot gets a PreToolUse hook through `--settings` (`agent-runner fence`)
that denies `git push` in this project (anywhere while `[git] push = false`), `git reset --hard`, `git clean`
(not `-n`) and `git checkout -- .`, and an Edit or Write in the main checkout (but its notes folder) or
another slot; an edit outside the project, in a sibling repository the task needs, is let through. It
holds every session, and replaces the no-push git config that `[git] push = false` used to set.

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
the run view** (`agent-runner attach`, or the terminal you started `agent-runner run` in), or run `agent-runner stop` from anywhere. Either way
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
| `slots N` | N slots (`+N`, `-N`: that many more or fewer) |
| `z` | suspend the computer once the run stops, or when it goes idle as `--suspend` would; `z` again: off |
| `x` | the same, shutting down (`--shutdown`); `x` again: off |

After a stop, power goes off at once, with no idle grace. `agent-runner stop --suspend` (or `--shutdown`) does
the same from anywhere, through `.runner/POWER`. A line the runner does not know is echoed back with
the key list. Each key is acted on as it is typed; ending sessions and adding a slot wake the loop at once.

**The same from any terminal, or a remote session.** Each key has a command, so nothing needs the run view:
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
runs in a session of its own (`.runner/gates/<key>.json`), and a fix or repair session an older run left
in its master window recorded itself in `.runner/master.json`; both outlive the runner. The restarted run waits for them,
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
it goes back out for another, smaller fix. Its third try fixes under the lock, in the merge worktree. It runs as
`claude -p`. Its prompt (`FIXER` in `runner.py`) includes the tail of the ledger. It either
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

The built-in prompt is the same text for every task up to its last part (F103): the fixed runner brief comes
first and says `<ID>` where the task's id goes, then the task's id, an earlier attempt and `prompt_extra`,
then the task's own paragraphs (concept, review, …) and policies, and the task's brief last. So every slot's
first turn starts with the same words and the model's prompt cache is reused across slots and tasks. A custom
template (`[run] prompt`) keeps the order it gives.

Each session also gets `AGENT_RUNNER=1`, `AGENT_SLOT=<n>` and anything `[run] slot_env` adds in its
environment, so your tools can tell slots apart, for example to give each one its own port or emulator
instance. `AGENT_RUNNER_WORKTREE` names the slot's worktree: while it is set, plan writes (`plan add`,
`note`, `tick` and the other edits) and `done` refuse, with nothing written, when the current directory is in
another project, and say to run the command from that worktree (B103).

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

## Commands

```
agent-runner                           the run in the background (a detached process, its slots hidden), the
                                       prompt straight back; `help` prints the usage
agent-runner attach [run|sN|cN|feed]   the run view (its log, live, and its keys; Ctrl-C leaves it), or a
                                       session's own terminal (Ctrl-b d detaches; Windows: no attach to a ConPTY
                                       session yet, only the log's place; before 1809 the hidden console); feed or
                                       board: agent-runner ui
agent-runner control [N]               a control session in this terminal (c1: the kept one, resumed)
agent-runner control --new [N]         another one beside the run, without taking focus; prints its claude.ai/code link
agent-runner control --new --no-wait   the same, returning once it starts ("control N is starting in a hidden terminal"),
                                       without waiting for its claude.ai/code link
agent-runner control --new --forward   the same, with the person's latest runner-feed message as its first
                                       message, read word for word from the feed's transcript (never retyped
                                       in a shell), and the files or images attached to it named with their
                                       paths; the runner feed hands requests on this way
  … --forward --runner                 the same, opened in agent-runner's own checkout (the clone it runs from,
                                       or a worktree under its [run] home) and labelled with this project: the
                                       feed hands asks about agent-runner itself (updates, releases, its bugs)
                                       on this way
agent-runner pitch [approve|no PITCH]  landed work that waits for a yes to be pushed (### Approve to push): approve
                                       it, or undo it with `no`
agent-runner since [WHEN] [--all|--follow]  what landed, started or got stuck since the last look (or WHEN:
                                       2h, yesterday), as a digest; --all every event; --follow each new one live
agent-runner plan [...]                the task list as a tool (agent-runner plan help)
agent-runner done ID "MSG" [--blocked WHY [--after X,Y]] [--artifact URL] [--no-test]
                                       --artifact: a concept's page (a K task without it takes the URL that
                                       `publish-page` recorded; --page FILE names its copy)
agent-runner run [N|once] [--dry-run] [--model M] [--idle S] [--stall S] [--pause S] [--force] [--shutdown|--suspend]
agent-runner stop [--force] [--suspend|--shutdown]
                                       finish what's running, start nothing new, exit (or s + Enter in the
                                       run view); --force ends the sessions now, to resume next run
agent-runner take ID [--merge|--drop]  one task in your own session or a subagent: a worktree on task/ID
                                       and its prompt; a run keeps off it. --merge after `done` there
agent-runner take "TEXT" --kind K [--files A,B] [--here]
                                       queue it (as `plan add`) and take it in one step; --here (also with
                                       an ID) moves the main checkout's uncommitted edits into the worktree
agent-runner resume ID...              continue each task's last session in its slot, once that slot is free
agent-runner cost [--days N] [--files] where the workers' tokens went, by kind of tool call (--files: by
                                       file read, and exact-repeat commands)
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
glossary = "GLOSSARY.md"  # the project's glossary (`agent-runner glossary`): seeded by the first control session,
                          # named in every brief; false = off (no file written, briefs skip it)

[git]
master_branch = ""        # optional local shared branch; must exist and be checked out
# empty uses remote HEAD, then main/master/trunk, then the current branch
push = "origin"           # where finished work goes; false turns every push off
push_merge = true         # push the shared branch after each tested merge
# with `[run] test` empty (no gate) only when set here: the default never pushes untested merges
land_edited = "wait"      # a tested merge held by uncommitted edits in the main checkout: "wait" for them, or
                          # "wip": move them to a wip/main-checkout-<time> branch and land (see Stopping a run)

[ui]
theme = "ryha"            # the terminal UI's (`ui`) colours: ryha (black, red accent), omarchy
                          # (~/.config/omarchy/current/theme/colors.toml, else ryha), terminal (the terminal's own
                          # 16 colours and background), light. The run app ignores it: it follows the browser's
                          # light or dark setting
web = "app"               # the view the run app's link opens: "app" (the run app) or "terminal" (the terminal-style
                          # page, /term); a browser that switched views opens its last one (see The run app)
chat_quiet = "6h"         # a chat that needs no reply, with nothing said in it for this long, is grayed at the bottom
                          # of the run app's Chats (never c1, a pinned or a renamed one); false: off

[models]                  # the model each type of work runs on (see Models per role below)
code = "opus"             # a task's own session; unset, [run] model sets it
review = "opus"           # the `review` subagent the spec review before done runs in
fix = "opus"              # merge-conflict fix and repair sessions; unset, [run] fix_model sets it
docs = "haiku"            # the `docs` subagent: CHANGELOG, docs, README, journal and plan-text edits; false: none
control = "opus"          # control sessions (c1, c2, …)
feed = "haiku"            # the runner feed, and the one-shot that publishes the run page's claude.ai copy
kinds = { F = "opus", B = "opus", T = "opus", V = "opus", K = "opus", D = "sonnet", C = "sonnet", R = "sonnet" }
                          # a task's own session by its kind (the id's letters: F105 is F); see Models per kind
local = false             # allow a local provider (ollama, or a provider url on localhost or a private address); see Model providers
providers = {}            # the repo's own providers, [models.providers.<name>]; see Model providers
fallback = []             # '<provider>:<model>' to go on with when a provider hits its cap, in order; see Fallback chain

[run]
test = ""                 # the gate, run by `done` and on every merge, e.g. "make test"
test_since = ""           # a merge's gate on what changed since {base}, e.g. "make test-since REV={base}"
full_every_hours = 24     # with test_since: the whole `test` once none has passed for this long; 0 = never
slots = 3
include_task_id_in_commit = true
comment_policy = "normal"
agent = "claude"          # the Claude Code executable a session runs: claude, or a wrapper around it
engine = "terminal"       # terminal = an interactive session in a hidden terminal (the default for now); stream = headless claude -p, stream-json in and out
model = "opus"
lean = true               # sessions get Bash/Read/Edit/Write/Artifact only, no MCP servers or user settings
remote = "auto"           # control sessions on Remote Control, and a control server to start more from claude.ai/code or the Claude apps; Enter in the run view opens it. auto: on where it can work (see Control sessions); true/false force it
remote_slots = false      # the slots on Remote Control too ("<task title> · <repo> s2 · B646"); not
                          # recommended: every slot start pushes to the phone
sessions = "one"          # what the Claude apps list for this project. one: c1, the project's chat; a slot goes
                          # on Remote Control only when opened from `agent-runner ui` (Sessions, session tab), and
                          # the run keeps a claude.ai copy of the run page. each: every slot its own entry (remote_slots)
web = true                # the run app (see The run app), served by the run on web_port for the LAN/Tailscale; its
                          # address, with the token it needs, is in `status` and the run log; false: off
web_port = 8770           # where the run app is served
silent = false            # phone pushes from those sessions after each one's start push (that one cannot be stopped): true = none, false = Claude Code's usual
control = true            # a run opens control session c1 beside it; false: none (`agent-runner control` still works)
control_idle = "3h"       # close idle control sessions 2, 3, … (never c1) once quiet this long, Claude spoke last, its last message does not end on a `DECIDE:` line (that one waits for `control_ask`), and nothing runs in it (a background task or Monitor; the needs-you watch does not count): process ended, controlN.pid removed, transcript kept (`claude --resume <sid>`); false: none closed idle
control_idle_quick = "5m"   # a session opened for one ask (a feed reply, `control --new --ask`) where the person sent only that message, a task got queued (`plan add` printed "added <ID>") and the last message has no `control_open` phrase and no `DECIDE:` line: closed after this instead (looked at every 5 min, so 5-10 min); false: control_idle
control_idle_talked = "12h" # a session the person sent a second message in: closed after this instead, and a `DECIDE:` question in it is filed only after the longer of this and control_ask; false: control_idle (and control_ask for its question). Slash commands (the runner's /rename), hook and system turns are not the person's messages
control_ask = "2h"        # a last message ending on a line `DECIDE: <question>` (the brief asks the session for one only when work waits on the answer): after this long it is filed under Needs you as a DECIDE item (an F task with the question + the session link; answering it reopens the task for a run to carry on), then closed; false: such a session stays open and nothing is filed
control_open = ["?", "want me to", "should i", "shall i", "would you like", "do you want"]  # what makes a last message an offer or open question: not filed, named in the run log when its session closes, never closed by control_idle_quick (case ignored; "?" must end its last paragraph, the rest may stand anywhere in it)
auto_upgrade = true       # upgrade by itself when a newer release is out, as `u` does, once no merge runs; the run restarts on it (false: only `u` or `agent-runner upgrade`)
install_skill = true      # keep the `agent-runner guide` skill in ~/.claude/skills and the user-level SessionStart hook (the control brief in a runner repo's main checkout) in Claude Code's user settings, from every agent-runner command, for sessions a person starts; false: neither is written
rules_pointer = true      # a run adds one line to the rules file (`rules`, else AGENTS.md or CLAUDE.md, never created) pointing every session at the agent-runner skill, committed on its own; never into a file with uncommitted edits or mid-merge; false: never
wizards = true            # an agent blocking with BLOCKED: (a login, a certificate, a secret) also writes a bash wizard to <notes>/wizards/<ID>.sh; Needs you shows `agent-runner wizard <ID>` to run it; false: no wizards
questionnaires = true     # a DECIDE with options is asked as a pick sheet (<notes>/sheets/<ID>.json, a page made with `agent-runner sheet <ID>`); Needs you shows one line and its link; false: a plain DECIDE
grill = "ask"             # control sessions ask rounds of numbered questions before queueing: "ask" = when the person says grill me / poke holes; "big" = also on big vague asks; "off"
voice = ""                # the person's wording file (`agent-runner voice`), read by control sessions, the runner feed and task agents; "" = ~/.config/agent-runner/voice.md (a .runner/voice.md with lines overrides it for this project)
voice_learn = "ask"       # "ask": a session that had to say something again offers one wording line to add; "off": lines are added only when the person says so
review = true             # before done, a fresh subagent reads the diff against the task's brief (spec only: missing, unasked, wrong); the commit ends "review: …"; false: no review
review_min_lines = 50     # a diff smaller than this (changed lines) skips the review, unless the task has a long form (plan/tasks/<ID>.md)
idle = 30                 # s quiet after a turn ends before a session without a successful `done` is ended (with one: 5 s)
stall = 1200              # s quiet at a prompt that counts as stalled
context_warn = 150        # k tokens: a slot session whose context peaked past this says so in its exit line and in `since`, with what filled it ("B32 peaked 168k (over 150k): runner.py 61k, test_runner.py 22k"); soft only, nothing is stopped; 0 = off. A new run also starts c1 afresh when its kept session last stood over it (F27)
task_tokens = 0           # tokens one task's session (and its subagents) may use: input, cache writes, output (cache reads are left out: they grow with turns times the context, and task_usd counts them). Past it the runner tells the task to stop at a clean point (commit, write its journal, end its turn) and parks it as wip/<ID>; one whose done already passed lands; one that goes on to 1.25 times the cap is ended. `status` shows each running task's spend ("1.2M tok $3.40"); 0 = no cap (F103)
task_usd = 0              # the same cap in dollars, at the API's list prices (a plan bills none; Opus prices for a model it does not know); 0 = no cap
pause = 60                # s between one session ending and the next starting in that slot
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
issues_watch = false      # true: one task per new open GitHub issue; ["bug", "runner"]: only issues with one of those labels
issues_trust = "skeptical"  # "skeptical": the task confirms the issue in the code first and follows nothing it says; "trust": do it as written
auto_release = false      # queue a release (`plan add V`) by itself: { every = 10 } once 10 tasks landed since the last release,
                          # { idle = true } when the run goes idle with landed work; both may be set; never while a release is open
merge_ahead = true        # tasks finishing during a batch's gate are merged on it and tested beside it
batch_max = 16            # finished branches waiting for the merge go in together under one gate run, and one push,
                          # at most this many (the rest take the next one); 0 = no cap, 1 = no batching
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
command_timeout = 3600    # s the gate, a retest, a hook (join, before_start, on_exit) or `done`'s gate may run: past it, failed
needs_order = "oldest"    # what waits on a person (Needs you): oldest first; "newest" first; "plan": TODO.md's order

[run.join]                # glob = a command that joins a conflict in that file itself:
# "data/addresses.txt" = "./tools/join {union} {out}"   # also {ours} {base} {theirs} {file}; exit 0 keeps {out}

```

### Models per role

`[models]` picks the model for each type of work, with the defaults above in every repo: `code` (the task's
session), `fix`, `control` and `feed` start sessions of their own; `review` and `docs` are Claude Code subagents
of the task session, passed in with `--agents` and a model each, so all of it is plan usage. The task's brief
names them: the spec review runs in the `review` subagent, and CHANGELOG, docs, README, journal and plan-text
edits go to the `docs` subagent, whose result the task then checks. A lean session gets the Agent tool whenever
one of them is on (`[run] review = false` drops `review`, `[models] docs = false` drops `docs`).

`[run] model` and `[run] fix_model` stay as aliases: they set `code` and `fix` when `[models]` does not, so an
older `model = "opus"` keeps working, and `run --model M` still picks the task model for one run. A role
`[models]` sets wins over them.

### Models per kind

`[models.kinds]` picks the model for a task's own session by its kind, the letters of its id (`F105` is F, `P17a`
is P). The defaults are `opus` for F, B, T, V and K, and `sonnet` for D, C and R; a repo's table is laid over them
kind by kind, so `D = "haiku"` changes only D. A kind not listed runs on `[models] code`. A task names its own
model with `model:` on its line (`plan add D "text" --files a.md --model haiku`, or `plan edit ID --model M`),
which wins over the kind. A task session's model is chosen in this order: the task's own `model:`; `run --model X`
given on the command line (it sets every task without its own); the
`[models.kinds]` entry for its kind; `[models] code`. A resumed session (cut off, failed, or answered after
`run ask`) goes on on the same model. A kind's value must be a model name (a string), or
the run refuses to start with a `[models.kinds]` error. A repo that sets `[models] code` or `[run] model` still gets
the default kinds for F, B, T, V, K, D, C and R; to run every kind on one model, set those kinds in `[models.kinds]`.

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

Local providers (ollama, or a provider whose url is `localhost`, `*.local`, or a loopback, private or link-local
address) are refused unless `[models] local = true` (off by default). Host names are not resolved. `local` can go
in runner.local.toml to allow it on one machine.

An unknown provider prefix is refused at start.

`claude:<model>` runs as the bare model name on Claude Code. A role naming another provider runs its sessions
in the [harness loop](#the-harness-loop).

Only task sessions (`[models] code`, `[models.kinds]`, a task's own `plan add --model`, `run --model`) and fix
sessions (`[models] fix`) can name another provider. `review`, `docs`, `control` and `feed` run as Claude Code
itself (its subagents, Remote Control control sessions, the feed's one-shot), so another provider there is refused
at start, saying why.

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
GEMINI_API_KEY, COPILOT_GITHUB_TOKEN). A model id the provider does not list is refused with the ids it has.

Tools: bash (each call starts in the worktree; timeout default 120 s, at most 3600 s; output over 30000 characters
is cut in the middle), read, edit, write, finish (runs `run finish`), ask (runs `run ask`; the task is parked under
Needs you and the answer resumes the same session), and publish_page (writes the HTML to
`<notes>/harness-pages/<task>/<name>.html`, then runs `run publish-page` on it, up to 420 s, and returns its
output, the URL included). A
`run finish` or `run ask` typed through bash ends the session the same way (it watches the slot's end mark).

The git fence: before every tool call it runs `run fence`, with the same rules as Claude Code sessions' PreToolUse
hook: no git push, reset --hard, clean, or checkout -- .; no edit or write outside the worktree in the main checkout
or another slot. A denied call returns the reason to the model and does not run.

Budgets: before every model call it holds what the session has spent, counted as for `[run] task_tokens` and
`task_usd`: tokens without cache reads; dollars from the provider's own cost when it gives one. Past a cap it stops,
writes the task's budget mark, and the run parks the branch as wip/<ID> as it does for any session over budget. Fix
sessions have no cap (`fix_timeout` holds them).

Tells: a person's `plan tell` (text typed into the hidden slot's terminal) is read from stdin and goes in as the next
user message.

Ending: at finish or ask; or after `idle` seconds at the end of a turn with nothing told; a fix session (`--once`)
ends with its first answer. A transient model error is tried 3 more times. A lasting one ends the session with an
API-error entry, which the run resumes as it would Claude's. With `[models] fallback` set, a quota or usage-limit error switches the session to the chain's next model instead (see Fallback chain).

Transcript: `<notes>/harness-sessions/<session id>.jsonl`, in Claude Code's entry shape (type user/assistant, content
blocks text/tool_use/tool_result, usage in Claude's keys), so status, spend, the exit line's stats and resume read it
as Claude's. Each entry also keeps the provider's message as sent (`harness` field), which a resume reads back, so a
resumed session keeps its whole history.

Not there yet: no Remote Control, no subagents (the review and docs subagents). A fix session starts fresh rather
than as a copy of the task's session.

### The stream engine

`[run] engine = "stream"` runs each slot's Claude Code session headless: `claude -p --input-format stream-json
--output-format stream-json --verbose`, on the same claude.ai login. ANTHROPIC_API_KEY is removed from its
environment, so its usage stays plan usage.

The brief (on a resume, the resume message, with `--resume <session id>`) is the first stream-json user message
on its stdin, so a brief of any length goes in whole.

No idle Stop hook: the session ends at its result event. Its stdin closes at once when nothing was sent during
that turn, otherwise when no next turn starts within 5 s. So `run finish` (then stopping), or a turn that ends
with nothing more to do, ends it. While the agent still runs a background command (a `done` waiting on the gate),
its stdin stays open, as the Stop hook's waiter does, until that command ends, `done` or `run finish` has run, or
`AGENT_RUNNER_IDLE_MAX` (10800 s) has passed.

`plan tell`, budget stops and typing from the Run page go in as its next user message, through the slot's FIFO: typed
text becomes a message at its Enter, and keys such as Escape are dropped. On Windows a stream session takes no tells: it
runs in a hidden console, which takes no typed text (ConPTY is for the other sessions).

Its event stream goes to the slot log, to `<notes>/streams/<session id>.jsonl` (the spend for `[run] task_tokens`
and `task_usd` is read from there), and to `attach sN` and the Run page's Terminal views.

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
  `backend = "pi"`, `agent = "pi"` and `AGENT_RUNNER_BACKEND=pi` fail at start. Name the model in `[models]` as
  `<provider>:<model>` instead.
- `[run] slot_env` keeps its name but defaults to `[]`: every slot gets `AGENT_SLOT=<n>` whatever it says, so
  a `slot_env` no longer needs to repeat it.

Removed since 0.58.0:

- `[plan] release_alone` is ignored, with one warning: tag the release `(alone)` instead (`plan edit V7
  --alone`); any task can run alone that way (F130).

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
```

### Windows CI for a task branch

Windows-only code (ConPTY, attach) cannot run on Linux: run its gate on Windows before the merge. Push with `run done
<ID> "<msg>" --blocked "waits for its Windows run"` (the git fence refuses `git push`; a plain `done` ticks the task and
cannot be repeated after a fix), then `gh workflow run ci.yml --ref task/<ID> -f system=windows` (or `linux`, `both`;
`-f tests="tests/test_windows.py tests/test_cmds.py"` for those files only), which prints the run's link. Wait in the
foreground, again until it ends: `timeout 540 gh run watch <run-id> --exit-status` (exit 124: not yet); `gh run view
<run-id> --log-failed` says why it failed. Once it is green, plain `done`, then `finish`.

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

A slot on Linux cannot run the Windows tests itself. For a quick check, run `tools/windows_vm.sh [--keep] [test
file ...]` first: it runs the test files (default `tests/test_windows.py`) of this worktree, uncommitted changes
included, on the Windows VM, starting the Docker container named by `WINDOWS_VM` (default `windows-vm`) if it is
stopped and stopping it again if it started it (`--keep` leaves it up). The output and exit code come back, and two
callers wait on a lock. Without the container or the ssh key it says so in one line and exits 2 without creating a
VM; then go straight to the Windows CI job run on request for the task branch (T13, `gh workflow run ci.yml --ref
task/<ID>`), which is the proof either way. The settings by environment are in the script's header.
