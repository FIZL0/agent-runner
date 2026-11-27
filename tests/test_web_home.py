"""The run page, home area (agent_runner/page/*-home.*): split from test_web.py (C41b), tests unchanged.

    python3 tests/test_web_home.py
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


LOGIN_DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const line = s => page.slice(page.indexOf(s), page.indexOf('\n', page.indexOf(s)));
let HOME_PAGE = false, all = false, H, S;
const el = {}, $ = () => el, atAll = () => all, I = {alert: '!'}, esc = s => s, setHTML = (e, h) => { e.h = h };
eval(line('function loginDraw('));
const draw = (run, home) => { S = {snap: {claude_login: run}}; H = {login: home}; loginDraw(); return [el.hidden, el.h] };
const out = {run: draw('R', 'H'), fine: draw('', 'H'), old: draw(undefined, '')};
all = true; out.all = draw('R', 'H'); out.allFine = draw('R', '');
all = false; HOME_PAGE = true; out.home = draw(undefined, 'H'); out.homeFine = draw(undefined, '');
let closed = 0; const closeSheet = () => { closed++; S.sheet = '' }, toast = () => {};
S = {sheet: 'login', snap: {}}; H = {login: 'H'}; loginDraw(); out.open = closed; H.login = ''; loginDraw(); out.closed = [closed, el.hidden];
console.log(JSON.stringify(out));
"""


