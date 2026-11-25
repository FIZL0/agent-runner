#!/usr/bin/env python3
"""F406h: a run with no Claude Code at all: every [models] role on another provider, no `claude` on PATH. A run end to end
on a fake provider (setup, run, a task through a fix session and its merge, a control chat, the feed), and what must not
hold or be said: the Claude login, usage caps, API and a missing [run] agent. The end to end part needs node."""
from __future__ import annotations

import contextlib
import io
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

from _check import check, eq, git, has, report, TMP_ROOT

from agent_runner import agent_hold, claude_use, config as CF, control as K, feed, loop, page_copy as PC, \
    plan as P, plat, review, runner as R, sched, setup as SU, setup_models as SM, state as S, status, \
    ui_model as U, vitals as V, watch as W
from agent_runner.config import Config, runner_cmd

MODEL = 'codex:gpt-test'
ROLES = ''.join(f'{r} = "{MODEL}"\n' for r in ('code', 'review', 'fix', 'docs', 'control', 'feed'))
KINDS = 'kinds = { ' + ', '.join(f'{k} = "{MODEL}"' for k in CF.DEFAULTS['models']['kinds']) + ' }\n'

# The fake provider: a task's session, a fix session and a chat are told apart by their tools and first message.
FAKE = r"""
import fs from 'node:fs';
export default function ({ provider, model }) {
  return {
    async call(context) {
      const text = (m) => typeof m.content === 'string' ? m.content : m.content.map((b) => b.text || '').join(' ');
      const tools = context.tools.map((t) => t.name), first = text(context.messages.find((m) => m.role === 'user'));
      const n = context.messages.filter((m) => m.role === 'assistant').length;
      const kind = tools.includes('finish') ? (first.startsWith('A merge of task/') ? 'fix' : 'task') : tools.includes('bash') ? 'chat' : 'once';
      fs.appendFileSync(process.env.FAKE_LOG, JSON.stringify({ kind, n, provider, model, first, last: text(context.messages[context.messages.length - 1]) }) + '\n');
      const step = (JSON.parse(fs.readFileSync(process.env.FAKE_SCRIPT, 'utf8'))[kind] || [])[n];
      const content = step ? step.map(([name, args], i) => ({ type: 'toolCall', id: `c${n}_${i}`, name, arguments: args }))
        : [{ type: 'text', text: kind === 'chat' || kind === 'once' ? `answer to ${first.slice(0, 40)}` : 'nothing more to do' }];
      return { role: 'assistant', content, api: 'fake', provider, model, timestamp: Date.now(), stopReason: step ? 'toolUse' : 'stop',
        usage: { input: 10, output: 5, cacheRead: 0, cacheWrite: 0, cost: { total: 0 } } };
    },
  };
}
"""


def path_without_claude(tmp: Path) -> str:
    """This PATH, each folder that has a `claude` replaced by links to all else in it."""
    out = []
    for i, d in enumerate(x for x in os.environ['PATH'].split(os.pathsep) if x and Path(x).is_dir()):
        if shutil.which('claude', path=d):
            own = tmp / f'bin{i}'
            own.mkdir()
            for f in Path(d).iterdir():
                if f.stem.lower() != 'claude':
                    os.symlink(f, own / f.name)
            d = str(own)
        out.append(d)
    return os.pathsep.join(out)


def repo_at(root: Path, models: str = ROLES + KINDS, run: str = '') -> Path:
    root.mkdir(parents=True)
    git(root, 'init', '-q', '-b', 'main')
    (root / '.gitignore').write_text('.runner/\nrunner.local.toml\n', encoding='utf-8')
    (root / 'plan').mkdir()
    (root / 'plan' / 'TODO.md').write_text('# TODO\n\n- [ ] **F1** write a.txt | files: a.txt\n', encoding='utf-8')
    (root / 'plan' / 'DONE.md').write_text('# DONE\n', encoding='utf-8')
    (root / 'a.txt').write_text('start\n', encoding='utf-8')
    (root / 'runner.toml').write_text(f'[run]\ntest = "true"\nmin_free_gb = 0\n{run}\n[models]\n{models}', encoding='utf-8')
    git(root, 'add', '-A')
    git(root, 'commit', '-qm', 'start')
    return root


