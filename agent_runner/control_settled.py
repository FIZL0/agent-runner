"""F160: control sessions learn when the item they are about is settled elsewhere.

A chat about a task or a Needs you item (its title starts with the id, or it was opened from that item: the first
message `need_chat`, `concept_chat` or an answer gives it; or it filed that concept or DECIDE itself: `filed`) is
told, in one typed line (`line`), when that item is dropped, changed, confirmed, shelved, restored or otherwise settled by someone else. Two halves:

- the command that settles it leaves one event in `<notes>/settled/<ns>-<pid>.json` (`record`): `plan` (`noting`, so also
  the run page, the TUI and `sheet`, which run it), `pitch`, and the run's own undo;
- the run (`tick`, each pass) picks the sessions an event goes to once, and types it into each. One with a question
  dialog up, held messages or a session just starting waits: text typed while a turn runs queues in Claude Code, but
  there it would be lost. Who got it is written before it is typed, so a restarted run never types it twice.

A settling no command here announces (a landing, a pull of the plan, a hand edit) is found by looking: an item a live
chat is about that was under Needs you (`waits.json`) and has left it, with no event in LEFT_GRACE s (`look_left`). So
a task's ordinary landing says nothing. Sessions the runner cannot type into (opened in a terminal, or by the apps'
control server) are not told; the needs guide has every session re-read an item before it asks for it.

Repeats (B812): an event like the last one of its item (same `what`, author and reason) is not told again to a session
told in the last AGAIN s, and takes the place of one still waiting for it: one line. Another event of the item between
them, also the session's own, ends that. After a told edit, one that says something else is still told. An edit of only
`--files` or `--pri` records nothing. F209b: a drop, confirm or approve the person sent from the run page, the TUI or a
pick link (`by_person`) closes the chats about it in place of the line, unless `keep_why` keeps one open. Known, not handled: a slot's edit in its unmerged worktree is told at once, so
the plan on main may not show it yet when the session re-reads the item.

The control modules are imported in the functions: `plan` uses the first half from sessions with no run."""

from __future__ import annotations

import datetime as dt
import hashlib
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
AGAIN = 120  # s in which a repeat of an event a session was told is not told again
LEFT_AT = [0.0]
TRIES = 3
ID = r'(?:[A-Z]+\d+[a-z0-9]*|pitch\d+)'
TITLE_ID = re.compile(rf'({ID})(?=[\s:,.;·]|$)')
# the first message of a chat opened from an item: ui_model.need_chat_text, concept_chat_text, answer; or 020-chats.logic.js
# compose(): 'About F1 (title): words', 'About R81 (title), which needs me: words', and, from a page kept open from before
# B219a, 'About concept K1 (title): words'
OPENED = re.compile(rf"This chat is about (?:concept )?({ID}) '"
                    rf"|(?:About (?:concept )?)?({ID})(?: \([^\n]*\))?(?:, which needs me)?: ")
ASKS_PERSON = ('AskUserQuestion', 'ExitPlanMode')  # typed text would answer these dialogs
# the plan commands that settle or change an item, and what is said of them
VERBS = {'drop': 'was dropped', 'change': 'was changed', 'edit': 'was changed', 'confirm': 'was answered',
         'approve': 'was approved', 'revise': 'was sent back for changes', 'shelve': 'was shelved',
         'unshelve': 'was put back under Needs you', 'restore': 'was restored', 'unblock': 'was reopened',
         'tick': 'was ticked'}
NO_REASON = ('tick', 'restore', 'edit')  # what follows the id there is no reason
CLOSES = ('drop', 'confirm', 'approve')  # F209b: settled for good: the person's closes the chats about it
PERSON_BY = 'the person in the run app'  # BY_ENV of the run page, the TUI and a pick link (ui_model._run)
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


def by_person(c) -> bool:
    """F209b: this command is the person's, sent from the run page, the TUI or a pick link: no chat's, agent's or run's."""
    who = author(c)
    return not who['n'] and who['by'] == PERSON_BY


def save(f: Path, d) -> None:
    tmp = f.with_suffix('.tmp')
    tmp.write_text(json.dumps(d), encoding='utf-8')
    tmp.replace(f)


