"""The run page, chats area, the message box: keys, slash menu, enter, interrupt, swipe (C46: split from test_web_chats.py), tests unchanged.

    python3 tests/test_web_chats_box.py
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


SLASH_DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n'), CMDS = JSON.parse(process.argv[3]);
const slice = (a, b) => { const i = page.indexOf(a); return page.slice(i, page.indexOf(b, i) + b.length); };
const logic = page.split('<script id="logic">')[1].split('</script>')[0];
const handlers = {}, store = {v: {}, get(k) { return this.v[k] || '' }, set(k, v) { this.v[k] = v }};
const DRAFT_KEY = k => k, boxKey = () => 'c1', grow = () => {}, esc = s => String(s), tq = p => p;
const S = {thread: 'c1', sel: [], drawer: false};
const TOUCH = () => false, busy = () => false, act = () => {}, selectedText = () => false, render = () => {}, modelOf = () => '', talkName = () => '';
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
    check('const BOX_KEYS=[' in page and page.count('keysLine(') >= 2, 'the keys are listed once, in BOX_KEYS, and '
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
eval(logic + 'const modelOf = () => "", talkName = () => "";' + slice('const TOUCH=', ';\n') + slice('const enterHint=', ';') + slice('function box(ph,foot){', '\n}\n')
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


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_esc_ctrl_c), in_tmp(test_slash_menu_b119), in_tmp(test_chat_keys_b200), in_tmp(test_composer_keys_b120), in_tmp(test_enter_b181), in_tmp(test_interrupt_c1_b141), in_tmp(test_swipe_or_scroll_b167)]))
