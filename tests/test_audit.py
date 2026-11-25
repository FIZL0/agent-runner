#!/usr/bin/env python3
"""F417: auto audit: the trigger, its scope, its brief, its model, its token cap, and the switch.

    python3 tests/test_audit.py        (no network; a few seconds of git)
"""
from __future__ import annotations

import datetime as dt
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from _check import check, eq, git, has, report

from agent_runner import audit as A, brief, claude_use, config as CF, loop, loop_after, merge, plan as P, runner as R  # noqa: E402
from agent_runner import sched, settings_live, shared_tools, slots, state as S, status  # noqa: E402

AT = [0]


def project(tmp: Path, every: str = '{ every = 3 }', toml: str = '', lines=()) -> Path:
    repo = Path(tempfile.mkdtemp(dir=tmp))
    git(repo, 'init', '-q', '-b', 'main')
    (repo / 'plan').mkdir()
    (repo / 'plan/TODO.md').write_text('# TODO\n\n### Next\n\n' + ''.join(f'- [ ] **{l}\n' for l in lines), encoding='utf-8')
    (repo / 'plan/DONE.md').write_text('# DONE\n', encoding='utf-8')
    (repo / 'runner.toml').write_text('[run]\ntest = "true"\nmin_free_gb = 0\nremote = false\n'
                                      f'{f"auto_audit = {every}" if every else ""}\n{toml}', encoding='utf-8')
    (repo / '.gitignore').write_text('.runner/\n', encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'start')
    R.init(repo)
    A.LOOKED[0] = 0.0
    AT[0] = 0
    return repo


def land(*ids, kind=None):
    """Landings, each batch a minute later than the last."""
    AT[0] += 1
    when = (dt.datetime.now() + dt.timedelta(minutes=AT[0])).isoformat(timespec='seconds')
    with open(R.C.notes('events.jsonl'), 'a', encoding='utf-8') as f:
        for t in ids:
            f.write(json.dumps({'time': when, 'kind': kind or R.EV_LANDED, 'id': t, 'text': f'{t}: merged, ticked'}) + '\n')


def run(**over):
    d = dict(idle_said=True, once=False, procs={}, waiting={}, merging=[], running={}, tried=set(), branch='main',
             restart_due=False, held_merges=[])
    return SimpleNamespace(**{**d, **over})


def tick(**over) -> str:
    A.LOOKED[0] = 0.0
    return A.tick(run(**over))


def line(repo: Path, tid: str) -> str:
    return next(l for l in P.lines(repo / 'plan/TODO.md') if f'**{tid}**' in l)


def close(repo: Path, tid: str):
    """Tick `tid` by hand, with no findings file."""
    f = repo / 'plan/TODO.md'
    f.write_text(f.read_text().replace(line(repo, tid) + '\n', ''), encoding='utf-8')
    git(repo, 'commit', '-qam', f'{tid} closed')


def audited(repo: Path, tid: str, text: str):
    """The audit `tid` lands: its findings file comes in on a branch of its own, as a task's does."""
    git(repo, 'checkout', '-qb', f'task/{tid}')
    f = repo / A.findings_file(tid)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', f'{tid} audit')
    git(repo, 'checkout', '-q', 'main')
    (repo / 'beside.txt').write_text(tid, encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'landed beside it')
    git(repo, 'merge', '-q', '--no-ff', '-m', f'merge {tid}', f'task/{tid}')


def test_trigger(tmp: Path):
    print('every N landed tasks and idle: one audit, once')
    repo = project(tmp)
    land('F1', 'F2')
    eq(tick(), '', 'two landed, none yet')
    land('F2')
    eq(tick(), '', 'a task counts once')
    land('F3', kind=R.EV_PART)
    tid = tick()
    eq(tid, 'R1', 'the third queues one')
    l = line(repo, tid)
    check(A.tagged(l) and '(follow-up, normal) (audit) ' in l, 'tagged', l)
    eq(P.fields(l)['files'], ['plan/audits/**'], 'it names the findings')
    eq(P.too_big(tid, R.C, repo / 'plan/TODO.md'), '', 'not over [run] task_size')
    eq((git(repo, 'log', '-1', '--format=%s'), git(repo, 'status', '--porcelain')),
       (f'Plan: {tid}, auto audit (3 landed)', ''), 'committed')
    ev = json.loads(R.C.notes('events.jsonl').read_text().splitlines()[-1])
    check(ev['kind'] in status.LATELY, 'status lists it')
    eq(status.since_event(ev, {})[1:], (tid, f'queued {tid} (auto_audit: 3 landed)'), 'and says it')
    land('F4', 'F5', 'F6')
    eq(tick(), '', 'none while one is open')
    P.block(tid, 'DECIDE: x?', todo=repo / 'plan/TODO.md')
    git(repo, 'commit', '-qam', 'blocked')
    eq(tick(), '', 'nor while one is blocked')


