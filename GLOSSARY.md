# agent-runner

agent-runner works a repo's plan unattended: each task gets an agent of its own, and the result is tested and
merged while a person steers. These are the words the person, the briefs and the code use for it; where two
words exist for one thing, use the term and avoid the rest. (Format after mattpocock/skills domain-modeling, MIT.)

## Language

### Work

**Task**:
One piece of queued work in the plan, named by an id: its kind letter and a number, like `F48`.
_Avoid_: ticket, issue, todo, job, item

**Kind**:
The sort of work a task is, given by the letter its id starts with (bug, feature, tests, docs, research, cleanup, concept).
_Avoid_: type, category, label

**Concept**:
Work whose outcome is a page of two or three options and a recommendation, built only once the person picks one.
_Avoid_: mock-up task, design task, proposal

**Gate**:
The project's test command that a task must pass before it is ticked, and its merge before it lands.
_Avoid_: CI, checks, test suite

**Take**:
Doing a task now, outside the queue, in a worktree and branch of one's own that the run leaves alone.
_Avoid_: grab, do it locally

**Claim**:
The mark a run or a take puts on a task it has started, so that no other run starts it too.
_Avoid_: lock, lease, reservation

**Same work**:
Two tasks with the same goal on the same files.
_Avoid_: similar task, overlap, related

**Sweep**:
Work over many pages, queued as one task per set of pages.
_Avoid_: pass, batch, bulk task

### The run

**Run**:
One working of the plan by agent-runner, from start to stop.
_Avoid_: session, job, daemon

**Slot**:
One of the run's places to work a task in parallel: a worktree and the agent session in it.
_Avoid_: worker, lane, agent

**Merge worktree**:
The run's own checkout where finished work is merged and gated before the main branch moves.
_Avoid_: merge checkout, staging, merge slot

**Fixer**:
A short agent session that rescues a merge: a fix session for a conflict, a repair session for a failed gate.
_Avoid_: master, merge agent, resolver

**Notes dir**:
The folder in the main checkout where the run keeps its logs and the files it hands the person.
_Avoid_: log dir, state dir

### Talking to the person

**Control session**:
An agent session in the main checkout through which the person reports on, steers and queues work for the run.
_Avoid_: control window, coordinator, chat

**c1**:
Number 1, the project chat older versions kept beside the run; retired (F176): numbers start at 2, and an older c1 is a chat like any other.
_Avoid_: control 1, main session, first control session, project chat

**Remote**:
Running the run's sessions on Remote Control, so the person steers from claude.ai/code or the Claude apps; the git remote that merges go to is the **push remote**.
_Avoid_: cloud, online, headless, remote (for the push remote)

**Needs you**:
The list of what waits on the person: concepts waiting for a pick, and tasks blocked on a CONFIRM (a check by hand), a DECIDE (a question or a choice) or a BLOCKED (access or a fix only a person can make).
_Avoid_: inbox, waiting list, blocked

**Shelve**:
Setting a Needs you item aside: the task stays blocked but leaves the list, and shows under the Plan view's Parked group until brought back.
_On screen_: Shelved until you bring it back; Bring back
_In code_: shelved_rows, shelved_back
_Avoid_: park, snooze, defer, drop

**Voice file**:
The person's own rules for how sessions word things, one per line, grown from what they say; one for all projects, and a project's own that overrides it.
_Said_: my wording, voice
_On screen_: The person's wording
_In code_: voice.py, agent-runner voice, [run] voice
_Avoid_: style guide, preferences

**Claude Code drift**:
Claude Code changed something agent-runner reads that is not a documented interface, so a part of agent-runner stopped working; said once per Claude Code version as a Needs you line
_Said_: Claude Code changed something
_On screen_: Claude Code X changed Y; Z no longer works
_In code_: claude_drift, EV_DRIFT, transcript_drift, link_drift, remote_answer_drift, claude-drift.json
_Avoid_: breakage, incompatibility

**Restyle**:
A style a person approved for the future too: a page of each current page or screen that would change, before and after, waiting for an OK; the interface work is held on it and reopens with the style once it is approved
_Said_: the future too, make everything look like this
_On screen_: restyle K9, held for restyle K9
_In code_: plan.restyle, plan.hold, plan.release_held, loop.restyles, plan restyle
_Avoid_: redesign, retheme

**Hidden control session**:
A control session with no window, as every control session starts (attach cN shows it); what it prints goes to its log
_Said_: control session in the background
_On screen_: c2 is up in a hidden terminal
_In code_: hidden_control, control_new_hidden, controlN.log
_Avoid_: headless control, background control

**Context warning**:
A slot session's context grew past the set size; the exit line and since say how big and which files filled it, and the session is told once, as a turn ends, to finish and file the rest as a part
_Said_: context budget
_On screen_: B32 peaked 168k (over 150k): runner.py 61k, test_runner.py 22k
_In code_: context_warn, context_over, EV_CONTEXT, cost.filled
_Avoid_: context limit, hard limit

**Exact-repeat command**:
the same shell line run again, word for word, in one session; its later results stay in context beside the first
_Said_: repeated command
_On screen_: exact-repeat commands
_In code_: files_report, rep_kept
_Avoid_: duplicate command

**Fold**:
Before a merge, a follow-up the branch filed that the target branch already got from another slot goes into that task as a note instead of becoming a second task.
_Said_: dedupe follow-ups
_On screen_: folded Y2 into Y1
_In code_: fold_doubles, join.renumber_doubles
_Avoid_: dedupe, collapse, squash

**Since digest**:
What since prints by default: one line per task with its last state under Started, Landed and Stuck, capped, ending with an ask for the full list (the raw log, which a control session hands over as a page)
_Said_: since summary
_On screen_: since yesterday 00:00: 2 started, 159 landed, 2 stuck
_In code_: since_digest, since --all
_Avoid_: event dump, raw log

**Guide page**:
One page of longer rules a session reads when an ask fits it; the control brief names each one instead of carrying its text.
_Said_: guide topic
_On screen_: agent-runner guide <topic>
_In code_: guide.TOPICS, guide.CONTROL_TOPICS, control_topic()
_Avoid_: help page, doc

**Issue watch**:
The run reading the repository's open GitHub issues and filing one task for each new one; a GitHub issue is the outside report, the task is the work on it
_Said_: issue watch
_On screen_: issues_watch
_In code_: issues_watch, issues_trust, watch_issues, agent_runner/issues.py
_Avoid_: ticket import

