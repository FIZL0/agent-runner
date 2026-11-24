#!/usr/bin/env python3
"""F65, C44: the run page model: the feed, chatting with a control session, the terminal view and concept copies.

    python3 tests/test_ui_model_chat.py        (a temp repo, no agent, no network)

The fake run and the helpers are in tests/_ui_model.py.
"""
from __future__ import annotations
import json
import os
import time
from pathlib import Path
from unittest import mock
from _check import check, eq, report
from agent_runner import state as S  # noqa: E402
from agent_runner import ui_model as U  # noqa: E402
from _ui_model import in_tmp,NOW, fake_run, ran_by, chat, said  # noqa: E402


def fake_transcript(path: Path) -> Path:
    """A Claude Code JSONL transcript: a person's message, the agent's words, a tool call and its result, a
    runner turn, thinking, a subagent's entry and a torn last line."""
    rows = [
        {'type': 'user', 'message': {'role': 'user', 'content': 'status?'}},
        {'type': 'assistant', 'message': {'content': [{'type': 'thinking', 'thinking': 'hm'},
                                                      {'type': 'text', 'text': 'Checking the run.'},
                                                      {'type': 'tool_use', 'name': 'Bash',
                                                       'input': {'command': './run status -n 20'}}]}},
        {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'content': 'run up: 3 slots\nl2\nl3\nl4'}]}},
        {'type': 'user', 'isMeta': True, 'message': {'content': 'meta'}},
        {'type': 'user', 'message': {'content': '<command-name>/rename</command-name>'}},
        {'type': 'assistant', 'isSidechain': True, 'message': {'content': [{'type': 'text', 'text': 'sub'}]}},
        {'type': 'system', 'content': 'x'},
        {'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': 'Nothing needs you.'}]}},
        {'type': 'user', 'message': {'content': [{'type': 'text', 'text': '[Request interrupted by user]'}]}},
    ]
    path.write_text(''.join(json.dumps(r) + '\n' for r in rows) + '{"type": "assi', encoding='utf-8')
    return path


def test_feed(tmp: Path) -> None:
    """F74: a session's feed is its transcript as say/you/tool/out entries, newest last; a session with no transcript says so."""
    from unittest import mock
    fake_run(tmp)
    t = fake_transcript(tmp / 'c2.jsonl')
    with mock.patch.object(U, 'transcript_of', side_effect=lambda n: str(t) if n == 'c2' else ''), \
            mock.patch.object(U, 'session_sid', return_value=''):
        f = U.feed('c2')
        none = U.feed('s3')
        eq(U.feed('c2', limit=2)['entries'], f['entries'][:1] + f['entries'][-2:],
           'a limit keeps the newest, after the latest prompt (B154)')
        check(U.feed('c2', limit=2)['more'], 'and says older ones were left out')
    eq(f['entries'], [{'kind': 'you', 'text': 'status?'}, {'kind': 'say', 'text': 'Checking the run.'},
                      {'kind': 'tool', 'text': 'Bash(./run status -n 20)'},
                      {'kind': 'out', 'text': 'run up: 3 slots\nl2\nl3\n…'},
                      {'kind': 'say', 'text': 'Nothing needs you.'}, {'kind': 'out', 'text': 'interrupted'}],
       'the feed: you, say, tool, out; meta, runner turns, thinking and subagents left out')
    eq((f['ok'], f['more']), (True, False), 'a whole feed')
    check(not none['ok'] and none['entries'] == [] and 'no transcript' in none['out'], 'no transcript: said', none)
    big = tmp / 'big.jsonl'
    last = json.dumps({'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': 'tail'}]}}) + '\n'
    big.write_text(json.dumps({'type': 'user', 'message': {'content': 'x' * 100}}) + '\n' + last, encoding='utf-8')
    eq([d['type'] for d in U.tail_rows(str(big), nbytes=len(last) + 10)], ['assistant'],
       'a tail read skips the line it cut')


