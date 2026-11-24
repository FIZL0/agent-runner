"""F102: the run's side of `run ask`: park the session that asked, and block its task under Needs you. The answer
resumes that session (`slots.answer_ask`); the agent's side is `tools.cmd_ask`.

F156: also the ask file, <notes>/asks/ID.json (`need_detail` reads it), and its pictures in <notes>/asks/ID/: where
it is, its clean-up (`clear_ask`), and the note for a long line that has none (`long_line`)."""

from __future__ import annotations

import json
import os
import re
import shutil
from contextlib import ExitStack
from pathlib import Path

from agent_runner import plan as P, plansync
from agent_runner import state as S
from agent_runner.state import commit_plan, git, log, MERGE, plan_rel
from agent_runner.sched import open_tasks

# C, ROOT and SLOTS_DIR are read off `state` each call: `init` sets them there, and `share` reaches only the
# modules in state.FAMILY


class _Now:
    def __getattr__(self, name):
        return getattr(S.C, name)


C = _Now()

EV_FINISHED = 'finished'  # task `id`'s agent ran `run finish` (summary)
EV_ASKED = 'asked'        # task `id`'s agent ran `run ask`: parked until the person answers (question)


def park_asked(n: int, tid: str, sid: str, question: str, branch: str) -> bool:
    """Slot n's session ran `run ask`: keep its work, commits and uncommitted edits alike, on asked/<tid> (never
    merged), note its session in `<notes>/<tid>.ask` for the answer to resume (`slots.answer_ask`), and block the
    task under Needs you (`block_asks`). False when the work could not be kept: the task ends as any other."""
    d = S.SLOTS_DIR / f's{n}'
    dirty = bool(git('status', '--porcelain', cwd=d).stdout.strip())
    if dirty and (git('add', '-A', cwd=d).returncode or
                  git('commit', '-qm', f'{tid} wip: uncommitted, asked', '--no-verify', cwd=d).returncode):
        log(f'slot {n}: {tid} asked, but its edits could not be kept; it ends as any other session')
        return False
    git('checkout', '-q', '--detach', cwd=d)
    if git('branch', '-M', f'task/{tid}', f'asked/{tid}').returncode:
        log(f'slot {n}: {tid} asked, but task/{tid} could not become asked/{tid}; it ends as any other session')
        return False
    C.notes(f'{tid}.ask').write_text(json.dumps({'sid': sid, 'question': question, 'slot': n, 'dirty': dirty,
                                                 'blocked': False}), encoding='utf-8')
    log(f'slot {n}: {tid} asks the person: {question[:300]} — parked as asked/{tid}; the answer resumes its '
        f'session', EV_ASKED, tid, question=question)
    block_asks(branch)
    return True


def block_asks(branch: str) -> None:
    """Block each asked task not blocked yet with `DECIDE: <its question>`, committed as `block_parked` commits
    (MERGE free, TODO.md clean); one that cannot be now is tried again next tick."""
    for f in C.notes().glob('*.ask'):
        try:
            ask = json.loads(f.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if not isinstance(ask, dict) or ask.get('blocked') or not MERGE.acquire(blocking=False):
            continue
        tid, hold = f.stem, ExitStack()
        try:
            if C.plan_external:
                hold.enter_context(plansync.locked(C))
                plansync.pull(C, force=True)
            rel = plan_rel('TODO.md')
            if tid in open_tasks(branch):
                if not C.plan_external and (git('status', '--porcelain', '--', rel).stdout.strip() or
                                            git('branch', '--show-current').stdout.strip() != branch):
                    continue
                P.block(tid, f'DECIDE: {ask.get("question", "")} (asked with `run ask`: your answer resumes its '
                        f'session)', todo=S.ROOT / rel, after=[], keep_ask=True)
                if not commit_plan(f'Plan: block {tid}, asked the person', rel):
                    if not C.plan_external:
                        git('checkout', '-q', '--', rel)
                    continue
            ask['blocked'] = True  # or ticked, dropped or blocked meanwhile: nothing to block
            f.write_text(json.dumps(ask), encoding='utf-8')
        finally:
            hold.close()
            MERGE.release()


def unblocked_asks() -> set[str]:
    """Tasks parked by an ask whose block is not committed yet: no slot may start them until it is."""
    out = set()
    for f in C.notes().glob('*.ask'):
        try:
            if not json.loads(f.read_text(encoding='utf-8')).get('blocked'):
                out.add(f.stem)
        except (OSError, ValueError, AttributeError):
            continue
    return out


LINE_MAX = 200  # a longer ask line with no ask file gets `long_line`'s note


def ask_file(tid: str, c=None) -> Path:
    """<notes>/asks/ID.json in the main checkout, whichever worktree this runs in."""
    return (c or S.cfg()).notes('asks', f'{tid}.json')


def _plans(todo: str | Path | None):
    """The configs whose plan `todo` is (None: the plan of the folder this runs in). A scratch copy of a TODO.md is
    no project's plan, so a change to it touches no ask file."""
    found = []
    for get in (lambda: S.cfg(), lambda: S.C):
        try:
            c = get()
            rel = os.path.relpath(c.todo, c.root)
            ours = {os.path.realpath(c.todo), os.path.realpath(S.main_checkout(c.root) / rel)}
            if todo is None or os.path.realpath(todo) in ours:
                found.append(c)
        except (OSError, ValueError, AttributeError, SystemExit):
            continue
    return found


def clear_ask(tid: str, todo: str | Path | None = None) -> None:
    """Take task `tid`'s ask file and its pictures away: its item was answered, dropped or blocks again, and an old
    one must never stand in for a new ask."""
    if not re.fullmatch(r'\w[\w.-]*', tid or ''):
        return
    for c in _plans(todo):
        try:
            d = c.notes('x').parent / 'asks'
            (d / f'{tid}.json').unlink(missing_ok=True)
            pics = d / tid
            if pics.is_symlink():
                pics.unlink()
            elif pics.is_dir():
                shutil.rmtree(pics, ignore_errors=True)
        except OSError:
            continue


def long_line(tid: str, why: str, c=None) -> str:
    """What `done --blocked` says about an ask line too long to read in Needs you, with no ask file; '' else."""
    if len(why) <= LINE_MAX or not any(a[1] == tid for a in P.asks((c or S.cfg()).todo)):
        return ''
    f = ask_file(tid, c)
    return '' if f.is_file() else (
        f'the line is {len(why)} characters, hard to read in Needs you, and it has no ask file. Blocked all the same; '
        f'write the steps to {f} now as {{"summary", "where", "steps": [...], "expect": [...], "shots": [{{"file", '
        f'"caption"}}]}} and Needs you shows those (no need to block again)')
