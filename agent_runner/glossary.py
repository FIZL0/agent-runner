"""`agent-runner glossary`: the project's GLOSSARY.md, kept by command (F22, after mattpocock/skills
domain-modeling, MIT).

Each entry names one thing three ways: the person's word (`_Said_`), the app's on-screen wording (`_On screen_`)
and the code names (`_In code_`), with a plain definition and the words to avoid; no implementation detail.

    glossary show [TERM]        the whole glossary, or one entry (found by any of its names)
    glossary add TERM --means "…" [--said …] [--ui …] [--code …] [--avoid …]
                                write or replace one entry; a repo with none gets a GLOSSARY.md
    glossary forget TERM        remove one entry
    glossary seed FILE|-        a starter glossary from a JSON list of entries ({term, means, said, ui, code,
                                avoid}); terms already there are kept as they are
    glossary scan [WORD]        the app's UI strings and main code names (modules, public functions, routes), or
                                where WORD shows in them: what a seed or a new term is drawn from

An edit commits itself in the main checkout (`plan: glossary …`), as plan commands do, so a control session never
leaves an edit there; in a worktree it waits for the task's own commit. `[plan] glossary` names the file
(default GLOSSARY.md); false turns it off: no file is written and the briefs say nothing of it.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

PROG = 'agent-runner glossary'

# The names an entry carries, in the order they are written, as (key, label).
FIELDS = (('said', 'Said'), ('ui', 'On screen'), ('code', 'In code'), ('avoid', 'Avoid'))

HEAD = """\
# {name} glossary

The words for each thing in {name}: what the person says, what the app shows and what the code calls it, with
a plain definition and the words to avoid. Kept by `{cmd} glossary` (add, show, forget); no implementation
detail. (Format after mattpocock/skills domain-modeling, MIT.)

## Language
"""

ENTRY = re.compile(r'^\*\*(.+?)\*\*:\n(.*?)(?=\n\s*\n|\n#|\Z)', re.M | re.S)


def setting(c=None):
    """`[plan] glossary`: a path (relative to the repo) or False (off)."""
    if c is None:
        from agent_runner.config import cfg
        c = cfg()
    v = c.raw['plan'].get('glossary', 'GLOSSARY.md')
    return v if isinstance(v, str) and v.strip() else False


def path(c=None, root=None) -> Path | None:
    """The glossary file, or None when `[plan] glossary = false`."""
    if c is None:
        from agent_runner.config import cfg
        c = cfg()
    v = setting(c)
    return None if v is False else Path(root or c.root) / Path(v).expanduser()


# --- the file ------------------------------------------------------------------------------------------------

def parse(text: str) -> dict[str, dict]:
    """{term: {'means', 'said', 'ui', 'code', 'avoid'}} for every `**Term**:` entry, in file order."""
    labels = {lab: key for key, lab in FIELDS}
    out = {}
    for term, body in ENTRY.findall(text):
        e = {'means': '', **{k: '' for k, _ in FIELDS}}
        means = []
        for line in body.splitlines():
            m = re.match(r'_(.+?)_:\s*(.*)$', line)
            if m and m.group(1) in labels:
                e[labels[m.group(1)]] = m.group(2).strip()
            else:
                means.append(line.strip())
        e['means'] = ' '.join(s for s in means if s)
        out[term] = e
    return out


def render(term: str, e: dict) -> str:
    """One entry as GLOSSARY.md holds it."""
    lines = [f'**{term}**:', _one_line(e.get('means', ''))]
    lines += [f'_{lab}_: {_one_line(e[k])}' for k, lab in FIELDS if e.get(k)]
    return '\n'.join(lines)


def _one_line(s: str) -> str:
    return ' '.join(str(s).split())


def _names(term: str, e: dict) -> list[str]:
    """Every name an entry answers to: its term, the person's word and the on-screen wording."""
    out = [term]
    for k in ('said', 'ui'):
        out += [w.strip(" '\"`") for w in re.split(r'[,;/]', e.get(k, '')) if w.strip()]
    return [_bare(n) for n in out]


def _bare(word: str) -> str:
    """A name to compare: lower case, without a leading 'the', 'a' or 'an' ('the list' is 'list')."""
    return re.sub(r'^(the|an?)\s+', '', word.strip().lower())


