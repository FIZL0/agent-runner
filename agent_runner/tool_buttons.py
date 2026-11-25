"""F428c: a shared tool's own buttons: any number, each a label and a command that runs once and ends.

A runner.toml tool has them as [[run.tools.<name>.buttons]], a device in devices.json, set by a person on the Tools
page. `press` (POST /tools, op `press`) runs one by its tool and label alone: the command is read here, at that moment,
never from the request. One button of a tool runs at a time, and none while a task has the tool, unless the request
says that same holder was confirmed.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess as sp
import tempfile
import time
from pathlib import Path

from agent_runner import devices, plat
from agent_runner.devices import Refused

FIELDS = ('label', 'cmd', 'confirm')
MOST = {'label': 60, 'cmd': 1000, 'confirm': 300}  # characters
TIMEOUT = 30.0      # s a command may run: with the check before it, within the 60 s Runner Home waits for an answer
OUT_MAX = 1 << 24   # bytes it may print before it is stopped


def checked(v) -> list[dict]:
    """`v` as a tool's buttons, [{label, cmd, confirm}], confirm only when set. A refusal never holds what was typed."""
    if not isinstance(v, list):
        raise Refused('buttons is a list, each with a label and a cmd')
    out: list[dict] = []
    for i, b in enumerate(v, 1):
        if not isinstance(b, dict) or any(k not in FIELDS for k in b):
            raise Refused(f'button {i} has a label, a cmd and an optional confirm, and nothing else')
        if any(not isinstance(x, str) for x in b.values()):
            raise Refused(f'button {i}: label, cmd and confirm are text')
        got = {k: b[k].strip(' ') for k in FIELDS if b.get(k, '').strip(' ')}
        for k in ('label', 'cmd'):
            if k not in got:
                raise Refused(f'button {i} needs a {k}')
        for k, s in got.items():
            if len(s) > MOST[k] or re.search(r'[\x00-\x1f\x7f]', s):
                raise Refused(f'button {i}: {k} is one line, {MOST[k]} characters at most')
        if got['label'].casefold() in {x['label'].casefold() for x in out}:
            raise Refused(f'button {i} has the label of another one')
        out.append(got)
    return out


def of_tool(t: dict) -> list[dict]:
    """The buttons of a [run.tools.<name>] table as the file has it; none when it is not a good one."""
    from agent_runner.config import tools_problem
    return [] if tools_problem({'x': t}) else checked(t.get('buttons', []))


def in_toml(c) -> dict[str, list[dict]]:
    """{name: its buttons} of the shared tools in the main checkout's runner.toml that have some."""
    return {n: bs for n, t in devices._toml_tools(c).items() if (bs := of_tool(t))}


# --- who has the tool ------------------------------------------------------------------------------------------------

def _key(*who: str) -> str:
    """A holder as the request sends it back: one holder, one key."""
    return hashlib.sha256('\0'.join(who).encode()).hexdigest()[:16]


def holder(name: str, dev: dict | None, c, check: str = '') -> tuple[str, str] | None:
    """(who has the tool now, in words; the key of that holder), None when nobody. `dev`: the device, None for a
    runner.toml tool, whose `check` is run. A missing or unknown tool is nobody's: a button may be what mends it."""
    from agent_runner import plan as P, shared_tools
    own = devices.project(c)
    if dev is None or name not in (c.run.get('tools') or {}):  # a runner.toml tool hides a device of its name from tasks
        task = (shared_tools.used(P.lines(c.todo), {'running': devices._running(own)}).get(name) or ('',))[0]
    else:
        task = ''
    if dev is not None:
        if not dev.get('exclusive'):
            return None
        if h := devices.holder(name, own) or (own, task):
            return (h[1] if h[0] == own else f'a task of {Path(h[0]).name}', _key(*h)) if h[1] else None
    state, who = shared_tools.run_check(check, c)
    if state == shared_tools.BUSY and not (task and shared_tools.names_task(who, task)):
        return who or 'someone', _key('', who)
    return (task, _key(own, task)) if task else None


