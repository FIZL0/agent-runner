"""F406f: a control session on the harness loop, for `[models] control` of another provider ('<provider>:<model>').

`control N` then starts `harness.mjs --chat` instead of Claude Code: many turns, waiting for the person between them,
the control brief (`guide.harness_fit`: without Remote Control, push and Artifact) as its system text, its transcript
where the harness loop keeps them, so the readers of a control chat's transcript find it by its session id.

Its git fence (`fence`) is asked before every tool call, through `run fence … control` (tools.fence_hook).

Not one of the FAMILY modules `share` reaches, so the run's settings are read through their modules at call time."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess as sp
import sys
from pathlib import Path

from agent_runner import state


def harness_control() -> bool:
    """`[models] control` is another provider's, so a control session that starts now runs on the harness loop."""
    from agent_runner import control as K, slots
    return slots.on_harness(K.control_model())


def ready(n: int) -> bool:
    """Control session `n` can start: Claude Code is told to trust the main checkout, the harness loop has Node."""
    from agent_runner import control as K, slots
    if not harness_control():
        slots.backend().trust(state.ROOT)
    elif not shutil.which('node'):
        print(f'control {n}: Node.js is not on PATH; a control session on {K.control_model()} needs it', file=sys.stderr)
        return False
    return True


def remote_off_line(why) -> str:
    """The run log's line on why Remote Control is off ('' when `[run] remote = false` asked for that)."""
    v = state.C.run['remote']
    if v and harness_control():
        return "remote control off: [models] control is another provider's"
    return f'remote control off: {why()}; [run] remote = true forces it' if v == 'auto' else ''


def rename(n: int, name: str, typed) -> bool:
    """`typed(n, '/rename …')`, or for a chat on the harness loop, which takes no /rename, False: it has its name in state."""
    return not harness_chat(n) and typed(n, f'/rename {name}')


def resume_into(a) -> bool:
    """`control --resume SID`: its arguments `a`, made `control N --reopen`; False when it cannot go on."""
    a.n, a.reopen = resume_number(a.resume), True
    return bool(a.n)


def harness_session(sid: str) -> bool:
    """Session `sid` ran on the harness loop."""
    from agent_runner import slots
    return bool(sid and slots.HARNESS.find_transcript(sid))


def harness_chat(n: int) -> bool:
    """Control session `n` runs on the harness loop: it takes no slash command (/rename)."""
    from agent_runner import control as K
    return harness_session(K.control_kept_sid(n))


def in_harness_chat() -> bool:
    """This process runs in the tools of a control session on the harness loop."""
    from agent_runner import control as K
    n = os.environ.get(K.CONTROL_N_ENV, '')
    if os.environ.get('AGENT_RUNNER') or os.environ.get('AGENT_RUNNER_SLOT'):  # a slot of a run a control session started
        return False
    try:
        state.C or state.init()
        return n.isdigit() and harness_chat(int(n))
    except (OSError, SystemExit):
        return False


def other_kind(sid: str) -> bool:
    """Session `sid` ran on the other kind of agent (the harness loop, Claude Code) than a control session does now."""
    return harness_control() != harness_session(sid)


def resumable(sid: str) -> bool:
    """Session `sid` has a transcript that a control session starting now can go on from: Claude Code and the harness
    loop cannot read each other's."""
    from agent_runner import slots
    b = slots.HARNESS if harness_control() else slots.backend()
    return bool(sid and b.find_transcript(sid))


def resume_hint(sid: str) -> str:
    """The command that goes on with session `sid`, for the run log."""
    from agent_runner import plat
    from agent_runner.config import shown_cmd
    if harness_session(sid):
        return f'{shown_cmd()} control --resume {sid}'
    return f'{plat.exe(state.C.run["agent"])} --resume {sid}'


def argv(n: int, sid: str, resume: bool, ask: str = '') -> list[str]:
    """Control session `n` as the harness loop in chat mode; `ask` is its first message."""
    from agent_runner import control as K, slots
    C, H, model = state.C, slots.HARNESS, K.control_model()
    C.notes(f'{sid}.brief').write_text(K.control_brief(harness=True), encoding='utf-8')  # every start: --system-file
    pf = C.notes(f'control{n}.prompt')
    pf.write_text(ask, encoding='utf-8')
    if not resume:  # there from the start, empty, so what reads a control session's transcript finds it
        (C.notes('harness-sessions') / f'{sid}.jsonl').parent.mkdir(parents=True, exist_ok=True)
        (C.notes('harness-sessions') / f'{sid}.jsonl').touch()
    flags = [f for f in H.flags(sid, model, 0, resume, True) if f != '--once']  # once: no task's budgets
    at = flags.index('--fence-cmd') + 1
    flags[at] = json.dumps([*json.loads(flags[at]), 'control'])
    if C.fallback:
        from agent_runner.fallback import harness_chain
        if chain := harness_chain(model):
            flags += ['--fallback', json.dumps([{'model': m, 'provider': C.providers.get(m.partition(':')[0])} for m in chain])]
    return H.argv('', pf, sid, ['--chat', *flags])


