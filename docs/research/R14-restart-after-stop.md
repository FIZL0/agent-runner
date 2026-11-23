# R14: what started opentennis's run 4 s after a stop

Question: run A logged `run stopped` at 2026-11-23 01:31:39 and a run came up at 01:31:43-44 (output in
`context/notes/background.out`, the `cmd_background` file). What started it?

## Verdict

Not automatic. The code has no path that starts a run on its own after a stop, and the machine has no
Home service, unit or other watcher that could. The evidence fits a person starting it from a terminal with
bare `agent-runner` (the picker, `cmd_pick`), but nothing on disk records who or what called
`cmd_background`, so this is the likeliest cause, not a proven one.

## What was ruled out

- **Upgrade self-restart** (`restart_if_upgraded`): it `execv`s in the same process (no `run stopped`, no
  new `background.out`), is skipped while `stopping()`, and would have come up on 0.61.0. The new run said
  it was 0.59.0.
- **Home's start button** (`home.py` ACTIONS `start` → bare `agent-runner`): Home is not installed on this
  machine (no `~/.config/agent-runner/home.log`, no systemd user unit, no `home serve` process).
- **systemd / cron**: no user unit runs agent-runner (`systemctl --user list-units`, `~/.config/systemd/user`).
- **Agent transcripts**: none, per the task.

## What can start a run

Only `cmd_background`: reached from bare `agent-runner` without a terminal (`cli.py:263`), `--attach`
(`cmds.py:673`), the picker when the chosen row is not up (`cmds.py:1391`), and Home's start. All four write
the same `background.out`, so the file cannot tell them apart.

## Why the picker fits

- Bash history shows bare `agent-runner` typed over and over, and a picker (`agent-runner`, pid 361671, pts9)
  is open in the `ifb` tmux pane now, picking other projects' runs from there.
- `cmd_pick` reads its rows once (`picker_rows`, before the loop). A row that was not up when drawn and gets
  Enter starts the run at once, whatever happened since: the keypress, not the stop, is the trigger, and a
  person pressing Enter 4 s after seeing the run stop would match.

## Why B137 saw a stop outliving its run

The new run's log at 01:31:44 says `control: c1 already runs (pid 1631487)` and `run page: cannot serve on
port 8770 (Address already in use)`: the old run's control session and page were still alive 5 s after `run
stopped`. The new run adopted c1, so the stop asked for run A met a live run B that had inherited A's control
session. That is a second, separate gap: `run stopped` is logged before the run's children are gone.

## Filed

- A follow-up to record who started a run (source and caller), so this question has an answer next time.
- A follow-up on a new run adopting the old run's control session and meeting its port 5 s after `run stopped`.
