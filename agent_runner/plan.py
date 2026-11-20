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
    ./run plan add PREFIX TEXT [--files A,B] [--after X,Y] [--test T] [--journal D] [--pri LEVEL] [--last] [--force] [@ WHERE]
                                 new "- [ ] **<next free id>** TEXT | files: A, B | after: X, Y …"; prints
                                 the id (warns without --files or --test). Refused (exit 3, nothing written) when an open task looks like the
                                 same work: `plan note` it there, or --force when it is different work.
                                 --last: at the end of Next, with `after: all above` (below)
    ./run plan drop <ID> WHY     not done but not wanted (a duplicate, overtaken): archived with "dropped: WHY";
                                 a slot running it is stopped, its branch deleted unmerged (B19)
    ./run plan restore <ID> [WHERE]   undo a mistaken tick or drop: back from DONE.md as open [ ], same id, text
                                 and fields kept, "dropped: WHY" removed; WHERE as `move` (default: top)
    ./run plan kinds             what each id letter means ([plan] kinds): an id's prefix says the kind of work
    ./run plan note <ID> TEXT    append " — TEXT" to the task (user details, priority reasons)
    ./run plan goal [TEXT]       print the `Goal:` paragraph above TODO.md's first heading; with TEXT replace it
                                 (title, fields-format line, other paragraphs, headings and tasks untouched)
    ./run plan newid PREFIX      the next free id, e.g. L -> L7; a task's id gives its next subtask, L3 -> L3a
    ./run plan archive           move every [x] line left in TODO.md to DONE.md (after merges, hand edits)
    ./run plan reopen            unblock every task whose BLOCKED (after X, Y) tasks are all done now
    ./run plan waiting [--all]   what waits for your OK: concept pages (K tasks: below) and tasks blocked on a
                                 person, each with a label (CONCEPT, CONFIRM, DECIDE, BLOCKED); --all adds the shelved
    ./run plan confirm <ID> [WHAT YOU SAW]   yes / it worked: a CONFIRM is ticked, a DECIDE or BLOCKED reopens
                                 with the answer noted, a concept is approved
    ./run plan change <ID> [--restart] WHAT  do WHAT instead: noted and reopened (a concept: revised); a slot
                                 running it is told "Your task changed: WHAT" in its pane and works on; with
                                 --restart, or no live pane, it is stopped and starts again from the new text
    ./run plan tell <ID> TEXT    type TEXT into the pane of the slot running ID (queued for its next turn); no
                                 plan edit; an error when no slot runs ID
    ./run plan shelve <ID>       later: stays blocked, off Needs you; `unshelve <ID>` brings it back
    ./run plan approve <ID> [CHOICE]   OK a concept (or its build task's id): the build opens, CHOICE noted on it
    ./run plan revise <ID> WHY   changes asked: the concept reopens with WHY noted, its waiting build is dropped
    ./run plan claims            which run has which task (with a remote to claim through), and since when (STALE: no refresh in 3 h),
                                 and any wip/main-checkout-* branches of edits moved aside to land a merge
    ./run plan unclaim <ID>      drop a claim, whoever's: for a run that crashed or was switched off

**Where `add` files a task.** A person's task goes to the top of the leading section, as before. A task
given a `--pri` (and every follow-up a running agent files, which is `normal` unless it says) is tagged
`(follow-up, LEVEL)` and filed by its level, so the work a person queued always comes first:

    critical   the plan's Critical section if it has one, else the top of the leading section, behind
               earlier critical ones: it breaks or blocks other work
    normal     `### Follow-ups`, made after the person's sections (before Stretch/Parked): the usual follow-up
    low        the same section, behind every normal one: a check, a small tidy-up, a nice-to-have
    later      `### Parked`, which a run never starts: big future work for a person to schedule

`@ WHERE` still overrides the place (the tag stays).

**Subtask or fresh id.** `add B646 …` makes B646a, which never runs beside B646 or its other subtasks: use it
only when the work can't start before its parent lands (it needs the parent's code, data or verdict). Work that
merely shares a topic, or came out of that task, gets a fresh letter (`add B …`) so a run starts it in parallel;
`add` notes this whenever it hands out a subtask id.

**Commits.** An edit in the main checkout commits at once (`plan: <command>`); a worktree's waits for `done`.
`AGENT_RUNNER_NOCOMMIT=1` leaves it uncommitted, for a script that commits it with its own change.

**A subtask keeps its parent's place.** `add P17 …` (a task's id as the prefix: a split of that task) files
P17a after P17 and its earlier subtasks, under P17's own tag or none, with no level of its own unless `--pri`
gives one: the rest of a person's task stays where the person queued it, not behind every follow-up. A parent
tagged `later` that was moved out of Parked passes on no tag: a person scheduled it, so its split runs too.

The line format is `- [ ] **ID** text | files: a, b | after: X, Y | test: name | journal: dir`, under `###`
headings, and the checkbox is `[ ]` open, `[x]` done, `[~]` blocked. The keyed fields are the only thing read
off a line: `files:` keeps running tasks apart, `after:` holds a task until those ids are done, `test:`
names the test it adds, `journal:` a journal dir its brief lists. Prose is never parsed for files or ids.

**A task that goes last** (a release) is filed with `add … --last`: at the end of Next, with `after: all above`.
That marker is no list to keep up: the run resolves it on every pick to each task above it in its own section
that is not done (open or blocked), tasks added above it later included, so it starts once the section has
drained. Tasks blocked on a person (CONFIRM, DECIDE, BLOCKED, a concept's OK) do not hold it until they reopen,
and other sections (Follow-ups) never do. `reopen`, `waiting` and `status` say what it still waits on.

**A block that only waits on another task says which**, as `BLOCKED: (after X, Y) why`, and `reopen` (which a
`./run run` calls after every merge) puts it back to `[ ]` the moment X and Y are done. Without that a task
blocked on "P36 is not merged yet" stays blocked long after P36 lands, because nothing reads prose. `block` fills the list in by itself
from the open task ids its WHY names, so a session that forgets `--after` still gets one.

**Concept tasks (kind K) build nothing.** Their session researches the repo and publishes an Artifact page of
2-3 options (what each looks like or does, the files it touches, the trade-off) and a recommendation, then
`done K7 "msg" --artifact URL` (refused without it). That notes the link on K7 and files the build task right
after it, `BLOCKED: waiting for your OK on URL`, which no run starts and `reopen` never frees. A person says
which option; `approve` opens the build with the choice noted, `revise` sends the concept back. A repo whose
`[plan] kinds` lack K has no concepts.

**A task blocked on a person says what it asks**, with a caps label first: `block ID "CONFIRM: watch a phone
for a push"` (check by hand, say what you saw), `"DECIDE: …"` (a question or a choice), `"BLOCKED: …"` (access,
a login, a fix only a person can make). Such a block waits on no task, lists under Needs you (`waiting`,
and `status`/`since`) beside the concept pages, and takes `confirm`, `change` or `shelve`.

**Design rule: checkboxes are only ever changed through this tool.** Never hand-edit a `- [ ]` in TODO.md or
DONE.md. Ticking by hand is how a task ends up done in one file and open in another, how an `after:`
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
           'unblock', 'move', 'next_id', 'add', 'similar', 'note', 'drop', 'next_task', 'files_on_line', 'fields', 'overlap', 'brief', 'open_ids',
           'write_atomic', 'child', 'subtasks', 'main', 'PRI', 'kinds', 'check_kind',
           'concept', 'concept_done', 'waiting', 'approve', 'revise',
           'asking', 'asks', 'confirm', 'change', 'shelve', 'unshelve']

