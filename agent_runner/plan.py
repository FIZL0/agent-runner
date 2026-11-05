"""The task list as a *tool*, not a file an agent reads whole.

A long project is hundreds of small tasks spread over months, and the agent doing them starts from
nothing every session. If the backlog is a file, every session pays for the whole file — and the one that
re-reads it on every turn pays again. So the backlog is a command instead:

    ./run plan                   index of plan/TODO.md: every heading and task id, one line each
    ./run plan next              the first open task, with its sub-items
    ./run plan <ID>              a task's full text: plan/tasks/<ID>.md, else its line in TODO.md or DONE.md
    ./run plan <name>            a heading's section (case-insensitive substring) in the plan files
    ./run plan -f FILE <name>    the same, on any other markdown file
    ./run plan brief <ID>        everything a task starts from, in one shot (see `brief`)
    ./run plan tick <ID>         done: [x], and the line moves to plan/DONE.md
    ./run plan block <ID> [--after X,Y] WHY   [~] with "BLOCKED: (after X, Y) WHY" appended
    ./run plan unblock <ID> [NOTE]   reopen: [ ], drop "BLOCKED: …", append NOTE (what unblocked it)
    ./run plan move <ID> WHERE   WHERE = top | before ID | after ID | in SECTION (its end); sub-items follow
    ./run plan add PREFIX TEXT [--pri LEVEL] [--force] [@ WHERE]   new "- [ ] **<next free id>** TEXT"; prints
                                 the id. Refused (exit 3, nothing written) when an open task looks like the
                                 same work: `plan note` it there, or --force when it is different work
    ./run plan drop <ID> WHY     not done but not wanted (a duplicate, overtaken): archived with "dropped: WHY"
    ./run plan kinds             what each id letter means ([plan] kinds): an id's prefix says the kind of work
    ./run plan note <ID> TEXT    append " — TEXT" to the task (user details, priority reasons)
    ./run plan newid PREFIX      the next free id, e.g. L -> L7; a task's id gives its next subtask, L3 -> L3a
    ./run plan archive           move every [x] line left in TODO.md to DONE.md (after merges, hand edits)
    ./run plan reopen            unblock every task whose BLOCKED (after X, Y) tasks are all done now
    ./run plan claims            [plan] repo: which run has which task, and since when (STALE: no refresh in 3 h)
    ./run plan unclaim <ID>      drop a claim, whoever's: for a run that crashed or was switched off

**Where `add` files a task.** A person's task goes to the top of the leading section, as before. A task
given a `--pri` (and every follow-up a running agent files, which is `normal` unless it says) is tagged
`(follow-up, LEVEL)` and filed by its level, so the work a person queued always comes first:

    critical   the top of the leading section, behind earlier critical ones: it breaks or blocks other work
    normal     `### Follow-ups`, made after the person's sections (before Stretch/Parked): the usual follow-up
    low        the same section, behind every normal one: a check, a small tidy-up, a nice-to-have
    later      `### Parked`, which a run never starts: big future work for a person to schedule

`@ WHERE` still overrides the place (the tag stays).

**A subtask keeps its parent's place.** `add P17 …` (a task's id as the prefix: a split of that task) files
P17a after P17 and its earlier subtasks, under P17's own tag or none, with no level of its own unless `--pri`
gives one: the rest of a person's task stays where the person queued it, not behind every follow-up.

The line format is `- [ ] **ID** text → files… | t: tests | j: journal-dir`, under `###` headings, and the
checkbox is `[ ]` open, `[x]` done, `[~]` blocked.

**A block that only waits on another task says which**, as `BLOCKED: (after X, Y) why`, and `reopen` (which a
`./run run` calls after every merge) puts it back to `[ ]` the moment X and Y are done. Without that a task
blocked on "P36 is not merged yet" stays blocked long after P36 lands, because nothing reads prose. `block` fills the list in by itself
from the open task ids its WHY names, so a session that forgets `--after` still gets one.

**Design rule: checkboxes are only ever changed through this tool.** Never hand-edit a `- [ ]` in TODO.md or
DONE.md. Ticking by hand is how a task ends up done in one file and open in another, how a `(after X)`
dependency silently stops being satisfied, and how two parallel agents both pick the same task. `tick` is one
transaction: mark it, mirror the mark into `plan/tasks/<ID>.md`, move the block to DONE.md under the same heading.

Everything here is plain text and atomic: a temp file plus `os.replace`, and a file whose content did not
change is not rewritten at all (so mtimes stay meaningful and git stays quiet).
"""
from __future__ import annotations

import difflib
import os
import re
import shlex
import subprocess
import sys
from collections import Counter
from functools import partial
from pathlib import Path

from agent_runner import plansync
from agent_runner.config import cfg
from agent_runner.gitops import git

PROG = './run plan'  # the name in messages; a wrapper sets its own ('./kit plan')
# The library API a wrapping project may call; names and signatures here change only in a major version.
__all__ = ['PROG', 'HELP', 'lines', 'index', 'section', 'ensure', 'archive', 'tick', 'block', 'reopen',
           'unblock', 'move', 'next_id', 'add', 'similar', 'note', 'drop', 'next_task', 'files_on_line', 'overlap', 'brief', 'open_ids',
           'write_atomic', 'child', 'subtasks', 'main', 'PRI', 'kinds', 'check_kind']

ITEM = re.compile(r'^(\s*)- \[(.)\] \*\*([^\s*]+)')
HEAD = re.compile(r'(#+) ')
# A path-ish token on a task line: `src/main.c`, `crates/sim/src/lib.rs`, `runner.toml`, `docs/api.md`,
# `play/*.rs`. Anything with a dot and a short extension; checked against the repo before it is believed.
FILE_TOKEN = re.compile(r'(?<![\w/.`-])([\w.*-]+(?:/[\w.*-]+)*\.[A-Za-z][\w+]{0,5}|[\w.-]+(?:/[\w.-]+)*/\*\*?)')
BARE_MAX = 5  # a bare file name in a task's text matching more tracked paths than this names none of them
JOURNAL_MAX = 12000  # chars of the newest journal file pasted into a brief; the rest is a Read away


# --- reading ------------------------------------------------------------------

def lines(path) -> list[str]:
    """A file's lines; [] when there is no such file."""
    if not os.path.exists(path):  # exists() is a stat() that says False on any OSError
        return []
    with open(path, encoding='utf-8', errors='replace') as f:
        return f.read().splitlines()


def _level(line: str) -> int:
    m = HEAD.match(line)
    return len(m.group(1)) if m else 0


def _item_block(ls: list[str], i: int) -> list[str]:
    """A task line plus every more-indented line under it (its sub-items and continuations)."""
    indent = len(ITEM.match(ls[i]).group(1))
    j = i + 1
    while j < len(ls) and ls[j].strip() and (len(ls[j]) - len(ls[j].lstrip())) > indent:
        j += 1
    return ls[i:j]


def index(path) -> list[str]:
    """Headings and task ids only — the whole backlog in a screenful, whatever its size."""
    out = []
    for line in lines(path):
        if _level(line):
            out.append(line)
        elif m := ITEM.match(line):
            out.append(f'{m.group(1)}[{m.group(2)}] {m.group(3)}')
    return out


