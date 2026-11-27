"""`./run done <ID> "<message>"`: how a session finishes a task, in one call that cannot be half-done.

    ./run done T4 "T4: the parser reads nested lists"
    ./run done T4 "T4 (part): lists parse, maps do not" --blocked "maps need T7's tokenizer" --after T7

In order: the test gate (`[run] test`), then tick the task (or
block it), `git add -A`, commit, and push the branch it committed on — unless that is the shared branch,
which only the runner pushes, after a merge.

One command rather than five because each of the five is a step a session forgets: a tick without the
commit, a commit without the tests, a branch never pushed. A failing gate commits nothing and ticks
nothing, so a "done" task is always one whose tests passed. Failed gates are counted per task in the
worktree's git dir (a pass or a block resets it): after three, `done` runs one more only if the worktree's content
changed since the last failure, and refuses `--blocked "CONFIRM: …"` until then (any other why blocks). If that one
fails too, it refuses until the task is blocked.

`[run] done_test` (F178) is what `done` runs in place of the test gate, on a docs-only diff too; the merge still
runs the gate, so a pass of it alone never lets a merge skip it.

A diff that is docs only (every file the worktree changes since the shared branch matches `[run] docs_files`)
skips the gate: `done` says 'docs only, gate skipped' and runs `[run] docs_check` instead, if one is set.

`--blocked WHY` marks it `[~]` instead. Say what would unblock it. If what it waits on is another task
landing, `--after ID[,ID]` (or just naming the open ids in WHY) lets a run reopen it once they merge. A CONFIRM or
BLOCKED that waits for an open task or release with no `--after`, or over 200 characters with no ask file, is refused.

`--until CHECK[,CHECK]`, with `--blocked`, is for a wait this machine can check by itself (`version:X.Y.Z`,
`login:PROVIDER`, `tool:NAME`, `check:NAME`; all must pass), in place of `--after`. A bad check is refused before the
gate runs.

F416: before the gate, a diff that deletes or renames a file, test, setting or command is checked for what still names
it: a dead path in code, config or CI is refused, and the rest is a list to answer once, with `--named "1 filed B12; 2
kept because …"` (`stale.py`).

`--artifact URL` is the page a concept task (kind K) published: required for one, which builds nothing.
It notes the link on the task (and in its journal), and files the build task blocked until a person
approves an option (`plan approve`). F74: it also keeps a local copy of the page at <notes>/concepts/<ID>.html
for the run page to show inline: `--page FILE` (the HTML it was published from), else the newest .html file
the worktree changed.

    ./run done K7 "K7: three layouts for the settings page" --artifact https://claude.ai/code/artifact/…
"""
from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import os
import re
import shutil
import stat
import sys
import tempfile
from functools import partial
from pathlib import Path

from agent_runner import asks, audit_fix, lessons_ask, plan, plansync, shared_tools, stale
from agent_runner.config import cfg, finished_mark
from agent_runner.gitops import git, missing_remote, push, shared_branch, shared_name, shell


PROG = 'run done'  # the name in messages; a wrapper sets its own ('kit done')
TESTED = 'refs/agent-runner/tested/'  # + <ID>: the commit whose tree `done`'s gate passed on
PARTIAL = 'refs/agent-runner/done-test/'  # + <ID>: the tested commit, when only `[run] done_test` passed on it
MAX_FAILS = 3  # failed gates a task gets in one worktree; a fourth runs only on changed content (B186)
__all__ = ['gate', 'main', 'PROG']


def gate(cwd: Path, key: str = 'test', full: bool = False, env: dict | None = None) -> tuple[int, str]:
    """Run `[run] <key>` in `cwd`; (exit code, last lines of its output, or all of it). (0, '') when not set."""
    cmd = cfg(cwd).run[key]
    if not cmd:
        return 0, ''
    rc, out = shell(cmd, cwd, env, cfg(cwd).run['command_timeout'])
    if rc is None:
        return 124, f'`{cmd}` ran past [run] command_timeout ({cfg(cwd).run["command_timeout"]}s): counted as failing'
    out = out.strip()
    return rc, out if full else '\n'.join(out.splitlines()[-15:])


