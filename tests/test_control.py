"""Control sessions: a handed-on ask as c1, the brief, take back, sessions one/each, reopening after a
shutdown. (C26 dropped B94's tests of the background tmux session, which is gone.)"""
from __future__ import annotations

import re
import subprocess
import tempfile
import types
import uuid
from pathlib import Path
from unittest import mock

from _check import check, eq, git, report

from agent_runner import control as K  # noqa: E402


def test_handed_ask_as_c1_starts_fresh():
    print('B96: control --new --ask that gets number 1 starts fresh, named; the kept c1 session stays kept')
    from agent_runner import runner as R
    d = Path(tempfile.mkdtemp(prefix='agent-runner-control-'))
    git(d, 'init', '-q')
    (d / '.gitignore').write_text('.runner/\n')
    (d / 'README.md').write_text('demo\n')
    git(d, 'add', '-A')
    git(d, 'commit', '-qm', 'start')
    R.init(d)
    kept = str(uuid.uuid4())
    sidf = R.C.notes('control.sid')
    sidf.write_text(kept + '\n', encoding='utf-8')
    R.C.notes('control1.title').unlink(missing_ok=True)
    ask = 'install IPAS looks wrong'
    with mock.patch.object(R.Claude, 'find_transcript', lambda self, s: '/x.jsonl'), \
            mock.patch.object(K, 'remote_on', lambda: True), mock.patch.object(K, 'ask_waiting', lambda: ''):
        eq(K.control_sid(1), (kept, True), 'c1 with no ask still resumes its kept session')
        sid, resume, argv = K.control_open(1, ask=ask)
        check(not resume and sid != kept, 'the ask starts a new session', (sid, resume))
        check('--resume' not in argv, 'no --resume', argv)
        eq(argv[argv.index('--session-id') + 1], sid, 'started with --session-id <new uuid>')
        check(uuid.UUID(sid).version == 4, 'the new id is a uuid')
        eq(argv[1], K.control_ask(ask), 'the ask is its first message')
        eq(argv[argv.index('--remote-control') + 1], K.control_name(1, ask), 'Remote Control gets the ask\'s name')
        eq(K.control_given(1), K.control_name(1, ask), 'control_give recorded that name')
        check(K.control_one_ask(1, sid), 'marked as opened for one ask')
        eq(sidf.read_text(encoding='utf-8').strip(), kept, 'control.sid still holds the run\'s own c1')
        eq(K.control_sid(1), (kept, True), 'and the run\'s c1 resumes it afterwards')
        files_only = K.control_open(1, images=['/tmp/shot.png'])
        check(not files_only[1] and files_only[0] not in (kept, sid), 'a files-only ask starts fresh too')


