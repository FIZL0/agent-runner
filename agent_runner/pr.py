"""F419: PR mode (`[git] pr`), for a mission-critical repository on GitHub. The runner never merges and never pushes
the main branch: a finished task's branch is pushed and one pull request opened for it, and the task is done when a
person merges that on GitHub, as a merge commit, a squash or a rebase.

`merge.merge` calls `submit` instead of merging. It takes main into the branch, runs the gate on the result and keeps it
in <notes>/prs.json. The parts of a split task go into one branch, pr/<KEY>, and one pull request once the last is
finished (`group`); a part started after another is taken in starts on that branch (`mates`). `tick`, from the run loop,
opens what is complete, asks `gh` what became of each pull request, brings the local main up to the remote's, and
ticks the tasks of a merged one (`landed`).

PR mode needs `[plan] repo` and a main branch GitHub protects from the token too (`problem`): `setup` and the run's
start refuse it without. The parts that talk to `gh` take a `gh` callable (`ci.gh_in`), so the tests give them answers.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote

from agent_runner import ci, pitch, plan as P, plansync
from agent_runner import state as S
from agent_runner.gitops import _net, drop_remote, git, shared_name
from agent_runner.whole_write import write_whole

POLL = 60            # s between two looks at the pull requests
BODY_MAX = 60_000    # GitHub takes 65536 characters
REVIEW = re.compile(r'^review: *(\S.*)$', re.M)
LOCK = threading.RLock()
AT = [0.0]
JOB: list[threading.Thread] = []
SAID: dict[str, str] = {}  # what was said last about each pull request or the main checkout: once, not every look


# --- may PR mode be on ----------------------------------------------------------------------------------------

def slug_of(url: str) -> str:
    """'owner/name' of a github.com remote url; '' for any other."""
    m = re.match(r'(?:[a-z+]+://)?(?:[^@/]+@)?(?:www\.)?github\.com(?::\d+/|[:/]+)([^/\s]+)/([^/\s]+?)(?:\.git)?/?$',
                 url.strip(), re.I)
    return f'{m[1]}/{m[2]}' if m else ''


def slug(root: Path, remote: str) -> str:
    """The push remote's 'owner/name' on GitHub, as it is written in the config, else with git's `insteadOf`; ''."""
    for a in (('config', '--get', f'remote.{remote}.url'), ('remote', 'get-url', remote)):
        if got := slug_of(git(*a, cwd=root).stdout):
            return got
    return ''


def _json(r):
    try:
        return None if r.returncode else json.loads(r.stdout)
    except ValueError:
        return None


def _why(r) -> str:
    return ((r.stderr or r.stdout).strip().splitlines() or [f'gh exited {r.returncode}'])[-1][:200]


def protection_problem(gh: ci.Gh, repo: str, branch: str) -> str:
    """Why GitHub does not keep this token from pushing `branch` itself; '' when it does: a ruleset or branch
    protection that wants a pull request, which the token cannot bypass. What cannot be read counts as not there."""
    b = quote(branch, safe='')
    r = gh('api', f'repos/{repo}/rules/branches/{b}')
    rules = _json(r)
    if not isinstance(rules, list):
        return f'GitHub did not say how {branch} is protected ({_why(r)})'
    bypass = False
    for i in dict.fromkeys(x.get('ruleset_id') for x in rules if isinstance(x, dict) and x.get('type') == 'pull_request'):
        one = _json(gh('api', f'repos/{repo}/rulesets/{i}'))
        if isinstance(one, dict) and one.get('current_user_can_bypass') == 'never':
            return ''
        bypass = True
    r = gh('api', f'repos/{repo}/branches/{b}/protection')
    p = _json(r)
    if not isinstance(p, dict):
        if bypass:
            return f"the ruleset that protects {branch} lets this machine's GitHub token bypass it: take it off the bypass list"
        if 'not protected' in _why(r).lower():
            return f'{branch} has no branch protection on GitHub: add a ruleset that requires a pull request, with no bypass'
        return (f"GitHub did not show this machine's token a protection of {branch} that requires a pull request "
                f'({_why(r)}): add a ruleset that does, with no bypass, as any token can read one')
    reviews = p.get('required_pull_request_reviews')
    if not isinstance(reviews, dict):
        return f"{branch}'s protection does not require a pull request"
    if not (p.get('enforce_admins') or {}).get('enabled'):  # only an admin's token reads this, so it is one
        return f"{branch}'s protection does not hold for admins, and this machine's token is one's: turn on \"Do not allow bypassing the above settings\""
    allowed = reviews.get('bypass_pull_request_allowances') or {}
    who = gh('api', 'user', '--jq', '.login').stdout.strip()
    users = [u.get('login') for u in allowed.get('users') or []]
    if allowed.get('teams') or allowed.get('apps') or users and (not who or who in users):
        return f"{branch}'s protection lets some bypass its pull requests, and this machine's token may be one: empty that list"
    return ''


def problem(c, root: Path, gh: ci.Gh | None = None) -> str:
    """Why PR mode cannot be on here; '' when it can. Asks GitHub."""
    remote = c.push_remote
    if not remote:
        return 'nothing is pushed here ([git] push or no_push), so no pull request can be opened'
    if not c.plan_repo or not c.plan_external:
        return 'it needs [plan] repo, with the plan outside this repository: plan commits would go to main otherwise'
    if git('remote', 'get-url', remote, cwd=root).returncode:
        return f'there is no remote {remote}'
    repo = slug(root, remote)
    if not repo:
        return f'{remote} is not on github.com, and PR mode is for GitHub only'
    if slug_of(c.plan_repo).lower() == repo.lower():
        return f'[plan] repo is this repository ({repo}): plan commits would go to it'
    branch = shared_name(root, remote)
    if not branch:
        return 'no main branch is known: set [git] master_branch'
    gh = gh or ci.gh_in(root)
    return protection_problem(gh, repo, branch)


def refusal(c, root: Path, gh: ci.Gh | None = None) -> str:
    """The line that refuses PR mode, or '' (off, or it may be on)."""
    why = problem(c, root, gh) if c.pr else ''
    return f'agent-runner: PR mode ([git] pr = true) is refused: {why}' if why else ''


def require(c, root: Path, gh: ci.Gh | None = None) -> None:
    """The run's start check."""
    if why := refusal(c, root, gh):
        raise SystemExit(why)


