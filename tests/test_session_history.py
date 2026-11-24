"""F191a: the session history (agent_runner/session_history.py) and its endpoint, /history/NAME.

    python3 tests/test_session_history.py
"""
from __future__ import annotations

import io
import json
from pathlib import Path
from unittest import mock

from _check import check, eq, report
from _web import fake_repo, get, in_tmp

from agent_runner import session_history as H
from agent_runner import ui_model as U
from agent_runner import web as W

AT = '2026-11-23T10:00:00.500Z'


def say(text: str, **kw) -> dict:
    return {'type': 'assistant', 'timestamp': AT, 'message': {'content': [{'type': 'text', 'text': text}]}, **kw}


def you(text, **kw) -> dict:
    return {'type': 'user', 'timestamp': AT, 'message': {'role': 'user', 'content': text}, **kw}


def call(cid: str, name: str, **args) -> dict:
    return {'type': 'assistant', 'uuid': f'u-{cid}', 'timestamp': AT,
            'message': {'content': [{'type': 'tool_use', 'id': cid, 'name': name, 'input': args}]}}


def result(cid: str, content='', made=None, error: bool = False) -> dict:
    return {'type': 'user', 'toolUseResult': made, 'message': {'content': [
        {'type': 'tool_result', 'tool_use_id': cid, 'content': content, 'is_error': error}]}}


def write(path: Path, rows: list[dict], mode: str = 'w') -> Path:
    with path.open(mode, encoding='utf-8', newline='\n') as f:
        f.writelines(json.dumps(r) + '\n' for r in rows)
    return path


def at(path) -> mock._patch:
    return mock.patch.object(U, 'transcript_of', return_value=str(path))


def words(g: dict) -> list[str]:
    return [e.get('text') or e.get('arg') or '' for e in g['entries']]


PATCH = [{'oldStart': 4, 'oldLines': 2, 'newStart': 4, 'newLines': 3, 'lines': [' a', '-b', '+c', '+d']}]
RECORDED = [  # the shapes of a recorded Claude Code 2.1 transcript
    {'type': 'mode', 'mode': 'normal'},
    {'type': 'attachment', 'attachment': {'type': 'date', 'date': '2026-11-23'}},
    you('<pasted_content id="1a">\nfix it\n</pasted_content>'),
    you([{'type': 'image'}, {'type': 'text', 'text': '[Image #1] see'}]),
    you('meta', isMeta=True),
    {'type': 'assistant', 'message': {'content': [{'type': 'thinking', 'thinking': 'hm'}, {'type': 'text', 'text': 'On it.'}]}},
    call('t1', 'Bash', command='ls\npwd'), call('t2', 'Read', file_path='a.py'),
    result('t2', '1\tx\n2\ty', {'type': 'text', 'file': {'numLines': 2}}),
    result('t1', 'x (files that changed …)', {'stdout': 'l1\nl2\nl3\nl4\nl5', 'stderr': '', 'bashEditDiff': {
        'files': [{'filePath': 'plan/TODO.md', 'hunks': PATCH}]}}),
    call('t3', 'Edit', file_path='a.py', old_string='b', new_string='c\nd'),
    result('t3', 'updated', {'filePath': 'a.py', 'structuredPatch': PATCH}),
    call('t4', 'Write', file_path='n.py', content='1\n2'), result('t4', 'created', {'type': 'create', 'structuredPatch': []}),
    call('t5', 'Bash', command='false'), result('t5', 'Exit code 1\nno', 'Error: Exit code 1\nno', True),
    call('t6', 'Bash', command='true'), result('t6', '', {'stdout': '', 'stderr': ''}),
    call('t7', 'Grep', pattern='x', path='src'), result('t7', 'a.py', {'numFiles': 1}),
    call('t8', 'Agent', description='Look', subagent_type='review'), result('t8', 'secret', {'isAsync': True}),
    call('t9', 'mcp__easel__chart', title='T'),
    result('t9', "The user doesn't want to proceed with this tool use.", 'User rejected tool use', True),
    say('sub', isSidechain=True),
    {'type': 'attachment', 'attachment': {'type': 'queued_command', 'commandMode': 'prompt', 'prompt': 'and this'}},
    {'type': 'attachment', 'attachment': {'type': 'queued_command', 'commandMode': 'task-notification',
                                          'prompt': '<task-notification>\n<summary>Agent done</summary>\n</task-notification>'}},
    you('From the runner, not the person: F1 was changed'),
    you('<command-name>/usage</command-name>\n<command-message>usage</command-message>\n<command-args></command-args>'),
    {'type': 'system', 'subtype': 'local_command', 'content': '<local-command-stdout>\x1b[1m3%\x1b[0m used</local-command-stdout>'},
    {'type': 'system', 'subtype': 'stop_hook_summary', 'content': ''},
    {'type': 'system', 'subtype': 'away_summary', 'content': 'Recap.'},
    say('API Error', isApiErrorMessage=True),
    you([{'type': 'text', 'text': '[Request interrupted by user]'}]),
    {'type': 'system', 'subtype': 'turn_duration', 'durationMs': 6139},
    {'type': 'attachment', 'attachment': {'type': 'hook_blocking_error', 'hookName': 'Stop', 'blockingError': {'blockingError': 'not yet'}}},
]


