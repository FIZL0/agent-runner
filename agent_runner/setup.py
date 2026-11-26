"""`agent-runner setup`: make the repo in this folder ready for a run (F49).

1. Save what is there: uncommitted work (tracked edits and untracked files) is committed to a backup branch,
   runner-setup-backup-<date>, through a scratch index, so the checkout, its index and HEAD stay as they were.
2. Write runner.toml when there is none, with a guessed gate, and add an empty `## Tools` section to CLAUDE.md
   when it has none (B80). Without ttyd, offer at a terminal to install it (F403). Ask there which providers to
   use, and log in to them (F406d, setup_models), and once whether the run audits by itself (F422).
3. Start one full Claude session (normal tools, CLAUDE.md, not the lean slot brief) whose first message asks it to
   read the repo and write the plan through `plan goal` / `plan add`, set the gate and a short notes section.
4. Print what it set up, and `agent-runner` to start the run (s in its launcher).

On a repo whose plan already has a TODO.md it asks before the session touches the plan (`--yes`: go on).
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from agent_runner.config import RUNNER

BACKUP = 'runner-setup-backup-{date}'

RUNNER_TOML = """# agent-runner's settings for this repo (written by `agent-runner setup`). Every key is optional;
# see docs/REFERENCE.md#runnertoml in agent-runner for all of them.

[run]
{test}
slots = 2
notes = ".runner"            # the runner's own files here: git-ignore it
"""


def git(root: Path, *a: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(['git', *a], cwd=str(root), capture_output=True, text=True, env=env)


def repo_root(cwd: Path) -> Path:
    """The checkout around cwd; a folder with no git becomes a repository on `main` first."""
    r = git(cwd, 'rev-parse', '--show-toplevel')
    if r.returncode:
        print(f'agent-runner setup: no git repository here: making {cwd} one', file=sys.stderr)
        r = git(cwd, 'init', '-q', '-b', 'main')
        if r.returncode:
            raise SystemExit(f'agent-runner setup: git init failed: {r.stderr.strip()}')
        return cwd.resolve()
    return Path(r.stdout.strip()).resolve()


def backup(root: Path, today: datetime.date | None = None) -> str | None:
    """Commit every uncommitted change (untracked files too, not ignored ones) to a new backup branch and
    return its name; None when the tree is clean. A scratch index does the work, so the checkout's index,
    working tree and branch are untouched: the dirty files stay dirty where they are."""
    if not git(root, 'status', '--porcelain', '--untracked-files=all').stdout.strip():
        return None
    base = BACKUP.format(date=(today or datetime.date.today()).isoformat())
    name, n = base, 1
    while not git(root, 'rev-parse', '--verify', '-q', f'refs/heads/{name}').returncode:
        n += 1
        name = f'{base}-{n}'
    head = git(root, 'rev-parse', '--verify', '-q', 'HEAD').stdout.strip()
    with tempfile.TemporaryDirectory(prefix='agent-runner-setup-') as t:
        env = {**os.environ, 'GIT_INDEX_FILE': str(Path(t) / 'index')}
        steps = [['read-tree', head]] if head else [['read-tree', '--empty']]
        steps.append(['add', '-A'])
        for step in steps:
            r = git(root, *step, env=env)
            if r.returncode:
                raise SystemExit(f'agent-runner setup: git {step[0]} failed: {r.stderr.strip()}')
        tree = git(root, 'write-tree', env=env).stdout.strip()
    msg = 'agent-runner setup: the uncommitted work as it was before setup'
    r = git(root, 'commit-tree', tree, *(['-p', head] if head else []), '-m', msg)
    if r.returncode:
        raise SystemExit(f'agent-runner setup: git commit-tree failed: {r.stderr.strip()}')
    r = git(root, 'branch', name, r.stdout.strip())
    if r.returncode:
        raise SystemExit(f'agent-runner setup: git branch {name} failed: {r.stderr.strip()}')
    return name


def guess_test(root: Path) -> str | None:
    """The repo's own test command, from the files that usually name it; None when nothing says."""
    pkg = root / 'package.json'
    if pkg.is_file():
        try:
            if json.loads(pkg.read_text(encoding='utf-8')).get('scripts', {}).get('test'):
                return 'npm test'
        except (OSError, ValueError, AttributeError):
            pass
    if (root / 'Cargo.toml').is_file():
        return 'cargo test'
    if (root / 'go.mod').is_file():
        return 'go test ./...'
    mk = root / 'Makefile'
    if mk.is_file():
        try:
            targets = {l.split(':', 1)[0] for l in mk.read_text(encoding='utf-8').splitlines() if ':' in l}
        except OSError:
            targets = set()
        for t in ('test', 'check'):
            if t in targets:
                return f'make {t}'
    if (root / 'pytest.ini').is_file() or (root / 'conftest.py').is_file():
        return 'python3 -m pytest -q'
    if (root / 'tests').is_dir() and any((root / 'tests').glob('test_*.py')):
        return 'python3 -m unittest discover -q -s tests'
    return None


