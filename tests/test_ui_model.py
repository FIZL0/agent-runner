#!/usr/bin/env python3
"""F65, C44: the run page model: the snapshot, the queue and the rows of a run.

    python3 tests/test_ui_model.py        (a temp repo, no agent, no network)

The fake run and the helpers are in tests/_ui_model.py.
"""
from __future__ import annotations
import datetime as dt
import json
import time
from pathlib import Path
from unittest import mock
from _check import check, eq, git, report
from agent_runner import state as S  # noqa: E402
from agent_runner import ui_model as U  # noqa: E402
from _ui_model import in_tmp,TODO, NOW, fake_run, ran_by, chat, said  # noqa: E402


QUEUE_TODO = """# TODO

## Now

### Next
- [ ] **F1** Board page for the run | files: a.py | size: simple
- [ ] **F66** Run page: lazygit layout on web | files: w.py
- [ ] **B2** Fix the merge retry | files: b.py | after: B109
- [ ] **F67** Terminal pane per slot | files: t.py | after: F66
- [ ] **B3** (follow-up, critical) The gate hangs | files: g.py
- [ ] **B4** Typo in after | files: h.py | after: Z99
- [~] **D5** Write the guide | files: d.md BLOCKED: DECIDE: which layout
- [ ] **V6** Release the next version | after: all
- [~] **R6** Check status on Windows | files: r.md BLOCKED: shelved: CONFIRM: run it on the laptop
- [ ] **V5** Release: bump the version where the project keeps it, tag and publish | files: v.py
- [ ] **F8** After the release | files: f.py | after: V5,R6

### Parked
- [ ] **F83** Big future work for a person to schedule | files: p.py
"""