# --- what is kept ----------------------------------------------------------------------------------------------

def read(c=None) -> list[dict]:
    """The pull requests, open or still collecting, oldest first: {'key', 'ids', 'tips' {task: the commit of task/<ID>
    taken in}, 'branch', 'head' (its tested commit), 'base', 'gate', 'number' (0 until it is opened), 'url', 'pushed'
    (the head the pull request has), 'state'}."""
    try:
        d = json.loads((c or S.C).notes('prs.json').read_text(encoding='utf-8'))
    except FileNotFoundError:
        return []
    return d['prs']


@contextmanager
def edit():
    """The records, written back when the block ends."""
    with LOCK:
        d = read()
        was = json.dumps(d)
        yield d
        if json.dumps(d) != was:
            write_whole(S.C.notes('prs.json'), json.dumps({'prs': d}, indent=1).encode())


def of(tid: str, d: list[dict] | None = None) -> dict | None:
    return next((x for x in (read() if d is None else d) if tid in x['ids']), None)


def rev(ref: str) -> str:
    return S.git('rev-parse', '-q', '--verify', f'{ref}^{{commit}}').stdout.strip()


def _has(commit: str, part: str) -> bool:
    return S.git('merge-base', '--is-ancestor', part, commit).returncode == 0


def holds(tid: str) -> bool:
    """task/<tid> as it is now is in a pull request, or waits for its other parts: nothing is to be merged."""
    if not S.C.pr:
        return False
    rec = of(tid)
    return bool(rec) and rec['tips'].get(tid) == rev(f'refs/heads/task/{tid}')


