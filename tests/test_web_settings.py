"""The run page, settings area (agent_runner/page/*-settings.*): split from test_web.py (C41b), tests unchanged.

    python3 tests/test_web_settings.py
"""
from __future__ import annotations

import datetime as dt
import html
import json
import os
import random
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
from test_web_sheet import DOM  # noqa: E402
from _web import TODO, fake_repo, get, post, LOGIC_DRIVER, logic_js, in_tmp  # noqa: E402


def test_no_settings_f178(tmp: Path) -> None:
    """F178: with no runner.toml, the one warning is in the snapshot, its status lines, the page and the TUI."""
    repo = fake_repo(tmp)
    said = 'no settings found, so no test gate and nothing is pushed'
    snap = U.snapshot(up=False, links={}, windows={})
    eq((snap['no_settings'], snap['status'][1]), (said, said), 'no runner.toml: said, right under the run state')
    check(not any('WARNING no test gate' in l for l in snap['status']), 'once, not beside the no-gate warning', snap['status'])
    from agent_runner import tui
    eq(tui.RunPage.row(None, 1, said)[0][1], 'yellow', 'the TUI marks it')
    check('S.snap.no_settings' in W.PAGE.read_text(encoding='utf-8') and 'p.no_settings' in W.PAGE.read_text(encoding='utf-8'),
          'the Run card and All projects show it')
    from agent_runner import cmds, home
    eq(home.project_row('p', repo, info=lambda r: {'up': False}, needs=lambda r: (0, []))['no_settings'], said,
       'Home has it beside Start')
    row = cmds.picker_rows([], repo, info=lambda r: {'up': False})[0]
    check(said in cmds.picker_text([row], 0) and said in cmds.launcher_text(row), 'the picker says it')
    from agent_runner import theme
    paint = cmds.PickerPaint(theme.get('terminal'), 256, 120)
    for sel in (0, 1):
        check(said in cmds.picker_text([row], sel, paint), 'and in colour, selected or not')
    check(said in cmds.launcher_text(row, '', paint), 'and in the coloured launcher')
    eq(U.no_settings(st={'no_settings': False}), '', 'a run started with settings from elsewhere says so itself')
    eq(U.no_settings(st={'no_settings': True}), said, 'or that it has none')
    (repo / 'runner.local.toml').write_text('[run]\ntest = "true"\n', encoding='utf-8')
    eq(U.no_settings(CF.Config(repo)), '', 'a gate from runner.local.toml: not said')
    (repo / 'runner.local.toml').unlink()
    (repo / 'runner.toml').write_text('', encoding='utf-8')
    eq(U.no_settings(CF.Config(repo)), '', 'an empty runner.toml is settings')
    eq(U.no_settings(st={'no_settings': True}), said, "the run's own word wins")


def test_trusted_networks_f136(tmp: Path) -> None:
    """F136: the run's own page opens without its key on `[ui] trusted_networks`; the key always by default."""
    fake_repo(tmp)
    token = W.web_token()
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {})
    base, ts = f'http://127.0.0.1:{srv.server_address[1]}', '100.101.1.2'
    try:
        trusted_checks(srv, base, lambda nets: S.C.raw['ui'].update(trusted_networks=nets), '/snapshot', token)
        eq(asked(f'{base}/t//s1/', ts, srv), 403, 'a session needs the key too')
        S.C.raw['ui']['trusted_networks'] = ['tailnet']
        got = []
        with mock.patch.object(srv.terms, 'ttyd', lambda n: {'ok': True, 'port': 9}), \
                mock.patch.object(W.session_frame, 'frame', lambda h, port, path, n, look: (got.append(path), h.send(200, '{}'))):
            eq(asked(f'{base}/t//s1/?x=1', ts, srv), 200, 'and opens on a trusted network')
        eq(got, [f'/t/{token}/s1/?x=1'], "at the ttyd's own path")
        eq(W.shown_links([], [f'http://100.101.1.1:8770/?t={token}', f'http://10.0.0.5:8770/?t={token}'], https=lambda p, t: []),
           ['http://100.101.1.1:8770/', f'http://10.0.0.5:8770/?t={token}', f'http://localhost:8770/?t={token}'], 'status drops the key of a trusted link only')
    finally:
        S.C.raw['ui']['trusted_networks'] = []
        srv.stop()


def test_https_link_b130(tmp: Path) -> None:
    fake_repo(tmp)
    serve = {'TCP': {'8771': {'HTTPS': True}, '8791': {'HTTPS': True}},
             'Web': {'box.tail.ts.net:8771': {'Handlers': {'/': {'Proxy': 'http://127.0.0.1:8770'}}},
                     'box.tail.ts.net:8791': {'Handlers': {'/': {'Proxy': 'http://127.0.0.1:8790'}}}}}
    eq(W.serve_https_urls(serve, 8770, 'TK'), ['https://box.tail.ts.net:8771/?t=TK'],
       'the https port that proxies to the web port gives the https link')
    eq(W.serve_https_urls(serve, 8780, 'TK'), [], 'no serve for that port: no https link')
    eq(W.serve_https_urls({}, 8770, 'TK'), [], 'nothing served: none')
    plain = {'TCP': {'80': {'HTTP': True}}, 'Web': {'box.tail.ts.net:80': {'Handlers': {'/': {'Proxy': 'http://127.0.0.1:8770'}}}}}
    eq(W.serve_https_urls(plain, 8770, 'TK'), [], 'a plain-http serve gives no https link')
    on443 = {'TCP': {'443': {'HTTPS': True}}, 'Web': {'box.tail.ts.net:443': {'Handlers': {'/': {'Proxy': 'http://localhost:8770'}}}}}
    eq(W.serve_https_urls(on443, 8770, 'TK'), ['https://box.tail.ts.net/?t=TK'], 'port 443 needs no port')
    ran = lambda argv, **k: subprocess.CompletedProcess(
        argv, 0, json.dumps(serve if argv[1] == 'serve' else {'BackendState': 'Running'}), '')
    eq(W.tailscale_https_urls(8770, 'TK', run=ran), ['https://box.tail.ts.net:8771/?t=TK'], 'read from tailscale')
    W.url_file().parent.mkdir(parents=True, exist_ok=True)
    W.url_file().write_text('http://box:8770/?t=TK\nhttp://10.0.0.5:8770/?t=TK\n', encoding='utf-8')
    with mock.patch.object(S, 'run_up', return_value=True), \
            mock.patch.object(W, 'tailscale_https_urls', lambda port, t: W.serve_https_urls(serve, port, t)):
        eq(W.page_line(), 'run page: https://box.tail.ts.net:8771/?t=TK (or http://box:8770/?t=TK or http://localhost:8770/?t=TK)',
           'status prints the https link first')
    # B129: the run log's address line at the start names the https link first too; web.url keeps the http ones
    with mock.patch.dict(W.os.environ, {'AGENT_RUNNER_NO_WEB': ''}), mock.patch.object(W, 'lan_ip', lambda: ''), \
            mock.patch.dict(S.C.run, {'web': True, 'web_port': 0}), mock.patch.object(S, 'log') as lg, \
            mock.patch.object(W, 'tailscale_https_urls', lambda port, t: [f'https://box.tail.ts.net:8771/?t={t}']):
        srv = W.start_web()
    try:
        line = next(str(c.args[0]) for c in lg.call_args_list if 'run page:' in str(c.args[0]))
        check(line.startswith(f'run page: https://box.tail.ts.net:8771/?t={W.web_token()} or http://'),
              'B129: the run log prints the https link first', line)
        check(all(u.startswith('http://') for u in W.url_file().read_text(encoding='utf-8').split()),
              'web.url keeps the http addresses (Home reads its port from them)')
    finally:
        srv.stop()
    # B129: an insecure context (plain http) gets the needs-https message, even where recognition exists
    if shutil.which('node'):
        got = logic_js([['micProblem', False, True]])
        check('needs https' in got[0], 'B129: insecure context: the mic says it needs https', got[0])


FAKE_TAILSCALE = r'''#!PYTHON
import json, sys
from pathlib import Path
here, a = Path(__file__).parent, sys.argv[1:]
d = json.loads((here / 'state.json').read_text())
with open(here / 'calls', 'a') as f:
    f.write(' '.join(a) + chr(10))
if a == ['status', '--json']:
    print(json.dumps({'BackendState': d['state'], 'Self': {'DNSName': 'box.tail.ts.net.'}, 'CertDomains': d['certs']}))
elif a == ['serve', 'status', '--json']:
    print(json.dumps(d['serve']))
elif a[0] == 'serve' and d['refuse']:
    sys.exit('Access denied: serve config denied')
elif a[0] == 'serve' and (p := next(x for x in a if x.startswith('--https=')).split('=')[1]):
    s = d['serve']
    if a[-1] == 'off':
        s['TCP'].pop(p), s['Web'].pop('box.tail.ts.net:' + p)
    else:
        s.setdefault('TCP', {})[p] = {'HTTPS': True}
        s.setdefault('Web', {})['box.tail.ts.net:' + p] = {'Handlers': {'/': {'Proxy': a[-1]}}}
    (here / 'state.json').write_text(json.dumps(d))
'''


