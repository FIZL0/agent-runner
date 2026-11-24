"""F202a: a run that is up reads runner.toml and runner.local.toml again when they change, with no restart."""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest import mock

from _check import check, eq, git, report

os.environ.pop('CLAUDE_CODE_SESSION_ID', None)  # not the session running this

from agent_runner import config, control as K, loop as L, runner as R, slots as SL, state as S, settings_live as SV, ui_model as U, watch as WT  # noqa: E402

LOGS: list[str] = []
SV.SETTINGS_STILL = 0.01


def run_of(toml: str = '', once: bool = False, model: str | None = None) -> tuple[Path, L.Run]:
    """A run on a repo of its own with `toml`, as `run()` sets it up before its first tick."""
    d = Path(tempfile.mkdtemp(prefix='agent-runner-settings-live-'))
    git(d, 'init', '-q')
    (d / '.gitignore').write_text('.runner/\nrunner.local.toml\n')
    (d / 'runner.toml').write_text(toml)
    git(d, 'add', '-A')
    git(d, 'commit', '-qm', 'start')
    R.init(d)
    S.share(SLOTS=S.C.run['slots'])
    SV.start()
    a = argparse.Namespace(model=model, force=False)
    LOGS.clear()
    return d, L.Run(a, SL.SLOTS, once, 'main', model or S.C.run['model'], 30, 1200, 60)


def wait(ok, what: str) -> None:
    end = time.monotonic() + 30
    while not ok() and time.monotonic() < end:
        time.sleep(0.02)
    check(ok(), what, LOGS)


def test_takes_changes() -> None:
    print('a change in either file is taken between ticks, by everyone who holds the config')
    d, run = run_of('[run]\nslots = 2\n')
    c, r = S.C, S.C.run
    SV.take(run)
    eq(LOGS, [], 'nothing changed: nothing read')
    (d / 'runner.toml').write_text('[run]\nslots = 4\nweekly_max = 50\nauto_upgrade = false\n[ui]\ntheme = "light"\n'
                                   '[models]\ncode = "sonnet"\n')
    SV.take(run)
    check(S.C is c and config.cfg(d) is c and L.C is c and WT.C is c, 'the config is the same object everywhere')
    eq((c.run['weekly_max'], run.r['weekly_max'], c.raw['ui']['theme']), (50, 50, 'light'), 'caps and the rest')
    eq((L.SLOTS, WT.SLOTS, SL.SLOTS), (4, 4, 4), 'the slot count')
    eq((run.model, WT.AUTO_UPGRADE[0]), ('sonnet', False), 'the model of new tasks, auto upgrade')
    eq(r['weekly_max'], 90, 'what is under way goes on with the values it took')
    check(any('now in force' in x and '[run] weekly_max = 50' in x for x in LOGS), 'said', LOGS)
    (d / 'runner.local.toml').write_text('[run]\nweekly_max = 40\n')
    SV.take(run)
    eq(S.C.run['weekly_max'], 40, 'a new runner.local.toml')
    (d / 'runner.local.toml').unlink()
    SV.take(run)
    eq(S.C.run['weekly_max'], 50, 'and its removal')
    S.share(SLOTS=7)  # the + key
    (d / 'runner.toml').write_text('[run]\nslots = 4\nweekly_max = 60\n')
    SV.take(run)
    eq(L.SLOTS, 7, 'another key leaves the slot count a key set')
    d, run = run_of(once=True, model='haiku')
    S.C.run['model_flag'] = 'haiku'
    (d / 'runner.toml').write_text('[run]\nslots = 5\n[models]\ncode = "sonnet"\n')
    SV.take(run)
    eq((L.SLOTS, run.model, S.C.run['model_flag']), (3, 'haiku', 'haiku'), '`run once` and `--model` hold')


def test_comments_only() -> None:
    print('a file that changes no value (the runner.local.toml a start makes) leaves the run as it is')
    d, run = run_of()
    r = S.C.run
    config.ensure_local(d)
    SV.take(run)
    check(S.C.run is r and not LOGS, 'nothing is taken or said', LOGS)


