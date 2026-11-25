"""C45: the run page's web.py, F138 option buttons that answer the run with no AI session.

Part of `web`: `web` runs this file in its own namespace (see its PARTS), so these names are `web`'s, and a test that sets
`web.X` reaches the code here. Not imported on its own."""

# --- F138: option buttons that answer the run with no AI session ------------------------------------------------
#
# A concept page's or a pick sheet's option button is a plain link to the run page's https address:
# <https base>/pick?id=<ID>&o=<option>&k=<code>; through Runner Home (F167) the base
# ends in /p/KEY. The code is a one-use secret made for that item and kept in
# <notes>/pick-codes/<ID>.json, never the run page's own token, so a leaked page can only pick an option for that
# item. /pick checks it, runs `plan confirm ID "go with <option>: <its name>"` (a pick sheet: `sheet ID --picks`),
# burns it, and shows a small page saying what happened (or why not: used, unknown, settled already).

PICK_OPTION = re.compile(r'[A-Za-z0-9]{1,8}')  # a concept's option: A, B, C
PICK_MAX = 600  # chars of a pick sheet's picks line
_PICK_LOCK = threading.Lock()


def pick_file(tid: str) -> Path:
    return S.C.notes('pick-codes', f'{tid}.json')


def _pick_state(tid: str) -> dict:
    try:
        d = json.loads(pick_file(tid).read_text(encoding='utf-8'))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def pick_code(tid: str) -> str:
    """Item `tid`'s pick code: the unused one kept for it, else a fresh one (owner-only file)."""
    if (d := _pick_state(tid)).get('code') and not d.get('used'):
        return d['code']
    code = secrets.token_urlsafe(18)
    f = pick_file(tid)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({'id': tid, 'code': code, 'made': time.strftime('%Y-%m-%d %H:%M')}) + '\n',
                 encoding='utf-8')
    try:
        os.chmod(f, 0o600)
    except OSError:
        pass
    return code


def run_port() -> int:
    """The run page's port: the one a run serves it on (<notes>/web.url), else `[run] web_port`; 0 when only
    Runner Home opens it (F165), or that port is Home's (F167: a run's own port from before Home)."""
    port = 0
    try:
        if us := url_file().read_text(encoding='utf-8').split():
            if not own_links(us):
                return 0
            port = urlsplit(us[0]).port or 0
    except (OSError, ValueError):
        pass
    port = port or int(S.C.run.get('web_port', 8770))
    return 0 if port == home_port() else port


def https_base(https=None) -> str:
    """The run page's https address with no token and no slash at its end, from Tailscale Serve: F167: Runner
    Home's for this project (`https://host[:port]/p/KEY`) when Home routes it, else the run's own
    (`https://host[:port]`); '' when there is none (the pages keep today's flow)."""
    https = https or tailscale_https_urls
    for u in site_urls(https=https):
        s = urlsplit(u)
        if s.scheme == 'https' and s.netloc:
            return f'https://{s.netloc}{s.path.rstrip("/")}'
    port = run_port()
    for u in https(port, 'x') if port else []:
        s = urlsplit(u)
        if s.scheme == 'https' and s.netloc:
            return f'https://{s.netloc}'
    return ''


def no_https_why() -> str:
    """Why `https_base` is '' (F165: without naming a port only Home opens)."""
    site = site_urls()
    if (site or run_port()) and page_https.not_connected():
        return 'Tailscale is not connected'
    if site:
        from agent_runner.home import serve_https_argv
        port = urlsplit(site[-1]).port
        return (f'Tailscale Serve proxies none to Runner Home\'s port {port}; '
                f'`{" ".join(serve_https_argv(port))}` gives Home one')
    if port := run_port():
        return f'Tailscale Serve proxies none to port {port}'
    return closed_line()


def pick_link(base: str, tid: str, code: str, option: str = '') -> str:
    """One option's link (no `o` when `option` is ''; a pick sheet adds its picks line to it)."""
    from urllib.parse import quote
    return f'{base}/pick?id={quote(tid)}&k={quote(code)}' + (f'&o={quote(option)}' if option else '')


