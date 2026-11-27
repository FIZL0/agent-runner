#!/usr/bin/env python3
"""F429: a held task keeps its place in the queue and is skipped (`plan hold`, `plan unhold`).

    python3 tests/test_row_hold.py        (a temp repo, a few seconds)
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

from _check import RUN, check, eq, git, has, report

from agent_runner import autorelease as A, plan as P, row_hold as H, runner as R, sched, tui, ui_model as U, web as W  # noqa: E402
from _web import logic_js  # noqa: E402

TODO = """# TODO

### Next

- [ ] **T1** first thing | files: a.py | after: T9 — a note
- [ ] **T2** second thing | files: b.py
- [ ] **T3** third thing | files: c.py | after: T2
- [ ] **V1** Release | after: all
- [ ] **T4** fourth thing | files: d.py

### Parked

### Stretch
"""
TOML = '[run]\ntest = "true"\nremote = false\nmin_free_gb = 0\nauto_release = { every = 2 }\n'


def cmd(*args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(RUN), *args], cwd=R.ROOT, capture_output=True, text=True,
                          env={**os.environ, 'AGENT_RUNNER_REPO': str(R.ROOT)}, encoding='utf-8')


def fresh():
    R.C.todo.write_text(TODO, encoding='utf-8')
    git(R.ROOT, 'commit', '-qam', 'fresh', '--allow-empty')


def save():
    git(R.ROOT, 'commit', '-qam', 'edit', '--allow-empty')


def line(tid: str) -> str:
    return P.section(R.C.todo, tid)[0]


def order() -> list[str]:
    return [tid for _, _, tid, _, _ in P.iter_tasks(P.lines(R.C.todo))]


def test_commands():
    print('plan hold and unhold write and clear the mark, where the task stands')
    fresh()
    before = line('T1')
    r = cmd('plan', 'hold', 'T1')
    eq((r.returncode, H.is_held(line('T1'))), (0, True), f'held {r.stderr}')
    eq(order(), ['T1', 'T2', 'T3', 'V1', 'T4'], 'it keeps its place')
    has(line('T1'), r'— a note', 'its words stay')
    has(git(R.ROOT, 'log', '-1', '--format=%s'), 'hold T1', 'committed')
    has(cmd('plan', 'hold', 'T1').stdout, 'held already', 'twice')
    P.edit('T1', 'other words | held: no | files: z.py', todo=R.C.todo)
    check(H.is_held(line('T1')), 'an edit keeps it')
    P.move('T1', 'bottom', todo=R.C.todo)
    check(H.is_held(line('T1')), 'and a move')
    cmd('plan', 'unhold', 'T1')
    check(not H.is_held(line('T1')), 'unheld')
    fresh()
    cmd('plan', 'hold', 'T1')
    cmd('plan', 'unhold', 'T1')
    eq(sorted(line('T1').split()), sorted(before.split()), 'unhold gives the line back')
    has(cmd('plan', 'unhold', 'T1').stdout, 'is not held', 'not held')
    r = cmd('plan', 'hold', 'Z9')
    check(r.returncode and 'no task' in r.stderr, 'no such task', r.stderr)
    tid = P.add('T', 'quotes | held: yes', todo=R.C.todo)
    check(not H.is_held(line(tid)), 'no new task is held')
    P.edit('T2', 'words | held: yes', todo=R.C.todo)
    check(not H.is_held(line('T2')), 'nor by an edit')


def test_under_way():
    print('a running, taken or finished task cannot be held')
    fresh()
    with mock.patch.object(P, 'run_on', lambda c, t: 's2'):
        eq(H.under_way(R.C, 'T2'), 's2 is on it', 'running')
    with mock.patch.object(sched, 'taken', lambda: {'T2': Path('x')}):
        eq(H.under_way(R.C, 'T2'), 'it is taken by hand', 'taken')
    resume = R.C.notes('T2.resume')
    resume.write_text('{"slot": 1, "sid": "x", "why": "cut off"}', encoding='utf-8')
    eq(H.under_way(R.C, 'T2'), 'it waits to resume', 'cut off, no run up')
    resume.unlink()
    P.block('T4', 'CONFIRM: look', todo=R.C.todo)
    save()
    r = cmd('plan', 'hold', 'T4')
    check(r.returncode and 'is blocked' in r.stderr, 'one that waits for the person', r.stderr)
    fresh()
    eq(H.under_way(R.C, 'T2'), '', 'free')
    git(R.ROOT, 'checkout', '-qb', 'task/T2')
    (R.ROOT / 'b.py').write_text('x\n', encoding='utf-8')
    git(R.ROOT, 'add', 'b.py')
    git(R.ROOT, 'commit', '-qm', 'T2')
    git(R.ROOT, 'checkout', '-q', 'main')
    r = cmd('plan', 'hold', 'T2')
    check(r.returncode == 1 and 'waits to merge' in r.stderr, 'finished', r.stderr)
    git(R.ROOT, 'branch', '-qD', 'task/T2')


def test_pick():
    print('a run skips it, and the dry run says why')
    fresh()
    eq(sched.pick({}, set(), 'main')[0], 'T1', 'T1 first')
    H.hold_task('T1', R.C.todo)
    save()
    eq(sched.pick({}, set(), 'main')[0], 'T2', 'then the next')
    eq(sched.explain({}, set(), 'main')['T1'], ('held', '`plan unhold T1` ends it'), 'the dry run')
    eq(P.next_task(R.C.todo), 'T2', 'plan next')
    h = sched.held({}, 'main')
    t = next(t for t in h.todo if t[0] == 'T1')
    eq(sched.holds(t, set(), h._replace(parked={'T1': ['w'] * 99})), ('held', None), 'never blocked on the person while held')
    H.hold_task('T3', R.C.todo)
    save()
    has(cmd('run', '--dry-run').stdout, r'(?m)^held: .*T1 .*T3 ', 'the dry run says it of one that waits too')
    H.unhold_task('T1', R.C.todo)
    save()
    eq(sched.pick({}, set(), 'main')[0], 'T1', 'unheld')


def test_release():
    print('an after: all release does not wait for a held task, nor for one stuck on it')
    fresh()
    H.hold_task('T2', R.C.todo)
    ls = P.lines(R.C.todo)
    i = P._find(ls, 'V1')
    eq(P.before_all(ls, i), ['T1'], 'T1 alone')
    eq(P.not_waiting(P.not_waiting_on(ls, i)), '; not waiting on: T2 (held), T3 (after T2)', 'and it says so')
    H.unhold_task('T2', R.C.todo)
    eq(P.before_all(P.lines(R.C.todo), i), ['T1', 'T2', 'T3'], 'unheld, it waits again')


def test_auto_release():
    print('a held release is not cut, and the count queues none beside it')
    fresh()
    ls = P.lines(R.C.todo)
    eq(A.waiting_releases('main', ls), {'V1'}, 'a waiting one')
    check(U._counts_on(ls, U.release_tasks(ls, {})), 'the count goes on')
    H.hold_task('V1', R.C.todo)
    save()
    ls = P.lines(R.C.todo)
    eq(A.waiting_releases('main', ls), set(), 'a held one hinders the count')
    check(not U._counts_on(ls, U.release_tasks(ls, {})), 'as its row says')
    A.AUTO_RELEASE_SEEN[0] = None
    with mock.patch.object(A, 'landed_since_release', lambda b: ['T7', 'T8', 'T9']):
        eq((A.auto_release('main'), A.auto_release('main', idle=True)), ('', ''), 'nothing cut')
        check(H.is_held(line('V1')) and 'after: all' in line('V1'), 'the release is as it was')
        H.unhold_task('V1', R.C.todo)
        save()
        A.AUTO_RELEASE_SEEN[0] = None
        check(A.auto_release('main'), 'unheld, the count cuts again')


def test_shown():
    print('the queue says held')
    fresh()
    for t in ('T1', 'T2', 'V1'):
        H.hold_task(t, R.C.todo)
    ls = P.lines(R.C.todo)
    rows = {r['id']: r for r in U.queue_rows(ls, {'running': {'1': 'T2'}})}
    eq([(rows[t]['state'].split()[0], rows[t].get('held', False)) for t in ('T1', 'T2', 'V1', 'T4')],
       [('held', True), ('running', True), ('held', True), ('ready', False)], 'the rows')
    eq(U.release_rows(ls, {})[0]['words'], 'held', 'a release')
    page = next(c for c in vars(tui).values() if hasattr(c, 'queue_tag'))
    eq(page.queue_tag(None, rows['T1']), ('held', 'dim'), 'the terminal UI')
    eq([w for w in P.waiting(R.C.todo) if w[1] == 'T1'], [], 'off Needs you')


def test_way():
    print('B846: a task under way with no slot on it says how, and which chat took it')
    fresh()
    notes, pid = R.C.notes, os.getpid()
    for f in notes().glob('control*'):
        f.unlink()
    live = {}  # {N: title}: control_titles, as the live sessions

    def rows(st=None):
        with mock.patch.object(U, 'control_titles', lambda: dict(live)):
            return {r['id']: r for r in U.queue_rows(P.lines(R.C.todo), st or {})}

    def way(tid, st=None):
        return rows(st)[tid].get('way')

    def take(tid, n='', slot=''):
        with mock.patch.dict(os.environ, {'AGENT_RUNNER_CONTROL': n, 'AGENT_RUNNER_SLOT': slot, 'AGENT_RUNNER_BY': ''}):
            r = cmd('take', tid)
        eq(r.returncode, 0, f'take {tid} {r.stderr}')

    def chat(n, pid, sid, title):
        notes(f'control{n}.pid').write_text(f'{pid} {sid}', encoding='utf-8')
        live[n] = title
    chat(10, pid, 'sid-a', 'D32 · site')
    take('T2', '10')
    eq(git(sched.taken()['T2'], 'status', '--porcelain'), '', 'no edit in its worktree')
    named = {'words': 'Taken by the chat D32 · site', 'chat': 'c10'}
    eq(way('T2'), named, 'the chat by its name')
    chat(10, pid, 'sid-b', 'D32 · site')
    eq(way('T2'), named, 'after /clear it is the same chat')
    chat(10, pid + 1, 'sid-b', 'control session')
    eq(way('T2'), {'words': 'Taken by the chat Chat 10', 'chat': 'c10'}, 'cleared, then reopened, with no name of its own')
    with mock.patch.object(U, 'chat_row', lambda n, sid: {'renamed': True, 'title': 'Mine'}):
        eq(way('T2')['words'], 'Taken by the chat Mine', "the person's name for it")
    ended = {'words': 'Taken by a chat that has ended'}
    chat(10, pid + 2, 'sid-c', 'another chat')
    eq(way('T2'), ended, 'a later chat with its number is not it')
    live.clear()
    eq(way('T2'), ended, 'ended')
    take('T3')
    take('T4', '10', '2')
    eq([way('T3'), way('T4')], [{'words': 'Taken by hand'}] * 2, 'unknown: from a terminal, or by a slot\'s agent')
    resume = notes('T1.resume')
    resume.write_text('{"slot": 1, "sid": "x", "why": "cut off"}', encoding='utf-8')
    eq(way('T1'), {'words': 'Waits to resume'}, 'waits to resume')
    eq([way('T1', {'merging': ['T1']}), way('T2', {'merging': ['T2']})], [{'words': 'Merging'}] * 2, 'merging')
    chat(10, pid + 1, 'sid-b', 'D32 · site')
    q = rows({'merging': ['T3']})
    if shutil.which('node'):
        eq(logic_js([['planWords', q[t], []] for t in ('T2', 'T3', 'T4', 'T1')]),
           ['Taken by the chat D32 · site', 'Merging', 'Taken by hand', 'Waits to resume'], 'the page says the same')
        live.clear()
        eq(logic_js([['planWords', rows()['T2'], []]]), [ended['words']], 'and of an ended one')
    resume.unlink()
    for t in ('T2', 'T3', 'T4'):
        cmd('take', t, '--drop')
    take('T2')
    eq(way('T2'), {'words': 'Taken by hand'}, 'taken again by hand: nothing left of the first take')
    cmd('take', 'T2', '--drop')
    eq(way('T2'), None, 'free again')


ROW_DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const logic = page.split('<script id="logic">')[1].split('</script>')[0].replace(/if\(typeof module[^\n]*/, '');
const at = page.indexOf('function taskRow('), row = page.slice(at, page.indexOf('\n}\n', at) + 3);
const S = {taskOpen: {}, tasks: {}, snap: {sessions: []}}, I = {chev: '>'}, esc = s => String(s), taskChip = id => id, foldIn = (k, h) => h, taskIsOpen = () => false;
eval(logic + row + 'globalThis.taskRow = taskRow');
console.log(JSON.stringify(JSON.parse(process.argv[3]).map(q => taskRow(q, q.id))));
"""


