"""Landing a tested merge: the main checkout (`land`, wip branches), pushing, releases, ticks and reopened
blocks, flaky tests."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess as sp
import sys
import time

from agent_runner import ci, freeze, gitops, plan as P, plansync
from agent_runner.config import RUNNER
from agent_runner.gitops import drop_if_merged, push
from agent_runner.state import (alarm, C, commit_plan, edited, git, init, log, newest, note, plan_rel, plan_text,
    ROOT, SLOTS_DIR)
from agent_runner.state import EV_LANDED, EV_PART, EV_RELEASED
from agent_runner.watch import HOGS
from agent_runner.join import (EDITED, ELSEWHERE, joined, LAND_WAIT, LAND_WAIT_WIP, LANDED, renumber_doubles,
    task_env, WAITING)


def here_hint() -> str:
    return (f'Next time, `{C.command} take --here ID` (or `take --here "TEXT" --kind K`) moves edits like these '
            f'into a worktree of their own')


def wip_main() -> list[str]:
    """The wip/main-checkout-* branches `move_edits_aside` made, so they are not forgotten."""
    return git('for-each-ref', '--format=%(refname:short)', 'refs/heads/wip/main-checkout-*').stdout.split()


def wip_main_info() -> list[tuple[str, float, int]]:
    """F23: (name, when it was made as a unix time, files it holds) for each wip/main-checkout-* branch, oldest
    first: a person's uncommitted edits, which the run never deletes, so Needs you lists them."""
    out = []
    for l in git('for-each-ref', '--sort=committerdate', '--format=%(refname:short)%09%(committerdate:unix)',
                 'refs/heads/wip/main-checkout-*').stdout.splitlines():
        name, _, when = l.partition('\t')
        n = len(git('diff', '--name-only', f'{name}^', name, '--').stdout.split())
        out.append((name, float(when or 0), n))
    return out


def wip_lines(wips, now: dt.datetime | None = None) -> list[str]:
    """F23: the Needs you lines for `wip_main_info`'s branches, each with its age and file count."""
    now = now or dt.datetime.now()
    out = []
    for name, when, n in wips:
        old = P.age(dt.datetime.fromtimestamp(when).strftime('%Y-%m-%d %H:%M'), now) if when else ''
        out.append('  ' + (f'{old:>3}  ' if old else '') +
                   f'Main-checkout edits moved aside ({n} file{"s" * (n != 1)}) - '
                   f'{C.command} wip show|restore|drop {name.removeprefix("wip/")} [{name}]')
    return out


WIP = re.compile(r'wip/([A-Za-z]+\d+[a-z0-9]*?)(?:-\d+)?')  # a task's parked or saved attempt: wip/<ID>, wip/<ID>-N


def done_ids(branch: str) -> set[str]:
    """F23: ids of the tasks DONE.md holds (ticked, or dropped: both are archived there), as the merge target
    has it; a plan outside the repo has one copy, read."""
    r = git('show', f'{newest(branch)}:{plan_rel("DONE.md")}') if not C.plan_external else None
    ls = r.stdout.splitlines() if r is not None and r.returncode == 0 else P.lines(C.done)
    return {tid.rstrip('.') for _, box, tid, _, _ in P.iter_tasks(ls) if box == 'x'}


def drop_wips(tid: str) -> list[str]:
    """F23: delete wip/<tid> and wip/<tid>-N, here and on `[git] push`: the task is ticked or dropped, so its
    parked attempts are read by nobody any more. Returns what it did. Never a wip/main-checkout-* branch."""
    did = []
    names = set(git('for-each-ref', '--format=%(refname:short)', f'refs/heads/wip/{tid}',
                    f'refs/heads/wip/{tid}-*').stdout.split())
    if r := C.push_remote:
        names |= {f'wip/{x}' for x in git('for-each-ref', '--format=%(refname:lstrip=4)',
                                          f'refs/remotes/{r}/wip/{tid}', f'refs/remotes/{r}/wip/{tid}-*').stdout.split()
                  if x.startswith(tid)}
    for name in sorted(names):
        if name.startswith('wip/main-checkout') or not ((m := WIP.fullmatch(name)) and m[1] == tid):
            continue
        if not git('rev-parse', '--verify', '-q', f'refs/heads/{name}').returncode and \
                not git('branch', '-D', name).returncode:
            did.append(f'deleted {name}')
        if out := gitops.drop_remote(ROOT, name):
            did.append(out)
    return did


