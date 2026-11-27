"""The run page, live area (agent_runner/page/*-live.*): split from test_web.py (C41b), tests unchanged.

    python3 tests/test_web_live.py
"""
from __future__ import annotations

import datetime as dt
import gzip
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


def test_feed_pane_concept(tmp: Path) -> None:
    """F74: /feed/NAME gives the session's feed, /concept/ID a concept's local page
    copy (sandboxed), and /act runs the new actions (interrupt, quick_ask)."""
    fake_repo(tmp)
    token = W.web_token()
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {'queue': []})
    base = f'http://127.0.0.1:{srv.server_address[1]}'
    entries = [{'kind': 'say', 'text': 'hi'}]
    try:
        with mock.patch.object(U, 'feed', side_effect=lambda n: {'ok': True, 'name': n, 'entries': entries}):
            r = json.loads(get(f'{base}/feed/c6?t={token}')[1])
        eq((r['name'], r['entries']), ('c6', entries), "/feed/c6 is c6's feed")
        eq(get(f'{base}/concept/K5?t={token}')[0], 404, 'no copy: 404')
        S.C.notes('concepts', 'K5.html').write_text('<h1>Option A</h1>', encoding='utf-8')
        with urllib.request.urlopen(f'{base}/concept/K5?t={token}', timeout=10) as resp:
            body, csp = resp.read(), resp.headers.get('Content-Security-Policy', '')
        eq((body, csp), (b'<h1>Option A</h1>', 'sandbox allow-scripts'), 'the copy, sandboxed')
        eq(get(f'{base}/concept/K5')[0], 403, 'and only with the token')
        ran = []

        def no_send(t):
            raise AssertionError(f'B139: a quick ask reached c1: {t!r}')
        with mock.patch.object(U, 'SEND', [no_send]), \
                mock.patch.object(U, 'RUN', [lambda argv: (ran.append(argv), (0, 'control 7 is starting'))[1]]):
            code, out = post(f'{base}/act?t={token}', {'name': 'quick_ask', 'args': {'key': 'needs', 'wait': False}})
        eq((out['ok'], out['name'], ran), (True, 'c7', [['control', '--new', '--no-wait', '--ask', 'what needs me?', '--no-feed']]),
           'B139: a quick ask through /act starts a new control session with it, named for the page to open')
        typed = []
        from agent_runner import slots as SLT
        with mock.patch.object(U, 'hidden_inbox', return_value=Path('/x/control6.in')), \
                mock.patch('agent_runner.plat.WINDOWS', False), \
                mock.patch.object(SLT, 'send_fifo_raw', lambda p, b: typed.append((p.name, b)) or True):
            code, out = post(f'{base}/act?t={token}', {'name': 'interrupt', 'args': {'session': 'c6'}})
        eq((out['ok'], typed), (True, [('control6.in', b'\x1b')]), 'interrupt c6 through /act')
    finally:
        srv.stop()


def test_control_rows(tmp: Path) -> None:
    """F73: a snapshot holding control session c6 and an idle s2: the page gives cN rows c1-like tabs (terminal,
    session) with no open button, an idle slot's terminal tab says it is idle, /terminal/c6 finds c6's pane by its
    tag, and the claude.ai copy lists c6 as a control session, not a slot."""
    from agent_runner import page_copy as PC
    fake_repo(tmp)
    snap = {'project': 'proj', 'at': 'now', 'status': ['run up'], 'queue': [], 'needs': [], 'concepts': [], 'log': [],
            'sessions': [
                {'name': 'c1', 'task': '', 'title': 'control session', 'minutes': None, 'state': 'live', 'files': [],
                 'link': 'https://claude.ai/code/c1', 'terminal': ''},
                {'name': 'c6', 'task': '', 'title': 'R43 site deploy', 'minutes': None, 'state': 'live', 'files': [],
                 'link': 'https://claude.ai/code/c6x', 'terminal': ''},
                U.idle_row('s2')]}
    token = W.web_token()
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: snap)
    base = f'http://127.0.0.1:{srv.server_address[1]}'
    try:
        page = get(f'{base}/?t={token}')[1]
        eq([s['name'] for s in json.loads(get(f'{base}/snapshot?t={token}')[1])['sessions']], ['c1', 'c6', 's2'],
           'the snapshot carries c6 and the idle s2')
        for part in (b"S.snap.sessions.filter(s=>/^c\\d+$/.test(s.name))",  # F133: then put in the kept order
                     b"const working_=()=>slots().filter(s=>s.task)", b'>Idle</span>'):
            check(part in page, f'the app lists cN as a chat, a slot on a task as working: {part.decode()}')
        asked = []
        with mock.patch.object(W.shutil, 'which', return_value='/usr/bin/ttyd'), \
                mock.patch('agent_runner.plat.WINDOWS', False), \
                mock.patch('agent_runner.attach.session_socket', lambda n: asked.append(n)):
            r = json.loads(get(f'{base}/terminal/c6?t={token}')[1])
        eq(asked, ['c6'], "c6's terminal looks up control session 6's socket")
        check(not r['ok'] and 'c6 is not up' in r['out'], 'and says when it has none', r)
    finally:
        srv.stop()
    copy = PC.page_copy_html(snap)
    check('<span class="r">c6</span><span>R43 site deploy</span><a' in copy and 'https://claude.ai/code/c6x' in copy,
          'the copy lists c6 with its title and session link', copy)
    check('s2 is idle: nothing running' in copy, 'and the idle s2 as idle', copy)
    check('open it from the run page' not in copy, 'with no open-it hint on c6 or s2', copy)