def pick_base(tid: str, https=None) -> str:
    """F138: item `tid`'s link with no option, for a pick sheet's Send to add its picks to ('' with no https)."""
    return pick_link(base, tid, pick_code(tid)) if (base := https_base(https)) else ''


def pick_links(tid: str, options: list[str], https=None) -> list[str]:
    """F138: one link per option of item `tid` ([] with no https address)."""
    if not (base := https_base(https)):
        return []
    code = pick_code(tid)
    return [pick_link(base, tid, code, o) for o in options]


def _concept_of(tid: str) -> tuple[str, str]:
    """(concept id, build id) of a waiting concept that `tid` names (either one); ('', '') for none."""
    from agent_runner import plan as P
    try:
        for build, cid, _, _ in P.waiting(S.C.todo, all=True):
            if tid in (build, cid):
                return cid, build
    except (SystemExit, OSError):
        pass
    return '', ''


def pick(tid: str, option: str, code: str) -> tuple[int, str]:
    """F138: answer item `tid` with `option` when `code` is its unused pick code: (HTTP status, what to say)."""
    from agent_runner.brief import has_sheet
    with _PICK_LOCK:  # a double tap runs once
        d = _pick_state(tid) if re.fullmatch(r'[A-Za-z]+\d+[a-z0-9]*', tid or '') else {}
        if not d.get('code') or not code or not hmac.compare_digest(code.encode(), str(d['code']).encode()):
            return 403, 'This link is unknown: it was not made for this item. Use the buttons on its page.'
        if d.get('used'):
            return 409, f'This link was used already ({d.get("option", "")} on {d["used"]}): {tid} is answered.'
        if not U.need_label(tid):
            return 409, f'{tid} is settled already: nothing waits for an answer on it.'
        sheet = has_sheet(tid)
        if not option or (len(option) > PICK_MAX if sheet else not PICK_OPTION.fullmatch(option)):
            return 400, f'{option!r} is not an option of {tid}.'
        if sheet:
            argv = ['sheet', tid, '--go'] if option.lower() in ('go', 'recommended') else \
                ['sheet', tid, '--picks', option]
            said = f'Sent your picks for {tid}: the run starts it again.'
        else:
            cid, build = _concept_of(tid)
            opts = concept_options(U.concept_copy(cid or tid))
            i = ord(option.upper()) - ord('A') if len(option) == 1 and option.isalpha() else -1
            name = opts[i]['name'] if 0 <= i < len(opts) else ''
            name = re.sub(r'\s*\(recommended\)\s*$', '', re.sub(rf'^\s*{option}\s*[:.)-]\s*', '', name, flags=re.I),
                          flags=re.I).strip()  # 'B: drawer (recommended)' is named 'drawer'
            argv = ['plan', 'confirm', tid, f'go with {option}' + (f': {name}' if name else '')]
            said = (f'Approved {option}' + (f' ({name})' if name else '') + f': the run starts {build}.'
                    if build else f'Answered {tid} with {option}: the run starts it again.')
        r = U.call(argv)
        if not r['ok']:
            return 409, f'{tid} was not answered: {(r.get("out") or "").strip() or "the runner refused it"}'
        d.update(used=time.strftime('%Y-%m-%d %H:%M'), option=option if not sheet else 'picks')
        pick_file(tid).write_text(json.dumps(d) + '\n', encoding='utf-8')
        return 200, said


def pick_page(code: int, said: str) -> bytes:
    """The small page /pick answers with."""
    import html as H
    head = 'Done' if code == 200 else 'Not answered'
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{head}</title>
<style>:root{{--bg:#f4f6f9;--fg:#1a1e26;--muted:#5f6876}}
@media (prefers-color-scheme:dark){{:root{{--bg:#11141a;--fg:#e6e9ef;--muted:#9aa3b2;color-scheme:dark}}}}
body{{background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,sans-serif;margin:0;
padding:32px max(16px,env(safe-area-inset-left,0px))}}h1{{font-size:1.3rem;margin:0 0 8px}}p{{margin:0;max-width:36em}}
</style></head><body><h1>{head}</h1><p>{H.escape(said)}</p></body></html>""".encode('utf-8')


