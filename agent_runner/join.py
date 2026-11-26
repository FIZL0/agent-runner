"""Joining a merge's conflicts by line (`union`, `renumber_doubles`, `[git] join` commands) and the merge
state shared by merging and landing."""

from __future__ import annotations

import datetime as dt
import fnmatch
import os
import re
import subprocess as sp
import sys
from pathlib import Path

from agent_runner import glossary, plan as P, plat
from agent_runner.state import C, git, hook, log, note, plan_rel


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
    return is_glossary(f) or any(fnmatch.fnmatch(f, g) for g in [*C.run['joinable'], *C.run['join']])


def is_glossary(f: str) -> bool:
    """True when `f` is the project's glossary (`[plan] glossary`): its conflicts join by entry (`glossary_join`)."""
    p = glossary.path(C)
    return p is not None and f == os.path.relpath(p, C.root).replace(os.sep, '/')


def glossary_join(f: str, tid: str, cwd: Path) -> str | None:
    """The glossary `f` with both sides of its conflict joined by entry (`glossary.join3`), or None to refuse: an
    entry both sides changed differently, a side that does not parse, or one that has no such file any more."""
    base, ours, theirs = (git('show', f':{stage}:{f}', cwd=cwd) for stage in (1, 2, 3))
    if ours.returncode or theirs.returncode:  # no base is fine: both sides started one
        log(f'{tid}: the conflict in {f} is not joined: one side removed the file')
        return None
    try:
        return glossary.join3('' if base.returncode else base.stdout, ours.stdout, theirs.stdout)
    except glossary.CannotJoin as e:
        log(f'{tid}: the conflict in {f} is not joined: {e}')
        return None


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
    rc, said = hook(f'{tid}: the [run.join] command for {f} (join refused)',
                    cmd.format_map({k: plat.quote(v) for k, v in vals.items()}), cwd)
    if rc is None:  # ran past [run] command_timeout: `hook` logged it
        return None
    if rc:
        log(f'{tid}: the [run.join] command for {f} refused the join (exit {rc}): '
            + ' / '.join(said.strip().splitlines()[-3:])[:300])
        return None
    try:
        return out.read_text(encoding='utf-8')
    finally:
        u.unlink(missing_ok=True)
        out.unlink(missing_ok=True)


def union(files: list[str], tid: str, cwd: Path) -> bool:
    """Join both sides of a conflict in every file `joinable` allows; a file with a `[run.join]` command
    goes through it (`custom_join`), which may refuse, and the glossary without one joins by entry (`glossary_join`)."""
    for f in files:
        own = any(fnmatch.fnmatch(f, g) for g in C.run['join'])
        if not own and is_glossary(f):
            if (text := glossary_join(f, tid, cwd)) is None:
                return False
            (cwd / f).write_text(text, encoding='utf-8')
            git('add', f, cwd=cwd)
            continue
        sides = []
        for stage in (2, 1, 3):  # ours, base, theirs
            t = C.notes(f'union.{tid}.{stage}')  # per task: joins run in threads at once
            t.write_text(git('show', f':{stage}:{f}', cwd=cwd).stdout, encoding='utf-8')
            sides.append(str(t))
        out = git('merge-file', '-p', '--union', *sides, cwd=cwd)
        text = out.stdout if out.returncode >= 0 else None
        if text is not None and own:
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


