#!/usr/bin/env python3
"""F428d: a tool's own buttons on the Tools page: on its card, the questions asked in place, what a press answered, and
the fields that set a device's.

    python3 tests/test_web_tool_buttons.py        (node; a second)
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from _check import check, eq, report

from agent_runner import web as W  # noqa: E402

DRIVER = r"""
const src = require('fs').readFileSync(process.argv[2], 'utf8'), cut = (a, b) => src.slice(src.indexOf(a), src.indexOf(b, src.indexOf(a)));
const S = {toolBusy: '', toolSaid: {}, f: {}, tools: {secure: true, aliases: [], tools: []}, sure: null, view: 'tools'}, sent = [], did = [];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => '&#' + c.charCodeAt(0) + ';'), clock = {now: () => clock.t, t: 100000};
let answer, focused = '';
const fetch = (u, o) => new Promise((ok, no) => { sent.push(JSON.parse(o.body)); answer = j => j ? ok({json: async () => j}) : no(new Error('gone')) });
const sheet = {_h: '', querySelectorAll: () => [], querySelector: q => ({focus: () => { focused = q }})};
const SHEETS = {}, toolPost = async (b, k) => { sent.push(b); return {ok: true, out: 'saved'} };
const f = new Function('S', 'esc', 'I', 'card', 'render', 'tq', 'fetch', 'Date', 'toolPost', 'location', '$', 'loadTools', 'plainOut', 'SHEETS', 'openSheet',
  'closeSheet', 'toast', 'QUESTION_AGAIN', cut('const toolOf=', 'function toolsHTML') + cut('const devText=', 'async function toolClick')
  + cut('async function toolClick', '\n}\n') + '\n}; return {toolCard, toolClick, toolEdit, toolForget}')(
  S, esc, {ext: ''}, (h, c, a) => `<${a}>` + h, () => {}, x => x, fetch, clock, toolPost, {hostname: 'box'}, () => sheet, async () => did.push('load'),
  (j, o) => j.out || o, SHEETS, () => {}, () => did.push('close'), () => {}, 500);
const LONG = 'Restart ' + 'a'.repeat(52), B = [{label: 'Wake', cmd: 'x'}, {label: 'Restart <it>', cmd: 'x', confirm: 'Really "restart"  it?'}, {label: LONG, cmd: 'x'}];
const base = {name: 'phone', label: 'The phone', description: '', used: true, state: 'free', words: 'free', at: 0, buttons: B};
const toml = {...base, source: 'runner.toml'}, dev = {...base, label: 'phone', source: 'device', kind: 'other', reach: 'x', secrets: {}};
S.tools.tools = [toml, dev];
const btns = t => [...f.toolCard(t).matchAll(/<button class="btn([^"]*)" data-tool="(press\w*)" data-name="([^"]*)" data-source="([^"]*)"([^>]*)>([^<]*)</g)]
  .map(m => [m[6], m[1].trim(), / disabled/.test(m[5]) ? 'off' : '', m[2]].join('|').replaceAll('&#60;', '<').replaceAll('&#62;', '>'));
