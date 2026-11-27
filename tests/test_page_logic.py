"""F478: a task control (hold, to the top, remove, put back) shows its result at once: the row is marked saving while its
action is in the outbox, and goes back when it is refused (agent_runner/page/090-live.logic.js, 072-plan-menu.js).

    python3 tests/test_page_logic.py        (needs node)
"""
from __future__ import annotations

import shutil

from _check import check, eq, report

from agent_runner import web as W
from _web import logic_js

DID = [{'id': 'F1', 'cid': 'a'}, {'id': 'F2', 'cid': 'b'}, {'id': 'F3', 'cid': 'c'}, {'id': 'F4', 'cid': 'd'}]


def test_held_state():
    if not shutil.which('node'):
        print('  (node missing: skipped)')
        return
    box = [{'cid': 'a', 'state': 'sending'}, {'cid': 'b', 'state': 'failed', 'err': 'no such task'},
           {'cid': 'c', 'state': 'sending', 'heldAt': 1}]
    r = logic_js([['rowPress', DID, box], ['rowPress', DID, []], ['rowPress', [], box],
                  ['rowShows', 'menu_hold:F1'], ['rowShows', 'menu_restore:F1'], ['rowShows', 'pause:'],
                  ['rowShows', 'slot_add:']])
    eq(r[0], {'saving': ['F1', 'F3'], 'failed': ['F2']}, 'sending rows are saving; a refused one is failed, not saving')
    eq(r[1], {'saving': [], 'failed': []}, 'settled (gone from the outbox): neither')
    eq(r[2], {'saving': [], 'failed': []}, 'nothing pressed: nothing marked')
    eq(r[3:], [True, True, False, False], 'a task control\'s row shows its result, a run control\'s button has its own rule')
    # per control: hold, to the top, remove, put back (the row menu's), a move by the grip, Wait for…
    for k in ['menu_hold', 'menu_unhold', 'menu_top', 'menu_remove', 'menu_restore', 'grip', 'waitset']:
        menu = k.startswith('menu_')
        d = [{'id': 'F9', 'cid': 'x', 'k': k}] if menu else []
        sending = [{'cid': 'x', 'state': 'sending', **({} if menu else {k: 'F9'})}]
        failed = [{'cid': 'x', 'state': 'failed', 'err': 'no', **({} if menu else {k: 'F9'})}]
        s, f = logic_js([['rowPress', d, sending], ['rowPress', d, failed]])
        eq(s['saving'], ['F9'], f'{k}: the row is saving while it is sent')
        check('F9' not in f['saving'], f'{k}: a refused one is no longer saving')
        if menu:
            eq(f['failed'], ['F9'], f'{k}: and is failed, so the row goes back')


def test_page():
    page = W.PAGE.read_text(encoding='utf-8')
    for pat, what in [('rowPress(PM.did,S.ob)', 'the row menu reads where each press stands'),
                      ('qmenu${q.saving?', 'the dots are marked while saving'), ('.qmenu.saving', 'and the mark is styled'),
                      ("if(x&&x.state==='failed')return false", 'a refused press is dropped, so the row is drawn as the snapshot says'),
                      ('rowShows(ck)||', 'no success toast for a task control: the row shows it')]:
        check(pat in page, what)


if __name__ == '__main__':
    raise SystemExit(report([test_held_state, test_page]))
