"""F106g: the fallback chain, `[models] fallback`: the '<provider>:<model>' list a task goes on with when its
provider hits its cap (a Claude usage limit, a provider's quota error).

* A Claude Code task that hits a cap while it runs (`caps`, every tick) is told to stop at a clean point, as an
  F103 budget stop is, and ended after CAP_GRACE s; one whose session ended on a cap is taken as it is. Either
  way `reap` reopens it in the same slot (`fallback_due`, `queue_fallback`): its worktree as the session left it,
  a new session on the next provider in the chain, told to read the work and the journal and carry on.
* A harness-loop task switches provider within its session (harness.mjs `--fallback`), and ends on the cap
  only when the chain holds no further harness model; the runner then reopens it as above (a claude entry).
* A capped provider is kept in `<notes>/capped.json` ({provider: until}), till the reset its error named, else
  CAP_HOLD s; a new task whose model is on a capped provider starts on the chain's first free one
  (`start_model`), and once the cap resets new tasks go back to their own model.
* F142: past `[run] session_max` / `weekly_max` a new task whose model is claude's starts on the chain's first free
  one too (`free_model`); one with none waits for the reset (`no_free`). Running tasks are not touched.
* F503: capped.json is keyed by login ('claude' its default login, 'claude@<name>' another, `cap_key`): a capped
  login goes on with the same provider's next free login (`free_login`, the session's env `session_env`), then the
  chain; a provider is capped only when all its logins are. A local model (ollama, no login) is a chain entry
  like any other, normally the last. `session_max` / `weekly_max` hold each login by its own usage (F514).
* With no chain and one login, nothing here acts: a task waits for the reset as before.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import time

from agent_runner import plat, state
from agent_runner.config import finished_mark, harness_model
from agent_runner.state import log

CAP_HOLD = 3600  # s a provider counts as capped when its error named no reset time
CAP_GRACE = 120  # s a session told to stop over a cap gets before it is ended
# the text of a usage limit or a quota error (Claude Code's own "usage limit reached|<epoch>", "You've hit your
# limit · resets 3pm"; a provider's 429, quota or resource-exhausted error)
CAP = re.compile(r'usage limit|limit reached|hit your limit|rate.?limit|quota|resource.?exhausted|'
                 r'too many requests|\b429\b', re.I)
CAP_TOLD: dict[str, float] = {}  # sid -> when it was told to stop over a cap

CAP_STOP = ('Stop at a clean point: {provider} has hit its usage cap ({why}). If your `{runner} done` is already '
            'running its test gate, let it finish and do nothing else. Otherwise do not run `done`: commit what is '
            'solid on task/{tid}, write in your journal what is done and what is left, then end your turn. The run '
            'goes on with {tid} in this worktree on {model}, the next free login or [models] fallback entry.')

FALLBACK = """The runner started this session on {model} for task {tid}: an earlier session worked on it in this \
worktree and stopped because {why}. Its commits on task/{tid} and its uncommitted edits are here as it left them. \
Before anything else read `git log {branch}..HEAD`, `git status` and the task's journal (if it wrote one), then \
carry on with the task where it left off and finish it as the brief below says.