def find(text: str, word: str) -> str | None:
    """The term of the entry `word` names: its term first, else a unique match on its person's or screen word."""
    entries = parse(text)
    w = word.strip().lower()
    if exact := next((t for t in entries if t.lower() == w), None):
        return exact
    hits = [t for t, e in entries.items() if _bare(w) in _names(t, e)]
    return hits[0] if len(hits) == 1 else None


def _span(text: str, term: str) -> tuple[int, int] | None:
    for m in ENTRY.finditer(text):
        if m.group(1) == term:
            return m.start(), m.end()
    return None


def put(text: str, term: str, e: dict) -> tuple[str, bool]:
    """`text` with the entry for `term` written (replaced in place, or added at the end); True when it is new."""
    if span := _span(text, term):
        return text[:span[0]] + render(term, e) + text[span[1]:], False
    return text.rstrip('\n') + '\n\n' + render(term, e) + '\n', True


def remove(text: str, term: str) -> str:
    span = _span(text, term)
    if not span:
        return text
    before, after = text[:span[0]].rstrip('\n'), text[span[1]:].lstrip('\n')
    return before + ('\n\n' + after if after else '\n')


def new_text(c) -> str:
    return HEAD.format(name=Path(c.root).name, cmd='agent-runner')  # committed: no machine's own path in it


# --- commands ------------------------------------------------------------------------------------------------

def _commit(c, p: Path, msg: str) -> None:
    """Commit the edit in the main checkout at once, as a plan edit does (and push it on the shared branch)."""
    from agent_runner import plan
    root = Path(c.root)
    try:
        rel = p.resolve().relative_to(root.resolve())
    except ValueError:  # a glossary outside the repo: nothing of this repo to commit
        return
    if subprocess.run(['git', 'check-ignore', '-q', str(rel)], cwd=root).returncode == 0:
        return
    plan._commit(root, [p], f'glossary {msg}'[:70])


def _write(p: Path, text: str) -> None:
    from agent_runner.plan import write_atomic
    p.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(p, text)


def add(c, term: str, e: dict) -> str:
    """Write one entry, making the file on the first add; commit it. Returns what to say."""
    p = path(c)
    if p is None:
        return 'the glossary is off ([plan] glossary = false): nothing written'
    term = _one_line(term)
    if not term or not _one_line(e.get('means', '')):
        raise SystemExit(f'{PROG} add: a term and --means (a plain definition) are needed')
    fresh = not p.exists()
    text = p.read_text(encoding='utf-8') if not fresh else new_text(c)
    if (had := find(text, term)) and had.lower() == term.lower():
        term = had  # keep the spelling the file has
    text, new = put(text, term, e)
    _write(p, text)
    _commit(c, p, f'add {term}')
    label = ' = '.join(dict.fromkeys(x for x in (e.get('said'), e.get('ui'), term) if x))
    where = f'{p.name} (new)' if fresh else p.name
    return f'{"added" if new else "updated"} {label} in {where}'


def forget(c, word: str) -> str:
    p = path(c)
    if p is None:
        return 'the glossary is off ([plan] glossary = false): nothing to forget'
    text = p.read_text(encoding='utf-8') if p.exists() else ''
    term = find(text, word)
    if not term:
        raise SystemExit(f'{PROG}: no entry for {word!r} in {p.name}')
    _write(p, remove(text, term))
    _commit(c, p, f'forget {term}')
    return f'forgot {term} ({p.name})'


def seed(c, entries: list[dict]) -> str:
    """A starter glossary in one write and one commit; a term already there is left as it is."""
    p = path(c)
    if p is None:
        return 'the glossary is off ([plan] glossary = false): nothing written'
    fresh = not p.exists()
    text = p.read_text(encoding='utf-8') if not fresh else new_text(c)
    added = []
    for e in entries:
        term = _one_line(e.get('term', ''))
        if not term or not _one_line(e.get('means', '')) or find(text, term):
            continue
        text, _ = put(text, term, e)
        added.append(term)
    if not added:
        return f'nothing new for {p.name}'
    _write(p, text)
    _commit(c, p, f'seed {len(added)} terms')
    return f'{"wrote" if fresh else "added to"} {p.name}: {", ".join(added)}'


def show(c, word: str = '') -> tuple[int, str]:
    p = path(c)
    if p is None:
        return 0, 'the glossary is off ([plan] glossary = false)'
    if not p.exists():
        return 1, f'no {p.name} yet: `{PROG} add TERM --means "…"` starts one'
    text = p.read_text(encoding='utf-8')
    if not word:
        return 0, text.rstrip('\n')
    term = find(text, word)
    if not term:
        return 1, f'no entry for {word!r} in {p.name}'
    return 0, render(term, parse(text)[term])


