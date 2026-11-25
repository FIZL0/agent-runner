#!/usr/bin/env python3
"""PR mode (F419, `[git] pr`): the refusals, one pull request per task (split parts together), and a person's merge.

    python3 tests/test_pr.py        (no network; some seconds of git)

Real git in a throwaway repo with a bare remote, reached by a github.com url git rewrites; `gh` is a fake that merges in
the bare remote as GitHub does.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

from _check import check, eq, git, has, report, run

from agent_runner import ci, config as CF, gitops, merge as M, plan as P, plansync, pr, runner as R  # noqa: E402
from agent_runner import sched, setup, slots, stack, state as S, ui_model as U  # noqa: E402

CF.FIXED['merge_ahead'] = False
URL = 'https://github.com/o/r.git'
TASKS = ('- [ ] **F1** one | files: a.py\n- [ ] **F2** two | files: b.py | after: F1\n'
         '- [ ] **P5a** first part | files: c.py\n- [ ] **P5b** second part | files: d.py | after: P5a\n')


def answer(argv, out='', code=0, err=''):
    return subprocess.CompletedProcess(argv, code, out if isinstance(out, str) else json.dumps(out), err)


class Gh:
    """GitHub: `protect` answers the api calls, pull requests are kept in `prs`, and `merge` is a person's."""

    def __init__(self, origin: Path | None = None, protect: dict | None = None):
        self.origin, self.prs, self.calls, self.down = origin, [], [], False
        self.protect = {'repos/o/r/rules/branches/main': [{'type': 'pull_request', 'ruleset_id': 7}],
                        'repos/o/r/rulesets/7': {'current_user_can_bypass': 'never'}} if protect is None else protect

    def __call__(self, *a):
        self.calls.append(a)
        if self.down:
            return answer(a, code=1, err='could not resolve host')
        if a[0] == 'api':
            got = self.protect.get(a[1])
            return answer(a, got) if got is not None else answer(a, code=1, err='gh: Not Found (HTTP 404)')
        opt = {a[i]: a[i + 1] for i in range(len(a) - 1) if a[i].startswith('--')}
        if a[:2] == ('pr', 'list'):
            return answer(a, [{'number': x['n'], 'url': x['url']} for x in self.prs
                              if x['head'] == opt['--head'] and x['state'] == 'OPEN'])
        if a[:2] == ('pr', 'create'):
            n = len(self.prs) + 1
            self.prs.append({'n': n, 'url': f'https://github.com/o/r/pull/{n}', 'head': opt['--head'], 'state': 'OPEN',
                             'title': opt['--title'], 'body': Path(opt['--body-file']).read_text(encoding='utf-8'),
                             'argv': a, 'commit': '', 'oid': ''})
            return answer(a, self.prs[-1]['url'] + '\n')
        x = next(x for x in self.prs if str(x['n']) == a[2])
        if a[:2] == ('pr', 'edit'):
            x['body'] = Path(opt['--body-file']).read_text(encoding='utf-8')
            return answer(a)
        if a[:2] == ('pr', 'view'):
            return answer(a, {'state': x['state'], 'baseRefName': 'main', 'headRefOid': x['oid'],
                              'mergeCommit': {'oid': x['commit']} if x['commit'] else None})
        raise AssertionError(a)

    def merge(self, n: int, how: str, work: Path) -> str:
        """A person presses GitHub's merge button."""
        x = self.prs[n - 1]
        git(work.parent, 'clone', '-q', str(self.origin), str(work))
        head = f'origin/{x["head"]}'
        x['oid'] = git(work, 'rev-parse', head)
        if how == 'merge':
            git(work, 'merge', '-q', '--no-ff', '-m', f'Merge pull request #{n}', head)
        elif how == 'squash':
            git(work, 'merge', '-q', '--squash', head)
            git(work, 'commit', '-qm', f'{x["title"]} (#{n})')
        else:
            git(work, 'commit', '-q', '--allow-empty', '-m', 'main moved')
            git(work, 'checkout', '-q', '--detach', head)
            git(work, 'rebase', '-q', 'main')
            git(work, 'checkout', '-q', '-B', 'main')
        git(work, 'push', '-q', 'origin', 'main')
        x.update(state='MERGED', commit=git(work, 'rev-parse', 'main'))
        return x['commit']


