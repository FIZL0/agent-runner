"""F192a: the question a chat waits on, for the question card: the DECIDE line with options that its last answer ends on,
or, talked about since (F430), an earlier one.

Read from the session's transcript, as the run reads it to file the question under Needs you (`control.control_state`,
`plan.decide_question`), so the card and Needs you ask the same words."""

from __future__ import annotations

import hashlib
import re

from agent_runner import need_detail
from agent_runner.plan import cut_question, decide_question


def ask_of(text: str, uuid: str = '', bare: bool = False) -> dict | None:
    """The question Claude's message `text` ends on: {'id' (its transcript entry's `uuid`, else one made of its
    words, as cut before B840: one filed then keeps its id), 'question', 'options': [{'name', 'rec'}], the recommended first}.
    None when it ends on no DECIDE line, or on one with no options (a malformed bracket is part of the question, as in Needs you);
    B832: `bare`, one with no options is that question with `options` [] (Home's Needs you lists it)."""
    q = decide_question(text)
    options, question = need_detail.decide_options('', q, f'DECIDE: {q}') if q else ([], '')
    if not options and not (bare and q):
        return None
    question = re.sub(r'(?:\s+https?://\S+)+\s*$', '', question)  # the links after the bracket
    return {'id': uuid or hashlib.sha256(cut_question(q).encode('utf-8')).hexdigest()[:16], 'question': question, 'options': options}


def needs(sid: str) -> dict[str, str]:
    """F192a3: {question id: the item that still asks it under Needs you (shelved too), '' once it does not} of the
    questions of session `sid` the run filed there. An item answered once, or that asks something else by now, is not that question's.
    With a plan that does not read, every item waits: `ui_model.question_answer` looks again."""
    from agent_runner import control_settled, plan as P, state
    if not (filed := control_settled.filed_questions(state.C, sid)):
        return {}
    try:
        waits = {a[1]: a[3] for a in P.asks(state.C.todo, all=True) if a[0] == 'DECIDE'}
        again = {t for t in filed if t in waits and ' — your answer (' in ' '.join(x.strip() for x in P.section(state.C.todo, t))}
    except (SystemExit, OSError):
        waits = {t: q['what'] for t, q in filed.items()}
        again = set()
    out: dict[str, str] = {}
    for tid, q in filed.items():
        out[q['id']] = out.get(q['id']) or (tid if waits.get(tid) == q['what'] and tid not in again else '')
    return out


def need_of(chat: str, ask_id: str, sid: str) -> str:
    """The item question `ask_id` of `chat` (c6) waits as; '' for none. `sid`: its session, '' once it closed (filing
    the question ends it): then the sessions that had its number."""
    from agent_runner import control_settled as Z, state
    sids = [sid] if sid else [d.get('sid', '') for f in Z.folder(state.C).glob('*.filed')
                              if f'c{(d := Z.read_json(f, {})).get("n")}' == chat]
    return next((t for s in sids if (t := needs(s).get(ask_id))), '')


def joined(ask: dict | None, sid: str) -> dict:
    """F192a3: what /live says of `ask` (`ask` of session `sid`): 'ask' with 'need', the item it is under Needs you, and
    None once that was answered there; 'answered', the ids of the session's questions that were."""
    ids = needs(sid)
    if ask and ask['id'] in ids:
        ask = {**ask, 'need': ids[ask['id']]} if ids[ask['id']] else None
    return {'ask': ask, 'answered': [i for i, tid in ids.items() if not tid]}


# F430: how a message about the question (Chat about this) begins, as 024-questionchat.logic.js words it
ABOUT, NOT = 'About your question “', '” (not my answer): '
PASTE = re.compile(r'<pasted_content[^>]*>\n?(.*?)</pasted_content[^>]*>\n?', re.S)  # Claude Code wraps a paste (each message typed in is one) in it


def is_about(text) -> bool:
    """Are the words `text` of one message about the question, not its answer? Of several pastes in one message, each
    must be; words that begin so with no paste around them are one message, whatever follows."""
    def one(t: str) -> bool:
        return t.startswith(ABOUT) and NOT in t
    if not isinstance(text, str):
        return False
    if one(text.lstrip()):
        return True
    parts = [t.strip() for t in PASTE.split(text) if t.strip()]
    return bool(parts) and all(map(one, parts))