def test_entries(tmp: Path) -> None:
    """A recorded transcript: what is in, in order, and each result folded with its call."""
    t = write(tmp / 'r.jsonl', RECORDED)
    with at(t):
        g = H.history('c2')
    es = g['entries']
    eq([(e['kind'], e.get('name') or e.get('what') or e.get('text')) for e in es], [
        ('you', 'fix it'), ('you', '[Image #1] see'), ('say', 'On it.'), ('tool', 'Bash'), ('tool', 'Read'),
        ('tool', 'Update'), ('tool', 'Write'), ('tool', 'Bash'), ('tool', 'Bash'), ('tool', 'Search'),
        ('tool', 'review'), ('tool', 'easel - chart (MCP)'), ('you', 'and this'), ('note', 'event'),
        ('you', 'From the runner, not the person: F1 was changed'), ('you', '/usage'), ('note', 'output'),
        ('note', 'recap'), ('note', 'error'), ('note', 'interrupted'), ('note', 'turn'), ('note', 'hook')],
       'order; meta, thinking, subagents and bookkeeping left out')
    tools = {e['call']: e for e in es if e['kind'] == 'tool'}

    def folded(cid: str, *keys: str) -> tuple:
        return tuple(tools[cid].get(k) for k in keys)
    eq(folded('t1', 'arg', 'state', 'text', 'show', 'lines'), ('ls\npwd', 'ok', 'l1\nl2\nl3\nl4\nl5', 3, 5),
       'a command: 3 lines shown, + 2 lines; its own output, not the words for the model')
    diff = [{'file': 'plan/TODO.md', 'added': 2, 'removed': 1, 'cut': 0,
             'hunks': [{'old': 4, 'new': 4, 'lines': [' a', '-b', '+c', '+d']}]}]
    eq(tools['t1']['diff'], diff, 'the files a command changed')
    eq(folded('t2', 'summary', 'show', 'lines', 'group'), ('Read 2 lines', 0, 2, 'read'), 'a read')
    eq(folded('t3', 'arg', 'summary', 'show'), ('a.py', 'Added 2 lines, removed 1 line', 0), 'an edit')
    eq(tools['t3']['diff'], [{**diff[0], 'file': 'a.py'}], "an edit's diff")
    eq(folded('t4', 'summary', 'text', 'show'), ('Wrote 2 lines to n.py', '1\n2', 2), 'a new file')
    eq(folded('t5', 'state', 'text', 'show'), ('error', 'Error: Exit code 1\nno', 2), 'a failure')
    eq(folded('t6', 'summary', 'lines'), ('(No output)', 0), 'no output')
    eq(folded('t7', 'arg', 'summary', 'group'), ('pattern: "x", path: "src"', 'Found 1 file', 'search'), 'a search')
    eq(folded('t8', 'summary', 'text'), ('Backgrounded agent', ''), 'a background agent')
    eq(folded('t9', 'state', 'summary'), ('error', 'Interrupted'), 'a refused call')
    eq((es[1]['images'], es[14]['from'], es[15].get('command'), es[16]['text'], es[20]['ms']),
       (1, 'runner', True, '3% used', 6139), 'images, the runner, a slash command, its output, how long')
    check(es[0]['at'] == 1795428000.5 and es[3]['id'] == 'u-t1:0', 'when, and an id that stays', es[0])
    check(not any(k.startswith('_') for e in es for k in e), 'nothing raw in an answer')
    eq((g['ok'], g['before'], g['reset'], g['more']), (True, '', False, False), 'a whole history')