# --- a press ---------------------------------------------------------------------------------------------------------

def _run(cmd: str, cwd: str) -> tuple[int | None, str, bytes]:
    """Run a command to its end: (exit, '' or why it was stopped, the end of its output)."""
    from agent_runner import device_page
    kw = {'creationflags': plat.CREATE_NO_WINDOW | plat.CREATE_NEW_PROCESS_GROUP, 'shell': True} if plat.WINDOWS \
        else {'start_new_session': True}
    with tempfile.TemporaryFile() as out:  # a file: something it leaves behind would hold a pipe open
        try:
            p = sp.Popen(cmd if plat.WINDOWS else ['/bin/sh', '-c', cmd], cwd=cwd, stdin=sp.DEVNULL, stdout=out,
                         stderr=out, env=device_page._env(), **kw)
        except OSError as e:
            raise Refused(f'the command does not start ({e.strerror or type(e).__name__})') from None
        end, why = time.monotonic() + TIMEOUT, ''
        while not why:
            try:
                p.wait(0.1)
                break
            except sp.TimeoutExpired:
                if time.monotonic() > end:
                    why = f'it ran past {TIMEOUT:g} s'
                elif os.fstat(out.fileno()).st_size > OUT_MAX:
                    why = 'it printed too much'
        if why:
            device_page._end(p.pid, lambda: p.poll() is None or device_page._group(p.pid))
            try:
                p.wait(2)
            except sp.TimeoutExpired:
                pass
        size = os.fstat(out.fileno()).st_size
        out.seek(max(0, size - device_page.LOG_KEEP))
        data = out.read(device_page.LOG_KEEP)
        if size > device_page.LOG_KEEP:
            data = data.partition(b'\n')[2]  # whole lines, or half a secret would not be hidden
        return None if why else p.returncode, why, data


def press(a: dict, c) -> dict:
    """POST /tools, op `press`: {name, button: its label, source, confirm: the question that was answered, holder: the
    key of the holder that was confirmed}. The answer: {ok, out, exit, lines}; {ok: False, ask} when the button has a
    question that `confirm` is not; {ok: False, busy: {holder, key}} when someone else has the tool."""
    name, source, t, dev = a.get('name'), devices._source(a), None, None
    known = devices.load()['devices']
    if not isinstance(name, str):
        raise Refused('there is no such tool')
    if source != 'device' and (source == devices.TOML or name not in known):
        if not (t := devices._toml_tools(c).get(name)):
            raise Refused('there is no such tool')
        buttons, cwd, lock = of_tool(t), devices.project(c), 'toml-' + _key(devices.project(c), name)
    else:
        dev = devices._get({'devices': known}, name)
        buttons, lock = dev.get('buttons') or [], f'dev-{name}'
        cwd = str(Path(dev.get('folder') or '~').expanduser())
    b = next((b for b in buttons if b['label'] == a.get('button')), None)
    if not b:
        raise Refused(f'{name} has no such button')
    if b.get('confirm') and a.get('confirm') != b['confirm']:
        return {'ok': False, 'out': b['confirm'], 'ask': b['confirm']}
    held = plat.lock(devices._folder('press') / lock)
    if not held:
        raise Refused(f'a button of {name} is still running')
    with held:
        h = holder(name, dev, c, (t or {}).get('check', ''))
        if h and a.get('holder') != h[1]:
            return {'ok': False, 'out': f'{name} is held by {h[0]}', 'busy': {'holder': h[0], 'key': h[1]}}
        rc, why, data = _run(b['cmd'], cwd)
    return {'ok': rc == 0, 'exit': rc, 'lines': devices.hidden_lines(data),
            'out': f'{b["label"]}: ' + (f'stopped, {why}' if why else 'done' if rc == 0 else f'failed (exit {rc})')}
