"""F96: the run page's own https address on the tailnet. While a run serves its page for every interface, Tailscale
Serve proxies https on the next port (8771) to it (`[run] web_https`), since browsers give the mic and other
secure-context features only to https or localhost. The rule the run made is kept in Home's config folder
(serve/<port>.json), so a run turns off such a one only: at its stop, or after a crash at the start of the next run
that has its port or is its project's. A rule no run made is left alone."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess as sp
from pathlib import Path

from agent_runner import state as S

ASK = 5  # s a `tailscale` question may take
MAKE = 15  # s `tailscale serve` may take: where Serve is not enabled it waits for a person to open a link


def rules_dir() -> Path:
    from agent_runner.home import config_dir
    return config_dir() / 'serve'


def rule_file(port: int) -> Path:
    return rules_dir() / f'{port}.json'


def owner() -> str:
    return str(S.C.notes('web.url').parent)


def read_rule(f: Path) -> dict | None:
    try:
        d = json.loads(f.read_text(encoding='utf-8'))
        return {'host': str(d['host']), 'https': int(d['https']), 'port': int(d['port']), 'run': str(d['run'])}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def keep_rule(rule: dict) -> None:
    f = rule_file(rule['port'])
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(rule) + '\n', encoding='utf-8')


def drop_rule(rule: dict) -> None:
    try:
        rule_file(rule['port']).unlink(missing_ok=True)
    except OSError:
        pass  # the stop goes on; the next start finds that the rule itself is gone


def tailscale(*args: str, limit: float = ASK) -> tuple[bool, str]:
    """`tailscale ARGS`: (did it work, its output, else its error)."""
    try:
        r = sp.run(['tailscale', *args], capture_output=True, text=True, encoding='utf-8', errors='replace',
                   stdin=sp.DEVNULL, timeout=limit)
    except sp.TimeoutExpired as e:
        got = (e.stdout or b'') + (e.stderr or b'')  # bytes, whatever `text` says
        said = got.decode('utf-8', 'replace') if isinstance(got, bytes) else got
        return False, ' '.join(said.split())[:300] or f'no answer in {limit:g} s'
    except (OSError, ValueError) as e:
        return False, str(e)
    return r.returncode == 0, (r.stdout if r.returncode == 0 else
                               ' '.join((r.stderr or r.stdout).split())[:300] or f'exit {r.returncode}')


def as_json(text: str) -> dict:
    try:
        got = json.loads(text or '{}')
    except ValueError:
        return {}
    return got if isinstance(got, dict) else {}


def backend(run=sp.run) -> str:
    """B815a: Tailscale's state: 'Running' while it is connected; '' when it does not say."""
    try:
        r = run(['tailscale', 'status', '--json'], capture_output=True, text=True, encoding='utf-8', errors='replace',
                stdin=sp.DEVNULL, timeout=ASK)
    except (OSError, ValueError, sp.SubprocessError):
        return ''
    return str(as_json(r.stdout).get('BackendState') or '') if r.returncode == 0 else ''


def not_connected() -> bool:
    """B815a: is Tailscale here but not connected (stopped, logged out, not answering)?"""
    if os.environ.get('AGENT_RUNNER_NO_SERVE') or not shutil.which('tailscale'):
        return False
    return backend() != 'Running'


def used(status: dict, https: int) -> bool:
    """Does `tailscale serve status --json` have any rule on port `https` (one in the foreground too)?"""
    return any(str(https) in (one.get('TCP') or {}) or
               any(h.rpartition(':')[2] == str(https) for h in one.get('Web') or {})
               for one in (status, *(status.get('Foreground') or {}).values()))


def is_ours(status: dict, rule: dict) -> bool:
    """Is the recorded `rule` still there as the run made it: its address, with only / and proxied to its port?"""
    handlers = ((status.get('Web') or {}).get(f'{rule["host"]}:{rule["https"]}') or {}).get('Handlers')
    return handlers == {'/': {'Proxy': f'http://127.0.0.1:{rule["port"]}'}}


