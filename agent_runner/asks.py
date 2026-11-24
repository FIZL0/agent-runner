"""F102: the run's side of `run ask`: park the session that asked, and block its task under Needs you. The answer
resumes that session (`slots.answer_ask`); the agent's side is `tools.cmd_ask`.

F156: also the ask file, <notes>/asks/ID.json (`need_detail` reads it), and its pictures in <notes>/asks/ID/: where
it is, its clean-up (`clear_ask`), and the note for a long line that has none (`long_line`)."""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess as sp
from contextlib import ExitStack
from pathlib import Path

from agent_runner import plan as P, plansync, plat
from agent_runner import state as S
from agent_runner.state import commit_plan, git, log, MERGE, plan_rel
from agent_runner.sched import open_tasks, plan_text

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


def block_asks(branch: str, tried: set | None = None) -> None:
    """Block each asked task not blocked yet with `DECIDE: <its question>`, committed as `block_parked` commits
    (MERGE free, TODO.md clean); one that cannot be now is tried again next tick. F175: also `sweep_env`, each tick.
    B767: one answered before its block leaves `tried`, the run's tasks not to start again: its session goes on."""
    sweep_env(branch)
    if tried is not None:
        tried -= answered_asks()
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
            else:  # B767: never beside a `plan confirm` of this ask; one under way: next tick (the loop never waits)
                if not (lock := plat.lock(plansync._lock_path(C))):
                    continue
                hold.callback(lock.close)
            try:  # answered while the lock was waited for
                ask = json.loads(f.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                continue
            if not isinstance(ask, dict) or ask.get('blocked'):
                continue
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


def _pending(tid: str, todo: str | Path | None):
    """B767: (the .ask file, its content) when task `tid` of the plan `todo` is parked by a `run ask` the run has not
    blocked yet, else None. A slot's worktree or a scratch copy of TODO.md is not the plan a run blocks in."""
    if not re.fullmatch(r'\w[\w.-]*', tid or ''):
        return None
    for c in _plans(todo):
        try:
            at = c.todo if c.plan_external else S.main_checkout(c.root) / os.path.relpath(c.todo, c.root)
            if todo is not None and os.path.realpath(todo) != os.path.realpath(at):
                continue
            f = c.notes(f'{tid}.ask')
            ask = json.loads(f.read_text(encoding='utf-8'))
        except (OSError, ValueError, SystemExit):
            continue
        if isinstance(ask, dict) and not ask.get('blocked'):
            return f, ask
    return None


def pending_ask(tid: str, todo: str | Path | None = None) -> str:
    """The question of `tid`'s ask that is not blocked yet; '' for none."""
    got = _pending(tid, todo)
    return str(got[1].get('question') or 'a question with no text') if got else ''


def settle_ask(tid: str, todo: str | Path | None = None) -> None:
    """The person answered `tid`'s ask before the run marked it blocked: `block_asks` passes over it, and the run lets
    the task start again (`answered_asks`), which resumes its session with the answer."""
    if got := _pending(tid, todo):
        f, ask = got
        _rewrite(f, {**ask, 'blocked': True, 'answered': True})


def _rewrite(f: Path, ask: dict) -> None:
    """Replace `f` whole: the run and a `plan confirm` read it at any time."""
    tmp = f.with_suffix('.ask-tmp')
    tmp.write_text(json.dumps(ask), encoding='utf-8')
    os.replace(tmp, f)


def no_slot(tid: str, req: dict) -> str:
    """B767: the answer to a `plan tell` / `change` of a task no slot runs. A tell's words are kept in the run log:
    its sender may no longer wait for the answer."""
    if req['how'] == 'tell':
        log(f'{tid}: not told: {req["text"]}')
    return f'no slot runs {tid} now'


def answered_asks() -> set[str]:
    """Tasks whose ask was answered before its block (`settle_ask`), each said once: the run tries them again."""
    out = set()
    for f in C.notes().glob('*.ask'):
        try:
            ask = json.loads(f.read_text(encoding='utf-8'))
            if ask.pop('answered', None):
                _rewrite(f, ask)
                out.add(f.stem)
        except (OSError, ValueError, AttributeError):
            continue
    return out


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


def sheet_file(tid: str, c=None) -> Path:
    """<notes>/sheets/ID.json in the main checkout: task `tid`'s pick sheet."""
    return (c or S.cfg()).notes('sheets', f'{tid}.json')


def clear_ask(tid: str, todo: str | Path | None = None) -> None:
    """Take task `tid`'s ask file, its pictures and its pick sheet (B204) away: its item was answered, dropped or
    blocks again, and an old one must never stand in for a new ask."""
    if not re.fullmatch(r'\w[\w.-]*', tid or ''):
        return
    for c in _plans(todo):
        _clear_file(c, tid)
        _clear_sheet(c, tid)


def _clear_sheet(c, tid: str) -> None:
    """Take the pick sheet itself away (its page stays where it was published)."""
    d = c.notes('x').parent / 'sheets'
    for f in (f'{tid}.json', f'{tid}.taken'):
        try:
            (d / f).unlink(missing_ok=True)
        except OSError:
            continue


def _clear_file(c, tid: str) -> None:
    """Take the ask file and its pictures away."""
    try:
        d = c.notes('x').parent / 'asks'
        for f in (f'{tid}.json', f'{tid}.taken', f'{tid}.said'):
            (d / f).unlink(missing_ok=True)
        pics = d / tid
        if pics.is_symlink():
            pics.unlink()
        elif pics.is_dir():
            shutil.rmtree(pics, ignore_errors=True)
    except OSError:
        return


def env_file(tid: str, c=None) -> Path:
    """F175: <notes>/asks/ID.env in the main checkout: the secrets the person gave for task `tid`, NAME='value' each."""
    return (c or S.cfg()).notes('asks', f'{tid}.env')


def _ignored(f: Path) -> bool:
    """Whether git leaves `f` alone; one it would not is added to the clone's `info/exclude` first."""
    at = {'cwd': f.parent, 'capture_output': True, 'text': True}
    if sp.run(['git', 'rev-parse', '--git-dir'], **at).returncode:
        return True  # no repo, so nothing to commit it to
    ask = ['git', 'check-ignore', '-q', f.name]
    if not sp.run(ask, **at).returncode:
        return True
    ex = Path(f.parent, sp.run(['git', 'rev-parse', '--git-path', 'info/exclude'], **at).stdout.strip())
    ex.parent.mkdir(parents=True, exist_ok=True)
    old = ex.read_text(encoding='utf-8') if ex.exists() else ''
    ex.write_text(old + ('' if not old or old.endswith('\n') else '\n') + '/**/asks/*.env\n', encoding='utf-8')
    return not sp.run(ask, **at).returncode


def _write_env(f: Path, text: str) -> None:
    """Replace `f` whole with `text`, readable by its owner alone from the start."""
    tmp = f.with_name(f'.{f.stem}.tmp.env')
    tmp.unlink(missing_ok=True)
    try:
        with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w', encoding='utf-8', newline='\n') as h:
            h.write(text)
        os.replace(tmp, f)
    finally:
        tmp.unlink(missing_ok=True)


def keep_secrets(tid: str, values: dict[str, str], c=None):
    """F175: write the secrets `values` ({NAME: value}) to task `tid`'s env file beside those it has, and return what
    puts the file back as it was (the answer they go with failed). Raises OSError when they cannot be kept."""
    f = env_file(tid, c)
    if not _ignored(f):
        raise OSError(f'git would track {f}')
    old = f.read_text(encoding='utf-8') if f.is_file() else None
    kept = [x for x in (old or '').splitlines() if x.partition('=')[0] not in values]
    _write_env(f, ''.join(f'{x}\n' for x in kept + [f'{k}={shlex.quote(v)}' for k, v in values.items()]))
    return lambda: f.unlink(missing_ok=True) if old is None else _write_env(f, old)


def clear_env(tid: str, todo: str | Path | None = None) -> None:
    """F175: take task `tid`'s secrets away: it was dropped (one that lands: `sweep_env`)."""
    for c in _plans(todo) if re.fullmatch(r'\w[\w.-]*', tid or '') else []:
        try:
            env_file(tid, c).unlink(missing_ok=True)
        except OSError:
            continue


def sweep_env(branch: str) -> None:
    """F175: take away the secrets of each task that is no longer open or blocked, neither on `branch` nor in the main
    checkout: it landed or was dropped. A task its session only ticked on its own branch keeps them."""
    files = list(C.notes('asks', 'x').parent.glob('*.env'))
    if not files:
        return
    live: set[str] = set()
    try:
        for ls in (plan_text(branch), P.lines(C.todo)):
            if not ls:
                return  # a plan that does not read ends nothing
            live |= {tid.rstrip('.') for _, box, tid, _, _ in P.iter_tasks(ls) if box != 'x'}
    except (OSError, SystemExit):
        return
    for f in files:
        if f.stem.removeprefix('.').removesuffix('.tmp') not in live:
            try:
                f.unlink(missing_ok=True)
            except OSError:
                continue


def taken_ask(tid: str, todo: str | Path | None, again: bool) -> None:
    """A block takes task `tid`'s ask file and its pick sheet (B204) as its own (each one's time is kept in an ID.taken
    beside it). `again`: the task was blocked already, so a file that block took, not written since, is an old ask's
    and goes; the other, written since, stays."""
    if not re.fullmatch(r'\w[\w.-]*', tid or ''):
        return
    for c in {c.notes('x').parent: c for c in _plans(todo)}.values():  # once a folder: a second look takes a new file for an old
        for f, clear in ((ask_file(tid, c), _clear_file), (sheet_file(tid, c), _clear_sheet)):
            try:
                at = str(f.stat().st_mtime_ns) if f.is_file() else ''
                mark = f.with_name(f'{tid}.taken')
                if again and at and mark.is_file() and mark.read_text(encoding='utf-8') == at:
                    clear(c, tid)
                elif at:
                    mark.write_text(at, encoding='utf-8')
            except OSError:
                continue


def long_line(tid: str, why: str, c=None) -> str:
    """What `done --blocked` says about an ask line too long to read in Needs you, with no ask file; '' else."""
    if len(why) <= LINE_MAX or not any(a[1] == tid for a in P.asks((c or S.cfg()).todo)):
        return ''
    f = ask_file(tid, c)
    said = f.with_name(f'{tid}.said')  # once per ask: `clear_ask` takes it away
    if f.is_file() or said.exists():
        return ''
    said.touch()
    return (
        f'the line is {len(why)} characters, hard to read in Needs you, and it has no ask file. Blocked all the same; '
        f'write the steps to {f} now as {{"summary", "where", "steps": [...], "expect": [...], "shots": [{{"file", '
        f'"caption"}}]}} and Needs you shows those (no need to block again)')