def write_toml(root: Path) -> tuple[bool, str | None]:
    """(written, gate): runner.toml only when there is none; an existing one is left exactly as it is."""
    f = root / 'runner.toml'
    if f.exists():
        return False, None
    test = guess_test(root)
    line = (f'test = "{test}"   # the gate: `done` and every merge run it' if test else
            '# test = "make test"   # the gate: `done` and every merge run it (setup found none: set it)')
    f.write_text(RUNNER_TOML.format(test=line), encoding='utf-8')
    return True, test


TOOLS_HEADING = '## Tools'
TOOLS_SECTION = (TOOLS_HEADING + '\n\n<!-- What agents here can reach to check their own work: ssh hosts, preview '
                 'servers, headless checks (machine logins go in ~/.claude/ACCESS.md). -->\n')


def ensure_tools(root: Path) -> str | None:
    """B80: add an empty `## Tools` section to CLAUDE.md (created when missing) unless it has one; slots read it
    before handing a check to a person. The file name when it was changed, else None."""
    f = root / 'CLAUDE.md'
    try:
        text = f.read_text(encoding='utf-8') if f.is_file() else ''
    except OSError:
        return None
    if any(l.strip() == TOOLS_HEADING for l in text.splitlines()):
        return None
    sep = '' if not text or text.endswith('\n\n') else '\n' if text.endswith('\n') else '\n\n'
    try:
        f.write_text(text + sep + TOOLS_SECTION, encoding='utf-8')
    except OSError:
        return None
    return f.name


def todo_path(root: Path) -> Path:
    """Where this repo's TODO.md is ([plan] dir or repo, as the run reads it); plan/TODO.md when the config
    cannot be read."""
    try:
        from agent_runner.config import cfg
        return cfg(root).todo
    except (Exception, SystemExit):
        return root / 'plan' / 'TODO.md'


def prompt(root: Path, gate: str | None, existing: bool) -> str:
    """The first message of the setup session: what to read, and how to write the plan and the repo context."""
    plan = f'{RUNNER} plan'
    gate_line = (f'runner.toml\'s `[run] test` is now `{gate}`, a guess: check it runs and passes, and fix it.'
                 if gate else 'Set runner.toml\'s `[run] test` to the command that runs the whole test suite.')
    start = ('This repo already has a task list: read it with `{p}` first, keep its tasks, and add only what is '
             'missing.' if existing else 'This repo has no task list yet.').format(p=plan)
    return f"""Set this repository up for agent-runner, which runs AI agents through plan/TODO.md, one task each, \
in parallel worktrees. {start}

1. Read the repo: README, its layout, how it builds and tests (run the tests once), and its open TODOs \
(TODO/FIXME comments, a TODO file, `gh issue list` if it has a GitHub remote).
2. The gate: {gate_line} `done` and every merge run it, so it must pass on main now; when it does not, file \
fixing it as the first task.
3. The plan, through the runner's tool only, never by editing plan/TODO.md by hand:
   - `{plan} goal "<one line: what this project is for and where it is heading>"`
   - `{plan} add <KIND> "<task>" --files a.py,dir/** [--after ID] [--pri low]` for each first task (5-15 small \
ones, each one session's work; KIND is the id letter, `{plan} kinds` lists them: B bug, F feature, T tests and \
tooling, D docs, C cleanup, R research). `--files` names the files a task will change, so the run keeps two \
agents off the same file.
   - `{plan}` to see the list it wrote.
4. The repo context agents need: a short `## Agent notes` section in CLAUDE.md, or AGENTS.md if the repo has one \
(build and test commands, where things live, what not to touch). Keep it short: every session loads it. Make \
sure `.runner/` is in .gitignore.
5. Commit runner.toml, plan/, the notes and .gitignore in one commit on the current branch.

End with a few lines: the gate, the goal, how many tasks, and what a person should check.
"""


