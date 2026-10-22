"""The one entry point: `./run <command>` (or `agent-runner <command>`)."""
from __future__ import annotations

import sys

USAGE = """usage: run <command> [args]

    plan [...]                 the task list as a tool (`run plan help`)
    plan add PREFIX TEXT [@ WHERE]
                               add a todo: `plan add B "…"` = next number (starts at once);
                               `plan add B646 "…"` = subtask B646a (runs after B646)
    done ID "MSG" [--blocked WHY [--after X,Y]]
                               test gate, tick or block, commit, push the task branch
    run [N|once] [--mode d|p] [--dry-run]
                               the unattended runner (`run run --help`)
    stop                       let the running tasks finish and merge, start nothing new
    --version                  print the version

Run it from anywhere inside the repository whose tasks it works on (or set AGENT_RUNNER_REPO).
Configuration: runner.toml at the repository's root, or the file AGENT_RUNNER_CONFIG names; see the README.
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
    print(USAGE, file=sys.stderr if cmd not in ('-h', '--help', 'help') else sys.stdout)
    return 0 if cmd in ('-h', '--help', 'help') else 2
