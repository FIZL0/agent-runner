#!/usr/bin/env python3
"""Approve to push (F98, `[run] approve`): what is held back, pitches, approving, and undoing.

    python3 tests/test_pitch.py        (no network; some seconds of git)

Real merges in a throwaway repo with a bare remote; only the page's publish is stubbed.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import tempfile
import time
from pathlib import Path

from _check import check, eq, git, has, report, run

from agent_runner import runner as R  # noqa: E402
from agent_runner import land, merge as M, pitch, plan as P, sched, status, ui_model as U, undo  # noqa: E402

TASKS = {'F1': ('one', 'ui/menu.py', ''), 'F2': ('two', 'ui/menu.py', ''), 'F3': ('three', 'net/send.py', ''),
         'F4': ('four', 'other/x.py', ''), 'F5': ('five', 'far/y.py', ' | after: F4')}


def make(tmp: Path, name: str, extra: str = 'approve = true\n') -> tuple[Path, Path]:
    d = tmp / name
    d.mkdir()
    origin, repo = d / 'origin.git', d / name
    git(d, 'init', '-q', '--bare', '-b', 'main', str(origin))
    repo.mkdir()
    git(repo, 'init', '-q', '-b', 'main')
    (repo / 'plan').mkdir()
    (repo / 'plan/TODO.md').write_text('# TODO\n\n### Next\n\n' + ''.join(
        f'- [ ] **{t}** {w} | files: {f}{a}\n' for t, (w, f, a) in TASKS.items())
        + '- [ ] **V1** Release | after: all\n', encoding='utf-8')
    (repo / 'plan/DONE.md').write_text('# DONE\n', encoding='utf-8')
    for _, f, _ in TASKS.values():
        (repo / f).parent.mkdir(exist_ok=True)
        (repo / f).write_text('top\n\n\n\n\nend\n', encoding='utf-8')
    (repo / 'runner.toml').write_text('[run]\ntest = "true"\nmin_free_gb = 0\nremote = false\nmerge_ahead = false\n'
                                      f'fix_merges = false\n{extra}',
                                      encoding='utf-8')
    (repo / '.gitignore').write_text('.runner/\nrunner.local.toml\n', encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'start')
    git(repo, 'remote', 'add', 'origin', str(origin))
    git(repo, 'push', '-q', '-u', 'origin', 'main')
    R.init(repo)
    pitch.PUSHED_AT[0] = time.time()
    land.UNPUSHED.clear()
    return repo, origin


def work(repo: Path, tid: str, text: str = '', where: str = 'top') -> str:
    """Task `tid` done on its branch and merged: the shared branch's head after it."""
    _, f, _ = TASKS[tid]
    git(repo, 'checkout', '-q', '-b', f'task/{tid}')
    old = (repo / f).read_text(encoding='utf-8')
    (repo / f).write_text(old.replace(where, f'{where}\n{text or tid}', 1), encoding='utf-8')
    todo = repo / 'plan/TODO.md'
    todo.write_text(todo.read_text(encoding='utf-8').replace(f'- [ ] **{tid}**', f'- [x] **{tid}**'), encoding='utf-8')
    git(repo, 'commit', '-qam', f'{tid}: did it')
    git(repo, 'checkout', '-q', 'main')
    eq(M.merge(tid, 'main'), None, f'{tid} merges')
    return git(repo, 'rev-parse', 'main')


def remote(origin: Path) -> str:
    return git(origin, 'rev-parse', 'main')


def state(tid: str) -> str:
    return next(x['state'] for x in reversed(pitch.read()['changes']) if x['id'] == tid)


def open_all() -> list[str]:
    """Open every group (as if long quiet), published by a stub; the open pitches."""
    pitch.tick(now=time.time() + 3600, publish=lambda f, u: 'https://claude.ai/artifact/abc', background=False)
    return [p['id'] for p in pitch.open_pitches()]


def of(tid: str) -> str:
    return next(x['pitch'] for x in reversed(pitch.read()['changes']) if x['id'] == tid)


def test_off(tmp: Path):
    print('approve = false: a merge is pushed as ever')
    repo, origin = make(tmp, 'off', '')
    check(not pitch.on(), 'approve is off by default')
    head = work(repo, 'F1')
    eq(remote(origin), head, 'main is pushed after the merge')
    eq(pitch.read()['changes'], [], 'nothing waits')
    eq((pitch.rows(), pitch.waiting_line()), ([], ''), 'no pitch, no line')
    r = run(repo, 'pitch')
    check(r.returncode == 1 and 'off' in r.stderr, '`pitch` says it is off', r.stderr)


