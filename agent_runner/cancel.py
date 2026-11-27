"""F426d: `plan cancel ID`: the run stops the agent on a running task and keeps its work on wip/ID, then the task is
held (F480, `plan hold`'s mark): it keeps its place and no run starts it again until the person unholds it. Nothing is cancelled while the task lands.

The run's part is `loop_requests.cancels`; it answers each request with JSON: {"cancelled", "msg", "wip"}."""
from __future__ import annotations

import json
import sys
import time

from agent_runner import plan as P

KIND = 'cancel'  # the request's channel. Not 'halt': a merge reads those, and deletes the branch of a halted task
YES = '--yes'
ASK = 'Cancel stops its agent, keeps its work and holds the task in its place: no agent starts it until you unhold it.'


def worked(tid: str, where: str, minutes: int | None) -> str:
    """How long `tid` has been worked on, a sentence ('' when that is not known)."""
    return '' if minutes is None else f'{tid} has worked {minutes} min{f" in {where}" if where else ""}. '


def question(tid: str, where: str = '', minutes: int | None = None) -> str:
    return f'{worked(tid, where, minutes)}{ASK} Cancel {tid}?'


def _state(c) -> dict:
    try:
        st = json.loads(c.notes('STATE').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return st if isinstance(st, dict) else {}


def minutes_in(c, tid: str) -> int | None:
    """The minutes the run's STATE says a slot has been on `tid`."""
    st = _state(c)
    n = next((n for n, t in (st.get('running') or {}).items() if t == tid), None)
    since = (st.get('since') or {}).get(n)
    return int((time.time() - since) // 60) if since else None


def landing(c, tid: str, where: str) -> str:
    """Why `tid` cannot be cancelled now: it lands, or its session ends by itself ('' when it can)."""
    from agent_runner.config import finished_mark
    if where == 'merging' or tid in (_state(c).get('merging') or []):
        return f'{tid} is landing, so it cannot be cancelled'
    if (m := finished_mark(where.removeprefix('s'), c)) and m.exists():
        return f'{tid} is finished and about to land, so it cannot be cancelled'
    if P.ending_ask(c, tid, where):
        return f'{tid} has just asked you a question and waits for your answer: it is not running any more'
    return ''


def stop(c, tid: str, words: list[str], wait: float | None = None) -> tuple[int, str, str]:
    """Ask the run to stop `tid`: (exit code, what to say, the note for its plan line). Code 0: the plan edit holds it."""
    if [w for w in words if w != YES]:
        return 2, f'{P.PROG} cancel <ID> [{YES}]', ''
    if (d := taken_dir(c, tid)) is not None:  # F455a
        return stop_taken(c, tid, d, words)
    if not (where := P.run_on(c, tid)):
        return 1, (f'{P.PROG}: {tid} is not running, so there is nothing to cancel (`{P.PROG} edit {tid} --pri later` '
                   'parks a queued task, `hold` holds it)'), ''
    if why := landing(c, tid, where):
        return 1, f'{P.PROG}: {why}', ''
    mins = minutes_in(c, tid)
    if YES not in words:
        return 3, f'{question(tid, where, mins)} To go on: {P.PROG} cancel {tid} {YES}', ''
    said = P.request(c, KIND, tid, {'how': 'cancel'}, P.HALT_WAIT if wait is None else wait)
    after = '' if mins is None else f' after {mins} min'
    if said is None:  # it stays asked; held now, so the run starts it again in no case
        return 0, f'asked the run to stop {where}: within seconds its work is on wip/{tid}, unless it lands first', \
            f'asked to cancel{after}: if it was stopped, what was done is on the newest wip/{tid} branch, go on from there'
    try:
        got = json.loads(said)
    except ValueError:
        got = {}
    if not got.get('cancelled'):
        return 1, f'{P.PROG}: {got.get("msg") or f"the run did not cancel {tid}"}', ''
    wip = got.get('wip') or ''
    return 0, got.get('msg', ''), f'cancelled{after}: ' + (
        f'its work is on {wip}, go on from there' if wip else 'nothing had been done yet')


def park(tid: str, note: str, todo=None) -> None:
    """Park `tid` in the plan, with what its next agent should know as a note."""
    todo, _ = P.ensure(todo)
    P.edit(tid, pri='later', todo=todo)
    if note:
        P.note(tid, note, todo=todo)


def hold(tid: str, note: str, todo=None) -> None:
    """F480: hold `tid` where it stands (`plan hold`'s mark), with what its next agent should know as a note."""
    from agent_runner import row_hold
    todo, _ = P.ensure(todo)
    ls = list(P.lines(todo))
    if not row_hold.is_held(ls[P._find(ls, tid)]):
        P.edit(tid, keyed=f' | {row_hold.KEY}: yes', todo=todo)
    if note:
        P.note(tid, note, todo=todo)


def main(c, argv: list[str]) -> tuple[int, list[str]]:
    """`plan cancel`, before its plan edit: (exit code, the edit's words), the code not 0 when there is no edit."""
    if not argv:
        print(f'{P.PROG} cancel <ID> [{YES}]', file=sys.stderr)
        return 2, []
    tid = argv[0]
    rc, said, note = stop(c, tid, argv[1:])
    if said:
        print(said, file=sys.stderr if rc else sys.stdout)
    return rc, [] if rc else ['cancel', tid, note]


# --- F455a: a task taken by hand (`take`), run up or not -------------------------------------------------------------

def taken_dir(c, tid: str):
    """The take worktree of `tid` (as `sched.taken`), or None when it is not taken by hand."""
    d = c.slots_dir / f'take-{tid}'
    return d if (d / '.git').exists() else None


def _taken_landing(c, tid: str) -> str:
    from agent_runner import plansync
    from agent_runner.done import TESTED
    from agent_runner.state import git
    if tid in (_state(c).get('merging') or []) or not git('rev-parse', '--verify', '-q', TESTED + tid).returncode \
            or (plansync.ticks(c) / tid).exists():
        return f'{tid} is finished and about to land, so it cannot be cancelled'
    return ''


def chat_of(c, d) -> int:
    """The live chat that took worktree `d` (B846's record), 0 when none is."""
    from agent_runner import taken_by
    from agent_runner.control import control_live_numbers
    try:
        return taken_by.chat(c, d, control_live_numbers()) or 0
    except Exception:  # noqa: BLE001 - not knowing the chat never stops a cancel
        return 0


def tell_chat(n: int, d) -> str:
    """Tell chat `n` to stop: what was done, '' when no chat was told."""
    from agent_runner.control import control_type
    try:
        if n and control_type(n, f'STOP: the person cancelled this task; its worktree {d} is gone and its work '
                                 'kept on a wip branch. Do no more work on it.'):
            return f'told chat {n} to stop'
    except OSError:
        pass
    return ''


def keep_taken(c, tid: str, d) -> tuple[str, str]:
    """Everything in take worktree `d` (commits, edits, untracked files) on a wip/<tid> branch, then the worktree and
    task/<tid> removed: (the wip branch, '' with nothing to keep; why nothing changed, '' when it went)."""
    from agent_runner import gitops, sched
    from agent_runner.slots import free_branch
    from agent_runner.state import default_branch, git, ROOT
    committed = False
    if git('status', '--porcelain', cwd=d).stdout.strip():
        git('add', '-A', cwd=d)
        if git('commit', '-q', '--no-verify', '-m', f'{tid} wip: uncommitted when it was cancelled', cwd=d).returncode:
            git('reset', '-q', cwd=d)
            return '', f'its uncommitted edits in {d} could not be committed, so nothing was changed'
        committed = True

    def undo(why: str) -> tuple[str, str]:
        if committed:
            git('reset', '-q', '--soft', 'HEAD~1', cwd=d)
            git('reset', '-q', cwd=d)
        return '', f'{why}, so nothing was changed'

    head = git('rev-parse', '-q', '--verify', 'HEAD', cwd=d).stdout.strip()
    branch = git('symbolic-ref', '-q', '--short', 'HEAD', cwd=d).stdout.strip()
    own = bool(head) and git('rev-list', '--count', f'{default_branch()}..{head}').stdout.strip() not in ('', '0')
    wip = ''
    if own and git('branch', wip := free_branch(f'wip/{tid}'), head).returncode:
        return undo(f'{wip} could not be made')
    if (r := git('worktree', 'remove', '--force', str(d))).returncode:
        if wip:
            git('branch', '-D', wip)
        return undo(f'its worktree {d} could not be removed ({r.stderr.strip()})')
    if branch == f'task/{tid}':
        git('branch', '-D', branch)
    if wip:
        sched.forgive_park(tid, wip)
        gitops.push(ROOT, wip)
    return wip, ''


def stop_taken(c, tid: str, d, words: list[str]) -> tuple[int, str, str]:
    """`stop` for a task taken by hand: no run is needed, this command does it all."""
    from agent_runner import state
    state.init(c.root)
    if why := _taken_landing(c, tid):
        return 1, f'{P.PROG}: {why}', ''
    if YES not in words:
        return 3, f'{tid} is taken by hand in {d}. {ASK} Cancel {tid}? To go on: {P.PROG} cancel {tid} {YES}', ''
    n = chat_of(c, d)  # before the worktree goes: the record is in its git folder
    wip, bad = keep_taken(c, tid, d)
    if bad:
        return 1, f'{P.PROG}: {bad}', ''
    told = tell_chat(n, d)
    said = f'cancelled {tid}; removed its take worktree; ' + (f'its work is on {wip}' if wip else 'nothing had been done')
    return 0, said + (f'; {told}' if told else ''), \
        'cancelled while taken by hand: ' + (f'its work is on {wip}, go on from there' if wip else 'nothing had been done yet')