def test_tailnet_https_f96(tmp: Path) -> None:
    if os.name == 'nt':
        return  # the fake is a script on PATH
    fake_repo(tmp)
    eq(CF.DEFAULTS['run']['web_https'], True, '[run] web_https is on by default')
    real = os.environ['PATH']
    bin_ = tmp / 'bin'
    bin_.mkdir()
    state, calls = bin_ / 'state.json', bin_ / 'calls'
    (bin_ / 'tailscale').write_text(FAKE_TAILSCALE.replace('PYTHON', sys.executable), encoding='utf-8')
    (bin_ / 'tailscale').chmod(0o755)

    def fake(serve=None, **kw):
        state.write_text(json.dumps({'state': 'Running', 'certs': ['box.tail.ts.net'], 'refuse': False,
                                     'serve': serve or {}, **kw}), encoding='utf-8')
        calls.write_text('', encoding='utf-8')

    def web_rules():
        return json.loads(state.read_text(encoding='utf-8'))['serve'].get('Web') or {}

    def changes():
        return [c for c in calls.read_text(encoding='utf-8').splitlines() if c.startswith('serve --')]

    def hold_pair():
        """Two ports in a row, bound for the whole test so that no other process gets them. Bound but not listening:
        a connection is refused, as on a free port. The run's server can bind the first beside its holder (both have
        SO_REUSEADDR; only Linux lets it, so elsewhere the first is let go). The second has not, so no other test
        run gets the pair. Below the ports outgoing connections get (32768 up on Linux, 49152 up elsewhere): many of
        those, just closed ones too, can leave no pair free there."""
        while True:
            a, b = socket.socket(), socket.socket()
            a.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            port = random.randrange(20000, 32000)
            try:
                a.bind(('0.0.0.0', port))
                b.bind(('0.0.0.0', port + 1))
            except OSError:
                a.close()
                b.close()
                continue
            if sys.platform != 'linux':
                a.close()
            return port, a, b
    port, *held = hold_pair()
    log: list[str] = []

    def start(home=0, site=(), path='', **settings):
        log.clear()
        env = {'AGENT_RUNNER_NO_WEB': '', 'AGENT_RUNNER_NO_SERVE': '', 'PATH': path or f'{bin_}{os.pathsep}{real}'}
        with mock.patch.dict(os.environ, env), mock.patch.object(W, 'home_port', lambda: home), \
                mock.patch.dict(S.C.run, {'web': True, 'web_port': port, **settings}), \
                mock.patch.object(W, 'site_urls', lambda root=None, https=None: list(site)):
            return W.start_web()

    with mock.patch.object(S, 'log', log.append), mock.patch.object(W, 'lan_ip', lambda: ''), \
            mock.patch.object(S, 'run_up', return_value=True), \
            mock.patch.object(W, 'HOME_LOOK', 999), \
            mock.patch.dict(os.environ, {'PATH': f'{bin_}{os.pathsep}{real}', 'AGENT_RUNNER_NO_SERVE': ''}):
        own = f'https://box.tail.ts.net:{port + 1}/?t={W.web_token()}'
        made = {f'box.tail.ts.net:{port + 1}': {'Handlers': {'/': {'Proxy': f'http://127.0.0.1:{port}'}}}}
        on = f'serve --bg --https={port + 1} http://127.0.0.1:{port}'
        off = f'serve --https={port + 1} off'

        other = {'TCP': {'9': {'HTTPS': True}}, 'Web': {'box.tail.ts.net:9': {'Handlers': {'/': {'Proxy': 'http://127.0.0.1:2'}}}}}
        fake(other)
        srv = start()
        eq(changes(), [on], 'the run makes the rule')
        check(log[-1].startswith(f'run page: {own} or http://'), 'the run log has the https address first', log)
        with mock.patch.object(W, 'site_urls', lambda: []):
            check(W.page_line().startswith(f'run page: {own} (or http://'), 'and so has status', W.page_line())
        with mock.patch.object(W, 'site_urls', lambda: ['http://box:1/p/a/?t=H']):
            eq(W.page_line(), f'run page: {own} (or http://box:1/p/a/?t=H or http://localhost:1/p/a/?t=H)', "ahead of Runner Home's http one")
        check(W.url_file().read_text(encoding='utf-8').startswith('http://'), 'web.url stays http')
        srv.stop()
        eq((changes()[1:], web_rules()), ([off], other['Web']), 'the stop turns it off, and no other rule')
        eq(W.page_https.made_rule(), None, 'nothing is left recorded')

        fake()
        srv = start()
        srv.https = False  # a run that did not stop
        srv.stop()
        eq(web_rules(), made, 'a crash leaves the rule')
        srv = start()
        eq(changes(), [on], 'the next run takes it over')
        srv.stop()
        eq(web_rules(), {}, 'and turns it off')

        fake()
        srv = start()
        srv.https = False
        srv.stop()
        with mock.patch.object(W.page_https, 'is_ours', wraps=W.page_https.is_ours) as ours:
            eq(start(web=False), None, 'a run with no page')
        check(ours.called and web_rules() == {}, 'turns off what the crashed one left', web_rules())

        fake()
        srv = start()
        srv.https = False
        srv.stop()
        start(home=port).stop()
        eq((web_rules(), W.page_https.made_rule()), (made, None), "Runner Home has that port by now: the rule is Home's")

        fake()
        srv = start()
        srv.https = False
        srv.stop()
        W.page_https.keep_rule({**W.page_https.made_rule(), 'run': 'another project'})
        start(web=False)
        eq(web_rules(), made, "another project's rule is not turned off")
        start().stop()
        eq(web_rules(), {}, 'but the run that has its port by now takes it over')

        fake()
        srv = start()
        changed = {'TCP': {str(port + 1): {'HTTPS': True}},
                   'Web': {f'box.tail.ts.net:{port + 1}': {'Handlers': {'/': {'Proxy': 'http://127.0.0.1:1'}}}}}
        fake(changed)
        srv.stop()
        eq((changes(), web_rules()), ([], changed['Web']), 'a rule someone changed meanwhile is left alone')

        fake()
        srv = start()
        check(srv.go_private(), 'Runner Home was installed')
        eq(web_rules(), {}, 'the run takes its rule with it')
        srv.stop()

        fake({'TCP': {'443': {'HTTPS': True}}, 'Web': {'box.tail.ts.net:443': {'Handlers': {'/': {'Proxy': f'http://127.0.0.1:{port}'}}}}})
        srv = start()
        check(f'https://box.tail.ts.net/?t={W.web_token()} or http' in log[-1], "the person's own rule is used", log)
        srv.stop()
        eq((changes(), len(web_rules())), ([], 1), 'and left alone')

        fake()
        start(home=port + 5).stop()
        start(web_https=False).stop()
        eq(changes(), [], "only Home opens it, or web_https = false: none made")

        def http_only(why: str, **kw) -> None:
            srv = start(**kw)
            srv.stop()
            said = [x for x in log if 'http only' in x]
            check(len(said) == 1 and why in said[0], f'http only: {why}', log)
            check('https://' not in log[-1] and 'run page: http://' in log[-1], 'the page is served over http', log)
            check(W.page_https.made_rule() is None and off not in changes(), 'nothing to turn off', changes())
        empty = tmp / 'empty'
        empty.mkdir()
        (empty / 'git').symlink_to(shutil.which('git'))
        fake()
        http_only('no tailscale here', path=str(empty))
        fake(state='NeedsLogin')
        http_only('not connected')
        fake(certs=None)
        http_only('HTTPS certificates are not enabled')
        fake(refuse=True)
        http_only('refused: Access denied: serve config denied')
        fake(changed)
        http_only('for something else')
        eq(web_rules(), changed['Web'], 'a rule on the next port is left alone')
        fake()
        held[1].listen()
        http_only('is taken')
    for one in held:
        one.close()


