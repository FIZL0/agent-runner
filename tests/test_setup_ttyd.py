"""F403: `agent-runner setup` offers to install ttyd when it is missing: asked at a terminal, never unasked, and setup goes on
whatever comes of it."""
from __future__ import annotations

import contextlib
import io
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

from _check import check, eq, git, has, report

from agent_runner import setup as S
from agent_runner import ui_model as U
from agent_runner import web as W

CMD = 'winget install tsl0922.ttyd'


def offer(answer: bool = True, terminal: bool = True, cmd: str = CMD, found: tuple = ('', ''), ran=0):
    """offer_ttyd with all of it faked: (the line it says, the questions asked, the commands run). `found` is what
    find_ttyd gives before and after the command; `ran` its exit code, or what it raises."""
    asked: list = []
    runs: list = []

    def run(argv, **kw):
        runs.append((argv, kw))
        if isinstance(ran, BaseException):
            raise ran
        return subprocess.CompletedProcess(argv, ran)

    with mock.patch.object(U, 'find_ttyd', side_effect=list(found)), \
            mock.patch.object(W, 'ttyd_install_cmd', lambda: cmd), \
            mock.patch.object(S, 'at_terminal', lambda: terminal), \
            mock.patch.object(S, 'ask', lambda q: asked.append(q) or answer), \
            mock.patch.object(S.shutil, 'which', lambda t: f'/bin/{t}.exe'), \
            mock.patch.object(S.subprocess, 'run', run):
        line = S.offer_ttyd()
    check(line is None or '\n' not in line, 'one line', line)
    return line, asked, runs


def test_yes():
    print('yes runs the command in this terminal, and ttyd is ready once found')
    line, asked, runs = offer(found=('', '/x/ttyd.exe'))
    eq(len(asked), 1, 'one question')
    has(asked[0], f'`{CMD}`', 'it names the exact command')
    check('\n' not in asked[0], 'in one line')
    eq(runs, [(['/bin/winget.exe', 'install', 'tsl0922.ttyd'], {})], "the command, with this terminal's stdin and stdout")
    has(line, 'ttyd is ready', 'found: ready')
    line, _, _ = offer()
    check('ready' not in line and 'not found yet' in line, 'exit 0 but not found: not ready', line)
    line, _, _ = offer(found=('', '/x/ttyd.exe'), ran=1)
    has(line, 'ttyd is ready', 'found is what counts')


def test_not_run():
    print('no, no terminal, no package manager, already there: nothing runs')
    line, asked, runs = offer(answer=False)
    eq((len(asked), runs), (1, []), 'no: asked, not run')
    has(line, f'`{CMD}`', 'the command is said')
    line, asked, runs = offer(terminal=False)
    eq((asked, runs), ([], []), 'no terminal: not asked, not run')
    has(line, f'`{CMD}`', 'the command is said')
    line, asked, runs = offer(cmd='')
    eq((asked, runs), ([], []), 'no package manager: not asked, not run')
    check(W.TTYD_INSTALL in line, 'the commands of every system are said', line)
    eq(offer(found=('/usr/bin/ttyd',)), (None, [], []), 'already there: nothing said')


def test_failed():
    print('a failed install says what failed')
    for ran, why in ((1, r'exit 1'), (FileNotFoundError('no sudo here'), 'no sudo here'), (KeyboardInterrupt(), 'interrupted')):
        line, _, runs = offer(ran=ran)
        eq(len(runs), 1, 'run once')
        has(line, f'`{CMD}` failed .{why}', 'the command and why')


def test_terminal():
    print('a terminal is stdin and stdout both')
    for i, o, want in ((True, True, True), (False, True, False), (True, False, False)):
        with mock.patch.object(S.sys, 'stdin', mock.Mock(isatty=lambda: i)), \
                mock.patch.object(S.sys, 'stdout', mock.Mock(isatty=lambda: o)):
            got = S.at_terminal()
        eq(got, want, f'stdin {i}, stdout {o}')


def test_main():
    print('setup goes on over ttyd, on a new repo and on one already set up; --yes is no answer to it')
    with tempfile.TemporaryDirectory() as t:
        root = Path(t)
        git(root, 'init', '-q')
        (root / 'plan').mkdir()
        for argv, todo in (([], False), ([], True), (['--yes'], True)):
            if todo:
                (root / 'plan' / 'TODO.md').write_text('# TODO\n\n- [ ] **F1** x\n', encoding='utf-8')
            asked: list = []
            runs: list = []
            launched: list = []
            real = subprocess.run

            def run(argv, **kw):
                if argv[0] == 'git':
                    return real(argv, **kw)
                runs.append(argv)
                return subprocess.CompletedProcess(argv, 1)

            out = io.StringIO()
            with mock.patch.object(U, 'find_ttyd', lambda: ''), mock.patch.object(W, 'ttyd_install_cmd', lambda: CMD), \
                    mock.patch.object(S, 'at_terminal', lambda: True), mock.patch.object(S.subprocess, 'run', run), \
                    mock.patch.object(S, 'ask', lambda q: asked.append(q) or True), \
                    mock.patch.object(S, 'launch', lambda r, text: launched.append(text) or 0), \
                    contextlib.redirect_stdout(out):
                eq(S.main(argv, cwd=root), 0, f'setup {argv} ends well')
            eq(sum('ttyd' in q for q in asked), 1, 'asked about ttyd')
            eq((len(runs), len(launched)), (1, 1), 'the install failed, and the session still starts')
            eq(out.getvalue().count('ttyd was not installed'), 2, 'said at once and in the summary')


if __name__ == '__main__':
    raise SystemExit(report([test_yes, test_not_run, test_failed, test_terminal, test_main]))
