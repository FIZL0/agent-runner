"""C52: concept tasks and the tasks that wait on a person's OK, taken out of plan.py.

Moved out of plan.py with no change: `plan` re-exports every name here, so `plan.<name>` still works.
Import `agent_runner.plan` first (it imports this module last, once its own names exist)."""
from __future__ import annotations

import re
from pathlib import Path
from agent_runner.plan_drop import drop
from agent_runner.plan import (
    FREED, ITEM, PRI_TAG, PROG, WAIT_ANY, WAIT_OK,
    _find, _item_block, _mark, _write, add, block,
    ensure, fields, iter_tasks, kinds, lines, note,
    prose, release_held, tick, unblock,
)


# --- concept tasks: an Artifact page of options, and a build that waits for a person's OK ----------------
#
# A K task builds nothing: its session publishes a page of 2-3 options and finishes with `done K7 "msg"
# --artifact URL`. `done` notes the link on K7 and files the build after it, blocked as "waiting for your OK on
# URL" (no `after:`, so `reopen` never frees it). `plan approve K7 "option B: …"` unblocks the build with the
# choice noted; `plan revise K7 WHY` sends the concept back for another round. A repo whose [plan] kinds lack K
# has no concepts: a K-lettered id there is an ordinary task.

CONCEPT = 'K'
WAITING = re.compile(r'BLOCKED: ' + re.escape(WAIT_OK) + r'(\S+)')
FROM_CONCEPT = re.compile(r'\bconcept ([A-Z]+\d+[a-z0-9]*)\b')


def concept(tid: str) -> bool:
    """Is `tid` a concept task: its letters are K, and this repo's kinds have K."""
    m = re.match(r'([A-Za-z]+)\d', tid)
    return bool(m) and m.group(1) == CONCEPT and CONCEPT in kinds()[0]


RESEARCH = re.compile(r'\s*research\b', re.I)  # F36: a kind whose meaning starts "research" changes no product


def research(tid: str, kinds_map: dict[str, str] | None = None) -> bool:
    """Is `tid` a research task (F36): its id letters name a kind whose meaning starts with "research" (R in
    KINDS; any letter a repo's own [plan] kinds mark so). Its merge carries findings only (`[run] findings`)."""
    m = re.match(r'([A-Za-z]+)\d', tid or '')
    k = kinds()[0] if kinds_map is None else kinds_map
    return bool(m) and bool(RESEARCH.match(str(k.get(m.group(1), ''))))


# F36, B221: the question a research task whose diff changes code puts to the person, and what their answer says
SHIP, QUEUE = 'Ship them', 'Queue them as their own task'
RESEARCH_BUTTONS = f'[{SHIP} (recommended) / {QUEUE}]'  # ends the question; its quote in an answer's note ends so too
MERGE_ANYWAY = re.compile(r'\bmerge[ -]anyway\b', re.I)
_SHIP_NAME = re.compile(r'(?:ship them|merge[ -]anyway)\s*(?:$|[:.!(])', re.I)  # the button, words after it or not
_SHIP_WORDS = re.compile(r'^(?:yes|yep|yeah|y|ok|okay|sure|done|go|ship|merge)\b|\b(?:go ahead|ship (?:it|them))\b', re.I)
_QUEUE_WORDS = re.compile(r'^queue\b|\bqueue (?:them|it|these|this|the (?:code|changes))\b|\bfollow[ -]?up\b|\bown task\b', re.I)
_NOT = re.compile(r"\b(?:no|not|never|dont|wont|without|only|findings|later|wait|first|until)\b|n['’]t\b|\?", re.I)  # no plain yes
_NOT_MERGE = re.compile(r"(?:\b(?:no|not|never|dont|without)|n't)\s+(?:\w+\s+){0,2}merge[ -]anyway", re.I)
_PERSON_NOTE = re.compile(r'(your answer|confirmed by you) \(|you said(?:, on (?:stuck|CONFIRM|DECIDE|BLOCKED) |: )')


