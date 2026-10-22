"""The one entry point: `./run <command>` (or `agent-runner <command>`)."""
from __future__ import annotations

import sys

USAGE = """agent-runner: AI agents work through plan/TODO.md, one task each, in parallel.

Run the agents
    agent-runner run once             try it: one task, then stop
    agent-runner run                  keep going with the slots runner.toml sets, until you stop it
    agent-runner run 3                3 agents at once
    agent-runner run --dry-run 3      show what 3 agents would start now, start nothing
    agent-runner stop                 let running tasks finish, start no new ones

See and change the task list
    agent-runner plan                 every task id, one line each
    agent-runner plan next            the task that starts next
    agent-runner plan B646            one task's full text
    agent-runner plan add B "Fix the menu flicker"
                                      new task B647: may run beside anything
    agent-runner plan add B646 "Bake the letter sheet"
                                      new subtask B646a: never runs beside B646
    agent-runner plan block B12 --after B646 "needs the new sheet"
                                      B12 waits, and reopens by itself once B646 is done
    agent-runner plan move B12 top    B12 to the top: the next free agent takes it
    agent-runner plan help            every plan command

Finish a task (what an agent runs at the end)
    agent-runner done B646 "Halve the sheet's memory"
    agent-runner done B646 "Halved part of it" --blocked "needs a browser to measure"

More
    agent-runner help order           what runs when, and how to make one task wait for another
    agent-runner run --help           every runner option
    agent-runner --version

Run it anywhere inside the repo. Settings: runner.toml in the repo root (or AGENT_RUNNER_CONFIG).
"""

ORDER = """What runs when

Each free agent takes the first task from the top of plan/TODO.md that it's allowed to start.
Several agents run at once, so a new task starts as soon as an agent is free, unless it is told to wait.

Make a task wait for another (writing "after B646" in its text is not enough):

    agent-runner plan add B646 "Bake the letter sheet"
        -> B646a. B646, B646a, B646b never run at the same time, so they go one by one, top to bottom.

    agent-runner plan block B12 --after B646 "needs the new sheet"
        -> B12 is blocked until B646 is done, then reopens by itself.

    A heading starting with "Next" or saying "in this order"
        -> one task from that section at a time (mode d only; mode p ignores it).

Choose what goes first:

    agent-runner plan move B12 top            first in line
    agent-runner plan move B12 after B646     right behind B646
    agent-runner plan add B "Fix it" @ after B646
    agent-runner plan add B "Fix it" @ bottom    last in the leading section (an agent's default)

Never started: blocked [~] tasks, ### Stretch, a task with open subtasks, a task that already failed this run,
and a finished task waiting to merge. In mode d, also a task that names a file a running task names.

Modes (runner.toml mode, or --mode): p = strictly top to bottom; d = only tasks on different files at once.

    agent-runner run --dry-run 3      what 3 free agents would start now, and why the rest wait
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