def test_brief_fits_session_start():
    print('B98: the control brief stays under 9,500 chars (Claude Code shows a 2KB preview of longer '
          'SessionStart output), with the core rules inline and the long ones behind guide <topic>')
    from agent_runner import guide as G, runner as R, voice
    d = Path(tempfile.mkdtemp(prefix='agent-runner-brief-'))
    git(d, 'init', '-q')
    (d / '.gitignore').write_text('.runner/\n')
    (d / 'README.md').write_text('demo\n')
    git(d, 'add', '-A')
    git(d, 'commit', '-qm', 'start')
    R.init(d)
    (d / '.runner').mkdir(exist_ok=True)
    rules = ['say agent, not slot', 'no task ids in titles', 'shorter answers, one line when it fits',
             'call the board the board, not the dashboard', 'never say "slot" to me', 'times as 14:05, not 2:05pm',
             'say landed, not merged', 'lead with what needs me']
    (d / '.runner' / 'voice.md').write_text(''.join(f'- {r}\n' for r in rules), encoding='utf-8')
    cmd = '/home/someone/projects/agent-runner-checkout/run'  # a long [run] command, named in every line
    with mock.patch.dict(R.C.run, {'command': cmd}), mock.patch.object(K, 'feed_on', lambda: False):
        brief = K.control_brief()
        check(len(brief) < K.BRIEF_MAX == 9500, f'with a voice file and the needs-you watch: {len(brief)} chars')
        check(all(r in brief for r in rules), 'the wording itself is carried inline')
        for core in ('**Never edit code or plan files here**', '**Never commit, merge or push in this checkout**',
                     f'{cmd} plan add <KIND>', f'{cmd} guide take', '**Open the session.**',
                     f'{cmd} control --title', '**Push what the person asked to hear', 'never push the main branch',
                     f'{cmd} since --follow --needs-you'):
            check(core in brief, f'core rule inline: {core}')
        for t in G.CONTROL_TOPIC_NAMES:
            check(f'`{t}`' in brief or f'guide {t}`' in brief, f'the brief names `guide {t}`')
            page = G.control_topic(t, cmd, 'Needs you', R.C)
            check(page.startswith('# ') and not re.search(r'\{(cmd|needs|file|repo|log|answer|watch)\}', page),
                  f'`guide {t}` prints its page, filled in')
        check('runner.local.toml' in G.control_topic('settings', cmd, 'Needs you', R.C), 'settings moved to its page')
        check(all(r in G.control_topic('voice', cmd, 'Needs you', R.C) for r in rules), 'guide voice shows the lines')
        (d / '.runner' / 'voice.md').write_text(''.join(f'- rule {i}: {"x" * 80}\n' for i in range(60)))
        long = K.control_brief()
        check(len(long) < K.BRIEF_MAX, f'a long voice file is pointed at, not carried: {len(long)} chars')
        check('60 lines' in long and f'{cmd} guide voice' in long, 'and the brief says where its lines are')
    # B104: Windows names python.exe and the run path, about 85 chars, in every line of the brief
    (d / '.runner' / 'voice.md').write_text(''.join(f'- {r}\n' for r in rules), encoding='utf-8')
    win = 'C:/hostedtoolcache/windows/Python/3.12.10/x64/python.exe D:/a/agent-runner/agent-runner/run'
    with mock.patch.dict(R.C.run, {'command': win}), mock.patch.object(K, 'feed_on', lambda: False):
        brief = K.control_brief()
        check(len(brief) < K.BRIEF_MAX, f'a Windows-long [run] command still fits: {len(brief)} chars')
        check(all(r in brief for r in rules), 'and the wording is still carried inline')
        check(f'`{win}` is the runner' in brief and f'`{win} <that command>`' in brief,
              'the Guide pages line still names the full command')
        check(K.bare_commands(f'`{win}` is the runner: means `{win} <that command>`. `{win} status`', win)
              .endswith('. `status`'), 'C21: bare_commands finds the end of the Guide pages line by its wording')
        check('`guide take`' in brief and '`plan add <KIND>' in brief, 'the commands after it are bare')
    check(voice.brief_fit('x', cmd, R.C) != '', 'brief_fit returns text')