def test_bad_kept() -> None:
    print('a file that does not parse, or a bad value: the old settings stay, said once, and the fix is taken')
    d, run = run_of('[run]\nweekly_max = 70\n')
    for bad in ('[run\nweekly_max = 1\n', '[run]\nweekly_max = 60\nslots = "four"\n', '[run]\nweekly_max = 60\nslots = 0\n',
                '[run]\nweekly_max = 60\nremote = "maybe"\n', 'run = 3\n', '[run]\nweekly_max = 60\nweb_port = 0\n',
                '[models]\ncode = "nope:"\n', '[run]\nagent = "pi"\n', '[run]\nagent = "no-such-agent-cli"\n'):
        for f in ('runner.toml', 'runner.local.toml'):
            LOGS.clear()
            (d / f).write_text(bad)
            SV.take(run)
            SV.take(run)
            eq((S.C.run['weekly_max'], S.C.run['slots'], L.SLOTS), (70, 3, 3), f'{f}: {bad!r} changes nothing')
            eq([x[:30] for x in LOGS], ['settings: changed, but not tak'], 'said once')
            check(len(LOGS[0]) > 70, 'and why', LOGS)
            (d / f).write_text('[run]\nweekly_max = 70\n')
            SV.take(run)
    (d / 'runner.toml').write_text('[run]\nweekly_max = 65\n')
    (d / 'runner.local.toml').unlink()
    SV.take(run)
    eq(S.C.run['weekly_max'], 65, 'the next good file is taken')
    with mock.patch.object(SV, 'SETTINGS_STILL', 0), S.LANDING:
        (d / 'runner.toml').write_text('')
        SV.take(run)
        eq(S.C.run['weekly_max'], 65, 'not while a merge moves the checkout')
    SV.take(run)
    eq(S.C.run['weekly_max'], 90, 'but once it is done')


def test_next_run() -> None:
    print('what cannot change live is kept, and is all the page lists as waiting')
    d, run = run_of('[run]\nnotes = ".runner"\n')
    home, notes = S.C.home, S.C.notes('x')
    (d / 'runner.local.toml').write_text('[run]\nweb_port = 9001\nhome = "/nowhere"\nnotes = "elsewhere"\nsession_max = 33\n'
                                         '[plan]\ndir = "other"\n[git]\nmaster_branch = "gone"\nno_push = true\n')
    SV.take(run)
    eq((S.C.run['session_max'], S.C.run['web_port'], S.C.home, S.C.notes('x'), S.C.plan_dir, S.C.master_branch),
       (33, 8770, home, notes, d / 'plan', None), 'the rest of the file is in force')
    eq(sorted(U.settings()['waits']), ['git.master_branch', 'git.no_push', 'plan.dir', 'run.home', 'run.notes', 'run.web_port'], 'waits')
    check(not S.C.no_push, 'the policy is not half on')
    check(any('waits for the next run' in x and '[run] web_port' in x and 'session_max' not in x for x in LOGS), 'said', LOGS)
    git(d, 'worktree', 'add', '-q', '--detach', str(wt := d.parent / (d.name + '-wt')))
    eq((config.cfg(wt).notes('x'), config.cfg(wt).run['session_max']), (notes, 33), 'the same in a worktree')
    applies = {f'{t["table"]}.{k["key"]}': k['applies'] for t in config.settings_snapshot(d)['tables'] for k in t['keys']}
    eq({k for k, v in applies.items() if v == 'next run'}, {f'{t}.{k}' for t, k in config.SETTING_NEXT}, 'applies says so')
    eq(applies['run.slots'], 'now', 'and now for the others')
    config._cfg.cache_clear()
    for bad in ('[run\n', '[run]\ncommand_timeout = "x"\n'):
        (d / 'runner.local.toml').write_text(bad)
        got = config.cfg(wt)
        eq((got.run['session_max'], got.run['command_timeout'], got.root), (33, 3600, wt.resolve()), 'a worktree read while a file is bad')
        config._cfg.cache_clear()
    (d / 'runner.local.toml').unlink()
    SV.take(run)
    eq((U.settings()['waits'], config.cfg(d).run['session_max']), ([], 90), 'set back: nothing waits')


