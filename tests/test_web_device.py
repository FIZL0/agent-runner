"""The run page, a device's page under Devices (B818a): what it draws, and where Back and a reload lead.

    python3 tests/test_web_device.py
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from _check import check, eq, report

from agent_runner import web as W
from _web import in_tmp

DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const cut = (a, b) => page.slice(page.indexOf(a), page.indexOf(b, page.indexOf(a)));
const H = {projects: [{key: 'a'}, {key: 'b'}], tab: 'devices', devices: [{id: 'local', ok: true, host: 'desk', verdict: {}}, {id: 'p1', ok: false, host: 'lap', verdict: {said: 'Its Home refused the token in the link', level: 'bad'}}], alerts: []};
let HB = '/', HKEY = '', HOME_PAGE = true, T = 'TOK', all = true, I = {back: '<svg/>'}, S = {drawer: true}, draws = 0, hits = [], answer = {}, went = [], on = {};
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => '&#' + c.charCodeAt(0) + ';');
const tq = p => p + (p.includes('?') ? '&' : '?') + 't=' + T, render = () => { draws++ }, atAll = () => all, oneProject = () => false, plainErr = e => e.message;
const card = (h, c = '', a = '') => `<div class="card ${c}" ${a}>${h}</div>`, emptyCard = t => card(t), kept = {}, tabStore = {set: (k, v) => { kept[k] = v }};
const homeErr = () => '', offHTML = () => '', addEventListener = (n, f) => { on[n] = f };
const goUp = stay => { if (!all) { went.push('up'); all = true; H.tab = ''; devSet('') } }, goDown = () => went.push('down');
// the browser's history, with Back as it comes: a popstate with the entry's state
const hist = [null]; let at = 0;
const history = {get state() { return hist[at] }, pushState(s) { hist.length = ++at; hist.push(s) }, replaceState(s, _, u) { hist[at] = s; if (u) urls.push(u) }, back() { at--; on.popstate({state: hist[at]}) }, forward() { at++; on.popstate({state: hist[at]}) }};
let posts = [], toasts = [], urls = [];
const location = {hash: '', pathname: '/', search: '?t=TOK'}, toast = (m, bad) => toasts.push([m, !!bad]);
const fetch = async (u, o) => { hits.push(u); if (o) posts.push([u, JSON.parse(o.body)]); const a = typeof answer === 'function' ? await answer(u) : answer; if (a instanceof Error) throw a; return {json: async () => a} };
eval([cut('function meterHTML', 'const hobOf'), cut('/* B818a: Device Vitals', '\nfunction chatRow('), cut("addEventListener('popstate'", 'function goProject')].join('\n').replace(/^const /gm, 'var ').replace(/^let /gm, 'var '));
eval(cut('function deviceCard', 'const ASKS_SHOWN').replace(/^const /gm, 'var '));
eval(cut('const ASKS_SHOWN', '/* a project with no run up').replace('const ASKS_SHOWN', 'var ASKS_SHOWN').replace(/^const homeErr.*$/m, ''));
const projectsNow = () => [], projectAsks = () => [], homeNeeds = () => 0, PGROUPS = [], exampleOffer = () => '', EX = {}, askRow = () => '';
I.alert = '';
const CLEAN = [{id: 't1', path: '/t<1>', size: 2 ** 30, ask: false, why: 'ended'}, {id: 'w1', path: '/w1', size: 2 ** 20, ask: true, why: 'holds files'}];
const FULL = {ok: true, host: 'desk<b>', here: true, verdict: {said: 'Room for 3 more agents', level: 'ok'}, headroom: {said: 'Room for 3 more agents', limits: {memory: 3, cpu: 5}},
  machine: {cpu: {pct: 41.4, threads: 16, load: 2.5, temp: 92, cores: [10, 80]}, mem: {total: 32 * 2 ** 30, avail: 8 * 2 ** 30}, disk: {path: '/', free: 100 * 2 ** 30, total: 400 * 2 ** 30},
    gpus: [{name: 'RX', temp: 50, pct: null}], sensors: [{chip: 'k10', label: 'Tctl', c: 60}], top: [{name: 'node', pid: 7, cpu: 3, rss: 2 ** 30}]},
  spark: {cpu: [1, null, 3], gpu: [4]}, footprint: {worktrees: 2 ** 31, tmp: 0, logs: null, wip: ['x'], total: 2 ** 31, largest: [{path: '/big', size: 2 ** 41}]}, clean: [{id: 'q', path: '/x', size: 1}],
  sessions: [{project: 'one', name: 's1', what: 'B1', cpu: 12, rss: 2 ** 20}], running: [{key: 'one'}]};
const tick = () => new Promise(r => setTimeout(r, 0));
(async () => {
  const out = {};
  out.card = deviceCard(H.devices[0]);
  answer = FULL; devOpen('local');
  out.loading = devHTML(); out.titleFirst = allTitle(); await tick();
  out.hit = hits[0]; out.html = devHTML(); out.title = allTitle(); out.back = devBackBtn(); out.drawer = S.drawer;
  DV.more = {machine: true, foot: true}; out.more = devHTML();
  // Back, Forward, the Back button, another tab, down and up again, a reload
  out.hist = hist.slice(); history.back(); out.b1 = [H.tab, H.dev, devOn()]; history.forward(); out.f1 = [H.tab, H.dev];
  devBack(); out.b2 = [H.tab, H.dev, at];
  history.forward(); devLeave(); out.b3 = [H.dev, at];
  history.forward(); H.tab = ''; devLeave(); out.left = [H.dev, history.state];
  H.tab = 'devices'; devOpen('local'); history.pushState({level: 'in'}, ''); all = false; out.off = [devOn(), devBackBtn()]; history.back(); out.up = [H.tab, H.dev, went];
  H.tab = ''; H.dev = ''; hits = []; devPlace(history.state); await tick(); out.reload = [H.tab, H.dev, hits.length];
  hits = []; history.back(); out.noload = hits.length;
  // not answering, then Home itself out of reach (what was read stays), then a late answer of the device before
  answer = {ok: false, out: 'timed out', id: 'p2'}; devOpen('p2'); await tick(); out.not = devHTML();
  devBack(); devOpen('p1'); await tick(); out.refused = devHTML(); out.notTitle = allTitle();
  devBack(); answer = FULL; devOpen('local'); await tick(); answer = new Error('down'); devLoad(); await tick(); out.unreached = devHTML();
  answer = {ok: false, out: 'no such device'}; devLoad(); await tick(); out.home = devHTML();
  let late; answer = u => u.includes('p9') ? {ok: true, host: 'nine'} : new Promise(r => { late = r });
  devLoad(); devBack(); devOpen('p9'); await tick(); late(FULL); await tick(); out.late = allTitle();
  // B818b: + slot, Clean and the old link
  devBack(); answer = {...FULL, running: [{key: 'one'}, {key: 'two'}], clean: CLEAN}; devOpen('p1'); await tick(); out.two = devHTML(); devBack();
  answer = {...FULL, running: [], clean: []}; devOpen('p1'); await tick(); out.none = devHTML(); devBack();
  answer = u => u.includes('/vitals/device') ? {...FULL, clean: CLEAN} : {ok: true, out: 'slots: 3'};
  devOpen('p1'); await tick(); out.ready = devHTML();
  posts = []; const p1 = devSlot('one'); out.adding = devHTML(); devSlot('one'); devClean('list'); await p1; await tick();
  out.slot = [posts, devSaid('room')];
  devClean('list'); out.list = devHTML(); devTick('t1', false); devTick('w1', true);
  const more = [{id: 'new', path: '/new', size: 5, ask: false, why: 'late'}, CLEAN[0]];
  answer = {...FULL, clean: more}; await devLoad(); out.fresh = devHTML();
  posts = []; devClean('cancel'); out.cancel = [devHTML(), posts.length];
  answer = {...FULL, clean: CLEAN}; await devLoad(); devClean('list'); devTick('t1', false); devTick('w1', true);
  answer = new Error('down'); posts = []; await devClean('go'); await tick(); out.lost = [devHTML(), posts];
  answer = u => u.includes('/vitals/device') ? {...FULL, clean: [CLEAN[0]]} : {ok: false, out: 'Removed 0 of 1\nnot removed: /w1', removed: []};
  posts = []; await devClean('go'); await tick(); out.gone = [devHTML(), posts];
  devClean('list'); devTick('t1', false); posts = []; await devClean('go'); out.empty = [DV.pick, posts.length];
  let slow; answer = u => u.includes('/vitals/device') ? FULL : new Promise(r => { slow = r });
  const p2 = devSlot('one'); await tick(); devBack(); devOpen('local'); slow({ok: true, out: 'late\nx'}); await p2; out.left2 = [toasts, DV.act];
  devBack(); H.tab = ''; H.alerts = [{what: 'hot', device: 'p1', clean: true}]; out.alert = projectsHTML();
  location.hash = '#device-p%2F1'; out.link = [devLink(), H.tab, H.dev, history.state, urls.at(-1)];
  location.hash = '#home'; out.nolink = devLink(); HKEY = 'k'; location.hash = '#device-x'; out.inproj = devLink();
  console.log(JSON.stringify(out));
})();
"""


