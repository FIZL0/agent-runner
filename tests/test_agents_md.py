#!/usr/bin/env python3
"""D8: AGENTS.md is short, every path in it exists, and `[run] rules` points at it so `context` prints it.

    python3 tests/test_agents_md.py        (no network)
"""
from __future__ import annotations

import re
import sys
import tomllib

from _check import ROOT, check, eq, report

from agent_runner import context as X  # noqa: E402

TEXT = (ROOT / 'AGENTS.md').read_text(encoding='utf-8')


def t_size() -> None:
    check(len(TEXT.encode()) <= 3 * 1024, 'D8: AGENTS.md is 3 KB at most', f'{len(TEXT.encode())} bytes')


def t_paths() -> None:
    missing = []
    for tok in re.findall(r'`([^`\s]+)`', TEXT):
        if '/' not in tok and not tok.endswith(('.md', '.py', '.html')):
            continue
        if tok.startswith(('./', '--')) or '<' in tok or ' ' in tok:
            continue
        if re.search(r'[A-Za-z0-9_.]+(/|\.\w+$)', tok) and not tok.startswith('python3'):
            names = [n.strip() for n in tok.split(',')]
            for n in names:
                n = n.rstrip(':')
                if n.startswith('NNN-') or '*' in n:
                    continue
                cands = [ROOT / n, ROOT / 'agent_runner' / n, ROOT / 'tests' / n]
                if not any(c.exists() for c in cands):
                    missing.append(n)
    # `foo*.py` names: at least one file matches
    for g in re.findall(r'`([\w/]+\*[\w.]*)`', TEXT):
        if not list((ROOT / 'agent_runner').glob(g)) and not list(ROOT.glob(g)):
            missing.append(g)
    eq(missing, [], 'D8: every path AGENTS.md names exists')


def t_context() -> None:
    rules = tomllib.loads((ROOT / 'runner.toml').read_text(encoding='utf-8'))['run']['rules']
    eq(rules, 'AGENTS.md', 'D8: [run] rules points at AGENTS.md')
    out, _ = X.report(ROOT, rules, 12)
    check(any('AGENTS.md' in line for line in out), 'D8: `context` prints AGENTS.md', '\n'.join(out))


if __name__ == '__main__':
    sys.exit(report([t_size, t_paths, t_context]))
