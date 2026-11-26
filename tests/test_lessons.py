#!/usr/bin/env python3
"""F413: lessons: matching, the caps, the self-drop, a merge of two adds, the command and the brief."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from _check import ROOT, check, eq, git, report, run  # noqa: F401

sys.path.insert(0, str(ROOT))
from agent_runner import lessons as L  # noqa: E402


def repo(tmp: Path, on: bool = True) -> Path:
    r = tmp / 'p'
    (r / 'plan').mkdir(parents=True)
    (r / 'src').mkdir()
    (r / 'src' / 'a.py').write_text('x\n')
    (r / 'src' / 'b.py').write_text('x\n')
    (r / 'plan' / 'TODO.md').write_text('# TODO\n\n- [ ] **F1** do it | files: src/a.py\n')
    (r / 'runner.toml').write_text('[plan]\nlessons = true\n' if on else '')
    git(r, 'init', '-q', '-b', 'main')
    git(r, 'add', '-A')
    git(r, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'init')
    return r


def test_matching_and_caps():
    print('lessons: matching, most specific first, at most 8, text at most 200')
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        a = L.add(d, 'broad one', ['src/**'])
        b = L.add(d, 'narrow one', ['src/a.py'])
        L.add(d, 'other file', ['docs/x.md'])
        eq([i for i, _ in L.matching(d, ['src/a.py'])], [b, a], 'the narrow lesson first, the other file left out')
        for n in range(10):
            L.add(d, f'many {n}', ['src/a.py'])
        eq(len(L.matching(d, ['src/a.py'])), 8, 'at most 8')
        try:
            L.add(d, 'x' * 201, ['src/a.py'])
            check(False, 'a long lesson is refused')
        except ValueError:
            check(True, 'a long lesson is refused')
        L.add(d, 'y' * 200, ['zzz/q.py'])
        check(L.new_id('y' * 200) in L.read(d)[0], 'a 200-character lesson is taken')
        L.drop(d, b, 'wrong now')
        live, dropped = L.read(d)
        check(b not in live and 'wrong now' in dropped[b][2], 'a drop is logged with its reason')


def test_self_drop_and_brief():
    print('lessons: one whose files are gone drops itself; the brief shows the rest, and none when off')
    with tempfile.TemporaryDirectory() as t:
        r = repo(Path(t))
        eq(run(r, 'plan', 'lesson', 'add', 'keep a short', '--files', 'src/a.py').returncode, 0, 'added')
        run(r, 'plan', 'lesson', 'add', 'gone file', '--files', 'old/*.py')
        out = run(r, 'plan', 'brief', 'F1').stdout
        check('keep a short' in out and '## Lessons' in out, 'the brief shows the lesson', out[-600:])
        check('gone file' not in L.read(r / 'plan')[0].__repr__(), 'the gone one dropped itself')
        check('gone from the tree' in (r / 'plan' / 'LESSONS.md').read_text(), 'its drop is logged')
        (r / 'runner.toml').write_text('')
        check('keep a short' not in run(r, 'plan', 'brief', 'F1').stdout, 'off: the brief shows none')
        check(run(r, 'plan', 'lesson', 'list').returncode != 0, 'off: the command says so')


def test_merge_two_adds():
    print('lessons: two branches each add one, and git merges both in')
    with tempfile.TemporaryDirectory() as t:
        r = repo(Path(t))
        run(r, 'plan', 'lesson', 'add', 'base one', '--files', 'src/a.py')
        git(r, 'add', '-A')
        git(r, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'base')
        git(r, 'checkout', '-qb', 'side')
        run(r, 'plan', 'lesson', 'add', 'side one', '--files', 'src/b.py')  # a plan edit here commits itself
        git(r, 'checkout', '-q', 'main')
        run(r, 'plan', 'lesson', 'add', 'main one', '--files', 'src/a.py')
        eq(git(r, 'status', '--porcelain'), '', 'the add is committed')
        git(r, '-c', 'user.name=t', '-c', 'user.email=t@t', 'merge', '-q', '--no-edit', 'side')
        texts = [v[0] for v in L.read(r / 'plan')[0].values()]
        eq(sorted(texts), ['base one', 'main one', 'side one'], 'both adds kept')
    base = L.render({'L000001': ('a', ['x'], '')}, {})
    ours = L.render({}, {'L000001': ('a', ['x'], 'today: wrong')})
    theirs = L.render({'L000001': ('a', ['x'], ''), 'L000002': ('b', ['y'], '')}, {})
    live, dropped = L.parse(L.merge(base, ours, theirs))
    eq((list(live), list(dropped)), (['L000002'], ['L000001']), 'a drop on one side stays dropped')
    base = L.render({}, {'L000001': ('a', ['x'], 'today: wrong')})
    ours = L.render({'L000001': ('a', ['x'], '')}, {})
    live, dropped = L.parse(L.merge(base, ours, base))
    eq((list(live), list(dropped)), (['L000001'], []), 'a lesson added again after its drop is kept')


if __name__ == '__main__':
    sys.exit(report([test_matching_and_caps, test_self_drop_and_brief, test_merge_two_adds]))
