"""`[run] ci_watch`: read the shared branch's GitHub Actions results, so a red CI is one task, not an inbox.

Nothing else on the machine reads them: a workflow that breaks goes on failing on every push the runner
makes, and the only sign is GitHub's failure email for each one. With `ci_watch = ["pages.yml"]` the run
asks `gh` every CI_POLL seconds for the newest finished run of each workflow on the shared branch. When it
is red (failure, timed out, startup failure; a cancelled one says nothing and the one before it decides),
a single `critical` task is filed with the failed jobs, and the last lines of `gh run view --log-failed`
go in its long form, plan/tasks/<ID>.md. No second task while one for that workflow is open (its line says
`<workflow>` on <branch> is red), and a run already judged is never filed again: the newest judged run
is kept in `<notes>/ci-<workflow>.seen`. A landing never waits on any of this.

`ci_watch = "auto"` (the default) watches every workflow in `.github/workflows/` that runs on a push to the
shared branch (`push_workflows`), and only its push runs: a nightly or a manual run is not about the code that
just merged. `false` (or `[]`) turns it off. A `gh` that cannot see the repository (not installed, not
logged in, the wrong account) is said once (`reachable`), not silently retried as "no runs".

The parts that talk to `gh` take a `gh` callable, so the tests give them canned answers.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Callable

CI_POLL = 300        # s between two looks at the workflows
RED = {'failure', 'timed_out', 'startup_failure'}
QUIET = {'cancelled', 'skipped', 'neutral', 'stale', ''}  # finished without saying anything about the code
TAIL = 40            # log lines a task's long form keeps, ending at the last error
GH_TIMEOUT = 60

Gh = Callable[..., subprocess.CompletedProcess]


def gh_in(cwd: Path) -> Gh:
    """`gh` run in `cwd` (it reads the repository from there), no prompt, GH_TIMEOUT to answer."""
    def gh(*a: str) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(['gh', *a], cwd=str(cwd), capture_output=True, text=True,
                                  stdin=subprocess.DEVNULL, timeout=GH_TIMEOUT,
                                  env={**os.environ, 'GH_PROMPT_DISABLED': '1', 'NO_COLOR': '1'})
        except (OSError, subprocess.TimeoutExpired) as e:
            return subprocess.CompletedProcess(['gh', *a], 124, '', str(e))
    return gh


def reachable(gh: Gh) -> str:
    """'' when `gh` can see this repository, else one line saying why it cannot."""
    r = gh('repo', 'view', '--json', 'nameWithOwner')
    if not r.returncode:
        return ''
    why = (r.stderr or r.stdout).strip().splitlines()
    return why[-1][:200] if why else f'gh exited {r.returncode}'


def _on_block(text: str) -> tuple[str, list[str]]:
    """A workflow's top-level `on:` key: (its inline value, its indented lines)."""
    ls = text.splitlines()
    for i, l in enumerate(ls):
        if m := re.match(r"""^["']?on["']?\s*:\s*(.*?)\s*(#.*)?$""", l):
            body = []
            for x in ls[i + 1:]:
                if x.strip() and not x[0].isspace() and not x.lstrip().startswith('#'):
                    break
                body.append(x)
            return m.group(1), body
    return '', []


def _names(value: str, lines: list[str]) -> list[str]:
    """`[a, 'b']` inline, or the `- a` items below it."""
    if value.startswith('['):
        return [v.strip().strip('"\'') for v in value.strip('[]').split(',') if v.strip()]
    if value:
        return [value.strip('"\'')]
    return [m.group(1).strip().strip('"\'') for x in lines if (m := re.match(r'^\s*-\s*(.+?)\s*(#.*)?$', x))]


def runs_on_push(text: str, branch: str) -> bool:
    """Does this workflow (its YAML text) run on a push to `branch`? Reads the common forms of `on:`:
    `on: push`, `on: [push, ...]`, and a `push:` block with `branches` / `branches-ignore` / `tags`."""
    # ponytail: a line-based reading of YAML's usual `on:` shapes, not a YAML parser; anchors or a flow map
    # for the whole key (`on: {push: ...}`) read as no push. Name the workflow in `ci_watch` for those.
    import fnmatch
    value, body = _on_block(text)
    if value:
        return 'push' in _names(value, [])
    items = [x for x in body if x.strip() and not x.lstrip().startswith('#')]
    if not items:
        return False
    top = min(len(x) - len(x.lstrip()) for x in items)
    for i, x in enumerate(items):
        ind, key = len(x) - len(x.lstrip()), x.strip()
        if ind != top:
            continue
        if re.fullmatch(r'-\s*push', key):
            return True
        if not (m := re.match(r'^push\s*:\s*(.*?)\s*(#.*)?$', key)):
            continue
        if m.group(1) in ('', '~', 'null', '{}'):
            sub = []
            for y in items[i + 1:]:
                if len(y) - len(y.lstrip()) <= top:
                    break
                sub.append(y)
        else:
            sub = []
        filters: dict[str, list[str]] = {}
        if m.group(1).startswith('{'):  # `push: { branches: [main] }`
            for k in re.finditer(r'([\w-]+)\s*:\s*(\[[^\]]*\]|[^,}]+)', m.group(1)):
                filters[k.group(1)] = _names(k.group(2).strip(), [])
        sind = min((len(y) - len(y.lstrip()) for y in sub), default=0)
        for j, y in enumerate(sub):
            if len(y) - len(y.lstrip()) == sind and (k := re.match(r'^\s*([\w-]+)\s*:\s*(.*?)\s*(#.*)?$', y)):
                below = []
                for z in sub[j + 1:]:
                    if len(z) - len(z.lstrip()) <= sind and not z.lstrip().startswith('-'):
                        break
                    below.append(z)
                filters[k.group(1)] = _names(k.group(2), below)
        hit = lambda pats: any(fnmatch.fnmatch(branch, p) for p in pats)
        if 'branches' in filters:
            return hit(filters['branches'])
        if 'branches-ignore' in filters:
            return not hit(filters['branches-ignore'])
        return 'tags' not in filters  # tags only: branch pushes do not run it
    return False


