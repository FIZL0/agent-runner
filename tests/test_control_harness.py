#!/usr/bin/env python3
"""F406f: a control session on the harness loop (agent_runner/control_harness.py, harness.mjs --chat), with a fake
provider: a hidden session and its transcript, a second turn, resume, the idle close, the git fence, the brief. Needs
node; no network and no real provider."""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from unittest import mock

from _check import check, eq, git, has, report

from agent_runner import control as K, control_harness as CH, control_names, control_reopen as CR, guide as G, \
    plat, runner as R, slots, state as S, tools
from agent_runner.config import Config, runner_cmd

os.environ.pop(K.CONTROL_N_ENV, None)  # a run a control session started hands its number on

# The fake provider answers the last user message: "run: CMD" calls bash, "read: FILE" read, "slow" never answers, "fail" is an error.
FAKE = r"""
import fs from 'node:fs';
export default function ({ provider, model }) {
  return {
    async call(context) {
      const last = context.messages[context.messages.length - 1];
      const text = typeof last.content === 'string' ? last.content : last.content.map((b) => b.text || '').join(' ');
      fs.appendFileSync(process.env.FAKE_LOG, JSON.stringify({ provider, model, system: context.systemPrompt,
        tools: context.tools.map((t) => t.name), images: context.messages.flatMap((m) => Array.isArray(m.content) ? m.content.filter((b) => b.type === 'image') : []),
        said: context.messages.filter((m) => m.role === 'user').map((m) => m.content) }) + '\n');
      const base = { role: 'assistant', api: 'fake', provider, model, timestamp: Date.now(), usage: { input: 10, output: 5,
        cacheRead: 0, cacheWrite: 0, cost: { total: 0 } } };
      if (last.role === 'user' && text === 'slow') await new Promise((r) => setTimeout(r, 60000));
      if (last.role === 'user' && text === 'fail') return { ...base, content: [], stopReason: 'error', errorMessage: '400 invalid request' };
      if (last.role === 'user' && text.startsWith('run: '))
        return { ...base, stopReason: 'toolUse', content: [{ type: 'toolCall', id: `c${Date.now()}`, name: 'bash', arguments: { command: text.slice(5) } }] };
      if (last.role === 'user' && text.startsWith('read: '))
        return { ...base, stopReason: 'toolUse', content: [{ type: 'toolCall', id: `c${Date.now()}`, name: 'read', arguments: { path: text.slice(6) } }] };
      return { ...base, stopReason: 'stop', content: [{ type: 'text', text: `answer to ${last.role === 'user' ? text : `tool (${text})`}` }] };
    },
  };
}
"""
MODEL = 'codex:gpt-test'
UNWANTED = re.compile(r'Artifact|PushNotification|Remote Control|Monitor|ToolSearch|claude\.ai/code|SendUserFile|subagent|Claude app')


class Env:
    def __init__(self, tmp: Path):
        self.repo = tmp / 'repo'
        self.repo.mkdir()
        git(self.repo, 'init', '-q', '-b', 'main')
        (self.repo / '.gitignore').write_text('.runner/\nrunner.toml\nrunner.local.toml\n', encoding='utf-8')
        (self.repo / 'README.md').write_text('test\n', encoding='utf-8')
        (self.repo / 'plan').mkdir()
        (self.repo / 'plan' / 'TODO.md').write_text('# TODO\n\n- [ ] **F1** a | files: a.txt\n', encoding='utf-8')
        git(self.repo, 'add', '.')
        git(self.repo, 'commit', '-qm', 'start')
        self.fake, self.log = tmp / 'fake.mjs', tmp / 'calls.jsonl'
        self.fake.write_text(FAKE, encoding='utf-8')
        self.log.write_text('', encoding='utf-8')
        os.environ.update(AGENT_RUNNER_HARNESS_PROVIDER=str(self.fake), FAKE_LOG=str(self.log))
        self.procs: list[subprocess.Popen] = []
        self.configure()

    def configure(self, model: str = MODEL):
        (self.repo / 'runner.toml').write_text(
            f'[run]\nremote = true\nagent = {json.dumps(sys.executable)}\n\n[models]\ncontrol = "{model}"\n', encoding='utf-8')
        R.init(self.repo)
        S.share(C=Config(self.repo))
        S.C = K.C

    def start(self, n: int, ask: str = '', reopen: bool = False) -> tuple[subprocess.Popen, str]:
        """Control session `n` as `control N` starts it, its terminal a pipe."""
        sid, resume, argv = K.control_open(n, ask=ask, reopen=reopen)
        env = {**K.control_env(), K.CONTROL_N_ENV: str(n)}
        p = subprocess.Popen(argv, cwd=str(self.repo), env=env, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                             stderr=subprocess.STDOUT, text=True, encoding='utf-8')
        self.procs.append(p)
        K.C.notes(f'control{n}.pid').write_text(f'{p.pid} {sid}', encoding='utf-8')
        return p, sid

    def calls(self) -> list[dict]:
        return [json.loads(x) for x in self.log.read_text(encoding='utf-8').splitlines()]


