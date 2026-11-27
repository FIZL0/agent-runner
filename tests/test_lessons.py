"""F413: lessons — matching, the caps, the self-drop, a merge of two adds."""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from _check import check, eq, git, report  # noqa: E402  (_check puts the repo on sys.path)
from agent_runner import lessons as L


def t_matching_and_caps():
    d = Path(tempfile.mkdtemp())
    a = L.add(d, 'globs first', ['src/**'])
    b = L.add(d, 'exact wins', ['src/menu.rs'])
    L.add(d, 'elsewhere', ['docs/x.md'])
    live = L.read(d)[0]
    got = [x['id'] for x in L.matching(live, ['src/menu.rs'])]
    eq(got, [b, a], 'the exact file before the glob, the other file not shown')
    eq(L.add(d, 'exact  wins', ['src/menu.rs']), b, 'the same text twice is one lesson')
    try:
        L.add(d, 'x' * 201, ['a'])
        check(False, 'over 200 characters refused')
    except ValueError:
        check(True, 'over 200 characters refused')
    for i in range(12):
        L.add(d, f'many {i}', ['lib/a.py'])
    eq(len(L.matching(L.read(d)[0], ['lib/a.py'])), 8, 'at most 8 in a brief')
    check(L.drop(d, b, 'wrong'), 'drop by id')
    check(b not in [x['id'] for x in L.read(d)[0]], 'a dropped lesson is not live')
    check('wrong' in L.path(d).read_text(), 'the reason is kept')


def t_self_drop():
    d = Path(tempfile.mkdtemp())
    keep = L.add(d, 'kept', ['agent_runner/*.py', 'gone.py'])
    lose = L.add(d, 'lost', ['gone.py', 'old/**'])
    dir_ = L.add(d, 'a dir', ['agent_runner'])
    eq(L.prune(d, ['agent_runner/plan.py', 'README.md']), [lose], 'only the lesson with every file gone drops')
    eq(sorted(x['id'] for x in L.read(d)[0]), sorted([keep, dir_]), 'the others stay')
    eq(L.prune(d, []), [], 'no tree read drops nothing')


def t_merge_two_adds():
    r = Path(tempfile.mkdtemp())
    git(r, 'init', '-q')
    (r / '.gitattributes').write_text('LESSONS.md merge=union\n')
    L.add(r, 'base', ['a.py'])
    git(r, 'add', '-A')
    git(r, 'commit', '-qm', 'base')
    git(r, 'checkout', '-qb', 'one')
    x = L.add(r, 'from one', ['b.py'])
    git(r, 'commit', '-qam', 'one')
    git(r, 'checkout', '-q', 'main')
    y = L.add(r, 'from two', ['c.py'])
    git(r, 'commit', '-qam', 'two')
    m = subprocess.run(['git', 'merge', '-q', 'one', '-m', 'm'], cwd=r, capture_output=True, text=True)
    eq(m.returncode, 0, 'two adds merge with no conflict')
    eq(len({x, y, L.lesson_id('base')} & {z['id'] for z in L.read(r)[0]}), 3, 'both adds and the base kept')


if __name__ == '__main__':
    raise SystemExit(report([t_matching_and_caps, t_self_drop, t_merge_two_adds]))
