#!/usr/bin/env python3
"""F106c: the harness loop (agent_runner/harness.mjs), run end to end with a fake provider: a temporary repository,
a slot worktree on task/F1, and the session started from the argv the runner builds for a model on another
provider. Needs node; no network and no real provider."""
from __future__ import annotations

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

from _check import check, eq, git, has, report

from agent_runner import runner as R
from agent_runner.config import Config, runner_cmd
from agent_runner.tools import take_end

# The fake provider: each call answers with step N of $FAKE_SCRIPT, N being the assistant messages already in the
# context (so a resumed session goes on where it was), and logs what it was given to $FAKE_LOG.
FAKE = r"""
import fs from 'node:fs';
export default function ({ provider, model }) {
  return {
    async call(context) {
      const steps = JSON.parse(fs.readFileSync(process.env.FAKE_SCRIPT, 'utf8'));
      const n = context.messages.filter((m) => m.role === 'assistant').length;
      fs.appendFileSync(process.env.FAKE_LOG, JSON.stringify({ provider, model, n, tools: context.tools.map((t) => t.name),
        messages: context.messages.map((m) => ({ role: m.role, text: typeof m.content === 'string' ? m.content :
          m.content.map((b) => b.text || b.name || '').join(' ') })) }) + '\n');
      const step = steps[n] || { text: 'nothing more to do' };
      if (step.cap === provider)  // F106g: this provider is at its cap for this step
        return { role: 'assistant', content: [], api: 'fake', provider, model, timestamp: Date.now(),
          stopReason: 'error', errorMessage: '429 You exceeded your current quota' };
      const content = [];
      if (step.text) content.push({ type: 'text', text: step.text });
      (step.calls || []).forEach((c, i) => content.push({ type: 'toolCall', id: `call_${n}_${i}`, name: c[0], arguments: c[1] }));
      return { role: 'assistant', content, api: 'fake', provider, model, timestamp: Date.now(),
        stopReason: step.calls ? 'toolUse' : 'stop', responseId: `resp_${n}_${process.pid}`,
        usage: { input: step.input || 100, output: 20, cacheRead: 0, cacheWrite: 0, totalTokens: 120,
          cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0.001 } } };
    },
  };
}
"""

MODEL = 'codex:gpt-test'
DONE = shlex.join([*runner_cmd(), 'done', 'F1', 'F1 a'])  # a real `done`, run in the session's worktree


class Env:
    def __init__(self, tmp: Path):
        self.repo = tmp / 'repo'
        self.repo.mkdir()
        git(self.repo, 'init', '-q', '-b', 'main')
        (self.repo / '.gitignore').write_text('.runner/\nrunner.toml\n', encoding='utf-8')  # rewritten per test
        (self.repo / 'README.md').write_text('test\n', encoding='utf-8')
        (self.repo / 'plan').mkdir()
        (self.repo / 'plan' / 'TODO.md').write_text('# TODO\n\n- [ ] **F1** write a.txt | files: a.txt\n', encoding='utf-8')
        git(self.repo, 'add', '.')
        git(self.repo, 'commit', '-qm', 'start')
        self.fake = tmp / 'fake.mjs'
        self.fake.write_text(FAKE, encoding='utf-8')
        self.script, self.log = tmp / 'script.json', tmp / 'calls.jsonl'
        self.configure('')
        self.wt = R.worktree(1, 'main')
        git(self.wt, 'checkout', '-q', '-B', 'task/F1', 'main')

    def configure(self, run: str, models: str = ''):
        (self.repo / 'runner.toml').write_text(f'[run]\n{run}\n' + (f'\n[models]\n{models}' if models else ''),
                                               encoding='utf-8')
        R.init(self.repo)
        R.C = Config(self.repo)

    def session(self, steps: list, prompt: str = 'do task F1', sid: str = '', resume: bool = False, idle: int = 1,
                stdin: str = '') -> tuple[subprocess.CompletedProcess, str, list[dict]]:
        """Run one harness session to its end; (the process, its session id, the provider calls it made)."""
        self.script.write_text(json.dumps(steps), encoding='utf-8')
        self.log.write_text('', encoding='utf-8')
        sid = sid or f'sid-{time.time_ns()}'
        argv = R.agent_argv(prompt, sid, MODEL, idle, 'slot1', resume, cwd=self.wt)
        env = {k: v for k, v in os.environ.items() if k != 'AGENT_RUNNER_CONFIG'}
        env.update(R.env_vars(R.slot_env(1)), AGENT_RUNNER_HARNESS_PROVIDER=str(self.fake),
                   FAKE_SCRIPT=str(self.script), FAKE_LOG=str(self.log))
        p = subprocess.run(argv, cwd=str(self.wt), env=env, input=stdin, capture_output=True, text=True, timeout=120)
        calls = [json.loads(l) for l in self.log.read_text(encoding='utf-8').splitlines() if l.strip()]
        return p, sid, calls

    def entries(self, sid: str) -> list[dict]:
        return list(R.entries(sid))


