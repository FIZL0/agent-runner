"""`agent-runner cost`: where a run's tokens go, by the kind of tool call that put them in context.

A tool result is paid for again on every later turn of its session (it stays in context), so what counts is
not its size but its size times the turns it stays: a 20 KB log read on turn 3 of a 60-turn session costs
far more than one read on turn 58. This sums that per kind of call: a Bash command by its program (and
subcommand or script: `git log`, `python3 tools/x.py`), the other tools by name.

    agent-runner cost                 the last 7 days of this repo's worker sessions (slots, merge fixes)
    agent-runner cost --days 1
    agent-runner cost FILE.jsonl …    any transcripts, Claude's or Pi's
    agent-runner cost --files         by file read (Read, cat/sed/grep targets) and exact-repeat commands

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


FILE_TOOLS = ('read', 'edit', 'write', 'multiedit')  # calls whose result is about one file (F25: by_file)


def call_kind(name: str, args: dict, by_file: bool = False) -> str:
    """`kind`, or with `by_file` a file tool's file name instead (`runner.py`), for what filled a context."""
    if by_file and name.lower() in FILE_TOOLS and isinstance(args, dict) and \
            (f := args.get('file_path') or args.get('path')):
        return os.path.basename(str(f).rstrip('/\\')) or str(f)
    return kind(name, args)


def session(path, by_file: bool = False, key=None) -> tuple[list[tuple[str, int, int]], int, int]:
    """(kind, chars, turn it arrived), the session's assistant turns, input tokens billed (cache reads too).
    With `by_file`, a Read (Edit, Write) counts under its file's name, not 'read'; with `key` (a function of
    the tool's name and arguments), whatever it returns instead of the kind (F26: `(name, args)`).
    Claude writes one line per content block of a turn (one message id); Pi one per message."""
    if key is None:
        key = lambda n, a: call_kind(n, a, by_file)  # noqa: E731
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
                tid = m.get('toolCallId')
                out.append((calls[tid] if tid in calls else key((m.get('toolName') or 'unknown').lower(), {}),
                            _text(m.get('content')), turns))
                continue
            content = m.get('content')
            for b in content if isinstance(content, list) else []:
                if not isinstance(b, dict):
                    continue
                if b.get('type') in ('tool_use', 'toolCall'):
                    calls[b.get('id')] = key(b.get('name', ''), b.get('input') or b.get('arguments') or {})
                elif b.get('type') == 'tool_result':
                    tid = b.get('tool_use_id')
                    out.append((calls[tid] if tid in calls else key('unknown', {}), _text(b.get('content')),
                                turns))
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


