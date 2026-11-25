"""F402b1: the page-only process (agent_runner/page_only.py): the run page while no run is up.

    python3 tests/test_page_only.py        (temp repos, real detached processes, a fake agent; under a minute)
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
from unittest import mock

from _check import check, eq, git, report, RUN
from _web import TODO, get, post

from agent_runner import cmds as M, config as CF, home as H, page_only as P, plat, state as S, web as W  # noqa: E402

CLAUDE = r"""#!%s
import os, sys
if not sys.stdin.isatty():
    sys.exit(0)
out = os.path.join(os.environ['HOME'], 'said')
open(out, 'a').write('ARGV ' + ' '.join(sys.argv[1:]) + '\n')
sys.stdout.write('\x1b[?2004h'); sys.stdout.flush()
while True:
    line = sys.stdin.readline()
    if not line:
        break
    open(out, 'a').write('IN ' + line)
""" % sys.executable


def free_port() -> int:
    with socket.socket() as s:
        s.bind(('0.0.0.0', 0))
        return s.getsockname()[1]


def until(f, limit: float = 30.0):
    end = time.monotonic() + limit
    while not (got := f()) and time.monotonic() < end:
        time.sleep(0.1)
    return got


def project(tmp: Path, env: dict) -> tuple[Path, int]:
    """A project of its own with no run, and an environment (`env`, filled in) with nothing of this machine's person."""
    root, home, port = tmp / 'proj', tmp / 'home', free_port()
    (root / 'plan').mkdir(parents=True)
    (tmp / 'bin').mkdir()
    home.mkdir()
    fake = tmp / 'bin' / 'claude'
    fake.write_text(CLAUDE, encoding='utf-8')
    fake.chmod(0o755)
    (root / '.gitignore').write_text('.runner/\n', encoding='utf-8')
    (root / 'runner.toml').write_text(f'[run]\ntest = "true"\nremote = false\nweb_port = {port}\ninstall_skill = false\n'
                                      'min_free_gb = 0\nauto_upgrade = false\n', encoding='utf-8')
    (root / 'plan' / 'TODO.md').write_text(TODO, encoding='utf-8')
    (root / 'plan' / 'DONE.md').write_text('# DONE\n', encoding='utf-8')
    git(root, 'init', '-q', '-b', 'main')
    git(root, 'add', '-A')
    git(root, 'commit', '-qm', 'start')
    env.update(HOME=str(home), USERPROFILE=str(home), CLAUDE_CONFIG_DIR=str(home / '.claude'), AGENT_RUNNER_NO_WEB='',
               AGENT_RUNNER_HOME_CONFIG=str(tmp / 'cfg'), AGENT_RUNNER_HOME=str(tmp / 'runs'),
               PATH=str(tmp / 'bin') + os.pathsep + os.environ['PATH'])
    return root, port


def pid_of(root: Path) -> int:
    return int((P.notes(root, 'page.live')).read_text(encoding='utf-8') or 0)


def ended(root: Path, pid: int) -> bool:
    return bool(until(lambda: not plat.alive(pid) and not P.held(root)))


