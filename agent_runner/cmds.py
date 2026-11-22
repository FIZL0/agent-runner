"""The other `agent-runner` commands: take, resume, key, upgrade, status, since, needs, wizard, sheet, stop,
control, and the run in the background (`attach`)."""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import os
import re
import shutil
import subprocess as sp
import sys
import time
from contextlib import redirect_stdout
from pathlib import Path

from agent_runner import plan as P, plansync, plat
from agent_runner.config import RUNNER, runner_cmd, shown_cmd
from agent_runner.state import (ask_stop, C, clear_stop, default_branch, edited, git, init, queued, REPO_TAG, ROOT,
    RUN_TAG, run_up, SLOTS_DIR, TAG)
from agent_runner.brief import has_sheet, prompt_for, wizard_cmd, wizard_file
from agent_runner.sched import ahead, open_tasks
from agent_runner.slots import (attach_target, backend, background_env, background_session, claude_json, entries,
    marker_pid, MUX, PRESENCE_ENV, quiet_file, remote_off_why, remote_on, remote_slots_on, REMOTE_URL, silent, tmux,
    transcript, window, worktree)
from agent_runner.watch import breaking, installed_version, last_session, queue_resume, upgrade, upgrade_argv
from agent_runner.land import wip_main_info
from agent_runner.control import (control_argv, control_brief, control_env, control_give, control_hook_input,
    control_link, control_live, control_mark_ask, CONTROL_N_ENV, control_name, control_ok, control_open, control_session_start,
    control_set_title, control_sid, free_control_number, RUNNER_STARTED_ENV)
from agent_runner.status import (follow, move_since_mark, progress_line, release_line, since_mark_file, since_start,
    since_text, status_text, waiting_ok)
from agent_runner.status import as_event, events_file, read_events
from agent_runner.state import EV_RUN_UP
from agent_runner.feed import (board, board_feed, board_held, control_late_files, control_new, control_new_runner,
    FORWARD_FLAG, forward_late_files, read_ask_file, SID_RE)
from agent_runner.loop import drop_session_env, finish, send_key, session_env_masks


TAKEN = """

You were handed this task by `{runner} take {tid}`, outside the runner's slots: you are in its worktree {d}. \
After `{runner} done {tid} ...` has committed, run `{runner} take {tid} --merge`: the runner tests and merges \
task/{tid} (or the run that is up does it within a minute). Never merge it yourself."""


def stash_ref(sha: str) -> str:
    """stash@{n} of the stash entry `sha`: `stash pop`/`drop` take no bare commit, and a run may stash meanwhile."""
    shas = git('stash', 'list', '--format=%H').stdout.split()
    return f'stash@{{{shas.index(sha)}}}' if sha in shas else sha


def running_slot(tid: str) -> int:
    """F52: the slot whose worktree is on task/<tid>, or that queued its resume; 0 for none."""
    path = ''
    for l in git('worktree', 'list', '--porcelain').stdout.splitlines():
        if l.startswith('worktree '):
            path = l.removeprefix('worktree ')
        elif l == f'branch refs/heads/task/{tid}' and re.fullmatch(r's\d+', Path(path).name) \
                and Path(path).parent.resolve() == SLOTS_DIR.resolve():
            return int(Path(path).name[1:])
    return next((n for n, q in queued().items() if q[0] == tid), 0)


def slot_link(n: int, tid: str = '') -> str:
    """F52: slot `n`'s claude.ai/code link: its pane's pid -> session id -> the transcript's bridge-session
    entry; '' when `[run] remote_slots` is off or any step is missing."""
    if not remote_slots_on():
        return ''
    try:
        # a resume queued for this task names its session; the pane then may run another task's
        sid = next((q[1] for m, q in queued().items() if m == n and (not tid or q[0] == tid)), None)
        if not sid and (pane := MUX.panes().get(f's{n}')) and plat.alive(pane[1]):
            sid = MUX.session_id(pane[1])
    except Exception:  # a multiplexer that is not there: no link, the rest of the message stands
        return ''
    if not sid:
        return ''
    bridge = ''
    for d in entries(sid, skip_bad=True):
        if isinstance(d, dict) and d.get('type') == 'bridge-session' and isinstance(d.get('bridgeSessionId'), str):
            bridge = d['bridgeSessionId']
    return control_link(bridge)


def slot_running(tid: str) -> str:
    """F52: why `take tid` refuses a task a slot runs, with where to watch and steer it instead."""
    n = running_slot(tid)
    if not n:
        return 'running in a slot'
    link = slot_link(n, tid)
    return (f'running in slot s{n}; nothing taken. Watch or steer it there instead:\n'
            + (f'  {link}\n' if link else '')
            + f'  {C.command} attach s{n}\n'
            + f'  {C.command} plan tell {tid} "what to do differently"')


