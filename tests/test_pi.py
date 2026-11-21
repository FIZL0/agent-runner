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
    c = configure(repo, 'agent = "/opt/bin/pi"\nmodel = "github-copilot/example"\n')
    eq((c.run['backend'], c.run['fix_model']), ('pi', 'github-copilot/example'),
       'an agent named pi selects Pi and the fixer model defaults to its model')
    c = configure(repo, 'backend = "pi"\nmodel = "github-copilot/example"\n')
    eq((c.run['agent'], c.run['backend'], c.run['fix_model']), ('pi', 'pi', 'github-copilot/example'),
       'C14: an old [run] backend = "pi" still maps to agent = "pi"')
    check(any('[run] backend is gone' in w and 'agent = "pi"' in w for w in c.warnings),
          'and warns, saying what to write instead', c.warnings)
    c = configure(repo, 'agent = "my-wrapper"\nbackend = "pi"\nfix_model = "other/model"\n')
    eq((c.run['backend'], c.run['fix_model']), ('pi', 'other/model'),
       'an old backend = "pi" beside a wrapper still runs it on Pi, with its own fixer model')
    os.environ['AGENT_RUNNER_BACKEND'] = 'pi'
    try:
        c = configure(repo, 'agent = "my-wrapper"\nfix_model = "other/model"\n')
        eq(c.run['backend'], 'pi', 'a wrapper not named pi runs on Pi with AGENT_RUNNER_BACKEND=pi')
    finally:
        del os.environ['AGENT_RUNNER_BACKEND']
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
    os.environ['AGENT_RUNNER_BACKEND'] = 'pi'
    try:
        c = configure(repo, 'model = "sonnet"\nfix_model = "opus"\n')
        eq((c.run['agent'], c.run['backend'], c.run['model'], c.run['fix_model']), ('pi', 'pi', '', ''),
           "AGENT_RUNNER_BACKEND=pi runs a Claude repo on Pi, without Claude's models")
        c = configure(repo, 'agent = "pi"\nmodel = "x/y"\n')
        eq(c.run['model'], 'x/y', 'an override naming the configured backend keeps its model')
        os.environ['AGENT_RUNNER_BACKEND'] = 'claude'
        c = configure(repo, 'model = "sonnet"\n')
        eq(c.run['model'], 'sonnet', 'an override naming the inferred backend keeps its model')
    finally:
        del os.environ['AGENT_RUNNER_BACKEND']
    (repo / 'runner.toml').write_text('[run]\n', encoding='utf-8')
    os.environ['AGENT_RUNNER_BACKEND'] = 'invalid'
    try:
        Config(repo)
    except SystemExit as e:
        has(str(e), 'unknown AGENT_RUNNER_BACKEND', 'unknown backends fail explicitly')
    else:
        check(False, 'unknown backends must fail')
    finally:
        del os.environ['AGENT_RUNNER_BACKEND']
    for agent in ('copilot', 'C:\\\\tools\\\\copilot.exe'):
        (repo / 'runner.toml').write_text(f'[run]\nagent = "{agent}"\n', encoding='utf-8')
        try:
            Config(repo)
        except SystemExit as e:
            has(str(e), 'copilot.*is gone.*agent = "pi".*github-copilot/',
                f'agent = {agent!r} (the removed Copilot CLI backend) fails, pointing to Pi + github-copilot')
        else:
            check(False, f'agent = {agent!r} must fail')


