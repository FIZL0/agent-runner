"""F68: the claude.ai copy of the run page (the run page copy), kept by c1.

With `[run] sessions = 'one'` the Claude apps list one entry per project, c1. For when this machine (and so the
run page it serves) is not reachable, c1 keeps a copy of the run page on claude.ai: the run writes the page from
F65's snapshot to <notes>/run-page-copy.html and, on a run event (a task starts, lands or blocks, a needs-you
item, a concept, the release), asks c1 to publish it with its Artifact tool, to the same URL each time
(<notes>/run-page-copy.url, which c1 writes after its first publish). The copy shows the run as the page does,
read-only, with the terminal and the chat as session links: a slot's claude.ai/code link (once opened) and c1's.
"""
from __future__ import annotations

import html
import json
import re
import time
from pathlib import Path

from agent_runner import plat
from agent_runner.control import control_live, control_ok, control_window
from agent_runner.slots import one_session, remote_on, send_fifo, send_to_pane
from agent_runner.state import C, log, ROOT

PAGE_COPY_EVERY = 300  # s between two asks to republish, however many run events come in between: each ask is
                       # a turn in c1, the person's chat, so a busy run does not fill it
PAGE_COPY_AT = [0.0]


def page_copy_file() -> Path:
    return C.notes('run-page-copy.html')


def page_copy_url_file() -> Path:
    return C.notes('run-page-copy.url')


def page_copy_url() -> str:
    try:
        u = page_copy_url_file().read_text(encoding='utf-8').strip()
    except OSError:
        return ''
    return u if re.fullmatch(r'https://claude\.ai/\S+', u) else ''


def page_copy_key(snap: dict) -> str:
    """What makes a run event for the copy: who runs what, the queue, needs-you items, concepts and the release.
    Minutes, usage and the log tail leave it as it is, so a quiet run asks c1 nothing."""
    return json.dumps({'up': snap.get('up'),
                       'sessions': [(s.get('name'), s.get('task'), s.get('state'), s.get('link'))
                                    for s in snap.get('sessions') or []],
                       'queue': [(q.get('id'), q.get('after'), q.get('pri')) for q in snap.get('queue') or []],
                       'needs': [n.get('id') for n in snap.get('needs') or []],
                       'concepts': [c.get('id') for c in snap.get('concepts') or []],
                       'release': snap.get('release')}, sort_keys=True, default=str)


def _h(s) -> str:
    return html.escape(str(s if s is not None else ''), quote=True)


def _a(url: str, text: str) -> str:
    return f'<a href="{_h(url)}" target="_blank" rel="noopener">{_h(text)}</a>' if url.startswith('https://') else ''


PAGE_COPY_STYLE = '''<style>
:root{--bg:#000;--fg:#e5e5e5;--dim:#737373;--line:#3a3a3a;--red:#ef4444;--green:#22c55e;--yellow:#f59e0b;
--blue:#60a5fa;--cyan:#06b6d4;--magenta:#a855f7;color-scheme:dark}
body{background:var(--bg);color:var(--fg);font:13px/1.45 "JetBrains Mono",ui-monospace,Menlo,monospace;
padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px));
padding-block:12px}
.top{display:flex;flex-wrap:wrap;gap:12px;color:var(--dim);margin-bottom:14px}.top b{color:var(--red)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,420px),1fr));gap:18px}
.box{position:relative;border:1px solid var(--line);padding:14px 10px 8px;min-width:0}
.box>.ttl{position:absolute;top:-9px;left:8px;background:var(--bg);padding:0 4px;color:var(--red);font-weight:700}
.row{display:flex;gap:8px;flex-wrap:wrap;padding:1px 0}.row>*{min-width:0}
.id{font-weight:700;color:var(--cyan)}.d{color:var(--dim)}.y{color:var(--yellow)}.g{color:var(--green)}
.m{color:var(--magenta)}.r{color:var(--red)}
a{color:var(--blue)}pre{margin:0;white-space:pre-wrap;overflow-wrap:anywhere;color:var(--dim)}
</style>'''


