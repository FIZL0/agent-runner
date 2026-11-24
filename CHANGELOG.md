# Changelog

Semantic versioning; what counts as breaking is in [docs/SETUP.md](docs/SETUP.md#versions).

## Unreleased

- Changed: a typed reply to a DECIDE on Needs you is its answer and runs at once with no session (F181a): `plan confirm ID "<words>"`, or `sheet ID --go` / `sheet ID --picks` for a pick sheet, on the run page and in `agent-runner ui`. Typed replies to other labels still open a new chat.
- Fixed: code in a diff in a session with the run's session theme is readable on the light page (F182). Plain code was mid grey (#616161); it is now the page's text colour, and the syntax colours that share no slot with the session theme's own have a light and a dark page value that reads at 4.5:1 on the added and removed rows. Claude Code draws this code in fixed 256-colour slots no theme names, so only the slots of the theme's base (dark or light) are filled: with a light base, slot 231, other programs' white text, stays white.
- Added: short asks for a person (F156). Every slot brief asks an agent to keep a CONFIRM, DECIDE or BLOCKED line, or a `run ask` question, to one short sentence (about 100 characters at most) and to write the rest to the task's `<notes>/asks/ID.json` (pictures under `<notes>/asks/ID/`): one action per step, words as seen on screen, no file names or code, no secrets. The file stays optional; `done --blocked` on a line over 200 characters that waits on a person and has no ask file says so once, names the file, and blocks all the same. The file and its pictures are removed once the item is answered, ticked or dropped, blocks again, or a new session starts on the task (`### Tasks waiting on a person` in docs/REFERENCE.md).
- Changed: a Needs you item on the run page (Home and Status) is one short card (F162): what is wanted and where in everyday words, the title, at most two lines of what to do, and Press for details. Pressing it opens a popup with the steps, what to see, notes, pictures, the agent's last words and the full task, and a reply box that goes with the answer. It replaces the More/Less fold. A task's `<notes>/asks/ID.json` can give the card and popup their own words, steps, expected list and pictures (`### Tasks waiting on a person` in docs/REFERENCE.md).
- Added: a run restarts on new code by itself (F149). With `[run] auto_upgrade` on (the default), a run from a source checkout restarts between merges once main's agent_runner code has held still for 10 min (at most 1 h after the first change), so one restart covers a batch. It keeps its slots and adopts its sessions. A run page never reloads by itself: a new version shows a popup, "A new version of this page is ready", with Refresh (which keeps what is typed) and Later.
- Changed: with `[run] auto_upgrade` off, nothing restarts a run by itself, not even on a newly installed version (before, any installed non-breaking version restarted it, e.g. after `uv tool upgrade`). `u`, `agent-runner upgrade` and Restart the run still restart it. Where a person must restart the run (auto_upgrade off, a breaking version, Windows), the popup says "A new version is ready. Restart the run to use it." Home's page says the same.
- Fixed: typing on a computer in a chat's session goes to the run page's message box while the agent CLI's prompt is hidden (B190). After a click in the session the keyboard was in the session's frame, so typed words landed in the agent CLI's own prompt, its normally hidden input showed, and Shift+Enter sent the first line alone (a terminal sends it as Enter). Now what is typed or pasted there goes to the message box (Shift+Enter a new line, the text kept whole). If the prompt already shows unsent words, Shift+Enter adds a new line in it. A menu or question still shows the whole window and gets every key. In the message box Enter still sends and Shift+Enter is still a new line.
- Fixed: text of several lines given to a plan change (Needs you answer, note, block, add or edit) is joined by a space in plan/TODO.md (B189). It was written with its newlines, so `run plan ID` and the brief showed only the first line and the agent lost the rest, and a later line that looked like a task line became a task. The task now stays one line and reads back whole; task lines already split are not repaired.
- Fixed: Talk's stop for a reply is the speaker button, not the mic (B174). The speaker is the one stop while a reply is read; the mic never stops it, and a press on it cuts the reply and listens at once. A reply that lands while the mic listens, or while another is read, plays after that, in order, and a sound that never ends is cleared by a check, so Talk no longer says "Speaking…" over silence.
- Added: devices (F169). The run app's Tools view adds the machines and test rigs agents reach over SSH or another way; a project says which it uses (Used here), and each one is a shared tool a task names in `needs:`. Secrets are write-only and kept on this machine (`### Devices` in docs/REFERENCE.md).
- Changed: Settings' Release by itself (Auto release) is two controls, Every (Off, 5, 10, 20 tasks) and When idle, so both can be on; changing one keeps the other, and with both on a count release and an idle one never queue two for the same landed work (F174).
- Changed: a setting saved for everyone is written to runner.toml at once (F173). It is committed alone on the shared branch and pushed as a plan edit is, and never queues a task. The Queued tag, the queued C task and its edit and drop are gone; a task Settings queued before still lands as a plain task.
- Fixed: a finished task that failed its test gate three times is no longer refused a fourth gate once it is fixed (B186). `done` keeps a hash of the worktree's content with each counted failed gate (uncommitted and untracked files count, ignored ones do not). After three failures, unchanged content is refused without a gate and changed content gets one more; a pass ticks and resets the count. Until that gate runs, `--blocked "CONFIRM: …"` is refused, so an agent no longer parks passing work as a false "CONFIRM: mark it done" Needs you item. The slot brief says CONFIRM is only for a check by hand the agent cannot do.
- Changed: no kept project chat (F176). The run opens no control session of its own and resumes none; `[run] control = true` now means it reopens the sessions a shutdown cut off (and, with `[run] remote`, keeps the control server up). Every prompt (the run app's Home box, a Status quick ask, Say what to change, a concept change, a typed Needs you reply, the runner feed) opens a new control session named for its ask, and numbers start at 2; an older c1 is a chat like any other. `agent-runner control` opens a blank one. The control server starts with `--no-create-session-in-dir`, so a stopped server keeps no session and each start gets a new environment.
- Fixed: a phone's Return key no longer sends a message (B181). On a touch phone or tablet Enter makes a new line in every message box, and only Send (or Ctrl/Cmd+Enter on a hardware keyboard) sends; a computer keeps Enter to send.
- Added: `[run] done_test` (F178). A command `done` runs before its commit in place of `test`, on a docs-only diff too (then `docs_check`, if set, runs as well): a build, an audit. A failing one ticks and commits nothing and counts as a failed gate; `--no-test` skips it. Merges still run `test` / `test_since`, so a passing done_test never lets a merge skip its gate (`refs/agent-runner/done-test/<ID>` marks it), and docs-only merges skip the gate as before.
- Added: a warning for a project with no settings file (F178). With no runner.toml, no AGENT_RUNNER_CONFIG file, and no gate or push_merge in runner.local.toml, the run picker and its launcher, the run page's Run card, Home's All projects and the TUI's Status panel say "no settings found, so no test gate and nothing is pushed". A run that is up says what it itself found.
- Fixed: a split task whose attempt was parked runs before its parts (B185). A session that filed parts (F2a, ...) and then failed left its attempt as wip/F2, and the run started F2a first, though F2a builds on F2's first part. Now the parked task goes first and its open subtasks wait until it lands. A `(split into ...)` task, one not parked, and a Stretch or Parked one keep the old order.
- Added: oversized tasks get split (F177). `[run] task_size` (10 by default, 0 = off) sets how big a task may be: its code files (files matching `docs_files` are not counted), plus 2 per numbered outcome, plus 1 per 400 characters of text (a long form is not read; concepts, releases and `(split into ...)` tasks never count as too big). `plan add`, `edit`, `note`, `approve` and `confirm` of a concept say when a task is over it and how to split it; control sessions split a big ask before queueing; the slot brief of such a task has the agent split it first and do only the first part. A task session past `[run] context_warn` is told once, as a turn ends (never mid-edit, not after its done), to commit what is solid, file the rest as a part and finish; nothing stops it if it goes on (both engines and the harness loop). Why 10: of iFizBox's last 383 tasks it flags 45, 39 of which peaked over 150k.
- Fixed: a command stopped for low memory no longer makes the agent ask the person (B184). Claude Code stops a background command when memory is low and says not to start it again unless asked, and an agent then asked. The slot brief now holds that stop as the person's standing go-ahead: the agent commits what is solid and runs `run wait-for memory`. Its slot is given up, its work is kept on waiting/<ID>, and the same session goes on with a message to run the command again once MemAvailable is 2 GB over `min_free_mem_gb` (a pause of a minute per stop). It needs no `[run.tools]` entry, shows on the queue row, `plan` and `status`, and is never a Needs you item. Under `min_free_mem_gb` no new session starts, and a slot's `done` gate waits for memory up to 10 min.
- Fixed: Pick links work through Runner Home (F167). With Home installed, a run listens on 127.0.0.1 only (F165),
  so no Pick link was made. Now a Pick link (`pick-links`, a pick sheet's Send) uses Home's Tailscale Serve https
  address, https://HOST/p/KEY/pick; Home routes GET /p/KEY/pick to the run with no Home token, because the link's
  one-use code is the check and the run checks it. With no run up, the link's page says to start the run. With no
  https address for Home's port, `pick-links` says so and gives the `tailscale serve` command. A run with its own
  https port still gets its Pick links as before where Home does not route it.
- Fixed: `run publish-page` and the run page copy and pitch pages now reach claude.ai (B180). They did not: the one-shot exited 0 with no URL. It had only `--tools Artifact`; Claude Code 2.1.330 then denies Read, and Artifact will not publish a file it may not read. It now has Artifact and Read, and a failed publish logs the end of its errors and answer, so a sign-in warning no longer hides the reason.
- Added: shared tools (F168). `[run.tools.<name>]` in runner.toml names something only one task can use at a time (a test phone, a device) with a `check` that says whether it is free, busy (and by whom) or missing. A task tags itself `needs:` (`plan add --needs`); the run never runs two tasks with the same tool, and holds a tagged task while it is busy or missing (at most 5 min when the check is unknown). An agent that finds its tool busy runs `run wait-for TOOL`: its session ends, its work is kept, and the same session resumes once the tool is free. Status, the TUI and the run page show the tool, and a missing one with tasks waiting is a Needs you item after 3 min. Without the setting nothing changes.
- Changed: Chat on a plan task, a concept or a setting, and Add a task open an empty new chat view at once, titled with what it is about; the session starts with the first message, and an unsent draft is kept per thing (F172).
- Changed: In Talk the chat fills the whole view and runs behind the top bar, the round buttons and the message
  box, which are see-through (solid under reduced transparency). The top bar slides off while the person scrolls
  up and returns on scrolling down or at the end, and the newest words stay clear of it at rest (F171).
- Changed: a chat or slot's real session shows its controls on the page (F170). The lines under Claude's prompt (the
  update notice, the status line, the mode, background shells and agents) lie past the frame's edge, and a chip row above
  the message box holds their controls: Working (Stop), the mode, shells, agents and Update (a sheet with the command,
  run on the run's machine). While Claude works the box has Force send, which interrupts and sends once Claude is at
  rest, beside Stop. `/` lists every command: the run's, Claude Code's, the project's, the person's and the chat's skills.
  Scrolling up hides the chips, box and top bar, with a thin strip that says Working. The session takes the run's own
  Claude Code theme, filled from the page's light or dark.

## 0.62.0 (2026-11-23)

- Changed: the run app's Settings page is rebuilt (F166). About 24 everyday settings sit in Speed and limits, Landing work, Models and Chats, each with its control on its row; the rest are behind Advanced, and commands, paths, patterns and rules behind Project file, read only with "Ask a chat to change it". Each setting says where a change is saved: this device at once (`runner.local.toml`), or everyone as a queued C task on `runner.toml`, shown as Queued until it starts. A row's More… has the other home and Reset. Changed lists what differs from the default, and the lines the run ignores or moved. Search finds names, descriptions and code names, and a card with Restart the run says how many changes wait for a restart. `agent-runner settings` still prints the developer notes.
- Removed: the settings cut (F166). `[run] comment_policy` is ignored (write its wording in `prompt_extra`); `[run] merge_ahead` is always on; `[run] idle`, `stall`, `pause`, `fix_timeout`, `control_idle_quick`, `control_idle_talked` and `control_open` are fixed (30 s, 1200 s, 60 s, 1800 s, 5 min, 12 h, and the built-in phrases), and `run --idle`, `--stall` and `--pause` stay. `[run] model` and `fix_model` move to `[models] code` and `fix`. `[run] sessions` folds into `remote_slots`, now "open" or "always". An old file still works, and the run log has a note.
- Changed: a chat or slot in the run app shows the real Claude Code session through ttyd, filling the space above the message box, in place of the page's own thread (bubbles, folded steps, Older messages, the jump button). The message box keeps its send, attachments, mic, slash menu, drafts, Stop and outbox; a phone gets a touch layer and a key row (F114). Attach works on Windows 10 1809 and later (ConPTY, through a local port), and the `feed` terminal mode is gone.
- Changed: the terminal-style web page is removed (the /term route, `[ui] web`, the Terminal view / App view switch);
  the per-session terminal stays; an old `[ui] web` in runner.toml is ignored (C29).
- Changed: one address for every project (F165). With Runner Home installed, a run's page and its ttyd terminals
  listen on 127.0.0.1 only, on a free port that only Home opens; no link, log line or status names that port. A
  `[run] web_port` the person sets stays open on every interface, unless it is Home's own port. Without Home, the
  first run up keeps port 8770 and a second run listens on 127.0.0.1 only, its status and run log offering
  `agent-runner home install`. Installing Home while runs are up moves each run off the public port within seconds, with no
  restart; after `home uninstall`, a run serves its own page again from its next start. When Home is down while a
  run is up, `status` and the run log say so with the command to start it. On Windows a second run
  can no longer bind the same port as another run. Option links (`pick-links`) need a run page with a port of its own
  (`web_port` set): Home does not route them.
- Added: Home has a Talk button (F164), first in the row under the message box. One press opens Talk in the page,
  without a reload, and the mic does not start by itself. It shows always, as Talk does in the sidebar (where the mic
  cannot listen, Talk is typed).
- Changed: a reload of the run app opens what was open (B177): the view (Home, Talk, Status, Plan, Concepts, Settings
  or All projects) and the open chat or slot, kept per project and per browser tab, drawn in the first frame so Home
  does not flash. A reload never starts the mic or reads an old reply aloud. A link may name a view or a chat (`#plan`,
  `#c3`, `#s1`) and wins over what was kept. With storage blocked the page opens on Home.
- Fixed: Talk's sound over Bluetooth and a bad connection (B178). A reply is read in fewer clips, with silence
  playing between them so the Bluetooth route stays open; the audio session is set for the mic and for playback; a
  pause nobody asked for is undone once per reply. A clip with no answer is tried again twice, then the phone's voice
  reads the rest of that reply with a toast saying so. Toast errors are plain words, and the mic report also logs
  what happened to the sound.
- Fixed: the run app added to a phone's Home Screen stays one app when you switch project (B179). The project
  switcher, All projects, the project cards, Device Vitals and its Home link opened iOS's in-app browser, because
  without a manifest the app's scope was the folder it was added from. The cause was read from the code and not
  reproduced on an iPhone. Home and a run now serve a manifest and an icon behind the token, no-store; a concept's
  View opens inside the app, and links to other sites still open outside.
- Added: control sessions learn when an item they are about is settled elsewhere (F160). A chat about a task or a
  Needs you item (its title starts with the id, or it was opened from that item) gets one typed line from the run when
  someone else drops, changes, confirms, approves, shelves, restores or otherwise settles it. Sessions also re-read an
  item before they ask the person for it.
- Changed: control sessions leave blocked and Needs you items alone: not mentioned, listed, counted or asked
  about in answers, the opening summary or a status, unless they bear on what the person is discussing or the person
  asks ("what needs me?"). A status starts with its headline, with no "Needs you" line or group. A DECIDE line is only
  a question of the session's own about the work under discussion. No unasked pushes of existing items, except the
  needs-you watch of a run without the runner feed (F151).
- Changed: `agent-runner ui` always runs inside tmux. Before, it ran in any terminal and outside tmux its session
  tab showed the feed read-only (v for tool steps, Enter attached full-screen); now started outside tmux it re-execs
  itself in the project's tmux session (a new session named for the folder, or a window in it), and without tmux it
  refuses with exit 2 and the install line. On Windows it refuses (exit 2) and prints the run page's link. The feed
  pane and v are gone; a session with no socket says so with its link (F141).
- Changed: in `agent-runner ui`'s Sessions, n starts a new chat (a control session, without waiting for its link);
  N no longer does. Concepts' N, chat about it, is unchanged (F153).
- Added: run speech (F158). Talk reads replies with speech made on the run's own machine, played in one audio element
  that a tap on the speaker (or a play button, or a typed Send) unlocks, so later replies play by themselves. The default
  voice is Kokoro af_heart; Talk settings list every Kokoro voice, Piper en_US-lessac-medium (light) and the device's own.
  Install with `agent-runner speech install [kokoro|piper]`. With no engine installed, or when one fails, the browser's
  own speech reads as before. Text never leaves the machine.
- Added: approve to push (F98). With `[run] approve = true`, merges land but nothing is pushed until a person approves a
  pitch on Needs you (Approve, or Not this to undo).
- Added: New Talk chat (F157). In Talk the top bar's New chat button is now New Talk chat: it stays in Talk, stops
  listening, reading aloud or waiting for a reply, clears the shown conversation, and the next message opens a fresh
  Talk session; the old chat stays in Chats, open. Before, the button left Talk for an ordinary chat and Talk always
  went on in the live session. Elsewhere (sidebar, other views) New chat is unchanged.
- Changed: the run app reworked in one go, to written rules, `docs/STYLE.md` (F83, with F124, F143, F128, F129, F110,
  F97, B142, B134 and F85). Before and after:
  - Style: sizes, corners, colours and durations were one-offs; now tokens and shared helpers, checked by a test.
  - Motion: the drawer slid and little else moved; now the drawer, the sheet, new cards and messages, the mic and box,
    and state words move, 150 to 250 ms, transform and opacity only, none under reduced motion.
  - Scroll: a click or a refresh in a chat could jump to its end, and new cards pushed the page; now a refresh keeps the
    reading position in every view, a chat follows its newest message unless you scrolled up (a jump button), and a
    send goes to the end. A refresh also waits for a press or a text selection to end.
  - Views: Agents and Activity are one Status view in `agent-runner ui`'s order (needs you, run, usage, landed lately,
    release, log); the run's state shows as a pill on every page (F124).
  - Run controls: the card had slots, pause, force and stop; the rest was missing. Now the everyday ones are on the Run
    card and a More… sheet has every one, with its key: upgrade, restart, suspend, shut down, start, resume a cut-off
    task, release stale claims, moved-aside edits (W show, E restore, O O drop in the TUI). Upgrade, suspend and shut
    down ask first (in the TUI the key twice) (F124).
  - Drawer: the menu button only; now a swipe right from anywhere, following the finger, and left to close (F124).
  - Talk: a 132px mic over a chat box; now 64px mic and speaker with a keyboard button that swaps in the box, a play
    button on each reply, and Talk settings (read aloud, voice, tap or hold, auto listen) (F124).
  - Talk replies: a chat past 200 feed entries stayed on Thinking…; its reply is found by the entry's id (B134).
  - Needs you: Chat set a context on the Project chat; now it opens a new chat that shows the question and its answers
    (F143). No Drop on the page, and no confirm in the TUI; now Drop everywhere, confirmed first (D D in the TUI, D on
    the terminal-style page) (F110).
  - Chats: no sign of one that waits for you; now a dot on it, a dot on the phone's menu button while Home or Concepts
    has a count, and quiet chats gray at the bottom after `[ui] chat_quiet` (6h; false off) (F128).
  - Chat names: only the runner named a chat; now double-click (phone: ⋯, TUI: r) renames it, c1 too, through
    `agent-runner control --rename N NAME` (F129).
  - Settings: a text dump in the terminal; now a Settings view with this device's values and the project's (F97).
  - Queue: a title cut off; now a row folds open to the whole task (F85).
  - Esc in the message box interrupted only an open chat; now the session the page shows: c1 on Home, Talk's in Talk
    (B142).
- **Breaking: `[plan] release_alone` is gone (F130).** Tag the release `(alone)` instead (`plan add V --alone`, or
  `plan edit V7 --alone`; `--no-alone` clears it). Any task can now run alone the same way, so a major rewrite can stop
  other tasks starting beside it. A runner.toml still setting the key gets one warning in the run log and is otherwise
  ignored.
- **Breaking: the Pi backend is gone (F106d).** `[run] agent = "pi"` (any executable named pi, pi.cmd included),
  `[run] backend = "pi"` and `AGENT_RUNNER_BACKEND=pi` now fail at start. Write the model as `<provider>:<model>` in
  `[models]` instead, e.g. `code = "copilot:<model>"`: it runs on the harness loop, and `agent-runner login <provider>`
  (`run login`) adds the provider's login, kept in Pi's `auth.json`. `[run] agent` is now only the Claude Code
  executable (or a wrapper around it); `[run] backend = "claude"` is ignored with a warning, and any other
  `AGENT_RUNNER_BACKEND` value is ignored. `[run] agent = "copilot"` still fails, now pointing to `[models] code =
  "copilot:<model>"`. Also removed: the bundled `pi_hooks.ts` and `pi_idle.ts` extensions, the `.runner/pi-sessions`
  folder, the no-push git config Pi sessions got with `[git] push = false` (the git fence now holds every session),
  and Pi's resume after a failed model call.
- Removed: the terminal UI's chat. `agent-runner ui` has no Status chat tab, no Sessions chat, feed or pane tabs and no
  session message box, so nothing is typed into a session from it, and Ctrl+C always quits. Status tabs are log,
  release and controls (the quick asks s y w u are buttons on the log tab and keys in Status); Sessions tabs are
  session for a control session or an idle slot, and session and diff for a slot on a task; `c` selects c1 (F112).
- Added: `agent-runner ui` shows the real Claude Code session beside its panels. Selecting a session row (cN or sN)
  inside tmux splits a pane running `agent-runner attach cN` (sessions with an attach socket, Linux and macOS), which
  tmux keeps for mouse selection and copy; l, Enter or Ctrl-l focus it, Ctrl-h comes back. Outside tmux the session
  tab shows its feed read-only with its link (o open, y copy), and Enter attaches full-screen (F112).
- Added: Ctrl-f in `agent-runner ui` makes the session full-screen between the UI's top and bottom bars; Ctrl-f again
  puts it side by side. Inside tmux the UI binds Ctrl-f and Ctrl-h in tmux's root table, acting only in its own window
  and passing the key through elsewhere; a key the person already bound is left alone, and quit unbinds them (F112).
- Changed: N ('+ new chat') in `agent-runner ui` no longer blocks up to 90 s for the Remote Control link. It runs
  `agent-runner control --new --no-wait` on a thread, selects a 'c… starting...' row at once, and selects the cN row
  once the run's state lists it (F112).
- Added: `agent-runner control --new --no-wait` returns once the session starts, printing "control N is starting in a
  hidden terminal", without waiting for its claude.ai/code link (F112).
- Changed: offers from control sessions ("Want me to take it right away?") no longer go under Needs you. Only a question
  the session marks with a last `DECIDE: <question>` line is filed there, after `control_ask`; the brief asks for that
  line only when work waits on the answer. Any other quiet control session closes after the usual idle time, and the run
  log names the offer it did not file (F135).
- Changed: the run page (web) answers at once. New chat, a concept's New chat, the Concepts + form, Needs you buttons
  (answers and Later), concept option picks, quick asks, chat messages, Release and Unpark show their result
  immediately and are sent behind. New chat opens straight away as a "starting..." chat you can type into; it starts
  without waiting (`control --new --no-wait`), and what you wrote is sent once the chat is up. Run controls and the
  Talk view still send directly as before (F137).
- Added: the run page's Outbox, kept in the browser (localStorage), holds each such action until the run answers. A
  small pill shows "N sending" or "N failed · tap to see"; after a dropped connection or a reload, actions are sent
  again in order. Each action carries a client id and the run page runs an id only once (the last 500, in memory, so
  a restarted run page forgets them), so a resent New chat never starts two chats. If the run refuses an action it
  stays: a popup lists it with Retry and Discard (a failed message also has Edit, which puts the words back in its
  box), and a Needs you card comes back when its answer failed (F137).
- Fixes: the run page broke while a run was older than the page on disk (after an update, not restarted): Settings never
  loaded, and a Needs you card's Chat stayed in the Outbox as "Not sent: no such action: need_chat" (B164). Now a run
  serves the run app and the terminal-style page it started with until it restarts; a page that still meets an older
  run (unknown action or route) says "This run is older than this page. Restart it." with Restart the run (or
  stop and start it, where there is no restart control). Its Outbox item is kept and sent once the run restarts (a
  confirmed one, like a drop, waits for Retry), and a failed Settings read keeps the settings shown with Try again.
- Fixes: in the harness loop, the finish tool refuses until `done` or `done --blocked` has succeeded for the slot's
  task. It says to run `done`, or `run ask` when only the person can answer, and the session goes on. Before, a
  session could end with its task still open and nothing under Needs you (B155).
- Changed: the queued release shows as its own row on the run page and in the TUI, and `agent-runner status` says it as
  `release: …` instead of `last: V5 waits for everything before it`. With `[run] auto_release` on and no release queued,
  the row reads `Next release · auto at 10 landed: 6/10` (dimmed); a queued V shows `V5 Release · waits for 24 open ahead`,
  then `ready`, `blocked` or `building`. Once it lands, `lately` says `landed: Release 1.2.0 [V5]` and the count restarts
  at 0. J and K move no task past the release, and Enter on the dimmed row opens the release tab (F131).
- Fixes: `run finish`, run from a slot's agent on a `task/<ID>` branch, is refused until `done` or `done --blocked`
  has succeeded, even when the worktree has no uncommitted changes. The refusal says to run `done` or `run ask`. Before,
  B155 guarded only the harness loop's finish tool, so `run finish` typed through bash or in a Claude Code session could
  end the session with its task still open and nothing under Needs you (B156).
- Changed: with `[models] fallback` set, a new task whose model is claude's starts on the chain's first free provider
  when `[run] session_max` or `weekly_max` is reached (not forced), instead of waiting for the reset. A task with no free
  provider still waits, and STOPPED is raised only when such a task is all that could start. Nothing is written to
  capped.json; without a chain tasks are held as before. A session is now resumed only by the kind of agent (Claude Code
  or the harness loop) that ran it; an answered one whose task now runs on the other gets a new session (F142).
- Fixes: a new control session started from the run page or the terminal UI (Chat on a card, Add a task, quick asks,
  Take, Talk, an answer handed on while c1 is off) starts at once. It used to wait about 65 s (5 + 60) looking for its
  message in the runner feed's transcript, and then showed a false note about attached images. Its message stays on
  screen with a starting line until the reply, and any sent message stays until its own text is in the chat (kept over
  a reload); one that does not arrive shows Not delivered with Retry and Discard. A long turn no longer loses the
  person's latest prompt from the chat, and the chat says when older messages are cut off; a message sent mid-turn
  (queued) shows as the person's (B154).
- Fixes: Device Vitals' headroom said "No room for another agent: a usage cap is reached" past `[run] session_max` or
  `weekly_max`, though new tasks start down `[models] fallback` (F142). While a project whose run is up (with none up,
  any project) has a free provider in its chain (not claude, not capped, logged in), the usage cap now sets no limit and
  the line reads e.g. "Room for 6 more agents, on [models] fallback: a usage cap is reached". Memory, CPU and disk limits
  still hold; without a free provider it is as before (B157).
- Fixes: on an iPhone with the keyboard open, the run app's header went off the top and an empty band sat under the
  message box; now the app fits the space above the keyboard, in Talk, Home, Settings and the sheet too. Opening and
  closing the keyboard no longer shows a grey band or pushes the header away (seen on an iPhone 15 Pro, iOS 27), the strip behind Safari's bar has the view's colour, and the Outbox pill no longer
  covers a chat's text (B160).
- Fixes: Talk's mic on an iPhone could end at once with "Heard nothing (error: aborted)" (B162). Now only one speech
  recognizer runs at a time (a start waits for the old one's end, the box's dictation too); an abort before any words
  is retried once by itself, then Talk's status line says what to try in plain words, with the mic mode and the time
  to the error; a hold survives iOS taking the touch (pointercancel) and a redraw. The mic line says "Starting the
  mic…" until sound is really captured, then "Listening…"; the note carries the recognizer's own error message (on an
  iPhone 'aborted' stands for any failure, silence too, so the message tells them apart); a stop that never gets an end
  no longer leaves Talk listening for ever; a listen with no words shows a "Copy mic report" button: the events from
  press to end with times, words counted, not kept. The cause on the person's iPhone is still not proven.
  Hold to talk also heard nothing on an iPhone or iPad (the person's report: mic on 4 s, no words; the cause is not
  proven), so there Talk now works as Tap (tap to start, tap again to send); the mic line and Talk settings say so, the
  saved setting is kept, and other devices keep Hold.
- Fixes: run app on a phone: a vertical scroll could also open the sidebar drawer, and the page scrolled while the
  drawer followed the finger. Now each touch is one thing until the finger lifts: a touch that scrolled never becomes
  a drawer swipe, and during a drawer swipe nothing scrolls; a swipe must also be more nearly sideways (B167).
- Fixes: `run finish` said "`done` has not run" after a `done` that had passed, because a test suite of agent-runner's
  own gate, run in another slot, deleted the slot's finished mark: a run's start in a test cleared the mark of the
  folder it ran in. Now a run clears only its own project's marks; `run finish` also accepts a task whose tick is
  committed on its branch and tested at HEAD, and a `done` again on a ticked, committed task puts the mark back (B172).
- Added: the gate workflow (ci.yml) runs on request for a task branch before its merge (`gh workflow run ci.yml --ref task/<ID> -f
  system=windows`), so Windows-only code can be checked from a Linux slot; see docs/REFERENCE.md (T13).
- Added: `tools/windows_vm.sh` runs test files (default `tests/test_windows.py`) of a worktree, uncommitted changes
  included, on the Windows VM the machine already has, for contributors working on Windows code. It is a repo tool and
  not part of the installed package (T14).
- Changed: Runner Home's footprint walk (every 10 min) now removes ended sessions' temp folders itself and logs in
  Home's service log (the systemd journal) what it freed; before, only the Clean button did. A session has ended when no process names it, Claude
  Code's session registry (`sessions/<pid>.json` under `CLAUDE_CONFIG_DIR` or `~/.claude`) has it not open (pid alive
  with the same procStart), the runner will not resume or wake it (queued resume, unanswered ask, cut-off slot task,
  runner feed, c1's kept conversation, cN with a pid file), and nothing wrote to its folder for 1 h (runner worktrees)
  or 24 h (main checkouts, newly included, in Clean too). With an unreadable or missing registry no main-checkout
  folder goes; without /proc (macOS, Windows) none goes. Each is rechecked just before deletion, and symlinks are never
  followed out of the temp root. Worktrees and wip/ branches still wait for the person in Clean. The fixed 5 GB alert
  is gone: the alert comes when the temp folders left exceed 5% of the disk, names the size and the largest folder, and
  mentions Clean only when it has a temp folder to free; min_free_gb's alert is unchanged. Home's service now keeps
  `CLAUDE_CONFIG_DIR` from the installing shell: re-run `agent-runner home install` if you set it (F144).
- Fixes found by `ci.yml` on Linux and Windows: `agent-runner needs` no longer cuts an ask in the
  middle of a backticked command; a multi-line tell whose line ends are CRLF (as Windows pipes them) no longer doubles
  its newlines in a harness loop session; copying the run page link on Windows works when the clipboard tool is a
  .bat or .cmd (B150).
- Fixes: on Windows, `wizard` works with a default Git for Windows install (its installer puts only Git\cmd on PATH, so
  no bash was found): after PATH it looks for bin\bash.exe beside git, and with none it says in one line that Git Bash
  is missing instead of a traceback. System32's WSL bash is no longer used as a fallback (B159).
- Fixes: Runner Home restarts itself when agent-runner's package files change on disk (an upgrade, or a clone's pull,
  same version or not), once the change holds over two 5 s looks, and never while a request or terminal tunnel is
  open. Before, it kept the version it started with until the service restarted (B165).
- Fixes: on Windows Home restarts its scheduled task for the same reason; and Home run by pythonw.exe no longer
  stops at its start for want of a stdout (it crashed with AttributeError), its output goes to home.log. A Home older
  than this needs one sign out and in (or `home install`) to pick it up (F152).
- Added: on Windows 10 1809 and later, slots, c1 and other control sessions run in a ConPTY pseudo-console (stdlib
  `ctypes`, 200 by 50) instead of a hidden console. Their output goes to `.runner/slotN.log` and `controlN.log`, and
  `plan tell`, budget stops, a typed `/rename` and the run page's send and keys reach them. Before 1809 the hidden
  console stays; headless stream slots are unchanged. `attach sN`, `attach cN` and `attach N` do not attach to a ConPTY
  session yet (they print where the log is), and `agent-runner list` lists control sessions on Windows too (F145).
- Fixes: a person's messages to a control session that hit the usage limit were lost, since Claude Code answers such a
  message with only an error and never retries it. They are now held and typed into the session in one message once the
  limit is over; `status` says how many are waiting and when they go (B170).
- Fixes: a person's message to a control session was also lost when its reply had begun and the usage limit cut it
  off, and when the session was started from a Claude app (through the control server). Both are now held too. The
  runner cannot type into an app session, so once the limit is over it copies that conversation into a numbered
  control session and types the held messages in there, once; the app chat itself is left as it is. Messages of an app
  chat the person closed, or that were answered there meanwhile, are left alone (B173).
- Fixes: a repair session's `FLAKE:` line was split on spaces as well as commas, so one quoted test name was filed as
  several flaky-test tasks (four critical tasks for one flake). It is now split on commas only, a quoted or backticked
  name stays whole, and the repair prompt states the names format (B176).

## 0.61.0 (2026-11-23)

- Added: the run page (web) deletes chats. Each row in the Chats list has a trash button, shown on hover (always
  on touch screens); the Project chat (c1) has none. A click deletes at once, no confirm: the row dims and an Undo
  button takes the trash button's spot until the person clicks anything else or leaves the page, and only then is
  the delete sent. Ctrl/Cmd+click picks chats, Shift+click picks a range from the last one clicked; with 2 or more
  picked a "Delete N" bar shows, with the same Undo, and Esc drops the pick. Deleting ends the control session (its
  process, pid file and title go; the transcript stays, resumable), so it leaves the list and no run start reopens
  it. New ui_model action `delete_chats {names: [...]}` refuses a list naming c1, backed by
  `control.end_control(n, why)` (F118).
- Added: the TUI drops with `d` in every left panel that lists things, with the panel focused. Sessions [2]: on a
  slot working on a task it drops the task (as `D` did); on a control session cN (N>1) it closes it: its process,
  controlN.pid and controlN.title go, the transcript stays (resumable), and the run log says "control N: closed
  from the TUI"; on c1 it only says c1 is the run's kept session. Queue [3] drops the task, Needs you [4] drops the
  item (plan drop), Concepts [5] drops the concept; Status [1] has nothing to drop. `D` stays as an alias where it
  worked before (a slot's task, a queued task). The bottom hint line and the `?` keys list show `d` where it
  applies; in the main pane `d` is not a drop key (a pick's `d` option keeps it). New function
  `control.close_from_tui(n)` (F116).

## 0.60.0 (2026-11-23)

- Added: runner tools on Claude Code. `agent-runner finish "summary"` ends a slot's session at once after
  `done`, its summary in the run log. `agent-runner ask "question"` parks the task under Needs you (`DECIDE:`),
  its work kept on `asked/<ID>`; the person's answer resumes that same session with the answer as its next
  message. A git fence (a PreToolUse hook in every slot's `--settings`) denies `git push`, `git reset --hard`,
  `git clean`, `git checkout -- .` and edits in the main checkout or another slot; it replaces the no-push git
  config, which only Pi keeps (F102).
- Added: Device Vitals in Runner Home. Home lists Devices, one card per machine with a plain verdict ("Room for
  3 more agents", or its top problem) and CPU, GPU, RAM and disk meters; a card opens that machine's vitals:
  Headroom (the smallest of the memory, CPU-load, disk-above-`min_free_gb` and usage-cap limits, at most 6, with
  a + slot button), Machine (CPU, GPU, memory, disk and temperatures, each with a 24 h sparkline from samples
  Home takes every 30 s and keeps for a day, about 300 KB), Runner footprint (worktrees, session temp folders,
  logs, `wip/` branches, each sized) with a Clean that lists what it removes first and only removes ended
  sessions' temp folders, worktrees merged into the main branch (run off, nothing uncommitted) and the `wip/`
  branches you tick, Sessions (CPU and memory per slot and control session), and More for per-core, every
  sensor, top processes and the largest folders. Disk under `min_free_gb`, a CPU or GPU at 90 °C, memory nearly
  full and session temp folders over 5 GB show under Needs you on Home and go to each running project's runner
  feed, which pushes them. Homes find each other through `agent-runner home peer add LINK` (`peer remove`,
  `peers`) or Tailscale (a tailnet machine whose Home takes this Home's token), so one Home shows every device.
  Read with the standard library; what a machine cannot read is hidden, never shown as zero (F95).
- Added: Runner Home. `agent-runner home install` sets up an always-on per-user service (systemd `--user` with
  linger on Linux, launchd on macOS, a scheduled task on Windows) that serves one token-gated page on port 8770
  listing every project (folders in `~/repos` with a `runner.toml`, plus `home add PATH`): running, idle or
  off, what needs you, and Start run, Pause, ±1 slot and Stop. Open routes to the project's run app through
  Home, so one link reaches every run. Install prints the link and a QR code; `home status`, `home list`,
  `home remove PATH` and `home uninstall` go with it. Off until installed. With Home installed, a run that finds
  its page port taken serves its page on a free port, which Home opens; without Home nothing changes (F94).
- **Breaking: a run on 0.59 or older cannot adopt across 0.60.0** (its sessions are in tmux panes this version
  no longer reads), so stop the old run (`agent-runner stop`) before upgrading; it neither auto-upgrades nor
  restarts itself onto 0.60+ (C28).
- 0.60.0 replaces the 1.0.0 tag published earlier the same day, and the v1.0.0 tag and GitHub release
  have been deleted (v0.60.0 is the Latest release). A run already installed at 1.0.0 must be reinstalled
  (`uv tool install --force` or re-pull) to get 0.60.0 and later, since it sees them as older (F119).
- Changed: a release (kind V) no longer runs alone. It still waits for what is ahead of it (`after: all`, or
  its own `--after`) to land, then starts even with other tasks running, and tasks start beside it. While it
  is busy the merge holds every other merge and push, so it releases exactly what was on main when it
  started; the run log and the dry run say why (`T5: waits to merge: V10 is releasing`). `[plan]
  release_alone = true` keeps the old behaviour (nothing beside it) (F99, F100).
- Breaking: tmux is gone. Every OS runs the hidden way, as Windows already did: each slot, c1 and every other
  control session, and the runner feed run in a terminal with no window (a pty shim; Windows: a hidden
  console). Bare `agent-runner` starts the run as a detached process (no `ar-<repo>` tmux session, no
  default-command panes), and `agent-runner run 3` runs in the foreground of its terminal. `[run] mux` and
  `run --mux` are removed: a leftover `mux` key is ignored with one warning line (C26).
- `agent-runner attach` (and `attach run`) is the run view: the run's log, followed live, and the runner keys
  typed there (`s`, `s!`, `p`, `f`, `+`, `-`, `slots N`, `z`, `x`, `u`, `?`, and an empty line for Remote
  Control), each posted to the run through `.runner/KEYS`, so it works from any terminal and over ssh. Ctrl-C
  leaves it and the run keeps going. `attach sN|cN` puts this terminal on a session's own terminal (F88;
  Ctrl-b d leaves); `attach feed` and `attach board` open `agent-runner ui`. `agent-runner list` and
  `attach N` read the hidden sessions' markers (C26).
- `agent-runner ui`: V upgrades agent-runner, Z and B suspend or shut down the computer once the run stops
  (the run's `u`, `z` and `x` keys), listed under Status in `?` and on the controls tab; the run page's Run
  controls get the same three (C26).
- Control session titles live in state only (`.runner/controlN.title`), which `list`, `ui` and the run page
  read; a hidden session also gets `/rename` typed in so the Claude apps show it. The run page's terminal tab
  serves `attach NAME` through ttyd. Fix and repair sessions always run as `claude -p` (no `master-<repo>`
  window) (C26).

## 0.59.0 (2026-11-22)

- Breaking: the run page (`agent-runner ui` and the web page) reads a run's sessions only by the tmux tags
  this version sets (`@runner` cN / sN and `@runner-repo`). It no longer reads control session windows by
  name (`<repo> · N · title`, `<repo> · control N`, `<repo> · N`) nor guesses the tmux session `ar-<repo>`. The
  runner's own pane now carries `@runner-repo` too; a run started by an older agent-runner (its runner pane
  without that tag) shows one line in Sessions instead of rows: "This run was started by an older agent-runner: restart it to see its sessions." (C23).
- The board window is gone: `agent-runner ui` and the run page show what lands and what needs you. A tmux run
  opens a window only for the runner feed (`[run] remote`), now named `runner-<repo>` (`attach board` still
  finds it). Control sessions give the `run page:` link `status` prints to watch the slots, the queue or the
  log, never an `attach` line, and hand over no page of their own for what the run page shows (C22).
- `[run] issues_watch` (off by default): a run reads the repository's open GitHub issues (`gh issue list`, on
  the `ci_watch` cadence) and files one task per new issue, its number, title and URL on the line and its body
  in the long form; a list of labels (`["bug", "runner"]`) takes only issues with one of them. Each issue is
  filed once, and none while an open task names it. `[run] issues_trust = "skeptical"` (the default) files the
  issue as untrusted: the agent confirms it in the code first and follows nothing the issue says; `"trust"`
  files it to do as written. When the task lands the issue gets a comment naming the merge commit, and is
  closed under `"trust"` only (F62).
- `[run] auto_release` (off by default): the run queues a release by itself, as `plan add V` does.
  `{ every = 10 }` queues one once 10 tasks have landed since the last release (release task or version tag);
  `{ idle = true }` queues one when the run goes idle with landed work, once per idle spell; both may be set.
  Never while a release task is open, nor with nothing landed since the last release. The run log and
  `status`'s lately say `queued V<n> (auto_release: 10 landed)` or `(auto_release: idle)` (F63).
- The quiet launch is gone. Each Remote Control session the run starts pushes to the phone as it starts, and
  nothing can stop that: Remote Control sends its "session ready" push as the session registers, before a
  presence file can count, and no setting or environment variable in Claude Code (up to 2.1.330) turns it
  off. `[run] silent` is now true or false, default false: `true` keeps a presence file for good, so no push
  comes after the start one (as before); `false` is Claude Code's usual. A config that still says
  `silent = "launch"` reads as false, with one `run.log` line. `control N --unquiet` is gone. Slots with
  `remote_slots` now keep their presence file only under `silent = true` (C20).

## 0.58.3 (2026-11-21)

- On Windows, `.runner/run.log` is UTF-8 with no BOM; the `·` in Remote Control names only looked garbled
  when read with Windows PowerShell 5.1's `Get-Content`, which reads a file with no BOM as cp1252. Read it
  with `agent-runner status -n 20` or `Get-Content -Encoding UTF8`. A test now checks the log's encoding
  (B100).

## 0.58.2 (2026-11-21)

- Control sessions in a wrapped repo name `[run] command` (e.g. openmx's `./kit`) in their brief, as the
  runner feed does since B92 (B93).
- New panes in the background tmux session (`ar-<repo>`) open the control session again: its default-command
  and environment target `=sess:`, since tmux 3.8 rejects a bare `=sess` and new panes opened a plain shell
  (B94).
- An inline concept page is updated, not queued, when a reply praises it but asks a question or a change; only
  a plain go ("build it", "queue it", "go with B") queues the build (B95).
- A handed-on ask (`control --new --ask`, from the runner feed) that gets number 1 starts a fresh session
  under its given name instead of resuming c1's kept session (B96).
- `upgrade` picks how to update by agent-runner's own install, not `sys.prefix`: a clone pulls, pipx upgrades
  with pipx, any other install with `uv tool`. A wrapper running system python3 with uv's packages no longer
  runs `git pull` in site-packages (B97).
- The control brief stays under 9,500 characters (Claude Code showed only a 2KB preview of the 21.8KB brief):
  the core rules are inline and the long ones behind `guide <topic>` (summary, output, queue, watch, settings,
  glossary, voice); a long voice file is pointed at (B98).
- `plan add V` skips the duplicate check, so a release whose text names the work it waits for adds without
  `--force` (B99).

## 0.58.1 (2026-11-21)

- The runner feed in a wrapped repo names `[run] command` (e.g. openmx's `./kit`) in its prompt and hints, and
  allows both that command and the runner itself, so it can hand an ask to a control session. Before, it named
  the bare runner, which skipped the wrapper's settings, and refused the wrapper's own command (B92).

## 0.58.0 (2026-11-21)

- Fewer settings (C14, from the R7 audit). An old runner.toml or runner.local.toml still works: each old key
  is logged at the run's start with what to write instead, and a renamed one still applies under its new name.
  - `[run] backend` is gone: the backend follows `agent` (an executable named `pi` runs on Pi) and
    `AGENT_RUNNER_BACKEND=claude|pi`. An old `backend = "pi"` is read as `agent = "pi"` (beside a wrapper not
    named pi it still runs on Pi); write `agent = "pi"`, or set `AGENT_RUNNER_BACKEND=pi` for a wrapper.
  - `[run] batch` is folded into `batch_max`: `batch_max = 1` is no batching. An old `batch = false` is read
    as `batch_max = 1`; past `max_unmerged`, that holds one slot free per extra waiting task (the half-batch
    step is 1).
  - Every slot gets `AGENT_SLOT=<n>`, and `[run] slot_env` (now `[]` by default) only adds to it. Before,
    setting `slot_env` dropped `AGENT_SLOT` unless it was repeated.
  - `[run] control_close` is folded into `control_idle`: `control_idle = false` closes no idle control session.
    An old `control_close = false` is read as `control_idle = false`.
  - `[run] control_ask_idle`, `control_file_asks` and `control_ask_kind` become one `control_ask = "2h"`:
    false keeps a session waiting on its open question open (nothing filed). An old `control_ask_idle` is
    read as `control_ask`; an open question is always filed (as an F task) before its session closes.
  - The `[needs]` table is gone: its heading is always "Needs you" and each item shows its age; its order is
    `[run] needs_order`. An old `[needs] order` is read as `[run] needs_order`.
  - `[run] flaky_kind` (T), `ci_kind` (B) and `control_ask_kind` (F) are constants.
  - `[run] timeout` is renamed `command_timeout` (it covers the gate, a retest, hook commands and `done`'s
    gate); an old `timeout` is read as `command_timeout`.
  - `agent-runner settings` comments no longer start with a task id (`B26:`, `F17:`, …).
- A run with no test gate (`[run] test` empty) says so: the run's start, `run --dry-run` and `status` show
  "WARNING no test gate ([run] test is empty): merges go to main untested", and its merges stay local unless
  the config sets `[git] push_merge` itself; each merge logs the `git push` to publish it. Before, it merged
  and pushed untested work without a word (B36).
- A hand plan edit in the main checkout no longer pushes the shared branch when merges stay local (no test
  gate and `[git] push_merge` not set, or `push_merge = false`): it warns "merges stay local, and this edit
  with them" and names the `git push` to publish them. Before, it published the untested merges a run had
  kept local (B86).
- `agent-runner cost --files` names what to split or stop re-reading: each file read (a Read, or what `cat`,
  `sed`, `grep`, … printed) by its results' tokens times the turns they stayed in context, with its
  re-reads, then the tokens exact-repeat commands added after their first run. In 20 slot sessions,
  `runner.py` held 25% of file-read tokens and 95 of its 110 reads were re-reads (F26).
- Two slots that file the same follow-up no longer give two tasks: before a merge, each task the branch added
  is held against the open tasks the target branch got since the branch forked (`plan add`'s same likeness
  check), and on a strong match it goes into that task as a note ("N2 filed the same as Y2 (folded at the
  merge): …"), logged as "folded Y2 into Y1"; lines the branch wrote that name it name the kept one. Before,
  `plan add` in a slot saw only that branch's plan, and two sessions did the same work (B33).
- c1 no longer grows until it compacts: when a person starts a new run and c1's kept session last stood over
  `[run] context_warn` (150k by default), c1 starts a fresh session and its opening summary says so in one
  line; 4 of 32 control sessions had passed 150k. A restart keeps the session whatever its size: the
  self-restart on an upgrade, a run within 6 hours of a crash, kill or Ctrl-C, and a run started within 5
  minutes of the last one ending (F27).
- A slot session whose context grew too big says so: past `[run] context_warn` (150k tokens by default, 0
  off), its exit line and `since` add e.g. `B32 peaked 168k (over 150k): runner.py 61k, test_runner.py 22k`,
  the files (or kinds of call) whose results filled it most. 10 of 51 slot sessions in two weeks passed 100k
  unseen. Soft only: nothing is stopped; the fix is a smaller task or a split file (F25).
- A hidden run on Linux and macOS (no tmux, or started outside a tmux session) now has control sessions: c1
  starts with it, and `control --new` no longer fails with "no tmux session", each in a terminal with no
  window through the hidden slots' shim, its output in `.runner/control<N>.log` (with `[run] remote`,
  `control --new` still prints its claude.ai/code link). A hidden run has no board window, so its control
  sessions keep their own needs-you watch instead of counting on a runner feed that is not there (F59).
- `status`'s `merged N in the last 24h` counts tasks, not merge commits: a task that fast-forwards (the
  first task of a fresh repo, or any whose branch main had not moved past) now counts, and a task that left
  two merge commits, or merged twice, counts once. It reads the run log's landed tasks, and with no run log
  the task ids heading the main branch's commit subjects (B78).
- When Claude Code changes something agent-runner reads from its internals, you are told instead of things
  going quiet: a transcript with none of the entry types it knows, a Remote Control pane that shows no
  claude.ai/code link in time, or `remoteDialogSeen` gone from `~/.claude.json` each give one needs-you line
  per Claude Code version, `<project> needs you: Claude Code X changed Y; Z no longer works`, in the runner
  feed and the control sessions' watch. Local only: nothing is filed (B45).
- A style for the future too: approve a concept's style and say it holds from now on, and the control session
  shows a restyle page (each current page or screen that changes, before and after) and runs `plan restyle
  "<style>" --page <url>`. Every queued task that touches the interface is held on it, kept; a running one is
  told to stop at a clean point, commit and write its journal, and is parked as `wip/<ID>` (one already in its
  test gate or merging lands, listed on the page). Approving the restyle reopens them all with the style in
  their note. `--dry` lists what it would hold, park and let land (F19).
- Your wording sticks: a voice file you shape by talking. "say X not Y", "shorter", "no ids" or "stop calling
  it Z" makes a control session add one line (`agent-runner voice add`, naming the file it went to); when you
  ask "what?" or rephrase what it said, it says it again plainly and offers one line to add, added only on
  yes (`[run] voice_learn = "off"` stops the offers). The global file is `~/.config/agent-runner/voice.md`
  (`[run] voice` moves it); a `.runner/voice.md` with lines overrides it for one project (`voice add
  --project` starts it as a copy of the global lines). Every control session's brief, the runner feed's
  system prompt and the task agents' brief (for the commit messages status and since show) carry it. "show
  my wording" is `voice show`, "forget X" is `voice forget X`, which removes one line and lists the matches
  when several hold X (F21).
- Needs you lines name their project, so a person who runs several knows which control session to answer in:
  status and since head the list `iFizBox needs you:`, `since --follow --needs-you` prints `iFizBox needs you:
  … [R43]` (`iFizBox: looks stuck: …` for the others), and a held run's desktop notice says `iFizBox needs
  you: run stopped: …`. Answers stay in their own project: `plan confirm|change|shelve` with an id only another
  project has says `nothing needs you here about 'R43' in <project>` and changes nothing (F33).

## 0.57.0 (2026-11-20)

- A release kind, `V`. `plan add V` files a release at the end of Next that waits for everything ahead of it
  (`after: all`, no `--after` needed), with the default release brief when given no text (bump the version,
  move CHANGELOG Unreleased under it, commit to main, check the release workflow and `gh release view`). It
  runs alone: the run starts it only once no other task runs or waits to merge, and starts nothing beside it,
  so it releases exactly what landed. `plan add V --now` (or `--pri critical`) files an interim release that
  does not wait. A release is never refused as a duplicate of another one (F38).
- Research tasks merge only their findings. A task whose kind means research (`R`, or a repo's own `[plan]
  kinds` entry that starts "research") lands when its diff changes only the plan directory, the journal or
  the new `[run] findings` globs (default `docs/research/**`, `research/**`). One that touches code is parked
  and blocks with `DECIDE:` naming the code files: answer `follow-up` or `merge anyway`. Its brief says to
  write findings, queue follow-ups with `plan add` and change no code (F36).

## 0.56.0 (2026-11-20)

- No more stray `%9/.runner/run.log` folders in the repo (or `tests/`). A control test stubbed every
  `subprocess.run` with a tmux pane id, git's answer included, so `log()` took "%9" for the main checkout and
  made it in the current directory. `toplevel` and `main_checkout` now take git's answer only when it is an
  absolute, existing directory (`toplevel` stops with an error, `main_checkout` falls back to the checkout),
  and the test stubs answer only tmux (B52).
- `--after all`: a task that waits for everything queued ahead of it, worked out live, so a release needs no
  wait list kept up by hand. `plan add`, `plan edit` and `plan block` take it, for any kind of task; the task
  starts once no open or blocked task above it in TODO.md remains, in any section, tasks queued above it later
  included. Parked (`--pri later`) and Stretch tasks and shelved ones don't hold it. `status`, `plan ID`,
  `plan reopen` and `plan waiting` show `T5 waits for everything before it (N open)` instead of an id list
  (F35).
- One hidden slot mode for every OS, tmux optional. A hidden slot runs in a terminal with no window: on Linux
  and macOS a pseudo-terminal from Python's standard library (`pty`), its output in `.runner/slotN.log` and
  `plan tell` typed into it through `.runner/slotN.in`; on Windows a console of its own whose window starts
  hidden. Each runs through a detached `run --slot-shim`, so a restarted run adopts it, and lands through the
  same worktree, `done`, gate and merge as a tmux slot. You watch it through `status`, control sessions and,
  with `[run] remote_slots`, Remote Control. `[run] mux` / `--mux` is `tmux` or `hidden`; the default is tmux
  inside a tmux session, else hidden, so a run without tmux (or outside a tmux session) is hidden, not an
  error, and bare `agent-runner` without tmux starts the run as a detached process. **Breaking:** the
  sequential run (`--no-tmux`, `mux = "none"`, the no-tmux fallback that committed in your checkout with no
  worktree and no merge gate), Windows Terminal tabs (`wt`) and visible console windows (`console`) are gone;
  `--no-tmux` is refused, and `wt`, `console` and `none` in `[run] mux` run hidden. `remote_slots` stays off
  by default and is now marked not recommended (every slot start pushes to the phone) (F40).
- Control sessions grill before queueing (after mattpocock/skills grilling, domain-modeling and to-tickets, MIT):
  on "grill me", "poke holes" or "stress-test it" they ask rounds of numbered questions, each with its
  recommended answer and worded so yes accepts it, look facts up themselves instead of asking, take one reply per
  round (`yes`, or `1b 2a` as on a pick sheet), and stop when nothing is left open. Settled words go to the
  glossary, an ADR is offered only for a hard-to-reverse trade-off, and the task's text carries the answers; an
  ask that becomes several tasks is shown as a numbered breakdown of vertical slices (prefactor first, ordered
  with `--after`) and queued on one yes. `agent-runner guide grill` holds the how. New `[run] grill`: `ask` (the
  default, only when asked), `big` (also before queueing a big or vague feature ask) or `off`. GLOSSARY.md gains
  same work and sweep (F20).
- Every repo the runner works keeps a GLOSSARY.md: each entry names one thing as the person says it, as the app
  shows it and as the code calls it, with a plain definition and the words to avoid. New command `agent-runner
  glossary [TERM]` (`show`, `add`, `forget`, `seed FILE`, `scan [WORD]`) writes it and commits itself in the
  main checkout, as plan commands do; a repo with none gets one on the first add. The first control session in a
  repo without one seeds 10-20 terms from the app's UI strings and code names straight away; control sessions
  add a term the person uses without asking and mention it in passing, offer a rename when the person, screen
  and code use three words for one thing, re-say things in glossary terms on "what?", and offer an ADR only for
  a hard-to-reverse, surprising trade-off. Slot prompts say to name new things with its terms and add new ones.
  `[plan] glossary` names the file; `false` turns it off (F22).
- Run events are structured: `log()` takes an event kind and task id, and each line with one is also a record
  `{time, kind, id, text}` (plus its fields: `why`, `left`, `slots`) in `<notes>/events.jsonl`. `since`,
  `since --follow` (and so the runner feed and its phone pushes), `status`'s "lately", the stop countdown and
  the background launch's wait for the run read those fields instead of matching run.log's prose, so
  rewording a log message changes nothing they print. run.log stays the plain log a person reads; its lines
  from before events.jsonl existed are still read for since and status. The runner's pane colours a line by
  its kind (F41).
- GLOSSARY.md (after mattpocock/skills domain-modeling, MIT) names agent-runner's own words once each: run,
  slot, task, kind, control session, c1, runner feed, board, take, gate, fixer, merge worktree, concept, Needs
  you (CONFIRM, DECIDE, BLOCKED), shelve, claim, notes dir, remote; each with a plain definition and the words
  to avoid. The slot prompt and the control brief now say in one line to use a repo's GLOSSARY.md terms when it
  has one (any project the runner works), and the control brief says c1, not "control 1" (D1).
- Docs-only changes skip the slow test gate, decided by the diff, not the task's letter: a merge (or `done`)
  whose files all match the new `[run] docs_files` (default `*.md`, `docs/**`) runs only `[run] docs_check`
  (a link/anchor check, if set) and logs `docs only, gate skipped`; a mixed diff runs the gate as before. A
  take or slot task that only edits docs or the plan no longer needs a hand-typed `--no-test` (F37).
- `[run] auto_upgrade` defaults to true: a run upgrades agent-runner by itself when a newer release is out
  (once no merge runs, never across a major version, nor on Windows) and restarts on it. Set
  `auto_upgrade = false` to upgrade only with `u` or `agent-runner upgrade`. `run --upgrade` is gone: `u`,
  `agent-runner upgrade` and the auto upgrade cover it (C6).
- The control brief and the agent-runner skill (GUIDE) are rewritten after mattpocock/skills
  writing-for-agents (MIT): the control brief is 3,886 words down to 2,794, GUIDE 1,333 down to 1,011 (what
  every session loads; the three topic pages below, 1,036 words in all, load only when their case comes up).
  What only one branch needs moved behind a pointer: `agent-runner guide take` (doing a task here, now), `guide
  concepts` (show options inline, approve or revise a queued concept) and `guide needs` (answering what needs
  the person: confirm/change/shelve, wizards, pick sheets) print it, and GUIDE and the control brief say when
  to read each. Prohibitions now come with the positive target ("keep the main checkout clean", "start it
  only when asked"), restatements of `--help` (plan subcommands, stop/pause flags) are gone, and the summary
  steps are numbered once. The slot prompt and the merge fixer and repair prompts state the same rules as
  what to do. Every behaviour is kept; the tests now check the moved rules in their topic pages (C2).

## 0.55.0 (2026-11-20)

- `agent_runner/runner.py` (9,100 lines) is split by responsibility into thirteen modules, each under 1,500
  lines and importing only those below it: `state`, `brief`, `sched`, `slots`, `watch`, `join`, `land`,
  `merge`, `control`, `status`, `feed`, `loop`, `cmds` (runner.py's docstring lists what each holds). Code
  moved, behaviour unchanged: `runner` re-exports every name, and `runner.X = v` still reaches every module
  that uses X. Open tasks that named runner.py now name the modules they touch, so they can run side by
  side (C3).

- Idle control sessions close at two more speeds: one the runner opened for a single ask (a reply from the
  feed) that ended with a task queued, no open question and no second message from the person closes after
  `[run] control_idle_quick` (5 min); one the person sent a second message in stays `[run]
  control_idle_talked` (12 h). Everything else keeps `control_idle`; false turns a
  tier off, and c1 is still never closed. The runner's `/rename` and hook or system turns no longer count as
  the person speaking last (F56).

- Control sessions push what the person asked to hear: "notify me when" on the session's own background
  work (a subagent or `take` it started) now ends in a PushNotification when that work reports, not just a
  line in the conversation; finished or stuck takes and anything that needs the person are pushed unasked
  while they are away, and a session that cannot push says so instead of promising to (B81).
- `agent-runner settings` prints every runner.toml key with its default and what it does, generated from
  the runner's own defaults (and their comments), with where to set it (runner.toml vs runner.local.toml),
  how (a runner.toml change through `take`, never in the main checkout) and when it applies (the next run).
  The skill (`guide`) and the control brief point at it and recommend a change in one line,
  `[table] key = value`, when what the person says fits a real key (too many control sessions:
  `control_idle`; fewer agents: `slots`; no phone pushes: `silent`), and make it on yes (B28).

- Slots verify before asking: the slot brief tells agents to try `~/.claude/ACCESS.md` and the `## Tools`
  section of the repo's CLAUDE.md (ssh hosts, preview servers, headless checks) before turning a check into
  an F task for a person. `agent-runner setup` adds an empty `## Tools` heading to CLAUDE.md
  when it has none (B80).

- A session opened by hand in a runner repo where no run has started yet (a fresh repo in the desktop app)
  gets the control brief too: any agent-runner command adds, once, a SessionStart hook
  (`control --brief --user`) to Claude Code's user settings (`~/.claude/settings.json`). It prints the brief
  only in the main checkout of a repo with `runner.toml`, `plan/TODO.md` or `.runner`, and nothing in a slot
  worktree, a control session the runner started, a repo whose own F53 hook prints it, or anywhere else;
  it is quick and silent on any error. `[run] install_skill = false` turns it off with the skill (B79).

- `[run] control_idle` defaults to 3h (was 1h): idle control sessions 2, 3, … close after 3 hours quiet;
  `control_ask_idle` stays 2h (T11).

- `plan edit ID "TEXT"` corrects a task in place: TEXT replaces its whole description, appended notes included,
  so a corrected instruction no longer sits after the stale one; the id, checkbox, BLOCKED text, follow-up tag
  and `| files:`/`after:`/… fields stay. `--files`, `--after`, `--test`, `--journal` change those fields, and
  `--pri` retags the task and moves it where `add` files that level. It commits as `plan: edit ID`, goes back
  in the pool like a noted task, and a slot running it is told "Your task changed" as on `plan change`.
  Control sessions use it to correct a task and `plan note` only for extra detail (F45).

- `agent-runner --help` puts what a person types first (start, attach, control, status, since, pause, stop,
  slots, wizard, guide, plan) and the rest under "Mostly for agents (you can run these too)", one short line
  each. Bare `agent-runner wizard` runs the one waiting wizard, lists them when several wait, or says there
  are none (F48).
- `agent-runner setup` makes the repo in this folder ready for a run: it commits any uncommitted work to a
  backup branch `runner-setup-backup-<date>` (your checkout stays as it was) and says its name, writes
  `runner.toml` if missing with a guessed gate, and starts one full Claude session that reads the repo and
  writes the goal and a first task list through `plan goal` / `plan add`, the gate and a short notes section
  in CLAUDE.md or AGENTS.md. It ends with what it set up and `agent-runner` to start. On a repo with a plan it
  asks first (`--yes` skips the question). It heads the person section of `--help` (F49).
- Choices come as a pick sheet. An agent that blocks with `DECIDE:` on options writes them as plain questions
  with 2-3 answers each (no option numbers) to `.runner/sheets/<ID>.json`, renders the page with
  `agent-runner sheet <ID> --html FILE` and publishes it: questions grouped by kind of change, answer buttons
  with the recommended one preselected and labelled, a collapsible Why, and a sticky bar with "N changes
  picked", Recommended and Send. Needs you, the feed and the control brief show one line, "<what is ready>.
  Pick on the sheet or reply go", with the sheet's link. Send gives a reply line (`R7 picks: backend=a …`);
  pasted in the chat, the session runs `agent-runner sheet R7 --picks "…"`, and "go" runs `sheet R7 --go`
  (the recommended set). Either reopens the task with each answer spelled out in its note. `[run]
  questionnaires = false` turns it off (F18).

## 0.54.0 (2026-11-20)

- A session you open by hand in a runner repo (the Claude desktop app, a terminal, an IDE) is a control
  session too: at run start the runner adds a SessionStart hook (`control --brief --hand`) to the main
  checkout's `.claude/settings.local.json`, per machine and never committed, so slot worktrees never get it.
  Control sessions the runner starts already have the brief from `--settings` and skip this one (F53).
- Releases reach your phone: when a merge brings a release onto main (a newer version heading at the top of
  CHANGELOG.md, or a new version tag), the run logs `<repo> X.Y.Z released: <first changelog line>`,
  `since --follow` prints it, and the runner feed sends it with PushNotification. Control sessions take
  "notify me when X" ("ping me when B56 merges", "tell me when the run is idle"): they say what they will
  watch for, watch `since --follow` (or poll `status`) with Monitor, push once when it happens, and stop (F51).

## 0.53.2 (2026-11-20)

- Windows: no more visible `...\Scripts\python.exe` console for the background run, the Stop hook's timer or
  `attach`'s helper. They started with `DETACHED_PROCESS`, and uv's `python.exe` launcher then gave the
  real python a new, visible console; they now start with `CREATE_NO_WINDOW` (B64).

## 0.53.1 (2026-11-20)

- `s!` (`stop --force`) on a session that never began (held at a dialog, so no transcript) no longer queues
  it to resume: `claude --resume` found no session and the slot sat there. The task starts afresh (B63).

## 0.53.0 (2026-11-20)

- Windows: slots no longer hang in their hidden console on Claude Code's "Do you trust this folder?" dialog.
  The runner wrote the trust to `~/.claude.json` under `C:\Users\...`, but Claude keys folders
  `C:/Users/...`, so it never saw it (B61).
- The runner deletes its own `wip/<ID>` and `wip/<ID>-N` branches, here and on `[git] push`, once the task
  is ticked or dropped (F23): after the merge that ticks it, on a `plan drop` of a running task, at the start
  of a run and every 10 minutes for tasks ticked or dropped by hand. An open or blocked task's wip stays.
  `wip/main-checkout-*` (a person's uncommitted edits) is never deleted: each is listed under Needs you in
  `status` and `since` with its age and file count, and the new `agent-runner wip [show|restore|drop NAME]`
  lists, shows, restores it into a `take` worktree (`wip restore NAME ID`, uncommitted) or deletes it here
  and on the remote.

## 0.52.0 (2026-11-20)

- Spec review before `done` (F28, after mattpocock/skills code-review's Spec axis, MIT): the slot prompt has
  the agent give a fresh subagent only `git diff <base>...HEAD` and `plan brief <ID>`, asking for what is
  missing or partial, what was not asked, and what looks wrong, each quoting the task. Missing and wrong get
  fixed before `done`; an unasked extra is reverted (and filed if worth keeping). Skipped under
  `[run] review_min_lines` (default 50) changed lines when the task has no long form. Every commit message
  ends `review: nothing`, `review: fixed <what>`, `review: filed <IDs>` or `review: skipped (small)`.
  `[run] review = false` turns it off; while on, lean Claude sessions also get the Agent tool.
- `plan restore ID [WHERE]` brings a ticked or dropped task back from `DONE.md` to `TODO.md` as open `[ ]`,
  same id, its text, fields and sub-items kept and its `dropped: WHY` note removed; at the top of the leading
  section unless WHERE (as `plan move`) says. A mistaken tick or drop no longer means re-adding the task
  under a new id. An unknown or still-open id is an error.
- **Breaking:** `plan answer` and its regex reply-guessing are gone, with `[needs] map_replies` (now
  ignored, with a warning). The control session and the runner feed map a reply that names no item ("yes",
  "B", "later") to the item's id themselves and run `plan confirm|change|shelve ID`, asking the person which
  one when they cannot tell. This also fixes `plan add`'s duplicate check: a second `_words` in plan.py had
  shadowed the first, so it matched on ids, fields and stop words again.
- Bare `agent-runner` in a folder holding `runner.toml` or `plan/TODO.md` but no git (a downloaded copy of
  `examples/hello`) makes it a repository with its files as the first commit, then starts the run; it used
  to print the usage. Outside a runner folder it says why git refused, not the whole usage (B58).
  `examples/hello/runner.toml` drops the removed `[run] mode`.

## 0.51.0 (2026-11-20)

- `plan add … --last` files a task at the end of Next with `after: all above`, a marker the run resolves on
  every pick to each task above it in its own section that is not done (ones added later included), so an
  end-of-queue task like a release waits for the whole section without a hand-kept `after:` list going
  stale. Tasks blocked on a person don't hold it until they reopen, and Follow-ups never do. `plan reopen`,
  `plan waiting` and `status` say what it still waits on. The release task T5 uses it now.

- The idle-stop waiter (`run --stop-waiter`) exits as soon as the session it watches is gone, also during
  its grace, instead of sleeping out the grace (up to hours) and then signalling a pid that may since belong
  to another process.

- A session that ends on a usage limit is a cut-off like any other: its worktree stays as it was and it
  resumes in its slot (at most 3 times), instead of the run dropping its transcript and sleeping the slot to
  the reset. The special usage-limit path (`limit_only`, the backends' `limits`) is gone; the `session_max` /
  `weekly_max` caps on starting new tasks are unchanged. Also removed: the agent evaluation probe
  `tests/agent_matrix.py` and `docs/AGENTS-EVAL.md` (`pi auth check` checks a Pi login).

- **Breaking:** the GitHub Copilot CLI backend (`[run] agent = "copilot"`) is gone; Pi with its
  `github-copilot` provider replaced it. A config that still names it stops the run with a message saying
  what to set instead: `backend = "pi"` and `model = "github-copilot/<model>"` (see
  [docs/SETUP.md](docs/SETUP.md#pi-and-enterprise-copilot)). Dead code went with it: the unused Pi extension
  writer, a shadowed `pi_argv0`, the `feed_images` and `alive` aliases, the hidden `run --mode` flag (a
  wrapper still passing it now gets an argparse error) and the empty config-rename table.

- A waiting task whose line guesses a whole directory (`tests/**`, `dir/*`) no longer waits just because a
  running or merge-waiting task touched one file in it; it still waits for a task whose line names a file or
  glob there. This repo's runner.toml sets `shared_files = ["CHANGELOG.md"]`, and the `plan add` guides say to
  name the exact test file, not `tests/**`.

- `status` says how the run is getting on: `merged 11 in the last 24h · 23 tasks left (2 blocked)` (tasks left
  leave out Parked and shelved ones; `status --window 2h` counts over another window), and, when a release
  task is queued, `release: waits on 7 of 25 tasks (T5)`. The control sessions' opening headline uses both,
  and a "how close is release?" is answered from that line, in everyday words.

- A slot's brief now tells it to check the access this machine already has before blocking with `BLOCKED:`
  on a login or token (`gh auth status`, `wrangler whoami`, the service's own CLI login, `ssh -T`,
  `~/.claude/ACCESS.md`) and to name the exact command that failed and its error in the `BLOCKED:` line.

- When a message handed on from the runner feed shows images that Claude Code recorded no saved path for (it
  changed how it records them again), the new control session's first message says so, with the Claude Code
  version, and asks the person to send the pictures there again, instead of the pictures vanishing silently.

- `plan goal` prints the `Goal:` paragraph above TODO.md's first heading, and `plan goal "TEXT"` replaces it
  (prefixed `Goal: ` when TEXT has none; added after the title line when there is none yet) and commits like
  other plan edits. The title, the fields-format line, other paragraphs, headings and task lines stay
  byte-identical. A stale goal no longer needs a task in a worktree to reword it: the control brief says to use it.

- `control --new --ask` passes on any file the person drops in the runner feed, not only images: a .zip,
  .p12 or .txt that Claude Code saves to `~/.claude/uploads/<sid>/<id>-<name>` (an attachment of type file)
  reaches the new control session as "The person attached NAME, saved at PATH: Read or open it before you
  answer", even when the feed drops or mangles the @-mention. `control --image` is now `--file` (`--image`
  still works); files Claude Code re-reads after a compaction are not counted as attached.

- `control --new --ask` again passes on a phone or remote screenshot: Claude Code 2.1.329 records such an
  image as an isMeta entry with `[Image: source: PATH]` text instead of an `inlined_image_paths` attachment,
  and the feed now reads those paths too (deduped; a later text-only message still forwards none).

- The run closes idle control sessions, so the Claude apps' session list stops piling up: every 5 minutes it
  reads the transcript of each live control session N (never c1) and ends it (its process, `controlN.pid`;
  the transcript stays, resumable) once it has been quiet an hour, Claude spoke last, its last message is not
  an open question or offer ("?", "want me to", "should I"), and nothing runs in it (a background task or
  Monitor; the needs-you watch does not count). One left on an open question for 2 hours has that question
  filed under Needs you as a DECIDE item (the question and the session link), then is closed. New `[run]`
  settings: `control_close`, `control_idle` (1h), `control_ask_idle` (2h), `control_open`,
  `control_file_asks` and `control_ask_kind`.

- Wizards for hand steps: a slot agent that blocks with `BLOCKED:` on steps only a person can take (a login,
  a signing cert, a secret, a dashboard click) is told to also write a bash wizard to
  `<notes>/wizards/<ID>.sh`, from the vendored `agent_runner/wizard_template.sh` (mattpocock/skills, MIT):
  one stage per step, URLs opened, hidden entry for secrets, `.env` / `gh secret` writes, a confirm before
  anything irreversible, checked with `bash -n`. Needs you shows `run: agent-runner wizard <ID>` under the
  item; `agent-runner wizard <ID>` checks the script, runs it in the main checkout, and confirms the item
  (`plan confirm`) when it ends well (`--check`: parse only; `--path`: where it is). New `[run] wizards`
  (default true).

- Control sessions opened with an ask are named after it in the Claude apps' session list: `control --new
  --ask TEXT` is "<repo> · N · <first words of TEXT>" (up to 5 words, about 40 characters; "screenshot" for
  an image-only ask) instead of "<repo> · control N", on Remote Control and as its tmux window. N stays, so
  higher is newer and `attach cN` still works; control 1 and a blank `control --new` keep the old name.

- "Waiting for your OK" is now **Needs you**, and reads plainly: each item is one line saying what is asked
  and what to reply (`Check the push reached your phone - reply yes/no`, `Pick an option for the new menu -
  reply A/B/C`), with its age (`2h`) first and its link on a line of its own, oldest first. The
  CONCEPT/CONFIRM/DECIDE/BLOCKED labels stay in the plan and in `plan waiting`, but no longer show in
  `status`, `since`, the feed or the control sessions' opening. A block on a person is stamped `(asked
  <time>)` when it is filed, which is where the age comes from. A reply that names no id ("yes", "B",
  "later", "use SQLite") goes to the one item it clearly answers: `plan answer "<reply>"`, which control
  sessions and the runner feed now run; it asks which one when the reply could fit several. New `[needs]`
  settings: `heading`, `ages`, `order` (`oldest`, `newest`, `plan`) and `map_replies`.

## 0.50.3 (2026-11-20)

- Control sessions show a concept inline for any "show me first" wording ("show me a concept first", "mock it
  up"), not only "concept X": they no longer queue a K task for it, nor `take` one on "do it here" (a K queued
  by mistake is dropped and the page written in the session). The agent-runner skill says the same.

- Images reach the new control session from a runner feed started by an older runner: `control --new --ask`
  reads the calling session's transcript (`CLAUDE_CODE_SESSION_ID`) for the handed-on message's images, and
  `<notes>/remote/feed.sid` only when that is unset. A feed started before 0.50 never wrote feed.sid, so it
  forwarded no pictures and the control session went looking for screenshots on the desktop instead.

## 0.50.2 (2026-11-20)

- Changes reach a running agent instead of restarting it. `plan change ID TEXT` on a task a slot is running
  notes the change as before, then types `Your task changed: TEXT` into the slot's tmux pane (Claude Code
  queues it for its next turn) and leaves the agent working, instead of ending its session, throwing its
  work away and starting over. `plan change ID --restart TEXT` keeps the old stop-and-restart, and so does a
  slot with no live pane (Windows terminals, a session that ended), which the command says. New
  `plan tell ID TEXT` sends a note to the running agent without editing the plan, and fails when no slot
  runs ID. Both go through the run (`<notes>/tell/<ID>.json`) and print e.g. `told s1 (F297)`. The control
  brief maps "tell it…" and small corrections of a running task to them.

- Pictures sent to the runner feed reach the control session it opens: `control --new --ask` picks up the
  images attached to the person's latest message in the feed (the saved paths Claude Code records in the
  feed's transcript) and passes them on as `--image`. The feed no longer has to do it, which a feed started
  before 0.50.1 (one session from the run's start to a real stop) never knew to, nor reliably did on Haiku.

## 0.50.1 (2026-11-20)

- A control session's needs-you watch no longer posts "Still watching. Nothing needs you right now." every
  five minutes: it starts the Monitor with `timeout_ms 1800000` (the cap) instead of the 5-minute default, and
  on a timeout with no lines re-arms it with no text at all, speaking only for a line it printed. The runner
  feed's Monitor does the same.

- The runner feed no longer drops pictures when it hands a message on: `control --new --ask TEXT` takes
  `--image PATH` (repeatable), which adds a line per image to the new control session's first message, naming
  its path and saying to Read it before answering. The feed's brief passes each image the message came with
  (the path the apps note it is saved at).
- `plan drop` and `plan change` on a task the run is on now stop it too, instead of only editing the plan
  while the slot's agent worked on and its branch could still merge. The command leaves a request for the run
  (`<notes>/halt/<ID>.json`); within seconds the run ends that slot's session, deletes task/<ID> here and on the
  remote, resets the worktree (nothing is saved: the work is unwanted) and frees the slot. A change then starts
  the task again in that slot from the new text. A dropped task whose finished branch waits to merge is deleted
  unmerged, and a cut-off session waiting to resume it is taken back. The command prints what the run did, e.g.
  `dropped F297; stopped s1, removed its work (reset s1, deleted task/F297, deleted task/F297 from origin)`.
  `plan change` now takes an open task as well (noted, stays open), not only one waiting on a person.
- Control sessions queue "do X after T181" with `plan add … --after T181` (or `plan block ID --after T181`
  for a queued task) instead of starting a watcher or Monitor that waits for T181: the run starts the task
  once those merge.
- The control brief maps more everyday requests to their commands: "park it" / "low priority" (`plan add
  --pri later|low`), "do that next" (`plan move ID top`), "never mind" (`plan drop`), "split that up" (`plan add
  ID`), "sleep or shut down when done" (`stop --suspend|--shutdown`), "pick that back up" (`resume ID`), tasks
  held by a crashed run (`plan claims`, `plan unclaim ID`) and "where are the tokens going" (`cost`).
- "concept X" / "sketch options for X" in a control session now shows the options there and then: the control
  session writes the page of 2-3 options and a recommendation itself, publishes it and opens it inline, instead
  of queuing a K task that waits for a run slot. It queues a concept only when the person says queue it, later
  or add a task.
- The runner feed ("<repo> · runner") carries on across restarts that are not a stop. An upgrade's restart
  (auto_upgrade, `u`) execs in place, so the board window and its feed stay up as they were. When the feed does
  have to start again (its board window was replaced or closed, the feed exited, a crashed run was started
  again), it resumes the same Claude session (`--resume`, its id kept in `<notes>/remote/feed.sid`), so its
  history and its app entry carry on instead of a new one. A stop still ends it, and the next run's feed is a
  new session. A resume that fails at once (the transcript is gone) makes the next start a fresh session.

## 0.50.0 (2026-11-20)

- Old Remote Control entries no longer pile up in claude.ai/code and the apps. Claude Code has no command to
  end or archive a session from outside. It archives its own entry when it exits on SIGTERM, SIGHUP or Ctrl-C,
  and an entry stays listed only when its process dies without that (SIGKILL, a crash, a reboot, a power-off
  right after a stop). The run now records the Remote Control processes it starts for itself, the runner feed
  and the control server, in `<notes>/remote/`. A stop ends them with SIGTERM and waits up to 20 s for them to
  archive themselves before the run exits, suspends or powers off. The next start does the same for any an
  earlier run left (a control server that run's restart adopts stays up instead: no new entry). None is
  SIGKILLed: one that outlives the wait is left running and named in run.log, and a feed the board had to kill
  is named at the next start, so you can archive it by hand. Control sessions are yours and stay up, and
  sessions the run did not start are never touched.
- The background run keeps a board window, "board-<repo>": `since --board` (what landed, started, stalled or
  needs you, the last 6 hours then live), under a line saying to steer from a control session. No LLM, so no
  tokens; it leaves the last-look mark alone, and the run opens it again within 30 s when it is closed.
  `agent-runner attach board` goes there.
- With `[run] remote` on, the run opens c1 beside it again (0.49.0 left it out), in tmux (or its Windows
  console) for the terminal only: it is not on Remote Control, so the apps show no "<repo> · control 1" beside
  the control server's "<repo> · control" (the one app entry for starting control sessions) and its start pushes
  nothing. It opens blank, with no summary turn, so it uses no tokens until you type in it.
- The runner feed: with `[run] remote` on, the board window is a lean Claude session that is also in the apps,
  as "<repo> · runner". It posts each line of `since --follow --keep-mark` as it lands, runs status, pause,
  stop, force, slots N and `control --new` when asked, and hands anything else to a new control session
  (`control --new --ask TEXT`), answering with its link. It runs Haiku with only Bash (the runner's command,
  nothing else) and Monitor, its own short system prompt, and no settings or MCP servers: about $0.001 a
  landing at API prices. With remote off, the board stays the free text feed.
- The runner feed is the one watch for what needs you: it pushes those lines (PushNotification), and control
  sessions start no needs-you watch of their own while it runs (they still do without it: remote off, Windows,
  no tmux). The full `since --follow` feed now carries the "waits for you" asks too. The board, and so the feed,
  opens in any tmux run, not only the background one. The feed loads no auto memory.
- `since --follow --keep-mark` leaves the last-look mark alone; `control --ask TEXT` gives a control session
  its first message.
- The board follows the run. It ends when the run does: after a plain stop once the running tasks are done, a
  force stop, or a crash. The runner feed's process ends, so "<repo> · runner" goes offline in the apps and the
  window closes. The next run opens a new board. While the run is idle, or paused or stopping with nothing
  running or merging, the feed holds its lines: no Haiku turns, no pushes, no tokens. When the run starts
  something (a task added, the run unpaused) it prints what was logged meanwhile and carries on. You can still
  type to it while it holds. The board window now runs `since --board [--feed] --run-pid PID`, and STATE says
  `idle`, `paused` and `stopping`. A board left by an earlier version is replaced when the run starts.
- Known limit of the quiet launch (checked by hand on a phone): Remote Control's own "session ready" push
  ignores `CLAUDE_CLIENT_PRESENCE_FILE`, so each Remote Control slot start (`remote_slots = true`) buzzes the
  phone even with `.runner/quiet-slots` in place, and the runner cannot stop it. The presence file only keeps
  the client's later pushes quiet.
- `remote_slots = true` means slots on Remote Control, and each slot start pushes to the phone. Nothing the
  runner can set stops that push (found in the Claude Code 2.1.329 binary): the server sends "session ready" as
  the session registers, and the presence pulses only start after that. `agentPushNotifEnabled` and
  `inputNeededNotifEnabled` are account settings on the server, which Claude Code only updates when you change
  them in /config, never from `--settings`, and no environment variable turns the push off. Slots keep
  `.runner/quiet-slots`, because Claude Code pulses it just before a needs-input or turn-done push, so those
  pushes should stay quiet. They keep `agentPushNotifEnabled: false`, which blocks a slot's own
  PushNotification tool. They no longer get `inputNeededNotifEnabled`, which did nothing. `remote_slots` stays
  off by default. To stop every push, turn notifications off for the Claude app on the phone (that covers all
  sessions). For the same reason, the control sessions' and the control server's quiet launch most likely
  does not silence their start push either.

## 0.49.0 (2026-11-20)

- Bare `agent-runner` starts the run in the background; `agent-runner attach [sN]` attaches to its pane (or a
  slot's), and `agent-runner --attach` does both: starts the run, or finds the one up in this repo, then attaches.
- `[run] auto_upgrade = true`: a run upgrades agent-runner by itself when the update check sees a newer
  release, once no merge is under way, and restarts on it keeping what the keys set. Never across a major
  version, nor on Windows.
- Control sessions: interactive Claude sessions in the main checkout for steering the run.
  `agent-runner control` opens one (`control --new` another, without taking focus, printing its claude.ai/code
  link). With Remote Control off, the run opens c1 beside it (`[run] control = false`: none); with it on, a
  control server starts them from claude.ai/code and the Claude apps, and the run opens no c1. Control sessions
  and the control server run with `bypassPermissions`, so the web and the phone see no permission prompts.
  Control 1 opens with a short status summary (a headline, then Waiting for your OK / Running / Landed / Stuck,
  concept pages opened inline) and a hints line of slash commands (`/run /since /follow /control /pause /stop
  /slots N`); later ones start blank. Each watches `since --follow --needs-you` and tells you, unasked, when
  the run is held, a task is left for a human, a slot looks stalled, or something waits on your answer.
- `agent-runner since [WHEN] [--follow] [--needs-you]`: what happened since you last looked, or a live feed.
- **Changed: `[run] remote` now means the control sessions and the control server; the slots go on Remote
  Control only with `[run] remote_slots = true`** (in 0.48.0 `remote = true` put the slots there). Remote slot
  sessions are named "<task title> · <repo> s2 · B646".
- Concept tasks (kind K) publish an Artifact page of options and build nothing: `done K7 --artifact URL`
  notes the link and files the build blocked "waiting for your OK on URL"; `plan approve` / `revise` /
  `waiting`. Tasks blocked on a person (CONFIRM / DECIDE / BLOCKED) are listed beside concepts under
  "Waiting for your OK"; `plan confirm` / `change` / `shelve` / `unshelve`, `plan waiting --all`.
- Hints print the command you typed (`agent-runner` from PATH, not the clone's `./run`).
- A run restarts an adopted control server that was started with other flags.
- Fixes: concurrent `plan add` on an in-repo plan never reuse an id; Claude trust creates a missing
  `$CLAUDE_CONFIG_DIR` (and skips trust if it cannot write there).

- `[run] silent` picks how quiet a run's Remote Control sessions are on the phone: `"launch"` (the default, the
  quiet launch below), `true` (no push ever, control sessions included), or `false` (no presence files or push
  settings: Claude Code's usual pushes). Anything else is refused.
- **Changed default: `[run] remote` is now `auto`, so control sessions and the control server go on Remote
  Control by default** (they were local unless you set `remote = true`). Auto turns it on only where it can
  work and otherwise leaves it off with one line in `run.log` saying why: the backend is pi, the agent is
  Copilot CLI, `ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN` is set, `CLAUDE_CODE_USE_BEDROCK`/`VERTEX`/`FOUNDRY`
  is set, `ANTHROPIC_BASE_URL` is not api.anthropic.com, or Claude Code's one-time "Enable Remote Control?" has
  not been answered yes (the launch asks it at a terminal; a no, or no terminal, starts the run local instead
  of refusing). `remote = true` / `false` still force it; anything else is refused. The slots stay local
  unless `remote_slots = true`. To keep the old behaviour: `remote = false`.
- Quiet launch: a run's Remote Control sessions no longer buzz the phone as they start. Each gets
  `CLAUDE_CLIENT_PRESENCE_FILE` (Claude Code 2.1.181+ sends no mobile push while that file exists). A control
  session's file (`.runner/quiet-c<N>`; the control server's `.runner/quiet-server`) is there only until its
  claude.ai/code link shows, so later pushes (a concept waiting for your OK, a stuck run) still arrive. Slots
  with `remote_slots` keep theirs (`.runner/quiet-slots`) for good, and get `agentPushNotifEnabled` and
  `inputNeededNotifEnabled` off in their settings too. Not yet checked by hand on a phone, and the docs don't
  say whether Remote Control's own "session ready" push honours the presence file.

## 0.48.0 (2026-11-19)

- Every key of the runner's pane is a command too, for a person in another terminal or a remote session:
  `agent-runner pause` / `force` (`--off` to take back), `slots N|+N|-N`, `stop --undo`, and `key <k>` for the
  rest. `pause`, `force` and `stop` say which way they go, so saying one twice does not undo it.
- `agent-runner status`: whether a run is up, what its keys have set, each slot's task, and the end of its log.
- A slot can publish a page or screenshots to claude.ai with the Artifact tool and link it (lean sessions
  now get `Bash,Read,Edit,Write,Artifact`). It needs a claude.ai login; print-mode fix sessions don't have it.
- `[run] remote = true`: every slot starts on Remote Control, named "<repo> · s2 · B646", so it can be watched
  and typed to from claude.ai/code, the desktop app or the phone apps. Enter in the runner's pane opens
  claude.ai/code. Claude Code only; needs a claude.ai login (not an API key).

## 0.47.0 (2026-11-19)

- `agent-runner take "TEXT" --kind K [--files A,B]`: queue a task and take it in one step, no id needed.
  `take --here` (with TEXT or an ID) moves the main checkout's uncommitted edits, new files too, into the new
  worktree, leaving the main checkout clean.
- The line a run puts in the rules file (AGENTS.md/CLAUDE.md) now says: asked to do something now, use
  `take`; never edit the main checkout. A run rewrites the older line in place. The guide says it too.
- Edits in the main checkout that hold a landing: the STOPPED line, and the log line when `land_edited =
  "wip"` moves them aside, say to use `take --here` next time. `plan claims` and `run --dry-run` list the
  `wip/main-checkout-*` branches, so they are not forgotten.
- A subtask of a parent tagged `later` but moved out of Parked is no longer tagged `later` itself.

## 0.46.1 (2026-11-19)

- A session whose `done` succeeded is ended 5 s after its last turn, not `[run] idle` (90 s): the slot's next
  task starts sooner. A session that stops without `done` still gets `[run] idle`, so a person can take it over,
  and `idle` now defaults to 30 s (was 90).

## 0.46.0 (2026-11-19)

- `agent-runner take ID`: one chosen task for a person's own session or a subagent, beside a run or without
  one. It gets a worktree in the runner's home (`take-ID`, on `task/ID`) and the prompt a slot would get; a
  run that is up treats it as running and keeps other tasks off its files. Finish with `done` there, then
  `take ID --merge`: with no run up it is tested and merged at once, otherwise the run merges it within a
  minute. `take ID --drop` gives it back. The guide skill says when to use it.
- A run merges any `task/` branch that finished outside its slots while it is up, not only at its start.
- `plan move P17 top` takes P17's subtasks with it: they no longer stay behind in Parked, where no run starts them.
- A subtask of a subtask (`plan add P17a …` -> P17a1) files after its family like any other subtask, not at the
  top of Next.

## 0.45.1 (2026-11-19)

- A newer agent-runner shows as a green banner in the runner's pane, shaped like the STOPPED one, saying how to
  upgrade (`u` + Enter when the pane reads keys). The run looks every 6 hours, not only at the start, says each
  version once, and `?` keeps listing it.

## 0.45.0 (2026-11-19)

- `u` in the runner's pane upgrades agent-runner (`uv tool upgrade`, `pipx upgrade`, or `git pull --ff-only` in
  a clone); the run restarts on the new version as it does after any upgrade. `run --upgrade` upgrades first,
  then starts on the new version.

## 0.44.0 (2026-11-19)

- `f` in the runner's pane forces past the session and weekly usage caps, as `--force` does, without a
  restart; `f` again puts them back. An upgrade restart keeps it.
- Hitting a usage cap raises the same loud STOPPED alarm as edits holding a merge (banner, bell, tmux message,
  desktop notification), saying how to go on: `f` + Enter, or a restart with `--force`.

## 0.43.0 (2026-11-18)

- More keys in the runner's pane, listed in a ruled-off block when the run starts and on `?` + Enter:
  `s!` stops now (ends the agent sessions, each queued to resume in its slot next run, then exits once the
  merges under way finish), `p` pauses without exiting, `+`/`-` add or take away a slot, and `z`/`x` suspend or
  shut the computer down once the run stops (or goes idle). A line it does not know is echoed back with the list.
- `stop` takes `--force`, `--suspend` and `--shutdown`, the same as `s!`, `z` and `x`.
- A key is acted on and logged the moment it is typed: `stopping` no longer waits up to a loop pass.
- A restart on an upgrade keeps what the keys set: the slot count, a pause, a suspend or shutdown, and a stop.

## 0.42.1 (2026-11-18)

- Agents are told to edit files with their editing tool, not `sed -i`, `perl -i` or a script in a heredoc, and
  to run one plain shell command at a time: a command Claude Code's safety check cannot read stops for a human,
  and in an unattended session it waits, is refused, and the minutes are lost. Also: no `rm -rf` on a variable
  or glob, no `git reset --hard`, `git clean`, `git checkout -- .`, `git stash` or `git push --force`. The same
  text is in the runner's prompt and in the guide skill (a new rule 7, which also keeps sessions out of the
  runner's home and `.runner/`).

## 0.42.0 (2026-11-18)

- One repair session per failure, not per task: a repaired merge rebuilt on commits the shared branch got after
  the repair, which fails the gate again, is a new failure and gets a repair session of its own (logged as such).
  The same failure on the same base still gives up after one.
- `run --dry-run` accounts for every open task: one held by a file clash says which files and who holds them
  (`waiting for files: F171 (web/app/** held by B20)`), and others say the running sibling, the task ahead in an
  ordered section, running, finished and waiting to merge, claimed by another runner, tried this run, or next
  once a slot is free. "Nothing to start" no longer leaves an open task out of every list.
- A branch that does not merge is logged as `not merged, parked as wip/<ID> — why`, with when the task starts
  again by itself (the next run, or this one once its line is edited). "LEFT FOR A HUMAN" is kept for what truly
  is: a crashed merge, or a branch that could not be parked.

## 0.41.0 (2026-11-18)

- Every command a person runs (`plan`, `--version`, `help`, …) keeps the `agent-runner guide` skill installed, not
  only `run`: anyone who has typed agent-runner on a machine has it. Said once on stderr when written.
- A run adds one line to the repo's rules file (`[run] rules`, else AGENTS.md or CLAUDE.md), committed on its own,
  pointing every session at the skill and `agent-runner guide`: the guidance reaches sessions on machines without
  the skill, and ones that would not pick it. Never into a file with uncommitted edits; it never creates a rules
  file; `[run] rules_pointer = false` turns it off.

## 0.40.0 (2026-11-18)

- A repair session that finds a flaky test, not a clash, ends with `FLAKE: <test>`. The runner then runs the gate
  once more on the merge as it is before parking anything, and files the flaky test to be fixed either way. A
  flake used to park a tested branch as `wip/<ID>` for a person.
- A merge held by uncommitted or staged edits in the main checkout is a loud STOPPED: a red banner in the runner's
  pane, the bell, a tmux message and a desktop notification (`notify-send`), raised again every 30 min while it
  holds, and a line when it clears. It was one yellow log line, easy to miss for hours.

## 0.39.0 (2026-11-18)

- Runs claim tasks with the plan in the code repo too, not only with `[plan] repo`: a claim is a ref on the
  code's remote (`refs/agent-runner/claims/<ID>`), and the first push wins. Two runs, on two machines or in
  two clones on one machine and account, never start the same task, and keep off each other's files.
- `agent-runner guide`: how an agent session a person starts in the repo should work with the runner (queue
  work with `plan add` instead of editing TODO.md or doing it on a branch, leave `task/*` and `wip/*` alone,
  how to unstick a task). Each run keeps it installed as a Claude Code skill in `~/.claude/skills/agent-runner`,
  rewritten whenever its text changes; `[run] install_skill = false` turns that off.

## 0.38.1

- `[git] land_edited = "wip"`: a tested merge that uncommitted edits in the main checkout would block no longer
  waits forever. After 3 minutes the edits (new files included) go to a `wip/main-checkout-<time>` branch, pushed
  with the shared branch, plus a stash; the log names the files and how to get them back, and the merge lands.
  The default stays `"wait"`.
## 0.38.0 (2026-11-17)

- A run restarts itself on a new version installed under it (`uv tool upgrade`, `pipx upgrade`, a pull in a
  clone), once no merge is going, and adopts its sessions, merges and gates. Before, the loop kept running
  the old code while the sessions' `done` and Stop hook ran the new one. Not on Windows, and not across a
  major version: that one is logged once for a human to restart.
- The run log names every stale key in `runner.toml` / `runner.local.toml` at the start of a run: a renamed one
  (it still works under its old name, from a table of renames each release adds to), a removed one with what to
  do instead, and an unknown one with the nearest real setting. An upgrade never needs a config edited first.

## 0.37.3 (2026-11-17)

- A task tried and failed in a run goes back in the pool once its line is edited (a `plan note` with what to
  do differently, a corrected line), not only once it is blocked and unblocked. A failed task waited for the
  next run even after it was given the fix: Cydian's I2 sat out a day-long run with its note saying what broke.

## 0.37.2 (2026-11-17)

- A merge turn that finds a merge already gated for other waiting tasks gives its turn up to them, once,
  instead of dropping that merge. After a restart, the gate a run left is adopted inside whichever turn
  comes first; P347's turn threw away R38's batch of 16 tasks, which had just passed a 42-minute gate.

## 0.37.1 (2026-11-17)

- A merge built ahead waits while a gate still runs in merge2. After a restart, a turn could adopt the gate an
  earlier run left there, and the next merge-ahead checked out over it: the gate then built and tested the
  new tree and reported its failures as the adopted merge's, and the retest on the real merge passed, so
  three tests were filed as load flakes that were never flaky.

## 0.37.0 (2026-11-17)

- With `[run] test_since`, a shared branch that gets code commits during a merge's gate no longer means
  building and testing the whole merge again. The new commits are merged into the tested merge, and the
  gate runs on what they change, from that merge. A conflict or a failure there still builds it all
  again. One kit commit to main during a 54-minute batch gate had cost a second 54 minutes.

## 0.36.1 (2026-11-17)

- A finished task waiting to merge holds only the files it changed, not every file its plan line names. One
  line naming `tests/**` kept 38 tasks from starting while merges were behind.

## 0.36.0 (2026-11-17)

- A failing batch's culprit is found by halving the batch: about 5 retests for 16 tasks, not 16.
- Task ids are held in a list in the git dir once handed out (by `plan add`, a renumber, or an unmerged
  branch at `run` start), so two branches no longer take the same id and get renumbered at merge, again
  and again.
- Gentler backpressure: `batch_max` 16, `max_unmerged` 32, one slot held per half batch past it.

## 0.35.0 (2026-11-16)

- A test the base already fails no longer blames a batch's tasks. Before, one inherited failure beside a
  new one put every task of the batch in a merge of its own, and the merges fell 70 tasks behind.
- If most of a batch fails alone, nobody is put aside: it is the base or the machine.
- Critical tasks merge alone and first; a merge built ahead goes next, then the rest in order.
- `[run] batch_max` (10) caps a batch; `[run] max_unmerged` (12) eases slots off while merges fall behind.

## 0.34.1 (2026-11-16)

- `plan add MD39b …` files the subtask MD39b1: a task id ending in a letter is taken as KIND when it is an
  open task's id, as one ending in a digit always was. A letter-ending id that is no open task is still refused.

## 0.34.0 (2026-11-16)

- Run sessions with GitHub Copilot CLI as well as Claude Code and Pi, including session recovery and fix sessions.
- Support local-only runs with `[git] push = false`, while preserving inherited Git configuration.
- Improve Windows terminal sessions, startup diagnostics and UTF-8 Git output.

## 0.33.0 (2026-11-16)

- `run --suspend`: like `--shutdown`, but the computer sleeps instead of powering off. On waking the run
  carries on, and it suspends again only after it has had work and gone idle again.
- README: *How it works* rewritten step by step (what makes a task wait, what happens in a merge), and a
  section on filing tasks from a Claude Code chat, with an example.

## 0.32.1 (2026-11-16)

- The runner's pane is in colour: starts blue, merges and pushes green, blocks and conflicts yellow, failures red,
  exits grey, task ids bold. Only on a terminal (Windows: Windows Terminal), never with `NO_COLOR`; run.log stays
  plain text.

## 0.32.0 (2026-11-16)

Breaking: settings removed. A config that still sets them is not an error; they are ignored.

- Mode p is gone: a run never starts two tasks on the same files (what mode d did), and an "in this order"
  section always runs one task at a time. `[run] mode` is ignored; `run --mode` is still accepted, and ignored,
  so wrapping CLIs that pass it keep working.
- `[run] fix_ahead` is folded into `fix_ahead_max`: `0` fixes conflicts under the lock, as `fix_ahead = false` did.
- Removed `[run] precommit` and `done --skip-check` (chain the check into `[run] test`, or run it in a wrapper
  before `done`), `[plan] brief` (use `brief_extra` and `outline`), `[run] ci_rerun` (a red CI run's failed jobs
  are always run once more first), and `[run] batch_wait` / `batch_min`.
- A remote given as a relative path (`origin = ../origin.git`, a relative `[plan] repo`) is the main checkout's:
  `done` in a slot's worktree pushes to it instead of failing. A push to a remote that cannot be reached says
  so with git's own message, not "has moved and merging it conflicts".
- README rewritten as an overview; the full behaviour and every key moved to docs/REFERENCE.md. The context
  numbers are re-measured over 1,836 slot sessions.

## 0.31.0 (2026-11-16)

- `agent-runner context [--check]`: what every session loads before it starts ([run] rules, CLAUDE.md,
  AGENTS.md and their `@` imports), per file and biggest section first, against `[plan] context_kb` (12 KB).
  `run` logs a warning at start when it's over; `--check` exits 1.
- `plan <name>` prefers a heading named exactly that over one that only contains it (`plan hst` no longer
  stops at `hst-data`), across every file it searches.
- `[plan] lookup` takes globs (`"plan/guide/*.md"`).
- The agents' prompt says reference material they write goes under its own heading in a lookup file, not in
  the rules file every session loads.

## 0.30.3 (2026-11-16)

- A conflict fixed ahead of the merge lock waits while another task, fixed ahead and not merged yet, had a
  conflict in one of the same files. It is then fixed once against that merge, instead of side by side and
  again after the first lands (`waits for X to merge first` in the log).

## 0.30.2 (2026-11-16)

- Windows Pi sessions launch the Node CLI directly instead of npm's `.cmd` shim; Linux/macOS keep
  their configured executable.
- Update notices accept single- and double-quoted version strings. Release automation reads the version
  as Python, rejects invalid versions, and publishes numbered releases with installation commands.
- The README version badge uses GitHub releases and links to installation instructions and release notes.

## 0.30.1 (2026-11-16)

- The agents' prompt tells them to file follow-ups with `--files` (and `--after`), not text alone.

## 0.30.0 (2026-11-16)

Breaking: a new task line format, and the old one is no longer read. Rewrite TODO.md once.

- A task line is `- [ ] **ID** prose | files: a, b | after: X, Y | test: name | journal: dir`, then an optional
  ` — note` and `BLOCKED: …`. Only the fields count; prose is never parsed for files or ids. `→ files`,
  `(after X)`, `| t:` and `| j:` are gone, and so is the rule that a line naming a running task's id waits.
- `plan add --files/--after/--test/--journal` writes the fields; a line with no `files:` and no `test:` gets a
  warning (an error with `[plan] need_files`). Its next free id counts the plan in every worktree of the repo,
  so two sessions adding at once no longer take the same id.
- Mode d keeps a task off the files of running and finished-but-unmerged tasks: their lines' and the ones
  their branches have touched. A path meets its own tail (`src/menu.rs` meets `app/src/menu.rs`).
- An ordered section is one whose heading says *in this order* or *one at a time* (no longer any *Next*).
- `LICENSE*` and `COPYING*` join `*.md` in the default `untested`: a license commit landing mid-gate no longer
  throws the passed gate away.
- Fixes: a merge whose branch kept getting code commits during its gate is no longer landed untested on the
  third try; gate records check the process start time, so a reused pid is not mistaken for a live gate;
  renumbering a doubled id renames its `plan/tasks/<ID>.md` too; the union/renumber scratch files are per
  task (two merges in threads no longer share one); `master.json` is removed only by its own session;
  a remote `task/*` branch an earlier failed push left behind is deleted once main has it; a branch left for a
  human drops its held refs as well as its fixed ones.
- Removed: support for pre-0.14 claims, the pre-0.13 `~/.cache/agent-runner` plan clone and `<repo>-slots/`
  worktrees.

## 0.27.0 (2026-11-15)

- `[run] session_max` (default 90): past that % of the account's 5-hour session usage, no new task starts,
  as `weekly_max` does for the 7-day usage. Before, only the weekly figure was watched, so a run of several
  slots could spend the whole session limit and leave every slot stuck at the limit prompt.

## 0.26.1 (2026-11-14)

- `batch_wait` skips a task whose gate is already running (adopted after a restart, or built ahead): a task
  joining it would start that gate over.

## 0.26.0 (2026-11-14)

- A batch that fails the gate looks for the task that breaks it by itself: each branch is merged alone and
  `retest` runs just the failing tests. Those tasks merge in their own turn; the rest are gated together
  again, instead of every branch going alone. With no branch failing alone, the batch repair runs as before.
- A one-task repair starts as a copy of the session that did the task (Claude only), so it knows the change.
  The repair prompt no longer assumes the branch passed the gate on its own.
- `[run] batch_wait` / `batch_min`: a finished task can wait for others before its gate run while slots
  still work, so one gate run covers more tasks. Off by default.

## 0.25.0 (2026-11-12)

- A gate failure the base fails the same way still merges anyway, and now files a critical task to make the
  test pass again (once, while none is open), so the shared branch is not left failing it unnoticed.
- With `[run] test_since`, a whole `test` that found only failures the base already has counts as the day's
  whole run: they are filed, and the merges after it go back to the selective gate rather than each running
  the whole `test` again to find the same failure. The task says to widen the selection too.

## 0.24.0 (2026-11-12)

- `[run] test_since`: a merge's gate tests only what changed since `{base}`, the commit the merge is on (one
  that passed a gate), and the whole `test` runs again once `[run] full_every_hours` (24) pass without one.
  The log says which ran.
- The prompt tells sessions to run `done` and whole test suites as a background command and wait: a gate
  waiting for a lock outlasted agents' own command time limits, and a cut-off `done` commits nothing.
- README: "Making it fast", what a many-slot setup needs from its gate.

## 0.23.0 (2026-11-11)

- A batch is pushed once, by the last of its tasks to record its landing (`… pushed main -> origin (with …)`),
  not once per task: each push to the shared branch is a CI run. A merge that takes the lock first pushes the
  batch before its own gate.

## 0.22.0 (2026-11-11)

- CI watch: a red run's failed jobs are run once more (`[run] ci_rerun`, on by default) before a task is
  filed, and nothing is judged while a newer run of the workflow is under way. A runner GitHub never handed
  the job and a DNS outage had each filed a task for a branch that was fine.
- A test the memory watch ends is named (thread names, then the binary's `--list`) and gets a `critical`
  task at the next merge, like a flaky one.
- `drop_ahead` removes `merge2`'s gate records with the gates it stops: one left behind read as a gate to wait on.

## 0.21.0 (2026-11-11)

- A memory watch (Linux): a process of the run's (in one of its worktrees, or started from a slot; never an
  agent) resident past `[run] proc_max_gb` ("auto": a quarter of the memory) is killed, alone, and logged;
  under `[run] min_free_mem_gb` (4) available, the run's biggest is. A test looping over a tree in RAM had
  grown to 52 GB in each of three slots' gates, and the machine's OOM handling ended other work for it.

## 0.20.3 (2026-11-10)

- A fix worktree (and `merge2`) is the runner's own: a task starting on files a fix ahead of the lock has
  open was logged as heading into "uncommitted edits outside the runner".

## 0.20.2 (2026-11-10)

- `[run] suspect` flags a block a merge adds, not a blocked line edited some other way (`fill_files` adding its
  `→` list made S283's merge flag S251's old block).

## 0.20.1 (2026-11-10)

- At most `[run] fix_ahead_max` (2) fixes ahead of the lock at once: a run started with many finished,
  conflicting branches would have opened a worktree, a build and an agent session for each of them. The
  rest wait their turn, so there are never more fix worktrees than the cap. Each also waits on
  `[run] before_start` (the room check) as a slot does, is trimmed past `slot_max_gb`, and an idle one is
  cleaned under `min_free_gb`.

## 0.20.0 (2026-11-10)

- A conflict the join cannot do gets its fix session before the merge lock is taken (`[run] fix_ahead`, on by
  default), in a fix worktree of its own (`fix1`, `fix2`, …, kept warm). The other finished tasks merge and
  gate meanwhile; the fixed merge (`refs/agent-runner/fixed/<ID>/<sha>`) then goes in under the lock, clean,
  or with a second, smaller fix ahead if the shared branch touched the same lines again. The third try fixes
  under the lock as before. `fix_timeout` now holds up only that task: one fix session used to hold every merge
  for up to 40 min.
- With `fix_ahead`, a batch rider whose conflict needs a session waits for its own turn instead of taking a
  session inside the batch.

## 0.19.6 (2026-11-09)

- A task line's files are its `→` list when it has one; prose file names count only on a line without one.
  A menu task that said "what race.rs already has" waited on every task touching race.rs.
- Picking: a task that a waiting task depends on (`(after X)`, `BLOCKED: (after X)`) takes that task's place
  in the order, transitively; Stretch and Parked lines pull nothing up. A Next task blocked on Follow-ups
  waited behind every task between them.
- The plan is read from the remote's shared branch when it is strictly ahead (fetched at most once a
  minute): a hand merge pushed from another worktree left the main checkout's plan showing that task open,
  and the next free slot would have started it again.
- With `[plan] need_files`, each merge gives task lines written into TODO.md by hand their prose's files
  (`plan.fill_files`) and logs, once each, the ones naming nothing.

## 0.19.5 (2026-11-09)

- `[plan] need_files`: `plan add` refuses a task line that names no file and no test (no `→` list, no
  `| t:`), and gives one whose prose names repo files a `→` list of them. Mode `d` keeps running tasks apart
  by those files, so a line naming none ran beside anything. A load-flake task names its test (`| t:`).

## 0.19.4 (2026-11-05)

- A critical follow-up goes into the plan's own Critical section when it has one (a heading naming
  "critical"), at its end, rather than to the top of the leading "Next" section, where in an ordered
  section it held up the queued work.

## 0.19.3 (2026-11-05)

- `[run] copies`: git-ignored files copied into a new worktree once, where `links` would share one file
  (a local config the tests read from the checkout's root). The merge-ahead worktree had none and its
  first gate failed on that alone.
- The gate on a merge built ahead says how it ended; a failure is kept for that batch's turn, which goes
  from it (retests, repairs) instead of running the gate again.

## 0.19.2 (2026-11-05)

- An adopted gate that failed is no longer thrown away: its merge is reused as it was gated and the
  failure handling (retests, the repair session) goes from that result, instead of a new batch with the
  tasks that finished meanwhile and a whole gate run again. The log says how an adopted gate ended.
- A gate that ended while no run was up counts as it ended (its exit code is read from disk), and a merge
  built ahead (merge2) survives a restart: its turn reuses it and waits for its gate by tree.
- A failed gate's output is kept a week (`.runner/gates/<key>.failed`); it used to be deleted.
- Two turns waiting on the same gate run read one result; the second used to find nothing and rerun it.
- The riders of a merge an earlier run gated wait from startup, so its turn finds them and reuses it.

## 0.19.1 (2026-11-05)

- A gate that passed under an earlier run is not wasted when tasks finish or plan commits land in
  between: its merge is reused as it was gated (the gate record keeps the batch), the plan commits are
  merged into it, and the tasks that finished meanwhile wait for the next turn. A gate pass is now keyed
  on the files the gate tests (`[run] untested` left out), so a plan commit does not make a passed merge new.

## 0.19.0 (2026-11-05)

- Merge ahead (`[run] merge_ahead`, on by default): tasks that finish while a batch is in its gate are
  merged on top of that merge in a second worktree (merge2) and gated beside it. The next turn reuses that
  merge, and waits for the gate already running on its tree, instead of starting its gate only after the
  last one landed. A failed first batch drops the merge built ahead and stops its gate.
- Gate runs are recorded per tree (`.runner/gates/<key>.json`, not `.runner/gate.json`), so a turn waits
  for a gate already running on its exact merge, and a restart adopts every gate an earlier run left.

## 0.18.0 (2026-11-05)

- A restarted run adopts the merge the last one was in the middle of, the way it adopts the slots'
  sessions. The merge gate now runs in a session of its own that outlives the runner, and a pass is kept
  per tree and gate command (`.runner/gates/`, a week), so the same merge is not tested twice. A fix or
  repair session in the master window records itself (`.runner/master.json`), the next run waits for it,
  and what it committed is kept under `refs/agent-runner/held/<ID>/` and reused when the merge is built
  again. A restart used to throw all of that away and redo it, which cost a whole gate run.
- The startup log no longer says every unmerged branch "finished while no run was up": it is "its merge
  was under way when the last run ended; adopting it" or "finished, not merged yet; merging it now", and
  the adopted one merges first.

## 0.17.0 (2026-11-05)

- `plan add` refuses text that looks like an open task's work (exit 3, nothing written), naming the open
  task: `plan note` it there, or add again with `--force` when it is different work. It used to add the
  task and then warn "may be the same work … drop this one", which agents kept reading as a refusal, so
  duplicates landed (three times in one repository in a week). A task's own split is never refused for
  looking like its parent; the runner's own filings (flaky tests, CI) are unchanged.
- `plan drop ID WHY`: close a task nobody will do, archived with `dropped: WHY` so its id stays used and
  what waits on it reopens. The old warning named a drop that did not exist.
- A note one side added to a task the other side ticked is no longer lost: the tick still wins in TODO.md,
  and after the merge the runner appends the note to the task's line in DONE.md (`plan.carry_notes`).

## 0.16.0 (2026-11-05)

- The task list and its archive merge by section and task instead of by line. `run` makes
  `agent-runner merge-plan` git's merge driver for TODO.md and DONE.md (`.git/config` and
  `.git/info/attributes`, shared by every worktree, never committed; a plan clone gets it on its next
  pull), so every merge of them goes through it: the runner's, a rebase, a person's. Each part merges
  against the base: sections by heading, tasks by id wherever they moved, and a task line's box, text,
  ` — notes` and `BLOCKED:` one by one. A task one side ticked stays gone though the other noted it, a
  moved heading comes out once, two notes on one line are both kept, a task added on each side goes where
  its side put it, and one id handed out on both sides keeps both tasks. Where both changed the same part
  of the merged branch's own task, the branch's words win (`AGENT_RUNNER_TASK`). Prose both sides
  rewrote falls back to git's text merge and its conflict. Replayed over 752 of this repository's
  past task-list merges, 739 come out as they did and the rest differ only in order or keep a move the
  old join undid.
- Removed what cleaned up after the line join: the runner's `dedupe_tasks` and `dedupe_headings` passes
  and `plansync`'s `tidy` (with its commit after a pull). TODO.md and DONE.md are no longer in the
  `[run] joinable` default (now `[]`) and are never line-joined, even when a config still lists them.

## 0.15.1 (2026-11-05)

- A joined task list keeps each heading no more often than either side has it. `--union` keeps both sides
  of a conflict, so a heading one side moved beside a line the other side changed came out twice; tasks
  filed later went under the empty first copy, and an ordered section's own tasks waited behind them.
  The extra copy is dropped and its lines go to the end of the first copy's section.

## 0.15.0 (2026-11-04)

- `runner.local.toml`: one machine's settings (`weekly_max`, `slots`, `model`, any key) laid over
  `runner.toml` key by key, so a person tunes their own run without editing the shared file. `run` creates
  it in the main checkout (all comments, changing nothing) when it is missing and never rewrites it, and
  keeps it out of git through the clone's `.git/info/exclude`. Worktrees read the main checkout's; it may
  wrap its tables in `[agent-runner]` like a wrapped config; a broken one stops the run naming the file.

## 0.14.1 (2026-11-04)

- `[run] ci_watch` defaults to `"auto"`: every workflow in `.github/workflows/` that runs on a push to the
  shared branch is watched, its push runs only (a nightly, release or manual run files nothing), so a red
  main becomes one critical task without any setup. `false` turns it off; a list still names workflows.
- A `gh` that cannot see the repository (not installed, not logged in, the wrong account) is said once in
  the run log instead of being read, every 5 min, as "no runs yet".

## 0.14.0 (2026-11-04)

Runners on several machines share one `[plan] repo` without stepping on each other.

- **Clashing claims settle.** Two runs that claim different tasks with overlapping files (or an ordered
  section, or a family) from plans read seconds apart both push, then both see both claims: the later
  claim gives way and the run picks again.
- **Claims hold touched files.** Each refresh adds the files the task's session has changed (its branch
  past main, and the slot's uncommitted and untracked edits), so a task line that lists too few files, or
  none, still keeps other runs off them.
- **Version in claims.** A claim records the runner's version and when it was claimed; `plan` and
  `plan claims` show it. A live claim from a runner older than 0.14 (which ignores other runs' files) is
  warned of once per run: upgrade every machine.
- **Faster dead-run recovery.** Claims refresh every 15 min (was 1 h) and go stale after 90 min (was 3 h).
  0.13 runners still refresh hourly, which stays inside 90 min.
- **No orphan claims.** A run's refresh drops its own claims on tasks it neither runs, queues nor holds an
  unmerged branch for, and a blocked task's finished branch (a concept round that ended while no run was
  up) is merged instead of sitting, claimed, for good.
- The claim file gains three lines (version, claimed at, files); 0.13 reads the first three as before.

## 0.13.4 (2026-11-04)

- A session whose `done` succeeded and that then sits quiet at its prompt past `[run] stall` is ended by the run
  itself, not just reported as stalled. The Stop hook's detached waiter can be lost, and two finished sessions
  held their slots for 5 and 8 hours.

## 0.13.3 (2026-11-04)

- Two runners on one `[plan] repo` keep off each other's files: another run's live claim counts as running
  here, so a task sharing its files, ordered section or family waits, not just the claimed task itself.
  A stale claim (a crashed run's) still holds only its own task.
- `dir/**` and `dir/*` on a task line are file patterns: they reserve everything under the folder, files
  that exist only on another branch included, and overlap the paths and patterns they match.

## 0.13.2 (2026-11-04)

- `run` no longer crashes starting a task when a worktree's folder was deleted without `git worktree remove`
  (a chat session's scratchpad, say): the edited-elsewhere check skips worktrees git lists as prunable.

## 0.13.1 (2026-11-03)

- `agent-runner home [slots|plan]` prints where this project's runner files are, from `[run] home` and
  `AGENT_RUNNER_HOME`, so a project's scripts (an emulator per slot, say) ask instead of rebuilding the path.

## 0.13.0 (2026-11-03)

- `[run] home` (default `~/runs/{repo}`) holds a project's worktrees (`s1`…, `merge`) and its `[plan] repo`
  clone (`plan/`), so the repos folder keeps only checkouts. `AGENT_RUNNER_HOME` overrides it on one machine.
  Worktrees in the old `<repo>-slots/` and a clone in `~/.cache/agent-runner/` keep being used until they are
  moved (`git worktree move`, a plain `mv` for the clone), with no run going.

## 0.12.0 (2026-11-03)

- `[plan] journal_layout = "id"`: one journal folder per task, `journal/<ID>/notes.md`, a retry in
  `journal/<ID>/<date>-<slug>/notes.md`. The prompt names that place, and the brief finds a `journal/<ID>/`
  folder and pastes its newest entry (a dated one beats an undated one). The default, `dated`, is unchanged.

## 0.11.1 (2026-11-03)

- A worktree over `slot_max_gb` is trimmed, not wiped: its least recently written git-ignored parts (folders
  split up to three levels, nothing under 1/500 of the cap) go until it is at half the cap, so the builds
  recent tasks used stay warm. On one project's slots that dropped old-hash library copies and stale
  cross-platform targets, 67 GB to 25 GB, and kept the live builds. The whole `git clean` stays for a disk
  under `min_free_gb`.

## 0.11.0 (2026-11-03)

- Worktrees no longer fill the disk. A slot or merge worktree over `[run] slot_max_gb` (default 50) is cleaned
  before its next task; under `[run] min_free_gb` (default 10) free, every free worktree is cleaned and no new
  task starts until there is room; slots past the run's count are removed once nothing uses them. The clean
  is `git clean -ffdXq` (every git-ignored file; `links` come back), or `[run] slot_clean`. Set either limit to
  0 for the old behaviour. One project's slots had grown to hundreds of GB of task-specific build folders.

## 0.10.0 (2026-11-03)

- `[plan] outline`: a command that prints one file's outline (`{file}` is the path). The brief shows it
  under each file the task line names, so a session starts with the map of what is where instead of
  paging through files to find its way. Each project supplies its own; unset, briefs are as before.
- `agent-runner cost`: where the workers' tokens go, per kind of tool call (a Bash command by program and
  subcommand or script, other tools by name), weighed by result size times the turns it stays in context.
  Reads Claude and Pi transcripts: by default the last 7 days of this repo's slot and merge sessions.

## 0.9.2 (2026-11-03)

- `[git] master_branch` optionally selects the local branch task worktrees use and tested merges target.
  It overrides remote `HEAD` discovery and fails before a run starts if the branch is missing or not checked out.
- The runner test suite passes on Windows.

## 0.9.1 (2026-11-03)

- `[plan] repo`: `plan` shows who has each claimed task and since when; `plan claims` lists them and
  `plan unclaim <ID>` drops one. A run re-stamps its own claims hourly, and logs once for each other claim
  unrefreshed for 3 h (STALE), so a crashed run on another machine no longer holds its tasks unseen.
- A run no longer starts a task that someone ticked or blocked in the seconds since its pick last read the
  plan: the claim pulls, and the task is checked again before it starts.

## 0.9.0 (2026-11-03)

- A task's long form moves to `plan/tasks/<ID>.md`, so the plan's top level is TODO.md, DONE.md and the
  overviews a person reads. Briefs, `plan <ID>`, ticks and CI-filed tasks use it; a long form still at
  `plan/<ID>.md` keeps working until it is moved (`git mv plan/<ID>.md plan/tasks/`).

## 0.8.0 (2026-11-03)

- `[plan] repo`: the plan in its own git repo, so several people and runners share one queue instead of a
  copy per branch (#3). Reads pull, edits push (a rejected push merges by line and retries), a run claims a
  task (`claims/<ID>`, pushed as it picks; offline it starts nothing) so two users' runs never take the same one, and a slot's `done` is ticked
  only once its merge lands, noting `landed <sha>`. `[plan] dir` may now be outside the repo (`~/…`) on
  its own too. Unset, nothing changes.

## 0.7.3 (2026-11-02)

- `[run] ci_watch`: a run reads the shared branch's GitHub Actions results (`gh run list`, every 5 min, never
  holding up a landing) and files one `critical` task for a red workflow run, with its failed jobs and the
  last lines of `--log-failed` in the task's long form; none again while it is open. openmx's pages.yml had
  been red on every push for two days, and its only sign was an email per push. `[run] ci_kind` (B) is
  the task's prefix.

## 0.7.2 (2026-11-02)

- Claude sessions no longer stop on a startup dialog nobody is there to answer. Lean mode leaves out user
  settings, so a session now passes `skipDangerousModePermissionPrompt` itself, and each slot and merge
  worktree is marked trusted in `~/.claude.json` (or `$CLAUDE_CONFIG_DIR`) before a session starts there.

## 0.7.1 (2026-11-01)

- Claude Code (Opus) is the default and needs no configuration; Pi is the way to other providers. The README
  and SETUP say so, and that Pi on an Anthropic model bills extra usage rather than the plan.
- Pi sessions run the repo's Claude Code PreToolUse hooks (`pi_hooks.ts`: exit 2 or a deny blocks the call,
  an updated command replaces it), so a repo's guards hold in Pi slots and fix sessions.
- `AGENT_RUNNER_BACKEND=claude|pi` picks the backend for one run, the repo's config otherwise kept.

## 0.7.0 (2026-10-30)

- A Pi backend (`[run] backend = "pi"`, or an `agent` executable named `pi`): provider-qualified models
  (GitHub Copilot, enterprise Copilot, Codex and other Pi logins), prompts by file at any size, retained
  sessions for resume and restart adoption, transcript statistics and stall checks. Claude stays the
  default. Setup, enterprise Copilot included: docs/SETUP.md.
- Pi sessions run interactive in their panes, watchable and takeable like Claude's; the bundled
  `pi_idle.ts` extension ends one after `idle` seconds settled at the prompt, not while text sits in the
  editor. Fix sessions use the `master-<repo>` window under tmux, print mode without it.
- Each agent CLI is a backend class (`Claude`, `Pi`) in `runner.py`; adding one is a subclass, see
  docs/AGENTS-EVAL.md. A fix session without tmux gets `slot_env`'s non-slot settings for Claude too.
- Claude: a brief too long for one command-line argument (96 KB on Linux, 24 000 characters on Windows) goes
  in whole as the system prompt (`--append-system-prompt-file <notes>/<sid>.brief`, given again on every
  resume), instead of a pointer the agent had to page through with Read. The file goes when the session ends.
- `docs/AGENTS-EVAL.md`: what a backend must support, candidate terminal agents (Copilot CLI, Codex,
  opencode, Arctic, Crush) by login type, and a test plan; `tests/agent_matrix.py` probes them. First
  live results: Pi and Copilot CLI pass the headless checks; Pi completes `run once` end to end.

## 0.6.34 (2026-10-29)

- The stall warning counts a session's quiet at a prompt from the end of its last tool run, not from its
  last transcript write. A tool's run writes nothing, so a long test run followed by a moment between
  commands was reported as "no transcript activity for 22 min at a prompt": openmx's P38, mid-gate.

## 0.6.33 (2026-10-29)

- `plan add <ID>`, a task split into subtasks, files them after the task and its earlier subtasks, under the
  task's own level tag or none, unless `--pri` or `@` says otherwise. Before, an agent's split was a `normal`
  follow-up like any other, so the rest of a person's task queued behind every follow-up: openmx's S149a-e.
  The prompt says to split this way.

## 0.6.32 (2026-10-29)

- Joining a task list keeps each task in the section the target files it under (the branch's, for the
  branch's own task), and moves a task's indented lines with it. Before, a doubled task stayed where its
  first copy was, so a branch cut before the plan was re-sorted put the old order back on merge: openmx's
  P185 moved 51 follow-ups back into Next.

## 0.6.31 (2026-10-29)

- A task whose text names a common file only in passing (`README.md`, in a spec) no longer lists every
  file of that name: a bare name that more than `BARE_MAX` (5) tracked paths share is prose, unless the
  line's `→` list names it, and that list now ends with its line instead of running on into the
  task's appended `plan/<ID>.md`. One openmx brief went from 597 READMEs and 129 KB to 9 KB.
- A prompt past 96 KiB reaches the agent as a short first turn pointing at `<notes>/<slot>.prompt`, as on
  Windows: Linux takes one argument of 128 KiB at most, and the session died at once ("Argument list too
  long", logged as "exited (no transcript)") every time the task came up.
- `plan brief` no longer crashes on a `j:` field when no journal directory is configured.

## 0.6.30 (2026-10-29)

- A restart never resumes a session that is still running. A slot whose last session's id is on a live
  process's command line (a pane opened before 0.6.20, untagged, so `adopt` cannot see it) is held, with
  a log line saying how to tag the pane, until that process ends; before, the run took its mid-turn
  transcript as cut off and resumed a second agent in the same worktree.

## 0.6.29 (2026-10-29)

- Follow-ups have a level: `plan add PREFIX TEXT --pri critical|normal|low|later`, tagged
  `(follow-up, LEVEL)` on the line. An agent's default is `normal`, which now files in `### Follow-ups`
  after every section a person queued, not at the bottom of the leading section (where it went ahead of
  them); `low` goes behind the normal ones, `critical` to the top, `later` to `### Parked`, which a run
  never starts. A person's task still goes to the top, untagged.
- Id prefixes name a kind of work: `[plan] kinds` (a table, letter -> meaning), shown in the prompt and
  by `plan kinds`; `plan add` refuses a letter it lacks. Without it the generic B/F/T/D/R/C are suggested.
- A test that failed and then passed alone gets a critical follow-up (`[run] flaky_kind`, default T) to
  make it robust when its merge lands; `[run] flaky` finds the same in a passing gate's own reruns.
- The prompt's follow-up paragraph is `{followups}`, for custom templates.

## 0.6.28 (2026-10-28)

- The runner ends what a finished session left running. Ending a session only ended the agent, so its
  tools' processes lived on under init: partyboard collected Gradle daemons and `find /` crawls that
  walked an sftp mount for up to 21 h, about 5 GB and two cores between them. Every process carrying
  `AGENT_RUNNER=1` and the session id of an agent no longer running is now sent SIGTERM (SIGKILL 5 s
  later) when a slot exits and at each temp sweep. POSIX only.

## 0.6.27 (2026-10-28)

- Prompt: every wait gets a time limit, and no whole-disk `find /`. partyboard N91 piled up
  `until grep "<line>" <log>` loops for over an hour after the runs they watched had died, and N97 crawled
  `/` for half an hour looking for one file.

## 0.6.26 (2026-10-28)

- The prompt's process rule is now: wait for and kill only the pids you started, never match processes
  by a command-line pattern. 0.6.25 suggested `tail --pid=...` for waiting; an agent then cleaned up with
  `ps | awk '/tail --pid/'` + `kill`, which matched every session's command line (each holds the whole
  prompt) and ended all three running sessions at once (partyboard N86, N90, N93; their work was kept on
  wip/ branches).

## 0.6.25 (2026-10-28)

- The session prompt tells agents to wait on a pid or `pgrep -x <name>`, never `until ! pgrep -f
  '<pattern>'`: the loop's own command line matches the pattern, so it never ends. Twice in partyboard
  (N35, N87) a session sat for 15-25 minutes on such loops, once before its `done`, where 0.6.22's
  finished mark can't help.

## 0.6.24 (2026-10-28)

- No more empty leftover branches. A slot whose only "change" is something a commit can't hold (a
  submodule edited inside, e.g. patches a build applies to it) showed in `git status`, so every reset
  saved an empty `wip/` or `leftover/` commit and pushed it: partyboard collected 87 of them. The save now
  keeps nothing when the snapshot's tree is HEAD's.

## 0.6.23 (2026-10-27)

- 0.6.22 still let a finished task sit for half an hour: a session with background tasks got the 30 min
  `AGENT_RUNNER_IDLE_BG` grace before the waiter first looked at the finished mark. Once `done` has
  succeeded the stop hook now hands the waiter the normal idle time.

## 0.6.22 (2026-10-27)

- A finished task no longer holds its slot. A successful `done` leaves `slot<N>.finished` in the notes
  folder (slots get `AGENT_RUNNER_SLOT`), and the idle stop then ends the session even when the agent still
  has a child process. Before, a leftover background command (a wait loop whose `pgrep -f` matched itself)
  kept a finished session alive for up to `AGENT_RUNNER_IDLE_MAX` (3 h). A slot clears the mark when it
  starts its next task.

## 0.6.21 (2026-10-27)

- A pane is a runner's only when its `@runner-repo` names that runner's main checkout; 0.6.20's
  fallback for untagged panes (by working directory) is gone. A pane opened before 0.6.20 is no one's:
  let its session end, or tag it (`tmux set-option -p -t <pane> @runner-repo <main checkout>`), before
  restarting a run.

## 0.6.20 (2026-10-27)

- Runners for different repos can share one tmux session. A pane now carries the repo it works for
  (`@runner-repo`, its main checkout), and each repo gets its own windows, `agents-<repo>` and
  `master-<repo>`. A restart adopts, holds and lays out only its own repo's panes; before, a second repo's
  runner adopted the first's `s1` (a task of the same id), held its `s2`/`s3` as "untracked sessions", and
  split its own panes into the first's `agents` window.

## 0.6.19 (2026-10-27)

- A run says when `main` has a newer version than the one running, with the command to upgrade
  (`pipx upgrade agent-runner`, `uv tool upgrade agent-runner`, or `git pull` in a clone). One read of
  `main`'s version, in the background, 5 s at most; silent when offline.

## 0.6.18 (2026-10-27)

- Each merge fetches the remote's shared branch first and, when it has commits the local one lacks, merges
  them into the merge before the gate (joined, or given to a fix session on a conflict). The gate tests
  both and the push goes through, instead of failing on a remote that moved.

## 0.6.17 (2026-10-27)

- No behaviour change: a simpler runner. Fewer git calls per scheduling tick: `pick` reads the tracked
  files once for every task line (`plan.files_on_line` takes them as `tracked=`), and one
  `git for-each-ref --no-merged` finds the finished `task/<ID>` branches for `pick` and `unmerged`, where
  each branch had a `rev-list` or `git log` of its own. The end of a tick picks at most once, not three times.
- The plan's 5 s read cache is gone (`plan.lines` reads the file): a read is cheap now that a tick makes
  few, and nothing has to clear it.
- A transcript's path is kept once found, so a stall check no longer globs `~/.claude/projects/*/` for
  every slot every 10 s.
- `plat.mux_choice` lost its unused `slots` argument; `gitops.shared_name` takes the name to fall back to.

## 0.6.16 (2026-10-27)

- A merge skips the gate only when `task/<ID>` is the tree `done`'s gate passed on, which `done` now records
  as `refs/agent-runner/tested/<ID>`. Before, any merge differing from the branch only in `[run] untested`
  files skipped it, so a fast-forward of a branch committed after `done`, by `done --no-test`, or by a
  session that never ran `done` was pushed untested.
- Rerunning failed tests on the base resets the merge worktree first and checks the checkout: a gate that
  left a tracked file edited made the checkout refuse, the "base" rerun ran on the merge, and a real
  failure read as "already fail without it; merged anyway".
- tmux refusing a pane fails that one start, or that fix or repair session (the merge is left for a human
  as for any failed fix), instead of ending the run or silently killing the merge thread.
- `[run] timeout` (3600 s): the gate, a retest, a `[run.join]` command, `before_start` and the sequential
  run's `on_exit` past it are stopped and count as failed. Pushes and fetches get no stdin, no password or
  ssh prompt (`GIT_TERMINAL_PROMPT=0`, `ssh -oBatchMode=yes` unless an ssh command is configured) and 300 s.
- Anything staged in the main checkout holds a tested merge, as edits to its files do: git refuses to
  merge onto it, and the merge was rebuilt, gated and refused every 10 min.
- A main checkout with another branch out is no longer switched to `main` to land a merge, carrying
  whatever was uncommitted there; the merge stays `task/<ID>` until `main` is out again.
- An earlier `wip/<ID>`, `leftover/<ID>` or `resumed/<ID>` is never overwritten: the new one is `-2`, `-3`, ….
- A `done` whose commit fails puts the plan back as it was, so it can run again (it said "no task <ID>").
- A slot asleep until a usage-limit reset lets go of `task/<ID>`, so another slot can take the task.
- When the remote's shared branch has moved, the runner's push no longer merges it into the main checkout
  and pushes that untested merge; it says so (0.6.18: the next merge takes it in).
- A SIGTERM or SIGHUP ends the run as Ctrl-C does, and either one waits up to a minute for a merge open in
  the main checkout to be committed or aborted first.
- The temp sweep matches only the slots' and the merge worktree's folders, not a sibling repo whose name
  starts the same, and never the main checkout's, where an interactive session has no session id to see.
- On Windows the runner's own command is quoted for Git Bash when a path has `'`, `$`, `` ` `` or `;`.

## 0.6.15 (2026-10-27)

- `plan add` names an open task that looks like the same work, with its id and the start of its text,
  under the new id. Nothing is printed when none does, so an agent's context pays only on a match: the
  new task's rarer words mostly on the other (half of them, weighted by how few tasks use them), or 30%
  of them plus a file that at most three open tasks name. Done tasks are not compared.
- Starting a task, the run logs any checkout outside its slots (the main checkout, a person's or a chat
  session's worktree) with uncommitted edits to the task's files: work there is invisible to the runner,
  and on 2026-10-26 two hand-made fixes sat uncommitted while the runners did the same two tasks.

## 0.6.14 (2026-10-26)

- A session's temp folder (`<tmp>/claude-<uid>/<project>/<session>/`: its scratchpad and background tasks'
  output) is deleted when the session ends for good. A session queued to resume keeps it. Claude Code
  never deletes these, and agents build in their scratchpads: here one tmpfs with a per-user quota reached
  EDQUOT holding 595 finished sessions' folders, 40 GB, 17 GB of it cargo target dirs.
- At startup and every 6 h the run also sweeps this repository's session folders (the main checkout's,
  the slots' and the merge worktree's) that no running process, no queued resume and no write in the last
  day claims: sessions that ended while no run was up, interactive ones, and those from before 0.6.14.
  Not on Windows, which has no /proc to tell a live session from an ended one.

## 0.6.13 (2026-10-24)

- Under tmux, fix and repair sessions are ordinary interactive sessions in a window named "master"
  instead of `claude -p`: you can watch one resolve a merge, or take it over by typing. Its Stop hook ends
  it 90 s after its answer, the runner then reads the merge worktree as before, and `fixer.log` gets the
  session id and its last words. There is no switch back to `-p`; only a run without tmux (Windows, the
  sequential run) still uses it, having no window to put the session in.

## 0.6.12 (2026-10-24)

- A batch that fails the gate gets one repair session for the whole batch before it is split: it sees every
  merge in it (`REPAIR_BATCH`), commits a fix on top, and the gate runs once more for all of them. Splitting
  cost every rider a gate run of its own and, for a clash between riders, a repair session each — in one
  night here every batch of fifteen failed to build together and went one by one.
- A rider whose conflict the line join cannot do gets a fix session inside the batch (`[run] fix_merges`),
  instead of waiting for its own turn and gate run.

## 0.6.11 (2026-10-24)

- A tested merge that cannot land only because of uncommitted edits in the main checkout is no longer
  parked as wip/<ID> after an hour. It waits 10 min holding MERGE, then gives the lock back; its branch
  stays task/<ID> (`pick` leaves it alone) and it is merged again, from a fresh build, as soon as the
  files it changes have no uncommitted edits (checked every minute). A stop leaves the branch for the next
  run's startup merge. Parking threw away finished, tested work for a fresh attempt: in one night an
  interactive session's uncommitted edits sent five finished tasks back to the queue, and serialised a
  dozen more behind an hour's wait each.

## 0.6.10 (2026-10-23)

- A merge that fails the gate gets one repair session before it is parked as wip/<ID>: a one-shot session
  like the fix session's, on the committed merge, with the gate's output (`.runner/merge-gate.log`). It
  commits a fix on top or says why not; the gate runs once more, and a second failure parks the branch as
  before. A clash git merges without a conflict (both sides adding one name, a caller of something the
  other side renamed) used to cost the whole task a fresh attempt. The repair is replayed when the merge is
  built again because the shared branch moved. `[run] repair_merges = false` turns it off.
- `[run] build`: a quick build (not the gate) the fix session runs before it commits, fixing what the two
  sides broke between them in files git merged on its own. Its prompt used to forbid any check, so it
  committed merges that did not compile.

## 0.6.9 (2026-10-23)

- A session cut off by an API error (the network dropped, `EAI_AGAIN`; the API down) is resumed in its own
  slot with `claude --resume` once the API answers, instead of being ended, its edits parked on wip/ and
  the task dropped for the run. At startup, a slot still on `task/<ID>` whose session stopped mid-turn
  while no run was up (a reboot) is resumed the same way. At most 3 resumes per session; a usage limit or
  a refused request is not a cut-off. No session starts or resumes while the API cannot be reached.
- `resume <ID>…` resumes a task's last session by hand once its slot is free, bringing its edits back
  from the wip/<ID> the runner saved.

## 0.6.8 (2026-10-23)

- A tested merge that cannot land yet says why, once, in the log (with a bell): uncommitted edits in the
  main checkout to the files the merge changes (named), or a merge of its own there. It used to wait up to
  60 min in silence, so the run looked hung with a finished task unmerged.
- A test gate that exits 130 without the run's Ctrl-C is a failure after 5 s. The merge thread used to
  wait on it forever.

## 0.6.7 (2026-10-22)

- A task a branch added under an id the target branch gave to another task meanwhile is renumbered (to
  the next id free on both sides) in a commit on top of the branch before each merge, and the lines the
  branch wrote that name it follow; logged as "renumbered P119 -> P122". Before, the join kept one line
  per id and silently dropped the branch's task.
- `plan tick` refuses an id listed twice as two tasks, instead of archiving one and leaving the other.

## 0.6.6 (2026-10-22)

- `plan add` run by an agent (`AGENT_RUNNER=1`) files its task at the bottom of the leading section, so
  follow-ups queue behind the work a person put there instead of jumping ahead of it. A person's `plan
  add` still goes to the top. `@ bottom` asks for the bottom either way.

## 0.6.5 (2026-10-22)

- The idle stop no longer ends a session whose agent is still running a background command: a `done`
  that waited past the 30 min background grace for a test slot was killed with its session, and its
  uncommitted work was lost. It waits for the command, up to `AGENT_RUNNER_IDLE_MAX` (10800 s).
- A session that ends with uncommitted edits has them saved before the slot is reset: on `wip/<ID>` when
  the task has no commits, else `leftover/<ID>`. Both are pushed and logged. `start` refuses to reset a
  slot whose edits could not be saved.

## 0.6.4 (2026-10-21)

- `agent-runner help` rewritten around real examples: running, adding tasks and subtasks, making one wait, finishing.
- `help order` and the README's *What runs when*: the order tasks start in, and the three ways to make one wait
  for another (subtask, `--after`, an ordered section).

## 0.6.3 (2026-10-21)

- `plan add`/`newid` on a task's own id give its next subtask (L3 -> L3a, L3a -> L3a1), which runs after its
  family instead of beside it; they used to give L31, a separate task that started at once.
- The top-level usage shows how to add a todo, and how to add one as a subtask.

## 0.6.2 (2026-10-21)

- The task prompt says commits in other repositories (a dependency or sibling repo the task needed) are pushed
  as usual; only this repo's main stays the runner's to merge. Publishing beyond git still needs the task to say so.

## 0.6.1 (2026-10-21)

- A merge that git rerere resolves entirely by itself is committed and no longer logged as an empty join.
- A merge git refuses to start (e.g. an untracked file in the way) parks the branch instead of being
  taken for a clean merge.

## 0.6.0 (2026-10-21)

- `run 1` and `run once` use a worktree, a pane and a tested merge like any other slot count; only
  `--no-tmux` (or no pane terminal installed) runs sessions in the checkout itself.
- `run once` exits when there is nothing it may start, and after its one task has merged.

## 0.5.0 (2026-10-21)

- Windows: ending a session first sends WM_CLOSE to every window in its process tree and gives those
  processes up to 10 s to exit (an emulator saves and shuts down), then `taskkill /T /F` as before.
- Windows: plan and journal paths handed to git, prompts and briefs use forward slashes, so `git show`
  and the plan-file union find TODO.md/DONE.md; `[run] retest` quotes `{names}` for cmd.exe.

## 0.4.1 (2026-10-20)

- A branch finished while no run was up is merged at startup even when its slot's worktree still has it
  checked out: idle slots are detached before the scan, not after it.

## 0.4.0 (2026-10-20)

- `run --shutdown`: power the computer off once nothing is running or merging and no open task can
  start (after 120 s idle). Blocked tasks don't keep it up.

## 0.3.1 (2026-10-20)

- Ctrl-C ends the run at once with one log line, no traceback and no second Ctrl-C; a gate it cut off
  isn't reported as a test failure.
- Slots start while branches finished before the run are still merging (the startup reopen no longer
  waits on the merge lock).
- The merge's test gate gets the `[run] slot_env` entries that aren't per slot (no `{n}`), e.g. a
  compiler cache, so it builds like the slots do.

## 0.3.0 (2026-10-20)

- Windows: a Windows Terminal tab per slot (`wt`), or a console window per slot when Windows Terminal
  isn't installed, through a slot shim that keeps each session's pid in `.runner/slotN.live`. The run
  lock, process checks, the Stop hook's timer and the end of a session work there too, from the
  standard library only. `[run] links` fall back to junctions and hard links without Developer Mode.
- `[run] mux` / `--mux tmux|wt|console|none` picks the terminal. The default is unchanged: tmux on
  Linux and macOS.
- `cmd_run(argv, prog=…)` and `cmd_stop(argv, prog=…)` take the wrapping CLI's name for `--help`;
  `stop` parses its arguments (`stop --help` no longer stops the run). Stop and idle messages name
  `[run] command`.

## 0.2.0 (2026-10-20)

From opentennis's `tools/parallel.py`, so it can switch over:

- Batch merges (`[run] batch`, on by default): finished branches waiting for the merge lock go in
  together under one gate run. A rider that conflicts beyond a join waits for its own turn, and a batch
  that fails the gate is split up.
- `[run] failures` + `retest`: a failure that passes when rerun alone counts as load. One the base
  already fails the same way merges anyway, and the ledger says so.
- `[run] untested`: globs (with `!`) for files the gate can't see; it used to be markdown only.
- `[run] before_start`: a check that holds new sessions (no display, device gone).
- `[run] not_attempt`: a regex on the last commit subject. Such a session, e.g. a spec phase, doesn't
  use up the task's one attempt.
- `[plan] brief`: the project's own brief command replaces the built-in brief.
- A restarted run adopts the sessions still running in its panes. A slot whose pane runs a session no
  run tracks is held, and a second `run` in the same repository refuses to start.
- The prompt goes through a file, because tmux's ~16 KB command limit broke long briefs.
- "(split into …)" parents wait for every subtask, blocked ones included, and tick themselves once those
  are done. A line that merely says "split into" isn't treated as a parent.

## 0.1.0 (2026-10-20)

The first release: the runner and plan tool out of openmx's and ps2-decomp-kit's `./kit run`, with
nothing game-specific in them.

- `run`, `plan`, `done` and `stop`: N sessions, one worktree and tmux pane per slot. A tested merge into
  the main checkout, then a push. One fix session per conflict, and `wip/<ID>` parking.
- The run stays up when it's idle and picks up a task a human unblocks (`retry_reopened`). From openmx
  9890a23.
- `s` + Enter in the runner's pane stops it gently, through the same STOP file as `run stop`. From
  openmx 0d94657 and ps2-decomp-kit 621e76e.
- A hand edit with `plan tick|block|…` in the main checkout commits at once, so a merge never waits on
  it.
- Packaging: `pyproject.toml` (stdlib only, Python ≥3.11) and an `agent-runner` console script.
  `python -m agent_runner` also works, and `./run` from a clone still works. There's an
  `agent_runner.__version__`, and `agent-runner --version` prints it.
- Config: `AGENT_RUNNER_CONFIG` names a file whose `[agent-runner]` table (or top level) replaces
  `runner.toml`, and the runner hands it on to every slot.
- Hooks for a wrapping project: `[run.join]` per-file joiners, the `[run] suspect` regex (flagged in
  the ledger), `[run] precommit` with `done --skip-check`, and `[run] command`. Also `[run] pass_env`,
  `{slots}` in `slot_env`, placeholders in `prompt_extra`, and `[plan] brief_extra`. `on_exit` now also
  gets the slot env in `run once`.
- Library API: the names in `__all__` of `agent_runner.plan`, `.done` and `.runner`. `plan.PROG` and
  `done.PROG` let a wrapper's messages name its own command.
