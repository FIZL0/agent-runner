"""`[run] ci_watch`: read the shared branch's GitHub Actions results, so a red CI is one task, not an inbox.

Nothing else on the machine reads them: a workflow that breaks goes on failing on every push the runner
makes, and the only sign is GitHub's failure email for each one. With `ci_watch = ["pages.yml"]` the run
asks `gh` every CI_POLL seconds for the newest finished run of each workflow on the shared branch. When it
is red (failure, timed out, startup failure; a cancelled one says nothing and the one before it decides),
a single `critical` task is filed with the failed jobs and the failing tests (`failing_tests`), and the FAIL
lines and tracebacks of `gh run view --log-failed`, then its last lines, go in its long form,
plan/tasks/<ID>.md. No second task while one for that workflow is open (its line says `<workflow>` on
<branch> is red): a failing test it does not name yet is named on it. A closed task that names a failing
test is opened again, its earlier fixes linked (`file_red`), and a run already judged is never filed again:
the newest judged run is kept in `<notes>/ci-<workflow>.seen`. With two closed in a week for the workflow (`closed_repeats`), the
third is filed blocked on a person rather than ahead of all work. A landing never waits on any of this.

`ci_watch = "auto"` (the default) watches every workflow in `.github/workflows/` that runs on a push to the
shared branch (`push_workflows`), and only its push runs: a nightly or a manual run is not about the code that
just merged. `false` (or `[]`) turns it off. A `gh` that cannot see the repository (not installed, not
logged in, the wrong account) is said once (`reachable`), not silently retried as "no runs".

The parts that talk to `gh` take a `gh` callable, so the tests give them canned answers.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Callable, NamedTuple

from agent_runner import plan as P

CI_POLL = 300        # s between two looks at the workflows
RED = {'failure', 'timed_out', 'startup_failure'}
QUIET = {'cancelled', 'skipped', 'neutral', 'stale', ''}  # finished without saying anything about the code
TAIL = 40            # log lines a task's long form keeps, ending at the last error
BEFORE, AFTER = 3, 5  # log lines kept around each FAIL line
FAIL_MAX = 200       # FAIL lines with their context a long form keeps
NAMED = 5            # failing tests a task's line names; its long form has them all
GH_TIMEOUT = 60
CI_KIND = 'B'        # C14: the id prefix a red run's task gets (was [run] ci_kind)

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
           '--json', 'databaseId,status,conclusion,headSha,url,displayTitle,createdAt,attempt')
    if r.returncode:
        return None
    try:
        runs = json.loads(r.stdout or '[]')
    except ValueError:
        return None
    done = [x for x in runs if x.get('status') == 'completed' and x.get('conclusion') not in QUIET]
    if not (run := max(done, key=lambda x: x['databaseId'], default=None)):
        return None
    # a newer run still going: what it says is the news (`to_file` waits for it)
    return {**run, 'newer': any(x['databaseId'] > run['databaseId'] and x.get('status') != 'completed' for x in runs)}


def failed_jobs(gh: Gh, run_id: int) -> list[str]:
    r = gh('run', 'view', str(run_id), '--json', 'jobs')
    try:
        return [j['name'] for j in json.loads(r.stdout)['jobs'] if j.get('conclusion') in RED]
    except (ValueError, KeyError, TypeError):
        return []


STAMP = re.compile(r'^\d{4}-\d\d-\d\dT[\d:.]+Z ?')


Log = list[tuple[str, str]]  # (job, text) per line


def failed_log(gh: Gh, run_id: int) -> tuple[Log, str]:
    """The failed jobs' whole log, and '' or why `gh` could not read it."""
    r = gh('run', 'view', str(run_id), '--log-failed')
    if r.returncode:
        return [], f'(gh run view --log-failed: {(r.stderr or r.stdout).strip()[:200]})'
    out = []
    for l in r.stdout.splitlines():
        job, _, rest = l.partition('\t')
        _, _, text = rest.partition('\t')  # the step, often UNKNOWN STEP
        out.append((job, COLOUR.sub('', STAMP.sub('', text.lstrip('\ufeff'))).rstrip()))
    return out, ''


def _shown(log: Log) -> list[str]:
    return [f'{job}: {text}'.rstrip() for job, text in log]


