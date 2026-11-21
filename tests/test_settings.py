"""B28: the settings reference (`agent-runner settings`), generated from config.DEFAULTS, and the guide and control
brief recommending a change only by a key that is really there."""
from __future__ import annotations

import re
import tempfile
import tomllib
from pathlib import Path

from _check import FAILED, check, eq, git, has, run

from agent_runner import config, guide
from agent_runner.config import DEFAULTS, default_docs, settings_reference

ref = settings_reference('agent-runner')

print('every [run] and [plan] key is in the reference, with its default and its comment')
lines = ref.splitlines()
sections: dict[str, list[str]] = {}
cur = None
for s in lines:
    if re.fullmatch(r'\[\w+\]', s):
        cur = sections.setdefault(s[1:-1], [])
    elif cur is not None and s:
        cur.append(s)
for table in ('run', 'plan', 'git'):
    check(table in sections, f'[{table}] has a heading')
    for k, v in DEFAULTS[table].items():
        line = next((s for s in sections.get(table, []) if s.startswith(f'{k} = ')), '')
        check(line, f'[{table}] {k} is listed')
        if line:  # the value as written parses back to the default
            val = re.split(r'  # ', line, maxsplit=1)[0]
            eq(tomllib.loads(val)[k], v, f'[{table}] {k}: its default, as TOML')
docs = default_docs()
check(all(docs['run'][k] for k in DEFAULTS['run']), 'every [run] key has a comment to show')
check(all(docs['plan'][k] for k in DEFAULTS['plan']), 'every [plan] key too')
has(ref, r'control_ask = "2h"  # quiet this long', 'a key reads as `key = default  # what it does`')
has(ref, r'apply on the next run', 'it says when a change applies')
has(ref, r'runner\.local\.toml \(this machine only', 'and runner.toml vs runner.local.toml')
has(ref, r'take "set \[TABLE\] KEY = VALUE','and that a runner.toml change goes through take, not the main checkout')
check(not re.search(r'  # [A-Z]\d+: ', ref), 'no comment starts with a task id (C14)')
check(not re.search(r"#\s*[A-Z]\d+: ", Path(config.__file__).read_text(encoding='utf-8').split('DEFAULTS: dict', 1)[1]
                    .split('\n}\n', 1)[0]), 'C14: nor does any comment in DEFAULTS itself')

print('`agent-runner settings` prints it')
tmp = Path(tempfile.mkdtemp(prefix='agent-runner-settings-'))
git(tmp, 'init', '-q')
r = run(tmp, 'settings')
eq(r.returncode, 0, 'exits 0')
check('slots = 3' in r.stdout and '[git]' in r.stdout, 'every table')

print('the guide and the control brief recommend settings, by real keys only')
for name, text in (('GUIDE', guide.GUIDE), ('CONTROL', guide.CONTROL)):
    check('settings` prints every key' in text, f'{name} points at `settings`')
    check('recommend the one change in one line' in text, f'{name} says to recommend a setting in one line')
    check('apply on the next run' in text, f'{name} says when it applies')
    check('never as an edit in the main checkout' in text and 'take "set [table] key' in text,
          f'{name} makes a runner.toml change through take')
named = [(t, k) for t, k in re.findall(r'`\[(\w+)\] (\w+) = ', guide.SETTINGS) if t != 'table']
eq(re.findall(r'`(\w+) = ', guide.SETTINGS), [], 'every example names its table')
check(len(named) >= 6, 'the brief names several example keys', str(named))
for table, k in named:
    check(k in DEFAULTS.get(table, {}), f'example [{table}] {k} is a real key')
check('night' not in guide.SETTINGS, 'no "fewer agents at night": no such setting')

raise SystemExit(1 if FAILED else print('\nall checks passed'))
