#!/usr/bin/env python3
"""B868: a task that waits for a release is never one of the tasks that release waits for."""
from __future__ import annotations

from _check import eq, report

from agent_runner import plan  # noqa: E402


def test_cycle():
    print('plan: a release does not wait on a task --after it')
    ls = ['# TODO', '', '### Next', '',
          '- [ ] **B1** a fix | files: a.py',
          '- [ ] **R2** after the release | after: V3',
          '- [ ] **R4** after R2 | after: R2',
          '- [ ] **V3** release | after: all',
          '- [ ] **V5** release last | after: all above']
    eq(plan.before_all(ls, 7), ['B1'], 'all: R2 and R4 left out')
    eq(plan.above(ls, 8), ['B1', 'R2', 'R4', 'V3'], 'another release still waits on them')
    ls2 = ls[:7] + ['- [ ] **V3** release | after: all above']
    eq(plan.above(ls2, 7), ['B1'], 'all above: R2 and R4 left out')
    eq(plan.waits_on(ls, 5), ['V3'], 'R2 still waits for the release')


if __name__ == '__main__':
    raise SystemExit(report([test_cycle]))
