"""F414: lessons asked only when something went wrong — each trigger once, a clean task never."""
from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace

from _check import check, eq, git, report  # noqa: E402  (_check puts the repo on sys.path)
from agent_runner import lessons_ask as A


def repo() -> Path:
    d = Path(tempfile.mkdtemp())
    git(d, 'init', '-q')
    return d


ON = SimpleNamespace(raw={'plan': {'lessons': True}})
OFF = SimpleNamespace(raw={'plan': {'lessons': False}})


def t_clean_never_asked():
    d = repo()
    eq(A.ask(d, 'F1', '- [ ] **F1** do x', ON), '', 'a clean task is not asked')


def t_gate_asks_once():
    d = repo()
    A.mark_failed_gate(d, 'F1')
    A.mark_failed_gate(d, 'F1')
    eq(A.ask(d, 'F1', '- [ ] **F1** x', OFF), '', 'lessons off: never asked')
    q = A.ask(d, 'F1', '- [ ] **F1** x', ON)
    check('gate failed' in q and 'check instead' in q, 'a failed gate asks, check first', q)
    eq(A.ask(d, 'F1', '- [ ] **F1** x', ON), '', 'asked once')
    eq(A.ask(d, 'F2', '- [ ] **F2** x', ON), '', 'another task is clean')


def t_person_change_asks_once():
    d = repo()
    item = '- [ ] **F1** x — you said: do this instead: y'
    check('person changed' in A.ask(d, 'F1', item, ON), 'a person\'s plan change asks')
    eq(A.ask(d, 'F1', item, ON), '', 'asked once')
    A.mark_failed_gate(d, 'F1')
    q = A.ask(d, 'F1', item, ON)
    check('gate failed' in q and 'person' not in q, 'a new trigger asks again, just it', q)


def t_repair_line():
    check('plan lesson add' in A.repair_line(ON), 'a repair session may file one')
    eq(A.repair_line(OFF), '', 'not with lessons off')


if __name__ == '__main__':
    raise SystemExit(report([t_clean_never_asked, t_gate_asks_once, t_person_change_asks_once, t_repair_line]))