def harness_argv(root: Path, text: str) -> list[str]:
    """F406h: the setup session on [models] control's provider: the harness loop's chat, `text` its first message. No git
    fence, as the Claude one has none: it commits the setup."""
    from agent_runner.config import cfg, runner_cmd
    from agent_runner.slots import HARNESS
    c = cfg(root)
    model = c.models['control']
    pf = c.notes('setup.prompt')
    pf.parent.mkdir(parents=True, exist_ok=True)
    pf.write_text(text, encoding='utf-8')
    flags = ['--chat', '--session-id', str(uuid.uuid4()), '--model', model, '--notes', str(c.notes()),
             '--runner-cmd', json.dumps(runner_cmd())]
    if own := c.providers.get(model.partition(':')[0]):
        flags += ['--provider', json.dumps(own)]
    print('agent-runner setup: Ctrl-D ends the session')
    return HARNESS.argv('', pf, '', flags)


def launch(root: Path, text: str) -> int | None:
    """One full interactive Claude session in the repo with `text` as its first message (normal tools and
    settings, not a slot's lean ones); waits for it to end. F406h: with no Claude Code here, a chat on the harness loop
    when no role needs it. None: neither can start here (`no_claude` says why)."""
    from agent_runner.setup_models import claude_program
    agent = claude_program(root)
    if not agent and no_claude(root):
        return None
    argv = [agent, text] if agent else harness_argv(root, text)
    agent = argv[0]
    try:
        return subprocess.run(argv, cwd=str(root)).returncode
    except OSError as e:
        print(f'agent-runner setup: cannot start {agent}: {e}', file=sys.stderr)
        return 127


def ask(question: str) -> bool:
    try:
        return input(f'{question} [y/N] ').strip().lower() in ('y', 'yes')
    except EOFError:
        return False


def at_terminal() -> bool:
    """Are stdin and stdout both a terminal (someone can answer, and a sudo or winget prompt works)?"""
    return all(f is not None and f.isatty() for f in (sys.stdin, sys.stdout))


def offer_ttyd() -> str | None:
    """F403: without ttyd a chat on the run page cannot show its session, so ask to install it with this machine's
    command, run in this terminal. The line to say about it; None when ttyd is there. Never installs unasked, and
    never fails setup."""
    from agent_runner import ui_model as U
    from agent_runner import web as W
    if U.find_ttyd():
        return None
    cmd = W.ttyd_install_cmd()
    if not cmd:
        return f'ttyd is not installed, so the run page cannot show sessions: {W.TTYD_INSTALL}'
    later = f'ttyd is not installed, so the run page cannot show sessions: install it with `{cmd}`'
    try:
        if not at_terminal() or not ask(f'ttyd is not installed, so the run page cannot show sessions: run `{cmd}` now?'):
            return later
    except KeyboardInterrupt:  # Ctrl-C is a no, too
        return later
    argv = cmd.split()
    argv[0] = shutil.which(argv[0]) or argv[0]  # Windows: scoop is a .cmd, which starts only by its full name
    try:
        code = subprocess.run(argv).returncode
        why = f'exit {code}'
    except OSError as e:
        code, why = 127, str(e)
    except KeyboardInterrupt:
        code, why = 130, 'interrupted'
    if U.find_ttyd():
        return 'ttyd is ready: the run page can show sessions'
    if code:
        return f'ttyd was not installed: `{cmd}` failed ({why})'
    return f'`{cmd}` ended, but ttyd is not found yet: open a new terminal, and run the command again if it is missing there'


def offer_models(root: Path) -> list[str]:
    """F406d: ask at a terminal which providers to use; the lines to say about it."""
    from agent_runner.setup_models import offer
    return offer(root, at_terminal())


def offer_audit(root: Path) -> str | None:
    """F422: ask at a terminal, once for a project, whether the run audits by itself ([run] auto_audit, default no). The
    answer, a no too, goes to the project's settings file, so it is not asked again; Ctrl-C or Ctrl-D leaves it open.
    The line to say about it; None when nothing was asked. Never fails setup."""
    from agent_runner import audit
    from agent_runner import config as CF
    if not at_terminal():
        return None
    try:
        snap = CF.settings_snapshot(root)
        row = next(k for t in snap['tables'] if t['table'] == 'run' for k in t['keys'] if k['key'] == 'auto_audit')
        f = CF.config_file(root)
    except (Exception, SystemExit):  # a config that does not load is the session's to mend
        return None
    if not snap['ok'] or not f or row['has_project'] or row['has_device']:
        return None
    try:
        yes = input(f'Audit by itself: when the run is idle and {audit.EVERY} tasks have landed, one looks for what is stale, '
                    'unused or wasted? [y/N] ').strip().lower() in ('y', 'yes')
    except (EOFError, KeyboardInterrupt):
        print()
        return None
    try:
        f = f.resolve()
        out = CF.setting_edit(f.read_bytes(), 'run', 'auto_audit', {'every': audit.EVERY} if yes else False, name=f.name)
        CF.write_whole(f, out, f.stat().st_mode & 0o777)
    except (OSError, ValueError) as e:
        return f'[run] auto_audit is not written to {f.name}: {e}'
    CF._cfg.cache_clear()
    return f'the run audits by itself every {audit.EVERY} tasks ([run] auto_audit in {f.name}: commit it)' if yes else \
        f'no audit by itself ([run] auto_audit = false in {f.name}: commit it; once committed, Settings on the run page can turn it on)'