def load(root: Path) -> Config:
    CF._LIVE.clear()
    CF._cfg.cache_clear()
    R.init(root)
    S.share(C=Config(root))
    return S.C


def until(what, seconds: float = 60.0):
    end = time.monotonic() + seconds
    while not (got := what()) and time.monotonic() < end:
        time.sleep(0.1)
    return got


def logged_in(tmp: Path) -> None:
    """A fake Codex login, the fake provider."""
    pi = tmp / 'pi'
    pi.mkdir()
    (pi / 'auth.json').write_text('{"openai-codex": {"type": "oauth"}}', encoding='utf-8')
    (tmp / 'fake.mjs').write_text(FAKE, encoding='utf-8')
    (tmp / 'calls.jsonl').write_text('', encoding='utf-8')
    os.environ.update(PI_CODING_AGENT_DIR=str(pi), AGENT_RUNNER_HARNESS_PROVIDER=str(tmp / 'fake.mjs'),
                      FAKE_LOG=str(tmp / 'calls.jsonl'), FAKE_SCRIPT=str(tmp / 'script.json'))


# --- what counts as using Claude Code ------------------------------------------------------------------------------

def test_uses(tmp: Path) -> None:
    print('which settings need Claude Code')
    base = ROLES + KINDS
    cases = [('all on another provider', base, False),
             ('the defaults', '', True),
             *[(f'{r} left on claude', base.replace(f'{r} = "{MODEL}"', f'{r} = "opus"'), True)
               for r in ('code', 'review', 'fix', 'control', 'feed')],
             ('a claude: name', base.replace(f'fix = "{MODEL}"', 'fix = "claude:opus"'), True),
             ('docs alone: a subagent of a Claude Code session', base.replace(f'docs = "{MODEL}"', 'docs = "haiku"'), False),
             ('docs = false', base.replace(f'docs = "{MODEL}"', 'docs = false'), False),
             ('a kind', ROLES + KINDS.replace(f'R = "{MODEL}"', 'R = "sonnet"'), True),
             ('a fallback, with no Claude Code here', base + 'fallback = ["gemini:pro", "opus"]\n', False),
             ('a fallback on others', base + 'fallback = ["gemini:pro"]\n', False)]
    for i, (what, models, want) in enumerate(cases):
        c = Config(repo_at(tmp / f'uses{i}', models))
        eq(claude_use.uses(c), want, what)
    from agent_runner import fallback as FB
    c = load(repo_at(tmp / 'chain', base + 'fallback = ["opus", "codex:other", "gemini:pro"]\n'))
    with mock.patch('agent_runner.login.missing', lambda m, c: ''):
        eq((sched.agent_held(), FB.chain_next(MODEL)), ('', 'gemini:pro'), 'which a cap then passes over')
        c = load(repo_at(tmp / 'chain2', base + 'fallback = ["opus", "gemini:pro"]\n', run=f'agent = "{sys.executable}"'))
        eq((claude_use.uses(c), FB.chain_next(MODEL)), (True, 'opus'), 'a fallback on a Claude Code that is here')
    c = Config(repo_at(tmp / 'flag'))
    c.run['model_flag'] = 'opus'
    eq(claude_use.uses(c), True, '`run --model opus`')


# --- what must not hold or be said ------------------------------------------------------------------------------

