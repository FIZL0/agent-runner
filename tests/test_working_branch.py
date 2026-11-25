"""F447b: a save of the working branch ([git] master_branch): what is refused, and the switch at the run's next start."""
from __future__ import annotations

import tempfile
import tomllib
from pathlib import Path
from unittest import mock

from _check import check, eq, git, has, report, run

from agent_runner import config, loop as L, pr, state as S, ui_model as U, working_branch as W

U.SETTING_SETTLE = 0.01
TODO = '# TODO\n\n## Queue\n\n- [ ] **F1** (normal) Do one thing. | files: one.txt\n'


def out(d: Path, *a: str) -> str:
    return git(d, *a).strip()


def project(toml: str = '[run]\ntest = "true"\n[git]\npush = false\n') -> Path:
    d = Path(tempfile.mkdtemp(prefix='agent-runner-working-branch-')).resolve()
    git(d, 'init', '-q')
    (d / 'plan').mkdir()
    (d / 'plan' / 'TODO.md').write_text(TODO, encoding='utf-8')
    (d / 'plan' / 'DONE.md').write_text('# DONE\n', encoding='utf-8')
    (d / '.gitignore').write_text('.runner/\nrunner.local.toml\n', encoding='utf-8')
    (d / 'runner.toml').write_text(toml, encoding='utf-8')
    git(d, 'add', '-A')
    git(d, 'commit', '-qm', 'start')
    git(d, 'branch', 'bare')
    git(d, 'checkout', '-q', '-b', 'dev')
    (d / 'dev.txt').write_text('dev\n', encoding='utf-8')
    git(d, 'add', '-A')
    git(d, 'commit', '-qm', 'on dev')
    git(d, 'checkout', '-q', 'bare')
    git(d, 'rm', '-q', 'plan/TODO.md')
    git(d, 'commit', '-qm', 'no task list')
    git(d, 'checkout', '-q', 'main')
    fresh(d)
    return d


def fresh(d: Path) -> None:
    """As a process that starts now reads it."""
    W.forget()
    S.init(d)


def state_of(d: Path) -> tuple:
    files = [d / 'runner.toml', d / 'runner.local.toml', d / '.runner' / W.NOTE]
    return (*(f.read_bytes() if f.exists() else None for f in files), out(d, 'rev-parse', 'HEAD', 'dev'),
            out(d, 'branch', '--show-current'))


def test_refused() -> None:
    print('a bad pick is refused with the reason, and nothing changes')
    d = project()
    git(d, 'branch', 'task/F9')
    git(d, 'branch', 'away')
    git(d, 'worktree', 'add', '-q', str(d.parent / (d.name + '-wt')), 'away')
    before = state_of(d)
    for save in (U.setting_device, U.setting_project):
        for v, why in (('gone', 'no local branch gone'), ('a b', 'not a valid branch name'), ('-x', 'not a valid'),
                       ('@{-1}', 'not a valid'), (' dev', 'spaces around'), (5, 'must be text'), ('bare', r'has no plan/TODO\.md'),
                       ('task/F9', "runner's own"), ('away', 'is checked out in')):
            r = save('git', 'master_branch', v)
            eq((r['ok'], state_of(d)), (False, before), f'{save.__name__} refuses {v!r}')
            has(r['out'], why, 'and says why')
    r = U.settings_save([{'table': 'git', 'key': 'master_branch', 'side': 'project', 'value': 'gone'}])
    eq((r['ok'], state_of(d)), (False, before), "the page's Save too")
    has(r['bad'][0]['why'], 'no local branch gone', 'with the reason')
    (d / 'runner.toml').write_text('[run]\ntest = "false"\n', encoding='utf-8')
    before = state_of(d)
    r = U.setting_project('git', 'master_branch', 'dev')
    eq((r['ok'], state_of(d)), (False, before), 'a save that cannot be written leaves no switch behind')
    git(d, 'checkout', '-q', '--', 'runner.toml')
    git(d, 'branch', '-q', 'old')
    (d / 'runner.toml').write_text('[run]\ntest = "true"\n[git]\nmaster_branch = "old"\npush = false\n', encoding='utf-8')
    git(d, 'commit', '-qam', 'old')
    (d / 'runner.local.toml').write_text('[git]\nmaster_branch = "main"\n', encoding='utf-8')
    git(d, 'branch', '-D', 'old')
    fresh(d)
    before = state_of(d)
    r = U.setting_reset('git', 'master_branch')
    eq((r['ok'], state_of(d)), (False, before), 'a reset to a branch that is gone')
    has(r['out'], 'no local branch old', 'and says why')


