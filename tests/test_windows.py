#!/usr/bin/env python3
"""Windows behaviour that runs anywhere: the slot tab's shim, and UTF-8 task-list merges.

    python3 tests/test_windows.py        (no network, no real agent; runs on Windows too)
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest import mock

from _check import ROOT, check, eq, git, has, report

from agent_runner import ci  # noqa: E402
from agent_runner import cmds  # noqa: E402
from agent_runner import conpty  # noqa: E402
from agent_runner import plat  # noqa: E402
from agent_runner import runner as R  # noqa: E402


def make_repo(tmp: Path) -> Path:
    repo = tmp / 'proj'
    repo.mkdir()
    git(repo, 'init', '-q', '-b', 'main')
    (repo / 'runner.toml').write_text('[run]\nmodel = "m1"\nfix_model = "m2"\n\n[git]\npush = false\n',
                                      encoding='utf-8')
    (repo / '.gitignore').write_text('.runner/\n', encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'start')
    return repo


def test_utf8_merge(tmp: Path):
    print('windows: a TODO.md conflict with non-ASCII text joins (git output is UTF-8, not the ANSI code page)')
    d = tmp / 'utf8'
    d.mkdir()
    git(d, 'init', '-q', '-b', 'main')
    (d / 'plan').mkdir()
    (d / 'runner.toml').write_text('', encoding='utf-8')
    head = '# TODO — “open” tasks\n\n### Later\n\n'
    (d / 'plan/TODO.md').write_text(head + '- [ ] **A1** one → a.py\n', encoding='utf-8')
    (d / 'plan/DONE.md').write_text('# DONE — the archive\n', encoding='utf-8')
    git(d, 'add', '-A'), git(d, 'commit', '-qm', 'base')
    git(d, 'checkout', '-qb', 'task/A2')
    (d / 'plan/TODO.md').write_text(head + '- [ ] **A1** one → a.py\n- [ ] **A2** two · b.py\n', encoding='utf-8')
    git(d, 'commit', '-qam', 'A2')
    git(d, 'checkout', '-q', 'main')
    (d / 'plan/TODO.md').write_text(head + '- [ ] **A1** one → a.py\n- [ ] **A3** three … c.py\n', encoding='utf-8')
    git(d, 'commit', '-qam', 'A3')
    R.init(d)
    base = git(d, 'rev-parse', 'HEAD')
    eq(R.merge_into(d, 'task/A2', 'm'), [], 'the task-list merge driver joins both added lines')
    text = (d / 'plan/TODO.md').read_text(encoding='utf-8')
    check('“open”' in text and '**A2** two ·' in text and '**A3** three …' in text,
          'with both lines and non-ASCII text unchanged', text)
    git(d, 'reset', '--hard', base)

    print('windows: a task id both sides gave away is renumbered, non-ASCII text intact')
    git(d, 'checkout', '-qb', 'task/A4', 'main~1')
    (d / 'plan/TODO.md').write_text(head + '- [ ] **A1** one → a.py\n- [ ] **A3** other “thing” → d.py\n',
                                    encoding='utf-8')
    git(d, 'commit', '-qam', 'A4 files A3')
    git(d, 'checkout', '-q', 'main')
    ref = R.renumber_doubles('task/A4', 'main', 'A4', d)
    check(ref != 'task/A4', 'the branch gets a renumbering commit')
    shown = R.git('show', f'{ref}:plan/TODO.md', cwd=d).stdout
    check('**A4** other “thing” → d.py' in shown or '**A5** other “thing” → d.py' in shown,
          'its A3 has a new id and its text is unchanged', shown)


def test_shim_once(repo: Path, tmp: Path):
    print('windows: a slot tab runs its job once and exits 0, so it closes and Enter cannot restart it')
    R.init(repo)
    marker, job, count = R.C.notes('slot8.live'), R.C.notes('slot8.job'), tmp / 'count'
    argv = [sys.executable, '-c', 'import sys; open(sys.argv[1], "a").write("x"); sys.exit(1)', str(count)]
    job.write_text(json.dumps({'argv': argv, 'cwd': str(repo), 'env': {}, 'marker': str(marker)}), encoding='utf-8')
    eq(R.slot_shim(str(job)), 0, 'exit 0 even when the agent was killed (taskkill leaves exit code 1)')
    eq(R.slot_shim(str(job)), 0, 'a restarted tab exits at once')
    eq(count.read_text(), 'x', 'and the session ran only once')
    has(marker.with_suffix('.exit').read_text(), r'^exit code 1 \(pid \d+\)$', 'how the agent ended (and its pid) is left for the runner')
    job.write_text(json.dumps({'argv': [str(tmp / 'no-such-agent.exe')], 'cwd': str(repo), 'env': {},
                               'marker': str(marker)}), encoding='utf-8')
    eq(R.slot_shim(str(job)), 0, 'an agent that cannot start still ends the tab cleanly')
    check(marker.with_suffix('.exit').read_text().startswith('could not start'), 'and says it could not start')


def test_run_log_utf8(repo: Path):
    print('windows: run.log is UTF-8 whatever the console code page (B100: a Remote Control name\'s "·")')
    R.init(repo)
    R.log('control: control server up as "hello · control" — “quoted”')
    raw = R.C.notes('run.log').read_bytes()
    check('hello · control'.encode('utf-8') in raw, 'the "·" is written as UTF-8 (C2 B7), not as cp1252 or cp437')
    check(not raw.startswith(b'\xef\xbb\xbf'), 'no BOM: readers take the first line as a run.log line')


def test_ci_workflow(tmp: Path):
    print('windows: ci.yml runs on push and pull request, and on request for one system and some test files (T13)')
    text = (ROOT / '.github/workflows/ci.yml').read_text(encoding='utf-8')
    on = text.split('\non:\n', 1)[1].split('\npermissions:', 1)[0]
    blocks = dict(re.findall(r'^  (\w+):\n((?:    .*\n?)*)', on, re.M))
    eq(sorted(blocks), ['pull_request', 'push', 'workflow_dispatch'], 'the three triggers')
    check(ci.runs_on_push(text, 'main') and not ci.runs_on_push(text, 'task/T13'), 'push still means main only')
    for name in ('push', 'pull_request'):
        has(blocks[name], r"paths-ignore: \['plan/\*\*', '\*\*\.md'\]", f'{name} still skips the plan and Markdown')
    has(blocks['workflow_dispatch'], r'options: \[both, windows, linux\]\n +default: both', 'which system, by default both')
    has(text, r'\|\| \'\["ubuntu-latest", "windows-latest"\]\'\) \}\}', 'with no input (push, pull request) both run')
    for system, image in (('windows', 'windows-latest'), ('linux', 'ubuntu-latest')):
        check(f"inputs.system == '{system}' && '[\"{image}\"]'" in text, f'{system} runs on {image} alone')
    script = text.split('- name: Test gate', 1)[1].split('run: |\n', 1)[1]
    runs = [x for x in re.split(r'\n {6}- ', text) if 'run: |' in x]
    check(all('${{' not in x.split('run: |', 1)[1] for x in runs), 'no expression is written into a script')
    has(text, r'TESTS: \$\{\{ inputs\.tests \}\}', 'the list of test files is an environment variable')

    d = tmp / 'ci'
    (d / 'tests').mkdir(parents=True)
    for n in ('test_a.py', 'test_b.py'):
        (d / 'tests' / n).write_text('', encoding='utf-8')
    script = 'python() { echo "RAN $1"; }\n' + re.sub(r'^ {10}', '', script, flags=re.M)

    def gate(tests: str):
        r = subprocess.run([cmds.bash_exe(), '--noprofile', '--norc', '-eo', 'pipefail', '-c', script], cwd=d,
                           env={**os.environ, 'TESTS': tests}, capture_output=True, encoding='utf-8')
        return r.returncode, re.findall(r'^RAN (\S+)$', r.stdout, re.M)

    both = ['tests/test_a.py', 'tests/test_b.py']
    eq(gate(''), (0, both), 'no list: every test file')
    eq(gate('  '), (0, both), 'nor a blank one')
    eq(gate('tests/test_b.py'), (0, both[1:]), 'one test file')
    eq(gate('tests/test_b.py tests/test_a.py'), (0, both[::-1]), 'two')
    for bad in ('tests/test_none.py', 'tests/*.py', '-c', 'tests/test_a.py;touch pwned', '$(touch pwned)'):
        eq(gate(bad), (1, []), f'{bad!r} fails the run and runs nothing')
    check(not (d / 'pwned').exists(), 'and nothing in the list is run as shell')


def test_bash_beside_git(tmp: Path):
    print('windows: the wizards\' bash is found with only Git\\cmd on PATH, the installer\'s default (B159)')
    ext = '.exe' if os.name == 'nt' else ''

    def fake(f: Path) -> Path:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text('', encoding='utf-8')
        f.chmod(0o755)
        return f

    d = tmp / 'bash'
    git_exe = fake(d / f'Git/cmd/git{ext}')
    wsl = fake(d / f'Windows/System32/bash{ext}')
    on_path = fake(d / f'msys/bash{ext}')
    was, env, here = plat.WINDOWS, dict(os.environ), os.getcwd()

    def found(*dirs: Path) -> str:
        os.environ['PATH'] = os.pathsep.join(map(str, dirs))
        try:
            return os.path.normcase(cmds.bash_exe())
        except SystemExit as e:
            return str(e.code)

    try:
        plat.WINDOWS = True
        os.environ['SystemRoot'] = str(d / 'Windows')
        os.chdir(d)  # Windows' which looks in the current directory too
        for dirs, what in (((wsl.parent, git_exe.parent), 'git but no bash.exe beside it'), ((wsl.parent,), 'no git')):
            said = found(*dirs)
            check(said.startswith('Git Bash is missing') and '\n' not in said, f'{what}: one line says so', said)
        beside = fake(d / 'Git/bin/bash.exe')
        eq(found(wsl.parent, git_exe.parent), os.path.normcase(str(beside)),
           'bash.exe beside git, not System32\'s WSL launcher')
        eq(found(wsl.parent, git_exe.parent, on_path.parent), os.path.normcase(str(on_path)), 'a bash on PATH goes first')
    finally:
        plat.WINDOWS = was
        os.chdir(here)
        os.environ.clear()
        os.environ.update(env)


def test_wizard_without_bash(repo: Path, tmp: Path):
    print('windows: a wizard with no Git Bash says so in one line, no traceback (B159)')
    wizard = repo / '.runner/wizards/F1.sh'
    wizard.parent.mkdir(parents=True, exist_ok=True)
    wizard.write_text('echo hi\n', encoding='utf-8')
    code = ('import os, pathlib, sys, types; from agent_runner import cmds, plat; plat.WINDOWS = True; '
            'cmds.init = lambda: None; cmds.C = types.SimpleNamespace(notes=lambda *a: pathlib.Path(sys.argv[1])); '
            'os.environ["PATH"] = ""; sys.exit(cmds.cmd_wizard(["F1"]))')
    r = subprocess.run([sys.executable, '-c', code, str(wizard)], cwd=tmp,
                       env={**os.environ, 'PYTHONPATH': str(ROOT)}, capture_output=True, encoding='utf-8')
    eq((r.returncode, len(r.stderr.splitlines())), (1, 1), 'exit 1 and one line')
    has(r.stderr, r'^Git Bash is missing', 'which says Git Bash is missing')


CONPTY_CHILD = """
import ctypes, os, subprocess, sys
if sys.argv[1] == 'keys':  # a full-screen program reads its keys raw, as the agent does
    k = ctypes.windll.kernel32
    k.SetConsoleMode(k.GetStdHandle(-10), 0x200)  # ENABLE_VIRTUAL_TERMINAL_INPUT alone
    print('READY', flush=True)
    got = b''
    while not got.endswith(b'\\r'):
        got += os.read(0, 1024)
    print('KEYS', got.hex(), flush=True)
    sys.exit(0)
