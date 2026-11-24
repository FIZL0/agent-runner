"""F176: no kept project chat. A run never resumes a session an earlier run left and opens none of its own; a
prompt opens a control session of its own; a reply goes to its chat; what a restart cut off goes on. Run:
`python3 tests/test_no_kept_chat.py`"""
from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from pathlib import Path
from unittest import mock

from _check import check, eq, git, report

from agent_runner import control as K, control_reopen as CR, feed as F, runner as R, slots as S, ui_model as U


def fake_repo() -> Path:
    """A repository whose folder is named as the friend's clone was (every name comes from ROOT.name)."""
    d = Path(tempfile.mkdtemp(prefix='agent-runner-f176-')) / 'clay-coordinator'
    d.mkdir()
    git(d, 'init', '-q', '-b', 'main')
    (d / '.gitignore').write_text('.runner/\n')
    (d / 'plan').mkdir()
    (d / 'plan/TODO.md').write_text('# TODO\n\n- [ ] **F1** do it | files: a.py\n', encoding='utf-8')
    (d / 'plan/DONE.md').write_text('# DONE\n', encoding='utf-8')
    git(d, 'add', '-A')
    git(d, 'commit', '-qm', 'start')
    R.init(d)
    R.C.notes().mkdir(parents=True, exist_ok=True)
    return d


def events(kind: str, ago: float) -> None:
    t = time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(time.time() - ago))
    R.C.notes('events.jsonl').write_text(json.dumps({'time': t, 'kind': kind}) + '\n', encoding='utf-8')


def test_second_run_starts_fresh() -> None:
    print('a second run picks up no session of the first: not c1, not the feed, with and without Remote Control')
    for remote in (False, True):
        fake_repo()
        old, feed = str(uuid.uuid4()), str(uuid.uuid4())
        R.C.notes('control.sid').write_text(old + '\n', encoding='utf-8')
        R.C.notes('control1.pid').write_text(f'999999999 {old}', encoding='utf-8')
        os.utime(R.C.notes('control1.pid'), (1, 1))  # live at the last shutdown, as an older runner's c1 was
        R.C.notes('remote').mkdir()
        R.C.notes('remote', 'feed.sid').write_text(f'{feed}\n{K.control_cmd()}\n', encoding='utf-8')
        events(R.EV_RUN_UP, 24 * 3600)  # the run was killed a day ago: it never forgot its feed
        opened = []
        with mock.patch.object(K, 'remote_on', lambda: remote), \
                mock.patch.object(K, 'transcript', lambda s: '/x.jsonl'), \
                mock.patch.object(K, 'entries', lambda s, skip_bad=False: []), \
                mock.patch.object(R.Claude, 'find_transcript', lambda self, s: '/x.jsonl'), \
                mock.patch.object(CR, 'boot_time', lambda: time.time()), \
                mock.patch.object(K, 'hidden_control', lambda n, cmd, wait=None: opened.append(cmd) or (1, '')):
            K.start_control()
            eq(opened, [], f'remote {remote}: a run start opens and resumes no chat')
            check(not R.C.notes('control.sid').exists() and not R.C.notes('control1.pid').exists(),
                  'the kept id is gone')
            sids = {K.control_open(n)[0] for n in (1, 2, 2)}
            eq((len(sids), old in sids), (3, False), 'every control session is a new id')
            eq(F.feed_sid_file(), '', "B195: an older version's feed session is forgotten")


