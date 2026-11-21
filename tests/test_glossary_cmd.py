"""F22: `agent-runner glossary` keeps a project's GLOSSARY.md (person's word, on-screen wording, code names, a
definition and the words to avoid) and commits it like a plan edit; the control brief seeds one and adds terms
without asking; the slot prompt names it; `[plan] glossary = false` turns it all off."""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace

from _check import FAILED, check, eq, git, run

from agent_runner import brief, glossary, guide


def repo(toml: str = '') -> Path:
    d = Path(tempfile.mkdtemp(prefix='agent-runner-glossary-'))
    git(d, 'init', '-q')
    (d / 'app').mkdir()
    (d / 'app' / 'board.py').write_text('def render_board():\n    return "<h1>Board</h1>"\n\n'
                                        '@app.get("/board")\ndef board_page():\n    pass\n')
    (d / '.gitignore').write_text('.runner/\n')
    if toml:
        (d / 'runner.toml').write_text(toml)
    git(d, 'add', '-A')
    git(d, 'commit', '-qm', 'start')
    return d


def subjects(d: Path) -> list[str]:
    return git(d, 'log', '--format=%s').splitlines()


print('a repo without GLOSSARY.md gets one on the first add, committed')
d = repo()
r = run(d, 'glossary', 'add', 'Board', '--said', 'the list', '--ui', 'Board', '--code', 'render_board(), board.py',
        '--means', 'The screen that lists every task.', '--avoid', 'list, page', stdin=subprocess.DEVNULL)
check(r.returncode == 0, 'add exits 0', r.stderr)
check('added the list = Board' in r.stdout, 'it says what it added, in passing', r.stdout)
g = d / 'GLOSSARY.md'
check(g.is_file(), 'GLOSSARY.md is made')
text = g.read_text()
for line in ('**Board**:', 'The screen that lists every task.', '_Said_: the list', '_On screen_: Board',
             '_In code_: render_board(), board.py', '_Avoid_: list, page'):
    check(line in text, f'the entry holds {line!r}')
check('glossary add Board' in subjects(d)[0], 'the add is committed at once', subjects(d)[0])
eq(git(d, 'status', '--porcelain', '--', 'GLOSSARY.md'), '', 'nothing left uncommitted')

print('show finds an entry by any of its names; add again replaces it in place')
r = run(d, 'glossary', 'show', 'list')
check(r.returncode == 0 and '**Board**' in r.stdout, '`show list` finds Board by the person\'s word', r.stdout + r.stderr)
r = run(d, 'glossary', 'Board')
check('_On screen_: Board' in r.stdout, 'bare `glossary TERM` shows it too')
run(d, 'glossary', 'add', 'Task', '--means', 'One piece of queued work.', '--avoid', 'ticket')
run(d, 'glossary', 'add', 'board', '--ui', 'Board', '--means', 'The screen of every task, open and done.')
text = g.read_text()
eq(text.count('**Board**'), 1, 'one Board entry, not two')
check('open and done' in text and text.index('**Board**') < text.index('**Task**'), 'replaced where it stood')
eq(glossary.parse(text)['Board']['said'], '', 'its fields are the new ones')

print('forget removes an entry and commits')
r = run(d, 'glossary', 'forget', 'Task')
check(r.returncode == 0, 'forget exits 0', r.stderr)
check('**Task**' not in g.read_text() and '**Board**' in g.read_text(), 'Task is gone, Board stays')
check('glossary forget Task' in subjects(d)[0], 'committed')
check(run(d, 'glossary', 'forget', 'Nope').returncode != 0, 'forgetting an unknown term fails')

print('seed writes a starter glossary with no prompt, in one commit')
d2 = repo()
seedf = d2.parent / f'{d2.name}-seed.json'
seedf.write_text(json.dumps([
    {'term': 'Board', 'said': 'the list', 'ui': 'Board', 'code': 'render_board()', 'means': 'Every task on one screen.',
     'avoid': 'list'},
    {'term': 'Task', 'means': 'One piece of queued work.', 'avoid': 'ticket'},
    {'term': 'Nothing', 'means': ''},  # no definition: skipped
]))
before = len(subjects(d2))
r = run(d2, 'glossary', 'seed', str(seedf), stdin=subprocess.DEVNULL)
check(r.returncode == 0, 'seed exits 0 without any input', r.stderr)
eq(sorted(glossary.parse((d2 / 'GLOSSARY.md').read_text())), ['Board', 'Task'], 'both terms written')
eq(len(subjects(d2)), before + 1, 'one commit')
r = run(d2, 'glossary', 'seed', '-', input=json.dumps([{'term': 'Board', 'means': 'other'},
                                                       {'term': 'Gate', 'means': 'The test command.'}]))
