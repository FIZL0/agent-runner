"""C52: `plan brief`, what a session starts from, taken out of plan.py.

Moved out of plan.py with no change: `plan` re-exports every name here, so `plan.<name>` still works.
Import `agent_runner.plan` first (it imports this module last, once its own names exist)."""
from __future__ import annotations

import os
import re
import shlex
import subprocess
from pathlib import Path
from agent_runner.config import cfg
from agent_runner.gitops import git
from agent_runner.plan import JOURNAL_MAX, PROG, fields, files_on_line, lines, long_form, section


def brief(tid: str, root=None, plan_dir=None, journal=None) -> list[str]:
    """Everything a task starts from, in one command.

    This is the highest-value thing in the module. A fresh session otherwise spends its first five or six
    turns finding the task line, looking for a `plan/tasks/<ID>.md`, hunting the journal directory, opening the
    files and running `git log` on them — all of it predictable, all of it paid for again on every turn after.
    `brief` assembles it once:

      * the task's own line (and sub-items) from TODO.md or DONE.md,
      * `plan/tasks/<ID>.md` in full, if the task has a long form,
      * its journal directory: the file list, and the newest entry pasted in (capped at JOURNAL_MAX chars,
        because the newest entry is where the last session said whose move it is),
      * the files named on the line: where they actually are, how long they are, and their last 3 commits —
        so the session knows whether someone changed them yesterday before it reads a single one — and,
        with `[plan] outline` (a command; {file} is the path), each file's outline: the map of what is
        where, so a session reads the part it needs instead of paging through the file to find it,
      * and the output of `[plan] brief_extra` (a command; {id} is the task), for what only the project
        knows how to find.

    `./run run` pastes this into the agent's first turn. A project whose own tool already writes a brief
    (one that also sets things up for the session, say) names it in `[plan] brief`, and its output is
    the brief instead.
    """
    c = cfg(root)
    root = c.root
    plan_dir = Path(plan_dir or c.plan_dir)
    journal = Path(journal) if journal else c.journal
    paths = [plan_dir / 'TODO.md', plan_dir / 'DONE.md']
    line = next((o for p in paths if (o := section(p, tid))), [])
    if not line:
        raise SystemExit(f'{PROG}: no task {tid!r} in {plan_dir}/TODO.md or DONE.md')
    text = '\n'.join(line)
    out = [f'## Task {tid} ({plan_dir.name}/TODO.md)', *line]
    own = long_form(plan_dir, tid)
    own_rel = f'{plan_dir.name}/{own.relative_to(plan_dir).as_posix()}'
    if own.exists():
        out += ['', f'## {own_rel}', *lines(own)]
        text += '\n' + '\n'.join(lines(own))

    # journals: the ones the line points at (`j: <dir>`) and any whose name carries this id
    named = fields(text).get('journal', [])
    try:
        dirs = sorted(d for d in os.listdir(journal) if (journal / d).is_dir()) if journal else []
    except OSError:
        dirs = []
    own_j = [d for d in dirs if d == tid or re.search(rf'-{re.escape(tid.lower())}(-|$)', d.lower())]
    for j in dict.fromkeys(named + own_j) if journal else ():  # `j:` on a line with no journal dir set
        d = journal / j
        if not d.is_dir():
            continue
        # entries: its .md files and those one folder down (an `id` layout's repeat attempts, <date>-<slug>/)
        files = sorted(p.relative_to(d).as_posix() for p in [*d.glob('*.md'), *d.glob('*/*.md')])
        rel = os.path.relpath(d, root).replace(os.sep, '/')
        out += ['', f'## Journal {rel}/: {" · ".join(files)}']
        if files and j in own_j:  # journals the line only points at are listed, not pasted
            newest = max(files, key=lambda f: (m[0] if (m := DATE.search(f)) else '', f))  # dated beats undated
            body = (d / newest).read_text(encoding='utf-8', errors='replace')
            cut = len(body) > JOURNAL_MAX
            out += [f'### {newest}' + (f' (first {JOURNAL_MAX} chars)' if cut else ''),
                    body[:JOURNAL_MAX].rstrip()]

    where = [p for p in files_on_line(text) if p != own_rel and '*' not in p]
    if where:
        out += ['', '## Files on the line, and their last commits']
        for t in where:
            log = git('log', '-3', '--format=%h %ad %s', '--date=short', '--', t, cwd=root).stdout.strip().splitlines()
            try:
                n_lines = sum(1 for _ in open(root / t, encoding='utf-8', errors='replace'))
                size = f'{n_lines} lines'
            except OSError:
                size = 'missing — this task creates it'
            out += [f'- `{t}` ({size})', *[f'  - {l[:120]}' for l in log]]
            if (cmd := c.raw['plan']['outline']) and size[0].isdigit():
                out += outline(cmd, t, root)
    if cmd := c.raw['plan']['brief_extra']:  # what only the project knows: its oracle names, a spec, …
        r = subprocess.run(cmd.format(id=tid), shell=True, cwd=str(root), capture_output=True, text=True,
                           errors='replace')
        if extra := (r.stdout.rstrip() or (f'({cmd} failed: {r.stderr.strip()[:200]})' if r.returncode else '')):
            out += ['', *extra.splitlines()]
    return out


DATE = re.compile(r'\d{4}-\d{2}-\d{2}')
OUTLINE_MAX = 6000  # chars of one file's outline in a brief


def outline(cmd: str, path: str, root) -> list[str]:
    """`[plan] outline` for one file, indented under its entry in the brief; a failure says so in one line."""
    cmd = cmd.format(file=shlex.quote(path))
    try:
        r = subprocess.run(cmd, shell=True, cwd=str(root), capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return [f'  (outline: `{cmd}` ran past 60 s)']
    if r.returncode or not r.stdout.strip():
        return [f'  (outline: `{cmd}` failed: {r.stderr.strip()[:150]})'] if r.returncode else []
    text = r.stdout.rstrip()
    cut = f'  … (outline cut at {OUTLINE_MAX} chars)' if len(text) > OUTLINE_MAX else ''
    return ['  outline:', *(f'    {l}' for l in text[:OUTLINE_MAX].splitlines()), *([cut] if cut else [])]