DOCS_SKIP = 'docs only, gate skipped'  # what `done` and the merge say when a diff is all `[run] docs_files`


def docs_only(files: list[str], globs: list[str]) -> bool:
    """Every one of `files` (at least one) matches `[run] docs_files` (the last glob that matches decides,
    `!glob` takes a file back): a diff the test gate need not run on."""
    def doc(f: str) -> bool:
        hit = False
        for g in globs:
            if fnmatch.fnmatch(f, g.lstrip('!')):
                hit = not g.startswith('!')
        return hit
    return bool(files) and all(map(doc, files))


def changed(cwd: Path) -> list[str]:
    """The files this worktree's work changes: commits since the shared branch, staged, unstaged and untracked
    (renames as both names, so a code file moved into docs/ still counts as code)."""
    shared = shared_name(cwd, cfg(cwd).push_remote or 'origin', default=None)
    base = shared and git('merge-base', 'HEAD', shared, cwd=cwd).stdout.strip() or 'HEAD'
    files = git('diff', '--name-only', '--no-renames', base, cwd=cwd).stdout.splitlines()
    files += git('ls-files', '--others', '--exclude-standard', cwd=cwd).stdout.splitlines()
    return sorted({f for f in files if f})


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog=PROG, description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('id', metavar='ID')
    ap.add_argument('message', metavar='MSG', help='the commit message')
    ap.add_argument('--blocked', metavar='WHY', help='mark it [~] instead of done: why, and what unblocks it')
    ap.add_argument('--after', metavar='IDS', default=None,
                    help='with --blocked: the tasks it waits on, comma-separated (default: read off WHY)')
    ap.add_argument('--until', metavar='CHECKS', default=None,
                    help='with --blocked: what it waits on that this machine checks by itself, comma-separated '
                         '(version:X.Y.Z, login:PROVIDER, tool:NAME, check:NAME); all must pass')
    ap.add_argument('--artifact', metavar='URL',
                    help="the page a concept task (K) published; required for one: its build waits for a person's OK")
    ap.add_argument('--page', metavar='FILE',
                    help='with --artifact: the local HTML file the page was published from; a copy is kept '
                         '(<notes>/concepts/<ID>.html) for the run page to show inline')
    ap.add_argument('--no-test', action='store_true', help='skip the gate (say why in the message)')
    ap.add_argument('--named', metavar='ANSWERS',
                    help='answers the removal check\'s list of what still names what this diff removes, e.g. '
                         '"1 filed B12; 2-3 kept because <why>"')
    a = ap.parse_args(argv)
    c = cfg()
    cwd = c.root
    if why := until_refusal(a, c):  # F427b
        print(why, file=sys.stderr)
        return 2
    if why := asks.line_refusal(a.id, a.blocked, a.after, a.until, c, PROG):  # B795
        print(why, file=sys.stderr)
        return 2
    if why := concept_link_refusal(a.id, a.blocked, c):  # B839
        print(why, file=sys.stderr)
        return 2
    if not a.blocked and tested_tick(a.id, c) and not git('status', '--porcelain', cwd=cwd).stdout.strip():
        print(f'{a.id} is already ticked and committed, and its gate passed on this commit: nothing to do again')
        push_task(c)  # a `done` cut off before its push
        return finished(c, a)  # B172: the mark may be gone
    if not a.artifact and not a.blocked and plan.concept(a.id):  # F106f: the page `run publish-page` published
        from agent_runner.page_copy import concept_url
        a.artifact = concept_url(a.id, c) or None
        if a.artifact:
            a.page = a.page or (str(p) if (p := c.notes('concepts', f'{a.id}.html')).is_file() else None)
    if why := artifact_refusal(a):
        print(why, file=sys.stderr)
        return 2

    if os.environ.get('AGENT_RUNNER_SLOT') and not a.blocked:  # F98: the page the person approves the push on
        from agent_runner import pitch
        if pitch.on(c) and (why := pitch.part_problem(a.id, c)):
            print(f'{PROG}: {why} before {a.id} is done: what a person reads before they approve the push (your brief '
                  f'says how). Nothing ticked.', file=sys.stderr)
            return 2
    if c.pr and not a.blocked:  # F419: what its pull request says
        from agent_runner import pr
        if why := pr.done_problem(a.id, a.message, c):
            print(f'{PROG}: {why} (your brief says how). {a.id} is not done. Nothing ticked.', file=sys.stderr)
            return 2
    if why := gate_limit(a, cwd):
        print(why, file=sys.stderr)
        return 1
    if not a.blocked and (why := stale.refusal(a.id, a.named, c, content_hash(cwd), PROG)):  # F416
        print(why, file=sys.stderr)
        return 2
    if why := audit_fix.refusal(a.id, a.blocked, c, lambda: content_hash(cwd), PROG):  # F418
        print(why, file=sys.stderr)
        return 2
    a.docs = docs = bool(not a.no_test and c.run['test'] and docs_only(changed(cwd), c.run['docs_files']))
    own = c.run['done_test']  # F178: in place of `test`, whatever the diff is
    if docs and not own:  # no tested ref either: the merge decides by its own diff
        print(DOCS_SKIP + (f' (docs check: {c.run["docs_check"]})' if c.run['docs_check'] else ''))
    if not a.no_test:
        from agent_runner import merge_rows  # B852: the run page says Waiting to test, then Testing
        if own or not docs:
            merge_rows.mark_slot_gate(c, a.id, cwd, 'waiting')
            shared_tools.gate_wait(c)  # B184
        merge_rows.mark_slot_gate(c, a.id, cwd, 'testing')
        try:
            content = '' if a.blocked else content_hash(cwd)  # before the gate: what it ran on, not what it wrote
            key = 'done_test' if own else 'docs_check' if docs else 'test'
            rc, tail = gate(cwd, key)
            if own and docs and not rc and c.run['docs_check']:
                key = 'docs_check'
                rc, tail = gate(cwd, key)
        finally:
            merge_rows.clear_slot_gate(c, a.id)
        if rc:
            print(tail)
            lessons_ask.mark_failed_gate(cwd, a.id)  # F414
            if a.blocked:
                last = 'Commit only what is solid, and'
            elif (n := fails(cwd, a.id, add=True, content=content)) > MAX_FAILS:
                last = (f'That is {n} failed gates on {a.id}: {PROG} refuses any more until it is blocked. Commit what '
                        f'is solid and')
            elif n == MAX_FAILS:
                last = (f'That is {n} failed gates on {a.id}: {PROG} refuses a fourth unless you change something. Fix '
                        f'it and run {PROG} again (one last gate), or commit what is solid and')
            else:
                last = f'Failed gate {n} of {MAX_FAILS}. Fix it, or commit what is solid and'
            block_why = '<why + what unblocks it>' if a.blocked or n < MAX_FAILS else BLOCK_WHY
            what = {'docs_check': f'The docs check (`{c.run["docs_check"]}`)',
                    'done_test': f'[run] done_test (`{own}`)'}.get(key, 'The test gate')
            print(f'\n{what} failed: nothing ticked, nothing committed. {last}\n'
                  f'    {PROG} {a.id} "<msg>" --blocked "{block_why}"', file=sys.stderr)
            return 1
        if own:
            print(f'done_test passed: {own}')
        elif c.run['test'] and not docs:
            print(f'gate passed: {c.run["test"]}')
    if a.blocked or not a.no_test:  # a pass, or a block: the next session on it starts its count afresh
        fails(cwd, a.id, reset=True)

    if not a.blocked:
        lesson_ask(a.id, c)
    if not c.plan_external:
        return record(a, c)
    with plansync.locked(c):  # after the gate: a gate can take an hour, and the lock holds every plan edit
        plansync.pull(c, force=True)
        return record(a, c)


