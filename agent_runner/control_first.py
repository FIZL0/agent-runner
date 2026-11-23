"""B147: a control session's first message, typed in once Remote Control is up.

Claude Code runs a positional first message (`claude "<ask>" --remote-control …`) before the Remote Control
bridge connects, so the claude.ai/code thread would start at the agent's reply. Under its own hidden shim a
control session therefore starts with no positional prompt (`control_argv` keeps the text in CONTROL_FIRST), and
`control N` leaves a detached process that types it in through the shim's FIFO once the session's log shows its
claude.ai/code link. Elsewhere (a terminal, Windows, Remote Control off) the positional prompt stays."""

from __future__ import annotations

import os
import time
from pathlib import Path

from agent_runner import plat
from agent_runner.control import CONTROL_LINK_WAIT, SESSION_LINK
from agent_runner.state import log

CONTROL_FIRST = ['']  # the first message control_argv left off the command line, for type_first_later
FIRST_SETTLE = 1.0  # s after the claude.ai/code link shows before the first message is typed in


def first_typed(n: int) -> bool:
    """Can this `control N` type its first message in rather than pass it on the command line? Only under its
    own hidden shim (AGENT_RUNNER_MARKER names `<notes>/control<n>.live`, the FIFO `control<n>.in` beside it; a
    slot's marker is not one), never on Windows."""
    return not plat.WINDOWS and Path(os.environ.get('AGENT_RUNNER_MARKER') or 'x').name == f'control{n}.live'


def first_wait(log_file: Path, since: int, wait: float) -> bool:
    """Wait up to `wait` s for the claude.ai/code link (Remote Control is up) in `log_file` past byte `since`;
    False when it never showed."""
    end = time.monotonic() + wait
    while True:
        try:
            with open(log_file, 'rb') as fh:
                fh.seek(since)
                if SESSION_LINK.search(fh.read().decode('utf-8', 'replace')):
                    return True
        except OSError:
            pass
        if time.monotonic() >= end:
            return False
        time.sleep(0.5)


def type_first(marker: Path, text: str, since: int, wait: float = 0.0) -> bool:
    """Type `text`, a control session's first message, through its hidden shim's FIFO (`<stem>.in` beside
    `marker`) once its log (`<stem>.log`) shows the claude.ai/code link, so the web thread starts with it. With
    no link in `wait` s (CONTROL_LINK_WAIT by default) it is typed anyway: late beats lost."""
    from agent_runner.slots import send_fifo
    first_wait(marker.with_suffix('.log'), since, wait or CONTROL_LINK_WAIT)
    time.sleep(FIRST_SETTLE)  # the TUI takes input a beat after it shows the link
    inbox = marker.with_suffix('.in')
    for _ in range(5):
        if send_fifo(inbox, text):
            return True
        time.sleep(1)
    return False


def type_first_later(text: str) -> None:
    """Before `control N` execs its agent, leave a detached process (double fork, so nothing waits on it) that
    types `text` in once Remote Control is up (`type_first`). POSIX only, as `first_typed`."""
    marker = Path(os.environ['AGENT_RUNNER_MARKER'])
    try:
        since = marker.with_suffix('.log').stat().st_size
    except OSError:
        since = 0
    mark = marker.with_suffix('.first')  # B154: other messages wait for this one (control_takes_input)
    mark.write_text('', encoding='utf-8')
    pid = os.fork()
    if pid:
        os.waitpid(pid, 0)
        return
    try:
        os.setsid()
        if os.fork():
            os._exit(0)
        null = os.open(os.devnull, os.O_RDWR)
        for fd in (0, 1, 2):  # off the session's terminal, so nothing it prints lands in the TUI
            os.dup2(null, fd)
        if not type_first(marker, text, since):  # recorded, so a lost first message is not silent
            log(f'{marker.stem}: its first message could not be typed in (no shim read {marker.with_suffix(".in")})')
    finally:
        mark.unlink(missing_ok=True)
        os._exit(0)
