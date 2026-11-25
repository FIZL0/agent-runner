"""The other `agent-runner` commands: take, resume, key, upgrade, status, since, needs, sheet, stop,
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
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from agent_runner import control_harness, control_held, no_push, page_only, plan as P, plansync, plat, shared_tools, stack
from agent_runner.config import RUNNER, runner_cmd, shown_cmd
from agent_runner.state import (ask_stop, C, clear_stop, default_branch, edited, git, init, queued, ROOT, run_up,
    SLOTS_DIR, EV_RUN_UP)
from agent_runner.brief import has_sheet, prompt_for
from agent_runner.sched import agent_held, ahead, open_tasks
from agent_runner.slots import (backend, claude_json, entries, logged, marker_pid, MUX, PRESENCE_ENV, quiet_file,
    remote_off_why, remote_on, remote_slots_on, REMOTE_URL, silent, transcript, worktree)
from agent_runner.attach import attach_session, session_socket
from agent_runner.watch import breaking, installed_version, last_session, queue_resume, upgrade, upgrade_argv
from agent_runner.land import wip_main_info
from agent_runner.control import (control_argv, control_brief, control_env, control_give, control_hook_input,
    control_link, control_live, control_mark_ask, CONTROL_N_ENV, control_name, control_open, control_session_start,
    control_set_title, control_sid, FIRST_CONTROL, free_control_number, RUNNER_STARTED_ENV)
from agent_runner.control_first import CONTROL_FIRST, type_first_later  # B147
from agent_runner.status import (follow, move_since_mark, progress_line, release_line, since_mark_file, since_start,
    since_text, status_text, waiting_ok, as_event, events_file, read_events)
from agent_runner.feed import board_held, control_new, read_ask_file
from agent_runner.loop import drop_session_env, finish, send_key


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
    """F52: slot `n`'s claude.ai/code link: its session's pid -> session id -> the transcript's bridge-session
    entry; '' when `[run] remote_slots` is not "always" or any step is missing."""
    if not remote_slots_on():
        return ''
    try:
        # a resume queued for this task names its session; the slot then may run another task's
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


def slot_running(tid: str, because: str = '') -> str:
    """F52: why `take tid` refuses a task a slot runs, with where to watch and steer it instead. B109: never an
    `attach sN` line (the person may be on the app, with no terminal): the slot's claude.ai/code link when there
    is one, and `plan tell` to steer it. `because`: why take did not take it back from the slot."""
    n = running_slot(tid)
    if not n:
        return 'running in a slot'
    link = slot_link(n, tid)
    return (f'running in slot s{n}' + (f' ({because})' if because else '') + '; nothing taken. '
            + (f'Watch or steer it there instead:\n  {link}\n' if link else 'Steer it from here instead:\n')
            + f'  {C.command} plan tell {tid} "what to do differently"')


def slot_just_started(tid: str, n: int, branch: str) -> bool:
    """B109: slot n started `tid` only moments ago: its worktree is on task/<tid> (not a cut-off session waiting
    to resume), the branch has no commits past `branch`, and no earlier attempt of it is parked (wip/<tid>)."""
    d = SLOTS_DIR / f's{n}'
    if not d.is_dir() or git('symbolic-ref', '-q', '--short', 'HEAD', cwd=d).stdout.strip() != f'task/{tid}':
        return False
    if git('rev-list', '--count', f'{stack.fork(tid, branch)}..task/{tid}').stdout.strip() != '0':
        return False
    return not git('for-each-ref', '--format=%(refname)', f'refs/heads/wip/{tid}',
                   f'refs/heads/wip/{tid}-*').stdout.strip()


def take_back(tid: str, n: int, branch: str) -> str | None:
    """B109: `take tid` on a task slot n started only moments ago: the person asked for it here, so the run
    stops that slot's agent, throws its attempt away and frees the slot (the B19 halt, as kind 'take' (B110):
    no drop, the task stays in the plan), and take goes on in a worktree of its own. The take worktree is made first,
    detached, so the run passes over the task as taken and never starts it again in the freed slot.
    Returns what the run said; None when no run is up to stop the slot, or it did not answer (nothing taken)."""
    if not P.run_on(C, tid):
        return None
    d = worktree(f'take-{tid}', branch)
    said = P.request(C, 'halt', tid, {'how': 'take'}, P.HALT_WAIT)  # B110: no drop, no EV_DROPPED
    end = time.monotonic() + 10
    while said is not None and time.monotonic() < end and \
            not git('rev-parse', '--verify', '-q', f'refs/heads/task/{tid}').returncode:
        time.sleep(0.2)  # the run answers after it deleted task/<tid>; a slow disk gets a moment
    if said is None or not git('rev-parse', '--verify', '-q', f'refs/heads/task/{tid}').returncode:
        (P.channel(C, 'halt') / f'{tid}.json').unlink(missing_ok=True)  # unanswered: the slot keeps it
        git('worktree', 'remove', '--force', str(d))
        return None
    return said.strip()


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
        n = running_slot(tid)
        fresh = bool(n) and slot_just_started(tid, n, branch)
        if fresh and take_back(tid, n, branch) is not None:  # the run's own answer is for its log
            print(f'{tid}: took it back from s{n}, which had only just started it (no commits): the run stopped '
                  f'that agent and gave the slot back; the task stays in the plan', file=sys.stderr)
            why = ''
        else:
            why = slot_running(tid, 'no run is up to stop it, or it did not answer' if fresh else
                               'further along: it has commits or earlier work' if n else '')
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
    """`pause`, `force`, `slots` and `key`: the runner keys from any terminal, or from a remote session.
    Unlike a typed key, `pause` and `force` say which way (on, or off with --off), so saying it twice is safe."""
    cmd = prog.split()[-1]
    ap = argparse.ArgumentParser(prog=prog, description={
        'pause': 'Start no new tasks; the run stays up (--off: start them again).',
        'force': 'Start tasks past the session and weekly usage caps (--off: the caps hold again).',
        'slots': 'Change the running slot count: N, +N or -N (a slot past the count finishes its task first).',
        'key': 'Send keys to the run as if typed in the run view (? lists them).'}[cmd])
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
    """B49 `agent-runner upgrade`: what `u` in the run view does, from any terminal or a control session.
    It runs `upgrade` (pipx, uv tool, or a pull, per `upgrade_argv`) here; a run that is up sees the new version
    on disk and restarts on it by itself (`restart_if_upgraded`), as after `u`; with auto_upgrade off it is asked to."""
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
        if not C.run['auto_upgrade'] and not plat.WINDOWS and not breaking(__version__, new):
            send_key('restart')  # F149: off, so it restarts on nothing by itself
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
    from agent_runner.ui_model import agent_problem
    from agent_runner.watch import claude_login_line
    print(status_text(up, st, read_events(), P.titles(C.done, C.todo),time.time(), waiting=waiting_ok(), wips=wip_main_info(),
                      login=claude_login_line(), agent=agent_problem(st=st),
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
                         'is idle, or paused or stopping with nothing running')
    a = ap.parse_args(argv)
    init()
    if a.needs_you and not a.follow:
        ap.error('--needs-you goes with --follow')
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
    if run_up():  # F168: they wait for a shared tool, not for the person
        print(*(f'{t} {said}\n' for t, said in shared_tools.wait_words().items()), sep='', end='')
    return 0


def cmd_sheet(argv: list[str], prog: str = f'{RUNNER} sheet') -> int:
    """`agent-runner sheet ID`: render a DECIDE's pick sheet, or answer the item with the picks sent from it."""
    from agent_runner import sheet
    ap = argparse.ArgumentParser(prog=prog, description='The pick sheet of a DECIDE: render its page, or answer it '
                                 'with the picks sent from the page (or the recommended ones).')
    ap.add_argument('id', help='the task id, as Needs you shows it')
    do = ap.add_mutually_exclusive_group()
    do.add_argument('--html', metavar='FILE', help='check the sheet and write its page to FILE, to look at')
    do.add_argument('--publish', action='store_true', help='publish its page and print the URL')
    do.add_argument('--picks', metavar='REPLY', help="the line the sheet's Send gave ('ID picks: a=b …'), or 'go'")
    do.add_argument('--go', action='store_true', help='answer with the recommended picks')
    do.add_argument('--path', action='store_true', help='print where the sheet is')
    ap.add_argument('--note', default='', help='with --picks or --go: words to note beside the picks')
    a = ap.parse_args(argv)
    a.note and a.picks is None and not a.go and ap.error('--note goes with --picks or --go')
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
    if a.html or a.publish:
        from agent_runner import web
        link = web.pick_base(a.id)  # F138: Send's link to the run
        if a.publish:
            return sheet.cmd_publish(spec, a.id, link, prog)
        Path(a.html).write_text(sheet.render(spec, a.id, pick=link), encoding='utf-8')
        print(f'{a.html}: {len(sheet.questions(spec))} questions; publish it with `{prog} {a.id} --publish`')
        print('F138: Send also gives a link that answers the run directly' if link else
              'F138: ' + NO_PICK_HTTPS.format(why=web.no_https_why()).replace('put no option buttons on the page and ', ''))
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
    return plan.main(['confirm', a.id, sheet.picks_note(spec, picks) + (f'; note: {note}' if (note := " ".join(a.note.split())) else '')])


