"""C45: the run page's web.py, Runner Home's watch on this run's page, and the run's start of it.

Part of `web`: `web` runs this file in its own namespace (see its PARTS), so these names are `web`'s, and a test that sets
`web.X` reaches the code here. Not imported on its own."""


def home_installed() -> bool:
    """F94: is Runner Home set up on this machine (`home install`, no `uninstall` since)?"""
    try:
        from agent_runner.home import home_on
        return home_on()
    except Exception:  # noqa: BLE001 - a run's page never fails over Home
        return False


def home_port() -> int:
    """B146: the port Runner Home serves on (`port` in its registry, 8770), 0 while it is not installed."""
    try:
        if home_installed():
            from agent_runner.home import load_registry
            return int(load_registry()['port'])
    except Exception:  # noqa: BLE001 - a run's page never fails over Home
        pass
    return 0


def home_only() -> bool:
    """F165: is this run's page Runner Home's alone to open? With Home installed, unless the person set `[run]
    web_port` (runner.toml or runner.local.toml) to a port other than Home's own, which is kept for Home."""
    port = home_port()
    return bool(port) and ('web_port' not in S.C.given.get('run', ()) or S.C.run.get('web_port') == port)


def write_urls(srv: WebServer) -> list[str]:
    """Keep the page's own addresses in <notes>/web.url (Home reads the port and token there): returns them."""
    port = srv.server_address[1]
    urls = [page_url(port, srv.token, LOCAL)] if srv.private() else page_urls(port, srv.token)
    url_file().write_text('\n'.join(urls) + '\n', encoding='utf-8')
    return urls


class HomeWatch:
    """F165: while a run is up, what Runner Home does to its page. `look` every HOME_LOOK s: Home installed
    meanwhile: the page leaves its port for 127.0.0.1; on 127.0.0.1 and nothing opens it on two checks in a row
    (a restart of Home is over by then): the run log says so and how to start Home, once, and when it is back."""

    def __init__(self, srv: WebServer, said: str = ''):
        self.srv, self.said, self.missed, self.looks = srv, said, 0, 0

    def look(self) -> None:
        if not self.srv.private():
            if not home_only() or not self.srv.go_private():
                return
            write_urls(self.srv)
            S.log('run page: Runner Home is installed, so only Home opens it now')
            self.missed = 0
            return
        self.looks += 1
        if self.looks % HOME_CHECK:
            return
        from agent_runner.home import site_links, why_closed
        if urls := site_links(S.C.root, https=lambda port, token: []):
            self.missed = 0
            if self.said:
                self.said = ''
                S.log(f'run page: {" or ".join(shown_links(urls, []))}')
            return
        self.missed += 1
        if self.missed >= 2 and (why := why_closed(S.C.root)) != self.said:
            self.said = why
            S.log(f'run page: {why}')

    def loop(self) -> None:
        while not self.srv.stopped.wait(HOME_LOOK):
            try:
                self.look()
            except Exception as e:  # noqa: BLE001 - the run goes on whatever Home does
                S.log(f'run page: looking for Runner Home failed ({type(e).__name__}: {e})')


HOME_LOOK = 2.0  # s between two looks (Home's install waits 8 s for its port)
HOME_CHECK = 10  # looks between two checks that Home opens the page


def serve_again(port: int) -> WebServer | None:
    """F402b1: the page on 127.0.0.1 at the `port` the page-only process had it on, so a page open there reconnects;
    None when there was none (0) or it cannot be had."""
    try:
        return serve(web_token(), port, LOCAL) if port else None
    except OSError:
        return None


def start_web(only: bool = False) -> WebServer | None:
    """The run's start: serve the page when `[run] web` is on (the run log gets its address), else nothing.
    F165: on `[run] web_port` for every interface, but with Runner Home installed (`home_only`), or that port
    taken by another, on 127.0.0.1 for Home alone: no project is on a port of its own unless the person set one.
    Without Home the first run up has web_port, and another one's log and status offer `home install`.
    A port in use costs the page, not the run. AGENT_RUNNER_NO_WEB=1 (the test suites) turns it off too.
    F402b1: `only`: the page-only process serves it; a run takes the page over from one that does."""
    from agent_runner import page_only
    was = 0 if only else page_only.take_over()
    url_file().unlink(missing_ok=True)
    r = S.C.run
    if not r.get('web', True) or os.environ.get('AGENT_RUNNER_NO_WEB'):
        page_https.left_over()
        return None
    from agent_runner.ui_model import SETTINGS_AT, settings_start
    if not only and not SETTINGS_AT[0]:  # F202a: a run took it as it read its settings
        settings_start()  # F166
    port = int(r.get('web_port', 8770))
    srv, why = None, ''
    if home_only():  # B146: Home's port is Home's, even while Home is not up yet
        if 'web_port' in S.C.given.get('run', ()):
            why = 'Runner Home is installed, so its port is kept for it'
    else:
        try:
            srv = serve(web_token(), port)
        except OSError as e:
            why = f'port {port} is taken ({e})'
    if srv is None:
        try:
            srv = serve_again(was) or serve(web_token(), 0, LOCAL)
        except OSError as e2:
            S.log(f'run page: cannot serve it ({e2}); set [run] web_port, or web = false')
            page_https.left_over()
            return None
        if why:
            S.log(f'run page: {why}, so only Runner Home opens it')
    urls = own_links(write_urls(srv))
    if r.get('web_https', True) and not srv.private():  # F96
        srv.https = page_https.https_on(srv.server_address[1])
    else:
        page_https.left_over()
    # B129: the run log names a Tailscale Serve https address first too (the mic needs https); web.url stays http.
    # B146: the device site's /p/KEY/ address first when one routes this project
    site = site_urls()
    shown = shown_links(site, urls)
    # B815b: the localhost link is Home's then, still the last
    own = [x for x in (shown_links([], urls) if site else []) if x not in shown and urlsplit(x).hostname != 'localhost']
    shown = shown[:-1] + own + shown[-1:] if site else shown
    closed = '' if shown else closed_line()
    S.log(f'run page: {" or ".join(shown) or closed}' +
          ('' if U.find_ttyd() else ' (ttyd is not installed, so a chat cannot show its session)'))
    threading.Thread(target=HomeWatch(srv, closed).loop, name='run-page-home', daemon=True).start()
    return srv