def filled(path, top: int = 3) -> list[tuple[str, int]]:
    """F25: what put the most into one session's context, largest first: (a file's name or a kind of call,
    k tokens of results), at most `top`, each at least 1k. A file read twice counts twice (both copies stay
    in context); compaction is ignored."""
    sums = Counter()
    try:
        got, _, _ = session(path, by_file=True)
    except OSError:
        return []
    for k, c, _ in got:
        sums[k] += c
    return [(k, c // 4000) for k, c in sums.most_common(top) if c >= 4000]


READERS = {'cat', 'head', 'tail', 'sed', 'grep', 'rg', 'nl', 'less', 'more', 'awk'}  # programs that print files
PATTERN_FIRST = {'sed', 'grep', 'rg', 'awk'}  # their first operand is a script or pattern, not a file
OPT_VALUE = {'head': {'-n', '-c'}, 'tail': {'-n', '-c'}, 'sed': {'-e', '-f'}, 'awk': {'-f', '-v', '-F'},
             'grep': {'-e', '-f', '-m', '-A', '-B', '-C'},
             'rg': {'-e', '-f', '-m', '-A', '-B', '-C', '-g', '--glob', '-t', '-T'}}  # options that take a value


def _bash_reads(command: str) -> list[str]:
    """The files a Bash line prints with cat, head, tail, sed, grep, rg, … (their operands, not patterns)."""
    import shlex
    out = []
    for line in command.replace('\\\n', ' ').splitlines():
        lex = shlex.shlex(line, posix=True, punctuation_chars=True)
        try:
            tokens = list(lex)  # quoted text stays one word: grep "a|b" f.py is one command
        except ValueError:
            tokens = line.split()
        parts, cur = [], []
        for w in tokens:
            if w and set(w) <= set('|&;()'):
                parts.append(cur)
                cur = []
            else:
                cur.append(w)
        parts.append(cur)
        for words in parts:
            while words and (re.fullmatch(r'\w+=.*', words[0]) or words[0] in ('env', 'nice', 'exec', 'time',
                                                                                  'timeout', 'command')):
                words = words[2:] if words[0] == 'timeout' else words[1:]
            if not words or os.path.basename(words[0]) not in READERS:
                continue
            out += _operands(os.path.basename(words[0]), words[1:])
    return out


def _operands(prog: str, words: list[str]) -> list[str]:
    """The files among one reader command's words: not its options, pattern, redirects or directories."""
    ops, skip, script, recursive = [], False, False, prog == 'rg'
    for w in words:
        if skip:
            skip = False
            continue
        if w[:1] in '<>':
            break  # a redirect: what follows is not read
        if w.startswith('-') and w != '-':
            if prog == 'sed' and (w == '-i' or w.startswith(('-i', '--in-place'))):
                return []  # sed -i edits, it does not print
            recursive = recursive or (prog == 'grep' and (w in ('-r', '-R', '--recursive') or
                                                          (w[1:2] != '-' and set('rR') & set(w))))
            script = script or (prog in PATTERN_FIRST and w in ('-e', '-f'))  # the pattern came as an option
            skip = w in OPT_VALUE.get(prog, ())
            continue
        ops.append(w)
    if prog in PATTERN_FIRST and not script:
        ops = ops[1:]
    ops = [w for w in ops if w not in ('-', '.', '..') and not w.endswith('/')
           and not re.fullmatch(r'[\d,+\-]+[pd]?', w)]
    if recursive:  # a recursive search names directories: keep what looks like a file
        ops = [w for w in ops if '.' in os.path.basename(w) or '*' in w]
    return ops


def reads(name: str, args: dict) -> list[str]:
    """F26: the files a call read, by name (`runner.py`): a Read's file, or a Bash line's cat/sed/grep/… targets."""
    if not isinstance(args, dict):
        return []
    n = name.lower()
    if n == 'read':
        paths = [args.get('file_path') or args.get('path')]
    elif n in ('bash', 'powershell'):
        paths = _bash_reads(str(args.get('command', '')))
    else:
        return []
    return [os.path.basename(str(p).rstrip('/\\')) or str(p) for p in paths if p]


def files_report(paths, top: int = 20) -> list[str]:
    """F26 `cost --files`: tokens in context (result size × turns kept) per file read, and what exact-repeat
    commands (the same Bash line run again in one session) added, so the report names what to split or stop
    re-reading. A Bash line that read several files shares its result among them evenly."""
    calls, rereads, chars, kept = Counter(), Counter(), Counter(), Counter()
    runs, rep_chars, rep_kept = Counter(), Counter(), Counter()
    n = turns = 0
    all_kept = 0
    for p in paths:
        try:
            got, t, _ = session(p, key=lambda nm, a: (nm, a))
        except OSError:
            continue
        n, turns = n + 1, turns + t
        seen_files, seen_cmds = set(), set()
        for (nm, a), c, at in got:
            k = c * max(t - at, 1)
            all_kept += k
            fs = reads(nm, a)
            for f in fs:
                calls[f] += 1
                rereads[f] += f in seen_files
                seen_files.add(f)
                chars[f] += c / len(fs)
                kept[f] += k / len(fs)
            if nm.lower() in ('bash', 'powershell') and isinstance(a, dict) and (cmd := str(a.get('command', '')).strip()):
                runs[cmd] += 1
                if cmd in seen_cmds:
                    rep_chars[cmd] += c
                    rep_kept[cmd] += k
                seen_cmds.add(cmd)
    if not n:
        return ['no transcripts']
    total, every = sum(kept.values()), all_kept or 1
    out = [f'{n} sessions, {turns} turns; file reads ~{int(total) // 4:,} tokens in context, '
           f'{100 * total / every:.0f}% of all tool results',
           f'  {"file":32} {"reads":>6} {"re-reads":>8} {"result tok":>11} {"in context":>13}  share',
           *(f'  {f[:32]:32} {calls[f]:6} {rereads[f]:8} {int(chars[f]) // 4:11,} {int(v) // 4:13,}  '
             f'{100 * v / (total or 1):4.1f}%' for f, v in kept.most_common(top))]
    rep = sum(rep_kept.values())
    out += ['', f'exact-repeat commands: ~{rep // 4:,} tokens in context from runs after the first, '
                f'{100 * rep / every:.0f}% of all tool results']
    if rep_kept:
        out.append(f'  {"command":48} {"runs":>5} {"repeat tok":>11} {"in context":>13}')
        out += [f'  {" ".join(c.split())[:48]:48} {runs[c]:5} {rep_chars[c] // 4:11,} {v // 4:13,}'
                for c, v in rep_kept.most_common(top)]
    return out


# --- a task's spend (F103: [run] task_tokens / task_usd) -------------------------------------------------------
#
# What one task's session has used so far, read from its transcript as it grows: tokens are those the model
# newly read or wrote (input, cache writes, output); cache reads are left out, as they grow with turns times the
# context and cost a tenth of the input price. Dollars count them all at the API's list prices per million
# tokens (a plan bills none, but the figure says how much of it a task took). A model it does not know is
# priced as Opus.

PRICES = {'opus': (5.0, 25.0), 'sonnet': (3.0, 15.0), 'haiku': (1.0, 5.0)}  # $ per M tokens: input, output
CACHE_WRITE, CACHE_READ = 1.25, 0.1  # times the input price


def price(model: str) -> tuple[float, float]:
    m = (model or '').lower()
    return next((v for k, v in PRICES.items() if k in m), PRICES['opus'])


def turn_spend(u: dict, model: str) -> tuple[int, float]:
    """(tokens, dollars) of one model call's usage, Claude's keys or Pi's (Pi's own cost when it gives one); the
    tokens leave cache reads out, the dollars do not."""
    get = lambda *ks: sum(int(u.get(k) or 0) for k in ks)  # noqa: E731
    fresh, read = get('input_tokens', 'input'), get('cache_read_input_tokens', 'cacheRead')
    write, out = get('cache_creation_input_tokens', 'cacheWrite'), get('output_tokens', 'output')
    pin, pout = price(model)
    usd = (fresh * pin + write * pin * CACHE_WRITE + read * pin * CACHE_READ + out * pout) / 1e6
    if isinstance(u.get('cost'), dict) and isinstance(u['cost'].get('total'), (int, float)):
        usd = float(u['cost']['total'])
    return fresh + write + out, usd


class Spend:
    """A task's spend so far, over its transcripts (the session's own and its subagents'), read on from where
    the last look stopped, so a check every few seconds costs only the new lines. Claude writes one line per
    content block of a turn, each with the turn's usage: a message id counts once, at its last line's usage."""

    def __init__(self):
        self.at: dict[str, int] = {}  # transcript -> bytes read
        self.turns: dict[str, tuple[int, float]] = {}  # message id -> (tokens, dollars)
        self.n = 0

    def add(self, path) -> None:
        path = str(path)
        try:
            with open(path, 'rb') as f:
                f.seek(self.at.get(path, 0))
                for raw in f:
                    if not raw.endswith(b'\n'):  # the line being written: read it whole next time
                        break
                    self.at[path] = self.at.get(path, 0) + len(raw)
                    try:
                        e = json.loads(raw)
                    except ValueError:
                        continue
                    m = e.get('message') if isinstance(e, dict) and isinstance(e.get('message'), dict) else {}
                    if (m.get('role') or e.get('type')) != 'assistant' or not isinstance(m.get('usage'), dict):
                        continue
                    if not (mid := m.get('id') or e.get('id')):
                        self.n += 1
                        mid = f'#{self.n}'
                    self.turns[f'{path}:{mid}'] = turn_spend(m['usage'], m.get('model') or '')
        except OSError:
            pass

    def total(self) -> tuple[int, float]:
        return sum(t for t, _ in self.turns.values()), sum(d for _, d in self.turns.values())


def session_files(path) -> list[Path]:
    """A session's transcript and its subagents' (Claude keeps those in `<session id>/subagents/`)."""
    p = Path(path)
    return [p, *sorted(p.with_suffix('').glob('subagents/*.jsonl'))]


def spend_text(tokens: int, usd: float) -> str:
    """'1.2M tok $3.40', for status and the run log."""
    tok = f'{tokens / 1e6:.1f}M' if tokens >= 1e6 else f'{tokens / 1e3:.0f}k'
    return f'{tok} tok ${usd:.2f}'


def over_budget(tokens: int, usd: float, max_tokens, max_usd) -> str:
    """Why a task's spend is past `[run] task_tokens` / `task_usd` (0 or empty: no cap), else ''."""
    if max_tokens and tokens >= int(max_tokens):
        return f'{spend_text(tokens, usd)} is past [run] task_tokens ({int(max_tokens):,})'
    if max_usd and usd >= float(max_usd):
        return f'{spend_text(tokens, usd)} is past [run] task_usd (${float(max_usd):.2f})'
    return ''


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
    ap.add_argument('--files', dest='by_file', action='store_true',
                    help='by file read (Read, cat/sed/grep targets) and exact-repeat commands instead')
    a = ap.parse_args(argv)
    paths = a.files or worker_transcripts(a.days)
    print('\n'.join(files_report(paths) if a.by_file else report(paths)))
    return 0
