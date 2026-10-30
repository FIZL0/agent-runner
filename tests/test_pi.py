#!/usr/bin/env python3
"""Pi backend checks, using temporary repositories and no network or installed agent."""
from __future__ import annotations

import io
import json
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from _check import check, eq, git, has, report

from agent_runner import plat
from agent_runner import runner as R
from agent_runner.config import Config


def configure(repo: Path, text: str = 'agent = "pi"\n'):
    (repo / 'runner.toml').write_text('[run]\n' + text, encoding='utf-8')
    R.init(repo)
    R.C = Config(repo)
    return R.C


def test_config(repo: Path):
    c = configure(repo)
    eq((c.run['backend'], c.run['model'], c.run['fix_model']), ('pi', '', ''),
       'agent=pi selects Pi, not Claude models')
    c = configure(repo, 'backend = "pi"\nmodel = "github-copilot/example"\n')
    eq((c.run['agent'], c.run['fix_model']), ('pi', 'github-copilot/example'),
       'an explicit backend sets the executable and fixer model defaults')
    c = configure(repo, 'agent = "my-wrapper"\nbackend = "pi"\nfix_model = "other/model"\n')
    eq((c.run['backend'], c.run['fix_model']), ('pi', 'other/model'),
       'wrappers and distinct fixer models are supported')
    c = configure(repo, 'agent = "pi.cmd"\n')
    eq(c.run['backend'], 'pi', 'Windows npm executable names are inferred')
    c = configure(repo, '')
    eq((c.run['agent'], c.run['backend'], c.run['model'], c.run['fix_model']),
       ('claude', 'claude', 'opus', 'opus'), 'unconfigured repositories retain Claude defaults')
    flags = R.agent_flags('sid', 'opus', 90)
    check(flags[:2] == ['--session-id', 'sid'] and '--settings' in flags and '--print' not in flags,
          'Claude still uses its interactive session flags and Stop hooks')
    eq(R.agent_flags('sid', 'opus', 90, resume=True)[:2], ['--resume', 'sid'],
       'Claude resume flags remain unchanged')
    (repo / 'runner.toml').write_text('[run]\nbackend = "invalid"\n', encoding='utf-8')
    try:
        Config(repo)
    except SystemExit as e:
        has(str(e), 'unknown.*backend', 'unknown backends fail explicitly')
    else:
        check(False, 'unknown backends must fail')


def test_commands(repo: Path):
    configure(repo)
    model = 'github-copilot/example'
    flags = R.agent_flags('test-session', model, 90)
    check('--print' in flags and '--session-id' in flags and '--settings' not in flags
          and '--permission-mode' not in flags, 'Pi uses native one-shot flags, not Claude hooks')
    eq(flags[flags.index('--model') + 1], model, 'provider-qualified models are passed intact')
    eq(flags[flags.index('--tools') + 1],
       f'read,{"powershell" if plat.WINDOWS else "bash"},edit,write', 'lean tools use the platform shell')
    check('--no-extensions' in flags and '--no-mcp' in flags, 'lean Pi disables external resources')
    check('--model' not in R.agent_flags('test-session', '', 90),
          'an empty model lets Pi choose its configured model')
    big = 'quotes " $HOME %PATH% &\n' * 3000
    argv = R.agent_argv(big, 'test-session', model, 90, 'slot1')
    eq(argv[-2:], ['--', f'@{R.C.notes("slot1.prompt")}'], 'Windows prompts use Pi file attachments')
    eq(R.C.notes('slot1.prompt').read_text(encoding='utf-8'), big, 'large prompts are preserved exactly')
    check(len(subprocess.list2cmdline(argv)) < 4000, 'large prompts stay below Windows command limits')
    eq(shlex.split(R.agent_cmd(big, 'test-session', model, 90, 'slot1'))[1:], argv[1:],
       'tmux and Windows use the same Pi arguments')
    try:
        R.agent_flags('missing', model, 90, resume=True)
    except FileNotFoundError:
        check(True, 'resuming a missing Pi session fails rather than silently starting over')
    else:
        check(False, 'a missing Pi session must fail')
    R.C.run['lean'] = False
    check('--no-extensions' not in R.agent_flags('test-session', model, 90),
          'lean=false preserves normal Pi resource loading')


def write_session(sid: str, *messages: dict) -> Path:
    path = R.C.notes('pi-sessions', f'2026-10-26T00-00-00_{sid}.jsonl')
    entries = [{'type': 'session', 'id': sid, 'timestamp': '2026-10-26T00:00:00Z'}]
    entries += [{'type': 'message', 'id': str(i), 'parentId': str(i - 1) if i else None,
                 'timestamp': f'2026-10-26T00:0{i + 1}:00Z', 'message': message}
                for i, message in enumerate(messages)]
    path.write_text(''.join(json.dumps(e) + '\n' for e in entries), encoding='utf-8')
    return path