def renumber_doubles(ref: str, onto: str, tid: str, cwd: Path, remote: bool = False, at=None,
                     held: list | None = None) -> str:
    """`ref`, or a commit on top of it that renumbers the tasks it added under an id `onto` already uses.

    A branch files a follow-up with the next id its own copy of the plan has free, while main, meanwhile,
    may have handed that id to another task. The merge keeps both lines (`plan.merge3`), but under one id, so a
    tick or a pick would take one for the other: P118's two follow-ups vanished that way. So before a merge the branch's
    new task gets the next id free on both sides, and every line the branch added or changed that names it
    follows; the change is logged. Run before each merge, the tested one and the one onto main.

    With `remote` (`renumber_upstream`), `ref` is this side and `onto` the remote's branch it takes in: nothing is
    folded, a task both sides have (one line, whatever was noted on it since) is no clash, and one that has a
    branch keeps its id, since its session and its merge go by it; that is logged.

    `at` (`renumber_plan`) is the project whose plan is in the repository `cwd`, which may be a `[plan] repo` clone:
    the paths, the notes folder, the branches and the log are that project's, with no run needed. What to do once the
    merge holds (reserve the new ids, log them) goes in `held` then, as calls."""
    rel = (lambda name: os.path.relpath(at.plan_dir / name, cwd).replace(os.sep, '/')) if at else plan_rel
    log_ = (lambda msg: _plan_log(at, msg)) if at else log
    files = [rel('TODO.md'), rel('DONE.md')]
    base = git('merge-base', onto, ref, cwd=cwd).stdout.strip()
    show = lambda rev, f: git('show', f'{rev}:{f}', cwd=cwd).stdout.splitlines() if rev else []

    def ids(rev):
        return {tid.rstrip('.'): f'**{tid}**{rest}'
                for f in files for _, _, tid, rest, _ in P.iter_tasks(show(rev, f))}

    old, theirs, ours = ids(base), ids(ref), ids(onto)
    try:
        folds, blocks = ({}, {}) if remote else fold_doubles(show(base, files[0]), show(ref, files[0]), show(onto, files[0]), tid)
    except Exception as e:  # a fold is a nicety: odd plan text must not stop the merge
        log(f'{tid}: could not hold its follow-ups against {onto} ({e}); a follow-up may land twice')
        folds, blocks = {}, {}
    doubled = [k for k in theirs if k not in old and k in ours and k != tid and theirs[k] != ours[k]
               and k not in folds]
    if remote:
        def said(line):  # its own words, without the notes and BLOCKED after them
            return next((s.strip() for s in P.SEG.split(line.partition('**')[2].partition('**')[2]) if s.strip()), '')

        if tid in theirs and tid not in old and tid in ours and theirs[tid] != ours[tid]:
            doubled.append(tid)  # the task of this merge: logged below
        doubled = [k for k in doubled if said(theirs[k]) != said(ours[k])]
        if begun := [k for k in doubled if k == tid or any(not git('rev-parse', '-q', '--verify', f'refs/heads/{b}/{k}',
                                                       cwd=at.root if at else cwd).returncode for b in ('task', 'wip'))]:
            log_(f'{tid}: {onto} uses {", ".join(begun)} for another task, but it is under way here, so it is not '
                'renumbered: two tasks now have that id')
            doubled = [k for k in doubled if k not in begun]
    if not doubled and not folds:
        return ref
    taken, new = set(old) | set(theirs) | set(ours) | P.reserved(cwd), {}
    for k in doubled:
        new[k] = _next_free(k, taken)
        taken.add(new[k])
    if doubled and held is not None:
        held.append(lambda: P.reserve(cwd, *new.values()))
    elif doubled:
        P.reserve(cwd, *new.values())  # or the next branch's renumber takes the same one (MD175 -> 180 -> 181 -> 182)
    moved = {**new, **folds}  # a line the branch wrote that names a folded task names the one it went into
    pat = re.compile(r'\b(' + '|'.join(map(re.escape, moved)) + r')\b')
    idx = (at or C).notes(f'renumber.{tid}.index')  # one per task: merges of different tasks run in threads at once
    env = {**os.environ, 'GIT_INDEX_FILE': str(idx)}
    g = lambda *a, **kw: git(*a, cwd=cwd, env=env, **kw)
    try:
        g('read-tree', ref)
        for f in files:
            was, now = set(show(base, f)), show(ref, f)
            if remote:  # a line both sides have stays one line
                was |= set(show(onto, f))
            if not now:
                continue
            if f == files[0] and folds:
                now = _splice(now, folds, blocks)
            text = '\n'.join(l if l in was else _renote(l, tid, new) if isinstance(l, _Kept)
                             else pat.sub(lambda m: moved[m.group(1)], l) for l in now) + '\n'
            blob = g('hash-object', '-w', '--stdin', input=text).stdout.strip()
            g('update-index', '--cacheinfo', f'100644,{blob},{f}')
        for k in folds:  # the long form the branch wrote for a folded one would name a task that is not there
            was = plan_rel(f'{P.TASKS}/{k}.md')
            if git('rev-parse', '-q', '--verify', f'{ref}:{was}', cwd=cwd).stdout.strip() and \
                    git('cat-file', '-e', f'{base}:{was}', cwd=cwd).returncode:
                g('update-index', '--force-remove', was)
                log(f'{tid}: dropped {was}, the long form of {k}, folded into {folds[k]}')
        for k, v in new.items():  # the long form the branch wrote for it goes with it
            was, now = rel(f'{P.TASKS}/{k}.md'), rel(f'{P.TASKS}/{v}.md')
            blob = git('rev-parse', '-q', '--verify', f'{ref}:{was}', cwd=cwd).stdout.strip()
            if blob and git('cat-file', '-e', f'{base}:{was}', cwd=cwd).returncode:
                g('update-index', '--force-remove', was)
                g('update-index', '--add', '--cacheinfo', f'100644,{blob},{now}')
        tree = g('write-tree').stdout.strip()
        pairs = ', '.join(f'{k} -> {v}' for k, v in new.items())
        into = ', '.join(f'{k} into {v}' for k, v in folds.items())
        said = '; '.join(([f'renumber {pairs} ({onto} already uses the id)'] if new else [])
                         + ([f'fold {into} ({onto} has the same follow-up)'] if folds else []))
        c = g('commit-tree', tree, '-p', ref, '-m', f'{tid}: {said}').stdout.strip()
    finally:
        idx.unlink(missing_ok=True)
    if not c:
        log_(f'{tid}: could not renumber {", ".join([*doubled, *folds])}; the merge may drop or double a task')
        return ref
    if new:
        text = f'{tid}: renumbered {pairs}: {onto} gave the id to another task meanwhile'
        if held is not None:
            held.append(lambda: log_(text))
        else:
            log_(text)
            note(f'{tid}: renumbered {pairs} before the merge')
    if folds:
        log(f'{tid}: folded {into}: {onto} has the same follow-up, filed by another slot meanwhile; '
            'noted there instead of adding it again')
        note(f'{tid}: folded {into} before the merge')
    return c


