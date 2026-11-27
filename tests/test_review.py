#!/usr/bin/env python3
"""F28: the spec review before done.

    python3 tests/test_review.py        (no network; a second or two, mostly git)

With `[run] review` on (the default) the slot prompt asks for a fresh subagent's spec review of the diff against
the brief, states when to skip it, and asks for the `review: …` line every commit message ends with; lean Claude
sessions get the Agent tool for it. `[run] review = false` drops all of that.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from unittest import mock

from _check import check, eq, git, has, report, run

from agent_runner import runner as R  # noqa: E402


def make(tmp: Path, toml: str = '') -> tuple[Path, dict]:
    root = tmp / 'proj'
    root.mkdir()
    git(root, 'init', '-q', '-b', 'main')
    (root / 'runner.toml').write_text('[run]\nremote = false\n' + toml, encoding='utf-8')
    (root / '.gitignore').write_text('.runner/\n', encoding='utf-8')
    git(root, 'add', '-A')
    git(root, 'commit', '-qm', 'start')
    env = {**os.environ, 'AGENT_RUNNER_REPO': str(root)}
    env.pop('AGENT_RUNNER', None)
    for text in ('add a thing | files: a.py', 'add another | files: b.py'):
        check(run(root, 'plan', 'add', 'F', text, env=env).returncode == 0, f'added {text}')
    return root, env


def test_prompt_on():
    print('review on (the default): the prompt carries the review paragraph and the skip rule')
    with tempfile.TemporaryDirectory() as t:
        root, _ = make(Path(t))
        R.init(root)
        check(R.C.run['review'] is True and R.C.run['review_min_lines'] == 50, 'on by default, 50 lines')
        p = R.prompt_for('F1', 1, 1, root, 'main')
        has(p, r'Spec review, before `done`', 'the review paragraph')
        has(p, r'fresh subagent', 'in a fresh subagent')
        has(p, re.escape('`git diff main...HEAD`'), 'given the diff against the base branch')
        has(p, re.escape(f'`{R.C.command} plan brief F1`'), 'and the brief')
        for what in ('missing', 'not asked', 'implemented but wrong', 'quoting the task', 'under 300 words'):
            check(what in p, f'asks for {what!r}', p)
        has(p, r'Fix \(a\) and \(c\)', 'missing and wrong get fixed')
        has(p, r'never file them', 'not filed')
        has(p, r'Revert \(b\)', 'unasked extras reverted')
        has(p, r'--pri normal', 'a follow-up is filed at normal')
        has(p, r'Skip the review when the diff is under 50 changed lines', 'the skip rule, with the threshold')
        has(p, re.escape('no long-form brief (plan/tasks/F1.md)'), 'and the long-form exception')
        has(p, r'this task has none', 'F1 has no long form')
        for line in ('`review: nothing`', '`review: fixed <what>`', '`review: filed <IDs>`',
                     '`review: skipped (small)`'):
            check(line in p, f'the commit line {line}', p)
        check(p.index('Spec review') < p.index('Project policies:'), 'before the policies')
        tools = R.lean()
        eq(tools[tools.index('--tools') + 1], 'Bash,Read,Edit,Write,Agent', 'lean: the Agent tool too')

        long = root / 'plan' / 'tasks' / 'F2.md'
        long.parent.mkdir(parents=True, exist_ok=True)
        long.write_text('# F2\n\nThe long form.\n', encoding='utf-8')
        has(R.prompt_for('F2', 1, 1, root, 'main'), r'this task has one, so review it whatever its size',
            'a task with a long form is reviewed whatever its size')

        R.C.run['review_min_lines'] = 120
        try:
            has(R.prompt_for('F1', 1, 1, root, 'main'), r'under 120 changed lines', '[run] review_min_lines')
        finally:
            R.C.run['review_min_lines'] = 50


def test_prompt_off():
    print('review = false: no review paragraph, no review line, no Agent tool')
    with tempfile.TemporaryDirectory() as t:
        root, _ = make(Path(t), 'review = false\n')
        R.init(root)
        p = R.prompt_for('F1', 1, 1, root, 'main')
        check('Spec review' not in p and 'review: ' not in p and '"review"' not in p, 'not in the prompt', p)
        check('review' not in R.subagents(), 'no review subagent (F101)')
        tools = R.lean()
        eq(tools[tools.index('--tools') + 1], 'Bash,Read,Edit,Write,Agent',
           'lean: the Agent tool still, for the docs subagent (F101)')
        with mock.patch.dict(R.C.raw['models'], {'docs': False}):
            tools = R.lean()
            eq(tools[tools.index('--tools') + 1], 'Bash,Read,Edit,Write', 'no subagent at all: no Agent tool')


ANSWER = r"""
import fs from 'node:fs';
export default function ({ provider, model }) {
  return { async call(context) {
    fs.writeFileSync(process.env.FAKE_LOG, JSON.stringify({ provider, model, tools: context.tools.map((t) => t.name),
      messages: context.messages.map((m) => m.content) }));
    return { role: 'assistant', content: [{ type: 'text', text: '(a) "add a thing": missing' }], api: 'fake', provider,
      model, timestamp: Date.now(), stopReason: 'stop', usage: { input: 1, output: 1, cacheRead: 0, cacheWrite: 0 } };
  } };
}
"""

CLAUDE = """#!/usr/bin/env python3
import json, os, sys
open(os.environ['FAKE_LOG'], 'w').write(json.dumps({'argv': sys.argv[1:], 'said': sys.stdin.read()}))
print('nothing')
"""


def test_prompt_provider():
    print("F406e: a review or docs model of another provider is no subagent; the brief runs `run review` instead")
    with tempfile.TemporaryDirectory() as t:
        root, _ = make(Path(t), '\n[models]\nreview = "codex:gpt-test"\ndocs = "codex:gpt-test"\n')
        R.init(root)
        eq(R.subagents(), {}, 'no subagent on another provider')
        p = R.prompt_for('F1', 1, 1, root, 'main', 'opus')
        has(p, re.escape(f'`{R.C.command} review F1 --base main`'), 'a Claude Code session runs the one-shot')
        check('subagent_type' not in p and 'Hand CHANGELOG' not in p, 'and writes its docs itself', p)
        for line in ('`review: nothing`', 'Fix (a) and (c)', 'Skip the review'):
            check(line in p, f'it still says {line!r}')


def test_one_shot():
    print('F406e: run review: a fresh one-shot on [models] review gets only the diff and the brief; findings come back')
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        root, env = make(tmp, '\n[models]\nreview = "codex:gpt-test"\n')
        wt = tmp / 'wt'
        git(root, 'worktree', 'add', '-q', '-b', 'task/F1', str(wt))
        (tmp / 'fake.mjs').write_text(ANSWER, encoding='utf-8')
        log = tmp / 'log.json'
        nopath = tmp / 'bin'  # no claude on PATH
        nopath.mkdir()
        for tool in ('git', 'node'):
            if at := shutil.which(tool):
                (nopath / tool).symlink_to(at)
        env = {**env, 'AGENT_RUNNER_HARNESS_PROVIDER': str(tmp / 'fake.mjs'), 'FAKE_LOG': str(log),
               'AGENT_RUNNER_SLOT': '1', 'PATH': str(nopath)}
        r = run(wt, 'review', 'F1', '--base', 'main', env=env)
        check(r.returncode == 1 and 'is empty' in r.stderr, 'nothing committed: it says so', r.stderr)
        (wt / 'a.py').write_text('print("the new thing")\n', encoding='utf-8')
        git(wt, 'add', '-A')
        git(wt, 'commit', '-qm', 'F1 a thing')
        if shutil.which('node'):
            r = run(wt, 'review', '--base', 'main', env=env)
            eq((r.returncode, r.stdout.strip()), (0, '(a) "add a thing": missing'), 'the findings are printed')
            got = json.loads(log.read_text(encoding='utf-8'))
            eq((got['provider'], got['model'], got['tools'], len(got['messages'])), ('codex', 'gpt-test', ['read'], 1),
               'a fresh one-shot on [models] review, read only')
            check('+print("the new thing")' in got['messages'][0] and 'add a thing' in got['messages'][0],
                  'handed the diff and the brief', got['messages'][0])
        toml = root / 'runner.toml'
        toml.write_text('[run]\nremote = false\nagent = "claude-f406e"\n', encoding='utf-8')
        (wt / 'runner.toml').write_text(toml.read_text(encoding='utf-8'), encoding='utf-8')
        r = run(wt, 'review', 'F1', '--base', 'main', env=env)
        check(r.returncode == 1 and 'no review: the one-shot on opus did not run' in r.stderr,
              'a claude review model with no claude on PATH: it says it did not run', r.stderr)
        fake = nopath / 'claude-f406e'
        fake.write_text(CLAUDE.replace('/usr/bin/env python3', sys.executable), encoding='utf-8')
        fake.chmod(0o755)
        r = run(wt, 'review', 'F1', '--base', 'main', env=env)
        eq((r.returncode, r.stdout.strip()), (0, 'nothing'), 'with it, a headless one-shot answers')
        got = json.loads(log.read_text(encoding='utf-8'))
        eq((got['argv'][0], got['argv'][got['argv'].index('--tools') + 1]), ('-p', 'Read'), 'with Read only')
        check('the new thing' in got['said'], 'and the diff on stdin')


def test_review_page():
    """F444: a waiting change's Review page shows its diff (cut to approve_diff_lines), the questions asked about it
    and their answers, and how to ask, ask for a better way, or approve."""
    from agent_runner import pitch, review as RV, state as S
    with tempfile.TemporaryDirectory() as t:
        root, _ = make(Path(t), 'approve_diff_lines = 3\n')
        R.init(root)
        before = git(root, 'rev-parse', 'HEAD')
        (root / 'a.py').write_text('one\ntwo <b>\nthree\nfour\n', encoding='utf-8')
        git(root, 'add', '-A')
        git(root, 'commit', '-qm', 'F1 a thing')
        after = git(root, 'rev-parse', 'HEAD')
        x = {'id': 'F1', 'title': 'add a thing', 'before': before, 'after': after, 'files': ['a.py'], 'state': 'waiting',
             'pitch': 'pitch1', 'say': {'what': 'a thing', 'why': 'you asked'}, 'subject': 'F1 a thing', 'merged': after, 'undo': '', 'key': 'F1@x', 'err': ''}
        diff, n = RV.change_diff(x)
        eq(len(diff.splitlines()), 3, 'cut to approve_diff_lines')
        check(n > 3, 'and it knows the whole length', n)
        page = pitch.page_html('pitch1', {'changes': [x], 'pitches': []})
        has(page, '3 of ', 'the page says the diff is cut')
        has(page, 'pitch ask pitch1 F1', 'how to ask about it')
        has(page, 'pitch better pitch1 F1 --why', 'how to ask for a better way')
        x['after'], x['before'] = x['before'], x['after']
        S.C.run['approve_diff_lines'] = 50
        has(pitch.page_html('pitch1', {'changes': [x], 'pitches': []}), '-two &lt;b&gt;', 'the diff, escaped')
        seen = []
        said, why = RV.ask_change(x, 'why four?', root, once=lambda text: (seen.append(text) or 'because', ''))
        eq((said, why), ('because', ''), 'the one-shot answers')
        check('why four?' in seen[0] and 'you asked' in seen[0] and 'two <b>' in seen[0],
              'handed the question, the why and the diff', seen[0])
        page = pitch.page_html('pitch1', {'changes': [x], 'pitches': []})
        has(page, 'why four?', 'the question is on the page')
        has(page, 'because', 'and its answer')
        S.C.run['approve_diff_lines'] = 0
        check('The diff' not in pitch.page_html('pitch1', {'changes': [x], 'pitches': []}), '0: no diff')


if __name__ == '__main__':
    tests = [test_prompt_provider] + ([] if os.name == 'nt' else [test_one_shot])  # its fake programs are POSIX
    raise SystemExit(report(tests + [test_prompt_on, test_prompt_off, test_review_page]))
