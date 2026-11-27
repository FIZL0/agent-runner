#!/usr/bin/env python3
"""F503: usage caps per login: capped.json keyed by login, a capped login going on with the same provider's next
login, then [models] fallback (a local model last), session_max / weekly_max per login, and the wait for the
earliest reset when everything is capped."""
from __future__ import annotations

import atexit
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _check import eq, check, report  # noqa: E402

from agent_runner import fallback as FB, state  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix='ar-fallback-'))
atexit.register(shutil.rmtree, TMP, True)
LOGINS = TMP / 'claude-logins.json'
OLLAMA = 'ollama:qwen'


def setup(logins: list[str], chain: list[str]) -> None:
    notes = TMP / 'notes'
    notes.mkdir(exist_ok=True)
    for f in notes.iterdir():
        f.unlink()
    rows = [{'name': n, 'dir': '' if i == 0 else str(TMP / n)} for i, n in enumerate(logins)]
    LOGINS.write_text(json.dumps({'logins': rows}), encoding='utf-8')
    state.C = SimpleNamespace(notes=lambda name: notes / name, fallback=chain, command='run',
                              providers={'ollama': {'baseUrl': 'http://localhost:11434/v1'}, 'openai': {}},
                              models={'code': 'opus'})


def patched(fn):
    def run():
        with mock.patch.dict(os.environ, {'AGENT_RUNNER_LOGINS': str(LOGINS)}), \
                mock.patch('agent_runner.login.missing', lambda m, c: ''), \
                mock.patch('agent_runner.claude_use.lacking', lambda m, c: False), \
                mock.patch('agent_runner.fallback.harness_model', lambda m, p: ':' in m):
            fn()
    run.__name__ = fn.__name__
    return run


@patched
def test_keys():
    setup(['work', 'home'], [])
    eq(FB.cap_key('claude', 'work'), 'claude', 'the default login keeps the plain provider key')
    eq(FB.cap_key('claude', 'home'), 'claude@home', 'another login is keyed by its name')
    FB.mark_capped('claude')
    eq(sorted(FB.capped_now()), ['claude'], 'capped.json holds the capped login')
    check(not FB.is_capped('claude'), 'claude is not capped while one login is free')
    eq(FB.free_login('claude'), 'home', 'the next login is free')
    FB.mark_capped('claude@home')
    check(FB.is_capped('claude'), 'claude is capped once every login is')


@patched
def test_same_provider_first():
    setup(['work', 'home'], ['opus', OLLAMA])
    sid = 's1'
    FB.note_model(sid, 'opus')
    FB.note_login(sid, 'work')
    got = FB.after_cap('T1', sid, 'usage limit reached')
    eq(got[:2], ('opus', 'home'), 'a capped login goes on with the same model on the next login')
    eq(state.C.notes('T1.login').read_text(), 'home', 'the next session is pinned to that login')
    env = FB.session_env('T1', 's2', 'opus')
    eq(env, [f'CLAUDE_CONFIG_DIR={TMP / "home"}'], 'the task carries on in its worktree on the next login')
    eq(FB.session_login('s2'), 'home', 'the new session notes its login')


@patched
def test_then_chain_local_last():
    setup(['work', 'home'], ['opus', 'openai:gpt', OLLAMA])
    FB.mark_capped('claude')
    FB.mark_capped('claude@home')
    FB.note_model('s1', 'opus')
    FB.note_login('s1', 'home')
    eq(FB.after_cap('T1', 's1', 'usage limit')[:2], ('openai:gpt', None), 'all logins capped: the next provider')
    FB.mark_capped('openai')
    eq(FB.chain_next('opus'), OLLAMA, 'the local model stays usable, last in the chain')
    eq(FB.start_model('opus'), OLLAMA, 'a new task starts on the local model')
    eq(FB.session_env('T2', 's3', OLLAMA), [], 'a local model gets no Claude login')


@patched
def test_new_task_free_login():
    setup(['work', 'home'], [])
    eq(FB.start_model('opus', FB.USAGE_HELD), 'opus', 'past session_max on the default login: still claude')
    eq(FB.free_model('opus', FB.USAGE_HELD), 'opus', 'it has a free login to start on')
    eq(FB.session_env('T1', 's1', 'opus', FB.USAGE_HELD), [f'CLAUDE_CONFIG_DIR={TMP / "home"}'],
       'session_max applies per login: it starts on the other one')
    setup(['work'], [])
    eq(FB.free_model('opus', FB.USAGE_HELD), None, 'one login past session_max: nothing free, it waits')