def said(root: Path) -> dict:
    """What the run on `root` holds or says of Claude, with no login, a cap reached and its API out of reach."""
    c = load(root)
    W._api[:] = [-1e9, True]

    def down(*a, **k):
        raise OSError('no network')
    with mock.patch.object(W.socket, 'create_connection', down), mock.patch.object(loop, 'usage_pct', lambda n: 100), \
            mock.patch.object(V, 'login_now', lambda now: 'No Claude login'):
        snap = U.snapshot(up=False, links={}, windows={})
        out = {'api': W.api_up(), 'cap': loop.capped(False), 'login': W.claude_login_line(), 'page': snap['claude_login'],
               'home': V.login_banner([root]), 'agent': sched.agent_held(), 'line': snap['agent_problem'],
               'fallback': V.free_fallback(c), 'status': ' '.join(snap['status'])}
        agent_hold.SAID[0] = ''
    W._api[:] = [-1e9, True]
    return out


def test_lines(tmp: Path) -> None:
    print('no Claude login, usage, API or missing agent holds or is said')
    own = {k: v for k, v in os.environ.items() if k.lower() != 'https_proxy' and not k.startswith('ANTHROPIC_')
           and k not in ('CLAUDE_CODE_OAUTH_TOKEN', 'CLAUDE_CODE_USE_BEDROCK', 'CLAUDE_CODE_USE_VERTEX', 'CLAUDE_CODE_USE_FOUNDRY')}
    with mock.patch.dict(os.environ, own, clear=True), mock.patch('sys.platform', 'linux'):
        none, uses = said(repo_at(tmp / 'none')), said(repo_at(tmp / 'uses', ROLES.replace(f'fix = "{MODEL}"', 'fix = "opus"') + KINDS))
    eq({k: v for k, v in none.items() if k != 'status'},
       {'api': True, 'cap': None, 'login': '', 'page': '', 'home': '', 'agent': '', 'line': '', 'fallback': True}, 'none of it')
    check('claude' not in none['status'].lower(), 'nor in status', none['status'])
    eq(uses['api'], False, 'one role on it: its API counts')
    has(uses['cap'] or '', 'session usage 100%', 'its cap')
    has(uses['login'] + uses['page'] + uses['home'], 'No Claude login.*No Claude login.*No Claude login', 'its login')
    has(uses['agent'], "'claude' is not on this machine", 'and it is missed')
    eq(uses['agent'], uses['line'], 'on the page too')
    c = load(repo_at(tmp / 'gone', run='agent = "pi"'))
    has(c.agent_problem, 'was removed', 'a removed [run] agent is said all the same')
    root = repo_at(tmp / 'live')
    was = load(root)
    (root / 'runner.local.toml').write_text('[run]\nagent = "nowhere-claude"\n', encoding='utf-8')
    new, changed, _ = CF.read_again(was)
    eq((list(changed), new.agent_problem), ([('run', 'agent')], ''), 'a run takes a new [run] agent nothing uses')


def test_vitals(tmp: Path) -> None:
    print('vitals: no login push, no usage read, no cap in the headroom')
    root, other = repo_at(tmp / 'v'), repo_at(tmp / 'w', '')
    pushed, reads = [], []

    def device(roots, up=None):
        vit = V.Vitals(lambda: roots, None, tailscale=False, sampler=mock.Mock(sample=lambda now: {'t': now, 'host': 'h'}, proc=Path('/nowhere')),
                       sessions=lambda: [], usage=lambda: reads.append(1) or {'session': 99}, info=lambda r: {'up': r == up},
                       push=lambda rs, what, host: pushed.append((rs, what)) or 1, log=lambda s: None, login=lambda now: 'No Claude login')
        vit.started = True
        vit.foot, vit.foot_at = {}, 1e12
        vit.tick(1e9, walk=False)
        vit.tick(1e9 + 1, walk=False)
        return vit.device(detail=False)
    room = device([root])['headroom']
    check('usage' not in room['limits'], 'no usage limit', room)
    eq(([r for rs, _ in pushed for r in rs], reads), ([], []), 'no login pushed to it, no usage read')
    room = device([root, other], up=root)['headroom']
    check('usage' not in room['limits'], 'the run that is up has no Claude: another project\'s cap is nothing to it', room)
    eq([r for rs, _ in pushed for r in rs], [other], 'the login is pushed to the project that uses it')
    room = device([root, other], up=other)['headroom']
    eq(room['limits'].get('usage'), 0, 'whose cap counts while it is up')


