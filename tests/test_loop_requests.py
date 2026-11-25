#!/usr/bin/env python3
"""The run's requests (loop_requests.py, C51): a tell to a slot, checked with the run's collaborators stubbed.

    python3 tests/test_loop_requests.py          (a temp repo, under a second)
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
from _loop_patch import patched
from test_loop import make, new_run, stubs

from agent_runner import loop  # noqa: E402
from agent_runner import loop_after, loop_requests, loop_watch  # noqa: E402
from agent_runner import teardown  # noqa: E402
from agent_runner import runner as R  # noqa: E402



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
        st.enter_context(patched(MUX=mux, log=lambda *a, **k: None))
        for m in (mock.patch.object(P, 'cfg', lambda *a: c),
                  mock.patch.object(P, 'halt', halted),
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


def main() -> int:
    with tempfile.TemporaryDirectory() as t:
        R.init(make(Path(t)))
        return report([test_tell_ending_ask])


if __name__ == '__main__':
    sys.exit(main())
