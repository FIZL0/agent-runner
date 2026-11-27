"""The run page's History view (F426c; agent_runner/page/200-history-view.js) and what the snapshot holds for it.

    python3 tests/test_web_history_view.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from _check import check, eq, report

from agent_runner import plan_search as PS  # noqa: E402
from agent_runner import state as S  # noqa: E402
from agent_runner import ui_model as U  # noqa: E402
from agent_runner import web as W  # noqa: E402
from _web import fake_repo, in_tmp, logic_js  # noqa: E402


def events(*evs: tuple) -> None:
    S.C.notes('events.jsonl').write_text(''.join(
        json.dumps({'time': at, 'kind': kind, 'id': tid, **more}) + '\n' for at, kind, tid, more in evs), encoding='utf-8')


def done_file(tmp: Path) -> Path:
    f = tmp / 'DONE-search.md'
    f.write_text('# DONE\n' + ''.join(f'- [x] **{t}** An old thing\n' for t in ('V5', 'F100', 'C9')), encoding='utf-8')
    return f


def test_snapshot(tmp: Path) -> None:
    """The lately rows carry the task's id, its kind and title, and are more than 6; past releases have their version."""
    fake_repo(tmp)
    events(*[(f'2026-11-20T10:00:{i:02d}', S.EV_LANDED, f'F{i + 100}', {}) for i in range(12)],
           ('2026-11-21T09:00:00', S.EV_LANDED, 'V5', {}),
           ('2026-11-21T09:00:05', S.EV_RELEASED, '', {'text': 'proj 1.2.0 released: Added: x.'}),
           ('2026-11-22T09:00:00', S.EV_LANDED, 'V6', {}),
           ('2026-11-22T09:00:05', S.EV_RELEASED, '', {'text': 'proj 1.3.0 released: Added: y.'}),
           ('2026-11-22T10:00:00', S.EV_PART, 'F1', {}),
           ('2026-11-22T11:00:00', S.EV_LEFT, 'B2', {'why': 'a check'}),
           ('2026-11-22T12:00:00', S.EV_IDLE, '', {}))
    snap = U.snapshot(up=True, links={})
    json.dumps(snap)
    late = snap['lately']
    eq(len(late), 17, 'more than 6 (every one here)')
    eq([(r['id'], r['kind']) for r in late[:5]], [('', ''), ('B2', ''), ('F1', 'part'), ('V6', 'landed'), ('V5', 'landed')],
       'newest first, each with its task and kind')
    check(late[2].get('title') and '[F1]' not in late[2]['title'] and 'landed' not in late[2]['title'], 'the title alone', late[2])
    check('title' not in late[1], 'a row that is no landing has none', late[1])
    eq(late[2]['text'].startswith(f'part landed'), True, 'the words are as before')
    eq(snap['past_releases'], [{'id': 'V6', 'title': 'Release 1.3.0', 'at': '2026-11-22T09:00:00'},
                               {'id': 'V5', 'title': 'Release 1.2.0', 'at': '2026-11-21T09:00:00'}], 'newest first')
    hits = {h['id']: h for h in PS.search('old', done=done_file(tmp))['done']}
    eq((hits['V5'].get('at'), hits['V5'].get('release'), hits['F100'].get('at'), 'at' in hits['C9']),
       ('2026-11-21T09:00:00', True, '2026-11-20T10:00:00', False), 'a search hit says when it landed')
    S.C.run['releases'] = False
    off = U.snapshot(up=True, links={})
    eq(off['past_releases'], [], 'none with releases off')
    S.C.run['releases'] = True
    events(*[('2026-11-20T10:00:00', S.EV_LANDED, f'F{i}', {}) for i in range(1, 201)])
    eq(len(U.snapshot(up=True, links={})['lately']), U.LATELY_MAX, 'capped')
    events(*[('2026-11-20T10:00:00', S.EV_LANDED, f'F{i}', {}) for i in range(1, 31)],
           *[('2026-11-20T11:00:00', S.EV_IDLE, '', {})] * 100)
    late = U.snapshot(up=True, links={})['lately']
    eq((len(late), sum(r['kind'] == 'landed' for r in late)), (36, 30), 'other events do not crowd the landings out')


