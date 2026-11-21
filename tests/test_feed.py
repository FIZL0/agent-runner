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


if __name__ == '__main__':
    raise SystemExit(report([test_feed_sid_keeps_command]))