def test_pr_mode() -> None:
    print('PR mode: a branch GitHub does not protect is refused')
    d = project()
    with mock.patch.object(pr, 'branch_problem', lambda c, root, b: f'{b} has no branch protection on GitHub'):
        config.Config.pr, was = property(lambda c: True), config.Config.__dict__['pr']
        try:
            (d / 'runner.toml').write_text('[git]\nmaster_branch = "dev"\n', encoding='utf-8')
            tip = out(d, 'rev-parse', 'dev')
            has(W._carry(d, 'dev'), 'in a pull request', 'nor is the setting committed to the branch by the runner')
            eq(out(d, 'rev-parse', 'dev'), tip, 'it has not moved')
            has(W.problem(d, 'dev'), 'PR mode could not go on with dev: dev has no branch protection', 'said')
        finally:
            config.Config.pr = was


def test_waits() -> None:
    print('a save moves nothing until a start, and everything goes on as before')
    for save, name in ((U.setting_project, 'runner.toml'), (U.setting_device, 'runner.local.toml')):
        d = project()
        r = save('git', 'master_branch', 'dev')
        eq((r['ok'], tomllib.loads((d / name).read_text())['git']['master_branch']), (True, 'dev'), f'saved in {name}')
        has(r['out'], 'the working branch stays main until the run starts again: then dev is checked out', 'and says what happens')
        eq(out(d, 'branch', '--show-current'), 'main', 'the main checkout stays')
        fresh(d)
        eq((S.default_branch(), S.C.master_branch), ('main', None), 'another process goes on with main')
        eq(run(d, 'run', '--dry-run').returncode, 0, 'a dry run starts, and switches nothing')
        eq(out(d, 'branch', '--show-current'), 'main', 'still there')
        row = next(k for t in U.settings()['tables'] for k in t['keys'] if k['key'] == 'master_branch')
        eq((row['value'], row['now'], row['next'], row['held']), ('dev', 'main', 'dev', []), 'the page is told')
        check('git.master_branch' in U.settings()['waits'], 'it waits for the next run')
        eq(save('git', 'master_branch', 'main')['ok'], True, 'taken back')
        fresh(d)
        check(not W.pending(d) and S.default_branch() == 'main', 'and nothing waits')
        save('git', 'master_branch', 'dev')
        save('git', 'master_branch', '')
        check(not (d / '.runner' / W.NOTE).exists(), 'also as it was: found by itself')


def test_picks() -> None:
    print('the snapshot has the picks')
    d = project()
    git(d, 'branch', 'wip/F3')
    row = next(k for t in U.settings()['tables'] for k in t['keys'] if k['key'] == 'master_branch')
    eq([(p['value'], p['branch'], p['auto']) for p in row['picks']],
       [('', 'main', True), ('bare', 'bare', False), ('dev', 'dev', False), ('main', 'main', False)],
       "found by itself, with the branch now, then the local branches but the runner's own")
    eq((row['now'], 'next' in row), ('main', False), 'the branch now, nothing waits')
    (d / 'runner.local.toml').write_text('[git]\nmaster_branch = "gone"\n', encoding='utf-8')
    row = next(k for t in U.settings()['tables'] for k in t['keys'] if k['key'] == 'master_branch')
    has(row['picks'][-1]['bad'], 'no local branch gone', 'a kept value that is none of them says what is wrong')


def test_switch() -> None:
    print('the next start switches; the next task starts from it and lands on it')
    for save in (U.setting_project, U.setting_device):
        d = project()
        save('git', 'master_branch', 'dev')
        main = out(d, 'rev-parse', 'main')
        fresh(d)
        eq(run(d, 'run', '--dry-run').returncode, 0, 'before')
        eq((W.waits(d), W.at_start(d)), (True, True), 'switched')
        fresh(d)
        eq((out(d, 'branch', '--show-current'), S.default_branch(), S.C.master_branch), ('dev', 'dev', 'dev'), 'on dev, which says so')
        eq((out(d, 'status', '--porcelain'), W.waits(d)), ('', False), 'clean, and nothing waits')
        if save is U.setting_project:
            eq(tomllib.loads(out(d, 'show', 'dev:runner.toml'))['git'], {'push': False, 'master_branch': 'dev'}, 'dev got the setting')
            eq(out(d, 'log', '-1', '--format=%s', 'dev'), 'settings: the working branch is dev', 'in a commit of its own')
            eq(out(d, 'diff', '--name-only', 'dev~1', 'dev'), 'runner.toml', 'of that file alone')
        r = run(d, 'take', 'F1')
        wt = S.SLOTS_DIR / 'take-F1'
        eq((r.returncode, (wt / 'dev.txt').exists()), (0, True), 'the next task starts from dev')
        (wt / 'one.txt').write_text('one\n', encoding='utf-8')
        r = run(wt, 'done', 'F1', 'F1 one thing')
        eq(r.returncode, 0, f'done: {r.stdout[-300:]}{r.stderr[-300:]}')
        r = run(d, 'take', 'F1', '--merge')
        has(r.stdout, 'F1: merged into dev', 'and lands on dev')
        eq((out(d, 'show', 'dev:one.txt'), out(d, 'rev-parse', 'main')), ('one', main), 'there, and main has not moved')
        fresh(d)
        eq(save('git', 'master_branch', 'main')['ok'], True, 'and back')
        fresh(d)
        eq(S.default_branch(), 'dev', 'dev until the start')
        eq(W.at_start(d), True, 'switched back')
        fresh(d)
        eq((S.default_branch(), out(d, 'branch', '--show-current')), ('main', 'main'), 'main again')