def test_feed_prompt_b154(tmp: Path) -> None:
    """B154: the feed always holds the person's latest prompt, however long the turn after it, and 'more' says the
    tail is cut; a message queued in a turn (an attachment, no user entry) is the person's too; 'at' is when."""
    from unittest import mock
    fake_run(tmp)

    def row(d: dict) -> str:
        return json.dumps(d) + '\n'

    def you(text: str, at: str = '2026-11-23T10:00:00.500Z') -> str:
        return row({'type': 'user', 'timestamp': at, 'message': {'content': text}})

    def say(text: str) -> str:
        return row({'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': text}]}})
    t = tmp / 'c3.jsonl'
    long = ''.join(say(f'step {i} ' + 'x' * 500) for i in range(1000))
    t.write_text(you('first') + you('do it') + row({'type': 'user', 'message': {'content': [
        {'type': 'tool_result', 'content': 'not the person'}]}}) + long, encoding='utf-8')
    at = 1795428000.5
    with mock.patch.object(U, 'transcript_of', return_value=str(t)), mock.patch.object(U, 'session_sid', return_value=''):
        f = U.feed('c3', limit=0)
        eq(f['entries'][0], {'kind': 'you', 'text': 'do it', 'at': at}, 'the latest prompt, before the cut tail')
        eq([e['kind'] for e in f['entries']].count('you'), 1, 'only the latest one')
        check(f['more'], "a cut tail says 'more' with no limit reached", f['more'])
        eq(U.feed('c3')['entries'][0]['text'], 'do it', 'with the page\'s limit too')
        with t.open('a', encoding='utf-8') as fh:
            fh.write(you('and now?') + long)
        eq(U.feed('c3')['entries'][0]['text'], 'and now?', 'a later prompt that the tail leaves behind')
        t.write_text(you('fresh') + long, encoding='utf-8')
        eq(U.feed('c3')['entries'][0]['text'], 'fresh', 'a transcript written anew is read anew')
        q = {'type': 'attachment', 'timestamp': '2026-11-23T10:00:00.500Z', 'attachment': {
            'type': 'queued_command', 'commandMode': 'prompt', 'prompt': 'one more thing'}}
        n = {**q, 'attachment': {**q['attachment'], 'commandMode': 'task-notification'}}
        t.write_text(you('go') + say('ok') + row(q) + row(n), encoding='utf-8')
        f = U.feed('c3')
        eq([(e['kind'], e['text']) for e in f['entries']], [('you', 'go'), ('say', 'ok'), ('you', 'one more thing')],
           'a message queued during a turn is in the feed; a queued notification is not')
        check(not f['more'], 'a whole feed has no more')


def test_chat_at_b154(tmp: Path) -> None:
    """B154: new_control and chat_to say when they ran and what was asked, so a page can tell its message's own entry."""
    from unittest import mock
    fake_run(tmp)
    before, ran, real = time.time(), [], U.RUN[0]
    U.RUN[0] = lambda argv: (ran.append(argv), (0, 'control 3 is starting in a hidden terminal\n'))[1]
    try:
        n = U.act('new_control', ask='theme ideas', wait=False)
        eq((n['name'], n['ask']), ('c3', 'theme ideas'), 'a new chat says what it was asked')
        check(before <= n['at'] <= time.time(), 'and when', n)
        U.act('quick_ask', key='needs'), U.act('concept_chat', cid='K5')
        r = U.act('chat_to', text='hi')
        eq((r['name'], before <= r['at']), ('c3', True), 'no chat named: the new chat that took the message')
        eq([a[-1] for a in ran], ['--no-feed'] * 4, 'every ask from a page or the TUI skips the feed lookup')
    finally:
        U.RUN[0] = real


