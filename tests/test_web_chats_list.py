"""The run page, chats area, the chats list: rows, cards, drop, quiet (C46: split from test_web_chats.py), tests unchanged.

    python3 tests/test_web_chats_list.py
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



def test_delete_chats_f118(tmp: Path) -> None:
    """F118: the page's delete_chats reaches control.end_control for each named chat; each chat
    row has a delete button, a delete is sent only once Undo is past, and chatPick picks as Ctrl/Cmd+click
    (toggle) and Shift+click (a range from the last clicked) do."""
    from agent_runner import control as CT
    fake_repo(tmp)
    page = W.page_html().decode()
    check('data-del=' in page and 'data-undo' in page and 'data-delsel' in page and "name:'delete_chats'" in page,
          'the page: a delete button per chat, Undo, a Delete N bar, the delete_chats action')
    token = W.web_token()
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {})
    url = f'http://127.0.0.1:{srv.server_address[1]}/act?t={token}'
    ended = []
    try:
        with mock.patch.object(CT, 'end_control', lambda n, why: (ended.append(n), n != 7)[1]):
            code, out = post(url, {'name': 'delete_chats', 'args': {'names': ['c4', 'c7']}})
            eq((code, out.get('ok'), out.get('deleted'), ended), (200, True, ['c4'], [4, 7]),
               'each named chat is ended; one already gone is said so')
            code, out = post(url, {'name': 'delete_chats', 'args': {'names': ['c1']}})
            eq((out.get('ok'), ended), (True, [4, 7, 1]), 'c1 is a chat like any other')
    finally:
        srv.stop()
    if not shutil.which('node'):
        print('  (no node here: the chat pick test is skipped)')
        return
    names = ['c1', 'c3', 'c4', 'c6', 'c9']
    got = logic_js([['chatPick', names, [], '', 'c4', 'toggle'], ['chatPick', names, ['c4'], 'c4', 'c9', 'toggle'],
                    ['chatPick', names, ['c4', 'c9'], 'c9', 'c4', 'toggle'], ['chatPick', names, ['c4'], 'c4', 'c9', 'range'],
                    ['chatPick', names, [], 'c6', 'c1', 'range'], ['chatPick', names, ['c3'], 'c3', 'c1', 'toggle'],
                    ['chatPick', names, ['c3', 'c4'], 'c4', 'c6', ''], ['chatPick', names, [], '', 'c6', 'range']])
    eq(got[0], {'sel': ['c4'], 'last': 'c4'}, 'Ctrl/Cmd+click picks a chat')
    eq(got[1], {'sel': ['c4', 'c9'], 'last': 'c9'}, 'and another, in list order')
    eq(got[2], {'sel': ['c9'], 'last': 'c4'}, 'and again takes it out')
    eq(got[3], {'sel': ['c4', 'c6', 'c9'], 'last': 'c4'}, 'Shift+click picks the range from the last clicked')
    eq(got[4]['sel'], ['c1', 'c3', 'c4', 'c6'], 'a range up to c1')
    eq(got[5]['sel'], ['c1', 'c3'], 'c1 is picked as any other')
    eq(got[6], {'sel': [], 'last': 'c6'}, 'a plain click drops the pick')
    eq(got[7], {'sel': ['c6'], 'last': 'c6'}, 'Shift+click with nothing clicked before picks that one')


def test_card_chat_b139(tmp: Path) -> None:
    """B139: a run page button that starts a chat (Add a task, a card's Chat, a quick ask, Take) starts a fresh
    control session (`control --new --ask`) instead of sending to one with its whole history; typing in an open
    chat's box with no card context goes to that chat (F176: on Home to a new one)."""
    fake_repo(tmp)

    def no_send(t):
        raise AssertionError(f'a chat-starting button reached c1: {t!r}')
    ran = []
    with mock.patch.object(U, 'SEND', [no_send]), \
            mock.patch.object(U, 'RUN', [lambda argv: (ran.append(argv), (0, 'control 9 is starting'))[1]]):
        q, t = U.act('quick_ask', key='since', wait=False), U.run_control('queue_take', tid='F1', wait=False)
    eq(ran, [['control', '--new', '--no-wait', '--ask', 'what happened since my last look?', '--no-feed'],
             ['control', '--new', '--no-wait', '--ask', 'do F1 here', '--no-feed']], 'quick_ask and take use new_control')
    eq((q['name'], t['name']), ('c9', 'c9'), 'each names its new chat for the page to open')
    page = W.PAGE.read_text(encoding='utf-8')
    send = page.split('async function send(by){', 1)[1].split('\n}', 1)[0]
    check('sendReq(ctx,to,msg)' in send and "newChat(rq.name,rq.args," in send,
          'send() starts a new chat when a card set the context', send)
    check("newChat('quick_ask'" in page and "outbox('quick_ask'" not in page, 'a quick ask starts a new chat', '')
    check("if(c.chat){" in page and "newChat(rq.name,rq.args,`${c.label} ${tid}`" in page, "Do it here opens the new chat it started", '')
    if not shutil.which('node'):
        print('  (no node here: the send script test is skipped)')
        return
    got = logic_js([['sendReq', {'kind': 'need', 'id': 'R6'}, 'c1', 'About R6, which needs me: hi'],
                    ['sendReq', {'kind': 'new'}, 'c1', 'Add a task: dark mode'],
                    ['sendReq', None, '', 'hello'], ['sendReq', None, 'c6', 'hi c6']])
    eq(got[:2], [{'name': 'new_control', 'args': {'ask': 'About R6, which needs me: hi'}},
                 {'name': 'new_control', 'args': {'ask': 'Add a task: dark mode'}}],
       'a send with S.ctx set calls new_control, not chat_to c1')
    eq(got[2:], [{'name': 'new_control', 'args': {'ask': 'hello'}},
                 {'name': 'chat_to', 'args': {'text': 'hi c6', 'to': 'c6'}}],
       'with no card context the box goes to its chat, on Home to a new one (F176)')


ROW_DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const slice = (a, b) => page.slice(page.indexOf(a), page.indexOf(b, page.indexOf(a)));
const line = s => { const i = page.indexOf(s); return page.slice(i, page.indexOf('\n', i)) + '\n' };
const logic = page.split('<script id="logic">')[1].split('</script>')[0].replace(/if\(typeof module[^\n]*/, '');
const on = {true: {}, false: {}}, sent = [], opened = [], add = (t, f, c) => (on[!!c][t] = on[!!c][t] || []).push(f);
const env = {S: {snap: {sessions: ['c1', 'c2', 'c3'].map(n => ({name: n, title: n, state: 'live'}))}, f: {}, sel: [], thread: null, sheet: '', drawer: true, ob: []},
  I: new Proxy({}, {get: (t, k) => '<i>' + String(k) + '</i>'}), esc: s => String(s), CSS: {escape: s => s}, isDrawer: true, all: false,
  document: {addEventListener: add, querySelector: () => null, body: {}}, addEventListener: () => {}, window: {addEventListener: () => {}},
  chatTitle: s => s.title, chatPins: () => env.pins, pins: ['c3'], chatNames: () => ['c1', 'c2', 'c3'], replyDue: () => false, drawerOn: () => env.isDrawer, atAll: () => env.all,
  sessionOf: n => env.S.snap.sessions.find(s => s.name === n), savePins: p => { env.pins = p; env.render() },
  outbox: (n, a) => sent.push([n, a]), openSheet: n => opened.push(n), fetch: () => Promise.resolve({json: () => ({ok: true})}), tq: p => p, slashOpen: () => false,
  open: n => opened.push(n), chatPick: () => ({sel: [], last: ''}), render: () => { env.settle(); env.html = env.S.snap.sessions.map(s => env.row(s)).join('\n') }};
const known = new Proxy(env, {has: () => true, get: (t, k) => k === Symbol.unscopables ? undefined : k in t ? t[k] : k in globalThis ? globalThis[k] : () => ''});
env.env = env;
new Function('known', 'env', 'with (known) {' + logic + slice('/* F118: a chat row:', 'function chatBar(') + slice('/* F118: a delete is final', 'const card=')
  + 'let tapped={n:"",at:0};' + slice("document.addEventListener('click',async e=>{", "document.addEventListener('submit'")
  + slice("document.addEventListener('keydown',e=>{\n", "/* B188: a soft keyboard's") + slice('let noClick=false;', '/* F83: a press')
  + 'env.row=chatRow;env.settle=rowSettle;env.ren=startRename;env.save=saveRename;env.final=finalDelete}')(known, env);
const S = env.S, out = {}, row = n => env.html.split('\n').find(h => h.includes(`data-k="chat:${n}"`));
/* a tap on the element that matches these selectors */
function tap(has, dataset = {}) {
  let stopped = false;
  const el = {dataset, closest: s => s.split(',').some(p => has.includes(p.trim())) ? el : null, hasAttribute: () => false}, e = {target: el, preventDefault() {}, stopPropagation() { stopped = true }};
  on.true.click.forEach(f => f(e)); if (!stopped) on.false.click.forEach(f => f(e)); return stopped;
}
const dots = n => tap(['[data-rowmenu]'], {rowmenu: n});
const btn = (k, n) => tap(['.rowacts', '.rowacts button', `[data-${k}]`], {[k]: n});
const thread = n => tap(['[data-thread]'], {thread: n});
/* a tap on the row's right end, where the dots are: on the button that is there */
const spot = n => { const b = row(n).match(/<button[^>]*(?=><i>|>Undo)/g).filter(x => !x.includes('class="del"')).pop();
  return b.includes('data-rowmenu') ? dots(n) : b.includes('data-undo') ? tap(['[data-undo]']) : btn(b.match(/data-(ren|pin|del)=/)[1], n) };
const esc = () => on.false.keydown.forEach(f => f({key: 'Escape', preventDefault() {}, target: {closest: () => null, matches: () => false}}));
env.render(); out.closed = row('c1');
dots('c1'); out.opened = [S.rowOpen, row('c1')]; out.pinnedRow = (dots('c3'), row('c3'));
out.switched = [S.rowOpen, (env.html.match(/class="rowacts"/g) || []).length];
out.outside = [thread('c2'), S.rowOpen, opened.length, S.drawer];
dots('c1'); out.scrim = [tap(['#scrim']), S.rowOpen, S.drawer];
dots('c1'); out.title = [thread('c1'), S.rowOpen, opened.length];
dots('c1'); esc(); out.esc = [S.rowOpen, S.drawer];
dots('c1'); S.drawer = false; env.render(); out.drawer = S.rowOpen; S.drawer = true;
env.isDrawer = false; S.drawer = false; dots('c1'); out.wide = S.rowOpen; esc(); env.isDrawer = true; S.drawer = true;
dots('c1'); btn('pin', 'c1'); out.pin = [env.pins.join(), S.rowOpen];
dots('c1'); btn('ren', 'c1'); out.ren = [S.ren, S.rowOpen, env.html.includes('data-renform')];
S.f.ren = 'New name'; env.save(); out.sent = sent; env.render();
spot('c2'); out.first = [S.rowOpen, S.undo || null]; spot('c2'); out.second = [S.rowOpen, S.undo.names, row('c2')];
spot('c2'); out.undone = [S.undo, row('c2').includes('data-rowmenu')];
spot('c2'); spot('c2'); dots('c1'); out.final = [S.snap.sessions.map(s => s.name).join(), S.rowOpen];
out.sheets = opened.length; console.log(JSON.stringify(out));
"""


def test_row_buttons_f187(tmp: Path) -> None:
    """F187: on touch, a chat row's three dots open its buttons in the row: Rename, Pin, and Delete where the dots were, so
    two taps there delete, with Undo. One row at a time; a tap elsewhere, Esc or the drawer closing only closes it; no sheet."""
    page = W.PAGE.read_text(encoding='utf-8')
    check("openSheet('chat'" not in page and '\n  chat(){' not in page, 'no chat sheet')
    if not shutil.which('node'):
        print('  (no node here: the row buttons script test is skipped)')
        return
    (tmp / 'driver.js').write_text(ROW_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs the row buttons', r.stderr[-1500:])
    if r.returncode:
        return
    o = json.loads(r.stdout)
    check('" data-k="chat:c1" data-crow=' in o['closed'] and 'aria-expanded="false"' in o['closed'] and 'rowacts' not in o['closed'], 'closed: the dots only', o['closed'])
    n, html = o['opened']
    acts = html.split('class="rowacts"')[1]
    eq((n, [acts.count(f'data-{k}="c1"') for k in ('ren', 'pin', 'del')], acts.count('aria-label') - 1, 'data-rowmenu' in html), ('c1', [1, 1, 1], 3, False),
       'open: three named buttons in place of the dots')
    check(acts.index('data-ren') < acts.index('data-pin') < acts.index('data-del'), 'Delete is the last, at the right end')
    check('Unpin this chat' in o['pinnedRow'].split('class="rowacts"')[1], 'a pinned row says Unpin')
    check('.rowacts button{width:var(--tap);height:var(--tap)' in page, 'each is a full target')
    eq(o['switched'], ['c3', 1], "another row's dots switch: one row open")
    eq(o['outside'], [True, '', 0, True], 'a tap on another chat only closes it')
    eq(o['scrim'], [True, '', True], 'a tap beside the drawer too')
    eq(o['title'], [True, '', 0], 'and one on its own title')
    eq(o['esc'], ['', True], 'Esc closes the row, not the drawer')
    eq(o['drawer'], '', 'the drawer closing closes it')
    eq(o['wide'], 'c1', 'with no drawer it opens too')
    eq(o['pin'], ['c3,c1', ''], 'Pin')
    eq(o['ren'], ['c1', '', True], 'Rename, in the row')
    eq(o['sent'], [['rename_chat', {'chat': 'c1', 'title': 'New name'}]], 'the new name is sent')
    eq(o['first'], ['c2', None], 'the first tap on the dots deletes nothing')
    eq(o['second'][:2], ['', ['c2']], 'a second tap on the same spot deletes')
    check('data-undo' in o['second'][2] and 'rowacts' not in o['second'][2], 'with Undo shown there', o['second'][2])
    eq(o['undone'], [None, True], 'Undo brings it back')
    eq(o['final'], ['c1,c3', 'c1'], 'the next tap makes the delete final, as before')
    eq(o['sheets'], 0, 'no sheet opened')


# F446: the same page, with the real open() and submit, and a chat opened at once
RENAME_DRIVER = ROW_DRIVER.split('env.render(); out.closed')[0].replace(
    "'env.row=chatRow;", "line('function open(n,named)') + line('function newChat(') + line('  S.waitNew={known,at:Date.now(),ph:') "
    "+ slice(\"document.addEventListener('submit'\", 'function selectedText(') + 'env.row=chatRow;env.openReal=open;env.chatNew=newChat;") + r"""
env.viewGo = go => go(); env.chats = () => S.snap.sessions; let clock = 1e12;
env.Date = {now: () => clock}; env.S.feeds = {}; env.outbox = (n, a) => { sent.push([n, a]); return {cid: 'z'} };
const box = () => [S.ren, (env.html.match(/data-renform/g) || []).length], start = n => { S.thread = null; sent.length = 0; clock += 5000; env.ren(n); S.f.ren = 'New name' };
const key = (k, sel) => on.false.keydown.forEach(f => f({key: k, preventDefault() {}, target: {closest: () => null, matches: s => s.split(',').includes(sel)}}));
start('c1'); out.open = [box(), row('c1')];
tap(['[data-rencancel]']); out.cancel = [box(), sent.length, row('c1').includes('>c1<'), S.drawer];
start('c1'); thread('c2'); out.other = [box(), sent.length, S.thread];
start('c1'); S.drawer = false; thread('c2'); clock += 100; S.drawer = false; thread('c2'); out.twice = [box(), S.f.ren, sent.length]; S.drawer = true;
start('c1'); tap(['.renform']); tap(['[data-f="ren"]']); env.render(); out.inside = [box(), S.f.ren];
start('c1'); env.openReal('c3'); out.switcher = [box(), sent.length, S.thread];
start('c1'); env.openReal('c1'); out.same = box();
start('c1'); env.openReal('c3', true); out.named = box();
start('c1'); env.chatNew('new_control', {}, 'New chat'); out.fresh = [box(), sent.map(s => s[0]), S.thread];
start('c1'); key('Escape', '[data-f="ren"]'); out.esc = [box(), sent.length];
start('c1'); key('Escape', '[data-rencancel]'); out.escCancel = [box(), sent.length, S.drawer];
start('c1'); on.false.submit.forEach(f => f({preventDefault() {}, target: {matches: s => s === '[data-renform]'}})); out.enter = [S.ren, sent.slice()];
console.log(JSON.stringify(out));
"""


def test_rename_cancel_f446(tmp: Path) -> None:
    """F446: a rename is cancelled by its Cancel button, by opening another chat any way, or Esc; Enter still saves."""
    if not shutil.which('node'):
        print('  (no node here: the rename script test is skipped)')
        return
    (tmp / 'driver.js').write_text(RENAME_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs the rename row', r.stderr[-1500:])
    if r.returncode:
        return
    o = json.loads(r.stdout)
    gone, kept = [None, 0], ['c1', 1]
    eq(o['open'][0], kept, 'the rename row')
    check('type="button" data-rencancel aria-label="Cancel rename"' in o['open'][1] and '<i>x</i>' in o['open'][1], 'it has a Cancel button', o['open'][1])
    eq(o['cancel'], [gone, 0, True, True], 'Cancel closes it, keeps the old name and the drawer, sends nothing')
    eq(o['other'], [gone, 0, 'c2'], 'one press on another chat cancels and opens it')
    eq(o['twice'], [['c2', 1], 'c2', 0], 'a double-click on another chat moves the rename to it')
    eq(o['inside'], [kept, 'New name'], 'a press inside the row or a redraw keeps it')
    eq(o['switcher'], [gone, 0, 'c3'], 'another chat opened any other way cancels it')
    eq(o['same'], kept, 'its own chat opened does not')
    eq(o['named'], kept, 'nor a starting chat that gets its name')
    eq(o['fresh'], [gone, ['new_control'], '@z'], 'a new chat cancels it')
    eq(o['esc'], [gone, 0], 'Esc cancels')
    eq(o['escCancel'], [gone, 0, True], 'Esc on the Cancel button cancels, and leaves the drawer')
    eq(o['enter'], [None, [['rename_chat', {'chat': 'c1', 'title': 'New name'}]]], 'Enter saves')


def test_chats_f128(tmp: Path) -> None:
    """F128, F129: the menu button's dot, a badge on a chat that needs a reply, quiet chats last and gray, and Rename."""
    fake_repo(tmp)
    page = W.page_html().decode()
    for part in ("count={home:needs,concepts:cn}", 'due=needs||cn;S.menuDot=!!due', "${S.menuDot?'<span class=\"bdot\"></span>':''}",
                 'title="needs your reply"', "quiet?' quiet':''", '<div class="qline">Quiet</div>', 'data-renform',
                 "outbox('rename_chat',{chat:n,title}", "SEEN_KEY='ar-seen'+(HKEY?':'+HKEY:'')", 'data-rowmenu=', '.crow.quiet .thread{color:'):
        check(part in page, f'the page has {part}')
    ran, token = [], W.web_token()
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {})
    try:
        with mock.patch.object(U, 'RUN', [lambda argv: (ran.append(argv), (0, 'renamed'))[1]]):
            code, out = post(f'http://127.0.0.1:{srv.server_address[1]}/act?t={token}',
                             {'name': 'rename_chat', 'args': {'chat': 'c4', 'title': 'Login woes'}})
    finally:
        srv.stop()
    eq((code, out.get('ok'), ran), (200, True, [['control', '--rename', '4', 'Login woes']]), 'the rename action')
    eq(W.run_snapshot().get('chat_quiet'), 21600, "the snapshot says when a chat is quiet")
    if not shutil.which('node'):
        print('  (no node here: the Chats script test is skipped)')
        return
    now = 1_000_000
    row = lambda n, **k: {'name': n, 'title': n, 'last': 'claude', 'at': now - 50000, 'needs_reply': False, **k}  # noqa: E731
    rows = [row('c1'), row('c2'), row('c3', needs_reply=True), row('c4', renamed=True), row('c5', at=now - 60), row('c6'), row('c7'),
            row('c8', at=0), row('c9')]
    o = {'pins': ['c6'], 'quiet': 21600, 'now': now, 'seen': {f'c{i}': now for i in range(1, 9)}, 'up': None}
    got = logic_js([['chatGroups', rows, o], ['chatGroups', rows, {**o, 'quiet': 0}], ['chatGroups', rows, {**o, 'up': 'c2'}],
                    ['needsReply', row('c2'), now], ['needsReply', row('c2'), now - 60000], ['needsReply', row('c2', last='tool'), 0],
                    ['needsReply', row('c2', needs_reply=True), now],
                    ['chatName', {'name': 'c1', 'title': 'Base', 'renamed': True}], ['chatName', {'name': 'c1', 'title': 'Base'}]])
    names = lambda g: ([x['name'] for x in g['top']], [x['name'] for x in g['quiet']])  # noqa: E731
    eq(names(got[0]), (['c3', 'c4', 'c5', 'c6', 'c8', 'c9'], ['c1', 'c2', 'c7']),
       'quiet last: not one that needs a reply (c3, c9 unread), a renamed, a fresh, a pinned or a new one')
    eq(names(got[1])[1], [], 'chat_quiet off: none')
    check('c2' in names(got[2])[0] and 'c1' in names(got[2])[1], 'the open chat that was up stays up, no other')
    eq(got[3:7], [False, True, False, True], 'a badge: unread since it spoke, or an open question; not while it works')
    eq(got[7:], ['Base', 'Base'], 'c1 shows its title as any other')


QUIET_DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const line = s => { const i = page.indexOf(s); return page.slice(i, page.indexOf('\n', i)) + '\n' };
const slice = (a, b) => page.slice(page.indexOf(a), page.indexOf(b, page.indexOf(a)));
const logic = page.split('<script id="logic">')[1].split('</script>')[0].replace(/if\(typeof module[^\n]*/, '');
const now = Date.now() / 1000, old = now - 50000;
const map = (m = {}) => ({m, get: k => m[k] || '', set: (k, v) => { m[k] = v }});
/* one load of the page: its Chats code over the tab's and the browser's storage; look() is a draw's part of it */
function load(tab, store, thread = null, hkey = 'a') {
  return new Function('tabStore', 'store', 'now', 'thread', 'HKEY', `
const document = {hidden: false, title: ''}, talkName = () => '', addEventListener = () => {}, render = () => {};
const S = {snap: {sessions: [], chat_quiet: 21600}, thread, view: 'home'};
` + logic + slice('const chatPins=', 'const chatNames=') + slice('/* B193: S.up', 'const replyDue=') + line('const groupChats=') + line('const shownChats=') + `
const names = g => [g.top.map(x => x.name).join(' '), g.quiet.map(x => x.name).join(' ')];
return {S, look(n) { if (n !== undefined) S.thread = n; markSeen(); return names(shownChats()) }};`)(tab, store, now, thread, hkey);
}
const c = (name, o) => ({name, last: 'claude', at: old, needs_reply: false, ...o});
const seen = o => map({'ar-seen:a': JSON.stringify(o)});
const rows = () => [c('c1'), c('c2'), c('c3'), c('c4', {at: now - 60})];
const out = {}, tab = map(), store = seen({c1: old, c2: old, c4: now - 60});
let p = load(tab, store); p.S.snap.sessions = rows();
out.before = p.look();
out.quiet = [p.look('c2'), p.look()];                    // a quiet chat opened: no move, draw after draw
p = load(tab, store, 'c2'); out.reload = [p.look()]; p.S.snap.sessions = rows(); out.reload.push(p.look(), p.look());
p.S.snap.sessions[1].at = now; out.said = p.look();       // something new is said in it
p.S.snap.sessions[1].at = old; p.S.seen.c2 = old; out.held = p.look();     // then it gets old while open
p.S.snap.sessions[1].at = old; out.unread = [p.look('c3'), p.look()];      // an old unread one, marked seen as it opens
p = load(tab, store, 'c3'); p.look(); p.S.snap.sessions = rows(); out.unreadReload = [p.look(), p.look()];
out.closed = p.look(null);
p = load(tab, store, 'c1'); p.S.snap.sessions = rows(); p.S.snap.chat_pins = ['c1']; out.pinned = p.look();
const t2 = map(); p = load(t2, map(), 'c1'); p.S.snap.sessions = rows(); p.look(); out.first = p.look();   // a first visit
const all = map(); out.by = [];   // B205: two projects and the run's own page, one localStorage
for (const [k, at] of [['a', old], ['b', old + 5], ['', old + 9]]) {
  p = load(map(), all, null, k); p.S.snap.sessions = [c('c1', {at})]; out.by.push(p.look()) }
p = load(map(), all, null, 'b'); p.S.snap.sessions = [c('c1', {at: now})]; p.look('c1');   // b's c1 opened again
p = load(map(), all, null, 'a'); p.S.snap.sessions = [c('c1')]; out.still = p.look();
out.kept = Object.fromEntries(Object.entries(all.m).map(([k, v]) => [k, JSON.parse(v).c1 === {'ar-seen:a': old, 'ar-seen:b': now, 'ar-seen': old + 9}[k]]));
console.log(JSON.stringify(out));
"""


def test_quiet_stays_b193(tmp: Path) -> None:
    """B193: opening a chat never moves it between the chats and Quiet, draw after draw and over a reload."""
    if not shutil.which('node'):
        print('  (no node here: the Quiet script test is skipped)')
        return
    (tmp / 'driver.js').write_text(QUIET_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs the Chats code', r.stderr[-1500:])
    if r.returncode:
        return
    o, still = json.loads(r.stdout), ['c4 c3', 'c2 c1']
    eq(o['before'], still, 'c1 and c2 are quiet; c3 is old but unread')
    eq(o['quiet'], [still, still], 'a quiet chat opened stays in Quiet')
    eq(o['reload'], [['', ''], still, still], 'and over a reload')
    eq(o['said'], ['c2 c4 c3', 'c1'], 'something new said in it brings it up')
    eq(o['held'], ['c4 c3 c2', 'c1'], 'and it stays up while it is open')
    eq(o['unread'], [still, still], 'an old unread chat marked seen as it opens stays up')
    eq(o['unreadReload'], [still, still], 'and over a reload')
    eq(o['closed'], ['c4', 'c3 c2 c1'], 'it goes Quiet once closed')
    eq(o['pinned'], ['c1 c4', 'c3 c2'], 'an open quiet chat comes up when pinned')
    eq(o['first'], ['c4', 'c3 c2 c1'], 'a first visit takes all as read')
    eq(o['by'], [['', 'c1']] * 3, "B205: each project's first visit takes its chats as read")
    eq(o['still'], ['', 'c1'], "opening another project's c1 leaves this one read")
    eq(o['kept'], {'ar-seen:a': True, 'ar-seen:b': True, 'ar-seen': True}, 'the record is kept by project')


def test_needs_drop_chat_f110(tmp: Path) -> None:
    """F110, F143: a Needs you card's Drop asks in the page, then need_drop; its Chat sends need_chat and opens a new chat (run_control)."""
    fake_repo(tmp)
    page = W.page_html().decode()
    for part in ('restBtns(n)', 'actSure(n.acts,n.id)', 'needChatAsk(n)'):
        check(part in page, f'the run app has {part}')
    ask = logic_js([['needChatAsk', {'id': 'R1', 'title': 'Phone', 'label': 'CONFIRM', 'ask': 'Does it work?',
                                     'answers': U.need_answers({'label': 'CONFIRM'})}]])[0]
    check('R1' in ask and 'Does it work?' in ask and '- Yes' in ask and '- No' in ask, 'the question and its answers show at once', ask)


SURE_DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const line = a => page.slice(page.indexOf(a), page.indexOf('\n', page.indexOf(a)) + 1);
const S = {snap: {controls: JSON.parse(process.argv[3])}, sure: 'need_drop:R1'}, cutsOff = () => '';
eval(line('const esc=') + line('const controlOf=') + line('const sureHTML=') + line('const ctlSure=') + line('const actSure=')
  + `console.log(JSON.stringify([actSure(['need_drop'], 'R1'), actSure(['need_drop'], 'R2')]))`);
"""


def test_drop_confirm_id_b191(tmp: Path) -> None:
    """B191: the Drop confirm on a Needs you item names that item, and only that item asks."""
    if not shutil.which('node'):
        print('  (no node here: the Drop confirm test is skipped)')
        return
    drop = [{k: c[k] for k in ('key', 'label', 'confirm')} for c in U.RUN_CONTROLS if c['key'] == 'need_drop']
    (tmp / 'driver.js').write_text(SURE_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE), json.dumps(drop)],
                       capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs the page script', r.stderr[-800:])
    asked_, other = json.loads(r.stdout or '["", ""]')
    check('Drop R1? It leaves the plan' in asked_ and '{id}' not in asked_, "the confirm has the row's id", asked_)
    eq(other, '', 'another item asks nothing')


DELETE_DRIVER = r"""
const fs = require('fs'), src = fs.readFileSync(process.argv[2], 'utf8');
const fn = name => { const i = src.indexOf('function ' + name + '('); let d = 0, j = src.indexOf('{', i);
  for (let k = j; k < src.length; k++) { if (src[k] === '{') d++; else if (src[k] === '}' && !--d) return src.slice(i, k + 1) } };
const rows = () => S.snap.sessions.map(s => s.name), out = {}, toasts = [];
let S, answer, drawn;
const toast = (t, bad) => toasts.push([t, !!bad]), actFailed = (j, t) => toast(t, true), plainErr = e => String(e), tq = x => x;
const render = () => { drawn = rows() };
const fetch = () => new Promise(r => { answer = r });
const snapLine = src.split('\n').find(l => l.includes('// B876: chats deleted here stay off')).split('//')[0];
eval(fn('finalDelete') + ';globalThis.finalDelete=finalDelete');
const delGoneOff = () => { const s = {}; eval(snapLine) };  // takeSnap's own line
const fresh = () => { S = {snap: {sessions: ['c1', 'c2', 'c3', 'c4'].map(name => ({name}))}, undo: {names: ['c2', 'c3'], bar: true}, thread: 'c2'}; globalThis.S = S };
(async () => {
  fresh(); finalDelete(); out.sameFrame = [drawn, S.thread];
  S.snap = {...S.snap, sessions: ['c1', 'c2', 'c3', 'c4'].map(name => ({name}))}; delGoneOff(); out.stale = rows();
  answer({json: () => ({ok: true})}); await new Promise(r => setTimeout(r, 0)); out.ok = [rows(), toasts.length];
  fresh(); finalDelete(); answer({json: () => ({ok: false, error: 'no'})}); await new Promise(r => setTimeout(r, 0));
  out.failed = [rows(), drawn, toasts.slice(), S.thread];
  fresh(); finalDelete(); answer(Promise.reject('down')); await new Promise(r => setTimeout(r, 0));
  out.down = rows();
  console.log(JSON.stringify(out)); process.exit(0);
})();
"""


def test_delete_at_once_b876(tmp: Path) -> None:
    """B876: deleted chats leave the list in the same frame, before the server answers; a snapshot taken
    before the delete does not bring them back; a failed delete puts them back with a toast."""
    if not shutil.which('node'):
        print('  (no node here: the delete script test is skipped)')
        return
    (tmp / 'page.js').write_text(W.page_html().decode(), encoding='utf-8')
    (tmp / 'driver.js').write_text(DELETE_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(tmp / 'page.js')], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs the delete', r.stderr[-1500:])
    if r.returncode:
        return
    o = json.loads(r.stdout)
    eq(o['sameFrame'], [['c1', 'c4'], None], 'both rows go in the first draw, before any answer; the open one closes')
    eq(o['stale'], ['c1', 'c4'], 'an older snapshot keeps them off')
    eq(o['ok'], [['c1', 'c4'], 0], 'the server says yes: they stay gone, no toast')
    eq(o['failed'], [['c1', 'c2', 'c3', 'c4'], ['c1', 'c2', 'c3', 'c4'], [['The delete did not work', True]], 'c2'],
       'a failed delete puts them back in their places, the open chat open again, with a toast')
    eq(o['down'], ['c1', 'c2', 'c3', 'c4'], 'and so does no answer at all')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_delete_at_once_b876), in_tmp(test_delete_chats_f118), in_tmp(test_card_chat_b139), in_tmp(test_row_buttons_f187), in_tmp(test_rename_cancel_f446), in_tmp(test_chats_f128), in_tmp(test_quiet_stays_b193), in_tmp(test_needs_drop_chat_f110), in_tmp(test_drop_confirm_id_b191)]))
