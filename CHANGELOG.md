# Changelog

Semantic versioning; what counts as breaking is in [docs/SETUP.md](docs/SETUP.md#versions).

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
