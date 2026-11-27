"""F192d: the option-tasks store: store, counts, queue once, drop."""
from __future__ import annotations

import tempfile
from pathlib import Path

from _check import FAILED, check

from agent_runner import option_tasks as O

root = Path(tempfile.mkdtemp())
q = 'Should the demo app keep its old login page?'
print('store and counts')
O.store(q, {'Yes': [['F', 'keep it', '--files', 'a.py'], ['T', 'test it']], 'No': []}, 'demo login', root)
check(O.counts(q + ' [Yes (recommended) / No]', root) == {'Yes': 2}, 'counts by the question words, bracket left out')
check(O.counts('Another question?', root) == {}, 'another question has none')
print('queue once')
added = []
check(len(O.queue(q, 'Yes', root, added.append)) == 2, 'the option queues its two tasks')
check(added[0] == ['F', 'keep it', '--files', 'a.py'], 'with its plan add arguments')
check(O.queue(q, 'Yes', root, added.append) == [] and len(added) == 2, 'a second tap adds nothing')
check(O.queue(q, 'No', root, added.append) == [], 'an option without tasks queues nothing')
print('drop')
check(O.drop(q, root) == 1 and O.counts(q, root) == {}, 'dropped once answered')
print('replaced')
O.store(q, {'Yes': [['F', 'old']]}, 'first', root)
O.store(q, {'Yes': [['F', 'new']], 'No': [['C', 'drop it']]}, 'second', root)
check(O.stored(q, root)['Yes'] == [['F', 'new']] and len(list(root.glob('*.json'))) == 1, 'storing again replaces')
check(O.drop(q, root) == 1 and O.counts(q, root) == {}, 'dropped once replaced by the answer')
check(not list(root.iterdir()), 'nothing left behind, claim files too')
raise SystemExit(1 if FAILED else 0)