def log_tail(log: Log, n: int = TAIL) -> list[str]:
    """The last `n` lines of a log up to the last `##[error]`, as `job: line`: the post-job cleanup after the
    error is git housekeeping, not the failure."""
    end = max((i for i, (_, l) in enumerate(log) if '##[error]' in l), default=len(log) - 1) + 1
    return _shown(log[max(0, end - n):end])


COLOUR = re.compile(r'\x1b\[[0-9;]*m')
FAIL_LINE = re.compile(r'^\s*(?:--- )?FAIL(?:ED|URE)?\b|^test .+ \.\.\. FAILED$|\sFAILED(?:\s+\[\s*\d+%\])?$'
                       r'|^\[\s+FAILED\s+\]|^\s*[✗✕✖]\s|^\s*not ok \d+|^ERROR:? (?:test|\S+::)')
TRACEBACK = 'Traceback (most recent call last)'
FAIL_NAMES = [re.compile(x) for x in (
    r'^\s*--- FAIL: (\S+)',                                # go
    r'^test (.+) \.\.\. FAILED$',                           # cargo
    r'^\[\s+FAILED\s+\] ([A-Za-z_]\w*\.\S+?),?(?:\s|$)',  # gtest
    r'^FAILED (\S+::.+?)(?: - .*)?$',                      # pytest's summary
    r'^(\S+::.+?) FAILED(?:\s+\[\s*\d+%\])?$',            # pytest -v
    r'^ERROR:? (test\w* \(.+|\S+::.+?)(?: - .*)?$',           # unittest, pytest: it did not get to fail
    r'^\s*not ok \d+ (?:- )?(.+)$',                        # TAP
    r'^\s*[✗✕✖]\s+(.+)$',
    r'^\s*FAIL(?:ED)?:? +([^\s(].*)$',                     # this repo's tests, unittest, jest
)]
TIMING = re.compile(r'\s+\(?\d+(?:\.\d+)? ?m?s\)?$')
SUITE = re.compile(r'^== (\S+)$')


def _key(name: str) -> str:
    """A test's name as a task's line can hold it: nothing the plan would read as a note, a field or a mark."""
    name = re.sub(r'\s+', ' ', TIMING.sub('', name)).strip()
    for a, b in (('`', "'"), ('|', '/'), ('—', '-'), ('(', '['), (')', ']'), ('**', '*'), ('BLOCKED:', 'BLOCKED')):
        name = name.replace(a, b)
    return name[:100].strip()


def _traceback_end(log: Log, i: int) -> int:
    """The index of the exception line that ends the traceback at log[i]."""
    job, l = log[i]
    ind, end = len(l) - len(l.lstrip()), i + 1
    while end < len(log) - 1 and end - i < 40 and log[end][0] == job and \
            (not log[end][1].strip() or len(log[end][1]) - len(log[end][1].lstrip()) > ind):
        end += 1
    return min(end, len(log) - 1)


def failing_tests(log: Log) -> list[str]:
    """The failing tests a log names, in its order. A test file (`== tests/test_x.py`) that names none, has a
    traceback and did not get to its `all checks passed` crashed: it is named itself. With nothing named at all,
    the exceptions of the log's tracebacks."""
    out: list[str] = []
    at: dict[str, int] = {}                  # job -> its test file's place in `suites`
    suites: list[list] = []                  # [its name, a traceback, named or passed, where its name goes in `out`]
    for job, l in log:
        if m := SUITE.match(l):
            at[job] = len(suites)
            suites.append([m[1], False, False, len(out)])
            out.append('')
        suite = suites[at[job]] if job in at else None
        name = next((m[1] for p in FAIL_NAMES if (m := p.match(l))), '')
        if name:
            out.append(_key(name))
        if suite and (name or l.strip() == 'all checks passed'):
            suite[2] = True
        elif suite and l.lstrip().startswith(TRACEBACK):
            suite[1] = True
    for name, crashed, told, i in suites:
        if crashed and not told:
            out[i] = _key(name)
    if not any(out):
        out = [_key(log[_traceback_end(log, i)][1]) for i, (_, l) in enumerate(log)
               if l.lstrip().startswith(TRACEBACK)]
    return list(dict.fromkeys(x for x in out if x))


