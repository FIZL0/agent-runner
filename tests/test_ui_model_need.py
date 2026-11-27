#!/usr/bin/env python3
"""F65, C44: the run page model: what Needs you shows: answers, options, sheets and details.

    python3 tests/test_ui_model_need.py        (a temp repo, no agent, no network)

The fake run and the helpers are in tests/_ui_model.py.
"""
from __future__ import annotations
import datetime as dt
import json
from pathlib import Path
from unittest import mock
from _check import check, eq, report
from agent_runner import state as S  # noqa: E402
from agent_runner import ui_model as U  # noqa: E402
from _ui_model import in_tmp,TODO, NOW, fake_run, ran_by, chat, said  # noqa: E402


ASKS_F162 = {  # real asks, as Needs you showed them
    'B160': ('CONFIRM', 'On an iPhone in Safari, after this lands and the run restarts: 1) reload, open a chat, tap the message box; '
             'the header stays and the box rides up with no grey band. 2) Close the keyboard; it glides back. 3) Same in Talk, '
             'Home, Settings and a sheet. Chat and Home were already seen working on the iPhone 15 Pro - reply yes/no'),
    'F154': ('CONFIRM', "On an iPhone, in a long chat, on Home and in the open drawer's list: scroll up/down and bend sideways (the "
             'drawer must not open or close); swipe the drawer open and closed at a slant (nothing may scroll up or down); taps '
             'still open rows, and holding a chat row still drags it - reply yes/no'),
    'F106h': ('BLOCKED', 'Log in to Copilot: `run login copilot` (device code; unattended it ended exit 124 waiting for approval at '
              'github.com/login/device). Then the Copilot check, the default and the docs follow; findings in '
              'docs/research/F106h-harness-end-to-end.md - reply done once it is'),
    'B163': ('STUCK', 'Stuck: waits for its Windows run - reply with what to do'),
    'B177': ('CONFIRM', 'On the iPhone, reload the run page on Talk, then on a chat, then on Plan: each opens again without Home '
             'flashing, and Talk neither listens nor speaks by itself - reply yes/no'),
    'R6': ('CONFIRM', "Once B79 is released and upgraded on the work Windows machine: in the Claude desktop app open a runner repo in "
           "its Claude Code (no run started from a terminal): (1) does 'status' give the run's status (the control brief)? (2) start "
           'a run from it, close the app: is the run still going? - reply with what you saw - reply yes/no')}


def test_need_answers_c33(tmp: Path) -> None:
    """C33: every needs row carries its answers; one rule for both pages and the chat text."""
    copy = tmp / 'K1.html'
    copy.write_text('<h1>Menu</h1><h2>Tabs</h2><p>a</p><h2>Drawer · recommended</h2><p>b</p>', encoding='utf-8')
    names = lambda row: [a['label'] for a in U.need_answers(row)]  # noqa: E731
    eq(names({'label': 'CONFIRM'}), ['Yes', 'No'], 'CONFIRM: Yes, No')
    eq(names({'label': 'DECIDE', 'ask': 'Ship it? yes or no'}), ['Yes', 'No'], 'a yes/no ask: Yes, No')
    eq(names({'label': 'DECIDE', 'ask': 'Which port?'}), [], 'DECIDE with no pick: reply only')
    eq(names({'label': 'BLOCKED'}), ['Done'], 'BLOCKED: Done, on both pages')
    eq(names({'label': 'CONCEPT', 'copy': str(copy)}), ['Tabs', 'Drawer · recommended'], "CONCEPT: the copy's options")
    eq(names({'label': 'CONCEPT'}), ['A', 'B', 'C'], 'CONCEPT without a copy: A, B, C')
    eq(names({'label': 'PITCH', 'options': ['Approve', 'Not this: drop']}), ['Approve', 'Not this: drop'], 'PITCH')
    rows, _ = U.needs_rows([('CONFIRM', 'F1', '', 'ok?', '', 'T', False), ('BLOCKED', 'F2', '', 'log in', '', 'T', False)],
                           dt.datetime.now())
    eq([[a['value'] for a in r['answers']] for r in rows], [['Yes', 'No'], ['Done']], 'the snapshot rows carry them')
    eq(U.need_options(rows[1]), ['Done'], 'the chat text uses the same')
    run, fix = {'forced': False}, {'unclaim': [{'id': 'F1'}]}
    on = U.controls_shown(True, run, fix)
    check('force' in on['shown'] and 'caps_on' not in on['shown'] and 'unclaim' in on['shown'], 'shown now', on)
    eq(U.controls_shown(False, run, fix)['card'], ['start'], 'no run: Start the run')
    check('pause' not in U.controls_shown(False, run, fix)['shown'], 'no run: no Pause')
    check(U.task_controls_on({'name': 's1', 'task': 'F1'}) and not U.task_controls_on({'name': 's1', 'task': 'F1',
          'state': 'merging'}) and not U.task_controls_on({'name': 'c1', 'task': 'F1'}), 'task controls')


