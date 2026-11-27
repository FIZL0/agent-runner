#!/usr/bin/env python3
"""F65, C44: the run page model: the actions: plan add and change, drop, answer, need_give.

    python3 tests/test_ui_model_actions.py        (a temp repo, no agent, no network)

The fake run and the helpers are in tests/_ui_model.py.
"""
from __future__ import annotations
import json
import os
import time
from pathlib import Path
from unittest import mock
from _check import check, eq, git, report
from agent_runner import ui_model as U  # noqa: E402
from _ui_model import in_tmp,TODO, NOW, fake_run, chat, said  # noqa: E402


F399_ASK = {'summary': 'Give the link of Install Switch', 'steps': [
    {'text': "Add main's copy of Install Switch to Shortcuts", 'link': 'https://example.com/Install%20Switch.shortcut'}, 'Share > Copy iCloud Link'],
    'inputs': [{'key': 'icloud', 'label': 'iCloud link', 'kind': 'link', 'hint': 'It starts with https://www.icloud.com/shortcuts/',
                'match': r'https://www\.icloud\.com/shortcuts/[0-9a-f]+', 'confirm': 'This publishes the shortcut. Send it?'}]}


def test_actions(tmp: Path) -> None:
    fake_run(tmp)
    ran, sent = [], []
    real_run, real_send = U.RUN[0], U.SEND[0]
    U.RUN[0] = lambda argv: (ran.append(argv), (0, 'ok'))[1]
    U.SEND[0] = lambda text: (sent.append(text), {'ok': True, 'code': 0, 'out': 'sent to c1', 'argv': []})[1]
    try:
        r = U.act('plan_add', kind='B', text='Fix X', files=['a.py', 'tests/test_a.py'], after='F1', pri='low')
        eq(r['ok'], True, 'an action that exits 0 is ok')
        U.act('plan_change', tid='F1', text='Board page, new words', files='a.py')
        U.act('drop', tid='B2', why='overtaken')
        eq(ran, [['plan', 'add', 'B', 'Fix X', '--files', 'a.py,tests/test_a.py', '--after', 'F1', '--pri', 'low'],
                 ['plan', 'edit', 'F1', 'Board page, new words', '--files', 'a.py'],
                 ['plan', 'drop', 'B2', 'overtaken']], 'each action runs its plan command')
        U.act('chat', text='how is it going?')
        eq(sent, ['how is it going?'], 'chat goes through SEND')
        eq(U.act('nope')['ok'], False, 'an unknown action is an error result')
        eq(U.act('drop', tid='B2')['code'], 2, 'a missing argument is an error result')
        U.RUN[0] = lambda argv: (3, 'looks like F1')
        eq(U.plan_add('F', 'Board page')['ok'], False, 'a refused add is not ok')
    finally:
        U.RUN[0], U.SEND[0] = real_run, real_send


def test_real_command(tmp: Path) -> None:
    """One action through the real runner: Later (`plan shelve`) shelves D3 in the fake run's plan."""
    repo = fake_run(tmp)
    r = U.run_control('need_later', tid='D3')
    eq((r.get('said'), r.get('gone')), ('D3 is set aside until you bring it back', 'D3'), 'its toast, and gone')
    check(r['ok'], 'plan shelve ran', r)
    check('BLOCKED: shelved: DECIDE' in (repo / 'plan' / 'TODO.md').read_text(encoding='utf-8'),
          'D3 is shelved in TODO.md', (repo / 'plan' / 'TODO.md').read_text(encoding='utf-8'))
    eq([n['id'] for n in U.snapshot(up=False, now=time.time(), links={})['needs']], ['F4'],
       'a shelved item leaves Needs you')