def offer_web_open(root: Path) -> str | None:
    """F454b: ask at a terminal, once for this machine, who can reach the run page ([run] web_open: everywhere, the
    default, or here). The answer goes to runner.local.toml, so it is not asked again; Enter takes the default;
    Ctrl-C or Ctrl-D leaves it open. The line to say about it; None when nothing was asked. Never fails setup."""
    from agent_runner import config as CF
    if not at_terminal():
        return None
    try:
        snap = CF.settings_snapshot(root)
        row = next(k for t in snap['tables'] if t['table'] == 'run' for k in t['keys'] if k['key'] == 'web_open')
    except (Exception, SystemExit):  # a config that does not load is the session's to mend
        return None
    if not snap['ok'] or row['has_project'] or row['has_device']:
        return None
    try:
        while True:
            a = input('Who can reach the run page: other devices too (default) or only this machine? '
                      '[Everywhere/here] ').strip().lower()
            if a in ('', 'e', 'everywhere', 'h', 'here'):
                break
            print('Answer everywhere or here (Enter: everywhere).')
    except (EOFError, KeyboardInterrupt):
        print()
        return None
    value = 'here' if a in ('h', 'here') else 'everywhere'
    try:
        f = CF.local_file(root) or CF.ensure_local(root)
        out = CF.setting_edit(f.read_bytes(), 'run', 'web_open', value, name=f.name)
        CF.write_whole(f, out, f.stat().st_mode & 0o777)
    except (OSError, ValueError) as e:
        return f'[run] web_open is not written to {CF.LOCAL}: {e}'
    CF._cfg.cache_clear()
    return ('the run page opens on this machine only' if value == 'here' else 'the run page opens on your other devices too') + \
        f' ([run] web_open = "{value}" in {f.name}; Settings can change it)'


def offer_home(root: Path, home=None) -> list[str]:
    """F456: offer Runner Home, one address for every project on this device, when it is not installed: at a terminal
    ask [Y/n], and a yes runs `home install` (which prints its links) and lists this project in Home if no scanned
    folder holds it. With Home installed, only offer to add the project. A no or Ctrl-C changes nothing (asked again
    next setup); a failed install is said, never fails setup. The lines to say about it."""
    if home is None:
        from agent_runner import home
    try:
        on = home.home_on()
    except Exception:
        return []
    def listed() -> bool:
        try:
            return root.resolve() in [p.resolve() for p in home.projects()]
        except Exception:
            return True  # a registry that does not load: leave it alone
    def add() -> str:
        try:
            ok, said = home.add_project(str(root))
        except Exception as e:
            ok, said = False, str(e)
        return said if ok else f'{root.name} is not added to Runner Home: {said} (`{RUNNER} home add {root}`)'
    if not at_terminal():
        if on:
            return [] if listed() else [f'Runner Home does not list {root.name}: add it with `{RUNNER} home add {root}`']
        return [f'Runner Home is not installed: `{RUNNER} home install` gives one address for every project on this device']
    try:
        if on:
            if listed():
                return []
            a = input(f'Runner Home does not list {root.name}: add it? [Y/n] ').strip().lower()
            return [add()] if a in ('', 'y', 'yes') else [f'{root.name} is not in Runner Home (`{RUNNER} home add {root}`)']
        a = input('Install Runner Home, one address for every project on this device? [Y/n] ').strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return [] if on else [f'Runner Home is not installed (`{RUNNER} home install`)']
    if a not in ('', 'y', 'yes'):
        return [f'Runner Home is not installed (`{RUNNER} home install`; setup asks again next time)']
    try:
        code = home.install()
    except KeyboardInterrupt:
        code = 'interrupted'
    except Exception as e:
        code = str(e)
    except SystemExit as e:
        code = f'exit {e.code}'
    if code != 0:
        try:
            home.mark_installed(False)  # install turns Home on first: a failed one leaves it off, asked again
        except Exception:
            pass
        return [f'Runner Home was not installed ({code if isinstance(code, str) else f"exit {code}"}): '
                f'try `{RUNNER} home install` again']
    out = ['Runner Home is installed']
    if not listed():
        out.append(add())
    return out