def test_login_banner_f126a(tmp: Path) -> None:
    """F126a: a Claude login that is ending, has ended or is missing is one banner on the run page and on Home, from a
    fake credentials file; none when it is far away, so a new login clears it."""
    from agent_runner import home as H
    repo, day, cfg = fake_repo(tmp), 86400, tmp / 'cfg'
    other = tmp / 'other'
    for d in (cfg, other):
        d.mkdir()
    (other / 'runner.toml').write_text('[run]\nagent = "otheragent"\n', encoding='utf-8')
    cred, roots = cfg / '.credentials.json', [other, repo]

    def login(left: float) -> None:
        cred.write_text(json.dumps({'claudeAiOauth': {'refreshToken': 'r', 'refreshTokenExpiresAt':
                                                      int((time.time() + left) * 1000)}}), encoding='utf-8')
    again = 'log in again (claude auth login)'
    off = ('ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_BASE_URL', 'CLAUDE_CODE_OAUTH_TOKEN',
           'CLAUDE_CODE_USE_BEDROCK', 'CLAUDE_CODE_USE_VERTEX', 'CLAUDE_CODE_USE_FOUNDRY')
    srv = H.serve_home('HT', 0, '127.0.0.1', rows=lambda: [], roots=lambda: roots, vitals=mock.Mock())
    try:
        with mock.patch.dict(os.environ, {'CLAUDE_CONFIG_DIR': str(cfg)}), mock.patch('sys.platform', 'linux'):
            for k in off:
                os.environ.pop(k, None)

            def said() -> tuple[str, str]:
                got = json.loads(get(f'http://127.0.0.1:{srv.server_address[1]}/projects?t=HT')[1])
                return U.snapshot(up=False, links={}, windows={})['claude_login'], got['claude_login']
            none = 'No Claude login: log in (claude auth login)'
            eq(said(), (none, none), 'missing: on both pages')
            login(2.5 * day)
            eq(said(), (f'Claude login expires in 2 days: {again}',) * 2, 'under 3 days')
            login(-day)
            eq(said(), (f'Claude login has expired: {again}',) * 2, 'past')
            roots.remove(repo)
            eq(said()[1], '', 'no project on this machine runs claude: none on Home')
            roots.append(repo)
            login(9 * day)
            eq(said(), ('', ''), 'far away, so after a new login: none')
    finally:
        srv.stop()
    page = W.PAGE.read_text(encoding='utf-8')
    eq((page.count('id="login"'), page.split('function render(')[1].split('\nfunction ')[0].count('loginDraw()')), (1, 1),
       'one banner, drawn with every view')
    if not shutil.which('node'):
        print('  (no node here: the banner script test is skipped)')
        return
    (tmp / 'driver.js').write_text(LOGIN_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node draws the banner', r.stderr[-1500:])
    if r.returncode:
        return
    again = '</span><button class="btn" data-login>Log in again</button>'  # F126b
    o, gone = json.loads(r.stdout), [True, '']
    eq((o['open'], o['closed']), (0, [1, True]), 'F126b: renewed: the banner goes and its sheet closes')
    eq((o['run'], o['fine'], o['old']), ([False, '!<span>R' + again], gone, gone), "the run page: the run's words, or none")
    eq((o['all'], o['allFine'], o['home'], o['homeFine']), ([False, '!<span>H' + again], gone, [False, '!<span>H' + again], gone),
       "All projects and Home: Home's words, or none")


NEED_DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const needs = JSON.parse(process.argv[3]);
const slice = (a, b) => page.slice(page.indexOf(a), page.indexOf(b, page.indexOf(a)));
const line = s => { const i = page.indexOf(s); return page.slice(i, page.indexOf('\n', i)) + '\n' };
const logic = page.split('<script id="logic">')[1].split('</script>')[0].replace(/if\(typeof module[^\n]*/, '');
const el = {h: '', cls: new Set(), focus() {}, scrollTop: 0, querySelectorAll: () => [], classList: {toggle: (c, on) => on ? el.cls.add(c) : el.cls.delete(c)}};
const sent = [], handlers = {}, fetched = [];
const env = {S: {snap: {needs, controls: JSON.parse(process.argv[4])}, f: {}, sheet: '', askShot: -1, askFold: {}, ob: []}, I: {ext: '', chev: ''}, SHEETS: {}, sheetBack: null,
  $: () => el, esc: t => env.E(t), setHTML: (n, h) => { el.h = h; return false }, keepScroll: () => () => {}, keepFields: () => () => {},
  document: {activeElement: null, addEventListener: (t, f) => { (handlers[t] = handlers[t] || []).push(f) }}, card: (h, c, a) => `<div class="card" ${a}>${h}</div>`,
  actSure: () => '', tq: p => p + '?t=T', toast: t => sent.push(['toast', t]), composing: () => false, HOME_PAGE: false,
  fetch: async p => { fetched.push(p); return {json: async () => ({ok: true, text: env.mute && p.startsWith('why/') ? '' : 'A task | files: <a>\nBLOCKED: CONFIRM'})} },
  render: () => env.sheetDraw(), outbox: (n, a, o) => { sent.push([n, a]); env.S.snap.needs = env.S.snap.needs.filter(x => x.id !== o.need); env.sheetDraw() }};
const known = new Proxy(env, {has: () => true, get: (t, k) => k === Symbol.unscopables ? undefined : k in t ? t[k] : k in globalThis ? globalThis[k] : () => ''});
env.env = env;
new Function('known', 'env', 'with (known) {' + logic + 'env.E=E_;' + line('const controlOf=') + line('const ctlBusy=') + slice('const actBtns=', 'const actSure=') + slice('function needBtns(', '/* F85: a task') + 'env.needOf=needOf;'
  + line('SHEETS.need=') + line('function openSheet(') + slice('function sheetOpener(', 'function sheetDraw(') + slice('function sheetDraw(', '/* --- F97') + 'env.sheetDraw=sheetDraw;env.card0=needCard;env.closeSheet=closeSheet;'
  + slice("document.addEventListener('click',async e=>{", "document.addEventListener('submit'")
  + slice("document.addEventListener('keydown',e=>{\n", "document.addEventListener('input',") + '}')(known, env);
const press = (sel, dataset = {}, inSheet = true) => handlers.click.forEach(f => f({target: {closest: s => s === sel ? {dataset, closest: () => inSheet, hasAttribute: () => false} : null}}));
const esc = () => handlers.keydown.forEach(f => f({key: 'Escape', preventDefault() {}, target: {closest: () => null, matches: () => false}}));
const S = env.S, out = {}, ans = (ctl, tid, inSheet) => press('[data-ctl]', {ctl, tid}, inSheet);
(async () => {
  const wait = () => new Promise(r => setTimeout(r, 10));
  out.card = env.card0(needs[0], 0);
  press('[data-needopen]', {needopen: 'B160'}, false); await wait();
  out.opened = [S.sheet, S.sheetArg, el.cls.has('open'), el.cls.has('dlg')]; out.fetched = [...fetched].sort(); out.html = el.h;
  press('[data-askfold]', {askfold: 'task'}); out.text = el.h;
  press('[data-shot]', {shot: '0'}); out.big = el.h; esc(); out.esc1 = [S.sheet, S.askShot]; esc(); out.esc2 = S.sheet;
  ans('need_answer1', 'F2', false); out.buttons = [S.sheet, sent.length];
  press('[data-needopen]', {needopen: 'B160'}, false);
  S.f['askre:B160'] = ' still grey '; ans('need_no', 'B160'); out.closed = S.sheet;
  press('[data-needopen]', {needopen: 'D7'}, false); out.reply = el.h; out.askCard = env.card0(needs[2], 2);
  out.steps = env.card0({...needs[2], detail: {...needs[2].detail, steps: ['a', 'b'], lead: [], title: 'D7'}}, 2);
  press('[data-reply]', {reply: 'D7'}); S.f['askre:D7'] = '8770'; press('[data-reply]', {reply: 'D7'}); out.sent = sent;
  S.f['askre:D8'] = ''; press('[data-needopen]', {needopen: 'D8'}, false); out.opts = el.h; out.optsCard = env.card0(needs[3], 3);
  S.f['askre:D8'] = ' dark too '; ans('need_answer1', 'D8'); out.opt = sent.slice(-1); sent.length -= 1;
  press('[data-needopen]', {needopen: 'D9'}, false); out.sheet = el.h; out.sheetCard = env.card0(needs[4], 4);
  ans('need_answer1', 'D9'); out.go = sent.slice(-1); sent.length -= 1;
  const pitch = {id: 'pitch1', label: 'PITCH', ask: 'Approve 1 change', options: ['Approve', 'Not this: drop'], acts: ['need_answer1', 'need_answer2', 'need_chat'], labels: {need_answer1: 'Approve', need_answer2: 'Not this: drop'}, changes: [{id: 'F1', title: 'a'}]};
  const no = {pitchno: '0', how: 'reopen', tid: 'F1'};
  env.mute = true; S.snap.needs = needs; S.askWhy = {}; press('[data-needopen]', {needopen: 'D7'}, false); await wait(); out.mute = el.h;
  const focused = [], node = (id, on) => ({dataset: {needopen: id}, isConnected: on, focus: () => focused.push(id + on)});
  env.document.querySelectorAll = () => [node('F2', true), node('D7', true)];
  env.sheetBack = node('D7', false); env.closeSheet(); out.focused = focused;
  S.snap.needs = [pitch]; S.f['askre:pitch1'] = ' nice '; press('[data-needopen]', {needopen: 'pitch1'}, false);
  out.pitchHtml = el.h; ans('need_answer1', 'pitch1'); S.snap.needs = [pitch]; press('[data-pitchno]', no);
  handlers.click.forEach(f => f({target: {closest: s => s === '[data-pitchno]' ? {dataset: no, closest: () => true, hasAttribute: () => true} : null}}));
  out.pitch = sent.slice(-2); sent.length -= 2; S.snap.needs = needs.slice(-1);
  press('[data-needopen]', {needopen: 'tool-x'}, false); out.tool = el.h; S.snap.needs = []; env.render(); out.left = S.sheet;
  console.log(JSON.stringify(out)); process.exit(0);
})();
"""


SHOT_DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const slice = (a, b) => page.slice(page.indexOf(a), page.indexOf(b, page.indexOf(a)));
const run = (reduced, hidden) => {
  const anims = [], body = [], css = {clipPath: 'none', paddingTop: '8px', paddingBottom: '0px', borderRadius: '16px', getPropertyValue: k => k === '--r-m' ? '10px' : k === '--dur-spring' ? '450ms' : k === '--dur' ? '200ms' : 'e-' + k};
  const node = (name, l, t, w, h, more) => ({name, style: {}, complete: true, isConnected: true, offsetWidth: w, offsetHeight: h, setAttribute() {}, remove() { const i = body.indexOf(this); if (i >= 0) body.splice(i, 1) },
    getBoundingClientRect: () => ({left: l, top: t, right: l + w, bottom: t + h, width: w, height: h}), cloneNode: () => node('copy', 0, 0, w, h),
    animate(f, o) { const a = {name, f, o, cancel() { this.gone = true; this.oncancel && this.oncancel() }}; anims.push(a); return a }, ...more});
  const thumb = node('thumb', 20, 500, 92, 120, {querySelector: () => ({naturalWidth: 720, naturalHeight: 1440})}), img = node('big', 20, 150, 360, 720, {complete: false, addEventListener() {}}), words = node('words', 20, 300, 300, 40), sheet = node('sheet', 0, 0, 0, 0);
  let high = 600, S = {askShot: -1};
  Object.assign(sheet, {scrollTop: 340, getBoundingClientRect: () => ({left: 0, top: 800 - high, right: 400, bottom: 800, width: 400, height: high}),
    querySelector: q => q === '.shotbig img' ? S.askShot >= 0 ? img : null : q === '[data-shot="0"]' ? S.askShot < 0 ? thumb : null : null,
    querySelectorAll: q => q.startsWith('.askbody') ? [words] : []});
  const f = new Function('S', '$', 'document', 'matchMedia', 'getComputedStyle', 'render', slice('const MO={', '\nconst shiftOf') + slice('const SHOT=', 'function needSheet(') + 'return {shotGo, SHOT, shotEnd}')(
    S, () => sheet, {hidden: !!hidden, body: {appendChild: x => body.push(x)}, documentElement: {}}, () => ({matches: reduced}), () => css,
    () => { high = S.askShot >= 0 ? 700 : 600; sheet.scrollTop = 17 });
  const out = {}, seen = () => anims.splice(0).map(a => [a.name, a.o.duration, a.o.easing, a.f]);
  f.shotGo(0); out.open = [S.askShot, sheet.scrollTop, seen()];
  out.room = img.style.aspectRatio; img.complete = true; f.shotGo(-1); out.close = [S.askShot, sheet.scrollTop, body.length, sheet.style.paddingTop || ''];
  const copy = anims.find(a => a.name === 'copy'); out.back = seen();
  if (copy) { copy.onfinish(); out.landed = body.length; }
  f.shotGo(0); f.shotGo(-1); out.two = body.length; f.shotEnd(); out.end = [body.length, sheet.style.paddingTop || ''];
  return out;
};
console.log(JSON.stringify({moves: run(false), calm: run(true), hidden: run(false, true)}));
"""


OVER_DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const slice = (a, b) => page.slice(page.indexOf(a), page.indexOf(b, page.indexOf(a)));
const run = (reduced, hidden) => {
  const anims = [], edges = [], css = {clipPath: 'none', getPropertyValue: k => k.startsWith('--dur') ? (k === '--dur' ? '200ms' : '450ms') : 'e-' + k};
  let high = 600, S = {sheet: ''};
  const node = name => ({name, matches: s => s === '.' + name, animate(f, o) { const a = {f, o, cancel() { this.oncancel && this.oncancel() }}; anims.push([name, o.duration, f]); this.last = a; return a }, removeAttribute() {}, setAttribute() {}, remove() { this.gone = true }, style: {}});
  const sheet = {...node('sheet'), scrollTop: 40, children: [node('grab'), node('words')], focus() {}, offsetWidth: 400, getBoundingClientRect: () => ({left: 0, top: 800 - high, right: 400, bottom: 800, width: 400, height: high})};
  const view = {...node('cview'), hidden: true, inert: false, querySelector: () => ({focus() {}})};
  const f = new Function('S', '$', 'document', 'matchMedia', 'getComputedStyle', 'render', 'shotEnd', 'shotEdges', 'runStop', 'scrollStop', 'sheetBack', 'loadVoices', 'I', 'esc',
    slice('const MO={', '/* an element moved by') + slice('function shotSeen(', '/* the part of a box') + slice('function sheetOver(', '/* F162a2') + slice('function conceptOpen(', "document.addEventListener('click'") + 'return {openSheet, conceptOpen, conceptClose}')(
    S, id => id === 'cview' ? view : sheet, {hidden: !!hidden, documentElement: {}}, () => ({matches: reduced}), () => css, () => { high = S.sheet === 'b' ? 400 : 600 }, () => {}, (el, t, b) => edges.push([t, b]), () => {}, () => {}, null, () => {}, {}, x => x);
  f.openSheet('a'); const out = {first: [edges.length, anims.length]};
  f.openSheet('b'); out.over = [[...edges], anims.map(a => a.slice(0, 2)), sheet.scrollTop];
  anims.length = 0; f.conceptOpen('x', 'X'); out.view = [view.hidden, anims.map(a => a[2][0].transform)];
  f.conceptClose(); out.leaving = [view.hidden, view.inert, anims.length]; if (view.last && view.last.onfinish) view.last.onfinish(); out.left = [view.hidden, view.inert];
  f.conceptOpen('x', 'X'); f.conceptClose(); f.conceptOpen('y', 'Y'); if (view.last && view.last.onfinish) view.last.onfinish(); out.again = [view.hidden, view.inert];
  return out;
};
console.log(JSON.stringify({moves: run(false), calm: run(true), hidden: run(false, true)}));
"""


def test_sheet_over_sheet_f189b(tmp: Path) -> None:
    """F189b: a sheet that takes another's place moves its edges from there and its words fade in, from its top; a concept's
    page slides in and out. All at once when calm()."""
    if not shutil.which('node'):
        print('  (no node here: the sheet script test is skipped)')
        return
    (tmp / 'driver.js').write_text(OVER_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node opens one sheet over another', r.stderr[-1500:])
    if r.returncode:
        return
    o = json.loads(r.stdout)
    m = o['moves']
    eq(m['first'], [0, 0], "the first sheet slides in by the stylesheet alone")
    eq(m['over'], [[[200, 0]], [['words', 200]], 0], 'over another: the edges move by what it lost, the words fade in, from its top')
    eq((m['view'], m['leaving'], m['left']), ([False, ['translateX(100%)']], [False, True, 2], [True, False]), "a concept's page slides in and out, out of reach at once")
    eq(m['again'], [False, False], 'opened again while it leaves: it stays')
    for k in ('calm', 'hidden'):
        eq((o[k]['over'], o[k]['view'], o[k]['leaving']), ([[], [], 0], [False, []], [True, False, 0]), f'{k}: at once')


def test_need_picture_moves_f189(tmp: Path) -> None:
    """F189: a picture opens out of its thumbnail and goes back into it, Back returns to the scroll place left; at once
    when calm()."""
    if not shutil.which('node'):
        print('  (no node here: the picture script test is skipped)')
        return
    (tmp / 'driver.js').write_text(SHOT_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node opens and closes the picture', r.stderr[-1500:])
    if r.returncode:
        return
    o = json.loads(r.stdout)
    m = o['moves']
    eq(m['open'][:2], [0, 0], 'open: the picture, from its top')
    eq(m['room'], '720/1440', 'a picture not decoded yet takes its room at once')
    by = {x[0]: x for x in m['open'][2]}
    eq(sorted(by), ['big', 'sheet', 'words'], 'open: the picture, the edges of the sheet and the words move')
    name, dur, ease, (first, last) = by['big']
    # the 92 x 120 thumbnail is covered by the 360 x 720 picture at 92/360; from its middle (66, 560) to (200, 510)
    check(first['transform'].startswith('translate(-134px,50px) scale(0.2555') and first['clipPath'].startswith('inset(125.2'), 'it starts as its thumbnail', first)
    eq((dur, ease, last['transform']), (450, 'e---spring-soft', 'none'), 'and goes to its own place on the tokens')
    eq(by['sheet'][3][0]['clipPath'], 'inset(100px 0px 0px 0px round 16px)', 'the sheet grows from where its edge was')
    eq((by['words'][1], by['words'][2]), (200, 'e---ease'), 'the words fade in')
    eq(m['close'], [-1, 340, 1, '108px'], 'Back: the scroll place left, the copy goes back, room kept for the edge')
    back = {x[0]: x for x in m['back']}
    check(back['copy'][3][1]['transform'].endswith('scale(0.25555555555555554)'), 'the copy ends as the thumbnail', back['copy'])
    check('thumb' in back, 'the thumbnail is hidden until then', sorted(back))
    eq((m['landed'], m['two'], m['end']), (0, 1, [0, '']), 'it is gone once there; pressed again, one copy; the sheet closed, none')
    for how in ('calm', 'hidden'):
        c = o[how]
        eq((c['open'], c['close'], c['back'], c['two']), ([0, 0, []], [-1, 340, 0, ''], [], 0), f'{how}: at once, and the scroll place all the same')
    page = W.PAGE.read_text(encoding='utf-8')
    eq(page.count('shotGo(-1)'), 2, 'Back and Esc go the same way')


def test_need_popup_f162(tmp: Path) -> None:
    """F162: a Needs you card is short, and a press on its words opens the popup with its steps, what to see, pictures
    and answers, all escaped; its buttons do not; an answer (with the reply box's words) closes it, and so does an item
    that leaves Needs you. Esc closes the picture, then the popup."""
    if not shutil.which('node'):
        print('  (no node here: the popup script test is skipped)')
        return
    d = {'said': 'Check this', 'where': 'iPhone, Safari', 'title': 'Keyboard <b>', 'summary': 'Run `x` <i>', 'lead': ['On an iPhone'],
         'steps': ['Tap <script>', 'Close it'], 'expect': ['No grey "band"'], 'notes': ['Reply yes/no'],
         'shots': [{'src': 'uploads/a b.png', 'path': '/x', 'caption': '"><img onerror=1>'}]}
    none = {k: [] for k in ('lead', 'expect', 'notes', 'shots')}
    needs = [{'id': 'B160', 'label': 'CONFIRM', 'ask': 'a', 'age': '20m', 'url': 'https://claude.ai/x', 'detail': d,
              'answers': [{'label': 'Yes', 'value': 'Yes'}, {'label': 'No', 'value': 'No'}]},
             {'id': 'F2', 'label': 'BLOCKED', 'ask': 'Log in', 'answers': [{'label': 'Done', 'value': 'Done'}]},
             {'id': 'D7', 'label': 'DECIDE', 'ask': 'Which port?', 'detail': {**none, 'said': 'Choose', 'where': '', 'title': 'Port <b>', 'summary': 'p', 'question': 'Which `port` <i>?', 'lead': ['8765 is taken.', 'Both <work>.'], 'steps': []}, 'answers': []},
             {'id': 'D8', 'label': 'DECIDE', 'ask': 'Which look?', 'options': (opts := [{'name': 'Full', 'rec': True}, {'name': 'No <change>', 'rec': False}]),
              'answers': U.need_answers({'label': 'DECIDE', 'options': opts})},
             {'id': 'D9', 'label': 'DECIDE', 'ask': 'Pick a layout', 'url': 'https://claude.ai/y', 'picks': {U.SHEET_GO_LABEL: 'go', 'Tabs': 'D9 picks: lay=a'},
              'options': (easy := [{'name': U.SHEET_GO_LABEL, 'rec': False}, {'name': 'Tabs', 'rec': True}]),
              'answers': U.need_answers({'label': 'DECIDE', 'options': easy})},
             {'id': 'tool-x', 'label': 'TOOL', 'ask': 'Connect it', 'answers': []}]
    for n in needs:  # F180: as the snapshot carries them
        n.update(acts=U.row_acts('need', n), labels=U.row_labels('need', n))
    (tmp / 'driver.js').write_text(NEED_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE), json.dumps(needs), json.dumps(U.controls())], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node presses the card', r.stderr[-1500:])
    if r.returncode:
        return
    o = json.loads(r.stdout)
    card = o['card']
    check('Check this · iPhone, Safari' in card and 'Keyboard &lt;b&gt;' in card and '<b class="q">Run <code>x</code> &lt;i&gt;</b><span class="small">Keyboard &lt;b&gt;</span>' in card
          and '2 steps · 20m' in card and '>B160</span><span class="asklab">' in card, 'the card: what is wanted and where, what is asked, the title small under it', card)
    check('Close it' not in card and card.index('</button>') < card.index('data-ctl="need_yes"'), 'no steps on it, and its buttons are not inside its words', card)
    eq(o['opened'], ['need', 'B160', True, True], 'a press on its words opens the popup')
    eq(o['fetched'], ['task/B160?t=T', 'why/B160?t=T'], 'which asks for why it waits and the whole task')
    h = o['html']
    parts = ['<h2>Run <code>x</code> &lt;i&gt;</h2><div class="small">Keyboard &lt;b&gt;</div>', 'Check this', '20m', 'On an iPhone', '<ol><li>Tap &lt;script&gt;</li><li>Close it</li></ol>',
             '<ul><li>No grey &quot;band&quot;</li></ul>', 'src="shot/uploads/a%20b.png?t=T"', 'Its page', 'Why it waits',
             'Full task', 'data-f="askre:B160"', 'class="btn pri" data-ctl="need_yes" data-tid="B160">Yes<', 'class="btn" data-ctl="need_no" data-tid="B160">No<', '>Later<', '>Open ']
    at = [h.find(x) for x in parts]
    check(-1 not in at and at == sorted(at), 'the popup, in order', list(zip(parts, at)))
    check('<script>' not in h and '<img onerror' not in h and '&quot;&gt;&lt;img onerror=1&gt;' in h, 'all of it escaped', h)
    check('<p>| files: &lt;a&gt;</p><p>BLOCKED: CONFIRM</p>' in o['text'] and '<pre' not in o['text'], 'the task text in paragraphs', o['text'])
    check('data-shotclose' in o['big'] and 'What to do' not in o['big'] and 'data-ctl="need_yes"' in o['big'], 'a picture opens in it, the answers stay', o['big'])
    eq((o['esc1'], o['esc2']), (['need', -1], ''), 'Esc closes the picture, then the popup')
    eq(o['buttons'], ['', 1], 'a button of the card answers and opens nothing')
    eq(o['closed'], '', 'an answer closes it')
    check('Full task' in o['mute'] and 'Why it waits' not in o['mute'], 'F162a2: no words of the agent, no Why it waits', o['mute'])
    eq(o['focused'], ['D7true'], 'F162a2: closing gives focus back to its card, drawn again since')
    page = W.PAGE.read_text(encoding='utf-8')
    check('.sheet.open:not(.drag){transition:transform var(--dur-spring) var(--spring-soft)}' in page and 'visible at once' in page,
          'F162a2: an opening sheet is visible at once, or it cannot take focus')
    check('data-reply="D7"' in o['reply'], 'an ask with no answers has Reply', o['reply'])
    q, t = 'Which <code>port</code> &lt;i&gt;?', 'Port &lt;b&gt;'
    check(f'<b class="q">{q}</b><span class="small">{t}</span><span class="askdo">8765 is taken. Both &lt;work&gt;.</span>' in o['askCard'],
          "B223b: a DECIDE's card: the question, the title small, its background", o['askCard'])
    check(f'<h2>{q}</h2><div class="small">{t}</div>' in o['reply'] and '<p>8765 is taken.</p><p>Both &lt;work&gt;.</p>' in o['reply']
          and 'What to do' not in o['reply'], 'the popup: the same, its background as paragraphs', o['reply'])
    check('askdo' not in o['steps'] and '<span class="small">Press' in o['steps'] and '2 steps' in o['steps'], 'no background, no title of its own: neither', o['steps'])
    check('<h2>Which look?</h2>' in o['opts'] and 'What to do' not in o['opts'], 'a DECIDE with no detail too', o['opts'])
    eq(o['sent'], [['run_control', {'key': 'need_answer1', 'tid': 'F2', 'text': 'Done'}],
                   ['run_control', {'key': 'need_no', 'tid': 'B160', 'text': 'No', 'note': 'still grey'}],
                   ['toast', 'Write your reply first'], ['answer', {'tid': 'D7', 'text': '8770'}]],
       "what is sent: the reply box's words go with the answer")
    want = 'class="btn pri" data-ctl="need_answer1" data-tid="D8">Full (recommended)</button><button class="btn" data-ctl="need_answer2" data-tid="D8">No &lt;change&gt;</button>'
    check(want in o['opts'] and want in o['optsCard'] and 'data-reply="D8"' in o['opts'], "F181c: a DECIDE's options are buttons, the recommended marked, Reply stays", o['opts'])
    eq(o['opt'], [['run_control', {'key': 'need_answer1', 'tid': 'D8', 'text': 'Full', 'note': 'dark too'}]], 'one sends the bare name and the note')
    want = 'class="btn pri" data-ctl="need_answer1" data-tid="D9">Go with the recommended picks</button><button class="btn" data-ctl="need_answer2" data-tid="D9">Tabs (recommended)</button>'
    check(want in o['sheet'] and want in o['sheetCard'] and 'data-reply="D9"' in o['sheet'], "F181b: a pick sheet's easy answers are buttons", o['sheet'])
    eq(o['go'], [['run_control', {'key': 'need_answer1', 'tid': 'D9', 'text': 'Go with the recommended picks'}]], 'a press opens no chat')
    check('>Approve<' in o['pitchHtml'] and 'need_answer2' not in o['pitchHtml'] and '>Chat<' in o['pitchHtml'], 'a pitch draws Approve alone', o['pitchHtml'])
    eq(o['pitch'], [['run_control', {'key': 'need_answer1', 'tid': 'pitch1', 'text': 'Approve', 'note': 'nice'}],
                    ['pitch_no', {'pid': 'pitch1', 'how': 'reopen', 'tid': 'F1', 'confirm': True, 'why': 'nice'}]],
       "F162a: a pitch's answers carry the words too")
    check('askfoot' not in o['tool'] and 'data-askfold' not in o['tool'], 'a missing tool has nothing to answer, and no task', o['tool'])
    eq(o['left'], '', 'it closes when the item leaves Needs you')


GIVE_DRIVER = NEED_DRIVER.split("  out.card = env.card0")[0].replace("  + slice(\"document.addEventListener('click'", "  + line(\"document.addEventListener('input',\") + slice(\"document.addEventListener('click'") + r"""
  const answers = JSON.parse(process.argv[5]), posts = [];
  env.sureHTML = new Function('esc', line('const sureHTML=') + 'return sureHTML')(env.E); env.kbReveal = () => {}; env.window = {isSecureContext: true}; env.KEEP = k => S.f[k];
  el.querySelector = () => null;
  const nodes = ['give:F399:link', 'givesec:F399:tok'].map(f => ({dataset: {f}, value: 'x', remove() { this.gone = true }}));
  el.querySelectorAll = s => s.startsWith('[data-f') ? nodes : [];
  env.fetch = async (p, o) => { if (!o) return {json: async () => ({ok: true, text: 't'})}; posts.push([p, JSON.parse(o.body), env.S.giving]); return {json: async () => answers.shift()} };
  const type = (k, v) => { S.f[k] = v };
  const type2 = (f, v) => handlers.input.forEach(h => h({target: {dataset: {f}, value: v, matches: s => s === '[data-f]'}}));
  const done = async sure => { press2(sure); await wait() };
  const press2 = sure => handlers.click.forEach(f => f({target: {closest: s => s === '[data-give]' ? {dataset: {give: 'F399'}, hasAttribute: () => sure} : null}}));
  out.card = env.card0(needs[0], 0); out.other = env.card0(needs[1], 1);
  press('[data-needopen]', {needopen: 'F399'}, false); await wait(); out.html = el.h;
  env.window.isSecureContext = false; env.render(); out.http = el.h; env.window.isSecureContext = true;
  type('give:F399:link', 'https://evil.example'); type('givesec:F399:tok', 'hunter2');
  await done(false); out.refused = [el.h, {...S.f}];
  await done(false); out.asked = [el.h, {...S.f}];
  S.sure = 'give:F399'; type2('give:F399:link', 'https://evil.example'); out.edited = S.sure; await done(true); out.sent = [S.sheet, {...S.f}, nodes.map(n => [n.value, !!n.gone]), S.snap.needs.map(n => n.id)];
  out.posts = posts; out.acts = sent;
  S.snap.needs = needs; nodes[1].value = 'x'; press('[data-needopen]', {needopen: 'F399'}, false);
  type('give:F399:link', 'kept'); type('givesec:F399:tok', 'hunter2'); env.closeSheet(); out.closed = [{...S.f}, nodes[1].value];
  console.log(JSON.stringify(out)); process.exit(0);
})();
"""


def give_row() -> dict:
    """F175a: a Needs you row as iFizBox F399 asks: two steps, a link with a match and a question, and a secret."""
    d = {'said': 'Waits on you', 'title': 'Shortcuts', 'where': '', 'summary': 's', 'lead': [], 'expect': ['It is listed'], 'notes': [], 'shots': [],
         'steps': ["Add main's copy of Install Switch to Shortcuts", 'Share > Copy iCloud Link', 'Run this'],
         'step_more': [{'link': 'https://www.icloud.com/shortcuts/a?b="c'}, {}, {'cmd': 'echo "<b>"', 'on': 'mini'}],
         'inputs': [{'key': 'link', 'label': 'iCloud link', 'kind': 'link', 'hint': 'h', 'match': '', 'confirm': 'Publish?', 'env': ''},
                    {'key': 'tok', 'label': 'To<ken', 'kind': 'secret', 'hint': '', 'match': '', 'confirm': '', 'env': 'TOK'}]}
    return {'id': 'F399', 'label': 'BLOCKED', 'ask': 'a', 'detail': d, 'answers': [{'label': 'Done', 'value': 'Done'}]}


def test_need_give_page_f175a(tmp: Path) -> None:
    """F175a: the popup draws an item's steps, fields and Done, with no plain answers; what it sends, a refusal, a
    question first, and what is left on the page afterwards."""
    if not shutil.which('node'):
        print('  (no node here: the popup script test is skipped)')
        return
    plain = {'id': 'F2', 'label': 'BLOCKED', 'ask': 'Log in', 'answers': [{'label': 'Done', 'value': 'Done'}]}
    needs = [give_row(), plain]
    for n in needs:
        n.update(acts=U.row_acts('need', n), labels=U.row_labels('need', n))
    answers = [{'ok': False, 'field': 'link', 'out': 'iCloud link: paste <it>'}, {'ok': False, 'code': 3, 'confirm': 'Publish?', 'out': 'Publish?'},
               {'ok': True, 'gone': 'F399', 'said': 'F399 has what you gave'}]
    (tmp / 'give.js').write_text(GIVE_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'give.js'), str(W.PAGE), json.dumps(needs), json.dumps(U.controls()), json.dumps(answers)],
                       capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node presses Done', r.stderr[-1500:])
    if r.returncode:
        return
    o = json.loads(r.stdout)
    h = o['html']
    check('need_answer1' not in o['card'] and 'need_answer1' in o['other'], 'no plain answers on its card; an item without inputs keeps them', o['card'])
    parts = ['Install Switch', 'href="https://www.icloud.com/shortcuts/a?b=&quot;c" target="_blank"', '>Open</a>', 'Share &gt; Copy iCloud Link', 'Run on mini',
             '<code>echo &quot;&lt;b&gt;&quot;</code>', '>Copy</button>', 'iCloud link', 'data-f="give:F399:link"', 'To&lt;ken',
             'data-f="givesec:F399:tok" type="password"', 'data-give="F399" >Done<']
    at = [h.find(x) for x in parts]
    check(-1 not in at and at == sorted(at), 'steps with Open and Copy, then a field each, then Done', list(zip(parts, at)))
    check('need_answer1' not in h and 'askre:' not in h and h.count('data-give=') == 1, 'one Done, no plain answer', h)
    check('plain http' in o['http'] and 'givesec' not in o['http'] and 'data-give="F399" disabled' in o['http'], 'over http: no secret field, and why', o['http'])
    vals = {'link': 'https://evil.example', 'tok': 'hunter2'}
    h, f = o['refused']
    check('iCloud link: paste &lt;it&gt;' in h and h.index('data-f="give:F399:link"') < h.index('paste &lt;it') < h.index('To&lt;ken') and 'aria-invalid' in h,
          'a refusal shows at its field', h)
    eq(f, {'give:F399:link': vals['link'], 'givesec:F399:tok': vals['tok']}, 'and keeps what was typed')
    h, f2 = o['asked']
    check('Publish?' in h and 'data-give="F399" data-sure' in h and '>Done<' not in h and f2 == f, 'asked first', h)
    eq([x[:2] for x in o['posts']], [['give?t=T', {'tid': 'F399', 'values': vals, 'confirm': c}] for c in (False, False, True)], 'what is sent, and where')
    eq(o['posts'][0][2], 'F399', 'and it shows that it is sending')
    check('hunter2' not in json.dumps([o['refused'][0], o['asked'][0], o['html']]), 'a secret is never in the markup')
    eq(o['sent'], ['', {}, [['', True], ['', True]], ['F2']], 'sent: the popup closes, its fields and their values are gone')
    eq(o['acts'], [['toast', 'F399 has what you gave']], 'nothing went through the outbox')
    eq(o['edited'], None, 'a field changed under the question: Done asks again')
    eq(o['closed'], [{'give:F399:link': 'kept'}, ''], 'closing forgets a secret, not a link')
    page = W.PAGE.read_text(encoding='utf-8')
    check("!k.startsWith('givesec:')" in page[page.index('function keepTyped'):page.index('function takeTyped')]
          and "secret:Object.keys(S.f).some(k=>k.startsWith('givesec:')" in page, 'a refresh keeps no secret and waits for it')
    from agent_runner import page_copy
    copy = page_copy.page_copy_html({'needs': needs})
    check('F399' in copy and '<input' not in copy and 'ken' not in copy, 'the claude.ai copy has no field', copy)


def test_give_route_f175a(tmp: Path) -> None:
    """F175a: POST /give: the token, and a secret only over https or this machine, whatever the page says; a failed
    match says its hint, a question is asked first; nothing the run keeps or shows but its own file has the secret."""
    import shlex
    import urllib.request as ur
    from agent_runner import home as H, plan as P
    from agent_runner.status import waiting_ok
    repo = fake_repo(tmp)
    asks = repo / '.runner' / 'asks'
    asks.mkdir(parents=True, exist_ok=True)
    token, secret, url = W.web_token(), 'hunter2-sentinel', 'https://www.icloud.com/shortcuts/abc'
    ask = lambda tid, *xs: (P.block(tid, 'BLOCKED: give it', todo=S.C.todo),  # noqa: E731
                            (asks / f'{tid}.json').write_text(json.dumps({'steps': ['Do it'], 'inputs': list(xs)}), encoding='utf-8'))
    ask('F1', {'key': 'link', 'label': 'iCloud link', 'kind': 'link', 'match': r'https://www\.icloud\.com/shortcuts/\S+', 'hint': 'paste the iCloud link',
               'confirm': 'Publish this?'})
    tokin = [{'key': 'tok', 'label': 'Token', 'kind': 'secret', 'env': 'TOK'}]
    ask('B2', *tokin)
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {'needs': U.needs_rows(waiting_ok(), dt.datetime.now())[0]})
    port = srv.server_address[1]
    hs = H.serve_home('home-tok', 0, '127.0.0.1', rows=lambda *a: [])
    hs.link, hs.project = (lambda root: (port, token)), (lambda key: repo)
    hp = hs.server_address[1]
    said = []

    def give(body, p=port, path=None, **hd) -> tuple[int, dict]:
        hd = {'Content-Type': 'application/json', 'Origin': f'http://127.0.0.1:{p}', **hd}
        req = ur.Request(f'http://127.0.0.1:{p}' + (path or f'/give?t={token}'), data=json.dumps(body).encode(), headers=hd, method='POST')
        try:
            with ur.urlopen(req, timeout=20) as r:
                got = r.status, r.read()
        except urllib.error.HTTPError as e:
            got = e.code, e.read()
        said.append(got[1].decode())
        return got[0], json.loads(got[1])
    far = {'Host': 'box:8770', 'Origin': 'http://box:8770'}  # as a page opened over plain http by name
    ts = {'Host': 'box.ts.net', 'Origin': 'https://box.ts.net', 'X-Forwarded-Proto': 'https', 'X-Forwarded-For': '100.1.2.3'}
    tok = {'tid': 'B2', 'values': {'tok': secret}}
    home = '/p/proj/give?t=home-tok'
    try:
        eq(give({'tid': 'F1', 'values': {'link': url}}, path='/give')[0], 403, 'only with the token')
        eq(give(tok, Origin='http://evil.example')[0], 403, 'not from another page')
        eq(give(tok, **{'Content-Type': 'text/plain'})[0], 400, 'JSON only')
        for bad in ([], {'tid': 5, 'values': {}}, {'tid': 'F1', 'values': [secret]}, {'tid': 'F1'}):
            eq(give(bad)[0], 400, f'bad request: {bad}')
        line = S.C.todo.read_text(encoding='utf-8')
        for body, p, path, hd in ((tok, port, None, far), ({**tok, 'secure': True}, port, None, far), (tok, port, None, {**ts, 'X-Forwarded-Proto': 'http'}),
                                  (tok, hp, home, far), ({**tok, 'secure': True}, hp, home, {**far, 'X-Runner-Channel': 'ok'})):
            code, r = give(body, p, path, **hd)
            check((code, r['ok'], r.get('field')) == (200, False, 'tok') and 'plain http' in r['out'], 'plain http: a secret is refused, and why', (hd, r))
        check(not (asks / 'B2.env').exists() and S.C.todo.read_text(encoding='utf-8') == line, 'nothing was kept or sent')
        r = give({'tid': 'F1', 'values': {'link': 'https://evil.example'}, 'confirm': True}, **far)[1]
        check((r['ok'], r['field']) == (False, 'link') and 'paste the iCloud link' in r['out'], 'a failed match says the hint at its field', r)
        for c in (False, 'true', 1):
            r = give({'tid': 'F1', 'values': {'link': url}, 'confirm': c}, **far)[1]
            eq((r['code'], r['confirm']), (3, 'Publish this?'), f'asked first ({c!r})')
        check(S.C.todo.read_text(encoding='utf-8') == line, 'nothing was sent yet')
        r = give({'tid': 'F1', 'values': {'link': url}, 'confirm': True}, **far)[1]
        check(r['ok'] and r['gone'] == 'F1' and url in S.C.todo.read_text(encoding='utf-8'), 'a link goes over http too', r)
        for p, path, hd in ((port, None, {}), (port, None, ts), (hp, home, ts), (hp, home, {})):
            ask('B2', *tokin)
            (asks / 'B2.env').unlink(missing_ok=True)
            r = give(tok, p, path, **hd)[1]
            check(r['ok'] and shlex.split((asks / 'B2.env').read_text(encoding='utf-8')) == [f'TOK={secret}'], 'https or this machine: kept', (hd, r))
        ask('B2', *tokin)
        with mock.patch.object(U, 'need_give', mock.Mock(side_effect=RuntimeError(secret))):
            check('RuntimeError' in give(tok)[1]['out'], 'an error says its kind alone')
        with mock.patch.object(W.Handler, 'log_message') as log:
            said.append(get(f'http://127.0.0.1:{port}/snapshot?t={token}')[1].decode())
            check(secret not in str(log.mock_calls), 'nor in a log')
    finally:
        hs.stop()
        srv.stop()
    check(not any(secret in x for x in said), 'no answer and no snapshot holds the secret')
    check('"inputs"' in said[-1], 'the snapshot asks for it', said[-1][:500])
    for f in repo.rglob('*'):
        if f.is_file() and f.name != 'B2.env':
            check(secret.encode() not in f.read_bytes(), f'nor does {f.name}')


def test_need_note_f162(tmp: Path) -> None:
    """F162: the words beside a button's answer reach the plan with it."""
    from agent_runner import plan as P
    fake_repo(tmp)
    P.block('F1', 'CONFIRM: check the board loads', todo=S.C.todo)
    P.block('B2', 'DECIDE: ship it, yes or no?', todo=S.C.todo)
    ran = []
    with mock.patch.object(U, 'RUN', [lambda argv: (ran.append(argv), (0, ''))[1]]):
        U.act('answer', tid='F1', text='Yes', button=True, note='on  wifi')
        U.act('answer', tid='F1', text='No', button=True, note='still grey')
        U.act('answer', tid='F1', text='No', button=True, note=' ')
        U.act('answer', tid='B2', text='Yes', button=True, note='on Monday')
    eq(ran, [['plan', 'confirm', 'F1', 'Yes: on wifi'], ['plan', 'change', 'F1', 'No: still grey'],
             ['plan', 'change', 'F1', 'No: the check failed'], ['plan', 'confirm', 'B2', 'Yes: on Monday']], 'the note goes with it')


def test_pitch_note_f162a(tmp: Path) -> None:
    """F162a: the words beside a pitch's answer are kept: Approve's go to a new chat, once it is approved; Not this's
    are its --why; if the chat does not start, the toast says the words."""
    fake_repo(tmp)
    ran, sent, code, ok = [], [], [0], [True]
    send = lambda t: (sent.append(t), {'ok': ok[0], 'code': 0, 'out': 'no session', 'argv': []})[1]  # noqa: E731
    with mock.patch.object(U, 'need_label', lambda tid: 'PITCH'), mock.patch.object(U, 'SEND', [send]), \
            mock.patch.object(U, 'RUN', [lambda argv: (ran.append(argv), (code[0], 'pushed'))[1]]):
        r = U.act('answer', tid='pitch1', text='Approve', button=True, note='- watch  the menu')
        U.act('answer', tid='pitch1', text='Not F1: drop', button=True, note='too slow')
        U.act('pitch_no', pid='pitch1', how='reopen', tid='F1', confirm=True, why='too  slow')
        U.act('answer', tid='pitch1', text='Approve', button=True)
        code[0] = 1
        U.act('answer', tid='pitch1', text='Approve', button=True, note='not yet')
        code[0], ok[0] = 0, False
        bad = U.act('answer', tid='pitch1', text='Approve', button=True, note='hold on')
    eq((r['said'], r['gone'], sent), ('pushed', 'pitch1', ['pitch1: approved. - watch the menu', 'pitch1: approved. hold on']),
       "Approve's words go to a chat, only once it is approved")
    eq(ran[:4], [['pitch', 'approve', 'pitch1'], ['pitch', 'no', 'pitch1', '--drop', 'F1', '--why=too slow'],
                 ['pitch', 'no', 'pitch1', '--reopen', 'F1', '--why=too slow'], ['pitch', 'approve', 'pitch1']], "Not this's are its why")
    check(bad['gone'] == 'pitch1' and 'hold on' in bad['said'], 'a chat that does not start: the words are said', bad)


def test_shot_f162(tmp: Path) -> None:
    """F162: a Needs you item's pictures are served only with the token, only images, only from <notes>/uploads and
    <notes>/asks, with no way out by .. or a symlink; /why gives the agent's last words."""
    repo = fake_repo(tmp)
    notes = repo / '.runner'
    (notes / 'uploads').mkdir(parents=True, exist_ok=True)
    (notes / 'asks').mkdir(parents=True, exist_ok=True)
    png = b'\x89PNG\r\n\x1a\nfake picture'
    for f in ('uploads/a b.png', 'asks/b.png', 'secret.png'):
        (notes / f).write_bytes(png)
    (notes / 'uploads' / 'fake.png').write_bytes(b'not a picture at all')
    (notes / 'uploads' / 'x.svg').write_text('<svg onload="1"/>')
    (notes / 'asks' / 'B1.json').write_text('{}')
    linked = True
    try:
        (notes / 'uploads' / 'out.png').symlink_to(notes / 'secret.png')
        (notes / 'asks' / 'dir').symlink_to(notes, target_is_directory=True)
    except OSError:
        linked = False
    token = W.web_token()
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {})
    base = f'http://127.0.0.1:{srv.server_address[1]}'
    try:
        for f in ('uploads/a%20b.png', 'asks/b.png'):
            eq(get(f'{base}/shot/{f}?t={token}'), (200, png), f'{f} is served')
            eq(get(f'{base}/shot/{f}')[0], 403, 'only with the token')
        bad = ['uploads/../secret.png', 'uploads/%2e%2e/secret.png', 'uploads/..%2fsecret.png', 'asks/..%5csecret.png',
               'secret.png', 'uploads/', 'uploads/no.png', 'uploads/fake.png', 'uploads/x.svg', 'asks/B1.json', 'concepts/a.png',
               'uploads/%2fetc/passwd', 'uploads/%00.png', 'uploads/..%2fasks/b.png']
        for f in bad + (['uploads/out.png', 'asks/dir/secret.png'] if linked else []):
            eq(get(f'{base}/shot/{f}?t={token}')[0], 404, f'{f} is refused')
        why = json.loads(get(f'{base}/why/F1?t={token}')[1])
        eq((why['ok'], why['text']), (True, ''), 'why it waits: no session, so no words (Full task has the task lines)')
        with mock.patch.object(U, 'agent_said', lambda tid: f'{tid} needs a phone'):
            eq(json.loads(get(f'{base}/why/F1?t={token}')[1])['text'], 'F1 needs a phone', "a session's last words")
        eq(json.loads(get(f'{base}/why/--x?t={token}')[1])['ok'], False, 'a task id only')
        eq(get(f'{base}/why/F1')[0], 403, 'only with the token')
    finally:
        srv.stop()


