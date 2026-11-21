"""`agent-runner voice`: the person's wording, kept in a voice file they shape by talking (F21).

One list line (`- …`) per rule (`say agent, not slot`, `shorter`, `no task ids`). Every control session's brief and the runner
feed's system prompt carry it, so what they write (answers, the summary, said-back status and since, task text)
follows it.

    voice show                  the wording every session reads, with the file each line is in
    voice add "<line>" [--project]
                                add one line: to the global file (all projects), or with --project to this
                                project's
    voice forget WORDS          remove every line holding WORDS (case ignored), from both files
    voice path                  the two files, whether or not they exist

Where it lives: `~/.config/agent-runner/voice.md` ($XDG_CONFIG_HOME when set) for all projects, `[run] voice` to
put it elsewhere; `<repo>/.runner/voice.md` (the notes directory) for one project. Both are read, the project's
lines after the global ones, and where they disagree the project's line wins. `[run] voice_learn` = ask (the
default: a session that had to say something again offers one line to add) or off (lines come only when told).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROG = 'agent-runner voice'
NAME = 'voice.md'
HEAD = """\
# Voice

How I want agent-runner sessions to word things: one rule per list line. Kept by `agent-runner voice` (add, show,
forget) and read by every control session and the runner feed.

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


def files(c=None) -> list[tuple[str, Path, list[str]]]:
    """[(which, path, lines)] for the global file and the project's, in reading order, those with lines only."""
    out = []
    for which, p in (('all projects', global_path(c)), ('this project', project_path(c))):
        if got := rules(p):
            out.append((which, p, got))
    return out


def text(c=None) -> str:
    """The wording as the briefs carry it: each file's lines under the file's name, the project's last; '' when
    neither file has a line."""
    got = files(c)
    if not got:
        return ''
    parts = []
    for which, p, lines in got:
        note = ' (wins where it disagrees with the global lines)' if which == 'this project' and len(got) > 1 else ''
        parts.append(f'From {_shown(p)}, {which}{note}:\n' + '\n'.join(f'- {s}' for s in lines))
    return '\n'.join(parts)


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


def feed(prompt: str, c=None) -> str:
    """The runner feed's system prompt with the wording at its end, when there is any (read at the feed's start:
    it has no file tools)."""
    from agent_runner.guide import VOICE_FEED
    got = text(c)
    return f'{prompt.rstrip()}\n\n{VOICE_FEED}\n{got}\n' if got else prompt


# --- the file ------------------------------------------------------------------------------------------------

def add(c, line: str, project: bool = False) -> str:
    """Append one line (a file that does not exist yet gets a heading first); what was done, naming the file."""
    line = ' '.join(line.split()).lstrip('-* ').strip()
    if not line:
        raise SystemExit(f'{PROG} add: the line is empty')
    p = project_path(c) if project else global_path(c)
    have = rules(p)
    if line.lower() in (s.lower() for s in have):
        return f'already in {_shown(p)}: {line}'
    try:
        old = p.read_text(encoding='utf-8')
    except OSError:
        old = HEAD
    if old and not old.endswith('\n'):
        old += '\n'
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + '.tmp')
    tmp.write_text(old + f'- {line}\n', encoding='utf-8')
    os.replace(tmp, p)
    return f'added to {_shown(p)}: {line}'


def forget(c, words: str) -> str:
    """Remove every line holding `words` (case ignored) from both files; what was removed, naming each file."""
    w = ' '.join(words.split()).lower()
    if not w:
        raise SystemExit(f'{PROG} forget: say which line')
    done = []
    for p in (global_path(c), project_path(c)):
        try:
            old = p.read_text(encoding='utf-8')
        except OSError:
            continue
        keep, gone = [], []
        for line in old.splitlines(keepends=True):
            s = line.strip()
            if s[:2] in ('- ', '* ') and w in ' '.join(s[2:].split()).lower():
                gone.append(s[2:].strip())
            else:
                keep.append(line)
        if gone:
            tmp = p.with_name(p.name + '.tmp')
            tmp.write_text(''.join(keep), encoding='utf-8')
            os.replace(tmp, p)
            done += [f'removed from {_shown(p)}: {g}' for g in gone]
    return '\n'.join(done) if done else f'no line holds {words.strip()!r}'


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