def page_copy_html(snap: dict) -> str:
    """The run page copy, from F65's snapshot `snap`: the run page's five panels and its log, read-only, with
    the terminal and the chat as session links (no token, no address of this machine)."""
    c1 = next((s for s in snap.get('sessions') or [] if s.get('name') == 'c1'), {})
    chat = c1.get('link', '')
    rows = []
    for s in snap.get('sessions') or []:
        if s.get('name') == 'c1':
            rows.append(f'<div class="row"><span class="r">c1</span><span>the project\'s chat</span>'
                        f'{_a(chat, "chat") or "<span class=d>" + _h(s.get("state")) + "</span>"}</div>')
            continue
        if re.fullmatch(r'c\d+', str(s.get('name') or '')):  # F73: another control session, not a slot
            rows.append(f'<div class="row"><span class="r">{_h(s.get("name"))}</span><span>{_h(s.get("title"))}'
                        f'</span>{_a(s.get("link", ""), "session") or "<span class=d>" + _h(s.get("state")) + "</span>"}'
                        '</div>')
            continue
        if s.get('state') == 'idle':
            rows.append(f'<div class="row"><span class="d">{_h(s.get("name"))}</span>'
                        f'<span class="d">{_h(s.get("name"))} is idle: nothing running</span></div>')
            continue
        mins = f'{s["minutes"]}m ' if s.get('minutes') is not None else ''
        term = _a(s.get('link', ''), 'terminal') or '<span class="d">open it from the run page to watch here</span>'
        rows.append(f'<div class="row"><span class="y">{_h(s.get("name"))}</span><span class="id">{_h(s.get("task"))}'
                    f'</span><span>{_h(s.get("title"))}</span><span class="d">{mins}{_h(s.get("state"))}</span>'
                    f'{term}</div>')
    queue = [f'<div class="row"><span class="id">{_h(q.get("id"))}</span><span>{_h(q.get("title"))}</span>'
             + (f'<span class="d">after {_h(", ".join(q["after"]) if isinstance(q.get("after"), list) else q["after"])}'
                f'</span>' if q.get('after') else '')
             + (f'<span class="r">{_h(q.get("pri"))}</span>' if q.get('pri') not in (None, '', 'normal') else '')
             + '</div>' for q in snap.get('queue') or []]
    needs = [f'<div class="row"><span class="y">{_h(n.get("id"))}</span><span>{_h(n.get("ask") or n.get("title"))}'
             f'</span><span class="d">{_h(n.get("age"))}</span>{_a(n.get("url") or "", "page")}</div>'
             for n in snap.get('needs') or []]
    concepts = [f'<div class="row"><span class="m">{_h(c.get("id"))}</span><span>{_h(c.get("title"))}</span>'
                f'{_a(c.get("url") or "", "options")}</div>' for c in snap.get('concepts') or []]

    def box(n: int, name: str, body: list[str], empty: str) -> str:
        return (f'<section class="box"><span class="ttl">[{n}] {name}</span>'
                + (''.join(body) or f'<div class="d">{empty}</div>') + '</section>')

    status = [f'<div class="row">{_h(l)}</div>' for l in snap.get('status') or []]
    log_ = '<pre>' + _h('\n'.join(snap.get('log') or [])) + '</pre>'
    project = _h(snap.get('project') or ROOT.name)
    return (f'<title>{project} run</title>\n'
            '<meta name="claude:viewport-fit-sides" content="cover">\n' + PAGE_COPY_STYLE
            + f'<div class="top"><span><b>{project}</b> · run page copy</span>'
            f'<span>as of {_h(snap.get("at"))}</span>{_a(chat, "chat with c1")}'
            '<span>read-only: the live page is served by the run on its machine</span></div>'
            '<div class="grid">' + box(1, 'Status', status, 'no run is up') + box(2, 'Sessions', rows, 'none')
            + box(3, 'Queue', queue, 'nothing queued') + box(4, 'Needs you', needs, 'Nothing needs you.')
            + box(5, 'Concepts', concepts, 'none') + box(6, 'Log', [log_], '') + '</div>\n')


def page_copy_ask(path: Path, url: str) -> str:
    """What the run types to c1 to republish the copy: one line, the runner's and not the person's."""
    where = (f'to {url} (pass it as url)' if url else
             f'(the same file path as before if you published it already, else a new artifact with icon '
             f'"dashboard"), then write its URL alone to {page_copy_url_file()}')
    return (f'agent-runner: the run changed. Publish the run page copy {path} with the Artifact tool {where}. '
            'This is the runner, not the person: say nothing about it here.')


def c1_send(text: str) -> bool:
    """Type `text` into c1 when it is live (its tmux pane, or a hidden c1's FIFO); False when it is not."""
    if not (pid := control_live(1)):
        return False
    if pane := control_window(1, pid):
        return send_to_pane(pane, text)
    return not plat.WINDOWS and send_fifo(C.notes('control1.in'), text)


def page_copy_tick(now: float | None = None, snap: dict | None = None, send=None) -> bool:
    """From the run loop: under `[run] sessions = 'one'`, with c1 live and on Remote Control (where its Artifact
    tool publishes), write the copy and ask c1 to republish it when the run changed since the last ask
    (`page_copy_key`), at most every PAGE_COPY_EVERY s. True when c1 was asked. Never raises."""
    now = time.time() if now is None else now
    try:
        if not (one_session() and control_ok() and remote_on()) or now - PAGE_COPY_AT[0] < PAGE_COPY_EVERY:
            return False
        if snap is None:
            from agent_runner import ui_model
            snap = ui_model.snapshot(log_n=20)
        keyf = C.notes('run-page-copy.key')
        key = page_copy_key(snap)
        try:
            if keyf.read_text(encoding='utf-8') == key:
                return False  # no run event since the last ask (with no URL yet too: asked again only on one)
        except OSError:
            pass
        f = page_copy_file()
        f.write_text(page_copy_html(snap), encoding='utf-8')
        if not (send or c1_send)(page_copy_ask(f, page_copy_url())):
            return False  # c1 is not up: the next tick asks again
        PAGE_COPY_AT[0] = now
        keyf.write_text(key, encoding='utf-8')
        return True
    except Exception as e:  # noqa: BLE001 - the copy is a nicety: a bad snapshot or write costs it, not the run
        log(f'run page copy: {e}')
        PAGE_COPY_AT[0] = now
        return False