def make(tmp: Path, name: str, extra: str = '', tasks: str = TASKS, start: bool = True) -> tuple[Path, Path, Gh]:
    d = tmp / name
    d.mkdir()
    origin, plan, seed, repo = d / 'origin.git', d / 'plan.git', d / 'seed', d / name
    for b in (origin, plan):
        git(d, 'init', '-q', '--bare', '-b', 'main', str(b))
    git(d, 'clone', '-q', str(plan), str(seed))
    (seed / 'TODO.md').write_text(f'# TODO\n\n### Next\n\n{tasks}', encoding='utf-8')
    (seed / 'DONE.md').write_text('# DONE\n', encoding='utf-8')
    git(seed, 'add', '-A')
    git(seed, 'commit', '-qm', 'plan')
    git(seed, 'push', '-q', 'origin', 'HEAD:main')
    repo.mkdir()
    git(repo, 'init', '-q', '-b', 'main')
    for f in 'abcd':
        (repo / f'{f}.py').write_text('top\n', encoding='utf-8')
    (repo / 'runner.toml').write_text(
        f'[run]\ntest = "git --version"\nmin_free_gb = 0\nremote = false\nfix_merges = false\nrepair_merges = false\n'
        f'home = "{(d / "home").as_posix()}"\n[plan]\nrepo = "{plan.as_posix()}"\n[git]\npr = true\n{extra}', encoding='utf-8')
    (repo / '.gitignore').write_text('.runner/\nrunner.local.toml\n', encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'start')
    git(repo, 'remote', 'add', 'origin', URL)
    git(repo, 'config', f'url.{origin.as_posix()}.insteadOf', URL)
    git(repo, 'push', '-q', '-u', 'origin', 'main')
    if start:
        R.init(repo)
        plansync.ensure_clone(S.C)
        plansync.pull(S.C, force=True)
    pr.SAID.clear()
    return repo, origin, Gh(origin)


def said(tid: str, review: str = 'review: fixed the label') -> str:
    f = pr.pitch.part_file(tid)
    f.write_text(json.dumps({'what': f'{tid} changes it for @someone', 'why': 'faster', 'try': 'open it', 'risk': 'none known'}),
                 encoding='utf-8')
    return pr.done_problem(tid, f'{tid}: did it\n\n{review}', S.C)


def work(repo: Path, tid: str, f: str, text: str = '', finished: bool = True, start: str = 'main', finish: bool = True):
    """Task `tid` done on its branch; what `submit` says of it (unless `finish` is off)."""
    git(repo, 'checkout', '-q', '-b', f'task/{tid}', start)
    (repo / f).write_text((repo / f).read_text(encoding='utf-8') + f'{text or tid}\n', encoding='utf-8')
    git(repo, 'commit', '-qam', f'{tid}: did it')
    git(repo, 'checkout', '-q', 'main')
    if finished:
        eq(said(tid), '', f'{tid}: done takes it')
        (plansync.ticks(S.C) / tid).touch()
    return M.merge(tid, 'main') if finish else None


def boxes() -> dict[str, str]:
    return {t: b for _, b, t, _, _ in P.iter_tasks(P.lines(S.C.todo) + P.lines(S.C.done))}


def using(gh):
    return mock.patch.object(ci, 'gh_in', lambda cwd: gh)


# --- refusals --------------------------------------------------------------------------------------------------

