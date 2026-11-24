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
for table in ('run', 'plan', 'git', 'models'):  # F101: [models] too
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
has(ref, r'most keys apply within seconds', 'it says when a change applies')
has(ref, r'apply on the next run: .*\[run\] web_port', 'and names the keys that wait for the next run')
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
check('guide settings' in guide.CONTROL, 'CONTROL points at `guide settings` (B98)')
for name, text in (('GUIDE', guide.GUIDE), ('guide settings', guide.CONTROL_TOPICS['settings'])):
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

print('F106a: a [models] role names a provider as <provider>:<model>')
from agent_runner.config import Config, model_providers, parse_model


def refused(fn) -> str:
    """The SystemExit message `fn` raises, '' when it raises none."""
    try:
        fn()
    except SystemExit as e:
        return str(e)
    return ''


eq(parse_model('opus'), ('claude', 'opus'), 'a bare name is claude')
eq(parse_model('claude:sonnet'), ('claude', 'sonnet'), 'claude:sonnet')
for p in ('copilot', 'codex', 'gemini'):
    eq(parse_model(f'{p}:m-1'), (p, 'm-1'), f'{p} is a built-in provider')
has(refused(lambda: parse_model('nope:m')), r"unknown provider 'nope'", 'an unknown provider is refused')
has(refused(lambda: parse_model('codex:')), r'no model', 'an empty model is refused')
has(refused(lambda: parse_model('ollama:llama3:8b')), r'local = true', 'ollama is refused while local is off')
eq(parse_model('ollama:llama3:8b', local=True), ('ollama', 'llama3:8b'), 'and allowed with local; the model keeps its colon')

provs = model_providers({'acme': {'kind': 'openai', 'url': 'https://api.acme.example/v1', 'key_env': 'ACME_KEY'},
                         'box': {'kind': 'anthropic', 'url': 'http://192.168.1.9:8080'},
                         'here': {'kind': 'openai', 'url': 'http://localhost:1234/v1'}})
eq(provs['acme'], {'kind': 'openai', 'url': 'https://api.acme.example/v1', 'key_env': 'ACME_KEY', 'local': False},
   'a custom provider: kind, url, key_env')
check(provs['box']['local'] and provs['here']['local'], 'a private address and localhost are local')
eq(parse_model('acme:gpt-x', provs), ('acme', 'gpt-x'), 'a role names a custom provider')
has(refused(lambda: parse_model('box:m', provs)), r'local = true', 'a custom provider on a private address is refused')
eq(parse_model('here:m', provs, local=True), ('here', 'm'), 'and allowed with local')
has(refused(lambda: model_providers({'x': {'kind': 'openai', 'url': 'https://a.example', 'key': 'sk-1'}})),
    r'keys never go in runner\.toml', 'a key in the config is refused')
has(refused(lambda: model_providers({'x': {'kind': 'openai', 'url': 'https://a.example'}})),
    r'key_env is missing', 'a remote provider needs key_env')
has(refused(lambda: model_providers({'x': {'kind': 'grpc', 'url': 'https://a.example', 'key_env': 'K'}})),
    r'kind must be one of openai, anthropic', 'kind is openai or anthropic')
has(refused(lambda: model_providers({'ollama': {'kind': 'openai', 'url': 'https://a.example', 'key_env': 'K'}})),
    r'built-in provider', 'a custom provider cannot shadow a built-in one')

print('F106a: [models] in runner.toml')
repo = Path(tempfile.mkdtemp(prefix='agent-runner-providers-'))
git(repo, 'init', '-q')


def load(text: str) -> Config:
    (repo / 'runner.toml').write_text(text, encoding='utf-8')
    return Config(repo)


c = load('[models]\ncode = "claude:sonnet"\nreview = "haiku"\n\n[models.kinds]\nD = "claude:haiku"\n')
eq((c.models['code'], c.models['review'], c.models['kinds']['D'], c.run['model']), ('sonnet', 'haiku', 'haiku', 'sonnet'),
   'claude:<model> runs as the bare name, and the run takes it')
check('local' not in c.models and 'providers' not in c.models and c.models_local is False and c.providers == {},
      'local and providers are settings, not roles; local is off by default')
eq(c.warnings, [], 'and neither warns as an unknown key')
custom = '[models.providers.acme]\nkind = "openai"\nurl = "https://api.acme.example/v1"\nkey_env = "ACME_KEY"\n'
c = load('[models]\ncode = "opus"\n\n' + custom)
eq(c.providers['acme']['key_env'], 'ACME_KEY', 'a custom provider is read from [models.providers.<name>]')
print('F106c: a task or fix session on another provider runs in the harness loop; Claude-only roles stay claude')
c = load('[models]\ncode = "acme:gpt-x"\nfix = "codex:gpt-6"\n\n[models.kinds]\nR = "gemini:pro"\n\n' + custom)
eq((c.models['code'], c.run['model'], c.run['fix_model'], c.models['kinds']['R']),
   ('acme:gpt-x', 'acme:gpt-x', 'codex:gpt-6', 'gemini:pro'), "another provider's model is kept as <provider>:<model>")
