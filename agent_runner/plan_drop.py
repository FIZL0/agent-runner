"""C52: `plan drop` and `plan restore`, the two ways a task leaves the plan without landing.

Moved out of plan.py: `plan` re-exports every name here, so `plan.<name>` still works.
Import `agent_runner.plan` first (it imports this module last, once its own names exist)."""
from __future__ import annotations

import json
import os
import re
import shutil
import time
from pathlib import Path
from agent_runner.plan import (
    ITEM, PROG, SPLIT, WAITS, _block_at, _find, _item_block, _mark,
    _place, _unblocked, _write, ensure, iter_tasks, lines, long_form,
    note, open_ids, resolve_after, tick, until_of,
)


def _split_ids(todo) -> set[str]:
    """Ids of the tasks in `todo` not done that say `(split into …)`."""
    ls = lines(todo)
    return {tid for _, box, tid, _, i in iter_tasks(ls) if box != 'x' and SPLIT.search(ls[i])}


def drop(tid: str, why: str, todo=None, done=None) -> list[str]:
    """Close a task nobody will do (a duplicate, work another task overtook): noted, then archived as ticked,
    so its id stays used and what waits on it reopens. Returns the split parents it made one whole task again:
    this was their last open part and none landed (B197). What `restore` needs to undo it is kept (`_keep`)."""
    todo, done = ensure(todo, done)
    was = _split_ids(todo)
    ls = lines(todo)
    rec = {'blocked': ITEM.match(ls[_find(ls, tid)]).group(2) == '~', 'waits': _waiters(ls, tid)}
    note(tid, f'dropped: {why}', todo=todo)
    kept = _keep(tid, rec, todo)
    try:
        tick(tid, todo, done)
    except SystemExit:
        for c in kept:
            _put_back(c, tid)
        raise
    from agent_runner.asks import clear_env  # here: asks imports this module
    clear_env(tid, todo)  # F175
    return sorted(was & open_ids(lines(todo)) - _split_ids(todo))


DROPPED = ' — dropped: '
KEEP = 30 * 86400  # B808: how long a dropped task's ask and the waits on it are kept, in seconds,
KEEP_ENV = 86400   # and its secrets
KEPT = 'kept.json'
ASK_FILES = ('asks/{}.json', 'asks/{}.taken', 'asks/{}.said', 'asks/{}', 'asks/{}.env', 'sheets/{}.json',
             'sheets/{}.taken', 'sheets/{}.url', 'sheets/{}.html', 'concepts/{}_sheet.html')  # under the notes dir


def _waiters(ls: list[str], tid: str) -> dict[str, dict]:
    """B808: the tasks blocked `(after …)` on `tid`, {id: {'line': its last line, 'said': what `reopen` will say}}."""
    out = {}
    for _, box, t, _, i in iter_tasks(ls):
        tail = ls[i + len(_item_block(ls, i)) - 1]
        w = WAITS.findall(tail) if box == '~' and not until_of(ls, i) else []
        ids = [x.strip() for x in w[-1].split(',') if x.strip()] if w else []
        if t != tid and tid in resolve_after(ls, i, ids):
            out[t] = {'line': tail,
                      'said': ', '.join('everything before it' if x == 'all' else x for x in ids) + ' landed'}
    return out


def _configs(todo) -> list:
    """The configs whose plan `todo` is, one a notes dir."""
    from agent_runner.asks import _plans  # here: asks imports this module's plan
    return list({c.notes('x').parent: c for c in _plans(todo)}.values())


def _keep(tid: str, rec: dict, todo) -> list:
    """B808: move dropped `tid`'s ask file, its pictures, pick sheet and secrets to <notes>/dropped/ID, with `rec`
    (was it blocked, and the tasks that waited on it), for `restore`. Returns the configs it did so for."""
    from agent_runner.asks import _ignored
    if not re.fullmatch(r'\w[\w.-]*', tid):
        return []
    kept = _configs(todo)
    for c in kept:
        sweep_kept(c)
        root, at = c.notes('x').parent, c.notes('dropped', tid, 'x').parent
        shutil.rmtree(at, ignore_errors=True)
        for f in (x.format(tid) for x in ASK_FILES):
            try:
                if (root / f).exists():
                    (at / f).parent.mkdir(parents=True, exist_ok=True)
                    if not f.endswith('.env') or _ignored(at / f):
                        os.replace(root / f, at / f)
            except OSError:
                continue
        at.mkdir(parents=True, exist_ok=True)
        (at / KEPT).write_text(json.dumps(rec), encoding='utf-8')
        os.utime(at)  # when it was dropped
    return kept