def test_refusals(tmp: Path):
    print('what PR mode is refused without')
    repo, origin, gh = make(tmp, 'ref')
    why = lambda g=gh, **kw: pr.problem(mock.Mock(**{'push_remote': 'origin', 'plan_repo': '/p.git', 'plan_external': True,  # noqa: E731
                                                     'master_branch': 'main', **kw}), repo, g)
    eq(pr.problem(S.C, repo, gh), '', 'a protected main, a plan of its own: it may be on')
    pr.require(S.C, repo, gh)
    has(why(push_remote=None), 'nothing is pushed', 'no push remote')
    has(why(plan_repo=''), r'needs \[plan\] repo', 'no plan repo')
    has(why(plan_external=False), r'needs \[plan\] repo', 'a plan inside the repository')
    has(why(plan_repo='git@github.com:O/r.git'), 'is this repository', 'the plan in this very repository')
    has(why(push_remote='gone'), 'no remote gone', 'no such remote')
    git(repo, 'remote', 'add', 'lab', 'https://gitlab.com/o/r.git')
    has(why(push_remote='lab'), 'GitHub only', 'not GitHub')

    ask = lambda protect: why(Gh(protect=protect))  # noqa: E731
    rules, rset = 'repos/o/r/rules/branches/main', 'repos/o/r/rulesets/7'
    old = 'repos/o/r/branches/main/protection'
    down = Gh()
    down.down = True
    has(why(down), 'did not say', 'GitHub cannot be reached')
    has(ask({rules: []}), 'did not show', 'no protection the token can read')
    bare = Gh(protect={rules: []})
    has(pr.protection_problem(lambda *a: answer(a, code=1, err='gh: Branch not protected (HTTP 404)') if a[1] == old else bare(*a),
                              'o/r', 'main'), 'no branch protection', 'no protection at all')
    has(ask({rules: [{'type': 'deletion', 'ruleset_id': 7}], rset: {'current_user_can_bypass': 'never'}}), 'did not show',
        'a ruleset that requires no pull request')
    for can in ('always', 'pull_requests_only', 'exempt', None):
        has(ask({rules: [{'type': 'pull_request', 'ruleset_id': 7}], rset: {'current_user_can_bypass': can}}), 'bypass it',
            f'a ruleset the token can bypass ({can})')
    full = {'required_pull_request_reviews': {}, 'enforce_admins': {'enabled': True}}
    eq(ask({rules: [], old: full}), '', 'classic protection that holds for admins')
    has(ask({rules: [], old: {**full, 'enforce_admins': {'enabled': False}}}), 'admins', 'not for admins')
    has(ask({rules: [], old: {'enforce_admins': {'enabled': True}}}), 'does not require', 'no pull request required')
    let = lambda **k: {**full, 'required_pull_request_reviews': {'bypass_pull_request_allowances': k}}  # noqa: E731
    has(ask({rules: [], old: let(users=[{'login': 'me'}]), 'user': 'me'}), 'bypass', 'the token may bypass')
    eq(ask({rules: [], old: let(users=[{'login': 'you'}]), 'user': 'me'}), '', 'another may')
    has(ask({rules: [], old: let(teams=[{'slug': 't'}]), 'user': 'me'}), 'bypass', 'a team may, and the token may be in it')

    bad = Gh(protect={rules: []})
    with using(bad):
        try:
            pr.require(S.C, repo)
            check(False, 'the start refuses')
        except SystemExit as e:
            has(str(e), r'PR mode \(\[git\] pr = true\) is refused: ', 'the start refuses, saying why')
        with mock.patch.object(setup, 'launch', side_effect=AssertionError('no session')), \
                mock.patch.object(setup, 'offer_ttyd', return_value=None), mock.patch('sys.stderr') as err:
            eq(setup.main(['--yes'], repo), 1, 'setup refuses')
        has(''.join(c.args[0] for c in err.write.call_args_list), 'is refused: ', 'setup says why')
    has(Path(R.__file__).with_name('loop.py').read_text(encoding='utf-8'), r'^    pr\.require\(C, ROOT\)', 'the run start asks')


