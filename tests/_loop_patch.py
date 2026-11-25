"""C51: `agent_runner.loop` was split into loop, loop_requests, loop_watch and loop_after. A name the run's
collaborators share (log, stopping, end_orphans, …) lives in each module that uses it, so a test stub goes to all."""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
from unittest import mock

from agent_runner import loop, loop_after, loop_requests, loop_watch

MODULES = (loop, loop_requests, loop_watch, loop_after)


@contextmanager
def patched(**names):
    """`mock.patch.object(loop, name, value)` for each name, in every loop module that holds the name."""
    with ExitStack() as st:
        for k, v in names.items():
            for mod in MODULES:
                if hasattr(mod, k):
                    st.enter_context(mock.patch.object(mod, k, v))
        yield
