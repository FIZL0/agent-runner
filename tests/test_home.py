"""[run] home: where a project's worktrees and plan clone live, its override, and the pre-0.13 places."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from _check import FAILED, eq, git, has

from agent_runner.config import Config

tmp = Path(tempfile.mkdtemp(prefix='agent-runner-home-'))
repo = tmp / 'proj'
repo.mkdir()
git(repo, 'init', '-q')
git(repo, 'commit', '-q', '--allow-empty', '-m', 'start')
env = os.environ.pop('AGENT_RUNNER_HOME')

print('home defaults to ~/runs/<repo>, and the worktrees and plan clone go in it')
(repo / 'runner.toml').write_text('[plan]\nrepo = "https://example.invalid/proj-plan.git"\n', encoding='utf-8')
c = Config(repo)
eq(c.home, Path('~/runs/proj').expanduser(), 'the default home is ~/runs/<repo>')
eq(c.slots_dir, c.home, 'the worktrees live in it')
eq(c.plan_dir, c.home / 'plan', 'and so does the plan clone')

print('[run] home and AGENT_RUNNER_HOME override it')
home = (tmp / 'mine/{repo}').as_posix()
(repo / 'runner.toml').write_text(f'[run]\nhome = "{home}"\n', encoding='utf-8')
eq(Config(repo).home, tmp / 'mine/proj', '[run] home, with {repo} filled in')
os.environ['AGENT_RUNNER_HOME'] = str(tmp / 'machine/{repo}')
eq(Config(repo).home, tmp / 'machine/proj', 'AGENT_RUNNER_HOME wins: one machine, without editing the shared config')

eq(Config(repo).slots_dir, tmp / 'machine/proj', 'the worktrees are in home')

print('`agent-runner home` answers scripts from the same settings')
from _check import run  # noqa: E402
eq(run(repo, 'home').stdout.strip(), str(tmp / 'machine/proj'), '`home` prints it')
eq(run(repo, 'home', 'slots').stdout.strip(), str(tmp / 'machine/proj'), '`home slots` prints the worktrees')
eq(run(repo, 'home', 'bogus').returncode, 2, 'anything else is a usage error')

print("runner.local.toml: one machine's settings over runner.toml, never shared, never rewritten")
from agent_runner.config import LOCAL, ensure_local  # noqa: E402
from _check import check  # noqa: E402
(repo / 'runner.toml').write_text('[run]\nslots = 3\nweekly_max = 90\nmodel = "opus"\n', encoding='utf-8')
f = ensure_local(repo)
eq(f, repo / LOCAL, 'run makes it in the main checkout')
r = Config(repo).run
eq((r['slots'], r['weekly_max'], r['model']), (3, 90, 'opus'), 'the made file is all comments: it changes nothing')
check(LOCAL not in git(repo, 'status', '--porcelain', '--untracked-files=all'), 'and git does not see it')
eq(git(repo, 'check-ignore', LOCAL), LOCAL, 'it is ignored (the clone\'s .git/info/exclude)')
f.write_text('[run]\nweekly_max = 50\nslots = 1\n', encoding='utf-8')
r = Config(repo).run
eq((r['slots'], r['weekly_max'], r['model']), (1, 50, 'opus'), 'its keys win; the rest stay runner.toml\'s')
ensure_local(repo)
eq(f.read_text(encoding='utf-8'), '[run]\nweekly_max = 50\nslots = 1\n', 'and a run never rewrites it')
exclude = repo / '.git/info/exclude'
eq(exclude.read_text(encoding='utf-8').count(f'/{LOCAL}'), 1, 'nor adds it to the excludes twice')
f.write_text('[agent-runner.run]\nweekly_max = 40\n', encoding='utf-8')
eq(Config(repo).run['weekly_max'], 40, 'it may wrap its tables in [agent-runner] too')
f.write_text('[run\n', encoding='utf-8')
try:
    Config(repo)
except SystemExit as e:
    check(LOCAL in str(e), 'a broken one stops the run naming the file', str(e))
else:
    check(False, 'a broken one stops the run naming the file')
f.unlink()

print('removed and unknown keys: still runs, and the run log says what to change')
(repo / 'runner.toml').write_text('[run]\nslotz = 2\nmode = "d"\n[kit]\nanything = 1\n', encoding='utf-8')
c = Config(repo)
eq(len(c.warnings), 2, 'one line per stale key, none for a table that is not ours')
check(any('mode is ignored' in w for w in c.warnings), 'a removed key says what to do instead')
check(any('did you mean slots' in w for w in c.warnings), 'a typo gets the nearest setting')
(repo / 'runner.toml').write_text('[run]\nslots = 3\n', encoding='utf-8')
eq(Config(repo).warnings, [], 'a clean config says nothing')

print('the guide: printed, and kept installed as a Claude Code skill')
from agent_runner import guide  # noqa: E402
eq(run(repo, 'guide').returncode, 0, '`guide` prints it')
for name in guide.TOPICS:  # C2: one branch's page each, behind a pointer in GUIDE and the control brief
    r = run(repo, 'guide', name)
    check(r.returncode == 0 and r.stdout.startswith('# ') and '{' not in r.stdout, f'`guide {name}` prints its page')
    check(f'agent-runner guide {name}' in guide.GUIDE, f'and GUIDE points at it')
eq(run(repo, 'guide', 'nope').returncode, 2, 'an unknown topic is a usage error')
from agent_runner.runner import PROMPT  # noqa: E402
check(guide.SAFE_SHELL in guide.GUIDE and guide.SAFE_SHELL in PROMPT, 'the shell-safety rules: in the guide and the agents\' prompt alike')
cc = tmp / 'claude'
os.environ['CLAUDE_CONFIG_DIR'] = str(cc)
eq(guide.install(), '', 'no Claude config dir: nothing written')
cc.mkdir()
check(guide.install(), 'installed, and the run log says so')
check(guide.skill_file().read_text(encoding='utf-8').startswith('---\nname: agent-runner'), 'as a skill')
eq(guide.install(), '', 'the same text: left alone, nothing said')
guide.skill_file().write_text('old', encoding='utf-8')
check(guide.install(), 'another runner version\'s text: rewritten')
guide.skill_file().unlink()
r = run(repo, '--version')
check(guide.skill_file().is_file() and 'installed the agent-runner skill' in r.stderr, '--version installs it too, said on stderr')
eq(r.stdout.strip().split()[0], 'agent-runner', 'and stdout stays the command\'s own')

print("the rules file gets one line pointing at the skill, committed")
g = lambda *a: __import__('agent_runner.gitops', fromlist=['git']).git(*a, cwd=repo)
eq(guide.point_rules(Config(repo), g), '', 'no rules file: none is made')
(repo / 'AGENTS.md').write_text('# Rules\nBuild with make.', encoding='utf-8')
git(repo, 'add', 'AGENTS.md')
git(repo, 'commit', '-qm', 'rules')
(repo / 'AGENTS.md').write_text('# Rules\nBuild with make.\nmine, uncommitted\n', encoding='utf-8')
eq(guide.point_rules(Config(repo), g), '', 'not into a file somebody is editing')
git(repo, 'checkout', '--', 'AGENTS.md')
check(guide.point_rules(Config(repo), g), 'AGENTS.md gets the pointer')
has((repo / 'AGENTS.md').read_text(encoding='utf-8'), r'Build with make\.\n\nTasks: .*agent-runner guide', 'appended')
eq(git(repo, 'status', '--porcelain', 'AGENTS.md'), '', 'and committed')
eq(guide.point_rules(Config(repo), g), '', 'only once')
has((repo / 'AGENTS.md').read_text(encoding='utf-8'), r'Asked to do something now\? Use `\S+ take', 'it says to take "do it now" work')
cmd = Config(repo).run['command'] or 'agent-runner'
(repo / 'AGENTS.md').write_text(f'# Rules\n\n{guide.OLD_POINTERS[0].format(cmd=cmd)}\nmore rules\n', encoding='utf-8')
git(repo, 'commit', '-qam', 'an older pointer')
check(guide.point_rules(Config(repo), g).startswith('updated'), 'an older pointer line is rewritten')
eq((repo / 'AGENTS.md').read_text(encoding='utf-8'), f'# Rules\n\n{guide.POINTER.format(cmd=cmd)}\nmore rules\n',
   'in place, once')

print('F148, F150: running first, then idle or paused, those off at the bottom, by name in each group')
from agent_runner import home as H  # noqa: E402
states = {'Echo': 'idle', 'alpha': 'off', 'bravo': 'running', 'Charlie': 'off', 'delta': 'running', 'foxtrot': 'running'}
for n in states:
    (tmp / 'f148' / n).mkdir(parents=True)
reg = {'projects': [str(tmp / 'f148' / n) for n in reversed(states)], 'hidden': [], 'scan': []}
rows = H.project_rows(reg, row=lambda key, root: {'key': key, 'name': root.name, 'state': states[root.name],
                                                  'paused': root.name == 'delta'})
eq([r['name'] for r in rows], ['bravo', 'foxtrot', 'delta', 'Echo', 'alpha', 'Charlie'],
   'running by name, then idle or paused, then off')

print('B764b: a wrong [run] agent does not hide the run from Home, and Home says it')
from unittest import mock  # noqa: E402
from agent_runner import web as W  # noqa: E402
(repo / LOCAL).unlink(missing_ok=True)
for agent in ('pi', 'nosuchagent'):
    (repo / 'runner.toml').write_text(f'[run]\nagent = "{agent}"\n', encoding='utf-8')
    Config(repo).notes('web.url').write_text('http://box:45678/?t=abc123\n', encoding='utf-8')
    with mock.patch('agent_runner.cmds.run_info', return_value={'up': True}):
        eq(H.run_link(repo), (45678, 'abc123'), f'agent = {agent}: the run page still has its port')
    row = H.project_row('p', repo, info=lambda r: {'up': False}, needs=lambda r: (0, []))
    has(row['agent_problem'], rf"\[run\] agent = '{agent}'", 'and Home says what is wrong')
check('p.agent_problem' in W.PAGE.read_text(encoding='utf-8') and 'S.snap.agent_problem' in W.PAGE.read_text(encoding='utf-8'),
      'in All projects and on the Run card')

print('F461: home install sets up https without a prompt, and asks once whether to trust the tailnet')
from agent_runner import page_https as PH  # noqa: E402
os.environ['AGENT_RUNNER_HOME_CONFIG'] = str(tmp / 'homecfg')
plain = ['http://box:8770/?t=x']
yes = lambda t: '/usr/bin/' + t  # noqa: E731
with mock.patch.object(PH, 'not_connected', lambda: False), \
        mock.patch.object(H, 'home_urls', lambda port, https=None: ['https://box.ts.net:8771/?t=x'] + plain):
    ran, said = [], []
    got = H.offer_https(8770, plain, call=lambda c: ran.append(c) or (0, ''), out=said.append,
                        ask=lambda q: 1 / 0, which=yes, status=lambda: {})
    eq(ran, [['tailscale', 'serve', '--bg', '--https=8771', 'http://127.0.0.1:8770']], 'serve made, no prompt')
    eq(got[0], 'https://box.ts.net:8771/?t=x', 'https link first')
    ran, said = [], []
    got = H.offer_https(8770, plain, call=lambda c: ran.append(c) or (0, ''), out=said.append, which=yes,
                        status=lambda: {'TCP': {'8771': {}}})
    eq((ran, got), ([], plain), 'port 8771 taken: nothing run')
    has(said[-1], r'http only \(Tailscale Serve already uses port 8771', 'and says why')
with mock.patch.object(PH, 'not_connected', lambda: True):
    said = []
    H.offer_https(8770, plain, call=lambda c: 1 / 0, out=said.append, which=yes)
    has(said[-1], r'http only \(Tailscale is not connected', 'not connected: says why')
eq(H.ask_tailnet(out=print, tty=False), False, 'not a tty: no question')
eq(H.ask_tailnet(out=print, ask=lambda q: False), False, 'a no: tailnet not added')
eq(H.load_registry()['trusted_networks'], [], 'nothing trusted')
eq(H.ask_tailnet(out=print, ask=lambda q: 1 / 0), False, 'a no is not asked again')
(tmp / 'homecfg' / 'tailnet-asked').unlink()
asked = []
eq(H.ask_tailnet(out=print, ask=lambda q: asked.append(q) or True), True, 'a yes adds tailnet')
eq(H.load_registry()['trusted_networks'], ['tailnet'], 'tailnet is trusted')
has(asked[0], 'Anyone on the tailnet can then do everything', 'the question warns')
eq(H.ask_tailnet(out=print, ask=lambda q: 1 / 0), False, 'trusted already: not asked again')
os.environ.pop('AGENT_RUNNER_HOME_CONFIG')

os.environ['AGENT_RUNNER_HOME'] = env
raise SystemExit(1 if FAILED else print('\nall checks passed'))