def until(what, seconds: float = 30.0):
    end = time.monotonic() + seconds
    while not (got := what()) and time.monotonic() < end:
        time.sleep(0.05)
    return got


def tell(p, text: str):
    p.stdin.write(f'\x1b[200~{text}\x1b[201~\r')
    p.stdin.flush()


def escape(p):
    p.stdin.write('\x1b')
    p.stdin.flush()
    time.sleep(0.3)  # an Escape with nothing after it, as a key is


def state(sid: str) -> dict:
    return K.control_state(K.entries(sid, skip_bad=True))


def answered(sid: str, text: str):
    return until(lambda: (s := state(sid))['last'] == 'claude' and text in s['text'])


def test_chat(env: Env):
    print('first message, a second turn, an error, an interrupt')
    p, sid = env.start(2, ask='hello there')
    check(answered(sid, 'answer to hello there'), 'the first message is answered', state(sid))
    call = env.calls()[0]
    eq((call['provider'], call['model']), ('codex', 'gpt-test'), 'by the provider and model of [models] control')
    eq(call['tools'], ['bash', 'read', 'edit', 'write', 'publish_page'], 'with a chat\'s tools: no finish, no ask')
    check('agent-runner control session' in call['system'], 'the control brief is its system text')
    eq(UNWANTED.findall(call['system']), [], 'which names nothing it has not')
    tell(p, 'two\nlines')
    check(answered(sid, 'answer to two\nlines'), 'a message typed in is its next turn', state(sid))
    eq(env.calls()[-1]['said'], ['hello there', 'two\nlines'], 'in the same conversation')
    eq(state(sid)['said'], 2, 'the person\'s two messages')
    tell(p, 'fail')
    check(until(lambda: '400 invalid' in state(sid)['text']), 'a failed model call is said', state(sid))
    tell(p, 'still there?')
    check(answered(sid, 'still there?'), 'and the session goes on')
    tell(p, 'slow')
    check(until(lambda: env.calls()[-1]['said'][-1] == 'slow'), 'a turn that hangs')
    escape(p)
    check(until(lambda: any('[Request interrupted' in K.message_text(d) for d in K.entries(sid, skip_bad=True))),
          'Escape interrupts it')
    tell(p, 'run: echo hi; echo $AGENT_RUNNER_CONTROL')
    check(answered(sid, 'answer to tool (hi\n2'), 'a tool runs, and knows its number', state(sid))
    tell(p, 'run: sleep 60')
    until(lambda: state(sid)['last'] == 'tool')
    time.sleep(0.5)
    t0 = time.monotonic()
    escape(p)
    tell(p, 'after')
    check(answered(sid, 'answer to after') and time.monotonic() - t0 < 20, 'Escape stops a tool too', state(sid))
    eq(K.transcript(sid), str(K.C.notes('harness-sessions') / f'{sid}.jsonl'), 'its transcript is where a control chat\'s is read')
    return p, sid


