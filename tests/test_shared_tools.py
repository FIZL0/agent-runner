#!/usr/bin/env python3
"""F168: shared tools ([run.tools]): a task waits for one without holding a slot.

    python3 tests/test_shared_tools.py        (a temp repo, a fake lock command, a few seconds)
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import time
from pathlib import Path

from _check import check, eq, git, report

from agent_runner import config as CF, plan as P, plat, runner as R, sched, slots, tools, ui_model as U  # noqa: E402
from agent_runner import shared_tools as T, status  # noqa: E402

CF.FIXED['merge_ahead'] = False
LOCK = Path()  # the fake lock: 'busy F9', 'missing unplugged', 'fail', 'hang'; no file: free
TODO = ('# TODO\n\n### Next\n\n- [ ] **T1** on the phone | files: a.py | needs: phone\n'
        '- [ ] **T2** also on the phone | files: b.py | needs: phone\n- [ ] **T3** no phone | files: c.py\n')


def lock(said: str = '') -> None:
    LOCK.write_text(said, encoding='utf-8')


def line(*words) -> str:
    """A check's command line, each word quoted for the shell: Python's own path may have a space."""
    return ' '.join(plat.quote(str(w).replace('\\', '/')) for w in words)


def make_repo(tmp: Path) -> Path:
    global LOCK
    repo = tmp / 'proj'
    (repo / 'plan').mkdir(parents=True)
    git(repo, 'init', '-q', '-b', 'main')
    LOCK = tmp / 'lock'
    lock()
    fake = tmp / 'lock.py'
    fake.write_text('import sys, time\n'
                    f'w, _, who = open({str(LOCK)!r}).read().partition(" ")\n'
                    'if w == "hang": time.sleep(30)\n'
                    'if who: print(who)\n'
                    'sys.exit({"": 0, "busy": 75, "missing": 69}.get(w, 1))\n', encoding='utf-8')
    (repo / 'plan/TODO.md').write_text(TODO, encoding='utf-8')
    (repo / 'plan/DONE.md').write_text('# DONE\n', encoding='utf-8')
    (repo / 'runner.toml').write_text('[run]\ntest = "true"\nmin_free_gb = 0\nremote = false\n[run.tools.phone]\n'
                                      f'check = {json.dumps(line(sys.executable, fake))}\n'
                                      'label = "iPhone 15"\nconnect = "Connect the iPhone 15 by USB"\n', encoding='utf-8')
    (repo / '.gitignore').write_text('.runner/\n', encoding='utf-8')
    for f in 'abc':
        (repo / f'{f}.py').write_text(f'# {f}\n', encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'start')
    return repo


def fresh(repo: Path, said: str = '') -> None:
    R.init(repo)
    T.stop()
    for f in T.S.C.notes().glob('*.wait'):
        f.unlink()
    lock(said)


def reads(*at: float) -> None:
    """One check per time in `at`."""
    for t in at:
        T.once('phone', t)


def first(running=None, claim=False):
    got = sched.pick(running or {}, set(), 'main', claim=claim)
    return got and got[0]


def task(tid: str) -> tuple:
    return next(t for t in sched.tasks('main') if t[0] == tid)


def test_config(repo: Path):
    print('config and plan: a tool needs a check; needs: is written, kept, and refused when unknown')
    for bad in ({'x': {}}, {'x': 'cmd'}, {'x': {'check': 'a', 'wat': 'b'}}, {'a b': {'check': 'a'}}):
        check(CF.tools_problem(bad), f'refused: {bad}')
    eq(CF.tools_problem({'x': {'check': 'a'}}), '', 'a name and a check are enough')
    fresh(repo)
    cwd = os.getcwd()
    os.chdir(repo)
    try:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            bad = P.main(['add', 'F', 'try it on a device', '--files', 'z.py', '--needs', 'tablet'])
            ok = P.main(['add', 'F', 'try it on a device', '--files', 'z.py', '--needs', 'phone'])
            bad2 = P.main(['edit', 'T3', '--needs', 'tablet'])
            ok2 = P.main(['edit', 'T3', 'now on the phone', '--needs', 'phone'])
            P.main(['T3'])
        eq((bad, ok, bad2, ok2), (2, 0, 2, 0), 'unknown names are refused, known ones taken')
        check('the project has: phone' in err.getvalue(), 'with the known ones', err.getvalue())
        check('now on the phone | files: c.py | needs: phone' in out.getvalue(), 'plan ID shows it', out.getvalue())
    finally:
        os.chdir(cwd)
        (repo / 'plan/TODO.md').write_text(TODO, encoding='utf-8')
        git(repo, 'commit', '-qam', 'plan as it was')


def test_busy_and_together(repo: Path):
    print('busy at the start: the next task starts; two tagged tasks never run together; the holder itself passes')
    fresh(repo, 'busy F389')  # no such task here: a holder outside the run
    reads(time.time())
    eq(first(claim=True), 'T3', 'T1 and T2 wait, T3 starts')
    eq(sched.explain({}, set(), 'main')['T1'], ('waiting for iPhone 15', 'held by F389, 0 min'), 'the dry run says why')
    lock()
    reads(time.time())
    eq(first(claim=True), 'T1', 'free: T1 starts')
    eq(first({1: task('T1')}, claim=True), 'T3', 'beside it T2 waits, T3 starts')
    eq(sched.explain({1: task('T1')}, set(), 'main')['T2'], ('waiting for iPhone 15', 'held by T1'), 'held by T1')
    lock('busy T1 pid 4')
    reads(time.time())
    eq(first(), 'T1', 'a task that holds the lock itself is not held by it')
    lock('busy T12')
    reads(time.time())
    eq(first(), 'T3', 'T12 is not T1')


def test_stale(repo: Path):
    print('a stale free answer starts nothing: the tool is checked again right before')
    fresh(repo)
    reads(time.time())
    lock('busy someone')
    eq(first(), 'T1', 'the last reading says free')
    eq(first(claim=True), 'T3', 'but the start checks again')


def test_missing(repo: Path):
    print('missing: held, back by itself, a blip does not flap, one Needs you item that clears')
    fresh(repo, 'missing unplugged')
    t = time.time()
    reads(t - 600)
    eq(first(), 'T3', 'missing at the start holds the tagged tasks')
    eq([a[1] for a in T.asks()], ['tool-phone'], 'it is a Needs you item, once though checked again')
    reads(t)
    eq(U.need_label('tool-phone'), 'TOOL', 'the pages know it as one')
    eq((T.asks()[0][0], T.asks()[0][3]), ('TOOL', 'Connect the iPhone 15 by USB: 2 tasks wait'), 'in plain words')
    said = (repo / '.runner/run.log').read_text(encoding='utf-8').count('Connect the iPhone 15 by USB')
    eq(said, 1, 'said once')
    check(any('tool-phone' == a[1] for a in status.waiting_ok()), 'status and needs list it')
    eq(T.line(T.rows()), 'Tools: iPhone 15: unplugged, 10 min, 2 tasks wait', 'the Tools line')
    lock()
    reads(t + 1)
    eq(first(), 'T3', 'one good reading is not back yet')
    reads(t + 2)
    eq((first(), T.asks()), ('T1', []), 'the second is: the task starts and the item is gone')
    lock('missing unplugged')
    reads(t + 3)
    eq((T.seen()['phone']['state'], T.pause('phone')), ('free', T.SOON), 'a blip changes nothing, checked again soon')
    eq(first(claim=True), 'T3', 'yet no task starts on it')
    lock()
    reads(t + 4)
    eq(T.seen()['phone']['since'], t + 1, 'and the spell goes on')
    lock('busy F9')
    reads(t + 5)
    T.READINGS['phone']['since'] = t - 9999
    eq(T.asks(), [], 'a busy tool is never a Needs you item')


def test_unknown(repo: Path):
    print('a check that fails or hangs: unknown, said once, holds no longer than UNKNOWN_HOLD')
    fresh(repo, 'fail')
    t = time.time()
    reads(t, t + 1)
    check(T.pending(), 'the run is not idle while it holds them')
    eq(T.seen()['phone']['state'], 'unknown', 'it fails')
    eq(first(), 'T3', 'it holds the tagged tasks at first')
    log = (repo / '.runner/run.log').read_text(encoding='utf-8')
    eq(log.count('iPhone 15: unknown'), 1, 'said once')
    T.READINGS['phone']['since'] = t - T.UNKNOWN_HOLD - 1
    check(not T.pending(), 'nothing is pending on it any more')
    eq((first(), first(claim=True)), ('T1', 'T1'), 'then they start all the same')
    eq(T.wait_words(), {}, 'and nothing says they wait')
    fresh(repo)
    for i, w in enumerate(['', '', 'fail', '', 'fail', '', 'fail']):
        lock(w)
        reads(t + i)
    eq(first(claim=True), 'T3', 'a check that fails now and then holds a start too')
    eq(T.seen()['phone']['shaky'], t + 2, 'counted from its first failure')
    T.READINGS['phone']['shaky'] = t - T.UNKNOWN_HOLD - 1
    eq(first(claim=True), 'T1', 'but no longer than one that always fails')
    lock()
    reads(t + 8, t + 9)
    eq(T.seen()['phone']['shaky'], 0, 'steady again: forgotten')
    keep, T.CHECK_TIMEOUT = T.CHECK_TIMEOUT, 0.5
    try:
        lock('hang')
        t0 = time.monotonic()
        eq(T.check('phone')[0], 'unknown', 'one that hangs is stopped')
        check(time.monotonic() - t0 < 10, 'at its timeout')
    finally:
        T.CHECK_TIMEOUT = keep


def agent(d: Path, *argv: str) -> tuple[int, str]:
    """`run wait-for` as slot 1's agent runs it in `d`."""
    cwd, out = os.getcwd(), io.StringIO()
    os.environ['AGENT_RUNNER_SLOT'] = '1'
    os.chdir(d)
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            return T.cmd_wait_for(list(argv)), out.getvalue()
    finally:
        os.chdir(cwd)
        os.environ.pop('AGENT_RUNNER_SLOT')