ITEM = re.compile(r'^(\s*)- \[(.)\] \*\*([^\s*]+)')
HEAD = re.compile(r'(#+) ')
KEYS = ('files', 'after', 'test', 'journal')
# ` | key: value` on a task's first line; a value ends at the next field, a note (` — `) or a BLOCKED
FIELD = re.compile(r' \| (' + '|'.join(KEYS) + r'): (.*?)(?= \| (?:' + '|'.join(KEYS) + r'): | — | BLOCKED: |$)')
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


def section(path, name: str, exact: bool = False) -> list[str]:
    """One named part of a markdown file: the first open task (`next`), a task by id, or a heading's section (with
    `exact`, only a heading that is `name` whole, any case)."""
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
        if lv and (name.lower() == line.lstrip('#').strip().lower() if exact else name.lower() in line.lower()):
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


DROPPED = ' — dropped: '


def restore(tid: str, where: str = 'top', ref: str | None = None, todo=None, done=None, plan_dir=None) -> None:
    """Undo a mistaken tick or drop (F47): the task's block goes from DONE.md back to TODO.md as open [ ], same id,
    its text, fields and sub-items kept, less the ` — dropped: WHY` its drop appended; at the top of the leading
    section unless `where` (as `move`) says. A tick made but not archived yet is reopened where it stands."""
    todo, done = ensure(todo, done)
    plan_dir = str(plan_dir or os.path.dirname(todo))
    ls, dl = list(lines(todo)), list(lines(done))
    here = next((i for i, l in enumerate(ls) if (m := ITEM.match(l)) and not m.group(1)
                 and m.group(3).rstrip('.') == tid), None)
    if here is not None and ITEM.match(ls[here]).group(2) != 'x':
        raise SystemExit(f'{PROG}: {tid} is still open in {Path(todo).name}: nothing to restore')
    if here is None:
        try:
            j = _find(dl, tid)
        except SystemExit:
            raise SystemExit(f'{PROG}: no task {tid!r} in {Path(done).name} to restore') from None
        blk = _item_block(dl, j)
        del dl[j:j + len(blk)]
        if j < len(dl) and not dl[j].strip() and j and not dl[j - 1].strip():
            del dl[j]  # don't leave a double blank line behind
        here = _place(ls, where, ref)
        ls[here:here] = blk
    else:
        blk = _item_block(ls, here)
    for k in range(here + len(blk) - 1, here - 1, -1):  # the drop's note is the last one on the block
        if DROPPED in ls[k]:
            ls[k] = ls[k][:ls[k].rindex(DROPPED)]
            break
    _mark(ls, here, ' ')
    _write(todo, ls)
    _write(done, dl)
    own = long_form(plan_dir, tid)
    if os.path.exists(own):
        _write(own, [re.sub(rf'^(\s*)- \[x\] \*\*{re.escape(tid)}\b', rf'\1- [ ] **{tid}', l) for l in lines(own)])


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


LAST = 'all above'  # an `after:` value (`plan add --last`): every task above it in its section not done yet (F43)


def _on_person(ls: list[str], i: int) -> bool:
    """Is the task at ls[i] blocked on a person: a CONFIRM/DECIDE/BLOCKED ask (shelved too) or a concept's OK."""
    m = ITEM.match(ls[i])
    if not m or m.group(2) != '~':
        return False
    tail = ls[i + len(_item_block(ls, i)) - 1]
    at = _block_at(tail)
    t = tail[at:].lstrip() if at >= 0 else ''
    return bool(ASKING.match(t) or WAIT_ANY.match(t))


def above(ls: list[str], i: int) -> list[str]:
    """What `after: all above` on the task at ls[i] stands for, read afresh each time: the top-level tasks above
    it in its own section (back to the nearest heading) that are not done, open or blocked, in order. A task
    blocked on a person (`asks`) does not hold it: a release does not wait on a Windows check nobody has done;
    once the person answers and it reopens, it holds it again. Other sections (Follow-ups) never count."""
    out = []
    for j in range(i - 1, -1, -1):
        if _level(ls[j]):
            break
        m = ITEM.match(ls[j])
        if m and not m.group(1) and m.group(2) != 'x' and not _on_person(ls, j):
            out.append(m.group(3).rstrip('.'))
    return out[::-1]


def waits_on(ls: list[str], i: int) -> list[str]:
    """The ids the task at ls[i] names in its `after:` field, `all above` resolved (`above`), itself left out.
    Done ones included: the caller checks which are still open."""
    tid = ITEM.match(ls[i]).group(3).rstrip('.')
    ids: list[str] = []
    for a in fields(ls[i]).get('after', []):
        ids += above(ls, i) if a == LAST else [a]
    return [t for t in dict.fromkeys(ids) if t != tid]


def last_waits(todo=None) -> list[tuple[str, list[str]]]:
    """(id, the open tasks it still waits on) for every task not done whose `after:` says `all above`, in order."""
    todo, _ = ensure(todo)
    ls = list(lines(todo))
    live = open_ids(ls)
    return [(m.group(3).rstrip('.'), [t for t in waits_on(ls, i) if t in live])
            for i, l in enumerate(ls)
            if (m := ITEM.match(l)) and not m.group(1) and m.group(2) != 'x' and LAST in fields(l).get('after', [])]


def last_lines(todo=None) -> list[str]:
    """'T5 waits on all above: F43, B54 (2 open)' for each `after: all above` task (`reopen`, `waiting`)."""
    return [f'{t} waits on all above: {", ".join(ids)} ({len(ids)} open)' if ids
            else f'{t} waits on all above: nothing left above it'
            for t, ids in last_waits(todo)]


def block(tid: str, why: str, todo=None, after=None) -> None:
    """[~] plus "BLOCKED: why". The why must say what would unblock it, or the next session just re-reads it.

    `after` is the tasks it waits on; `reopen` unblocks it once they are all done. Left as None it is read
    off `why`: every task id named there that is still open, other than this task and its own subtasks.
    Pass [] for a block that waits on no task (a human, a tool, a capture).
    """
    todo, _ = ensure(todo)
    ls = list(lines(todo))
    i = _find(ls, tid)
    why = stamp_ask(why)
    if after is None and asking(why):
        after = []  # it waits on a person (`asks`), not on a task its words happen to name
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
    ls[end] = (_unblocked(ls[end]) if end == i else ls[end].split(' BLOCKED: ')[0]) + (f' — {note}' if note else '')
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
    """Move `tid` and its subtasks with it (P17a, P17a1 … stay right after P17, in their order): a parent moved to
    the top must not leave the rest of its work behind in Parked, where no run starts it."""
    todo, _ = ensure(todo)
    ls = list(lines(todo))
    blk = []
    for t in [tid] + [m.group(3).rstrip('.') for l in ls if (m := ITEM.match(l)) and not m.group(1)
                      and child(tid, m.group(3).rstrip('.'))]:
        i = _find(ls, t)
        got = _item_block(ls, i)
        del ls[i:i + len(got)]
        blk += got
    j = _place(ls, where, ref)
    ls[j:j] = blk
    _write(todo, ls)


def next_id(prefix: str, paths=None, taken=()) -> str:
    """The next free id with this prefix, counting DONE.md too: ids are permanent and never reused. A task's own id
    gives its next subtask (P17 -> P17a, P17a -> P17a1), which the runner keeps from running beside its family.
    `taken`: more ids in use (those `reserved` holds)."""
    if paths is None:
        paths = list(ensure())
    ids = [m.group(1) for p in paths for l in lines(p) if (m := re.match(r'\s*- \[.\] \*\*([^*\s]+)\*\*', l))]
    ids += list(taken)
    if prefix[-1:].isdigit():
        k = [m.group(1) for t in ids if (m := re.fullmatch(rf'{re.escape(prefix)}([a-z])', t.rstrip('.')))]
        return prefix + chr(ord(max(k, default='`')) + 1)
    n = [int(m.group(1)) for t in ids if (m := re.fullmatch(rf'{re.escape(prefix)}(\d+)', t.rstrip('.')))]
    return f'{prefix}{max(n, default=0) + 1}'


