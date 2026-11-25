#!/usr/bin/env python3
"""The parallel loop's Run object (C9): its state lives on the object and each loop step is a method, each
checked here on its own with the run's collaborators stubbed. The whole loop runs end to end in test_runner.

    python3 tests/test_loop.py          (a temp repo, under a second)
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

from _check import check, eq, git, report

from agent_runner import loop  # noqa: E402
from agent_runner import teardown  # noqa: E402
from agent_runner import runner as R  # noqa: E402


def make(tmp: Path) -> Path:
    repo = tmp / 'proj'
    repo.mkdir()
    git(repo, 'init', '-q', '-b', 'main')
    (repo / 'a.py').write_text('# a\n')
    (repo / '.gitignore').write_text('.runner/\n')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'start')
    return repo


def new_run(slots: int = 2, once: bool = False) -> loop.Run:
    return loop.Run(argparse.Namespace(force=False), slots, once, 'main', 'm', 30, 600, 5)


def stubs(st: ExitStack, said: list, **over) -> dict:
    """Stub the loop module's collaborators; returns the mocks by name."""
    names = dict(log=lambda msg, *kind, **fields: said.append(msg), end_orphans=None, last_words=None, drop_session_tmp=None, git=None,
                 save_leftovers=False, not_attempt=False, cut_off=None, stats='1 min', resumes=0,
                 queue_resume=None, finish=None, stopping=False, forced=False, pick=None, start=None,
                 capped=None, backlog_slots=2, api_down=False, low_disk=False, power_due=False, shut_down=False,
                 idle_line='run idle', clear_stop=None, rc_sweep_stop=None, stopped_by='test', take_end={},
                 park_asked=False)
    names.update(over)
    got = {}
    for k, v in names.items():
        m = v if callable(v) and not isinstance(v, mock.Mock) else mock.Mock(return_value=v)
        got[k] = st.enter_context(mock.patch.object(loop, k, m))
    st.enter_context(mock.patch.object(loop, 'backend', lambda: argparse.Namespace(report_exit=False)))
    return got


def test_state():
    print('Run: the loop state is the object\'s, one slot free per count')
    run = new_run(3)
    for k in ('procs', 'running', 'tried', 'closed', 'free_at', 'merging', 'stall_said',
              'failed_starts', 'foreign', 'waiting'):
        check(hasattr(run, k), f'{k} is on the run')
    eq(sorted(run.free_at), [1, 2, 3], 'a free_at per slot')
    check(not run.idle_said and not run.cap_said and run.held_said == 3, 'nothing said yet')
    for step in ('open', 'tick', 'top', 'slot', 'reap', 'watch_stall', 'held',
                 'resume_queued', 'fill', 'after', 'end'):
        check(callable(getattr(run, step, None)), f'step {step} is a method')


def test_reap():
    print('Run.reap: an ended session is merged and its slot rests; a cut-off one is queued to resume')
    said: list = []
    run = new_run()
    run.procs[1], run.running[1] = (111, 'sid1', 0), ('T1', '', set(), set())
    with ExitStack() as st:
        st.enter_context(mock.patch.object(loop.plat, 'alive', lambda pid: False))
        m = stubs(st, said)
        before = dt.datetime.now()
        eq(run.reap(1), False, 'an ended session: the slot goes on to the next steps')
        check(1 not in run.procs and 1 not in run.running, 'the slot is free')
        eq(run.tried, {'T1'}, 'its task counts as tried')
        eq(len(run.merging), 1, 'its merge thread is kept')
        run.merging[0].join(5)
        eq(m['finish'].call_args.args, ('T1', 1, 'sid1', 'main'), 'the merge finishes that task')
        check(run.free_at[1] >= before + dt.timedelta(seconds=5), 'the slot rests for the pause')
        eq(run.reap(1), False, 'a free slot: nothing to reap')
    run = new_run()
    run.procs[2], run.running[2] = (222, 'sid2', 0), ('T2', '', set(), set())
    with ExitStack() as st:
        st.enter_context(mock.patch.object(loop.plat, 'alive', lambda pid: False))
        m = stubs(st, said, cut_off='usage limit')
        eq(run.reap(2), True, 'cut off: nothing more for this slot this tick')
        eq(m['queue_resume'].call_args.args, ('T2', 2, 'sid2', 'usage limit'), 'it resumes in its slot')
        check(not run.merging and not run.tried, 'neither merged nor tried')