def test_serves(tmp: Path) -> None:
    print('F402b1: w starts it; the page, plan add and a chat work; a second is refused; a run takes over')
    env: dict = {}
    root, port = project(tmp, env)
    opened: list[str] = []
    live: list[int] = []
    with mock.patch.dict(os.environ, env):
        CF._cfg.cache_clear()
        S.init(root)
        eq((P.serving(root), P.links(root), P.take_over(), P.notes(root, 'page.lock').exists()), (False, [], 0, False),
           'none yet, and looking makes no file')
        # the launcher's w, through its own action
        row = {'root': root, 'name': 'proj', 'run': {'up': False}, 'link': ''}
        it = iter(('w', 'w', 'q'))
        acts = {'page': lambda r: P.open_page(r, lambda u: opened.append(u) or 'opened')}
        shown: list[str] = []
        try:
            M.launch(row, lambda: next(it), shown.append, acts)
            live.append(pid_of(root))
            check(len(opened) == 2 and opened[0] == opened[1] == row['link'] and f':{port}/?t=' in opened[0],
                  'w starts it and opens its page, w again opens the same', (opened, shown[-1]))
            check('opened' in shown[-1] and 'not running' in shown[-1], 'the launcher says so; no run is up', shown[-1])
            check(plat.alive(live[0]) and live[0] != os.getpid(), 'it is a process of its own')
            eq((S.run_up(), M.run_info(root).get('up')), (False, False), 'run_up stays false')
            r = subprocess.run([sys.executable, str(RUN), 'status'], cwd=root, capture_output=True, text=True)
            check('no run' in (r.stdout + r.stderr).lower() and 'run page:' not in r.stdout, 'status says no run is up',
                  r.stdout + r.stderr)

            # one at most
            r = subprocess.run([sys.executable, str(RUN), 'page-only'], cwd=root, capture_output=True, text=True, timeout=60)
            check(r.returncode == 0 and 'already' in r.stdout and pid_of(root) == live[0], 'no second process', r.stdout + r.stderr)
            eq(P.start(root), '', 'starting it again is the same one')

            # the page
            base, t = f'http://127.0.0.1:{port}', W.web_token()
            code, body = get(f'{base}/?t={t}')
            check(code == 200 and b'proj' in body, 'the run page answers')
            eq(get(f'{base}/?t=no')[0], 403, 'not without the key')
            snap = json.loads(get(f'{base}/snapshot?t={t}')[1])
            eq((snap.get('up'), [q['id'] for q in snap.get('queue') or []]), (False, ['F1', 'B2']), 'its snapshot: not up, the queue')
            check('start' in snap['shown'], 'with the start control', snap.get('shown'))
            eq(H.run_link(root), (port, t), 'Runner Home routes to it')
            code, got = post(f'{base}/act?t={t}', {'name': 'plan_add', 'args': {
                'kind': 'F', 'text': 'A new leaf', 'files': 'leaf.py'}, 'cid': 'a1'})
            todo = (root / 'plan' / 'TODO.md').read_text(encoding='utf-8')
            check(code == 200 and got['ok'] and 'A new leaf' in todo, 'a task added lands in the plan', got)
            eq((list((tmp / 'runs').rglob('s1')), git(root, 'branch', '--list', 'task/*')), ([], ''), 'no slot, no task branch')

            if not plat.WINDOWS:  # the fake agent is a script with a shebang
                said = tmp / 'home' / 'said'
                heard = lambda w: said.exists() and w in said.read_text(encoding='utf-8')  # noqa: E731
                code, got = post(f'{base}/act?t={t}', {'name': 'new_control', 'args': {'ask': 'first words', 'wait': False}})
                check(got['ok'] and got['name'] == 'c2', 'a new chat starts', got)
                check(until(lambda: heard('first words')), 'and has its first message')
                got = until(lambda: (g := post(f'{base}/act?t={t}', {'name': 'chat_to', 'args': {
                    'text': 'more words', 'to': 'c2'}, 'hold': True})[1])['ok'] and g)
                check(got and until(lambda: heard('more words')), 'a chat takes a message',
                      said.read_text(encoding='utf-8') if said.exists() else 'nothing')
                live.append(int(S.C.notes('control2.pid').read_text().split()[0]))

            # a run takes it over: the same key, the same port; an open page's stream ends, so it connects again
            stream, read = urllib.request.urlopen(f'{base}/events?t={t}', timeout=30), []

            def drain():
                while True:
                    try:
                        if not (line := stream.readline()):
                            return
                    except OSError:  # Windows resets the connection of a process that ended
                        return
                    read.append(line)
            reader = threading.Thread(target=drain, daemon=True)
            reader.start()
            check(until(lambda: read), 'an open page has its stream')  # unread, it is lost with a reset connection
            lock = plat.lock(S.C.notes('run.lock'))  # as loop.run before start_web
            srv = None
            try:
                with mock.patch.object(S, 'log'):
                    srv = W.start_web()
                eq((srv.server_address[1], srv.token), (port, t), "the run's page: the same port and key")
                check(f':{port}/' in P.urls(root)[0], 'and web.url is its own', P.urls(root))
                reader.join(10)
                check(not reader.is_alive() and read and read[0].startswith(b'data: '), "the open page's stream ended",
                      (reader.is_alive(), read[:1]))
                check(ended(root, live[0]), 'the page-only process is gone')
                eq(get(f'{base}/?t={t}')[0], 200, 'and the run answers there')
                eq((P.serving(root), S.C.notes('page.stop').exists()), (False, False), 'nothing of it is left')
                check(f':{port}/' in P.urls(root)[0], 'its end left web.url to the run')
                r = subprocess.run([sys.executable, str(RUN), 'page-only'], cwd=root, capture_output=True, text=True, timeout=60)
                check('a run is up' in r.stdout and P.urls(root), 'none starts while a run is up', r.stdout + r.stderr)
            finally:
                if srv:
                    srv.stop()
                lock.close()
            if len(live) > 1:
                check(plat.alive(live[1]), 'the chat goes on')
        finally:
            for pid in live:
                if plat.alive(pid):
                    plat.terminate(pid)