RESERVED = 'agent-runner-ids'  # in the repo's git dir: every id `add` (or a renumber) handed out, one a line


def _reserved_file(at) -> Path | None:
    try:
        d = os.path.dirname(os.path.abspath(at)) if os.path.isfile(at) else str(at)
        r = git('rev-parse', '--git-common-dir', cwd=d)
    except (OSError, subprocess.SubprocessError):
        return None
    return (Path(d) / r.stdout.strip()) / RESERVED if not r.returncode and r.stdout.strip() else None


def reserved(at) -> set[str]:
    """The ids handed out in this repo so far, by any checkout: a branch's new tasks sit only on that branch until
    it merges, and once its slot moves on to the next task no checkout shows them, so the next free id is
    counted against this list too, or two branches take the same one and the second is renumbered at its merge."""
    f = _reserved_file(at)
    try:
        return set(f.read_text(encoding='utf-8').split()) if f else set()
    except OSError:
        return set()


def reserve(at, *ids: str) -> None:
    if (f := _reserved_file(at)) and ids:
        try:
            with open(f, 'a', encoding='utf-8') as out:
                out.write(''.join(f'{t}\n' for t in ids))
        except OSError:
            pass


def _other_checkouts(*plan_files) -> list[Path]:
    """The same plan files in the repo's other worktrees (a run's slots, a session's own worktree): `add` counts
    their ids too, so two sessions adding at once don't both take the next free one. Ids added on a branch with
    no checkout left are still renumbered when it merges."""
    try:
        here = Path(git('rev-parse', '--show-toplevel', cwd=os.path.dirname(os.path.abspath(plan_files[0]))
                        ).stdout.strip())
        rels = [Path(os.path.abspath(f)).relative_to(here) for f in plan_files]
        r = git('worktree', 'list', '--porcelain', cwd=here)
    except (OSError, ValueError, subprocess.SubprocessError):
        return []
    trees = [Path(l[9:]) for l in r.stdout.splitlines() if l.startswith('worktree ')]
    return [p for t in trees if t != here for rel in rels if (p := t / rel).is_file()]


PRI = ('critical', 'normal', 'low', 'later')  # a follow-up's level, most urgent first

PRI_TAG = re.compile(r'\(follow-up, (' + '|'.join(PRI) + r')\)')
FOLLOW_UPS, PARKED = 'Follow-ups', 'Parked'  # the sections `add` makes for levels normal/low and later
# Sections a run never starts tasks from (a heading starting with one of these)
SKIPPED = ('Stretch', PARKED)
# The id letters when a repo names none in [plan] kinds: kinds of work any project has
KINDS = {'B': 'bug: something that worked, or should, is broken', 'F': 'feature: new behaviour',
         'T': 'tests and tooling: the gate, scripts, CI, the build', 'D': 'docs',
         'R': 'research: find out, measure or check; no product change', 'C': 'cleanup: refactor, remove, tidy',
         'K': 'concept: nothing is built yet; research the repo and publish an Artifact page of 2-3 options and a '
              'recommendation; the build waits for a person\'s OK'}


def kinds() -> tuple[dict[str, str], bool]:
    """What each id prefix means, and whether the repo set them (then `add` refuses any other prefix)."""
    k = cfg().raw['plan'].get('kinds') or {}
    return (dict(k), True) if k else (KINDS, False)


def _pathish(arg: str) -> bool:
    """An argument that reads as a file path: a slash, a file extension, or a file that exists here."""
    return ' ' not in arg and ('/' in arg or bool(re.search(r'\.[A-Za-z0-9]{1,8}$', arg)) or Path(arg).exists())


def add_args(rest: list[str]) -> tuple[str, str, str, bool, bool]:
    """`plan add`'s arguments after PREFIX → (text, where, keyed fields, given --pri value or '', force), or
    SystemExit(2) with what is wrong (B43): an unquoted `--files dir/*` is expanded by the shell, so its first path
    becomes the value and the rest would be folded into the text. Text is the first argument (one quoted string,
    or bare words before any flag when none reads as a path); any other free argument is refused."""
    text: list[str] = []
    where: list[str] = []
    vals: dict[str, str] = {}
    pri, force, after_flag, in_where, last = '', False, False, False, False

    def no(why: str):
        raise SystemExit(f'{PROG}: not added: {why}\nquote the text and each flag value: '
                         f'{PROG} add KIND "the text" --files \'a,dir/**\' (a bare dir/* is expanded by the shell)')

    k = 0
    while k < len(rest):
        a = rest[k]
        if a == '--force':
            force = True
        elif a == '--last':  # F43: at the end of the leading section, `after: all above`
            last, after_flag, in_where = True, False, False
        elif a == '--pri' or a.lstrip('-') in KEYS and a.startswith('--'):
            if k + 1 >= len(rest) or rest[k + 1].startswith('--'):
                no(f'{a} needs a value')
            if a in vals or (a == '--pri' and pri):
                no(f'{a} given twice')
            if a == '--pri':
                pri = rest[k + 1]
            else:
                vals[a] = rest[k + 1]
            k, after_flag, in_where = k + 1, True, False
        elif a.startswith('--'):
            no(f'unknown flag {a}')
        elif a == '@' and not in_where:
            in_where = True
        elif in_where:
            where.append(a)
        elif after_flag:
            no(f'stray argument {a!r} after a flag value' + (' (a path: was a --files value unquoted?)'
                                                            if _pathish(a) else ''))
        elif text and (' ' in text[0] or _pathish(a)):
            no(f'a second text argument {a!r}: the text is already {text[0]!r}' if ' ' in text[0]
               else f'{a!r} reads as a path, not text')
        else:
            text.append(a)
        k += 1
    if in_where and not where:
        no('@ needs a place (top, bottom, before ID, after ID, in SECTION)')
    if last:
        vals['--after'] = ', '.join(x for x in (vals.get('--after', '').strip(', '), LAST) if x)
    keyed = ''
    for key in KEYS:  # `--files a,b` → ` | files: a, b`, in KEYS order
        if (v := vals.get(f'--{key}')) is not None:
            keyed += f' | {key}: ' + (v if key == 'test' else ', '.join(
                LAST if x == LAST else ', '.join(re.split(r'[,\s]+', x)) for x in re.split(r',\s*', v.strip(', '))))
    t, _, w = ' '.join(text).partition(' @ ')
    return t, ' '.join(where) or w or ('bottom' if last else ''), keyed, pri, force