def section(path, name: str) -> list[str]:
    """One named part of a markdown file: the first open task (`next`), a task by id, or a heading's section."""
    ls = lines(path)
    if name == 'next':
        for i, line in enumerate(ls):
            m = ITEM.match(line)
            if m and m.group(2) == ' ' and not m.group(1):
                return _item_block(ls, i)
        return []
    for i, line in enumerate(ls):
        m = ITEM.match(line)
        if m and m.group(3).rstrip('.') == name:
            return _item_block(ls, i)
    for i, line in enumerate(ls):
        lv = _level(line)
        if lv and name.lower() in line.lower():
            j = i + 1
            while j < len(ls) and not (0 < _level(ls[j]) <= lv):
                j += 1
            return ls[i:j]
    return []


def _find(ls: list[str], tid: str) -> int:
    for i, line in enumerate(ls):
        m = ITEM.match(line)
        if m and not m.group(1) and m.group(3).rstrip('.') == tid:
            return i
    raise SystemExit(f'{PROG}: no task {tid!r} ({PROG} for the index)')


# --- writing ------------------------------------------------------------------

def write_atomic(path, text: str) -> None:
    """Replace a file in one step (a temp file beside it, then `os.replace`): several processes of one run
    read the task list at once, and a truncate-then-write has a window where it is empty."""
    path = Path(path)
    tmp = path.with_name(f'.{path.name}.{os.getpid()}.tmp')
    try:
        tmp.write_text(text, encoding='utf-8')
        if path.exists():
            os.chmod(tmp, path.stat().st_mode & 0o777)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _write(path, ls: list[str]) -> None:
    """Atomic (see `write_atomic`), and a no-op when nothing changed."""
    path = str(path)
    text = '\n'.join(ls).rstrip('\n') + '\n'
    try:
        if open(path, encoding='utf-8').read() == text:
            return
    except OSError:
        pass
    write_atomic(path, text)


def _mark(ls: list[str], i: int, box: str) -> None:
    ls[i] = re.sub(r'^(\s*)- \[.\]', rf'\1- [{box}]', ls[i])


def ensure(todo=None, done=None) -> tuple[str, str]:
    """Paths of TODO.md / DONE.md, created with a heading if a fresh checkout has neither."""
    if todo is None:
        c = cfg()
        todo, done = c.todo, done or c.done
    todo = str(todo)
    done = str(done or Path(todo).with_name('DONE.md'))  # DONE.md beside the TODO.md it archives
    os.makedirs(os.path.dirname(todo) or '.', exist_ok=True)
    if not os.path.exists(todo):
        _write(todo, ['# TODO — open tasks, in order', '', '### Next', ''])
    if not os.path.exists(done):
        _write(done, [f'# DONE — the archive (`{PROG} tick <ID>` puts them here)', ''])
    return todo, done


SPLIT = re.compile(r'\(split into ([^)]*)\)')


def child(parent: str, tid: str) -> bool:
    """P17 -> P17a, P11k -> P11k1: the parent's id plus a character of the other kind (so P170 is not P17's)."""
    rest = tid[len(parent):]
    return tid.startswith(parent) and bool(rest) and rest[0].isdigit() != parent[-1].isdigit()


def subtasks(tid: str, line: str, ids) -> set[str]:
    """A split parent's subtasks among `ids`: its children by id, and any its `(split into …)` names."""
    named = {t for m in SPLIT.findall(line) for t in TASK_ID.findall(m)}
    return {t for t in ids if t != tid and (child(tid, t) or t in named)}


def _close_parents(ls: list[str], dl: list[str]) -> None:
    """Tick each `(split into …)` parent whose subtasks are all done (in DONE.md, or ticked here). Only a
    parent that says it was split: a task whose ids merely look like children is left to its own session."""
    boxes = {m.group(3).rstrip('.'): m.group(2) for m in map(ITEM.match, dl + ls) if m and not m.group(1)}
    for i, l in enumerate(ls):
        m = ITEM.match(l)
        if m and not m.group(1) and m.group(2) != 'x' and SPLIT.search(l):
            kids = subtasks(m.group(3).rstrip('.'), l, boxes)
            if kids and all(boxes[k] == 'x' for k in kids):
                _mark(ls, i, 'x')


def archive(todo, done) -> int:
    """Move every top-level [x] task (with its sub-lines) from todo into done, under the same ### heading;
    a split parent goes too once its subtasks are all done.

    Needed because a session or a human sometimes ticks by hand, and a merge then brings that tick in
    without moving the line. Running it is always safe.
    """
    ls, dl, sec, moved = list(lines(todo)), list(lines(done)), '', 0
    if not dl:
        dl = ['# DONE — the archive', '']
    _close_parents(ls, dl)
    i = 0
    while i < len(ls):
        if _level(ls[i]):
            sec = ls[i]
        m = ITEM.match(ls[i])
        if not (m and not m.group(1) and m.group(2) == 'x'):
            i += 1
            continue
        block = _item_block(ls, i)
        del ls[i:i + len(block)]
        if i < len(ls) and not ls[i].strip() and i and not ls[i - 1].strip():
            del ls[i]  # don't leave a double blank line behind
        h = sec or '### (no section)'
        if h not in dl:
            dl += ['', h, '']
        j = dl.index(h) + 1
        while j < len(dl) and not _level(dl[j]):
            j += 1
        while j - 1 > 0 and dl[j - 1].strip() == '':
            j -= 1
        dl[j:j] = block
        moved += 1
    if moved:
        _write(done, dl)
        _write(todo, ls)
    return moved


def tick(tid: str, todo=None, done=None, plan_dir=None) -> int:
    """Mark a task done everywhere it is written down, in one go, and archive it."""
    todo, done = ensure(todo, done)
    plan_dir = str(plan_dir or os.path.dirname(todo))
    ls = list(lines(todo))
    if sum(1 for l in ls if (m := ITEM.match(l)) and not m.group(1) and m.group(3).rstrip('.') == tid) > 1:
        raise SystemExit(f'{PROG}: {tid} is listed twice, as two different tasks; give one a new id '
                         f'(`{PROG} newid`) before ticking, or the other is archived with it')
    _mark(ls, _find(ls, tid), 'x')
    _write(todo, ls)
    own = long_form(plan_dir, tid)
    if os.path.exists(own):
        _write(own, [re.sub(rf'^(\s*)- \[[ ~]\] \*\*{re.escape(tid)}\b', rf'\1- [x] **{tid}', l)
                     for l in lines(own)])
    return archive(todo, done)


def drop(tid: str, why: str, todo=None, done=None) -> int:
    """Close a task nobody will do (a duplicate, work another task overtook): noted, then archived as ticked,
    so its id stays used and what waits on it reopens. """
    note(tid, f'dropped: {why}', todo=todo)
    return tick(tid, todo, done)


TASKS = 'tasks'  # a task's long form is <plan dir>/tasks/<ID>.md, so the top level stays TODO.md and overviews


def long_form(plan_dir, tid: str) -> Path:
    """The task's long form: <plan dir>/tasks/<ID>.md. A plan from before 0.9 keeps it at <plan dir>/<ID>.md,
    which still counts until it is moved (`git mv`)."""
    new, old = Path(plan_dir) / TASKS / f'{tid}.md', Path(plan_dir) / f'{tid}.md'
    return old if old.exists() and not new.exists() else new