def done_mark() -> Path:
    """Slot 1's `finished_mark`, in the test's repository (`finished_mark` itself reads the working directory's)."""
    return R.C.notes('slot1.finished')


def results(entries: list[dict]) -> list[dict]:
    return [b for e in entries if e['type'] == 'user' and isinstance(e['message']['content'], list)
            for b in e['message']['content'] if b.get('type') == 'tool_result']


def test_routing(env: Env):
    argv = R.agent_argv('p', 'sid-x', MODEL, 90, 'slot1', cwd=env.wt)
    check(argv[1].endswith('harness.mjs') and argv[argv.index('--model') + 1] == MODEL and
          argv[argv.index('--session-id') + 1] == 'sid-x' and '--remote-control' not in ' '.join(argv),
          'a model on another provider than claude starts the harness loop, with no Remote Control', argv)
    eq(R.sids(argv), ['sid-x'], 'and its session id reads off its argv as a Claude session\'s does')
    check(R.agent_argv('p', 'sid-y', 'opus', 90, 'slot1', cwd=env.wt)[0] != argv[0], 'a claude model still runs Claude Code')
    env.configure('', models='local = true\n\n[models.providers.acme]\nkind = "openai"\n'
                      'url = "https://api.acme.example/v1"\nkey_env = "ACME_KEY"\n')
    try:
        local = R.agent_argv('p', 'sid-l', 'ollama:llama3:8b', 90, 'slot1', cwd=env.wt)
        check(local[1].endswith('harness.mjs') and 'ollama:llama3:8b' in local and '--provider' not in local,
              'ollama (with [models] local = true) runs in the harness loop, its model whole', local)
        own = R.agent_argv('p', 'sid-a', 'acme:gpt-x', 90, 'slot1', cwd=env.wt)
        given = json.loads(own[own.index('--provider') + 1]) if '--provider' in own else {}
        check(own[1].endswith('harness.mjs') and given.get('url') == 'https://api.acme.example/v1'
              and given.get('key_env') == 'ACME_KEY' and given.get('kind') == 'openai',
              'a [models.providers] provider runs there too, handed its kind, url and key_env (never a key)', own)
    finally:
        env.configure('')
    check(not R.on_harness('acme:gpt-x'), 'with no such provider in the config, acme:gpt-x is no harness model')
    with mock.patch.dict(R.C.run, fix_model='gemini:pro'):
        fix = R.backend().fix_cmd('fix it')
        check(fix[1].endswith('harness.mjs') and '--once' in fix and 'gemini:pro' in fix,
              'a fix session on another provider runs the harness loop once', fix)
        eq(R.backend().fork_flags('sid-x'), [], 'and starts fresh, not as a copy of a Claude session')


