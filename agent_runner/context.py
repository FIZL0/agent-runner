"""`agent-runner context`: what every session loads before it starts, and where it could shrink.

Claude Code loads CLAUDE.md (and the files it `@`-imports) into every turn; the runner's prompt points the session at
`[run] rules`; other agents read AGENTS.md. Whatever is in them is paid for on every turn of every session, so they
hold the rules only, and reference material (code maps, how-tos, background) lives in `[plan] lookup` files, one
`## section` each, printed on demand by `plan "<section>"`.
"""
import re
import sys
from pathlib import Path

IMPORT = re.compile(r'(?:^|\s)@([\w./~-]+\.md)\b')


def core_files(root: Path, rules: str = '') -> list[Path]:
    """The always-read instruction files: [run] rules, CLAUDE.md, AGENTS.md, and what they @-import."""
    seen: list[Path] = []
    todo = [root / n for n in ([rules] if rules else []) + ['CLAUDE.md', 'AGENTS.md']]
    while todo:
        p = todo.pop(0)
        if not p.is_file() or p.resolve() in [s.resolve() for s in seen]:
            continue
        seen.append(p)
        text = p.read_text(encoding='utf-8', errors='replace')
        todo += [(p.parent / m).expanduser() for m in IMPORT.findall(text)]
    return seen


def sections(text: str) -> list[tuple[str, int]]:
    """(heading, bytes) for each `## ` section; text before the first one is '(top)'."""
    out, name, size = [], '(top)', 0
    for line in text.splitlines(keepends=True):
        if line.startswith('## '):
            out.append((name, size))
            name, size = line[3:].strip(), 0
        size += len(line.encode('utf-8'))
    out.append((name, size))
    return [s for s in out if s[1]]


def report(root: Path, rules: str, budget_kb: float) -> tuple[list[str], bool]:
    """The report's lines, and whether the files are over budget."""
    files = core_files(root, rules)
    total = sum(p.stat().st_size for p in files)
    over = total > budget_kb * 1024
    out = [f'every session loads {total / 1024:.1f} KB (~{total // 4000}k tokens a turn), budget {budget_kb:g} KB'
           f' ([plan] context_kb){": OVER" if over else ""}']
    for p in files:
        text = p.read_text(encoding='utf-8', errors='replace')
        out.append(f'  {p.relative_to(root) if p.is_relative_to(root) else p}  {len(text.encode()) / 1024:.1f} KB')
        for name, size in sorted(sections(text), key=lambda s: -s[1])[:5]:
            out.append(f'      {size / 1024:5.1f} KB  {name}')
    if over:
        out.append('Move reference material (code maps, how-tos, background) into a [plan] lookup file, one ## section '
                   'each, and leave a one-line pointer: `agent-runner plan "<section>"` prints it when needed.')
    return out, over


def warning(root: Path, rules: str, budget_kb: float) -> str:
    """One line for `run`'s start when the core files are over budget, else ''."""
    if not budget_kb:
        return ''
    total = sum(p.stat().st_size for p in core_files(root, rules))
    return (f'instruction files every session loads are {total / 1024:.0f} KB, over [plan] context_kb '
            f'({budget_kb:g}): `agent-runner context` shows what to move out') if total > budget_kb * 1024 else ''


def main(argv: list[str]) -> int:
    from agent_runner.config import cfg
    if argv not in ([], ['--check']):
        print('agent-runner context [--check]', file=sys.stderr)
        return 2
    c = cfg()
    out, over = report(c.root, c.run['rules'], c.raw['plan']['context_kb'] or 12)
    print('\n'.join(out))
    return 1 if over and argv == ['--check'] else 0
