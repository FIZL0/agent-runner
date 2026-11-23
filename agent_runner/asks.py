"""F102: the run's side of `run ask`: park the session that asked, and block its task under Needs you. The answer
resumes that session (`slots.answer_ask`); the agent's side is `tools.cmd_ask`."""

from __future__ import annotations

import json
from contextlib import ExitStack

from agent_runner import plan as P, plansync
from agent_runner.state import C, commit_plan, git, log, MERGE, plan_rel, ROOT, SLOTS_DIR
from agent_runner.sched import open_tasks

EV_FINISHED = 'finished'  # task `id`'s agent ran `run finish` (summary)
EV_ASKED = 'asked'        # task `id`'s agent ran `run ask`: parked until the person answers (question)


def park_asked(n: int, tid: str, sid: str, question: str, branch: str) -> bool:
    """Slot n's session ran `run ask`: keep its work, commits and uncommitted edits alike, on asked/<tid> (never
    merged), note its session in `<notes>/<tid>.ask` for the answer to resume (`slots.answer_ask`), and block the
    task under Needs you (`block_asks`). False when the work could not be kept: the task ends as any other."""
    d = SLOTS_DIR / f's{n}'
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
                        f'session)', todo=ROOT / rel, after=[])
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