def test_shelved_f184(tmp: Path) -> None:
    """F184: a shelved task, a concept build too, is in the snapshot's own `shelved` list and in none of queue, needs
    and concepts; Bring back is the real plan unshelve, Drop asks first; never Unpark."""
    repo = fake_run(tmp)
    todo = repo / 'plan' / 'TODO.md'
    snap = U.snapshot(up=False, now=time.time(), links={})
    eq(snap['shelved'], [], 'nothing shelved: an empty list')
    had = [q['id'] for q in snap['queue']]
    todo.write_text(TODO.split('### Parked')[0], encoding='utf-8')  # no parked task
    for tid in ('D3', 'F4'):
        check(U.run_control('need_later', tid=tid)['ok'], f'{tid} is shelved')
    place = todo.read_text(encoding='utf-8')
    snap = U.snapshot(up=False, now=time.time(), links={})
    eq([(r['id'], r['state'], r['acts']) for r in snap['shelved']],
       [(t, 'shelved', ['shelved_back', 'shelved_drop']) for t in ('D3', 'F4')], 'both, in plan order, with their actions')
    d3, f4 = snap['shelved']
    eq((d3['title'], d3['ask']), ('Write the guide', U.P.plain_ask('DECIDE', 'which layout', 'Write the guide')),
       'its short title and what it waits for in plain words')
    check('lazy layout' in f4['title'] and f4['ask'].startswith('Pick an option'), 'a concept build says so too', f4)
    eq([q['id'] for q in snap['queue']], [t for t in had if t not in ('D3', 'F4', 'R8')], 'the queue has neither')
    eq((snap['needs'], snap['concepts']), ([], []), 'nor Needs you, nor Concepts')
    for key, tid in (('queue_unpark', 'D3'), ('shelved_back', 'F1'), ('shelved_drop', 'ZZ9')):
        eq(U.run_control(key, tid=tid, confirm=True)['code'], 1, f'{key} on {tid} is refused')
    r = U.run_control('shelved_drop', tid='D3')
    check(not r['ok'] and r['confirm'].startswith('Drop D3?'), 'drop asks first', r)
    eq(todo.read_text(encoding='utf-8'), place, 'and nothing has changed yet')
    r = U.run_control('shelved_back', tid='D3')
    eq((r['ok'], r['argv'], r['said']), (True, ['plan', 'unshelve', 'D3'], 'D3 is under Needs you again'), 'plan unshelve')
    snap = U.snapshot(up=False, now=time.time(), links={})
    eq(([r['id'] for r in snap['shelved']], [n['id'] for n in snap['needs']]), (['F4'], ['D3']), 'under Needs you again')
    r = U.run_control('shelved_drop', tid='F4', confirm=True)
    check(r['ok'] and '**F4**' not in todo.read_text(encoding='utf-8'), 'a confirmed drop takes it out of the plan', r)
    eq(U.snapshot(up=False, now=time.time(), links={})['shelved'], [], 'and off the list')


def test_to_new(tmp: Path) -> None:
    """F176: a prompt starts a new control session, also while an older runner's c1 is live."""
    from unittest import mock
    from agent_runner import control as K
    fake_run(tmp)
    typed = []
    with mock.patch.object(K, 'control_live', return_value=4242), \
            mock.patch.object(K, 'control_type', side_effect=lambda n, t: (typed.append((n, t)), True)[1]):
        ran = []
        with mock.patch.object(U, 'RUN', [lambda argv: (ran.append(argv), (0, 'ok'))[1]]):
            U.to_new('hello')
            U.to_new('again')
    eq(typed, [], 'nothing is typed into a chat')
    eq(ran, [['control', '--new', '--no-wait', '--ask', t, '--no-feed'] for t in ('hello', 'again')], 'each its own')


def test_answers_f180(tmp: Path) -> None:
    """F180: a Needs you row's fixed answers are row actions: Yes and No, Done or its options, labelled by the row;
    one runs the plan command only when the row still has the answer pressed, with the words beside it."""
    fake_run(tmp)
    for row, want in (({'label': 'CONFIRM'}, {'need_yes': 'Yes', 'need_no': 'No'}),
                      ({'label': 'DECIDE', 'ask': 'Which port?'}, {}),
                      ({'label': 'BLOCKED'}, {'need_answer1': 'Done'}),
                      ({'label': 'TOOL', 'ask': 'Connect it, yes or no'}, {}),
                      ({'label': 'PITCH', 'options': ['Approve', 'Not this: drop']},
                       {'need_answer1': 'Approve', 'need_answer2': 'Not this: drop'})):
        eq(U.row_labels('need', row), want, f'{row["label"]}: its answers')
        eq([k for k in U.row_acts('need', row) if U.run_control_of(k).get('answer')], list(want), 'and its acts')
    ran = []
    rows = {'B2': {'id': 'B2', 'label': 'CONFIRM'}, 'F1': {'id': 'F1', 'label': 'BLOCKED'}, 'D3': {'id': 'D3', 'label': 'DECIDE'}}
    with mock.patch.object(U, 'RUN', [lambda argv: (ran.append(argv), (0, 'ok'))[1]]), \
            mock.patch.object(U, 'row_of', lambda where, tid: rows.get(tid)), \
            mock.patch.object(U, 'need_label', lambda tid: rows.get(tid, {}).get('label', '')):
        r = U.act('run_control', key='need_yes', tid='B2', text='Yes', note='on  wifi')
        eq((r['ok'], r['said'], r['gone']), (True, 'B2 ticked', 'B2'), 'Yes ticks it')
        U.act('run_control', key='need_no', tid='B2', text='No')
        U.act('run_control', key='need_answer1', tid='F1', text='Done')
        eq(ran, [['plan', 'confirm', 'B2', 'Yes: on wifi'], ['plan', 'change', 'B2', 'No: the check failed'],
                 ['plan', 'confirm', 'F1', 'Done']], 'the plan commands')
        ran.clear()
        for key, tid, text in (('need_answer1', 'F1', 'Option A'), ('need_answer1', 'F1', ''), ('need_yes', 'F1', 'Yes'),
                               ('need_answer1', 'D3', 'A'), ('need_yes', 'ZZ9', 'Yes')):
            eq(U.run_control(key, tid=tid, text=text)['code'], 1, f'{key} {text!r} on {tid} is refused')
        eq(U.run_control('need_yes', tid='ZZ9', text='Yes')['out'], 'ZZ9 no longer needs you (answered already?)', 'and says why')
        eq(ran, [], 'and runs nothing')