def test_decide_options_f181c(tmp: Path) -> None:
    """F181c: a DECIDE's options are its answers, from the ask file or the bracket that ends its question, never from
    prose; the recommended one is first and marked, and the value sent is the bare name, by plan confirm."""
    repo = fake_run(tmp)
    todo, link = repo / 'plan' / 'TODO.md', 'https://claude.ai/artifact/QCMg'
    plain = todo.read_text(encoding='utf-8')

    def ask(words: str) -> dict:
        todo.write_text(plain.replace('DECIDE: which layout https://claude.ai/artifact/abc', f'DECIDE: {words}'), encoding='utf-8')
        return U.row_of('need', 'D3')
    said = lambda row: [(a['label'], a['value']) for a in row['answers']]  # noqa: E731
    look = [('Full (recommended)', 'Full'), ('Small', 'Small'), ('No change', 'No change')]
    f179 = 'Which look for the chat window: Full (recommended), Small, or no change?'
    eq((said(row := ask(f'{f179} {link}')), row.get('options')), ([], None), "F179's question, options in prose: never guessed")
    row = ask(f'Which look for the chat window? [Full (recommended) / Small / No change] {link}')
    eq((said(row), row['url'], row['what']), (look, link, 'Which look for the chat window?'), "F179's as a bracket: its buttons")
    check('[Full' not in json.dumps([row['ask'], row['ask_short'], row['what'], row['detail']['steps'], row['detail']['summary']]),
          'the bracket is not shown in the question', row)
    eq(U.row_labels('need', row), {'need_answer1': 'Full', 'need_answer2': 'Small', 'need_answer3': 'No change'}, 'what a press sends: the bare names')
    eq(said(ask('Which size? [small / iPhone (Recommended)]')), [('iPhone (recommended)', 'iPhone'), ('small', 'small')],
       'the recommended first, the rest as given, names as written')
    eq(said(ask('Ship it? [Yes / No (recommended)].')), [('No (recommended)', 'No'), ('Yes', 'Yes')], 'Yes and No with one recommended')
    for bad in ('[A]', '[A/B]', '[A / ]', '[ / B]', '[A / a]', '[A (recommended) / B (recommended)]', '[A / B', '[A / B] or so',
                '[A [x] / B]', '[A / -b]', '[A / ' + 'b' * 81 + ']', '[' + ' / '.join(f'o{j}' for j in range(13)) + ']', '[(recommended) / B]'):
        row = ask(f'Which one? {bad}')
        eq((said(row), row['what']), ([], f'Which one? {bad}'), f'{bad[:30]}: no buttons, and it stays in the question')
    for late in (f'Which? {link} [A / B]', f'Which? [A {link} / B]'):
        eq(said(ask(late)), [], f'{late}: a link before the bracket ends, no buttons')
    row = ask(f'Which? [A / B] {link} https://example.com/b')
    eq((said(row), row['what']), ([('A', 'A'), ('B', 'B')], 'Which? https://example.com/b'), 'two links after it')
    f = S.C.notes('uploads', 'x').parent.parent / 'asks' / 'D3.json'
    f.parent.mkdir(parents=True, exist_ok=True)
    opts = [{'name': 'Keep'}, {'name': 'Move [it] / all', 'rec': True}]
    f.write_text(json.dumps({'options': opts}), encoding='utf-8')
    eq(said(ask('Which one, then?')), [('Move [it] / all (recommended)', 'Move [it] / all'), ('Keep', 'Keep')], "the ask file's options")
    row = ask('Which one? [A / B]')
    eq((row['answers'][1]['value'], row['what']), ('Keep', 'Which one?'), 'it wins over a bracket, which is still not shown')
    for bad in ('x', [], [{'name': 'A'}], [{'name': 'A'}, 'B'], [{'name': 'A'}, {'name': 3}], [{'name': 'A'}, {'name': 'B', 'rec': 'yes'}]):
        f.write_text(json.dumps({'options': bad}), encoding='utf-8')
        eq([a['value'] for a in ask('Which one? [C / D]')['answers']], ['C', 'D'], f'{bad}: malformed, so the bracket')
    f.write_text(json.dumps({'options': opts, 'inputs': [{'key': 'a'}]}), encoding='utf-8')
    row = ask('Which one? [C / D]')
    eq((row['answers'], row['what']), ([], 'Which one? [C / D]'), 'an item with inputs: Done answers it, the bracket stays')
    f.unlink()
    row, _ = U.needs_rows([('BLOCKED', 'F2', '', 'Log in [A / B]', '', 'T', False)], dt.datetime.now())
    eq((said(row[0]), row[0]['what']), ([('Done', 'Done')], 'Log in [A / B]'), 'only a DECIDE has them')
    row = ask('Which look? [Full (recommended) / Small]')
    eq(U.need_options(row), ['Full (recommended)', 'Small'], "the chat's text lists them")
    with mock.patch.object(U, 'SEND', [lambda t: check(False, 'no session starts', t)]):
        eq(U.act('run_control', key='need_answer1', tid='D3', text='Full (recommended)')['ok'], False, 'the bare name only')
        r = U.act('run_control', key='need_answer1', tid='D3', text='Full', note='dark  too')  # the real plan confirm
    eq((r['ok'], r['gone'], r['argv'][-3:]), (True, 'D3', ['confirm', 'D3', 'Full: dark too']), 'a press: plan confirm, with the note')
    check('- [ ] **D3**' in (t := todo.read_text(encoding='utf-8')) and '): Full: dark too' in t, 'D3 is open with the answer', t)


