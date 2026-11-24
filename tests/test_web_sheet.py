"""The run page's Needs you popup over a refresh (B222a): the field in use stays the same element.

    python3 tests/test_web_sheet.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from _check import check, eq, report
from _web import in_tmp
from test_web_home import NEED_DRIVER, give_row

from agent_runner import ui_model as U  # noqa: E402
from agent_runner import web as W  # noqa: E402

# the little of a DOM the sheet uses: enough HTML parsing for the page's own well-formed markup
DOM = r"""
const VOID = new Set(['input', 'img', 'br']), un = s => s.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, '&');
const doc = {activeElement: null};
class Node {
  constructor(type, name) { Object.assign(this, {nodeType: type, nodeName: name, childNodes: [], parentNode: null, attrs: new Map(), data: '', typed: null}) }
  get dataset() { const d = {}; for (const [k, v] of this.attrs) if (k.startsWith('data-')) d[k.slice(5).replace(/-(.)/g, (_, c) => c.toUpperCase())] = v; return d }
  get value() { return this.typed ?? this.attrs.get('value') ?? '' } set value(v) { this.typed = v; this.writes = (this.writes || 0) + 1 }
  get type() { return this.attrs.get('type') || 'text' }
  get isConnected() { for (let x = this; x; x = x.parentNode) if (x === root) return true; return false }
  getAttributeNames() { return [...this.attrs.keys()] } getAttribute(k) { return this.attrs.has(k) ? this.attrs.get(k) : null } hasAttribute(k) { return this.attrs.has(k) }
  setAttribute(k, v) { this.attrs.set(k, v) } removeAttribute(k) { this.attrs.delete(k) }
  contains(x) { for (; x; x = x.parentNode) if (x === this) return true; return false }
  remove() { const p = this.parentNode; if (!p) return; if (this.contains(doc.activeElement)) doc.activeElement = null; p.childNodes.splice(p.childNodes.indexOf(this), 1); this.parentNode = null }
  insertBefore(x, at) { x.remove(); const i = at ? this.childNodes.indexOf(at) : this.childNodes.length; if (i < 0) throw Error('insertBefore: not a child'); this.childNodes.splice(i, 0, x); x.parentNode = this }
  isEqualNode(o) { return this.nodeName === o.nodeName && this.data === o.data && this.attrs.size === o.attrs.size && [...this.attrs].every(([k, v]) => o.attrs.get(k) === v)
    && this.childNodes.length === o.childNodes.length && this.childNodes.every((c, i) => c.isEqualNode(o.childNodes[i])) }
  get all() { return this.childNodes.flatMap(c => c.nodeType === 1 ? [c, ...c.all] : []) }
  get text() { return this.data + this.childNodes.map(c => c.text).join('') }
  querySelectorAll(s) { const m = /^\[([\w-]+)(?:\^="(.*)")?\]$/.exec(s); if (!m) throw Error('selector ' + s); return this.all.filter(x => x.hasAttribute(m[1]) && x.getAttribute(m[1]).startsWith(m[2] || '')) }
  focus() { doc.activeElement = this; this.focused = (this.focused || 0) + 1 } setSelectionRange(a, b) { this.selectionStart = a; this.selectionEnd = b }
  set innerHTML(h) {
    [...this.childNodes].forEach(c => c.remove()); let at = this;
    for (const m of h.matchAll(/<\/([\w]+)>|<([\w]+)((?:\s+[\w-]+(?:="[^"]*")?)*)\s*>|[^<]+/g)) {
      if (m[1]) { if (at.nodeName !== m[1]) throw Error('bad markup: </' + m[1] + '> in ' + at.nodeName); at = at.parentNode; continue }
      const x = m[2] ? new Node(1, m[2]) : new Node(3, '#text');
      if (m[2]) for (const a of m[3].matchAll(/([\w-]+)(?:="([^"]*)")?/g)) x.attrs.set(a[1], un(a[2] || '')); else x.data = un(m[0]);
      at.insertBefore(x, null); if (m[2] && !VOID.has(m[2])) at = x }
    if (at !== this) throw Error('unclosed ' + at.nodeName) }
}
const root = new Node(1, 'aside');
root.cls = new Set(); root.classList = {toggle: (c, on) => on ? root.cls.add(c) : root.cls.delete(c)}; root.querySelector = () => null; root.scrollTop = 0;
"""

# the popup's real code on it: setHTML(), keepFields() and all of sheetDraw()
DRIVER = DOM + NEED_DRIVER.split('const S = env.S, out')[0].replace('const el = {', 'const el0 = {', 1).replace('const sent = []', 'const el = root, sent = []', 1) \
    .replace('setHTML: (n, h) => { el.h = h; return false }, ', '').replace('keepFields: () => () => {},', '', 1) \
    .replace('document: {activeElement: null, ', 'document: {get activeElement() { return doc.activeElement }, createElement: () => ({content: new Node(11, "#fragment"), set innerHTML(h) { this.content.innerHTML = h }}), ', 1) \
    .replace("  + line('SHEETS.need=')", "  + line('function setHTML(') + slice('function keepFields(', '/* a press under way') + line('SHEETS.need=')", 1) + r"""
const S = env.S, out = {}, wait = () => new Promise(r => setTimeout(r, 10)), field = f => el.querySelectorAll('[data-f]').find(x => x.dataset.f === f);
env.window = {isSecureContext: true}; env.sureHTML = () => ''; env.kbReveal = () => {}; env.document.querySelectorAll = () => [];
const type = (x, v) => { x.focus(); x.typed = v; x.writes = 0; x.focused = 0; x.selectionStart = x.selectionEnd = 2; S.f[x.dataset.f] = v };
const kept = x => [x.isConnected, field(x.dataset.f) === x, doc.activeElement === x, x.value, x.writes, x.focused, x.selectionStart];
const d7 = needs.find(n => n.id === 'D7'), b1 = needs.find(n => n.id === 'B1'), img = () => el.all.find(x => x.nodeName === 'img');
const fresh = () => { const t = new Node(11, '#fragment'); t.innerHTML = el._h; return el.childNodes.length === t.childNodes.length && el.childNodes.every((c, i) => c.isEqualNode(t.childNodes[i])) };
(async () => {
  press('[data-needopen]', {needopen: 'D7'}, false); await wait();
  let x = field('askre:D7'); out.first = x.value; type(x, 'teh port'); const h = el._h;
  env.render(); out.typed = [kept(x), el._h === h, !h.includes('teh port')];
  const pic = img(); d7.age = '2m'; env.render(); out.age = [kept(x), el.text.includes('2m'), img() === pic, fresh()];
  d7.age = ''; env.render(); out.noage = [kept(x), fresh()];
  d7.detail.notes = ['A note <b>']; d7.detail.steps = ['One', 'Two']; S.askFold = {task: true}; env.render();
  out.parts = [kept(x), el.text.includes('A note <b>') && el.text.includes('Two'), img() === pic, fresh()];
  d7.detail.steps = []; d7.options = [{name: 'A'}, {name: 'B'}]; d7.answers = [{label: 'A', value: 'A'}, {label: 'B', value: 'B'}]; d7.acts = ['need_answer1', 'need_answer2']; d7.labels = {need_answer1: 'A', need_answer2: 'B'}; env.render();
  out.buttons = [kept(x), el.querySelectorAll('[data-ctl]').length, el.querySelectorAll('[data-reply]').length, fresh()];
  S.askShot = 0; env.render(); out.shot = [kept(x), fresh()]; S.askShot = -1; env.render(); out.unshot = [kept(x), fresh()];
  doc.activeElement = null; d7.age = '3m'; env.render(); out.unfocused = [field('askre:D7').value, field('askre:D7') !== x];
  env.closeSheet(); press('[data-needopen]', {needopen: 'B1'}, false); await wait(); out.other = field('askre:B1').value;
  env.closeSheet(); press('[data-needopen]', {needopen: 'D7'}, false); await wait(); out.back = field('askre:D7').value;
  env.closeSheet(); press('[data-needopen]', {needopen: 'D7'}, false); out.again = field('askre:D7').value;
  env.closeSheet(); delete S.f['askre:D7']; press('[data-needopen]', {needopen: 'D7'}, false); out.sentGone = field('askre:D7').value;
  x = field('askre:D7'); type(x, 'ok'); S.snap.needs = needs.filter(n => n.id !== 'D7'); env.render(); out.left = [S.sheet, el.cls.has('open')];
  S.snap.needs = needs; press('[data-needopen]', {needopen: 'D7'}, false); x = field('askre:D7'); type(x, '8770'); press('[data-reply]', {reply: 'D7'}); out.replied = [S.sheet, sent.slice(-1)[0]];
  S.snap.needs = needs; press('[data-needopen]', {needopen: 'F399'}, false); await wait();
  const link = field('give:F399:link'), tok = field('givesec:F399:tok'); type(tok, 'hunter2'); type(link, 'http');
  const f = needs.find(n => n.id === 'F399'); f.age = '9m'; f.detail.lead = ['New words']; S.giveSaid = {id: 'F399', field: 'link', out: 'Not a link'}; env.render();
  out.give = [kept(link), link.getAttribute('aria-invalid'), el.text.includes('Not a link') && el.text.includes('9m'), field('givesec:F399:tok').value, fresh()];
  S.giveSaid = {}; env.render(); out.giveOk = [kept(link), link.getAttribute('aria-invalid'), fresh()];
  f.detail.inputs = f.detail.inputs.slice(1); env.render(); out.inputGone = [!!field('give:F399:link'), field('givesec:F399:tok').value, fresh()];
  console.log(JSON.stringify(out)); process.exit(0);
})();
"""


def test_need_field_stays_b222a(tmp: Path) -> None:
    """B222a: through a refresh after typing, an age, notes, steps, buttons or a picture, the reply or give field in use
    is the same element, never written to or focused again; its words come back after closing and reopening; an
    answered item closes the popup."""
    if not shutil.which('node'):
        print('  (no node here: the popup field test is skipped)')
        return
    d = {'said': 'Choose', 'where': '', 'title': 'Port', 'summary': 'p', 'question': 'Which port?', 'lead': ['8765 is taken.'], 'steps': [],
         'expect': [], 'notes': [], 'shots': [{'src': 'a.png', 'path': '/x', 'caption': 'c'}]}
    needs = [{'id': 'D7', 'label': 'DECIDE', 'ask': 'Which port?', 'age': '1m', 'detail': d, 'answers': []},
             {'id': 'B1', 'label': 'BLOCKED', 'ask': 'Log in', 'answers': [{'label': 'Done', 'value': 'Done'}]}, give_row()]
    for n in needs:
        n.update(acts=U.row_acts('need', n), labels=U.row_labels('need', n))
    (tmp / 'driver.js').write_text(DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE), json.dumps(needs), json.dumps(U.controls())], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node types in the popup', r.stderr[-1500:])
    if r.returncode:
        return
    o = json.loads(r.stdout)
    same = [True, True, True, 'teh port', 0, 0, 2]  # in the page, the same element, in focus, its words, never written, never focused again, its caret
    eq(o['first'], '', 'the reply box starts empty')
    eq(o['typed'], [same, True, True], 'a refresh after typing draws nothing: no typed word is in the markup')
    eq(o['age'], [same, True, True, True], 'a new age: the same field, and the picture is not drawn again')
    eq(o['noage'], [same, True], 'the age going')
    eq(o['parts'], [same, True, True, True], 'notes, steps and a fold')
    eq(o['buttons'], [same, 2, 1, True], 'answer buttons beside the field')
    eq((o['shot'], o['unshot']), ([same, True], [same, True]), 'a picture opening and closing')
    eq(o['unfocused'], ['teh port', True], 'a field not in use is drawn again, with its words')
    eq((o['other'], o['back'], o['again']), ('', 'teh port', 'teh port'), 'its words come back after closing and reopening, and only there')
    eq(o['sentGone'], '', 'the words of a reply that was sent do not')
    eq(o['left'], ['', False], 'an item answered elsewhere closes the popup, also while typing')
    eq(o['replied'], ['', ['answer', {'tid': 'D7', 'text': '8770'}]], 'a reply closes it')
    eq(o['give'], [[True, True, True, 'http', 0, 0, 2], 'true', True, 'hunter2', True], 'a give field: the same element, marked refused; the other keeps its words')
    eq(o['giveOk'], [[True, True, True, 'http', 0, 0, 2], None, True], 'and not refused again')
    eq(o['inputGone'], [False, 'hunter2', True], 'its input left the item: it goes, the other stays')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_need_field_stays_b222a)]))