def test_approve(tmp: Path):
    print('approve and pr refuse each other')
    repo, _, _ = make(tmp, 'both')
    eq(CF.DEFAULTS['git']['pr'], False, 'off by default')
    has(CF.setting_check(repo, 'run', 'approve', True), 'cannot both be on', 'Settings refuses approve under pr')
    eq(CF.setting_check(repo, 'git', 'pr', True), '', 'pr itself')
    f = repo / 'runner.toml'
    text = f.read_text(encoding='utf-8')
    f.write_text(text.replace('pr = true', 'pr = false').replace('[run]\n', '[run]\napprove = true\n'), encoding='utf-8')
    has(CF.setting_check(repo, 'git', 'pr', True), 'cannot both be on', 'Settings refuses pr under approve')
    f.write_text(text.replace('[run]\n', '[run]\napprove = true\n'), encoding='utf-8')
    r = run(repo, 'plan')
    check(r.returncode != 0 and 'cannot both be on' in r.stderr, 'a config with both does not load', r.stderr)
    f.write_text(text.replace('pr = true', 'pr = "yes"'), encoding='utf-8')
    check('[git] pr' in run(repo, 'plan').stderr, 'pr is true or false')


# --- a task's pull request -------------------------------------------------------------------------------------

def test_opens(tmp: Path):
    print('a finished task opens one pull request; main stays')
    repo, origin, gh = make(tmp, 'one')
    start = git(origin, 'rev-parse', 'main')
    with using(gh):
        has(pr.done_problem('F1', 'x\n\nreview: nothing', S.C), 'what, why, try, risk', 'done wants what the pull request says')
        has(said('F1', 'no line'), 'review: ', 'and the spec review')
        eq(work(repo, 'F1', 'a.py'), False, 'it waits for a person')
        eq(len(gh.prs), 1, 'one pull request')
        x = gh.prs[0]
        eq((x['title'], x['head']), ('F1: one', 'task/F1'), 'title and branch')
        check('--draft' not in x['argv'], 'ready for review')
        for want in ('## What', 'F1 changes it', '## Why', 'faster', '## How to try it', 'open it', '## Risk', 'none known',
                     '## Spec review', 'fixed the label', '**F1** one', '## Gate', 'passed: `git --version`'):
            check(want in x['body'], f'the body says {want}', x['body'])
        check('@someone' not in x['body'], 'a name in it notifies nobody')
        eq(git(origin, 'rev-parse', 'task/F1'), git(repo, 'rev-parse', 'task/F1'), 'its branch is pushed')
        eq((git(origin, 'rev-parse', 'main'), git(repo, 'rev-parse', 'main')), (start, start), 'main is where it was')
        eq(boxes()['F1'], ' ', 'not done yet')
        check((plansync.ticks(S.C) / 'F1').exists(), 'its done is kept for the merge')
        eq(slots.unmerged('main', []), [], 'nothing is left to merge')
        check('F2' not in [t[0] for t in sched.tasks('main')], 'what waits for it waits for the merge')
        eq(M.merge('F1', 'main'), False, 'again: nothing new')
        pr.look('main', gh)
        eq((len(gh.prs), boxes()['F1']), (1, ' '), 'open on GitHub: nothing happens')
        with edit_rec() as rec:  # the run died between opening it and writing that down
            rec.update(number=0, url='', pushed='')
        pr.look('main', gh)
        eq((len(gh.prs), pr.read()[0]['number']), (1, 1), 'the one that is there is found again')
        gh.prs[0]['state'] = 'CLOSED'
        pr.look('main', gh)
        eq((boxes()['F1'], pr.read()[0]['state']), ('~', 'CLOSED'), 'closed without a merge: not done, a person is asked')
    check(not any(c[:2] == ('pr', 'merge') for c in gh.calls), 'the runner never merges')


class edit_rec:
    def __enter__(self):
        self.cm = pr.edit()
        return self.cm.__enter__()[0]

    def __exit__(self, *a):
        return self.cm.__exit__(*a)


