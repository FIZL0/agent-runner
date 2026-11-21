#!/usr/bin/env python3
"""B88: `since` folds the run log into a digest short enough to say back on a phone.

    python3 tests/test_since.py        (no network, no repo; well under a second)

One line per task with its last state under Started / Landed / Stuck, run idle and stopped repeats folded into
one last run state, a cap past which Landed names the rest by id (each landed task named once) and a last line
that asks for the full list (B89: never a command, the person may be on a phone); the control brief and the
/since skill always hand `since --all` over as a page.
"""
from __future__ import annotations

import datetime as dt

from _check import check, eq, report

from agent_runner import status as S  # noqa: E402

NOW = dt.datetime(2026, 11, 21, 9, 0, 0)
START = dt.datetime(2026, 11, 20, 0, 0, 0)


def ev(t: str, kind: str, tid: str = '', **kw) -> dict:
    return {'time': f'2026-11-20T{t}:00', 'kind': kind, 'id': tid, 'text': '', **kw}


def test_fold() -> None:
    titles = {'B1': 'Fix the flicker', 'F2': 'Board window', 'B3': 'Slow merge', 'R4': 'Check the push'}
    log = [ev('01:00', S.EV_STARTED, 'B1'), ev('01:05', S.EV_IDLE), ev('01:10', S.EV_STOPPED),
           ev('01:11', S.EV_STARTED, 'B1'), ev('01:20', S.EV_LANDED, 'B1'), ev('01:21', S.EV_IDLE),
           ev('02:00', S.EV_STARTED, 'F2'), ev('02:10', S.EV_PARKED, 'F2', why='tests fail. More words'),
           ev('02:20', S.EV_STARTED, 'F2'), ev('02:30', S.EV_LANDED, 'F2'),
           ev('03:00', S.EV_STARTED, 'B3'), ev('03:10', S.EV_PARKED, 'B3', why='merge conflict'),
           ev('04:00', S.EV_STARTED, 'R4'), ev('04:01', S.EV_CONTEXT, 'R4', peak=160, warn=150),
           ev('05:00', S.EV_RELEASED, text='agent-runner 0.57.0 released: A release kind.'),
           ev('06:00', S.EV_IDLE), ev('06:30', S.EV_STOPPED)]
    text, last = S.since_digest(log, START, titles, NOW)
    eq(text.splitlines(), [
        'since yesterday 00:00: 1 started, 2 landed, 1 stuck',
        'Started:', '  Check the push [R4]',
        'Landed:', '  Board window [F2]', '  Fix the flicker [B1]',
        'Stuck:', '  Slow merge (merge conflict) [B3]',
        'Run:', '  agent-runner 0.57.0 released: A release kind. (yesterday 05:00)',
        '  last: run stopped (yesterday 06:30)'], 'one line per task, its last state; run noise folded')
    eq(last, '2026-11-20T06:30:00', 'the newest stamp read, for the mark')
    raw, _ = S.since_text(log, START, titles, NOW)
    check(raw.count('run idle') == 3 and raw.count('[B1]') == 3, '--all (digest off) keeps the raw log', raw)
    eq(S.since_text(log, START, titles, NOW, digest=True)[0], text, 'since_text(digest=True) is the digest')
    eq(S.since_digest(log, NOW, titles, NOW)[0], 'nothing new since 09:00', 'nothing after start')


def test_cap() -> None:
    log, titles = [], {}
    for i in range(200):
        tid = f'T{i}'
        titles[tid] = f'A task title that runs on a while, number {i}'
        log += [ev(f'{i // 60 + 1:02d}:{i % 60:02d}', S.EV_STARTED, tid),
                ev(f'{i // 60 + 1:02d}:{i % 60:02d}', S.EV_LANDED, tid), ev(f'{i // 60 + 1:02d}:{i % 60:02d}', S.EV_IDLE)]
    log += [ev('20:00', S.EV_STARTED, 'B9'), ev('20:01', S.EV_PARKED, 'B9', why='tests fail')]
    log += [ev(f'21:{m:02d}', S.EV_RELEASED, text=f'agent-runner 0.{m}.0 released: more words') for m in range(8)]
    text, _ = S.since_digest(log, START, titles, NOW)
    lines = text.splitlines()
    check(len(text.encode()) < 2048, f'200 landed fit in under 2KB ({len(text.encode())} bytes)', text)
    check(sum(1 for l in lines if l.startswith('  ') and l.endswith(']')) <= S.DIGEST_CAP, 'at most the cap titled')
    named = [i for i in range(200) if len([l for l in lines if f'[T{i}]' in l or f' T{i},' in l + ',']) == 1]
    eq(len(named), 200, 'every landed task named exactly once')
    check(any('(tests fail) [B9]' in l for l in lines), 'the cap spares Stuck', text)
    eq(lines[-1], S.DIGEST_MORE, 'cut: ends asking for the full list')
    check(not any(w in lines[-1] for w in ('since', '--', 'run ', '`')), 'B89: the last line names no command', lines[-1])
    eq(text.count('run idle'), 1, 'run idle once, as the last run state')
    eq((text.count(' released: '), '  …and 5 earlier' in lines), (S.DIGEST_RUN, True), 'run lines capped too')


def test_full_list_as_page() -> None:
    """B89: the brief and /since run `since --all` themselves and hand it over as a page, never as a command."""
    from agent_runner import guide as G
    brief = G.CONTROL.format(repo='r', cmd='RUN', log='l', watch='w', needs='n', answer='a')
    check('/since' in brief and 'guide output' in brief, 'B98: the brief points /since at `guide output`')
    brief = G.control_topic('output', 'RUN', 'n')  # B98: which holds the rules
    skill = G.control_skills('RUN')['since']
    for name, text in (('brief', brief), ('/since', skill)):
        check(all(w in text for w in ('since --all', 'Artifact', 'SendUserFile', 'link')),
              f'{name}: since --all handed over as a page', text[-600:])
    check(all(w in brief for w in ('status -n', 'plan waiting --all', S.DIGEST_MORE)),
          'brief: the same for other long output, and the digest\'s ask word for word')
    check('run `RUN since --all $ARGUMENTS`' in skill and 'every time' in skill and 'short digest' not in skill,
          '/since: always the full list as a page, not a digest first', skill)
    check('"/since", "what happened?": always the full list as a page' in brief and 'every time' in brief,
          'brief: /since always the full list as a page')
    check('Artifact' in G.control_skills('RUN')['run'], '/run: long status output as a page too')
    eq(S.since_start('2026-11-20T21:02', None, NOW), dt.datetime(2026, 11, 20, 21, 2),
       'since --all takes the date-time the brief tells the session to pass')


def main() -> int:
    return report([test_fold, test_cap, test_full_list_as_page])


if __name__ == '__main__':
    import sys
    sys.exit(main())