# --- joining a merge conflict (T31) --------------------------------------------------------------------------

class CannotJoin(ValueError):
    """The sides of a glossary conflict need somebody to read them: a fix session."""


def _outline(text: str) -> tuple[dict, dict]:
    """A glossary as (sections, entries): {heading path: the prose under that heading} and {term, lower case:
    (heading path, the entry's text)}, both in file order. CannotJoin when some of the text is neither."""
    sections: dict[tuple, list[str]] = {(): []}
    entries: dict[str, tuple[tuple, list[str]]] = {}
    path: tuple = ()
    body = None  # the open entry's lines
    closed = False  # an entry of this section ended: only another entry or a heading may follow
    if '\ufffd' in text:
        raise CannotJoin('it is not all UTF-8')
    for n, raw in enumerate(text.split('\n'), 1):
        line = raw.rstrip()
        if re.match(r'(<{7}|={7}|>{7}|\|{7})', line) or line.lstrip().startswith(('```', '~~~')):
            raise CannotJoin(f'line {n} is a conflict mark or a code fence')
        if not line:
            closed, body = closed or body is not None, None
            if not closed:
                sections[path].append('')
        elif line.startswith('#'):
            m = re.match(r'(#{1,6})\s+\S', line)
            if not m or body is not None:  # right under an entry's line it may be part of that entry
                raise CannotJoin(f'line {n} is no heading of its own')
            path = (*(h for h in path if len(h) - len(h.lstrip('#')) < len(m.group(1))), line)
            if path in sections:
                raise CannotJoin(f'the section {line!r} is there twice')
            sections[path], body, closed = [], None, False
        elif line.startswith('**'):
            m = re.fullmatch(r'\*\*(.+?)\*\*:', line)
            if not m or body is not None:
                raise CannotJoin(f'line {n} does not start an entry of its own')
            key = _one_line(m.group(1)).lower()
            if key in entries:
                raise CannotJoin(f'the term {m.group(1)!r} is there twice')
            body = [line]
            entries[key] = (path, body)
        elif body is not None:
            body.append(line)
        elif closed:
            raise CannotJoin(f'line {n} is text after an entry')
        else:
            sections[path].append(raw)
    if bare := next((b[0] for _, b in entries.values() if len(b) < 2), None):
        raise CannotJoin(f'{bare} has no definition')
    if {_one_line(t).lower() for t in parse(text)} != set(entries):
        raise CannotJoin('its entries do not parse')
    return ({k: '\n'.join(v).strip('\n') for k, v in sections.items()},
            {k: (s, '\n'.join(b)) for k, (s, b) in entries.items()})


def _pick(base: dict, ours: dict, theirs: dict, what: str) -> dict:
    """{key: value} of a three-way merge by key: a key changed, added or removed on one side takes that side."""
    out = {}
    for k in dict.fromkeys([*ours, *theirs, *base]):
        b, o, t = base.get(k), ours.get(k), theirs.get(k)
        if o != t and b not in (o, t):
            raise CannotJoin(f'both sides changed the {what} {k[-1:] if isinstance(k, tuple) else k!r} differently')
        if (v := t if o == b else o) is not None:
            out[k] = v
    return out


def _order(base: list, ours: list, theirs: list, keep) -> list:
    """The keys of `keep` in order: a side that moved keys gives the order, and each key only the other side has
    comes after the one it follows there (and after what the first side added at that place)."""
    b, o, t = ([k for k in side if k in keep] for side in (base, ours, theirs))
    every = set(b) & set(o) & set(t)
    bo, oo, to = ([k for k in side if k in every] for side in (b, o, t))
    if to not in (bo, oo):
        if oo != bo:
            raise CannotJoin('both sides moved the same entries or sections')
        o, t = t, o
    out = list(o)
    for i, k in enumerate(t):
        if k in out:
            continue
        at = out.index(t[i - 1]) + 1 if i else 0
        while at < len(out) and out[at] not in t:
            at += 1
        out.insert(at, k)
    return out