# --- the parts of a split task ---------------------------------------------------------------------------------

def open_items(ls: list[str]) -> dict[str, int]:
    """{task: its line's index} of those not done, but for Stretch and Parked ones, which no run starts."""
    return {tid: i for section, box, tid, _, i in P.iter_tasks(ls) if box != 'x' and not section.startswith(P.SKIPPED)}


def _waits(ls: list[str], i: int) -> set[str]:
    """What the task at `i` waits for: its `after:` and, blocked, its `(after X)`."""
    out = set(P.waits_on(ls, i))
    if not P.until_of(ls, i):
        out |= {t for a in P.WAITS.findall('\n'.join(P._item_block(ls, i))) for t in P.TASK_ID.findall(a)}
    return out


def _parts(tid: str, ls: list[str], items: dict[str, int]) -> set[str]:
    """`tid` and the open tasks split off with it: of its family, or named in a `(split into …)` of one."""
    fam = lambda t: re.match(r'[A-Za-z]*\d*', t).group()  # noqa: E731 - sched.family; sched imports this module
    out, todo = {tid}, [tid]
    while todo:
        t = todo.pop()
        named = {x for p, i in items.items() for kids in [P.subtasks(p, ls[i], items)] if p == t or t in kids
                 for x in {p, *kids}}
        new = ({x for x in items if fam(x) == fam(t)} | named) - out
        out |= new
        todo += new
    return out


def group(tid: str, ls: list[str], taken: set[str] = frozenset()) -> set[str]:
    """The open tasks that share `tid`'s pull request. Not one already in an opened one (`taken`), nor one that can
    start only once this pull request is merged: it waits for another task that waits for one of these, or it is
    blocked on one of these. That gets one of its own."""
    items = open_items(ls)
    out = (_parts(tid, ls, items) if tid in items else {tid}) - (set(taken) - {tid})

    def beyond(t: str) -> set[str]:
        """Everything `t` waits for by way of a task outside the group."""
        seen: set[str] = set()
        todo = [x for x in _waits(ls, items[t]) if x in items and x not in out]
        while todo:
            x = todo.pop()
            if x not in seen:
                seen.add(x)
                todo += [y for y in _waits(ls, items[x]) if y in items]
        return seen

    def later(t: str) -> bool:
        blocked = ls[items[t]].lstrip().startswith('- [~]')
        return bool(beyond(t) & out) or blocked and bool(_waits(ls, items[t]) & (out - {t}))
    while gone := {t for t in out - {tid} if t in items and later(t)}:
        out -= gone
    return out


def _opened(d: list[dict]) -> set[str]:
    return {t for x in d if x['number'] for t in x['ids']}


def missing(rec: dict, ls: list[str], d: list[dict]) -> set[str]:
    """The parts a pull request still waits for."""
    if rec['number']:
        return set()
    return set().union(*(group(t, ls, _opened(d)) for t in rec['ids'])) - set(rec['ids'])


def mates(tid: str, ls: list[str], d: list[dict] | None = None) -> set[str]:
    """The parts beside `tid` that wait in its pull request's branch: `tid` starts on it, so it waits for none of them."""
    if not S.C.pr:
        return set()
    d = read() if d is None else d
    open_, out = _opened(d), set()
    for x in d:
        if not x['number'] and tid not in x['ids'] and any(tid in group(t, ls, open_) for t in x['ids']):
            out |= set(x['ids'])
    return out


def start_on(tid: str, branch: str) -> dict:
    """The branch of its finished parts a fresh start of `tid` checks out, as `stack` records it; {} for main."""
    if not S.C.pr or not (m := mates(tid, S.plan_text(branch))):
        return {}
    rec = next(x for x in read() if set(x['ids']) & m)
    return {'on': rec['head'], 'tids': sorted(m)}


# --- a finished task -------------------------------------------------------------------------------------------

def said_file(tid: str, c=None) -> Path:
    return (c or S.C).notes('prs', f'{tid}.json')


