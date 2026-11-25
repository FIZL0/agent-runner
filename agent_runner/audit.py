"""Auto audit (F417, `[run] auto_audit`): once `every` tasks have landed since the last audit, the idle run queues one
audit task: what changed since, read for what is stale, dead or wasted, its findings written to a file.

A task is an audit by the tag `(audit)` that opens its text, so one is added by hand with `plan add` too. The run's
settings (ROOT, C) are read from `state` when used, not imported, so `init` reaches this module too."""
from __future__ import annotations

import datetime as dt
import os
import posixpath
import re
import time
from contextlib import ExitStack
from pathlib import Path

from agent_runner import plan as P, plansync, state as S
from agent_runner.state import EV_AUTO_AUDIT, EV_LANDED, EV_PART, MERGE

TAG = '(audit)'
TAG_AT = re.compile(r'^\s*- \[.\] \*\*[^*]+\*\*\s*(?:\(follow-up, \w+\)\s*)?(?:\(alone\)\s*)?\(audit\)')
EVERY = 50       # tasks landed: `auto_audit = true`
LOOK_EVERY = 60  # seconds between two looks of an idle run
LOOKED = [0.0]
NAMED = 200      # landed tasks a brief names at most, the newest
AUDITED = re.compile(r'^Audited: \S*\.\.([0-9a-f]{7,40})\s*$', re.M)
TEXT = (f'{TAG} Audit what changed since the last audit: stale and duplicate tasks, old asks, dead docs, lessons, unused '
        'code and tests, waste in run cost. Check: the findings file is written.')

PROMPT = """\
{tid} is an audit: find what is stale, dead or wasted, and change nothing. Write what you find to `{file}`, the one \
file you change, and file or edit no task: what is done about a finding is decided later, from that file. Only write \
there what you checked; nothing found is a finding too, so always write the file.

Scope: only what changed since the last audit, {scope}. `git diff --stat {diff}` and `git log --oneline {log}` say \
what. Read a file that did not change only to check whether something that did left it stale. {left}{landed}
Look at:
- Tasks (`{runner} plan`, `{runner} plan <ID>`): stale, duplicate, about something a done task removed, or whose runs keep \
ending with no commits ({notes}/no-commits.json counts them, now, and `no commits` in {notes}/run.log names the closed and blocked ones too).
- Asks under Needs you not answered for over 7 days ((asked …) on the task's line; with none, the date the plan's git \
history or {notes}/events.jsonl gives).
- Docs, the glossary and lessons that name something gone or say what is no longer so; lessons that repeat or \
contradict each other.
- Code and tests nothing uses any more: search for every name before you say so.
- Waste in run cost (`{runner} cost --days {days}`, `{runner} cost --files --days {days}`): the same file or command read \
over and over, sessions past the context warning, work done twice.
An open task, question or ask counts whatever its age.

The file starts with the line `Audited: {range}`. Then a heading for each area with a list: the finding, the evidence \
(path:line, id or command), and what you recommend. Last, `## Not reached`: what you had no room for, or `none`.
{cap}Write the file as you go, the surest findings first, then run `done`."""

CAP = ('It stops at {cap:,} tokens ([run] audit_tokens; input, cache writes and output, subagents too): before that, finish '
       'with what you have.\n')

# what a session past its cap is told, in place of brief.BUDGET_STOP: its findings land
STOP = ('Stop now: {tid} has used its cap ({why}). Look at nothing more. If your `{runner} done` is already running, let it '
        'finish and do nothing else. Otherwise put what you have in the findings file, name what you did not reach under '
        '`## Not reached`, then run `{runner} done {tid} "<message>"` and `{runner} finish`.')


def every_of(v) -> int:
    """`[run] auto_audit` as the tasks landed that queue an audit; 0 = off. `true` is EVERY."""
    if v is True:
        return EVERY
    n = v.get('every') if isinstance(v, dict) else 0
    return n if isinstance(n, int) and not isinstance(n, bool) and n > 0 else 0


