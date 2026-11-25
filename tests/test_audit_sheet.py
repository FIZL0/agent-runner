#!/usr/bin/env python3
"""F418: an audit fixes dead references alone, asks the rest on one pick sheet, and carries out the answers.

    python3 tests/test_audit_sheet.py        (no network; a few seconds of git)
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from _check import check, eq, git, has, report, run

from agent_runner import audit as A, audit_fix as X, brief, merge, plan as P, runner as R, sheet, stale, state as S  # noqa: E402

GUIDE = ('# Guide\n\nThe parser is in `src/old_parser.py`. It reads\nlabels.\n\nRun `frob_labels` to start. Keep this one.\n\n'
         '- [the map](old_map.md)\n- `src/lexer.py` splits words\n')
GLOSS = '# Glossary\n\n**Label**:\nA name on a box.\n_In code_: frob_labels, split_words\n'
TASKS = ['R7** (audit) look | files: plan/audits/**', 'T1** a stale task | files: src/lexer.py', 'T2** another | files: src/lexer.py']


def project(tmp: Path, toml: str = '') -> tuple[Path, Path, dict]:
    """A repository whose `frob_labels`, src/old_parser.py and docs/old_map.md are gone, and R7's worktree."""
    tmp = Path(tempfile.mkdtemp(dir=tmp))
    repo, wt = tmp / 'repo', tmp / 'wt'

    def put(f, text):
        (repo / f).parent.mkdir(parents=True, exist_ok=True)
        (repo / f).write_text(text, encoding='utf-8')
    git(tmp, 'init', '-q', '-b', 'main', str(repo))
    put('src/old_parser.py', 'def frob_labels(): pass\n')
    put('docs/old_map.md', 'a map\n')
    put('src/lexer.py', 'def split_words(): pass\n')
    put('docs/guide.md', GUIDE)
    put('GLOSSARY.md', GLOSS)
    put('plan/lessons.md', '- `frob_labels` is slow.\n- Boxes are heavy.\n')
    put('CHANGELOG.md', '- Added `frob_labels`.\n')
    put('plan/TODO.md', '# TODO\n\n### Next\n\n' + ''.join(f'- [ ] **{t}\n' for t in TASKS))
    put('plan/DONE.md', '# DONE\n')
    put('runner.toml', f'[run]\ntest = "true"\nmin_free_gb = 0\nremote = false\n{toml}')
    put('.gitignore', '.runner/\n')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'start')
    git(repo, 'rm', '-q', 'src/old_parser.py', 'docs/old_map.md')
    put('src/new_parser.py', 'def read_labels(): pass\n')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'a new parser')
    git(repo, 'worktree', 'add', '-q', '-b', 'task/R7', str(wt), 'main')
    R.init(repo)
    env = {**os.environ, 'AGENT_RUNNER_REPO': str(wt)}
    return repo, wt, env


def questions(n: int, **over) -> dict:
    one = {'answers': ['Drop it', 'Keep it'], 'recommended': 0, 'keep': 1, 'why': 'T9 did it.', **over}
    return {'title': 'R7 audit', 'summary': f'{n} findings to decide',
            'groups': [{'heading': 'Tasks', 'questions': [{'id': f'q{i}', 'q': f'Drop T{i}?',
                                                           **{k: v for k, v in one.items() if v is not None}} for i in range(1, n + 1)]}]}


def write_sheet(spec: dict):
    f = R.C.notes('sheets', 'R7.json')
    f.write_text(json.dumps(spec), encoding='utf-8')
    return f


def edit(wt: Path, f: str, old: str, new: str):
    p = wt / f
    text = p.read_text(encoding='utf-8')
    check(old in text, f'{f} has {old[:30]!r}')
    p.write_text(text.replace(old, new), encoding='utf-8')


def findings(wt: Path, text: str = 'Audited: start..x\n'):
    f = wt / 'plan/audits/R7.md'
    f.parent.mkdir(exist_ok=True)
    f.write_text(text, encoding='utf-8')


def refused(wt: Path, env: dict, *a) -> str:
    r = run(wt, 'done', 'R7', 'R7 audit', *a, env=env)
    check(r.returncode == 2 and not git(wt, 'log', '--format=%h', 'main..HEAD'), 'done refuses, nothing committed', r.stderr + r.stdout)
    return r.stderr


def limit(wt: Path) -> dict:
    """What the merge would say of the worktree's content, taken back afterwards."""
    git(wt, 'add', '-A')
    git(wt, 'commit', '-qm', 'R7 try', '--allow-empty')
    base = git(wt, 'merge-base', 'main', 'HEAD')
    bad = X.problems(S.C, base, 'task/R7', 'R7', False)
    eq(sorted(merge.research_code('R7', 'main')), sorted(bad), 'the merge reads the same')
    git(wt, 'reset', '-q', '--hard', 'main')
    return bad