def test_no_main(tmp: Path):
    print('nothing pushes or commits on main')
    repo, origin, _ = make(tmp, 'main')
    start = git(origin, 'rev-parse', 'main')
    git(repo, 'commit', '-q', '--allow-empty', '-m', 'by hand')
    has(gitops.push(repo, 'main', shared=True), 'PR mode', 'the push of a merge')
    has(P._push(repo), 'PR mode', 'the push of an edit')
    eq(git(origin, 'rev-parse', 'main'), start, 'main is where it was')
    has(pr.follow('main'), 'GitHub does not have', 'a commit on main here is said')
    git(repo, 'reset', '-q', '--hard', start)
    head = git(repo, 'rev-parse', 'main')
    r = U.setting_project('run', 'slots', 4)
    check(not r['ok'] and 'pull request' in r['out'], 'a setting for everyone is not committed', str(r))
    eq(git(repo, 'rev-parse', 'main'), head, 'no commit')


def test_styles(tmp: Path):
    print('a person merges it: merge commit, squash, rebase')
    for how in ('merge', 'squash', 'rebase'):
        repo, origin, gh = make(tmp, how)
        with using(gh):
            eq(work(repo, 'F1', 'a.py'), False, f'{how}: opened')
            commit = gh.merge(1, how, tmp / how / 'person')
            pr.look('main', gh)
        eq(boxes()['F1'], 'x', f'{how}: ticked')
        check(f'landed {commit[:10]}' in S.C.done.read_text(encoding='utf-8') + S.C.todo.read_text(encoding='utf-8'),
              f'{how}: with the commit it landed as')
        eq(git(repo, 'rev-parse', 'main'), commit, f'{how}: main here follows')
        check('F1' in (repo / 'a.py').read_text(encoding='utf-8'), f'{how}: in the main checkout')
        eq(git(repo, 'branch', '--list', 'task/*'), '', f'{how}: its branch is gone here')
        eq(git(origin, 'branch', '--list', 'task/*'), '', f'{how}: and on the remote')
        eq(pr.read(), [], f'{how}: nothing is kept')
        check('F2' in [t[0] for t in sched.tasks('main')], f'{how}: what waited for it may start')


def test_left_over(tmp: Path):
    print('a newer commit that missed the merge is kept')
    repo, origin, gh = make(tmp, 'left')
    with using(gh):
        work(repo, 'F1', 'a.py')
        git(repo, 'checkout', '-q', 'task/F1')
        git(repo, 'commit', '-q', '--allow-empty', '-m', 'F1: more')
        more = git(repo, 'rev-parse', 'HEAD')
        git(repo, 'checkout', '-q', 'main')
        with mock.patch.object(pr, '_net', lambda cwd: lambda *a: answer(a, code=1, err='offline')):
            eq(M.merge('F1', 'main'), False, 'taken in, not pushed')
        gh.merge(1, 'squash', tmp / 'left' / 'person')
        with mock.patch.object(pr, 'open_due'):  # the merge came before the next push
            pr.look('main', gh)
    eq(boxes()['F1'], 'x', 'ticked')
    eq(git(repo, 'rev-parse', 'leftover/F1'), more, 'its newer commit is on leftover/F1')


def test_second_group(tmp: Path):
    print('parts filed while the first pull request is open get one of their own')
    repo, origin, gh = make(tmp, 'second', tasks='- [ ] **P5a** first | files: c.py\n- [ ] **P5b** second | files: d.py\n')
    with using(gh):
        work(repo, 'P5a', 'c.py')
        work(repo, 'P5b', 'd.py')
        first = git(origin, 'rev-parse', 'pr/P5')
        S.C.todo.write_text(S.C.todo.read_text(encoding='utf-8') + '- [ ] **P5c** third | files: a.py\n'
                            '- [ ] **P5d** fourth | files: b.py\n', encoding='utf-8')
        work(repo, 'P5c', 'a.py')
        work(repo, 'P5d', 'b.py')
    eq(([x['head'] for x in gh.prs], [x['ids'] for x in pr.read()]),
       (['pr/P5', 'pr/P5-2'], [['P5a', 'P5b'], ['P5c', 'P5d']]), 'two pull requests')
    eq(git(origin, 'rev-parse', 'pr/P5'), first, 'the first is as it was')


