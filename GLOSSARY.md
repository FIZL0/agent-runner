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
The control session the run opens beside it when it starts, and keeps.
_Avoid_: control 1, main session, first control session

**Runner feed**:
The lean session in the Claude apps that reposts what lands and what needs the person, and hands any other ask to a control session.
_Avoid_: feed session, bot

**Board**:
The hidden session that holds the runner feed; with no runner feed there is none, and the run page shows what lands (`attach board` opens agent-runner ui).
_Avoid_: dashboard, status window

**Remote**:
Running the run's sessions on Remote Control, so the person steers from claude.ai/code or the Claude apps; the git remote that merges go to is the **push remote**.
_Avoid_: cloud, online, headless, remote (for the push remote)

**Needs you**:
The list of what waits on the person: concepts waiting for a pick, and tasks blocked on a CONFIRM (a check by hand), a DECIDE (a question or a choice) or a BLOCKED (access or a fix only a person can make).
_Avoid_: inbox, waiting list, blocked

**Shelve**:
Setting a Needs you item aside: the task stays blocked but leaves the list until unshelved.
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
A control session with no window, as every run starts them (attach cN shows it); what it prints goes to its log
_Said_: control session in the background
_On screen_: c1 is up in a hidden terminal
_In code_: hidden_control, control_new_hidden, controlN.log
_Avoid_: headless control, background control

**Context warning**:
A slot session's context grew past the set size; the exit line and since say how big and which files filled it
_Said_: context budget
_On screen_: B32 peaked 168k (over 150k): runner.py 61k, test_runner.py 22k
_In code_: context_warn, context_over, EV_CONTEXT, cost.filled
_Avoid_: context limit, hard limit

**Fresh c1**:
c1 starting a new session instead of resuming the kept one, on a new run when the kept one last stood over the context warning; a restart always resumes
_Said_: fresh control session
_On screen_: c1 starts a fresh session
_In code_: control_sid(new_run=), CONTROL_FRESH, run_restart, control_bloated, --new-run
_Avoid_: reset c1, new c1

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
The run queuing a release task by itself, after a set number of tasks have landed or when it goes idle with landed work
_Said_: auto release
_On screen_: queued V<n> (auto_release: 10 landed / idle)
_In code_: [run] auto_release, autorelease.auto_release, autorelease.landed_since_release, plan.add_release, EV_AUTO_RELEASE
_Avoid_: auto publish, auto version

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
The run page published on claude.ai by c1, read-only, for when the machine running the run cannot be reached
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
A session's own transcript on the Run page: the agent's words, the person's, and each tool step with its output, newest last
_Said_: feed
_On screen_: feed
_In code_: ui_model.feed, feed_entries, /feed/NAME
_Avoid_: log, terminal

**Quick ask**:
One of the Status chat's ready-made questions to c1, sent with one key or tap
_Said_: quick asks, presets
_On screen_: since last look, since yesterday, what needs me, usage
_In code_: QUICK_ASKS, quick_ask
_Avoid_: preset, shortcut

**Terminal view**:
A session's own terminal on the Run page, through ttyd (attach NAME); with no ttyd, how to install it; on Windows, the session feed only
_Said_: terminal
_On screen_: terminal
_In code_: terminal_mode, terminal_fallback
_Avoid_: console

**Terminal-style page**:
The Run page on the web drawn like the terminal UI (numbered panels, keys), beside the run app; the run app's 'Terminal view' switch opens it and its 'App view' goes back
_Said_: terminal-style web page
_On screen_: Terminal view (the switch), App view (back)
_In code_: web_term.html, /term, term_html, [ui] web = "terminal"
_Avoid_: old page, classic view

**Direct edit**:
Changing a queued task's fields (what, kind, priority, files, after) on the Run page, each field with its own key, written straight to the plan
_Said_: direct edit
_On screen_: direct edit
_In code_: editHTML, plan_change, plan_add
_Avoid_: form, inline edit

**Chat edit**:
Saying in your own words what to change about a task, or what a new task is, for c1 to write into the plan
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
The run app's one page on the run itself: what needs the person, the run with its slots and controls, usage, what landed lately, the release, then the run log
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

**Quiet chat**:
A chat that needs no reply and has had nothing said in it for `[ui] chat_quiet`: grayed, at the bottom of Chats, until something is said
_Said_: quiet chats
_On screen_: Quiet
_In code_: chat_quiet, chatGroups
_Avoid_: archived chat, old chat, stale chat

**Device override**:
A setting this machine's runner.local.toml sets over the project's runner.toml
_Said_: This device
_On screen_: This device, Reset
_In code_: save_local_setting, setting_device, setting_reset
_Avoid_: local config, user setting

**Run app**:
The chat app a run serves on the web for a phone or a desktop: Home, a thread per session, and the Plan, over the same Run page
_Said_: run app
_On screen_: run page link (in `status` and the run log)
_In code_: web_page.html, web.py, [run] web
_Avoid_: web page, dashboard, web UI

**Run controls**:
The buttons and keys that change the run itself from the run page or agent-runner ui: slots, pause, force, stop, and stopping one slot's task
_Said_: run controls
_On screen_: Run controls
_In code_: RUN_CONTROLS, run_control, controls(), controlReq
_Avoid_: run buttons, admin controls

**Concept chat**:
A new control session about one concept, told which concept and its page, to change that page and build nothing until a plain go
_Said_: chat about it
_On screen_: N chat about it; New chat
_In code_: concept_chat, concept_chat_text
_Avoid_: concept session