def done_problem(tid: str, message: str, c) -> str:
    """Why `done` does not finish `tid` yet: what its pull request says, or its spec review, is not there. Its review is
    kept as `message` ends with it."""
    if why := pitch.part_problem(tid, c):
        return f'{why}: its pull request says them'
    got = REVIEW.findall(message)
    if not got and c.run['review'] and not P.concept(tid):
        return 'the message needs its last line `review: …`: PR mode opens a pull request only for a reviewed task'
    write_whole(said_file(tid, c), json.dumps({'review': got[-1].strip() if got else ''}).encode())
    return ''


def reviewed(tid: str) -> str | None:
    """What `tid`'s spec review found, as its `done` said it; None for no review."""
    try:
        return str(json.loads(said_file(tid).read_text(encoding='utf-8'))['review'])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def submit(tid: str, branch: str):
    """In place of a merge: finished task/<tid>, gated with main taken in, goes into its pull request. False when it is
    in one (it is done when a person merges that), None when there is nothing to open one for, else why not."""
    from agent_runner import merge as M
    if holds(tid):
        return False
    ls = S.plan_text(branch)
    i = open_items(ls).get(tid)
    if i is not None and ls[i].lstrip().startswith('- [~]'):
        return park_blocked(tid)
    if not (plansync.ticks(S.C) / tid).exists():
        return 'its `done` has not passed, and PR mode opens a pull request only for a task whose gate and spec review did'
    if S.C.run['review'] and not P.concept(tid) and not reviewed(tid):
        return 'it has no spec review, and PR mode opens no pull request without one'
    if M.research_task(tid) and not M.research_code(tid, branch):
        M.drop_strays(tid, branch)
    with S.MERGE.turn(lambda: 3):
        if why := M.research_held(tid, branch):
            M.forget(tid)
            return why
        d = read()
        ls = S.plan_text(branch)
        own = of(tid, d)  # its branch moved since: its pull request gets what is new
        rec = own or next((x for x in d if not x['number'] and any(tid in group(t, ls, _opened(d)) for t in x['ids'])), None)
        parts = group(tid, ls, _opened(d))
        if not rec:
            key = min(parts, key=lambda t: (len(t), t))
            root = name = re.match(r'[A-Za-z]*\d*', key).group()
            n = 1
            while any(x['branch'] == f'pr/{root}' for x in d):  # an earlier one of the same task is still open
                n += 1
                root = f'{name}-{n}'
            rec = {'key': root if len(parts) > 1 else tid, 'ids': [], 'tips': {}, 'head': '', 'base': '', 'gate': '',
                   'number': 0, 'url': '', 'pushed': '', 'state': '', 'at': time.time(),
                   'branch': f'pr/{root}' if len(parts) > 1 else f'task/{tid}'}
        try:
            why, head, base, gate = build(tid, branch, rec, M)
        finally:
            M.forget(tid)
        if why:
            return why
        ref = f'refs/heads/{rec["branch"]}'
        tip = head if rec['branch'] == f'task/{tid}' else rev(f'refs/heads/task/{tid}')
        if S.git('update-ref', ref, head).returncode:
            return f'{rec["branch"]} could not be moved to its tested commit'
        with edit() as d:
            if not (now := next((x for x in d if x['branch'] == rec['branch']), None)):
                d.append(now := rec)
            now.update(head=head, base=base, gate=gate, ids=[*dict.fromkeys([*now['ids'], tid])],
                       tips={**now['tips'], tid: tip})
    if left := missing(now, S.plan_text(branch), read()):
        S.note(f'{tid}: gate passed, waits for {", ".join(sorted(left))} to share a pull request')
        S.log(f'{tid}: gate passed; its pull request opens once {", ".join(sorted(left))} finish: one for the whole task')
    open_due(branch)
    return False


