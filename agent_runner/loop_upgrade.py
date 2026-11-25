"""C53: the upgrade and restart part of the end of a tick, split from loop_after."""

from __future__ import annotations

from agent_runner import exit_hook
from agent_runner.state import stopping
from agent_runner.watch import auto_upgrade, restart_if_upgraded, watch_code


def upgrade_tick(run) -> None:
    """Upgrade, watch the code, and restart onto a new version when no merge is under way."""
    if not stopping():
        auto_upgrade(bool(run.merging))
        watch_code(bool(run.merging))  # F149
    if not run.merging and not stopping() and not exit_hook.busy():  # B801: a restart forgets which slot it holds
        restart_if_upgraded()