def test_chat_hold_b158(tmp: Path) -> None:
    """B158: a message to a chat that cannot take input yet is not typed: the run page is told to hold it
    (wait False), any other caller waits; a slot's and a new chat's never wait."""
    from unittest import mock
    from agent_runner import control as K, plat, session_now, slots
    fake_run(tmp)
    typed, ready, real = [], [False], U.RUN[0]
    U.RUN[0] = lambda argv: (0, 'control 3 is starting in a hidden terminal\n')
    try:
        with mock.patch.object(U, 'hidden_inbox', return_value=Path('/x/control3.in')), \
                mock.patch.object(plat, 'WINDOWS', False), \
                mock.patch.object(K, 'control_takes_input', side_effect=lambda n: ready[0]), \
                mock.patch.object(slots, 'send_fifo', side_effect=lambda p, x: (typed.append(x), True)[1]):
            for more in ({}, {'force': True}, {'unsent': True}):
                with mock.patch.object(session_now, 'force_send', side_effect=AssertionError('sent')):
                    r = U.act('chat_to', text='hi', to='c3', wait=False, **more)
                eq((r['ok'], r.get('hold'), typed), (False, True, []), f'held, not typed, while the chat starts {more}')
            with mock.patch.object(U, 'START_WAIT', 0.2):
                r = U.act('chat_to', text='hi', to='c3')
            eq((r['ok'], r.get('hold'), typed), (False, None, []), 'a caller that waits: not delivered, and not held')
            check('starting' in r['out'], 'and says why', r)
            eq(U.act('chat_to', text='new', wait=False).get('hold'), None, 'a new chat is never held')
            check(U.act('chat_to', text='slot', to='s3', wait=False)['ok'], 'nor is a slot')
            typed.clear()
            ready[0] = True
            r = U.act('chat_to', text='hi', to='c3', wait=False)
            eq((r['ok'], typed), (True, ['hi']), 'typed once the chat takes input')
    finally:
        U.RUN[0] = real


def test_chat_force_queued(tmp: Path) -> None:
    """F190b: chat_to with force and no text types nothing: it forces what is queued; only to a named session."""
    from agent_runner import session_now
    fake_run(tmp)
    done = {'ok': True, 'code': 0, 'out': 'x', 'argv': []}
    with mock.patch.object(session_now, 'force_queued', return_value=done) as fq, \
            mock.patch.object(session_now, 'force_send', return_value=done) as fs, \
            mock.patch.object(U, 'send', return_value=done) as sent:
        before = time.time()
        r = U.act('chat_to', text='', to='c3', force=True, unsent=True)
        eq((r['ok'], before <= r['at'], fq.call_args[0], fs.called, sent.called), (True, True, ('c3', True), False, False),
           'no text: the queue is forced, nothing typed')
        eq((U.act('chat_to', text='', force=True)['ok'], fq.call_count, sent.called), (False, 1, False), 'no session, no new chat')
        U.act('chat_to', text='hi', to='c3', force=True)
        eq((fs.call_args[0][:2], fq.call_count), (('c3', 'hi'), 1), 'with text: as before')