def check_kind(prefix: str) -> str | None:
    """Why `prefix` is the wrong id letter, or None. A task's own id (P17 -> P17a, MD39b -> MD39b1) is a subtask,
    always fine: one ending in a digit whatever it is, one ending in a letter if it is an open task's id."""
    if prefix[-1:].isdigit():
        return None
    if re.search(r'\d', prefix) and prefix in open_ids(lines(ensure()[0])):
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
    if pri == 'critical':  # a plan's own Critical section, if it has one (it runs beside the ordered work)
        h = next((i for i, l in enumerate(ls) if _level(l) and 'critical' in l.lower()), None)
        if h is not None:  # everything there is critical: in order, at its end
            return _section_end(ls, h)
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
    subtasks, which a new subtask files after, and the parent's level tag; None when no such task is open.
    A parent tagged `later` but moved out of Parked gives no tag: a person scheduled it, so its split runs too."""
    todo, _ = ensure(todo, None)  # a kind letter (B) matches no open id, so it gets None below
    last, tag, sec = None, None, ''
    for l in lines(todo):
        if _level(l) == 3:
            sec = l[4:].strip()
        m = ITEM.match(l)
        if m and not m.group(1) and m.group(2) != 'x':
            t = m.group(3).rstrip('.')
            if t == prefix:
                last, tag = t, (PRI_TAG.search(l) or [None, None])[1]
                if tag == 'later' and not sec.startswith(SKIPPED):
                    tag = None
            elif last and child(prefix, t):  # P17 -> P17a, P17a -> P17a1
                last = t
    return (last, tag) if last else None


def add(prefix: str, text: str, where: str | None = None, ref: str | None = None, todo=None, done=None,
        pri: str | None = None) -> str:
    """File a new task; with `pri` it is tagged `(follow-up, pri)` and, unless `where` says, filed by its level."""
    if pri is not None and pri not in PRI:
        raise SystemExit(f'{PROG}: --pri must be one of {" | ".join(PRI)}, not {pri!r}')
    todo, done = ensure(todo, done)
    tid = next_id(prefix, [todo, done, *_other_checkouts(todo, done)], reserved(todo))
    reserve(todo, tid)
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
    """The words of a task's text, its fields aside: no ids, no dated user quotes' brackets."""
    text = prose(text)
    text = re.sub(r'\*\*[^*]+\*\*|\([^)]*\d{4}-\d\d-\d\d[^)]*\)', ' ', PRI_TAG.sub(' ', text))
    return {w for w in re.findall(r'[a-z][a-z-]{3,}', text.lower()) if w not in _STOP}


def _files(text: str) -> set[str]:
    return set(fields(text).get('files', []))


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
        body = prose(re.sub(r'^\s*- \[.\] \*\*[^*]+\*\*\s*', '', line)).strip()

        out.append(f'{tid}: {body[:90]}{"…" if len(body) > 90 else ""}')
    return out


def note(tid: str, text: str, todo=None) -> None:
    todo, _ = ensure(todo)
    ls = list(lines(todo))
    i = _find(ls, tid)
    ls[i + len(_item_block(ls, i)) - 1] += f' — {text}'
    _write(todo, ls)


# --- the goal paragraph (F24) ------------------------------------------------------------------------------
#
# The text between TODO.md's title line and its first heading or task is the project's preamble: a `Goal:`
# paragraph, the line that explains the keyed fields, sometimes rules. `plan goal` reads and replaces only the
# paragraph that starts with `Goal:`, so a control session can reword a stale goal without a task; the title, the
# fields-format line, other paragraphs, headings and task lines stay byte-identical.

GOAL = re.compile(r'goal:', re.I)


def _goal_span(ls: list[str]) -> tuple[int, int, int]:
    """(start, end, preamble end) of the `Goal:` paragraph in ls; start == end == where a new one goes when
    there is none (after the title line and its blank)."""
    top = 1 if ls and _level(ls[0]) == 1 else 0
    stop = next((k for k in range(top, len(ls)) if _level(ls[k]) or ITEM.match(ls[k])), len(ls))
    k = top
    while k < stop:
        if not ls[k].strip():
            k += 1
            continue
        j = k
        while j < stop and ls[j].strip():
            j += 1
        if GOAL.match(ls[k].lstrip()):
            return k, j, stop
        k = j
    at = top + 1 if top and top < len(ls) and not ls[top].strip() else top
    return at, at, stop


def goal(text: str | None = None, todo=None) -> str:
    """The goal paragraph; with text, replace it (prefixed `Goal: ` when text has no such start) and return it."""
    todo, _ = ensure(todo)
    ls = list(lines(todo))
    a, b, _ = _goal_span(ls)
    if text is None:
        return '\n'.join(ls[a:b])
    text = text.strip()
    if not GOAL.match(text):
        text = f'Goal: {text}'
    new = [l.rstrip() for l in text.splitlines()]
    if a == b:  # a new paragraph: keep a blank line on each side
        before = [''] if a and ls[a - 1].strip() else []
        after = [''] if a >= len(ls) or ls[a].strip() else []
        new = before + new + after
    ls[a:b] = new
    _write(todo, ls)
    return text


# --- concept tasks: an Artifact page of options, and a build that waits for a person's OK ----------------
#
# A K task builds nothing: its session publishes a page of 2-3 options and finishes with `done K7 "msg"
# --artifact URL`. `done` notes the link on K7 and files the build after it, blocked as "waiting for your OK on
# URL" (no `after:`, so `reopen` never frees it). `plan approve K7 "option B: …"` unblocks the build with the
# choice noted; `plan revise K7 WHY` sends the concept back for another round. A repo whose [plan] kinds lack K
# has no concepts: a K-lettered id there is an ordinary task.

CONCEPT = 'K'
WAIT_OK = 'waiting for your OK on '
WAITING = re.compile(r'BLOCKED: ' + re.escape(WAIT_OK) + r'(\S+)')
FROM_CONCEPT = re.compile(r'\bconcept ([A-Z]+\d+[a-z0-9]*)\b')


def concept(tid: str) -> bool:
    """Is `tid` a concept task: its letters are K, and this repo's kinds have K."""
    m = re.match(r'([A-Za-z]+)\d', tid)
    return bool(m) and m.group(1) == CONCEPT and CONCEPT in kinds()[0]


def build_kind() -> str:
    """The id letter a concept's build task gets: F (feature) where the kinds have it, else the first other one."""
    k = kinds()[0]
    return 'F' if 'F' in k else next((p for p in k if p != CONCEPT), 'F')


def title_of(line: str) -> str:
    """A task line's own words: after its `**ID**`, without the fields, the follow-up tag, notes or BLOCKED."""
    t = re.sub(r'^\s*- \[.\] \*\*[^*]+\*\*\s*', '', line.split('\n')[0])
    t = re.split(r' — | BLOCKED: ', t)[0]
    return ' '.join(PRI_TAG.sub('', prose(t)).split())


def concept_done(tid: str, url: str, todo=None, done=None) -> str:
    """Note the concept's page on `tid` and file its build task right after it, blocked until a person approves
    an option. Returns the build task's id. The concept itself is ticked by the caller (`done`)."""
    todo, done = ensure(todo, done)
    ls = lines(todo)
    line = ls[_find(ls, tid)]
    files = fields(line).get('files', [])
    note(tid, f'concept page: {url}', todo=todo)
    text = f'Build the option a person approves on concept {tid}\'s page: {title_of(line)}'
    if files:
        text += ' | files: ' + ', '.join(files)
    bid = add(build_kind(), text, 'after', tid, todo=todo, done=done)
    block(bid, WAIT_OK + url, todo=todo, after=[])
    return bid


def waiting(todo=None, all: bool = False) -> list[tuple[str, str, str, str]]:
    """Build tasks waiting for a person's OK on a concept page: (build id, concept id or '', url, title).
    Shelved ones (`shelve`) only with `all`."""
    todo, _ = ensure(todo)
    ls, out = lines(todo), []
    for i, l in enumerate(ls):
        m = ITEM.match(l)
        if not (m and not m.group(1) and m.group(2) == '~'):
            continue
        tail = ls[i + len(_item_block(ls, i)) - 1]
        if w := (WAIT_ANY if all else WAITING).findall(tail):
            w = [x[-1] if isinstance(x, tuple) else x for x in w]
            k = FROM_CONCEPT.search(l)
            title = re.sub(r'^Build the option a person approves on concept \S+ page: ', '', title_of(l))
            out.append((m.group(3).rstrip('.'), k.group(1) if k else '', w[-1], title))
    return out


def _waiter(tid: str, todo) -> tuple[str, str, str, str]:
    """The waiting build task `tid` names: the build task itself or its concept."""
    for w in waiting(todo, all=True):
        if tid in (w[0], w[1]):
            return w
    raise SystemExit(f'{PROG}: nothing waits for an OK on {tid!r}: `{PROG} waiting` lists what does')


