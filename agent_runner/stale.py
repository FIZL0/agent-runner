"""F416: the removal check. When a task's diff deletes or renames a file, test, setting or command, `done` lists what
still names it. A dead path in code, config or CI refuses `done`; the rest is a list the agent answers once, with
`--named "1 filed B12; 2-3 kept because …"` (what is fixed is gone from the list by itself).

It reads text only: git's diff and grep, the plan's open tasks, this project's Claude Code memories. No model call.
Only names specific enough to search are looked for. History may name what is gone: DONE.md, CHANGELOG, findings
(docs/research), the journal, closed tasks' long forms.
"""
from __future__ import annotations

import fnmatch
import json
import os
import posixpath
import re
import tempfile
from pathlib import Path
from typing import NamedTuple

from agent_runner import plan
from agent_runner.config import main_checkout
from agent_runner.gitops import git, shared_name


class Gone(NamedTuple):
    """Something the diff removed: its kind, its name, what it became ('' = deleted), and other names for it."""
    kind: str  # file, test, setting, command, workflow
    name: str
    now: str = ''
    also: tuple[str, ...] = ()

    @property
    def said(self) -> str:
        return f'{self.kind} `{self.name}` ' + (f'(renamed to `{self.now}`)' if self.now else '(removed)')


class Mention(NamedTuple):
    """A place that still names one: `dead` when it is a dead path in code, config or CI."""
    what: str   # Gone.said
    sort: str   # code, config, CI, docs, glossary, lessons, other, open task, open auto-filed CI task, memory
    place: str  # a file, or a task's id
    lines: tuple[int, ...] = ()
    dead: bool = False

    @property
    def key(self) -> str:  # not the line numbers: they move
        return f'{self.what}\t{self.sort}\t{self.place}'

    def __str__(self) -> str:
        at = ':' + ','.join(map(str, self.lines[:4])) + ('…' if len(self.lines) > 4 else '') if self.lines else ''
        return f'{self.sort} {self.place}{at} names {self.what}'


# --- which names are specific enough ---------------------------------------------------------------------------

COMMON = set('app base build cli client common conf config conftest core helpers index init license main makefile models '
             'readme run script server settings setup style styles test tests types util utils version'.split())


def specific(name: str) -> bool:
    """A name a search finds and little else: two words or more (a_b, a-b, a.b, a/b, aB, 'a b'), not one common one."""
    return len(name) >= 5 and bool(re.search(r'\w[ _./:-]+\w|[a-z][A-Z]', name.strip('_. -')))


def specific_file(base: str) -> bool:
    """`specific`, for a file's name without its folder: its extension makes a longer, uncommon word do."""
    stem, ext = posixpath.splitext(base)
    return specific(stem) or bool(ext) and len(stem) >= 4 and stem.lower().strip('_') not in COMMON


# --- what a file's text defines --------------------------------------------------------------------------------

TEST_DEFS = [re.compile(p, re.M) for p in (
    r'^\s*(?:async\s+)?def (test_\w+)\(',               # Python
    r'^\s*class (Test\w+|\w+Test)\b',
    r'^func (Test\w+)\(',                               # Go
    r'^\s*(?:async\s+)?fn (test_\w+|\w+_test)\(',       # Rust
    r'''^\s*(?:it|test)(?:\.\w+)?\(\s*(['"`])(.+?)\1\s*,''',  # JavaScript
)]
ENV = re.compile(r'''(?:environ(?:\.get\(|\[)|getenv\(|env::var\(|process\.env\[)\s*['"]([A-Z][A-Z0-9_]+)['"]'''
                 r'''|process\.env\.([A-Z][A-Z0-9_]+)''')
PARSERS = re.compile(r'''(?:add_parser|\.command)\(\s*['"]([\w:-]+)['"]''')
DICT_KEY = re.compile(r'''['"]([\w.-]+)['"]\s*:''')
CONSTANT = re.compile(r'^([A-Z][A-Z0-9_]+)\s*(?::[^=\n]+)?=(?!=)', re.M)
FIELD = re.compile(r'^\s+(\w+)\s*:\s*[\w\[\]., |]+=(?!=)', re.M)
FILE_KEY = re.compile(r'''^\s*(?:export\s+)?["']?([\w.-]+)["']?\s*[=:]''')
LOCKS = re.compile(r'(^|[-.])lock(\.\w+)?$|^npm-shrinkwrap\.json$|^go\.sum$', re.I)
CODE = set('py pyi js mjs cjs jsx ts mts cts tsx vue svelte sh bash zsh fish ps1 bat cmd rb go rs c h cc cpp cxx hpp hh m '
           'mm java kt kts scala swift cs php pl pm lua r jl ex exs erl hs clj dart zig nim sql html htm css scss sass '
           'less tf hcl nix gradle cmake mk el vim awk sed qml glsl metal'.split())