def test_need_detail_f162(tmp: Path) -> None:
    """F162: real asks split into what to do and what to see, nothing lost; <notes>/asks/ID.json stands in for them, a
    broken, odd or oversized one is the fallback; the pictures a task names and the file's are found."""
    from agent_runner import need_detail as N
    got = {}
    for tid, (label, ask) in ASKS_F162.items():
        pieces = N.split_ask(ask, label in ('CONFIRM', 'BLOCKED'))
        eq(''.join(p for _, p in pieces), ask, f'{tid}: the pieces joined are the ask')
        got[tid] = N.detail(label, tid, ask, 'A task', '')
    for odd in ('', 'x', '  a; b  ', 'Pick: 1) a 2) b', 'Read (a; b: c', 'See https://x.y/z: ok. e.g. This one; then\nthat', '`a; b` then c'):
        eq(''.join(p for _, p in N.split_ask(odd)), odd, f'joined back: {odd!r}')
    b = got['B160']
    eq((b['said'], b['where'], b['summary']), ('Check this', 'iPhone, Safari', 'Reload, open a chat, tap the message box'), 'the card')
    eq(b['steps'], ['Reload, open a chat, tap the message box', 'Close the keyboard', 'Same in Talk, Home, Settings and a sheet.'], 'B160: the steps')
    eq(b['expect'], ['The header stays and the box rides up with no grey band.', 'It glides back.'], 'B160: what to see')
    eq(b['lead'], ['On an iPhone in Safari, after this lands and the run restarts'], 'B160: where and when')
    check('Chat and Home were already seen working on the iPhone 15 Pro' in b['notes'], 'B160: the rest is kept', b['notes'])
    eq((len(got['F154']['steps']), got['F154']['expect'], got['F154']['where']),
       (2, ['Taps still open rows, and holding a chat row still drags it'], 'iPhone'), 'F154')
    eq((got['F106h']['said'], len(got['F106h']['steps']), got['F106h']['expect']), ('Do this', 1, []), 'F106h: code after a colon is the same step')
    check('`run login copilot`' in got['F106h']['steps'][0], 'and it is kept', got['F106h'])
    eq((got['B163']['said'], got['B163']['steps']), ('Stuck', ['Waits for its Windows run']), 'B163')
    eq((len(got['B177']['steps']), len(got['B177']['expect'])), (3, 1), 'B177: then is a step, the colon what to see')
    eq((len(got['R6']['steps']), got['R6']['expect']), (3, ['Is the run still going?']), 'R6: (1) and (2)')
    eq(N.detail('DECIDE', 'F1', 'Which look: Full, Small?', '', '')['question'], 'Which look: Full, Small?', 'a question is one piece')
    for ask in ('Stuck: 1) do this. 2) do that', 'Stuck: (1) do this. (2) do that', 'Stuck: 1. do this. 2. do that - reply with what to do'):  # B797
        eq(''.join(p for _, p in N.split_ask(ask, False)), ask, f'joined back: {ask!r}')
        d = N.detail('STUCK', 'B9', ask, 'A task', '')
        eq((d['steps'], d['summary']), (['Do this.', 'Do that'], 'Do this.'), f'no step of Stuck alone: {ask!r}')
    for semi, do, see in (  # F162a1: after a colon each piece after a ';' is classed again
            ('Tap Save: it says Saved; tap Undo; the list returns', ['Tap Save', 'Tap Undo'], ['It says Saved', 'The list returns']),
            ('Tap Save: it says Saved; and the list returns; and tap Undo', ['Tap Save', 'And tap Undo'], ['It says Saved', 'And the list returns']),
            ('Tap Save: it says Saved; on Home, the list returns; in Talk, tap Undo', ['Tap Save', 'In Talk, tap Undo'],
             ['It says Saved', 'On Home, the list returns']),
            ('Tap Save: it says Saved; your words are sent; Talk stays quiet', ['Tap Save'], ['It says Saved', 'Your words are sent', 'Talk stays quiet']),
            ('Tap Save: it says Saved; tap Undo: rows come back', ['Tap Save', 'Tap Undo'], ['It says Saved', 'Rows come back'])):
        pieces = N.split_ask(semi)
        eq(''.join(p for _, p in pieces), semi, f'joined back: {semi!r}')
        eq([[N.shown(p) for k, p in pieces if k == kind] for kind in ('do', 'see')], [do, see], f'classed again: {semi!r}')
    repo = fake_run(tmp)
    notes = repo / '.runner'
    for d in ('asks', 'uploads'):
        (notes / d).mkdir(parents=True, exist_ok=True)
    png = b'\x89PNG\r\n\x1a\nfake'
    for f in ('asks/one.png', 'uploads/IMG_1.png', 'uploads/IMG_2.PNG', 'secret.png'):
        (notes / f).write_bytes(png)
    S.C.todo.write_text(TODO.replace('which layout', f'which layout, see {notes}/uploads/IMG_1.png and .runner/uploads/gone.png'), encoding='utf-8')
    d3 = lambda: next(n['detail'] for n in U.snapshot(up=False, now=NOW, links={})['needs'] if n['id'] == 'D3')  # noqa: E731
    plain = d3()
    eq([s['src'] for s in plain['shots']], ['uploads/IMG_1.png'], 'the picture its line names, only one that is there')
    js = notes / 'asks' / 'D3.json'
    js.write_text(json.dumps({'summary': 'Open both', 'where': 'iPad', 'steps': ['Open one', 7, ''], 'expect': ['Two tabs'], 'shots': [
        {'file': 'one.png', 'caption': 'Before'}, {'file': 'uploads/IMG_2.PNG'}, {'file': '../secret.png', 'caption': 'x'},
        {'file': str(notes / 'secret.png')}, 'x', {'caption': 'y'}]}), encoding='utf-8')
    full = d3()
    eq({k: full[k] for k in ('summary', 'where', 'steps', 'expect', 'lead')},
       {'summary': 'Open both', 'where': 'iPad', 'steps': ['Open one'], 'expect': ['Two tabs'], 'lead': []}, 'the file stands in')
    eq([(s['src'], s['caption']) for s in full['shots']], [('asks/one.png', 'Before'), ('uploads/IMG_2.PNG', ''),
                                                           ('uploads/IMG_1.png', 'Picture named in the task')], 'its pictures, none from outside')
    for bad in ('{', '[]', 'null', '"x"', '{"steps": 5, "shots": {}, "expect": null, "summary": []}', '[' * 100000, '{"a": "' + 'x' * N.FILE_MAX + '"}'):
        js.write_text(bad, encoding='utf-8')
        eq(d3(), plain, f'the fallback for {bad[:20]!r}')
    js.write_bytes(b'\xff\xfe\x00')
    eq(d3(), plain, 'and for one that is no text')


