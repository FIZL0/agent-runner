"""F192a: the question a chat waits on, for the question card: the DECIDE line with options that its last answer ends on,
or, talked about since (F430), an earlier one.

Read from the session's transcript, as the run reads it to file the question under Needs you (`control.control_state`,
`plan.decide_question`), so the card and Needs you ask the same words."""

from __future__ import annotations

import hashlib
import re

from agent_runner import need_detail
from agent_runner.plan import cut_question, decide_question


def ask_of(text: str, uuid: str = '') -> dict | None:
    """The question Claude's message `text` ends on: {'id' (its transcript entry's `uuid`, else one made of its
    words, as cut before B840: one filed then keeps its id), 'question', 'options': [{'name', 'rec'}], the recommended first}.
    None when it ends on no DECIDE line, or on one with no options (a malformed bracket is part of the question, as in Needs you)."""
    q = decide_question(text)
    options, question = need_detail.decide_options('', q, f'DECIDE: {q}') if q else ([], '')
    if not options:
        return None
    question = re.sub(r'(?:\s+https?://\S+)+\s*$', '', question)  # the links after the bracket
    return {'id': uuid or hashlib.sha256(cut_question(q).encode('utf-8')).hexdigest()[:16], 'question': question, 'options': options}


def decide_questions(text: str) -> list[str]:
    """F192b1: the questions Claude's message `text` ends on, in order: its trailing run of `DECIDE:` lines, blank
    lines between allowed; each as `plan.decide_question` reads one. [] when its last non-empty line is none."""
    from agent_runner.plan import DECIDE_LINE
    out: list[str] = []
    for line in reversed(text.strip().splitlines() if text.strip() else []):
        if not line.strip():
            continue
        if not DECIDE_LINE.match(line):
            break
        out.append(decide_question(line))
    return [q for q in reversed(out) if q]


def asks_of(text: str, uuid: str = '') -> list[dict]:
    """F192b1: each question `text` ends on (`decide_questions`), as `ask_of` says one, a question with no options
    too (its 'options' []). The first has `ask_of`'s id; each other one its uuid and place (`<uuid>-2`), else one
    made of its own words."""
    out = []
    for i, q in enumerate(decide_questions(text)):
        options, question = need_detail.decide_options('', q, f'DECIDE: {q}')
        question = re.sub(r'(?:\s+https?://\S+)+\s*$', '', question) if options else q
        own = hashlib.sha256(cut_question(q).encode('utf-8')).hexdigest()[:16]
        out.append({'id': (uuid and (f'{uuid}-{i + 1}' if i else uuid)) or own, 'question': question, 'options': options})
    return out


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


def joined(asks: list[dict] | dict | None, sid: str) -> dict:
    """F192a3: what /live says of `asks` (`asks` of session `sid`; one `ask` as before): 'asks', those still open in
    order, each with 'need', the item it is under Needs you ('' for none yet), and left out once that was answered
    there; 'ask', the first of them with options (None for none), as before; 'answered', the ids of the session's
    questions that were."""
    ids = needs(sid)
    if isinstance(asks, dict):
        asks = [asks]
    left = [{**a, 'need': ids.get(a['id'], '')} for a in asks or () if ids.get(a['id'], 1)]
    first = next((a for a in left if a['options']), None)
    if first and first['id'] not in ids:
        first = {k: v for k, v in first.items() if k != 'need'}
    return {'ask': first, 'asks': left, 'answered': [i for i, tid in ids.items() if not tid]}


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


def ask(rows) -> dict | None:
    """The first question with options of `asks(rows)`; None for none."""
    return next((a for a in asks(rows) if a['options']), None)


def asks(rows) -> list[dict]:
    """F192b1: the questions (`asks_of`) transcript entries `rows` leave open. The question transcript entries `rows` leave open; None when the person has spoken since, or Claude's turn goes on
    after it (a tool call). F430: messages about it (`is_about`) and Claude's replies to them leave it open, until a reply
    ends on another DECIDE line."""
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
    out = _ends_on(parts[0])[1]
    for part in parts[1:]:
        decides, new = _ends_on(part)
        out = new if decides else out
    return out


def _ends_on(rows: list[dict]) -> tuple[bool, list[dict]]:
    """Whether the last answer in `rows` ends on a DECIDE line, and its `asks_of`."""
    from agent_runner.control import control_state, message_text
    st = control_state(rows)
    if st['last'] != 'claude':
        return False, []
    said = next((d for d in reversed(rows) if d.get('type') == 'assistant' and message_text(d).strip()), {})
    items = (said.get('message') or {}).get('content')
    if any(isinstance(x, dict) and x.get('type') == 'tool_use' for x in (items if isinstance(items, list) else ())):
        return False, []  # a call in the same entry; one after it is `control_state`'s to see
    return bool(decide_question(st['text'])), asks_of(st['text'], str(said.get('uuid') or ''))