def approve(tid: str, choice: str = '', todo=None) -> str:
    """A person's OK: unblock the build task of concept `tid` (or the build task `tid`) with the choice noted, so
    a run starts it. Returns the build task's id."""
    todo, _ = ensure(todo)
    w = _waiter(tid, todo)
    unblock(w[0], f'approved ({w[2]}): {choice}' if choice else f'approved as recommended on {w[2]}', todo=todo)
    return w[0]


def revise(tid: str, why: str, todo=None, done=None) -> str:
    """Changes asked for: drop the waiting build task and reopen the concept with `why` noted, so its next
    session publishes a new round. Returns the concept's id."""
    todo, done = ensure(todo, done)
    b, k, url, _ = _waiter(tid, todo)
    if not k:
        raise SystemExit(f'{PROG}: {b} names no concept to send back; `{PROG} note` and `{PROG} unblock` it by hand')
    ls, dl = lines(todo), lines(done)
    at = next((i for i, l in enumerate(ls) if (m := ITEM.match(l)) and not m.group(1) and m.group(3) == k), None)
    if at is None:  # archived: move its block back from DONE.md to where the build task stands
        j = _find(dl, k)
        blk = _item_block(dl, j)
        del dl[j:j + len(blk)]
        _write(done, dl)
        i = _find(ls, b)
        ls[i:i] = blk
        at = i
    _mark(ls, at, ' ')
    _write(todo, ls)
    note(k, f'changes asked on {url}: {why}', todo=todo)
    drop(b, f'concept {k} sent back for changes', todo=todo, done=done)
    return k


# --- tasks waiting on a person: "Needs you" (B27; "Waiting for your OK" before) ------------------------------
#
# A block whose why starts with a caps label waits on a person, not on a task: `BLOCKED: CONFIRM: watch a
# phone for a push` (check something by hand and say what you saw), `DECIDE: …` (answer a question or a
# choice), `BLOCKED: …` (access, a login, or a fix only a person can make). An agent files one with
# `done ID "msg" --blocked "CONFIRM: …"`. They list under "Needs you" beside the concept pages
# (label CONCEPT), and take three answers: `confirm` (it worked / what they saw: a CONFIRM is ticked, a DECIDE
# or BLOCKED reopens with the answer noted, a concept is approved), `change` ("do X instead": noted and
# reopened; a concept is revised) and `shelve` (stays blocked, leaves the list until `waiting --all` or
# `unshelve`). A shelved block reads `BLOCKED: shelved: …`.

ASK_LABELS = ('CONFIRM', 'DECIDE', 'BLOCKED')
SHELVED = 'shelved: '
ASKING = re.compile(r'BLOCKED: (shelved: )?(' + '|'.join(ASK_LABELS) + r'): (.*)$')
WAIT_ANY = re.compile(r'BLOCKED: (shelved: )?' + re.escape(WAIT_OK) + r'(\S+)')
URL = re.compile(r'https?://\S+')
CONCEPT_ASK = 'pick an option on the page'


def _block_at(tail: str) -> int:
    """Where a task's last ` BLOCKED: ` starts in its last line (-1 for none), not counting the label of a
    `BLOCKED: BLOCKED: …` or `BLOCKED: shelved: BLOCKED: …`."""
    at = [m.start() for m in re.finditer(' BLOCKED: ', tail)
          if not tail[:m.start()].endswith((' BLOCKED:', ' shelved:'))]
    return at[-1] if at else -1


def asking(why: str) -> bool:
    """Does a block's why wait on a person: it starts with CONFIRM:, DECIDE: or BLOCKED:."""
    return bool(re.match(r'(' + '|'.join(ASK_LABELS) + r'): ', why.strip()))


def asks(todo=None, all: bool = False) -> list[tuple[str, str, str, str, str, str, bool]]:
    """Everything waiting on a person, in TODO.md order: (label, task id, its concept id or '', what to do, link
    or '', the task's title, shelved). Label CONCEPT is a build task waiting on a concept page (`waiting`).
    Shelved ones only with `all`."""
    todo, _ = ensure(todo)
    ls, out = lines(todo), []
    for i, l in enumerate(ls):
        m = ITEM.match(l)
        if not (m and not m.group(1) and m.group(2) == '~'):
            continue
        tid = m.group(3).rstrip('.')
        tail = ls[i + len(_item_block(ls, i)) - 1]
        at = _block_at(tail)
        tail = tail[at:] if at >= 0 else ''
        if w := WAIT_ANY.match(tail.lstrip()):
            k = FROM_CONCEPT.search(l)
            title = re.sub(r'^Build the option a person approves on concept \S+ page: ', '', title_of(l))
            item = ('CONCEPT', tid, k.group(1) if k else '', CONCEPT_ASK, w.group(2), title, bool(w.group(1)))
        elif a := ASKING.match(tail.lstrip()):
            what = ASKED.sub('', a.group(3).split(' — ')[0]).strip()
            u = URL.search(what)
            if u:
                what = ' '.join((what[:u.start()] + what[u.end():]).split()).rstrip(' :,;')
            item = (a.group(2), tid, '', what, u.group(0) if u else '', title_of(l), bool(a.group(1)))
        else:
            continue
        if all or not item[6]:
            out.append(item)
    return out


def _ask(tid: str, todo) -> tuple[str, str, str, str, str, str, bool]:
    """What `tid` (a task waiting on a person, or a concept whose build waits) asks, shelved or not."""
    for a in asks(todo, all=True):
        if tid in (a[1], a[2]):
            return a
    raise SystemExit(f'{PROG}: {tid!r} waits on no answer from you: `{PROG} waiting --all` lists what does')


def confirm(tid: str, said: str = '', todo=None, done=None) -> str:
    """The person's yes ("it worked", or what they saw): a CONFIRM is ticked with it noted, a DECIDE or BLOCKED
    reopens with the answer noted (so a run picks it up), a concept is approved. Returns what happened."""
    todo, done = ensure(todo, done)
    label, t, k, what, _, _, _ = _ask(tid, todo)
    if label == 'CONCEPT':
        return f'approved: {approve(tid, said, todo=todo)} is open now, and a run starts it'
    if label == 'CONFIRM':
        unblock(t, f'confirmed by you ({what}): {said or "it worked"}', todo=todo)
        tick(t, todo=todo, done=done)
        return f'confirmed and ticked {t}'
    unblock(t, f'your answer ({label} {what}): {said or "done"}', todo=todo)
    return f'{t} is open again with your answer noted, and a run starts it'


def change(tid: str, instead: str, todo=None, done=None) -> str:
    """'Do X instead': the task reopens with `instead` noted; a concept is sent back (`revise`)."""
    todo, done = ensure(todo, done)
    try:
        label, t, k, what, _, _, _ = _ask(tid, todo)
    except SystemExit:  # B19: an open task (one a slot may be running) takes a change too: noted, stays open
        ls = list(lines(todo))
        if tid not in open_ids(ls) or ls[_find(ls, tid)].lstrip().startswith('- [~]'):
            raise
        note(tid, f'you said: do this instead: {instead}', todo=todo)
        return f'{tid} has your change noted'
    if label == 'CONCEPT':
        return f'{revise(tid, instead, todo=todo, done=done)} is open again with your changes noted'
    unblock(t, f'you said, on {label} {what}: do this instead: {instead}', todo=todo)
    return f'{t} is open again with your change noted, and a run starts it'