def test_quoted(tmp: Path):
    print('a check whose program and argument have a space in their quoted path')
    repo = tmp / 'spaced'
    (repo / 'plan').mkdir(parents=True)
    git(repo, 'init', '-q', '-b', 'main')
    (repo / 'plan/TODO.md').write_text(TODO, encoding='utf-8')
    (repo / 'plan/DONE.md').write_text('# DONE\n', encoding='utf-8')
    d = tmp / 'with space'
    d.mkdir()
    tool = d / ('tool.cmd' if plat.WINDOWS else 'tool')
    tool.write_text('@type %1\n@exit 75\n' if plat.WINDOWS else '#!/bin/sh\ncat "$1"\nexit 75\n', encoding='utf-8')
    tool.chmod(0o755)
    who = d / 'the holder'
    who.write_text('F9\n', encoding='utf-8')
    # a literal string, as a person writes it: the quotes around each path, and backslashes on Windows
    (repo / 'runner.toml').write_text('[run]\nremote = false\n[run.tools.phone]\n'
                                      f"check = '\"{tool}\" \"{who}\"'\n", encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'start')
    fresh(repo)
    eq(T.check('phone'), ('busy', 'F9'), 'it runs, with its argument and its exit code')


def test_wait_for(repo: Path, tmp: Path):
    print('wait-for: the slot is given up, the work kept; the same session goes on first once free, over a restart')
    fresh(repo)
    d = R.worktree(1, 'main')
    git(d, 'checkout', '-q', '-B', 'task/T2', 'main')
    (d / 'b.py').write_text('# half\n', encoding='utf-8')
    git(d, 'commit', '-qam', 'T2: half')
    (d / 'new.py').write_text('# not committed\n', encoding='utf-8')
    eq(agent(d, 'nope')[0], 2, 'an unknown tool is refused')
    rc, said = agent(d, 'phone')
    eq((rc, tools.ended(1, R.C)), (0, False), 'free: the session goes on')
    lock('busy T2')
    eq((agent(d, 'phone')[0], tools.ended(1, R.C)), (1, False), 'a session that holds it itself is refused')
    lock('busy F389')
    reads(time.time())
    eq(agent(d, 'phone')[0], 0, 'busy: it waits')
    end = tools.take_end(1, R.C)
    eq((end['how'], end['tid'], end['text']), ('wait', 'T2', 'phone'), 'the end mark says so')
    check(T.park(1, 'T2', 'sid-w', 'phone'), 'the run parks it')
    eq((git(repo, 'branch', '--list', 'task/T2'), sched.parked_attempts()), ('', {}), 'never merged, no park count')
    eq(status.waiting_ok(), [], 'not a Needs you item')
    eq(T.wait_words()['T2'], 'waits for iPhone 15, held by F389, 0 min', 'the pages say what it waits on')
    row = next(q for q in U.queue_rows(P.lines(R.C.todo), {}) if q['id'] == 'T2')
    eq((row['state'], row['tool_wait']), ('tool', 'waits for iPhone 15, held by F389, 0 min'), 'the queue row too')
    eq(first(), 'T3', 'another task takes the slot')
    check(T.pending(), 'and the run is not idle meanwhile')
    lock('missing unplugged')
    t = time.time()
    reads(t - 400, t - 399, t)
    eq((first(), [a[1] for a in T.asks()], T.wait_words()['T2'][:38]),
       ('T3', ['tool-phone'], 'waits for iPhone 15, unplugged, 6 min'), 'gone while T2 waits: it waits on, asked once due')
    lock('busy F389')
    reads(t, t)
    d2 = R.worktree(2, 'main')  # a run that crashed as it woke T2
    git(d2, 'checkout', '-q', '-B', 'task/T2', 'waiting/T2')
    T.settle_ended([1, 2])
    eq((git(repo, 'branch', '--list', 'task/T2'), list(T.parked())), ('', ['T2']), 'a start cut short: T2 waits still')
    T.READINGS.clear()  # a run that starts again
    T.settle_ended([1])
    reads(time.time())
    eq((list(T.parked()), first()), (['T2'], 'T3'), 'a restart keeps it waiting')
    lock()
    reads(time.time())
    eq((first(), sched.explain({}, set(), 'main')['T1'][1]), ('T2', 'T2 goes first'), 'free: ahead of T1')
    old = tmp / 'projects/-old/sid-w.jsonl'
    old.parent.mkdir(parents=True)
    old.write_text('{}\n', encoding='utf-8')
    opened = []

    class Mux:
        name = 'fake'

        def open(self, *a, **kw):
            opened.append((a, kw))
            return 4343

        def where(self, n):
            return f'slot {n}'
    mux, R.MUX, find = R.MUX, Mux(), slots.Claude.find_transcript
    slots.Claude.find_transcript = lambda self, sid: str(old) if sid == 'sid-w' and old.exists() else None
    try:
        got = R.start(2, task('T2'), 'main', 'opus', 90, 2)
    finally:
        R.MUX, slots.Claude.find_transcript = mux, find
    d2 = R.SLOTS_DIR / 's2'
    eq((got and got[:2], opened and opened[0][1].get('resume')), ((4343, 'sid-w'), True), 'the same session resumes')
    check('iPhone 15 is yours' in opened[0][0][2] and 'another worktree' in opened[0][0][2], 'told why and where')
    eq((git(d2, 'log', '-1', '--format=%s'), (d2 / 'b.py').read_text(), git(d2, 'status', '--porcelain')),
       ('T2: half', '# half\n', '?? new.py'), 'with its commit and its edits as they were')
    eq((git(repo, 'branch', '--list', 'waiting/T2'), T.parked(), T.holding('T2')), ('', {}, 'phone'),
       'it waits no more, and has the tool')
    eq(first({2: ('T2', '', set(), set())}), 'T3', 'so T1 does not start beside it')
    T.forget('T2')
    eq(T.holding('T2'), '', 'until its session ends')
    git(d2, 'checkout', '-q', '-f', '--detach', 'main')
    git(d2, 'clean', '-fdq')
    git(repo, 'branch', '-D', 'task/T2')


