"""`agent-runner voice`: the person's wording, kept in a voice file they shape by talking (F21).

One list line (`- …`) per rule (`say agent, not slot`, `shorter`, `no task ids`). Every control session's brief
carries it, so what they write (answers, the summary, said-back status and since, task text)
follows it; task agents get it too, for what status and since show of their work (commit messages, done and
blocked lines).

    voice show                  the wording every session reads, and the file it is in
    voice add "<line>" [--project]
                                add one line: to the global file (all projects), or with --project to this
                                project's (which starts as a copy of the global lines)
    voice forget WORDS          remove the one line holding WORDS (case ignored) from the file in effect;
                                several such lines: nothing removed, they are listed
    voice path                  the two files, whether or not they exist

Where it lives: `~/.config/agent-runner/voice.md` ($XDG_CONFIG_HOME when set) for all projects, `[run] voice` to
put it elsewhere; `<repo>/.runner/voice.md` (the notes directory) for one project, which overrides the global
file: when it has a line, it is read instead. `[run] voice_learn` = ask (the
default: a session that had to say something again offers one line to add) or off (lines come only when told).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from agent_runner.whole_write import one_change, write_whole

PROG = 'agent-runner voice'
NAME = 'voice.md'
HEAD = """\
# Voice

How I want agent-runner sessions to word things: one rule per list line. Kept by `agent-runner voice` (add, show,
forget) and read by every control session.

"""
LEARN = ('ask', 'off')


def global_path(c=None) -> Path:
    """`[run] voice` (`~` expanded, relative to the repo), else `$XDG_CONFIG_HOME/agent-runner/voice.md`, else
    `~/.config/agent-runner/voice.md`."""
    v = _run(c).get('voice', '')
    if isinstance(v, str) and v.strip():
        p = Path(v.strip()).expanduser()
        return p if p.is_absolute() else Path(_root(c)) / p
    base = os.environ.get('XDG_CONFIG_HOME', '').strip()
    return (Path(base) if base else Path.home() / '.config') / 'agent-runner' / NAME


def project_path(c=None) -> Path:
    """`<main checkout>/<[run] notes>/voice.md`: `.runner/voice.md` by default."""
    from agent_runner.config import main_checkout
    notes = _run(c).get('notes', '.runner') or '.runner'
    return main_checkout(_root(c)) / Path(notes).expanduser() / NAME


def learn_mode(c=None) -> str:
    """`[run] voice_learn`: 'ask' (the default, and for anything it does not know) or 'off' (false too)."""
    v = _run(c).get('voice_learn', 'ask')
    if v is False:
        return 'off'
    v = str(v).strip().lower()
    return v if v in LEARN else 'ask'


def _cfg(c):
    if c is None:
        from agent_runner.config import cfg
        c = cfg()
    return c


def _run(c) -> dict:
    try:
        return _cfg(c).run
    except (Exception, SystemExit):
        return {}


def _root(c) -> Path:
    try:
        return Path(_cfg(c).root)
    except (Exception, SystemExit):
        return Path.cwd()


def rules(p: Path) -> list[str]:
    """A voice file's rules: its list lines (`- …` or `* …`), the marker dropped; headings and prose are not."""
    try:
        text = p.read_text(encoding='utf-8')
    except OSError:
        return []
    return [s for line in text.splitlines() if (t := line.strip())[:2] in ('- ', '* ') and (s := t[2:].strip())]


def in_effect(c=None) -> tuple[str, Path, list[str]] | None:
    """(which, path, lines) of the file sessions read: the project's when it has a line (it overrides the global
    one), else the global one; None when neither has a line."""
    for which, p in (('this project', project_path(c)), ('all projects', global_path(c))):
        if got := rules(p):
            return which, p, got
    return None