def _about(d: dict) -> bool:
    """`is_about` of a person's transcript entry; an image in it changes nothing."""
    c = (d.get('message') or {}).get('content')
    texts = [c] if isinstance(c, str) else [x.get('text') for x in c or () if isinstance(x, dict) and x.get('type') == 'text']
    texts = [t for t in texts if isinstance(t, str) and t.strip() and not t.startswith('[Image')]
    return bool(texts) and all(map(is_about, texts))


def ask(rows, bare: bool = False) -> dict | None:
    """The question transcript entries `rows` leave open; None when the person has spoken since, or Claude's turn goes on
    after it (a tool call). F430: messages about it (`is_about`) and Claude's replies to them leave it open, until a reply
    ends on another DECIDE line. `bare` as `ask_of`."""
    from agent_runner.control import message_text, person_turn
    from agent_runner.feed import queued_message
    parts: list[list] = [[]]  # what the person's last other words began, and then each message about the question
    for d in rows:
        if not isinstance(d, dict) or d.get('isSidechain'):
            continue
        d = queued_message(d) or d  # typed during a turn
        if d.get('type') == 'user' and person_turn(d):
            if _about(d):
                parts.append([])
            elif not (len(parts) > 1 and message_text(d).startswith('[Request interrupted')):  # a reply cut short answers nothing
                parts = [[]]
        parts[-1].append(d)
    out = _ends_on(parts[0], bare)[1]
    for part in parts[1:]:
        asks, new = _ends_on(part, bare)
        out = new if asks else out
    return out


def _ends_on(rows: list[dict], bare: bool = False) -> tuple[bool, dict | None]:
    """Whether the last answer in `rows` ends on a DECIDE line, and its `ask_of`."""
    from agent_runner.control import control_state, message_text
    st = control_state(rows)
    if st['last'] != 'claude':
        return False, None
    said = next((d for d in reversed(rows) if d.get('type') == 'assistant' and message_text(d).strip()), {})
    items = (said.get('message') or {}).get('content')
    if any(isinstance(x, dict) and x.get('type') == 'tool_use' for x in (items if isinstance(items, list) else ())):
        return False, None  # a call in the same entry; one after it is `control_state`'s to see
    return bool(decide_question(st['text'])), ask_of(st['text'], str(said.get('uuid') or ''), bare)


def chat_needs(sessions: list[dict]) -> list[dict]:
    """B832: Home's Needs you rows of the live chats in session rows `sessions` (`ui_model.session_rows`) whose answer
    ends on a DECIDE line, at once, before the run files it: {'chat' (cN), 'id' (the question's), 'title' (the chat's
    name), 'question', 'options' (maybe []), 'at' (epoch s)}. Each row's 'question' is `ask(rows, bare=True)` of its
    cached transcript read (`ui_model.chat_state`); one the run filed shows only as its item, so is left out here."""
    out = []
    for r in sessions:
        q, sid = r.get('question'), r.get('sid') or ''
        if not (q and str(r.get('name', '')).startswith('c')):
            continue
        if q['id'] in needs(sid):  # filed: its item asks it (or asked it, and it was answered there)
            continue
        out.append({'chat': r['name'], 'id': q['id'], 'title': r.get('title') or r['name'], 'question': q['question'],
                    'options': q['options'], 'at': int(r.get('at') or 0)})
    return out


def live_needs() -> list[dict]:
    """F486: `chat_needs` of this repository's live chats, for the `needs` command and status's Needs you, which run in
    a process of their own with no cached transcript read: one read per live chat. [] when they cannot be read."""
    try:
        from agent_runner import ui_model as U
        return chat_needs(U.control_rows(U.control_titles()))
    except Exception:  # noqa: BLE001 - a nicety of Needs you: the filed items still show
        return []