def test_order_and_drop(repo: Path):
    print('several waiting wake in order; a dropped one is forgotten; a tool gone from runner.toml holds nothing')
    fresh(repo, 'busy F9')
    for tid, at in (('T2', 1.0), ('T1', 2.0)):
        git(repo, 'branch', '-f', f'waiting/{tid}', 'main')
        T.mark(tid).write_text(json.dumps({'tool': 'phone', 'sid': 's', 'at': at}), encoding='utf-8')
    lock()
    reads(time.time())
    eq((first(), first({1: task('T2')})), ('T2', 'T3'), 'the longest wait first, one at a time')
    eq(sched.explain({}, {'T2'}, 'main')['T1'], ('free', ''), 'one that cannot start does not hold the next')
    (repo / 'plan/DONE.md').write_text('# DONE\n\n- [x] **T2** — dropped: no\n', encoding='utf-8')
    T.prune()
    eq((list(T.parked()), git(repo, 'branch', '--list', 'waiting/T2')), (['T1'], ''), 'the dropped one is gone')
    (repo / 'plan/DONE.md').write_text('# DONE\n', encoding='utf-8')
    keep, R.C.run['tools'] = R.C.run['tools'], {'pad': {'check': 'true'}}
    try:
        eq(sched.explain({}, set(), 'main')['T1'], ('free', ''), 'a removed tool holds nothing')
    finally:
        R.C.run['tools'] = keep
    T.forget('T1')


