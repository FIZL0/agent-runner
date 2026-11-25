"""F448a: every key of Settings' 'file' groups has a save that works or a reason, and what would stop the run or lose the
plan is refused with nothing changed."""
from __future__ import annotations

import os
import shutil
import tempfile
import tomllib
from pathlib import Path
from unittest import mock

from _check import FAILED, check, eq, git, has

from agent_runner import config as CF, plat, setting_checks as SC, setting_words as W, state as S, ui_model as U

os.environ.pop('AGENT_RUNNER_HOME', None)  # it wins over [run] home, which is a folder of this test's own below
top = Path(tempfile.mkdtemp(prefix='agent-runner-checks-')).resolve()
repo, far = top / 'proj', top / 'far'
repo.mkdir()
git(repo, 'init', '-q')
(repo / 'plan' / 'tasks').mkdir(parents=True)
TODO = '# TODO\n\n### Next\n\n- [ ] **F1** one\n'
(repo / 'plan' / 'TODO.md').write_text(TODO, encoding='utf-8')
(repo / 'plan' / 'DONE.md').write_text('# DONE\n', encoding='utf-8')
(repo / 'plan' / 'tasks' / 'F1.md').write_text('long form\n', encoding='utf-8')
(repo / '.gitignore').write_text('.runner/\nrunner.local.toml\nbuild/\n', encoding='utf-8')
(repo / 'RULES.md').write_text('rules\n', encoding='utf-8')
(repo / 'prompt.md').write_text('do {tid}\n', encoding='utf-8')
(repo / 'bad-prompt.md').write_text('do {tid\n', encoding='utf-8')
toml, mine = repo / 'runner.toml', repo / 'runner.local.toml'
START = f'[run]\nhome = "{(top / "runs").as_posix()}"\n'
toml.write_text(START, encoding='utf-8')
git(repo, 'add', '-A')
git(repo, 'commit', '-qm', 'start')
git(top, 'clone', '-q', '--bare', str(repo), str(far))
git(repo, 'remote', 'add', 'origin', str(far))
S.init(repo)
U.SETTING_SETTLE = 0.0
head = lambda: git(repo, 'rev-parse', 'HEAD')  # noqa: E731


def raw(f: Path = toml) -> dict:
    return tomllib.loads(f.read_text(encoding='utf-8')) if f.exists() else {}


def refused(table: str, key: str, v, why: str, say: str = '') -> None:
    was = toml.read_bytes(), raw(mine), head()
    for save in (U.setting_project, U.setting_device):
        r = save(table, key, v)
        eq((r['ok'], (toml.read_bytes(), raw(mine), head())), (False, was), f'{save.__name__} refuses [{table}] {key} = {v!r} {say}')
        has(r['out'], why, 'and says why')


