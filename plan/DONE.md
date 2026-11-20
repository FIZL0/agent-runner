# DONE — the archive (`./run plan tick <ID>` puts them here)

### Next
- [x] **B1** agent-runner plan add/note/move/block/... on a plan inside the repo (no [plan] repo) skips plansync.locked: plan.main only locks when c.plan_external, so two control sessions filing at once can read the same TODO.md, take the same next id, and one write drops the other's task (user 2026-11-19 'fix the plan add thing to handle' several control sessions). Take plansync.locked(c) around every EDITS command for in-repo plans too (reads stay unlocked). Done when: a test runs two 'plan add' processes at once on an in-repo plan, 20 times, and every task lands with a distinct id. | files: agent_runner/plan.py, tests/test_plan.py
