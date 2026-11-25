"""F68: the claude.ai copy of the run page (the run page copy).

With `[run] remote_slots = 'open'` a slot is in the Claude apps only once opened. For when this machine (and so the
run page it serves) is not reachable, the run keeps a copy of the run page on claude.ai: it writes the page from
F65's snapshot to <notes>/run-page-copy.html and, on a run event (a task starts, lands or blocks, a needs-you
item, a concept, the release), publishes it to the same URL each time (<notes>/run-page-copy.url). The copy
shows the run as the page does, read-only, with the terminal and the chat as session links: a slot's
claude.ai/code link (once opened) and each chat's.

B122: the publish is a one-shot headless `claude -p` with only Artifact and Read (`page_copy_argv`), never a
control session: typing the ask into a chat cost a turn (~8k tokens) there on every run event. At most one
publish every PAGE_COPY_EVERY s, and only when the page changed apart from its clock (`page_copy_key`). When
the one-shot cannot publish, the copy stops for the run (`PAGE_COPY_OFF`): it never falls back to a chat.

F406e: with `[models] feed` on another provider the one-shot runs on the harness loop, which has no Artifact tool, so
there is no claude.ai page: the local copy is the answer, and that is no failure.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import subprocess as sp
import threading
import time
from pathlib import Path

from agent_runner import plat
from agent_runner.control import control_env
from agent_runner.feed import feed_model, feed_on_harness, harness_once  # F101: [models] feed; the one-shot only publishes a file it is handed
from agent_runner.sched import agent_held
from agent_runner.slots import one_session, remote_on
from agent_runner.state import C, log, ROOT

PAGE_COPY_EVERY = 600  # s between two publishes, however many run events come in between
PAGE_COPY_AT = [0.0]
PAGE_COPY_TIMEOUT = 300  # s a one-shot publish gets before it counts as failed
PAGE_COPY_FAIL_MAX = 3  # failed publishes in a row before the copy stops for the run
PAGE_COPY_FAILS = [0]
PAGE_COPY_OFF = ['']  # why the copy stopped for this run, '' while it is kept
PAGE_COPY_BUSY = threading.Lock()  # held while a one-shot publishes: one at a time
ARTIFACT_URL = re.compile(r'https://claude\.ai/(?:code/)?artifact/[A-Za-z0-9_-]+')


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
    """What makes a run event for the copy: the page as it would be published, apart from what moves with the
    clock: its 'as of' time, the log lines, a slot's minutes and the numbers in the status lines (usage). Those
    change every minute, so with them in the key a busy run would publish every PAGE_COPY_EVERY s; a quiet run
    publishes nothing. The status lines' words stay in it: a run that pauses or stops is a change."""
    calm = {**snap, 'at': '', 'log': [], 'status': [re.sub(r'\d+', '#', str(l)) for l in snap.get('status') or []],
            'sessions': [{**s, 'minutes': None} for s in snap.get('sessions') or []]}
    return hashlib.sha256(page_copy_html(calm).encode('utf-8')).hexdigest()


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


def need_opts(n: dict) -> str:
    """B203: a DECIDE's options after its ask (F181c takes their bracket off it), as its answer buttons say them."""
    if n.get('label') != 'DECIDE' or not n.get('options'):
        return ''
    return f'<span>{_h(" / ".join(a["label"] for a in n.get("answers") or []))}</span>'