def renumber_upstream(d: Path, up: str, tid: str) -> None:
    """Before `d` merges in the remote's `up`: the tasks this side added under an id `up` uses for another task
    get a new one (`renumber_doubles`), in a commit on `d`'s HEAD. What is pushed keeps its id."""
    ref = renumber_doubles('HEAD', up, tid, d, remote=True)
    if ref != 'HEAD' and (r := git('merge', '-q', '--ff-only', ref, cwd=d)).returncode:
        log(f'{tid}: the renumbering does not apply in {d}; two tasks may have one id: {r.stderr.strip()[:200]}')


def renumber_plan(c, d: Path, up: str) -> list:
    """`renumber_upstream` for plan commits taken in outside a run's merge (B829): `d` is project `c`'s main checkout
    or its `[plan] repo` clone. When a new commit on `d`'s HEAD renumbers some, the calls to make once the merge holds; else []."""
    for a, b in (('HEAD', up), (up, 'HEAD')):
        if not git('merge-base', '--is-ancestor', a, b, cwd=d).returncode:
            return []  # not diverged: nothing can clash
    held: list = []
    ref = renumber_doubles('HEAD', up, 'plan', d, remote=True, at=c, held=held)
    if ref == 'HEAD':
        return []
    if (r := git('merge', '-q', '--ff-only', ref, cwd=d)).returncode:
        _plan_log(c, f'plan: the renumbering does not apply in {d}; two tasks may have one id: {r.stderr.strip()[:200]}')
        return []
    return held


def _plan_log(c, msg: str) -> None:
    """`msg` for whoever edits the plan (stderr: a plan command's stdout is its answer) and in project `c`'s run.log."""
    print(f'! {msg}', file=sys.stderr)
    try:
        with open(c.notes('run.log'), 'a', encoding='utf-8') as f:
            f.write(f'=== {dt.datetime.now().isoformat(timespec="seconds")} {msg}\n')
    except OSError:
        pass


class _Kept(str):
    """A plan line `renumber_doubles` copies from the other side as it is: only its fold notes are renumbered."""


def _renote(line: str, tid: str, new: dict) -> str:
    """A kept line (`_Kept`) with the ids `new` renumbers renamed in the fold notes `tid` added to it, which
    quote the branch's words; the rest of the line is the other side's, whose ids are its own."""
    if not new:
        return line
    pat = re.compile(r'\b(' + '|'.join(map(re.escape, new)) + r')\b')
    head, *notes = line.split(f' — {tid} filed the same as ')
    return head + ''.join(f' — {tid} filed the same as ' + pat.sub(lambda m: new[m.group(1)], n) for n in notes)


