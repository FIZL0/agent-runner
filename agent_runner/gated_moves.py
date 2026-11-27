"""F493: whether the shared branch moved during a merge's gate only by gated work on other files."""
from __future__ import annotations

from agent_runner.state import git

GATE_FILES = ('runner.toml',)  # a change here may change the gate itself: always tested again


def moved_by_gated_only(base: str, new: str, merged: str, moved: list[str]) -> bool:
    """Main went from `base` to `new` only by merges the runner made (each passed its own gate), none of them
    touching a file the merge `merged` changes or the gate's own settings: the tested merge needs no new gate.
    A hand commit on main (any first-parent commit that is not a runner's merge) tests it again."""
    if not moved or any(f in GATE_FILES for f in moved):
        return False
    ours = set(git('diff', '--name-only', base, merged).stdout.split())
    if ours & set(moved):
        return False
    for line in git('log', '--first-parent', '--format=%P%x09%s', f'{base}..{new}').stdout.splitlines():
        parents, _, subject = line.partition('\t')
        if len(parents.split()) != 2 or not subject.startswith(("Merge branch 'task/", 'Merge: ')):
            return False
    return True