CONFIG = set('toml yaml yml json json5 jsonc ini cfg conf env properties xml plist service timer desktop'.split())
CONFIG_NAMES = re.compile(r'^(Makefile|GNUmakefile|justfile|Dockerfile.*|Containerfile|Procfile|CMakeLists\.txt|'
                          r'requirements[\w-]*\.txt|MANIFEST\.in|CODEOWNERS|\.env.*|\.gitattributes|\.gitmodules|'
                          r'\.editorconfig|\.\w+rc)$', re.I)
CI = ('.github/workflows/*', '.github/actions/*', '.gitea/workflows/*', '.forgejo/workflows/*', '.circleci/*',
      '.buildkite/*', '.woodpecker/*', '.woodpecker.y*ml', '.gitlab-ci*', '.gitlab/*', '.travis.yml', 'Jenkinsfile',
      'azure-pipelines*', 'bitbucket-pipelines*', 'appveyor.yml', '.drone.yml')
WORKFLOWS = ('.github/workflows/*',)
SETTINGS_FILE = re.compile(r'config|settings|options|defaults', re.I)
COMMANDS_FILE = re.compile(r'^(cli|commands?|cmds)$', re.I)


def any_glob(path: str, globs) -> bool:
    return any(fnmatch.fnmatchcase(path, g) for g in globs)


def sort_of(path: str, glossary: str = '') -> str:
    """What sort of place a file is."""
    base = posixpath.basename(path)
    ext = posixpath.splitext(base)[1][1:].lower()
    if any_glob(path, CI):
        return 'CI'
    if path == glossary or base.upper() == 'GLOSSARY.MD':
        return 'glossary'
    if re.search(r'(^|[/_-])lessons?\b', path, re.I) and ext in ('md', 'txt', 'rst'):
        return 'lessons'
    if re.search(r'^\.\w*ignore$', base):  # a pattern there may well match nothing
        return 'other'
    if CONFIG_NAMES.match(base) or ext in CONFIG:
        return 'config'
    if ext in ('md', 'rst', 'txt', 'adoc', 'mdx', 'org') or ext in ('html', 'htm') and path.startswith('docs/'):
        return 'docs'
    return 'code' if ext in CODE or not ext else 'other'


def tests_in(text: str) -> set[str]:
    return {m[m.re.groups] for p in TEST_DEFS for m in p.finditer(text)}


def defined(path: str, text: str) -> set[tuple[str, str]]:
    """The (kind, name)s of the tests, settings and commands the file at `path` defines, as far as a regex tells."""
    base = posixpath.basename(path)
    stem, ext = posixpath.splitext(base)
    ext = ext[1:].lower()
    sort = sort_of(path)
    out: set[tuple[str, str]] = set()
    if LOCKS.search(base):
        return out
    if re.search(r'test|spec', path, re.I) and sort == 'code':
        return {('test', n) for n in tests_in(text)}
    if any_glob(path, WORKFLOWS):
        return {('workflow', m[1].strip('\'"')) for m in re.finditer(r'^name:\s*(.+?)\s*(?:#.*)?$', text, re.M)}
    if sort == 'code':
        out |= {('setting', m[1] or m[2]) for m in ENV.finditer(text)}
        out |= {('command', m[1]) for m in PARSERS.finditer(text)}
        if SETTINGS_FILE.search(stem):
            out |= {('setting', m[1]) for p in (DICT_KEY, CONSTANT, FIELD) for m in p.finditer(text)}
        elif COMMANDS_FILE.match(stem):
            out |= {('command', m[1]) for m in DICT_KEY.finditer(text)}
    elif base == 'package.json':
        try:
            scripts = json.loads(text).get('scripts') or {}
            out |= {('command', f'npm run {n}') for n in scripts}
        except (ValueError, AttributeError, TypeError):
            pass
    elif base.lower() in ('makefile', 'gnumakefile', 'justfile'):
        run = 'just' if base.lower() == 'justfile' else 'make'
        out |= {('command', f'{run} {m[1]}') for m in re.finditer(r'^@?([A-Za-z][\w-]*)\b[^:=\n]*:(?!=)', text, re.M)}
    elif sort == 'config' and ext != 'xml' and (ext not in ('json', 'json5', 'jsonc') or
                                                re.search(r'config|settings|options|rc$', stem, re.I)):
        section = ''
        for l in text.splitlines():
            if m := re.match(r'\s*\[+([^\]]+)\]+\s*(?:#.*)?$', l):
                section = m[1].lower()
            elif (m := FILE_KEY.match(l)) and 'dependencies' not in section:
                out.add(('command' if section.endswith('scripts') else 'setting', m[1]))
    return out