def page_copy_html(snap: dict) -> str:
    """The run page copy, from F65's snapshot `snap`: the run page's five panels and its log, read-only, with
    the terminal and the chat as session links (no token, no address of this machine)."""
    rows = []
    for s in snap.get('sessions') or []:
        if re.fullmatch(r'c\d+', str(s.get('name') or '')):  # F73: a control session, not a slot
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
    rels = [f'<div class="row"><span class="m">{_h(r.get("id") or "V")}</span><span>{_h(r.get("title"))}</span>'
            f'<span class="d">{_h(r.get("words"))}</span></div>' for r in snap.get('releases') or []]  # F185
    queue = [f'<div class="row"><span class="id">{_h(q.get("id"))}</span><span>{_h(q.get("title"))}</span>'
             + (f'<span class="d">after {_h(", ".join(q["after"]) if isinstance(q.get("after"), list) else q["after"])}'
                f'</span>' if q.get('after') else '')
             + (f'<span class="r">{_h(q.get("pri"))}</span>' if q.get('pri') not in (None, '', 'normal') else '')
             + '</div>' for q in snap.get('queue') or [] if not q.get('release')]
    needs = [f'<div class="row"><span class="y">{_h(n.get("id"))}</span><span>{_h(n.get("ask") or n.get("title"))}'
             f'</span>{need_opts(n)}<span class="d">{_h(n.get("age"))}</span>{_a(n.get("url") or "", "page")}</div>'
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
            f'<span>as of {_h(snap.get("at"))}</span>'
            '<span>read-only: the live page is served by the run on its machine</span></div>'
            '<div class="grid">' + box(1, 'Status', status, 'no run is up') + box(2, 'Sessions', rows, 'none')
            + box(3, 'Queue', rels + queue, 'nothing queued') + box(4, 'Needs you', needs, 'Nothing needs you.')
            + box(5, 'Concepts', concepts, 'none') + box(6, 'Log', [log_], '') + '</div>\n')


def page_copy_ask(path: Path, url: str, icon: str = 'dashboard', caps: dict | None = None) -> str:
    """The one-shot publisher's prompt: publish `path`, to `url` when there is one, and answer with the URL alone
    (it cannot write files, so the run writes the URL file from that answer). F411: `caps`, the capabilities the page
    declares (a pick sheet's db)."""
    where = (f'to the existing artifact {url}: read it first with action "read" (a publish to it is refused until '
             'then), then publish the file to that url; the file replaces the page whole' if url else
             f'as a new artifact with icon "{icon}"')
    where += f'. Pass capabilities {json.dumps(caps)} exactly' if caps else ''
    return (f'Publish the HTML file {path} with the Artifact tool {where}. Do nothing else, and answer with the '
            "artifact's claude.ai URL alone.")


def page_copy_argv(path: Path, url: str, icon: str = 'dashboard', **caps) -> list[str]:
    """B122: the one-shot headless session that publishes the copy: `claude -p`, Haiku, the Artifact tool and
    Read only (B180: `--tools` denies Read when it is left out, and Artifact then refuses to publish a file;
    dontAsk refuses the rest and any read outside its folder), no settings sources or MCP servers, a few turns.
    Never a control session."""
    return [plat.exe(C.run['agent']), '-p', page_copy_ask(path, url, icon, **caps), '--model', feed_model(),
            '--tools', 'Artifact,Read', '--allowedTools', 'Artifact', '--permission-mode', 'dontAsk',
            '--strict-mcp-config', '--setting-sources', '', '--settings', json.dumps({'autoMemoryEnabled': False}),
            '--max-turns', '6']


def page_copy_said(r) -> str:
    """What a failed one-shot said, on one line: the end of its errors, then of its answer. Both, as a warning on
    stderr (a sign-in that ends soon) is not why it failed; the answer is (B180)."""
    ends = (' '.join((t or '').split())[-300:] for t in (r.stderr, r.stdout))
    return ' | '.join(e for e in ends if e)


def page_copy_publish(path: Path, url: str, icon: str = 'dashboard', **caps) -> str:
    """Run the one-shot (`page_copy_argv`; `harness_once` for another provider's feed model) and return the URL it
    published to, '' when it did not (`caps`: see `page_copy_ask`). Raises OSError when the agent cannot be started at all. B764c: FileNotFoundError
    while [run] agent is wrong and the feed model is Claude's."""
    if feed_on_harness():  # F406e: no claude.ai page from there, whatever it says: the local copy stands
        said, why = harness_once(feed_model(), page_copy_ask(path, url, icon) + ' With no Artifact tool, publish it '
                                 'nowhere: answer "local copy".', path.parent, PAGE_COPY_TIMEOUT)
        log(f'run page copy: no claude.ai page without Claude Code; the local copy is {path}' + (f' ({why})' if why else ''))
        return ''
    if bad := agent_held():  # B764c: as no agent here (F406e): the local copy is the answer
        raise FileNotFoundError(bad)
    r = sp.run(page_copy_argv(path, url, icon, **caps), cwd=str(path.parent), env=control_env(), stdin=sp.DEVNULL,
               capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=PAGE_COPY_TIMEOUT)
    got = ARTIFACT_URL.findall(r.stdout or '')
    if r.returncode != 0 or not got:
        log(f'run page copy: the one-shot publish failed (exit {r.returncode}): {page_copy_said(r)}')
        return ''
    return url if url in got else got[-1]