def join3(base: str, ours: str, theirs: str) -> str:
    """The glossary with both sides' changes since `base`, joined by entry and not by line; CannotJoin when an
    entry (or a section's prose) was changed differently on both sides, or a side does not parse."""
    sides = [_outline(t) for t in (base, ours, theirs)]
    sections = _pick(*(s for s, _ in sides), 'section')
    entries = _pick(*(e for _, e in sides), 'term')
    if lost := next((k for k, (s, _) in entries.items() if s not in sections), None):
        raise CannotJoin(f'one side removed the section the other has the term {lost!r} in')
    order = _order(*(list(s) for s, _ in sides), sections)
    blocks = []
    for s in order:
        blocks += [*s[-1:], *([sections[s]] if sections[s] else [])]
        mine = {k for k, (at, _) in entries.items() if at == s}
        blocks += [entries[k][1] for k in _order(*([k for k in e if e[k][0] == s] for _, e in sides), mine)]
    text = '\n\n'.join(blocks) + '\n'
    if _outline(text) != (sections, entries):  # dicts: the order aside, nothing lost, doubled or moved
        raise CannotJoin('the joined text does not hold what both sides have')
    return text


# --- scan: what a seed or a new term is drawn from -----------------------------------------------------------

CODE_EXT = {'.py', '.rs', '.go', '.ts', '.tsx', '.js', '.jsx', '.mjs', '.rb', '.java', '.kt', '.swift', '.cs',
            '.c', '.cc', '.cpp', '.h', '.php', '.ex', '.dart', '.lua', '.vue', '.svelte'}
UI_EXT = {'.html', '.htm', '.jsx', '.tsx', '.vue', '.svelte', '.erb', '.hbs', '.jinja', '.j2', '.xml', '.xaml',
          '.strings', '.po', '.arb'}
SKIP = re.compile(r'(^|/)(tests?|spec|__tests__|vendor|node_modules|third_party|dist|build|examples?|docs?)/'
                  r'|(^|/)(test_|_test\.|.*\.test\.|.*\.spec\.|.*\.min\.)')
FUNC = re.compile(r'^\s*(?:pub(?:\([^)]*\))?\s+)?(?:export\s+)?(?:async\s+)?(?:def|fn|func|function)\s+'
                  r'(?:\([^)]*\)\s*)?([A-Za-z][A-Za-z0-9_]*)', re.M)
ROUTE = re.compile(r'''(?:\.(?:get|post|put|patch|delete|route|api_route)|\bpath|\bre_path|Route)\s*\(\s*'''
                   r'''['"](/[^'"]*|[a-z][\w\-/<>:{}]*)['"]''')
UI_TEXT = re.compile(r'>\s*([A-Z][^<>{}\n]{1,40}?)\s*<|\b(?:title|label|placeholder|aria-label|alt)\s*=\s*'
                     r'["\']([^"\'{}\n]{2,40})["\']')


def _files(root: Path) -> list[str]:
    r = subprocess.run(['git', 'ls-files'], cwd=root, capture_output=True, text=True)
    return [f for f in r.stdout.splitlines() if not SKIP.search(f)]


def _read(root: Path, f: str) -> str:
    try:
        p = root / f
        return p.read_text(encoding='utf-8', errors='replace') if p.stat().st_size < 400_000 else ''
    except OSError:
        return ''


def scan(root: Path, limit: int = 40) -> dict[str, list[str]]:
    """{'UI strings', 'Modules', 'Public functions', 'Routes': names, most common first}."""
    from collections import Counter
    found = {k: Counter() for k in ('UI strings', 'Modules', 'Public functions', 'Routes')}
    for f in _files(root):
        ext = Path(f).suffix.lower()
        if ext not in CODE_EXT | UI_EXT:
            continue
        text = _read(root, f)
        if ext in CODE_EXT and Path(f).stem not in ('__init__', '__main__', 'index', 'main', 'mod', 'lib'):
            found['Modules'][f] += 1
        if ext in CODE_EXT:
            found['Public functions'].update(n for n in FUNC.findall(text) if not n.startswith('_'))
            found['Routes'].update(ROUTE.findall(text))
        if ext in UI_EXT or ext in CODE_EXT:
            for a, b in UI_TEXT.findall(text):
                if (s := (a or b).strip()) and re.search(r'[A-Za-z]{3}', s) and not re.search(r'[=;()\[\]]', s):
                    found['UI strings'][s] += 1
    return {k: [n for n, _ in v.most_common(limit)] for k, v in found.items()}


