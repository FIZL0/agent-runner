"""D1: GLOSSARY.md has an entry (a definition and the words to avoid) for every term the person, the briefs and
the code use, and the slot and control briefs tell agents to use a repo's GLOSSARY.md terms."""
from __future__ import annotations

import re
from pathlib import Path

from _check import FAILED, check

from agent_runner import brief, guide

ROOT = Path(__file__).resolve().parent.parent
TERMS = ['Run', 'Slot', 'Task', 'Kind', 'Control session', 'c1', 'Take', 'Gate', 'Fixer',
         'Merge worktree', 'Concept', 'Needs you', 'Shelve', 'Claim', 'Notes dir', 'Remote']

print('GLOSSARY.md has an entry per term')
text = (ROOT / 'GLOSSARY.md').read_text(encoding='utf-8')
entries = dict(re.findall(r'^\*\*(.+?)\*\*:\n(.+?)(?=\n\n|\Z)', text, re.M | re.S))
for t in TERMS:
    body = entries.get(t, '')
    check(bool(body), f'{t}: has an entry')
    check('\n_Avoid_: ' in body, f'{t}: names the words to avoid')
check(all(w in entries['Needs you'] for w in ('CONFIRM', 'DECIDE', 'BLOCKED')), 'Needs you names its three kinds')
check('push remote' in entries['Remote'], 'Remote tells Remote Control apart from the git push remote')

print('the briefs point at a project GLOSSARY.md')
check('GLOSSARY.md' in guide.GLOSSARY, 'the line names GLOSSARY.md')
check(guide.GLOSSARY in brief.PROMPT, 'the slot prompt carries it')
control = guide.CONTROL.format(cmd='agent-runner', repo='demo', needs='Needs you', watch='', answer='', log='run.log')
check(guide.GLOSSARY in control, 'the control brief carries it')
check('control 1' not in control.lower(), 'the control brief says c1, not control 1')

raise SystemExit(1 if FAILED else print('\nall checks passed'))
