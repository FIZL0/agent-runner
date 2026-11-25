#!/usr/bin/env python3
"""F194b: the walkthrough on the web (agent_runner/page/*-walk.*): Runner Home's offer of the example project, the
steps, and that skip stays. Nothing here starts a run.

    python3 tests/test_web_walk.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from unittest import mock

from _check import check, eq, report
from agent_runner import demo as D  # noqa: E402
from agent_runner import home as H  # noqa: E402
from agent_runner import state as S  # noqa: E402
from agent_runner import web as W  # noqa: E402
from _web import fake_repo, in_tmp, logic_js, post  # noqa: E402

STEPS = ['queue', 'start', 'session', 'needs', 'land', 'chat', 'own']


def test_make(tmp: Path) -> None:
    print('Home makes the example project with the command\'s own function, lists it and names its key')
    other = tmp / 'other'
    other.mkdir()
    (other / 'runner.toml').write_text('', encoding='utf-8')
    env = {'AGENT_RUNNER_HOME_CONFIG': str(tmp / 'cfg'), 'AGENT_RUNNER_HOME': str(tmp / 'runs' / '{repo}')}
    with mock.patch.dict(os.environ, env), mock.patch.object(D, 'DEFAULT', str(tmp / 'ex')), \
            mock.patch.object(H, 'SCAN', [str(tmp / 'none')]):
        acts = []
        srv = H.serve_home('HT', 0, '127.0.0.1', act=lambda *a: acts.append(a) or {'ok': True, 'out': ''}, vitals=mock.Mock())
        url = f'http://127.0.0.1:{srv.server_address[1]}/example?t='
        try:
            eq(post(url + 'no', {})[0], 403, 'not without the key')
            check(not (tmp / 'ex').exists(), 'so nothing is made')
            (tmp / 'ex').mkdir()
            code, d = post(url + 'HT', {})
            check(code == 200 and not d['ok'] and 'is there already' in d['out'], 'a folder of the person\'s: refused, said why', d)
            eq(H.projects(), [], 'and not listed')
            (tmp / 'ex').rmdir()
            code, d = post(url + 'HT', {})
            eq((code, d['ok'], d['made'], d['key']), (200, True, True, 'ex'), 'made, and where to open it')
            check(D.is_demo(tmp / 'ex') and not D.busy(tmp / 'ex') and not acts, 'the example project, with nothing started')
            eq(H.projects(), [(tmp / 'ex').resolve()], 'Home lists it')
            H.remove_project(str(tmp / 'ex'))
            code, d = post(url + 'HT', {})
            eq((d['ok'], d['made'], d['key']), (True, False, 'ex'), 'there already: opened, listed again, not made over')
            call = {'info': lambda r: {}, 'facts': lambda r, i: {}, 'needs': lambda r: (0, []), 'plan': lambda r: {}}
            eq([H.project_row('k', r, **call)['example'] for r in (tmp / 'ex', other)], [True, False],
               'Home\'s row says which project is the example')
        finally:
            srv.stop()
        with mock.patch.object(S, 'ROOT', (tmp / 'ex').resolve()):
            eq(W.with_extras({})['example'], True, 'and so does the run page\'s snapshot')
    fake_repo(tmp)
    eq(W.with_extras({})['example'], False, 'in another project: no')


def test_steps(tmp: Path) -> None:
    print('the steps: one card each, in order; Back and Skip always; what is kept')
    if not shutil.which('node'):
        print('  (no node here: skipped)')
        return
    up = {'off': False, 'up': True, 'working': 1, 'needs': 1, 'landed': 1, 'home': True}
    down = {'off': True, 'up': False, 'working': 0, 'needs': 1, 'landed': 0, 'home': True}
    got = logic_js([['walkStep', i, up] for i in STEPS] + [['walkStep', i, down] for i in STEPS])
    eq([s['id'] for s in got], STEPS * 2, 'every step, with the run up and not')
    check(all(s['at'] and s['title'] and s['text'] for s in got), 'each has words and something to point at')
    eq([s['view'] for s in got[:7]], ['plan', 'status', 'status', 'home', 'status', 'home', ''], 'where each thing is')
    check('side by side' in got[0]['text'] and got[0]['many'] == 3, 'the queue: tasks side by side', got[0])
    off = got[8]
    check('your own Claude usage' in off['text'] and 'Nothing starts until you press it' in off['text'] and
          off['at'][0] == '[data-pact="start"]', 'Start run: whose usage, and that only a press starts it', off)
    cards = logic_js([['walkHTML', s, x, True] for s, x in zip(got, [up] * 7 + [down] * 7)])
    for s, h in zip(got, cards):
        check('data-walk="back"' in h and ('data-walk="skip"' in h or 'data-walk="done"' in h), f'{s["id"]}: Back and Skip')
        check('data-ctl' not in h and 'data-pact' not in h, f'{s["id"]}: the card itself starts nothing')
        eq(h.count('btn pri'), 1, f'{s["id"]}: one main button')
    check('data-addproject' in cards[6], 'the last one adds their own project')
    alone, away = logic_js([['walkHTML', got[6], {**up, 'home': False}, True], ['walkHTML', got[0], up, False]])
    check('data-addproject' not in alone and 'agent-runner setup' in logic_js([['walkStep', 'own', {**up, 'home': False}]])[0]['text'],
          'without Runner Home it says the command')
    check('Show me' in away and 'Show me' not in cards[0], 'on another view it offers to show the thing')
    st = {'at': 'needs', 'off': False}
    mv = logic_js([['walkParse', ''], ['walkParse', 'x{'], ['walkParse', '{"at":"gone"}'], ['walkParse', '{"at":"land","off":true}'],
                   ['walkMove', st, 'next'], ['walkMove', st, 'back'], ['walkMove', st, 'skip'],
                   ['walkMove', {**st, 'off': True}, 'again'], ['walkMove', {'at': 'own', 'off': False}, 'done'],
                   ['walkMove', {'at': 'queue', 'off': False}, 'back']])
    first = {'at': 'queue', 'off': False}
    eq(mv[:4], [first, first, first, {'at': 'land', 'off': True}], 'nothing kept, or nothing of use: the first step; else where they were')
    eq(mv[4:], [{'at': 'land', 'off': False}, {'at': 'session', 'off': False}, {'at': 'needs', 'off': True}, st,
                {'at': 'queue', 'off': True}, first], 'Next, Back, Skip, shown again where it was, Done, and Back on the first')
    offer, failed = logic_js([['exampleOffer', {}], ['exampleOffer', {'err': 'no git'}]])
    check('Try the example project' in offer and 'data-example' in offer and 'data-addproject' in offer,
          'Home with no projects: the example beside adding your own', offer)
    check('no git' in failed and 'Retry' in failed, 'one that failed says why, with Retry')


DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const logic = page.split('<script id="logic">')[1].split('</script>')[0].split('if(typeof module').join('if(false&&typeof module');
const i = page.indexOf("/* --- F194b: the example project's walkthrough (walkStep"), src = page.slice(i, page.indexOf("\nconst card=", i));
const kept = {}, store = {get: k => kept[k] || '', set: (k, v) => { if (v) kept[k] = v; else delete kept[k] }};
const open = (o) => {
  const el = {hidden: true, h: '', querySelector: () => null}, on = {}, said = [], went = [];
  const S = {snap: {project: o.project, example: o.example, up: true, needs: [], lately: []}, view: o.view || 'home', thread: o.thread || null};
  const env = {S, store, HOME_PAGE: !!o.home, HKEY: o.home || '', HB: o.home ? '/' : '', T: 't', I: {ask: ''}, $: () => el, keysIn: () => new Map(), enter() {}, esc: s => s,
    setHTML: (e, h) => { const c = e.h !== h; e.h = h; return c }, projectOf: k => (o.rows || []).find(p => p.key === k), working_: () => [], atAll: () => !!o.all,
    render: () => env.draw(), goView: v => { S.view = v; went.push(v); env.draw() }, toast: t => said.push(t), requestAnimationFrame() {}, scrollGlide() {}, flying: () => 0,
    homePost: async () => o.answer, location: {}, projectLink: (b, k) => b + 'p/' + k, addEventListener() {}, innerWidth: 400, getComputedStyle: () => ({}),
    document: {querySelector: () => null, querySelectorAll: () => [], addEventListener: (t, f) => { on[t] = f }}};
  new Function('env', 'with (env) {' + logic + src + ';env.draw=walkDraw;env.row=walkRow;env.make=tryExample}')(env);
  env.draw();
  const at = () => el.hidden ? '' : (el.h.match(/data-k="walk:(\w+)"/) || [])[1];
  const press = w => { on.click({detail: 1, target: {closest: s => s === '[data-walk]' ? {dataset: {walk: w}} : null}}); return at() };
  return {at, press, said, went, row: () => env.row(), env};
};
const out = {}, demo = {project: 'demo', example: true};
let p = open(demo);
out.first = p.at(); out.next = p.press('next'); out.went = p.went; out.kept = open(demo).at();
out.skip = p.press('skip'); out.said = p.said; out.stays = open(demo).at(); out.row = p.row().includes('data-walk="again"');
out.again = p.press('again');
out.others = [open({project: 'mine', example: false}).at(), open({project: 'mine'}).at(), open({project: 'mine'}).row(), open({home: 'b', rows: [{key: 'b', state: 'off'}]}).at()];
out.chats = [open({...demo, thread: 'c1'}).at(), open({...demo, view: 'talk'}).at(), open({...demo, all: true}).at()];
out.off = open({home: 'ex', rows: [{key: 'ex', state: 'off', example: true}]}).at();
kept['ar-walk:ex'] = JSON.stringify({at: 'land', off: true});
(async () => {
  const a = open({home: 'z', answer: {ok: true, key: 'ex', made: false}}); await a.env.make(); out.was = [a.env.location.href, !!kept['ar-walk:ex']];
  const b = open({home: 'z', answer: {ok: true, key: 'ex', made: true}}); await b.env.make(); out.made = [b.env.location.href, !!kept['ar-walk:ex']];
  const c = open({home: 'z', answer: {ok: false, out: 'no git'}}); await c.env.make(); out.failed = c.env.location.href || '';
  console.log(JSON.stringify(out));
})();
"""