def text(c=None) -> str:
    """The wording as the briefs carry it: the file in effect's lines under its name; '' when there are none."""
    got = in_effect(c)
    if not got:
        return ''
    which, p, lines = got
    note = f', read instead of {_shown(global_path(c))}' if which == 'this project' and rules(global_path(c)) else ''
    return f'From {_shown(p)} ({which}{note}):\n' + '\n'.join(f'- {s}' for s in lines)


def _shown(p: Path) -> str:
    """A path as the person would type it: `~/…` under the home folder."""
    try:
        return '~/' + p.relative_to(Path.home()).as_posix()
    except ValueError:
        return p.as_posix()


# --- what the briefs say -------------------------------------------------------------------------------------

def fit(brief: str, cmd: str, c=None) -> str:
    """The control brief with the wording paragraph (fitted to `[run] voice_learn`) and the wording itself."""
    from agent_runner.guide import VOICE, VOICE_LEARN
    learn = VOICE_LEARN.format(cmd=cmd) if learn_mode(c) == 'ask' else ''
    extra = VOICE.format(cmd=cmd, file=_shown(global_path(c)), project=_shown(project_path(c)), learn=learn)
    got = text(c)
    extra += ('\n' + got + '\n') if got else '\nNo wording yet: neither file has a line.\n'
    return f'{brief.rstrip()}\n\n{extra}'


# B98: the control brief keeps the wording itself and a pointer; the paragraph is `guide voice`'s page
POINTER = ("**The person's wording.** Follow every line below in all you write to them; on wording it wins over "
           "this brief. When they tell you how to word things (\"say X not Y\", \"shorter\"), or say \"show my "
           "wording\" or \"forget X\", read `guide voice` first.")


def brief_fit(brief: str, cmd: str, c=None, inline: bool = True) -> str:
    """B98: the control brief with the wording in effect and a pointer to `guide voice` in place of the
    paragraph `fit` adds, so the brief stays short. `inline=False` (wording too long for the brief): a line that
    says how many lines there are and that `guide voice` prints them, in place of the lines themselves."""
    got = text(c)
    if got and not inline:
        n = len((in_effect(c) or ('', '', []))[2])
        got = f'The wording has {n} lines, too many to carry here: read them now with `{cmd} guide voice`.'
    extra = POINTER.format(cmd=cmd)
    if learn_mode(c) == 'ask':
        extra += ' So too when they ask "what?" or say back what you said in their own words.'
    extra += '\n' + (got if got else 'No wording yet: neither file has a line.')
    return f'{brief.rstrip()}\n\n{extra}\n'


def topic(cmd: str, c=None) -> str:
    """B98: `guide voice`: the wording paragraph fitted to `[run] voice_learn`, and the wording in effect."""
    from agent_runner.guide import VOICE, VOICE_LEARN
    learn = VOICE_LEARN.format(cmd=cmd) if learn_mode(c) == 'ask' else ''
    out = '# The person\'s wording\n\n' + VOICE.format(cmd=cmd, file=_shown(global_path(c)),
                                                       project=_shown(project_path(c)), learn=learn)
    got = text(c)
    return out + ('\n' + got + '\n' if got else '\nNo wording yet: neither file has a line.\n')


def slot(prompt: str, c=None) -> str:
    """A task agent's brief with the wording at its end, when there is any: what it writes that status and since
    show (its commit message, done and blocked lines, tasks it files)."""
    from agent_runner.guide import VOICE_SLOT
    got = text(c)
    return f'{prompt.rstrip()}\n\n{VOICE_SLOT}\n{got}\n' if got else prompt


# --- the file ------------------------------------------------------------------------------------------------

def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    write_whole(p, text.encode('utf-8'))


def _lock_file() -> Path:
    """One lock for both voice files, in the person's config folder: never a file beside one `[run] voice` names."""
    base = os.environ.get('XDG_CONFIG_HOME', '').strip()
    return (Path(base) if base else Path.home() / '.config') / 'agent-runner' / 'voice.lock'