def test_chat_and_terminal(tmp: Path) -> None:
    """F74: chat to any control session (none named: SEND; cN typed in through its shim's FIFO), interrupt
    (Escape typed in), a new control session's link, the quick asks to c1, and the terminal view: ttyd,
    install ttyd, or (Windows) the feed only."""
    from unittest import mock
    from agent_runner import plat, slots
    fake_run(tmp)
    sent, typed, raw, ran = [], [], [], []
    real = U.SEND[0], U.RUN[0]
    U.SEND[0] = lambda text: (sent.append(text), {'ok': True, 'code': 0, 'out': 'sent to c1', 'argv': []})[1]
    U.RUN[0] = lambda argv: (ran.append(argv), (0, 'c3 is open: https://claude.ai/code/session_c3x\n'))[1]
    inboxes = {'c6': Path('/x/control6.in'), 's2': Path('/x/slot2.in')}
    try:
        with mock.patch.object(U, 'hidden_inbox', side_effect=lambda n: inboxes.get(n)), \
                mock.patch.object(plat, 'WINDOWS', False), \
                mock.patch.object(slots, 'send_fifo', side_effect=lambda p, t: (typed.append((p.name, t)), True)[1]), \
                mock.patch.object(slots, 'send_fifo_raw', side_effect=lambda p, b: (raw.append((p.name, b)), True)[1]):
            eq(U.act('chat_to', text='hi c1')['out'], 'sent to c1', 'no chat named: the way chat does')
            eq(U.act('chat_to', text='how is R43?', to='c6')['out'], 'sent to c6', 'c6 too')
            r = U.act('chat_to', text='hello', to='c9')
            eq(U.act('interrupt', session='c6')['out'], 'interrupted c6', 'interrupt c6')
            eq(U.keys('s2', text='yes', key='Enter')['ok'], True, 'keys typed into s2')
            eq(U.keys('s2', key='F13')['ok'], False, 'an unknown key is refused')
            eq(U.act('keys', session='s2', text='x')['ok'], False, "C25: 'keys' is no action: no page types into a session")
        check(not hasattr(U, 'capture') and not hasattr(U, 'CAPTURE_EVERY'),
              'C25: the built-in view\'s capture went with it')
        eq(sent, ['hi c1'], 'through SEND')
        eq(typed, [('control6.in', 'how is R43?')], 'c6 typed in through its FIFO')
        check(not r['ok'] and 'is not up' in r['out'], 'a session that is not up says so', r)
        eq(raw, [('control6.in', b'\x1b'), ('slot2.in', b'yes\r')], 'Escape into c6; text then Enter into s2')

        n = U.act('new_control', ask='')
        eq((n['ok'], n['link'], ran[-1]), (True, 'https://claude.ai/code/session_c3x', ['control', '--new']),
           'a new control session (control --new) and its claude.ai/code link')
        U.act('new_control', ask='theme ideas')
        eq(ran[-1], ['control', '--new', '--ask', 'theme ideas', '--no-feed'], 'with a first message')

        sent.clear()
        ran.clear()
        for k in ('since', 'yesterday', 'needs', 'usage'):
            U.act('quick_ask', key=k)
        eq((sent, [r[-2] for r in ran]), ([], ['what happened since my last look?', 'what happened since yesterday?',
                                             'what needs me?', 'where are the tokens going?']),
           'B139: each quick ask starts a new control session with it (control --new --ask), not c1')
        eq(U.act('quick_ask', key='nope')['ok'], False, 'an unknown quick ask is refused')
        eq([a['key'] for a in U.snapshot(up=False, now=NOW, links={})['quick_asks']],
           ['since', 'yesterday', 'needs', 'usage'], 'the snapshot lists them')
    finally:
        U.SEND[0], U.RUN[0] = real

    which = lambda have: (lambda name: f'/usr/bin/{name}' if name in have else None)  # noqa: E731
    with mock.patch.object(plat, 'WINDOWS', False):
        with mock.patch('shutil.which', side_effect=which({'ttyd'})):
            eq(U.terminal_mode(), 'ttyd', 'ttyd: ttyd')
        with mock.patch('shutil.which', side_effect=which(set())):
            eq(U.terminal_mode(), 'install', 'C25: no ttyd: install ttyd (the built-in view is gone)')
    with mock.patch.object(plat, 'WINDOWS', True), mock.patch('shutil.which', side_effect=which({'ttyd'})):
        eq(U.terminal_mode(), 'ttyd', 'F114: Windows too: the real terminal, no feed mode')
    with mock.patch.object(plat, 'WINDOWS', True), mock.patch('shutil.which', side_effect=which(set())), \
            mock.patch.dict(os.environ, LOCALAPPDATA=''):  # B761: a ttyd that winget installed here is not looked at
        eq(U.terminal_mode(), 'install', 'and without ttyd, how to install it')