def test_paging(tmp: Path) -> None:
    """Newest first, older on demand with nothing lost or twice, a call and its result never apart."""
    rows: list[dict] = []
    for i in range(40):
        rows += [you(f'p{i}'), call(f'a{i}', 'Bash', command=f'c{i}'), call(f'b{i}', 'Bash', command=f'd{i}'),
                 result(f'a{i}', f'o{i}'), result(f'b{i}', f'q{i}'), say(f's{i}')]
    t = write(tmp / 'p.jsonl', rows)
    with at(t), mock.patch.object(H, 'BLOCK', 37):
        whole = H.history('c2', limit=300)
        for limit in (1, 2, 3, 7):
            g = H.history('c2', limit=limit)
            eq(words(g)[-1], 's39', f'the newest page first (of {limit})')
            all_, pages = g['entries'], 1
            while g['before']:
                g = H.history('c2', before=g['before'], limit=limit)
                all_, pages = g['entries'] + all_, pages + 1
            eq(all_, whole['entries'], f'pages of {limit} are the whole, each call with its result')
            check(pages > 1, 'in pages')
    eq(len(whole['entries']), 160, 'every entry')
    check(all(e['state'] == 'ok' for e in whole['entries'] if e['kind'] == 'tool'), 'every call has its result')


def test_since(tmp: Path) -> None:
    """What was written after a mark: a result of a call already given, a line still being written, a long catch-up."""
    t = write(tmp / 's.jsonl', [you('go'), call('x', 'Read', file_path='a.py')])
    with at(t):
        g = H.history('c2')
        eq([e.get('state') for e in g['entries']], [None, 'running'], 'a call at work')
        eq(H.history('c2', since=g['since'])['entries'], [], 'nothing new')
        with t.open('a', encoding='utf-8') as f:
            f.write('{"type": "assis')
        n = H.history('c2', since=g['since'])
        eq((n['entries'], n['since']), ([], g['since']), 'half a line waits')
        t.write_bytes(t.read_bytes()[:-len('{"type": "assis')])
        write(t, [result('x', '1\tq'), say('read it')], 'a')
        n = H.history('c2', since=g['since'])
        eq([(e['kind'], e.get('call'), e.get('summary'), e.get('text')) for e in n['entries']],
           [('result', 'x', 'Read 1 line', '1\tq'), ('say', None, None, 'read it')], 'the result, worded by its call')
        write(t, [say(f'n{i}') for i in range(25)], 'a')
        got, mark, asks = [], n['since'], 0
        while True:
            n = H.history('c2', since=mark, limit=10)
            got, mark, asks = got + words(n), n['since'], asks + 1
            if not n['more']:
                break
        eq((got, asks), ([f'n{i}' for i in range(25)], 3), "a long catch-up comes in answers, 'more' till the last")
        old = H.history('c2', limit=1)
        write(t, [call('y', 'Bash', command='z'), you('stop'), say('ok')], 'a')
        end = H.history('c2', limit=2)
        check(old['before'] and H.history('c2', before=end['before'], limit=1)['entries'][0]['state'] == 'stopped',
              'a call left with no result on an older page is not at work')


