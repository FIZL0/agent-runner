# Changelog

Semantic versioning; what counts as breaking is in [docs/SETUP.md](docs/SETUP.md#versions).

## Unreleased

- Windows: a Windows Terminal tab per slot (`wt`), or a console window per slot when Windows Terminal
  isn't installed, through a slot shim that keeps each session's pid in `.runner/slotN.live`. The run
  lock, process checks, the Stop hook's timer and the end of a session work there too, from the
  standard library only. `[run] links` fall back to junctions and hard links without Developer Mode.
- `[run] mux` / `--mux tmux|wt|console|none` picks the terminal. The default is unchanged: tmux on
  Linux and macOS.

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