def test_finish(env: Env):
    p, sid, calls = env.session([
        {'text': 'working', 'calls': [['write', {'path': 'a.txt', 'content': 'hello\n'}],
                                      ['bash', {'command': 'git add a.txt && git commit -qm "F1 a" && cat a.txt'}]]},
        {'calls': [['bash', {'command': DONE}]]},
        {'calls': [['finish', {'summary': 'wrote a.txt'}]]},
        {'text': 'should never be asked'},
    ], idle=30)
    done_mark().unlink()
    eq(p.returncode, 0, 'a session that calls finish exits 0')
    check(len(calls) == 3, 'finish ends it: no model call after it, though idle is 30 s', calls[-1]['messages'][-1])
    eq((env.wt / 'a.txt').read_text(encoding='utf-8'), 'hello\n', 'write wrote the file in the worktree')
    eq(calls[0]['tools'], ['bash', 'read', 'edit', 'write', 'finish', 'ask', 'publish_page'], 'the session\'s tools')
    eq(calls[0]['provider'], 'codex', 'the provider is the role\'s')
    end = take_end(1, R.C)
    eq((end.get('how'), end.get('tid'), end.get('text')), ('finish', 'F1', 'wrote a.txt'),
       'it left the end mark `run finish` leaves, read as a Claude session\'s')
    es = env.entries(sid)
    eq(R.transcript(sid), str(R.C.notes('harness-sessions') / f'{sid}.jsonl'), 'the transcript is under harness-sessions')
    check([e['type'] for e in es][:2] == ['user', 'assistant'] and es[1]['message']['content'][1]['type'] == 'tool_use'
          and es[1]['message']['stop_reason'] == 'tool_use' and es[0]['sessionId'] == sid,
          'its entries are in Claude\'s shape', es[:2])
    has(results(es)[1]['content'], r'hello', 'a tool result is a tool_result block with the output')
    eq(R.task_spend(sid), (360, 0.003), 'spend reads its usage as a Claude session\'s (3 calls of 120 tokens)')
    has(R.stats(sid), r'3 calls', 'and so does the exit line\'s stats')
    eq(R.last_words(sid), 'working', 'and its last words')


def test_finish_refused(env: Env):
    """B155: the finish tool refuses until `done` (or `done --blocked`) has run for the task."""
    finish = ['finish', {'summary': 'cannot be completed without the code word'}]
    git(env.wt, 'checkout', '-q', '-B', 'task/F1', 'main')  # F1 open again: test_finish's `done` ticked it
    for done, what in ((DONE, '`done`'), (DONE + ' --blocked "needs the code word"', '`done --blocked`')):
        p, sid, calls = env.session([{'calls': [finish]}, {'calls': [['bash', {'command': done}]]},
                                     {'calls': [finish]}, {'text': 'should never be asked'}], idle=30)
        rs = results(env.entries(sid))
        check(rs[0]['is_error'] and 'done F1' in rs[0]['content'] and '--blocked' in rs[0]['content']
              and 'ask tool' in rs[0]['content'], 'finish with no done is refused, naming done and ask', rs[0])
        has(calls[1]['messages'][-1]['text'], r'finish refused', 'and the loop goes on, the model told why')
        check(done_mark().exists() and not rs[1]['is_error'], f'then {what} runs', rs[1])
        eq((p.returncode, len(calls), take_end(1, R.C).get('how')), (0, 3, 'finish'), f'and finish after {what} ends it')
        done_mark().unlink()
        git(env.wt, 'checkout', '-q', '-B', 'task/F1', 'main')
    p, sid, calls = env.session([{'calls': [finish]}, {'calls': [['ask', {'question': 'What is the code word?'}]]},
                                 {'text': 'should never be asked'}], idle=30)
    eq((p.returncode, len(calls), take_end(1, R.C).get('how')), (0, 2, 'ask'), 'ask still ends it with no done')