def need_lines(rows: list[dict], indent: str = '') -> list[str]:
    """F486: one 'cN - question [A (recommended) / B]' line per `chat_needs` row."""
    out = []
    for r in rows:
        opts = ' / '.join(o['name'] + (' (recommended)' if o.get('rec') else '') for o in r.get('options') or [])
        out.append(f'{indent}{r["chat"]} - {r["question"]}' + (f' [{opts}]' if opts else ''))
    return out


def with_chats(lines: list[str]) -> list[str]:
    """F486: the `needs` command's lines (`plan.needs_lines`, its count last) with the live chats' DECIDE questions
    before the count, counted too."""
    if not (chats := need_lines(live_needs())):
        return lines
    n = len(lines) - 1 + len(chats)
    return lines[:-1] + chats + ['1 thing needs you' if n == 1 else f'{n} things need you']


def decide_questions(text: str) -> list[str]:
    """F192b1: the questions Claude's message `text` ends on, in order: the trailing run of `DECIDE:` lines (each as
    `plan.decide_question` reads one, so a wrapped one too), blank lines between allowed. A DECIDE quoted above other
    words is none."""
    from agent_runner.plan import DECIDE_LINE
    out, lines = [], text.strip().splitlines()
    while lines and (q := decide_question('\n'.join(lines))):
        out.append(q)
        i = max((j for j, x in enumerate(lines) if DECIDE_LINE.match(x)), default=0)
        lines = '\n'.join(lines[:i]).strip().splitlines()
    return out[::-1]


def asks_of(text: str, uuid: str = '', bare: bool = False) -> list[dict]:
    """F192b1: `ask_of` of each question `decide_questions` reads in `text`, in order. The first keeps `ask_of`'s id;
    with `uuid`, the next ones are '<uuid>#2', '<uuid>#3'…, else each is made of its own words. With no `bare`, a
    question with no options is left out."""
    out = []
    for i, q in enumerate(decide_questions(text)):
        a = ask_of(f'DECIDE: {q}', uuid if not (uuid and i) else f'{uuid}#{i + 1}', bare)
        if a:
            out.append(a)
    return out


# F192b1c: how a message that answers one of several questions begins (the page words it alike)
ANSWER, ANSWER_END = 'My answer to your question “', '”: '


def answer_to(text) -> str | None:
    """F192b1c: the question a person's message `text` names as the one it answers (`ANSWER`…`ANSWER_END`), else None."""
    if not isinstance(text, str) or not (t := text.strip()).startswith(ANSWER) or ANSWER_END not in t:
        return None
    return t[len(ANSWER):].split(ANSWER_END, 1)[0].strip()


def answered_with(question: str, text: str) -> str:
    """F192b1c: the message that answers `question` alone, `text` its words."""
    return f'{ANSWER}{question}{ANSWER_END}{text}'


def open_asks(rows, bare: bool = False) -> list[dict]:
    """F192b1c: each question the open message of transcript entries `rows` ends on (`ask`), in order, less the ones a
    person's message since named as answered (`answer_to`); a named answer that names none of them closes all, as any
    other message does. [] for none."""
    from agent_runner.control import message_text, person_turn
    from agent_runner.feed import queued_message
    named: list[str] = []
    kept: list = []
    for d in rows:
        if isinstance(d, dict) and not d.get('isSidechain'):
            q = queued_message(d) or d
            if q.get('type') == 'user' and person_turn(q) and (n := answer_to(message_text(q))) is not None:
                named.append(n)
                d = {**q, 'message': {**(q.get('message') or {}), 'content': f'{ABOUT}{n}{NOT}'}}  # `ask` reads it as no answer
        kept.append(d)
    first = ask(kept, bare)
    if not first:
        return []
    said = next((d for d in reversed(kept) if isinstance(d, dict) and d.get('type') == 'assistant' and d.get('uuid') == first['id']), None)
    every = asks_of(message_text(said), first['id'], bare) if said else []
    every = every if any(a['id'] == first['id'] for a in every) else [first]
    named = [re.sub(r'\s*\[[^\]]*\]$', '', n).strip() for n in named]  # its options' bracket too
    if any(n not in {a['question'].strip() for a in every} for n in named):
        return []
    return [a for a in every if a['question'].strip() not in named]