def test_home_switcher_f134(tmp: Path) -> None:
    """F134: through Runner Home (/p/KEY/) the sidebar opens with a project switcher: every Home project from
    Home's /projects, running/idle/off and its needs-you count, each a link to /p/KEY/?t=TOKEN on the same Home
    address; Home's own page is the same app in Home mode (HOME_PAGE), with All projects and Devices."""
    page = W.PAGE.read_text(encoding='utf-8')
    check("fetch(tq(HB+'projects'))" in page, "the switcher reads Home's /projects, with the page's token")
    check('sideShow(`${allRow()}' in page and 'data-up' in page, 'F150: the sidebar starts with All projects when Home is around')
    check('projects:projectsHTML' in page, 'and the run app has an All projects view')
    run_page = W.page_html().decode()
    home_page = W.page_html(home=True).decode()
    check('const HOME_PAGE=/*HOME_PAGE*/false;' in run_page and 'const HOME_PAGE=true;' in home_page and
          '<title>Runner Home</title>' in home_page, "Home's page is the run app with HOME_PAGE on", home_page[:600])
    if not shutil.which('node'):
        print('  (no node here: the switcher script test is skipped)')
        return
    ps = [{'key': 'alpha', 'name': 'alpha', 'state': 'running', 'paused': False, 'needs': 2},
          {'key': 'beta two', 'name': 'beta two', 'state': 'idle', 'paused': True, 'needs': 0},
          {'key': 'gamma', 'name': 'gamma', 'state': 'off', 'needs': None}]
    got = logic_js([['switcherRows', ps, 'alpha', '/', 'HT&1'],
                    ['homeBase', '/p/alpha/', False], ['homeBase', '/', True], ['homeBase', '/', False],
                    ['homeKey', '/p/beta%20two/'], ['homeKey', '/'],
                    ['projectMain', {'state': 'off'}], ['projectMain', {'state': 'off', 'starting': True}],
                    ['projectMain', {'state': 'idle', 'page': 'p/a/'}],
                    ['projectMore', {'name': 'a', 'state': 'off'}], ['projectMore', {'name': 'a', 'state': 'running', 'slots': 2}],
                    ['projectWords', {'state': 'idle', 'paused': True, 'slots': 1, 'running': [], 'left': 3}],
                    ['projectOrder', [{'key': k, 'state': s, 'paused': z} for k, s, z in
                                      (('off2', 'off', False), ('Off1', 'off', False), ('paused', 'running', True),
                                       ('Idle', 'idle', False), ('b', 'running', False), ('A', 'running', False))]],
                    ['switcherRows', ps, 'alpha', '/', 'T', 'plan'],
                    ['oneProject', ps], ['oneProject', ps[:1]], ['oneProject', None], ['needsOf', ps], ['needsOf', ps, 'alpha'],
                    ['projectAsks', [{'key': 'z', 'name': 'z', 'state': 'off', 'asks': ['F2 - check - it']},
                                     {'key': 'a', 'name': 'a', 'state': 'idle', 'asks': ['K1 - pick one']}]],
                    ['snapKept', {'home': {'t': 'TOKEN'}, 'boot': 'b', 'at': 'now', 'page': 'p', 'version': '1', 'queue': [1]}],
                    ['homeBase', '/p/alpha/', True], ['placeOf', '{}', '#need-F162a2', True, []], ['placeOf', '{}', '#need-', True, []]])
    up = {'key': 'a', 'state': 'running', 'slots': 2}
    act = lambda n, arg='', st='sending', key='a': {'name': n, 'state': st, 'args': {'project': key, 'arg': arg}}
    now = logic_js([['projectNow', {'key': 'a', 'state': 'off'}, [act('start')]], ['projectNow', up, [act('pause'), act('slots', '5')]],
                    ['projectNow', up, [act('pause', st='failed'), act('stop', key='b')]], ['projectNow', up, [act('stop')]],
                    ['projectNow', {**up, 'paused': True}, [act('resume')]]])
    eq([now[0].get('starting'), (now[1]['paused'], now[1]['slots']), now[2], now[3]['stopping'], now[4]['paused']],
       [True, (True, 5), up, True, False], 'F150: an action on its way shows at once; one that failed, or of another project, does not')
    eq([(r['key'], r['said'], r['needs'], r['href'], r['on']) for r in got[0]],
       [('alpha', 'running', 2, '/p/alpha/?t=HT%261#home', True), ('beta two', 'paused', 0, '/p/beta%20two/?t=HT%261#home', False),
        ('gamma', 'off', 0, '/p/gamma/?t=HT%261#home', False)],
       "the switcher lists Home's projects with their state and needs-you count, each linking /p/KEY/?t=TOKEN#home")
    eq(got[1:6], ['/', '/', '', 'beta two', ''],
       "Home's address from the page's path: /p/KEY/ through Home, / on Home's own page, none on a run's own port")
    eq([got[6]['label'], got[7]['label'], got[8]['label']], ['Start run', 'Starting…', 'Open'], "a card's one main button")
    eq([b['label'] for b in got[9]], ['Unlist'], 'the rest is in its … sheet')
    eq([(b['label'], b.get('a'), bool(b.get('sure'))) for b in got[10]],
       [('Pause', 'pause', False), ('Slots', None, False), ('Stop', 'stop', True), ('Unlist', None, True)], 'Stop and Unlist ask first')
    eq(got[11], 'paused · 0 of 1 slot · 3 queued', 'the words under a project')
    eq([r['key'] for r in got[12]], ['A', 'b', 'Idle', 'paused', 'Off1', 'off2'], 'F150: running, idle or paused, off; by name in each')
    eq([r['href'] for r in got[13]][0], '/p/alpha/?t=T#home', 'switching opens Home')
    eq(got[14:19], [False, True, False, 2, 0], "All projects' row hides with one project; its count is the others'")
    eq([(a['key'], a['id'], a['what']) for a in got[19]], [('a', 'K1', 'Pick one'), ('z', 'F2', 'Check - it')], 'what needs you, over all projects')
    eq(got[20], {'queue': [1]}, 'the snapshot kept for the next visit holds no token and nothing of one run or version')
    eq(got[21], '/', "Home's page at /p/KEY/ (a project that is off) knows where Home is")
    eq((got[22], got[23]['link']), ({'v': 'home', 't': '', 'link': True, 'need': 'F162a2'}, False), 'a link to an item of Needs you')


