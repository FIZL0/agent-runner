#!/usr/bin/env python3
"""F18: pick sheets for a DECIDE with options.

    python3 tests/test_sheet.py        (no network; a few seconds, mostly git)

A DECIDE with `<notes>/sheets/<ID>.json` shows one line under Needs you and in the feed ('<summary>. Pick on the
sheet or reply go') with the sheet's link; `sheet ID --html` renders the page (questions with answers, the
recommended one preselected, a Why, a sticky bar with Send); the reply Send gives, or 'go', reopens the task
with each answer in its note; `[run] questionnaires = false` turns it off.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import tempfile
from pathlib import Path

from _check import check, eq, git, has, report, run

from agent_runner import plan as P  # noqa: E402
from agent_runner import runner as R  # noqa: E402
from agent_runner import sheet as S  # noqa: E402

URL = 'https://claude.ai/code/artifact/0000-pick'
SPEC = {
    'title': 'F2 config cleanup', 'summary': '2 config cleanups ready, 1 optional',
    'intro': 'F2 audited the config keys.',
    'groups': [
        {'heading': 'Remove keys', 'questions': [
            {'id': 'backend', 'q': 'How should the runner know which backend to use?',
             'answers': ['Work it out from `agent`', 'Keep `run.backend`'], 'recommended': 0, 'keep': 1,
             'why': 'Only two projects set it, both to the default.'}]},
        {'heading': 'Rename', 'questions': [
            {'id': 'silent', 'q': 'Rename `silent`?', 'answers': ['Keep it', 'notify', 'rc_quiet'],
             'recommended': 0, 'keep': 0, 'why': 'The name does not say what goes quiet.'}]},
    ]}


def make(tmp: Path, toml: str = '') -> tuple[Path, dict]:
    root = tmp / 'proj'
    root.mkdir()
    git(root, 'init', '-q')
    (root / 'runner.toml').write_text('[run]\nremote = false\n' + toml, encoding='utf-8')
    (root / '.gitignore').write_text('.runner/\n', encoding='utf-8')
    git(root, 'add', '-A')
    git(root, 'commit', '-qm', 'start')
    env = {**os.environ, 'AGENT_RUNNER_REPO': str(root)}
    env.pop('AGENT_RUNNER', None)
    for text in ('signing setup | files: a.py', 'config cleanup | files: b.py'):
        check(run(root, 'plan', 'add', 'F', text, env=env).returncode == 0, f'added {text}')
    return root, env


def test_spec():
    print('a sheet is questions with answers: checked, parsed, spelled out')
    eq(S.problems(SPEC), [], 'the example is a sheet')
    bad = json.loads(json.dumps(SPEC))
    bad['groups'][0]['questions'][0]['answers'] = ['only one']
    del bad['summary']
    has('; '.join(S.problems(bad)), r'no "summary".*backend: "answers" must list 2 or 3', 'says what is wrong')
    bad['groups'][0]['questions'][0]['answers'] = list('abcd')
    has('; '.join(S.problems(bad)), r'backend: "answers" must list 2 or 3', 'four answers are too many')
    try:
        S.parse_picks(SPEC, 'yes')
        check(False, "'yes' is not taken as go (it may answer another item)")
    except ValueError:
        check(True, "'yes' is not taken as go (it may answer another item)")
    eq(S.parse_picks(SPEC, 'go'), {'backend': 0, 'silent': 0}, "'go' is the recommended set")
    eq(S.parse_picks(SPEC, 'Recommended'), {'backend': 0, 'silent': 0}, "and so is 'recommended'")
    eq(S.parse_picks(SPEC, 'F2 picks: backend=b silent=c'), {'backend': 1, 'silent': 2}, "Send's reply line")
    eq(S.parse_picks(SPEC, 'silent=b'), {'backend': 0, 'silent': 1}, 'one it does not name keeps its recommended')
    for wrong in ('F2 picks: nope=a', 'backend=c', 'F2 picks: 1b 2a'):
        try:
            S.parse_picks(SPEC, wrong)
            check(False, f'{wrong!r} is refused')
        except ValueError:
            check(True, f'{wrong!r} is refused')
    eq(S.changes(SPEC, S.parse_picks(SPEC, 'go')), 1, 'the recommended set changes one thing')
    note = S.picks_note(SPEC, {'backend': 1, 'silent': 2})
    has(note, r'^picks on the sheet: backend \(How should the runner know which backend to use\?\): Keep run\.backend; '
              r'silent \(Rename silent\?\): rc_quiet$', 'each question with its answer spelled out')
    has(S.picks_note(SPEC, {}), r'Work it out from agent \(recommended\)', 'recommended ones say so')


def test_page():
    print('the page: grouped questions, answer buttons, recommended preselected, Why, sticky bar, no numbers')
    page = S.render(SPEC, 'F2')
    has(page, r'^<title>F2 config cleanup</title>', 'its title first')
    for want in ('Remove keys', 'Rename', 'How should the runner know which backend to use?', 'recommended',
                 '<summary>Why</summary>', 'changes picked', '>Recommended</button>', '>Send</button>',
                 'position:fixed', 'prefers-color-scheme: dark', 'max(16px,env(safe-area-inset-left'):
        check(want in page, f'has {want!r}')
    has(page, r'<code>agent<\\/code>', '`backticks` show as code')
    check('<html' not in page and '<body' not in page, 'no skeleton of its own (the Artifact tool adds it)')
    evil = json.loads(json.dumps(SPEC))
    evil['groups'][0]['questions'][0]['q'] = '</script><script>alert(1)</script>'
    check('<script>alert(1)' not in S.render(evil, 'F2'), 'question text is escaped')
    check(not re.search(r'>\s*\d+\s*[.)-]\s', page), 'no option numbers on the page')


def test_db():
    print('F54: Send writes {id, picks} to the page\'s artifact db; the control session reads it back')
    eq(S.CAPABILITIES, {'db': {}}, 'the page declares the db capability')
    check('wake' not in S.CAPABILITIES['db'], 'R8: no db wake list (the artifact service drops it; it wakes nothing)')
    page = S.render(SPEC, 'F2')
    has(page, re.escape("window.claude.use('db')"), 'Send opens the page\'s db')
    has(page, re.escape("db.doc('picks/'+S.tid).set({id:S.tid,picks:txt,"), 'and writes {id, picks} to picks/<ID>')
    has(page, r'navigator\.clipboard\.writeText', 'and copies the line where there is no db')
    has(page, r'Say "sent" in the chat with the run', 'and tells the person how the run hears of it')
    from agent_runner import guide as G
    has(G.topic('needs'), r'ArtifactData tool \(`get`, the\s+sheet\'s url, collection `picks`',
        'the needs guide (C2: the control brief points at it) reads the db')
    has(G.CONTROL, r'`\{cmd\} guide needs`', 'and the control brief points at it')
    has(G.FEED_ANSWER, r'ArtifactData tool \(`get`, the sheet\'s url, collection `picks`', 'and so does the feed rule')
    has(R.SHEET_PROMPT, re.escape('capabilities {{"db": {{}}}}'), 'the slot brief says to publish with the db')


def test_needs_you():
    print('a DECIDE with a sheet: one line and its link in status, the feed and the control brief')
    with tempfile.TemporaryDirectory() as t:
        root, env = make(Path(t))
        R.init(root)
        todo = R.C.todo
        P.block('F2', f'DECIDE: 2 config cleanups ready, 1 optional {URL}', todo=todo)
        text = R.status_text(False, {}, [], {}, 0.0, waiting=R.waiting_ok())
        has(text, r'reply with your answer \[F2\]', 'no sheet yet: the plain DECIDE line')
        f = R.C.notes('sheets', 'F2.json')
        f.write_text(json.dumps(SPEC), encoding='utf-8')
        check(R.has_sheet('F2'), 'has_sheet finds <notes>/sheets/F2.json')
        text = R.status_text(False, {}, [], {}, 0.0, waiting=R.waiting_ok())
        lines = text.splitlines()
        i = next((n for n, l in enumerate(lines) if '[F2]' in l), -1)
        check(i >= 0 and lines[i].endswith('2 config cleanups ready, 1 optional. Pick on the sheet or reply go [F2]'),
              'status: one line, the summary and what to do', text)
        eq(lines[i + 1:i + 2], [f'    {URL}'], 'and the sheet\'s link under it')
        line = '=== 2026-11-20T14:35:00 F2: merged, blocked'
        nl = R.needs_you_line(line, {}, dt.datetime(2026, 11, 20, 15, 0), R.waiting_ok())
        eq(nl, f'14:35  {R.ROOT.name} needs you: 2 config cleanups ready, 1 optional. Pick on the sheet or reply go [F2]  {URL}',
           'the feed line links the sheet')
        here = os.getcwd()
        os.chdir(root)
        try:
            brief = R.ask_waiting()
        finally:
            os.chdir(here)
        has(brief, re.escape(f'- F2: 2 config cleanups ready, 1 optional. Pick on the sheet or reply go {URL}'),
            'the control brief has the line and the link')

        p = R.prompt_for('F2', 1, 1, root, 'main')
        has(p, r'When you block with `DECIDE:` on a choice', 'the slot brief says when to write a sheet')
        has(p, re.escape(str(f)), 'and where')
        has(p, re.escape(f'{R.C.command} sheet F2 --html'), 'and how to render it')
        has(p, r'no option numbers anywhere', 'questions with answers, not a numbered list')

        R.C.run['questionnaires'] = False
        try:
            check('sheet' not in R.prompt_for('F2', 1, 1, root, 'main'), 'questionnaires = false: not in the brief')
            text = R.status_text(False, {}, [], {}, 0.0, waiting=R.waiting_ok())
            has(text, r'reply with your answer \[F2\]', 'and status words it as a plain DECIDE')
        finally:
            R.C.run['questionnaires'] = True


def test_answer():
    print('the picks sent from the sheet (or go) reopen the task with each answer in its note')
    with tempfile.TemporaryDirectory() as t:
        root, env = make(Path(t))
        todo = root / 'plan' / 'TODO.md'
        r = run(root, 'done', 'F2', 'F2: audit', '--no-test', '--blocked',
                f'DECIDE: 2 config cleanups ready, 1 optional {URL}', env=env)
        check(r.returncode == 0, 'blocked with DECIDE:', r.stdout + r.stderr)
        f = Path(run(root, 'sheet', 'F2', '--path', env=env).stdout.strip())
        eq(f, root / '.runner' / 'sheets' / 'F2.json', '--path: where it goes')
        r = run(root, 'sheet', 'F2', '--go', env=env)
        check(r.returncode == 1 and 'F2.json' in r.stderr, 'no sheet: says so', r.stderr)
        f.write_text(json.dumps(SPEC), encoding='utf-8')
        out = Path(t) / 'sheet.html'
        r = run(root, 'sheet', 'F2', '--html', str(out), env=env)
        check(r.returncode == 0 and out.is_file() and 'How should the runner' in out.read_text(encoding='utf-8'),
              '--html writes the page', r.stdout + r.stderr)
        has(r.stdout, re.escape('capabilities {"db": {}}'), 'and says to publish it with the db capability')
        r = run(root, 'sheet', 'F2', '--picks', 'F2 picks: backend=z', env=env)
        check(r.returncode == 2 and 'backend=z' in r.stderr, 'a pick the sheet has not is refused', r.stderr)
        has(todo.read_text(encoding='utf-8'), r'^- \[~\] \*\*F2\*\*', 'and the task still waits')
        r = run(root, 'sheet', 'F2', '--picks', 'F2 picks: backend=b silent=a', env=env)
        check(r.returncode == 0, 'the picks go through', r.stdout + r.stderr)
        has(todo.read_text(encoding='utf-8'),
            r'^- \[ \] \*\*F2\*\* .*your answer \(DECIDE .*\): picks on the sheet: backend \(.*\): Keep run\.backend; '
            r'silent \(.*\): Keep it \(recommended\)$', 'reopened, the picks spelled out in its note')


def test_go():
    print("'go' answers with the recommended set")
    with tempfile.TemporaryDirectory() as t:
        root, env = make(Path(t))
        todo = root / 'plan' / 'TODO.md'
        run(root, 'done', 'F2', 'F2: audit', '--no-test', '--blocked', f'DECIDE: cleanups ready {URL}', env=env)
        f = root / '.runner' / 'sheets' / 'F2.json'
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(SPEC), encoding='utf-8')
        r = run(root, 'sheet', 'F2', '--go', env=env)
        check(r.returncode == 0, 'go goes through', r.stdout + r.stderr)
        has(todo.read_text(encoding='utf-8'), r'^- \[ \] \*\*F2\*\* .*Work it out from agent \(recommended\)',
            'with the recommended answers noted')


if __name__ == '__main__':
    raise SystemExit(report([test_spec, test_page, test_db, test_needs_you, test_answer, test_go]))
