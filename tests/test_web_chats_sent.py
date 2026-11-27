"""The run page, chats area, upload, outbox, sent messages and tabs (C46: split from test_web_chats.py), tests unchanged.

    python3 tests/test_web_chats_sent.py
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from _check import check, eq, git, report
from _trust import asked, trusted_checks

from agent_runner import config as CF  # noqa: E402
from agent_runner import state as S  # noqa: E402
from agent_runner import ui_model as U  # noqa: E402
from agent_runner import web as W  # noqa: E402
from _web import TODO, fake_repo, get, post, LOGIC_DRIVER, logic_js, in_tmp  # noqa: E402



def post_raw(url: str, data: bytes, ctype: str = 'image/png') -> tuple[int, dict]:
    req = urllib.request.Request(url, data=data, method='POST', headers={'Content-Type': ctype})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b'{}')


def post_raw(url: str, data: bytes, ctype: str = 'image/png') -> tuple[int, dict]:
    req = urllib.request.Request(url, data=data, method='POST', headers={'Content-Type': ctype})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b'{}')


def test_upload(tmp: Path) -> None:
    """F79: an attachment from the message box is kept under .runner/uploads and its path comes back, for the
    message that hands it to the session; a name with a path in it cannot leave that folder."""
    repo = fake_repo(tmp)
    token = W.web_token()
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {})
    base = f'http://127.0.0.1:{srv.server_address[1]}'
    png = b'\x89PNG\r\n\x1a\nfake picture'
    try:
        code, r = post_raw(f'{base}/upload?t={token}&name=screen%20shot.png', png)
        eq(code, 200, 'an upload is answered')
        p = Path(r['path'])
        check(r['ok'] and p.is_file() and p.read_bytes() == png, 'the file is kept as sent', r)
        eq(p.parent, (repo / '.runner' / 'uploads').resolve(), 'under .runner/uploads')
        check(p.name.endswith('-screen_shot.png'), 'named by its time and its own name, made safe', p.name)
        code, r2 = post_raw(f'{base}/upload?t={token}&name=screen%20shot.png', b'second')
        check(r2['ok'] and r2['path'] != r['path'] and p.read_bytes() == png, 'a second one never overwrites it', r2)
        code, r3 = post_raw(f'{base}/upload?t={token}&name=..%2F..%2Fetc%2Fpasswd', b'x', 'text/plain')
        eq(Path(r3['path']).parent, p.parent, 'a name with a path in it stays in the uploads folder')
        check(Path(r3['path']).name.endswith('-passwd'), 'keeping only its last part', r3)
        code, r4 = post_raw(f'{base}/upload?t={token}&name=x', b'')
        check(code == 400 and not r4['ok'], 'an empty upload is refused', r4)
        code, _ = post_raw(f'{base}/upload?name=x.png', png)
        eq(code, 403, 'and an upload without the token')
    finally:
        srv.stop()
    eq(W.safe_name('.hidden'), 'hidden', 'no leading dot')
    eq(W.safe_name('C:\\Users\\me\\a b.txt'), 'a_b.txt', 'a Windows path keeps its last part')
    eq(W.safe_name(''), 'file', 'no name: file')


def test_outbox_f137(tmp: Path) -> None:
    """F137: the page draws an action at once and keeps it in an outbox (localStorage) until the run answers; it
    is sent again after a drop or a reload with the same client id, which the run page runs only once. A failed
    action stays, with Retry and Discard. New chats start without waiting, and messages to a chat still starting
    go once it has its name."""
    fake_repo(tmp)
    token = W.web_token()
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {})
    url = f'http://127.0.0.1:{srv.server_address[1]}/act?t={token}'
    ran = []
    try:
        with mock.patch.object(U, 'RUN', [lambda argv: (ran.append(argv), (0, 'control 7 is starting in a hidden '
                                                                            'terminal'))[1]]):
            _, a = post(url, {'name': 'new_control', 'args': {'wait': False}, 'cid': 'k1'})
            _, b = post(url, {'name': 'new_control', 'args': {'wait': False}, 'cid': 'k1'})
            _, c = post(url, {'name': 'new_control', 'args': {'wait': False}, 'cid': 'k2'})
            _, d = post(url, {'name': 'concept_chat', 'args': {'cid': 'K5', 'title': 'T', 'wait': False}, 'cid': 'k3'})
    finally:
        srv.stop()
    eq([x[:3] for x in ran], [['control', '--new', '--no-wait']] * 3, 'k1 ran once; k2 and the concept chat ran')
    eq((a['ok'], a['name'], b.get('again'), b['name'], c.get('again')), (True, 'c7', True, 'c7', None),
       'a copy of k1 answers with its first result; a new cid runs again')
    eq(d['name'], 'c7', 'a concept chat starts without waiting too')
    once, n = W.ActsOnce(), []

    def boom():
        n.append(1)
        raise RuntimeError('cut off')
    for _ in range(2):
        try:
            once.run('x', boom)
        except RuntimeError:
            pass
    eq(len(n), 2, 'an action that did not finish runs again for the same cid')
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {})
    url = f'http://127.0.0.1:{srv.server_address[1]}/act?t={token}'
    try:
        def crash(name, **a):
            raise RuntimeError('disk full')
        with mock.patch.object(U, 'act', crash):
            code, e = post(url, {'name': 'chat_to', 'args': {'text': 'x'}, 'cid': 'k9'})
        eq((code, e['ok'], e['out']), (200, False, 'chat_to failed: disk full'),
           'an action that crashes answers as failed (Retry, Discard), so the outbox does not send it for ever')
        gate, ran2 = __import__('threading').Event(), []

        def slow(name, **a):
            ran2.append(1)
            gate.wait(10)
            return {'ok': True}
        with mock.patch.object(U, 'act', slow), mock.patch.object(W.ActsOnce, 'WAIT', 0.2):
            t = __import__('threading').Thread(target=post, args=(url, {'name': 'chat_to', 'args': {}, 'cid': 'k10'}))
            t.start()
            while not ran2:
                __import__('time').sleep(0.02)
            code, w = post(url, {'name': 'chat_to', 'args': {}, 'cid': 'k10'})
            gate.set()
            t.join(10)
        eq((code, len(ran2)), (503, 1), 'a copy of an action still running gets 503 (sent again later), not a failure')
        asked = []
        with mock.patch.object(U, 'act', lambda name, **a: (asked.append(a), {'ok': False, 'hold': True, 'out': ''})[1]):
            for body in ({'hold': True}, {'hold': True}, {}):  # B158
                post(url, {'name': 'chat_to', 'args': {'text': 'x', 'to': 'c3'}, 'cid': 'k11', **body})
            post(url, {'name': 'answer', 'args': {'tid': 'F1'}, 'cid': 'k12', 'hold': True})
        eq(asked, [{'text': 'x', 'to': 'c3', 'wait': False}] * 2 + [{'text': 'x', 'to': 'c3'}, {'tid': 'F1'}],
           'B158: a held message is tried again under its client id; only a message of a page that holds is not waited for')
    finally:
        srv.stop()
    eq(once.run('', lambda: {'ok': True}), {'ok': True}, 'no cid: it just runs')
    page = W.PAGE.read_text(encoding='utf-8')
    for part in ("JSON.stringify({name:it.name,args:it.args,cid:it.cid,hold:true})", "addEventListener('online',()=>drain())",
                 'id="obbar"', 'id="obpop"', 'standRows()', 'obBubbles(n)', 'obCards(x=>x.concept)',
                 "if(OB.offline)drain()", "outbox('chat_to',{text:msg,to,..."):
        check(part in page, f'the page has {part}')
    send = page.split('async function send(by){', 1)[1].split('\n}', 1)[0]
    check("act('chat_to'" not in send, 'a message no longer waits for chat_to before leaving the box', send)
    if not shutil.which('node'):
        print('  (no node here: the outbox script test is skipped)')
        return
    it = lambda cid, name='answer', **k: {'cid': cid, 'name': name, 'args': k.pop('args', {}), 'state': 'sending',  # noqa: E731
                                          'say': cid, **k}
    nc = it('n1', 'new_control', newchat=True)
    msg = it('m1', 'chat_to', args={'to': '@n1', 'text': 'hi'})
    box = [nc, msg, it('a1', need='F1'), it('p1', concept='F9')]
    got = logic_js([
        ['obParse', json.dumps(box + [{'cid': 'z'}, 'junk', {**nc, 'state': 'odd'}])], ['obParse', '{bad'],
        ['obNext', box], ['obNext', [msg]],
        ['obSettle', box, 'n1', {'ok': True, 'name': 'c7'}],
        ['obSettle', box, 'n1', {'ok': False, 'out': 'no run is up\nmore'}],
        ['obSettle', box, 'a1', {'ok': True}],
        ['obRetry', [{**nc, 'state': 'failed', 'err': 'x'}, {**msg, 'state': 'failed'}], 'm1', 'n2'],
        ['obDrop', box, 'n1'],
        ['obName', box, '@n1', 'c8'],
        ['obCounts', [nc, {**msg, 'state': 'failed'}]],
        ['obHidden', box, 'need'], ['obHidden', [{**box[2], 'state': 'failed'}], 'need'], ['obHidden', box, 'concept'],
        ['obPill', {'sending': 2, 'failed': 1}, False], ['obPill', {'sending': 1, 'failed': 0}, True],
        ['obPill', {'sending': 0, 'failed': 0}, False],
        ['obNext', [it('h1', 'chat_to', args={'to': 'c3'}, by='a', heldAt=1, until=2),
                    it('h2', 'chat_to', args={'to': 'c3'}, by='b')], 'b', ['a'], 5000],
    ])
    eq(got[17], None, "B158: a message another tab holds is not overtaken")
    eq([x['cid'] for x in got[0]], ['n1', 'm1', 'a1', 'p1'], 'a stored outbox keeps only whole items')
    eq(got[1], [], 'a broken store is an empty outbox')
    eq(got[2]['cid'], 'n1', 'items go in order')
    eq(got[3], None, 'a message to a chat still starting waits for it')
    eq([(x['cid'], x['args'].get('to')) for x in got[4]], [('m1', 'c7'), ('a1', None), ('p1', None)],
       'a new chat that answers leaves, and its messages go to its name')
    eq([(x['cid'], x['state'], x.get('err')) for x in got[5][:2]],
       [('n1', 'failed', 'no run is up'), ('m1', 'failed', 'the new chat did not start')],
       'a failed new chat stays with its first line, and so do its messages')
    eq([x['cid'] for x in got[6]], ['n1', 'm1', 'p1'], 'an answered item leaves the outbox')
    eq([(x['cid'], x['state'], x['args'].get('to')) for x in got[7]], [('n2', 'sending', None), ('m1', 'sending', '@n2')],
       "Retry on a message waiting for a chat that did not start retries the chat, under a new cid")
    eq([x['cid'] for x in got[8]], ['a1', 'p1'], 'Discard on a new chat drops its messages too')
    eq(got[9][1]['args']['to'], 'c8', 'a chat the snapshot names gets its messages')
    eq(got[10], {'sending': 1, 'failed': 1}, 'the pill counts')
    eq((got[11], got[12], got[13]), (['F1'], [], ['F9']), 'only items still sending hide their cards')
    eq(got[14], ['2 sending', '1 failed · tap to see'], "the pill's words")
    eq(got[15], ['1 waiting for the connection'], 'offline, it says it waits')
    eq(got[16], [], 'nothing in the outbox: no pill')


SENT_DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const grab = (start) => { const i = page.indexOf(start); return page.slice(i, page.indexOf('\n}\n', i) + 2); };
const logic = page.split('<script id="logic">')[1].split('</script>')[0];
const kept = {}, store = {get: k => kept[k] || '', set(k, v) { kept[k] = v }};
const said = [], toast = t => said.push(t), render = () => {}, tq = p => p, obDraw = () => {}, talkHear = () => {};
const esc = t => String(t), LOGO = () => '', threadTitle = n => n, PN = () => 'p', md = t => t, I = {chev: ''};
const isAgent = () => false, chats = () => [], takeSnap = () => {}, TK = {playing: ''}, sureHTML = () => '';
const opened = [], open = n => { S.thread = n; opened.push(n) };
let feeds = {}, answers = [], posts = [];
const fetch = async (p, o) => {
  if (p === 'act') { posts.push(JSON.parse(o.body)); return {status: 200, json: async () => answers.shift() || {ok: true, at: 100}} }
  return {json: async () => feeds[p.split('/')[1]] || {ok: false, entries: [], out: 'no transcript'}};
};
const S = {snap: {sessions: [{name: 'c3', state: 'live'}], needs: [], concepts: []}, feeds: {}, sent: {}, ob: [], openSteps: {}, thread: null, waitNew: null};
const feedOf = n => (S.feeds[n] || {}).entries || [], sessionOf = n => S.snap.sessions.find(s => s.name === n);
const OB = {busy: false, offline: false, timer: 0, wait: 2000}, obLoad = () => {}, obBeat = () => {}, obLive = () => [], obTake = async () => true, OB_KEY = 'ob', SENT_KEY = 'sent';
let cids = 0;
const newCid = () => 'k' + (++cids), realNow = Date.now;
let skew = 0;
Date.now = () => realNow() + skew;
const line = s => { const i = page.indexOf(s); return page.slice(i, page.indexOf('\n', i)) + '\n' };
eval(logic.replace(/if\(typeof module[^\n]*/, '') + line('function obChange(') + grab('function outbox(') + grab('async function drain(')
  + "const DK = {}, CHATS_OF = '';" + line('const DRAFT_KEY=') + grab('function boxMove(') + grab('function obDone(') + grab('function obBubbles(') + line('const ended=') + grab('function talkConvo(') + line('const notDelivered=') + grab('async function loadFeed(')
  + grab('function addSent(') + grab('function carrySent(') + line('const keepSent=') + line('const busy=n') + line('const obState=') + line('const obBtns=') + `
const tick = () => new Promise(r => setTimeout(r, 5));
const settle = async () => { for (let i = 0; i < 6; i++) await tick() };
const shows = (n, t) => talkConvo(n).includes(t);
(async () => {
  const out = {};
  // a new chat with an ask: shown as pending in its thread until the feed has it
  const it = outbox('quick_ask', {key: 'since'}, {newchat: true, say: 'Since', ask: 'what happened?'});
  answers.unshift({ok: true, name: 'c3', at: 100, ask: 'what happened?'});
  S.thread = '@' + it.cid; await settle();
  out.opened = opened.slice(); out.askBeforeFeed = shows('c3', 'what happened?');
  await loadFeed('c3'); out.askNoTranscript = shows('c3', 'what happened?');
  feeds.c3 = {ok: true, entries: [{kind: 'you', text: 'another'}]};
  await loadFeed('c3'); out.askOtherEntry = shows('c3', 'what happened?');
  feeds.c3.entries.push({kind: 'you', text: 'what happened?', at: 130});
  out.starting = shows('c3', 'Starting the chat…');
  await loadFeed('c3'); out.askLanded = [(S.sent.c3.pending || []).length, kept.sent, shows('c3', 'Starting the chat…')];
  feeds.c3.entries.push({kind: 'say', text: 'Hello.'});
  await loadFeed('c3'); out.replied = shows('c3', 'Starting the chat…');
  // two messages: each leaves only when its own text is in the feed, and an older same text does not count
  for (const t of ['yes', 'and more']) { answers.push({ok: true, at: 200}); outbox('chat_to', {text: t, to: 'c3'}, {text: t, say: t}); }
  await settle();
  out.kept = JSON.parse(kept.sent).c3.map(p => p.text);
  feeds.c3.entries.push({kind: 'you', text: 'yes', at: 150}, {kind: 'say', text: 'ok'}, {kind: 'you', text: 'and more', at: 210});
  await loadFeed('c3'); out.own = S.sent.c3.pending.map(p => p.text);
  feeds.c3.entries.push({kind: 'say', text: 'Done.'});
  await loadFeed('c3'); skew += 50000; await loadFeed('c3');
  out.failed = S.sent.c3.pending.map(p => [p.text, p.state]);
  out.failedShown = [shows('c3', 'Not delivered'), shows('c3', 'data-sentretry'), shows('c3', 'data-sentdrop')];
  out.lost = notDelivered().map(x => [x.n, x.p.text]);
  feeds.c3.entries.push({kind: 'you', text: 'yes', at: 260});
  await loadFeed('c3'); out.late = S.sent.c3.pending.length;
  // B158: held while the chat starts: kept, not sent past, then sent in order
  posts = []; answers = [{ok: false, hold: true, out: 'c3 is still starting'}];
  for (const t of ['one', 'two']) outbox('chat_to', {text: t, to: 'c3'}, {text: t, say: t});
  outbox('answer', {tid: 'F1'}, {say: 'F1'});
  await settle(); clearTimeout(OB.timer);
  out.held = [posts.map(p => p.args.text || p.name), S.ob.map(x => [x.args.text, x.state, obState(x)])];
  skew += 5000; await drain(); await settle();
  out.after = [posts.map(p => p.args.text || p.name), S.ob.length, S.sent.c3.pending.map(p => p.text)];
  answers = Array(5).fill({ok: false, hold: true, out: 'c3 is still starting'});
  for (const t of ['never', 'nor this']) outbox('chat_to', {text: t, to: 'c3'}, {text: t, say: t});
  await settle(); clearTimeout(OB.timer);
  skew += 200000; await drain(); clearTimeout(OB.timer); out.slept = S.ob.map(x => x.state);
  for (let i = 0; i < 2; i++) { skew += 70000; await drain(); clearTimeout(OB.timer) }
  out.never = [S.ob.map(x => [x.state, x.err]), said.includes('Not sent: never')];
  console.log(JSON.stringify(out));
  process.exit(0);
})();`);
"""


