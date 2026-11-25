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
