"""F192d2: one tap queues the work, page side: the card's count, the tap after the hold calls POST /queue, Undo adds nothing.

    python3 tests/test_web_question_queue.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from _check import check, eq, report
from _web import in_tmp
from test_web_question import DRIVER

from agent_runner import web as W  # noqa: E402

ASK = {'id': 'u1', 'question': 'Which look?', 'options': [{'name': 'Full', 'rec': True}, {'name': 'Small', 'rec': False}],
       'tasks': {'Full': 2}}

FETCH = r"""
const posts = []; let answer = {ok: true, out: '“Full”: queued 2 tasks: a; b'};
const tq = p => p;
const fetch = async (u, o) => { posts.push([u, JSON.parse(o.body)]); return {json: async () => answer} };
"""


def run(tmp: Path, steps: str) -> list | None:
    if not shutil.which('node'):
        print('  (no node here: the queue tap test is skipped)')
        return None
    js = ''.join((W.PAGE_DIR / f).read_text(encoding='utf-8') for f in ('023-question.logic.js', '024-questionchat.logic.js', '095-question.js'))
    f = tmp / 'queue.js'
    f.write_text(DRIVER.replace('PAGE', FETCH + js).replace('STEPS', steps), encoding='utf-8')
    r = subprocess.run(['node', str(f), json.dumps(ASK)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs the card', r.stderr[-800:])
    return json.loads(r.stdout or '[]')


def test_count(tmp: Path) -> None:
    out = run(tmp, "live(ASK); say(dock); pick(0); say(dock);")
    if out is None:
        return
    card, held = out[0][0], out[1][0]
    check('>Full (recommended) · queues 2 tasks<' in card, 'the option with stored tasks says how many it queues', card)
    check('>Small<' in card, 'an option without stays as it is', card)
    check('Queueing 2 tasks for “Full”' in held and 'data-qundo' in held, 'the hold says it queues, with Undo', held)


def test_tap(tmp: Path) -> None:
    out = run(tmp, """
      live(ASK); pick(0); await pass(4900); say(posts.length); await pass(200);
      say(posts, sent.length, toasts, kind());""")
    if out is None:
        return
    eq(out[0], [0], 'nothing is queued in the hold')
    posts, nsent, toasts, kind = out[1]
    eq(posts, [['queue', {'chat': 'c1', 'question': 'Which look?', 'option': 'Full'}]], 'after the hold, one POST /queue')
    eq(nsent, 0, 'no answer is sent to Claude')
    eq(toasts, ['“Full”: queued 2 tasks: a; b'], 'the one line of what was queued')
    eq(kind, '', 'the card is gone')


def test_undo_and_plain(tmp: Path) -> None:
    out = run(tmp, """
      live(ASK); pick(0); await pass(1000); undo(); await pass(6000); say(posts.length, sent.length, kind());
      await pass(1000); pick(1); await pass(5100); say(posts.length, sent.length);""")
    if out is None:
        return
    eq(out[0], [0, 0, 'card'], 'Undo in the hold queues nothing and sends nothing')
    eq(out[1], [0, 1], 'an option without stored tasks sends its answer as before')


def test_failed(tmp: Path) -> None:
    out = run(tmp, """
      answer = {ok: false, out: 'Nothing to queue (queued already?)'};
      live(ASK); pick(0); await pass(5100); say(kind(), toasts);""")
    if out is None:
        return
    eq(out[0][0], 'card', 'a queue that failed brings the card back')
    check('Nothing to queue' in out[0][1][0], 'and says why', out[0][1])


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(f) for f in (test_count, test_tap, test_undo_and_plain, test_failed)]))
