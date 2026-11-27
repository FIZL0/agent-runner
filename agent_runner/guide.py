"""`agent-runner guide`: how an agent session a person starts in a runner's repo should work with the runner.

Sessions the runner starts get a brief; the ones a person starts in the repo get nothing, and they edit TODO.md
by hand, commit plan changes, do a slot's work themselves on a branch and ask whether to merge it. The same text
is printed by `agent-runner guide` (for any agent: point AGENTS.md at it) and kept installed as a Claude Code
skill (`[run] install_skill`), which costs a session one line until it applies. A run rewrites the skill when
its text changes, so it always matches the installed runner. The runner's own sessions run lean (no user
settings, no Skill tool) and the text tells one that sees it anyway to follow its brief.

C2: material only one branch of a session needs (concepts, answering Needs you, the take flow) is in TOPICS,
printed by `agent-runner guide <topic>`; GUIDE and the control brief carry a pointer that names when to read it.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from agent_runner.guide_text import *  # noqa: F401,F403 (C59)

def grill_mode(c=None) -> str:
    """`[run] grill`: 'ask' (the default, and for anything it does not know), 'big', or 'off' (false too)."""
    try:
        if c is None:
            from agent_runner.config import C as c
        v = c.run.get('grill', 'ask')
    except (Exception, SystemExit):
        return 'ask'
    if v is False:
        return 'off'
    v = str(v).strip().lower()
    return v if v in GRILL_MODES else 'ask'


def grill_fit(text: str, cmd: str, c=None) -> str:
    """The control brief with its grilling line fitted to `[run] grill`: as is, widened to big asks, or gone."""
    line = GRILL.format(cmd=cmd)
    mode = grill_mode(c)
    if mode == 'off':
        return text.replace(line + '\n', '').replace(line, '')
    if mode == 'big':
        return text.replace(line, GRILL_BIG.format(cmd=cmd))
    return text


def topic(name: str, cmd: str = 'agent-runner', needs: str = 'Needs you') -> str:
    """One TOPICS page, filled in."""
    return TOPICS[name].format(cmd=cmd, needs=needs)


def cmd_guide(rest: list[str]) -> int:
    """`guide`: GUIDE; `guide <topic>`: that page, naming the runner as typed and this repo's Needs you heading."""
    if not rest:
        print(GUIDE, end='')
        return 0
    if rest[0] not in TOPICS and rest[0] not in CONTROL_TOPIC_NAMES:
        print(f'guide: no topic {rest[0]!r}; topics: {", ".join([*TOPICS, *CONTROL_TOPIC_NAMES])}', file=sys.stderr)
        return 2
    from agent_runner import plan as P
    from agent_runner.config import RUNNER
    needs = P.needs_cfg()['heading']
    from agent_runner.control_harness import in_harness_chat
    chat = in_harness_chat()  # F406f
    if rest[0] in TOPICS:
        page = topic(rest[0], RUNNER, needs)
        print(harness_fit(page, RUNNER) if chat else page, end='')
        return 0
    from agent_runner.config import cfg
    try:
        c = cfg()
    except (Exception, SystemExit):  # outside a repository: the runner as typed, the defaults
        c = None
    # B98: the control brief names [run] command (B93), so its pages do too
    cmd = c.command if c else RUNNER
    page = HARNESS_WATCH.format(cmd=cmd) if chat and rest[0] == 'watch' else control_topic(rest[0], cmd, needs, c)
    print(harness_fit(page, cmd) if chat else page, end='')
    return 0


