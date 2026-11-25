"""F170: Stop, Force send, a session's background work and commands, Claude Code's update, the session theme."""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
from pathlib import Path
from unittest import mock

from _check import check, eq, report  # noqa: F401 (sets the suite's own environment first)
from agent_runner import session_now as N, session_theme as T, ui_model as U


class Session:
    """A Claude session that answers keys as Claude Code 2.1.330 does."""

    def __init__(self, status: str = 'busy', queued: int = 0, stuck: bool = False):
        self.status, self.queued, self.stuck, self.got = status, queued, stuck, []

    def keys(self, name: str, text: str = '', key: str = '') -> dict:
        self.got.append(key or text)
        if key in ('Escape', 'C-c') and not self.stuck:
            if self.queued:
                self.queued = 0  # what was queued is its next turn
            else:
                self.status = 'idle'
        return {'ok': True, 'code': 0, 'out': '', 'argv': []}

    def send(self, name: str, text: str) -> dict:
        self.got.append(('sent', text))
        return {'ok': True, 'code': 0, 'out': 'sent', 'argv': []}

    def __enter__(self):
        self.p = [mock.patch.object(U, 'keys', self.keys), mock.patch.object(N, 'status', lambda n: self.status),
                  mock.patch.object(N, 'NEXT_WAIT', 0.2), mock.patch.object(N, 'STOP_WAIT', 0.3)]
        for p in self.p:
            p.start()
        N._STOPPED.clear()
        return self

    def __exit__(self, *a):
        for p in self.p:
            p.stop()


def test_stop_and_force() -> None:
    with Session() as s:
        s.stuck = True
        check(N.stop('c2')['ok'] and N.stop('c2')['ok'], 'Stop while it works')
        eq(s.got, ['C-c'], 'one Ctrl+C: a second press at once sends none')
    for st in ('idle', 'shell', 'waiting'):
        with Session(st) as s:
            eq((N.stop('c2')['ok'], s.got), (False, []), f'never to one that is {st}')
    with Session('') as s:
        eq((N.stop('s2')['ok'], s.got), (True, ['Escape']), 'no status known: Escape, harmless idle')
    with Session('idle') as s:
        eq((N.force_send('c2', 'hi', s.send)['ok'], s.got), (True, [('sent', 'hi')]), 'idle: it just sends')
    with Session() as s:
        N.force_send('c2', 'hi', s.send)
        eq(s.got, ['Escape', '\n', ('sent', 'hi')], 'interrupted, at rest, on a line of its own, sent once')
    with Session(queued=2) as s:
        N.force_send('c2', 'hi', s.send)
        eq(s.got, ['Escape', 'Escape', '\n', ('sent', 'hi')], 'queued messages go in as a turn, interrupted too')
    with Session(stuck=True) as s:
        r = N.force_send('c2', 'hi', s.send)
        check(not r['ok'] and ('sent', 'hi') not in s.got, 'one that never rests gets nothing', s.got)
    with Session() as s:
        N.force_send('c2', '!ls', s.send)
        eq(s.got, ['Escape', '\x13', ('sent', '!ls')], 'a command stands first: what was put back is set aside')
    with Session('idle') as s:
        N.force_send('c2', 'hi', s.send, unsent=True)
        eq(s.got, ['\n', ('sent', 'hi')], 'idle with words left in its input: below them')
    with Session() as s, mock.patch.object(U, 'send', s.send):
        U.act('chat_to', text='hi', to='c2', unsent=True)
        U.act('chat_to', text='hi', to='c2')
        eq(s.got, ['\n', ('sent', 'hi'), ('sent', 'hi')], 'F190a: without force a working session is never interrupted')
    with Session() as s, mock.patch.object(U, 'send', s.send):
        eq((U.act('chat_to', text='hi', to='c2', force=True)['ok'], s.got[-1]), (True, ('sent', 'hi')), 'chat_to force')


def _at(t: float) -> str:
    return time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(t)) + f'.{int(t % 1 * 1000):03d}Z'


def _op(op: str, text=None, at: float = 0, **a) -> dict:
    return {'type': 'queue-operation', 'operation': op, 'timestamp': _at(at or time.time()),
            **({} if text is None else {'content': text}), **a}