PRUNED = [0.0]  # when `prune_wips` last looked
PRUNE_EVERY = 600


def prune_wips(branch: str, force: bool = False) -> list[str]:
    """F23: every wip/<ID> (and wip/<ID>-N) whose task is done or dropped (in DONE.md and no longer open or blocked
    in TODO.md) deleted, here and on the remote: a task ticked or dropped by hand, or while no run was up,
    leaves its parked attempts behind otherwise. At most every PRUNE_EVERY seconds unless `force`."""
    if not force and time.time() - PRUNED[0] < PRUNE_EVERY:
        return []
    PRUNED[0] = time.time()
    refs = git('for-each-ref', '--format=%(refname:short)', 'refs/heads/wip/').stdout.split()
    if r := C.push_remote:
        refs += [f'wip/{x}' for x in git('for-each-ref', '--format=%(refname:lstrip=4)',
                                         f'refs/remotes/{r}/wip/').stdout.split()]
    ids = {m[1] for x in refs if not x.startswith('wip/main-checkout') and (m := WIP.fullmatch(x))}
    if not ids:
        return []
    live = {tid for _, box, tid, _, _ in P.iter_tasks(plan_text(branch)) if box != 'x'}
    did = []
    for tid in sorted((ids & done_ids(branch)) - live):
        if got := drop_wips(tid):
            did.append(f'{tid}: done, so its parked attempts went: {", ".join(got)}')
            log(did[-1])
    return did


def wip_name(arg: str) -> str:
    """`main-checkout-…` or `wip/main-checkout-…`: the branch `agent-runner wip` means."""
    return arg if arg.startswith('wip/') else f'wip/{arg}'


def cmd_wip(argv: list[str], prog: str = f'{RUNNER} wip') -> int:
    """F23 `agent-runner wip [show|restore|drop NAME]`: the wip/main-checkout-* branches of a person's edits that
    a merge moved aside. The run never deletes them; this is how a person looks, takes them back or lets go."""
    ap = argparse.ArgumentParser(prog=prog, description='The main checkout\'s uncommitted edits a merge moved to a '
                                 'wip/main-checkout-* branch: list them, show one, restore it into a take worktree, '
                                 'or drop it (here and on the remote).')
    ap.add_argument('what', nargs='?', choices=('list', 'show', 'restore', 'drop'), default='list')
    ap.add_argument('name', nargs='?', help='the branch, with or without wip/')
    ap.add_argument('id', nargs='?', help='restore: the task whose take worktree gets the edits (`take ID` first); '
                                          'default the one take worktree there is')
    a = ap.parse_args(argv)
    init()
    if a.what == 'list':
        wips = wip_main_info()
        print('\n'.join(wip_lines(wips)) if wips else 'no wip/main-checkout-* branches')
        return 0
    if not a.name:
        ap.error(f'{a.what} needs NAME')
    name = wip_name(a.name)
    if git('rev-parse', '--verify', '-q', f'refs/heads/{name}').returncode:
        print(f'{name}: no such branch here', file=sys.stderr)
        return 1
    if a.what == 'show':
        print(git('show', '--stat', '--format=%h %ci%n%s%n', name).stdout.rstrip())
        return 0
    if a.what == 'drop':
        if git('branch', '-D', name).returncode:
            print(f'{name}: could not be deleted', file=sys.stderr)
            return 1
        print(f'deleted {name}')
        if out := gitops.drop_remote(ROOT, name):
            print(out)
        return 0
    takes = sorted(p for p in SLOTS_DIR.glob('take-*') if p.is_dir())
    if a.id:
        d = SLOTS_DIR / f'take-{a.id}'
        if not d.is_dir():
            print(f'{a.id}: not taken (no {d}); `{C.command} take {a.id}` first', file=sys.stderr)
            return 1
    elif len(takes) == 1:
        d = takes[0]
    else:
        print(f'restore {name} into which take worktree? `{C.command} take ID` first, then '
              f'`{C.command} wip restore {a.name} ID`' + (f' (taken: {", ".join(p.name[5:] for p in takes)})'
                                                         if takes else ''), file=sys.stderr)
        return 1
    r = git('cherry-pick', '--no-commit', name, cwd=d)
    if r.returncode:
        print(f'{name} did not apply cleanly in {d}: {r.stderr.strip()}\nresolve the conflicts there (the edits '
              f'are uncommitted), or `git cherry-pick --abort` in it; {name} is kept', file=sys.stderr)
        return 1
    git('reset', '-q', cwd=d)  # uncommitted and unstaged, as they were in the main checkout
    print(f'{name}: its edits are in {d}, uncommitted; `{C.command} wip drop {a.name}` once you have them')
    return 0


