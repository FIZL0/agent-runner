"""The run page: a new chat while it starts reads Starting, never Loading or ended (F196).

    python3 tests/test_web_chats_start.py
"""
from __future__ import annotations

import shutil

from _check import eq, check, report
from _web import logic_js
from agent_runner import web as W


def test_born_f196():
    page = W.PAGE.read_text(encoding='utf-8')
    check('born:bornNow(n)' in page, 'feedNow passes whether the chat was just started here')
    check('S.born[j.name]=now' in page, 'the new-chat answer records when its chat was born')
    if not shutil.which('node'):
        print('  (no node here: the feedState test is skipped)')
        return
    got = logic_js([['feedState', {'born': True, 'chat': True}],
                    ['feedState', {'born': True, 'chat': True, 'info': {'live': False}}],
                    ['feedState', {'born': True, 'chat': True, 'info': {'ok': True}}],
                    ['feedState', {'chat': True}],
                    ['feedState', {'chat': True, 'info': {'live': False}}]])
    eq(got, ['starting', 'starting', 'session', 'loading', 'ended'],
       'a just-born chat reads starting until its session is up; others as before')


if __name__ == '__main__':
    raise SystemExit(report([test_born_f196]))