def test_background(repo: Path):
    print('the run\'s own checker: a thread per tool, woken by a start; TOOLS.json for the pages')
    fresh(repo)
    T.start()
    end = time.monotonic() + 20
    while 'phone' not in T.READINGS and time.monotonic() < end:
        time.sleep(0.05)
    eq(T.seen()['phone']['state'], 'free', 'it reads the tool by itself')
    lock('busy F9')
    eq(first(claim=True), 'T3', 'a start wakes it, and a stale answer starts nothing')
    check((repo / '.runner/TOOLS.json').exists(), 'the pages read TOOLS.json')
    T.stop()
    check(not T.THREADS and not (repo / '.runner/TOOLS.json').exists(), 'stopped, both are gone')


def test_after_and_release(repo: Path):
    print('--after and a release behave as before in a project with shared tools')
    todo = repo / 'plan/TODO.md'
    was = todo.read_text(encoding='utf-8')
    try:
        todo.write_text('# TODO\n\n## Now\n- [ ] **T7** Uses it. | files: a.py | needs: phone\n'
                        '- [ ] **T8** Later. | files: b.py | after: T7\n- [ ] **V1** Release. | after: all\n', encoding='utf-8')
        git(repo, 'commit', '-qam', 'after')
        fresh(repo, 'busy F9')
        reads(time.time())
        eq(first(), None, 'the tagged one waits, and what waits on it, and the release behind them')
        lock()
        reads(time.time())
        eq(first(), 'T7', 'free: the first starts')
        eq(first({1: task('T7')}), None, 'the others still wait for it')
    finally:
        todo.write_text(was, encoding='utf-8')
        git(repo, 'commit', '-qam', 'back')


