#!/usr/bin/env python3
"""B795: `done --blocked` refuses an ask line that does not say what the person does.

    python3 tests/test_done_asks.py        (no network; a few seconds, mostly git)
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from _check import check, eq, git, has, report, run

from agent_runner import asks as A  # noqa: E402
from agent_runner import runner as R  # noqa: E402

LONG = 'press the button ' * 15


def make(t: Path) -> tuple[Path, dict]:
    root = t / 'proj'
    root.mkdir()
    git(root, 'init', '-q')
    # the gate leaves a mark: a refusal comes before it
    (root / 'runner.toml').write_text('[run]\nremote = false\ntest = "touch .runner/gate-ran"\n[git]\npush = false\n',
                                      encoding='utf-8')
    (root / '.gitignore').write_text('.runner/\n', encoding='utf-8')
    (root / '.runner').mkdir()
    (root / 'plan').mkdir()
    (root / 'plan' / 'TODO.md').write_text('# TODO\n\n### Queue\n\n' + ''.join(
        f'- [ ] **{t}** job {t} | files: {t}.py\n' for t in ('F1', 'F2', 'F3', 'F4', 'V5', 'R17', 'K9')), encoding='utf-8')
    git(root, 'add', '-A')
    git(root, 'commit', '-qm', 'start')
    R.init(root)
    return root, {**os.environ, 'AGENT_RUNNER_REPO': str(root)}


def test_waits() -> None:
    print('which words make a named task a wait')
    live = {'V5', 'F1', 'F2', 'F12a', 'R17'}
    for why, ids in (('BLOCKED: the run is 0.62.0; release V5 and upgrade, then this reruns', ['V5']),
                     ('BLOCKED: waits for the next release V5', ['V5']),
                     ('CONFIRM: once F1 and F2 land, look at the list', ['F1', 'F2']),
                     ('BLOCKED: F12a (the list) must land first', ['F12a']),
                     ('BLOCKED: Needs task F1', ['F1']),
                     ('BLOCKED: F1 is needed first', ['F1']),
                     ('BLOCKED: F1 and F2 both must land', ['F1', 'F2']),
                     ('BLOCKED: Upgrade to V5 then rerun', ['V5']),
                     ('BLOCKED: pending F1', ['F1']),
                     ('BLOCKED: no go until after the release of V5', ['V5']),
                     ('BLOCKED: waiting on the upload page, F1', ['F1']),
                     ('BLOCKED: release `V5` first', ['V5']),
                     ('CONFIRM: wait until F1 is done', ['F1']),
                     ('CONFIRM: start F1 from the phone', []),
                     ('BLOCKED: Run F1 tests on your phone', []),
                     ('CONFIRM: after F1 opens, press Save', []),
                     ('CONFIRM: the F1 release notes read well', []),
                     ('CONFIRM: Open F1 done list', []),
                     ('BLOCKED: R17 waits for V5', ['V5']),  # never on itself
                     ('CONFIRM: after F9 the list is short', []),  # not open
                     ('CONFIRM: the list F1 made is short', []),
                     ('CONFIRM: Press Save on the F1 page; it has a tick', []),
                     ('BLOCKED: Open https://x.test/waits for/F1 and log in', []),
                     ('BLOCKED: Log in to Codex on the Mac: codex login failed', [])):
        eq(A.waits_named('R17', why, live), ids, why)


def test_done(root: Path, env: dict) -> None:
    todo, ran = root / 'plan' / 'TODO.md', root / '.runner' / 'gate-ran'
    done = lambda tid, why, *more: run(root, 'done', tid, f'{tid}: x', '--blocked', why, *more, env=env)  # noqa: E731

    def refused(tid: str, why: str, *pats: str, more=()) -> None:
        before, head = todo.read_text(encoding='utf-8'), git(root, 'rev-parse', 'HEAD')
        ran.unlink(missing_ok=True)
        r = done(tid, why, *more)
        eq(r.returncode, 2, f'refused: {why[:60]}')
        for p in (*pats, r'Nothing blocked\.'):
            has(r.stderr, p, f'says {p}')
        eq((todo.read_text(encoding='utf-8'), git(root, 'rev-parse', 'HEAD'), ran.exists()), (before, head, False),
           'nothing is blocked or committed, and the gate did not run')

    def blocked(tid: str, why: str, *more: str) -> None:
        r = done(tid, why, *more)
        check(r.returncode == 0 and f'blocked {tid}' in r.stdout, f'blocks: {why[:60]} {more}', r.stdout + r.stderr)

    f = root / '.runner' / 'asks' / 'F1.json'
    print('a long CONFIRM or BLOCKED with no ask file')
    for label in ('CONFIRM', 'BLOCKED'):
        refused('F1', f'{label}: {LONG}', rf'{label} line is \d+ characters, over 200', re.escape(str(f)),
                'starts with what the person does')
    refused('F1', f'CONFIRM: {LONG}', 'over 200', more=('--after', 'F2'))
    refused('F1', 'CONFIRM: ' + 'x' * 192, '201 characters')
    blocked('F1', 'CONFIRM: ' + 'x' * 191)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text('{"steps": ["Press Save"]}', encoding='utf-8')
    blocked('F1', f'CONFIRM: {LONG}')
    refused('F1', f'CONFIRM: {LONG}', 'no ask file')  # the file is the last ask's
    blocked('F2', f'BLOCKED: {LONG}', '--after', 'F4')  # asks the person nothing
    blocked('F3', f'DECIDE: {LONG}')  # noted, as before

    print('a CONFIRM or BLOCKED that waits on an open task or release')
    refused('R17', 'BLOCKED: the run is 0.62.0; release V5 and upgrade, then this reruns',
            r'waits for V5', r'--blocked "<why, with no label>" --after V5')
    refused('R17', 'CONFIRM: once F4 lands, look at the list', r'the same CONFIRM with --after F4')
    refused('R17', 'CONFIRM: once F4 lands, look at the list', 'waits for F4', more=('--after', ''))
    blocked('R17', 'CONFIRM: once F4 lands, look at the list', '--after', 'F4')
    blocked('R17', 'BLOCKED: waits for V5', '--until', 'version:9.9.9')
    blocked('R17', 'release V5 lands')  # no label: the wait is read off the words
    has(todo.read_text(encoding='utf-8'), r'R17.*BLOCKED: \(after V5\) .*release V5 lands', 'and waits on it')

    print('a CONFIRM that names /concept/<ID> of a task with no concept filed (B839)')
    refused('F3', 'CONFIRM: Watch both videos; the page address ends in /concept/F3', 'no concept is filed for F3',
            '"shots"', '.mp4', 'a link')
    g = root / '.runner' / 'asks' / 'F3.json'
    g.write_text('{"steps": ["Open the page at /concepts/F2"]}', encoding='utf-8')
    refused('F3', 'CONFIRM: Watch both videos and say which reads better', 'no concept is filed for F2')
    g.unlink()
    blocked('F3', 'CONFIRM: Pick an option on the page /concept/K9')  # a filed concept is fine

    print('a BLOCKED that waits for a command or a held tool (B810)')
    r17 = ('BLOCKED: The iPhone 15 UI lock is held by iFizBox task B440 (busy 25+ min); rerun when tools/ui-15.sh '
           'state exits 0')
    for why in (r17, 'BLOCKED: the phone is busy with another task', 'BLOCKED: reopen once `make probe` passes',
                'BLOCKED: retry when the simulator is not in use', 'BLOCKED: check state returns 0 then go on'):
        check(A.machine_wait(why), f'a machine wait: {why[:60]}')
    refused('R17', r17, 'no person is needed', r'file a task that adds one', 'block --after it')
    blocked('R17', r17, '--until', 'version:9.9.9')
    blocked('R17', r17, '--after', 'F4')
    refused('R17', 'BLOCKED: reopen once `make probe` passes', 'no person is needed')
    refused('R17', 'BLOCKED: lock held; restart when `x` state exits 0', 'no person is needed')
    blocked('F2', 'BLOCKED: Unlock the phone; the lock is held by the screen saver')
    for why in ('BLOCKED: Plug the iPhone 15 in; the device is busy until then',
                'BLOCKED: Unlock the phone; the lock is held by the screen saver',
                'BLOCKED: Sign in to Codex; rerun when `codex login status` exits 0',
                'BLOCKED: The phone is locked; unlock it and press Trust',
                'BLOCKED: Log in to Codex on the Mac; `codex login` says: not signed in'):
        check(not A.machine_wait(why), f'asks a person: {why[:60]}')
    toml = root / 'runner.toml'
    toml.write_text(toml.read_text(encoding='utf-8') + '[run.checks.probe]\ncmd = "true"\n', encoding='utf-8')
    refused('R17', r17, r'run wait-for NAME', r'--until tool:NAME or check:NAME', r'check:probe')
    toml.write_text(toml.read_text(encoding='utf-8').replace('[run.checks.probe]\ncmd = "true"\n', ''), encoding='utf-8')

    print('a good line')
    blocked('F4', 'BLOCKED: Log in to Codex on the Mac; `codex login` says: not signed in')
    blocked('F4', 'CONFIRM: Press Save on the F3 page and see that it stays saved')


def test_prompt(root: Path) -> None:
    print('the brief says it')
    p = R.prompt_for('F3', 1, 1, root, 'main')
    for k in ('It starts with what the person does, in words a person who never saw the task understands, and the reason '
              'comes second; it names no task id without that task\'s title.',
              'A wait on a task or a release is `--after <ID>`, and a wait a check can read is `--until <CHECK>` '
              '(`version:X.Y.Z`, `login:PROVIDER`, `tool:NAME`, `check:NAME`, or `date:YYYY-MM-DD` when all it waits '
              'for is a day, and it reopens by itself then): never `BLOCKED:`',
              f'over {A.LINE_MAX} characters with no ask file', 'names, after what the person does, the exact command'):
        check(k in p, k[:60], p)


def main() -> int:
    test_waits()
    with tempfile.TemporaryDirectory() as t:
        root, env = make(Path(t).resolve())
        test_done(root, env)
        test_prompt(root)
    return report([])


if __name__ == '__main__':
    raise SystemExit(main())