def test_decide_question_b223a(tmp: Path) -> None:
    """B223a: a DECIDE is a question with its background as paragraphs, no steps unless its ask file has them; a CONFIRM
    or BLOCKED keeps its steps. `needs` shows the question."""
    from agent_runner import need_detail as N, plan as P
    repo = fake_run(tmp)

    def row(ask: str, label: str = 'DECIDE') -> dict:
        return U.needs_rows([(label, 'D9', '', ask, '', 'T', False)], NOW)[0][0]
    need = lambda ask: P.needs_lines([('DECIDE', 'D9', '', ask, '', 'T', False)])[0]  # noqa: E731
    b221 = ('And a fix. This is finished, but held because R8 was research, which changes no product. "Ship them" merges it '
            'with the findings. "Queue them as their own task" keeps only the findings now and queues the rest. '
            f'Ship these changes? {P.RESEARCH_BUTTONS}')
    r = row(b221)
    d = r['detail']
    eq((d['question'], d['summary'], d['steps'], d['expect']), ('Ship these changes?', 'Ship these changes?', [], []), 'B221: one question, no steps')
    eq(d['lead'], [b221.split(' Ship these changes?')[0]], 'B221: the rest is its background, whole')
    eq(d['notes'], ['Reply with your answer'], 'its notes kept')
    eq([o['name'] for o in r['options']], [P.SHIP, P.QUEUE], 'its buttons')
    check(not any('[' in x for x in [*d['lead'], d['question'], *d['notes']]), 'no bracket repeated', d)
    eq(need(b221), 'D9 - Ship these changes?', 'needs shows the question')
    old = ('R90 is research, but its diff changes code (done.log), so it did not merge. Answer `follow-up` (the code is filed) or '
           '`merge anyway` (the code lands); the attempt is parked on wip/R90')
    d = row(old)['detail']
    eq((d['question'], d['steps']), ('R90 is research, but its diff changes code (done.log), so it did not merge.', []), 'an old ask: its first sentence, whole')
    eq((d['summary'], d['lead'], d['notes']), (d['question'], [old.split('did not merge. ')[1]], ['Reply with your answer']), 'the rest of it is its background')
    eq(need('pick a layout. Full is larger'), 'D9 - pick a layout', 'needs: the first sentence when nothing is asked')
    d = row('Pick a layout')['detail']
    eq((d['question'], d['lead']), ('Pick a layout', []), 'said whole in the question, so not again')
    for ask, want in (('It is slow; then keep it? Full is larger. Evidence is in the log', ('It is slow; then keep it?', ['Full is larger.'], 'Evidence is in the log')),
                      ('Keep it? (asked with `run ask`: your answer resumes its session)',
                       ('Keep it?', ['(asked with `run ask`: your answer resumes its session)'], None)),
                      ('The log is already kept, drop it?', ('The log is already kept, drop it?', [], None)),
                      ('Why? - a thing - another', ('Why?', ['- a thing - another'], None)),
                      ('Keep it? we would say yes', ('Keep it?', ['We would say yes'], None)),
                      ('Full? or Small?', ('Full? or Small?', [], None)),
                      ('Two looks. Keep it (or drop it?)', ('Keep it (or drop it?)', ['Two looks.'], None)),
                      ('Keep the log (why? it is old), then?', ('Keep the log (why? it is old), then?', [], None)),
                      ('Keep e.g. the log?', ('Keep e.g. the log?', [], None)),
                      ('It is old. Which? https://example.com/b', ('Which?', ['It is old.', 'https://example.com/b'], None)),
                      ('One.\n\nTwo. Keep it?', ('Keep it?', ['One.', 'Two.'], None))):
        d = row(ask)['detail']
        eq((d['question'], d['lead'], d['notes']), (*want[:2], [n for n in (want[2], 'Reply with your answer') if n]), ask)
    eq(need('It is old. Keep e.g. the log? Yes is simpler'), 'D9 - Keep e.g. the log?', 'needs: the whole question')
    eq(need(f'Background. {"Is it so " * 12}or not?'), f'D9 - {"Is it so " * 12}or not?', 'a long one is not cut')
    f = repo / '.runner' / 'asks' / 'D9.json'
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({'summary': 'Choose a look', 'steps': ['Open both'], 'expect': ['Two'], 'options': [{'name': 'Full'}, {'name': 'Small'}]}), encoding='utf-8')
    r = row('Two are ready. Which look? [A / B]')
    d = r['detail']
    eq((d['question'], d['summary'], d['steps'], d['expect'], d['lead']), ('Which look?', 'Which look?', ['Open both'], ['Two'], []), 'an ask file: its steps')
    eq([o['name'] for o in r['options']], ['Full', 'Small'], 'and its options')
    d = row('The look')['detail']
    eq((d['question'], d['summary']), ('Choose a look',) * 2, 'no question mark: the file summary')
    eq(need('The look'), 'D9 - Choose a look', 'in needs too')
    f.unlink()
    for label in ('CONFIRM', 'BLOCKED'):
        d = row('Open Home; tap Undo: the list returns', label)['detail']
        eq((d['steps'], d['expect'], d['lead'], d['question'], d['summary']),
           (['Open Home', 'Tap Undo'], ['The list returns'], [], '', 'Open Home'), f'{label}: unchanged')