# --- B27: "Needs you": each ask in everyday words, with its age --------------------------------------------
#
# What waits on a person shows under `[needs] heading` ("Needs you") as one plain line each: what is asked and
# what to reply ("Check the push reached your phone - reply yes/no"), its link on a line of its own, oldest
# first with its age. The caps labels stay in TODO.md and in `asks`, for the tools; the person never reads
# them. A block on a person is stamped `(asked YYYY-MM-DD HH:MM)` when it is filed, which is where the age
# comes from (older blocks have none and sort first). A reply that names no id ("yes", "B", "later") is mapped
# to its item by the session the person talks to (control or feed), which then runs confirm, change or
# shelve with that id, and asks the person when it cannot tell which item (C5: no regex guessing here).

ASKED = re.compile(r' ?\(asked (\d{4}-\d\d-\d\d \d\d:\d\d)\)')
REPLY_HINT = {'CONCEPT': 'reply A/B/C', 'CONFIRM': 'reply yes/no', 'DECIDE': 'reply with your answer',
              'BLOCKED': 'reply done once it is'}


def needs_cfg() -> dict:
    """`[needs]`: heading, ages, order (config.DEFAULTS has them all)."""
    try:
        return {'heading': 'Needs you', 'ages': True, 'order': 'oldest', **(cfg().raw.get('needs') or {})}
    except SystemExit:  # outside a repository: the defaults
        return {'heading': 'Needs you', 'ages': True, 'order': 'oldest'}


def stamp_ask(why: str, now=None) -> str:
    """`why` with `(asked <now>)` added when it waits on a person (a caps label, or a concept's OK) and has no
    stamp yet."""
    import datetime as dt
    if ASKED.search(why) or not (asking(why) or why.startswith(WAIT_OK)):
        return why
    return f'{why} (asked {(now or dt.datetime.now()).strftime("%Y-%m-%d %H:%M")})'


def asked_at(todo=None) -> dict[str, str]:
    """{task id: 'YYYY-MM-DD HH:MM'} for each blocked task whose block carries an `(asked …)` stamp."""
    todo, _ = ensure(todo)
    ls, out = lines(todo), {}
    for i, l in enumerate(ls):
        m = ITEM.match(l)
        if not (m and not m.group(1) and m.group(2) == '~'):
            continue
        tail = ls[i + len(_item_block(ls, i)) - 1]
        at = _block_at(tail)
        if at >= 0 and (s := ASKED.search(tail[at:])):
            out[m.group(3).rstrip('.')] = s.group(1)
    return out


def _lower_first(s: str) -> str:
    return s[:1].lower() + s[1:] if s[:2] != s[:2].upper() else s


def plain_ask(label: str, what: str, title: str) -> str:
    """One ask in everyday words, without its caps label: what is asked, then what to reply."""
    if label == 'CONCEPT':
        said = f'Pick an option for {_lower_first(title)}' if title else 'Pick an option on the page'
    else:
        said = (what or title or 'Have a look').rstrip(' .')
        said = re.sub(r'[\s,;:]+(see|at|via|here)$', '', said)  # what led to a link that now has its own line
        said = said[:1].upper() + said[1:]
    return f'{said} - {REPLY_HINT.get(label, "reply when you can")}'


