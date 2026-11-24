"""The tests' few helpers: plain prints, no framework, so `python3 tests/test_x.py` is the whole interface."""
from __future__ import annotations

import atexit
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'run'
sys.path.insert(0, str(ROOT))

FAILED: list[str] = []

# git that ignores the user's config (signing, hooks, a default branch name) and needs no identity
_gitconfig = tempfile.NamedTemporaryFile('w', prefix='agent-runner-test-gitconfig', delete=False)
_gitconfig.write('[user]\n\tname = test\n\temail = test@example.invalid\n[init]\n\tdefaultBranch = main\n')
_gitconfig.close()
os.environ.update(GIT_CONFIG_GLOBAL=_gitconfig.name, GIT_CONFIG_NOSYSTEM='1')
os.environ.pop('AGENT_RUNNER_REPO', None)
# a gate run by `done` in a slot inherits the slot session's markers: without this the code under test acts
# as a slot's agent (no skill install, a different plan path) and the suites fail only inside a run
os.environ.pop('AGENT_RUNNER_SLOT', None)
os.environ.pop('AGENT_RUNNER', None)
os.environ.pop('AGENT_RUNNER_WORKTREE', None)  # B103: else `done` in a test project refuses it as another project
os.environ['AGENT_RUNNER_NO_NOTIFY'] = '1'  # an alarm in a test rings no desktop notification
os.environ['AGENT_RUNNER_NO_WEB'] = '1'  # a run under test serves no run page (it would take the real port 8770)
os.environ['AGENT_RUNNER_NO_SERVE'] = '1'  # F96: one that does makes no rule in this machine's Tailscale

# B68: every temp folder of this suite, its subprocesses' too, goes under one root of its own, so a trust entry
# the suite leaks into the person's real ~/.claude.json is told apart from other sessions' (see claude_json_leaks)
SYS_TMP = Path(tempfile.gettempdir())
TMP_ROOT = Path(tempfile.mkdtemp(prefix='agent-runner-test-'))
tempfile.tempdir = str(TMP_ROOT)
for _k in ('TMPDIR', 'TEMP', 'TMP'):
    os.environ[_k] = str(TMP_ROOT)
_mem = TMP_ROOT / 'meminfo'  # B184: no suite waits for the real machine's memory
_mem.mkdir()
(_mem / 'meminfo').write_text('MemTotal: 33554432 kB\nMemAvailable: 16777216 kB\n')
os.environ['AGENT_RUNNER_MEMINFO_DIR'] = str(_mem)
if not shutil.which('claude'):  # B764c: a machine without Claude Code (CI): the default [run] agent must be there
    _bin = TMP_ROOT / 'claude-bin'
    _bin.mkdir()
    for _name, _text in (('claude', '#!/bin/sh\nexit 127\n'), ('claude.cmd', '@exit /b 127\r\n')):
        (_bin / _name).write_text(_text, encoding='utf-8')
        (_bin / _name).chmod(0o755)
    os.environ['PATH'] += os.pathsep + str(_bin)
_SUITE_PID = os.getpid()


@atexit.register  # exit handlers run last-registered first: this one after the leak check and every suite's own
def _remove_temp() -> None:
    """T21: the suite's temp root and git config go when it ends, passed or failed. What a process still running
    there holds or writes again is left behind; it never changes the exit code."""
    if os.getpid() != _SUITE_PID:
        return  # a forked child has the handler too, and its parent still uses the folder
    try:
        os.chdir(ROOT)  # Windows removes no folder that is a current one
    except OSError:
        pass
    for wait in (0, 0.1, 0.3):  # a process that is just ending may still write there
        time.sleep(wait)
        shutil.rmtree(TMP_ROOT, ignore_errors=True)
        if not TMP_ROOT.exists():
            break
        root = os.path.realpath(TMP_ROOT)
        for d, dirs, files in os.walk(root):  # a read-only folder, and on Windows a read-only file, stops rmtree
            # before Python 3.12 a Windows junction is no link to islink: never follow one out of the root
            dirs[:] = [n for n in dirs if os.path.realpath(os.path.join(d, n)).startswith(root + os.sep)]
            for p in [d, *(os.path.join(d, n) for n in dirs + (files if os.name == 'nt' else []))]:
                try:
                    if not os.path.islink(p):
                        os.chmod(p, 0o700)
                except OSError:
                    pass
    try:
        os.unlink(_gitconfig.name)
    except OSError:
        pass


# the files Claude Code (and Claude.trust) would use without the suite's own CLAUDE_CONFIG_DIR below
REAL_CLAUDE_JSON = list(dict.fromkeys(
    [Path.home() / '.claude.json'] + ([Path(os.environ['CLAUDE_CONFIG_DIR']) / '.claude.json']
                                      if os.environ.get('CLAUDE_CONFIG_DIR') else [])))


def _projects(f: Path) -> set[str]:
    try:
        return set(json.loads(f.read_text(encoding='utf-8')).get('projects') or {})
    except (OSError, ValueError, AttributeError):
        return set()


_REAL_BEFORE = {f: _projects(f) for f in REAL_CLAUDE_JSON}
os.environ['CLAUDE_CONFIG_DIR'] = tempfile.mkdtemp(prefix='agent-runner-test-claude-')  # never the real ~/.claude
# T15: nor the person's ~/.config/agent-runner (voice.md goes into every control brief and changes its length)
os.environ['XDG_CONFIG_HOME'] = tempfile.mkdtemp(prefix='agent-runner-test-config-')
# worktrees and plan clones go under a temp folder, never the real ~/runs
os.environ['AGENT_RUNNER_HOME'] = str(Path(tempfile.mkdtemp(prefix='agent-runner-test-runs-')) / '{repo}')

