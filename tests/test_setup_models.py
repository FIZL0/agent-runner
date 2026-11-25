"""F406d: `agent-runner setup` asks which providers to use, logs in to each and writes [models]; every answer is faked."""
from __future__ import annotations

import builtins
import contextlib
import io
import json
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

from _check import check, eq, git, has, report

from agent_runner import config as CF
from agent_runner import login
from agent_runner import setup as S
from agent_runner import setup_models as M

real_run = subprocess.run
CLAUDE = '/x/claude'


def repo(t: str, toml: str = '', local: str = '') -> Path:
    root = Path(t).resolve()
    git(root, 'init', '-q', '-b', 'main')
    for name, text in (('runner.toml', toml), (CF.LOCAL, local)):
        if text:
            (root / name).write_text(text, encoding='utf-8')
    return root


def setup(root: Path, answers=(), claude: str = '', terminal: bool = True, creds: dict | None = None, code: int = 0,
          logged: bool = False, argv=()):
    """setup's main, all of it faked: (exit, printed, questions asked, (argv) of the programs run)."""
    left, asked, runs = list(answers), [], []

    def answer(q=''):
        asked.append(q)
        if not left:
            raise EOFError
        a = left.pop(0)
        if isinstance(a, BaseException):
            raise a
        return a

    def run(cmd, **kw):
        if cmd[0] == 'git':
            return real_run(cmd, **kw)
        if cmd[1:] == ['auth', 'status']:
            return subprocess.CompletedProcess(cmd, 0, json.dumps({'loggedIn': logged}), '')
        runs.append(list(cmd))
        return subprocess.CompletedProcess(cmd, code)

    out = io.StringIO()
    CF._cfg.cache_clear()
    with mock.patch.object(S, 'offer_ttyd', lambda: None), mock.patch.object(S, 'offer_audit', lambda root: None), mock.patch.object(S, 'at_terminal', lambda: terminal), \
            mock.patch.object(M, 'claude_program', lambda r: claude), mock.patch.object(builtins, 'input', answer), \
            mock.patch.object(login, 'stored', lambda: creds or {}), mock.patch.object(subprocess, 'run', run), \
            mock.patch.dict('os.environ', {'GEMINI_API_KEY': ''}), contextlib.redirect_stdout(out):
        got = S.main(list(argv), cwd=root)
    CF._cfg.cache_clear()
    eq(got, 0, 'setup ends well')
    eq(left, [], 'every answer was asked for')
    return out.getvalue(), asked, runs


def words(runs: list) -> list:
    """The runner's own commands among `runs`, without how it is started."""
    n = len(CF.runner_cmd())
    return [r[n:] for r in runs if r[:n] == CF.runner_cmd()]


def test_claude_only():
    print('Claude only: logged in with claude auth login, [models] on Claude, the session starts')
    with tempfile.TemporaryDirectory() as t:
        root = repo(t)
        out, asked, runs = setup(root, ['1'], claude=CLAUDE)
        has(out, r'1  Claude Code +found, not logged in', 'listed as found')
        has(out, r'2  GitHub Copilot +not logged in .github.com or a GitHub Enterprise domain', 'Copilot too')
        for p in ('Codex', 'Gemini', 'Ollama'):
            has(out, rf'\d  {p} ', f'{p} too')
        eq(len(asked), 1, 'one question')
        eq(runs[0], [CLAUDE, 'auth', 'login'], 'logged in')
        check(len(runs) == 2 and runs[1][0] == CLAUDE, 'then the setup session', runs)
        c = CF.Config(root)
        eq((c.models['code'], c.models['fix'], c.models['kinds']), ('opus', 'opus', CF.DEFAULTS['models']['kinds']), 'models')
        has((root / CF.LOCAL).read_text(encoding='utf-8'), r'(?m)^code = "opus"', 'written')
        git(root, 'add', '-A')
        check(CF.LOCAL not in git(root, 'diff', '--cached', '--name-only'), 'git ignores it')
    with tempfile.TemporaryDirectory() as t:
        root = repo(t, local='[models]\ncode = "copilot:m"\nfix = "sonnet"\nkinds = { F = "copilot:m", D = "haiku" }\n')
        out, _, runs = setup(root, ['claude'], claude=CLAUDE, logged=True)
        has(out, 'Claude Code: already logged in', 'no second login')
        eq(len(runs), 1, 'only the session')
        c = CF.Config(root)
        eq((c.models['code'], c.models['fix']), ('opus', 'sonnet'), 'back on Claude; its own model is kept')
        eq((c.models['kinds']['F'], c.models['kinds']['D']), ('opus', 'haiku'), 'the kinds too')
    with tempfile.TemporaryDirectory() as t:
        root = repo(t, local='[models.kinds]\nF = "copilot:m"\n')
        out, _, _ = setup(root, ['claude'], claude=CLAUDE, logged=True)
        has(out, 'not written.*kinds.*by hand', 'kinds in a section of their own are left to the person, and said')
        check('code' not in (root / CF.LOCAL).read_text(encoding='utf-8'), 'and nothing is half done')


