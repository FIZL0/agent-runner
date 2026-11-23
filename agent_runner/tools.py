"""F102: the runner tools a slot's agent uses on Claude Code: `run finish`, `run ask` and the git fence.

    run finish "summary"    the task is done (after `done`): the summary is recorded and the Stop hook ends
                            the session at once, instead of waiting out the idle time
    run ask "question"      a question only a person can answer: the run parks the task under Needs you, and
                            the person's answer resumes this same session as its next message

Both leave the slot's end mark, `<notes>/slot<N>.end` ({how: finish|ask, tid, text}); the Stop hook ends the
session when it sees one, and the run reads it when the session has ended (`take_end`): a finish's summary goes to
the run log, an ask parks the task (`loop.park_asked`).

The git fence is a PreToolUse hook every slot gets through --settings (`fence_hook`): it denies `git push`,
`git reset --hard`, `git clean` and `git checkout -- .`, and an Edit or Write outside the slot's worktree.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shlex
import sys
from pathlib import Path

__all__ = ['cmd_finish', 'cmd_ask', 'end_mark', 'take_end', 'ended', 'fence', 'fence_hook']


def end_mark(slot: str | int | None = None, c=None) -> Path | None:
    """The slot's end mark (`AGENT_RUNNER_SLOT` when no slot is given), or None outside a slot. `c` is the run's
    config (the run passes its own); left out, the one of the folder this runs in, a slot's worktree."""
    from agent_runner.config import cfg
    slot = slot if slot is not None else os.environ.get('AGENT_RUNNER_SLOT')
    return (c or cfg()).notes(f'slot{slot}.end') if slot not in (None, '') else None


def ended(slot: str | int | None = None, c=None) -> bool:
    """This slot's agent ran `finish` or `ask`: its session is to end at once."""
    try:
        return bool((m := end_mark(slot, c)) and m.exists())
    except SystemExit:  # no repository (a hook in an odd place): nothing to end
        return False


