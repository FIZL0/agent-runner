"""B774: a task whose runs end with no commits stops looping: two in a row, with its own plan text the same at both
ends, and it is blocked under Needs you with what its last session said."""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from contextlib import ExitStack
from pathlib import Path

from agent_runner import plan as P, plansync
from agent_runner import state as S
from agent_runner.state import commit_plan, EV_LEFT, git, log, MERGE, note, plan_rel, plan_text

LIMIT = 2       # runs in a row that end with no commits before a person is asked
SAID_MAX = 240  # characters of the last session's words in the block
_LOCK = threading.Lock()  # the merge threads and the loop both write the record


def _file() -> Path:
    return S.C.notes('no-commits.json')


def _read() -> dict[str, dict]:
    """{task: {'runs', 'plan' (its mark then), 'said'}} of the tasks whose last run ended with no commits."""
    try:
        d = json.loads(_file().read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return {t: r for t, r in d.items() if isinstance(r, dict)} if isinstance(d, dict) else {}


def _write(d: dict[str, dict]) -> None:
    tmp = _file().with_suffix('.json-tmp')
    try:
        tmp.write_text(json.dumps(d, indent=1), encoding='utf-8')
        os.replace(tmp, _file())
    except OSError as e:
        log(f'could not note the tasks that ended with no commits ({e}); they may start again')


def _open_marks(branch: str) -> dict[str, str]:
    """{open task: a mark of all the plan says to it: its lines, its long form and what it was told}. Where its lines
    stand does not count."""
    ls, out = plan_text(branch), {}
    for _, box, tid, _, i in P.iter_tasks(ls):
        if box != ' ':
            continue
        text = '\n'.join(P._item_block(ls, i)).strip()
        for f in (P.long_form(S.C.plan_dir, tid), P.told_file(S.C, tid)):
            try:
                text += '\0' + f.read_text(encoding='utf-8', errors='replace')
            except OSError:
                text += '\0'
        out[tid] = hashlib.sha256(text.encode()).hexdigest()
    return out


def ended(tid: str, said: str, branch: str) -> None:
    """A slot's session on `tid` ended with no commits, its last words `said`. One that closed or blocked its task
    (a plan outside the repo) did its work."""
    mark = _open_marks(branch).get(tid)
    with _LOCK:
        d = _read()
        old = d.pop(tid, None)
        if mark:
            runs = old['runs'] + 1 if old and old.get('plan') == mark and isinstance(old.get('runs'), int) else 1
            d[tid] = {'runs': runs, 'plan': mark, 'said': plain(said)}
        if old or mark:
            _write(d)


def forget(tid: str) -> None:
    """`tid` has commits, or is no longer open: its runs with none are no longer in a row."""
    with _LOCK:
        d = _read()
        if d.pop(tid, None) is not None:
            _write(d)


def reopened(tid: str, c) -> None:
    """`tid` of project `c`'s plan was unblocked, maybe with no run up: forget it, as `forget` does. Takes
    the project, since a plan command has no run's state."""
    f = c.notes('no-commits.json')
    with _LOCK:
        try:
            d = json.loads(f.read_text(encoding='utf-8'))
            if isinstance(d, dict) and d.pop(tid, None) is not None:
                tmp = f.with_suffix('.json-tmp')
                tmp.write_text(json.dumps(d, indent=1), encoding='utf-8')
                os.replace(tmp, f)
        except (OSError, ValueError):
            return


def stuck(branch: str) -> dict[str, dict]:
    """The open tasks that LIMIT runs in a row ended with no commits, unchanged in the plan since: none may start."""
    d = {t: r for t, r in _read().items() if isinstance(r.get('runs'), int) and r['runs'] >= LIMIT}
    if not d:
        return {}
    marks = _open_marks(branch)
    return {t: r for t, r in d.items() if marks.get(t) == r.get('plan')}


def plain(said: str) -> str:
    """A session's words on a plan line: nothing the plan would read as its own mark (a field, a tag, a wait, a block,
    buttons), and short."""
    s = re.sub(r'[()\[\]]', '', said).replace('|', '/').replace('"', "'")
    s = re.sub(r'\s*[—–]\s*', ' - ', s)
    s = re.sub(r'\b(BLOCKED|DECIDE|CONFIRM|CONCEPT):', lambda m: m[1].lower(), s)
    s = ' '.join(s.split())
    return s if len(s) <= SAID_MAX else s[:SAID_MAX].rstrip() + '…'


def tick(branch: str) -> None:
    """Each tick of the run: forget the tasks that closed or blocked (reopened, they count afresh), and block the
    stuck ones on a person, committed as `sched.block_parked` commits; one that cannot be now is tried again next
    tick."""
    if not (d := _read()):
        return
    marks = _open_marks(branch)
    for tid in d:
        if tid not in marks:
            forget(tid)
    for tid, r in stuck(branch).items():
        _block(tid, r, branch)


def _block(tid: str, r: dict, branch: str) -> bool:
    if not MERGE.acquire(blocking=False):
        return False
    hold = ExitStack()
    hold.callback(MERGE.release)
    with hold:
        if S.C.plan_external:
            hold.enter_context(plansync.locked(S.C))
            plansync.pull(S.C, force=True)
        rel = plan_rel('TODO.md')
        if not S.C.plan_external and (git('status', '--porcelain', '--', rel).stdout.strip() or
                                      git('branch', '--show-current').stdout.strip() != branch):
            return False
        if tid not in stuck(branch):  # edited, closed or blocked meanwhile
            return False
        if tid not in P.open_ids(P.lines(S.ROOT / rel)):
            return False  # the main checkout is behind the remote
        said = str(r.get('said') or '')
        P.block(tid, f'DECIDE: {tid} ended {r["runs"]} times in a row with no commits: change it, start it again or '
                'drop it? ' + (f'Its last session said: "{said}"' if said else 'Its last session left no words.'),
                todo=S.ROOT / rel, after=[])
        if not commit_plan(f'Plan: block {tid}, {r["runs"]} runs in a row with no commits', rel):
            if not S.C.plan_external:
                git('checkout', '-q', '--', rel)
            return False
        forget(tid)
        why = f'{r["runs"]} runs in a row ended with no commits'
        note(f'{tid}: LEFT FOR A HUMAN — {why}; blocked on a person')
        log(f'{tid}: LEFT FOR A HUMAN — {why}; blocked on a person instead of starting it again', EV_LEFT, tid, why=why)
        return True


# B858: a session the model API turned away (an HTTP 400, invalid_request_error) did no work on its task: the setup
# (provider, agent version) is wrong, not the task. It does not count, and the run pauses for a person.
_API_ERR = re.compile(r'API Error:\s*4(?!29)\d\d|invalid_request_error', re.I)
SETUP_SAID: list[str] = []  # the setup problems already put under Needs you by this run


def api_error(said: str) -> bool:
    """`said`, a session's last words, is the model API refusing its request, not the agent's own words."""
    return bool(said and _API_ERR.search(said))


def session_setup(sid: str) -> tuple[str, str]:
    """(agent version, model) session `sid`'s transcript names; '' for what it does not."""
    version = model = ''
    if not sid or sid == '(unknown)':
        return version, model
    try:
        from agent_runner.slots import entries
        for d in entries(sid, skip_bad=True):
            version = str(d.get('version') or version)
            m = d.get('message')
            model = str(m.get('model') or model) if isinstance(m, dict) else model
    except Exception:  # noqa: BLE001 - a transcript we cannot read still pauses the run
        pass
    return version, model


def setup_problem(tid: str, said: str, sid: str = '') -> None:
    """`tid`'s session ended on an API error: forget any count, pause the run (no new tasks) and say once under
    Needs you what the setup problem is, in plain words."""
    from agent_runner import fallback as FB
    forget(tid)
    S.PAUSED[0] = True
    version, model = session_setup(sid)
    try:
        provider = FB.provider(model) if model else ''
    except Exception:  # noqa: BLE001
        provider = ''
    msg = plain(said)
    title = 'the model API turned the agent away: fix the setup, then press p'
    detail = '; '.join(x for x in (
        f'provider {provider}' if provider else '', f'model {model}' if model else '',
        f'agent version {version}' if version else '', f'the API said: "{msg}"') if x)
    detail += f'. {tid} is not counted against and stays ready; the run is paused, no new tasks start until p.'
    log(f'{tid}: the model API refused the session: a setup problem, not the task\'s ({detail})')
    if msg in SETUP_SAID:
        return
    SETUP_SAID.append(msg)
    S.alarm(title, detail)
