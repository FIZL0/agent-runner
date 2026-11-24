#!/usr/bin/env python3
"""Join a CHANGELOG.md conflict (`[run.join]`): `changelog_join.py OURS BASE THEIRS OUT`.

A plain line union puts an entry written before a release under the released version, because the lines
around it moved. So: keep OURS whole, take the lines THEIRS added (not in BASE, not in OURS) and put them at
the top of OURS's `## Unreleased` section; drop a line THEIRS removed from BASE. Exit 1 (a fix session) when
OURS has no Unreleased section.
"""
import sys
from pathlib import Path


def join(ours: str, base: str, theirs: str) -> str | None:
    o, b, t = (x.splitlines() for x in (ours, base, theirs))
    added = [l for l in t if l.strip() and l not in set(b) and l not in set(o)]
    removed = {l for l in b if l.strip() and l not in set(t)}
    out = [l for l in o if l not in removed]
    try:
        i = out.index('## Unreleased')
    except ValueError:
        return None if added else '\n'.join(out) + '\n'
    j = i + 1
    while j < len(out) and not out[j].strip():
        j += 1
    out[j:j] = added
    return '\n'.join(out) + '\n'


def main(argv: list[str]) -> int:
    ours, base, theirs, out = (Path(a) for a in argv[1:5])
    text = join(*(p.read_text(encoding='utf-8') for p in (ours, base, theirs)))
    if text is None:
        print('no "## Unreleased" section to put the new entries in')
        return 1
    out.write_text(text, encoding='utf-8')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
