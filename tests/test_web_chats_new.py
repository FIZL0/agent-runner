"""The run page, chats area, new chat and + Chat: the first lines, the hold, the order (C46: split from test_web_chats.py), tests unchanged.

    python3 tests/test_web_chats_new.py
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
  env.working_ = () => [];
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
    check('newconcept' not in home, 'F426a: New concept is the Concepts view\'s + button, not on Home', home)
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


PLUS_DRIVER = r"""
const page = require('fs').readFileSync(0, 'utf8').replace(/\r\n/g, '\n'), on = {};
const grab = s => { const i = page.indexOf(s); return page.slice(i, page.indexOf('\n}\n', i) + 2) + '\n' };
const line = s => { const i = page.indexOf(s); return page.slice(i, page.indexOf('\n', i)) + '\n' };
let now = 0, timers = [], busy = false, opened = [], uploads = 0, btn = {disabled: false};
const setTimeout = (f, ms) => { timers.push({f, at: now + ms, id: timers.length + 1}); return timers.length };
const clearTimeout = id => { timers.forEach(t => { if (t.id === id) t.at = Infinity }) };
const go = ms => { now += ms; timers.forEach(t => { if (t.at <= now) { t.at = Infinity; t.f() } }) };
const S = {view: 'home', thread: null, snap: {}}, I = {plus: ''}, HOME_PAGE = false;
const $ = () => ({addEventListener: (t, f) => { on[t] = f }}), upload = () => { uploads++ }, about = a => { opened.push(a) }, newChat = n => { opened.push(n) };
const document = {querySelector: s => s.split(',').includes(S.thread ? '.plus[data-new]' : '.plus[data-about="new"]') ? btn : null};
const render = () => { if (!busy) { btn.disabled = plusBtn().includes(' disabled') } };
const press = (what, plus) => { const el = {sel: '[data-about]', dataset: {about: what}, matches: s => plus && s.split(',').includes(`.plus[data-about="${what}"]`)}; opened = []; CLICK(el); return opened };
eval(line('const PLUS_HELD=').replace('const', 'var') + line('const isNew=').replace('const', 'var') + line('let PLUS_HOLD=').replace('let', 'var') + grab('function holdPlus(') + line('function plusHeld(') + grab('function plusBtn(')
  + line("$('file').addEventListener('cancel'") + line("$('file').addEventListener('change'")
  + 'var CLICK=el=>{let x;const q=s=>el.sel===s?el:null;' + line("  if(x=q('[data-new]'))") + line("  if(x=q('[data-about]'))") + '}');
