"""`./run run`: keep N agent sessions working through the task list, for as long as the work lasts.

Most of a long project is small, checkable steps that need no human in the loop: they need the backlog,
the tests and a commit. This is the loop that does that. It picks the next task nobody is on, opens a git
worktree and a hidden terminal for it (a pseudo-terminal; on Windows a ConPTY pseudo-console, or a hidden console with no ConPTY), and
starts an agent session with the task's brief already pasted into the first turn. It waits for the session to finish, merges and tests the branch, pushes it, and starts the
next task.

    ./run run once            one task, then stop (the way to try it the first time)
    ./run run                 [run] slots agents (3), in the foreground of this terminal
    ./run run 5               5 agents
    ./run run 1               one agent, in a worktree like any count
    ./run run --dry-run 4     print what 4 free slots would start now, and start nothing
    ./run stop                finish what is running, start nothing new, then exit (or type s + Enter
                              in the run view, `attach`; ? + Enter there lists every key)
    ./run stop --force        end the sessions now (each resumes in the next run), then exit
    (every form but `once` stays up when the work runs out: it logs `run idle` and waits for more)

docs/REFERENCE.md describes each mechanism. In short:

* **picking** (`tasks`, `pick`) goes down TODO.md in order and skips
  - blocked tasks and split parents (a parent parked as wip/<ID> goes first: its subtasks are skipped, B185),
  - tasks whose `| after: X, Y` names a task not done yet,
  - the Stretch and Parked sections, anything tried this run (until its line is edited), and branches waiting to be merged,
  - a task parked twice (wip/<ID>, wip/<ID>-2): the run blocks it on a person instead (`block_parked`).
  - a task whose two runs in a row end with no commits, its plan text unchanged: the run blocks it `DECIDE:` (`no_commits`, B774).

  Parts of a split task run together only when their `files:` do not meet and neither waits for the other
  (a part naming none waits), and never beside the task they are parts of. An ordered section runs one task at a time. Two tasks never run on the same
  files: a line's `| files:` and, for a task running, the files it has touched; a finished one waiting to merge
  holds only the files it changed, and once in a merge under way not even those: the task starts on top of that
  merge (F198, `stack.py`). A whole-directory glob (`dir/**`) is a guess, not a lock: it meets only
  another such glob, so a task naming a file under it waits only for the files the glob's task has touched.
* **one worktree per slot**, kept warm between tasks, with `[run] links` symlinked in;
* **an idle stop** (the Stop hook): a finished session is ended once its transcript is quiet;
* **a cut-off session resumes**: one ended by an API error or a usage limit (or, at startup, mid-turn) is resumed
  in its slot;
* **a stall watchdog**: belled and logged, with the session to attach to;
* **merges in a merge worktree**: tested before the shared branch moves, so the main checkout never
  holds an untested merge and nobody's edits are stashed;
* **a fix session per conflict** that a line join cannot do;
* **blocks reopen themselves** when what they waited on lands;
* **a tested merge is pushed**;
* **it stays up**: out of work, it logs `run idle` and keeps reading TODO.md (`retry_reopened` puts a
  tried task a human unblocked back in the pool). Scripts watch run.log for `run idle`, not the exit.

Internal modes (used by the sessions it starts, not by you):
    --stop-hook            Stop hook: arm the idle timer for the session that is stopping
    --stop-waiter P T N S  the detached timer itself
    --slot-shim JOB        run one hidden slot's session (a pty; Windows: a pseudo-console, or a hidden console with no ConPTY), its pid in a marker file

What depends on the OS is in `plat.py`; the terminals are `HiddenMux` in `slots.py`, and the Windows pseudo-console is `conpty.py`.

C3 split this file by responsibility; each module imports only the ones before it in this list:
    state    shared state and small helpers: init, log, git, the plan file, the stop request
    brief    what a session is told: PROMPT, OTHERS, prompt_for, review/sheet paragraphs
    sched    picking the next task: tasks, pick, clashes, claims, parked tasks
    slots    worktrees, backends, a slot's environment, start/resume, disk, HiddenMux
    watch    transcripts, stalls, cut-offs, temp folders, memory, API and usage, upgrades, the Stop hook
    join     joining a merge's conflicts by line, and merge state shared with landing
    land     landing a tested merge in the main checkout, wip branches, pushes, releases, flaky tests
    merge    the merge worktree: fix and repair sessions, the merge gate, merges ahead, merge_batch
    control  control sessions, closing idle ones, the control server, Remote Control processes
    status   status, since, follow, Needs you lines
    feed     ending an older version's runner feed, handing a feed message on, opening a control session
    loop     the run: keys, finish, the loop (cmd_run); C51: its areas are loop_requests (halts, tells, restyles),
             loop_watch (CI, issues) and loop_after (the end of a tick; C53: its sweep of branches that
             finished outside the slots is loop_sweep, its upgrade and restart step loop_upgrade), re-exported by loop
    cmds     the other commands: take, resume, key, upgrade, status, since, needs, sheet, stop,
             control, background and attach
This module re-exports every name of theirs, so `runner.X` reads as before; `runner.X = v` reaches every
module that uses X (`state.share`).
"""
from __future__ import annotations

import sys
import types

from agent_runner import (state, brief, sched, slots, watch, join, land, merge, control, status, feed, loop,
                          cmds)
from agent_runner.state import share

for _m in (state, brief, sched, slots, watch, join, land, merge, control, status, feed, loop, cmds):
    globals().update({k: v for k, v in vars(_m).items() if not (k.startswith('__') and k.endswith('__'))})
del _m

# The library API a wrapping project may call; these change only in a major version. `cmd_run(argv)` and
# `cmd_stop(argv)` are the commands; `PROMPT`, `FIXER` and `OTHERS` may be replaced before `cmd_run`.
__all__ = ['init', 'cmd_run', 'cmd_stop', 'pick', 'tasks', 'prompt_for', 'reopen_landed', 'retry_reopened',
           'ask_stop', 'stopping', 'cmd_resume', 'PROMPT', 'FIXER', 'OTHERS']


class _Runner(types.ModuleType):
    """`runner.X = v` sets X in every runner module that holds it, as one module's global did before C3."""

    def __setattr__(self, name: str, value) -> None:
        share(**{name: value})
        super().__setattr__(name, value)


sys.modules[__name__].__class__ = _Runner