def test_whole_b793b(tmp: Path) -> None:
    """B793b: detail's title is the task's first sentence whole, and its summary the whole first step or question, for each label, every step whole; the
    row's ask_short stays cut."""
    fake_run(tmp)
    title = 'Show the whole title of a task ' + 'that has many words ' * 6 + 'up to here'
    step = 'Open the settings of the app (the gear at the top) and read docs/a/b.md ' + 'and look at each row ' * 8 + 'to the end'
    check(len(title) >= 150, 'the fixture is long', len(title))
    for label in ('CONFIRM', 'DECIDE', 'BLOCKED', 'STUCK'):
        for ask in (step, step + '?') if label == 'DECIDE' else (step,):
            row = U.needs_rows([(label, 'D9', '', ask, '', title + '. More words here', False)], NOW)[0][0]
            d = row['detail']
            eq(d['title'], title, f'{label}: the title')
            eq(d['summary'], ask, f'{label}: the summary')
            check(len(row['ask_short']) <= U.ASK_SHORT, f'{label}: ask_short is cut', row['ask_short'])
        if label in ('CONFIRM', 'BLOCKED'):
            d = U.needs_rows([(label, 'D9', '', f'1) {step}. 2) {step}', '', title, False)], NOW)[0][0]['detail']
            eq((d['summary'], d['steps']), (step + '.', [step + '.', step]), f'{label}: two long steps, each whole')