def test_ask(env: Env):
    p, sid, calls = env.session([{'calls': [['ask', {'question': 'Which of the two? I recommend the first.'}]]},
                                 {'text': 'should never be asked'}], idle=30)
    eq((p.returncode, len(calls)), (0, 1), 'a session that calls ask ends after it')
    end = take_end(1, R.C)
    eq((end.get('how'), end.get('tid')), ('ask', 'F1'), 'with the end mark `run ask` leaves')
    from agent_runner import asks
    with mock.patch.object(asks, 'block_asks', lambda branch: None):
        check(asks.park_asked(1, 'F1', sid, end['text'], 'main'), 'the run parks the task as it parks a Claude one')
    check(bool(git(env.repo, 'branch', '--list', 'asked/F1')) and R.C.notes('F1.ask').exists(),
          'its work kept on asked/F1, its session noted for the answer')
    check(R.move_transcript(sid, env.wt), 'and the answer can resume its session from any slot')
    git(env.wt, 'checkout', '-q', '-B', 'task/F1', 'main')
    git(env.repo, 'branch', '-D', 'asked/F1')
    R.C.notes('F1.ask').unlink()


def test_fallback(env: Env):
    env.configure('', models='fallback = ["sonnet", "gemini:pro-test"]\n')
    try:
        argv = R.agent_argv('p', 'sid-f', MODEL, 90, 'slot1', cwd=env.wt)
        chain = json.loads(argv[argv.index('--fallback') + 1]) if '--fallback' in argv else []
        eq([c['model'] for c in chain], [], 'a claude entry first in the chain: nothing to switch to in-session')
        env.configure('', models='fallback = ["gemini:pro-test", "sonnet"]\n')
        done_mark().touch()  # as a `done` leaves it
        p, sid, calls = env.session([
            {'text': 'working', 'calls': [['bash', {'command': 'echo one'}]]},
            {'cap': 'codex', 'calls': [['finish', {'summary': 'done on gemini'}]]},
        ])
        eq(p.returncode, 0, 'a session whose provider hits its cap goes on and finishes')
        take_end(1, R.C)  # its finish mark, read as the run reads it
        done_mark().unlink()
        eq([(c['provider'], c['n']) for c in calls], [('codex', 0), ('codex', 1), ('gemini', 1)],
           'the cap on codex switches the same session to gemini, which gets the whole conversation so far')
        has(calls[-1]['messages'][-1]['text'], r'one', 'with the tool results the codex turns made')
        eq(R.C.notes(f'{sid}.model').read_text(encoding='utf-8'), 'gemini:pro-test',
           'the session\'s model is noted for the runner')
        from agent_runner import fallback as FB
        check('codex' in FB.capped_now(), 'and codex is noted capped, so new tasks start down the chain')
        from agent_runner import login
        with mock.patch.object(login, 'missing', lambda m, c: ''):
            eq(FB.start_model(MODEL), 'gemini:pro-test', 'a new codex task starts on gemini while codex is capped')
        with mock.patch.object(login, 'missing', lambda m, c: m.partition(':')[0]):
            eq(FB.start_model(MODEL), MODEL, 'but not while gemini has no login')
        has(json.dumps(env.entries(sid)), r'hit its cap', 'the transcript says the session switched')
        R.C.notes('capped.json').unlink()
        eq(FB.start_model(MODEL), MODEL, 'once the cap is gone, new tasks go back to the first')
        env.configure('')
        p, sid, calls = env.session([{'cap': 'codex', 'text': 'never'}])
        eq((p.returncode, [c['provider'] for c in calls]), (1, ['codex']),
           'with no chain a cap ends the session as before')
    finally:
        R.C.notes('capped.json').unlink(missing_ok=True)
        env.configure('')


