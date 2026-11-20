"""Joining a merge's conflicts by line (`union`, `renumber_doubles`, `[git] join` commands) and the merge
state shared by merging and landing."""

from __future__ import annotations

import fnmatch
import os
import re
import subprocess as sp
from pathlib import Path

from agent_runner import plan as P, plat
from agent_runner.state import C, git, log, note, plan_rel, TASK


def joinable(f: str) -> bool:
    """True when the runner may join both sides of a conflict in `f` itself (`[run] joinable`, globs).

    Only for files where a line is a whole record and two agents each added records: a changelog, a
    journal. Not the task list and its archive, whatever the config says: git merges those by task
    (`plan.merge3`), and a conflict left there is in prose. Never prose, even prose that is only appended to. A union joins
    *lines*, and two sides that both reflowed one paragraph give it no line to agree on. It then stitches
    them into something that reads like a sentence and is not one, and a reader believes it. A paragraph
    needs reading, so it goes to a fix session.
    """
    if f in (plan_rel('TODO.md'), plan_rel('DONE.md')):
        return False  # git merged it by task already (`plan.merge3`): what still conflicts there is prose
    return any(fnmatch.fnmatch(f, g) for g in [*C.run['joinable'], *C.run['join']])


def custom_join(f: str, sides: list[str], text: str, tid: str, cwd: Path) -> str | None:
    """`[run.join]`: hand a joined file to the project's own joiner. The text to keep, or None to refuse.

    Some record-per-line files cannot be joined blind: an address list where both sides gave one name two
    different addresses must go to somebody who can pick, not to whichever branch merged first. The
    project knows its own records, so it gets a command per glob, with these placeholders (all paths):

        {ours} {base} {theirs}   the three sides of the conflict
        {union}                  both sides' lines joined (what the runner would keep without this)
        {out}                    where to write the result; it starts as a copy of {union}
        {file}                   the file's path in the repo

    Exit 0 keeps {out}; anything else refuses the join, and the conflict goes to a fix session (its output
    is logged). A command rather than a Python hook, so it can be any language, and so the project's own
    CLI (`./kit oracle-join ...`) is the one place that knows the format.
    """
    cmd = next(c for g, c in C.run['join'].items() if fnmatch.fnmatch(f, g))
    u, out = C.notes(f'union.{tid}.joined'), C.notes(f'union.{tid}.out')  # per task: joins run in threads at once
    u.write_text(text, encoding='utf-8')
    out.write_text(text, encoding='utf-8')
    vals = dict(ours=sides[0], base=sides[1], theirs=sides[2], union=str(u), out=str(out), file=f)
    try:
        r = sp.run(cmd.format_map({k: plat.quote(v) for k, v in vals.items()}), shell=True, cwd=str(cwd),
                   capture_output=True, text=True, errors='replace', timeout=C.run['timeout'])
    except sp.TimeoutExpired:
        log(f'{tid}: the [run.join] command for {f} ran past [run] timeout ({C.run["timeout"]}s); join refused')
        return None
    if r.returncode:
        log(f'{tid}: the [run.join] command for {f} refused the join (exit {r.returncode}): '
            + ' / '.join((r.stdout + r.stderr).strip().splitlines()[-3:])[:300])
        return None
    try:
        return out.read_text(encoding='utf-8')
    finally:
        u.unlink(missing_ok=True)
        out.unlink(missing_ok=True)


def union(files: list[str], tid: str, cwd: Path) -> bool:
    """Join both sides of a conflict in every file `joinable` allows; a file with a `[run.join]` command
    goes through it (`custom_join`), which may refuse."""
    for f in files:
        sides = []
        for stage in (2, 1, 3):  # ours, base, theirs
            t = C.notes(f'union.{tid}.{stage}')  # per task: joins run in threads at once
            t.write_text(git('show', f':{stage}:{f}', cwd=cwd).stdout, encoding='utf-8')
            sides.append(str(t))
        out = git('merge-file', '-p', '--union', *sides, cwd=cwd)
        text = out.stdout if out.returncode >= 0 else None
        if text is not None and any(fnmatch.fnmatch(f, g) for g in C.run['join']):
            text = custom_join(f, sides, text, tid, cwd)
        for t in sides:
            Path(t).unlink(missing_ok=True)
        if text is None:
            return False
        (cwd / f).write_text(text, encoding='utf-8')
        git('add', f, cwd=cwd)
    return True


def _next_free(k: str, taken: set[str]) -> str:
    """The next id of `k`'s kind that `taken` does not hold: P119 -> P124, P118a -> P118c."""
    if m := re.fullmatch(r'(.*\d)([a-z])', k):
        last = max((t[-1] for t in taken if len(t) == len(k) and t.startswith(m.group(1))), default='`')
        return m.group(1) + chr(ord(last) + 1)
    if m := re.fullmatch(r'(.*[^\d])(\d+)', k):
        n = [int(t[len(m.group(1)):]) for t in taken if t.startswith(m.group(1)) and t[len(m.group(1)):].isdigit()]
        return f'{m.group(1)}{max(n, default=0) + 1}'
    return k + 'r'