def cmd_take(argv: list[str], prog: str = f'{RUNNER} take') -> int:
    """`take ID`: a worktree on task/<ID> for a person's own session or subagent, beside a run or without one.
    `take "TEXT" --kind K` queues the task first; `--here` carries the main checkout's uncommitted edits along."""
    ap = argparse.ArgumentParser(prog=prog, description='Do one chosen task in your own session (or a subagent) '
                                 'in a worktree of its own; a run that is up leaves the task and its files alone.')
    ap.add_argument('id', metavar='ID|TEXT', help="an open task's id; with --kind, the text of a new task")
    ap.add_argument('--kind', metavar='K', help='queue TEXT as a new task of this kind (`plan kinds`), then take it')
    ap.add_argument('--files', metavar='A,B', help='with --kind: the files it changes, as for `plan add`')
    ap.add_argument('--here', action='store_true', help="move the main checkout's uncommitted edits into the "
                    'new worktree, leaving the main checkout clean')
    what = ap.add_mutually_exclusive_group()
    what.add_argument('--merge', action='store_true', help='after `done`: remove the worktree and merge task/<ID>')
    what.add_argument('--drop', action='store_true', help='give the task back: remove the worktree, keep no commits')
    a = ap.parse_args(argv)
    if (a.merge or a.drop) and (a.kind or a.files or a.here):
        ap.error('--merge and --drop take only an ID')
    init()
    tid, branch = a.id, default_branch()
    d = SLOTS_DIR / f'take-{tid}'
    if a.merge or a.drop:
        if not d.is_dir():
            print(f'{tid}: not taken (no {d})', file=sys.stderr)
            return 1
        if git('status', '--porcelain', cwd=d).stdout.strip():
            print(f'{tid}: {d} has uncommitted edits: `{C.command} done {tid} "..."` there first'
                  + (', or commit or delete them' if a.drop else ''), file=sys.stderr)
            return 1
        ahead_ = git('rev-list', '--count', f'{branch}..task/{tid}').stdout.strip() not in ('', '0')
        if a.drop and ahead_:
            print(f'{tid}: task/{tid} has commits; --merge them, or delete the branch yourself first', file=sys.stderr)
            return 1
        git('worktree', 'remove', str(d))
        if not ahead_:
            git('branch', '-D', f'task/{tid}')
            print(f'{tid}: given back; the run may start it' if a.drop else f'{tid}: no commits, nothing to merge')
            return 0
        if not plat.lock(C.notes('run.lock')):
            print(f'{tid}: the run that is up merges task/{tid} within a minute (see {C.notes("run.log")})')
            return 0
        finish(tid, 0, '', branch)  # no run is up: this process holds run.lock and merges it now
        merged = git('rev-parse', '--verify', '-q', f'refs/heads/task/{tid}').returncode != 0
        print(f'{tid}: merged into {branch}' if merged and tid not in open_tasks(branch) else
              f'{tid}: not merged; {C.notes("run.log")} says why')
        return 0
    stash = ''
    if a.here and edited():  # stashed first, so the plan edit `--kind` commits never meets them
        if git('stash', 'push', '-u', '-q', '-m', 'agent-runner take --here').returncode:
            print('could not stash the main checkout\'s edits; nothing taken', file=sys.stderr)
            return 1
        stash = git('rev-parse', 'stash@{0}').stdout.strip()

    def fail(msg: str) -> int:
        print(msg, file=sys.stderr)
        if stash and git('stash', 'pop', '-q', stash_ref(stash)).returncode:
            print(f'your edits are in the stash ({stash}): `git stash pop` to get them back', file=sys.stderr)
        return 1

    if a.kind:
        out = io.StringIO()
        with redirect_stdout(out):
            rc = P.main(['add', a.kind, tid] + (['--files', a.files] if a.files else []))
        if rc or not (m := re.match(r'added (\S+)', out.getvalue())):
            return fail(out.getvalue().strip() or 'not queued')
        tid = m[1]
        print(f'queued {tid}', file=sys.stderr)
        d = SLOTS_DIR / f'take-{tid}'
        # ponytail: a run polling in the moment between this commit and the worktree below could start tid too
    if tid not in open_tasks(branch):
        return fail(f'{tid}: not an open task on {branch}' + ('' if a.kind else ' (new work: `--kind K "TEXT"`)'))
    held = {l.removeprefix('branch refs/heads/') for l in
            git('worktree', 'list', '--porcelain').stdout.splitlines() if l.startswith('branch ')}
    why = ('taken already, in ' + str(d) if d.is_dir() else
           'running in a slot' if f'task/{tid}' in held or tid in {q[0] for q in queued().values()} else
           'finished, waiting to merge' if tid in ahead(branch) else
           f'claimed by {plansync.claims(C)[tid].who}' if tid in plansync.taken(C) else '')
    if why == 'running in a slot':
        why = slot_running(tid)
    if why:
        return fail(f'{tid}: {why}')
    worktree(f'take-{tid}', branch)
    if (co := git('checkout', '-q', '-B', f'task/{tid}', branch, cwd=d)).returncode:
        return fail(f'{tid}: checkout failed: {co.stderr.strip()}')
    if stash:
        if git('stash', 'apply', '-q', '--index', stash, cwd=d).returncode and \
                git('stash', 'apply', '-q', stash, cwd=d).returncode:
            print(f'{tid}: your edits did not apply cleanly in {d}; they are kept in the stash ({stash})',
                  file=sys.stderr)
        else:
            git('stash', 'drop', '-q', stash_ref(stash))
            print(f'{tid}: moved your uncommitted edits from {ROOT} into {d}', file=sys.stderr)
    print(f'{tid} is yours, in {d} (branch task/{tid}); a run leaves it and its files alone.\n'
          f'Give the agent that does it this prompt, with {d} as its working directory:\n')
    print(prompt_for(tid, 0, 2, d, branch) + TAKEN.format(runner=C.command, tid=tid, d=d))
    return 0


