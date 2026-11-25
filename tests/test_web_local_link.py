"""B815b: the run page's localhost link: listed with and without Tailscale, opened by the picker, Home's behind Home.

    python3 tests/test_web_local_link.py
"""
from __future__ import annotations

import os
import urllib.request
from pathlib import Path
from unittest import mock

from _check import check, eq, report
from _web import fake_repo, in_tmp

from agent_runner import cmds as M
from agent_runner import devices
from agent_runner import home as H
from agent_runner import page_only as P
from agent_runner import state as S
from agent_runner import web as W

OWN = ['http://box:8770/?t=TK', 'http://10.0.0.5:8770/?t=TK']
HERE = 'http://localhost:8770/?t=TK'
HTTPS = 'https://box.tail.ts.net:8771/?t=TK'
SITE = ['http://box:8770/p/proj/?t=HT']
SITE_HERE = 'http://localhost:8770/p/proj/?t=HT'
NONE = lambda port, token: []  # noqa: E731 - no Tailscale
TAIL = lambda port, token: [HTTPS]  # noqa: E731


def test_listed(tmp: Path) -> None:
    fake_repo(tmp)
    eq(W.local_link(OWN), HERE, 'the localhost address, with the key')
    eq(W.local_link(SITE), SITE_HERE, "at Home's path")
    eq(W.local_link([]), '', 'no address: none')
    eq(W.local_link(['http://127.0.0.1:4444/?t=TK']), '', 'F165: none for the port only Home opens')
    eq(W.local_link([HTTPS, *OWN]), HERE, 'from the http address, not the https port')
    eq(W.shown_links([], OWN, NONE), [*OWN, HERE], 'no Tailscale: listed, last')
    eq(W.shown_links([], OWN, TAIL), [HTTPS, *OWN, HERE], 'Tailscale: https first, localhost still listed')
    eq(W.shown_links([], [], NONE), [], 'nothing to open: nothing listed')
    with mock.patch.object(W, 'run_trusted', lambda: ['10.0.0.0/24']):
        eq(W.shown_links([], OWN[1:], NONE), ['http://10.0.0.5:8770/', HERE], 'a trusted network: localhost keeps its key')
    W.url_file().parent.mkdir(parents=True, exist_ok=True)
    W.url_file().write_text('\n'.join(OWN) + '\n', encoding='utf-8')
    with mock.patch.object(S, 'run_up', return_value=True):
        for look, want in ((NONE, f'{OWN[0]} (or {OWN[1]} or {HERE})'), (TAIL, f'{HTTPS} (or {OWN[0]} or {HERE})')):
            with mock.patch.object(W, 'tailscale_https_urls', look):
                eq(W.page_line(lambda: []), f'run page: {want}', 'status has it')


def started(site: list[str], home: int):
    """(the server, what the run log said) of a run's start on a free port."""
    log: list[str] = []
    with mock.patch.dict(os.environ, {'AGENT_RUNNER_NO_WEB': ''}), mock.patch.object(W, 'lan_ip', lambda: ''), \
            mock.patch.dict(S.C.run, {'web': True, 'web_port': 0, 'web_https': False}), \
            mock.patch.object(W, 'home_port', lambda: home), mock.patch.object(W, 'site_urls', lambda *a, **k: list(site)), \
            mock.patch.object(W, 'tailscale_https_urls', NONE), mock.patch.object(S, 'log', log.append):
        return W.start_web(), log


def test_served(tmp: Path) -> None:
    fake_repo(tmp)
    srv, log = started([], 0)
    port = srv.server_address[1]
    try:
        here = f'http://localhost:{port}/?t={W.web_token()}'
        check(any(here in x for x in log), 'the run log has it', log)
        with urllib.request.urlopen(here, timeout=10) as r:
            eq((r.status, b'<html' in r.read()), (200, True), 'the server opens it')
        check('localhost' not in W.url_file().read_text(encoding='utf-8'), 'web.url keeps the addresses Home reads')
        eq(devices.channel('127.0.0.1', {'Host': f'localhost:{port}', 'Origin': f'http://localhost:{port}'}), '',
           'and takes a secret there, as from loopback')
    finally:
        srv.stop()


def test_behind_home(tmp: Path) -> None:
    fake_repo(tmp)
    srv, log = started(SITE, 8770)
    port = str(srv.server_address[1])
    try:
        check(srv.private(), 'only Home opens its port')
        said = ' '.join(log)
        check(SITE_HERE in said and port not in said, "the log has Home's localhost link, not the run's port", log)
        with mock.patch.object(S, 'run_up', return_value=True), mock.patch.object(W, 'tailscale_https_urls', NONE):
            eq(W.page_line(lambda: SITE), f'run page: {SITE[0]} (or {SITE_HERE})', 'and so has status')
            with mock.patch.object(W, 'closed_line', lambda: 'Home is down'):
                eq(W.page_line(lambda: []), 'run page: Home is down', 'Home down: no localhost link to its port')
    finally:
        srv.stop()


