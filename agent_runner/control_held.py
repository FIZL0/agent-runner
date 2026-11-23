"""B170: a person's messages to a control session that met a usage limit are held, and put in once it is over.

Claude Code answers such a message with only an API error and never retries it, and nothing here looked at a
control session's transcript for that (a slot's session is resumed by `watch.cut_off`), so the ask was lost.
Every HELD_EVERY s the run reads the transcript of each control session with a pid file: the person's messages
whose reply was only a usage-limit error, and that no later turn of theirs got an answer to (`walk`), are held
in `<notes>/held/<sid>.json`. The transcript stays the truth; the record only outlives the pid file, so a session
that has ended, or a run that was down, is found again. While one is held `close_controls` leaves the session open
and `status` says so. Once the limit is over they are typed into the session in one message, in order
(HELD_LEAD), after reopening it when it has ended. A try that meets the limit again is only another error in the
transcript, so they stay held till the new reset. One typed is not typed again until the transcript shows how
it went or its process has ended. A session the person closed (`end_control`, /exit, /clear, archived online) is
dropped (`drop`).

Not one of the FAMILY modules `share` reaches, so the run's settings are read through their modules at call time."""

from __future__ import annotations

import base64
import binascii
import datetime as dt
import json
import re
import time
from pathlib import Path

from agent_runner import control as K, fallback, plat, state

HELD_EVERY = 30  # s between looks
HELD_AT = [0.0]
HELD_MARGIN = 60  # s past the reset before the messages go in
HELD_SETTLE = (90, 30)  # s a session must have been up before it is typed into: on Remote Control, else
HELD_LOST = 600  # s a session the runner reopened may show nothing of what was typed before it is started again
HELD_TRIES = 3  # times a reopen, or an answer that is another API error, may fail before it is left to the person
HELD_TURN = 900  # s a message with no reply yet counts as a turn under way
HELD_LEAD = '[agent-runner: held by the usage limit]'
CLOSED_BY = re.compile(r'<command-name>/(exit|quit|clear)</command-name>')
WAITING_BLOCK = re.compile(r'\s*<runner-waiting>.*?</runner-waiting>', re.S)
RUNNER_SAID = ('Open with the summary your control brief describes', 'Say first, in one line: "c1 starts a fresh',
               'agent-runner: the run changed. ')  # the first messages the runner itself gives (CONTROL_START, F27, F68)
HELD, RUNNER = 'held', 'runner'  # what `walk` keeps for a message with no reply yet that is not the person's
_SEEN: dict[str, tuple] = {}  # sid -> (what its transcript was, `walk` of it)


def folder() -> Path:
    return state.C.notes('held')


def record_file(sid: str) -> Path:
    return folder() / f'{sid}.json'


def load(f: Path) -> dict:
    try:
        d = json.loads(f.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) and d.get('sid') and isinstance(d.get('n'), int) else {}


def save(rec: dict) -> None:
    folder().mkdir(parents=True, exist_ok=True)
    tmp = record_file(rec['sid']).with_suffix('.tmp')
    tmp.write_text(json.dumps(rec), encoding='utf-8')
    tmp.replace(record_file(rec['sid']))


def records() -> list[dict]:
    return [r for f in sorted(folder().glob('*.json')) if (r := load(f))]


def drop(sid: str) -> None:
    """The person closed session `sid` (or sent its messages again elsewhere): what it holds up to now is never
    put in."""
    if not sid:
        return
    try:
        folder().mkdir(parents=True, exist_ok=True)
        (folder() / f'{sid}.dropped').write_text(str(time.time()), encoding='utf-8')
        record_file(sid).unlink(missing_ok=True)
    except OSError as e:
        state.log(f'control: could not drop the held messages of {sid}: {e}')


