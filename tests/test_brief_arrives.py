"""B775: a 30 KB brief reaches the session as its system prompt, and a session whose brief did not arrive is ended."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

from _check import check, eq, has, report
from agent_runner import brief_arrives as B, slots, state as S

LONG = 'Do the one task.\n' + 'a long line of the plan ' * 1280 + '\nThe last words of the brief.'
SHORT = 'Do the one task named here.\n' + 'a short brief ' * 40


def user(text: str) -> dict:
    return {'type': 'user', 'message': {'role': 'user', 'content': text}}


def snapshot(text: str) -> dict:
    return {'type': 'attachment', 'attachment': {'type': 'prompt_snapshot', 'systemPrompt': ['You are an agent.', text]}}


def shape(text: str) -> dict:
    return {'type': 'api-request-shape', 'shape': {'system': [{'type': 'text', 'text': text}]}}


ANSWER = {'type': 'assistant', 'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': 'No brief.'}]}}


def test_flags(tmp: Path) -> None:
    check(len(LONG) > 30000, 'a 30 KB brief')
    argv = slots.agent_argv(LONG, 'sid-long', 'opus', 90, 'slot1')
    brief = S.C.notes('sid-long.brief')
    has(argv[1], 'in your system prompt', 'a hidden slot: its first message points at the system prompt')
    check('--append-system-prompt-file' in argv, 'and the first start carries the flag')
    eq(argv[argv.index('--append-system-prompt-file') + 1], str(brief), 'naming the brief')
    has(brief.read_text(encoding='utf-8'), LONG, 'whole')
    again = slots.agent_argv(LONG, 'sid-long', 'opus', 90, 'slot1', resume=True)
    eq(again.count('--append-system-prompt-file'), 1, 'once on a resume')
    check('--append-system-prompt-file' not in slots.agent_argv(SHORT, 'sid-s', 'opus', 90, 'slot1'), 'not for a short one')
    cmd = slots.agent_cmd(LONG * 5, 'sid-cmd', 'opus', 90, 'slot1')
    has(cmd, '--append-system-prompt-file', 'the same for a shell command past its limit')


def test_missing(tmp: Path) -> None:
    t = tmp / 't.jsonl'

    def said(prompt: str, *rows, end: str = '') -> str | None:
        t.write_text(''.join(json.dumps(r) + '\n' for r in rows) + end, encoding='utf-8')
        return B.missing(str(t), prompt)

    point = user(slots.LONG_BRIEF.format(marker=B.MARKER))
    whole = f'# {B.MARKER}\n\n{LONG}'
    eq(said(LONG, point, snapshot(whole)), '', 'arrived in the system prompt')
    eq(said(LONG, point, shape(whole), ANSWER), '', 'or seen in the request')
    has(said(LONG, point, snapshot('nothing'), ANSWER), 'no brief', 'R45: a pointer at nothing')
    has(said(LONG, point, snapshot(whole[:-100])), 'whole brief', 'a cut one')
    eq(said(LONG, point), None, 'not said yet')
    eq(said(LONG, point, end='{"type": "att'), None, 'nor in a line being written')
    eq(said(LONG, point, ANSWER), '', 'a transcript with no system prompt cannot tell')
    eq(said(SHORT, user(SHORT), ANSWER), '', 'a short brief is the first message')
    eq(said(SHORT, user([{'type': 'text', 'text': SHORT}])), '', 'in either form')
    has(said(SHORT, user(SHORT[:60])), 'characters', 'a cut first message')
    eq(B.missing(str(tmp / 'none'), SHORT), None, 'no transcript yet')


def test_check(tmp: Path) -> None:
    t = tmp / 'sid-c.jsonl'
    lines: list[str] = []

    def run(sid: str, *rows, resume: bool = False, alive: bool = True) -> bool:
        """Was the session ended?"""
        t.write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
        S.C.notes('slot1.prompt').write_text(LONG, encoding='utf-8')
        S.C.notes('slot1.job').write_text(json.dumps(
            {'argv': ['claude', 'p', '--resume' if resume else '--session-id', sid]}), encoding='utf-8')
        proc = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
        try:
            if not alive:
                proc.kill()
                proc.wait()
            with mock.patch.object(slots, 'transcript', lambda s: str(t)), \
                    mock.patch.object(S, 'log', lambda text, *a, **k: lines.append(text)):
                for _ in range(2):  # a second look says nothing more
                    B.check({1: (proc.pid, sid, 0)}, {1: ('R45', 'x', set())})
            if not alive:
                return False
            try:
                proc.wait(timeout=5 if lines else 0.2)
                return True
            except subprocess.TimeoutExpired:
                return False
        finally:
            proc.kill()
            proc.wait()

    point = user(slots.LONG_BRIEF.format(marker=B.MARKER))
    whole = snapshot(f'# {B.MARKER}\n\n{LONG}')
    check(not run('sid-1', point, whole) and not lines, 'a session with its brief goes on', str(lines))
    check(not run('sid-2', point, snapshot('x'), resume=True) and not lines, 'so does a resumed one', str(lines))
    check(run('sid-3', point, snapshot('x')), 'one without is ended')
    eq(len(lines), 1, 'and said once')
    has(lines[0], r"slot 1: R45's brief did not arrive .*its session is ended", 'in the run log')
    run('sid-4', point, snapshot('x'), ANSWER, alive=False)
    has(lines[-1], 'had ended already', 'one that ended first is said too')


def run() -> None:
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d).resolve()
        subprocess.run(['git', 'init', '-q', str(tmp)], check=True)
        (tmp / 'plan').mkdir()
        (tmp / 'plan' / 'TODO.md').write_text('# TODO\n', encoding='utf-8')
        S.init(tmp)
        for t in (test_flags, test_missing, test_check):
            t(tmp)


if __name__ == '__main__':
    raise SystemExit(report([run]))