def _you(text: str) -> dict:
    return {'type': 'user', 'timestamp': _at(time.time()), 'message': {'content': text}}


def _say(text: str) -> dict:
    return {'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': text}]}}


def test_queued() -> None:
    """F190b: what Claude Code's queue entries leave queued."""
    note = '<task-notification>\n<task-id>b1</task-id>'
    for want, why, rows in (
            (0, 'nothing queued', [_you('hi'), _say('ok')]),
            (1, 'queued', [_you('hi'), _op('enqueue', 'and this')]),
            (2, 'two, one with an image (no content)', [_op('enqueue', 'and this'), _op('enqueue')]),
            (0, 'taken in as the next turn', [_op('enqueue', 'and this'), _op('dequeue'), _you('and this')]),
            (0, 'taken into the turn under way', [_op('enqueue', 'a'), _op('remove', 'a', reason='absorbed_mid_turn')]),
            (1, 'the oldest of two is', [_op('enqueue', 'a'), _op('enqueue', 'b'), _op('dequeue')]),
            (0, 'back in the input', [_op('enqueue', 'a'), _op('popAll', 'a')]),
            (0, "a background event is no sent message", [_op('enqueue', note)]),
            (1, 'an event first, and it is taken first', [_op('enqueue', note), _op('enqueue', 'a'), _op('dequeue')]),
            (1, 'a paste, as a message typed in is', [_op('enqueue', '<pasted_content id="1">\nhi\n</pasted_content id="1">')]),
            (0, 'a wrapped event', [_op('enqueue', f'<pasted_content id="1">\n{note}')])):
        eq(N.queued_in(rows), want, why)
    old = [_op('enqueue', 'a', at=1000.0)]
    eq((N.queued_in(old, 900), N.queued_in(old, 1100)), (1, 0), 'the queue of an earlier process ended with it')


def test_live_queued(tmp: Path) -> None:
    """F190b: the page's word on a session says what is queued, from the transcript: a reload keeps it."""
    f, rec = tmp / 't.jsonl', {'status': 'busy', 'startedAt': (time.time() - 60) * 1000}
    f.write_text(''.join(json.dumps(d) + '\n' for d in (_you('hi'), _op('enqueue', 'and this'))), encoding='utf-8')
    with mock.patch.object(N, 'record', lambda n: rec), mock.patch.object(N, 'transcript', lambda n, r: str(f)):
        eq((N.live('c2')['queued'], N.live('c2')['queued'], N.queued_now('c2')), (1, 1, 1), 'queued, and on every read')
        rec['startedAt'] = (time.time() + 60) * 1000
        eq(N.live('c2')['queued'], 0, 'the same file under a new process')
        rec.update(startedAt=0, status='idle')
        eq(N.live('c2')['queued'], 0, 'never in an idle one')
        rec['status'] = 'busy'
        with open(f, 'a', encoding='utf-8') as o:
            o.write(json.dumps(_op('dequeue')) + '\n')
        eq(N.live('c2')['queued'], 0, 'taken in')
    with mock.patch.object(N, 'record', lambda n: {}):
        eq((N.live('c9')['queued'], N.queued_now('c9')), (0, 0), 'no such session')


