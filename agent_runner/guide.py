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

# One text for both audiences: the runner's own sessions get it in their prompt (they load no skills), the
# sessions a person starts get it in GUIDE.
SAFE_SHELL = ('Change files with your file-editing tool, never with `sed -i`, `perl -i`, or a script fed through a '
              'heredoc or `python -c`, and give the shell one plain command at a time, not a chain of `;`/`&&`/pipes '
              'mixing edits, redirects and nested quotes: a command your safety check cannot read stops for a human '
              'to decode, and in an unattended session nobody is there, so it is refused and the minutes are lost. '
              'Delete only paths you name in full (never `rm -rf` on a variable or a glob), and never `git reset '
              '--hard`, `git clean`, `git checkout -- .`, `git stash` or `git push --force`: they destroy work you '
              'cannot get back.')

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
   run at once) and say how to check the result. **Never edit files in the main checkout**: uncommitted
   edits there hold every merge, and may be moved to a `wip/main-checkout-*` branch out of your sight.
   Asked to do it now? `agent-runner take` (6) gives you a worktree of your own.
3. **Leave the runner's branches alone**: never merge, rebase, push or delete `task/*` or `wip/*`, and never
   tick a task by hand. The runner merges after its test gate. A `wip/<ID>` branch is a parked attempt
   (`.runner/run.log` says why): the task stays open and starts again by itself in the next run, or in this
   one once its line is edited, so `plan note` what the next attempt should do differently.
4. **To unstick a task**, read why it stopped (`agent-runner plan ID`, its journal, `.runner/run.log`),
   then `plan note` what to do differently, or `plan unblock ID "what changed"`. An edited task goes back
   in the pool, even in the same run.
5. **Is it running, and what next?** `tail -20 .runner/run.log` (the `[run] notes` dir), and
   `agent-runner run --dry-run 3` for what would start and why the rest wait. Do not start or stop a run
   unless the person asks: it runs in their tmux. `agent-runner stop` lets running tasks finish first.
   To act once the run is done, wait in the background until run.log's last line is `run idle`:
   `timeout 4h bash -c 'until tail -n1 .runner/run.log | grep -q "run idle"; do sleep 60; done'`. Never
   `tail -f run.log | grep -m1 'run idle'`: grep exits on the match, but tail only dies when it next
   writes, and an idle run writes nothing more, so the wait never ends.
6. **To do one task yourself now** (the person asks, or it is urgent), with or without a run going:
   `agent-runner take ID` makes it a worktree and branch `task/ID` of its own (a run then leaves the task
   and its files alone) and prints the prompt for whoever does it. Work not queued yet:
   `agent-runner take "what, why, how to check" --kind K --files a.py` queues it and takes it in one step.
   Already started editing in the main checkout? Add `--here`: your uncommitted edits move into the new
   worktree and the main checkout is left clean. Hand that prompt to a subagent with the
   worktree as its working directory, or work there yourself; it finishes with `agent-runner done ID "msg"`
   there, then `agent-runner take ID --merge` (the runner tests and merges it, or the run that is up does).
   `take ID --drop` gives it back untouched. Several takes on tasks with different files can go at once.
7. **No dangerous or unreadable commands.** The main checkout is where the runner lands merges, and its
   worktrees and `task/*` branches hold agents' unmerged work. """ + SAFE_SHELL + """ Leave the runner's
   home (`~/runs/<repo>/`) and `.runner/` alone, and ask the person before anything that deletes.

`agent-runner help order` explains what runs when; `agent-runner --help` lists every command.
"""

CONTROL = """\
# agent-runner control session

You are a control session of agent-runner, in the main checkout of {repo}. A person (at this terminal, or in
claude.ai/code and the Claude apps) runs the run through you: you report on it, steer it and shape its queue.
The runner's own agents do the tasks, each in a worktree of its own. **Never edit code or plan files here**:
uncommitted edits in the main checkout hold every merge. Answer in a few short lines: the person may be on a
phone.

What the person asks, and what you run (`{cmd}` is the runner):
- "status?", "what's running?": `{cmd} status`, and say it back short: each slot's task and minutes, what
  waits to merge, what merged, blocked or was parked lately, usage.
- pause / go on: `{cmd} pause` / `{cmd} pause --off`. More or fewer agents: `{cmd} slots +1`, `slots -1`,
  `slots 4`. Past the usage caps: `{cmd} force` (`--off`). Stop: `{cmd} stop` (running tasks finish first),
  `{cmd} stop --force` (now; they resume next run), `{cmd} stop --undo`. Start a run when none is up: `{cmd}`.