def test_sent_b154(tmp: Path) -> None:
    """B154: a sent message stays shown until its own text is in the feed as 'you': a new chat's ask is carried over,
    and one that never lands is shown as not delivered, with Retry."""
    if not shutil.which('node'):
        print('  (no node here: the sent message script test is skipped)')
        return
    p = lambda text, at=100, **k: {'text': text, 'at': at, 'since': 0, 'state': 'sent', **k}  # noqa: E731
    you = lambda text, at=110: {'kind': 'you', 'text': text, 'at': at}  # noqa: E731
    left = lambda ps, es: ['sentLeft', ps, es]  # noqa: E731
    got = logic_js([
        left([p('hi')], [{'kind': 'say', 'text': 'hi'}]),
        left([p('hi')], [you('hi', 90)]), left([p('hi')], [you('hi')]),
        left([p('hi'), p('hi')], [you('hi')]),
        left([p('a  b\n\nc')], [you('\n\n<pasted_content id="36f3">\na b\nc\n</pasted_content>')]),
        left([p('one'), p('two')], [you('one\ntwo')]),
        left([p('yes')], [you('yes please')]),
        left([p('fix B1')], [you('fix B1\n\n<runner-waiting>\nF2: x\n</runner-waiting>')]),
        left([p('look\n\nAttached: /r/a.png')], [you('look\n\n[Image #1]')]),
        left([p('hello', talk=True)], [you('(Talk: answer as speech.) hello')]),
        ['sentStep', [p('x', since=1000)], [{'kind': 'say', 'text': 'ok'}], 60000, True],
        ['sentStep', [p('x', since=1000)], [{'kind': 'tool', 'text': 'Bash(ls)'}], 60000, True],
        ['sentStep', [p('x', since=1000)], [{'kind': 'tool', 'text': 'Bash(ls)'}], 60000, False],
        ['sentStep', [p('x', since=1000, first=True)], [], 60000, True],
        ['sentStep', [p('/clear', since=1000)], [], 60000, True],
        ['sentStep', [p('x', since=1000)], [you('later', 200)], 60000, True, True],
        ['sentStep', [p('x', 300, since=1000)], [you('before', 200), {'kind': 'say', 'text': 'ok'}], 60000, True, True],
        left([p('Attached: /r/a.png')], [you('[Image #1]')]),
    ])
    eq([len(x) for x in got[:3]], [1, 1, 0], "only your own words, and only since they were sent, make it land")
    eq(len(got[3]), 1, 'one entry lands one of two same messages')
    eq([len(x) for x in got[4:10]], [0, 0, 1, 0, 0, 0],
       'a paste wrap, merged messages, a whole line only, the waiting block, an image, a Talk reminder')
    eq([[(x['text'], x['state']) for x in r] for r in got[10:]],
       [[('x', 'failed')], [('x', 'sent')], [('x', 'failed')], [('x', 'sent')], [], [], [('x', 'failed')], []],
       'not delivered once idle a while; not mid-turn; a chat that ended; longer for a first message; a slash command goes; behind the cut; not before it; a picture alone')
    (tmp / 'driver.js').write_text(SENT_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs the page', r.stderr[-1500:])
    o = json.loads(r.stdout or '{}')
    eq(o.get('opened'), ['c3'], 'the started chat opens')
    eq([o.get(k) for k in ('askBeforeFeed', 'askNoTranscript', 'askOtherEntry')], [True] * 3,
       "a new chat's ask stays shown before its feed, with no transcript, and past another entry")
    eq(o.get('askLanded'), [0, '', True], 'and leaves once the feed has it')
    eq((o.get('starting'), o.get('replied')), (True, False), 'the starting line stands until the reply')
    eq(o.get('kept'), ['yes', 'and more'], 'kept over a reload')
    eq(o.get('own'), ['yes'], 'only the message in the feed leaves')
    eq((o.get('failed'), o.get('failedShown')), ([['yes', 'failed']], [True] * 3), 'never landed: Not delivered, Retry, Discard')
    wait = 'waiting for the chat to start'
    eq(o.get('held'), [['one', 'answer'], [['one', 'sending', wait], ['two', 'sending', 'sending…']]],
       'B158: a held message holds the next to its chat, not other actions')
    eq(o.get('after'), [['one', 'answer', 'one', 'two'], 0, ['one', 'two']], 'then both go, in order')
    eq(o.get('slept'), ['sending', 'sending'], 'a page that slept counts anew')
    eq(o.get('never'), [[['failed', 'c3 is still starting']] * 2, True],
       'a chat that never takes input: failed, with Retry, and the next one does not go before it')
    eq(o.get('lost'), [['c3', 'yes']], 'F114: and the outbox lists it')
    eq(o.get('late'), 0, 'one that lands after all leaves')


TABS_DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const grab = (start) => { const i = page.indexOf(start); return page.slice(i, page.indexOf('\n}\n', i) + 2) + '\n' };
const slice = (a, b) => page.slice(page.indexOf(a), page.indexOf(b, page.indexOf(a)));
const logic = page.split('<script id="logic">')[1].split('</script>')[0].replace(/if\(typeof module[^\n]*/, '');
let kept = {}, skew = 0, posts = [], gate = null;
const tabs = [], realNow = Date.now;
Date.now = () => realNow() + skew;
// a browser tab: its own page over the one storage; a change it makes tells the others, unless they are frozen
function tab(key) {
  const on = {}, t = {on, frozen: false};
  const store = {get: k => kept[k] || '', set(k, v) {
    if ((kept[k] || '') === v) return;
    if (v) kept[k] = v; else delete kept[k];
    for (const o of tabs) if (o !== t) setImmediate(() => !o.frozen && (o.on.storage || (() => {}))({key: k, newValue: v || null}))}};
  const fetch = async (p, o) => { const b = JSON.parse(o.body); posts.push(b.cid); if (gate) await gate; return {status: 200, json: async () => ({ok: true})} };
  const document = {hidden: false, addEventListener: (n, f) => { on[n] = f }};
  Object.assign(t, new Function('store', 'fetch', 'document', 'addEventListener', 'HKEY', logic
    + "const S={snap:{},ob:[]},render=()=>{},obDraw=()=>{},tq=p=>p,obDone=()=>{};"
    + slice("const OB_KEY=", '/* B154: the sent messages') + grab('function outbox(') + grab('async function drain(')
    + slice("addEventListener('storage'", '/* --- what the snapshot') + 'return {S,OB,outbox,drain,OB_KEY,obChange}')(store, fetch, document, (n, f) => { on[n] = f }, key));
  tabs.push(t); return t;
}
const wait = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  const out = {};
  // a double drain, and another tab that hears of it, while the post is slow: one post
  let open; gate = new Promise(r => { open = r });
  const a = tab('p'), b = tab('p');
  a.outbox('chat_to', {text: 'x', to: 'c1'}); a.drain(); a.drain(); b.drain();
  await wait(150); b.drain(); await wait(50); out.slow = posts.length;
  open(); gate = null; await wait(50); out.done = [posts.length, a.S.ob.length, b.S.ob.length, Object.keys(kept)];
  // a tab that was frozen meanwhile comes back: its old copy neither goes nor is put back
  posts = []; b.frozen = true; gate = new Promise(r => { open = r });
  a.outbox('chat_to', {text: 'y', to: 'c1'}); b.S.ob = a.S.ob.slice(); await wait(20); open(); gate = null; await wait(50);
  b.frozen = false; skew += 60000; b.on.visibilitychange(); await wait(150);
  out.back = [posts.length, b.S.ob.length];
  // the frozen one's old copy is not written over what another tab keeps
  b.S.ob = []; b.frozen = true; gate = new Promise(r => { open = r });
  a.outbox('chat_to', {text: 'z', to: 'c1'}); b.obChange(l => l); out.kept = JSON.parse(kept[a.OB_KEY]).length;
  open(); gate = null; await wait(50); b.frozen = false;
  // a tab that is gone mid-post leaves its item: of two others, one sends it again, with the same id
  posts = []; gate = new Promise(() => {});
  const c = tab('p'), it = c.outbox('chat_to', {text: 'w', to: 'c1'}); await wait(20); c.frozen = true; gate = null;
  a.drain(); b.drain(); await wait(150); out.early = posts.length;
  c.on.pagehide(); await wait(250);
  out.left = [posts.length, posts.every(p => p === it.cid), a.S.ob.length];
  // two messages from two tabs: each once; another project behind the same address has its own outbox
  posts = []; const o1 = a.outbox('chat_to', {text: '1', to: 'c1'}), o2 = b.outbox('chat_to', {text: '2', to: 'c1'}); await wait(150);
  out.two = posts.slice().sort().join() === [o1.cid, o2.cid].sort().join();
  const q = tab('q'); out.project = [q.OB_KEY !== a.OB_KEY, tab('').OB_KEY];
  console.log(JSON.stringify(out));
  process.exit(0);
})();
"""


def test_once_b161(tmp: Path) -> None:
    """B161: a message goes once: one tab sends an item, and the run page acts on an id once, over a restart too."""
    import threading
    fake_repo(tmp)
    token, ran, gate = W.web_token(), [], threading.Event()

    def typed(name, **a):
        ran.append(a['text'])
        gate.wait(10)
        return {'ok': True, 'out': 'sent to c1'}
    got = []
    body = {'name': 'chat_to', 'args': {'text': 'hi', 'to': 'c1'}, 'cid': 'two'}
    for again in (False, True):
        srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {})
        url = f'http://127.0.0.1:{srv.server_address[1]}/act?t={token}'
        try:
            with mock.patch.object(U, 'act', typed):
                ts = [threading.Thread(target=lambda: got.append(post(url, body)[1])) for _ in range(1 if again else 2)]
                for t in ts:
                    t.start()
                while not ran:
                    __import__('time').sleep(0.02)
                gate.set()
                for t in ts:
                    t.join(20)
        finally:
            srv.stop()
    eq(ran, ['hi'], 'two posts of one id at once, and one after a restart, type once')
    eq([(r['ok'], r['out']) for r in got], [(True, 'sent to c1')] * 3, 'each gets the first result')
    f = tmp / 'once.jsonl'
    with mock.patch.object(W.ActsOnce, 'KEEP', 3):
        once = W.ActsOnce(f)
        for i in range(20):
            once.run(f'i{i}', lambda i=i: {'ok': True, 'n': i})
        f.write_text(f.read_text() + '["cut', encoding='utf-8')
        check(len(f.read_text().splitlines()) <= 7, 'the file is kept short', f.read_text())
        eq(W.ActsOnce(f).run('i19', lambda: {})['n'], 19, 'a line cut off does not lose the rest')
        W.ActsOnce(f).run('next', lambda: {'ok': True, 'n': 1})
        eq(W.ActsOnce(f).run('next', lambda: {}).get('n'), 1, 'nor the next one kept after it')
    if not shutil.which('node'):
        print('  (no node here: the outbox tabs test is skipped)')
        return
    (tmp / 'driver.js').write_text(TABS_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs the page', r.stderr[-1500:])
    o = json.loads(r.stdout or '{}')
    eq((o.get('slow'), o.get('done')), (1, [1, 0, 0, []]), 'a double drain and two tabs post once, and leave nothing')
    eq((o.get('back'), o.get('kept')), ([1, 0], 1), "a tab that was away neither sends nor puts back its old copy")
    eq((o.get('early'), o.get('left')), (1, [2, True, 0]), 'one tab takes over the item of a tab that went, with its id')
    eq((o.get('two'), o.get('project')), (True, [True, 'ar-outbox']), 'two messages go once each; a project has its own outbox')


def test_install_command_b761(tmp: Path) -> None:
    """B761: a chat without ttyd names one install command, this machine's, once; the list of all only where no package
    manager is found. A ttyd that winget installed is found by a run that still has the PATH from before."""
    real = W.ttyd_install_cmd
    for tool, cmd in (('winget', 'winget install tsl0922.ttyd'), ('pacman', 'sudo pacman -S ttyd')):
        with mock.patch.object(W, 'ttyd_install_cmd', lambda: real(lambda t: t == tool)):
            r = W.terminal_fallback('c1')
        eq((r['cmd'], r['out'].count(cmd), r['out'].count('install ttyd') + r['out'].count('tsl0922') + r['out'].count('pacman')),
           (cmd, 1, 1), f'{tool}: its command, once, and no other')
    with mock.patch.object(W, 'ttyd_install_cmd', return_value=''):
        r = W.terminal_fallback('c1')
    check(r['cmd'] == '' and r['out'].count(W.TTYD_INSTALL) == 1, 'no package manager found: the list', r)

    winget = tmp / 'Microsoft' / 'WinGet'
    link, package = winget / 'Links' / 'ttyd.exe', winget / 'Packages' / 'tsl0922.ttyd_x' / 'ttyd.exe'
    with mock.patch('agent_runner.plat.WINDOWS', True), mock.patch('shutil.which', return_value=None), \
            mock.patch.dict(os.environ, LOCALAPPDATA=str(tmp)):
        eq((U.find_ttyd(), U.terminal_mode()), ('', 'install'), 'not installed')
        for f in (package, link):
            f.parent.mkdir(parents=True)
            f.write_text('')
            eq((U.find_ttyd(), U.terminal_mode()), (str(f), 'ttyd'), f"not on the run's PATH, in winget's {f.parent.name}")
            eq(W.Terminals('t', 1, '').argv('login', '', 2)[0], str(f), 'and it is the one that is started')


RESPONSE_DRIVER = r"""
const fs = require('fs'), page = fs.readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n'), shared = fs.readFileSync(process.argv[3] + '/030-shared.js', 'utf8');
const grab = s => { const i = page.indexOf(s); if (i < 0) throw Error(s); return page.slice(i, page.indexOf('\n}\n', i) + 2) + '\n' };
const line = s => { const i = page.indexOf(s); if (i < 0) throw Error(s); return page.slice(i, page.indexOf('\n', i)) + '\n' };
const slice = (a, b) => page.slice(page.indexOf(a), page.indexOf(b, page.indexOf(a)));
const logic = page.split('<script id="logic">')[1].split('</script>')[0].replace(/if\(typeof module[^\n]*/, '');
const kept = {}, posts = [], box = {value: '', classList: {contains: () => false}};
let answers = [];
/* one load of the page over this browser's storage */
function load() {
  return new Function('kept', 'posts', 'box', 'take', `
const on = {}, store = {get: k => kept[k] || '', set(k, v) { kept[k] = v }}, tabStore = {get: () => '', set() {}}, HKEY = 'p', CHATS_OF = 'p:';
const document = {title: 'p', querySelector: () => box}, addEventListener = (t, f) => { on[t] = f }, setTimeout = () => {}, TOUCH = () => false, typingIn = () => false;
const S = {snap: {at: 'now', sessions: [], needs: [], concepts: [], chat_quiet: 0}, ob: [], sent: {}, feeds: {}, atts: {}, sel: [], thread: null, view: 'home', f: {}, ren: null};
const tq = p => p, fetch = async (p, o) => { posts.push(o ? JSON.parse(o.body) : p); return {status: 200, json: async () => o ? take() : {}} };
const said = [], toast = t => said.push(t), esc = t => String(t).replace(/&/g, '&amp;').replace(/</g, '&lt;'), I = {}, H = {alerts: []}, HI = {}, DK = {}, HOME_PAGE = false, HOLD_MS = 1, PD = {};
const OB = {tab: 't', kept: true}, OB_TAB = 'tab:', SENT_KEY = 'sent', OB_DEAD = 1, obLoad = () => {}, obBeat = () => {}, obLive = () => [], obDraw = () => {}, takeSnap = () => {}, obTake = async () => true, OB_KEY = 'ob';
const atAll = () => false, allRow = () => '', walkRow = () => '', chatBar = () => '', homeNeeds = () => 0, histAdd = () => {}, sentMark = () => {}, loadFeed = () => {}, card = h => h, modelOf = () => '';
const chatRow = (s, q) => '[' + s.name + (q ? ' q' : '') + ']', render = () => {};
let shown = '';
const sideShow = h => { shown = h };
` + logic + shared.split('/* --- a little markdown')[0] + slice('let DR=null;', '/* the sidebar drawn again') + line('const DRAFT_KEY=') + line('const boxKey=')
  + slice('/* F201: the starting chats', 'function obCards(') + line('const newCid=') + line('function obChange(') + line('const keepSent=') + grab('function addSent(') + grab('function carrySent(') + grab('function boxMove(')
  + grab('function outbox(') + grab('async function drain(') + grab('function obDone(') + line('const agoWords=') + grab('function responseHTML(') + grab('function chatsSheet(')
  + line('function open(') + grab('async function send(') + 'function newChat(' + page.split('function newChat(')[1].split('\n}')[0].split('/* F172')[0] + `
return {S, on, said, side() { side(); return shown }, sheet: chatsSheet, view: () => responseHTML(S.thread), open, send, names: chatNames, retained: () => S.ctx};`)(kept, posts, box, () => answers.shift() || {ok: true});
}
const resp = (id, item, at, o) => ({id, item, title: 'Title ' + item, question: 'Which <look>?', ask: 'x', answer: 'Full', note: '', at, ...o});
const settle = async () => { for (let i = 0; i < 8; i++) await new Promise(r => setTimeout(r, 2)) };
(async () => {
  const out = {}, now = Date.now() / 1000; let p = load(), {S} = p;
  const snap = o => Object.assign(S.snap, {sessions: [{name: 'c1', at: now - 50, last: 'you', state: 'live'}, {name: 'c2', at: now - 90000, last: 'you', state: 'live'}], responses: [resp('2-1', 'F2', now - 10, {note: 'Keep it <b>small</b>'}), resp('1-1', 'F1', now - 100000)]}, o);
  snap(); S.seen = {};
  out.off = p.side(); out.sheet = p.sheet(); out.names = p.names();
  snap({chat_quiet: 21600}); out.quiet = p.side().match(/qline|\[c[^\]]*\]|data-thread="\+[^"]*"|newlabel/g);
  p.open('+response:2-1'); out.view = p.view(); out.opened = [S.thread, p.retained().label, posts.length, kept['ar-seen-responses:p']];
  out.after = (p.side().match(/newlabel/g) || []).length;
  p.open('c1'); out.other = [(p.side().match(/newlabel/g) || []).length, p.retained()];
  p = load(); ({S} = p); snap(); S.seen = {}; out.reload = (p.side().match(/newlabel/g) || []).length;
  // nothing starts until words are sent
  p.open('+response:2-1'); box.value = '  '; await p.send(); await settle(); out.empty = posts.length;
  box.value = 'why Full?'; answers = [{ok: false, out: 'no run is up'}]; await p.send(); out.standIn = [S.thread, p.side()]; await settle();
  out.sent = posts.filter(x => x.name); out.failed = p.side().includes('data-thread="+response:2-1"');
  S.ob = []; S.thread = null; out.discarded = p.side().includes('data-thread="+response:2-1"');
  p.open('+response:2-1'); box.value = 'again'; posts.length = 0; answers = [{ok: true, name: 'c3', ask: 'About F2', at: 1}]; await p.send(); await settle();
  out.went = [posts.filter(x => x.name).map(x => x.name), S.thread, p.side().includes('+response:2-1'), p.side().includes('+response:1-1')];
  // one whose chat was started elsewhere: the words stay
  p.open('+response:9-9'); box.value = 'late'; posts.length = 0; await p.send(); out.gone = [posts.length, box.value, p.said.length > 0, p.view().includes('no longer kept')];
  console.log(JSON.stringify(out)); process.exit(0);
})();
"""


def test_responses_f425b(tmp: Path) -> None:
    """F425b: the sent responses are rows in the Chats list's Quiet group: 'new' until opened once, no session on
    opening one, one on the first words, and then the chat stands in the row's place."""
    if not shutil.which('node'):
        print('  (no node here: the sent response script test is skipped)')
        return
    (tmp / 'driver.js').write_text(RESPONSE_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE), str(W.PAGE_DIR)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs the sent responses', r.stderr[-1500:])
    if r.returncode:
        return
    o = json.loads(r.stdout)
    row = o['off'].split('<div class="qline">Quiet</div>')
    check(len(row) == 2 and '+response' not in row[0] and row[1].count('data-thread="+response:') == 2,
          'with chat_quiet off the rows still stand under Quiet, never in the top list', o['off'])
    check('F2 Title F2' in row[1] and row[1].count('newlabel') == 2 and 'bdot' not in o['off'] and 'class="n"' not in o['off'] and 'data-del' not in row[1],
          'each with its id and title and new, with no dot and no count', row[1])
    check(o['sheet'].count('data-thread="+response:') == 2 and 'Quiet' in o['sheet'] and o['sheet'].count('newlabel') == 2, 'the switcher has them too', o['sheet'])
    eq(sorted(o['names']), ['c1', 'c2'], 'no chat among the chats a pick takes')
    eq(o['quiet'], ['[c1]', 'qline', 'data-thread="+response:2-1"', 'newlabel', '[c2 q]', 'data-thread="+response:1-1"', 'newlabel'], 'among the quiet chats, newest first')
    check(all(t in o['view'] for t in ('Which &lt;look>?', 'Full', 'Keep it &lt;b>small')), 'opened: the question, the answer, the note, escaped', o['view'])
    eq(o['opened'], ['+response:2-1', 'F2 Title F2', 0, '["2-1"]'], 'opening it asks the run for nothing')
    eq((o['after'], o['other'], o['reload']), (1, [1, None], 1), 'and takes its label off, for a reload too')
    eq(o['empty'], 0, 'no words: nothing starts')
    check(str(o['standIn'][0]).startswith('@') and 'starting' in o['standIn'][1] and 'data-thread="+response:2-1"' not in o['standIn'][1], 'words: the starting chat takes the row\'s place at once', o['standIn'])
    eq([(x['name'], x['args']) for x in o['sent']], [('response_chat', {'rid': '2-1', 'text': 'why Full?', 'wait': False})], 'one session, about that response')
    eq((o['failed'], o['discarded']), (False, True), 'a chat that did not start, discarded: the row is back')
    eq(o['went'], [['response_chat'], 'c3', False, True], 'it started: the chat is open and the row stays away under an older snapshot')
    eq(o['gone'], [0, 'late', True, True], 'a response that is gone sends nothing and keeps the words')