@patched
def test_all_capped_waits():
    setup(['work', 'home'], ['opus'])
    soon = time.time() + 600
    FB.mark_capped('claude', time.time() + 3000)
    FB.mark_capped('claude@home', soon)
    FB.note_model('s1', 'opus')
    with mock.patch('agent_runner.fallback.log', lambda *a, **k: None):
        eq(FB.after_cap('T1', 's1', 'usage limit'), None, 'all capped and no local model: no next')
    eq(FB.earliest_reset(), FB.capped_now()['claude@home'], 'it waits for the earliest reset')
    check(abs(FB.earliest_reset() - soon) < 1, 'the earliest reset is the first one to lift')


@patched
def test_one_login_unchanged():
    setup(['default'], [])
    check(not FB.multi(), 'one login: no switching, as before')
    eq(FB.session_env('T1', 's1', 'opus'), [], 'the default login gets no CLAUDE_CONFIG_DIR')


@patched
def test_other_login_usage():
    setup(['work', 'home', 'spare'], [])
    state.C.run = {'session_max': 80, 'weekly_max': 90}
    use = {str(TMP / 'home'): {'five_hour': {'utilization': 85}}, str(TMP / 'spare'): {'seven_day': {'utilization': 10}}}
    with mock.patch('agent_runner.watch.login_usage', lambda d: use.get(d)):
        eq(FB.usage_held_logins(), frozenset({'claude@home'}), 'a login past session_max by its own usage is held')
        eq(FB.session_env('T1', 's1', 'opus', FB.USAGE_HELD), [f'CLAUDE_CONFIG_DIR={TMP / "spare"}'],
           'default and home past their caps: it starts on the spare login')
        use[str(TMP / 'spare')] = {'seven_day': {'utilization': 95}}
        eq(FB.free_model('opus', FB.USAGE_HELD), None, 'every login past its caps: nothing free, it waits')
        state.FORCED[0] = True
        try:
            eq(FB.usage_held_logins(), frozenset(), 'forced: the caps hold no login')
        finally:
            state.FORCED[0] = False


@patched
def test_login_usage_kept():
    from agent_runner import watch as W
    cfg = TMP / 'other'
    cfg.mkdir(exist_ok=True)
    (cfg / '.claude.json').write_text(json.dumps({'oauthAccount': {'accountUuid': 'u-other'}}), encoding='utf-8')
    with mock.patch.dict(os.environ, {'XDG_STATE_HOME': str(TMP / 'xdg')}):
        with mock.patch('agent_runner.watch._fetch_login_usage', lambda d: {'five_hour': {'utilization': 50}}):
            eq(W.login_usage(str(cfg))['five_hour']['utilization'], 50, 'a login is read from its own config dir')
        W._login_usage.clear()
        (TMP / 'xdg' / 'agent-runner' / f'usage-fetch-{W.config_login(str(cfg))}.json').unlink()

        def fail(d):
            raise OSError
        with mock.patch('agent_runner.watch._fetch_login_usage', fail):
            eq(W.login_usage(str(cfg))['five_hour']['utilization'], 50, 'a failed fetch keeps the last good reading')
    check(W.login_usage(str(TMP / 'none')) is None, 'a dir with no login reads nothing')


@patched
def test_pinned_login():
    from agent_runner import config as CF
    eq(CF.claude_model('claude@home:opus'), 'claude@home:opus', 'a pinned login stays in the settled model')
    eq(CF.claude_model('claude:opus'), 'opus', 'claude with no pin is the bare name')
    eq(CF.pinned_login('claude@home:opus'), ('opus', 'home'), 'the pin splits into model and login')
    eq(CF.pinned_login('opus'), ('opus', None), 'no pin: no login')
    for bad in ('openai@x:gpt', 'claude@:opus', 'claude@a b:opus'):
        try:
            CF.parse_model(bad, {'openai': {}})
            check(False, f'{bad} is refused')
        except SystemExit:
            pass
    setup(['work', 'home', 'spare'], [])
    with mock.patch('agent_runner.fallback.harness_model', CF.harness_model):
        eq(FB.provider('claude@home:opus'), 'claude', 'a pinned model runs on claude')
        eq(FB.session_env('T1', 's1', 'claude@home:opus'), [f'CLAUDE_CONFIG_DIR={TMP / "home"}'],
           'the session starts on its pinned login')
        FB.mark_capped('claude@home')
        eq(FB.start_model('claude@home:opus'), 'claude@home:opus', 'a capped pin keeps its model')
        eq(FB.session_env('T2', 's2', 'claude@home:opus'), [],
           'a capped pinned login falls back to its provider\'s first free login')
        FB.mark_capped('claude')
        eq(FB.session_env('T3', 's3', 'claude@home:opus'), [f'CLAUDE_CONFIG_DIR={TMP / "spare"}'],
           'then the next free one')


if __name__ == '__main__':
    sys.exit(report([test_keys, test_same_provider_first, test_then_chain_local_last, test_new_task_free_login,
                     test_all_capped_waits, test_one_login_unchanged, test_other_login_usage, test_login_usage_kept,
                     test_pinned_login]))