def test_fixes(tmp: Path):
    print('dead references in docs, the glossary and lessons land')
    _, wt, _ = project(tmp)
    findings(wt)
    edit(wt, 'docs/guide.md', 'src/old_parser.py', 'src/new_parser.py')
    edit(wt, 'docs/guide.md', 'It reads\nlabels.', 'It\nreads labels.')
    edit(wt, 'docs/guide.md', 'Run `frob_labels` to start. ', '')
    edit(wt, 'docs/guide.md', '- [the map](old_map.md)\n', '')
    edit(wt, 'GLOSSARY.md', 'frob_labels, split', 'read_labels, split')
    edit(wt, 'plan/lessons.md', '- `frob_labels` is slow.\n', '')
    eq(limit(wt), {}, 'within the limit')


def test_limit(tmp: Path):
    print('the fix limit is enforced on the diff')
    _, wt, env = project(tmp)
    for f, old, new, why in (
            ('docs/guide.md', 'Run `frob_labels` to start. Keep this one.', '', 'names nothing that is gone: "Keep this one'),
            ('docs/guide.md', 'Keep this one.', 'Keep that one.', 'names nothing that is gone'),
            ('docs/guide.md', '# Guide', '# Guide\n\nA new `src/lexer.py` line.', 'it adds'),
            ('docs/guide.md', '`frob_labels` to start', '`frob_labels` to begin', 'still names frob_labels'),
            ('docs/guide.md', '`frob_labels` to start', '`read_labels` quickly', 'the words quickly'),
            ('docs/guide.md', 'src/old_parser.py', 'src/none.py', 'the words none'),
            ('docs/guide.md', '`src/lexer.py` splits words', 'words', 'names nothing that is gone'),
            ('docs/guide.md', '\n\nRun', '\n\n\nRun', 'only its spacing'),
            ('GLOSSARY.md', 'A name on a box.', 'A name.', 'names nothing that is gone'),
            ('plan/lessons.md', '- Boxes are heavy.\n', '', 'names nothing that is gone'),
            ('CHANGELOG.md', '- Added `frob_labels`.\n', '', 'not a doc'),
            ('src/lexer.py', 'pass', 'return', 'not a doc'),
            ('runner.toml', 'min_free_gb = 0', 'min_free_gb = 1', 'not a doc'),
            ('plan/TODO.md', 'a stale task', 'an edited task', 'changes T1 before'),
            ('plan/TODO.md', '- [ ] **T1** a stale task | files: src/lexer.py\n', '', 'changes T1 before'),
            ('plan/TODO.md', '- [ ] **T1**', '- [ ] **T9** a new one\n- [ ] **T1**', 'changes T9 before')):
        edit(wt, f, old, new)
        bad = limit(wt)
        check(list(bad) == [f] and why in bad[f], f'{f}: {why}', bad)
    (wt / 'docs/new.md').write_text('x\n')
    (wt / 'plan/tasks').mkdir()
    (wt / 'plan/tasks/T1.md').write_text('x\n')
    os.remove(wt / 'GLOSSARY.md')
    eq(sorted(limit(wt)), ['GLOSSARY.md', 'docs/new.md', 'plan/tasks/T1.md'], 'a file added or deleted')
    findings(wt)
    edit(wt, 'src/lexer.py', 'pass', 'return')
    has(refused(wt, env), r'fix limit.*\n  src/lexer\.py: not a doc', 'done says which file and why')
    has(refused(wt, env, '--blocked', 'CONFIRM: look'), r'src/lexer\.py', 'blocked too, as that lands')


def test_sheet(tmp: Path):
    print('one pick sheet, at most 10 questions, each with a recommendation, why and keep')
    _, wt, env = project(tmp)
    findings(wt)
    f = write_sheet(questions(11))
    try:
        sheet.load(f)
        check(False, '11 are refused')
    except ValueError as e:
        has(str(e), '11 questions: an audit asks at most 10', '11 are refused')
    check(run(wt, 'sheet', 'R7', env=env).returncode == 1, 'by the command too')
    ask = ('--blocked', 'DECIDE: 11 findings to decide')
    has(refused(wt, env, *ask), 'at most 10', 'and by done')
    for k in ('recommended', 'keep', 'why'):
        write_sheet(questions(2, **{k: None}))
        has(refused(wt, env, *ask), f'question q1: no "{k}"', f'no {k}')
    has(refused(wt, env), 'pick sheet that is not asked', 'one that is written is asked')
    f.unlink()
    has(refused(wt, env, *ask), 'pick sheet alone', 'no DECIDE without it')
    other = f.with_name('T1.json')
    other.write_text(json.dumps(questions(11, keep=None)), encoding='utf-8')
    eq(len(sheet.questions(sheet.load(other))), 11, "another task's sheet is as before")
    r = run(wt, 'done', 'R7', 'R7 audit', env=env)
    check(r.returncode == 0, 'nothing found: no sheet, just done', r.stderr)
    _, wt, env = project(tmp, 'questionnaires = false\n')
    has(A.prompt('R7', 'main', wt), 'ask nothing', 'pick sheets off: it asks nothing')