# C26: agent-runner runs no terminal multiplexer. A stand-in `tmux` goes first on PATH for the suite and its
# subprocesses: it fails, and notes each call in a file `report()` checks, so a call left anywhere fails the
# suite whether or not the machine has the real one.
NO_MUX_BIN = Path(tempfile.mkdtemp(prefix='agent-runner-test-nomux-'))
NO_MUX_LOG = NO_MUX_BIN / 'calls'
if os.name != 'nt':
    (NO_MUX_BIN / 'tmux').write_text(f'#!/bin/sh\necho "$*" >> "{NO_MUX_LOG}"\nexit 127\n', encoding='utf-8')
    (NO_MUX_BIN / 'tmux').chmod(0o755)
    os.environ['PATH'] = f'{NO_MUX_BIN}{os.pathsep}{os.environ.get("PATH", "")}'
os.environ.pop('TMUX', None)
os.environ.pop('TMUX_PANE', None)


def check(ok, what, extra=''):
    print(('  ok   ' if ok else '  FAIL ') + what + ('' if ok else f'\n         {extra}'))
    if not ok:
        FAILED.append(what)


def eq(got, want, what):
    check(got == want, what, f'got {got!r}\n         want {want!r}')


def has(text, pat, what):
    check(re.search(pat, text, re.M) is not None, what, f'no /{pat}/ in:\n{text[-800:]}')


def git(cwd, *a) -> str:
    cwd = Path(cwd)
    bare = (cwd / 'HEAD').is_file() and (cwd / 'objects').is_dir() and (cwd / 'refs').is_dir()
    args = ['git', '--git-dir', str(cwd.resolve()), *a] if bare else ['git', *a]
    r = subprocess.run(args, cwd=str(cwd), capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f'git {" ".join(a)}: {r.stderr}')
    return r.stdout.strip()


def run(cwd, *a, **kw) -> subprocess.CompletedProcess:
    """`./run <a>` in cwd, the way an agent session calls it."""
    return subprocess.run([sys.executable, str(RUN), *a], cwd=str(cwd), capture_output=True, text=True, **kw)


def claude_json_leaks() -> list[str]:
    """Folders this suite added to the real ~/.claude.json's `projects` (Claude.trust's entries): its temp
    folders all sit under TMP_ROOT, so another session writing the file at the same time is never counted."""
    roots = {p.as_posix().rstrip('/') for p in (TMP_ROOT, TMP_ROOT.resolve())}
    fold = (lambda s: s.lower()) if os.name == 'nt' else (lambda s: s)
    roots = {fold(r) for r in roots}
    return sorted(k for f in REAL_CLAUDE_JSON for k in _projects(f) - _REAL_BEFORE[f]
                  if any(fold(k.replace('\\', '/')).startswith(r + '/') or fold(k) == r for r in roots))


def check_real_claude_json() -> bool:
    _CHECKED.append(1)
    leaks = claude_json_leaks()
    check(not leaks, 'the real ~/.claude.json gained no trust entry from this suite',
          f'{len(leaks)} added: {leaks[:5]}')
    return not leaks


_CHECKED: list[int] = []


@atexit.register
def _check_at_exit() -> None:
    """A suite that ends without report() (test_home) is held to it too: a leak turns its exit code to 1."""
    if not _CHECKED and not check_real_claude_json():
        sys.stdout.flush()
        _remove_temp()  # os._exit runs no further exit handler
        os._exit(1)


def report(tests) -> int:
    for t in tests:
        t()
    check_real_claude_json()
    calls = NO_MUX_LOG.read_text(encoding='utf-8').splitlines() if NO_MUX_LOG.exists() else []
    check(not calls, 'C26: nothing called tmux', f'{len(calls)} calls: {calls[:5]}')
    print()
    if FAILED:
        print(f'{len(FAILED)} FAILED:')
        for f in FAILED:
            print(f'  - {f}')
        return 1
    print('all checks passed')
    return 0


def stale_test_entries(data: dict) -> list[str]:
    """Trust entries old suites left in a real ~/.claude.json: a folder under the system temp dir whose entry
    holds nothing but Claude.trust's flag (a session Claude Code itself ran there has more), `\\` keys too."""
    fold = (lambda s: s.replace('\\', '/').lower()) if os.name == 'nt' else (lambda s: s)
    roots = {fold(p.as_posix().rstrip('/')) + '/' for p in (SYS_TMP, SYS_TMP.resolve())}
    return [k for k, v in (data.get('projects') or {}).items()
            if isinstance(v, dict) and set(v) <= {'hasTrustDialogAccepted'} and fold(k).startswith(tuple(roots))]


def clean_real_claude_json(argv: list[str]) -> int:
    """`python3 tests/_check.py [--clean]`: list (or, with --clean, remove) the stale test entries in the real
    ~/.claude.json. Best with no Claude Code session open: one rewriting the file at that moment can undo it."""
    for f in REAL_CLAUDE_JSON:
        try:
            data = json.loads(f.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        stale = stale_test_entries(data)
        print(f'{f}: {len(stale)} stale test entr{"y" if len(stale) == 1 else "ies"}')
        for k in stale[:20]:
            print(f'  {k}')
        if '--clean' in argv and stale:
            for k in stale:
                del data['projects'][k]
            tmp = f.with_name(f'{f.name}.agent-runner.tmp')
            tmp.write_text(json.dumps(data, indent=2), encoding='utf-8')
            os.replace(tmp, f)
            print('  removed')
        elif stale:
            print('  run again with --clean to remove them')
    return 0


if __name__ == '__main__':
    sys.exit(clean_real_claude_json(sys.argv[1:]))