def push_workflows(root: Path, branch: str) -> list[str]:
    """The workflow files under `root`/.github/workflows that run on a push to `branch`, sorted."""
    d = root / '.github' / 'workflows'
    if not d.is_dir():
        return []
    out = []
    for f in sorted([*d.glob('*.yml'), *d.glob('*.yaml')]):
        try:
            if runs_on_push(f.read_text(encoding='utf-8', errors='replace'), branch):
                out.append(f.name)
        except OSError:
            pass
    return out


def newest_finished(gh: Gh, workflow: str, branch: str, event: str = '') -> dict | None:
    """The newest run of `workflow` on `branch` that finished saying something (green or red), or None
    (none yet, every recent one cancelled, or `gh` could not answer: not logged in, offline). `event`
    (`push`): only runs that event started."""
    r = gh('run', 'list', '-w', workflow, '-b', branch, '-L', '20', *(['-e', event] if event else []),
           '--json', 'databaseId,status,conclusion,headSha,url,displayTitle,createdAt')
    if r.returncode:
        return None
    try:
        runs = json.loads(r.stdout or '[]')
    except ValueError:
        return None
    done = [x for x in runs if x.get('status') == 'completed' and x.get('conclusion') not in QUIET]
    return max(done, key=lambda x: x['databaseId'], default=None)


def failed_jobs(gh: Gh, run_id: int) -> list[str]:
    r = gh('run', 'view', str(run_id), '--json', 'jobs')
    try:
        return [j['name'] for j in json.loads(r.stdout)['jobs'] if j.get('conclusion') in RED]
    except (ValueError, KeyError, TypeError):
        return []


STAMP = re.compile(r'^\d{4}-\d\d-\d\dT[\d:.]+Z ?')


def log_tail(gh: Gh, run_id: int, n: int = TAIL) -> list[str]:
    """The last `n` lines of the failed jobs' logs up to the last `##[error]`, as `job: line`: the post-job
    cleanup after the error is git housekeeping, not the failure."""
    r = gh('run', 'view', str(run_id), '--log-failed')
    if r.returncode:
        return [f'(gh run view --log-failed: {(r.stderr or r.stdout).strip()[:200]})']
    out = []
    for l in r.stdout.splitlines():
        job, _, rest = l.partition('\t')
        _, _, text = rest.partition('\t')  # the step, often UNKNOWN STEP
        out.append(f'{job}: {STAMP.sub("", text)}'.rstrip())
    end = max((i for i, l in enumerate(out) if '##[error]' in l), default=len(out) - 1) + 1
    return out[max(0, end - n):end]


def marker(workflow: str, branch: str) -> str:
    """What a filed task's line says, and what an open one is recognised by."""
    return f'`{workflow}` on {branch} is red'


def seen_file(notes: Callable[[str], Path], workflow: str) -> Path:
    return notes(f'ci-{re.sub(r"[^A-Za-z0-9_.-]", "_", workflow)}.seen')


def to_file(gh: Gh, workflow: str, branch: str, seen: Path, open_text: str,
            event: str = '') -> tuple[str, list[str]] | None:
    """(task line text, long form lines) for a red run nobody has been told about, else None.

    The newest finished run is judged once: its id goes in `seen` whatever it says, and a run no newer than
    that is not looked at again. A red one with a task for this workflow still open files nothing."""
    run = newest_finished(gh, workflow, branch, event)
    if not run:
        return None
    try:
        last = int(seen.read_text().strip() or 0)
    except (OSError, ValueError):
        last = 0
    if run['databaseId'] <= last:
        return None
    seen.write_text(f'{run["databaseId"]}\n')
    if run['conclusion'] not in RED or marker(workflow, branch) in open_text:
        return None
    jobs = failed_jobs(gh, run['databaseId'])
    tail = log_tail(gh, run['databaseId'])
    sha = run.get('headSha', '')[:8]
    text = (f'CI: {marker(workflow, branch)} ({run["conclusion"]}, run {run["databaseId"]} on {sha}, '
            f'{run["createdAt"][:16].replace("T", " ")} UTC): failed {", ".join(jobs) or "(no job named)"}. '
            f'Make it green; the log\'s last lines are in this task\'s long form, the rest is '
            f'`gh run view {run["databaseId"]} --log-failed`. While this is open no other CI task is filed '
            f'for `{workflow}`. {run["url"]}')
    long = [f'CI run {run["url"]}', '', f'Commit {run.get("headSha", "")}: {run.get("displayTitle", "")}', '',
            f'Failed jobs: {", ".join(jobs) or "(none named)"}', '',
            f'Last {len(tail)} lines of `gh run view {run["databaseId"]} --log-failed`, to the last error:', '',
            '```', *tail, '```']
    return text, long