NO_PICK_HTTPS = ('no https address for the run page ({why}): '
                 'put no option buttons on the page and keep today\'s flow (the person replies, or Sends)')


def cmd_pick_links(argv: list[str], prog: str = f'{RUNNER} pick-links') -> int:
    """F138: `agent-runner pick-links ID A,B,C`: one link per option, for the option buttons on a concept page;
    each answers the run with no AI session (web /pick). Exit 1, saying so, when the run page has no https."""
    import re
    from agent_runner import web
    ap = argparse.ArgumentParser(prog=prog, description="Print each option's button link for item ID: tapping "
                                 'it answers the run with that option (a one-use code, not the page token).')
    ap.add_argument('id', help='the item id: the concept (or the task whose question it is)')
    ap.add_argument('options', help='the options, comma-separated: A,B,C')
    a = ap.parse_args(argv)
    if not re.fullmatch(r'[A-Za-z]+\d+[a-z0-9]*', a.id):
        ap.error(f'{a.id!r} is not a task id')
    opts = [o.strip() for o in a.options.split(',') if o.strip()]
    if not opts or not all(web.PICK_OPTION.fullmatch(o) for o in opts):
        ap.error('options are letters or digits, comma-separated: A,B,C')
    init()
    links = web.pick_links(a.id, opts)
    if not links:
        print(f'{prog}: ' + NO_PICK_HTTPS.format(why=web.no_https_why()), file=sys.stderr)
        return 1
    for o, link in zip(opts, links):
        print(f'{o} {link}')
    return 0


def cmd_stop(argv: list[str], prog: str = f'{RUNNER} stop') -> int:
    """`./run stop`: the running sessions finish and merge, nothing new starts, and the run exits."""
    ap = argparse.ArgumentParser(prog=prog, description='Finish the running tasks, start nothing new, then the run stops. Its run page stays up (`agent-runner page-only stop` ends it), except after --suspend or --shutdown.')
    ap.add_argument('--force', action='store_true',
                    help='end the agent sessions now (each resumes in the next run), as s! in the run view')
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
          + (f', then {"suspends" if a.suspend else "shuts down"} the computer' if a.suspend or a.shutdown else '; its page stays up' if page_only.kept() else ''))
    return 0


# --- the run in the background: bare `agent-runner`, and `attach` ----------------------------------------


def background_argv() -> list[str]:
    """What bare `agent-runner` starts as a detached process: the run, its slots hidden (as every run's are)."""
    return [*runner_cmd(), 'run']