def lesson_ask(tid: str, c) -> None:
    """F414: print the lesson question when something went wrong in `tid`; never stops `done`."""
    try:
        ls = plan.lines(c.todo)
        item = '\n'.join(plan._item_block(ls, plan._find(ls, tid)))
    except (OSError, SystemExit, ValueError, IndexError):
        item = ''
    if q := lessons_ask.ask(c.root, tid, item, c):
        print(q, file=sys.stderr)


def record(a, c) -> int:
    """Tick (or block) the task, commit, push the branch. A plan outside the repo is published on its own,
    after the code commit; in a runner's slot its tick waits for the merge to land (`runner.land_tick`)."""
    cwd = c.root
    kept = {p: p.read_bytes() for p in (c.todo, c.done, plan.long_form(c.plan_dir, a.id)) if p.exists()}
    later = c.plan_external and not a.blocked and (finished_mark() is not None or c.pr)  # F419: a take's too
    again = not a.blocked and ticked(a.id, c)  # B172: `done` ran before; more work on top, or its mark is gone
    if a.artifact and not a.blocked and not again:
        journal_link(c, a.id, a.artifact)
        if plan.concept(a.id) and (kept_copy := keep_page(c, a.id, getattr(a, 'page', None))):
            print(f'kept a copy of the page: {kept_copy}')
        if plan.concept(a.id):
            bid = plan.concept_done(a.id, a.artifact)
            print(f'{bid} filed to build it, blocked until a person approves an option '
                  f'(`plan approve {a.id} "option B: …"`)')
        else:
            plan.note(a.id, f'page: {a.artifact}')
    if a.blocked:
        plan.block(a.id, a.blocked, after=None if a.after is None else [t for t in a.after.split(',') if t],
                   keep_ask=True, **({} if a.until is None else {'until': a.until.split(',')}))
        print(f'blocked {a.id}')
        if said := asks.long_line(a.id, a.blocked, c):  # F156
            print(f'note: {said}')
    elif again:
        print(f'{a.id} is already ticked')
    elif later:
        (plansync.ticks(c) / a.id).touch()
        print(f'{a.id} is ticked in {c.plan_dir} once ' + ('a person merges its pull request' if c.pr else 'its merge lands'))
    else:
        plan.tick(a.id)
        print(f'ticked {a.id}')

    g = partial(git, cwd=cwd)

    def untick() -> int:  # nothing committed: the plan as it was, so `done` can run again
        g('reset', '-q')
        for p, b in kept.items():
            p.write_bytes(b)
        if later:
            (plansync.ticks(c) / a.id).unlink(missing_ok=True)
        return 1

    if g('add', '-A').returncode:
        print('git add failed', file=sys.stderr)
        return untick()
    if (own := own_output(cwd)) and g('reset', '-q', '--', *(f':(top,literal){f}' for f in own)).returncode:
        print(f'git reset failed on {", ".join(own)}', file=sys.stderr)
        return untick()
    if not g('diff', '--cached', '--quiet').returncode:
        print('nothing to commit (the tick was already committed?)')
        if not a.no_test and not getattr(a, 'docs', False):
            mark_tested(a.id, c)
        push_task(c)
        return finished(c, a)
    message = a.message
    if not c.run['include_task_id_in_commit']:
        prefix = f'{a.id}:'
        if message.startswith(prefix):
            message = message[len(prefix):].lstrip(' \t')
    if (r := g('commit', '-qm', message)).returncode:
        print(f'git commit failed: {r.stderr.strip()}', file=sys.stderr)
        return untick()
    if not a.no_test and not getattr(a, 'docs', False):  # what the gate passed on, so a merge that differs from it only in [run] untested skips it
        mark_tested(a.id, c)
    print(g('log', '-1', '--oneline').stdout.strip())
    push_task(c)
    return finished(c, a)