"""


def provider(model: str) -> str:
    """The provider a settled model runs on: '<provider>' for a harness model, else 'claude'."""
    return model.partition(':')[0] if harness_model(model, state.C.providers) else 'claude'


def capped_now() -> dict[str, float]:
    """{provider: until} of the providers capped now: `<notes>/capped.json`, the runner's and the harness loop's."""
    try:
        d = json.loads(state.C.notes('capped.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    now = time.time()
    return {p: float(u) for p, u in d.items() if isinstance(u, (int, float)) and u > now} \
        if isinstance(d, dict) else {}


def mark_capped(name: str, until: float | None = None) -> None:
    """`name` is capped till `until` (else CAP_HOLD s from now)."""
    d = capped_now()
    d[name] = max(d.get(name, 0.0), until or time.time() + CAP_HOLD)
    state.C.notes('capped.json').write_text(json.dumps(d), encoding='utf-8')


def login_names(prov: str) -> list[str]:
    """F503: the logins of provider `prov`, the default first: claude's from `run login claude --as`; [''] (its one
    login) for a provider with no logins of its own."""
    if prov != 'claude':
        return ['']
    from agent_runner.claude_use import logins
    return [r['name'] for r in logins()] or ['']


def cap_key(prov: str, login: str = '') -> str:
    """F503: the key in capped.json of `prov`'s login `login`: '<provider>' for its default login (as before
    multi-login, and as the harness loop writes it), '<provider>@<login>' for another."""
    names = login_names(prov)
    return prov if not login or login == names[0] else f'{prov}@{login}'


def free_login(prov: str, capped: dict | None = None) -> str | None:
    """F503: the first login of `prov` that is not capped ('' its default with no name); None when all are."""
    capped = capped_now() if capped is None else capped
    return next((n for n in login_names(prov) if cap_key(prov, n) not in capped), None)


def is_capped(name: str, capped: dict | None = None) -> bool:
    """A capped.json key ('<provider>@<login>') is capped; a provider is capped when every login of it is (F503)."""
    capped = capped_now() if capped is None else capped
    if '@' in name:
        return name in capped
    return free_login(name, capped) is None


def earliest_reset(capped: dict | None = None) -> float | None:
    """F503: when the first cap lifts (all capped and no local model: the run waits for it); None with none."""
    capped = capped_now() if capped is None else capped
    return min((u for u in capped.values() if u != float('inf')), default=None)


def note_login(sid: str, login: str) -> None:
    """F503: the Claude login session `sid` runs on ('' the default)."""
    try:
        state.C.notes(f'{sid}.login').write_text(login, encoding='utf-8')
    except OSError:
        pass


def session_login(sid: str) -> str:
    try:
        return state.C.notes(f'{sid}.login').read_text(encoding='utf-8').strip()
    except OSError:
        return ''


def session_env(tid: str, sid: str, model: str, held: frozenset = frozenset(), login: str | None = None) -> list[str]:
    """F503: the env entries for session `sid` of `tid` on `model`: on claude, the login it runs on (`login`, else
    the one a cap stop pinned in `<tid>.login`, else the first free one), noted for the session; [] elsewhere."""
    from agent_runner.claude_use import login_env
    if provider(model) != 'claude':
        return []
    pin = state.C.notes(f'{tid}.login')
    if login is None:
        try:
            login = pin.read_text(encoding='utf-8').strip()
            pin.unlink(missing_ok=True)
        except OSError:
            login = None
    if login is None:
        login = free_login('claude', with_held(held)) or ''
    note_login(sid, login)
    return [f'{k}={v}' for k, v in login_env(login).items()]


def multi() -> bool:
    """F503: claude has more than one login, so a cap moves to the next one even with no chain."""
    return len(login_names('claude')) > 1


def chain_next(model: str, capped: dict | None = None, whole: bool = False) -> str | None:
    """The chain's model to go on with after `model`: the first entry after it (after none when it is not in the
    chain) on another provider that is not capped and has its login; None when there is none, or no chain. `whole`: the
    whole chain's first such entry (a new task: no entry before its model has been tried)."""
    from agent_runner.claude_use import lacking
    from agent_runner.login import missing
    chain = state.C.fallback
    after = chain[chain.index(model) + 1:] if model in chain and not whole else chain
    capped = capped_now() if capped is None else capped
    return next((m for m in after if provider(m) != provider(model) and not is_capped(provider(m), capped)
                 and not missing(m, state.C) and not lacking(m, state.C)), None)  # F106e: a provider with no login is passed over


def harness_chain(model: str) -> list[str]:
    """F106g: the entries a harness-loop session on `model` may switch to within itself: those after it in the
    chain (all of it when it is not in it) up to the first claude one, which only a new session can run."""
    chain = state.C.fallback
    out = []
    for m in chain[chain.index(model) + 1:] if model in chain else chain:
        if provider(m) == 'claude':
            break
        if provider(m) != provider(model):
            out.append(m)
    return out


USAGE_HELD = frozenset({'claude'})  # the providers `[run] session_max` / `weekly_max` hold new tasks from


def with_held(held: frozenset) -> dict[str, float]:
    """The providers a new task passes over: those capped now, and `held` (past the usage caps: USAGE_HELD), and
    F514: claude's other logins whose own usage is past `[run] session_max` / `weekly_max`."""
    return {**capped_now(), **dict.fromkeys(held | usage_held_logins(), float('inf'))}


def usage_held_logins() -> frozenset:
    """F514: the cap keys of claude's logins other than the default whose own usage (read from their own config
    dir's credentials) is at or past `[run] session_max` / `weekly_max`; none with one login or while forced. The
    default login's usage is read by the loop (`capped`, USAGE_HELD)."""
    if state.FORCED[0] or not multi():
        return frozenset()
    from agent_runner.claude_use import logins
    from agent_runner.watch import login_usage
    run = getattr(state.C, 'run', None) or {}
    out = set()
    for r in logins()[1:]:
        if not r.get('dir'):
            continue
        got = login_usage(r['dir']) or {}
        for name, key in (('five_hour', 'session_max'), ('seven_day', 'weekly_max')):
            try:
                w, cap = got[name]['utilization'], run.get(key)
            except (TypeError, KeyError):
                continue
            if isinstance(w, (int, float)) and isinstance(cap, (int, float)) and w >= cap:
                out.add(cap_key('claude', r['name']))
                break
    return frozenset(out)


