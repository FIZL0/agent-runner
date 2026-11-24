"""The run page's Settings search after a trip away from Settings (F204b).

    python3 tests/test_web_settings_away.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from _check import check, eq, report
from _web import in_tmp

from agent_runner import web as W  # noqa: E402

DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const logic = page.split('<script id="logic">')[1].split('</script>')[0].replace(/if\(typeof module[^\n]*/, '');
const slice = (a, b) => page.slice(page.indexOf(a), page.indexOf(b, page.indexOf(a)));
const line = a => slice(a, '\n') + '\n';
let now = 1e12, S, field, drawn = 0, dead = [];
const Date = {now: () => now}, ears = {}, on = (k, f) => { (ears[k] = ears[k] || []).push(f) };
const document = {hidden: false, title: 't', activeElement: null, addEventListener: on, querySelector: s => s === '[data-f="setq"]' ? field : null}, addEventListener = on;
const mk = () => { const m = {}; return {m, get: k => m[k] || '', set(k, v) { m[k] = v }} };
const store = mk(), tabStore = mk(), HKEY = 'p', HI = {i: null}, OB_KEY = 'ob', DRAFT_KEY = k => k, boxKey = () => 'home';
const PD = {}, selecting = () => false, MO = {}, TOUCH = () => true, typingIn = () => false, isNew = n => n[0] === '+', keepPlace = () => {}, loadFeed = () => {}, loadSettings = () => {}, loadTools = () => {};
const takePlace = () => { S.view = 'settings'; S.thread = null }, placeLoad = () => {}, HOME_PAGE = false, HB = '', location = {hash: '#settings'};
const others = {'set:project:run.slots': '7', planq: 'merge', padd: '/x'};
const fire = k => (ears[k] || []).forEach(f => f({}));
eval(logic + line('const LATER_KEY=') + slice('function keepTyped(', 'function newsRefresh(') + line('function open(n,named)') + line('function goView(v)')
  + slice('function settingsTrip(', '/* F133, F201: drag')
  + slice("addEventListener('hashchange'", '/* F150: a link to an item')
  + slice('function render(force){', '  if(!force&&') + ' drawn++ }');
const start = () => { S = {f: {...others, setq: 'cap'}, view: 'settings', thread: null, atts: {}, ob: [], setOpen: {}, setChanged: true, snap: {}}; field = {value: 'cap'}; document.hidden = false; render(true) };
const MIN = 60000, SHORT = 5 * MIN - 1, LONG = 5 * MIN, out = {};
const said = () => { const {setq, ...rest} = S.f; return [setq, field.value, JSON.stringify(rest) === JSON.stringify(others) && S.setChanged] };
const trip = (leave, back) => [SHORT, LONG].map(ms => { start(); leave(); now += ms; back(); return said() });
const hide = () => { document.hidden = true; fire('visibilitychange') }, show = () => { document.hidden = false; fire('visibilitychange') };
out.view = trip(() => goView('home'), () => goView('settings'));
out.link = trip(() => goView('plan'), () => fire('hashchange'));
out.thread = trip(() => open('c1'), () => goView('settings'));
out.back = trip(() => open('c1'), () => { S.thread = null; render(true) });
out.hidden = trip(hide, show);
out.bfcache = trip(() => fire('pagehide'), () => fire('pageshow'));
out.drawnHidden = trip(() => { hide(); render() }, show);
out.reload = trip(() => { if (!keepTyped()) throw 'not kept'; S = {f: {}, view: 'settings', thread: null, snap: {}, atts: {}, setOpen: {}, ob: []} },
  () => { takeTyped(); S.setChanged = true; field.value = S.f.setq; render(true) });
start(); goView('home'); now += 3 * MIN; keepTyped(); S = {f: {}, view: 'home', thread: null, snap: {}, atts: {}, setOpen: {}, ob: [], setChanged: true}; takeTyped(); render(true); now += 2 * MIN; goView('settings'); out.around = said();
start(); goView('home'); now += 3 * MIN; hide(); now += 1 * MIN; show(); now += 1 * MIN; goView('settings'); out.both = said();
start(); goView('home'); now += 3 * MIN; goView('settings'); now += 3 * MIN; goView('home'); now += 3 * MIN; goView('settings'); out.twice = said();
start(); now += 60 * MIN; render(); show(); out.stayed = said();
start(); hide(); now += LONG; const n = drawn; show(); out.redrawn = drawn > n;
console.log(JSON.stringify(out));
"""


def test_search_after_trip_f204b(tmp: Path) -> None:
    """F204b: 5 minutes or more away from Settings clears its search, by any way out and back; less keeps it."""
    if not shutil.which('node'):
        return
    (tmp / 'away.js').write_text(DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'away.js'), str(W.PAGE)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node goes away and comes back', r.stderr[-1500:])
    if r.returncode:
        return
    o = json.loads(r.stdout)
    kept, gone = ['cap', 'cap', True], ['', '', True]  # the last: other fields' words and the Changed filter stay
    for way in ('view', 'link', 'thread', 'back', 'hidden', 'bfcache', 'drawnHidden', 'reload'):
        eq(o[way], [kept, gone], f'{way}: under 5 minutes keeps the search, 5 clears it')
    eq(o['around'], gone, 'a reload while away does not start the time anew')
    eq(o['both'], gone, 'nor does the page hidden and shown while away')
    eq(o['twice'], kept, 'two short trips are not one long one')
    eq(o['stayed'], kept, 'an hour in Settings keeps it')
    check(o['redrawn'], 'the list is drawn anew when the page shows again')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_search_after_trip_f204b)]))
