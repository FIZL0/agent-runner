"""F160: control sessions learn when the item they are about is settled elsewhere.

A chat about a task or a Needs you item (its title starts with the id, or it was opened from that item: the first
message `need_chat`, `concept_chat` or an answer gives it) is told, in one typed line (`line`), when that item is dropped,
changed, confirmed, shelved, restored or otherwise settled by someone else. Two halves:

- the command that settles it leaves one event in `<notes>/settled/<ns>-<pid>.json` (`record`): `plan` (`noting`, so also
  the run page, the TUI and `sheet`, which run it), `pitch`, and the run's own undo;
- the run (`tick`, each pass) picks the sessions an event goes to once, and types it into each. One with a question
  dialog up, held messages or a session just starting waits: text typed while a turn runs queues in Claude Code, but
  there it would be lost. Who got it is written before it is typed, so a restarted run never types it twice.

A settling no command here announces (a landing, a pull of the plan, a hand edit) is found by looking: an item a live
chat is about that was under Needs you (`waits.json`) and has left it, with no event in LEFT_GRACE s (`look_left`). So
a task's ordinary landing says nothing. Sessions the runner cannot type into (opened in a terminal, or by the apps'
control server) are not told; the needs guide has every session re-read an item before it asks for it.

The control modules are imported in the functions: `plan` uses the first half from sessions with no run."""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import time
from pathlib import Path

LEAD = 'From the runner, not the person: '  # RUNNER_TURN, person_message and held messages know it: no person's message
BY_ENV = 'AGENT_RUNNER_BY'  # who runs a command no session runs, in words (the run app)
KEEP = 86400  # s an event no run took, or that could not be typed, is kept
LEFT_EVERY = 30  # s between two looks for items that left Needs you
LEFT_GRACE = 120  # s after an item left Needs you before it is told with no event
LEFT_AT = [0.0]
TRIES = 3
ID = r'(?:[A-Z]+\d+[a-z0-9]*|pitch\d+)'
TITLE_ID = re.compile(rf'({ID})(?=[\s:,.;·]|$)')
# the first message of a chat opened from an item: ui_model.need_chat_text, concept_chat_text, answer
OPENED = re.compile(rf"This chat is about (?:concept )?({ID}) '|({ID})(?: \([^\n]*\))?: ")
ASKS_PERSON = ('AskUserQuestion', 'ExitPlanMode')  # typed text would answer these dialogs
# the plan commands that settle or change an item, and what is said of them
VERBS = {'drop': 'was dropped', 'change': 'was changed', 'edit': 'was changed', 'confirm': 'was answered',
         'approve': 'was approved', 'revise': 'was sent back for changes', 'shelve': 'was shelved',
         'unshelve': 'was put back under Needs you', 'restore': 'was restored', 'unblock': 'was reopened',
         'tick': 'was ticked'}
NO_REASON = ('tick', 'restore', 'edit')  # what follows the id there is no reason
_SEEN: dict[str, tuple] = {}


def folder(c) -> Path:
    return c.notes('settled', 'x').parent


def pid_sid(c, n: int) -> str:
    try:
        return c.notes(f'control{n}.pid').read_text(encoding='utf-8').strip().partition(' ')[2].strip()
    except OSError:
        return ''


def author(c) -> dict:
    """Who runs this command: {'by': in words ('' unknown), 'n', 'sid'}; n and sid of a control session."""
    if slot := os.environ.get('AGENT_RUNNER_SLOT'):  # first: a run a control session started has its mark too
        return {'by': f"s{slot.removeprefix('s')}'s agent", 'n': 0, 'sid': ''}
    n = os.environ.get('AGENT_RUNNER_CONTROL', '')  # control.CONTROL_N_ENV
    if n.isdigit():
        return {'by': f'c{n}', 'n': int(n), 'sid': pid_sid(c, int(n))}
    return {'by': os.environ.get(BY_ENV, ''), 'n': 0, 'sid': ''}


def save(f: Path, d) -> None:
    tmp = f.with_suffix('.tmp')
    tmp.write_text(json.dumps(d), encoding='utf-8')
    tmp.replace(f)


def record(c, ids, what: str, reason: str = '', who: dict | None = None, at: float = 0.0) -> None:
    """Leave one event for the run: item `ids[0]` (the others name the same item) `what` ('was dropped'). Nothing
    without a control session to tell. Never stops the command that settled it."""
    try:
        if not any(c.notes().glob('control*.pid')):
            return
        reason = ' '.join(str(reason or '').split()).rstrip('.')
        if len(reason) > 200:
            reason = reason[:199].rsplit(' ', 1)[0] + '…'
        save(folder(c) / f'{time.time_ns()}-{os.getpid()}.json',
             {'ids': list(dict.fromkeys(x for x in ids if x)), 'what': what, 'reason': reason,
              'at': at or time.time(), **(author(c) if who is None else who)})
    except (OSError, AttributeError):
        pass


