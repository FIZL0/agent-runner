"""F406h: does a project run anything on Claude Code? With every [models] role on another provider it needs no Claude
Code: a missing one, its login, its usage and its API then hold nothing and are not said."""
from __future__ import annotations


def uses(c, flag: str = '') -> bool:
    """A session of config `c` may run on Claude Code: a role, a kind or `run --model` (`flag`, else the one `c`
    was given) names a claude model, or a [models] fallback entry does and Claude Code is here (a missing one is passed
    over: fallback.chain_next). Not [models] docs: that is a subagent of a Claude Code
    task session, so with none it never runs. A claude model on a task's own line is not counted: only that task
    waits for Claude Code (login.unlogged)."""
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