def build(tid: str, branch: str, rec: dict, M) -> tuple[str | None, str, str, str]:
    """(why not, the tested commit, the main it is on, what the gate said): task/<tid> on what `rec` holds, with main
    taken in, gated. A branch only gets commits on top, so pushing it needs no force. Holds MERGE."""
    d = M.worktree('merge', branch)
    M.adopt_merge(d)
    g = lambda *a: S.git(*a, cwd=d)  # noqa: E731
    try:
        g('merge', '--abort')
        S.clean(d)
        fetch(branch)
        base, tip = rev(main_ref(branch)), rev(f'refs/heads/task/{tid}')
        others = bool(set(rec['ids']) - {tid})
        start = rec['head'] if others else tip
        g('checkout', '-q', '--detach', start)
        for ref, msg in ((tip, M.merge_message(tid, f'task/{tid}')), (base, f'Merge {branch} into {rec["branch"]}')):
            if not g('merge-base', '--is-ancestor', ref, 'HEAD').returncode:
                continue
            if (files := M.merge_into(d, ref, msg, tid)) is None:
                return f'git refused to merge {ref[:10]} into {rec["branch"]} (see the merge worktree, {d})', '', '', ''
            if files and not M.joined(files, tid, d) and (why := M.refix(tid, branch, ref, files, d, msg=msg)):
                return why, '', '', ''
        t = M.BatchTurn(tid, branch, d, True, set(), False, False)
        t.base, t.merged = base, g('rev-parse', 'HEAD').stdout.strip()
        docs = M.docs_merge(t)
        if why := M.batch_test(t):
            return str(why), '', '', ''
        old = [n for n, v in M.BROKEN.items() if v[0] == tid]
        gate = ('no test gate is set' if not S.C.run['test'] else 'docs only, so the gate was skipped' if docs else
                f'passed: `{S.C.run["test"]}`' + (f' (but for {", ".join(old)}, which {branch} fails too)' if old else ''))
        return None, t.merged, base, gate
    finally:
        M.UNDER.clear()
        g('merge', '--abort')
        g('checkout', '-q', '--detach')


def park_blocked(tid: str) -> str | None:
    """A task blocked by its session opens no pull request: its commits stay on wip/<ID>, for when it opens again."""
    from agent_runner.sched import forgive_park
    from agent_runner.slots import free_branch
    from agent_runner.gitops import push
    wip = free_branch(f'wip/{tid}')
    if S.git('branch', '-M', f'task/{tid}', wip).returncode:
        return f'it is blocked, and task/{tid} could not be renamed to {wip}'
    forgive_park(tid, wip)
    S.note(f'{tid}: blocked; its commits are kept on {wip}, no pull request')
    S.log(f'{tid}: blocked, so no pull request; its commits are kept on {wip}', S.EV_PART, tid)
    if out := push(S.ROOT, wip):
        S.log(f'{tid}: {out}')
    return None


# --- the pull request ------------------------------------------------------------------------------------------

def _words(v) -> str:
    return re.sub(r'@(?=\w)', '@​', str(v or '').strip())  # a name in it notifies nobody


def _fence(text: str) -> str:
    """`text` as a code block: no name in it notifies anybody, and no number in it links."""
    ticks = '`' * max(3, 1 + max((len(m) for m in re.findall('`+', text)), default=0))
    return f'{ticks}text\n{text}\n{ticks}'


def title(rec: dict, ls: list[str]) -> str:
    tid = rec['key'] if any(t == rec['key'] for _, _, t, _, _ in P.iter_tasks(ls)) else rec['ids'][0]
    i = next((i for _, _, t, _, i in P.iter_tasks(ls) if t == tid), None)
    name = P.title_of(ls[i]) if i is not None else tid
    head = f'{rec["key"]}: ' if S.C.run['include_task_id_in_commit'] else ''
    return (head + _words(name))[:240]


def _task_text(tid: str, ls: list[str]) -> str:
    i = next((i for _, _, t, _, i in P.iter_tasks(ls) if t == tid), None)
    text = '\n'.join(P._item_block(ls, i)) if i is not None else tid
    try:
        return f'{text}\n\n' + P.long_form(S.C.plan_dir, tid).read_text(encoding='utf-8').strip()
    except OSError:
        return text


