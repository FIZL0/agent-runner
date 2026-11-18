"""`agent-runner guide`: how an agent session a person starts in a runner's repo should work with the runner.

Sessions the runner starts get a brief; the ones a person starts in the repo get nothing, and they edit TODO.md
by hand, commit plan changes, do a slot's work themselves on a branch and ask whether to merge it. The same text
is printed by `agent-runner guide` (for any agent: point AGENTS.md at it) and kept installed as a Claude Code
skill (`[run] install_skill`), which costs a session one line until it applies. A run rewrites the skill when
its text changes, so it always matches the installed runner. The runner's own sessions run lean (no user
settings, no Skill tool) and the text tells one that sees it anyway to follow its brief.
"""
from __future__ import annotations

import os
from pathlib import Path

GUIDE = """\
# Working in a repo that agent-runner works

agent-runner works through plan/TODO.md unattended: each task gets its own agent, git worktree and branch
(`task/<ID>`); the runner tests the branch, merges it, pushes, and ticks the task. In a session a person
started, you are the coordinator: you shape the queue, the runner's agents do the tasks. (With
AGENT_RUNNER_SLOT set you are one of the runner's agents: follow your brief, not this.)

1. **Change the task list only through `agent-runner plan`**, never by editing TODO.md or DONE.md. The
   commands keep the format the runner, its merges and its claims read, and in the main checkout they
   commit themselves (`plan: <command>`): do not commit plan files by hand.
   - queue: `agent-runner plan add <KIND> "what, why, how to check" --files a.py,src/b/** [--after ID]`
     (`plan kinds` lists the KIND letters; `--pri critical|normal|low|later` for follow-ups)
   - change: `plan note ID "..."`, `plan move ID top|after X`, `plan block ID [--after X] "why"`,
     `plan unblock ID`, `plan drop ID "why"`
   - read: `agent-runner plan`, `plan ID`, `plan next`, `plan claims`, `plan help`
2. **Queue work instead of doing it**, unless the person asks you to do it yourself now. A running runner
   starts a queued task within a minute. Good tasks name their `--files` (tasks on the same files never
   run at once) and say how to check the result.
3. **Leave the runner's branches alone**: never merge, rebase, push or delete `task/*` or `wip/*`, and never
   tick a task by hand. The runner merges after its test gate; a `wip/<ID>` branch was left for a person,
   so tell the person and point at `.runner/run.log`.
4. **To unstick a task**, read why it stopped (`agent-runner plan ID`, its journal, `.runner/run.log`),
   then `plan note` what to do differently, or `plan unblock ID "what changed"`. An edited task goes back
   in the pool, even in the same run.
5. **Is it running, and what next?** `tail -20 .runner/run.log` (the `[run] notes` dir), and
   `agent-runner run --dry-run 3` for what would start and why the rest wait. Do not start or stop a run
   unless the person asks: it runs in their tmux. `agent-runner stop` lets running tasks finish first.
6. **Work you did yourself** in the main checkout on a task id: `agent-runner done ID "message"` runs the
   test gate, ticks the task and commits.

`agent-runner help order` explains what runs when; `agent-runner --help` lists every command.
"""

SKILL = """\
---
name: agent-runner
description: Use in a session a person started (not a runner slot) in a git repo that agent-runner works (it has plan/TODO.md, runner.toml or .runner/) before you add, change, check or unblock tasks, edit TODO.md, merge task/ or wip/ branches, or take on work the runner could queue.
---
"""


def skill_file() -> Path:
    return Path(os.environ.get('CLAUDE_CONFIG_DIR') or Path.home() / '.claude') / 'skills' / 'agent-runner' / 'SKILL.md'


def install() -> str:
    """Write the skill when it is missing or its text changed. A line for the run log, or '' when there was
    nothing to do (or no ~/.claude: Claude Code is not used here)."""
    f = skill_file()
    text = SKILL + '\n' + GUIDE
    if not f.parent.parent.parent.is_dir():
        return ''
    try:
        if f.is_file() and f.read_text(encoding='utf-8') == text:
            return ''
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding='utf-8')
    except OSError:
        return ''
    return f'installed the agent-runner skill ({f}): sessions a person starts here learn to use the runner'