SWITCH_DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const logic = page.split('<script id="logic">')[1].split('</script>')[0].replace(/if\(typeof module[^\n]*/, '');
const i = page.indexOf("const TAB_KEY='ar-tab'"), src = page.slice(i, page.indexOf("/* the list's level or the project's", i));
const ps = [{key: 'a', state: 'idle'}, {key: 'b', state: 'idle'}];
const from = tab => new Function('tabStore', 'projectsNow', logic + `const HKEY='a',HB='/',T='T';` + src + ';return [rowsNow()[1].href, projectHref("b"), lastTab()]')({get: () => tab}, () => ps);
const key = new Function(logic + 'return placeOf')();
console.log(JSON.stringify(['plan', '', 'home'].map(from).concat([['{"v":"plan","t":""}', '{"v":"home","t":"c3"}'].map(k => key(k, '#home', true, []))])));
"""


def test_switch_home_f203(tmp: Path) -> None:
    """F203: a switch to another project (the list, its number keys, a card, Open) opens its Home, from Plan or a chat
    here, also when Plan or a chat was open there; the view last open is still known for coming down again."""
    if not shutil.which('node'):
        print('  (no node here: the switch script test is skipped)')
        return
    (tmp / 'driver.js').write_text(SWITCH_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE)], capture_output=True, text=True, encoding='utf-8')
    check(r.returncode == 0, 'node runs the switch script', r.stderr[-800:])
    if r.returncode:
        return
    got, b = json.loads(r.stdout), '/p/b/?t=T#home'
    eq(got[:3], [[b, b, 'plan'], [b, b, ''], [b, b, 'home']], "the list's link and a card's open Home, from Plan, a chat or Home")
    eq(got[3], [{'v': 'home', 't': '', 'link': True}] * 2, 'over the view or chat kept there')


HOME_ACT_DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const logic = page.split('<script id="logic">')[1].split('</script>')[0].replace(/if\(typeof module[^\n]*/, '');
const i = page.indexOf("/* --- F150: Home's actions"), src = page.slice(i, page.indexOf('/* --- F150: Runner Home in the app', i));
const m = {}, store = {get: k => m[k] || '', set: (k, v) => { if (v) m[k] = v; else delete m[k] }};
let cids = 0, posts = [], answer = null, said = [];
const open = () => {
  const S = {}, H = {begun: {}, turn: 0, projects: [{key: 'a', state: 'running', slots: 2}, {key: 'b', state: 'off'}]};
  const api = new Function('S', 'H', 'store', 'fetch', logic + `
    const HB='/', tq=p=>p, newCid=()=>'k'+nextCid(), render=()=>{}, obDraw=()=>{}, toast=t=>said.push(t), loadProjects=()=>{}, addEventListener=()=>{}, setTimeout=f=>{later.push(f)}, clearTimeout=()=>{};
    ` + src + ';return {homeAct,homeDrain,homeRetry,homeHas}').bind(null);
  return {S, H, ...api(S, H, store, async (u, o) => { const b = JSON.parse(o.body); posts.push(b); const j = await answer(b); if (j === 'lost') throw new Error('lost'); return {status: 200, json: async () => j} })};
};
global.nextCid = () => ++cids; global.said = said; global.later = [];
const settle = async () => { for (let n = 0; n < 8; n++) await new Promise(r => setImmediate(r)) };
(async () => {
  const out = {}, hold = {};
  // a slow start holds up no other project, and the next page follows it with the same cid
  answer = b => b.name === 'start' ? new Promise(r => hold.start = r) : {ok: true, out: 'paused'};
  let p = open(); p.homeAct('b', 'start', '', 'Start run · b'); p.homeAct('a', 'pause', '', 'Pause · a'); await settle();
  out.slow = [posts.map(x => [x.project, x.name, x.cid]), p.S.hob.map(x => x.name), p.H.projects[0].paused];
  answer = () => ({ok: true, out: 'started'}); posts = [];
  let q = open(); out.kept = q.S.hob.map(x => x.name); q.homeDrain(); await settle();
  out.follows = [posts.map(x => x.cid), q.S.hob.length, !!q.H.begun.b, m['ar-outbox:@home'] || ''];
  // a refusal stays with Retry, under a new cid; a lost connection is sent again with the same one
  answer = () => ({ok: false, out: 'no'}); posts = []; q.homeAct('a', 'slots', '3', '3 slots · a'); await settle();
  out.failed = q.S.hob.map(x => [x.state, x.err]); const bad = q.S.hob[0].cid;
  answer = () => 'lost'; q.homeRetry(bad); await settle(); out.lost = q.S.hob.map(x => x.state);
  answer = () => ({ok: true, out: '3 slots'}); later.pop()(); await settle();
  out.again = [posts.length, posts[1].cid === posts[2].cid, posts[0].cid !== posts[1].cid, q.S.hob.length, q.H.projects[0].slots];
  console.log(JSON.stringify(out));
})();
"""


def test_home_actions_f150(tmp: Path) -> None:
    """F150: start, pause, slots and stop go through Home's own outbox, followed over a switch to another project."""
    if not shutil.which('node'):
        print('  (no node here: the Home actions script test is skipped)')
        return
    (tmp / 'driver.js').write_text(HOME_ACT_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE)], capture_output=True, text=True, encoding='utf-8')
    eq(r.returncode, 0, 'node runs the Home actions')
    if r.returncode:
        print(r.stderr)
        return
    o = json.loads(r.stdout)
    eq(o['slow'], [[['b', 'start', 'k1'], ['a', 'pause', 'k2']], ['start'], True], 'a slow start holds up no other project')
    eq((o['kept'], o['follows']), (['start'], [['k1'], 0, True, '']), 'the next page follows it, with the same id')
    eq((o['failed'], o['lost']), ([['failed', 'no']], ['sending']), 'a refusal stays, a lost connection waits')
    eq(o['again'], [3, True, True, 0, 3], 'and is sent again: the same id after a lost connection, a new one on Retry')


