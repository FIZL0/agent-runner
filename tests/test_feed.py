"""B195: a run starts no board and no runner feed, and ends one an older version left; the hand-off of a feed's
message to a control session."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from _check import check, eq, git, report

os.environ.pop('CLAUDE_CODE_SESSION_ID', None)  # feed_sid reads the calling session first: not the one running this

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


def test_photo_alone_forwarded():
    print('BUG1: a photo with no words in the feed transcript is handed on with its file, never as a lost message')
    import contextlib
    import io
    import json
    import subprocess
    from unittest import mock
    sid = '12345678-1234-1234-1234-123456789abc'
    tdir = tempfile.mkdtemp(prefix='agent-runner-feed-photo-')
    tr = Path(tdir, 'feed.jsonl')
    photo = lambda uid: {'type': 'user', 'uuid': uid, 'origin': {'kind': 'human'},
                         'message': {'content': [{'type': 'image', 'source': {'type': 'base64', 'data': ''}}]}}
    hum = lambda text, uid: {'type': 'user', 'uuid': uid, 'origin': {'kind': 'human'},
                             'message': {'content': [{'type': 'text', 'text': text}]}}
    pics = lambda *p: {'type': 'attachment', 'attachment': {'type': 'inlined_image_paths', 'paths': list(p)}}
    meta = lambda p: {'type': 'user', 'isMeta': True, 'message': {'content': [
        {'type': 'text', 'text': f'[Image: source: {p}]'}]}}
    call = lambda cmd: {'type': 'assistant', 'message': {'content': [
        {'type': 'tool_use', 'name': 'Bash', 'input': {'command': cmd}}]}}
    write = lambda *es: tr.write_text(''.join(json.dumps(e) + '\n' for e in es))
    opened = []

    def new_window_argv():
        return opened[-1]

    with mock.patch.object(R.C, 'notes', lambda *a: Path(tdir, *a)), \
            mock.patch.object(R, 'transcript', lambda s: str(tr) if s == sid else None), \
            mock.patch.dict(os.environ, {'CLAUDE_CODE_SESSION_ID': sid}), \
            mock.patch.object(R, 'control_live', lambda n: None), \
            mock.patch.object(R, 'control_new_hidden', lambda n, cmd, name, wait=0: opened.append(cmd) or 0), \
            mock.patch.object(R.plat, 'WINDOWS', False), mock.patch.object(R, 'remote_on', lambda: False), \
            mock.patch.object(R, 'FEED_WAIT', 0.3):
        write(hum('status', 'u1'), call('run status'), photo('u2'), pics('/u/shot.png'),
              call('run control --new --forward'))
        with contextlib.redirect_stdout(io.StringIO()):
            rc = R.control_new(9, forward=True)
        argv = new_window_argv()
        check(rc == 0 and '/u/shot.png' in argv and '--feed-sid' not in argv and '--forward' not in argv,
              'the photo is handed on as a file, with nothing left to wait for', argv)
        check('--ask-file' not in argv and '--ask' not in argv, 'and no lost-message note or other ask', argv)
        check(not any(R.feed_lost_note() in a for a in argv), 'never feed_lost_note', argv)
        eq(R.feed_pending(sid)[2], False, 'the photo is marked handed on')

        # Claude Code 2.1.329's form (an isMeta '[Image: source: …]' entry), and the feed ran a command of its
        # own about the photo first: still handed on, not left as a message that never showed
        opened.clear()
        write(photo('u3'), meta('/tmp/claude/images/1.png'), call('ls /tmp/claude/images'),
              call('run control --new --forward'))
        with contextlib.redirect_stdout(io.StringIO()):
            R.control_new(9, forward=True)
        argv = new_window_argv()
        check('/tmp/claude/images/1.png' in argv and '--ask-file' not in argv,
              'a photo the feed looked at first is handed on with its file', argv)

        # the late path (control N --forward --feed-sid): the photo's saved path shows only after control --new
        # gave up, so control N waits for it instead of a drift note after FEED_WAIT
        opened.clear()
        write(photo('u4'), call('run control --new --forward'))
        with contextlib.redirect_stdout(io.StringIO()):
            R.control_new(9, forward=True)
        argv = new_window_argv()
        check('--forward' in argv and argv[argv.index('--feed-sid') + 1] == sid and '--ask-file' not in argv,
              'a photo with no saved path yet is left for control N to wait for', argv)
        eq(R.feed_pending(sid)[2], True, 'and is not marked handed on yet')
        write(photo('u4'), pics('/u/late.png'), call('run control --new --forward'))
        with contextlib.redirect_stdout(io.StringIO()):
            got = R.forward_late_files(9, sid, wait=1)
        eq(got, ('', ['/u/late.png'], True), 'control N takes a late photo with its file and no note')

        # a photo whose saved path never shows: said so, not lost
        write(photo('u5'), call('run control --new --forward'))
        with contextlib.redirect_stdout(io.StringIO()):
            got = R.forward_late_files(9, sid, wait=0.3)
        check(got[0] != R.feed_lost_note() and 'image' in got[0] and not got[1],
              'an image with no saved path gets the drift note, not feed_lost_note', got)

        # no message at all: the lost note still
        write(hum('status', 'u1'), call('run status'))
        R.C.notes(R.REMOTE_DIR, R.FEED_FORWARDED).unlink(missing_ok=True)
        with contextlib.redirect_stdout(io.StringIO()):
            got = R.forward_late_files(9, sid, wait=0.3)
        eq(got, (R.feed_lost_note(), [], True), 'neither words nor files: feed_lost_note')


def test_queued_message_forwarded():
    print('B106: a message sent while the feed was busy (a queued_command attachment) is handed on word for word')
    import contextlib
    import io
    import json
    import subprocess
    from unittest import mock
    sid = '12345678-1234-1234-1234-123456789abd'
    tdir = tempfile.mkdtemp(prefix='agent-runner-feed-queued-')
    tr = Path(tdir, 'feed.jsonl')
    hum = lambda text, uid: {'type': 'user', 'uuid': uid, 'origin': {'kind': 'human'},
                             'message': {'content': [{'type': 'text', 'text': text}]}}
    queued = lambda prompt, uid, mode='prompt': {
        'type': 'attachment', 'uuid': uid, 'version': '2.1.303',
        'attachment': {'type': 'queued_command', 'prompt': prompt, 'commandMode': mode,
                       'origin': {'kind': 'human'}, 'source_uuid': 'src-' + uid}}
    monitor = {'type': 'attachment', 'uuid': 'm1', 'attachment': {
        'type': 'queued_command', 'commandMode': 'task-notification',
        'prompt': '<task-notification>\n<status>completed</status>\n</task-notification>'}}
    call = lambda cmd: {'type': 'assistant', 'message': {'content': [
        {'type': 'tool_use', 'name': 'Bash', 'input': {'command': cmd}}]}}
    result = {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': 't', 'content': 'ok'}]}}
    write = lambda *es: tr.write_text(''.join(json.dumps(e) + '\n' for e in es))
    opened = []
    said = 'can you connect and make one\nwith "quotes" and $(no shell)'

    with mock.patch.object(R.C, 'notes', lambda *a: Path(tdir, *a)), \
            mock.patch.object(R, 'transcript', lambda s: str(tr) if s == sid else None), \
            mock.patch.dict(os.environ, {'CLAUDE_CODE_SESSION_ID': sid}), \
            mock.patch.object(R, 'control_live', lambda n: None), \
            mock.patch.object(R, 'control_new_hidden', lambda n, cmd, name, wait=0: opened.append(cmd) or 0), \
            mock.patch.object(R.plat, 'WINDOWS', False), mock.patch.object(R, 'remote_on', lambda: False), \
            mock.patch.object(R, 'FEED_WAIT', 0.3):
        eq(R.queued_message(monitor), None, 'a queued task notification is not a person message')
        # the feed was handling a Monitor event (its own tool calls) when the person wrote
        write(hum('status', 'u1'), call('run status'), monitor, call('run since --wait'), result,
              queued(said, 'q1'), call('run control --new --forward'))
        eq(R.feed_pending(sid), (said, 'q1', True), 'feed_pending takes the queued message, ready to hand on')
        eq(R.feed_latest(sid)[3], said, 'and feed_latest reads its words too')
        with contextlib.redirect_stdout(io.StringIO()):
            rc = R.control_new(9, forward=True)
        argv = opened[-1]
        check(rc == 0 and '--ask-file' in argv, 'control --new --forward hands it on in a file', argv)
        ask = Path(argv[argv.index('--ask-file') + 1])
        eq(ask.read_text(encoding='utf-8'), said, 'word for word')
        check('--feed-sid' not in argv and '--forward' not in argv, 'with nothing left to wait for', argv)
        check(not any(R.feed_lost_note() in a for a in argv), 'never feed_lost_note', argv)
        eq(R.feed_pending(sid)[2], False, 'and it is marked handed on')
        log = Path(tdir, R.REMOTE_DIR, R.FEED_LOG).read_text(encoding='utf-8')
        check('control --new --forward: sid ' + sid in log and '"can you connect and make one' in log
              and 'found' in log, 'the take is logged to handoff.log', log)

        # in transcript order: a later type=user message wins over an earlier queued one, and the other way round
        write(queued('older queued words here', 'q2'), hum('newer typed words here please', 'u3'))
        eq(R.feed_pending(sid)[:2], ('newer typed words here please', 'u3'), 'a later typed message is the latest')
        write(hum('older typed words here', 'u4'), queued([{'type': 'text', 'text': 'look [Image #1]'},
                                                         {'type': 'image', 'source': {'type': 'base64'}}], 'q3'))
        eq(R.feed_pending(sid)[:2], ('look [Image #1]', 'q3'), 'a later queued message with an image is the latest')
        eq(R.feed_latest(sid)[1], 1, 'and its image counts as shown')

        # control N's late wait logs its take too, found or not
        write(hum('status', 'u1'), call('run status'))
        R.C.notes(R.REMOTE_DIR, R.FEED_FORWARDED).unlink(missing_ok=True)
        with contextlib.redirect_stdout(io.StringIO()):
            R.forward_late_files(9, sid, wait=0.3)
        log = Path(tdir, R.REMOTE_DIR, R.FEED_LOG).read_text(encoding='utf-8')
        check('control N --forward --feed-sid: sid ' + sid in log and 'NOT found' in log,
              'a message that never showed is logged as NOT found', log)


def test_page_ask_skips_feed_b154():
    print('B154: an ask from the run page or the TUI (--no-feed) starts control N at once; a feed hand-off still waits')
    import contextlib
    import io
    from unittest import mock
    from agent_runner import cmds, feed as F
    R.init(repo())
    opened, looked = [], []

    def run(*argv):
        opened.clear(), looked.clear()
        with mock.patch.object(F, 'control_new_hidden', lambda n, cmd, name, wait=0: opened.append((cmd, wait)) or 0), \
                mock.patch.object(F.plat, 'WINDOWS', False), mock.patch.object(F, 'feed_sid', lambda: SID), \
                mock.patch.object(F, 'feed_wait', lambda *a, **k: (looked.append(a), (False, [], 0, ''))[1]), \
                contextlib.redirect_stdout(io.StringIO()):
            cmds.cmd_control(['--new', *argv])
        return opened[0][0]
    cmd = run('--no-wait', '--ask', 'what needs me?', '--no-feed')
    check(not looked and '--feed-sid' not in cmd, 'no look in the feed, and control N waits for nothing', cmd)
    ask = open(cmd[cmd.index('--ask-file') + 1], encoding='utf-8').read() if '--ask-file' in cmd else cmd[cmd.index('--ask') + 1]
    eq(ask.strip(), 'what needs me?', 'its first message is the ask, with no images note')
    eq(opened[0][1], -1, '--no-wait still holds')
    cmd = run('--ask', 'handed on by the feed')
    check(looked and cmd[cmd.index('--feed-sid') + 1] == SID, 'a feed hand-off still looks, and control N waits', cmd)


if __name__ == '__main__':
    raise SystemExit(report([test_run_ends_old_feed, test_no_feed_starts, test_photo_alone_forwarded,
                             test_queued_message_forwarded, test_page_ask_skips_feed_b154]))
