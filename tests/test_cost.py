#!/usr/bin/env python3
"""`agent-runner cost`: what a call costs is its result's size times the turns it stays in context.

    python3 tests/test_cost.py          (no network, no agent)
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from _check import eq, has, report

from agent_runner import cost  # noqa: E402


def write(path: Path, entries: list[dict]) -> Path:
    path.write_text(''.join(json.dumps(e) + '\n' for e in entries), encoding='utf-8')
    return path


def claude_turn(mid: str, *blocks) -> list[dict]:
    """Claude writes one line per content block of a turn, every line with the turn's message id."""
    return [{'type': 'assistant', 'message': {'id': mid, 'role': 'assistant', 'content': [b],
                                              'usage': {'input_tokens': 10}}} for b in blocks]


def result(tid: str, text: str) -> dict:
    return {'type': 'user', 'message': {'role': 'user', 'content': [
        {'type': 'tool_result', 'tool_use_id': tid, 'content': [{'type': 'text', 'text': text}]}]}}


def test_kinds():
    print('cost: what a call is counted under')
    k = lambda c: cost.kind('Bash', {'command': c})
    eq(k('cd /x && git log -3 -- a.py'), 'git log', 'a cd in front is not the command')
    eq(k('mkdir -p out && python3 tools/check.py --all | tail'), 'python3 tools/check.py', 'nor a mkdir')
    eq(k("timeout 60 FOO=1 python3 - <<'EOF'\nprint(1)\nEOF"), 'python3 (inline)', 'inline python')
    eq(k('python3 -m pytest -q'), 'python3 -m pytest', 'a module')
    eq(k('sed -n 1,80p a.py'), 'sed', 'a plain program')
    eq(cost.kind('Read', {'file_path': 'a.py'}), 'read', 'other tools by name')
    eq(cost.kind('bash', {'command': 'grep -rn x .'}), 'grep', "Pi's lower-case bash")


def test_sessions():
    print('cost: size × turns in context, Claude and Pi')
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        big = 'x' * 4000  # ~1000 tokens
        claude = write(tmp / 'c.jsonl', [
            *claude_turn('m1', {'type': 'text', 'text': 'look'},
                         {'type': 'tool_use', 'id': 'a', 'name': 'Bash', 'input': {'command': 'cat big.log'}}),
            result('a', big),
            {'type': 'api-request-blob', 'message': {'role': 'user', 'content': [  # a snapshot: never counted
                {'type': 'tool_result', 'tool_use_id': 'a', 'content': big}]}},
            *claude_turn('m2', {'type': 'tool_use', 'id': 'b', 'name': 'Read', 'input': {}}),
            result('b', 'y' * 400),
            *claude_turn('m3', {'type': 'text', 'text': 'done'}),
        ])
        got, turns, billed = cost.session(claude)
        eq(turns, 3, 'turns are message ids, not lines')
        eq(billed, 30, 'billed input counted once per turn')
        eq(got, [('cat', 4000, 1), ('read', 400, 2)], 'each result once, with the turn it arrived on')
        pi = write(tmp / 'p.jsonl', [
            {'type': 'message', 'message': {'role': 'assistant', 'content': [
                {'type': 'toolCall', 'id': 'p1', 'name': 'bash', 'arguments': {'command': 'git diff'}}],
                'usage': {'input': 5, 'cacheRead': 7}}},
            {'type': 'message', 'message': {'role': 'toolResult', 'toolCallId': 'p1', 'toolName': 'bash',
                                            'content': [{'type': 'text', 'text': 'z' * 800}]}},
            {'type': 'message', 'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': 'ok'}]}},
        ])
        eq(cost.session(pi), ([('git diff', 800, 1)], 2, 12), "Pi's toolCall / toolResult")
        out = '\n'.join(cost.report([claude, pi]))
        has(out, r'^2 sessions, 5 turns, 3 tool calls; ~42 input tokens billed', 'the header')
        has(out, r'cat +1 +1,000 +2,000 ', 'cat: 1000 tokens, in context for 2 turns')
        has(out, r'^  cat.*\n  git diff.*\n  read', 'sorted by what stayed in context')


def main() -> int:
    return report([test_kinds, test_sessions])


if __name__ == '__main__':
    sys.exit(main())