def test_fence(env: Env):
    outside = env.repo / 'outside.txt'
    p, sid, calls = env.session([
        {'calls': [['bash', {'command': 'git push origin HEAD'}],
                   ['write', {'path': str(outside), 'content': 'no\n'}],
                   ['edit', {'path': str(env.repo / 'README.md'), 'old_string': 'test', 'new_string': 'x'}],
                   ['read', {'path': str(env.repo / 'README.md')}]]},
        {'text': 'done looking'},
    ])
    eq(p.returncode, 0, 'the session ends after its idle time with nothing told')
    rs = results(env.entries(sid))
    check(rs[0]['is_error'] and 'git fence' in rs[0]['content'] and 'git push' in rs[0]['content'],
          'a git push is denied by the git fence', rs[0])
    check(rs[1]['is_error'] and 'git fence' in rs[1]['content'] and not outside.exists(),
          'a write outside the worktree (the main checkout) is denied, and nothing is written', rs[1])
    check(rs[2]['is_error'] and (env.repo / 'README.md').read_text(encoding='utf-8') == 'test\n',
          'and an edit there', rs[2])
    check(not rs[3]['is_error'] and 'test' in rs[3]['content'], 'reading there is allowed', rs[3])
    has(calls[1]['messages'][-4]['text'], r'git fence', 'the model is told why')
    from agent_runner import slots
    with mock.patch.object(slots, 'fence_argv', lambda: [sys.executable, '-c', 'raise SystemExit(3)']):
        p, sid, _ = env.session([{'calls': [['write', {'path': 'b.txt', 'content': 'no\n'}]]}, {'text': 'ok'}])
    rs = results(env.entries(sid))
    check(rs[0]['is_error'] and 'could not run' in rs[0]['content'] and not (env.wt / 'b.txt').exists(),
          'a fence that cannot run denies the call: it never fails open', rs[0])


def test_budget(env: Env):
    env.configure('task_tokens = 1000')
    try:
        p, sid, calls = env.session([{'input': 5000, 'calls': [['bash', {'command': 'echo spent'}]]},
                                     {'text': 'should never be asked'}], idle=30)
    finally:
        env.configure('')
    eq((p.returncode, len(calls)), (0, 1), 'past [run] task_tokens it stops before its next model call')
    has(R.budget_mark('F1'), r'past \[run\] task_tokens \(1,000\)', 'and leaves the budget mark the run parks it by')
    R.C.notes('F1.budget').unlink()
    es = env.entries(sid)
    check(es[-1]['type'] == 'system' and 'task_tokens' in es[-1]['message']['content'], 'its transcript says why')
    check(results(es) and 'spent' in results(es)[0]['content'], 'the tool call of the last turn still ran')


def test_resume(env: Env):
    steps = [{'text': 'first answer'}, {'text': 'second answer'}]
    p, sid, calls = env.session(steps, prompt='the first message')
    eq((p.returncode, len(calls)), (0, 1), 'a session that ends its turn ends after idle')
    p, _, calls = env.session(steps, prompt='the runner resumed this session', sid=sid, resume=True)
    check(p.returncode == 0, 'a resumed session runs', p.stderr)
    eq([(m['role'], m['text']) for m in calls[0]['messages']],
       [('user', 'the first message'), ('assistant', 'first answer'), ('user', 'the runner resumed this session')],
       'it keeps its history, and the new message comes after it')
    eq(R.last_words(sid), 'second answer', 'one transcript for both')
    try:
        R.agent_argv('go on', 'no-such-session', MODEL, 1, 'slot1', True, cwd=env.wt)
        refused = ''
    except FileNotFoundError as e:
        refused = str(e)
    has(refused, r'harness session no-such-session is missing', 'a resume with no transcript is refused, as Pi\'s is')


def test_tell(env: Env):
    p, sid, calls = env.session([{'text': 'one'}, {'text': 'two'}],
                                stdin='\x1b[200~please also\nupdate the docs\x1b[201~\r')
    told = [m['text'] for c in calls for m in c['messages'] if m['role'] == 'user']
    check('please also\nupdate the docs' in told, 'a tell typed into its terminal goes in as a user message, whole', told)


def test_brief(env: Env):
    """F132: a harness loop session has no Agent tool, so its brief hands nothing to a subagent."""
    env.configure('review = true', models='review = "sonnet"\ndocs = "haiku"\n')
    try:
        claude = R.prompt_for('F1', 1, 2, env.wt, 'main', 'opus')
        has(claude, 'subagent_type "docs"', 'a Claude Code session is told to hand docs to the docs subagent')
        has(claude, 'subagent_type "review"', 'and to give the spec review to the review subagent')
        loop = R.prompt_for('F1', 1, 2, env.wt, 'main', MODEL)
        check('subagent_type "docs"' not in loop and 'docs` subagent' not in loop,
              'a harness loop session\'s brief leaves out the docs subagent', loop[-3000:])
        check('Agent tool' not in loop and 'subagent_type' not in loop,
              'and names no Agent tool or subagent for the review', loop[-3000:])
        has(loop, 'review your own work as a fresh reader would', 'its spec review is a self-review')
        check('`review: skipped (small)`' in loop, 'that still ends the commit message with its review line')
        eq(R.prompt_for('F1', 1, 2, env.wt, 'main'), claude, 'no model given reads as Claude Code')
    finally:
        env.configure('')