const chat = plus => { const el = {sel: '[data-new]', matches: s => plus && s.split(',').includes('.plus[data-new]')}; opened = []; CLICK(el); return opened.length };
const pick = t => on[t]({target: {files: [1, 2], value: 'x'}});
const see = () => { render(); return [btn.disabled, press('new', true).length] };
const o = {before: see()};
for (const t of ['change', 'cancel']) { S.view = t === 'change' ? 'home' : 'plan'; pick(t); const a = [see()]; go(990); a.push(see()); o[t + 'Chip'] = [press('new', false).length, press('newconcept', true).length, press('plan:F1', false).length]; go(20); a.push([btn.disabled], see()); o[t] = a }
o.uploads = uploads;
pick('change'); go(600); pick('change'); go(600); o.again = [see()]; go(500); o.again.push(see());
busy = true; btn.disabled = false; pick('change'); o.busy = [press('new', true).length]; btn.disabled = true; go(1010); o.busy.push(btn.disabled, press('new', true).length);
busy = false; pick('change'); S.view = 'concepts'; o.other = plusBtn().includes(' disabled'); go(1010);
const seeChat = () => { render(); return [btn.disabled, chat(true)] };
o.chats = {};
for (const n of ['c1', 's1']) for (const t of ['change', 'cancel']) {
  S.thread = n; const a = [seeChat()], was = uploads; pick(t); a.push(seeChat()); go(990); a.push(seeChat(), chat(false)); go(20); a.push([btn.disabled], seeChat(), uploads - was);
  busy = true; btn.disabled = false; pick(t); a.push(chat(true)); btn.disabled = true; go(1010); a.push([btn.disabled], chat(true)); busy = false;
  o.chats[n + ' ' + t] = a;
}
console.log(JSON.stringify(o));
"""


def test_plus_hold_b213(tmp: Path) -> None:
    """B213, B768: for a second after the file picker closes, + Task (Home, Plan) and + Chat (a chat, a
    slot) are disabled and open nothing, also across a redraw; then they work again by themselves. Other buttons and the attachments are not held."""
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
    eq(sorted(o['chats']), ['c1 cancel', 'c1 change', 's1 cancel', 's1 change'], 'B768: a chat and a slot, change and cancel')
    for k, v in o['chats'].items():
        eq(v, [[False, 1], [True, 0], [True, 0], 1, [False], [False, 1], 2 if 'change' in k else 0, 0, [False], 1],
           f'B768: {k}: + Chat is held for a second, redraws and waiting draws too, then works by itself; the sidebar\'s + Chat and the files are not held')


PLUS_CHAT_DRIVER = r"""
const page = require('fs').readFileSync(0, 'utf8').replace(/\r\n/g, '\n');
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
    eq(words, {'home': 'Task', 'plan': 'Task', 'concepts': 'Concept', 'status': '', 'tools': 'Tool',
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
    eq(got[:5], [4, 0, 0, 0, 0], 'a gap over the working lines, and nothing else, is seen')
    eq((got[5]['t'], got[5]['far']), (-152, 212), 'at rest the working lines stand on the box')
    eq(got[6]['t'], 60, 'pulled down, the first line is clear of the bar')
    eq(got[7]['far'], 124, 'a long chat goes as far as it did')
    eq((got[8]['t'], got[8]['far']), (60, 0), 'a screen whose words fit has nothing to pull')
    eq((got[9]['t'], got[10]['t']), (60, 60), 'a short one too long for its room is reached; pulled, its place is kept')
    eq(got[11:], [-10, -4, 0, 10, 0], "the frame's share, to its end, and back; with older lines the session's first")


REST_DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const logic = page.split('<script id="logic">')[1].split('</script>')[0].replace(/if\(typeof module[^\n]*/, '');
const slice = (a, b) => page.slice(page.indexOf(a), page.indexOf(b, page.indexOf(a)));
const ROWS = 46, TOP = 40, RULE = '─'.repeat(40);
let lines = [], moves = [], up = false;
const term = {rows: ROWS, modes: {mouseTrackingMode: 'any'}, buffer: {active: {baseY: 0, viewportY: 0, getLine: y => ({translateToString: () => lines[y] || '', getCell: () => null})}}};
const feedTerm = () => term, feedTop = () => 0, feedKeep = () => {}, liveLoad = () => {}, render = () => {}, pastSee = () => {}, feedSlim = () => {}, pastUp = () => up, feedWhole = on => { FD.whole = on };
const KEPT = new Map(), FEED_KEEP = 2000, FOOT_WAIT = 400, TEXT_WAIT = 1200, setTimeout = f => 1, clearTimeout = () => {};
const FD = {n: 'c1', shown: true, drawn: true, foot: undefined, whole: false, wait: 0, off: 0, jump: false, top: false, gap: 0, short: 0, still: '', run: 0, slim: false, keptAt: Infinity, fresh: true};
const feedPlace = () => { FD.at = feedSpot({main: 800, bar: 60, dock: 180, row: 56, high: 900, pad: 12, cell: 20, foot: FD.foot, short: FD.short, whole: FD.whole, off: FD.off, top: FD.top}) };
const feedGlide = () => { moves.push(1); feedPlace() };
const foot = ['❯ ', RULE, '  ⏵⏵ bypass permissions on', '', ''];
const screen = (words, low = []) => [...words, ...Array(TOP - words.length - low.length).fill(''), ...low, RULE, ...foot];
const words = n => Array.from({length: n}, (x, i) => i ? 'words ' + i : '❯ my message'), spin = ['● Churning… (7s)', ''];
eval(logic + slice('function feedLines(', '/* B766: the session has') + slice('const feedOldest=', 'function feedStill()') + slice('const STILL_ROWS', '// the terminal') + `
const see = l => { lines = l; moves = []; feedSee(); FD.fresh = false; return [FD.at.t, FD.gap, FD.at.off, FD.at.far, moves.length] };
const out = {};
out.first = see(screen(words(5)));
out.work = see(screen(words(5), spin)); out.grow = see(screen(words(20), spin)); out.done = see(screen(words(20)));
out.over = see(screen(words(30), spin)); out.overDone = see(screen(words(30)));
out.closed = see(screen(words(37), spin)); out.full = see(screen(words(39), ['x']));
out.todos = see(screen(words(5), ['✻ Running all the tests… (12s)', ...Array.from({length: 12}, (x, i) => '  ☐ step ' + i), '']));
out.named = see(screen(words(33), ['✻ Running tests… (12s)', '']));
out.noted = see(screen(words(5), ['  Session renamed to: x', '']));
out.code = see([...words(30), ...Array(5).fill(''), 'x', 'y', 'z', ...Array(1).fill(''), '', RULE, ...foot]);
out.rate = see(screen(words(5), ['● How is Claude doing?', '  1: Bad  2: Fine', '']));
term.modes.mouseTrackingMode = 'none'; term.buffer.active.viewportY = term.buffer.active.baseY = 3; out.older = see([...Array(3).fill(''), ...screen(words(5), spin)]);
term.modes.mouseTrackingMode = 'any'; term.buffer.active.viewportY = term.buffer.active.baseY = 0;
up = true; see(screen(words(5), spin)); out.reading = [FD.gap, moves.length]; up = false;
see(screen(words(5), spin)); lines = ['Do you want to proceed?', '❯ 1. Yes', '  2. No', '', 'Esc to cancel']; feedSee(); out.menu = [FD.foot, FD.gap, FD.short];
console.log(JSON.stringify(out));`);
"""


def test_rest_b786(tmp: Path) -> None:
    """B786: a session that is not full rests with its first line under the top bar, working or not, while its words fit."""
    if not shutil.which('node'):
        print('  (no node here: the rest test is skipped)')
        return
    (tmp / 'rest.js').write_text(REST_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'rest.js'), str(W.PAGE)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs feedSee()', r.stderr[-900:])
    o = json.loads(r.stdout or '{}')
    eq(o.get('first'), [60, 0, 0, 0, 0], 'a new chat starts under the top bar')
    eq((o.get('work'), o.get('grow'), o.get('done')), ([60, 5, 0, 0, 0], [60, 20, 0, 0, 1], [60, 0, 0, 0, 0]), 'working, more words, at rest again: it stays there, and nothing is to pull')
    eq((o.get('over'), o.get('overDone')), ([8, 30, 0, 52, 1], [8, 0, 0, 52, 0]), 'words that no longer fit end on the box, the working line there or not')
    eq((o.get('closed'), o.get('full')[0]), ([-192, 0, 0, 124, 1], -192), 'the gap closes: all of it ends on the box, by a glide')
    eq((o.get('todos')[:2], o.get('named')[1]), ([60, 5], 33), 'a list under the working line, a name of several words')
    eq(o.get('noted')[:2], [60, 5], 'a notice alone under the gap')
    eq((o.get('code')[1], o.get('rate')[1], o.get('older')[1]), (0, 0, 0), 'blank lines in an answer, a survey to answer, older lines: as a full one')
    eq(o.get('reading')[1], 0, 'while the history is read nothing glides')
    eq(o.get('menu'), [None, 0, 0], 'a menu or a question: no such rest')


def test_chat_order_f133(tmp: Path) -> None:
    """F133, F201: the pinned chats, set through /act chat_order, are kept by the run (a file in the notes dir) in
    their order: in the snapshot after a reload, and a new server's; a deleted chat drops out. Each chat row has a pin
    button, only a pinned one drags, by pointer events, and chatMove places it among the pins."""
    fake_repo(tmp)
    page = W.page_html().decode()
    check('data-pin=' in page and "act('chat_order'" in page and "'pointerdown'" in page and "closest('.crow[data-crow]')" in page,
          'the page: a pin button per chat, chat rows dragged by pointer events, the chat_order action')
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
    eq(o['named'], 'c4 c1 @b @a c3 c10 c5 c6 q c2 q', 'one with its name, not in the snapshot yet, keeps its place (F196d: and its key)')
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


NAME_DRIVER = r"""
const page = require('fs').readFileSync(0, 'utf8');
const line = a => { const i = page.indexOf(a); return page.slice(i, page.indexOf('\n', i)) };
const S = {ob: [], came: []}, sess = {};
const isNew = n => n === '+', isAgent = n => false, sessionOf = n => sess[n], chatTitle = s => s.title;
eval(line('const threadTitle=') + page.slice(page.indexOf('function bornSay('), page.indexOf('\n}\n', page.indexOf('function bornSay(')) + 3) + `
const seen = [];
S.ob = [{newchat: true, cid: 'k1', say: 'fix the login page', state: 'sending'}];
seen.push(threadTitle('@k1'));
S.ob = []; S.came = [{name: 'c7', was: '@k1', say: 'fix the login page', state: 'sending'}];
seen.push(threadTitle('@k1'), threadTitle('c7'));
sess.c7 = {name: 'c7', title: 'fix the login page'}; S.came = [];
seen.push(threadTitle('c7'));
sess.c7 = {name: 'c7', title: 'Login page fix'};
seen.push(threadTitle('c7'));
console.log(JSON.stringify(seen));`);
"""


def test_born_name_f196e(tmp: Path) -> None:
    """F196e: a new chat's shown name goes from its first message's words straight to its own title, never the bare cN
    or 'New chat' between; the server names a new chat that has no name yet with those words."""
    fake_repo(tmp)
    if shutil.which('node'):
        r = subprocess.run(['node', '-e', NAME_DRIVER], input=W.page_html().decode(), capture_output=True, text=True, timeout=60)
        check(r.returncode == 0, 'node runs threadTitle()', r.stderr[-900:])
        eq(json.loads(r.stdout or '[]'), ['fix the login page'] * 4 + ['Login page fix'],
           'the words while it starts, under both its names and in its first snapshot row (name_new), then its title')
    else:
        print('  (no node here: the shown name test is skipped)')
    from agent_runner import control as K
    K.control_give(7, K.control_base_name(7))
    U.name_new({'ok': True, 'out': 'control 7 is up'}, 'fix the login page')
    eq(U.given_title(K.control_given(7), 7), 'fix the login page', 'a new chat with no name gets its first words')
    K.control_give(7, K.control_summary_name(7, 'Login page fix'))
    U.name_new({'ok': True, 'out': 'control 7 is up'}, 'fix the login page')
    eq(U.given_title(K.control_given(7), 7), 'Login page fix', 'never over a name it has')



NEED_CONCEPT_DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const line = s => { const i = page.indexOf(s); if (i < 0) throw new Error('missing ' + s); return page.slice(i, page.indexOf('\n', i)) + '\n' };
let did = [];
const S = {sheet: null, snap: {concepts: [{concept: 'K9', title: 'Other'}, {concept: 'K14', title: 'Lazy layout'}], needs: [{id: 'K14'}, {id: 'B5'}]}};
const about = a => did.push(['about', a]), closeSheet = () => { did.push(['close']); S.sheet = null },
  newChat = (n, a) => did.push(['newChat', n, a.tid]), needChatAsk = () => 'ask', outbox = () => did.push(['act']);
eval(line('function needConcept(') + 'var CLICK=(c,tid)=>{const rq={name:"need_chat",args:{tid}};' + line('    if(c.chat&&c.where===') + line("    if(c.chat){const n=") + line('      newChat(rq.name') + '}');
const need = {chat: true, where: 'need'}, o = {};
did = []; CLICK(need, 'K14'); o.card = did;
did = []; S.sheet = 'need'; CLICK(need, 'K14'); o.popup = did;
did = []; CLICK(need, 'B5'); o.other = did;
console.log(JSON.stringify(o));
"""


def test_need_concept_chat_b219b(tmp: Path) -> None:
    """B219b: Chat on a Needs you concept (card or popup) opens the concept's new chat view and sends nothing; other
    Needs you items keep their Chat."""
    if not shutil.which('node'):
        print('  (no node here: the Needs you concept Chat test is skipped)')
        return
    (tmp / 'driver.js').write_text(NEED_CONCEPT_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node presses Chat', r.stderr[-1500:])
    if r.returncode:
        return
    o = json.loads(r.stdout)
    eq(o['card'], [['about', 'concept:1']], 'the card opens the concept view, nothing posted')
    eq(o['popup'], [['close'], ['about', 'concept:1']], 'the popup closes and opens it, nothing posted')
    eq(o['other'], [['newChat', 'need_chat', 'B5']], 'a non-concept item keeps its Chat')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_born_name_f196e), in_tmp(test_new_chat), in_tmp(test_new_chat_view_f172), in_tmp(test_plus_hold_b213), in_tmp(test_plus_chat_b762), in_tmp(test_first_lines_b766), in_tmp(test_rest_b786), in_tmp(test_chat_order_f133), in_tmp(test_chats_newest_f201), in_tmp(test_need_concept_chat_b219b)]))