PARTS_DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const k = {...JSON.parse(process.argv[3]), name: 'Release by itself', desc: 'd', home: 'everyone', value: false, source: 'default'};
const logic = page.split('<script id="logic">')[1].split('</script>')[0].replace(/if\(typeof module[^\n]*/, '');
const slice = (a, b) => page.slice(page.indexOf(a), page.indexOf(b));
const S = {f: {}, ob: [], setOpen: {}, set: {tables: [{table: 'run', keys: [k]}]}}, esc = t => String(t).replace(/"/g, '&quot;');
const document = {querySelectorAll: () => []}, render = () => {}, toast = t => { throw new Error(t) };
let saved = [];
const draftSet = (id, side, d) => saved.push([side, d.text]), closeSheet = () => {};
eval(logic + slice('const settingId=', 'const resetBtn=') + slice('function saveSetting(', 'function resetSetting(') + `
const row = text => { S.f = {}; k.value = JSON.parse(text); k.has_project = k.value !== false; k.project = k.value; return settingRow(k, {}) };
const out = {rows: {}};
for (const t of ['false', '{"every":10}', '{"idle":true}', '{"every":10,"idle":true}']) out.rows[t] = row(t);
row('false');
const move = (part, x, side, now) => savePart({value: String(x), checked: x, dataset: {id: 'run.auto_release', side, setpart: part, ...(now ? {now: ''} : {})}});
move('every', 10, 'project', true); move('idle', true, 'project', true); move('every', 0, 'project', true); move('idle', false, 'project', true);
out.saved = saved; saved = [];
row('{"idle":true}'); move('idle', false, 'project', false); const before = saved.length; saveSetting('run.auto_release', 'project');
out.sheet = before ? ['saved early'] : saved;
out.readonly = settingRow({...k, locked: 'a run is up'}, {});
console.log(JSON.stringify(out));`);
"""


RELEASES_DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const set = JSON.parse(require('fs').readFileSync(process.argv[3], 'utf8'));
const logic = page.split('<script id="logic">')[1].split('</script>')[0].replace(/if\(typeof module[^\n]*/, '');
const slice = (a, b) => page.slice(page.indexOf(a), page.indexOf(b));
const S = {f: {}, ob: [], setOpen: {}, set, snap: {}}, esc = t => String(t).replace(/"/g, '&quot;'), I = {chev: ''};
const card = t => `<div>${t}</div>`, emptyCard = card, obCards = () => '', controlOf = () => null, foldIn = (k, t) => t, SHEETS = {};
eval(logic + slice('const settingId=', 'function saveSetting(') + `
const at = k => set.tables.find(t => t.table === 'run').keys.find(x => x.key === k);
const draw = (q, changed) => { S.f = {setq: q}; S.setChanged = changed; return settingsHTML() };
const out = [];
for (const on of [true, false, true]) {
  at('releases').value = on; at('releases').source = on ? 'default' : 'project';
  out.push({page: draw('', false), named: draw('release by itself', false), key: draw('auto_release', false), word: draw('releases', false), kinds: draw('features, fixes', false), changed: draw('', true), kept: at('auto_release').value});
}
console.log(JSON.stringify(out));`);
"""


def test_manage_releases_f193(tmp: Path) -> None:
    """F193: with Manage releases off, Settings lists, finds and counts nothing about releases but its own switch."""
    repo = fake_repo(tmp)
    (repo / 'runner.toml').write_text('[run]\nslots = 4\nauto_release = { every = 10 }\n', encoding='utf-8')
    if not shutil.which('node'):
        return
    snap = CF.settings_snapshot(repo)
    (tmp / 'set.json').write_text(json.dumps(snap), encoding='utf-8')
    (tmp / 'releases.js').write_text(RELEASES_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'releases.js'), str(W.PAGE), str(tmp / 'set.json')], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node draws Settings', r.stderr[-900:])
    if r.returncode:
        return
    draws = json.loads(r.stdout)
    auto, switch, words = 'data-k="set:run.auto_release"', 'data-k="set:run.releases"', 'Also concepts and releases.'
    for d, on in zip(draws, (True, False, True)):
        say = f'Manage releases {"on" if on else "off"}: '
        check(switch in d['page'], say + 'its switch shows')
        for view in ('page', 'named', 'key', 'changed'):
            eq(auto in d[view], on, say + f'Release by itself, in {view}')
        check(switch in d['word'], say + 'a search finds the switch')
        for view in ('page', 'word', 'kinds'):
            eq(words in d[view], on, say + f'the kinds row names releases, in {view}')
        check('Features, fixes, tests' in d['kinds'] and 'Also concepts' in d['kinds'], say + 'that row stays')
        eq('data-k="setkinds:build"' in d['word'], on, say + 'a search for releases finds that row')
        eq(d['kept'], {'every': 10}, say + 'the value is kept')
        eq(re.search(r'Changed (\d+)', d['page'])[1], '2', say + 'the count')  # slots, and Release by itself or the switch
        eq(switch in d['changed'], not on, say + 'the switch is in Changed once it is off')
        check(not on or re.search(r'<option value="10" selected', d['page']), say + 'Release by itself has its value')
    eq(draws[2], draws[0], 'turned back on, everything is as it was')


CLEAR_DRIVER = DOM + r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const set = JSON.parse(require('fs').readFileSync(process.argv[3], 'utf8'));
const logic = page.split('<script id="logic">')[1].split('</script>')[0].replace(/if\(typeof module[^\n]*/, '');
const slice = (a, b) => page.slice(page.indexOf(a), page.indexOf(b, page.indexOf(a)));
const S = {f: {}, ob: [], setOpen: {}, set, snap: {}, view: 'settings'}, esc = t => String(t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;'), I = {chev: '', x: 'x'};
const card = t => `<div>${t}</div>`, emptyCard = card, obCards = () => '', controlOf = () => null, foldIn = (k, t) => t, SHEETS = {};
const field = () => root.querySelectorAll('[data-f]').find(x => x.dataset.f === 'setq'), x = () => root.querySelectorAll('[data-setqclear]')[0];
const ears = {}, n = null, body = root, document = {get activeElement() { return doc.activeElement }, querySelector: field, createElement: () => ({content: new Node(11, '#fragment'), set innerHTML(h) { this.content.innerHTML = h }}),
  addEventListener: (k, f) => { (ears[k] = ears[k] || []).push(f) }};
const kbFocus = e => e.focus(), $ = () => root; let press;
eval(logic + slice('const settingId=', 'function saveSetting(') + slice('function setHTML(', '/* F83') + slice('function keepFields(', '/* a press under way')
  + slice('function fieldHTML(', '/* F189b: a press in the sheet') + slice("document.addEventListener('input',", "document.addEventListener('paste'") + slice("/* F114, F204a", "document.addEventListener('visibilitychange'")
  + "function render() { const keep = keepFields(body), h = settingsHTML(); " + slice('const drew=', '\n') + " if (drew) keep() }"
  + "press = q => { " + slice("if(q('[data-setqclear]'))", '\n') + " };");
const now = () => [!x().hasAttribute('hidden'), root.text.length], type = v => { field().typed = v; field().writes = 0; field().focused = 0; field().selectionStart = 1; field().matches = s => s === '[data-f]'; ears.input[0]({target: field()}) };
const out = {}; render(); const f = field(); out.start = now(); f.focus();
const fresh = () => { const t = new Node(11, '#fragment'); t.innerHTML = root._h; return root.childNodes.every((c, i) => c.isEqualNode(t.childNodes[i])) };
const kept = () => [field() === f, f.isConnected, doc.activeElement === f, f.writes, f.focused, fresh()];
type('r'); out.one = [now(), kept()]; type('releases'); out.more = [now(), kept()]; type('zzzz'); out.none = [now(), kept()]; type(''); out.empty = [now(), kept()];
type('releases'); let stopped = 0; ears.pointerdown[0]({target: {closest: s => s.includes('[data-setqclear]')}, preventDefault: () => stopped++}); out.holds = stopped;
out.label = [x().getAttribute('aria-label'), x().nodeName];
press(s => s === '[data-setqclear]'); out.cleared = [now(), S.f.setq, f.value, field() === f, doc.activeElement === f, f.focused, fresh()];
type('r'); doc.activeElement = null; press(s => s === '[data-setqclear]'); out.unfocused = [now(), S.f.setq, field().value, doc.activeElement === field()];
console.log(JSON.stringify(out));
"""


def test_search_clear_f204a(tmp: Path) -> None:
    """F204a: the x in the Settings search shows only with text and clears it; the field in use stays the same element."""
    css = (W.PAGE).read_text(encoding='utf-8')
    check('.setq .fld::-webkit-search-cancel-button{display:none}' in css and 'width:var(--tap);height:var(--tap)' in css.split('.setq .x{')[1].split('}')[0],
          'the native x is hidden, and ours is the size of a finger')
    if not shutil.which('node'):
        return
    repo = fake_repo(tmp)
    (tmp / 'set.json').write_text(json.dumps(CF.settings_snapshot(repo)), encoding='utf-8')
    (tmp / 'clear.js').write_text(CLEAR_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'clear.js'), str(W.PAGE), str(tmp / 'set.json')], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node types in the search', r.stderr[-1500:])
    if r.returncode:
        return
    o = json.loads(r.stdout)
    same = [True, True, True, 0, 0, True]  # the same element, in the page, in focus, never written to or focused again; the list as drawn anew
    shown, whole = o['start']
    eq(shown, False, 'no x with no text')
    for k in ('one', 'more', 'none'):
        eq((o[k][0][0], o[k][1]), (True, same), f'typing ({k}): the x shows and the field stays')
    check(o['more'][0][1] < whole and o['none'][0][1] < o['more'][0][1], 'the list is what matches')
    eq(o['empty'], [[False, whole], same], 'deleting the words hides it')
    eq((o['holds'], o['label']), (1, ['Clear search', 'button']), 'a press on it leaves the focus where it is')
    eq(o['cleared'], [[False, whole], '', '', True, True, 0, True], 'it empties the search, shows the full list and keeps focus and field')
    eq(o['unfocused'], [[False, whole], '', '', True], 'pressed with focus elsewhere, focus goes to the field')


def test_settings_f97(tmp: Path) -> None:
    """F97: the Settings view: every key with its value, source and default; a device value saved and reset in place in
    runner.local.toml, its comments kept; a project value committed in runner.toml (F173); bad values refused."""
    repo = fake_repo(tmp)
    toml, local = repo / 'runner.toml', repo / 'runner.local.toml'
    toml.write_text('[run]\nslots = 4\nslotz = 1\n\n[rnu]\nslots = 9\n\n[git]\npush = false\n', encoding='utf-8')
    mine = '# my laptop\n[run]\nslots = 2   # it is small\nlinks = [\n  "data",  # one\n]  # big\n\n# the end\n[ui]\ntheme = "light"\n'
    local.write_text(mine, encoding='utf-8')
    token = W.web_token()
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {})
    base = f'http://127.0.0.1:{srv.server_address[1]}'
    ran = []
    U.settings_start()

    def key(table, k):
        d = json.loads(get(f'{base}/settings?t={token}')[1])
        return next(x for t in d['tables'] if t['table'] == table for x in t['keys'] if x['key'] == k), d

    def act_(name, **args):
        return post(f'{base}/act?t={token}', {'name': name, 'args': args})[1]
    try:
        slots, d = key('run', 'slots')
        eq((slots['value'], slots['source'], slots['project'], slots['device'], slots['default'], slots['applies'], slots['type']),
           (2, 'device', 4, 2, 3, 'now', 'number'), 'slots: the device value is in force, over the project and the default')
        push, _ = key('git', 'push')
        eq((push['value'], push['source'], push['off']), (False, 'project', True), 'push = false, from the project')
        quiet, _ = key('ui', 'chat_quiet')
        eq((quiet['value'], quiet['source'], quiet['applies']), ('6h', 'default', 'now'), 'chat_quiet: the default, 6h')
        eq(key('run', 'web_port')[0]['applies'], 'next run', 'web_port cannot change while the run is up')
        eq((quiet['name'], quiet['home']), ('Gray out a chat after', 'device'), 'with its name and home')
        check('bottom of Chats' in quiet['desc'], 'and its description', quiet)
        eq([(u['table'], u['key'], u['file']) for u in d['unknown']], [('run', 'slotz', 'runner.toml'), ('rnu', '', 'runner.toml')],
           'an unknown key is flagged, and an unknown table')
        check('did you mean' in d['unknown'][0]['why'], 'and says why', d['unknown'])
        every = {(t, k) for t, keys in CF.DEFAULTS.items() for k in keys}
        eq({(t['table'], k['key']) for t in d['tables'] for k in t['keys']}, every, 'every key `settings` lists')
        eq([f'[{t}] {k}' for t, k in sorted(every) if CF.setting_problem(t, k, CF.DEFAULTS[t][k])], [], 'every default is valid')
        with mock.patch.object(U, 'RUN', [lambda argv: (ran.append(argv), (0, 'added C9 it'))[1]]), \
                mock.patch.object(S, 'run_up', lambda: True):
            eq(act_('setting_device', table='run', key='slots', value=5)['ok'], True, 'a device save')
            eq(key('run', 'slots')[1]['waits'], [], 'slots applies now: nothing waits')
            eq(local.read_text(encoding='utf-8'), mine.replace('slots = 2 ', 'slots = 5 '), 'edits that value only, comments kept')
            eq(ran, [['slots', '5']], 'slots applies now, through the slots action')
            eq(act_('setting_device', table='run', key='links', value=['a b'])['ok'], True, 'a list over several lines')
            check('# one\nlinks = ["a b"]  # big' in local.read_text(encoding='utf-8'), 'becomes one line, its comments kept')
            eq(act_('setting_device', table='git', key='land_edited', value='wip')['ok'], True, 'a table not there yet')
            eq(key('run', 'slots')[1]['waits'], [], 'F202a: the run reads them by itself')
            eq(act_('setting_device', table='run', key='web_port', value=8999)['ok'], True, 'one it cannot take')
            eq(key('run', 'slots')[1]['waits'], ['run.web_port'], 'waits for the next run')
            eq(act_('setting_reset', table='run', key='web_port')['ok'], True, 'reset again')
            eq(CF.tomllib.loads(local.read_text(encoding='utf-8'))['git'], {'land_edited': 'wip'}, 'is added')
            eq(key('run', 'slots')[0]['value'], 5, 'the page reads the new value')
            for t, k in (('run', 'slots'), ('run', 'links'), ('git', 'land_edited')):
                eq(act_('setting_reset', table=t, key=k)['ok'], True, f'reset [{t}] {k}')
            left = local.read_text(encoding='utf-8')
            check(all(x not in left for x in ('slots', 'links', 'land_edited')) and '# my laptop' in left and '# the end' in left
                  and 'theme = "light"' in left, 'a reset takes the key out, nothing else', left)
            eq((key('run', 'slots')[0]['source'], ran[-1]), ('project', ['slots', '4']), 'and the project value is in force again')
            ran.clear()
            before = toml.read_text(encoding='utf-8')
            git(repo, 'add', 'runner.toml')
            git(repo, 'commit', '-qm', 'settings')
            r = act_('setting_project', table='run', key='weekly_max', value=80)
            eq((r['ok'], ran), (True, []), 'a project save queues no task')
            eq(toml.read_text(encoding='utf-8'), before.replace('slotz = 1\n', 'slotz = 1\nweekly_max = 80\n'), 'and writes that key at once')
            r = act_('setting_project', table='run', key='slots', unset=True)
            eq((r['ok'], key('run', 'slots')[0]['has_project'], ran), (True, False, [['slots', '3']]), 'Reset for everyone takes it out, at once')
            check(not act_('setting_project', table='run', key='nokey', unset=True)['ok'], 'an unknown key is refused')
            ran.clear()
            now = local.read_text(encoding='utf-8')
            for t, k, v in (('run', 'slots', 'four'), ('run', 'slots', 0), ('run', 'slots', True), ('run', 'web', 'yes'),
                            ('run', 'web_port', 99999), ('ui', 'theme', 'pink'), ('run', 'links', 'x'), ('run', 'remote', 1),
                            ('ui', 'chat_quiet', 'soon'), ('ui', 'chat_quiet', True), ('models', 'code', 'nope:x:y'),
                            ('run', 'nokey', 1), ('nope', 'x', 1), ('run', 'weekly_max', -1)):
                for name in ('setting_device', 'setting_project'):
                    r = act_(name, table=t, key=k, value=v)
                    check(not r['ok'] and r['out'], f'{name} refuses [{t}] {k} = {v!r}', r)
            eq((local.read_text(encoding='utf-8'), ran), (now, []), 'a refused value changes nothing')
            eq(subprocess.run(['git', 'status', '--porcelain', '--', 'runner.toml'], cwd=repo, capture_output=True, text=True).stdout, '', 'runner.toml is clean')
            local.write_text('run = { slots = 2 }\n', encoding='utf-8')
            check('by hand' in act_('setting_device', table='run', key='slots', value=3)['out'], 'an inline table: by hand')
            eq(local.read_text(encoding='utf-8'), 'run = { slots = 2 }\n', 'and it is left alone')
    finally:
        srv.stop()
    for text, v in (('[run]\nslots = 1\n[run.join]\na = "b"\n', 9), ('', 3), ('# only comments\n', 3),
                    ('[agent-runner.run]\nslots = 1\n', 2), ('[run]\nprompt_extra = """\n[run]\nslots = 7\n"""\nslots = 1\n', 2)):
        raw = CF.tomllib.loads(CF.toml_edit(text, 'run', 'slots', v))
        eq((raw.get('agent-runner') or raw)['run']['slots'], v, f'set in {text!r}')
    eq(CF.setting_problem('ui', 'chat_quiet', False), '', 'chat_quiet = false is off')
    check(CF.setting_problem('ui', 'chat_quiet', 5), 'a bare number is refused')
    key_parts = next(x['parts'] for t in CF.settings_snapshot(repo)['tables'] if t['table'] == 'run' for x in t['keys'] if x['key'] == 'auto_release')
    page = W.page_html().decode()
    for part in ('settingsHTML', 'data-setsave="${other}"', 'data-setreset=', 'data-setmore=', 'data-setstep=', 'Find a setting',
                 "'Advanced'", "'Project file'", 'Ask a chat to change it', 'Restart the run', "outbox('settings_save'"):
        check(part in page, f'the Settings view has {part}')
    if not shutil.which('node'):
        return
    k = lambda **o: {'key': 'k', 'type': 'text', 'default': '', 'also': [], 'off': False, **o}  # noqa: E731
    got = logic_js([['settingValue', k(type='number', default=3), '4'], ['settingValue', k(type='number', default=3), 'x'],
                    ['settingValue', k(type='list', default=[]), 'a\n b \n'], ['settingValue', k(type='switch', default=True), 'false'],
                    ['settingValue', k(off=True, default='6h'), 'false'], ['settingValue', k(default='6h'), 'false'],
                    ['settingValue', k(type='choice', default='auto'), 'true'], ['settingValue', k(type='choice', default='auto'), 'auto'],
                    ['settingValue', k(type='table', default=False, also=['table']), '{ every = 10 }'],
                    ['settingValue', k(type='table', default=False), 'nope'],
                    ['settingValue', k(type='text', default='auto', also=['number']), '8'],
                    ['settingValue', k(default=False, also=['list']), 'bug, ui'], ['settingValue', k(default=False, also=['list']), 'true']])
    eq([g.get('v', 'err') for g in got], [4, 'err', ['a', 'b'], False, False, 'false', True, 'auto', {'every': 10}, 'err', 8,
                                          ['bug', 'ui'], True], "a field's words as a value of its type")
    names = ['claude', 'copilot', 'codex']
    eq(logic_js([['modelProviders', 'code', 'opus', names], ['modelProviders', 'code', 'opus', names, 'copilot'],
                 ['modelProviders', 'kinds', {'F': 'opus', 'D': 'codex:x', 'C': 'claude:opus'}, names, 'copilot'],
                 ['modelProviders', 'provider', 'codex', names], ['modelProviders', 'provider', 'claude', names],
                 ['modelProviders', 'tiers', {'copilot': {'opus': 'x'}}, names, 'copilot']]),
       [[], ['copilot'], ['copilot', 'codex'], ['codex'], [], []], 'F443: a bare model is [models] provider’s; the Provider row names its own')
    item = lambda c, **o: {'cid': c, 'name': 'setting_project', 'state': 'sending', 'set': {'id': 'run.slots'}, **o}  # noqa: E731
    box = [item('a'), item('b'), item('c', set={'id': 'run.web'}), item('d', name='setting_device'), item('e', state='failed')]
    eq([x['cid'] for x in logic_js([['obAdd', box, item('f'), 'a']])[0]], ['a', 'c', 'd', 'e', 'f'],
       'F173: a later save of a setting takes the place of the one not sent yet, never of the one going')
    for gone in ('Queue for everyone', 'lands through', 'queuedTask', 'k.queued'):
        check(gone not in page, f'F173: no {gone!r} left in the page')
    check('overSays' in page, 'a row says when this device overrides everyone')
    # F174: Release by itself is two controls, and both can be on
    from agent_runner import setting_words as SW
    rel = k(table='run', key='auto_release', type='table', default=False, also=['table'], parts=SW.parts('run', 'auto_release'))
    eq(key_parts, rel['parts'], 'the Settings route carries the two controls')
    both = '{"every":10,"idle":true}'
    cases = [('false', 'Off', False), ('{"every":10}', 'Every 10 tasks', {'every': 10}), ('{"idle":true}', 'When idle', {'idle': True}),
             (both, 'Every 10 tasks and when idle', {'every': 10, 'idle': True})]
    for text, says, value in cases:
        now, said, val = logic_js([['partsNow', text], ['settingSays', rel, text], ['settingValue', rel, text]])
        eq((now, said, val['v']), ({'every': (value or {}).get('every', 0), 'idle': bool((value or {}).get('idle'))}, says, value), f'the row: {says}')
    eq(logic_js([['partSet', 'false', 'every', 10], ['partSet', 'false', 'idle', True], ['partSet', '{"every":10}', 'idle', True],
                 ['partSet', '{"idle":true}', 'every', 10], ['partSet', both, 'every', 0], ['partSet', both, 'idle', False],
                 ['partSet', '{"every":10}', 'every', 0], ['partSet', '{"idle":true}', 'idle', False], ['partSet', '{"every":7}', 'idle', True],
                 ['partSet', both, 'every', 20]]),
       ['{"every":10}', '{"idle":true}', both, both, '{"idle":true}', '{"every":10}', 'false', 'false', '{"every":7,"idle":true}',
        '{"every":20,"idle":true}'], 'changing one keeps the other; both off is false')
    eq(logic_js([['partOptions', rel, '{"every":7}'], ['partOptions', rel, 'false'], ['partsNow', '{"every":true,"idle":"yes"}']]),
       [[[0, 'Off'], [5, '5 tasks'], [7, '7 tasks'], [10, '10 tasks'], [20, '20 tasks']],
        [[0, 'Off'], [5, '5 tasks'], [10, '10 tasks'], [20, '20 tasks']], {'every': 0, 'idle': False}], 'a count of their own is kept and shown')
    (tmp / 'parts.js').write_text(PARTS_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'parts.js'), str(W.PAGE), json.dumps(rel)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node draws the row and moves its controls', r.stderr[-900:])
    if r.returncode == 0:
        o = json.loads(r.stdout)
        for text, says, value in cases:
            html, v = o['rows'][text], value or {}
            eq(re.findall(r'<option value="(\d+)" selected', html), [str(v.get('every', 0))], f'{says}: the Every list')
            eq(bool(re.search(r'data-setpart="idle"[^>]* checked>', html)), bool(v.get('idle')), f'{says}: the When idle switch')
        eq(o['saved'], [['project', '{"every":10}'], ['project', both], ['project', '{"idle":true}'], ['project', 'false']],
           'F202b: each change of one is the whole value, in the draft')
        eq(o['sheet'], [['project', 'false']], "More…'s own two controls change it only on its button")
        check('setpart' not in o['readonly'], 'F448b: a row that cannot change now has no control')
    # F166: a row's control, and which rows show
    rem = k(type='choice', choices=['auto', True, False], words={'auto': 'Auto', 'true': 'On', 'false': 'Off'})
    pct = k(type='number', default=90, unit='%', words={'90': '90%'})
    par = k(table='run', key='approve', value=False)
    kid = k(table='run', key='approve_wait', parent='run.approve')
    got = logic_js([['settingText', {'every': 10}], ['settingText', False], ['pickValue', rel, '{"every":10}'], ['pickValue', rel, 'false'],
                    ['pickValue', rem, 'true'], ['pickValue', rem, 'auto'], ['pickValue', pct, '80'], ['pickOptions', pct, '94'],
                    ['pickOptions', k(words={}, choices=[]), 'x'], ['settingSays', rel, '{"every":10}'], ['settingSays', k(unit='GB'), '4'],
                    ['settingSide', k(home='device', has_device=False)], ['settingSide', k(home='everyone', has_device=False)],
                    ['settingSide', k(home='everyone', has_device=True)], ['settingChanged', k(source='device', value=3, default=3)],
                    ['settingChanged', k(source='project', value=4, default=3)], ['settingShows', kid, [par]],
                    ['settingShows', kid, [{**par, 'value': True}]], ['settingShows', kid, [{**par, 'has_project': True, 'value': True}]],
                    ['settingHit', k(table='run', key='slots', name='Tasks at once', desc='How many.'), 'slots'],
                    ['settingHit', k(table='run', key='slots', name='Tasks at once', desc='How many.'), 'tasks at'],
                    ['kindsModel', ['F', 'B'], {'F': 'opus', 'B': 'opus'}], ['kindsModel', ['F', 'B'], {'F': 'opus', 'B': 'haiku'}]])
    eq(got, ['{"every":10}', 'false', {'every': 10}, False, True, 'auto', 80, [['90', '90%'], ['94', '94%']], None, 'Every 10 tasks', '4 GB',
             'device', 'project', 'device', False, True, False, True, True, True, True, 'opus', ''], "a row's control, its home and when it shows")


AGENT_DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const set = JSON.parse(require('fs').readFileSync(process.argv[3], 'utf8'));
const logic = page.split('<script id="logic">')[1].split('</script>')[0].replace(/if\(typeof module[^\n]*/, '');
const slice = (a, b) => page.slice(page.indexOf(a), page.indexOf(b));
const S = {f: {}, ob: [], setOpen: {}, set, snap: {}, setTab: 'device'}, esc = t => String(t).replace(/&/g, '&amp;').replace(/"/g, '&quot;');  // F462: the program is this device's
const I = {chev: '', x: ''}, card = t => `<div>${t}</div>`, emptyCard = card, obCards = () => '', controlOf = () => null, foldIn = (k, t) => t, SHEETS = {};
const document = {querySelector: () => null, querySelectorAll: () => []}, render = () => {}, toast = t => { throw new Error(t) };
let saved = [];
const closeSheet = () => {}, draftSet = (id, side, d) => saved.push([side, id, d.unset ? null : d.text]), draftDrop = () => {};
eval(logic + slice('const settingId=', '/* the stepper:') + `
const k = set.tables.find(t => t.table === 'run').keys.find(x => x.key === 'agent'), row = () => settingRow(settingOf('run.agent'), {}), out = {row: row()};
const pick = (value, side, now) => pickAgent({value, dataset: {id: 'run.agent', setagent: side, ...(now ? {now: ''} : {})}});
pick(AGENT_OTHER, 'device', true); out.other = row(); out.asked = saved.length;
S.f['setother:device:run.agent'] = ' /opt/wrap '; saveSetting('run.agent', 'device'); out.wrap = saved; saved = [];
out.kept = row();
const was = [k.has_device, k.device]; k.has_device = true; k.device = '/opt/wrap'; row(); out.left = !('setother:device:run.agent' in S.f);
[k.has_device, k.device] = was;
pick(AGENT_OTHER, 'device', true); resetSetting('run.agent', 'device'); out.reset = !('setother:device:run.agent' in S.f); saved = [];
pick('claude', 'device', true); out.picked = saved; saved = []; S.f = {};
pick('claude', 'project', false); out.sheet = saved.length; saveSetting('run.agent', 'project'); out.sheetSaved = saved; S.f = {};
S.setTab = 'project'; setModels(); out.models = [...settingsHTML().matchAll(/data-k="set:([a-z.]+)/g)].map(m => m[1]);
console.log(JSON.stringify(out));`);
"""


def test_agent_picker_f405(tmp: Path) -> None:
    """F405: [run] agent is picked from the Claude Code programs found here, a kept value that is wrong stays in the
    list; the providers stand beside it with their logins, and no secret."""
    if os.name == 'nt':
        return  # the fakes are scripts on PATH
    from agent_runner import agents_here as A
    repo = fake_repo(tmp)
    local = repo / 'runner.local.toml'

    def program(d: str, name: str, body: str) -> Path:
        p = tmp / d / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f'#!/bin/sh\n{body}\n', encoding='utf-8')
        p.chmod(0o755)
        return p
    one = program('a', 'claude', 'echo "2.1.330 (Claude Code)"')
    two = program('b', 'claude', 'echo "2.0.1 (Claude Code)"')
    link = tmp / 'c' / 'claude'
    link.parent.mkdir()
    link.symlink_to(one)
    wrap = program('w', 'my-claude', f'echo ran >> {tmp}/ran')
    pi = tmp / 'pi'
    pi.mkdir()
    (pi / 'auth.json').write_text(json.dumps({'github-copilot': {'type': 'oauth', 'refresh': 'SECRET-R', 'access': 'SECRET-A'}}), encoding='utf-8')
    path = os.pathsep.join([str(one.parent), str(link.parent), str(two.parent), os.environ['PATH']])
    real = shutil.which
    only = lambda cmd, mode=os.F_OK | os.X_OK, path=None: (lambda p: p if not p or cmd != 'claude' or p.startswith(str(tmp)) else None)(real(cmd, mode, path))  # noqa: E731
    env = {'PATH': path, 'PI_CODING_AGENT_DIR': str(pi), 'GEMINI_API_KEY': 'SECRET-G'}
    env = mock.patch.dict(os.environ, env)
    which, places = mock.patch.object(shutil, 'which', only), mock.patch.object(A, 'PLACES', (str(one.parent),))

    def settings() -> tuple[dict, dict]:
        d = U.settings()
        return next(k for t in d['tables'] if t['table'] == 'run' for k in t['keys'] if k['key'] == 'agent'), d

    def draw(d: dict) -> dict:
        (tmp / 'set.json').write_text(json.dumps(d), encoding='utf-8')
        (tmp / 'agent.js').write_text(AGENT_DRIVER, encoding='utf-8')
        r = subprocess.run(['node', str(tmp / 'agent.js'), str(W.PAGE), str(tmp / 'set.json')], capture_output=True, text=True, timeout=60)
        check(r.returncode == 0, 'node draws the row and picks', r.stderr[-1500:])
        return json.loads(r.stdout) if r.returncode == 0 else {}
    node = bool(shutil.which('node'))
    with env, which, places:
        k, d = settings()
        eq([(p['value'], p['path'], p['version'], p['found']) for p in k['picks']],
           [('claude', str(one), '2.1.330', True), (str(two), str(two), '2.0.1', True)],
           'found: the one a bare claude starts, then each other once, with path and version')
        by = {p['name']: p for p in d['providers']}
        eq({n: p['state'] for n, p in by.items()},
           {'claude': 'unchecked', 'copilot': 'in', 'codex': 'out', 'gemini': 'in', 'ollama': 'none'}, 'each provider and its login')
        eq((by['codex']['cmd'], by['copilot']['cmd']), (f'{CF.RUNNER} login codex', ''), 'with no login, the command')
        check('GEMINI_API_KEY' in by['gemini']['says'] and 'OAuth' in by['copilot']['says'], 'where a login is kept', by)
        check('SECRET' not in json.dumps(d), 'never a secret')
        if node:
            o = draw(d)
            check(f'<option value="claude" selected>claude 2.1.330 · {one}</option>' in o['row'], 'the picker, on its row', o['row'])
            check('Other path…' in o['row'] and 'not found' not in o['row'] and 'setother' not in o['row'], 'found: not marked, no field')
            for part in (f'At {one}, version 2.1.330', 'Logged in: OAuth', f'Not logged in: <span class="setkey">{CF.RUNNER} login codex</span>',
                         'No login needed', 'Provider in Models picks one for every model', 'data-setmodels'):
                check(part in o['row'], f'the row says {part!r}', o['row'])
            check('data-f="setother:device:run.agent"' in o['other'] and ' data-now' in o['other'].split('setother:')[1].split('>')[0], 'Other path: a field, for the bar')
            eq((o['asked'], o['wrap']), (0, [['device', 'run.agent', '/opt/wrap']]), 'F202b: its words are the change')
            check('value=" /opt/wrap "' in o['kept'], 'what is typed stays until it is what is kept')
            eq(o['left'], True, 'then the field goes')
            eq(o['reset'], True, 'a reset takes the field too')
            eq(o['picked'], [['device', 'run.agent', 'claude']], 'F202b: a pick goes to the draft')
            eq((o['sheet'], o['sheetSaved']), (0, [['project', 'run.agent', 'claude']]), "in More… it waits for its button")
            check({'models.control', 'models.code', 'models.kinds', 'models.providers'} <= set(o['models'])
                  and all(m.startswith('models.') for m in o['models']), 'the link shows the [models] settings', o['models'])
        for kept, bad in (('nosuchagent', 'is not on this machine'), ('pi', 'was removed')):
            local.write_text(f'[run]\nagent = "{kept}"\n', encoding='utf-8')
            k, d = settings()
            p = k['picks'][-1]
            check(p['value'] == kept and not p['found'] and bad in p['bad'], f'not found: {kept} stays in the list, marked', p)
            eq(len(k['picks']), 3, 'beside those found')
            if node:
                o = draw(d)
                check(f'<option value="{kept}" selected>{kept} (not found)</option>' in o['row'] and 'v-bad' in o['row'], 'and on the page', o['row'])
        local.write_text('[run]\nagent = 5\n', encoding='utf-8')
        if node:
            check('<option value="5" selected>5 (not found)' in draw(settings()[1])['row'], 'a value that is no text is marked too')
        r = U.setting_device('run', 'agent', str(wrap))
        check(r['ok'], 'another path: a wrapper that is there is saved', r)
        k, d = settings()
        eq([(p['value'], p['found'], p['bad']) for p in k['picks'][2:]], [(str(wrap), True, '')], 'and is in the list, not marked')
        check(not (tmp / 'ran').exists(), 'a wrapper is not started to ask its version')
        r = U.setting_device('run', 'agent', str(tmp / 'nothing'))
        check(not r['ok'] and 'no such file' in r['out'], 'a path that is not there is refused', r)
        eq(settings()[0]['device'], str(wrap), 'and nothing is written')
        local.write_text('[models.providers.mine]\nkind = "openai"\nurl = "https://x.example"\nkey_env = "MINE_KEY"\n', encoding='utf-8')
        mine = lambda: next(p for p in settings()[1]['providers'] if p['name'] == 'mine')  # noqa: E731
        eq((mine()['state'], mine()['cmd']), ('out', f'{CF.RUNNER} login mine'), 'a provider of its own, with no login')
        with mock.patch.dict(os.environ, {'MINE_KEY': 'SECRET-M'}):
            eq((mine()['state'], mine()['says'], mine()['cmd']), ('in', 'env MINE_KEY', ''), 'and with one')
        local.write_text('[models.providers.mine]\nkey = "SECRET-K"\n', encoding='utf-8')
        eq(settings()[1]['providers'][-1]['name'], '[models.providers]', 'providers that are not valid: said')
        check('SECRET' not in json.dumps(settings()[1]['providers']), 'without what they hold')
        local.unlink()
        with mock.patch.object(shutil, 'which', lambda cmd, mode=1, path=None: None if cmd == 'claude' else real(cmd, mode, path)):
            k, d = settings()
            eq([(p['value'], p['found']) for p in k['picks']], [('claude', False)], 'none found: the default is marked')


LOGIN_DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const set = JSON.parse(require('fs').readFileSync(process.argv[3], 'utf8'));
const logic = page.split('<script id="logic">')[1].split('</script>')[0].replace(/if\(typeof module[^\n]*/, '');
const slice = (a, b) => page.slice(page.indexOf(a), page.indexOf(b, page.indexOf(a)));
const S = {f: {}, ob: [], setOpen: {}, set, snap: {}, draft: {}, sheet: ''}, esc = t => String(t).replace(/&/g, '&amp;').replace(/"/g, '&quot;');
const I = {ext: ''}, card = t => t, emptyCard = card, obCards = () => '', controlOf = () => null, foldIn = (k, t) => t, SHEETS = {};
const els = {}, $ = n => els[n] = els[n] || {hidden: false, h: '', value: '', kids: [], appendChild(x) { this.kids.push(x) }}, setHTML = (el, h) => { el.h = h };
const win = {}, ears = {}, clicks = [], location = {origin: 'o'}, HOME_PAGE = false, HB = '', T = 'TT', atAll = () => false, tq = u => u;
const document = {hidden: false, querySelector: () => null, querySelectorAll: () => [], addEventListener: (k, f) => { if (k === 'click') clicks.push(f) }, createElement: () => ({contentWindow: win, remove() {}})};
const addEventListener = (k, f) => { ears[k] = f }, setInterval = () => 0, render = () => {}, toast = () => {}, openSheet = n => { S.sheet = n }, loadProjects = () => {};
let logins = {}, term = {ok: true}, asked = [], typed = [];
const fetch = async u => { asked.push(u); return {ok: true, json: async () => u === 'logins' ? logins : term} };
const settle = async () => { for (let i = 0; i < 5; i++) await new Promise(r => setTimeout(r, 2)) };
const says = text => { win.term = {input: s => typed.push(s), buffer: {active: {length: 1, getLine: () => ({isWrapped: false, translateToString: () => text})}}} };
const press = sel => clicks.forEach(f => f({target: {closest: s => s === sel[0] ? {dataset: sel[1]} : null}}));
const provider = (name, ok, login) => ({name, ok, where: ok ? 'OAuth in auth.json' : 'no login', terminal: name === 'claude' ? 'login' : name === 'ollama' ? '' : 'login-' + name, login: {state: '', said: '', reopened: [], ...login}});
const all = (over = {}) => ({ok: true, providers: ['claude', 'copilot', 'codex', 'gemini', 'ollama'].map(n => over[n] || provider(n, ['claude', 'ollama'].includes(n)))});
eval(logic + slice('const settingId=', '/* the stepper:') + slice('/* F406c: a model', "/* F150: a project's") + `
const tell = d => ears.message({origin: 'o', source: win, data: {session: LG.name, ...d}});
const row = id => settingRow(settingOf(id), {}), draft = (id, text) => { const f = setField(id, 'project'); S.f[f] = text; S.draft[f] = {id, side: 'project', text} };
const out = {};
(async () => {
  draft('models.code', 'copilot:gpt-5');
  out.nokey = row('models.code');
  logins = all(); await loadLogins();
  out.none = row('models.code'); out.other = row('models.fix');
  draft('models.fallback', 'codex:gpt-5\\nopus'); out.fallback = row('models.fallback');
  out.kinds = kindsRow({id: 'x', name: 'x', desc: '', kinds: ['F']}, {...settingOf('models.kinds'), has_project: true, project: {F: 'gemini:pro'}});
  const undo = [{table: 'models', key: 'code', now: {has: true, value: 'copilot:gpt-5'}}, {table: 'models', key: 'fallback', now: {has: true, value: ['codex:x']}}];
  out.waits = loginWaits(undo, loginsNow(set, S.logins));
  out.list = providersHTML(set);
  // Copilot asks where it is; a GitHub Enterprise domain
  asked = []; press(['[data-plogin]', {plogin: 'copilot'}]); await settle(); out.where = [S.sheet, SHEETS.login(), [...asked]];
  term = {ok: false, out: 'must be a bare host name'}; loginAt('https://x/'); await settle(); out.refused = [$('loginsay').h, $('loginbtns').h];
  press(['[data-plogin]', {plogin: 'copilot'}]); term = {ok: true}; asked = [];
  loginAt('company.ghe.com'); await settle(); out.ghe = [[...asked], LG.frame.src];
  logins = all({copilot: provider('copilot', false, {state: 'running'})});
  says('Open https://company.ghe.com/login/device and enter the code ABCD-1234'); tell({state: 'up'}); await settle();
  out.code = [$('loginsay').h, $('loginbtns').h, $('logincode').hidden]; out.going = row('models.code');
  $('logininput').value = 'k-SECRET'; loginCode(); out.typed = [[...typed], asked.join(' ').includes('SECRET'), $('logininput').value];
  logins = all({copilot: provider('copilot', false, {state: 'failed', said: 'no such host'})});
  tell({state: 'down', code: 4001}); await settle(); out.failed = [$('loginsay').h, $('loginbtns').h, row('models.code')];
  asked = []; press(['[data-plogin]', {plogin: 'copilot'}]); press(['[data-loginhost]', {}]); await settle(); out.github = [...asked];
  says(''); logins = all(); tell({state: 'up'}); await settle();
  logins = all({copilot: provider('copilot', true, {state: 'done', said: 'copilot is logged in', reopened: ['F7']})});
  tell({state: 'down', code: 4001}); await settle(); out.done = [$('loginsay').h, $('loginbtns').h, row('models.code'), $('loginterm').hidden];
  out.waited = loginWaits(undo.slice(0, 1), loginsNow(set, S.logins)); out.again = providersHTML(set);
  press(['[data-plogin]', {plogin: 'gemini'}]); out.gemini = SHEETS.login(); loginOpen(); out.claude = [LG.name, SHEETS.login()];
  console.log(JSON.stringify(out));
})()`);
"""


BRANCH_DRIVER = AGENT_DRIVER.split('eval(')[0] + r"""
eval(logic + slice('const settingId=', '/* the stepper:') + `
const id = 'git.master_branch', row = () => settingRow(settingOf(id), {}), out = {row: row()};
S.f[setField(id, setTab())] = 'dev'; out.dev = row();
S.f[setField(id, setTab())] = 'gone'; out.gone = row();
console.log(JSON.stringify(out));`);
"""


def test_working_branch_f447a(tmp: Path) -> None:
    """F447a: the working branch is in Landing work under its own name, picked from the snapshot's branches, and the row
    says what Save does, that it waits for a restart, and why a pick cannot be saved."""
    from agent_runner import setting_words as SW
    eq((SW.group('git', 'master_branch'), SW.name('git', 'master_branch')), ('landing', 'Working branch'), 'its group and name')
    if not shutil.which('node'):
        return
    repo = fake_repo(tmp)
    snap = CF.settings_snapshot(repo)
    k = next(k for t in snap['tables'] if t['table'] == 'git' for k in t['keys'] if k['key'] == 'master_branch')
    k.update(picks=[{'value': '', 'branch': 'main', 'auto': True, 'bad': ''}, {'value': 'main', 'branch': 'main', 'auto': False, 'bad': ''},
                    {'value': 'dev', 'branch': 'dev', 'auto': False, 'bad': ''},
                    {'value': 'gone', 'branch': 'gone', 'auto': False, 'bad': 'not a branch to pick'}], now='main')
    (tmp / 'set.json').write_text(json.dumps(snap), encoding='utf-8')
    (tmp / 'branch.js').write_text(BRANCH_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'branch.js'), str(W.PAGE), str(tmp / 'set.json')], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node draws the row', r.stderr[-1500:])
    if r.returncode:
        return
    d = json.loads(r.stdout)
    check('<select class="fld setpick"' in d['row'] and 'Found by itself (main)' in d['row'] and 'data-setagent' not in d['row'], 'a pick of the branches', d['row'])
    check('Save:' not in d['row'] and 'v-bad' not in d['row'], 'nothing to say before a change', d['row'])
    check('v-bad' in d['gone'], 'and in the refusal colour')
    check('Save: finished work is applied to dev' in d['dev'], 'what Save does', d['dev'])
    check('once the run restarts' in d['dev'], 'and that it waits for a restart')
    check('It cannot be saved: not a branch to pick' in d['gone'], 'a bad pick says why', d['gone'])


def test_provider_login_f406c(tmp: Path) -> None:
    """F406c: beside a [models] setting that names a provider with no login: Log in, in the login sheet; the provider
    list has it too; how it ended is said."""
    if not shutil.which('node'):
        return
    pi = tmp / 'pi'
    repo = fake_repo(tmp)
    env = {k: v for k, v in os.environ.items() if k not in ('GEMINI_API_KEY', 'COPILOT_GITHUB_TOKEN')}
    with mock.patch.dict(os.environ, {**env, 'PI_CODING_AGENT_DIR': str(pi)}, clear=True):
        S.init(repo)
        (tmp / 'set.json').write_text(json.dumps(U.settings()), encoding='utf-8')
    (tmp / 'login.js').write_text(LOGIN_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'login.js'), str(W.PAGE), str(tmp / 'set.json')], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs the logins', r.stderr[-1500:])
    if r.returncode:
        return
    o = json.loads(r.stdout)
    check(f'{html.escape(CF.RUNNER)} login copilot' in o['nokey'] and 'data-plogin' not in o['nokey'], 'where /logins is refused: the command', o['nokey'])
    check('copilot is not logged in. Its tasks wait for the login.' in o['none'] and 'data-plogin="copilot"' in o['none']
          and '>Log in</button>' in o['none'], 'no login: said, with Log in', o['none'])
    check('data-plogin' not in o['other'], 'a setting on claude has none')
    check('codex is not logged in. It is passed over until the login.' in o['fallback'], 'a fallback', o['fallback'])
    check('data-plogin="gemini"' in o['kinds'], 'a kind', o['kinds'])
    eq(o['waits'], 'Tasks on copilot wait for the login. codex has no login yet', 'what a Save says')
    check('data-login>Log in again' in o['list'] and all(f'data-plogin="{p}"' in o['list'] for p in ('copilot', 'codex', 'gemini'))
          and 'data-plogin="ollama"' not in o['list'], "the provider list's", o['list'])
    eq((o['where'][0], o['where'][2]), ('login', []), 'Copilot asks first, with no terminal yet')
    check('data-loginhost>github.com' in o['where'][1] and 'data-f="logindomain"' in o['where'][1], 'github.com or a domain', o['where'])
    check('bare host name' in o['refused'][0] and 'data-plogin="copilot">Start again' in o['refused'][1], 'a refused domain: why, and again', o['refused'])
    eq(o['ghe'], [['terminal/login-copilot~company.ghe.com'], 't/TT/login-copilot~company.ghe.com/?fontSize=12'], 'the domain’s terminal')
    check('enter the code ABCD-1234' in o['code'][0] and 'href="https://company.ghe.com/login/device"' in o['code'][1] and not o['code'][2],
          'its code and its page', o['code'])
    check('Login under way' in o['going'] and '>Show the login</button>' in o['going'], 'the row says it goes on', o['going'])
    eq(o['typed'][1:], [False, ''], 'what is typed goes to the terminal only')
    eq(o['typed'][0], ['k-SECRET'], 'and gets there')
    check('The login failed: no such host' in o['failed'][0] and 'Start again' in o['failed'][1], 'failed: why, and again', o['failed'])
    check('v-bad">The login failed: no such host' in o['failed'][2] and '>Log in</button>' in o['failed'][2], 'on the row too', o['failed'])
    eq(o['github'][0], 'terminal/login-copilot', 'github.com has no domain')
    check('copilot is logged in. Starts again: F7' in o['done'][0] and 'Close' in o['done'][1] and o['done'][3], 'done: said', o['done'])
    check('copilot: Logged in' in o['done'][2] and 'data-plogin' not in o['done'][2], 'the row says logged in', o['done'])
    eq(o['waited'], '', 'and nothing waits')
    check('>Log in again</button>' in o['again'].split('data-k="prov:copilot"')[1].split('data-k=')[0], 'the list: Log in again', o['again'])
    check('type="password"' in o['gemini'] and 'Log in to gemini' in o['gemini'], 'a key is typed hidden')
    check(o['claude'][0] == 'login' and 'Send code' in o['claude'][1] and 'password' not in o['claude'][1], "claude's is as it was", o['claude'])


def test_plan_share_f460a(tmp: Path) -> None:
    """F460a: Settings > Plan's "Share the plan between machines": the `plan_share` action runs plan repo-setup and
    answers its lines; the page shows them, the last one apart as what the other machine runs."""
    from agent_runner import web_actions
    check(U.ACTIONS.get('plan_share') is web_actions.plan_share, 'the action is there')
    with mock.patch.object(U, 'plan_repo_setup', return_value={'ok': True, 'lines': ['Moved the plan to x', 'git clone y && run plan join']}) as m:
        r = U.act('plan_share', target=' git@h:p.git ')
    eq(m.call_args.args, (' git@h:p.git ',), 'the URL goes to plan repo-setup')
    eq((r['ok'], r['lines'], r['out']), (True, ['Moved the plan to x', 'git clone y && run plan join'], 'Moved the plan to x\ngit clone y && run plan join'), 'its lines')
    with mock.patch.object(U, 'plan_repo_setup', return_value={'ok': False, 'lines': ['no gh login']}):
        eq(U.act('plan_share')['ok'], False, 'a refusal is no ok')
    page = W.PAGE.read_text(encoding='utf-8')
    check('Share the plan between machines' in page and 'data-planshare' in page and "name:'plan_share'" in page, 'the button and its action')
    if not shutil.which('node'):
        return
    js = page.split('<script id="logic">', 1)[1].split('</script>', 1)[0]
    (tmp / 'logic.js').write_text(js + '\nmodule.exports.planShareView=planShareView;\n', encoding='utf-8')
    (tmp / 'driver.js').write_text(LOGIC_DRIVER, encoding='utf-8')
    cases = [['planShareView', {'ok': True, 'lines': ['a', 'b', 'run this']}], ['planShareView', {'ok': False, 'out': 'no'}],
             ['planShareView', None]]
    p = subprocess.run(['node', str(tmp / 'driver.js'), str(tmp / 'logic.js')], input=json.dumps(cases), capture_output=True, text=True, timeout=60)
    check(p.returncode == 0, 'node runs', p.stderr[-800:])
    got = json.loads(p.stdout or '[]') or [{}] * 3
    eq(got[0], {'lines': ['a', 'b'], 'cmd': 'run this', 'err': False}, 'the last line is the command')
    eq(got[1], {'lines': ['no'], 'cmd': '', 'err': True}, 'a refusal says why')
    eq(got[2].get('err'), True, 'no answer')


FILE_DRIVER = AGENT_DRIVER.split('eval(')[0] + r"""
eval(logic + slice('const settingId=', '/* the stepper:') + `
S.setTab = 'project'; S.setOpen = {'#advanced': true, '#file': true};
const all = settingsAll(set), out = {page: settingsHTML(), rows: {}};
for (const k of all) { S.setOpen[settingId(k)] = true; out.rows[settingId(k)] = settingRow(k, {}); }
const t = all.find(k => settingId(k) === 'run.test'); t.locked = 'a task is running'; out.locked = settingRow(t, {});
console.log(JSON.stringify(out));`);
"""


def test_project_file_f448b(tmp: Path) -> None:
    """F448b: every group opens and every key shows a control or the reason it cannot change, with More… and Ask a chat;
    the Project file group is no longer read only; a saved [run] test lands in runner.toml."""
    repo = fake_repo(tmp)
    toml = repo / 'runner.toml'
    toml.write_text('[run]\nslots = 2\n', encoding='utf-8')
    git(repo, 'add', 'runner.toml')
    git(repo, 'commit', '-qm', 'settings')
    token = W.web_token()
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {})
    base = f'http://127.0.0.1:{srv.server_address[1]}'
    U.settings_start()
    try:
        r = post(f'{base}/act?t={token}', {'name': 'setting_project', 'args': {'table': 'run', 'key': 'test', 'value': 'python3 -V'}})[1]
        check(r['ok'] is True, 'a [run] test save', r)
        eq(CF.tomllib.loads(toml.read_text(encoding='utf-8'))['run'].get('test'), 'python3 -V', 'lands in runner.toml')
    finally:
        srv.shutdown()
    if not shutil.which('node'):
        return
    (tmp / 'set.json').write_text(json.dumps(CF.settings_snapshot(repo)), encoding='utf-8')
    (tmp / 'file.js').write_text(FILE_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'file.js'), str(W.PAGE), str(tmp / 'set.json')], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node draws the page', r.stderr[-1500:])
    if r.returncode:
        return
    d = json.loads(r.stdout)
    check('read only' not in d['page'] and 'Commands' in d['page'], 'Project file opens, not read only')
    bare = [id_ for id_, h in d['rows'].items() if not re.search(r'data-f="set|data-setstep|data-setagent|data-setpart|setlock', h)]
    eq(bare, [], 'every key has a control or a stated reason')
    asks = [id_ for id_, h in d['rows'].items() if 'data-about="setting:' not in h or 'data-setmore=' not in h]
    eq(asks, [], 'every open row has More… and Ask a chat to change it')
    check('Cannot change here now: a task is running' in d['locked'] and 'data-f="set' not in d['locked'], 'a locked key says why, no control', d['locked'])


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_no_settings_f178), in_tmp(test_trusted_networks_f136), in_tmp(test_https_link_b130), in_tmp(test_tailnet_https_f96), in_tmp(test_manage_releases_f193), in_tmp(test_search_clear_f204a), in_tmp(test_settings_f97), in_tmp(test_agent_picker_f405), in_tmp(test_provider_login_f406c), in_tmp(test_plan_share_f460a), in_tmp(test_working_branch_f447a), in_tmp(test_project_file_f448b)]))