def test_without(tmp: Path):
    print('a project without the setting: nothing new')
    repo = tmp / 'plain'
    (repo / 'plan').mkdir(parents=True)
    git(repo, 'init', '-q', '-b', 'main')
    (repo / 'plan/TODO.md').write_text(TODO, encoding='utf-8')
    (repo / 'plan/DONE.md').write_text('# DONE\n', encoding='utf-8')
    (repo / 'runner.toml').write_text('[run]\nremote = false\n', encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'start')
    R.init(repo)
    T.stop()
    T.start()
    eq((T.THREADS, T.rows(), T.line([]), T.asks(), T.brief('run', 'T1'), T.pending()), ({}, [], '', [], '', False),
       'no checker, line, item or brief')
    eq((first(), first({1: task('T1')})), ('T1', 'T2'), 'and a needs: left on a line holds nothing')
    check('tool_wait' not in U.queue_rows(P.lines(R.C.todo), {})[0], 'queue rows as before')


def meminfo(avail_gb: float) -> None:
    Path(os.environ['AGENT_RUNNER_MEMINFO_DIR'], 'meminfo').write_text(
        f'MemTotal: {32 * 2 ** 20} kB\nMemAvailable: {int(avail_gb * 2 ** 20)} kB\n', encoding='utf-8')


