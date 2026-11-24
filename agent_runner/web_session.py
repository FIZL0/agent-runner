"""C45: the run page's web.py, a session's socket, live state and resume.

Part of `web`: `web` runs this file in its own namespace (see its PARTS), so these names are `web`'s, and a test that sets
`web.X` reaches the code here. Not imported on its own."""

# --- the sessions' terminals ---------------------------------------------------------------------------------------

def socket_of(name: str) -> str:
    """C26: the attach socket of session `name` (s2, c6) as a path, '' when it has none (not up)."""
    try:
        from agent_runner.attach import session_socket
        sock = session_socket(name)
        return str(sock) if sock else ''
    except Exception:  # noqa: BLE001 - no notes dir
        return ''


def terminal_fallback(name: str) -> dict:
    """F74: a chat without ttyd: how to install it (`mode` 'install'); the message box works meanwhile. B761: `cmd` is
    this machine's command, once in `out` (the page shows it as code); with none found, `out` lists them all. F126b:
    the login names its command, to be run by hand."""
    cmd = ttyd_install_cmd()
    if provider_login.is_login(name):  # F406a: a name already checked
        from agent_runner.config import RUNNER
        provider, _, domain = name.removeprefix(provider_login.PREFIX).partition('~')
        return {'ok': False, 'mode': 'install', 'cmd': cmd, 'out':
                f'ttyd is not installed, so the login cannot be shown here. Install it on {socket.gethostname()} (' +
                (cmd or TTYD_INSTALL) + ') and open the login again, or run '
                f'{" ".join([RUNNER, *provider_login.words(provider, domain)])} in a terminal there.'}
    if name == session_frame.LOGIN:
        return {'ok': False, 'mode': 'install', 'out':
                f'ttyd is not installed, so the login cannot be shown here. Install it on {socket.gethostname()} (' +
                (cmd or TTYD_INSTALL) +
                f') and press Log in again, or run {watch.LOGIN_CMD} in a terminal there.'}
    how = f'on {socket.gethostname()} ' + (f'with {cmd}' if cmd else f'({TTYD_INSTALL})')
    return {'ok': False, 'mode': 'install', 'cmd': cmd, 'out':
            f'ttyd is not installed, so a chat cannot show the session: install it {how} and open the chat again. '
            f'Until then, messages still reach {name}.'}


def session_live(name: str) -> bool:
    """F114: does session `name` run (its marker names a live process)?"""
    from agent_runner.slots import marker_pid
    try:
        pid = marker_pid(S.C.notes(f'{"control" if name[0] == "c" else "slot"}{name[1:]}.live'))
        return bool(pid and plat.alive(pid))
    except Exception:  # noqa: BLE001 - no notes dir
        return False


def headless(name: str) -> bool:
    """F114: a slot of the stream engine: it has no terminal, only a stream of events."""
    try:
        return bool(json.loads(S.C.notes(f'slot{name[1:]}.job').read_text(encoding='utf-8')).get('stream'))
    except Exception:  # noqa: BLE001 - no job, not JSON
        return False


def resumable(name: str) -> str:
    """F114: the conversation an ended chat (cN) can be resumed with, as a session id; '' for none."""
    if not re.fullmatch(r'c\d+', name):
        return ''
    try:
        from agent_runner.control import control_kept_sid
        from agent_runner.slots import transcript
        sid = control_kept_sid(int(name[1:]))
        return sid if sid and transcript(sid) else ''
    except Exception:  # noqa: BLE001 - no notes dir
        return ''


def no_session(name: str) -> dict:
    """F114: why session `name` has no terminal to show (`mode` 'none'): `live` (it runs), its claude.ai/code `link`
    and whether it can be resumed."""
    if not re.fullmatch(r'[cs]\d+', name):
        return {'ok': False, 'mode': 'none', 'live': False, 'out': f'{name} is not a session.', 'link': '', 'resume': False}
    live, sid = session_live(name), resumable(name)
    if live and name[0] == 's' and headless(name):
        out = f'{name} runs headless ([run] engine = "stream"), so it has no terminal to show. Messages still reach it.'
    elif live and plat.WINDOWS and not plat.has_conpty():
        out = f'{name} runs in a hidden console: showing it here takes Windows 10 1809 or later.'
    elif live:
        out = f'{name} is up, but there is no terminal to attach to. If it just started, it comes in a moment.'
    else:
        out = f'{name} is not up, so there is no session to show.'
    link = U._bridge_link(sid or U.session_sid(name))
    return {'ok': False, 'mode': 'none', 'live': live, 'out': out, 'link': link, 'resume': bool(sid) and not live}


def resume_chat(chat: str) -> dict:
    """F114: Resume on an ended chat: its conversation comes up again under its number (`control N --reopen`)."""
    bad = {'ok': False, 'code': 2, 'argv': []}
    if not re.fullmatch(r'c\d+', str(chat)):
        return {**bad, 'out': f'resume_chat: a chat, not {chat!r}'}
    if session_live(chat):
        return {'ok': True, 'code': 0, 'out': f'{chat} is up already', 'argv': [], 'name': chat}
    if not (sid := resumable(chat)):
        return {**bad, 'out': f'{chat} has no conversation left to resume'}
    from agent_runner.control_reopen import reopen_control
    where = reopen_control(int(chat[1:]), sid)
    return {'ok': bool(where), 'code': 0 if where else 1, 'argv': [], 'name': chat,
            'out': f'{chat} is resuming' if where else f'{chat} could not be resumed (the run log says why)'}


U.ACTIONS['resume_chat'] = resume_chat


