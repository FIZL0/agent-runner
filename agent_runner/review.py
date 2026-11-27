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
    ap.add_argument('--page', action='store_true', help="F444d: write the Review page of the task's change that waits "
                    'on its task branch or as a pull request, and print its path')
    ap.add_argument('--ask', metavar='QUESTION', help='F444d: ask about that waiting change; the answer is printed '
                    'and kept on its Review page')
    a = ap.parse_args(argv)
    state.init()
    tid = a.id or task_here()
    if not tid:
        print('run review: no task: this worktree is not on a task/<ID> branch (give the ID)', file=sys.stderr)
        return 2
    top = git('rev-parse', '--show-toplevel', cwd=Path.cwd())
    cwd = Path(top.stdout.strip()) if not top.returncode else Path.cwd()
    if a.page or a.ask:
        return cmd_where(tid, a.base or state.default_branch(), a.page, a.ask, cwd)
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


def asked_file(key: str) -> Path:
    """Where the questions about one change (its `key`, ID@merge) are kept: a reopened task's next change starts empty."""
    return state.C.notes('pitches', f'{key}.asked.json')


def asked(key: str) -> list[dict]:
    """The questions the person asked about change `key`, each {q, a, at}, oldest first."""
    try:
        v = json.loads(asked_file(key).read_text(encoding='utf-8'))
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
        f = asked_file(x['key'])
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(asked(x['key']) + [{'q': q, 'a': said, 'at': time.time()}], indent=1) + '\n',
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


def asked_html(key: str) -> str:
    qs = asked(key)
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


# --- F444d: the Review page of a change that waits on its task branch, or as a pull request in PR mode ----------------
#
# A change that is not merged here yet waits elsewhere: on its task/<ID> branch, or (PR mode) as the pull request
# that carries it. It gets the same Review page: its diff, what its agent wrote (why), the questions asked about it,
# and how to answer it. `run review ID --page` writes it; `run review ID --ask "…"` asks about the change.

def _change(tid: str, before: str, after: str, where: str, url: str = '') -> dict:
    from agent_runner import pitch as PI
    from agent_runner.plan_concepts import title_of
    plan = PI._plan_prefix()
    files = state.git('diff', '--name-only', '--no-renames', before, after).stdout.split('\n')
    line = PI._line_of(tid, after)
    return {'key': f'{tid}@{after[:12]}', 'id': tid, 'title': title_of(line) if line else tid, 'before': before,
            'after': after, 'files': [f for f in files if f and not (plan and f.startswith(plan))],
            'say': PI.part(tid), 'subject': state.git('log', '-1', '--format=%s', after).stdout.strip(),
            'where': where, 'url': url}


def waiting_change(tid: str, base: str) -> tuple[dict | None, str]:
    """(task `tid`'s change as it waits now, why there is none): in its pull request when PR mode holds one, else on
    task/<tid> against where it leaves `base`."""
    from agent_runner import pr
    rec = pr.of(tid)
    if rec and rec.get('head') and rec.get('base'):
        tip = rec.get('tips', {}).get(tid) or rec['head']
        before = state.git('merge-base', rec['base'], tip).stdout.strip() or rec['base']
        return _change(tid, before, tip, 'pr', rec.get('url', '')), ''
    tip = state.git('rev-parse', '-q', '--verify', f'refs/heads/task/{tid}^{{commit}}').stdout.strip()
    if not tip:
        return None, f'{tid} has no task/{tid} branch and no pull request'
    before = state.git('merge-base', base, tip).stdout.strip()
    if not before or before == tip:
        return None, f'task/{tid} has nothing that {base} does not have'
    return _change(tid, before, tip, 'branch'), ''


def where_html(x: dict) -> str:
    if x.get('where') == 'pr':
        link = f' <a href="{_esc(x["url"])}">{_esc(x["url"])}</a>' if x.get('url') else ''
        return f'<p class="m">It waits as a pull request.{link}</p>'
    return f'<p class="m">It waits on its branch task/{_esc(x["id"])}, not merged yet.</p>'


def where_answers_html(x: dict) -> str:
    """How to answer a change that waits on its branch or as a pull request, as commands."""
    cmd = state.C.command if hasattr(state.C, 'command') else 'agent-runner'
    tid = _esc(x['id'])
    better = (f'say so on the pull request' + (f' (<a href="{_esc(x["url"])}">open it</a>)' if x.get('url') else '')
              if x.get('where') == 'pr' else f'<code>{_esc(cmd)} plan note {tid} "what you want instead"</code>')
    return ('<section><h3>Answer it</h3><ul>'
            f'<li>Ask about it: <code>{_esc(cmd)} review {tid} --ask "your question"</code></li>'
            f'<li>Ask for a better way: {better}</li></ul></section>')


def where_page_html(x: dict, project: str = '') -> str:
    """The Review page of change `x` that waits on its branch or as a pull request."""
    why = why_text(x)
    body = f'<section><h3>Why</h3><p>{_esc(why).replace(chr(10), "<br>")}</p></section>' if why else ''
    return (f'<title>{_esc(project)} {_esc(x["id"])}</title>\n{REVIEW_STYLE}<div class="wrap"><article>'
            f'<h1>{_esc(x["title"])}</h1><p class="m">{_esc(x["id"])}</p>{where_html(x)}{body}'
            + diff_html(x) + asked_html(x['key']) + where_answers_html(x) + '</article></div>\n')


def page_file(tid: str) -> Path:
    return state.C.notes('review', f'{tid}.html')


def cmd_where(tid: str, base: str, page: bool, q: str | None, cwd: Path) -> int:
    x, why = waiting_change(tid, base)
    if not x:
        print(f'run review: {why}', file=sys.stderr)
        return 1
    if q:
        said, why = ask_change(x, q, cwd)
        if not said:
            print(f'run review: no answer: {why}', file=sys.stderr)
            return 1
        print(said)
    if page or q:
        f = page_file(tid)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(where_page_html(x, state.C.name if hasattr(state.C, 'name') else ''), encoding='utf-8')
        print(f)
    return 0