def test_answered_ask_and_tell():
    print('B767: the loop tries a task answered before its block again, and keeps a tell no slot could take')
    said: list = []
    run = new_run()
    run.tried = {'T1', 'T2'}
    with ExitStack() as st:
        stubs(st, said, block_asks=lambda branch, tried: tried.discard('T1'), watch_ci=None, watch_issues=None, stopping=True,
              keep_claims=None, take_keys=None, queued={})
        st.enter_context(mock.patch.object(loop.undo, 'tick', mock.Mock()))
        run.after()
    eq(run.tried, {'T2'}, 'answered: back in the pool')
    with ExitStack() as st:
        m = stubs(st, said, tell_requests={'T9': {'how': 'tell', 'text': 'use red'}}, tell_answer=None)
        st.enter_context(mock.patch.object(loop, 'MUX', argparse.Namespace(typed=False)))
        st.enter_context(mock.patch('agent_runner.asks.log', said.append))
        loop.tells({}, {})
    eq(m['tell_answer'].call_args.args[:2], ('T9', False), 'told false')
    check('T9: not told: use red' in said, 'its words are in the run log', said)


def test_tell_ending_ask():
    print('B770: a tell to a slot whose agent has just run `run ask` waits for the ask to be parked')
    import io
    import json
    import os
    import threading
    import time
    from contextlib import redirect_stderr, redirect_stdout
    from agent_runner import asks
    P, c = loop.P, R.C
    c.todo.parent.mkdir(parents=True, exist_ok=True)
    tid = P.add('F', 'the header colour', todo=c.todo)
    git(c.root, 'add', '-A')
    git(c.root, 'commit', '-qm', 'plan')
    typed: list = []
    mux = argparse.Namespace(typed=True, name='fake', panes=lambda: {'s1': ('/n/slot1.live', os.getpid())},
                             send=lambda hit, text: typed.append(text) or True)
    mark, parked = c.notes('slot1.end'), c.notes(f'{tid}.ask')
    running = {1: (tid, '', set(), set())}
    procs = {1: (os.getpid(), 'sid', 0)}

    def end(how='ask', of=tid):
        mark.write_text(json.dumps({'how': how, 'tid': of, 'text': 'Red or blue?'}), encoding='utf-8')

    def park():  # what `reap` does once the session has ended
        running.clear()
        mark.unlink()
        parked.write_text(json.dumps({'sid': 'sid', 'question': 'Red or blue?', 'slot': 1, 'dirty': False,
                                      'blocked': False}), encoding='utf-8')

    def command(*argv, between=lambda: None, wait=20.0):
        """Run `plan *argv` beside the loop's ticks: the first ones find the request, then `between`, then more."""
        out, rc = io.StringIO(), []

        def cmd():
            rc.append(P.main(list(argv)))
        with redirect_stdout(out), redirect_stderr(out), mock.patch.object(P, 'TELL_WAIT', wait):
            th = threading.Thread(target=cmd)
            th.start()
            req = P.tell_dir(c) / f'{tid}.json'
            until = time.monotonic() + 20
            while not req.exists() and th.is_alive() and time.monotonic() < until:
                time.sleep(0.01)
            loop.tells(procs, running)
            held = req.exists()
            between()
            if wait > 1:
                loop.tells(procs, running)
            th.join(30)
        return rc[0] if rc else None, held, out.getvalue()

    halted = mock.Mock(return_value='halted')
    with ExitStack() as st:
        for m in (mock.patch.object(loop, 'MUX', mux), mock.patch.object(P, 'cfg', lambda *a: c),
                  mock.patch.object(P, 'halt', halted), mock.patch.object(loop, 'log', lambda *a, **k: None),
                  mock.patch.object(asks, 'log', lambda *a, **k: None),
                  mock.patch.object(P, 'run_on', lambda c, t: 's1' if running or mark.exists() else '')):
            st.enter_context(m)
        end()
        rc, held, out = command('tell', tid, 'red', between=park)
        eq((rc, held, typed), (1, True, []), 'held while the session ends, nothing typed, then it fails')
        check('asks the person: Red or blue?' in out and f'confirm {tid} red`' in out, 'with the question and its confirm', out)
        check('plan note' not in out, 'and no note', out)
        check(not c.notes('told', f'{tid}.txt').exists(), 'not kept as told')
        parked.unlink()

        running[1] = (tid, '', set(), set())
        end()
        rc, held, out = command('tell', tid, 'red', wait=0.5)
        eq((rc, held, typed), (1, True, []), 'the session has not ended in time: it fails too')
        check('asks the person: Red or blue?' in out and 'once the session in s1 has ended' in out, 'with the question', out)
        check(not c.notes('told', f'{tid}.txt').exists(), 'not kept as told')
        (P.tell_dir(c) / f'{tid}.json').unlink()

        rc, held, out = command('change', tid, 'use green', between=park)
        eq((rc, held, typed), (0, True, []), 'a change waits too, and is noted')
        check('asks the person: Red or blue?' in out and not halted.called, 'it says the question and halts nothing', out)
        parked.unlink()

        running[1] = (tid, '', set(), set())
        end()
        rc, held, out = command('change', tid, 'use blue', between=lambda: (
            park(), P.block(tid, 'DECIDE: Red or blue?', todo=c.todo, after=[], keep_ask=True)))
        eq((rc, held, typed), (0, True, []), 'the same when the ask is blocked by the next tick')
        check('asks the person: Red or blue?' in out and not halted.called, 'the question, and no halt', out)
        P.unblock(tid, todo=c.todo)
        parked.unlink()

        running[1] = (tid, '', set(), set())
        end()
        with mock.patch.object(loop.plat, 'alive', lambda pid: False):
            rc, held, out = command('tell', tid, 'red', between=park)
        eq((rc, held, typed), (1, True, []), 'the same when its session is dead and not reaped yet')
        check('asks the person: Red or blue?' in out and 'no live pane' not in out and 'plan note' not in out, 'the question', out)
        parked.unlink()

        running[1] = (tid, '', set(), set())
        with mock.patch.object(mux, 'send', lambda hit, text: end() or True):
            rc, held, out = command('tell', tid, 'red', between=park)
        eq((rc, held), (1, True), 'asked as the text was typed: not told either')
        check('asks the person: Red or blue?' in out, 'the question', out)
        parked.unlink()

        running[1] = (tid, '', set(), set())
        for how, of in (('finish', tid), ('wait', tid), ('ask', 'F99')):
            end(how, of)
            typed.clear()
            rc, held, out = command('tell', tid, 'red')
            eq((rc, held, len(typed)), (0, False, 1), f'a mark of {how} by {of}: typed as before')
        mark.unlink()
        c.notes('told', f'{tid}.txt').unlink()