def test_old_script_c37a(tmp: Path) -> None:
    """C37a: a BLOCKED item with an old <notes>/wizards/ID.sh shows its steps and links, read as text, nothing run."""
    from agent_runner import need_detail as N
    repo = fake_run(tmp)
    w = repo / '.runner' / 'wizards'
    w.mkdir(parents=True, exist_ok=True)
    mark = repo / 'ran'
    (w / 'D3.sh').write_text(f'#!/bin/bash\nstage() {{ touch {mark}; }}\n# STAGES: author this section.\n'
                             f'stage "Get the key"\nopen_url https://example.com/keys\nsay "Create a key, see https://example.com/help"\n'
                             f'step "Copy it"\ntouch {mark}\n', encoding='utf-8')
    d = N.detail('BLOCKED', 'D3', 'Give the key', 'T', '')
    eq(d['steps'], ['Get the key', 'Open this', 'Create a key, see https://example.com/help', 'Copy it'], 'its steps')
    eq([m.get('link') for m in d['step_more']], [None, 'https://example.com/keys', 'https://example.com/help', None], 'its links')
    check(not mark.exists(), 'nothing ran')
    check(not any('cmd' in m for m in d['step_more']), 'no run line')
    eq(N.detail('CONFIRM', 'D3', 'Check it', 'T', '')['steps'], ['Check it'], 'only a BLOCKED item reads it')