def research_choice(said: str) -> str:
    """What the answer `said` to the research question chooses: 'ship', 'queue', or '' when it is neither."""
    said = ' '.join(said.split()).strip('`\'"')
    if _SHIP_NAME.match(said):
        return 'ship'
    if _QUEUE_WORDS.search(said):
        return 'queue'
    return 'ship' if _SHIP_WORDS.search(said) and not _NOT.search(re.sub(r'\bno (?:problem|need)\b', '', said, flags=re.I)) else ''


def _note_parts(item: str) -> list[str]:
    """The parts of a task's text `item`: its own line first, then each note; not what it is blocked with."""
    return item.split(' BLOCKED: ')[0].split(' — ')


def _own_words(part: str, tid: str) -> tuple[str, bool] | None:
    """(the person's own words in the note `part`, whether they answer `tid`'s research question), the question it
    quotes left out; None when the note is not one `confirm` or `change` wrote."""
    part = part.strip()
    if not (m := _PERSON_NOTE.match(part)):
        return None
    for end in (RESEARCH_BUTTONS, f'the attempt is parked on wip/{tid}'):  # the second: an ask from before B221
        if m[0] != 'you said: ' and (at := part.find(end)) >= 0:
            return re.sub(r'^\)?:\s*(?:do this instead:\s*)?', '', part[at + len(end):]), True
    cut = '): ' if m[1] else 'do this instead: '
    return part.rsplit(cut, 1)[-1] if cut in part else '', False


def research_ships(item: str, tid: str) -> bool:
    """B221: does the last decision on task `tid`'s text `item` land its research diff's code: an answer to the
    question (`research_choice`), or with no clear one a note that says `merge anyway` and offers no other answer. A
    question quoted in a note decides nothing."""
    choice, noted = '', False
    for part in _note_parts(item)[1:]:
        own = _own_words(part, tid)
        said, ours = own or (part, False)
        if ours:
            choice, noted = research_choice(said), False
        elif MERGE_ANYWAY.search(said) and not _NOT_MERGE.search(said) and not _QUEUE_WORDS.search(said):
            noted = True
    return choice == 'ship' or not choice and noted


ASKED_FOR = re.compile(r'^asked for: *["“]?(.+?)["”]? *$', re.I | re.M)  # a commit message line: the person's words


def told_file(c, tid: str) -> Path:
    """B221: what `tell` passed on to the agent of `tid`, kept because no plan line has it."""
    return c.notes('told', f'{tid}.txt')


def person_words(item: str, tid: str, long: str = '', told: str = '') -> str:
    """Everything the person said about task `tid`: its request (its line and long form `long`, unless an agent filed
    it as a follow-up), their answers and changes, and what was `told`."""
    parts = _note_parts(item)
    said = [] if not parts or PRI_TAG.search(parts[0]) else [parts[0], long]
    said += [own[0] for p in parts[1:] if (own := _own_words(p, tid))]
    return '\n'.join([*said, told])


def asked_for(messages: str, words: str) -> str:
    """B221: the first `asked for: "<words>"` line of the commit `messages` that quotes the person's `words` (three
    words or more, as they stand there); '' for none."""
    flat = lambda s: ' '.join(re.sub(r'[`"\'“”‘’]', '', s).casefold().split())  # noqa: E731
    heard = [flat(x) for x in words.split('\n')]
    for m in ASKED_FOR.finditer(messages):
        q = flat(m[1]).rstrip('.…')
        if len(q.split()) >= 3 and any(q in h for h in heard):
            return m[1]
    return ''


def build_kind() -> str:
    """The id letter a concept's build task gets: F (feature) where the kinds have it, else the first other one."""
    k = kinds()[0]
    return 'F' if 'F' in k else next((p for p in k if p != CONCEPT), 'F')


def title_of(line: str) -> str:
    """A task line's own words: after its `**ID**`, without the fields, the follow-up and `(alone)` tags, notes
    or BLOCKED."""
    t = re.sub(r'^\s*- \[.\] \*\*[^*]+\*\*\s*', '', line.split('\n')[0])
    t = re.split(r' — | BLOCKED: ', t)[0]
    return ' '.join(re.sub(r'^\s*\(alone\)', '', PRI_TAG.sub('', prose(t))).split())