GUIDE = """\
# Working in a repo that agent-runner works

agent-runner works through plan/TODO.md unattended: each task gets its own agent, git worktree and branch
(`task/<ID>`); the runner tests the branch, merges it, pushes, and ticks the task. In a session a person
started, you work like a control session: you shape the queue, the runner's agents do the tasks. (With
AGENT_RUNNER_SLOT set you are one of the runner's agents: follow your brief, not this.)

1. **Change the task list through `agent-runner plan`**: it keeps the format the runner, its merges and its
   claims read, and in the main checkout it commits itself (`plan: <command>`). TODO.md and DONE.md are its
   output: leave them to it, unedited and uncommitted by hand.
   - queue: `agent-runner plan add <KIND> "what, why, how to check" --files a.py,src/b/** [--after ID]`
     (`plan kinds` lists the KIND letters; `--pri critical|high|normal|low|later` for follow-ups). Name the exact files, the test file too (`tests/test_menu.py`, not `tests/**`): a task waits for any other on
     its files. """ + OWN_FILES + ' ' + SPLIT_FILES + """
   - correct: `plan edit ID "corrected text"` (it replaces the description and its notes, so no stale
     instruction stays beside the new one); `plan note ID "..."` only adds detail. `plan restore ID` undoes a
     mistaken tick or drop; `agent-runner plan help` lists the rest
   - **concepts**: a person asking to see a concept or options ("show me a concept first") gets the page from
     you, in this session, not a K task, filed right after with `plan concept "<title>" --page <URL>`: read
     `agent-runner guide concepts` first
   - **Needs you**: a queued concept or a task blocked on a person, or the person's reply to one: read
     `agent-runner guide needs` first
   - **grilling** ("grill me", "poke holes", "stress-test it"): rounds of questions before you queue: read
     `agent-runner guide grill` first
2. **Queue work instead of doing it**, unless the person asks you to do it yourself now. A running runner
   starts a queued task within a minute. Good tasks name their `--files` (tasks on the same files never
   run at once) and say how to check the result. **Keep the main checkout clean**: uncommitted edits there
   hold every merge, and may be moved to a `wip/main-checkout-*` branch out of your sight. **Doing it now**
   (asked, or urgent): `agent-runner take` gives you a worktree of your own; read `agent-runner guide take`.
3. **Leave the runner's branches to the runner**: it alone merges, rebases, pushes or deletes `task/*` and
   `wip/*`, and ticks tasks, after its test gate. A `wip/<ID>` branch is a parked attempt (`.runner/run.log`
   says why): the task stays open and starts again by itself in the next run, or in this one once its line is
   edited, so `plan note` what the next attempt should do differently.
4. **To unstick a task**, read why it stopped (`agent-runner plan ID`, its journal, `.runner/run.log`),
   then `plan note` what to do differently, or `plan unblock ID "what changed"`. An edited task goes back
   in the pool, even in the same run.
5. **Is it running, and what next?** `tail -20 .runner/run.log` (the `[run] notes` dir), and
   `agent-runner run --dry-run 3` for what would start and why the rest wait. The run is the person's: start
   or stop it only when they ask (`agent-runner stop` lets running tasks finish first).
   To act once the run is done, wait in the background until run.log's last line is `run idle`:
   `timeout 4h bash -c 'until tail -n1 .runner/run.log | grep -q "run idle"; do sleep 60; done'`. That poll
   ends; `tail -f run.log | grep -m1 'run idle'` does not (tail dies only when it next writes, and an idle run
   writes nothing more).
6. **Commands you can read and undo.** The main checkout is where the runner lands merges, and its
   worktrees and `task/*` branches hold agents' unmerged work. """ + SAFE_SHELL + """ Leave the runner's
   home (`~/runs/<repo>/`) and `.runner/` alone, and ask the person before anything that deletes.

""" + SETTINGS.format(cmd='agent-runner') + """
`agent-runner help order` explains what runs when; `agent-runner --help` lists every command.
"""

# B27: a reply that answers an item under Needs you without naming it ({needs} is its heading)
CONTROL_ANSWER = ('work out which item it answers, run `{cmd} plan confirm|change|shelve ID` as the needs guide '
                  'says, and say in a line what it did. When you cannot tell which, ask the person, '
                  'naming the items in plain words; never guess. Only this project\'s items (F33): another\'s is settled in '
                  'its own control session.')

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
    uncommitted edits, nor mid-merge, nor in PR mode (F419: no commit on main). A line for the run log, or ''. Off with `[run] rules_pointer = false`."""
    if c.pr or not c.run['rules_pointer'] or not (f := rules_file(c)):
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


# C59: the control brief and its pages live in guide_control.py; import them from here.
from agent_runner.guide_topics import *  # noqa: E402,F401,F403
from agent_runner.guide_control import *  # noqa: E402,F401,F403
