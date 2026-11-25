"""The run page's Status view (F426e; agent_runner/page/076-status.js, 032-status.logic.js) and the snapshot's merging
tasks (agent_runner/merge_rows.py).

    python3 tests/test_web_status_view.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from unittest import mock

from _check import check, eq, report

from agent_runner import merge_rows as M  # noqa: E402
from agent_runner import state as S  # noqa: E402
from agent_runner import ui_model as U  # noqa: E402
from agent_runner import web as W  # noqa: E402
from _web import fake_repo, in_tmp, logic_js  # noqa: E402


def test_merge_rows(tmp: Path) -> None:
    """A merging task whose slot went on has a row: its step is the run log's last words since it left its slot."""
    fake_repo(tmp)
    S.C.notes('run.log').write_text(
        '=== 2026-11-25T09:00:00 F1: the gate failed an hour ago\n=== 2026-11-25T10:00:00 slot 1: F1 finished: all done\n'
        '=== 2026-11-25T10:00:01 slot 1: B2 (Next; b.py)\n=== 2026-11-25T10:00:02 F1: conflicts in a.py need reading — handing them to a fix session\n'
        '=== 2026-11-25T10:00:03 F10: merged, ticked\nnot a line\n', encoding='utf-8')
    st = {'merging': ['F1', 'B2'], 'running': {'1': 'B2'}, 'slots': 1}
    got = M.rows(st, {'F1': 'Board page'}, lambda sid: '', {})
    eq(got[0], {'id': 'F1', 'title': 'Board page', 'step': 'Conflicts in a.py need reading, handing them to a fix session', 'link': ''}, 'its step')
    eq(got[1]['step'], '', 'nothing said since its slot: no step')
    asked = []
    M.LINKS.clear()
    with mock.patch('agent_runner.watch.last_session', side_effect=lambda t: asked.append(t) or (1, 'sid-' + t)):
        links = [M.rows(st, {}, lambda sid: 'https://x/' + sid)[0]['link'] for _ in range(2)]
        eq(links, ['https://x/sid-F1'] * 2, "its session's link")
        eq(asked, ['F1', 'B2'], 'looked up once while it merges')
        M.rows({}, {}, lambda sid: '')
        eq(M.LINKS, {}, 'and forgotten after')
    S.C.notes('STATE').write_text(json.dumps(st), encoding='utf-8')
    eq([r['id'] for r in U.snapshot(up=True, links={})['merging']], ['F1', 'B2'], 'in the snapshot')
    eq(U.snapshot(up=False, links={})['merging'], [], 'none with no run up')


def test_logic() -> None:
    if not shutil.which('node'):
        print('  (no node here: the logic is not run)')
        return
    q = lambda i, state, *files, **more: {'id': i, 'state': state, 'files': list(files), **more}  # noqa: E731
    run = q('F1', 'running s1 3m', 'a/**', 'b.py')
    cases = [({'queue': [run, q('F2', 'after')], 'run': {'paused': True}}, 'The run is paused: no new tasks start.'),
             ({'queue': [q('F2', 'ready')], 'run': {'stopping': True, 'paused': True}}, 'The run is stopping: nothing new starts.'),
             ({'queue': [run, q('F9', 'parked')]}, 'The queue is empty.'),
             ({}, 'The queue is empty.'),
             ({'queue': [run, q('F2', 'ready', 'a/x.js')]}, 'Of 1 queued task, 1 shares files with a task under way.'),
             ({'queue': [run, q('F2', 'ready', 'b.py'), q('F3', 'after'), q('F4', 'after'), q('B5', 'blocked'), q('C1', 'held'),
                         q('T1', 'tool'), q('D1', 'critical', 'c.md')]},
              'Of 7 queued tasks, 1 shares files with a task under way, 2 wait for another task, 1 is blocked, 1 is held, '
              '1 waits for a tool or a check, 1 is ready but not started yet.')]
    eq(logic_js([['idleWhy', s, []] for s, _ in cases]), [w for _, w in cases], 'why an idle slot starts nothing')
    eq(logic_js([['idleWhy', {'queue': [q('F2', 'ready', 'a/x.js'), q('F3', 'ready', 'a/**')]}, ['F2']]]),
       ['Of 1 queued task, 1 shares files with a task under way.'], 'a merging task is under way, not queued')
    snap = {'merging': [{'id': 'F1', 'title': '', 'step': 'x', 'link': 'l'}, {'id': 'F2', 'title': 'Two', 'step': '', 'link': ''}],
            'sessions': [{'name': 's1', 'task': 'F1', 'title': 'One', 'state': 'merging'}, {'name': 's2', 'task': 'F3', 'title': 'Three', 'state': 'merging'},
                         {'name': 's3', 'task': 'F4', 'state': 'running'}]}
    rows, older, none = logic_js([['mergeRows', snap], ['mergeRows', {'sessions': snap['sessions']}], ['mergeRows', {}]])
    eq([(r['id'], r['title'], r.get('slot')) for r in rows], [('F1', 'One', 's1'), ('F2', 'Two', None), ('F3', 'Three', 's2')], 'each once')
    eq(([r['id'] for r in older], none), (['F1', 'F3'], []), 'an older run, and no plan yet')


