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
* With no chain, nothing here acts: a task waits for the reset as before.
"""
from __future__ import annotations

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
USAGE_CAPPED = [False]  # the loop's `capped` holds claude ([run] session_max / weekly_max) this tick
CAP_TOLD: dict[str, float] = {}  # sid -> when it was told to stop over a cap

CAP_STOP = ('Stop at a clean point: {provider} has hit its usage cap ({why}). If your `{runner} done` is already '
            'running its test gate, let it finish and do nothing else. Otherwise do not run `done`: commit what is '
            'solid on task/{tid}, write in your journal what is done and what is left, then end your turn. The run '
            'goes on with {tid} in this worktree on {model}, the next provider in [models] fallback.')

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


def is_capped(name: str, capped: dict | None = None) -> bool:
    return name in (capped_now() if capped is None else capped) or (name == 'claude' and USAGE_CAPPED[0])


def chain_next(model: str, capped: dict | None = None) -> str | None:
    """The chain's model to go on with after `model`: the first entry after it (after none when it is not in the
    chain) on another provider that is not capped and has its login; None when there is none, or no chain."""
    from agent_runner.login import missing
    chain = state.C.fallback
    after = chain[chain.index(model) + 1:] if model in chain else chain
    capped = capped_now() if capped is None else capped
    return next((m for m in after if provider(m) != provider(model) and not is_capped(provider(m), capped)
                 and not missing(m, state.C)), None)  # F106e: a provider with no login is passed over


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


def start_model(model: str) -> str:
    """The model a new task starts on: its own, unless its provider is capped and the chain has a free one."""
    if state.C.fallback and is_capped(provider(model)):
        return chain_next(model) or model
    return model


def chain_open() -> bool:
    """With claude capped, a new task can still start: the chain names a provider that is not capped."""
    return bool(state.C.fallback) and chain_next(state.C.models['code'], {**capped_now(), 'claude': float('inf')}) is not None


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


def reset_at(text: str) -> float | None:
    """The reset time a cap's text names as an epoch (Claude Code's "usage limit reached|1764000000")."""
    if (m := re.search(r'\|(\d{10})\b', text)) and float(m[1]) > time.time():
        return float(m[1])
    return None


def fallback_due(tid: str, sid: str) -> tuple[str, str] | None:
    """(model, why): the session of `tid` that ended stopped on a cap, and the chain names where it goes on;
    None otherwise (no chain: the cut-off path waits for the reset as before)."""
    mark = state.C.notes(f'{tid}.fallback')
    try:
        d = json.loads(mark.read_text(encoding='utf-8'))
        mark.unlink()
        if isinstance(d, dict) and d.get('model'):
            return d['model'], d.get('why') or 'its provider hit its cap'
    except (OSError, ValueError):
        pass
    if not state.C.fallback or not (text := cap_text(sid)):
        return None
    was = session_model(sid)
    mark_capped(provider(was), reset_at(text))
    if not (nxt := chain_next(was)):
        return None
    return nxt, f'{provider(was)} hit its cap ({text[:120]})'


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
    if not state.C.fallback:
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
        mark_capped('claude', reset_at(text))
        if not (nxt := chain_next(was)):
            continue  # every provider in the chain is capped: it waits for the reset, as with no chain
        why = f'claude hit its cap ({text[:120]})'
        state.C.notes(f'{tid}.fallback').write_text(json.dumps({'model': nxt, 'why': why}), encoding='utf-8')
        CAP_TOLD[sid] = time.time()
        said = type_into(n, procs, CAP_STOP.format(provider='claude', why=text[:120], runner=state.C.command, tid=tid,
                                                   model=nxt))
        if said is None:
            log(f'slot {n}: {tid} {why}: told it to stop at a clean point and commit; it goes on with {nxt}', None, tid)
        else:
            CAP_TOLD[sid] = float('inf')
            plat.terminate(pid)
            log(f'slot {n}: {tid} {why}; {said}, so its session is ended; it goes on with {nxt}', None, tid)