def own_output(cwd: Path) -> list[str]:
    """B224: the staged files this command's own stdout or stderr goes to (`run done … > done.log 2>&1`): never part
    of the work. Paths from the top of the worktree."""
    ids = set()
    for fd in (1, 2):
        try:
            st = os.fstat(fd)
        except OSError:  # closed
            continue
        if stat.S_ISREG(st.st_mode) and st.st_ino:  # no inode: a file system that cannot say which file it is
            ids.add((st.st_dev, st.st_ino))
    if not ids:
        return []
    top = Path(git('rev-parse', '--show-toplevel', cwd=cwd).stdout.strip())
    out = []
    for f in git('diff', '--cached', '--name-only', '--no-renames', '-z', cwd=cwd).stdout.split('\0'):
        try:
            st = os.stat(top / f, follow_symlinks=False) if f else None
        except (OSError, ValueError):  # deleted, or a name this system cannot hold
            continue
        if st and (st.st_dev, st.st_ino) in ids:
            out.append(f)
    return out


def mark_tested(tid: str, c) -> None:
    """`done` passed on HEAD. With `[run] done_test` that was not the gate, so PARTIAL says so first and the merge
    runs it (`gate_passed_on`)."""
    git('update-ref', *([PARTIAL + tid, 'HEAD'] if c.run['done_test'] else ['-d', PARTIAL + tid]), cwd=c.root)
    git('update-ref', TESTED + tid, 'HEAD', cwd=c.root)