def test_take_back_from_a_slot_just_started():
    print('B109: take on a task a slot started moments ago (no commits) takes it back and frees the slot; one '
          'with commits refuses, with no attach line')
    import io
    import sys
    import threading
    import time
    from contextlib import redirect_stderr, redirect_stdout
    from agent_runner import cmds as M, loop as L, plan as P, runner as R
    d = Path(tempfile.mkdtemp(prefix='agent-runner-b109-'))
    git(d, 'init', '-q', '-b', 'main')
    (d / 'plan').mkdir()
    (d / 'plan/TODO.md').write_text('# TODO\n\n### Later\n\n- [ ] **T1** fresh one | files: a.py\n'
                                    '- [ ] **T2** further along | files: b.py\n', encoding='utf-8')
    (d / 'plan/DONE.md').write_text('# DONE\n', encoding='utf-8')
    (d / 'runner.toml').write_text('[run]\ntest = "true"\nremote = false\nmin_free_gb = 0\n', encoding='utf-8')
    (d / '.gitignore').write_text('.runner/\n')
    git(d, 'add', '-A')
    git(d, 'commit', '-qm', 'start')
    R.init(d)
    slot = R.worktree(5, 'main')
    git(slot, 'checkout', '-q', '-B', 'task/T1', 'main')  # the run's slot 5 has just claimed T1
    agent = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    procs, running, free_at = {5: (agent.pid, '', None)}, {5: ('T1', 'fresh one', ['a.py'])}, {}

    def the_run():  # the run's loop, as far as halts go: it answers the take's request
        end = time.monotonic() + 30
        while time.monotonic() < end and 'T1' not in L.halt_requests():
            time.sleep(0.05)
        L.halts(procs, running, free_at, set(), 'main', 'm', 0, 5)

    take = io.StringIO()
    logged = []  # (msg, event kind) the run logs
    import os
    here = os.getcwd()
    os.chdir(d)  # take reads the repository around the current directory, as from a control session
    with mock.patch.object(P, 'run_on', lambda c, tid: 's5' if tid == 'T1' and 5 in running else ''), \
            mock.patch.object(L, 'end_orphans', lambda: None), \
            mock.patch.object(L, 'log', lambda msg, kind=None, *a, **k: logged.append((msg, kind))), \
            mock.patch.object(L, 'note', lambda *a, **k: None):
        t = threading.Thread(target=the_run, daemon=True)
        t.start()
        with redirect_stderr(take), redirect_stdout(io.StringIO()):
            rc = M.cmd_take(['T1'])
        t.join(30)
    try:
        agent.wait(15)
    except subprocess.TimeoutExpired:
        agent.kill()
    eq(rc, 0, f'take succeeds: {take.getvalue()}')
    check('took it back from s5' in take.getvalue(), 'and says it took it back from s5', take.getvalue())
    check(agent.poll() is not None, "the slot's agent was stopped")
    check(5 not in procs and 5 not in running and 5 in free_at, 'the slot is given back')
    check(git(slot, 'rev-parse', '--abbrev-ref', 'HEAD') == 'HEAD', 'the slot worktree is off task/T1')
    eq(git(M.SLOTS_DIR / 'take-T1', 'rev-parse', '--abbrev-ref', 'HEAD'), 'task/T1', 'the take worktree has task/T1')
    eq(M.running_slot('T1'), 0, 'no slot runs T1 now')
    from agent_runner.state import EV_DROPPED
    check(not any(k == EV_DROPPED for _, k in logged), 'B110: a take back records no EV_DROPPED event', logged)
    check(any(m.startswith('took T1 back to a take') for m, _ in logged), "B110: the run logs 'took T1 back to a "
          "take', not 'dropped'", logged)

    git(slot, 'checkout', '-q', '-B', 'task/T2', 'main')
    (slot / 'b.py').write_text('# b\n')
    git(slot, 'add', '-A')
    git(slot, 'commit', '-qm', 'T2 work')
    asked = []
    err = io.StringIO()
    with mock.patch.object(P, 'run_on', lambda c, tid: 's5'), \
            mock.patch.object(P, 'request', lambda *a, **k: asked.append(a) or 'stopped'):
        with redirect_stderr(err), redirect_stdout(io.StringIO()):
            rc = M.cmd_take(['T2'])
    eq(rc, 1, 'take refuses a task whose slot has commits')
    check(not asked, 'and never asks the run to stop that slot', asked)
    check('running in slot s5' in err.getvalue() and 'plan tell T2' in err.getvalue(), 'names the slot and plan tell',
          err.getvalue())
    check('attach s' not in err.getvalue(), 'the refusal has no attach line', err.getvalue())
    eq(git(slot, 'rev-parse', '--abbrev-ref', 'HEAD'), 'task/T2', 'the slot keeps T2')
    check(not (M.SLOTS_DIR / 'take-T2').exists(), 'and nothing is taken')
    os.chdir(here)
    from agent_runner.guide import topic
    check('attach s' not in topic('take', './run'), 'the take guide hands out no attach line either')


