"""B28: the settings reference (`agent-runner settings`), generated from config.DEFAULTS, and the guide and control
brief recommending a change only by a key that is really there."""
from __future__ import annotations

import re
import tempfile
import tomllib
from pathlib import Path

from _check import FAILED, check, eq, git, has, run

from agent_runner import guide
from agent_runner.config import DEFAULTS, default_docs, settings_reference

ref = settings_reference('agent-runner')

print('every [run] and [plan] key is in the reference, with its default and its comment')
lines = ref.splitlines()
for table in ('run', 'plan', 'git', 'needs'):
    check(f'[{table}]' in lines, f'[{table}] has a heading')
    for k, v in DEFAULTS[table].items():
        line = next((s for s in lines if s.startswith(f'{k} = ')), '')
        check(line, f'[{table}] {k} is listed')
        if line:  # the value as written parses back to the default
            val = re.split(r'  # ', line, maxsplit=1)[0]
            eq(tomllib.loads(val)[k], v, f'[{table}] {k}: its default, as TOML')
docs = default_docs()
check(all(docs['run'][k] for k in DEFAULTS['run']), 'every [run] key has a comment to show')
check(all(docs['plan'][k] for k in DEFAULTS['plan']), 'every [plan] key too')
has(ref, r'control_idle = "3h"  # quiet this long', 'a key reads as `key = default  # what it does`')
has(ref, r'apply on the next run', 'it says when a change applies')
has(ref, r'runner\.local\.toml \(this machine only', 'and runner.toml vs runner.local.toml')
has(ref, r'take "set \[run\] KEY = VALUE', 'and that a runner.toml change goes through take, not the main checkout')
check('control_close = true  # the run closes' in ref, 'a ticket tag (B26:) is dropped from a comment')

print('`agent-runner settings` prints it')
tmp = Path(tempfile.mkdtemp(prefix='agent-runner-settings-'))
git(tmp, 'init', '-q')
r = run(tmp, 'settings')
eq(r.returncode, 0, 'exits 0')
check('slots = 3' in r.stdout and '[needs]' in r.stdout, 'every table')

print('the guide and the control brief recommend settings, by real keys only')
for name, text in (('GUIDE', guide.GUIDE), ('CONTROL', guide.CONTROL)):
    check('settings` prints every key' in text, f'{name} points at `settings`')
    check('recommend the one change in one line' in text, f'{name} says to recommend a setting in one line')
    check('apply on the next run' in text, f'{name} says when it applies')
    check('never as an edit in the main checkout' in text and 'take "set [run]' in text,
          f'{name} makes a runner.toml change through take')
named = [(t, k) for t, k in re.findall(r'`\[(\w+)\] (\w+) = ', guide.SETTINGS) if t != 'table'] + [
    ('run', k) for k in re.findall(r'`(\w+) = ', guide.SETTINGS)]
check(len(named) >= 6, 'the brief names several example keys', str(named))
for table, k in named:
    check(k in DEFAULTS.get(table, {}), f'example [{table}] {k} is a real key')
check('night' not in guide.SETTINGS, 'no "fewer agents at night": no such setting')

raise SystemExit(1 if FAILED else print('\nall checks passed'))