def test_typed_decide_f181a(tmp: Path) -> None:
    """F181a: the words typed as a DECIDE's reply are its answer (plan confirm, no session); a CONFIRM's and a
    concept's still open a chat."""
    repo = fake_run(tmp)
    todo = repo / 'plan' / 'TODO.md'
    todo.write_text(TODO.replace('- [ ] **B2** Fix the merge retry | files: b.py | after: F1',
                                 '- [~] **B2** Fix the merge retry | files: b.py BLOCKED: CONFIRM: look at it'),
                    encoding='utf-8')
    eq(U.answer_argv('D3', ' the lazy one '), (['plan', 'confirm', 'D3', 'the lazy one'],
                                               'D3 answered (the lazy one): a run starts it'), 'DECIDE: plan confirm')
    for words in ('', '  '):
        eq(U.answer_argv('D3', words), ([], ''), 'no words, no answer')
    eq([U.answer_argv(t, 'looks odd') for t in ('B2', 'F4')], [([], '')] * 2, "a CONFIRM's and a concept's: a chat")
    with mock.patch('agent_runner.brief.has_sheet', lambda tid: tid == 'D3'):
        eq([U.answer_argv('D3', w)[0] for w in ('go', 'D3 picks: a=b', 'neither')],
           [['sheet', 'D3', '--go'], ['sheet', 'D3', '--picks', 'D3 picks: a=b'], ['plan', 'confirm', 'D3', 'neither']],
           "a pick sheet's go and Send line are still the sheet's")
        eq([U.answer_argv('D3', w, True, ' after  Friday')[0] for w in ('go', 'D3 picks: a=b')],
           [['sheet', 'D3', '--go', '--note=after Friday'], ['sheet', 'D3', '--picks', 'D3 picks: a=b', '--note=after Friday']],
           'F162a: the words beside them go with them')
    sent = []
    with mock.patch.object(U, 'SEND', [lambda t: (sent.append(t), {'ok': True, 'code': 0, 'out': 'sent', 'argv': []})[1]]):
        r = U.act('answer', tid='D3', text='the lazy one')  # the real plan confirm
        U.act('answer', tid='B2', text='looks odd')
    eq((r['ok'], r.get('gone')), (True, 'D3'), 'answered at once, off Needs you')
    check('- [ ] **D3**' in todo.read_text(encoding='utf-8') and 'the lazy one' in todo.read_text(encoding='utf-8'),
          'D3 is open again with the words noted', todo.read_text(encoding='utf-8'))
    eq(sent, ['B2 (Fix the merge retry): looks odd'], "only the CONFIRM's words went to a chat")


