"""F406e `run review ID`: the spec review as a fresh one-shot on `[models] review`, any provider's.

A Claude Code session with a claude review model hands the review to its `review` subagent instead. A session on the
harness loop has no subagents, and a subagent cannot run another provider's model: both run this before `done`. The
one-shot is given only the task's diff and brief; its findings are printed, so the session reads them as the command's
output. A claude model runs as `claude -p` with Read only, another provider's in the harness loop with read only.
"""
from __future__ import annotations

import argparse
import json
import subprocess as sp
import sys
from pathlib import Path

from agent_runner import plat, state
from agent_runner.brief import brief_for, SUBAGENTS
from agent_runner.gitops import git
from agent_runner.tools import task_here

TIMEOUT = 900  # s the one-shot gets

ASK = """{role}

Say, in under 300 words, each finding quoting the task's words: (a) what the task asked for that is missing or partial, \
(b) what the diff does that was not asked, (c) what looks implemented but wrong. With none, answer "nothing".

The task's brief:

{brief}

The diff (`git diff {base}...HEAD`):

{diff}
"""


def prompt(tid: str, base: str, cwd: Path, diff: str) -> str:
    return ASK.format(role=SUBAGENTS['review'][1], brief=brief_for(tid, cwd), base=base, diff=diff)


def claude_once(model: str, text: str, cwd: Path) -> tuple[str, str]:
    """(the answer, why it failed) of a headless Claude Code one-shot with Read only, `text` on stdin."""
    from agent_runner.control import control_env
    from agent_runner.sched import agent_held
    if bad := agent_held():  # B764c
        return '', f'the one-shot on {model} did not run: {bad}'
    argv = [plat.exe(state.C.run['agent']), '-p', '--model', model, '--tools', 'Read', '--permission-mode', 'dontAsk',
            '--strict-mcp-config', '--setting-sources', '', '--settings', json.dumps({'autoMemoryEnabled': False})]
    try:
        r = sp.run(argv, cwd=str(cwd), env=control_env(), input=text, capture_output=True, text=True,
                   encoding='utf-8', errors='replace', timeout=TIMEOUT)
    except (OSError, sp.SubprocessError) as e:
        return '', f'the one-shot on {model} did not run: {e}'
    said = (r.stdout or '').strip()
    if r.returncode or not said:
        end = ' '.join(f'{r.stderr or ""} {said}'.split())[-300:]
        return '', f'the one-shot on {model} gave no answer (exit {r.returncode}): {end}'
    return said, ''


def review(tid: str, base: str, cwd: Path) -> tuple[str, str]:
    """(the findings, why there are none) of a fresh one-shot's spec review of `tid`'s diff in worktree `cwd`."""
    from agent_runner.feed import harness_once
    from agent_runner.slots import on_harness
    r = git('diff', f'{base}...HEAD', cwd=cwd)
    if r.returncode:
        return '', f'git diff {base}...HEAD failed: {r.stderr.strip()}'
    if not r.stdout.strip():
        return '', f'git diff {base}...HEAD is empty: commit the work first'
    model, text = state.C.models['review'], prompt(tid, base, cwd, r.stdout)
    return harness_once(model, text, cwd, TIMEOUT) if on_harness(model) else claude_once(model, text, cwd)


def cmd_review(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog='run review', description="The spec review before `done`: a fresh one-shot on "
                                 "[models] review is given only this worktree's committed diff and the task's brief, "
                                 'and its findings are printed.')
    ap.add_argument('id', nargs='?', help="the task (default: this worktree's task/<ID> branch)")
    ap.add_argument('--base', help='the branch the diff is taken against (default: the shared branch)')
    a = ap.parse_args(argv)
    state.init()
    tid = a.id or task_here()
    if not tid:
        print('run review: no task: this worktree is not on a task/<ID> branch (give the ID)', file=sys.stderr)
        return 2
    top = git('rev-parse', '--show-toplevel', cwd=Path.cwd())
    cwd = Path(top.stdout.strip()) if not top.returncode else Path.cwd()
    said, why = review(tid, a.base or state.default_branch(), cwd)
    if why:
        print(f'run review: no review: {why}', file=sys.stderr)
        return 1
    print(said)
    return 0


# --- F444: the Review page: each waiting change's diff and why, a question about it, a better way ---------------------
#
# With `[run] approve`, a pitch's page is the Review page: per change what its agent wrote (why), its diff
# (`[run] approve_diff_lines` lines of it), and the questions the person asked about it with their answers.
# `agent-runner pitch ask pitch1 F1 "…"` asks one (a fresh one-shot on `[models] review` given the change's diff, why
# and the question); `pitch better pitch1 F1 --why "…"` asks for a better way (the change is undone and its task
# reopened with that note); `pitch approve pitch1` approves them. The change waits after landing, on the local
# shared branch, and is pushed once approved.

ASK_CHANGE = """You answer a person's question about one change that is merged here and waits for their approval.
Answer in under 200 words, plainly, quoting the diff where it helps. Say when the diff does not show the answer.

The change: {title} ({tid})

What its agent wrote of it:
{why}

Its diff:

{diff}

The person's question: {q}
"""