def move_edits_aside(tid: str) -> str | None:
    """[git] land_edited = "wip": the main checkout's uncommitted edits (new files included) as one commit on
    wip/main-checkout-<time>, on top of HEAD, pushed when the shared branch is; then a stash of them (a second
    copy) clears the checkout so the tested merge can land. The branch name, or None when there was nothing."""
    files = sorted(edited())
    if not files:
        return None
    name = f'wip/main-checkout-{time.strftime("%Y-%m-%d-%H%M%S")}'
    idx = os.path.join(git('rev-parse', '--git-dir').stdout.strip() or '.git', 'agent-runner-wip-index')
    env = {**os.environ, 'GIT_INDEX_FILE': idx}
    try:
        sp.run(['git', 'read-tree', 'HEAD'], cwd=ROOT, env=env, check=True, capture_output=True)
        sp.run(['git', 'add', '-A', '--', *files], cwd=ROOT, env=env, check=True, capture_output=True)
        tree = sp.run(['git', 'write-tree'], cwd=ROOT, env=env, check=True, capture_output=True, text=True).stdout.strip()
    finally:
        try:
            os.remove(idx)
        except OSError:
            pass
    msg = f'Uncommitted edits from the main checkout, moved aside so {tid} could land ({len(files)} files)'
    commit = git('commit-tree', tree, '-p', 'HEAD', '-m', msg).stdout.strip()
    if not commit or git('branch', name, commit).returncode:
        return None
    if git('stash', 'push', '-u', '-q', '-m', f'{name} (agent-runner)', '--', *files).returncode:
        return None
    remote = C.push_remote
    if C.push_merge and remote and not C.approve and not git('remote', 'get-url', remote).returncode:
        git('push', '-q', remote, name)
    more = f' and {len(files) - 6} more' if len(files) > 6 else ''
    log(f'{tid}: moved uncommitted edits in the main checkout ({", ".join(files[:6])}{more}) to {name} '
        f'(and a stash) so the tested merge could land: git checkout {name}, or git stash pop. {here_hint()}')
    return name