def start_model(model: str, held: frozenset = frozenset()) -> str:
    """The model a new task starts on: its own, unless its provider is capped (or in `held`) and the chain has a
    free one."""
    if (state.C.fallback or multi()) and is_capped(provider(model), capped := with_held(held)):
        return chain_next(model, capped, whole=True) or model
    return model


def free_model(model: str, held: frozenset) -> str | None:
    """F142: `start_model`, but None when that model's provider is capped or in `held`: nothing free to start on."""
    m = start_model(model, held)
    return None if is_capped(provider(m), with_held(held)) else m


def no_free(branch: str, model: str, held: frozenset) -> set[str]:
    """F142: the open tasks with no free model while `held` providers take no new task: they wait for the reset."""
    from agent_runner.sched import tasks
    from agent_runner.slots import task_model
    ls, free = state.plan_text(branch), {}
    out = set()
    for tid, *_ in tasks(branch):
        m = task_model(tid, model, branch, ls)
        if m not in free:
            free[m] = free_model(m, held) is not None
        if not free[m]:
            out.add(tid)
    return out


def note_model(sid: str, model: str) -> None:
    """The model session `sid` runs on, for `reap` (the harness loop rewrites it when it switches)."""
    try:
        state.C.notes(f'{sid}.model').write_text(model, encoding='utf-8')
    except OSError:
        pass


def session_model(sid: str) -> str:
    try:
        return state.C.notes(f'{sid}.model').read_text(encoding='utf-8').strip() or state.C.models['code']
    except OSError:
        return state.C.models['code']


def cap_text(sid: str) -> str:
    """The cap session `sid` stopped on: its last turn an API error that reads as a usage limit or quota; ''
    otherwise."""
    from agent_runner.slots import entries
    last = None
    for d in entries(sid, skip_bad=True):
        if d.get('type') in ('user', 'assistant') and not d.get('isSidechain') and not d.get('isMeta'):
            last = d
    if not last or not last.get('isApiErrorMessage'):
        return ''
    c = (last.get('message') or {}).get('content') if isinstance(last.get('message'), dict) else ''
    text = ' '.join((c if isinstance(c, str) else ' '.join(x.get('text', '') for x in c or []
                                                          if isinstance(x, dict))).split())
    if last.get('error') != 'rate_limit' and not CAP.search(text):
        return ''
    return text[:200] or 'usage limit'


def limit_of(d: dict) -> tuple[str, float | None] | None:
    """B170: (text, reset epoch or None) when transcript entry `d` is a usage-limit error, read from the error's own
    fields (its words only from a Claude Code that wrote none); None otherwise. The reset: the error's `resetsAt`,
    else what its words name after the moment it was written (not after now: that would move it on a day)."""
    if not d.get('isApiErrorMessage'):
        return None
    c = (d.get('message') or {}).get('content') if isinstance(d.get('message'), dict) else ''
    text = ' '.join((c if isinstance(c, str) else ' '.join(str(x.get('text') or '') for x in c or []
                                                          if isinstance(x, dict))).split())
    kind = d.get('error') or d.get('apiError')
    if kind not in ('rate_limit', 'usage_limit_reached') and (kind or not CAP.search(text)):
        return None
    params = d.get('apiErrorParams') if isinstance(d.get('apiErrorParams'), dict) else {}
    for q in (d.get('quotaLimits'), params.get('rate_limit_info')):
        if isinstance(q, dict) and isinstance(q.get('resetsAt'), (int, float)):
            return text, float(q['resetsAt'])
    try:
        at = dt.datetime.fromisoformat(str(d['timestamp']).replace('Z', '+00:00')).timestamp()
    except (KeyError, ValueError):
        at = None
    return text, reset_at(text, at)


def reset_at(text: str, now: float | None = None) -> float | None:
    """The reset time a cap's text names, as an epoch: Claude Code's "usage limit reached|1764000000", or
    "resets 3pm" / "resets 3:30pm" / "resets 15:00" (local time, the next such time); None when it names none."""
    now = time.time() if now is None else now
    if (m := re.search(r'\|(\d{10})\b', text)) and float(m[1]) > now:
        return float(m[1])
    if not (m := re.search(r'resets?\s+(?:at\s+)?(\d{1,2})(?::(\d\d))?\s*([ap]m)?\b', text, re.I)):
        return None
    hour, minute, half = int(m[1]), int(m[2] or 0), (m[3] or '').lower()
    if half:
        hour = hour % 12 + (12 if half == 'pm' else 0)
    if hour > 23 or minute > 59:
        return None
    at = dt.datetime.fromtimestamp(now).replace(hour=hour, minute=minute, second=0, microsecond=0)
    if at.timestamp() <= now:
        at += dt.timedelta(days=1)
    return at.timestamp()


