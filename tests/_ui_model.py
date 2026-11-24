"""C44: what the tests/test_ui_model*.py files share: the fake run, its plan and the helpers (not run by the gate)."""
from __future__ import annotations
import json
import tempfile
from pathlib import Path
from unittest import mock
from _check import git
from agent_runner import state as S  # noqa: E402
from agent_runner import ui_model as U  # noqa: E402

TODO = """# TODO

## Now

### Next
- [ ] **F1** Board page for the run | files: a.py, tests/test_a.py
- [ ] **B2** Fix the merge retry | files: b.py | after: F1
- [~] **D3** Write the guide | files: docs/x.md BLOCKED: DECIDE: which layout https://claude.ai/artifact/abc
- [~] **F4** Build the option a person approves on concept K5 page: lazy layout | files: c.py BLOCKED: waiting for your OK on https://claude.ai/artifact/k5
- [ ] **V6** Release the next version | after: F1, B2

### Follow-ups
- [ ] **T7** (follow-up, low) Tidy the gate | files: run

### Parked
- [ ] **R8** Measure the cost | files: notes.md
"""


NOW = 1_800_000_000.0


def fake_run(tmp: Path) -> Path:
    repo = tmp / 'proj'
    (repo / 'plan').mkdir(parents=True)
    git(repo, 'init', '-q')
    (repo / '.gitignore').write_text('.runner/\n')
    (repo / 'plan' / 'TODO.md').write_text(TODO, encoding='utf-8')
    (repo / 'plan' / 'DONE.md').write_text('# DONE\n', encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'start')
    S.init(repo)
    S.C.notes('STATE').write_text(json.dumps({
        'state': '3 slots', 'running': {'1': 'F1', '2': 'B2'}, 'since': {'1': NOW - 14 * 60, '2': NOW - 60},
        'merging': ['B2'], 'usage': {'five_hour': 42.0, 'seven_day': 85.0}}), encoding='utf-8')
    S.C.notes('run.log').write_text(''.join(f'=== 2026-11-21T10:{i:02d}:00 line {i}\n' for i in range(30)),
                                    encoding='utf-8')
    return repo


def ran_by(out: list, text: str = 'ok'):
    return mock.patch.object(U, 'RUN', [lambda argv: (out.append(argv), (0, text))[1]])


def chat(n: int, sid: str, rows: list) -> str:
    S.C.notes(f'control{n}.pid').write_text(f'1 {sid}', encoding='utf-8')
    f = S.C.notes(f'{sid}.jsonl')
    f.write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
    return str(f)


def said(who: str, text: str, at: str) -> dict:
    return {'type': who, 'timestamp': at, 'message': {'content': [{'type': 'text', 'text': text}] if who == 'assistant'
                                                      else text}}


def in_tmp(f):
    def go():
        print(f.__name__)
        with tempfile.TemporaryDirectory() as d:
            f(Path(d))
    go.__name__ = f.__name__
    return go