def test_snapshot(tmp: Path) -> None:
    fake_run(tmp)
    snap = U.snapshot(up=True, now=NOW, log_n=5, links={'s1': 'https://claude.ai/code/session_1'},
                      terminal_base='http://127.0.0.1:8765/')
    json.dumps(snap)  # JSON-ready, all of it
    eq(snap['up'], True, 'up as given')
    eq(snap['status'][0], 'run up: 3 slots', 'status opens with the run state')
    check(any('tasks left' in l for l in snap['status']), 'status has the progress line', snap['status'])
    check(any(l.startswith('release: V6 Release the next version · waits for 2: F1 Board page for the run, B2 ') for l in snap['status']), 'status has the release line',
          snap['status'])
    eq(snap['status'][-1], 'usage: session 42%, week 85%', 'status ends with usage')

    eq(snap['slots'], 3, "the run's slot count")
    names = [s['name'] for s in snap['sessions']]
    eq(names, ['s1', 's2', 's3'], 'every slot of the 3-slot run in order, the idle s3 too')
    eq(snap['sessions'][2], {'name': 's3', 'task': '', 'title': '', 'minutes': None, 'state': 'idle',
                             'files': [], 'link': '', 'terminal': '', 'task_controls': False, 'acts': []}, 'an idle slot: no task, state idle')
    s1, s2 = snap['sessions'][0], snap['sessions'][1]
    eq((s1['task'], s1['title'], s1['minutes'], s1['state'], s1['files']),
       ('F1', 'Board page for the run', 14, 'running', ['a.py', 'tests/test_a.py']), 'slot 1 row')
    eq(s1['link'], 'https://claude.ai/code/session_1', 'session link')
    eq(s1['terminal'], 'http://127.0.0.1:8765/terminal/s1', 'terminal URL under the base')
    eq((s2['task'], s2['minutes'], s2['state'], s2['link']), ('B2', 1, 'merging', ''), 'slot 2 merging, no link')

    q = {t['id']: t for t in snap['queue']}
    eq(list(q), ['F1', 'B2', 'D3', 'F4', 'V6', 'T7', 'R8'], 'every open task, in plan order, the release at its place (F195c)')
    eq(q['B2']['after'], ['F1'], 'after')
    eq(q['B2']['files'], ['b.py'], 'files')
    check(q['F1']['kind'].startswith('feature'), 'kind from the id letter', q['F1']['kind'])
    eq((q['F1']['pri'], q['T7']['pri'], q['R8']['pri']), ('normal', 'low', 'later'), 'pri from tag and section')
    eq(q['T7']['title'], 'Tidy the gate', 'title without the level tag')
    eq((q['D3']['blocked'], q['F1']['blocked']), (True, False), 'blocked flag')

    needs = {n['id']: n for n in snap['needs']}
    eq(sorted(needs), ['D3', 'F4'], 'Needs you: the decide and the concept')
    eq((needs['D3']['label'], needs['D3']['url']), ('DECIDE', 'https://claude.ai/artifact/abc'), 'decide with link')
    check(needs['D3']['ask'], 'an ask in plain words', needs['D3'])
    item = snap['concepts'][0].pop('item', {})
    eq((item.get('label'), item.get('news'), needs['F4'].get('news')), ('CONCEPT', 'new', 'new'),
       'F197b1: the concept carries its Needs you item, New on both')
    eq(snap['concepts'], [{'id': 'F4', 'concept': 'K5', 'title': 'lazy layout',
                           'url': 'https://claude.ai/artifact/k5', 'copy': '',
                           'lead': U.concept_chat_text({'concept': 'K5', 'title': 'lazy layout',
                                                        'url': 'https://claude.ai/artifact/k5'}),
                           'acts': ['concept_chat', 'concept_drop'], 'version': '0-', 'news': 'new',
                           'news_words': ''}], 'concept with its page link, New: never opened (F197a)')
    eq(snap['log'], [f'=== 2026-11-21T10:{i:02d}:00 line {i}' for i in range(25, 30)], 'run log tail')
    rel, = snap['releases']
    eq(snap['release'], 'release: ' + rel['text'] + rel['note'], 'release line: the one row (F185)')
    eq((rel['id'], rel['state'], [w['id'] for w in rel['waits']]), ('V6', 'waits', ['F1', 'B2']), 'one open release')
    eq(q['V6']['release'], rel, 'its queue row carries it')
    with mock.patch.object(U, '_state', lambda up: {'running': {'1': 'V6'}}):
        eq(U.snapshot(up=True, now=NOW, links={}, windows={})['releases'][0]['words'], 'releasing now', 'one running')

    down = U.snapshot(up=False, now=NOW, links={})
    eq(down['status'][0], 'no run is up', 'no run: said so')
    eq([s['name'] for s in down['sessions']], [], 'no run and no chat: no rows')
    eq(down['slots'], 0, 'no run: no slots')
    off = {x['id']: x for x in down['queue']}
    eq((off['F1']['state'], off['F1'].get('tool_wait'), off['F1'].get('waits_run')), ('tool', U.RUN_WAIT, True),
       'F402c1: no run: a task that nothing else keeps waits for the run to start')
    eq((off['B2']['state'], off['R8']['state'], off['D3']['state']), ('after', 'parked', 'blocked'), 'the others say what keeps them')
    check(not any(x.get('waits_run') for x in q.values()), 'a run up: none waits for it', q)
    kept, again = U.wait_for_run([{'id': 'B7', 'state': 'critical', 'after': ['F1']}, {'id': 'B6', 'state': 'ready', 'under_way': True}])
    eq((kept['state'], kept.get('waits_run'), again.get('waits_run')), ('after', None, True),
       'a critical one another task keeps says that; one that waits to resume waits for the run')
    crit, held = U.wait_for_run([{'id': 'B9', 'state': 'critical'}, {'id': 'B8', 'state': 'held'}])
    eq((crit['tool_wait'], held), (U.RUN_WAIT + ', goes first', {'id': 'B8', 'state': 'held'}), 'a critical one goes first; a held one is held')