TASK_ID = re.compile(r'\b([A-Z]+\d+[a-z0-9]*)\b')
WAITS = re.compile(r'BLOCKED: \(after ([^)]*)\)')


def open_ids(ls: list[str]) -> set[str]:
    """Ids of the top-level tasks in `ls` that are not done: open or blocked."""
    return {m.group(3).rstrip('.') for l in ls if (m := ITEM.match(l)) and not m.group(1) and m.group(2) != 'x'}


def block(tid: str, why: str, todo=None, after=None) -> None:
    """[~] plus "BLOCKED: why". The why must say what would unblock it, or the next session just re-reads it.

    `after` is the tasks it waits on; `reopen` unblocks it once they are all done. Left as None it is read
    off `why`: every task id named there that is still open, other than this task and its own subtasks.
    Pass [] for a block that waits on no task (a human, a tool, a capture).
    """
    todo, _ = ensure(todo)
    ls = list(lines(todo))
    i = _find(ls, tid)
    if after is None:
        live = open_ids(ls)
        after = [t for t in dict.fromkeys(TASK_ID.findall(why))
                 if t in live and t != tid and not t.startswith(tid)]
    _mark(ls, i, '~')
    end = i + len(_item_block(ls, i)) - 1
    ls[end] += ' BLOCKED: ' + (f'(after {", ".join(after)}) ' if after else '') + why
    _write(todo, ls)


def reopen(todo=None) -> list[tuple[str, list[str]]]:
    """Unblock every [~] task whose `BLOCKED: (after …)` tasks are all done. Returns (id, those ids).

    "Done" is "not open in TODO.md": ticked, archived, or dropped. A task blocked twice keeps only its last
    BLOCKED, so it is that one's list that counts.
    """
    todo, _ = ensure(todo)
    ls = list(lines(todo))
    live, out = open_ids(ls), []
    for i, l in enumerate(ls):
        m = ITEM.match(l)
        if not (m and not m.group(1) and m.group(2) == '~'):
            continue
        tail = ls[i + len(_item_block(ls, i)) - 1]
        w = WAITS.findall(tail)
        ids = [t.strip() for t in w[-1].split(',') if t.strip()] if w else []
        if ids and not set(ids) & live:
            out.append((m.group(3).rstrip('.'), ids))
    for tid, ids in out:
        unblock(tid, f'reopened: {", ".join(ids)} landed', todo=todo)
    return out


def unblock(tid: str, note: str = '', todo=None) -> None:
    todo, _ = ensure(todo)
    ls = list(lines(todo))
    i = _find(ls, tid)
    _mark(ls, i, ' ')
    end = i + len(_item_block(ls, i)) - 1
    ls[end] = ls[end].split(' BLOCKED: ')[0] + (f' — {note}' if note else '')
    _write(todo, ls)


def _place(ls: list[str], where: str, ref: str | None) -> int:
    """Index to insert a top-level item at: top (first task of the leading section), bottom (its last),
    before/after ID, or in SECTION (at its end)."""
    if where == 'top':
        h = next((i for i, l in enumerate(ls) if _level(l) and 'next' in l.lower()), None)
        if h is None:
            h = next((i for i, l in enumerate(ls) if _level(l) == 3), None)
        if h is None:
            h = next((i for i, l in enumerate(ls) if _level(l)), -1)
        i = h + 1
        while i < len(ls) and not ITEM.match(ls[i]) and not _level(ls[i]):
            i += 1
        return i
    if where == 'bottom':
        i = j = _place(ls, 'top', None)
        while j < len(ls) and not _level(ls[j]):
            j += 1
        while j > i and ls[j - 1].strip() == '':
            j -= 1
        return j
    if where in ('before', 'after'):
        if not ref:
            raise SystemExit(f'{PROG}: {where} needs a task id')
        i = _find(ls, ref)
        return i if where == 'before' else i + len(_item_block(ls, i))
    if where == 'in':
        h = next((i for i, l in enumerate(ls) if _level(l) and (ref or '').lower() in l.lower()), None)
        if h is None:
            raise SystemExit(f'{PROG}: no section {ref!r}')
        j = h + 1
        while j < len(ls) and not (0 < _level(ls[j]) <= _level(ls[h])):
            j += 1
        while j - 1 > 0 and ls[j - 1].strip() == '':
            j -= 1
        return j
    raise SystemExit(f'{PROG}: where must be top | bottom | before ID | after ID | in SECTION, not {where!r}')


def move(tid: str, where: str, ref: str | None = None, todo=None) -> None:
    todo, _ = ensure(todo)
    ls = list(lines(todo))
    i = _find(ls, tid)
    blk = _item_block(ls, i)
    del ls[i:i + len(blk)]
    j = _place(ls, where, ref)
    ls[j:j] = blk
    _write(todo, ls)


def next_id(prefix: str, paths=None) -> str:
    """The next free id with this prefix, counting DONE.md too: ids are permanent and never reused. A task's own id
    gives its next subtask (P17 -> P17a, P17a -> P17a1), which the runner keeps from running beside its family."""
    if paths is None:
        paths = list(ensure())
    if prefix[-1:].isdigit():
        k = [m.group(1) for p in paths for l in lines(p)
             if (m := re.match(rf'\s*- \[.\] \*\*{re.escape(prefix)}([a-z])\b', l))]
        return prefix + chr(ord(max(k, default='`')) + 1)
    n = [int(m.group(1)) for p in paths for l in lines(p)
         if (m := re.match(rf'\s*- \[.\] \*\*{re.escape(prefix)}(\d+)\b', l))]
    return f'{prefix}{max(n, default=0) + 1}'


PRI = ('critical', 'normal', 'low', 'later')  # a follow-up's level, most urgent first
PRI_TAG = re.compile(r'\(follow-up, (' + '|'.join(PRI) + r')\)')
FOLLOW_UPS, PARKED = 'Follow-ups', 'Parked'  # the sections `add` makes for levels normal/low and later
# Sections a run never starts tasks from (a heading starting with one of these)
SKIPPED = ('Stretch', PARKED)
# The id letters when a repo names none in [plan] kinds: kinds of work any project has
KINDS = {'B': 'bug: something that worked, or should, is broken', 'F': 'feature: new behaviour',
         'T': 'tests and tooling: the gate, scripts, CI, the build', 'D': 'docs',
         'R': 'research: find out, measure or check; no product change', 'C': 'cleanup: refactor, remove, tidy'}


def kinds() -> tuple[dict[str, str], bool]:
    """What each id prefix means, and whether the repo set them (then `add` refuses any other prefix)."""
    k = cfg().raw['plan'].get('kinds') or {}
    return (dict(k), True) if k else (KINDS, False)


def check_kind(prefix: str) -> str | None:
    """Why `prefix` is the wrong id letter, or None. A task's own id (P17 -> P17a) is a subtask, always fine."""
    if prefix[-1:].isdigit():
        return None
    k, own = kinds()
    if prefix in k:
        return None
    listing = '\n  '.join(f'{p}  {m}' for p, m in k.items())
    return (f'{PROG}: {prefix!r} is not a kind of task here; pick the letter for the kind of work '
            f'(or a task id, for a subtask):\n  {listing}') if own else None