def test_held(tmp: Path):
    print('approve = true: nothing reaches the remote')
    repo, origin = make(tmp, 'held')
    start = remote(origin)
    part = pitch.part_file('F1')
    part.write_text(json.dumps({'what': 'The menu <opens> `fast`', 'why': 'less waiting', 'try': 'open the run page',
                                'risk': 'nothing known', 'before': 'slow', 'after': 'fast'}), encoding='utf-8')
    eq(pitch.part_problem('F1'), '', 'F1 wrote its part')
    has(pitch.part_problem('F2'), 'needs what, why, try, risk', 'F2 did not, and that is said')
    head = work(repo, 'F1')
    eq(remote(origin), start, 'no push after a merge')
    eq(state('F1'), 'waiting', 'F1 waits')
    eq(pitch.waiting_line(), '1 change waits to be pushed', 'and is counted')
    has(status.status_text(False, {}, [], {}, 0), '1 change waits to be pushed', 'status says it')
    from agent_runner import gitops
    git(repo, 'branch', 'task/F2')
    eq(gitops.push(repo, 'task/F2'), '', 'a task branch is not pushed')
    eq(git(origin, 'for-each-ref', '--format=%(refname)'), 'refs/heads/main', 'the remote has main only')
    from agent_runner import plansync
    check(not plansync.enabled(R.C), 'nor a claim')
    git(repo, 'branch', '-D', 'task/F2')
    eq(P._push(repo), '', 'a plan edit is not pushed either')
    eq(remote(origin), start, 'the remote is as it was')
    eq(sched.unpushed(), 1, 'the release has one change to wait for')
    h = sched.Held([], [], set(), set(), set(), {}, set())
    eq(sched.holds(('V1', '', set(), set()), set(), h), ('unpushed', None), 'a release is held while it waits')
    eq(sched.holds(('F2', '', set(), set()), set(), h), None, 'another task is not')
    eq(open_all(), ['pitch1'], 'its pitch opens')
    page = (repo / '.runner/concepts/pitch1.html').read_text(encoding='utf-8')
    for w in ('The menu &lt;opens&gt; <code>fast</code>', 'less waiting', 'open the run page', 'nothing known', 'slow'):
        check(w in page, f'the page says {w!r}', page)
    check(page.index('ui/menu.py') > page.index('nothing known'), 'the files come last')
    row = status.waiting_ok()[-1]
    eq(row[:2] + (row[4],), ('PITCH', 'pitch1', 'https://claude.ai/artifact/abc'), 'it is under Needs you')
    need = U.needs_rows([row], dt.datetime.now())[0][0]
    eq((need['options'], [c['id'] for c in need['changes']]), (['Approve', 'Not this: reopen', 'Not this: drop'], ['F1']), 'with its answers')
    ev = [e for e in status.read_events() if e['kind'] == pitch.EV_PITCH]
    eq(len(ev), 1, 'one event is logged for the phone')
    has(status.needs_you_line(json.dumps(ev[0]), {}, dt.datetime.now(), []) or '', r'needs you: Approve 1 change',
        'which the needs-you feed pushes')
    open_all()
    eq(len([e for e in status.read_events() if e['kind'] == pitch.EV_PITCH]), 1, 'said once')
    eq(U.answer_argv('pitch1', 'Approve', True)[0], ['pitch', 'approve', 'pitch1'], 'Approve runs the command')
    eq(U.answer_argv('pitch1', 'Not F1: drop', True)[0], ['pitch', 'no', 'pitch1', '--drop', 'F1'], 'so does Not this')
    eq(U.answer_argv('pitch1', 'Not this: reopen', True)[0], ['pitch', 'no', 'pitch1'], 'for all of it too')
    eq(U.pitch_no('pitch1', 'drop', 'F1')['code'], 3, 'Not this asks first')
    r = run(repo, 'pitch', 'approve', 'pitch1')
    eq(r.returncode, 0, 'approved: ' + r.stdout + r.stderr)
    eq(remote(origin), head, 'and pushed up to its merge')
    eq(sched.unpushed(), 0, 'nothing is held now')
    eq(sched.holds(('V1', '', set(), set()), set(), h), None, 'and the release may start')