def test_memory(tmp: Path):
    print('B184 memory: a session stopped for low memory parks, never under Needs you, and goes on once there is some')
    repo = tmp / 'low'
    (repo / 'plan').mkdir(parents=True)
    git(repo, 'init', '-q', '-b', 'main')
    (repo / 'plan/TODO.md').write_text(TODO, encoding='utf-8')
    (repo / 'plan/DONE.md').write_text('# DONE\n', encoding='utf-8')
    (repo / 'runner.toml').write_text('[run]\ntest = "true"\nmin_free_gb = 0\nremote = false\n', encoding='utf-8')
    (repo / '.gitignore').write_text('.runner/\n', encoding='utf-8')
    for f in 'abc':
        (repo / f'{f}.py').write_text(f'# {f}\n', encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'start')
    fresh(repo)
    check(CF.tools_problem({'memory': {'check': 'a'}}), 'no shared tool may take the name')
    log = lambda: (repo / '.runner/run.log').read_text(encoding='utf-8')
    told = lambda: log().count('T2 stopped for low memory') + log().count('for memory; it goes on by itself')
    d = R.worktree(1, 'main')
    git(d, 'checkout', '-q', '-B', 'task/T2', 'main')
    (d / 'b.py').write_text('# half\n', encoding='utf-8')
    opened = []

    class Mux:
        name = 'fake'

        def open(self, *a, **kw):
            opened.append((a, kw))
            return 4343

        def where(self, n):
            return f'slot {n}'
    mux, find, pause = R.MUX, slots.Claude.find_transcript, T.MEMORY_PAUSE
    old = tmp / 'projects/-low/sid-m.jsonl'
    old.parent.mkdir(parents=True)
    old.write_text('{}\n', encoding='utf-8')
    R.MUX = Mux()
    slots.Claude.find_transcript = lambda self, sid: str(old) if sid == 'sid-m' else None
    try:
        meminfo(12)
        eq((agent(d, 'memory')[0], tools.ended(1, R.C)), (0, False), 'free by now: the first stop keeps the slot')
        meminfo(5)  # over the floor (4), not comfortably
        eq((agent(d, 'memory')[0], tools.take_end(1, R.C)['text']), (0, 'memory'), 'short: it waits')
        check(T.park_end(1, 'T2', 'sid-m', {'how': 'wait', 'tid': 'T2', 'text': 'memory'}), 'the run parks it')
        eq((status.waiting_ok(), P.asks(R.C.todo)), ([], []), 'not a Needs you item')
        eq(T.wait_words()['T2'], 'waits for memory, 5.0 GB free, goes on at 6.0 GB', 'the pages say what it waits on')
        row = next(q for q in U.queue_rows(P.lines(R.C.todo), {}) if q['id'] == 'T2')
        eq((row['state'], row['tool_wait'][:17]), ('tool', 'waits for memory,'), 'the queue row too')
        check(P._tool_waits(R.C, R.C.todo)['T2'].startswith('waits for memory'), 'and plan')
        check(T.low_memory(), 'no new session takes what it waits for')
        keep, T.MEMORY_LONG = T.MEMORY_LONG, 0.0
        eq(T.low_memory(), False, 'but not for ever')
        T.MEMORY_LONG = keep
        check(any('T2 waits for memory' in x for x in status.tool_lines({})), 'and status')
        eq((first(claim=True), T.pending()), ('T1', True), 'another task takes the slot; the run is not idle')
        eq(sched.explain({}, set(), 'main')['T2'][0], 'waiting for memory', 'the dry run says why')
        T.settle_ended([1])
        eq(list(T.parked()), ['T2'], 'a restart keeps it waiting')

        meminfo(12)
        eq(first(claim=True), 'T1', 'free, but not before its pause')
        T.MEMORY_PAUSE = 0
        eq(first(claim=True), 'T2', 'then it goes first')
        T.MEMORY_PAUSE, T.MEMORY_WOKEN[0] = 60, time.time()
        T.mark('T2').write_text(json.dumps({**T.parked()['T2'], 'at': time.time() - 999}), encoding='utf-8')
        eq(T.memory_hold('T2'), 'another task just went on', 'one at a time')
        T.MEMORY_PAUSE = 0
        got = R.start(2, task('T2'), 'main', 'opus', 90, 2)
        eq((got and got[1], opened[0][1].get('resume')), ('sid-m', True), 'the same session resumes')
        check('Memory is free again' in opened[0][0][2] and 'Run the command again now' in opened[0][0][2], 'told so')
        eq(((R.SLOTS_DIR / 's2/b.py').read_text(), T.parked(), T.holding('T2')), ('# half\n', {}, ''),
           'its work is there; nobody has the memory')
        eq(first({2: task('T2')}), 'T1', 'so others start beside it')
        eq(told(), 0, 'nothing said about two stops')

        meminfo(1)  # low throughout
        eq(agent(R.SLOTS_DIR / 's2', 'memory')[0], 0, 'stopped a third time')
        check(T.park(2, 'T2', 'sid-m', 'memory'), 'parked again')
        for t in (0, 1, 5000, 9000):
            T.say_memory(time.time() + t)
        eq((list(T.parked()), told(), status.waiting_ok()), (['T2'], 1, []), 'still waiting, told once, not Needs you')
        check('stopped for low memory 3 times' in log(), 'how often', log()[-400:])
        T.S.C.notes('T2.mem').unlink()
        for t in (60, 5000, 9000):
            T.say_memory(time.time() + t)
        eq(told(), 2, 'a first wait that lasts is said once too')

        check(T.low_memory() and T.low_memory(), 'under the floor no session starts')
        eq(log().count('GB): no new session starts until there is more'), 1, 'said once')
        os.environ['AGENT_RUNNER_SLOT'] = '1'
        keep, T.GATE_WAIT = T.GATE_WAIT, 0.0
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            T.gate_wait(R.C)
        check('the gate starts once there is more' in out.getvalue(), 'a gate waits, no longer than its deadline')
        T.GATE_WAIT = keep
        meminfo(12)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            T.gate_wait(R.C)
        eq((out.getvalue(), T.low_memory()), ('', False), 'with memory neither is held')
        (repo / 'plan/DONE.md').write_text('# DONE\n\n- [x] **T2** done\n', encoding='utf-8')
        T.prune()
        check(not T.parked() and not T.S.C.notes('T2.mem').exists(), 'done: its wait and its count go')
        from agent_runner import brief
        check('wait-for memory' in brief.PROMPT and 'standing go-ahead' in brief.PROMPT, 'the brief has the go-ahead')
    finally:
        os.environ.pop('AGENT_RUNNER_SLOT', None)
        R.MUX, slots.Claude.find_transcript, T.MEMORY_PAUSE = mux, find, pause
        meminfo(16)


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp_:
        tmp = Path(tmp_)
        repo = make_repo(tmp)
        return report([lambda: test_config(repo), lambda: test_busy_and_together(repo), lambda: test_stale(repo),
                       lambda: test_missing(repo), lambda: test_unknown(repo), lambda: test_wait_for(repo, tmp),
                       lambda: test_order_and_drop(repo), lambda: test_background(repo), lambda: test_after_and_release(repo),
                       lambda: test_without(tmp), lambda: test_quoted(tmp), lambda: test_memory(tmp)])


if __name__ == '__main__':
    sys.exit(main())