def test_idle_slots(tmp: Path) -> None:
    """F71: a 3-slot run on one task lists s1..s3, the idle ones with state idle; the count comes from
    STATE's `slots`, else its state line, else `[run] slots` while the run starts."""
    fake_run(tmp)
    S.C.notes('STATE').write_text(json.dumps({'state': '3 slots, paused', 'slots': 3, 'running': {'2': 'F1'},
                                              'since': {'2': NOW - 60}}), encoding='utf-8')
    snap = U.snapshot(up=True, now=NOW, links={})
    eq(snap['slots'], 3, 'slots from STATE')
    eq([(s['name'], s['task'], s['state']) for s in snap['sessions']],
       [('s1', '', 'idle'), ('s2', 'F1', 'running'), ('s3', '', 'idle')],
       'every slot listed, the idle ones with state idle')
    S.C.notes('STATE').write_text(json.dumps({'slots': 1, 'running': {'1': 'F1', '3': 'B2'}}), encoding='utf-8')
    eq([s['name'] for s in U.snapshot(up=True, now=NOW, links={})['sessions']], ['s1', 's3'],
       'a slot past the count still on its task stays listed; no idle s2 past the count')
    S.C.notes('STATE').write_text(json.dumps({'state': '2 slots', 'running': {}}), encoding='utf-8')
    eq(U.snapshot(up=True, now=NOW, links={})['slots'], 2, 'a STATE without slots: the count from its state line')
    S.C.notes('STATE').unlink()
    snap = U.snapshot(up=True, now=NOW, links={})
    eq((snap['slots'], [s['state'] for s in snap['sessions']]), (3, ['idle', 'idle', 'idle']),
       'the run starting, no STATE yet: [run] slots, all idle')


def test_version_f90(tmp: Path) -> None:
    """F90: the run writes its version into STATE and the snapshot carries it as 'version'; '' when STATE has
    none (an older run) or no run is up."""
    from agent_runner import __version__, loop
    fake_run(tmp)
    eq(U.snapshot(up=True, now=NOW, links={})['version'], '', 'a STATE with no version (an older run): empty')
    loop.write_state({})
    eq(json.loads(S.C.notes('STATE').read_text(encoding='utf-8')).get('version'), __version__,
       "write_state puts the run's version in STATE")
    eq(U.snapshot(up=True, now=NOW, links={})['version'], __version__, 'the snapshot carries it')
    S.C.notes('STATE').write_text(json.dumps({'state': '1 slot', 'running': {}, 'version': '9.9.9'}),
                                  encoding='utf-8')
    eq(U.snapshot(up=True, now=NOW, links={})['version'], '9.9.9', "the version from STATE, not this process's")
    eq(U.snapshot(up=False, now=NOW, links={})['version'], '', 'no run up: empty')


def test_control_titles(tmp: Path) -> None:
    """C26: the live control sessions, titled from the names kept in state (controlN.title), never from a
    window: every live cN, then s1..s3 from STATE."""
    import subprocess as sp
    repo = fake_run(tmp)
    S.C.notes('STATE').write_text(json.dumps({'state': '3 slots', 'running': {'2': 'F1'}, 'since': {},
                                              'merging': []}), encoding='utf-8')
    live = sp.Popen(['sleep', '60'])
    try:
        named = {1: f'{repo.name} · 1 · Install IPAs row + wider', 3: f'{repo.name} · 3',
                 4: f'{repo.name} · control 4', 6: f'{repo.name} · 6 · Pairing broken: Tailscale logout',
                 7: f'{repo.name} · R43 · site deploy', 9: ''}
        for n, name in named.items():
            S.C.notes(f'control{n}.pid').write_text(f'{live.pid}', encoding='utf-8')
            if name:
                S.C.notes(f'control{n}.title').write_text(name + '\n', encoding='utf-8')
        S.C.notes('control5.pid').write_text('999999999', encoding='utf-8')  # ended: not listed
        S.C.notes('control5.title').write_text(f'{repo.name} · 5 · gone\n', encoding='utf-8')
        eq(U.control_titles(), {1: 'Install IPAs row + wider', 3: 'control session', 4: 'control session',
                                6: 'Pairing broken: Tailscale logout', 7: 'R43 · site deploy', 9: 'control session'},
           'each live one, titled from state; the ended one left out')
        snap = U.snapshot(up=True, now=NOW, links={})
    finally:
        live.kill()
        live.wait()
    eq([(s['name'], s['state']) for s in snap['sessions']],
       [('c1', 'live'), ('c3', 'live'), ('c4', 'live'), ('c6', 'live'), ('c7', 'live'), ('c9', 'live'),
        ('s1', 'idle'), ('s2', 'running'), ('s3', 'idle')], 'each cN, then s1-s3')
    eq(snap['sessions'][0]['title'], 'Install IPAs row + wider', 'c1 titled from state')
    eq(snap['sessions_note'], '', 'no note')


