"""F460a: run page actions that are not the plan's or a setting's: Settings > Plan's "Share the plan between machines".

Imported by `web`; each adds itself to `ui_model.ACTIONS`, so the page's outbox reaches it at POST /act."""
from __future__ import annotations

from agent_runner import ui_model as U


def plan_share(target: str = '') -> dict:
    """`plan repo-setup [target]` for this project (`ui_model.plan_repo_setup`), as an action's result: 'lines' are what it
    says, the last one being what the other machine runs; 'out' is them joined."""
    r = U.plan_repo_setup(str(target or ''))
    lines = [str(x) for x in r.get('lines') or []]
    ok = bool(r.get('ok'))
    return {'ok': ok, 'code': 0 if ok else 1, 'out': '\n'.join(lines), 'argv': [], 'lines': lines}


U.ACTIONS['plan_share'] = plan_share
