#!/usr/bin/env python3
"""T31: the runner joins a conflict in the glossary by entry, on real git merges and with no setting.

    python3 tests/test_glossary_join.py        (no network; a few seconds of git)
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

from _check import ROOT, check, eq, git, report

from agent_runner import glossary as G  # noqa: E402
from agent_runner import join as J  # noqa: E402
from agent_runner import merge as M  # noqa: E402
from agent_runner import runner as R  # noqa: E402


def entry(term: str, means: str = '', avoid: str = 'x') -> str:
    return f'**{term}**:\n{means or "What " + term + " is."}\n_Avoid_: {avoid}\n'


BASE = ('# Proj\n\nThe words.\n\n## Language\n\n### Work\n\n' + entry('Task') + '\n' + entry('Gate')
        + '\n### Run\n\n' + entry('Slot') + '\n' + entry('Run'))


def after(text: str, term: str, new: str) -> str:
    """`text` with the entry `new` right after `term`'s."""
    old = G.render(term, G.parse(text)[term])
    return text.replace(old, old + '\n\n' + new.rstrip('\n'), 1)


def merged(tmp: Path, ours, theirs, base: str | None = BASE, toml: str = '', name: str = 'GLOSSARY.md'):
    """(the conflicted files, whether the runner joined them, the file after) of a merge of two branches."""
    repo = Path(tempfile.mkdtemp(dir=tmp)) / 'proj'
    (repo / 'plan').mkdir(parents=True)
    git(repo, 'init', '-q', '-b', 'main')
    (repo / 'plan/TODO.md').write_text('# TODO\n', encoding='utf-8')
    (repo / 'plan/DONE.md').write_text('# DONE\n', encoding='utf-8')
    (repo / 'runner.toml').write_text(toml or '[run]\nremote = false\n', encoding='utf-8')
    (repo / '.gitignore').write_text('.runner/\n', encoding='utf-8')
    p = repo / name
    if base is not None:
        p.write_text(base, encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'start')
    for b, text in (('task/A', ours), ('task/B', theirs)):
        git(repo, 'checkout', '-q', '-b', b, 'main')
        p.write_text(text, encoding='utf-8')
        git(repo, 'add', '-A')
        git(repo, 'commit', '-qm', b)
    git(repo, 'checkout', '-q', 'task/A')
    R.init(repo)
    files = M.merge_into(repo, 'task/B', 'merge', 'B1')
    ok = bool(files) and M.joined(files, 'B1', repo)
    return files, ok, p.read_text(encoding='utf-8')


def test_added(tmp: Path):
    print('two terms added at one place: both stay, once, under their own section')
    files, ok, text = merged(tmp, after(BASE, 'Gate', entry('Claim')), after(BASE, 'Gate', entry('Take')))
    eq(files, ['GLOSSARY.md'], 'the merge conflicts in the glossary')
    check(ok, 'and is joined with no setting')
    eq(list(G.parse(text)), ['Task', 'Gate', 'Claim', 'Take', 'Slot', 'Run'], 'every term once, in its section')
    eq(text, after(after(BASE, 'Gate', entry('Take')), 'Gate', entry('Claim')), 'the rest is as it was')
    end = [BASE.rstrip('\n') + '\n\n' + entry(t) for t in ('Claim', 'Take')]
    eq(list(G.parse(G.join3(BASE, *end)))[-3:], ['Run', 'Claim', 'Take'], 'and at the end of the file')


def test_sections(tmp: Path):
    print('terms and sections added on either side')
    ours, theirs = after(BASE, 'Gate', entry('Claim')), BASE + '\n### Home\n\n' + entry('Page')
    text = G.join3(BASE, ours, theirs)
    check('### Home\n\n**Page**' in text and '**Claim**' in text.split('### Run')[0], 'each under its own section')
    eq(G.join3(BASE, theirs, ours), text, 'the same the other way')
    gone = BASE[:BASE.index('\n### Run')]
    refused(BASE, gone, after(BASE, 'Run', entry('Claim')), 'a term added in a section the other side removed')
    refused(BASE, BASE.replace('The words.', 'A.'), BASE.replace('The words.', 'B.'), 'a text both sides changed')
    check('A.\n' in G.join3(BASE, BASE.replace('The words.', 'A.'), ours), "one side's change of a text is kept")
    work, run = BASE.split('\n### Run')[0], '\n### Run' + BASE.split('\n### Run')[1]
    head, body = work.split('### Work')
    moved = head + run.lstrip('\n') + '\n### Work' + body
    for a, b in ((moved, ours), (ours, moved)):
        eq(list(G.parse(G.join3(BASE, a, b))), ['Slot', 'Run', 'Task', 'Gate', 'Claim'], "one side's order is kept")


