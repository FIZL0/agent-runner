"""C45: the run page's web.py, the page file, the token and the page's addresses.

Part of `web`: `web` runs this file in its own namespace (see its PARTS), so these names are `web`'s, and a test that sets
`web.X` reaches the code here. Not imported on its own."""

PAGE_DIR = Path(__file__).with_name('page')  # C41a: the page's CSS and scripts, one file per area


class PageFile:
    """C41a: web_page.html is the page's frame; its parts (agent_runner/page/NNN-area.css, .logic.js, .js) go in at
    its /*PAGE_PARTS:kind*/ lines in the order of their names, so the one page the server sends is the same as
    when it was a single file. `read_text` is the joined page, for whoever read the file before."""

    def __init__(self, frame: Path, parts: Path):
        self.frame, self.parts = frame, parts

    def read_text(self, encoding: str = 'utf-8') -> str:
        page = self.frame.read_text(encoding=encoding)
        for kind, ext in (('css', '.css'), ('logic', '.logic.js'), ('js', '.js')):
            names = sorted(p for p in self.parts.glob('*' + ext) if kind == 'logic' or not p.name.endswith('.logic.js'))
            page = page.replace(f'/*PAGE_PARTS:{kind}*/\n', ''.join(p.read_text(encoding=encoding) for p in names), 1)
        return page

    def __str__(self) -> str:
        """A path to the joined page, for a node script that reads it as a file (the tests' drivers)."""
        text = self.read_text()
        at = Path(tempfile.gettempdir()) / f"agent-runner-page-{hashlib.sha256(text.encode('utf-8')).hexdigest()[:12]}.html"
        if not at.is_file():
            part = at.with_suffix(f'.{os.getpid()}.tmp')
            part.write_text(text, encoding='utf-8')
            part.replace(at)
        return str(at)


PAGE =PageFile(Path(__file__).with_name('web_page.html'), PAGE_DIR)
# B164: the page as it was when this process loaded its code: an update on disk while the run is up must not
# serve a page that asks for routes and actions this run does not have. A restart serves the new one.
PAGE_TEXT = PAGE.read_text(encoding='utf-8')
PAGE_PRINT = hashlib.sha256(PAGE_TEXT.encode('utf-8')).hexdigest()[:12]  # F149: which page this process serves
BOOT = secrets.token_hex(4)  # B164: this process, so the page knows when the run restarted
TICK = 2.0  # s between snapshots the events stream compares
PING = 15.0  # s of no change before the stream sends a keep-alive comment
# B761: said only where ttyd_install_cmd finds no package manager
TTYD_INSTALL = ('Arch: pacman -S ttyd; Debian/Ubuntu: apt install ttyd; macOS: brew install ttyd; Windows: winget '
                'install tsl0922.ttyd')


# --- the token and the address ----------------------------------------------------------------------------------

def token_file() -> Path:
    return S.C.notes('web.token')


def web_token() -> str:
    """This project's run page token: read from <notes>/web.token, made there (owner-only) the first time."""
    f = token_file()
    try:
        if t := f.read_text(encoding='utf-8').strip():
            return t
    except OSError:
        pass
    t = secrets.token_urlsafe(18)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(t + '\n', encoding='utf-8')
    try:
        os.chmod(f, 0o600)
    except OSError:
        pass
    return t


def page_url(port: int, token: str, host: str = '') -> str:
    return f'http://{host or socket.gethostname()}:{port}/?t={token}'