def test_sessions_one_and_each():
    print('F68: [run] sessions = one keeps a slot off Remote Control until opened, its link then in the snapshot, '
          'and c1 republishes the claude.ai copy; each puts every slot there as before')
    import os
    from agent_runner import page_copy as PC, runner as R, slots as S, ui_model as U
    d = Path(tempfile.mkdtemp(prefix='agent-runner-f68-'))
    git(d, 'init', '-q', '-b', 'main')
    (d / 'plan').mkdir()
    (d / 'plan/TODO.md').write_text('# TODO\n\n### Later\n\n- [ ] **T1** fix the <b>widget</b> | files: a.py\n',
                                    encoding='utf-8')
    (d / 'plan/DONE.md').write_text('# DONE\n', encoding='utf-8')
    (d / 'runner.toml').write_text('[run]\ntest = "true"\nremote_slots = true\n', encoding='utf-8')
    (d / '.gitignore').write_text('.runner/\n')
    git(d, 'add', '-A')
    git(d, 'commit', '-qm', 'start')
    R.init(d)
    eq(R.C.run['sessions'], 'one', 'sessions defaults to one')
    check(S.one_session(), 'one_session() under the default')
    eq(S.remote_flags('slot2', None), [], 'one: a slot starts with no --remote-control (not listed in the apps)')
    argv = S.agent_argv('brief', str(uuid.uuid4()), 'opus', 60, 'slot2')
    check('--remote-control' not in argv, 'one: the slot argv has no --remote-control', argv)

    sid, typed, bridged = str(uuid.uuid4()), [], []

    class FakeMux:
        typed = True

        def panes(self):
            return {'s2': ('%9', os.getpid())}

        def session_id(self, pid):
            return sid

        def send(self, hit, text):
            typed.append((hit, text))
            if text.startswith('/remote-control '):
                bridged.append({'type': 'bridge-session', 'bridgeSessionId': 'cse_f68abc'})
            return True

    link = f'{S.REMOTE_URL}/session_f68abc'
    st = {'running': {'2': 'T1'}, 'since': {}}
    with mock.patch.object(S, 'MUX', FakeMux()), mock.patch.object(S, 'remote_off_why', lambda dialog=True: ''), \
            mock.patch.object(S, 'entries', lambda s, skip_bad=False: list(bridged) if s == sid else []):
        rows = U.session_rows(st, P_lines(d), {'T1': 'fix the widget'}, 0)
        eq(rows[1]['link'], '', 'one: before it is opened the slot has no claude.ai link')
        got, why = S.slot_open('s2', wait=2)
        eq((got, why), (link, ''), 'slot_open types /remote-control and returns the link')
        check(typed and typed[0][1].startswith('/remote-control ') and 's2' in typed[0][1], 'typed into s2', typed)
        rows = U.session_rows(st, P_lines(d), {'T1': 'fix the widget'}, 0)
        eq(rows[1]['link'], link, "one: once opened, the slot's link is in F65's snapshot")
        eq(U.act('open_session', slot='s2'), {'ok': True, 'code': 0, 'out': link, 'argv': []},
           'the run page action open_session gives the link, typing nothing more')
        eq(len(typed), 1, 'an open slot is not told again')
    eq(S.slot_open('s7')[0], '', 'a slot with no session gives no link')

    snap = {'project': 'demo', 'at': '2026-11-22T10:00:00', 'up': True, 'status': ['run up: 1 busy'],
            'sessions': [{'name': 'c1', 'state': 'live', 'link': f'{S.REMOTE_URL}/session_c1'},
                         {'name': 's2', 'task': 'T1', 'title': 'fix the <b>widget</b>', 'minutes': 4,
                          'state': 'running', 'link': link}],
            'queue': [{'id': 'T1', 'title': 'fix the <b>widget</b>', 'after': [], 'pri': 'normal'}],
            'needs': [], 'concepts': [], 'log': ['started T1 in s2'], 'release': ''}
    asks = []
    send = lambda path, url: asks.append((path, url)) or (url or 'https://claude.ai/artifact/abc')  # noqa: E731
    PC.PAGE_COPY_AT[0] = 0.0
    PC.PAGE_COPY_OFF[0] = ''
    with mock.patch.object(PC, 'remote_on', lambda: True), mock.patch.object(PC, 'control_ok', lambda: True):
        check(PC.page_copy_tick(now=1000.0, snap=snap, publish=send, background=False), 'one: the copy is published')
        page = PC.page_copy_file().read_text(encoding='utf-8')
        check(link in page and f'{S.REMOTE_URL}/session_c1' in page, 'the copy links the terminal and the chat')
        check('<b>widget' not in page and '&lt;b&gt;widget' in page, 'task text is escaped')
        check('?t=' not in page and '<title>' in page, 'no run page token; a title')
        eq(asks, [(PC.page_copy_file(), '')], 'the first publish has the file and no URL yet')
        eq(PC.page_copy_url(), 'https://claude.ai/artifact/abc', 'the URL it published to is kept')
        check(not PC.page_copy_tick(now=1000.0 + PC.PAGE_COPY_EVERY + 1, snap=snap, publish=send, background=False),
              'nothing changed: not published again')
        later = {**snap, 'sessions': snap['sessions'][:1], 'log': ['landed T1']}
        check(not PC.page_copy_tick(now=1010.0, snap=later, publish=send, background=False),
              'not within PAGE_COPY_EVERY of the last publish')
        check(PC.page_copy_tick(now=1000.0 + 2 * PC.PAGE_COPY_EVERY, snap=later, publish=send, background=False),
              'a run event after that publishes again')
        eq(asks[-1][1], 'https://claude.ai/artifact/abc', 'to the same URL')

        with mock.patch.dict(R.C.run, {'sessions': 'each'}):
            check(not S.one_session(), 'each: one_session() is off')
            flags = S.remote_flags('slot2', None)
            eq(flags[:1], ['--remote-control'], 'each: a slot starts on Remote Control, as before')
            check('s2' in flags[1], 'named with its slot', flags)
            argv = S.agent_argv('brief', str(uuid.uuid4()), 'opus', 60, 'slot2')
            check('--remote-control' in argv, 'each: the slot argv has --remote-control (listed), as before', argv)
            check(not PC.page_copy_tick(now=1e9, snap={**snap, 'up': False}, publish=send,
                                        background=False), 'each: no copy kept')