def fail_lines(log: Log) -> list[str]:
    """Each FAIL line and traceback of a log with a few lines around it, as `job: line`, `...` between places."""
    core: set[int] = set()
    for i, (_, l) in enumerate(log):
        if l.lstrip().startswith(TRACEBACK):
            core.update(range(i, _traceback_end(log, i) + 1))
        elif FAIL_LINE.search(l):
            core.add(i)
    at = sorted({j for i in core for j in range(max(0, i - BEFORE), min(len(log), i + AFTER + 1))})
    if len(at) > FAIL_MAX:
        at = sorted(core)  # too many for their context: every failure before any of it
    shown = _shown(log)
    out: list[str] = []
    for n, i in enumerate(at[:FAIL_MAX]):
        if n and at[n - 1] != i - 1:
            out.append('...')
        out.append(shown[i])
    if len(at) > FAIL_MAX:
        out.append(f'... ({len(at) - FAIL_MAX} more such lines in the log)')
    return out


def marker(workflow: str, branch: str) -> str:
    """What a filed task's line says, and what an open one is recognised by."""
    return f'`{workflow}` on {branch} is red'


def ticked_names(tests: list[str], most: int = 0) -> str:
    """`a`, `b`: how a task's line and long form name failing tests, at most `most` of them (0: all)."""
    out = ', '.join(f'`{t}`' for t in (tests[:most] if most else tests))
    return out + (f' and {len(tests) - most} more' if most and len(tests) > most else '')


class Red(NamedTuple):
    """A red run to file: a new task's line and the long form's section, and what `file_red` keys it by."""
    text: str
    long: list[str]
    tests: list[str]
    run: dict
    mark: str


def seen_file(notes: Callable[[str], Path], workflow: str) -> Path:
    return notes(f'ci-{re.sub(r"[^A-Za-z0-9_.-]", "_", workflow)}.seen')


def to_file(gh: Gh, workflow: str, branch: str, seen: Path, open_text: str,
            event: str = '', rerun: bool = False, say: Callable[[str], None] = lambda _: None
            ) -> Red | None:
    """What to file for a red run nobody has been told about, else None.

    The newest finished run is judged once: its id goes in `seen` whatever it says, and a run no newer than
    that is not looked at again. Not while a newer run is still going: that one is judged when it ends. A
    red one with a task for this workflow still open is returned only when its log names a failing test
    (`file_red` names it there). With `rerun`, a red run on its first
    attempt has its failed jobs run again (`gh run rerun --failed`) instead, and is judged on the second:
    a hosted runner that never came, or a network that dropped, is not the code's to fix. Only the newest
    run is ever rerun, so an older commit's deploy never lands over a newer one's."""
    run = newest_finished(gh, workflow, branch, event)
    if not run or run.get('newer'):
        return None
    try:
        last = int(seen.read_text().strip() or 0)
    except (OSError, ValueError):
        last = 0
    if run['databaseId'] <= last:
        return None
    if rerun and run['conclusion'] in RED and run.get('attempt', 1) < 2 and \
            marker(workflow, branch) not in open_text and \
            not gh('run', 'rerun', str(run['databaseId']), '--failed').returncode:
        say(f'`{workflow}` run {run["databaseId"]} on {branch} is red ({", ".join(failed_jobs(gh, run["databaseId"])) or "no job named"}); '
            f'its failed jobs are running again, and only a second red files a task')
        return None
    seen.write_text(f'{run["databaseId"]}\n')
    if run['conclusion'] not in RED:
        return None
    log, why = failed_log(gh, run['databaseId'])
    if why and marker(workflow, branch) in open_text:
        seen.write_text(f'{last}\n')  # which test failed is not known yet: the next look reads it again
        return None
    tests = failing_tests(log)
    if marker(workflow, branch) in open_text and not tests:
        return None
    jobs = failed_jobs(gh, run['databaseId'])
    fails, tail = fail_lines(log), log_tail(log) or [why or '(the log is empty)']
    sha = run.get('headSha', '')[:8]
    named = f'Failing: {ticked_names(tests, NAMED)}. ' if tests else ''
    text = (f'CI: {marker(workflow, branch)} ({run["conclusion"]}, run {run["databaseId"]} on {sha}, '
            f'{run["createdAt"][:16].replace("T", " ")} UTC): failed {", ".join(jobs) or "(no job named)"}. {named}'
            f'Make it green; the log\'s FAIL lines and last lines are in this task\'s long form, the rest is '
            f'`gh run view {run["databaseId"]} --log-failed`. While this is open no other CI task is filed '
            f'for `{workflow}`; other failing tests are named here. {filed_stamp()} {run["url"]}')
    long = [f'CI run {run["url"]}', '', f'Commit {run.get("headSha", "")}: {run.get("displayTitle", "")}', '',
            f'Failed jobs: {", ".join(jobs) or "(none named)"}', '']
    if tests:
        long += [f'Failing tests: {ticked_names(tests)}', '']
    if fails:
        long += ['FAIL lines and tracebacks:', '', '```', *fails, '```', '']
    long += [f'Last {len(tail)} lines of `gh run view {run["databaseId"]} --log-failed`, to the last error:', '',
             '```', *tail, '```']
    return Red(text, long, tests, run, marker(workflow, branch))


