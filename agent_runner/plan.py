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
    ./run plan block <ID> [--after X,Y] WHY   [~] with "BLOCKED: (after X, Y) WHY" appended; --after all (below)
    ./run plan block <ID> --until CHECK[,CHECK] WHY   the same, waiting on what this machine checks by itself (below)
    ./run plan unblock <ID> [NOTE]   reopen: [ ], drop "BLOCKED: …", append NOTE (what unblocked it)
    ./run plan move <ID> WHERE   WHERE = top | before ID | after ID | in SECTION (its end); sub-items follow
    ./run plan add PREFIX TEXT [--files A,B] [--after X,Y] [--test T] [--journal D] [--model M] [--size simple|complex] [--needs TOOL] [--pri LEVEL] [--alone] [--last] [--force] [@ WHERE]
                                 new "- [ ] **<next free id>** TEXT | files: A, B | after: X, Y …"; prints
                                 the id (warns without --files or --test). Refused (exit 3, nothing written) when an open task looks like the
                                 same work: `plan note` it there, or --force when it is different work.
                                 The very text and fields of one not done are refused with --force too.
                                 --last: at the end of Next, with `after: all above` (below)
                                 add V [TEXT] [--now]: a release (below); --alone: it runs alone (below)
    ./run plan drop <ID> WHY     not done but not wanted (a duplicate, overtaken): archived with "dropped: WHY";
                                 a slot running it is stopped, its branch deleted unmerged (B19). The last open
                                 part of a split task: that ticks if a part landed, else is one whole task again
                                 B772: tasks blocked (after ID) on it ask you "still wanted? [Keep / Drop]";
                                 --duplicate-of X / --overtaken-by X (or a WHY that says so): they wait on X
                                 instead while X is open, else go on. (after all) and releases go on either way
    ./run plan cancel <ID> [--yes]   stop the slot running it, keep its work on wip/<ID> and hold it in its place, so
                                 no run starts it until `unhold <ID>`; says the minutes worked and stops
                                 nothing without --yes; refused while it lands
    ./run plan restore <ID> [WHERE]   undo a mistaken tick or drop: back from DONE.md as open [ ], same id, text
                                 and fields kept, "dropped: WHY" removed; WHERE as `move` (default: top)
                                 a dropped blocked task comes back blocked, with its ask file if this machine still has it
    ./run plan kinds             what each id letter means ([plan] kinds): an id's prefix says the kind of work
    ./run plan note <ID> TEXT    append " — TEXT" to the task (user details, priority reasons); a
                                 slot running it is told the note in its pane, as `tell` does
    ./run plan edit <ID> [TEXT] [--files A,B] [--after X,Y] [--test T] [--journal D] [--model M] [--size simple|complex] [--needs TOOL] [--pri LEVEL] [--alone | --no-alone]
                                 rewrite the task in place: TEXT replaces its whole description, notes included;
                                 id, checkbox, BLOCKED, tags and fields kept, but each flag replaces its field,
                                 --pri retags it and moves it as `add` files that level, --alone/--no-alone sets
                                 or clears its `(alone)` tag. A corrected instruction
                                 goes here, not in a note. A slot running it is told "Your task changed: …"
    ./run plan edit <ID> --wait-for X,Y|none   what a queued task waits for, exactly: replaces its `after:`, or the
                                 (after …) it is blocked on; none clears it. Refused for a release, a task that has
                                 started or asks the person, a done or unknown id, its own parent or subtask, a circle
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
                                 plan edit; an error when no slot runs ID, with the question it asks the person and the
                                 command that answers it, or the `note` to run
    ./run plan shelve <ID>       later: stays blocked, off Needs you; `unshelve <ID>` brings it back
    ./run plan hold <ID>         it keeps its place in the queue and no run starts it; `unhold <ID>` ends it; on a task
                                 a slot of this run is on, it is cancelled first (as `cancel <ID> --yes`)
    ./run plan hold|unhold|move|drop|restore next-release …   the same for the Next release row ([run] auto_release),
                                 which is no task: `move` makes it a release that waits for the tasks above its place,
                                 `drop … WHY` skips that cut (the count starts from zero) and `restore` undoes it
    ./run plan approve <ID> [CHOICE]   OK a concept (or its build task's id): the build opens, CHOICE noted on it
    ./run plan revise <ID> WHY   changes asked: the concept reopens with WHY noted, its waiting build is dropped
    ./run plan concept "TITLE" --page URL [--files A,B]   a concept page a chat showed inline: filed as a K task
                                 already done with its page, its build waiting for the OK (as a finished K
                                 leaves it), so Needs you and the Concepts view list it; the pick is approve/revise
    ./run plan restyle STYLE --page URL [--from ID] [--ui GLOBS] [--tasks IDS] [--dry]   a style approved for the
                                 future too: files the restyle (its page shows each page or screen that changes,
                                 before and after) and holds every queued task that touches the interface on it;
                                 a running one is parked as wip/<ID> at a clean point (one in its test gate or
                                 merging lands); approving the restyle reopens them with the style noted. --dry
                                 lists what it would hold, park and let land
    ./run plan claims            which run has which task (with a remote to claim through), and since when (STALE: no refresh in 3 h),
                                 and any wip/main-checkout-* branches of edits moved aside to land a merge
    ./run plan unclaim <ID>      drop a claim, whoever's: for a run that crashed or was switched off
    ./run plan repo-setup [URL|path]  move the plan to its own repo (plan repo mode), for two machines

**Where `add` files a task.** A person's task goes to the top of the leading section, as before. A task
given a `--pri` (and every follow-up a running agent files, which is `normal` unless it says) is tagged
`(follow-up, LEVEL)` and filed by its level, so the work a person queued always comes first:

    critical   the plan's Critical section if it has one, else the top of the leading section, behind
               earlier critical ones: it breaks or blocks other work
    high       the top of the leading section, behind critical and earlier high ones: important, but blocks
               nothing; a run tries it after the critical tasks and ahead of the rest, wherever its line stands
    normal     `### Follow-ups`, made after the person's sections (before Stretch/Parked): the usual follow-up
    low        the same section, behind every normal one: a check, a small tidy-up, a nice-to-have
    later      `### Parked`, which a run never starts: big future work for a person to schedule

`@ WHERE` still overrides the place (the tag stays).

**Subtask or fresh id.** `add B646 …` makes B646a, which never runs beside B646, and beside its other subtasks only
when both name `files:` that do not meet and neither is `after:` the other (F199): use it for a part of B646's work,
or work that can't start before it lands (it needs the parent's code, data or verdict). Work that
merely shares a topic, or came out of that task, gets a fresh letter (`add B …`) so a run starts it in parallel;
`add` notes this whenever it hands out a subtask id.

**Commits.** An edit in the main checkout commits at once (`plan: <command>`) and, on the shared branch, pushes
to `[git] push` (one line on stderr when it cannot); a worktree's waits for `done`.
`AGENT_RUNNER_NOCOMMIT=1` leaves it uncommitted, for a script that commits it with its own change.

**A subtask keeps its parent's place.** `add P17 …` (a task's id as the prefix: a split of that task) files
P17a after P17 and its earlier subtasks, under P17's own tag or none, with no level of its own unless `--pri`
gives one: the rest of a person's task stays where the person queued it, not behind every follow-up. A parent
tagged `later` that was moved out of Parked passes on no tag: a person scheduled it, so its split runs too.

The line format is `- [ ] **ID** text | files: a, b | after: X, Y | test: name | journal: dir | model: M | needs: tool`, under `###`
headings, and the checkbox is `[ ]` open, `[x]` done, `[~]` blocked. The keyed fields are the only thing read
off a line: `files:` keeps running tasks apart, `after:` holds a task until those ids are done, `test:`
names the test it adds, `journal:` a journal dir its brief lists, `model:` the model its session runs on
(`--model haiku`, over its kind's in [models.kinds]), `size:` simple or complex (`--size simple`, the
model in [models] sizes when set, F470), `needs:` the shared tools it needs (`--needs iphone15`, a
name in [run.tools]), without which no run starts it. Prose is never parsed for files or ids.