def gate_passed_on(tid: str, cwd: Path) -> str:
    """The tree `done`'s whole gate passed on, '' when none, or only `[run] done_test` (F178) did."""
    at = lambda ref, kind: git('rev-parse', '-q', '--verify', f'{ref}{tid}^{{{kind}}}', cwd=cwd).stdout.strip()  # noqa: E731
    commit = at(TESTED, 'commit')
    return '' if not commit or commit == at(PARTIAL, 'commit') else at(TESTED, 'tree')


def push_task(c) -> None:
    """Push the branch this worktree is on (never the shared one) and say what became of it."""
    cwd = c.root
    here = git('branch', '--show-current', cwd=cwd).stdout.strip()
    if here and (line := push(cwd, here)):
        print(line)
    elif here and c.approve:
        print(f'{here} not pushed: [run] approve is on, so it stays here until a person approves it')
    elif here and (gone := missing_remote(cwd)):
        print(f'{here} not pushed: no remote {gone}')
    elif here and (remote := c.push_remote) and shared_branch(cwd, remote, here):
        print(f'{here} is not pushed: done only pushes a task branch (git push {remote} {here} to publish)')


def ticked(tid: str, c) -> bool:
    """`done` already ticked `tid`: the tick is in this branch's last commit; for a plan outside the repo, in the
    plan itself, or left for the runner to make once the merge lands."""
    if not c.plan_external:
        texts = [git('show', f'HEAD:{p.relative_to(c.root).as_posix()}', cwd=c.root).stdout for p in (c.done, c.todo)]
    elif (plansync.ticks(c) / tid).exists():
        return True
    else:
        texts = [p.read_text(encoding='utf-8') for p in (c.done, c.todo) if p.exists()]
    return any(not m.group(1) and m.group(2) == 'x' and m.group(3).rstrip('.') == tid
               for t in texts for l in t.splitlines() if (m := plan.ITEM.match(l)))


def tested_tick(tid: str, c=None) -> bool:
    """`tid` is ticked and the commit its gate passed on is HEAD: `done` succeeded here, whatever became of the
    slot's mark (B172)."""
    c = c or cfg()
    ref = git('rev-parse', '--verify', '-q', TESTED + tid, cwd=c.root).stdout.strip()
    return bool(ref) and ref == git('rev-parse', 'HEAD', cwd=c.root).stdout.strip() and ticked(tid, c)


def fails_file(cwd: Path, tid: str) -> Path | None:
    """Where `tid`'s failed gates are counted: in this worktree's own git dir, so slots never share a count. A line
    `<count> <content hash>` per failure. None outside a repository."""
    r = git('rev-parse', '--absolute-git-dir', cwd=cwd)
    return None if r.returncode else Path(r.stdout.strip()) / 'agent-runner' / 'failed-gates' / tid