# --- what the diff removes -------------------------------------------------------------------------------------

def base_of(c, tid: str) -> str:
    """What this worktree's own work is past: the merge it was started on (F198), else the shared branch."""
    shared = shared_name(c.root, c.push_remote or 'origin', default=None)
    base = shared and git('merge-base', 'HEAD', shared, cwd=c.root).stdout.strip() or 'HEAD'
    try:
        on = json.loads(c.notes(f'{tid}.stacked').read_text(encoding='utf-8'))['on']
    except (OSError, ValueError, KeyError, TypeError):
        return base
    inside = lambda a, b: not git('merge-base', '--is-ancestor', a, b, cwd=c.root).returncode  # noqa: E731
    return on if isinstance(on, str) and on and inside(on, 'HEAD') and inside(base, on) else base


def history(c):
    """path -> whether it is history, or the plan's own lists, which are read as open tasks instead."""
    rel = lambda p: p.relative_to(c.root).as_posix() if p.is_relative_to(c.root) else None  # noqa: E731
    globs = ['docs/research/*'] + [g for g in c.run['findings'] or [] if not g.startswith('!')]
    plan_dir = rel(c.plan_dir)
    if plan_dir is not None:
        pre = '' if plan_dir == '.' else plan_dir + '/'
        globs += [f'{pre}TODO.md', f'{pre}DONE.md', f'{pre}{plan.TASKS}/*']
    if c.journal and (j := rel(c.journal)) and j != '.':
        globs.append(f'{j}/*')

    def is_history(path: str) -> bool:
        base = posixpath.basename(path)
        return (base == 'DONE.md' or base.upper().startswith(('CHANGELOG', 'CHANGES.')) or any_glob(path, globs)
                or plan_dir is not None and posixpath.dirname(path) == ('' if plan_dir == '.' else plan_dir)
                and bool(plan.TASK_ID.fullmatch(posixpath.splitext(base)[0])))
    return is_history


def show(root: Path, rev: str, path: str) -> str:
    r = git('show', f'{rev}:{path}', cwd=root)
    return '' if r.returncode or '\0' in r.stdout[:8000] else r.stdout


def removed(root: Path, base: str, tree: str, files: set[str], is_history) -> list[Gone]:
    """What `tree` (its `files`) no longer has of `base`."""
    parts = git('diff', '--name-status', '-z', '-M', base, tree, cwd=root).stdout.split('\0')
    out: list[Gone] = []
    old: set[tuple[str, str]] = set()
    new: set[tuple[str, str]] = set()
    bases = {posixpath.basename(f) for f in files}
    i = 0
    while i + 1 < len(parts):
        status = parts[i]
        was, now = parts[i + 1], parts[i + 2] if status[:1] in 'RC' else parts[i + 1]
        i += 3 if status[:1] in 'RC' else 2
        if status[:1] in 'DMRT' and not is_history(was):
            old |= defined(was, show(root, base, was))
        if status[:1] in 'AMRCT' and not is_history(now):
            new |= defined(now, show(root, tree, now))
        if status[:1] not in 'DR' or is_history(was):
            continue
        # no longer tracked, but ignored: something still makes it
        if not git('check-ignore', '-q', '--no-index', '--', was, cwd=root).returncode:
            continue
        name = posixpath.basename(was)
        also = [name] if '/' in was and name not in bases and specific_file(name) else []
        mod = was.removesuffix('.py').removesuffix('/__init__')
        if was.endswith('.py') and '/' in mod and not any(
                f in (f'{mod}.py', f'{mod}/__init__.py') or f.startswith(f'{mod}/') for f in files):
            also.append(mod.replace('/', '.'))
        out.append(Gone('file', was, now if status[:1] == 'R' else '', tuple(also)))
    return out + [Gone(k, n) for k, n in sorted(old - new)]