def land(tid: str, branch: str, merged: str) -> str | None:
    """Move the shared branch in the main checkout to the tested merge: seconds, not a test run.

    None when it landed, 'conflict' when the branch's new commits clash with it (the caller builds it again
    on top), else why it could not. Uncommitted edits there are never moved aside: git refuses, before it
    starts, a merge that would change a file somebody is editing, so this waits LAND_WAIT for them to commit,
    then gives MERGE back with a why starting EDITED: `finish` keeps task/<ID> and tries again once they are.
    A main checkout with another branch out is never switched: the why starts ELSEWHERE, kept the same way.
    """
    t0 = time.time()
    said = False

    while git('diff', '--name-only', '--diff-filter=U').stdout.strip() or \
            git('rev-parse', '--verify', '-q', 'MERGE_HEAD').returncode == 0:
        if time.time() - t0 > 60 * 60:
            return 'the main checkout has a merge or unmerged paths of its own, for 60 min'
        if not said:
            said = True
            alarm(f'{tid} cannot land: {ROOT.name} is mid-merge',
                  f'the main checkout ({ROOT}) is in the middle of a merge of its own; finish or abort it, and '
                  f'{tid} lands on {branch}.')
        freeze.pause(10)
    cur = git('branch', '--show-current').stdout.strip()
    if cur != branch:
        return f'{ELSEWHERE} ({cur or "a detached HEAD"}, not {branch})'
    msg = ['-m', f'{tid}: the tested merge, onto commits {branch} got during the tests']
    ref = renumber_doubles(merged, 'HEAD', tid, ROOT)
    while git('merge', '-q', *msg, ref, **task_env(tid)).returncode and \
            git('rev-parse', '--verify', '-q', 'MERGE_HEAD').returncode:
        if C.land_edited == 'wip' and time.time() - t0 > LAND_WAIT_WIP and move_edits_aside(tid):
            continue
        if time.time() - t0 > LAND_WAIT:
            return f'{EDITED} to files the merge changes'
        if not said:
            mine = edited()
            files = sorted(mine & set(git('diff', '--name-only', 'HEAD', ref).stdout.split())) or sorted(mine)
            more = f' and {len(files) - 6} more' if len(files) > 6 else ''
            said = True
            alarm(f'{tid} cannot land: uncommitted edits in {ROOT.name}',
                  f'{tid} is tested and waits to land on {branch}, but the main checkout ({ROOT}) has uncommitted '
                  f'edits to {", ".join(files[:6])}{more}, which the merge changes. Commit them, or move them to a '
                  f'branch, and it lands within a minute. {here_hint()}')
        freeze.pause(10)
    if git('rev-parse', '--verify', '-q', 'MERGE_HEAD').returncode == 0:
        files = git('diff', '--name-only', '--diff-filter=U').stdout.split()
        if not joined(files, tid, ROOT):
            git('merge', '--abort')
            return 'conflict'
    if git('merge-base', '--is-ancestor', merged, 'HEAD').returncode:
        return f'the merge did not land in {branch}; merge it again'
    return None


def record_landed(tid: str, branch: str, base: str, merged: str, M) -> None:
    """Record that task/<tid> landed with the merge `merged` (`M`: merge.py): its branch and refs go, it is ticked."""
    M.forget(tid)
    git('branch', '-d', f'task/{tid}')
    git('update-ref', '-d', M.TESTED + tid)
    git('update-ref', '-d', M.PARTIAL + tid)
    for h in git('for-each-ref', '--format=%(refname)', f'{M.HELD}{tid}/', f'{M.FIXED}{tid}/').stdout.split():
        git('update-ref', '-d', h)
    land_tick(tid, merged)
    line = next((l for l in plan_text(branch) if f'**{tid}**' in l), '')
    state = 'blocked' if line.startswith('- [~]') else 'part' if line else 'ticked'
    msg = f'{tid}: merged, {state}' + (f'; SUSPECT, recheck: {sus}' if (sus := M.suspect(base, merged)) else '')
    note(msg)
    log(msg, EV_PART if state == 'blocked' else EV_LANDED, tid)
    reopen_landed(branch, tid)  # before the push, so the reopen goes out with the merge
    keep_landed()


def keep_landed() -> None:
    """B827: what landed and is not recorded yet, for the next run (`load_landed`) when this one is cut off."""
    f = C.notes('landed.json')
    if LANDED:
        f.write_text(json.dumps(LANDED), encoding='utf-8')
    else:
        f.unlink(missing_ok=True)


def load_landed() -> None:
    try:
        LANDED.update({t: tuple(v) for t, v in json.loads(C.notes('landed.json').read_text(encoding='utf-8')).items()})
    except (OSError, ValueError, AttributeError, TypeError):
        pass