def test_dropped(tmp: Path):
    print('one dropped before it landed: not again for the same work')
    repo = project(tmp)
    land('F1', 'F2', 'F3')
    tid = tick()
    with mock.patch.object(A, 'landed', lambda *a, **k: ['F1', 'F2']):
        close(repo, tid)
        eq(tick(), '', 'under N')
    f = R.C.notes('events.jsonl')  # it was queued after they landed, not before as this test's stamps have it
    evs = [json.loads(x) for x in f.read_text().splitlines()]
    evs[-1]['time'] = (dt.datetime.now() + dt.timedelta(minutes=1, seconds=1)).isoformat(timespec='seconds')
    f.write_text(''.join(json.dumps(e) + '\n' for e in evs), encoding='utf-8')
    eq((tick(), A.landed('main')), ('', ['F1', 'F2', 'F3']), 'not queued; the next one still covers them')
    land(tid, 'F4', 'F5')
    eq(tick(), '', 'an audit landing is not counted')
    land('F6')
    check(tick(), 'three more: one')


def test_busy(tmp: Path):
    print('not while the run is busy')
    project(tmp, lines=['T1** a task | files: a'])
    land('F1', 'F2', 'F3')
    alive = SimpleNamespace(is_alive=lambda: True)
    eq(tick(), '', 'a task may start')
    for why, over in (('not idle', {'idle_said': False}), ('a session', {'procs': {1: 1}}), ('run once', {'once': True}),
                      ('a session waits to resume', {'waiting': {1: 1}}), ('a merge', {'merging': [alive]})):
        eq(tick(tried={'T1'}, **over), '', why)
    with mock.patch.object(S, 'stopping', lambda: True):
        eq(tick(tried={'T1'}), '', 'stopping')
    with mock.patch.object(loop, 'PAUSED', [True]):
        eq(tick(tried={'T1'}), '', 'paused')
    with mock.patch.object(shared_tools, 'pending', lambda tried: True):
        eq(tick(tried={'T1'}), '', 'a task waits for a shared tool')
    R.MERGE.acquire()
    try:
        eq(tick(tried={'T1'}), '', 'the merge lock is held')
    finally:
        R.MERGE.release()
    check(tick(tried={'T1'}), 'idle: queued')
    print("the run's own tick and idle queue it")
    repo = project(tmp)
    land('F1', 'F2', 'F3')
    names = ('retry_reopened', 'upgrade_tick', 'watch_ci', 'watch_issues', 'auto_release', 'sweep_unmerged', 'keep_claims', 'block_asks')
    with mock.patch.multiple(loop_after, **{n: lambda *a, **k: None for n in names}), \
            mock.patch('agent_runner.control_held.controls_tick', lambda b: None), \
            mock.patch('agent_runner.page_copy.page_copy_tick', lambda: None), mock.patch.object(loop, 'take_keys', lambda: None):
        loop_after.after(run(closed=set(), free_at={}, slots=1, idle_said=False))
        check('(audit)' not in (repo / 'plan/TODO.md').read_text(), 'busy: none')
        loop_after.after(run(closed=set(), free_at={}, slots=1))
        loop_after.after(run(closed=set(), free_at={}, slots=1))
    eq((repo / 'plan/TODO.md').read_text().count('(audit) '), 1, 'idle: one, once')


