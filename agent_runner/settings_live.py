"""F202a: a run that is up reads runner.toml and runner.local.toml again when they change, with no restart.

Not one of the FAMILY modules `share` reaches, so the run's settings (ROOT, C, SLOTS) are read through their modules."""
from __future__ import annotations

import threading
import time

from agent_runner import config, slots, state as S

SETTINGS_SEEN: list = []  # `settings_print` as last read, taken or refused


def start() -> dict:
    """As the run starts, on the settings it has read: what later changes are told by. Its [run] table."""
    from agent_runner import ui_model
    SETTINGS_SEEN[:] = [config.settings_print(S.ROOT)]
    ui_model.settings_start()  # what the Settings page's `waits` compares with
    return S.C.run


KEPT: dict[str, tuple] = {}  # session -> (its model, its budget caps), from before the settings changed


def restore(keep: dict) -> dict:
    """`keep` (`loop.kept_keys`), its KEPT taken over: a restart in place adopts the same sessions."""
    KEPT.update(keep.get('kept') or {})
    return keep


def caps(sid: str) -> tuple:
    """Session `sid`'s budget caps, [run] task_tokens and task_usd: its own, when the settings changed since."""
    return KEPT[sid][1] if sid in KEPT else (S.C.run.get('task_tokens') or 0, S.C.run.get('task_usd') or 0)


def keep_own(sid: str, tid: str, model: str, branch: str) -> None:
    """The settings are about to change: session `sid` of `tid` goes on with the model and caps it has."""
    if sid not in KEPT:
        KEPT[sid] = slots.task_model(tid, model, branch), caps(sid)


def take(run) -> None:
    """The loop's tick: `run` (a `loop.Run`) takes changed settings; the sessions there are (running, or cut off and
    waiting to resume) keep theirs."""
    def before() -> None:
        own = [(p[1], run.running[n][0]) for n, p in run.procs.items() if n in run.running]
        for sid, tid in own + [(q[1], q[0]) for q in S.queued().values()]:
            keep_own(sid, tid, run.model, run.branch)
    if read_settings(before, run.once):
        run.r = S.C.run
        run.model = run.a.model or run.r['model']


def read_settings(before=lambda: None, once: bool = False) -> dict:
    """The run loop's tick: the settings files changed, so the run takes them, without a restart; the changed keys
    ({} when nothing changed, or they cannot be taken: the run keeps what it has and run.log says why). `before` runs
    first, on the old settings; `once`: the slot count is the run's own."""
    if not SETTINGS_SEEN or S.LANDING.locked():  # a merge is moving the checkout: its files may be half written
        return {}
    now = config.settings_print(S.ROOT)
    if now == SETTINGS_SEEN[0]:
        return {}
    time.sleep(SETTINGS_STILL)  # a save by hand or a git checkout may be under way: the next tick looks again
    if config.settings_print(S.ROOT) != now or S.LANDING.locked():
        return {}
    SETTINGS_SEEN[0] = now
    told = list(S.C.warnings)
    try:
        new, changed, waits = config.read_again(S.C)
    except ValueError as e:
        S.log(f'settings: changed, but not taken, so the run keeps the ones it has: {e}')
        return {}
    before()
    config.reload(S.C, new, waits)
    for w in S.C.warnings:
        if w not in told:
            S.log(w)
    for what, keys in (('now in force (running tasks keep their own)', changed), ('waits for the next run', waits)):
        if keys:
            S.log(f'settings: {what}: ' + ', '.join(f'[{t}] {k}' + (
                f' = {config.toml_value(changed[t, k])[:60]}' if isinstance(changed.get((t, k)), (bool, int, float, str))
                else '') for t, k in keys))
    try:
        apply_settings(changed, once)
    except Exception as e:  # noqa: BLE001 - the run goes on
        S.log(f'settings: {type(e).__name__}: {e}')
    return changed


SETTINGS_STILL = 0.2  # s the changed files must hold still


def apply_settings(changed: dict, once: bool = False) -> None:
    """What changed settings do beyond being read from now on."""
    from agent_runner import control as K, watch
    run = {k: v for (t, k), v in changed.items() if t == 'run'}
    if 'slots' in run and not once and run['slots'] != slots.SLOTS:
        S.share(SLOTS=run['slots'])
        S.log(f'slots: {slots.SLOTS}')
    if 'auto_upgrade' in run:
        watch.AUTO_UPGRADE[0] = bool(run['auto_upgrade'])
    if {'remote', 'control'} & set(run):
        K.settle_control_server()
    if {'remote', 'remote_slots'} & set(run):
        S.log(slots.remote_line() or 'remote control off')
    if 'silent' in run:
        K.settle_quiet()
    if run.get('install_skill') or run.get('rules_pointer'):
        threading.Thread(target=_add_pointers, daemon=True).start()


def _add_pointers() -> None:
    from agent_runner.guide import install, point_rules
    if S.C.run['install_skill'] and (said := install()):
        S.log(said)
    with S.LANDING:  # it commits in the main checkout
        said = point_rules(S.C, S.git)
    if said:
        S.log(said)
