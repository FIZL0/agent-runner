#!/usr/bin/env python3
"""F406g: the run app with a control session on the harness loop (a chat on another provider), with a fake provider: a
new chat, its state, reply, queued messages and Stop, images, a DECIDE, Talk, Resume, and what it lacks hidden. The
page's own words need node alone; the sessions need node and a hidden terminal (POSIX)."""
from __future__ import annotations

import base64
import datetime as dt
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path

from _check import check, eq, has, report
from _web import get, logic_js, post
from test_control_harness import Env, answered, until

from agent_runner import chat_question as Q, control as K, control_harness as CH, plat, status, ui_model as U, web as W
from agent_runner.attach import attach_size_frame

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==')
WORDS = 'Codex · gpt-test'


class Page:
    """The run page of `env`'s repository, and the chats started from it."""

    def __init__(self, env: Env):
        self.env, self.token = env, W.web_token()
        self.srv = W.serve(self.token, 0, '127.0.0.1', snap=lambda: {})
        self.base = f'http://127.0.0.1:{self.srv.server_address[1]}'

    def act(self, name: str, **args) -> dict:
        code, r = post(f'{self.base}/act?t={self.token}', {'name': name, 'args': args})
        eq(code, 200, f'{name} answers')
        return r

    def get(self, path: str):
        return json.loads(get(f'{self.base}/{path}{"&" if "?" in path else "?"}t={self.token}')[1])

    def live(self, chat: str) -> dict:
        return self.get(f'live/{chat}')

    def rests(self, chat: str, word: str = 'idle'):
        return until(lambda: self.live(chat)['status'] == word)


def sid_of(chat: str) -> str:
    return K.control_kept_sid(int(chat[1:]))


def last(chat: str) -> dict:
    return K.control_state(K.entries(sid_of(chat), skip_bad=True))


def started(page: Page, ask: str) -> str:
    r = page.act('new_control', ask=ask, wait=False)
    chat = r['name']
    check(chat, 'the new chat says its name', r)
    eq(r['link'], '', 'and has no claude.ai link')
    check(until(lambda: sid_of(chat) and K.control_live(int(chat[1:]))), 'it is up')
    check(answered(sid_of(chat), f'answer to {ask}'), 'its first message is answered')
    return chat


def test_chat(page: Page) -> None:
    print('a new chat, its state, reply, queued messages, Stop')
    chat = started(page, 'hello')
    check(page.rests(chat), 'idle, waiting for the person', page.live(chat))
    d = page.live(chat)
    eq((d['ok'], d['harness'], d['mode'], d['queued'], d['tasks']), (True, True, '', 0, []), 'its live state')
    row = next(x for x in U.control_rows(U.control_titles()) if x['name'] == chat)
    eq((row['model'], row['link'], row['last']), (WORDS, '', 'claude'), 'its row: provider and model, no link')
    eq(page.get(f'commands?s={chat}'), [], 'no slash commands')
    eq(page.get('commands'), [], 'nor for a new chat')
    r = page.act('stop_session', session=chat)
    check(not r['ok'] and K.control_live(int(chat[1:])), 'Stop on an idle one does nothing', r)
    check(page.act('chat_to', text='and again', to=chat)['ok'], 'a reply')
    check(answered(sid_of(chat), 'answer to and again'), 'is answered')
    page.act('chat_to', text='slow', to=chat)
    check(page.rests(chat, 'busy'), 'working')
    check(abs(page.live(chat)['since'] - time.time()) < 60, 'since when')
    page.act('chat_to', text='queued one', to=chat)
    check(until(lambda: page.live(chat)['queued'] == 1), 'a message sent meanwhile is queued', page.live(chat))
    check(page.act('chat_to', text='', to=chat, force=True)['ok'], 'Force send of what is queued')
    check(answered(sid_of(chat), 'answer to queued one'), 'sends it at once')
    eq(page.live(chat)['queued'], 0, 'nothing is queued any more')
    page.act('chat_to', text='slow', to=chat)
    page.rests(chat, 'busy')
    check(page.act('chat_to', text='/now this', to=chat, force=True)['ok'], 'Force send of words')
    check(answered(sid_of(chat), 'answer to /now this'), 'as they were typed', last(chat))
    page.act('chat_to', text='slow', to=chat)
    page.rests(chat, 'busy')
    check(page.act('stop_session', session=chat)['ok'], 'Stop')
    check(page.rests(chat), 'it rests')
    eq(U.feed(chat)['entries'][-1]['text'], 'interrupted', 'and the feed says so')
    page.act('chat_to', text='run: sleep 60', to=chat)
    check(page.rests(chat, 'busy') and page.act('interrupt', session=chat)['ok'], 'Esc')
    check(page.rests(chat) and K.control_live(int(chat[1:])), 'stops it and keeps the chat')
    pid = K.control_live(int(chat[1:]))
    check(page.act('restart_chat', chat=chat)['ok'], 'restarted')
    check(until(lambda: K.control_live(int(chat[1:])) not in (0, pid)) and page.rests(chat), 'it is up again')
    page.act('chat_to', text='after restart', to=chat)
    check(answered(sid_of(chat), 'answer to after restart'), 'in the same conversation')
    check('hello' in page.env.calls()[-1]['said'], 'with all of it')


