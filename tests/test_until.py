#!/usr/bin/env python3
"""F427a: the until checks, read and run one at a time.

    python3 tests/test_until.py        (a temp repo, fake commands, a few seconds)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

from _check import check, eq, git, has, report

from agent_runner import __version__, config as CF, plat, runner as R, shared_tools as T, until as U, watch  # noqa: E402


def line(code: str) -> str:
    return ' '.join(plat.quote(w.replace('\\', '/')) for w in (sys.executable, code))


def make_repo(tmp: Path) -> Path:
    repo = tmp / 'proj'
    (repo / 'plan').mkdir(parents=True)
    git(repo, 'init', '-q', '-b', 'main')
    (repo / 'plan/TODO.md').write_text('# TODO\n', encoding='utf-8')
    (repo / 'plan/DONE.md').write_text('# DONE\n', encoding='utf-8')
    scripts = {'good': 'print("up")', 'quiet': '', 'later': 'import sys; print("still booting"); sys.exit(75)',
               'broken': 'import sys; print("out"); print("no route", file=sys.stderr); sys.exit(1)',
               'hang': 'import time; time.sleep(30)',
               'where': 'import os; print(os.path.basename(os.getcwd()), os.environ.get("AGENT_RUNNER_SLOT", "none"))'}
    toml = '[run]\ntest = "true"\nremote = false\n'
    for n, code in scripts.items():
        f = tmp / f'{n}.py'
        f.write_text(code, encoding='utf-8')
        toml += f'[run.checks.{n}]\ncmd = {json.dumps(line(str(f)))}\n'
    toml += 'label = "the folder"\n[run.tools.phone]\ncheck = "true"\nlabel = "iPhone 15"\n'
    toml += '[models.providers.mine]\nkind = "openai"\nurl = "https://example.invalid/v1"\nkey_env = "MINE_KEY"\n'
    (repo / 'runner.toml').write_text(toml, encoding='utf-8')
    (repo / '.gitignore').write_text('.runner/\n', encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'start')
    return repo


def test_read():
    print('a check is one of four kinds, and names what is here')
    for bad in ('', 'true', 'rm -rf x', 'cmd:true', 'shell:true', 'Version:1.2.3', 'check:', 'check:true', 'check:good; true',
                'check:good,later', 'tool:tablet', 'tool:memory', 'login:nobody', 'version:1.2', 'version:v1.2.3',
                'version:1.2.3 && true', 'version:latest'):
        check(U.problem(bad), f'refused: {bad!r}')
        eq(U.run(bad)[0], U.CANNOT, f'and never run: {bad!r}')
    for good in ('version:0.66.0', 'login:claude', 'login:codex', 'login:mine', 'tool:phone', 'check:good', ' check:good '):
        eq(U.problem(good), '', f'taken: {good!r}')
    has(U.problem('check:nope'), 'good, quiet', 'it says which there are')
    has(U.problem('uptime'), r'run\.checks', 'a command is sent to runner.toml')
    eq([U.label(t) for t in ('version:0.66.0', 'login:codex', 'tool:phone', 'check:where', 'check:good')],
       ['version 0.66.0', 'codex login', 'iPhone 15', 'the folder', 'good'], 'what the screens call it')


def test_version():
    print('version: the run that is up, else this process')
    eq(U.run(f'version:{__version__}')[0], U.PASSED, 'equal passes')
    eq(U.run('version:999.0.0'), (U.NOT_YET, f'the run is on {__version__}'), 'newer does not')
    keep, plat.lock = plat.lock, lambda f: None  # a run is up
    try:
        st = R.C.notes('STATE')
        for have, want, got in (('0.9.0', '0.10.0', U.NOT_YET), ('0.10.0', '0.9.9', U.PASSED), ('1.0.0', '1.0.0', U.PASSED)):
            st.write_text(json.dumps({'version': have}), encoding='utf-8')
            eq(U.run(f'version:{want}'), (got, f'the run is on {have}'), f'{have} for {want}, compared as numbers')
        for text in ('{}', 'x', '[]'):
            st.write_text(text, encoding='utf-8')
            eq(U.run('version:0.1.0')[0], U.CANNOT, f'a STATE of {text} says no version')
    finally:
        plat.lock = keep


def test_login(tmp: Path):
    print('login: read from files on this machine')
    os.environ['PI_CODING_AGENT_DIR'] = str(tmp)
    auth = tmp / 'auth.json'
    for k in ('MINE_KEY', 'GEMINI_API_KEY'):
        os.environ.pop(k, None)
    eq(U.run('login:codex')[0], U.NOT_YET, 'none stored')
    past = (time.time() - 60) * 1000
    for cred, got in (({'type': 'oauth', 'refresh': 'r', 'expires': past}, U.PASSED), ({'type': 'oauth', 'expires': past}, U.NOT_YET),
                      ({'type': 'api_key', 'key': 'k'}, U.PASSED)):
        auth.write_text(json.dumps({'openai-codex': cred}), encoding='utf-8')
        state, words = U.run('login:codex')
        eq(state, got, f'codex: {sorted(cred)}')
        check('"k"' not in words, 'never the secret')
    eq(U.run('login:mine')[0], U.NOT_YET, 'a custom provider')
    os.environ['MINE_KEY'] = 'secret-key'
    state, words = U.run('login:mine')
    eq((state, 'secret-key' in words), (U.PASSED, False), 'with its key set')
    eq(U.run('login:ollama')[0], U.PASSED, 'a local one needs none')

    home = tmp / 'claude'
    home.mkdir()
    cred = home / '.credentials.json'
    os.environ['CLAUDE_CONFIG_DIR'] = str(home)
    keep, watch.own_claude_login = watch.own_claude_login, lambda agent='claude': True
    platform = sys.platform
    try:
        sys.platform = 'linux'
        eq(U.run('login:claude')[0], U.NOT_YET, 'no Claude login')
        sys.platform = 'darwin'
        eq(U.run('login:claude')[0], U.CANNOT, 'in the Keychain: not guessed')
        for days, got in ((30, U.PASSED), (1, U.PASSED), (-1, U.NOT_YET)):
            cred.write_text(json.dumps({'claudeAiOauth': {'refreshToken': 'r', 'refreshTokenExpiresAt':
                                                          (time.time() + days * 86400) * 1000}}), encoding='utf-8')
            eq(U.run('login:claude')[0], got, f'it ends in {days} days')
        watch.own_claude_login = lambda agent='claude': False
        eq(U.run('login:claude')[0], U.PASSED, 'a key or another provider')
        keep_agent, R.C.run['agent'] = R.C.run['agent'], '/opt/wrapper'
        eq(U.run('login:claude')[0], U.CANNOT, "a wrapper's login cannot be read")
        R.C.run['agent'] = keep_agent
    finally:
        sys.platform, watch.own_claude_login = platform, keep


def test_tool():
    print('tool: free passes, busy and missing do not yet, unknown cannot run')
    keep = T.check
    try:
        for said, want in (((T.FREE, ''), (U.PASSED, 'free')), ((T.BUSY, 'F9'), (U.NOT_YET, 'held by F9')),
                           ((T.MISSING, 'unplugged'), (U.NOT_YET, 'unplugged')), ((T.UNKNOWN, 'its check failed'), (U.CANNOT, 'its check failed'))):
            T.check = lambda name, c=None, said=said: said
            eq(U.run('tool:phone'), want, said[0])
    finally:
        T.check = keep


def test_named():
    print('check: [run.checks.NAME], 0 passed, 75 not yet, else cannot run')
    os.environ['AGENT_RUNNER_SLOT'] = '1'
    try:
        eq(U.run('check:where'), (U.PASSED, 'proj none'), "in the main checkout, without a slot's markers")
    finally:
        os.environ.pop('AGENT_RUNNER_SLOT')
    eq(U.run('check:good'), (U.PASSED, 'up'), 'its first line')
    eq(U.run('check:quiet'), (U.PASSED, 'passed'), 'and words with none')
    eq(U.run('check:later'), (U.NOT_YET, 'still booting'), 'exit 75')
    eq(U.run('check:broken'), (U.CANNOT, 'its command failed (exit 1: no route)'), 'another exit')
    keep, U.CHECK_TIMEOUT = U.CHECK_TIMEOUT, 0.5
    t = time.monotonic()
    eq(U.run('check:hang'), (U.CANNOT, 'its command ran past 0.5 s'), 'a hang is cut off')
    check(time.monotonic() - t < 15, 'and not waited for')
    U.CHECK_TIMEOUT = keep
    eq(keep, 10.0, 'the limit is 10 s')


def test_config(repo: Path):
    print('config: a bad [run.checks] is named')
    for bad, why in (('x', 'table'), ({'a b': {'cmd': 'x'}}, 'a name is'), ({'x': {}}, 'needs cmd'), ({'x': 'true'}, 'needs cmd'),
                     ({'x': {'cmd': ' '}}, 'needs cmd'), ({'x': {'cmd': 'a', 'wat': 'b'}}, 'wat is not one of'),
                     ({'x': {'cmd': 'a', 'label': 3}}, 'label must be text')):
        has(CF.checks_problem(bad), why, f'refused: {bad}')
        check(CF.setting_problem('run', 'checks', bad), 'as a setting too')
    eq(CF.setting_problem('run', 'checks', {'x': {'cmd': 'a', 'label': 'b'}}), '', 'cmd and label')
    f = repo / 'runner.toml'
    f.write_text('[run]\n[run.checks.vm]\nlabel = "VM"\n', encoding='utf-8')
    try:
        CF.Config(repo)
        check(False, 'a config with no cmd is refused')
    except SystemExit as e:
        has(str(e), r'\[run\.checks\.vm\] needs cmd', 'a config with no cmd is refused')


def main() -> int:
    tmp = Path(tempfile.mkdtemp())
    repo = make_repo(tmp)
    R.init(repo)
    return report([test_read, test_version, lambda: test_login(tmp), test_tool, test_named, lambda: test_config(repo)])


if __name__ == '__main__':
    sys.exit(main())