def test_no_pi(env: Env):
    """F106d: the Pi backend is gone; a file that still names it is told the [models] provider form instead."""
    for run in ('agent = "pi"', 'agent = "/opt/bin/pi"', 'agent = "pi.cmd"', 'backend = "pi"',
                'agent = "my-wrapper"\nbackend = "pi"'):
        try:
            env.configure(run)
        except SystemExit as e:
            has(str(e), r'Pi backend is gone.*\[models\].*"<provider>:<model>".*copilot:<model>',
                f'{run!r} is refused, naming the [models] provider form')
        else:
            check(False, f'{run!r} must be refused')
    with mock.patch.dict(os.environ, AGENT_RUNNER_BACKEND='pi'):
        try:
            env.configure('')
        except SystemExit as e:
            has(str(e), r'AGENT_RUNNER_BACKEND=pi.*Pi backend is gone.*\[models\]', 'so is AGENT_RUNNER_BACKEND=pi')
        else:
            check(False, 'AGENT_RUNNER_BACKEND=pi must be refused')
    for agent in ('copilot', 'C:\\\\tools\\\\copilot.exe'):
        try:
            env.configure(f'agent = "{agent}"')
        except SystemExit as e:
            has(str(e), r'copilot.*is gone.*\[models\] code = "copilot:<model>"',
                f'agent = {agent!r} (the removed Copilot CLI backend) points to the copilot provider')
        else:
            check(False, f'agent = {agent!r} must be refused')
    try:
        env.configure('backend = "claude"')
        check(any('[run] backend is ignored' in w for w in R.C.warnings),
              'an old backend = "claude" is ignored, with a warning', R.C.warnings)
        env.configure('')
        eq((R.C.run['agent'], R.C.run['backend'], R.C.run['model'], R.C.run['fix_model']),
           ('claude', 'claude', 'opus', 'opus'), 'an unconfigured repository runs Claude Code on its defaults')
        flags = R.agent_flags('sid', 'opus', 90)
        check(flags[:2] == ['--session-id', 'sid'] and '--settings' in flags and '--print' not in flags,
              'Claude Code keeps its interactive session flags and Stop hooks')
        eq(R.agent_flags('sid', 'opus', 90, resume=True)[:2], ['--resume', 'sid'], 'and its resume flags')
        env.configure('\n[git]\npush = false')
        p = R.prompt_for('F1', 1, 1, env.wt, 'main', MODEL)
        check('Pushing is off' in p and 'pushes task/' not in p,
              'with [git] push = false a harness session is told pushing is off, not that done pushes')
        check(not any(e.startswith('GIT_CONFIG_') for e in R.slot_env(1)),
              'and gets no no-push git config: the git fence holds every session')
    finally:
        env.configure('')


def main() -> int:
    node = shutil.which('node')
    if not node:
        print('  skip: no node on PATH (all but the brief check)')
    with tempfile.TemporaryDirectory() as tmp:
        env = Env(Path(tmp))
        try:
            if not node:  # F132: the brief check runs no session, so needs no node
                return report([lambda: test_brief(env), lambda: test_no_pi(env)])
            return report([lambda: test_routing(env), lambda: test_finish(env),
                           lambda: test_finish_refused(env), lambda: test_ask(env),
                           lambda: test_fence(env), lambda: test_fallback(env), lambda: test_budget(env), lambda: test_resume(env),
                           lambda: test_tell(env), lambda: test_brief(env), lambda: test_no_pi(env)])
        finally:
            git(env.repo, 'worktree', 'remove', '--force', str(env.wt))


if __name__ == '__main__':
    sys.exit(main())
