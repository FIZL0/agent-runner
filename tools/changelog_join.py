#!/usr/bin/env python3
"""Join a CHANGELOG.md conflict (`[run.join]`): `changelog_join.py OURS BASE THEIRS OUT`.

A plain line union puts an entry written before a release under the released version, because the lines
around it moved. So: the side with more `## ` headings (the one that released) is the skeleton. The other
side's entries (lines starting `- `) that are not in BASE nor in the skeleton go at the top of the skeleton's
`## Unreleased` section; an entry the other side removed from BASE leaves the skeleton. Headings and prose
are never carried over. Exit 1 (a fix session) when the skeleton has no Unreleased section.
"""
import sys
from pathlib import Path


def join(ours: str, base: str, theirs: str) -> str | None:
    o, b, t = (x.splitlines() for x in (ours, base, theirs))
    heads = lambda ls: sum(l.startswith('## ') for l in ls)
    skel, other = (o, t) if heads(o) >= heads(t) else (t, o)
    entry = lambda l: l.startswith('- ')
    added = [l for l in other if entry(l) and l not in set(b) and l not in set(skel)]
    removed = {l for l in b if entry(l) and l not in set(other)}
    out = [l for l in skel if l not in removed]
    if not added:
        return '\n'.join(out) + '\n'
    try:
        i = out.index('## Unreleased')
    except ValueError:
        return None
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
