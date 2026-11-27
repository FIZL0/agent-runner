"""F444c: the Review buttons on a pitch in the run app: Ask about it and Ask for a better way (agent_runner/web_review.py
and page/095-review.logic.js)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _check import check, eq, report  # noqa: E402
from _web import W, U, logic_js  # noqa: E402,F401

from agent_runner import web_review as R  # noqa: E402


def fake(out='the answer'):
    got = []

    def call(argv):
        got.append(argv)
        return {'ok': True, 'code': 0, 'out': out, 'argv': argv}
    return got, call


def test_actions_join():
    check(U.ACTIONS.get('pitch_ask') is R.pitch_ask, 'pitch_ask is a run page action')
    check(U.ACTIONS.get('pitch_better') is R.pitch_better, 'pitch_better is a run page action')


def test_ask():
    got, call = fake('Because  it is faster.\n')
    r = R.pitch_ask('pitch1', 'F1', '  why  this way? ', call=call)
    eq(got, [['pitch', 'ask', 'pitch1', 'F1', 'why this way?']], 'pitch ask with the question')
    check(r['ok'] and r['answer'] == 'Because  it is faster.', 'the answer comes back', r)
    for args in (('nope', 'F1', 'q'), ('pitch1', 'x y', 'q'), ('pitch1', 'F1', '  ')):
        got, call = fake()
        r = R.pitch_ask(*args, call=call)
        check(not r['ok'] and not got, f'refused without a call: {args}', r)


def test_better():
    got, call = fake()
    r = R.pitch_better('pitch1', 'F1', 'use a cache', call=call)
    check(r.get('confirm') and not got, 'it asks first', r)
    r = R.pitch_better('pitch1', 'F1', 'use  a cache', confirm=True, call=call)
    eq(got, [['pitch', 'better', 'pitch1', 'F1', '--why=use a cache']], 'pitch better with what instead')
    check(r['ok'] and 'better way' in r['said'], 'said', r)
    got, call = fake()
    check(not R.pitch_better('pitch1', 'F1', '', confirm=True, call=call)['ok'] and not got, 'no words: refused')


def test_page():
    n = {'id': 'pitch1', 'changes': [{'id': 'F1', 'title': 'A <b>'}, {'id': 'F2', 'title': 'B'}]}
    a, b, c = logic_js([['reviewAskHTML', n, 3, {}, None],
                        ['reviewAskHTML', n, 3, {'pitch1:F1': {'q': 'why?', 'a': 'so <i>'}}, 'better:pitch1:F2'],
                        ['reviewField', 'pitch1', 'F1']])
    check('Ask about it' in a and 'Ask for a better way' in a and a.count('data-review="3"') == 4, 'buttons per change', a)
    check('A &lt;b&gt;' in a and 'data-sure' not in a, 'escaped, no confirm', a)
    check('so &lt;i&gt;' in b and 'why?' in b, 'the answer shows', b)
    check(b.count('data-sure') == 1 and 'Undo F2' in b, 'the better way asks first, in place', b)
    eq(c, 'review:pitch1:F1', 'field')


if __name__ == '__main__':
    sys.exit(report([test_actions_join, test_ask, test_better, test_page]))