def record(c, ids, what: str, reason: str = '', who: dict | None = None, at: float = 0.0,
           said: str = '', closes: bool = False) -> None:
    """Leave one event for the run: item `ids[0]` (the others name the same item) `what` ('was dropped'). Nothing
    without a control session to tell. `said`: the command's words, whole, to know a repeat by. `closes` (F209b):
    the person settled it for good outside a chat, so the chats about it close in place of being told.
    Never stops the command that settled it."""
    try:
        if not any(c.notes().glob('control*.pid')):
            return
        reason = ' '.join(str(reason or '').split()).rstrip('.')
        if len(reason) > 200:
            reason = reason[:199].rsplit(' ', 1)[0] + '…'
        save(folder(c) / f'{time.time_ns()}-{os.getpid()}.json',
             {'ids': list(dict.fromkeys(x for x in ids if x)), 'what': what, 'reason': reason,
              'said': hashlib.sha256(said.encode()).hexdigest()[:16] if said else '',
              'at': at or time.time(), **(author(c) if who is None else who), **({'closes': True} if closes else {})})
    except (OSError, AttributeError):
        pass


def filed(c, ids, who: dict | None = None) -> None:
    """F209a: the control session `who` (this command's own: `author`) filed the items `ids` (a concept and its build,
    a DECIDE), so it is about them. Kept by session id: a number is handed out again. Nothing without one, and
    it never stops the command that filed them."""
    try:
        who = author(c) if who is None else who
        if sid := who['sid']:
            f = filed_file(c, sid)
            save(f, {**read_json(f, {}), 'n': who['n'], 'sid': sid,
                     'ids': list(dict.fromkeys([*filed_ids(c, sid), *(x for x in ids if x)]))})
    except (OSError, AttributeError):
        pass


def filed_question(c, sid: str, tid: str, ask_id: str, what: str) -> None:
    """F192a3: the item `tid`, filed by session `sid` (`filed`, before this), is its question `ask_id`
    (`chat_question.ask`), which reads `what` under Needs you (`plan.asks`)."""
    try:
        f = filed_file(c, sid)
        d = read_json(f, {})
        save(f, {**d, 'asked': {**d.get('asked', {}), tid: {'id': ask_id, 'what': what}}})
    except OSError:
        pass


def filed_questions(c, sid: str) -> dict[str, dict]:
    """F192a3: {item: {'id', 'what'}} of the questions of session `sid` filed under Needs you, the oldest first."""
    ids = filed_ids(c, sid)
    asked = read_json(filed_file(c, sid), {}).get('asked', {}) if ids else {}
    return {t: asked[t] for t in ids if t in asked}


def filed_file(c, sid: str) -> Path:
    return folder(c) / f'{sid}.filed'


def filed_ids(c, sid: str) -> list[str]:
    return read_json(filed_file(c, sid), {}).get('ids', []) if sid else []


def substance(rest: list[str]) -> list[str]:
    """`edit`'s arguments without `--files X` and `--pri X`: [] when it settles nothing (only its files or place)."""
    out, i = [], 0
    while i < len(rest):
        if rest[i] in ('--files', '--pri'):
            i += 2
        else:
            out.append(rest[i])
            i += 1
    return out


def noting(c, a, todo, run):
    """Run plan subcommand `a` (`run`: its exit code) and record what it settled."""
    if a.cmd not in VERBS:
        return run()
    said = list(getattr(a, 'rest', None) or [])
    if a.cmd == 'edit' and not (said := substance(said)):
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
        record(c, ids, VERBS[a.cmd], '' if a.cmd in NO_REASON else ' '.join(getattr(a, 'rest', None) or []),
               said='\n'.join(said), closes=a.cmd in CLOSES and by_person(c))
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
    """The items control session `n` is about: what its title starts with, what it was opened from, and
    the concepts and DECIDEs it filed itself (`filed`)."""
    from agent_runner import control as K, state
    from agent_runner.control_names import person_name
    title = person_name(n, f.get('title', '')) or (f.get('title', '') if K.control_renamed({'title': f.get('title', '')}, n)
                                                   else K.control_given(n))
    return {x for x in (title_id(title, state.ROOT.name), f.get('opened', ''),
                        *filed_ids(state.C, sid)) if x}


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
        files = sorted(d.glob('*-*.json'))
        for do in (pick, step):  # all picked before any is typed: repeats that came together are one line
            for f in files:
                try:
                    do(f, now)
                except Exception as e:  # noqa: BLE001 - one event never stops the others
                    state.log(f'{f.name}: a settled item could not be told: {e}')
                    f.unlink(missing_ok=True)
        if force or now - LEFT_AT[0] >= LEFT_EVERY:
            LEFT_AT[0] = now
            look_left(d, now)
    except Exception as e:  # noqa: BLE001 - never stops the run loop
        state.log(f'the settled items could not be looked at: {e}')


def told_key(ev: dict) -> list:
    """What an event and its repeat have in common, besides the item."""
    return [ev['what'], ev.get('by', ''), ev.get('sid', ''), ev.get('reason', '')]