def body(rec: dict, ls: list[str]) -> str:
    """What, why, how to try it and risk as each task's session wrote them, its text, the gate and its review."""
    room = BODY_MAX // max(1, len(rec['ids'])) // 2
    out = []
    for tid in rec['ids']:
        say = pitch.part(tid)
        if len(rec['ids']) > 1:
            out.append(f'# {tid}')
        for k, h in (('what', 'What'), ('why', 'Why'), ('try', 'How to try it'), ('risk', 'Risk')):
            out.append(f'## {h}\n\n{_words(say.get(k))[:room // 4] or "Not said."}')
        out.append(f'## Spec review\n\n{_words(reviewed(tid))[:room // 4] or "None."}')
        text = _task_text(tid, ls)
        out.append('<details><summary>The task</summary>\n\n' +
                   _fence(text if len(text) <= room else text[:room] + '\n…') + '\n\n</details>')
    out.append(f'## Gate\n\n{_words(rec["gate"])}, on {rec["head"][:10]} with {rec["base"][:10]} of the main branch in it.')
    return '\n\n'.join(out)


def open_due(branch: str, gh: ci.Gh | None = None) -> None:
    """Push the branch of every pull request that is complete and not as tested on GitHub, and open it."""
    gh = gh or ci.gh_in(S.ROOT)
    with LOCK:
        ls, d = S.plan_text(branch), read()
        for rec in d:
            if rec['pushed'] == rec['head'] or missing(rec, ls, d):
                continue
            if why := _open(rec, ls, branch, gh):
                _say(rec['key'], f'{rec["key"]}: its pull request is not {"updated" if rec["number"] else "open"} yet: '
                                 f'{why}; the run tries again')
                continue
            with edit() as now:
                next(x for x in now if x['branch'] == rec['branch']).update(rec)
            SAID.pop(rec['key'], None)


def _open(rec: dict, ls: list[str], branch: str, gh: ci.Gh) -> str:
    """Push `rec`'s branch and open its pull request, or bring the open one up to date: why not, or ''."""
    remote = S.C.push_remote
    repo = remote and slug(S.ROOT, remote)
    if not repo:
        return 'there is no GitHub remote to push to'
    if rec['branch'] == branch:
        return f'it is on {branch} itself'
    r = _net(S.ROOT)('push', '-q', remote, f'{rec["head"]}:refs/heads/{rec["branch"]}')  # never by force
    if r.returncode:
        return f'{rec["branch"]} did not push ({_why(r)})'
    if not rec['number']:  # one opened just before the run ended is this one
        r = gh('pr', 'list', '--repo', repo, '--head', rec['branch'], '--base', branch, '--state', 'open', '--json', 'number,url')
        got = _json(r)
        if got is None:
            return _why(r)
        if got:
            rec.update(number=int(got[0]['number']), url=got[0]['url'])
    f = S.C.notes('prs', f'{rec["key"]}.md')
    f.write_text(body(rec, ls), encoding='utf-8')
    if rec['number']:
        r = gh('pr', 'edit', str(rec['number']), '--repo', repo, '--body-file', str(f))
        if r.returncode:
            return _why(r)
        rec['pushed'] = rec['head']
        return ''
    r = gh('pr', 'create', '--repo', repo, '--base', branch, '--head', rec['branch'], '--title', title(rec, ls),
           '--body-file', str(f))
    if r.returncode or not (m := re.search(r'https://\S+/pull/(\d+)', r.stdout)):
        return _why(r)
    rec.update(number=int(m[1]), url=m[0], pushed=rec['head'], state='OPEN')
    ids = ', '.join(rec['ids'])
    S.note(f'{ids}: pull request #{m[1]} opened: {m[0]}')
    S.log(f'{ids}: pull request #{m[1]} opened, for a person to merge: {m[0]}')
    return ''


def _say(key: str, line: str) -> None:
    if SAID.get(key) != line:
        SAID[key] = line
        S.log(line)


