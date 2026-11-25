"""B773: `plan add` and `plan edit` refuse a text that holds a glob the shell expanded.

    python3 tests/test_plan_glob.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from _check import RUN, check, eq, has, report


def test_expanded_glob() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        def git(*a: str) -> str:
            return subprocess.run(['git', *a], cwd=root, check=True, capture_output=True, text=True).stdout.strip()

        git('init', '-q')
        git('commit', '-q', '--allow-empty', '-m', 'start')
        (root / 'journal').mkdir()
        for i in range(20):
            (root / 'journal' / f'note{i:02}').mkdir()
        paths = [f'journal/note{i:02}' for i in range(20)]
        env = {**os.environ, 'AGENT_RUNNER_REPO': str(root)}

        def plan(*a: str) -> subprocess.CompletedProcess:
            return subprocess.run([sys.executable, str(RUN), 'plan', *a], cwd=root, env=env, capture_output=True, text=True, timeout=120)

        r = plan('add', 'R', 'the parser', '--files', 'p.py')
        eq(r.returncode, 0, 'a first add')
        todo = root / 'plan' / 'TODO.md'
        before, head = todo.read_text(encoding='utf-8'), git('rev-parse', 'HEAD')
        many, files = ' '.join(paths), ('--files', paths[0])
        gaps = ' '.join(f'{p} my note.md' if i % 5 == 4 else p for i, p in enumerate(paths))
        for args, what in (((f'check the page {many}', *files), 'paths folded into the text'),
                           ((f'check the page {many} and then more', *files, '--force'), 'in its middle, with --force'),
                           ((f'check the page {gaps}', *files), 'names with a space between them'),
                           ((many,), 'a text of paths only'),
                           ((f'check the page | files: {many}',), "a field's value in the text"),
                           (('check the page\n' + '\n'.join(paths), *files), 'one path to a line'),
                           (('check the page', *files, '@', 'bottom', *paths), 'paths after the @ place'),
                           (('check the page', '--files', *paths), 'an unquoted --files glob'),
                           (('check the page', *paths), 'paths as words of their own'),
                           (('check', 'it', *paths), 'and after bare words')):
            for cmd, said in ((('add', 'R'), 'not added'), (('edit', 'R1'), 'not edited')):
                if cmd[0] == 'edit' and {'@', '--force'} & set(args):
                    continue  # edit takes neither
                r = plan(*cmd, *args)
                eq(r.returncode, 2, f'{cmd[0]}: {what} is refused')
                has(r.stderr, rf'{said}: ', f'{cmd[0]}: {what}: says so')
                has(r.stderr, r'(?i)quote', f'{cmd[0]}: {what}: says to quote')
        has(plan('add', 'R', f'x {many}', *files).stderr, r'20 existing paths .*Quote the glob', 'and why')
        eq(todo.read_text(encoding='utf-8'), before, 'TODO.md is unchanged')
        eq(git('rev-parse', 'HEAD'), head, 'and nothing was committed')

        few = f'compare {" ".join(paths[:3])} with {paths[4]} and {paths[5]}, in journal; also ' + ', '.join(paths[6:])
        for cmd in (('add', 'R'), ('edit', 'R1')):
            r = plan(*cmd, few, '--files', 'journal/**')
            check(r.returncode == 0, f'{cmd[0]}: ordinary text naming paths still files', r.stderr)
        eq(todo.read_text(encoding='utf-8').count(few), 2, 'word for word')
        r = plan('add', 'R', 'gone: ' + ' '.join(f'old/{i}' for i in range(20)), '--files', 'q.py')
        check(r.returncode == 0, 'paths that do not exist are only words', r.stderr)
        r = plan('add', 'R', 'sweep them', '--files', many)
        check(r.returncode == 0, 'a quoted --files list of paths is no text', r.stderr)


if __name__ == '__main__':
    raise SystemExit(report([test_expanded_glob]))