def cmd_resume(argv: list[str], prog: str = f'{RUNNER} resume') -> int:
    """`./run resume <ID>…`: continue a task's last session in its own slot, though the run already ended it."""
    ap = argparse.ArgumentParser(prog=prog, description=
        'Continue the last session of each task in the slot it ran in, with its whole conversation: for a '
        'session cut off before the run could resume it by itself (past its resume limit). '
        'The run resumes it once that slot is free; a slot that moved on gets the task back from the wip/<ID> '
        'the runner saved, its edits uncommitted again.')
    ap.add_argument('ids', nargs='+', metavar='ID')
    a = ap.parse_args(argv)
    init()
    branch = default_branch()
    open_ids = open_tasks(branch)
    bad = 0
    for tid in a.ids:
        if tid not in open_ids:
            print(f'{tid}: not an open task on {branch}', file=sys.stderr)
        elif not (last := last_session(tid)):
            print(f'{tid}: no session of it in the slot logs', file=sys.stderr)
        elif not transcript(last[1]):
            print(f'{tid}: the transcript of its session {last[1]} is gone', file=sys.stderr)
        else:
            queue_resume(tid, last[0], last[1], 'resumed by hand')
            print(f'{tid}: session {last[1]} resumes in slot {last[0]} once that slot is free')
            continue
        bad += 1
    if not bad and plat.lock(C.notes('run.lock')):
        print(f'no run is up: it resumes when `{C.command} run` starts')
    return 1 if bad else 0


def cmd_key(argv: list[str], prog: str = f'{RUNNER} key') -> int:
    """`pause`, `force`, `slots` and `key`: the runner pane's keys from any terminal, or from a remote session.
    Unlike a typed key, `pause` and `force` say which way (on, or off with --off), so saying it twice is safe."""
    cmd = prog.split()[-1]
    ap = argparse.ArgumentParser(prog=prog, description={
        'pause': 'Start no new tasks; the run stays up (--off: start them again).',
        'force': 'Start tasks past the session and weekly usage caps (--off: the caps hold again).',
        'slots': 'Change the running slot count: N, +N or -N (a slot past the count finishes its task first).',
        'key': 'Send keys to the run as if typed in its pane (? lists them).'}[cmd])
    if cmd == 'slots':
        ap.add_argument('count', help='N, +N or -N')
    elif cmd == 'key':
        ap.add_argument('keys', nargs='+')
    else:
        ap.add_argument('--off', action='store_true')
    a = ap.parse_args(argv)
    init()
    if not run_up():
        print(f'no run is up in this repository: `{C.command} run` starts one', file=sys.stderr)
        return 1
    keys = {'slots': lambda: [f'slots {a.count}'], 'key': lambda: a.keys}.get(
        cmd, lambda: [f'{cmd[0]} {"off" if a.off else "on"}'])()
    send_key(*keys)
    print(f'sent to the run: {", ".join(keys)} (it acts within 10 s; `{C.command} status` shows it)')
    return 0


def cmd_upgrade(argv: list[str], prog: str = f'{RUNNER} upgrade') -> int:
    """B49 `agent-runner upgrade`: what `u` in the runner's pane does, from any terminal or a control session.
    It runs `upgrade` (pipx, uv tool, or a pull, per `upgrade_argv`) here; a run that is up sees the new version
    on disk and restarts on it by itself (`restart_if_upgraded`), as after `u`."""
    ap = argparse.ArgumentParser(prog=prog, description='Upgrade agent-runner (pipx, uv tool, or a git pull in '
                                 'its clone); a run that is up restarts on the new version by itself.')
    ap.parse_args(argv)
    init()
    if not upgrade():
        print(f'the upgrade failed: run `{" ".join(upgrade_argv())}` by hand to see why', file=sys.stderr)
        return 1
    from agent_runner import __version__
    new = installed_version()
    if new and new != __version__ and run_up():
        print('the run that is up restarts on it by itself' if not plat.WINDOWS and not breaking(__version__, new)
              else 'read CHANGELOG.md, then restart the run')
    return 0


def cmd_status(argv: list[str], prog: str = f'{RUNNER} status') -> int:
    """`agent-runner status`: is a run up, what its keys have set, each slot's task, and the log's end."""
    ap = argparse.ArgumentParser(prog=prog, description='What the run is doing.')
    ap.add_argument('-n', type=int, default=0, help='also the last N lines of run.log (default none)')
    ap.add_argument('--window', default='24h', metavar='W',
                    help='count merges over this window: 2h, 30m, 1d, today, yesterday, or a date/time (default 24h)')
    a = ap.parse_args(argv)
    init()
    up = run_up()
    try:
        st = json.loads(C.notes('STATE').read_text(encoding='utf-8')) if up else {}
    except (OSError, ValueError):
        st = {}
    try:
        lines = C.notes('run.log').read_text(encoding='utf-8', errors='replace').splitlines()
    except OSError:
        lines = []
    print(status_text(up, st, read_events(), P.titles(C.done, C.todo),time.time(), waiting=waiting_ok(), wips=wip_main_info(),
                      progress='\n'.join(x for x in (progress_line(a.window), release_line(P.lines(C.todo))) if x)))
    from agent_runner.web import page_line
    if said := page_line():  # F66: the run page's address, with its token
        print(said)
    if lines and a.n:
        print('\nrun.log:\n' + '\n'.join(f'  {l}' for l in lines[-a.n:]))
    return 0


