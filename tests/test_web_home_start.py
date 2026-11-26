"""The run page, Home's Start card: no run is up, so Home starts one in one tap (F402c).

    python3 tests/test_web_home_start.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from _check import check, eq, report

from agent_runner import ui_model as U
from agent_runner import web as W
from _web import fake_repo, in_tmp

DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const line = a => page.slice(page.indexOf(a), page.indexOf('\n', page.indexOf(a)) + 1);
const grab = a => page.slice(page.indexOf(a), page.indexOf('\n}\n', page.indexOf(a)) + 3);
const logic = page.split('<script id="logic">')[1].split('</script>')[0].split('if(typeof module').join('if(false&&typeof module');
const S = {ob: [], atts: {}, f: {}, view: 'home', thread: null, snap: null};
const no = () => '', env = {S, I: {}, DK: {}, LOGO: no, greeting: no, keysLine: no, ttydLine: no, needsSec: no, dictWhy: no, micWhy: no, shownSession: no, busy: no,
  sessWorks: no, modelOf: no, enterHint: no, boxKey: () => 'home', homeChips: no, homeSums: no, homeBox: no};
const names = ['const esc=', 'const card=', 'const controlOf=', 'const ctlBusy=', 'const obBtns='];
const src = logic + names.map(line).join('') + ['box', 'homeHTML', 'homeStart'].map(f => grab(`function ${f}(`)).join('');
const home = new Function('env', 'with(env){' + src.replace(/^const /gm, 'var ') + '; return homeHTML}')(env);
console.log(JSON.stringify(JSON.parse(require('fs').readFileSync(0, 'utf8')).map(([snap, ob]) => { S.snap = snap; S.ob = (ob || []).filter(x => x.ctl); S.startOk = (ob || []).some(x => x.ok) ? Date.now() : 0; return home() })));
"""


def test_home_start_f402c(tmp: Path) -> None:
    """F402c: with no run up Home's first card says Not running, with the one accent button; what a start does stands there."""
    if not shutil.which('node'):
        print('  (no node here: the Start card test is skipped)')
        return
    fake_repo(tmp)
    def snap(up, boot='b1'):
        return {'up': up, 'boot': boot, 'sessions': [], 'needs': [], 'queue': [], 'controls': U.controls(), **U.controls_shown(up, {}, {})}
    start = {'cid': 'x1', 'ctl': 'start:', 'name': 'run_control', 'args': {'key': 'start'}}
    cases = [[snap(False)], [snap(False), [{**start, 'state': 'sending'}]],
             [snap(False), [{**start, 'state': 'failed', 'err': 'port <8000> is taken'}]], [snap(True)], [snap(False, '')],
             [snap(True), [{**start, 'state': 'failed', 'err': 'late'}]], [snap(False), [{'ok': True}]]]
    (tmp / 'd.js').write_text(DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'd.js'), str(W.PAGE)], input=json.dumps(cases), capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node draws Home', r.stderr[-1500:])
    if r.returncode:
        return
    off, busy, bad, up, old, late, acked = json.loads(r.stdout)
    check(0 <= off.find('data-k="start"') < off.find('class="greet"'), 'the Start card is at the top', off)
    check('<b>Not running</b>' in off, 'Not running')
    eq((off.count('data-ctl="start"'), off.count('btn acc')), (1, 1), 'one Start button, the one accent')
    check('data-form' in off, 'the message box is there')
    for k in ('pause', 'stop', 'slot_add'):
        check(f'data-ctl="{k}"' not in off, f'no {k}')
    check('Starting the run…' in busy and 'btn acc busy' in busy and 'livedot' in busy, 'starting, in place', busy)
    check('Starting the run…' in acked and 'btn acc busy' in acked, 'the start went through, the snapshot is not there yet: still starting', acked)
    check('Not started: port &lt;8000&gt; is taken' in bad and 'data-obretry="x1"' in bad and 'data-obdrop="x1"' in bad, 'a failure, in place, with Retry', bad)
    check('data-ctl="start"' not in bad, 'Retry stands in for Start')
    for h, what in ((up, 'a run is up'), (old, 'a kept snapshot'), (late, 'a run that came up after a failed start')):
        check('data-k="start"' not in h and 'btn acc talkbig' in h, f'{what}: no Start card, Talk is the accent', h)


