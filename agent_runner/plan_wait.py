"""F441: set what a queued task waits for (`plan edit ID --wait-for X,Y|none`, the Plan page's Wait for…).

The ids replace the task's `after:`, exactly. A task blocked on `(after …)` has that list replaced instead, as that is
the one `reopen`, `status` and the page read; its `after:` goes, so it waits for nothing twice."""
from __future__ import annotations

import re

from agent_runner import plan as P

FLAG = '--wait-for'
NONE = 'none'  # the flag's value that clears the waits


def parse(value: str) -> list[str]:
    """The flag's value as ids, each once; [] for `none`."""
    ids = list(dict.fromkeys(t for t in re.split(r'[,\s]+', value) if t))
    return [] if ids == [NONE] else ids


def _wait_at(ls: list[str], i: int) -> tuple[int, re.Match] | None:
    """Where the last block of the blocked task at ls[i] starts in its last line, and its `(after …)`; None when it
    is blocked on something else."""
    tail = ls[i + len(P._item_block(ls, i)) - 1]
    at = P._block_at(tail)
    m = P.WAITS.match(tail[at + 1:]) if at >= 0 else None
    return (at, m) if m else None


def blocked_on(ls: list[str], i: int) -> list[str]:
    """The ids of the `(after …)` the task at ls[i] is blocked on; [] when its last block names none."""
    got = _wait_at(ls, i)
    return [t.strip() for t in got[1].group(1).split(',') if t.strip()] if got else []


def _family(ls: list[str], one: int, other: int) -> bool:
    """Is the task at ls[other] a subtask of the one at ls[one]?"""
    tid = P.ITEM.match(ls[other]).group(3).rstrip('.')
    return bool(P.subtasks(P.ITEM.match(ls[one]).group(3).rstrip('.'), ls[one], [tid]))


def _edges(ls: list[str], i: int, where: dict[str, int]) -> list[str]:
    """What the task at ls[i] cannot be done before: the ids it names, its open subtasks, and what its `all` or `all
    above` stands for, with the tasks that marker skips for now (it waits for them once the person acts on them)."""
    tid = P.ITEM.match(ls[i]).group(3).rstrip('.')
    out = P._named_after(ls, i) + sorted(P.subtasks(tid, ls[i], where), key=where.get)
    for on, got in ((P._waits_all(ls, i), P._before_all), (P.LAST in P.fields(ls[i]).get('after', []), P._above)):
        if on:
            waits, skipped = got(ls, i)
            out += [*waits, *skipped]
    return [t for t in dict.fromkeys(out) if t in where and t != tid]


def circle(ls: list[str], tid: str, ids: list[str]) -> list[str]:
    """The chain from one of `ids` back to `tid` through what each waits for in `ls`, ids in order; [] for none."""
    where = P._open_at(ls)
    came = {t: '' for t in ids}
    todo = list(ids)
    while todo:
        t = todo.pop(0)
        for n in _edges(ls, where[t], where) if t in where else ():
            if n == tid:
                chain = [t]
                while came[chain[0]]:
                    chain.insert(0, came[chain[0]])
                return [*chain, tid]
            if n not in came:
                came[n] = t
                todo.append(n)
    return []


def _with_after(line: str, ids: list[str]) -> str:
    """The task line with exactly `ids` as its `after:` ([]: none), every other field where it was. `ahead:` (F435)
    goes with the `after: all` it belongs to."""
    body = P._unblocked(line)
    tail = line[len(body):]
    field = f' | after: {", ".join(ids)}' if ids else ''
    put = False

    def swap(m):
        nonlocal put
        if m.group(1) == 'ahead':
            return ''
        if m.group(1) != 'after':
            return m.group(0)
        new, put = '' if put else field, True
        return new
    body = P.FIELD.sub(swap, body)
    if not put:
        ends = [m.end() for m in P.FIELD.finditer(body)]  # before the notes that follow the fields
        at = ends[-1] if ends else len(body)
        body = body[:at] + field + body[at:]
    return body + tail


def _kept_notes(cut: str) -> str:
    """The notes in the block text `cut` that reopening takes off a line."""
    return ' — '.join(n for part in cut.split(' BLOCKED: ') if (n := part.partition(' — ')[2].strip()))