DRIVER = r"""
const fs = require('fs'), page = fs.readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const line = a => page.slice(page.indexOf(a), page.indexOf('\n', page.indexOf(a)) + 1);
const grab = a => page.slice(page.indexOf(a), page.indexOf('\n}\n', page.indexOf(a)) + 3);
const S = {ob: [], taskOpen: {}, tasks: {}, sure: null, snap: JSON.parse(fs.readFileSync(process.argv[3], 'utf8'))};
const asked = [], clicks = [];
const env = {S, MO: {}, I: new Proxy({}, {get: () => ''}), lastWords: n => n === 's1' ? 'Reading the plan' : '', taskChip: id => `<kind ${id}>`, obCards: () => '', ttydLine: () => '',
  meterHTML: m => `[${m.name} ${m.said}]`, emptyCard: t => `[${t}]`, controlsCard: () => '[run card]', foldIn: (k, h) => `<fold>${h}</fold>`, oldRunHTML: t => t, taskInView: () => {}, render: () => {},
  plainOut: (j, t) => t, oldRun: () => false, tq: p => p, fetch: async u => { asked.push(u); return {json: async () => ({ok: true, text: 'the whole text'})} }, document: {addEventListener: (k, f) => clicks.push(f)}};
const src = ['const esc=', 'const card=', 'const controlsOf=', 'const controlOf=', 'const ctlBusy=', 'const sureHTML=', 'const ctlSure=', 'const slots=', 'const working_=', 'const sessionOf=',
  'const taskControlsOn=', 'const taskIsOpen=', 'const chatBtn='].map(line).join('') + grab('function cutsOff(') + grab('async function openTask(')
  + LOGIC + STATUS;
const draw = new Function('env', 'with(env){' + src.replace(/^const /gm, 'var ') + '; return {html: statusHTML, openTask}}')(env);
const read = k => clicks.forEach(f => f({target: {closest: s => s === '[data-readtask]' ? {dataset: {readtask: k}} : null}}));
(async () => {
  const out = {shut: draw.html()};
  await draw.openTask('F1', 'working'); out.run = draw.html();
  read('working:F1'); out.read = draw.html();
  S.sure = 'task_cancel:F1'; out.sure = draw.html(); S.sure = null;
  await draw.openTask('s3', 'working'); out.idle = draw.html();
  await draw.openTask('F9', 'merging'); out.merge = draw.html();
  await draw.openTask('F9', 'merging'); await draw.openTask('F8', 'merging'); out.slot = draw.html();
  S.snap = {...S.snap, up: false, sessions: [], merging: [], usage: []}; out.down = draw.html();
  console.log(JSON.stringify({...out, asked}));
})();
"""