class Queue:
    """A session with a transcript that answers Escape and Enter as Claude Code 2.1.331 does. `late`: what is queued
    goes in on its own just before the Escape; `pop`: an Escape pops the queue into the input."""

    def __init__(self, f: Path, queue=(), status='busy', late=False, pop=False, stuck=False, then='idle'):
        self.then = then  # its status once a `late` one is interrupted
        self.f, self.queue, self.status, self.late, self.pop, self.stuck = f, list(queue), status, late, pop, stuck
        self.got, self.input = [], []
        f.write_text('', encoding='utf-8')
        self.add(_you('first'), *(_op('enqueue', q) for q in queue))

    def add(self, *rows) -> None:
        with open(self.f, 'a', encoding='utf-8') as o:
            o.write(''.join(json.dumps(d) + '\n' for d in rows))

    def take(self) -> None:
        self.add(*(_op('dequeue') for _ in self.queue), *(_you(q) for q in self.queue))
        self.queue = []

    def keys(self, name: str, text: str = '', key: str = '') -> dict:
        self.got.append(key or text)
        if key == 'Enter' and self.input:
            self.add(*(_you(x) for x in self.input))
            self.input, self.status = [], 'busy'
        elif key == 'Escape' and not self.stuck:
            if self.late:  # its turn has no answer yet: put back
                self.input, self.status = list(self.queue), self.then
                self.take()
            elif self.pop:
                self.input, self.status, self.queue = self.queue, 'idle', []
                self.add(_you('[Request interrupted by user]'), _op('popAll', '\n'.join(self.input)))
            else:
                self.add(_you('[Request interrupted by user]'))
                self.take()
        return {'ok': True, 'code': 0, 'out': '', 'argv': []}

    def said(self, text: str) -> int:
        return sum(d['message']['content'] == text for d in map(json.loads, self.f.read_text(encoding='utf-8').splitlines())
                   if d['type'] == 'user')

    def __enter__(self):
        self.p = [mock.patch.object(U, 'keys', self.keys), mock.patch.object(N, 'STOP_WAIT', 0.5),
                  mock.patch.object(N, 'record', lambda n: {'status': self.status, 'startedAt': 1}),
                  mock.patch.object(N, 'transcript', lambda n, r: str(self.f)),
                  mock.patch.object(U, 'send', side_effect=AssertionError('text typed'))]
        for p in self.p:
            p.start()
        return self

    def __exit__(self, *a):
        for p in self.p:
            p.stop()


def test_force_queued(tmp: Path) -> None:
    """F190b: a force with no text: one interrupt, and what is queued arrives once; nothing to do, nothing done."""
    f = tmp / 't.jsonl'
    with Queue(f, ['a', 'b']) as s:
        r = U.act('chat_to', to='c2', text='', force=True)
        eq((r['ok'], s.got, s.said('a'), s.said('b'), s.status), (True, ['Escape'], 1, 1, 'busy'), 'one Escape, each arrives once')
        eq((s.said('first'), s.input), (1, []), 'the interrupted prompt stays in the conversation')
        eq((U.act('chat_to', to='c2', text=' ', force=True)['ok'], s.got), (True, ['Escape']), 'again: they are in, nothing done')
    for st, q in (('busy', []), ('idle', []), ('idle', ['a']), ('shell', ['a']), ('waiting', ['a']), ('', ['a'])):
        with Queue(f, q, st) as s:
            r = U.act('chat_to', to='c2', text='', force=True)
            eq((r['ok'], s.got), (True, []), f'nothing done: {st!r} with {q}')
    with Queue(f, ['a'], late=True) as s:
        check(N.force_queued('c2')['ok'], 'taken in just before')
        eq((s.got, s.input, s.status), (['Escape', 'Enter'], [], 'busy'), 'put back unanswered: sent from the input, not lost')
    for then, more in (('waiting', {}), ('idle', {'unsent': True})):
        with Queue(f, ['a'], late=True, then=then) as s:
            N.force_queued('c2', **more)
            eq(s.got, ['Escape'], f'no Enter into a question, nor with words of the person in its input: {then} {more}')
    with Queue(f, ['a'], pop=True) as s:
        check(N.force_queued('c2')['ok'], 'popped into the input')
        eq((s.got, s.said('a'), s.input), (['Escape', 'Enter'], 1, []), 'sent from there, once')
    with Queue(f, ['a'], stuck=True) as s:
        eq((N.force_queued('c2')['ok'], s.got), (False, ['Escape']), 'one that does not stop: said, one Escape')
    with Queue(f, ['a']) as s, mock.patch.object(U, 'keys', lambda *a, **k: {'ok': False, 'code': 1, 'out': 'no', 'argv': []}):
        eq(N.force_queued('c2')['out'], 'no', 'an Escape that does not reach it says why')


