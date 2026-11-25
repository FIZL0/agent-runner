"""F418: what an audit's own diff may change: its findings file, its own task, and dead references in docs, the
glossary and lessons. The rest is asked on its pick sheet; once that is answered, the plan too (drops, edits, tasks).
`done` refuses a diff past it (`refusal`), and the merge puts one to a person (`beyond`).

Read off the diff alone, sentence by sentence: each sentence that goes names something that was in the repository and
is no longer, and what stands in its place has no new word but the name of something that is there. History
(CHANGELOG, DONE.md, the journal, findings) may name what is gone, so it is not fixed."""
from __future__ import annotations

import posixpath
import re
from difflib import SequenceMatcher
from pathlib import Path

from agent_runner import audit, plan as P, stale, state as S
from agent_runner.gitops import git, shared_name

DOCS = ('docs', 'glossary', 'lessons')
FILE_MODES = ('100644', '100755')
FENCE = re.compile(r'\s*(```|~~~)')
STARTS = re.compile(r'\s*(?:[-*+>|#=]|\d+[.)]\s|_\w|\*\*)')  # a line that begins a block of its own
SENTENCE = re.compile(r'(?<=[.!?])\s+(?=[A-Z`*_\[("])')
LINK = re.compile(r'\]\(\s*<?([^)\s>]+)')
CODE = re.compile(r'`([^`]+)`')
IN_CODE = re.compile(r'^_In code_:(.*)', re.I)
BARE_PATH = re.compile(r'(?<![\w/.:~$<-])[\w.-]+(?:/[\w.-]+)+')
SPLIT = re.compile(r'''[\s,;|=(){}\[\]"'<>]+''')


def sentences(text: str) -> list[str]:
    """`text` as sentences: a paragraph wrapped another way is the same; a line of a code block stands alone."""
    out: list[str] = []
    block: list[str] = []
    fenced = False

    def flush():
        if block:
            out.extend(SENTENCE.split(' '.join(' '.join(block).split())))
            block.clear()
    for l in text.splitlines():
        if FENCE.match(l):
            flush()
            fenced = not fenced
            out.append(l.rstrip())
        elif fenced:
            out.append(l.rstrip())
        elif not l.strip():
            flush()
        else:
            if STARTS.match(l):
                flush()
            block.append(l)
    flush()
    return out


def references(s: str) -> list[str]:
    """What the sentence `s` names: link targets, `code`, paths, a glossary term's names in code."""
    raw = LINK.findall(s) + BARE_PATH.findall(s)
    spans = CODE.findall(s)
    if m := IN_CODE.match(s):
        spans.append(m[1])
    for span in spans:
        raw += SPLIT.split(span)
    out = []
    for r in raw:
        r = re.sub(r'(?:#.*|:\d[\d,-]*|\(\))$', '', r.strip('`.,:;!? ')) if not r.startswith('#') else ''
        if len(r) >= 4 and re.search('[A-Za-z]', r) and not re.match(r'\w+:|[~/$]', r):
            out.append(r)
    return list(dict.fromkeys(out))


class Tree:
    """What is in the tree `rev` of `root`, and what was at `base` or before it."""

    def __init__(self, root: Path, base: str, rev: str, is_history, glossary: str):
        self.root, self.base, self.rev, self.is_history, self.glossary = root, base, rev, is_history, glossary
        out = git('ls-tree', '-r', '-z', '--name-only', '--full-tree', rev, cwd=root).stdout
        self.files = {f for f in out.split('\0') if f}
        self.there = self.files | {'/'.join(f.split('/')[:i]) for f in self.files for i in range(1, f.count('/') + 1)}
        self.seen: dict[tuple[str, str], bool] = {}

    def once(self, what: str, name: str, look) -> bool:
        if (what, name) not in self.seen:
            self.seen[what, name] = bool(look())
        return self.seen[what, name]

    def has_path(self, name: str, place: str) -> bool:
        n = posixpath.normpath(name)
        return n in self.there or posixpath.normpath(posixpath.join(posixpath.dirname(place), name)) in self.there or \
            any(f.endswith('/' + n) for f in self.there)

    def prose(self, f: str) -> bool:
        return stale.sort_of(f, self.glossary) in DOCS or self.is_history(f)

    def has_name(self, name: str) -> bool:
        def look():
            for n in dict.fromkeys((name, name.rsplit('.', 1)[-1])):
                out = git('grep', '-l', '-z', '-I', '-w', '-F', '-e', n, self.rev, '--', ':/', cwd=self.root).stdout
                if any(not self.prose(f.split(':', 1)[1]) for f in out.split('\0') if f):
                    return True
            return False
        return self.once('now', name, look)

    def had(self, name: str) -> bool:
        """Was `name` a path of the repository, or in its code, before it went."""
        def look():
            path = posixpath.normpath(name)
            while path.startswith('../'):
                path = path[3:]
            word = '(^|[^[:alnum:]_])' + re.sub(r'([.^$*+?()\[\]{}|\\])', r'\\\1', name) + '([^[:alnum:]_]|$)'
            at = [f':(top,literal){path}', f':(top,glob)**/{path}']
            code = [':/', *(f':(top,exclude,glob)**/*.{x}' for x in ('md', 'rst', 'txt', 'adoc', 'mdx', 'org'))]
            return (git('log', '-1', '--format=%h', self.base, '--', *at, cwd=self.root).stdout.strip() or
                    git('log', '-1', '--format=%h', f'-G{word}', self.base, '--', *code, cwd=self.root).stdout.strip())
        return self.once('had', name, look)

    def live(self, name: str, place: str) -> bool:
        return self.has_path(name, place) or self.has_name(name)

    def dead(self, s: str, place: str) -> set[str]:
        return {r for r in references(s) if not self.live(r, place) and self.had(r)}


