#!/usr/bin/env python3
"""F173: a setting saved for everyone is one key of runner.toml, committed alone on the shared branch and pushed.

    python3 tests/test_config.py        (temp repos with a bare remote, no agent; a few seconds)
"""
from __future__ import annotations

import subprocess
import tempfile
import threading
import time
from pathlib import Path
from unittest import mock

from _check import check, eq, git, report

from agent_runner import config as CF  # noqa: E402
from agent_runner import plan as P  # noqa: E402
from agent_runner import plansync  # noqa: E402
from agent_runner import state as S  # noqa: E402
from agent_runner import ui_model as U  # noqa: E402

TOML = '# ours\n[run]\ntest = "true"\nweekly_max = 90   # a cap\nslots = 2\n\n# the end\n[git]\nland_edited = "wait"\n'


def out(cwd: Path, *a: str) -> str:
    return git(cwd, *a).strip()


def project(tmp: Path, toml: bytes | None = TOML.encode(), extra: str = '') -> Path:
    repo, remote = tmp / 'proj', tmp / 'origin.git'
    (repo / 'plan').mkdir(parents=True)
    git(tmp, 'init', '-q', '--bare', str(remote))
    git(repo, 'init', '-q')
    git(repo, 'remote', 'add', 'origin', str(remote))
    (repo / '.gitignore').write_text('.runner/\nrunner.local.toml\n' + extra)
    (repo / 'plan' / 'TODO.md').write_text('# TODO\n\n### Next\n- [ ] **F1** It | files: a.py\n', encoding='utf-8')
    (repo / 'plan' / 'DONE.md').write_text('# DONE\n', encoding='utf-8')
    if toml is not None:
        (repo / 'runner.toml').write_bytes(toml)
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'start')
    git(repo, 'push', '-q', 'origin', 'main')
    S.init(repo)
    return repo


def save(key='weekly_max', value=80, table='run', **kw) -> dict:
    return U.setting_project(table, key, value, **kw)


def commits(repo: Path) -> int:
    return int(out(repo, 'rev-list', '--count', 'HEAD'))


def status(repo: Path) -> str:
    return git(repo, 'status', '--porcelain', '--untracked-files=all')


def test_one_key(tmp: Path) -> None:
    """Only that key changes, one commit of one file, pushed, no task; somebody else's edits stay out of it."""
    repo = project(tmp)
    todo = (repo / 'plan' / 'TODO.md').read_text(encoding='utf-8')
    (repo / 'mine.py').write_text('x\n')
    (repo / '.gitignore').write_text('.runner/\nrunner.local.toml\n# staged\n')
    git(repo, 'add', '.gitignore')
    with mock.patch.object(U, 'RUN', [lambda argv: (1, f'ran {argv}')]):
        r = save()
    check(r['ok'] and 'not pushed' not in r['out'], 'saved and pushed', r)
    eq((repo / 'runner.toml').read_text(encoding='utf-8'), TOML.replace('= 90', '= 80'), 'that key only, its comment kept')
    eq(commits(repo), 2, 'one commit')
    eq(out(repo, 'show', '--name-only', '--format=%s', 'HEAD').split('\n'), ['settings: [run] weekly_max = 80', '', 'runner.toml'],
       'of one file')
    eq(out(tmp / 'origin.git', 'rev-parse', 'main'), out(repo, 'rev-parse', 'HEAD'), 'pushed')
    eq((repo / 'plan' / 'TODO.md').read_text(encoding='utf-8'), todo, 'no task')
    eq(status(repo), 'M  .gitignore\n?? mine.py', "the person's other edits are as they were")
    eq((save()['ok'], commits(repo)), (True, 2), 'the same value again: no commit')
    check(not save(key='nokey')['ok'] and not save(value=-1)['ok'], 'a bad one is refused')
    r = save(value=None, unset=True)
    check(r['ok'] and 'weekly_max' not in (repo / 'runner.toml').read_text(encoding='utf-8'), 'a reset takes it out', r)
    r = save(value='a | files: b')
    check(not r['ok'], 'still checked')
    check(save(key='test', value='a | files: b — BLOCKED: x')['ok'], 'no task line: any text value is fine')