def cmd_since(argv: list[str], prog: str = f'{RUNNER} since') -> int:
    """`agent-runner since [2h|yesterday|…] [--follow]`: what happened since the last look, one short line each."""
    ap = argparse.ArgumentParser(prog=prog, description='What happened since you last looked (or since WHEN): '
                                 'landed, started, stuck, needs you, run idle or stopped, oldest first.')
    ap.add_argument('when', nargs='?', help='2h, 30m, 1d, today, yesterday, or a date/time; default: the last `since`')
    ap.add_argument('--all', action='store_true',
                    help='every event, one line each, oldest first (default: a short digest, one line per task '
                         'with its last state)')
    ap.add_argument('--follow', '-f', action='store_true',
                    help='stay running and print one line per new event as it happens')
    ap.add_argument('--needs-you', action='store_true',
                    help='with --follow: only what needs you (the run held, a task left for you, stalled, or '
                         'waiting on your answer), and the last-look mark stays put')
    ap.add_argument('--keep-mark', action='store_true',
                    help='with --follow: leave the last-look mark where it is, and print nothing while the run '
                         'is idle, or paused or stopping with nothing running (the runner feed)')
    ap.add_argument('--board', action='store_true',
                    help="the board window's feed: a header, the last 6 hours, then --follow; the last-look mark "
                         "stays put, and no tokens are used")
    ap.add_argument('--feed', action='store_true',
                    help='with --board: run the runner feed (the Haiku session on Remote Control) instead, and end '
                         'it with --run-pid')
    ap.add_argument('--run-pid', type=int, default=0, metavar='PID',
                    help='with --board: the run that opened it; the board ends once that process has')
    a = ap.parse_args(argv)
    init()
    if a.needs_you and not a.follow:
        ap.error('--needs-you goes with --follow')
    if (a.feed or a.run_pid) and not a.board:
        ap.error('--feed and --run-pid go with --board')
    if a.board:
        return board_feed(a.run_pid) if a.feed else board(a.run_pid)
    if a.follow:
        return follow(needs_you=a.needs_you, mark=not a.keep_mark, hold=board_held if a.keep_mark else None)
    f = since_mark_file()
    try:
        mark = f.read_text(encoding='utf-8').strip() or None
    except OSError:
        mark = None
    now = dt.datetime.now().replace(microsecond=0)
    start = since_start(a.when, mark, now)
    text, last = since_text(read_events(), start, P.titles(C.done, C.todo), now, since_mark=not a.when and bool(mark),
                            waiting=waiting_ok(), wips=wip_main_info(), digest=not a.all)
    print(text)
    move_since_mark(last or now.isoformat())
    return 0


def cmd_needs(argv: list[str], prog: str = f'{RUNNER} needs') -> int:
    """F44 `agent-runner needs`: only what waits on the person, one 'ID - what to do' line each in Needs you
    order, then '2 things need you' or 'Nothing needs you'; no bodies, notes or lately, so a feed or control
    session spends almost no context on it."""
    argparse.ArgumentParser(prog=prog, description='What waits on you, one line each.').parse_args(argv)
    init()
    w = waiting_ok()
    stamps = {a[1]: a[7] for a in w if len(a) > 7 and a[7]}
    print('\n'.join(P.needs_lines(P.in_order(w, stamps, P.needs_cfg()['order']), has_sheet)))
    return 0


def waiting_wizards() -> list[tuple[str, str]]:
    """F48: (id, title) of each item under Needs you (not the shelved ones) that has a wizard, in TODO order."""
    out = []
    for label, tid, _k, _what, _url, title, sh, *_ in waiting_ok():
        if label != 'CONCEPT' and not sh and wizard_file(tid) and tid not in [t for t, _ in out]:
            out.append((tid, title))
    return out


def bash_exe() -> str:
    """B75: the bash to run wizards with. A bare 'bash' on Windows makes CreateProcess search System32 before PATH
    and get the WSL launcher (C:\\Windows\\System32\\bash.exe), not Git Bash; resolve it on PATH instead, and
    there skip a System32 bash when another is on PATH."""
    found = shutil.which('bash')
    if os.name == 'nt':
        sysdir = os.path.normcase(os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'System32'))
        for d in os.environ.get('PATH', '').split(os.pathsep):
            exe = shutil.which('bash', path=d) if d else None
            if exe and os.path.normcase(os.path.dirname(os.path.abspath(exe))) != sysdir:
                return exe
    return found or 'bash'


def cmd_wizard(argv: list[str], prog: str = f'{RUNNER} wizard') -> int:
    """`agent-runner wizard [ID]`: run the wizard an agent left for a BLOCKED item, then confirm the item."""
    ap = argparse.ArgumentParser(prog=prog, description='Walk through the hand steps a blocked task needs '
                                 '(a login, a cert, a secret), then confirm it.')
    ap.add_argument('id', nargs='?', help='the task id, as Needs you shows it (none: the one that waits)')
    ap.add_argument('--check', action='store_true', help='only check the script (bash -n), run nothing')
    ap.add_argument('--path', action='store_true', help='print where the script is, run nothing')
    a = ap.parse_args(argv)
    init()
    if not a.id:  # F48: bare `wizard` runs the one waiting, or lists them to pick
        ids = waiting_wizards()
        if not ids:
            print('No wizard waits for you.')
            return 0
        if len(ids) > 1:
            print(f'{len(ids)} wizards wait for you:')
            for i, (tid, title) in enumerate(ids, 1):
                print(f'  {i}. {tid}  {title}')
            pick = ''
            if sys.stdin.isatty():
                try:
                    pick = input('Which one (number or id, Enter: none)? ').strip()
                except EOFError:
                    pick = ''
            chosen = [t for i, (t, _) in enumerate(ids, 1) if pick in (str(i), t)] if pick else []
            if not chosen:
                print(f'Run one with `{wizard_cmd("ID")}`.')
                return 0 if not pick else 2
            ids = [(chosen[0], '')]
        a.id = ids[0][0]
    f = C.notes('wizards', f'{a.id}.sh')
    if a.path:
        print(f)
        return 0
    if not f.is_file():
        print(f'{prog}: {a.id} has no wizard ({f})', file=sys.stderr)
        return 1
    bash = bash_exe()
    chk = sp.run([bash, '-n', str(f)], capture_output=True, text=True)
    if chk.returncode:
        print(f'{prog}: {f} does not parse, so it was not run:\n{chk.stderr.strip()}', file=sys.stderr)
        return 1
    if a.check:
        print(f'{f}: ok')
        return 0
    r = sp.run([bash, str(f)], cwd=str(C.root))
    if r.returncode:
        print(f'{prog}: the wizard stopped (exit {r.returncode}); {a.id} still needs you. '
              f'Run `{wizard_cmd(a.id)}` again to carry on.', file=sys.stderr)
        return r.returncode
    from agent_runner import plan
    return plan.main(['confirm', a.id, 'the wizard ran to the end'])


