"""F413: lessons, what a project's agents learned, shown in a brief only where they apply.

`<plan dir>/LESSONS.md` holds one line per lesson: `- L<hex> TEXT | files: a,b/**`. The id is taken from the
text, so two branches that each add a lesson never pick the same id, and the file merges by line union (a
`[run] joinable` entry). A lesson that is dropped (`plan lesson drop`, or by itself when its files are all gone
from the tree) moves under `## Dropped` with the date and the reason, so the drop merges the same way.

On only with `[plan] lessons = true`.
"""
from __future__ import annotations

import datetime
import fnmatch
import hashlib
import re
import sys
from pathlib import Path

TEXT_MAX = 200  # characters of one lesson's text
BRIEF_MAX = 8  # lessons one brief shows
DROPPED = '## Dropped'
HEAD = ('# Lessons', '', 'What agents learned, one per line, shown in a brief whose task names the same files. '
        '`plan lesson add "TEXT" --files …`, `plan lesson list`, `plan lesson drop ID "why"`.', '')
LINE = re.compile(r'^- (L[0-9a-f]{6}) (.+?) \| files: ([^|]+?)(?: \| (.*))?$')


def path(plan_dir) -> Path:
    return Path(plan_dir) / 'LESSONS.md'


def lesson_id(text: str) -> str:
    return 'L' + hashlib.sha1(' '.join(text.split()).encode()).hexdigest()[:6]


def read(plan_dir) -> tuple[list[dict], list[str]]:
    """The live lessons (dicts: id, text, files) and the file's lines."""
    p = path(plan_dir)
    ls = p.read_text(encoding='utf-8').splitlines() if p.exists() else []
    live, seen = [], set()
    for l in ls:
        if l.strip() == DROPPED:
            break
        if (m := LINE.match(l.strip())) and m[1] not in seen:  # a union of the same add twice: once
            seen.add(m[1])
            live.append({'id': m[1], 'text': m[2], 'files': [f.strip() for f in m[3].split(',') if f.strip()]})
    return live, ls