# --- who still names it ----------------------------------------------------------------------------------------

def patterns(g: Gone, bases: set[str]) -> list[str]:
    """The names of `g` to search for."""
    if g.kind == 'file':
        if '/' in g.name:
            path = [g.name] if len(g.name) >= 5 else []
        else:
            path = [g.name] if specific_file(g.name) and g.name not in bases else []
        return [*path, *g.also]
    return [] if g.kind == 'workflow' or not specific(g.name) else [g.name]


def spots(name: str, line: str):
    """Where `line` holds `name` as a whole word (`x.py` is not in `x.pyc`, `ax.py` or `x.py.bak`)."""
    for m in re.finditer(re.escape(name), line):
        before, after = line[:m.start()], line[m.end():]
        if not re.search(r'[\w-]$', before) and not re.match(r'[\w-]|\.\w', after):
            yield m.start()


def path_at(line: str, at: int, path: str, place: str, files: set[str]) -> str:
    """What `path` at line[at] is in the file `place`: 'dead', 'other' (a URL, another folder's) or '' (one that is
    there)."""
    pre = re.search(r'[\w.$@{}~:+/)-]*$', line[:at])[0]
    here = posixpath.dirname(place)
    there = lambda p: posixpath.normpath(p).lstrip('/') in files  # noqa: E731
    if set(pre) <= set('./'):
        if there(posixpath.join(here, pre.lstrip('/') + path)):
            return ''
        if not pre or pre == './':
            return 'dead'
        target = posixpath.normpath(posixpath.join(here, pre + path))
        return 'dead' if pre.startswith('../') and target == path else 'other'
    if pre.endswith('/') and there(pre + path):
        return ''
    return 'dead' if re.search(r'(\$\w+|[)}])/$', pre) else 'other'


def in_tree(gone: list[Gone], root: Path, tree: str, files: set[str], is_history, glossary: str) -> list[Mention]:
    """The files of `tree` that name something of `gone`; the gone that turn out to be defined there still are
    taken out of `gone`."""
    bases = {posixpath.basename(f) for f in files}
    names = {n: g for g in gone for n in patterns(g, bases)}
    if not names:
        return []
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / 'names'
        f.write_text('\n'.join(names) + '\n', encoding='utf-8')
        # from the top, whatever folder: a tree's paths are the whole repository's
        out = git('grep', '-n', '-I', '-z', '-F', '-f', str(f), tree, '--', ':/', cwd=root).stdout
    found: dict[tuple[Gone, str], tuple[list[int], bool]] = {}
    for l in out.split('\n'):
        try:
            place, no, text = l.split('\0', 2)
        except ValueError:
            continue
        place = place.split(':', 1)[1]
        if is_history(place) or LOCKS.search(posixpath.basename(place)):
            continue
        for name, g in names.items():
            if name not in text:
                continue
            dead = [path_at(text, at, name, place, files) if name == g.name and g.kind == 'file' else 'other'
                    for at in spots(name, text)]
            if g.kind == 'file' and name != g.name and any(spots(g.name, text)):
                continue  # the path's own spot says it
            if not (dead := [d for d in dead if d]):
                continue
            nos, was = found.setdefault((g, place), ([], False))
            if int(no) not in nos:
                nos.append(int(no))
            found[g, place] = nos, was or 'dead' in dead
    defs = {p: defined(p, show(root, tree, p)) for p in {p for _, p in found}}
    kept = {g for g, p in found if (g.kind, g.name) in defs[p]}
    gone[:] = [g for g in gone if g not in kept]
    out = []
    for (g, place), (nos, dead) in found.items():
        if g not in kept:
            sort = sort_of(place, glossary)
            out.append(Mention(g.said, sort, place, tuple(nos), dead and sort in ('code', 'config', 'CI')))
    return out