def test_force_presses(tmp: Path) -> None:
    """F190b: two presses at once interrupt once."""
    with Queue(tmp / 't.jsonl', ['a']) as s:
        ts = [threading.Thread(target=N.force_queued, args=('c2',)) for _ in range(2)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(10)
        eq((s.got, s.said('a')), (['Escape'], 1), 'one interrupt')


def test_tasks() -> None:
    def use(i, name, **inp):
        return {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'id': i, 'name': name, 'input': inp}]}}

    def result(i, text, **got):
        return {'type': 'user', 'timestamp': '2026-11-23T22:52:26Z', 'toolUseResult': got,
                'message': {'content': [{'type': 'tool_result', 'tool_use_id': i, 'content': text}]}}
    started = 'Command running in background with ID: {0}. Output is being written to: /x/{0}.output. You will'
    rows = [use('1', 'Bash', command='make  test'), result('1', started.format('b1')), use('2', 'Bash', command='sleep'),
            result('2', started.format('b2')), use('3', 'Agent', description='Look'),
            result('3', 'launched', status='async_launched', agentId='a1', description='Look'),
            {'type': 'user', 'message': {'content': '<task-notification>\n<task-id>b1</task-id>\n<status>completed</status>'}},
            use('4', 'TaskStop', task_id='b2')]
    eq([(t['id'], t['kind'], t['name'], t['running']) for t in N.tasks(rows)],
       [('b1', 'shell', 'make test', False), ('b2', 'shell', 'sleep', False), ('a1', 'agent', 'Look', True)], 'shells and agents')


def test_skills(tmp: Path) -> None:
    f = tmp / 't.jsonl'

    def add(**a):
        with open(f, 'a', encoding='utf-8') as o:
            o.write(json.dumps({'type': 'attachment', 'attachment': {'type': 'skill_listing', **a}}) + '\n')
    add(content='- a:one: First\n- two: Second', names=['a:one', 'two'])
    eq(N.skills(str(f)), {'a:one': 'First', 'two': 'Second'}, 'names and words')
    add(content='- three: Third', names=['three'])
    eq(list(N.skills(str(f))), ['a:one', 'two', 'three'], 'what came since')
    eq(N.session_skills('../x'), {}, 'not a session name')


def test_update_and_restart() -> None:
    with mock.patch.object(N.sp, 'run') as run:
        for bad in ('rm -rf /', 'mise upgrade claude; ls', 'claude update --x', ''):
            check(not N.claude_update(bad)['ok'], f'not run: {bad!r}')
        eq(run.call_count, 0, 'nothing but an update command is run')
        run.return_value = mock.Mock(returncode=0, stdout='ok', stderr='')
        check(N.claude_update('mise upgrade claude')['ok'], 'the one its notice names is')
        run.return_value = mock.Mock(returncode=1, stdout='', stderr='no network')
        check('no network' in N.claude_update('claude update')['out'], 'a failure says why')
    check(not N.restart_chat('c1')['ok'] and not N.restart_chat('s1')['ok'], 'c2 and up')
    with mock.patch.object(N, 'record', lambda n: {'status': 'busy', 'pid': 1}), mock.patch.object(N.plat, 'terminate') as end:
        check(not N.restart_chat('c2')['ok'] and not end.called, 'never one that works')
    with mock.patch.object(N, 'record', lambda n: {'status': 'idle', 'pid': 77, 'sessionId': 'sid'}), \
            mock.patch.object(N.plat, 'terminate') as end, mock.patch.object(N.plat, 'alive', lambda p: False), \
            mock.patch.object(U, 'hidden_inbox', lambda n: None), mock.patch('agent_runner.control.transcript', lambda s: 'x'), \
            mock.patch('agent_runner.control.control_keep_sid'), \
            mock.patch('agent_runner.control_reopen.reopen_control', return_value='x') as again:
        check(N.restart_chat('c2')['ok'], 'an idle one restarts')
        eq((end.call_args[0], again.call_args[0]), ((77,), (2, 'sid')), 'its process ends, its conversation comes up again')