from agent_runner.config import harness_model
check(harness_model('acme:gpt-x', c.providers) and harness_model('gemini:pro') and not harness_model('opus')
      and not harness_model('github-copilot/m1') and not harness_model('acme:gpt-x'),
      'harness_model: another provider\'s, built in or custom (with its providers); not claude\'s nor a Pi model')
has(refused(lambda: load('[models]\ncontrol = "acme:gpt-x"\n\n' + custom)), r'control = .*runs as Claude Code',
    '[models] control runs as Claude Code itself, so another provider there is refused, saying why')
for role in ('review', 'docs', 'feed'):
    eq(load(f'[models]\n{role} = "acme:gpt-x"\n\n' + custom).models[role], 'acme:gpt-x',
       f'F406e: [models] {role} takes any provider')
    eq(config.setting_check(repo, 'models', role, 'acme:gpt-x'), '', f'and Settings takes it for {role}')
has(refused(lambda: load('[models]\ncode = "ollama:llama3"\n')), r'local = true', 'ollama refused, local off')
eq(load('[models]\nlocal = true\ncode = "ollama:llama3"\n').models['code'], 'ollama:llama3',
   'with local = true it runs (in the harness loop)')
c = load('')
eq((c.task_model('D1', 'claude:opus'), c.task_model('D1', 'gemini:pro'), c.task_model('D1', 'haiku')),
   ('opus', 'gemini:pro', 'haiku'), "a task's own claude:<model> runs bare, another provider's as <provider>:<model>")
has(refused(lambda: load('[models]\nlocal = "yes"\n')), r'local must be true or false', 'local is a boolean')

print('F166: every setting has a name, a description, a group and a home, in plain words')
from agent_runner import setting_words as W
every = {f'{t}.{k}' for t, keys in DEFAULTS.items() for k in keys}
eq(set(W.WORDS) ^ every, set(), 'a line for each setting, and none for another')
groups = {g[0] for g in W.GROUPS}
for at, (group, name, desc) in W.WORDS.items():
    t, k = at.split('.')
    check(name and len(name) <= 34 and '_' not in name and name != k, f'{at} has a plain name', name)
    check(desc.endswith('.') and 20 <= len(desc) <= 130 and '`' not in desc and '—' not in desc, f'{at} has a short description', desc)
    check(len(re.findall(r'[.:] ', desc)) >= 1, f'{at} says what changes when it is moved', desc)
    check(group in groups and W.home(t, k) in (W.DEVICE, W.EVERYONE), f'{at} has a group and a home')
eq(len({n for _, n, _ in W.WORDS.values()} - {'Chats'}), len(W.WORDS) - 1, 'no two settings share a name')
for table in (W._HOMES, W._PARENTS, W._CHOICES, W._UNITS):
    eq(set(table) - every, set(), 'the other tables name real settings only')
for at, words in W._CHOICES.items():
    t, k = at.split('.')
    for v in words:
        val = {'true': True, 'false': False}.get(v, v)
        val = int(v) if v.isdigit() else __import__('json').loads(v) if v.startswith('{') else val
        eq(config.setting_problem(t, k, val), '', f'{at}: {v} is a value it takes')
page = [at for at, w in W.WORDS.items() if W._WHERE[w[0]] == 'page']
check(20 <= len(page) <= 28, 'about 24 everyday settings', len(page))

print('F193: Release by itself shows only while Manage releases is on, and its value is kept while it is off')
eq((W.parent('run', 'auto_release'), W.parent('run', 'releases')), ('run.releases', ''), 'it hangs on Manage releases, which always shows')
for on in (True, False):
    load(f'[run]\nreleases = {str(on).lower()}\nauto_release = {{ every = 10 }}\n')
    rows = {k['key']: k for t in config.settings_snapshot(repo)['tables'] if t['table'] == 'run' for k in t['keys']}
    eq((rows['releases']['value'], rows['auto_release']['value'], rows['auto_release']['parent']), (on, {'every': 10}, 'run.releases'),
       f'the settings answer with releases {on}')

print('F166: the settings that were cut: an old file still works, and is told')
CUT = {'comment_policy': '"minimal"', 'idle': '9', 'stall': '9', 'pause': '9', 'merge_ahead': 'false', 'fix_timeout': '9',
       'control_idle_quick': 'false', 'control_idle_talked': '"1d"', 'control_open': '["x"]'}
for k, v in {**CUT, 'model': '"sonnet"', 'fix_model': '"haiku"', 'sessions': '"each"'}.items():
    check(k not in DEFAULTS['run'], f'[run] {k} is cut')
    c = load(f'[run]\n{k} = {v}\n')
    check(len(c.warnings) == 1 and f'[run] {k}' in c.warnings[0], f'an old {k} loads, with a note', c.warnings)