def msys_pids() -> set[int]:
    return {pid for pid, _, name in plat._snapshot() if name.lower() in ('sleep.exe', 'cat.exe')}


def test_stopped_tool(env: Env, p, sid: str):
    print('Windows: a stopped tool call leaves no Git Bash child')
    if not plat.WINDOWS:
        return
    for i, cmd in enumerate(('sleep 61; echo x', '(sleep 61; echo x) & wait', 'sleep 61 | cat')):
        before = msys_pids()
        tell(p, f'run: {cmd}')
        check(until(lambda: msys_pids() - before), f'it runs: {cmd}')
        time.sleep(0.5)  # `cat` too
        mine = msys_pids() - before
        escape(p)
        tell(p, f'stopped {i}')
        check(answered(sid, f'answer to stopped {i}'), 'Escape stops it', state(sid))
        check(until(lambda: not mine & msys_pids(), 10), 'and no child of it is left', mine & msys_pids())
    tell(p, 'run: echo "a*"\'\\"\'; exit 3')
    check(answered(sid, 'answer to tool (a*\\"'), 'a command reaches bash as it is', state(sid))
    has(state(sid)['text'], r'exit code 3', 'and its exit code comes back')
    before = msys_pids()
    tell(p, 'run: sleep 30 >/dev/null 2>&1 </dev/null & echo left')
    check(answered(sid, 'answer to tool (left'), 'a call that ends by itself', state(sid))
    left = msys_pids() - before
    check(left, 'leaves its background process going')
    for pid in left:
        subprocess.run(['taskkill', '/F', '/PID', str(pid)], capture_output=True)
    for n, how, end in ((7, 'Ctrl-D', lambda q: (q.stdin.write('\x04'), q.stdin.flush())),
                        (8, 'a chat closed from outside', lambda q: subprocess.run(
                            ['taskkill', '/T', '/F', '/PID', str(q.pid)], capture_output=True))):
        before = msys_pids()
        q, _ = env.start(n, ask='run: sleep 61 | cat')
        check(until(lambda: len(msys_pids() - before) > 1), 'a chat with a tool call')
        mine = msys_pids() - before
        end(q)
        check(until(lambda: not mine & msys_pids(), 10), f'{how} ends its children too', mine & msys_pids())
        until(lambda: q.poll() is not None)
        K.C.notes(f'control{n}.pid').unlink()


def test_title(env: Env, sid: str):
    print('its title')
    with mock.patch.object(K, 'control_type', lambda *a: check(False, 'nothing is typed into it', a)), \
            contextlib.redirect_stdout(io.StringIO()):
        eq(K.control_set_title(2, 'R43 site deploy'), 0, 'control --title')
        eq(K.control_given(2), f'{env.repo.name} · R43 · site deploy', 'names it in state')
        eq(control_names.control_rename('2', 'mine'), 0, 'control --rename')
    check(K.control_renamed(state(sid), 2), 'a person\'s name is kept')
    K.C.notes('control2.name').unlink()