ANSWER_CHAT_DRIVER = r"""
const fs = require('fs'), page = fs.readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n'), shared = fs.readFileSync(process.argv[3] + '/030-shared.js', 'utf8');
const slice = (a, b) => page.slice(page.indexOf(a), page.indexOf(b, page.indexOf(a)));
const logic = page.split('<script id="logic">')[1].split('</script>')[0].replace(/if\(typeof module[^\n]*/, '');
const kept = {}, now = Date.now() / 1000;
const p = new Function('kept', 'now', `
const on = {}, store = {get: k => kept[k] || '', set(k, v) { kept[k] = v }}, tabStore = {get: () => '', set() {}}, HKEY = 'p';
const document = {title: 'p', hidden: false}, addEventListener = (t, f) => { on[t] = f }, setTimeout = () => {};
const S = {snap: {at: 'now', sessions: [], needs: [], concepts: [], chat_quiet: 21600, responses: []}, ob: [], sent: {}, feeds: {}, sel: [], thread: null, view: 'home', f: {}, ren: null};
const esc = t => String(t), I = {}, H = {alerts: []}, HOME_PAGE = false, HOLD_MS = 1, PD = {}, atAll = () => false, allRow = () => '', walkRow = () => '', chatBar = () => '', homeNeeds = () => 0;
const chatRow = (s, q) => '<button>[' + s.name + (q ? ' q' : '') + ']</button>', sideRow = (x, q) => chatRow(x, q), standRows = () => [], render = () => {};
let shown = '';
const sideShow = h => { shown = h };
` + logic + shared.split('/* --- a little markdown')[0] + slice('let DR=null;', '/* the sidebar drawn again') + `
return {S, side() { side(); return shown }, markSeen, came: answerChatCame};`)(kept, now);
const {S} = p, quiet = () => { const h = p.side().split('<div class="qline">Quiet</div>'); return [h[0].match(/\[c\d[^\]]*\]|newlabel/g), (h[1] || '').match(/\[c\d[^\]]*\]|newlabel/g)] };
S.snap.sessions = [{name: 'c1', at: now - 5, last: 'you', state: 'live'}]; S.seen = {};
const out = {};
p.came({ok: true, chat: 'c5', said: 'B2 ticked'});
S.snap.sessions.push({name: 'c5', at: now - 1, last: 'claude', state: 'live'});
out.came = quiet();
S.thread = 'c5'; p.markSeen(); S.thread = null; out.opened = quiet();
S.snap.sessions[1] = {name: 'c5', at: now, last: 'claude', needs_reply: true, state: 'live'}; out.asks = quiet();
console.log(JSON.stringify(out));
"""


