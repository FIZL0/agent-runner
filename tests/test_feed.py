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


if __name__ == '__main__':
    raise SystemExit(report([test_run_ends_old_feed, test_no_feed_starts, test_feed_hand_off_is_gone,
                             test_queued_message, test_control_new_ask_opens_session]))