**Auto release**:
The run queuing a release task by itself, after a set number of tasks have landed (it then starts at once) or when it goes idle with landed work
_Said_: auto release
_On screen_: queued V<n> (auto_release: 10 landed / idle)
_In code_: [run] auto_release, autorelease.auto_release, autorelease.landed_since_release, plan.add_release, plan.cut_release, release_ahead, EV_AUTO_RELEASE
_Avoid_: auto publish, auto version

**Manage releases**:
The setting for whether a project has releases to manage; off, none is shown or queued by itself, and an open release is an ordinary task
_Said_: manage releases
_On screen_: Manage releases
_In code_: [run] releases, autorelease.releases_on, snapshot manage_releases
_Avoid_: release mode, release toggle

**Run page**:
One view of the whole run (sessions, queue, what needs the person, concepts, the run log, the release) that the web page, the terminal UI and the claude.ai copy all show, with the same actions on it
_Said_: run page
_On screen_: Run page
_In code_: ui_model.snapshot, ui_model.act
_Avoid_: dashboard, status page

**Theme**:
The Run page's set of colours, in the terminal and on the web: ryha, omarchy, terminal or light.
_Said_: theme
_On screen_: T theme
_In code_: theme.py, [ui] theme, THEMES
_Avoid_: skin, colour scheme, palette

**Run page copy**:
The run page published on claude.ai by the run, read-only, linking each chat, for when the machine running the run cannot be reached
_Said_: claude.ai copy
_On screen_: run page copy
_In code_: page_copy_html, page_copy_tick, run-page-copy.html
_Avoid_: mirror, snapshot page

**Open a slot**:
Put one slot's session on Remote Control from the run page, so it is listed in claude.ai/code and the Claude apps until it ends
_Said_: open it
_On screen_: open sN in the Claude apps
_In code_: slot_open, open_session
_Avoid_: attach, share

**Session feed**:
A session's transcript as data: the agent's words, the person's, and each tool step with its output, newest last. Talk reads it; a chat shows the session itself (The session), not this
_Said_: feed
_On screen_: feed
_In code_: ui_model.feed, feed_entries, /feed/NAME
_Avoid_: log, terminal, thread

**Force send**:
Sends what the session still has queued at once, interrupting it. With words (`chat_to` with `force`, no page control) it interrupts with Escape, waits until Claude Code is at rest, and sends the message once. Send with words queues.
_Said_: force send
_On screen_: "Force send" (the arrow's label while the box is empty and a sent message is still queued)
_In code_: sendIs, forceQueued, session_now.force_queued, session_now.force_send, chat_to (force), .send.force
_Avoid_: interrupt and send, resend

**Session chips**:
The row of chips above a chat's message box that holds the lines Claude Code draws under its prompt, which the frame hides: Working, the mode, N shells, N agents, Update. Each opens a sheet. On a chat on the harness loop the row holds only Working and the model (`Codex · gpt-5.6-sol`, sheet `sessmodel`).
_Said_: chips
_On screen_: Working, Update, 2 shells
_In code_: sessionChips, .schips, session_now.py
_Avoid_: footer, status bar, toolbar

**Slim message box**:
The row at a session's bottom that stands in for the message box while the reader has scrolled up: the draft or its placeholder, and while Claude works, Working (its sheet opens) and Stop. A tap opens the full box, and the chips and top bar come back.
_Said_: the type button
_On screen_: Reply to c2, Working, Stop
_In code_: .slimbox, slimDraw, .slim
_Avoid_: thin strip, strip, handle, bar

**Session theme**:
The Claude Code theme the run gives the sessions it starts (control sessions and slots), named `agent-runner` in their settings: its colours each browser fills from the run page's light or dark. A person's own terminals keep theirs.
_Said_: the run's look
_On screen_: none (the session looks like the page)
_In code_: session_theme.py, session_look, frame_look, arLook
_Avoid_: session look, terminal theme, skin

**Quick ask**:
One of the Status page's ready-made questions, sent in a new control session with one key or tap
_Said_: quick asks, presets
_On screen_: since last look, since yesterday, what needs me, usage
_In code_: QUICK_ASKS, quick_ask
_Avoid_: preset, shortcut

**Terminal view**:
A session's own terminal, shown through ttyd in a chat or slot (`attach NAME` shows the same one); with no ttyd, how to install it (TTYD_INSTALL); on Windows the same, through the session's ConPTY port
_Said_: terminal
_On screen_: terminal
_In code_: terminal_mode, terminal_fallback, session_frame.py, /terminal/NAME
_Avoid_: console

**Direct edit**:
Changing a queued task's fields (what, kind, priority, files, after) on the Run page, each field with its own key, written straight to the plan
_Said_: direct edit
_On screen_: direct edit
_In code_: editHTML, plan_change, plan_add
_Avoid_: form, inline edit

**Chat edit**:
Saying in your own words what to change about a task, or what a new task is, for a control session to write into the plan
_Said_: chat edit
_On screen_: chat edit
_In code_: data-form=chatedit
_Avoid_: AI edit, prompt edit

**Device list**:
Every project's run and sessions on this device, numbered so one can be attached by its number
_Said_: agent-runner list
_On screen_: agent-runner list
_In code_: cmd_list, device_projects, device_sessions, list_text
_Avoid_: session list, ls

**Style rules**:
How the run app looks, moves and speaks: its tokens, parts, states, words, motion and scrolling, which every change to it follows
_Said_: the style rules, STYLE.md
_On screen_: docs/STYLE.md
_In code_: docs/STYLE.md, test_style_f83, the tokens in web_page.html's :root
_Avoid_: style guide (that is the voice file), design system, theme

**Status view**:
The run app's one page on the run itself, in four sections: Run (the run's state, notices and controls), Working (a row per slot), Merging (the tasks that merge now) and Usage
_Said_: Status
_On screen_: Status
_In code_: statusHTML, NAV
_Avoid_: Activity, Agents page, dashboard

**State pill**:
The run's state in a word or two at the top of every page of the run app: Running, Paused, Stopping, Caps forced or Not up
_Said_: the pill
_On screen_: Running, Paused, Stopping, Caps forced, Not up
_In code_: ui_model.run_state, pill()
_Avoid_: badge, tag, label