def titles(*paths, width: int = 60) -> dict[str, str]:
    """{id: its `short_title`} from the plan files `paths` (TODO.md, DONE.md); a later file's line wins, so
    pass DONE.md before TODO.md. A missing file adds nothing."""
    out = {}
    for f in paths:
        for _, _, tid, rest, _ in iter_tasks(lines(f)):
            out[tid] = short_title(rest, width)
    return out


def _drop_asides(t: str) -> str:
    """`t` without its (…) asides that hold a date, a quote or a file path: "(user 2026-11-19: 'make it…')",
    "(see runner.py, plan/TODO.md)". Nested brackets count; an aside that is plain words stays."""
    out, depth, start = [], 0, 0
    for i, ch in enumerate(t):
        if ch == '(':
            if depth == 0:
                out.append(t[start:i])
                start = i
            depth += 1
        elif ch == ')' and depth:
            depth -= 1
            if depth == 0:
                aside = t[start:i + 1]
                noisy = re.search(r"^\((?:follow-up|user|asked)\b|\d{4}-\d\d-\d\d|['\"`‘’“”]|/|\w\.(?:py|md|toml|json|rs|ts|js|sh|txt|ya?ml)\b", aside)
                out.append('' if noisy else aside)
                start = i + 1
    out.append(t[start:])  # an unclosed ( keeps its tail
    return ''.join(out)


def short_title(rest: str, width: int = 60) -> str:
    """A task's line, after its id, as a few plain words for a person: its first sentence, without the ` | `
    fields, asides with dates, quotes or file lists, quote marks and bold, cut at a word to about `width`."""
    t = _drop_asides(rest.split(' | ')[0])
    t = re.sub(r'\b\d{4}-\d\d-\d\d\b', '', t)
    t = re.sub(r"(?<!\w)(['\"`])\1(?!\w)", 'empty', t)  # `''` read aloud
    t = re.sub(r"[*`\"“”‘’]|(?<!\w)'|'(?!\w)", '', t)
    t = re.sub(r'[\w./-]*\w::(?:\w+::)*(\w+)', r'\1', t)  # a Rust/pytest path a::b::c reads as its name, c
    t = re.split(r'(?<=[.!?;:])\s+(?=[A-Z(\d])|\s+—\s+|\s+--\s+', re.sub(r' ([,.;:])', r'\1', ' '.join(t.split())), maxsplit=1)[0]
    t = t.strip(' .,;:—-')
    if len(t) > width:
        cut = t[:width - 1].rsplit(' ', 1)[0].rstrip(' ,;:—-')
        if len(cut) < width // 2:  # one long word: cut inside it rather than drop it
            cut = t[:width - 1].rstrip(' ,;:—-')
        t = cut + '…'
    return t


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
    FREED[:] = release_held({x for x in w[:2] if x}, choice, todo=todo)  # F19: a restyle frees what it held
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


def concept_shown(title: str, page: str, files=None, todo=None, done=None, local=None) -> tuple[str, str]:
    """F108: a concept page a chat (a control session) wrote and showed inline lands in the plan as a K task
    already done: ticked with its page noted and its build waiting for the OK, as `concept_done` leaves a finished
    K task, so Needs you, `waiting` and the run page's Concepts list it until the person picks (`approve`,
    `revise` on its id). Where the kinds lack K only the waiting build is filed. Returns (concept id, build id);
    the two are the same id without K. F406f: `local(id)`, with no claude.ai page: gives the concept its copy, and its address."""
    todo, done = ensure(todo, done)
    text = ' '.join(title.split()) + (' | files: ' + ', '.join(files) if files else '')
    if CONCEPT not in kinds()[0]:
        bid = add(build_kind(), f'Build the option a person approves on the concept page: {text}', todo=todo,
                  done=done)
        block(bid, WAIT_OK + (local(bid) if local else page), todo=todo, after=[])
        return bid, bid
    kid = add(CONCEPT, text, todo=todo, done=done)
    page = local(kid) if local else page
    bid = concept_done(kid, page, todo=todo, done=done)
    tick(kid, todo=todo, done=done)
    return kid, bid