def test_answer_chats_f465(tmp: Path) -> None:
    """F465: a chat a Needs you answer started rests in Quiet with 'new' until opened once, and goes to the top only
    as any chat does: when it asks the person something."""
    sent = {'ok': True, 'code': 0, 'out': 'control 7 is starting in a hidden console', 'argv': []}
    with mock.patch.object(U, 'SEND', [lambda t: sent]), mock.patch.object(U, 'answer_argv', lambda *a: ([], '')):
        r = U.answer('F9', 'why so?')
    eq(r.get('chat'), 'c7', 'the answer names the chat it started')
    eq(U.answer_chat({'ok': False, 'out': 'control 7'}), '', 'none when it did not start')
    check('answerChatCame(j)' in (W.PAGE_DIR / '020-live.js').read_text(encoding='utf-8'), 'the page takes it from the answer')
    if not shutil.which('node'):
        print('  (no node here: the answer chat script test is skipped)')
        return
    (tmp / 'driver.js').write_text(ANSWER_CHAT_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE), str(W.PAGE_DIR)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs the answer chats', r.stderr[-1500:])
    if r.returncode:
        return
    o = json.loads(r.stdout)
    eq(o['came'], [['[c1]'], ['[c5 q]', 'newlabel']], 'a chat an answer started: under Quiet, new')
    eq(o['opened'], [['[c1]'], ['[c5 q]']], 'opened once: no longer new, still quiet')
    eq(o['asks'], [['[c5]', '[c1]'], None], 'it asks the person something: at the top')


