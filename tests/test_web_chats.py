"""The run page, chats area (agent_runner/page/*-chats.*): split from test_web.py (C41b), tests unchanged.

    python3 tests/test_web_chats.py
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


def test_new_chat(tmp: Path) -> None:
    """F84: a + on the Chats heading row starts a new chat (new_control through /act, which runs control --new)."""
    fake_repo(tmp)
    page = W.page_html().decode()
    check('<div class="shead row"><span>Chats</span><button class="shadd" data-new title="New chat">${I.plus}Chat</button>' in page,
          'the + Chat sits at the end of the Chats heading row')
    eq(len(re.findall(r'<button[^>]* data-new[ >]', page)), 1, 'F150: and nowhere else but the top bar (plusBtn, B762)')
    check("newChat('new_control',{},'New chat')" in page and "outbox(name,{...args,wait:false}" in page,
          'data-new sends new_control through the outbox, without waiting (F137)')
    token = W.web_token()
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {})
    calls = []
    try:
        link = 'https://claude.ai/code/session_abc'
        with mock.patch.object(U, 'RUN', [lambda argv: (calls.append(argv), (0, f'started c7: {link}'))[1]]):
            code, out = post(f'http://127.0.0.1:{srv.server_address[1]}/act?t={token}',
                             {'name': 'new_control', 'args': {}})
        eq((code, out.get('ok'), out.get('link')), (200, True, link), 'new_control answers with the new link')
        eq(calls, [['control', '--new']], 'its endpoint runs control --new')
    finally:
        srv.stop()


def test_esc_ctrl_c(tmp: Path) -> None:
    """B116: on the run app Esc never goes back while interrupting (B120: in the box it interrupts a working chat,
    out of it only goes back); Ctrl+C interrupts the open
    chat while it works (not over selected text), and the message box has a Stop button."""
    page = W.page_html().decode()
    start = page.index("document.addEventListener('keydown'")
    handler = page[start:page.index('\n});', start)]
    lines = handler.splitlines()
    esc_lines = [ln for ln in lines if "e.key==='Escape'" in ln]
    check(len(esc_lines) >= 2, 'the keydown handler has its Esc branches', esc_lines)
    # B120: in the message box Esc interrupts a working chat (after the menu closes); out of it, never
    out_of_box = handler[handler.index("if(e.key==='Escape'&&S.sel.length)"):]
    for ln in esc_lines:
        if ln.strip() in out_of_box:
            check('interrupt' not in ln, 'an Esc branch out of the box sends no interrupt', ln)
    esc_int = [ln for ln in esc_lines if 'interrupt' in ln]
    check(len(esc_int) == 1 and 'shownSession()' in esc_int[0] and 'busy(n)' in esc_int[0] and 'S.thread=null' not in esc_int[0],
          'Esc in the box interrupts only a working chat, and does not go back', esc_int)
    check(any("e.key==='Escape'" in ln and 'blur()' in ln for ln in lines), 'Esc in the box leaves it')
    check(any("e.key==='Escape'&&S.thread&&" in ln and 'S.thread=null' in ln for ln in lines), 'Esc out of the box goes back')
    ctrl = [ln for ln in lines if 'e.ctrlKey' in ln]
    check(len(ctrl) == 1 and "act('interrupt',{session:n})" in ctrl[0] and 'busy(n)' in ctrl[0]
          and '!selectedText(' in ctrl[0], 'Ctrl+C interrupts the working chat, not over selected text', ctrl)
    check('class="send stop" data-stop="${esc(shownNow)}"' in page, 'the box has a Stop button while the session works')
    check("if(x=q('[data-stop]')){const n=x.dataset.stop||shownSession();if(n)act('interrupt',{session:n});return}" in page,
          'Stop interrupts the session it stands by')


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


SLASH_DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n'), CMDS = JSON.parse(process.argv[3]);
const slice = (a, b) => { const i = page.indexOf(a); return page.slice(i, page.indexOf(b, i) + b.length); };
const logic = page.split('<script id="logic">')[1].split('</script>')[0];
const handlers = {}, store = {v: {}, get(k) { return this.v[k] || '' }, set(k, v) { this.v[k] = v }};
const DRAFT_KEY = k => k, boxKey = () => 'c1', grow = () => {}, esc = s => String(s), tq = p => p;
const S = {thread: 'c1', sel: [], drawer: false};
const TOUCH = () => false, busy = () => false, act = () => {}, selectedText = () => false, render = () => {};
let sent = 0; const send = () => { sent++ };
const menu = {hidden: true, innerHTML: '', querySelector() { return null }};
const ta = {value: '', blurred: 0, matches(s) { return s === '[data-in]' }, focus() {}, blur() { this.blurred++ },
            setSelectionRange() {}, closest() { return null }};
const document = {activeElement: ta, addEventListener(t, f) { handlers[t] = f },
                  querySelector(s) { return s === '[data-slash]' ? menu : s === '[data-in]' ? ta : null }};
const fetch = () => Promise.resolve({json: () => Promise.resolve(CMDS)});
eval(logic + slice('const SL={', 'ta.value.length);\n}\n') + slice("document.addEventListener('keydown',", '\n});\n') + `
(async () => {
  await new Promise(r => setTimeout(r, 0));
  const out = {}, type = v => { ta.value = v; slashShow(ta) };
  const rows = () => [...menu.innerHTML.matchAll(/<b>\\/([^<]*)<\\/b>/g)].map(m => m[1]);
  const key = k => handlers.keydown({key: k, target: ta, preventDefault() {}});
  type('/'); out.slash = {hidden: menu.hidden, rows: rows()};
  type('/s'); out.s = rows();
  key('ArrowDown'); out.on = (menu.innerHTML.match(/class="on"[^>]*><b>\\/([^<]*)/) || [])[1];
  key('Enter'); out.picked = {value: ta.value, hidden: menu.hidden, sent};
  type('/co'); key('Escape'); out.esc = {hidden: menu.hidden, blurred: ta.blurred, value: ta.value, thread: S.thread};
  type('hello /run'); out.mid = menu.hidden;
  type('/clear'); key('Enter'); out.full = {sent, hidden: menu.hidden};
  console.log(JSON.stringify(out));
})();`);
"""


def test_slash_menu_b119(tmp: Path) -> None:
    """B119: typing / in the message box shows the session's slash commands (/commands: the control session's own
    skills, the agent CLI's built-ins, the project's skills) as a menu that filters as you type; arrows and Enter
    pick, Esc closes the menu and stays in the chat, and a command typed in full is sent."""
    repo = fake_repo(tmp)
    (repo / '.claude' / 'skills' / 'deploy').mkdir(parents=True)
    (repo / '.claude' / 'skills' / 'deploy' / 'SKILL.md').write_text(
        '---\nname: deploy\ndescription: Ship the site\n---\nDo it.\n', encoding='utf-8')
    token = W.web_token()
    (tmp / 'home' / '.claude' / 'commands').mkdir(parents=True)  # the person's own, apart from this machine's
    (tmp / 'home' / '.claude' / 'commands' / 'notes.md').write_text('---\ndescription: Take notes\n---\nGo.\n')
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {})
    try:
        with mock.patch.object(Path, 'home', return_value=tmp / 'home'):
            code, body = get(f'http://127.0.0.1:{srv.server_address[1]}/commands?t={token}')
    finally:
        srv.stop()
    eq(code, 200, '/commands answers')
    cmds = json.loads(body)
    names = [c['name'] for c in cmds]
    eq(names[:7], ['run', 'since', 'follow', 'control', 'pause', 'stop', 'slots'], "the control session's own first")
    check({'clear', 'compact', 'deploy', 'notes'} <= set(names), "the built-ins, the project's skill and the "
          "person's command are listed", names)
    eq(len(names), len(set(names)), 'each name once')
    eq(next(c['desc'] for c in cmds if c['name'] == 'run'), "The agent-runner run's status",
       'a description without its (the person typed …)')
    eq(next(c['desc'] for c in cmds if c['name'] == 'deploy'), 'Ship the site', "a skill's description")
    if not shutil.which('node'):
        print('  (no node here: the slash menu script test is skipped)')
        return
    got = logic_js([['slashMatches', cmds, '/sl'], ['slashMatches', [], '/pa'], ['slashMatches', cmds, 'hi'],
                    ['slashMatches', cmds, '/run now'], ['slashMove', 0, 3, 'ArrowUp'], ['slashMove', 2, 3, 'ArrowDown']])
    eq(got[0][0]['name'], 'slots', '/sl filters to /slots first')
    eq([c['name'] for c in got[1]], ['pause', 'compact'], 'no list from the run page: the fixed list stands in')
    eq(got[2:4], [[], []], 'no menu without a leading / or once a space follows the command')
    eq(got[4:], [2, 0], 'the arrows wrap round')
    few = [{'name': n, 'desc': ''} for n in ('run', 'since', 'slots', 'control', 'clear', 'compact', 'cost')]
    (tmp / 'driver.js').write_text(SLASH_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE), json.dumps(few)], capture_output=True,
                       text=True, timeout=60)
    check(r.returncode == 0, 'node runs the slash menu', r.stderr[-800:])
    got = json.loads(r.stdout or '{}')
    eq(got.get('slash'), {'hidden': False, 'rows': [c['name'] for c in few]}, "'/' shows the menu with every command")
    eq(got.get('s'), ['since', 'slots', 'cost'], "'/s' filters: names that start with s, then those that hold it")
    eq(got.get('on'), 'slots', 'ArrowDown moves the highlight')
    eq(got.get('picked'), {'value': '/slots ', 'hidden': True, 'sent': 0}, 'Enter picks it into the box, not sent')
    eq(got.get('esc'), {'hidden': True, 'blurred': 0, 'value': '/co', 'thread': 'c1'},
       'Esc closes the menu and stays in the box and the chat')
    eq(got.get('mid'), True, 'a / later in the words shows no menu')
    eq(got.get('full'), {'sent': 1, 'hidden': True}, 'Enter on a command typed in full sends it')