def test_run_start() -> None:
    print("the run's own start switches before it reads anything off the branch")
    d = project()
    U.setting_project('git', 'master_branch', 'dev')
    fresh(d)

    class Enough(Exception):
        pass
    seen = []

    def first(c, root):
        seen.append((out(root, 'branch', '--show-current'), c.master_branch, bool(L.RUN_LOCK)))
        raise Enough
    try:
        with mock.patch.object(L.no_push, 'require', first), mock.patch.object(L, 'init', lambda: S.init(d)):
            L.run([], 'run')
    except Enough:
        pass
    finally:
        while L.RUN_LOCK:
            L.RUN_LOCK.pop().close()
    eq(seen, [('dev', 'dev', True)], 'on dev, with its settings, run.lock held')


def test_held() -> None:
    print('never with uncommitted edits, or while tasks run or wait to merge: the run starts on the branch it has')
    d = project()
    U.setting_project('git', 'master_branch', 'dev')
    fresh(d)

    def held(why: str, what: str) -> None:
        logs: list[str] = []
        with mock.patch.object(S, 'log', lambda m, *a, **k: logs.append(m)):
            eq((W.at_start(d), out(d, 'branch', '--show-current'), S.default_branch()), (False, 'main', 'main'), what)
        has(' '.join(logs), why, 'and says why')
    (d / 'new.txt').write_text('mine\n', encoding='utf-8')
    held('1 uncommitted edit in the main checkout', 'an uncommitted edit')
    (d / 'new.txt').unlink()
    wt = S.SLOTS_DIR / 's1'
    git(d, 'worktree', 'add', '-q', '-b', 'task/F1', str(wt), 'main')
    held('F1 is being worked on', 'a running task, with no commit yet')
    has(U.settings_save([{'table': 'git', 'key': 'master_branch', 'side': 'device', 'value': 'dev'}])['say'],
        r'\(now: F1 is being worked on\)', 'a save says so too')
    (d / 'runner.local.toml').unlink()
    (wt / 'one.txt').write_text('one\n', encoding='utf-8')
    git(wt, 'add', '-A')
    git(wt, 'commit', '-qm', 'F1')
    git(d, 'worktree', 'remove', str(wt))
    held('F1 waits to merge', 'a finished task')
    git(d, 'branch', '-D', 'task/F1')
    with mock.patch.object(pr, 'read', lambda c=None: [{'key': 'F1'}]):
        held('F1 has a pull request', 'an open pull request')
    git(d, 'branch', '-m', 'dev', 'dev2')
    held('no local branch dev', 'the branch went meanwhile')
    eq(run(d, 'run', '--dry-run').returncode, 0, 'the run can start')
    git(d, 'branch', '-m', 'dev2', 'dev')
    eq(W.at_start(d), True, 'and the next start switches')


def other(d: Path) -> tuple[Path, Path]:
    """`d` with a remote, and another machine's clone of it (no local dev)."""
    remote = d.parent / (d.name + '-origin')
    git(d.parent, 'clone', '-q', '--bare', str(d), str(remote))
    git(d, 'remote', 'add', 'origin', str(remote))
    git(d, 'fetch', '-q')
    b = d.parent / (d.name + '-other')
    git(d.parent, 'clone', '-q', str(remote), str(b))
    return remote, b


def value_in(d: Path, v: str, msg: str) -> None:
    (d / 'runner.toml').write_text(f'[run]\ntest = "true"\n[git]\npush = false\nmaster_branch = "{v}"\n', encoding='utf-8')
    git(d, 'commit', '-qam', msg)


SAVED = 'settings: [git] master_branch = "dev"'