**A task that goes last** (a release) is filed with `add … --last`: at the end of Next, with `after: all above`.
That marker is no list to keep up: the run resolves it on every pick to each task above it in its own section
that is not done (open or blocked), tasks added above it later included, so it starts once the section has
drained. Tasks blocked on a person (CONFIRM, DECIDE, BLOCKED, a concept's OK) or shelved do not hold it until they
reopen, nor do tasks whose `after:` (or `BLOCKED: (after X)`) leads to one of those or to a shelved, Parked or Stretch
one, through any number of tasks, or split tasks with such a subtask;
other sections (Follow-ups) never do. `status`, `plan ID`, `reopen` and `waiting` say what it
still waits on and what it does not.

**A task that waits for everything before it** takes `--after all` (`add`, `edit`, `block`; any kind): `after:
all`, or `BLOCKED: (after all) why`, which the run resolves on every pick (and `reopen` after every merge) to each
open or blocked task above it in TODO.md, in any section, tasks queued above it later included. Tasks a run never
starts do not hold it, or it would never run: Parked (`--pri later`) and Stretch sections, shelved tasks, and
tasks blocked for the person (a `CONFIRM:`/`DECIDE:`/`BLOCKED:` ask, a concept's OK) until they reopen, and tasks
that cannot be done before one of these is answered or brought back: their `after:` or `BLOCKED: (after X)`, or an
open subtask of a split one, leads to it, through any number of tasks. A task that can still run holds it. `status`, `plan ID`,
`reopen` and
`waiting` say 'T5 waits for everything before it (12 open); not waiting on: R6 (needs you), R9 (after R6)'.

**A release is kind V** (F38): `add V` files it at the end of Next, no `--after` or `--files` needed, and with
no text it gets the default release brief (RELEASE_BRIEF) and `after: all`. It starts once what it waits for
has landed, even with other tasks running (F99), and tasks start beside it; while it is busy the merge holds
every other merge and push, so it releases exactly what was on the shared branch when it started. Tagged
`(alone)` (below) it runs alone instead. `add V --now` (or `--pri critical`) is an interim release: critical, at
the top, no `after: all`. A release is never refused as a duplicate of another. One auto release queued on idle lists what was ahead of it (`| ahead: T1, T2`, F435), and its `after: all` counts only those.

**A task that runs alone** (F130, any kind: a release, a major rewrite) is tagged `(alone)` first in its text:
`add … --alone`, or `edit ID --alone` (`--no-alone` clears it). The run starts it only when nothing else runs or
waits to merge in this run, and starts nothing beside it; tasks taken by hand or claimed by another runner do
not hold it (B107), unless they are tagged `(alone)` too. The dry run says 'runs alone'.

**A block that only waits on another task says which**, as `BLOCKED: (after X, Y) why`, and `reopen` (which a
`./run run` calls after every merge) puts it back to `[ ]` the moment X and Y are done. Without that a task
blocked on "P36 is not merged yet" stays blocked long after P36 lands, because nothing reads prose. `block` fills the list in by itself
from the open task ids its WHY names, so a session that forgets `--after` still gets one.

**A block that waits on something this machine can check** says which, as `block ID --until CHECK[,CHECK] WHY`
(`done --blocked WHY --until CHECK`): `version:X.Y.Z`, `login:PROVIDER`, `tool:NAME`, `check:NAME` or
`date:YYYY-MM-DD` (that day has come), and all must pass. It reads `BLOCKED: (until version:0.66.0) why`, needs no person, and no run starts it; `unblock` frees it at
any time. A check that is none of these, or names what is not here, is refused and nothing is blocked. With a
CONFIRM or DECIDE the question comes back under Needs you once they pass; any other block reopens for an agent.
It does not hold an `after: all` or `all above` task: a release must not wait for a task that waits for its version.

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

import argparse
import calendar
import difflib
import math
import os
import re
import shlex
import subprocess
import sys
import time
from collections import Counter
from functools import partial
from pathlib import Path
from types import SimpleNamespace

from agent_runner import plansync
from agent_runner.config import cfg, claude_model, main_checkout, SIZES
from agent_runner.gitops import git

PROG = './run plan'  # the name in messages; a wrapper sets its own ('./kit plan')
# The library API a wrapping project may call; names and signatures here change only in a major version.
__all__ = ['PROG', 'HELP', 'lines', 'index', 'section', 'ensure', 'archive', 'tick', 'block', 'reopen',
           'unblock', 'move', 'next_id', 'add', 'similar', 'note', 'drop', 'next_task', 'files_on_line', 'fields', 'overlap', 'brief', 'open_ids',
           'write_atomic', 'child', 'subtasks', 'main', 'PRI', 'kinds', 'check_kind',
           'concept', 'concept_done', 'waiting', 'approve', 'revise', 'restyle', 'hold', 'held_on', 'release_held',
           'asking', 'asks', 'confirm', 'change', 'shelve', 'unshelve', 'edit', 'needs_lines',
           'iter_tasks', 'titles', 'short_title', 'concept_shown']

ITEM = re.compile(r'^(\s*)- \[(.)\] \*\*([^\s*]+)')
HEAD = re.compile(r'(#+) ')
KEYS = ('files', 'ahead', 'after', 'test', 'journal', 'model', 'size', 'needs', 'split-by', 'held', 'moved')  # F435: ahead, written by auto release alone (release_ahead); F429a: moved, written by `move` alone (release_moves); F429: held, written by `hold` alone (row_hold); B196: split-by, written by `add` alone; F105: model, the task's own session model; F168: needs, shared tools
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
            if m and m.group(2) == ' ' and not m.group(1) and 'held' not in fields(line):  # F429
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


def one_line(text: str) -> str:
    """B189: `text` as it goes on a task line, which is one line of TODO.md: its lines joined by a space (a
    newline would end the task's block there, and what follows would belong to no task). A later line that starts
    as a task line's own markup does (a field, a note, a BLOCKED) gets a `>` before it, so the join makes none."""
    ls = text.splitlines()
    if len(ls) < 2:
        return ''.join(ls)
    ls = [x for l in ls if (x := l.strip())]
    return ' '.join(ls[:1] + [f'>{x}' if x.startswith(('| ', '— ', 'BLOCKED: ')) else x for x in ls[1:]])


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


def _dropped(ls: list[str], i: int) -> bool:
    """Whether the closed task at ls[i] was dropped (`drop` noted it), so it never landed."""
    from agent_runner.plan_drop import DROPPED  # C52: the module imports this one
    return DROPPED in _item_block(ls, i)[-1]  # where `note` appends


def _close_parents(ls: list[str], dl: list[str]) -> list[str]:
    """Tick each `(split into …)` parent whose subtasks are all done (in DONE.md, or ticked here). Only a
    parent that says it was split: a task whose ids merely look like children is left to its own session.
    B197: when every subtask was dropped none of it was done, so the parent stays, its `(split into …)` taken
    off: one whole task again (a BLOCKED on it stays). Returns the ids of those."""
    whole: list[str] = []
    landed = {m.group(3).rstrip('.') for x in (dl, ls) for i, l in enumerate(x)
              if (m := ITEM.match(l)) and not m.group(1) and m.group(2) == 'x' and not _dropped(x, i)}
    boxes = {m.group(3).rstrip('.'): m.group(2) for m in map(ITEM.match, dl + ls) if m and not m.group(1)}
    for i, l in enumerate(ls):
        m = ITEM.match(l)
        if m and not m.group(1) and m.group(2) != 'x' and SPLIT.search(l):
            kids = subtasks(m.group(3).rstrip('.'), l, boxes)
            if kids and all(boxes[k] == 'x' for k in kids):
                if kids & landed:
                    _mark(ls, i, 'x')
                else:
                    ls[i] = re.sub(r'\s*' + SPLIT.pattern, '', l)
                    whole.append(m.group(3).rstrip('.'))
    return whole


def archive(todo, done) -> int:
    """Move every top-level [x] task (with its sub-lines) from todo into done, under the same ### heading;
    a split parent goes too once its subtasks are all done, at least one of them landed.

    Needed because a session or a human sometimes ticks by hand, and a merge then brings that tick in
    without moving the line. Running it is always safe.
    """
    ls, dl, sec, moved = list(lines(todo)), list(lines(done)), '', 0
    if not dl:
        dl = ['# DONE — the archive', '']
    whole = _close_parents(ls, dl)
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
    if moved or whole:
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
    _clear_ask(tid, todo)
    own = long_form(plan_dir, tid)
    if os.path.exists(own):
        _write(own, [re.sub(rf'^(\s*)- \[[ ~]\] \*\*{re.escape(tid)}\b', rf'\1- [x] **{tid}', l)
                     for l in lines(own)])
    return archive(todo, done)




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


# F427b: a block that waits on until checks (`until.py`): `BLOCKED: (until version:0.66.0, login:codex) why`.
UNTIL = re.compile(r'BLOCKED: \(until ([^)]*)\)')


def until_of(ls: list[str], i: int) -> list[str]:
    """The until checks the last block of the task at ls[i] waits on; [] when it is not blocked on any."""
    m = ITEM.match(ls[i])
    if not m or m.group(2) != '~':
        return []
    tail = ls[i + len(_item_block(ls, i)) - 1]
    at = _block_at(tail)
    u = UNTIL.match(tail[at:].lstrip()) if at >= 0 else None
    return [t.strip() for t in u.group(1).split(',') if t.strip()] if u else []


def until_list(given: str, c=None) -> list[str]:
    """`--until`'s comma list as checks, each once. SystemExit says why one is refused. A check [run.checks] names only
    on this branch, or only in the main checkout, is taken."""
    from agent_runner import until  # here: until imports this module
    out = list(dict.fromkeys(x.strip() for x in given.split(',')))
    if '' in out:  # none, or a space after a comma made the next check a word of the why
        raise SystemExit(f'{PROG}: --until takes checks, comma-separated with no space: version:X.Y.Z, login:PROVIDER, '
                         'tool:NAME, check:NAME or date:YYYY-MM-DD. Nothing blocked.')
    c = c or cfg()
    for t in out:
        if (why := until.problem(t, c)) and until.problem(t, cfg(main_checkout(c.root))):
            raise SystemExit(f'{PROG}: --until: {why}. Nothing blocked.')
    return out


def until_label(checks: list[str], c=None) -> str:
    """'version 0.66.0, codex login': the checks as the screens call them."""
    from agent_runner import until
    try:
        c = c or cfg(main_checkout())
        return ', '.join(until.label(t, c) for t in checks)
    except (OSError, SystemExit, subprocess.SubprocessError):  # outside a repository: as written
        return ', '.join(checks)


def until_waits(ls: list[str], c=None) -> dict[str, str]:
    """{task: 'waits for version 0.66.0'} for the tasks blocked on until checks."""
    return {tid: f'waits for {until_label(got, c)}' for _, box, tid, _, i in iter_tasks(ls)
            if box == '~' and (got := until_of(ls, i))}


def until_passed(tid: str, todo=None) -> bool:
    """Reopen `tid`, all whose until checks passed, with a note of them. False, and nothing done, for a task that waits
    on none. A CONFIRM or DECIDE kept in the block goes back under Needs you instead (as B60's does)."""
    todo, _ = ensure(todo)
    ls = lines(todo)
    if not (got := until_of(ls, _find(ls, tid))):
        return False
    said = f'{until_label(got)} passed'
    if not _reask(tid, said, todo):
        unblock(tid, f'reopened: {said}', todo=todo)
    return True


def above(ls: list[str], i: int) -> list[str]:
    """What `after: all above` on the task at ls[i] stands for, read afresh each time: the top-level tasks above
    it in its own section (back to the nearest heading) that are not done, open or blocked, in order. A task
    blocked on a person (`asks`) does not hold it, nor one stuck on such a task (`_stuck_on`, B207, B209): a release
    does not wait on a Windows check nobody has done; once the person answers and it reopens, it holds it again.
    Other sections (Follow-ups) never count."""
    return _above(ls, i)[0]


def _above(ls: list[str], i: int) -> tuple[list[str], dict[str, list[str]]]:
    """(the tasks `after: all above` on ls[i] waits on, the ones it skips: `not_waiting_on`)."""
    start = i
    while start and not _level(ls[start - 1]):
        start -= 1
    return _split_skipped(ls, _not_waiting_back(ls, i, [j for j in range(start, i) if (m := ITEM.match(ls[j]))
                                                        and not m.group(1) and m.group(2) != 'x']))


def _split_skipped(ls: list[str], at: list[int]) -> tuple[list[str], dict[str, list[str]]]:
    """Of the tasks at the lines `at`: (the ids waited on, {id skipped: what it is stuck on}, [] for one that
    itself needs the person). A shelved task is neither: the person set it aside."""
    where = _open_at(ls)
    never = {i for section, _, _, _, i in iter_tasks(ls) if section.startswith(SKIPPED)}
    out, person, stuck = [], {}, {}
    for j in at:
        tid = ITEM.match(ls[j]).group(3).rstrip('.')
        if _shelved(ls, j):
            continue
        if _on_person(ls, j):
            person[tid] = []
        elif checks := until_of(ls, j):  # F427b: it may wait for the very release this is
            stuck[tid] = [until_label(checks)]
        elif 'held' in fields(ls[j]):  # F429
            stuck[tid] = [HELD_ROW]
        elif roots := _stuck_on(ls, j, where, never):
            stuck[tid] = roots
        else:
            out.append(tid)
    return out, person | stuck


def _open_at(ls: list[str]) -> dict[str, int]:
    """{id: its line's index} for the top-level tasks in `ls` that are not done."""
    return {m.group(3).rstrip('.'): i for i, l in enumerate(ls)
            if (m := ITEM.match(l)) and not m.group(1) and m.group(2) != 'x'}


def _named_after(ls: list[str], i: int) -> list[str]:
    """The ids the task at ls[i] itself says it waits on: its `after:` field, and a block's `(after …)` list.
    `all` and `all above` are left out: what they stand for already skips what is stuck."""
    ids = list(fields(ls[i]).get('after', []))
    if ITEM.match(ls[i]).group(2) == '~':
        w = [] if until_of(ls, i) else WAITS.findall(' '.join(_item_block(ls, i)))
        ids +=[t.strip() for t in w[-1].split(',')] if w else []
    return [t for t in ids if t and t not in (ALL, LAST)]


def _held_by(ls: list[str], i: int, where: dict[str, int]) -> list[str]:
    """What the task at ls[i] cannot be done before: `_named_after`, and a split parent's unfinished subtasks
    (B209), as `sched.tasks` holds it for them. Not one without `(split into …)` that has an attempt of its own:
    its session is on it, or it goes before them (`sched.parents_first`)."""
    tid = ITEM.match(ls[i]).group(3).rstrip('.')
    kids = subtasks(tid, ls[i], where)
    if kids and not SPLIT.search(ls[i]) and _attempted(tid):
        kids = set()
    return _named_after(ls, i) + sorted(kids, key=where.get)


def _attempted(tid: str) -> bool:
    """Has `tid` a branch, here or pushed by another machine: task/<ID> (running or to merge) or wip/<ID>."""
    from agent_runner import state  # here: state imports this module
    root = state.C.root if state.C else '.'
    return bool(git('for-each-ref', '--format=%(refname)', *(f'{at}/{b}' for at in ('refs/heads', 'refs/remotes/*')
                    for b in (f'task/{tid}', f'wip/{tid}', f'wip/{tid}-*')), cwd=root).stdout.strip())


def _stuck_on(ls: list[str], i: int, where: dict[str, int], never: set[int]) -> list[str]:
    """B207, B209: the tasks blocked for the person, shelved, or in a section no run starts (`never`: the lines of
    the Parked and Stretch tasks) that the task at ls[i] waits on, directly or down the chain of unfinished tasks
    (`where`: `_open_at`) and split parents' subtasks, so no run can finish it until the person acts on them. []
    when it can still run. A cycle is walked once."""
    out, seen, todo = [], {i}, _held_by(ls, i, where)
    while todo:
        j = where.get(todo.pop(0))
        if j is None or j in seen:
            continue
        seen.add(j)
        if j in never or _on_person(ls, j) or _shelved(ls, j) or until_of(ls, j) or 'held' in fields(ls[j]):
            out.append(ITEM.match(ls[j]).group(3).rstrip('.'))
        else:
            todo += _held_by(ls, j, where)
    return out


HELD_ROW = ''  # F429: the root a held task itself is stuck on: no task, the person's hold
ALL = 'all'  # an `after:` (or `block --after`) value: every task before it in TODO.md not done yet (F35)


def _shelved(ls: list[str], i: int) -> bool:
    """Is the task at ls[i] shelved (`shelve`): blocked, its last block reading `BLOCKED: shelved: …`."""
    m = ITEM.match(ls[i])
    if not m or m.group(2) != '~':
        return False
    tail = ls[i + len(_item_block(ls, i)) - 1]
    at = _block_at(tail)
    return at >= 0 and tail[at:].lstrip().startswith('BLOCKED: ' + SHELVED)


def before_all(ls: list[str], i: int) -> list[str]:
    """What `after: all` on the task at ls[i] stands for, read afresh each time (F35): every top-level task above
    it in TODO.md, in any section, that is not done (open or blocked), in order. Tasks a run never starts do not
    hold it, or it would never run: those in Parked (`--pri later`) and Stretch sections, shelved ones, and those
    blocked for the person (a `CONFIRM:`/`DECIDE:`/`BLOCKED:` ask, a concept's OK: B101), and those stuck on one
    of these (`_stuck_on`, B207, B209). `not_waiting_on` lists them; once the person answers and
    such a task reopens, it holds it again. On a line that lists what was ahead of it (F435), those and their parts
    alone."""
    return _before_all(ls, i)[0]


def not_waiting_on(ls: list[str], i: int) -> dict[str, list[str]]:
    """The tasks `after: all` (or `all above`) on ls[i] would wait on but skips: the ones blocked for the person
    (B101), {id: []}, then the ones stuck on one blocked, shelved or never started (`_stuck_on`), {id: those}. Shelved ones are left
    out, and so is one its `after:` names itself, which it does wait on. {} for a task with neither marker."""
    skipped = (_before_all(ls, i)[1] if _waits_all(ls, i)
               else _above(ls, i)[1] if LAST in fields(ls[i]).get('after', []) else {})
    named = {ITEM.match(ls[i]).group(3).rstrip('.'), *_named_after(ls, i)}
    return {t: roots for t, roots in skipped.items() if t not in named}


def _before_all(ls: list[str], i: int) -> tuple[list[str], dict[str, list[str]]]:
    """(the tasks `after: all` on ls[i] waits on, the ones it skips: `not_waiting_on`)."""
    from agent_runner import release_ahead  # here: it imports this module
    at, section = [], ''
    for j in range(i):
        if ls[j].startswith('### '):
            section = ls[j][4:].strip()
        m = ITEM.match(ls[j])
        if m and not m.group(1) and m.group(2) != 'x' and not section.startswith(SKIPPED) and \
                release_ahead.counted(ls[i], m.group(3).rstrip('.')):  # F435
            at.append(j)
    return _split_skipped(ls, _not_waiting_back(ls, i, at))


def _not_waiting_back(ls: list[str], i: int, at: list[int]) -> list[int]:
    """B868: the lines of `at` whose task does not wait, by name and down the chain, on the task at ls[i]: a task
    that waits for a release is never one the release waits for, or neither could start."""
    me, where = ITEM.match(ls[i]).group(3).rstrip('.'), _open_at(ls)

    def back(j: int) -> bool:
        seen, todo = {j}, _named_after(ls, j)
        while todo:
            t = todo.pop(0)
            if t == me:
                return True
            k = where.get(t)
            if k is not None and k not in seen:
                seen.add(k)
                todo += _named_after(ls, k)
        return False
    return [j for j in at if not back(j)]


def resolve_after(ls: list[str], i: int, ids: list[str]) -> list[str]:
    """`ids` (an `after:` field or a block's `(after …)` list) with `all above` and `all` resolved for ls[i]."""
    out: list[str] = []
    for a in ids:
        out += above(ls, i) if a == LAST else before_all(ls, i) if a == ALL else [a]
    return out


def waits_on(ls: list[str], i: int) -> list[str]:
    """The ids the task at ls[i] names in its `after:` field, `all above` (`above`) and `all` (`before_all`)
    resolved, itself left out. Done ones included: the caller checks which are still open."""
    tid = ITEM.match(ls[i]).group(3).rstrip('.')
    return [t for t in dict.fromkeys(resolve_after(ls, i, fields(ls[i]).get('after', []))) if t != tid]


def _waits_all(ls: list[str], i: int) -> bool:
    """Does the task at ls[i] wait on everything before it: `after: all`, or a last block's `(after all)`."""
    if ALL in fields(ls[i]).get('after', []):
        return True
    w = WAITS.findall(ls[i + len(_item_block(ls, i)) - 1])
    return bool(w) and not until_of(ls, i) and ALL in [t.strip() for t in w[-1].split(',')]


def last_waits(todo=None) -> list[tuple[str, list[str]]]:
    """(id, the open tasks it still waits on) for every task not done whose `after:` says `all above` or `all`
    (or whose block waits `(after all)`), in order."""
    todo, _ = ensure(todo)
    ls = list(lines(todo))
    live = open_ids(ls)
    out = []
    for i, l in enumerate(ls):
        if not ((m := ITEM.match(l)) and not m.group(1) and m.group(2) != 'x'):
            continue
        tid = m.group(3).rstrip('.')
        if _waits_all(ls, i):
            out.append((tid, [t for t in before_all(ls, i) if t in live and t != tid]))
        elif LAST in fields(l).get('after', []):
            out.append((tid, [t for t in waits_on(ls, i) if t in live]))
    return out


def all_line(tid: str, n: int, skipped=None, listed: bool = False) -> str:
    """How `status` and `plan` say what an `after: all` task waits on: a count, not an id list (F35), then the
    tasks it does not wait on (`not_waiting_on`), by id. `listed`: only what was ahead of it when it was queued (F435)."""
    what = 'what was ahead when it was queued' if listed else 'everything before it'
    line = f'{tid} waits for {what} ({n} open)' if n else f'{tid} waits for {what}: nothing left'
    return line + not_waiting(skipped)


def not_waiting(skipped) -> str:
    """'; not waiting on: R6, R2 (needs you), R89 (after R6)' for the tasks an `after: all` task skips
    (`not_waiting_on`: B101, B207), '' for none."""
    skipped = skipped or {}
    person = [t for t, roots in skipped.items() if not roots]
    said = [f'{", ".join(person)} (needs you)'] if person else []
    said += [f'{t} (held)' if roots == [HELD_ROW] else f'{t} (after {", ".join(roots)})'
             for t, roots in skipped.items() if roots]
    return f'; not waiting on: {", ".join(said)}' if said else ''


def last_lines(todo=None) -> list[str]:
    """'T5 waits on all above: F43, B54 (2 open)' for each `after: all above` task, 'T5 waits for everything
    before it (12 open)' for each `after: all` one (`reopen`, `waiting`), each with what it does not wait on."""
    todo, _ = ensure(todo)
    ls = list(lines(todo))
    at = _open_at(ls)
    out = []
    for t, ids in last_waits(todo):
        skipped = not_waiting_on(ls, at[t])
        out.append(all_line(t, len(ids), skipped, 'ahead' in fields(ls[at[t]])) if _waits_all(ls, at[t])
                   else (f'{t} waits on all above: {", ".join(ids)} ({len(ids)} open)' if ids
                         else f'{t} waits on all above: nothing left above it') + not_waiting(skipped))
    return out


def block(tid: str, why: str, todo=None, after=None, keep_ask: bool = False, until=None) -> None:
    """[~] plus "BLOCKED: why". The why must say what would unblock it, or the next session just re-reads it.

    `after` is the tasks it waits on; `reopen` unblocks it once they are all done. Left as None it is read
    off `why`: every task id named there that is still open, other than this task and its own subtasks.
    Pass [] for a block that waits on no task (a human, a tool, a capture).
    `keep_ask`: the agent may have written this block's ask file (F156); any other block takes an old one away.
    Its pick sheet likewise (B204).
    `until`: the until checks it waits on (F427b), as a list; not with `after`.
    """
    if until is not None:
        if after:
            raise SystemExit(UNTIL_AFTER.format(prog=PROG))
        until, after = until_list(','.join(until)), []
    todo, _ = ensure(todo)
    ls = list(lines(todo))
    i = _find(ls, tid)
    again = ITEM.match(ls[i]).group(2) == '~'
    why = one_line(why)
    if after or until:  # B211: a wait on a task that says BLOCKED: asks the person nothing; it reopens for an agent
        why = re.sub(r'^\s*(?:BLOCKED:\s*)+(?=\S)', '', why)
    why = stamp_ask(why)
    if after is None and asking(why):
        after = []  # it waits on a person (`asks`), not on a task its words happen to name
    if after is None:
        live = open_ids(ls)
        after = [t for t in dict.fromkeys(TASK_ID.findall(why))
                 if t in live and t != tid and not t.startswith(tid)]
    same = False
    kept = _last_ask(ls, i) if (after or until) and not asking(why) else ''
    if kept and not (until and kept.startswith('BLOCKED: ')):  # B60: it waits on X, then on the person again
        keep_ask = same = True  # the same ask comes back, its ask file with it
        why = f'{kept} — {why}'
    if not after and not until and not ASKED.search(why):  # B35: it waits on no task, so it lists under Needs you, with an age
        why = f'{why} (asked {__import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M")})'
    _mark(ls, i, '~')
    end = i + len(_item_block(ls, i)) - 1
    if until:  # the last block is the one that counts: an earlier one's `(after X)` is read no more
        at = len(_unblocked(ls[end])) if end == i else len(ls[end].split(' BLOCKED: ')[0])
        ls[end] = ls[end][:at] + WAITS.sub('BLOCKED:', ls[end][at:])
    ls[end] += ' BLOCKED: ' + (f'(after {", ".join(after)}) ' if after else
                               f'(until {", ".join(until)}) ' if until else '') + why
    _write(todo, ls)
    if not keep_ask:
        _clear_ask(tid, todo)
    elif not same:
        from agent_runner.asks import taken_ask
        taken_ask(tid, todo, again)


UNTIL_AFTER = '{prog}: --until and --after do not go together: block on one, and on the other once it is done. Nothing blocked.'


def _clear_ask(tid: str, todo) -> None:
    from agent_runner.asks import clear_ask  # here: asks imports this module
    clear_ask(tid, todo)


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
        w = [] if until_of(ls, i) else WAITS.findall(tail)  # a merge can leave an earlier `(after X)` on the line
        ids = [t.strip() for t in w[-1].split(',') if t.strip()] if w else []
        held = set(resolve_after(ls, i, ids)) - {m.group(3).rstrip('.')}  # `(after all)`: read afresh (F35)
        if ids and not held & live:
            out.append((m.group(3).rstrip('.'), ['everything before it' if t == ALL else t for t in ids]))
    for tid, ids in out:
        if not _reask(tid, f'{", ".join(ids)} landed', todo):
            unblock(tid, f'reopened: {", ".join(ids)} landed', todo=todo)
    return out


def unblock(tid: str, note: str = '', todo=None) -> None:
    todo, _ = ensure(todo)
    note = one_line(note)
    ls = list(lines(todo))
    i = _find(ls, tid)
    _mark(ls, i, ' ')
    end = i + len(_item_block(ls, i)) - 1
    ls[end] = (_unblocked(ls[end]) if end == i else ls[end].split(' BLOCKED: ')[0]) + (f' — {note}' if note else '')
    _write(todo, ls)
    _clear_ask(tid, todo)
    from agent_runner.asks import reopened  # here: asks imports this module
    reopened(tid, todo)


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
    if where == 'top':  # B196: a person wants it now
        blk[0] = _unheld(blk[0])
    j = _place(ls, where, ref)
    ls[j:j] = blk
    _write(todo, ls)


def next_id(prefix: str, paths=None, taken=()) -> str:
    """The next free id with this prefix, counting DONE.md too: ids are permanent and never reused. A task's own id
    gives its next subtask (P17 -> P17a, P17a -> P17a1), which never runs beside its parent (`sched.kin_clash`).
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


PRI = ('critical', 'high', 'normal', 'low', 'later')  # a follow-up's level, most urgent first


def next_pri(pri: str) -> str:
    """F438: the level the Priority control sets on a task of level `pri`: critical, then high, then normal again
    (down, so lowering a task never passes through a higher level)."""
    return {'critical': 'high', 'high': 'normal'}.get(pri, 'critical')


PRI_TAG = re.compile(r'\(follow-up, (' + '|'.join(PRI) + r')\)')
FOLLOW_UPS, PARKED = 'Follow-ups', 'Parked'  # the sections `add` makes for levels normal/low and later
# Sections a run never starts tasks from (a heading starting with one of these)
SKIPPED = ('Stretch', PARKED)
# The id letters when a repo names none in [plan] kinds: kinds of work any project has
KINDS = {'B': 'bug: something that worked, or should, is broken', 'F': 'feature: new behaviour',
         'T': 'tests and tooling: the gate, scripts, CI, the build', 'D': 'docs',
         'R': 'research: find out, measure or check; no product change', 'C': 'cleanup: refactor, remove, tidy',
         'K': 'concept: nothing is built yet; research the repo and publish an Artifact page of 2-3 options and a '
              'recommendation; the build waits for a person\'s OK',
         'V': 'release: waits for everything ahead of it, then starts beside running tasks; other merges wait '
              'until it lands (tagged (alone) it runs alone); with no text it gets the default release brief'}
# The release kind (F38): `add V` files it at the end of the leading section (`after: all` unless `--now` or
# `--pri critical` says release now), gets RELEASE_BRIEF when given no text, and is never refused as a
# duplicate of another release. Other tasks run beside it, but their merges wait while it is busy
# (`merge.hold_for_release`, F99); tagged `(alone)` a run starts no other task beside one (`sched.clash`)
RELEASE = 'V'
RELEASE_BRIEF = ('Release: bump the version where the project keeps it, per its versioning rules (agent-runner\'s: '
                 'docs/SETUP.md#versions), move CHANGELOG.md\'s Unreleased entries under the new version heading, '
                 'commit to main so the release workflow tags and publishes it. Check: the release workflow '
                 'passed (gh run list) and gh release view shows the new tag')


def release(tid: str) -> bool:
    """Is `tid` a release task (kind V, F38): it waits for what is ahead of it, and other merges wait for it
    (F99); tagged `(alone)` it also runs alone."""
    m = re.match(r'[A-Za-z]+', tid or '')
    return bool(m) and m.group() == RELEASE


# F130: a task of any kind tagged `(alone)` runs alone: the run starts it only when nothing else runs or waits to
# merge, and nothing beside it (`sched.clash`). The tag stands first in the description, after the level tag:
# `- [ ] **F9** (follow-up, normal) (alone) the rewrite`, so prose that mentions "(alone)" is never read as one.
ALONE = '(alone)'
ALONE_AT = re.compile(r'^\s*- \[.\] \*\*[^*]+\*\*\s*(?:\(follow-up, \w+\)\s*)?\(alone\)')


def alone(line: str) -> bool:
    """Is the task line `line` tagged `(alone)` (F130)."""
    return bool(ALONE_AT.match(line or ''))


def alone_ids(ls: list[str]) -> frozenset:
    """Ids of the top-level tasks of plan lines `ls` tagged `(alone)`, whatever their box (F130)."""
    return frozenset(tid for _, _, tid, _, i in iter_tasks(ls) if alone(ls[i]))


def alone_flag(rest: list[str]) -> tuple[list[str], bool | None]:
    """`plan add`/`edit` arguments without `--alone`/`--no-alone`, and what they asked: True, False or None."""
    flag = None
    for a in rest:
        if a in ('--alone', '--no-alone'):
            flag = a == '--alone'
    return [a for a in rest if a not in ('--alone', '--no-alone')], flag


def open_release(ls: list[str]) -> str:
    """The id of a release task in TODO.md's lines `ls` not done yet (open or blocked), else ''."""
    return next((t for t in sorted(open_ids(ls)) if release(t)), '')


def add_release(todo=None) -> str:
    """File a release as `plan add V` with no text does (F63, `[run] auto_release`): the default brief, after
    everything ahead of it now (F435: not what is queued above it later), at the end of the leading section. Its id."""
    from agent_runner import release_ahead  # here: it imports this module
    todo, _ = ensure(todo)
    tid = add(RELEASE, RELEASE_BRIEF + f' | after: {ALL}', 'bottom', todo=todo)
    release_ahead.record(tid, todo)
    return tid


def cut_release(tid: str = '', todo=None) -> str:
    """File a release that starts at once, as `plan add V --now` does (F195a, `[run] auto_release` by count): or,
    with `tid`, make that waiting release one (critical, at the top, no `after:`). Its id."""
    if not tid:
        return add(RELEASE, RELEASE_BRIEF, pri='critical', todo=todo)
    todo, _ = ensure(todo)
    ls = list(lines(todo))
    i = _find(ls, tid)
    ls[i] = FIELD.sub(lambda m: '' if m.group(1) in ('after', 'ahead') else m.group(0), ls[i])
    _write(todo, ls)
    edit(tid, pri='critical', todo=todo)
    return tid


def waiting_default(ls: list[str], ids, queued=()) -> str:
    """The first of the waiting releases `ids` in `ls` that waits by `after: all` alone, whatever its level or place,
    and has the default brief, as `plan add V` with no text files it, or is one auto release `queued` (an older
    version's brief). '' for none."""
    return next((tid for _, box, tid, _, i in iter_tasks(ls) if tid in ids and box == ' '
                 and (RELEASE_BRIEF in ls[i] or tid in queued) and fields(ls[i]).get('after') == [ALL]), '')


def kinds() -> tuple[dict[str, str], bool]:
    """What each id prefix means, and whether the repo set them (then `add` refuses any other prefix)."""
    k = cfg().raw['plan'].get('kinds') or {}
    return (dict(k), True) if k else (KINDS, False)


def _pathish(arg: str) -> bool:
    """An argument that reads as a file path: a slash, a file extension, or a file that exists here."""
    return ' ' not in arg and ('/' in arg or bool(re.search(r'\.[A-Za-z0-9]{1,8}$', arg)) or Path(arg).exists())


EXPANDED = 6  # B773: a stretch of text with this many more existing paths than other words is an expanded glob


def expanded_paths(text: str) -> list[str]:
    """B773: the existing paths in the first stretch of `text` that is mostly such paths (EXPANDED more of them than
    of its other words: a file name with a space is two other words), else []. A path with a comma or a full stop
    after it, as prose and lists have, is an other word."""
    got: list[str] = []
    score = best = 0
    for w in text.split():
        if os.path.exists(w):
            got, score = [*got, w] if score else [w], score + 1
            best = max(best, score)
        elif score:
            score -= 1
            if not score and best >= EXPANDED:
                break
            best = best if score else 0
    return got if best >= EXPANDED else []


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
        elif a == '--pri' or a.lstrip('-') in KEYS and a.startswith('--') and a not in (f'--{SPLIT_BY}', '--held', '--moved', '--ahead'):
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
    if got := next((g for part in (text, where) if (g := expanded_paths(' '.join(part)))), []):  # B773
        no(f'{len(got)} existing paths ({got[0]} … {got[-1]}): a glob the shell expanded? Quote the glob, '
           f"as in --files 'dir/**'")
    if in_where and not where:
        no('@ needs a place (top, bottom, before ID, after ID, in SECTION)')
    if (m := vals.get('--model')) is not None and (not m.strip() or len(m.split()) > 1 or ',' in m):
        no(f'--model takes one model name (haiku, sonnet, opus), not {m!r}')
    if (sz := vals.get('--size')) is not None and sz.strip() not in SIZES:  # F470
        no(f'--size takes {" or ".join(SIZES)}, not {sz!r}')
    if m is not None and ':' in m:  # F125: another provider is refused here, not swapped for the kind's model later
        c = cfg()
        try:
            claude_model(m.strip(), c.providers, c.models_local, '--model')
        except SystemExit as e:
            no(str(e).removeprefix('agent-runner: '))
    if last:
        vals['--after'] = ', '.join(x for x in (vals.get('--after', '').strip(', '), LAST) if x)
    keyed = ''
    for key in KEYS:  # `--files a,b` → ` | files: a, b`, in KEYS order
        if (v := vals.get(f'--{key}')) is not None:
            keyed += f' | {key}: ' + (v.strip() if key == 'size' else v if key in ('test', 'model') else ', '.join(
                LAST if x == LAST else ', '.join(re.split(r'[,\s]+', x)) for x in re.split(r',\s*', v.strip(', '))))
    t, _, w = ' '.join(text).partition(' @ ')
    t, w, keyed = one_line(t), one_line(w), one_line(keyed)
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
    if pri == 'high':  # F438: behind the critical and earlier high ones that lead, never in a Critical section
        i = _place(ls, 'top', None)
        h = next((k for k in range(i - 1, -1, -1) if _level(ls[k])), None)
        if h is not None and 'critical' in ls[h].lower():
            h = next((k for k in range(h + 1, len(ls)) if 0 < _level(ls[k]) <= _level(ls[h])), None)
            h = h if h is not None and _level(ls[h]) == 3 else None
            if h is None or ls[h].lstrip('# ').startswith((FOLLOW_UPS, *SKIPPED)):
                h = _make_section(ls, 'Next', (FOLLOW_UPS, *SKIPPED))
            i = h + 1
            while i < len(ls) and not ITEM.match(ls[i]) and not _level(ls[i]):
                i += 1
        while i < len(ls) and ITEM.match(ls[i]) and (t := PRI_TAG.search(ls[i])) and t.group(1) in ('critical', 'high'):
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
        pri: str | None = None, alone_: bool = False, split_c=None) -> str:
    """File a new task; with `pri` it is tagged `(follow-up, pri)` and, unless `where` says, filed by its level;
    with `alone_` it is tagged `(alone)` (F130); with `split_c` (a Config) one too big for a session is held for
    its author to split it (B196: `SPLIT_HOLD`)."""
    if pri is not None and pri not in PRI:
        raise SystemExit(f'{PROG}: --pri must be one of {" | ".join(PRI)}, not {pri!r}')
    todo, done = ensure(todo, done)
    text = one_line(text)
    tid = next_id(prefix, [todo, done, *_other_checkouts(todo, done)], reserved(todo))
    reserve(todo, tid)
    ls = list(lines(todo))
    if alone_ and not text.startswith(ALONE):
        text = f'{ALONE} {text}'
    if pri and not PRI_TAG.search(text):
        text = f'(follow-up, {pri}) {text}'
    j = _place_pri(ls, pri) if pri and not where else _place(ls, where or 'top', ref)
    from agent_runner import release_ahead, release_moves, row_hold  # here: they import this module
    line = release_ahead.cleared(release_moves.cleared(row_hold.cleared(_unheld(f'- [ ] **{tid}** {text}'))))  # only this sets a split hold, `hold` a held task
    if split_c and _big([line], tid, split_c):  # in the same write: no run reads the task without it
        line += f' | {SPLIT_BY}: {split_stamp()}'
    ls[j:j] = [line]
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


def similar(text: str, todo=None, skip: str | None = None, limit: int = 3, ls: list[str] | None = None) -> list[str]:
    """Open or blocked tasks that look like the same work as `text`, best first, as 'ID: start of its text'.

    Shown when a task is added, so a duplicate is caught before an agent spends a session on it. Kept quiet
    unless the match is strong, since every line lands in an agent's context: the new task's rarer words
    (weighted by how few tasks use them) mostly also on the other, or a fair share of them plus a file that
    few open tasks name. `ls`: plan lines to look in instead of the TODO.md (B33: a side of a merge)."""
    import math
    if ls is None:
        todo, _ = ensure(todo)
        ls = lines(todo)
    tasks = [(m.group(3), l) for l in ls
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
        if fs and f2 and not overlap(fs, f2):
            continue  # B42: both name files and share none (a sweep's template wording on other pages): other work
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


OWN_KEYS = ('split-by', 'held', 'moved', 'ahead')  # fields only a command of their own writes, so no add gives them


def _same_key(text: str) -> tuple:
    """What makes two task texts the same one: the words and the fields, whitespace, the level and the `(alone)` tag
    aside. `text` is a task's lines joined, without its id."""
    body = ' '.join(text.split())
    keys = {k: tuple(sorted(v)) for k, v in fields(body).items() if k not in OWN_KEYS}
    body = re.sub(rf'^{PRI_TAG.pattern}\s*', '', prose(body).strip()).removeprefix(ALONE)
    return ' '.join(body.split()), tuple(sorted(keys.items()))


def same_task(text: str, todo=None, done=None) -> str:
    """B817: the id of the open or blocked task that says exactly `text` (`_same_key`), with or without
    notes and a BLOCKED after it, else ''. Other checkouts'
    tasks count too, as another slot may have filed it and not merged yet; the first checkout that has an id (this
    one, then the main one) says what it reads, and an id done in any of them is done. A release is never the same."""
    todo, done = ensure(todo, done)
    todos = [Path(todo), *_other_checkouts(todo)]
    words, keys = _same_key(one_line(text))

    def same(line: str) -> bool:
        w, k = _same_key(line)
        return k == keys and (w == words or w.startswith((f'{words} — ', f'{words} BLOCKED: ')))

    seen = {tid.rstrip('.') for t in todos for f in (t, t.with_name(Path(done).name))
            for _, box, tid, _, _ in iter_tasks(lines(f)) if box == 'x'}
    for t in todos:
        ls = lines(t)
        here = [(tid.rstrip('.'), rest, i) for _, _, tid, rest, i in iter_tasks(ls)]
        for tid, rest, i in here:
            if tid not in seen and not release(tid) and same(' '.join([rest, *_item_block(ls, i)[1:]])):
                return tid
        seen |= {tid for tid, _, _ in here}
    return ''


def last_answer(tid: str, todo=None, about: str = '') -> str:
    """F102: the person's answer `confirm` or `change` last noted on the task ('your answer (DECIDE …): …', 'you
    said, on DECIDE …: do this instead: …'), for the session that asked; '' when none is noted last, or when it
    does not name the question `about` (an answer to an earlier one)."""
    todo, _ = ensure(todo)
    ls = list(lines(todo))
    try:
        i = _find(ls, tid)
    except SystemExit:
        return ''
    last = ls[i + len(_item_block(ls, i)) - 1].split(' BLOCKED: ')[0].rsplit(' — ', 1)
    said = last[1].strip() if len(last) > 1 else ''
    if about and ' '.join(about.split())[:30] not in said:
        return ''
    return said if said.startswith(('your answer (', 'you said')) else ''


def note(tid: str, text: str, todo=None) -> None:
    todo, _ = ensure(todo)
    ls = list(lines(todo))
    i = _find(ls, tid)
    ls[i + len(_item_block(ls, i)) - 1] += f' — {one_line(text)}'
    _write(todo, ls)


def edit(tid: str, text: str = '', keyed: str = '', pri: str | None = None, todo=None,
         alone_: bool | None = None) -> str:
    """F45: rewrite a task in place. `text` replaces its whole description, notes (` — …`) included, so a
    corrected instruction does not sit after the stale one; '' keeps them. The id, the checkbox, the
    `BLOCKED: …` tail, the `(follow-up, LEVEL)` tag and the keyed fields stay, except that fields given in
    `text` or in `keyed` (` | files: a | after: X`, as `add_args` builds it) replace those keys. With `pri` the
    tag becomes that level and the line moves where `add` files that level. The `(alone)` tag (F130) stays too:
    `alone_` True sets it, False clears it. Returns the new first line."""
    if pri is not None and pri not in PRI:
        raise SystemExit(f'{PROG}: --pri must be one of {" | ".join(PRI)}, not {pri!r}')
    todo, _ = ensure(todo)
    text, keyed = one_line(text), one_line(keyed)
    ls = list(lines(todo))
    i = _find(ls, tid)
    first = ls[i]
    m = re.match(r'^(\s*- \[.\] \*\*[^*]+\*\*)\s*', first)
    head, rest = m.group(1), first[m.end():]
    body = _unblocked(rest)
    tail = rest[len(body):]  # ` BLOCKED: …` with whatever followed it
    old = dict(FIELD.findall(body))
    tag = PRI_TAG.search(body)
    tag = f'(follow-up, {pri})' if pri else (tag.group(0) if tag else '')
    was_alone = alone(first)
    old_blk = _item_block(ls, i)
    rest_blk = old_blk[1:]
    if text.strip():
        desc = prose(text).strip()
        new = dict(FIELD.findall(text))
        new.pop(SPLIT_BY, None)
        new.pop('held', None)  # F429: `hold` alone writes it
        new.pop('moved', None)  # F429a: `move` alone writes it
        new.pop('ahead', None)  # F435: auto release alone writes it
        # continuation lines before the first sub-item are description too (and `note` appends to a block's
        # last line): they go, sub-items stay, and a BLOCKED on a dropped last line moves to the first line
        k = next((n for n, l in enumerate(rest_blk) if ITEM.match(l)), len(rest_blk))
        if rest_blk and k == len(rest_blk) and ' BLOCKED: ' in rest_blk[-1]:
            tail = ' BLOCKED: ' + rest_blk[-1].split(' BLOCKED: ', 1)[1]
        rest_blk = rest_blk[k:]
    else:
        desc, new = ' '.join(PRI_TAG.sub('', prose(body)).split()), {}
    if desc.startswith(ALONE):  # F130: kept apart from the description, so --alone/--no-alone can set or clear it
        desc, was_alone = desc[len(ALONE):].lstrip(), True
    flag = ALONE if (was_alone if alone_ is None else alone_) else ''
    vals = {**old, **new, **dict(FIELD.findall(keyed))}
    if 'after' in {**new, **dict(FIELD.findall(keyed))}:  # F435: it waits for what the person says now
        vals.pop('ahead', None)
    fieldtext = ''.join(f' | {k}: {vals[k]}' for k in KEYS if k in vals)
    line = ' '.join(x for x in (head, tag, flag, desc) if x) + fieldtext + tail
    blk = [line] + rest_blk
    del ls[i:i + len(old_blk)]
    j = _place_pri(ls, pri) if pri else i  # with --pri, moved like `add` files that level
    ls[j:j] = blk
    _write(todo, ls)
    return line


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


WAIT_OK = 'waiting for your OK on '
TASK_LINE = re.compile(r'^- \[(.)\] \*\*([^*\s]+)\*\*(.*)')  # a top-level task line: its box, its id, the rest
def iter_tasks(ls: list[str]):
    """Each top-level task line of a plan's lines `ls`, in order, as (section, box, id, rest, index): `section`
    is the last `### ` heading above it ('' before any), `box` the character in its [ ], `rest` the line after
    its `**ID**`, `index` its place in `ls` (for `_item_block`, `waits_on`)."""
    section = ''
    for i, l in enumerate(ls):
        if l.startswith('### '):
            section = l[4:].strip()
        elif m := TASK_LINE.match(l):
            yield section, m.group(1), m.group(2), m.group(3), i

# --- F19: a style for the future too: a restyle page, and the interface work held until it is approved -------
#
# A person approves a concept's style and says it holds from now on ("the future too", "make everything look
# like this"). The control session publishes a restyle page (each current page or screen that changes to match,
# before and after) and runs `plan restyle STYLE --page URL`: it files the restyle as a concept already shown
# (a K task ticked with its page, its build waiting for an OK, as `concept_done` does) and holds every queued task
# that touches the interface on it: `BLOCKED: held for restyle K9 (style: …): …`, kept, not dropped. A task a
# slot runs is held too and the run asked to park it (`loop.restyles`): one already in its test gate or merging
# lands, and is noted on the restyle to list on its page; any other is told to stop at a clean point, commit and
# write its journal, and its branch is parked as wip/<ID>. Approving the restyle (`approve`, `confirm`) reopens
# every task held on it with the style noted. Nothing waits in a held-open session while the person decides.

UI_FILES = ('*.html', '*.htm', '*.css', '*.scss', '*.sass', '*.less', '*.vue', '*.svelte', '*.jsx', '*.tsx',
            '*.astro', '*.erb', '*.hbs', '*.jinja', '*.j2', '*.twig', '*.liquid', '*.qml', '*.xib',
            '*.storyboard', 'templates/**', 'static/**', 'public/**', 'assets/**', 'web/**', 'ui/**', 'site/**',
            'frontend/**', 'components/**', 'styles/**', 'pages/**', 'screens/**', 'views/**')
UI_WORDS = re.compile(r'\b(ui|interface|screens?|pages?|buttons?|layouts?|styles?|styling|css|themes?|menus?|'
                      r'dialogs?|icons?|fonts?|colou?rs?|dark mode|front[- ]?end|look and feel)\b', re.I)
RESTYLE_HELD = 'held for restyle '
HELD = re.compile(r'BLOCKED: (?:shelved: )?held for restyle ([A-Za-z]+\d+[a-z0-9]*) \(style: (.*)\): reopens ')
LANDED_OLD = 'landed in the old style while the restyle waits: '
RESTYLE_PARK: list[str] = []  # the running tasks `_p_restyle` held, for `main` to ask the run to park
FREED: list[str] = []  # the held tasks the last `approve` reopened, for its message


def ui_task(line: str, globs=None) -> bool:
    """Does the task line touch the interface: its `files:` meet `globs` (UI_FILES), or, naming no files, its
    words do (a page, a screen, a button, the style)."""
    from agent_runner.plan_concepts import title_of  # C52: the module imports this one
    files = fields(line).get('files', [])
    if files:
        return bool(overlap(set(files), set(globs or UI_FILES)))
    return bool(UI_WORDS.search(title_of(line)))


def restyle_targets(globs=None, ids=None, todo=None) -> list[tuple[str, str]]:
    """(id, title) of each queued task the restyle holds: open ([ ]) top-level tasks that touch the interface
    (`ui_task`), or exactly `ids` when given; concepts and releases never (they build no interface)."""
    from agent_runner.plan_concepts import concept, title_of  # C52: the module imports this one
    todo, _ = ensure(todo)
    out = []
    for _, box, tid, rest, i in iter_tasks(lines(todo)):
        line = f'- [{box}] **{tid}**{rest}'
        if box != ' ' or concept(tid) or release(tid):
            continue
        if (tid in ids) if ids else ui_task(line, globs):
            out.append((tid, title_of(line)))
    return out


def hold(tid: str, rid: str, style: str, todo=None) -> None:
    """Block `tid` on restyle `rid`: no `(after …)` (the restyle's concept is ticked at once, which must not free
    it) and no ask stamp (it waits on no person but the restyle's own OK); `approve` frees it."""
    todo, _ = ensure(todo)
    ls = list(lines(todo))
    i = _find(ls, tid)
    _mark(ls, i, '~')
    end = i + len(_item_block(ls, i)) - 1
    ls[end] += (f' BLOCKED: {RESTYLE_HELD}{rid} (style: {one_line(style)}): reopens with the style noted once the '
                f'restyle page is approved')
    _write(todo, ls)


def held_on(rids, todo=None) -> list[tuple[str, str, str]]:
    """(task id, restyle id, style) of each task held on one of the restyles `rids`."""
    todo, _ = ensure(todo)
    ls, out = lines(todo), []
    for _, box, tid, _, i in iter_tasks(ls):
        if box == '~' and (m := HELD.search(ls[i + len(_item_block(ls, i)) - 1])) and m.group(1) in rids:
            out.append((tid, m.group(1), m.group(2)))
    return out


def release_held(rids, choice: str = '', todo=None) -> list[str]:
    """The restyle `rids` names was approved: reopen each task held on it with the style it is to use noted."""
    freed = []
    for tid, rid, style in held_on(rids, todo):
        unblock(tid, f'style to use (restyle {rid} approved): {style}' + (f'; as approved: {choice}' if choice else ''),
                todo=todo)
        freed.append(tid)
    return freed


def restyle(style: str, page: str, frm: str = '', globs=None, ids=None, files=None, running=lambda tid: '',
            todo=None, done=None) -> dict:
    """File the restyle of `style` (shown on `page`) and hold the interface work on it. `running(tid)` says what a
    run does with a task ('s2', 'merging', '': `run_on`). Returns {'rid', 'build', 'held', 'park', 'landing'}:
    the restyle's id (its concept, or its build where the kinds lack K), its build task, the queued tasks held,
    the running ones held for the run to park, and the merging ones left to land (noted on the restyle)."""
    from agent_runner.plan_concepts import CONCEPT, build_kind, concept_done  # C52: the module imports this one
    todo, done = ensure(todo, done)
    targets = restyle_targets(globs, ids, todo)
    ui = files or sorted({f for t, _ in targets for f in fields(lines(todo)[_find(lines(todo), t)]).get('files', [])
                          if overlap({f}, set(globs or UI_FILES))})
    text = (f'Restyle to the style approved{" on " + frm if frm else ""} for the future too: {style}. Each current '
            f'page or screen that changes to match it, before and after, is on the restyle page')
    if ui:
        text += ' | files: ' + ', '.join(ui)
    if CONCEPT in kinds()[0]:
        rid = add(CONCEPT, text, todo=todo, done=done)
        bid = concept_done(rid, page, todo=todo, done=done)
        tick(rid, todo=todo, done=done)
    else:
        rid = bid = add(build_kind(), text, todo=todo, done=done)
        block(bid, WAIT_OK + page, todo=todo, after=[])
    out = {'rid': rid, 'build': bid, 'held': [], 'park': [], 'landing': []}
    for tid, _ in targets:
        where = running(tid)
        if where == 'merging':
            out['landing'].append(tid)
            note(bid, LANDED_OLD + tid, todo=todo)
            continue
        hold(tid, rid, style, todo=todo)
        out['park' if where else 'held'].append(tid)
    return out


def restyle_build(rid: str, todo=None) -> str:
    """The build task of restyle `rid` still waiting for its OK (where a landed task is listed), else `rid`."""
    from agent_runner.plan_concepts import waiting  # C52: the module imports this one
    return next((w[0] for w in waiting(todo, all=True) if rid in (w[0], w[1])), rid)


def park_text(tid: str, rid: str, style: str, runner: str = 'agent-runner') -> str:
    """What a slot running `tid` reads when restyle `rid` parks it (F19)."""
    return (f'Stop at a clean point: a person approved a new style for the interface for the future too ({style}), '
            f'and {tid} now waits for its restyle page ({rid}) to be approved. If your `{runner} done` is already '
            f'running its test gate, let it finish and do nothing else. Otherwise do not run `done`: commit what is '
            f'solid on task/{tid}, write in your journal what is done and what is left, then end your turn. The run '
            f'parks your branch as wip/{tid}; the task starts again from there, with the style in its note, once the '
            f'restyle is approved.')


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
          if not tail[:m.start()].endswith((' BLOCKED:', ' shelved:'))
          and not re.search(r' BLOCKED: \((?:after|until) [^)]*\)$', tail[:m.start()])]  # B60's `(after X) BLOCKED: …`
    return at[-1] if at else -1


def asking(why: str) -> bool:
    """Does a block's why wait on a person: it starts with CONFIRM:, DECIDE: or BLOCKED:."""
    return bool(re.match(r'(' + '|'.join(ASK_LABELS) + r'): ', why.strip()))


# B60: a person's check (CONFIRM/DECIDE/BLOCKED) sent back to wait on a task (`change`, then `block --after X`,
# or `block --after X` on the blocked ask itself) keeps its kind: the block reads `BLOCKED: (after X) CONFIRM:
# <what it asked> — <why>`, which waits on X like any other (off Needs you, no slot takes it), and once X lands
# `reopen` puts it back under Needs you with its question instead of opening it for an agent.
CHANGED = re.compile(r'you said, on (' + '|'.join(ASK_LABELS) + r') (.*?): do this instead: ')
ANSWERED = re.compile(r'(?:confirmed by you \(|your answer \((?:' + '|'.join(ASK_LABELS) + r') |'
                      r'you said, on stuck )')
REASK = re.compile(r'BLOCKED: \((?:after|until) [^)]*\) ((?:' + '|'.join(ASK_LABELS) + r'): .*)$')


def _last_ask(ls: list[str], i: int) -> str:
    """'LABEL: what it asked' when the task at ls[i]'s last block was a person's check still to do: blocked on it
    now, or sent back to the queue by `change` (no answer since). '' otherwise."""
    tail = ls[i + len(_item_block(ls, i)) - 1]
    at = _block_at(tail)
    if ITEM.match(ls[i]).group(2) == '~' and at >= 0:
        t = tail[at:].lstrip()
        if (a := ASKING.match(t)) and not a.group(1):
            return f'{a.group(2)}: {a.group(3)}'
        return m.group(1) if (m := REASK.match(t)) else ''
    c = list(CHANGED.finditer(tail))
    if not c or any(m.start() > c[-1].start() for m in ANSWERED.finditer(tail)):
        return ''
    return f'{c[-1].group(1)}: {c[-1].group(2)}'


def _reask(tid: str, said: str, todo) -> bool:
    """Put task `tid`, whose `(after …)` or `(until …)` block keeps a person's check (`_last_ask`), back under Needs you,
    `said` what it waited for ('X7 landed')."""
    ls = list(lines(todo))
    i = _find(ls, tid)
    end = i + len(_item_block(ls, i)) - 1
    at = _block_at(ls[end])
    if at < 0 or not (m := REASK.match(ls[end][at:].lstrip())):
        return False
    ask = re.sub(r' — back for you: [^—]*?(?:landed|passed)(?= —|$)', '', ASKED.sub('', m.group(1)))  # one, not a pile
    ls[end] = ls[end][:at] + ' BLOCKED: ' + stamp_ask(f'{ask} — back for you: {said}')
    _write(todo, ls)
    return True


# B35: a block with no caps label that waits on no open task (`done --blocked 'tests flake, unclear why'`) is
# freed by nothing: `reopen` has no `(after …)` to wait out. It lists under Needs you too, as label STUCK, in
# plain words: what it says, reply with what to do (`change` reopens it with that noted, `confirm` reopens it).
# A task waiting `(after X)` on such an X stays off the list: X is on it, and answering X frees both.
STUCK = 'STUCK'


def _stuck_why(tail: str) -> tuple[str, str, bool] | None:
    """(what it says, its link or '', shelved) when `tail` (a task's last line, from its last ` BLOCKED: `) is a
    block with no caps label and no concept page that waits on no task, else None."""
    t = tail.strip()
    if not t.startswith('BLOCKED: ') or ASKING.match(t) or WAIT_ANY.match(t):
        return None
    why = t[len('BLOCKED: '):]
    shelved = why.startswith(SHELVED)
    why = why[len(SHELVED):] if shelved else why
    if why.startswith(RESTYLE_HELD):
        return None  # F19: held on a restyle; its OK (listed as a concept) frees it
    if UNTIL.match(t):
        return None  # F427b: it waits on until checks
    if (w := re.match(r'\(after ([^)]*)\)\s*', why)):
        if any(x.strip() for x in w.group(1).split(',')):
            return None  # it waits on tasks: `reopen` frees it once they are done
        why = why[w.end():]
    what = ASKED.sub('', why.split(' — ')[0].split(' | ')[0]).strip()
    u = URL.search(what)
    if u:
        what = ' '.join((what[:u.start()] + what[u.end():]).split()).rstrip(' :,;')
    return what or 'it says nothing more', u.group(0) if u else '', shelved


def _waiters(ls: list[str]) -> dict[str, list[str]]:
    """{id: the tasks its `BLOCKED: (after …)` waits on} for each blocked task."""
    out = {}
    for i, l in enumerate(ls):
        if (m := ITEM.match(l)) and not m.group(1) and m.group(2) == '~':
            if not until_of(ls, i) and (w := WAITS.findall(ls[i + len(_item_block(ls, i)) - 1])):
                out[m.group(3).rstrip('.')] = [t.strip() for t in w[-1].split(',') if t.strip()]
    return out


def asks(todo=None, all: bool = False) -> list[tuple[str, str, str, str, str, str, bool]]:
    """Everything waiting on a person, in TODO.md order: (label, task id, its concept id or '', what to do, link
    or '', the task's title, shelved). Label CONCEPT is a build task waiting on a concept page (`waiting`);
    label STUCK a block with no caps label that waits on no task (B35). Shelved ones only with `all`."""
    from agent_runner.plan_concepts import FROM_CONCEPT, title_of  # C52: the module imports this one
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
        elif s := _stuck_why(tail):
            held = [h for h, ids in _waiters(ls).items() if tid in ids]
            what = s[0] + (f' (holds {", ".join(held)} too)' if held else '')  # answering it frees those
            item = (STUCK, tid, '', what, s[1], title_of(l), s[2])
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
    raise SystemExit(f'{PROG}: nothing needs you here about {tid!r}{project_in()}: `{PROG} waiting --all` lists what '
                     f'does; another project\'s item is answered in its own control session')


def _parked_ask(tid: str, todo) -> str:
    """B767: the question task `tid`, open in `todo`, asked with `run ask` and that the run has not blocked yet
    (`asks.block_asks`); '' for none."""
    from agent_runner.asks import pending_ask  # here: asks imports this module
    open_now = any(t.rstrip('.') == tid and box == ' ' for _, box, t, _, _ in iter_tasks(lines(todo)))
    return pending_ask(tid, todo) if open_now else ''


def _ask_or_parked(tid: str, todo) -> tuple[str, str, str, str, str, str, bool]:
    """`_ask`, and (B767) a question asked with `run ask` whose block is not in the plan yet, as its block will read."""
    try:
        return _ask(tid, todo)
    except SystemExit:
        if not (q := _parked_ask(tid, todo)):
            raise
    what = URL.sub('', q.split(' — ')[0]) if URL.search(q) else q.split(' — ')[0]
    return 'DECIDE', tid, '', ' '.join(what.split()).rstrip(' :,;'), '', '', False


def _answer(tid: str, text: str, todo) -> None:
    """Reopen `tid` with the person's answer noted. B767: an ask the run has not blocked yet is settled with it, so
    `block_asks` never files it after."""
    from agent_runner.asks import settle_ask
    if _parked_ask(tid, todo):
        note(tid, text, todo=todo)
        _clear_ask(tid, todo)
    else:
        unblock(tid, text, todo=todo)
    settle_ask(tid, todo)


def _not_told(tid: str, text: str, c) -> str:
    """B767: what to run with a `tell` that reached no session: when `tid` asks the person, its question and the
    commands that answer it (never run from here); else the note for its next attempt."""
    said = shlex.quote(text)
    try:
        label, _, _, what, url, _, _ = _ask_or_parked(tid, c.todo)
    except SystemExit:
        if (where := run_on(c, tid)) and (q := ending_ask(c, tid, where)):  # B770: not parked in time
            return (f'. {tid} asks the person: {q}\nOnly if your text answers that, once the session in {where} has ended '
                    f'(`{PROG} {tid}` then shows the question): `{PROG} confirm {tid} {said}`, or, to have something '
                    f'else done: `{PROG} change {tid} {said}`')
        return f' (`{PROG} note {tid} TEXT` notes it for the next attempt)'
    return (f'. {tid} {"is stuck and waits on" if label == STUCK else "asks"} the person: {what}{f" {url}" if url else ""}\n'
            f'Only if your text answers that: `{PROG} confirm {tid} {said}`, or, to have something else done: '
            f'`{PROG} change {tid} {said}`')


def project_in() -> str:
    """F33: ' in <project>' (the main checkout's name) for a message about this project only; '' outside a repo.
    confirm, change and shelve read only this project's plan, never another's (a person's call)."""
    try:
        from agent_runner.config import main_checkout
        return f' in {main_checkout().name}'
    except (OSError, SystemExit, subprocess.SubprocessError):
        return ''


def confirm(tid: str, said: str = '', todo=None, done=None) -> str:
    """The person's yes ("it worked", or what they saw): a CONFIRM is ticked with it noted, a DECIDE or BLOCKED
    reopens with the answer noted (so a run picks it up), a concept is approved. Returns what happened."""
    from agent_runner.plan_concepts import approve  # C52: the module imports this one
    todo, done = ensure(todo, done)
    label, t, k, what, _, _, _ = _ask_or_parked(tid, todo)
    if label == 'CONCEPT':
        return f'approved: {approve(tid, said, todo=todo)} is open now, and a run starts it' + freed_line()
    if label == 'CONFIRM':
        unblock(t, f'confirmed by you ({what}): {said or "it worked"}', todo=todo)
        tick(t, todo=todo, done=done)
        return f'confirmed and ticked {t}'
    if label == STUCK:  # B35
        unblock(t, f'you said, on stuck ({what}): {said or "try again"}', todo=todo)
        return f'{t} is open again with your answer noted, and a run starts it'
    _answer(t, f'your answer ({label} {what}): {said or "done"}', todo)
    return f'{t} is open again with your answer noted, and a run starts it'


def change(tid: str, instead: str, todo=None, done=None) -> str:
    """'Do X instead': the task reopens with `instead` noted; a concept is sent back (`revise`)."""
    from agent_runner.plan_concepts import revise  # C52: the module imports this one
    todo, done = ensure(todo, done)
    try:
        label, t, k, what, _, _, _ = _ask_or_parked(tid, todo)
    except SystemExit:  # B19: an open task (one a slot may be running) takes a change too: noted, stays open
        ls = list(lines(todo))
        if tid not in open_ids(ls) or ls[_find(ls, tid)].lstrip().startswith('- [~]'):
            raise
        note(tid, f'you said: do this instead: {instead}', todo=todo)
        return f'{tid} has your change noted'
    if label == 'CONCEPT':
        return f'{revise(tid, instead, todo=todo, done=done)} is open again with your changes noted'
    _answer(t, f'you said, on {"stuck" if label == STUCK else label} {what}: do this instead: {instead}', todo)
    return f'{t} is open again with your change noted, and a run starts it'


# --- B27: "Needs you": each ask in everyday words, with its age --------------------------------------------
#
# What waits on a person shows under "Needs you" as one plain line each: what is asked and
# what to reply ("Check the push reached your phone - reply yes/no"), its link on a line of its own, oldest
# first with its age. The caps labels stay in TODO.md and in `asks`, for the tools; the person never reads
# them. A block on a person is stamped `(asked YYYY-MM-DD HH:MM)` when it is filed, which is where the age
# comes from (older blocks have none and sort first). A reply that names no id ("yes", "B", "later") is mapped
# to its item by the session the person talks to (control or feed), which then runs confirm, change or
# shelve with that id, and asks the person when it cannot tell which item (C5: no regex guessing here).

ASKED = re.compile(r' ?\(asked (\d{4}-\d\d-\d\d \d\d:\d\d)\)')
REPLY_HINT = {'CONCEPT': 'reply A/B/C', 'CONFIRM': 'reply yes/no', 'DECIDE': 'reply with your answer',
              'BLOCKED': 'reply done once it is', 'PITCH': 'reply approve or not this',
              'TOOL': 'this clears once it is back', 'READY': 'reply looks good, change it or not now', 'PR': 'this clears once it is merged or closed', 'STUCK': 'reply with what to do'}


def needs_cfg() -> dict:
    """Needs you's heading and ages (C14: constants) and its order (`[run] needs_order`)."""
    try:
        order = cfg().run.get('needs_order') or 'oldest'
    except SystemExit:  # outside a repository: the default
        order = 'oldest'
    return {'heading': 'Needs you', 'ages': True, 'order': order}


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


def plain_ask(label: str, what: str, title: str, sheet: bool = False) -> str:
    """One ask in everyday words, without its caps label: what is asked, then what to reply. `sheet`: a DECIDE
    with a pick sheet (F18), whose answer is picked on the sheet's page or 'go' for the recommended set."""
    if sheet and label == 'DECIDE':
        said = (what or title or 'Pick on the sheet').rstrip(' .')
        said = re.sub(r'[\s,;:]+(see|at|via|here|on the sheet)$', '', said)
        return f'{said[:1].upper() + said[1:]}. Pick on the sheet or reply go'
    if label == 'CONCEPT':
        said = f'Pick an option for {_lower_first(title)}' if title else 'Pick an option on the page'
    else:
        said = (what or title or 'Have a look').rstrip(' .')
        said = re.sub(r'[\s,;:]+(see|at|via|here)$', '', said)  # what led to a link that now has its own line
        said = said[:1].upper() + said[1:]
        if label == STUCK:  # B35: it asks nothing itself, so say it is stuck
            said = f'Stuck: {_lower_first(said)}'
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
    """`items` (asks tuples, id second) in `[run] needs_order`: 'oldest' first (unstamped ones are older still),
    'newest' first, or 'plan' (as given: TODO.md's order). The sort is stable, so equal ages keep plan order."""
    if order == 'plan':
        return list(items)
    key = lambda a: stamps.get(a[1], '')
    return sorted(items, key=key, reverse=order == 'newest')


NEEDS_WIDTH = 72  # chars of an ask's first sentence `needs` keeps, before its reply hint


def needs_lines(items: list, sheet=lambda tid: False) -> list[str]:
    """F44 `needs`: per ask that is not shelved one 'ID - what to do' line ('R7 - pick which config changes to
    build'; the ask's own 'reply with …' kept: 'R6 - Windows desktop check, reply with what you saw'), then one summary line ('2 things need you', 'Nothing needs you'). `items`
    are asks tuples in the order to show; `sheet(tid)` says a DECIDE has a pick sheet. No links, bodies or notes.
    B223a: a DECIDE shows its question, not the first sentence."""
    from agent_runner import need_detail
    out = []
    for label, tid, k, what, _url, title, sh, *_ in items:
        if sh:
            continue
        own = re.search(r'[\s,;:.–—-]*\b(reply (?:with|yes|no|done|go|A/)[^.;]*)[.;]?\s*$', what or '')
        what = what[:own.start()] if own else what  # the agent's own 'reply with …' replaces the generic hint
        asked = ''
        if label == 'DECIDE':
            what = need_detail.decide_options(tid, what or '')[1]
            asked = need_detail.question_of(what)
            what = asked or need_detail.asks_file(tid).get('summary') or what
        said = plain_ask(label, what, title, label == 'DECIDE' and sheet(tid))
        generic = f' - {REPLY_HINT.get(label, "reply when you can")}'
        said = said[:-len(generic)] if said.endswith(generic) else \
            said.replace('. Pick on the sheet', ', pick on the sheet')  # a pick sheet's ask keeps its how
        hint = own.group(1) if own else ''  # only the agent's own words: the generic one is noise here
        said = said if asked else re.split(r'(?<=[.?!])\s', said, maxsplit=1)[0].rstrip('.')  # its first sentence
        if len(said) > NEEDS_WIDTH and not asked:  # a question is whole: its end is what is asked
            cut = said[:NEEDS_WIDTH].rsplit(' ', 1)[0]
            if cut.count('`') % 2 and (end := said.find('`', len(cut))) >= 0:  # B150: never cut inside a command
                cut = said[:end + 1]
            said = cut if cut == said else cut.rstrip(' :,;-(') + '…'
        said = what.strip()[:1] + said[1:] if what and said[:1].lower() == what.strip()[:1].lower() else _lower_first(said)
        out.append(f'{k or tid} - {said}' + (f', {hint}' if hint else ''))
    n = len(out)
    return out + ['Nothing needs you' if not n else '1 thing needs you' if n == 1 else f'{n} things need you']


# --- C11: the file channels a command uses to ask the run that is up for something ---------------------------
#
# A request: the command writes <notes>/<kind>/<ID>.json and waits for the run's <ID>.done (`request`); the
# run lists what is asked of it each pass (`requests`) and answers each (`respond`), which takes the request
# away. halt and tell go this way. A post: lines appended to <notes>/<name> (KEYS, POWER), which the run
# takes once on its next pass (`take`) and answers nowhere. STOP and STOP.force stay plain files.

def channel(c, kind: str) -> Path:
    """<notes>/<kind>, the folder of `kind`'s requests (notes() makes it)."""
    return c.notes(kind, 'x').parent


def request(c, kind: str, tid: str, payload: dict, wait: float) -> str | None:
    """Ask the run for `payload` about `tid` and return its answer (the .done file's text), or None when it has
    not answered within `wait` s. The request stays for the run to find later."""
    import json
    import time
    d = channel(c, kind)
    done = d / f'{tid}.done'
    done.unlink(missing_ok=True)
    tmp = d / f'{tid}.json.tmp'
    tmp.write_text(json.dumps({**payload, 'at': time.time()}), encoding='utf-8')
    os.replace(tmp, d / f'{tid}.json')
    end = time.time() + wait
    while True:
        try:
            said = done.read_text(encoding='utf-8')
            done.unlink(missing_ok=True)
            return said
        except OSError:
            pass
        if time.time() >= end:
            return None
        time.sleep(0.25)


def requests(c, kind: str) -> dict[str, dict]:
    """{ID: payload}: the `kind` requests waiting for the run; an unreadable one or one not a JSON object is
    skipped."""
    import json
    out = {}
    for f in channel(c, kind).glob('*.json'):
        try:
            req = json.loads(f.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if isinstance(req, dict):
            out[f.stem] = req
    return out


def respond(c, kind: str, tid: str, text: str) -> None:
    """The run's answer to `tid`'s `kind` request, for the command waiting on it; the request is taken away."""
    d = channel(c, kind)
    tmp = d / f'{tid}.done.tmp'
    tmp.write_text(text, encoding='utf-8')
    os.replace(tmp, d / f'{tid}.done')
    (d / f'{tid}.json').unlink(missing_ok=True)


def post(c, name: str, *lines: str) -> None:
    """Append `lines` to <notes>/<name>, for the run to `take` on its next pass."""
    with open(c.notes(name), 'a', encoding='utf-8') as f:
        f.write(''.join(f'{x}\n' for x in lines))


def take(c, name: str) -> list[str]:
    """The non-blank lines posted to <notes>/<name>, stripped, taken once. Moved aside before it is read, so a
    line posted meanwhile goes in a new file for the next pass."""
    f = c.notes(name)
    taken = f.with_name(f'{name}.{os.getpid()}')
    try:
        f.replace(taken)
    except OSError:
        return []
    try:
        return [x for l in taken.read_text(encoding='utf-8').splitlines() if (x := l.strip())]
    finally:
        taken.unlink(missing_ok=True)


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
    return channel(c, 'halt')


def run_on(c, tid: str) -> str:
    """What a run up in this repository is doing with `tid` ('s2', 'merging'), from its STATE; '' for nothing
    (no run up, or the task is none of its)."""
    import json

    if not _run_up(c):
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
    where = run_on(c, tid)
    if not where:
        return ''
    if (said := request(c, 'halt', tid, {'how': how}, HALT_WAIT if wait is None else wait)) is not None:
        return said.strip()
    if where == 'merging':
        return f'asked the run not to land {tid}: unless its merge is already landing, task/{tid} is deleted unmerged'
    return (f'asked the run to stop {where}: within seconds it ends that session, deletes task/{tid} and its work'
            + (', then starts it again from the new text' if how == 'change' else '')
            + f' (`{c.command} since` shows it)')


# --- F16: tell a running agent something, without stopping it ---------------------------------------------
#
# A slot runs an interactive session in a hidden terminal, where text typed while it works queues for its next
# turn. `plan tell ID TEXT` (and `plan change ID TEXT` on a running task, unless --restart) leaves a request in
# <notes>/tell/<ID>.json ({"how": "tell" | "change", "text": …}); the run (`runner.tells`, every pass of its
# loop) finds the slot's session, pastes the message into it and presses Enter, and answers in
# <notes>/tell/<ID>.done ({"told": true|false, "msg": …}). With no live session (Windows, a cut-off session
# waiting to resume, the task merging) it answers told false and `change` falls back to the B19 halt. B770: a slot
# whose agent has just run `run ask` is typed nothing: the answer waits for the ask to be parked, then is told false;
# `tell` prints the question, and `change` (noted in the plan) does too and halts nothing.

TELL_WAIT = 30.0  # s `tell`/`change` wait for the run to pass the message on


def tell_dir(c) -> Path:
    return channel(c, 'tell')


def tell_text(how: str, text: str) -> str:
    """What the agent reads in its pane."""
    return f'Your task changed: {text}' if how == 'change' else f'A note on your task, from the person running this run: {text}'


def ending_ask(c, tid: str, slot: str) -> str:
    """B770: the question of task `tid` while `slot` ('s2') holds the end mark of its `run ask`: its session is ending
    and the ask is not parked yet. '' for none."""
    import json
    try:
        end = json.loads(c.notes(f'slot{slot[1:]}.end').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return ''
    if not isinstance(end, dict) or end.get('how') != 'ask' or end.get('tid') != tid:
        return ''
    return str(end.get('text') or 'a question with no text')


def _asks_now(c, tid: str, where: str) -> bool:
    """B770: does `tid` ask the person: its session in slot `where` is ending on a `run ask`, or it is parked or blocked."""
    if ending_ask(c, tid, where):
        return True
    try:
        return _ask_or_parked(tid, c.todo)[1] == tid  # not another task that waits on concept `tid`
    except SystemExit:
        return False


def tell(c, tid: str, text: str, how: str = 'tell', wait: float | None = None) -> tuple[bool | None, str]:
    """Ask the run to type `text` into the pane of the slot running `tid`. (True, 'told s1 (F297)') when it
    did; (False, why) when it could not (no live pane, or no slot of a run runs it: then why is ''); (None,
    what was asked) when the run did not answer within `wait` s."""
    from agent_runner.plan_concepts import told_file  # C52: the module imports this one
    import json
    where = run_on(c, tid)
    if not where or where == 'merging':
        return False, ''
    said = request(c, 'tell', tid, {'how': how, 'text': text}, TELL_WAIT if wait is None else wait)
    try:
        got = json.loads(said) if said is not None else None
    except ValueError:
        got = None
    if not isinstance(got, dict) and _asks_now(c, tid, where):  # B770
        return False, f'{where} ({tid}) was not told: its session asked the person'
    if not isinstance(got, dict) or got.get('told'):
        with open(told_file(c, tid), 'a', encoding='utf-8') as f:  # B221
            f.write(' '.join(text.split()) + '\n')
    if isinstance(got, dict):
        return bool(got.get('told')), str(got.get('msg', ''))
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


# --- F177: a task too big for one session -----------------------------------------------------------------------

OUTCOME = re.compile(r'\((\d{1,2})\)|(?<!\S)(\d{1,2})[.)](?=\s)')  # (1), 1. or 1)
SIZE_CHARS = 400  # characters of text that weigh as much as one code file; a numbered outcome weighs as two


def outcomes(text: str) -> int:
    """How many numbered outcomes `text` lists: (1) (2) (3), 1. 2. or 1) 2), each list counted from its 1; a lone
    number is no list."""
    n = run = 0
    for a, b in OUTCOME.findall(text):
        k = int(a or b)
        if k == run + 1:
            run = k
        elif k == 1:
            n, run = n + (run if run > 1 else 0), 1
    return n + (run if run > 1 else 0)


def size(blk: list[str], docs: list[str] = ()) -> tuple[int, int, int, int]:
    """(size, code files, numbered outcomes, characters of text) of a task's lines: each file on it that `docs`
    (`[run] docs_files`) does not match is 1, a numbered outcome 2, SIZE_CHARS of text 1. Its long form is not
    read: reference text there makes no task bigger."""
    from agent_runner.done import docs_only
    files = [f for f in files_on_line('\n'.join(blk)) if not docs_only([f], docs)]
    text = '\n'.join([prose(blk[0]), *blk[1:]]) if blk else ''
    n = outcomes(text)
    return len(files) + 2 * n + len(text) // SIZE_CHARS, len(files), n, len(text)


def too_big(tid: str, c, todo) -> str:
    """Why open task `tid` is over `[run] task_size` (0 is off): 'size 37, over 10: 19 code files, …'; else ''.
    Never a concept or a release (they build nothing), nor a task already `(split into …)` parts."""
    ls = lines(todo)
    i = next((i for i, l in enumerate(ls) if (m := ITEM.match(l)) and m.group(3).rstrip('.') == tid), None)
    return '' if i is None else _big(_item_block(ls, i), tid, c)


def _big(blk: list[str], tid: str, c) -> str:
    """`too_big` of a task's lines `blk`."""
    from agent_runner.plan_concepts import concept  # C52: the module imports this one
    try:
        most = int(c.run.get('task_size') or 0)
    except (TypeError, ValueError):
        return ''
    if most <= 0 or concept(tid) or release(tid):
        return ''
    if ITEM.match(blk[0]).group(2) == 'x' or SPLIT.search(blk[0]):
        return ''
    n, files, parts, chars = size(blk, c.run.get('docs_files') or [])
    if n <= most:
        return ''
    return (f'size {n}, over [run] task_size {most}: {files} code file{"s" * (files != 1)}, {parts} numbered '
            f'outcomes, {chars:,} characters of text')


# B196: `plan add` of a task too big for one session writes `| split-by: <when>` on its line, and no run starts it
# before then, so its author can split it. On the line, so every machine's run and a branch's merge carry it.
SPLIT_BY = 'split-by'
SPLIT_HOLD = 300  # seconds, fixed: a session that never splits its task only delays it


def split_stamp(now: float | None = None) -> str:
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime((time.time() if now is None else now) + SPLIT_HOLD))


def split_left(line: str, now: float | None = None) -> float:
    """Seconds a task's line still holds it for its author to split it (B196); 0 for none, or a time that does not
    read or lies over two SPLIT_HOLDs ahead (another machine's wrong clock)."""
    try:
        by = calendar.timegm(time.strptime(fields(line).get(SPLIT_BY, [''])[0], '%Y-%m-%dT%H:%M:%SZ'))
    except (ValueError, IndexError):
        return 0
    left = by - (time.time() if now is None else now)
    return left if 0 < left <= 2 * SPLIT_HOLD else 0


def split_in(left: float) -> str:
    """When a held task starts, for `left` seconds: 'starts in 4 min if it is not'."""
    return f'starts in {math.ceil(left / 60)} min if it is not'


def split_waits(ls: list[str], now: float | None = None, busy=()) -> dict[str, str]:
    """B196: {task: 'waits to be split, starts in 4 min if it is not'} for the open tasks held for their author,
    but for the `busy` ones (running, or taken by hand) and those that wait for another task."""
    live = {tid for _, box, tid, _, _ in iter_tasks(ls) if box != 'x'}
    return {tid: f'waits to be split, {split_in(left)}' for section, box, tid, _, i in iter_tasks(ls)
            if box == ' ' and tid not in busy and not section.startswith(SKIPPED) and (left := split_left(ls[i], now))
            and not live & (set(waits_on(ls, i)) - {tid})}


def _unheld(line: str) -> str:
    """A task line without its split-by field."""
    return FIELD.sub(lambda m: '' if m.group(1) == SPLIT_BY else m.group(0), line)


def end_split_hold(tid: str, todo=None) -> None:
    """The task is split, or small enough now: a run may start it at once."""
    todo, _ = ensure(todo)
    ls = list(lines(todo))
    i = _find(ls, tid)
    if (now := _unheld(ls[i])) != ls[i]:
        ls[i] = now
        _write(todo, ls)


def big_note(tid: str, x) -> str:
    """What `plan add`, `edit`, `note` and an approval add to their message about a task over the size."""
    why = too_big(tid, x.c, x.todo)
    return why and (f'\n{tid} is too big for one session ({why}). Split it now: `{PROG} add {tid} "<part>" --files …` '
                    f'for each part ({tid}a, {tid}b, …; `--after` a part it needs, never {tid}), then `{PROG} edit '
                    f'{tid} "<title> (split into {tid}a, {tid}b)"`; {tid} ticks itself once its parts land')


def overlap(a: set[str], b: set[str]) -> set[str]:
    """Paths and patterns (`dir/**`, `dir/*.rs`) of `a` that meet `b`'s: equal, one a tail of the other
    (`src/menu.rs` is `app/src/menu.rs`), or one matching the other as a pattern."""
    import fnmatch

    def meet(x: str, y: str) -> bool:
        return (x == y or x.endswith('/' + y) or y.endswith('/' + x)
                or ('*' in x and fnmatch.fnmatch(y, f'*{x}')) or ('*' in y and fnmatch.fnmatch(x, f'*{y}')))
    return {x for x in a for y in b if meet(x, y)}



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


def noted(a: list[str], b: list[str]) -> bool:
    """Whether task block `b` is block `a` with ` — note`s added to its last line, as `note` adds them."""
    return len(a) == len(b) > 0 and a[:-1] == b[:-1] and b[-1].startswith(a[-1] + ' — ')


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
    for k in [k for k in io if k in it and k not in ib and noted(io[k][1], it[k][1])]:  # B33: theirs = ours + notes
        io[k] = (io[k][0], it[k][1])  # one task, which theirs noted (`join.fold_doubles`): ours' place, theirs' words
    for k in [k for k in io if k in it and k not in ib and noted(it[k][1], io[k][1])]:  # B829: ours = theirs + notes
        it[k] = (it[k][0], io[k][1])
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
    if not gd or gd != cd or os.path.exists(os.path.join(gd, 'MERGE_HEAD')):
        return
    if rb := next((d for d in ('rebase-merge', 'rebase-apply') if os.path.isdir(os.path.join(gd, d))), None):
        print(f'! plan edit left uncommitted and unpushed: a rebase is in progress in {root} (.git/{rb}); '
              f'finish it (git rebase --continue) or drop it (git rebase --abort)', file=sys.stderr)
        return
    g('add', '--', *map(str, paths))  # a fresh plan/ is untracked, and commit -- PATH skips those
    if not g('commit', '-q', '-m', f'plan: {msg}', '--', *map(str, paths)).returncode and (why := _push(root)):
        print(f'! plan edit committed here but not pushed: {why}', file=sys.stderr)


def _run_up(c) -> bool:
    """A run holds `<notes>/run.lock` in this repository (no lock file is made just to look)."""
    from agent_runner import plat
    if not c.notes('run.lock').exists():
        return False
    if f := plat.lock(c.notes('run.lock')):
        f.close()
        return False
    return True


def _keeps_merges_local(c) -> str:
    """Why a merge does not push the shared branch here (land.pushes_main's rule, B36), or '' when it does:
    a hand edit's push then would publish those merges too (B86)."""
    if not c.raw['git']['push_merge']:
        return '[git] push_merge is off'
    if not c.run['test'] and 'push_merge' not in c.given.get('git', ()):
        return 'no test gate ([run] test is empty) and [git] push_merge is not set'
    return ''


def _push(root: Path) -> str:
    """B73: publish a hand edit's commit on the shared branch to `[git] push`, fast-forward only. Rejected:
    one rebase onto the remote, or a merge of it when ids clashed and were renumbered (not while a run is up here: its merges land in this checkout, and its next
    merge publishes main), then push again. Returns why it could not, or '' (pushed, or nothing to push)."""
    from agent_runner import gitops
    g, c = partial(git, cwd=root), cfg(root)
    remote = c.push_remote
    if not remote or g('remote', 'get-url', remote).returncode:
        return ''
    branch = g('branch', '--show-current').stdout.strip()
    if not branch or branch != gitops.shared_name(root, remote):
        return ''  # a branch of your own: yours to push
    if c.approve:  # F98: it goes out with the next approved pitch
        return ''
    if c.pr:  # F419
        return f'PR mode never pushes {branch}'
    if why := _keeps_merges_local(c):  # B86: pushing would publish the merges a run kept local
        return f'{why}: merges stay local, and this edit with them; to publish them: git push {remote} {branch}'
    net = gitops._net(root)
    if not (r := net('push', '-q', remote, branch)).returncode:
        return ''
    why = (r.stderr.strip().splitlines() or ['no message'])[-1][:200]
    if _run_up(c):
        return f'{remote} refused it ({why}); a run is up here, and its next merge publishes {branch}'
    if (f := net('fetch', '-q', remote, branch)).returncode:
        return f'offline? ({(f.stderr.strip().splitlines() or [why])[-1][:200]})'
    if g('status', '--porcelain', '--untracked-files=no').stdout.strip():
        return f'{remote}/{branch} has moved, and uncommitted changes here stop a rebase onto it'
    if not c.plan_external:
        install_driver(root, [p.relative_to(c.root).as_posix() for p in (c.todo, c.done)])
    up, was = f'refs/remotes/{remote}/{branch}', g('rev-parse', 'HEAD').stdout.strip()
    if g('rev-parse', '-q', '--verify', up).stdout != g('rev-parse', 'FETCH_HEAD').stdout:
        up = 'FETCH_HEAD'
    from agent_runner import join  # it reads this module
    renumbered = join.renumber_plan(c, root, up)
    # B829: merged, as a rebase would replay the edits made under the old ids; so too with an earlier such merge
    # that was never pushed
    if renumbered or g('rev-list', '--merges', '-n1', f'{up}..HEAD').stdout.strip():
        if g('merge', '-q', '--no-edit', up).returncode:
            g('merge', '--abort')
            g('reset', '-q', '--keep', was)  # the renumbering goes with the merge it was for
            return f'{branch} and {remote}/{branch} have diverged and do not merge cleanly; pull and push by hand'
        for then in renumbered:
            then()
    elif g('rebase', '-q', 'FETCH_HEAD').returncode:
        g('rebase', '--abort')
        return f'{branch} and {remote}/{branch} have diverged and do not rebase cleanly; pull and push by hand'
    if (r := net('push', '-q', remote, branch)).returncode:
        return (r.stderr.strip().splitlines() or ['no message'])[-1][:200]
    return ''


EDITS = ('tick', 'block', 'reopen', 'unblock', 'move', 'add', 'note', 'archive', 'drop', 'approve', 'revise',
         'confirm', 'change', 'shelve', 'unshelve', 'restore', 'edit', 'restyle', 'concept',
         'hold', 'unhold', 'cancel')


WORKTREE_ENV = 'AGENT_RUNNER_WORKTREE'  # B103: a slot's own worktree, set in its pane (slots.slot_env)


def other_project(c, prog: str = '', cmd: str = '') -> str:
    """B103: the refusal when a slot's agent writes the plan from another project's checkout (a `cd` elsewhere,
    and the project is found from the current directory), else ''. The slot's worktree is $AGENT_RUNNER_WORKTREE;
    unset or empty (no slot, or a person's shell), nothing is checked."""
    wt = os.environ.get(WORKTREE_ENV, '')
    if not wt:
        return ''
    from agent_runner.config import main_checkout
    try:
        mine, here = main_checkout(wt), main_checkout(c.root)
    except SystemExit:  # the worktree is gone or no checkout: nothing to compare against
        return ''
    if mine == here:
        return ''
    if cmd == 'add':  # B785: the person's answer to a control session's question allows it
        from agent_runner.control_other import may_add
        if may_add(wt, mine, here):
            return ''
    return (f'{prog or PROG}: nothing written: the current directory is in {here.name} ({c.root}), but this slot '
            f'works on {mine.name}. Run the command from its own worktree: cd {wt}')


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ('-h', '--help', 'help'):
        print(HELP)
        return 0
    c = cfg()
    if argv[:1] and (argv[0] in EDITS or argv[0] == 'goal' and len(argv) > 1) and (why := other_project(c, '', argv[0])):
        print(why, file=sys.stderr)
        return 3
    if argv[:1] == ['tell']:  # F16: no plan edit, so no lock
        return _tell(c, argv[1:])
    if argv[:1] == ['cancel']:  # F426d: the run stops it first, outside the lock, as it reads the plan; then it is parked
        from agent_runner import cancel
        rc, argv = cancel.main(c, argv[1:])
        if rc:
            return rc
    elif argv[:1] == ['hold'] and len(argv) > 1:  # F480: a slot of this run on it: cancelled first, then held
        from agent_runner import cancel, row_hold
        if row_hold.slot_on(c, argv[1]):
            rc, argv = cancel.main(c, [argv[1], cancel.YES])
            if rc:
                return rc
    restart = False
    if argv[:1] == ['change'] and '--restart' in argv[2:]:
        restart, argv = True, [a for a in argv if a != '--restart']
    editing = argv[:1] and (argv[0] in EDITS or argv[0] == 'goal' and len(argv) > 1)
    if not c.plan_external:
        if not editing:
            return _main(argv, c)  # a read of the checkout's own file needs no lock
        with plansync.locked(c):  # two sessions filing at once would take the same id, and one write drop the other
            rc = _main(argv, c)
    else:
        with plansync.locked(c):  # a read pulls too, so it sees other people's edits
            plansync.pull(c, force=bool(editing))
            rc = _main(argv, c)
    if not argv:  # B821: the index, an edit of nothing
        return rc
    if not rc and argv[0] == 'edit' and len(argv) > 2:  # F45: a slot running it hears of it, as on a change
        got = section(ensure()[0], argv[1])[:1]
        now = re.sub(r'^\s*- \[.\] \*\*[^*]+\*\*\s*', '', _unblocked(got[0])) if got else ''
        argv = ['change', argv[1], f'it now reads: {now}']
    if not rc and argv[0] == 'restyle':  # F19: outside the lock, so the run can read the plan as it parks them
        for said in park_running(c):
            print(said)
    if not rc and argv[0] in ('drop', 'change') and len(argv) > 2:
        # B19: outside the lock, so the run can read the plan while it stops and restarts the slot
        if argv[0] == 'change' and not restart:  # F16: tell the agent instead of stopping it
            told, said = tell(c, argv[1], ' '.join(argv[2:]), 'change')
            if told is not False:
                print(said)
                return rc
            if said and _asks_now(c, argv[1], run_on(c, argv[1])):
                print(said + _not_told(argv[1], ' '.join(argv[2:]), c))  # B770: never halt it, its work waits too
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
    if told is None:  # B767: not answered in time, and it may ask the person by now: then no slot runs it
        try:
            _ask_or_parked(tid, c.todo)
            told = False
        except SystemExit:
            pass
    if told is False:
        print(f'{PROG}: {said or f"{tid} is not running: no slot of a run here is on it"}'
              + _not_told(tid, text, c), file=sys.stderr)
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

    if (a := _parse_command(argv)) is not None:
        from agent_runner import control_settled  # F160: the chats about the item it settles are told
        return control_settled.noting(c, a, todo, lambda: a.run(a, SimpleNamespace(
            c=c, plan_dir=plan_dir, todo=todo, done=done, say=say)))

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
        rel, shown = _releases(c, todo)  # F185
        out, cl = rel + [l for l in index(todo) if l[4:] not in shown], plansync.claims(c)
        out = [f'{l}  [{plansync.label(cl[t])}]' if (t := l.rsplit(' ', 1)[-1]) in cl else l for l in out]
        tw = _tool_waits(c, todo)
        tw.update(_split_waits(c, todo))
        tw.update({t: w for t, w in until_waits(lines(todo)).items() if t not in tw})
        out = [f'{l}  [{tw[t]}]' if (t := l.rsplit(' ', 1)[-1]) in tw else l for l in out]
    else:
        # a heading named exactly that, in any file, before one that only contains it (`hst` before `hst-data`)
        out = next((o for ex in (True, False) for p in paths if (o := section(p, argv[0], ex))), [])
    if not out:
        print(f'{PROG}: nothing named {argv[0]!r} — run `{PROG}` for the index', file=sys.stderr)
        return 1
    print('\n'.join(out))
    if argv and TASK_ID.fullmatch(argv[0]):  # `after: all` (F35), `all above`: what it still waits on
        for l in last_lines(todo):
            if l.startswith(f'{argv[0]} waits '):
                print(l)
        if said := (until_waits(lines(todo)) | _split_waits(c, todo) | _tool_waits(c, todo)).get(argv[0]):
            print(f'{argv[0]} {said}')
        if q := _parked_ask(argv[0], todo):  # B767
            print(f'{argv[0]} asks the person (the run has not listed it yet): {q}')
    return 0


# --- the subcommands (C12) -------------------------------------------------------
# Each takes the parsed words `a` and `x` (c, plan_dir, todo, done, and say: print, then commit the edit) and
# returns the exit code. Their messages and codes are what agents read: keep them word for word.

def _text(a) -> str:
    return ' '.join(a.rest)


def _p_tick(a, x):
    n = tick(a.id)
    return x.say(f'ticked {a.id}' + (f', moved {n} line(s) to {x.plan_dir.name}/DONE.md' if n else ''))


def _p_drop(a, x):
    from agent_runner.plan_drop import drop  # C52: the module imports this one
    from agent_runner import release_moves
    if a.id == release_moves.NEXT:
        print(release_moves.drop_next(x.todo, _text(a)))
        return 0
    by = None
    if a.rest and a.rest[0] in ('--duplicate-of', '--overtaken-by'):  # B772
        if len(a.rest) < 3:
            print(f'{PROG}: drop {a.id} {a.rest[0]} <ID> WHY: name the other task, then why', file=sys.stderr)
            return 2
        by, a.rest = a.rest[1], [a.rest[0][2:].replace('-', ' ') + ' ' + a.rest[1] + ':', *a.rest[2:]]
    whole = drop(a.id, _text(a), by=by)
    skipped = release(a.id) and release_moves.removed(a.id)
    return x.say(f'dropped {a.id}' + (f': that cut is skipped, and the count starts from zero (`{PROG} restore {a.id}` '
                                      'undoes it)' if skipped else '') + ''.join(
        f'\nno part of {k} landed, so {k} is one whole task again (`{PROG} {k}`: edit it if its text lacks the work '
        f'the parts held)' for k in whole))


def _p_restore(a, x):
    from agent_runner.plan_drop import restore  # C52: the module imports this one
    from agent_runner import release_moves
    if a.id == release_moves.NEXT:
        print(release_moves.restore_next())
        return 0
    blocked = restore(a.id, a.rest[0] if a.rest else 'top', ' '.join(a.rest[1:]) or None)
    if release(a.id):
        release_moves.restored(a.id)
    return x.say(f'restored {a.id}: {"blocked again, as it was," if blocked else "open again"} in {Path(x.todo).name}')


def _p_block(a, x):
    after, until, rest = None, None, list(a.rest)
    if '--until' in rest[:3] or '--until' in rest[-2:]:  # before the why (--after too), or after it
        at = rest.index('--until') if '--until' in rest[:3] else len(rest) - 1 - rest[::-1].index('--until')
        until = rest[at + 1:at + 2]
        del rest[at:at + 2]
    if rest[:1] == ['--after'] and len(rest) > 2:
        after, rest = [t for t in rest[1].split(',') if t], rest[2:]
    if '--until' in rest:
        print(f'{PROG}: block {a.id}: --until CHECK[,CHECK] goes once, before the why or after it, with no space after '
              'a comma. Nothing blocked.', file=sys.stderr)
        return 2
    if until is not None and not ' '.join(rest).strip():
        print(f'{PROG}: block {a.id} --until CHECK needs a why. Nothing blocked.', file=sys.stderr)
        return 2
    block(a.id, ' '.join(rest), after=after, until=until)
    if ' '.join(rest).lstrip().startswith('DECIDE: '):
        _filed_here(x.c, a.id)
    return x.say(f'blocked {a.id}')


def _p_reopen(a, x):
    got = reopen()
    return x.say('\n'.join([f'reopened {t} ({", ".join(ids)} landed)' for t, ids in got] or ['nothing to reopen']
                           + last_lines()))


def _p_unblock(a, x):
    unblock(a.id, _text(a))
    return x.say(f'unblocked {a.id}')


def _p_move(a, x):
    from agent_runner import release_moves, row_hold
    where, ref = a.rest[0], ' '.join(a.rest[1:]) or None
    if a.id == release_moves.NEXT:
        tid = release_moves.move_next(where, ref, x.todo)
        return x.say(f'moved {a.id} {_text(a)}: it is {tid} now, and waits for the tasks above it')
    _find(lines(x.todo), a.id)
    order = where in ('before', 'after') and not release(a.id) and not any(  # B824b: its place alone, also while it runs
        t == ref and section.startswith(PARKED) for section, _, t, _, _ in iter_tasks(lines(x.todo)))
    if not order and (why := row_hold.under_way(x.c, a.id)):
        print(f'{PROG}: {a.id} cannot be moved: {why}', file=sys.stderr)
        return 1
    move(a.id, where, ref)
    if release(a.id):
        release_moves.rewait(a.id, x.todo)
        return x.say(f'moved {a.id} {_text(a)}: it waits for the tasks above it')
    return x.say(f'moved {a.id} {_text(a)}')


def _p_approve(a, x):
    from agent_runner.plan_concepts import approve  # C52: the module imports this one
    bid = approve(a.id, _text(a))
    return x.say(f'approved: {bid} is open now, and a run starts it' + freed_line() + big_note(bid, x))


def _filed_here(c, *ids):
    """F209a: the control session this command runs in filed `ids`, so it is about them."""
    from agent_runner import control_settled
    control_settled.filed(c, ids)


def concept_copy(c, url: str, kid: str) -> bool:
    """B882: give concept `kid` the local copy of its https page that publish-page kept (concepts/<tid>.html beside
    a <tid>.url holding the same URL), so the run page finds its options. False when there is none or it has one."""
    d = c.notes('concepts', 'x').parent
    if not url.startswith('http') or (d / f'{kid}.html').is_file():
        return False
    for u in sorted(d.glob('*.url')):
        try:
            same = u.read_text(encoding='utf-8').strip() == url.strip()
        except OSError:
            continue
        if same and u.stem != kid and (src := d / f'{u.stem}.html').is_file():
            (d / f'{kid}.html').write_bytes(src.read_bytes())
            (d / f'{kid}.url').write_text(url.strip() + '\n', encoding='utf-8')
            return True
    return False


def concept_copy_backfill(c, done) -> list[str]:
    """B882: the concepts already filed with a claude.ai page and no copy get the one publish-page kept."""
    try:
        text = Path(done).read_text(encoding='utf-8')
    except (OSError, TypeError):
        return []
    return [m[1] for m in re.finditer(r'^- \[x\] \*\*(K\d+[a-z0-9]*)\*\*.*concept page: (https?://\S+)', text, re.M)
            if concept_copy(c, m[2], m[1])]


def _p_concept(a, x):
    """`plan concept "TITLE" --page URL [--files A,B]` (F108): file a concept page shown inline, waiting for an OK."""
    from agent_runner.plan_concepts import concept_shown  # C52: the module imports this one
    words, opts, it = [], {}, iter(a.rest)
    for w in it:
        if w in ('--page', '--files'):
            opts[w[2:]] = next(it, '')
        else:
            words.append(w)
    title, page = ' '.join(words).strip(), (opts.get('page') or '').strip()
    local = None
    if x.c and (m := re.fullmatch(r'/concept/([A-Za-z]+\d+[a-z0-9]*)', page)) and \
            (src := x.c.notes('concepts', f'{m[1]}.html')).is_file():  # F406f: no claude.ai page, so the run page's copy
        def local(tid):
            x.c.notes('concepts', f'{tid}.html').write_bytes(src.read_bytes())
            x.c.notes('concepts', f'{tid}.url').write_text(f'/concept/{tid}\n', encoding='utf-8')
            return f'/concept/{tid}'
    if not title or not (local or re.match(r'https?://\S+$', page)):
        print(f'{PROG} concept "<what the page shows options for>" --page <the page\'s URL> [--files A,B]',
              file=sys.stderr)
        return 2
    files = [f for f in re.split(r'[,\s]+', opts.get('files') or '') if f] or None
    kid, bid = concept_shown(title, page, files, todo=x.todo, done=x.done, local=local)
    if x.c and not local:
        concept_copy(x.c, page, kid)  # B882: the copy publish-page kept of this claude.ai page
        concept_copy_backfill(x.c, x.done)
    page = f'/concept/{kid}' if local else page
    _filed_here(x.c, kid, bid)
    head = f'concept {kid} filed, done' if kid != bid else f'{bid} filed'
    return x.say(f'{head}: its build {bid} waits for the OK on {page}; the pick goes through '
                 f'`{PROG} approve {kid} "<option>"` or `{PROG} revise {kid} "<what to change>"`')


def freed_line() -> str:
    """F19: what the last `approve` reopened that its restyle held, for its message ('' for none)."""
    return f'; reopened with the style noted: {", ".join(FREED)}' if FREED else ''


def _p_restyle(a, x):
    """`plan restyle STYLE --page URL [--from ID] [--ui GLOBS] [--tasks IDS] [--files A,B] [--dry]` (F19)."""
    words, opts, it = [], {}, iter(a.rest)
    for w in it:
        if w in ('--page', '--from', '--ui', '--tasks', '--files'):
            opts[w[2:]] = next(it, '')
        elif w == '--dry':
            opts['dry'] = True
        else:
            words.append(w)
    style = ' '.join(words).strip()
    split = lambda k: [v for v in re.split(r'[,\s]+', opts.get(k) or '') if v] or None
    globs, ids = split('ui'), split('tasks')
    if opts.get('dry'):
        got = restyle_targets(globs, ids, x.todo)
        rows = [f'{t}  {run_on(x.c, t) or "queued"}  {title}' for t, title in got]
        print('\n'.join(rows) if rows else 'no queued task touches the interface')
        print('(queued: held until the restyle is approved; sN: parked as wip/<ID> at a clean point, or let land when '
              'already in its test gate; merging: lands in the old style, list it on the restyle page)')
        return 0
    if not style or not opts.get('page'):
        print(f'{PROG} restyle "<the approved style>" --page <the restyle page\'s URL> [--from ID] [--ui GLOBS] '
              f'[--tasks IDS] [--files A,B] [--dry]', file=sys.stderr)
        return 2
    got = restyle(style, opts['page'], opts.get('from') or '', globs, ids, split('files'),
                  running=lambda t: run_on(x.c, t), todo=x.todo, done=x.done)
    _filed_here(x.c, got['rid'], got['build'])
    RESTYLE_PARK[:] = [f'{t}\t{got["rid"]}\t{style}' for t in got['park']]
    said = [f'restyle {got["rid"]} filed (its build {got["build"]} waits for the OK on {opts["page"]})']
    if got['held']:
        said.append(f'held until it is approved: {", ".join(got["held"])}')
    if got['park']:
        said.append(f'running, parked as wip/<ID> at a clean point and held: {", ".join(got["park"])}')
    if got['landing']:
        said.append(f'merging, lands in the old style (list it on the restyle page): {", ".join(got["landing"])}')
    if skipped := [t for t in ids or [] if t not in got['held'] + got['park'] + got['landing']]:
        said.append(f'not held (not open and queued, or a concept or release): {", ".join(skipped)}')
    return x.say('\n'.join(said))


RESTYLE_WAIT = 30.0  # s `restyle` waits for the run to say what it did with each running task


def park_running(c, wait: float | None = None) -> list[str]:
    """Ask the run to park each running task `_p_restyle` held (`loop.restyles`); what it said for each."""
    out = []
    for row in RESTYLE_PARK:
        tid, rid, style = row.split('\t', 2)
        said = request(c, 'restyle', tid, {'rid': rid, 'style': style}, RESTYLE_WAIT if wait is None else wait)
        out.append(said.strip() if said is not None else
                   f'asked the run to park {tid} at a clean point; it has not answered yet (`{c.command} since` shows it)')
    RESTYLE_PARK.clear()
    return out


def _p_revise(a, x):
    from agent_runner.plan_concepts import revise  # C52: the module imports this one
    k = revise(a.id, _text(a))
    return x.say(f'{k} is open again with your changes noted; its build task is dropped until the next round')


def _p_waiting(a, x):
    every = bool(a.all)
    from agent_runner import pitch, pr_rows, ready
    w = asks(all=every) + [r[:7] for r in pitch.rows(cfg()) + pr_rows.asks(cfg())
                           + ready.asks(cfg(), all=every)]  # F98, F420, F445b
    print('\n'.join('  '.join(s for s in (label, t, title, '' if label == 'CONCEPT' else what, u,
                                          f'(concept {k})' if k else '', '(shelved)' if sh else '') if s)
                    for label, t, k, what, u, title, sh in w)
          or 'nothing waits for your OK' + ('' if every else f' (`{PROG} waiting --all` adds the shelved)'))
    if ll := last_lines():
        print('\n'.join(ll))
    return 0


def _p_confirm(a, x):
    from agent_runner import ready
    if ready.task_of(a.id):  # F445b: Looks good
        return x.say(ready.good(a.id, x.c))
    t = _ask_or_parked(a.id, x.todo)[1]  # a concept's build: approving it says when it is too big (F177)
    return x.say(confirm(a.id, _text(a)) + big_note(t, x))


def _p_change(a, x):
    from agent_runner import ready
    if ready.task_of(a.id):  # F445b: Change it
        return x.say(ready.change(a.id, _text(a), x.c, x.todo, x.done))
    return x.say(change(a.id, _text(a)) + big_note(a.id, x))


def _p_concept_updated(a, x):
    """`plan concept-updated K "<what changed>" [--file PAGE]` (F197a): a chat updated concept K's page at the same
    link; the run shows it as Updated with those words. --file: the updated page, copied over the run's copy."""
    from agent_runner import concept_news
    words, page, it = [], '', iter(a.rest)
    for w in it:
        if w == '--file':
            page = next(it, '')
        else:
            words.append(w)
    what = ' '.join(words).strip()
    if not x.c or not re.fullmatch(r'[A-Za-z]+\d+\w*', a.id) or not what or (page and not Path(page).is_file()):
        print(f'{PROG} concept-updated <concept id> "<what changed>" [--file <the updated page>]', file=sys.stderr)
        return 2
    return x.say(f'concept {a.id} updated (version {concept_news.updated(x.c, a.id, what, page)}): '
                 'the run shows it as Updated until its details are opened')


def _p_concept_opened(a, x):
    """`plan concept-opened K VERSION` (F197a): concept K's details popup was opened showing VERSION."""
    from agent_runner import concept_news
    if not x.c or not re.fullmatch(r'[A-Za-z]+\d+\w*', a.id):
        print(f'{PROG} concept-opened <concept id> <version>', file=sys.stderr)
        return 2
    concept_news.opened(x.c, a.id, a.version)
    return x.say(f'concept {a.id} opened at version {a.version}')


def _p_shelve(a, x):
    from agent_runner import ready
    if ready.task_of(a.id):  # F445b: Not now
        return x.say(f'shelved {ready.shelve(a.id, True, x.c)}: off {needs_cfg()["heading"]} (`{PROG} unshelve` brings it back)')
    return x.say(f'shelved {shelve(a.id)}: still blocked, off {needs_cfg()["heading"]} (`{PROG} unshelve` brings it back)')


def _p_unshelve(a, x):
    from agent_runner import ready
    if ready.task_of(a.id):
        return x.say(f'{ready.shelve(a.id, False, x.c)} is back on {needs_cfg()["heading"]}')
    return x.say(f'{unshelve(a.id)} is back on {needs_cfg()["heading"]}')


def _p_hold(a, x):
    from agent_runner import release_moves, row_hold
    if a.id == release_moves.NEXT:
        print(release_moves.hold_next(x.todo))
        return 0
    _find(lines(x.todo), a.id)
    if why := row_hold.under_way(x.c, a.id):
        print(f'{PROG}: {a.id} cannot be held: {why}', file=sys.stderr)
        return 1
    if not row_hold.hold_task(a.id, x.todo):
        print(f'{a.id} is held already')
        return 0
    return x.say(f'held {a.id}: it keeps its place and no run starts it (`{PROG} unhold {a.id}` ends it)')


def _p_unhold(a, x):
    from agent_runner import release_moves, row_hold
    if a.id == release_moves.NEXT:
        print(release_moves.unhold_next())
        return 0
    if not row_hold.unhold_task(a.id, x.todo):
        print(f'{a.id} is not held')
        return 0
    return x.say(f'{a.id} is no longer held')


def _p_cancel(a, x):
    from agent_runner import cancel
    cancel.hold(a.id, _text(a), x.todo)  # F480: held in its place, as `hold` does
    return x.say(f'cancelled {a.id}: held, so it keeps its place and no run starts it (`{PROG} unhold {a.id}` ends it)')


def _p_kinds(a, x):
    k, own = kinds()
    return x.say('\n'.join(f'{p}  {m}' for p, m in k.items())
                 + ('' if own else '\n(the defaults: set [plan] kinds in runner.toml to name your own)'))


def _needs_wrong(text: str) -> str:
    """F168: why the `needs:` in a task's text or keyed fields is refused (a shared tool the project does not name)."""
    from agent_runner import shared_tools
    return shared_tools.unknown_names(fields('- ' + text).get('needs', []), cfg(main_checkout())) \
        if ' | needs: ' in text else ''


def _tool_waits(c, st_todo) -> dict[str, str]:
    """F168: {task: 'waits for iPhone 15, held by F389, 12 min'}; {} without shared tools, or when they cannot be read."""
    from agent_runner import shared_tools, state
    if not shared_tools.specs(c) and not any(c.notes().glob('*.wait')):  # B184: or a wait for memory
        return {}
    try:
        if state.C is None:
            state.init()
        return shared_tools.wait_words(lines(st_todo))
    except (OSError, SystemExit, ValueError):
        return {}


def _releases(c, todo) -> tuple[list[str], set[str]]:
    """F185: the index's Releases group, as `status` says them, every task named (`ui_model.release_rows`): (its lines, the ids of the
    open releases in it, which the index below then leaves out). ([], set()) for none, or when they do not read."""
    from agent_runner import state, ui_model as U
    try:
        if state.C is None:
            state.init()
        if main_checkout(c.root) != state.ROOT:  # another project's plan: no STATE or run log of it is read here
            return [], set()
        ls = lines(todo)
        rows = U.release_rows(ls, U._state(state.run_up()))
        claimed = {t: plansync.label(x) for t, x in plansync.claims(c).items()}
        claimed |= _tool_waits(c, todo) | _split_waits(c, todo)
    except (OSError, SystemExit, ValueError):
        return [], set()
    if not rows:
        return [], set()
    shown = {r['id'] for r in rows if not r['placeholder']}
    box = {tid: b for _, b, tid, _, _ in iter_tasks(ls)}
    out = [(f'[{box[r["id"]]}] ' if r['id'] in shown else '') + (f'{r["id"]} {r["title"]} · {r["all"]}' if r['id'] else r['text']) + r['note']
           + (f'  [{claimed[r["id"]]}]' if r['id'] in shown and r['id'] in claimed else '') for r in rows]
    return ['## Releases', *out, ''], shown


def _split_waits(c, todo) -> dict[str, str]:
    """`split_waits` of the plan, without the tasks running or taken by hand here, or claimed."""
    ls = lines(todo)
    if not split_waits(ls):  # nearly always: nothing more is read
        return {}
    from agent_runner import sched, state
    try:
        if state.C is None:
            state.init()
        busy = {*sched.taken(), *plansync.claims(c)}
    except (OSError, SystemExit, ValueError):
        busy = ()
    return split_waits(ls, busy=busy)


def _p_add(a, x):
    kind = a.kind
    rel = kind == RELEASE  # F38: a release (module doc)
    now = rel and '--now' in a.rest
    rest, solo = alone_flag(a.rest)  # F130: --alone tags it `(alone)`
    try:
        text, where, keyed, pri, force = add_args([r for r in rest if not (rel and r == '--now')])
    except SystemExit as e:
        print(e, file=sys.stderr)
        return 2
    if now and pri and pri != 'critical':
        print(f'{PROG}: not added: --now is --pri critical, not {pri}', file=sys.stderr)
        return 2
    pri = 'critical' if now else pri
    if not (given := bool(pri)):
        pri = None if rel else add_default()
    if why := check_kind(kind):
        print(why, file=sys.stderr)
        return 2
    if rel:
        text = text or RELEASE_BRIEF
        if pri != 'critical' and 'after' not in fields(text + keyed):  # F99
            keyed += f' | after: {ALL}'  # it waits for everything ahead of it
        if not where and not given:
            where = 'bottom'  # the end of the leading section: behind the work queued there
    text += keyed
    if why := _needs_wrong(text):  # F168
        print(f'{PROG}: not added: {why}', file=sys.stderr)
        return 2
    w = where.split(maxsplit=1) or [None]
    if not given and not where and (fam := family_end(kind)):
        w, pri = ['after', fam[0]], fam[1]  # a split stays with its parent (module doc)
    if not release(kind) and (twin := same_task(text, x.todo, x.done)):  # B817: --force and a split change nothing here
        how = (f'`{PROG} note {twin} TEXT` it there, or say what is different' if twin in open_ids(lines(x.todo)) else
               f'{twin} is in another checkout and not merged here yet; if this is different work, say what is different')
        print(f'{PROG}: not added: {twin} is this task, word for word, and not done; --force does not add it again. {how}',
              file=sys.stderr)
        return 3
    fam = kind if re.search(r'\d', kind) else None  # a split is like its parent, by design
    # B99: a release is never the same work as a build, even when its text names what it waits for
    same = [] if rel else [s for s in similar(text) if not (fam and s.split(':')[0].startswith(fam))]
    if same and not force:
        print(f'{PROG}: not added: already open, and may be the same work:\n  ' + '\n  '.join(same)
              + f'\n`{PROG} note <ID> TEXT` it there; if it is different work, add it again with --force',
              file=sys.stderr)
        return 3
    if not {'files', 'test'} & set(fields(text)) and not rel:  # a release holds the merges, whatever its files
        why = (f'the line has no `files:`: pass `--files path/a,dir/**` (the files the task will change) '
               f'or `--test name` (the test it adds); the run keeps running tasks apart by them, and a line '
               f'naming none runs beside anything')
        if cfg().raw['plan'].get('need_files'):
            print(f'{PROG}: not added: {why}', file=sys.stderr)
            return 2
        print(f'{PROG}: warning: {why}', file=sys.stderr)

    tid = add(kind, text, w[0], (w[1:] or [None])[0], pri=pri, alone_=bool(solo), split_c=x.c)
    msg = f'added {tid}' + (f' ({pri})' if pri else '') + (' (alone: nothing starts beside it)' if solo else '')
    if fam and family_end(kind):  # B196: the parent is split now
        end_split_hold(kind)
    if fam:  # a subtask waits for its parent, and for the other parts it shares files with or that name none (F199)
        print(f'{PROG}: note: {tid} never runs beside {kind}, and beside its other subtasks only when both name '
              f'`files:` that do not meet; if it is not part of {kind}, add it '
              f'with a fresh letter instead (`{PROG} add {re.match(r"[A-Za-z]+", kind).group()} …`)',
              file=sys.stderr)
    if pri == 'critical' and os.environ.get('AGENT_RUNNER') == '1':
        msg += '\ncritical goes ahead of the queued work: its text must say what it breaks or blocks'
    return x.say(msg + big_note(tid, x))


def _p_note(a, x):
    text = _text(a)
    note(a.id, text)
    told, said = tell(x.c, a.id, text)  # F512: a slot running it reads the note too
    return x.say(f'noted {a.id}' + (f'; {said}' if told is not False and said else '') + big_note(a.id, x))


def _p_edit(a, x):
    if '--wait-for' in a.rest:  # F441
        from agent_runner import plan_wait
        return plan_wait.command(a, x)
    if refused := [w for w in a.rest if w in ('@', '--last', '--force')]:
        print(f'{PROG}: edit takes no {refused[0]} (`{PROG} move ID WHERE` moves a task)', file=sys.stderr)
        return 2
    rest, solo = alone_flag(a.rest)  # F130: --alone sets the `(alone)` tag, --no-alone clears it
    try:
        text, _, keyed, pri, _ = add_args(rest)
    except SystemExit as e:
        print(str(e).replace('not added', 'not edited'), file=sys.stderr)
        return 2
    if not (text.strip() or keyed or pri or solo is not None):
        print(f'{PROG} edit <ID> "new text" [--files A,B] [--after X,Y] [--test T] [--journal D] [--model M] '
              '[--needs TOOL] [--pri LEVEL] [--alone | --no-alone]',
              file=sys.stderr)
        return 2
    if why := _needs_wrong(text + keyed):  # F168
        print(f'{PROG}: not edited: {why}', file=sys.stderr)
        return 2
    edit(a.id, text, keyed, pri or None, alone_=solo)
    if not too_big(a.id, x.c, x.todo):  # B196
        end_split_hold(a.id)
    return x.say(f'edited {a.id}' + big_note(a.id, x))


def _p_goal(a, x):
    if not a.rest:
        if not (got := goal()):
            print(f'{PROG}: no `Goal:` paragraph above the first heading in {Path(x.todo).name}; '
                  f'`{PROG} goal "TEXT"` writes one', file=sys.stderr)
            return 1
        print(got)
        return 0
    goal(_text(a))
    return x.say('goal set')


def _p_newid(a, x):
    return x.say(next_id(a.kind))


def _p_brief(a, x):
    from agent_runner.plan_brief import brief  # C52: the module imports this one
    return x.say('\n'.join(brief(a.id)))


def _p_lesson(a, x):  # F413
    from agent_runner import lessons
    return lessons.command(x.c, a.rest)


def _p_archive(a, x):
    return x.say(f'archived {archive(x.todo, x.done)}')


def _p_claims(a, x):
    got = sorted(plansync.claims(x.c).items())
    wips = git('for-each-ref', '--format=%(refname:short)', 'refs/heads/wip/main-checkout-*', cwd=x.c.root).stdout.split()
    return x.say('\n'.join([f'{t}  {plansync.label(cl)}' for t, cl in got] or ['no claims'])
                 + ''.join(f'\n{w}  main-checkout edits moved aside: pick them up' for w in wips))


def _p_unclaim(a, x):
    if not plansync.unclaim(x.c, a.id):
        print(f'{PROG}: no claim on {a.id}', file=sys.stderr)
        return 1
    return x.say(f'unclaimed {a.id}')


def _p_repo_setup(a, x):  # F460
    from agent_runner import plan_repo_setup
    return x.say('\n'.join(plan_repo_setup.setup(x.c, a.target)))


# name: (its words in order, the least count of free words after them (None: none taken), handler). A word is a
# name, or (name, add_argument options) for an optional one.
SUBCOMMANDS = {
    'tick': (('id',), None, _p_tick),
    'drop': (('id',), 1, _p_drop),
    'restore': (('id',), 0, _p_restore),
    'block': (('id',), 1, _p_block),
    'reopen': ((), None, _p_reopen),
    'unblock': (('id',), 0, _p_unblock),
    'move': (('id',), 1, _p_move),
    'approve': (('id',), 0, _p_approve),
    'revise': (('id',), 1, _p_revise),
    'concept': ((), 1, _p_concept),
    'concept-updated': (('id',), 1, _p_concept_updated),
    'concept-opened': (('id', 'version'), None, _p_concept_opened),
    'restyle': ((), 0, _p_restyle),
    'waiting': ((('all', {'nargs': '?', 'choices': ['--all']}),), None, _p_waiting),
    'confirm': (('id',), 0, _p_confirm),
    'change': (('id',), 1, _p_change),
    'shelve': (('id',), None, _p_shelve),
    'unshelve': (('id',), None, _p_unshelve),
    'hold': (('id',), None, _p_hold),
    'unhold': (('id',), None, _p_unhold),
    'cancel': (('id',), 0, _p_cancel),
    'kinds': ((), None, _p_kinds),
    'add': (('kind',), 1, _p_add),
    'note': (('id',), 1, _p_note),
    'edit': (('id',), 1, _p_edit),
    'goal': ((), 0, _p_goal),
    'newid': (('kind',), None, _p_newid),
    'brief': (('id',), None, _p_brief),
    'lesson': ((), 1, _p_lesson),
    'archive': ((), None, _p_archive),
    'claims': ((), None, _p_claims),
    'unclaim': (('id',), None, _p_unclaim),
    'repo-setup': ((('target', {'nargs': '?'}),), None, _p_repo_setup),
}


class _NoFit(Exception):
    """The words fit no subcommand: `_main` reads them as a lookup, as it always has."""


class _Parser(argparse.ArgumentParser):
    """Refuses by raising, never by printing argparse's usage and exiting: a command given the wrong count of
    words falls through to the lookup (`plan tick` alone shows DONE.md's heading), as before argparse."""

    def error(self, message):
        raise _NoFit(message)


_NOPREFIX = '\x01'  # no word is an option: an id or a text may start with '-', and add/edit read their own flags
_DASHES = '\x02--'  # argparse drops a literal '--'; the words keep it (`plan note B1 -- x` notes '-- x'). Not
# _NOPREFIX first, or argparse reads it as an option and `plan tick --` misses its id
_PARSER: list[_Parser] = []


def _parser() -> _Parser:
    if not _PARSER:
        p = _Parser(prog='plan', add_help=False, allow_abbrev=False, prefix_chars=_NOPREFIX)
        sub = p.add_subparsers(dest='cmd', parser_class=_Parser)
        for name, (words, least, run) in SUBCOMMANDS.items():
            s = sub.add_parser(name, add_help=False, allow_abbrev=False, prefix_chars=_NOPREFIX)
            for w in words:
                word, opts = w if isinstance(w, tuple) else (w, {})
                s.add_argument(word, **opts)
            if least is not None:
                s.add_argument('rest', nargs=argparse.REMAINDER)
            s.set_defaults(run=run, least=least)
        _PARSER.append(p)
    return _PARSER[0]


def _parse_command(argv: list[str]):
    """argv as a subcommand's parsed words (`.run` its handler), or None: no subcommand fits, so a lookup."""
    try:
        a = _parser().parse_args([_DASHES if w == '--' else w for w in argv])
    except _NoFit:
        return None
    if not a.cmd:
        return None
    for k, v in vars(a).items():
        if v == _DASHES:
            setattr(a, k, '--')
        elif isinstance(v, list):
            setattr(a, k, ['--' if w == _DASHES else w for w in v])
    if a.least is not None and len(a.rest) < a.least and not (a.cmd == 'add' and a.kind == RELEASE):
        return None  # `add V` alone takes the default release brief (F38)
    return a


DECIDE_LINE = re.compile(r'^[\s>*_`]*DECIDE:[\s*_`]*(.+?)[\s*_`]*$')  # F135: a line `DECIDE: <the question>`


def decide_question(text: str) -> str:
    """F135: the question work waits on in Claude's last message `text`, '' for none: its last non-empty line
    `DECIDE: <the question>` (only the last, so a status quoting another item's DECIDE line is none). B840: it is whole
    up to QUESTION_MAX, and `on_a_line`."""
    q = ' '.join(m[1].split()) if text.strip() and (m := DECIDE_LINE.match(text.strip().splitlines()[-1])) else ''
    if not q and text.strip():
        q = _wrapped_decide(text.strip().splitlines())
    return cut_question(on_a_line(q), QUESTION_MAX)


def _wrapped_decide(lines: list) -> str:
    """B871: a DECIDE line wrapped over several lines at the end of the last paragraph: the lines from the nearest
    `DECIDE:` line down, joined. Only when that line leaves its bracket of options open (so the lines below carry it
    on); a status that quotes a whole DECIDE and then says more is none."""
    for i in range(len(lines) - 2, -1, -1):
        if not lines[i].strip():
            return ''
        if m := DECIDE_LINE.match(lines[i]):
            head = m[1]
            if head.count('[') <= head.count(']'):
                return ''
            return ' '.join(' '.join([head] + lines[i + 1:]).split())
    return ''


QUESTION_MAX = 2000  # B840: a guard only; a view with little room cuts the question itself


def on_a_line(q: str) -> str:
    """B840: question `q` without the two marks that end or begin a block on a task line (`asks`, `_block_at`), so its
    item under Needs you keeps all of it. As long as before."""
    return q.replace(' — ', ' – ').replace(' BLOCKED: ', ' BLOCKED; ')


def cut_question(q: str, most: int = 240) -> str:
    """Question `q` in `most` characters. F181d: a long one is cut before the bracket of options (and any links) that
    ends it, which is kept for its buttons. 240: as questions were filed before B840, to know one by those words."""
    if len(q) <= most:
        return q
    end = m[0] if (m := re.search(r' \[[^\[\]]+ / [^\[\]]+\]\.?(?: https?://\S+)*$', q)) else ''
    head, room = q[:len(q) - len(end)], max(most - 1 - len(end), 100)  # a long bracket still leaves the question 100
    return q if len(head) <= room else head[:room].rsplit(' ', 1)[0] + '…' + end


# --- C52: the areas moved to modules of their own. Each imports this module, so this one reaches them only when a
# name is asked for (`plan.drop`, `from agent_runner.plan import short_title`), never at import (no import cycle).
MOVED = ('plan_drop', 'plan_concepts', 'plan_brief')


def __getattr__(name: str):
    import importlib
    if not name.startswith('__'):
        for mod in MOVED:
            if name in vars(m := importlib.import_module(f'agent_runner.{mod}')):
                return vars(m)[name]
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')


if __name__ == '__main__':
    sys.exit(main())