def test_off(tmp: Path):
    print('off by default; what the setting takes')
    repo = project(tmp, every='')
    land(*[f'F{i}' for i in range(60)])
    with mock.patch.object(A, 'idle', lambda run: check(False, 'off looked')):
        eq((R.C.run['auto_audit'], tick(), A.queue('main')), (False, '', ''), 'off: nothing queued')
    eq([A.every_of(v) for v in (True, {'every': 7}, {}, {'every': 0}, {'every': True}, {'every': 'x'}, False, 'x')],
       [50, 7, 0, 0, 0, 0, 0, 0], 'true is 50')
    eq((CF.setting_type('run', 'auto_audit'), CF.DEFAULTS['models']['audit']), ('table', 'opus'), 'defaults')
    for bad in ('auto_audit = "yes"', 'audit_tokens = "x"', 'audit_tokens = -1'):
        (repo / 'runner.toml').write_text(f'[run]\n{bad}\n', encoding='utf-8')
        try:
            CF.Config(repo)
            check(False, f'{bad} is refused')
        except SystemExit as e:
            has(str(e), rf'\[run\] {bad.split()[0]}', bad)


def test_scope(tmp: Path):
    print('scope: only what changed since the last audit')
    repo = project(tmp)
    land('F1', 'F2', 'F3')
    tid = tick()
    git(repo, 'checkout', '-qb', 'scratch')
    said = A.prompt(tid, 'main', repo)
    git(repo, 'checkout', '-q', 'main')
    until = git(repo, 'rev-parse', 'main')
    has(said, rf'Audited: start\.\.{until[:12]}', 'none before it: from the start')
    for cmd in ('diff --stat', 'log --oneline'):
        words = said.split(f'`git {cmd} ')[1].split('`')[0].split()
        check(git(repo, *cmd.split(), *words), f'git {cmd} runs', words)
    has(said, r'Tasks landed since \(3\): F1, F2, F3', 'the landed tasks')
    audited(repo, tid, f'Audited: start..{until[:12]}\n\n## Docs\n')
    eq(A.last('main'), until[:12], 'the next one starts where it read up to')
    close(repo, tid)
    land('F4')
    # the events' stamps are minutes ahead of the commit: the first three count as later here
    eq(A.landed('main')[-1], 'F4', 'a task landed since')
    said = A.prompt('R2', 'main', repo)
    has(said, r'Not reached` is in scope too', 'what the last one did not reach is in it')
    (repo / 'plan/audits/README.md').write_text('x')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'a readme')
    eq((A.last('main'), A.audits('main')), (until[:12], {tid}), 'a README there is no audit')
    said = A.prompt('R2', 'main', repo)
    has(said, rf'`git diff --stat {until[:12]}\.\.{git(repo, "rev-parse", "main")[:12]}`', 'its range')
    check('beside.txt' in git(repo, 'diff', '--name-only', f'{until[:12]}..main'), 'what landed beside the audit is in it')
    old = dt.datetime.now() - dt.timedelta(days=1)
    f = R.C.notes('events.jsonl')
    evs = [json.loads(x) for x in f.read_text().splitlines()]
    for e in evs[:3]:
        e['time'] = old.isoformat(timespec='seconds')
    f.write_text(''.join(json.dumps(e) + '\n' for e in evs), encoding='utf-8')
    eq(A.landed('main'), ['F4'], 'what landed before it is not in it')
    before = git(repo, 'rev-parse', 'main')
    audited(repo, 'R3', 'no range here\n')
    eq(A.last('main'), before, 'a file with no range: the commit it began from')
    audited(repo, 'R4', 'Audited: start..deadbeefdead\n')
    check(A.last('main') not in ('', 'deadbeefdead'), 'a commit that is not on the branch is not believed')
    eq(A.audits('main'), {'R1', 'R3', 'R4'}, 'the audits that landed')