def grep(root: Path, word: str, limit: int = 30) -> list[str]:
    """`file:line: text` where `word` shows in the app's UI and code files."""
    pat = re.compile(re.escape(word), re.I)
    out = []
    for f in _files(root):
        if Path(f).suffix.lower() not in CODE_EXT | UI_EXT:
            continue
        for i, line in enumerate(_read(root, f).splitlines(), 1):
            if pat.search(line):
                out.append(f'{f}:{i}: {line.strip()[:120]}')
                if len(out) >= limit:
                    return out
    return out


# --- what the briefs say -------------------------------------------------------------------------------------

CONTROL = """\
**The glossary ({file}).** Keep it with `{cmd} glossary` (`show [TERM]`, `add`, `forget`, `scan [WORD]`); it commits
itself, so it is the one file you change here. Never ask the person about it: write, then mention it in passing.
- When the person uses a word for a thing that is not in it, run `{cmd} glossary scan <word>` (and `show`) to
  find the screen's wording and the code names, then add it at once: `{cmd} glossary add "<Term>" --said "<their
  word>" --ui "<on-screen wording>" --code "<module, function>" --means "<plain definition>" --avoid "<other
  words>"`, and say only, in passing, `added list = Board screen to the glossary`. A definition says what it is
  to the person, never how it is built (no config keys, paths or internals beyond the code names).
- "forget X", "that's wrong": `{cmd} glossary forget X` (or `add` again to correct it).
- When the person, the screen and the code use three different words for one thing, offer once to queue a
  rename to the glossary's term (`{cmd} plan add C "rename … to …" --files …`); queue it only on yes.
- When the person asks "what?" or seems lost, say it again in the glossary's terms, shorter.
- Offer an ADR in docs/adr/ only for a choice that is hard to reverse, surprising and a real trade-off;
  never for the rest.
"""

SEED = """\
**Start the glossary now.** {file} does not exist yet: once you have answered the person's first message, run
`{cmd} glossary scan` (UI strings, modules, public functions, routes) and pick the 10-20 terms the person and the
app use most. Write them, with the Write tool, as a JSON list to a file in your scratchpad (never in this
checkout): `[{{"term": "Board", "said": "the list", "ui": "Board", "code": "render_board(), board.py", "means":
"The screen that lists every task.", "avoid": "list, page"}}]`, then run `{cmd} glossary seed <that file>`,
which writes and commits it. Do not ask first; say in one line, in passing, that you started the glossary with
N terms and that "forget X" drops one.
"""

SLOT = """\
Glossary ({file}): name new things (functions, files, screens, messages) with its terms, and when you add a \
thing it has no term for, add one: `{cmd} glossary add "<Term>" --said "<the person's word>" --ui "<on-screen \
wording>" --code "<code names>" --means "<plain definition, no implementation detail>" --avoid "<other words>"` \
(it lands with your commit)."""


def fit(text: str, who: str, cmd: str, c=None) -> str:
    """A brief (`who`: 'control' or 'slot') fitted to `[plan] glossary`: off, the generic glossary line is taken
    out and nothing added; on, that line names the configured file and the glossary's own paragraph follows, the
    control brief's with the seed ask when the file does not exist yet."""
    from agent_runner.guide import GLOSSARY
    try:
        p = path(c)
    except (Exception, SystemExit):  # no config to read: leave the brief as it is
        return text
    if p is None:
        return text.replace(' ' + GLOSSARY, '').replace(GLOSSARY, '')
    name = setting(c)
    if name != 'GLOSSARY.md':
        text = text.replace(GLOSSARY, GLOSSARY.replace('a GLOSSARY.md', name).replace('GLOSSARY.md', name))
    if who == 'slot':
        return f'{text.rstrip()}\n\n' + SLOT.format(file=name, cmd=cmd)
    extra = CONTROL.format(file=name, cmd=cmd)
    if not p.exists():
        extra += '\n' + SEED.format(file=name, cmd=cmd)
    return f'{text.rstrip()}\n\n{extra}'


# B98: the control brief carries a pointer; the paragraph above is `guide glossary`'s page
POINTER = ("**The glossary ({file}).** Keep it with `{cmd} glossary`, unasked: when the person uses a word for a "
           "thing that is not in it, or says \"forget X\", read `guide glossary` first.")
SEED_POINTER = ("{file} does not exist yet: once you have answered the first message, read `guide "
                "glossary` and start it.")