print('every key of the file groups: a save that works, or a reason')
groups = {g[0] for g in W.GROUPS if g[2] == 'file'}
keys = [tuple(at.split('.')) for at, w in W.WORDS.items() if w[0] in groups]
# the plan's copy, and a plan repository that has it, for the moves
shutil.copytree(repo / 'plan', top / 'plan2')
planrepo = top / 'planrepo'
shutil.copytree(repo / 'plan', planrepo)
git(planrepo, 'init', '-q')
git(planrepo, 'add', '-A')
git(planrepo, 'commit', '-qm', 'plan')
VALUES: dict = {
    'run.test': 'true', 'run.done_test': 'for t in a b; do echo "$t"; done', 'run.test_since': 'echo {base}', 'run.retest': 'echo {names}',
    'run.build': 'true && true', 'run.docs_check': 'X=1 true', 'run.before_start': 'true', 'run.on_exit': 'true', 'run.slot_clean': 'true',
    'run.command': 'sh', 'run.tools': {'phone': {'check': 'true', 'label': 'a'}}, 'run.checks': {'vm': {'cmd': 'true'}},
    'run.join': {'*.log': 'cat {ours} {theirs}'}, 'plan.brief_extra': 'echo {id}', 'plan.outline': 'echo {file}',
    'run.home': str(top / 'runs2'), 'run.links': ['data'], 'run.copies': ['a.cfg'], 'run.slot_env': ['PORT=80{n}'], 'run.pass_env': ['HOME'],
    'run.shared_files': ['a.py'], 'run.joinable': ['*.log'], 'git.master_branch': 'main', 'git.push': False,
    'plan.dir': str(top / 'plan2'), 'plan.repo': str(planrepo), 'plan.journal': 'journal', 'plan.journal_layout': 'id',
    'run.untested': ['*.md', '!a.md'], 'run.docs_files': ['*.md'], 'run.findings': ['research/**'],
    'run.failures': r'^FAIL (\w+)', 'run.flaky': r'flaky: (\w+)', 'run.suspect': 'needs a human', 'run.not_attempt': '^spec {id}',
    'run.rules': 'RULES.md', 'run.prompt': 'prompt.md', 'run.prompt_extra': 'You are {tid}.', 'run.voice': 'voice.md',
    'plan.glossary': 'WORDS.md', 'plan.lookup': ['plan/*.md'], 'plan.kinds': {'F': 'feature'},
    'models.providers': {'acme': {'kind': 'openai', 'url': 'https://a.example', 'key_env': 'K'}},
}
for t, k in keys:
    at = f'{t}.{k}'
    for side, f in (('project', toml), ('device', mine)):
        if why := SC.locked(repo, t, k):
            eq(at, 'run.notes', f'{at} cannot be changed here')
            check(why.count('. ') == 0 and len(why) < 150, 'one sentence says why', why)
            has(U.setting_project(t, k, '.logs')['out'], 'log folder', 'and the save says it')
            continue
        save = U.setting_project if side == 'project' else U.setting_device
        r = save(t, k, VALUES[at])
        eq((r['ok'], raw(f).get(t, {}).get(k)), (True, VALUES[at]), f'{at} saves for {side}')
        if not r['ok']:
            print('   ', r['out'])
        if (t, k) == ('run', 'home') and side == 'project':
            eq(S.SLOTS_DIR, top / 'runs2', 'and this page goes by it')
        r = U.setting_project(t, k, unset=True) if side == 'project' else U.setting_reset(t, k)
        eq((r['ok'], k in raw(f).get(t, {})), (True, False), f'{at}: its reset for {side}')
        if not r['ok']:
            print('   ', r['out'])
        if (t, k) == ('run', 'home') and side == 'project':
            eq(U.setting_project('run', 'home', str(top / 'runs'))['ok'], True, 'home is put back')
check(not [at for at in W._WARNS if tuple(at.split('.')) not in keys], 'a warning names a key of these groups')
for at, s in W._WARNS.items():
    check(s.endswith('.') and '. ' not in s and len(s) <= 130, f'{at}: its warning is a sentence', s)
row = {(t['table'], k['key']): k for t in U.settings()['tables'] for k in t['keys']}
check(row['run', 'test']['warn'] == W._WARNS['run.test'] and not row['run', 'slots']['warn'], 'the page gets the warnings')
check(row['run', 'notes']['locked'] and not row['plan', 'dir']['locked'], 'and why a key is not changed there')

print('commands')
refused('run', 'test', '   ', 'only spaces')
if not plat.WINDOWS:  # sh reads it
    refused('run', 'test', 'if true', 'shell can read')
    refused('run', 'before_start', 'no-such-prog-f448a --x', 'no command no-such-prog-f448a')
    refused('run', 'build', './gone.sh', r'no command \./gone\.sh')
    refused('run', 'tools', {'p': {'check': 'echo "'}}, 'shell can read')
    refused('run', 'checks', {'p': {'cmd': '('}}, 'shell can read')
refused('plan', 'brief_extra', 'echo {name}', r'\{id\}')
refused('plan', 'outline', 'awk {print} {file}', 'written')
refused('run', 'join', {'*.a': 'echo {mine}'}, 'placeholders')
refused('run', 'join', {'*.a': 5}, 'command')

print('patterns')
for k in ('failures', 'flaky', 'suspect', 'not_attempt'):
    refused('run', k, '(x', 'not a regular expression')
    refused('run', k, 'x*', 'match everything')