def change_diff(x: dict, limit: int | None = None) -> tuple[str, int]:
    """(change `x`'s diff, cut to `limit` lines, and how many lines it has in all); ('', 0) with none to show."""
    limit = state.C.run.get('approve_diff_lines', 400) if limit is None else limit
    if not (limit and x.get('before') and x.get('after')):
        return '', 0
    if not x.get('files'):  # the plan's files are left out of a change's files, and so of its diff
        return '', 0
    r = state.git('diff', '--no-color', '--no-renames', x['before'], x['after'], '--', *x['files'])
    lines = r.stdout.splitlines() if not r.returncode else []
    return '\n'.join(lines[:limit]), len(lines)


def asked_file(tid: str) -> Path:
    return state.C.notes('pitches', f'{tid}.asked.json')


def asked(tid: str) -> list[dict]:
    """The questions the person asked about change `tid`, each {q, a, at}, oldest first."""
    try:
        v = json.loads(asked_file(tid).read_text(encoding='utf-8'))
        return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []
    except (OSError, ValueError):
        return []


def why_text(x: dict) -> str:
    say = x.get('say') or {}
    return '\n'.join(f'{h}: {say[k]}' for k, h in (('what', 'What'), ('why', 'Why'), ('try', 'Try it'),
                                                    ('risk', 'Risk')) if say.get(k)) or x.get('subject', '')


def ask_change(x: dict, q: str, cwd: Path, once=None) -> tuple[str, str]:
    """(the answer, why there is none) to question `q` about change `x`; a kept answer is added to `asked`."""
    diff, n = change_diff(x, max(400, state.C.run.get('approve_diff_lines', 400) or 0))
    text = ASK_CHANGE.format(title=x.get('title', ''), tid=x['id'], why=why_text(x) or '(nothing)', q=q,
                             diff=(diff + (f'\n… ({n} lines in all)' if n > diff.count('\n') + 1 else '')) or '(none)')
    if once is None:
        from agent_runner.feed import harness_once
        from agent_runner.slots import on_harness
        model = state.C.models['review']
        once = (lambda t: harness_once(model, t, cwd, TIMEOUT)) if on_harness(model) else \
            (lambda t: claude_once(model, t, cwd))
    said, why = once(text)
    if said:
        import time
        f = asked_file(x['id'])
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(asked(x['id']) + [{'q': q, 'a': said, 'at': time.time()}], indent=1) + '\n',
                     encoding='utf-8')
    return said, why


def _esc(s) -> str:
    import html
    return html.escape(str(s or ''))


def diff_html(x: dict) -> str:
    """Change `x`'s diff on its Review page: folded, added lines green, removed red."""
    diff, n = change_diff(x)
    if not diff:
        return ''
    rows = []
    for l in diff.splitlines():
        cls = ('a' if l.startswith('+') and not l.startswith('+++') else 'd' if l.startswith('-') and
               not l.startswith('---') else 'h' if l.startswith(('diff ', '@@')) else '')
        rows.append(f'<span class="{cls}">{_esc(l)}</span>' if cls else _esc(l))
    shown = diff.count('\n') + 1
    cut = f'<p class="m">{shown} of {n} lines shown.</p>' if n > shown else ''
    return (f'<details class="diff"><summary>The diff ({n} lines)</summary><pre>' + '\n'.join(rows)
            + f'</pre>{cut}</details>')


def asked_html(tid: str) -> str:
    qs = asked(tid)
    if not qs:
        return ''
    return '<section><h3>You asked</h3>' + ''.join(
        f'<p><b>{_esc(x.get("q"))}</b></p><p>{_esc(x.get("a")).replace(chr(10), "<br>")}</p>' for x in qs) + '</section>'


def answers_html(pid: str, tid: str) -> str:
    """How to answer change `tid` of pitch `pid`, as commands (the Review page is a copy, with no buttons)."""
    cmd = state.C.command if hasattr(state.C, 'command') else 'agent-runner'
    return ('<section><h3>Answer it</h3><ul>'
            f'<li>Ask about it: <code>{_esc(cmd)} pitch ask {pid} {tid} "your question"</code></li>'
            f'<li>Ask for a better way: <code>{_esc(cmd)} pitch better {pid} {tid} --why "what you want instead"'
            f'</code></li><li>Approve: <code>{_esc(cmd)} pitch approve {pid}</code></li></ul></section>')


REVIEW_STYLE = """<style>
details.diff summary{cursor:pointer;color:var(--muted)}
details.diff pre{font-family:ui-monospace,monospace;font-size:.78rem;overflow-x:auto;margin:6px 0 0;padding:8px;
border:1px solid var(--line);border-radius:8px;white-space:pre}
details.diff .a{color:#1a7f37}details.diff .d{color:#cf222e}details.diff .h{color:var(--muted)}
@media (prefers-color-scheme: dark){details.diff .a{color:#56d364}details.diff .d{color:#f85149}}
</style>"""