def test_answer(tmp: Path):
    print('an answer is carried out')
    repo, wt, env = project(tmp)
    git(wt, 'branch', '-q', 'before')
    said = brief.prompt_for('R7', 1, 1, wt, 'main')
    for w in ('dead references in docs', 'at most 10 questions', 'Nothing to ask: no sheet'):
        check(w in ' '.join(said.split()), w)
    findings(wt, 'Audited: start..x\n\n- T1 is stale [q1]: `plan drop T1`\n')
    edit(wt, 'docs/guide.md', 'src/old_parser.py', 'src/new_parser.py')
    write_sheet(questions(10))
    r = run(wt, 'done', 'R7', 'R7 audit', '--blocked', 'DECIDE: 10 findings to decide https://claude.ai/x', env=env)
    eq(r.returncode, 0, 'it blocks on its sheet')
    eq(merge.research_code('R7', 'main'), [], 'its file and fix merge')
    git(repo, 'merge', '-q', '--no-ff', '-m', 'part', 'task/R7')
    eq(A.answered('R7', P.lines(repo / 'plan/TODO.md')), False, 'not answered yet')
    r = run(repo, 'sheet', 'R7', '--picks', 'R7 picks: q2=b', env={**env, 'AGENT_RUNNER_REPO': str(repo)})
    eq(r.returncode, 0, 'the picks are sent')
    git(repo, 'commit', '--allow-empty', '-qam', 'answered')
    check(A.answered('R7', P.lines(repo / 'plan/TODO.md')), 'answered')
    git(wt, 'checkout', '-q', '-B', 'task/R7', 'main')
    said = ' '.join(brief.prompt_for('R7', 1, 1, wt, 'main').split())
    for w in ('carry out the answers', 'plan/audits/R7.md', 'audit no more', 'q1 (Drop T1?): Drop it (recommended)',
              'q2 (Drop T2?): Keep it'):
        check(w in said, w)
    check('Audited: ' not in said.split('Project policies')[0].split('R7 is an audit')[1], 'not the audit again')
    for argv in (('drop', 'T1', 'stale'), ('edit', 'T2', 'another, edited', '--files', 'src/lexer.py'),
                 ('add', 'T', 'remove the unused splitter', '--files', 'src/lexer.py', '--force')):
        r = run(wt, 'plan', *argv, env=env)
        check(r.returncode == 0, f'plan {argv[0]}', r.stderr)
    edit(wt, 'src/lexer.py', 'pass', 'return')
    has(refused(wt, env), r'src/lexer\.py', 'code is still a task')
    edit(wt, 'src/lexer.py', 'return', 'pass')
    r = run(wt, 'done', 'R7', 'R7 carried out', env=env)
    eq(r.returncode, 0, 'done' + r.stderr)
    eq(merge.research_code('R7', 'main'), [], 'the drop, the edit and the task merge')
    git(repo, 'merge', '-q', '--no-ff', '-m', 'R7', 'task/R7')
    todo, done = ((repo / f'plan/{f}.md').read_text() for f in ('TODO', 'DONE'))
    check('**T1**' not in todo and 'dropped: stale' in done and 'another, edited' in todo and 'unused splitter' in todo, 'they landed', todo)
    ask = [f'- [ ] **R7** (audit) x — your answer (DECIDE {w}): yes' for w in ('y? ' + P.RESEARCH_BUTTONS, 'drop?')]
    eq([A.answered('R7', [l]) for l in ask], [False, True], "the merge's own question is another one; words are an answer")
    eq(stale.sort_of('plan/lessons.md'), 'lessons', 'lessons are lessons')


def in_tmp(f):
    def go():
        with tempfile.TemporaryDirectory() as d:
            f(Path(d))
    go.__name__ = f.__name__
    return go


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(f) for f in (test_fixes, test_limit, test_sheet, test_answer)]))
