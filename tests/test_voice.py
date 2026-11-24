"""F21: the person's wording: a global voice file and a project one, kept by `agent-runner voice`, carried by every
control session's brief; `[run] voice` moves the global file and `[run]
voice_learn` (ask | off) fits the brief."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from _check import FAILED, check, eq, git, run

# never the person's real ~/.config/agent-runner/voice.md: this process and every `run` it starts
XDG = Path(tempfile.mkdtemp(prefix='agent-runner-voice-xdg-'))
os.environ['XDG_CONFIG_HOME'] = str(XDG)
GLOBAL = XDG / 'agent-runner' / 'voice.md'

from agent_runner import guide, voice  # noqa: E402


def repo(toml: str = '') -> Path:
    d = Path(tempfile.mkdtemp(prefix='agent-runner-voice-'))
    git(d, 'init', '-q')
    (d / '.gitignore').write_text('.runner/\n')
    (d / 'README.md').write_text('demo\n')
    if toml:
        (d / 'runner.toml').write_text(toml)
    git(d, 'add', '-A')
    git(d, 'commit', '-qm', 'start')
    return d


def cfg(root: Path, **run_keys):
    return SimpleNamespace(root=root, run={'notes': '.runner', **run_keys})


def clear():
    for p in (GLOBAL,):
        if p.exists():
            p.unlink()


print('where the files are')
d = repo()
c = cfg(d)
eq(voice.global_path(c), GLOBAL, 'global: $XDG_CONFIG_HOME/agent-runner/voice.md')
eq(voice.project_path(c), d / '.runner' / 'voice.md', 'project: <repo>/.runner/voice.md')
eq(voice.global_path(cfg(d, voice='my/words.md')), d / 'my' / 'words.md', '[run] voice moves it (relative: the repo)')
eq(voice.global_path(cfg(d, voice='~/w.md')), Path.home() / 'w.md', '[run] voice expands ~')
with mock.patch.dict(os.environ, {'XDG_CONFIG_HOME': ''}):
    eq(voice.global_path(c), Path.home() / '.config' / 'agent-runner' / 'voice.md', 'no XDG: ~/.config/agent-runner')

print('add, show, forget')
clear()
eq(voice.text(c), '', 'no file: no wording')
check('No wording yet' in voice.show(c), 'show says there is none')
out = voice.add(c, 'say agent, not slot')
check('added to' in out and 'voice.md' in out, 'add names the file it went to', out)
eq(voice.rules(GLOBAL), ['say agent, not slot'], 'one line in the global file; the heading is not a rule')
check('already' in voice.add(c, 'Say agent, not slot'), 'the same line twice is kept once')
out = voice.add(c, 'no task ids', project=True)
eq(voice.rules(d / '.runner' / 'voice.md'), ['say agent, not slot', 'no task ids'],
   '--project: the project file, started as a copy of the global lines')
check('1 lines of' in out, 'add says it copied them', out)
shown = voice.show(c)
check('this project' in shown and 'read instead of' in shown, 'show: the project file, read instead', shown)
voice.add(c, 'no task ids in titles', project=True)
out = voice.forget(c, 'task ids')
check('nothing removed' in out and 'no task ids in titles' in out, 'several lines hold it: none removed, listed', out)
eq(len(voice.rules(d / '.runner' / 'voice.md')), 3, 'and all are kept')
out = voice.forget(c, 'NO TASK IDS')
check('removed from' in out and '.runner/voice.md' in out, 'an exact match removes that one, naming the file', out)
eq(voice.rules(d / '.runner' / 'voice.md'), ['say agent, not slot', 'no task ids in titles'], 'only that line')
check('no line' in voice.forget(c, 'nothing like it'), 'forget of nothing says so')
check('instead' in voice.add(c, 'shorter'), 'a global add says this project reads its own file instead')
(d / '.runner' / 'voice.md').unlink()

print('the control brief carries the wording; the project file overrides the global one')
clear()
control = guide.CONTROL.format(cmd='agent-runner', repo='demo', needs='Needs you', watch='', answer='', log='run.log')
b = voice.fit(control, 'agent-runner', c)
check("The person's wording" in b and 'agent-runner voice add' in b, 'the brief says how to grow it')
check('No wording yet' in b, 'no file: it says there is none')
check('Learned' in b and 'Add: say agent, not slot? yes' in b, 'voice_learn = ask: the learned offer')
check('Learned' not in voice.fit(control, 'agent-runner', cfg(d, voice_learn='off')), 'voice_learn = off: none')
check('show my wording' in b and 'voice forget' in b, 'show my wording, forget X')
GLOBAL.parent.mkdir(parents=True, exist_ok=True)
GLOBAL.write_text('# Voice\n\n- call it a slot\n- shorter\n', encoding='utf-8')
b = voice.fit(control, 'agent-runner', c)
check('- call it a slot' in b and '- shorter' in b, 'the global lines are in the brief', b[-400:])
(d / '.runner').mkdir(exist_ok=True)
(d / '.runner' / 'voice.md').write_text('- call it an agent, not a slot\n', encoding='utf-8')
b = voice.fit(control, 'agent-runner', c)
check('call it an agent' in b and '- call it a slot' not in b and '- shorter' not in b,
      'the project file overrides the global one: only its lines are in the brief', b[-400:])
check('read instead of the global file' in b, 'and the brief says so')

print("the task agents' brief carries the wording")
s = voice.slot('the slot brief', c)
check(s.startswith('the slot brief') and '- call it an agent, not a slot' in s and 'commit message' in s,
      'for the commit message status and since show', s)
check('- shorter' in voice.slot('the slot brief', cfg(repo())), 'another repo: the global lines')

GLOBAL.unlink()
eq(voice.slot('x', cfg(repo())), 'x', "no wording: the task agents' brief is unchanged")

print('config: the defaults are documented')
from agent_runner.config import DEFAULTS, default_docs  # noqa: E402
eq(DEFAULTS['run'].get('voice'), '', '[run] voice defaults to the global file')
eq(DEFAULTS['run'].get('voice_learn'), 'ask', '[run] voice_learn defaults to ask')
check('off' in default_docs()['run']['voice_learn'], 'its comment names the modes')
for v, want in [('ask', 'ask'), ('off', 'off'), (False, 'off'), ('OFF', 'off'), ('nonsense', 'ask')]:
    eq(voice.learn_mode(cfg(d, voice_learn=v)), want, f'voice_learn = {v!r}')

print('the real commands: voice and control --brief')
d2 = repo()
r = run(d2, 'voice', 'add', 'say agent, not slot')
check(r.returncode == 0 and 'added to' in r.stdout, '`voice add` writes the global file', r.stderr)
r = run(d2, 'voice', 'add', '--project', 'no task ids')
check(r.returncode == 0 and (d2 / '.runner' / 'voice.md').exists(), '`voice add --project` writes .runner/voice.md',
      r.stderr)
r = run(d2, 'voice', 'show')
check('say agent, not slot' in r.stdout and 'no task ids' in r.stdout, '`voice show` prints the project file',
      r.stdout)
b = run(d2, 'control', '--brief').stdout
check('- say agent, not slot' in b and '- no task ids' in b, 'control --brief carries the wording', b[-500:])
b = run(repo(), 'control', '--brief').stdout
check('- say agent, not slot' in b and '- no task ids' not in b, 'another repo: the global file only', b[-500:])
b = run(repo('[run]\nvoice_learn = "off"\n'), 'control', '--brief').stdout
check("The person's wording" in b and 'Learned' not in b, 'voice_learn = "off" in runner.toml: no learned offer')
r = run(d2, 'voice', 'forget', 'task ids')
check('removed from' in r.stdout, '`voice forget` removes it', r.stdout)

from agent_runner import runner as R  # noqa: E402
R.init(d2)
env = {**os.environ, 'AGENT_RUNNER_REPO': str(d2)}
env.pop('AGENT_RUNNER', None)
check(run(d2, 'plan', 'add', 'F', 'add a thing | files: a.py', env=env).returncode == 0, 'a task to brief')
p = R.prompt_for('F1', 1, 1, d2, 'main')
check('- say agent, not slot' in p and 'commit message' in p, "the task agent's prompt carries the wording", p[-300:])

raise SystemExit(1 if FAILED else print('\nall checks passed'))