def pick(f: Path, now: float) -> None:
    """One event, the first time: choose its sessions, without those told the same a moment ago (`told.json`: {item:
    its last event's key and {sid: who was picked for it}})."""
    ev = read_json(f, {})
    if not ev.get('ids') or now - ev.get('at', 0) > KEEP:
        return f.unlink(missing_ok=True)
    if 'to' in ev:
        return
    ev['to'] = {}
    told = {i: t for i, t in read_json(f.parent / 'told.json', {}).items()
            if any(now - x['at'] <= KEEP for x in t['sids'].values())}
    key, picked, replaced = told_key(ev), {}, {}
    for n, sid, fx, ids in live():
        hit = next((i for i in ev['ids'] if i in ids), '')
        mine = sid == ev['sid'] if ev.get('sid') else n == ev.get('n')
        if not hit or mine or fx.get('begun', 0) > ev['at']:  # one begun since reads it as it is now
            continue
        last = told[hit]['sids'].get(sid) if hit in told and told[hit]['key'] == key else None
        if last:
            same = last['said'] == ev.get('said', '')
            waits = sid in read_json(f.parent / last['file'], {}).get('to', {})
            if waits and (same or not ev.get('reason')):  # this one takes its place; no words of its line are lost
                replaced[sid] = last['file']
            elif not waits and same and ev['at'] - last['at'] <= AGAIN:
                picked[sid] = last
                continue
        ev['to'][sid] = {'id': hit, 'tries': 0}
        picked[sid] = {'at': ev['at'], 'said': ev.get('said', ''), 'file': f.name}
    for i in ev['ids']:
        told[i] = {'key': key, 'sids': picked}
    save(f, ev)  # first: a run killed here tells a waiting one twice, never not at all
    for sid, name in replaced.items():
        if old := read_json(f.parent / name, {}):
            old['to'].pop(sid, None)
            save(f.parent / name, old)
    save(f.parent / 'told.json', {i: t for i, t in told.items() if t['sids']})
    forget_wait(f.parent, ev['ids'])


def not_told(f: Path, ev: dict, sid: str) -> None:
    """Event `f` could not be typed into session `sid`: a repeat of it is no repeat there."""
    told = read_json(f.parent / 'told.json', {})
    for i in ev['ids']:
        if i in told and told[i]['sids'].get(sid, {}).get('file') == f.name:
            del told[i]['sids'][sid]
    save(f.parent / 'told.json', {i: t for i, t in told.items() if t['sids']})


def step(f: Path, now: float) -> None:
    """One picked event: type it into each session that can take it."""
    from agent_runner import control as K, control_held as H, state
    ev = read_json(f, {})
    if 'to' not in ev:
        return
    for sid, to in list(ev['to'].items()):
        n = H.live_number(sid)
        fx = facts(sid)
        if not n or fx.get('closed'):  # ended since: nothing is typed, nor when it comes back
            del ev['to'][sid]
            continue
        if not state.C.notes(f'control{n}.in').exists():
            state.log(f'control {n}: not told that {to["id"]} {ev["what"]}: it takes no typed text')
            del ev['to'][sid]
            not_told(f, ev, sid)
            continue
        began = state.C.notes(f'control{n}.pid').stat().st_mtime
        if ev.get('closes') and 'keep' not in to:  # F209b
            why = keep_why(n, sid, fx, ev)
            if why is None:  # a turn under way: looked at again when it ends
                continue
            if not why:
                del ev['to'][sid]
                save(f, ev)  # before closing: a restarted run closes nothing twice
                close_chat(n, sid, to['id'], ev)
                continue
            ev['to'][sid] = to = {**to, 'keep': why}
            save(f, ev)
            state.log(f'control {n}: kept open, {to["id"]} {ev["what"]} but {why}')
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
            not_told(f, ev, sid)
    if ev['to']:
        save(f, ev)
    else:
        f.unlink(missing_ok=True)


def keep_why(n: int, sid: str, fx: dict, ev: dict) -> str | None:
    """F209b: why chat `n` (session `sid`, its `facts` `fx`) stays open though the person settled event `ev`'s item
    for good: '' when nothing keeps it, None while a turn is under way (looked at again when it ends). The keep
    reasons are `control_verdict`'s, and a take it runs or another item it is about still under Needs you."""
    from agent_runner import control as K, control_held as H, pitch, plan as P, sched, state, taken_by
    st = K.control_state(K.entries(sid, skip_bad=True))
    if K.control_renamed(st, n):
        return 'renamed by the person'
    if st['last'] == 'tool':
        return None
    if st['last'] != 'claude':
        return 'the person spoke last' if st['last'] == 'person' else 'no turn yet'
    if st['running']:
        return f'{len(st["running"])} background task(s) still running'
    if K.decide_question(st['text']):
        return 'its last message asks another DECIDE'
    if fx.get('dialog'):
        return 'a question dialog is up'
    if H.holds(sid):
        return 'a message is held'
    if any(taken_by.chat(state.C, d, [n]) == n for d in sched.taken().values()):
        return 'a take of it runs'
    if others := about(n, sid, fx) - set(ev['ids']):
        asks = [*P.asks(state.C.todo), *pitch.rows(state.C)]
        if waiting := sorted(others & {i for a in asks for i in (a[1], a[2]) if i}):
            return f'it is about {", ".join(waiting)} too, still waiting'
    return ''