def test_one_side(tmp: Path):
    print('an entry edited or removed on one side takes that side')
    new = BASE.replace('What Gate is.\n_Avoid_: x', 'The test command.\n_Avoid_: y')
    add = after(BASE, 'Gate', entry('Claim'))
    both = after(after(new, 'Gate', entry('Take')), 'Run', entry('Page'))
    add = after(add, 'Run', entry('Home'))  # git conflicts at the end, where both added
    for what, a, b in (('ours', both, add), ('theirs', add, both)):
        files, ok, text = merged(tmp, a, b)
        check(files and ok, f'an edit on {what} beside an added term conflicts and is joined')
        eq(G.parse(text)['Gate']['means'], 'The test command.', 'the edit is kept')
        check(text.count('**Gate**') == 1 and {'Claim', 'Take', 'Page', 'Home'} <= set(G.parse(text)),
              'once, and the added terms too')
    gone = G.remove(BASE, 'Gate')
    for what, a, b in (('ours', gone, add), ('theirs', add, gone)):
        files, ok, text = merged(tmp, a, b)
        check(files and ok, f'a removal on {what} beside an added term conflicts and is joined')
        eq(list(G.parse(text)), ['Task', 'Claim', 'Slot', 'Run', 'Home'], 'the entry is gone, nothing else')
    refused(BASE, gone, new, 'an entry one side removed and the other edited')


def refused(base: str, ours: str, theirs: str, what: str):
    try:
        check(False, f'{what} is refused', G.join3(base, ours, theirs))
    except G.CannotJoin as e:
        check(True, f'{what} is refused ({e})')


def test_both(tmp: Path):
    print('one entry changed differently on both sides goes to a fix session')
    files, ok, _ = merged(tmp, after(BASE, 'Gate', entry('Claim', 'One.')), after(BASE, 'Gate', entry('Claim', 'Two.')))
    check(files and not ok, 'the same term added differently')
    refused(BASE, after(BASE, 'Gate', entry('Claim')), after(BASE, 'Slot', entry('claim')),
            'the same term added in two spellings and sections')
    refused(BASE, BASE.replace('What Run is.', 'A.'), BASE.replace('What Run is.', 'B.'), 'two edits of one entry')
    same = after(BASE, 'Gate', entry('Claim'))
    eq(G.join3(BASE, same, same), same, 'the same term added alike is there once')


def test_unparseable(tmp: Path):
    print('text that does not parse goes to a fix session')
    odd = after(BASE, 'Gate', entry('Claim') + '\nA loose line after an entry.')
    files, ok, _ = merged(tmp, odd, after(BASE, 'Gate', entry('Take')))
    check(files and not ok, 'a loose line after an entry')
    for what, bad in (('a conflict mark', BASE.replace('What Run is.', '<<<<<<< HEAD')),
                      ('a term twice', BASE + '\n' + entry('Gate')),
                      ('a term line twice', BASE.replace('**Run**:\n', '**Run**:\n**Run**:\n')),
                      ('a term with no definition', BASE + '\n**Bare**:\n'),
                      ('an entry on one line', BASE + '\n**Take**: to take.\n'),
                      ('a section twice', BASE + '\n### Run\n\n' + entry('Take')),
                      ('a # line in an entry', BASE.replace('What Run is.', 'What Run is.\n# odd')),
                      ('a code fence', BASE.replace('What Run is.', '```')),
                      ('bytes that are no text', BASE.replace('What Run is.', '�'))):
        refused(BASE, bad, BASE, f'{what} on our side')
        refused(BASE, BASE, bad, f'{what} on theirs')


def test_files(tmp: Path):
    print('which file, and a project of its own ways')
    a, b = after(BASE, 'Gate', entry('Claim')), after(BASE, 'Gate', entry('Take'))
    files, ok, text = merged(tmp, a, b, base=None)
    check(files and ok is True, 'a glossary both sides started (no base) is joined')
    eq(set(G.parse(text)), {'Task', 'Gate', 'Claim', 'Take', 'Slot', 'Run'}, 'with the terms of both')
    _, ok, _ = merged(tmp, a, b, toml='[run]\nremote = false\n[plan]\nglossary = "WORDS.md"\n', name='WORDS.md')
    check(ok, '[plan] glossary names the file')
    check(not J.joinable('GLOSSARY.md'), 'and GLOSSARY.md is then a file like any other')
    _, ok, _ = merged(tmp, a, b, toml='[run]\nremote = false\n[plan]\nglossary = false\n')
    check(not ok, 'glossary = false: no join')
    _, ok, _ = merged(tmp, a, b, toml='[run]\nremote = false\njoinable = ["*.md"]\n')
    check(ok, 'a joinable glob joins it by entry as well')
    _, ok, _ = merged(tmp, after(BASE, 'Gate', entry('Claim', 'One.')), after(BASE, 'Gate', entry('Claim', 'Two.')),
                      toml='[run]\nremote = false\njoinable = ["*.md"]\n')
    check(not ok, 'and never by line')
    _, ok, text = merged(tmp, a, b, toml='[run]\nremote = false\n[run.join]\n"*.md" = "git show :2:{file} > {out}"\n')
    check(ok and text == a, "a project's own [run.join] for it wins")
    if shutil.which('false'):
        _, ok, _ = merged(tmp, a, b, toml='[run]\nremote = false\n[run.join]\n"*.md" = "false"\n')
        check(not ok, 'also when it refuses')


def test_own_glossary(tmp: Path):
    print("this repo's own glossary parses, so its conflicts can be joined")
    text = (ROOT / 'GLOSSARY.md').read_text(encoding='utf-8')
    eq(G.parse(G.join3(text, text, text)), G.parse(text), 'joined with itself it holds what it held')


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        return report([lambda t=t: t(Path(tmp)) for t in (test_added, test_sections, test_one_side, test_both,
                                                          test_unparseable, test_files, test_own_glossary)])


if __name__ == '__main__':
    sys.exit(main())