def test_reopen_after_shutdown():
    print('B121: c2+ live at a shutdown come back on run start with --resume <same sid> and their title; '
          'one closed on purpose stays closed')
    import os
    import sys
    import time
    from agent_runner import control_reopen as CR, runner as R, slots as S
    d = Path(tempfile.mkdtemp(prefix='agent-runner-reopen-'))
    git(d, 'init', '-q')
    (d / '.gitignore').write_text('.runner/\n')
    (d / 'README.md').write_text('demo\n')
    git(d, 'add', '-A')
    git(d, 'commit', '-qm', 'start')
    R.init(d)
    p = subprocess.Popen([sys.executable, '-c', 'pass'])
    p.wait()
    dead = p.pid  # a process that is gone, as every control session is after a reboot
    booted = time.time() - 1000
    gone = 'Remote Control disconnected — this session was ended or archived from another device or app (code 4090)'
    rows: dict[str, list] = {}
    with mock.patch.object(R.Claude, 'find_transcript', lambda self, s: f'/{s}.jsonl' if s in rows else ''), \
            mock.patch.object(K, 'transcript', lambda s: f'/{s}.jsonl' if s in rows else ''), \
            mock.patch.object(K, 'entries', lambda s, skip_bad=False: rows.get(s, [])), \
            mock.patch.object(K, 'remote_on', lambda: True), mock.patch.object(K, 'ask_waiting', lambda: ''), \
            mock.patch.object(CR, 'boot_time', lambda: booted):
        sid1, resume1, _ = K.control_open(1)
        rows[sid1] = []
        sid2, resume2, _ = K.control_open(2, ask='fix the deploy page')
        check(not resume2, 'c2 starts fresh the first time')
        eq(R.C.notes('control2.sid').read_text(encoding='utf-8').strip(), sid2, 'c2 keeps its id in control2.sid')
        title2 = K.control_given(2)
        eq(title2, K.control_name(2, 'fix the deploy page'), 'c2 has the title its ask gave it')
        opened = {n: K.control_open(n)[0] for n in (3, 4, 5)}
        for n, sid in [(1, sid1), (2, sid2), *opened.items()]:
            rows.setdefault(sid, [])
            R.C.notes(f'control{n}.pid').write_text(f'{dead} {sid}', encoding='utf-8')
        rows[opened[4]] = [{'type': 'system', 'content': gone}]  # c4: closed in the apps while the machine was off
        R.C.notes('control3.pid').unlink()  # c3: closed on purpose (idle close, B26; closed online, B53)
        for n in (1, 2, 4):  # live at the shutdown: pid files from before this boot
            os.utime(R.C.notes(f'control{n}.pid'), (booted - 100, booted - 100))
        # c5: its pid file is from this boot, so the person quit it while the machine was up

        started = []
        with mock.patch.object(CR, 'reopen_control', lambda n, sid: started.append((n, sid)) or 'a test window'):
            eq(CR.reopen_controls(), [2], 'run start reopens c2 only')
        eq(started, [(2, sid2)], 'with its own session id')
        check(R.C.notes('control2.pid').exists(), 'c2 is still listed until it is up again')
        for n in (3, 4, 5):
            check(not R.C.notes(f'control{n}.pid').exists(), f'c{n} stays closed (no pid file)')
        eq(CR.controls_to_reopen(), [(2, sid2)], 'asking again names c2 only')

        sid, resume, argv = K.control_open(2, reopen=True)  # what `control 2 --reopen` runs
        eq((sid, resume), (sid2, True), 'control 2 --reopen resumes the same conversation')
        eq(argv[argv.index('--resume') + 1], sid2, '--resume <same sid>')
        check('--session-id' not in argv, 'not a new session', argv)
        eq(argv[argv.index('--remote-control') + 1], title2, 'under the title it had')
        check(len(argv) > 1 and argv[1] != K.control_ask('fix the deploy page'), 'its ask is not sent again', argv)
        eq(K.control_given(2), title2, 'its title is left as it was')
        rows[sid2] = [{'type': 'custom-title', 'customTitle': 'deploy talk'}]
        named = K.control_open(2, reopen=True)[2]
        eq(named[named.index('--remote-control') + 1], 'deploy talk', 'a name the person gave it wins')
        fresh, again, _ = K.control_open(2)
        check(not again and fresh != sid2, 'a plain control 2 (control --new) starts fresh', (fresh, again))
        eq(K.control_sid(1), (sid1, True), 'c1 still resumes its kept session')

        got = []
        with mock.patch.object(S, 'MUX', object()), mock.patch.object(K.plat, 'WINDOWS', False), \
                mock.patch.object(K, 'hidden_control', lambda n, cmd: got.append(cmd) or (4242, '')):
            check(CR.reopen_control(2, sid2).startswith('a hidden terminal'), 'a hidden run reopens it hidden')
        eq(got[0][-3:], ['control', '2', '--reopen'], 'as control 2 --reopen')

        calls = []  # the run restarted: start_control reopens them first, unless [run] control is off
        with mock.patch.object(CR, 'reopen_controls', lambda: calls.append(1) or []), \
                mock.patch.object(K, 'control_ok', lambda: True), \
                mock.patch.object(K, 'hidden_control', lambda n, cmd: (4243, '')), \
                mock.patch.object(K.plat, 'WINDOWS', False), mock.patch.object(K, 'mark_board', lambda: None):
            with mock.patch.dict(R.C.run, {'control': True}):
                K.start_control()
            eq(len(calls), 1, 'a run start reopens the control sessions')
            with mock.patch.dict(R.C.run, {'control': False}):
                K.start_control()
            eq(len(calls), 1, 'not with [run] control = false')

        R.C.notes('control6.pid').write_text(f'{dead} {sid2}', encoding='utf-8')
        eq(CR.forget_ended_controls(), [6], 'the run loop forgets one that ended during this boot, not c2')
        check(not R.C.notes('control6.pid').exists(), 'c6 will not be reopened')