def brief_fit(text: str, cmd: str, c=None) -> str:
    """B98: the control brief fitted as `fit(text, 'control', …)` does, with the glossary's paragraph (and seed
    ask) behind `guide glossary`: a two-line pointer in its place, so the brief stays short."""
    try:
        p = path(c)
    except (Exception, SystemExit):  # no config to read: leave the brief as it is, as fit does
        return text
    if p is None:
        return fit(text, 'control', cmd, c)  # the glossary line taken out, nothing added
    full = fit(text, 'slot', cmd, c)  # the glossary line fitted to the file's name, SLOT appended
    name = setting(c)
    slot = SLOT.format(file=name, cmd=cmd)
    base = (full[:full.rindex(slot)] if slot in full else full).rstrip()  # never break the SessionStart hook
    extra = POINTER.format(file=name, cmd=cmd)
    if not p.exists():
        extra += ' ' + SEED_POINTER.format(file=name, cmd=cmd)
    return f'{base}\n\n{extra}\n'


def topic(cmd: str, c=None) -> str:
    """B98: `guide glossary`: the control brief's glossary paragraph, with the seed ask when there is no file."""
    try:
        p = path(c)
    except (Exception, SystemExit):
        p = None
    if p is None:
        return '# The glossary\n\nThis project keeps no glossary (`[plan] glossary = false`).\n'
    name = setting(c)
    out = '# The glossary\n\n' + CONTROL.format(file=name, cmd=cmd)
    if not p.exists():
        out += '\n' + SEED.format(file=name, cmd=cmd)
    return out


# --- the command ---------------------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(prog=PROG, description=__doc__.split('\n\n')[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd')
    s = sub.add_parser('show', help='the whole glossary, or one entry')
    s.add_argument('term', nargs='*')
    a = sub.add_parser('add', help='write or replace one entry')
    a.add_argument('term', nargs='+')
    a.add_argument('--means', required=True, help='a plain definition, no implementation detail')
    a.add_argument('--said', default='', help="the person's word for it")
    a.add_argument('--ui', default='', help="the app's on-screen wording")
    a.add_argument('--code', default='', help='the code names: modules, functions, routes')
    a.add_argument('--avoid', default='', help='the words not to use for it')
    f = sub.add_parser('forget', help='remove one entry')
    f.add_argument('term', nargs='+')
    d = sub.add_parser('seed', help='a starter glossary from a JSON list of entries')
    d.add_argument('file', help='a JSON file, or - for stdin')
    n = sub.add_parser('scan', help="the app's UI strings and code names, or where WORD shows in them")
    n.add_argument('word', nargs='*')
    if argv[:1] and argv[0] in ('-h', '--help', 'help'):
        print(__doc__)
        return 0
    if not argv or argv[0] not in sub.choices:  # bare, or a term: show it
        argv = ['show', *argv]
    args = ap.parse_args(argv)
    from agent_runner.config import cfg
    c = cfg()
    if args.cmd == 'show':
        rc, out = show(c, ' '.join(args.term))
        print(out, file=sys.stdout if not rc else sys.stderr)
        return rc
    if args.cmd == 'scan':
        root = Path(c.root)
        if args.word:
            hits = grep(root, ' '.join(args.word))
            print('\n'.join(hits) if hits else f'no UI string or code name holds {" ".join(args.word)!r}')
            return 0
        for k, names in scan(root).items():
            print(f'## {k}\n' + ('\n'.join(f'  {x}' for x in names) if names else '  (none found)'))
        return 0
    from agent_runner import plansync
    with plansync.locked(c):  # two sessions adding at once would drop one write
        if args.cmd == 'add':
            e = {k: getattr(args, k) for k in ('means', 'said', 'ui', 'code', 'avoid')}
            print(add(c, ' '.join(args.term), e))
        elif args.cmd == 'forget':
            print(forget(c, ' '.join(args.term)))
        else:
            raw = sys.stdin.read() if args.file == '-' else Path(args.file).read_text(encoding='utf-8')
            try:
                entries = json.loads(raw)
            except json.JSONDecodeError as e:
                raise SystemExit(f'{PROG} seed: not JSON: {e}')
            if isinstance(entries, dict):
                entries = entries.get('terms') or [entries]
            if not isinstance(entries, list) or not all(isinstance(x, dict) for x in entries):
                raise SystemExit(f'{PROG} seed: a JSON list of {{"term", "means", …}} objects is needed')
            print(seed(c, entries))
    return 0