def remote_ready(tty: bool | None = None, ask=input) -> bool:
    """With `[run] remote`: will Claude Code start a slot without its one-time "Enable Remote Control? (y/n)"?
    In a hidden session that question would hold every slot, so it is asked here, in this terminal, and the
    answer kept where Claude Code keeps it (`remoteDialogSeen` in ~/.claude.json). False: start nothing.
    Under `[run] remote = 'auto'` (and remote_slots not "always") it never stops a run: with no terminal to ask on, or
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


def started_note(slots: int, where: str) -> str:
    attach = ("where slot 2's log is: attach s2" if plat.has_conpty() else
              "slot 2's console window: attach s2 (closing that window ends the session)" if plat.WINDOWS else
              "the run's log and keys (attach s2: slot 2's terminal; Ctrl-b d leaves it)")
    lines = [f'the run is up in the background: {slots} slot{"s" if slots != 1 else ""}, {where}',
             f'    {shown_cmd()} status     what it is doing',
             f'    {shown_cmd()} attach     {attach}',
             f'    {shown_cmd()} stop       finish the running tasks, then end it (--force: now)']
    if C.run['control']:
        lines.append(f'    {shown_cmd()} control    a new control session in this terminal')
    if remote_on():
        lines.append(f'    {REMOTE_URL}  the control sessions, from any device or the Claude apps')
    elif remote_slots_on():
        lines.append(f'    {REMOTE_URL}  the slots, from any device or the Claude apps')
    return '\n'.join(lines)


STARTED_BY_ENV = 'AGENT_RUNNER_STARTED_BY'  # B145: set by a caller that starts the run for someone (Home: 'Home start')
EV_STARTED_BY = 'run started by'  # B145: who asked for the run (by, tty, ppid, parent)


def started_by_record(by: str) -> dict:
    """B145: who is starting the run: `by` (bare agent-runner, picker, --attach or Home start), the caller's
    tty ('no tty' without one, 'terminal' on Windows, which has no tty names), its parent pid and that parent's
    command name ('' where it cannot be read)."""
    tty = 'no tty'
    ttyname = getattr(os, 'ttyname', lambda fd: 'terminal')  # B760: Windows Python has no os.ttyname
    for fd in (0, 1, 2):
        try:
            if os.isatty(fd):
                tty = ttyname(fd)
                break
        except OSError:
            pass
    ppid = os.getppid()
    parent = ''
    try:
        parent = Path(f'/proc/{ppid}/comm').read_text(encoding='utf-8', errors='replace').strip()
    except OSError:
        pass
    return {'by': by, 'tty': tty, 'ppid': ppid, 'parent': parent}


def log_started_by(by: str) -> None:
    """B145: 'run started by <by>' with the caller's tty and parent pid into run.log and events.jsonl (not to the
    terminal), so a run that comes up right after a stop can be traced to the picker, Home or a script."""
    rec = started_by_record(by)
    stamp = dt.datetime.now().isoformat(timespec='seconds')
    msg = (f'run started by {rec["by"]} (tty {rec["tty"]}, parent pid {rec["ppid"]}'
           + (f' {rec["parent"]}' if rec['parent'] else '') + f', pid {os.getpid()})')
    try:
        with open(C.notes('run.log'), 'a', encoding='utf-8') as f:
            f.write(f'=== {stamp} {msg}\n')
    except OSError:
        pass
    try:
        with open(events_file(), 'a', encoding='utf-8') as f:
            f.write(json.dumps({'time': stamp, 'kind': EV_STARTED_BY, 'id': '', 'text': msg, **rec},
                               ensure_ascii=False) + '\n')
    except OSError:
        pass


def cmd_background(argv: list[str], by: str = 'bare agent-runner') -> int:
    """Bare `agent-runner`: start the run as a detached process (`plat.spawn_detached`), its slots hidden, and
    give the prompt back once it is up. `attach` then shows its log and takes its keys. `by` (B145): who asked,
    logged before the run starts; AGENT_RUNNER_STARTED_BY overrides it (Home's start button sets it)."""
    by = os.environ.pop(STARTED_BY_ENV, '') or by
    drop_session_env()
    init()
    if run_up():
        print(f'a run is already up in this repository: {shown_cmd()} status, {shown_cmd()} attach, '
              f'{shown_cmd()} stop')
        return 0
    if not remote_ready():
        return 1
    log_started_by(by)
    log_file = C.notes('run.log')
    since = events_file().stat().st_size if events_file().exists() else 0
    out = C.notes('background.out')
    proc = plat.spawn_detached([*plat.service_scope(), *background_argv()], out=out)
    slots = wait_started(since, lambda: proc.poll() is not None)
    if slots is None:
        try:
            said = out.read_text(encoding='utf-8', errors='replace').strip()[-2000:]
        except OSError:
            said = ''
        print(f'the run did not come up' + (f':\n{said}' if said else f'; see {log_file}'), file=sys.stderr)
        return 1
    print(started_note(slots, 'its slots hidden'))
    return 0


def cmd_background_attach(argv: list[str]) -> int:
    """`agent-runner --attach`: the background run (started now, or the one already up in this repo), then the
    run view in this terminal, as `attach` shows it; Ctrl-C leaves it and the run keeps going. Windows: the run
    has no view of its own there, so it is bare `agent-runner`, and says so."""
    if argv:
        print(f'{shown_cmd()} --attach takes nothing more (got {" ".join(argv)})', file=sys.stderr)
        return 2
    init()
    if plat.WINDOWS:
        print(f'on Windows the run has no window to attach: --attach starts it as {shown_cmd()} does')
        return cmd_background([], by='--attach')
    if not run_up():
        if r := cmd_background([], by='--attach'):
            return r
    return cmd_attach([])


def hidden_attach(which: str) -> str:
    """F40: what `attach` says of a slot (Windows: or a control session) that runs hidden but has no socket to
    attach through (it could not be made; Windows before 1809 has none): where its output is and how to steer it; '' when there
    is no such session (the caller says so)."""
    c = plat.WINDOWS and re.fullmatch(r'c\d+', which)
    stem = f'{"control" if c else "slot"}{which[1:]}'
    pid = marker_pid(C.notes(f'{stem}.live')) if c or re.fullmatch(r's\d+', which) else 0
    if not (pid and plat.alive(pid)):
        return ''
    if c:
        return f'{which} runs hidden (pid {pid}), with no terminal to attach: its output goes to ' + \
            str(C.notes(f'{stem}.log'))
    remote = f'; on Remote Control ({REMOTE_URL})' if remote_slots_on() else ''
    return (f'{which} runs hidden (pid {pid}), with no terminal to attach: its output goes to '
            f'{C.notes(f"{stem}.log")}{remote}' +
            ('' if plat.WINDOWS and not C.notes(f'{stem}.in').exists() else
             f'; {shown_cmd()} plan tell <ID> "<text>" types into it'))


def cmd_attach(argv: list[str], prog: str = f'{RUNNER} attach') -> int:
    """`agent-runner attach [sN|cN|run|feed]`: the run view, or a session's own terminal; on Windows a slot's
    console window. No name (or `run`): the run view (`run_view`: its log, live, and its keys; Ctrl-C leaves).
    F88: a session is attached through its shim's socket (`attach_session`); Ctrl-b d leaves. `feed` and
    `board`: the TUI. F80: `attach N` (a number from `agent-runner list`) or `attach <project> cN|sN|feed|run`,
    from any folder."""
    if not any(a.startswith('-') for a in argv) and (argv[:1] and argv[0].isdigit() or len(argv) == 2):
        return attach_listed(argv)
    ap = argparse.ArgumentParser(prog=prog, description="Show the run view (its log and keys), or a session's own "
                                 f"terminal (s2, c3); attach N: number N of {shown_cmd()} list; attach <project> "
                                 "s2|c3|run|feed: from any folder.")
    ap.add_argument('slot', nargs='?', default='', help='s2 for slot 2; c3 for control session 3; feed or board for '
                    'the TUI; a number: that one of the list; none or run: the run view')
    a = ap.parse_args(argv)
    init()
    which = {'run': 'runner', '': 'runner'}.get(a.slot, a.slot)
    if sock := session_socket(which):  # F88: a hidden session's own terminal, through its shim's socket
        return attach_session(sock, which)
    if plat.WINDOWS:
        if which == 'runner':
            print(f'on Windows the run has no window of its own: {shown_cmd()} status shows it, and its log is '
                  f'{C.notes("run.log")}. {shown_cmd()} attach s1 shows slot 1.')
            return 0
        c = re.fullmatch(r'c\d+', which)
        marker = C.notes(f'{"control" if c else "slot"}{which[1:]}.live')
        pid = marker_pid(marker) if c or re.fullmatch(r's\d+', which) else 0
        if not (pid and plat.alive(pid)):
            print(f'{which} is not running: {shown_cmd()} status lists the slots', file=sys.stderr)
            return 1
        if logged(marker):  # F145: no console window to show
            print(hidden_attach(which))
            return 0
        if not plat.show_console(pid):
            print(f'{which} runs as pid {pid}, but its console window could not be shown', file=sys.stderr)
            return 1
        print(f'{which}: its console window is up (minimize it to hide it again; closing it ends the session)')
        return 0
    if which == 'runner':
        from agent_runner.run_view import run_view
        return run_view()
    if which in ('feed', 'board'):  # B195: no run has one any more; the TUI shows what lands
        from agent_runner.tui import main as tui_main
        return tui_main([])
    if said := hidden_attach(which):
        print(said)
        return 0
    print(f'{which} is not running in this repository: {shown_cmd()} status lists the slots, {shown_cmd()} list '
          f'every session on this device', file=sys.stderr)
    return 1


# --- F80: every agent-runner session on this device: `list`, and `attach N` / `attach <project> X` -----------


def window_control_title(repo: str, wname: str, n: int) -> str:
    """A control session's title from the name the runner gave it (`control_given`), as the Run page's Sessions
    shows it: "<repo> · 6 · Pairing broken" is 'Pairing broken'; 'control session' when the name holds nothing
    more."""
    title = wname[len(repo) + 3:].strip() if wname.startswith(f'{repo} · ') else ''
    if title.startswith(f'{n} · '):
        title = title[len(f'{n} · '):].strip()
    return 'control session' if title in ('', str(n), f'control {n}') else title


def run_info(root: Path) -> dict:
    """What `list` says of the run of the project at `root`: up (its run lock is held) and its STATE (state,
    slots, running, since); {} when that project's settings or notes cannot be read."""
    try:
        from agent_runner.config import Config
        c = Config(root)
        f = plat.lock(c.notes('run.lock'))
        if f:
            f.close()
            return {'up': False}
        try:
            st = json.loads(c.notes('STATE').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            st = {}
        return {'up': True, **(st if isinstance(st, dict) else {})}
    except (OSError, SystemExit, ValueError, KeyError, TypeError):
        return {}


def device_projects(hidden: dict[Path, dict[str, int]], info=run_info, now: float | None = None,
                    titles: dict[Path, dict[int, str]] | None = None) -> list[dict]:
    """F80: each project with a run or sessions on this device: {'root', 'name', 'run' (`info(root)`), 'rows'}.
    C26: found from the hidden sessions' markers, `hidden` ({root: {'s2': pid, 'c1': pid, 'feed': pid}}, a
    root with {} when only its run may be up), never from window names. Rows in order: the run ('run', while
    it is up), the runner feed ('feed'), control sessions cN (titled from `titles`, {root: {N: the name the
    runner gave it}}), then slots sN with their task and minutes from the run's STATE; each has 'name',
    'what', 'pid', 'root' and 'n', numbered 1..N over all projects."""
    now = time.time() if now is None else now
    out, n = [], 0
    for root in sorted(hidden, key=lambda r: (r.name, str(r))):
        pids = hidden[root]
        run = info(root) or {}
        if not pids and not run.get('up'):
            continue
        running = {f's{k}': v for k, v in (run.get('running') or {}).items() if str(k).isdigit()} if run.get('up') else {}
        since = run.get('since') or {}
        named = (titles or {}).get(root, {})
        listed = []
        if run.get('up'):
            listed.append(('run', 'the run'))
        if 'feed' in pids:
            listed.append(('feed', 'runner feed'))
        listed += [(f'c{k}', window_control_title(root.name, named.get(k, ''), k))
                   for k in sorted(int(c[1:]) for c in pids if re.fullmatch(r'c\d+', c))]
        for s in sorted(set(running) | {k for k in pids if re.fullmatch(r's\d+', k)}, key=lambda k: int(k[1:])):
            tid, t0 = running.get(s, ''), since.get(s[1:])
            mins = f' · {int((now - t0) // 60)}m' if tid and isinstance(t0, (int, float)) else ''
            listed.append((s, f'{tid}{mins}' if tid else 'idle'))
        rows_out = []
        for name, what in listed:
            pid = pids.get(name, 0)
            num = 0
            if pid or name == 'run':
                n += 1
                num = n
            rows_out.append({'name': name, 'what': what, 'pid': pid, 'root': root, 'n': num})
        out.append({'root': root, 'name': root.name, 'run': run, 'rows': rows_out})
    return out


def run_words(run: dict) -> str:
    """'run up: running · 3 slots', 'run up: idle', or 'no run up'."""
    if not run.get('up'):
        return 'no run up'
    slots, state = run.get('slots'), run.get('state') or 'starting'
    return (f'run up: {state}' + (f' · {slots} slot{"" if slots == 1 else "s"}'
                                  if isinstance(slots, int) and 'slot' not in state else ''))


def list_text(projects: list[dict]) -> str:
    """`agent-runner list`: each project, then its numbered sessions (a number is what `attach N` takes)."""
    if not projects:
        return 'no agent-runner sessions on this device\n'
    out = []
    for p in projects:
        out.append(f'{p["name"]}  {run_words(p["run"])}  ({p["root"]})')
        for r in p['rows']:
            out.append(f'  {str(r["n"]) if r["n"] else "-":>3}  {r["name"]:<5} {r["what"]}')
    return '\n'.join(out) + '\n'


def hidden_consoles() -> tuple[dict[Path, dict[str, int]], dict[Path, dict[int, str]]]:
    """({main checkout: {'s2': pid, 'c1': pid, 'feed': pid}}, {main checkout: {N: control N's given name}}) of
    each hidden session alive on this device (`<notes>/slotN.live`, `controlN.live`, `board.live`). Every project
    found is a key, so `device_projects` can list a run that is up with no session. Found through the slot
    worktrees in the runs folder (AGENT_RUNNER_HOME, else `[run] home`'s default ~/runs/<project>), the
    current repository's own `[run] home`, and the current repository's notes."""
    from agent_runner.config import Config
    roots: set[Path] = set()
    worktrees: list[Path] = []
    try:
        here = main_checkout_of(Path.cwd())
        roots.add(here)
        worktrees += Config(here).home.glob('s*')
    except (SystemExit, OSError, KeyError, TypeError):
        pass
    home = os.environ.get('AGENT_RUNNER_HOME') or '~/runs/{repo}'
    if '{repo}' in home:  # one folder per project: <base>/<project>/sN
        base = Path(os.path.expanduser(home.split('{repo}')[0]))
        worktrees += base.glob('*/s*') if base.is_absolute() and base.is_dir() else []
    elif Path(os.path.expanduser(home)).is_absolute():  # one project's folder: <home>/sN
        worktrees += Path(os.path.expanduser(home)).glob('s*')
    for wt in sorted(set(worktrees)):
        if re.fullmatch(r's\d+', wt.name) and (wt / '.git').exists():
            try:
                roots.add(main_checkout_of(wt))
            except (SystemExit, OSError):
                continue
    out: dict[Path, dict[str, int]] = {}
    titles: dict[Path, dict[int, str]] = {}
    for root in roots:
        try:
            c = Config(root)
            out.setdefault(root, {})
            for m in sorted(c.notes().glob('*.live')):
                hit = re.fullmatch(r'(slot|control)(\d+)|board', m.stem)
                if not hit:
                    continue
                if not ((pid := marker_pid(m)) and plat.alive(pid)):
                    continue
                name = 'feed' if not hit[1] else f'{hit[1][0]}{hit[2]}'
                out[root][name] = pid
                if hit[1] == 'control':
                    try:
                        titles.setdefault(root, {})[int(hit[2])] = c.notes(f'control{hit[2]}.title').read_text(
                            encoding='utf-8').strip()
                    except OSError:
                        pass
        except (SystemExit, OSError, ValueError, KeyError):
            continue
    return out, titles


def main_checkout_of(path: Path) -> Path:
    from agent_runner.config import main_checkout
    return main_checkout(path)


def device_sessions() -> list[dict]:
    """`device_projects` for this device: its hidden sessions (`hidden_consoles`)."""
    hidden, titles = hidden_consoles()
    return device_projects(hidden, titles=titles)


def cmd_list(argv: list[str], prog: str = f'{RUNNER} list') -> int:
    """`agent-runner list`, from any folder: every agent-runner session on this device, numbered for `attach N`."""
    ap = argparse.ArgumentParser(prog=prog, description='Every agent-runner run and session on this device: '
                                 f'{shown_cmd()} attach N shows number N.')
    ap.parse_args(argv)
    print(list_text(device_sessions()), end='')
    return 0


def pick_listed(projects: list[dict], argv: list[str]) -> tuple[dict | None, str]:
    """The row `attach N` or `attach <project> <name>` names, or (None, why not)."""
    rows = [(p, r) for p in projects for r in p['rows']]
    if len(argv) == 1:
        hit = [r for _, r in rows if r['n'] == int(argv[0])]
        return (hit[0], '') if hit else (None, f'no session {argv[0]}: {shown_cmd()} list numbers them')
    proj, name = argv
    name = {'board': 'feed', 'runner': 'run'}.get(name, name)
    name = f's{name}' if name.isdigit() else name
    mine = [p for p in projects if proj in (p['name'], str(p['root']))]
    if not mine:
        return None, f'no project {proj} with sessions on this device: {shown_cmd()} list'
    hit = [r for p in mine for r in p['rows'] if r['name'] == name and r['n']]
    return (hit[0], '') if hit else (None, f'{proj} has no session {name} to attach: {shown_cmd()} list')


def attach_listed(argv: list[str]) -> int:
    """`attach N` / `attach <project> cN|sN|feed|run`: that project's `attach <name>`, run from its main
    checkout (the run view, a session's own terminal, the TUI; on Windows as `attach sN` there)."""
    if len(argv) > 2:
        print(f'{shown_cmd()} attach N, or attach <project> cN|sN|feed|run', file=sys.stderr)
        return 2
    row, why = pick_listed(device_sessions(), argv)
    if not row:
        print(why, file=sys.stderr)
        return 1
    os.chdir(row['root'])  # its own repository: `attach` (and the TUI) read the project they are run in
    return cmd_attach([row['name']])


def cmd_control(argv: list[str], prog: str = f'{RUNNER} control') -> int:
    """`agent-runner control [N]`: a new control session in this terminal, in the main checkout, as number N (the
    first free one by default)."""
    drop_session_env()
    ap = argparse.ArgumentParser(prog=prog, description='A control session here: ask it for status, pause, '
                                 'slots, stop; it files asks with plan add and does do-it-now work with take.')
    ap.add_argument('n', nargs='?', type=int, help='its number (2 and up); default the first free')
    ap.add_argument('--new', action='store_true', help='open another one without taking focus (a hidden terminal: '
                    'attach cN shows it; Windows: a hidden console) and print its claude.ai/code link')
    ap.add_argument('--no-wait', action='store_true', help='with --new: return once it starts, without waiting '
                    'for its claude.ai/code link (the terminal UI reads the link from state later)')
    ap.add_argument('--brief', action='store_true', help=argparse.SUPPRESS)  # the SessionStart hook
    ap.add_argument('--hand', action='store_true', help=argparse.SUPPRESS)  # F53: the hook in settings.local.json
    ap.add_argument('--reopen', action='store_true', help=argparse.SUPPRESS)  # B121: resume cN after a shutdown
    ap.add_argument('--ask', default='', help=argparse.SUPPRESS)  # its first message: tests and older feeds (B72)
    ap.add_argument('--ask-file', default='', help=argparse.SUPPRESS)  # B72: the first message, from a file (control --new)
    ap.add_argument('--no-feed', action='store_true', help=argparse.SUPPRESS)  # B154: the run page and the TUI pass it; no effect
    ap.add_argument('--file', '--image', dest='file', action='append', default=[], metavar='PATH',
                    help='a file or image the person attached to the first message (repeatable): the first message '
                    'names it and its path and says to Read or open it')
    ap.add_argument('--title', default=None, metavar='SUMMARY', help='from inside control session N, once it has '
                    'read its first message: name it "<repo> · N · SUMMARY" for what it is for')
    ap.add_argument('--rename', nargs=2, default=None, metavar=('N', 'NAME'), help='the person\'s own name for '
                    'control session N (the run app\'s Rename, r in agent-runner ui)')
    ap.add_argument('--resume', metavar='SID', default='', help='go on with the control session of that session id')
    a = ap.parse_args(argv)
    init()
    if a.rename:  # F129
        from agent_runner.control_names import control_rename
        return control_rename(*a.rename)
    if a.brief:
        if a.hand and os.environ.get(RUNNER_STARTED_ENV):
            return 0  # F53: a session the runner started has its brief from --settings already
        print(control_brief(), end='')
        env_n = os.environ.get(CONTROL_N_ENV, '')
        if env_n.isdigit():  # F32: /clear or /new in control session N
            sys.stdout.flush()
            control_session_start(int(env_n), control_hook_input())
        return 0
    if a.n is not None and a.n < FIRST_CONTROL and a.title is None and not a.reopen:  # F176: any free one
        a.n = None
    if a.title is not None:
        env_n = os.environ.get(CONTROL_N_ENV, '')
        return control_set_title(a.n or (int(env_n) if env_n.isdigit() else 0), a.title)
    if a.new:
        return control_new(a.n, ask=a.ask, images=a.file, **({'wait': -1} if a.no_wait else {}))
    if a.ask_file:
        a.ask = read_ask_file(a.ask_file) or a.ask
    no_push.require(C, ROOT)
    if bad := agent_held():  # B764c
        print(f'no control session started: {bad}', file=sys.stderr)
        return 1
    if a.resume and not control_harness.resume_into(a):  # F406f
        return 1
    n = a.n or free_control_number()
    if pid := control_live(n):
        print(f'control {n} already runs (pid {pid}): {shown_cmd()} control starts another', file=sys.stderr)
        return 1
    control_held.look(n)  # B170: before an ended session N's pid file is written over
    sid, resume, argv = control_open(n, ask=a.ask, images=a.file, reopen=a.reopen)
    if not control_harness.ready(n):
        return 1
    os.chdir(ROOT)
    pidf = C.notes(f'control{n}.pid')
    env = control_env()
    env[CONTROL_N_ENV] = str(n)  # F29: `control --title` from its tools knows which session it is
    if '--remote-control' in argv:  # while it is there ([run] silent) no push after its start push, which cannot be stopped
        env[PRESENCE_ENV] = str(quiet_file(f'c{n}', on=silent()))
    if not plat.WINDOWS:  # exec: the pid in the file is the session's own
        pidf.write_text(f'{os.getpid()} {sid}', encoding='utf-8')
        if first := CONTROL_FIRST[0]:  # B147: typed in once Remote Control is up, so the web thread shows it
            type_first_later(first)
        os.execvpe(argv[0], argv, env)
    p = sp.Popen(argv, env=env)
    pidf.write_text(f'{p.pid} {sid}', encoding='utf-8')
    while True:
        try:
            return p.wait()
        except KeyboardInterrupt:
            continue  # Ctrl-C is the session's (it interrupts a turn)


# --- F91: bare agent-runner at a terminal: the run picker, then the launcher -------------------------------------

def picker_wanted() -> bool:
    """Bare `agent-runner` shows the run picker only to a person at a terminal: stdin and stdout TTYs, and not
    a slot's agent. Otherwise it starts the run, as before."""
    try:
        tty = sys.stdin.isatty() and sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False
    return tty and not os.environ.get('AGENT_RUNNER_SLOT')


def page_link(urls: list[str], https=None) -> str:
    """B135: the run page link from <notes>/web.url's addresses (all http): a Tailscale Serve https address for
    its port first, as `run status` (web.page_line) and the run log print it, since Talk's mic needs https."""
    if not urls:
        return ''
    try:
        from agent_runner.web import https_first  # B146: keeps the path (/p/KEY/ through the device site)
        return https_first(urls, https)[0]
    except (OSError, ValueError):
        pass
    return urls[0]


def run_facts(root: Path, run: dict, https=None, site=None) -> dict:
    """What the run picker and the launcher say of the project at `root` beside `run` (`run_info`): tasks left,
    stopping (a stop was asked for), and the run page link ('' while no run serves one; its https address first,
    B135; B146: the device site's /p/KEY/ address when one routes the project, `site(root)`, home.site_links)."""
    out = {'left': None, 'stopping': False, 'link': '', 'no_settings': '', 'agent_problem': ''}
    try:
        from agent_runner.config import Config
        from agent_runner.status import tasks_left
        c = Config(root)
        from agent_runner.ui_model import agent_problem, no_settings
        out['agent_problem'] = agent_problem(c, run if run.get('up') else None)  # B764b
        out['no_settings'] = no_settings(c, run if run.get('up') else None)  # F178
        out['left'] = tasks_left(c.todo.read_text(encoding='utf-8').splitlines())[0]
        out['stopping'] = bool(run.get('up')) and c.notes('STOP').exists()
        if run.get('up'):
            us = c.notes('web.url').read_text(encoding='utf-8').split()
            if us:
                from agent_runner import home, web  # F165: own_links: never a page only Home opens
                us = (site or home.site_links)(root) or web.own_links(us)
            out['link'] = page_link(us, https)
    except (OSError, SystemExit, ValueError, KeyError, TypeError):
        pass
    return out


def warnings_of(row: dict) -> list[str]:
    """The warning lines under a picker row: no settings found (F178), a wrong `[run] agent` (B764b)."""
    return [row[k] for k in ('no_settings', 'agent_problem') if row.get(k)]


def picker_rows(projects: list[dict], here: Path | None, info=None, facts=None) -> list[dict]:
    """The run picker's rows: one per run on this device (`device_sessions`, runs only: a project whose run is
    up), by name; the project around the current folder (`here`) first, marked here, even when its run is not
    up. Each: {'root', 'name', 'run', 'here', 'left', 'stopping', 'link'}."""
    info, facts = info or run_info, facts or run_facts
    rows = [{'root': p['root'], 'name': p['name'], 'run': p['run'], 'here': False}
            for p in projects if (p.get('run') or {}).get('up')]
    if here is not None:
        mine = [r for r in rows if Path(r['root']) == here]
        rows = [r for r in rows if Path(r['root']) != here]
        row = mine[0] if mine else {'root': here, 'name': here.name, 'run': info(here) or {}}
        rows.insert(0, {**row, 'here': True})
    return [{**r, **facts(Path(r['root']), r['run'])} for r in rows]


def left_words(row: dict) -> str:
    if row.get('stopping'):
        return 'stopping'
    n = row.get('left')
    return '' if n is None else f'{n} task{"" if n == 1 else "s"} left'


def slots_words(run: dict) -> str:
    n = run.get('slots')
    return f'{n} slot{"" if n == 1 else "s"}' if isinstance(n, int) else ''


DIM, BOLD, RESET, CLEAR = '\x1b[2m', '\x1b[1m', '\x1b[0m', '\x1b[H\x1b[J'


class PickerPaint:
    """F109: the run picker and the launcher in the run page's colours (`[ui] theme`, theme.py): the accent
    title, this screen's keys yellow, keys that work everywhere bright blue, the focused row on the run page's
    dark-red bar across the width. Text in no colour keeps the terminal's own foreground and background."""

    def __init__(self, theme: dict, colours: int = 256, width: int | None = None):
        self.theme, self.colours, self.fixed = theme, colours, width

    @property
    def width(self) -> int:
        """The bar's width: the one given, else the terminal's at each draw, so the bar follows a resize."""
        return self.fixed or shutil.get_terminal_size((100, 24)).columns

    def code(self, token: str, ground: bool = False) -> str:
        from agent_runner import theme as TH
        return TH.sgr(self.theme, token, self.colours, ground)

    def c(self, token: str, text: str, bold: bool = False) -> str:
        return f'\x1b[{"1;" if bold else ""}{self.code(token)}m{text}{RESET}'

    def key(self, k: str) -> str:
        return self.c('yellow', k, True)

    def hints(self, keys: list[tuple[str, str]], everywhere: tuple[str, str]) -> str:
        """The run page's hint line: this screen's keys yellow, labels in text colour, a │, then the key that
        works everywhere in bright blue with its label dim."""
        sep = self.c('dim', ' · ')
        return (sep.join(f'{self.key(k)} {label}' for k, label in keys) + ' ' + self.c('line', '│') + ' '
                + self.c('bblue', everywhere[0], True) + self.c('dim', f' {everywhere[1]}'))

    def bar(self, parts: list[tuple[str, str | None]]) -> str:
        """One row on the focused-row bar: bold in the selection's colours, a part with a token in that colour
        (fg only, so the bar runs on), padded and erased to the line's end in the bar's colour."""
        on = f'\x1b[1;{self.code("sel", True)};{self.code("selfg")}m'
        text, n = on, 0
        for s, token in parts:
            text += f'\x1b[{self.code(token)}m{s}\x1b[{self.code("selfg")}m' if token else s
            n += len(s)
        return text + ' ' * max(0, self.width - 1 - n) + '\x1b[K' + RESET


def picker_paint(here: Path | None, env=None) -> PickerPaint | None:
    """F109: the colours for the run picker on this terminal, None (bold and dim only) when NO_COLOR is set
    or the output is not a terminal. The theme is `[ui] theme` of the project around the current folder,
    else the default."""
    from agent_runner import theme as TH
    env = os.environ if env is None else env
    try:
        tty = sys.stdout.isatty()
    except (AttributeError, ValueError):
        tty = False
    if env.get('NO_COLOR') or not tty or env.get('TERM') == 'dumb':
        return None
    name = TH.DEFAULT
    if here is not None:
        try:
            from agent_runner.config import Config
            name = TH.checked(Config(here).raw.get('ui', {}).get('theme', TH.DEFAULT))
        except (OSError, SystemExit, ValueError, KeyError, TypeError):
            pass
    return PickerPaint(TH.get(name), TH.terminal_colours(env))


def picker_text_painted(rows: list[dict], sel: int, p: PickerPaint, hint: str = '') -> str:
    """Screen 1 in colour (F109, concept K2 option A)."""
    out = [p.c('accent', 'agent-runner', True) + f'{BOLD} · pick a run{RESET}', '']
    if not rows:
        out.append(p.c('dim', '  no run is up on this device; start one from inside a project: agent-runner, then Enter and s'))
    for i, r in enumerate(rows):
        up = (r['run'] or {}).get('up')
        slots, left = slots_words(r['run']) if up else '(not running)', left_words(r)
        what = ' · '.join(x for x in (slots, left) if x)
        gap = ' ' * max(1, 29 - len(what))
        name = f'{r["name"]:<16} '
        warn = ''.join('\n' + p.c('yellow', f'     {w}') for w in warnings_of(r))
        slot_tok = 'green' if up else 'dim'
        left_tok = 'yellow' if r.get('stopping') else 'dim'
        if i == sel:
            parts = [(f'  {i + 1}  {name}', None), (slots, slot_tok if up else None)]
            if left:
                parts += [(' · ' if slots else '', None), (left, 'yellow' if r.get('stopping') else None)]
            parts += [(gap + str(r['root']) + ('  here' if r['here'] else '') + ' ', None)]
            out.append(p.bar(parts) + warn)
            continue
        bits = [p.c(slot_tok, slots)] + ([p.c(left_tok, left)] if left else [])
        line = f'  {p.key(str(i + 1))}  {name}' + ' · '.join(bits) + gap + p.c('dim', str(r['root']))
        out.append(line + ('  ' + p.c('accent', 'here') if r['here'] else '') + warn)
    out += ['', p.c('dim', hint)] if hint else []  # F194c
    out += ['', p.hints([('j/k', 'move'), ('1-9', 'pick'), ('⏎', 'pick')], ('q', 'quit'))]
    return '\n'.join(out) + '\n'


def launcher_text_painted(row: dict, said: str, p: PickerPaint, no_tui: str = '') -> str:
    """Screen 2 in colour (F109): the run page's keys as buttons, the link in blue."""
    left, up = left_words(row), (row['run'] or {}).get('up')
    slots = slots_words(row['run']) if up else ''
    status = ' · '.join([p.c('green', '● run up') if up else p.c('dim', 'not running')]
                        + ([p.c('green', slots)] if slots else [])
                        + ([p.c('yellow' if row.get('stopping') else 'dim', left)] if left else []))
    link = f'\x1b[4;{p.code("bblue")}m{row["link"]}{RESET}' if row['link'] else \
        p.c('dim', no_link_words(row))
    button = lambda k, label: p.c('dim', '[') + p.key(k) + f' {label}' + p.c('dim', ']')  # noqa: E731
    out = [p.c('accent', row['name'], True) + ' ' + button('0', 'all runs') + '  ' + p.c('dim', str(row['root'])),
           status, *(p.c('yellow', w) for w in warnings_of(row)), link, '',
           '  '.join(button(k, label) for k, label in launcher_keys(row, no_tui)),
           '', *([p.c('dim', no_tui), ''] if no_tui else [])]
    if said:
        out += [said, '']
    out += [p.hints([('⏎', enter_words(no_tui))], ('q', 'back')), p.c('dim', 'status · attach · stop · control: agent-runner --help')]
    return '\n'.join(out) + '\n'


def picker_text(rows: list[dict], sel: int, paint: PickerPaint | None = None, hint: str = '') -> str:
    """Screen 1, the run picker: one numbered row per run, the selected one marked (F109: in colour with
    `paint`, else bold and dim). `hint`: a line over the keys (F194c, demo.hint)."""
    if paint is not None:
        return picker_text_painted(rows, sel, paint, hint)
    out = [f'{BOLD}agent-runner · pick a run{RESET}', '']
    if not rows:
        out.append('  no run is up on this device; start one from inside a project: agent-runner, then Enter and s')
    for i, r in enumerate(rows):
        up = (r['run'] or {}).get('up')
        what = ' · '.join(x for x in (slots_words(r['run']) if up else '(not running)', left_words(r)) if x)
        mark = '>' if i == sel else ' '
        line = f'{mark} {i + 1}  {r["name"]:<16} {what:<28} {r["root"]}' + ('  here' if r['here'] else '')
        out += [f'{BOLD}{line}{RESET}' if i == sel else line, *(f'     {w}' for w in warnings_of(r))]
    out += ['', hint] if hint else []
    out += ['', f'{DIM}j/k or arrows move · 1-9 picks · Enter picks · q quits{RESET}']
    return '\n'.join(out) + '\n'


def no_link_words(row: dict) -> str:
    return 'no run page link (`status` says why)' if (row['run'] or {}).get('up') else 'no run page yet'


def launcher_keys(row: dict, no_tui: str = '') -> list[tuple[str, str]]:
    """The launcher's keys and labels: F402a s while the run is not up, t only where there is a TUI."""
    return ([] if (row['run'] or {}).get('up') else [('s', 'start the run')]) + [('w', 'open the run page')] \
        + ([] if no_tui else [('t', 'terminal UI')]) + [('c', 'copy the link')]


def enter_words(no_tui: str) -> str:
    return 'open the run page' if no_tui else 'terminal UI'


def launcher_text(row: dict, said: str = '', paint: PickerPaint | None = None, no_tui: str = '') -> str:
    """Screen 2, the launcher for the picked project: its run's status (F402a: not running while it is not up), its
    run page link, the keys, the dim footer. `no_tui`: why there is no TUI here (`tui.refusal`), '' when there is."""
    if paint is not None:
        return launcher_text_painted(row, said, paint, no_tui)
    up = (row['run'] or {}).get('up')
    status = ' · '.join(x for x in ('● run up' if up else 'not running', slots_words(row['run']) if up else '',
                                    left_words(row)) if x)
    more = {'w': ' in the browser', 't': ' (agent-runner ui)'}
    out = [f'{BOLD}{row["name"]}{RESET} [0 all runs]  {row["root"]}', status, *warnings_of(row),
           row['link'] or f'{DIM}{no_link_words(row)}{RESET}', '',
           *(f'  {k}  {"open the " if k == "t" else ""}{label}{more.get(k, "")}' for k, label in launcher_keys(row, no_tui)),
           f'  q  back · ⏎ {enter_words(no_tui)}', '', *([f'{DIM}{no_tui}{RESET}', ''] if no_tui else [])]
    out += [said, ''] if said else []
    out.append(f'{DIM}status · attach · stop · control: agent-runner --help{RESET}')
    return '\n'.join(out) + '\n'


def read_key() -> str:
    """One key, read raw: a digit or letter as itself, 'up', 'down', 'enter', 'esc'; '' for anything else."""
    if plat.WINDOWS:
        import msvcrt
        ch = msvcrt.getwch()
        if ch in ('\x00', '\xe0'):
            return {'H': 'up', 'P': 'down'}.get(msvcrt.getwch(), '')
    else:
        import select
        import termios
        import tty
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            ch = os.read(fd, 1).decode('utf-8', 'replace')
            if ch == '\x1b':
                seq = ''
                while select.select([fd], [], [], 0.05)[0] and len(seq) < 8:
                    seq += os.read(fd, 1).decode('utf-8', 'replace')
                return {'[A': 'up', 'OA': 'up', '[B': 'down', 'OB': 'down'}.get(seq, 'esc' if not seq else '')
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
    if ch in ('\r', '\n'):
        return 'enter'
    if ch == '\x1b':
        return 'esc'
    if ch == '\x03':
        raise KeyboardInterrupt
    return ch


def pick_run(rows: list[dict], key=read_key, show=None, paint: PickerPaint | None = None, hint: str = '') -> int | None:
    """Screen 1: the index of the run picked (a digit, or Enter on the selection), None when q or Esc quit.
    Starts on row 1 (the current folder's project when there is one)."""
    show = show or (lambda s: (sys.stdout.write(CLEAR + s), sys.stdout.flush()))
    sel = 0
    while True:
        show(picker_text(rows, sel, paint, hint))
        k = key()
        if k in ('q', 'esc'):
            return None
        if not rows:
            continue
        if k in ('j', 'down'):
            sel = min(sel + 1, len(rows) - 1)
        elif k in ('k', 'up'):
            sel = max(sel - 1, 0)
        elif k == 'enter':
            return sel
        elif k.isdigit() and 1 <= int(k) <= len(rows):
            return int(k) - 1


def open_link(url: str) -> str:
    import webbrowser
    return 'opened in the browser' if webbrowser.open(url) else f'no browser here: {url}'


def wayland_env() -> dict | None:
    """F117: the environment for wl-copy when WAYLAND_DISPLAY is unset (a tmux pane, a process started without
    it) but a Wayland socket is in $XDG_RUNTIME_DIR; None to keep the environment as it is."""
    run_dir = os.environ.get('XDG_RUNTIME_DIR')
    if os.environ.get('WAYLAND_DISPLAY') or not run_dir:
        return None
    socks = sorted(p.name for p in Path(run_dir).glob('wayland-*') if not p.name.endswith('.lock'))
    return {**os.environ, 'WAYLAND_DISPLAY': socks[0]} if socks else None


def osc52_copy(url: str, out=None) -> bool:
    """F117: the link to the terminal's clipboard as OSC 52, wrapped for tmux when TMUX is set; False when
    there is no terminal to write to."""
    import base64
    out = out or sys.stdout
    try:
        if not out.isatty():
            return False
        seq = f'\x1b]52;c;{base64.b64encode(url.encode("utf-8")).decode("ascii")}\x07'
        if os.environ.get('TMUX'):
            # plain for tmux's set-clipboard, then wrapped for passthrough (tmux 3.3+ needs allow-passthrough)
            seq += '\x1bPtmux;' + seq.replace('\x1b', '\x1b\x1b') + '\x1b\\'
        out.write(seq)
        out.flush()
        return True
    except (OSError, ValueError, AttributeError):
        return False


def copy_link(url: str, out=None) -> str:
    """The link on this machine's clipboard (wl-copy, xclip, pbcopy or clip, the first that works; wl-copy
    given the Wayland socket when WAYLAND_DISPLAY is unset); else to the terminal as OSC 52; else the link
    itself to copy by hand."""
    for argv in (['wl-copy'], ['xclip', '-selection', 'clipboard'], ['pbcopy'], ['clip']):
        if exe := shutil.which(argv[0]):
            try:
                # B150: run what `which` found: on Windows a bare name starts only an .exe, not a .bat or .cmd
                # B153: no captured pipes; wl-copy forks a daemon that holds them open, and a capture waits
                # for it until the timeout.
                if not sp.run([exe, *argv[1:]], input=url.encode('utf-8'), stdout=sp.DEVNULL, stderr=sp.DEVNULL, timeout=5,
                              env=wayland_env() if argv[0] == 'wl-copy' else None).returncode:
                    return 'link copied'
            except (OSError, sp.SubprocessError):
                continue
    if osc52_copy(url, out):
        return 'link copied (terminal)'
    return f'no clipboard tool here (wl-copy, xclip, pbcopy, clip): {url}'


PICK = 'pick a run'  # B153: what the launcher's t says when 0 in the TUI went back to the pick-a-run screen


def open_ui(root: Path) -> str:
    """The launcher's t: the TUI, or F141 why this machine has none (the launcher would clear what `ui` prints)."""
    from agent_runner.tui import PICK_RC, PICKER_ENV, refusal
    if why := refusal():
        link = run_facts(root, {'up': True})['link'] if plat.WINDOWS else ''
        return f'{why} {link}'.rstrip()
    rc = sp.call([*runner_cmd(), 'ui'], cwd=str(root), env=dict(os.environ, **{PICKER_ENV: '1'}))
    return PICK if rc == PICK_RC else ''


def home_link(root: Path) -> str:
    """F402a: Runner Home's /p/KEY/ for the project at `root` while no run serves its page; '' when Home does not
    route it: then the page-only process's (F402b1), while one serves."""
    from agent_runner.home import site_links
    return (site_links(root) or page_only.links(root) or [''])[0]


def start_row(root: Path) -> str:
    """F402a: the launcher's s: start the run of the project at `root` (`cmd_background`, from its own checkout); ''
    once it is up, else why not. Only stderr is kept for that: a question `remote_ready` asks stays on screen."""
    err, repo, was = io.StringIO(), os.environ.pop('AGENT_RUNNER_REPO', None), os.getcwd()
    try:
        os.chdir(root)
        with redirect_stderr(err):
            rc = cmd_background([], by='picker')
    except SystemExit as e:
        rc, _ = 1, err.write(str(e))
    except OSError as e:
        rc, _ = 1, err.write(f'the run did not start: {e}')
    finally:
        os.chdir(was)
        if repo is not None:
            os.environ['AGENT_RUNNER_REPO'] = repo
    return (err.getvalue().strip() or 'the run did not start') if rc else ''


def started_row(row: dict, since: str) -> None:
    """F402a: `row` read again after s. A STATE from before `since` is an earlier run's (a new run writes its own on
    its first tick), so only that it is up is taken from it."""
    root = Path(row['root'])
    run = run_info(root)
    if run.get('up') and str(run.get('at') or '') < since:
        run = {'up': True}
    row.update({'run': run, **run_facts(root, run)})


LAUNCHER_ACTIONS = {'w': open_link, 'c': copy_link, 't': open_ui, 's': start_row, 'page': lambda root: page_only.open_page(root, open_link)}


def launch(row: dict, key=read_key, show=None, actions=None, paint: PickerPaint | None = None) -> str:
    """Screen 2 for the picked project: w, t and c act and stay, Enter as t (F117); F402a: s starts its run while
    it is not up, and no other key does; with no TUI here no t, and Enter as w. 'back' for q or Esc, and B153
    for 0 (the project name's key) or 0 in the TUI t opened. B153: drawn to the terminal, the project's name is
    the window title until it goes back."""
    title = show is None
    show = show or (lambda s: (sys.stdout.write(CLEAR + s), sys.stdout.flush()))
    acts = {**LAUNCHER_ACTIONS, **(actions or {})}
    said = ''
    from agent_runner.tui import refusal
    no_tui = refusal()
    if title:
        from agent_runner.tui import window_title
        sys.stdout.write(window_title(f'{row["name"]} · runner'))
    try:
        while True:
            up = (row['run'] or {}).get('up')
            if not up and not row.get('link'):
                row['link'] = home_link(Path(row['root']))
            show(launcher_text(row, said, paint, no_tui))
            k = key()
            if k in ('q', 'esc', '0'):
                return 'back'
            if k == 'enter':
                k = 'w' if no_tui else 't'
            if k == 's' and not up:
                show(launcher_text(row, 'starting the run…', paint, no_tui))
                since = dt.datetime.now().isoformat(timespec='seconds')
                said = acts['s'](Path(row['root'])) or ''
                started_row(row, since)
                if not said and not row['run'].get('up'):
                    said = 'the run started and ended again; its run log says why'
            elif k == 't' and not no_tui:
                said = acts['t'](Path(row['root'])) or ''
                if said == PICK:
                    return 'back'
            elif k == 'w' and not up:
                show(launcher_text(row, 'opening the run page…', paint, no_tui))
                said, row['link'] = (got := acts['page'](Path(row['root'])))[0], got[1] or row['link']
            elif k in ('w', 'c'):
                said = acts[k](row['link']) if row['link'] else 'no run page link to use' if up else no_link_words(row)
    finally:
        if title:
            from agent_runner.tui import TITLE_BACK
            sys.stdout.write(TITLE_BACK)
            sys.stdout.flush()


def cmd_pick(here: Path | None, key=read_key, show=None, actions=None, sessions=None, paint=None, hint: str = '') -> int:
    """F91: bare `agent-runner` at a terminal. Screen 1 picks a run (the current folder's project first,
    also when its run is not up); screen 2, the launcher, opens its run page, its terminal UI or copies the link,
    and F402a starts a run that is not up only on its s. q on screen 2 goes back to screen 1. F109: drawn to the terminal (no `show`), both screens take the
    run page's colours (`picker_paint`)."""
    rows = picker_rows((sessions or device_sessions)(), here)
    if here is None and rows:  # F194c: a run is up on this device: no first time
        hint = ''
    if paint is None and show is None:
        paint = picker_paint(here)
    while True:
        i = pick_run(rows, key, show, paint, hint)
        if i is None:
            return 0
        if sessions is None:  # F402a: s is offered by what the run is now, not when the picker opened
            run = run_info(Path(rows[i]['root']))
            rows[i].update({'run': run, **run_facts(Path(rows[i]['root']), run)})
        launch(rows[i], key, show, actions, paint)
