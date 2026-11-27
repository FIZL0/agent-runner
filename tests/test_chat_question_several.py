"""F192b1: several DECIDE lines at the end of one answer."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent_runner.chat_question import ask_of, asks_of, decide_questions  # noqa: E402

ONE = 'Done.\n\nDECIDE: Ship it now? [Yes (recommended) / No]'
assert asks_of(ONE, 'u1') == [ask_of(ONE, 'u1')]
assert asks_of(ONE) == [ask_of(ONE)]

SEV = 'Two things.\n\nDECIDE: Ship it now? [Yes / No]\n\nDECIDE: Which colour? [Red (recommended) / Blue]\nDECIDE: Tell me more?'
assert decide_questions(SEV) == ['Ship it now? [Yes / No]', 'Which colour? [Red (recommended) / Blue]', 'Tell me more?']
a = asks_of(SEV, 'u1')
assert [x['id'] for x in a] == ['u1', 'u1#2'], a
assert a[0]['question'] == 'Ship it now?' and [o['name'] for o in a[1]['options']] == ['Red', 'Blue'], a
b = asks_of(SEV, 'u1', bare=True)
assert [x['id'] for x in b] == ['u1', 'u1#2', 'u1#3'] and b[2]['options'] == []
c = asks_of(SEV)
assert len({x['id'] for x in c}) == 2 and c == asks_of(SEV)  # stable ids, each its own

QUOTED = 'Status: it said\nDECIDE: Old one? [A / B]\nand now it is done.'
assert asks_of(QUOTED, bare=True) == [] and decide_questions(QUOTED) == []
MIXED = 'DECIDE: Old one? [A / B]\nsome words\n\nDECIDE: New one? [C / D]'
assert decide_questions(MIXED) == ['New one? [C / D]']
print('ok')
