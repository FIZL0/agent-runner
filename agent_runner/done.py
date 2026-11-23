"""`./run done <ID> "<message>"`: how a session finishes a task, in one call that cannot be half-done.

    ./run done T4 "T4: the parser reads nested lists"
    ./run done T4 "T4 (part): lists parse, maps do not" --blocked "maps need T7's tokenizer" --after T7

In order: the test gate (`[run] test`), then tick the task (or
block it), `git add -A`, commit, and push the branch it committed on — unless that is the shared branch,
which only the runner pushes, after a merge.

One command rather than five because each of the five is a step a session forgets: a tick without the
commit, a commit without the tests, a branch never pushed. A failing gate commits nothing and ticks
nothing, so a "done" task is always one whose tests passed. Failed gates are counted per task in the
worktree's git dir: after three, `done` refuses to run a fourth until the task is blocked (a pass resets it).

A diff that is docs only (every file the worktree changes since the shared branch matches `[run] docs_files`)
skips the gate: `done` says 'docs only, gate skipped' and runs `[run] docs_check` instead, if one is set.

`--blocked WHY` marks it `[~]` instead. Say what would unblock it. If what it waits on is another task
landing, `--after ID[,ID]` (or just naming the open ids in WHY) lets a run reopen it once they merge.

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
import sys
from functools import partial
from pathlib import Path

from agent_runner import plan, plansync
from agent_runner.config import cfg, finished_mark
from agent_runner.gitops import git, missing_remote, push, shared_branch, shared_name, shell


PROG = 'run done'  # the name in messages; a wrapper sets its own ('kit done')
TESTED = 'refs/agent-runner/tested/'  # + <ID>: the commit whose tree `done`'s gate passed on
MAX_FAILS = 3  # failed gates a task gets in one worktree; the next `done` refuses to run a fourth
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
    ap.add_argument('--artifact', metavar='URL',
                    help="the page a concept task (K) published; required for one: its build waits for a person's OK")
    ap.add_argument('--page', metavar='FILE',
                    help='with --artifact: the local HTML file the page was published from; a copy is kept '
                         '(<notes>/concepts/<ID>.html) for the run page to show inline')
    ap.add_argument('--no-test', action='store_true', help='skip the gate (say why in the message)')
    a = ap.parse_args(argv)
    c = cfg()
    cwd = c.root
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
    if not a.blocked and not a.no_test and fails(cwd, a.id) >= MAX_FAILS:
        print(f'{PROG}: the test gate failed {MAX_FAILS} times on {a.id}: a fourth is not run. Commit what is '
              f'solid and\n    {PROG} {a.id} "<msg>" --blocked "<why + what unblocks it>"\nNothing ticked.',
              file=sys.stderr)
        return 1
    a.docs = docs = bool(not a.no_test and c.run['test'] and docs_only(changed(cwd), c.run['docs_files']))
    if docs:  # no tested ref either: the merge decides by its own diff
        print(DOCS_SKIP + (f' (docs check: {c.run["docs_check"]})' if c.run['docs_check'] else ''))
    if not a.no_test:
        rc, tail = gate(cwd, 'docs_check' if docs else 'test')
        if rc:
            print(tail)
            if a.blocked:
                last = 'Commit only what is solid, and'
            elif (n := fails(cwd, a.id, add=True)) >= MAX_FAILS:
                last = f'That is {n} failed gates on {a.id}: {PROG} refuses a fourth. Commit what is solid and'
            else:
                last = f'Failed gate {n} of {MAX_FAILS}. Fix it, or commit what is solid and'
            what = f'The docs check (`{c.run["docs_check"]}`)' if docs else 'The test gate'
            print(f'\n{what} failed: nothing ticked, nothing committed. {last}\n'
                  f'    {PROG} {a.id} "<msg>" --blocked "<why + what unblocks it>"', file=sys.stderr)
            return 1
        if c.run['test'] and not docs:
            print(f'gate passed: {c.run["test"]}')
    if a.blocked or not a.no_test:  # a pass, or a block: the next session on it starts its count afresh
        fails(cwd, a.id, reset=True)

    if not c.plan_external:
        return record(a, c)
    with plansync.locked(c):  # after the gate: a gate can take an hour, and the lock holds every plan edit
        plansync.pull(c, force=True)
        return record(a, c)


def record(a, c) -> int:
    """Tick (or block) the task, commit, push the branch. A plan outside the repo is published on its own,
    after the code commit; in a runner's slot its tick waits for the merge to land (`runner.land_tick`)."""
    cwd = c.root
    kept = {p: p.read_bytes() for p in (c.todo, c.done, plan.long_form(c.plan_dir, a.id)) if p.exists()}
    later = c.plan_external and not a.blocked and finished_mark() is not None
    if a.artifact and not a.blocked:
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
        plan.block(a.id, a.blocked, after=None if a.after is None else [t for t in a.after.split(',') if t])
        print(f'blocked {a.id}')
    elif later:
        (plansync.ticks(c) / a.id).touch()
        print(f'{a.id} is ticked in {c.plan_dir} once its merge lands')
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
    if not g('diff', '--cached', '--quiet').returncode:
        print('nothing to commit (the tick was already committed?)')
        if not a.no_test and not getattr(a, 'docs', False):
            g('update-ref', TESTED + a.id, 'HEAD')
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
        g('update-ref', TESTED + a.id, 'HEAD')
    print(g('log', '-1', '--oneline').stdout.strip())
    here = g('branch', '--show-current').stdout.strip()
    if here and (line := push(cwd, here)):
        print(line)
    elif here and c.approve:
        print(f'{here} not pushed: [run] approve is on, so it stays here until a person approves it')
    elif here and (gone := missing_remote(cwd)):
        print(f'{here} not pushed: no remote {gone}')
    elif here and (remote := c.push_remote) and shared_branch(cwd, remote, here):
        print(f'{here} is not pushed: done only pushes a task branch (git push {remote} {here} to publish)')
    return finished(c, a)


def fails(cwd: Path, tid: str, add: bool = False, reset: bool = False) -> int:
    """The failed `done` gates counted for `tid` in this worktree (its own git dir, so slots never share a
    count): `add` one, or `reset` to none (a pass, or a block). The count after."""
    r = git('rev-parse', '--absolute-git-dir', cwd=cwd)
    if r.returncode:
        return 0
    f = Path(r.stdout.strip()) / 'agent-runner' / 'failed-gates' / tid
    if reset:
        f.unlink(missing_ok=True)
        return 0
    try:
        n = int(f.read_text().strip() or 0)
    except (OSError, ValueError):
        n = 0
    if add:
        n += 1
        try:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(f'{n}\n')
        except OSError:
            pass
    return n


def artifact_refusal(a) -> str | None:
    """Why `done` refuses these arguments, or None: a concept task finishes only with the page it published."""
    if a.artifact and not re.match(r'https?://\S+$', a.artifact):
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
    if m := finished_mark():
        m.touch()
    return 0