def test_reap_finish_and_ask():
    print('Run.reap (F102): a finish logs its summary and merges; an ask parks the task instead of merging it')
    said: list = []
    run = new_run()
    run.procs[1], run.running[1] = (111, 'sid1', 0), ('T1', '', set(), set())
    with ExitStack() as st:
        st.enter_context(mock.patch.object(loop.plat, 'alive', lambda pid: False))
        m = stubs(st, said, take_end={'how': 'finish', 'tid': 'T1', 'text': 'the parser reads lists'},
                  park_asked=True)
        eq(run.reap(1), False, 'finished: the slot goes on')
        run.merging[0].join(5)
        check(any('T1 finished: the parser reads lists' in s for s in said), 'the summary is in the run log', said)
        check(m['finish'].called and not m['park_asked'].called, 'and it merges as any ended session')
    run = new_run()
    run.procs[1], run.running[1] = (111, 'sid1', 0), ('T1', '', set(), set())
    with ExitStack() as st:
        st.enter_context(mock.patch.object(loop.plat, 'alive', lambda pid: False))
        m = stubs(st, said, take_end={'how': 'ask', 'tid': 'T1', 'text': 'plain or coloured?'}, park_asked=True,
                  cut_off='usage limit')
        eq(run.reap(1), False, 'asked: the slot is free')
        eq(m['park_asked'].call_args.args, (1, 'T1', 'sid1', 'plain or coloured?', 'main'), 'the task is parked')
        check(not run.merging and not m['queue_resume'].called, 'neither merged nor queued to resume')
        eq(run.tried, {'T1'}, 'and no other slot starts it this run')
    run = new_run()
    run.procs[1], run.running[1] = (111, 'sid1', 0), ('T1', '', set(), set())
    with ExitStack() as st:  # F168
        st.enter_context(mock.patch.object(loop.plat, 'alive', lambda pid: False))
        m = stubs(st, said, take_end={'how': 'wait', 'tid': 'T1', 'text': 'phone'}, cut_off='usage limit')
        park = st.enter_context(mock.patch.object(loop.shared_tools, 'park', mock.Mock(return_value=True)))
        eq((run.reap(1), park.call_args.args), (False, (1, 'T1', 'sid1', 'phone')), 'waits for a tool: the slot is free')
        check(not run.merging and not m['queue_resume'].called and not run.tried,
              'neither merged, queued nor tried: it goes on by itself')