def test_view(tmp: Path) -> None:
    """The run, working, merging, usage; each agent's row opens in place to its own options, one per list."""
    page = W.page_html().decode()
    for gone in ('data-plusslot', 'plusSlot', 'relCard', 'landedText', "'Add a slot'", 'Landed lately'):
        check(gone not in page, f'no {gone}')
    if not shutil.which('node'):
        print('  (no node here: the Status view is not drawn)')
        return
    slot = lambda n, tid='', **m: {'name': n, 'task': tid, 'title': f'Title {tid}', 'state': 'running', 'minutes': 5, 'task_controls': bool(tid), **m}  # noqa: E731
    snap = {'up': True, 'run': {}, 'slots': 4, 'controls': U.controls(), 'queue': [{'id': 'B5', 'state': 'blocked', 'files': []}],
            'usage': [{'name': 'session', 'pct': 40}],
            'sessions': [slot('s1', 'F1'), slot('s2', 'F8', state='merging', task_controls=False), slot('s3'), slot('s4', 'F2'),
                         {'name': 'c1', 'task': '', 'title': 'a chat', 'state': 'live'}],
            'merging': [{'id': 'F9', 'title': 'Nine', 'step': 'Conflicts in a.py', 'link': 'https://x/9'}]}
    logic = (W.PAGE_DIR / '032-status.logic.js').read_text(encoding='utf-8')
    status = (W.PAGE_DIR / '076-status.js').read_text(encoding='utf-8')
    (tmp / 'driver.js').write_text(DRIVER.replace('LOGIC', json.dumps(logic)).replace('STATUS', json.dumps(status)), encoding='utf-8')
    (tmp / 'snap.json').write_text(json.dumps(snap), encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE), str(tmp / 'snap.json')], capture_output=True, text=True, encoding='utf-8', timeout=60)
    check(r.returncode == 0, 'node runs the page script', r.stderr[-800:])
    o = json.loads(r.stdout)
    shut = o['shut']

    def order(h: str, *xs: str) -> None:
        at = [h.find(x) for x in xs]
        check(all(i >= 0 for i in at) and at == sorted(at), ', '.join(xs), (at, h))
    order(shut, '>Run<', '[run card]', '>Working<', 'data-task="F1"', '>Idle<', 'data-task="F2"', '>Merging<', 'data-task="F9"', 'data-task="F8"', '>Usage<', '[session 40%]')
    for gone in ('Landed', 'Release', 'Run log', 'data-quick', 'Needs you', '<fold>', 'data-task="c1"', 'class="btns"', 'aria-expanded="true"'):
        check(gone not in shut, f'shut: no {gone}', shut)
    eq(shut.count('data-task="F8"'), 1, 'a slot that merges is in Merging alone')
    check(shut.count('data-list="working"') == 3 and shut.count('data-list="merging"') == 2, 'two lists', shut)
    run = o['run']
    order(run, 'data-task="F1"', 'Reading the plan', 'data-thread="s1"', '>Open session<', '>Read task<', 'data-ctl="task_cancel" data-tid="F1"', 'data-ctl="task_drop"', 'data-about="plan:F1"', 'data-task="F2"')
    eq(run.count('<fold>'), 1, 'that row alone')
    check('the whole text' not in run and 'the whole text' in o['read'] and 'data-readtask="working:F1" aria-expanded="true"' in o['read'], 'Read task opens its text')
    check('F1 has worked 5 min in s1. Cancel stops its agent' in o['sure'] and 'Yes, cancel' in o['sure'] and o['sure'].count('data-sure') == 1, 'Cancel asks in its row', o['sure'])
    idle = o['idle']
    order(idle, '>Idle<', 'Of 1 queued task, 1 is blocked.', 'Removing one takes s4, which finishes its task first.', 'data-ctl="slot_remove"', '>Remove a slot<')
    eq((idle.count('<fold>'), 'the whole text' in idle), (1, False), 'the open row shut, with its text')
    m = o['merge']
    order(m, 'data-task="F9"', 'Conflicts in a.py', 'href="https://x/9"', '>Read task<', 'data-about="plan:F9"')
    eq(m.count('<fold>'), 2, 'one open row in each list')
    last = m.split('>Merging<', 1)[1]
    check('task_cancel' not in last and 'task_drop' not in last, 'no Cancel or Drop while it merges', last)
    order(o['slot'], 'data-task="F8"', 'Its merge is built and tested, or waits its turn.', 'data-thread="s2"', 'data-about="plan:F8"')
    eq(o['slot'].split('>Merging<', 1)[1].count('<fold>'), 1, 'one open row per list')
    order(o['down'], '[No agent is working.]', '[Nothing is merging.]', '[No usage read yet.]')
    eq(o['asked'], ['task/F1', 'task/F9', 'task/F8'], 'the text of a task, not of an idle slot')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_merge_rows), test_logic, in_tmp(test_view)]))