@one_change(_lock_file)
def add(c, line: str, project: bool = False) -> str:
    """Append one line; what was done, naming the file. A file that does not exist yet gets a heading first, and
    a project file starting out gets the global lines too: it is read instead of them, so none is lost."""
    line = ' '.join(line.split()).lstrip('-* ').strip()
    if not line:
        raise SystemExit(f'{PROG} add: the line is empty')
    p = project_path(c) if project else global_path(c)
    if line.lower() in (s.lower() for s in rules(p)):
        return f'already in {_shown(p)}: {line}'
    try:
        old = p.read_text(encoding='utf-8')
    except OSError:
        old = HEAD
    if old and not old.endswith('\n'):
        old += '\n'
    copied = rules(global_path(c)) if project and not rules(p) else []
    old += ''.join(f'- {s}\n' for s in copied if s.lower() != line.lower())
    _write(p, old + f'- {line}\n')
    out = f'added to {_shown(p)}: {line}'
    if copied:
        out += f' (with the {len(copied)} lines of {_shown(global_path(c))}, which it now stands in for here)'
    if not project and rules(project_path(c)):
        out += f'; this project reads {_shown(project_path(c))} instead: add it there too with --project'
    return out


@one_change(_lock_file)
def forget(c, words: str) -> str:
    """Remove the one line holding `words` (case ignored) from the file in effect; what was removed, naming the
    file. Several lines holding it: nothing removed, unless one is exactly `words`; they are listed instead."""
    w = ' '.join(words.split()).lower()
    if not w:
        raise SystemExit(f'{PROG} forget: say which line')
    got = in_effect(c)
    if not got:
        return f'no line holds {words.strip()!r}: there is no wording yet'
    _, p, _ = got
    old = p.read_text(encoding='utf-8').splitlines(keepends=True)
    norm = lambda ln: ' '.join(ln.strip()[2:].split()).lower() if ln.strip()[:2] in ('- ', '* ') else None
    hits = [i for i, ln in enumerate(old) if norm(ln) is not None and w in norm(ln)]
    if len(hits) > 1:
        hits = [i for i in hits if norm(old[i]) == w] or hits
    if not hits:
        return f'no line in {_shown(p)} holds {words.strip()!r}'
    if len(hits) > 1:
        return (f'{len(hits)} lines in {_shown(p)} hold {words.strip()!r}, nothing removed; say which:\n'
                + '\n'.join(f'- {old[i].strip()[2:].strip()}' for i in hits))
    gone = old.pop(hits[0]).strip()[2:].strip()
    _write(p, ''.join(old))
    return f'removed from {_shown(p)}: {gone}'


def show(c=None) -> str:
    got = text(c)
    if got:
        return got
    return (f'No wording yet. Add a line with `{PROG} add "<line>"` ({_shown(global_path(c))}, all projects) or '
            f'`--project` ({_shown(project_path(c))}).')


# --- the command ---------------------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] in (['-h'], ['--help'], ['help']):
        print(__doc__)
        return 0
    ap = argparse.ArgumentParser(prog=PROG, description=__doc__.split('\n\n')[0])
    sub = ap.add_subparsers(dest='cmd')
    sub.add_parser('show', help='the wording every session reads')
    a = sub.add_parser('add', help='add one line')
    a.add_argument('line', nargs='+')
    a.add_argument('--project', action='store_true', help="to this project's file, not the global one")
    f = sub.add_parser('forget', help='remove every line holding WORDS')
    f.add_argument('words', nargs='+')
    sub.add_parser('path', help='the two files')
    args = ap.parse_args(argv or ['show'])
    from agent_runner.config import cfg
    c = cfg()
    if args.cmd == 'add':
        print(add(c, ' '.join(args.line), args.project))
    elif args.cmd == 'forget':
        print(forget(c, ' '.join(args.words)))
    elif args.cmd == 'path':
        for which, p in (('all projects', global_path(c)), ('this project', project_path(c))):
            print(f'{which}: {p}' + ('' if p.exists() else ' (none yet)'))
    else:
        print(show(c))
    return 0