c = load('[run]\n' + ''.join(f'{k} = {v}\n' for k, v in CUT.items()))
eq({k: c.run[k] for k in config.FIXED}, config.FIXED, 'the fixed ones keep their values')
eq((c.run['idle'], c.run['stall'], c.run['pause'], c.run['merge_ahead'], c.run['fix_timeout']), (30, 1200, 60, True, 1800), "today's values")
c = load('[run]\nmodel = "sonnet"\nfix_model = "haiku"\n')
eq((c.models['code'], c.models['fix']), ('sonnet', 'haiku'), 'model and fix_model move to [models] code and fix')
for text, want in (('', 'open'), ('remote_slots = true\n', 'open'), ('sessions = "each"\n', 'open'),
                   ('sessions = "each"\nremote_slots = true\n', 'always'), ('sessions = "one"\nremote_slots = true\n', 'open'),
                   ('remote_slots = "always"\n', 'always'), ('remote_slots = "open"\n', 'open')):
    eq(load('[run]\n' + text).run['remote_slots'], want, f'slots in the Claude apps: {text!r}')
(repo / 'runner.local.toml').write_text('[run]\nremote_slots = true\nmodel = "haiku"\n', encoding='utf-8')
eq(load('[run]\nsessions = "each"\n').run['remote_slots'], 'always', 'one in each file')
snap = config.settings_snapshot(repo)
row = next(k for t in snap['tables'] for k in t['keys'] if k['key'] == 'remote_slots')
eq((row['value'], row['device'], row['name']), ('always', 'always', 'Slots in the Claude apps'), 'the page shows the same')
config.save_local_setting(repo, 'models', 'code', unset=True)
check('model' not in (repo / 'runner.local.toml').read_text(encoding='utf-8'), 'Reset takes the old key out too')
config.save_local_setting(repo, 'run', 'remote_slots', 'open')
eq(load('[run]\nsessions = "each"\n').run['remote_slots'], 'open', 'a value set on the page wins over the old keys')
(repo / 'runner.local.toml').unlink()
has(refused(lambda: load('[run]\nremote_slots = "yes"\n')), r"must be 'open' or 'always'", 'another value is refused')
(repo / 'runner.local.toml').write_text('slots = 2\n', encoding='utf-8')
has(config.settings_snapshot(repo)['unknown'][0]['why'], r'no \[run\] line is above it', 'a limit with no [run] line above it says so')

print('B764a: a wrong [run] agent is refused, and nothing is written')
from unittest import mock
from agent_runner import state as S, ui_model as U
proj = Path(tempfile.mkdtemp(prefix='agent-runner-agent-'))
git(proj, 'init', '-q')
(proj / 'plan').mkdir()
(proj / 'plan' / 'TODO.md').write_text('# TODO\n', encoding='utf-8')
(proj / '.gitignore').write_text('.runner/\nrunner.local.toml\n', encoding='utf-8')
toml, mine = proj / 'runner.toml', proj / 'runner.local.toml'
toml.write_text('[run]\nslots = 2\n', encoding='utf-8')
mine.write_text('[run]\nslots = 4\n', encoding='utf-8')
wrapper = proj / 'my-claude'
wrapper.write_text('#!/bin/sh\n', encoding='utf-8')
wrapper.chmod(0o755)
git(proj, 'add', '-A')
git(proj, 'commit', '-qm', 'start')
S.init(proj)
HINT = r'\[models\].*"<provider>:<model>"'
before = toml.read_bytes(), mine.read_bytes()
for save in (U.setting_device, U.setting_project):
    for v, why in (('pi', HINT), ('/opt/bin/Pi', HINT), ('copilot', HINT), ('copilot.exe', HINT), ('', 'is empty'),
                   ('  ', 'is empty'), (5, 'must be text')):
        r = save('run', 'agent', v)
        eq((r['ok'], (toml.read_bytes(), mine.read_bytes())), (False, before), f'{save.__name__} refuses {v!r}')
        has(r['out'], why, 'and says why')
for v in ('nosuchagent-b764a', str(proj / 'gone' / 'claude'), str(proj / 'plan'), 'claude-b764a --x'):
    r = U.setting_device('run', 'agent', v)
    eq((r['ok'], mine.read_bytes()), (False, before[1]), f'a device save refuses {v!r}')
    has(r['out'], 'no such command on PATH', 'and says why')
for v in (str(wrapper), './my-claude'):
    r = U.setting_device('run', 'agent', v)
    eq((r['ok'], tomllib.loads(mine.read_text(encoding='utf-8'))['run']['agent']), (True, v), f'a wrapper that exists saves: {v}')
with mock.patch.dict('os.environ', PATH=f'{proj}{__import__("os").pathsep}{__import__("os").environ["PATH"]}'):
    eq(U.setting_device('run', 'agent', 'my-claude')['ok'], True, 'and a command on PATH')
eq(U.setting_reset('run', 'agent')['ok'], True, 'a reset is never refused')
for v in (str(wrapper), 'nosuchagent-b764a'):
    r = U.setting_project('run', 'agent', v)
    eq((r['ok'], tomllib.loads(toml.read_text(encoding='utf-8'))['run']['agent']), (True, v), f'a project save takes {v}: other machines share it')

raise SystemExit(1 if FAILED else print('\nall checks passed'))