def test_device_b818a(tmp: Path) -> None:
    """B818a: a device opens as a page under Devices, in the app's parts; Back and a reload keep the place."""
    (tmp / 'page.html').write_bytes(W.page_html(home=True))
    (tmp / 'd.js').write_text(DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'd.js'), str(tmp / 'page.html')], capture_output=True, text=True, encoding='utf-8', timeout=60)
    check(r.returncode == 0, 'node runs the page script', r.stderr[-1500:])
    o = json.loads(r.stdout)
    check('data-devopen="local"' in o['card'] and 'device?id=' not in o['card'], 'a tap on a device stays in the app', o['card'])
    check('Loading' in o['loading'] and o['titleFirst'] == '<span class="tt">desk</span>', 'its name at once, Loading until it answers')
    eq(o['hit'], '/dev/local/vitals/device?t=TOK', 'it reads the device with the token')
    h = o['html']
    for s in ('desk&#60;b&#62;', '· this one', 'v-ok">Room for 3 more agents', 'Smallest of: memory 3 · cpu 5', '41%', '16 threads', 'class="b" style="width:92%',
              '24.0 GB / 32.0 GB', '100.0 GB free', 'Runner footprint · 2.0 GB', 'Session temp folders', 'wip/ branches', 'one s1 · B1', '12.0% · 1 MB'):
        check(s in h, f'the page shows {s}', h)
    eq((h.count('class="spark"'), h.count('data-devmore'), h.count('aria-expanded="false"')), (1, 2, 2), 'a sparkline where there are two points; two folds')
    check('Logs' not in h and '<b>desk<' not in h, 'what was not read is left out, names are escaped')
    check('device?id=' not in h and 'data-devslot="one"' in h and 'data-devclean="list"' in h, 'the actions are here, with no link to the old page')
    check('Per core' not in h and all(s in o['more'] for s in ('Per core', 'All sensors', 'node (7)', '/big', '2.0 TB', 'Less')), 'More shows the rest')
    check('Back to Devices' in o['back'] and o['drawer'] is False, 'the top bar leads back, the drawer is closed')
    eq(o['hist'], [{'level': 'all', 'tab': 'devices'}, {'level': 'all', 'tab': 'devices', 'dev': 'local'}], 'a history entry of its own')
    eq((o['b1'], o['f1'], o['b2']), (['devices', '', ''], ['devices', 'local'], ['devices', '', 0]), 'Back, Forward and Back to Devices')
    eq(o['b3'], ['', 0], 'Devices in the sidebar is the way back too')
    eq(o['left'], ['', {'level': 'all', 'tab': ''}], 'Overview takes the entry over')
    eq((o['off'], o['up']), (['', ''], ['devices', 'local', ['up']]), 'up again by Back: the device')
    eq((o['reload'], o['noload']), (['devices', 'local', 1], 0), 'a reload opens it; the list asks for no device')
    check('v-bad">Not answering' in o['not'] and 'timed out' in o['not'] and 'data-devload' in o['not'], 'not answering, why, and Retry', o['not'])
    check('Its Home refused' in o['refused'] and 'lap' in o['notTitle'], "a listed one says what the list says", o['refused'])
    check('Could not reach Runner Home: down' in o['unreached'] and 'Headroom' in o['unreached'], 'what was read stays')
    check('no such device' in o['home'] and 'Not answering' not in o['home'] and 'Headroom' in o['home'], "Home's own refusal is no word of the device")
    eq(o['late'], '<span class="tt">nine</span>', 'a late answer of another device is dropped')


    # B818b
    check('+ slot · one' in o['two'] and '+ slot · two' in o['two'] and '+ slot</button>' in o['ready'], 'a + slot for each run up, named when there are two')
    check('No run up on this device' in o['none'] and 'Nothing to clean.' in o['none'], 'no run up, nothing to clean: said so')
    check('Clean 1.0 GB safely…' in o['ready'], 'Clean says what is safe', o['ready'])
    check('data-devslot="one" disabled' in o['adding'] and 'busy' in o['adding'], 'the press shows at once', o['adding'])
    eq(o['slot'][0], [['/dev/p1/act?t=TOK', {'project': 'one', 'name': 'slots', 'arg': '+1'}]], '+ slot goes once, to that device')
    check('slots: 3' in o['slot'][1] and 'v-bad' not in o['slot'][1], 'and its answer shows')
    ticked = lambda s, i: f'data-f="devtick:{i}" checked' in s
    check(ticked(o['list'], 't1') and 'devtick:w1' in o['list'] and not ticked(o['list'], 'w1') and '/t&#60;1&#62;' in o['list'], 'the safe ones come ticked')
    check(not ticked(o['fresh'], 't1') and ticked(o['fresh'], 'w1') and '/new' not in o['fresh'], 'a refresh keeps the list and the ticks')
    check('devtick' not in o['cancel'][0] and o['cancel'][1] == 0 and 'Clean 1.0 GB' in o['cancel'][0], 'Cancel closes it and removes nothing')
    want = [['/dev/p1/vitals/clean?t=TOK', {'items': ['w1']}]]
    eq(o['lost'][1], want, 'Remove ticked sends what is ticked, only that')
    check(ticked(o['lost'][0], 'w1') and not ticked(o['lost'][0], 't1') and 'Could not reach Runner Home: down' in o['lost'][0], 'out of reach: the ticks stay')
    eq(o['gone'][1], want, 'and go again on the next press')
    check('devtick' not in o['gone'][0] and 'not removed: /w1' in o['gone'][0], 'answered: the list closes, what was not removed is said')
    eq(o['empty'], [None, 0], 'nothing ticked: nothing sent')
    eq(o['left2'], [[['late', False]], {'busy': '', 'said': {}}], 'an answer for a device that was left is a toast')
    check('data-devopen="p1">Clean' in o['alert'] and 'device?id=' not in o['alert'], "an alert's Clean opens the device here", o['alert'])
    eq(o['link'], [True, 'devices', 'p/1', {'level': 'all', 'tab': 'devices', 'dev': 'p/1'}, '/?t=TOK'], 'an old link opens the device; the # goes, the token stays')
    eq((o['nolink'], o['inproj']), (False, False), 'no other # does')


def test_device_wired_b818a(tmp: Path) -> None:
    page = W.PAGE.read_text(encoding='utf-8')
    check('setInterval(()=>{if(devOn())devLoad()},30000)' in page, 'it refreshes every 30 s while it is open')
    check('devLink()||devPlace(history.state)' in page and all(s in page for s in ('devSlot(x.dataset.devslot)', 'devClean(x.dataset.devclean)', 'devTick(x.dataset.devtick,x.checked)')), 'the presses and the old link are wired')
    check('devPlace(history.state)' in page and "devLeave()" in page, 'a reload and the tabs are wired')
    eq(page.count('${devBackBtn()}') + page.count(':devBackBtn()}'), 2, "both top bars, Home's and a project's")


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_device_b818a), in_tmp(test_device_wired_b818a)]))
