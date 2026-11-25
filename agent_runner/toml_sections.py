"""F448a: a setting that is a table written as sections ([run.tools.iphone15], [run.join]) set in its file.

Only the entries that change are touched: a section that stays keeps its lines and comments."""
from __future__ import annotations

import json
import re
import tomllib

Section = tuple[int, int, tuple[str, ...], bool]  # its first line, the line after its last key, its path, a plain [table]?


def sections(lines: list[str]) -> list[Section]:
    """Every [header] of `lines`, in order."""
    from agent_runner.config import _toml_span
    out: list[list] = []
    i = 0
    while i < len(lines):
        l = lines[i]
        n = 1
        if l.strip() and not l.lstrip().startswith('#'):
            if l.lstrip().startswith('['):
                out.append([i, i + 1, _path(l), not l.lstrip().startswith('[[')])
            else:
                n = _toml_span(lines, i) or 1
                if out:
                    out[-1][1] = i + n
        i += n
    return [(a, b, p, plain) for a, b, p, plain in out]


def _path(header: str) -> tuple[str, ...]:
    try:
        d = tomllib.loads(header)
    except tomllib.TOMLDecodeError:
        return ()
    out = []
    while isinstance(d, (dict, list)) and d:
        if isinstance(d, list):
            d = d[0]
            continue
        k = next(iter(d))
        out.append(k)
        d = d[k]
    return tuple(out)


def _under(lines: list[str], path: tuple[str, ...]) -> list[Section]:
    return [s for s in sections(lines) if s[2][:len(path)] == path]


def written(lines: list[str], path: tuple[str, ...]) -> bool:
    """Is the table at `path` written as sections?"""
    return bool(_under(lines, path))


def drop(lines: list[str], path: tuple[str, ...]) -> list[str]:
    """`lines` without the sections at and under `path`; comments between sections stay."""
    out = list(lines)
    for a, b, *_ in reversed(_under(lines, path)):
        del out[a:b]
        if 0 < a < len(out) and not out[a - 1].strip() and not out[a].strip():
            del out[a]
    return out


def change(lines: list[str], path: tuple[str, ...], have: dict, want: dict) -> list[str]:
    """`lines` with the table at `path` (written as sections, `have` now) made `want`. What it cannot do it leaves: the
    caller reads the result back."""
    out = list(lines)
    for k in [k for k in have if k not in want or have[k] != want[k]]:
        at = _under(out, (*path, k))
        if at and k in want and isinstance(have[k], dict) and isinstance(want[k], dict) and at[0][2] == (*path, k) and at[0][3] \
                and want[k]:
            out = change(out, (*path, k), have[k], want[k])
            continue
        if at:
            out = drop(out, (*path, k))
            if k in want:
                out = _add(out, path, k, want[k], at[0][0])
        else:
            out = _key(out, path, k, want)
    for k in want:
        if k not in have:
            out = _add(out, path, k, want[k])
    return out


def _bare(k: str) -> str:
    return k if re.fullmatch(r'[A-Za-z0-9_-]+', k) else json.dumps(k, ensure_ascii=False)


def _own(lines: list[str], path: tuple[str, ...]) -> Section | None:
    return next((s for s in sections(lines) if s[2] == path and s[3]), None)


def _key(lines: list[str], path: tuple[str, ...], k: str, want: dict) -> list[str]:
    """The line of `k` in the section `path`, set to `want`'s or taken out."""
    from agent_runner.config import _toml_comment, _toml_inner, _toml_span, toml_value
    own = _own(lines, path)
    i, end = (own[0] + 1, own[1]) if own else (0, 0)
    while i < end:
        l = lines[i]
        n = (_toml_span(lines, i) or 1) if l.strip() and not l.lstrip().startswith('#') else 0
        if n:
            was = lines[i:i + n]
            try:
                hit = next(iter(tomllib.loads('\n'.join(was))), None) == k
            except tomllib.TOMLDecodeError:
                hit = False
            if hit:
                dent = l[:len(l) - len(l.lstrip())]
                new = [dent + c for c in _toml_inner(was)]
                if k in want:
                    new.append(f'{dent}{_bare(k)} = {toml_value(want[k])}{_toml_comment(chr(10).join(was))}')
                return [*lines[:i], *new, *lines[i + n:]]
        i += n or 1
    return lines


def _add(lines: list[str], path: tuple[str, ...], k: str, v, at: int | None = None) -> list[str]:
    """A new entry: a line in the section `path`, or, for a table with no such section or one whose entries are
    sections, a section of its own (at line `at`, else after the last one there)."""
    from agent_runner.config import toml_value
    own, under = _own(lines, path), _under(lines, path)
    alone = isinstance(v, dict) and (own is None or len(under) > 1 or own[1] == own[0] + 1)
    if own and not alone:
        return [*lines[:own[1]], f'{_bare(k)} = {toml_value(v)}', *lines[own[1]:]]
    if not isinstance(v, dict):  # its other entries are sections: these lines need their own header, above them
        new, at = [f'[{".".join(map(_bare, path))}]', f'{_bare(k)} = {toml_value(v)}', ''], under[0][0] if under else len(lines)
        return [*lines[:at], *new, *lines[at:]]
    new = [f'[{".".join(map(_bare, (*path, k)))}]', *(f'{_bare(x)} = {toml_value(y)}' for x, y in v.items())]
    if at is not None:
        tail = [''] if at < len(lines) and lines[at].strip() else []
        return [*lines[:at], *new, *tail, *lines[at:]]
    at = under[-1][1] if under else len(lines)
    tail = [''] if at < len(lines) and lines[at].strip() else [] if at < len(lines) else ['']
    return [*lines[:at], '', *new, *tail, *lines[at:]]