def in_text(gone: list[Gone], text: str, bases: set[str]) -> list[Gone]:
    """Those of `gone` that `text` names."""
    return [g for g in gone if any(any(spots(n, l)) for n in patterns(g, bases) if n in text
                                   for l in text.splitlines() if n in l)]


CI_TASK = re.compile(r'^CI: `(.+?)` on \S+ is red|^make the test `(.+?)` ')


def in_tasks(gone: list[Gone], c, tid: str, files: set[str]) -> list[Mention]:
    """The open tasks (and their long forms) that name something of `gone`, `tid` itself left out."""
    from agent_runner.ci import FILED, _key
    bases = {posixpath.basename(f) for f in files}
    ls = plan.lines(c.todo) if c.todo.exists() else []
    out = []
    for _, box, t, rest, i in plan.iter_tasks(ls):
        t = t.rstrip('.')
        if box == 'x' or t == tid:
            continue
        own = plan.long_form(c.plan_dir, t)
        text = '\n'.join(plan._item_block(ls, i) + (plan.lines(own) if own.exists() else []))
        auto = CI_TASK.match(rest.strip()) if FILED.search(text) else None
        hit = in_text(gone, text, bases)
        if auto:  # its line names the test or workflow in backticks, whatever the word
            ticked = re.findall(r'`([^`]+)`', text)
            ends = {t for name in ticked for t in (name, name.split('::')[-1])}
            for g in gone:
                named = g.kind == 'workflow' and g.name == auto[1] or g.kind == 'test' and _key(g.name) in ends or \
                    g.kind == 'file' and g.name in {name.split('::')[0] for name in ticked}
                if named and g not in hit:
                    hit.append(g)
        out += [Mention(g.said, 'open auto-filed CI task' if auto else 'open task', t) for g in hit]
    return out


def in_memories(gone: list[Gone], c, files: set[str]) -> list[Mention]:
    """This project's Claude Code memories (of the main checkout and of this worktree) that name one of `gone`."""
    from agent_runner.watch import project_slug
    bases = {posixpath.basename(f) for f in files}
    home = Path(os.environ.get('CLAUDE_CONFIG_DIR') or Path.home() / '.claude') / 'projects'
    out = []
    for d in dict.fromkeys(home / project_slug(p) / 'memory' for p in (main_checkout(c.root), c.root)):
        for f in sorted(d.glob('**/*.md')):
            out += [Mention(g.said, 'memory', str(f)) for g in in_text(gone, read(f), bases)]
    return out


def in_plan_files(gone: list[Gone], c, files: set[str]) -> list[Mention]:
    """A plan outside the repository: its lessons and overviews, which no grep of the repository sees."""
    if not c.plan_external:
        return []
    bases = {posixpath.basename(f) for f in files}
    return [Mention(g.said, 'lessons' if f.stem.upper().startswith('LESSON') else 'docs', str(f))
            for f in sorted(c.plan_dir.glob('*.md'))
            if f.name not in ('TODO.md', 'DONE.md') and not plan.TASK_ID.fullmatch(f.stem)
            for g in in_text(gone, read(f), bases)]


def read(f: Path) -> str:
    try:
        return f.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return ''


def mentions(c, tid: str, tree: str) -> list[Mention]:
    """All that still names what this worktree's diff (as `tree`) removes."""
    base = base_of(c, tid)
    files = {f for f in git('ls-tree', '-r', '-z', '--full-tree', '--name-only', tree, cwd=c.root).stdout.split('\0') if f}
    is_history = history(c)
    gone = removed(c.root, base, tree, files, is_history)
    if not gone:
        return []
    out = in_tree(gone, c.root, tree, files, is_history, str(c.raw['plan']['glossary'] or ''))
    gone = [g for g in gone if g.kind != 'workflow' or not any(
        ('workflow', g.name) in defined(f, show(c.root, tree, f)) for f in files if any_glob(f, WORKFLOWS))]
    return out + in_plan_files(gone, c, files) + in_tasks(gone, c, tid, files) + in_memories(gone, c, files)


# --- the answers -----------------------------------------------------------------------------------------------

ANSWER = re.compile(r'(?:(all|\d[\d\s,-]*)\s+)?(fixed|filed(?:\s+as)?\s+(\S+?)|kept because\s+(\S.*))\s*$', re.S)
FORM = '"1 filed B12; 2-3 kept because <why>" (no number: all of them)'


