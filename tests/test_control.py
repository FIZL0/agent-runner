"""B94: the background session's default-command and environment target '=sess:', which tmux 3.8's set-option
accepts (a bare '=sess' it rejects with "no such session", so new panes opened a plain shell)."""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from unittest import mock

from _check import check, eq, git, report

from agent_runner import control as K  # noqa: E402


def test_background_session_options_target():
    print('B94: set-option and set-environment for the background session target =<sess>:')
    root = Path('/tmp/repo')
    cmds = K.background_session_options('ar-demo', root, ['FOO=bar=baz'])
    eq(cmds[0][:4], ['set-option', '-t', '=ar-demo:', 'default-command'], 'set-option targets =ar-demo:')
    eq(cmds[0][4], K.control_default_command(root), 'default-command is the control command')
    eq(cmds[1], ['set-environment', '-t', '=ar-demo:', 'FOO', 'bar=baz'], 'set-environment targets =ar-demo:')
    check(all(c[2] == '=ar-demo:' for c in cmds), 'no bare =ar-demo target')


def test_real_tmux_takes_the_option():
    if not shutil.which('tmux'):
        print('  (no tmux: skipped the live check)')
        return
    print('B94: on this tmux, show-options prints the default-command set through that target')
    sock = Path(tempfile.mkdtemp(prefix='b94-tmux-')) / 's'
    t = ['tmux', '-S', str(sock)]
    try:
        r = subprocess.run([*t, 'new-session', '-d', '-s', 'ar-demo'], capture_output=True, text=True, timeout=20)
        if r.returncode:
            print(f'  (tmux could not start a server: {r.stderr.strip()}; skipped)')
            return
        for args in K.background_session_options('ar-demo', Path('/tmp/repo'), ['B94_X=1']):
            r = subprocess.run([*t, *args], capture_output=True, text=True, timeout=20)
            eq(r.returncode, 0, f'tmux {args[0]} succeeds ({r.stderr.strip()})')
        out = subprocess.run([*t, 'show-options', '-v', '-t', 'ar-demo', 'default-command'],
                             capture_output=True, text=True, timeout=20).stdout.strip()
        eq(out, K.control_default_command(Path('/tmp/repo')), 'show-options prints the control command')
    finally:
        subprocess.run([*t, 'kill-server'], capture_output=True, timeout=20)


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
        check(f'`{win}` is the runner' in brief and f'`{win} plan …`' in brief,
              'the Guide pages line still names the full command')
        check('`guide take`' in brief and '`plan add <KIND>' in brief, 'the commands after it are bare')
    check(voice.brief_fit('x', cmd, R.C) != '', 'brief_fit returns text')


if __name__ == '__main__':
    raise SystemExit(report([test_background_session_options_target, test_real_tmux_takes_the_option,
                             test_handed_ask_as_c1_starts_fresh, test_brief_fits_session_start]))