def without(s: str, names) -> list[str]:
    """The words of `s` in order, the references `names` left out."""
    for n in sorted(names, key=len, reverse=True):
        s = s.replace(n, ' ')
    return re.findall(r'\w+', s)


def same_but(was: str, now: str, place: str, tree: Tree) -> bool:
    """Is `now` the sentence `was` with its dead references taken out, each or none replaced by one that is there."""
    had, has = references(was), references(now)
    gone = [r for r in had if r not in has and r in tree.dead(was, place)]
    put = [r for r in has if r not in had and tree.live(r, place)]
    return bool(gone) and len(put) <= len(gone) and without(was, gone) == without(now, put)


def fix_problem(old: str, new: str, place: str, tree: Tree) -> str:
    """Why the change of `place` from `old` to `new` is more than dead references fixed, or ''."""
    a, b = sentences(old), sentences(new)
    ops = [o for o in SequenceMatcher(None, a, b, autojunk=False).get_opcodes() if o[0] != 'equal']
    if not ops:
        return 'only its spacing changes'
    for _, i1, i2, j1, j2 in ops:
        gone, put = a[i1:i2], b[j1:j2]
        dead: set[str] = set()
        for s in gone:
            if not (d := tree.dead(s, place)):
                return f'what goes names nothing that is gone: "{s[:80]}"'
            dead |= d
        said = {r for p in put for r in references(p)}
        if still := dead & said:
            return f'it still names {", ".join(sorted(still))}'
        left = iter(gone)  # each that stands in their place is one of them, in order
        for p in put:
            if not any(same_but(w, p, place, tree) for w in left):
                return f'it changes more than the name: "{p[:80]}"'
    return ''


def _rel(c, p: Path) -> str:
    return p.relative_to(c.root).as_posix() if p.is_relative_to(c.root) else ''


def plan_problem(c, base: str, head: str, tid: str) -> str:
    """What the plan of `head` (in the repository) changes of `base`'s beside the task `tid`, or ''."""
    def at(rev):
        todo, done = (stale.show(c.root, rev, r).splitlines() if r else [] for r in (_rel(c, c.todo), _rel(c, c.done)))
        out, own, order, ticked = {}, set(), [], set()
        for ls in (done, todo):
            for _, box, t, _, i in P.iter_tasks(ls):
                block = P._item_block(ls, i)
                if ls is todo:
                    own |= set(range(i, i + len(block)))
                    if t != tid and box == 'x':
                        ticked.add(t)
                    elif t != tid:
                        order.append(t)
                if t != tid:
                    out[t] = '\n'.join(block)
        return out, order, ticked, [l.rstrip() for i, l in enumerate(todo) if l.strip() and i not in own]
    was, now = at(base), at(head)
    # one ticked in TODO.md already is archived by the next tick
    changed = sorted(t for t in was[0].keys() | now[0].keys() if was[0].get(t) != now[0].get(t)
                     and not (t in was[2] and t in now[0]))
    if changed:
        return f'it changes {", ".join(changed[:8])} before the sheet is answered'
    return '' if was[1] == now[1] and was[3] == now[3] else 'it changes the order or the text between tasks before the sheet is answered'