def last_fail(f: Path | None) -> tuple[int, str]:
    """The count and content hash of the last failure in `f`; (0, '') when none."""
    try:
        n, _, content = f.read_text().strip().splitlines()[-1].partition(' ') if f else ('0', '', '')
        return int(n), content
    except (OSError, ValueError, IndexError):
        return 0, ''


def fails(cwd: Path, tid: str, add: bool = False, reset: bool = False, content: str = '') -> int:
    """The failed `done` gates counted for `tid` in this worktree: `add` one that ran on `content`, or `reset` to
    none (a pass, or a block). The count after."""
    f = fails_file(cwd, tid)
    if f is None:
        return 0
    if reset:
        f.unlink(missing_ok=True)
        return 0
    n = last_fail(f)[0]
    if add:
        n += 1
        try:
            f.parent.mkdir(parents=True, exist_ok=True)
            with f.open('a') as fh:
                fh.write(f'{n} {content}\n')
        except OSError:
            pass
    return n


def content_hash(cwd: Path) -> str:
    """The tree of this worktree's files as they are (uncommitted and untracked too, ignored ones not), so a commit
    of the same files does not change it. Made in a copy of the index; the real one is not touched. '' on failure."""
    r = git('rev-parse', '--absolute-git-dir', cwd=cwd)
    if r.returncode:
        return ''
    real = Path(r.stdout.strip()) / 'index'
    with tempfile.TemporaryDirectory() as tmp:
        index = Path(tmp) / 'index'
        env = {**os.environ, 'GIT_INDEX_FILE': str(index)}
        try:
            if real.exists():
                shutil.copy2(real, index)  # with its mtime, by which git knows an entry it must read again
        except OSError:
            return ''
        if git('add', '-A', cwd=cwd, env=env).returncode:
            return ''
        return git('write-tree', cwd=cwd, env=env).stdout.strip()


BLOCK_WHY = '<the name of the failing test or check: why + what unblocks it>'


def gate_limit(a, cwd: Path) -> str | None:
    """B186: why `done` refuses at MAX_FAILS failed gates, or None. Content changed since the last failure gets one
    more gate, and until that ran a CONFIRM block is refused: it asks a person to mark done what a gate decides."""
    n, content = last_fail(fails_file(cwd, a.id))
    if n < MAX_FAILS:
        return None
    if a.blocked:
        if n > MAX_FAILS or not re.match(r'\s*CONFIRM:', a.blocked):
            return None
        return (f'{PROG}: the test gate failed {n} times on {a.id}, and a person cannot confirm a gate. Once it is '
                f'fixed, run {PROG} without --blocked: changed files get one more gate\n    {PROG} {a.id} "<msg>"\n'
                f'If it is not fixed, block with --blocked "{BLOCK_WHY}". Nothing blocked.')
    if a.no_test or n == MAX_FAILS and not (content and content == content_hash(cwd)):
        return None
    again = ('a fourth is not run on unchanged files. Fix it and run it again (one last gate), or commit'
             if n == MAX_FAILS else 'no more are run until it is blocked. Commit')
    return (f'{PROG}: the test gate failed {n} times on {a.id}: {again} what is solid and\n'
            f'    {PROG} {a.id} "<msg>" --blocked "{BLOCK_WHY}"\nNothing ticked.')


def until_refusal(a, c) -> str | None:
    """F427b: why `done` refuses its `--until`, or None."""
    if a.until is None:
        return None
    if not a.blocked:
        return f'{PROG}: --until goes with --blocked WHY. Nothing ticked.'
    if a.after:
        return plan.UNTIL_AFTER.format(prog=PROG)
    try:
        plan.until_list(a.until, c)
    except SystemExit as e:
        return str(e).replace(plan.PROG, PROG, 1)
    return None


