"""`done`'s kept pages and write-ups: a concept's page link and local copy, a task's finished write-up (F74, F509, F513)."""
from __future__ import annotations

import datetime as dt
import re
import sys
from pathlib import Path

from agent_runner.done_docs import changed


def _prog() -> str:
    from agent_runner import done
    return done.PROG  # read late: a wrapper sets its own name


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
            print(f'{_prog()}: --page {page} is not a file: no local copy kept', file=sys.stderr)
        return None
    try:
        dest = c.notes('concepts', f'{tid}.html')
        dest.write_bytes(src.read_bytes())
    except OSError as e:
        print(f'{_prog()}: could not keep a copy of the page ({e})', file=sys.stderr)
        return None
    return dest


def writeup_file(c, tid: str) -> Path:
    """F509: where a task's finished write-up is kept, beside the run's notes, so it outlives log rotation."""
    return c.notes('writeups', f'{tid}.md')


def keep_writeup(c, tid: str, text: str) -> Path | None:
    """F509: keep what the agent says it did when it finishes (`run finish`'s summary) with task `tid`."""
    if not tid or not (text or '').strip():
        return None
    try:
        f = writeup_file(c, tid)
        f.write_text(text.strip() + '\n', encoding='utf-8')
        return f
    except OSError:
        return None


def journal_entry(c, tid: str) -> str:
    """F509: the task's newest journal notes, when the repo keeps a journal; '' else."""
    if not (j := c.journal):
        return ''
    try:
        dirs = sorted(d for d in j.iterdir() if d.is_dir() and
                      (d.name == tid or re.search(rf'-{re.escape(tid.lower())}(-|$)', d.name.lower())))
        return (dirs[-1] / 'notes.md').read_text(encoding='utf-8').strip() if dirs else ''
    except OSError:
        return ''


def writeup(c, tid: str) -> str:
    """F509: a task's finished write-up: its kept summary, then its journal entry; '' when it has none."""
    try:
        said = writeup_file(c, tid).read_text(encoding='utf-8').strip()
    except OSError:
        said = ''
    said = said or logged_writeup(c, tid)
    return '\n\n'.join(p for p in (said, journal_entry(c, tid)) if p)


def logged_writeup(c, tid: str) -> str:
    """F513: for a task that finished before write-ups were kept, its newest `finished:` summary from the run's
    events (the full summary), else from run.log (cut at 300 characters); '' when neither has one."""
    import json
    said = ''
    try:
        for line in c.notes('events.jsonl').read_text(encoding='utf-8', errors='replace').splitlines():
            if f'"{tid}"' not in line:
                continue
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get('kind') == 'finished' and e.get('id') == tid:
                said = (e.get('summary') or '').strip() or said
    except OSError:
        pass
    if said:
        return said
    pat = re.compile(rf'^=== \S+ slot \d+: {re.escape(tid)} finished: (.*)$')
    try:
        for line in c.notes('run.log').read_text(encoding='utf-8', errors='replace').splitlines():
            if (m := pat.match(line)) and m[1].strip():
                said = m[1].strip()
    except OSError:
        pass
    return said

