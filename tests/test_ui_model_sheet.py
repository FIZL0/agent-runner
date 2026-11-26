#!/usr/bin/env python3
"""C56: the run page model: a pick sheet's buttons.

    python3 tests/test_ui_model_sheet.py
"""
from __future__ import annotations
import datetime as dt
import json
from pathlib import Path
from unittest import mock
from _check import check, eq, report
from agent_runner import state as S  # noqa: E402
from agent_runner import ui_model as U  # noqa: E402
from _ui_model import in_tmp,TODO, NOW, fake_run, ran_by, chat, said  # noqa: E402


def test_sheet_buttons_f181b(tmp: Path) -> None:
    """F181b: a pick sheet's easy answers are its item's buttons: the recommended picks (sheet ID --go), and with one
    question each of its answers (sheet ID --picks), with the note and no session. Never from a sheet that does not
    read, or for an ask that is not the sheet's."""
    repo = fake_run(tmp)
    todo, f = repo / 'plan' / 'TODO.md', S.C.notes('sheets', 'D3.json')
    f.parent.mkdir(parents=True, exist_ok=True)
    plain = todo.read_text(encoding='utf-8')
    lay = {'id': 'lay', 'q': 'Which layout?', 'answers': ['Keep `tabs`', 'Drawer'], 'recommended': 1}
    size = {'id': 'size', 'q': 'Which size?', 'answers': ['Small', 'Big']}
    go = ('Go with the recommended picks', 'Go with the recommended picks')

    def said(*qs: dict) -> list:
        f.write_text(json.dumps({'summary': 'Pick a layout', 'groups': [{'questions': list(qs)}]}), encoding='utf-8')
        return [(a['label'], a['value']) for a in U.row_of('need', 'D3')['answers']]
    eq(said(lay, size), [go], 'more questions: the recommended picks alone')
    eq(said(lay), [go, ('Drawer (recommended)', 'Drawer'), ('Keep tabs', 'Keep tabs')], 'one question: each answer too, plain')
    check(U.need_options(U.row_of('need', 'D3')) == ['Which layout?: Keep `tabs` / Drawer (recommended)'], "the chat's text has its question")
    ran = []
    with ran_by(ran, 'D3 is open again'), mock.patch.object(U, 'SEND', [lambda t: check(False, 'no session starts', t)]):
        r = U.act('run_control', key='need_answer1', tid='D3', text=go[0])
        eq((r['ok'], r['gone'], r['said']), (True, 'D3', 'D3 answered with the recommended picks'), 'go')
        U.act('run_control', key='need_answer2', tid='D3', text='Drawer', note='dark  too')
        U.act('run_control', key='need_answer3', tid='D3', text='Keep tabs')
        n = len(ran)
        eq(U.act('run_control', key='need_answer3', tid='D3', text='Tabs')['ok'], False, 'its answers changed: refused')
        eq(len(ran), n, 'and nothing ran')
    eq(ran, [['sheet', 'D3', '--go'], ['sheet', 'D3', '--picks', 'D3 picks: lay=b', '--note=dark too'],
             ['sheet', 'D3', '--picks', 'D3 picks: lay=a']], 'what each press runs')
    for bad in (['Drawer', 'drawer'], ['A', 'b' * 81], ['A', go[0]]):
        eq(said(dict(lay, answers=bad)), [go], f'{bad[1][:30]}: answers that make no buttons of their own')
    for bad in ('x', '{}', '{"summary": "s", "groups": [{"questions": [{"id": "a"}]}]}'):
        f.write_text(bad, encoding='utf-8')
        eq(U.row_of('need', 'D3')['answers'], [], f'{bad}: no buttons')
    said(lay)
    asks = S.C.notes('uploads', 'x').parent.parent / 'asks' / 'D3.json'
    asks.parent.mkdir(parents=True, exist_ok=True)
    asks.write_text(json.dumps({'inputs': [{'key': 'a', 'label': 'A'}]}), encoding='utf-8')
    if U.need_detail.asks_file('D3')['inputs']:
        eq(said(lay), [], 'an item with inputs: Done answers it')
    else:
        check(False, 'the fixture has an input', asks.read_text())
    asks.unlink()
    with mock.patch('agent_runner.brief.questionnaires_on', lambda: False):
        eq(said(lay), [], 'questionnaires off')
    todo.write_text(plain.replace('which layout https://claude.ai/artifact/abc', 'which layout [A / B] https://claude.ai/artifact/abc'),
                    encoding='utf-8')
    eq([v for _, v in said(lay)], ['A', 'B'], "the ask's own options come first")
    todo.write_text(plain.replace('which layout https://claude.ai/artifact/abc', 'which colour'), encoding='utf-8')
    eq(said(lay), [], "a later ask with no page is not the sheet's")
    todo.write_text(plain, encoding='utf-8')
    with mock.patch.object(U, 'SEND', [lambda t: check(False, 'no session starts', t)]):
        r = U.act('run_control', key='need_answer2', tid='D3', text='Drawer')  # the real sheet --picks
    t = todo.read_text(encoding='utf-8')
    check(r['ok'] and '- [ ] **D3**' in t and 'picks on the sheet: lay (Which layout?): Drawer (recommended)' in t, 'D3 is open with the pick', (r, t))
    U.P.block('D3', 'DECIDE: which font https://claude.ai/artifact/def', todo=S.C.todo)
    eq(said(lay), [], 'a sheet answered once makes no buttons for the next ask')
    eq(said(size), [go, ('Small (recommended)', 'Small'), ('Big', 'Big')], 'a new sheet does')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_sheet_buttons_f181b)]))