def test_off_page_f402c(tmp: Path) -> None:
    """F402c: the off page is drawn only on Runner Home's own page, which a project's page-only process takes over."""
    page = W.PAGE.read_text(encoding='utf-8')
    eq([ln.strip() for ln in page.splitlines() if 'offHTML()' in ln and 'function' not in ln],
       ['if(HOME_PAGE&&!atAll())return offHTML();'], 'the one use of the off page')


def opened(where: str, home: int = 0):
    """F454a: (the server, what the run log said, the Tailscale Serve ports asked for) of a start with web_open = `where`."""
    import os
    from unittest import mock
    from agent_runner import page_https
    from agent_runner import state as S
    log: list[str] = []
    served: list[int] = []
    with mock.patch.dict(os.environ, {'AGENT_RUNNER_NO_WEB': ''}), mock.patch.object(W, 'lan_ip', lambda: '10.0.0.5'), \
            mock.patch.dict(S.C.run, {'web': True, 'web_port': 0, 'web_https': True, 'web_open': where}), \
            mock.patch.object(W, 'home_port', lambda: home), mock.patch.object(W, 'home_installed', lambda: bool(home)), \
            mock.patch.object(W, 'site_urls', lambda *a, **k: []), mock.patch.object(W, 'tailscale_https_urls', lambda p, t: []), \
            mock.patch.object(page_https, 'https_on', lambda port: served.append(port) or None), \
            mock.patch.object(page_https, 'left_over', lambda: None), mock.patch.object(S, 'log', log.append):
        return W.start_web(), log, served


def test_web_open_f454a(tmp: Path) -> None:
    """F454a: [run] web_open: everywhere serves every interface; here only 127.0.0.1, its localhost link, no Serve rule."""
    from agent_runner import config as CF
    fake_repo(tmp)
    eq(S_C().run['web_open'], 'everywhere', 'the default: everywhere')
    srv, log, served = opened('everywhere')
    try:
        port = srv.server_address[1]
        eq(srv.server_address[0], '0.0.0.0', 'everywhere: every interface')
        check(f'10.0.0.5:{port}' in W.url_file().read_text(encoding='utf-8'), 'and its LAN link', log)
        eq(served, [port], 'and a Tailscale Serve rule')
    finally:
        srv.stop()
    srv, log, served = opened('here')
    try:
        port = srv.server_address[1]
        here = f'http://localhost:{port}/?t={W.web_token()}'
        eq(srv.server_address[0], '127.0.0.1', 'here: 127.0.0.1 only')
        eq(W.url_file().read_text(encoding='utf-8').split(), [here], 'its localhost link, with its key')
        check(any(here in x for x in log) and not any('nothing opens' in x.lower() for x in log), 'the run log names it', log)
        eq(served, [], 'and no Tailscale Serve rule')
        W.HomeWatch(srv).look()
        eq(srv.server_address[1], port, 'it stays where it is with no Home')
    finally:
        srv.stop()
    srv, log, served = opened('here', home=1)
    try:
        eq((srv.server_address[0], W.url_file().read_text(encoding='utf-8').count('localhost')), ('127.0.0.1', 0),
           "with Runner Home: Home's page, as before")
    finally:
        srv.stop()
    check('web_open' in CF.setting_problem('run', 'web_open', 'lan'), 'a bad value is refused')
    eq(CF.setting_problem('run', 'web_open', 'here'), '', 'here is a value')
    (tmp / 'proj' / 'runner.local.toml').write_text("[run]\nweb_open = 'lan'\n", encoding='utf-8')
    try:
        CF.Config(tmp / 'proj')
        check(False, 'a bad value in runner.local.toml stops the load')
    except SystemExit as e:
        check('web_open' in str(e), 'a bad value in runner.local.toml stops the load', str(e))


def S_C():
    from agent_runner import state as S
    return S.C


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_home_start_f402c), in_tmp(test_off_page_f402c), in_tmp(test_web_open_f454a)]))