def test_concept_copy(tmp: Path) -> None:
    """F74: `done --artifact` keeps a copy of a K task's page (--page FILE, else the .html the worktree changed)
    at <notes>/concepts/<ID>.html, and the snapshot's concept row gives its path."""
    from types import SimpleNamespace
    from agent_runner import done as D
    repo = fake_run(tmp)
    page = tmp / 'page.html'
    page.write_text('<title>K5 options</title><h1>Option A</h1>', encoding='utf-8')
    c = SimpleNamespace(root=repo, notes=S.C.notes)
    kept = D.keep_page(c, 'K5', str(page))
    eq(kept, S.C.notes('concepts', 'K5.html'), 'kept at <notes>/concepts/K5.html')
    eq(kept.read_text(encoding='utf-8'), page.read_text(encoding='utf-8'), 'a copy of the page')
    snap = U.snapshot(up=False, now=NOW, links={})
    eq(snap['concepts'][0]['copy'], str(kept), "the concept row gives the copy's path")
    eq(U.concept_copy('../K5'), '', 'an id that is not one finds nothing')
    (repo / 'journal').mkdir()
    (repo / 'journal' / 'k7.html').write_text('<h1>K7</h1>', encoding='utf-8')
    eq(D.keep_page(c, 'K7').read_text(encoding='utf-8'), '<h1>K7</h1>', 'no --page: the .html the worktree changed')
    eq(D.keep_page(c, 'K8', str(tmp / 'missing.html')), None, 'a --page that is not a file: no copy')


def test_concept_chat(tmp: Path) -> None:
    """F86: `concept_chat` starts a new control session (control --new --ask) whose first message names the
    concept, its page link and local copy, and says to follow guide concepts."""
    from types import SimpleNamespace
    from agent_runner import done as D
    repo = fake_run(tmp)
    page = tmp / 'page.html'
    page.write_text('<h1>Option A</h1>', encoding='utf-8')
    kept = D.keep_page(SimpleNamespace(root=repo, notes=S.C.notes), 'K5', str(page))
    ran = []
    real = U.RUN[0]
    U.RUN[0] = lambda argv: (ran.append(argv), (0, 'c3 is open: https://claude.ai/code/session_c3x\n'))[1]
    try:
        for cid in ('K5', 'F4'):
            r = U.act('concept_chat', cid=cid)
            eq((r['ok'], r['link']), (True, 'https://claude.ai/code/session_c3x'), f'{cid}: the new session link')
            eq(ran[-1][:3], ['control', '--new', '--ask'], f'{cid}: control --new --ask')
            ask = ran[-1][3]
            for want in ("concept K5 'lazy layout'", 'https://claude.ai/artifact/k5', str(kept), 'guide concepts',
                         'Artifact tool', 'open it inline', 'plain go'):
                check(want in ask, f'{cid}: the first message says {want!r}', ask)
        U.act('concept_chat', cid='K9', title='Dark theme', url='https://claude.ai/artifact/k9')
        check("concept K9 'Dark theme'" in ran[-1][3] and 'https://claude.ai/artifact/k9' in ran[-1][3]
              and 'no local copy' in ran[-1][3], 'a concept no longer listed: the given title and link', ran[-1])
        n = len(ran)
        eq(U.act('concept_chat', cid='../K5')['ok'], False, 'an id that is not one is refused')
        eq(len(ran), n, 'and runs nothing')
    finally:
        U.RUN[0] = real