def home_installed() -> bool:
    try:
        from agent_runner import home
        return home.home_on()
    except Exception:
        return False


def no_claude(root: Path) -> str:
    """F406d: what cannot run while this machine has no Claude Code, in one line; '' when it has one."""
    from agent_runner import setup_models as M
    from agent_runner.claude_use import uses
    if M.claude_program(root):
        return ''
    c = M.config(root)
    if c and not uses(c):  # F406h: no role needs it: the setup session runs on [models] control's provider
        from agent_runner.login import missing
        out = missing(c.models['control'], c)
        why = f'{out} has no login (`{RUNNER} login {out}`)' if out else '' if shutil.which('node') else 'Node.js is not on PATH'
        return why and f'{why}, so the setup session, chats and tasks cannot run yet (`{RUNNER} plan add` files tasks by hand)'
    why = c.agent_problem if c and c.run['agent'] != 'claude' else 'no Claude Code here'
    return (f'{why}, so these cannot run yet: the setup session that writes the plan, chats, spec reviews and tasks on '
            f'a claude model (`{RUNNER} plan add` files tasks by hand)')


def pr_refused(root: Path) -> str:
    """F419: why the config's PR mode may not be on here, '' when it may (or is off)."""
    from agent_runner import pr
    from agent_runner.config import Config
    try:
        return pr.refusal(Config(root), root)
    except (SystemExit, Exception) as e:  # a config that does not load is the session's to mend, but for this
        return str(e) if 'cannot both be on' in str(e) else ''


def count_tasks(todo: Path) -> int:
    try:
        return sum(1 for l in todo.read_text(encoding='utf-8').splitlines() if l.lstrip().startswith('- [ ] **'))
    except OSError:
        return 0


def main(argv: list[str], cwd: Path | None = None) -> int:
    ap = argparse.ArgumentParser(prog=f'{RUNNER} setup', description='Make this repo ready for a run: back up '
                                 'uncommitted work to a branch, write runner.toml if missing, and start a Claude '
                                 'session that reads the repo and writes the plan, the gate and the notes.')
    ap.add_argument('--yes', '-y', action='store_true', help='a repo that has a plan already: go on without asking')
    a = ap.parse_args(argv)
    root = repo_root(Path(cwd or Path.cwd()))
    if why := pr_refused(root):  # F419
        print(why, file=sys.stderr)
        return 1
    said: list[str] = []
    name = backup(root)
    said.append(f'uncommitted work saved on branch {name} (your files are still here, unchanged)' if name
                else 'nothing uncommitted to save')
    for line in said:
        print(f'agent-runner setup: {line}')
    written, gate = write_toml(root)
    said.append('runner.toml written' + (f', gate `{gate}`' if gate else ', no gate found yet') if written
                else 'runner.toml kept as it was')
    print(f'agent-runner setup: {said[-1]}')
    if tools := ensure_tools(root):
        said.append(f'added an empty `{TOOLS_HEADING}` section to {tools}: list what agents can reach there')
        print(f'agent-runner setup: {said[-1]}')
    if ttyd := offer_ttyd():
        said.append(ttyd)
        print(f'agent-runner setup: {said[-1]}')
    for line in offer_models(root):
        said.append(line)
        print(f'agent-runner setup: {line}')
    for line in offer_home(root):  # F456
        said.append(line)
        print(f'agent-runner setup: {line}')
    if not home_installed() and (opens := offer_web_open(root)):  # F454b's question counts only with no Home
        said.append(opens)
        print(f'agent-runner setup: {opens}')
    if audits := offer_audit(root):
        said.append(audits)
        print(f'agent-runner setup: {audits}')
    todo = todo_path(root)
    existing = todo.is_file()
    text = prompt(root, gate, existing)
    if existing and not a.yes and not no_claude(root) and not ask(f'{todo} exists: start a session that reads it and adds to it?'):
        said.append('plan left alone (re-run with --yes to let the session add to it)')
    else:
        code = launch(root, text)
        said.append(no_claude(root) if code is None else f'setup session ended (exit {code})')
        if todo.is_file():
            said.append(f'{todo.relative_to(root) if todo.is_relative_to(root) else todo}: '
                        f'{count_tasks(todo)} open tasks')
    print('\nagent-runner setup:\n' + ''.join(f'  - {s}\n' for s in said) + '\nStart the run: agent-runner')
    return 0
