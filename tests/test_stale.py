#!/usr/bin/env python3
"""F416: the removal check at `done`: what still names a removed file, test, setting or command.

    python3 tests/test_stale.py        (no network; a few seconds, mostly git)
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

from _check import check, eq, git, has, report, run

from agent_runner import stale as S  # noqa: E402

FILES = {
    '.gitignore': '.runner/\n',
    'runner.toml': '[run]\nremote = false\nreview = false\ntest = "python3 gate.py"\n[git]\npush = false\n',
    'gate.py': 'open(".runner/gate-ran", "a").write("x")\n',
    'src/tile_sheet.py': 'print("a tile sheet with some lines")\nX = 1\nY = 2\nZ = 3\n',
    'src/app.py': 'import os\nHOME = os.environ.get("APP_HOME_DIR")\n',
    'src/cli.py': 'p.add_parser("bake-sheet")\np.add_parser("draw")\n',
    'app.toml': '[app]\ntile_size = 4\nname = "x"\n',
    'package.json': '{"scripts": {"deploy": "x", "start": "y"}, "dependencies": {"left-pad": "1"}}\n',
    'tests/test_tiles.py': 'def test_tile_edges():\n    pass\n\n\ndef test_tile_rows():\n    pass\n',
    '.github/workflows/nightly.yml': 'name: Nightly\non: push\n',
    '.github/workflows/ci.yml': 'name: ci\non: push\n',
    'README.md': '# App\n\nNothing here.\n',
    'GLOSSARY.md': '# App\n\n## Language\n',
}
TASKS = ''.join(f'- [ ] **{t}** job {t} | files: {t}.py\n' for t in ('F1', 'F2', 'F3'))


class Proj:
    """A project on task/F1, and `done` in it."""

    def __init__(self, t: str, more: dict[str, str] | None = None, tasks: str = '', done: str = '') -> None:
        self.root = Path(t) / 'proj'
        self.root.mkdir()
        git(self.root, 'init', '-q', '-b', 'main')
        files = {**FILES, **(more or {}), 'plan/TODO.md': f'# TODO\n\n### Queue\n\n{TASKS}{tasks}',
                 'plan/DONE.md': f'# DONE\n\n### Queue\n\n{done}'}
        for f, text in files.items():
            self.write(f, text)
        (self.root / '.runner').mkdir()
        git(self.root, 'add', '-A')
        git(self.root, 'commit', '-qm', 'start')
        git(self.root, 'checkout', '-q', '-b', 'task/F1')
        self.claude = Path(t) / 'claude'
        self.env = {**os.environ, 'AGENT_RUNNER_REPO': str(self.root), 'CLAUDE_CONFIG_DIR': str(self.claude)}

    def write(self, f: str, text: str) -> None:
        (self.root / f).parent.mkdir(parents=True, exist_ok=True)
        (self.root / f).write_text(text, encoding='utf-8')

    def done(self, *more: str, tid: str = 'F1'):
        return run(self.root, 'done', tid, f'{tid}: x', *more, env=self.env)

    def gate_ran(self) -> bool:
        return (self.root / '.runner' / 'gate-ran').exists()

    def refused(self, what: str, *pats: str, more=()) -> str:
        head = git(self.root, 'rev-parse', 'HEAD')
        r = self.done(*more)
        check(r.returncode == 2 and 'Nothing ticked' in r.stderr, f'refused: {what}', r.stdout + r.stderr)
        eq((git(self.root, 'rev-parse', 'HEAD'), self.gate_ran()), (head, False), 'nothing committed, no gate ran')
        for p in pats:
            has(r.stderr, p, f'says {p}')
        return r.stderr

    def passes(self, what: str, *more: str) -> str:
        r = self.done(*more)
        check(r.returncode == 0 and 'ticked F1' in r.stdout, f'passes: {what}', r.stdout + r.stderr)
        return r.stdout + r.stderr


def proj(**kw):
    t = tempfile.TemporaryDirectory()
    p = Proj(t.name, **kw)
    p.tmp = t
    return p


def test_names() -> None:
    print('which names are specific enough')
    for n in ('tile_size', 'bake-sheet', 'tileSize', 'npm run deploy', 'test_tile_rows', 'src/app.py'):
        check(S.specific(n), f'{n} is')
    for n in ('slots', 'name', 'web', '_private', 'a_b', 'Config'):
        check(not S.specific(n), f'{n} is not')
    eq([S.specific_file(n) for n in ('tile_sheet.py', 'gate.py', 'config.py', 'README.md', '__init__.py', 'index.html')],
       [True, True, False, False, False, False], 'files')
    eq([S.sort_of(f) for f in ('a/b.py', 'x.toml', 'Makefile', '.github/workflows/x.yml', 'docs/a.md', 'GLOSSARY.md',
                               'plan/LESSONS.md', '.gitignore', 'a.svg', 'requirements.txt', 'run')],
       ['code', 'config', 'config', 'CI', 'docs', 'glossary', 'lessons', 'other', 'other', 'config', 'code'], 'sorts')


def test_path_at() -> None:
    print('when a line that holds the path names the removed file')
    files = {'sub/src/a_b.py', 'lib/src/a_b.py'}
    for line, place, want in (('open("src/a_b.py")', 'x.py', 'dead'), ('run: ./src/a_b.py', 'x.yml', 'dead'),
                              ('$ROOT/src/a_b.py', 'x.sh', 'dead'), ('${{ x }}/src/a_b.py', 'x.yml', 'dead'),
                              ('$(pwd)/src/a_b.py', 'x.sh', 'dead'), ('"../src/a_b.py"', 'tests/x.py', 'dead'),
                              ('"src/a_b.py"', 'sub/x.py', ''), ('lib/src/a_b.py', 'x.py', ''),
                              ('https://x.test/src/a_b.py', 'x.py', 'other'), ('other/src/a_b.py', 'x.py', 'other')):
        at = line.index('src/a_b.py')
        eq(S.path_at(line, at, 'src/a_b.py', place, files), want, f'{line} in {place}')
    eq([list(S.spots('a_b.py', l)) for l in ('a_b.pyc', 'xa_b.py', 'a_b.py.bak', 'a_b.py.', '`a_b.py`')],
       [[], [], [], [0], [1]], 'whole words')


def test_nothing_removed() -> None:
    print('no noise on a diff that removes nothing')
    p = proj()
    p.write('src/app.py', FILES['src/app.py'] + 'SEE = "src/never_there.py"\n')
    p.write('docs/new.md', 'See src/tile_sheet.py, tile_size, bake-sheet.\n')
    out = p.passes('a change and an addition')
    check('named' not in out, 'nothing said', out)
    git(p.root, 'checkout', '-q', '-b', 'task/F2')
    (p.root / 'src/tile_sheet.py').unlink()
    (p.root / 'docs/new.md').unlink()
    r = p.done(tid='F2')
    check(r.returncode == 0 and 'named' not in r.stdout + r.stderr, 'a removal nothing names says nothing',
          r.stdout + r.stderr)


def test_dead_path() -> None:
    print('a dead path in code, config or CI refuses')
    for place, text in (('src/use.py', 'open("src/tile_sheet.py")\n'), ('more.toml', 'file = "src/tile_sheet.py"\n'),
                        ('.github/workflows/ci.yml', 'name: ci\nrun: python3 src/tile_sheet.py\n')):
        p = proj(more={place: text})
        (p.root / 'src/tile_sheet.py').unlink()
        n = 2 if 'ci.yml' in place else 1
        p.refused(place, rf'{re.escape(place)}:{n} names file `src/tile_sheet.py` \(removed\)', 'a dead path')
        p.refused('an answer does not help', 'a dead path', more=('--named', 'kept because I say so'))
        r = p.done('--blocked', 'a wall')
        check(r.returncode == 0, 'a block is not checked', r.stdout + r.stderr)
    p = proj(more={'src/use.py': 'open("src/tile_sheet.py")\n'})
    (p.root / 'src/tile_sheet.py').unlink()
    p.refused('first')
    p.write('src/use.py', 'pass\n')
    p.passes('once it is fixed')


def test_folder_and_import() -> None:
    print('a folder that is gone, an import, two files of one name')
    p = proj(more={'tests/tiles/test_big_tiles.py': 'x = 1\n', '.github/workflows/ci.yml': 'name: ci\nrun: pytest tests/tiles/\n',
                   'src/use.py': 'import src.tile_sheet\n', 'a/one_thing.sh': 'echo a\n', 'b/one_thing.sh': 'echo b\n',
                   'docs/a.md': 'b/one_thing.sh and one_thing.sh\n', 'src/route.py': 'get("tests/tiles/")\n'})
    for f in ('tests/tiles/test_big_tiles.py', 'src/tile_sheet.py', 'a/one_thing.sh', 'b/one_thing.sh'):
        (p.root / f).unlink()
    err = p.refused('both are dead paths', r'CI .*ci\.yml:2 names folder `tests/tiles`',
                    r'src/use\.py:1 names file `src/tile_sheet.py`')
    check('route.py' not in err, 'a folder named in code is only listed', err)
    p.write('.github/workflows/ci.yml', 'name: ci\n')
    p.write('src/use.py', 'pass\n')
    p.refused('the rest', r'src/route\.py:1 names folder', r'names file `a/one_thing\.sh`|names file `b/one_thing\.sh`')


def test_rename() -> None:
    print('a rename')
    p = proj(more={'src/use.py': 'open("src/tile_sheet.py")\n', 'docs/a.md': 'See `tile_sheet.py`.\n'})
    git(p.root, 'mv', 'src/tile_sheet.py', 'src/atlas_sheet.py')
    p.refused('the old path in code', r'src/use.py:1 names file `src/tile_sheet.py` \(renamed to `src/atlas_sheet.py`\)')
    p.write('src/use.py', 'open("src/atlas_sheet.py")\n')
    p.refused('its name in docs', r'1\. docs docs/a\.md:1 names file `src/tile_sheet.py` \(renamed to')
    p.write('docs/a.md', 'See `atlas_sheet.py`.\n')
    p.passes('all fixed, with no answer')
    p = proj(more={'docs/a.md': 'See `tile_sheet.py`.\n'})
    git(p.root, 'mv', 'src/tile_sheet.py', 'tile_sheet.py')
    p.passes('a file moved is still named by its name')


def test_kinds() -> None:
    print('a test, a setting, a command')
    docs = ('tile_size, APP_HOME_DIR, `bake-sheet`, test_tile_rows; npm run deploy; but draw, name, start and left-pad '
            'are too common or no command\n')
    p = proj(more={'docs/a.md': docs})
    p.write('app.toml', '[app]\n')
    p.write('src/app.py', 'pass\n')
    p.write('src/cli.py', 'pass\n')
    p.write('package.json', '{"scripts": {}}\n')
    p.write('tests/test_tiles.py', 'def test_tile_edges():\n    pass\n')
    err = p.refused('each', *(rf'docs docs/a\.md:1 names {k} \(removed\)' for k in (
        'setting `tile_size`', 'setting `APP_HOME_DIR`', 'command `bake-sheet`', 'command `npm run deploy`',
        'test `test_tile_rows`')))
    eq(len(re.findall(r'^  \d+\. ', err, re.M)), 5, 'and no other')

    p = proj(more={'docs/a.md': docs})
    p.write('app.toml', '[app]\n')
    p.write('settings/more.toml', '[app]\ntile_size = 4\n')
    p.write('tests/test_tiles.py', 'def test_tile_edges():\n    pass\n')
    p.write('tests/test_rows.py', 'def test_tile_rows():\n    pass\n')
    p.passes('moved to another file, none is removed')

    p = proj(more={'src/latest_config.py': 'D = {"tile_width": 4}\n', 'prod.toml': 'tile_width = 5\n',
                   'src/inspector_cli.py': 'p.add_parser("draw-all")\np.add_argument("-t", "--tile-flag")\n',
                   'docs/a.md': 'tile_width, draw-all, --tile-flag\n'})
    p.write('src/latest_config.py', 'D = {}\n')
    p.write('src/inspector_cli.py', 'pass\n')
    p.refused('a config file that still sets it hides nothing', r'docs docs/a\.md:1 names setting `tile_width`',
              r'config prod\.toml:1 names setting `tile_width`', r'names command `draw-all`', r'names setting `--tile-flag`')
    p = proj(more={'lib/app.toml': 'tile_size = 9\n', 'docs/a.md': 'tile_size\n'})
    p.write('app.toml', '[app]\n')
    p.passes('a setting another config file still has')


def test_places() -> None:
    print('docs, glossary, lessons, open tasks, memories; and what is history')
    say = 'See src/tile_sheet.py.\n'
    p = proj(more={'docs/a.md': say, 'GLOSSARY.md': say, 'plan/LESSONS.md': say, 'plan/tasks/F3.md': say,
                   'plan/tasks/F9.md': say, 'CHANGELOG.md': say, 'docs/research/r.md': say},
             tasks='- [ ] **F4** use src/tile_sheet.py | files: src/tile_sheet.py\n',
             done='- [x] **F9** made src/tile_sheet.py\n')
    p.write('plan/TODO.md', (p.root / 'plan/TODO.md').read_text().replace('job F1', 'remove src/tile_sheet.py'))
    d = p.claude / 'projects' / re.sub(r'[^A-Za-z0-9]', '-', str(p.root.resolve())) / 'memory'
    d.mkdir(parents=True)
    (d / 'sheet.md').write_text(say, encoding='utf-8')
    (p.root / 'src/tile_sheet.py').unlink()
    err = p.refused('a list', r'docs docs/a\.md:1 ', r'glossary GLOSSARY\.md:1 ', r'lessons plan/LESSONS\.md:1 ',
                    r'open task F3 ', r'open task F4 ', r'memory .*sheet\.md ')
    eq(len(re.findall(r'^  \d+\. ', err, re.M)), 6, 'not the changelog, findings, DONE.md, a closed or its own task')


def test_ci_tasks() -> None:
    print('an open auto-filed CI task for a removed test or workflow')
    p = proj(tasks='- [ ] **B5** CI: `Nightly` on main is red (failure, run 1): failed x. (filed 2026-11-20) u | files: x\n'
                   '- [ ] **B6** make the test `t/test_rows.py::test_tile_rows` robust: it raced (filed 2026-11-20)\n'
                   '- [ ] **B7** CI: `ci` on main is red (failure, run 2): failed x. (filed 2026-11-20) u | files: x\n'
                   '- [x] **B8** CI: `Nightly` on main is red (failure, run 1) (filed 2026-11-10)\n')
    (p.root / '.github/workflows/nightly.yml').unlink()
    p.write('tests/test_tiles.py', 'def test_tile_edges():\n    pass\n')
    err = p.refused('both', r'open auto-filed CI task B5 names workflow `Nightly`',
                    r'open auto-filed CI task B6 names test `test_tile_rows`')
    eq(len(re.findall(r'^  \d+\. ', err, re.M)), 2, 'no other')
    p = proj(tasks='- [ ] **B5** CI: `Nightly` on main is red (failure, run 1): failed x. (filed 2026-11-20) u\n')
    git(p.root, 'mv', '.github/workflows/nightly.yml', '.github/workflows/night.yml')
    p.passes('a workflow whose name stays')


def test_answers() -> None:
    print('the list is answered once')
    say = 'See src/tile_sheet.py.\n'
    p = proj(more={'docs/a.md': say, 'docs/b.md': say, 'docs/c.md': say})
    (p.root / 'src/tile_sheet.py').unlink()
    p.refused('an answer before the list was shown', r'3\. ', more=('--named', 'all kept because x'))
    p.refused('a bad answer', 'does not read', more=('--named', 'whatever'))
    p.refused('a number not there', 'does not read', more=('--named', '4 kept because x'))
    p.refused('no reason', 'does not read', more=('--named', 'kept because '))
    p.refused('a task that is not', 'no open task B99', more=('--named', 'filed B99'))
    p.refused('fixed that is not', 'answered fixed, but still named', more=('--named', '1 fixed; 2 filed F2; 3 fixed'))
    err = p.refused('only what is left', r'1\. docs docs/a\.md', r'2\. docs docs/c\.md')
    check('docs/b.md' not in err, 'the answered one is off the list', err)
    p.write('docs/c.md', 'x\n')
    p.refused('c is fixed', r'1\. docs docs/a\.md')
    p.write('gate.py', 'raise SystemExit(1)\n')
    r = p.done('--named', 'kept because it is told; see the page')
    check(r.returncode == 1 and 'gate failed' in r.stderr, 'answered: on to the gate', r.stdout + r.stderr)
    has(r.stdout, r'docs/a\.md:1 .*: kept because it is told; see the page', 'and says the answers')
    has(r.stdout, r'docs/b\.md:1 .*: filed F2', 'all of them')
    p.write('gate.py', 'pass\n')
    p.write('docs/d.md', say)
    p.refused('only a new one is asked', r'1\. docs docs/d\.md')
    p.passes('answered', '--named', 'all kept because of it')


def test_ignored_and_stacked() -> None:
    print('a file that is ignored now, and a merge it was started on')
    p = proj(more={'src/use.py': 'open("src/tile_sheet.py")\n'})
    p.write('.gitignore', '.runner/\nsrc/tile_sheet.py\n')
    git(p.root, 'rm', '-q', '--cached', 'src/tile_sheet.py')
    p.passes('it is made, not removed')

    p = proj(more={'docs/a.md': 'See src/tile_sheet.py.\n'})
    git(p.root, 'rm', '-q', 'src/tile_sheet.py')
    git(p.root, 'commit', '-qm', 'F2: the other task removed it')
    on = git(p.root, 'rev-parse', 'HEAD').strip()
    p.refused('its own removal', r'docs/a\.md')
    (p.root / '.runner' / 'F1.stacked').write_text(json.dumps({'on': on, 'tids': ['F2']}), encoding='utf-8')
    p.write('docs/b.md', 'x\n')
    p.passes('not the one of the merge it started on')


if __name__ == '__main__':
    raise SystemExit(report([test_names, test_path_at, test_nothing_removed, test_dead_path, test_folder_and_import, test_rename, test_kinds,
                             test_places, test_ci_tasks, test_answers, test_ignored_and_stacked]))
