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
eq(parse_model('nope:m', backend='pi'), ('claude', 'nope:m'), 'on Pi an unknown prefix is Pi\'s own model syntax')
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

print('F106a: in runner.toml, until the loop engine (F106c) only claude runs')
repo = Path(tempfile.mkdtemp(prefix='agent-runner-providers-'))
git(repo, 'init', '-q')


def load(text: str) -> Config:
    (repo / 'runner.toml').write_text(text, encoding='utf-8')
    return Config(repo)


c = load('[models]\ncode = "claude:sonnet"\nreview = "haiku"\n\n[models.kinds]\nD = "claude:haiku"\n')
eq((c.models['code'], c.models['review'], c.models['kinds']['D'], c.run['model']), ('sonnet', 'haiku', 'haiku', 'sonnet'),
   'claude:<model> runs as the bare name, [run] model follows')
check('local' not in c.models and 'providers' not in c.models and c.models_local is False and c.providers == {},
      'local and providers are settings, not roles; local is off by default')
eq(c.warnings, [], 'and neither warns as an unknown key')
custom = '[models.providers.acme]\nkind = "openai"\nurl = "https://api.acme.example/v1"\nkey_env = "ACME_KEY"\n'
c = load('[models]\ncode = "opus"\n\n' + custom)
eq(c.providers['acme']['key_env'], 'ACME_KEY', 'a custom provider is read from [models.providers.<name>]')
has(refused(lambda: load('[models]\nreview = "acme:gpt-x"\n\n' + custom)), r'not supported yet.*F106c',
    'a role on a non-claude provider is refused at start, saying why')
has(refused(lambda: load('[models.kinds]\nR = "gemini:pro"\n')), r'\[models\.kinds\] R .*not supported yet',
    'a kind on one too')
has(refused(lambda: load('[models]\ncode = "ollama:llama3"\n')), r'local = true', 'ollama refused, local off')
has(refused(lambda: load('[models]\nlocal = true\ncode = "ollama:llama3"\n')), r'not supported yet',
    'with local = true it passes the local check (and waits for F106c)')
has(refused(lambda: load('[models]\nlocal = "yes"\n')), r'local must be true or false', 'local is a boolean')

raise SystemExit(1 if FAILED else print('\nall checks passed'))