def test_running_keep() -> None:
    print('a running task keeps the model and the budget it has')
    d, run = run_of('[run]\ntask_tokens = 1000\n[models.kinds]\nF = "opus"\n')
    run.running, run.procs = {1: ('F1', '', set(), set())}, {1: (os.getpid(), 'sid-live-1', 0.0)}
    (d / 'runner.toml').write_text('[run]\ntask_tokens = 10\n[models.kinds]\nF = "haiku"\n')
    SV.take(run)
    eq(SV.KEPT['sid-live-1'], ('opus', (1000, 0)), 'its own')
    eq((SL.task_model('F2', run.model, 'main'), S.C.run['task_tokens']), ('haiku', 10), 'a new one has the new')
    with mock.patch.object(os, 'execv') as ex, mock.patch.dict(os.environ):
        WT.restart_run()
        eq((L.kept_keys()['kept']['sid-live-1'], ex.call_count), (['opus', [1000, 0]], 1), 'a restart in place hands it on')
    told: list = []
    run.procs[2], run.running[2] = (os.getpid(), 'sid-live-2', 0.0), ('F2', '', set(), set())
    SL.BUDGET_AT[0] = 0.0
    with mock.patch.object(SL, 'task_spend', lambda sid: (12, 0.0)):
        SL.budgets(run.procs, run.running, lambda n, procs, text: told.append(n))
    eq(told, [2], 'only the new one is past its budget')
    (d / 'runner.toml').write_text('[run]\ntask_tokens = 5\n[models.kinds]\nF = "sonnet"\n')
    SV.take(run)
    eq(SV.KEPT['sid-live-1'], ('opus', (1000, 0)), 'a second change too')


def test_remote_and_silent() -> None:
    print('[run] remote off ends the control server, on starts it; silent reaches the sessions that are up')
    d, run = run_of('[run]\nremote = true\n')
    argv = [sys.executable, '-c', 'import time; time.sleep(120)', 'remote-control']

    def server_up():
        return K.control_server_live()

    def write(text):
        (d / 'runner.toml').write_text(text)
        SV.take(run)
    quiet = S.C.notes('quiet-server')
    (S.C.notes('control2.live')).write_text('1')
    pids: list[int] = []
    with mock.patch.object(K, 'control_server_argv', lambda: argv), mock.patch.object(K, 'server_stale', lambda a: False), \
            mock.patch.object(K, 'backend', mock.MagicMock()), mock.patch('atexit.register', lambda f: f), \
            mock.patch.object(K, 'CONTROL_SERVER_WAIT', (600, 600)):
        try:
            K.start_control_server()
            for off, on in (('[run]\nremote = false\n', '[run]\nremote = true\n'),
                            ('[run]\nremote = true\ncontrol = false\n', '[run]\nremote = true\n')):
                wait(server_up, 'the control server is up')
                pids.append(server_up())
                write(off)
                wait(lambda: not K.SERVER_TURN[0][0].is_alive(), f'{off!r} ends its thread')
                check(not R.plat.alive(pids[-1]) and not R.rc_records(), 'and the server and its record', LOGS)
                write(on)
            wait(server_up, 'and on again starts one')
            check(server_up() not in pids, 'a new one')
            pids.append(server_up())
            write('[run]\nremote = true\nweekly_max = 20\n')
            eq((server_up(), len(K.SERVER_TURN)), (pids[-1], 1), 'another key leaves it')
            check(not quiet.exists(), 'not silent')
            write('[run]\nremote = true\nsilent = true\n')
            check(quiet.exists() and S.C.notes('quiet-c2').exists(), 'silent')
            write('[run]\nremote = true\n')
            check(not quiet.exists() and not S.C.notes('quiet-c2').exists(), 'and not again')
            write('[run]\nremote = false\n')
            wait(lambda: not K.SERVER_TURN[0][0].is_alive(), 'and ended')
            K.SERVER_TURN.clear()  # a run that started with remote off has none
            write('[run]\nremote = true\n')
            wait(server_up, 'on starts one there')
            pids.append(server_up())
            write('[run]\nremote = false\n')
            wait(lambda: not K.SERVER_TURN[0][0].is_alive(), 'and off ends it')
        finally:
            for t, off in K.SERVER_TURN:
                off.set()
                t.join(30)


def test_tick() -> None:
    print('the loop reads them on its tick, and a new slot count opens the slots')
    d, run = run_of('[run]\nslots = 1\n')
    (d / 'runner.toml').write_text('[run]\nslots = 3\n')
    with mock.patch.object(L, 'sweep_tmp', lambda *a, **k: None), mock.patch.object(L, 'prune_wips', lambda *a, **k: None):
        run.top()
    eq((run.slots, sorted(run.free_at)), (3, [1, 2, 3]), 'slots 2 and 3 are open')


if __name__ == '__main__':
    for m in list(sys.modules.values()):
        if getattr(m, '__name__', '').startswith('agent_runner.') and hasattr(m, 'log') and callable(m.log):
            m.log = lambda msg, *a, **k: LOGS.append(msg)
    raise SystemExit(report([test_takes_changes, test_comments_only, test_bad_kept, test_next_run, test_running_keep,
                             test_remote_and_silent, test_tick]))