def _last_filed(line: str) -> str:
    return max(FILED.findall(line), default='')


def fixes(tid: str, git: Callable[..., subprocess.CompletedProcess]) -> list[str]:
    """The commits that landed a task, newest first: its merges, else the commits whose subject starts with it."""
    e = re.escape(tid)
    for pat in (f"^Merge branch 'task/{e}'", f'^{e}[ :]'):
        r = git('log', '-n', '3', '--format=%h', '-E', f'--grep={pat}')
        if not r.returncode and r.stdout.split():
            return r.stdout.split()
    return []


class Filed(NamedTuple):
    tid: str
    how: str               # what was done, for the run log
    paths: list[Path]      # the plan files it changed


def file_red(red: Red, todo: Path, done: Path, git: Callable[..., subprocess.CompletedProcess]) -> Filed | None:
    """Put a red run on the plan, keyed by its workflow and failing tests. None: the open task has it all.

    The workflow's task is open: the failing tests it does not name are named on it. Else the last closed task
    of the workflow that names one of them is opened again, unless it was dropped (a person's decision).
    Else a new critical task. The earlier tasks that name one are linked with the commits that landed them. With
    two filed in a week for the workflow (B34, whatever the test), a new or reopened one is blocked on a person."""
    plan_dir, done_lines = todo.parent, P.lines(done)
    says = lambda tid, line: '\n'.join([line, *P.lines(P.long_form(plan_dir, tid))])
    names = lambda text: [t for t in red.tests if f'`{t}`' in text]
    run = f'run {red.run["databaseId"]} on {red.run.get("headSha", "")[:8]}'

    for l in P.lines(todo):
        if (m := P.ITEM.match(l)) and not m[1] and m[2] != 'x' and red.mark in l:
            tid = m[3].rstrip('.')
            known = names(_since_reopened(says(tid, l)))
            new = [t for t in red.tests if t not in known]
            if not new:
                return None
            _note(tid, f'{run} also fails {ticked_names(new, NAMED)}: its FAIL lines are in the long form', todo)
            return Filed(tid, f'names {ticked_names(new, NAMED)} too', [todo, _section(plan_dir, tid, red)])

    same = [(tid, l) for l in done_lines
            if (m := DONE_ITEM.match(l)) and red.mark in l and names(says(tid := m[1].rstrip('.'), l))]
    closed = [(tid, l) for tid, l in same if P.DROPPED not in l]
    repo = red.run['url'].split('/actions/')[0]
    linked, links = [], []
    for tid, l in same:
        got = [] if P.DROPPED in l else fixes(tid, git)
        linked.append(f'{tid} ({"dropped" if P.DROPPED in l else ", ".join(got) or "no commit found"})')
        links.append(f'- {tid}: ' + ('dropped' if P.DROPPED in l else
                                     ', '.join(f'{repo}/commit/{c}' for c in got) or 'no commit found'))
    before = f'Earlier fixes that did not hold: {", ".join(linked)}' if linked else ''
    earlier = closed_repeats(done_lines, red.mark)
    paths = [todo]
    if closed:
        tid, l = max(closed, key=lambda c: _last_filed(c[1]))
        new = [t for t in red.tests if t not in names(says(tid, l))]
        P.restore(tid, todo=todo, done=done, plan_dir=plan_dir)
        _note(tid, f'reopened: {run} fails {ticked_names([t for t in red.tests if t not in new], NAMED)} again'
              + (f', and {ticked_names(new, NAMED)}' if new else '')
              + f'; its FAIL lines are in the long form. {before}. {filed_stamp()} {red.run["url"]}', todo)
        paths.append(done)
        how = 'reopened'
    else:
        tid = P.add(CI_KIND, red.text + (f' {before}.' if before else ''), todo=todo, pri='critical')
        how = 'filed'
    if len(earlier) >= REPEAT_LIMIT - 1:  # B34: the third in a week waits on a person, not ahead of all work
        P.block(tid, repeat_ask(red.mark.removesuffix(' is red'), earlier), todo=todo, after=[])
        how += f' (blocked on a person, after {", ".join(dict.fromkeys(earlier))})'
    else:
        how += ' (critical)'
    return Filed(tid, how, [*paths, _section(plan_dir, tid, red, links, bool(closed))])