def take_end(slot: int, c=None) -> dict:
    """The slot's end mark, read and removed: {} when there is none (or it cannot be read)."""
    m = end_mark(slot, c)
    if not m or not m.exists():
        return {}
    try:
        d = json.loads(m.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        d = {}
    m.unlink(missing_ok=True)
    return d if isinstance(d, dict) else {}


def task_here(cwd: Path | str | None = None) -> str:
    """The task this worktree is on, from its branch task/<ID>; '' on any other branch."""
    from agent_runner.gitops import git
    b = git('branch', '--show-current', cwd=Path(cwd or os.getcwd())).stdout.strip()
    return b.removeprefix('task/') if b.startswith('task/') else ''


def _write_end(how: str, tid: str, text: str) -> Path | None:
    m = end_mark()
    if m is None:
        return None
    m.parent.mkdir(parents=True, exist_ok=True)
    m.write_text(json.dumps({'how': how, 'tid': tid, 'text': text,
                             'at': dt.datetime.now().isoformat(timespec='seconds')}), encoding='utf-8')
    return m


def cmd_finish(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog='run finish', description='End this session now: the task is done (run it '
                                 'after `done`, or `done --blocked`). The summary goes to the run log.')
    ap.add_argument('summary', help='one line: what the session did')
    a = ap.parse_args(argv)
    if not os.environ.get('AGENT_RUNNER_SLOT'):
        print('run finish: not in a runner slot, so there is no session to end. Summary noted here only:\n'
              f'  {a.summary}')
        return 0
    from agent_runner.config import finished_mark
    from agent_runner.gitops import git
    done = (m := finished_mark()) and m.exists()  # this slot's `done` succeeded
    if not done and git('status', '--porcelain', cwd=Path.cwd()).stdout.strip():
        print('run finish: `done` has not run, and this worktree has uncommitted changes: they would be left '
              'behind. Run `done <ID> "<msg>"` (or `--blocked "<why>"`) first, then finish.', file=sys.stderr)
        return 1
    _write_end('finish', task_here(), a.summary)
    print('finished: this session ends when you stop now. Say nothing more.')
    return 0


def cmd_ask(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog='run ask', description='Ask the person a question only they can answer: the '
                                 'task is parked under Needs you, and their answer resumes this session.')
    ap.add_argument('question', help='the question, in plain words, with what you recommend')
    a = ap.parse_args(argv)
    q = ' '.join(a.question.split())
    if not q:
        print('run ask: the question is empty', file=sys.stderr)
        return 2
    if not os.environ.get('AGENT_RUNNER_SLOT'):
        print('run ask: not in a runner slot. Ask the person directly, or block the task with '
              '`done <ID> "<msg>" --blocked "DECIDE: <question>"`.', file=sys.stderr)
        return 2
    if not (tid := task_here()):
        print('run ask: this worktree is not on a task/<ID> branch, so there is no task to park', file=sys.stderr)
        return 2
    _write_end('ask', tid, q)
    print(f'asked: {q}\nStop now. The session ends, {tid} is parked under Needs you with your worktree as it is, and '
          'the person\'s answer comes back as the next message of this session.')
    return 0


# --- the git fence ---------------------------------------------------------------

EDIT_TOOLS = {'Edit': 'file_path', 'Write': 'file_path', 'MultiEdit': 'file_path', 'NotebookEdit': 'notebook_path'}
FENCE_TOOLS = 'Bash|' + '|'.join(EDIT_TOOLS)  # the hook's matcher
SEPARATORS = {';', '&&', '||', '|', '&', '(', ')', ';;', '|&'}
GIT_ARG_OPTS = {'-C', '-c', '--git-dir', '--work-tree', '--namespace', '--exec-path', '--config-env'}


def _within(p: Path, root: Path | None) -> bool:
    if root is None:
        return False
    try:
        p.relative_to(root)
        return True
    except ValueError:
        return False


def _real(p: str | Path, cwd: Path) -> Path:
    p = Path(os.path.expanduser(str(p)))
    return Path(os.path.realpath(p if p.is_absolute() else cwd / p))


def _tokens(cmd: str) -> list[str]:
    try:
        lex = shlex.shlex(cmd, posix=True, punctuation_chars=';&|()')
        lex.whitespace_split = True
        return list(lex)
    except ValueError:  # an open quote: read it word by word all the same
        return cmd.split()


def _git_calls(cmd: str, cwd: Path):
    """(directory, subcommand, its arguments) for each `git` call in a shell command: `cd DIR` and `git -C DIR`
    move the directory. Quoted text is one word, so a commit message that says "git push" is not a call."""
    toks, here = _tokens(cmd), cwd
    i = 0
    while i < len(toks):
        t = toks[i]
        if t == 'cd' and i + 1 < len(toks) and toks[i + 1] not in SEPARATORS:
            here = _real(toks[i + 1], here)
            i += 2
            continue
        if t == 'git' or t.endswith('/git'):
            where, j = here, i + 1
            while j < len(toks) and toks[j].startswith('-'):
                opt = toks[j]
                if opt in GIT_ARG_OPTS and j + 1 < len(toks):
                    if opt == '-C':
                        where = _real(toks[j + 1], where)
                    j += 2
                    continue
                j += 1
            k = j + 1
            while k < len(toks) and toks[k] not in SEPARATORS:
                k += 1
            if j < len(toks) and toks[j] not in SEPARATORS:
                yield where, toks[j], toks[j + 1:k]
            i = k
            continue
        i += 1


def fence(tool: str, tool_input: dict, cwd: str | Path, worktree: str | Path | None, root: str | Path,
          slots_dir: str | Path, notes: str | Path, push: bool) -> str | None:
    """Why the git fence denies this tool call, or None to let it run.

    Denied: `git push` in this project (its main checkout or any slot; elsewhere too while `[git] push` is off),
    `git reset --hard`, `git clean` (but `-n`), `git checkout -- .`/`git checkout .`; an Edit or Write in another
    slot or in the main checkout (but its notes folder, where wizards and pick sheets go). An edit outside the
    project (a sibling repository the task needs, the scratchpad) is let through: the brief allows that work."""
    cwd = _real(cwd or '.', Path('/'))
    root, slots, notes_dir = _real(root, cwd), _real(slots_dir, cwd), _real(notes, cwd)
    own = _real(worktree, cwd) if worktree else None
    if own is None and _within(cwd, slots):  # a merge-worktree session: the folder of slots_dir it is in
        own = slots / cwd.relative_to(slots).parts[0] if cwd != slots else None
    if tool in EDIT_TOOLS:
        p = (tool_input or {}).get(EDIT_TOOLS[tool])
        if not p:
            return None
        f = _real(p, cwd)
        if _within(f, own):
            return None
        if _within(f, slots) or (_within(f, root) and not _within(f, notes_dir)):
            return (f'the git fence: {f} is outside your worktree ({own or "none"}). Change files only in your '
                    f'worktree; the main checkout and the other slots belong to other work.')
        return None
    if tool != 'Bash':
        return None
    for where, sub, args in _git_calls((tool_input or {}).get('command', ''), cwd):
        if sub == 'push' and (not push or any(_within(where, r) for r in (own, root, slots))):
            return ('the git fence: no `git push` here. `run done` pushes your task branch; the runner pushes '
                    'the merge.')
        if sub == 'reset' and '--hard' in args:
            return 'the git fence: no `git reset --hard`: it destroys work. Commit, or make a new commit that undoes it.'
        if sub == 'clean' and not any(a in ('-n', '--dry-run') or re.match(r'-[a-zA-Z]*n', a) for a in args):
            return 'the git fence: no `git clean`: it deletes files for good. Delete only paths you name in full.'
        if sub == 'checkout' and '.' in args:
            return 'the git fence: no `git checkout -- .`: it throws away every uncommitted change.'
    return None


def fence_hook(argv: list[str]) -> int:
    """The PreToolUse hook: `fence ROOT SLOTS_DIR NOTES PUSH` (PUSH 1 or 0), the tool call as JSON on stdin; prints
    Claude Code's deny decision when `fence` refuses the call. Always exits 0: a broken hook must not stop work."""
    if len(argv) != 4 or not os.environ.get('AGENT_RUNNER'):
        return 0
    try:
        ev = json.load(sys.stdin)
        why = fence(ev.get('tool_name', ''), ev.get('tool_input') or {}, ev.get('cwd') or os.getcwd(),
                    os.environ.get('AGENT_RUNNER_WORKTREE'), argv[0], argv[1], argv[2], argv[3] == '1')
    except Exception:
        return 0
    if why:
        print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
                                                 'permissionDecisionReason': why}}))
    return 0
