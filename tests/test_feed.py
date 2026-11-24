"""B195: a run starts no board and no runner feed, and ends one an older version left; `control --new --ask` opens a
session with its message and files, and looks nowhere in a feed (C39)."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from _check import check, eq, git, report

os.environ.pop('CLAUDE_CODE_SESSION_ID', None)  # not the session running this

from agent_runner import runner as R  # noqa: E402

SID = '11111111-2222-3333-4444-555555555555'


def repo() -> Path:
    d = Path(tempfile.mkdtemp(prefix='agent-runner-feed-'))
    git(d, 'init', '-q')
    (d / '.gitignore').write_text('.runner/\n')
    (d / 'README.md').write_text('demo\n')
    git(d, 'add', '-A')
    git(d, 'commit', '-qm', 'start')
    return d


def test_run_ends_old_feed():
    print("B195: a run's start ends the feed and board an older version left, also one started by this very run "
          'before it restarted in place, and forgets its session; a pid that is no board is left alone')
    import subprocess
    import sys
    import threading
    import time
    R.init(repo())
    me = os.getpid()
    for over in ('this run', 'an earlier run'):
        feed = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
        board = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)', 'since', '--board', '--feed'])
        for p in (feed, board):  # reaped when they end: a zombie counts as ended anyway
            threading.Thread(target=p.wait, daemon=True).start()
        gone = subprocess.Popen([sys.executable, '-c', 'pass'])
        gone.wait()
        try:
            R.rc_record('feed', 'demo · runner', feed.pid, me if over == 'this run' else gone.pid, SID)
            R.C.notes(R.REMOTE_DIR, R.FEED_SID).write_text(f'{SID}\nagent-runner\n', encoding='utf-8')
            R.C.notes('board.live').write_text(str(board.pid), encoding='utf-8')
            for f in ('board.log', 'board.job', 'no-board'):
                R.C.notes(f).write_text('{}', encoding='utf-8')
            R.feed.BOARD_WAIT, was = 1, R.feed.BOARD_WAIT
            try:
                R.rc_sweep_start()
                end = time.monotonic() + 30
                while any(t.name == 'remote-sweep' for t in threading.enumerate()) and time.monotonic() < end:
                    time.sleep(0.05)
            finally:
                R.feed.BOARD_WAIT = was
            check(not R.plat.alive(feed.pid), f"{over}: the feed is ended (its teardown archives its entry)")
            if sys.platform.startswith('linux'):  # macOS: no command line to tell; it ends once its feed has
                check(not R.plat.alive(board.pid), f'{over}: the board is ended')
            eq([r for r in R.rc_records() if r['kind'] == 'feed'], [], f'{over}: its record is dropped')
            eq(R.feed_sid_parts(), ('', ''), f'{over}: its session is forgotten')
            eq(sorted(f.name for f in R.C.notes().glob('*board*')), [], f'{over}: its files are gone')
        finally:
            for p in (feed, board):
                if p.poll() is None:
                    p.kill()
    stranger = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    try:
        R.C.notes('board.live').write_text(str(stranger.pid), encoding='utf-8')  # its pid reused after a reboot
        R.feed.end_board()
        check(R.plat.alive(stranger.pid), 'a process that is no board is not touched')
        check(not R.C.notes('board.live').exists(), 'the stale marker goes')
    finally:
        stranger.kill()
        stranger.wait()


def test_no_feed_starts():
    print('B195: nothing starts a board or a feed, on any OS; control sessions start no watch and name no feed')
    import contextlib
    import io
    from unittest import mock
    from agent_runner import cmds, control as K, guide, loop
    R.init(repo())
    for gone in ('start_board', 'keep_board', 'board_feed', 'feed_argv'):
        check(not hasattr(R, gone) and not hasattr(loop, gone), f'{gone} is gone')
    started = []
    for win in (False, True):
        with mock.patch.object(K, 'remote_on', lambda: True), mock.patch.object(R.plat, 'WINDOWS', win), \
                mock.patch.object(K, 'hidden_shim', lambda *a, **k: started.append(a) or (1, '')):
            K.start_control()
            brief = K.control_brief()
        check('runner feed' not in brief and 'needs-you watch' not in brief and '--needs-you' not in brief
              and 'start no watch on them unasked' in brief, f'the brief (Windows {win}) starts no watch', brief)
        check('guide watch' in brief, 'and "notify me when" is still a guide page')
    eq(started, [], 'a run start opens no hidden session of its own')
    page = guide.CONTROL_TOPICS['watch']
    check('"notify me when X"' in page and 'since --follow' in page and '--needs-you' in page,
          '"notify me when" works on ask')
    for flag in ('--board', '--feed'):
        with contextlib.redirect_stderr(io.StringIO()):
            try:
                rc = cmds.cmd_since([flag])
            except SystemExit as e:
                rc = e.code
        eq(rc, 2, f'since {flag} is gone')


def test_feed_hand_off_is_gone():
    print('C39: the runner feed\'s hand-off (--forward, --runner, --from-feed, --feed-sid, feed_wait, feed_take) is gone')
    import contextlib
    import io
    from agent_runner import cmds
    for gone in ('feed_wait', 'feed_take', 'feed_latest', 'feed_scan', 'feed_files', 'feed_sid', 'feed_pending',
                 'control_late_files', 'forward_late', 'forward_late_files', 'FORWARD_FLAG', 'FEED_WAIT'):
        check(not hasattr(R, gone) and not hasattr(R.feed, gone), f'{gone} is gone')
    for flag in ('--forward', '--runner', '--from-feed', '--feed-sid'):
        with contextlib.redirect_stderr(io.StringIO()):
            try:
                rc = cmds.cmd_control(['--new', flag, 'x'] if flag in ('--from-feed', '--feed-sid') else ['--new', flag])
            except SystemExit as e:
                rc = e.code
        eq(rc, 2, f'control {flag} is gone')


def test_queued_message():
    print('B106: a message sent while a session was busy (a queued_command attachment) reads as a person message')
    queued = lambda prompt, mode='prompt': {
        'type': 'attachment', 'uuid': 'q1', 'version': '2.1.303',
        'attachment': {'type': 'queued_command', 'prompt': prompt, 'commandMode': mode,
                       'origin': {'kind': 'human'}, 'source_uuid': 'src-q1'}}
    got = R.feed.queued_message(queued('hello there'))
    check(got is not None and got['type'] == 'user' and got['message']['content'] == 'hello there',
          'a queued prompt comes back in a user entry\'s shape', got)
    eq(R.feed.queued_message(queued('<task-notification>x</task-notification>', 'task-notification')), None,
       'a queued task notification is not a person message')


def test_control_new_ask_opens_session():
    print('B154, C39: control --new --ask (run page, TUI: --no-feed) opens control N at once with its message and files')
    import contextlib
    import io
    from unittest import mock
    from agent_runner import cmds, feed as F
    R.init(repo())
    opened = []

    def run(*argv):
        opened.clear()
        with mock.patch.object(F, 'control_new_hidden', lambda n, cmd, name, wait=0: opened.append((cmd, wait)) or 0), \
                mock.patch.object(F.plat, 'WINDOWS', False), mock.patch.object(F, 'control_live', lambda n: None), \
                contextlib.redirect_stdout(io.StringIO()):
            cmds.cmd_control(['--new', *argv])
        return opened[0][0]
    shot = os.path.join(tempfile.mkdtemp(prefix='agent-runner-feed-shot-'), 'a.png')
    for flags in (['--no-feed'], []):
        cmd = run('--no-wait', '--ask', 'what needs me?', '--file', shot, *flags)
        check('--feed-sid' not in cmd and '--forward' not in cmd, 'control N waits for nothing', cmd)
        eq(open(cmd[cmd.index('--ask-file') + 1], encoding='utf-8').read(), 'what needs me?',
           'its first message is the ask')
        eq(cmd[cmd.index('--file') + 1], str(Path(shot).resolve()), 'and its file goes with it')
        eq(opened[0][1], -1, '--no-wait still holds')


ONCE = r"""
import fs from 'node:fs';
export default function ({ provider, model }) {
  return { async call(context) {
    fs.appendFileSync(process.env.FAKE_LOG, JSON.stringify({ provider, model, tools: context.tools.map((t) => t.name),
      system: context.systemPrompt, said: context.messages[0].content }) + '\n');
    const bad = process.env.FAKE_FAIL, n = context.messages.filter((m) => m.role === 'assistant').length;
    const content = n ? [{ type: 'text', text: 'published: https://claude.ai/artifact/made-up' }]
      : [{ type: 'toolCall', id: 'c1', name: 'bash', arguments: { command: 'touch ran-bash' } }];
    return { role: 'assistant', content: bad ? [] : content, api: 'fake', provider, model, timestamp: Date.now(),
      stopReason: bad ? 'error' : n ? 'stop' : 'toolUse', errorMessage: bad ? '401 unauthorized' : undefined,
      usage: { input: 1, output: 1, cacheRead: 0, cacheWrite: 0 } };
  } };
}
"""


def test_feed_on_a_provider():
    print("F406e: a feed model of another provider: its one-shot runs on the harness loop, the local copy is the answer, "
          'also with no claude on PATH')
    import contextlib
    import io
    import json
    import shutil
    from unittest import mock
    from agent_runner import cli, done, feed, page_copy as PC
    d = repo()
    toml = '[models]\nfeed = "codex:gpt-test"\n\n[run]\nagent = "/nonexistent/claude-f406e"\n'
    (d / 'runner.toml').write_text(toml)
    R.init(d)
    page = d / 'options.html'
    page.write_text('<h1>options</h1>')
    fake, log = d / 'fake.mjs', d / 'calls.jsonl'
    fake.write_text(ONCE)
    env = {'AGENT_RUNNER_HARNESS_PROVIDER': str(fake), 'FAKE_LOG': str(log), 'AGENT_RUNNER_SLOT': '1',
           'AGENT_RUNNER_REPO': str(d)}
    said: list = []
    with mock.patch.dict(os.environ, env), mock.patch.object(PC, 'C', R.C), mock.patch.object(PC, 'log', said.append):
        if shutil.which('node'):
            eq(PC.page_copy_publish(page, ''), '', 'no claude.ai page, whatever the model answers')
            call = [json.loads(x) for x in log.read_text().splitlines()]
            eq((call[0]['provider'], call[0]['model'], call[0]['tools']), ('codex', 'gpt-test', ['read']),
               'the one-shot runs on the feed model with read only')
            check(str(page) in call[0]['said'], 'and is handed the page', call[0]['said'])
            check('finish' not in call[0]['system'], 'its system text names no slot tools')
            check(len(call) == 2 and not (d / 'ran-bash').exists(), 'a tool it was not given does not run')
            eq(list(R.C.notes().glob('once-*')), [], 'its prompt file goes')
            check('made-up' in feed.harness_once('codex:gpt-test', 'hi', d, 60)[0], 'harness_once gives its last words')
            with mock.patch.dict(os.environ, FAKE_FAIL='1'):
                got, why = feed.harness_once('codex:gpt-test', 'hi', d, 60)
                check(not got and '401 unauthorized' in why, 'or why it failed', why)
        with mock.patch.object(feed.HARNESS, 'argv', lambda *a: ['/nonexistent/node']):
            eq(PC.page_copy_publish(page, ''), '', 'no node either: still no error')
            PC.PAGE_COPY_FAILS[0], PC.PAGE_COPY_OFF[0] = 0, ''
            key = d / 'key'
            for _ in range(PC.PAGE_COPY_FAIL_MAX + 1):
                key.write_text('k')
                PC.PAGE_COPY_BUSY.acquire()
                PC.page_copy_job(page, '', key, PC.page_copy_publish)
            eq((PC.PAGE_COPY_FAILS[0], PC.PAGE_COPY_OFF[0], key.read_text()), (0, '', 'k'),
               'the run page copy counts it as no failure')
            eq(PC.publish_page('K1', page)[1], '/concept/K1', 'a concept page: the run page has it')
        # a claude feed model, and no claude on this machine
        d2 = repo()  # its own: the settings are kept per folder
        (d2 / 'runner.toml').write_text(toml.replace('codex:gpt-test', 'haiku'))
        R.init(d2)
        check(not feed.feed_on_harness(), 'a claude feed model')
        with mock.patch.object(PC, 'C', R.C):
            dest, url = PC.publish_page('K2', page)
            eq((dest.read_text(), url, PC.concept_url('K2')), ('<h1>options</h1>', '/concept/K2', '/concept/K2'),
               'no claude on PATH: the local copy is the answer, recorded for done')
            PC.publish_page('K2', page, publish=lambda f, u: check(u == '', 'never handed on as a URL to update') or '')
            PC.concept_url_file('K3').write_text('https://claude.ai/artifact/old')
            eq(PC.publish_page('K3', page, publish=lambda f, u: '')[1], '', 'a one-shot that failed is still a failure')
        with mock.patch.dict(os.environ, AGENT_RUNNER_REPO=str(d2)), contextlib.redirect_stdout(io.StringIO()) as out:
            was = os.getcwd()
            os.chdir(d2)
            try:
                rc = cli.main(['publish-page', str(page), '--id', 'K4'])
            finally:
                os.chdir(was)
                PC.C = R.C
        check(rc == 0 and 'no claude.ai page' in out.getvalue(), 'publish-page goes through and says so', out.getvalue())
    from agent_runner import ui_model as Q
    row = ('CONCEPT', 'F9', 'K2', 'waiting for your OK on /concept/K2', '/concept/K2', 'a title', False, '')
    import datetime as dt
    concepts = Q.needs_rows([row], dt.datetime.now())[1]
    check(len(concepts) == 1 and concepts[0]['url'] == '' and concepts[0]['copy'].endswith('K2.html'),
          'the run page and the TUI open the local copy, with no bare link', concepts)
    args = mock.Mock(id='K2', artifact='/concept/K2', blocked=None)
    eq(done.artifact_refusal(args), None, 'done takes it as the concept\'s page')
    args.artifact = '/concept/K9'
    check(done.artifact_refusal(args), 'but not another task\'s')


if __name__ == '__main__':
    raise SystemExit(report([test_feed_on_a_provider, test_run_ends_old_feed, test_no_feed_starts, test_feed_hand_off_is_gone,
                             test_queued_message, test_control_new_ask_opens_session]))