def test_main_held(tmp: Path):
    print('merged, but main here cannot follow: not ticked until it does')
    repo, _, gh = make(tmp, 'held')
    with using(gh):
        work(repo, 'F1', 'a.py')
        gh.merge(1, 'squash', tmp / 'held' / 'person')
        (repo / 'a.py').write_text('mine\n', encoding='utf-8')
        with mock.patch.object(S, 'alarm') as alarm:
            pr.look('main', gh)
            pr.look('main', gh)
        eq((alarm.call_count, boxes()['F1']), (1, ' '), 'said once, and not ticked')
        eq((repo / 'a.py').read_text(encoding='utf-8'), 'mine\n', 'the edit is left alone')
        git(repo, 'checkout', '-q', '--', 'a.py')
        pr.look('main', gh)
        eq(boxes()['F1'], 'x', 'once it can, it is ticked')


def test_not_ready(tmp: Path):
    print('no gate, no review, no pull request')
    repo, origin, gh = make(tmp, 'not')
    with using(gh):
        has(work(repo, 'F1', 'a.py', finished=False), 'done` has not passed', 'a session that never ran done')
        (plansync.ticks(S.C) / 'F1').touch()
        has(M.merge('F1', 'main'), 'no spec review', 'no review')
        eq(said('F1'), '', 'reviewed now')
        with mock.patch.object(M, 'tested', return_value='the gate fails'):
            eq(M.merge('F1', 'main'), 'the gate fails', 'a red gate')
        eq((gh.prs, pr.read()), ([], []), 'nothing was opened or kept')
        gh.down = True
        eq(M.merge('F1', 'main'), False, 'GitHub away: it waits')
        eq((len(gh.prs), pr.read()[0]['number']), (0, 0), 'not open yet')
        gh.down = False
        pr.look('main', gh)
        eq((len(gh.prs), pr.read()[0]['number']), (1, 1), 'the next look opens it')

        git(repo, 'checkout', '-q', '-b', 'task/F2', 'main')
        git(repo, 'commit', '-q', '--allow-empty', '-m', 'F2: half')
        git(repo, 'checkout', '-q', 'main')
        P.block('F2', 'BLOCKED: a login', todo=S.C.todo)
        eq(M.merge('F2', 'main'), None, 'a blocked task opens none')
        check(git(repo, 'branch', '--list', 'wip/F2') and not git(repo, 'branch', '--list', 'task/F2'), 'its work is on wip/')
        eq(len(gh.prs), 1, 'still the one')


def test_main_moved(tmp: Path):
    print('main moved meanwhile: taken in, tested, pushed with no force')
    repo, origin, gh = make(tmp, 'moved')
    other = tmp / 'moved' / 'other'
    with using(gh):
        work(repo, 'F1', 'a.py', finish=False)
        git(repo, 'push', '-q', 'origin', 'task/F1')  # as done does
        tip = git(repo, 'rev-parse', 'task/F1')
        git(tmp / 'moved', 'clone', '-q', str(origin), str(other))
        (other / 'b.py').write_text('theirs\n', encoding='utf-8')
        git(other, 'commit', '-qam', 'theirs')
        git(other, 'push', '-q', 'origin', 'main')
        seen = []
        real = M.tested
        with mock.patch.object(M, 'tested', lambda *a, **k: (seen.append(a[0]), real(*a, **k))[1]):
            eq(M.merge('F1', 'main'), False, 'opened')
    eq(seen, ['F1'], 'the gate ran on the two together')
    now = git(origin, 'rev-parse', 'task/F1')
    eq(git(origin, 'show', f'{now}:b.py'), 'theirs', 'main is in it')
    git(origin, 'merge-base', '--is-ancestor', tip, now)
    eq(git(repo, 'rev-parse', 'task/F1'), now, 'the branch here is the one on GitHub')