def test_task_model(tmp: Path) -> None:
    print("a task whose own model is claude's waits alone")
    root = repo_at(tmp / 'own')
    load(root)
    from agent_runner import login
    eq(login.unlogged('F1', 'main', MODEL), False, 'a task on the other provider starts')
    with mock.patch('agent_runner.slots.task_model', lambda *a, **k: 'opus'):
        eq(login.unlogged('F1', 'main', MODEL), True, 'one on opus does not')
    asks = P.asks(root / 'plan' / 'TODO.md')
    eq([(a[0], a[1]) for a in asks], [('BLOCKED', 'F1')], 'it is under Needs you')
    has(str(asks), 'Claude Code is not on this machine', 'with why')
    eq(sched.agent_held(), '', 'and holds nothing else')


def test_task_held(tmp: Path) -> None:
    print("a task whose own model is claude's, with Claude Code here: the usage caps and the API hold it alone")
    from agent_runner import fallback as FB
    bin_ = tmp / 'claude-bin'
    bin_.mkdir()
    (bin_ / 'claude').write_text('#!/bin/sh\n', encoding='utf-8')
    (bin_ / 'claude').chmod(0o755)
    env = {k: v for k, v in os.environ.items() if k.lower() != 'https_proxy'}
    env['PATH'] = f'{bin_}{os.pathsep}{os.environ["PATH"]}'
    two = '# TODO\n\n- [ ] **F1** one | files: a.txt | model: opus\n- [ ] **F2** two | files: b.txt\n'

    def ticks(name: str, usage: int = 0, api: bool = True, todo: str = two, chain: str = '', force: bool = False) -> tuple:
        """(what one fill of each of two slots started, the alarms, the usage and API reads, the log)"""
        root = repo_at(tmp / name, ROLES + KINDS + chain)
        (root / 'plan' / 'TODO.md').write_text(todo, encoding='utf-8')
        git(root, 'commit', '-qam', 'plan', '--allow-empty')
        c = load(root)
        started, alarms, reads, logs = [], [], [], []

        def connect(*a, **k):
            reads.append('api')
            if not api:
                raise OSError('no network')
            return mock.Mock()

        def start(n, task, branch, model, idle, slots, held=frozenset()):
            m = 'opus' if task[0] == 'F1' else MODEL
            started.append((task[0], FB.start_model(m, held)))
            return (n, 'sid', None)
        r = loop.Run.__new__(loop.Run)
        r.__dict__.update(procs={}, running={}, slots=2, r=c.run, a=mock.Mock(force=force), branch='main', model=MODEL,
                          idle=30, pause=1, tried=set(), merging=[], waiting={}, foreign={}, stall_said=set(),
                          held_said=2, cap_said=False, cap_fell=False, once=True, idle_said=False, failed_starts={},
                          free_at={})
        W._api[:] = [-1e9, True]
        with mock.patch.object(W.socket, 'create_connection', connect), mock.patch.object(loop, 'start', start), \
                mock.patch.object(loop, 'usage_pct', lambda n: reads.append('usage') or usage), \
                mock.patch.object(loop, 'alarm', lambda *a: alarms.append(a[0])), \
                mock.patch.object(loop, 'log', lambda s, *a, **k: logs.append(s)), \
                mock.patch.object(S, 'log', lambda s, *a, **k: logs.append(s)), \
                mock.patch.object(loop, 'ask_stop', lambda *a: None), mock.patch.object(loop, 'low_disk', lambda *a: False), \
                mock.patch.object(loop.shared_tools, 'low_memory', lambda: False), \
                mock.patch('agent_runner.login.missing', lambda m, c: ''):
            r.fill(1)
            r.fill(2)
        W._api[:] = [-1e9, True]
        return started, alarms, set(reads), ' '.join(logs)
    with mock.patch.dict(os.environ, env, clear=True):
        one = two[:two.index('- [ ] **F2')]
        own, other = ('F1', 'opus'), ('F2', MODEL)
        eq(ticks('h-ok')[0], [own, other], 'nothing in the way: both start')
        alarm = ['session usage 100% >= 90%: F1 cannot start until the reset']
        eq(ticks('h-cap', usage=100)[:2], ([other], alarm), 'past the cap: only the other starts, and the alarm names the one held')
        eq(ticks('h-cap1', usage=100, todo=one)[:2], ([], alarm), 'alone in the plan: held, and the alarm is raised once')
        eq(ticks('h-force', usage=100, force=True)[0], [own, other], 'forced: the cap is off')
        chain = 'fallback = ["gemini:pro"]\n'
        got = ticks('h-chain', usage=100, api=False, chain=chain)
        eq(got[0], [('F1', 'gemini:pro'), other], 'a chain: it starts there, its API nothing to it')
        has(got[3], 'first free provider in .models. fallback', 'and it is said')
        got = ticks('h-api', api=False)
        eq(got[0], [other], 'the API down: only the other starts')
        eq(got[3].count('F1 cannot start'), 1, 'which is said once')
        eq(ticks('h-api-chain', api=False, chain=chain)[0], [other], 'with a chain too')
        eq(ticks('h-none', usage=100, api=False, todo=two.replace(' | model: opus', ''))[2], set(),
           'no task on claude: no usage and no API is read')


