"""The task list as a *tool*, not a file an agent reads whole.

A long project is hundreds of small tasks spread over months, and the agent doing them starts from
nothing every session. If the backlog is a file, every session pays for the whole file — and the one that
re-reads it on every turn pays again. So the backlog is a command instead:

    ./run plan                   index of plan/TODO.md: every heading and task id, one line each
    ./run plan next              the first open task, with its sub-items
    ./run plan <ID>              a task's full text: plan/<ID>.md, else its line in TODO.md or DONE.md
    ./run plan <name>            a heading's section (case-insensitive substring) in the plan files
    ./run plan -f FILE <name>    the same, on any other markdown file
    ./run plan brief <ID>        everything a task starts from, in one shot (see `brief`)
    ./run plan tick <ID>         done: [x], and the line moves to plan/DONE.md
    ./run plan block <ID> [--after X,Y] WHY   [~] with "BLOCKED: (after X, Y) WHY" appended
    ./run plan unblock <ID> [NOTE]   reopen: [ ], drop "BLOCKED: …", append NOTE (what unblocked it)
    ./run plan move <ID> WHERE   WHERE = top | before ID | after ID | in SECTION (its end); sub-items follow
    ./run plan add PREFIX TEXT [@ WHERE]   new "- [ ] **<next free id>** TEXT"; prints the id, and any open task
                                 that looks like the same work (nothing when none does)
    ./run plan note <ID> TEXT    append " — TEXT" to the task (user details, priority reasons)
    ./run plan newid PREFIX      the next free id, e.g. L -> L7; a task's id gives its next subtask, L3 -> L3a
    ./run plan archive           move every [x] line left in TODO.md to DONE.md (after merges, hand edits)
    ./run plan reopen            unblock every task whose BLOCKED (after X, Y) tasks are all done now

The line format is `- [ ] **ID** text → files… | t: tests | j: journal-dir`, under `###` headings, and the
checkbox is `[ ]` open, `[x]` done, `[~]` blocked.

**A block that only waits on another task says which**, as `BLOCKED: (after X, Y) why`, and `reopen` (which a
`./run run` calls after every merge) puts it back to `[ ]` the moment X and Y are done. Without that a task
blocked on "P36 is not merged yet" stays blocked long after P36 lands, because nothing reads prose. `block` fills the list in by itself
from the open task ids its WHY names, so a session that forgets `--after` still gets one.

**Design rule: checkboxes are only ever changed through this tool.** Never hand-edit a `- [ ]` in TODO.md or
DONE.md. Ticking by hand is how a task ends up done in one file and open in another, how a `(after X)`
dependency silently stops being satisfied, and how two parallel agents both pick the same task. `tick` is one
transaction: mark it, mirror the mark into `plan/<ID>.md`, move the block to DONE.md under the same heading.

Everything here is plain text and atomic: a temp file plus `os.replace`, and a file whose content did not
change is not rewritten at all (so mtimes stay meaningful and git stays quiet).
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from collections import Counter
from functools import partial
from pathlib import Path

from agent_runner.config import cfg
from agent_runner.gitops import git

PROG = './run plan'  # the name in messages; a wrapper sets its own ('./kit plan')
# The library API a wrapping project may call; names and signatures here change only in a major version.
__all__ = ['PROG', 'HELP', 'lines', 'index', 'section', 'ensure', 'archive', 'tick', 'block', 'reopen',
           'unblock', 'move', 'next_id', 'add', 'similar', 'note', 'next_task', 'files_on_line', 'brief', 'open_ids',
           'write_atomic', 'child', 'subtasks', 'main']

ITEM = re.compile(r'^(\s*)- \[(.)\] \*\*([^\s*]+)')
HEAD = re.compile(r'(#+) ')
# A path-ish token on a task line: `src/main.c`, `crates/sim/src/lib.rs`, `runner.toml`, `docs/api.md`,
# `play/*.rs`. Anything with a dot and a short extension; checked against the repo before it is believed.
FILE_TOKEN = re.compile(r'(?<![\w/.`-])([\w.*-]+(?:/[\w.*-]+)*\.[A-Za-z][\w+]{0,5})')
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

    Needed because a merge can bring a tick in from a branch without moving the line, and because a human
    sometimes ticks by hand anyway. Running it is always safe.
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
    own = os.path.join(plan_dir, f'{tid}.md')
    if os.path.exists(own):
        _write(own, [re.sub(rf'^(\s*)- \[[ ~]\] \*\*{re.escape(tid)}\b', rf'\1- [x] **{tid}', l)
                     for l in lines(own)])
    return archive(todo, done)


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


def add_default() -> str:
    """Where `plan add` files a task when no `@` says: a running agent's follow-up goes to the bottom of the
    leading section, behind the work a person queued; a person's own task goes to the top."""
    return 'bottom' if os.environ.get('AGENT_RUNNER') == '1' else 'top'