NEWS_DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const logic = page.split('<script id="logic">')[1].split('</script>')[0].replace(/if\(typeof module[^\n]*/, '');
const part = page.slice(page.indexOf("let RUN_VERSION=''"), page.indexOf('function takeSnap('));
const mk = () => { const m = {}; return {m, get: k => m[k] || '', set(k, v) { if (dead) return; if (v) m[k] = v; else delete m[k] }} };
let dead = false, reloads = 0, said = [], ta = null, rc = {key: 'restart'};
const store = mk(), tabStore = mk(), HKEY = 'p', HI = {i: null}, TK = {}, DK = {}, OB_KEY = 'ob';
const DRAFT_KEY = k => 'd:' + k, boxKey = () => 'home', toast = t => said.push(t), esc = t => String(t), render = () => {};
const document = {title: 't', querySelector: () => ta}, location = {reload() { reloads++ }}, els = {}, $ = k => els[k] = els[k] || {};
const setHTML = (e, h) => { e.h = h }, controlOf = () => rc, ctlBusy = () => false, ctlSure = () => 'SURE';
let H, S;
const fresh = (snap, f) => { H = {add: ''}; S = {snap, f: f || {}, atts: {}, ob: [], setOpen: {}, sure: null}; };
fresh({});
const src = (home, mine) => logic + part.replace("let RUN_VERSION=''", "var RUN_VERSION=''").replace(/\bconst /g, 'var ')
  + `;var HOME_PAGE=${home}, PAGE_PRINT=${JSON.stringify(mine)};`;
const out = {};
eval(src(false, 'aaa').replace(/\bconst /g, 'var '));
const draw = snap => { S.snap = snap; newsDraw(); return [els.news.hidden, els.news.h] };
out.same = draw({page: 'aaa', version: '1'});
out.oldRun = draw({version: '2'});
out.newer = draw({page: 'bbb', version: '1'});
newsLater('page:bbb'); out.later = draw({page: 'bbb'}); out.next = draw({page: 'ccc'});
S.later = tabStore.get(LATER_KEY).split(' '); out.laterKept = draw({page: 'bbb'})[0];
out.restart = draw({page: 'aaa', restart_needed: 'k1'});
S.sure = 'restart'; out.sure = draw({page: 'aaa', restart_needed: 'k1'})[1]; S.sure = null;
rc = null; out.noctl = draw({page: 'aaa', restart_needed: 'k1'})[1];
newsLater('restart:k1'); out.restartLater = [draw({page: 'aaa', restart_needed: 'k1'})[0], draw({page: 'aaa', restart_needed: 'k2'})[0]];
PAGE_PRINT = '/' + '*PAGE_PRINT*/'; out.raw = draw({page: 'bbb'})[0]; PAGE_PRINT = 'aaa';
out.noReload = reloads;
// Refresh keeps what is written, or waits
const go = () => { const n = reloads; said = []; newsRefresh(); return [reloads - n, said[0] || ''] };
fresh({}, {'set:project:x': '5', setq: 'cap'}); S.f.padd = '/x'; S.ren = 'c2'; S.setOpen = {a: 1};
S.atts = {c1: [{name: 'p.png', path: '/up/p.png', thumb: 'data:'}], c2: []}; S.ob = [{cid: '1'}]; store.set('ob', JSON.stringify(S.ob));
ta = {value: 'half a thought'}; store.set('d:home', ta.value);
out.kept = go();
fresh({}); takeTyped(); out.back = [S.f, S.f.padd, S.ren, S.setOpen, S.atts]; out.once = tabStore.get(TYPED_KEY);
HOME_PAGE = true; out.homeKey = eval(part.match(/TYPED_KEY=([^;]*);/)[1]) !== TYPED_KEY; HOME_PAGE = false;  // F432
fresh({}); ta = null; out.nothing = [go(), tabStore.get(TYPED_KEY)];
fresh({}); tabStore.set(TYPED_KEY, JSON.stringify({atts: [{name: 'o', path: '/o'}]})); takeTyped(); out.oldAtts = S.atts;  // kept by a page before B182
fresh({}); S.atts = {c9: [{name: 'x'}]}; out.uploading = go();
fresh({}); TK.rec = {}; out.mic = go(); TK.rec = null; DK.rec = {}; out.dict = go(); DK.rec = null;
fresh({}, {'dev:password': 'hunter2', setq: 'a'}); out.form = [go(), JSON.stringify(tabStore.m).includes('hunter2')];
fresh({}); ta = {value: 'not kept'}; store.set('d:home', ''); out.unkept = go();
dead = true; fresh({}); ta = null; S.f.padd = 'x'; out.dead = go(); fresh({}); S.ob = [{cid: '9'}]; out.deadOb = go();
HOME_PAGE = true; fresh({}); S.later = []; out.home = [draw({page: 'bbb'})[1], draw({page: 'aaa', restart_needed: true})[1]];
console.log(JSON.stringify(out));
"""


def test_news_f149(tmp: Path) -> None:
    """F149: a page that is not the one the run serves shows a popup with Refresh and Later and never reloads by
    itself; Refresh keeps what is written; code only a person restarts the run on says a restart is needed."""
    page = W.page_html().decode()
    check(f"const PAGE_PRINT='{W.PAGE_PRINT}'" in page and f"const PAGE_PRINT='{W.PAGE_PRINT}'" in W.page_html(home=True).decode(),
          "the page holds its own fingerprint, Home's too")
    snap = W.with_extras({})
    eq((snap['page'], snap['restart_needed']), (W.PAGE_PRINT, ''), 'the snapshot names the page the run serves')
    with mock.patch.object(W.watch, 'RESTART_NEEDED', ['k']):
        eq(W.with_extras({})['restart_needed'], 'k', 'and that a person must restart the run')
    eq((page.count('location.reload()'), page.split('function turnIntoApp(){')[1].split('\n}')[0].count('location.reload()')), (2, 1),
       'one reload in the page, the Refresh button, and one on the page of a project that is off, once its run is up (F150)')
    from agent_runner import home as H
    stamps = [('a', 1)]
    with mock.patch.object(H, 'package_stamp', lambda: stamps[0]):
        srv = H.serve_home('HT', 0, '127.0.0.1', rows=lambda: [], roots=lambda: [], vitals=mock.Mock())
        own = H.HomeServer('HT', 0, '127.0.0.1', rows=lambda: [], roots=lambda: [], vitals=mock.Mock(), stamp=lambda: stamps[0])
        try:
            url = f'http://127.0.0.1:{srv.server_address[1]}/projects?t=HT'
            got = json.loads(get(url)[1])
            eq((got['page'], got['restart_needed']), (W.PAGE_PRINT, ''), 'Home answers its page too')
            stamps[0] = ('b', 2)
            check(json.loads(get(url)[1])['restart_needed'], 'a Home that cannot restart itself says so')
            check(not own.restart_needed(), 'one that restarts by itself needs no person')
        finally:
            srv.stop()
            own.server_close()
    if not shutil.which('node'):
        print('  (no node here: the popup script test is skipped)')
        return
    (tmp / 'driver.js').write_text(NEWS_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs the popup', r.stderr[-1500:])
    if r.returncode:
        return
    o = json.loads(r.stdout)
    eq((o['same'], o['oldRun'], o['raw']), ([True, ''], [True, ''], True), 'the same page, or a run that names none: no popup')
    check(not o['newer'][0] and 'A new version of this page is ready' in o['newer'][1] and 'data-newsrefresh' in o['newer'][1]
          and 'data-newslater' in o['newer'][1], 'another page, the version the same: the popup', o['newer'])
    eq((o['later'][0], o['next'][0], o['laterKept']), (True, False, True), 'Later holds for that page, over a reload too; the next one shows')
    check('Restart the run to use it' in o['restart'][1] and 'data-ctl="restart"' in o['restart'][1], 'a restart is needed', o['restart'])
    eq(o['sure'].count('SURE'), 1, 'its button asks first')
    check('data-ctl' not in o['noctl'] and 'start it again' in o['noctl'], 'a run without the control: what to do', o['noctl'])
    eq(o['restartLater'], [True, False], 'Later holds for that code; newer code shows')
    eq(o['noReload'], 0, 'nothing of that reloads the page')
    eq(o['kept'], [1, ''], 'Refresh with a draft and an outbox reloads')
    eq(o['back'], [{'set:project:x': '5', 'setq': 'cap', 'padd': '/x'}, '/x', 'c2', {'a': 1},
                   {'c1': [{'name': 'p.png', 'path': '/up/p.png'}]}], 'and what was written comes back, an attachment to its own box')
    eq(o['oldAtts'], {'home': [{'name': 'o', 'path': '/o'}]}, "B182: an older page's attachments come back in the open box")
    eq((o['once'], o['nothing']), ('', [[1, ''], '']), 'once; with nothing written nothing is kept')
    check(o['homeKey'], "F432: the off page in between (Home's, same project) does not take them")
    for k, word in (('uploading', 'uploading'), ('mic', 'mic'), ('dict', 'mic'), ('unkept', 'cannot keep'), ('dead', 'cannot keep'),
                    ('deadOb', 'cannot keep')):
        check(o[k][0] == 0 and word in o[k][1], f'{k}: Refresh waits and says why', o[k])
    check(o['form'][0][0] == 0 and 'device form' in o['form'][0][1] and not o['form'][1], 'a device form holds it, and its secret is never kept', o['form'])
    check('data-newsrefresh' in o['home'][0] and 'Restart Runner Home' in o['home'][1] and 'data-ctl' not in o['home'][1], 'the same on Home', o['home'])


SCROLL_DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const grab = (start) => { const i = page.indexOf(start); return page.slice(i, page.indexOf('\n}\n', i) + 2); };
const line = s => { const i = page.indexOf(s); return page.slice(i, page.indexOf('\n', i)) + '\n' };
const logic = page.split('<script id="logic">')[1].split('</script>')[0];
// a scrolling box as the page has it: keyed rows of a height each, drawn from its markup ('key:height key:height')
class Box {
  constructor(h) { this.h = h; this._top = 0; this.rows = []; this.on = {}; this.cls = new Set();
    this.classList = {add: c => this.cls.add(c), remove: c => this.cls.delete(c), toggle: (c, v) => v ? this.cls.add(c) : this.cls.delete(c), contains: c => this.cls.has(c)} }
  set innerHTML(v) { this.v = v; let y = 0;
    this.rows = v.replace(/<[^>]*>/g, ' ').split(' ').filter(x => x.includes(':')).map(r => { const [k, n] = r.split(':'); const e = {dataset: {k}, y, n: +n, cls: new Set()};
      e.classList = {add: c => e.cls.add(c)}; e.getBoundingClientRect = () => ({top: e.y - this._top, bottom: e.y + e.n - this._top}); y += +n; return e });
    this.scrollTop = this._top }
  get innerHTML() { return this.v || '' }
  get scrollHeight() { return this.rows.reduce((a, r) => a + r.n, 0) }
  get clientHeight() { return this.h }
  get offsetWidth() { return 1 }
  get scrollTop() { return this._top }
  set scrollTop(v) { this._top = Math.max(0, Math.min(v, Math.max(0, this.scrollHeight - this.h))) }
  getBoundingClientRect() { return {top: 0, bottom: this.h} }
  querySelectorAll(s) { return s === '[data-k]' ? this.rows : [] }
  contains() { return false }
  addEventListener(t, f) { this.on[t] = f }
}
const els = {body: new Box(100), dock: new Box(10), top: new Box(10), jump: new Box(10)};
const $ = k => els[k] = els[k] || new Box(10);
const ta = {value: 'hello', dataset: {}};
const document = {activeElement: null, hidden: false, querySelector: s => s === '[data-in]' ? ta : s === '.main' ? main : s === '.notices' ? {offsetHeight: 0} : null};
const on = {}, main = {classList: {toggle: (c, v) => on[c] = v}, style: {setProperty() {}}};
const window = {}, matchMedia = () => ({matches: reduced}), getComputedStyle = () => ({getPropertyValue: k => k.startsWith('--dur') ? '450ms' : 'ease'});
let reduced = false, frames = []; const requestAnimationFrame = f => frames.push(f);
let HOME_PAGE = false, VIEW = 'a:60 b:60 c:60', CHAT = 'm1:80 m2:80';
const S = {snap: {sessions: []}, view: 'home', thread: null, f: {}, atts: {}, ob: [], feeds: {}, live: true, sheet: ''};
const pageColor = () => {}; const HI = {i: null}, TERM = {mode: ''}, I = {down: ''}, keysLine = () => '', esc = s => s, tq = p => p;
const markSeen = () => {}, obHide = () => {}, obDraw = () => {}, newsDraw = () => {}, loginDraw = () => {}, offDraw = () => {}, walkDraw = () => {}, setBarDraw = () => {}, waitBarDraw = () => {}, side = () => {}, rowSettle = () => {}, sheetDraw = () => {}, topHTML = () => 'x:1';
const isAgent = () => false, threadTitle = n => n, feedDraw = () => {}, box = () => 'box', store = {get: () => '', set() {}};
const boxKey = () => S.thread || 'home', grow = () => {}, slashShow = () => {}, talkHTML = () => CHAT, histAdd = () => {};
const homeHTML = () => VIEW, statusHTML = () => VIEW, planHTML = () => VIEW, historyHTML = () => VIEW, conceptsHTML = () => VIEW, toolsHTML = () => VIEW, settingsHTML = () => VIEW, settingsDraw = (el, h) => setHTML(el, h), planDraw = settingsDraw, histDraw = settingsDraw, projectsHTML = () => VIEW;
const DRAFT_KEY = k => k, toast = () => {}, open = n => { S.thread = n; render(true) }, outboxed = [];
const talkMic = () => 'mic', talkFoot = () => '', talkDraw = () => {}, talkBack = () => {}, talkLate = () => true, talkAway = () => {}, keepPlace = () => {}, settingsTrip = () => {};
const outbox = (n, a) => { outboxed.push([n, a.text]); CHAT += ' mine' + outboxed.length + ':40'; render(true) };
eval(logic + line('function setHTML(') + grab('function keepScroll(') + grab('function keysIn(').split('\nfunction enter')[0]
  + grab('function enter(') + page.slice(page.indexOf('const MO='), page.indexOf('\nconst shiftOf=')) + '\nconst flying=()=>0,glideSpot=()=>null,glide=()=>{},leaving=()=>{},freshWords=()=>{},sentFrom=()=>{},sentMark=()=>{},loopsInStep=()=>{},sendFly=()=>{},viewSlide=()=>{};' + grab('function keepFields(') + line('function viewIn(') + line('const PD=') + 'const selecting=()=>false;'
  + line('let lastPlace=') + line('S.at={};') + line('const chatShown=') + line('function toEnd(') + line('let SEE=') + grab('function seeRoom(') + grab('function seeBar(')
  + grab('function render(') + line("$('body').addEventListener('scroll'") + grab('async function send(') + `
(async () => {
  const b = $('body'), out = {}, scroll = y => { b.scrollTop = y; b.on.scroll() };
  // every view: a refresh keeps the reading position, whatever came in above it
  out.views = {};
  for (const v of ['home', 'status', 'plan', 'concepts', 'tools', 'settings']) {
    S.view = v; VIEW = 'a:60 b:60 c:60 d:60'; render(true);
    b.scrollTop = 70; VIEW = 'a:60 b:60 c:60 d:60 e:60'; render();
    const same = b.scrollTop;
    VIEW = 'new:35 a:60 b:60 c:60 d:60 e:60'; render();
    out.views[v] = [same, b.scrollTop];
  }
  b.scrollTop = 0; VIEW = 'top:20 ' + VIEW; render(); out.atTop = b.scrollTop;
  out.entered = b.rows.filter(r => r.cls.has('enter')).map(r => r.dataset.k);
  VIEW = VIEW + ' '; b._h = ''; render(); out.still = b.rows.filter(r => r.cls.has('enter')).length;
  b.scrollTop = 50; S.view = 'plan'; render(true); S.view = 'settings'; render(true); out.back = b.scrollTop;
  // Talk: opens at its end, follows what comes in, stays put once scrolled up
  S.view = 'talk'; render(true);
  const left = () => b.scrollHeight - b.scrollTop - b.clientHeight;
  out.open = left();
  CHAT += ' m3:90'; render(); out.follows = left();
  scroll(5); CHAT += ' m4:90'; render(); out.up = b.scrollTop;
  scroll(10); PD.down = true; CHAT += ' m5:50'; render(); out.held = b.innerHTML.includes('m5'); PD.down = false; render(); out.after = [b.innerHTML.includes('m5'), b.scrollTop];
  // F171: Talk's top bar: away on a scroll up, back on a scroll down, never by a refresh or a change of size
  out.see = on.see; toEnd(); const end = b.scrollTop, bar = [on.away];
  scroll(end - 100); bar.push(on.away);                        // up: away
  CHAT += ' m6:90'; render(); bar.push(on.away);               // new words: still away
  b.h = 60; b.on.scroll(); bar.push(on.away); b.h = 100; b.on.scroll();  // the keyboard: still away
  scroll(end - 96); bar.push(on.away);                         // 4px down: not yet
  scroll(end - 90); bar.push(on.away);                         // 10px: back
  scroll(end - 150); bar.push(on.away); b._top = -40; b.on.scroll(); b._top = 0; b.on.scroll(); bar.push(on.away);  // iOS's bounce at the top
  toEnd(); bar.push(on.away);                                  // at the end: back
  b._top += 40; b.on.scroll(); b._top -= 40; b.on.scroll(); bar.push(on.away);  // the bounce at the end
  scroll(0); CHAT = 'm1:40'; render(); bar.push(on.away);      // nothing left to scroll: back
  S.view = 'home'; render(true); out.bar = bar; out.leaves = [on.see, on.away];
  console.log(JSON.stringify(out));
})();`);
"""


def test_scroll_f83(tmp: Path) -> None:
    """F83: a refresh keeps the reading position in every view (what came in above moves nothing); Talk opens at its
    newest words and follows them unless the person scrolled up."""
    if not shutil.which('node'):
        print('  (no node here: the scroll script test is skipped)')
        return
    (tmp / 'driver.js').write_text(SCROLL_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs render()', r.stderr[-900:])
    got = json.loads(r.stdout or '{}')
    for v, (same, above) in (got.get('views') or {}).items():
        eq((same, above), (70, 105), f'{v}: a refresh keeps scrollTop, and a card above it moves nothing on screen')
    eq(len(got.get('views') or {}), 6, 'every view was looked at')
    eq(got.get('atTop'), 0, 'at the very top, the new thing shows')
    eq((got.get('entered'), got.get('still')), (['top'], 0), 'only what is new comes in moving; a redraw moves nothing')
    eq(got.get('back'), 50, 'coming back to a view returns to where it was')
    eq(got.get('open'), 0, 'Talk opens at its newest words')
    eq(got.get('follows'), 0, 'and follows what comes in')
    eq(got.get('up'), 5, 'scrolled up: it stays put')
    eq(got.get('see'), True, "F171: Talk's chat runs behind its bar and buttons")
    eq(got.get('bar'), [False, True, True, True, True, False, True, True, False, False, False],
       "F171: Talk's top bar goes on a scroll up, comes back on a scroll down or at the end; a refresh, the keyboard or a bounce moves nothing")
    eq(got.get('leaves'), [False, False], 'F171: no other view is see-through')
    css = W.PAGE.read_text(encoding='utf-8').split('<style>', 1)[1].split('</style>', 1)[0]
    eq(set(re.findall(r'\.main\.see\.away \.(\w+)', css)), {'top'}, 'F171: only the top bar (and the notices under it) goes: the buttons stay')
    check('prefers-reduced-transparency:reduce' in css, 'F171: Reduce Transparency: solid')
    eq((got.get('held'), got.get('after')), (False, [True, 10]), 'a press holds the refresh back until it ends')


KB_DRIVER = SCROLL_DRIVER.split("const els = ")[0] + r"""
const on = {}, VVS = {height: 800, offsetTop: 0, scale: 1, addEventListener: (t, f) => on[t] = f};
const CSS = {supports: p => p === '-webkit-touch-callout'}, window = {CSS, visualViewport: VVS, scrollY: 0, scrollTo(x, y) { this.scrollY = y }};
const cls = () => { const c = new Set(); return {toggle: (k, v) => v ? c.add(k) : c.delete(k), contains: k => c.has(k)} };
const els = {app: {style: {}, classList: cls()}, body: new Box(600)};
const $ = k => els[k], box = {matches: () => true, closest: () => null}, docOn = {};
let clock = 5000, frames = [], reduced = false, glides = [];
Date.now = () => clock;
let later = [], every = null;
const setTimeout = f => later.push(f), tasks = () => { const l = later; later = []; l.forEach(f => f()) };
const setInterval = f => (every = f, 1), clearInterval = () => { every = null };
let lastPlace = null;
const requestAnimationFrame = f => frames.push(f), frame = (ms = 16) => { clock += ms; const l = frames; frames = []; l.forEach(f => f()) };
const matchMedia = () => ({matches: reduced}), getComputedStyle = () => ({getPropertyValue: k => k === '--ease' ? ' ease-out' : '250ms'});
const anim = who => (kf, o) => { const a = {who, from: kf[0].transform, ms: o.duration, cancel() {}}; glides.push(a); return a };
els.body.style = {}; els.body.animate = anim('text');
const dockEl = {style: {}, animate: anim('dock'), getBoundingClientRect: () => ({top: (parseInt(els.app.style.top) || 0) + (parseInt(els.app.style.height) || 800) - 100})};
const document = {activeElement: null, documentElement: {clientHeight: 800}, addEventListener: (t, f) => docOn[t] = f, querySelector: s => s === '.dockwrap' ? dockEl : null};
const S = {view: 'talk', thread: null, pin: true, sheet: ''};
const seeRoom = () => {}, seeBar = () => {};
const feedTop = () => null, feedGlide = () => {}, TOUCH = () => false, MO = {scroll: new Map()};
eval(line('const atEnd=') + line('const chatShown=') + line('function toEnd(') + page.slice(page.indexOf('const VV='), page.indexOf('function grow(')) + `
const b = $('body'), out = {}, left = () => b.scrollHeight - b.scrollTop - b.clientHeight;
const app = () => [$('app').style.height || '', $('app').style.top || '', $('app').classList.contains('kb')];
// what the layout does: the chat loses what .app loses
const vv = (h, top, t = 'resize') => { VVS.height = h; VVS.offsetTop = top; b.h = h - 200; on[t]() };
b.innerHTML = 'a:900 b:900'; toEnd();
vv(700, 0); out.bar = app();
document.activeElement = box;
window.scrollY = 90; vv(420, 260); out.open = [app(), left(), window.scrollY];
vv(420, 0, 'scroll'); out.panned = [app(), left()];
vv(380, 10); out.taller = [app(), left()];
vv(800, 24); out.closed = [app(), left()];
S.pin = false; b.scrollTop = 300; vv(420, 260); out.up = b.scrollTop; vv(800, 0);
VVS.scale = 2; vv(400, 50); out.zoom = app(); VVS.scale = 1; vv(800, 0);
document.activeElement = null; vv(420, 0); out.noField = app(); vv(800, 0);
S.view = 'home'; b.scrollTop = 0;
const field = {matches: () => true, closest: () => b, getBoundingClientRect: () => ({top: 400 - b.scrollTop, bottom: 440 - b.scrollTop})};
document.activeElement = field; vv(420, 260); out.field = [app(), b.scrollTop];
field.getBoundingClientRect = () => ({top: 500 - b.scrollTop, bottom: 540 - b.scrollTop});
docOn.focusin({target: field}); out.next = b.scrollTop;
// the order the recording shows: focus, the pan, the resize late; then blur before the resize
document.activeElement = null; frame(2000); frame(2000); vv(800, 0);
S.view = 'talk'; S.pin = true; toEnd(); window.scrollY = 0; glides.forEach(g => g.onfinish && g.onfinish());
document.activeElement = box; docOn.focusin({target: box});
VVS.offsetTop = 260; window.scrollY = 90; frame(); out.panFirst = [app(), window.scrollY];
VVS.height = 420; b.h = 220; glides = []; frame(); out.thenShort = [app(), left(), glides.map(g => [g.who, g.from, g.ms]), b.style.marginTop];
glides[0].onfinish(); out.glided = [b.style.marginTop, left()];
on.resize(); on.scroll(); out.lateEvents = app();
VVS.offsetTop = 0; frame(); out.settled = app();
frame(2000); frame(2000); out.idle = frames.length;
VVS.offsetTop = 40;
docOn.focusout({target: box, relatedTarget: box}); Promise.resolve().then(() => { out.nextField = app();
  docOn.focusout({target: box, relatedTarget: null}); document.activeElement = box; return Promise.resolve() }).then(() => { out.redrawn = app();
  document.activeElement = null; b.h = 600; glides = []; docOn.focusout({target: box, relatedTarget: null}); return Promise.resolve() }).then(() => {
  out.blurFirst = [app(), left(), glides.map(g => g.who)];
  VVS.offsetTop = 0; frame(); out.unpanned = app();
  VVS.height = 800; on.resize(); out.lateClose = app(); frame(2000);
  VVS.offsetTop = 24; on.scroll(); out.after = app(); VVS.offsetTop = 0;
  reduced = true; glides = []; document.activeElement = box; vv(420, 0); out.reduced = [app(), glides.length]; document.activeElement = null; vv(800, 0);
  // a tap on a box: its focus is made here, with no scroll; a scroll, a long press and a box in focus are left alone
  const log = [], tb = {style: {}, matches: () => true, getBoundingClientRect: () => ({top: 0, bottom: 0}), value: 'draft', isConnected: true, closest: () => tb, setSelectionRange: (x, y) => log.push([x, y]), blur: () => log.push('blur'), focus: o => log.push([o.preventScroll, tb.style.opacity]), click: () => log.push('click')};
  const tap = (dx, ms, off) => { log.length = 0; let stopped = false; docOn.touchstart({touches: [{clientX: 50, clientY: 700}], target: tb}); clock += ms;
    docOn.touchend({cancelable: true, defaultPrevented: !!off, changedTouches: [{clientX: 50, clientY: 700 + dx}], preventDefault() { stopped = true }}); return [stopped, log.slice()] };
  out.tap = tap(2, 80); frame(); out.hidden = tb.style.opacity; frame(); out.shown = tb.style.opacity;
  // a notice's row in a chat scrolled up: the text stays, also when the chat is another one
  eval(line('let noticeH=').replace('let ', 'var ') + line('function noticeRoom('));
  lastPlace = 'a'; noticeRoom(0); S.pin = false; b.scrollTop = 300; noticeRoom(36); const r1 = b.scrollTop; noticeRoom(0); const r2 = b.scrollTop;
  lastPlace = 'b'; noticeRoom(36); out.notice = [r1, r2, b.scrollTop];
  out.notTap = [tap(30, 80), tap(0, 700), tap(0, 80, true)]; document.activeElement = tb; out.scripted = tap(0, 80)[1][0]; vv(420, 0); out.again = tap(0, 80);
  // B212a: the viewport is back with no event, the box still in focus
  tasks(); document.activeElement = box; vv(420, 0); frame(2000); frame(2000); const asked = !!every;
  VVS.height = 800; if (every) every(); out.noEvent = [asked, app(), !!every];
  // blurred, and the viewport never says the keyboard went: a script's focus later
  vv(420, 0); document.activeElement = null; docOn.focusout({target: box, relatedTarget: null});
  const enter = () => { document.activeElement = box; docOn.focusin({target: box, relatedTarget: null}); frame(); return app() };
  Promise.resolve().then(() => { const full = app(); clock += 2000; out.stale = [full, enter()]; on.resize(); out.staleEvent = app();
    VVS.scale = 2; VVS.height = 210; on.resize(); VVS.scale = 1; VVS.height = 420; on.resize(); out.staleZoom = app();
    VVS.height = 800; on.resize(); VVS.height = 420; on.resize(); out.staleOver = app();
    document.activeElement = null; docOn.focusout({target: box, relatedTarget: null}); return Promise.resolve() }).then(() => {
    out.soon = enter(); document.activeElement = null; docOn.focusout({target: box, relatedTarget: null}); return Promise.resolve() }).then(() => {
    clock += 2000; docOn.click(); out.pressed = enter(); tasks();
    document.activeElement = null; docOn.focusout({target: box, relatedTarget: null}); return Promise.resolve() }).then(() => {
    clock += 2000; enter(); docOn.input({isTrusted: false}); const own = app(); docOn.input({isTrusted: true}); out.typed = [own, app()];
    // another app, the keyboard open
    document.hidden = true; box.blur = () => { document.activeElement = null; docOn.focusout({target: box, relatedTarget: null}) };
    docOn.visibilitychange(); return Promise.resolve() }).then(() => { document.hidden = false; on.resize(); out.otherApp = [document.activeElement, app(), every];
  console.log(JSON.stringify(out));
  }).catch(e => { console.error(e); process.exit(1) });
});`);
"""


def test_keyboard_b160(tmp: Path) -> None:
    """B160: while a phone's keyboard is open .app takes the visual viewport's height and place with no bottom inset, a
    pinned chat stays at its end, a field in a scroller is shown, and closing puts all of it back."""
    css = W.PAGE.read_text(encoding='utf-8').split('<style>', 1)[1].split('</style>', 1)[0]
    check(re.search(r'\.app\.kb\{[^}]*position:fixed[^}]*padding-bottom:0\}', css), 'keyboard open: .app is placed, with no bottom inset')
    check(re.search(r'\.app\{[^}]*padding-bottom:env\(safe-area-inset-bottom', css), 'closed: .app keeps its bottom inset')
    check(re.search(r'\.app\.kb \.dock\{padding-bottom:8px\}', css), 'and the dock its 14px only when closed')
    check(':root.term{--page:var(--t-bg)}' in css and re.search(r'html,body\{[^}]*background:var\(--page\)', css), "outside .app is the view's own colour")
    check('.main.term .over{height:auto' in css, "a chat's notices have a row of their own")
    check('interactive-widget=resizes-content' in W.PAGE.read_text(encoding='utf-8'), 'a browser that can resizes the page itself')
    check('html,body{height:100%;overscroll-behavior:none;overflow:hidden;' in css and 'body{position:fixed;inset:0' in css, 'the document is locked')
    if not shutil.which('node'):
        print('  (no node here: the keyboard script test is skipped)')
        return
    (tmp / 'driver.js').write_text(KB_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs kbFit()', r.stderr[-900:])
    got = json.loads(r.stdout or '{}')
    off = ['', '', False]
    eq(got.get('bar'), off, "Safari's own bar is no keyboard")
    eq(got.get('open'), [['420px', '260px', True], 0, 0], 'open: .app has the height and place, the chat stays at its end, the document is scrolled back')
    eq(got.get('panned'), [['420px', '0px', True], 0], 'a pan moves .app with it')
    eq(got.get('taller'), [['380px', '10px', True], 0], 'a taller keyboard too')
    eq(got.get('closed'), [off, 0], 'closed: back to normal, still at the end, whatever offsetTop Safari left')
    eq(got.get('up'), 300, 'a chat scrolled up stays where it was')
    eq((got.get('zoom'), got.get('noField')), (off, off), 'neither a pinch zoom nor a short window with no field in focus is a keyboard')
    eq(got.get('field'), [['420px', '260px', True], 228], 'a field in a view is scrolled above the keyboard')
    eq(got.get('next'), 328, 'and so is the next field, with the keyboard still open')
    eq(got.get('panFirst'), [['', '260px', False], 0], 'a pan before the resize: full height, the header follows it, the document is scrolled back')
    eq(got.get('thenShort'), [['420px', '260px', True], 0, [['text', 'translateY(380px)', 250], ['dock', 'translateY(380px)', 250]], '-380px'],
       'the viewport changed: seen on the next frame with no event, and the box and the words glide there')
    eq(got.get('glided'), ['', 0], 'after the glide nothing of it is left')
    eq((got.get('lateEvents'), got.get('settled')), (['420px', '260px', True], ['420px', '0px', True]), 'late events change nothing; the pan that ends is followed')
    eq(got.get('idle'), 0, 'and no frame is asked for once it is settled')
    eq((got.get('nextField'), got.get('redrawn')), (['420px', '0px', True],) * 2, 'going to another field, or a redrawn box, closes nothing')
    eq(got.get('blurFirst'), [['', '40px', False], 0, ['text', 'dock']], 'a blur before the resize: full height at once, pinned, the header still on screen')
    eq((got.get('unpanned'), got.get('lateClose'), got.get('after')), (off, off, off), 'then all of it back to normal')
    eq(got.get('reduced'), [['420px', '0px', True], 0], 'reduced motion: no glide')
    eq(got.get('tap'), [True, [[5, 5], [True, '0'], 'click']], "a tap's focus does not scroll, and the box is see-through for it")
    eq((got.get('hidden'), got.get('shown')), ('0', ''), 'for two frames')
    eq(got.get('scripted'), 'blur', 'a box focused by a script has no keyboard: the tap focuses it anew')
    eq(got.get('notice'), [336, 300, 300], "a notice's row moves no text; a chat just opened keeps its place")
    eq((got.get('notTap'), got.get('again')), ([[False, []]] * 3, [False, []]), 'a scroll, a long press, a swipe and a box in focus are left to the browser')
    up = ['420px', '0px', True]
    eq(got.get('noEvent'), [True, off, False], 'B212a: a viewport back with no event is seen while the keyboard is open, and no longer asked for then')
    eq((got.get('stale'), got.get('staleEvent'), got.get('staleZoom')), ([off, off], off, off), "B212a: a script's focus over a viewport still short from a keyboard long away: full height")
    eq((got.get('staleOver'), got.get('soon'), got.get('pressed')), (up, up, up), 'a height that changed, a box back soon, and a press are a keyboard')
    eq(got.get('typed'), [off, up], 'and so is typing, but not words a script put in')
    eq(got.get('otherApp'), [None, off, None], 'B212a: going to another app leaves the box, so .app is whole on the way back')


KB_FEED_DRIVER = r"""
const fs = require('fs'), page = fs.readFileSync(process.argv[2], 'utf8');
const slice = (a, b) => { const i = page.indexOf(a); if (i < 0) throw Error(a); return page.slice(i, page.indexOf(b, i)) };
const line = s => slice(s, '\n') + '\n';
const on = {}, VVS = {height: 800, offsetTop: 0, scale: 1, addEventListener: (t, f) => on[t] = f};
const CSS = {supports: () => true}, window = {CSS, visualViewport: VVS, scrollY: 0, scrollTo() {}};
let clock = 5000, hidden = false, reduced = false, touch = true, glides = [], doc = 800, wide = 390, boxH = 27, extra = 0, after = [];
Date.now = () => clock;
const setTimeout = f => after.push(f), clearTimeout = () => {}, requestAnimationFrame = () => {};
const matchMedia = () => ({matches: reduced});
const getComputedStyle = el => el === ta ? {minHeight: '26px', lineHeight: '23.2px', paddingTop: '2px', paddingBottom: '2px'}
  : {getPropertyValue: k => k === '--sab' ? '34px' : k === '--ease' ? ' ease-out' : '250ms'};
const cls = () => ({toggle() {}, contains: () => false});
let kbNow = () => 0;
const kbOn = () => kbNow() > 0, mainH = () => kbNow() || doc - 34;
const anim = who => (kf, o) => { const a = {who, by: parseFloat((kf[0].translate || kf[0].transform.replace('0px,', '')).match(/(-?[\d.]+)px/)[1]), o: [o.duration, o.easing], cancel() {}}; glides.push(a); return a };
const ta = {get offsetHeight() { return boxH }, matches: () => true};
const main = {get clientHeight() { return mainH() }, get clientWidth() { return wide }, style: {setProperty() {}}, classList: cls()};
const dockEl = {get offsetHeight() { return 142 + boxH + extra - (kbOn() ? 6 : 0) }, style: {}, animate: anim('dock'), getBoundingClientRect: () => ({top: main.clientHeight - dockEl.offsetHeight})};
const ff = {style: {}, animate: anim('frame'), getBoundingClientRect: () => ({top: parseFloat((ff.style.transform || '(0').split('(')[1]) + parseFloat((ff.style.translate || '0 0').split(' ')[1])})};
const els = {app: {style: {}, classList: cls()}, body: {style: {}, scrollTop: 0}, feedframe: ff, feed: {style: {}}, top: {offsetHeight: 52}};
const $ = k => els[k], docOn = {};
const document = {get hidden() { return hidden }, activeElement: null, documentElement: {get clientHeight() { return doc }}, addEventListener: (t, f) => (docOn[t] = docOn[t] || []).push(f),
  querySelector: s => s === '.main' ? main : s === '.dockwrap' ? dockEl : s === '.notices' ? {offsetHeight: 0} : s === '#dock [data-in]' ? ta : null};
const S = {view: 'talk', thread: 'c6', pin: true, sheet: ''}, TOUCH = () => touch, seeRoom = () => {}, seeBar = () => {}, toEnd = () => {};
const MO = {fly: new Map()}, shiftOf = () => ({m42: 0}), FD = {frame: {}, shown: true, foot: {top: 40}, whole: false, off: 0, jump: false, held: '', t: 0, above: 0, last: 0, full: 0, wide: 0, doc: 0, short: 0}, CELL = 17;
const feedScreen = () => ({cell: CELL, el: {getBoundingClientRect: () => ({top: 12})}, t: {buffer: {active: {type: 'alternate'}}}});
global.pastPlace = global.pastGlide = () => {}; global.pastUp = () => false;  // F191b: tests/test_web_history.py
eval(line('const SLIM_H=') + line('const KB_PAD=') + line('const FOOT_ROWS=') + slice('function feedSpot(', '/* B192') + slice('function moAnim(', 'const shiftOf=') + slice('function growGlide(', '/* B119') + line('const calm=') + line('const chatShown=')
  + slice('function feedRoom(', '/* the bars and the box away') + slice('const VV=', 'function grow(') + `
kbNow = () => kbH;
// the frame's height, and from its last line to the box
const at = () => { feedPlace(); return [parseInt(ff.style.height), Math.round(dockEl.getBoundingClientRect().top - (parseFloat(ff.style.transform.split('(')[1]) + 12 + (FD.whole ? FD.last : FD.short || FD.foot.top) * CELL))] };
const kb = h => { document.activeElement = h ? ta : null; VVS.height = h || doc; glides = []; on.resize(); clock += 2000; glides.forEach(g => stay || g.onfinish && g.onfinish()); return [at(), glides.map(g => [g.who, g.by, ...g.o])] };
const out = {};
let stay = false;
const trip = k => out[k] = [at(), kb(420), (boxH = 73, at()), (boxH = 27, at()), kb(380)[0], kb(0)];
trip('rest'); FD.short = 34; trip('short'); FD.short = 6; trip('fits'); FD.short = 0;
FD.whole = true; FD.last = 31; trip('whole'); FD.last = 9; trip('asked'); FD.whole = false;
at(); FD.jump = true; FD.t += 80; FD.off = 80; trip('up'); out.kept = FD.off; const t0 = FD.t; extra = 40; at(); out.chip = FD.t - t0; extra = 0; at(); FD.jump = false; FD.off = 0; at();
const dk = {children: [], animate: anim('box')}, tb = {closest: k => k === '.dock' ? dk : {animate() {}}};
glides = []; feedPlace(); boxH = 73; growGlide(tb, 46); out.grown = glides.map(g => [g.who, g.by, ...g.o]);
reduced = true; glides = []; boxH = 27; growGlide(tb, -46); out.grownCalm = glides.length; reduced = false; at();
stay = true; kb(420); out.room = els.feed.style.bottom; stay = false; kb(0); out.roomAfter = els.feed.style.bottom;
// half way: from where it is on screen
stay = true; kb(420); stay = false; ff.style.translate = '0 100px'; dockEl.getBoundingClientRect = () => ({top: 0}); kb(0); out.mid = glides.filter(g => g.who === 'frame').map(g => g.by);
dockEl.getBoundingClientRect = () => ({top: main.clientHeight - dockEl.offsetHeight}); ff.style.translate = '';
reduced = true; out.calm = kb(420)[1]; kb(0); reduced = false; hidden = true; out.hid = kb(420)[1]; kb(0); hidden = false;
// rotation, the keyboard open; then closed
kb(420); doc = 390; wide = 844; out.turned = kb(200)[0][0]; out.turnedBack = kb(0)[0][0]; doc = 900; wide = 1200; out.window = at()[0]; doc = 800; wide = 390; at();
// a browser that shrinks the page itself, and a blur before it is back
document.activeElement = ta; docOn.focusin.forEach(f => f({target: ta})); clock += 2000; doc = VVS.height = 450; on.resize(); out.shrunk = at();
document.activeElement = null; docOn.focusout.forEach(f => f({target: ta})); out.left = at()[0]; clock += 2000; after.forEach(f => f()); out.real = at()[0];
touch = false; document.activeElement = ta; doc = VVS.height = 300; out.desk = at()[0];
console.log(JSON.stringify(out));`);
"""


def test_keyboard_feed_b214(tmp: Path) -> None:
    """B214: the keyboard over a session never resizes it: its frame goes with the message box, its last line on the box,
    and a rotation or a real window change still resizes."""
    if not shutil.which('node'):
        print('  (no node here: the session keyboard script test is skipped)')
        return
    (tmp / 'driver.js').write_text(KB_FEED_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs kbFit() over a session', r.stderr[-900:])
    got = json.loads(r.stdout or '{}')
    for k, high, gap in (('rest', 812, 0), ('short', 812, 0), ('whole', 545, 0), ('asked', 545, 0), ('up', 812, -80)):
        here, opened, grown, back, taller, closed = got.get(k) or [None] * 6
        eq([here, grown, back, taller], [[high, gap]] * 4, f'{k}: one size, the last line as far from the box, keyboard open, box grown')
        eq((opened, closed), ([[high, gap], [['dock', 340, 250, 'ease-out'], ['frame', 340, 250, 'ease-out']]],
                              [[high, gap], [['dock', -380, 250, 'ease-out'], ['frame', -380, 250, 'ease-out']]]), f'{k}: the frame goes with the box')
    fits = got.get('fits') or [None] * 6
    eq((fits[0], fits[1], fits[5]), ([812, 431], [[812, 91], [['dock', 340, 250, 'ease-out']]], [[812, 431], [['dock', -380, 250, 'ease-out']]]),
       'B786: a short one that fits stands under the top bar, keyboard open or closed, and does not move')
    eq((got.get('grown'), got.get('grownCalm')), ([['frame', 46, 250, 'ease-out'], ['box', 46, 250, 'ease-out']], 0), 'a box that grew: the frame goes with it; none when calm')
    eq(got.get('kept'), 80, 'scrolled up, as far past its rest as before')
    eq(got.get('chip'), 0, 'scrolled up, a chip row that comes moves nothing')
    eq((got.get('room'), got.get('roomAfter')), ('-340px', ''), 'its lines are drawn below the view while they come up')
    eq(got.get('mid'), [-240], 'half way, it goes on from where it is on screen')
    eq((got.get('calm'), got.get('hid')), ([], []), 'calm: no glide')
    eq((got.get('turned'), got.get('turnedBack'), got.get('window')), (402, 402, 912), 'a rotation and a window change resize it')
    eq((got.get('shrunk'), got.get('left'), got.get('real')), ([812, 0], 812, 462), 'a browser that shrinks the page: the same, until it is no keyboard')
    eq(got.get('desk'), 312, 'on a desktop a short window is a short window')


OLD_RUN_DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const given = JSON.parse(process.argv[3]);
const grab = (start) => { const i = page.indexOf(start); return page.slice(i, page.indexOf('\n}\n', i) + 2) + '\n' };
const line = s => { const i = page.indexOf(s); return page.slice(i, page.indexOf('\n', i)) + '\n' };
const slice = (a, b) => page.slice(page.indexOf(a), page.indexOf(b));
const logic = page.split('<script id="logic">')[1].split('</script>')[0];
const kept = {}, store = {get: k => kept[k] || '', set(k, v) { kept[k] = v }};
const said = [], toast = t => said.push(t), render = () => {}, tq = p => p, esc = t => String(t);
const els = {}, $ = k => els[k] = els[k] || {}, setHTML = (el, h) => { el.h = h };
const emptyCard = t => t, card = h => h, pageTitle = () => '', HOME_PAGE = false, document = {}, I = {chev: ''}, draftTidy = () => {};
const working_ = () => [], talkWaitName = () => '', chats = () => S.chats || [], open = n => { S.thread = n };
const DK = {rec: null, key: '', base: ''}, CHATS_OF = '';
const carrySent = () => {}, addSent = () => {};
let reply = null, status = 200, posts = [];
const fetch = async (p, o) => {
  if (p === 'act') posts.push(JSON.parse(o.body));
  return {status, ok: status < 400, json: async () => reply};
};
const rc = {key: 'restart', label: 'Restart the run', confirm: 'Restart?'};
const S = {snap: {needs: [], concepts: [], controls: [rc], boot: 'b1'}, f: {}, ob: [], thread: null, view: 'settings', waitNew: null, obOpen: false, gone: {}, setOpen: {}};
const OB = {busy: false, offline: false, timer: 0, wait: 2000}, obLoad = () => {}, obBeat = () => {}, obLive = () => [], obTake = async () => true, OB_KEY = 'ob';
const threadTitle = n => n, cutsOff = () => '', sureHTML = q => q;
let cids = 0;
const newCid = () => 'k' + (++cids);
eval(logic.replace(/if\(typeof module[^\n]*/, '') + line('function obChange(') + line('function actFailed(') + grab('async function act(') + grab('function outbox(') + grab('async function drain(')
  + line('const DRAFT_KEY=') + grab('function boxMove(') + grab('function obDone(') + line('const controlOf=') + line('const ctlSure=') + line('const ctlBusy=') + slice('function oldRunHTML(', 'const obBtns=')
  + line('const obBtns=') + line('const obState=') + line('const notDelivered=') + grab('function obDraw(') + line('function obBoot(') + grab('function obRetryClick(')
  + line('function obCards(') + slice('const settingId=', 'const setErrHTML=') + slice('const setErrHTML=', 'SHEETS.setting=') + grab('async function loadSettings(') + grab('function takeSnap(') + `
const settle = async () => { for (let i = 0; i < 6; i++) await new Promise(r => setTimeout(r, 5)) };
(async () => {
  const out = {};
  // Settings: the route is not there, then another error, then one over settings already loaded
  reply = given.route; status = 404; await loadSettings(); out.route = [settingsHTML(), S.set === undefined];
  reply = {ok: false, out: 'disk full'}; status = 200; await loadSettings(); out.err = settingsHTML();
  S.set = {ok: false, out: 'x'}; out.bad = settingsHTML();
  const good = {tables: [], groups: [], unknown: [], project: 'p', device: 'd'};
  reply = good; await loadSettings(); out.good = [settingsHTML(), S.set === good];
  reply = given.route; status = 404; await loadSettings(); out.keeps = [S.set === good, settingsHTML()];
  // need_chat to a run without it: kept, with the restart control and no Retry
  reply = given.act; status = 200;
  const it = outbox('need_chat', {tid: 'F1'}, {newchat: true, say: 'About F1'}); S.thread = '@' + it.cid;
  outbox('chat_to', {text: 'hi', to: '@' + it.cid}, {text: 'hi', say: 'hi'});
  await settle(); obDraw();
  out.pill = els.obbar.h;
  out.refused = [S.ob.map(x => [x.name, x.state]), said[said.length - 1], els.obpop.h, JSON.parse(kept.ob).length];
  // another snapshot of the same run: nothing is sent again; the next run: both go, under a cid every tab shares
  posts = []; takeSnap({boot: 'b1'}); await settle(); out.same = posts.length;
  reply = {ok: true, name: 'c7'}; takeSnap({boot: 'b2'}); await settle();
  out.sent = [posts.map(p => [p.name, p.cid, p.args.to || '']), S.ob.length, S.thread];
  // one an older page left in the Outbox (no boot kept) goes too; a plain failure does not
  S.ob = [{cid: 'z', name: 'need_chat', args: {}, state: 'failed', err: 'no such action: need_chat', say: 'z'},
          {cid: 'y', name: 'answer', args: {}, state: 'failed', err: 'disk full', say: 'y'}];
  posts = []; takeSnap({boot: 'b3'}); await settle(); out.legacy = [posts.map(p => p.cid), S.ob.map(x => x.cid)];
  // still refused by a run that is older too: once per run, no loop
  reply = given.act; S.ob = [{cid: 'z', name: 'need_chat', args: {}, state: 'failed', err: 'no such action: need_chat', say: 'z'}];
  posts = []; takeSnap({boot: 'b4'}); await settle(); takeSnap({boot: 'b4'}); await settle(); out.once = posts.map(p => p.cid);
  S.ob = [{cid: 'd', name: 'need_drop', args: {confirm: true}, state: 'failed', err: 'no such action: need_drop', say: 'd'}];
  posts = []; takeSnap({boot: 'b5'}); await settle(); S.obOpen = true; obDraw(); out.ctl = [posts.length, els.obpop.h.includes('data-obretry')];
  // outside the Outbox (Talk): the same words and control
  S.ob = []; S.obOpen = false; await act('talk', {}); out.act = [said[said.length - 1], S.obOpen, els.obpop.h];
  S.snap.controls = []; obDraw(); out.noctl = els.obpop.h;
  // F174: a save that settles leaves the newer value the field holds while its own save has yet to go
  const set = {id: 'run.auto_release'}, f = 'set:project:run.auto_release', one = {cid: 'p1', name: 'setting_project', args: {}, set, say: 's'};
  reply = good; status = 200; out.newer = [];
  for (const j of [{ok: true, out: 'x'}, {ok: false, out: 'no'}]) for (const wait of [true, false]) {
    S.f[f] = 'new'; S.ob = wait ? [{...one, cid: 'p2', state: 'sending'}] : [];
    obDone(one, j); await settle(); out.newer.push(f in S.f)}
  // B202: words typed in a chat still starting: Retry, its name by the run's answer, and by a snapshot
  const drafts = () => [S.thread, Object.fromEntries(Object.entries(kept).filter(([k, v]) => k.startsWith('ar-draft:') && v)), DK.key, DK.base];
  S.ob = [{cid: 'n1', name: 'new_control', args: {}, newchat: true, state: 'failed', err: 'x', say: 'n'}]; S.thread = '@n1';
  store.set(DRAFT_KEY('@n1'), 'and mo'); store.set(DRAFT_KEY('c1'), 'other'); Object.assign(DK, {rec: {}, key: '@n1', base: 'and'});
  reply = {ok: false, out: 'busy'}; cids = 100; obRetryClick('n1'); await settle(); out.words = [drafts()];
  reply = {ok: true, name: 'c9'}; obRetryClick('k101'); await settle(); out.words.push(drafts());
  DK.rec = null; S.ob = []; S.thread = '@w'; S.waitNew = {ph: '@w', known: ['c9'], at: Date.now()}; S.chats = [{name: 'c9'}, {name: 'c10'}];
  store.set(DRAFT_KEY('@w'), 'newer'); store.set(DRAFT_KEY('c10'), 'older'); takeSnap({boot: S.snap.boot}); await settle(); out.words.push(drafts());
  console.log(JSON.stringify(out));
  process.exit(0);
})();`);
"""


RELOAD_DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const grab = (start) => { const i = page.indexOf(start); return page.slice(i, page.indexOf('\n}\n', i) + 2) + '\n' };
const line = s => { const i = page.indexOf(s); return page.slice(i, page.indexOf('\n', i)) + '\n' };
const slice = (a, b) => page.slice(page.indexOf(a), page.indexOf(b, page.indexOf(a)));
const logic = page.split('<script id="logic">')[1].split('</script>')[0].replace(/if\(typeof module[^\n]*/, '');
const map = () => { const m = {}; return {m, getItem: k => k in m ? m[k] : null, setItem: (k, v) => { m[k] = String(v) }, removeItem: k => { delete m[k] }} };
const boom = {getItem() { throw new Error('blocked') }, setItem() { throw new Error('blocked') }, removeItem() { throw new Error('blocked') }};
const settle = async () => { for (let i = 0; i < 6; i++) await new Promise(r => setTimeout(r, 2)) };
/* one load of the page: the page's own place and Talk code, over the tab's and the browser's storage */
function load(o) {
  const body = `
const log = {draws: [], settings: 0, spoke: [], heard: 0, on: {}};
const HOME_PAGE = false, location = {pathname: o.path || '/p/a/', search: '?t=x', hash: o.hash || ''}, document = {title: o.title || 'a · runner', querySelector: () => null};
const history = {replaceState(a, b, u) { log.url = u; location.hash = '' }}, addEventListener = (t, f) => { log.on[t] = f };
const setTimeout = () => { log.focus = (log.focus || 0) + 1 }, tq = p => p, TOUCH = () => false, takeTyped = () => {}, toast = () => {}, esc = t => String(t), LOGO = () => '', md = t => t, I = {chev: ''};
const fetch = async p => ({json: async () => (o.feeds || {})[decodeURIComponent(p.split('/')[1])] || {ok: false, name: decodeURIComponent(p.split('/')[1]), entries: [], out: 'none'}});
const S = {snap: {sessions: [], needs: []}, view: 'home', thread: null, ctx: null, feeds: {}, sent: o.sent || {}, ob: o.ob || [], openSteps: {}, gone: {}, waitNew: null};
const OB = {}, drain = () => {}, working_ = () => [], keepSent = () => {}, loadSettings = () => { log.settings++ }, loadTools = () => {};
const TK = {state: '', wait: null, starting: [], gen: 0}, TS = {read: true, auto: true}, speak = t => log.spoke.push(t), listen = () => { log.heard++ };
const render = () => { keepPlace(); log.draws.push([S.view, S.thread]) }, obBubbles = () => '', isAgent = n => n[0] === 's';
const threadTitle = n => n, PN = () => 'p', sentBubbles = () => '', starting = () => false, startLine = () => '', busy = () => true, talkGoing = () => '', tkey = t => t;
` + logic + line('const HB=') + slice('const store=', 'const DRAFT_KEY') + line('const TALK_FOR=') + line('const talkKept=')
  + line('const sessionOf=') + 'const chats=()=>S.snap.sessions;' + line('const feedOf=')
  + grab('function talkOld(') + grab('function talkName(') + grab('function talkWaitName(') + grab('function talkHear(') + grab('function talkHTML(')
  + line('const ended=') + grab('function talkConvo(') + grab('function takeSnap(') + grab('async function loadFeed(')
  + slice('/* B177: the open view and chat', '/* --- doing things') + line('function open(') + line('function goView(')
  + slice('\ntakePlace();', 'if(HOME_PAGE){  // F134') + line('placeLoad();  // B177')
  + `;return {S, TK, log, location, open, goView, takeSnap, loadFeed, talkConvo, talkHTML, talkName, talkKeep, talkKept, at: () => [S.view, S.thread]};`;
  return new Function('o', 'sessionStorage', 'localStorage', body)(o, o.tab, o.browser || map());
}
const c = (n, title) => ({name: n, title: title || n, state: 'live'});
const snap = (...l) => ({at: 'now', sessions: [c('c1'), ...l], needs: []});
(async () => {
  const out = {views: {}}, talk = {ok: true, name: 'c4', entries: [{kind: 'you', text: 'hi'}, {kind: 'say', text: 'An old reply.'}]};
  let tab = map(), p;
  for (const v of ['home', 'talk', 'tools', 'plan', 'concepts', 'settings', 'projects']) {  // F476: Status is Work ('plan')
    load({tab}).goView(v); p = load({tab}); out.views[v] = [p.log.draws[0][0], p.log.draws.length];
    p.takeSnap(snap()); out.views[v].push(p.at()[0]);
    if (v === 'settings') out.settings = p.log.settings;
  }
  tab.m['ar-place:b · runner'] = '{"v":"projects"}';
  p = load({tab, path: '/', title: 'b · runner'}); out.noHome = p.at();
  // a chat and a slot, over the view they were opened from
  const feeds = {c3: {ok: true, name: 'c3', entries: [{kind: 'say', text: 'Said.'}]}};
  tab = map(); p = load({tab, feeds}); p.goView('plan'); p.open('c3');
  p = load({tab, feeds}); out.chat = [p.log.draws[0]]; p.takeSnap(snap(c('c3'))); await settle(); out.chat.push(p.at(), p.talkConvo('c3').includes('This chat has ended'));
  p = load({tab, feeds}); p.takeSnap(snap()); await settle(); out.ended = [p.at(), p.talkConvo('c3').includes('This chat has ended.'), p.talkConvo('c3').includes('Working on it'), p.talkConvo('c3').includes('Said.')];
  p = load({tab}); out.gone = [p.log.draws[0]]; await settle(); out.gone.push(p.at()); p.takeSnap(snap()); out.gone.push(p.at()); out.gone.push(load({tab}).at());
  tab = map(); p = load({tab}); p.open('s1');
  p = load({tab}); p.takeSnap(snap(c('s1'))); await settle(); out.slot = p.at();
  p = load({tab}); p.takeSnap(snap()); await settle(); out.goneSlot = p.at();
  // the feed could not be read: not gone
  load({tab}).open('c3'); p = load({tab, feeds: {c3: {ok: false, out: 'no such page'}}}); p.takeSnap(snap()); await settle(); out.unread = p.at();
  // just started, its message not landed: not gone; a stand-in lives with its outbox item
  p = load({tab, sent: {c3: {pending: [{id: 'k', text: 'x'}]}}}); p.takeSnap(snap()); await settle(); out.fresh = p.at();
  p = load({tab}); p.goView('plan'); p.open('@k1'); p = load({tab, ob: [{cid: 'k1', newchat: true, args: {}}]}); out.standIn = [p.at()];
  p.open('c8'); out.quiet = p.log.focus || 0; p.open('c3'); out.quiet = [out.quiet, p.log.focus]; p.open('@k1');
  out.standIn.push(load({tab}).at());
  // projects, by Home's key or by the run's own title; another tab
  tab = map(); load({tab}).goView('plan'); out.other = [load({tab, path: '/p/b/'}).at(), load({tab}).at(), load({tab: map()}).at()];
  tab = map(); load({tab, path: '/', title: 'x · runner'}).goView('status'); out.own = [load({tab, path: '/', title: 'y · runner'}).at(), load({tab, path: '/', title: 'x · runner'}).at()];
  // what is kept is no place
  out.junk = [];
  for (const t of ['{', 'null', '7', '{"v":"nope","t":"../x"}', '{"v":"agents","t":4}']) { tab = map(); tab.m['ar-place:a'] = t; out.junk.push(load({tab}).at()) }
  // storage that throws
  p = load({tab: boom, browser: boom}); p.takeSnap(snap()); p.goView('talk'); p.talkHTML(); out.boom = p.at();
  // a link wins, and leaves the address
  tab = map(); load({tab}).open('c3');
  p = load({tab, hash: '#plan'}); out.link = [p.at(), p.log.url]; p.goView('status'); out.link.push(load({tab}).at());
  out.link.push(load({tab, hash: '#c5'}).at(), load({tab, hash: '#nothing'}).at());
  p = load({tab}); p.location.hash = '#settings'; p.log.on.hashchange(); out.link.push([...p.at(), p.log.settings]);
  // Talk: its own chat, quiet, per tab and per project
  tab = map(); const browser = map(), two = snap(c('c2', 'Talk'), c('c4', 'Talk'));
  p = load({tab, browser}); p.goView('talk'); p.talkKeep('c4');
  const tab2 = map(); load({tab: tab2, browser}).talkKeep('c2');
  p = load({tab, browser, feeds: {c4: talk}}); out.talkFirst = [p.talkHTML().includes('Loading'), p.talkHTML().includes('Talk to the run')];
  p.takeSnap(two); p.talkHTML(); await settle(); await p.loadFeed('c4'); await p.loadFeed('c4');
  out.talk = [p.at(), p.talkName(), p.talkHTML().includes('An old reply.'), p.log.spoke, p.log.heard, p.TK.state];
  p = load({tab: map(), browser}); p.takeSnap(two); out.talkNewTab = p.talkName();
  p = load({tab, browser, path: '/p/b/'}); p.takeSnap(snap(c('c4'), c('c2', 'Talk'))); out.talkOther = p.talkName();
  p = load({tab, browser, path: '/p/c/', feeds: {c4: talk}}); p.talkKeep('c4'); p.goView('talk');
  p = load({tab, browser, path: '/p/c/', feeds: {c4: talk}}); p.takeSnap(snap()); p.talkHTML(); await settle(); const h = p.talkHTML();
  out.talkEnded = [h.includes('An old reply.'), h.includes('This chat has ended.'), h.includes('Your next message opens a new Talk chat.'), p.talkName(), p.log.spoke.length];
  p = load({tab, browser, path: '/p/c/'}); p.takeSnap(snap()); p.talkHTML(); await settle(); out.talkGone = p.talkHTML().includes('Talk to the run');
  p = load({tab: tab2, browser, path: '/p/c/'}); p.talkKeep(''); load({tab: map(), browser, path: '/p/c/'}).talkKeep('c9'); out.talkNone = p.talkKept();
  const own = {tab: map(), browser, path: '/'}; load({...own, title: 'x · runner'}).talkKeep('c4');
  p = load({...own, title: 'y · runner'}); out.talkOwn = [p.talkKept(), load({...own, title: 'x · runner'}).talkKept()];
  console.log(JSON.stringify(out));
})();
"""


def test_reload_b177(tmp: Path) -> None:
    """B177: a reload opens what was open: the view, the chat or slot, and Talk's own chat, per project and per tab."""
    if not shutil.which('node'):
        print('  (no node here: the reload script test is skipped)')
        return
    (tmp / 'driver.js').write_text(RELOAD_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs the reloads', r.stderr[-1500:])
    if r.returncode:
        return
    o, home = json.loads(r.stdout), ['home', None]
    for v, got in o['views'].items():
        eq(got, [v, 1, v], f'{v}: open in the first draw after a reload, and still after the first snapshot')
    eq(len(o['views']), 7, 'every view')
    eq(o['settings'], 1, 'Settings reads its settings')
    eq(o['noHome'], home, 'All projects without Runner Home falls to Home')
    eq(o['chat'], [['plan', 'c3'], ['plan', 'c3'], False], 'a chat is open in the first draw, over the view it was opened from')
    eq(o['ended'], [['plan', 'c3'], True, False, True], 'an ended chat shows its words and that it ended, not that it works')
    eq(o['gone'], [['plan', 'c3'], ['plan', 'c3'], home, home], 'a chat that no longer exists: Home, once the run says so')
    eq((o['slot'], o['goneSlot']), (['home', 's1'], home), 'a slot too')
    eq((o['unread'], o['fresh']), (['home', 'c3'], ['home', 'c3']), 'a feed that could not be read, or a chat just started, is not gone')
    eq(o['standIn'], [['plan', '@k1'], home], 'a chat still starting, while the outbox has it')
    eq(o['quiet'], [0, 1], 'and its box is not focused when it gets its name')
    eq(o['talkEnded'], [True, True, True, '', 0], "Talk's chat that has ended: its words and that it ended; the next message opens a new one")
    eq((o['talkGone'], o['talkNone'], o['talkOwn']), (True, '', ['', 'c4']), 'a gone one greets; another tab, or another project on the same address, does not set it')
    eq(o['other'], [home, ['plan', None], home], 'two projects, or two tabs, do not share')
    eq(o['own'], [home, ['plan', None]], "nor two projects on a run's own address")
    eq(o['junk'], [home] * 4 + [['plan', None]], 'what is no place is Home; an old view name is its new one')
    eq(o['boom'], ['talk', None], 'storage that throws: the page loads and works')
    eq(o['link'], [['plan', None], '/p/a/?t=x', ['plan', None], ['home', 'c5'], ['home', 'c5'], ['settings', None, 1]],
       "a link's view or chat wins and leaves the address; one that names nothing does not; one followed in the open page")
    eq(o['talkFirst'], [True, False], 'Talk waits for its chat without a greeting')
    eq(o['talk'], [['talk', None], 'c4', True, [], 0, ''], "Talk's own chat, with no reply read aloud and no mic")
    eq((o['talkNewTab'], o['talkOther']), ('c2', 'c2'), "a new tab takes the browser's last; another project does not")


def test_older_run_b164(tmp: Path) -> None:
    """B164: a run serves the page it started with, whatever an update puts on disk; and a page newer than its run
    says so (Settings, a need_chat the run does not know) and sends what it kept once the run restarts."""
    fake_repo(tmp)
    with mock.patch.object(Path, 'read_text', side_effect=AssertionError('read from disk')):
        page = W.page_html()
    check(b'function settingsHTML(' in page, 'the run app is served from the start, not from the file on disk')
    real = Path.read_text

    def newer(self, *a, **k):
        return 'NEWER' if self == W.PAGE else real(self, *a, **k)
    with mock.patch.object(Path, 'read_text', newer):
        check('NEWER' not in W.page_html().decode(), 'an update on disk changes neither page')
    eq(W.with_extras({})['boot'], W.BOOT, 'the snapshot names the process, so the page sees a restart')
    token = W.web_token()
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {})
    base = f'http://127.0.0.1:{srv.server_address[1]}'
    try:
        without = {k: v for k, v in U.ACTIONS.items() if k != 'need_chat'}
        with mock.patch.object(U, 'ACTIONS', without):
            _, refused = post(f'{base}/act?t={token}', {'name': 'need_chat', 'args': {'tid': 'F1'}, 'cid': 'k1'})
        code, route = get(f'{base}/no-settings?t={token}')
    finally:
        srv.stop()
    eq((refused['ok'], refused['out']), (False, 'no such action: need_chat'), 'a run without need_chat refuses it')
    eq((code, json.loads(route)['ok']), (404, False), 'a run without a route answers 404')
    if not shutil.which('node'):
        print('  (no node here: the older run script test is skipped)')
        return
    (tmp / 'driver.js').write_text(OLD_RUN_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE), json.dumps({'act': refused, 'route': json.loads(route)})],
                       capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs the page against an older run', r.stderr[-900:])
    if r.returncode:
        return
    o = json.loads(r.stdout)
    old, wait, btn = 'This run is older than this page. Restart it.', 'It goes once the run restarts', 'data-ctl="restart"'
    check(old in o['route'][0] and btn in o['route'][0] and 'no such' not in o['route'][0] and 'Try again' in o['route'][0],
          'Settings on an older run says so, with the restart control, not a raw 404', o['route'])
    check(o['route'][1], 'and the error is not kept as the settings')
    check('disk full' in o['err'] and 'Try again' in o['err'] and btn not in o['err'], 'another error: its words and Try again', o['err'])
    check(isinstance(o['bad'], str) and 'Try again' in o['bad'], 'an error object in S.set does not throw')
    check('Find a setting' in o['good'][0] and o['good'][1] and 'Try again' not in o['good'][0], 'Try again that works clears it', o['good'])
    check(o['keeps'][0] and old in o['keeps'][1] and 'Find a setting' in o['keeps'][1], 'settings already loaded stay', o['keeps'])
    eq(o['refused'][0], [['need_chat', 'failed'], ['chat_to', 'failed']], 'need_chat and its message stay in the Outbox')
    check(o['refused'][1] == old and wait in o['refused'][2] and btn in o['refused'][2], 'which says why, with the restart control', o['refused'])
    check('no such action' not in o['refused'][2] and o['refused'][3] == 2, 'no raw error, and kept over a reload', o['refused'])
    check('data-obretry' not in o['refused'][2], 'no Retry that can never work, on its message either', o['refused'])
    check('2 waiting for a restart' in o['pill'] and 'failed' not in o['pill'].split('>', 1)[1], 'the pill says it waits', o['pill'])
    eq(o['ctl'], [0, True], 'a confirmed action never goes by itself after a restart: Retry')
    eq(o['newer'], [True, False, True, False], 'F174: a save that settles keeps a newer value waiting to go in its field')
    c1, c9 = {'ar-draft:c1': 'other'}, {'ar-draft:c1': 'other', 'ar-draft:c9': 'and mo'}
    eq(o['words'], [['@k101', {**c1, 'ar-draft:@k101': 'and mo'}, '@k101', 'and'], ['c9', c9, 'c9', 'and'],
                    ['c10', {**c9, 'ar-draft:c10': 'older\nnewer'}, 'c9', 'and']],
       "B202: words typed in a chat still starting are in its box after Retry and when it gets its name")
    eq(o['same'], 0, 'the same run: not sent again')
    eq(o['sent'], [[['need_chat', 'k1~b2', ''], ['chat_to', 'k2', 'c7']], 0, 'c7'], 'the run restarted: both go, once')
    eq(o['legacy'], [['z~b3'], ['y']], 'one an earlier page left there goes too; a plain failure waits for Retry')
    eq(o['once'], ['z~b4'], 'refused again: once per run')
    check(o['act'][0] == old and o['act'][1] and btn in o['act'][2], 'Talk says the same', o['act'])
    check('Stop the run and start it again' in o['noctl'], 'a run without the restart control: what to do instead', o['noctl'])


FEED_DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const logic = page.split('<script id="logic">')[1].split('</script>')[0].replace(/if\(typeof module[^\n]*/, '');
const part = page.slice(page.indexOf('const FD={'), page.indexOf('/* the touch layer over the frame'));
const el = () => ({hidden: false, kids: [], appendChild(x) { this.kids.push(x); x.box = this }, classList: {toggle() {}}});
const els = {feed: el(), body: el(), feedframe: el(), feedsay: el(), feedstand: el(), feedline: el()}, $ = k => els[k];
els.feed.clientWidth = 1020;
const on = {}, docOn = {}, location = {origin: 'https://x'}, addEventListener = (t, f) => on[t] = f;
const typed = [], term = {modes: {applicationCursorKeysMode: false}, input: t => typed.push(t), rows: 2,
  buffer: {active: {viewportY: 1, getLine: y => ({translateToString: () => ['old', 'one  ', 'two'][y]})}}};
const hold = {}, calls = [], arLine = {dial: (n, l) => calls.push('dial ' + n + ' ' + l), hang: () => calls.push('hang'), keep: () => 'screen of ' + hold.FD.n, show: k => { arLine.shown = k }, heard: () => hold.heard || 0};
const requestAnimationFrame = f => f(), md = t => t, feedOf = n => n === 'c12' ? [{kind: 'you', text: 'Hi'}, {kind: 'tool', text: 'ls'}, {kind: 'say', text: 'Hello back'}] : [];
let lost = false;
const document = {hidden: false, documentElement: {classList: {toggle() {}}}, addEventListener: (t, f) => docOn[t] = f,
  createElement: () => ({style: {}, contentWindow: {term, arLine, arLook() {}}, remove() { const k = this.box.kids; k.splice(k.indexOf(this), 1) }})};
const getComputedStyle = () => ({fontFamily: 'mono'}); document.body = {appendChild(x) { x.box = {kids: []} }};
const window = {}, T = 'TOK', esc = t => String(t), LOGO = () => '', I = {ext: ''}, tq = p => p, card = h => h;
const timers = [], setTimeout = (f, ms) => timers.push({f, ms}), clearTimeout = () => {};
const said = [], toast = t => said.push(t), sheets = [], openSheet = n => sheets.push(n), upload = f => said.push(f);
const S = {snap: {sessions: [{name: 'c6', link: 'L'}, {name: 'c12'}], fixups: {resume: [{id: 'F1'}]}}, sent: {}, ob: [], last: {s3: {task: 'F1', title: 'a'}}};
const isAgent = n => !/^(c\d+|@.+)$/.test(n), sessionOf = n => S.snap.sessions.find(s => s.name === n), threadTitle = n => n;
const starting = n => n === 'c8', sentBubbles = () => '', obBubbles = () => 'WAITS', controlOf = () => ({}), ctlBusy = () => false;
const setHTML = (e, h) => { e.innerHTML = h }, render = () => feedDraw(S.thread);
const feedGone = () => {}, feedUp = () => {}, feedSee = () => {}, feedPlace = () => {}, feedLook = () => 'dark', feedShown = on => { hold.FD.shown = on }, feedAt = (x, y) => [x, y];
let answers = {};
const fetch0 = async p => { if (lost) throw new Error('lost'); return {json: async () => answers[p.split('/')[1]]} };
let fetch = fetch0;
eval(logic + part + `
hold.FD = FD;
const settle = async () => { for (let i = 0; i < 8; i++) await Promise.resolve() };
const at = () => [!$('feed').hidden, !$('body').hidden, $('feedframe').kids.map(k => k.src)];
(async () => {
  const out = {}, show = async n => { S.thread = n; render(); await settle(); return at() };
  answers.c6 = {ok: true, path: '/t/TOK/c6/'};
  out.c6 = await show('c6'); out.waits = [$('feedsay').hidden, $('feedline').hidden, $('feedstand').hidden, FD.frame.className, timers.some(t => t.ms > 4000)];
  FD.since -= 6000; feedSkin(); out.long = [$('feedsay').hidden, $('feedsay').innerHTML.includes('Connecting')];
  render(); out.once = $('feedframe').kids.length;
  feedKey('up'); out.early = said.slice();
  const f = FD.frame, word = (d, src = f.contentWindow, origin = location.origin) => on.message({data: {session: 'c6', ...d}, source: src, origin});
  word({state: 'up'}, {}); word({state: 'up'}, f.contentWindow, 'https://evil'); out.foreign = FD.up;
  word({state: 'up'}); out.up = [FD.up, $('feedsay').hidden];
  for (const [k] of FEED_KEYS) feedKey(k);
  out.keys = typed.splice(0); term.modes.applicationCursorKeysMode = true; feedKey('up'); out.app = typed.splice(0);
  feedText(); out.text = [S.feedText, sheets];
  word({files: ['pic']}); out.files = said.pop();
  word({state: 'drawn'}); out.drawn = [FD.frame.className, $('feedline').hidden, $('feedstand').hidden, $('feedsay').hidden];
  // F206: its connection breaks: its screen stays, and it dials again by itself, with no load
  FD.foot = {}; calls.length = 0; lost = true; word({state: 'down'});
  out.down = [arLine.shown, FD.frame.className, $('feedline').hidden, $('feedsay').hidden, timers.some(t => t.ms === 250)];
  timers.filter(t => t.ms === 250).pop().f(); await settle();
  out.lost = [at(), calls.slice(), arLine.shown]; FD.since -= 6000; feedSkin(); out.re = $('feedsay').innerHTML; lost = false;
  word({state: 'up'}); word({state: 'drawn'}); out.again = [arLine.shown, $('feedline').hidden, FD.frame === f];
  // F206a: the network goes silent, the socket still open: after 5 s the line and Reconnecting…, over the screen as it is
  let quit; const ask = silent => { fetch = silent ? (p, o) => { quit = o.signal; return new Promise((f, no) => quit.addEventListener('abort', no)) } : fetch0; return liveGet('c6') };
  const q1 = ask(true), q2 = await ask(true); FD.deaf -= 4000; feedSkin(); out.quiet4 = $('feedsay').hidden;
  FD.deaf -= 1500; hold.heard = Date.now(); feedSkin(); out.heard = $('feedsay').hidden;
  hold.heard = 0; feedSkin(); out.mute = [$('feedline').hidden, $('feedsay').innerHTML.includes('Reconnecting'), FD.frame.className, arLine.shown, q2];
  timers.filter(t => t.ms === 8000).pop().f(); await q1; feedSkin(); out.gave = [quit.aborted, FD.ask, $('feedline').hidden];
  calls.length = 0; answers.c6 = {ok: true}; await ask(false); await settle(); out.unmute = [calls.slice(), arLine.shown, $('feedsay').hidden, FD.deaf];
  word({state: 'up'}); word({state: 'drawn'}); out.unmuted = [$('feedline').hidden, $('feedsay').hidden];
  await ask(false); out.answered = FD.deaf;
  ask(true); FD.deaf -= 9000; liveStop(); feedSkin(); out.woke = [quit.aborted, FD.deaf, $('feedline').hidden]; fetch = fetch0;
  // another chat: the same frame; back: its last screen at once, and it is dialed before the run's answer
  answers.c12 = {ok: true, look: 'page'}; calls.length = 0; const go = show('c12'); out.other = [$('feedstand').hidden, $('feedstand').innerHTML, feedWant()]; await go;
  // B819: the stand-in's text size is the terminal's, on touch and not, and its cells are xterm's
  const sizes = () => [/fontSize=(\\d+)/.exec(feedSrc('c12'))[1], /font-size:(\\d+)px/.exec(standHTML('c12'))[1]];
  out.sizes = [sizes()]; globalThis.matchMedia = window.matchMedia = () => ({matches: true}); out.sizes.push(sizes()); delete window.matchMedia;
  STAND.seen['12f'] = {w: 7.2, h: 16}; STAND.seen['13f'] = {w: 7.8, h: 17};
  window.devicePixelRatio = 3; out.cells = [standCells(12, 'f', 402)]; window.devicePixelRatio = 1; out.cells.push(standCells(13, 'f', 1020)); delete window.devicePixelRatio;
  out.pad = [STAND.pad, STAND.line];
  out.dialed = [calls.slice(), FD.frame === f, $('feedframe').kids.length, feedWant(), FD.frame.className];
  word({state: 'up'}); out.stale = FD.up; word({session: 'c12', state: 'up'}); word({session: 'c12', state: 'drawn'});
  calls.length = 0; const back2 = show('c6'); out.back6 = [arLine.shown, FD.frame.className, $('feedstand').hidden, calls.slice()]; await back2; out.one = calls.filter(c => c.startsWith('dial')).length;
  word({state: 'up'}); word({state: 'drawn'});
  // the session ends: its last screen stays, with what to do over the box
  FD.foot = null; arLine.keep = () => 'its goodbye';
  word({state: 'down'}); answers.c6 = {ok: false, mode: 'none', live: false, link: 'https://claude.ai/code/x', resume: true, out: 'c6 is not up'};
  timers.filter(t => t.ms === 250).pop().f(); await settle(); out.ended = [at().slice(0, 2), feedHTML('c6'), feedEnd('c6'), arLine.shown, feedWant(), $('feedline').hidden];
  arLine.keep = () => 'screen of ' + FD.n;
  answers.s3 = {ok: false, mode: 'none', live: false, out: 'x'}; await show('s3'); out.idle = feedHTML('s3');
  answers.s4 = {ok: false, mode: 'none', live: true, out: 's4 runs headless'}; await show('s4'); out.none = [at(), feedHTML('s4')];
  answers.c9 = {ok: false, mode: 'install', out: 'ttyd is not installed: install it with winget install tsl0922.ttyd and', cmd: 'winget install tsl0922.ttyd'}; S.snap.ttyd_install = answers.c9.cmd; await show('c9'); out.install = [at(), feedHTML('c9')];
  answers.c10 = {ok: false, mode: 'install', out: 'install it (the list)', cmd: ''}; await show('c10'); out.nocmd = feedHTML('c10');
  answers.c8 = {ok: false, mode: 'none', live: false, out: 'x'}; await show('c8'); out.starting = feedHTML('c8');
  answers.c8 = {ok: true, look: 'dark'}; timers.filter(t => t.ms === 3000).pop().f(); await settle(); out.started = at();
  await show('@k'); out.stand = [at(), feedHTML('@k')];
  // out of sight a while: the frame goes, so the session has its other viewers' size; back: it comes again
  await show('c8'); document.hidden = true; calls.length = 0; docOn.visibilitychange(); timers.filter(t => t.ms === 15000).pop().f(); out.away = [calls.slice(), $('feedframe').kids.length, feedWant()];
  document.hidden = false; docOn.visibilitychange(); await settle(); out.back = [calls.slice(), feedWant()];
  // F206a: frozen before its timer ran, its socket still open in name: dialed again
  word({session: 'c8', state: 'up'}); document.hidden = true; docOn.visibilitychange(); FD.hid -= 20000; document.hidden = false; calls.length = 0;
  docOn.visibilitychange(); await settle(); out.frozen = calls.slice();
  word({session: 'c8', state: 'up'}); document.hidden = true; docOn.visibilitychange(); document.hidden = false; calls.length = 0; docOn.visibilitychange(); out.glance = calls.slice();
  fetch = async () => ({json: async () => { throw new TypeError('cut') }}); await liveGet('c8'); out.cut = FD.deaf > 0; fetch = fetch0;
  await show(null); out.home = at();
  console.log(JSON.stringify(out));
})();`);
"""


def test_session_feed_f114(tmp: Path) -> None:
    """F114: a chat or slot shows the real session (one ttyd frame for the open chat) with the message box under it and
    no thread of the page's own; a starting, ended or terminal-less one says so; the key row types into it."""
    page = W.PAGE.read_text(encoding='utf-8')
    order = [page.index(x) for x in ('<div class="body" id="body">', '<div class="feed" id="feed" hidden>', '<div class="dock" id="dock">')]
    eq(order, sorted(order), 'the session stands between the header and the message box')
    check("dock=(isNew(n)?'':feedEnd(n)+sessRow(n)+keysRow())+box(" in page and 'convo(n)' not in page.split('function render(', 1)[1].split('\n}\n', 1)[0],
          'a chat draws its box, and no thread')
    check('touch-action:pinch-zoom' in page and '@media (pointer:coarse){.feedtouch{display:block} .keyb{display:inline-flex}' in page,
          'a touch device has the touch layer and the key row')
    head = W.session_frame.with_head(b'<html><head><title>t</title>', 'c6', 'dark').decode()
    check(head.startswith('<html><head><meta name="referrer"') and 'if(pressed&&!touch)focus.call' in head and 'name="c6"' in head,
          "ttyd's page takes the keyboard only from a mouse press in it", head[:300])
    (tmp / '.claude').mkdir()
    eq(W.session_frame.session_look(tmp), 'dark', 'no theme set: dark')
    (tmp / '.claude' / 'settings.json').write_text('{"theme": "light-daltonized"}', encoding='utf-8')
    eq(W.session_frame.session_look(tmp), 'light', "a light theme of the agent's: a light ground")
    if not shutil.which('node'):
        print('  (no node here: the session feed script test is skipped)')
        return
    (tmp / 'driver.js').write_text(FEED_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs the session feed', r.stderr[-1500:])
    if r.returncode:
        return
    o = json.loads(r.stdout)
    eq(o['c6'][:2], [True, False], 'a chat shows the session, not the body')
    check(len(o['c6'][2]) == 1 and o['c6'][2][0].startswith('t/TOK/c6/'), "c6's own terminal, on the page's address", o['c6'])
    eq((o['waits'], o['once'], o['up']), ([True, False, False, 'blank', True], 1, [True, False]),
       'F206: until it is drawn a line moves and no blank frame shows; a redraw keeps the one frame')
    eq(o['long'], [False, True], 'after 5 s it says it is connecting')
    eq(o['drawn'], ['', True, True, True], 'drawn: the terminal, and nothing over it')
    eq(o['down'], ['screen of c6', '', False, True, True], 'F206: the connection breaks: its screen stays under the line, and it tries again soon')
    eq(o['lost'], [[True, False, ['t/TOK/c6/?fontSize=13']], ['dial c6 '], 'screen of c6'], 'by itself, with no page load, though the run cannot be asked')
    check('Reconnecting…' in o['re'], 'after 5 s it says so', o['re'])
    eq(o['again'], [None, True, True], 'the terminal again, in the same frame')
    eq((o['quiet4'], o['heard']), (True, True), 'F206a: nothing yet before 5 s, nor while the session sends')
    eq(o['mute'], [False, True, '', None, None], 'F206a: a silent network: the line and Reconnecting…, its screen as it is, and no second question')
    eq(o['gave'], [True, None, False], 'the question is given up, and it still says so')
    eq(o['unmute'], [['hang', 'dial c6 '], 'screen of c6', False, 0], 'the first answer dials again, its screen kept, still saying so')
    eq((o['unmuted'], o['answered']), ([True, True], 0), 'drawn: nothing over it, and a run that answers is not silent')
    eq((o['frozen'], o['glance'], o['cut']), (['hang', 'dial c8 dark'], [], True),
       'F206a: back after a long freeze it dials again, after a glance away not; a body cut off is no answer')
    check('t.onRender(feedSee)' in page and "st==='loading'&&sessionOf(n)" in page,
          'F206a: placed in the frame that draws it, and the chips there from the first frame')
    eq(o['woke'], [True, 0, True], 'back from a locked phone: no old question counts')
    eq(o['other'][0], False, 'a chat not seen here: its latest messages stand in')
    check('Hi  ' in o['other'][1] and 'Hello back' in o['other'][1] and 'ls' not in o['other'][1], 'your words and the replies', o['other'][1])
    eq(o['sizes'], [['13', '13'], ['12', '12']], "B819: the stand-in's text size is feedSrc's, on touch too")
    eq([(c['cols'], round(c['cell'], 2)) for c in o['cells']], [(49, 20.67), (125, 22)], 'its columns and rows, as Chromium has them at 402px and on a desktop')
    eq(o['pad'], [int(W.session_frame.PAD.split()[1].removesuffix('px')), float(W.session_frame.LINE_HEIGHT)], "and the frame's own padding and line height")
    check('padding:0 14px' in page and '.main.term .msgs{font:14px/1.55' in page, 'its left edge; the other messages keep their look')
    got = logic_js([['pastLines', [{'kind': 'say', 'text': 'Two parts:\n- **one** that is long enough to wrap\n- two\n\nLast.\n\n- x'}], 24]])[0]
    eq([x['t'] for x in got], ['', '● Two parts:', '  - one that is long', '    enough to wrap', '  - two', '', '  Last.', '', '  - x'],
       'B819: as Claude Code 2.1.332 draws a list: right under its words, and hung')
    eq((o['other'][2], o['dialed']), ('', [['hang', 'dial c12 page-dark'], True, 1, 'c12', 'blank']), 'the one frame, connected to it')
    eq(o['stale'], False, "a word of the chat before is nothing")
    eq((o['back6'], o['one']), (['screen of c6', '', True, ['hang', 'dial c6 ']], 1), 'back: its last screen at once, and one dial, before the run answers')
    eq((len(o['early']), o['foreign']), (1, False), 'a key before it is connected says so; a word from elsewhere is nothing')
    eq(o['keys'], ['\x1b', '\t', '\x1b[A', '\r', '\x03', '\x1b[D', '\x1b[B', '\x1b[C'], 'the key row types its keys')
    eq(o['app'], ['\x1bOA'], 'as the terminal would, in application cursor mode')
    eq(o['text'], ['one\ntwo', ['text']], "the screen's text in a sheet, to copy")
    eq(o['files'], 'pic', 'files dropped on the session are attached')
    eq((o['ended'][0], o['ended'][3:]), ([True, False], ['screen of c6', '', True]), 'ended: its last screen stays, not its goodbye, and it is not connected')
    check('This chat has ended' in o['ended'][2] and 'class="col' not in o['ended'][2], 'with the card over its box', o['ended'][2])
    for part in ('This chat has ended', 'https://claude.ai/code/x', 'data-resume="c6"'):
        check(part in o['ended'][1], f'ended says {part}', o['ended'][1])
    check('data-ctl="resume" data-tid="F1"' in o['idle'], 'a slot whose task was cut off: Resume', o['idle'])
    check('s4 runs headless' in o['none'][1] and o['none'][0][:2] == [False, True], 'no terminal: why', o['none'])
    check('ttyd is not installed' in o['install'][1] and o['install'][0][:2] == [False, True], 'no ttyd: how to install it', o['install'])
    check(o['install'][1].count('winget install') == 1 and '<code>winget install tsl0922.ttyd</code>' in o['install'][1], 'B761: the command once, as code', o['install'])
    check('install it (the list)' in o['nocmd'] and '<code>' not in o['nocmd'], 'B761: with no command, the list as it is', o['nocmd'])
    check('Starting the chat' in o['starting'], 'a starting chat says so', o['starting'])
    check(o['started'][0], 'then shows its session', o['started'])
    check('WAITS' in o['stand'][1] and o['stand'][0][:2] == [False, True], "a stand-in shows what waits for it", o['stand'])
    eq((o['away'], o['back']), ([['hang'], 1, ''], [['hang', 'dial c8 dark'], 'c8']), 'out of sight it hangs up, the frame stays; back, it dials again')
    eq(o['home'][:2], [False, True], 'another view has no session')


def test_switcher_f206(tmp: Path) -> None:
    """F206: a chat's last line in the title's switcher, the stand-in's messages, and how many screens are kept."""
    page = W.PAGE.read_text(encoding='utf-8')
    check('data-chats aria-haspopup="dialog"' in page and 'SHEETS.chats=chatsSheet' in page, "a chat's title opens the switcher")
    check('viewTransitionName' not in page and '||S.thread&&n!==S.thread){go();return}' in page, 'a switch is at once: no title flies')
    if not shutil.which('node'):
        return
    say, you, tool = {'kind': 'say', 'text': 'One\n\nTwo\n'}, {'kind': 'you', 'text': 'Go\non'}, {'kind': 'tool', 'text': 'Read x'}
    got = logic_js([['chatLast', [you, say], False], ['chatLast', [say, you], False], ['chatLast', [say, tool, {'kind': 'out', 'text': 'o'}], True],
                    ['chatLast', [say, tool], False], ['chatLast', None, True], ['standMsgs', [tool, you, say] * 5]])
    eq(got[:5], ['Two', 'You: Go', 'Working: Read x', 'Two', ''], 'the last line')
    eq([m['w'] for m in got[5]], ['u', 'a'] * 4, 'the latest messages')
    js = page.split('<script id="logic">', 1)[1].split('</script>', 1)[0] + (
        "\nconst k=new Map();for(let i=0;i<14;i++)keptPut(k,'c'+i,i);console.log(JSON.stringify([keptPut(k,'c2','x'),k.get('c2')]))")
    (tmp / 'k.js').write_text(js, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'k.js')], capture_output=True, text=True, timeout=60)
    names, two = json.loads(r.stdout or '[[], 0]')
    eq((len(names), names[0], names[-1], two), (12, 'c3', 'c2', 'x'), 'the last 12 chats, the newest kept longest')


def test_session_proxy_f114(tmp: Path) -> None:
    """F114: /t/TOKEN/NAME/ is ttyd's page and WebSocket on the page's own address, with the token only; /terminal/NAME
    says why there is none, with the link and whether it can be resumed, and resume_chat reopens it."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import socket
    fake_repo(tmp)

    class Ttyd(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.headers.get('Upgrade'):
                self.send_response(101)
                self.end_headers()
                self.close_connection = True
                while data := self.rfile.read1(99):
                    self.wfile.write(b'echo:' + data)
                return
            data = b'<html><head><title>x</title></head>' + self.path.encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
    ttyd = ThreadingHTTPServer(('127.0.0.1', 0), Ttyd)
    ttyd.daemon_threads = True
    threading.Thread(target=ttyd.serve_forever, daemon=True).start()
    token = W.web_token()
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {})
    port = srv.server_address[1]
    base = f'http://127.0.0.1:{port}'
    try:
        with mock.patch.object(srv.terms, 'ttyd', lambda name, sock='': {'ok': True, 'port': ttyd.server_address[1]}):
            code, body = get(f'{base}/t/{token}/c6/?fontSize=12')
            check(code == 200 and b'name="c6"' in body and f'/t/{token}/c6/?fontSize=12'.encode() in body, "ttyd's page", body[-200:])
            with urllib.request.urlopen(urllib.request.Request(f'{base}/t/{token}/c6/?fontSize=12', headers={'Accept-Encoding': 'gzip'}), timeout=10) as r:
                tag, zipped = r.headers['ETag'], r.read()
                eq((r.headers['Content-Encoding'], r.headers['Cache-Control'], gzip.decompress(zipped)), ('gzip', 'private, no-cache', body),
                   'F206: compressed, and kept by the browser')
            eq(get(f'{base}/t/{token}/c6/?fontSize=12', {'If-None-Match': tag}), (304, b''), 'which asks each time, and gets it only when it changed')
            eq(get(f'{base}/t/wrong/c6/', {'If-None-Match': tag})[0], 403, 'never without the token')
            eq(get(f'{base}/t/wrong/c6/')[0], 403, 'only with the token')
            eq(get(f'{base}/t/{token}/x')[0], 403, 'no name: refused')
            eq(get(f'{base}/t/{token}/..x/')[0], 404, 'not a session name')
            with socket.create_connection(('127.0.0.1', port), timeout=10) as c:
                c.sendall(f'GET /t/{token}/c6/ws HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n'.encode())
                got = b''
                while b'\r\n\r\n' not in got:
                    got += c.recv(999)
                check(got.startswith(b'HTTP/1.1 101') or b' 101 ' in got[:20], 'its WebSocket', got[:60])
                c.sendall(b'hi')
                back = b''
                while len(back) < 7 and (d := c.recv(99)):
                    back += d
                eq(back, b'echo:hi', 'flows both ways')
        with mock.patch.object(W, 'resumable', return_value='sid'), mock.patch.object(U, '_bridge_link', return_value='L'), \
                mock.patch.object(W.shutil, 'which', return_value='ttyd'):
            r = json.loads(get(f'{base}/terminal/c6?t={token}')[1])
            eq((r['ok'], r['live'], r['link'], r['resume']), (False, False, 'L', True), 'an ended chat: its link and Resume')
            with mock.patch.object(W.shutil, 'which', return_value=None):
                r = json.loads(get(f'{base}/terminal/c6?t={token}')[1])
            eq((r['mode'], r['resume']), ('none', True), 'without ttyd too')
            with mock.patch('agent_runner.control_reopen.reopen_control', return_value='x') as ro:
                out = post(f'{base}/act?t={token}', {'name': 'resume_chat', 'args': {'chat': 'c6'}})[1]
            eq((out['ok'], ro.call_args[0]), (True, (6, 'sid')), 'resume_chat reopens its conversation')
        check(not U.act('resume_chat', chat='s1')['ok'] and not U.act('resume_chat', chat='../x')['ok'], 'not a slot, not a path')
        with mock.patch.object(W, 'session_live', return_value=True), mock.patch.object(W, 'headless', return_value=True):
            check('headless' in W.no_session('s2')['out'], 'a headless slot says so')
    finally:
        srv.stop()
        ttyd.shutdown()
        ttyd.server_close()


F170_IDLE = ['● done', '', '✻ Worked for 1s', '                Update available · run mise upgrade claude', '─' * 60, '❯ ', '─' * 60,
             '  [PONYTAIL]', '  ⏵⏵ bypass permissions on (shift+tab to cycle) · 1 shell · ← 2 agents']


def test_session_controls_f170(tmp: Path) -> None:
    """F170: the lines at the bottom of Claude's window are read off its screen and become chips; a menu or a question
    hides nothing; the frame's place never depends on the bars; the look is the run's own theme."""
    if not shutil.which('node'):
        print('  (no node here: the session controls script test is skipped)')
        return
    typed = [*F170_IDLE[:5], '❯ some words', *F170_IDLE[6:]]
    bash = [*F170_IDLE[:5], '! ', '─' * 60, '  ! for shell mode']
    work = ['● Simmering… (3s · esc)', '─' * 40 + ' my chat ──', '❯ ', '─' * 60, '  ⏸ plan mode on · esc to interrupt']
    menu = ['▔' * 60, '  Select model', '  ❯ 1. Opus', '    2. Haiku', '  Enter to save · Esc to cancel']
    ask = ['─' * 60, 'Do you want to proceed?', '❯ 1. Yes', '  2. No', '', 'Esc to cancel']
    listed = ['  Background', '  2 background tasks', '    Shells', '  ❯ ● python3 run_tests.py     running', '',
              '    Background agents', '    ● Tester: run…   running · Haiku', '  x to stop · Esc to close']
    spot = {'main': 800, 'bar': 60, 'dock': 180, 'row': 28, 'high': 900, 'pad': 12, 'cell': 20, 'foot': {'top': 38}, 'short': 0, 'off': 0}
    live = {'tasks': [{'kind': 'shell', 'running': True}, {'kind': 'shell', 'running': False}], 'mode': 'plan'}
    got = logic_js([['feedFoot', F170_IDLE, None], ['feedFoot', typed, None], ['feedFoot', bash, None], ['feedFoot', work, None],
                    ['feedFoot', menu, None], ['feedFoot', ask, None], ['feedFoot', ['hi'], None], ['taskLines', listed],
                    ['feedSpot', spot], ['feedSpot', {**spot, 'off': 9999}], ['feedSpot', {**spot, 'dock': 260}],
                    ['feedSpot', {**spot, 'short': 5}], ['feedSpot', {**spot, 'foot': None}], ['feedSpot', {**spot, 'whole': True}],
                    ['sessionChips', {'foot': None, 'live': live, 'working': True}],
                    ['sessionChips', {'foot': {'mode': 'bypassPermissions', 'update': 'x', 'agents': 2}, 'live': {}}],
                    ['sessionChips', {}], ['forWords', 72], ['forWords', 3720]])
    f = got[0]
    eq([f[k] for k in ('top', 'end', 'text', 'mode', 'shells', 'agents', 'update', 'status', 'work')],
       [3, 6, '', 'bypassPermissions', 1, 2, 'mise upgrade claude', ['[PONYTAIL]'], False], 'every line is read')
    eq((got[1]['text'], got[2]['bash']), ('some words', True), 'unsent words, and shell mode, are seen')
    eq((got[3]['work'], got[3]['mode'], got[3]['top']), (True, 'plan', 1), 'working; a session name on the rule')
    eq(got[4:7], [None, None, None], 'a menu, a question, no prompt: nothing is hidden')
    eq([(x['name'], x['on'], x['running']) for x in got[7]],
       [('python3 run_tests.py', True, True), ('Tester: run', False, True)], "Claude Code's own task list")
    eq(got[8], {'t': -152, 'off': 0, 'far': 152, 'cut': 128}, 'at rest the words end on the box')
    eq(got[9]['t'], 0, 'scrolled down all the way, they end on the slim message box')
    eq(got[10], {'t': -232, 'off': 0, 'far': 232, 'cut': 128}, 'a box that grows moves the frame: its size stays')
    eq((got[11]['t'], got[11]['far']), (60, 0), 'B786: a short chat starts under the top bar, with nothing to pull')
    eq((got[12], got[13]), ({'t': -280, 'off': 0, 'far': 0, 'cut': 0}, {'t': -280, 'off': 0, 'far': 0, 'cut': 0}), 'nothing is cut while all shows')
    eq([c['label'] for c in got[14]], ['Working', 'Plan', '1 shell'], 'only what runs')
    eq([c['label'] for c in got[15]], ['Bypass', '2 agents', 'Update'], 'what the screen says')
    eq(([c['label'] for c in got[16]], got[17], got[18]), (['Session'], '1m 12s', '1h 2m'), 'nothing known; a clock')
    page = W.PAGE.read_text(encoding='utf-8')
    check('data-halt' in page and page.count('force:true') == 1 and "{text:'',to,force:true" in page,
          'F190a: Stop while it works; F190c: only what is queued is forced')
    check('if(!same){render();sendRedraw()}' in page and '\n  send(e.submitter)});' in page, 'F190c: the arrow follows what is queued; a press says so')
    check('act force' not in page and '>Force send<' not in page and page.count('data-send aria-label="Send" title="Send">${I.send}') == 1,
          'B208: one Send arrow, never a wide text button')
    check('\n  sendDraw(ta);' in page.split('function grow(', 1)[1][:60], 'F205: it follows the attachments')
    check('lineHeight=1.3' in W.session_frame.ttyd_options('dark') and 'minimumContrastRatio=4.5' in W.session_frame.ttyd_options('dark'),
          'room between the lines, text that reads')
    head = W.session_frame.with_head(b'<head>', 'c6', 'page').decode()
    check('"light":{' in head and '"dark":{' in head and 'look="page"' in head and 'ar-box' in head, 'a themed session: both looks', head[:200])
    check('look="light"' in W.session_frame.with_head(b'<head>', 'c6', 'light').decode(), 'one from before: its one ground')
    check('"page-light":{' in head and '"page-dark":{' in head, 'F206: every look, as the page outlives one chat')


def test_bars_over_text_b192(tmp: Path) -> None:
    """B192: in a chat the bars only go over the text. The session's frame moves by a scroll alone, its share of it and
    the session's are the whole scroll, and it is at rest again at the session's end; one slim row stands for the box."""
    page = W.PAGE.read_text(encoding='utf-8')
    for gone in ('FD.pulling', '#feedframe.glide', 'data-strip', 'feedSettle'):
        check(gone not in page, f'no {gone}: the bars never move the frame')
    check('.main.sess.slim .dockwrap{pointer-events:none}' in page, 'a touch where the box was is the session\'s')
    bar = '.main.sess.slim .top:not(:has(:focus-visible))'
    check(bar + '{transform:translateY(calc(-1*var(--slimtop,100%) - env(safe-area-inset-top,0px)));opacity:0;pointer-events:none}' in page
          and bar + '>:not(.menu){visibility:hidden}' in page,
          'B215: the menu fades with the bar and takes no taps, keyboard focus on it shows the bar')
    eq(page.count('.main.sess.slim .top'), page.count(bar), 'B215: no other rule keeps a control over the text')
    slow = lambda *ps: ','.join(f'{p} var(--dur-bars) var(--ease)' for p in ps)  # noqa: E731
    check('--dur-slow:250ms; --dur-bars:400ms;' in page, 'B218a: the bars have a duration of their own')
    bars = page[page.index("/* B218: the bars' one motion"):page.index('.main.sess.still :is(')]
    eq('--dur-slow' in bars, False, 'B218a: top and bottom on the same one')
    check('opacity calc(var(--dur-bars)*.6)' in bars and 'transition-delay:calc(var(--dur-bars)*.4)' in bars, 'B218a: the inner fade in proportion')
    for rule, what in (('.main.sess .top{transition:' + slow('transform', 'opacity') + '}', 'the top bar'),
                       ('.main.sess .notices{transition:' + slow('transform', 'opacity') + ',visibility var(--dur-bars)}', "a notice's row"),
                       ('.dock{background:none;background-color:var(--bg);transition:' + slow('translate', 'opacity') + ',', 'the message box'),
                       ('transition:' + slow('translate', 'opacity') + ',visibility var(--dur-bars)}', 'the slim box')):
        check(rule in page, f'B218: {what} goes and comes on the one motion', rule)
    check('.main.sess.slim .notices{transform:translateY(calc(-1*var(--slimtop' in page, 'B218: a notice goes with the top bar, as one')
    up = '.main.sess:is(.pulled,:has(.feedpast.up)) .dockwrap'
    check(up + ' .dock{background-color:transparent;transition-delay:0s}' in page and up + '{pointer-events:none}' in page,
          'B789: scrolled up, nothing is drawn behind the chips and the box, and a press between them is the text\'s')
    check(':is(.dock>:not(.schips,.keys,.gone0),:is(.schips,.keys)>*,.slimground){pointer-events:auto}' in page, 'B789: each chip and the box take theirs')
    check('.schips .chip{flex:none;background:var(--surface)' in page and '.box{background:var(--surface)' in page, 'B789: each on its own fill')
    ground = page.split('\n.slimground{', 1)[1].split('}', 1)[0]
    check('height:calc(var(--slimgap,14px) + var(--r-xl));background:var(--bg);opacity:1;transition:opacity var(--dur-bars) var(--ease)' in ground
          and '.main.sess.slim .slimground{opacity:0}' in page and 'slimgrow' not in page,
          'B789: a ground under the foot line alone, and none behind the slim box', ground)
    check('.main.sess.slim .slimbox>div{pointer-events:auto}' in page, 'B789: a press beside the slim box is the text\'s')
    check("classList.toggle('pulled',at.off>0)" in page, 'B789: the frame pulled down counts as scrolled up')
    check('.main.sess.still :is(' in page and "toggle('still',calm())" in page, 'B218: at once under calm()')
    check('d.inert=FD.shown&&FD.slim;row.inert=!FD.slim' in page and 'slimSize();FD.slim=on' in page, 'B218: only the one that shows takes a tap; measured before it moves')
    row = page[page.index('function slimDraw('):]
    row = row.split('function workDraw')[0]
    check(all(x in row for x in ('data-slimbox', 'data-halt', 'data-sheet="sesswork"')) and 'schips' not in row and 'data-clip' not in row,
          'the slim message box: its words, Working and Stop, no chips or options', row)
    if not shutil.which('node'):
        print('  (no node here: the bars script test is skipped)')
        return
    spot = {'main': 800, 'bar': 60, 'dock': 180, 'row': 56, 'high': 900, 'pad': 12, 'cell': 20, 'foot': {'top': 38}, 'short': 0, 'off': 0}
    up = {'off': 0, 'far': 124, 'jump': True, 'slim': True}
    pill = lambda words: [*F170_IDLE[:2], words, '', *F170_IDLE[4:]]
    got = logic_js([['feedSpot', {**spot, 'hold': -100}], ['feedSpot', {**spot, 'hold': -100, 'dock': 260}], ['feedSpot', {**spot, 'hold': -28, 'dock': 260}],
                    ['feedSpot', {**spot, 'hold': None}],
                    ['feedShare', -10, {**up, 'jump': False}], ['feedShare', -10, {**up, 'slim': False}], ['feedShare', -10, up],
                    ['feedShare', -10, {**up, 'off': 120}], ['feedShare', 10, {**up, 'off': 120, 'slim': False}], ['feedShare', 10, {**up, 'off': 4}],
                    ['feedShare', 10, up],
                    ['feedBars', -5, {'slim': False, 'run': 0}], ['feedBars', -5, {'slim': False, 'run': -5}], ['feedBars', 5, {'slim': True, 'run': -40}],
                    ['feedBars', 5, {'slim': True, 'run': 5}],
                    ['feedFoot', pill('● done       Jump to bottom (ctrl+End) ↓'), None], ['feedFoot', pill('● done   2 new messages (ctrl+End) ↓'), None],
                    ['feedFoot', pill('the Jump to bottom pill'), None], ['feedFoot', F170_IDLE, None]])
    eq([x['t'] for x in got[:4]], [-100, -100, -28, -152], 'scrolled up its place stays, a grown box or not; at the end it rests on the box')
    eq((got[0]['off'], got[1]['off']), (52, 132), 'and how far that is from rest is known')
    eq(got[4:11], [0, 0, -10, -4, 10, 4, 0], 'up: the session first, then the frame; down: the frame first, and no pixel twice')
    eq([x['slim'] for x in got[11:15]], [False, True, True, False], 'away 8px up, back 8px down')
    eq([x['jump'] for x in got[15:19]], [True, True, False, False], "scrolled up, as Claude Code's pill says it, new words too")
    driver = page.split('<script id="logic">', 1)[1].split('</script>', 1)[0] + r"""
// a whole scroll over a session that takes rows: how far a line went is how far the finger went, at every step
const ROW = 20; let FD = {off: 0, far: 124, jump: false, slim: false, run: 0}, rest = 0, hist = 0, frame = 0, bad = 0, finger = 0;
function scroll(px) {
  finger += px;
  const b = feedBars(px, FD); FD.run = b.run; if (b.slim !== FD.slim && (!b.slim || FD.jump)) FD.slim = b.slim;
  const take = feedShare(px, FD); FD.off -= take; frame -= take;
  const [n, left] = feedSteps(rest + px - take, ROW); rest = left; hist -= n * ROW; FD.jump = hist > 0;
  if (Math.abs(-finger - (hist + frame)) >= ROW) bad++;
}
for (let i = 0; i < 100; i++) scroll(-4);
const top = {slim: FD.slim, off: FD.off, hist};
for (let i = 0; i < 100; i++) scroll(4);
console.log(JSON.stringify({bad, top, end: {slim: FD.slim, off: FD.off, hist, frame}}));
"""
    f = tmp / 'b192.js'
    f.write_text(driver, encoding='utf-8')
    r = subprocess.run(['node', str(f)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs the scroll', r.stderr[-800:])
    out = json.loads(r.stdout or '{}')
    eq(out.get('bad'), 0, 'a line is never a row off the finger')
    eq((out.get('top') or {}).get('slim'), True, 'scrolled up, the bars are away')
    eq((out.get('top') or {}).get('off'), 124, 'and the lines fill the room')
    eq(out.get('end'), {'slim': False, 'off': 0, 'hist': 0, 'frame': 0}, 'back at the end all is at rest')


def test_phone_screen_b194(tmp: Path) -> None:
    """B194: a narrow window: the rule over the prompt is mostly the session's name, and the pill is drawn over the
    middle of a line. Neither makes the page show the agent CLI's own input, and words in an answer are not them."""
    if not shutil.which('node'):
        print('  (no node here: the phone screen test is skipped)')
        return
    shot = ['● Built, landed and live: F149 (the run page', '  keeps it Jump to bottom (ctrl+End) ↓ :09.', '',
            '─────── agent-runner · F149 · page auto-update ─', '❯', '─' * 48, '  [PONYTAIL]', '  ⏵⏵ bypass permissions on · ← 2 agents']
    rule = lambda l, w=48: [*shot[:3], l, '❯ ', '─' * w, *shot[6:]]
    over = lambda label, w=48: ('x' * w)[:(w - len(label) - 2) // 2] + f' {label} ' + 'tail of line'
    pill = lambda l, w=48: ['● ok', l, '', '─' * w, '❯ ', '─' * w, '  ⏵⏵ auto mode on']
    labels = ['Jump to bottom (ctrl+End) ↓', '1 new message (ctrl+End) ↓', '12 new messages (ctrl+End) ↓', 'Waiting for your answer (ctrl+End) ↓',
              'Jump to bottom ↓', 'Jump to bottom (click) ↓', 'Jump to bottom · fn+↓ to scroll']
    # what Claude Code 2.1.331 draws at 48 and 34 columns
    names = [(' agent-runner · F149 · page auto-update and m… ─', 48), (' agent-runner · F149 · page aut… ─', 34),
             ('────── agent-runner · F149 · page auto-updates ─', 48), ('── agent-runner · F149 · page auto-update soon ─', 48),
             (' 日本語の長い名前の会話がここにあります日本語… ─', 48), ('─' * 43 + ' c3 ─', 48), (' 🇬🇧 👨\u200d👩\u200d👧 ' + 'n' * 37 + '… ─', 48), (' 日本語の長い名前の会話がここに… ─', 34)]
    table = ['● x', ' Name │ Value', '───────┼──────── long words in the table here ─', '  a │ b', '', '─' * 48, '  more']
    md = ['● x', '', '─' * 48, '', '  words of an answer', ' a line that ends with a dash ─', '  more words', '─' * 48, '  more']
    short = [*shot[:3], ' not as wide as the window ─', '❯ ', '─' * 48]
    typed = [*shot[:4], '❯ own words', '  second ─', '─' * 48, *shot[6:]]
    jumps = [over(x) for x in labels]
    no = ['  the Jump to bottom (ctrl+End) ↓ pill is there', '  Jump to bottom (ctrl+End) ↓ goes to the end', '  a Jump to bottom pill in the middle, no more',
          '           Jump to bottom (ctrl+End) is words']
    got = logic_js([['feedFoot', x, None] for x in [shot, *(rule(*n) for n in names), table, md, short, typed,
                                                    *(pill(x) for x in jumps), *(pill(x) for x in no),
                                                    pill('  日本語 Jump to bottom (ctrl+End) ↓ 語'.replace('語 J', '語x J')),
                                                    [*pill('')[:2], over(labels[2]), *pill('')[3:]]]])
    eq([got[0][k] for k in ('top', 'end', 'text', 'mode', 'agents', 'jump')], [3, 5, '', 'bypassPermissions', 2, True], "the screenshot's own lines")
    i = 1 + len(names)
    eq([(f or {}).get('top') for f in got[1:i]], [3] * len(names), 'a longer name, a cut one, a wide one, a short one')
    eq(got[i:i + 3], [None, None, None], 'a table, a markdown rule or a narrower line is not the prompt')
    eq((got[i + 3]['top'], got[i + 3]['text']), (3, 'own words\n  second ─'), 'unsent words that end in a dash are words')
    i += 4
    eq([f['jump'] for f in got[i:i + len(jumps)]], [True] * len(jumps), 'the pill over the middle of a line, in each wording')
    i += len(jumps)
    eq([f['jump'] for f in got[i:i + len(no)]], [False] * len(no), 'words that only mention it')
    i += len(no)
    eq(got[i]['jump'], True, 'over a line of wide letters')
    eq((got[i + 1]['jump'], got[i + 1]['top']), (True, 3), "right over the rule it is the pill, not Claude Code's note")
    driver = W.PAGE.read_text(encoding='utf-8').split('<script id="logic">', 1)[1].split('</script>', 1)[0] + f'''
const l = {json.dumps(shot)}; console.log(JSON.stringify([() => false, (y, x) => y === 1 && x >= 10 && x < 39].map(lit => feedFoot(l, null, lit).jump)))'''
    (tmp / 'b194.js').write_text(driver, encoding='utf-8')
    run = subprocess.run(['node', str(tmp / 'b194.js')], capture_output=True, text=True, timeout=60)
    eq(run.stdout.strip(), '[false,true]', "the same words with no ground of the pill's own are an answer's")


def test_frame_typing_b190(tmp: Path) -> None:
    """B190: with the keyboard in the session's frame, what is typed or pasted goes to the message box while the agent
    CLI's input is hidden, Shift+Enter a new line there; with words in its prompt Shift+Enter is a new line in it; a
    menu, a question and every other key are the session's."""
    head = W.session_frame.with_head(b'<head>', 'c6', 'page').decode()
    check("addEventListener('keydown'" in head and "addEventListener('paste'" in head and 'parent.feedTyped(e,paste)' in head,
          "the frame asks the page before ttyd's own script", head[-900:])
    if not shutil.which('node'):
        print('  (no node here: the frame typing test is skipped)')
        return
    page = W.PAGE.read_text(encoding='utf-8')
    typed = page[page.index('function feedTyped('):]
    typed = typed[:typed.index('\n}\n') + 3]
    js = page.split('<script id="logic">', 1)[1].split('</script>', 1)[0]
    driver = js + '\n' + typed + r"""
let sent = [], inputs = 0, focused = 0;
const S = {sheet: ''}, FD = {foot: {text: '', bash: false}, whole: false, slim: true};
const ta = {value: 'ab', selectionStart: 1, selectionEnd: 1, focus() { focused++ }, dispatchEvent() { inputs++ },
  setRangeText(t, a, b) { this.value = this.value.slice(0, a) + t + this.value.slice(b); this.selectionStart = this.selectionEnd = a + t.length }};
const document = {querySelector: () => ta}, feedSlim = on => { FD.slim = on }, sessType = x => { sent.push(x); return true };
const pastPress = () => false;  // F191b
const key = (key, o) => feedTyped(Object.assign({key}, o)), SE = ['Enter', {shiftKey: true}], out = {};
out.many = [key('x'), key(...SE), key(...SE), key('/'), feedTyped({}, 'p1\np2'), ta.value, sent.length, inputs, focused, FD.slim];
out.own = [key('Enter'), key('Escape'), key('c', {ctrlKey: true}), key('v', {metaKey: true}), key('Tab', {shiftKey: true}),
  key('x', {isComposing: true}), key('Process', {keyCode: 229}), key('Enter', {shiftKey: true, ctrlKey: true})];
out.altgr = key('@', {ctrlKey: true, altKey: true, getModifierState: k => k === 'AltGraph'});
S.sheet = 'run'; out.sheet = key('x'); S.sheet = '';
FD.foot = feedFoot(['● ok', '● How is Claude doing this session? (optional)', '  1: Bad    2: Fine   3: Good   0: Dismiss', '', '─'.repeat(40), '❯ ', '─'.repeat(40)], null);
out.rate = [key('2'), key(...SE)];
const had = ta.value;
FD.whole = true; FD.foot = {text: 'own words', bash: false};
out.words = [key('x'), key(...SE), feedTyped({}, 'p'), sent];
FD.foot = null; out.menu = [key('x'), key(...SE), key('1'), feedTyped({}, 'p'), sent.length];
FD.whole = false; out.menuNew = [key('x'), key(...SE)];
out.same = ta.value === had;
console.log(JSON.stringify(out));
"""
    f = tmp / 'b190.js'
    f.write_text(driver, encoding='utf-8')
    r = subprocess.run(['node', str(f)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs the page script', r.stderr[-800:])
    out = json.loads(r.stdout or '{}')
    eq(out.get('many'), [True] * 5 + ['ax\n\n/p1\np2b', 0, 5, 5, False], 'hidden: all of it in the message box, the session gets none')
    eq(out.get('own'), [False] * 8, "every other key is the session's")
    eq((out.get('altgr'), out.get('sheet')), (True, False), 'AltGr types; a sheet open: not ours')
    eq(out.get('rate'), [False, True], "a survey's digit is the session's")
    eq(out.get('words'), [False, True, False, ['\n']], 'words in its prompt: Shift+Enter is a new line there')
    eq((out.get('menu'), out.get('menuNew'), out.get('same')), ([False, False, False, False, 1], [False, False], True), 'a menu or a question is untouched')


def test_frame_copy_b845(tmp: Path) -> None:
    """B845: with a session that tracks the mouse, a drag in the frame selects, a click still goes to the session, a right
    click does not, and Ctrl+C copies the selected words, with none it is the session's. Not in the login's terminal."""
    if not shutil.which('node'):
        print('  (no node here: the frame copy test is skipped)')
        return
    driver = r"""
const at = {}, sent = [], out = {};
let picked = '', clip = '', mode = 'drag', mac = MAC, real = true;
globalThis.addEventListener = (t, f) => (at[t] = at[t] || []).push(f);
globalThis.removeEventListener = (t, f) => { at[t] = at[t].filter(x => x !== f) };
globalThis.HTMLElement = class { focus() {} };
globalThis.location = {origin: 'o'}; globalThis.parent = {postMessage() {}}; globalThis.window = globalThis;
globalThis.matchMedia = () => ({matches: false}); globalThis.WebSocket = class {};
Object.defineProperty(globalThis, 'navigator', {value: {platform: mac ? 'MacIntel' : 'Linux x86_64'}});
globalThis.MouseEvent = class { constructor(type, o) { Object.assign(this, o, {type}) } };
globalThis.document = {fonts: {load: () => ({then() {}})}, execCommand() { fire('copy', {clipboardData: {setData: (k, v) => { clip = v }}}) }};
const box = {dispatchEvent(e) { sent.push(e.type + (e.shiftKey ? '+shift' : '') + (e.altKey ? '+alt' : '')); if ((e.shiftKey || e.altKey) && e.type === 'mousedown') picked = 'words' }};
globalThis.term = {element: {contains: () => true, querySelector: () => box}, get modes() { return {mouseTrackingMode: mode} }, focus() {}, textarea: {select() {}},
  hasSelection: () => !!picked, getSelection: () => picked, clearSelection() { picked = '' }};
function fire(type, o) { const e = Object.assign({type, isTrusted: real, target: {}, button: 0, buttons: 0, clientX: 0, clientY: 0, stopped: false,
  preventDefault() {}, stopImmediatePropagation() { this.stopped = true }}, o); for (const f of [...at[type] || []]) { f(e); if (e.stopped) break } return e }
HEADJS
const take = () => sent.splice(0), press = (o, x, y) => { const r = [fire('mousedown', {buttons: 1, ...o}).stopped]; if (x) r.push(fire('mousemove', {buttons: 1, clientX: x}).stopped); r.push(fire('mouseup', {clientX: x || 0, ...o}).stopped); return [r, take()] };
const c = o => { const e = fire('keydown', {keyCode: 67, key: 'c', ctrlKey: true, ...o}); return [e.stopped, clip, picked] };
fire('pointerdown', {pointerType: 'touch'}); out.touch = press({});
fire('pointerdown', {pointerType: 'mouse'});
out.click = press({}); out.jitter = press({}, 3);
out.drag = press({}, 30); out.move = fire('mousemove', {}).stopped;
out.copy = c(); out.held = c({repeat: true}); out.none = c();
picked = 'cmd'; out.cmd = c({ctrlKey: false, metaKey: true});
picked = 'x'; out.shiftC = c({shiftKey: true}); picked = '';
const r = fire('mousedown', {button: 2}); out.right = [r.stopped, !!r.shiftKey, !!r.altKey];
out.own = press({[mac ? 'altKey' : 'shiftKey']: true}, 30);
out.ctrlClick = press({ctrlKey: true}); picked = '';
real = false; out.page = press({}, 30); real = true;
mode = 'none'; out.off = press({}, 30);
console.log(JSON.stringify(out));
"""
    plain = [[False, False], []]
    for mac, name in ((False, 'c6'), (True, 'c6'), (False, 'login')):
        head = W.session_frame.with_head(b'<head>', name, 'dark').decode().split('<script>', 1)[1].split('</script>', 1)[0]
        f = tmp / 'b845.js'
        f.write_text(driver.replace('MAC', json.dumps(mac), 1).replace('HEADJS', head), encoding='utf-8')
        r = subprocess.run(['node', str(f)], capture_output=True, text=True, timeout=60)
        check(r.returncode == 0, "node runs the frame's script", r.stderr[-800:])
        out = json.loads(r.stdout or '{}')
        if name == 'login':
            eq((out.get('click'), out.get('drag'), out.get('right')), (plain, [[False] * 3, []], [False, False, False]), "the login's mouse is untouched")
            eq(out.get('cmd'), [False, '', 'cmd'], "and so are its keys")
            continue
        key = '+alt' if mac else '+shift'
        eq(out.get('touch'), plain, 'touch is untouched')
        eq(out.get('click'), [[True, True], ['mousedown', 'mouseup']], 'a click is held, then sent')
        eq(out.get('jitter'), [[True] * 3, ['mousedown', 'mouseup']], 'a hand that shakes still clicks')
        eq((out.get('drag'), out.get('move')), ([[True, False, False], ['mousedown' + key]], True), 'a drag selects; a bare move keeps the words')
        eq((out.get('copy'), out.get('held'), out.get('none')), ([True, 'words', ''], [True, 'words', ''], [False, 'words', '']),
           "Ctrl+C copies and clears, a held key is no interrupt, the next one is the session's")
        eq((out.get('cmd'), out.get('shiftC')), ([True, 'cmd', ''], [False, 'cmd', 'x']), 'Cmd+C too, not Ctrl+Shift+C')
        eq(out.get('right'), [False, not mac, mac], 'a right click is read as one that selects, so none is sent')
        eq(out.get('own'), [[False] * 3, []], 'a press that selects by itself is untouched')
        eq(out.get('ctrlClick'), [[True, False], []] if mac else [[True, True], ['mousedown', 'mouseup']], "Ctrl+click is a Mac's right click")
        eq((out.get('page'), out.get('off')), ([[False] * 3, []],) * 2, "the page's own clicks and a session that tracks no mouse are untouched")


def test_session_run_side_f170(tmp: Path) -> None:
    """F170: /live, /commands?s=, and which colours a session's frame gets."""
    fake_repo(tmp)
    job = S.C.notes('control6.job')
    S.C.notes('control6.live').write_text('1', encoding='utf-8')
    for spec, look in (({'argv': ['x'], 'look': 'custom:agent-runner'}, 'page'), ({'argv': ['x', '{"theme": "custom:agent-runner"}']}, 'page'),
                       ({'argv': ['x']}, W.session_frame.session_look())):
        job.write_text(json.dumps(spec), encoding='utf-8')
        eq(W.frame_look('c6'), look, f'the look of {spec}')
    token = W.web_token()
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {})
    base = f'http://127.0.0.1:{srv.server_address[1]}'
    try:
        with mock.patch.object(W.session_now, 'session_skills', lambda n: {'ponytail:x': 'Lazy', 'run': 'no'} if n == 'c6' else {}):
            names = [c['name'] for c in json.loads(get(f'{base}/commands?s=c6&t={token}')[1])]
            plain = [c['name'] for c in json.loads(get(f'{base}/commands?t={token}')[1])]
        check('ponytail:x' in names and names.count('run') == 1 and 'ponytail:x' not in plain, "a chat's own skills", names[-5:])
        check({'mcp', 'tasks', 'usage', 'rewind'} <= set(plain), "Claude Code's own commands", plain)
        eq(json.loads(get(f'{base}/live/c9?t={token}')[1])['ok'], False, 'no such session')
        eq(get(f'{base}/live/c9')[0], 403, 'only with the token')
    finally:
        srv.stop()


SEND_WAIT_DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const slice = (a, b) => { const i = page.indexOf(a); if (i < 0) throw Error(a); return page.slice(i, page.indexOf(b, i) + b.length); };
const logic = page.split('<script id="logic">')[1].split('</script>')[0];
const attrs = {}, cls = {}, toggle = (n, on) => { cls[n] = !!on };
const btn = {title: '', classList: {toggle}, setAttribute(k, v) { attrs[k] = v }, removeAttribute(k) { delete attrs[k] }};
const boxEl = {classList: {toggle}, querySelector: () => btn};
const ta = {value: '', style: {}, scrollHeight: 20, offsetHeight: 20, closest: s => s === '.box' ? boxEl : null};
const S = {thread: 'c1', view: 'home', atts: {}}, said = [], asks = [];
let works = false, growGlide = () => {}, toast = t => said.push(t), tq = p => p, plainErr = String;
const FD = {n: 'c1'}, HI = {}, store = {set() {}}, DRAFT_KEY = k => k, sent = [], sentMark = () => {}, histAdd = () => {}, threadTitle = String;
const outbox = (name, args) => sent.push([name, args]);
const boxKey = () => S.thread, isNew = () => false, sessWorks = () => works, document = {querySelector: () => ta};
const render = () => grow(ta, true), fetch = () => new Promise((ok, no) => asks.push({ok: j => ok({json: async () => j}), no}));
const tick = () => new Promise(r => setTimeout(r, 0));
const timers = [], acts = [], act = (name, args) => new Promise(ok => acts.push({name, args, ok}));
let clock = 1e12, lives = 0, liveLoad = () => { lives++ };
Date.now = () => clock;
eval(logic + slice('let boxWas=', '\n}\n') + slice('function sendDraw(', '\n}\n') + slice('const sendHeld=', '\n') + slice('function sendNow(', '\n}\n')
     + slice('function sendRedraw(', '\n') + slice('function sendHold(', '\n').replace('setTimeout(', 'later(') + slice('async function forceQueued(', '\n}\n')
     + slice('async function send(by){', '\n}\n') + slice('async function upload(', '\n}\n') + `
const later = (f, ms) => timers.push([clock + ms, f]);
const pass = ms => { clock += ms; for (const t of timers.splice(0)) if (t[0] <= clock) t[1](); else timers.push(t) };
(async () => {
  const look = () => [attrs['aria-label'], btn.title, attrs['aria-disabled'] || '', !!cls.force, !!cls.has], out = {};
  const start = (v, w) => { S.atts = {}; asks.length = said.length = 0; ta.value = v; works = !!w; upload({name: 'a'}) };
  start(''); out.alone = look(); asks[0].ok({ok: true, path: '/a'}); await tick(); out.aloneUp = look();
  start('hi'); out.words = look(); await send(); out.said = said.slice(); out.kept = [ta.value, S.atts.c1.length];
  asks[0].ok({ok: true, path: '/a'}); await tick(); out.wordsUp = look();
  start(''); asks[0].no('net'); await tick(); out.failed = look();
  start('hi'); asks[0].ok({ok: false, out: 'no'}); await tick(); out.failedWords = look();
  start('hi'); S.atts.c1.splice(0, 1); render(); out.removed = look();
  start('hi', true); out.works = look(); asks[0].ok({ok: true, path: '/a'}); await tick(); out.worksUp = look();
  for (const [k, v, w, a, t] of [['words', 'hi', true, []], ['att', '', true, [{path: '/a'}]], ['idle', 'hi', false, []], ['unsent', 'hi', true, [], 'x']]) {
    S.atts = {c1: a}; ta.value = v; works = w; FD.foot = {text: t || ''}; sent.length = 0; render();
    const l = look(); await send(); out['sent_' + k] = [l, sent.map(x => [x[0], Object.keys(x[1]), x[1].text.includes(v || '/a')])] }
  start('hi'); upload({name: 'b'}); asks[0].ok({ok: true, path: '/a'}); await tick(); out.one = look();
  asks[1].ok({ok: true, path: '/b'}); await tick(); out.both = look();
  start('hi'); S.thread = 'c2'; render(); out.other = look();
  // F190c: a press as the page makes it (the arrow), and an empty Enter (no button)
  const by = {classList: {contains: n => !!cls[n]}}, press = () => send(by), words = v => { ta.value = v; render() };
  const live = q => { FD.live = {status: 'busy', queued: q}; sendRedraw() }, n = () => [sent.length, acts.length];
  S.thread = 'c1'; S.atts = {}; works = true; FD.foot = {text: ''}; sent.length = acts.length = 0; pass(60000); live(0);
  words(''); out.nothing = look(); await press(); out.nothingN = n();
  words('one'); await press(); words(''); out.after = look(); live(1); out.held = look(); await press(); out.heldN = n();
  pass(500); words('two'); out.heldWords = look(); await press(); words(''); out.heldWordsN = n(); pass(600); out.again = look(); await press(); out.againN = n();
  lives = 0; pass(500); out.force = look(); out.asked = lives > 0; await send(); out.enterN = n();
  words('three'); out.queuedWords = look(); await press(); words(''); out.queuedWordsN = n(); pass(1100);
  S.atts = {c1: [{path: '/a'}]}; render(); out.att = look(); S.atts = {c1: [{err: 'no'}]}; render(); out.attErr = look(); S.atts = {}; render();
  press(); out.forced = [look(), acts.map(x => [x.name, x.args])]; await press(); pass(5000); await press(); out.twiceN = n();
  acts[0].ok({ok: true}); await tick(); out.answered = look(); await press(); out.answeredN = n(); live(0); pass(1100); out.done = look();
  live(1); FD.foot = {text: 'x'}; press(); out.unsentForce = acts[1].args; acts[1].ok({ok: true}); await tick(); pass(1100); FD.foot = {text: ''};
  works = false; render(); out.idle = look(); await press(); out.idleN = n();
  works = true; FD.live = null; for (const k in sendHeld) delete sendHeld[k]; render(); out.reload = look(); live(1); out.reloaded = look();
  FD.n = 'c2'; render(); out.otherChat = look(); FD.n = 'c1'; S.thread = null; render(); out.home = look();
  console.log(JSON.stringify(out));
})();`);
"""


def test_send_waits_f205(tmp: Path) -> None:
    """F205: the send arrow is gray, and says Uploading…, while an attachment of its box uploads; it turns back at once,
    and an uploaded attachment alone is something to send."""
    page = W.PAGE.read_text(encoding='utf-8')
    check('.box .send[data-send][aria-disabled=true]:not(#_){opacity:.4;filter:grayscale(1);' in page, 'gray, with an empty box too')
    if not shutil.which('node'):
        print('  (no node here: the send arrow test is skipped)')
        return
    (tmp / 'driver.js').write_text(SEND_WAIT_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs the send arrow', r.stderr[-800:])
    o = json.loads(r.stdout or '{}')
    wait = lambda has: ['Uploading…', 'Uploading…', 'true', False, has]  # noqa: E731
    ready = lambda has: ['Send', 'Send', '', False, has]  # noqa: E731
    for k, want in (('alone', wait(False)), ('aloneUp', ready(True)), ('words', wait(True)), ('wordsUp', ready(True)),
                    ('failed', ready(False)), ('failedWords', ready(True)), ('removed', ready(True)), ('works', wait(True)),
                    ('worksUp', ready(True)), ('one', wait(True)), ('both', ready(True)), ('other', ready(True))):
        eq(o.get(k), want, f'F205: {k}')
    eq((o.get('said'), o.get('kept')), (['Wait for the attachments to finish uploading'], ['hi', 1]), 'a tap or Enter says why, and nothing is lost')
    for k, args in (('words', ['text', 'to']), ('att', ['text', 'to']), ('idle', ['text', 'to']), ('unsent', ['text', 'to', 'unsent'])):
        eq(o.get(f'sent_{k}'), [ready(True), [['chat_to', args, True]]], f'F190a: {k}: the plain Send, sent once with no force')
    held, force = ['Send', 'Send', 'true', False, False], ['Force send', 'Force send', '', True, False]
    for k, want in (('nothing', ready(False)), ('after', held), ('held', held), ('heldWords', ready(True)), ('again', held), ('force', force),
                    ('queuedWords', ready(True)), ('att', ready(True)), ('attErr', ready(False)), ('answered', held), ('done', ready(False)),
                    ('idle', ready(False)), ('reload', ready(False)), ('reloaded', force), ('otherChat', ready(False)), ('home', ready(False))):
        eq(o.get(k), want, f'F190c: {k}')
    for k, want in (('nothingN', [0, 0]), ('heldN', [1, 0]), ('heldWordsN', [2, 0]), ('againN', [2, 0]), ('enterN', [2, 0]),
                    ('queuedWordsN', [3, 0]), ('twiceN', [3, 1]), ('answeredN', [3, 1]), ('idleN', [3, 2])):
        eq(o.get(k), want, f'F190c: {k}: messages sent, forces')
    eq(o.get('forced'), [held, [['chat_to', {'text': '', 'to': 'c1', 'force': True}]]], 'F190c: a press forces once, with no text')
    eq(o.get('unsentForce'), {'text': '', 'to': 'c1', 'force': True, 'unsent': True}, 'F190c: with words in its prompt')
    check(o.get('asked'), 'F190c: after the delay what is queued is asked again')


def test_banner_f402c(tmp: Path) -> None:
    """F402c: the run-off banner is not on Home, whose Start card says it; every other view but Status has it."""
    if not shutil.which('node'):
        return
    s = {'up': False, 'boot': 'b', 'shown': U.controls_shown(False, {}, {})['shown']}
    got = logic_js([['runOff', s, {'view': v}] for v in ('home', 'status', 'plan', 'talk')]
                   + [['runOff', s, {'view': 'home', 'thread': 'c1'}], ['runStarts', s], ['runStarts', {**s, 'up': True}]])
    eq(got, [False, False, False, True, True, True, False], 'where the banner shows (F476: Work has the run controls, as Status had)')


def test_copilot_jump_b863(tmp: Path) -> None:
    """B863: a session scrolled up whose screen draws no jump pill (Copilot's) shows the page's own Jump to bottom, which
    takes it to its newest output; Claude's pill stays its own."""
    page = W.PAGE.read_text(encoding='utf-8')
    check('||!HX.st&&FD.shown&&!!FD.own' in page, 'the page\'s jump button shows for it')
    if not shutil.which('node'):
        return
    claude = [*F170_IDLE[:2], '● done       Jump to bottom (ctrl+End) ↓', '', *F170_IDLE[4:]]
    foots = logic_js([['feedFoot', claude, None], ['feedFoot', ['● an answer', 'more words', '', '> Ask Copilot'], None]])
    got = logic_js([['feedOwnJump', True, foots[1]], ['feedOwnJump', True, None], ['feedOwnJump', False, foots[1]],
                    ['feedOwnJump', True, foots[0]], ['feedOwnJump', False, foots[0]]])
    eq(got, [True, True, False, False, False], 'scrolled up with no pill of its own: the page\'s button; Claude keeps its pill')
    src = ''.join(page[page.index(f'function {f}('):].split('\n', 1)[0] + '\n' for f in ('pastJumpGo', 'feedOwnEnd'))
    (tmp / 'driver.js').write_text(src + r"""
let ends=0, downs=0, draws=0;
const FD={own:true}, HX={st:''}, feedTerm=()=>({scrollToBottom:()=>ends++}), pastDown=()=>downs++, pastJumpDraw=()=>draws++;
pastJumpGo();
const one=[ends,downs,FD.own,draws];
HX.st='up';pastJumpGo();
console.log(JSON.stringify([one,[ends,downs]]));
""", encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js')], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs the jump', r.stderr[-900:])
    if r.returncode == 0:
        eq(json.loads(r.stdout), [[1, 0, False, 1], [1, 1]], 'a press takes the terminal to its end; the history still goes back its own way')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_feed_pane_concept), in_tmp(test_control_rows), in_tmp(test_news_f149), in_tmp(test_scroll_f83), in_tmp(test_keyboard_b160), in_tmp(test_keyboard_feed_b214), in_tmp(test_reload_b177), in_tmp(test_older_run_b164), in_tmp(test_session_feed_f114), in_tmp(test_switcher_f206), in_tmp(test_session_proxy_f114), in_tmp(test_session_controls_f170), in_tmp(test_bars_over_text_b192), in_tmp(test_phone_screen_b194), in_tmp(test_frame_typing_b190), in_tmp(test_frame_copy_b845), in_tmp(test_session_run_side_f170), in_tmp(test_send_waits_f205), in_tmp(test_banner_f402c), in_tmp(test_copilot_jump_b863)]))