def seen(chat: str, want: str, rows: int = 20) -> str:
    """What a viewer that comes to `chat`'s terminal gets to see, until `want` is in it."""
    s = socket.socket(socket.AF_UNIX)
    s.connect(W.socket_of(chat))
    s.settimeout(0.5)
    s.sendall(attach_size_frame(rows, 90))
    got, end = b'', time.monotonic() + 10
    while want.encode() not in got and time.monotonic() < end:
        try:
            got += s.recv(65536)
        except TimeoutError:
            pass
    s.close()
    return got.decode('utf-8', 'replace')


def test_screen(page: Page) -> None:
    print('its terminal, for a viewer that comes')
    chat = started(page, 'draw me')
    page.rests(chat)
    has(seen(chat, 'answer to draw me'), 'answer to draw me', 'what was said before, with nothing new printed')
    has(seen(chat, 'answer to draw me'), 'answer to draw me', 'again for the next, of the same size')
    check(page.act('restart_chat', chat=chat)['ok'] and until(lambda: page.live(chat)['ok']), 'restarted')
    until(lambda: W.socket_of(chat))
    time.sleep(1)
    has(seen(chat, 'answer to draw me'), 'answer to draw me', 'a resumed one too')


def test_images(page: Page) -> None:
    print('images')
    req = urllib.request.Request(f'{page.base}/upload?name=shot.png&t={page.token}', data=PNG, headers={'Content-Type': 'image/png'})
    with urllib.request.urlopen(req, timeout=10) as r:
        shot = Path(json.loads(r.read())['path'])
    chat = started(page, 'here is a picture')
    page.act('chat_to', text=f'read: {shot}', to=chat)
    check(answered(sid_of(chat), f'answer to tool ({shot} (image/png)'), 'read names the image', last(chat))
    img = page.env.calls()[-1]['images']
    eq([(i['mimeType'], base64.b64decode(i['data'])) for i in img], [('image/png', PNG)], 'and the model gets it')
    check(base64.b64encode(PNG).decode() not in Path(K.transcript(sid_of(chat))).read_text(encoding='utf-8'),
          'the transcript keeps its path, not its bytes')
    shot.unlink()
    page.act('chat_to', text='go on', to=chat)
    check(answered(sid_of(chat), 'answer to go on'), 'an image that is gone breaks nothing')
    eq(page.env.calls()[-1]['images'], [], 'it is left out')


def test_decide(page: Page) -> None:
    print('a DECIDE')
    chat = started(page, 'hi there')
    sid = sid_of(chat)
    page.act('chat_to', text='x\n\nDECIDE: Which look? [Full (recommended) / Small]', to=chat)
    check(answered(sid, 'DECIDE: Which look?'), 'the chat ends on a question')
    check(U.chat_state(int(chat[1:]), sid)['needs_reply'], 'its row needs a reply')
    page.rests(chat)
    K.close_controls(branch='main', force=True, now=time.time() + 50000)
    todo = K.C.todo.read_text(encoding='utf-8')
    has(todo, r'DECIDE: Which look\? \[Full', 'idle, it is filed')
    tid = re.search(r'\*\*(\w+)\*\*(?=[^\n]*Which look)', todo)[1]
    row = next(x for x in U.needs_rows(status.waiting_ok(), dt.datetime.now())[0] if x['id'] == tid)
    eq([o['name'] for o in row['options']], ['Full', 'Small'], 'its options are buttons')
    has(todo, rf'control --resume {sid}', 'and it says how to go on')
    r = page.act('run_control', key='need_answer2', tid=tid, text='Small')
    check(r['ok'] and 'Small' in K.C.todo.read_text(encoding='utf-8'), 'a press answers it', r)