def test_ghe_no_claude():
    print('Copilot on a GitHub Enterprise domain, no Claude Code')
    with tempfile.TemporaryDirectory() as t:
        root = repo(t)
        out, asked, runs = setup(root, ['9', 'copilot', 'not a host', 'https://Corp.ghe.com/', 'copilot:gpt-x'])
        has(out, r'1  Claude Code +not found', 'Claude is not found')
        has(out, 'Use 1 to 5', 'a wrong pick is asked again')
        has(out, 'bare host name', 'a wrong domain too')
        eq(words(runs), [['login', 'copilot', '--enterprise=corp.ghe.com']], 'the login, with the bare host')
        eq(len(runs), 1, 'no session is started')
        check(not any('plan' in q for q in asked), 'nor asked about', asked)
        has(out, 'copilot has no login .*cannot run yet', 'it says what cannot run')
        eq({c_ for r, c_ in CF.Config(root).models.items() if r in ('code', 'fix', 'review', 'control', 'feed', 'docs')}, {'copilot:gpt-x'},
           'F406h: every role is on it')
        check('127' not in out and 'cannot start' not in out, 'and does not fail', out)
        c = CF.Config(root)
        eq((c.models['code'], c.models['fix']), ('copilot:gpt-x',) * 2, 'models')
        eq({c.task_model(k + '1') for k in 'FBTVKDCR'}, {'copilot:gpt-x'}, 'every kind of task runs on it')
        (root / 'plan').mkdir()
        (root / 'plan' / 'TODO.md').write_text('# TODO\n', encoding='utf-8')
        out, asked, runs = setup(root, ['2', '', '', ''], creds={'github-copilot': {'type': 'oauth', 'enterpriseUrl': 'corp.ghe.com'}})
        eq(runs, [], 'logged in already: no login')
        has(out, r'logged in: .*GitHub Enterprise corp.ghe.com', 'the list names the domain')
        eq(CF.Config(root).models['code'], 'copilot:gpt-x', 'Enter keeps the model')
        _, _, again = setup(root, ['2', 'y', '', 'gpt-y'], creds={'github-copilot': {'type': 'oauth'}}, code=1)
        eq(words(again), [['login', 'copilot', '--enterprise=']], 'a login on another domain, when asked for')
        eq(CF.Config(root).models['code'], 'copilot:gpt-y', 'a failed login keeps the pick: its tasks wait for the login')
        eq(len(asked), 4, 'a repo with a plan is asked before the session adds to it')


def test_several():
    print('several: each logged in, the first runs the tasks; a failed login, Ollama, github.com')
    with tempfile.TemporaryDirectory() as t:
        root = repo(t)
        out, _, runs = setup(root, ['5, copilot', '', 'llama3:8b'], code=1)
        eq(words(runs), [['login', 'copilot', '--enterprise=']], 'github.com; Ollama needs none')
        has(out, 'Ollama: needs no login', 'said')
        has(out, r'GitHub Copilot is not logged in: `.* login copilot` failed .exit 1', 'a failed login is said')
        c = CF.Config(root)
        eq((c.models['code'], c.models_local), ('ollama:llama3:8b', True), 'a local provider is allowed')
    with tempfile.TemporaryDirectory() as t:
        root = repo(t)
        out, _, runs = setup(root, ['1 3', 'm'])
        has(out, 'Claude Code is not found: install it', 'Claude picked, not here')
        eq(words(runs), [['login', 'codex']], 'the other is logged in')
        eq(CF.Config(root).models['code'], 'codex:m', 'and runs the tasks')


def test_none():
    print('none picked: nothing is logged in or written')
    for answers in ([''], [KeyboardInterrupt()], []):
        with tempfile.TemporaryDirectory() as t:
            root = repo(t)
            _, asked, runs = setup(root, answers)
            eq((len(asked), runs, (root / CF.LOCAL).exists()), (1, [], False), f'{answers}: one question, nothing done')
    with tempfile.TemporaryDirectory() as t:
        root = repo(t)
        out, _, _ = setup(root, ['4', ''])
        has(out, 'no model given for Gemini', 'no model')
        check(not (root / CF.LOCAL).exists(), 'nothing written')


def test_no_terminal():
    print('no terminal: asks nothing, says the login commands')
    with tempfile.TemporaryDirectory() as t:
        root = repo(t)
        out, asked, runs = setup(root, terminal=False)
        eq((asked, runs, (root / CF.LOCAL).exists()), ([], [], False), 'nothing asked, run or written')
        for p in ('copilot', 'codex', 'gemini'):
            check(f'login {p}`' in out, f'{p} is said', out)
        check('`claude auth login`' in out and '--enterprise company.ghe.com' in out, 'Claude and Enterprise too', out)
        check('login ollama' not in out, 'Ollama needs none', out)


def test_program():
    print('the Claude Code program: [run] agent, else none; its login')
    with tempfile.TemporaryDirectory() as t, tempfile.TemporaryDirectory() as t2:
        root, other = repo(t), repo(t2, '[run]\nagent = "/nowhere/claude"\n')
        CF._cfg.cache_clear()
        with mock.patch('shutil.which', lambda c, **k: CLAUDE if c == 'claude' else None):
            eq(M.claude_program(root), CLAUDE, 'found')
            eq(M.claude_program(other), '', 'the one named is missing')
            has(S.no_claude(other), r'/nowhere/claude.*cannot run yet', 'and said')
        with mock.patch('shutil.which', lambda c, **k: None):
            eq(M.claude_program(root), '', 'none')
            eq(S.launch(root, 'x'), None, 'no launch')
        CF._cfg.cache_clear()
    for out, want in (('{"loggedIn": true}', 'in'), ('{"loggedIn": false}', 'out'), ('what?', ''), ('[]', '')):
        with mock.patch.object(subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(a, 1, out, '')):
            eq(M.claude_state(CLAUDE), want, out)


if __name__ == '__main__':
    raise SystemExit(report([test_claude_only, test_ghe_no_claude, test_several, test_none, test_no_terminal, test_program]))