def test_part_of_part_b199(tmp: Path) -> None:
    """B199: a part of a part (F162a2) is a task id to every call that takes one; what is no id is still refused."""
    repo = fake_run(tmp)
    todo, asks = repo / 'plan' / 'TODO.md', repo / '.runner' / 'asks'
    todo.write_text(TODO.replace('**D3**', '**F162a2**'), encoding='utf-8')
    asks.mkdir(exist_ok=True)
    (asks / 'F162a2.json').write_text(json.dumps({'inputs': [{'key': 'note'}]}), encoding='utf-8')
    with mock.patch.object(U, 'agent_said', lambda tid: f'{tid} said'):
        eq(U.need_why('F162a2').get('text'), 'F162a2 said', 'Why it waits')
    check('F162a2' in U.task_text('F162a2').get('text', ''), "the task's text")
    with mock.patch.object(U, 'new_control', lambda text, wait: {'ok': True, 'text': text}):
        check('F162a2' in U.need_chat('F162a2').get('text', ''), 'Chat')
    check('F162a2' in U.control_argv('task_drop', tid='F162a2'), 'a run control')
    for bad in ('', None, 'f162a2', 'F', '162', 'F162-a', 'F162 a2', 'F162a2\n', '--F162a2'):
        eq([U.need_why(bad)['ok'], U.need_give(bad, {'note': 'x'}).get('code')], [False, 2], f'no task id: {bad!r}')
    r = U.need_give('F162a2', {'note': 'the top one'})
    eq((r['ok'], r.get('gone')), (True, 'F162a2'), 'its inputs are sent')
    check('- [ ] **F162a2**' in todo.read_text(encoding='utf-8'), 'and it reopens', todo.read_text(encoding='utf-8'))

def test_frame_kept_b860(tmp: Path) -> None:
    """B860: a concept card's framed options page is kept over a redraw: the box is changed in place, not written over"""
    page = Path(__file__).resolve().parent.parent / 'agent_runner' / 'page'
    plan = (page / '140-plan.js').read_text(encoding='utf-8')
    shared = (page / '010-shared.js').read_text(encoding='utf-8')
    check('data-keep="cframe:${id}"' in plan, 'the frame is marked to keep')
    check("querySelector('iframe[data-keep]')" in shared and 'morphKids(el,t.content)' in shared, 'setHTML morphs a box holding one')
    check("o.dataset.keep===n.dataset.keep&&o.getAttribute('src')===n.getAttribute('src')" in shared, 'the same frame is left alone')

def test_concept_item_f197b1(tmp: Path) -> None:
    """F197b1: one concept gives one item shape in needs and in concepts, waiting or a kept page; news on both"""
    kept = {'id': 'K7', 'concept': 'K7', 'title': 'an old page', 'url': '', 'copy': '', 'page': True, 'waits': False,
            'history': True}
    news = {'version': '2', 'news': 'updated', 'news_words': 'Updated today'}
    with mock.patch.object(U, 'page_rows', lambda *a: [dict(kept)]), \
            mock.patch.object(U, 'concept_row_news', lambda *a: dict(news)), \
            mock.patch.object(U, 'concept_copy', lambda k: ''):
        needs, concepts = U.needs_rows([('CONCEPT', 'F9', 'K2', 'waiting for your OK', '', 'a title', False, '')], NOW)
    keys = set(U.ITEM_KEYS) | {'news', 'news_words'}
    eq([sorted(c['item']) for c in concepts], [sorted(keys)] * 2, 'every Concepts row carries the same item shape')
    item = concepts[0]['item']
    eq({k: item[k] for k in U.ITEM_KEYS}, {k: needs[0].get(k, item['acts'] if k == 'acts' else None) for k in U.ITEM_KEYS},
       'a waiting concept: the item is its Needs you entry')
    eq((needs[0]['news'], needs[0]['news_words']), ('updated', 'Updated today'), 'the Needs you item shows Updated too')
    eq((concepts[1]['item']['label'], concepts[1]['item']['what'], concepts[1]['item']['answers']),
       ('CONCEPT', 'an old page', []), 'a kept page with no Needs you entry still gets one')

