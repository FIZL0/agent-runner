#!/usr/bin/env python3
"""Probe terminal coding agents for what agent-runner needs (docs/AGENTS-EVAL.md).

    python tests/agent_matrix.py                 # static: installed? version? headless flags in --help?
    python tests/agent_matrix.py --auth          # + non-interactive login check (no model call)
    python tests/agent_matrix.py --live pi       # + tiny real tasks in a temp git repo (spends tokens)
    python tests/agent_matrix.py --live pi --model github-copilot/gpt-5-mini

Not part of the regular test suite: results depend on what is installed and logged in.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess as sp
import sys
import tempfile
import time
import uuid
from pathlib import Path

# name -> how to probe it. `help`: argv for help text. `need`: requirement -> regex the help must match.
# `auth`: argv that reports login state without prompting. `live`: argv template for one headless run;
# {prompt_file} {prompt} {sid} {model} are filled in; model flags are dropped when no model is given.
AGENTS: dict[str, dict] = {
    'pi': {
        'help': ['--help'],
        'need': {'R1 headless': r'--print|-p\b', 'R2 file prompt': r'@file|@<?path', 'R3 auto-approve': r'--approve',
                 'R4 model': r'--model', 'R5 session id': r'--session-id', 'R7 tool allowlist': r'--tools',
                 'JSON output': r'--mode\b.*json|json'},
        'auth': ['auth', 'check', '--provider', 'github-copilot', '--json'],
        'live': ['--print', '--approve', '--session-id', '{sid}', '[--model', '{model}]', '--', '@{prompt_file}'],
    },
    'copilot': {
        'help': ['--help'],
        'need': {'R1 headless': r'-p, --prompt', 'R3 auto-approve': r'--allow-all-tools|--yolo',
                 'R4 model': r'--model', 'R5 session id': r'--session-id', 'R5 resume': r'--resume',
                 'R7 tool allowlist': r'--allow-tool|--deny-tool|--available-tools',
                 'JSON output': r'--output-format'},
        'auth': None,  # verify: is there a status command that does not open a browser?
        'live': ['-p', '{prompt}', '--allow-all-tools', '--session-id', '{sid}', '[--model', '{model}]'],
    },
    'codex': {
        'help': ['exec', '--help'],
        'need': {'R1 headless': r'exec|Run Codex non-interactively', 'R3 auto-approve': r'--full-auto|--dangerously|bypass',
                 'R4 model': r'--model', 'R5 resume': r'resume', 'JSON output': r'--json',
                 'R2 stdin prompt': r'stdin|-\s'},
        'auth': ['login', 'status'],
        'live': ['exec', '--full-auto', '--skip-git-repo-check', '[--model', '{model}]', '{prompt}'],
    },
    'opencode': {
        'help': ['run', '--help'],
        'need': {'R1 headless': r'run', 'R4 model': r'--model|-m\b', 'R5 session': r'--session|-s\b',
                 'JSON output': r'--format', 'R2 file prompt': r'--file|-f\b'},
        'auth': ['auth', 'list'],
        'live': ['run', '[--model', '{model}]', '{prompt}'],
    },
    'arctic': {  # opencode-style packaging; flags unverified
        'help': ['--help'], 'need': {'R1 headless': r'\brun\b|--print|-p\b', 'R4 model': r'--model'},
        'auth': None, 'live': None,
    },
    'crush': {
        'help': ['--help'], 'need': {'R1 headless': r'\brun\b', 'R4 model': r'--model', 'JSON output': r'json'},
        'auth': None, 'live': ['run', '{prompt}'],
    },
    'claude': {
        'help': ['--help'],
        'need': {'R1 headless': r'-p, --print', 'R3 auto-approve': r'--permission-mode', 'R4 model': r'--model',
                 'R5 session id': r'--session-id', 'R7 tool allowlist': r'--allowedTools|--tools',
                 'JSON output': r'--output-format'},
        'auth': None,
        'live': ['-p', '{prompt}', '--permission-mode', 'bypassPermissions', '--session-id', '{sid}',
                 '[--model', '{model}]'],
    },
}

# Live checks: (name, prompt, check(repo, output) -> bool). Each runs in a fresh temp git repo.
MARK = 'ZEBRA-7731'
LIVE = [
    ('B1 answers and exits', 'Reply with exactly the word READY and nothing else.',
     lambda repo, out: 'READY' in out),
    ('B3 edits a file unprompted', 'Create a file named hello.txt containing exactly: hi from the agent',
     lambda repo, out: (repo / 'hello.txt').exists() and 'hi from the agent' in (repo / 'hello.txt').read_text()),
    ('B3 runs a shell command', 'Run `git log --oneline -1` in a shell and reply with the commit subject only.',
     lambda repo, out: 'seed commit' in out),
    ('B2 long prompt intact', 'x' * 150_000 + f'\nIgnore the filler above. Reply with the code word: {MARK}',
     lambda repo, out: MARK in out),
]


def run(argv: list[str], timeout: int = 60, **kw) -> tuple[int, str]:
    try:
        p = sp.run(argv, capture_output=True, text=True, encoding='utf-8', errors='replace',
                   stdin=sp.DEVNULL, timeout=timeout, **kw)
        return p.returncode, (p.stdout or '') + (p.stderr or '')
    except sp.TimeoutExpired:
        return 124, 'timeout'
    except OSError as e:
        return 127, str(e)


def fill(template: list[str], model: str, **vals) -> list[str]:
    """Fill {placeholders}; drop the bracketed [--model {model}] pair when no model is given."""
    out, skip = [], False
    for a in template:
        if a.startswith('['):
            skip = not model
            a = a[1:]
        end = a.endswith(']')
        a = a.rstrip(']') if end else a
        if not skip:
            out.append(a.format(model=model, **vals))
        if end:
            skip = False
    return out


def static(name: str, spec: dict, exe: str) -> dict:
    row = {'version': run([exe, '--version'], 20)[1].strip().splitlines()[:1]}
    _, text = run([exe, *spec['help']], 30)
    for req, pat in spec['need'].items():
        row[req] = bool(re.search(pat, text, re.I))
    return row


def auth(spec: dict, exe: str) -> str:
    if not spec.get('auth'):
        return 'no non-interactive check known'
    code, out = run([exe, *spec['auth']], 30)
    return f'exit {code}: {" ".join(out.split())[:120]}'


def live(name: str, spec: dict, exe: str, model: str) -> list[tuple[str, bool, float, str]]:
    results = []
    for title, prompt, ok in LIVE:
        with tempfile.TemporaryDirectory(prefix=f'am-{name}-') as d:
            repo = Path(d)
            run(['git', 'init', '-q'], cwd=repo)
            (repo / 'README.md').write_text('seed\n')
            run(['git', 'add', '.'], cwd=repo)
            run(['git', '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'seed commit'], cwd=repo)
            pf = repo.parent / f'{repo.name}.prompt'
            pf.write_text(prompt, encoding='utf-8')
            argv = [exe, *fill(spec['live'], model, prompt=prompt, prompt_file=str(pf), sid=str(uuid.uuid4()))]
            if len(prompt) > 30_000 and '{prompt}' in ' '.join(spec['live']):
                results.append((title, False, 0.0, 'prompt only passes on the command line (R2 gap)'))
                continue
            t = time.time()
            code, out = run(argv, 600, cwd=repo, env={**os.environ, 'NODE_USE_SYSTEM_CA': '1'})
            passed = code == 0 and ok(repo, out)
            results.append((title, passed, time.time() - t, f'exit {code}' + ('' if passed else f': {out[-200:]!r}')))
            pf.unlink(missing_ok=True)
    return results


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('agents', nargs='*', default=list(AGENTS))
    ap.add_argument('--auth', action='store_true', help='also check login state (no model call)')
    ap.add_argument('--live', action='store_true', help='also run tiny real tasks (spends tokens)')
    ap.add_argument('--model', default='', help='model id for --live, e.g. github-copilot/gpt-5-mini')
    a = ap.parse_args()
    for name in a.agents:
        spec = AGENTS[name]
        exe = shutil.which(name)
        print(f'\n== {name}: {exe or "not installed"}')
        if not exe:
            continue
        for k, v in static(name, spec, exe).items():
            print(f'  {k:22} {v if not isinstance(v, bool) else ("yes" if v else "NO")}')
        if a.auth or a.live:
            print(f'  {"auth":22} {auth(spec, exe)}')
        if a.live:
            if not spec.get('live'):
                print('  live                   no headless template yet')
                continue
            for title, passed, secs, note in live(name, spec, exe, a.model):
                print(f'  {"PASS" if passed else "FAIL"} {title:30} {secs:6.1f}s  {note}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
