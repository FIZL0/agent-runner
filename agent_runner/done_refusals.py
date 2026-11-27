"""`done`'s refusals: why it will not take its arguments (`--until`, `--artifact`, a CONFIRM naming a missing concept)."""
from __future__ import annotations

import re
import sys

from agent_runner import asks, plan


def _prog() -> str:
    return sys.modules['agent_runner.done'].PROG  # read late: a wrapper sets its own name


def until_refusal(a, c) -> str | None:
    """F427b: why `done` refuses its `--until`, or None."""
    if a.until is None:
        return None
    if not a.blocked:
        return f'{_prog()}: --until goes with --blocked WHY. Nothing ticked.'
    if a.after:
        return plan.UNTIL_AFTER.format(prog=_prog())
    try:
        plan.until_list(a.until, c)
    except SystemExit as e:
        return str(e).replace(plan.PROG, _prog(), 1)
    return None


def artifact_refusal(a) -> str | None:
    """Why `done` refuses these arguments, or None: a concept task finishes only with the page it published."""
    if a.artifact and not re.match(r'https?://\S+$', a.artifact) and a.artifact != f'/concept/{a.id}':  # F406e: local page
        return f'{_prog()}: --artifact takes the page\'s URL (https://…), not {a.artifact!r}'
    if plan.concept(a.id) and not a.artifact and not a.blocked:
        return (f'{_prog()}: {a.id} is a concept task: it builds nothing, it publishes a page of options. Publish it '
                f'(the Artifact tool), then\n    {_prog()} {a.id} "<msg>" --artifact <its url>\nNothing ticked.')
    return None


def concept_link_refusal(tid: str, why: str | None, c) -> str | None:
    """B839: why `done --blocked` refuses a CONFIRM whose line or ask file names /concept/<ID> of a task that is no
    concept: no concept is filed for it, so that page is in no Concepts list and the person cannot open it."""
    if not re.match(r'\s*CONFIRM:', why or ''):
        return None
    text = why or ''
    try:
        f = asks.ask_file(tid, c)
        if f.is_file():
            text += '\n' + f.read_text(encoding='utf-8')
    except OSError:
        pass
    bad = sorted({i for i in re.findall(r'/concepts?/([A-Za-z]+\d+[a-z]*)', text) if not plan.concept(i)})
    if not bad:
        return None
    return (f'{_prog()}: the CONFIRM names /concept/{bad[0]}, but no concept is filed for {", ".join(bad)}: the person '
            f'has no such page to open. Put what they watch or look at in the ask file\'s "shots" (pictures, or .mp4 '
            f'and .webm videos under {asks.ask_file(tid, c).with_suffix("")}/, 50 MB each), or give a link they can '
            f'open. Nothing blocked.')