def test_parts(tmp: Path):
    print('split parts share one pull request')
    repo, origin, gh = make(tmp, 'parts')
    ls = S.plan_text('main')
    eq(pr.group('P5a', ls), {'P5a', 'P5b'}, 'the parts')
    eq(pr.group('F1', ls), {'F1'}, 'a task alone')
    with using(gh):
        check('P5b' not in [t[0] for t in sched.tasks('main')], 'the second waits for the first')
        eq(work(repo, 'P5a', 'c.py'), False, 'the first is in')
        eq(gh.prs, [], 'no pull request with a part missing')
        check('P5b' in [t[0] for t in sched.tasks('main')], 'the second may start now')
        h = sched.held({}, 'main')
        t = next(t for t in h.todo if t[0] == 'P5b')
        eq(sched.clash_or_stack(t, h), (None, {}), 'and clashes with nothing')
        on = stack.begin('P5b', 'main')
        eq(on, git(repo, 'rev-parse', 'pr/P5'), 'on the first part')
        eq(stack.begin('F2', 'main'), 'main', 'another task starts on main')
        git(repo, 'branch', 'task/P5b', on)
        has(stack.told('P5b', 'main'), 'share its pull request', 'it is told')
        git(repo, 'branch', '-D', 'task/P5b')
        eq(stack.settle('P5b', 'main'), None, 'it is not moved off that')
        eq(work(repo, 'P5b', 'd.py', start=on), False, 'the second is in')
        eq([x['head'] for x in gh.prs], ['pr/P5'], 'one pull request')
        for want in ('# P5a', '# P5b', 'first part', 'second part'):
            check(want in gh.prs[0]['body'], f'it says {want}')
        gh.merge(1, 'squash', tmp / 'parts' / 'person')
        pr.look('main', gh)
    eq((boxes()['P5a'], boxes()['P5b']), ('x', 'x'), 'both ticked')
    eq((git(repo, 'branch', '--list', 'task/*', 'pr/*'), git(origin, 'branch', '--list', 'task/*', 'pr/*')), ('', ''),
       'no branch is left')


def test_parts_apart(tmp: Path):
    print('parts that cannot share one, and a dropped part')
    repo, _, gh = make(tmp, 'apart', tasks='- [ ] **P5a** first | files: c.py\n- [ ] **P5b** second | files: d.py\n'
                       '- [ ] **X1** between | files: a.py | after: P5a\n- [ ] **P5c** last | files: b.py | after: X1\n')
    eq(pr.group('P5a', S.plan_text('main')), {'P5a', 'P5b'}, 'one that waits for a task outside that waits for these')
    with using(gh):
        eq(work(repo, 'P5a', 'c.py'), False, 'a is in')
        eq(work(repo, 'P5b', 'd.py'), False, 'b, from main, joins it')
        eq(len(gh.prs), 1, 'and it opens without the last')

    repo, _, gh = make(tmp, 'drop', tasks='- [ ] **P5a** first | files: c.py\n- [ ] **P5b** second | files: d.py\n'
                       '- [ ] **P5c** third | files: a.py\n')
    with using(gh):
        work(repo, 'P5a', 'c.py')
        work(repo, 'P5b', 'd.py')
        P.tick('P5a', S.C.todo, S.C.done)  # dropped: closed in the plan
        git(repo, 'branch', '-D', 'task/P5a')
        pr.look('main', gh)
        rec = pr.read()[0]
        eq((rec['ids'], git(repo, 'show', f'{rec["head"]}:c.py')), (['P5b'], 'top'), 'a dropped part is not in it')
        P.tick('P5c', S.C.todo, S.C.done)
        pr.look('main', gh)
        eq([x['head'] for x in gh.prs], ['pr/P5'], 'it opens once no part is missing')


TESTS = [test_refusals, test_approve, test_opens, test_no_main, test_styles, test_left_over, test_second_group, test_main_held, test_not_ready,
         test_main_moved, test_parts, test_parts_apart]

if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='agent-runner-test-pr-') as t:
        sys.exit(report([lambda f=f, i=i: f((Path(t) / str(i)).mkdir() or Path(t) / str(i)) for i, f in enumerate(TESTS)]))