def test_page(tmp: Path) -> None:
    print('the page: only in the example project; where they are is kept; skip stays; the menu brings it back')
    page = W.PAGE.read_text(encoding='utf-8')
    for fn in ('side', 'offSide'):
        check('walkRow()' in page.split(f'function {fn}(')[1].split('\nfunction ')[0], f'{fn}() has the menu\'s row')
    check('exampleOffer(' in page.split('function projectsHTML(')[1].split('\nfunction ')[0], 'Home draws the offer')
    if not shutil.which('node'):
        print('  (no node here: skipped)')
        return
    (tmp / 'driver.js').write_text(DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs the walkthrough', r.stderr[-1500:])
    if r.returncode:
        return
    o = json.loads(r.stdout)
    eq((o['first'], o['next'], o['went'], o['kept']), ('queue', 'start', ['status'], 'start'), 'Next goes on, to its view; a reload is where they were')
    eq((o['skip'], o['stays'], o['said']), ('', '', ['The walkthrough stays in the menu']), 'skipped, and still after a reload')
    eq((o['row'], o['again']), (True, 'start'), 'the menu shows it again, where it was')
    eq(o['others'], ['', '', '', ''], 'never in another project, nor its menu row')
    eq(o['chats'], ['', '', ''], 'nor over a chat, Talk or All projects')
    eq(o['off'], 'queue', 'on the example project\'s page with no run up too')
    eq((o['was'], o['made'], o['failed']), (['/p/ex/?t=t#home', True], ['/p/ex/?t=t#home', False], ''),
       'the offer opens it; a new copy starts its walkthrough again; one that failed goes nowhere')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_make), in_tmp(test_steps), in_tmp(test_page)]))