def test_chat_keys_b200(tmp: Path) -> None:
    """B200: Runner Home's projects share one localStorage, so a chat's draft, history and sent messages are kept by
    project: c1 of one project never shows another's. A page with no project in its address keeps the plain names."""
    if not shutil.which('node'):
        return
    driver = tmp / 'keys.js'
    driver.write_text(r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const line = s => { const i = page.indexOf(s); if (i < 0) throw new Error(s); return page.slice(i, page.indexOf('\n', i)) + '\n' };
const slice = (a, b) => { const i = page.indexOf(a); return page.slice(i, page.indexOf(b, i)) };
const logic = page.split('<script id="logic">')[1].split('</script>')[0].replace(/if\(typeof module[^\n]*/, '');
const kept = {}, store = {get: k => kept[k] || '', set(k, v) { if (v) kept[k] = v; else delete kept[k] }};
const load = path => new Function('store', 'location', logic + 'const HOME_PAGE=false,S={};' + line('const HB=')
  + line('const CHATS_OF=') + line('const DRAFT_KEY=') + line('const HIST_KEY=') + line('function histGet(') + line('function histAdd(')
  + line('const newCid=') + slice('const SENT_KEY=', 'function addSent(')
  + 'return {S,DRAFT_KEY,histGet,histAdd,keepSent}')(store, {pathname: path});
const a = load('/p/a/');
store.set(a.DRAFT_KEY('c1'), 'draft a'); a.histAdd('c1', 'hist a');
a.S.sent = {c1: {pending: [{id: 'i', text: 'sent a', at: 0, since: Date.now(), state: 'sent'}]}}; a.keepSent();
const see = path => { const p = load(path); return [store.get(p.DRAFT_KEY('c1')), p.histGet('c1'), Object.keys(p.S.sent)] };
const out = {a: see('/p/a/'), b: see('/p/b/'), own: see('/')};
const own = load('/'); store.set(own.DRAFT_KEY('c1'), 'd'); own.histAdd('c1', 'h'); own.S.sent = a.S.sent; own.keepSent();
out.keys = Object.keys(kept).sort();
console.log(JSON.stringify(out));
""", encoding='utf-8')
    r = subprocess.run(['node', str(driver), str(W.PAGE)], capture_output=True, text=True, encoding='utf-8', timeout=60)
    check(r.returncode == 0, 'node runs the chat keys', r.stderr[-800:])
    got = json.loads(r.stdout or '{}')
    eq(got.get('a'), ['draft a', ['hist a'], ['c1']], "a project's chat keeps its draft, history and sent messages over a load")
    eq((got.get('b'), got.get('own')), (['', [], []], ['', [], []]), "another project's c1 shows none of them")
    eq(got.get('keys'), ['ar-draft:a:c1', 'ar-draft:c1', 'ar-hist:a:c1', 'ar-hist:c1', 'ar-sent', 'ar-sent:a'],
       'the keys hold the project, where the address does')


COMPOSER_DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');  // a Windows checkout is CRLF
const slice = (a, b) => { const i = page.indexOf(a); return page.slice(i, page.indexOf(b, i) + b.length); };
const logic = page.split('<script id="logic">')[1].split('</script>')[0];
const handlers = {}, acts = [];
const store = {v: {}, get(k) { return this.v[k] || '' }, set(k, v) { if (v) this.v[k] = v; else delete this.v[k] }};
const CHATS_OF = '', DRAFT_KEY = k => 'ar-draft:' + k, grow = () => {}, esc = s => String(s), tq = p => p;
const S = {thread: 'c1', sel: [], drawer: false, view: 'home'};
const boxKey = () => S.thread || 'home';
let BUSY = false, sent = 0, prevented = 0, TALK = '';
const talkName = () => TALK, TOUCH = () => false;
const busy = () => BUSY, act = (n, a) => { acts.push([n, a.session]) }, selectedText = () => false,
      render = () => {}, send = () => { sent++ };
const menu = {hidden: true, innerHTML: '', querySelector() { return null }};
const ta = {value: '', blurred: 0, selectionStart: 0, selectionEnd: 0, matches(s) { return s === '[data-in]' },
            focus() {}, blur() { this.blurred++ }, closest() { return null },
            setSelectionRange(a, b) { this.selectionStart = a; this.selectionEnd = b }};
const document = {activeElement: ta, addEventListener(t, f) { handlers[t] = f },
                  querySelector(s) { return s === '[data-slash]' ? menu : s === '[data-in]' ? ta : null }};
const fetch = () => Promise.resolve({json: () => Promise.resolve([])});
eval(logic + slice('const HIST_KEY=', 'return true;\n}\n') + slice('const SL={', 'ta.value.length);\n}\n')
     + slice('const shownSession=', ";\n") + slice("document.addEventListener('click',", '\n});\n')
     + slice("document.addEventListener('keydown',", '\n});\n') + `
(async () => {
  await new Promise(r => setTimeout(r, 0));
  const out = {};
  const key = (k, o) => { const was = prevented; handlers.keydown(Object.assign({key: k, target: ta,
    preventDefault() { prevented++ }}, o || {})); return prevented > was };
  const at = (v, c) => { ta.value = v; ta.selectionStart = ta.selectionEnd = c == null ? v.length : c };
  histAdd('c1', 'first'); histAdd('c1', 'second\\nline'); histAdd('c1', 'second\\nline'); histAdd('c2', 'other');
  out.stored = JSON.parse(store.get('ar-hist:c1'));
  at('draft');
  out.up1 = [key('ArrowUp'), ta.value, store.get('ar-draft:c1')];
  out.upMid = [key('ArrowUp'), ta.value];          // the caret on the recalled message's last line: Up moves it
  ta.setSelectionRange(0, 0);
  out.up2 = [key('ArrowUp'), ta.value];
  out.upTop = [key('ArrowUp'), ta.value];
  out.down1 = [key('ArrowDown'), ta.value];
  out.down2 = [key('ArrowDown'), ta.value];
  out.down3 = [key('ArrowDown'), ta.value];
  out.draft = store.get('ar-draft:c1');
  S.thread = 'c2'; at('');
  out.other = [key('ArrowUp'), ta.value];
  S.thread = 'c3'; at('');
  out.none = [key('ArrowUp'), ta.value];
  S.thread = 'c1'; at('one');
  out.shift = [key('Enter', {shiftKey: true}), sent];
  out.enter = [key('Enter'), sent];
  BUSY = true; at('x');
  out.escBusy = [key('Escape'), acts.slice(), ta.blurred, S.thread];
  BUSY = false;
  out.escIdle = [key('Escape'), acts.length, ta.blurred, S.thread];
  store.v['ar-hist:c4'] = 'not json'; S.thread = 'c4'; at('');
  out.bad = [key('ArrowUp'), ta.value];
  // B142: Esc in the box interrupts the shown session too: none on Home, the Talk session in the Talk view
  S.thread = null; S.view = 'home'; BUSY = true; acts.length = 0; at('x');
  out.homeEsc = [key('Escape'), acts.slice()];
  acts.length = 0; S.view = 'talk'; TALK = 'c7';
  out.talkEsc = [key('Escape'), acts.slice()];
  acts.length = 0; S.view = 'home'; BUSY = false; const blurs = ta.blurred;
  out.homeEscIdle = [key('Escape'), acts.length, ta.blurred - blurs];
  // B141: on Home (no chat open) Ctrl+C and Stop interrupt nothing (F176); in the Talk view the Talk session
  S.thread = null; S.view = 'home'; BUSY = true; acts.length = 0;
  const ctrlC = () => key('c', {ctrlKey: true});
  out.homeCtrlC = [ctrlC(), acts.slice()];
  acts.length = 0;
  handlers.click({target: {closest: s => s === '[data-stop]' ? {dataset: {stop: ''}} : null}});
  out.homeStop = acts.slice();
  acts.length = 0; S.view = 'talk'; TALK = 'c7';
  out.talkCtrlC = [ctrlC(), acts.slice()];
  acts.length = 0; TALK = '';
  out.talkNone = [ctrlC(), acts.slice()];
  acts.length = 0; S.view = 'home'; BUSY = false;
  out.homeIdle = [ctrlC(), acts.slice()];
  console.log(JSON.stringify(out));
})();`);
"""


def test_composer_keys_b120(tmp: Path) -> None:
    """B120: the run app's message box takes Claude Code's keys: Up and Down recall the messages sent in that chat
    (kept per chat in localStorage), Shift+Enter makes a new line and Enter sends, Esc interrupts a working chat;
    the keys are listed once (BOX_KEYS); without ttyd the page shows one line with this machine's install command."""
    page = W.page_html().decode()
    check('const BOX_KEYS=[' in page and page.count('keysLine()') >= 2, 'the keys are listed once, in BOX_KEYS, and '
          'shown under the box')
    check("'ar-hist:'+CHATS_OF+k" in page and 'localStorage' in page, 'the history is kept per chat in localStorage')
    check("S.snap.terminal_mode==='install'" in page and 'A chat shows the real session with ttyd' in page,
          'without ttyd the page says a chat needs it')
    eq(W.ttyd_install_cmd(lambda t: t == 'pacman'), 'sudo pacman -S ttyd', 'Arch: pacman')
    eq(W.ttyd_install_cmd(lambda t: t == 'brew'), 'brew install ttyd', 'macOS: brew')
    eq(W.ttyd_install_cmd(lambda t: False), '', 'no package manager known: no command')
    with mock.patch.object(W, 'ttyd_install_cmd', return_value='sudo pacman -S ttyd'):
        eq(W.with_extras({'terminal_mode': 'install'}).get('ttyd_install'), 'sudo pacman -S ttyd',
           'the snapshot carries the install command when ttyd is missing')
        check('ttyd_install' not in W.with_extras({'terminal_mode': 'ttyd'}), 'and not when ttyd is there')
    if not shutil.which('node'):
        print('  (no node here: the message box keys test is skipped)')
        return
    got = logic_js([['histPush', ['a'], ' b '], ['histPush', ['a', 'b'], 'b'], ['histPush', ['a'], '  '],
                    ['histStep', 2, None, 'ArrowUp'], ['histStep', 2, 0, 'ArrowUp'], ['histStep', 2, 1, 'ArrowDown'],
                    ['histEdge', 'ab\ncd', 1, 1, 'ArrowUp'], ['histEdge', 'ab\ncd', 4, 4, 'ArrowUp'],
                    ['histEdge', 'ab\ncd', 1, 1, 'ArrowDown'], ['histEdge', 'ab', 0, 2, 'ArrowUp']])
    eq(got[:3], [['a', 'b'], ['a', 'b'], ['a']], 'a sent message joins the history, not twice in a row, not blank')
    eq(got[3:6], [1, 0, 2], 'Up from the draft goes to the last message, stops at the first; Down comes back')
    eq(got[6:], [True, False, False, False], 'Up and Down leave the text only from its first / last line')
    (tmp / 'driver.js').write_text(COMPOSER_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs the message box keys', r.stderr[-800:])
    got = json.loads(r.stdout or '{}')
    eq(got.get('stored'), ['first', 'second\nline'], 'the history is stored per chat, a repeat once')
    eq(got.get('up1'), [True, 'second\nline', ''], 'Up recalls the last message sent in this chat, not saved as '
       'the draft')
    eq(got.get('upMid'), [False, 'second\nline'], 'Up off its first line moves the caret, as in Claude Code')
    eq(got.get('up2'), [True, 'first'], 'Up on the first line recalls the one before')
    eq(got.get('upTop'), [True, 'first'], 'Up at the oldest stays there')
    eq(got.get('down1'), [True, 'second\nline'], 'Down goes forward again')
    eq(got.get('down2'), [True, 'draft'], 'Down past the last brings back the unsent draft')
    eq(got.get('down3'), [False, 'draft'], 'Down at the draft does nothing more')
    eq(got.get('draft'), 'draft', 'the draft is saved again')
    eq(got.get('other'), [True, 'other'], "another chat recalls its own messages")
    eq(got.get('none'), [False, ''], 'a chat with no history leaves Up alone')
    eq(got.get('shift'), [False, 0], 'Shift+Enter is left to the box (a new line), not sent')
    eq(got.get('enter'), [True, 1], 'Enter sends')
    eq(got.get('escBusy'), [True, [['interrupt', 'c1']], 0, 'c1'], 'Esc interrupts the working chat and stays in it')
    eq(got.get('escIdle'), [True, 1, 1, 'c1'], 'Esc in an idle chat leaves the box, sends nothing, does not go back')
    eq(got.get('bad'), [False, ''], 'a broken stored history is read as none')
    eq(got.get('homeEsc'), [True, []], 'B142, F176: Esc on Home interrupts nothing')
    eq(got.get('talkEsc'), [True, [['interrupt', 'c7']]], 'B142: in the Talk view, the Talk session')
    eq(got.get('homeEscIdle'), [True, 0, 1], 'B142: Esc on Home leaves the box')
    eq(got.get('homeCtrlC'), [False, []], 'F176: Ctrl+C with no chat open is the browser\'s')
    eq(got.get('homeStop'), [], 'Stop with no chat open interrupts nothing')
    eq(got.get('talkCtrlC'), [True, [['interrupt', 'c7']]], 'in the Talk view Ctrl+C interrupts the Talk session')
    eq(got.get('talkNone'), [False, []], 'a Talk view with no Talk session yet interrupts nothing')
    eq(got.get('homeIdle'), [False, []], 'no chat open leaves Ctrl+C to the browser')
    check('data-stop="${esc(shownNow)}"' in page, "the box's Stop names the shown session")


ENTER_DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const slice = (a, b) => { const i = page.indexOf(a); if (i < 0) throw Error(a); return page.slice(i, page.indexOf(b, i) + b.length); };
const logic = page.split('<script id="logic">')[1].split('</script>')[0];
const handlers = {}, window = globalThis;
let COARSE = false, log = [];
globalThis.matchMedia = q => ({matches: q === '(pointer:coarse)' && COARSE});
const S = {thread: null, view: 'home', sel: [], atts: {}, f: {}}, store = {v: {}, get(k) { return this.v[k] || '' }, set(k, v) { this.v[k] = v }};
const DRAFT_KEY = k => k, boxKey = () => 'k', esc = s => String(s), tq = p => p, I = {}, HI = {i: null};
const busy = () => false, act = () => {}, selectedText = () => false, render = () => {}, histKey = () => false;
const send = () => log.push('send');
const shownSession = () => '', sessWorks = busy, dictWhy = () => '', micWhy = () => '', DK = {};
const menu = {hidden: true, innerHTML: '', querySelector() { return null }};
const el = sel => ({value: '', style: {}, scrollHeight: 90, offsetHeight: 92, clientHeight: 90, matches(s) { return s === sel }, focus() {}, blur() {}, setSelectionRange() {}, closest() { return null }});
const ta = el('[data-in]');
const document = {activeElement: ta, addEventListener(t, f) { handlers[t] = f },
                  querySelector(s) { return s === '[data-slash]' ? menu : s === '[data-in]' ? ta : null }};
const fetch = () => Promise.resolve({json: () => Promise.resolve([{name: 'clear', desc: ''}])});
eval(logic + slice('const TOUCH=', ';\n') + slice('const enterHint=', ';') + slice('function box(ph,foot){', '\n}\n')
     + slice('let boxWas=', '\n}\n') + 'function growGlide(){}\nfunction sendDraw(){}\n'
     + slice('const SL={', 'ta.value.length);\n}\n') + slice("document.addEventListener('keydown',", '\n});\n')
     + slice("document.addEventListener('beforeinput',", '\n});\n')
     + slice("document.addEventListener('input',", ')}});\n') + `
(async () => {
  await new Promise(r => setTimeout(r, 0));
  const keys = {enter: {}, shift: {shiftKey: true}, ctrl: {ctrlKey: true}, cmd: {metaKey: true},
                ime: {isComposing: true}, imeSafari: {keyCode: 229}, imeCtrl: {isComposing: true, ctrlKey: true}};
  const press = (t, o) => { log = []; let p = false;
    handlers.keydown(Object.assign({key: 'Enter', target: t, preventDefault() { p = true }}, o));
    return log.length ? log.join() : p ? 'taken' : 'line' };
  const all = t => Object.fromEntries(Object.entries(keys).map(([k, o]) => [k, press(t, o)]));
  const out = {};
  for (COARSE of [false, true]) {
    const o = out[COARSE ? 'touch' : 'fine'] = {};
    for (const [n, thread, view] of [['chat', 'c1', 'home'], ['new', '+new', 'home'], ['home', null, 'home'], ['talk', null, 'talk']]) {
      S.thread = thread; S.view = view; ta.value = 'hi'; menu.hidden = true;
      o[n] = {keys: all(ta), hint: box('', '').includes('data-in enterkeyhint="enter"')};
    }
    handlers.input({target: ta}); o.grown = ta.style.height;
    ta.value = '/cl'; slashShow(ta); o.pick = [press(ta, {}), ta.value];
    ta.value = '/clear'; slashShow(ta); o.full = press(ta, {});
    ta.value = '/cl'; slashShow(ta); o.pickIme = [press(ta, {keyCode: 229}), ta.value];
    const brk = (v, more, key) => { ta.value = v; slashShow(ta); let p = false;
      if (key) press(ta, key);
      handlers.beforeinput(Object.assign({inputType: 'insertLineBreak', target: ta, preventDefault() { p = true }}, more));
      return [p ? 'taken' : 'line', ta.value] };
    ta.value = '/cl'; slashShow(ta); o.pickShift = [press(ta, {shiftKey: true}), ta.value];
    o.brk229 = brk('/cl', {}, {keyCode: 229}); o.brkNoKey = brk('/cl', {}, {key: 'Unidentified'});
    o.brkIme = brk('/cl', {isComposing: true}, {isComposing: true}); o.brkWord = brk('/cl', {inputType: 'insertText'});
    o.brkFull = brk('/clear', {}, {keyCode: 229}); o.brkNone = brk('hi', {});
  }
  console.log(JSON.stringify(out));
})();`);
"""


def test_enter_b181(tmp: Path) -> None:
    """B181: with a coarse main pointer Enter is a new line in every message box, the box grows, and Ctrl/Cmd+Enter or
    the Send button sends; with a fine one Enter sends and Shift+Enter is a new line. Enter picks in the slash menu
    with both, and an input method that is composing never sends."""
    if not shutil.which('node'):
        print('  (no node here: the Enter test is skipped)')
        return
    (tmp / 'driver.js').write_text(ENTER_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs the Enter keys', r.stderr[-800:])
    got = json.loads(r.stdout or '{}')
    ime = {'ime': 'line', 'imeSafari': 'line', 'imeCtrl': 'line'}
    for kind in ('fine', 'touch'):
        o, touch = got.get(kind, {}), kind == 'touch'
        for name in ('chat', 'new', 'home', 'talk'):
            want = {'enter': 'line' if touch else 'send', 'shift': 'line', 'ctrl': 'send', 'cmd': 'send', **ime}
            eq(o.get(name, {}).get('keys'), want, f'{kind}, {name}: what Enter does')
            eq(o.get(name, {}).get('hint'), touch, f"{kind}, {name}: the keyboard's key says enter only on touch")
        eq(o.get('grown'), '90px', f'{kind}: the message box grows')
        eq(o.get('pick'), ['taken', '/clear '], f'{kind}: Enter picks in the slash menu, not sent')
        eq(o.get('full'), 'line' if touch else 'send', f'{kind}: Enter on a command typed in full')
        eq(o.get('pickIme'), ['line', '/cl'], f'{kind}: composing, Enter picks nothing')
        # B188: a phone's Return may carry its keyboard's own Shift, or come as keyCode 229 or with no key name
        picked = ['taken', '/clear '] if touch else ['line', '/cl']
        eq(o.get('pickShift'), picked, f'{kind}: Enter with Shift in the slash menu')
        eq(o.get('brk229'), picked, f'{kind}: a line break after a keyCode 229 keydown')
        eq(o.get('brkNoKey'), picked, f'{kind}: a line break after a keydown with no key name')
        eq(o.get('brkIme'), ['line', '/cl'], f'{kind}: composing, a line break picks nothing')
        eq(o.get('brkWord'), ['line', '/cl'], f'{kind}: typing picks nothing')
        eq(o.get('brkFull'), ['line', '/clear'], f'{kind}: a line break on a command typed in full')
        eq(o.get('brkNone'), ['line', 'hi'], f'{kind}: a line break with no menu open')


def test_interrupt_c1_b141(tmp: Path) -> None:
    """B141: interrupt c1 types Escape into its hidden session's FIFO, <notes>/control1.in, and the feed shows
    the transcript's interrupt as 'interrupted'."""
    from agent_runner import slots as SLT
    fake_repo(tmp)
    S.C.notes('control1.live').write_text(str(os.getpid()), encoding='utf-8')
    typed = []
    with mock.patch('agent_runner.plat.WINDOWS', False), \
            mock.patch.object(SLT, 'send_fifo_raw', lambda p, b: typed.append((p.name, b)) or True):
        r = U.interrupt('c1')
    eq((r['ok'], typed, r['out']), (True, [('control1.in', b'\x1b')], 'interrupted c1'),
       'interrupt c1 sends Escape to control1.in')
    row = {'type': 'user', 'message': {'content': [{'type': 'text', 'text': '[Request interrupted by user]'}]}}
    eq(U.feed_entries([row]), [{'kind': 'out', 'text': 'interrupted'}], "the page's feed then shows 'interrupted'")


def test_chat_order_f133(tmp: Path) -> None:
    """F133, F201: the pinned chats, set through /act chat_order, are kept by the run (a file in the notes dir) in
    their order: in the snapshot after a reload, and a new server's; a deleted chat drops out. Each chat row has a pin
    button, only a pinned one drags, by pointer events, and chatMove places it among the pins."""
    fake_repo(tmp)
    page = W.page_html().decode()
    check('data-pin=' in page and "act('chat_order'" in page and "'pointerdown'" in page and "closest('.crow.pinned[data-crow]')" in page,
          'the page: a pin button per chat, only pinned rows dragged by pointer events, the chat_order action')
    sessions = [{'name': n} for n in ('c1', 'c3', 'c4', 's1')]
    token = W.web_token()

    def snap_of(srv) -> dict:
        return json.loads(get(f'http://127.0.0.1:{srv.server_address[1]}/snapshot?t={token}')[1])

    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {'sessions': sessions})
    try:
        eq(snap_of(srv)['chat_pins'], [], 'nothing kept yet: no pins')
        url = f'http://127.0.0.1:{srv.server_address[1]}/act?t={token}'
        code, out = post(url, {'name': 'chat_order', 'args': {'pins': ['c4', 'c1']}})
        eq((code, out.get('ok')), (200, True), 'chat_order is taken')
        eq(post(url, {'name': 'chat_order', 'args': {'order': 'c4'}})[1].get('ok'), False, 'order must be a list')
        eq(post(url, {'name': 'chat_order', 'args': {'nope': 1}})[1].get('ok'), False, 'an unknown arg is refused')
        eq(post(url, {'name': 'chat_order', 'args': {'pins': 'c4'}})[1].get('ok'), False, 'so must pins')
        eq(post(url, {'name': 'chat_order', 'args': {}})[1].get('ok'), False, 'and one of them is there')
        s = snap_of(srv)
        eq((s.get('chat_order'), s['chat_pins']), (None, ['c4', 'c1']), 'a reload shows the pins in their order')
        eq(post(url, {'name': 'chat_order', 'args': {'order': ['c1', 'c3', 'c4']}})[1].get('ok'), True, 'order alone')
        eq(snap_of(srv)['chat_pins'], ['c1', 'c4'], "a page from before: the pins in its order, no chat more")
    finally:
        srv.stop()
    check(W.S.C.notes(W.CHAT_ORDER_FILE).exists(), 'kept in the notes dir')
    sessions = [{'name': n} for n in ('c1', 'c3', 'c7', 's1')]  # c4 deleted, c7 new
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {'sessions': sessions})
    try:
        eq(snap_of(srv)['chat_pins'], ['c1'], 'a new server (another page, a phone): the deleted pinned chat drops out')
    finally:
        srv.stop()
    if not shutil.which('node'):
        print('  (no node here: the chat move test is skipped)')
        return
    pins = ['c4', 'c1', 'c3']
    got = logic_js([['chatMove', pins, 'c3', 0], ['chatMove', pins, 'c4', 9], ['chatMove', pins, 'c9', 1]])
    eq(got, [['c3', 'c4', 'c1'], ['c1', 'c3', 'c4'], pins], 'a pin dropped lands there, or at the end; no other chat does')


SORT_DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const line = s => { const i = page.indexOf(s); if (i < 0) throw Error(s); return page.slice(i, page.indexOf('\n', i)) + '\n' };
const slice = (a, b) => page.slice(page.indexOf(a), page.indexOf(b, page.indexOf(a)));
const logic = page.split('<script id="logic">')[1].split('</script>')[0].replace(/if\(typeof module[^\n]*/, '');
const now = 1e6, row = (name, at, o) => ({name, at: at && now - at, last: 'you', ...o});
const p = new Function('now', `
const shown = [], PD = {}, HOLD_MS = 15000, HOME_PAGE = false, I = {}, H = {alerts: []};
const S = {snap: {needs: [], chat_quiet: 21600}, seen: {}, sel: [], ob: [], thread: null, ren: null};
const Date = {now: () => now * 1000}, esc = s => String(s), atAll = () => false, working_ = () => [], allRow = () => '', walkRow = () => '', chatBar = () => '';
const homeNeeds = () => 0, sessionOf = n => S.snap.sessions.find(s => s.name === n), chatRow = (s, q) => '[' + s.name + (q ? ' q' : '') + ']', sideShow = h => shown.push(h);
` + logic + line('const chatPins=') + line('const chats=') + line('const chatNames=') + line('const groupChats=') + line('const shownChats=')
  + slice('let DR=null;', 'function side(){') + slice('function side(){', '/* the sidebar drawn again')
  + slice('/* F201: the starting chats', 'function obCards(') + `
return {S, PD, chatNames, drag(d) { DR = d }, draw() { shown.length = 0; side();
  return shown.length ? (shown[0].match(/\\[c[^\\]]*\\]|data-k="chat:[^"]*"/g) || []).map(x => x.replace(/data-k="chat:|["\\[\\]]/g, '')).join(' ') : 'kept' }};`)(now);
const {S} = p, out = {}, at = (n, t) => { S.snap.sessions.find(s => s.name === n).at = now - t };
S.snap.sessions = [row('c1', 90), row('c2', 50000), row('c3', 10), row('c4', 60000), row('c5', 30), row('c6', 40000), row('c10', 30)];
out.order = p.draw();
S.snap.chat_pins = ['c4', 'c1']; S.snap.chat_order = ['c6', 'c5', 'c1', 'c4']; out.pins = p.draw(); out.next = p.chatNames();
S.ob = [{newchat: true, cid: 'a', say: 'A', state: 'failed', at: 1}, {newchat: true, cid: 'b', say: 'B', state: 'sending', at: 2}, {name: 'chat_to', cid: 'x'}];
out.starting = p.draw(); out.startNext = p.chatNames();
S.ob = S.ob.slice(0, 1); S.came = [{name: 'c11', was: '@b', start: 2, say: 'B', state: 'sending', at: now * 1000}]; S.ren = 'c5'; out.namedEdit = p.draw(); S.ren = null; out.named = p.draw();
S.snap.sessions.push(row('c11', 0)); S.ob = []; out.up = p.draw(); at('c11', 1); out.active = p.draw();
S.snap.sessions.pop(); out.gone = p.draw();
at('c5', 1); out.moved = p.draw();
S.ren = 'c3'; at('c10', 0.5); S.snap.sessions.push(row('c12', 0)); out.edit = p.draw();
at('c2', 0.2); out.editQuiet = p.draw(); S.ren = null; out.edited = p.draw();
S.ren = 'c6'; S.ob = [{newchat: true, cid: 'z', say: 'Z'}]; out.low = p.draw(); S.ren = null; S.ob = [];
out.before = p.draw(); at('c3', 0.1); p.PD.row = now * 1000; out.press = [p.draw(), p.PD.late]; p.PD.row = now * 1000 - 20000; out.long = p.draw(); p.PD.row = 0;
p.drag({on: true}); out.drag = p.draw(); p.drag(null); out.after = p.draw();
console.log(JSON.stringify(out));
"""


def test_chats_newest_f201(tmp: Path) -> None:
    """F201: the sidebar's chats, and Quiet, go newest to oldest by last activity, the pins first in their own order,
    then the chats still starting; next and previous follow; no row moves under a drag, a name edit or a press."""
    if not shutil.which('node'):
        print('  (no node here: the chat sort test is skipped)')
        return
    (tmp / 'driver.js').write_text(SORT_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs the sidebar', r.stderr[-1500:])
    if r.returncode:
        return
    o = json.loads(r.stdout)
    eq(o['order'], 'c3 c10 c5 c1 c6 q c2 q c4 q', 'both lists newest first; the same time: the newer chat')
    eq(o['pins'], 'c4 c1 c3 c10 c5 c6 q c2 q', 'pins first in their own order; a kept order of the rest places nothing')
    eq(o['next'], ['c4', 'c1', 'c3', 'c10', 'c5', 'c6', 'c2'], 'the order next, previous and a range follow')
    eq(o['starting'], 'c4 c1 @b @a c3 c10 c5 c6 q c2 q', 'starting chats first under the pins, the last started on top')
    eq(o['startNext'], o['next'], 'a starting chat is no chat to pick yet')
    eq(o['named'], 'c4 c1 c11 @a c3 c10 c5 c6 q c2 q', 'one with its name, not in the snapshot yet, keeps its place')
    eq(o['namedEdit'], o['named'], 'and during a name edit')
    eq(o['up'], 'c4 c1 c11 c3 c10 c5 c6 q c2 q', 'a chat with no activity time keeps that place')
    eq(o['active'], o['up'], 'and so once it is active')
    eq(o['gone'], o['pins'], 'one that ended does not come back as starting')
    eq(o['moved'], 'c4 c1 c5 c3 c10 c6 q c2 q', 'the chat last active moves up')
    eq(o['edit'], 'c4 c1 c5 c3 c10 c12 c6 q c2 q', 'a name edit: no row moves; a new chat goes last')
    eq(o['editQuiet'], o['edit'], 'nor out of Quiet')
    eq(o['edited'], 'c4 c1 c12 c2 c10 c5 c3 c6 q', 'once it ends they do')
    eq(o['low'], 'c4 c1 c12 c2 c10 c5 c3 c6 q @z', 'an edit in Quiet: what is new goes under it')
    eq(o['press'], ['kept', True], 'a press on a row: not drawn until it ends')
    eq(o['long'], 'c4 c1 c12 c3 c2 c10 c5 c6 q', 'but never for long')
    eq([o['drag'], o['after']], ['kept', o['long']], 'a drag holds the list too')


def test_answer_button_b138(tmp: Path) -> None:
    """B138: a Needs you button through /act runs the plan command itself, never an AI session (SEND fails if
    called), and its ok result names the item gone; the page drops that item at once and keeps it off while a
    snapshot taken before the answer still lists it; a failed answer keeps it."""
    from agent_runner import plan as P
    fake_repo(tmp)
    P.block('F1', 'CONFIRM: check the board loads on your phone', todo=S.C.todo)

    def no_send(text):
        raise AssertionError(f'an answer button reached an AI session: {text!r}')
    ran = []
    token = W.web_token()
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {})
    url = f'http://127.0.0.1:{srv.server_address[1]}/act?t={token}'
    try:
        with mock.patch.object(U, 'RUN', [lambda argv: (ran.append(argv), (0, 'confirmed and ticked F1'))[1]]), \
                mock.patch.object(U, 'SEND', [no_send]):
            code, yes = post(url, {'name': 'run_control', 'args': {'key': 'need_yes', 'tid': 'F1', 'text': 'Yes'}})
            code, no = post(url, {'name': 'run_control', 'args': {'key': 'need_no', 'tid': 'F1', 'text': 'No'}})
    finally:
        srv.stop()
    eq(ran, [['plan', 'confirm', 'F1', 'Yes'], ['plan', 'change', 'F1', 'No: the check failed']],
       'Yes is plan confirm, No is plan change (reopened)')
    eq((yes['ok'], yes['said'], yes['gone']), (True, 'F1 ticked', 'F1'), 'the result says what was done')
    eq(no['said'], 'F1 reopened: the check failed', "No's words")
    page = W.PAGE.read_text(encoding='utf-8')
    check("if(S.f&&(it.args.note||it.args.why||(it.name==='answer'&&!it.args.button)))delete S.f['askre:'+it.need]" in page,
          'F162a: the reply box is emptied only of words that were sent', '')
    check("obCards(x=>x.need)" in page, 'the answer stands in Needs you while it is sent (F137)', '')
    if not shutil.which('node'):
        print('  (no node here: the page script test is skipped)')
        return
    needs = [{'id': 'F1'}, {'id': 'R6'}]
    got = logic_js([
        ['goneMark', {}, yes, 1000],
        ['needsShown', needs, {'F1': 1000}, 2000],
        ['needsShown', needs, {'F1': 1000}, 1000 + 31000],
        ['goneMark', {}, {'ok': False, 'out': 'plan: F1 is not waiting'}, 1000],
        ['answerSaid', yes, 'F1', 'Yes'],
    ])
    eq(got[0], {'F1': 1000}, 'an ok result marks the item answered')
    eq(got[1], [{'id': 'R6'}], 'the page drops it at once, and a stale snapshot keeps it off')
    eq(got[2], needs, 'a while later the run\'s own list counts again')
    eq(got[3], {}, 'a failed answer marks nothing: the item stays')
    eq(got[4], 'F1 ticked', 'the toast says what was done')


def test_pick_f138(tmp: Path) -> None:
    """F138: an option button's /pick link answers the item with no AI session and no page token: a good code
    confirms it (`plan confirm ID "go with B: <its name>"`) and is burnt; a reused, wrong or missing code is
    refused, and so is an item settled already. pick-links prints one link per option, with no token in them;
    with no https address it says so and prints none."""
    import io
    from contextlib import redirect_stderr, redirect_stdout
    from agent_runner import cmds, plan as P
    fake_repo(tmp)
    token = W.web_token()
    off = mock.patch.dict(os.environ, {'AGENT_RUNNER_HOME_CONFIG': str(tmp / 'no-home')})  # F167: not this machine's Home
    off.start()
    https = lambda port, t: [f'https://box.tail.ts.net:8771/?t={t}']
    cid, build = P.concept_shown('tabs or a drawer', 'https://claude.ai/artifact/k1', ['a.py'],
                                 todo=S.C.todo, done=S.C.done)
    copy = S.C.notes('concepts', f'{cid}.html')
    copy.parent.mkdir(parents=True, exist_ok=True)
    copy.write_text('<h1>Menu</h1><h2>A: tabs</h2><p>x</p><h2>B: drawer (recommended)</h2><p>y</p>', encoding='utf-8')
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.object(W, 'tailscale_https_urls', https), mock.patch.object(cmds, 'init', lambda: None), \
            redirect_stdout(out):
        rc = cmds.cmd_pick_links([cid, 'A,B,C'])
    eq(rc, 0, 'pick-links prints the links')
    lines = out.getvalue().split()
    eq(len(lines), 6, 'one link per option')
    eq([lines[0], lines[2], lines[4]], ['A', 'B', 'C'], 'each line names its option')
    link = lines[3]
    check(link.startswith(f'https://box.tail.ts.net:8771/pick?id={cid}&k=') and link.endswith('&o=B'),
          'a link is the run page https base /pick?id&k&o', link)
    check(token not in out.getvalue() and 't=' not in out.getvalue(), 'no page token in the links', out.getvalue())
    code = re.search(r'&k=([^&]+)', link)[1]
    eq(json.loads(W.pick_file(cid).read_text())['code'], code, 'the code is kept in .runner/pick-codes')
    check(code != token, 'the code is not the page token')
    with mock.patch.object(W, 'tailscale_https_urls', lambda port, t: []), mock.patch.object(cmds, 'init', lambda: None), \
            redirect_stdout(out), redirect_stderr(err):
        rc = cmds.cmd_pick_links([cid, 'A,B'])
    eq(rc, 1, 'no https address: no links')
    check('no https address' in err.getvalue(), 'and it says so', err.getvalue())
    ran = []
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {})
    base = f'http://127.0.0.1:{srv.server_address[1]}'

    def fake_run(argv):
        ran.append(argv)
        return 0, 'approved'
    try:
        with mock.patch.object(U, 'RUN', [fake_run]):
            c1, wrong = get(f'{base}/pick?id={cid}&o=B&k=nope')
            c2, tok = get(f'{base}/pick?id={cid}&o=B&k={token}')
            c3, ok = get(f'{base}{link[link.index("/pick"):]}')
            c4, again = get(f'{base}{link[link.index("/pick"):]}')
    finally:
        srv.stop()
    eq((c1, c2), (403, 403), 'a wrong code, or the page token, is refused')
    check(b'unknown' in wrong, 'and says the link is unknown', wrong)
    eq(c3, 200, 'the good code answers')
    eq(ran, [['plan', 'confirm', cid, 'go with B: drawer']], 'it runs plan confirm with the option name')
    check(b'Approved B (drawer)' in ok and f'the run starts {build}'.encode() in ok, 'and says what it did', ok)
    eq(c4, 409, 'the code is burnt: a second tap is refused')
    check(b'used already' in again, 'and says it was used', again)
    check(json.loads(W.pick_file(cid).read_text()).get('used'), 'the code file is marked used')
    # an item settled already
    P.block('F1', 'DECIDE: which colour', todo=S.C.todo)
    code1 = W.pick_code('F1')
    with mock.patch.object(U, 'need_label', lambda tid: ''):
        eq(W.pick('F1', 'A', code1)[0], 409, 'an item settled already is refused')
    eq(W.pick_code('F1'), code1, 'an unused code is kept for the next links')
    with mock.patch.object(U, 'RUN', [fake_run]):
        eq(W.pick('F1', 'A', code1)[0], 200, 'a DECIDE answers too')
    eq(ran[-1], ['plan', 'confirm', 'F1', 'go with A'], 'with its option')
    check(W.pick_code('F1') != code1, 'once used, new links get a new code')
    eq(W.pick('../x', 'A', code1)[0], 403, 'a bad id is unknown')
    eq(W.pick('F1', '', '')[0], 403, 'no code: unknown')
    off.stop()


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
    send = page.split('async function send(){', 1)[1].split('\n}', 1)[0]
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
        q, t = U.act('quick_ask', key='since', wait=False), U.run_control('task_take', tid='F1', wait=False)
    eq(ran, [['control', '--new', '--no-wait', '--ask', 'what happened since my last look?', '--no-feed'],
             ['control', '--new', '--no-wait', '--ask', 'do F1 here', '--no-feed']], 'quick_ask and take use new_control')
    eq((q['name'], t['name']), ('c9', 'c9'), 'each names its new chat for the page to open')
    page = W.PAGE.read_text(encoding='utf-8')
    send = page.split('async function send(){', 1)[1].split('\n}', 1)[0]
    check('sendReq(ctx,to,msg)' in send and "newChat(rq.name,rq.args," in send,
          'send() starts a new chat when a card set the context', send)
    check("newChat('quick_ask'" in page and "outbox('quick_ask'" not in page, 'a quick ask starts a new chat', '')
    check("if(c.chat){" in page and "newChat(rq.name,rq.args,`${c.label} ${tid}`" in page, "Take back opens the new chat it started", '')
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


NEW_VIEW_DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const grab = s => { const i = page.indexOf(s); return page.slice(i, page.indexOf('\n}\n', i) + 2) + '\n' };
const line = s => { const i = page.indexOf(s); return page.slice(i, page.indexOf('\n', i)) + '\n' };
const logic = page.split('<script id="logic">')[1].split('</script>')[0].replace(/if\(typeof module[^\n]*/, '');
const log = {acts: [], fetched: [], focus: 0, draws: 0}, kept = {}, ta = {value: ''}, tab = {};
const env = {S: {snap: {at: 'now', sessions: [], needs: [], queue: [{id: 'F1', title: 'Board page'}], concepts: [{id: 'K5', concept: 'K5', title: 'Lazy layout', lead: "This chat is about concept K5 'Lazy layout': its page https://claude.ai/artifact/k5.", acts: ['concept_chat', 'concept_drop']}]},
    view: 'home', thread: null, ctx: null, atts: {}, ob: [], sel: [], feeds: {}, sent: {}},
  HI: {i: null}, DK: {}, I: {}, HOME_PAGE: false, HB: '', location: {hash: ''}, PLACE_KEY: 'p', placeWas: '', CHATS_OF: '', FD: {}, TOUCH: () => false,
  store: {get: k => kept[k] || '', set: (k, v) => { if (v) kept[k] = v; else delete kept[k] }},
  tabStore: {get: k => tab[k] || '', set: (k, v) => { tab[k] = v }},
  document: {querySelector: () => ta, addEventListener: (t, f) => { env.on = env.on || {}; (env.on[t] = env.on[t] || []).push(f) }},
  settingOf: v => v === 'ui.x' ? {table: 'ui', key: 'x', name: 'A setting'} : null,
  outbox: (name, args, o) => { log.acts.push([name, args]); const it = {cid: 'k' + log.acts.length, name, args, ...o}; env.S.ob.push(it); return it },
  chats: () => [], kbFocus: () => { log.focus++ }, setTimeout: () => 0, fetch: p => { log.fetched.push(p); return Promise.reject(0) }, tq: p => p,
  card: h => h, emptyCard: h => h, esc: t => String(t), starting: () => false, Date, Math,
  render: () => { log.draws++; env.keepPlace(); ta.value = kept['ar-draft:' + env.boxKey()] || '' }};
const known = new Proxy(env, {has: () => true, get: (t, k) => k === Symbol.unscopables ? undefined : k in t ? t[k] : k in globalThis ? globalThis[k] : () => ''});
env.env = env;
const names = ['about', 'send', 'open', 'goView', 'keepPlace', 'takePlace', 'boxKey', 'shownSession', 'threadTitle', 'feedHTML', 'box', 'keptCheck', 'feedLoad', 'homeHTML', 'conceptsHTML', 'conceptCard', 'upload', 'attsMove'];
new Function('known', 'env', 'with (known) {' + logic + line('const DRAFT_KEY=') + line('const boxKey=') + line('const shownSession=') + line('const sessionOf=')
  + line('const isAgent=') + line('const threadTitle=') + grab('function box(') + line('const feedNow=') + grab('async function feedLoad(') + grab('function feedHTML(')
  + grab('async function loadFeed(') + line('function keepPlace(') + grab('function takePlace(') + grab('function keptCheck(')
  + line('function open(') + line('function goView(') + grab('async function send(') + 'function viewGo(go){go()}' + line('function newChat(') + line("  S.waitNew={known,at:Date.now(),ph:'@'+it.cid};open(")
  + grab('function about(') + grab('async function upload(') + grab('function homeHTML(') + grab('function conceptsHTML(') + grab('function conceptCard(') + line('const actBtns=') + page.slice(page.indexOf("document.addEventListener('keydown',e=>{\n"), page.indexOf("document.addEventListener('input',")) + names.map(n => 'env.' + n + '=' + n + ';').join('') + '}')(known, env);
const type = t => { ta.value = t; env.store.set('ar-draft:' + env.boxKey(), t) };
const S = env.S, out = {press: []};
(async () => {
  for (const [view, a] of [['plan', 'plan:F1'], ['concepts', 'concept:0'], ['settings', 'setting:ui.x'], ['home', 'new'], ['home', 'newconcept'], ['concepts', 'newconcept']]) {
    env.goView(view); log.focus = 0; env.about(a);
    out.press.push([S.view, S.thread, env.threadTitle(S.thread), log.focus]);
  }
  out.bad = []; for (const a of ['plan:F9', 'concept:7', 'setting:no']) { env.goView('plan'); env.about(a); out.bad.push([S.thread, S.ctx]) }
  // unsent: a draft, an empty Enter, Back by Esc, and press again
  env.goView('plan'); env.about('plan:F1'); out.body = env.feedHTML(S.thread); out.box = env.box('x');
  out.stop = env.shownSession(); await env.send(); await env.feedLoad(); type('make it fir');
  env.on.keydown.forEach(f => f({key: 'Escape', preventDefault() {}, target: {closest: () => null, matches: () => false}}));
  out.back = [S.view, S.thread, S.ctx, log.acts.length, log.fetched.length];
  env.about('plan:F1'); out.draft = ta.value;
  // a reload opens it again, with no focus
  const was = S.ctx; S.ctx = null; S.thread = null; S.view = 'home'; log.focus = 0; env.takePlace(); env.keptCheck();
  out.reload = [S.view, S.thread, JSON.stringify(S.ctx) === JSON.stringify(was), log.focus];
  type('make it first'); await env.send(); out.sent = [[...log.acts], S.thread, S.ctx, S.view, env.boxKey(), Object.keys(kept).filter(k => k.startsWith('ar-draft:'))];
  type('and more'); await env.send(); out.then = log.acts[1];
  env.goView('concepts'); env.about('concept:0'); type('hm'); env.open('c1'); out.left = [S.thread, S.ctx];
  type('hello'); await env.send(); out.c1 = log.acts[2];
  // F183: a new concept, its buttons, its draft and its first message
  env.working_ = env.upNext = () => []; const cs = S.snap.concepts;
  out.buttons = [env.homeHTML(), env.conceptsHTML(), (S.snap.concepts = [], env.conceptsHTML())]; S.snap.concepts = cs;
  env.goView('concepts'); env.about('newconcept'); type('a dark mo'); env.goView('home'); env.about('newconcept'); out.kdraft = ta.value;
  S.ctx = null; S.thread = null; env.takePlace(); env.keptCheck(); out.kreload = [S.view, S.thread, S.ctx];
  const n = log.acts.length; type('a dark mode'); await env.send();
  out.ksent = [log.acts.slice(n), S.ctx, S.view, env.threadTitle(S.thread), Object.keys(kept).filter(k => k.includes('newconcept'))];
  // B219a: a concept card's one Chat: nothing until the first message, which holds its link and the words
  env.controlOf = k => ({key: k, label: k === 'concept_chat' ? 'New chat' : 'Drop'}); env.ctlBusy = () => false;
  out.kcard = env.conceptCard(S.snap.concepts[0], 0); env.controlOf = () => null;
  let k = log.acts.length; const fetched = log.fetched.length;
  env.goView('concepts'); env.about('concept:0'); type('make it wider'); env.goView('home');
  out.kleft = [log.acts.length - k, log.fetched.length - fetched, S.thread, S.ctx];
  env.goView('concepts'); env.about('concept:0'); S.ctx = null; S.thread = null; env.takePlace(); env.keptCheck();
  out.kopen = [log.acts.length - k, ta.value]; delete S.ctx.lead; await env.send();  // a view kept from an older page has no lead
  out.kfirst = [log.acts.slice(k), S.ctx, S.view, env.threadTitle(S.thread)];
  // B182: attachments per box
  const seen = () => ['a.png', 'b.txt'].filter(x => env.box('x').includes(x)), go = n => { env.open(n); return seen() };
  let answer; env.fetch = p => p.startsWith('upload') ? new Promise(r => { answer = j => r({json: async () => j}) }) : Promise.reject(0);
  env.goView('home'); env.open('c1'); let up = env.upload({name: 'a.png', type: ''}); out.atts = {at: seen()};
  out.atts.away = go('c2'); answer({ok: true, path: '/up/a.png'}); await up; out.atts.landed = seen();
  let m = log.acts.length; type('only words'); await env.send(); out.atts.sent2 = log.acts.slice(m).map(a => a[1].text);
  up = env.upload({name: 'b.txt', type: ''}); answer({ok: true, path: '/up/b.txt'}); await up;
  env.goView('home'); out.atts.home = seen(); env.goView('talk'); out.atts.talk = seen();
  env.goView('plan'); env.about('plan:F1'); out.atts.fresh = seen();
  out.atts.back = [go('c2'), go('c1')];
  m = log.acts.length; type('look'); await env.send(); out.atts.sent1 = log.acts.slice(m).map(a => a[1].text);
  out.atts.after = [seen(), go('c2')];
  S.atts = env.attsMove(S.atts, 'c2', 'c7'); out.atts.moved = [seen(), go('c7')];
  // Talk: a message that did not go puts its attachment back in Talk's box, though another is open
  env.talkSend = async () => { env.open('c1'); return false };
  env.goView('talk'); up = env.upload({name: 'a.png', type: ''}); answer({ok: true, path: '/up/a.png'}); await up;
  type('hi'); await env.send(); out.atts.talkBack = [S.thread, seen(), (env.goView('talk'), seen())];
  const unatt = page.slice(page.indexOf("if(x=q('[data-unatt]'))"), page.indexOf('\n', page.indexOf("if(x=q('[data-unatt]'))")));
  new Function('S', 'boxKey', 'q', 'render', 'let x;' + unatt)(S, env.boxKey, () => ({dataset: {unatt: '0'}}), () => {});
  out.atts.removed = [seen(), go('c7')];
  // B212: focus on open, on touch and on desktop: [blurred before the draw, the box focused by the timer, by the tap]
  const draw = env.render, doc = env.document; let at;
  env.talkSend = () => ''; env.typingIn = el => !!el; env.setTimeout = f => { f(); return 0 };
  ta.focus = () => { at.timer++ };
  const left = {blur() { at.blur++; doc.activeElement = null }};
  env.render = () => { draw(); if (doc.activeElement) at.drawnFocused = true };
  const focus = (on, go) => { at = {blur: 0, timer: 0, drawnFocused: false}; log.focus = 0; doc.activeElement = on ? left : null; go(); doc.activeElement = null; return [at.blur, at.timer, log.focus, at.drawnFocused] };
  const home = () => { env.goView('home'); env.about('new'); type('a task') };
  const all = () => ({open: focus(false, () => env.open('c1')), over: focus(true, () => env.open('c2')), about: focus(false, () => env.about('plan:F1')),
    aboutOver: focus(true, () => env.about('plan:F1')), send: (home(), focus(true, () => env.send())), named: focus(true, () => env.open('c8', true))});
  env.TOUCH = () => true; out.touch = all(); env.TOUCH = () => false; out.desk = all();
  console.log(JSON.stringify(out)); process.exit(0);
})();
"""


def test_new_chat_view_f172(tmp: Path) -> None:
    """F172: Chat on a task, a concept or a setting, and Add a task, open an empty new chat view at once with nothing
    sent; the first message starts the session once, with its About text; Back returns, and a draft is kept."""
    page = W.PAGE.read_text(encoding='utf-8')
    check('data-unctx' not in page and 'class="ctx"' not in page, 'the box has no About line')
    check("if(q('[data-home]')){viewGo(()=>{S.thread=null;S.ctx=null;render(true)},S.thread);return}" in page, "Back leaves to the view under it")
    if not shutil.which('node'):
        print('  (no node here: the new chat view test is skipped)')
        return
    (tmp / 'driver.js').write_text(NEW_VIEW_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node presses Chat', r.stderr[-1500:])
    if r.returncode:
        return
    o = json.loads(r.stdout)
    eq(o['press'], [['plan', '+plan:F1', 'F1 Board page', 1], ['concepts', '+concept:K5', 'Lazy layout', 1],
                    ['settings', '+setting:[ui] x', 'A setting', 1], ['home', '+new', 'Add a task', 1],
                    ['home', '+newconcept', 'New concept', 1], ['concepts', '+newconcept', 'New concept', 1]],
       'a press opens the view over the one it was pressed in, titled, its box focused in the tap')
    eq(o['bad'], [[None, None]] * 3, 'a thing that is gone opens nothing')
    check('F1 Board page' in o['body'] and 'starts with your first message' in o['body'], 'it is empty and says so', o['body'])
    check('to a new chat' in o['box'] and 'data-feedkeys' not in o['box'], 'its box has no session keys', o['box'])
    eq(o['stop'], '', 'there is no session to interrupt')
    eq(o['touch'], {'open': [0, 0, 0, False], 'over': [1, 0, 0, False], 'about': [0, 0, 1, False], 'aboutOver': [0, 0, 1, True], 'send': [1, 0, 0, False], 'named': [0, 0, 0, True]},
       'B212: on touch a chat opens without focus and drops what was left before the draw; Chat and + Task focus in the tap; a chat that gets its name keeps it')
    eq(o['desk'], {'open': [0, 1, 0, False], 'over': [0, 1, 0, True], 'about': [0, 1, 1, False], 'aboutOver': [0, 1, 1, True], 'send': [0, 1, 0, True], 'named': [0, 1, 0, True]},
       'B212: a desktop pointer focuses the box on open, and nothing is dropped')
    eq(o['back'], ['plan', None, None, 0, 0], 'left unsent: back on Plan, no action sent and no session asked for')
    eq(o['draft'], 'make it fir', 'pressed again: the draft is there')
    eq(o['reload'], ['plan', '+plan:F1', True, 0], 'a reload keeps it open, without focus')
    ask = 'About F1 (Board page): make it first'
    eq(o['sent'][1:], ['@k1', None, 'plan', '@k1', []], 'the first send: its draft is gone, and Back is still Plan')
    eq(o['sent'][0], [['new_control', {'ask': ask, 'wait': False}]],
       'the first send calls new_control once, with the About text')
    eq(o['then'], ['chat_to', {'text': 'and more', 'to': '@k1'}], 'the next message goes to that chat')
    eq(o['left'], ['c1', None], 'another chat opened over it is that chat')
    eq(o['c1'], ['chat_to', {'text': 'hello', 'to': 'c1'}], 'and a message there goes there')
    home, some, none = o['buttons']
    check('<span class="chips"><button class="chip" data-about="new">' in home
          and 'Add a task</button><button class="chip" data-about="newconcept">' in home and 'New concept</button></span>' in home,
          "F183: Home has New concept beside Add a task, the two on one row when a phone's width wraps the chips", home)
    check('.chips{display:flex;gap:8px;flex-wrap:wrap' in page, "the chips wrap to a phone's width")
    check("concepts:()=>b('data-about=\"newconcept\"','Concept'" in page, "F150: the Concepts view's button is + Concept, at the top right")
    check('No concept waits' in none and 'No concept waits' not in some, 'the empty state stays', none)
    eq(o['kdraft'], 'a dark mo', 'the draft is kept, from Concepts to Home')
    eq(o['kreload'], ['home', '+newconcept', {'kind': 'newconcept', 'label': 'New concept'}], 'a reload keeps the view')
    eq(o['ksent'], [[['new_control', {'ask': 'Concept: a dark mode', 'wait': False}]], None, 'home', 'New concept', []],
       'the first message starts a control session with Concept: …')
    check(o['kcard'].count('<button') == 2 and 'data-about="concept:0">Chat<' in o['kcard'] and 'data-ctl="concept_drop"' in o['kcard']
          and 'New chat' not in o['kcard'] and 'concept_chat' not in o['kcard'], 'B219a: a concept card has one Chat', o['kcard'])
    eq(o['kleft'], [0, 0, None, None], 'B219a: Chat left unsent posts nothing and leaves no session')
    eq(o['kopen'], [0, 'make it wider'], 'pressed again, and after a reload: nothing sent, the draft is there')
    eq(o['kfirst'], [[['new_control', {'ask': "This chat is about concept K5 'Lazy layout': its page https://claude.ai/artifact/k5."
                                               '\n\nmake it wider', 'wait': False}]], None, 'concepts', 'Lazy layout'],
       'the first message starts one session, with what it is about and the words')
    eq(o['atts'], {'at': ['a.png'], 'away': [], 'landed': [], 'sent2': ['only words'], 'home': [], 'talk': [], 'fresh': [],
                   'back': [['b.txt'], ['a.png']], 'sent1': ['look\n\nAttached: /up/a.png'], 'after': [[], ['b.txt']],
                   'moved': [[], ['b.txt']], 'talkBack': ['c1', [], ['a.png']], 'removed': [[], ['b.txt']]},
       'B182: an attachment stays in the box it was added in, goes only with its message, and is there on coming back')


SWIPE_DRIVER = r"""
const fs = require('fs'), page = fs.readFileSync(0, 'utf8');
const logic = page.split('<script id="logic">')[1].split('</script>')[0];
const on = {}, els = {}, S = {}, PD = {}, HB = '', render = () => {}, getComputedStyle = () => ({overflowX: 'auto'});
let DR = null, noClick = false, skip = '';
const dragEnd = () => { DR = null }, closeSheet = () => { S.sheet = '' };
const cls = () => ({add() {}, remove() {}});
const $ = k => els[k] = els[k] || {style: {}, classList: cls(), offsetWidth: 280, scrollTop: 0};
const document = {body: {}, querySelector: () => ({offsetParent: {}}),
  addEventListener(t, f, o) { (on[t] = on[t] || []).push(f) }};
const box = {scrollTop: 500, scrollHeight: 3000, clientHeight: 600, scrollWidth: 400, clientWidth: 400, parentElement: document.body};
const el = {scrollHeight: 20, clientHeight: 20, parentElement: box, closest: s => skip && s.includes(skip) ? {} : null};
let now = 0;
const fire = (t, x, y, o = {}) => { let stopped = false;
  on[t].forEach(f => f({target: el, touches: Array(o.n || (t === 'touchstart' || t === 'touchmove' ? 1 : 0)).fill().map((_, i) => ({identifier: i, clientX: x, clientY: y})), timeStamp: now += 100,
    cancelable: o.cancelable !== false, preventDefault() { if (o.cancelable !== false) stopped = true }}));
  return stopped };
eval(logic + page.slice(page.indexOf('/* F124: a swipe right anywhere'), page.indexOf("addEventListener('pagehide'", page.indexOf('/* F124: a swipe right anywhere'))) + `
// a touch from (100, 300) through these [dx, dy, options]: the moves it kept from scrolling, and where the drawer ends
function touch(open, moves, end = 'touchend') {
  S.drawer = open; S.sheet = ''; DR = null; skip = ''; box.scrollTop = 500; box.scrollHeight = 3000; fire('touchstart', 100, 300);
  const kept = moves.map(([dx, dy, o = {}]) => { if (o.top) box.scrollTop = o.top; if (o.h) box.scrollHeight = o.h;
    if (o.hold) DR = {ready: true, hold: 1}; if (o.start) { fire('touchstart', 9, 9, {n: 2}); return 'start' }
    if (o.lift) { fire('touchend', 9, 9, {n: 1}); return 'lift' }
    return fire('touchmove', 100 + dx, 300 + dy, o) });
  const at = $('side').style.transform; fire(end, 0, 0); return [kept.map(k => typeof k === 'string' ? k : +k).join(), !!S.drawer, at, !!noClick && !(noClick = false)];
}
const out = {
  scrollFirst: touch(false, [[2, -20], [60, -30], [220, -30]]),
  slowScroll: touch(false, [[1, -4], [3, -5, {top: 505}], [60, -6], [220, -6]]),
  begun: touch(false, [[20, 2, {cancelable: false}], [220, 2]]),
  grew: touch(false, [[3, 0, {top: 900, h: 3400}], [40, 0], [220, 0]]),
  sideFirst: touch(false, [[12, 2], [60, 90], [220, 300]]),
  diagonal: touch(false, [[20, 14], [220, 150]]),
  shallow: touch(false, [[20, 8], [220, 150]]),
  close: touch(true, [[-12, 3], [-60, -120], [-220, -200]]),
  closeScroll: touch(true, [[-2, -15], [-220, -20]]),
  wrongWay: touch(false, [[-20, 0], [220, 0]]),
  cancel: touch(false, [[20, 0], [220, 0]], 'touchcancel'),
  second: touch(false, [[20, 0], [0, 0, {start: true}], [220, 40, {n: 2}], [0, 0, {lift: true}], [220, 90]]),
  grewThenScrolled: touch(false, [[3, 0, {top: 900, h: 3400}], [4, -5, {top: 905}], [220, -6]]),
  held: touch(false, [[2, 0], [20, 0, {hold: true}], [220, 0]]),
  tap: touch(false, [[4, 3]]),
};
const from = k => { skip = k; S.drawer = false; S.sheet = ''; DR = null; fire('touchstart', 100, 300);
  const r = fire('touchmove', 200, 300); fire('touchend'); return r };
out.box = from('textarea'); out.mic = from('.mic.hold');
box.scrollWidth = 900; out.sideways = from('#body'); box.scrollWidth = 400;
skip = '#sheet'; S.sheet = 'run'; fire('touchstart', 100, 300); out.sheet = [fire('touchmove', 100, 420), $('sheet').style.transform]; fire('touchend'); out.sheet.push(S.sheet);
console.log(JSON.stringify(out));process.exit(0)`);
"""


def test_swipe_or_scroll_b167(tmp: Path) -> None:
    """B167: a touch is a scroll or a drawer swipe until the finger lifts, never both."""
    page = W.page_html().decode()
    css = page.split('<style>', 1)[1].split('</style>', 1)[0]
    for sel in ('.side{', '.scrim{'):
        check('touch-action:pan-y pinch-zoom' in css.split('\n' + sel, 1)[1].split('}', 1)[0], f'{sel}}} pans up and down only')
    if not shutil.which('node'):
        print('  (no node here: the swipe script test is skipped)')
        return
    p = subprocess.run(['node', '-e', SWIPE_DRIVER], input=page, capture_output=True, text=True, encoding='utf-8', timeout=30)
    check(p.returncode == 0, 'the swipe script runs', p.stderr)
    got = json.loads(p.stdout or '{}')
    for k, what in (('scrollFirst', 'a scroll that bends sideways'), ('slowScroll', 'the scroller moved first'),
                    ('begun', 'a scroll has begun: the move is not cancelable'), ('diagonal', 'a diagonal move'),
                    ('grewThenScrolled', 'a scroll after a new message'), ('wrongWay', 'a swipe left with the drawer closed'), ('held', 'a held row')):
        kept, opened, *_ = got.get(k)
        check('1' not in kept and not opened, f'{what}: no drawer, and the scroll is left alone', got.get(k))
    eq(got['grew'][:2], ['0,1,1', True], "a chat's new message is not the finger's scroll")
    eq(got['sideFirst'][:2], ['1,1,1', True], 'sideways, then vertical: every move is kept from scrolling')
    eq(got['shallow'][:2], ['1,1', True], 'a shallow diagonal moves the drawer only')
    eq(got['close'][:2], ['1,1,1', False], 'the same for the swipe that closes')
    eq(got['closeScroll'][:2], ['0,0', True], "a scroll of the drawer's list does not close it")
    eq(got['cancel'][:2], ['1,1', False], 'a cancelled swipe leaves the drawer as it was')
    eq(got['second'][:2], ['1,start,1,lift,1', True], 'a second finger, down or up, does not end the lock')
    eq(got['tap'][0::3], ['0', False], 'a tap stays a tap')
    eq([got['box'], got['mic'], got['sideways']], [False] * 3, 'text boxes, the held mic and sideways scrollers are left alone')
    eq(got['sheet'], [False, 'translateY(120px)', ''], "the sheet's swipe down")


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
const document = {hidden: false, title: ''}, talkName = () => '';
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


PLUS_DRIVER = r"""
const page = require('fs').readFileSync(0, 'utf8'), on = {};
const grab = s => { const i = page.indexOf(s); return page.slice(i, page.indexOf('\n}\n', i) + 2) + '\n' };
const line = s => { const i = page.indexOf(s); return page.slice(i, page.indexOf('\n', i)) + '\n' };
let now = 0, timers = [], busy = false, opened = [], uploads = 0, btn = {disabled: false};
const setTimeout = (f, ms) => { timers.push({f, at: now + ms, id: timers.length + 1}); return timers.length };
const clearTimeout = id => { timers.forEach(t => { if (t.id === id) t.at = Infinity }) };
const go = ms => { now += ms; timers.forEach(t => { if (t.at <= now) { t.at = Infinity; t.f() } }) };
const S = {view: 'home', thread: null, snap: {}}, I = {plus: ''}, HOME_PAGE = false;
const $ = () => ({addEventListener: (t, f) => { on[t] = f }}), upload = () => { uploads++ }, about = a => { opened.push(a) };
const document = {querySelector: s => s === '.plus[data-about="new"]' ? btn : null};
const render = () => { if (!busy) { btn.disabled = plusBtn().includes(' disabled') } };
const press = (what, plus) => { const el = {dataset: {about: what}, matches: s => plus && s === `.plus[data-about="${what}"]`}; opened = []; CLICK(el); return opened };
eval(line('let PLUS_HOLD=') .replace('let', 'var') + grab('function holdPlus(') + line('function plusHeld(') + grab('function plusBtn(')
  + line("$('file').addEventListener('cancel'") + line("$('file').addEventListener('change'")
  + 'var CLICK=el=>{let x;const q=()=>el;' + line("  if(x=q('[data-about]'))") + '}');
const pick = t => on[t]({target: {files: [1, 2], value: 'x'}});
const see = () => { render(); return [btn.disabled, press('new', true).length] };
const o = {before: see()};
for (const t of ['change', 'cancel']) { S.view = t === 'change' ? 'home' : 'plan'; pick(t); const a = [see()]; go(990); a.push(see()); o[t + 'Chip'] = [press('new', false).length, press('newconcept', true).length, press('plan:F1', false).length]; go(20); a.push([btn.disabled], see()); o[t] = a }
o.uploads = uploads;
pick('change'); go(600); pick('change'); go(600); o.again = [see()]; go(500); o.again.push(see());
busy = true; btn.disabled = false; pick('change'); o.busy = [press('new', true).length]; btn.disabled = true; go(1010); o.busy.push(btn.disabled, press('new', true).length);
busy = false; pick('change'); S.view = 'concepts'; o.other = plusBtn().includes(' disabled');
console.log(JSON.stringify(o));
"""


def test_plus_hold_b213(tmp: Path) -> None:
    """B213: for a second after the file picker closes, + Task (Home, Plan) is disabled and opens nothing, also across
    a redraw; then it works again by itself. Other buttons and the attachments are not held."""
    if not shutil.which('node'):
        print('  (no node here: the + Task hold test is skipped)')
        return
    (tmp / 'driver.js').write_text(PLUS_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js')], input=W.PAGE.read_text(encoding='utf-8'),
                       capture_output=True, text=True, encoding='utf-8', timeout=60)
    check(r.returncode == 0, 'node presses + Task', r.stderr[-1500:])
    if r.returncode:
        return
    o = json.loads(r.stdout)
    eq(o['before'], [False, 1], 'no picker: + Task opens the new task chat')
    for t in ('change', 'cancel'):
        eq(o[t], [[True, 0], [True, 0], [False], [False, 1]], f'{t}: held for a second, redraws too, then works by itself')
        eq(o[t + 'Chip'], [1, 1, 1], f'{t}: no other button is held')
    eq(o['uploads'], 2, 'the picked files are added at once')
    eq(o['again'], [[True, 0], [False, 1]], 'a second pick holds it for a second from then')
    eq(o['busy'], [0, False, 1], 'while draws wait (a finger down, a selection) it is held and let go all the same')
    eq(o['other'], False, 'another view\'s + is not disabled')


PLUS_CHAT_DRIVER = r"""
const page = require('fs').readFileSync(0, 'utf8');
const grab = s => { const i = page.indexOf(s); return page.slice(i, page.indexOf('\n}\n', i) + 2) + '\n' };
const line = s => { const i = page.indexOf(s); return page.slice(i, page.indexOf('\n', i)) + '\n' };
const at = (thread, view, HOME_PAGE, all) => new Function('S', 'I', 'HOME_PAGE', 'atAll', 'PLUS_HOLD', 'controlOf',
  line('const isNew=') + grab('function plusBtn(') + 'return plusBtn()')({thread, view, snap: {up: true}, tools: {secure: true}}, {plus: ''}, HOME_PAGE, () => all, 0, () => true);
const o = {views: {}};
for (const t of ['c1', 'F12', 's1', '+new', '+plan:F1', '@k1']) o[t] = at(t, 'plan', false, false);
for (const v of ['home', 'plan', 'concepts', 'status', 'tools', 'talk', 'settings', 'projects']) o.views[v] = at(null, v, false, false);
o.homeAll = at(null, 'projects', true, true); o.homeOne = at(null, 'home', true, false);
console.log(JSON.stringify(o));
"""


def test_plus_chat_b762(tmp: Path) -> None:
    """B762: + Chat is at the top right in an open chat and in a slot's session; not in a new or starting chat, and the
    other views keep their own +."""
    if not shutil.which('node'):
        print('  (no node here: the + Chat test is skipped)')
        return
    (tmp / 'driver.js').write_text(PLUS_CHAT_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js')], input=W.PAGE.read_text(encoding='utf-8'),
                       capture_output=True, text=True, encoding='utf-8', timeout=60)
    check(r.returncode == 0, 'node draws the + of each place', r.stderr[-1500:])
    if r.returncode:
        return
    o = json.loads(r.stdout)
    chat = '<button class="btn plus" data-new title="New chat">Chat</button>'
    for t in ('c1', 'F12', 's1'):
        eq(o[t], chat, f'{t}: + Chat')
    for t in ('+new', '+plan:F1', '@k1'):
        eq(o[t], '', f'{t}: none in a new or starting chat')
    words = {v: re.sub('<[^>]*>', '', h) for v, h in o['views'].items()}
    eq(words, {'home': 'Task', 'plan': 'Task', 'concepts': 'Concept', 'status': 'Slot', 'tools': 'Device',
               'talk': 'New talk', 'settings': '', 'projects': 'Project'}, 'the other views keep their own +')
    check(not any('data-new ' in h for h in o['views'].values()), 'and none of them starts a chat')
    eq([re.sub('<[^>]*>', '', o['homeAll']), o['homeOne']], ['Project', ''], "Runner Home's own page is unchanged")


def test_first_lines_b766(tmp: Path) -> None:
    """B766: every line of a session is reachable: with nothing older to scroll to, an upward scroll moves the frame till
    its first line is clear of the top bar, a gap over the working lines or not; a long chat is as it was."""
    if not shutil.which('node'):
        print('  (no node here: the first lines test is skipped)')
        return
    spot = {'main': 800, 'bar': 60, 'dock': 180, 'row': 56, 'high': 900, 'pad': 12, 'cell': 20, 'foot': {'top': 38}, 'short': 0, 'off': 0}
    new = ['❯ my message', '', '● Running a tool', '  ⎿ $ ls'] + [''] * 20 + ['● Churning… (7s)', '  Session renamed to: x', '']
    full = ['❯ my message'] + ['words'] * 20 + ['', '● Churning… (7s)', '']
    code = ['❯ my message', '', '', '', '', ''] + ['words'] * 10 + ['']
    state = {'off': 0, 'far': 212, 'jump': False, 'slim': False}
    got = logic_js([['feedGap', new, len(new)], ['feedGap', full, len(full)], ['feedGap', code, len(code)],
                    ['feedGap', [''] * 20 + ['● Churning… (7s)'], 21], ['feedGap', ['hi'] + [''] * 20, 21],
                    ['feedSpot', {**spot, 'top': True}], ['feedSpot', {**spot, 'top': True, 'off': 9999}], ['feedSpot', spot],
                    ['feedSpot', {**spot, 'top': True, 'short': 5}], ['feedSpot', {**spot, 'top': True, 'short': 34, 'off': 9999}],
                    ['feedSpot', {**spot, 'top': True, 'hold': 60, 'dock': 260}],
                    ['feedShare', -10, {**state, 'top': True}], ['feedShare', -10, {**state, 'top': True, 'off': 208}],
                    ['feedShare', -10, {**state, 'top': True, 'off': 212}], ['feedShare', 10, {**state, 'top': True, 'off': 212}],
                    ['feedShare', -10, state]])
    eq(got[:5], [True, False, False, False, False], 'a gap over the working lines, and nothing else, is seen')
    eq((got[5]['t'], got[5]['far']), (-152, 212), 'at rest the working lines stand on the box')
    eq(got[6]['t'], 60, 'pulled down, the first line is clear of the bar')
    eq(got[7]['far'], 124, 'a long chat goes as far as it did')
    eq((got[8]['t'], got[8]['far']), (508, 0), 'a screen whose words fit has nothing to pull')
    eq((got[9]['t'], got[10]['t']), (60, 60), 'a short one too long for its room is reached; pulled, its place is kept')
    eq(got[11:], [-10, -4, 0, 10, 0], "the frame's share, to its end, and back; with older lines the session's first")


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_upload), in_tmp(test_new_chat), in_tmp(test_esc_ctrl_c), in_tmp(test_delete_chats_f118), in_tmp(test_slash_menu_b119), in_tmp(test_chat_keys_b200), in_tmp(test_composer_keys_b120), in_tmp(test_enter_b181), in_tmp(test_interrupt_c1_b141), in_tmp(test_chat_order_f133), in_tmp(test_chats_newest_f201), in_tmp(test_answer_button_b138), in_tmp(test_pick_f138), in_tmp(test_outbox_f137), in_tmp(test_sent_b154), in_tmp(test_once_b161), in_tmp(test_card_chat_b139), in_tmp(test_new_chat_view_f172), in_tmp(test_swipe_or_scroll_b167), in_tmp(test_row_buttons_f187), in_tmp(test_chats_f128), in_tmp(test_quiet_stays_b193), in_tmp(test_needs_drop_chat_f110), in_tmp(test_drop_confirm_id_b191), in_tmp(test_plus_hold_b213), in_tmp(test_plus_chat_b762), in_tmp(test_first_lines_b766)]))
