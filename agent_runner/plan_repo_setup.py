"""F460: `plan repo-setup [URL|path]`: turn plan repo mode on in one step.

Makes (or takes) the plan repo, moves the plan in the code repo (TODO.md, DONE.md, tasks/ long forms) into it with
its history kept (`git subtree split`), sets `[plan] repo` in runner.toml in a commit on this checkout's branch,
and says the one line the second machine needs. A plan repo that already holds a plan is joined: this checkout
reads that plan from now on and its own in-repo copy goes, as on the first machine.
"""
from __future__ import annotations

import re
import shutil
import tomllib
from pathlib import Path

from agent_runner import config as CF
from agent_runner.gitops import git


def is_url(t: str) -> bool:
    return '://' in t or bool(re.match(r'^[\w.-]+@[\w.-]+:', t))


def default_target(c) -> Path:
    return c.home / 'plan.git'


def join_line(repo: str) -> str:
    return f'On the other machine, in its checkout: git pull, then agent-runner plan repo-setup {repo}'


def _heads(target: str, cwd: Path) -> list[str]:
    r = git('ls-remote', '--heads', target, cwd=cwd)
    if r.returncode:
        raise SystemExit(f'agent-runner: cannot read the plan repo {target}: {r.stderr.strip()}')
    return r.stdout.split()


def _local_target(c, target: str | None) -> str:
    """A path: made as an empty bare repo when it is not there yet."""
    p = Path(target).expanduser() if target else default_target(c)
    p = (c.root / p).resolve() if not p.is_absolute() else p
    if p.is_relative_to(c.root):
        raise SystemExit(f'agent-runner: the plan repo {p} must be outside the code repo')
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        if (r := git('init', '-q', '--bare', '-b', 'main', str(p), cwd=p.parent)).returncode:
            raise SystemExit(f'agent-runner: cannot make {p}: {r.stderr.strip()}')
    return p.as_posix()


def _set_toml(root: Path, repo: str) -> None:
    f = root / 'runner.toml'
    text = f.read_text(encoding='utf-8') if f.exists() else ''
    text = CF.toml_edit(text, 'plan', 'repo', repo)
    raw = tomllib.loads(text)
    d = (raw.get('agent-runner', raw).get('plan') or {}).get('dir')
    if d is not None and (root / Path(d).expanduser()).resolve().is_relative_to(root.resolve()):
        text = CF.toml_edit(text, 'plan', 'dir', unset=True)  # the clone goes to its default place
    f.write_text(text, encoding='utf-8')


def setup(c, target: str | None = None) -> list[str]:
    """Plan repo mode on for this checkout; the lines to print. SystemExit with the reason when it cannot."""
    from agent_runner import plansync
    if c.plan_repo:
        plansync.ensure_clone(c)
        plansync.pull(c, force=True)
        return [f'plan repo mode is on: {c.plan_repo}, cloned in {c.plan_dir}', join_line(c.plan_repo)]
    if c.plan_external:
        raise SystemExit(f'agent-runner: [plan] dir {c.plan_dir} is outside the code repo; set [plan] repo by hand')
    root = c.root
    rel = c.plan_dir.relative_to(root).as_posix()
    if rel in ('', '.'):
        raise SystemExit('agent-runner: the plan is the repo\'s root; move it into a folder (plan/) first')
    repo = target if target and is_url(target) else _local_target(c, target)
    out = []
    if _heads(repo, root):
        out.append(f'joined the plan already in {repo}; this checkout\'s own plan copy goes')
    else:
        tracked = git('ls-files', '--', rel, cwd=root).stdout.strip()
        if not tracked:
            raise SystemExit(f'agent-runner: no plan committed in {rel}/ to move')
        r = git('subtree', 'split', '-q', '-P', rel, 'HEAD', cwd=root)
        sha = r.stdout.strip().splitlines()[-1] if not r.returncode and r.stdout.strip() else ''
        if not sha:
            raise SystemExit(f'agent-runner: git subtree split -P {rel} failed: {r.stderr.strip()}')
        if (r := git('push', '-q', repo, f'{sha}:refs/heads/main', cwd=root)).returncode:
            raise SystemExit(f'agent-runner: cannot push the plan to {repo}: {r.stderr.strip()}')
        out.append(f'moved {rel}/ with its history to {repo}')
    work = c.plan_dir
    keep = c.root / '.git' / 'plan-repo-setup'  # the working copy, edits not yet committed included
    if keep.exists():
        shutil.rmtree(keep)
    shutil.copytree(work, keep)
    joined = bool(out[0].startswith('joined'))
    _set_toml(root, repo if is_url(repo) else Path(repo).as_posix())
    git('rm', '-r', '-q', '--cached', '--', rel, cwd=root)
    shutil.rmtree(work)
    git('add', 'runner.toml', cwd=root)
    if (r := git('commit', '-qm', f'plan: the plan moves to its own repo, {repo}', cwd=root)).returncode:
        raise SystemExit(f'agent-runner: cannot commit runner.toml: {r.stderr.strip() or r.stdout.strip()}')
    out.append('runner.toml: [plan] repo set and committed on this branch')
    n = CF.Config(root)
    plansync.ensure_clone(n)
    if not joined:  # what was edited but not committed in the code repo goes along
        shutil.copytree(keep, n.plan_dir, dirs_exist_ok=True)
        plansync.publish(n, 'the working copy at repo-setup')
    else:
        from agent_runner import plan as P
        mine = P.open_ids(P.lines(keep / 'TODO.md')) if (keep / 'TODO.md').exists() else set()
        there = ''.join(p.read_text(encoding='utf-8') for p in (n.todo, n.done) if p.exists())
        if gone := sorted(t for t in mine if f'**{t}**' not in there):
            out.append(f'open here but not in the plan repo (add them again if still wanted): {", ".join(gone)}')
    shutil.rmtree(keep)
    out.append(f'the plan is cloned in {n.plan_dir}')
    out.append(join_line(repo))
    return out