def cmd_sheet(argv: list[str], prog: str = f'{RUNNER} sheet') -> int:
    """`agent-runner sheet ID`: render a DECIDE's pick sheet, or answer the item with the picks sent from it."""
    from agent_runner import sheet
    ap = argparse.ArgumentParser(prog=prog, description='The pick sheet of a DECIDE: render its page, or answer it '
                                 'with the picks sent from the page (or the recommended ones).')
    ap.add_argument('id', help='the task id, as Needs you shows it')
    do = ap.add_mutually_exclusive_group()
    do.add_argument('--html', metavar='FILE', help='check the sheet and write its page to FILE, to publish')
    do.add_argument('--picks', metavar='REPLY', help="the line the sheet's Send gave ('ID picks: a=b …'), or 'go'")
    do.add_argument('--go', action='store_true', help='answer with the recommended picks')
    do.add_argument('--path', action='store_true', help='print where the sheet is')
    a = ap.parse_args(argv)
    init()
    f = C.notes('sheets', f'{a.id}.json')
    if a.path:
        print(f)
        return 0
    try:
        spec = sheet.load(f)
    except ValueError as e:
        print(f'{prog}: {e}', file=sys.stderr)
        return 1
    if a.html:
        Path(a.html).write_text(sheet.render(spec, a.id), encoding='utf-8')
        print(f'{a.html}: {len(sheet.questions(spec))} questions; publish it with the Artifact tool, with '
              f'capabilities {json.dumps(sheet.CAPABILITIES)} (F54: Send writes the picks to its db)')
        return 0
    if a.picks is None and not a.go:
        print(f'{f}: {len(sheet.questions(spec))} questions, ok')
        return 0
    try:
        picks = sheet.parse_picks(spec, 'go' if a.go else a.picks)
    except ValueError as e:
        print(f'{prog}: {e}', file=sys.stderr)
        return 2
    from agent_runner import plan
    return plan.main(['confirm', a.id, sheet.picks_note(spec, picks)])


def cmd_stop(argv: list[str], prog: str = f'{RUNNER} stop') -> int:
    """`./run stop`: the running sessions finish and merge, nothing new starts, and the run exits."""
    ap = argparse.ArgumentParser(prog=prog, description='Finish the running tasks, start nothing new, then exit.')
    ap.add_argument('--force', action='store_true',
                    help='end the agent sessions now (each resumes in the next run), as s! in the pane')
    power = ap.add_mutually_exclusive_group()
    power.add_argument('--suspend', action='store_true', help='then suspend the computer')
    power.add_argument('--shutdown', action='store_true', help='then shut the computer down')
    power.add_argument('--undo', action='store_true', help='take a gentle stop back: start tasks again')
    a = ap.parse_args(argv)
    init()
    if a.undo:
        if a.force:
            ap.error('--undo takes back a gentle stop; a stop now (--force) is under way already')
        send_key('s off') if run_up() else clear_stop()
        print('stop taken back')
        return 0
    if a.suspend or a.shutdown:
        P.post(C, 'POWER', 'suspend' if a.suspend else 'shutdown')  # the run's P.take keeps the last one
    ask_stop(f'{C.command} stop' + (' --force' if a.force else ''), force=a.force)
    print(f'asked the run to stop ({C.notes("STOP")}); it exits once '
          + ('its sessions are ended and the merges under way are done' if a.force else
             'the running tasks are merged')
          + (f', then {"suspends" if a.suspend else "shuts down"} the computer' if a.suspend or a.shutdown else ''))
    return 0


# --- the run in the background: bare `agent-runner`, and `attach` ----------------------------------------


def tmux_launch_argv(session: str, win: str, root: Path, cmd: str, env: list[str], exists: bool) -> list[str]:
    """The tmux command that starts `cmd` (`agent-runner run`) detached, in the window `win` of `session`: a new
    session, or a new window when the session is already there (the slots' window of a run that ended is
    still in it, and the new run adopts its panes). The window stays after its run exits until the launch
    has seen the run come up (remain-on-exit), so a run that fails at once leaves its message to show."""
    envs = [a for e in env for a in ('-e', e)]
    start = (['new-window', '-d', '-t', f'={session}:'] if exists else ['new-session', '-d', '-s', session])
    return ['tmux', *start, '-n', win, '-c', str(root), *envs, cmd,
            ';', 'set-option', '-w', '-t', f'={session}:{win}', 'remain-on-exit', 'on']


def background_argv() -> list[str]:
    """What bare `agent-runner` starts without tmux (Windows, or tmux not installed), as a detached process:
    the run, its slots hidden."""
    return [*runner_cmd(), 'run', '--hidden']


