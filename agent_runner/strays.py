"""B224: the stray files a research task committed, taken off its branch before the merge."""

from __future__ import annotations

import os

from agent_runner import state as S
from agent_runner.brief import findings_globs
from agent_runner.done import docs_only


def new_empty(tid: str, branch: str) -> list[str]:
    """B224: the files task/<tid> adds with nothing in them."""
    empty = S.git('hash-object', '-t', 'blob', '--stdin', input='').stdout.strip()
    parts = S.git('diff', '--raw', '-z', '--no-abbrev', '--no-renames', f'{branch}...task/{tid}').stdout.split('\0')
    return [f for meta, f in zip(parts[::2], parts[1::2]) if (m := meta.split())[4] == 'A' and m[3] == empty]


def drop_strays(tid: str, branch: str) -> None:
    """B224: the new empty files beyond its findings that a research task committed (a log the shell had just made,
    say) come off task/<tid> in a commit on top. The caller has seen no real code beside them (`merge.research_code`).
    Before it waits for the lock, so every merge built of it, a rider's too, is without them."""
    globs = findings_globs()
    if not (strays := [f for f in new_empty(tid, branch) if not docs_only([f], globs)]):
        return
    old = S.git('rev-parse', f'refs/heads/task/{tid}').stdout.strip()
    idx = S.C.notes(f'strays.{tid}.index')
    env = {**os.environ, 'GIT_INDEX_FILE': str(idx)}
    try:
        tree = '' if S.git('read-tree', old, env=env).returncode or \
            S.git('update-index', '--force-remove', '--', *strays, env=env).returncode else \
            S.git('write-tree', env=env).stdout.strip()
    finally:
        idx.unlink(missing_ok=True)
    said = f'dropped {", ".join(strays)}: new and empty, no part of the findings'
    new = tree and S.git('commit-tree', tree, '-p', old, '-m', f'{tid}: {said}').stdout.strip()
    if not new or S.git('update-ref', f'refs/heads/task/{tid}', new, old).returncode:
        S.log(f'{tid}: could not drop {", ".join(strays)} (new and empty); it lands with the findings')
        return
    S.log(f'{tid}: {said}')