- "add a task", "fix X", "can someone…": queue it with `{cmd} plan add <KIND> "what, why, how to check"
  --files a.py,dir/**` (`{cmd} plan kinds` lists KIND letters; `--pri critical` only when it blocks work).
  Change the queue with `{cmd} plan note|move|block|unblock|drop`; read it with `{cmd} plan`, `{cmd} plan ID`.
- "do it now", "just fix it": `{cmd} take "what, why, how to check" --kind K --files a.py` (or `{cmd} take ID`
  for a queued task) makes a worktree of its own and prints the prompt: hand that prompt to a subagent with
  the worktree as its working directory, or work there yourself, then `{cmd} take ID --merge`. Never in
  this checkout.
- Why did a task stop? `{cmd} plan ID`, the run log `{log}`, then `{cmd} plan note ID "do X instead"` or
  `{cmd} plan unblock ID "what changed"`.

Keep the person posted without being asked: at the start of the session, start the Monitor tool on
`tail -n 0 -F {log} | grep --line-buffered -E '{watch}'` and, for each line it brings, post one short line
(task id, what happened). Say nothing else for it.

""" + SAFE_SHELL + """
"""

CONTROL_WATCH = r': merged, |not merged, parked|LEFT FOR A HUMAN|parked for a person|looks stalled|run idle|run stopped'

CONTROL_START = ("Start the run-log watch your control brief describes, then tell me the run's status in two or "
                 "three short lines (`{cmd} status`), and wait for me.")


SKILL = """\
---
name: agent-runner
description: Use in a session a person started (not a runner slot) in a git repo that agent-runner works (it has plan/TODO.md, runner.toml or .runner/) before you add, change, check or unblock tasks, edit TODO.md, merge task/ or wip/ branches, or take on work the runner could queue.
---
"""


POINTER = ('Tasks: this repo is worked by agent-runner. Use the agent-runner skill (or run `{cmd} guide`): queue '
           'work with `{cmd} plan add`, never edit the plan\'s TODO.md by hand, never merge task/* or wip/* branches. '
           'Asked to do something now? Use `{cmd} take "what" --kind K` (a worktree of your own; `--here` brings '
           'edits already made along); never edit the main checkout.')
OLD_POINTERS = [('Tasks: this repo is worked by agent-runner. Use the agent-runner skill (or run `{cmd} guide`): '
                 'queue work with `{cmd} plan add`, never edit the plan\'s TODO.md by hand, never merge task/* or '
                 'wip/* branches.')]  # rewritten to POINTER where a run finds them


def rules_file(c) -> Path | None:
    """The repo's rules file every session loads: `[run] rules`, else AGENTS.md or CLAUDE.md; None when it has
    none (the runner never creates one)."""
    names = [c.run['rules']] if c.run['rules'] else ['AGENTS.md', 'CLAUDE.md']
    return next((c.root / n for n in names if (c.root / n).is_file()), None)


def point_rules(c, git) -> str:
    """Add POINTER to the rules file once, committed on its own, so every session in the repo (on a machine
    without the skill, or one that would not pick it) learns to work with the runner. Never into a file with
    uncommitted edits, nor mid-merge. A line for the run log, or ''. Off with `[run] rules_pointer = false`."""
    if not c.run['rules_pointer'] or not (f := rules_file(c)):
        return ''
    text = f.read_text(encoding='utf-8')
    rel = f.relative_to(c.root).as_posix()
    cmd = c.run['command'] or 'agent-runner'  # what everyone types, never this machine's path to a clone
    new = POINTER.format(cmd=cmd)
    old = next((o for p in OLD_POINTERS if (o := p.format(cmd=cmd)) in text), None)
    if new in text or (old is None and (f'{cmd} guide' in text or 'agent-runner guide' in text)) or \
            git('status', '--porcelain', '--', rel).stdout.strip() or \
            not git('rev-parse', '-q', '--verify', 'MERGE_HEAD').returncode:
        return ''
    f.write_text(text.replace(old, new) if old else
                 text + ('' if text.endswith('\n') or not text else '\n') + '\n' + new + '\n', encoding='utf-8')
    what = 'updated the agent-runner line in' if old else 'added a line to'
    if git('commit', '-q', '-m', f'{rel}: point sessions at the agent-runner skill', '--', rel).returncode:
        git('checkout', '--', rel)
        return ''
    return f'{what} {rel} pointing every session at the agent-runner skill (committed)'


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