def test_queue_rows(tmp: Path) -> None:
    """F74: each queue row carries after's title (the open task's title, '(landed)' for a done one, 'all:
    everything above it') and a state: running sN Nm, critical, after, ready."""
    repo = fake_run(tmp)
    (repo / 'plan' / 'TODO.md').write_text(QUEUE_TODO, encoding='utf-8')
    (repo / 'plan' / 'DONE.md').write_text('# DONE\n\n- [x] **B109** Take back a task\n', encoding='utf-8')
    S.C.notes('STATE').write_text(json.dumps({'state': '2 slots', 'running': {'2': 'F1'},
                                              'since': {'2': NOW - 6 * 60}}), encoding='utf-8')
    q = {t['id']: t for t in U.snapshot(up=True, now=NOW, links={})['queue']}
    eq({t: q[t]['after_title'] for t in q},
       {'F1': '', 'F66': '', 'B2': 'B109 (landed)', 'F67': 'F66 Run page', 'B3': '',
        'B4': 'Z99 (not in the plan)', 'D5': '', 'V6': 'all: everything above it', 'V5': '',
        'F8': 'V5 Release, R6 Check status on Windows', 'F83': ''},
       "after's title: open (id and short title only, B115), landed (in DONE.md), not in the plan, all")
    check('R6' not in q, 'B115: a shelved task is not in the queue the page gets')
    eq({t: q[t]['state'] for t in q},
       {'F1': 'running s2 6m', 'F66': 'ready', 'B2': 'ready', 'F67': 'after', 'B3': 'critical', 'B4': 'ready',
        'D5': 'blocked', 'V6': 'after', 'V5': 'ready', 'F8': 'after', 'F83': 'parked'},
       'state: running sN Nm, ready, after (an open task ahead), critical, blocked ([~]), parked (B118)')
    eq(q['F83']['pri'], 'later', 'B118: a task under Parked is level later')
    eq((q['F1'].get('size'), q['F66'].get('size')), ('simple', None), 'F485: a sized task carries its size; others none')
    check(all(q[t]['state'].split()[0] in U.QUEUE_STATES for t in q), 'every state is one of QUEUE_STATES')