def test_about(page: Page) -> None:
    print('words about its question, queued')
    chat = started(page, 'hi about')
    sid = sid_of(chat)
    page.act('chat_to', text='x\n\nDECIDE: Which hue? [Red / Blue]', to=chat)
    check(answered(sid, 'DECIDE: Which hue?'), 'the chat ends on a question')
    page.rests(chat)
    qid = (page.live(chat)['ask'] or {}).get('id')
    check(qid, 'which it asks', page.live(chat))
    about = f'{Q.ABOUT}Which hue?{Q.NOT}'

    def says() -> tuple:
        d = page.live(chat)
        return (d['ask'] or {}).get('id'), d['queued']
    page.act('chat_to', text=f'{about}slow', to=chat)
    check(page.rests(chat, 'busy'), 'a reply to words about it is under way')
    page.act('chat_to', text=f'{about}and why?', to=chat)
    check(until(lambda: page.live(chat)['queued'] == 1), 'more of them are queued')
    eq((says(), CH.now(sid)['answers']), ((qid, 1), False), 'it is still asked')
    page.act('chat_to', text='Blue', to=chat)
    check(until(lambda: page.live(chat)['queued'] == 2), 'an answer is queued after them')
    eq((says(), CH.now(sid)['answers']), ((None, 2), True), 'it is asked no more')
    check(page.act('chat_to', text='', to=chat, force=True)['ok'] and answered(sid, 'answer to Blue'), 'the answer goes in')
    page.rests(chat)
    eq((says(), CH.now(sid)['answers']), ((None, 0), False), 'answered, nothing queued')


def test_talk(page: Page) -> None:
    print('Talk')
    r = page.act('talk', text='what is up', to='')
    chat = r['session']
    check(r['ok'] and chat, 'the first words open a chat', r)
    check(until(lambda: sid_of(chat) and 'answer to' in last(chat)['text'] and 'what is up' in last(chat)['text']), 'and are answered', last(chat))
    eq([e['kind'] for e in U.feed(chat)['entries'][-2:]], ['you', 'say'], 'the feed Talk reads aloud has both')
    r = page.act('talk', text='and now', to=chat)
    check(r['session'] == chat and until(lambda: 'and now' in last(chat)['text']), 'the next words go to it')


def test_resume(page: Page) -> None:
    print('Resume')
    chat = started(page, 'keep me')
    sid, n = sid_of(chat), int(chat[1:])
    pid = K.control_live(n)
    plat.terminate(pid)
    check(until(lambda: not K.control_live(n) and not W.session_live(chat)), 'ended')
    eq((page.live(chat)['ok'], list(K.C.notes().glob('*.now.part'))), (False, []), 'no state of an ended one')
    check(W.no_session(chat)['resume'], 'it can be resumed')
    page.env.configure('opus')
    d = W.no_session(chat)
    check(not d['resume'] and 'another provider' in d['why'], 'not with [models] control on Claude Code, and it says why', d)
    check('another provider' in page.act('resume_chat', chat=chat)['out'], 'nor by an old page')
    eq((U.new_chat_model(), CH.chat_model(sid)), ('', WORDS), 'new chats are Claude Code ones; this one was not')
    check(page.get('commands'), 'and slash commands are back')
    page.env.configure()
    check(page.act('resume_chat', chat=chat)['ok'], 'Resume')
    check(until(lambda: K.control_live(n)) and page.rests(chat), 'it is up', page.live(chat))
    page.act('chat_to', text='back', to=chat)
    check(answered(sid, 'answer to back'), 'and answers')
    check('keep me' in page.env.calls()[-1]['said'], 'with what was said in it')


def test_model_words(env: Env) -> None:
    print('its provider and model in words')
    eq(U.new_chat_model(), WORDS, 'of a new chat')
    eq(CH.model_words('mine:org/x:7b'), 'mine · org/x:7b', 'a custom provider has the name it was given')
    sid = str(uuid.uuid4())
    (K.C.notes('harness-sessions')).mkdir(exist_ok=True)
    (K.C.notes('harness-sessions') / f'{sid}.jsonl').touch()
    eq(CH.chat_model(sid), WORDS, 'a chat')
    K.C.notes(f'{sid}.model').write_text('gemini:g-3', encoding='utf-8')
    eq(CH.chat_model(sid), 'Gemini · g-3', 'one that a cap moved down the fallback')
    eq(CH.chat_model('no-such'), '', 'a Claude Code chat has none')
    K.C.notes(f'{sid}.now').write_text(json.dumps({'pid': 999999999, 'status': 'busy'}), encoding='utf-8')
    eq(CH.now(sid), {}, 'a process that is gone says nothing')