def made_rule() -> dict | None:
    """The rule a run of this project made and has not turned off yet."""
    me = owner()
    return next((r for f in sorted(rules_dir().glob('*.json')) if (r := read_rule(f)) and r['run'] == me), None)


def https_off(say=True) -> None:
    """Turn off the rule this project's run made, if it is still the one it made. One that could not be turned off
    stays recorded, for the next start."""
    if not (rule := made_rule()):
        return
    ok, out = tailscale('serve', 'status', '--json')
    if ok and is_ours(as_json(out), rule):
        ok, out = tailscale('serve', f'--https={rule["https"]}', 'off')
    if ok:
        drop_rule(rule)
    elif say:
        S.log(f'run page: could not turn off Tailscale Serve on port {rule["https"]}: {out}')


def left_over() -> None:
    """A start whose page is not on a port for every interface, or wants no https: turn off what a run that did not
    stop left. Runner Home on that port by now has the address as its own, so it stays."""
    if not (rule := made_rule()):
        return
    from agent_runner.web import home_port
    if home_port() == rule['port']:
        drop_rule(rule)
    else:
        https_off()


def https_on(port: int) -> bool:
    """Give the page on `port` an https address on the next port. True when a rule of the run's own is there for the
    stop to turn off. One line in the run log says why it is http only (nothing, where a rule the run did not
    make proxies to it already)."""
    if os.environ.get('AGENT_RUNNER_NO_SERVE'):  # the test suites: never this machine's own Tailscale
        return False
    why = _https_on(port)
    if why:
        S.log(f'run page: http only, {why}')
    return made_rule() is not None


def _https_on(port: int) -> str:
    """https_on's work: '' when the page has an https address, else why not."""
    if not shutil.which('tailscale'):
        return 'no tailscale here for an https address'
    ok, out = tailscale('status', '--json')
    st = as_json(out) if ok else {}
    host = str((st.get('Self') or {}).get('DNSName') or '').rstrip('.')
    if st.get('BackendState') != 'Running' or not host:
        return 'Tailscale is not connected' + (f' ({out})' if not ok else '')
    ok, out = tailscale('serve', 'status', '--json')
    if not ok:
        return f'tailscale serve status failed: {out}'
    serves = as_json(out)
    https = port + 1
    rule = {'host': host, 'https': https, 'port': port, 'run': owner()}
    old = made_rule()
    if old == rule and is_ours(serves, rule):
        return ''  # this run restarted, or the last one did not stop
    if old:
        https_off(say=False)
        if made_rule():
            return 'an earlier Tailscale Serve rule of this run is still there'
    if (left := read_rule(rule_file(port))) and {**left, 'run': rule['run']} == rule and is_ours(serves, left):
        keep_rule(rule)  # another project's run that did not stop: the port is this run's now, and so is the rule
        return ''
    from agent_runner.web import serve_https_urls
    if serve_https_urls(serves, port, 'x'):
        return ''  # the person's own rule
    if https > 65535:
        return f'port {port} has no next port for https'
    if used(serves, https):
        return f'Tailscale Serve uses port {https} for something else'
    with socket.socket() as s:  # Serve would take the tailnet's connections from a server on that port
        s.settimeout(1)
        if s.connect_ex(('127.0.0.1', https)) == 0:
            return f'port {https} is taken'
    if not st.get('CertDomains'):
        return 'HTTPS certificates are not enabled on the tailnet (Tailscale admin console, DNS)'
    # recorded first: a run that dies in between still leaves a rule that can be told as its own
    keep_rule(rule)
    ok, out = tailscale('serve', '--bg', f'--https={https}', f'http://127.0.0.1:{port}', limit=MAKE)
    if not ok:
        https_off(say=False)  # should it have come up all the same
        return f'tailscale serve refused: {out}'
    return ''
