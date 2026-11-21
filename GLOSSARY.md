# agent-runner

agent-runner works a repo's plan unattended: it gives each task an agent of its own, tests the result and merges
it, while a person steers from a control session. These are the words the person, the briefs and the code use
for it; when two words exist for one thing, the first is the one to use and the others are under _Avoid_.
(Format after mattpocock/skills domain-modeling, MIT.)

## Language

### Work

**Task**:
One line of the plan (plan/TODO.md) with an id: a kind letter and a number, like `F48`.
_Avoid_: ticket, issue, todo, job, item (an item is a line under Needs you)

**Kind**:
The letter that starts a task's id and says what sort of work it is: B bug, F feature, T tests and tooling, D docs, R research, C cleanup, K concept.
_Avoid_: type, category, label

**Concept**:
A task of kind K, or a request to see options before anything is built: its outcome is a page of two or three options and a recommendation, and the build waits for the person's pick.
_Avoid_: mock-up task, design task, proposal

**Gate**:
The project's test command, which must pass before a task is ticked and again on the merge before it lands.
_Avoid_: CI, checks, test suite (when the gate is meant)

**Take**:
Doing a task now, outside the queue, in a worktree and branch of its own that the run then leaves alone.
_Avoid_: grab, do it locally, work in the main checkout

**Claim**:
A run's or a take's hold on a task, visible to every other run on the repo, so nobody else starts it.
_Avoid_: lock (a lock is the run's own one-at-a-time guard), lease, reservation

### The run

**Run**:
One working of the plan by agent-runner, from start to stop: its slots, its merges and c1 beside it.
_Avoid_: session (a session is one agent conversation), job, daemon

**Slot**:
One of the run's places for a task: a worktree (`s1`, `s2`, …) and the agent session working a task in it.
_Avoid_: worker, lane, agent (when the place is meant)

**Merge worktree**:
The run's own checkout where a finished task is merged and gated before the main branch moves, so the main checkout only ever gets tested work.
_Avoid_: merge checkout, staging, merge slot

**Fixer**:
A short agent session the run starts at merge time: a fix session when a merge conflicts, a repair session when the gate fails on the merge.
_Avoid_: master, merge agent, resolver

**Notes dir**:
The folder in the main checkout (`[run] notes`, `.runner/` by default) where the run keeps its logs, ledger, wizards and pick sheets.
_Avoid_: log dir, state dir, `.runner` (when the setting is meant)

### Talking to the person

**Control session**:
A Claude Code session in the main checkout through which the person runs the run: they ask for status, steer it and shape the queue; the run's own agents do the tasks.
_Avoid_: control window, coordinator, chat

**c1**:
The control session the run opens beside it when it starts, kept across runs and never closed for being idle.
_Avoid_: control 1, the main session, the first control session

**Runner feed**:
The lean session shown in the Claude apps as "<repo> · runner" that reposts what lands and what needs the person, and hands any other ask to a new control session.
_Avoid_: feed session, Haiku session, the bot

**Board**:
The terminal pane that shows the same lines as the runner feed (what lands, what needs the person) without an agent behind it.
_Avoid_: dashboard, status window

**Remote**:
Running the run's sessions on Remote Control (`[run] remote`), so the person steers from claude.ai/code or the Claude apps instead of the terminal.
_Avoid_: cloud, online, headless. The git remote that merges are pushed to is the **push remote** (`[git] push`), never just "remote".

**Needs you**:
The list of what waits on the person, oldest first: concepts waiting for a pick, and tasks blocked on a person, each one a CONFIRM (check something by hand), a DECIDE (answer a question or a choice) or a BLOCKED (access, a login or a fix only a person can make). The person sees each in plain words, never the label.
_Avoid_: inbox, waiting list, blocked (alone), the queue

**Shelve**:
Putting a Needs you item aside: the task stays blocked but leaves the list until it is unshelved.
_Avoid_: park (a parked attempt is a `wip/` branch), snooze, defer, drop (drop removes the task)