def _changed(ls: list[str], i: int, ids: list[str]) -> tuple[list[str], str | None]:
    """(`ls` with the waits of the task at ls[i] set to `ids`, None or the notes it is still to be reopened with)."""
    ls = list(ls)
    if P.ITEM.match(ls[i]).group(2) != '~':
        ls[i] = _with_after(ls[i], ids)
        return ls, None
    end = i + len(P._item_block(ls, i)) - 1
    at, m = _wait_at(ls, i)
    reopen = None
    head, rest = ls[end][:at], ls[end][at + 1 + m.end():]
    cut = len(P._unblocked(ls[i]) if end == i else ls[end].split(' BLOCKED: ')[0])
    if ids:
        # an earlier block's `(after X)` a merge left is read no more
        head = head[:cut] + P.WAITS.sub('BLOCKED:', head[cut:])
        ls[end] = f'{head} BLOCKED: (after {", ".join(ids)}){rest}'
    elif ask := P.REASK.match(ls[end][at + 1:]):  # B60: a person's check that waited comes back to them
        ls[end] = head[:cut] + P.WAITS.sub('BLOCKED:', head[cut:]) + ' BLOCKED: ' + P.stamp_ask(ask.group(1))
    else:
        reopen = _kept_notes(ls[end][cut:])
    ls[i] = _with_after(ls[i], [])
    return ls, reopen


def why_not(ls: list[str], done: list[str], tid: str, ids: list[str]) -> str:
    """Why the waits of `tid` cannot be `ids`, in plain words; '' when they can. What works on it is not looked at."""
    where = P._open_at(ls)
    over = {m.group(3).rstrip('.') for l in [*done, *ls]
            if (m := P.ITEM.match(l)) and not m.group(1) and m.group(2) == 'x'}

    def gone(t: str) -> str:
        return f'{t} is done' if t in over else f'there is no task {t}'
    if tid not in where:
        return gone(tid)
    i = where[tid]  # B870: a release's waits are set the same way, its `after: all` replaced by the list
    if P.ITEM.match(ls[i]).group(2) == '~' and not _wait_at(ls, i):
        return f'{tid} is ' + ('shelved' if P._shelved(ls, i) else 'waiting for you' if P._on_person(ls, i)
                               else f'waiting for {P.until_label(c)}' if (c := P.until_of(ls, i))
                               else 'blocked on something other than a task')
    for t in ids:
        if t == tid:
            return f'{tid} cannot wait for itself'
        if t not in where:
            return gone(t)
        if _family(ls, i, where[t]):
            return f'{t} is a subtask of {tid}'
        if _family(ls, where[t], i):
            return f'{tid} is a subtask of {t}'
    if chain := circle(_changed(ls, i, ids)[0], tid, ids):
        return f'that makes a circle: {tid} would wait for ' + ', which waits for '.join(chain)
    return ''


def set_waits(c, tid: str, ids: list[str], todo=None, done=None) -> None:
    """`tid` waits for exactly `ids` ([]: for nothing). SystemExit says why not, with nothing changed."""
    todo, done = P.ensure(todo, done)
    ls = list(P.lines(todo))
    why = why_not(ls, P.lines(done), tid, ids)
    if not why:
        from agent_runner import row_hold
        why = row_hold.under_way(c, tid)
        why = why and f'{tid} has started: {why}'
    if why:
        raise SystemExit(f'{P.PROG}: waits not changed: {why}')
    ls, reopen = _changed(ls, P._find(ls, tid), ids)
    P._write(todo, ls)
    if reopen is not None:
        P.unblock(tid, reopen, todo=todo)


def command(a, x) -> int:
    """`plan edit ID --wait-for X,Y|none`, alone: `a` its words, `x` as every plan subcommand takes it."""
    import sys
    if len(a.rest) != 2 or a.rest[0] != FLAG or not a.rest[1].strip(', '):
        print(f'{P.PROG} edit <ID> {FLAG} X,Y|{NONE} (on its own)', file=sys.stderr)
        return 2
    ids = parse(a.rest[1])
    set_waits(x.c, a.id, ids, x.todo, x.done)
    return x.say(f'{a.id} waits for {", ".join(ids)}' if ids else f'{a.id} waits for nothing')