def noting(c, a, todo, run):
    """Run plan subcommand `a` (`run`: its exit code) and record what it settled."""
    if a.cmd not in VERBS or a.cmd == 'edit' and a.rest[:1] == ['--pri'] and len(a.rest) == 2:  # only its place
        return run()
    from agent_runner import plan as P
    ids, needed = [a.id], False
    try:
        ask = P._ask(a.id, todo)
        ids, needed = [a.id, ask[1], ask[2]], True
    except (SystemExit, OSError):
        pass
    rc = run()
    if not rc and (needed or a.cmd != 'tick'):  # an ordinary tick says nothing
        record(c, ids, VERBS[a.cmd], '' if a.cmd in NO_REASON else ' '.join(getattr(a, 'rest', None) or []))
    return rc


def done_by(c, tid: str) -> None:
    """`done` in a control session's own take: its landing is not told to that session."""
    if (who := author(c))['sid']:  # a session this project knows
        try:
            save(folder(c) / f'{tid}.by', who)
        except OSError:
            pass


def line(tid: str, ev: dict) -> str:
    at = dt.datetime.fromtimestamp(ev['at']).strftime('%H:%M')
    return (f'{LEAD}{tid} {ev["what"]} at {at}' + (f' by {ev["by"]}' if ev.get('by') else '')
            + (f': {ev["reason"]}' if ev.get('reason') else '')
            + '. Re-read it before asking the person anything for it.')


# --- the run's half ------------------------------------------------------------------------------------------

def facts(sid: str) -> dict:
    """What session `sid`'s transcript says: 'title' (its custom title), 'opened' (the item its first message names
    it was opened from, ''), 'begun' (when it began), 'dialog' (a question to the person is up), 'closed' (online).
    {} without a transcript."""
    from agent_runner import control as K
    if not (path := K.transcript(sid)):
        return {}
    try:
        s = os.stat(path)
    except OSError:
        return {}
    key = (path, s.st_size, s.st_mtime_ns)
    if (got := _SEEN.get(sid)) and got[0] == key:
        return got[1]
    rows = [d for d in K.entries(sid, skip_bad=True) if isinstance(d, dict) and not d.get('isSidechain')]
    out = {'title': '', 'opened': '', 'begun': 0.0, 'dialog': False, 'closed': K.closed_online(rows)}
    first, asking = None, set()
    for d in rows:
        out['begun'] = out['begun'] or K._stamp(d) or 0.0
        if d.get('type') == 'custom-title':
            out['title'] = str(d.get('customTitle') or '').strip()
        elif d.get('type') == 'user' and first is None and K.person_turn(d):
            first = K.message_text(d).lstrip()
        c = (d.get('message') or {}).get('content') if d.get('type') in ('user', 'assistant') else None
        for x in c if isinstance(c, list) else ():
            if isinstance(x, dict) and x.get('type') == 'tool_use' and x.get('name') in ASKS_PERSON:
                asking.add(x.get('id'))
            elif isinstance(x, dict) and x.get('type') == 'tool_result':
                asking.discard(x.get('tool_use_id'))
    if m := OPENED.match(first or ''):
        out['opened'] = m[1] or m[2]
    out['dialog'] = bool(asking)
    _SEEN[sid] = (key, out)
    return out


def title_id(title: str, project: str) -> str:
    """The item id a control session's title starts with, after the project and number the runner puts first."""
    t = re.sub(r'^\d+ · ', '', title.removeprefix(f'{project} · '))
    return m[1] if (m := TITLE_ID.match(t)) else ''


def about(n: int, sid: str, f: dict) -> set[str]:
    """The items control session `n` is about: what its title starts with, and what it was opened from."""
    from agent_runner import control as K, state
    from agent_runner.control_names import person_name
    title = person_name(n, f.get('title', '')) or (f.get('title', '') if K.control_renamed({'title': f.get('title', '')}, n)
                                                   else K.control_given(n))
    return {x for x in (title_id(title, state.ROOT.name), f.get('opened', '')) if x}


def live() -> list[tuple[int, str, dict, set[str]]]:
    """(n, sid, facts, the items it is about) of each live control session not closed online that is about one."""
    from agent_runner import control as K, control_held as H
    out = []
    for n in H.numbers():
        sid = H.pid_sid(n)[1]
        if sid and K.control_live(n) and not (f := facts(sid)).get('closed') and (ids := about(n, sid, f)):
            out.append((n, sid, f, ids))
    return out


