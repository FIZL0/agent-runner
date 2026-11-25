"""B775: a task's session has its brief: in its first message, or, for a long one, in its system prompt."""
from __future__ import annotations

import json
import os
from pathlib import Path

from agent_runner import plat, state as S

MARKER = 'agent-runner task brief'  # the heading of a long brief in the system prompt
SEEN: set[str] = set()  # the sessions whose brief is settled: it arrived, or the session was ended
TAIL = 200              # characters of the brief's end that must be there too: a cut one has not arrived


def with_brief(flags: list[str], brief: Path) -> list[str]:
    """`flags` with the long brief as the system prompt: the flags are made before the brief is written, so they
    name only one that a session already had (a resume)."""
    flag = '--append-system-prompt-file'
    return flags if flag in flags else [*flags, flag, str(brief)]


def _flat(text: str) -> str:
    return ' '.join(text.split())


def _text(content) -> str:
    if isinstance(content, str):
        return content
    return ' '.join(b.get('text') or '' for b in content or [] if isinstance(b, dict))


def _system(d: dict) -> str:
    """The system prompt a transcript entry keeps; '' for any other entry."""
    if d.get('type') == 'attachment' and isinstance(a := d.get('attachment'), dict) and a.get('type') == 'prompt_snapshot':
        s = a.get('systemPrompt')
        return s if isinstance(s, str) else ' '.join(x for x in s or [] if isinstance(x, str))
    if d.get('type') == 'api-request-shape' and isinstance(d.get('shape'), dict):
        return _text(d['shape'].get('system'))
    return ''


def missing(transcript: str, prompt: str) -> str | None:
    """Why `prompt`, the brief of the session that started `transcript`, did not arrive; '' when it did, or when
    the transcript cannot tell; None while it does not say yet."""
    from agent_runner.slots import LONG_BRIEF
    want = _flat(prompt)
    tail, pointer = want[-TAIL:], _flat(LONG_BRIEF.format(marker=MARKER))
    pointed = False
    try:
        with open(transcript, encoding='utf-8', errors='replace') as f:
            for line in f:
                try:
                    d = json.loads(line)
                except ValueError:
                    return None  # the line being written
                if not isinstance(d, dict) or d.get('isSidechain'):
                    continue
                if pointed and (system := _flat(_system(d))):
                    if MARKER in system and tail in system:
                        return ''
                    return 'its system prompt does not have the whole brief' if MARKER in system else \
                        'its first message points at the system prompt, which has no brief'
                if d.get('type') == 'user' and not d.get('isMeta') and not pointed:
                    said = _flat(_text((d.get('message') or {}).get('content')))
                    if said == pointer and said != want:
                        pointed = True
                    elif tail in said and len(said) >= len(want):
                        return ''
                    else:
                        return f'its first message has {len(said)} of the brief\'s {len(want)} characters'
                elif d.get('type') == 'assistant':
                    return ''  # it answered, and the transcript keeps no system prompt: no telling
    except OSError:
        pass
    return None


def check(procs: dict, running: dict) -> None:
    """End each running task's session whose brief did not arrive, and say so in the run log. A resumed
    session is not looked at: its first message is the old one, and its flags name the long brief it was started
    with (`Claude.flags`). One that ended before this look is only said."""
    from agent_runner.slots import transcript
    for n, (pid, sid, _) in [(n, p) for n, p in procs.items() if n in running and p[1] not in SEEN]:
        if not (t := transcript(sid)):
            continue
        try:
            argv = json.loads(S.C.notes(f'slot{n}.job').read_text(encoding='utf-8'))['argv']
            prompt = S.C.notes(f'slot{n}.prompt').read_text(encoding='utf-8')
        except (OSError, ValueError, KeyError):
            continue
        if '--session-id' not in argv or sid not in argv:
            SEEN.add(sid)
            continue
        if (why := missing(os.fspath(t), prompt)) is None:
            continue
        SEEN.add(sid)
        if not why:
            continue
        tid = running[n][0]
        if up := plat.alive(pid):
            plat.terminate(pid)
        S.log(f'slot {n}: {tid}\'s brief did not arrive ({why}); ' +
              ('its session is ended' if up else 'its session had ended already'), None, tid)