def test_page(env: Env) -> None:
    print('the page')
    if not shutil.which('node'):
        return
    live = {'status': 'busy', 'harness': True}
    got = logic_js([['sessionChips', {'foot': None, 'live': live, 'working': True, 'model': WORDS}],
                    ['sessionChips', {'foot': None, 'live': {}, 'model': WORDS}],
                    ['keysLine', True], ['keysLine', False]])
    eq(got[0], [{'key': 'work', 'label': 'Working'}, {'key': 'model', 'label': WORDS}], 'Working and the model, no mode')
    eq(got[1], [{'key': 'model', 'label': WORDS}], 'idle: the model')
    check('commands' not in got[2] and 'commands' in got[3], 'the box names no commands where there are none')
    page = W.page_html().decode()
    check('sessmodel(){' in page, 'the model chip has its sheet')
    check('i.why' in page, 'an ended chat says why it cannot come back')
    check('real&&!modelOf(S.thread)?' in page and 'ta&&!modelOf(' in page, 'no / button and no slash menu')
    js = page[page.index('const modelOf='):].split('\n', 1)[0]
    r = subprocess.run(['node', '-e', f"""
const S={{snap:{{chat_model:'new'}}}}, FD={{n:'c8',live:{{harness:true}}}}, sessionOf=n=>({{c2:{{model:'m'}},c3:{{}}}})[n], isAgent=n=>!/^(c\\d+|[@+].+)$/.test(n||'');
{js}
console.log(JSON.stringify(['c2','c3','c8','c9','s1','@x','+plan:F1',''].map(modelOf)))"""], capture_output=True, text=True, timeout=60)
    eq(r.stdout.strip(), '["m","","new","","","new","new","new"]', 'each chat has its own, a new one what new chats run on', )


def test_tally_open(env: Env) -> None:
    """F489: on the run page a tally line opens to its calls on a tap and folds on the next."""
    print('the tally line opens')
    if not shutil.which('node'):
        return
    page = W.page_html().decode()
    js = page.split('<script id="logic">', 1)[1].split('</script>', 1)[0]
    entries = [{'kind': 'tool', 'name': 'Read', 'group': 'read', 'arg': 'README.md', 'call': 't1', 'state': 'ok'}] + [
        {'kind': 'tool', 'name': 'Bash', 'arg': f'echo {w}', 'call': f't{i + 2}', 'state': 'ok'} for i, w in enumerate(('one', 'two', 'three'))]
    test = f"""
const open = new Set(), entries = {json.dumps(entries)};
const lines = () => pastLines(entries, 60, open);
const fold = lines().find(l => l.h.includes('data-fold'));
const el = {{closest: s => s === '[data-fold]' ? {{getAttribute: () => /data-fold="([^"]*)"/.exec(fold.h)[1]}} : null}};
const shut = lines().map(l => l.t), tap1 = pastFoldTap(open, el), opened = lines().map(l => l.t);
pastFoldTap(open, el);
console.log(JSON.stringify({{shut, tap1, opened, again: lines().map(l => l.t), other: pastFoldTap(open, {{closest: () => null}})}}));"""
    r = subprocess.run(['node', '-'], input=js + test, capture_output=True, text=True, timeout=60)
    o = json.loads(r.stdout or 'null') or {}
    check(any('Read 1 file, ran 3 shell commands' in t for t in o.get('shut', [])), 'the folded line', o or r.stderr[-800:])
    check(o.get('tap1') is True and len(o.get('opened', [])) > len(o['shut']), 'a tap opens the list', o)
    opened = '\n'.join(o.get('opened', []))
    check(all(w in opened for w in ('Read(README.md)', 'Bash(echo one)', 'Bash(echo three)')), 'each call with its argument', opened)
    eq(o.get('again'), o.get('shut'), 'a tap again folds it')
    eq(o.get('other'), False, 'a tap elsewhere is not one')


def main() -> int:
    with tempfile.TemporaryDirectory(prefix='ar-web-harness-', ignore_cleanup_errors=True) as d:
        env = Env(Path(d).resolve())
        page = None
        tests = [lambda: test_model_words(env), lambda: test_page(env), lambda: test_tally_open(env)]
        try:
            if shutil.which('node') and not plat.WINDOWS:
                page = Page(env)
                tests += [lambda f=f: f(page) for f in (test_chat, test_screen, test_images, test_decide, test_about, test_talk, test_resume)]
            else:
                print('SKIP: the sessions need node and a hidden terminal')
            return report(tests)
        finally:
            if page:
                page.srv.stop()
            for n in K.control_live_numbers():
                K.end_control(n, 'the test is over')


if __name__ == '__main__':
    sys.exit(main())
