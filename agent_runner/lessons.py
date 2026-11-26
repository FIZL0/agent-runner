"""F413: lessons, what a project's agents learned, shown in a brief only where they apply.

plan/LESSONS.md holds one line per lesson: `- L<id> <text> | files: a, dir/**`. The id is a short hash of the
text, so two branches that each add one never take the same id. Under `## Dropped`, the lessons dropped and why
(by hand with `plan lesson drop`, or by themselves once none of their files is left in the tree).

A brief shows the lessons whose files meet the task's, most specific first, at most BRIEF_MAX. Off unless
`[plan] lessons = true`. The file merges like plan lines (`merge_file`, git's driver `merge-lessons`): both
sides' additions are kept, and a lesson dropped on either side stays dropped."""
from __future__ import annotations

import datetime
import fnmatch
import hashlib
import re
import shlex
import subprocess
from pathlib import Path

NAME = 'LESSONS.md'
TEXT_MAX = 200  # characters of one lesson
BRIEF_MAX = 8  # lessons in one brief
DROPPED = '## Dropped'
HEAD = ['# Lessons', '',
        'What agents learned, one line each, shown in the brief of a task whose files meet its files.',
        '`plan lesson add "TEXT" --files a,b`, `plan lesson list`, `plan lesson drop ID "why"`.', '']
LINE = re.compile(r'^- (L[0-9a-f]{6}) (.*?) \| files: (.*?)(?: \| dropped (.*))?$')
DRIVER = 'agent-runner-lessons'


def new_id(text: str) -> str:
    return 'L' + hashlib.sha1(' '.join(text.split()).encode('utf-8')).hexdigest()[:6]


def parse(lines: list[str]) -> tuple[dict, dict]:
    """(live, dropped): id -> (text, files, why) in file order."""
    live, dropped, into = {}, {}, None
    into = live
    for l in lines:
        if l.strip() == DROPPED:
            into = dropped
        elif m := LINE.match(l.rstrip()):
            into[m[1]] = (m[2], [f.strip() for f in m[3].split(',') if f.strip()], m[4] or '')
    return live, dropped


def render(live: dict, dropped: dict) -> list[str]:
    row = lambda i, v: f'- {i} {v[0]} | files: {", ".join(v[1])}' + (f' | dropped {v[2]}' if v[2] else '')
    out = HEAD + [row(i, v) for i, v in live.items()]
    if dropped:
        out += ['', DROPPED, ''] + [row(i, v) for i, v in dropped.items()]
    return out


def path(plan_dir) -> Path:
    return Path(plan_dir) / NAME


def read(plan_dir) -> tuple[dict, dict]:
    p = path(plan_dir)
    return parse(p.read_text(encoding='utf-8').splitlines()) if p.exists() else ({}, {})


def write(plan_dir, live: dict, dropped: dict) -> None:
    path(plan_dir).write_text('\n'.join(render(live, dropped)) + '\n', encoding='utf-8')


def add(plan_dir, text: str, files: list[str]) -> str:
    text = ' '.join(text.split()).replace(' | ', ' - ')
    if not text:
        raise ValueError('a lesson needs its text')
    if len(text) > TEXT_MAX:
        raise ValueError(f'a lesson is at most {TEXT_MAX} characters; this one is {len(text)}')
    if not files:
        raise ValueError('a lesson needs the files it applies to: --files a,dir/**')
    live, dropped = read(plan_dir)
    i = new_id(text)
    if i in live:
        raise ValueError(f'{i} already says that')
    dropped.pop(i, None)
    live[i] = (text, files, '')
    write(plan_dir, live, dropped)
    return i


def drop(plan_dir, lid: str, why: str) -> None:
    why = ' '.join(why.split())
    if not why:
        raise ValueError('say why the lesson is wrong')
    live, dropped = read(plan_dir)
    if lid not in live:
        raise ValueError(f'no lesson {lid}')
    t, f, _ = live.pop(lid)
    dropped[lid] = (t, f, f'{datetime.date.today().isoformat()}: {why}')
    write(plan_dir, live, dropped)


def _meet(x: str, y: str) -> bool:
    """As plan.overlap: equal, one a tail of the other, or one matching the other as a pattern."""
    return (x == y or x.endswith('/' + y) or y.endswith('/' + x)
            or ('*' in x and fnmatch.fnmatch(y, f'*{x}')) or ('*' in y and fnmatch.fnmatch(x, f'*{y}')))


def _specific(pattern: str) -> int:
    """How narrow a pattern is: its characters before the first wildcard."""
    return len(pattern.split('*', 1)[0])


def matching(plan_dir, task_files: list[str], most: int = BRIEF_MAX) -> list[tuple[str, str]]:
    """(id, text) of the lessons whose files meet `task_files`, most specific first, at most `most`."""
    live, _ = read(plan_dir)
    scored = []
    for n, (i, (text, files, _)) in enumerate(live.items()):
        hit = [f for f in files if any(_meet(f, t) for t in task_files)]
        if hit:
            scored.append((-max(map(_specific, hit)), len(files), n, i, text))
    return [(i, t) for *_, i, t in sorted(scored)][:most]


def tracked(root) -> list[str]:
    r = subprocess.run(['git', 'ls-files'], cwd=str(root), capture_output=True, text=True, errors='replace')
    return r.stdout.splitlines() if r.returncode == 0 else []


