"""F212: the Plan view's search, agent_runner/plan_search.py, and its route.

    python3 tests/test_plan_search.py
"""
from __future__ import annotations

import json
import urllib.parse
from pathlib import Path
from unittest import mock

from _check import check, eq, report

from agent_runner import plan_search as PS  # noqa: E402
from agent_runner import state as S  # noqa: E402
from agent_runner import web as W  # noqa: E402
from _web import fake_repo, get, in_tmp  # noqa: E402

PLAN = """# TODO

### Next
- [ ] **B7** Mentions f21 in its title | files: a.py
- [ ] **F212** A search in the Plan view (the person, 2026-11-24: 'find it') | files: page/140-plan.js
  - a line under it names the aardvark
- [ ] **F21** Draw the board. The zebra is only said here, far from the title | files: b.py
- [~] **D3** Pick a colour — BLOCKED: shelved: DECIDE: which one?
- [~] **D4** Pick a size — BLOCKED: DECIDE: which one?
- [ ] **B8** Cost is $5 (50%) [a.b*] \\d+ <b>&amp;

### Parked
- [ ] **F83** Read the zebra aloud | files: c.py
- [x] **F90** Ticked by hand, not archived
"""
DONE = """# DONE

### Next
- [x] **F1** An old zebra
- [x] **F2** A dropped zebra — dropped: nobody wants it
- [x] **F21** The archive's copy of a task reopened since
"""


def plan(repo: Path) -> None:
    (repo / 'plan' / 'TODO.md').write_text(PLAN, encoding='utf-8')
    (repo / 'plan' / 'DONE.md').write_text(DONE, encoding='utf-8')


def ids(q: str) -> list[list[str]]:
    r = PS.search(q)
    return [[t['id'] for t in r[g]] for g in ('open', 'parked', 'done')]


def test_matching(tmp: Path) -> None:
    plan(fake_repo(tmp))
    for q in ('F21', 'f21', ' f21 '):
        eq(ids(q), [['F21', 'F212', 'B7'], [], []], f'{q!r}: the id itself, then its prefix, then the words')
    eq(ids('zebra'), [['F21'], ['F83'], ['F2', 'F1']], 'a word only in the body, a parked task, done ones from the end')
    eq(ids('ZEBRA read'), [[], ['F83'], []], 'every word, in any order and case')
    eq(ids('read zebra missing'), [[], [], []], 'and not when one is missing')
    eq(ids('aardvark')[0], ['F212'], 'a line under the task')
    eq(ids('140-plan')[0], ['F212'], 'its fields too')
    eq(ids('view f212')[0], ['F212'], 'an id among words')
    eq(ids('colour'), [[], ['D3'], []], 'a shelved task is under Parked')
    eq(ids('size'), [['D4'], [], []], 'a blocked one is open')
    eq(ids('ticked')[2], ['F90'], 'a task ticked but not archived is done')
    eq(ids('archive'), [[], [], ['F90']], "a reopened task's archived copy is not searched")
    for q in ('$5', '(50%)', '[a.b*]', '\\d+', '<b>&amp;'):
        eq(ids(q)[0], ['B8'], f'{q} stands for itself')
    for q in ('.*', 'a.c', '\\w'):
        eq(ids(q), [[], [], []], f'{q} is no pattern')
    eq(ids('   '), [[], [], []], 'nothing typed finds nothing')
    eq([t['state'] for t in PS.search('zebra')['done']], ['dropped', 'done'], 'a dropped task says so')
    S.C.todo.write_text('### Next\n- [ ] **B1** About dogs, then a zebra crossing far away. The owl\n'
                        '- [ ] **B2** An owl\n- [ ] **O1** Not it\n', encoding='utf-8')
    eq(ids('owl')[0], ['B2', 'B1'], 'titles before the rest of the text')


def test_cap(tmp: Path) -> None:
    plan(fake_repo(tmp))
    S.C.done.write_text('### Next\n' + ''.join(f'- [x] **F{i}** An otter\n' for i in range(300, 333)), encoding='utf-8')
    r = PS.search('otter')
    eq((len(r['done']), r['more'], r['done'][0]['id']), (PS.DONE_MAX, 3, 'F332'), 'done is capped, and says how many more')


def test_route(tmp: Path) -> None:
    repo = fake_repo(tmp)
    plan(repo)
    token = W.web_token()
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {})
    base = f'http://127.0.0.1:{srv.server_address[1]}'
    try:
        def ask(q: str) -> dict:
            code, body = get(f'{base}/plan-search?q={urllib.parse.quote(q)}&t={token}')
            eq(code, 200, f'{q!r} is answered')
            return json.loads(body)
        eq([t['id'] for t in ask('f21')['open']], ['F21', 'F212', 'B7'], 'the route finds')
        eq([t['id'] for t in ask('<b>&amp; (50%)')['open']], ['B8'], 'special characters arrive as typed')
        eq(get(f'{base}/plan-search?q=f21')[0], 403, 'only with the token')
        got = json.loads(get(f'{base}/task/F1?t={token}')[1])
        check(got['ok'] and 'An old zebra' in got['text'], 'the task route reads a done id', got)
        eq(((repo / 'plan' / 'TODO.md').read_text(encoding='utf-8'), (repo / 'plan' / 'DONE.md').read_text(encoding='utf-8')),
           (PLAN, DONE), 'it changes nothing')
        with mock.patch.object(PS.P, 'lines', side_effect=PermissionError('no')):
            eq(ask('f21')['ok'], False, 'an archive that cannot be read is no empty one')
        (repo / 'plan' / 'TODO.md').unlink()
        got = ask('f21')
        check(not got['ok'] and 'could not be read' in got['out'], 'a missing plan says so', got)
    finally:
        srv.stop()


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_matching), in_tmp(test_cap), in_tmp(test_route)]))
