"""Build output in a worktree, and what git ignores there that is not (B776).

`git worktree remove` refuses uncommitted and untracked files but deletes git-ignored ones, and those can be
someone's notes or scripts. `held_files` names them; build output (known by the mark its tool leaves, never by a
folder called build or dist) and links are not among them. When in doubt, a file is held.
"""
from __future__ import annotations

import hashlib
import os
import subprocess as sp
from pathlib import Path

CACHEDIR_SIGNATURE = b'Signature: 8a477f597d28d172789f06886806bc55'  # bford.info/cachedir
CARGO_FILES = {'CACHEDIR.TAG', '.rustc_info.json', '.cargo-lock'}


def held_files(d: Path) -> list[str] | None:
    """What git ignores in worktree `d` that is no build output and no link, as paths under it (a folder with
    nothing else in it as one, 'notes/'). None when git could not tell."""
    try:
        r = sp.run(['git', 'ls-files', '--others', '--ignored', '--exclude-standard', '--directory', '-z'],
                   cwd=d, capture_output=True, timeout=60)
    except (OSError, sp.SubprocessError):
        return None
    if r.returncode:
        return None
    rels = sorted({os.fsdecode(x).rstrip('/') for x in r.stdout.split(b'\0') if x})
    out: list[str] = []
    seen: set[str] = set()
    for rel in rels:  # a folder sorts before what is in it, which git may list too
        if any(str(p) in seen for p in _parents(rel)):
            continue
        seen.add(rel)
        out += _held(d / rel, rel)[0]
    return out


def _parents(rel: str) -> list[str]:
    parts = rel.split('/')
    return ['/'.join(parts[:i]) for i in range(1, len(parts))]


def _held(p: Path, rel: str, cargo: bool = False) -> tuple[list[str], bool]:
    """(the held paths in `p`, is there anything in it that is not held). `cargo`: inside a Cargo target folder."""
    if p.is_symlink():
        return [], True
    if not p.is_dir():
        known = p.suffix == '.pyc' or (cargo and p.name in CARGO_FILES)
        return ([], True) if known else ([rel], False)
    try:
        kids = sorted(p.iterdir())
    except OSError:
        return [rel + '/'], False
    names = {k.name for k in kids}
    if '.git' in names:  # a repository of its own: its commits are nowhere else
        return [rel + '/'], False
    target = _cargo_target(p)
    if _is_build_output(p, names, target, cargo):
        repos = _repos_held(p)
        return [f'{rel}/{r}/' for r in repos], True
    out, other = [], not kids
    for k in kids:
        held, rest = _held(k, f'{rel}/{k.name}', target)
        out += held
        other = other or rest
    return (out, True) if other else ([rel + '/'], False)


def _read(p: Path, n: int = 512) -> bytes:
    try:
        with open(p, 'rb') as f:
            return f.read(n)
    except OSError:
        return b''


def _cargo_target(p: Path) -> bool:
    """Is `p` a Cargo target folder? It can hold hand-made checkouts and pictures beside Cargo's own folders, so
    its cache tag does not speak for all of it."""
    tag = _read(p / 'CACHEDIR.TAG')
    return (tag.startswith(CACHEDIR_SIGNATURE) and b'created by cargo' in tag) or (p / '.rustc_info.json').is_file()


def _is_build_output(p: Path, names: set[str], target: bool, cargo: bool) -> bool:
    if target:
        return False  # looked into: only its profile folders are known
    if cargo:
        return '.fingerprint' in names and 'deps' in names  # a profile: debug, release, …
    if p.name == '__pycache__':
        return False  # its .pyc files are known one by one
    if 'CMakeCache.txt' in names:
        return _out_of_source(p)
    return (p.name == 'node_modules' or 'pyvenv.cfg' in names
            or (p.name.endswith('.egg-info') and 'PKG-INFO' in names)
            or _read(p / 'CACHEDIR.TAG').startswith(CACHEDIR_SIGNATURE))


def _out_of_source(p: Path) -> bool:
    """Does CMake build folder `p` build sources that are not in it?"""
    for line in _read(p / 'CMakeCache.txt', 4 << 20).splitlines():
        if line.startswith(b'CMAKE_HOME_DIRECTORY:'):
            try:
                home = Path(os.fsdecode(line.partition(b'=')[2].strip())).resolve()
                return not home.is_relative_to(p.resolve())
            except (OSError, ValueError, RuntimeError):
                return False
    return False


def _repos_held(p: Path) -> list[str]:
    """The git repositories inside build output `p`, but for CMake-fetched ones with nothing of their own."""
    out = []
    for top, dirs, files in os.walk(p, onerror=lambda e: None):
        if '.git' in dirs or '.git' in files:
            rel = Path(top).relative_to(p)
            if '_deps' not in rel.parts or not _fetched_only(Path(top)):
                out.append(rel.as_posix())
        dirs[:] = [x for x in dirs if x != '.git']
    return sorted(out)


def _fetched_only(repo: Path) -> bool:
    """Has `repo` no local change and no commit that did not come from its remote?"""
    def g(*args: str) -> str | None:
        try:
            r = sp.run(['git', *args], cwd=repo, capture_output=True, text=True, errors='replace', timeout=30)
        except (OSError, sp.SubprocessError):
            return None
        return r.stdout.strip() if r.returncode == 0 else None
    top = g('rev-parse', '--show-toplevel')
    if not top or Path(top).resolve() != repo.resolve() or g('status', '--porcelain') != '':
        return False
    fetched = ['FETCH_HEAD'] if g('rev-parse', '--verify', '-q', 'FETCH_HEAD') else []
    return g('rev-list', '-n1', '--all', 'HEAD', '--not', '--remotes', '--tags', *fetched) == ''


def held_names(held: list[str], most: int = 12) -> str:
    """'modding/, notes.txt and 3 more'; past 4 paths, by their folder at the top, so each one shows."""
    if len(held) > 4:
        held = list(dict.fromkeys(top + ('/' if sep else '') for top, sep, _ in (h.partition('/') for h in held)))
    more = f' and {len(held) - most} more' if len(held) > most else ''
    return ', '.join(held[:most]) + more


def held_key(held: list[str] | None) -> str | None:
    """A short key of the list `held_files` gave: '' for an empty one, None for none."""
    if not held:
        return None if held is None else ''
    return hashlib.sha1('\0'.join(held).encode('utf-8', 'surrogateescape')).hexdigest()[:12]
