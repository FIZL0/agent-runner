"""C45: the run page's web.py, the snapshot the page gets, its extras and the chat order.

Part of `web`: `web` runs this file in its own namespace (see its PARTS), so these names are `web`'s, and a test that sets
`web.X` reaches the code here. Not imported on its own."""

# --- the server -------------------------------------------------------------------------------------------------

class Snapshots:
    """The snapshot, made at most once per TICK however many pages watch it."""

    def __init__(self, make):
        self.make, self.lock, self.at, self.last = make, threading.Lock(), 0.0, ''

    def get(self) -> str:
        with self.lock:
            if time.monotonic() - self.at >= TICK or not self.last:
                try:
                    self.last = json.dumps(with_chat_order(self.make()), ensure_ascii=False)
                except Exception as e:  # noqa: BLE001 - a bad read shows on the page, it does not end the stream
                    self.last = json.dumps({'error': f'{type(e).__name__}: {e}'})
                self.at = time.monotonic()
            return self.last


def page_html(home: bool = False) -> bytes:
    """F79: the run app. Its light and dark looks follow the browser's setting (`[ui] theme` is the terminal
    UI's). F134: `home`
    is Runner Home's own page (HOME_PAGE): the All projects view and the project switcher, no run behind it."""
    page = PAGE_TEXT.replace('/*PAGE_PRINT*/', PAGE_PRINT, 1)
    if home:
        page = page.replace('/*HOME_PAGE*/false', 'true', 1).replace(
            '<title>agent-runner</title>', '<title>Runner Home</title>', 1)
    else:  # B153: the project's name as the window title ('ifizbox · runner'), before the script runs
        try:
            name = S.project()
        except Exception:  # noqa: BLE001 - no project initialised: the default title
            name = ''
        if name:
            page = page.replace('<title>agent-runner</title>', f'<title>{html.escape(name)} · runner</title>', 1)
    return page.encode('utf-8')


concept_options = U.concept_options  # C33: one option list, in ui_model


TTYD_PACKAGES = (('pacman', 'sudo pacman -S ttyd'), ('apt', 'sudo apt install ttyd'), ('dnf', 'sudo dnf install ttyd'),
                 ('zypper', 'sudo zypper install ttyd'), ('brew', 'brew install ttyd'),
                 ('winget', 'winget install tsl0922.ttyd'), ('scoop', 'scoop install ttyd'))


def ttyd_install_cmd(which=shutil.which) -> str:
    """B120: the command that installs ttyd here, from the first package manager found ('' when none is)."""
    return next((cmd for tool, cmd in TTYD_PACKAGES if which(tool)), '')


def with_extras(snap: dict) -> dict:
    """F79: what the run app shows beyond the snapshot: this machine's name, and each concept's options."""
    snap['machine'], snap['boot'] = socket.gethostname(), BOOT
    snap['page'], snap['restart_needed'] = PAGE_PRINT, watch.RESTART_NEEDED[0]  # F149
    snap['session_look'] = session_frame.session_look()  # F114: the ground of a session's colours
    if snap.get('terminal_mode') == 'install':
        snap['ttyd_install'] = ttyd_install_cmd()  # B120: the page's one line on how to get it
    for c in snap.get('concepts') or []:
        c['options'] = concept_options(c.get('copy', ''))
    snap['example'] = example_project()  # F194b: its page shows the walkthrough
    snap['home'] = home_address()  # B153: the project name top-left links to Runner Home
    return snap


def example_project() -> bool:
    """F194b: is the run's project the example one (demo.py)? Only its page shows the walkthrough."""
    try:
        from agent_runner.demo import is_demo
        return S.ROOT is not None and is_demo(S.ROOT)
    except Exception:  # noqa: BLE001 - a run's page never fails over the walkthrough
        return False


def home_address() -> dict:
    """B153: Runner Home's port and token, for the run page's link to it on the host the page came from
    ({} while Home is not installed or has no token yet; the token file is only read, never made)."""
    try:
        port = home_port()
        if not port:
            return {}
        from agent_runner.home import config_dir
        token = (config_dir() / 'home.token').read_text(encoding='utf-8').strip()
        return {'port': port, 't': token} if token else {}
    except Exception:  # noqa: BLE001 - a run's page never fails over Home
        return {}


CHAT_ORDER_FILE = 'chat_order.json'  # F133: the sidebar's pinned chats, in their order, in the notes dir


def pin_list(names: list[str], saved: dict | None) -> list[str]:
    """F133, F201: the pinned chats of `names`, in their saved order. A file from before F201 also keeps an `order`
    of every chat: there the pins stand in that order. A chat that is gone (not in `names`) drops out."""
    saved = saved if isinstance(saved, dict) else {}
    order, pins = ([n for n in saved.get(k) or [] if isinstance(n, str)] for k in ('order', 'pins'))
    place = {n: i for i, n in enumerate(order)}
    return sorted(dict.fromkeys(n for n in pins if n in names), key=lambda n: place.get(n, len(order)))


def chat_order_path() -> Path | None:
    try:
        return S.C.notes(CHAT_ORDER_FILE)
    except Exception:  # noqa: BLE001 - no project, so no notes dir
        return None


def load_chat_order() -> dict:
    p = chat_order_path()
    try:
        d = json.loads(p.read_text(encoding='utf-8')) if p else {}
    except (OSError, ValueError):
        d = {}
    return d if isinstance(d, dict) else {}


def save_chat_order(order=None, pins=None) -> dict:
    """F133: the `chat_order` action: keep the sidebar's pinned chats, in their order (`pins`, cN names), for every
    page. F201: the rest sort by last activity, so `order` (a page from before) only orders the pins."""
    def names(v):
        return list(dict.fromkeys(n for n in v if isinstance(n, str) and re.fullmatch(r'c\d+', n))) \
            if isinstance(v, list) else None
    if (order is None and pins is None) or (order is not None and names(order) is None):
        return {'ok': False, 'code': 2, 'out': 'chat_order: order and pins are lists of chat names', 'argv': []}
    saved = load_chat_order()
    old = [n for n in saved.get('pins') or [] if isinstance(n, str)]
    pins = names(pins) if pins is not None else pin_list(old, saved)
    if pins is None:
        return {'ok': False, 'code': 2, 'out': 'chat_order: order and pins are lists of chat names', 'argv': []}
    if order is not None:
        pins = pin_list(pins, {'order': names(order), 'pins': pins})
    p = chat_order_path()
    if not p:
        return {'ok': False, 'code': 2, 'out': 'chat_order: no project here to keep it in', 'argv': []}
    tmp = p.with_name(p.name + '.tmp')  # written whole, then moved in: a snapshot never reads half a file
    tmp.write_text(json.dumps({'pins': pins}), encoding='utf-8')
    os.replace(tmp, p)
    return {'ok': True, 'code': 0, 'out': 'chat order kept', 'argv': []}


def with_chat_order(snap):
    """F133: the snapshot with the pinned chats in their order (`chat_pins`)."""
    if not isinstance(snap, dict) or 'error' in snap:
        return snap
    names = [s.get('name') for s in snap.get('sessions') or [] if isinstance(s, dict)
             and re.fullmatch(r'c\d+', str(s.get('name')))]
    snap['chat_pins'] = pin_list(names, load_chat_order())
    return snap


def run_snapshot() -> dict:
    return with_extras(U.snapshot(terminal_base='.'))