def test_second_shim_keeps_live_session():
    print('B131: a second hidden_shim for a control session that is up returns its pid and leaves .job/.live alone')
    from agent_runner import runner as R
    d = Path(tempfile.mkdtemp(prefix='agent-runner-control-'))
    git(d, 'init', '-q')
    (d / '.gitignore').write_text('.runner/\n')
    (d / 'README.md').write_text('demo\n')
    git(d, 'add', '-A')
    git(d, 'commit', '-qm', 'start')
    R.init(d)
    live = subprocess.Popen(['sleep', '30'])  # the first control 13, up
    try:
        job, marker, logf = (R.C.notes(f'control13.{x}') for x in ('job', 'live', 'log'))
        job.write_text('{"argv": ["first"]}', encoding='utf-8')
        marker.write_text(str(live.pid), encoding='utf-8')
        logf.write_text('Remote Control active · https://claude.ai/code/session_01First\n', encoding='utf-8')
        started = []
        no_shim = mock.patch.object(K, 'sp', types.SimpleNamespace(Popen=lambda *a, **k: started.append(a),
                                                                  DEVNULL=subprocess.DEVNULL))
        with no_shim:
            eq(K.hidden_control(13, ['control', '13'], wait=0.5), (live.pid, K.SHIM_ALREADY),
               'the second one answers with the live pid')
        eq(started, [], 'and starts no second shim')
        eq(job.read_text(encoding='utf-8'), '{"argv": ["first"]}', '.job is left as it was')
        eq(marker.read_text(encoding='utf-8'), str(live.pid), '.live is left as it was')
        check(logf.exists() and 'session_01First' in logf.read_text(encoding='utf-8'), 'and its log too')

        import contextlib
        import io
        out = io.StringIO()
        with no_shim, mock.patch.object(R.feed, 'remote_on', lambda: True), contextlib.redirect_stdout(out):
            eq(R.feed.control_new_hidden(13, ['control', '13'], 'c13', wait=0), 0,
               'control --new on that number is not an error')
        check('already up' in out.getvalue() and 'session_01First' in out.getvalue(),
              'it says so, with the link already in its log', out.getvalue())

        live.kill()
        live.wait()
        with no_shim:
            pid, why = K.hidden_control(13, ['control', '13'], wait=0.3)
        check(pid == 0 and len(started) == 1, 'a marker whose pid has ended does not stop a new start', (pid, why))
        check(not marker.exists() and '"control", "13"' in job.read_text(encoding='utf-8'),
              'the stale marker is cleared and the job rewritten')
    finally:
        if live.poll() is None:
            live.kill()
            live.wait()


def P_lines(d: Path) -> list[str]:
    return (d / 'plan/TODO.md').read_text(encoding='utf-8').splitlines()


if __name__ == '__main__':
    raise SystemExit(report([test_handed_ask_as_c1_starts_fresh, test_brief_fits_session_start,
                             test_take_back_from_a_slot_just_started, test_sessions_one_and_each,
                             test_reopen_after_shutdown, test_second_shim_keeps_live_session]))
