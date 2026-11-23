#!/usr/bin/env python3
"""F177: a task too big for one session is split: the size rule, what `plan` and the slot brief say, and the one
message to a session past [run] context_warn.

    python3 tests/test_task_size.py        (no network; a few seconds, mostly git)
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

from _check import check, eq, git, has, report, run

from agent_runner import brief, config, guide, plan as P, runner as R, sched, watch

SMALL = 'The retry stops after three tries and says why; check: test_retry | files: app/retry.py, tests/test_retry.py'
# the shape of iFizBox's F392, which reached 483k: its 21 files, its six numbered changes and about its length
F392 = ('Build the concept as approved. ' + ' '.join(
    f'({n}) ' + 'A tap on a row uses that way, its blue detail disclosure opens its page, and the footer says so in '
    'every era, light and dark, with the normal pressed highlight and no leftover price button; iOS 6) keeps its '
    'info circle. ' * 2 for n in range(1, 7))
    + '| files: ' + ', '.join([f'web/app/screens/s{n}.js' for n in range(19)] + ['docs/settings.md', 'docs/eras.md']))


def make(d: Path, toml: str = '') -> tuple[Path, dict]:
    root = d / 'repo'
    root.mkdir()
    git(root, 'init', '-q', '-b', 'main')
    (root / 'runner.toml').write_text('[run]\nremote = false\n' + toml, encoding='utf-8')
    (root / '.gitignore').write_text('.runner/\n', encoding='utf-8')
    git(root, 'add', '-A')
    git(root, 'commit', '-qm', 'start')
    return root, {**os.environ, 'AGENT_RUNNER_REPO': str(root)}


def plan(root, env, *words) -> str:
    p = run(root, 'plan', *words, env=env)
    check(p.returncode == 0, f'plan {words[0]} works', p.stdout + p.stderr)
    return p.stdout


def test_rule():
    print('the size of a task: code files, numbered outcomes, length of text')
    n, files, outs, _ = P.size([f'- [ ] **F1** {SMALL}'])
    eq((files, outs, n <= 10), (2, 0, True), 'a small task is under the default')
    n, files, outs, chars = P.size([f'- [ ] **F392** {F392}'], ['*.md', 'docs/**'])
    eq((files, outs), (19, 6), "F392: 19 code files (its docs are not counted) and six outcomes")
    check(n == 19 + 12 + chars // P.SIZE_CHARS > 10, 'over the default', n)
    eq(P.outcomes('fix (1) and see iOS 7) and 0.26.0'), 0, 'a lone number is no list')
    eq(P.outcomes('1. a\n2. b\n3. c'), 3, 'a plain list')
    eq(P.outcomes('(1) a (2) b — (1) c (2) d (3) e'), 5, 'two lists add up')


def test_plan_says():
    print('plan add, edit, note and an approval say when a task is too big')
    with tempfile.TemporaryDirectory() as t:
        root, env = make(Path(t))
        check('too big' not in plan(root, env, 'add', 'F', SMALL), 'a small task is silent')
        check('too big' not in plan(root, env, 'note', 'F1', 'also log it'), 'a small note is silent')
        big = plan(root, env, 'add', 'F', F392)
        has(big, r'F2 is too big for one session \(size \d+, over \[run\] task_size 10: 19 code files, 6 numbered '
                 r'outcomes, [\d,]+ characters of text\)', 'plan add says so, with what makes it big')
        has(big, r'add F2 "<part>".*split into F2a, F2b', 'and how to split it')
        has(plan(root, env, 'note', 'F1', F392.split('|')[0]), r'F1 is too big', 'plan note says so')
        check('too big' not in plan(root, env, 'edit', 'F1', SMALL), 'small again after an edit')
        has(plan(root, env, 'edit', 'F1', F392), r'F1 is too big', 'plan edit says so')
        todo = root / 'plan' / 'TODO.md'
        for how in ('approve', 'confirm'):
            out = plan(root, env, 'concept', f'Rows as buttons, {how}', '--page', f'https://x.test/{how}',
                       '--files', ','.join(f'web/{how}/s{n}.js' for n in range(19)))
            k = out.split()[1]
            check('too big' not in out, 'filing a concept is silent')
            has(plan(root, env, how, k, 'option A'), r'F\d+ is too big', f'plan {how} of its concept says so')
        plan(root, env, 'add', 'F2', 'the first rows | files: web/app/a.js')
        plan(root, env, 'edit', 'F2', 'Rows as buttons (split into F2a)')
        eq(P.too_big('F2', mock.Mock(run={'task_size': 1}), todo), '',
           'a task split into parts is not too big')


def test_off():
    print('[run] task_size = 0: never')
    with tempfile.TemporaryDirectory() as t:
        root, env = make(Path(t), 'task_size = 0\n')
        check('too big' not in plan(root, env, 'add', 'F', F392), 'plan add is silent')
        R.init(root)
        check('Split F1 first' not in R.prompt_for('F1', 1, 1, root, 'main'), 'and so is the brief')


def test_brief():
    print('the slot brief of a task over the size has it split first; the control brief splits before queueing')
    with tempfile.TemporaryDirectory() as t:
        root, env = make(Path(t))
        plan(root, env, 'add', 'F', SMALL)
        plan(root, env, 'add', 'F', F392)
        plan(root, env, 'add', 'K', F392, '--force')
        R.init(root)
        eq(R.C.run['task_size'], 10, 'on by default')
        big = [l for l in R.prompt_for('F2', 1, 1, root, 'main').splitlines() if l.startswith('Split F2 first')]
        eq(len(big), 1, 'the line is there')
        has(big[0], r'plan add F2 "<what, why.*plan edit F2 .*do only that part', 'file the rest, do the first part')
        for tid in ('F1', 'K1'):
            check('Split ' not in R.prompt_for(tid, 1, 1, root, 'main'), f'{tid}: a small task or a concept: no line')
    has(guide.CONTROL, r'a big ask split into parts first: .guide queue.', 'the control brief')
    has(guide.control_topic('queue'), r'(?s)Split a big ask before you queue it.*--pri later', 'and its queue page')


def test_split_flow():
    print('a title parked as split, its parts queued: the title ticks itself')
    with tempfile.TemporaryDirectory() as t:
        root, env = make(Path(t))
        plan(root, env, 'add', 'F', 'Rows as buttons (split into parts) | files: a.js', '--pri', 'later')
        plan(root, env, 'add', 'F1', 'the first rows', '--files', 'a.js', '--pri', 'normal')
        R.init(root)
        git(root, 'add', '-A')
        git(root, 'commit', '-qm', 'plan', '--allow-empty')
        eq([t[0] for t in sched.tasks('main')], ['F1a'], 'only the part is in the pool')
        plan(root, env, 'tick', 'F1a')
        check('**F1**' not in (root / 'plan' / 'TODO.md').read_text(encoding='utf-8'), 'the title ticked itself')


def entry(k: int, **more) -> str:
    return json.dumps({'type': 'assistant', **more, 'message': {'usage': {
        'input_tokens': 1000, 'cache_read_input_tokens': (k - 1) * 1000}}}) + '\n'


def test_one_message():
    print('a session past [run] context_warn is told once, as a turn ends')
    with tempfile.TemporaryDirectory() as d:
        root, _ = make(Path(d))
        git(root, 'checkout', '-qb', 'task/F7')
        notes = root / '.runner'
        notes.mkdir(exist_ok=True)
        t = Path(d) / '11111111-1111-1111-1111-111111111111.jsonl'
        seen, cwd, stdin = [], os.getcwd(), sys.stdin

        def stop(event='Stop', idle=90) -> str:
            out = io.StringIO()
            sys.stdin = io.StringIO(json.dumps({'transcript_path': str(t), 'hook_event_name': event}))
            with contextlib.redirect_stdout(out):
                rc = watch.stop_hook(idle)
            check(rc == 0, 'the hook exits 0')
            return out.getvalue()
        try:
            os.chdir(root)
            with mock.patch.dict(os.environ, AGENT_RUNNER='1', AGENT_RUNNER_SLOT='3'), \
                    mock.patch.object(watch.plat, 'spawn_detached', seen.append):
                t.write_text(entry(120) + entry(900, isSidechain=True), encoding='utf-8')
                eq((stop(), len(seen)), ('', 1), 'under it: nothing said (a subagent is not counted), the waiter starts')
                t.write_text(entry(120) + entry(168), encoding='utf-8')
                (notes / 'slot3.finished').touch()
                eq(stop(), '', 'not after its done')
                (notes / 'slot3.finished').unlink()
                eq(stop('StopFailure'), '', 'not as an API error ends the turn')
                before = len(seen)
                said = json.loads(stop())
                eq((said['decision'], len(seen)), ('block', before), 'told at the turn end, which goes on, with no waiter')
                has(said['reason'], r'168k tokens.*150k.*already running its test gate, let it finish.*commit what is '
                    r'solid on task/F7.*plan add F7 .*done.*finish.*nothing stops you if you go on', 'what to do')
                eq((stop(), len(seen)), ('', before + 1), 'once: the next turn end only waits, as always')
                (notes / f'{t.stem}.full').unlink()
                check(stop(idle=-1) and stop(idle=-1) == '' and len(seen) == before + 1,
                      'the stream engine: told once too, and never a waiter')
                (notes / f'{t.stem}.full').unlink()
                (root / 'runner.toml').write_text('[run]\nremote = false\ncontext_warn = 0\n', encoding='utf-8')
                config._cfg.cache_clear()
                eq(stop(), '', 'context_warn = 0: never')
                (root / 'runner.toml').write_text('[run]\nremote = false\n', encoding='utf-8')
                config._cfg.cache_clear()
                git(root, 'checkout', '-q', 'main')
                eq(stop(), '', 'not a session on no task branch (a fix session)')
        finally:
            sys.stdin = stdin
            os.chdir(cwd)
    check('{peak}' in brief.CONTEXT_FULL and '{tid}' in brief.CONTEXT_FULL, 'the harness fills in the same text')


if __name__ == '__main__':
    raise SystemExit(report([test_rule, test_plan_says, test_off, test_brief, test_split_flow, test_one_message]))