def add_default() -> str | None:
    """The level `plan add` files a task at when none is given: a running agent's follow-up is `normal`, behind
    the work a person queued; a person's own task (None) goes to the top."""
    return 'normal' if os.environ.get('AGENT_RUNNER') == '1' else None


def _section_end(ls: list[str], h: int) -> int:
    """Index after the last non-blank line of the section headed at ls[h]."""
    j = h + 1
    while j < len(ls) and not (0 < _level(ls[j]) <= _level(ls[h])):
        j += 1
    while j - 1 > h + 1 and ls[j - 1].strip() == '':  # keep the blank line under the heading
        j -= 1
    return j


def _heading(ls: list[str], name: str) -> int | None:
    return next((i for i, l in enumerate(ls) if _level(l) == 3 and l[4:].strip().startswith(name)), None)


def _make_section(ls: list[str], name: str, before: tuple[str, ...]) -> int:
    """Index of the `### name` heading, made before the first of the `before` sections (else at the end)."""
    h = _heading(ls, name)
    if h is not None:
        return h
    at = min((i for b in before if (i := _heading(ls, b)) is not None), default=len(ls))
    while at > 0 and ls[at - 1].strip() == '':
        at -= 1
    ls[at:at] = ['', f'### {name}', ''] + ([''] if at < len(ls) else [])
    return at + 1


def _place_pri(ls: list[str], pri: str) -> int:
    """Index to file a follow-up of level `pri` at (see the module doc); may add its section to `ls`."""
    if pri == 'critical':
        i = _place(ls, 'top', None)
        while i < len(ls) and ITEM.match(ls[i]) and (t := PRI_TAG.search(ls[i])) and t.group(1) == 'critical':
            i += len(_item_block(ls, i))
        return i
    if pri == 'later':
        return _section_end(ls, _make_section(ls, PARKED, ()))
    h = _make_section(ls, FOLLOW_UPS, SKIPPED)
    end = _section_end(ls, h)
    if pri == 'normal':  # before the first low one
        return next((i for i in range(h + 1, end) if (m := ITEM.match(ls[i])) and not m.group(1)
                     and (t := PRI_TAG.search(ls[i])) and t.group(1) == 'low'), end)
    return end


def family_end(prefix: str, todo=None) -> tuple[str, str | None] | None:
    """For a subtask prefix (a task id open in TODO.md): the last id of its family, the parent and its
    subtasks, which a new subtask files after, and the parent's level tag; None when no such task is open."""
    if not prefix[-1:].isdigit():
        return None
    todo, _ = ensure(todo, None)
    last, tag = None, None
    for l in lines(todo):
        m = ITEM.match(l)
        if m and not m.group(1) and m.group(2) != 'x':
            t = m.group(3).rstrip('.')
            if t == prefix:
                last, tag = t, (PRI_TAG.search(l) or [None, None])[1]
            elif last and re.fullmatch(rf'{re.escape(prefix)}[a-z]\w*', t):
                last = t
    return (last, tag) if last else None


def add(prefix: str, text: str, where: str | None = None, ref: str | None = None, todo=None, done=None,
        pri: str | None = None) -> str:
    """File a new task; with `pri` it is tagged `(follow-up, pri)` and, unless `where` says, filed by its level."""
    if pri is not None and pri not in PRI:
        raise SystemExit(f'{PROG}: --pri must be one of {" | ".join(PRI)}, not {pri!r}')
    todo, done = ensure(todo, done)
    tid = next_id(prefix, [todo, done])
    ls = list(lines(todo))
    if pri and not PRI_TAG.search(text):
        text = f'(follow-up, {pri}) {text}'
    j = _place_pri(ls, pri) if pri and not where else _place(ls, where or 'top', ref)
    ls[j:j] = [f'- [ ] **{tid}** {text}']
    _write(todo, ls)
    return tid


# Words too common in any task line to say two tasks are about the same thing.
_STOP = set('''about after again along also another anything around because before being below between could
does doing each every first from have here into itself just keeps like makes means might more most much never
only other over same should since some still such than that their them then there these they this those
through today under until what when where which while with without would your'''.split())


def _words(text: str) -> set[str]:
    """The words of a task's text before its file list: no ids, no dated user quotes' brackets."""
    text = text.split('→')[0].split('| t:')[0]
    text = re.sub(r'\*\*[^*]+\*\*|\([^)]*\d{4}-\d\d-\d\d[^)]*\)', ' ', PRI_TAG.sub(' ', text))
    return {w for w in re.findall(r'[a-z][a-z-]{3,}', text.lower()) if w not in _STOP}


def _files(text: str) -> set[str]:
    text = text.split('| t:')[0]
    return {f.rstrip('.,;:') for f in FILE_TOKEN.findall(text.partition('→')[2] or text)}


def similar(text: str, todo=None, skip: str | None = None, limit: int = 3) -> list[str]:
    """Open or blocked tasks that look like the same work as `text`, best first, as 'ID: start of its text'.

    Shown when a task is added, so a duplicate is caught before an agent spends a session on it. Kept quiet
    unless the match is strong, since every line lands in an agent's context: the new task's rarer words
    (weighted by how few tasks use them) mostly also on the other, or a fair share of them plus a file that
    few open tasks name."""
    import math
    todo, _ = ensure(todo)
    tasks = [(m.group(3), l) for l in lines(todo)
             if (m := ITEM.match(l)) and not m.group(1) and m.group(2) != 'x' and m.group(3) != skip]
    if not tasks:
        return []
    docs = [(tid, _words(l), _files(l)) for tid, l in tasks]
    df = Counter(w for _, ws, _ in docs for w in ws)  # how many tasks use each word
    hub = Counter(f for _, _, fs in docs for f in fs)  # and name each file
    n = len(docs)
    weight = lambda w: math.log((n + 1) / (df[w] + 1))
    ws, fs = _words(text), _files(text)
    total = sum(weight(w) for w in ws)
    if not total:
        return []
    hits = []
    for (tid, w2, f2), (_, line) in zip(docs, tasks):
        score = sum(weight(w) for w in ws & w2) / total
        rare = any(hub[f] <= 3 for f in fs & f2)
        if score >= 0.5 or (rare and score >= 0.3):
            hits.append((score, tid, line))
    hits.sort(key=lambda h: -h[0])
    out = []
    for _, tid, line in hits[:limit]:
        body = re.sub(r'^\s*- \[.\] \*\*[^*]+\*\*\s*', '', line).split('→')[0].strip()
        out.append(f'{tid}: {body[:90]}{"…" if len(body) > 90 else ""}')
    return out


def note(tid: str, text: str, todo=None) -> None:
    todo, _ = ensure(todo)
    ls = list(lines(todo))
    i = _find(ls, tid)
    ls[i + len(_item_block(ls, i)) - 1] += f' — {text}'
    _write(todo, ls)


# --- what a session starts from ----------------------------------------------

