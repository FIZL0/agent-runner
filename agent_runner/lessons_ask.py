"""F414: lessons are captured when something went wrong.

With `[plan] lessons = true`, `run done` asks the session for one lesson (or 'none') only after a failed gate in
this task or a person's plan change on it; a merge repair's prompt says its session may file one. Each trigger
asks once per task; a clean task is never asked; it never blocks `done`.
"""
from __future__ import annotations

import re
from pathlib import Path

from agent_runner.gitops import git

PERSON = re.compile(r'you said\b|do this instead', re.I)  # the notes `plan change` and a stuck answer write

CHECK_FIRST = ('If a test or the git fence can enforce it, add or file that check instead of a lesson '
               '(`run plan add T …`); once the check exists, the lesson goes (`plan lesson drop ID "why"`).')

WHY = {'gate': 'a gate failed in this task', 'person': 'a person changed this task in the plan'}


def on(c) -> bool:
    return bool(c.raw.get('plan', {}).get('lessons'))


def _dir(cwd: Path) -> Path | None:
    r = git('rev-parse', '--absolute-git-dir', cwd=cwd)
    return None if r.returncode else Path(r.stdout.strip()) / 'agent-runner' / 'lessons'


def _read(f: Path) -> set[str]:
    try:
        return set(f.read_text().split())
    except OSError:
        return set()


def _add(f: Path, word: str) -> None:
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        with f.open('a') as fh:
            fh.write(word + '\n')
    except OSError:
        pass


def mark_failed_gate(cwd: Path, tid: str) -> None:
    """Note that `tid`'s gate failed in this worktree (kept past the pass that resets the fail count)."""
    if d := _dir(cwd):
        _add(d / f'{tid}.seen', 'gate')


def person_changed(item: str) -> bool:
    """True when the task's plan text holds a person's change (`you said: do this instead: …`)."""
    return bool(PERSON.search(item or ''))


def ask(cwd: Path, tid: str, item: str, c) -> str:
    """The lesson question for `tid`, or '' (lessons off, nothing went wrong, or each trigger already asked).
    Marks what it asks as asked."""
    if not on(c) or not (d := _dir(cwd)):
        return ''
    seen = _read(d / f'{tid}.seen') | ({'person'} if person_changed(item) else set())
    new = sorted(seen - _read(d / f'{tid}.asked'))
    if not new:
        return ''
    for w in new:
        _add(d / f'{tid}.asked', w)
    why = ' and '.join(WHY[w] for w in new if w in WHY)
    return (f'Lesson? {why[:1].upper() + why[1:]}. {CHECK_FIRST} Otherwise, if it taught something the next '
            f'agent on these files should know: `run plan lesson add "TEXT" --files …`; if not, nothing to do '
            f'(none). This does not hold up {tid}.')


REPAIR_LINE = ('6. Lessons are on here: if this clash taught something the next agent on these files should know, '
               'say so in your last words and file it with `run plan lesson add "TEXT" --files …`; if a test or '
               'the git fence can enforce it, file that check instead (`run plan add T …`).\n')


def repair_line(c) -> str:
    """The repair prompt's lesson step, '' with lessons off."""
    return REPAIR_LINE if on(c) else ''