def dropped_at(sid: str) -> float:
    try:
        return float((folder() / f'{sid}.dropped').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return 0.0


# --- what a transcript holds ---------------------------------------------------------------------------------

def as_message(d: dict) -> dict | None:
    """A transcript entry as a user message: itself, or one the person typed during a turn (an attachment)."""
    if d.get('type') == 'user':
        return d
    a = d.get('attachment') if d.get('type') == 'attachment' else None
    if isinstance(a, dict) and a.get('type') == 'queued_command' and a.get('commandMode', 'prompt') == 'prompt':
        return {**d, 'type': 'user', 'origin': a.get('origin'), 'message': {'content': a.get('prompt')},
                'uuid': a.get('source_uuid') or d.get('uuid'), 'timestamp': a.get('timestamp') or d.get('timestamp')}
    return None


def norm(text: str) -> str:
    """A message's words, for telling a resent one: without what the runner added around them, spaces or case."""
    text = WAITING_BLOCK.sub('', text).removeprefix(K.TALK_TAG)
    if text.startswith(K.TALK_BRIEF):
        text = text.removeprefix(K.TALK_BRIEF).lstrip().removeprefix(K.TALK_SAID)
    return ' '.join(text.split()).casefold()


def files_of(d: dict) -> list[dict]:
    """The images and documents in a message, as their base64 sources."""
    c = (d.get('message') or {}).get('content')
    return [x['source'] for x in c if isinstance(x, dict) and x.get('type') in ('image', 'document')
            and isinstance(x.get('source'), dict) and x['source'].get('data')] if isinstance(c, list) else []


def same(a: dict, b: dict) -> bool:
    return a['norm'] == b['norm'] and [f.get('data') for f in a['files']] == [f.get('data') for f in b['files']]


def walk(rows, dropped: float = 0.0) -> dict:
    """What transcript entries `rows` hold: 'asks', the person's messages in order whose reply was only a
    usage-limit error and that no later turn of theirs answered ({id, at, text, norm, files}; one sent twice
    counts once), none sent before `dropped`; 'until', when the last such error says the limit is over; 'open',
    the messages with no reply yet; 'held_at', when a HELD_LEAD message last came in; 'errors', the replies to
    one that were some other API error; 'answered', {words: when} of the person's answered messages; 'last_at'."""
    w = {'asks': [], 'until': 0.0, 'open': [], 'held_at': 0.0, 'errors': 0, 'answered': {}, 'last_at': 0.0}
    fails = 0
    for d in rows:
        if not isinstance(d, dict) or d.get('isSidechain'):
            continue
        at = K._stamp(d) or 0.0
        w['last_at'] = max(w['last_at'], at)
        if m := as_message(d):
            at = K._stamp(m) or at
            text = K.message_text(m)
            if CLOSED_BY.search(text) and text.lstrip().startswith('<command-'):
                w['asks'], w['open'] = [], []
            elif text.startswith('[Request interrupted'):  # the person stopped that turn
                if HELD in w['open']:
                    w['asks'] = []
                w['open'] = []
            elif HELD_LEAD in text[:400] and not m.get('isMeta'):
                w['open'].append(HELD)
                w['held_at'] = at
            elif K.person_turn(m):
                w['open'].append(RUNNER if text.startswith(RUNNER_SAID) else
                                 {'id': str(m.get('uuid') or at), 'at': at, 'text': WAITING_BLOCK.sub('', text).strip(),
                                  'norm': norm(text), 'files': files_of(m)})
        elif d.get('type') == 'assistant':
            mine = [a for a in w['open'] if isinstance(a, dict)]
            if d.get('isApiErrorMessage'):
                if lim := fallback.limit_of(d):
                    w['asks'] += [a for a in mine if not (a['at'] and a['at'] <= dropped)]
                    fails = fails + 1 if HELD in w['open'] else fails
                    hold = fallback.CAP_HOLD * 2 ** min(max(fails - 1, 0), 3)
                    w['until'] = lim[1] if lim[1] and lim[1] > at else at + hold
                elif HELD in w['open']:
                    w['errors'] += 1
                    w['until'] = at + fallback.CAP_HOLD
                w['open'] = []
                continue
            msg = d.get('message') if isinstance(d.get('message'), dict) else {}
            if msg.get('model') == '<synthetic>':  # Claude Code's own "No response requested.", not an answer
                continue
            c = msg.get('content')
            if not (isinstance(c, str) and c.strip() or isinstance(c, list) and any(
                    isinstance(x, dict) and (x.get('type') == 'tool_use' or str(x.get('text') or '').strip())
                    for x in c)):
                continue
            if mine or HELD in w['open']:  # not a turn a notification or the runner began
                w['answered'].update({a['norm']: a['at'] for a in mine + w['asks']})
                w['asks'], w['errors'], fails = [], 0, 0
            w['open'] = []
    out: list[dict] = []
    for a in w['asks']:
        if not any(same(a, b) for b in out):
            out.append(a)
    w['asks'] = out
    return w


def read(sid: str) -> dict:
    """`walk` of session `sid`'s transcript, and 'online': its Remote Control session was closed online. Kept
    while the transcript has not changed."""
    path, was = K.transcript(sid), dropped_at(sid)
    try:
        st = Path(path or '').stat() if path else None
    except OSError:
        st = None
    key = (path, was, st and (st.st_size, st.st_mtime_ns))
    if st and _SEEN.get(sid, ('',))[0] == key:
        return _SEEN[sid][1]
    rows = list(K.entries(sid, skip_bad=True))
    w = {**walk(rows, was), 'online': K.closed_online(rows)}
    _SEEN[sid] = (key, w)
    return w


def holds(sid: str) -> bool:
    """Whether session `sid` holds messages that are still to go in: it is not closed as idle."""
    rec = load(record_file(sid))
    return not rec.get('stuck') and bool(read(sid)['asks'])


def resent(sid: str, asks: list[dict]) -> set[str]:
    """The ids of `asks` (held by `sid`) that the person sent again later, in another session of this checkout,
    and got answered there, or that another session holds too (the latest one puts it in)."""
    out = set()
    others = {r['sid'] for r in records()} - {sid}
    first = min(a['at'] for a in asks)
    home = Path(K.transcript(sid) or '.').parent
    for f in home.glob('*.jsonl'):
        try:
            if f.stem == sid or f.stat().st_mtime < first:
                continue
        except OSError:
            continue
        others.add(f.stem)
    for o in others:
        w = read(o)
        kept = w['asks'] if record_file(o).exists() else []
        out |= {a['id'] for a in asks if a['norm'] and (
            w['answered'].get(a['norm'], 0.0) > a['at'] or
            any(same(a, b) and (b['at'], o) > (a['at'], sid) for b in kept))}
    return out


# --- the record of a session that holds messages ---------------------------------------------------------------

def pid_sid(n: int) -> tuple[int, str]:
    """(pid, sid) as control session `n`'s pid file names them; (0, '') without one."""
    try:
        p, _, sid = state.C.notes(f'control{n}.pid').read_text(encoding='utf-8').strip().partition(' ')
        return int(p), sid.strip()
    except (OSError, ValueError):
        return 0, ''


def numbers() -> list[int]:
    return sorted(int(m[1]) for f in state.C.notes().glob('control*.pid')
                  if (m := re.fullmatch(r'control(\d+)\.pid', f.name)))


def live_number(sid: str) -> int:
    """The number of the live control session in conversation `sid`; 0 for none."""
    return next((n for n in numbers() if pid_sid(n)[1] == sid and K.control_live(n)), 0)


def look(n: int) -> None:
    """Keep a record of control session `n`'s held messages, if it has any. Called every HELD_EVERY s, and
    before its pid file goes or its number is used again."""
    try:
        pid, sid = pid_sid(n)
        if not sid or not K.transcript(sid):
            return
        w = read(sid)
        if not w['asks'] or w['online']:
            return
        rec = load(record_file(sid))
        new = {**rec, 'n': n, 'sid': sid, 'pid': pid, 'name': K.control_given(n) or rec.get('name') or '',
               'asks': len(w['asks']), 'until': w['until']}
        if new != rec:
            save(new)
        if not rec:
            state.log(f'control: {line(new)}')
    except Exception as e:  # noqa: BLE001 - one unreadable session never stops a close, a start or the loop
        state.log(f'control {n}: could not look for messages held by a usage limit: {e}')


def asks_text(k: int) -> str:
    return f'{k} ask' + ('' if k == 1 else 's')


def line(rec: dict) -> str:
    """A record as `status` and the run log say it: which chat, how many asks wait, and for what."""
    k = int(rec.get('asks') or 0)
    chat = f'c{rec["n"]}' + (f' "{rec["name"]}"' if rec.get('name') else '')
    one = k == 1
    start = f'{chat}: {asks_text(k)} {"waits" if one else "wait"}'
    if rec.get('stuck'):
        return f'{start} since a usage limit and could not be put in: {rec["stuck"]}. Send {"it" if one else "them"} again'
    until = float(rec.get('until') or 0)
    if until + HELD_MARGIN > time.time():
        when = dt.datetime.fromtimestamp(until).strftime('%a %H:%M')
        return (f'{start} for the usage limit, which resets {when}; '
                f'the runner puts {"it" if one else "them"} in then')
    return f'{start} to go in: ' + (rec.get('why') or 'the usage limit should be over')


def lines() -> list[str]:
    """`status`'s lines, one per chat that holds messages."""
    return [line(r) for r in records()]


# --- putting them in ---------------------------------------------------------------------------------------------

def saved_file(sid: str, ask: dict, i: int, src: dict) -> str:
    """One file of a held message, written beside the record (the session may have ended): its path, or ''."""
    ext = re.sub(r'\W', '', str(src.get('media_type') or 'image/png').split('/')[-1].split('+')[0]) or 'png'
    f = folder() / f'{sid}-{re.sub(r"[^0-9A-Za-z]", "", ask["id"])[:12]}-{i}.{ext}'
    try:
        f.write_bytes(base64.b64decode(src['data']))
    except (OSError, ValueError, TypeError, binascii.Error):
        return ''
    return str(f)


def message(sid: str, asks: list[dict]) -> str:
    """The one message that puts `asks` into their session, in order, marked as held."""
    k = len(asks)
    out = [f'{HELD_LEAD} The usage limit is over. ' +
           ('This message from the person got' if k == 1 else f'These {k} messages from the person got') +
           ' only its error as a reply. In their own words, in the order sent; answer each once, and skip one you '
           'have already dealt with:']
    for i, a in enumerate(asks, 1):
        sent = dt.datetime.fromtimestamp(a['at']).strftime(' (%a %H:%M)') if a['at'] else ''
        out.append(f'Message {i} of {k}{sent}: {a["text"]}'.rstrip())
        for j, src in enumerate(a['files'], 1):
            if p := saved_file(sid, a, j, src):
                out.append(f'The person attached this to message {i}, saved at "{p}": Read it before you answer.')
    return '\n\n'.join(out)


def reopen(rec: dict) -> bool:
    """Start the ended session of `rec` from its transcript, hidden, under its number or (when another has it)
    the first free one, which `rec` then names. Whether it started."""
    from agent_runner import control_reopen as CR
    n, sid = rec['n'], rec['sid']
    if n == 1:
        try:
            kept = state.C.notes('control.sid').read_text(encoding='utf-8').strip()
        except OSError:
            kept = ''
        if kept == sid and not K.control_taken(1):  # the run's own c1, as the run opens it, with no opening summary
            cmd = [*K.runner_cmd(), 'control', '1', '--blank', *(['--local'] if K.remote_on() else [])]
            if plat.WINDOWS and not plat.has_conpty():
                plat.spawn_console(cmd, state.ROOT, K.control_env(), hidden=True)
                return True
            return bool(K.hidden_control(1, cmd)[0])
    if n > 1 and not K.control_taken(n) and K.control_claim(n):
        m = n
    else:
        m = K.claim_control_number()
    if m == 1:  # number 1 is the run's kept session's
        K.control_unclaim(1)
        m = 2
        while K.control_taken(m) or not K.control_claim(m):
            m += 1
    try:
        if m != n:
            look(m)
        state.C.notes(f'control{m}.pid').unlink(missing_ok=True)
        K.control_keep_sid(m, sid)
        if m != n or not K.control_given(m):
            K.control_give(m, rec.get('name') or K.control_base_name(m))
        ok = bool(CR.reopen_control(m, sid))
        rec['n'] = m
        return ok
    finally:
        K.control_unclaim(m)


def finished(rec: dict, why: str) -> None:
    record_file(rec['sid']).unlink(missing_ok=True)
    state.log(f'control: the messages c{rec["n"]} held for the usage limit are done with: {why}')


def stays(rec: dict, why: str = '', stuck: str = '') -> None:
    """`rec` waits on, saying `why`; `stuck`: it is left to the person, said once in the run log."""
    if stuck and not rec.get('stuck'):
        rec['stuck'] = stuck
        state.log(f'control: {line(rec)}')
    rec['why'] = why
    save(rec)


def step(rec: dict, now: float) -> None:
    """One look at a session that holds messages: forget it, wait, reopen it, or put them in."""
    sid, n = rec['sid'], rec['n']
    if not K.transcript(sid):
        return finished(rec, 'its transcript is gone')
    w = read(sid)
    if not w['asks']:
        return finished(rec, 'answered' if w['held_at'] or w['answered'] else 'the person closed it')
    pid, pid_names = pid_sid(n)
    cleared = pid and pid == rec.get('pid') and pid_names != sid and K.control_live(n) == pid  # /clear or /new
    if w['online'] or cleared:
        drop(sid)
        return finished(rec, 'the person closed that conversation')
    rec['asks'], rec['until'] = len(w['asks']), w['until']
    if rec.get('typed') and w['held_at'] >= rec['typed']['at'] - 5 and HELD not in w['open']:
        for k in ('typed', 'reopened', 'tries'):  # its reply was an error: a fresh try once that is over
            rec.pop(k, None)
    if rec.get('stuck') or now < w['until'] + HELD_MARGIN:
        return stays(rec, stuck=rec.get('stuck') or '')
    live = live_number(sid)
    if live:
        rec['n'] = n = live
        pid = rec['pid'] = K.control_live(live)
    if t := rec.get('typed'):
        seen = w['held_at'] >= t['at'] - 5
        if live and pid == t['pid']:
            if not seen and rec.get('reopened') and now - t['at'] > HELD_LOST and w['last_at'] < t['at']:
                # the session the runner started never took it (a dialog, say): start it again
                plat.terminate(pid)
                rec.pop('typed')
                rec['tries'] = rec.get('tries', 0) + 1
                return stays(rec, 'its session is started again')
            return stays(rec, 'typed in; the session has not answered yet')
        else:
            rec.pop('typed')  # that process ended with no answer
    if w['errors'] >= HELD_TRIES or rec.get('tries', 0) >= HELD_TRIES:
        return stays(rec, stuck='the API refuses it' if w['errors'] >= HELD_TRIES else 'its session does not come up')
    # looked at again before it is put in, and before its session is reopened for it
    gone = resent(sid, w['asks'])
    asks = [a for a in w['asks'] if a['id'] not in gone]
    if not asks:
        drop(sid)
        return finished(rec, 'the person sent them again elsewhere')
    if not live:
        return step_ended(rec, now)
    started = state.C.notes(f'control{n}.pid').stat().st_mtime
    if now - started < HELD_SETTLE[0 if K.remote_on() else 1]:
        return stays(rec, 'its session is starting')
    if w['open'] and now - w['last_at'] < HELD_TURN:
        return stays(rec, 'a turn is under way')
    if not state.C.notes(f'control{n}.in').exists():
        return stays(rec, 'its session is open in a terminal the runner cannot type into; they go in once it ends')
    text = message(sid, asks)
    rec['typed'] = {'at': now, 'pid': pid}
    stays(rec, 'typed in; the session has not answered yet')  # before typing: a run killed here never types twice
    if K.control_type(n, text):
        state.log(f'control {n}: the usage limit is over: put in the {asks_text(len(asks))} it held')
    else:
        rec.pop('typed')
        stays(rec, 'its session takes no typed text')


def step_ended(rec: dict, now: float) -> None:
    """`step` for a session with no live control process: reopen it, unless someone else has it."""
    from agent_runner.watch import live_session
    n, sid = rec['n'], rec['sid']
    if live_session(sid):
        return stays(rec, 'its conversation is open outside the runner; they go in once that ends')
    if not state.C.run['control']:
        return stays(rec, 'its session has ended, and [run] control is off')
    if now - rec.get('reopened', 0) < max(HELD_SETTLE) or (K.control_taken(n) and K.control_kept_sid(n) == sid):
        return stays(rec, 'its session is starting')
    rec['tries'] = rec.get('tries', 0) + 1 if rec.get('reopened') else rec.get('tries', 0)
    if rec['tries'] >= HELD_TRIES:
        return stays(rec, stuck='its session does not come up')
    rec['reopened'] = now
    if reopen(rec):
        state.log(f'control {rec["n"]}: reopened for the asks it held for the usage limit (--resume {sid})')
        stays(rec, 'its session is starting')
    else:
        stays(rec, 'its session could not be started')


def held_tick(force: bool = False, now: float | None = None) -> None:
    """Every HELD_EVERY s from the run loop: look at each control session, then at each record."""
    now = time.time() if now is None else now
    if not force and now - HELD_AT[0] < HELD_EVERY:
        return
    HELD_AT[0] = now
    for n in numbers():
        look(n)
    for rec in records():
        try:
            step(rec, now)
        except Exception as e:  # noqa: BLE001 - one record never stops the loop or the others
            state.log(f'control {rec["n"]}: its held messages could not be looked at: {e}')


def controls_tick(branch: str) -> None:
    """The run loop's look at the control sessions: held messages (B170), idle ones (B26), ones closed online (B53)."""
    held_tick()
    K.close_controls(branch)
    K.end_closed_controls()