def age(stamp: str, now) -> str:
    """How long ago `stamp` ('YYYY-MM-DD HH:MM') was, short: '5m', '2h', '3d'; '' when it does not parse."""
    import datetime as dt
    try:
        mins = max(0, int((now - dt.datetime.strptime(stamp, '%Y-%m-%d %H:%M')).total_seconds() // 60))
    except (ValueError, TypeError):
        return ''
    return 'now' if mins < 1 else f'{mins}m' if mins < 60 else f'{mins // 60}h' if mins < 48 * 60 else f'{mins // 1440}d'


def in_order(items: list, stamps: dict[str, str], order: str = 'oldest') -> list:
    """`items` (asks tuples, id second) in `[needs] order`: 'oldest' first (unstamped ones are older still),
    'newest' first, or 'plan' (as given: TODO.md's order). The sort is stable, so equal ages keep plan order."""
    if order == 'plan':
        return list(items)
    key = lambda a: stamps.get(a[1], '')
    return sorted(items, key=key, reverse=order == 'newest')


# --- B19: drop or change a task a run's slot is on: the run stops that slot too ------------------------------
#
# `drop` and `change` edit the plan, which a running session never rereads, so on their own the slot's agent
# would work on and its branch could still merge. When a run in this repository is on the task (a slot runs
# it, a cut-off session waits to resume it, or its finished branch waits to merge), the command leaves a
# request in <notes>/halt/<ID>.json ({"how": "drop" | "change"}) and waits up to HALT_WAIT s for the run's
# answer in <notes>/halt/<ID>.done, which it prints. The run (`runner.halts`, every pass of its loop) ends the
# session, deletes task/<ID> here and on the remote, resets the worktree and frees the slot; on a change it
# starts the task again in that slot, from the new text. A drop of a finished branch is never merged.

HALT_WAIT = 30.0  # s `drop`/`change` wait for the run to say what it did


def halt_dir(c) -> Path:
    return c.notes('halt', 'x').parent  # notes() makes the folder


def run_on(c, tid: str) -> str:
    """What a run up in this repository is doing with `tid` ('s2', 'merging'), from its STATE; '' for nothing
    (no run up, or the task is none of its)."""
    import json

    from agent_runner import plat
    if not c.notes('run.lock').exists():
        return ''  # no run was ever up here (and no lock file made just to look)
    if f := plat.lock(c.notes('run.lock')):
        f.close()  # nobody holds it: no run is up
        return ''
    try:
        st = json.loads(c.notes('STATE').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        st = {}
    if n := next((n for n, t in (st.get('running') or {}).items() if t == tid), None):
        return f's{n}'
    try:
        return f's{json.loads(c.notes(f"{tid}.resume").read_text(encoding="utf-8"))["slot"]}'
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return 'merging' if tid in (st.get('merging') or []) else ''


def halt(c, tid: str, how: str, wait: float | None = None) -> str:
    """Ask the run to stop what it does with `tid` (`how`: 'drop' or 'change') and return what it did, or
    what it will do when it has not answered within `wait` s; '' when no run is on the task."""
    import json
    import time
    where = run_on(c, tid)
    if not where:
        return ''
    d = halt_dir(c)
    (d / f'{tid}.done').unlink(missing_ok=True)
    tmp = d / f'{tid}.json.tmp'
    tmp.write_text(json.dumps({'how': how, 'at': time.time()}), encoding='utf-8')
    os.replace(tmp, d / f'{tid}.json')
    end = time.time() + (HALT_WAIT if wait is None else wait)
    while True:
        try:
            said = (d / f'{tid}.done').read_text(encoding='utf-8').strip()
            (d / f'{tid}.done').unlink(missing_ok=True)
            return said
        except OSError:
            pass
        if time.time() >= end:
            break
        time.sleep(0.25)
    if where == 'merging':
        return f'asked the run not to land {tid}: unless its merge is already landing, task/{tid} is deleted unmerged'
    return (f'asked the run to stop {where}: within seconds it ends that session, deletes task/{tid} and its work'
            + (', then starts it again from the new text' if how == 'change' else '')
            + f' (`{c.command} since` shows it)')


# --- F16: tell a running agent something, without stopping it ---------------------------------------------
#
# A slot runs an interactive session in a tmux pane, where text typed while it works queues for its next turn.
# `plan tell ID TEXT` (and `plan change ID TEXT` on a running task, unless --restart) leaves a request in
# <notes>/tell/<ID>.json ({"how": "tell" | "change", "text": …}); the run (`runner.tells`, every pass of its
# loop) finds the slot's pane, pastes the message into it and presses Enter, and answers in
# <notes>/tell/<ID>.done ({"told": true|false, "msg": …}). With no live pane (not tmux, a cut-off session
# waiting to resume, the task merging) it answers told false and `change` falls back to the B19 halt.

TELL_WAIT = 30.0  # s `tell`/`change` wait for the run to pass the message on


def tell_dir(c) -> Path:
    return c.notes('tell', 'x').parent  # notes() makes the folder


def tell_text(how: str, text: str) -> str:
    """What the agent reads in its pane."""
    return f'Your task changed: {text}' if how == 'change' else f'A note on your task, from the person running this run: {text}'


def tell(c, tid: str, text: str, how: str = 'tell', wait: float | None = None) -> tuple[bool | None, str]:
    """Ask the run to type `text` into the pane of the slot running `tid`. (True, 'told s1 (F297)') when it
    did; (False, why) when it could not (no live pane, or no slot of a run runs it: then why is ''); (None,
    what was asked) when the run did not answer within `wait` s."""
    import json
    import time
    where = run_on(c, tid)
    if not where or where == 'merging':
        return False, ''
    d = tell_dir(c)
    (d / f'{tid}.done').unlink(missing_ok=True)
    tmp = d / f'{tid}.json.tmp'
    tmp.write_text(json.dumps({'how': how, 'text': text, 'at': time.time()}), encoding='utf-8')
    os.replace(tmp, d / f'{tid}.json')
    end = time.time() + (TELL_WAIT if wait is None else wait)
    while True:
        try:
            got = json.loads((d / f'{tid}.done').read_text(encoding='utf-8'))
            (d / f'{tid}.done').unlink(missing_ok=True)
            return bool(got.get('told')), str(got.get('msg', ''))
        except (OSError, ValueError):
            pass
        if time.time() >= end:
            break
        time.sleep(0.25)
    return None, f'asked the run to pass it on to {where} ({tid}); it has not answered yet (`{c.command} since` shows it)'


def _shelf(tid: str, on: bool, todo) -> str:
    todo, _ = ensure(todo)
    t = _ask(tid, todo)[1]
    ls = list(lines(todo))
    i = _find(ls, t)
    end = i + len(_item_block(ls, i)) - 1
    at = _block_at(ls[end])
    head, why = ls[end][:at], ls[end][at + len(' BLOCKED: '):]
    if on and not why.startswith(SHELVED):
        why = SHELVED + why
    elif not on and why.startswith(SHELVED):
        why = why[len(SHELVED):]
    ls[end] = f'{head} BLOCKED: {why}'
    _write(todo, ls)
    return t


def shelve(tid: str, todo=None) -> str:
    """'Later': the task stays blocked but leaves Needs you (`waiting --all` still lists it)."""
    return _shelf(tid, True, todo)


def unshelve(tid: str, todo=None) -> str:
    """Back on Needs you."""
    return _shelf(tid, False, todo)


# --- what a session starts from ----------------------------------------------

def next_task(todo=None) -> str | None:
    """The id of the first open task, or None."""
    todo, _ = ensure(todo)
    blk = section(todo, 'next')
    return ITEM.match(blk[0]).group(3).rstrip('.') if blk else None


def fields(line: str) -> dict[str, list[str]]:
    """A task line's keyed fields (`| files: a, b | after: X`), comma lists, read off its first line only (a
    brief appends the long form, whose prose is no field)."""
    return {k: [x for v in re.split(r',\s*', val) if (x := v.strip().strip('`'))]
            for k, val in FIELD.findall(_unblocked(line.split('\n')[0]))}


FIELD_START = re.compile(r' \| (?:' + '|'.join(KEYS) + r'): ')


def _unblocked(line: str) -> str:
    """A task line without the ` BLOCKED: …` that `block` appends. That marker comes after the keyed fields, so
    one the task's prose quotes (before its fields) is kept: only a marker after the first field is cut, or the
    first marker when the line has no field."""
    f = FIELD_START.search(line)
    at = line.find(' BLOCKED: ', f.start() if f else 0)
    return line if at < 0 else line[:at]


def prose(line: str) -> str:
    """A task line without its keyed fields."""
    return FIELD.sub('', line)


def files_on_line(text: str) -> list[str]:
    """The `files:` of a task line: paths and patterns (`dir/**`, `dir/*.rs`). The run keeps two running tasks
    apart by them (`overlap`)."""
    return fields(text).get('files', [])


def overlap(a: set[str], b: set[str]) -> set[str]:
    """Paths and patterns (`dir/**`, `dir/*.rs`) of `a` that meet `b`'s: equal, one a tail of the other
    (`src/menu.rs` is `app/src/menu.rs`), or one matching the other as a pattern."""
    import fnmatch

    def meet(x: str, y: str) -> bool:
        return (x == y or x.endswith('/' + y) or y.endswith('/' + x)
                or ('*' in x and fnmatch.fnmatch(y, f'*{x}')) or ('*' in y and fnmatch.fnmatch(x, f'*{y}')))
    return {x for x in a for y in b if meet(x, y)}


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
    named = fields(text).get('journal', [])
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

    where = [p for p in files_on_line(text) if p != own_rel and '*' not in p]
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
        r = subprocess.run(cmd.format(id=tid), shell=True, cwd=str(root), capture_output=True, text=True,
                           errors='replace')
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
`after:` fields all name tasks by id.
"""


def _commit(root: Path, paths: list[Path], msg: str) -> None:
    """A plan edit made by hand in the main checkout commits at once: the runner lands a merge only once no
    uncommitted edit there touches a file it changes, and nearly every merge changes TODO.md. Worktrees (the
    agents') commit through `done`; mid-merge the edit stays uncommitted for whoever is merging."""
    g = partial(git, cwd=root)
    gd, cd = (g('rev-parse', '--path-format=absolute', f).stdout.strip() for f in ('--git-dir', '--git-common-dir'))
    if os.environ.get('AGENT_RUNNER_NOCOMMIT'):  # the caller commits the edit with its own change
        return
    if gd and gd == cd and not os.path.exists(os.path.join(gd, 'MERGE_HEAD')):
        g('add', '--', *map(str, paths))  # a fresh plan/ is untracked, and commit -- PATH skips those
        g('commit', '-q', '-m', f'plan: {msg}', '--', *map(str, paths))


EDITS = ('tick', 'block', 'reopen', 'unblock', 'move', 'add', 'note', 'archive', 'drop', 'approve', 'revise',
         'confirm', 'change', 'shelve', 'unshelve', 'restore')


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ('-h', '--help', 'help'):
        print(HELP)
        return 0
    c = cfg()
    if argv[:1] == ['tell']:  # F16: no plan edit, so no lock
        return _tell(c, argv[1:])
    restart = False
    if argv[:1] == ['change'] and '--restart' in argv[2:]:
        restart, argv = True, [a for a in argv if a != '--restart']
    edit = argv[:1] and (argv[0] in EDITS or argv[0] == 'goal' and len(argv) > 1)
    if not c.plan_external:
        if not edit:
            return _main(argv, c)  # a read of the checkout's own file needs no lock
        with plansync.locked(c):  # two sessions filing at once would take the same id, and one write drop the other
            rc = _main(argv, c)
    else:
        with plansync.locked(c):  # a read pulls too, so it sees other people's edits
            plansync.pull(c, force=bool(edit))
            rc = _main(argv, c)
    if not rc and argv[0] in ('drop', 'change') and len(argv) > 2:
        # B19: outside the lock, so the run can read the plan while it stops and restarts the slot
        if argv[0] == 'change' and not restart:  # F16: tell the agent instead of stopping it
            told, said = tell(c, argv[1], ' '.join(argv[2:]), 'change')
            if told is not False:
                print(said)
                return rc
            if said:
                print(f'{said}; stopping it and starting it again from the new text instead (as --restart)')
        if said := halt(c, argv[1], argv[0]):
            print(said)
    return rc


def _tell(c, argv: list[str]) -> int:
    """`plan tell ID TEXT`: a note typed into the pane of the slot running ID; the plan is not edited."""
    if len(argv) < 2:
        print(f'{PROG} tell <ID> TEXT', file=sys.stderr)
        return 2
    tid, text = argv[0], ' '.join(argv[1:])
    told, said = tell(c, tid, text)
    if told is False:
        print(f'{PROG}: {said or f"{tid} is not running: no slot of a run here is on it"}'
              + ('' if said else f' (`{PROG} note {tid} TEXT` notes it for the next attempt)'), file=sys.stderr)
        return 1
    print(said)
    return 0


def _main(argv: list[str], c) -> int:
    plan_dir = c.plan_dir
    todo, done = ensure()

    def say(msg):
        print(msg)
        if argv[0] in EDITS or argv[0] == 'goal' and len(argv) > 1:
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
    if argv[:1] == ['restore'] and len(argv) > 1:
        restore(argv[1], argv[2] if len(argv) > 2 else 'top', ' '.join(argv[3:]) or None)
        return say(f'restored {argv[1]}: open again in {Path(todo).name}')
    if argv[:1] == ['block'] and len(argv) > 2:
        after, rest = None, argv[2:]
        if rest[0] == '--after' and len(rest) > 2:
            after, rest = [t for t in rest[1].split(',') if t], rest[2:]
        block(argv[1], ' '.join(rest), after=after)
        return say(f'blocked {argv[1]}')
    if argv == ['reopen']:
        got = reopen()
        return say('\n'.join([f'reopened {t} ({", ".join(ids)} landed)' for t, ids in got] or ['nothing to reopen']
                             + last_lines()))
    if argv[:1] == ['unblock'] and len(argv) > 1:
        unblock(argv[1], ' '.join(argv[2:]))
        return say(f'unblocked {argv[1]}')
    if argv[:1] == ['move'] and len(argv) > 2:
        move(argv[1], argv[2], ' '.join(argv[3:]) or None)
        return say(f'moved {argv[1]} {" ".join(argv[2:])}')
    if argv[:1] == ['approve'] and len(argv) > 1:
        bid = approve(argv[1], ' '.join(argv[2:]))
        return say(f'approved: {bid} is open now, and a run starts it')
    if argv[:1] == ['revise'] and len(argv) > 2:
        k = revise(argv[1], ' '.join(argv[2:]))
        return say(f'{k} is open again with your changes noted; its build task is dropped until the next round')
    if argv in (['waiting'], ['waiting', '--all']):
        w = asks(all=len(argv) > 1)
        print('\n'.join('  '.join(x for x in (label, t, title, '' if label == 'CONCEPT' else what, u,
                                              f'(concept {k})' if k else '', '(shelved)' if sh else '') if x)
                        for label, t, k, what, u, title, sh in w)
              or 'nothing waits for your OK' + ('' if len(argv) > 1 else f' (`{PROG} waiting --all` adds the shelved)'))
        if ll := last_lines():
            print('\n'.join(ll))
        return 0
    if argv[:1] == ['confirm'] and len(argv) > 1:
        return say(confirm(argv[1], ' '.join(argv[2:])))
    if argv[:1] == ['change'] and len(argv) > 2:
        return say(change(argv[1], ' '.join(argv[2:])))
    if argv[:1] in (['shelve'], ['unshelve']) and len(argv) == 2:
        if argv[0] == 'shelve':
            return say(f'shelved {shelve(argv[1])}: still blocked, off {needs_cfg()["heading"]} (`{PROG} unshelve` brings it back)')
        return say(f'{unshelve(argv[1])} is back on {needs_cfg()["heading"]}')
    if argv == ['kinds']:
        k, own = kinds()
        return say('\n'.join(f'{p}  {m}' for p, m in k.items())
                   + ('' if own else '\n(the defaults: set [plan] kinds in runner.toml to name your own)'))
    if argv[:1] == ['add'] and len(argv) > 2:
        try:
            text, where, keyed, pri, force = add_args(argv[2:])
        except SystemExit as e:
            print(e, file=sys.stderr)
            return 2
        if not (given := bool(pri)):
            pri = add_default()
        if why := check_kind(argv[1]):
            print(why, file=sys.stderr)
            return 2
        text += keyed
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
        if not {'files', 'test'} & set(fields(text)):
            why = (f'the line has no `files:`: pass `--files path/a,dir/**` (the files the task will change) '
                   f'or `--test name` (the test it adds); the run keeps running tasks apart by them, and a line '
                   f'naming none runs beside anything')
            if cfg().raw['plan'].get('need_files'):
                print(f'{PROG}: not added: {why}', file=sys.stderr)
                return 2
            print(f'{PROG}: warning: {why}', file=sys.stderr)

        tid = add(argv[1], text, w[0], (w[1:] or [None])[0], pri=pri)
        msg = f'added {tid}' + (f' ({pri})' if pri else '')
        if fam:  # a subtask queues behind its family: only right when it needs the parent's code, data or verdict
            print(f'{PROG}: note: {tid} never runs beside {argv[1]}\'s family; if it could start now, add it '
                  f'with a fresh letter instead (`{PROG} add {re.match(r"[A-Za-z]+", argv[1]).group()} …`)',
                  file=sys.stderr)
        if pri == 'critical' and os.environ.get('AGENT_RUNNER') == '1':
            msg += '\ncritical goes ahead of the queued work: its text must say what it breaks or blocks'
        return say(msg)
    if argv[:1] == ['note'] and len(argv) > 2:
        note(argv[1], ' '.join(argv[2:]))
        return say(f'noted {argv[1]}')
    if argv[:1] == ['goal']:
        if len(argv) == 1:
            if not (got := goal()):
                print(f'{PROG}: no `Goal:` paragraph above the first heading in {Path(todo).name}; '
                      f'`{PROG} goal "TEXT"` writes one', file=sys.stderr)
                return 1
            print(got)
            return 0
        goal(' '.join(argv[1:]))
        return say('goal set')
    if argv[:1] == ['newid'] and len(argv) == 2:
        return say(next_id(argv[1]))
    if argv[:1] == ['brief'] and len(argv) == 2:
        return say('\n'.join(brief(argv[1])))
    if argv == ['archive']:
        return say(f'archived {archive(todo, done)}')
    if argv == ['claims']:
        got = sorted(plansync.claims(c).items())
        wips = git('for-each-ref', '--format=%(refname:short)', 'refs/heads/wip/main-checkout-*', cwd=c.root).stdout.split()
        return say('\n'.join([f'{t}  {plansync.label(cl)}' for t, cl in got] or ['no claims'])
                   + ''.join(f'\n{w}  main-checkout edits moved aside: pick them up' for w in wips))
    if argv[:1] == ['unclaim'] and len(argv) == 2:
        if not plansync.unclaim(c, argv[1]):
            print(f'{PROG}: no claim on {argv[1]}', file=sys.stderr)
            return 1
        return say(f'unclaimed {argv[1]}')

    # a lookup: an id, a section name, or `next`
    paths = [todo, plan_dir / 'REFERENCE.md', plan_dir / 'HUMAN.md', done]
    if c.run['rules']:
        paths.append(c.root / c.run['rules'])
    paths += [p for f in c.raw['plan']['lookup'] for p in (sorted(c.root.glob(f)) if any(ch in f for ch in '*?[') else [c.root / f])]
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
        # a heading named exactly that, in any file, before one that only contains it (`hst` before `hst-data`)
        out = next((o for ex in (True, False) for p in paths if (o := section(p, argv[0], ex))), [])
    if not out:
        print(f'{PROG}: nothing named {argv[0]!r} — run `{PROG}` for the index', file=sys.stderr)
        return 1
    print('\n'.join(out))
    return 0


if __name__ == '__main__':
    sys.exit(main())