def test_need_give_f175(tmp: Path) -> None:
    """F175: the asks file's step links, commands and inputs are read; need_give sends them: text and links as quoted
    data in the answer, a secret only in the env file, which goes when its task lands or is dropped."""
    from agent_runner import asks as A, need_detail as N, plan as P
    repo = fake_run(tmp)
    todo, asks = repo / 'plan' / 'TODO.md', repo / '.runner' / 'asks'
    asks.mkdir(exist_ok=True)
    blocked = TODO.replace('- [ ] **B2** Fix the merge retry | files: b.py | after: F1',
                           '- [~] **B2** Fix the merge retry | files: b.py BLOCKED: CONFIRM: look at it')
    plain = None

    def ask(d, tid='D3') -> dict:
        todo.write_text(blocked, encoding='utf-8')
        (asks / f'{tid}.json').write_text(d if isinstance(d, str) else json.dumps(d), encoding='utf-8')
        return next(n for n in U.snapshot(up=False, now=NOW, links={})['needs'] if n['id'] == tid)

    plain = ask('{')
    eq((plain['detail']['inputs'], plain['detail']['step_more']), ([], []), 'a broken file falls back: no inputs')
    good = {'key': 'ok'}
    for odd in (5, {}, [good] * 2, *([good, x] for x in (
            5, {}, {'key': 'a b'}, {'key': 'a', 'kind': 'pin'}, {'key': 'a', 'match': '('}, {'key': 'a', 'match': 'x' * 201},
            {'key': 'a', 'kind': 'secret', 'env': 'A B'}, {'key': 'a', 'kind': ['x']}, {'key': 'a', 'confirm': True}, {'key': 'a', 'env': 'TOK'}))):
        eq(ask({'inputs': odd, 'steps': odd})['detail']['inputs'], [], f'one malformed, so none: {str(odd)[-40:]}')
    row = ask(F399_ASK)
    d = row['detail']
    eq((d['steps'], d['step_more']), (["Add main's copy of Install Switch to Shortcuts", 'Share > Copy iCloud Link'],
                                      [{'link': 'https://example.com/Install%20Switch.shortcut'}, {}]), 'F399: steps and the link')
    eq(d['inputs'], [{**F399_ASK['inputs'][0], 'env': ''}], 'F399: its input')
    eq(row['answers'], plain['answers'], "the plain answers stay F162's")
    more = ask({'steps': [{'cmd': 'gh auth login', 'on': 'rycs'}, {'cmd': 'ls'}, {'text': 'Look', 'link': 'javascript:x'}]})['detail']
    eq(more['steps'], ['Run this', 'Run this', 'Look'], 'steps with no words')
    eq((more['step_more'][0], bool(more['step_more'][1]['on']), more['step_more'][2]),
       ({'cmd': 'gh auth login', 'on': 'rycs'}, True, {}), 'a command and its machine; only web links')

    ask(F399_ASK)
    before, link = todo.read_text(encoding='utf-8'), 'https://www.icloud.com/shortcuts/ab12'
    r = U.need_give('D3', {'icloud': 'https://evil.example/x'}, confirm=True)
    eq((r['ok'], r.get('field'), r['argv']), (False, 'icloud', []), 'a failed match sends nothing')
    check('starts with https://www.icloud.com' in r['out'] and 'evil' not in r['out'], 'and says the hint', r)
    for bad in ('', 'x\ny', 5, 'javascript:alert(1)', link + '\n' + link, 'https://' + 'a' * N.LINK_MAX):
        eq(U.need_give('D3', {'icloud': bad}, confirm=True).get('field'), 'icloud', f'refused: {str(bad)[:20]!r}')
    for vals in ({}, None, {'icloud': link, 'more': 'x'}):
        check(not U.need_give('D3', vals, confirm=True)['ok'], 'only the inputs it has now', vals)
    r = U.need_give('D3', {'icloud': link})
    eq((r['code'], r.get('confirm')), (3, 'This publishes the shortcut. Send it?'), 'asked first')
    eq(todo.read_text(encoding='utf-8'), before, 'nothing was sent so far')
    r = U.need_give('D3', {'icloud': f' {link} '}, confirm=True)
    eq((r['ok'], r.get('gone')), (True, 'D3'), 'sent')
    check('- [ ] **D3**' in todo.read_text(encoding='utf-8') and f'"iCloud link" is "{link}"' in todo.read_text(encoding='utf-8'),
          'the task reopens with the link, quoted', todo.read_text(encoding='utf-8'))
    check('need_give' not in U.ACTIONS, 'a page cannot say it is secure itself')
    check(not U.need_give('D3', {'icloud': link}, confirm=True)['ok'], 'answered: no second time')

    markup = '$(touch x) | files: z.py \u2014 BLOCKED: (after F1) "q" (split into F9)'
    ask({'inputs': [{'key': 'note'}]}, 'B2')
    r = U.need_give('B2', {'note': markup})
    line = next(x for x in todo.read_text(encoding='utf-8').splitlines() if '**B2**' in x)
    check(r['ok'] and line.startswith('- [ ]'), "a CONFIRM's inputs reopen it, not tick it", line)
    check(' | files: z.py' not in line and '(split' not in line and 'BLOCKED:' not in line, 'a value is no plan markup', line)
    eq(json.loads(U.as_data(markup)), markup, 'and reads back as it was')

    secret = "s3cr'et $(x)"
    two = {'inputs': [{'key': 'tok', 'label': 'Token', 'kind': 'secret', 'env': 'MY_TOKEN'}]}
    ask(two)
    env = asks / 'D3.env'
    r = U.need_give('D3', {'tok': secret})
    check(not r['ok'] and r.get('field') == 'tok' and 'http' in r['out'] and not env.exists(), 'plain http: refused, says why', r)
    with mock.patch.object(U, 'RUN', [lambda argv: (1, 'no')]):
        check(not U.need_give('D3', {'tok': secret}, secure=True)['ok'] and not env.exists(), 'a failed answer keeps no secret')
    (repo / '.gitignore').write_text('')  # git would track it: excluded here
    r = U.need_give('D3', {'tok': secret}, secure=True)
    check(r['ok'] and env.is_file(), 'kept', r)
    import shlex
    eq(shlex.split(env.read_text(encoding='utf-8')), [f'MY_TOKEN={secret}'], 'in the env file, quoted')
    if os.name != 'nt':
        eq(env.stat().st_mode & 0o777, 0o600, 'owner-only')
    check('asks/' not in git(repo, 'status', '--porcelain', '-uall', '--', '.runner/asks/D3.env'), 'out of git')
    (repo / '.gitignore').write_text('.runner/\n')
    text = todo.read_text(encoding='utf-8')
    check('MY_TOKEN is in ' in text and 'asks/D3.env' in text.replace('\\', '/'), 'the note names it and where', text)
    snap = U.snapshot_json(up=False, now=NOW, links={})
    for f in repo.rglob('*'):
        if f.is_file() and f != env:
            check(b's3cr' not in f.read_bytes(), f'not in {f.relative_to(repo)}')
    check('s3cr' not in snap + json.dumps(r), 'nor in the snapshot or the result')

    ask({'inputs': [{'key': 'b', 'kind': 'secret'}]})
    U.need_give('D3', {'b': 'two'}, secure=True)
    eq(shlex.split(env.read_text(encoding='utf-8')), [f'MY_TOKEN={secret}', 'B=two'], 'a later one is added')
    A.sweep_env('HEAD')
    check(env.exists(), 'an open task keeps them')
    P.tick('D3', todo=todo)
    A.sweep_env('HEAD')
    check(env.exists(), 'one ticked here only, not landed yet, does too')
    git(repo, 'commit', '-qam', 'landed')
    A.sweep_env('HEAD')
    check(not env.exists(), 'gone once it landed')
    ask({'inputs': [{'key': 'b', 'kind': 'secret'}]})
    U.need_give('D3', {'b': 'two'}, secure=True)
    check(env.exists(), 'kept again')
    P.drop('D3', 'not wanted', todo=todo)
    check(not env.exists(), 'gone once dropped')


def test_slow_log_f479(tmp: Path) -> None:
    fake_run(tmp)
    logged, real_run = [], U.RUN[0]
    with mock.patch.object(U.S, 'log', lambda msg, *a, **k: logged.append(msg)), mock.patch.object(U, 'SLOW_S', 0.05):
        try:
            U.RUN[0] = lambda argv: (0, 'ok')
            U.call(['plan', 'drop', 'B2'])
            eq(logged, [], 'a fast action logs nothing')
            U.RUN[0] = lambda argv: (time.sleep(0.1), (0, 'ok'))[1]
            U.call(['plan', 'drop', 'B2'])
            eq(len(logged), 1, 'a slow action logs once')
            check('plan drop B2 took' in logged[0], f'it names the command and its time: {logged}')
        finally:
            U.RUN[0] = real_run


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_need_give_f175), in_tmp(test_actions), in_tmp(test_real_command), in_tmp(test_shelved_f184), in_tmp(test_to_new), in_tmp(test_answers_f180), in_tmp(test_typed_decide_f181a), in_tmp(test_slow_log_f479)]))
