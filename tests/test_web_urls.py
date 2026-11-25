"""B815a: the run page's links: a Tailscale Serve https address only while Tailscale is connected.

    python3 tests/test_web_urls.py
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from unittest import mock

from _check import check, eq, report
from _web import fake_repo, in_tmp

from agent_runner import devices, page_https
from agent_runner import home as H
from agent_runner import state as S
from agent_runner import web as W

SERVE = {'TCP': {'8771': {'HTTPS': True}},
         'Web': {'box.tail.ts.net:8771': {'Handlers': {'/': {'Proxy': 'http://127.0.0.1:8770'}}}}}
HTTPS = 'https://box.tail.ts.net:8771/?t=TK'
RUN = subprocess.run
PLAIN = ['http://box:8770/?t=TK', 'http://10.0.0.5:8770/?t=TK']


class Tailscale:
    """A `tailscale` in state `state` with SERVE saved; it keeps what it was asked."""

    def __init__(self, state: str, code: int = 0, text: str | None = None):
        self.state, self.code, self.text, self.asked = state, code, text, []

    def __call__(self, argv, **kw):
        if argv[0] != 'tailscale':  # git and the rest, as they are
            return RUN(argv, **kw)
        self.asked.append(argv[1:])
        if argv[1:] == ['serve', 'status', '--json']:
            return subprocess.CompletedProcess(argv, 0, json.dumps(SERVE), '')
        text = json.dumps({'BackendState': self.state}) if self.text is None else self.text
        return subprocess.CompletedProcess(argv, self.code, text, '')

    def here(self):
        """This machine's `tailscale`, as every caller finds it."""
        ps = [mock.patch.object(W.sp, 'run', self),
              mock.patch.object(W.shutil, 'which', lambda n, *a, **k: f'/usr/bin/{n}'),
              mock.patch.dict(os.environ, {'AGENT_RUNNER_NO_SERVE': ''})]
        # the defaults bound sp.run as they loaded: give them this one
        ps.append(mock.patch.object(W, 'tailscale_https_urls', lambda port, t, f=W.tailscale_https_urls: f(port, t, run=self)))
        ps.append(mock.patch.object(page_https, 'backend', lambda run=self, f=page_https.backend: f(run)))
        return ps


def within(ts: Tailscale, do):
    ps = ts.here()
    for p in ps:
        p.start()
    try:
        return do()
    finally:
        for p in reversed(ps):
            p.stop()


def test_addresses(tmp: Path) -> None:
    for state in ('Stopped', 'NeedsLogin', 'Starting', ''):
        eq(W.tailscale_https_urls(8770, 'TK', run=Tailscale(state)), [], f'a saved rule, Tailscale {state!r}: no https address')
    eq(W.tailscale_https_urls(8770, 'TK', run=Tailscale('Running')), [HTTPS], 'connected: the https address')
    eq(W.tailscale_https_urls(8770, 'TK', run=Tailscale('Running', code=1)), [], 'tailscale status failed: none')
    for text in ('not json', '[]', ''):
        eq(W.tailscale_https_urls(8770, 'TK', run=Tailscale('', text=text)), [], f'status says {text!r}: none, no error')
    ts = Tailscale('Running')
    eq(W.tailscale_https_urls(9999, 'TK', run=ts), [], 'no rule for that port: none')
    eq(ts.asked, [['serve', 'status', '--json']], 'and the state is not asked for')
    with mock.patch.object(W.shutil, 'which', lambda *a, **k: None), \
            mock.patch.dict(os.environ, {'AGENT_RUNNER_NO_SERVE': ''}):
        eq(W.https_first(PLAIN, None), PLAIN, 'no tailscale binary: the plain links')
        check(not page_https.not_connected(), 'and it is not said to be stopped')

    def gone(*a, **k):
        raise FileNotFoundError('tailscale')
    eq(W.tailscale_https_urls(8770, 'TK', run=gone), [], 'a binary that does not start: none, no error')
    eq(page_https.backend(gone), '', 'nor a state')


def test_shown(tmp: Path) -> None:
    fake_repo(tmp)
    W.url_file().parent.mkdir(parents=True, exist_ok=True)
    W.url_file().write_text('\n'.join(PLAIN) + '\n', encoding='utf-8')

    def links():
        with mock.patch.object(S, 'run_up', return_value=True), mock.patch.object(W, 'site_urls', lambda *a, **k: []), \
                mock.patch.object(W, 'page_urls', lambda port, t: list(PLAIN)), \
                mock.patch.object(W, 'home_port', lambda: 0), mock.patch.object(H, 'home_token', lambda: 'TK'):
            return {'line': W.page_line(), 'shown': W.shown_links([], PLAIN), 'home': H.home_urls(8770),
                    'base': W.https_base(), 'why': W.no_https_why(), 'hint': devices.https_link()}
    off, ts = Tailscale('Stopped'), Tailscale('Running')
    got = within(off, links)
    eq(got['line'], f'run page: {PLAIN[0]} (or {PLAIN[1]})', 'stopped: status, the terminal UI and the picker say the plain links')
    eq(got['shown'], PLAIN, 'the run log too')
    eq(got['home'], PLAIN, "and Home's links")
    eq((got['base'], got['hint']), ('', ''), "no https for option links or the page's https hint")
    eq(got['why'], 'Tailscale is not connected', 'and why')
    check(all(a in (['serve', 'status', '--json'], ['status', '--json']) for a in off.asked),
          'the saved rule is only read', off.asked)
    got = within(ts, links)
    eq(got['line'], f'run page: {HTTPS} (or {PLAIN[0]})', 'connected: https first')
    eq(got['shown'], [HTTPS] + PLAIN, 'in the run log too')
    eq(got['home'], [HTTPS] + PLAIN, "and Home's links")
    eq((got['base'], got['hint']), ('https://box.tail.ts.net:8771', HTTPS + '#tools'), 'option links and the hint')


def test_offer(tmp: Path) -> None:
    said, ran = [], []
    offer = lambda: H.offer_https(8770, PLAIN, call=lambda c: ran.append(c) or (0, ''), out=said.append,  # noqa: E731
                                  ask=lambda q: True, which=lambda n: '/usr/bin/' + n)
    eq(within(Tailscale('Stopped'), offer), PLAIN, 'stopped: home install gives the plain links')
    eq(ran, [], 'and runs no tailscale serve')
    within(Tailscale('', code=1), offer)
    eq(ran, [], 'nor with a Tailscale that does not answer')
    eq(said[:1], ["No https link while Tailscale is not connected: Talk's mic needs one."], 'and says why')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_addresses), in_tmp(test_shown), in_tmp(test_offer)]))
