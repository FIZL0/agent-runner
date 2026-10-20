"""`./run done <ID> "<message>"`: how a session finishes a task, in one call that cannot be half-done.

    ./run done T4 "T4: the parser reads nested lists"
    ./run done T4 "T4 (part): lists parse, maps do not" --blocked "maps need T7's tokenizer" --after T7

In order: the test gate (`[run] test`), the pre-commit check (`[run] precommit`), then tick the task (or
block it), `git add -A`, commit, and push the branch it committed on — unless that is the shared branch,
which only the runner pushes, after a merge.

One command rather than five because each of the five is a step a session forgets: a tick without the
commit, a commit without the tests, a branch never pushed. A failing gate commits nothing and ticks
nothing, so a "done" task is always one whose tests passed.

`[run] precommit` is for what must never be committed at all, whatever the tests say (a project's audit
for leaked secrets or names). It runs on the worktree before anything is staged; `--skip-check` commits
anyway, for the one deliberate case, and the commit message should say why.

`--blocked WHY` marks it `[~]` instead. Say what would unblock it. If what it waits on is another task
landing, `--after ID[,ID]` (or just naming the open ids in WHY) lets a run reopen it once they merge.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from agent_runner import plan
from agent_runner.config import cfg
from agent_runner.gitops import push, shared_branch


PROG = 'run done'  # the name in messages; a wrapper sets its own ('kit done')
__all__ = ['gate', 'check', 'main', 'PROG']


def gate(cwd: Path, key: str = 'test') -> tuple[int, str]:
    """Run `[run] <key>` in `cwd`; (exit code, last lines of its output). (0, '') when it is not set."""
    cmd = cfg(cwd).run[key]
    if not cmd:
        return 0, ''
    r = subprocess.run(cmd, shell=True, cwd=str(cwd), capture_output=True, text=True)
    tail = (r.stdout + r.stderr).strip().splitlines()[-15:]
    return r.returncode, '\n'.join(tail)


def check(cwd: Path) -> tuple[int, str]:
    """The pre-commit check, `[run] precommit`, as `gate` runs the tests."""
    return gate(cwd, 'precommit')


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog=PROG, description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('id', metavar='ID')
    ap.add_argument('message', metavar='MSG', help='the commit message')
    ap.add_argument('--blocked', metavar='WHY', help='mark it [~] instead of done: why, and what unblocks it')
    ap.add_argument('--after', metavar='IDS', default=None,
                    help='with --blocked: the tasks it waits on, comma-separated (default: read off WHY)')
    ap.add_argument('--no-test', action='store_true', help='skip the gate (say why in the message)')
    ap.add_argument('--skip-check', action='store_true',
                    help='commit even though [run] precommit failed (say why in the message)')
    a = ap.parse_args(argv)
    c = cfg()
    cwd = c.root

    if not a.no_test:
        rc, tail = gate(cwd)
        if rc:
            print(tail)
            print(f'\nThe test gate failed: nothing ticked, nothing committed. Fix it, or commit what is solid '
                  f'and\n    {PROG} {a.id} "<msg>" --blocked "<why + what unblocks it>"', file=sys.stderr)
            return 1
        if c.run['test']:
            print(f'gate passed: {c.run["test"]}')

    if c.run['precommit']:
        rc, tail = check(cwd)
        if rc and not a.skip_check:
            print(tail)
            print(f'\nThe pre-commit check failed ({c.run["precommit"]}): nothing ticked, nothing committed. '
                  f'Fix what it found, or, if this one is deliberate,\n    {PROG} {a.id} "<msg>" --skip-check',
                  file=sys.stderr)
            return 1
        print(f'check {"failed, skipped (--skip-check)" if rc else "passed"}: {c.run["precommit"]}')

    if a.blocked:
        plan.block(a.id, a.blocked, after=None if a.after is None else [t for t in a.after.split(',') if t])
        print(f'blocked {a.id}')
    else:
        plan.tick(a.id)
        print(f'ticked {a.id}')

    def g(*args):
        return subprocess.run(['git', *args], cwd=str(cwd), capture_output=True, text=True)

    if g('add', '-A').returncode:
        print('git add failed', file=sys.stderr)
        return 1
    if not g('diff', '--cached', '--quiet').returncode:
        print('nothing to commit (the tick was already committed?)')
        return 0
    if (r := g('commit', '-qm', a.message)).returncode:
        print(f'git commit failed: {r.stderr.strip()}', file=sys.stderr)
        return 1
    print(g('log', '-1', '--oneline').stdout.strip())
    here = g('branch', '--show-current').stdout.strip()
    if here and (line := push(cwd, here)):
        print(line)
    elif here and (remote := c.push_remote) and shared_branch(cwd, remote, here):
        print(f'{here} is not pushed: done only pushes a task branch (git push {remote} {here} to publish)')
    return 0
