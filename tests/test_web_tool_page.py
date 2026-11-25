#!/usr/bin/env python3
"""F428b: a runner.toml tool's web page on the run page: Start, Use and Stop on its card, and Use on a Needs you item.

    python3 tests/test_web_tool_page.py        (a temp repo, node, a real process; a few seconds)
"""
from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from _check import check, eq, git, report

os.environ['AGENT_RUNNER_KEYRING'] = 'off'
from agent_runner import config as CF, device_page as DP, devices as D, runner as R, shared_tools as T, ui_model as U, web as W  # noqa: E402

BASE = '[run]\ntest = "true"\nmin_free_gb = 0\nremote = false\n'
TODO = '# TODO\n\n### Next\n\n- [ ] **T1** x | files: a.py\n'

DRIVER = r"""
const src = require('fs').readFileSync(process.argv[2], 'utf8'), cut = (a, b) => src.slice(src.indexOf(a), src.indexOf(b, src.indexOf(a)));
const S = {toolBusy: '', toolSaid: {}, tools: {secure: true, tools: []}, sure: null, view: 'tools'}, calls = [], at = {hostname: 'box.ts.net'};
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => '&#' + c.charCodeAt(0) + ';'), I = {ext: ''};
const viewGo = f => f(), goView = v => calls.push('view ' + v), closeSheet = () => calls.push('close');
let answer; const toolPost = async (b, k) => { calls.push([b, k]); S.toolSaid = {[k]: {ok: answer.ok, out: answer.out}}; return answer };
const spots = ['tool:device:phone', 'tool:runner.toml:phone'].map((k, i) => ({dataset: {k}, getBoundingClientRect: () => ({top: 100 * (i + 1)})}));
const body = {scrollTop: 0, querySelectorAll: () => spots, getBoundingClientRect: () => ({top: 0})};
const f = new Function('S', 'esc', 'I', 'card', 'render', 'tq', 'viewGo', 'goView', 'closeSheet', 'toolPost', 'location', '$',
  cut('const toolSaid=', 'function toolHostKey') + cut('function toolHostKey', 'function toolsHTML') + cut('async function toolClick', '\n}\n')
  + '\n}; return {toolCard, toolSpot, needDevices, toolClick}')(S, esc, I, (h, c, a) => `<${a}>` + h, () => {}, x => x, viewGo, goView, closeSheet, toolPost, at, () => body);
const btns = h => [...h.matchAll(/<(button|a) class="btn([^"]*)"([^>]*)>([^<]*)</g)].map(m => [m[4].trim(), m[2].trim(),
  / disabled/.test(m[3]) ? 'off' : '', m[1] === 'a' ? (m[3].match(/href="([^"]*)" target="_blank" rel="noopener noreferrer"/) || [])[1] : (m[3].match(/data-source="([^"]*)"/) || [])[1]]);
const tool = (run, page = ':8123') => ({name: 'phone', label: 'The phone', source: 'runner.toml', description: 'd', used: true, state: 'free', words: 'free', at: 0, page, run});
const dev = run => ({...tool(run, 'http://rig'), label: 'phone', source: 'device', kind: 'other', reach: 'x', secrets: {}});
const st = (state, lines = []) => ({state, lines});
const page = t => { const h = f.toolCard(t); return [btns(h), (h.match(/data-k="pagestate:([^"]*)" data-v="([^"]*)">Web page ([^ <]*)/) || []).slice(1), (h.match(/<pre[^>]*>([^<]*)/) || [])[1] || ''] };
(async () => {
  const out = {}, all = () => [st('stopped'), st('running'), st('failed', ['one', '<two>']), null].map(r => page(tool(r)));
  out.rw = all(); S.tools.secure = false; out.ro = all(); S.tools.secure = true;
  const bare = tool(null); delete bare.page; delete bare.run; out.bare = f.toolCard(bare);
  out.links = ['https://x/y', 'javascript:1', ':80@evil.example', ':8x'].map(p => (page(tool(null, p))[0][0] || [])[3] || '');
  at.hostname = '[::1]'; out.six = page(tool(null))[0][0][3]; at.hostname = ''; out.file = page(tool(null))[0]; at.hostname = 'box.ts.net';
  const need = (state, d = {}) => btns(f.needDevices({devices: [{name: 'phone', label: 'The phone', source: 'runner.toml', page: ':8123', state, ...d}]}))[0];
  out.need = ['running', '', 'stopped', 'failed'].map(s => need(s));
  const press = async (t, a, source = 'runner.toml') => { answer = a; await f.toolClick({dataset: {tool: t, name: 'phone', source}}); return JSON.stringify(S.toolSaid) };
  out.said = [await press('start', {ok: true, state: 'running', out: 'x'}), await press('stop', {ok: false, out: 'did not stop'})];
  out.where = [f.toolCard(tool(st('running'))).includes('did not stop'), f.toolCard(dev(st('running'))).includes('did not stop')];
  await press('start', {ok: true, state: 'running', out: 'x'}, 'device'); out.calls = calls.splice(0);
  S.toolBusy = 'start:runner.toml:phone:'; out.busy = [tool(st('stopped')), dev(st('stopped'))].map(t => f.toolCard(t).includes('btn pri busy')); S.toolBusy = '';
  out.spot = [];
  for (const source of ['runner.toml', null]) { body.scrollTop = 0; await press('show', {}, source); f.toolSpot(); out.spot.push([body.scrollTop, S.toolGo]) }
  out.went = calls;
  console.log(JSON.stringify(out));
})();
"""