def fold_doubles(base: list[str], ref: list[str], onto: list[str], tid: str) -> tuple[dict, dict]:
    """B33: the follow-ups a branch added that `onto` got meanwhile from another slot, as {its id: onto's id},
    and {onto's id: onto's task block with a ` — note` per folded task}.

    `plan add` turns away a follow-up like an open task (`plan.similar`), but in a slot it sees only that
    branch's plan, not what other slots filed and have not merged: two slots that hit the same flaky test file
    it twice, and two sessions do it. So before a merge each task the branch added (its own `tid` aside) is
    held against the open tasks `onto` added since the branch forked, and on a match `similar` calls strong it
    goes into that one as a note. Only those: one already there when the branch forked, `add` showed it, and
    an add made anyway (`--force`) is other work."""
    was = {t for _, _, t, _, _ in P.iter_tasks(base)}
    fresh, starts = [], {}
    for _, box, t, _, i in P.iter_tasks(onto):
        if t.rstrip('.') not in was and box != 'x':
            starts[t.rstrip('.')] = len(fresh)
            fresh += P._item_block(onto, i)
    if not fresh:
        return {}, {}
    folds, blocks = {}, {}
    for _, box, t, rest, i in P.iter_tasks(ref):
        k = t.rstrip('.')
        if k in was or k == tid or box == 'x' or ref[i] in onto:
            continue  # theirs from before, its own task, done, or the very line onto has (git keeps one)
        hits = [h.split(':', 1)[0].rstrip('.') for h in P.similar(ref[i], ls=onto, limit=len(onto))]
        if not (j := next((h for h in hits if h in starts), None)):  # all of onto's open tasks weigh the words
            continue
        body = P.prose(re.sub(r'^\s*- \[.\] \*\*[^*]+\*\*\s*', '', ref[i])).strip()
        b = blocks.get(j) or fresh[starts[j]:starts[j] + len(P._item_block(fresh, starts[j]))]
        blocks[j] = b[:-1] + [b[-1] + f' — {tid} filed the same as {k} (folded at the merge): '
                              f'{body[:200]}{"…" if len(body) > 200 else ""}']
        folds[k] = j
    return folds, blocks


def _splice(ls: list[str], folded: dict, blocks: dict) -> list[str]:
    """Plan lines `ls` with each folded task's block (`fold_doubles`) swapped for the block of the task it went
    into, noted, at the first one's place: `plan.merge3` then keeps one task with the notes."""
    out, put, i = [], set(), 0
    while i < len(ls):
        m = P.ITEM.match(ls[i])
        k = m.group(3).rstrip('.') if m and not m.group(1) else None
        if k not in folded:
            out.append(ls[i])
            i += 1
            continue
        if folded[k] not in put:
            put.add(folded[k])
            out += [_Kept(l) for l in blocks[folded[k]]]
        i += len(P._item_block(ls, i))
    return out


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
    if not (r := git('merge', '--no-edit', '-m', msg, ref, cwd=d, **task_env(tid))).returncode:
        return []
    if files := git('diff', '--name-only', '--diff-filter=U', cwd=d).stdout.split():
        return files
    if git('rev-parse', '-q', '--verify', 'MERGE_HEAD', cwd=d).returncode:
        log(f'git refused to merge {ref} in {d}: {(r.stderr or r.stdout or "").strip()[-500:]}', tid=tid)
        return None
    git('commit', '-q', '--no-edit', cwd=d)
    return []


def joined(files: list[str], tid: str, d: Path) -> bool:
    """Every conflicted file in `d` is one the runner may join, and joining them worked: committed."""
    if not (all(map(joinable, files)) and union(files, tid, d)):
        return False
    git('commit', '-q', '--no-edit', cwd=d)
    return True


def common_dir(d: Path) -> Path | None:
    """The real path of `d`'s git common dir (the repo it belongs to), or None when it is no git folder."""
    r = git('rev-parse', '--path-format=absolute', '--git-common-dir', cwd=d)
    return Path(r.stdout.strip()).resolve() if not r.returncode and r.stdout.strip() else None


def own_worktree(d: Path) -> bool:
    """`d` is a worktree of this repo (BUG2). A folder from another copy of the repo (its .git points
    elsewhere) has none of this repo's task branches: it is logged, dropped from that repo's worktree list
    and removed, so the caller adds it again from this one."""
    from agent_runner import state as S
    if not d.is_dir():
        return False
    theirs, ours = common_dir(d), common_dir(S.ROOT)
    if theirs is None or ours is None or theirs == ours:
        return True
    log(f'{d} belongs to another copy of the repo ({theirs}), not {ours}: dropped and added again from this one')
    if git('worktree', 'remove', '--force', str(d), cwd=theirs.parent if theirs.name == '.git' else theirs).returncode:
        import shutil
        shutil.rmtree(d, ignore_errors=True)
    return False