def fallback_due(tid: str, sid: str) -> tuple[str, str] | None:
    """(model, why): the session of `tid` that ended stopped on a cap, and the chain names where it goes on;
    None otherwise (no chain: the cut-off path waits for the reset as before)."""
    mark = state.C.notes(f'{tid}.fallback')
    try:
        d = json.loads(mark.read_text(encoding='utf-8'))
        mark.unlink()
        if isinstance(d, dict) and d.get('model'):
            if isinstance(d.get('login'), str):
                state.C.notes(f'{tid}.login').write_text(d['login'], encoding='utf-8')
            return d['model'], d.get('why') or 'its provider hit its cap'
    except (OSError, ValueError):
        pass
    if not (state.C.fallback or multi()) or not (text := cap_text(sid)):
        return None
    if not (nxt := after_cap(tid, sid, text)):
        return None
    return nxt[0], nxt[2]


def after_cap(tid: str, sid: str, text: str) -> tuple[str, str | None, str] | None:
    """F503: session `sid` of `tid` hit a cap (`text`): its login is marked capped, and (model, login, why) says where
    the task goes on: the same model on its provider's next free login, else the chain's next free entry (its
    login picked at start: None); None when all are capped and no local model is left (it waits for
    `earliest_reset`). A login to go on on is pinned in `<tid>.login` for the next session."""
    was, login = session_model(sid), session_login(sid)
    prov = provider(was)
    key = cap_key(prov, login)
    mark_capped(key, reset_at(text))
    why = f'{key} hit its cap ({text[:120]})'
    if (other := free_login(prov)) is not None:
        state.C.notes(f'{tid}.login').write_text(other, encoding='utf-8')
        return was, other, why
    if nxt := chain_next(was):
        return nxt, None, why
    if (at := earliest_reset()) is not None:
        log(f'{tid}: every login and provider is capped; it waits for the first reset, '
            f'{dt.datetime.fromtimestamp(at):%a %H:%M}', None, tid)
    return None


def queue_fallback(tid: str, n: int, sid: str, why: str, model: str) -> None:
    """Queue `tid` to go on in slot n on `model`: `resume_queued` starts a new session there (`queued_model`)."""
    state.C.notes(f'{tid}.resume').write_text(json.dumps({'slot': n, 'sid': sid, 'why': why, 'model': model}),
                                        encoding='utf-8')


def queued_model(tid: str) -> str:
    """The fallback model `tid`'s queued resume goes on with; '' for a plain resume of its session."""
    try:
        return json.loads(state.C.notes(f'{tid}.resume').read_text(encoding='utf-8')).get('model') or ''
    except (OSError, ValueError, AttributeError):
        return ''


def caps(procs: dict, running: dict, type_into) -> None:
    """Each running Claude Code task that hit a cap, with a chain to go on: claude marked capped, the task told to
    stop at a clean point and commit (its `<tid>.fallback` mark says where it goes on), and ended once it has
    had CAP_GRACE s, or at once when nothing could be typed into it. One whose `done` passed is left to land."""
    if not (state.C.fallback or multi()):
        return
    for sid in [s for s in CAP_TOLD if s not in {p[1] for p in procs.values()}]:
        CAP_TOLD.pop(sid)
    for n, (pid, sid, _) in list(procs.items()):
        if n not in running or ((m := finished_mark(n)) and m.exists()) or not plat.alive(pid):
            continue  # an ended session is the reap's (`fallback_due`)
        tid = running[n][0]
        if sid in CAP_TOLD:
            if time.time() - CAP_TOLD[sid] >= CAP_GRACE and plat.alive(pid):
                CAP_TOLD[sid] = float('inf')
                plat.terminate(pid)
                log(f'slot {n}: {tid} had {CAP_GRACE} s to stop over the cap; its session is ended', None, tid)
            continue
        if provider(was := session_model(sid)) != 'claude' or not (text := cap_text(sid)):
            continue  # the harness loop switches within its session
        if not (got := after_cap(tid, sid, text)):
            continue  # every login and provider in the chain is capped: it waits for the reset, as with no chain
        nxt, login, why = got
        state.C.notes(f'{tid}.fallback').write_text(json.dumps({'model': nxt, 'why': why, 'login': login}),
                                                   encoding='utf-8')
        nxt = f'{nxt} on login {login or "default"}' if login is not None else nxt
        CAP_TOLD[sid] = time.time()
        said = type_into(n, procs, CAP_STOP.format(provider='claude', why=text[:120], runner=state.C.command, tid=tid,
                                                   model=nxt))
        if said is None:
            log(f'slot {n}: {tid} {why}: told it to stop at a clean point and commit; it goes on with {nxt}', None, tid)
        else:
            CAP_TOLD[sid] = float('inf')
            plat.terminate(pid)
            log(f'slot {n}: {tid} {why}; {said}, so its session is ended; it goes on with {nxt}', None, tid)