refused('run', 'failures', '(a)(b)', '2 groups')
refused('run', 'untested', ['*.md', ' '], 'empty entry')
refused('run', 'docs_files', ['!'], 'empty entry')

print('files, folders, variables')
for v in ('/etc/hosts', '../x', '~/x', '', '.', '.git/config'):
    refused('run', 'links', [v], 'empty entry|inside the project')
refused('run', 'slot_env', ['PORT'], 'NAME=value')
refused('run', 'slot_env', ['A={x}'], 'written twice')
refused('run', 'slot_env', ['AGENT_RUNNER_HOME=x'], 'the runner itself')
refused('run', 'pass_env', ['A B'], 'name of a variable')
refused('git', 'push', 'nowhere', 'no remote nowhere')
refused('git', 'push', '', 'turn it off')
refused('run', 'rules', 'gone.md', 'no file gone.md')
refused('run', 'prompt', 'gone.md', 'no file gone.md')
refused('run', 'prompt', 'bad-prompt.md', 'brace')
refused('run', 'prompt_extra', 'a { b', 'brace')
refused('run', 'voice', 'plan/TODO.md', 'write over')
refused('plan', 'glossary', 'plan/DONE.md', 'write over')
refused('plan', 'glossary', 'plan', 'a folder')
refused('plan', 'journal', '.', 'whole project')
refused('plan', 'journal', 'RULES.md', 'a file')
refused('plan', 'lookup', ['/abs/*.md'], 'not a file pattern')
refused('plan', 'lookup', ['plan'], 'a folder')
refused('plan', 'kinds', {'F1': 'x'}, 'letters')
refused('run', 'voice', '~nobody-f448a/x.md', 'voice')

print('a provider that a role still names stays; moving the role in the same Save lets it go')
eq(U.setting_project('models', 'providers', VALUES['models.providers'])['ok'], True, 'a provider')
eq(U.setting_project('models', 'code', 'acme:m')['ok'], True, 'a role on it')
for out in (U.setting_project('models', 'providers', {}), U.setting_project('models', 'providers', unset=True)):
    eq(out['ok'], False, 'it cannot go')
    has(out['out'], 'acme', 'and it says which')
eq(U.settings_save([{'table': 'models', 'key': 'providers', 'side': 'project', 'unset': True},
                    {'table': 'models', 'key': 'code', 'side': 'project', 'unset': True}])['ok'], True, 'both at once')

print('where the plan and the worktrees are')
refused('plan', 'dir', str(top / 'empty'), 'does not have the same TODO.md')
(top / 'plan2' / 'TODO.md').write_text(TODO + '- [ ] **F2** two\n', encoding='utf-8')
refused('plan', 'dir', str(top / 'plan2'), 'TODO.md')
(top / 'plan2' / 'TODO.md').write_text(TODO, encoding='utf-8')
(top / 'plan2' / 'tasks' / 'F1.md').unlink()
refused('plan', 'dir', str(top / 'plan2'), r'tasks/F1\.md')
shutil.copy(repo / 'plan' / 'tasks' / 'F1.md', top / 'plan2' / 'tasks' / 'F1.md')
refused('plan', 'dir', 'RULES.md', 'a file')
refused('plan', 'dir', '', 'empty')
shutil.copytree(repo / 'plan', repo / 'build' / 'plan')
refused('plan', 'dir', 'build/plan', 'not committed')
refused('plan', 'repo', str(top / 'nowhere'), 'cannot be cloned')
refused('plan', 'repo', '--upload-pack=x', 'not a git address')
refused('plan', 'repo', str(far), 'does not have the same TODO.md')
refused('run', 'home', '', 'empty')
refused('run', 'home', str(top), 'holds the project')
refused('run', 'home', str(repo / 'trees'), 'does not ignore')
refused('run', 'home', str(repo / 'RULES.md'), 'RULES.md')
other = top / 'other'
(other / 's1').mkdir(parents=True)
refused('run', 'home', str(other), "not one of this project's worktrees")
git(repo, 'worktree', 'add', '-q', '-b', 'task/F1', str(top / 'runs' / 's1'))
refused('run', 'home', str(top / 'runs2'), 'F1 is still in a worktree')
refused('plan', 'dir', str(top / 'plan2'), 'F1 is still in a worktree')
git(repo, 'worktree', 'remove', str(top / 'runs' / 's1'))
with mock.patch.object(SC, '_run_up', lambda root: True):
    for t, k in SC.PLAN_AT:
        refused(t, k, VALUES[f'{t}.{k}'], 'while the run is up')
        check(SC.locked(repo, t, k), f'the page says so of [{t}] {k}')