def test_resume_held(tmp: Path) -> None:
    print('a cut-off session on a claude model waits for the Claude API, any other resumes')
    from agent_runner import fallback as FB
    env = {k: v for k, v in os.environ.items() if k.lower() != 'https_proxy'}

    def ticks(name: str, was: str, api: list[bool], fallback: str = '', **run) -> tuple:
        """(how many resumes after each tick of slot 1, whether it still waits, the log), `api` up or not at each"""
        c = load(repo_at(tmp / name))
        c.run.update(run)
        FB.note_model('sid', was)
        if fallback:
            FB.queue_fallback('F1', 1, 'sid', 'cut', fallback)
        else:
            c.notes('F1.resume').write_text(json.dumps({'slot': 1, 'sid': 'sid', 'why': 'cut'}), encoding='utf-8')
        resumed, logs, counts = [], [], []
        r = loop.Run.__new__(loop.Run)
        r.__dict__.update(procs={}, running={}, slots=1, branch='main', model=MODEL, idle=30, tried=set(),
                          waiting={1: ('F1', 'sid', 'cut')}, stall_said=set(), idle_said=False)

        def resume(n, tid, sid, why, branch, model, idle, fallback='', slots=1):
            resumed.append(fallback)
            return (n, sid, None)

        for up in api:
            W._api[:] = [-1e9, True]
            with mock.patch.object(W.socket, 'create_connection', mock.Mock(side_effect=None if up else OSError('no network'))), \
                    mock.patch.object(loop, 'resume', resume), mock.patch.object(S, 'log', lambda s, *a, **k: logs.append(s)):
                if r.waiting:
                    r.resume_queued(1)
            counts.append(len(resumed))
        W._api[:] = [-1e9, True]
        eq(c.notes('F1.resume').exists(), bool(r.waiting), f'{name}: its queue mark goes only when it resumes')
        return counts, bool(r.waiting), ' '.join(logs), resumed
    with mock.patch.dict(os.environ, env, clear=True):
        got = ticks('r-own', 'opus', [False, False, True])
        eq(got[:2], ([0, 0, 1], False), 'on opus: held while the API is down, resumed once it is up')
        eq(got[2].count('F1 cannot resume'), 1, 'which is said once')
        eq(ticks('r-other', MODEL, [False])[:3], ([1], False, ''), 'on the other provider: resumed')
        eq(ticks('r-to', MODEL, [False], 'opus')[:2], ([0], True), 'queued to go on with opus: held')
        got = ticks('r-from', 'opus', [False], MODEL)
        eq((got[0], got[3]), ([1], [MODEL]), 'queued to go on from opus with the other: resumed')
        eq(ticks('r-agent', 'opus', [False], agent='other')[0], [1], 'another [run] agent: the Claude API holds nothing')