def test_way_button():
    print('B846: on the page the words that name the chat open it')
    if not shutil.which('node'):
        print('  (no node here: skipped)')
        return
    way = {'words': 'Taken by the chat Mine', 'chat': 'c10'}
    qs = [{'id': 'F1', 'state': 'ready', 'under_way': True, 'way': way}, {'id': 'F2', 'state': 'blocked', 'under_way': True, 'way': way},
          {'id': 'F3', 'state': 'ready', 'under_way': True, 'way': {'words': 'Taken by a chat that has ended'}}]
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / 'row.js').write_text(ROW_DRIVER, encoding='utf-8')
        r = subprocess.run(['node', str(Path(d) / 'row.js'), str(W.PAGE), json.dumps(qs)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node draws the rows', r.stderr[-800:])
    if r.returncode:
        return
    a, b, c = json.loads(r.stdout)
    head, _, after = a.partition('</button>')
    check('Taken by' not in head and 'data-thread="c10"' in after and 'Taken by the chat Mine' in after, 'a button under the head', a)
    check('data-thread' not in b and 'Waits for you' in b, 'not on a row that says something else', b)
    check('data-thread' not in c and 'Taken by a chat that has ended' in c, 'nor for an ended chat', c)


def test_merge():
    print('the plan merge keeps it')
    base = TODO.split('\n')
    held = [l + ' | held: yes' if 'T2' in l and '**T2**' in l else l for l in base]
    noted = [l + ' — n' if '**T2**' in l else l for l in base]
    got = P.merge3(held, base, noted)
    i = next(i for i, l in enumerate(got) if '**T2**' in l)
    check(H.is_held(got[i]) and '— n' in got[i], 'the hold and the note', got[i])


def test_running():
    print('F480: hold on a task a slot runs stops the slot and holds it; a claim from another machine refuses')
    from test_cancel import HELD, Proj
    from agent_runner import plansync
    was = os.environ['AGENT_RUNNER_REPO']
    with tempfile.TemporaryDirectory() as tmp:
        p = Proj(Path(tmp))
        os.environ['AGENT_RUNNER_REPO'] = str(p.repo)
        try:
            p.start()
            rc, out, err = p.cmd('hold', 'H1')
            eq(rc, 0, f'it goes through ({err})')
            has(out, r'cancelled H1; stopped s1', 'the slot is stopped')
            check(p.agent.wait(10) is not None, 'its agent is ended')
            eq((p.procs, p.running), ({}, {}), 'the slot runs nothing')
            has(p.todo(), HELD, 'the line is held in its place')
            p.tick()
            h = sched.held({}, 'main')
            eq(sched.holds(next(t for t in sched.tasks('main') if t[0] == 'H1'), p.tried, h), ('held', None),
               'no run picks it up')
            eq(p.cmd('unhold', 'H1')[0], 0, 'unhold')
            h = sched.held({}, 'main')
            eq(sched.holds(next(t for t in sched.tasks('main') if t[0] == 'H1'), p.tried, h), None, 'then it runs again')
            fake = mock.Mock(who='ryha@omarchy-desktop')
            with mock.patch.object(plansync, 'claims', lambda c: {'H2': fake}), \
                    mock.patch.object(plansync, 'stale', lambda cl: False):
                eq(H.under_way(R.C, 'H2'), "another machine's run has claimed it (ryha@omarchy-desktop)", 'said')
                before = p.todo()
                eq(P.main(['hold', 'H2']), 1, 'refused')
                eq(p.todo(), before, 'nothing changed')
        finally:
            os.environ['AGENT_RUNNER_REPO'] = was
            p.end()


def main() -> int:
    tmp = Path(tempfile.mkdtemp())
    os.environ['AGENT_RUNNER_DEVICES'] = str(tmp / 'devices')
    repo = tmp / 'proj'
    (repo / 'plan').mkdir(parents=True)
    git(repo, 'init', '-q', '-b', 'main')
    for n, text in (('plan/TODO.md', TODO), ('plan/DONE.md', '# DONE\n'), ('runner.toml', TOML), ('.gitignore', '.runner/\n')):
        (repo / n).write_text(text, encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'start')
    os.environ['AGENT_RUNNER_REPO'] = str(repo)
    R.init(repo)
    return report([test_commands, test_under_way, test_pick, test_release, test_auto_release, test_shown, test_way, test_way_button, test_merge, test_running])


if __name__ == '__main__':
    sys.exit(main())
