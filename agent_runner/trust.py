"""F136: trusted networks: where a page (Runner Home's, a run's own) opens without its key (`?t=`).

Off by default. The networks are CIDRs, `tailnet` for Tailscale's own two,
F481: a host name (its device's addresses, looked up again after NAME_TTL), or `all` (no key anywhere). A request is let in by its client's
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


ALL = 'all'  # F481: any network: no key anywhere
ALL_CIDRS = ('0.0.0.0/0', '::/0')
HOST_NAME = re.compile(r'(?=.*[a-zA-Z])[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?)*\.?')
NAME_TTL = 60.0  # F481: a host name is looked up again after this long, so a changed Tailscale address still works
_names: dict = {}  # name -> (when, [addresses])
KINDS = f'write a CIDR like 192.168.1.0/24, {TAILNET}, a host name like box.tail1.ts.net, or {ALL}'


def _host_name(name: str) -> bool:
    return '/' not in name and bool(HOST_NAME.fullmatch(name))


def name_addresses(name: str, look=None) -> list:
    """F481: the addresses host name `name` resolves to, from a short cache ([] when it does not resolve)."""
    import time
    now = time.monotonic()
    got = _names.get(name)
    if look is None and got and now - got[0] < NAME_TTL:
        return got[1]
    try:
        ips = sorted({str(a[4][0]).split('%')[0] for a in (look or socket.getaddrinfo)(name, None)})
    except (OSError, UnicodeError):
        ips = []
    if look is None:
        _names[name] = (now, ips)
    return ips


def network_problem(name) -> str:
    """Why `name` is no network ('' when it is one)."""
    if not isinstance(name, str):
        return f'{name!r} is not a network'
    if name in (TAILNET, ALL):
        return ''
    if _host_name(name):
        return '' if name_addresses(name) else f'{name!r} does not resolve: no device has that name here; {KINDS}'
    try:
        ipaddress.ip_network(name)
        return ''
    except ValueError as e:
        return f'{name!r} is not a network ({e}): {KINDS}'


def networks(names) -> list:
    """The networks `names` stand for; one that is no network is left out (it trusts nobody)."""
    out = []
    for n in names if isinstance(names, (list, tuple)) else ():
        if not network_problem(n):
            cidrs = TAILNET_CIDRS if n == TAILNET else ALL_CIDRS if n == ALL else (
                name_addresses(n) if _host_name(n) else (n,))
            out += [ipaddress.ip_network(c) for c in cidrs]
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
        host = urlsplit(u).hostname or ''
        # a name `from_page` refuses needs its key
        ips = _addresses(host, look or socket.getaddrinfo) if _own_name(urlsplit(u).netloc) else []
        out.append(re.sub(r'\?t=[^&#]*', '', u, count=1) if ips and all(_in(ip, nets) for ip in ips) else u)
    return out