def test_links() -> None:
    """History is the NAV row after Plan; its link opens it and every older link opens what it did."""
    page = W.PAGE.read_text(encoding='utf-8')
    check("['plan','Work'],['concepts','Concepts']" in page and "'history'].includes(v)?'plan'" in page, 'F476: History is part of the Work page; its old link opens Work')
    for part in ('history:historyHTML', "history:'History'", "\n history:ic("):
        check(part in page, f'the page has {part}')
    if not shutil.which('node'):
        print('  (no node here: the links are not run)')
        return
    links = ['#history', '#talk', '#home', '#status', '#agents', '#activity', '#plan', '#concepts', '#tools', '#settings', '#nope']
    got = logic_js([['placeOf', '', h, False, []] for h in links])
    eq([(g['v'], g['link']) for g in got],
       [('plan', True), ('talk', True), ('home', True), ('plan', True), ('plan', True), ('plan', True), ('plan', True),
        ('concepts', True), ('tools', True), ('settings', True), ('home', False)], 'each link (F476: History, Status and their old names open Work)')
    eq(logic_js([['placeOf', '{"v":"history"}', '', False, []]])[0]['v'], 'plan', 'a reload of History opens Work (F476)')
    ctx = {'kind': 'report', 'id': 'F1', 'title': 'One', 'label': 'x'}
    got = logic_js([['compose', ctx, 'it is blank', []], ['ctxKey', ctx], ['newPh', ctx]])
    check(got[0].startswith('A problem with F1 (One), which has landed: it is blank') and 'bug task' in got[0], 'the report', got[0])
    eq(got[1:], ['+report:F1', 'What is the problem?'], 'its new chat, not the one of Chat')


DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const grab = a => page.slice(page.indexOf(a), page.indexOf('\n}\n', page.indexOf(a)) + 3);
const from = page.indexOf('/* F426c: the History view'), src = page.slice(from, page.indexOf("\ndocument.addEventListener('click'", from));
const snap = JSON.parse(process.argv[3]);
const opened = [], chats = [], asked = [];
const env = {S: {snap, f: {}, taskOpen: {}, tasks: {}}, I: new Proxy({}, {get: () => ''}), LOGLINE_ICON: {},
  esc: s => String(s ?? ''), taskChip: id => `<kind ${id}>`, card: (h, c, a) => `<div class="card" ${a}>${h}</div>`, emptyCard: t => `[empty ${t}]`,
  foldIn: (k, h) => `<fold>${h}</fold>`, agoWords: () => '5 min', logKind: () => '', releasesOn: s => s.manage_releases !== false,
  oldRun: () => false, oldRunHTML: t => t, plainOut: (j, t) => t, tq: p => p, render: () => {}, clearTimeout: () => {}, setTimeout: f => { env.fire = f; return 1 },
  open: k => opened.push(k), ctxKey: c => '+' + c.kind + ':' + c.id, newChat: (...a) => chats.push(a), kbFocus: () => {},
  document: {querySelector: () => null}, fetch: async u => { asked.push(u); return {json: async () => env.reply} }};