def answers_file(root: Path, tid: str) -> Path | None:
    """Where the list shown and its answers are kept: in this worktree's own git dir, as the failed gates are."""
    r = git('rev-parse', '--absolute-git-dir', cwd=root)
    return None if r.returncode else Path(r.stdout.strip()) / 'agent-runner' / 'still-named' / f'{tid}.json'


def numbers(text: str | None, most: int) -> list[int] | None:
    """The places '1,3-4' names, of `most`; all for none or 'all'. None: not such a list."""
    if not text or text == 'all':
        return list(range(1, most + 1))
    out: list[int] = []
    for part in re.split(r'[\s,]+', text.strip(' ,')):
        if not (m := re.fullmatch(r'(\d+)(?:-(\d+))?', part)):
            return None
        a, b = int(m[1]), int(m[2] or m[1])
        if not 1 <= a <= b <= most:
            return None
        out += range(a, b + 1)
    return out


def answered(text: str, listed: list[str], c) -> tuple[dict[str, str], str]:
    """({mention key: answer}, '') as `--named` says it of the list last shown, or ({}, what is wrong with it)."""
    out: dict[str, str] = {}
    for part in re.split(r';\s*(?=(?:(?:all|\d[\d\s,-]*)\s+)?(?:fixed|filed|kept because)\b)', text.strip().rstrip(';')):
        m = ANSWER.fullmatch(part.strip())
        nos = m and numbers(m[1], len(listed))
        if not m or nos is None:
            return {}, f'--named does not read {part.strip()!r}: {FORM}'
        if m[3] and not exists(m[3], c):
            return {}, f'--named: no open task {m[3]}'
        for n in nos:
            out[listed[n - 1]] = m[2].strip()
    return out, ''


def exists(tid: str, c) -> bool:
    """`tid` is an open task, here or (filed from there) in the main checkout."""
    todos = [c.todo]
    if not c.plan_external:
        todos.append(main_checkout(c.root) / c.plan_dir.relative_to(c.root) / 'TODO.md')
    return any(t.rstrip('.') == tid and box != 'x' for f in todos if f.exists()
               for _, box, t, _, _ in plan.iter_tasks(plan.lines(f)))


def refusal(tid: str, named: str | None, c, tree: str, prog: str) -> str | None:
    """Why `done` refuses `tid`'s diff (its content is `tree`), or None."""
    found = mentions(c, tid, tree) if tree else []
    f = answers_file(c.root, tid)
    if not found or f is None:
        return None
    if dead := [m for m in found if m.dead]:
        return '\n'.join([f'{prog}: this diff removes a file that code, config or CI still names (a dead path):',
                          *(f'  {m}' for m in dead), 'Fix each, then run it again (code that must name it, a fixture '
                          'or a migration, can build the path from its parts). Nothing ticked.'])
    try:
        kept = json.loads(f.read_text(encoding='utf-8'))
        listed, answers = list(kept['listed']), dict(kept['answers'])
    except (OSError, ValueError, KeyError, TypeError):
        listed, answers = [], {}
    wrong = ''
    if named and listed:
        new, wrong = answered(named, listed, c)
        answers |= new
    by_key = {m.key: m for m in found}
    if fixed := [k for k, a in answers.items() if a == 'fixed' and k in by_key]:
        wrong = wrong or 'answered fixed, but still named'
    for k in fixed:
        del answers[k]
    left = [k for k in by_key if k not in answers]
    if wrong and not left:  # nothing is left to answer: a bad word about it does no harm
        wrong = ''
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({'listed': left or listed, 'answers': answers}, indent=1), encoding='utf-8')
    if not left:
        if named:
            print('still named, answered:')
            for k, m in by_key.items():
                print(f'  {m}: {answers[k]}')
        return None
    return '\n'.join([*([f'{prog}: {wrong}'] if wrong else []),
                      f'{prog}: this diff removes what is still named here:',
                      *(f'  {n}. {by_key[k]}' for n, k in enumerate(left, 1)),
                      'Fix what is wrong there now (then it is off this list), file it, or keep it, and run it again '
                      f'with\n    --named {FORM}\nEach is answered once. Nothing ticked.'])