def tagged(line: str) -> bool:
    """Is the task line `line` an audit."""
    return bool(TAG_AT.match(line or ''))


def is_audit(tid: str, ls: list[str] | None = None) -> bool:
    """Is `tid` an audit, by the plan's lines `ls` (else the plan file's)."""
    try:
        ls = P.lines(S.C.todo) if ls is None else ls
    except (OSError, AttributeError):
        return False
    return any(t == tid and tagged(ls[i]) for _, _, t, _, i in P.iter_tasks(ls))


def open_audit(ls: list[str]) -> bool:
    return any(box != 'x' and tagged(ls[i]) for _, box, _, _, i in P.iter_tasks(ls))


def folder() -> str:
    """Where audits write their findings: `audits/` in the plan directory, `docs/audits` when that is outside the
    repository or its root."""
    plan = '' if S.C.plan_external else os.path.relpath(S.C.plan_dir, S.C.root).replace(os.sep, '/')
    return 'docs/audits' if plan in ('', '.') else f'{plan}/audits'


def findings_file(tid: str) -> str:
    return f'{folder()}/{tid}.md'


def last(branch: str) -> str:
    """The commit the last audit that landed read up to: what its findings file says, else the commit before the one
    that added the file. '' when there was none."""
    r = S.git('log', '-1', '--diff-filter=A', '--name-only', '--format=%H', branch, '--', f':(glob){folder()}/[A-Z]*[0-9]*.md')  # an id, not a README
    got = r.stdout.split()
    if r.returncode or len(got) < 2:
        return ''
    m = AUDITED.search(S.git('show', f'{branch}:{got[1]}').stdout)
    if m and not S.git('merge-base', '--is-ancestor', m[1], branch).returncode:
        return m[1]
    return S.git('rev-parse', '--verify', '-q', f'{got[0]}^').stdout.strip()


def audits(branch: str) -> set[str]:
    """Ids of the audits that landed."""
    files = S.git('ls-tree', '-r', '--name-only', branch, '--', folder() + '/').stdout.splitlines()
    return {m[1] for f in files if (m := re.fullmatch(r'([A-Z]+\d+[a-z]*)\.md', posixpath.basename(f)))}


def stamp(commit: str) -> str:
    """`commit`'s time as events are stamped: local, with no zone. '' without one."""
    when = S.git('log', '-1', '--format=%ct', commit).stdout.strip() if commit else ''
    return dt.datetime.fromtimestamp(int(when)).isoformat(timespec='seconds') if when else ''


def landed(branch: str, count: bool = False) -> list[str]:
    """The tasks landed since the last audit, oldest first; a part landing too, an audit never. `count`: since the last
    one the run queued as well, so one that is dropped, or wrote no file, is not queued again for the same work."""
    from agent_runner.status import read_events
    evs, not_these = read_events(), audits(branch)
    queued = [e for e in evs if e['kind'] == EV_AUTO_AUDIT]
    not_these |= {e.get('id') for e in queued}
    since = max([stamp(last(branch)), *((e['time'][:19] for e in queued) if count else ())])
    out = dict.fromkeys(e['id'] for e in evs if e['kind'] in (EV_LANDED, EV_PART) and e.get('id')
                        and e['time'][:19] > since and e['id'] not in not_these)
    return list(out)


def idle(run) -> bool:
    """`run` (a loop.Run) has nothing running, waiting or merging, and nothing it may start."""
    from agent_runner import exit_hook, loop, shared_tools
    from agent_runner.sched import pick
    if not run.idle_said or run.once or loop.PAUSED[0] or S.stopping():
        return False
    if run.procs or run.waiting or any(t.is_alive() for t in run.merging) or exit_hook.busy():
        return False
    return not shared_tools.pending(run.tried) and not pick(run.running, run.tried, run.branch)