def test_groups(tmp: Path):
    print('grouping and what opens a pitch')
    repo, _ = make(tmp, 'groups', 'approve = true\napprove_batch = 3\n')
    for t in ('F1', 'F2', 'F3', 'F4', 'F5'):
        work(repo, t)
    got = [[x['id'] for x in g] for g in pitch.groups(pitch.read()['changes'])]
    eq(got, [['F1', 'F2'], ['F3'], ['F4', 'F5']], 'one file together, unrelated apart, a follower with what it follows')
    ch = lambda i, *f: {'id': i, 'files': list(f), 'waits': []}
    eq(len(pitch.groups([ch('A1', 'src/a.py'), ch('A2', 'tests/test_a.py')])), 1, 'a module and its tests')
    eq(len(pitch.groups([ch('A1', 'x/util.py'), ch('A2', 'y/util.py')])), 2, 'not two files of one name')
    eq(len(pitch.groups([ch('A1', 'src/a.py'), ch('A2', 'src/b.py')])), 1, 'one directory')
    eq(len(pitch.groups([ch('A1', 'tests/test_a.py'), ch('A2', 'tests/test_b.py')])), 2, 'but not tests/')
    eq(len(pitch.groups([ch('A1', 'CHANGELOG.md', 'x/a.py'), ch('A2', 'CHANGELOG.md', 'y/b.py')], {'CHANGELOG.md'})),
       2, 'nor a shared file')
    now = time.time()
    eq(pitch.open_due(now), [], 'nothing opens: not quiet, none of 3 tasks')
    eq(pitch.open_due(now + 29 * 60), [], 'nor after 29 minutes')
    eq(len(pitch.open_due(now + 31 * 60)), 3, 'after 31 quiet minutes each group opens')
    repo, _ = make(tmp, 'batch', 'approve = true\napprove_batch = 2\n')
    for t in ('F1', 'F3', 'F2'):
        work(repo, t)
    eq(len(pitch.open_due()), 1, 'two related tasks open theirs at once with approve_batch = 2')
    eq((of('F1'), of('F2'), of('F3')), ('pitch1', 'pitch1', ''), 'and not the unrelated one')


def test_order(tmp: Path):
    print('approving: exactly up to the pitch, in merge order')
    repo, origin = make(tmp, 'order')
    start = remote(origin)
    h1, h3 = work(repo, 'F1'), work(repo, 'F3')
    h4 = work(repo, 'F4')
    eq(len(open_all()), 3, 'three pitches')
    rc, said = pitch.approve(of('F3'))
    eq((rc, remote(origin)), (0, start), 'the second is held: the first waits')
    has(said, rf'not pushed yet.*{of("F1")} landed before it', 'and says which to approve')
    has(pitch.ask_of(of('F1'), pitch.read()), rf'{of("F3")} is approved and waits for this one', 'so does its item')
    rc, said = pitch.approve(of('F1'))
    eq((rc, remote(origin)), (0, h3), 'approving the first pushes both, and not the third')
    eq((state('F1'), state('F3'), state('F4')), ('pushed', 'pushed', 'waiting'), 'the third still waits')
    check(h1 != h3 != h4, 'three heads')
    eq(pitch.also_going(of('F4'), pitch.read()), [], 'nothing else goes out with the third')
    git(repo, 'commit', '-q', '--allow-empty', '-m', 'later, by hand')
    pitch.approve(of('F4'))
    eq(remote(origin), h4, 'a later commit does not go out with it')
    check(pitch.approve('pitch1')[0] == 1, 'answered once')


def test_died(tmp: Path):
    print('a run that dies as a merge lands, and commits no task made')
    repo, origin = make(tmp, 'died')
    (repo / 'hand.py').write_text('x\n')
    git(repo, 'add', '-A'), git(repo, 'commit', '-qm', 'made by hand')
    after, pitch.landed = pitch.landed, lambda *a: None
    try:
        work(repo, 'F1')
    finally:
        pitch.landed = after
    eq(state('F1'), 'landing', 'recorded before it landed')
    pitch.settle()
    eq(state('F1'), 'waiting', 'and found again: it waits')
    open_all()
    eq(pitch.also_going('pitch1', pitch.read()), ['made by hand'], 'the hand commit is named')
    check('made by hand' in (repo / '.runner/concepts/pitch1.html').read_text(), 'on the page')


def test_moved(tmp: Path):
    print('approving when the remote has moved')
    repo, origin = make(tmp, 'moved')
    work(repo, 'F1')
    open_all()
    git(tmp / 'moved', 'clone', '-q', str(origin), 'away')
    away = tmp / 'moved/away'
    (away / 'z.txt').write_text('z\n')
    git(away, 'add', '-A'), git(away, 'commit', '-qm', 'elsewhere'), git(away, 'push', '-q')
    rc, said = pitch.approve('pitch1')
    eq(rc, 1, 'it is not pushed')
    has(said, 'origin/main has moved', 'and says why')
    h3 = work(repo, 'F3')
    eq(pitch.push_approved(), [], 'the merge that takes the remote in is not approved: nothing goes')
    open_all()
    pitch.approve(of('F3'))
    eq((remote(origin), state('F1')), (h3, 'pushed'), 'once it is, both go out')


