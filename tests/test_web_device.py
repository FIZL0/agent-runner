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
const history = {get state() { return hist[at] }, pushState(s) { hist.length = ++at; hist.push(s) }, replaceState(s) { hist[at] = s }, back() { at--; on.popstate({state: hist[at]}) }, forward() { at++; on.popstate({state: hist[at]}) }};
const fetch = async u => { hits.push(u); const a = typeof answer === 'function' ? await answer(u) : answer; if (a instanceof Error) throw a; return {json: async () => a} };
eval([cut('function meterHTML', 'const hobOf'), cut('/* B818a: Device Vitals', '\nfunction chatRow('), cut("addEventListener('popstate'", 'function goProject')].join('\n').replace(/^const /gm, 'var ').replace(/^let /gm, 'var '));
eval(cut('function deviceCard', 'const ASKS_SHOWN').replace(/^const /gm, 'var '));
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
  history.forward(); H.tab = ''; devLeave(); out.left = [H.dev, history.state];
  H.tab = 'devices'; devOpen('local'); history.pushState({level: 'in'}, ''); all = false; out.off = [devOn(), devBackBtn()]; history.back(); out.up = [H.tab, H.dev, went];
  H.tab = ''; H.dev = ''; hits = []; devPlace(history.state); await tick(); out.reload = [H.tab, H.dev, hits.length];
  hits = []; history.back(); out.noload = hits.length;
  // not answering, then Home itself out of reach (what was read stays), then a late answer of the device before
  answer = {ok: false, out: 'timed out', id: 'p2'}; devOpen('p2'); await tick(); out.not = devHTML();
  devBack(); devOpen('p1'); await tick(); out.refused = devHTML(); out.notTitle = allTitle();
  devBack(); answer = FULL; devOpen('local'); await tick(); answer = new Error('down'); devLoad(); await tick(); out.unreached = devHTML();
  let late; answer = u => u.includes('p9') ? {ok: true, host: 'nine'} : new Promise(r => { late = r });
  devLoad(); devBack(); devOpen('p9'); await tick(); late(FULL); await tick(); out.late = allTitle();
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
    check('device?id=local&#38;t=TOK">Clean or add a slot' in h and 'data-slot' not in h, 'read only: the old page has the actions')
    check('Per core' not in h and all(s in o['more'] for s in ('Per core', 'All sensors', 'node (7)', '/big', '2.0 TB', 'Less')), 'More shows the rest')
    check('Back to Devices' in o['back'] and o['drawer'] is False, 'the top bar leads back, the drawer is closed')
    eq(o['hist'], [{'level': 'all', 'tab': 'devices'}, {'level': 'all', 'tab': 'devices', 'dev': 'local'}], 'a history entry of its own')
    eq((o['b1'], o['f1'], o['b2']), (['devices', '', ''], ['devices', 'local'], ['devices', '', 0]), 'Back, Forward and Back to Devices')
    eq(o['left'], ['', {'level': 'all', 'tab': ''}], 'Overview takes the entry over')
    eq((o['off'], o['up']), (['', ''], ['devices', 'local', ['up']]), 'up again by Back: the device')
    eq((o['reload'], o['noload']), (['devices', 'local', 1], 0), 'a reload opens it; the list asks for no device')
    check('v-bad">Not answering' in o['not'] and 'timed out' in o['not'] and 'data-devload' in o['not'], 'not answering, why, and Retry', o['not'])
    check('Its Home refused' in o['refused'] and 'lap' in o['notTitle'], "a listed one says what the list says", o['refused'])
    check('Could not reach Runner Home: down' in o['unreached'] and 'Headroom' in o['unreached'], 'what was read stays')
    eq(o['late'], '<span class="tt">nine</span>', 'a late answer of another device is dropped')


def test_device_wired_b818a(tmp: Path) -> None:
    page = W.PAGE.read_text(encoding='utf-8')
    check('setInterval(()=>{if(devOn())devLoad()},30000)' in page, 'it refreshes every 30 s while it is open')
    check('devPlace(history.state)' in page and "devLeave()" in page, 'a reload and the tabs are wired')
    eq(page.count('${devBackBtn()}') + page.count(':devBackBtn()}'), 2, "both top bars, Home's and a project's")


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_device_b818a), in_tmp(test_device_wired_b818a)]))
