"""F444c: the Review page's own buttons in the run app, beside a pitch's Approve and Not this: Ask about it (a
question about one change, its answer shown on the page) and Ask for a better way (the change is undone and its task
reopened with what the person wants instead). They are the web's own actions (`WEB_ACTIONS`), each through the
`pitch ask` and `pitch better` commands, so the answer is kept on the Review page too."""
from __future__ import annotations

import re

TASK = re.compile(r'[A-Z]+\d+[a-z0-9]*')


def _bad(name: str, out: str) -> dict:
    return {'ok': False, 'code': 2, 'out': f'{name}: {out}', 'argv': []}


def _ids(pid: str, tid: str) -> str:
    from agent_runner import pitch
    if not pitch.PITCH_ID.fullmatch(str(pid or '')):
        return f'no pitch {pid!r}'
    if not TASK.fullmatch(str(tid or '')):
        return f'no change {tid!r}'
    return ''


def pitch_ask(pid: str = '', tid: str = '', q: str = '', call=None) -> dict:
    """Ask about change `tid` of pitch `pid`: `pitch ask`; 'answer' is what came back, shown under the change."""
    q = ' '.join(str(q or '').split())
    if why := _ids(pid, tid) or ('' if q else 'type your question first'):
        return _bad('pitch_ask', why)
    r = (call or _call)(['pitch', 'ask', pid, tid, q])
    if r.get('ok'):
        r.update(answer=str(r.get('out') or '').strip(), pid=pid, tid=tid, q=q)
    return r


def pitch_better(pid: str = '', tid: str = '', why: str = '', confirm: bool = False, call=None) -> dict:
    """Ask for a better way to change `tid` of pitch `pid`: `pitch better --why`, after a confirm (it undoes it)."""
    why = ' '.join(str(why or '').split())
    if bad := _ids(pid, tid) or ('' if why else 'say what you want instead first'):
        return _bad('pitch_better', bad)
    ask = f'Undo {tid} here and reopen its task with what you want instead?'
    if confirm is not True:
        return {'ok': False, 'code': 3, 'out': ask, 'confirm': ask, 'argv': []}
    r = (call or _call)(['pitch', 'better', pid, tid, f'--why={why}'])
    if r.get('ok'):
        r['said'] = f'{tid}: the run undoes it and reopens it for a better way'
    return r


def _call(argv: list[str]) -> dict:
    from agent_runner import ui_model as U
    return U.call(argv)


WEB_ACTIONS = {'pitch_ask': pitch_ask, 'pitch_better': pitch_better}


def _join() -> None:
    from agent_runner import ui_model as U
    U.ACTIONS.update(WEB_ACTIONS)


_join()