def test_status_f124(tmp: Path) -> None:
    """F124: the snapshot holds what the Status view shows: the state pill's words, usage, what landed lately, and
    what the Fix up controls would work on."""
    fake_run(tmp)
    for st, want in (({}, 'Running'), ({'paused': True}, 'Paused'), ({'forced': True}, 'Caps forced'),
                     ({'stopping': True, 'paused': True}, 'Stopping')):
        eq(U.run_state(True, st), want, f'{st}: {want}')
    eq(U.run_state(False, {'paused': True}), 'Not up', 'no run: Not up')
    S.C.notes('events.jsonl').write_text(json.dumps({'time': '2026-11-21T10:00:00', 'kind': 'landed', 'id': 'F1'}) + '\n',
                                         encoding='utf-8')
    snap = U.snapshot(up=True, now=NOW, links={})
    json.dumps(snap)
    eq((snap['run']['state'], snap['run']['forced']), ('Running', False), 'the run state in the snapshot')
    eq(snap['usage'], [{'name': 'session', 'pct': 42}, {'name': 'week', 'pct': 85}], 'usage, each with its percent')
    check(any('F1' in x['text'] and x['at'].startswith('2026-11-21T10:00') for x in snap['lately']), 'what landed lately',
          snap['lately'])
    eq(snap['fixups'], {'resume': [], 'unclaim': [], 'wip': []}, 'nothing to fix')
    git(S.ROOT, 'branch', 'wip/main-checkout-2026-11-20-101010')
    git(S.ROOT, 'branch', 'wip/T7')
    U.FIXUPS[0] = float('-inf')
    from agent_runner import slots, watch
    with mock.patch.object(watch, 'last_session', lambda tid: (1, 'sid')), \
            mock.patch.object(slots, 'transcript', lambda sid: '/x.jsonl'):
        fix = U.snapshot(up=True, now=NOW, links={})['fixups']
    eq([x['id'] for x in fix['wip']], ['main-checkout-2026-11-20-101010'], 'the edits a merge moved aside')
    eq([x['id'] for x in fix['resume']], ['T7'], 'a cut-off task with its work kept, running nowhere')
    ran = []
    two = {'resume': [], 'unclaim': [{'id': 'F1', 'label': ''}, {'id': 'B2', 'label': ''}], 'wip': []}
    with ran_by(ran), mock.patch.object(U, 'fixups', lambda st, ls: two):
        eq(U.run_control('unclaim')['ok'], True, 'release stale claims')
    eq(ran, [['plan', 'unclaim', 'F1'], ['plan', 'unclaim', 'B2']], 'every stale claim is released')
    by = {c['key']: c for c in U.controls()}
    for key in ('stop_now', 'suspend', 'shutdown', 'upgrade'):
        check(by[key]['confirm'] and by[key]['group'], f'{key} asks first, from the sheet', by[key])
    eq([by[k]['group'] for k in ('slot_add', 'pause', 'stop', 'force', 'upgrade', 'resume', 'wip_drop')],
       ['', '', '', 'Run', 'Run', 'Fix up', 'Fix up'], "the sheet's groups; the everyday ones are on the card")


def test_chat_rows_f128(tmp: Path) -> None:
    """F128, F129: each chat's row says who spoke last and when, whether an open question waits for the person, and the
    name the person gave it."""
    fake_run(tmp)
    from agent_runner import control as K, slots
    at = '2026-11-21T10:00:00.000Z'
    paths = {'s2': chat(2, 's2', [said('user', 'hi', at), said('assistant', 'Which one do you want?', at)]),
             's3': chat(3, 's3', [said('user', 'hi', at), said('assistant', 'Done.', '2026-11-21T10:05:00.000Z')]),
             's4': chat(4, 's4', [said('assistant', 'Hm?', at), said('user', 'go', at)]),
             's5': chat(5, 's5', [said('assistant', 'Done.', at), {'type': 'custom-title', 'customTitle': 'Mine'}])}
    ents = lambda sid, skip_bad=False: [json.loads(l) for l in open(paths[sid], encoding='utf-8')]  # noqa: E731
    with mock.patch.object(slots, 'transcript', lambda sid: paths.get(sid)), mock.patch.object(slots, 'entries', ents), \
            mock.patch.object(K, 'control_live', lambda n: n in (2, 3, 4, 5)):
        rows = {r['name']: r for r in U.control_rows({2: 'two', 3: 'three', 4: 'four', 5: 'five'})}
        eq([(rows[n]['last'], rows[n]['needs_reply']) for n in ('c2', 'c3', 'c4')],
           [('claude', True), ('claude', False), ('person', False)], 'who spoke last; an open question needs a reply')
        eq(rows['c3']['at'] - rows['c2']['at'], 300, 'the last activity, in seconds')
        eq((rows['c5']['title'], rows['c5']['renamed'], rows['c3']['title']), ('Mine', True, 'three'),
           "a chat the person renamed shows their name; another keeps the runner's")
        S.C.notes('control3.name').write_text(json.dumps({'name': 'Login', 'was': ''}), encoding='utf-8')
        r3 = {r['name']: r for r in U.control_rows({3: 'three'})}['c3']
        eq((r3['title'], r3['renamed']), ('Login', True), 'a rename shows before its turn has typed it')
    eq(U.chat_quiet(), 6 * 3600, 'chat_quiet: 6 hours')
    with mock.patch.dict(S.C.raw['ui'], {'chat_quiet': False}):
        eq(U.chat_quiet(), 0, 'false turns it off')
    ran = []
    with ran_by(ran):
        eq(U.act('rename_chat', chat='c3', title='  Login  woes ')['ok'], True, 'rename_chat')
        eq(U.act('rename_chat', chat='s1', title='x')['ok'], False, 'a slot is not a chat')
        eq(U.act('rename_chat', chat='c3', title='  ')['ok'], False, 'a name, please')
    eq(ran, [['control', '--rename', '3', 'Login woes']], 'control --rename N NAME')