def test_hidden_send(tmp: Path) -> None:
    """F89: a hidden session is reached through its shim's FIFO, found from its .live marker:
    send writes a bracketed paste then CR, interrupt writes a raw ESC, and a FIFO nobody reads gives ok False."""
    import os
    from agent_runner import plat
    if plat.WINDOWS:
        return
    fake_run(tmp)
    readers, typed = [], []

    def hidden(stem: str, reader: bool = True) -> None:
        S.C.notes(f'{stem}.live').write_text(str(os.getpid()), encoding='utf-8')
        os.mkfifo(S.C.notes(f'{stem}.in'))
        if reader:
            readers.append(os.open(S.C.notes(f'{stem}.in'), os.O_RDONLY | os.O_NONBLOCK))

    def drain(fd: int) -> bytes:
        try:
            return os.read(fd, 65536)
        except BlockingIOError:
            return b''

    hidden('slot2')
    hidden('control3')
    hidden('slot4', reader=False)
    try:
        with mock.patch.object(plat, 'WINDOWS', False):
            r = U.send('s2', 'hello s2')
            eq((r['ok'], r['out']), (True, 'sent to s2'), 'send to a hidden slot')
            eq(drain(readers[0]), b'\x1b[200~hello s2\x1b[201~\r', 'a bracketed paste, then CR')
            r = U.interrupt('c3')
            eq((r['ok'], r['out']), (True, 'interrupted c3'), 'interrupt a hidden control session')
            eq(drain(readers[1]), b'\x1b', 'a raw ESC, no paste')
            eq(U.keys('s2', text='y', key='Enter')['ok'], True, 'keys: text and a key, raw')
            eq(drain(readers[0]), b'y\r', 'y then CR')
            r = U.send('s4', 'anyone?')
            check(not r['ok'], 'a FIFO with no reader: ok False', r)
            check(not U.interrupt('s4')['ok'], 'nor an interrupt')
            r = U.send('s9', 'hi')
            check(not r['ok'] and 'is not up' in r['out'], 'no marker: not up', r)
        S.C.notes('slot5.live').write_text(str(os.getpid()), encoding='utf-8')  # no slot5.in: a hidden console
        with mock.patch.object(plat, 'WINDOWS', True):
            for r in (U.send('s5', 'hi'), U.interrupt('s5')):
                check(not r['ok'] and 'cannot be typed into' in r['out'], 'Windows hidden console: no typing', r)
            with mock.patch('agent_runner.slots.pipe_send', lambda i, c, p=0: typed.append((i.name, c)) or True):
                check(U.send('s2', 'hi')['ok'] and U.interrupt('c3')['ok'], 'F145: Windows ConPTY takes typed text')
            eq(typed, [('slot2.in', [b'\x1b[200~hi\x1b[201~', b'\r']), ('control3.in', [b'\x1b'])],
               'a bracketed paste then CR, and a raw ESC, through the pipe')
    finally:
        for fd in readers:
            os.close(fd)


def test_delete_chats(tmp: Path) -> None:
    """F118: delete_chats ends each named control session (its process, controlN.pid and .title go, so it leaves
    the chat list and no run start reopens it), an older runner's c1 too (F176)."""
    import subprocess as sp
    fake_run(tmp)
    procs = {n: sp.Popen(['sleep', '60']) for n in (1, 3, 4)}
    try:
        for n, p in procs.items():
            S.C.notes(f'control{n}.pid').write_text(f'{p.pid} sid-{n}', encoding='utf-8')
            S.C.notes(f'control{n}.title').write_text(f'proj · {n} · chat {n}\n', encoding='utf-8')
        with mock.patch('agent_runner.control.control_live', lambda n: procs[n].pid if n in procs and
                        procs[n].poll() is None and S.C.notes(f'control{n}.pid').exists() else 0):
            eq(U.act('delete_chats', names=[])['ok'], False, 'no names: refused')
            eq(U.act('delete_chats', names=['s2'])['ok'], False, 'a slot is not a chat')
            r = U.act('delete_chats', names=['c3', 'c9'])
            eq((r['ok'], r['deleted']), (True, ['c3']), 'c3 deleted, c9 was not there')
            procs[3].wait(timeout=10)
            check(not S.C.notes('control3.pid').exists() and not S.C.notes('control3.title').exists(),
                  'its pid file and title are gone')
            eq(sorted(U.control_titles()), [1, 4], 'the chat list keeps c1 and c4')
            check(procs[1].poll() is None and procs[4].poll() is None, 'the others still run')
            eq(U.act('delete_chats', names=['c1'])['deleted'], ['c1'], 'c1 is a chat like any other')
    finally:
        for p in procs.values():
            p.kill()
            p.wait()


