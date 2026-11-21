"""F20: control sessions grill before queueing (after mattpocock/skills grilling, domain-modeling, to-tickets, MIT):
the control brief has the grilling branch, `agent-runner guide grill` says how, and `[run] grill` (ask | big | off)
fits it."""
from __future__ import annotations

import re
import tempfile
from pathlib import Path
from types import SimpleNamespace

from _check import FAILED, check, eq, git, run

from agent_runner import guide

ROOT = Path(__file__).resolve().parent.parent


def repo(toml: str = '') -> Path:
    d = Path(tempfile.mkdtemp(prefix='agent-runner-grill-'))
    git(d, 'init', '-q')
    (d / '.gitignore').write_text('.runner/\n')
    (d / 'README.md').write_text('demo\n')
    if toml:
        (d / 'runner.toml').write_text(toml)
    git(d, 'add', '-A')
    git(d, 'commit', '-qm', 'start')
    return d


def cfg(v=None):
    return SimpleNamespace(run={} if v is None else {'grill': v})


print('the control brief has the grilling branch')
control = guide.CONTROL.format(cmd='agent-runner', repo='demo', needs='Needs you', watch='', answer='', log='run.log')
line = guide.GRILL.format(cmd='agent-runner')
check(line in control, 'the control brief carries the grilling line')
check('grill me' in line and 'poke holes' in line and 'stress-test' in line, 'it names the asks that start it')
check('agent-runner guide grill' in line, 'it points at the grill topic')

print('the grill topic: rounds, recommended answers, facts looked up, one reply per round, then queue')
page = guide.topic('grill', 'agent-runner')
for words, what in [('numbered', 'questions are numbered'), ('recommended answer', 'each has a recommended answer'),
                    ('"yes"', 'worded so yes accepts it'), ('never ask them', 'facts are looked up, never asked'),
                    ('1b 2a', 'one reply answers a round, as on a pick sheet'),
                    ('nothing is left open', 'it stops when nothing is left open'),
                    ('settled answers', 'the task text carries the settled answers'),
                    ('glossary add', 'terms go to the glossary'), ('docs/adr/', 'an ADR only for hard choices'),
                    ('vertical slice', 'several tasks are vertical slices'), ('prefactor first', 'prefactor first'),
                    ('--after', 'ordered with --after'), ('one yes before queueing', 'one yes before any is queued')]:
    check(words in page, what)
check(max(len(l) for l in page.splitlines()) <= 120, 'phone-width lines')

print('[run] grill fits the brief')
eq(guide.grill_mode(cfg()), 'ask', 'default: ask')
for v, want in [('ask', 'ask'), ('big', 'big'), ('off', 'off'), (False, 'off'), ('BIG', 'big'), ('nonsense', 'ask')]:
    eq(guide.grill_mode(cfg(v)), want, f'grill = {v!r}')
eq(guide.grill_fit(control, 'agent-runner', cfg()), control, 'ask: the brief as it is')
big = guide.grill_fit(control, 'agent-runner', cfg('big'))
check(line not in big and 'big or vague' in big and 'agent-runner guide grill' in big, 'big: widened to big asks')
off = guide.grill_fit(control, 'agent-runner', cfg('off'))
check('guide grill' not in off and 'Grilling' not in off, 'off: the line is gone')
check('**Needs you items**' in off and '\n\n- **Needs you items**' not in off, 'off: no gap left behind')

print('config: the default is documented')
from agent_runner.config import DEFAULTS, default_docs  # noqa: E402
eq(DEFAULTS['run'].get('grill'), 'ask', '[run] grill defaults to ask')
check('big' in default_docs()['run']['grill'], 'its comment names the modes')

print('GLOSSARY.md seeds the words that keep tasks apart')
text = (ROOT / 'GLOSSARY.md').read_text(encoding='utf-8')
entries = dict(re.findall(r'^\*\*(.+?)\*\*:\n(.+?)(?=\n\n|\Z)', text, re.M | re.S))
check('same goal on the same files' in entries.get('Same work', ''), "'same work' = same goal on the same files")
check('one task per set of pages' in entries.get('Sweep', ''), "'sweep' = one task per set of pages")

print('the real brief: control --brief follows runner.toml')
b = run(repo(), 'control', '--brief').stdout
check('guide grill' in b and 'big or vague' not in b, 'no setting: the ask line', b[-300:])
b = run(repo('[run]\ngrill = "big"\n'), 'control', '--brief').stdout
check('big or vague' in b, 'grill = "big": widened')
b = run(repo('[run]\ngrill = "off"\n'), 'control', '--brief').stdout
check(b and 'guide grill' not in b, 'grill = "off": none')
r = run(repo(), 'guide', 'grill')
check(r.returncode == 0 and 'vertical slice' in r.stdout, '`agent-runner guide grill` prints the topic', r.stderr)

raise SystemExit(1 if FAILED else print('\nall checks passed'))
