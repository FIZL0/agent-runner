"""C45: the run page's web.py, a slot's diff and the ttyd terminals.

Part of `web`: `web` runs this file in its own namespace (see its PARTS), so these names are `web`'s, and a test that sets
`web.X` reaches the code here. Not imported on its own."""

DIFF_BYTES = 200_000  # the most of a slot's diff the diff tab shows


def slot_diff(name: str) -> dict:
    """F75: the diff tab: slot `name`'s (s2) work so far, its worktree (committed or not) against where it
    branched off the shared branch: {'ok', 'name', 'text'} or {'ok': False, 'out': why}."""
    if not (name[:1] == 's' and name[1:].isdigit()):
        return {'ok': False, 'name': name, 'out': f'{name} is not a slot: only a slot has a diff'}
    d = Path(S.SLOTS_DIR) / name
    if not d.is_dir():
        return {'ok': False, 'name': name, 'out': f'{name} has no worktree yet'}
    try:
        base = S.default_branch()
    except SystemExit as e:
        return {'ok': False, 'name': name, 'out': str(e)}

    def git(*a: str) -> sp.CompletedProcess:
        return sp.run(['git', '-C', str(d), *a], capture_output=True, text=True, encoding='utf-8',
                      errors='replace', timeout=20)
    try:
        mb = git('merge-base', base, 'HEAD')
        if mb.returncode:
            return {'ok': False, 'name': name, 'out': f'git merge-base {base} HEAD: {mb.stderr.strip()}'}
        r = git('diff', mb.stdout.strip())
    except (OSError, sp.SubprocessError) as e:
        return {'ok': False, 'name': name, 'out': f'git diff: {e}'}
    if r.returncode:
        return {'ok': False, 'name': name, 'out': f'git diff: {r.stderr.strip()}'}
    text = r.stdout
    if len(text) > DIFF_BYTES:
        text = text[:DIFF_BYTES] + '\n… (the rest left out)'
    return {'ok': True, 'name': name, 'text': text}


def frame_look(name: str) -> str:
    """F170: the colours session `name`'s terminal gets: 'page' (it was started with the run's theme, so each browser
    fills them from its own light or dark), else 'dark' or 'light' as the person's agent theme is."""
    inbox = U.hidden_inbox(name)
    try:
        spec = json.loads(inbox.with_suffix('.job').read_text(encoding='utf-8')) if inbox else {}
    except (OSError, ValueError):
        spec = {}
    if spec.get('look') == session_theme.SETTING or any(session_theme.SETTING in str(a) for a in spec.get('argv') or []):
        return 'page'
    return session_frame.session_look()


class Terminals:
    """One ttyd per session, started the first time it is opened, on 127.0.0.1 and a free port of its own; F114: the
    run page serves it under /t/TOKEN/NAME/ on its own address (`Handler.session`), so https and Runner Home reach
    it, and the address is as secret as the page's. C26: it runs `attach NAME` for each browser, a client of the
    session's own socket (F88) like any other; the session has the smallest of its clients' sizes (`attach.Viewers`)."""

    def __init__(self, token: str, port: int, bind: str):
        self.token, self.port, self.bind = token, port, LOCAL
        self.procs: dict[str, tuple[sp.Popen, int, str]] = {}
        self.lock = threading.Lock()
        self.login = login_hold.LoginHold()  # F126b

    def cwd(self, name: str) -> str:
        return str(Path.home() if name == session_frame.LOGIN else S.ROOT)  # F126b: Home has no project

    def argv(self, name: str, sock: str, port: int) -> list[str]:
        from agent_runner.config import runner_cmd
        runs = session_frame.login_argv() if name == session_frame.LOGIN else [*runner_cmd(), 'attach', name]  # F126b
        return ['ttyd', '-W', '-p', str(port), '-i', LOCAL, '-b', f'/t/{self.token}/{name}',
                *(['-w', self.cwd(name)] if plat.WINDOWS else []),  # ttyd's Windows build starts nothing without it
                *session_frame.ttyd_options(session_frame.session_look()), *runs]

    def ended(self, name: str, port: int, err: str) -> str:
        # F165: a port nobody opens is never named; ttyd's own error has it
        return f'ttyd for {name} ended at once: ' + re.sub(rf'( to)?( port:?)? *\b{port}\b', '', err)

    def open(self, name: str) -> dict:
        """Where the page finds session `name`: {'ok', 'port' (the page's own), 'path'}, or why not."""
        if name == session_frame.LOGIN:  # F126b
            got = self.ttyd(name)
            return got if not got['ok'] else {'ok': True, 'port': self.port, 'path': f'/t/{self.token}/{name}/'}
        sock = socket_of(name)
        if U.terminal_mode() == 'install':  # an ended one says that it ended: ttyd would not bring it back
            return terminal_fallback(name) if sock or session_live(name) else no_session(name)
        from agent_runner.attach import reachable
        if not sock or name[0] == 's' and headless(name) or not reachable(Path(sock)):
            return no_session(name)
        got = self.ttyd(name, sock)
        return got if not got['ok'] else {'ok': True, 'port': self.port, 'path': f'/t/{self.token}/{name}/',
                                          'look': frame_look(name)}

    def ttyd(self, name: str, sock: str = '') -> dict:
        """The port session `name`'s ttyd listens on, started when it is not up: {'ok', 'port'} or {'ok', 'out'}."""
        sock = sock or (name if name == session_frame.LOGIN else socket_of(name))  # F126b: the login has no socket
        with self.lock:
            p = self.procs.get(name)
            if p and p[0].poll() is None and (p[2] == sock or not sock):
                return {'ok': True, 'port': p[1]}
            if not sock or U.terminal_mode() == 'install':
                return no_session(name) if not sock else terminal_fallback(name)
            if p and p[0].poll() is None:
                p[0].terminate()
            self.procs.pop(name, None)
            with socket.create_server((LOCAL, 0)) as s:
                port = s.getsockname()[1]
            err = tempfile.TemporaryFile()  # not a pipe: nobody reads it while ttyd runs
            kw = {'creationflags': plat.CREATE_NO_WINDOW} if plat.WINDOWS else {'start_new_session': True}
            try:
                proc = sp.Popen(self.argv(name, sock, port), cwd=self.cwd(name), stdin=sp.DEVNULL, stdout=sp.DEVNULL,
                                stderr=err, env={**os.environ, 'AGENT_RUNNER_WEB': '1'}, **kw)
            except OSError as e:
                err.close()
                return {'ok': False, 'mode': 'none', 'live': True, 'out': f'ttyd for {name} did not start: {e}'}
            end = time.monotonic() + 5
            while True:  # one that cannot start ends at once: say so, not a dead frame
                if proc.poll() is not None:
                    err.seek(0)
                    said = err.read().decode(errors='replace').strip()
                    err.close()
                    return {'ok': False, 'mode': 'none', 'live': True, 'out': self.ended(name, port, said[-300:])}
                try:
                    socket.create_connection((LOCAL, port), timeout=0.5).close()
                    break
                except OSError:
                    if time.monotonic() > end:
                        break
                    time.sleep(0.05)
            err.close()  # ttyd has its own copy
            self.procs[name] = (proc, port, sock)
            return {'ok': True, 'port': port}

    def close(self) -> None:
        self.login.close()
        for proc, _, _ in list(self.procs.values()):
            if proc.poll() is None:
                proc.terminate()