# --- end to end ----------------------------------------------------------------------------------------------------

def calls(tmp: Path) -> list[dict]:
    return [json.loads(x) for x in (tmp / 'calls.jsonl').read_text(encoding='utf-8').splitlines()]


def test_setup(tmp: Path) -> None:
    print('setup: every role goes to the pick, and the setup session runs on it')
    root = tmp / 'fresh'
    root.mkdir()
    git(root, 'init', '-q', '-b', 'main')
    git(root, 'commit', '-q', '--allow-empty', '-m', 'start')
    (tmp / 'script.json').write_text(json.dumps({'chat': [[['bash', {'command': f'{shlex.join(runner_cmd())} plan goal "a goal"'}]]]}),
                                     encoding='utf-8')
    answers = ['codex', 'gpt-test']
    out = io.StringIO()
    real, seen = subprocess.run, []

    def run(cmd, *a, **kw):  # the session's terminal is closed, so it ends with its first turn
        if 'harness.mjs' in ' '.join(map(str, cmd)):
            seen.append(cmd)
            p = subprocess.Popen(cmd, cwd=kw['cwd'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            until(lambda: any(c['kind'] == 'chat' and c['n'] == 1 for c in calls(tmp)))
            time.sleep(0.5)
            return subprocess.CompletedProcess(cmd, (p.communicate()[0], p.returncode)[1])
        return real(cmd, *a, **kw)
    CF._cfg.cache_clear()
    with mock.patch.object(SU, 'offer_ttyd', lambda: None), mock.patch.object(SU, 'at_terminal', lambda: True), \
            mock.patch('builtins.input', lambda q='': answers.pop(0)), mock.patch.object(SU.subprocess, 'run', run), \
            contextlib.redirect_stdout(out):
        eq(SU.main([], cwd=root), 0, 'setup ends well')
    c = Config(root)
    eq({c.models[r] for r in ('code', 'fix', 'review', 'control', 'feed', 'docs')}, {MODEL}, 'every role')
    eq(claude_use.uses(c), False, 'so it needs no Claude Code')
    has(out.getvalue(), 'setup session ended .exit 0', 'the session ran')
    check('cannot run yet' not in out.getvalue(), 'and nothing is said to wait', out.getvalue())
    has(calls(tmp)[0]['first'], 'Set this repository up', 'with setup\'s own first message')
    has((root / 'plan' / 'TODO.md').read_text(encoding='utf-8'), 'a goal', 'and it wrote the plan')
    with mock.patch('agent_runner.login.missing', lambda m, c: 'codex'):
        has(SU.no_claude(root), 'codex has no login.*cannot run yet', 'with no login it says so')


def test_run(tmp: Path) -> None:
    print('a run: a task, a conflict for a fix session, the merge')
    root = repo_at(tmp / 'repo')
    git(root, 'config', 'core.autocrlf', 'false')
    main = tmp / 'main_moves.py'  # what makes the conflict: main changes a.txt while the task works
    main.write_text('import subprocess, sys, pathlib\n'
                    f'r = {str(root)!r}\npathlib.Path(r, "a.txt").write_text("from main\\n")\n'
                    'subprocess.run(["git", "-C", r, "commit", "-qam", "main moves"], check=True)\n', encoding='utf-8')
    bash = lambda c: ['bash', {'command': c}]  # noqa: E731
    (tmp / 'script.json').write_text(json.dumps({
        'task': [[['write', {'path': 'a.txt', 'content': 'from F1\n'}], bash('git add a.txt && git commit -qm "F1 a"')],
                 [bash(shlex.join([*runner_cmd(), 'done', 'F1', 'F1 a']))],
                 [bash(f'{shlex.quote(sys.executable)} {shlex.quote(str(main))}')],
                 [['finish', {'summary': 'wrote a.txt'}]]],
        'fix': [[['write', {'path': 'a.txt', 'content': 'from main\nfrom F1\n'}], bash('git add a.txt && git commit -q --no-edit')]],
    }), encoding='utf-8')
    (tmp / 'calls.jsonl').write_text('', encoding='utf-8')
    env = {k: v for k, v in os.environ.items() if k != 'AGENT_RUNNER_CONFIG'}
    try:
        p = subprocess.run([*runner_cmd(), 'run', 'once', '--pause', '1'], cwd=root, env=env, stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, timeout=240)
        out = p.stdout + p.stderr
    except subprocess.TimeoutExpired as e:
        out = f'timed out: {(e.stdout or b"")[-3000:]!r}'
    log = (root / '.runner' / 'run.log').read_text(encoding='utf-8', errors='replace')
    kinds = [c['kind'] for c in calls(tmp)]
    check('task' in kinds and 'fix' in kinds, 'the task and the fix session ran on the provider', (kinds, out[-2500:]))
    eq(git(root, 'show', 'main:a.txt').strip(), 'from main\nfrom F1', 'the conflict is resolved and merged')
    check('F1' not in sched.open_tasks('main') if load(root) else False, 'the task is ticked')
    for bad in ('usage', 'API cannot', 'No agent session', 'not on this machine', 'log in'):
        check(bad not in log, f'the run log has no {bad!r}', log[-2500:])
    r = subprocess.run([*runner_cmd(), 'status'], cwd=root, env=env, capture_output=True, text=True, timeout=60)
    check(r.returncode == 0 and 'claude' not in r.stdout.lower(), 'status says nothing of Claude', r.stdout + r.stderr)


def test_chat(tmp: Path) -> None:
    print('a control chat and the feed')
    root = tmp / 'repo'
    load(root)
    (tmp / 'script.json').write_text('{}', encoding='utf-8')
    r = subprocess.run([*runner_cmd(), 'control', '--new', '--ask', 'hello there'], cwd=root, capture_output=True, text=True, timeout=90)
    check(r.returncode == 0, 'a chat starts', r.stdout + r.stderr)
    n = next((i for i in range(1, 9) if K.control_kept_sid(i)), 0)
    try:
        check(until(lambda: 'answer to hello there' in K.control_state(K.entries(K.control_kept_sid(n), skip_bad=True))['text']), 'and answers')
    finally:
        K.end_control(n, 'the test is over')
    page = tmp / 'page.html'
    page.write_text('<p>hi</p>', encoding='utf-8')
    eq(PC.page_copy_publish(page, ''), '', 'the feed\'s one-shot runs, and the local copy stands')
    said_, why = feed.harness_once(feed.feed_model(), 'say hi', tmp, 60)
    eq((said_, why), ('answer to say hi', ''), 'it answers')
    with mock.patch.object(review, 'git', lambda *a, **k: mock.Mock(returncode=0, stdout='+x')), \
            mock.patch.object(review, 'prompt', lambda *a: 'review this'):
        eq(review.review('F1', 'main', root), ('answer to review this', ''), 'so does the spec review')


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix='no-claude-', dir=TMP_ROOT)).resolve()
    if plat.WINDOWS:  # the links below need a privilege there
        print('SKIP: Windows')
        return report([lambda: test_uses(tmp)])
    os.environ['PATH'] = path_without_claude(tmp)
    for k in (K.CONTROL_N_ENV, 'AGENT_RUNNER_CONFIG'):
        os.environ.pop(k, None)
    here = os.getcwd()
    logged_in(tmp)
    assert not shutil.which('claude')
    tests = [test_uses, test_lines, test_vitals, test_task_model, test_task_held, test_resume_held]
    if shutil.which('node'):
        tests += [test_setup, test_run, test_chat]
    else:
        print('SKIP: no node on PATH')
    try:
        return report([lambda t=t: t(tmp) for t in tests])
    finally:
        os.chdir(here)


if __name__ == '__main__':
    sys.exit(main())