def _write(plan_dir, ls: list[str]) -> None:
    p = path(plan_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('\n'.join(ls).rstrip('\n') + '\n', encoding='utf-8')


def add(plan_dir, text: str, files: list[str]) -> str:
    text = ' '.join(text.split()).replace('|', '/')
    if not text:
        raise ValueError('a lesson needs its text')
    if len(text) > TEXT_MAX:
        raise ValueError(f'a lesson is at most {TEXT_MAX} characters ({len(text)} given)')
    if not files:
        raise ValueError('a lesson needs --files: the files or globs it applies to')
    live, ls = read(plan_dir)
    tid = lesson_id(text)
    if any(x['id'] == tid for x in live):
        return tid
    ls = ls or list(HEAD)
    at = next((i for i, l in enumerate(ls) if l.strip() == DROPPED), len(ls))
    while at and not ls[at - 1].strip():  # after the last lesson, before the blank lines
        at -= 1
    ls.insert(at, f'- {tid} {text} | files: {",".join(files)}')
    _write(plan_dir, ls)
    return tid


def drop(plan_dir, tid: str, why: str) -> bool:
    """Moves lesson `tid` under ## Dropped with today's date and `why`; False when there is no such live lesson."""
    live, ls = read(plan_dir)
    end = next((i for i, l in enumerate(ls) if l.strip() == DROPPED), len(ls))
    i = next((i for i, l in enumerate(ls[:end]) if (m := LINE.match(l.strip())) and m[1] == tid), None)
    if i is None:
        return False
    line = ls.pop(i).strip()
    m = LINE.match(line)
    if DROPPED not in (l.strip() for l in ls):
        ls += ['', DROPPED, '']
    ls.append(f'- {m[1]} {m[2]} | files: {m[3]} | dropped {datetime.date.today()}: {" ".join(why.split()) or "no reason"}')
    _write(plan_dir, ls)
    return True


def _meets(pattern: str, f: str) -> bool:
    return (pattern == f or f.endswith('/' + pattern) or pattern.endswith('/' + f)
            or ('*' in pattern and fnmatch.fnmatch(f, pattern)) or ('*' in f and fnmatch.fnmatch(pattern, f)))


def specificity(pattern: str) -> int:
    """More for a plain path than a glob, and for a longer fixed part."""
    return (0 if '*' in pattern or '?' in pattern else 1000) + len(pattern.replace('*', ''))


def matching(live: list[dict], task_files: list[str], most: int = BRIEF_MAX) -> list[dict]:
    """The lessons whose files meet `task_files`, most specific first, at most `most`."""
    scored = []
    for x in live:
        hit = [specificity(p) for p in x['files'] for f in task_files if _meets(p, f)]
        if hit:
            scored.append((-max(hit), x['id'], x))
    return [x for *_, x in sorted(scored, key=lambda s: s[:2])][:most]


def gone(lesson: dict, tree: list[str]) -> bool:
    """True when none of the lesson's files is in `tree` (the repo's tracked paths)."""
    return not any(_meets(p, f) or (not any(c in p for c in '*?[') and f.startswith(p.rstrip('/') + '/'))
                   for p in lesson['files'] for f in tree)


def prune(plan_dir, tree: list[str]) -> list[str]:
    """Drops the lessons whose files are all gone from `tree`, saying so on stderr; their ids."""
    if not tree:
        return []  # no tree read: drop nothing rather than everything
    out = []
    for x in read(plan_dir)[0]:
        if gone(x, tree) and drop(plan_dir, x['id'], 'its files are all gone from the tree'):
            print(f'lesson {x["id"]} dropped itself: its files ({",".join(x["files"])}) are all gone', file=sys.stderr)
            out.append(x['id'])
    return out


def brief_lines(c, task_files: list[str]) -> list[str]:
    """The brief's lessons section ([] when the setting is off or none applies)."""
    if not c.raw['plan'].get('lessons') or not task_files:
        return []
    from agent_runner.gitops import git
    tree = git('ls-files', cwd=c.root).stdout.splitlines()
    prune(c.plan_dir, tree)
    got = matching(read(c.plan_dir)[0], task_files)
    if not got:
        return []
    return ['', '## Lessons on these files (wrong one? `plan lesson drop ID "why"`)',
            *(f'- {x["id"]} {x["text"]} ({",".join(x["files"])})' for x in got)]


def command(c, rest: list[str]) -> int:
    """`plan lesson add "TEXT" --files A,B`, `plan lesson list`, `plan lesson drop ID "why"`."""
    prog = 'agent-runner plan lesson'
    if not c.raw['plan'].get('lessons'):
        print(f'{prog}: lessons are off; `[plan] lessons = true` in runner.toml turns them on', file=sys.stderr)
        return 2
    verb, args = (rest[0], rest[1:]) if rest else ('', [])
    if verb == 'list':
        live = read(c.plan_dir)[0]
        print('\n'.join(f'{x["id"]} {x["text"]} | files: {",".join(x["files"])}' for x in live) or 'no lessons')
        return 0
    if verb == 'add':
        files, words, i = [], [], 0
        while i < len(args):
            if args[i] == '--files' and i + 1 < len(args):
                files += [f.strip() for f in args[i + 1].split(',') if f.strip()]
                i += 2
            elif args[i].startswith('--files='):
                files += [f.strip() for f in args[i][8:].split(',') if f.strip()]
                i += 1
            else:
                words.append(args[i])
                i += 1
        try:
            print(f'lesson {add(c.plan_dir, " ".join(words), files)}')
        except ValueError as e:
            print(f'{prog}: not added: {e}', file=sys.stderr)
            return 2
        return 0
    if verb == 'drop' and len(args) >= 2:
        if not drop(c.plan_dir, args[0], ' '.join(args[1:])):
            print(f'{prog}: no lesson {args[0]}', file=sys.stderr)
            return 1
        print(f'dropped lesson {args[0]}')
        return 0
    print(f'{prog} add "TEXT" --files A,B | list | drop ID "why"', file=sys.stderr)
    return 2
