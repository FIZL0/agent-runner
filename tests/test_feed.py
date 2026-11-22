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

    def tm(*a, **k):
        opened.append(a)
        return subprocess.CompletedProcess(a, 0, '%9\n' if a[0] == 'new-window' else '', '')

    def new_window_argv():
        return R.shlex.split(next(c for c in opened if c[0] == 'new-window')[-1])

    with mock.patch.object(R.C, 'notes', lambda *a: Path(tdir, *a)), \
            mock.patch.object(R, 'transcript', lambda s: str(tr) if s == sid else None), \
            mock.patch.dict(os.environ, {'CLAUDE_CODE_SESSION_ID': sid}), \
            mock.patch.object(R, 'tmux', tm), mock.patch.object(R, 'control_live', lambda n: None), \
            mock.patch.object(R, 'control_new_session', lambda: 'ar-proj'), \
            mock.patch.object(R.shutil, 'which', lambda x: '/usr/bin/tmux'), \
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

        # the late path (control N --forward --feed-sid): the photo shows only after control --new gave up
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


def test_brief_names_photos():
    print('BUG1: the feed brief hands every photo or file on, never asks about it')
    from agent_runner.guide import RUNNER_BRIEF
    rb = RUNNER_BRIEF.format(cmd='run', repo='r', answer='')
    line = next((ln for ln in rb.split('\n- ') if 'photo' in ln), '')
    check('always hand it on' in line and 'control --new --forward' in line and 'never ask' in line,
          'photos are always handed on with control --new --forward', line)


if __name__ == '__main__':
    raise SystemExit(report([test_feed_sid_keeps_command, test_photo_alone_forwarded, test_brief_names_photos]))