def next_task(todo=None) -> str | None:
    """The id of the first open task, or None."""
    todo, _ = ensure(todo)
    blk = section(todo, 'next')
    return ITEM.match(blk[0]).group(3).rstrip('.') if blk else None


def files_on_line(text: str, root=None, tracked=None) -> list[str]:
    """Repo paths named on a task line, resolved against the repo. Also used by `./run run` in mode `d`
    to keep two running agents off the same files, so the matching lives here, once. `tracked`: the repo's
    paths (`_tracked`), when the caller reads them once for many lines."""
    root = Path(root or cfg().root)
    text = text.split('| t:')[0]
    names = list(dict.fromkeys(FILE_TOKEN.findall(text)))
    # what follows `→` is the task's file list by the line format, so a new top-level file counts there;
    # the list ends with its line (a brief appends the task's long form, whose prose is no list)
    listed = set(FILE_TOKEN.findall(text.partition('→')[2].split('\n')[0])) if '→' in text else set()
    tracked = _tracked(root) if tracked is None else tracked
    out = []
    for n in names:
        n = n.rstrip('.,;:')
        if '*' in n:  # `play/*.rs`, `play/**` on a line mean every file there
            import fnmatch
            # the pattern itself too: files it names that this checkout lacks (made on another branch) still overlap
            out += [t for t in tracked if fnmatch.fnmatch(t, f'*{n}')] + [n]
            continue
        hits = [t for t in tracked if t == n or t.endswith('/' + n)]
        if '/' not in n and n not in listed and len(hits) > BARE_MAX:
            continue  # prose about a kind of file (`README.md`, `mod.json`), not one of the task's files
        # A path that does not exist yet is still the task's file: half the backlog creates its files, and
        # `brief` wants to say "missing — this task creates it" rather than quietly listing nothing. Only
        # names that look like paths or follow the `→`, though, or prose about `fpu.rs` becomes a file the
        # runner reserves.
        out += hits or ([n] if '/' in n or n in listed or (root / n).exists() else [])
    return list(dict.fromkeys(out))


def overlap(a: set[str], b: set[str]) -> set[str]:
    """Paths and patterns (`dir/**`, `dir/*.rs`) of `a` that meet `b`'s: equal, or one matching the other."""
    import fnmatch
    pa, pb = [x for x in a if '*' in x], [y for y in b if '*' in y]  # few: only patterns need fnmatch
    return (a & b) | {x for x in pa for y in b if fnmatch.fnmatch(y, x)} | {
        x for x in a for y in pb if fnmatch.fnmatch(x, y)}


def _tracked(root) -> list[str]:
    """Every tracked path, from git; a filesystem walk when this isn't a git checkout (tests, a fresh copy)."""
    try:
        r = git('ls-files', cwd=root, timeout=20)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.split()
    except (OSError, subprocess.SubprocessError):
        pass
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ('.git', 'target', 'node_modules', '__pycache__')]
        for f in filenames:
            out.append(os.path.relpath(os.path.join(dirpath, f), root).replace(os.sep, '/'))
    return out


def brief(tid: str, root=None, plan_dir=None, journal=None) -> list[str]:
    """Everything a task starts from, in one command.

    This is the highest-value thing in the module. A fresh session otherwise spends its first five or six
    turns finding the task line, looking for a `plan/tasks/<ID>.md`, hunting the journal directory, opening the
    files and running `git log` on them — all of it predictable, all of it paid for again on every turn after.
    `brief` assembles it once:

      * the task's own line (and sub-items) from TODO.md or DONE.md,
      * `plan/tasks/<ID>.md` in full, if the task has a long form,
      * its journal directory: the file list, and the newest entry pasted in (capped at JOURNAL_MAX chars,
        because the newest entry is where the last session said whose move it is),
      * the files named on the line: where they actually are, how long they are, and their last 3 commits —
        so the session knows whether someone changed them yesterday before it reads a single one — and,
        with `[plan] outline` (a command; {file} is the path), each file's outline: the map of what is
        where, so a session reads the part it needs instead of paging through the file to find it,
      * and the output of `[plan] brief_extra` (a command; {id} is the task), for what only the project
        knows how to find.

    `./run run` pastes this into the agent's first turn. A project whose own tool already writes a brief
    (one that also sets things up for the session, say) names it in `[plan] brief`, and its output is
    the brief instead.
    """
    c = cfg(root)
    root = c.root
    if cmd := c.raw['plan']['brief']:
        r = subprocess.run(cmd.format(id=tid), shell=True, cwd=str(root), capture_output=True, text=True)
        if r.returncode:
            raise SystemExit(f'{PROG}: `{cmd.format(id=tid)}` failed: {r.stderr.strip()[:300]}')
        return r.stdout.rstrip().splitlines()
    plan_dir = Path(plan_dir or c.plan_dir)
    journal = Path(journal) if journal else c.journal
    paths = [plan_dir / 'TODO.md', plan_dir / 'DONE.md']
    line = next((o for p in paths if (o := section(p, tid))), [])
    if not line:
        raise SystemExit(f'{PROG}: no task {tid!r} in {plan_dir}/TODO.md or DONE.md')
    text = '\n'.join(line)
    out = [f'## Task {tid} ({plan_dir.name}/TODO.md)', *line]
    own = long_form(plan_dir, tid)
    own_rel = f'{plan_dir.name}/{own.relative_to(plan_dir).as_posix()}'
    if own.exists():
        out += ['', f'## {own_rel}', *lines(own)]
        text += '\n' + '\n'.join(lines(own))

    # journals: the ones the line points at (`j: <dir>`) and any whose name carries this id
    named = re.findall(r'\bj: ([\w.-]+)', text)
    try:
        dirs = sorted(d for d in os.listdir(journal) if (journal / d).is_dir()) if journal else []
    except OSError:
        dirs = []
    own_j = [d for d in dirs if d == tid or re.search(rf'-{re.escape(tid.lower())}(-|$)', d.lower())]
    for j in dict.fromkeys(named + own_j) if journal else ():  # `j:` on a line with no journal dir set
        d = journal / j
        if not d.is_dir():
            continue
        # entries: its .md files and those one folder down (an `id` layout's repeat attempts, <date>-<slug>/)
        files = sorted(p.relative_to(d).as_posix() for p in [*d.glob('*.md'), *d.glob('*/*.md')])
        rel = os.path.relpath(d, root).replace(os.sep, '/')
        out += ['', f'## Journal {rel}/: {" · ".join(files)}']
        if files and j in own_j:  # journals the line only points at are listed, not pasted
            newest = max(files, key=lambda f: (m[0] if (m := DATE.search(f)) else '', f))  # dated beats undated
            body = (d / newest).read_text(encoding='utf-8', errors='replace')
            cut = len(body) > JOURNAL_MAX
            out += [f'### {newest}' + (f' (first {JOURNAL_MAX} chars)' if cut else ''),
                    body[:JOURNAL_MAX].rstrip()]

    where = [p for p in files_on_line(text, root) if p != own_rel and '*' not in p]
    if where:
        out += ['', '## Files on the line, and their last commits']
        for t in where:
            log = git('log', '-3', '--format=%h %ad %s', '--date=short', '--', t, cwd=root).stdout.strip().splitlines()
            try:
                n_lines = sum(1 for _ in open(root / t, encoding='utf-8', errors='replace'))
                size = f'{n_lines} lines'
            except OSError:
                size = 'missing — this task creates it'
            out += [f'- `{t}` ({size})', *[f'  - {l[:120]}' for l in log]]
            if (cmd := c.raw['plan']['outline']) and size[0].isdigit():
                out += outline(cmd, t, root)
    if cmd := c.raw['plan']['brief_extra']:  # what only the project knows: its oracle names, a spec, …
        r = subprocess.run(cmd.format(id=tid), shell=True, cwd=str(root), capture_output=True, text=True)
        if extra := (r.stdout.rstrip() or (f'({cmd} failed: {r.stderr.strip()[:200]})' if r.returncode else '')):
            out += ['', *extra.splitlines()]
    return out