def test_home_screen_b179(tmp: Path) -> None:
    """B179: the run app on a phone's Home Screen: a manifest whose scope holds every project, behind the token, and
    no link inside the app that opens a new tab there."""
    fake_repo(tmp)
    srv = W.serve('TOK', 0, '127.0.0.1')
    base = f'http://127.0.0.1:{srv.server_address[1]}'
    try:
        for path in ('/manifest.webmanifest', '/icon-180.png'):
            eq((get(f'{base}{path}')[0], get(f'{base}{path}?t=WRONG')[0]), (403, 403), f'{path} needs the token')
        with urllib.request.urlopen(f'{base}/manifest.webmanifest?t=TOK', timeout=10) as r:
            m = json.loads(r.read())
            eq((r.headers['Content-Type'], r.headers['Cache-Control']),
               ('application/manifest+json; charset=utf-8', 'no-store'), 'the manifest, never stored')
        eq((m['name'], m['scope'], m['start_url'], m['display']), (S.project(), './', './?t=TOK', 'standalone'),
           "a run's own address: its own root, back in with the token")
        check('theme_color' not in m, 'no one colour for both themes')
        code, png = get(f'{base}/icon-180.png?t=TOK')
        eq((code, png[:8], int.from_bytes(png[16:20], 'big')), (200, b'\x89PNG\r\n\x1a\n', 180), 'the icon is a PNG')
        eq(get(f'{base}/icon-999.png?t=TOK')[0], 404, 'only the sizes it has')
    finally:
        srv.stop()
    for what, home in (('run page', False), ("Home's page", True)):
        page = W.page_html(home=home).decode()
        for tag in ('name="apple-mobile-web-app-capable" content="yes"',
                    'name="apple-mobile-web-app-status-bar-style" content="default"', 'viewport-fit=cover'):
            check(tag in page, f'the {what} has {tag}')
        check("add('manifest',manifestLink(HB,HKEY,T))" in page and "add('apple-touch-icon'" in page,
              f'the {what} links its manifest and icon')
        links = re.findall(r'<a class="(?:prow|btn|pname|brand)[^>]*(?:projectLink|projectHref|r\.href|esc\(href\))[^>]*>', page)
        check(len(links) >= 4, f'the {what} has the list, Overview and project card links', links)
        for a in links:
            check('_blank' not in a, f'{what}: a link between projects opens no tab', a)
    if not shutil.which('node'):
        print('  (no node here: the Home Screen script test is skipped)')
        return
    o = 'https://h.ts.net:8771'
    eq(logic_js([['manifestLink', '/', 'beta two', 'T&1'], ['manifestLink', '/', '', 'T'], ['manifestLink', '', 'x', 'T'],
                 ['appLink', o + '/p/a/?t=T', o, '/'], ['appLink', o + '/p/a/concept/K1?t=T', o, '/'],
                 ['appLink', 'https://claude.ai/x?t=T', o, '/'], ['appLink', 'http://h.ts.net:8770/?t=T', o, '/'],
                 ['appLink', o + '/other/?t=T', o, '/home/'], ['appLink', o + '/p/a/', o, '/'], ['appLink', o + '/p/a/?t=', o, '/'], ['appLink', '', o, '/']]),
       ['/manifest.webmanifest?p=beta%20two&t=T%261', '/manifest.webmanifest?t=T', './manifest.webmanifest?t=T',
        'go', 'concept', '', '', '', '', 'go', ''],
       "the manifest at Home's root; the app's own pages stay in it, other sites open outside")