def page_copy_stop(why: str) -> None:
    PAGE_COPY_OFF[0] = why
    log(f'run page copy: stopped for this run: {why}')


def page_copy_job(f: Path, url: str, keyf: Path, publish) -> None:
    """One publish, its URL written on success; a failure forgets the key, so the first tick past PAGE_COPY_EVERY
    from this try publishes again, changed or not, and PAGE_COPY_FAIL_MAX failures in a row stop the copy (a
    one-off failure, say a network blip, does not)."""
    try:
        try:
            got = publish(f, url)
        except (OSError, sp.SubprocessError) as e:  # no agent to start, or it hung: as good as a failed publish
            if isinstance(e, FileNotFoundError):
                PAGE_COPY_FAILS[0] = 0  # F406e: no Claude Code here: the local copy is the answer
                log(f'run page copy: the agent {C.run["agent"]} is not here, so no claude.ai page; the local copy is {f}')
                return
            log(f'run page copy: {e}')
            got = ''
        if got:
            PAGE_COPY_FAILS[0] = 0
            if got != url:
                page_copy_url_file().write_text(got + '\n', encoding='utf-8')
            return
        if feed_on_harness():  # F406e: the local copy is the answer
            PAGE_COPY_FAILS[0] = 0
            return
        PAGE_COPY_FAILS[0] += 1
        keyf.unlink(missing_ok=True)
        if PAGE_COPY_FAILS[0] >= PAGE_COPY_FAIL_MAX:
            page_copy_stop(f'{PAGE_COPY_FAILS[0]} one-shot publishes failed in a row')
    except Exception as e:  # noqa: BLE001 - a nicety: never the run's
        log(f'run page copy: {e}')
    finally:
        PAGE_COPY_BUSY.release()


def page_copy_tick(now: float | None = None, snap: dict | None = None, publish=None,
                   background: bool = True) -> bool:
    """From the run loop: under `[run] remote_slots = 'open'` with Remote Control on (the copy is for the apps), write
    the copy and publish it (`publish`, default the one-shot `page_copy_publish`, in a thread of its own unless
    `background` is off) when the page changed since the last publish (`page_copy_key`), at most every
    PAGE_COPY_EVERY s and one at a time. B122: nothing is ever typed into a control session. True when a
    publish was started. Never raises."""
    now = time.time() if now is None else now
    try:
        if (PAGE_COPY_OFF[0] or not (one_session() and remote_on())
                or now - PAGE_COPY_AT[0] < PAGE_COPY_EVERY or (agent_held() and not feed_on_harness())):  # B764c
            return False
        if snap is None:
            from agent_runner import ui_model
            snap = ui_model.snapshot(log_n=20)
        keyf = C.notes('run-page-copy.key')
        key = page_copy_key(snap)
        try:
            if keyf.read_text(encoding='utf-8') == key:
                return False  # no run event since the last publish
        except OSError:
            pass
        if not PAGE_COPY_BUSY.acquire(blocking=False):
            return False  # the last publish is still running: the next tick looks again
        try:
            f = page_copy_file()
            f.write_text(page_copy_html(snap), encoding='utf-8')
            keyf.write_text(key, encoding='utf-8')
            PAGE_COPY_AT[0] = now
            args = (f, page_copy_url(), keyf, publish or page_copy_publish)
        except BaseException:
            PAGE_COPY_BUSY.release()
            raise
        if background:
            threading.Thread(target=page_copy_job, args=args, name='run-page-copy', daemon=True).start()
        else:
            page_copy_job(*args)
        return True
    except Exception as e:  # noqa: BLE001 - the copy is a nicety: a bad snapshot or write costs it, not the run
        log(f'run page copy: {e}')
        PAGE_COPY_AT[0] = now
        return False


# --- F106f: publish_page on every engine ---------------------------------------------------------------------