BEFORE_REOPENED = '## Before it was opened again'


def _since_reopened(text: str) -> str:
    """A task's line and long form, less what they said before it was last opened again: a test fixed then and
    failing now is news."""
    line, _, own = text.partition('\n')
    return line.rsplit(' — reopened: run ', 1)[-1] + '\n' + own.split(BEFORE_REOPENED)[0]


def _note(tid: str, text: str, todo: Path) -> None:
    """`plan.note`, but before what a blocked task is blocked with: `unblock` cuts all that follows it."""
    ls = list(P.lines(todo))
    i = P._find(ls, tid)
    end = i + len(P._item_block(ls, i)) - 1
    body = P._unblocked(ls[end])
    ls[end] = f'{body} — {P.one_line(text)}{ls[end][len(body):]}'
    P._write(todo, ls)


def _section(plan_dir: Path, tid: str, red: Red, links: list[str] | None = None, again: bool = False) -> Path:
    """Write a red run into the task's long form, above what an earlier run put there."""
    own = P.long_form(plan_dir, tid)
    old = P.lines(own)
    title = old[0] if old and old[0].startswith('# ') else f'# {tid} — CI: {red.mark}'
    rest = old[1:] if old and old[0] == title else old
    own.parent.mkdir(parents=True, exist_ok=True)
    new = [*(['Earlier fixes that did not hold:', '', *links, ''] if links else []), *red.long]
    body = [title, '', *([f'## Run {red.run["databaseId"]}', ''] if rest else []), *new, '']
    if any(x.strip() for x in rest):
        body += [*([BEFORE_REOPENED, ''] if again else ['## Before', '']
                   if not any(x.startswith('## Run ') for x in rest) else []),
                 *('\n'.join(rest).strip('\n').split('\n')), '']
    own.write_text('\n'.join(body), encoding='utf-8')
    return own


# B34: an auto-filed critical task that closes while what it was for still fails is filed again, ahead of all
# queued work: a fix that does not fix would chain them with no person in the loop. Each one carries the day
# it was filed, and the third within REPEAT_DAYS for one workflow (or test) is filed blocked on a person.
REPEAT_LIMIT = 3     # the nth auto-filed task for one failure within REPEAT_DAYS is filed blocked
REPEAT_DAYS = 7
FILED = re.compile(r'\(filed (\d{4}-\d\d-\d\d)\)')
DONE_ITEM = re.compile(r'^- \[x\] \*\*([^\s*]+?)\*\*')


def filed_stamp(today: str = '') -> str:
    """What an auto-filed task's line carries, so its closed copy in DONE.md says when it was filed."""
    return f'(filed {today or dt.date.today().isoformat()})'


def closed_repeats(done_lines: list[str], key: str, today: str = '', days: int = REPEAT_DAYS) -> list[str]:
    """Ids of the closed (DONE.md) top-level tasks whose line holds `key` and a filed stamp no older than
    `days`, oldest first: the auto-filed tasks for this failure that closed while it went on failing. One
    opened again (`file_red`) has a stamp for each time, and its id is there for each."""
    now = dt.date.fromisoformat(today) if today else dt.date.today()
    out = []
    for l in done_lines:
        if not (m := DONE_ITEM.match(l)) or key not in l:
            continue
        for day in FILED.findall(l):
            try:
                if (now - dt.date.fromisoformat(day)).days <= days:
                    out.append(m[1])
            except ValueError:
                continue
    return out


def repeat_ask(what: str, earlier: list[str]) -> str:
    """The why a repeat is blocked with (see `closed_repeats`): a person decides, the earlier tasks named."""
    names = ', '.join(t if earlier.count(t) == 1 else f'{t} {earlier.count(t)} times' for t in dict.fromkeys(earlier))
    return (f'BLOCKED: {what} has had {len(earlier)} auto-filed tasks closed in {REPEAT_DAYS} days while it still '
            f'fails ({names}); look at why their fixes did not hold before another agent tries. '
            f'`plan unblock` to let a run try again, or drop it')
