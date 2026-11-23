"""F129: the person's own name for a control session (`control --rename`).

Not one of the FAMILY modules `share` reaches, so the run's settings are read through their modules at call time."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from agent_runner import control as K, state


def person_name_file(n: int) -> Path:
    """F129: `<notes>/control<n>.name`: the name the person gave control session `n` on the run page or in the TUI,
    and the custom title its transcript had then (JSON {name, was}), until the typed /rename shows there."""
    return state.C.notes(f'control{n}.name')


def person_name(n: int, title: str) -> str:
    """F129: the name the person last gave control session `n`, whose transcript's custom title is `title`; '' when
    the person named it nowhere but the apps. A title that changed since (a rename in the apps, or the typed
    one arriving) is the newer name, so the record stands only until then."""
    try:
        d = json.loads(person_name_file(n).read_text(encoding='utf-8'))
        return str(d['name']) if title in (str(d['was']), str(d['name'])) else ''
    except (OSError, ValueError, KeyError, TypeError):
        return ''


def control_rename(number: str, name: str) -> int:
    """F129 `control --rename N NAME`: the person's own rename of control session `n` (c1 too), from the run app or
    the TUI: `/rename NAME` is typed into it, so its custom title is the person's and `control_renamed` keeps it
    (never closed when idle, B41; `control --title` does not replace it). The name is kept in state too, so it
    shows at once, before the turn under way ends."""
    if not number.isdigit():
        print(f'--rename N NAME: N is the control session\'s number, not {number!r}', file=sys.stderr)
        return 2
    n, name = int(number), ' '.join(str(name or '').split())[:80]
    if not name or name.startswith('/'):
        print('--rename needs a name', file=sys.stderr)
        return 2
    if not K.control_live(n):
        print(f'control {n} is not up', file=sys.stderr)
        return 1
    try:
        sid = state.C.notes(f'control{n}.pid').read_text(encoding='utf-8').strip().partition(' ')[2]
    except OSError:
        sid = ''
    was = K.control_state(K.entries(sid, skip_bad=True))['title'] if sid and K.transcript(sid) else ''
    try:
        person_name_file(n).write_text(json.dumps({'name': name, 'was': was}) + '\n', encoding='utf-8')
    except OSError:
        pass
    if K.control_type(n, f'/rename {name}'):
        print(f'control {n} is renamed "{name}"')
    else:
        print(f'control {n} is named "{name}" on the run page and in the TUI (it runs in a terminal of its own, so '
              f'the Claude apps keep its name)')
    return 0