def concept_url_file(tid: str, c=None) -> Path:
    """Where `run publish-page` records the claude.ai URL of task `tid`'s page: beside its local copy. `c` is a
    config (default the run's)."""
    return (c or C).notes('concepts', f'{tid}.url')


def concept_url(tid: str, c=None) -> str:
    """What `run publish-page` recorded for task `tid`'s page: its claude.ai URL, or where the run page shows it
    (`local_page`, F406e: published without Claude Code); '' for none."""
    try:
        u = concept_url_file(tid, c).read_text(encoding='utf-8').strip()
    except OSError:
        return ''
    return u if ARTIFACT_URL.fullmatch(u) or u == local_page(tid) else ''


def local_page(tid: str) -> str:
    """F406e: the answer for a page with no claude.ai page: where the run page shows its local copy."""
    return f'/concept/{tid}'


def publish_page(tid: str, src: Path, publish=None) -> tuple[Path, str]:
    """F106f: copy the page `src` to <notes>/concepts/<tid>.html (the run page shows it at /concept/<tid>), then
    publish that copy to claude.ai with the one-shot (`publish`, default `page_copy_publish`): to the URL recorded
    for `tid` when there is one, so a second publish updates the same page. The URL is recorded (`concept_url`),
    and `done` takes it as a concept's --artifact. (the copy, the URL or '' when the one-shot did not publish). F406e: with no Claude Code to
    publish it (none here, or a feed model of another provider) the answer is its `local_page`."""
    dest = C.notes('concepts', f'{tid}.html')
    dest.write_bytes(src.read_bytes())
    old = u if (u := concept_url(tid)) != local_page(tid) else ''
    local = feed_on_harness()
    try:
        got = (publish or (lambda f, u: page_copy_publish(f, u, icon='options')))(dest, old)
    except (OSError, sp.SubprocessError) as e:
        log(f'publish-page {tid}: {e}')
        local = local or isinstance(e, FileNotFoundError)  # no agent on this machine
        got = ''
    if not got and local:
        got = local_page(tid)
    if got:
        concept_url_file(tid).write_text(got + '\n', encoding='utf-8')
    return dest, got


def cmd_publish_page(argv: list[str]) -> int:
    """`run publish-page FILE`: show the person a page, on any engine (Claude Code sessions, the harness loop)."""
    import argparse
    import sys
    from agent_runner.state import init
    from agent_runner.tools import task_here
    ap = argparse.ArgumentParser(prog='run publish-page', description="Show the person a page (a concept's options, "
                                 'a report): the run page shows it at /concept/<ID>, and a one-shot publishes it to '
                                 'claude.ai; its URL is printed and recorded for `done`.')
    ap.add_argument('file', help='the HTML file')
    ap.add_argument('--id', help='the task it belongs to (default: this worktree\'s task/<ID> branch)')
    a = ap.parse_args(argv)
    src = Path(a.file)
    if not src.is_file():
        print(f'run publish-page: {a.file} is not a file', file=sys.stderr)
        return 2
    tid = a.id or task_here()
    if not re.fullmatch(r'[A-Za-z]+\d+[a-z0-9]*', tid or ''):
        print('run publish-page: no task: this worktree is not on a task/<ID> branch (give --id ID)', file=sys.stderr)
        return 2
    global C
    C = init()  # this module is not one `state.share` sets
    from agent_runner import plan as P
    dest, url = publish_page(tid, src.resolve())
    print(f'the run page shows it at /concept/{tid} (copy: {dest})')
    if not url and tid.startswith('chat1'):  # F406f: a chat's page: no task to finish with it
        print('run publish-page: the one-shot could not publish it to claude.ai (the run log says why): the copy on the '
              'run page is the page.', file=sys.stderr)
        return 1
    if not url:
        print(f'run publish-page: the one-shot could not publish it to claude.ai (the run log says why). Run this '
              f'again, or finish with `done {tid} "<msg>" --blocked "<why>"`.', file=sys.stderr)
        return 1
    print('no claude.ai page without Claude Code: the copy on the run page is the page' if url == local_page(tid)
          else f'published: {url}')
    if P.concept(tid):
        print(f'Recorded for {tid}: `done {tid} "<msg>"` takes it as --artifact, and Needs you links it.')
    return 0