print('TTY', sys.stdin.isatty(), sys.stdout.isatty(), os.environ['F145'], os.path.basename(os.getcwd()), flush=True)
print('MARKER', os.path.basename(os.environ['AGENT_RUNNER_MARKER']), flush=True)
p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])  # shares the pseudo-console
print('KID', p.pid, flush=True)
print('READY', flush=True)
line = input()
print('GOT', line, 'END', flush=True)
sys.exit(7)
"""


def plain(f: Path) -> str:
    """A session's log with no escape sequences: the console host puts its own between a program's words."""
    s = f.read_text(encoding='utf-8', errors='replace') if f.exists() else ''
    return re.sub(r'\x1b(?:\][^\x07\x1b]*(?:\x07|\x1b\\)|\[[0-9;?]*[ -/]*[@-~])', '', s)


def until(what, seconds: float = 60.0) -> bool:
    end = time.monotonic() + seconds
    while not what() and time.monotonic() < end:
        time.sleep(0.1)
    return bool(what())


def pipe_access(name: str) -> str:
    """The access list of the named pipe `name`, as SDDL text (Windows)."""
    import ctypes
    from ctypes import wintypes as w
    a, k = ctypes.WinDLL('advapi32'), ctypes.WinDLL('kernel32')
    k.CreateFileW.restype = w.HANDLE
    k.CloseHandle.argtypes = [w.HANDLE]
    a.GetSecurityInfo.argtypes = [w.HANDLE, ctypes.c_int, w.DWORD, *[ctypes.c_void_p] * 5]
    h = k.CreateFileW(name, 0x40020000, 0, None, 3, 0, None)  # GENERIC_WRITE | READ_CONTROL
    sd, text = ctypes.c_void_p(), w.LPWSTR()
    try:
        a.GetSecurityInfo(h, 6, 4, None, None, None, None, ctypes.byref(sd))  # SE_KERNEL_OBJECT, its DACL
        a.ConvertSecurityDescriptorToStringSecurityDescriptorW(sd, 1, 4, ctypes.byref(text), None)
    finally:
        k.CloseHandle(h)
    return text.value or ''


def test_conpty(tmp: Path):
    print('windows: run_conpty: a session in a pseudo-console, its output in the log, typed into by slotN.in (F145)')
    check(plat.has_conpty() or os.name != 'nt', 'Windows 10 1809 and later have it')
    if not plat.has_conpty():
        return
    d = tmp / 'conpty'
    d.mkdir()
    child = d / 'child.py'
    child.write_text(CONPTY_CHILD, encoding='utf-8')

    def start(mode: str):
        marker, log, got = d / f'{mode}.live', d / f'{mode}.log', []
        t = threading.Thread(target=lambda: got.append(R.slots.run_conpty(
            [sys.executable, str(child), mode], str(d), {'F145': 'an env value'}, marker, log)), daemon=True)
        t.start()
        text = lambda: plain(log)
        check(until(lambda: 'READY' in text()), f'{mode}: its output reaches the log', text())
        return marker, text, got, t

    marker, text, got, t = start('line')
    inbox = marker.with_suffix('.in')
    check(until(inbox.exists), 'its inbox is there')
    pid = R.marker_pid(marker)
    check(plat.alive(pid), 'the marker holds the pid while it runs')
    has(text(), r'TTY True True an env value conpty', 'it has a terminal, its environment and its directory')
    has(text(), r'MARKER line\.live', 'and is told its marker')
    m = re.search(r'KID (\d+)', text())
    kid = int(m[1]) if m else 0
    access = pipe_access(inbox.read_text(encoding='utf-8'))
    sid = subprocess.run(['whoami', '/user', '/fo', 'csv', '/nh'], capture_output=True, text=True).stdout
    sid = re.search(r'S-1-[\d-]+', sid)[0]
    has(access, r'^D:P\(A;;[A-Z0-9x]+;;;[^()]+\)$', 'the pipe has one entry in its access list')
    check(access.endswith(f';{sid})') or access.endswith(';LA)'), 'and it is this user', f'{access} {sid}')
    check(R.send_fifo_raw(inbox, b'typed '), 'raw text is sent')
    check(R.send_fifo_raw(inbox, 'as two sends, naïve'.encode('utf-8')), 'by one sender after another')
    check(R.send_fifo_raw(inbox, b'\r'), 'then Enter')
    t.join(60)
    check(not t.is_alive(), 'a child of the child that keeps running does not hang the drain')
    if kid and plat.alive(kid):
        plat.terminate(kid)
    eq(got, [(7, pid)], 'its exit code and pid come back')
    has(text(), r'GOT typed as two sends, naïve END', 'the typed text reached it, and its last output the log')
    check(not marker.exists() and not inbox.exists(), 'the marker and the inbox go when it ends')
    check(not R.send_fifo(inbox, 'late') and not R.send_fifo_raw(inbox, b'late'), 'nothing is sent to an ended one')
    inbox.write_text(r'\\.\pipe\agent-runner-none', encoding='utf-8')
    check(not R.send_fifo(inbox, 'late'), 'nor to an inbox a killed shim left')

    marker, text, got, t = start('keys')
    until(marker.with_suffix('.in').exists)
    check(R.send_fifo(marker.with_suffix('.in'), 'two\nlines'), 'a message is sent')
    t.join(60)
    has(text(), 'KEYS ' + b'\x1b[200~two\nlines\x1b[201~\r'.hex(),
        'a program that reads keys gets the bracketed paste, then Enter')
    eq([g[0] for g in got], [0], 'and ends')
    try:
        R.slots.run_conpty([str(d / 'no-such-agent.exe')], str(d), {}, d / 'none.live', None)
        check(False, 'an agent that cannot start is an OSError')
    except OSError:
        check(not (d / 'none.live').exists(), 'an agent that cannot start is an OSError, with no marker')


def test_conpty_slot(repo: Path, tmp: Path):
    print('windows: HiddenMux and hidden_control run through the detached shim, in a pseudo-console (F145)')
    if not plat.has_conpty():
        return
    R.init(repo)
    child = tmp / 'slot-child.py'
    child.write_text(CONPTY_CHILD, encoding='utf-8')
    argv, log = [sys.executable, str(child), 'line'], R.C.notes('slot6.log')
    mux = R.HiddenMux()
    with mock.patch.object(R.slots, 'agent_argv', lambda *a, **k: argv), \
            mock.patch.object(R.slots, 'stream_engine', lambda: False), \
            mock.patch.object(R.slots, 'env_vars', lambda env: {'F145': 'x'}):
        pid = mux.open(6, repo, 'p', 'sid-6', 'm', 1, [], log)
    check(pid and plat.alive(pid), 'the slot is up')
    check(mux.typed, 'and takes typed text')
    if not pid:
        return
    check(until(lambda: 'READY' in plain(log)), 'its output is in the slot log', plain(log))
    from agent_runner import attach as A
    sock = A.session_socket('s6')
    check(sock, 'F114: its shim listens for attach')
    with mock.patch.object(cmds, 'init'), mock.patch.object(cmds, 'attach_session', lambda s, n: 41):
        eq(cmds.cmd_attach(['s6']), 41, 'attach s6 attaches')
    c = A.connect(sock)
    c.sendall(A.attach_size_frame(30, 100))
    c.settimeout(10)
    check(bool(c.recv(100)), 'and a client that came gets the screen drawn again')
    c.close()
    check(mux.send(mux.panes()['s6'], 'hello slot'), 'a tell is typed in')
    ended = R.C.notes('slot6.exit')
    check(until(ended.exists), 'it ends', plain(log))
    has(plain(ended), rf'^exit code 7 \(pid {pid}\)$', 'and how is left for the runner')
    has(plain(log), r'GOT .*hello slot', 'the tell reached it')

    with mock.patch.dict(os.environ, {'F145': 'y'}):
        pid, why = R.control.hidden_control(5, argv)
    check(pid, 'a control session is up in a pseudo-console', why)
    log = R.control.hidden_control_log(5)
    check(until(lambda: 'READY' in plain(log)), 'its output is in its log', plain(log))
    check(R.control.control_type(5, '/rename x'), 'text is typed into it')
    check(until(R.C.notes('control5.exit').exists), 'it ends')
    has(plain(log), r'GOT .*/rename x', 'the text reached it')


def test_attach_logged(repo: Path):
    print('windows: attach shows a hidden console, and names the log of a session that has none (F145)')
    R.init(repo)
    notes = R.C.notes
    for stem, spec in (('slot3', {}), ('slot4', {'conpty': True}), ('slot5', {'stream': True}),
                       ('control4', {'conpty': True})):
        notes(f'{stem}.live').write_text('4242', encoding='utf-8')
        notes(f'{stem}.job').write_text(json.dumps(spec), encoding='utf-8')
    try:
        for name, stem, console in (('s3', 'slot3', True), ('s4', 'slot4', False), ('s5', 'slot5', False),
                                    ('c4', 'control4', False)):
            shown, out = [], io.StringIO()
            with mock.patch.object(plat, 'WINDOWS', True), mock.patch.object(plat, 'alive', lambda p: p == 4242), \
                    mock.patch.object(plat, 'show_console', lambda p: shown.append(p) or True), \
                    mock.patch.object(cmds, 'init'), contextlib.redirect_stdout(out):
                rc = cmds.cmd_attach([name])
            eq(rc, 0, f'attach {name}')
            eq(shown, [4242] if console else [], f'{name}: its console is shown' if console else f'{name}: none is')
            eq(len(out.getvalue().splitlines()), 1, f'{name}: one line')
            eq(str(notes(f'{stem}.log')) in out.getvalue(), not console, f'{name}: the log is named' if not console else f'{name}: no log')
    finally:
        for stem in ('slot3', 'slot4', 'slot5', 'control4'):
            for x in ('live', 'job'):
                notes(f'{stem}.{x}').unlink()


def test_no_conpty(repo: Path, tmp: Path):
    print('windows: with no ConPTY a slot keeps the hidden console, which takes no typed text (F145)')
    R.init(repo)
    opened, mux = [], R.HiddenMux()
    for has_it, stream, want in ((False, False, 'console'), (True, False, 'detached'), (True, True, 'console')):
        with mock.patch.object(plat, 'WINDOWS', True), mock.patch.object(plat, 'has_conpty', lambda: has_it), \
                mock.patch.object(plat, 'spawn_console', lambda *a, **k: opened.append('console')), \
                mock.patch.object(plat, 'spawn_detached', lambda *a, **k: opened.append('detached')), \
                mock.patch.object(R.slots, 'agent_argv', lambda *a, **k: ['x']), \
                mock.patch.object(R.slots, 'stream_engine', lambda: stream), \
                mock.patch.object(R.slots, 'SHIM_WAIT', 0.0):
            mux.open(9, repo, 'p', 'sid-9', 'm', 1, [], R.C.notes('slot9.log'))
            eq((opened.pop(), mux.typed), (want, has_it), f'ConPTY {has_it}, headless {stream}: {want}')
    check(not plat.has_conpty() or os.name == 'nt', 'no ConPTY off Windows')
    check(os.name == 'nt' or not conpty.pipe_send(tmp / 'none.in', [b'x']), 'nothing to send to')


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix='agent-runner-windows-'))
    repo = make_repo(tmp)
    return report([lambda: test_shim_once(repo, tmp), lambda: test_utf8_merge(tmp), lambda: test_run_log_utf8(repo),
                   lambda: test_ci_workflow(tmp), lambda: test_bash_beside_git(tmp),
                   lambda: test_wizard_without_bash(repo, tmp), lambda: test_attach_logged(repo),
                   lambda: test_no_conpty(repo, tmp), lambda: test_conpty(tmp), lambda: test_conpty_slot(repo, tmp)])


if __name__ == '__main__':
    sys.exit(main())
