"""`agent-runner cost`: where a run's tokens go, by the kind of tool call that put them in context.

A tool result is paid for again on every later turn of its session (it stays in context), so what counts is
not its size but its size times the turns it stays: a 20 KB log read on turn 3 of a 60-turn session costs
far more than one read on turn 58. This sums that per kind of call: a Bash command by its program (and
subcommand or script: `git log`, `python3 tools/x.py`), the other tools by name.

    agent-runner cost                 the last 7 days of this repo's worker sessions (slots, merge fixes)
    agent-runner cost --days 1
    agent-runner cost FILE.jsonl …    any transcripts, Claude's or Pi's

Tokens are estimated as characters / 4; context compaction is ignored, so long sessions read high.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from collections import Counter
from pathlib import Path

SUB = {'git', 'gh', 'npm', 'npx', 'pnpm', 'cargo', 'make', 'just', 'go', 'uv', 'docker', 'agent-runner', 'run',
       'python', 'python3', 'node', 'bash', 'sh'}  # programs whose next word says what was done
WRAP = re.compile(r'^(?:cd \S+ *(?:&&|;) *|\w+=\S* +|timeout +\S+ +|time +|env +|nice +|exec +)+')


SETUP = {'cd', 'mkdir', 'export', 'source', '.', 'set', 'pushd', 'true'}  # steps before the real command


def kind(name: str, args: dict) -> str:
    """'git log', 'python3 tools/check.py', 'python3 (inline)', 'read', …: what a call's result counts under.
    For a Bash line, its first command that is not set-up (cd, mkdir, export, …)."""
    name = name.lower()
    if name not in ('bash', 'powershell') or not isinstance(args, dict):
        return name or 'unknown'
    for part in re.split(r'\s*(?:\|\|?|&&|;|\n)\s*', str(args.get('command', '')).strip()):
        words = WRAP.sub('', part).split()
        if words and os.path.basename(words[0]) not in SETUP:
            break
    else:
        return 'bash'
    prog = os.path.basename(words[0])
    if prog in SUB and len(words) > 1:
        nxt = words[1]
        if nxt in ('-c', '-') or nxt.startswith('<<'):
            return f'{prog} (inline)'
        if nxt == '-m' and len(words) > 2:
            return f'{prog} -m {words[2]}'
        rest = [w for w in words[1:] if not w.startswith('-')]
        return f'{prog} {rest[0]}' if rest else prog
    return prog


def _text(content) -> int:
    if isinstance(content, str):
        return len(content)
    return sum(len(b.get('text', '') or '') for b in content or [] if isinstance(b, dict))


def session(path) -> tuple[list[tuple[str, int, int]], int, int]:
    """(kind, chars, turn it arrived), the session's assistant turns, input tokens billed (cache reads too).
    Claude writes one line per content block of a turn (one message id); Pi one per message."""
    calls: dict[str, str] = {}
    out, turns, billed, last = [], 0, 0, None
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get('type') not in ('user', 'assistant', 'message'):  # not request snapshots, which repeat
                continue
            m = e.get('message') if isinstance(e.get('message'), dict) else {}
            role = m.get('role') or e.get('type')
            if role == 'assistant':
                mid = m.get('id') or id(m)
                if mid != last:
                    turns, last = turns + 1, mid
                    u = m.get('usage') or {}
                    billed += sum(u.get(k, 0) or 0 for k in ('input_tokens', 'cache_read_input_tokens',
                                                             'cache_creation_input_tokens', 'input', 'cacheRead',
                                                             'cacheWrite'))
            if role == 'toolResult':  # Pi: the result is a message of its own
                out.append((calls.get(m.get('toolCallId'), (m.get('toolName') or 'unknown').lower()),
                            _text(m.get('content')), turns))
                continue
            content = m.get('content')
            for b in content if isinstance(content, list) else []:
                if not isinstance(b, dict):
                    continue
                if b.get('type') in ('tool_use', 'toolCall'):
                    calls[b.get('id')] = kind(b.get('name', ''), b.get('input') or b.get('arguments') or {})
                elif b.get('type') == 'tool_result':
                    out.append((calls.get(b.get('tool_use_id'), 'unknown'), _text(b.get('content')), turns))
    return out, turns, billed


def report(paths) -> list[str]:
    calls, chars, kept = Counter(), Counter(), Counter()
    turns = billed = n = 0
    for p in paths:
        try:
            got, t, b = session(p)
        except OSError:
            continue
        n, turns, billed = n + 1, turns + t, billed + b
        for k, c, at in got:
            calls[k] += 1
            chars[k] += c
            kept[k] += c * max(t - at, 1)  # read on its own turn, then on every later one
    if not n:
        return ['no transcripts']
    total = sum(kept.values()) or 1
    out = [f'{n} sessions, {turns} turns, {sum(calls.values())} tool calls; ~{billed:,} input tokens billed',
           f'  {"kind":32} {"calls":>6} {"result tok":>11} {"in context":>13}  share',
           *(f'  {k[:32]:32} {calls[k]:6} {chars[k] // 4:11,} {v // 4:13,}  {100 * v / total:4.1f}%'
             for k, v in kept.most_common())]
    return out


def worker_transcripts(days: float) -> list[Path]:
    """This repo's worker sessions: Claude's for each slot and merge worktree, and the run's Pi sessions."""
    from agent_runner import runner as R
    R.init()
    dirs = [Path(os.path.expanduser('~/.claude/projects')) / R.project_slug(d)
            for d in R.SLOTS_DIR.glob('*') if d.is_dir()]
    dirs.append(R.C.notes('pi-sessions'))
    since = time.time() - days * 86400
    return sorted(p for d in dirs if d.is_dir() for p in d.glob('*.jsonl') if p.stat().st_mtime >= since)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog='agent-runner cost', description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('files', nargs='*', help='transcripts (.jsonl); default: this repo\'s worker sessions')
    ap.add_argument('--days', type=float, default=7, help='how far back the default looks (default 7)')
    a = ap.parse_args(argv)
    print('\n'.join(report(a.files or worker_transcripts(a.days))))
    return 0