DATE = re.compile(r'\d{4}-\d{2}-\d{2}')
OUTLINE_MAX = 6000  # chars of one file's outline in a brief


def outline(cmd: str, path: str, root) -> list[str]:
    """`[plan] outline` for one file, indented under its entry in the brief; a failure says so in one line."""
    cmd = cmd.format(file=shlex.quote(path))
    try:
        r = subprocess.run(cmd, shell=True, cwd=str(root), capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return [f'  (outline: `{cmd}` ran past 60 s)']
    if r.returncode or not r.stdout.strip():
        return [f'  (outline: `{cmd}` failed: {r.stderr.strip()[:150]})'] if r.returncode else []
    text = r.stdout.rstrip()
    cut = f'  … (outline cut at {OUTLINE_MAX} chars)' if len(text) > OUTLINE_MAX else ''
    return ['  outline:', *(f'    {l}' for l in text[:OUTLINE_MAX].splitlines()), *([cut] if cut else [])]


# --- merging --------------------------------------------------------------------
#
# Merged as text, a task list goes wrong in ways nothing after the merge can undo for certain: two edits
# beside each other conflict, a union keeps both sides, and a moved heading comes out twice or a task one
# side ticked comes back open. `merge3` merges what the file is made of, each part against the base:
# sections by heading, tasks by id wherever they moved, and the parts of a task's line (its box, its
# text, each ` — note`, its BLOCKED) one by one. git runs it as the merge of the task list and its
# archive (`install_driver`), so a merge, a rebase or a pull gets it, the runner's and anybody's.

DRIVER = 'agent-runner-plan'
SEG = re.compile(r'(?= — | BLOCKED: )')  # where a task line's parts start: `note` and `block` append these
BOX = re.compile(r'^(\s*- \[)(.)(\] )(.*)$')


def _parse(ls: list[str]) -> list[tuple]:
    """[(section key, heading line, [(item key, lines)])], the lines above the first heading first (key
    None). A top-level task is one item, its block with it, keyed ('t', id, n); any other line is keyed
    ('l', section key, text, n), the nth such text in its section, so a blank line has a place too."""
    secs: list[tuple] = [(None, None, [])]
    heads, seen = Counter(), Counter()
    i = 0
    while i < len(ls):
        l = ls[i]
        if _level(l):
            heads[l] += 1
            secs.append(((l, heads[l]), l, []))
            i += 1
            continue
        m = ITEM.match(l)
        if m and not m.group(1):
            b = _item_block(ls, i)
            tid = m.group(3).rstrip('.')
            seen[tid] += 1
            secs[-1][2].append((('t', tid, seen[tid]), b))
            i += len(b)
            continue
        seen[(secs[-1][0], l)] += 1
        secs[-1][2].append((('l', secs[-1][0], l, seen[(secs[-1][0], l)]), [l]))
        i += 1
    return secs


def _kept(k, o: dict, b: dict, t: dict) -> bool:
    """Whether a part stays: one in the base stays while both sides kept it (a side that dropped it, as a
    tick drops a task from the list, wins over an edit on the other); one the base lacks, while a side
    brought it in."""
    return (k in o and k in t) if k in b else (k in o or k in t)


def _order(want: set, o: list, b: list, t: list) -> list:
    """`want` in order: ours, unless only theirs re-sorted what all three have; what the other side brought
    in or moved goes after the part before it there, past what the first side added in the same place."""
    keep = set(o) & set(t)
    common = [k for k in b if k in keep]
    co, ct = [k for k in o if k in set(common)], [k for k in t if k in set(common)]
    first, other = (t, o) if co == common and ct != common else (o, t)
    out = [k for k in first if k in want]
    have, mine, bs = set(out), set(other), set(b)
    for i, k in enumerate(other):
        if k not in want or k in have:
            continue
        j = next((out.index(p) + 1 for p in reversed(other[:i]) if p in have), 0)
        while j < len(out) and out[j] not in mine and out[j] not in bs:
            j += 1
        out.insert(j, k)
        have.add(k)
    return out + [k for k in want if k not in have]


def _resolve(b: list[str], o: list[str], t: list[str]) -> list[str]:
    """One stretch both sides changed: ours, less what theirs dropped, with what theirs brought in where its
    first drop was (an edited part keeps its place), else after."""
    new, out, put = [x for x in t if x not in b and x not in o], [], False
    for x in o:
        if x in b and x not in t:
            out += [] if put else new
            put = True
        else:
            out.append(x)
    return out if put else out + new


def _merge_parts(o: list[str], b: list[str], t: list[str]) -> list[str]:
    """A three-way merge of a list of parts (a line's notes, a task's sub-lines): between the parts all
    three keep, each stretch is the side that changed it, or with both, `_resolve`'s join of the two."""
    def kept(x):
        sm = difflib.SequenceMatcher(None, b, x, autojunk=False)
        return {i: j for a, j0, n in sm.get_matching_blocks() for i, j in zip(range(a, a + n), range(j0, j0 + n))}
    mo, mt = kept(o), kept(t)
    out, i, j, k = [], 0, 0, 0
    for s in [*(s for s in range(len(b)) if s in mo and s in mt), len(b)]:
        js, ks = (mo[s], mt[s]) if s < len(b) else (len(o), len(t))
        bc, oc, tc = b[i:s], o[j:js], t[k:ks]
        out += tc if oc == bc else oc if tc == bc or oc == tc else _resolve(bc, oc, tc)
        out += b[s:s + 1]
        i, j, k = s + 1, js + 1, ks + 1
    return out


def _pick(o, b, t, theirs: bool):
    """One value both sides may have changed: the side that changed it, or with both, theirs for the
    branch's own task, else ours."""
    return t if o == b else o if t == b else t if theirs else o


def _merge_line(o: str, b: str, t: str, theirs: bool) -> str:
    if o == b or o == t:
        return t
    if t == b:
        return o
    mo, mb, mt = BOX.match(o), BOX.match(b), BOX.match(t)
    if not (mo and mb and mt):
        mo = mb = mt = None
    po, pb, pt = (SEG.split(m.group(4) if m else l) for m, l in ((mo, o), (mb, b), (mt, t)))
    head = _pick(po[0], pb[0], pt[0], theirs)  # the task's own words: one side's, never both
    text = head + ''.join(_merge_parts(po[1:], pb[1:], pt[1:]))
    if not mo:
        return text
    return mo.group(1) + _pick(mo.group(2), mb.group(2), mt.group(2), theirs) + mo.group(3) + text


def _merge_block(o: list[str], b: list[str], t: list[str], theirs: bool) -> list[str]:
    if len(o) == len(b) == len(t):
        return [_merge_line(*ls, theirs) for ls in zip(o, b, t)]
    return [_merge_line(o[0], b[0], t[0], theirs), *_merge_parts(o[1:], b[1:], t[1:])]


def _moves(base: list[tuple], side: list[tuple]) -> dict:
    """{base section key: where `side` put most of its tasks}, for each section `side` no longer has (a
    renamed heading): a task the other side filed under the old heading goes to the new one."""
    at = {k: s for s, _, items in side for k, _ in items}
    out = {}
    for s, _, items in base:
        if s is None or any(s == x for x, _, _ in side):
            continue
        went = Counter(at[k] for k, _ in items if k[0] == 't' and k in at)
        if went:
            out[s] = went.most_common(1)[0][0]
    return out


def merge3(ours: list[str], base: list[str], theirs: list[str], own: str | None = None) -> list[str] | None:
    """The task list `ours` and `theirs` make from `base`, or None when both rewrote the same prose (the
    lines between tasks), which needs somebody to read it. `own` is the task the merged branch did: where
    both sides changed the same part of its line, the branch's wins; everywhere else the target's does."""
    if ours == theirs or theirs == base:
        return list(ours)
    if ours == base:
        return list(theirs)
    O, B, T = _parse(ours), _parse(base), _parse(theirs)
    so, sb, st = ({s: h for s, h, _ in X} for X in (O, B, T))
    io, ib, it = ({k: (s, ls) for s, _, items in X for k, ls in items} for X in (O, B, T))

    def prose(X, s):
        return {k for k, (x, ls) in X.items() if k[0] == 'l' and x == s and ls[0].strip()}

    for s in {**so, **sb, **st}:
        do, dt = prose(io, s) ^ prose(ib, s), prose(it, s) ^ prose(ib, s)
        if do and dt and do != dt:
            return None
    for k in [k for k in io if k in it and k not in ib and io[k][1] != it[k][1]]:  # one id, two new tasks
        it = {(k[0], k[1], ('theirs', k[2])) if x == k else x: v for x, v in it.items()}  # keep both
    mo, mt = _moves(B, O), _moves(B, T)
    for X, mv in ((io, mo), (it, mt)):  # a renamed section's own lines are still the base's: one key for both
        back = {(n, x, c): (s, x, c) for s, n in mv.items() for _, s_, x, c in [k for k in ib if k[0] == 'l'] if s_ == s}
        for k in [k for k in X if k[0] == 'l' and k[1:] in back]:
            X[('l', *back[k[1:]])] = X.pop(k)
    lines, place = {}, {}
    for k in {**io, **it}:
        if not _kept(k, io, ib, it):
            continue
        lo, lb, lt = (X[k][1] if k in X else None for X in (io, ib, it))
        mine = k[0] == 't' and k[1] == own
        if lo is None or lt is None:
            lines[k] = lo or lt
        elif lb is None:
            lines[k] = lo
        else:
            lines[k] = _merge_block(lo, lb, lt, mine)
        so_, sb_, st_ = (X[k][0] if k in X else None for X in (io, ib, it))
        s = so_ if st_ is None or (so_ is not None and so_ != sb_) else st_
        if s in sb and s not in so and s in mo:  # filed under a heading ours renamed: under the new one
            s = mo[s]
        elif s in sb and s not in st and s in mt:  # or one theirs renamed
            s = mt[s]
        place[k] = s
    heads = {**sb, **so, **st}
    want = {s for s in heads if _kept(s, so, sb, st)} | set(place.values())
    out = []
    for s in _order(want, list(so), list(sb), list(st)):
        if heads[s] is not None:
            out.append(heads[s])
        here = {k for k, x in place.items() if x == s}
        seq = lambda X: [k for k, (x, _) in X.items() if {**mt, **mo}.get(x, x) == s]  # a renamed one by its new name
        for k in _order(here, seq(io), seq(ib), seq(it)):
            out += lines[k]
    return out


def carry_notes(done: list[str], base: list[str], sides: list[list[str]]) -> list[str]:
    """`done` (a merged DONE.md) with each ` — note` a side's TODO.md added to a task the other side ticked: the
    tick wins in TODO.md (`_kept`), and git merges DONE.md apart from it, so the note would go with the line."""
    def tops(ls):
        return {m.group(3).rstrip('.'): l for l in ls if (m := ITEM.match(l)) and not m.group(1)}
    was, out = tops(base), list(done)
    for i, l in enumerate(out):
        m = ITEM.match(l)
        if not (m and not m.group(1)) or (tid := m.group(3).rstrip('.')) not in was:
            continue
        old = set(SEG.split(was[tid])[1:])
        for side in sides:
            for part in SEG.split(tops(side).get(tid, ''))[1:]:
                if part.startswith(' — ') and part not in old and part not in out[i]:
                    out[i] += part
    return out


def merge_file(base: str, ours: str, theirs: str) -> int:
    """git's merge driver (%O %A %B): the merged task list into `ours`. When `merge3` can't merge it, git's
    own text merge, and 1 with its conflict marks when that conflicts too. The branch's task is
    AGENT_RUNNER_TASK when the runner merges."""
    read = lambda p: Path(p).read_text(encoding='utf-8', errors='replace')
    o, b, t = read(ours), read(base), read(theirs)
    got = merge3(o.splitlines(), b.splitlines(), t.splitlines(), os.environ.get('AGENT_RUNNER_TASK') or None)
    if got is None:
        r = subprocess.run(['git', 'merge-file', '-L', 'ours', '-L', 'base', '-L', 'theirs', ours, base, theirs])
        return 0 if r.returncode == 0 else 1
    Path(ours).write_text('\n'.join(got) + ('\n' if o.endswith('\n') or not o else ''), encoding='utf-8')
    return 0


def install_driver(cwd, rels: list[str]) -> None:
    """Make `merge_file` git's merge for `rels` (paths from the top of the repository at `cwd`): the driver
    in the repository's config, the paths in its info/attributes, both shared by every worktree and never
    committed. Run again it changes nothing, unless the runner moved (another interpreter)."""
    from agent_runner.config import runner_cmd
    g = partial(git, cwd=cwd)
    r = g('rev-parse', '--path-format=absolute', '--git-common-dir')
    if r.returncode:
        return
    cmd = shlex.join([*runner_cmd(), 'merge-plan']) + ' %O %A %B'
    if g('config', f'merge.{DRIVER}.driver').stdout.strip() != cmd:
        g('config', f'merge.{DRIVER}.name', 'agent-runner: a task list merged by section and task')
        g('config', f'merge.{DRIVER}.driver', cmd)
    att = Path(r.stdout.strip()) / 'info' / 'attributes'
    have = att.read_text(encoding='utf-8').splitlines() if att.exists() else []
    if missing := [w for w in (f'/{p} merge={DRIVER}' for p in rels) if w not in have]:
        att.parent.mkdir(parents=True, exist_ok=True)
        att.write_text('\n'.join(have + missing) + '\n', encoding='utf-8')


# --- the command ---------------------------------------------------------------

HELP = __doc__ + """
Ids are permanent: `tick` moves a line to DONE.md but never renumbers, and `newid`/`add` count DONE.md too,
so a finished id is never handed out again. That matters because journal directories, commit messages and
`(after X)` dependencies all name tasks by id.
"""


def _commit(root: Path, paths: list[Path], msg: str) -> None:
    """A plan edit made by hand in the main checkout commits at once: the runner lands a merge only once no
    uncommitted edit there touches a file it changes, and nearly every merge changes TODO.md. Worktrees (the
    agents') commit through `done`; mid-merge the edit stays uncommitted for whoever is merging."""
    g = partial(git, cwd=root)
    gd, cd = (g('rev-parse', '--path-format=absolute', f).stdout.strip() for f in ('--git-dir', '--git-common-dir'))
    if gd and gd == cd and not os.path.exists(os.path.join(gd, 'MERGE_HEAD')):
        g('add', '--', *map(str, paths))  # a fresh plan/ is untracked, and commit -- PATH skips those
        g('commit', '-q', '-m', f'plan: {msg}', '--', *map(str, paths))


EDITS = ('tick', 'block', 'reopen', 'unblock', 'move', 'add', 'note', 'archive', 'drop')


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ('-h', '--help', 'help'):
        print(HELP)
        return 0
    c = cfg()
    if not c.plan_external:
        return _main(argv, c)
    edit = argv[:1] and argv[0] in EDITS
    with plansync.locked(c):  # a read pulls too, so it sees other people's edits
        plansync.pull(c, force=bool(edit))
        return _main(argv, c)


def _main(argv: list[str], c) -> int:
    plan_dir = c.plan_dir
    todo, done = ensure()

    def say(msg):
        print(msg)
        if argv[0] in EDITS:
            if c.plan_external:
                if out := plansync.publish(c, ' '.join(argv)[:70]):
                    print(out, file=sys.stderr)
            elif argv[0] != 'archive':
                _commit(c.root, [todo, done], ' '.join(argv)[:70])
        return 0

    if argv[:1] == ['tick'] and len(argv) == 2:
        n = tick(argv[1])
        return say(f'ticked {argv[1]}' + (f', moved {n} line(s) to {plan_dir.name}/DONE.md' if n else ''))
    if argv[:1] == ['drop'] and len(argv) > 2:
        drop(argv[1], ' '.join(argv[2:]))
        return say(f'dropped {argv[1]}')
    if argv[:1] == ['block'] and len(argv) > 2:
        after, rest = None, argv[2:]
        if rest[0] == '--after' and len(rest) > 2:
            after, rest = [t for t in rest[1].split(',') if t], rest[2:]
        block(argv[1], ' '.join(rest), after=after)
        return say(f'blocked {argv[1]}')
    if argv == ['reopen']:
        got = reopen()
        return say('\n'.join(f'reopened {t} ({", ".join(ids)} landed)' for t, ids in got) or 'nothing to reopen')
    if argv[:1] == ['unblock'] and len(argv) > 1:
        unblock(argv[1], ' '.join(argv[2:]))
        return say(f'unblocked {argv[1]}')
    if argv[:1] == ['move'] and len(argv) > 2:
        move(argv[1], argv[2], ' '.join(argv[3:]) or None)
        return say(f'moved {argv[1]} {" ".join(argv[2:])}')
    if argv == ['kinds']:
        k, own = kinds()
        return say('\n'.join(f'{p}  {m}' for p, m in k.items())
                   + ('' if own else '\n(the defaults: set [plan] kinds in runner.toml to name your own)'))
    if argv[:1] == ['add'] and len(argv) > 2:
        rest, pri = argv[2:], add_default()
        if force := '--force' in rest:
            rest = [a for a in rest if a != '--force']
        if given := '--pri' in rest[:-1]:
            k = rest.index('--pri')
            pri, rest = rest[k + 1], rest[:k] + rest[k + 2:]
        if why := check_kind(argv[1]):
            print(why, file=sys.stderr)
            return 2
        text, _, where = ' '.join(rest).partition(' @ ')
        w = where.split(maxsplit=1) or [None]
        if not given and not where and (fam := family_end(argv[1])):
            w, pri = ['after', fam[0]], fam[1]  # a split stays with its parent (module doc)
        fam = argv[1] if re.search(r'\d', argv[1]) else None  # a split is like its parent, by design
        same = [s for s in similar(text) if not (fam and s.split(':')[0].startswith(fam))]
        if same and not force:
            print(f'{PROG}: not added: already open, and may be the same work:\n  ' + '\n  '.join(same)
                  + f'\n`{PROG} note <ID> TEXT` it there; if it is different work, add it again with --force',
                  file=sys.stderr)
            return 3
        tid = add(argv[1], text, w[0], (w[1:] or [None])[0], pri=pri)
        msg = f'added {tid}' + (f' ({pri})' if pri else '')
        if pri == 'critical' and os.environ.get('AGENT_RUNNER') == '1':
            msg += '\ncritical goes ahead of the queued work: its text must say what it breaks or blocks'
        return say(msg)
    if argv[:1] == ['note'] and len(argv) > 2:
        note(argv[1], ' '.join(argv[2:]))
        return say(f'noted {argv[1]}')
    if argv[:1] == ['newid'] and len(argv) == 2:
        return say(next_id(argv[1]))
    if argv[:1] == ['brief'] and len(argv) == 2:
        return say('\n'.join(brief(argv[1])))
    if argv == ['archive']:
        return say(f'archived {archive(todo, done)}')
    if argv == ['claims']:
        got = sorted(plansync.claims(c).items())
        return say('\n'.join(f'{t}  {plansync.label(cl)}' for t, cl in got) or 'no claims')
    if argv[:1] == ['unclaim'] and len(argv) == 2:
        if not plansync.unclaim(c, argv[1]):
            print(f'{PROG}: no claim on {argv[1]}', file=sys.stderr)
            return 1
        return say(f'unclaimed {argv[1]}')

    # a lookup: an id, a section name, or `next`
    paths = [todo, plan_dir / 'REFERENCE.md', plan_dir / 'HUMAN.md', done]
    if c.run['rules']:
        paths.append(c.root / c.run['rules'])
    paths = [str(p) for p in paths if os.path.exists(p)]
    if argv[:1] == ['-f']:
        if len(argv) < 3:
            print(f'{PROG} -f FILE <name>', file=sys.stderr)
            return 2
        paths, argv = [argv[1]], argv[2:]
    task_file = long_form(plan_dir, argv[0]) if argv else None
    if len(paths) > 1 and task_file and task_file.exists():
        out = lines(task_file)
    elif not argv:
        out, cl = index(todo), plansync.claims(c)
        out = [f'{l}  [{plansync.label(cl[t])}]' if (t := l.rsplit(' ', 1)[-1]) in cl else l for l in out]
    else:
        out = next((o for p in paths if (o := section(p, argv[0]))), [])
    if not out:
        print(f'{PROG}: nothing named {argv[0]!r} — run `{PROG}` for the index', file=sys.stderr)
        return 1
    print('\n'.join(out))
    return 0


if __name__ == '__main__':
    sys.exit(main())