def tick(run) -> str:
    """The end of a tick: queue an audit when one is due and `run` is idle. Its id, or ''."""
    if not every_of(S.C.run.get('auto_audit')) or not run.idle_said or time.time() - LOOKED[0] < LOOK_EVERY:
        return ''
    LOOKED[0] = time.time()
    return queue(run.branch) if idle(run) else ''


def kind() -> str:
    """The id letter of an audit: a research kind, whose branch may change its findings only."""
    k = S.C.raw['plan'].get('kinds') or P.KINDS
    return next((p for p in k if P.research(f'{p}1', k)), None) or \
        next((p for p in k if p not in ('K', P.RELEASE)), 'R')


def queue(branch: str) -> str:
    """Queue an audit when `every` tasks have landed since the last one and none is open. Committed in the main
    checkout as `file_split` commits its tasks, only when MERGE is free. The id, or ''."""
    every = every_of(S.C.run.get('auto_audit'))
    if not every or not MERGE.acquire(blocking=False):
        return ''
    hold = ExitStack()
    try:
        rel = S.plan_rel('TODO.md')
        if S.C.plan_external:
            hold.enter_context(plansync.locked(S.C))
            plansync.pull(S.C, force=True)
        elif S.git('branch', '--show-current').stdout.strip() != branch or \
                S.git('status', '--porcelain', '--', S.plan_rel('')).stdout.strip():
            return ''
        if open_audit(P.lines(S.ROOT / rel)) or (n := len(landed(branch, count=True))) < every:
            return ''
        why = f'{n} landed'
        tid = P.add(kind(), f'{TEXT} | files: {folder()}/**', todo=S.ROOT / rel, pri='normal')
        if not S.commit_plan(f'Plan: {tid}, auto audit ({why})', rel):
            S.git('checkout', '-q', '--', rel)
            return ''
        S.log(f'queued {tid} (auto_audit: {why})', EV_AUTO_AUDIT, tid, why=why)
        return tid
    finally:
        hold.close()
        MERGE.release()


def caps(tid: str, own: tuple) -> tuple:
    """Session caps `own` (tokens, dollars) as `tid` has them: an audit's tokens stop at `[run] audit_tokens` too."""
    cap = S.C.run.get('audit_tokens') or 0
    if not cap or not is_audit(tid):
        return own
    return min(filter(None, (cap, own[0]))), own[1]


def prompt(tid: str, branch: str, cwd: Path) -> str:
    """The audit paragraphs of `tid`'s brief, in the worktree `cwd`: its scope, what it looks at, its file and its cap."""
    until = S.git('merge-base', 'HEAD', branch, cwd=cwd).stdout.strip()[:12] or branch
    since = last(branch)[:12]
    ids = landed(branch)
    days = max(1, (dt.datetime.now() - dt.datetime.fromisoformat(stamp(since))).days + 1) if since else 30
    if since:
        span = diff = log = f'{since}..{until}'
    else:  # no audit yet: all there is, newest first, up to the cap
        empty = S.git('hash-object', '-t', 'tree', '--stdin', input='').stdout.strip()
        span, diff, log = f'start..{until}', f'{empty} {until}', until
    scope = f'which read up to {since} ({stamp(since)[:10]})' if since else \
        'and there was none: start at what changed last and go back until the cap'
    cap = S.C.run.get('audit_tokens') or 0
    left = (f'What the newest file in {folder()}/ lists under `## Not reached` is in scope too. ') if since else ''
    said = f'Tasks landed since ({len(ids)}{", the newest" if len(ids) > NAMED else ""}): {", ".join(ids[-NAMED:])}.\n' if ids else ''
    return PROMPT.format(tid=tid, file=findings_file(tid), scope=scope, range=span, diff=diff, log=log, left=left, landed=said, runner=S.C.command,
                         notes=S.C.notes(), days=days, cap=CAP.format(cap=int(cap)) if cap else '')