def test_sessions(repo: Path):
    configure(repo)
    user = {'role': 'user', 'content': 'do the task'}
    tool = {'role': 'assistant', 'stopReason': 'toolUse',
            'content': [{'type': 'toolCall', 'name': 'write'}]}
    result = {'role': 'toolResult', 'content': [{'type': 'text', 'text': 'written'}]}
    done = {'role': 'assistant', 'stopReason': 'stop',
            'content': [{'type': 'text', 'text': 'finished'}],
            'usage': {'input': 1000, 'cacheRead': 2000, 'cacheWrite': 1000}}
    path = write_session('finished', user, tool, result, done)
    eq(R.transcript('finished'), str(path), 'runner-owned Pi sessions are discoverable')
    eq(R.last_words('finished'), 'finished', 'Pi final text is readable')
    has(R.stats('finished'), r'4 min, 1 calls, context 4k first, 4k peak', 'Pi token usage is normalized')
    eq(R.cut_off('finished', mid_turn=True), None, 'a completed Pi session is not resumed')
    flags = R.agent_flags('finished', '', 90, resume=True)
    check('--session-id' in flags and '--resume' not in flags,
          'Pi resumes exact IDs without opening its interactive session picker')
    marker, job = R.C.notes('slot8.live'), R.C.notes('slot8.job')
    marker.write_text(str(os.getpid()), encoding='utf-8')
    job.write_text(json.dumps({'argv': R.agent_argv('test', 'finished', '', 90, 'slot8')}),
                   encoding='utf-8')
    try:
        mux = R.ShimMux('console')
        eq(mux.session_id(os.getpid()), 'finished', 'Windows restart adoption discovers Pi session IDs')
        eq(mux.panes()['s8'][1], os.getpid(), 'Windows Pi slots remain visible through the existing shim')
    finally:
        marker.unlink()
        job.unlink()
    write_session('mid', user, tool, result)
    eq(R.cut_off('mid'), None, 'unfinished turns are left alone during normal completion')
    eq(R.cut_off('mid', mid_turn=True), 'its transcript stops mid-turn', 'interrupted Pi tools resume on restart')
    error = {'role': 'assistant', 'stopReason': 'error', 'content': [],
             'errorMessage': '503 service unavailable'}
    write_session('error', user, error)
    eq(R.cut_off('error'), error['errorMessage'], 'transient Pi errors trigger resume')
    eq(R.last_words('error'), error['errorMessage'], 'Pi errors remain visible even with empty content')
    error['errorMessage'] = '401 authentication failed'
    write_session('auth', user, error)
    eq(R.cut_off('auth'), None, 'authentication errors are not retried')
    error['errorMessage'] = '403 forbidden: connection denied'
    write_session('denied', user, error)
    eq(R.cut_off('denied'), None, 'permanent errors take priority over transient-looking words')
    error['errorMessage'] = 'ETIMEDOUT'
    write_session('timeout', user, error)
    eq(R.cut_off('timeout'), 'ETIMEDOUT', 'connection timeouts can resume')
    limited = write_session('limited', user, {'role': 'assistant', 'stopReason': 'error',
                                            'errorMessage': 'limit resets 3pm'})
    eq(R.limit_only('limited', R.C.notes('slot1.log'), 0), None, 'Claude usage-reset handling is not used for Pi')
    check(limited.exists(), 'Pi transcripts are never deleted by Claude-specific cleanup')
    with patch.object(R, 'weekly', side_effect=AssertionError('must not query Claude')):
        eq(R.capped(False), None, 'Pi does not query Claude weekly usage')


def test_fixer(repo: Path):
    configure(repo, 'backend = "pi"\nmodel = "github-copilot/example"\n'
              'slot_env = ["AGENT_SLOT={n}", "NODE_USE_SYSTEM_CA=1"]\n')
    original = subprocess.run
    calls = []

    def execute(argv, **kw):
        if isinstance(argv, list) and argv[0] == 'git':
            return original(argv, **kw)
        calls.append((argv, kw))
        return subprocess.CompletedProcess(argv, 7)

    with patch.object(R, 'MASTER_PANE', True), patch.object(R.sp, 'run', side_effect=execute):
        eq(R.fix_session('resolve the merge', repo, io.StringIO()), 7,
           'Pi fix sessions return their real exit code, even with tmux enabled')
        argv, kw = calls[-1]
        check('--print' in argv and '--settings' not in argv, 'fix sessions use the Pi backend too')
        eq(kw['env']['NODE_USE_SYSTEM_CA'], '1', 'fixers inherit non-slot environment settings')
        eq(kw['env'].get('AGENT_SLOT'), os.environ.get('AGENT_SLOT'), 'fixers do not inject a slot number')
    eq(R.C.notes('master.prompt').read_text(encoding='utf-8'), 'resolve the merge', 'fixer prompts also use files')


def test_sequential_failure(repo: Path):
    configure(repo)
    R.C.run['on_exit'] = 'cleanup command'
    task = ('T1', 'test', set(), set())
    saved = Path.cwd()
    original = subprocess.run
    cleaned = []

    def execute(argv, **kw):
        if isinstance(argv, list) and argv[0] == 'git':
            return original(argv, **kw)
        if argv == 'cleanup command':
            cleaned.append(True)
        return subprocess.CompletedProcess(argv, 7)

    os.chdir(repo)
    try:
        with patch.object(R, 'pick', return_value=task), patch.object(R, 'retry_reopened'), \
                patch.object(R, 'prompt_for', return_value='test'), \
                patch.object(R, 'run_session', return_value=7), \
                patch.object(R.sp, 'run', side_effect=execute):
            eq(R.sequential('main', '', 90, 0, True, once=True), 7,
               'sequential Pi failures propagate instead of reporting success')
            check(cleaned, 'failed Pi sessions still run on_exit cleanup')
    finally:
        os.chdir(saved)


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / 'repo with spaces'
        repo.mkdir()
        git(repo, 'init', '-q', '-b', 'main')
        (repo / 'README.md').write_text('test\n', encoding='utf-8')
        git(repo, 'add', 'README.md')
        git(repo, 'commit', '-qm', 'start')
        return report([lambda: test_config(repo), lambda: test_commands(repo),
                       lambda: test_sessions(repo), lambda: test_fixer(repo),
                       lambda: test_sequential_failure(repo)])


if __name__ == '__main__':
    sys.exit(main())