def test_line_ends(tmp: Path) -> None:
    """CRLF stays CRLF, with autocrlf too, and git sees nothing left to commit."""
    repo = project(tmp, TOML.replace('\n', '\r\n').encode())
    git(repo, 'config', 'core.autocrlf', 'true')
    git(repo, 'add', '--renormalize', '.')
    git(repo, 'commit', '-qm', 'crlf')
    check(save()['ok'], 'saved')
    eq((repo / 'runner.toml').read_bytes(), TOML.replace('= 90', '= 80').replace('\n', '\r\n').encode(), 'CRLF kept')
    eq(status(repo), '', 'nothing left dirty')


def test_waits_for_a_merge(tmp: Path) -> None:
    """A merge that is landing is waited for, and saves that come meanwhile are one commit."""
    repo = project(tmp)
    got: list = []
    S.LANDING.acquire()
    ts = [threading.Thread(target=lambda v=v: got.append(save(value=v))) for v in (81, 82, 83)]
    try:
        for t in ts:
            t.start()
            time.sleep(0.05)
        ts.append(threading.Thread(target=lambda: got.append(save(key='slots', value=4))))
        ts[-1].start()
        time.sleep(U.SETTING_SETTLE + 0.5)
        eq((got, commits(repo), (repo / 'runner.toml').read_text(encoding='utf-8')), ([], 1, TOML), 'nothing while it lands')
    finally:
        S.LANDING.release()
    for t in ts:
        t.join(30)
    eq([r['ok'] for r in got], [True] * 4, 'then all are saved')
    eq(commits(repo), 2, 'as one commit')
    eq((repo / 'runner.toml').read_text(encoding='utf-8'), TOML.replace('= 90', '= 83').replace('slots = 2', 'slots = 4'), 'the last of each')
    S.LANDING.acquire()
    try:
        with mock.patch.object(U, 'SETTING_WAIT', 0.1):
            r = save(value=70)
    finally:
        S.LANDING.release()
    check(not r['ok'] and 'landing' in r['out'], 'a landing that does not end: refused', r)
    eq((commits(repo), status(repo)), (2, ''), 'with nothing changed')
    S.MERGE.acquire()
    try:
        check(save(value=70)['ok'], 'a merge still in its gate does not hold it')
    finally:
        S.MERGE.release()


def test_refused(tmp: Path) -> None:
    """The person's own edits in runner.toml, another branch, a merge of their own, a failing commit: nothing changes."""
    repo = project(tmp)
    f = repo / 'runner.toml'
    for staged in (False, True):
        f.write_text(TOML + '# mine\n', encoding='utf-8')
        if staged:
            git(repo, 'add', 'runner.toml')
        r = save()
        check(not r['ok'] and 'uncommitted edits' in r['out'], 'refused', r)
        eq((f.read_text(encoding='utf-8'), commits(repo)), (TOML + '# mine\n', 1), 'and left alone')
    git(repo, 'reset', '-q', '--', 'runner.toml')
    git(repo, 'checkout', '-q', '--', 'runner.toml')
    git(repo, 'checkout', '-q', '-b', 'mine')
    r = save()
    check(not r['ok'] and 'mine out, not main' in r['out'], 'another branch is out', r)
    git(repo, 'checkout', '-q', 'main')
    (repo / '.git' / 'MERGE_HEAD').write_text(out(repo, 'rev-parse', 'HEAD') + '\n')
    r = save()
    check(not r['ok'] and 'under way' in r['out'], 'mid-merge', r)
    (repo / '.git' / 'MERGE_HEAD').unlink()
    hook = repo / '.git' / 'hooks' / 'pre-commit'
    hook.parent.mkdir(exist_ok=True)
    hook.write_text('#!/bin/sh\necho no >&2\nexit 1\n')
    hook.chmod(0o755)
    r = save()
    check(not r['ok'] and 'could not be committed' in r['out'], 'a commit that fails', r)
    hook.unlink()
    eq((f.read_text(encoding='utf-8'), commits(repo), status(repo)), (TOML, 1, ''), 'the file is as it was')
    f.write_text('run = { slots = 2 }\n', encoding='utf-8')
    git(repo, 'commit', '-qam', 'inline')
    r = save(key='slots', value=3)
    check(not r['ok'] and 'runner.toml' in r['out'] and 'local' not in r['out'], 'a key not on its own line names this file', r)
    eq(status(repo), '', 'and it is clean')


