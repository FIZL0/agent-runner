# Changelog

Semantic versioning; what counts as breaking is in [docs/SETUP.md](docs/SETUP.md#versions).

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