# --- what became of it -----------------------------------------------------------------------------------------

def main_ref(branch: str) -> str:
    """The remote's main branch as last fetched, which the pull request is merged into; else the local one."""
    ref = f'refs/remotes/{S.C.push_remote}/{branch}'
    return ref if rev(ref) else f'refs/heads/{branch}'


def fetch(branch: str) -> None:
    if S.C.push_remote:
        _net(S.ROOT)('fetch', '-q', S.C.push_remote, branch)


def follow(branch: str) -> str:
    """Bring the local main branch up to the remote's, fast-forward only: why it could not, or ''."""
    fetch(branch)
    with S.LANDING:
        here, there = rev(f'refs/heads/{branch}'), rev(main_ref(branch))
        if here == there:
            return ''
        if not _has(there, here):
            return (f'{branch} here has commits GitHub does not have: move them to a branch, as PR mode never pushes '
                    f'{branch}')
        if S.git('branch', '--show-current').stdout.strip() == branch:
            r = S.git('merge', '-q', '--ff-only', there)
            said = ' '.join(r.stderr.split())[:300]
            return f'{branch} here could not be brought up to date: {said}' if r.returncode else ''
        if f'branch refs/heads/{branch}' in S.git('worktree', 'list', '--porcelain').stdout.splitlines():
            return f'{branch} is checked out in another worktree'
        S.git('update-ref', f'refs/heads/{branch}', there, here)
        return ''


def tick(branch: str) -> None:
    """From the run loop, every POLL s, in a thread of its own."""
    if not S.C.pr or time.time() - AT[0] < POLL or any(t.is_alive() for t in JOB):
        return
    AT[0] = time.time()
    JOB[:] = [threading.Thread(target=look, args=(branch,), name='pull requests', daemon=True)]
    JOB[0].start()


def look(branch: str, gh: ci.Gh | None = None) -> None:
    """One look: main brought up to date, dropped parts taken out, what is due opened, what is merged ticked."""
    gh = gh or ci.gh_in(S.ROOT)
    try:
        why = follow(branch)
        if why and SAID.get('main') != why:
            SAID['main'] = why
            S.alarm(f'{branch} here is behind GitHub', why)
        elif not why:
            SAID.pop('main', None)
        drop_closed(branch)
        open_due(branch, gh)
        for rec in read():
            if rec['number']:
                _look_at(rec, branch, gh)
    except Exception as e:  # noqa: BLE001 - the next look tries again
        _say('look', f'pull requests: {type(e).__name__}: {e}')


def _look_at(rec: dict, branch: str, gh: ci.Gh) -> None:
    repo = slug(S.ROOT, S.C.push_remote or 'origin')
    r = gh('pr', 'view', str(rec['number']), '--repo', repo, '--json', 'state,mergeCommit,headRefOid,baseRefName')
    got = _json(r)
    if not isinstance(got, dict):
        return _say(rec['key'], f'{rec["key"]}: GitHub did not say what became of pull request #{rec["number"]} ({_why(r)})')
    with edit() as d:
        for x in d:
            if x['branch'] == rec['branch']:
                x['state'] = got['state']
    if got['state'] == 'CLOSED':
        return _say(rec['key'], f'{rec["key"]}: pull request #{rec["number"]} was closed without a merge: {rec["url"]}')
    if got['state'] != 'MERGED':
        return None
    if got.get('baseRefName') != branch:
        return _say(rec['key'], f'{rec["key"]}: pull request #{rec["number"]} was merged into {got.get("baseRefName")}, not {branch}')
    commit = (got.get('mergeCommit') or {}).get('oid', '')
    if not commit or not rev(commit) or not _has(f'refs/heads/{branch}', commit):
        why = follow(branch)
        if not commit or not rev(commit) or not _has(f'refs/heads/{branch}', commit):
            return _say(rec['key'], f'{rec["key"]}: pull request #{rec["number"]} is merged, but not in {branch} here yet'
                                    f'{f": {why}" if why else ""}')
    landed(rec, commit, got.get('headRefOid', ''), branch)
    return None