def read_json(f: Path, default):
    try:
        d = json.loads(f.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default
    return d if isinstance(d, type(default)) else default


def tick(force: bool = False, now: float | None = None) -> None:
    """From the run loop: type what was settled into the sessions about it."""
    from agent_runner import state
    now = time.time() if now is None else now
    d = folder(state.C)
    try:
        for f in sorted(d.glob('*-*.json')):
            try:
                step(f, now)
            except Exception as e:  # noqa: BLE001 - one event never stops the others
                state.log(f'{f.name}: a settled item could not be told: {e}')
                f.unlink(missing_ok=True)
        if force or now - LEFT_AT[0] >= LEFT_EVERY:
            LEFT_AT[0] = now
            look_left(d, now)
    except Exception as e:  # noqa: BLE001 - never stops the run loop
        state.log(f'the settled items could not be looked at: {e}')


def step(f: Path, now: float) -> None:
    """One event: choose its sessions the first time, then type it into each that can take it."""
    from agent_runner import control as K, control_held as H, state
    ev = read_json(f, {})
    if not ev.get('ids') or now - ev.get('at', 0) > KEEP:
        return f.unlink(missing_ok=True)
    if 'to' not in ev:
        ev['to'] = {}
        for n, sid, fx, ids in live():
            hit = next((i for i in ev['ids'] if i in ids), '')
            mine = sid == ev['sid'] if ev.get('sid') else n == ev.get('n')
            if hit and not mine and not fx.get('begun', 0) > ev['at']:  # one begun since reads it as it is now
                ev['to'][sid] = {'id': hit, 'tries': 0}
        save(f, ev)
        forget_wait(f.parent, ev['ids'])
    for sid, to in list(ev['to'].items()):
        n = H.live_number(sid)
        fx = facts(sid)
        if not n or fx.get('closed'):  # ended since: nothing is typed, nor when it comes back
            del ev['to'][sid]
            continue
        if not state.C.notes(f'control{n}.in').exists():
            state.log(f'control {n}: not told that {to["id"]} {ev["what"]}: it takes no typed text')
            del ev['to'][sid]
            continue
        began = state.C.notes(f'control{n}.pid').stat().st_mtime
        if fx.get('dialog') or H.holds(sid) or now - began < H.HELD_SETTLE[0 if K.remote_on() else 1]:
            continue
        del ev['to'][sid]
        save(f, ev)  # before typing: a run killed here never types it twice
        if K.control_type(n, line(to['id'], ev)):
            state.log(f'control {n}: told that {to["id"]} {ev["what"]}')
        elif to['tries'] + 1 < TRIES:
            ev['to'][sid] = {**to, 'tries': to['tries'] + 1}
        else:
            state.log(f'control {n}: not told that {to["id"]} {ev["what"]}: its session takes no typed text')
    if ev['to']:
        save(f, ev)
    else:
        f.unlink(missing_ok=True)


# --- what left Needs you with no event ---------------------------------------------------------------------------

def forget_wait(d: Path, ids) -> None:
    waits = read_json(d / 'waits.json', {})
    if any(i in w for w in waits.values() for i in ids):
        save(d / 'waits.json', {s: k for s, w in waits.items() if (k := {i: v for i, v in w.items() if i not in ids})})


def look_left(d: Path, now: float) -> None:
    """Note the Needs you items live chats are about, and record an event for one that has left Needs you for
    LEFT_GRACE s that no command announced."""
    from agent_runner import pitch, plan as P, state
    was, chats = read_json(d / 'waits.json', {}), live()
    if not chats and not was:
        return
    asks = [*P.asks(state.C.todo), *pitch.rows(state.C)]
    needs = {i for a in asks for i in (a[1], a[2]) if i}
    waits: dict[str, dict] = {}
    left: dict[str, float] = {}
    for _, sid, _, ids in chats:
        for i in ids:
            if i in needs:
                waits.setdefault(sid, {})[i] = 0
            elif i in was.get(sid, {}):
                at = was[sid][i] or now
                if now - at >= LEFT_GRACE:
                    left[i] = min(at, left.get(i, at))
                else:
                    waits.setdefault(sid, {})[i] = at
    for i, at in left.items():
        what, reason = outcome(i)
        by = d / f'{i}.by'
        who = read_json(by, {}) if what == 'landed' else {}
        by.unlink(missing_ok=True)
        record(state.C, [i], what, reason, who=who or {'by': '', 'n': 0, 'sid': ''}, at=at)
    if waits != was:
        save(d / 'waits.json', waits)


def outcome(tid: str) -> tuple[str, str]:
    """(what became of item `tid` that left Needs you, the reason), from the plan's files."""
    from agent_runner import plan as P, state
    for path in (state.C.todo, state.C.done):
        ls = P.lines(path)
        for i, l in enumerate(ls):
            if not (m := P.ITEM.match(l)) or m.group(1) or m.group(3).rstrip('.') != tid:
                continue
            block = ' '.join(P._item_block(ls, i))
            if m.group(2) == 'x':
                return ('was dropped', block.rsplit(P.DROPPED, 1)[1]) if P.DROPPED in block else ('landed', '')
            if m.group(2) == ' ':
                return 'was reopened', ''
            return ('was shelved', '') if any(tid in (a[1], a[2]) for a in P.asks(state.C.todo, all=True)) else \
                ('no longer waits on the person', '')
    return 'no longer waits on the person', ''