**Sheet**:
A panel that slides up over the run app with more choices about what is on screen
_Said_: More… sheet
_On screen_: More…, Talk settings
_In code_: SHEETS, openSheet
_Avoid_: modal, popup, dialog (a pick sheet is another thing: a DECIDE's page of options)

**Overview**:
The run app's main page on Home, all projects at once: Needs you over all projects, then a card per project (running, idle or paused first, then off, by name)
_Said_: all projects page
_On screen_: Overview
_In code_: projectsHTML, projectCard
_Avoid_: dashboard

**All projects**:
The sidebar's first row, and the level it opens: the sidebar turns into the project list (Overview, Running, Idle, Off, Devices) with a count of what needs you in other projects; a project turns it back
_Said_: All projects row, project list
_On screen_: All projects
_In code_: allSide, allRow, goUp, goDown
_Avoid_: project switcher, switcher

**Off page**:
The fallback page of a project with no run up, shown by Runner Home only when the page-only process cannot start: its name and state, Start run, what it needs and its queue; it becomes the run's app once the run is up
_Said_: off page
_On screen_: the project's name and state, Start run
_In code_: offHTML, HomeHandler.off_page
_Avoid_: stopped page, off project page

**Quiet chat**:
A chat that needs no reply and has had nothing said in it for `[ui] chat_quiet`: grayed, at the bottom of Chats. Opening it does not move it; the quiet ends when something is said in it, or it is pinned or renamed
_Said_: quiet chats
_On screen_: Quiet
_In code_: chat_quiet, chatGroups, holdUp
_Avoid_: archived chat, old chat, stale chat

**Device override**:
A setting this machine's runner.local.toml sets over the project's runner.toml
_Said_: This device
_On screen_: This device (the Settings tab), This device: 5 (its marker on Project), Reset
_In code_: save_local_setting, setting_device, setting_reset, overSays, overNote
_Avoid_: local config, user setting

**Run app**:
The chat app a run serves on the web for a phone or a desktop: Home, a chat per session (each shows the real session, see The session), and the Plan, over the same Run page
_Said_: run app
_On screen_: run page link (in `status` and the run log)
_In code_: web_page.html, web.py, [run] web
_Avoid_: web page, dashboard, web UI

**The session**:
What a chat or slot shows in the run app: the real Claude Code session through ttyd, in one frame between the header and the message box. The page never draws or redraws it, except that a switch may show the chat's Last screen until the session draws.
_Said_: the session, the real window
_On screen_: (no wording: the session itself)
_In code_: session_frame.py, #feed, /t/TOKEN/NAME/
_Avoid_: thread, transcript, chat view

**Key row**:
The row of keys (Esc, Tab, ↑, Enter, Ctrl-C, Text, ←, ↓, →) that folds out from the message box's keyboard button on a touch device, for a session's menus.
_Said_: the keys
_On screen_: Esc Tab ↑ Enter Ctrl-C Text ← ↓ →
_In code_: FEED_KEYS, web_page.html
_Avoid_: keypad, shortcut bar, toolbar

**Run controls**:
The buttons and keys that change the run itself from the run page or agent-runner ui: slots, pause, force, stop, and stopping one slot's task
_Said_: run controls
_On screen_: Run controls
_In code_: RUN_CONTROLS, run_control, controls(), controlReq, answer_of, row_labels
_Avoid_: run buttons, admin controls

**Concept chat**:
A new control session about one concept, told which concept and its page, to change that page and build nothing until a plain go
_Said_: chat about it
_On screen_: N chat about it; Chat
_In code_: concept_chat, concept_chat_text
_Avoid_: concept session

**Parked task**:
A queued task at level later, in the plan's Parked section: a run never starts it until a person unparks it, which moves it to Follow-ups. The Plan view's Parked group also lists shelved tasks (see Shelve), after the parked ones; they stay distinct from these. A split task with an open part neither parked nor shelved is not parked: it stands in the queue.
_Said_: parked
_On screen_: Parked: a run won't start it
_In code_: state 'parked', unpark, parkedLast, queueGroups
_Avoid_: later task, on hold

**High task**:
A queued task at level high: a run tries it after the critical ones and ahead of the rest, wherever its line stands, as soon as a slot is free. Only critical gets the merge order, the alone turn and an interim release.
_Said_: high priority
_On screen_: High priority: goes ahead of normal tasks, as soon as a slot is free
_In code_: --pri high, high_tasks, next_pri
_Avoid_: urgent task, critical task

**Attach**:
Put this terminal on a session's own terminal, to watch it and type into it, until Ctrl-b d leaves it running (on Windows 1809 and later too; the run app's session has no detach key)
_Said_: attach
_On screen_: attach s2; Back: Ctrl-b d
_In code_: cmd_attach, attach_session, session_socket, slotN.sock, controlN.sock, attach_windows.py
_Avoid_: open (that is Open a slot), connect

**Run picker**:
What bare agent-runner shows at a terminal: one row per run on this device, the current folder's project first, to pick one; picking a row opens its launcher, and no pick starts a run
_Said_: pick a run
_On screen_: agent-runner · pick a run
_In code_: cmds.cmd_pick, pick_run, picker_rows
_Avoid_: run menu, chooser

**Launcher**:
The screen after the run picker: the picked run's status and run page link, and keys to open the page, open its terminal UI or copy the link; for a run that is not up, also s to start it in the background
_Said_: launcher menu
_On screen_: w open the run page · t terminal UI · c copy the link · s start the run
_In code_: cmds.launch, launcher_text
_Avoid_: action menu

**Follow an upgrade**:
When the run restarts on a newer agent-runner, an open TUI starts again on it where it was; an open run page does not reload, it shows the New version popup
_Said_: follow an upgrade of the run
_On screen_: (no wording: the TUI starts again; the run page shows the popup)
_In code_: follow_upgrade, newer_version, PLACE_ENV, snapshot 'version'
_Avoid_: hot reload, auto-refresh

**Run view**:
The run's log followed live in any terminal, taking the runner keys typed there; Ctrl-C leaves it and the run keeps going
_Said_: attach, the runner's pane
_On screen_: runner keys: type one here and press Enter
_In code_: run_view.py, run_view, view_key, keys_help(view=True), attach run
_Avoid_: runner pane, runner window, console

**Model role**:
A type of work the runner picks a model for: a task's session, the spec review, a fix, docs edits, control sessions, the run page copy
_Said_: type of work
_On screen_: [models] code, review, fix, docs, control, feed
_In code_: [models], Config.models, resolve_models, subagents
_Avoid_: model kind, model type

**Runner Home**:
One always-on page for every project on the machine: each one's run state and what needs the person, buttons to start, pause, resize and stop its run, and a way into its run app
_Said_: Home, runner home
_On screen_: Runner Home
_In code_: home.py, HomeServer, project_rows, run_action, install
_Avoid_: dashboard, hub