def remote_ready(tty: bool | None = None, ask=input) -> bool:
    """With `[run] remote`: will Claude Code start a slot without its one-time "Enable Remote Control? (y/n)"?
    In a hidden pane that question would hold every slot, so it is asked here, in this terminal, and the
    answer kept where Claude Code keeps it (`remoteDialogSeen` in ~/.claude.json). False: start nothing.
    Under `[run] remote = 'auto'` (and no remote_slots) it never stops a run: with no terminal to ask on, or
    answered no, the run starts with Remote Control off, and its log says why."""
    auto = C.run['remote'] == 'auto' and not remote_slots_on()
    if not (remote_slots_on() or (not remote_off_why(dialog=False) if auto else remote_on())):
        return True
    f = claude_json()
    try:
        data = json.loads(f.read_text(encoding='utf-8')) if f.exists() else {}
    except (OSError, ValueError):
        data = None
    if data is not None and data.get('remoteDialogSeen'):
        return True
    if auto and (not (sys.stdin.isatty() if tty is None else tty) or data is None):
        return True  # off for this run: remote_off_why says so in its log
    if not (sys.stdin.isatty() if tty is None else tty) or data is None:
        print(f'[run] remote is on, and Claude Code asks once, at a terminal, before Remote Control starts.\n'
              f'Run `claude remote-control` in a terminal and answer y (it does not ask again), then {shown_cmd()} again;\n'
              f'or set [run] remote = false (runner.local.toml for this machine). Nothing started.', file=sys.stderr)
        return False
    print('[run] remote is on: sessions start on Remote Control, which Claude Code asks about once.\n'
          'Answered here, the sessions in the background will not stop at the question.')
    try:
        yes = ask('Enable Remote Control? (y/n) ').strip().lower() in ('y', 'yes')
    except EOFError:
        yes = False
    if not yes and auto:
        print('Remote Control stays off for this run. [run] remote = false (runner.local.toml for this machine) '
              'stops this question.')
        return True
    if not yes:
        print(f'Nothing started: the slots would stop at that question. Set [run] remote = false to run '
              f'without Remote Control.', file=sys.stderr)
        return False
    data['remoteDialogSeen'] = True
    tmp = f.with_name(f'{f.name}.agent-runner.tmp')
    tmp.write_text(json.dumps(data, indent=2), encoding='utf-8')
    os.replace(tmp, f)
    return True


