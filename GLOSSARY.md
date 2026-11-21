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
The terminal pane that shows the runner feed's lines, with no agent behind it.
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
A control session with no window, started by a run with no tmux pane to open it in; what it prints goes to its log
_Said_: control session without tmux
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

**Fold**:
Before a merge, a follow-up the branch filed that the target branch already got from another slot goes into that task as a note instead of becoming a second task.
_Said_: dedupe follow-ups
_On screen_: folded Y2 into Y1
_In code_: fold_doubles, join.renumber_doubles
_Avoid_: dedupe, collapse, squash