def published(tid: str, branch: str) -> None:
    """After a merge that passed the test gate: push the shared branch, then drop the task's remote branch.

    Pushed here, and only after the gate, which is what makes publishing it unattended defensible. A failed
    push is logged, not fatal: the merge landed locally and the next one pushes both. With `[git] push_merge
    = false` the merge stays local and the `git push` to run is logged instead; `drop_if_merged` then keeps
    the task branch on the remote until the shared branch there has it. With no gate (`[run] test` empty)
    the merge stays local the same way unless the config sets `push_merge` itself (`pushes_main`, B36).

    A batch is pushed once, by the last of its tasks to land: while the others are still waiting for the lock
    to record theirs, this one's push is left to them (each push is a CI run on the shared branch).
    """
    UNPUSHED.append(tid)
    if not (C.push_merge and LANDED and set(LANDED) <= WAITING):
        push_landed(tid, branch)


def no_gate_line() -> str:
    """The warning for a run with no test gate (`[run] test` empty), or '' when it has one: logged at the
    run's start, printed by --dry-run and status, so untested merges never reach main without a word."""
    if C.run['test']:
        return ''
    if C.pr:  # F419
        return 'WARNING no test gate ([run] test is empty): pull requests open untested'
    push = ('and wait for your approval: [run] approve is set' if C.approve and C.push_merge else
            'and are pushed: [git] push_merge is set' if pushes_main() else
            'and stay local: set [git] push_merge = true to push them anyway' if C.push_merge else
            'and stay local')
    return f'WARNING no test gate ([run] test is empty): merges go to main untested {push}'


def pushes_main() -> bool:
    """Whether a merge pushes the shared branch: `[git] push_merge`, and with no test gate only when the
    config sets push_merge itself, so the default never publishes untested work unattended."""
    return C.push_merge and bool(C.run['test'] or 'push_merge' in C.given.get('git', ()))


def push_landed(tid: str, branch: str) -> None:
    """`published`'s push, for `tid` and the tasks of its batch whose push was left to it."""
    if C.approve and C.push_merge:  # F98: the landed changes wait in pitches (`pitch.landed`)
        UNPUSHED.clear()
        return
    if C.push_merge and not pushes_main():
        log(f'{tid}: merged, not pushed: no test gate ([run] test is empty) and [git] push_merge is not set; '
            f'to publish it untested: git push {C.push_remote} {branch}')
    elif C.push_merge:
        if out := push(ROOT, branch, shared=True):
            log(f'{tid}: {out}' + (f' (with {", ".join(UNPUSHED[:-1])})' if len(UNPUSHED) > 1 else ''))
    elif C.push_remote:
        log(f'{tid}: merged, not pushed ([git] push_merge is off): git push {C.push_remote} {branch}')
    # this batch's branches, and any an earlier failed push left behind (nothing else retries those)
    r = C.push_remote
    left = git('for-each-ref', f'--merged=refs/remotes/{r}/{branch}', '--format=%(refname:lstrip=4)',
               f'refs/remotes/{r}/task/').stdout.split() if C.push_merge and r else []
    for t in dict.fromkeys(UNPUSHED + left):
        if out := drop_if_merged(ROOT, f'task/{t}'):
            log(f'{t}: {out}')
    UNPUSHED.clear()


UNPUSHED: list[str] = []  # tasks landed whose push `published` left to the last of their batch


REOPENED: set[str] = set()  # tasks `reopen_landed` put back to [ ]: `cmd_run` lets them be tried again
def idle_line() -> str:
    return f'run idle: no task it may start; waiting for TODO.md to change (Ctrl-C or {C.command} stop to end it)'


TRIED_TEXT: dict[str, str] = {}  # a tried task's line as it read once it was tried: `retry_reopened` compares


