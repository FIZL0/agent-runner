# Changelog

Semantic versioning; what counts as breaking is in [docs/SETUP.md](docs/SETUP.md#versions).

## 0.6.4 (2026-10-21)

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
