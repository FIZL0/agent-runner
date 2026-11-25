"""F406h: does a project run anything on Claude Code? With every [models] role on another provider it needs no Claude
Code: a missing one, its login, its usage and its API then hold nothing and are not said."""
from __future__ import annotations


def uses(c, flag: str = '') -> bool:
    """A session of config `c` may run on Claude Code: a role, a kind or `run --model` (`flag`, else the one `c`
    was given) names a claude model, or a [models] fallback entry does and Claude Code is here (a missing one is passed
    over: fallback.chain_next). Not [models] docs: that is a subagent of a Claude Code
    task session, so with none it never runs. A claude model on a task's own line is not counted: only that task
    waits, for Claude Code (login.unlogged) or for its usage and API (`own_tasks`)."""
    from agent_runner.config import agent_missing, harness_model
    models = getattr(c, 'models', None)
    if not isinstance(models, dict):
        return True
    named = [v for k, v in models.items() if k not in ('kinds', 'docs') and isinstance(v, str)]
    named += (models.get('kinds') or {}).values()
    named += filter(None, [flag or c.run.get('model_flag')])
    if any(not harness_model(m, c.providers) for m in named):
        return True
    return any(not harness_model(m, c.providers) for m in c.fallback) and not agent_missing(c.root, str(c.run['agent']))


def account(c) -> bool:
    """`c`'s sessions run on this machine's Claude account: its login, usage caps and API matter to it."""
    return (c.run.get('agent') or 'claude') == 'claude' and uses(c)


def lacking(model: str, c) -> bool:
    """A task on settled `model` needs Claude Code, which this machine lacks, in a project that needs it for nothing else
    (one that does is held as a whole: sched.agent_held)."""
    from agent_runner.config import agent_missing, harness_model
    return not harness_model(model, c.providers) and not uses(c) and bool(agent_missing(c.root, c.run['agent']))


def own_tasks(c, branch: str, model: str) -> dict[str, str]:
    """B791: {id: model} of the open tasks whose own model is claude's, in a project that needs this machine's Claude
    account for nothing else, with Claude Code here: its usage caps and API hold these tasks alone. Empty in a project
    they hold as a whole (`account`)."""
    from agent_runner.config import agent_missing, harness_model
    if (c.run.get('agent') or 'claude') != 'claude' or uses(c) or agent_missing(c.root, 'claude'):
        return {}
    from agent_runner.sched import tasks
    from agent_runner.slots import task_model
    from agent_runner.state import plan_text
    ls = plan_text(branch)
    settled = {tid: task_model(tid, model, branch, ls) for tid, *_ in tasks(branch)}
    return {tid: m for tid, m in settled.items() if not harness_model(m, c.providers)}


def own_waiting(run) -> dict[str, str]:
    """B791: the `own_tasks` that `run` (a loop.Run) may still start."""
    from agent_runner import state
    gone = run.tried | {t[0] for t in run.running.values()}
    return {t: m for t, m in own_tasks(state.C, run.branch, run.model).items() if t not in gone}


def passed_over(run, own: dict[str, str], held: frozenset) -> tuple[set[str], set[str]]:
    """The tasks `run` starts nothing of now: (those with no free model past a usage cap, the `own` ones that would
    start on Claude Code while its API cannot be reached). With `own`, only they are held. The API is said once."""
    from agent_runner import fallback, state
    from agent_runner.watch import api_up
    passed = fallback.no_free(run.branch, run.model, held) if held else set()
    if own:
        passed &= own.keys()
    out = {t for t, m in own.items() if fallback.provider(fallback.start_model(m, held)) == 'claude'}
    if not out or api_up(True):
        run.stall_said.discard('api own')
        return passed, set()
    if 'api own' not in run.stall_said:
        run.stall_said.add('api own')
        state.log(f'the Claude API cannot be reached: {", ".join(sorted(out))} cannot start until it can')
    return passed, out


def resume_held(run, n: int) -> bool:
    """B799: the session queued for slot `n` of `run` would go on with a claude model while the Claude API cannot be
    reached, in a project that needs the account for nothing else (else `api_down` holds it). Said once."""
    from agent_runner import fallback as FB, state
    from agent_runner.watch import api_up
    tid, sid, _ = run.waiting[n]
    key, c = f'api {tid}', state.C
    if (c.run.get('agent') or 'claude') != 'claude' or account(c) or \
            FB.provider(FB.queued_model(tid) or FB.session_model(sid)) != 'claude' or api_up(True):
        run.stall_said.discard(key)
        return False
    if key not in run.stall_said:
        run.stall_said.add(key)
        state.log(f'the Claude API cannot be reached: {tid} cannot resume until it can')
    return True


def cap_alarm(w: str, own: str, detail: str) -> tuple[str, str]:
    """The usage-cap alarm's line and detail; `own`: the task it holds alone (B791)."""
    if not own:
        return f'{w}: no new tasks', detail
    how = detail[detail.find('To go on now'):]
    return f'{w}: {own} cannot start until the reset', f'its model is a claude one; tasks on other models still start. {how}'