def retry_reopened(tried: set[str], closed: set[str], branch: str) -> None:
    """Put back in the pool every tried task whose line has closed and opened again, or been edited, since it was
    tried.

    `tried` keeps a task from being started twice in a run, which is right for one that ended still open
    (it failed: a human looks next) and wrong once the human has looked: a task blocked and then unblocked by
    hand, or one whose text changed (a `plan note` with what to do differently, a corrected line) carries new
    information, and a run that stays up for days would otherwise never try it again. `closed` is the tried
    tasks seen blocked or gone from TODO.md since; one seen open again after that is retried. An open one is
    retried when its line differs from how it read the first time this saw it tried (moving it doesn't count).
    """
    if not tried:
        TRIED_TEXT.clear()
        return
    ls = plan_text(branch)
    lines = {tid: (box, ls[i].strip()) for _, box, tid, _, i in P.iter_tasks(ls)}
    for t in list(TRIED_TEXT):
        if t not in tried:
            del TRIED_TEXT[t]
    for t in list(tried):
        box, text = lines.get(t, (None, ''))
        if box != ' ':
            closed.add(t)
            TRIED_TEXT.pop(t, None)
        elif t in closed:
            tried.discard(t)
            closed.discard(t)
            log(f'{t}: open again since it was tried; back in the pool')
        elif t not in TRIED_TEXT:
            TRIED_TEXT[t] = text
        elif TRIED_TEXT[t] != text:
            tried.discard(t)
            del TRIED_TEXT[t]
            log(f'{t}: its line changed since it was tried; back in the pool')


FLAKY_KIND = 'T'  # C14: the id prefix a flaky, broken or runaway test's task gets (was [run] flaky_kind)
FLAKY: dict[str, str] = {}  # a test that failed under load and passed alone -> the task whose gate saw it
# a test that failed on the merge and on its base too -> (the task, the base, whether the daily whole test found it)
BROKEN: dict[str, tuple[str, str, bool]] = {}


def flaky(tid: str, names: list[str]) -> None:
    for n in names:
        FLAKY.setdefault(n, tid)


def file_flaky(rel: str) -> list[str]:
    """File a critical follow-up to make each flaky test robust, each runaway one bounded, and each one the
    shared branch already fails passing again, unless an open task names it already.

    A rerun alone lets the merge through, but the flake is still there and costs every later gate a rerun (or a
    red one, when it flakes twice), so it is fixed before the queued work rather than worked around."""
    if not FLAKY and not HOGS and not BROKEN:
        return []
    ls = P.lines(ROOT / rel)
    open_text = '\n'.join(l for l in ls if (m := P.ITEM.match(l)) and m.group(2) != 'x')
    kind, out = FLAKY_KIND, []
    for name, (gb, where) in list(HOGS.items()):
        del HOGS[name]
        if name in open_text:
            continue
        out.append(add_test_task(kind, name, f'stop growing: it held {gb} GB in {where} until the run\'s '
                               f'memory watch ended it. Find what it allocates without bound (a walk that loops, '
                               f'a list grown per case) and bound it', rel))
        open_text += '\n' + name
    for name, (tid, base, daily) in list(BROKEN.items()):
        del BROKEN[name]
        if name in open_text:
            continue
        how = (' The daily whole test found it: a selective gate ([run] test_since) let in whatever broke it, so '
               'also make the selection reach this test from what it reads.') if daily else ''
        out.append(add_test_task(kind, name, f'pass again: it fails on the shared branch ({base[:10]}), '
                               f'found by {tid}\'s merge gate, which merged anyway as not its doing. Find the '
                               f'merge that broke it (git bisect from the last gate it passed) and fix the code '
                               f'or the test.{how}', rel))
        open_text += '\n' + name
    for name, tid in list(FLAKY.items()):
        del FLAKY[name]
        if name in open_text:
            continue
        out.append(add_test_task(kind, name, f'robust: it failed under load in {tid}\'s merge gate and '
                               f'passed alone. Find what it races (wall-clock time, shared ports or files, '
                               f'other processes) and remove that, rather than widening a timeout', rel))
        open_text += '\n' + name
    return out


