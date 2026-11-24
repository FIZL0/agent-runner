"""F194c: the example project's walkthrough in the terminal UI: the steps the page shows (its WALK_STEPS, the one list),
worded for keys. Where the person is, or that they skipped it, is kept in the project's .runner folder.
"""
from __future__ import annotations

import json
from pathlib import Path

LIST = Path(__file__).with_name('page') / '084-walk.logic.js'
PLACE = {'queue': (3, ''), 'start': (1, 'controls'), 'session': (2, ''), 'needs': (4, ''), 'land': (1, 'log'),
         'chat': (2, ''), 'own': (0, '')}  # the panel a step points at (0 none), and its tab
BACK, NEXT, SKIP = '<', '>', '/'  # the keys; SKIP shows a skipped walkthrough again too


def steps() -> list[dict]:
    """The steps in order, as the page has them."""
    text = LIST.read_text(encoding='utf-8')
    return json.loads(text[text.index('\n[') + 1:text.rindex(']') + 1])


def words(s: dict, up: bool = False, working: int = 0, needs: int = 0, landed: int = 0) -> str:
    """What step `s` says in the terminal UI: whether a run is up, and how many tasks are worked on, need the
    person and landed."""
    say = {'start': [s.get('up' if up else 'off'), s.get('keysUp' if up else 'keysOff')],
           'session': [s.get('text'), s.get('keysWorking' if working else 'keysIdle')],
           'needs': [s.get('text'), s.get('some' if needs else 'none'), s.get('keys')],
           'land': [s.get('text'), s.get('keys'), '' if landed else s.get('none')],
           'own': [s.get('text'), s.get('setup')]}.get(s['id'], [s.get('text'), s.get('keys')])
    return ' '.join(w for w in say if w)


class Walk:
    """Where the person is in the walkthrough: `at` the step's id, `off` skipped or done; kept in `file`."""

    def __init__(self, file: Path):
        self.file, self.steps = file, steps()
        self.ids = [s['id'] for s in self.steps]
        try:
            kept = json.loads(file.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            kept = {}
        kept = kept if isinstance(kept, dict) else {}
        self.at = kept.get('at') if kept.get('at') in self.ids else self.ids[0]
        self.off = kept.get('off') is True

    @property
    def i(self) -> int:
        return self.ids.index(self.at)

    @property
    def step(self) -> dict:
        return self.steps[self.i]

    @property
    def last(self) -> bool:
        return self.i == len(self.steps) - 1

    def press(self, k: str) -> bool:
        """Key `k`; False when it is not one of the walkthrough's now. Next on the last step is done."""
        if k == SKIP:
            if not self.off and self.last:
                self.at = self.ids[0]
            self.off = not self.off
        elif self.off or k not in (BACK, NEXT):
            return False
        elif k == NEXT and self.last:
            self.at, self.off = self.ids[0], True
        else:
            self.at = self.ids[min(max(self.i + (1 if k == NEXT else -1), 0), len(self.ids) - 1)]
        try:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            self.file.write_text(json.dumps({'at': self.at, 'off': self.off}) + '\n', encoding='utf-8')
        except OSError:  # not kept: the walkthrough still goes on
            pass
        return True


def of(root: Path, notes: Path) -> Walk | None:
    """The walkthrough of the project at `root` (its notes folder: `notes`), None unless it is the example one."""
    try:
        from agent_runner.demo import is_demo
        return Walk(notes / 'walk.json') if is_demo(root) else None
    except Exception:  # noqa: BLE001 - the terminal UI never fails over the walkthrough
        return None
