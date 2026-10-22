"""The one entry point: `./run <command>` (or `agent-runner <command>`)."""
from __future__ import annotations

import sys

USAGE = """usage: run <command> [args]

    plan [...]                 the task list as a tool (`run plan help`)
    plan add PREFIX TEXT [@ WHERE]
                               add a todo: `plan add B "…"` = next number (may run alongside others);
                               `plan add B646 "…"` = subtask B646a (never alongside B646)
    help order                 what runs when, and how to make one task wait for another
    done ID "MSG" [--blocked WHY [--after X,Y]]
                               test gate, tick or block, commit, push the task branch
    run [N|once] [--mode d|p] [--dry-run]
                               the unattended runner (`run run --help`)
    stop                       let the running tasks finish and merge, start nothing new
    --version                  print the version

Run it from anywhere inside the repository whose tasks it works on (or set AGENT_RUNNER_REPO).
Configuration: runner.toml at the repository's root, or the file AGENT_RUNNER_CONFIG names; see the README.
"""

ORDER = """What runs when

Each free slot reads plan/TODO.md from the top and starts the first task it is allowed to. So the order of the
lines is the order of the work. `plan add` puts a new task at the top; `plan add … @ after ID` or `plan move ID
after ID` places it.

Several slots run at once. A task that must wait for another needs one of these, or it starts as soon as a slot is free:

  subtask     plan add A12 "…"           -> A12a, A12b, …. One family (A12, A12a, A12b) never runs two tasks at
                                            once, so they go one at a time, top to bottom.
  after       plan block B3 --after A12 "why"
                                         -> B3 is [~] until A12 is done; the run reopens it by itself.
  ordered     a section heading that starts with "Next" or says "in this order": one task from it at a time.
              Mode d only; mode p ignores it.
  mention     a line naming a running task's id waits while that task runs. Only while it runs: a line saying
              "follows A12" still starts if A12 hasn't started yet. Use a subtask or --after instead.

Never started: [~] blocked, ### Stretch, a parent with open subtasks, a task already tried this run, a task whose
branch is finished and waiting to merge, and in mode d a task naming a file a running task names.

Modes (runner.toml [run] mode, or --mode): p = strict top-to-bottom, files may overlap; d = different files.
`run run --dry-run N` shows what N free slots would start, and why the rest wait.
"""


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd, rest = (argv[0], argv[1:]) if argv else ('', [])
    if cmd in ('--version', '-V', 'version'):
        from agent_runner import __version__
        print(f'agent-runner {__version__}')
        return 0
    if cmd == 'plan':
        from agent_runner import plan
        return plan.main(rest)
    if cmd == 'done':
        from agent_runner import done
        return done.main(rest)
    if cmd == 'run':
        from agent_runner import runner
        return runner.cmd_run(rest)
    if cmd == 'stop':
        from agent_runner import runner
        return runner.cmd_stop(rest)
    if cmd == 'help' and rest[:1] == ['order']:
        print(ORDER)
        return 0
    print(USAGE, file=sys.stderr if cmd not in ('-h', '--help', 'help') else sys.stdout)
    return 0 if cmd in ('-h', '--help', 'help') else 2