def test_commands(repo: Path):
    configure(repo)
    model = 'github-copilot/example'
    flags = R.agent_flags('test-session', model, 90)
    check('--print' not in flags and '--session-id' in flags and '--settings' not in flags
          and '--permission-mode' not in flags, 'Pi runs interactive, without Claude hooks')
    exts = [flags[i + 1] for i, f in enumerate(flags) if f == '-e']
    check([Path(e).name for e in exts] == ['pi_hooks.ts', 'pi_idle.ts'] and all(Path(e).exists() for e in exts)
          and flags[flags.index('--runner-idle') + 1] == '90',
          'the bundled hook bridge and idle exit, given the idle seconds')
    once = R.agent_flags('test-session', model, 90, once=True)
    check('--print' in once and 'pi_idle.ts' not in ' '.join(once) and 'pi_hooks.ts' in ' '.join(once),
          'once: print mode, hooks bridged, no idle exit')
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
    with patch.object(R.plat, 'WINDOWS', False), patch.object(R.plat, 'exe', return_value='pi'):
        argv = R.Pi().argv('prompt', R.C.notes('slot1.prompt'), 'test-session', [])
    eq(argv[0], 'pi', 'Linux keeps launching Pi through its configured executable')
    with tempfile.TemporaryDirectory() as d:
        npm = Path(d)
        cli = npm / 'node_modules' / '@earendil-works' / 'pi-coding-agent' / 'dist' / 'bundle' / 'cli.js'
        node = npm / 'node.exe'
        cli.parent.mkdir(parents=True)
        cli.touch()
        node.touch()
        with patch.object(R.plat, 'WINDOWS', True), patch.object(R.plat, 'exe', return_value=str(npm / 'pi.cmd')):
            argv = R.Pi().argv('prompt', R.C.notes('slot1.prompt'), 'test-session', [])
        eq(argv[:2], [str(node), str(cli)], "Windows launches the Node CLI instead of npm's .cmd shim")


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
        mux = R.HiddenMux()
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
    eq(R.cut_off('limited'), None, 'a limit that reaches a Pi transcript is not resumed (Pi retries rate limits itself)')
    check(limited.exists(), 'and its transcript is kept')
    with patch.object(R, 'account_usage', side_effect=AssertionError('must not query Claude')):
        eq(R.capped(False), None, 'Pi does not query Claude usage')


def test_fixer(repo: Path):
    configure(repo, 'agent = "pi"\nmodel = "github-copilot/example"\n'
              'slot_env = ["NODE_USE_SYSTEM_CA=1"]\n')
    original = subprocess.run
    calls = []

    def execute(argv, **kw):
        if isinstance(argv, list) and argv[0] == 'git':
            return original(argv, **kw)
        calls.append((argv, kw))
        return subprocess.CompletedProcess(argv, 7)

    with patch.object(R, 'MASTER_PANE', True), patch.object(R.shutil, 'which', return_value='pi'), \
            patch.object(R, 'pane', return_value=2 ** 22 + 7) as pane:
        eq(R.fix_session('resolve the merge', repo, io.StringIO()), 0, 'under tmux a Pi fixer is a pane session')
        cmd = pane.call_args[0][2]
        check('pi_idle.ts' in cmd and '--print' not in cmd, 'watchable in the master window, ended by pi_idle')
    with patch.object(R, 'MASTER_PANE', False), patch.object(R.sp, 'run', side_effect=execute):
        eq(R.fix_session('resolve the merge', repo, io.StringIO()), 7,
           'Pi fix sessions without tmux return their real exit code')
        argv, kw = calls[-1]
        check('--print' in argv and '--settings' not in argv, 'fix sessions use the Pi backend too')
        eq(kw['env']['NODE_USE_SYSTEM_CA'], '1', 'fixers inherit non-slot environment settings')
        eq(kw['env'].get('AGENT_SLOT'), os.environ.get('AGENT_SLOT'), 'fixers do not inject a slot number')
    eq(R.C.notes('master.prompt').read_text(encoding='utf-8'), 'resolve the merge', 'fixer prompts also use files')


