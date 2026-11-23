"""B91: the runner feed resumes its kept session only while the runner command it may run is the same; a session
kept from before (another command, or none named: from before B91) gives way to a fresh one."""
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


def test_feed_sid_keeps_command():
    print('B91: feed.sid keeps the runner command beside the session id, and a changed command starts afresh')
    R.init(repo())
    f = R.C.notes(R.REMOTE_DIR, R.FEED_SID)
    f.unlink(missing_ok=True)

    sid, resume = R.feed_session('agent-runner')
    check(R.SID_RE.fullmatch(sid) and not resume, 'none kept: a new session', (sid, resume))
    eq(f.read_text(encoding='utf-8'), f'{sid}\nagent-runner\n', 'the id and the command are kept')
    eq(R.feed_sid_file(), sid, 'feed_sid_file still reads just the id')
    eq(R.feed_sid(), sid, 'and so does feed_sid')

    eq(R.feed_session('agent-runner'), (sid, True), 'the same command resumes the same session')

    sid2, resume = R.feed_session('/new/agent-runner')
    check(sid2 != sid and not resume, 'another command starts a fresh session', (sid2, resume))
    eq(f.read_text(encoding='utf-8'), f'{sid2}\n/new/agent-runner\n', 'and keeps the new command')

    f.write_text(SID + '\n', encoding='utf-8')  # from before B91: the feed of a pre-B71 run allowed only ./kit
    eq(R.feed_sid_file(), SID, 'an old one-line feed.sid is still read for hand-offs')
    sid3, resume = R.feed_session('agent-runner')
    check(sid3 != SID and not resume, 'but a session kept without a command is not resumed', (sid3, resume))

    f.write_text('garbage\nagent-runner\n', encoding='utf-8')
    sid4, resume = R.feed_session('agent-runner')
    check(sid4 != 'garbage' and not resume, 'a kept id that is no session id starts afresh', (sid4, resume))

    eq(R.feed_session()[1], False, 'the default command is RUNNER, not the test one')
    eq(f.read_text(encoding='utf-8').splitlines()[1], R.RUNNER, 'so RUNNER is what is kept by default')
    eq(R.feed_session(), (R.feed_sid_file(), True), 'and resumed by default')

    R.feed_forget_session()
    eq(R.feed_sid_parts(), ('', ''), 'a real stop forgets both')


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


def test_brief_names_photos():
    print('BUG1: the feed brief hands every photo or file on, never asks about it')
    from agent_runner.guide import RUNNER_BRIEF
    rb = RUNNER_BRIEF.format(cmd='run', repo='r', answer='')
    line = next((ln for ln in rb.split('\n- ') if 'photo' in ln), '')
    check('always hand it on' in line and 'control --new --forward' in line and 'never ask' in line,
          'photos are always handed on with control --new --forward', line)


if __name__ == '__main__':
    raise SystemExit(report([test_feed_sid_keeps_command, test_photo_alone_forwarded, test_queued_message_forwarded,
                                test_page_ask_skips_feed_b154,
                                test_brief_names_photos]))