def test_idle_and_resume(env: Env, p, sid: str):
    print('close when idle, reopen and resume')
    now = time.time()
    eq(K.close_controls(force=True, now=now), [], 'not closed at once')
    out = K.close_controls(force=True, now=now + 100000)
    eq([(n, how) for n, how, _ in out], [(2, 'closed')], 'closed when idle')
    until(lambda: p.poll() is not None)
    eq(p.returncode, 1 if plat.WINDOWS else 0, 'the process ends')  # Windows: taskkill, whose exit code is 1
    has(K.C.notes('run.log').read_text(encoding='utf-8'), rf'control --resume {sid}', 'the run log says how to go on with it')
    was = len(env.calls())
    p2, sid2 = env.start(2, reopen=True)
    eq(sid2, sid, 'reopened by its session id')
    time.sleep(1)
    eq((len(env.calls()), p2.poll()), (was, None), 'and waits for the person')
    tell(p2, 'again')
    check(answered(sid, 'answer to again'), 'answers')
    check('hello there' in env.calls()[-1]['said'], 'with the earlier conversation')
    with contextlib.redirect_stderr(io.StringIO()):
        eq(CH.resume_number(sid), 0, 'a session that is up is not resumed twice')
    p2.stdin.close()
    until(lambda: p2.poll() is not None)
    eq(p2.returncode, 0, 'a closed terminal ends it')
    K.C.notes('control2.pid').unlink()
    n = CH.resume_number(sid)
    eq(K.control_sid(n, reopen=True), (sid, True), 'control --resume SID goes on with it')
    K.C.notes(f'control{n}.pid').write_text(f'999999999 {sid}', encoding='utf-8')
    eq(CR.controls_to_reopen(booted=time.time() + 60), [(n, sid)], 'a shutdown\'s reopen finds it')
    env.configure('opus')
    eq(CR.controls_to_reopen(booted=time.time() + 60), [], 'not with [models] control on Claude Code, which cannot read it')
    check('--remote-control' in K.control_argv(3, 'sid-x', False, 'hi', typed=False), 'Claude Code starts as before')
    env.configure()


def test_command(env: Env):
    print('control --new: a hidden session, its messages typed in')
    if plat.WINDOWS:
        return
    r = subprocess.run([*runner_cmd(), 'control', '--new', '--ask', 'from the page'], cwd=str(env.repo),
                       capture_output=True, text=True, timeout=90)
    has(r.stdout, r'control (\d+) is up in .*it is local \(on the harness loop\)', 'it says it is local, waiting for no link')
    if not (m := re.search(r'control (\d+) ', r.stdout)):
        return check(False, 'it started', r.stderr)
    n = int(m[1])
    until(lambda: K.control_live(n) and K.control_kept_sid(n))
    sid, pid = K.control_kept_sid(n), K.control_live(n)
    try:
        check(answered(sid, 'answer to from the page'), 'the ask is answered', state(sid))
        check(until(lambda: K.control_takes_input(n)), 'it takes input')
        check(K.control_type(n, 'typed in ' + 'x' * 6000), 'a long message is typed in')
        check(answered(sid, 'x' * 6000), 'and answered whole', state(sid)['text'][:80])
    finally:
        K.end_control(n, 'the test is over')
    check(pid and until(lambda: not plat.alive(pid)), 'closing it ends it', pid)


def test_fence(env: Env):
    print('the fence')
    remote = env.repo.parent / 'remote.git'
    git(env.repo, 'init', '-q', '--bare', str(remote))
    git(env.repo, 'remote', 'add', 'origin', str(remote))
    p, sid = env.start(4, ask='run: git push origin main')
    check(answered(sid, 'no `git push`'), 'a git push is refused', state(sid))
    eq(subprocess.run(['git', '-C', str(remote), 'branch'], capture_output=True, text=True).stdout, '', 'and nothing was pushed')
    tell(p, 'run: git commit --allow-empty -m x')
    check(answered(sid, 'no `git commit` in the main checkout'), 'a commit in the main checkout too', state(sid))
    tell(p, 'run: git merge main')
    check(answered(sid, 'no `git merge` in the main checkout'), 'and a merge', state(sid))
    tell(p, 'run: git log --oneline')
    check(answered(sid, 'start'), 'git log runs', state(sid))
    p.stdin.close()
    wt, other = R.SLOTS_DIR / 'take-F1', env.repo.parent / 'other'
    git(env.repo, 'worktree', 'add', '-q', '-b', 'task/F1', str(wt))
    git(env.repo, 'init', '-q', str(other))

    def fence(tool, **inp):
        return CH.fence(tool, inp, env.repo, env.repo, R.SLOTS_DIR, K.C.notes(), True)
    eq(fence('Bash', command=f'cd {wt.as_posix()} && git commit -m "x"'), None, 'a commit in a take worktree runs')
    check(fence('Bash', command=f'git -C {wt.as_posix()} push'), 'a push there does not')
    eq(fence('Bash', command=f'git -C {other.as_posix()} push'), None, 'another repository is not fenced')
    for cmd in ('bash -c "git push"', '(cd /tmp); git push', 'cd /nowhere-at-all || git commit -m x', 'sh -c "git merge main"'):
        check(fence('Bash', command=cmd), f'refused: {cmd}')
    check(fence('Bash', command='git reset --hard'), 'git reset --hard does not run')
    check(fence('Edit', file_path='README.md'), 'no edit of a file in the main checkout')
    eq(fence('Edit', file_path='runner.local.toml'), None, 'but one git ignores')
    eq(fence('Write', file_path=str(K.C.notes('x.html'))), None, 'and the notes')
    eq(fence('Write', file_path=str(wt / 'a.txt')), None, 'and a take worktree')
    check(fence('Write', file_path=str(R.SLOTS_DIR / 's1' / 'a.txt')), 'not a slot\'s')
    out = io.StringIO()
    ev = json.dumps({'tool_name': 'Bash', 'tool_input': {'command': 'git push'}, 'cwd': str(env.repo)})
    with mock.patch.object(sys, 'stdin', io.StringIO(ev)), contextlib.redirect_stdout(out):
        eq(tools.fence_hook([str(env.repo), str(R.SLOTS_DIR), str(K.C.notes()), '1', 'control']), 0, 'the hook, with no AGENT_RUNNER')
    has(out.getvalue(), 'deny', 'denies')