**Runs alone**:
A task tagged `(alone)` that starts only when nothing else runs or waits to merge in the run, and starts nothing beside it; any kind of task, a release included
_Said_: runs alone, nothing beside it
_On screen_: runs alone, (alone)
_In code_: `(alone)` tag, plan.alone, plan.alone_ids, plan add/edit --alone, Held.alone, sched.clash, sched.turn_of
_Avoid_: exclusive, release_alone

**Task budget**:
The most tokens or dollars one task's session may use; past it the task stops at a clean point and is parked as wip/<ID>
_Said_: per-task budget
_On screen_: s1 speed up the parser [T3] 12 min 2.5M tok $7.50
_In code_: task_tokens, task_usd, budgets, budget_mark, cost.Spend, SPENT
_Avoid_: quota, limit

**Device Vitals**:
Runner Home's view of each machine that runs agent-runner: how many more agents fit, its CPU, GPU, memory, disk and temperatures over the last day, what the runner keeps on its disk, and each session's share
_Said_: vitals, device vitals
_On screen_: Devices; Device Vitals
_In code_: vitals.py, Vitals, /devices, /device, page/052-device.js, devHTML
_Avoid_: monitor, stats, health

**Headroom**:
How many more agents a machine can take now: the smallest of what its free memory, CPU load, disk above min_free_gb and the usage caps allow, at most six
_Said_: room, how many more agents
_On screen_: Headroom; Room for N more agents
_In code_: headroom
_Avoid_: capacity, spare slots

**Runner footprint**:
What agent-runner itself keeps on a machine's disk: worktrees under the run home, session temp folders, logs and wip/ branches
_Said_: footprint, what the runner uses on disk
_On screen_: Runner footprint
_In code_: footprint
_Avoid_: cache, junk