def add_test_task(kind: str, name: str, what: str, rel: str) -> str:
    """`file_flaky`'s task "make the test `name` <what>", critical and stamped with the day it was filed; the
    third within a week for one test (B34, `ci.closed_repeats`) is filed blocked on a person instead."""
    tid = P.add(kind, f'make the test `{name}` {what} {ci.filed_stamp()} | test: {name}', todo=ROOT / rel,
                pri='critical')
    earlier = ci.closed_repeats(P.lines(ROOT / plan_rel('DONE.md')), f'make the test `{name}` ')
    if len(earlier) >= ci.REPEAT_LIMIT - 1:
        P.block(tid, ci.repeat_ask(f'the test `{name}`', earlier), todo=ROOT / rel, after=[])
        log(f'{tid}: the test `{name}` failed again after {", ".join(earlier)} closed; blocked on a person')
    return tid


def land_tick(tid: str, merged: str) -> None:
    """A plan outside the repo: tick what `done` finished, now that its code is on the shared branch, with
    where it landed. Ticked at `done` instead, a merge left for a human would leave the task closed."""
    mark = plansync.ticks(C) / tid
    if not C.plan_external or not mark.exists():
        return
    with plansync.locked(C):
        plansync.pull(C, force=True)
        if tid in P.open_ids(P.lines(C.todo)):
            P.note(tid, f'landed {merged[:10]}', todo=C.todo)
            P.tick(tid, C.todo, C.done)
            if out := plansync.publish(C, f'tick {tid} (landed {merged[:10]})'):
                log(f'{tid}: {out}')
    mark.unlink(missing_ok=True)


def reopen_landed(branch: str, why: str) -> None:
    if not C.plan_external:
        return _reopen_landed(branch, why)
    with plansync.locked(C):
        plansync.pull(C, force=True)
        _reopen_landed(branch, why)


def _reopen_landed(branch: str, why: str) -> None:
    """File the flaky tests the gate met (`file_flaky`), and unblock what a merge freed (`plan.reopen`), each
    committed in the main checkout, holding MERGE.

    Without it, a task blocked on "X is not merged yet" stays blocked until a human reads the prose. Left alone when TODO.md has edits nobody
    committed (somebody mid-edit), so it never commits theirs; the next merge tries again.
    """
    rel = plan_rel('TODO.md')
    if git('branch', '--show-current').stdout.strip() != branch or git('status', '--porcelain', '--', rel).stdout.strip():
        return
    if filed := file_flaky(rel):
        if not commit_plan(f'Plan: {", ".join(filed)} to fix flaky, runaway or failing tests ({why}\'s merge)', rel):
            git('checkout', '-q', '--', rel)
        else:
            for t in filed:
                note(f'{t}: filed, a flaky, runaway or failing test to fix')
                log(f'{t}: filed (critical), a flaky, runaway or failing test to fix')
    if not (got := P.reopen(ROOT / rel)):
        return
    names = ', '.join(t for t, _ in got)
    if not commit_plan(f'Plan: reopen {names} ({why} landed what they waited on)', rel):
        git('checkout', '-q', '--', rel)
        return
    REOPENED.update(t for t, _ in got)
    back = {a[1] for a in P.asks(ROOT / rel)}  # B60: a person's check that waited on a task goes back to them
    for t, ids in got:
        said = f'{t}: back under Needs you' if t in back else f'{t}: reopened'
        note(f'{said}, {", ".join(ids)} landed')
        log(f'{said}, {", ".join(ids)} landed')
def reopen_until(branch: str, ids: list[str]) -> list[str]:
    """F427c: reopen the tasks `ids` whose until checks all passed, committed in the main checkout as
    `_reopen_landed` commits: holding MERGE, left alone when TODO.md has edits nobody committed (the next round tries
    again). With a shared plan it is pulled first, so a task another machine reopened is not reopened twice. The ids
    reopened."""
    from agent_runner.state import MERGE
    if not ids or not MERGE.acquire(blocking=False):
        return []
    try:
        if not C.plan_external:
            return _reopen_until(branch, ids)
        with plansync.locked(C):
            plansync.pull(C, force=True)
            return _reopen_until(branch, ids)
    finally:
        MERGE.release()