def _kept(c, tid: str) -> dict:
    """What `_keep` wrote down of `tid`; {} for nothing."""
    try:
        return json.loads((c.notes('dropped', tid) / KEPT).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def _put_back(c, tid: str) -> None:
    """Move what `_keep` kept for `tid` back."""
    root, at = c.notes('x').parent, c.notes('dropped', tid)
    for f in (x.format(tid) for x in ASK_FILES):
        try:
            if (at / f).exists():
                (root / f).parent.mkdir(parents=True, exist_ok=True)
                os.replace(at / f, root / f)
        except OSError:
            continue
    shutil.rmtree(at, ignore_errors=True)


def sweep_kept(c) -> None:
    """B808: take away what was kept for tasks dropped more than KEEP ago, and their secrets after KEEP_ENV."""
    for d in c.notes('dropped').glob('*/'):
        try:
            age = time.time() - d.stat().st_mtime
            if age > KEEP:
                shutil.rmtree(d, ignore_errors=True)
            elif age > KEEP_ENV:
                (d / 'asks' / f'{d.name}.env').unlink(missing_ok=True)
        except OSError:
            continue


def _wait_again(c, waits: dict, todo) -> None:
    """Block each task that `reopen` freed by the drop as it was. One that something changed or works on since stays."""
    from agent_runner import row_hold
    for t, was in waits.items():
        ls = list(lines(todo))
        try:
            i = _find(ls, t)
        except SystemExit:
            continue
        end = i + len(_item_block(ls, i)) - 1
        box, cur, line, at = ITEM.match(ls[i]).group(2), ls[end], was['line'], _block_at(was['line'])
        body = _unblocked(line) if end == i else line.split(' BLOCKED: ')[0]  # as `unblock` cuts it
        freed = f' — reopened: {was["said"]}'
        back = re.compile(rf' — back for you: {re.escape(was["said"])}(?: \(asked [^)]*\))?$')  # `plan._reask`
        if box == ' ' and cur.endswith(freed):
            cur = cur[:-len(freed)]
            new = cur + line[len(body):]
        elif box == '~' and (n := _block_at(cur)) >= 0 and cur[:n].rstrip()[6:] == line[:at].rstrip()[6:] \
                and back.search(cur):
            new = cur[:n] + line[at:]
        else:
            continue
        if row_hold.under_way(c, t):
            continue
        ls[end] = new
        _mark(ls, i, '~')
        _write(todo, ls)


def restore(tid: str, where: str = 'top', ref: str | None = None, todo=None, done=None, plan_dir=None) -> bool:
    """Undo a mistaken tick or drop (F47): the task's block goes from DONE.md back to TODO.md as open [ ], same id,
    its text, fields and sub-items kept, less the ` — dropped: WHY` its drop appended; at the top of the leading
    section unless `where` (as `move`) says. A tick made but not archived yet is reopened where it stands.
    B808: a dropped task that was blocked is blocked again, its ask with it, and what its drop freed waits on it again.
    Returns whether it is blocked."""
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
    dropped = blocked = False
    for k in range(here + len(blk) - 1, here - 1, -1):  # the drop's note is the last one on the block
        if DROPPED in ls[k]:
            ls[k] = ls[k][:ls[k].rindex(DROPPED)]
            dropped = True
            blocked = k == here + len(blk) - 1 and (_unblocked(ls[k]) != ls[k] if k == here else ' BLOCKED: ' in ls[k])
            break
    recs = [(c, _kept(c, tid)) for c in _configs(todo)] if dropped else []
    blocked = next((r['blocked'] for _, r in recs if 'blocked' in r), blocked)  # else (dropped elsewhere) as its line reads
    _mark(ls, here, '~' if blocked else ' ')
    _write(todo, ls)
    _write(done, dl)
    own = long_form(plan_dir, tid)
    if os.path.exists(own):
        _write(own, [re.sub(rf'^(\s*)- \[x\] \*\*{re.escape(tid)}\b', rf'\1- [ ] **{tid}', l) for l in lines(own)])
    for c, rec in recs:
        _put_back(c, tid)
        _wait_again(c, rec.get('waits') or {}, todo)
    return blocked