def add(prefix: str, text: str, where: str = 'top', ref: str | None = None, todo=None, done=None) -> str:
    todo, done = ensure(todo, done)
    tid = next_id(prefix, [todo, done])
    ls = list(lines(todo))
    j = _place(ls, where, ref)
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
    text = re.sub(r'\*\*[^*]+\*\*|\([^)]*\d{4}-\d\d-\d\d[^)]*\)', ' ', text)
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
    # what follows `→` is the task's file list by the line format, so a new top-level file counts there
    listed = set(FILE_TOKEN.findall(text.partition('→')[2])) if '→' in text else set()
    tracked = _tracked(root) if tracked is None else tracked
    out = []
    for n in names:
        n = n.rstrip('.,;:')
        if '*' in n:  # `play/*.rs` on a line means every file in that directory
            import fnmatch
            out += [t for t in tracked if fnmatch.fnmatch(t, f'*{n}')]
            continue
        hits = [t for t in tracked if t == n or t.endswith('/' + n)]
        # A path that does not exist yet is still the task's file: half the backlog creates its files, and
        # `brief` wants to say "missing — this task creates it" rather than quietly listing nothing. Only
        # names that look like paths or follow the `→`, though, or prose about `fpu.rs` becomes a file the
        # runner reserves.
        out += hits or ([n] if '/' in n or n in listed or (root / n).exists() else [])
    return list(dict.fromkeys(out))


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
    turns finding the task line, looking for a `plan/<ID>.md`, hunting the journal directory, opening the
    files and running `git log` on them — all of it predictable, all of it paid for again on every turn after.
    `brief` assembles it once:

      * the task's own line (and sub-items) from TODO.md or DONE.md,
      * `plan/<ID>.md` in full, if the task has a long form,
      * its journal directory: the file list, and the newest entry pasted in (capped at JOURNAL_MAX chars,
        because the newest entry is where the last session said whose move it is),
      * the files named on the line: where they actually are, how long they are, and their last 3 commits —
        so the session knows whether someone changed them yesterday before it reads a single one,
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
    own = plan_dir / f'{tid}.md'
    if own.exists():
        out += ['', f'## {plan_dir.name}/{tid}.md', *lines(own)]
        text += '\n' + '\n'.join(lines(own))

    # journals: the ones the line points at (`j: <dir>`) and any whose name carries this id
    named = re.findall(r'\bj: ([\w.-]+)', text)
    try:
        dirs = sorted(d for d in os.listdir(journal) if (journal / d).is_dir()) if journal else []
    except OSError:
        dirs = []
    own_j = [d for d in dirs if re.search(rf'-{re.escape(tid.lower())}(-|$)', d.lower())]
    for j in dict.fromkeys(named + own_j):
        d = journal / j
        if not d.is_dir():
            continue
        files = sorted(f for f in os.listdir(d) if f.endswith('.md'))
        rel = os.path.relpath(d, root).replace(os.sep, '/')
        out += ['', f'## Journal {rel}/: {" · ".join(files)}']
        if files and j in own_j:  # journals the line only points at are listed, not pasted
            body = (d / files[-1]).read_text(encoding='utf-8', errors='replace')
            cut = len(body) > JOURNAL_MAX
            out += [f'### {files[-1]}' + (f' (first {JOURNAL_MAX} chars)' if cut else ''),
                    body[:JOURNAL_MAX].rstrip()]

    where = [p for p in files_on_line(text, root) if p != f'{plan_dir.name}/{tid}.md']
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
    if cmd := c.raw['plan']['brief_extra']:  # what only the project knows: its oracle names, a spec, …
        r = subprocess.run(cmd.format(id=tid), shell=True, cwd=str(root), capture_output=True, text=True)
        if extra := (r.stdout.rstrip() or (f'({cmd} failed: {r.stderr.strip()[:200]})' if r.returncode else '')):
            out += ['', *extra.splitlines()]
    return out


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


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ('-h', '--help', 'help'):
        print(HELP)
        return 0
    c = cfg()
    plan_dir = c.plan_dir
    todo, done = ensure()

    def say(msg):
        print(msg)
        if argv[0] in ('tick', 'block', 'reopen', 'unblock', 'move', 'add', 'note'):
            _commit(c.root, [todo, done], ' '.join(argv)[:70])
        return 0

    if argv[:1] == ['tick'] and len(argv) == 2:
        n = tick(argv[1])
        return say(f'ticked {argv[1]}' + (f', moved {n} line(s) to {plan_dir.name}/DONE.md' if n else ''))
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
    if argv[:1] == ['add'] and len(argv) > 2:
        text, _, where = ' '.join(argv[2:]).partition(' @ ')
        w = where.split(maxsplit=1) or [add_default()]
        tid = add(argv[1], text, w[0], (w[1:] or [None])[0])
        same = similar(text, skip=tid)
        msg = f'added {tid}'
        if same:
            msg += ('\nalready open, and may be the same work (if so, `plan note` it there and drop this one):\n  '
                    + '\n  '.join(same))
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
    task_file = plan_dir / f'{argv[0]}.md' if argv else None
    if len(paths) > 1 and task_file and task_file.exists():
        out = lines(task_file)
    elif not argv:
        out = index(todo)
    else:
        out = next((o for p in paths if (o := section(p, argv[0]))), [])
    if not out:
        print(f'{PROG}: nothing named {argv[0]!r} — run `{PROG}` for the index', file=sys.stderr)
        return 1
    print('\n'.join(out))
    return 0


if __name__ == '__main__':
    sys.exit(main())
