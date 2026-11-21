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


def test_filled():
    print('cost: what filled one session, by file (F25)')
    with tempfile.TemporaryDirectory() as t:
        f = write(Path(t) / 'c.jsonl', [
            *claude_turn('m1', {'type': 'tool_use', 'id': 'a', 'name': 'Read', 'input': {'file_path': '/w/a/runner.py'}}),
            result('a', 'x' * 12000),
            *claude_turn('m2', {'type': 'tool_use', 'id': 'b', 'name': 'Read', 'input': {'file_path': '/w/a/runner.py'}}),
            result('b', 'x' * 8000),
            *claude_turn('m3', {'type': 'tool_use', 'id': 'c', 'name': 'Bash', 'input': {'command': 'git diff'}}),
            result('c', 'x' * 9000),
            *claude_turn('m4', {'type': 'tool_use', 'id': 'd', 'name': 'Read', 'input': {'file_path': 'small.py'}}),
            result('d', 'x' * 400),
        ])
        eq(cost.filled(f), [('runner.py', 5), ('git diff', 2)], 'a file read twice counts twice; under 1k is left out')
        eq(cost.session(f)[0][0][0], 'read', 'without by_file a Read is still "read"')
        eq(cost.filled(Path(t) / 'none.jsonl'), [], 'no transcript: nothing')


def test_reads():
    print('cost: the files a call read (F26)')
    b = lambda c: cost.reads('Bash', {'command': c})
    eq(cost.reads('Read', {'file_path': '/w/s1/agent_runner/runner.py'}), ['runner.py'], 'a Read by file name')
    eq(b('sed -n 1,80p agent_runner/runner.py'), ['runner.py'], "sed's script is not a file")
    eq(b('grep -n "def main" a.py b.py | head -5'), ['a.py', 'b.py'], "grep's pattern is not a file, nor head's 5")
    eq(b('cd /w && tail -n 40 .runner/run.log'), ['run.log'], "tail's -n takes a value")
    eq(b('cat a.py > b.py'), ['a.py'], 'a redirect target is not read')
    eq(b('git diff'), [], 'other programs read no file')
    eq(b('grep -n x \\\n  a.py'), ['a.py'], 'a continued line')
    eq(b('grep -n "a|b; c" f.py 2>/dev/null'), ['f.py'], 'a quoted | or ; is part of the pattern')
    eq(b("sed -i 's/a/b/' a.py"), [], 'sed -i edits, it does not read')
    eq(b('grep -rn x agent_runner/ tests run.py'), ['run.py'], 'a recursive search: directories are not files')
    eq(b('timeout 60 cat a.log && rg x agent_runner'), ['a.log'], 'timeout in front; rg on a directory')
    eq(cost.reads('Edit', {'file_path': 'a.py'}), [], 'an Edit is not a read')


def test_files_report():
    print('cost --files: tokens per file read, and from exact-repeat commands (F26)')
    with tempfile.TemporaryDirectory() as t:
        f = write(Path(t) / 'c.jsonl', [
            *claude_turn('m1', {'type': 'tool_use', 'id': 'a', 'name': 'Read', 'input': {'file_path': '/w/runner.py'}}),
            result('a', 'x' * 4000),  # 1000 tokens, kept 4 turns
            *claude_turn('m2', {'type': 'tool_use', 'id': 'b', 'name': 'Bash',
                                'input': {'command': 'git log -3'}}),
            result('b', 'x' * 400),  # 100 tokens, kept 3 turns
            *claude_turn('m3', {'type': 'tool_use', 'id': 'c', 'name': 'Bash',
                                'input': {'command': 'sed -n 1,80p agent_runner/runner.py'}}),
            result('c', 'x' * 800),  # 200 tokens, kept 2 turns
            *claude_turn('m4', {'type': 'tool_use', 'id': 'd', 'name': 'Bash',
                                'input': {'command': 'git log -3'}}),
            result('d', 'x' * 400),  # 100 tokens, kept 1 turn
            *claude_turn('m5', {'type': 'text', 'text': 'done'}),
        ])
        out = '\n'.join(cost.files_report([f]))
        has(out, r'^1 sessions, 5 turns; file reads ~4,400 tokens in context, 92% of all tool results', 'the header')
        has(out, r'^  runner\.py +2 +1 +1,200 +4,400  100\.0%', 'two reads of one file: 1000×4 + 200×2, one a re-read')
        has(out, r'exact-repeat commands: ~100 tokens in context from runs after the first, 2% ', 'repeats')
        has(out, r'^  git log -3 +2 +100 +100$', 'the repeated command, by its second run only')
        eq(cost.files_report([Path(t) / 'none.jsonl']), ['no transcripts'], 'no transcript: nothing')


def main() -> int:
    return report([test_kinds, test_sessions, test_filled, test_reads, test_files_report])


if __name__ == '__main__':
    sys.exit(main())
