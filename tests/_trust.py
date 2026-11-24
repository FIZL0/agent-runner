"""F136: the checks of a page opened without its key, the same for Runner Home and a run's own page."""
from __future__ import annotations

import urllib.error
import urllib.request

from _check import eq


def asked(url: str, peer: str = '', srv=None, post: bool = False, **headers) -> int:
    """F136: the status of `url` asked with `headers` (X_Forwarded_For=…), as a client at `peer` ('': loopback)."""
    real = type(srv).get_request
    srv.get_request = lambda: (lambda got: (got[0], (peer or got[1][0], got[1][1])))(real(srv))
    req = urllib.request.Request(url, data=b'{}' if post else None,
                                 headers={k.replace('_', '-'): v for k, v in headers.items()})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            asked.headers = r.headers
            return r.status
    except urllib.error.HTTPError as e:
        e.read()
        return e.code
    finally:
        del srv.get_request


def trusted_checks(srv, base: str, trusted, path: str, key: str) -> None:
    """F136: what opens `path` without the key; `trusted(list)` sets the page's networks."""
    ts, lan = '100.101.1.2', '192.168.1.9'

    def ask(peer='', **h) -> int:
        return asked(base + path, peer, srv, **h)
    eq([ask(), ask(ts), ask(X_Forwarded_For=ts)], [403] * 3, 'no trusted networks (the default): the key is needed')
    trusted(['tailnet'])
    eq([ask(ts), ask('::ffff:' + ts), ask('fd7a:115c:a1e0::5')], [200] * 3, 'a client on a trusted network: in with no key')
    eq(asked(f'{base}{path}?t=OLD', ts, srv), 200, 'an old key is no bar there')
    eq(ask(lan), 403, 'a client on another network: refused')
    eq([ask(), ask(X_Forwarded_For='127.0.0.1'), ask(X_Forwarded_For='nonsense')], [403] * 3,
       'loopback with no X-Forwarded-For, or one that names no network client: refused')
    eq(ask(X_Forwarded_For=ts), 200, 'loopback with a trusted X-Forwarded-For (Tailscale Serve): in')
    eq(ask(X_Forwarded_For=f'{ts}, {lan}'), 403, 'what the proxy added last counts, not what the client said before it')
    eq(ask(lan, X_Forwarded_For=ts), 403, 'X-Forwarded-For from a peer that is not loopback is ignored')
    eq(ask(ts, X_Forwarded_For=lan), 200, 'either way')
    eq(asked.headers.get('X-Frame-Options'), 'SAMEORIGIN', 'a page opened with no key is framed by its own pages only')
    eq(ask(ts, Origin=base), 200, 'a request of its own page: in')
    eq([ask(ts, Origin='http://evil.example'), ask(ts, Origin='null'), ask(ts, Sec_Fetch_Site='cross-site'),
        ask(ts, Sec_Fetch_Site='same-site')], [403] * 4, "another web site's page: refused")
    eq(ask(ts, Sec_Fetch_Site='cross-site', Sec_Fetch_Mode='navigate', Sec_Fetch_Dest='document'), 200, 'a link to it opens')
    eq(asked(f'{base}/act', ts, srv, post=True, Origin='http://evil.example'), 403, 'nor may it send an action')
    eq(ask(ts, Host='evil.example', Origin='http://evil.example'), 403, "nor one whose name leads here")
    eq(ask(ts, Host='box.tail1.ts.net', Origin='https://box.tail1.ts.net'), 200, 'the tailnet name is its own')
    eq(asked(f'{base}{path}?t={key}', lan, srv, Origin='http://evil.example'), 200, 'with the key: as before')
    trusted(['127.0.0.0/8', 'nonsense'])
    eq([ask(), ask(X_Forwarded_For='127.0.0.1')], [403, 403], 'loopback is never trusted, even listed')
    trusted(['192.168.1.0/24'])
    eq([ask(lan), ask(ts)], [200, 403], 'a CIDR trusts its own clients only')
    trusted([])
    eq(ask(ts), 403, 'taken off the list: the key is needed again, with no restart')