def close_chat(n: int, sid: str, tid: str, ev: dict) -> None:
    """F209b: end chat `n`: its process ends, its transcript stays (Resume brings it back, it is listed as closed)."""
    from agent_runner import control_closed, control_harness, plat, state
    pidf = state.C.notes(f'control{n}.pid')
    try:
        pid = int(pidf.read_text(encoding='utf-8').split()[0])
    except (OSError, ValueError, IndexError):
        return
    plat.terminate(pid)
    pidf.unlink(missing_ok=True)
    control_closed.idle_closed(n, sid, time.time())
    state.log(f'control {n}: closed, {tid} {ev["what"]} by the person (transcript kept: '
              f'{control_harness.resume_hint(sid)})')


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
    kin = concept_builds(left)
    for i, at in left.items():
        if i in kin:  # told once, as its build's
            continue
        what, reason = outcome(i)
        by = d / f'{i}.by'
        who = read_json(by, {}) if what == 'landed' else {}
        by.unlink(missing_ok=True)
        record(state.C, [i, *(k for k in kin if kin[k] == i)], what, reason, who=who or {'by': '', 'n': 0, 'sid': ''}, at=at)
    if waits != was:
        save(d / 'waits.json', waits)


def concept_builds(ids) -> dict[str, str]:
    """{a concept: its build task} of those of `ids` that both are in it: a chat can be about both (F209a)."""
    from agent_runner import plan as P, state
    out = {}
    for path in (state.C.todo, state.C.done):
        for l in P.lines(path):
            if (m := P.ITEM.match(l)) and (b := m.group(3).rstrip('.')) in ids:
                if 'Build the option a person approves on concept ' in l and (k := P.FROM_CONCEPT.search(l)) and k[1] in ids:
                    out[k[1]] = b
    return out


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


def several_questions(rows: list, ask: dict | None) -> list[tuple[dict, str]]:
    """F192b1b: (its `chat_question.asks_of` entry, its DECIDE question as written) of each question the answer that
    holds open question `ask` ends on, when it ends on more than one; [] otherwise."""
    from agent_runner import chat_question
    from agent_runner.control import message_text
    said = ask and next((d for d in reversed(rows) if isinstance(d, dict) and d.get('type') == 'assistant'
                         and d.get('uuid') == ask['id']), None)
    if not said:
        return []
    text = message_text(said)
    qs, asks = chat_question.decide_questions(text), chat_question.asks_of(text, ask['id'], bare=True)
    return list(zip(asks, qs)) if len(qs) > 1 and len(asks) == len(qs) else []


def to_file(rows: list, sid: str, q: str) -> tuple[list[str], list[tuple[dict | None, str]]]:
    """F192b1b: (the items that still ask them, the (ask, question) left to file) of the questions open in transcript
    entries `rows` of session `sid`; `q` the question as `control_verdict` read it, for an answer with one."""
    from agent_runner import chat_question
    ask = chat_question.ask(rows)
    asks = several_questions(rows, ask or chat_question.ask(rows, bare=True)) or [(ask, q)]
    waits = chat_question.needs(sid) if any(a for a, _ in asks) else {}
    have = [t for a, _ in asks if a and (t := waits.get(a['id']))]
    return have, [(a, x) for a, x in asks if not (a and waits.get(a['id']))]


def questions_filed(c, todo, new: list, sid: str, n: int, rows: list) -> None:
    """F192b1b: the items `new` [(id, ask, question)] were committed: each knows its question (`filed_question`)."""
    from agent_runner import control_ask, plan as P
    waiting = {a[1]: a[3] for a in P.asks(todo, all=True)}
    for tid, a, x in new:
        control_ask.filed(tid, sid, x, rows, n)  # B809b: after the commit, as a block takes the ask file away
        filed(c, [tid], {'n': n, 'sid': sid})  # F209a: reopened, it is about its question
        if a and (what := waiting.get(tid, '')):
            filed_question(c, sid, tid, a['id'], what)