def test_project_name_b153(tmp: Path) -> None:
    """B153: the run page shows the project's name, not agent-runner: the window title ('proj · runner'), the
    top-left (a link to Runner Home), the logo's letter and a chat's lead label."""
    fake_repo(tmp)
    run_page = W.page_html().decode()
    check('<title>proj · runner</title>' in run_page, 'the served title is the project first', run_page[:400])
    check("document.title=pageTitle(S.snap.project)" in run_page, 'and the snapshot keeps it')
    check('if(!HB||oneProject(H.projects))return brand();' in run_page and '<b>agent-runner</b>' not in run_page,
          'the top-left is the project name (brand), not agent-runner')
    check('class="logo">ar<' not in run_page and "'agent-runner')}</div>" not in run_page,
          'no ar logo, no agent-runner lead label')
    with mock.patch.object(W, 'home_port', lambda: 0):
        eq(W.home_address(), {}, 'Home not installed: no Home link')
    cfg = tmp / 'cfg'
    cfg.mkdir()
    (cfg / 'home.token').write_text('HT\n')
    from agent_runner import home as HM
    with mock.patch.object(W, 'home_port', lambda: 8770), mock.patch.object(HM, 'config_dir', lambda: cfg):
        eq(W.home_address(), {'port': 8770, 't': 'HT'}, "Home's port and token for the link")
        eq(W.with_extras({})['home'], {'port': 8770, 't': 'HT'}, 'in the run page snapshot')
    if not shutil.which('node'):
        print('  (no node here: the Home link script test is skipped)')
        return
    home = {'port': 8770, 't': 'H&T'}
    got = logic_js([['homeHref', '', 'RT', home, {'protocol': 'http:', 'hostname': 'box'}],
                    ['homeHref', '', 'RT', home, {'protocol': 'https:', 'hostname': 'box.ts.net'}],
                    ['homeHref', '/', 'RT', home, {'protocol': 'http:', 'hostname': 'box'}],
                    ['homeHref', '', 'RT', {}, {'protocol': 'http:', 'hostname': 'box'}],
                    ['pageTitle', 'ifizbox'], ['pageTitle', '']])
    eq(got[:4], ['http://box:8770/?t=H%26T', 'http://box.ts.net:8770/?t=H%26T', '/?t=RT', ''],
       "the top-left name links to Runner Home: its port and token on the page's host (over http, also from https); "
       "through Home, Home's own base; none while Home is not installed")
    eq(got[4:], ['ifizbox · runner', 'agent-runner'], 'the window title: the project first')


HOME_DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const line = a => page.slice(page.indexOf(a), page.indexOf('\n', page.indexOf(a)) + 1);
const grab = a => page.slice(page.indexOf(a), page.indexOf('\n}\n', page.indexOf(a)) + 3);
const logic = page.split('<script id="logic">')[1].split('</script>')[0].split('if(typeof module').join('if(false&&typeof module');
const S = {ob: [], atts: {}, f: {}, view: 'home', thread: null, snap: null};
const no = () => '', env = {S, I: {}, DK: {}, LOGO: no, greeting: no, keysLine: no, ttydLine: no, needsSec: () => '[needs]', dictWhy: no, micWhy: no,
  shownSession: no, busy: no, sessWorks: no, modelOf: no, keysShown: no, enterHint: no, boxKey: () => 'home', obCards: f => S.ob.filter(f).map(x => `[ob ${x.ctl}]`).join('')};
const names = ['const esc=', 'const card=', 'const controlOf=', 'const ctlBusy=', 'const CTL_ICON=', 'const chatPins=', 'const chats=', 'const chatTitle=', 'const slots=', 'const working_=', 'const homeSums='];
const src = logic + names.map(line).join('') + ['box', 'homeHTML', 'homeStart', 'homeChips', 'homeStatus', 'homePlan'].map(f => grab(`function ${f}(`)).join('');
const at = new Function('env', 'with(env){' + src.replace(/^const /gm, 'var ') + '; return {home: homeHTML, box: () => box("x")}}')(env);
const out = JSON.parse(require('fs').readFileSync(0, 'utf8')).map(([snap, ob]) => { S.snap = snap; S.ob = ob || []; return at.home() });
const boxes = [['home', null], ['home', 'c1'], ['home', '+new']].map(([v, t]) => { S.view = v; S.thread = t; return at.box() });
console.log(JSON.stringify([out, boxes]));
"""


def test_home_f426a(tmp: Path) -> None:
    """F426a: Home is Talk, the box without dictation, the shortcuts, Needs you, and one line each for Status and Plan."""
    if not shutil.which('node'):
        print('  (no node here: the Home test is skipped)')
        return
    fake_repo(tmp)
    ctl = U.controls()
    chat = [{'name': 'c4'}, {'name': 'c1', 'at': 50}, {'name': 'c3', 'at': 90}, {'name': 'c2', 'at': 70}]
    slot = [{'name': 's1', 'task': 'F1', 'state': 'live'}, {'name': 's2', 'task': 'F2', 'state': 'live'},
            {'name': 's3', 'task': 'F3', 'state': 'merging'}]
    rel = {'id': 'V1', 'title': 'Ship', 'state': 'waits', 'words': 'waits for 2: F1 a, F2 b', 'waits': [{'id': 'F1'}, {'id': 'F2'}]}
    q = [{'id': 'F1', 'state': 'running'}, {'id': 'F9', 'state': 'ready'}, {'id': 'F8', 'state': 'parked'}, {'id': 'V1', 'state': 'waiting', 'release': rel}]
    base = {'up': True, 'run': {'state': 'Running'}, 'sessions': chat + slot, 'chat_pins': ['c1'], 'queue': q, 'releases': [rel],
            'controls': ctl, 'card': ['slot_remove', 'slot_add', 'pause', 'stop'], 'needs': []}
    paused = {**base, 'run': {'state': 'Paused', 'paused': True}, 'card': ['go_on'], 'sessions': [], 'queue': [], 'releases': []}
    down = {**base, 'up': False, 'run': {}, 'card': ['start'], 'sessions': [], 'manage_releases': False}
    nxt = {**rel, 'state': 'next', 'waits': []}
    cases = [[base], [paused], [down], [{**base, 'queue': [{**q[3], 'release': nxt}], 'releases': [nxt]}],
             [base, [{'ctl': 'pause:', 'state': 'sending'}, {'ctl': 'stop:', 'state': 'sending'}]]]
    (tmp / 'driver.js').write_text(HOME_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE)], input=json.dumps(cases), capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node draws Home', r.stderr[-1500:])
    if r.returncode:
        return
    (up, pa, dn, free, sent), boxes = json.loads(r.stdout)
    at = [up.find(x) for x in ('btn acc talkbig" data-view="talk"', 'data-form', 'Last chat', 'Add a task', 'data-ctl="pause"',
                               'Since my last look', '[needs]', 'data-view="status"', 'data-view="plan"')]
    check(all(i >= 0 for i in at) and at == sorted(at), 'Talk, the box, the shortcuts, Needs you, Status, Plan', at)
    eq(up.count('btn acc'), 1, 'Talk is the one accent button')
    check('data-thread="c3"' in up and up.count('data-thread=') == 1, 'Last chat is the newest, not the pinned or one with nothing said yet; no agent cards', up)
    for gone in ('What needs me', 'New concept', 'Working now', 'Up next', 'New release', 'data-k="task:'):
        check(gone not in up, f'no {gone}')
    words = lambda h: re.findall(r'class="grow ell">([^<]*)<', h)  # noqa: E731
    eq(words(up), ['2 working, 1 merging', '2 left, next release waits for 2'], 'parked tasks and the release are not counted')
    eq(words(pa), ['Paused · No agent is working', 'The queue is empty'], 'paused, and nothing left')
    eq(words(dn), ['No run is up', '2 left'], 'no run; with releases off nothing is said of them')
    eq(words(free), ['2 working, 1 merging', 'The queue is empty, release next'], 'a release with nothing before it')
    check('data-ctl="go_on"' in pa and 'data-ctl="pause"' not in pa and 'Last chat' not in pa, 'Go on while paused; no Last chat with no chat', pa)
    check('data-ctl=' not in dn, 'no run: neither Pause nor Go on', dn)
    check('[ob pause:]' in sent and '[ob stop:]' not in sent and 'chip busy' in sent, 'a Pause being sent shows on Home', sent)
    eq(['data-dict' in b for b in boxes], [False, True, True], "no dictation in Home's box; an open chat and a new chat's keep it")
    check('agentCard' not in W.PAGE.read_text(encoding='utf-8'), 'the agent card is gone')


def test_status_view_f124(tmp: Path) -> None:
    """F124 (F120-F122): Status in place of Activity and Agents, its sections in the TUI's order, the state pill, the
    Run card and the More… sheet from the one list of controls, and the swipe that follows the finger."""
    page = W.page_html().decode()
    body = page.split('function statusHTML(){', 1)[1].split('\n}\n', 1)[0]
    check('needsSec' not in body, 'C50: Status has no Needs you section')
    check('needsSec()' in page.split('function homeHTML(){', 1)[1].split('\n}\n', 1)[0], 'C50: Home still has it')
    for gone in ('agentsHTML', 'activityHTML', "['agents','Agents']", "['activity','Activity']"):
        check(gone not in page, f'no {gone}: one Status view')
    for part in ('data-sheet="run"', 'id="sheet"', 'role="dialog"', 'data-k="pill"', 'cardControls(S.snap)',
                 'controlGroups(S.snap)', "outbox(rq.name,rq.args,{ctl:"):
        check(part in page, f'the page has {part}')
    for ev in ('touchstart', 'touchmove', 'touchend', 'touchcancel'):
        check(f"document.addEventListener('{ev}'" in page, f'{ev} is handled')
    swipe = page.split('/* F124: a swipe right anywhere', 1)[1].split("addEventListener('pagehide'", 1)[0]
    check(swipe.count('preventDefault') == 1 and swipe.count('{passive:true}') == 3 and swipe.count('{passive:false}') == 1,
          'only its touchmove is not passive (B167)')
    for part in ('input,textarea,select', 'sideways(el)', 'translateX(', 'swipeOpens('):
        check(part in swipe, f'the swipe has {part}')
    if not shutil.which('node'):
        print('  (no node here: the Status script test is skipped)')
        return
    with mock.patch('agent_runner.plat.WINDOWS', False):
        cs = U.controls()
    with mock.patch('agent_runner.plat.WINDOWS', True):  # B163: no re-exec there, so no restart
        win = U.controls()
    fix2 = {'resume': [], 'unclaim': [{'id': 'F1', 'label': 'x'}] * 2, 'wip': []}
    snap = lambda up_, run, fix: {'up': up_, 'controls': cs, 'run': run, 'fixups': fix,  # noqa: E731
                                  **U.controls_shown(up_, run, fix)}
    with mock.patch('agent_runner.plat.WINDOWS', False):
        up = snap(True, {}, fix2)
        paused, none_up, nofix, forced = (snap(True, {'paused': True, 'stopping': True}, fix2), snap(False, {}, fix2),
                                          snap(True, {}, {}), snap(True, {'forced': True, 'stopping': True}, fix2))
    with mock.patch('agent_runner.plat.WINDOWS', True):
        winup = {**snap(True, {}, fix2), 'controls': win}
    got = logic_js([['viewOf', 'agents'], ['viewOf', 'activity'], ['viewOf', 'plan'],
                    ['runPill', {'up': True, 'run': {'state': 'Caps forced'}}], ['runPill', {'up': False}],
                    ['cardControls', up], ['cardControls', paused],
                    ['cardControls', none_up], ['controlGroups', up], ['controlGroups', nofix],
                    ['controlGroups', forced],
                    ['swipeTakes', 4, 3, False], ['swipeTakes', 40, 5, False], ['swipeTakes', -40, 5, False],
                    ['swipeTakes', -40, 5, True], ['swipeTakes', 40, 60, False],
                    ['swipeOpens', 100, 0, 280, False], ['swipeOpens', 180, 0, 280, False],
                    ['swipeOpens', 60, 0.8, 280, False], ['swipeOpens', -60, -0.8, 280, True],
                    ['swipeOpens', -60, 0, 280, True], ['atEnd', {'scrollHeight': 500, 'scrollTop': 400, 'clientHeight': 100}],
                    ['atEnd', {'scrollHeight': 500, 'scrollTop': 300, 'clientHeight': 100}],
                    ['controlGroups', winup]])
    eq(got[:3], ['plan', 'plan', 'plan'], 'the old views land on Work (F476)')
    eq(got[3:5], [{'text': 'Caps forced', 'cls': 'warn'}, {'text': 'Not up', 'cls': ''}], "the pill's words")
    eq(got[5], ['slot_remove', 'slot_add', 'pause', 'stop'], "the card's everyday buttons")
    eq(got[6], ['slot_remove', 'slot_add', 'go_on', 'stop_now', 'stop_undo'], 'paused and stopping: what undoes it')
    eq(got[7], ['start'], 'no run: Start the run')
    for groups, more, on in ((got[8], ['restart'], ''), (got[23], [], ' (Windows)')):
        keys = [(g['group'], [i['c']['key'] for i in g['items']]) for g in groups]
        eq(keys, [('Stop', ['stop', 'stop_now', 'suspend', 'shutdown']), ('Run', ['slot_add', 'slot_remove', 'slots_set', 'pause', 'force', 'upgrade', *more]),  # B763b
                  ('Fix up', ['unclaim'])], f'the sheet: Stop, Run and Fix up, what there is to fix only{on}')
    eq(got[8][2]['items'][0]['label'], 'Release stale claims (2)', 'with its count')
    eq([g['group'] for g in got[9]], ['Stop', 'Run'], 'nothing to fix: no Fix up')
    eq([i['c']['key'] for i in got[10][0]['items']], ['stop_now', 'stop_undo', 'suspend', 'shutdown'], 'stopping already: no Stop, Take the stop back')  # B763b
    check('caps_on' in [i['c']['key'] for i in got[10][1]['items']], 'caps forced: Caps back on')
    eq(got[11:16], ['wait', 'drag', '', 'drag', ''], 'right opens, left closes, a mostly vertical move does neither')
    eq(got[16:21], [False, True, True, False, True], 'it settles by how far and how fast')
    eq(got[21:23], [True, False], 'at the end, or not')



PULL_DRIVER = r"""
const page = require('fs').readFileSync(0, 'utf8').replace(/\r\n/g, '\n');
const logic = page.split('<script id="logic">')[1].split('</script>')[0];
const on = {}, els = {}, S = {}, PD = {}, HB = '', render = () => {}, atAll = () => false, getComputedStyle = () => ({overflowX: 'auto', transform: ''});
let DR = null, noClick = false, inside = ['#body'], refreshes = 0, reduced = false, wide = false, ran = [];
const calm = () => reduced, TOUCH = () => false, shiftOf = () => ({m41: 0, m42: 0}), dragEnd = () => { DR = null }, closeSheet = () => { S.sheet = '' };
let said = [];
const TK = {}, DK = {}, devTyped = () => false, keepTyped = () => true, toast = t => said.push(t), location = {reload() { refreshes++ }};
const elem = () => ({style: {}, offsetWidth: 280, scrollTop: 0, set: new Set(), setAttribute(k, v) { this[k] = v }, append() {},
  classList: {add() {}, remove() {}, toggle() {}}, firstElementChild: {style: {}}, lastElementChild: {textContent: ''},
  animate(f) { ran.push(f); return {cancel() {}} }, getBoundingClientRect: () => ({left: 0, top: 50, width: 400})});
