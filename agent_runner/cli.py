"""The one entry point: `./run <command>` (or `agent-runner <command>`)."""
from __future__ import annotations

import os
import sys

USAGE = """agent-runner: AI agents work through plan/TODO.md, one task each, in parallel.

What you type
    agent-runner setup                make this repo ready: back up uncommitted work, runner.toml, a first plan
    agent-runner                      start the run in the background and get the prompt back
    agent-runner --attach             the same, then watch its pane here (Ctrl-b d: back to the background)
    agent-runner attach [s2]          see the run's pane, or slot 2's
    agent-runner control              a control session here: ask it "status?", to pause, add slots, file a task
    agent-runner control --new        another one beside the run; prints its claude.ai/code link
    agent-runner status               is a run up, each slot's task, merges lately, usage (-n 20: log too)
    agent-runner since [2h|yesterday] what landed, started or got stuck since you last looked (--follow: live)
    agent-runner pause                start no new tasks, stay up (--off: go on)
    agent-runner stop                 let running tasks finish, start no new ones (--force: now)
    agent-runner slots +1             one slot more (-1 fewer, 4: exactly four)
    agent-runner wizard               walk through the hand steps a blocked task waits on, then confirm it
    agent-runner guide                how an agent you start in this repo should work with the runner
    agent-runner plan                 every task id, one line each
    agent-runner plan add B "Fix the menu flicker"
                                      new task B647 (B: the kind of work, see `plan kinds`)
    agent-runner plan B646            one task's full text
    agent-runner wip                  your main-checkout edits a merge moved aside (show|restore|drop NAME)
    agent-runner upgrade              update agent-runner; a run that is up restarts on it

Mostly for agents (you can run these too)
    agent-runner take B646            do B646 in your own session beside a run: prints its worktree and prompt
    agent-runner take B646 --merge    after `done` there: the runner tests and merges it (--drop: give it back)
    agent-runner resume B646          continue B646's last session, cut off by a dropped network or a reboot
    agent-runner done B646 "Halve the sheet's memory" [--blocked "why"]
    agent-runner plan block B12 --after B646 "why"
    agent-runner plan move B12 top    B12 to the top: the next free agent takes it
    agent-runner plan next            the task that starts next
    agent-runner plan help            every plan command
    agent-runner key z                any key the runner's pane takes (? lists them)
    agent-runner home [slots|plan]    where this project's runner files are: for scripts
    agent-runner context              what every session loads (rules, CLAUDE.md, AGENTS.md) and what to move out
    agent-runner cost                 where the workers' tokens go, by kind of tool call (last 7 days)
    agent-runner run once             one task in this terminal, then stop (run 3: three agents)
    agent-runner run --dry-run 3      what 3 agents would start now; starts nothing
    agent-runner force                start tasks past the usage caps (--off: caps hold)
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

    agent-runner plan add B "Use the sheet" --after B646 --files src/menu.rs
        -> a fresh task with `| after: B646 | files: src/menu.rs`: it waits for B646, and stays off
           the files a running or finished-unmerged task touches.

    agent-runner plan block B12 --after B646 "needs the new sheet"
        -> B12 is blocked until B646 is done, then reopens by itself.

    A heading saying "in this order" or "one at a time"
        -> one task from that section at a time.

Choose what goes first:

    agent-runner plan move B12 top            first in line
    agent-runner plan move B12 after B646     right behind B646
    agent-runner plan add B "Fix it" @ after B646
    agent-runner plan add B "Fix it" @ bottom    last in the leading section
    agent-runner plan add B "Check it" --pri low
        -> a follow-up: critical (top: it breaks or blocks work), normal (an agent's default) and low go
           after the queued sections, in ### Follow-ups; later is parked in ### Parked.
    agent-runner plan kinds                   what each id letter means ([plan] kinds)

Never started: blocked [~] tasks, ### Stretch and ### Parked, a task with open subtasks, a task that already failed this run,
and a finished task waiting to merge. Nor a task that names a file a running task names.

    agent-runner run --dry-run 3      what 3 free agents would start now, and why the rest wait
"""


def skill() -> None:
    """Keep the guide installed as a Claude Code skill from every command a person runs, not only `run`: anyone
    who has typed agent-runner on this machine has it. Off with `[run] install_skill = false`."""
    try:
        from agent_runner.config import cfg
        if not cfg().run['install_skill']:
            return
    except (Exception, SystemExit):  # outside a repo, or a config the command itself will complain about
        pass
    from agent_runner.guide import install
    if said := install():
        print(said, file=sys.stderr)