eq(SC._run_up(repo), False, 'no run is up')
lock = plat.lock(S.C.notes('run.lock'))
eq(SC._run_up(repo), True, 'a held run.lock is one')
lock.close()
was = toml.read_bytes()
r = U.settings_save([{'table': 'plan', 'key': 'dir', 'side': 'project', 'value': str(top / 'plan2')},
                     {'table': 'run', 'key': 'home', 'side': 'project', 'value': str(top / 'runs2')}])
eq((r['ok'], len(r['bad']), raw()['plan']['dir']), (False, 1, str(top / 'plan2')), 'two moves in one Save: the first only')
has(r['out'], 'one setting at a time', 'and it says why')
eq(S.C.plan_dir, top / 'plan2', 'this page reads the plan there')
(top / 'plan2' / 'TODO.md').write_text(TODO + '- [ ] **F2** two\n', encoding='utf-8')
r = U.setting_project('plan', 'dir', unset=True)
eq((r['ok'], raw()['plan']['dir']), (False, str(top / 'plan2')), 'a reset that loses a task is refused')
has(r['out'], 'tasks would be lost', 'and says why')

print('a table written as sections keeps the rest of them')
TEXT = '''[run]
slots = 2

# the phone
[run.tools.phone]
check = "true"  # free?
label = "A"  # its name

[[run.tools.phone.buttons]]
label = "go"
cmd = "true"

[run.tools.vm]
check = "x" # vm

[run.join]
"a.b" = "one"  # keep

[git]
push = "origin"
'''
BASE = tomllib.loads(TEXT)['run']


def edited(key: str, v=None, unset: bool = False) -> str:
    out = CF.toml_edit(TEXT, 'run', key, v, unset)
    eq(tomllib.loads(out)['run'].get(key), None if unset else v, f'{key} = {v!r} reads back')
    return out


out = edited('tools', {**BASE['tools'], 'phone': {**BASE['tools']['phone'], 'label': 'B'}})
eq(out, TEXT.replace('label = "A"', 'label = "B"'), 'one value: only its line changes')
out = edited('tools', {'vm': BASE['tools']['vm']})
check('# the phone' in out and 'check = "x" # vm' in out and 'buttons' not in out, 'a tool goes with its buttons', out)
out = edited('tools', {**BASE['tools'], 'new one': {'check': 'y', 'buttons': [{'label': 'l', 'cmd': 'c'}]}})
check(all(l in out for l in TEXT.splitlines()) and '[run.tools."new one"]' in out, 'a new tool is a section of its own', out)
edited('tools', {**BASE['tools'], 'phone': {'check': 'true', 'label': 'A', 'buttons': [{'label': 'other', 'cmd': 'true'}]}})
edited('tools', {**BASE['tools'], 'phone': {'check': 'true'}})
out = edited('join', {'a.b': 'two', 'c': 'three'})
check('"a.b" = "two"  # keep\nc = "three"' in out, 'an entry changes in place, and one is added after it', out)
for key in ('tools', 'join'):
    edited(key, {})
    edited(key, unset=True)
    check('[git]\npush = "origin"' in edited(key, unset=True), 'the tables after it stay')
wrapped = TEXT.replace('[run', '[agent-runner.run').replace('[[run', '[[agent-runner.run').replace('[git]', '[agent-runner.git]')
eq(tomllib.loads(CF.toml_edit(wrapped, 'run', 'join', {'z': 'q'}))['agent-runner']['run']['join'], {'z': 'q'}, 'under [agent-runner] too')

raise SystemExit(1 if FAILED else print('\nall checks passed'))