**Clean**:
Removing only what the runner made and no longer needs (ended sessions' temp folders, worktrees merged into the main branch (one holding git-ignored files that are no build output or link is left unticked), wip/ branches the person ticks), after listing it first; ended sessions' temp folders also go by themselves on Home's regular walk, while worktrees and wip/ branches wait for the person; old build output in a runner worktree of a project whose run is off goes by itself on the same walk
_Said_: clean up, free space
_On screen_: Clean; Remove ticked
_In code_: clean, clean_plan, /vitals/clean, auto_clean, clean_builds
_Avoid_: purge, wipe, prune

**Peer**:
Another machine's Runner Home that this Home shows under Devices, listed by its link or found on Tailscale
_Said_: other machine, other Home
_On screen_: Devices
_In code_: peers, peer add, peer_links
_Avoid_: node, remote host

**Device alert**:
A warning Device Vitals raises about a machine (too hot, disk nearly full, a Claude login ending), told to the person as a needs-you line
_Said_: device alert
_On screen_: needs you: box: CPU at 95°C (over 90°C)
_In code_: EV_DEVICE, vitals.push_alert
_Avoid_: drift

**Talk**:
The run app's spoken chat: the person taps a big mic and speaks, its own control session answers in short spoken sentences, and the reply is read aloud; a chat box under it takes typing.
_Said_: talk mode, by voice, hands-free
_On screen_: Talk, New Talk chat
_In code_: talk (web action), talk_ask, TALK_BRIEF, talkSend, newTalk
_Avoid_: voice mode, assistant, dictation

**Git fence**:
The check before each of a slot agent's tool calls that refuses a push, a destructive git command or an edit outside its worktree
_Said_: git fence
_On screen_: the git fence
_In code_: tools.fence, fence_hook, fence_hooks
_Avoid_: guard, sandbox

**Ask**:
A slot agent's question to the person: the task waits under Needs you, and the answer goes back to the same session
_Said_: run ask
_On screen_: asked with run ask
_In code_: cmd_ask, park_asked, block_asks, answer_ask, asked/<ID>
_Avoid_: question tool, AskUserQuestion

**Session pane**:
The selected session shown as itself in a tmux pane beside the terminal UI's panels, where the person types to it, selects and copies; Ctrl-f makes it full-screen between the top and bottom bars
_Said_: the right pane, the real Claude Code session inside the TUI
_On screen_: (no wording: the session itself, beside the panels)
_In code_: SidePane, RunPage.sync, want_side
_Avoid_: chat view, side window

**Harness loop**:
agent-runner's own agent loop, which runs a task, fix or control session on a model from a provider other than claude
_Said_: our own agent loop, the loop engine
_On screen_: harness loop
_In code_: harness.mjs, slots.Harness, config.harness_model
_Avoid_: loop engine, Pi loop

**Provider login**:
the sign-in or key a model provider other than claude needs before the harness loop can run a session on it
_Said_: login, run login
_On screen_: run login
_In code_: login.py, login.login_of, login.park_unlogged, provider_login.py, harness.mjs --login
_Avoid_: auth, credentials, token

**Chat order**:
The order of the run app's Chats list: pinned chats on top in their own order, then the rest newest to oldest by last activity, so every page shows the same list
_Said_: drag a pinned chat to reorder, pin chats, newest to oldest
_On screen_: Pin this chat / Unpin this chat
_In code_: chat_order, pin_list, chatSort, chatMove, chat_order.json
_Avoid_: chat sort, favourites

**Pick link**:
A plain link behind a pick sheet's Send that answers the run with that option when tapped, through a one-use code made for that item
_Said_: option button
_On screen_: Go with B / Answer the run with these picks
_In code_: web.pick, web.pick_base, /pick
_Avoid_: approve URL, magic link

**Outbox**:
The run page's list of actions a person took that the run has not answered yet: each shows at once, is sent behind in order, is sent again after a dropped connection or a reload, and stays with Retry and Discard if the run refuses it.
_Said_: do those things in the background
_On screen_: N sending · N failed · tap to see
_In code_: S.ob, outbox(), drain(), obSettle, ActsOnce
_Avoid_: queue, pending list

**Stream engine**:
A slot's Claude Code session run with no terminal, reading its brief and every tell as messages and ending when its turn ends with nothing more sent; it has no Remote Control. The terminal engine, an interactive session in a hidden terminal, is the other.
_Said_: headless Claude Code, claude -p
_On screen_: runs headless ([run] engine = "stream")
_In code_: [run] engine, slots.stream_engine, slots.run_stream, slots.StreamInput, <notes>/streams/<sid>.jsonl
_Avoid_: pipe mode, API mode, background session

**Fallback chain**:
The ordered list of models a task goes on with when its provider hits its usage cap or quota; new tasks go back to their own model once the cap resets
_Said_: fallback
_On screen_: [models] fallback
_In code_: C.fallback, agent_runner/fallback.py, chain_next, capped.json
_Avoid_: failover, backup model

**Release row**:
The row, or rows, that say how each release stands: each open release as a row of the Queue at its place in the plan order (no Releases group); the auto release's count, dimmed, before the task it stands before, when auto release is counting; then the newest one that landed (in status and `agent-runner plan`, not in the Queue)
_Said_: next release
_On screen_: V17 Release · waits for 2: F1 one, F2 two / Waits for everything above / Waits for 3 tasks / releasing now / V16 Release 0.62.0 · released 17:06 / Next release · auto at 10 landed: 6/10
_In code_: ui_model.release_rows, ui_model.pin_releases, status.release_line, planRows, queueCard, queue_with_releases, planReleases, plan._releases, relWords, gripWaits
_Avoid_: release banner

**Pitch**:
A set of landed changes grouped for one person to approve before they are pushed, or undone with Not this.
_Said_: pitch
_On screen_: Approve / Not this
_In code_: pitch.py, pitch1, pitches.json
_Avoid_: pull request, review, release note

**Approve to push**:
A run mode where merged work is held on the local branch until a person approves it, and only then pushed to the remote.
_Said_: approve mode
_On screen_: N changes wait to be pushed
_In code_: [run] approve, pitch.on
_Avoid_: PR mode, gated push

**PR mode**:
A run mode where each finished task is a pull request on GitHub that a person merges, and the runner never merges or pushes the shared branch.
_Said_: PR mode
_On screen_: Pull requests
_In code_: [git] pr, pr.py, prs.json
_Avoid_: approve mode, gated push

**Mic report**:
What happened on Talk's mic from the press to the end of a listen that heard no words or sent words (with what ended it), and to the sound of replies, each event with its time, to copy and send; it holds no words
_Said_: the mic log
_On screen_: Copy mic report
_In code_: micLog, micReport, micCopy, TK.trail
_Avoid_: trace, debug log

**Held message**:
A person's message to a control session, or to a session started from a Claude app, whose reply was only a usage-limit error or was cut off by the limit, kept and put into that session (a copy of an app session) once the limit is over
_Said_: messages dropped because of the weekly limit
_On screen_: asks wait for the usage limit
_In code_: control_held, <notes>/held/
_Avoid_: lost message, queued message

**Settled line**:
The one line the run types into a control session about an item when that item was settled elsewhere
_Said_: the chat was told nothing
_On screen_: From the runner, not the person: R81 was dropped at 13:28 by c4
_In code_: control_settled, <notes>/settled/
_Avoid_: notification, alert

**Run speech**:
Talk's replies made into sound on the run's own machine and played by the run app; without it the browser's own speech reads them.
_Said_: the voice, natural voice
_On screen_: Voice, Default (af_heart)
_In code_: speech.py, speech_worker.py, /speech, runVoice, playClips
_Avoid_: TTS, voice file

**Setting's home**:
Where a change to a setting is saved: both are saved when the Settings bar's Save is pressed, this device in runner.local.toml, everyone in runner.toml
_Said_: this device or everyone
_On screen_: this device, everyone
_In code_: setting_words.home, settingSide, setting_project, plansync.commit_file
_Avoid_: scope, level

**Shared tool**:
Something only one task can use at a time, such as a test phone or a device; named under [run.tools] and asked for by a task's needs: field
_In code_: shared_tools.specs, [run.tools], needs:
_Avoid_: resource, device lock, semaphore

**Wait for a tool**:
A task giving up its slot until a shared tool is free; its session then goes on, ahead of other tasks
_In code_: cmd_wait_for, park, waiting/<ID>
_Avoid_: park, poll

**New chat view**:
The empty chat a card's Chat, Add a task or New concept opens, titled with what it is about; its session starts with the first message
_Said_: empty new chat
_On screen_: The chat starts with your first message.
_In code_: ctxKey, isNew, newPh, about, S.ctx
_Avoid_: About line, draft chat

**Wait for memory**:
A task giving up its slot after a command was stopped for low memory, until memory is free; its session then goes on by itself, as for a shared tool
_Said_: stopped for low memory
_On screen_: waits for memory, 5.0 GB free, goes on at 6.0 GB
_In code_: MEMORY, _wait_memory, waiting/<ID>
_Avoid_: memory tool, memory lock

**Task size**:
How big a task is, from its code files, numbered outcomes and length of text; over the set size it is split into parts
_Said_: oversized task
_On screen_: F5 is too big for one session (size 37, over 10: ...)
_In code_: task_size, size, too_big, SPLIT_PROMPT
_Avoid_: weight, points

**Device**:
A machine or test rig that agents reach over SSH or another way, added by a person on the Tools page; a project uses it as a shared tool, and its secrets stay on this machine.
_Said_: device
_On screen_: Tools, Add a device
_In code_: devices.py, run device
_Avoid_: host, server, box, endpoint

**Tools page**:
The run app's view where a person adds, edits and removes devices, switches each on for this project, tests it and sets its secrets; it also lists the shared tools that runner.toml names.
_Said_: Tools page
_On screen_: Tools
_In code_: toolsHTML, GET/POST /tools, devices.page
_Avoid_: devices page, tools screen, settings

**New version popup**:
The popup over a run page or Home's page when the run serves another page than the open one (Refresh loads it), or when newer code waits for a person to restart the run. Later hides it for that page in this tab. A page never reloads by itself.
_Said_: the new version popup
_On screen_: A new version of this page is ready; Refresh; Later
_In code_: newsDraw, pageNews, PAGE_PRINT, snapshot 'page', 'restart_needed'
_Avoid_: banner, toast, update bar

**Changed-code restart**:
A run from a source checkout (a clone with .git beside agent_runner/) with auto_upgrade on restarts itself as soon as main's agent_runner code has changed, and holds new merges until then. It keeps its slots and adopts its sessions.
_Said_: restart on changed code
_In code_: watch_code, code_restart, hold_merge
_Avoid_: hot reload

**Ask file**:
The short steps, what to see and pictures or videos, and for a DECIDE its `options` (answer buttons), an agent writes for what it asks of a person, shown in Needs you; for a control session's filed question, also what explains it (the text above the DECIDE line, its session and project, copied pictures); gone once the item is answered
_Said_: asks file
_On screen_: the steps, what to see and pictures or videos on a Needs you card and popup
_In code_: asks/ID.json, asks.ask_file, clear_ask, ASKS_PROMPT, keep_explained
_Avoid_: notes file, ask json, brief

**Split hold**:
The time before which a task too big for one session does not start, set by `plan add` so its author can file the parts first; it ends early once a first part is filed, the task is split or brought under the size, or it is moved to the top.
_Said_: picked up as you were making it
_On screen_: waits to be split, starts in 4 min if it is not
_In code_: SPLIT_HOLD, split-by, split_left, split_waits, splitting
_Avoid_: grace period, cooldown

**Input**:
a text, link or secret a Needs you item asks the person to enter, sent with Done as its answer; a secret is kept only in the task's own secrets file
_Said_: what the person has to give
_On screen_: one field on a Needs you item
_In code_: inputs, need_give, input_wrong, asks/ID.env
_Avoid_: form field, parameter

**Claude login**:
the claude.ai sign-in on a machine that its Claude Code sessions run on; it ends after a while and a person renews it
_Said_: Claude login, log in again
_On screen_: Claude login, login banner under the top bar, Log in again button
_In code_: watch.claude_login, watch.LOGIN_CMD, claude_login (snapshot), vitals.login_banner, session_frame.login_argv, login_hold.LoginHold
_Avoid_: credentials, token, auth

**Trusted network**:
a network whose devices open Runner Home or a run's page without its key
_Said_: trusted networks, my tailnet
_On screen_: Networks with no key
_In code_: trusted_networks, trust.py, home trust
_Avoid_: whitelist, allowlist

**Tailnet address**:
The https address of a run's page on Tailscale, so a browser there gets the microphone for Talk
_Said_: https on Tailscale
_On screen_: run page link in status and the run log, Run page over https setting
_In code_: page_https.py, [run] web_https, serve/<port>.json
_Avoid_: serve URL, public link

**Example project**:
A tiny app with a plan that ships with agent-runner; one command makes a copy with a remote on the same machine, to try a run on
_Said_: example repo, demo
_On screen_: The example project
_In code_: demo.py, agent-runner demo, examples/hello, is_demo
_Avoid_: sample repo, sandbox, playground

**Mic test**:
A sheet from Talk settings that runs four tries of the mic, one press each, with no message sent: words with the sound setting left as it is, words with it set to play and record, words right after a silent sound, and sound level only with no recognizer; Copy mic test copies a report of the tries so far
_Said_: mic check
_On screen_: Mic test…, Copy mic test
_In code_: micTest, MT, SHEETS.mictest
_Avoid_: diagnostic

**Walkthrough**:
Short cards, one at a time, that point at the parts of a run on the example project's page and in the terminal UI; skipped or not and where the person is are kept
_Said_: walkthrough, tour
_On screen_: Walkthrough
_In code_: walkStep, walkDraw, 065-walk.js, walk.py, WALK_STEPS
_Avoid_: tutorial, onboarding, tour guide

**Page fold**:
a row on the run page that opens in place to show more, and closes again
_Said_: a fold
_On screen_: a chevron row
_In code_: foldIn, .foldin, data-askfold
_Avoid_: accordion, expander

**File split**:
A task the run queues by itself to divide a file that ready tasks wait for while slots are free
_Said_: split the big file
_On screen_: Split busy files
_In code_: file_split.py, queue_file_split, [run] split_files, EV_FILE_SPLIT
_Avoid_: split (for a task), refactor task

**Last screen**:
The screen a chat's session was last drawn with, kept in the page for the last 12 chats (in memory, gone on reload). A switch to that chat shows it at once, dimmed, until the session's first whole draw; a chat not seen in this page shows its latest messages in its place.
_Said_: kept screen
_On screen_: (no wording: the dimmed screen under a thin moving line)
_In code_: keptPut, feedKeep, feedBack, feedDrawn, standHTML, .feedline, .feedstand
_Avoid_: cache, snapshot, preview, thumbnail

**Title switcher**:
What a chat's title in the top bar opens, with a down chevron: the chats in the sidebar's order, each with its last line, a dot when it needs your reply and a check on the open one. Rename this chat is at its foot.
_Said_: switcher
_On screen_: Chats; Rename this chat
_In code_: SHEETS.chats, chatsSheet, chatLast
_Avoid_: chat picker, dropdown, tab bar, title menu

**No-push policy**:
A project setting under which the runner pushes nothing and git refuses a push in every session it starts, in any repository.
_Said_: no-push policy
_On screen_: Never push
_In code_: no_push, [git] no_push, AGENT_RUNNER_NO_PUSH
_Avoid_: push lock, offline mode

**Session history**:
A chat's or slot's whole transcript as data for the run page, in pages: the person's messages, the agent's words, each tool call folded with its result, and notes. Unlike the Session feed, it reaches back to the transcript's start. A chat's session scrolls back through it, over the live screen (The session).
_Said_: history
_On screen_: the history a chat's or slot's session scrolls back to, over the live screen
_In code_: session_history.py, history, /history/NAME, 021-history.logic.js, 092-history.js, HX, #feedpast
_Avoid_: scrollback, log

**Pull to refresh**:
On touch, pulling the main view or the sidebar down past its top: a small spinner follows the finger, and letting go far enough does what Refresh does.
_Said_: pull down past the top to refresh
_On screen_: Let go to refresh; Refreshing
_In code_: pullPane, pullStart, pullMove, pullEnd, PULL_AT
_Avoid_: swipe to refresh, hot reload

**Plan search**:
The Plan view's field that finds tasks by words or a task id, open, parked and done ones, and shows the matches in place of the groups while it holds text.
_Said_: a search in plan
_On screen_: Find a task
_In code_: plan_search, planFound, planq
_Avoid_: task filter, lookup

**Device page**:
The web page a device or a runner.toml tool can have, opened from the Tools page; a start command saved with it makes the runner able to start and stop what serves it, and to say whether it is running, stopped or failed.
_Said_: web page of a device
_On screen_: Web page to open, Use, Start, Stop, Open NAME in Tools
_In code_: device_page.py, page_state, run device start|stop, toolPage, toolKey, needDevices, need_pages, need_tools
_Avoid_: app, service, server

**Settings bar**:
The bar at the foot of the run page's Settings that holds the changes made to its rows and not yet saved, with Undo and Save; after a Save it says what was saved, with Undo and a close.
_Said_: save and undo button
_On screen_: N changes not saved, Save, Undo
_In code_: #setbar, setBarDraw, settings_save
_Avoid_: save bar, footer

**Jump button**:
The round button, with its own fill and border, that floats over the lines just above a chat's message box and glides a scrolled-back session to its live end. It shows once the reader is well above the end, with a dot when there is something new.
_Said_: jump to bottom
_On screen_: Jump to bottom
_In code_: .pastjump, pastDown
_Avoid_: scroll button, pill

**Page-only process**:
A background process of one project that serves its whole run page while no run is up, so chats and the plan work there; it starts no work, and ends when a run starts, on `agent-runner page-only stop`, or after some time with no page open where Runner Home can start it again; a run's stop hands its page to one
_Said_: open the page without starting the run
_On screen_: opening the run page…
_In code_: page_only.serve, page_only.open_page, page_only.hand_over, web.start_web(only=True)
_Avoid_: page server, idle run, light run

**Recorded**:
The way of Talk where the run's machine turns a clip the page recorded into words; the other way is the browser's own recognition.
_Said_: have both as an option
_On screen_: Recorded
_In code_: recorded.py, /recorded, Recorder, 172-talk.js
_Avoid_: STT, transcription

**Last chat**:
The shortcut on a run page's Home that opens the chat with the newest activity, pinned or not
_Said_: last chat
_On screen_: Last chat
_In code_: homeChips
_Avoid_: recent chat, previous chat

**Open mic**:
The mic's stream kept open on Talk with Speech to words: Recorded, so a press listens at once. It is listened to only from a press: with no listen on, its sound is dropped at once, and nothing from before a press is kept or sent.
_Said_: start listening while on that page; not listen 24/7, but only when the mic is pressed
_On screen_: the mic is open, not listening
_In code_: recLook, recAhead, recRing, .mic.open
_Avoid_: hot mic, always listening

**Until check**:
Something a blocked task waits on that the machine can read by itself: a version, a login, a tool or a named command. It passes, has not passed yet, or cannot run
_On screen_: Until checks
_In code_: until.py, [run.checks]
_Avoid_: poll, condition, probe

**Sent response**:
What a person answered to a Needs you item with no chat opened for it, kept with its question so a chat about it can still be started; it goes once that chat starts
_Said_: responses, what I answered
_On screen_: a dim row in the Chats list's Quiet group, with "new" until it is opened once
_In code_: sent_responses, keep_response, response_chat, snapshot responses, responseRows, responseHTML
_Avoid_: reply record, answer log

**History view**:
The run page's History view, opened from the NAV row after Plan: one scroll with a Find in history field, Landed (the newest landed tasks, each opening in place to what it is, its text, What changed, Report a problem and Chat last), Releases (past ones, newest 20; with Manage releases off the section goes), and the Run log with its Since my last look and Since yesterday chips.
_Said_: History
_On screen_: History
_In code_: historyHTML, histRow, past_releases, NAV
_Avoid_: Activity, archive, timeline

**Question card**:
The question a chat's last answer ends on, when it has options to pick from, shown as a card above the message box; it goes once the person answers. When the question was filed as a Needs you item, the card and that item are one question: an option picked on the card, or an answer under Needs you, closes both. The person can minimize it to one line and show it again (its − and ^), which answers nothing. It hides while the person is scrolled up, and is back at the bottom
_Said_: answer buttons in a chat
_On screen_: the question and one button per option above a chat's message box, a Chat about this button last among them, a Minimize question − at its top right, minimized one line with a Show question ^, or the Sending row with Undo while an answer waits
_In code_: chat_question.ask, chat_question.needs, /live's ask, questionCard, questionHTML, questionMinimize, questionScroll, QN.away, QN.gone, QN.min, .qcard, question_answer
_Avoid_: poll, prompt card, quick replies

**Held task**:
A queued task or release that keeps its place and is skipped until the person ends the hold
_Said_: hold
_On screen_: Held: a run won't start it
_In code_: plan hold, plan unhold, row_hold.py, held
_Avoid_: paused task, parked, shelved

**Marked question**:
A question card's question while the person writes about it: what they send is an ordinary message about it, never its answer, and its card comes back after the send
_Said_: chat about this
_On screen_: Chat about this, not your answer, with the question, above the message box
_In code_: questionMark, questionMarkHTML, QN.mark, .qabout
_Avoid_: quoted question, reply context

**Removed cut**:
An automatic release the person removed, or the Next release row removed: no release is cut then, and only tasks landed after the removal count to the next; it can be restored
_Said_: skip this release
_On screen_: that cut is skipped, and the count starts from zero
_In code_: release_moves.removed, release_moves.drop_next, EV_CUT_REMOVED, next-release
_Avoid_: cancelled release, skipped release

**Hint**:
The bubble that names a control with only an icon or a sign (no letter or digit): its aria-label, else its title, shown over or under it while a mouse hovers it or a finger holds it
_Said_: hint
_In code_: iconWords, hintSpot, .hint
_Avoid_: tooltip, popover, help text

**Row menu**:
The three dots on a Plan queue row, and the icons they bring in on the row to hold it, move it to the top or remove it
_Said_: the menu on the row
_On screen_: ⋯ on a Plan queue row: Hold or End the hold, Wait for…, To the top, Remove with Undo
_In code_: rowMenu, menuRows, menu_hold, menu_unhold, menu_top, menu_remove, menu_restore, queuemenu
_Avoid_: context menu, kebab menu

**Cancel**:
Stop the run of a running task without removing it: its agent is stopped, its work is kept on wip/ID and the task is parked, so no agent starts it until the person unparks it; not while the task lands
_Said_: cancel instead of take back
_On screen_: Cancel on a running slot; Yes, cancel
_In code_: cancel.py, task_cancel, plan cancel, cancels, keep_work
_Avoid_: take back, abort, kill

**Tool button**:
A shared tool's own button on the Tools page: a label and a command that runs once and ends, with an optional question asked first; any tool or device can have any number
_Said_: custom button
_On screen_: the button's own label
_In code_: tool_buttons.py, [[run.tools.<name>.buttons]], op press
_Avoid_: action, macro, shortcut

**Row grip**:
The thin handle on a Plan queue row that moves it: dragged by a mouse, or with arrow up and down while it has the focus
_Said_: the grip
_On screen_: six dots at the left of a Plan queue row: Move ID: drag, or arrow up and down
_In code_: rowGrip, gripRows, gripMove, gripDraw, data-grip
_Avoid_: drag handle, gripper

**Row lift**:
On touch, a Plan queue row that a finger holds still until it lifts, so the finger then moves it like the grip; the touch is the row's until the finger lifts
_Said_: hold and drag
_On screen_: hold a Plan queue row until it lifts, then drag
_In code_: liftRow, liftUp, liftMove, liftEnd, LF
_Avoid_: long press, drag mode

**Run-off banner**:
A bar under the top bar that says The run is not running, with one Start the run button, while no run is up and the page-only process serves the run page. It shows on every view but Home and Status (whose Start card and Run card say it), and on those two only while a chat is open; not on All projects, and only from a fresh snapshot.
_Said_: the not running bar
_On screen_: The run is not running
_In code_: runOff, offDraw, #runoff
_Avoid_: stopped notice, off bar

**Start card**:
The card at the top of the run page's Home while no run is up: Not running, one Start the run button, then Starting the run… while it starts, or Not started: why with Retry and Discard in its place after a failure. It goes once the run is up, and the view stays as it was.
_Said_: start card
_On screen_: Not running, Start the run
_In code_: homeStart, runStarts
_Avoid_: run-off banner, start bar, off page, Start run card

**Closed-page bar**:
The bar under the top bar that replaces the lost-connection notice when Runner Home answers that nothing serves the open run page (its page-only process ended while the page slept): with a Reload button, which starts the page-only process by a page load with Home's key and keeps what is typed. A fetch starts nothing; the bar goes once the page answers again.
_Said_: the run page is closed
_On screen_: The run page is closed
_In code_: lostDraw, askClosed
_Avoid_: offline bar, lost banner, reconnect notice

**Run wait**:
What a queued task's Plan row says, on the run page and in the TUI, while no run is up and nothing else keeps the task; it starts once a run does
_Said_: waits for the run
_On screen_: Waits for the run to start
_In code_: RUN_WAIT, wait_for_run, waits_run, addedWaits
_Avoid_: offline task, not running task, pending start

**Removal check**:
What a task's finish looks for when its work deletes or renames a file, test, setting or command: the places that still name it.
_Said_: what still names it
_On screen_: still named
_In code_: stale.py, refusal, Gone, Mention
_Avoid_: dead-reference scan, stale check

**Feedback round**:
One resumed session of a task on its open pull request's branch, to answer review comments, red CI, a conflict or a person's answer, ending with a push and replies
_Said_: PR feedback
_On screen_: resumes for pull request #N
_In code_: pr_feedback, round
_Avoid_: retry, review cycle

**Audit**:
A task that looks at what changed since the last one for what is stale, dead or wasted, writes its findings to a file and asks on one pick sheet; queued by hand, or by an idle run once enough tasks have landed.
_Said_: auto audit
_On screen_: Audit by itself; Audit model
_In code_: audit.py, audit_fix, (audit), auto_audit, audit_tokens
_Avoid_: cleanup run, sweep, health check

**Fix limit**:
What an audit's own diff may change without a question: its findings file, its own task, and dead references in docs, the glossary and lessons. `done` and the merge refuse a diff past it.
_Said_: fix limit
_On screen_: the audit's fix limit
_In code_: audit_fix
_Avoid_: guard, whitelist

**Split task**:
a task divided into parts that are tasks of their own; it is done once its parts are; dropping it leaves its open parts in the plan
_Said_: split task
_On screen_: Split: 2 of 4 parts landed
_In code_: (split into …), split_parts, split_ask, state 'split'
_Avoid_: parent task, umbrella task

**Pull request state**:
What an open pull request of PR mode waits for, in words: a review, a fix, or the person's merge.
_Said_: waits for review, changes asked, CI red
_On screen_: waits for review; changes asked; CI red; conflicts with the main branch; approved, waits to be merged
_In code_: pr_rows.state_of
_Avoid_: PR status, merge state

**Wait for…**:
Setting which tasks a queued task waits for: exactly the ones picked, or none
_Said_: wait for, what it waits for
_On screen_: Wait for…; ⋯ on a Plan queue row: Wait for…; What should B456 wait for?; Done, Cancel
_In code_: plan edit --wait-for, plan_wait.py, set_waits, waitHTML, waitRows, data-waitset
_Avoid_: block on, depend on

**Parts list**:
Under a split task's card in the Plan queue, every part of it in the order it runs: the landed ones ticked, then the rest, each with its own state
_Said_: subtasks in a dropdown
_On screen_: Parts, in the order they run
_In code_: split.list, partRows, partsBar, partCard, 079-plan-parts
_Avoid_: subtasks dropdown

**Settings tab**:
One of the two views of Settings, Project (runner.toml, for everyone) or This device (runner.local.toml); every row edits the file of the tab in view
_Said_: Project and This device tabs
_On screen_: Project, This device
_In code_: setTab, settingsTab, SET_TABS, .settabs
_Avoid_: scope switch, home picker

**Working branch**:
The branch finished work is applied to and tasks start from; found by itself when not set.
_Said_: working branch
_On screen_: Working branch
_In code_: [git] master_branch, isBranch, branchSays, branchHTML
_Avoid_: main branch, master branch

**Review page**:
A pitch's page, where a person reads each waiting change's diff and why, asks about it, asks for a better way, and approves it
_Said_: review page
_On screen_: The diff / You asked / Answer it
_In code_: pitch.page_html, review.diff_html, pitch ask, pitch better
_Avoid_: code review, PR page

**Lazyrunner**:
The run page's keyboard-first layout: the sidebar as numbered panels on the left, the view on the right, keys to move; the same panels as the Standard layout
_Said_: lazyrunner, keyboard mode
_On screen_: Layout: Lazyrunner
_In code_: 189-lazy.js, 189-lazy.css, LAZY_PANELS, :root.lazy
_Avoid_: TUI mode, lazy view

**Lesson**:
Something a project's agents learned about some files, shown to the next task that works on them
_Said_: lesson
_On screen_: Lessons on these files
_In code_: lessons.py, plan lesson
_Avoid_: tip, hint

**Default login**:
The first login of a provider, used when a model name pins none

**Spare worktree**:
A slot's worktree kept, unused, after the slot count went down, so the next new slot reuses it instead of building one
_Said_: keep the worktrees of removed slots
_On screen_: kept as a spare
_In code_: slot_prep.spares, .spare-sN
_Avoid_: cached slot

**Question row**:
Several questions a chat asks at once, one question card each, side by side to swipe through, with a count
_Said_: horizontal scrolling if there's multiple questions
_On screen_: 1 of 3
_In code_: questionRowHTML, .qmany, .qswipe
_Avoid_: carousel, slider