env.taskIsOpen = (l, id) => env.S.taskOpen[l] === id;
env.taskBodyHTML = new Function(grab('function taskBodyHTML') + ';return taskBodyHTML')();  // F509
new Function('env', 'with(env){' + src + ';Object.assign(env,{historyHTML,histAct,histLoad})}')(env);
(async () => {
  const out = {shut: env.historyHTML()};
  env.S.taskOpen = {landed: 'F1'}; out.loading = env.historyHTML();
  env.S.tasks.F1 = {text: 'the whole text'}; out.open = env.historyHTML();
  env.S.taskOpen = {}; env.S.f.histq = 'OLD thing'; out.wait = env.historyHTML();
  env.reply = {ok: true, q: 'OLD thing', open: [], parked: [], done: [{id: 'F9', title: 'Old thing', state: 'done', at: '2026-01-02T10:00:00'}, {id: 'F7', title: 'By hand', state: 'done'}, {id: 'V1', title: 'Old release', state: 'done', at: '2026-01-02T10:00:00', release: true}, {id: 'F8', title: 'Old thing dropped', state: 'dropped'}], more: 2};
  env.fire(); await new Promise(r => setImmediate(r)); out.found = env.historyHTML();
  env.S.f.histq = 'started'; out.log = env.historyHTML();
  env.reply = {ok: true, q: 'started', open: [], parked: [], done: [], more: 0};
  await env.histLoad(); env.S.f.histq = 'zzz'; env.historyHTML(); env.reply = {...env.reply, q: 'zzz'}; await env.histLoad(); out.none = env.historyHTML();
  env.reply = {ok: false}; await env.histLoad(); out.failed = env.historyHTML();
  env.S.f.histq = '';
  env.histAct('changed', 'F1'); env.histAct('report', 'F1'); out.ctx = [env.S.ctx]; env.histAct('chat', 'V6'); out.ctx.push(env.S.ctx); env.histAct('chat', 'gone');
  env.S.snap = {...snap, manage_releases: false, past_releases: []}; out.off = env.historyHTML();
  env.S.snap = {log: []}; out.empty = env.historyHTML();
  console.log(JSON.stringify({...out, opened, chats, asked}));
})();
"""


def test_view(tmp: Path) -> None:
    """Search, landed, past releases, the run log; a row opens in place to its text, its time and its options."""
    if not shutil.which('node'):
        print('  (no node here: the History view is not drawn)')
        return
    row = lambda tid, kind, title: {'at': '2026-11-21T20:55:00', 'text': f'x [{tid}]', 'id': tid, 'kind': kind, 'title': title}  # noqa: E731
    snap = {'lately': [row('F1', 'landed', 'One'), row('F1', 'part', 'One'), row('B2', 'part', 'Two'), row('V6', 'landed', 'Release 1.3.0'),
                       {'at': '2026-11-21T20:00:00', 'text': 'needs you: C3 [C3]', 'id': 'C3', 'kind': ''}],
            'past_releases': [{'id': 'V6', 'title': 'Release 1.3.0', 'at': '2026-11-21T20:55:00'}],
            'log': ['10:00 started F1', '10:05 landed F1']}
    (tmp / 'driver.js').write_text(DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE), json.dumps(snap)],
                       capture_output=True, text=True, encoding='utf-8', timeout=60)
    check(r.returncode == 0, 'node runs the page script', r.stderr[-800:])
    o = json.loads(r.stdout)
    shut = o['shut']
    at = [shut.find(x) for x in ('Find in history', '>Landed<', '>Releases<', '>Run log<', 'data-quick="since"', '10:05 landed F1', '10:00 started F1')]
    check(all(i >= 0 for i in at) and at == sorted(at), 'search, landed, releases, the log newest first', at)
    eq([shut.count(f'data-task="{t}"') for t in ('F1', 'B2', 'V6', 'C3')], [1, 1, 1, 0], 'each once, a release in Releases, and no other event')
    check('data-task="V6" data-list="pastrel"' in shut and '>part landed · 5 min<' in shut and '<kind B2>' in shut, 'the release; a part says so', shut)
    check('data-hist="' not in shut and 'aria-expanded="true"' not in shut, 'all shut')
    check('Loading…' in o['loading'], 'its text is on the way', o['loading'])
    op = o['open']
    check('the whole text' in op and 'Landed at ' in op, 'its text and its time', op)
    at = [op.find(f'data-hist="{k}" data-id="F1"') for k in ('changed', 'report', 'chat')]
    check(all(i >= 0 for i in at) and at == sorted(at), 'What changed, Report a problem, Chat last', op)
    eq(op.count('<fold>'), 1, 'that row alone')
    check('Loading…' in o['wait'], 'a search waits', o['wait'])
    check('data-task="F9"' in o['found'] and 'F8' not in o['found'] and '2 more done tasks' in o['found'], 'older landed tasks, not a dropped one', o['found'])
    check('data-task="F9" data-list="landed"' in o['found'] and 'data-task="F7" data-list="donelist"' in o['found']
          and 'data-task="V1" data-list="pastrel"' in o['found'], 'one that landed, one that did not, a release', o['found'])
    check('plan-search?q=OLD%20thing' in o['asked'][0], 'the server is asked', o['asked'])
    check('10:00 started F1' in o['log'] and '10:05' not in o['log'], 'the run log is searched', o['log'])
    check('[empty Nothing matches.]' in o['none'], 'nothing found', o['none'])
    check('data-histload' in o['failed'], 'a failed search: Try again', o['failed'])
    ((name, args, say, ask),) = o['chats']
    check(name == 'new_control' and args['ask'] == ask and 'F1 (One)' in ask and say == 'What changed in F1', 'What changed asks a new chat', o['chats'])
    eq([(c['kind'], c['id'], c['title']) for c in o['ctx']], [('report', 'F1', 'One'), ('plan', 'V6', 'Release 1.3.0')], 'the new chat views')
    eq(o['opened'], ['+report:F1', '+plan:V6'], 'opened, and nothing for a task that is gone')
    check('>Releases<' not in o['off'] and 'data-task="V6"' in o['off'], 'releases off: an ordinary landed task', o['off'])
    for words in ('Nothing has landed yet.', 'Nothing has been released yet.', 'Nothing in the run log yet.'):
        check(words in o['empty'], words, o['empty'])


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_snapshot), test_links, in_tmp(test_view)]))