def test_open_chat_f209c(tmp: Path) -> None:
    """F209c: a Needs you row and a Concepts row name the open chat about them (the latest begun); none: no 'chat'"""
    from agent_runner import control_settled as Z
    live = [(3, 's3', {'begun': 10.0}, {'F9'}), (5, 's5', {'begun': 20.0}, {'F9', 'K2'}), (7, 's7', {'begun': 5.0}, {'B1'})]
    with mock.patch.object(Z, 'live', lambda: live), mock.patch.object(U, 'page_rows', lambda *a: []), \
            mock.patch.object(U, 'concept_copy', lambda k: ''):
        needs, concepts = U.needs_rows([('CONCEPT', 'F9', 'K2', 'waiting for your OK', '', 'a title', False, ''),
                                        ('DECIDE', 'B4', '', 'which?', '', 'other', False, '')], NOW)
    eq((needs[0].get('chat'), concepts[0].get('chat'), concepts[0]['item'].get('chat')), (5, 5, 5), 'the latest open chat')
    check('chat' not in needs[1], 'no open chat: no chat named')
    with mock.patch.object(Z, 'live', lambda: []):
        eq(U.open_chats({'F9'}), {}, 'nothing open: nothing named')


def test_option_tasks_f192d3(tmp: Path) -> None:
    """F192d3: a DECIDE option with stored tasks shows how many, a press queues them (once) instead of leaving them to
    a session, and an answered question's stored tasks go."""
    import os
    from agent_runner import asks, option_tasks
    repo = fake_run(tmp)
    todo = repo / 'plan' / 'TODO.md'
    todo.write_text(todo.read_text(encoding='utf-8').replace('DECIDE: which layout https://claude.ai/artifact/abc',
                                                             'DECIDE: Which layout? [Full / Small]'), encoding='utf-8')
    option_tasks.store('Which layout?', {'Full': [['F', 'a'], ['F', 'b']], 'Small': []}, 'q1')
    row = U.row_of('need', 'D3')
    eq([(a['value'], a.get('tasks')) for a in row['answers']], [('Full', 2), ('Small', None)], 'the count, options with tasks')
    check('queues 2 tasks' in row['answers'][0]['label'], 'the label says it', row['answers'])
    added: list = []
    from agent_runner import plan
    real = plan.main
    with mock.patch.object(plan, 'main', lambda a: added.append(a[1:]) or 0 if a[:1] == ['add'] else real(a)), \
            mock.patch.object(U, 'SEND', [lambda t: check(False, 'no session starts', t)]):
        r = U.act('run_control', key='need_answer1', tid='D3', text='Full')
    eq((r['ok'], r.get('queued'), added), (True, 2, [['F', 'a'], ['F', 'b']]), 'a press queues the tasks')
    check('queued already' in todo.read_text(encoding='utf-8'), 'the answer says they are queued')
    eq(option_tasks.stored('Which layout?'), {}, 'and they are dropped')
    p = option_tasks.store('Old question?', {'A': [['F', 'x']]}, 'q2')
    option_tasks.store('Which layout?', {'A': [['F', 'y']]}, 'q3')
    asks.drop_option_tasks(S.C)
    check(p.exists(), 'a just stored question is kept')
    for f in p.parent.glob('*.json'):
        os.utime(f, (1, 1))
    todo.write_text(todo.read_text(encoding='utf-8') + '- [~] **D4** x BLOCKED: DECIDE: Which layout? [A / B]\n', encoding='utf-8')
    eq(asks.drop_option_tasks(S.C), 1, 'an old question no DECIDE asks any more is dropped')
    eq((p.exists(), option_tasks.counts('Which layout?')), (False, {'A': 1}), 'one still asked stays')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_option_tasks_f192d3), in_tmp(test_open_chat_f209c), in_tmp(test_concept_item_f197b1), in_tmp(test_frame_kept_b860), in_tmp(test_decide_options_f181c), in_tmp(test_decide_question_b223a), in_tmp(test_part_of_part_b199), in_tmp(test_whole_b793b), in_tmp(test_old_script_c37a), in_tmp(test_need_detail_f162), in_tmp(test_need_answers_c33)]))