SENT_SOON_DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const grab = (start) => { const i = page.indexOf(start); return page.slice(i, page.indexOf('\n}\n', i) + 2) + '\n' };
const slice = (a, b) => page.slice(page.indexOf(a), page.indexOf(b, page.indexOf(a)));
const logic = page.split('<script id="logic">')[1].split('</script>')[0].replace(/if\(typeof module[^\n]*/, '');
const kept = {}, store = {get: k => kept[k] || '', set(k, v) { if (v) kept[k] = v; else delete kept[k] }};
let t0 = 0, answered = 0, shownSent = 0;
const fetch = async () => { await new Promise(r => setTimeout(r, 50)); answered = Date.now() - t0;
  return {status: 200, json: async () => ({ok: true, at: 1, out: 'sent to c1'})} };
const document = {hidden: false, addEventListener: () => {}};
const P = new Function('store', 'fetch', 'document', 'addEventListener', 'HKEY', logic
  + "const S={snap:{},ob:[]},obDraw=()=>{},tq=p=>p,toast=()=>{},feedOf=()=>[],esc=s=>String(s),render=()=>{};"
  + slice("const OB_KEY=", '/* B154: the sent messages') + slice('/* B154: the sent messages', '/* a new chat') + grab('const tkey=') + grab('function sentBubbles(')
  + grab('function outbox(') + grab('async function drain(') + grab('function obDone(')
  + 'return {S,outbox,sentBubbles}')(store, fetch, document, () => {}, '');
(async () => {
  t0 = Date.now(); P.outbox('chat_to', {text: 'hi', to: 'c1'});
  for (const end = Date.now() + 2000; Date.now() < end && !shownSent; await new Promise(r => setTimeout(r, 5)))
    if (/class="u pending sent"/.test(P.sentBubbles('c1', t => t))) shownSent = Date.now() - t0;
  console.log(JSON.stringify({answered, shownSent, sending: P.S.ob.length}));
  process.exit(0);
})();
"""


def test_sent_soon_b878(tmp: Path) -> None:
    """B878: a message the run took shows sent as soon as the send's own answer comes, not when the feed has it."""
    css = (W.PAGE_DIR / '060-shared.css').read_text(encoding='utf-8')
    check('.u.pending.sent{opacity:1}' in css, 'a sent bubble is not faded like one still sending')
    if not shutil.which('node'):
        print('  (no node here: the sent-soon script test is skipped)')
        return
    (tmp / 'driver.js').write_text(SENT_SOON_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs the send', r.stderr[-1500:])
    if r.returncode:
        return
    o = json.loads(r.stdout)
    print(f"  B878: answer {o['answered']} ms, bubble sent {o['shownSent']} ms")
    check(0 < o['shownSent'] <= 200, 'a 50 ms answer: the bubble is sent within 200 ms', o)
    eq(o['sending'], 0, 'and the outbox has nothing left sending')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_upload), in_tmp(test_outbox_f137), in_tmp(test_sent_b154), in_tmp(test_once_b161), in_tmp(test_install_command_b761), in_tmp(test_responses_f425b), in_tmp(test_answer_chats_f465), in_tmp(test_sent_soon_b878)]))