def test_page(tmp: Path) -> None:
    print("a runner.toml tool's card: its page's state and buttons, as a device's")
    if not shutil.which('node'):
        print('  (no node here: skipped)')
        return
    (tmp / 'page.js').write_text(DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'page.js'), str(W.PAGE)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node draws the cards', r.stderr[-1500:])
    if r.returncode:
        return
    o, src, url = json.loads(r.stdout), 'runner.toml', 'http://box.ts.net:8123'
    for key, off in (('rw', ''), ('ro', 'off')):
        start, use, stop = ['Start', 'pri', off, src], ['Use', 'pri', '', url], ['Stop', '', off, src]
        at = lambda s: [f'{src}:phone', s, url]  # noqa: E731
        eq(o[key], [[[start], at('stopped'), ''], [[use, stop], at('running'), ''],
                    [[start], at('failed'), 'one\n&#60;two&#62;'], [[use], at(''), '']], f'each state ({key})')
    check('<div class="btns">' not in o['bare'] and 'Web page' not in o['bare'], 'without page the card has none of it', o['bare'])
    eq(o['links'], ['https://x/y', '', '', ''], 'only http, https and :PORT are links')
    eq((o['six'], o['file']), ('http://[::1]:8123', []), "the page's own host; a page with none has no link")
    go = ['Open The phone in Tools', '', '', src]
    eq(o['need'], [['Use The phone', '', '', url]] * 2 + [go] * 2, 'Needs you: Use, or the way to its card')
    eq(o['said'][0], '{}', 'the state says it')
    eq(o['where'], [True, False], "a refusal is on the tool's card, not on a device's of the same name")
    eq(o['calls'], [[{'op': 'start', 'name': 'phone', 'source': src}, f'{src}:phone'], [{'op': 'stop', 'name': 'phone', 'source': src}, f'{src}:phone'],
                    [{'op': 'start', 'name': 'phone', 'source': 'device'}, 'phone']], 'what a press sends')
    eq(o['busy'], [True, False], 'only its own button is busy')
    eq(o['spot'], [[188, ''], [88, '']], 'Open goes to the card of the tool, or of the device')
    eq(o['went'], ['view tools'] * 2, 'on the Tools page')


def test_needs(repo: Path) -> None:
    print('the snapshot: a Needs you row has the pages of the runner.toml tools its task needs')

    def toml(*lines: str) -> None:
        (repo / 'runner.toml').write_text(BASE + '[run.tools.phone]\ncheck = "true"\nlabel = "The phone"\n' + ''.join(l + '\n' for l in lines)
                                          + '[run.tools.bare]\ncheck = "true"\n', encoding='utf-8')
        T.S.C.run['tools'] = CF.Config(repo).run['tools']

    def op(op_: str, **a) -> dict:
        return D.post(json.dumps({'op': op_, 'name': 'phone', 'source': 'runner.toml', **a}).encode(), T.S.C)[1]

    def devs(tid: str = 'T4'):
        return next(n for n in U.snapshot(up=False, links={}, terminal_base='.')['needs'] if n['id'] == tid).get('devices')
    (repo / 'plan/TODO.md').write_text(TODO + '- [~] **T4** x | files: d.py | needs: rig, bare, phone\n  more words BLOCKED: CONFIRM: ok?\n'
                                       '- [~] **T5** y | files: e.py BLOCKED: CONFIRM: ok?\n'
                                       '- [~] **T6** z | files: f.py | needs: bare BLOCKED: CONFIRM: ok?\n', encoding='utf-8')
    toml('page = ":8123"', 'start = "sleep 600"')
    phone = {'name': 'phone', 'label': 'The phone', 'source': 'runner.toml', 'page': ':8123', 'state': 'stopped'}
    eq((devs(), devs('T5'), devs('T6')), ([phone], None, None), 'the one with a page')
    D.post(json.dumps({'op': 'save', 'name': 'rig', 'kind': 'other', 'reach': 'git x', 'page': 'http://rig'}).encode(), T.S.C)
    D.post(json.dumps({'op': 'use', 'name': 'rig', 'on': True}).encode(), T.S.C)
    eq(devs(), [{'name': 'rig', 'page': 'http://rig', 'state': ''}, phone], "beside a device's")
    check(op('start')['ok'], 'started')
    eq(devs()[1]['state'], 'running', 'its state follows')
    op('stop')
    toml('page = "http://x"')
    eq(devs()[1], {**phone, 'page': 'http://x', 'state': ''}, 'a page with no start command has no state')
    toml()
    eq([d['name'] for d in devs()], ['rig'], 'none without page')


def main() -> int:
    if os.name == 'nt':
        print('skipped: process groups are POSIX')
        return 0
    with tempfile.TemporaryDirectory() as tmp_:
        tmp = Path(tmp_).resolve()
        os.environ['AGENT_RUNNER_DEVICES'] = str(tmp / 'state')
        os.environ['AGENT_RUNNER_HOME_CONFIG'] = str(tmp / 'homecfg')
        repo = tmp / 'proj'
        (repo / 'plan').mkdir(parents=True)
        git(repo, 'init', '-q', '-b', 'main')
        (repo / 'plan/TODO.md').write_text(TODO, encoding='utf-8')
        (repo / 'plan/DONE.md').write_text('# DONE\n', encoding='utf-8')
        (repo / 'runner.toml').write_text(BASE, encoding='utf-8')
        git(repo, 'add', '-A')
        git(repo, 'commit', '-qm', 'start')
        R.init(repo)
        try:
            return report([lambda: test_page(tmp), lambda: test_needs(repo)])
        finally:
            for d in (tmp / 'state/pages').glob('*'):  # a failed check leaves no process behind
                with contextlib.suppress(Exception):
                    DP.stop(d)


if __name__ == '__main__':
    sys.exit(main())