def test_start_from_page(tmp: Path) -> None:
    print("F402b1: the page's own Start runs to its end while the run takes the page over")
    if plat.WINDOWS:
        return
    env: dict = {}
    root, port = project(tmp, env)
    with mock.patch.dict(os.environ, env):
        CF._cfg.cache_clear()
        S.init(root)
        (root / 'plan' / 'TODO.md').write_text('# TODO\n\n### Next\n', encoding='utf-8')
        git(root, 'commit', '-qam', 'nothing to do')
        eq(P.start(root), '', 'it starts')
        pid, t, run = pid_of(root), W.web_token(), 0
        try:
            got = post_long(f'http://127.0.0.1:{port}/act?t={t}', {'name': 'run_control', 'args': {'key': 'start'}})
            check(got.get('ok'), 'the answer comes back', got)
            check(S.run_up(), 'the run is up')
            check(ended(root, pid), 'the page-only process is gone')
            eq(get(f'http://127.0.0.1:{port}/?t={t}')[0], 200, 'the run serves the page on the same port')
        finally:
            subprocess.run([sys.executable, str(RUN), 'stop', '--force'], cwd=root, capture_output=True, timeout=60)
            check(until(lambda: not S.run_up(), 60), 'the run ended')
            if plat.alive(pid):
                plat.terminate(pid)


def post_long(url: str, body: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read())


def test_ends(tmp: Path) -> None:
    print('F402b1: it ends when idle, not while a page is open; on a signal; [run] web off; a stale note')
    env: dict = {}
    root, port = project(tmp, env)
    with mock.patch.dict(os.environ, env), mock.patch.object(S, 'log'), mock.patch.object(P, 'held_messages') as held:
        CF._cfg.cache_clear()
        S.init(root)
        go = threading.Event()
        code: list[int] = []
        with mock.patch.object(P, 'IDLE', 2.0), mock.patch.object(P, 'LOOK', 0.1):
            th = threading.Thread(target=lambda: code.append(P.serve(go)), daemon=True)
            S.C.notes('page.stop').write_text('999999999', encoding='utf-8')  # of a run that is gone
            th.start()
            check(until(lambda: P.serving(root)), 'it serves, whatever a gone run left')
            stream = urllib.request.urlopen(f'http://127.0.0.1:{port}/events?t={W.web_token()}', timeout=30)
            time.sleep(3.5)
            check(th.is_alive(), 'with a page open it stays past the idle time')
            check(held.called, 'the messages chats hold are looked at')
            # the page is gone: its stream's next write fails, as after the keep-alive
            with mock.patch.object(W, 'PING', 0.2):
                stream.close()
                th.join(30)
            eq((th.is_alive(), code), (False, [0]), 'with none open it ends')
            eq((P.urls(root), P.held(root), P.serving(root)), ([], False, False), 'web.url, its lock and note are gone')
            go.set()
            eq(P.serve(go), 0, 'asked to end (a signal sets this): it does')
        lock = plat.lock(S.C.notes('page.lock'))
        eq((P.take_over(0.2), P.asked_to_end()), (0, True), 'one too slow to end: the run goes on, and it is still asked to')
        lock.close()
        S.C.notes('page.stop').unlink()
        (root / 'runner.toml').write_text('[run]\nweb = false\n', encoding='utf-8')
        with mock.patch.dict(S.C.run, {'web': False}):
            eq(P.serve(go), 1, '[run] web off: none')
        check('off here' in P.start(root), 'and w says why', P.start(root))


def test_private(tmp: Path) -> None:
    print('F402b1: the port taken and no Home: on 127.0.0.1, opened there; the run keeps that port')
    env: dict = {}
    root, port = project(tmp, env)
    taken = socket.socket()
    taken.bind(('0.0.0.0', port))
    taken.listen()
    with mock.patch.dict(os.environ, env), mock.patch.object(S, 'log'), mock.patch.object(P, 'held_messages'):
        CF._cfg.cache_clear()
        S.init(root)
        go = threading.Event()
        th = threading.Thread(target=lambda: P.serve(go), daemon=True)
        th.start()
        srv = None
        try:
            check(until(lambda: P.serving(root)), 'it serves')
            got = P.links(root)
            check(len(got) == 1 and got[0].startswith('http://127.0.0.1:') and f':{port}/' not in got[0],
                  'its own address, on this machine', got)
            eq(P.open_page(root, lambda u: f'opened {u}'), (f'opened {got[0]}', got[0]), 'w opens it')
            # the person sees Home's address once Home routes the project
            with mock.patch.object(W, 'site_urls', lambda *a, **k: ['http://h:1/p/proj/?t=k']):
                eq(P.links(root), ['http://h:1/p/proj/?t=k'], "Home's address when it routes the project")
            lock = plat.lock(S.C.notes('run.lock'))
            try:
                srv = W.start_web()
                eq(W.page_url(srv.server_address[1], srv.token, W.LOCAL), got[0], 'the run has the same address')
            finally:
                lock.close()
            th.join(10)
            check(not th.is_alive(), 'it ended')
            check(P.urls(root) == got, 'web.url is the run\'s', P.urls(root))
        finally:
            go.set()
            taken.close()
            if srv:
                srv.stop()
            th.join(10)


def in_tmp(f):
    def go():
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            f(Path(d))
    go.__name__ = f.__name__
    return go


if __name__ == '__main__':
    sys.exit(report([in_tmp(test_serves), in_tmp(test_start_from_page), in_tmp(test_ends), in_tmp(test_private)]))