const ask = t => (f.toolCard(t).match(/data-k="pressask:[^"]*" role="group"><div[^>]*>([^<]*)</) || [])[1] || '';
const said = t => { const m = f.toolCard(t).match(/data-k="pressed:[^"]*" role="status"><div class="([^"]*)">([^<]*)<\/div>(?:<pre class="tasktext">([^<]*)<)?/); return m ? [/v-bad/.test(m[1]), m[2], m[3] || '', f.toolCard(t).endsWith('</div>')] : null };
const click = (tool, o = {}) => f.toolClick({dataset: {tool, name: 'phone', source: 'runner.toml', ...o}});
const soon = () => new Promise(r => setImmediate(r)), say = async j => { answer(j); await soon() };
(async () => {
  const out = {};
  out.idle = [btns(toml), btns(dev)]; S.tools.secure = false; out.ro = btns(toml); S.tools.secure = true;
  out.none = [{...toml, buttons: undefined}, {...dev, buttons: undefined}].map(t => /toolbtns|press/.test(f.toolCard(t)));
  // one that runs
  click('press', {label: 'Wake'}); out.busy = [btns(toml), btns(dev)]; click('press', {label: LONG}); out.once = sent.length;
  click('press', {label: 'Wake', source: 'device'}); out.two = sent.length; await say({ok: true, out: 'Wake: done', lines: []}); out.devSaid = [said(dev), said(toml), btns(dev)];
  delete S.press['runner.toml:phone'];
  out.run = []; for (const j of [{ok: true, out: 'Wake: done', exit: 0, lines: ['up', '<b>']}, {ok: false, out: 'Wake: failed (exit 3)', exit: 3, lines: ['no']}, {ok: false, out: 'phone has no such button'}, null]) {
    click('press', {label: 'Wake'}); out.cleared = said(toml); await say(j); out.run.push(said(toml)) }
  out.sent = sent.splice(0); out.loads = did.splice(0).length;
  // a question: No, a second tap, Yes; another question than the one shown
  const yes = () => click('pressyes'); await click('press', {label: 'Restart <it>'}); out.ask = [ask(toml), btns(toml), ask(dev), sent.length];
  await click('pressno'); out.no = [ask(toml), btns(toml).length];
  await click('press', {label: 'Restart <it>'}); await yes(); out.tap = sent.length; clock.t += 600;
  yes(); out.asked = btns(toml)[1]; await say({ok: false, out: 'New?', ask: 'New?'}); out.again = [ask(toml), btns(toml)[0]]; clock.t += 600;
  // someone has it: then another one has
  yes(); await say({ok: false, out: 'x', busy: {holder: 'T4 <a>', key: 'k1'}}); out.held = [ask(toml), btns(toml)]; clock.t += 600;
  yes(); await say({ok: false, out: 'x', busy: {holder: 'T5', key: 'k2'}}); out.other = ask(toml); clock.t += 600;
  yes(); await say({ok: true, out: 'Restart: done', lines: []}); out.end = [ask(toml), said(toml)]; out.asks = sent.splice(0);
  // its button went while the question stood
  await click('press', {label: 'Restart <it>'}); out.gone = [ask({...toml, buttons: [B[0]]}), btns({...toml, buttons: [B[0]]})]; await click('pressno');
  // a device's sheet
  const heads = h => [...h.matchAll(/role="group" aria-label="(Button \d)"/g)].map(m => m[1]), fields = h => [...h.matchAll(/data-f="dev:(b\d+-\w+)"/g)].map(m => m[1]);
  f.toolEdit(dev); out.form = [heads(SHEETS.device()), fields(SHEETS.device()), S.f['dev:b1-confirm'], SHEETS.device().includes('restart')];
  await click('btndel', {i: '0'}); await click('btnadd'); out.focus = focused; out.more = [heads(SHEETS.device()), fields(SHEETS.device()).filter(x => x.endsWith('label')), 'dev:b0-label' in S.f];
  S.f['dev:b3-label'] = 'Lock'; S.f['dev:b3-cmd'] = 'lock it';
  S.press = {phone: {said: {ok: true, out: 'old', lines: []}}}; await f.toolClick({dataset: {tool: 'save', name: 'phone'}}); out.saved = [sent.pop().buttons, said(dev)];
  f.toolForget(); out.left = Object.keys(S.f).filter(k => k.startsWith('dev:'));
  f.toolEdit(dev); for (const i of '012') await click('btndel', {i}); await f.toolClick({dataset: {tool: 'save', name: 'phone'}}); out.empty = sent.pop().buttons;
  f.toolEdit(null); out.add = fields(SHEETS.device()); await click('btnadd'); out.first = fields(SHEETS.device());
  S.press = {phone: {said: {ok: true, out: 'old', lines: []}}}; await f.toolClick({dataset: {tool: 'remove', name: 'phone'}}); out.removed = said(dev);
  click('press', {label: 'Wake', source: 'device'}); await f.toolClick({dataset: {tool: 'remove', name: 'phone'}}); await say({ok: true, out: 'Wake: done', lines: []}); out.late = [said(dev), btns(dev)[0]];
  console.log(JSON.stringify(out));
})();
"""


def test_page(tmp: Path) -> None:
    print("a tool's own buttons: its card, the questions, the answers, a device's sheet")
    if not shutil.which('node'):
        print('  (no node here: skipped)')
        return
    (tmp / 'page.js').write_text(DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'page.js'), str(W.PAGE)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0 and bool(r.stdout), 'node draws the cards', r.stderr[-1500:])
    if r.returncode or not r.stdout:
        return
    o, long, re_ = json.loads(r.stdout), 'Restart ' + 'a' * 52, 'Restart <it>'
    names, src = ('Wake', re_, long), 'runner.toml'
    idle = [f'{n}|||press' for n in names]
    eq(o['idle'], [idle, idle], 'each tool shows its own')
    eq(o['ro'], [f'{n}||off|press' for n in names], 'read only: disabled')
    eq(o['none'], [False, False], 'a tool with none has none of it')
    eq(o['busy'], [['Wake|busy||press', f'{re_}||off|press', f'{long}||off|press'], idle], "busy; a tool's other buttons wait, another tool's do not")
    eq((o['once'], o['two']), (1, 2), 'one at a time per tool, two tools side by side')
    eq(o['devSaid'], [[False, 'Wake: done', '', True], None, idle], "the answer is on its own tool's card")
    eq(o['run'][:3], [[False, 'Wake: done', 'up\n&#60;b&#62;', True], [True, 'Wake: failed (exit 3)', 'no', True],
                      [True, 'phone has no such button', '', True]], 'the result, the failure with its lines, the refusal: at the foot of the card')
    check(o['run'][3][0] and 'may have run' in o['run'][3][1], 'no answer: it does not say that nothing ran', o['run'][3])
    eq(o['cleared'], None, 'a new press takes the old answer away')
    p = {'op': 'press', 'name': 'phone', 'button': 'Wake', 'source': src}
    eq(o['sent'], [p, {**p, 'source': 'device'}, *[p] * 4], 'what a press sends')
    eq(o['loads'], 5, 'the states are read again after each')
    q = 'Really &#34;restart&#34;  it?'
    yes, no = [f'Yes, {re_}|bad||pressyes', 'No|||pressno']
    eq(o['ask'], [q, [yes, no], '', 0], "its question in the buttons' place, nothing sent")
    eq(o['no'], ['', 3], 'No: the buttons again')
    eq(o['tap'], 0, 'a second tap on the same spot is no Yes')
    eq(o['asked'], f'{re_}|busy||press', 'Yes: busy')
    eq(o['again'], ['New?', yes], 'another question by now: asked again')
    eq(o['held'], ['The phone is held by T4 &#60;a&#62;.', ['Use it anyway|bad||pressyes', no]], 'names the holder')
    eq(o['other'], 'The phone is held by T5.', 'a new holder asks again')
    eq(o['end'], ['', [False, 'Restart: done', '', True]], 'then it runs')
    p = {**p, 'button': re_}
    eq(o['asks'], [{**p, 'confirm': 'Really "restart"  it?'}, {**p, 'confirm': 'New?'}, {**p, 'confirm': 'New?', 'holder': 'k1'},
                   {**p, 'confirm': 'New?', 'holder': 'k2'}], 'the question exactly as asked, and the holder that was named')
    eq(o['gone'], ['', ['Wake|||press']], 'a question goes with its button')
    eq(o['form'], [['Button 1', 'Button 2', 'Button 3'], [f'b{i}-{k}' for i in range(3) for k in ('label', 'cmd', 'confirm')],
                   'Really "restart"  it?', False], "the sheet has a device's buttons, no value in the markup")
    eq(o['more'], [['Button 1', 'Button 2', 'Button 3'], ['b1-label', 'b2-label', 'b3-label'], False], 'one removed, one added')
    eq(o['focus'], '[data-f="dev:b3-label"]', 'the new one has the focus')
    eq(o['saved'], [[{'label': re_, 'cmd': 'x', 'confirm': 'Really "restart"  it?'}, {'label': long, 'cmd': 'x', 'confirm': ''},
                     {'label': 'Lock', 'cmd': 'lock it', 'confirm': ''}], None], 'saved with the device; what an old press said goes')
    eq(o['left'], [], 'what was typed goes when the sheet closes')
    eq(o['empty'], [], 'all removed')
    eq((o['add'], o['first']), ([], ['b0-label', 'b0-cmd', 'b0-confirm']), 'a new device has none, and can get one')
    eq(o['removed'], None, 'a removed device leaves no answer')
    eq(o['late'], [None, 'Wake|||press'], 'nor one that comes after it went')


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        return report([lambda: test_page(Path(tmp))])


if __name__ == '__main__':
    sys.exit(main())