def wait_started(since: int, gone, timeout: float = 30.0) -> int | None:
    """Wait for the run's start event (F41: `run up` in events.jsonl) past byte `since`; its slot count, or
    None when `gone()` says the run ended first or `timeout` passed."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            with open(events_file(), 'rb') as f:
                f.seek(since)
                new = f.read().decode('utf-8', 'replace')
        except OSError:
            new = ''
        for l in new.splitlines():
            if (e := as_event(l)) and e['kind'] == EV_RUN_UP:
                return int(e.get('slots') or 0)
        if gone():
            return None
        time.sleep(0.3)
    return None


def started_note(slots: int, where: str, hidden: bool = False) -> str:
    attach = ("slot 2's console window: attach s2 (closing that window ends the session)" if plat.WINDOWS else
              "where each slot's log is (the slots run hidden)" if hidden else
              "its pane (attach s2: slot 2's); detach again with Ctrl-b d")
    lines = [f'the run is up in the background: {slots} slot{"s" if slots != 1 else ""}, {where}',
             f'    {shown_cmd()} status     what it is doing',
             f'    {shown_cmd()} attach     {attach}',
             f'    {shown_cmd()} stop       finish the running tasks, then end it (--force: now)']
    if C.run['control'] and control_ok():
        beside = 'c1 runs beside the run: attach c1' + (' (terminal only; the apps start control sessions from '
                                                        'the control server)' if remote_on() else '')
        lines.append(f'    {shown_cmd()} control    a control session in this terminal ({beside})')
    if remote_on():
        lines.append(f'    {REMOTE_URL}  the control sessions, from any device or the Claude apps')
    elif remote_slots_on():
        lines.append(f'    {REMOTE_URL}  the slots, from any device or the Claude apps')
    return '\n'.join(lines)


def cmd_background(argv: list[str]) -> int:
    """Bare `agent-runner`: start the run where no terminal shows it, and give the prompt back. With tmux: a
    detached tmux session "ar-<repo>" running `agent-runner run`, its slots' window in the same session.
    Windows, or no tmux (F40): the run as a detached process, its slots hidden."""
    drop_session_env()
    init()
    sess = background_session()
    if run_up():
        print(f'a run is already up in this repository: {shown_cmd()} status, {shown_cmd()} attach '
              f'(tmux attach -t {sess} when it was started in the background), {shown_cmd()} stop')
        return 0
    if not remote_ready():
        return 1
    log_file = C.notes('run.log')
    since = events_file().stat().st_size if events_file().exists() else 0
    if plat.WINDOWS or not shutil.which('tmux'):
        out = C.notes('background.out')
        proc = plat.spawn_detached(background_argv(), out=out)
        slots = wait_started(since, lambda: proc.poll() is not None)
        if slots is None:
            try:
                said = out.read_text(encoding='utf-8', errors='replace').strip()[-2000:]
            except OSError:
                said = ''
            print(f'the run did not come up' + (f':\n{said}' if said else f'; see {log_file}'), file=sys.stderr)
            return 1
        print(started_note(slots, 'its slots hidden' + ('' if plat.WINDOWS else ' (tmux is not installed)'), hidden=True))
        return 0
    win = window('runner')
    exists = not tmux('has-session', '-t', f'={sess}').returncode
    for c in session_env_masks(sess) if exists else ():  # an earlier launch from a Claude session left them
        tmux(*c)
    if exists:  # a dead runner window left from a failed start would take the name
        tmux('kill-window', '-t', f'={sess}:{win}')
    cmd = plat.command_text([*runner_cmd(), 'run'])
    r = sp.run(tmux_launch_argv(sess, win, ROOT, cmd, background_env(), exists), capture_output=True, text=True)
    if r.returncode:
        print(f'tmux could not start the run: {r.stderr.strip()}', file=sys.stderr)
        return 1
    for c in session_env_masks(sess) if not exists else ():  # a new session takes the server's global env
        tmux(*c)
    target = f'={sess}:{win}'

    def gone() -> bool:
        p = tmux('list-panes', '-t', target, '-F', '#{pane_dead}')
        return p.returncode != 0 or p.stdout.strip() == '1'

    slots = wait_started(since, gone)
    settle = time.monotonic() + 3  # a run that fails setting up its first slots does so right after its start line
    while slots is not None and time.monotonic() < settle:
        slots = None if gone() else slots
        time.sleep(0.3)
    if slots is None:
        said = '\n'.join([l for l in tmux('capture-pane', '-p', '-J', '-t', target).stdout.splitlines() if l.strip()][-25:])
        tmux('kill-window', '-t', target)
        print(f'the run did not come up' + (f':\n{said}' if said else f'; see {log_file}'), file=sys.stderr)
        return 1
    tmux('set-option', '-w', '-t', target, 'remain-on-exit', 'off')  # up: when it ends, its window goes with it
    print(started_note(slots, f'in tmux session {sess}'))
    return 0


def attach_argv(sess: str, pane_id: str, inside: bool) -> list[list[str]]:
    """The tmux commands that bring up `pane_id`: select its window and pane, then switch this client to its
    session (inside tmux) or attach this terminal to it."""
    return [['tmux', 'select-window', '-t', pane_id], ['tmux', 'select-pane', '-t', pane_id],
            ['tmux', 'switch-client' if inside else 'attach-session', '-t', sess]]


def cmd_background_attach(argv: list[str]) -> int:
    """`agent-runner --attach`: the background run (started now, or the one already up in this repo), then its
    pane in this terminal, as `attach` shows it; Ctrl-b d sends it back. Inside tmux it switches the client.
    Windows, or no tmux: the run has no pane to attach, so it is bare `agent-runner`, and says so."""
    if argv:
        print(f'{shown_cmd()} --attach takes nothing more (got {" ".join(argv)})', file=sys.stderr)
        return 2
    init()
    if plat.WINDOWS or not shutil.which('tmux'):
        print(f'{"on Windows" if plat.WINDOWS else "without tmux"} the run has no window to attach: '
              f'--attach starts it as {shown_cmd()} does')
        return cmd_background([])
    if not run_up():
        if r := cmd_background([]):
            return r
    return cmd_attach([])


def hidden_attach(which: str) -> str:
    """F40, POSIX: what `attach` says of a run or slot that has no tmux pane because it runs hidden: where its
    output is and how to watch it; '' when there is no such run or slot (the caller says so)."""
    if which == 'runner':
        return (f'the run has no pane (it runs without tmux): {shown_cmd()} status shows it, and its log is '
                f'{C.notes("run.log")}' if run_up() else '')
    pid = marker_pid(C.notes(f'slot{which[1:]}.live')) if re.fullmatch(r's\d+', which) else 0
    if not (pid and plat.alive(pid)):
        return ''
    remote = f'; on Remote Control ({REMOTE_URL})' if remote_slots_on() else ''
    return (f'{which} runs hidden (pid {pid}), with no pane to attach: its output goes to '
            f'{C.notes(f"slot{which[1:]}.log")}{remote}; {shown_cmd()} plan tell <ID> "<text>" types into it')


def cmd_attach(argv: list[str], prog: str = f'{RUNNER} attach') -> int:
    """`agent-runner attach [sN]`: the runner's pane, or a slot's; on Windows a slot's console window."""
    ap = argparse.ArgumentParser(prog=prog, description="Show the run's pane, or a slot's (s2, or 2).")
    ap.add_argument('slot', nargs='?', default='', help='s2 (or 2) for slot 2; master for a fix session; board for the board '
                    'window; none: the runner')
    a = ap.parse_args(argv)
    init()
    which = f's{a.slot}' if a.slot.isdigit() else (a.slot or 'runner')
    if plat.WINDOWS:
        if which == 'runner':
            print(f'on Windows the run has no window of its own: {shown_cmd()} status shows it, and its log is '
                  f'{C.notes("run.log")}. {shown_cmd()} attach s1 shows slot 1.')
            return 0
        pid = marker_pid(C.notes(f'slot{which[1:]}.live')) if re.fullmatch(r's\d+', which) else 0
        if not (pid and plat.alive(pid)):
            print(f'{which} is not running: {shown_cmd()} status lists the slots', file=sys.stderr)
            return 1
        if not plat.show_console(pid):
            print(f'{which} runs as pid {pid}, but its console window could not be shown', file=sys.stderr)
            return 1
        print(f'{which}: its console window is up (minimize it to hide it again; closing it ends the session)')
        return 0
    rows = tmux('list-panes', '-a', '-F', f'#{{session_name}}\t#{{pane_id}}\t#{{{TAG}}}\t#{{{REPO_TAG}}}\t#{{{RUN_TAG}}}') \
        if shutil.which('tmux') else None
    hit = attach_target(rows.stdout.splitlines(), ROOT, which) if rows and not rows.returncode else None
    if not hit and (said := hidden_attach(which)):
        print(said)
        return 0
    if not hit:
        print((f'no pane {which} in tmux for this repository' if which != 'runner' else
               'no run in tmux for this repository') + f': {shown_cmd()} status; {shown_cmd()} starts the run', file=sys.stderr)
        return 1
    *select, go = attach_argv(*hit, inside=bool(os.environ.get('TMUX')))
    for c in select:
        sp.run(c, capture_output=True)
    return sp.call(go)