def lan_ip() -> str:
    """This machine's address on the network it routes out of ('' if none): a phone that cannot resolve the
    bare hostname still reaches this. No packet is sent (a UDP connect only picks the route)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(('192.0.2.1', 9))
            ip = s.getsockname()[0]
        return '' if ip.startswith('127.') else ip
    except OSError:
        return ''


def serve_https_urls(status: dict, port: int, token: str) -> list[str]:
    """B130: the https addresses `tailscale serve status --json` (parsed as `status`) proxies to this machine's
    `port`, with the token: `https://HOST:PORT/?t=TOKEN` for each Web entry whose handler proxies there."""
    out = []
    for hostport, web in ((status or {}).get('Web') or {}).items():
        for h in ((web or {}).get('Handlers') or {}).values():
            m = re.fullmatch(r'https?://(?:127\.0\.0\.1|localhost|\[::1\]|0\.0\.0\.0):(\d+)/?', str((h or {}).get('Proxy', '')))
            if m and int(m.group(1)) == port:
                host, _, p = hostport.rpartition(':')
                if host and ((status.get('TCP') or {}).get(p) or {}).get('HTTPS') is True:
                    out.append(f'https://{host}' + ('' if p == '443' else f':{p}') + f'/?t={token}')
                break
    return out


def tailscale_https_urls(port: int, token: str, run=sp.run) -> list[str]:
    """B130: the https addresses Tailscale Serve gives the page on `port` ([] without tailscale or a serve for
    it). Safari's mic needs a secure context, so these come first where the page's address is printed."""
    if run is sp.run and not shutil.which('tailscale'):
        return []
    try:
        r = run(['tailscale', 'serve', 'status', '--json'], capture_output=True, text=True, timeout=5)
        return serve_https_urls(json.loads(r.stdout or '{}'), port, token) if r.returncode == 0 else []
    except (OSError, ValueError, sp.SubprocessError):
        return []


def page_urls(port: int, token: str) -> list[str]:
    """The page's addresses: by hostname, then by LAN address when there is one."""
    return [page_url(port, token)] + ([page_url(port, token, ip)] if (ip := lan_ip()) else [])


def url_file() -> Path:
    return S.C.notes('web.url')


def site_urls(root: Path | None = None, https=None) -> list[str]:
    """B146: the run app's addresses through the device site (home.site_links: Runner Home's /p/KEY/ on its port)
    for the project at `root` (this run's), [] while nothing on the device routes it. Worked out each time it is
    shown, never kept in <notes>/web.url: that keeps the run's own port, which Home routes to, and the device
    site can come up or go after the run starts."""
    try:
        from agent_runner.home import site_links
        return site_links(root or S.C.root, https=https)
    except Exception:  # noqa: BLE001 - the run's own link still works without Home
        return []


LOCAL = '127.0.0.1'


def own_links(urls: list[str]) -> list[str]:
    """F165: of a run's own addresses (<notes>/web.url), those another device may open: not the 127.0.0.1 one,
    which is there for Runner Home only and is never shown."""
    return [u for u in urls if urlsplit(u).hostname != LOCAL]


def closed_line() -> str:
    """F165: why nothing opens this run's page, and what opens it (home.why_closed)."""
    from agent_runner.home import why_closed
    return why_closed(S.C.root)


def run_trusted() -> list[str]:
    """F136: the networks this run's own page opens to without its key."""
    return S.C.raw['ui'].get('trusted_networks') or [] if S.C else []


def shown_links(site: list[str], own: list[str], https=None) -> list[str]:
    """F136: the page's addresses as they are printed: Runner Home's (`site`) when it routes the run, else the run's
    own, https first, each without its key where the page's network is trusted (trust.shown)."""
    if site:
        from agent_runner.home import load_registry
        got = trust.shown(https_first(site, https), load_registry()['trusted_networks'])
        if own and not any(u.startswith('https://') for u in got):  # F96: the run's own https address, ahead of http
            got = [u for u in shown_links([], own, https) if u.startswith('https://')] + got
        return got
    return trust.shown(https_first(own, https), run_trusted())


def https_first(urls: list[str], https=None) -> list[str]:
    """`urls` with the Tailscale Serve https addresses for the first one's port ahead of them, at its path
    (/p/KEY/ through the device site, B146) and with its token (B130: Safari's mic needs https)."""
    if not urls:
        return []
    u = urlsplit(urls[0])
    if u.port and (t := (parse_qs(u.query).get('t') or [''])[0]):
        path = u.path or '/'
        got = [x.replace('/?t=', f'{path}?t=', 1) for x in (https or tailscale_https_urls)(u.port, t)]
        return [x for x in got if x not in urls] + urls
    return list(urls)


def page_line(site=None) -> str:
    """`run page: URL` while a run serves the page (what `status` prints), else ''. B146: the device site's
    /p/KEY/ address when one routes this project (site_urls), else the run's own; F165: with neither, why; B130: a Tailscale Serve https
    address for that port comes first (Safari's mic needs https); <notes>/web.url keeps the run's own http ones,
    which Home reads its port from."""
    try:
        if S.run_up() and (us := url_file().read_text(encoding='utf-8').split()):
            us = shown_links((site or site_urls)(), own_links(us))
            if not us:
                return f'run page: {closed_line()}'
            return f'run page: {us[0]}' + (f' (or {us[1]})' if len(us) > 1 else '')
    except (OSError, ValueError):
        pass
    return ''