def test_other_machine() -> None:
    print('another machine that pulls a save for everyone switches at its next start, with the same holds')
    for how in (('pull', '-q', '--ff-only'), ('pull', '-q', '--no-rebase', '--no-edit'), ('pull', '-q', '--rebase')):
        d = project()
        _, b = other(d)
        eq(U.setting_project('git', 'master_branch', 'dev')['ok'], True, 'saved on the first machine')
        git(d, 'push', '-q', 'origin', 'main')
        if '--ff-only' not in how:
            (b / 'mine.txt').write_text('mine\n', encoding='utf-8')
            git(b, 'add', '-A')
            git(b, 'commit', '-qm', 'mine')
        fresh(b)
        check(not W.waits(b), 'nothing waits before the pull')
        git(b, *how)
        fresh(b)
        eq((S.default_branch(), S.C.master_branch, W.waits(b)), ('main', None, True), f'{how}: goes on with main, a switch waits')
        eq(W.pending(b), {'now': 'main', 'next': 'dev'}, 'to dev')
        r = run(b, 'run', '--dry-run')
        eq(r.returncode, 0, f'a command works: {r.stderr[-200:]}')
        (b / 'new.txt').write_text('mine\n', encoding='utf-8')
        eq((W.at_start(b), out(b, 'branch', '--list', 'dev')), (False, ''), 'an uncommitted edit holds it, and no branch is made')
        (b / 'new.txt').unlink()
        with mock.patch.object(W, '_switch', lambda *a: 'no'):
            eq((W.at_start(b), out(b, 'branch', '--list', 'dev')), (False, ''), 'one made for a switch that fails goes')
        eq(W.at_start(b), True, 'switched')
        fresh(b)
        eq((out(b, 'branch', '--show-current'), S.default_branch(), W.waits(b)), ('dev', 'dev', False), 'on dev, nothing waits')
        eq((out(b, 'status', '--porcelain'), (b / 'dev.txt').exists()), ('', True), "clean, with the remote's dev")
        git(b, 'checkout', '-q', 'main')
        check(not W.waits(b), 'left by hand: it is not switched again')


def test_other_machine_reset() -> None:
    print('a pulled reset to the branch found by itself switches too, and a save on that machine takes it back')
    d = project()
    git(d, 'checkout', '-q', 'dev')
    value_in(d, 'dev', 'settings: the working branch is dev')
    git(d, 'checkout', '-q', 'main')
    _, b = other(d)
    git(b, 'checkout', '-q', 'dev')
    fresh(b)
    check(not W.waits(b), 'on dev')
    git(d, 'checkout', '-q', 'dev')
    (d / 'runner.toml').write_text('[run]\ntest = "true"\n[git]\npush = false\n', encoding='utf-8')
    git(d, 'commit', '-qam', 'settings: [git] master_branch is reset')
    git(d, 'push', '-q', 'origin', 'dev')
    git(b, 'pull', '-q')
    fresh(b)
    eq((S.default_branch(), W.pending(b)), ('dev', {'now': 'dev', 'next': 'main'}), 'dev until the start')
    eq(U.setting_device('git', 'master_branch', 'dev')['ok'], True, 'this device keeps dev')
    fresh(b)
    eq((S.default_branch(), W.pending(b)), ('dev', {}), 'and nothing waits')
    (b / 'runner.local.toml').unlink()
    fresh(b)
    eq((W.at_start(b), out(b, 'branch', '--show-current')), (True, 'main'), 'without it: switched to main')


def test_by_hand() -> None:
    print('a value changed by hand is refused as before')

    def refused(b: Path, what: str) -> None:
        fresh(b)
        check(not W.waits(b), f'{what}: no switch waits')
        try:
            S.default_branch()
            check(False, f'{what}: refused')
        except SystemExit as e:
            has(str(e), 'working branch', f'{what}: refused')
    d = project()
    value_in(d, 'dev', SAVED)
    refused(d, 'committed here')
    d = project()
    git(d, 'checkout', '-q', '-b', 'side')
    value_in(d, 'dev', SAVED)
    git(d, 'checkout', '-q', 'main')
    git(d, 'merge', '-q', 'side')
    refused(d, 'merged from a branch of this machine')
    d = project()
    (d / 'runner.local.toml').write_text('[git]\nmaster_branch = "dev"\n', encoding='utf-8')
    refused(d, "this device's file")
    d = project()
    _, b = other(d)
    (b / 'runner.toml').write_text('[git]\nmaster_branch = "dev"\n', encoding='utf-8')
    git(b, 'branch', 'dev', 'origin/dev')
    refused(b, 'an edit not committed')
    git(b, 'checkout', '-q', '--', 'runner.toml')
    value_in(d, 'dev', 'use dev')
    git(d, 'push', '-q', 'origin', 'main')
    git(b, 'pull', '-q')
    refused(b, 'changed by hand on the other machine and pulled')


if __name__ == '__main__':
    raise SystemExit(report([test_refused, test_pr_mode, test_waits, test_picks, test_switch, test_run_start, test_held, test_other_machine,
                             test_other_machine_reset, test_by_hand]))
