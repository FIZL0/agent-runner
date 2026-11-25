"""F192a: the question a chat waits on, for the question card: the DECIDE line with options that its last answer ends on.

Read from the session's transcript, as the run reads it to file the question under Needs you (`control.control_state`,
`plan.decide_question`), so the card and Needs you ask the same words."""

from __future__ import annotations

import hashlib
import re

from agent_runner import need_detail
from agent_runner.plan import decide_question


def ask_of(text: str, uuid: str = '') -> dict | None:
    """The question Claude's message `text` ends on: {'id' (its transcript entry's `uuid`, else one made of its
    words), 'question', 'options': [{'name', 'rec'}], the recommended first}. None when it ends on no DECIDE line, or
    on one with no options (a malformed bracket is part of the question, as in Needs you)."""
    q = decide_question(text)
    options, question = need_detail.decide_options('', q, f'DECIDE: {q}') if q else ([], '')
    if not options:
        return None
    question = re.sub(r'(?:\s+https?://\S+)+\s*$', '', question)  # the links after the bracket
    return {'id': uuid or hashlib.sha256(q.encode('utf-8')).hexdigest()[:16], 'question': question, 'options': options}


def needs(sid: str) -> dict[str, str]:
    """F192a3: {question id: the item that still asks it under Needs you (shelved too), '' once it does not} of the
    questions of session `sid` the run filed there. An item that asks something else by now is not that question's.
    With a plan that does not read, every item waits: `ui_model.question_answer` looks again."""
    from agent_runner import control_settled, plan as P, state
    if not (filed := control_settled.filed_questions(state.C, sid)):
        return {}
    try:
        waits = {a[1]: a[3] for a in P.asks(state.C.todo, all=True) if a[0] == 'DECIDE'}
    except (SystemExit, OSError):
        waits = {t: q['what'] for t, q in filed.items()}
    out: dict[str, str] = {}
    for tid, q in filed.items():
        out[q['id']] = out.get(q['id']) or (tid if waits.get(tid) == q['what'] else '')
    return out


def joined(ask: dict | None, sid: str) -> dict:
    """F192a3: what /live says of `ask` (`ask` of session `sid`): 'ask' with 'need', the item it is under Needs you, and
    None once that was answered there; 'answered', the ids of the session's questions that were."""
    ids = needs(sid)
    if ask and ask['id'] in ids:
        ask = {**ask, 'need': ids[ask['id']]} if ids[ask['id']] else None
    return {'ask': ask, 'answered': [i for i, tid in ids.items() if not tid]}


def ask(rows) -> dict | None:
    """`ask_of` the last answer in transcript entries `rows`; None when the person has spoken since, or Claude's turn
    goes on after it (a tool call)."""
    from agent_runner.control import control_state, message_text
    rows = [d for d in rows if isinstance(d, dict) and not d.get('isSidechain')]
    st = control_state(rows)
    if st['last'] != 'claude':
        return None
    said = next((d for d in reversed(rows) if d.get('type') == 'assistant' and message_text(d).strip()), {})
    items = (said.get('message') or {}).get('content')
    if any(isinstance(x, dict) and x.get('type') == 'tool_use' for x in (items if isinstance(items, list) else ())):
        return None  # a call in the same entry; one after it is `control_state`'s to see
    return ask_of(st['text'], str(said.get('uuid') or ''))