def drop_gone(plan_dir, root) -> list[str]:
    """Drop, with the reason logged under Dropped, each lesson none of whose files is left in the tree."""
    live, dropped = read(plan_dir)
    have = tracked(root)
    if not live or not have:
        return []
    gone = [i for i, (_, files, _) in live.items()
            if not any(_meet(f, h) or fnmatch.fnmatch(h, f) for f in files for h in have)]
    for i in gone:
        t, f, _ = live.pop(i)
        dropped[i] = (t, f, f'{datetime.date.today().isoformat()}: its files are all gone from the tree')
    if gone:
        write(plan_dir, live, dropped)
    return gone


def merge(base: list[str], ours: list[str], theirs: list[str]) -> list[str]:
    """Three-way: every live lesson either side has (ours first), less any lesson dropped or removed on either side."""
    (bl, bd), (ol, od), (tl, td) = parse(base), parse(ours), parse(theirs)
    dropped = {**td, **od}
    gone = set(dropped) | {i for i in bl if i not in ol or i not in tl}
    live = {i: v for i, v in {**tl, **ol}.items() if i not in gone}
    live = {i: live[i] for i in [*ol, *tl] if i in live}
    return render(live, dropped)


def merge_file(base: str, ours: str, theirs: str) -> int:
    """git's merge driver (%O %A %B): the merged lessons into `ours`."""
    read_ = lambda p: Path(p).read_text(encoding='utf-8', errors='replace').splitlines()
    Path(ours).write_text('\n'.join(merge(read_(base), read_(ours), read_(theirs))) + '\n', encoding='utf-8')
    return 0


def install_driver(cwd, rel: str) -> None:
    """Make `merge_file` git's merge for LESSONS.md at `rel` (from the top of the repository at `cwd`)."""
    from agent_runner.config import runner_cmd
    g = lambda *a: subprocess.run(['git', *a], cwd=str(cwd), capture_output=True, text=True)
    r = g('rev-parse', '--path-format=absolute', '--git-common-dir')
    if r.returncode:
        return
    cmd = shlex.join([*runner_cmd(), 'merge-lessons']) + ' %O %A %B'
    if g('config', f'merge.{DRIVER}.driver').stdout.strip() != cmd:
        g('config', f'merge.{DRIVER}.name', 'agent-runner: lessons merged by line')
        g('config', f'merge.{DRIVER}.driver', cmd)
    att = Path(r.stdout.strip()) / 'info' / 'attributes'
    have = att.read_text(encoding='utf-8').splitlines() if att.exists() else []
    if (w := f'/{rel} merge={DRIVER}') not in have:
        att.parent.mkdir(parents=True, exist_ok=True)
        att.write_text('\n'.join(have + [w]) + '\n', encoding='utf-8')


def brief_lines(c, task_files: list[str]) -> list[str]:
    """The brief's section: lessons for the task's files, after dropping those whose files are gone."""
    if not c.raw['plan'].get('lessons') or not task_files:
        return []
    gone = drop_gone(c.plan_dir, c.root)
    got = matching(c.plan_dir, task_files)
    out = ['', '## Lessons for these files (wrong? `plan lesson drop ID "why"`)'] if got else []
    out += [f'- {i} {t}' for i, t in got]
    if gone:
        out += [f'(dropped, their files are gone: {", ".join(gone)})']
    return out


def command(c, words: list[str], prog: str = 'plan') -> int:
    """`plan lesson add "TEXT" --files a,b`, `plan lesson list`, `plan lesson drop ID "why"`."""
    import sys
    if not c.raw['plan'].get('lessons'):
        print(f'{prog}: lessons are off; turn them on with [plan] lessons = true in runner.toml', file=sys.stderr)
        return 2
    verb, rest = (words[0], words[1:]) if words else ('', [])
    try:
        if verb == 'add':
            files: list[str] = []
            text = []
            k = 0
            while k < len(rest):
                if rest[k] == '--files' and k + 1 < len(rest):
                    files += [f.strip() for f in rest[k + 1].split(',') if f.strip()]
                    k += 2
                else:
                    text.append(rest[k])
                    k += 1
            i = add(c.plan_dir, ' '.join(text), files)
            try:
                install_driver(c.plan_dir, Path(path(c.plan_dir)).resolve().relative_to(
                    Path(subprocess.run(['git', 'rev-parse', '--show-toplevel'], cwd=str(c.plan_dir),
                                        capture_output=True, text=True).stdout.strip()).resolve()).as_posix())
            except (ValueError, OSError):
                pass
            print(f'added lesson {i}')
        elif verb == 'list':
            gone = drop_gone(c.plan_dir, c.root)
            live, _ = read(c.plan_dir)
            for i, (t, f, _) in live.items():
                print(f'{i} {t} | files: {", ".join(f)}')
            if gone:
                print(f'(dropped, their files are gone: {", ".join(gone)})')
            if not live:
                print('no lessons')
        elif verb == 'drop' and len(rest) >= 2:
            drop(c.plan_dir, rest[0], ' '.join(rest[1:]))
            print(f'dropped lesson {rest[0]}')
        else:
            print(f'usage: {prog} lesson add "TEXT" --files a,b | lesson list | lesson drop ID "why"', file=sys.stderr)
            return 2
    except ValueError as e:
        print(f'{prog}: {e}', file=sys.stderr)
        return 2
    return 0