def test_fresh(tmp: Path) -> None:
    """A /clear (another transcript), one written anew, a compaction, no transcript, a mark that is none."""
    a, b = write(tmp / 'a.jsonl', [you('old'), say('x' * 500)]), write(tmp / 'b.jsonl', [you('new')])
    with at(a):
        mark = H.history('c2')['since']
    with at(b):
        for kw in ({'since': mark}, {'before': mark}, {'since': 'junk'}, {'since': 'b:-1'}, {'before': 'b:999999'}):
            g = H.history('c2', **kw)
            eq((words(g), g['reset']), (['new'], True), f'the new transcript whole, and drop the rest: {kw}')
        check(not H.history('c2')['reset'], 'the first ask resets nothing')
    c = write(tmp / 'c.jsonl', [
        you('before'), {'type': 'system', 'subtype': 'compact_boundary', 'content': 'Conversation compacted'},
        you('This session is being continued …', isCompactSummary=True, isVisibleInTranscriptOnly=True), say('after')])
    with at(c):
        eq([(e['kind'], e.get('text')) for e in H.history('c2')['entries']],
           [('you', 'before'), ('note', 'Conversation compacted'), ('say', 'after')],
           'a compaction is a note; what came before it stays, its summary is left out')
    with mock.patch.object(U, 'transcript_of', return_value=''):
        g = H.history('s3')
    check(not g['ok'] and g['entries'] == [] and 'no transcript' in g['out'], 'no transcript: said', g)
    with at(tmp / 'gone.jsonl'):
        check(not H.history('c2')['ok'], 'a transcript that went')
    with at(a):
        check(not H.history('../c2')['ok'], 'only a chat or a slot')
    with at(write(tmp / 'e.jsonl', [])):
        g = H.history('c2')
        eq((g['ok'], g['entries'], g['before']), (True, [], ''), 'an empty one')


def test_long(tmp: Path) -> None:
    """A page of a long transcript reads its own part only, and a line longer than a page's budget still moves on."""
    t = tmp / 'l.jsonl'
    write(t, [say(f'w{i} ' + 'x' * 2000) for i in range(6000)])
    read = [0]

    class Counted(io.FileIO):
        def read(self, n=-1):
            d = super().read(n)
            read[0] += len(d)
            return d

        def readline(self, n=-1):
            d = super().readline(n)
            read[0] += len(d)
            return d
    with at(t), mock.patch.object(H, 'open', lambda p, m: Counted(p), create=True):
        g = H.history('c2')
        eq(len(g['entries']), H.PAGE, 'a page')
        check(read[0] < 1_500_000, 'the newest page of 12 MB reads under 1.5 MB', read[0])
        read[0] = 0
        H.history('c2', before=g['before'])
        check(read[0] < 1_500_000, 'and so does an older one', read[0])
        read[0] = 0
        write(t, [say('one more')], 'a')
        eq(words(H.history('c2', since=g['since'])), ['one more'], 'the new line')
        check(read[0] < 600_000, 'an ask for what is new reads little', read[0])
    big = write(tmp / 'big.jsonl', [you('first'), {'type': 'blob', 'x': 'y' * 5000}, say('last')])
    with at(big), mock.patch.object(H, 'PAGE_BYTES', 100), mock.patch.object(H, 'PAIR_BYTES', 100):
        g, got = H.history('c2'), []
        for _ in range(9):
            got = words(g) + got
            if not g['before']:
                break
            g = H.history('c2', before=g['before'])
        eq(got, ['first', 'last'], 'a line longer than the budget is passed')


def test_endpoint(tmp: Path) -> None:
    """GET /history/NAME: the page and its marks in the query, with the token only, as the feed."""
    fake_repo(tmp)
    token = W.web_token()
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {'queue': []})
    base = f'http://127.0.0.1:{srv.server_address[1]}'
    t = write(tmp / 'w.jsonl', [say(f'm{i} é') for i in range(5)])
    try:
        with at(t):
            g = json.loads(get(f'{base}/history/c6?t={token}&n=2')[1])
            eq((g['name'], words(g)), ('c6', ['m3 é', 'm4 é']), 'the newest page')
            o = json.loads(get(f'{base}/history/c6?t={token}&n=2&before={g["before"]}')[1])
            eq(words(o), ['m1 é', 'm2 é'], 'an older one')
            eq(json.loads(get(f'{base}/history/c6?t={token}&since={g["since"]}')[1])['entries'], [], 'nothing new')
            eq(len(json.loads(get(f'{base}/history/c6?t={token}&n=junk')[1])['entries']), 5, 'a size that is none')
            eq(get(f'{base}/history/c6')[0], get(f'{base}/feed/c6')[0], 'without the token, as the feed')
            eq(get(f'{base}/history/c6')[0], 403, 'refused')
        with mock.patch.object(U, 'transcript_of', return_value=''):
            check(not json.loads(get(f'{base}/history/s9?t={token}')[1])['ok'], 'no transcript: not ok, no error page')
    finally:
        srv.stop()


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_entries), in_tmp(test_paging), in_tmp(test_since), in_tmp(test_fresh),
                             in_tmp(test_long), in_tmp(test_endpoint)]))