def cmd_control(argv: list[str], prog: str = f'{RUNNER} control') -> int:
    """`agent-runner control [N]`: a control session in this terminal, in the main checkout. No N: c1 (the kept
    session, resumed) when it is not running, else the next free number."""
    drop_session_env()
    ap = argparse.ArgumentParser(prog=prog, description='A control session here: ask it for status, pause, '
                                 'slots, stop; it files asks with plan add and does do-it-now work with take.')
    ap.add_argument('n', nargs='?', type=int, help='its number (1 resumes the kept session); default the first free')
    ap.add_argument('--new', action='store_true', help='open another one without taking focus (a window in the '
                    "run's tmux session; Windows: a hidden console) and print its claude.ai/code link")
    ap.add_argument('--brief', action='store_true', help=argparse.SUPPRESS)  # the SessionStart hook
    ap.add_argument('--hand', action='store_true', help=argparse.SUPPRESS)  # F53: the hook in settings.local.json
    ap.add_argument('--blank', action='store_true', help=argparse.SUPPRESS)  # c1 under [run] remote: no opening turn
    ap.add_argument('--local', action='store_true', help=argparse.SUPPRESS)  # c1 under [run] remote: not in the apps
    ap.add_argument('--new-run', action='store_true', help=argparse.SUPPRESS)  # F27: c1 of a new run (not a restart)
    ap.add_argument('--ask', default='', help=argparse.SUPPRESS)  # its first message: tests and older feeds (B72)
    ap.add_argument('--ask-file', default='', help=argparse.SUPPRESS)  # B72: the forwarded message, from a file
    ap.add_argument(FORWARD_FLAG, action='store_true', help='open another one (as --new) whose first message is '
                    "the person's latest message in the runner feed, word for word, with its attachments (the "
                    'feed hands requests on this way)')
    ap.add_argument('--runner', action='store_true', help='with --forward: open it in agent-runner\'s own checkout '
                    'instead, labelled with this project (the feed hands asks about agent-runner itself on this way)')
    ap.add_argument('--from-feed', default='', help=argparse.SUPPRESS)  # B54: the project a --runner ask came from
    ap.add_argument('--file', '--image', dest='file', action='append', default=[], metavar='PATH',
                    help='a file or image the person attached to the first message (repeatable): the first message '
                    'names it and its path and says to Read or open it')
    ap.add_argument('--feed-sid', default='', help=argparse.SUPPRESS)  # B57: wait for the handed-on message's files
    ap.add_argument('--title', default=None, metavar='SUMMARY', help='from inside control session N, once it has '
                    'read its first message: name it "<repo> · N · SUMMARY" for what it is for')
    a = ap.parse_args(argv)
    init()
    if a.brief:
        if a.hand and os.environ.get(RUNNER_STARTED_ENV):
            return 0  # F53: a session the runner started has its brief from --settings already
        print(control_brief(), end='')
        env_n = os.environ.get(CONTROL_N_ENV, '')
        if env_n.isdigit():  # F32: /clear or /new in control session N
            sys.stdout.flush()
            control_session_start(int(env_n), control_hook_input())
        return 0
    if a.title is not None:
        env_n = os.environ.get(CONTROL_N_ENV, '')
        return control_set_title(a.n or (int(env_n) if env_n.isdigit() else 0), a.title)
    if not control_ok():
        print(f'control sessions are Claude Code sessions; [run] agent is {C.run["agent"]}', file=sys.stderr)
        return 1
    if a.runner and a.forward and not a.feed_sid:
        return control_new_runner(a.n, images=a.file)
    if a.new or (a.forward and not a.feed_sid):
        return control_new(a.n, ask=a.ask, images=a.file, forward=a.forward and not a.from_feed,
                           handed=bool(a.from_feed))
    if a.ask_file:
        a.ask = read_ask_file(a.ask_file) or a.ask
    if a.forward and a.feed_sid and SID_RE.fullmatch(a.feed_sid):
        a.ask, got, done = forward_late_files(a.n or free_control_number(), a.feed_sid)
        a.file = [*a.file, *(i for i in got if i not in a.file)]  # BUG1: a photo sent alone
        a.feed_sid = '' if done else a.feed_sid
    n = a.n or free_control_number()
    if pid := control_live(n):
        print(f'control {n} already runs (pid {pid}): {shown_cmd()} control starts another', file=sys.stderr)
        return 1
    if a.feed_sid and a.ask and SID_RE.fullmatch(a.feed_sid):
        print('waiting for the runner feed to record the message and its attachments…', flush=True)
        try:  # hold number n while waiting, so another control --new does not take it
            C.notes(f'control{n}.pid').write_text(f'{os.getpid()}', encoding='utf-8')
        except OSError:
            pass
        a.ask, a.file = control_late_files(a.ask, a.file, a.feed_sid)
    sid, resume, argv = control_open(n, ask=a.ask, images=a.file, new_run=a.new_run, blank=a.blank, local=a.local)
    backend().trust(ROOT)
    os.chdir(ROOT)
    pidf = C.notes(f'control{n}.pid')
    env = control_env()
    env[CONTROL_N_ENV] = str(n)  # F29: `control --title` from its tools knows which session it is
    if '--remote-control' in argv and silent():  # no push after its start push (that one cannot be stopped)
        env[PRESENCE_ENV] = str(quiet_file(f'c{n}'))
    if not plat.WINDOWS:  # exec: the pid in the file is the session's own
        pidf.write_text(f'{os.getpid()} {sid}', encoding='utf-8')
        os.execvpe(argv[0], argv, env)
    p = sp.Popen(argv, env=env)
    pidf.write_text(f'{p.pid} {sid}', encoding='utf-8')
    while True:
        try:
            return p.wait()
        except KeyboardInterrupt:
            continue  # Ctrl-C is the session's (it interrupts a turn)