def test_plan_facts_f150(tmp: Path) -> None:
    """F150: what All projects says of any project's plan: titles, the next tasks, what landed today."""
    import datetime as dt
    from agent_runner.config import Config
    repo = fake_run(tmp)
    c = Config(repo)
    (repo / 'plan' / 'TODO.md').write_text('# TODO\n### Next\n- [ ] **F1** First\n- [~] **B2** Stuck\n- [x] **F3** Done\n'
                                           '### Parked\n- [ ] **F9** Later\n', encoding='utf-8')
    (repo / 'plan' / 'DONE.md').write_text('# DONE\n- [x] **F4** Old\n', encoding='utf-8')
    log = c.notes('events.jsonl')
    ev = lambda at, kind, tid: json.dumps({'time': at, 'kind': kind, 'id': tid, 'text': ''}) + '\n'
    log.write_text(ev('2026-11-23T10:00:00', 'landed', 'F0') + ev('2026-11-24T09:00:00', 'landed', 'F4') + 'half a li\n'
                   + ev('2026-11-24T09:30:00', 'started', 'F1') + ev('2026-11-24T10:00:00', 'landed', 'F3'), encoding='utf-8')
    day = dt.datetime(2026, 11, 24, 12)
    f = U.plan_facts(c, day)
    eq(f['titles'], {'F1': 'First', 'B2': 'Stuck', 'F9': 'Later'}, 'the open tasks by title')
    eq(f['queue'], [{'id': 'F1', 'title': 'First'}], 'the next ones: not stuck, not parked')
    eq(f['landed'], ['Done', 'Old'], 'what landed today, newest first')
    check(U.plan_facts(c, day) is f, 'kept while no file changes')
    log.write_text(log.read_text(encoding='utf-8') + ev('2026-11-24T11:00:00', 'landed', 'F1'), encoding='utf-8')
    eq(U.plan_facts(c, day)['landed'], ['First', 'Done', 'Old'], 'and read again when one does')
    eq(U.plan_facts(c, day + dt.timedelta(days=1))['landed'], [], 'nothing yet the next day')


def test_pin_list_f133(tmp: Path) -> None:
    """F133, F201: the run app's pinned chats (web.pin_list), in their order; a chat that is gone drops out."""
    from agent_runner import web as W
    names = ['c1', 'c3', 'c4', 'c6']
    eq(W.pin_list(names, {}), [], 'nothing saved')
    eq(W.pin_list(names, None), [], 'no file')
    eq(W.pin_list(names, {'pins': ['c4', 'c1']}), ['c4', 'c1'], 'the pins in their own order')
    eq(W.pin_list(names, {'order': ['c6', 'c3', 'c1', 'c4'], 'pins': ['c4', 'c1', 'c6']}), ['c6', 'c1', 'c4'],
       'a file from before F201: in its order')
    eq(W.pin_list(['c1', 'c3'], {'pins': ['c9', 'c1']}), ['c1'], 'a gone chat drops out')
    eq(W.pin_list(names, {'order': 'junk', 'pins': [3, 'c3', 'c3']}), ['c3'], 'junk in the file is skipped')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_plan_facts_f150), in_tmp(test_snapshot), in_tmp(test_idle_slots), in_tmp(test_version_f90), in_tmp(test_control_titles), in_tmp(test_queue_rows), in_tmp(test_pin_list_f133), in_tmp(test_status_f124), in_tmp(test_chat_rows_f128)]))