def test_theme(tmp: Path) -> None:
    def lum(h):
        c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        c = [x / 12.92 if x <= .03928 else ((x + .055) / 1.055) ** 2.4 for x in c]
        return .2126 * c[0] + .7152 * c[1] + .0722 * c[2]
    slots = [r[i] for r in T.ROLES.values() for i in (0, 1)]
    eq(len(slots), len(set(slots)), 'no slot stands for two roles')
    from agent_runner import web as W
    css = W.PAGE.read_text(encoding='utf-8')  # C41a: the joined page
    grounds = re.findall(r'--bg:(#\w+)', css)
    for look, at, ground in (('dark', 2, grounds[1]), ('light', 3, grounds[0])):
        got = T.page_look(look)
        eq(got['background'], ground, f"the {look} ground is the page's own")
        for k in ('text', 'muted', 'subtle', 'accent', 'accent2', 'ok', 'warn', 'bad', 'link', 'violet', 'pink'):
            a, b = sorted((lum(T.ROLES[k][at]), lum(ground)))
            check((b + .05) / (a + .05) >= 4.5, f'{look} {k} reads at 4.5:1')
        eq((len(got['extendedAnsi']), got['extendedAnsi'][T.ROLES['accent'][0] - 16]), (240, T.ROLES['accent'][at]), 'its slots')
    with mock.patch.dict(os.environ, {'CLAUDE_CONFIG_DIR': str(tmp)}):
        eq(T.settings('dark'), {'theme': 'custom:agent-runner', 'spinnerTipsEnabled': False, 'prefersReducedMotion': True,
                                'bashEditDiffEnabled': False}, 'the settings')
        d = json.loads((tmp / 'themes' / 'agent-runner.json').read_text(encoding='utf-8'))
        eq((d['base'], d['overrides']['success']), ('dark', 'ansi256(108)'), 'the theme file')
        T.settings('light')
        eq(json.loads((tmp / 'themes' / 'agent-runner.json').read_text(encoding='utf-8'))['base'], 'light', 'for light terminals')
        (tmp / 'f').write_text('')
    with mock.patch.dict(os.environ, {'CLAUDE_CONFIG_DIR': str(tmp / 'f')}):
        check('theme' not in T.settings('dark'), 'no file, no theme named')


def test_code_colours() -> None:
    """F182: plain code in a diff is the page's text colour in both looks, and no code colour needs xterm to change it."""
    def lum(h):
        c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        c = [x / 12.92 if x <= .03928 else ((x + .055) / 1.055) ** 2.4 for x in c]
        return .2126 * c[0] + .7152 * c[1] + .0722 * c[2]
    taken = {r[i] for r in T.ROLES.values() for i in (0, 1)}
    for b, base, plain, other in ((0, 'dark', 231, 236), (1, 'light', 236, 231)):
        slots = [n for c in T.CODE.values() for n in c[b]]
        eq((len(slots), taken & set(slots)), (len(set(slots)), set()), f'{base} base: no slot stands for two roles')
        for look, i in (('dark', 2), ('light', 3)):
            got = T.page_look(look, base)
            at = lambda n: got['extendedAnsi'][n - 16]
            eq((at(plain), at(other)), (got['foreground'], T.xterm256(other)), f"{base} base, {look} page: plain code, the other base's slot left alone")
            grounds = [got['background'], *(T.ROLES[k][i] for k in ('add', 'add2', 'gone', 'gone2'))]
            for n in slots:
                for g in grounds:
                    x, y = sorted((lum(at(n)), lum(g)))
                    check((y + .05) / (x + .05) >= 4.5, f'{base} base, {look} page: {n} reads at 4.5:1 on {g}', at(n))
    for look in ('dark', 'light'):  # the base is the person's look unless given
        with mock.patch('agent_runner.session_frame.session_look', lambda: look):
            eq(T.page_look('light'), T.page_look('light', look), f'a person whose terminals are {look}')


def in_tmp(f):
    def run():
        with tempfile.TemporaryDirectory() as d:
            f(Path(d))
    return run


if __name__ == '__main__':
    raise SystemExit(report([test_stop_and_force, test_queued, in_tmp(test_live_queued), in_tmp(test_force_queued),
                             in_tmp(test_force_presses), test_tasks, in_tmp(test_skills), test_update_and_restart, in_tmp(test_theme), test_code_colours]))