def resume_number(sid: str) -> int:
    """`control --resume SID`: the number its conversation goes on under, made ready for `--reopen`; 0 (and why, on
    stderr) when it cannot go on."""
    from agent_runner import control as K, control_held
    if n := control_held.live_number(sid):
        print(f'control {n} is that session, and it is up', file=sys.stderr)
        return 0
    if not resumable(sid):
        print(f'no session {sid} that [models] control = {K.control_model()!r} can go on with', file=sys.stderr)
        return 0
    n = K.free_control_number()
    control_held.look(n)
    state.C.notes(f'control{n}.pid').unlink(missing_ok=True)
    state.C.notes(f'control{n}.name').unlink(missing_ok=True)
    K.control_give(n, K.control_base_name(n))
    K.control_keep_sid(n, sid)
    return n


# --- its git fence -----------------------------------------------------------------------------------------------

LANDS = {'commit', 'merge', 'pull', 'rebase', 'cherry-pick', 'revert', 'am'}  # git commands that make a commit here


def _git(where: Path, *args: str) -> str:
    try:
        r = sp.run(['git', '-C', str(where), *args], capture_output=True, text=True, timeout=20)
    except (OSError, sp.SubprocessError):
        return ''
    return r.stdout.strip() if r.returncode == 0 else ''


def _common(where: Path) -> str:
    d = _git(where, 'rev-parse', '--git-common-dir')
    return os.path.realpath(where / d) if d else ''


def git_calls(cmd: str, cwd: Path):
    """`tools._git_calls` of a command and of the ones it hands a shell (`bash -c "…"`, `eval "…"`); one whose folder
    cannot be told (not there, or a `cd` in a subshell) is judged where the session is too."""
    from agent_runner import tools as T
    for where, sub, args in T._git_calls(cmd, cwd):
        if where.is_dir():
            yield where, sub, args
        if where != cwd and (not where.is_dir() or '(' in cmd):
            yield cwd, sub, args
    toks = T._tokens(cmd)
    for i, t in enumerate(toks):
        if t.rpartition('/')[2] in ('bash', 'sh', 'zsh', 'dash', 'eval'):
            for inner in toks[i + 1:]:
                if inner in T.SEPARATORS:
                    break
                if ' ' in inner:
                    yield from git_calls(inner, cwd)


def fence(tool: str, tool_input: dict, cwd: str | Path, root: str | Path, slots_dir: str | Path, notes: str | Path,
          push: bool) -> str | None:
    """Why the git fence denies this tool call of a control session, or None to let it run: no push in this project,
    no commit or merge in the main checkout, none of the commands that destroy work (`tools.fence`); no edit of the
    main checkout's files (but its notes, and files git ignores: runner.local.toml) or of a run's worktree. One made by `take` is
    the session's to work in."""
    from agent_runner import tools as T
    cwd = T._real(cwd or '.', Path('/'))
    root, slots, notes_dir = T._real(root, cwd), T._real(slots_dir, cwd), T._real(notes, cwd)
    if tool in T.EDIT_TOOLS:
        p = (tool_input or {}).get(T.EDIT_TOOLS[tool])
        if not p:
            return None
        f = T._real(p, cwd)
        if T._within(f, notes_dir):
            return None
        if T._within(f, slots) and f != slots:
            if f.relative_to(slots).parts[0].startswith('take-'):
                return None
            return f'the git fence: {f} is in a worktree of the run\'s. Tell its task (`plan tell ID`) instead.'
        if T._within(f, root):
            top = _git(next((d for d in f.parents if d.is_dir()), root), 'rev-parse', '--show-toplevel')
            if top and os.path.realpath(top) != str(root):  # a worktree inside the checkout
                return None
            if not _git(root, 'check-ignore', str(f)):
                return (f'the git fence: {f} is in the main checkout, where an edit holds every merge. Change the plan '
                        'with `plan`, and code in the worktree `take` makes.')
        return None
    if tool != 'Bash':
        return None
    for where, sub, args in git_calls((tool_input or {}).get('command', ''), cwd):
        top = _git(where, 'rev-parse', '--show-toplevel')
        if sub in LANDS and top and os.path.realpath(top) == str(root):
            return (f'the git fence: no `git {sub}` in the main checkout: work lands only through a task\'s branch, '
                    'which the runner tests and merges.')
        if sub == 'push' and (c := _common(where)) and c == _common(root):
            where = root  # a worktree of this project, wherever it is
        why = T.fence('Bash', {'command': shlex.join(['git', sub, *args])}, where, None, root,
                      slots, notes, push)
        if why:
            return why.replace('`run done` pushes your task branch; the runner pushes the merge.',
                               'Work lands only through a task\'s branch (`take`), which the runner pushes.')
    return None