const $ = k => els[k] = els[k] || elem();
const document = {body: {append() {}}, querySelector: () => ({offsetParent: wide ? null : {}}),
  createElement() { const p = elem(), c = p.set; p.classList = {add: x => c.add(x), remove: x => c.delete(x), toggle: (x, y) => y ? c.add(x) : c.delete(x)}; return p },
  addEventListener(t, f) { (on[t] = on[t] || []).push(f) }};
const box = {scrollTop: 0, scrollHeight: 3000, clientHeight: 600, scrollWidth: 400, clientWidth: 400, parentElement: document.body};
const el = {scrollHeight: 20, clientHeight: 20, parentElement: box, closest: s => s.split(',').some(x => inside.includes(x)) ? elem() : null};
let now = 0;
const fire = (t, x, y, n, o = {}) => { let kept = 0;
  on[t].forEach(f => f({target: el, touches: Array(n).fill().map((_, i) => ({identifier: i, clientX: x, clientY: y})), timeStamp: now += 100,
    cancelable: !o.late, preventDefault() { kept = 1 }}));
  return kept };
const at0 = page.indexOf('function newsRefresh(){'), real = page.slice(at0, page.indexOf('\n}', at0) + 3);
eval(logic + real + page.slice(page.indexOf('/* F124: a swipe right anywhere'), page.indexOf("addEventListener('pagehide'", page.indexOf('/* F124: a swipe right anywhere'))) + `
// a touch through these [dx, dy, options]: the moves it kept, the refreshes, whether it sprang back, how far the spinner got
function touch(moves, o = {}) {
  S.drawer = !!o.drawer; S.sheet = o.sheet || ''; S.obOpen = !!o.pop; DR = null; inside = o.inside || ['#body']; TK.rec = o.held && {}; S.f = {}; S.atts = {}; said = []; reduced = !!o.calm; wide = !!o.wide;
  box.scrollTop = o.top || 0; $('cview').hidden = !o.concept; refreshes = 0; ran = []; $('side').style.transform = ''; if (PULL) { PULL.style = {}; PULL.set.clear() }
  fire('touchstart', 100, 300, o.fingers || 1);
  const kept = moves.map(([dx, dy, m = {}]) => { if (m.top) box.scrollTop = m.top; if (m.hold) DR = {ready: true, hold: 1};
    if (m.open) S.sheet = 'run';
    if (m.second) { fire('touchstart', 9, 9, 2); return 's' } return fire('touchmove', 100 + dx, 300 + dy, 1, m) }).join('');
  const mid = PULL ? [PULL.style.transform || '', PULL.set.has('ready'), PULL.lastElementChild.textContent] : [];
  fire(o.end || 'touchend', 0, 0, 0); if (SW) kept += '!';
  return {kept, refreshes, back: ran.length, mid, go: !!PULL && PULL.set.has('go'), drawer: S.drawer, sheet: S.sheet, role: PULL && PULL.role, noClick, said};
}
const down = [[0, 5], [1, 9], [2, 60], [3, 90]];
const out = {
  pull: touch(down), side: touch(down, {inside: ['#side'], drawer: true}), wide: touch(down, {wide: true}),
  short: touch([[0, 9], [0, 60]]), undone: touch([[0, 9], [0, 90], [0, 30]]), cancel: touch(down, {end: 'touchcancel'}),
  second: touch([[0, 9], [0, 90], [0, 0, {second: true}], [0, 95]]), twoFingers: touch(down, {fingers: 2}),
  opened: touch([[0, 9], [0, 90, {open: true}]]), held: touch(down, {held: true}), calm: touch(down, {held: true, calm: true}),
  up: touch([[0, -9], [0, 90]]), sidewaysLeft: touch([[-12, 2], [0, 90]]), slant: touch([[9, 10], [9, 90]]), wideSide: touch([[12, 2], [0, 90]], {wide: true}),
  scrolledList: touch(down, {top: 40}), scrolledFirst: touch([[0, 5, {top: 3}], [0, 90]]), begun: touch([[0, 9, {late: true}], [0, 90]]),
  sheet: touch(down, {sheet: 'run'}), popup: touch(down, {pop: true}), concept: touch(down, {concept: true}), row: touch([[0, 5], [0, 9, {hold: true}], [0, 90]]),
  box: touch(down, {inside: ['#body', 'textarea']}), iframe: touch(down, {inside: ['#body', 'iframe']}), dock: touch(down, {inside: ['#dock']}), terminal: touch(down, {inside: ['#feedtouch']}),
  drawerSwipe: touch([[20, 0], [220, 90]]), drawerClose: touch([[-20, 0], [-220, 90]], {inside: ['#side'], drawer: true}), sheetSwipe: touch([[0, 20], [0, 120]], {sheet: 'run', inside: ['#sheet']}),
};
out.logic = [PULL_AT, pullAt(0), pullAt(-20), pullAt(70) < 70 && pullAt(200) > pullAt(70)];
console.log(JSON.stringify(out));process.exit(0)`);
"""


def test_pull_refresh_f401(tmp: Path) -> None:
    """F401: on touch, a pull down past the top refreshes once, as Refresh does; anything else is left alone."""
    page = W.page_html().decode()
    css = page.split('<style>', 1)[1].split('</style>', 1)[0]
    check('html,body{height:100%;overscroll-behavior:none;overflow:hidden' in css and 'overscroll-behavior:contain' in css, 'the lock stays (B160)')
    news = page.split('function newsRefresh(){', 1)[1].split('\n}', 1)[0]
    check('return false' in news and 'location.reload();return true' in news, 'Refresh says whether it is held')
    if not shutil.which('node'):
        print('  (no node here: the pull script test is skipped)')
        return
    p = subprocess.run(['node', '-e', PULL_DRIVER], input=page, capture_output=True, text=True, encoding='utf-8', timeout=30)
    check(p.returncode == 0, 'the pull script runs', p.stderr)
    got = json.loads(p.stdout or '{}')
    for k in ('pull', 'side', 'wide'):
        eq([got[k][x] for x in ('kept', 'refreshes', 'back', 'go')], ['0111', 1, 0, True], f'{k}: refreshes once, kept from scrolling once it is a pull')
    eq(got['pull']['mid'][1:] + [got['pull']['role']], [True, 'Let go to refresh', 'status'], 'ready past the threshold, and said')
    check(got['pull']['noClick'], 'letting go presses nothing')
    check(got['held']['said'], 'a held reload says why')
    eq([got['drawerClose'][x] for x in ('kept', 'refreshes', 'drawer')], ['11', 0, False], 'a drawer swipe still closes it')
    for k in ('short', 'undone', 'cancel', 'held', 'opened'):
        eq([got[k][x] for x in ('refreshes', 'back', 'go')], [0, 1, False], f'{k}: springs back')
    eq([got['second'][x] for x in ('kept', 'refreshes', 'back')], ['11s0', 0, 1], 'a second finger ends it')
    eq([got['calm'][x] for x in ('refreshes', 'back', 'go')], [0, 0, False], 'calm(): back at once')
    for k in ('up', 'sidewaysLeft', 'slant', 'wideSide', 'scrolledList', 'scrolledFirst', 'begun', 'sheet', 'popup', 'concept', 'row',
              'box', 'iframe', 'dock', 'terminal', 'twoFingers'):
        check('1' not in got[k]['kept'] and not got[k]['refreshes'] and not got[k]['back'], f'{k}: no pull', got[k])
    eq([got['drawerSwipe'][x] for x in ('kept', 'refreshes', 'drawer')], ['11', 0, True], 'a drawer swipe still opens the drawer')
    eq([got['sheetSwipe'][x] for x in ('refreshes', 'sheet')], [0, ''], 'a sheet swipe still closes the sheet')
    eq(got['logic'], [70, 0, 0, True], 'the threshold, and the spinner resists')


def test_page_gzip_b769a(tmp: Path) -> None:
    """B769a: the run app's page is compressed once and answered 304 to a browser that kept it, with the key only, direct,
    through Home and on Home's own pages; everything else stays no-store, and /events comes as it is sent."""
    from agent_runner import home as H
    from agent_runner import session_frame as F
    repo = fake_repo(tmp)
    snaps = [{'n': 1}]
    srv = W.serve('RT', 0, '127.0.0.1', snap=lambda: snaps[0])
    link = [(srv.server_address[1], 'RT')]
    hs = H.serve_home('HT', 0, '127.0.0.1', rows=lambda: [], roots=lambda: [repo], vitals=mock.Mock())
    hs.link, hs.project = (lambda root: link[0]), (lambda key: repo)
    run, home = (f'http://127.0.0.1:{x.server_address[1]}' for x in (srv, hs))

    def ask(url: str, **hd):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={k.replace('_', '-'): v for k, v in hd.items()}), timeout=10) as r:
                return r.status, r.headers, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.headers, e.read()

    def page(at: str, key: str, want: bytes, what: str) -> str:
        made.clear()
        F._gz_app.clear()
        code, hd, body = ask(f'{at}?t={key}')
        eq((code, hd['Content-Encoding'], body == want), (200, None, True), f'{what}: plain without Accept-Encoding')
        eq(ask(f'{at}?t={key}', Accept_Encoding='br, gzip;q=0')[1]['Content-Encoding'], None, f'{what}: plain when gzip is refused')
        for _ in range(2):
            code, hd, body = ask(f'{at}?t={key}', Accept_Encoding='gzip, deflate')
            eq((code, hd['Content-Encoding'], hd['Content-Length'], gzip.decompress(body) == want), (200, 'gzip', str(len(body)), True), f'{what}: compressed')
            check(len(body) < len(want) * .5, f'{what}: under half the size', (len(body), len(want)))
        eq(len(made), 1, f'{what}: compressed once')
        eq((hd['Cache-Control'], hd['Vary'], hd['Referrer-Policy']), ('private, no-cache', 'Accept-Encoding', 'no-referrer'), f'{what}: kept, asked each time')
        tag = hd['ETag']
        for match in (tag, 'W/' + tag, f'"x", {tag}'):
            code, hd, body = ask(f'{at}?t={key}', If_None_Match=match, Accept_Encoding='gzip')
            eq((code, body, hd['ETag'], hd['Cache-Control']), (304, b'', tag, 'private, no-cache'), f'{what}: 304 for {match}')
        eq(ask(f'{at}?t={key}', If_None_Match='"old"')[0], 200, f'{what}: another version is sent')
        for q in ('?t=wrong', ''):
            code, hd, body = ask(at + q, If_None_Match=tag, Accept_Encoding='gzip')
            eq((code, hd['ETag'], hd['Cache-Control']), (403, None, 'no-store'), f'{what}: a matching ETag does not stand in for the key ({q})')
        return tag

    def first_event(at: str, key: str) -> None:
        with urllib.request.urlopen(urllib.request.Request(f'{at}events?t={key}', headers={'Accept-Encoding': 'gzip'}), timeout=10) as r:
            eq((r.headers['Content-Encoding'], r.headers['Cache-Control']), (None, 'no-store'), 'events: never compressed or kept')
            eq(json.loads(r.readline()[6:])['n'], 1, 'the first event comes while the stream is open')
            r.readline()
            snaps[0] = {'n': 2}
            eq(json.loads(r.readline()[6:])['n'], 2, 'and the next when it changes')
            snaps[0] = {'n': 1}
        srv.snaps.at = 0.0
    real, made = gzip.compress, []
    try:
        with mock.patch.object(F.gzip, 'compress', lambda *a: made.append(1) or real(*a)):
            mine, homes = W.page_html(), H.home_page()
            run_tag = page(f'{run}/', 'RT', mine, 'the run')
            eq(page(f'{home}/p/proj/', 'HT', mine, 'through Home'), run_tag, 'the same page, the same ETag')
            home_tag = page(f'{home}/', 'HT', homes, 'Home')
            link[0] = None
            eq(page(f'{home}/p/proj/', 'HT', homes, 'a project with no run up'), home_tag, "Home's page")
            eq(ask(f'{home}/p/proj/?t=HT', If_None_Match=run_tag)[0], 200, "the run's page is not taken for it")
            link[0] = (srv.server_address[1], 'RT')
        for url in (f'{run}/snapshot?t=RT', f'{home}/p/proj/snapshot?t=HT', f'{home}/projects?t=HT', f'{run}/manifest.webmanifest?t=RT'):
            code, hd, _ = ask(url, Accept_Encoding='gzip')
            eq((code, hd['Cache-Control'], hd['ETag'], hd['Content-Encoding']), (200, 'no-store', None, None), f'{url.split("?")[0]}: no-store')
        first_event(f'{run}/', 'RT')
        first_event(f'{home}/p/proj/', 'HT')
    finally:
        hs.stop()
        srv.stop()