def test_need_chat_f143(tmp: Path) -> None:
    """F143: a Needs you item's Chat starts a control session whose first message holds the ask and the options; a bad
    id, or one that no longer needs the person, is refused."""
    fake_run(tmp)
    ran = []
    ask = {'title': 'Layout', 'summary': 'Pick a layout', 'groups': [{'heading': 'h', 'questions': [
        {'id': 'lay', 'q': 'Which layout?', 'answers': ['Tabs', 'Drawer'], 'recommended': 1}]}]}
    with ran_by(ran, 'control 7 is starting'):
        r = U.act('need_chat', tid='D3', wait=False)
        eq((r['ok'], r['name']), (True, 'c7'), 'a new chat')
        eq(ran[-1][:4], ['control', '--new', '--no-wait', '--ask'], 'control --new --ask, not waiting')
        text = ran[-1][4]
        check(text == r['ask'] and 'D3' in text and "'Write the guide'" in text and 'hich layout' in text
              and 'wait for my reply' in text, 'its first message: the id, the title and what was asked', text)
        S.C.notes('sheets', 'D3.json').write_text(json.dumps(ask), encoding='utf-8')
        U.act('need_chat', tid='D3')
        check('Possible answers:' in ran[-1][3] and 'Which layout?: Tabs / Drawer (recommended)' in ran[-1][3],
              "a pick sheet's questions and answers are in it", ran[-1])
        eq(U.need_options({'label': 'CONFIRM'}), ['Yes', 'No'], 'a CONFIRM: Yes, No')
        eq(U.need_options({'label': 'DECIDE', 'options': ['a', 'b']}), ['A', 'B'], "an item's own options")
        path = chat(9, 'sx', [said('assistant', 'I looked at both. Tabs cost a day, the drawer two.', '2026-11-21T10:00:00Z')])
        from agent_runner import slots, watch
        with mock.patch.object(watch, 'last_session', lambda tid: (1, 'sx')), mock.patch.object(slots, 'transcript', lambda sid: path):
            U.act('need_chat', tid='D3')
        check('Tabs cost a day, the drawer two.' in ran[-1][3], "the agent's full last message is in it", ran[-1])
        n = len(ran)
        for bad in ('', 'D3; rm', '--force', 'F1'):
            eq(U.act('need_chat', tid=bad)['ok'], False, f'refused: {bad!r}')
        eq(len(ran), n, 'a refused one starts nothing')


def test_feed_ids_b134(tmp: Path) -> None:
    """B134: a feed entry carries its transcript entry's id, the same in every later feed."""
    rows = [{'type': 'user', 'uuid': 'u1', 'message': {'content': 'hi'}},
            {'type': 'assistant', 'uuid': 'u2', 'message': {'content': [
                {'type': 'text', 'text': 'a'}, {'type': 'tool_use', 'name': 'Bash', 'input': {'command': 'ls'}}]}},
            {'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': 'no id'}]}}]
    es = U.feed_entries(rows)
    eq([e.get('id', '') for e in es], ['u1:0', 'u2:0', 'u2:1', ''], 'the uuid and the block')
    eq([e.get('id', '') for e in U.feed_entries(rows[1:])][0], 'u2:0', 'the same from a later, shorter tail')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_feed), in_tmp(test_feed_prompt_b154), in_tmp(test_chat_at_b154), in_tmp(test_chat_hold_b158), in_tmp(test_chat_force_queued), in_tmp(test_chat_and_terminal), in_tmp(test_concept_copy), in_tmp(test_concept_chat), in_tmp(test_hidden_send), in_tmp(test_delete_chats), in_tmp(test_need_chat_f143), in_tmp(test_feed_ids_b134)]))
