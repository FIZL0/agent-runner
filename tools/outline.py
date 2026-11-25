#!/usr/bin/env python3
"""The outline of one file (`[plan] outline`): `outline.py FILE` prints its parts, one a line, with line numbers.

Python: classes, functions, methods and `# --- section ---` comments. JavaScript (.js, .mjs): classes with their
methods, top-level functions (declared, or a name set to one) and `// --- section ---` comments. Markdown:
headings. Any other kind prints nothing. JavaScript is read line by line, not parsed: a line of a template
literal that looks like a top-level declaration is listed too.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

PY_SECTION = re.compile(r'\s*#\s*(?:-{3,}|={3,}|─{3,})\s*(.*?\w.*?)[\s─=-]*$')
JS_SECTION = re.compile(r'\s*(?://|/\*)\s*(?:-{3,}|={3,}|─{3,})\s*(.*?\w.*?)[\s─=-]*(?:\*/)?\s*$')
JS_EXPORT = r'(?:export\s+)?(?:default\s+)?'
JS_CLASS = re.compile(JS_EXPORT + r'class\b(?:\s+(?!extends\b)([\w$]+))?')
JS_FUNCTION = re.compile(JS_EXPORT + r'(?:async\s+)?function\b\s*\*?\s*([\w$]+)?')
JS_NAMED = re.compile(r'(?:export\s+)?(?:(?:const|let|var)\s+)?([\w$.]+)\s*=\s*(?:async\b\s*)?'
                      r'(?:function\b|\([^()]*(?:\([^()]*\)[^()]*)*\)\s*=>|[\w$]+\s*=>)')
JS_METHOD = re.compile(r'(\s+)(?:(?:static|async|get|set)\s+)*\*?\s*(#?[\w$]+)\s*\(.*\)\s*\{')
JS_NOT_METHOD = {'if', 'for', 'while', 'switch', 'catch', 'with', 'function', 'return'}
HEADING = re.compile(r' {0,3}(#{1,6})\s+(.*?)(?:\s+#+)?\s*$')
FENCE = re.compile(r' {0,3}(`{3,}|~{3,})(.*)$')

WORDS_MAX = 80  # chars of one part's words

Entry = tuple  # (line number, depth, words)


def python(text: str) -> list[Entry]:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):  # a conflict, a template: what the lines alone show
        return python_lines(text)
    out = sections(text, PY_SECTION, strings(tree))

    def walk(nodes, depth):
        for n in nodes:
            if isinstance(n, ast.ClassDef):
                out.append((n.lineno, depth, f'class {n.name}'))
                walk(n.body, depth + 1)
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out.append((n.lineno, depth, f'def {n.name}'))
            else:  # a definition under an `if` or `try`
                for part in ('body', 'handlers', 'orelse', 'finalbody'):
                    if isinstance(inner := getattr(n, part, None), list):
                        walk(inner, depth)
    walk(tree.body, 0)
    return sorted(out)


def python_lines(text: str) -> list[Entry]:
    found = ((i, re.match(r'(\s*)(?:async\s+)?(class|def)\s+(\w+)', l)) for i, l in enumerate(text.splitlines(), 1))
    return sorted([(i, 1 if m[1] else 0, f'{m[2]} {m[3]}') for i, m in found if m] + sections(text, PY_SECTION))


def strings(tree) -> set[int]:
    """The lines inside a string of several lines: a `# ---` there is not a section."""
    return {i for n in ast.walk(tree) if isinstance(n, (ast.Constant, ast.JoinedStr))
            for i in range(n.lineno + 1, n.end_lineno + 1)}


def sections(text: str, pattern, skip=()) -> list[Entry]:
    return [(i, 0, f'--- {m[1]}') for i, l in enumerate(text.split('\n'), 1)
            if i not in skip and (m := pattern.match(l))]


def javascript(text: str) -> list[Entry]:
    out, comment, in_class, member = [], False, False, None  # member: the indent of the class's own lines
    for i, line in enumerate(text.split('\n'), 1):
        if comment:
            comment = '*/' not in line
            continue
        if m := JS_SECTION.match(line):
            out.append((i, 0, f'--- {m[1]}'))
        if line.lstrip().startswith('/*'):
            comment = '*/' not in line
            continue
        if m := JS_CLASS.match(line):
            out.append((i, 0, f'class {m[1] or "(default)"}'))
            in_class, member = not line.rstrip().endswith('}'), None
        elif m := JS_FUNCTION.match(line):
            out.append((i, 0, f'function {m[1] or "(default)"}'))
        elif m := JS_NAMED.match(line):
            out.append((i, 0, f'function {m[1]}'))
        elif in_class and line.strip() and not line.lstrip().startswith('//'):
            indent = line[:len(line) - len(line.lstrip())]
            member = indent if member is None else member
            if (m := JS_METHOD.match(line)) and m[1] == member and m[2] not in JS_NOT_METHOD:
                out.append((i, 1, m[2]))
        if in_class and line.startswith('}'):
            in_class = False
    return out


def markdown(text: str) -> list[Entry]:
    out, fence = [], ''
    for i, line in enumerate(text.split('\n'), 1):
        if m := FENCE.match(line):
            if not fence:
                fence = m[1]
            elif m[1].startswith(fence) and not m[2].strip():
                fence = ''
        elif not fence and (m := HEADING.match(line)):
            out.append((i, 0, f'{m[1]} {m[2]}'))
    return out


KINDS = {'.py': python, '.js': javascript, '.mjs': javascript, '.md': markdown}


def outline(path: Path) -> list[str]:
    kind = KINDS.get(path.suffix.lower())
    if not kind:
        return []
    text = path.read_text(encoding='utf-8-sig', errors='replace')
    return [f'{n} {"  " * depth}{words[:WORDS_MAX]}' for n, depth, words in kind(text)]


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit('usage: outline.py FILE')
    try:
        print('\n'.join(outline(Path(sys.argv[1]))))
    except OSError as e:
        sys.exit(f'outline.py: {e}')