def test_backend_end_to_end(repo: Path):
    print('pi: command lines, the extensions, the session files, stats and resuming a failed call')
    configure(repo, 'agent = "pi"\nmodel = "github-copilot/m1"\nfix_model = "github-copilot/m2"\n')
    sessions = R.C.notes('pi-sessions')
    argv = R.agent_argv('do T1', 'sid-p', 'github-copilot/m1', 45, 'slotP')
    eq(argv[-2:], ['--', f'@{R.C.notes("slotP.prompt")}'], 'Pi reads its options, the prompt from a file')
    eq(R.C.notes('slotP.prompt').read_text(encoding='utf-8'), 'do T1', 'the prompt file keeps the full task')
    eq(argv[argv.index('--session-id') + 1], 'sid-p', 'the session id is ours')
    eq(Path(argv[argv.index('--session-dir') + 1]), sessions, 'in a session folder of this run')
    eq(argv[argv.index('--model') + 1], 'github-copilot/m1', 'with the model')
    exts = [Path(argv[i + 1]) for i, arg in enumerate(argv[:-1]) if arg == '-e']
    check([p.name for p in exts] == ['pi_hooks.ts', 'pi_idle.ts'] and '--runner-idle' in argv and
          argv[argv.index('--runner-idle') + 1] == '45', 'the extensions bridge hooks and stop idle sessions')
    fix = R.fix_cmd('fix it')
    check('--print' in fix and fix[fix.index('--model') + 1] == 'github-copilot/m2',
          'a fix session is print mode and uses fix_model')

    ev = lambda ts, **m: json.dumps({'type': 'message', 'timestamp': ts, 'message': m},  # noqa: E731
                                    separators=(',', ':'))
    lines = [json.dumps({'type': 'session', 'id': 'sid-p', 'timestamp': '2020-01-01T10:00:00.000Z'},
                        separators=(',', ':')),
             ev('2020-01-01T10:00:01.000Z', role='user', content='go'),
             ev('2020-01-01T10:00:05.000Z', role='assistant', stopReason='toolUse',
                usage={'input': 2, 'cacheRead': 18000, 'cacheWrite': 2000, 'output': 50}),
             ev('2020-01-01T10:00:06.000Z', role='toolResult', toolName='bash'),
             ev('2020-01-01T10:09:00.000Z', role='assistant', stopReason='stop',
                usage={'input': 2, 'cacheRead': 40000, 'cacheWrite': 1000, 'output': 80})]
    sessions.mkdir(parents=True, exist_ok=True)
    f = sessions / '2020-01-01T10-00-00-000Z_sid-p.jsonl'
    f.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    eq(R.transcript('sid-p'), str(f), 'the transcript is <timestamp>_<id>.jsonl in the session folder')
    eq(R.stats('sid-p'), '9 min, 2 calls, context 20k first, 41k peak', 'stats read the assistant usage')
    eq(R._user_entries(str(f)), 2, 'a user message and a tool result count as activity')
    eq(R.agent_failed('sid-p'), None, 'a session that ended its turn is not failed')
    with open(f, 'a', encoding='utf-8') as fh:
        fh.write(ev('2020-01-01T10:10:00.000Z', role='assistant', stopReason='error',
                    errorMessage='fetch failed', usage={}) + '\n')
    got = R.agent_failed('sid-p')
    check(got is not None and got[0] == 'fetch failed' and got[1] > R.RESUME_AFTER,
          'a failed model call is found, to be resumed', str(got))
    check(R.pi_last_error(str(f))[0] == 'fetch failed', 'and the Stop hook leaves that session alone')
    with open(f, 'a', encoding='utf-8') as fh:
        fh.write(ev('2020-01-01T10:12:00.000Z', role='user', content=R.RESUME) + '\n')
    eq(R.agent_failed('sid-p'), None, 'once resumed it is not failed any more')


def test_no_push(repo: Path):
    print('with [git] push = false, no agent session can push')
    configure(repo, 'agent = "pi"\n\n[git]\npush = false\n')
    p = R.prompt_for('SA1', 1, 1, repo, 'main')
    check('Pushing is off' in p and 'pushes task/' not in p, 'the prompt says pushing is off, not that done pushes')
    env = dict(e.split('=', 1) for e in R.slot_env(1))
    count = int(os.environ.get('GIT_CONFIG_COUNT', '0'))
    eq(env.get('GIT_CONFIG_COUNT'), str(count + len(R.NO_PUSH_URLS)), 'the session gets the no-push git config')
    with patch.dict(os.environ, {'GIT_CONFIG_COUNT': '1', 'GIT_CONFIG_KEY_0': 'safe.bareRepository',
                                 'GIT_CONFIG_VALUE_0': 'explicit'}):
        inherited = R.env_vars(R.slot_env(1))
        eq(inherited['GIT_CONFIG_KEY_0'], 'safe.bareRepository', 'existing git config keys are retained')
        eq(inherited['GIT_CONFIG_VALUE_0'], 'explicit', 'existing git config values are retained')
        eq(inherited['GIT_CONFIG_COUNT'], str(1 + len(R.NO_PUSH_URLS)), 'no-push settings are appended')
    git(repo, 'remote', 'add', 'origin', 'https://example.invalid/x.git')
    try:
        r = subprocess.run(['git', 'push', 'origin', 'main'], cwd=str(repo), capture_output=True, text=True,
                           env={**os.environ, **env})
        check(r.returncode != 0 and 'agent-runner-no-push' in r.stderr, 'a git push from the session fails before '
              'it reaches the network', r.stderr)
        r = subprocess.run(['git', '-C', str(repo), 'push', '--dry-run', 'origin', 'main'], capture_output=True,
                           text=True, env={**os.environ, **env})
        check(r.returncode != 0 and 'agent-runner-no-push' in r.stderr, 'in whatever form it is typed', r.stderr)
    finally:
        git(repo, 'remote', 'remove', 'origin')


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
                       lambda: test_backend_end_to_end(repo),
                       lambda: test_no_push(repo)])


if __name__ == '__main__':
    sys.exit(main())
