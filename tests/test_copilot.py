#!/usr/bin/env python3
"""`[run] agent = "copilot"`: the command lines, the Stop hook file, folder trust and the transcript reader.

    python3 tests/test_copilot.py        (no network, no real agent; runs on Windows too)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from _check import RUN, check, eq, git, report

from agent_runner import runner as R  # noqa: E402


def make_repo(tmp: Path) -> Path:
    repo = tmp / 'proj'
    repo.mkdir()
    git(repo, 'init', '-q', '-b', 'main')
    (repo / 'runner.toml').write_text('[run]\nagent = "copilot"\nmodel = "m1"\nfix_model = "m2"\n\n[git]\npush = false\n',
                                      encoding='utf-8')
    (repo / '.gitignore').write_text('.runner/\n', encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'start')
    return repo


def test_commands(repo: Path):
    print('copilot: the session and fix-session command lines')
    R.init(repo)
    check(R.copilot(), '[run] agent = "copilot" is recognised')
    argv = R.agent_argv('do T1', 'sid-1', 'm1', 90, 'slotC')
    eq(argv[1:3], ['-i', 'do T1'], 'the prompt goes in with -i (interactive, so the Stop hook can end it)')
    eq(argv[3:5], ['--session-id', 'sid-1'], 'and the session id is ours, so adopt and the transcript find it')
    for flag in ('--allow-all', '--no-ask-user', '--no-auto-update'):
        check(flag in argv, f'{flag}: nobody is there to answer')
    eq(argv[argv.index('--model') + 1], 'm1', 'the model is passed on')
    check('--settings' not in argv and '--permission-mode' not in argv, 'no Claude Code flags')
    fix = R.fix_cmd('fix it')
    eq(fix[1:3], ['-p', 'fix it'], 'a fix session is prompt mode')
    eq(fix[fix.index('--model') + 1], 'm2', 'with [run] fix_model')
    R.C.run['agent'] = 'claude'
    try:
        eq(R.agent_argv('p', 'sid-2', 'opus', 90, 'slotC')[1:4], ['p', '--session-id', 'sid-2'],
           'Claude Code keeps its own command line')
    finally:
        R.C.run['agent'] = 'copilot'


def test_hooks(repo: Path):
    print('copilot: the Stop hook goes in the checkout\'s settings.local.json')
    f = repo / '.github/copilot/settings.local.json'
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text('{"keep": 1, "hooks": {"preToolUse": []}}', encoding='utf-8')
    R.copilot_hooks(repo, 45)
    conf = json.loads(f.read_text(encoding='utf-8'))
    eq(conf['keep'], 1, 'other settings are kept')
    check('preToolUse' in conf['hooks'], 'and other hooks')
    stop = conf['hooks']['Stop'][0]
    eq(stop['exec'], sys.executable, 'the hook runs this interpreter directly, no shell')
    eq(stop['args'][-4:], ['run', '--stop-hook', '--idle', '45'], 'in --stop-hook mode with the idle time')
    r = subprocess.run([sys.executable, str(RUN), 'run', '--stop-hook'], input='{"transcript_path": "x"}',
                       capture_output=True, text=True,
                       env={k: v for k, v in os.environ.items() if k != 'AGENT_RUNNER'})
    eq(r.returncode, 0, 'outside a runner session (no AGENT_RUNNER) the hook does nothing')


def test_no_push(repo: Path):
    print('copilot: with [git] push = false, no agent session can push')
    R.init(repo)
    argv = R.agent_argv('p', 'sid-3', 'm1', 90, 'slotC')
    eq(argv[argv.index('--deny-tool') + 1], 'shell(git push)', 'Copilot refuses git push in a session')
    fix = R.fix_cmd('fix it')
    eq(fix[fix.index('--deny-tool') + 1], 'shell(git push)', 'and in a fix session')
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
    r = subprocess.run(['git', 'push', 'origin', 'main'], cwd=str(repo), capture_output=True, text=True,
                       env={**os.environ, **env})
    check(r.returncode != 0 and 'agent-runner-no-push' in r.stderr, 'a git push from the session fails before it '
          'reaches the network', r.stderr)
    r = subprocess.run(['git', '-C', str(repo), 'push', '--dry-run', 'origin', 'main'], capture_output=True,
                       text=True, env={**os.environ, **env})
    check(r.returncode != 0 and 'agent-runner-no-push' in r.stderr, 'in whatever form it is typed', r.stderr)
    git(repo, 'remote', 'remove', 'origin')


def test_utf8_merge(tmp: Path):
    print('windows: a TODO.md conflict with non-ASCII text joins (git output is UTF-8, not the ANSI code page)')
    d = tmp / 'utf8'
    d.mkdir()
    git(d, 'init', '-q', '-b', 'main')
    (d / 'plan').mkdir()
    (d / 'runner.toml').write_text('', encoding='utf-8')
    head = '# TODO — “open” tasks\n\n### Later\n\n'
    (d / 'plan/TODO.md').write_text(head + '- [ ] **A1** one → a.py\n', encoding='utf-8')
    (d / 'plan/DONE.md').write_text('# DONE — the archive\n', encoding='utf-8')
    git(d, 'add', '-A'), git(d, 'commit', '-qm', 'base')
    git(d, 'checkout', '-qb', 'task/A2')
    (d / 'plan/TODO.md').write_text(head + '- [ ] **A1** one → a.py\n- [ ] **A2** two · b.py\n', encoding='utf-8')
    git(d, 'commit', '-qam', 'A2')
    git(d, 'checkout', '-q', 'main')
    (d / 'plan/TODO.md').write_text(head + '- [ ] **A1** one → a.py\n- [ ] **A3** three … c.py\n', encoding='utf-8')
    git(d, 'commit', '-qam', 'A3')
    R.init(d)
    base = git(d, 'rev-parse', 'HEAD')
    eq(R.merge_into(d, 'task/A2', 'm'), [], 'the task-list merge driver joins both added lines')
    text = (d / 'plan/TODO.md').read_text(encoding='utf-8')
    check('“open”' in text and '**A2** two ·' in text and '**A3** three …' in text,
          'with both lines and non-ASCII text unchanged', text)
    git(d, 'reset', '--hard', base)

    print('windows: a task id both sides gave away is renumbered, non-ASCII text intact')
    git(d, 'checkout', '-qb', 'task/A4', 'main~1')
    (d / 'plan/TODO.md').write_text(head + '- [ ] **A1** one → a.py\n- [ ] **A3** other “thing” → d.py\n',
                                    encoding='utf-8')
    git(d, 'commit', '-qam', 'A4 files A3')
    git(d, 'checkout', '-q', 'main')
    ref = R.renumber_doubles('task/A4', 'main', 'A4', d)
    check(ref != 'task/A4', 'the branch gets a renumbering commit')
    shown = R.git('show', f'{ref}:plan/TODO.md', cwd=d).stdout
    check('**A4** other “thing” → d.py' in shown or '**A5** other “thing” → d.py' in shown,
          'its A3 has a new id and its text is unchanged', shown)


def test_shim_once(repo: Path, tmp: Path):
    print('windows: a slot tab runs its job once and exits 0, so it closes and Enter cannot restart it')
    R.init(repo)
    marker, job, count = R.C.notes('slot8.live'), R.C.notes('slot8.job'), tmp / 'count'
    argv = [sys.executable, '-c', 'import sys; open(sys.argv[1], "a").write("x"); sys.exit(1)', str(count)]
    job.write_text(json.dumps({'argv': argv, 'cwd': str(repo), 'env': {}, 'marker': str(marker)}), encoding='utf-8')
    eq(R.slot_shim(str(job)), 0, 'exit 0 even when the agent was killed (taskkill leaves exit code 1)')
    eq(R.slot_shim(str(job)), 0, 'a restarted tab exits at once')
    eq(count.read_text(), 'x', 'and the session ran only once')
    eq(marker.with_suffix('.exit').read_text(), 'exit code 1', 'how the agent ended is left for the runner')
    job.write_text(json.dumps({'argv': [str(tmp / 'no-such-agent.exe')], 'cwd': str(repo), 'env': {},
                               'marker': str(marker)}), encoding='utf-8')
    eq(R.slot_shim(str(job)), 0, 'an agent that cannot start still ends the tab cleanly')
    check(marker.with_suffix('.exit').read_text().startswith('could not start'), 'and says it could not start')


def test_trust(tmp: Path):
    print('copilot: the repo and its slots are trusted folders')
    home = tmp / 'copilot-home'
    home.mkdir()
    (home / 'config.json').write_text('// User settings belong in settings.json.\n// This file is managed automatically.\n'
                                      + json.dumps({'other': True, 'trustedFolders': [str(tmp / 'trusted')]}),
                                      encoding='utf-8')
    os.environ['COPILOT_HOME'] = str(home)
    R.copilot_trust(tmp / 'proj', tmp / 'trusted' / 'below')
    text = (home / 'config.json').read_text(encoding='utf-8')
    check(text.startswith('// User settings belong in settings.json.\n// This file'), 'its comment lines are kept')
    conf = json.loads(text.split('\n', 2)[2])
    eq(conf['trustedFolders'], [str(tmp / 'trusted'), str(tmp / 'proj')],
       'an untrusted folder is added; one under a trusted folder is not')
    check(conf['other'], 'the rest of config.json is kept')
    R.copilot_trust(tmp / 'proj')
    eq(len(json.loads((home / 'config.json').read_text(encoding='utf-8').split('\n', 2)[2])['trustedFolders']), 2,
       'and only once')


def test_transcript(tmp: Path):
    print('copilot: the transcript is session-state/<id>/events.jsonl')
    home = Path(os.environ['COPILOT_HOME'])
    d = home / 'session-state' / 'sid-9'
    d.mkdir(parents=True)
    ev = lambda t, ts, **data: json.dumps({'type': t, 'data': data, 'timestamp': ts},  # noqa: E731
                                          separators=(',', ':'))  # compact, as Copilot writes it
    lines = [ev('session.start', '2026-01-01T10:00:00.000Z'),
             ev('user.message', '2026-01-01T10:00:01.000Z', content='go'),
             ev('session.usage_record', '2026-01-01T10:00:05.000Z', usage={'inputTokens': 20000}),
             ev('tool.execution_complete', '2026-01-01T10:03:00.000Z', success=True),
             ev('session.usage_record', '2026-01-01T10:12:00.000Z', usage={'inputTokens': 64000})]
    (d / 'events.jsonl').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    eq(R.transcript('sid-9'), str(d / 'events.jsonl'), 'found by the session id we gave it')
    eq(R.transcript('nope'), None, 'and None for a session that never started')
    eq(R.stats('sid-9'), '12 min, 2 calls, context 20k first, 64k peak', 'stats read the usage records')
    eq(R._user_entries(str(d / 'events.jsonl')), 2, 'a user message and a tool result count as activity')
    eq(R.limit_only('sid-9', tmp / 'none.log', 0), None, 'a session that worked is not a usage limit')
    d2 = home / 'session-state' / 'sid-10'
    d2.mkdir()
    (d2 / 'events.jsonl').write_text(ev('session.error', '2026-01-01T10:00:00.000Z', errorType='rate_limit',
                                        message='Rate limit exceeded') + '\n', encoding='utf-8')
    check(R.limit_only('sid-10', tmp / 'none.log', 0) is not None, 'one that only hit a rate limit is')
    check(not d2.exists(), 'and its transcript is dropped, so nothing resumes it')

    print('copilot: a session that stopped on a failed model call (a network drop) is found, to be resumed')
    d3 = home / 'session-state' / 'sid-11'
    d3.mkdir()
    fail = ev('session.error', '2020-01-01T10:05:00.000Z', errorType='query',
              message='Execution failed: Failed to get response from the AI model; retried 5 times')
    (d3 / 'events.jsonl').write_text('\n'.join([*lines, ev('assistant.turn_end', '2020-01-01T10:05:00.000Z'), fail,
                                                ev('session.warning', '2020-01-01T10:06:00.000Z', message='x')])
                                     + '\n', encoding='utf-8')
    got = R.copilot_failed('sid-11')
    check(got is not None and 'Failed to get response' in got[0] and got[1] > R.RESUME_AFTER,
          'its last word is the failed call, and how long ago it was', str(got))
    with open(d3 / 'events.jsonl', 'a', encoding='utf-8') as f:
        f.write(ev('user.message', '2020-01-01T10:08:00.000Z', content=R.RESUME) + '\n')
    eq(R.copilot_failed('sid-11'), None, 'once it is resumed (a new message), it is not failed any more')
    eq(R.copilot_failed('sid-9'), None, 'and a session that is working is not failed')


def test_pi(repo: Path):
    print('pi: command lines, the extension, the session files, stats and resuming a failed call')
    R.init(repo)
    R.C.run['agent'], R.C.run['backend'], R.C.run['model'], R.C.run['fix_model'] = (
        'pi', 'pi', 'github-copilot/m1', 'github-copilot/m2')
    try:
        check(R.pi() and not R.copilot(), '[run] agent = "pi" is recognised')
        argv = R.agent_argv('do T1', 'sid-p', 'github-copilot/m1', 45, 'slotP')
        eq(argv[-2:], ['--', f'@{R.C.notes("slotP.prompt")}'], 'Pi reads its options, the prompt from a file')
        eq(R.C.notes('slotP.prompt').read_text(encoding='utf-8'), 'do T1', 'the prompt file keeps the full task')
        eq(argv[argv.index('--session-id') + 1], 'sid-p', 'the session id is ours')
        eq(Path(argv[argv.index('--session-dir') + 1]), R.pi_sessions(), 'in a session folder of this run')
        eq(argv[argv.index('--model') + 1], 'github-copilot/m1', 'with the model')
        exts = [Path(argv[i + 1]) for i, arg in enumerate(argv[:-1]) if arg == '-e']
        check([p.name for p in exts] == ['pi_hooks.ts', 'pi_idle.ts'] and '--runner-idle' in argv and
              argv[argv.index('--runner-idle') + 1] == '45', 'the extensions bridge hooks and stop idle sessions')
        eq(R.env_vars(R.slot_env(1)).get('GIT_CONFIG_COUNT'),
           str(int(os.environ.get('GIT_CONFIG_COUNT', '0')) + len(R.NO_PUSH_URLS)),
           'the Pi session inherits the no-push git config')
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
        f = R.pi_sessions() / '2020-01-01T10-00-00-000Z_sid-p.jsonl'
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
    finally:
        R.C.run['agent'], R.C.run['backend'], R.C.run['model'], R.C.run['fix_model'] = (
            'copilot', 'claude', 'm1', 'm2')


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix='agent-runner-copilot-'))
    repo = make_repo(tmp)
    return report([lambda: test_commands(repo), lambda: test_hooks(repo), lambda: test_no_push(repo),
                   lambda: test_trust(tmp), lambda: test_transcript(tmp), lambda: test_shim_once(repo, tmp),
                   lambda: test_utf8_merge(tmp), lambda: test_pi(repo)])


if __name__ == '__main__':
    sys.exit(main())