HOME_NEW_DRIVER = r"""
const page = require('fs').readFileSync(0, 'utf8').replace(/\r\n/g, '\n');
const grab = s => { const i = page.indexOf(s); if (i < 0) throw new Error('missing ' + s); return page.slice(i, page.indexOf('\n}\n', i) + 2) + '\n' };
const line = s => { const i = page.indexOf(s); if (i < 0) throw new Error('missing ' + s); return page.slice(i, page.indexOf('\n', i)) + '\n' };
const logic = page.split('<script id="logic">')[1].split('</script>')[0].replace(/if\(typeof module[^\n]*/, '');
const acts = [], ta = {value: '', classList: {contains: () => false}};
const env = {S: {snap: {at: 'now', sessions: [], needs: [], queue: [], concepts: []}, view: 'home', thread: null, ctx: null,
    atts: {}, ob: [], feeds: {}, sent: {}, came: []},
  HI: {i: null}, FD: {}, HOME_PAGE: false, HB: '', TOUCH: () => false, store: {get: () => '', set: () => {}},
  document: {querySelector: () => ta}, setTimeout: () => 0, Date, Math, JSON,
  outbox: (name, args, o) => { const it = {cid: 'k' + (acts.length + 1), name, args, state: 'sending', at: Date.now(), ...o}; acts.push([name, args, !!o.newchat]); env.S.ob.push(it); return it },
  chats: () => [], loadFeed: () => {}, render: () => {}};
const known = new Proxy(env, {has: () => true, get: (t, k) => k === Symbol.unscopables ? undefined : k in t ? t[k] : k in globalThis ? globalThis[k] : () => ''});
env.env = env;
const won = line('  if(it.newchat&&j.name)');
new Function('known', 'env', 'with (known) {' + logic + line('const DRAFT_KEY=') + line('const boxKey=') + line('const feedOf=')
  + line('const bornNow=') + line('const starting=') + line('const BORN_MS=') + line('const standRows=')
  + line('const sessionOf=') + grab('function addSent(') + line('function carrySent(')
  + line('function open(') + grab('async function send(') + line('function newChat(') + line("  S.waitNew={known,at:Date.now(),ph:'@'+it.cid};open(")
  + 'function answered(it,j){const now=Date.now();' + won + '}'
  + 'env.send=send;env.answered=answered;env.standRows=standRows;env.state=n=>feedState({stand:String(n||"")[0]==="@",starting:starting(n),born:bornNow(n),info:null,chat:true});}')(known, env);
const S = env.S, out = {};
(async () => {
  ta.value = 'what is up'; await env.send();
  const it = S.ob[0];
  out.sent = [acts, S.view, S.thread, env.state(S.thread), env.standRows().map(r => r.name)];
  S.ob = [];  // settled: the outbox drops it
  env.answered(it, {ok: true, name: 'c7', ask: 'what is up', at: Date.now() / 1000});
  out.named = [S.thread, env.state(S.thread), env.standRows().map(r => [r.name, r.say])];
  console.log(JSON.stringify(out));
})().catch(e => { console.error(e.stack); process.exit(1) });
"""


def test_home_new_chat_f196f(tmp: Path) -> None:
    """F196f: a new chat started from Home's message box goes as one from +: new_control through the outbox without
    waiting, one stand-in opened in place that reads Starting the chat, and the server's answer (its name) turns that one
    row into the chat, still starting, never Loading or ended."""
    if not shutil.which('node'):
        print('  (no node here: the Home new chat test is skipped)')
        return
    (tmp / 'driver.js').write_text(HOME_NEW_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js')], input=W.PAGE.read_text(encoding='utf-8'),
                       capture_output=True, text=True, encoding='utf-8', timeout=60)
    eq(r.returncode, 0, 'node runs the Home new chat')
    if r.returncode:
        print(r.stderr)
        return
    o = json.loads(r.stdout)
    acts, view, thread, state, rows = o['sent']
    eq([(a[0], a[1].get('wait'), a[2]) for a in acts], [('new_control', False, True)], 'one new_control, not waited for, a new chat')
    eq((view, thread, state, rows), ('home', '@k1', 'starting', ['@k1']), 'opened in place as one stand-in, Starting the chat')
    eq(o['named'], ['c7', 'starting', [['c7', 'what is up']]], 'its name keeps one row, still starting, with the same words')
    # the server: Home's chip (quick_ask) and its box (new_control with ask) are answered as + is: a name, the ask, at
    said = {'ok': True, 'code': 0, 'out': 'control 7 started', 'argv': []}
    fake_repo(tmp)
    srv = W.serve('RT', 0, '127.0.0.1', snap=lambda: {})
    try:
        with mock.patch.object(U, 'call', lambda argv, *a, **k: dict(said, argv=argv)), mock.patch.object(U, 'name_new', lambda r, ask: r):
            url = f'http://127.0.0.1:{srv.server_address[1]}/act?t=RT'
            asks = {'plus': ('new_control', {}), 'box': ('new_control', {'ask': 'what is up'}), 'chip': ('quick_ask', {'key': 'since'})}
            got = {k: post(url, {'name': n, 'args': {**a, 'wait': False}, 'cid': k})[1] for k, (n, a) in asks.items()}
    finally:
        srv.stop()
    eq({k: (v['ok'], v['name'], '--no-wait' in v['argv'], bool(v['at'])) for k, v in got.items()},
       {k: (True, 'c7', True, True) for k in got}, "Home's new chats get the name and time + gets, started without waiting")


CONCEPT_DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const slice = (a, b) => page.slice(page.indexOf(a), page.indexOf(b, page.indexOf(a)));
const logic = page.split('<script id="logic">')[1].split('</script>')[0].replace(/if\(typeof module[^\n]*/, '');
const posted = [], opened = [];
const S = {snap: {needs: [{id: 'K14', label: 'CONCEPT'}, {id: 'B1', label: 'CONFIRM'}],
  concepts: [{id: 'K14', concept: 'K14', news: 'updated', news_words: 'new option', version: '2-ab'}]}};
const env = {S, tq: p => p, fetch: (p, o) => { posted.push([p, JSON.parse(o.body)]); return Promise.resolve({}) },
  shotEnd: () => {}, askLoad: () => {}, openSheet: (k, id) => opened.push(id)};
const known = new Proxy(env, {has: () => true, get: (t, k) => k === Symbol.unscopables ? undefined : k in t ? t[k] : k in globalThis ? globalThis[k] : () => ''});
const out = new Function('known', 'with (known) {' + logic + slice('const needOf=', '\n') + '\n' + slice('function needOpen(', '\n') + '\n'
  + slice('function conceptOpened(', '\n/*') + '\nreturn {needOpen, conceptSeen}}')(known);
const r = {seenOther: out.conceptSeen('B1', S.snap.concepts), seenNone: out.conceptSeen('K14', [{id: 'K14', news: '', version: '1-x'}])};
out.needOpen('B1'); r.afterOther = posted.length;
out.needOpen('K14'); r.posted = posted.slice(); r.badge = [S.snap.concepts[0].news, S.snap.concepts[0].news_words];
out.needOpen('K14'); r.again = posted.length; r.opened = opened;
console.log(JSON.stringify(r));
"""


def test_concept_popup_f197b3(tmp: Path) -> None:
    """F197b3: opening a concept's details popup (Home's card or its Concepts row, both `data-needopen`) posts
    concept_opened with its row's version and clears New/Updated at once; another item and a seen concept post
    nothing; View is a plain link that opens the page and clears nothing."""
    page = W.PAGE.read_text(encoding='utf-8')
    view = re.search(r'<a class="btn" href="\$\{esc\(view\)\}"[^`]*`', page)
    check(bool(view) and 'needopen' not in view.group(0) and 'conceptOpened' not in view.group(0), 'View opens the page only')
    if not shutil.which('node'):
        print('  (no node here: the concept popup script test is skipped)')
        return
    (tmp / 'driver.js').write_text(CONCEPT_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node opens the concept popup', r.stderr[-1500:])
    if r.returncode:
        return
    o = json.loads(r.stdout)
    eq((o['seenOther'], o['seenNone'], o['afterOther']), (None, None, 0), 'only a New or Updated concept is told')
    eq(o['posted'], [['act', {'name': 'concept_opened', 'args': {'concept': 'K14', 'version': '2-ab'}}]], 'the popup posts concept_opened')
    eq(o['badge'], ['', ''], 'New/Updated clear at once')
    eq((o['again'], o['opened']), (1, ['B1', 'K14', 'K14']), 'a second open posts nothing more; the popup opens each time')


CHAT_OPEN_DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const slice = (a, b) => page.slice(page.indexOf(a), page.indexOf(b, page.indexOf(a)));
const opened = [], posted = [];
let live = ['c7'];
const S = {sheet: 'need', snap: {needs: [{id: 'B1', label: 'CONFIRM', chat: 7}, {id: 'B2', label: 'CONFIRM'}],
  concepts: [{id: 'K14', concept: 'K14', title: 'Lazy', chat: 7}, {id: 'K15', concept: 'K15', title: 'Wide'}]}};
const env = {S, chats: () => live.map(name => ({name})), open: n => opened.push(n), closeSheet: () => { S.sheet = '' },
  ctxKey: c => '+' + c.kind + ':' + c.id, document: {querySelector: () => null}, kbFocus: () => {},
  outbox: (n, a) => posted.push(n), fetch: () => posted.push('fetch')};
const known = new Proxy(env, {has: () => true, get: (t, k) => k === Symbol.unscopables ? undefined : k in t ? t[k] : k in globalThis ? globalThis[k] : () => ''});
const out = new Function('known', 'with (known) {' + slice('function chatOpenOf(', '\n') + '\n' + slice('function chatRowOf(', '\n') + '\n'
  + slice('function about(', '\n}\n') + '\n}\nreturn {about, chatOpenOf, chatRowOf}}')(known);
const r = {};
out.about('concept:0'); r.concept = [opened.slice(), S.ctx || null, S.sheet];
r.need = [out.chatOpenOf(out.chatRowOf('B1')), out.chatOpenOf(out.chatRowOf('B2')), opened.slice()];
out.about('concept:1'); r.none = [opened.slice(), S.ctx && S.ctx.id];
live = []; S.ctx = null; opened.length = 0;
r.ended = out.chatOpenOf(out.chatRowOf('B1')); out.about('concept:0'); r.endedConcept = [opened.slice(), S.ctx && S.ctx.id];
r.posted = posted;
console.log(JSON.stringify(r));
"""


def test_chat_opens_open_chat_f209c1(tmp: Path) -> None:
    """F209c1: Chat on a Needs you or Concepts row whose snapshot names 'chat' opens that chat and posts nothing; with
    none, or once that chat has left the chat list, it is the new chat view as before."""
    page = W.PAGE.read_text(encoding='utf-8')
    check("chatOpenOf(chatRowOf(tid)))return;" in page, 'a Needs you card\'s Chat tries the open chat first')
    if not shutil.which('node'):
        print('  (no node here: the open chat script test is skipped)')
        return
    (tmp / 'driver.js').write_text(CHAT_OPEN_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs Chat', r.stderr[-1500:])
    if r.returncode:
        return
    o = json.loads(r.stdout)
    eq(o['concept'], [['c7'], None, ''], "a concept's Chat opens c7, no new chat view, the sheet closes")
    eq(o['need'], [True, False, ['c7', 'c7']], "a Needs you row's Chat opens c7; a row with no chat does not")
    eq(o['none'], [['c7', 'c7', '+concept:K15'], 'K15'], 'a concept with no open chat gets the new chat view')
    eq((o['ended'], o['endedConcept']), (False, [['+concept:K14'], 'K14']), 'an ended chat falls back to the new chat view')
    eq(o['posted'], [], 'nothing is posted')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_login_banner_f126a), in_tmp(test_need_popup_f162), in_tmp(test_sheet_over_sheet_f189b), in_tmp(test_need_picture_moves_f189), in_tmp(test_need_give_page_f175a), in_tmp(test_give_route_f175a), in_tmp(test_need_note_f162), in_tmp(test_pitch_note_f162a), in_tmp(test_shot_f162), in_tmp(test_home_switcher_f134), in_tmp(test_switch_home_f203), in_tmp(test_home_actions_f150), in_tmp(test_home_screen_b179), in_tmp(test_project_name_b153), in_tmp(test_home_f426a), in_tmp(test_status_view_f124), in_tmp(test_pull_refresh_f401), in_tmp(test_page_gzip_b769a), in_tmp(test_home_new_chat_f196f), in_tmp(test_concept_popup_f197b3), in_tmp(test_chat_opens_open_chat_f209c1)]))