def problems(c, base: str, head: str, tid: str, answered: bool) -> dict[str, str]:
    """{file: why} for what the diff from `base` to `head` (a commit or a tree) changes past the fix limit of the
    audit `tid`; `answered`: its sheet was, so it carries out the plan changes."""
    parts = git('diff', '--raw', '-z', '--no-abbrev', '--no-renames', base, head, cwd=c.root).stdout.split('\0')
    is_history = stale.history(c)
    glossary = c.raw['plan'].get('glossary') or ''
    lists = {_rel(c, c.todo), _rel(c, c.done)} - {''}
    plan_dir = '' if c.plan_external else _rel(c, c.plan_dir)
    long_forms = posixpath.normpath(f'{plan_dir}/{P.TASKS}' if plan_dir not in ('', '.') else P.TASKS) + '/'
    journal = _rel(c, c.journal) if c.journal else ''
    tree = None
    out: dict[str, str] = {}
    for meta, f in zip(parts[::2], parts[1::2]):
        was, now, _, _, how = meta.lstrip(':').split()
        if f == audit.findings_file(tid, c) and now in FILE_MODES or \
                journal not in ('', '.') and f.startswith(journal + '/') and (how == 'A' or tid.lower() in f.lower()):
            continue
        if not c.plan_external and f in lists:
            if not answered and (why := plan_problem(c, base, head, tid)):
                out[f] = why
            continue
        if not c.plan_external and f.startswith(long_forms):
            if not answered and f != f'{long_forms}{tid}.md':
                out[f] = "it changes a task before the sheet is answered"
            continue
        if stale.sort_of(f, glossary) not in DOCS or is_history(f):
            out[f] = 'not a doc, the glossary or lessons'
        elif how != 'M' or was != now or now not in FILE_MODES:
            out[f] = 'a file added, deleted or of another mode'
        else:
            old, new = stale.show(c.root, base, f), stale.show(c.root, head, f)
            tree = tree or Tree(c.root, base, head, is_history, glossary)
            if not old or not new:
                out[f] = 'not text, or emptied'
            elif why := fix_problem(old, new, f, tree):
                out[f] = why
    return out


def _at(c, rev: str) -> list[str]:
    """TODO.md's lines as `rev` has them; a plan outside the repository has one copy."""
    if c.plan_external:
        return P.lines(c.todo)
    return git('show', f'{rev}:{_rel(c, c.todo)}', cwd=c.root).stdout.splitlines()


def beyond(tid: str, branch: str) -> list[str] | None:
    """The files task/`tid` changes past its fix limit, as the merge reads them; None when it is no audit."""
    from agent_runner.strays import new_empty
    ls = _at(S.C, branch)
    if not audit.is_audit(tid, ls):
        return None
    base = S.git('merge-base', branch, f'task/{tid}').stdout.strip()
    bad = problems(S.C, base, f'task/{tid}', tid, audit.answered(tid, ls))
    return list(bad) if set(bad) - set(new_empty(tid, branch)) else []


def refusal(tid: str, blocked: str | None, c, tree, prog: str) -> str | None:
    """Why `done` refuses the audit `tid`, or None: a diff past its fix limit, a question that is not its sheet, or a
    sheet not asked. `tree()` is the worktree's content."""
    from agent_runner import sheet
    base = stale.base_of(c, tid)
    plans = [_at(c, r) for r in (base, shared_name(c.root, c.push_remote or 'origin', default=None)) if r]
    if not any(audit.is_audit(tid, ls) for ls in plans):
        return None
    ships = any(P.research_ships('\n'.join(P._item_block(ls, i)), tid) for ls in plans  # the person took the merge's question
                for _, _, t, _, i in P.iter_tasks(ls) if t.rstrip('.') == tid)
    answered = any(audit.answered(tid, ls) for ls in plans)
    asks = bool(blocked) and bool(re.match(r'\s*DECIDE:', blocked))
    f = c.notes('sheets', f'{tid}.json')
    if asks and answered:
        return f'{prog}: {tid} had its one pick sheet, and it is answered: carry that out. Nothing blocked.'
    if c.run['questionnaires'] is not False and not answered:
        if asks:
            try:
                spec = sheet.load(f)
            except ValueError as e:
                return f'{prog}: an audit asks on its pick sheet alone, and that one is none: {e}. Nothing blocked.'
            if why := audit.sheet_problems(spec):
                return f'{prog}: {f}: {"; ".join(why)}. Nothing blocked.'
        elif not blocked and f.is_file():
            return (f'{prog}: {tid} wrote a pick sheet that is not asked: publish it and run this with --blocked '
                    f'"DECIDE: <its summary> <its url>", or delete {f} when nothing needs an answer. Nothing ticked.')
    if not ships and (bad := problems(c, base, tree() or 'HEAD', tid, answered)):
        said = '\n'.join(f'  {p}: {why}' for p, why in bad.items())
        return (f'{prog}: past the audit\'s fix limit (dead references in docs, the glossary and lessons):\n{said}\n'
                f'Take it back, and put it on the pick sheet or queue it as the answer says. Nothing ticked or blocked.')
    return None