def adopt_folder() -> bool:
    """A runner project with no git yet (a downloaded copy of examples/hello): make it a repo with one commit,
    so the bare command can start the run. Only a folder that holds runner.toml or plan/TODO.md."""
    import subprocess
    from pathlib import Path
    if Path('.git').exists() or not (Path('runner.toml').is_file() or Path('plan/TODO.md').is_file()):
        return False
    print('agent-runner: no git repository here: making this folder one, with its files as the first commit',
          file=sys.stderr)
    for cmd in (['init', '-q', '-b', 'main'], ['add', '-A'], ['commit', '-qm', 'Start: the files as they came']):
        r = subprocess.run(['git', *cmd], capture_output=True, text=True)
        if r.returncode:
            print(f'agent-runner: git {cmd[0]} failed: {(r.stderr or r.stdout).strip()}', file=sys.stderr)
            return False
    return True


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd, rest = (argv[0], argv[1:]) if argv else ('', [])
    if cmd != 'merge-plan' and not os.environ.get('AGENT_RUNNER_SLOT'):  # not git's driver, not a slot's agent
        skill()
    if cmd in ('--version', '-V', 'version'):
        from agent_runner import __version__
        print(f'agent-runner {__version__}')
        return 0
    if cmd == 'plan':
        from agent_runner import plan
        if os.path.basename(sys.argv[0]) == 'agent-runner':  # installed: name it as the user types it
            plan.PROG = 'agent-runner plan'
        return plan.main(rest)
    if cmd == 'merge-plan' and len(rest) == 3:  # git's merge driver for the task list (plan.install_driver)
        from agent_runner import plan
        return plan.merge_file(*rest)
    if cmd == 'done':
        from agent_runner import done
        return done.main(rest)
    if cmd == 'setup':  # F49
        from agent_runner import setup
        return setup.main(rest)
    if cmd == 'run':
        from agent_runner import runner
        return runner.cmd_run(rest)
    if not argv:  # bare: the run in the background (outside a repository: the usage, as before)
        from agent_runner.config import toplevel
        try:
            toplevel()
        except SystemExit as e:
            if not adopt_folder():
                print(f'{e}\nagent-runner --help: every command', file=sys.stderr)
                return 2
        from agent_runner import runner
        return runner.cmd_background(rest)
    if cmd == '--attach':  # bare, then attach: the run's pane in this terminal
        from agent_runner import runner
        return runner.cmd_background_attach(rest)
    if cmd == 'attach':
        from agent_runner import runner
        return runner.cmd_attach(rest)
    if cmd == 'control':
        from agent_runner import runner
        return runner.cmd_control(rest)
    if cmd == 'context':
        from agent_runner import context
        return context.main(rest)
    if cmd == 'cost':
        from agent_runner import cost
        return cost.main(rest)
    if cmd == 'home':  # one answer for every script: never rebuild these paths by hand
        from agent_runner.config import cfg
        c = cfg()
        what = {'': c.home, 'slots': c.slots_dir, 'plan': c.plan_dir}.get(rest[0] if rest else '')
        if what is None or len(rest) > 1:
            print('agent-runner home [slots|plan]', file=sys.stderr)
            return 2
        print(what)
        return 0
    if cmd == 'resume':
        from agent_runner import runner
        return runner.cmd_resume(rest)
    if cmd == 'wizard':  # F17
        from agent_runner import runner
        return runner.cmd_wizard(rest)
    if cmd == 'take':
        from agent_runner import runner
        return runner.cmd_take(rest)
    if cmd == 'wip':  # F23
        from agent_runner import runner
        return runner.cmd_wip(rest)
    if cmd == 'stop':
        from agent_runner import runner
        return runner.cmd_stop(rest)
    if cmd == 'status':
        from agent_runner import runner
        return runner.cmd_status(rest)
    if cmd == 'since':
        from agent_runner import runner
        return runner.cmd_since(rest)
    if cmd in ('pause', 'force', 'slots', 'key'):
        from agent_runner import runner
        return runner.cmd_key(rest, f'{runner.RUNNER} {cmd}')
    if cmd == 'upgrade':  # B49
        from agent_runner import runner
        return runner.cmd_upgrade(rest)
    if cmd == 'guide':
        from agent_runner.guide import GUIDE
        print(GUIDE, end='')
        return 0
    if cmd == 'help' and rest[:1] == ['order']:
        print(ORDER)
        return 0
    print(USAGE, file=sys.stderr if cmd not in ('-h', '--help', 'help') else sys.stdout)
    return 0 if cmd in ('-h', '--help', 'help') else 2