def test_brief_and_pages(env: Env):
    print('the brief and its pages')
    check(not slots.remote_on(), 'no Remote Control, though [run] remote = true')
    brief = K.control_brief(harness=True)
    check('Never commit, merge or push in this checkout' in brief, 'the brief\'s rules stay')
    eq(UNWANTED.findall(brief), [], 'the brief names nothing it has not')
    sid = str(uuid.uuid4())
    (K.C.notes('harness-sessions') / f'{sid}.jsonl').touch()
    K.C.notes('control9.pid').write_text(f'1 {sid}', encoding='utf-8')
    here = os.getcwd()
    os.chdir(env.repo)
    try:
        with mock.patch.dict(os.environ, {K.CONTROL_N_ENV: '9'}):
            for t in (*G.TOPICS, *G.CONTROL_TOPIC_NAMES):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    G.cmd_guide([t])
                eq(UNWANTED.findall(out.getvalue()), [], f'guide {t} too')
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            G.cmd_guide(['concepts'])
        has(out.getvalue(), 'Artifact tool', 'a Claude Code session\'s pages stay')
    finally:
        os.chdir(here)
    K.C.notes('control9.pid').unlink()
    K.C.notes('concepts', 'chat1ab12.html').write_text('<p>hi</p>', encoding='utf-8')
    r = subprocess.run([*runner_cmd(), 'plan', 'concept', 'a look', '--page', '/concept/chat1ab12'], cwd=str(env.repo),
                       capture_output=True, text=True, timeout=60)
    m = re.search(r'concept (K\d+) filed', r.stdout)
    check(m and K.C.notes('concepts', f'{m[1]}.html').read_text(encoding='utf-8') == '<p>hi</p>',
          'a page with no claude.ai address is filed as a concept, its copy kept', r.stdout + r.stderr)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix='agent-runner-control-harness-', ignore_cleanup_errors=True) as d:
        here = os.getcwd()
        env = Env(Path(d).resolve())

        def chat():
            p, sid = test_chat(env)
            test_stopped_tool(env, p, sid)
            test_title(env, sid)
            test_idle_and_resume(env, p, sid)
        try:
            tests = [lambda: test_brief_and_pages(env)]
            if shutil.which('node'):
                tests = [chat, lambda: test_command(env), lambda: test_fence(env), *tests]
            else:
                print('SKIP: no node on PATH')
            return report(tests)
        finally:
            for p in env.procs:
                p.kill()
            os.chdir(here)


if __name__ == '__main__':
    sys.exit(main())
