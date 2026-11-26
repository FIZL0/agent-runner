"""F98: approve to push (`[run] approve`). Tasks merge and pass the gate here as ever, but nothing reaches the push
remote until a person approves it.

Each task that lands is a change in <notes>/pitches.json (`landed`). Changes that touch the same component wait in
one pitch (`groups`); a group opens as a pitch once it has been quiet for `[run] approve_wait` minutes or holds
`[run] approve_batch` tasks (`open_due`). A pitch is a page for the person (`page_html`), an item under Needs you
(`rows`) and an event `since` shows. Approve pushes the shared branch up to the pitch's last
merge, in merge order (`approve`, `target`); Not this marks changes to be undone (`refuse`), which the run does
under the merge lock (`undo.undo_changes`).

A change's `state`: waiting -> approved -> pushed, or waiting -> undoing -> undone.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import html
import json
import os
import re
import subprocess as sp
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from agent_runner import plan as P, plat
from agent_runner import state as S
from agent_runner.gitops import drop_if_merged, missing_remote, push_sha

PITCH_ID = re.compile(r'pitch\d+')
LABEL = 'PITCH'
EV_PITCH = 'pitch'      # a pitch opened (text: what it asks), or one of its changes could not be undone
LOCK_WAIT = 600         # s: an approval may hold the lock for a push
PUSH_RETRY = 300        # s between two tries of an approved push the remote refused
# directories that hold everybody's files: sharing one says nothing about what a change is about
COMMON_DIRS = {'', '.', 'test', 'tests', 'doc', 'docs'}
PARTS = ('what', 'why', 'try', 'risk')  # what a task's agent writes of its change (`part_file`); all needed
IMAGES = {'.png': 'png', '.jpg': 'jpeg', '.jpeg': 'jpeg', '.gif': 'gif', '.webp': 'webp'}
IMAGE_MAX = 2_000_000


def on(c=None) -> bool:
    """Is approve to push in force: the setting, a push remote that is there, and `[git] push_merge`."""
    c = c or S.C
    try:
        return bool(c is not None and c.approve and c.push_merge and not missing_remote(c.root))
    except (AttributeError, SystemExit, OSError):
        return False


def store_file(c=None) -> Path:
    return (c or S.C).notes('pitches.json')


def read(c=None) -> dict:
    """{'next': the next pitch's number, 'changes': [...], 'pitches': [...]}, changes in merge order."""
    try:
        d = json.loads(store_file(c).read_text(encoding='utf-8'))
    except FileNotFoundError:
        d = {}
    return {'next': 1, 'changes': [], 'pitches': [], **d}


@contextmanager
def edit(c=None):
    """The store, locked against the run's threads and the commands, written back when the block ends."""
    f = store_file(c)
    end = time.monotonic() + LOCK_WAIT
    while not (lk := plat.lock(f.with_suffix('.lock'))):
        if time.monotonic() > end:
            raise TimeoutError(f'{f} is locked by another process')
        time.sleep(0.05)
    try:
        d = read(c)
        was = json.dumps(d)
        yield d
        if json.dumps(d) == was:
            return
        tmp = f.with_suffix('.tmp')
        tmp.write_text(json.dumps(d, indent=1), encoding='utf-8')
        os.replace(tmp, f)
    finally:
        lk.close()


def part_file(tid: str, c=None) -> Path:
    """Where `tid`'s agent writes its part of the pitch, as JSON (`PARTS`, and maybe 'before' and 'after')."""
    return (c or S.C).notes('pitches', f'{tid}.json')


def part(tid: str, c=None) -> dict:
    try:
        d = json.loads(part_file(tid, c).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def part_problem(tid: str, c=None) -> str:
    """Why `tid`'s part of the pitch is not ready; '' when it is."""
    d = part(tid, c)
    gone = [k for k in PARTS if not str(d.get(k) or '').strip()]
    return f'{part_file(tid, c)} needs {", ".join(gone)}' if gone else ''


# --- what landed ---------------------------------------------------------------------------------------------

def _anc(a: str, b: str) -> bool:
    return bool(a and b) and S.git('merge-base', '--is-ancestor', a, b).returncode == 0


def _plan_prefix() -> str:
    return '' if S.C.plan_external else S.plan_rel('').rstrip('/') + '/'


def _span(tid: str, base: str, merged: str, alone: bool) -> tuple[str, str]:
    """(before, after): two commits whose difference is task `tid`'s change. The first merge of base..merged that
    brought task/<tid> in, against its first parent; a branch that went in as a fast-forward, against `base`."""
    tip = S.git('rev-parse', '-q', '--verify', f'task/{tid}').stdout.strip()
    if tip and _anc(tip, merged):
        for m in S.git('rev-list', '--merges', '--reverse', '--topo-order', f'{base}..{merged}').stdout.split():
            if _anc(tip, m) and not _anc(tip, f'{m}^1'):
                return S.git('rev-parse', f'{m}^1').stdout.strip(), m
        return S.git('merge-base', base, tip).stdout.strip(), tip
    return (base, merged) if alone else ('', '')


def _line_of(tid: str, base: str) -> str:
    """`tid`'s task line as it read before its merge."""
    if S.C.plan_external:
        ls = P.lines(S.C.todo) + P.lines(S.C.done)
    else:
        ls = S.git('show', f'{base}:{S.plan_rel("TODO.md")}').stdout.splitlines()
    return next((ls[i] for _, _, t, _, i in P.iter_tasks(ls) if t == tid), '')


def landing(tids: list[str], base: str, merged: str) -> None:
    """The tasks of one tested merge about to land, each a change that will wait for approval. Recorded before it
    lands, so a run that dies in between leaves no merge untracked (`settle`). Their task branches are still there."""
    if not on():
        return
    plan, new = _plan_prefix(), []
    for tid in tids:
        before, after = _span(tid, base, merged, len(tids) == 1)
        files = S.git('diff', '--name-only', '--no-renames', before, after).stdout.split('\n') if before else []
        line = _line_of(tid, base)
        new.append({'key': f'{tid}@{merged[:12]}', 'id': tid, 'at': time.time(), 'base': base, 'merged': merged,
                    'title': P.title_of(line) if line else tid, 'before': before, 'after': after,
                    'files': [f for f in files if f and not (plan and f.startswith(plan))],
                    'waits': P.fields(line).get('after', []) if line else [], 'say': part(tid),
                    'subject': S.git('log', '-1', '--format=%s', after).stdout.strip() if after else '',
                    'state': 'landing', 'pitch': '', 'how': '', 'why': '', 'undo': '', 'err': ''})
    with edit() as d:
        have = {x['key'] for x in d['changes']}
        d['changes'] += [x for x in new if x['key'] not in have]


def landed(merged: str, ok: bool) -> None:
    """The merge `landing` recorded landed (`ok`), or did not."""
    if not on():
        return
    with edit() as d:
        mine = [x for x in d['changes'] if x['state'] == 'landing' and x['merged'] == merged]
        for x in mine:
            x.update(state='waiting', at=time.time())
        if not ok:
            d['changes'] = [x for x in d['changes'] if x not in mine]
    for x in mine if ok else []:
        part_file(x['id']).unlink(missing_ok=True)
        S.log(f'{x["id"]}: merged, waits for your approval before it is pushed ([run] approve)')


def unpushed(d: dict | None = None) -> list[dict]:
    """The changes that landed here and are not pushed, less the ones undone."""
    return [x for x in (d or read())['changes'] if x['state'] in ('waiting', 'approved', 'undoing')]


def waiting_line() -> str:
    """'3 changes wait to be pushed (1 pitch for you to approve)' for status and the run page; '' for none."""
    if not on():
        return ''
    d = read()
    if not (n := len(unpushed(d))):
        return ''
    k = len(open_pitches(d))
    return (f'{n} change{"s" * (n != 1)} wait{"s" * (n == 1)} to be pushed'
            + (f' ({k} pitch{"es" * (k != 1)} for you to approve)' if k else ''))


# --- grouping ------------------------------------------------------------------------------------------------

def _related(a: dict, b: dict, shared: set[str]) -> bool:
    """Do two changes touch the same component: one follows the other, or they share a file, a module (its tests
    count as it) or a directory that is not everybody's."""
    if a['id'] == b['id'] or a['id'] in b['waits'] or b['id'] in a['waits']:
        return True
    fa, fb = ({f for f in x['files'] if f not in shared} for x in (a, b))
    tests = lambda fs: {m[1] or m[2] for f in fs if (m := re.fullmatch(r'test_(.+)|(.+)_test', Path(f).stem))}
    code = lambda fs: {Path(f).stem for f in fs}
    where = lambda fs: {d for f in fs if (d := str(Path(f).parent).replace('\\', '/')).split('/')[0] not in COMMON_DIRS}
    return bool(fa & fb or tests(fa) & code(fb) or code(fa) & tests(fb) or where(fa) & where(fb))


def groups(changes: list[dict], shared=()) -> list[list[dict]]:
    """`changes` in their components, each in merge order."""
    out: list[list[dict]] = []
    for x in changes:
        mine = [g for g in out if any(_related(x, y, set(shared)) for y in g)]
        out = [g for g in out if g not in mine] + [[y for g in mine for y in g] + [x]]
    at = {id(x): i for i, x in enumerate(changes)}
    return [sorted(g, key=lambda x: at[id(x)]) for g in out]


def open_due(now: float | None = None) -> list[dict]:
    """Open a pitch for each group that has been quiet for `approve_wait` minutes or holds `approve_batch` tasks."""
    now = time.time() if now is None else now
    opened = []
    with edit() as d:
        loose = [x for x in d['changes'] if x['state'] == 'waiting' and not x['pitch']]
        for g in groups(loose, S.C.run['shared_files']):
            full = len({x['id'] for x in g}) >= max(1, S.C.run['approve_batch'])
            if not full and now - max(x['at'] for x in g) < S.C.run['approve_wait'] * 60:
                continue
            p = {'id': f'pitch{d["next"]}', 'at': now, 'url': '', 'said': False}
            d['next'] += 1
            d['pitches'].append(p)
            for x in g:
                x['pitch'] = p['id']
            opened.append(p)
    return opened


def open_pitches(d: dict | None = None) -> list[dict]:
    """The pitches with a change still waiting for the person's answer."""
    d = d or read()
    live = {x['pitch'] for x in d['changes'] if x['state'] == 'waiting' and x['pitch']}
    return [p for p in d['pitches'] if p['id'] in live]


def changes_of(pid: str, d: dict | None = None, state: str = '') -> list[dict]:
    return [x for x in (d or read())['changes'] if x['pitch'] == pid and (not state or x['state'] == state)]


def ask_of(pid: str, d: dict) -> str:
    xs = changes_of(pid, d, 'waiting')
    said = f'Approve {len(xs)} change{"s" * (len(xs) != 1)} to push: ' + '; '.join(x['title'][:80] for x in xs)
    held = [p for p in dict.fromkeys(x['pitch'] for x in d['changes'] if x['state'] == 'approved')
            if any(b['pitch'] == pid for b in target(d, p)[1])]
    if held:
        said += f' ({", ".join(held)} is approved and waits for this one)'
    return said + ''.join(f'. {x["id"]} could not be undone: {x["err"]}' for x in xs if x['err'])


def rows(c=None) -> list[tuple]:
    """The open pitches as Needs you items, in `plan.asks`'s shape with the stamp eighth."""
    if not on(c):
        return []
    try:
        d = read(c)
        return [(LABEL, p['id'], '', ask_of(p['id'], d), p['url'],
                 '; '.join(x['title'] for x in changes_of(p['id'], d, 'waiting')), False,
                 dt.datetime.fromtimestamp(p['at']).strftime('%Y-%m-%d %H:%M')) for p in open_pitches(d)]
    except (OSError, ValueError, KeyError):
        return []


# --- the page ------------------------------------------------------------------------------------------------

def _rich(s) -> str:
    return re.sub(r'`([^`]+)`', r'<code>\1</code>', html.escape(str(s or '').strip())).replace('\n', '<br>')


def _shown(v, word: str) -> str:
    """A 'before' or 'after': a picture when it is an image file in the notes dir, else its words."""
    v = str(v or '').strip()
    if not v:
        return ''
    body = f'<p>{_rich(v)}</p>'
    if (kind := IMAGES.get(Path(v).suffix.lower())) and '\n' not in v:
        try:
            f = (S.C.notes('pitches', 'x').parent / v).resolve()
            if f.is_relative_to(Path(S.C.notes()).resolve()) and f.stat().st_size <= IMAGE_MAX:
                data = base64.b64encode(f.read_bytes()).decode()
                body = f'<img alt="{word}" src="data:image/{kind};base64,{data}">'
        except OSError:
            pass
    return f'<figure><figcaption>{word}</figcaption>{body}</figure>'


STYLE = """<style>
:root{--bg:#f4f6f9;--fg:#1a1e26;--muted:#5f6876;--line:#dce1e8;--card:#fff}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#11141a;--fg:#e6e9ef;--muted:#9aa3b2;
--line:#2a303a;--card:#191d25;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#11141a;--fg:#e6e9ef;--muted:#9aa3b2;--line:#2a303a;--card:#191d25;color-scheme:dark}
body{background:var(--bg);color:var(--fg);font-family:system-ui,-apple-system,sans-serif;font-size:15px;line-height:1.5}
.wrap{max-width:680px;margin:0 auto;padding-block:20px 60px;padding-left:max(16px,env(safe-area-inset-left,0px));
padding-right:max(16px,env(safe-area-inset-right,0px));display:grid;gap:18px}
h1{font-size:1.35rem;margin:0}h2{font-size:1.1rem;margin:0}p{margin:0}.m{color:var(--muted)}
article{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;display:grid;gap:10px;min-width:0}
h3{font-size:.75rem;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);margin:0 0 2px;font-weight:600}
code{font-family:ui-monospace,monospace;font-size:.85em;overflow-wrap:anywhere}
.pair{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,240px),1fr));gap:10px}
figure{margin:0;min-width:0}figcaption{color:var(--muted);font-size:.8rem}img{max-width:100%;border:1px solid var(--line);border-radius:8px}
ul{margin:0;padding-left:1.2em}
</style>"""


def also_going(pid: str, d: dict) -> list[str]:
    """The unpushed commits approving `pid` pushes that are no task's change and not the plan's alone (a commit made
    by hand, a repair, what was unpushed before `approve` was on), so the person approves those knowingly."""
    ref, to = _remote_ref(), target(d, pid)[0]
    if not (ref and to):
        return []
    plan, known = _plan_prefix(), set()
    for x in d['changes']:
        if x['before']:
            known |= set(S.git('rev-list', f'{x["before"]}..{x["after"]}').stdout.split())
        known.add(x['undo'])
    out = S.git('log', '--no-merges', '--format=%H %s', f'{ref}..{to}', '--', '.',
                *([f':(exclude){plan}'] if plan else [])).stdout.splitlines()
    return [l[41:] for l in out if l[:40] not in known]


def page_html(pid: str, d: dict, project: str = '') -> str:
    """A pitch's page: per change what it changes, why, how to try it and what it might break, as its agent wrote
    it; the files at the bottom. F444: it is the Review page too: each change's diff and the questions asked."""
    from agent_runner import review as R  # review imports brief, which imports this
    cards, files = [], []
    xs = changes_of(pid, d)
    for x in xs:
        say = x.get('say') or {}
        what = say.get('what') or x.get('subject') or x['title']
        body = ''.join(f'<section><h3>{h}</h3><p>{_rich(v)}</p></section>' for h, v in (
            ('What changes for you', what), ('Why you would want it', say.get('why')),
            ('Try it now', say.get('try')), ('What it might break', say.get('risk'))) if v)
        pair = _shown(say.get('before'), 'Before') + _shown(say.get('after'), 'After')
        cards.append(f'<article><h2>{_rich(x["title"])}</h2><p class="m">{html.escape(x["id"])}</p>{body}'
                     + (f'<div class="pair">{pair}</div>' if pair else '')
                     + R.diff_html(x) + R.asked_html(x['key'])  # F444: the Review page
                     + (R.answers_html(pid, x['id']) if x['state'] == 'waiting' else '') + '</article>')
        files.append(f'<p>{html.escape(x["id"])}</p><ul>'
                     + ''.join(f'<li><code>{html.escape(f)}</code></li>' for f in x['files']) + '</ul>')
    if also := also_going(pid, d):
        files.append('<h3>Also goes out with them</h3><ul>' + ''.join(f'<li>{html.escape(l)}</li>' for l in also)
                     + '</ul>')
    n = len(xs)
    return (f'<title>{html.escape(project)} {pid}</title>\n<meta name="claude:viewport-fit-sides" content="cover">\n'
            f'{STYLE}{R.REVIEW_STYLE}<div class="wrap"><div><h1>{n} change{"s" * (n != 1)} ready to push</h1>'
            f'<p class="m">They are merged and tested here, and not pushed. Approve them, or say Not this to all or '
            f'one of them, under Needs you. Read each one\'s diff, ask about it, or ask for a better way.</p></div>' + ''.join(cards)
            + '<article><h3>Files changed</h3>' + ''.join(files) + '</article></div>\n')


def _job(pid: str, publish) -> None:
    """Write pitch `pid`'s page, publish it, and say the pitch is open. A page that does not publish is still on the
    run page (/concept/<pitch>)."""
    try:
        d = read()
        f = S.C.notes('concepts', f'{pid}.html')
        f.write_text(page_html(pid, d, S.project()), encoding='utf-8')
        try:
            url = publish(f, '')
        except (OSError, sp.SubprocessError) as e:
            S.log(f'{pid}: its page was not published: {e}')
            url = ''
        with edit() as d:
            p = next(p for p in d['pitches'] if p['id'] == pid)
            p.update(url=url, said=True)
            ask = ask_of(pid, d)
        S.log(f'{ask} [{pid}]' + (f' {url}' if url else ''), EV_PITCH, pitch=pid)
    except Exception as e:  # noqa: BLE001 - it is shown again on the next tick, never the run's end
        S.log(f'{pid}: {e}')
    finally:
        BUSY.discard(pid)


BUSY: set[str] = set()  # pitches whose page is being published
PUSHED_AT = [0.0]


def _publish(f: Path, url: str) -> str:
    from agent_runner.page_copy import page_copy_publish
    return page_copy_publish(f, url, icon='inbox')


def tick(now: float | None = None, publish=None, background: bool = True) -> None:
    """From the run loop: settle what is on the remote already, open the pitches due, publish and say the new ones,
    and try an approved push again. Never raises."""
    if not on():
        return
    now = time.time() if now is None else now
    try:
        if not read()['changes']:
            return
        if now - PUSHED_AT[0] >= PUSH_RETRY:
            PUSHED_AT[0] = now
            settle()
            if any(x['state'] == 'approved' for x in read()['changes']):
                push_approved()
        open_due(now)
        for p in open_pitches():
            if p['said'] or p['id'] in BUSY:
                continue
            BUSY.add(p['id'])
            args = (p['id'], publish or _publish)
            if background:
                threading.Thread(target=_job, args=args, name=p['id'], daemon=True).start()
            else:
                _job(*args)
    except Exception as e:  # noqa: BLE001 - the next tick looks again
        S.log(f'pitches: {e}')


# --- answers -------------------------------------------------------------------------------------------------

def target(d: dict, pid: str) -> tuple[str, list[dict]]:
    """(the commit pitch `pid`'s approval pushes the shared branch to, the undecided changes that would go with
    it). The commit is its last merge; or a later one when that is what holds the undo of a change inside it, so a
    change the person said Not this to never goes out without its undo."""
    xs = changes_of(pid, d, 'approved') or changes_of(pid, d, 'waiting')
    if not xs:
        return '', []
    to = xs[0]['merged']
    for x in xs[1:]:
        if _anc(to, x['merged']):
            to = x['merged']
    to = _with_undos(d, to)
    if (ref := _remote_ref()) and not _anc(ref, to):  # the remote moved: the first landing that holds its commits
        to = next((t for x in d['changes'] for t in (x['merged'], x['undo']) if t and _anc(to, t) and _anc(ref, t)), to)
        to = _with_undos(d, to)
    return to, [x for x in d['changes'] if x['state'] in ('waiting', 'undoing') and x['pitch'] != pid
                and _anc(x['merged'], to)] + [x for x in changes_of(pid, d)
                                              if x['state'] in ('waiting', 'undoing') and _anc(x['merged'], to)]


def _with_undos(d: dict, to: str) -> str:
    moved = True
    while moved:
        moved = False
        for x in d['changes']:
            if x['state'] == 'undone' and _anc(x['merged'], to) and not _anc(x['undo'], to):
                to, moved = x['undo'], True
    return to


def _remote_ref() -> str:
    ref = f'refs/remotes/{S.C.push_remote}/{S.default_branch()}'
    return '' if S.git('rev-parse', '-q', '--verify', ref).returncode else ref


def settle() -> None:
    """A merge that landed as the run died waits like any other; what the remote has already (pushed by hand, or before `approve` was on) waits
    for nothing."""
    ref, branch = _remote_ref(), S.default_branch()
    with edit() as d:
        for x in d['changes']:
            if x['state'] == 'landing' and _anc(x['merged'], branch):  # the run died before `landed`
                x['state'] = 'waiting'
            if ref and x['state'] in ('waiting', 'approved') and _anc(x['merged'], ref):
                x['state'] = 'pushed'


def _blockers(left: list[dict], pid: str) -> str:
    names = list(dict.fromkeys(x['pitch'] or f'{x["id"]} (its pitch is not open yet)' if x['pitch'] != pid else
                               f'{x["id"]} ({"being undone" if x["state"] == "undoing" else "not answered"})'
                               for x in left))
    return ', '.join(names)


def push_approved() -> list[str]:
    """Push as far as the approvals allow, in merge order; one line per push or failure."""
    out, branch = [], S.default_branch()
    with edit() as d:
        pids = list(dict.fromkeys(x['pitch'] for x in d['changes'] if x['state'] == 'approved'))
        for pid in pids:
            to, left = target(d, pid)
            if not to or left or not changes_of(pid, d, 'approved'):
                continue
            if why := push_sha(S.ROOT, to, branch):
                out.append(f'! {pid} did not push: {why}')
                continue
            went = [x for x in d['changes'] if x['state'] == 'approved' and _anc(x['merged'], to)]
            for x in went:
                x['state'] = 'pushed'
            out.append(f'pushed {branch} up to {to[:10]} -> {S.C.push_remote}: '
                       + ', '.join(dict.fromkeys(x['id'] for x in went)))
            for x in went:
                if not S.git('rev-parse', '-q', '--verify',
                             f'refs/remotes/{S.C.push_remote}/task/{x["id"]}').returncode:
                    drop_if_merged(S.ROOT, f'task/{x["id"]}')
    for l in out:
        S.log(l)
    return out


def approve(pid: str) -> tuple[int, str]:
    """The person's yes to pitch `pid`: pushed up to its last merge, or held until the earlier ones are approved."""
    settle()
    with edit() as d:
        xs = changes_of(pid, d, 'waiting')
        if not xs:
            return 1, f'{pid}: nothing in it waits for an answer'
        for x in xs:
            x.update(state='approved', err='')
    said = push_approved()
    d = read()
    if not changes_of(pid, d, 'approved'):
        return 0, f'{pid} approved. ' + '; '.join(said)
    to, left = target(d, pid)
    if left:
        return 0, (f'{pid} is approved, and not pushed yet: it goes out in merge order, and {_blockers(left, pid)} '
                   f'landed before it or with it. Approve that too, and both are pushed.')
    return 1, f'{pid} is approved, and not pushed: {"; ".join(said)}. The run tries again.'


def refuse(pid: str, picks: dict[str, str], why: str = '') -> tuple[int, str]:
    """The person's Not this to some of pitch `pid`'s changes: {task id: 'reopen' or 'drop'}; the run undoes them."""
    with edit() as d:
        live = [x for x in changes_of(pid, d) if x['state'] in ('waiting', 'approved')]
        if not live:
            return 1, f'{pid}: nothing in it can be undone (pushed already, or undone)'
        if bad := sorted(set(picks) - {x['id'] for x in live}):
            return 1, f'{pid} has no change {", ".join(bad)} to undo'
        for x in live:
            if x['id'] in picks:
                x.update(state='undoing', how=picks[x['id']], why=why, err='')
    return 0, (f'{pid}: not this: ' + ', '.join(f'{t} ({h})' for t, h in picks.items())
               + '. The run undoes it here, through the gate.')


def undoing() -> list[dict]:
    """The changes to undo, newest first."""
    return [x for x in read()['changes'] if x['state'] == 'undoing'][::-1] if on() else []


def undone(keys: list[str], sha: str) -> None:
    """The run landed the undo of these changes as `sha`; an approval that waited for it may push now."""
    with edit() as d:
        for x in d['changes']:
            if x['key'] in keys:
                x.update(state='undone', undo=sha)
    push_approved()


def not_undone(keys: list[str], why: str) -> None:
    """They could not be undone: back under Needs you, with why."""
    ask = {}
    with edit() as d:
        for x in d['changes']:
            if x['key'] in keys:
                x.update(state='waiting', err=why[:300])
                ask[x['pitch']] = ''
        for pid in ask:
            ask[pid] = ask_of(pid, d)
    for pid, said in ask.items():
        S.log(f'{said} [{pid}]', EV_PITCH, pitch=pid)


def review_answer(pid: str, ids: list[str]) -> int:
    """F444 `pitch ask PITCH ID "question"`: a one-shot answers it from the change's diff and why; the answer is kept
    and shown on the Review page, which is written again here (its run page copy)."""
    if len(ids) < 2:
        print('agent-runner pitch: ask needs the change and your question: pitch ask pitch1 F1 "why this way?"',
              file=sys.stderr)
        return 2
    tid, q = ids[0], ' '.join(ids[1:]).strip()
    d = read()
    x = next((x for x in changes_of(pid, d)[::-1] if x['id'] == tid), None)
    if not x:
        print(f'agent-runner pitch: {pid} has no change {tid}', file=sys.stderr)
        return 1
    from agent_runner import review as R
    said, why = R.ask_change(x, q, S.ROOT)
    if why:
        print(f'agent-runner pitch: no answer: {why}', file=sys.stderr)
        return 1
    try:
        S.C.notes('concepts', f'{pid}.html').write_text(page_html(pid, read(), S.project()), encoding='utf-8')
    except OSError:
        pass
    print(said)
    return 0


def cmd_pitch(argv: list[str]) -> int:
    """`agent-runner pitch [approve|no PITCH]`: the pitches that wait, and the person's answer to one."""
    ap = argparse.ArgumentParser(prog='agent-runner pitch', description='[run] approve: the landed changes that wait '
                                 'for your approval before they are pushed.')
    ap.add_argument('what', nargs='?', choices=('list', 'approve', 'no', 'ask', 'better'), default='list')
    ap.add_argument('pitch', nargs='?', help='the pitch (pitch1)')
    ap.add_argument('ids', nargs='*', metavar='ID', help='no: only these changes of it (default: all), reopened; '
                    'ask: the change, then your question; better: the change')
    ap.add_argument('--reopen', default='', metavar='ID,ID', help='no: undo these and put their tasks back')
    ap.add_argument('--drop', default='', metavar='ID,ID', help='no: undo these and drop their tasks (all: every one)')
    ap.add_argument('--why', default='', help='no: what is wrong with it, noted on the tasks')
    a = ap.parse_args(argv)
    S.init()
    if not on():
        print('[run] approve is off (or there is nowhere to push): merges are pushed as they land' if not S.C.approve
              else 'nothing to approve: [git] push_merge is off, or the push remote is not there', file=sys.stderr)
        return 1
    if a.what == 'list':
        d = read()
        print(waiting_line() or 'nothing waits to be pushed')
        for p in open_pitches(d):
            print(f'{p["id"]}  {p["url"]}'.rstrip())
            for x in changes_of(p['id'], d, 'waiting'):
                print(f'  {x["id"]}  {x["title"][:100]}')
        return 0
    if not PITCH_ID.fullmatch(a.pitch or ''):
        ap.error(f'{a.what} needs a pitch, as `pitch` lists them (pitch1)')
    if a.what == 'approve':
        rc, said = approve(a.pitch)
    elif a.what == 'ask':
        return review_answer(a.pitch, a.ids)
    else:
        if a.what == 'better':  # F444: undone and reopened, with what the person wants instead
            if len(a.ids) != 1 or not a.why.strip():
                ap.error('better needs one change and --why "what you want instead"')
            a.why = f'asked for a better way: {a.why.strip()}'
        split = lambda s: [x for x in re.split(r'[,\s]+', s) if x]
        every = [x['id'] for x in changes_of(a.pitch) if x['state'] in ('waiting', 'approved')]
        drop = every if a.drop == 'all' else split(a.drop)
        back = [*a.ids, *split(a.reopen)]
        picks = {t: 'reopen' for t in back or ([] if drop else every)} | {t: 'drop' for t in drop}
        rc, said = refuse(a.pitch, picks, a.why)
        if not rc and (lk := plat.lock(S.C.notes('run.lock'))):  # no run is up: this process does it now
            from agent_runner import runner  # noqa: F401 - loads the modules `init` sets up
            from agent_runner.undo import undo_changes
            S.init()
            undo_changes(S.default_branch())
            lk.close()
            said += ''.join(f'\n{x["id"]}: {"undone" if x["state"] == "undone" else "not undone: " + x["err"]}'
                            for x in changes_of(a.pitch) if x['id'] in picks)
    if not rc:
        from agent_runner import control_settled  # F160
        control_settled.record(S.C, [a.pitch], 'was approved' if a.what == 'approve' else 'was answered no', a.why)
    print(said, file=sys.stderr if rc else sys.stdout)
    return rc
