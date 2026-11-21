#!/usr/bin/env python3
"""F19: a style approved for the future too.

    python3 tests/test_restyle.py        (no network; a few seconds, mostly git)

`plan restyle STYLE --page URL` files the restyle as a concept waiting for an OK and holds every queued task that
touches the interface on it; a task a slot runs is held too and the run parks it as wip/<ID> at a clean point (one
whose `done` already passed lands, noted on the restyle); approving the restyle reopens them all with the style
in their note.
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from unittest import mock

from _check import check, eq, git, has, report, run

import test_runner as TR  # noqa: E402  (its make_repo: a throwaway repo with a bare origin)
from agent_runner import loop as L  # noqa: E402
from agent_runner import plan as P  # noqa: E402
from agent_runner import runner as R  # noqa: E402
from agent_runner import sched  # noqa: E402

URL = 'https://claude.ai/code/artifact/restyle1'
STYLE = 'option B: dark cards, rounded corners'


def test_plan_restyle():
    print('plan: restyle holds the queued interface tasks, not the others; approving it reopens them with the style')
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        git(root, 'init', '-q')
        (root / 'runner.toml').write_text('[plan]\n', encoding='utf-8')
        (root / '.gitignore').write_text('.runner/\n', encoding='utf-8')
        (root / 'plan').mkdir()
        todo, done = root / 'plan' / 'TODO.md', root / 'plan' / 'DONE.md'
        todo.write_text('# TODO\n\n### Next\n\n'
                        '- [ ] **F1** the settings screen | files: web/settings.html\n'
                        '- [ ] **F2** the parser | files: src/parse.py\n'
                        '- [ ] **F3** the menu | files: src/menu.tsx\n'
                        '- [ ] **B4** the button colours on the start page\n'
                        '- [~] **F5** the login form | files: web/login.html BLOCKED: DECIDE: which provider\n'
                        '- [ ] **K6** a concept for the help page | files: web/help.html\n', encoding='utf-8')
        done.write_text('# DONE\n', encoding='utf-8')
        git(root, 'add', '-A'); git(root, 'commit', '-qm', 'start')
        env = {**os.environ, 'AGENT_RUNNER_REPO': str(root)}
        env.pop('AGENT_RUNNER', None)

        r = run(root, 'plan', 'restyle', STYLE, '--dry', env=env)
        eq(r.returncode, 0, 'restyle --dry goes through')
        eq(re.findall(r'^(\w+)  queued', r.stdout, re.M), ['F1', 'F3', 'B4'],
           'it lists the queued tasks that touch the interface: by files, or by words when a line names none')
        eq(git(root, 'status', '--porcelain'), '', '--dry changes nothing')
        eq(run(root, 'plan', 'restyle', STYLE, env=env).returncode, 2, 'no --page: refused')

        with mock.patch.dict(os.environ, {'AGENT_RUNNER_REPO': str(root)}):
            got = P.restyle(STYLE, URL, 'K1', running=lambda t: {'F3': 's2', 'B4': 'merging'}.get(t, ''),
                            todo=str(todo), done=str(done))
            eq(got['held'], ['F1'], 'the queued interface task is held')
            eq(got['park'], ['F3'], 'the running one is held too, for the run to park')
            eq(got['landing'], ['B4'], 'the merging one lands in the old style')
            rid, bid = got['rid'], got['build']
            t = todo.read_text(encoding='utf-8')
            has(done.read_text(encoding='utf-8'), rf'- \[x\] \*\*{rid}\*\* Restyle to the style approved on K1 .*'
                rf'concept page: {re.escape(URL)}', 'the restyle is a concept already shown: ticked with its page')
            has(t, rf'^- \[~\] \*\*{bid}\*\* Build the option a person approves on concept {rid}\'s page: Restyle.*'
                rf'\| files: src/menu\.tsx, web/settings\.html BLOCKED: waiting for your OK on {re.escape(URL)} .*'
                rf'— {re.escape(P.LANDED_OLD)}B4$', 'its build waits for the OK, on the held tasks\' interface files, '
                'with the merging task listed')
            for tid in ('F1', 'F3'):
                has(t, rf'^- \[~\] \*\*{tid}\*\* .* BLOCKED: held for restyle {rid} \(style: {re.escape(STYLE)}\): '
                       'reopens', f'{tid} held on the restyle, kept in TODO.md')
            for tid in ('F2', 'B4'):
                has(t, rf'^- \[ \] \*\*{tid}\*\*', f'{tid} untouched')
            has(t, r'^- \[~\] \*\*F5\*\* .*BLOCKED: DECIDE: which provider$', 'a task blocked on a person stays as it is')
            has(t, r'^- \[ \] \*\*K6\*\*', 'a concept is not held: it builds nothing')
            eq(P.reopen(str(todo)), [], 'reopen never frees a held task: the restyle\'s concept is ticked already')
            eq([(a[0], a[1]) for a in P.asks(str(todo))], [('CONCEPT', bid), ('DECIDE', 'F5')],
               'Needs you lists the restyle, and no held task as stuck')
            eq(sorted(x[0] for x in P.held_on({rid}, str(todo))), ['F1', 'F3'], 'held_on finds them')

            P.approve(rid, 'as shown', todo=str(todo))
            eq(sorted(P.FREED), ['F1', 'F3'], 'approving the restyle reopens what it held')
            t = todo.read_text(encoding='utf-8')
            for tid in ('F1', 'F3'):
                has(t, rf'^- \[ \] \*\*{tid}\*\* .* — style to use \(restyle {rid} approved\): {re.escape(STYLE)}; '
                       r'as approved: as shown$', f'{tid} open again with the style in its note')
            has(t, rf'^- \[ \] \*\*{bid}\*\* .*approved', 'and the restyle build opens')

        print('plan: restyle on the command line commits, and names what it held')
        todo.write_text(todo.read_text(encoding='utf-8') + '- [ ] **F7** the about page | files: web/about.html\n',
                        encoding='utf-8')
        git(root, 'commit', '-qam', 'F7')
        r = run(root, 'plan', 'restyle', 'flat', '--page', URL, '--tasks', 'F7', env=env)
        check(r.returncode == 0, 'restyle goes through', r.stdout + r.stderr)
        has(r.stdout, r'restyle K\d+ filed .*\nheld until it is approved: F7$', 'it says what it filed and held')
        eq(git(root, 'status', '--porcelain'), '', 'and commits it')
        has(todo.read_text(encoding='utf-8'), r'^- \[~\] \*\*F7\*\* .*held for restyle K\d+ \(style: flat\)',
            '--tasks names the tasks to hold')


def test_run_parks(repo: Path, tmp: Path):
    print('run: a running interface task is told to stop at a clean point, then parked as wip/<ID>, held')
    R.init(repo)
    todo, done = repo / 'plan/TODO.md', repo / 'plan/DONE.md'
    got = P.restyle(STYLE, URL, 'K1', ids=['T2'], running=lambda t: 's1', todo=str(todo), done=str(done))
    rid = got['rid']
    eq(got['park'], ['T2'], 'T2, running, is held for the run to park')
    git(repo, 'add', '-A'); git(repo, 'commit', '-qm', 'plan: restyle')
    git(repo, 'branch', 'task/T2', 'main')
    d = tmp / 'wt-T2'
    git(repo, 'worktree', 'add', '-q', str(d), 'task/T2')
    (d / 'b.py').write_text('# the printer, half done\n', encoding='utf-8')
    git(d, 'commit', '-qam', 'T2 printer: half of it')
    git(repo, 'worktree', 'remove', '--force', str(d))

    sent = []

    class Mux:
        typed, name = True, 'tmux'

        def panes(self):
            return {'s1': ('%1', os.getpid())}

        def send(self, hit, text):
            sent.append((hit, text))
            return True

    P.request(R.C, 'restyle', 'T2', {'rid': rid, 'style': STYLE}, 0)
    with mock.patch.object(L, 'MUX', Mux()):
        L.restyles({1: (os.getpid(), 'sid', None)}, {1: ('T2', '', set(), set())}, 'main')
    eq(len(sent), 1, 'the run types one message into the slot\'s pane')
    has(sent[0][1], r'Stop at a clean point.*let it finish.*commit what is solid.*journal.*wip/T2',
        'telling it to stop at a clean point, commit and write its journal (or let a running gate finish)')
    has((R.C.notes('restyle') / 'T2.done').read_text(encoding='utf-8'), r'told s1 \(T2\) to stop at a clean point',
        'and answers the restyle command')
    eq(L.restyle_mark('T2'), {'rid': rid, 'how': 'park'}, 'marked to park when its session ends')

    eq(L._finish('T2', 1, 'sid', 'main'), True, 'its session ends: finished, not left waiting')
    heads = set(git(repo, 'for-each-ref', '--format=%(refname:short)', 'refs/heads/').split())
    check('wip/T2' in heads and 'task/T2' not in heads, 'parked as wip/T2, not merged', heads)
    eq(git(repo, 'log', '-1', '--format=%s', 'wip/T2'), 'T2 printer: half of it', 'with its commits')
    check('T2' not in sched.parked_attempts(), 'a restyle park is no failed merge: it does not count to the limit')
    eq(L.restyle_mark('T2'), {}, 'its mark is gone')
    has(todo.read_text(encoding='utf-8'), rf'^- \[~\] \*\*T2\*\* .*held for restyle {rid}', 'still held in the plan')

    print('run: one whose done already passed lands, and is listed on the restyle')
    R.finished_mark(1).touch()
    P.request(R.C, 'restyle', 'T1', {'rid': rid, 'style': STYLE}, 0)
    with mock.patch.object(L, 'MUX', Mux()):
        L.restyles({1: (os.getpid(), 'sid', None)}, {1: ('T1', '', set(), set())}, 'main')
    R.finished_mark(1).unlink()
    eq(len(sent), 1, 'nothing typed: it is not stopped')
    eq(L.restyle_mark('T1'), {'rid': rid, 'how': 'land'}, 'marked to land')
    L.restyle_landed('T1', rid)
    has(todo.read_text(encoding='utf-8'), rf'^- \[~\] \*\*{got["build"]}\*\* .*{re.escape(P.LANDED_OLD)}T1',
        'noted on the restyle\'s waiting build, for its page')
    eq(git(repo, 'status', '--porcelain'), '', 'in a commit')
    R.C.notes('T1.restyle').unlink()

    print('run: approving the restyle reopens the parked task with the style noted')
    P.approve(rid, todo=str(todo))
    has(todo.read_text(encoding='utf-8'), rf'^- \[ \] \*\*T2\*\* .* — style to use \(restyle {rid} approved\): '
        rf'{re.escape(STYLE)}$', 'T2 open again with the style in its note, its earlier attempt on wip/T2')


def main() -> int:
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        repo = TR.make_repo(tmp)
        return report([test_plan_restyle, lambda: test_run_parks(repo, tmp)])


if __name__ == '__main__':
    import sys
    sys.exit(main())
