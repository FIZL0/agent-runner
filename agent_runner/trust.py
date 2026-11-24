"""F136: trusted networks: where a page (Runner Home's, a run's own) opens without its key (`?t=`).

Off by default. The networks are CIDRs, or `tailnet` for Tailscale's own two. A request is let in by its client's
address: the connection's, or, behind a proxy on this machine (Tailscale Serve), the address that proxy puts last in
X-Forwarded-For; the header counts from a loopback peer only. A loopback client is never trusted.

The key is also what kept other web sites out: a page in a trusted device's browser can send requests here. So with no
key a request must come from the page itself (`from_page`).
"""
from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urlsplit

TAILNET = 'tailnet'
TAILNET_CIDRS = ('100.64.0.0/10', 'fd7a:115c:a1e0::/48')
LOCAL_ENDS = ('.local', '.lan', '.home', '.home.arpa', '.internal', '.localdomain')  # names no public DNS gives out


def network_problem(name) -> str:
    """Why `name` is no network ('' when it is one)."""
    if not isinstance(name, str):
        return f'{name!r} is not a network'
    if name == TAILNET:
        return ''
    try:
        ipaddress.ip_network(name)
        return ''
    except ValueError as e:
        return f'{name!r} is not a network ({e}): write a CIDR like 192.168.1.0/24, or {TAILNET}'


def networks(names) -> list:
    """The networks `names` stand for; one that is no network is left out (it trusts nobody)."""
    out = []
    for n in names if isinstance(names, (list, tuple)) else ():
        if not network_problem(n):
            out += [ipaddress.ip_network(c) for c in (TAILNET_CIDRS if n == TAILNET else (n,))]
    return out


def _address(text: str):
    try:
        ip = ipaddress.ip_address(str(text).strip().split('%')[0])
    except ValueError:
        return None
    return getattr(ip, 'ipv4_mapped', None) or ip


def _in(ip, nets: list) -> bool:
    return ip is not None and not ip.is_loopback and any(ip in n for n in nets)  # another IP version is not in


def client(peer: str, headers):
    """The client's address (None: unknown): the peer's, or, from a loopback peer, the last one in X-Forwarded-For,
    the one the proxy on this machine added (what comes before it is the client's own word)."""
    ip = _address(peer)
    if ip is not None and ip.is_loopback:
        return _address(','.join(headers.get_all('X-Forwarded-For') or []).split(',')[-1])
    return ip


def _own_name(host: str) -> bool:
    """Is `host` (a Host header) a name only this machine has? Another site's name may be made to lead here (DNS
    rebinding), and its page would then count as this one."""
    try:
        name = (urlsplit(f'//{host}').hostname or '').rstrip('.')
    except ValueError:
        return False
    if _address(name) or name == 'localhost' or name.endswith('.ts.net'):
        return True
    me = socket.gethostname().lower()
    return bool(name) and (name == me or name == me.split('.')[0]
                           or ('.' not in name) or name.endswith(LOCAL_ENDS))


def from_page(method: str, peer: str, headers) -> bool:
    """Did the page itself (or the person, opening it) send this, not another web site's page?"""
    ip = _address(peer)
    host = (headers.get('Host') or '').strip().lower()
    if ip is not None and ip.is_loopback and headers.get('X-Forwarded-Host'):
        host = headers['X-Forwarded-Host'].split(',')[-1].strip().lower()
    if not _own_name(host):
        return False
    origin = headers.get('Origin')
    if origin is not None:
        try:
            if urlsplit(origin.lower()).netloc != host:
                return False
        except ValueError:
            return False
    if (headers.get('Sec-Fetch-Site') or 'none') in ('same-origin', 'none'):
        return True
    return method == 'GET' and headers.get('Sec-Fetch-Mode') == 'navigate' and headers.get('Sec-Fetch-Dest') == 'document'


def lets_in(names, method: str, peer: str, headers) -> bool:
    """May this request in without the key?"""
    nets = networks(names)
    return bool(nets) and _in(client(peer, headers), nets) and from_page(method, peer, headers)


def _addresses(host: str, look) -> list:
    if ip := _address(host):
        return [ip]
    try:
        return [_address(a[4][0]) for a in look(host, None)]
    except (OSError, UnicodeError):
        return []


def shown(urls: list[str], names, look=None) -> list[str]:
    """`urls` as they are printed: a link whose host has trusted addresses only goes without its key."""
    nets = networks(names)
    if not nets:
        return list(urls)
    out = []
    for u in urls:
        ips = _addresses(urlsplit(u).hostname or '', look or socket.getaddrinfo)
        out.append(re.sub(r'\?t=[^&#]*', '', u, count=1) if ips and all(_in(ip, nets) for ip in ips) else u)
    return out