def artifact_refusal(a) -> str | None:
    """Why `done` refuses these arguments, or None: a concept task finishes only with the page it published."""
    if a.artifact and not re.match(r'https?://\S+$', a.artifact) and a.artifact != f'/concept/{a.id}':  # F406e: local page
        return f'{PROG}: --artifact takes the page\'s URL (https://…), not {a.artifact!r}'
    if plan.concept(a.id) and not a.artifact and not a.blocked:
        return (f'{PROG}: {a.id} is a concept task: it builds nothing, it publishes a page of options. Publish it '
                f'(the Artifact tool), then\n    {PROG} {a.id} "<msg>" --artifact <its url>\nNothing ticked.')
    return None


def journal_link(c, tid: str, url: str) -> Path | None:
    """Write the page's link into the task's journal, when the repo keeps one (`[plan] journal`): the newest
    folder named for the task, else a new one in the repo's layout. The file it wrote to, or None."""
    if not (j := c.journal):
        return None
    try:
        dirs = sorted(d for d in j.iterdir() if d.is_dir() and
                      (d.name == tid or re.search(rf'-{re.escape(tid.lower())}(-|$)', d.name.lower())))
    except OSError:
        dirs = []
    d = dirs[-1] if dirs else j / (tid if c.raw['plan']['journal_layout'] == 'id'
                                   else f'{dt.date.today().isoformat()}-{tid.lower()}-concept')
    f = d / 'notes.md'
    try:
        d.mkdir(parents=True, exist_ok=True)
        with f.open('a', encoding='utf-8') as fh:
            fh.write(f'\n**Page:** {url}\n')
    except OSError:
        return None
    return f


def keep_page(c, tid: str, page: str | None = None) -> Path | None:
    """F74: keep a local copy of the page a concept task published, at <notes>/concepts/<ID>.html, so the run
    page shows it inline: `page` (`--page FILE`), else the newest .html file this worktree changed. The copy,
    or None when there is no such file."""
    src = Path(page) if page else None
    if src is None:
        found = [p for p in (c.root / f for f in changed(c.root) if f.lower().endswith(('.html', '.htm')))
                 if p.is_file()]
        src = max(found, key=lambda p: p.stat().st_mtime) if found else None
    if src is None or not src.is_file():
        if page:
            print(f'{PROG}: --page {page} is not a file: no local copy kept', file=sys.stderr)
        return None
    try:
        dest = c.notes('concepts', f'{tid}.html')
        dest.write_bytes(src.read_bytes())
    except OSError as e:
        print(f'{PROG}: could not keep a copy of the page ({e})', file=sys.stderr)
        return None
    return dest


def finished(c=None, a=None) -> int:
    """Publish a plan kept outside the repo; tell the slot's stop waiter this task is done, so a leftover
    background command can't hold the slot."""
    if c and c.plan_external and (out := plansync.publish(c, f'{a.id}: {a.message}')):
        print(out, file=sys.stderr)
    if c and a and not a.blocked:
        from agent_runner import control_settled  # F160: a take's own landing is not told to its session
        control_settled.done_by(c, a.id)
    if m := finished_mark():
        m.touch()
    return 0


def concept_link_refusal(tid: str, why: str | None, c) -> str | None:
    """B839: why `done --blocked` refuses a CONFIRM whose line or ask file names /concept/<ID> of a task that is no
    concept: no concept is filed for it, so that page is in no Concepts list and the person cannot open it."""
    if not re.match(r'\s*CONFIRM:', why or ''):
        return None
    text = why or ''
    try:
        f = asks.ask_file(tid, c)
        if f.is_file():
            text += '\n' + f.read_text(encoding='utf-8')
    except OSError:
        pass
    bad = sorted({i for i in re.findall(r'/concepts?/([A-Za-z]+\d+[a-z]*)', text) if not plan.concept(i)})
    if not bad:
        return None
    return (f'{PROG}: the CONFIRM names /concept/{bad[0]}, but no concept is filed for {", ".join(bad)}: the person '
            f'has no such page to open. Put what they watch or look at in the ask file\'s "shots" (pictures, or .mp4 '
            f'and .webm videos under {asks.ask_file(tid, c).with_suffix("")}/, 50 MB each), or give a link they can '
            f'open. Nothing blocked.')