def renumber_doubles(ref: str, onto: str, tid: str, cwd: Path) -> str:
    """`ref`, or a commit on top of it that renumbers the tasks it added under an id `onto` already uses.

    A branch files a follow-up with the next id its own copy of the plan has free, while main, meanwhile,
    may have handed that id to another task. The merge keeps both lines (`plan.merge3`), but under one id, so a
    tick or a pick would take one for the other: P118's two follow-ups vanished that way. So before a merge the branch's
    new task gets the next id free on both sides, and every line the branch added or changed that names it
    follows; the change is logged. Run before each merge, the tested one and the one onto main."""
    files = [plan_rel('TODO.md'), plan_rel('DONE.md')]
    base = git('merge-base', onto, ref, cwd=cwd).stdout.strip()
    show = lambda rev, f: git('show', f'{rev}:{f}', cwd=cwd).stdout.splitlines() if rev else []

    def ids(rev):
        return {m.group(2).rstrip('.'): re.sub(r'^- \[.\] ', '', l)
                for f in files for l in show(rev, f) if (m := TASK.match(l))}

    old, theirs, ours = ids(base), ids(ref), ids(onto)
    doubled = [k for k in theirs if k not in old and k in ours and k != tid and theirs[k] != ours[k]]
    if not doubled:
        return ref
    taken, new = set(old) | set(theirs) | set(ours) | P.reserved(cwd), {}
    for k in doubled:
        new[k] = _next_free(k, taken)
        taken.add(new[k])
    P.reserve(cwd, *new.values())  # or the next branch's renumber takes the same one (MD175 -> 180 -> 181 -> 182)
    pat = re.compile(r'\b(' + '|'.join(map(re.escape, new)) + r')\b')
    idx = C.notes(f'renumber.{tid}.index')  # one per task: merges of different tasks run in threads at once
    env = {**os.environ, 'GIT_INDEX_FILE': str(idx)}
    g = lambda *a, **kw: git(*a, cwd=cwd, env=env, **kw)
    try:
        g('read-tree', ref)
        for f in files:
            was, now = set(show(base, f)), show(ref, f)
            if not now:
                continue
            text = '\n'.join(l if l in was else pat.sub(lambda m: new[m.group(1)], l) for l in now) + '\n'
            blob = g('hash-object', '-w', '--stdin', input=text).stdout.strip()
            g('update-index', '--cacheinfo', f'100644,{blob},{f}')
        for k, v in new.items():  # the long form the branch wrote for it goes with it
            was, now = plan_rel(f'{P.TASKS}/{k}.md'), plan_rel(f'{P.TASKS}/{v}.md')
            blob = git('rev-parse', '-q', '--verify', f'{ref}:{was}', cwd=cwd).stdout.strip()
            if blob and git('cat-file', '-e', f'{base}:{was}', cwd=cwd).returncode:
                g('update-index', '--force-remove', was)
                g('update-index', '--add', '--cacheinfo', f'100644,{blob},{now}')
        tree = g('write-tree').stdout.strip()
        pairs = ', '.join(f'{k} -> {v}' for k, v in new.items())
        c = g('commit-tree', tree, '-p', ref, '-m',
              f'{tid}: renumber {pairs} ({onto} already uses the id)').stdout.strip()
    finally:
        idx.unlink(missing_ok=True)
    if not c:
        log(f'{tid}: could not renumber {", ".join(doubled)}; the merge may drop a task')
        return ref
    log(f'{tid}: renumbered {pairs}: {onto} gave the id to another task meanwhile')
    note(f'{tid}: renumbered {pairs} before the merge')
    return c


LAND_WAIT = 10 * 60  # how long a tested merge holds MERGE waiting on edits in the main checkout
LAND_WAIT_WIP = 3 * 60  # with [git] land_edited = "wip": how long before those edits go to a wip branch
EDITS_POLL = 60  # then how often its thread looks whether those edits are committed
REMIND_EVERY = 30 * 60  # and how often it raises the alarm again while they are not
EDITED = 'uncommitted edits in the main checkout'  # land()'s why for them; finish() keeps the branch
ELSEWHERE = 'the main checkout has another branch out'  # and for that: never switched under whoever works there

WAITING: set[str] = set()  # finished tasks queued on MERGE: whoever merges next takes them along
LANDED: dict[str, tuple[str, str]] = {}  # a task that landed in another's batch -> (base, merged)
TASK_SID: dict[str, str] = {}  # the session that did a task, kept for its repair (`repair_merge`)


def task_env(tid: str) -> dict:
    """The environment for a git merge of `tid`'s branch: the task list's merge driver (`plan.merge3`) lets the
    branch's own words win where both sides edited the same part of that task's line."""
    return {'env': {**os.environ, 'AGENT_RUNNER_TASK': tid}} if tid else {}


def merge_into(d: Path, ref: str, msg: str, tid: str = '') -> list[str] | None:
    """`git merge ref` in d: the files left in conflict ([] when it merged), or None when git refused it.

    A failed merge with nothing in conflict is either git rerere having replayed an earlier resolution of
    every file (the merge is still open: committed here) or git refusing to start (e.g. an untracked file
    in the way), which must not pass for a merge."""
    if not git('merge', '--no-edit', '-m', msg, ref, cwd=d, **task_env(tid)).returncode:
        return []
    if files := git('diff', '--name-only', '--diff-filter=U', cwd=d).stdout.split():
        return files
    if git('rev-parse', '-q', '--verify', 'MERGE_HEAD', cwd=d).returncode:
        return None
    git('commit', '-q', '--no-edit', cwd=d)
    return []


def joined(files: list[str], tid: str, d: Path) -> bool:
    """Every conflicted file in `d` is one the runner may join, and joining them worked: committed."""
    if not (all(map(joinable, files)) and union(files, tid, d)):
        return False
    git('commit', '-q', '--no-edit', cwd=d)
    return True