def test_own_port_and_home(tmp: Path) -> None:
    fake_repo(tmp)
    srv, log = started(SITE, 0)  # Home routes it, and its own port is open too
    try:
        port = srv.server_address[1]
        said = ' '.join(log).replace(' or ', ' ').split()
        links = [x for x in said if x.startswith('http')]
        eq((links[0], links[-1], len(links)), (SITE[0], SITE_HERE, 3), "Home's, its own, then Home's localhost link")
        check(f':{port}/' in links[1], 'its own address by hostname', links)
    finally:
        srv.stop()


def test_home_opens_it(tmp: Path) -> None:
    fake_repo(tmp)
    home = H.serve_home('HT', 0, rows=lambda: [])
    try:
        with urllib.request.urlopen(f'http://localhost:{home.server_address[1]}/?t=HT', timeout=10) as r:
            eq((r.status, b'<html' in r.read()), (200, True), 'Home takes its localhost link')
    finally:
        home.stop()


def facts_of(root: Path, own: list[str], site: list[str], https) -> dict:
    S.C.todo.parent.mkdir(parents=True, exist_ok=True)
    S.C.todo.write_text('- [ ] **B1** one\n', encoding='utf-8')
    W.url_file().parent.mkdir(parents=True, exist_ok=True)
    W.url_file().write_text('\n'.join(own) + '\n', encoding='utf-8')
    return M.run_facts(root, {'up': True}, https, lambda r: list(site))


def test_picker(tmp: Path) -> None:
    root = fake_repo(tmp)
    private = ['http://127.0.0.1:4444/?t=TK']
    for own, site, https, link, here, why in (
            (OWN, [], NONE, OWN[0], HERE, 'no Tailscale'),
            (OWN, [], TAIL, HTTPS, HERE, 'Tailscale connected'),
            (private, SITE, NONE, SITE[0], SITE_HERE, 'behind Home'),
            (private, [], NONE, '', '', 'only Home opens it, and it does not')):
        facts = facts_of(root, own, site, https)
        eq((facts['link'], facts['local']), (link, here), f'{why}: the link and the localhost one')
        acted, shown = [], []
        acts = {'w': lambda u: acted.append(('w', u)) or 'opened', 'c': lambda u: acted.append(('c', u)) or 'copied'}
        row = {'root': root, 'name': 'proj', 'run': {'up': True}, **facts}
        it = iter(('w', 'c', 'q'))
        M.launch(row, lambda: next(it), shown.append, acts)
        eq(acted, [('w', here), ('c', link)] if link else [], f'{why}: w opens localhost, c copies the link for other devices')
    row = {'root': root, 'name': 'proj', 'run': {'up': True}, **facts_of(root, OWN, [], NONE)}
    it, shown = iter(('w', 'q')), []
    M.launch(row, lambda: next(it), shown.append, {'w': lambda u: f'no browser here: {u}'})
    check(f'no browser here: {OWN[0]}\n' in shown[-1], 'no browser here (ssh): the link another device opens is named', shown[-1])
    with mock.patch('agent_runner.tui.refusal', lambda: 'no terminal UI here:'), mock.patch.object(M.plat, 'WINDOWS', True), \
            mock.patch.object(M, 'run_facts', lambda r, run: {'link': HTTPS, 'local': HERE}):
        eq(M.open_ui(root), f'no terminal UI here: {HERE}', "Windows' t names the localhost link")


def test_page_only(tmp: Path) -> None:
    root, opened = fake_repo(tmp), []
    opener = lambda u: opened.append(u) or 'opened'  # noqa: E731
    with mock.patch.object(P, 'start', lambda r: ''), mock.patch.object(P, 'serving', lambda r=None: True), \
            mock.patch.object(P, 'urls', lambda r=None: OWN), mock.patch.object(W, 'site_urls', lambda *a, **k: []), \
            mock.patch.object(W, 'tailscale_https_urls', TAIL):
        eq(P.open_page(root, opener), ('opened', HTTPS), 'no run up: the launcher shows the https link')
        with mock.patch.object(W, 'site_urls', lambda *a, **k: SITE):
            eq(P.open_page(root, opener)[0], 'opened', 'and through Home')
        with mock.patch.object(W, 'run_trusted', lambda: ['10.0.0.0/24']), mock.patch.object(P, 'urls', lambda r=None: OWN[1:]), \
                mock.patch.object(W, 'tailscale_https_urls', NONE):
            eq(P.open_page(root, opener), ('opened', 'http://10.0.0.5:8770/'), 'on a trusted network')
            eq(opened.pop(), HERE, 'localhost is opened with its key')
    with mock.patch.object(P, 'start', lambda r: ''), mock.patch.object(P, 'links', lambda r: []), \
            mock.patch.object(M, 'run_info', lambda r: {'up': True}), \
            mock.patch.object(M, 'run_facts', lambda r, run: {'link': HTTPS, 'local': HERE}):
        eq(P.open_page(root, opener), ('opened', HTTPS), 'a run that came up meanwhile')
    eq(opened, [HERE, SITE_HERE, HERE], 'each opened by localhost')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_listed), in_tmp(test_served), in_tmp(test_behind_home),
                             in_tmp(test_own_port_and_home), in_tmp(test_home_opens_it), in_tmp(test_picker), in_tmp(test_page_only)]))
