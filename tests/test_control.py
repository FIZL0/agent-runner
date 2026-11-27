"""Control sessions: a handed-on ask, the brief, take back, sessions one/each, reopening after a
shutdown. (C26 dropped B94's tests of the background tmux session, which is gone.)"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import subprocess
import tempfile
import time
import types
import uuid
from pathlib import Path
from unittest import mock

from _check import check, eq, git, report
from _loop_patch import patched

from agent_runner import control as K  # noqa: E402


def test_handed_ask_starts_fresh():
    print('B96, F176: control --new --ask starts fresh, named, whatever id an older runner kept for its c1')
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
            mock.patch.object(K, 'remote_on', lambda: True):
        check(K.control_sid(1)[0] != kept and not K.control_sid(1)[1], 'the kept session is not resumed')
        sid, resume, argv = K.control_open(1, ask=ask)
        check(not resume and sid != kept, 'the ask starts a new session', (sid, resume))
        check('--resume' not in argv, 'no --resume', argv)
        eq(argv[argv.index('--session-id') + 1], sid, 'started with --session-id <new uuid>')
        check(uuid.UUID(sid).version == 4, 'the new id is a uuid')
        eq(argv[1], K.control_ask(ask), 'the ask is its first message')
        eq(argv[argv.index('--remote-control') + 1], K.control_name(1, ask), 'Remote Control gets the ask\'s name')
        eq(K.control_given(1), K.control_name(1, ask), 'control_give recorded that name')
        check(K.control_one_ask(1, sid), 'marked as opened for one ask')
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
    with mock.patch.dict(R.C.run, {'command': cmd}):
        brief = K.control_brief()
        check(len(brief) < K.BRIEF_MAX == 9500, f'with a voice file: {len(brief)} chars')
        check(all(r in brief for r in rules), 'the wording itself is carried inline')
        for core in ('**Never edit code or plan files here**', '**Never commit, merge or push in this checkout**',
                     '**Open the session.**', '**Push what the person asked to hear', 'never push the main branch'):
            check(core in brief, f'core rule inline: {core}')
        # B150: the voice file's path is in the brief, so a longer temp folder takes it past BRIEF_MAX and its
        # commands go bare (B104): either form carries the rule, each is tested below whatever this machine's paths
        for core in ('plan add <KIND>', 'guide take', 'control --title'):
            check(f'{cmd} {core}' in brief or f'`{core}' in brief, f'core rule inline: {core}')
            with mock.patch.object(K, 'BRIEF_MAX', 10 ** 6):
                check(f'{cmd} {core}' in K.control_brief(), f'with room, its full command: {core}')
            with mock.patch.object(voice, '_shown', lambda p: '/deep' * 150 + '/voice.md'):
                deep = K.control_brief()
            check(f'`{core}' in deep and len(deep) < K.BRIEF_MAX, f'under a deep path, bare: {core}')
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
    with mock.patch.dict(R.C.run, {'command': win}):
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
            patched(end_orphans=lambda: None, log=lambda msg, kind=None, *a, **k: logged.append((msg, kind)),
                    note=lambda *a, **k: None):
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
    print('F68: [run] remote_slots = open keeps a slot off Remote Control until opened, its link then in the snapshot, '
          'and the run keeps the claude.ai copy; always puts every slot there as before')
    import os
    from agent_runner import page_copy as PC, runner as R, slots as S, ui_model as U
    d = Path(tempfile.mkdtemp(prefix='agent-runner-f68-'))
    git(d, 'init', '-q', '-b', 'main')
    (d / 'plan').mkdir()
    (d / 'plan/TODO.md').write_text('# TODO\n\n### Later\n\n- [ ] **T1** fix the <b>widget</b> | files: a.py\n',
                                    encoding='utf-8')
    (d / 'plan/DONE.md').write_text('# DONE\n', encoding='utf-8')
    (d / 'runner.toml').write_text('[run]\ntest = "true"\nremote_slots = "open"\n', encoding='utf-8')
    (d / '.gitignore').write_text('.runner/\n')
    git(d, 'add', '-A')
    git(d, 'commit', '-qm', 'start')
    R.init(d)
    eq(R.C.run['remote_slots'], 'open', 'slots are listed when opened')
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
        eq(rows[0]['link'], '', 'one: before it is opened the slot has no claude.ai link')
        got, why = S.slot_open('s2', wait=2)
        eq((got, why), (link, ''), 'slot_open types /remote-control and returns the link')
        check(typed and typed[0][1].startswith('/remote-control ') and 's2' in typed[0][1], 'typed into s2', typed)
        rows = U.session_rows(st, P_lines(d), {'T1': 'fix the widget'}, 0)
        eq(rows[0]['link'], link, "one: once opened, the slot's link is in F65's snapshot")
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
    with mock.patch.object(PC, 'remote_on', lambda: True):
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

        with mock.patch.dict(R.C.run, {'remote_slots': 'always'}):
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
            mock.patch.object(K, 'remote_on', lambda: True), \
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
            eq(CR.reopen_controls(), [2], 'run start reopens c2 only: not an older runner\'s c1')
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
        check(not K.control_sid(1)[1], 'nor is c1 resumed')

        got = []
        with mock.patch.object(S, 'MUX', object()), mock.patch.object(K.plat, 'WINDOWS', False), \
                mock.patch.object(K, 'hidden_control', lambda n, cmd: got.append(cmd) or (4242, '')):
            check(CR.reopen_control(2, sid2).startswith('a hidden terminal'), 'a hidden run reopens it hidden')
        eq(got[0][-3:], ['control', '2', '--reopen'], 'as control 2 --reopen')

        calls = []  # the run restarted: start_control reopens them first, unless [run] control is off
        with mock.patch.object(CR, 'reopen_controls', lambda: calls.append(1) or []), \
                mock.patch.object(K, 'hidden_control', lambda n, cmd: (4243, '')), \
                mock.patch.object(K.plat, 'WINDOWS', False):
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
        no_shim = mock.patch.object(K.plat, 'spawn_detached', lambda *a, **k: started.append(a))
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

        # the root cause: two `control --new` that arrive together each claim a number of their own
        with mock.patch.object(K, 'free_control_number', lambda: 13), mock.patch.object(K, 'control_live', lambda n: 0):
            eq(K.claim_control_number(), 14, 'a number whose shim marker is live is taken: the next one')
            claims = R.C.notes('control14.claim')
            check(claims.exists(), 'and claimed')
            other = subprocess.Popen(['sleep', '30'])  # another control --new holds c14's claim
            try:
                claims.write_text(str(other.pid), encoding='utf-8')
                eq(K.claim_control_number(), 15, 'a number another live control --new claimed is skipped')
                K.control_unclaim(14)
                check(claims.exists(), "unclaim leaves another process's claim alone")
            finally:
                other.kill()
                other.wait()
            eq(K.claim_control_number(), 14, "a claim whose process ended is taken over")
            K.control_unclaim(14)
            K.control_unclaim(15)
            check(not claims.exists() and not R.C.notes('control15.claim').exists(), 'unclaim drops its own claims')

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


def test_first_message_typed_after_remote_control():
    print('B147: on Remote Control under the hidden shim the first message is not a positional prompt (it would '
          'run before the bridge connects); it is typed in through the FIFO once the claude.ai/code link shows')
    import threading
    import time
    from agent_runner import control_first as KF, runner as R
    d = Path(tempfile.mkdtemp(prefix='agent-runner-first-'))
    git(d, 'init', '-q')
    (d / '.gitignore').write_text('.runner/\n')
    (d / 'README.md').write_text('demo\n')
    git(d, 'add', '-A')
    git(d, 'commit', '-qm', 'start')
    R.init(d)
    ask = 'hi'
    with mock.patch.object(K, 'remote_on', lambda: True):
        argv = K.control_argv(3, 'sid', False, ask=ask, typed=True)
        check(ask not in argv and argv[1] == '--session-id', 'remote on + ask: no positional prompt', argv)
        check('--remote-control' in argv, 'still on Remote Control', argv)
        eq(KF.CONTROL_FIRST[0], K.control_ask(ask), 'the ask is kept to be typed in after start')
        eq(K.control_argv(3, 'sid', False, typed=True)[1], '--session-id', 'no ask: no prompt')
        eq(KF.CONTROL_FIRST[0], '', 'and nothing typed in')
        with mock.patch.dict(os.environ, {'AGENT_RUNNER_MARKER': ''}):
            argv = K.control_argv(3, 'sid', False, ask=ask)
        eq(argv[1], K.control_ask(ask), 'not under a hidden shim (a terminal): the positional prompt stays')
        eq(KF.CONTROL_FIRST[0], '', 'and nothing is left to type')
        with mock.patch.dict(os.environ, {'AGENT_RUNNER_MARKER': '/n/slot1.live'}):
            eq(K.control_argv(3, 'sid', False, ask=ask)[1], K.control_ask(ask), "a slot's marker is not c3's shim")
        with mock.patch.dict(os.environ, {'AGENT_RUNNER_MARKER': '/n/control3.live'}), \
                mock.patch.object(K.plat, 'WINDOWS', False):
            eq(K.control_argv(3, 'sid', False, ask=ask)[1], '--session-id', "under c3's own shim it is typed in")
    with mock.patch.object(K, 'remote_on', lambda: False):
        argv = K.control_argv(3, 'sid', False, ask=ask, typed=True)
        eq(argv[1], K.control_ask(ask), 'Remote Control off: the positional prompt stays')
        eq(KF.CONTROL_FIRST[0], '', 'nothing to type')

    from agent_runner import cmds
    calls = []

    def fake_exec(exe, argv, env):
        calls.append(('exec', argv))
        raise SystemExit(0)
    here = os.getcwd()
    os.chdir(d)  # cmd_control's init() reads the current directory
    try:
        with mock.patch.object(K, 'remote_on', lambda: True), \
                mock.patch.object(K.plat, 'WINDOWS', False), \
                mock.patch.dict(os.environ, {'AGENT_RUNNER_MARKER': str(R.C.notes('control3.live'))}), \
                mock.patch.object(cmds, 'backend', lambda: types.SimpleNamespace(trust=lambda root: None)), \
                mock.patch.object(cmds, 'type_first_later', lambda text: calls.append(('type', text))), \
                mock.patch.object(cmds.os, 'execvpe', fake_exec):
            try:
                calls.append(('returned', cmds.cmd_control(['3', '--ask', ask])))
            except SystemExit:
                pass
    finally:
        os.chdir(here)
    eq([c[0] for c in calls], ['type', 'exec'], 'control 3 --ask under its shim leaves the typer, then execs')
    check(calls[0][1] == K.control_ask(ask) and K.control_ask(ask) not in calls[1][1],
          'the ask goes to the typer, not on the command line', calls)

    marker, log_file, inbox = d / 'control3.live', d / 'control3.log', d / 'control3.in'
    log_file.write_text('earlier run https://claude.ai/code/session_old\n', encoding='utf-8')
    since = log_file.stat().st_size
    linked, typed = [], []
    if os.name != 'nt':
        os.mkfifo(inbox, 0o600)
        rd = os.open(inbox, os.O_RDONLY | os.O_NONBLOCK)
        fifo = contextlib.nullcontext()
    else:  # no FIFO on Windows: what send_fifo is asked to type, after the same wait for the link
        fifo = mock.patch('agent_runner.slots.send_fifo', lambda i, text: typed.append((i, text)) or True)

    def bridge_up():
        time.sleep(0.8)
        linked.append(time.monotonic())
        with open(log_file, 'a', encoding='utf-8') as fh:
            fh.write('Remote Control active https://claude.ai/code/session_new\n')
    t = threading.Thread(target=bridge_up)
    t.start()
    with mock.patch.object(KF, 'FIRST_SETTLE', 0.0), fifo:
        ok = KF.type_first(marker, ask, since, wait=10)
    sent = time.monotonic()
    t.join()
    check(ok and linked and sent >= linked[0], 'typed only after the link showed (not the earlier run\'s)', (ok, linked))
    if os.name == 'nt':
        eq(typed, [(inbox, ask)], 'the ask went to its FIFO')
        return
    got = b''
    while True:
        try:
            chunk = os.read(rd, 4096)
        except BlockingIOError:
            break
        if not chunk:
            break
        got += chunk
    os.close(rd)
    eq(got, b'\x1b[200~hi\x1b[201~\r', 'the ask went through the FIFO as a paste and Enter')


def test_takes_input_b158():
    print('B158: a starting control session takes input once its TUI is up (bracketed paste on) and its first message is in')
    import json
    import os
    import time
    from agent_runner import control_first as KF, runner as R
    d = Path(tempfile.mkdtemp(prefix='agent-runner-control-'))
    git(d, 'init', '-q')
    (d / '.gitignore').write_text('.runner/\n')
    git(d, 'add', '-A')
    git(d, 'commit', '-qm', 'start')
    R.init(d)
    job, log, first = R.C.notes('control14.job'), R.C.notes('control14.log'), R.C.notes('control14.first')
    log.write_bytes(b'\x1b[?2004h an earlier session of this number')
    was = log.stat().st_size
    with mock.patch.object(K.plat, 'spawn_detached', lambda *a, **k: None):
        K.hidden_shim('control14', ['control', '14'], wait=0.1)
    eq(json.loads(job.read_text(encoding='utf-8')).get('log_from'), was, 'the job keeps where its log starts')
    with mock.patch.object(K.plat, 'WINDOWS', True):
        check(K.control_takes_input(14), 'a Windows console does not pass it on: nothing is held')
    if os.name == 'nt':
        return
    check(K.control_takes_input(15), 'no hidden session of this number: nothing to wait for')
    check(not K.control_takes_input(14), 'only the earlier session was up')
    with log.open('ab') as fh:
        fh.write(b'starting...')
    check(not K.control_takes_input(14), 'the launcher is not the TUI')
    with log.open('ab') as fh:
        fh.write(b'\x1b[?25h\x1b[?2004h')
    check(K.control_takes_input(14), 'the TUI is up')
    first.write_text('', encoding='utf-8')
    check(not K.control_takes_input(14), 'its first message is still to be typed in')
    old = time.time() - 3600
    os.utime(first, (old, old))
    check(K.control_takes_input(14), 'a first-message mark left behind holds nothing')
    first.unlink()
    go = d / 'go'

    def typing(m, t, since):
        end = time.monotonic() + 20
        while not go.exists() and time.monotonic() < end:
            time.sleep(0.02)
        return True
    with mock.patch.dict(os.environ, {'AGENT_RUNNER_MARKER': str(R.C.notes('control14.live'))}), \
            mock.patch.object(KF, 'type_first', typing):
        KF.type_first_later('hi')
        check(first.exists(), 'type_first_later marks it before the agent starts')
        go.write_text('')
        end = time.monotonic() + 20
        while first.exists() and time.monotonic() < end:
            time.sleep(0.05)
        check(not first.exists(), 'and clears it once typed')
    log.write_bytes(b'')
    check(K.control_takes_input(14), 'a log cut since holds nothing')


def P_lines(d: Path) -> list[str]:
    return (d / 'plan/TODO.md').read_text(encoding='utf-8').splitlines()


def test_rename_f129():
    """F129: control --rename N NAME types /rename, and the session then counts as renamed by the person: kept when idle,
    and control --title leaves it alone."""
    from agent_runner import cmds as M, runner as R
    from agent_runner.control_names import person_name
    d = Path(tempfile.mkdtemp(prefix='agent-runner-rename-'))
    git(d, 'init', '-q')
    (d / '.gitignore').write_text('.runner/\n')
    git(d, 'add', '-A')
    git(d, 'commit', '-qm', 'start')
    R.init(d)
    typed = []
    with mock.patch.object(K, 'control_live', lambda n: n in (1, 4)), mock.patch.object(M, 'init'), \
            mock.patch.object(K, 'control_type', lambda n, text: (typed.append((n, text)), True)[1]):
        eq(M.cmd_control(['--rename', '4', '  Login   woes ']), 0, 'control --rename 4 NAME')
        eq(typed, [(4, '/rename Login woes')], 'types /rename NAME into it')
        st = {'last': 'claude', 'text': 'Done.', 'at': 1.0, 'running': set(), 'title': '', 'said': 1, 'queued': False}
        cf = {'idle': 60, 'quick': 60, 'talked': 60, 'ask_idle': 60, 'open': ['?']}
        eq(K.control_verdict(st, cf, 1e9, 4), ('keep', 'renamed by the person'), 'kept, before the title shows too')
        eq(K.control_verdict({**st, 'title': 'Login woes'}, cf, 1e9, 4), ('keep', 'renamed by the person'), 'and after')
        eq(K.control_verdict(st, cf, 1e9, 5)[0], 'close', 'another session still closes')
        eq(person_name(4, 'Renamed in the app'), '', 'a later rename in the apps is the newer name')
        eq(M.cmd_control(['--rename', '1', 'Home base']), 0, 'c1 can be renamed')
        eq(M.cmd_control(['--rename', '9', 'x']), 1, 'one that is not up is refused')
        eq(M.cmd_control(['--rename', '4', '  ']), 2, 'and so is an empty name')
        typed.clear()
        K.control_set_title(4, 'what it is for')
        eq(typed, [], 'control --title leaves the name')
    with mock.patch.object(K, 'control_live', lambda n: False):
        K.C.notes('control4.pid').write_text('1 sid', encoding='utf-8')
        with mock.patch.object(K, 'log', lambda *a: None):
            K.end_control(4, 'test')
    eq(person_name(4, ''), '', 'an ended session takes its name with it')


# --- B170: messages held by a usage limit ----------------------------------------------------------------------

T0 = 1795384282.0  # 2026-11-22T21:51:22Z
RESET = 1795399200.0


def stamp(at: float) -> str:
    import datetime as dt
    return dt.datetime.fromtimestamp(at, dt.timezone.utc).isoformat().replace('+00:00', 'Z')


def said(text, at, **kw):
    return {'type': 'user', 'uuid': f'u{at}', 'timestamp': stamp(at), 'origin': {'kind': 'human'},
            'message': {'role': 'user', 'content': text}, **kw}


def limit(at, resets=RESET, **kw):
    """The error as Claude Code 2.1.330 wrote it (transcript b35563a2, 2026-11-22)."""
    return {'type': 'assistant', 'timestamp': stamp(at), 'isApiErrorMessage': True, 'error': 'rate_limit',
            'apiError': 'usage_limit_reached', 'quotaLimits': {'status': 'rejected', 'resetsAt': resets},
            'message': {'model': '<synthetic>', 'content': [
                {'type': 'text', 'text': "You've hit your weekly limit \u00b7 resets 9pm (America/New_York)"}]}, **kw}


def answer(text, at, **kw):
    return {'type': 'assistant', 'timestamp': stamp(at),
            'message': {'model': 'claude-opus-5-5', 'content': [{'type': 'text', 'text': text}]}, **kw}


def four():
    shot = {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png', 'data': 'aGVsbG8='}}
    asks = [[shot, {'type': 'text', 'text': 'control windows in the terminal too'}], 'N is super slow',
            'keep the ^ shortcuts', 'n not N']
    return [x for i, a in enumerate(asks) for x in (said(a, T0 + 30 * i), limit(T0 + 30 * i + 1))]


ORDER = ['control windows in the terminal too', 'N is super slow', 'keep the ^ shortcuts', 'n not N']


@contextlib.contextmanager
def held_world():
    """A project whose control sessions' transcripts are `w.rows`, live ones `w.live` ({n: pid}); what is typed
    is in `w.typed`, reopened ones in `w.opened`."""
    from agent_runner import control_held as H, control_reopen as CR, runner as R, watch
    d = Path(tempfile.mkdtemp(prefix='agent-runner-held-'))
    git(d, 'init', '-q')
    (d / '.gitignore').write_text('.runner/\n')
    (d / 'README.md').write_text('demo\n')
    git(d, 'add', '-A')
    git(d, 'commit', '-qm', 'start')
    R.init(d)
    H._SEEN.clear()
    w = types.SimpleNamespace(H=H, rows={}, live={}, typed=[], opened=[], logs=[], outside=[])
    home = d / 'transcripts'
    home.mkdir()

    def path(s):
        if s not in w.rows:
            f = home / f'{s}.jsonl'  # one the runner wrote (B173: a copy of an app session)
            return str(f) if f.exists() else ''
        (home / f'{s}.jsonl').write_text(''.join(json.dumps(x) + '\n' for x in w.rows[s]), encoding='utf-8')
        return str(home / f'{s}.jsonl')

    def rows_of(s, skip_bad=False):
        f = home / f'{s}.jsonl'
        return iter(w.rows[s] if s in w.rows else
                    [json.loads(x) for x in f.read_text(encoding='utf-8').splitlines()] if f.exists() else [])

    def up(n, sid, pid, ago=1000.0):
        f = R.C.notes(f'control{n}.pid')
        f.write_text(f'{pid} {sid}', encoding='utf-8')
        os.utime(f, (RESET - ago, RESET - ago))
        w.live[n] = pid
        R.C.notes(f'control{n}.in').write_text('', encoding='utf-8')
    w.up = up

    def tick(at):
        for s in w.rows:
            path(s)
        H._SEEN.clear()
        with mock.patch.object(H.time, 'time', lambda: at):
            H.held_tick(force=True, now=at)
    w.tick = tick

    def reopened(n, sid):
        w.opened.append((n, sid))
        return 'a test window'
    with mock.patch.object(K, 'transcript', path), \
            mock.patch.object(K, 'entries', rows_of), \
            mock.patch.object(K, 'control_live', lambda n: w.live.get(n, 0)), \
            mock.patch.object(K, 'control_type', lambda n, t: w.typed.append((n, t)) or True), \
            mock.patch.object(K, 'remote_on', lambda: False), \
            mock.patch.object(CR, 'reopen_control', reopened), \
            mock.patch.object(watch, 'live_session', lambda s: 99 if s in w.outside else None), \
            mock.patch.object(R.state, 'log', lambda *a, **k: w.logs.append(a[0])), \
            mock.patch.object(K, 'log', lambda *a, **k: w.logs.append(a[0])):
        w.notes = R.C.notes
        yield w


def in_order(text, words):
    at = [text.find(x) for x in words]
    return -1 not in at and at == sorted(at) and all(text.count(x) == 1 for x in words)


def test_held_delivered_once():
    print('B170: four messages that got only a usage-limit error go in once, in order, when it is over')
    with held_world() as w:
        w.rows['a'] = four()
        w.up(5, 'a', 41)
        w.tick(T0 + 200)
        eq(w.typed, [], 'nothing is typed while the limit holds')
        eq(len([x for x in w.logs if 'wait for the usage limit' in x]), 1, 'the run log says so')
        w.tick(T0 + 300)
        eq(len([x for x in w.logs if 'wait for the usage limit' in x]), 1, 'once')
        with mock.patch.object(w.H.time, 'time', lambda: T0 + 300):
            got = w.H.lines()
        check(len(got) == 1 and '4 asks wait' in got[0] and got[0].startswith('c5') and 'resets' in got[0],
              'status: which chat, how many, when', got)
        with mock.patch.object(K, 'control_live_numbers', lambda: [5]), \
                mock.patch.object(K.plat, 'terminate', lambda p: w.typed.append(('ended', p))):
            eq(K.close_controls(force=True, now=T0 + 90000), [], 'it is not closed as idle')
            w.rows['idle'] = [said('hi', T0), answer('hello', T0 + 1)]
            w.up(5, 'idle', 41)
            eq([x[1] for x in K.close_controls(force=True, now=T0 + 90000)], ['closed'], 'one that holds nothing is')
        w.typed.clear()
        w.up(5, 'a', 41)
        w.tick(RESET + 61)
        eq([n for n, _ in w.typed], [5], 'typed into its session once')
        text = w.typed[0][1]
        check(text.startswith(w.H.HELD_LEAD) and in_order(text, ORDER), 'marked, all four, in order', text)
        saved = re.search(r'saved at "([^"]+)"', text)
        check(saved and Path(saved[1]).read_bytes() == b'hello', 'the image goes along, saved', text)
        w.tick(RESET + 100)
        w.H.HELD_AT[0] = 0.0  # a restarted run knows only the record
        w.tick(RESET + 4000)
        eq(len(w.typed), 1, 'not typed again before it shows, however long, also by a restarted run')
        w.rows['a'] += [said(text, RESET + 62)]
        w.tick(RESET + 5000)
        eq(len(w.typed), 1, 'nor while its turn runs')
        w.rows['a'] += [answer('on it', RESET + 70)]
        w.tick(RESET + 6000)
        eq((len(w.typed), w.H.records()), (1, []), 'answered: done with')


def test_held_still_limited():
    print('B170: a retry that meets the limit again loses nothing and is tried again at the new reset')
    with held_world() as w:
        w.rows['a'] = four()
        w.up(5, 'a', 41)
        w.tick(RESET + 61)
        text = w.typed[0][1]
        nxt = RESET + 86400
        w.rows['a'] += [said(text, RESET + 62), limit(RESET + 63, resets=nxt)]
        w.tick(RESET + 400)
        eq(len(w.typed), 1, 'it waits for the new reset')
        w.rows['a'] += [said('and a fifth', RESET + 500), limit(RESET + 501, resets=nxt)]
        w.tick(nxt + 61)
        eq(len(w.typed), 2, 'then they go in')
        check(in_order(w.typed[1][1], [*ORDER, 'and a fifth']), 'all of them, the new one last', w.typed[1][1])
        w.rows['a'] += [said(w.typed[1][1], nxt + 62), {**limit(nxt + 63), 'error': 'server_error', 'apiError': None}]
        w.tick(nxt + 120)
        eq(len(w.typed), 2, 'another API error waits too')
        w.tick(nxt + 63 + 3600 + 61)
        eq(len(w.typed), 3, 'and is tried again')


def test_held_stuck_and_cut():
    print('B170: a limit inside the replay turn keeps the asks; untaken and stuck ones are said, and a new message retries')
    with held_world() as w:
        held = said(w.H.HELD_LEAD + ' x', RESET + 62)
        step = answer('reading', RESET + 63)
        eq(len(w.H.walk(four() + [held, step, limit(RESET + 64, RESET + 9000)])['asks']), 4, 'cut off mid-replay: held')
        done = answer('all done', RESET + 65)
        done['message']['stop_reason'] = 'end_turn'
        eq(w.H.walk(four() + [held, step, done, limit(RESET + 70)])['asks'], [], 'not once its turn ended')
        eq([a['text'] for a in w.H.walk(four() + [held, step, said('next', RESET + 70), limit(RESET + 71)])['asks']],
           ['next'], 'nor when the next message meets the limit')
        w.rows['a'] = four()
        w.up(5, 'a', 41)
        w.tick(RESET + 61)
        w.tick(RESET + 1000)
        w.tick(RESET + 2000)
        eq(len([x for x in w.logs if 'has not taken them' in x]), 1, 'untaken: said once')
        eq(len(w.typed), 1, 'and not typed twice')
        bad = {**limit(0), 'error': 'invalid_request', 'apiError': None}
        for i in range(3):
            at = RESET + 3000 + 10 * i
            w.rows['a'] += [said(w.typed[0][1], at), {**bad, 'timestamp': stamp(at + 1)}]
        w.tick(RESET + 10000)
        check(w.H.records()[0].get('stuck') and not w.H.holds('a'), 'three refusals: left to the person')
        w.rows['a'] += [said('again', RESET + 20000), limit(RESET + 20001, RESET + 30000)]
        w.tick(RESET + 20100)
        check(w.H.holds('a'), 'a new message held there is not stuck too')
        w.tick(RESET + 30061)
        check(len(w.typed) == 2 and in_order(w.typed[1][1], [*ORDER, 'again']), 'and goes in with the rest', w.typed[1:])


def test_held_resent_and_runner():
    print('B170: what the person sent again is not doubled; the runner\'s own messages are not held')
    with held_world() as w:
        w.rows['a'] = four() + [said('n not  N', T0 + 200), limit(T0 + 201)]
        w.up(5, 'a', 41)
        w.rows['b'] = [said('N is super slow', T0 + 500), answer('filed', T0 + 510)]  # in another chat, answered
        w.rows['c'] = [said('keep the ^ shortcuts', T0 - 500), answer('ok', T0 - 490)]  # earlier: not a resend
        w.tick(RESET + 61)
        check(in_order(w.typed[0][1], [ORDER[0], ORDER[2], ORDER[3]]), 'each once', w.typed[0][1])
        check(ORDER[1] not in w.typed[0][1], 'not the one answered elsewhere', w.typed[0][1])
    with held_world() as w:
        w.rows['a'] = [said('yes', T0), limit(T0 + 1)] + four()[:2]
        w.up(5, 'a', 41)
        w.rows['b'] = [said('yes', T0 + 500), answer('done', T0 + 510), said(ORDER[0], T0 + 520), answer('x', T0 + 530)]
        w.tick(RESET + 61)
        check('Message 2 of 2' in w.typed[0][1], 'a bare yes, or the same words without the image, is no resend', w.typed)
    from agent_runner import control_held as H
    start = 'Open with the summary your control brief describes (its layout: …), and wait for me.'  # an older runner's c1
    copy = 'agent-runner: the run changed. Publish the run page copy x. This is the runner, not the person'
    for t in (start, f'Say first, in one line: "c1 starts a fresh session: x." Then: {start}', copy):
        eq(H.walk([said(t, T0), limit(T0 + 1)])['asks'], [], 'the runner\'s own message')
    block = '\n\n<runner-waiting>\nAdded by the runner.\n- R43: Deploy?\n</runner-waiting>'  # B790: an older runner's
    got = H.walk([said('fix the deploy' + block, T0), limit(T0 + 1)])['asks']
    eq([(a['text'], a['norm']) for a in got], [('fix the deploy', 'fix the deploy')],
       'an old transcript\'s waiting block is left out: only the person\'s words')
    eq(H.walk(four() + [said('hello?', RESET), answer('all five then', RESET + 1)])['asks'], [],
       'a later turn of the person\'s that was answered takes them all')
    note = {'type': 'user', 'timestamp': stamp(RESET), 'origin': {'kind': 'task-notification'},
            'message': {'content': '<task-notification>x</task-notification>'}}
    eq(len(H.walk(four() + [note, answer('seen', RESET + 1)])['asks']), 4, 'a notification\'s turn does not')
    synth = answer('No response requested.', RESET)
    synth['message']['model'] = '<synthetic>'
    eq(len(H.walk(four() + [synth])['asks']), 4, 'nor Claude Code\'s own words on a resume')
    net = {**limit(T0 + 1), 'error': 'unknown', 'apiError': None}
    eq(H.walk([said('x', T0), net])['asks'], [], 'the error\'s kind decides, not its words')
    old = {k: v for k, v in limit(T0 + 1).items() if k in ('type', 'timestamp', 'isApiErrorMessage', 'message', 'error')}
    got = H.walk([said('x', T0), old])
    check(T0 < got['until'] <= T0 + 86401, 'no resetsAt: the next such time after the error', got['until'])


def test_held_reopened():
    print('B170: an ended session is reopened from its transcript, also by a run that was down; a closed one is not')
    with held_world() as w:
        w.rows['a'] = four()
        w.up(5, 'a', 41)
        w.live.clear()  # it ended, and the run was down at the reset
        w.notes('control5.in').unlink()
        w.tick(RESET + 61)
        eq((w.opened, w.typed), ([(5, 'a')], []), 'reopened first')
        w.tick(RESET + 70)
        eq(len(w.opened), 1, 'once')
        w.up(5, 'a', 42, ago=-65)
        w.tick(RESET + 80)
        eq(w.typed, [], 'not typed into while it starts')
        w.tick(RESET + 200)
        eq([n for n, _ in w.typed], [5], 'then typed in')
        w.tick(RESET + 300)
        eq((len(w.typed), len(w.opened)), (1, 1), 'once')
        w.live.clear()  # and it dies before it takes them
        w.tick(RESET + 400)
        eq(len(w.opened), 2, 'a process that ended unanswered is reopened, not given up')
    with held_world() as w:
        w.rows['a'] = four()
        w.up(5, 'a', 41)
        w.tick(T0 + 200)
        w.live.clear()
        from agent_runner import control_reopen as CR
        CR.forget_control(5, 'it ended while the machine was up')
        w.rows['new'] = []
        w.up(5, 'new', 50)  # its number is another session's now
        K.control_keep_sid(5, 'new')
        w.outside.append('a')
        w.tick(RESET + 61)
        eq(w.opened, [], 'not while someone else has that conversation open')
        w.outside.clear()
        w.tick(RESET + 91)
        eq([s for _, s in w.opened], ['a'], 'reopened after its pid file is gone')
        check(w.opened[0][0] not in (1, 5), 'under a free number', w.opened)
        eq(w.H.pid_sid(5), (50, 'new'), 'the session that has its number is left alone')
    for how in ('end', 'exit', 'clear', 'online'):
        with held_world() as w:
            w.rows['a'] = four()
            w.up(5, 'a', 41)
            w.tick(T0 + 200)
            if how == 'end':
                with mock.patch.object(K.plat, 'terminate', lambda p: None):
                    K.end_control(5, 'deleted from the run page')
                w.live.clear()
            elif how == 'exit':
                w.rows['a'].append(said('<command-name>/exit</command-name>', T0 + 300))
                w.live.clear()
            elif how == 'clear':
                w.rows['new'] = []
                w.up(5, 'new', 41)
            else:
                w.rows['a'].append({'type': 'system', 'content': 'Remote Control disconnected (code 4090)'})
            w.tick(RESET + 61)
            w.tick(RESET + 400)
            eq((w.opened, w.typed, w.H.records()), ([], [], []), f'closed on purpose ({how}): not resumed')


# --- B173: cut-off replies, and sessions started from the Claude apps ---------------------------------------------

def tool(at, **kw):
    d = answer('', at, **kw)
    d['message'].update(stop_reason='tool_use', content=[{'type': 'tool_use', 'id': 't', 'name': 'Bash', 'input': {}}])
    return d


def result(at):
    return {'type': 'user', 'timestamp': stamp(at),
            'message': {'content': [{'type': 'tool_result', 'tool_use_id': 't', 'content': 'ok'}]}}


def ended(text, at):
    d = answer(text, at)
    d['message']['stop_reason'] = 'end_turn'
    return d


def test_held_cut_off():
    print('B173: a message whose reply a usage limit cut off is held too, and goes in once')
    from agent_runner import control_held as H

    def asks(rows, was=0.0):
        return [a['text'] for a in H.walk(rows, was)['asks']]
    ask = said('fix the login', T0)
    eq(asks([ask, answer('I will look', T0 + 1), limit(T0 + 2)]), ['fix the login'], 'after text')
    eq(asks([ask, tool(T0 + 1), result(T0 + 2), limit(T0 + 3)]), ['fix the login'], 'after a tool call')
    late = {'type': 'attachment', 'uuid': 'q', 'timestamp': stamp(T0 + 3), 'attachment': {
        'type': 'queued_command', 'commandMode': 'prompt', 'prompt': 'and the logout', 'source_uuid': 'q1'}}
    eq(asks([ask, tool(T0 + 1), result(T0 + 2), late, answer('both then', T0 + 4), limit(T0 + 5)]),
       ['fix the login', 'and the logout'], 'with one typed during the turn')
    eq(asks([ask, tool(T0 + 1), result(T0 + 2), late, limit(T0 + 5)]), ['fix the login', 'and the logout'],
       'also when that one had no reply yet')
    eq(asks([ask, ended('fixed', T0 + 1), limit(T0 + 9)]), [], 'not once the reply ended')
    note = {'type': 'user', 'timestamp': stamp(T0 + 5), 'origin': {'kind': 'task-notification'},
            'message': {'content': '<task-notification>x</task-notification>'}}
    eq(asks([ask, answer('done', T0 + 1), note, tool(T0 + 6), limit(T0 + 7)]), [], 'nor when a notification\'s turn was cut')
    eq(asks([ask, tool(T0 + 1), limit(T0 + 2)], T0 + 10), [], 'nor what was dropped')
    eq(asks([ask, tool(T0 + 1), said('[Request interrupted by user]', T0 + 2), limit(T0 + 3)]), [], 'nor one interrupted')
    eq(asks([ask, tool(T0 + 1), limit(T0 + 2), said('go on', RESET + 1), ended('fixed', RESET + 2)]), [],
       'a later answered turn of the person\'s takes it')
    eq(H.walk([ask, tool(T0 + 1), limit(T0 + 2)])['answered'], {}, 'it does not count as answered')
    with held_world() as w:
        w.rows['a'] = [ask, tool(T0 + 1), result(T0 + 2), limit(T0 + 3)]
        w.up(5, 'a', 41)
        w.tick(T0 + 200)
        eq(w.typed, [], 'it waits for the reset')
        w.tick(RESET + 61)
        w.tick(RESET + 100)
        eq(len(w.typed), 1, 'typed in once')
        text = w.typed[0][1]
        check('fix the login' in text and 'its reply was cut off' in text, 'and said to be cut off', text)
        w.rows['a'] += [said(text, RESET + 62), tool(RESET + 63), limit(RESET + 64, resets=RESET + 9000)]
        w.tick(RESET + 400)
        eq(len(w.typed), 1, 'cut off again: it waits for the new reset')
        w.tick(RESET + 9061)
        eq(len(w.typed), 2, 'then goes in again')
        w.rows['a'] += [said(w.typed[1][1], RESET + 9062), ended('fixed', RESET + 9070)]
        w.tick(RESET + 9100)
        eq((len(w.typed), w.H.records()), (2, []), 'answered: done with')


APP = '919c84d4-9292-5e75-bd70-fde86b95629b'


@contextlib.contextmanager
def app_world():
    """`held_world` with a control server (pid 70) and its child `w.child`, a session started from the Claude apps."""
    from agent_runner import feed
    with held_world() as w, tempfile.TemporaryDirectory() as reg:
        w.child, w.server, w.dead, w.reg = 71, 70, set(), Path(reg)
        bridge = {'type': 'bridge-session', 'bridgeSessionId': 'session_x1', 'sessionId': APP}
        w.rows[APP] = [bridge] + [{**x, 'sessionId': APP} for x in four()]
        for pid, sid in ((71, APP), (72, 'aaaaaaaa-0000-4000-8000-000000000000')):  # 72: a person's own session
            (Path(reg) / f'{pid}.json').write_text(json.dumps(
                {'pid': pid, 'sessionId': sid, 'bridgeSessionId': 'session_x1'}), encoding='utf-8')
        w.rows['aaaaaaaa-0000-4000-8000-000000000000'] = [said('my own chat', T0), limit(T0 + 1)]
        with mock.patch.object(feed, 'claude_sessions_dir', lambda: Path(reg)), \
                mock.patch.object(K, 'control_server_live', lambda: w.server), \
                mock.patch.object(K, 'control_state', lambda rows: {'title': ''}), \
                mock.patch.object(K.plat, 'children', lambda p: [71] if p == 70 and 71 not in w.dead else []), \
                mock.patch.object(K.plat, 'started', lambda p: None), \
                mock.patch.object(K.plat, 'alive', lambda p: p in (70, 71, 41, 42) and p not in w.dead):
            yield w


def test_held_app_session():
    print('B173: a session started from the Claude apps: what it holds goes once into a numbered copy of it')
    with app_world() as w:
        w.tick(T0 + 200)
        eq([r['sid'] for r in w.H.records()], [APP], 'held; a person\'s own session is not')
        with mock.patch.object(w.H.time, 'time', lambda: T0 + 300):
            got = w.H.lines()
        check(len(got) == 1 and got[0].startswith('a chat from the Claude apps: 4 asks wait'), 'status says so', got)
        w.tick(RESET + 61)
        recs = w.H.records()
        eq((len(recs), recs[0].get('from')), (1, APP), 'copied')
        new = recs[0]['sid']
        rows = [json.loads(x) for x in Path(K.transcript(new)).read_text(encoding='utf-8').splitlines()]
        eq({x['sessionId'] for x in rows}, {new}, 'under its own id')
        check(not any(x['type'] == 'bridge-session' for x in rows), 'without the app session\'s Remote Control entry')
        w.tick(RESET + 70)
        w.tick(RESET + 80)
        eq([s for _, s in w.opened], [new], 'the copy is opened once')
        n = w.opened[0][0]
        check(n > 1, 'under a number from FIRST_CONTROL', n)
        w.up(n, new, 42, ago=-75)
        w.tick(RESET + 300)
        w.tick(RESET + 400)
        eq([x for x, _ in w.typed], [n], 'typed in once')
        text = w.typed[0][1]
        check(in_order(text, ORDER), 'all four, in order', text)
        w.rows[new] = [*rows, said(text, RESET + 301), ended('done', RESET + 310)]
        w.tick(RESET + 500)
        eq((w.H.records(), len(w.typed)), ([], 1), 'answered: done with')
        w.rows[APP] += [said('a sixth', RESET + 600), limit(RESET + 601, resets=RESET + 9000)]
        w.tick(RESET + 700)
        eq(w.H.records()[0]['asks'], 1, 'a later message there is held on its own')
        w.tick(RESET + 9061)
        w.tick(RESET + 9070)
        m, other = w.opened[-1]
        check(other != new, 'in a copy of its own', w.opened)
        w.up(m, other, 41, ago=-9075)
        w.live.pop(n, None) if m != n else None
        w.tick(RESET + 9300)
        check('a sixth' in w.typed[-1][1] and ORDER[0] not in w.typed[-1][1], 'without the earlier ones', w.typed[-1])
    with app_world() as w:
        w.rows[APP] = [said('fix the login', T0), tool(T0 + 1), result(T0 + 2), limit(T0 + 3)]
        w.tick(RESET + 61)
        eq([r.get('from') for r in w.H.records()], [APP], 'one whose reply was cut off too')
    with app_world() as w:
        w.tick(T0 + 200)
        w.rows[APP] += [said('hello?', RESET + 10), ended('all four then', RESET + 20)]
        w.tick(RESET + 61)
        eq((w.H.records(), w.opened), ([], []), 'answered in the app before that: nothing goes in')
    with app_world() as w:
        w.tick(RESET + 61)
        w.rows[APP] += [said('hello?', RESET + 62), ended('all four then', RESET + 63)]
        w.tick(RESET + 70)
        w.tick(RESET + 90)
        eq((w.H.records(), w.opened), ([], []), 'answered there after the copy, before it was opened: nor then')
    with app_world() as w:
        w.tick(T0 + 200)
        rec = w.H.records()[0]
        keep = dict(rec)
        w.tick(RESET + 61)
        w.H.save(keep)  # killed right after the copy: the app record is back
        (w.H.folder() / f'{APP}.dropped').unlink()
        w.tick(RESET + 70)
        eq(len([r for r in w.H.records() if r.get('from')]), 1, 'a run killed on the way makes no second copy')


def test_held_app_ended():
    print('B173: an app session the person closed is dropped; one that failed or ended with its server is not')
    with app_world() as w:
        w.rows[APP] = [said('fix it', T0), limit(T0 + 1), said('fix it', T0 + 60), limit(T0 + 61)]
        w.tick(RESET + 61)
        w.tick(RESET + 70)
        w.tick(RESET + 80)
        eq(len(w.H.records()), 1, 'sent twice: one copy')
    with app_world() as w:
        w.tick(T0 + 200)
        w.rows['bbbbbbbb-0000-4000-8000-000000000000'] = []
        (w.reg / '71.json').write_text(json.dumps(
            {'pid': 71, 'sessionId': 'bbbbbbbb-0000-4000-8000-000000000000'}), encoding='utf-8')
        w.tick(RESET + 61)
        eq((w.H.records(), w.opened), ([], []), '/clear there: dropped')
    for how, kept in (('closed', False), ('failed', True), ('server', True)):
        with app_world() as w:
            w.tick(T0 + 200)
            w.dead.add(71)
            if how == 'server':
                w.server = 0
            log = {'closed': 'Session completed (2h) cse_x1', 'failed': 'Session failed: Process exited with error cse_x1'}
            w.notes('control-server.log').write_text(f'[8A[J[02:05:39] {log.get(how, "")}\nCapacity: 0/32\n',
                                                     encoding='utf-8')
            w.tick(RESET + 61)
            eq([r.get('from') for r in w.H.records()], [APP] if kept else [], how)


@contextlib.contextmanager
def settled_world():
    """`held_world` with a plan: R81 under Needs you, R82 and R90 open; c4 opened from R81, c5 titled R81, c6 titled
    R90 and only mentioning R81."""
    from agent_runner import control_settled as Z, runner as R
    with held_world() as w:
        R.C.todo.parent.mkdir(parents=True, exist_ok=True)
        R.C.todo.write_text('# TODO\n\n## Now\n\n- [~] **R81** Tailscale login BLOCKED: CONFIRM: sign in on the phone\n'
                            '- [ ] **R82** the probe\n- [ ] **R90** other work\n', encoding='utf-8')
        git(R.ROOT, 'add', '-A')
        git(R.ROOT, 'commit', '-qm', 'plan')
        Z._SEEN.clear()
        Z.LEFT_AT[0] = 0.0
        w.Z, w.R = Z, R
        base = time.time()
        w.base = base
        w.rows['s4'] = [said("This chat is about R81 'Tailscale login', which needs me. What was put to me:", base - 900),
                        answer('Sign in on the phone, then say done.', base - 890)]
        w.rows['s5'] = [said('what is R82 about, and the login?', base - 900), answer('A login.', base - 890)]
        w.rows['s6'] = [said('compare R90 with R81', base - 900), answer('Done.', base - 890)]
        for n in (4, 5, 6):
            w.up(n, f's{n}', 40 + n)
            os.utime(w.notes(f'control{n}.pid'), (base - 800, base - 800))
        K.control_give(5, f'{R.ROOT.name} · R81 · Tailscale login')
        K.control_give(6, f'{R.ROOT.name} · 6 · R90 and R81')

        def plan_cmd(*argv, by=0, slot=''):
            from agent_runner import plan as P
            env = {'AGENT_RUNNER_CONTROL': str(by or ''), 'AGENT_RUNNER_SLOT': slot, 'AGENT_RUNNER_BY': ''}
            with mock.patch.dict(os.environ, env), mock.patch.object(P, 'cfg', lambda *a: R.C), \
                    mock.patch.object(P, 'other_project', lambda *a: ''), contextlib.redirect_stdout(io.StringIO()):
                return P.main(list(argv))
        w.plan = plan_cmd

        def look(at=0.0):
            for s in w.rows:
                K.transcript(s)
            Z.tick(force=True, now=at or base)
        w.look = look
        yield w


def test_settled_told_once():
    print('F160: a drop by one control session is typed once into the others about the item')
    with settled_world() as w:
        w.look()
        eq(w.typed, [], 'nothing settled: nothing typed')
        eq(w.plan('drop', 'R81', 'the phone is signed in', by=4), 0, 'c4 drops it')
        w.look()
        eq([n for n, _ in w.typed], [5], 'typed into the one titled R81; not its dropper, nor one that mentions it')
        check(re.fullmatch(r'From the runner, not the person: R81 was dropped at \d\d:\d\d by c4: the phone is signed in\. '
                           r'Re-read it before asking the person anything for it\.', w.typed[0][1]), 'the line', w.typed)
        w.look()
        w.look(w.base + 400)
        w.Z._SEEN.clear()  # a restarted run knows only the notes
        w.Z.LEFT_AT[0] = 0.0
        w.look(w.base + 4000)
        eq(len(w.typed), 1, 'not again, by a restarted run either')
    with settled_world() as w:
        w.plan('drop', 'R81', 'gone', by=4)
        with mock.patch.object(K, 'control_type', side_effect=KeyboardInterrupt):  # killed while it types
            try:
                w.look()
            except KeyboardInterrupt:
                pass
        w.look()
        eq(w.typed, [], 'a run killed while it typed does not type it again')


def test_settled_repeats_b812():
    print('B812: an edit of only the files says nothing; the same event again is one line')
    edit = ('edit', 'R81', 'sign in on the laptop')
    with settled_world() as w:
        for rest in (('--files', 'a.py'), ('--files', 'a.py,b.py'), ('--files', 'b.py'),
                     ('--files', 'b.py', '--pri', 'low'), ('--pri', 'normal', '--files', 'a.py')):
            eq(w.plan('edit', 'R81', *rest, slot='1'), 0, f'edit {rest}')
        w.look()
        eq(w.typed, [], 'files and place: nothing typed')
        w.plan('edit', 'R81', '--after', 'R90', slot='1')
        w.look()
        eq([n for n, _ in w.typed], [4, 5], 'what it waits for is told')
    with settled_world() as w:
        w.plan(*edit, slot='1')
        w.look()
        w.plan(*edit, '--files', 'a.py', slot='1')
        w.look()
        eq([n for n, _ in w.typed], [4, 5], 'the same text again: one line each')
        w.Z._SEEN.clear()
        w.plan(*edit, slot='1')
        w.look()
        eq(len(w.typed), 2, 'nor by a restarted run')
        w.plan('edit', 'R81', 'sign in on the tablet', slot='1')
        w.look()
        eq(len(w.typed), 4, 'another text is told')
        w.plan('edit', 'R81', 'sign in on the tablet', slot='2')
        w.look()
        eq(len(w.typed), 6, 'another author too')
        w.plan('drop', 'R81', 'no need', slot='2')
        w.look()
        eq([('was dropped' in t) for _, t in w.typed[6:]], [True, True], 'a later drop too')
        w.plan('restore', 'R81', slot='2')
        w.plan('drop', 'R81', 'no need', slot='2')
        w.look()
        eq(len(w.typed), 12, 'the same drop after a restore is no repeat')
    with settled_world() as w:
        w.plan('change', 'R81', 'use the laptop', slot='1')
        w.look()
        w.plan('change', 'R81', 'use the tablet', slot='1')
        w.look()
        eq(len(w.typed), 4, 'another reason is told')
    with settled_world() as w:
        w.plan('drop', 'R81', 'x', slot='1')
        w.look()
        w.plan('restore', 'R81', by=4)
        w.plan('drop', 'R81', 'x', slot='1')
        w.look()
        eq([n for n, t in w.typed if n == 4], [4, 4], "a session's own command between them ends the repeat")
    with settled_world() as w:
        w.plan(*edit, slot='1')
        w.plan('edit', 'R81', 'sign in on the tablet', slot='1')
        w.look()
        eq([n for n, _ in w.typed], [4, 5], 'two that waited together: one line each')
    with settled_world() as w:
        w.plan(*edit, slot='1')
        with mock.patch.object(w.Z, 'time', types.SimpleNamespace(time=lambda: w.base - w.Z.AGAIN - 60,
                                                                  time_ns=lambda: 1)):
            w.plan(*edit, slot='1')
        for f in w.Z.folder(w.R.C).glob('1-*.json'):
            check(json.loads(f.read_text(encoding='utf-8'))['at'] < w.base - w.Z.AGAIN, 'an old event')
        os.utime(w.notes('control4.pid'), (w.base, w.base))  # just started: it waits
        os.utime(w.notes('control5.pid'), (w.base, w.base))
        w.look()
        eq(w.typed, [], 'both wait')
        w.look(w.base + 200)
        eq([n for n, _ in w.typed], [4, 5], 'one still waiting is replaced, however old')
        check(not list(w.Z.folder(w.R.C).glob('*-*.json')), 'no event is left')
    with settled_world() as w:
        with mock.patch.object(w.Z, 'time', types.SimpleNamespace(time=lambda: w.base - w.Z.AGAIN - 60,
                                                                  time_ns=lambda: 1)):
            w.plan(*edit, slot='1')
        w.look()
        w.plan(*edit, slot='1')
        w.look()
        eq(len(w.typed), 4, 'past the window it is told again')
    with settled_world() as w:
        with mock.patch.object(w.Z, 'time', types.SimpleNamespace(time=lambda: w.base - 42, time_ns=lambda: 1)):
            w.plan(*edit, slot='1')
        w.look()
        w.plan(*edit, slot='1')
        w.look()
        eq(len(w.typed), 2, '42 s later it is not')
    with settled_world() as w:
        for end in ('laptop', 'tablet'):
            w.plan('change', 'R81', 'sign in ' + 'again ' * 40 + end, slot='1')
        w.look()
        eq(len(w.typed), 4, 'two reasons that differ only past the cut are both told')


def test_settled_verbs_and_openers():
    print('F160: what is told, by whom, and which sessions are about an item')
    with settled_world() as w:
        w.plan('shelve', 'R81')
        w.look()
        eq(sorted(n for n, _ in w.typed), [4, 5], 'a terminal\'s shelve: both, with no author')
        check(' was shelved at ' in w.typed[0][1] and ' by ' not in w.typed[0][1], 'worded', w.typed[0])
        w.typed.clear()
        for argv, what in ((('unshelve', 'R81'), 'was put back'), (('change', 'R81', 'use the laptop'), 'was changed'),
                           (('drop', 'R81', 'no'), 'was dropped'), (('restore', 'R81'), 'was restored')):
            eq(w.plan(*argv), 0, argv[0])
            w.look()
            check([n for n, _ in w.typed] == [4, 5] and what in w.typed[0][1], argv[0], w.typed)
            w.typed.clear()
        for argv in (('note', 'R81', 'x'), ('drop', 'R82', 'x'), ('move', 'R81', 'top'), ('edit', 'R90', '--pri', 'normal')):
            w.plan(*argv)
        w.look()
        eq(w.typed, [], 'a note, a move or another item says nothing')
    from agent_runner import control_settled as Z
    for title, want in (('p · R81 · login', 'R81'), ('p · 5 · R81: yes', 'R81'), ('R81 Tailscale', 'R81'),
                        ('p · 5 · about R81', ''), ('p · control 5', ''), ('R812x', 'R812x'), ('C1-only', '')):
        eq(Z.title_id(title, 'p'), want, title)
    from agent_runner import ui_model as U
    for text in (U.need_chat_text({'id': 'R81', 'title': 'a', 'ask': 'b', 'what': ''}),
                 U.concept_chat_text({'concept': 'K2', 'title': 't'}), 'R81 (a (b) c): yes', 'R81: yes'):
        m = Z.OPENED.match(text)
        check(m and (m[1] or m[2]) in ('R81', 'K2'), f'opened from its item: {text[:40]}')
    check(not Z.OPENED.match('what of R81: is it on?'), 'a mention is not')
    got = []
    with mock.patch.object(U.sp, 'run', lambda a, **k: got.append(k['env']) or types.SimpleNamespace(
            returncode=0, stdout='', stderr='')), mock.patch.dict(os.environ, {'AGENT_RUNNER_CONTROL': '4'}):
        U._run(['plan', 'drop', 'R81', 'x'])
    check('AGENT_RUNNER_CONTROL' not in got[0] and got[0]['AGENT_RUNNER_BY'] == 'the person in the run app',
          'the run app\'s command is the person\'s, not the session\'s that started the run')


def test_settled_closes_f209b():
    print('F209b: what the person settles for good outside a chat closes the chats about it, unless one keeps it')
    from agent_runner import control_held as H, control_settled as Z, sched, taken_by, ui_model as U

    def by_person(w, *argv):
        with mock.patch.dict(os.environ, {'AGENT_RUNNER_BY': Z.PERSON_BY, 'AGENT_RUNNER_CONTROL': '', 'AGENT_RUNNER_SLOT': ''}):
            from agent_runner import plan as P
            with mock.patch.object(P, 'cfg', lambda *a: w.R.C), mock.patch.object(P, 'other_project', lambda *a: ''), \
                    contextlib.redirect_stdout(io.StringIO()):
                return P.main(list(argv))

    @contextlib.contextmanager
    def world():
        with settled_world() as w:
            w.ended = []
            with mock.patch('agent_runner.plat.terminate', lambda p: w.ended.append(p)):
                yield w

    with world() as w:
        eq(by_person(w, 'drop', 'R81', 'not needed'), 0, 'dropped on the run page')
        w.look()
        eq((sorted(w.ended), w.typed), ([44, 45], []), 'both chats on R81 close, nothing typed; c6 only mentions it')
        check(not w.notes('control4.pid').exists() and w.notes('control4.closed').exists(), 'listed as closed, resumable')
        check(any('control 4: closed, R81 was dropped by the person' in x for x in w.logs), 'run.log names the item', w.logs)
        w.Z._SEEN.clear()
        w.look(w.base + 400)
        eq(len(w.ended), 2, 'a restarted run closes nothing twice')
    with world() as w:
        eq(by_person(w, 'shelve', 'R81'), 0, 'shelved')
        w.look()
        eq((w.ended, [n for n, _ in w.typed]), ([], [4, 5]), 'shelve types the line as now')
    for verb, ended in (('revise', []), ('approve', [46])):
        with world() as w:
            K.control_give(6, f'{w.R.ROOT.name} · 6')
            w.plan('concept', 'the menu', '--page', 'https://claude.ai/code/artifact/aaa', by=6)
            w.look()
            eq(by_person(w, verb, 'K1', 'rounder'), 0, verb)
            w.look()
            eq((w.ended, [n for n, _ in w.typed]), (ended, [] if ended else [6]), f'{verb} of a concept its chat filed')
    with world() as w:
        w.plan('change', 'R81', 'No: the check failed')
        w.look()
        eq(w.ended, [], 'by no person: nothing closes')
    with world() as w:
        eq(w.plan('drop', 'R81', 'gone', by=6), 0, 'a chat drops it')
        w.look()
        eq((w.ended, [n for n, _ in w.typed]), ([], [4, 5]), 'a chat\'s decision types the line')
    keeps = {
        'person': lambda w: w.rows['s4'].append(said('wait', w.base - 800)),
        'decide': lambda w: w.rows['s4'].append(answer('DECIDE: which login next? [a / b]', w.base - 800)),
        'running': lambda w: w.rows['s4'].append({**answer('started', w.base - 800), 'bg': True}),
        'renamed': lambda w: w.rows['s4'].append({'type': 'custom-title', 'customTitle': 'my login chat'}),
        'other': lambda w: (w.plan('block', 'R82', 'CONFIRM: look'),
                            w.rows['s4'].__setitem__(0, said("This chat is about R82 'probe', which needs me.", w.base - 900)),
                            w.Z.filed(w.R.C, ['R81'], {'n': 4, 'sid': 's4'})),
    }

    def bg_state(r, f=K.control_state):  # a background task, as control_state reads one, in the chat marked so
        rows = list(r)
        return {**f(rows), 'running': {'b1'} if any(x.get('bg') for x in rows) else set()}
    for name, make in keeps.items():
        with world() as w:
            make(w)
            with mock.patch.object(K, 'control_state', bg_state):
                by_person(w, 'drop', 'R81', 'x')
                w.look()
            eq((w.ended, sorted(n for n, _ in w.typed)), ([45], [4]), f'{name}: c4 kept and told, c5 closed')
            check(any('control 4: kept open' in x for x in w.logs), f'{name}: logged', w.logs)
    for name in ('held', 'dialog', 'take'):
        with world() as w:
            pats = [mock.patch.object(H, 'holds', lambda s: s == 's4' and name == 'held'),
                    mock.patch.object(sched, 'taken', lambda: {'R81': Path('/x')} if name == 'take' else {}),
                    mock.patch.object(taken_by, 'chat', lambda c, d, live: 4 if live == [4] else 0)]
            if name == 'dialog':
                w.rows['s4'].append({'type': 'assistant', 'timestamp': stamp(w.base - 800), 'message': {
                    'content': [{'type': 'tool_use', 'id': 't1', 'name': 'AskUserQuestion', 'input': {}}]}})
            with contextlib.ExitStack() as st:
                for p in pats:
                    st.enter_context(p)
                by_person(w, 'drop', 'R81', 'x')
                w.look()
            eq(w.ended, [45], f'{name}: c4 kept')
            check(name == 'dialog' or any('control 4: kept open' in x for x in w.logs), f'{name}: logged', w.logs)
    with world() as w:
        w.rows['s4'].append({'type': 'assistant', 'timestamp': stamp(w.base - 800), 'message': {
            'content': [{'type': 'tool_use', 'id': 't2', 'name': 'Bash', 'input': {'command': 'ls'}}]}})
        by_person(w, 'drop', 'R81', 'x')
        w.look()
        eq(w.ended, [45], 'a turn under way: not yet')
        w.rows['s4'] += [{'type': 'user', 'timestamp': stamp(w.base - 700), 'message': {
            'content': [{'type': 'tool_result', 'tool_use_id': 't2', 'content': 'ok'}]}}, answer('Done.', w.base - 690)]
        w.Z._SEEN.clear()
        w.look(w.base + 60)
        eq((sorted(w.ended), w.typed), ([44, 45], []), 'looked at again once it ended: closed')
    with world() as w:  # the pick link runs `sheet` through the run app's command, which marks it the person's
        got = []
        with mock.patch.object(U.sp, 'run', lambda a, **k: got.append(k['env']) or types.SimpleNamespace(
                returncode=0, stdout='', stderr='')):
            U._run(['sheet', 'R81', '--go'])
        eq(got[0]['AGENT_RUNNER_BY'], Z.PERSON_BY, 'a pick link\'s sheet is the person\'s')


def test_settled_concept_chat():
    print('B219a1: a chat whose first message the run page made for a concept is told of its pick and its drop')
    from agent_runner import plan as P, ui_model as U
    url, title = 'https://claude.ai/code/artifact/aaa', "the run page's (new) menu"
    lead = U.concept_chat_text({'concept': 'K1', 'id': 'F1', 'title': title, 'url': url, 'copy': '/x/K1.html'})
    for argv, what in ((('approve', 'F1', 'option B'), 'K1 was approved'), (('confirm', 'K1', 'option B'), 'K1 was answered'),
                       (('drop', 'F1', 'no need'), 'K1 was dropped')):
        with settled_world() as w:
            w.R.C.todo.write_text(w.R.C.todo.read_text(encoding='utf-8') +
                                  f"- [~] **F1** Build the option a person approves on concept K1's page: {title} "
                                  f'BLOCKED: {P.WAIT_OK}{url} (asked 2026-11-24 10:00)\n', encoding='utf-8')
            # as 020-chats.logic.js compose() words them: now, and by a page kept open from before B219a
            first = {4: f"{lead}\n\nwhy B?\n\nK9: isn't it\nthe 'same'?\n\nAttached: /x/a.png", 5: lead,
                     6: f'About concept K1 ({title}): why B?\nR90: and this?', 7: 'About concept K1: why B?',
                     8: 'what About concept K1: is it?'}
            for n, text in first.items():
                w.rows[f's{n}'] = [said(text, w.base - 900), answer('Reading it.', w.base - 890)]
                if n > 6:
                    w.up(n, f's{n}', 40 + n)
                os.utime(w.notes(f'control{n}.pid'), (w.base - 800, w.base - 800))
                K.control_give(n, f'{w.R.ROOT.name} · {n}')
            w.look()
            eq(w.typed, [], f'{argv[0]}: nothing settled, nothing typed')
            eq(w.plan(*argv), 0, f'{argv[0]} {argv[1]}')
            w.look()
            eq(sorted(n for n, _ in w.typed), [4, 5, 6, 7], f'{argv[0]} {argv[1]}: each chat opened from it, not a mention')
            check(all(f'{what} at ' in t for _, t in w.typed), f'worded: {what}', w.typed)


def test_settled_about_chat():
    print('B226: a chat that starts with the About line of a task or a need is told when that item is settled')
    title = "the run page's (new) menu: it's [wide]"
    first = {4: f"About R90 ({title}): why?\n\nR82: isn't it\nthe 'same' (really)?\n\nAttached: /x/a.png",
             5: f"About R81 ({title}), which needs me: I can't\nsign in (yet)\n\nR90: and this?",
             6: 'About R90: why?', 7: 'About R81, which needs me: why?', 8: 'what About R90: is it?',
             9: 'About R90 and R81: which?', 10: 'About the R81 (login): is it?'}
    for argv, what, told in ((('drop', 'R90', 'no need'), 'R90 was dropped', [4, 6]),
                             (('change', 'R90', 'use the laptop'), 'R90 was changed', [4, 6]),
                             (('drop', 'R81', 'no need'), 'R81 was dropped', [5, 7]),
                             (('confirm', 'R81', 'it works'), 'R81 was answered', [5, 7])):
        with settled_world() as w:
            for n, text in first.items():  # as 020-chats.logic.js compose() words them
                w.rows[f's{n}'] = [said(text, w.base - 900), answer('Reading it.', w.base - 890)]
                if n > 6:
                    w.up(n, f's{n}', 40 + n)
                os.utime(w.notes(f'control{n}.pid'), (w.base - 800, w.base - 800))
                K.control_give(n, f'{w.R.ROOT.name} · {n}')
            w.look()
            eq(w.typed, [], f'{argv[0]}: nothing settled, nothing typed')
            eq(w.plan(*argv), 0, f'{argv[0]} {argv[1]}')
            w.look()
            eq(sorted(n for n, _ in w.typed), told, f'{argv[0]} {argv[1]}: each chat opened from it, not a mention')
            check(all(f'{what} at ' in t for _, t in w.typed), f'worded: {what}', w.typed)


def test_settled_filed():
    print('F209a, F211: a chat is about the concept, restyle or DECIDE it filed itself')
    from agent_runner import plan as P
    url = 'https://claude.ai/code/artifact/aaa'
    for tid, by, told in (('K1', 4, [6]), ('F1', 4, [6]), ('K1', 0, [6]), ('K1', 6, []), ('F1', 6, [])):
        with settled_world() as w:
            K.control_give(6, f'{w.R.ROOT.name} · 6')
            eq(w.plan('concept', 'the menu', '--page', url, by=6), 0, 'c6 files it')
            eq((P.waiting(w.R.C.todo)[0][:2]), ('F1', 'K1'), 'as K1 with its build F1')
            w.look()
            eq(w.typed, [], 'filing it says nothing')
            eq(w.plan('approve', tid, 'option B', by=by), 0, 'approved')
            w.look()
            w.look(w.base + 400)
            w.look(w.base + 4000)
            eq([n for n, _ in w.typed], told, f'approve {tid} by c{by}: the filer is told once, not of its own')
            check(all(f'{tid} was approved at ' in t for _, t in w.typed), 'worded', w.typed)
    for tid, by, told in (('K1', 4, [6]), ('F1', 4, [6]), ('K1', 0, [6]), ('K1', 6, []), ('F1', 6, [])):
        with settled_world() as w:
            K.control_give(6, f'{w.R.ROOT.name} · 6')
            eq(w.plan('restyle', 'rounder buttons', '--page', url, by=6), 0, 'c6 files the restyle')
            eq(w.Z.about(6, 's6', {}), {'K1', 'F1'}, 'about it and its build')
            w.look()
            eq(w.typed, [], 'filing it says nothing')
            eq(w.plan('approve', tid, 'go', by=by), 0, 'approved')
            w.look()
            w.look(w.base + 400)
            w.look(w.base + 4000)
            eq([n for n, _ in w.typed], told, f'approve {tid} of a restyle by c{by}: the filer is told once, not of its own')
            check(all(f'{tid} was approved at ' in t for _, t in w.typed), 'worded', w.typed)
    with settled_world() as w:
        K.control_give(6, f'{w.R.ROOT.name} · 6')
        w.plan('concept', 'the menu', '--page', url, by=6)
        w.plan('concept', 'the tabs', '--page', url + 'b', by=6)
        eq(w.Z.about(6, 's6', {}), {'K1', 'F1', 'K2', 'F2'}, 'all it filed, each with its build')
        w.rows['new'] = [said('hi', w.base - 900), answer('Hello.', w.base - 890)]
        w.up(6, 'new', 51)
        os.utime(w.notes('control6.pid'), (w.base - 800, w.base - 800))
        w.up(7, 's6', 46)
        os.utime(w.notes('control7.pid'), (w.base - 800, w.base - 800))
        K.control_give(7, f'{w.R.ROOT.name} · 7')
        eq(w.Z.about(6, 'new', {}), set(), 'another session with its number is not about them')
        w.plan('approve', 'K1', 'A', by=6)
        w.look()
        eq([n for n, _ in w.typed], [7], 'the filer is told, also under another number; not who has its number now')
    with settled_world() as w:
        w.plan('concept', 'the menu', '--page', url, slot='2', by=6)
        w.plan('concept', 'the tabs', '--page', url)
        check(not list(w.Z.folder(w.R.C).glob('*.filed')), 'a slot\'s or a terminal\'s is no chat\'s')
    with settled_world() as w:
        K.control_give(6, f'{w.R.ROOT.name} · 6')
        w.plan('concept', 'the menu', '--page', url, by=6)
        w.look()
        P.approve('K1', 'A', todo=w.R.C.todo)  # a pulled plan: no command here
        for at in (40, 400, 440):
            w.look(w.base + at)
        eq([n for n, _ in w.typed], [6], 'left Needs you with no command: one line for the two ids')
        check('F1 was reopened' in w.typed[0][1], 'worded', w.typed)
    with settled_world() as w:
        K.control_give(6, f'{w.R.ROOT.name} · 6')
        w.plan('block', 'R82', 'CONFIRM: look', by=6)
        eq(w.Z.about(6, 's6', {}), set(), 'a CONFIRM is not a DECIDE')
        w.plan('block', 'R90', 'DECIDE: which?', by=6)
        eq(w.Z.about(6, 's6', {}), {'R90'}, 'a DECIDE it blocked a task with')
        tid = K.file_control_ask(6, 's6', 'Which look?', '')
        check(tid and tid in w.Z.about(6, 's6', {}), 'its open question, filed by the run', tid)
        w.plan('confirm', tid, 'the small one')
        w.look()
        eq([n for n, _ in w.typed], [6], 'reopened, it is told of the answer')


def test_settled_waits_and_skips():
    print('F160: not typed where it would be lost; ended and closed sessions are left alone; no person\'s message')
    with settled_world() as w:
        ask = {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'id': 'q', 'name': 'AskUserQuestion'}]}}
        w.rows['s5'] = w.rows['s5'] + [ask]
        os.utime(w.notes('control4.pid'), (w.base, w.base))  # just started
        w.plan('confirm', 'R81', 'signed in', slot='2')
        w.look()
        eq(w.typed, [], 'a question dialog and a starting session wait')
        w.rows['s5'] = w.rows['s5'] + [{'type': 'user', 'message': {'content': [
            {'type': 'tool_result', 'tool_use_id': 'q', 'content': 'ok'}]}}]
        w.look(w.base + 200)
        eq([n for n, _ in w.typed], [4, 5], 'then both are told')
        check("by s2's agent: signed in." in w.typed[0][1], 'by a slot', w.typed[0])
        text = w.typed[0][1]
        rows = [*w.rows['s5'], said(text, w.base)]
        eq(K.control_state(rows)['said'], 1, 'it is not counted as a message of the person\'s')
        check(not K.person_turn(said(text, w.base)) and not K.person_message(said(text, w.base)) and
              not K.person_message(said([{'type': 'text', 'text': text}], w.base)), 'nor read as one')
        held = w.H.walk([said('real ask', T0), answer('ok', T0 + 1), said(text, T0 + 2), limit(T0 + 3)])
        eq(held['asks'], [], 'nor held when it meets the usage limit')
    with settled_world() as w:
        w.live.pop(5)
        w.rows['s4'] = w.rows['s4'] + [{'type': 'system', 'content': 'Remote Control disconnected — archived (code 4090)'}]
        w.plan('drop', 'R81', 'x')
        w.look()
        w.live[5] = 45
        w.look(w.base + 100)
        eq(w.typed, [], 'an ended session and one closed online are not told, nor when reopened')


def test_settled_landing():
    print('F160: a landing is told only to a chat that waited on the item under Needs you')
    with settled_world() as w:
        from agent_runner import plan as P
        w.rows['s6'] = [said('R82: how far is it?', w.base - 900)]
        w.look()
        for t in ('R82', 'R81'):
            P.unblock(t, 'x', todo=w.R.C.todo) if t == 'R81' else None
            P.tick(t, w.R.C.todo, w.R.C.done)
        w.look(w.base + 40)
        eq(w.typed, [], 'a command\'s own event gets its time')
        w.look(w.base + 400)
        w.look(w.base + 440)
        eq([n for n, _ in w.typed], [4, 5], 'the chats on the Needs you item; not the one on an ordinary task')
        check('R81 landed at ' in w.typed[0][1], 'said as landed', w.typed[0])
        w.look(w.base + 900)
        eq(len(w.typed), 2, 'once')
    with settled_world() as w:
        from agent_runner import plan as P
        w.look()
        with mock.patch.dict(os.environ, {'AGENT_RUNNER_CONTROL': '5', 'AGENT_RUNNER_SLOT': ''}):
            w.Z.done_by(w.R.C, 'R81')
        P.unblock('R81', 'x', todo=w.R.C.todo)
        P.tick('R81', w.R.C.todo, w.R.C.done)
        for at in (40, 400, 440):
            w.look(w.base + at)
        eq([n for n, _ in w.typed], [4], 'not into the session that landed it')


def test_settled_rule_in_guide():
    print('F160: the needs guide carries the re-read rule, and the brief points at it')
    from agent_runner import guide as G
    page = ' '.join(G.topic('needs', 'run').split())
    for words in ('Re-read it (`run plan ID`) right before you ask', 'on each follow-up', 'say so at once',
                  'stop every watch', 'reservation', 'From the runner, not the person:'):
        check(words in page, words)
    check('Re-read an item right before' in ' '.join(G.CONTROL.split()), 'the brief says it')


def test_shell_rule_b880():
    print('B880: the control brief and the concepts guide say one plain command per bash call, files by the edit tools')
    from agent_runner import guide as G
    for name, text in (('brief', G.CONTROL), ('concepts', G.topic('concepts', 'run'))):
        page = ' '.join(text.split())
        for words in ('edit/write tools', 'never a python or sed heredoc', 'one plain command per bash call',
                      'absolute paths', 'no shell variables', 'no `&&` chains', '`| tail`'):
            check(words in page, f'{name}: {words}')


def test_decide_options_f181d():
    print('F181d: a control session ends its DECIDE with the options, and filing keeps the bracket for the buttons')
    from agent_runner import guide as G, need_detail as N, plan as P, runner as R
    core = ' '.join(G.CONTROL.split())
    for words in ('holding it up? [Yes (recommended) / No]`', 'any link after the bracket',
                  'One DECIDE per question'):
        check(words in core, f'the brief: {words}')
    check('[Full (recommended) / Small]' in G.topic('needs', 'run'), 'the needs guide says what the bracket is')
    d = Path(tempfile.mkdtemp(prefix='agent-runner-decide-'))
    git(d, 'init', '-q')
    (d / 'plan').mkdir()
    (d / 'plan' / 'TODO.md').write_text('# TODO\n\n### Next\n\n- [ ] **F1** other | files: a.py\n', encoding='utf-8')
    git(d, 'add', '-A')
    git(d, 'commit', '-qm', 'start')
    R.init(d)
    eq(K.ROOT, d.resolve(), 'B874: control files in the temp repo, never the checkout')
    todo, link, names = d / 'plan' / 'TODO.md', 'https://claude.ai/code/session_01AbC', ['Full', 'Small', 'No change']
    more = ' https://example.com/a'
    for n, (words, after) in enumerate((('Which look?', ''), ('Which look? ' + 'It is a long story. ' * 20, ''),
                                        ('Which look?', more), ('Which look? ' + 'It is a long story. ' * 20, more))):
        q = P.decide_question(f'Two ways.\n\n**DECIDE: {words.strip()} [Full (recommended) / Small / No change]{after}**')
        check(q.startswith(words.strip()) and '…' not in q, f'{n}: {len(q)} characters, whole', q)
        tid = K.file_control_ask(n + 3, f'sid-{n}', q, link)
        a = next(x for x in P.asks(todo) if x[1] == tid)
        line = next(x for x in todo.read_text(encoding='utf-8').splitlines() if f'**{tid}**' in x)
        opts, what = N.decide_options(tid, a[3], line)
        eq([o['name'] for o in opts], names, f'{n}: filed as {tid}, its options are buttons')
        check(opts and opts[0]['rec'] and what.startswith('Which look?') and '[' not in what, f'{n}: and off the question', what)
    long = 'Which look? [' + ' / '.join(f'{c * 60}' for c in 'abcd') + ']'
    eq(P.decide_question(f'DECIDE: {long}'), long, 'a long bracket costs a short question no word')
    plain = ('word ' * 100).strip()
    eq(P.decide_question(f'DECIDE: {plain}'), plain, 'B840: over 240 with no bracket: whole')
    q = P.decide_question('DECIDE: ' + 'word ' * 900 + '[Yes / No] https://example.com/a')
    check(len(q) <= P.QUESTION_MAX and q.endswith('… [Yes / No] https://example.com/a'), 'past the guard: cut before its bracket', len(q))


def test_wrong_agent_b764c():
    print('B764c: while [run] agent is wrong a new control session is refused with the reason, and none is reopened')
    from agent_runner import cmds, config as CF, control_held as H, control_reopen as CR, feed, runner as R, session_now as SN, web as W
    d = Path(tempfile.mkdtemp(prefix='agent-runner-agent-'))
    git(d, 'init', '-q')
    (d / 'my-claude').write_text('#!/bin/sh\n', encoding='utf-8')
    (d / 'my-claude').chmod(0o755)
    local = d / 'runner.local.toml'
    local.write_text("[run]\nagent = 'my-claude'\nremote = false\n", encoding='utf-8')
    CF._cfg.cache_clear()
    R.init(d)
    started, reopened = [], []

    def ask(fn) -> tuple[int, str]:
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(err):
            return fn(), err.getvalue()

    with mock.patch.object(feed, 'hidden_control', lambda n, cmd: started.append(n) or (1, '')), \
            mock.patch.object(K, 'hidden_control', lambda n, cmd: started.append(n) or (1, '')), \
            mock.patch.object(cmds, 'init', lambda *a: None), mock.patch.object(cmds, 'control_open', lambda *a, **k: started.append(a)), \
            mock.patch.object(W, 'session_live', lambda n: False), mock.patch.object(W, 'resumable', lambda n: 'sid'), \
            mock.patch.object(CR, 'reopen_controls', lambda: reopened.append(1)):
        local.write_text("[run]\nagent = 'nosuchagent'\nremote = false\n", encoding='utf-8')
        for name, fn in (('--new', lambda: feed.control_new(ask='hi')), ('control N', lambda: cmds.cmd_control(['3']))):
            code, said = ask(fn)
            check(code == 1 and "[run] agent = 'nosuchagent' is not on this machine: install it" in said, f'{name} is refused, with why', said)
        check('install it' in W.resume_chat('c3')['out'], 'so is Resume on an ended chat')
        with mock.patch.object(SN, 'record', lambda c: {'status': 'idle', 'sessionId': 'sid', 'pid': 1}), \
                mock.patch.object(K, 'transcript', lambda s: '/x'), mock.patch.object(SN.plat, 'terminate') as end:
            got = SN.restart_chat('c3')
        check('install it' in got['out'] and not got['ok'] and not end.called, 'Restart too, and the chat goes on', got)
        eq(CR.reopen_control(3, 'sid'), '', 'nothing reopens one')
        stayed = []
        with mock.patch.object(H, 'stays', lambda rec, why='', stuck='': stayed.append(why)), \
                mock.patch('agent_runner.watch.live_session', lambda sid: False), mock.patch.object(K, 'control_taken', lambda n: False):
            rec = {'n': 3, 'sid': 'sid', 'reopened': 1.0, 'tries': 1}
            H.step_ended(rec, time.time())
        check('install it' in stayed[0] and rec['tries'] == 1, 'an ended one with held messages waits, and it is no try', stayed)
        K.start_control()
        K.reopen_when_right()
        eq((started, reopened), ([], []), 'those a shutdown cut off wait too')
        off, popped = K.threading.Event(), []
        with mock.patch.object(K, 'control_server_live', lambda: 0), mock.patch.object(K, 'rc_record'), \
                mock.patch.object(K, 'control_server_argv', lambda: popped.append('asked') or ['true', '--settings']), mock.patch('atexit.register'), \
                mock.patch.object(K, 'backend'), mock.patch.object(off, 'wait', lambda s: off.set()):
            K.keep_control_server(off)
        eq(popped, [], 'the control server does not start')
        local.write_text("[run]\nagent = 'my-claude'\nremote = false\n", encoding='utf-8')
        K.reopen_when_right()
        K.reopen_when_right()
        eq(reopened, [1], 'fixed: they come back, once')
        code, said = ask(lambda: feed.control_new(ask='hi', wait=-1))
        eq((code, len(started)), (0, 1), 'and a new one starts')
    CF._cfg.cache_clear()


def test_settings_two_writers_b806():
    print('B806: two starts that write the control settings at the same moment both get the file')
    from agent_runner import runner as R
    d = Path(tempfile.mkdtemp(prefix='agent-runner-settings-'))
    git(d, 'init', '-q')
    R.init(d)
    f = R.C.notes('control-settings.json')
    f.unlink(missing_ok=True)
    real, tmps = os.replace, []

    def replace(src, dst):  # the second writer runs whole between the first one's write and its replace
        tmps.append(str(src))
        if len(tmps) == 1:
            f.unlink(missing_ok=True)
            K.control_settings()
        real(src, dst)

    def left():
        return [p.name for p in f.parent.glob('control-settings.json*') if p != f]

    data = mock.patch.object(K, 'control_settings_data', lambda: {'hooks': {}})  # the theme it reads is written with os.replace too
    with data, mock.patch.object(K.os, 'replace', replace):
        try:
            got = K.control_settings()
        except FileNotFoundError as e:
            got = e
    eq(got, f, 'the first writer does not crash')
    eq(len(set(tmps)), 2, 'each wrote a temp file of its own')
    eq(json.loads(f.read_text(encoding='utf-8')), {'hooks': {}}, 'the file is whole')
    eq(left(), [], 'no temp file is left')
    f.unlink()
    said = ''
    with data, mock.patch.object(K.os, 'replace', side_effect=PermissionError('held')):
        try:
            K.control_settings()
        except PermissionError as e:
            said = str(e)
    eq(said, 'held', 'a replace that fails still says so')
    eq(left(), [], 'and its temp file is removed')


def test_idle_close_stays_quiet_b859():
    print('B859: a chat closed for being idle stays in the chat list, in Quiet; one closed from the TUI goes')
    from agent_runner import ui_model as U
    with held_world() as w:
        now = T0 + 2000
        for n, sid in ((5, 'idle5'), (6, 'idle6')):
            w.rows[sid] = [said('hi', T0), answer('hello', T0 + 1)]
            w.up(n, sid, 40 + n)
            w.tick(T0 + 5)
            K.C.notes(f'control{n}.title').write_text(f'{K.ROOT.name} · {n} · Pairing broken\n', encoding='utf-8')
        with mock.patch.object(K, 'control_live_numbers', lambda: [5, 6]), \
                mock.patch.object(K.plat, 'terminate', lambda p: None), \
                mock.patch.object(K, 'control_cfg', lambda: {'idle': 600, 'ask_idle': 0, 'talked': 0, 'quick': 0,
                                                             'open': []}):
            eq(sorted(x[0] for x in K.close_controls(force=True, now=now)), [5, 6], 'both closed as idle')
        w.live.clear()
        with mock.patch.object(U, 'chat_quiet', lambda: 21600.0), \
                mock.patch.object(K.time, 'time', lambda: now):
            rows = [r for r in U.session_rows({}, [], {}, now) if r['name'].startswith('c')]
            eq([(r['name'], r['state'], r['closed'], r['title']) for r in rows],
               [('c5', 'closed', True, 'Pairing broken'), ('c6', 'closed', True, 'Pairing broken')],
               'listed, closed, with their titles')
            eq(K.close_from_tui(6)['ok'], True, 'the TUI closes c6')
            eq([r['name'] for r in U.closed_rows()], ['c5'], 'c6 is gone at once, c5 stays')
        with mock.patch.object(U, 'chat_quiet', lambda: 21600.0), \
                mock.patch.object(K.time, 'time', lambda: T0 + 30000):
            eq(U.closed_rows(), [], 'once chat_quiet passed, c5 goes too')


if __name__ == '__main__':
    raise SystemExit(report([test_handed_ask_starts_fresh, test_brief_fits_session_start,
                             test_take_back_from_a_slot_just_started, test_sessions_one_and_each,
                             test_reopen_after_shutdown, test_second_shim_keeps_live_session,
                             test_first_message_typed_after_remote_control, test_takes_input_b158, test_rename_f129, test_held_delivered_once,
                             test_held_still_limited, test_held_stuck_and_cut, test_held_resent_and_runner, test_held_reopened, test_held_cut_off,
                             test_held_app_session, test_held_app_ended, test_settled_told_once, test_settled_repeats_b812,
                             test_settled_verbs_and_openers, test_settled_concept_chat, test_settled_about_chat, test_settled_filed, test_settled_closes_f209b, test_settled_waits_and_skips, test_settled_landing,
                             test_settled_rule_in_guide, test_decide_options_f181d, test_wrong_agent_b764c, test_settings_two_writers_b806, test_idle_close_stays_quiet_b859, test_shell_rule_b880]))