def landed(rec: dict, commit: str, head: str, branch: str) -> None:
    """A person merged `rec`'s pull request, as `commit` on main: its tasks are ticked, and its branches go. A commit a
    branch got that was not in the pull request stays, on leftover/<ID>."""
    from agent_runner import land, merge as M
    from agent_runner.slots import free_branch
    S.git('fetch', '-q', S.C.push_remote, f'refs/pull/{rec["number"]}/head')
    with S.MERGE.turn(lambda: 0):
        for tid in rec['ids']:
            land.land_tick(tid, commit)
            tip = rev(f'refs/heads/task/{tid}')
            inside = _has(head, tip) if head and rev(head) else tip == rec['tips'].get(tid) and rec['pushed'] == rec['head']
            if tip and not inside:  # not wip/, which goes with the tick
                S.git('branch', '-M', f'task/{tid}', wip := free_branch(f'leftover/{tid}'))
                S.log(f'{tid}: task/{tid} has commits that were not in the merged pull request; kept on {wip}')
            elif tip:
                S.git('branch', '-D', f'task/{tid}')
            for r in (M.TESTED + tid, M.PARTIAL + tid):
                S.git('update-ref', '-d', r)
            msg = f'{tid}: pull request #{rec["number"]} merged by a person, ticked'
            S.note(msg)
            S.log(msg, S.EV_LANDED, tid)
        land.reopen_landed(branch, ', '.join(rec['ids']))
        if rec['branch'].startswith('pr/'):
            S.git('branch', '-D', rec['branch'])
        with edit() as d:
            d[:] = [x for x in d if x['branch'] != rec['branch']]
    for tid in rec['ids']:
        plansync.release(S.C, tid)
        pitch.part_file(tid).unlink(missing_ok=True)
        said_file(tid).unlink(missing_ok=True)
        if f'task/{tid}' != rec['branch']:
            drop_remote(S.ROOT, f'task/{tid}')
    S.C.notes('prs', f'{rec["key"]}.md').unlink(missing_ok=True)
    SAID.pop(rec['key'], None)
    at = _net(S.ROOT)('ls-remote', '--heads', S.C.push_remote, rec['branch']).stdout.split()
    if at and at[0] in (head, rec['pushed']):  # not one somebody pushed to since
        drop_remote(S.ROOT, rec['branch'])
    land.prune_wips(branch, force=True)


def drop_closed(branch: str) -> None:
    """A part dropped before its pull request opened is not in it: the branch is built again from the others. One whose
    pull request is open is said: closing that is a person's."""
    ls = S.plan_text(branch)
    live = {tid for _, box, tid, _, _ in P.iter_tasks(ls) if box != 'x'}
    for rec in read():
        if not (gone := [t for t in rec['ids'] if t not in live]):
            continue
        if rec['number']:
            if rec['state'] == 'CLOSED' and len(gone) == len(rec['ids']):
                _forget(rec)
            elif rec['state'] == 'OPEN':
                _say(rec['key'], f'{", ".join(gone)}: no longer open in the plan, but pull request #{rec["number"]} is: '
                                 f'close it if nobody wants it: {rec["url"]}')
            continue
        _forget(rec)
        for t in (left := [t for t in rec['ids'] if t in live]):
            if any(_has(f'refs/heads/task/{t}', rec['tips'][x]) for x in gone):
                S.alarm(f'{t} is built on dropped work', f'{", ".join(gone)} was dropped, but {t} was started on top of it, '
                        f'so its pull request has those commits too.')
        for t in left:
            if (why := submit(t, branch)) not in (False, None):
                S.log(f'{t}: {why}')


def _forget(rec: dict) -> None:
    with edit() as d:
        d[:] = [x for x in d if x['branch'] != rec['branch']]
    if rec['branch'].startswith('pr/'):
        S.git('branch', '-D', rec['branch'])