def test_fill():
    print('Run.fill: the free slot takes the next task; a start that fails is tried again after the pause')
    said: list = []
    task = ('T1', 'the parser', set(), set())
    run = new_run()
    with ExitStack() as st:
        stubs(st, said, pick=task, start=(5, 'sid', 0))
        run.idle_said = True
        run.fill(1)
        eq(run.procs.get(1), (5, 'sid', 0), 'started')
        eq(run.running.get(1), task, 'with its task')
        check(not run.idle_said and any('run busy' in s for s in said), 'the idle run says it is busy')
    run = new_run()
    with ExitStack() as st:
        st.enter_context(mock.patch.object(loop.plansync, 'release', lambda *a: None))
        stubs(st, said, pick=task, start=None)
        run.fill(1)
        eq(run.failed_starts, {'T1': 1}, 'the failed start is counted')
        check(1 not in run.procs and run.free_at[1] > dt.datetime.now(), 'the slot waits before trying again')
        check('T1' not in run.tried, 'not tried yet')
    run = new_run()
    with ExitStack() as st:
        m = stubs(st, said, pick=task, start=(5, 'sid', 0), stopping=True)
        run.fill(1)
        check(not run.procs and not m['pick'].called, 'a stop starts nothing')


def test_end():
    print('Run.end: idle is said once; `once` ends; a drained stop ends the run')
    said: list = []
    run = new_run()
    with ExitStack() as st:
        stubs(st, said)
        eq(run.end(), None, 'idle: the run goes on')
        check(run.idle_said and said.count('run idle') == 1, 'and says so', said)
        eq(run.end(), None, 'still idle')
        eq(said.count('run idle'), 1, 'said once')
    with ExitStack() as st:
        stubs(st, said)
        eq(new_run(once=True).end(), 0, '`once` with nothing to start ends')
    with ExitStack() as st:
        m = stubs(st, said, stopping=True)
        st.enter_context(mock.patch.object(loop, 'POWER', ''))
        eq(new_run().end(), 0, 'a stop with nothing running or merging ends the run')
        check(m['clear_stop'].called and m['rc_sweep_stop'].called, 'clearing the stop and the feed')
        busy = new_run()
        busy.procs[1] = (1, 's', 0)
        eq(busy.end(), None, 'a stop waits for the running sessions')


def test_stop_ends_own_b144():
    print('B144: `run stopped` is said only once the board, control server and page are gone; a start right '
          'after a stop waits for that run to end')
    import subprocess
    said: list = []
    order: list = []
    board = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    try:
        R.C.notes('board.live').write_text(str(board.pid))
        page = mock.Mock(stop=lambda: order.append('page'))
        loop.PAGE[:] = [page]
        with ExitStack() as st:
            stubs(st, said, stopping=True, rc_sweep_stop=lambda: order.append('remote'),
                  log=lambda msg, *a, **k: order.append(msg))
            st.enter_context(mock.patch.object(loop, 'POWER', ''))
            st.enter_context(mock.patch.object(teardown, 'kept_page', lambda say: False))  # the handover: test_page_only
            st.enter_context(mock.patch.object(loop.plat, 'alive', lambda pid: board.poll() is None and pid == board.pid))
            eq(new_run().end(), 0, 'a drained stop ends the run')
        stopped = next(i for i, m in enumerate(order) if m.startswith('run stopped'))
        check(order.index('remote') < stopped and order.index('page') < stopped, 'feed, server and page first', order)
        check(board.poll() is not None, 'the board ended before `run stopped`')
        eq(loop.PAGE, [], 'the page is closed and dropped')
    finally:
        board.kill()
        board.wait()
        R.C.notes('board.live').unlink(missing_ok=True)
        loop.PAGE.clear()

    print('B144: a start while the old run still holds run.lock and is stopping waits, then takes it')
    held = R.plat.lock(R.C.notes('run.lock'))
    check(held is not None, 'the old run holds the lock')
    ticks = [0]

    def sleep(_s):  # the old run's process ends on the third look
        ticks[0] += 1
        if ticks[0] == 3:
            held.close()
    with mock.patch.object(teardown, 'stopping', lambda: True), mock.patch.object(teardown.time, 'sleep', sleep):
        got = teardown.wait_last_run(5)
    check(got is not None and ticks[0] == 3, 'it waited for the old run, then took the lock', ticks)
    got.close()
    held = R.plat.lock(R.C.notes('run.lock'))
    with mock.patch.object(teardown, 'stopping', lambda: False), mock.patch.object(teardown, 'last_event_stopped', lambda: False), \
            mock.patch.object(teardown.time, 'sleep', lambda s: (_ for _ in ()).throw(AssertionError('waited'))):
        try:
            teardown.wait_last_run(5)
            check(False, 'a run that is up and not stopping is refused')
        except SystemExit as e:
            check('another run is going' in str(e), 'refused at once, as before', e)
    held.close()


def main() -> int:
    with tempfile.TemporaryDirectory() as t:
        R.init(make(Path(t)))
        return report([test_state, test_reap, test_answered_ask_and_tell, test_tell_ending_ask, test_reap_finish_and_ask, test_fill, test_end, test_stop_ends_own_b144])


if __name__ == '__main__':
    sys.exit(main())