def test_brief(tmp: Path):
    print('the brief, by hand too')
    repo = project(tmp, lines=['R7** (follow-up, low) (audit) the docs most of all | files: plan/audits/**',
                               'R8** research an (audit) of x | files: plan/r8.md'])
    said = brief.prompt_for('R7', 1, 1, repo, 'main')
    for words in ('R7 is an audit', 'plan/audits/R7.md', 'stale, duplicate', 'a done task removed', 'no commits',
                  'over 7 days', 'lessons', 'Code and tests nothing uses', 'cost --days', '1,000,000 tokens'):
        check(words in said, words)
    check('R7 is a research task' not in said, 'not the research paragraphs: it queues nothing')
    check('R8 is a research task' in brief.prompt_for('R8', 1, 1, repo, 'main'), 'the tag opens the text')
    eq(A.queue('main'), '', 'nothing landed')
    land('F1', 'F2', 'F3')
    eq(tick(tried={'R7', 'R8'}), '', 'one added by hand is open: none by itself')
    git(repo, 'checkout', '-qb', 'task/R7')
    (repo / 'plan/audits').mkdir()
    (repo / 'plan/audits/R7.md').write_text('x\n')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'R7')
    eq(merge.research_code('R7', 'main'), [], 'its file merges as findings')
    with mock.patch.object(CF.Config, 'plan_external', True):
        eq(A.findings_file('R7'), 'docs/audits/R7.md', 'a plan elsewhere')
        check('docs/audits/**' in brief.findings_globs(), 'merges too')


def test_model(tmp: Path):
    print('[models] audit')
    toml = '[models]\naudit = "codex:gpt-6"\n[models.kinds]\nR = "haiku"\n'
    lines = ['R7** (audit) x', 'R8** research', 'R9** (audit) y | model: sonnet']
    project(tmp, toml=toml, lines=lines)
    eq([slots.task_model(t, 'opus', 'main') for t in ('R7', 'R8', 'R9')], ['codex:gpt-6', 'haiku', 'sonnet'],
       'any provider; an audit only; its own model wins')
    with mock.patch.dict(R.C.run, model_flag='fable'):
        eq(slots.task_model('R7', 'opus', 'main'), 'fable', 'so does run --model')
    project(tmp, lines=lines)
    eq(slots.task_model('R7', 'opus', 'main'), 'opus', 'opus by default')
    roles = ''.join(f'{r} = "codex:m"\n' for r in ('code', 'fix', 'review', 'control', 'feed', 'docs'))
    kinds = ''.join(f'{k} = "codex:m"\n' for k in CF.DEFAULTS['models']['kinds'])
    project(tmp, toml=f'[models]\n{roles}[models.kinds]\n{kinds}')
    check(not claude_use.uses(R.C), 'it alone does not make a project need Claude Code')


def test_cap(tmp: Path):
    print('[run] audit_tokens')
    project(tmp, toml='audit_tokens = 1000\n', lines=['R7** (audit) x', 'R8** research'])
    eq([A.caps('R7', c) for c in ((0, 2), (500, 0), (5000, 0))], [(1000, 2), (500, 0), (1000, 0)], 'the smaller')
    eq(A.caps('R8', (0, 2)), (0, 2), 'an audit only')
    with mock.patch.dict(R.C.run, audit_tokens=0):
        eq(A.caps('R7', (0, 2)), (0, 2), '0: no cap')

    def look(tid, tokens):
        told, ended = [], []
        slots.BUDGET_AT[0] = 0.0
        with mock.patch.object(slots, 'task_spend', lambda sid: (tokens, 0.1)), \
                mock.patch.object(slots, 'finished_mark', lambda n: None), \
                mock.patch.object(slots.plat, 'terminate', ended.append):
            slots.budgets({1: (99999999, f'sid-{tid}', 0)}, {1: (tid, 'Next', set(), set())},
                          lambda n, procs, text: told.append(text))
        return told, ended
    eq((look('R7', 999), look('R8', 9999)), (([], []), ([], [])), 'under it; not an audit')
    told, ended = look('R7', 1001)
    has(told[0], r'past \[run\] audit_tokens \(1,000\).*then run `[^`]*done R7 ', 'told to stop and land what it found')
    check('do not run `done`' not in told[0], 'not to leave it', told[0])
    eq((ended, look('R7', 1200), look('R7', 1300)), ([], ([], []), ([], [99999999])), 'ended when it goes on')


def in_tmp(f):
    def go():
        with tempfile.TemporaryDirectory() as d:
            f(Path(d))
    go.__name__ = f.__name__
    return go


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(f) for f in (test_trigger, test_dropped, test_busy, test_off, test_scope, test_brief,
                                                 test_model, test_cap)]))
