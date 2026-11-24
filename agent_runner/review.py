"""F406e `run review ID`: the spec review as a fresh one-shot on `[models] review`, any provider's.

A Claude Code session with a claude review model hands the review to its `review` subagent instead. A session on the
harness loop has no subagents, and a subagent cannot run another provider's model: both run this before `done`. The
one-shot is given only the task's diff and brief; its findings are printed, so the session reads them as the command's
output. A claude model runs as `claude -p` with Read only, another provider's in the harness loop with read only.
"""
from __future__ import annotations

import argparse
import json
import subprocess as sp
import sys
from pathlib import Path

from agent_runner import plat, state
from agent_runner.brief import brief_for, SUBAGENTS
from agent_runner.gitops import git
from agent_runner.tools import task_here

TIMEOUT = 900  # s the one-shot gets

ASK = """{role}

Say, in under 300 words, each finding quoting the task's words: (a) what the task asked for that is missing or partial, \
(b) what the diff does that was not asked, (c) what looks implemented but wrong. With none, answer "nothing".

The task's brief:

{brief}

The diff (`git diff {base}...HEAD`):

{diff}
"""


def prompt(tid: str, base: str, cwd: Path, diff: str) -> str:
    return ASK.format(role=SUBAGENTS['review'][1], brief=brief_for(tid, cwd), base=base, diff=diff)


def claude_once(model: str, text: str, cwd: Path) -> tuple[str, str]:
    """(the answer, why it failed) of a headless Claude Code one-shot with Read only, `text` on stdin."""
    from agent_runner.control import control_env
    from agent_runner.sched import agent_held
    if bad := agent_held():  # B764c
        return '', f'the one-shot on {model} did not run: {bad}'
    argv = [plat.exe(state.C.run['agent']), '-p', '--model', model, '--tools', 'Read', '--permission-mode', 'dontAsk',
            '--strict-mcp-config', '--setting-sources', '', '--settings', json.dumps({'autoMemoryEnabled': False})]
    try:
        r = sp.run(argv, cwd=str(cwd), env=control_env(), input=text, capture_output=True, text=True,
                   encoding='utf-8', errors='replace', timeout=TIMEOUT)
    except (OSError, sp.SubprocessError) as e:
        return '', f'the one-shot on {model} did not run: {e}'
    said = (r.stdout or '').strip()
    if r.returncode or not said:
        end = ' '.join(f'{r.stderr or ""} {said}'.split())[-300:]
        return '', f'the one-shot on {model} gave no answer (exit {r.returncode}): {end}'
    return said, ''


def review(tid: str, base: str, cwd: Path) -> tuple[str, str]:
    """(the findings, why there are none) of a fresh one-shot's spec review of `tid`'s diff in worktree `cwd`."""
    from agent_runner.feed import harness_once
    from agent_runner.slots import on_harness
    r = git('diff', f'{base}...HEAD', cwd=cwd)
    if r.returncode:
        return '', f'git diff {base}...HEAD failed: {r.stderr.strip()}'
    if not r.stdout.strip():
        return '', f'git diff {base}...HEAD is empty: commit the work first'
    model, text = state.C.models['review'], prompt(tid, base, cwd, r.stdout)
    return harness_once(model, text, cwd, TIMEOUT) if on_harness(model) else claude_once(model, text, cwd)


def cmd_review(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog='run review', description="The spec review before `done`: a fresh one-shot on "
                                 "[models] review is given only this worktree's committed diff and the task's brief, "
                                 'and its findings are printed.')
    ap.add_argument('id', nargs='?', help="the task (default: this worktree's task/<ID> branch)")
    ap.add_argument('--base', help='the branch the diff is taken against (default: the shared branch)')
    a = ap.parse_args(argv)
    state.init()
    tid = a.id or task_here()
    if not tid:
        print('run review: no task: this worktree is not on a task/<ID> branch (give the ID)', file=sys.stderr)
        return 2
    top = git('rev-parse', '--show-toplevel', cwd=Path.cwd())
    cwd = Path(top.stdout.strip()) if not top.returncode else Path.cwd()
    said, why = review(tid, a.base or state.default_branch(), cwd)
    if why:
        print(f'run review: no review: {why}', file=sys.stderr)
        return 1
    print(said)
    return 0
