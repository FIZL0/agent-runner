"""F500: slot worktrees built faster. A new worktree is registered under one lock and checked out outside it, so
several are built at once; a slot past the run's count is kept as a spare (`.spare-sN`) and moved back into
use instead of being built again; each step's time is logged, so the slow one shows."""

from __future__ import annotations

import re
import threading
import time
from pathlib import Path

from agent_runner import state as S  # S.X: init and runner.X = v reach it

REGISTER = threading.Lock()  # `git worktree prune/add/move` change .git/worktrees: one at a time
_DIR_LOCKS: dict[str, threading.Lock] = {}
_DIR_LOCKS_LOCK = threading.Lock()
SLOW = 5.0  # a step slower than this many seconds is logged


def dir_lock(d: Path) -> threading.Lock:
    """One lock per worktree folder: a slot being prepared is not built twice at once."""
    with _DIR_LOCKS_LOCK:
        return _DIR_LOCKS.setdefault(str(d), threading.Lock())


def timed(what: str, step: str, t0: float, always: bool = False) -> None:
    if (s := time.monotonic() - t0) >= SLOW or always:
        S.log(f'{what}: {step} took {s:.0f}s')


def spares() -> list[Path]:
    return sorted(d for d in S.SLOTS_DIR.glob('.spare-*') if d.is_dir())


def keep_spare(d: Path) -> bool:
    """Move the unused slot worktree `d` aside as a spare, still registered with git, for a later slot."""
    with REGISTER:
        target = S.SLOTS_DIR / f'.spare-{d.name}-{int(time.time())}'
        return S.git('worktree', 'move', str(d), str(target)).returncode == 0


def build(d: Path, branch: str) -> None:
    """Make `d` a worktree on `branch` (detached): a spare moved in when there is one, else a new one whose
    checkout runs outside the registration lock."""
    what = f'worktree {d.name}'
    t0 = time.monotonic()
    with REGISTER:
        S.SLOTS_DIR.mkdir(parents=True, exist_ok=True)
        S.git('worktree', 'prune')
        for s in spares():
            if S.git('worktree', 'move', str(s), str(d)).returncode == 0:
                break
        else:
            s = None
            S.git('worktree', 'add', '-q', '--no-checkout', '--detach', str(d), branch)
    if s is not None:
        S.git('checkout', '-q', '--detach', branch, cwd=d)
        timed(what, f'reusing the spare {s.name}', t0, always=True)
        return
    t1 = time.monotonic()
    S.git('checkout', '-q', '-f', cwd=d)
    timed(what, 'the checkout', t1)
    timed(what, 'building it', t0, always=True)


def prepare(ns: list[int], branch: str, worktree) -> list[threading.Thread]:
    """Build the missing slot worktrees of `ns` at once, in the background, instead of one per slot start."""
    out = []
    for n in ns:
        if not (S.SLOTS_DIR / f's{n}').exists():
            t = threading.Thread(target=_prepare_one, args=(n, branch, worktree), daemon=True)
            t.start()
            out.append(t)
    return out


def _prepare_one(n: int, branch: str, worktree) -> None:
    try:
        worktree(n, branch)
    except Exception as e:  # the slot's own start builds it again and reports
        S.log(f'slot {n}: preparing its worktree failed: {e}')


def is_slot(name: str) -> bool:
    return bool(re.fullmatch(r's\d+', name))
