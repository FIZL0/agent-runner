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

**Release alone**:
A release task that waits for every task ahead of it and runs with nothing beside it; off by default, when a release starts like any other task
_Said_: release runs alone
_On screen_: a release runs alone
_In code_: [plan] release_alone, plan.release_alone, sched.release_alone
_Avoid_: exclusive release

**Run view**:
The run's log followed live in any terminal, taking the runner keys typed there; Ctrl-C leaves it and the run keeps going
_Said_: attach, the runner's pane
_On screen_: runner keys: type one here and press Enter
_In code_: run_view.py, run_view, view_key, keys_help(view=True), attach run
_Avoid_: runner pane, runner window, console