**Parked task**:
A queued task at level later, in the plan's Parked section: a run never starts it until a person unparks it, which moves it to Follow-ups.
_Said_: parked
_On screen_: Parked: a run won't start it
_In code_: state 'parked', unpark, parkedLast, queueGroups
_Avoid_: later task, on hold

**Attach**:
Put this terminal on a session's own terminal, to watch it and type into it, until Ctrl-b d leaves it running
_Said_: attach
_On screen_: attach s2; Back: Ctrl-b d
_In code_: cmd_attach, attach_session, session_socket, slotN.sock, controlN.sock
_Avoid_: open (that is Open a slot), connect

**Run picker**:
What bare agent-runner shows at a terminal: one row per run on this device, the current folder's project first, to pick one
_Said_: pick a run
_On screen_: agent-runner · pick a run
_In code_: cmds.cmd_pick, pick_run, picker_rows
_Avoid_: run menu, chooser

**Launcher**:
The screen after the run picker: the picked run's status and run page link, and keys to open the page, open its terminal UI or copy the link
_Said_: launcher menu
_On screen_: w open the run page · t terminal UI · c copy the link
_In code_: cmds.launch, launcher_text
_Avoid_: action menu

**Follow an upgrade**:
When the run restarts on a newer agent-runner, an open TUI starts again on it where it was and an open run page reloads
_Said_: follow an upgrade of the run
_On screen_: (no wording: the TUI starts again, the run page reloads)
_In code_: follow_upgrade, followVersion, newer_version, PLACE_ENV, snapshot 'version'
_Avoid_: hot reload, auto-refresh

**Run view**:
The run's log followed live in any terminal, taking the runner keys typed there; Ctrl-C leaves it and the run keeps going
_Said_: attach, the runner's pane
_On screen_: runner keys: type one here and press Enter
_In code_: run_view.py, run_view, view_key, keys_help(view=True), attach run
_Avoid_: runner pane, runner window, console

**Model role**:
A type of work the runner picks a model for: a task's session, the spec review, a fix, docs edits, control sessions, the feed
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
_In code_: `(alone)` tag, plan.alone, plan.alone_ids, plan add/edit --alone, Held.alone, sched.clash
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
_In code_: vitals.py, Vitals, /devices, /device
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
Removing only what the runner made and no longer needs (ended sessions' temp folders, worktrees merged into the main branch, wip/ branches the person ticks), after listing it first; ended sessions' temp folders also go by themselves on Home's regular walk, while worktrees and wip/ branches wait for the person
_Said_: clean up, free space
_On screen_: Clean; Remove ticked
_In code_: clean, clean_plan, /vitals/clean, auto_clean
_Avoid_: purge, wipe, prune

**Peer**:
Another machine's Runner Home that this Home shows under Devices, listed by its link or found on Tailscale
_Said_: other machine, other Home
_On screen_: Devices
_In code_: peers, peer add, peer_links
_Avoid_: node, remote host

**Device alert**:
A warning Device Vitals raises about a machine (too hot, disk nearly full), told to the person as a needs-you line
_Said_: device alert
_On screen_: needs you: box: CPU at 95°C (over 90°C)
_In code_: EV_DEVICE, vitals.push_alert
_Avoid_: drift

**Talk**:
The run app's spoken chat: the person taps a big mic and speaks, its own control session answers in short spoken sentences, and the reply is read aloud; a chat box under it takes typing.
_Said_: talk mode, by voice, hands-free
_On screen_: Talk
_In code_: talk (web action), talk_ask, TALK_BRIEF, talkSend
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
Inside tmux, the selected session shown as itself in a tmux pane beside the terminal UI's panels, where the person types to it, selects and copies; Ctrl-f makes it full-screen between the top and bottom bars
_Said_: the right pane, the real Claude Code session inside the TUI
_On screen_: (no wording: the session itself, beside the panels)
_In code_: SidePane, RunPage.sync, want_side
_Avoid_: chat view, side window

**Harness loop**:
agent-runner's own agent loop, which runs a task or fix session on a model from a provider other than claude
_Said_: our own agent loop, the loop engine
_On screen_: harness loop
_In code_: harness.mjs, slots.Harness, config.harness_model
_Avoid_: loop engine, Pi loop

**Provider login**:
the sign-in or key a model provider other than claude needs before the harness loop can run a session on it
_Said_: login, run login
_On screen_: run login
_In code_: login.py, login.login_of, login.park_unlogged, harness.mjs --login
_Avoid_: auth, credentials, token

**Chat order**:
The order of the run app's Chats list and which chats are pinned to its top, kept by the run so every page shows the same list
_Said_: drag to reorder chats, pin chats
_On screen_: Pin this chat / Unpin this chat
_In code_: chat_order, chat_list, chatMove, chat_order.json
_Avoid_: chat sort, favourites

**Pick link**:
A plain link on a concept page's option or a pick sheet that answers the run with that option when tapped, through a one-use code made for that item
_Said_: option button
_On screen_: Go with B / Answer the run with these picks
_In code_: web.pick, web.pick_links, pick-links, /pick
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
The one row at the end of the queue that says how the next release stands: how close an auto release is, or what the queued release task waits for
_Said_: next release
_On screen_: Next release · auto at 10 landed: 6/10 / V5 Release · waits for 24 open ahead / building
_In code_: ui_model.release_row, ui_model.pin_release, status.release_line, planQueue
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