text = (d2 / 'GLOSSARY.md').read_text()
check('Every task on one screen.' in text and '**Gate**' in text, 'a second seed keeps what is there, adds the rest')

print('scan lists the UI strings and code names, and greps a word')
r = run(d2, 'glossary', 'scan')
for want in ('## UI strings', 'Board', 'app/board.py', 'render_board', '/board'):
    check(want in r.stdout, f'scan shows {want!r}', r.stdout)
r = run(d2, 'glossary', 'scan', 'render_board')
check('app/board.py:1:' in r.stdout, 'scan WORD shows where it is', r.stdout)

print('[plan] glossary = false: no file written, the briefs skip it')
d3 = repo('[plan]\nglossary = false\n')
r = run(d3, 'glossary', 'add', 'Board', '--means', 'The screen.')
check(r.returncode == 0, 'add exits 0', r.stderr)
check('off' in r.stdout and not (d3 / 'GLOSSARY.md').exists(), 'nothing written', r.stdout)
r = run(d3, 'glossary', 'seed', '-', input='[{"term": "Board", "means": "x"}]')
check(not (d3 / 'GLOSSARY.md').exists(), 'seed writes nothing either')
off = SimpleNamespace(raw={'plan': {'glossary': False}}, root=d3)
control = guide.CONTROL.format(cmd='agent-runner', repo='demo', needs='Needs you', watch='', answer='', log='run.log')
fitted = glossary.fit(control, 'control', 'agent-runner', off)
check(guide.GLOSSARY not in fitted and 'glossary add' not in fitted, 'the control brief says nothing of it')
fitted = glossary.fit(brief.PROMPT, 'slot', 'agent-runner', off)
check(guide.GLOSSARY not in fitted and 'glossary add' not in fitted, 'nor the slot prompt')

print('the control brief: seed straight away when there is none, add new terms without asking')
on = SimpleNamespace(raw={'plan': {'glossary': 'GLOSSARY.md'}}, root=d3)
fitted = glossary.fit(control, 'control', 'agent-runner', on)
check(guide.GLOSSARY in fitted, 'it keeps the glossary line')
check('agent-runner glossary seed' in fitted and 'Do not ask first' in fitted, 'no glossary yet: seed it, unasked')
check('Never ask the person about it' in fitted and 'add it at once' in fitted, 'a new term is added, unasked')
check('in passing' in fitted, 'and mentioned only in passing')
check('glossary forget' in fitted, '"forget X" undoes one')
check('offer once to queue a' in fitted and 'only on yes' in fitted, 'a rename is offered, not queued silently')
check('"what?"' in fitted, '"what?" is said again in glossary terms')
check('docs/adr/' in fitted and 'hard to reverse' in fitted, 'an ADR only for a hard-to-reverse choice')
on_d = SimpleNamespace(raw={'plan': {'glossary': 'GLOSSARY.md'}}, root=d)
check('glossary seed' not in glossary.fit(control, 'control', 'agent-runner', on_d), 'with a glossary: no seed ask')
custom = SimpleNamespace(raw={'plan': {'glossary': 'docs/TERMS.md'}}, root=d3)
fitted = glossary.fit(control, 'control', 'agent-runner', custom)
check('docs/TERMS.md' in fitted and 'GLOSSARY.md' not in fitted, 'a configured path is named instead')

print('the slot prompt: name new things with its terms, add new ones')
fitted = glossary.fit(brief.PROMPT, 'slot', 'agent-runner', on)
check('agent-runner glossary add' in fitted and 'name new things' in fitted, 'the slot prompt carries it')
check(run(d, 'settings').stdout.count("glossary = \"GLOSSARY.md\"") == 1, '`settings` lists [plan] glossary')

raise SystemExit(1 if FAILED else print('\nall checks passed'))