def test_not_this(tmp: Path):
    print('Not this: undone here by a commit, its task reopened or dropped')
    repo, origin = make(tmp, 'no')
    start = remote(origin)
    work(repo, 'F1', where='top')
    work(repo, 'F2', where='end')
    work(repo, 'F3')
    open_all()
    eq(of('F1'), of('F2'), 'F1 and F2 are one pitch')
    eq(pitch.refuse('pitch1', {'F3': 'reopen'})[0], 1, 'a change of another pitch is refused')
    eq(pitch.refuse('pitch1', {'F1': 'reopen'}, 'wrong colour')[0], 0, 'Not this on F1 alone')
    eq([x['id'] for x in pitch.undoing()], ['F1'], 'it waits to be undone')
    before = git(repo, 'rev-list', '--count', 'main')
    undo.undo_changes('main')
    eq(state('F1'), 'undone', 'undone')
    eq(int(git(repo, 'rev-list', '--count', 'main')), int(before) + 1, 'one commit')
    has(git(repo, 'log', '-1', '--format=%s', 'main'), 'F1: undo, not approved', 'that says so')
    body = (repo / 'ui/menu.py').read_text()
    check('F1' not in body and 'F2' in body, 'F1 is gone, F2 stays', body)
    has((repo / 'plan/TODO.md').read_text(), r'^- \[ \] \*\*F1\*\*.*not approved.*wrong colour', 'F1 is open again')
    check('**F1**' not in (repo / 'plan/DONE.md').read_text(), 'and not in DONE.md')
    eq(state('F2'), 'waiting', 'F2 still waits')
    eq(remote(origin), start, 'nothing is pushed by that')
    rc, said = pitch.approve('pitch1')
    has(said, 'not pushed yet', 'F2 alone would push F1 without its undo: it waits for what is between')
    eq(remote(origin), start, 'so it is held')
    pitch.approve(of('F3'))
    eq(remote(origin), git(repo, 'rev-parse', 'main'), 'with F3 approved, all go out, the undo included')
    check('F1' not in git(origin, 'show', 'main:ui/menu.py'), 'and the remote never shows F1')
    work(repo, 'F4')
    open_all()
    r = run(repo, 'pitch', 'no', of('F4'), '--drop', 'F4')  # no run up: the command undoes it itself
    eq((r.returncode, state('F4')), (0, 'undone'), 'a drop through the command: ' + r.stdout + r.stderr)
    has((repo / 'plan/DONE.md').read_text(), r'\*\*F4\*\*.*dropped: not approved', 'F4 stays closed, as dropped')
    check('F4' not in (repo / 'other/x.py').read_text(), 'and its change is gone')
    eq(pitch.unpushed(), [], 'an undone change holds nothing')


def test_not_undone(tmp: Path):
    print('Not this that cannot be done goes back under Needs you')
    repo, _ = make(tmp, 'stuck')
    work(repo, 'F1', 'aaa')
    work(repo, 'F2', 'bbb', where='aaa')
    open_all()
    pitch.refuse('pitch1', {'F1': 'reopen'})
    undo.undo_changes('main')
    eq(state('F1'), 'waiting', 'it waits again')
    has(pitch.rows()[0][3], r'F1 could not be undone: it conflicts with later work in ui/menu.py', 'with why')
    eq(git(repo, 'status', '--porcelain'), '', 'the main checkout is clean')
    R.C.run['test'] = 'false'
    pitch.refuse('pitch1', {'F2': 'reopen'})
    undo.undo_changes('main')
    R.C.run['test'] = 'true'
    has(pitch.rows()[0][3], r'F2 could not be undone: the tests fail', 'an undo that fails the gate does not land')
    check('bbb' in (repo / 'ui/menu.py').read_text(), 'F2 is still in')


def test_done(tmp: Path):
    print('done in a slot wants the part a person reads')
    repo, origin = make(tmp, 'done')
    git(repo, 'checkout', '-q', '-b', 'task/F1')
    (repo / 'ui/menu.py').write_text('new\n')
    env = {**os.environ, 'AGENT_RUNNER_SLOT': '1'}
    r = run(repo, 'done', 'F1', 'F1: x', env=env)
    check(r.returncode == 2 and 'F1.json' in r.stderr, 'refused without it', r.stdout + r.stderr)
    pitch.part_file('F1').write_text(json.dumps({k: k for k in pitch.PARTS}))
    r = run(repo, 'done', 'F1', 'F1: x', env=env)
    eq(r.returncode, 0, 'taken with it: ' + r.stderr)
    has(r.stdout, 'task/F1 not pushed: .run. approve', 'and says the branch stays here')
    eq(git(origin, 'for-each-ref', '--format=%(refname)'), 'refs/heads/main', 'it did')
    p = R.prompt_for('F1', 1, 1, repo, 'main')
    check('pitches/F1.json' in p.replace('\\', '/') and 'pushes task/' not in p, 'the brief asks for it')


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        return report([lambda: test_off(t), lambda: test_held(t), lambda: test_groups(t), lambda: test_order(t),
                       lambda: test_died(t), lambda: test_moved(t), lambda: test_not_this(t), lambda: test_not_undone(t),
                       lambda: test_done(t)])


if __name__ == '__main__':
    sys.exit(main())