def test_push_fails(tmp: Path) -> None:
    repo = project(tmp)
    git(repo, 'remote', 'set-url', 'origin', str(tmp / 'gone.git'))
    r = save()
    check(r['ok'] and 'saved here, not pushed' in r['out'], 'said', r)
    eq((commits(repo), status(repo)), (2, ''), 'committed here')


def test_device_over_it(tmp: Path) -> None:
    """A device override wins: the answer says so and the run is not told; without one it is told of `slots`."""
    repo = project(tmp)
    (repo / 'runner.local.toml').write_text('[run]\nslots = 5\n', encoding='utf-8')
    ran: list = []
    with mock.patch.object(U, 'RUN', [lambda argv: (ran.append(argv), (0, ''))[1]]), mock.patch.object(S, 'run_up', lambda: True):
        r = save(key='slots', value=3)
        check(r['ok'] and 'This device keeps its own (5)' in r['out'], 'said', r)
        eq(ran, [], 'the run keeps its count')
        (repo / 'runner.local.toml').unlink()
        save(key='slots', value=4)
        eq(ran, [['slots', '4']], 'else it applies now')


def test_other_files(tmp: Path) -> None:
    """No runner.toml yet: made and committed. One git ignores, or outside the repo: written, no commit."""
    (tmp / 'a').mkdir()
    repo = project(tmp / 'a', None)
    check(save()['ok'], 'saved')
    eq(CF.tomllib.loads((repo / 'runner.toml').read_text(encoding='utf-8')), {'run': {'weekly_max': 80}}, 'made')
    eq((commits(repo), status(repo)), (2, ''), 'and committed')
    (tmp / 'b').mkdir()
    repo = project(tmp / 'b', extra='runner.toml\n')
    r = save()
    check(r['ok'] and 'not in git' in r['out'], 'ignored by git', r)
    eq((commits(repo), status(repo)), (1, ''), 'no commit')
    f = tmp / 'kit.toml'
    f.write_text('[agent-runner.run]\nslots = 1\n', encoding='utf-8')
    with mock.patch.dict('os.environ', AGENT_RUNNER_CONFIG=str(f)):
        r = save(key='slots', value=3)
    check(r['ok'] and 'slots = 3' in f.read_text(encoding='utf-8') and commits(repo) == 1, 'outside the repo', r)


def test_external_plan(tmp: Path) -> None:
    """With [plan] repo the save is a commit in the code repo, and the plan is not touched."""
    git(tmp, 'init', '-q', '--bare', str(tmp / 'plan.git'))
    toml = f'[plan]\nrepo = "{(tmp / "plan.git").as_posix()}"\ndir = "{(tmp / "clone").as_posix()}"\n\n' + TOML
    repo = project(tmp, toml.encode())
    plansync.ensure_clone(S.C)
    plan_head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=tmp / 'clone', capture_output=True, text=True).stdout
    check(S.C.plan_external and save()['ok'], 'saved')
    eq(commits(repo), 2, 'in the code repo')
    eq(subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=tmp / 'clone', capture_output=True, text=True).stdout, plan_head, 'not the plan')
    eq([t for _, _, t, _, _ in P.iter_tasks(P.lines(S.C.todo))] if S.C.todo.exists() else [], [], 'no task there')


def in_tmp(f):
    def go():
        print(f.__name__)
        with tempfile.TemporaryDirectory() as d:
            f(Path(d))
    return go


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(f) for f in (test_one_key, test_line_ends, test_waits_for_a_merge, test_refused, test_push_fails,
                                                 test_device_over_it, test_other_files, test_external_plan)]))
