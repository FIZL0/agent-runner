"""B852: a Working row says Testing or Waiting to test while its task's `done` gate runs or waits
(agent_runner/merge_rows.py: mark_slot_gate, live_gates, gate_phase; ui_model_snapshot.py's session_rows).

    python3 tests/test_slot_testing.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from _check import check, eq, report

from agent_runner import merge_rows as M  # noqa: E402
from agent_runner import state as S  # noqa: E402
from agent_runner import ui_model as US  # noqa: E402
from _web import fake_repo, in_tmp  # noqa: E402


def test_phases(tmp: Path) -> None:
    fake_repo(tmp)
    st = {'running': {'1': 'F1', '2': 'F2', '3': 'F3'}, 'since': {}}
    gate = lambda: {r['task']: r['gate'] for r in US.session_rows(st, [], {}, 0.0, links={}, windows={}) if r['task']}  # noqa: E731
    eq(gate(), {'F1': '', 'F2': '', 'F3': ''}, 'no gate: Working')
    M.mark_slot_gate(S.C, 'F1', tmp, 'testing')
    M.mark_slot_gate(S.C, 'F2', tmp, 'waiting')
    eq(gate(), {'F1': 'testing', 'F2': 'waiting', 'F3': ''}, 'a running gate and a waiting one')
    eq(M.stage('F1', M.live_gates()), M.UNKNOWN, "a slot's gate is not a merge gate")
    dead = subprocess.Popen([sys.executable, '-c', 'pass'])
    dead.wait()
    (S.C.notes(M.SLOT_GATES, 'F3.json')).write_text(
        '{"tid": "F3", "phase": "testing", "pid": %d}' % dead.pid, encoding='utf-8')
    eq(gate()['F3'], '', 'a gate killed midway never leaves the row at Testing')
    M.clear_slot_gate(S.C, 'F1')
    eq(gate()['F1'], '', 'the gate ended: Working again')
    os.environ.pop('AGENT_RUNNER_SLOT', None)
    eq(M.gate_phase('F9', '2', [{'slot_gate': True, 'tid': 'X', 'slot': '2', 'phase': 'testing'}]), 'testing', 'by its slot too')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_phases)]))
