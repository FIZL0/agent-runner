"""F21: the person's wording: a global voice file and a project one, kept by `agent-runner voice`, carried by every
control session's brief and the runner feed's system prompt; `[run] voice` moves the global file and `[run]
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
voice.add(c, 'no task ids', project=True)
eq(voice.rules(d / '.runner' / 'voice.md'), ['no task ids'], '--project: the project file')
shown = voice.show(c)
check(shown.index('say agent') < shown.index('no task ids'), 'both shown, the project last', shown)
check('wins where it disagrees' in shown, 'the project lines win', shown)
out = voice.forget(c, 'TASK IDS')
check('removed from' in out and 'no task ids' in out, 'forget removes the line, naming the file', out)
eq(voice.rules(d / '.runner' / 'voice.md'), [], 'and it is gone')
check('no line holds' in voice.forget(c, 'nothing like it'), 'forget of nothing says so')

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
check(b.index('call it a slot') < b.index('call it an agent'), 'the project lines come after the global ones')
check('its lines win where they disagree' in b and 'wins where it disagrees' in b,
      'and the brief says the project lines win')

print('the feed prompt carries the wording')
rb = guide.RUNNER_BRIEF.format(cmd='agent-runner', repo='demo', answer='')
f = voice.feed(rb, c)
check(f.startswith(rb.rstrip()) and '- call it an agent, not a slot' in f and '- shorter' in f,
      'the feed system prompt ends with the wording')
check('repeated exactly' in f, 'monitor lines still repeat exactly')
GLOBAL.unlink()
eq(voice.feed(rb, cfg(repo())), rb, 'no wording: the feed prompt is unchanged')

print('config: the defaults are documented')
from agent_runner.config import DEFAULTS, default_docs  # noqa: E402
eq(DEFAULTS['run'].get('voice'), '', '[run] voice defaults to the global file')
eq(DEFAULTS['run'].get('voice_learn'), 'ask', '[run] voice_learn defaults to ask')
check('off' in default_docs()['run']['voice_learn'], 'its comment names the modes')
for v, want in [('ask', 'ask'), ('off', 'off'), (False, 'off'), ('OFF', 'off'), ('nonsense', 'ask')]:
    eq(voice.learn_mode(cfg(d, voice_learn=v)), want, f'voice_learn = {v!r}')

print('the real commands: voice, control --brief and the feed argv')
d2 = repo()
r = run(d2, 'voice', 'add', 'say agent, not slot')
check(r.returncode == 0 and 'added to' in r.stdout, '`voice add` writes the global file', r.stderr)
r = run(d2, 'voice', 'add', '--project', 'no task ids')
check(r.returncode == 0 and (d2 / '.runner' / 'voice.md').exists(), '`voice add --project` writes .runner/voice.md',
      r.stderr)
r = run(d2, 'voice', 'show')
check('say agent, not slot' in r.stdout and 'no task ids' in r.stdout, '`voice show` prints both', r.stdout)
b = run(d2, 'control', '--brief').stdout
check('- say agent, not slot' in b and '- no task ids' in b, 'control --brief carries both files', b[-500:])
b = run(repo('[run]\nvoice_learn = "off"\n'), 'control', '--brief').stdout
check("The person's wording" in b and 'Learned' not in b, 'voice_learn = "off" in runner.toml: no learned offer')
r = run(d2, 'voice', 'forget', 'task ids')
check('removed from' in r.stdout, '`voice forget` removes it', r.stdout)

from agent_runner import feed as F, runner as R  # noqa: E402
R.init(d2)
with mock.patch.object(F, 'remote_on', lambda: True, create=True), mock.patch.dict(R.C.run, {'agent': 'claude'}):
    fa = R.feed_argv()
system = fa[fa.index('--system-prompt') + 1]
check('- say agent, not slot' in system, 'the feed is started with the wording in its system prompt', system[-300:])

raise SystemExit(1 if FAILED else print('\nall checks passed'))