def _reopen_until(branch: str, ids: list[str]) -> list[str]:
    rel = plan_rel('TODO.md')
    if git('branch', '--show-current').stdout.strip() != branch or git('status', '--porcelain', '--', rel).stdout.strip():
        return []
    todo = ROOT / rel
    ls = P.lines(todo)
    said = {}
    for _, box, tid, _, i in P.iter_tasks(ls):
        if tid in ids and box == '~' and (got := P.until_of(ls, i)):
            said[tid] = P.until_label(got, C)
    back = {a[1] for a in P.asks(todo)}
    done = [t for t in said if P.until_passed(t, todo)]
    if not done:
        return []
    if not commit_plan(f'Plan: reopen {", ".join(done)} (until checks passed)', rel):
        git('checkout', '-q', '--', rel)
        return []
    REOPENED.update(done)
    back = {a[1] for a in P.asks(todo)} - back
    for t in done:
        msg = f'{t}: {"back under Needs you" if t in back else "reopened"}, {said[t]} passed'
        note(msg)
        log(msg)
    return done


# F42: a task the stopping run no longer waits for (B19's `halts` logs 'dropped <ID>; …')


RELEASE_HEAD = re.compile(r'^##\s+\[?v?(\d+(?:\.\d+)+)\b', re.M)  # a CHANGELOG.md version heading
RELEASE_TAG = re.compile(r'^v?(\d+(?:\.\d+)+)$')
RELEASES_SAID: set[str] = set()  # versions `announce_release` logged this run: a batch lands once per task


def _vtuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split('.'))


def changelog_entry(rev: str, version: str | None = None) -> tuple[str, str] | None:
    """(version, its first changelog line) from CHANGELOG.md at `rev`: the newest version heading, or the one
    for `version`; None when there is none. The first line is the entry's first bullet (or paragraph),
    unwrapped, to its first sentence, at most 160 characters; '' when the entry is empty."""
    r = git('show', f'{rev}:CHANGELOG.md')
    if r.returncode:
        return None
    text = r.stdout
    heads = [h for h in RELEASE_HEAD.finditer(text) if version is None or h[1] == version]
    if not heads:
        return None
    h = heads[0]
    nxt = re.search(r'^#', text[h.end():], re.M)
    body = text[h.end():h.end() + nxt.start() if nxt else None].split('\n', 1)[1:]
    first = []
    for l in (body[0] if body else '').splitlines():
        s = l.strip()
        if not s:
            if first:
                break
            continue
        if first and s.startswith(('- ', '* ')):
            break
        first.append(s[2:] if not first and s.startswith(('- ', '* ')) else s)
    line = re.split(r'(?<=[.!?])\s', ' '.join(first), maxsplit=1)[0] if first else ''
    if len(line) > 160:
        line = line[:159].rsplit(' ', 1)[0] + '…'
    return h[1], line


def release_line_for(base: str, merged: str) -> str | None:
    """F51: '<repo> 0.53.0 released: <first changelog line>' when the merge `base`..`merged` brought a release
    onto the shared branch (a newer version heading at the top of CHANGELOG.md, or a new version tag), else
    None."""
    new, old = changelog_entry(merged), changelog_entry(base)
    version, first = None, ''
    if new and (not old or _vtuple(new[0]) > _vtuple(old[0])):
        version, first = new
    else:
        tags = [t for t in git('tag', '--merged', merged, '--no-merged', base).stdout.split() if RELEASE_TAG.match(t)]
        if tags:
            tag = max(tags, key=lambda t: _vtuple(RELEASE_TAG.match(t)[1]))
            version = RELEASE_TAG.match(tag)[1]
            got = changelog_entry(merged, version)
            first = got[1] if got else git('tag', '-l', '--format=%(contents:subject)', tag).stdout.strip()
    if not version:
        return None
    return f'{ROOT.name} {version} released' + (f': {first}' if first else '')


def announce_release(base: str, merged: str) -> None:
    """Log `release_line_for`'s line once per version, for `since --follow`."""
    try:
        line = release_line_for(base, merged)
    except Exception:
        return
    if line and (v := line.split(' ')[1]) not in RELEASES_SAID:
        RELEASES_SAID.add(v)
        log(line, EV_RELEASED)