def test_restart_keeps_what_runs() -> None:
    print("a restart mid-task: the running slots go on, and a chat a shutdown cut off is reopened")
    fake_repo()
    R.C.notes('remote').mkdir()
    feed, cut = str(uuid.uuid4()), str(uuid.uuid4())
    R.C.notes('remote', 'feed.sid').write_text(f'{feed}\n{K.control_cmd()}\n', encoding='utf-8')
    R.C.notes('control3.pid').write_text(f'999999999 {cut}', encoding='utf-8')
    os.utime(R.C.notes('control3.pid'), (1, 1))
    events(R.EV_RUN_UP, 30)
    opened = []
    with mock.patch.object(K, 'transcript', lambda s: '/x.jsonl'), \
            mock.patch.object(K, 'entries', lambda s, skip_bad=False: []), \
            mock.patch.object(CR, 'boot_time', lambda: time.time()), \
            mock.patch.object(CR, 'reopen_control', lambda n, sid: opened.append((n, sid)) or 'here'):
        K.start_control()
    eq(opened, [(3, cut)], 'the cut-off chat is reopened')
    eq(F.feed_sid_file(), '', "B195: an older version's feed session is forgotten over a restart too")

    class Mux:
        def panes(self):
            return {'s1': ('%1', os.getpid()), 'c3': ('%2', os.getpid())}

        def session_id(self, pid):
            return 'slot-sid'
    wt = Path(tempfile.mkdtemp(prefix='agent-runner-f176-slots-'))
    git(R.ROOT, 'worktree', 'add', '-q', '-b', 'task/F1', str(wt / 's1'))
    with mock.patch.object(S, 'MUX', Mux()), mock.patch.object(S, 'SLOTS_DIR', wt), \
            mock.patch.object(S, 'tasks', lambda branch: [('F1', 'a.py')]):
        got = S.adopt('main')
    eq({n: (s[0], s[1], t[0]) for n, (s, t) in got.items()}, {1: (os.getpid(), 'slot-sid', 'F1')},
       'the running slot is adopted, and only it')


def test_prompts_and_replies() -> None:
    print('a prompt opens its own chat, a reply stays in its chat, and no chat is special')
    fake_repo()
    ran, typed = [], []
    inbox = Path(tempfile.mkdtemp(prefix='agent-runner-f176-inbox-')) / 'c2.in'
    inbox.touch()  # on Windows a session with no inbox file takes no typing
    with mock.patch.object(U, 'RUN', [lambda argv: (ran.append(argv), (0, f'control {len(ran) + 1} is starting'))[1]]), \
            mock.patch.object(U, 'hidden_inbox', lambda n: inbox if n == 'c2' else None), \
            mock.patch.object(S, 'send_fifo', lambda p, t: typed.append((p.name, t)) or True):
        names = [U.act('chat_to', text=t)['name'] for t in ('one', 'two')]
        eq(names, ['c2', 'c3'], 'each prompt is a chat of its own')
        U.act('chat', text='three')
        check(all(a[:2] == ['control', '--new'] for a in ran) and len(ran) == 3, 'through control --new', ran)
        U.act('chat_to', text='a reply', to='c2')
    eq((typed, len(ran)), ([('c2.in', 'a reply')], 3), 'a reply is typed into its chat and opens none')
    eq(K.control_number(), K.FIRST_CONTROL, "numbers start past the kept session's 1")
    with mock.patch.object(K, 'control_live', lambda n: 4242), mock.patch.object(K.plat, 'terminate', lambda p: None):
        R.C.notes('control1.pid').write_text('4242 sid', encoding='utf-8')
        eq(K.control_live_numbers(), [1], "an older runner's live c1 is listed with the rest")
        eq(K.close_from_tui(1)['ok'], True, 'and can be closed')
    check('opens with the summary' not in K.control_brief(), 'the brief names no chat that opens with the summary')


def test_reopen_is_its_own() -> None:
    print("control 1 --reopen (Resume on an older runner's c1) never resumes another number's chat")
    from agent_runner import cmds
    fake_repo()
    got = []

    def opened(n, **k):
        got.append((n, k['reopen']))
        raise SystemExit
    with mock.patch.object(cmds, 'control_open', opened), mock.patch.object(cmds, 'init', lambda: None), \
            mock.patch.object(cmds, 'free_control_number', lambda: 2):
        for argv in (['1', '--reopen'], ['1']):
            try:
                cmds.cmd_control(argv)
            except SystemExit:
                pass
    eq(got, [(1, True), (2, False)], '--reopen keeps its number; a plain control 1 is a new session')


def test_control_server_pre_creates_none() -> None:
    print('the control server pre-creates no session: Claude Code adopts that one again in every later run')
    fake_repo()
    with mock.patch.object(K, 'server_help', lambda exe: '--settings <file>\n--[no-]create-session-in-dir'):
        check(K.NO_PRECREATE in K.control_server_argv(), 'asked not to', K.control_server_argv())
    with mock.patch.object(K, 'server_help', lambda exe: '--settings <file>'):
        check(K.NO_PRECREATE not in K.control_server_argv(), 'an older Claude Code does not know the flag')


if __name__ == '__main__':
    raise SystemExit(report([test_second_run_starts_fresh, test_restart_keeps_what_runs, test_prompts_and_replies,
                             test_reopen_is_its_own,
                             test_control_server_pre_creates_none]))
