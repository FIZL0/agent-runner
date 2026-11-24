"""F162: what a Needs you card and its popup say: what is wanted, where, the steps, what the person should see, and the
pictures.

They come from the optional file <notes>/asks/ID.json, {summary, where, steps: [...], expect: [...], shots: [{file,
caption}]}, each field standing in for what the ask's own words give. Those are split by rule (`split_ask`), with no AI
and nothing lost: the pieces joined are the ask. A missing, broken or oversized file is never an error.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from agent_runner import plan as P
from agent_runner import state as S

SAID = {'CONFIRM': 'Check this', 'DECIDE': 'Choose', 'CONCEPT': 'Choose', 'PITCH': 'Choose', 'BLOCKED': 'Do this',
        'TOOL': 'Do this', P.STUCK: 'Stuck'}  # what is wanted, in everyday words
FILE_MAX = 64 * 1024        # an asks file larger than this is not read
SHOT_MAX = 50 * 1024 * 1024
SHOTS_MAX = 20
SHOT_DIRS = ('uploads', 'asks')  # under the notes dir, the only folders pictures are shown from
SHOT_TYPES = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.gif': 'image/gif',
              '.webp': 'image/webp'}

PREP = re.compile(r'(?:and |then )?(?:on|in|at|after|before|once|with|when|while|for|from|using|if)\b', re.I)
SEE = re.compile(r'(?:the|it|its|they|each|all of|both|nothing|no|there|taps|you should|you see)\b', re.I)
NOTE = re.compile(r'(?:then the|findings|notes are|evidence|details are)\b|[^:;]*\b(?:was|were|is|are) already\b', re.I)
HINT = re.compile(r'\s+- (?:reply\b|this clears\b)')
THEN = re.compile(r'(?:and\s+)?then,?\s', re.I)
PLACE = re.compile(r'\b(?:on|in|with|using)\s+(?:\w+\s+){0,2}?(iPhone(?: \d+(?: Pro)?(?: Max)?)?|iPad|Android|phone|Mac|'
                   r'Windows|Linux|Safari|Chrome|Firefox|Edge|terminal)\b', re.I)
NAMED = re.compile(r'(?:^|[\s(\'"`/])uploads/([\w.@+-]+\.(?:png|jpe?g|gif|webp))(?![\w/])', re.I)


def _numbers(ask: str) -> list[int]:
    """Where the numbered steps of `ask` start: 1) 2) 3), (1) (2) or 1. 2., in order; [] for fewer than two."""
    out, n, at = [], 1, 0
    while m := re.compile(rf'(?<!\S)(?:\({n}\)|{n}[.)])(?=\s)').search(ask, at):
        out.append(m.start())
        n, at = n + 1, m.end()
    return out if len(out) > 1 else []


def _lead(head: str) -> bool:
    """Whether `head`, the words before a colon, only say where and when ("On an iPhone, after this lands")."""
    parts = [x.strip() for x in head.split(',') if x.strip()]
    return bool(parts) and all(PREP.match(x) for x in parts)


def split_ask(ask: str, sees: bool = True) -> list[tuple[str, str]]:
    """`ask` in pieces, (kind, words): 'lead' (where and when), 'do' (a step), 'see' (what to see) and 'note' (the
    rest, such as how to reply). Split at sentences, numbered steps, ';' and 'then', and at a colon into do and see;
    never inside brackets or `code`. The pieces joined are `ask`. `sees` False: no piece is a 'see' (a question)."""
    numbers = _numbers(ask)
    hint = HINT.search(ask)
    end = hint.start() if hint else len(ask)
    pieces: list[tuple[str, str]] = []
    at, kind, depth, code, i = 0, '', 0, False, 0

    def kind_of(text: str, why: str, was: str) -> str:
        s = re.sub(r'^(?:\(\d+\)|\d+[.)])\s+', '', text.strip())
        if NOTE.match(s):
            return 'note'
        if why == 'colon':
            return 'see'
        if not sees or why == 'then' or THEN.match(s):
            return 'do'
        return 'see' if SEE.match(s) or (why == 'semi' and was == 'see') else 'do'

    cuts: list[tuple[int, str]] = [(0, 'start')]
    while i < end:
        c = ask[i]
        if c == '`':
            code = not code
        if not code:
            if i in numbers and i > cuts[-1][0]:
                depth = 0
                cuts.append((i, 'number'))
            if c in '([':
                depth += 1
            elif c in ')]':
                depth = max(0, depth - 1)
            elif not depth:
                nxt = re.compile(r'\s+').match(ask, i + 1)
                rest = ask[nxt.end():end] if nxt else ''
                if c == '\n' and nxt is not None and ask[i + 1] == '\n' and rest:  # a paragraph; one newline is a wrap
                    cuts.append((nxt.end(), 'sentence'))
                elif nxt and rest:
                    if c in '.?!' and re.match(r'[A-Z0-9(`"\'\[]', rest) and \
                            not re.search(r'(?:\be\.g|\bi\.e|\bvs|(?:^|\s)\d{1,2})\.$', ask[:i + 1]):
                        cuts.append((nxt.end(), 'sentence'))
                    elif c == ';':
                        cuts.append((nxt.end(), 'semi'))
                    elif c == ':':
                        cuts.append((nxt.end(), 'colon'))
                if c.isspace() and (t := THEN.match(ask, i + 1)) and t.end() <= end:
                    here = ask[cuts[-1][0]:i]
                    if here.strip() and not re.search(r'\b(?:until|since|by|if|when|once|and)\W*$|\b(?:if|when|unless)\b',
                                                      here, re.I):
                        cuts.append((i + 1, 'then'))
        i += 1
    for j, (pos, why) in enumerate(cuts):
        text = ask[pos:cuts[j + 1][0] if j + 1 < len(cuts) else end]
        if not pieces:
            kind = kind_of(text, why, '')
        elif why == 'colon':
            head = pieces[-1][1]
            if pos in numbers and not (len(pieces) == 1 and _lead(head.strip(' :\n'))):  # steps follow
                kind = kind_of(text, 'start', '')
            elif kind == 'do' and len(pieces) == 1 and _lead(head.strip(' :\n')):
                pieces[-1] = ('lead', head)
                kind = kind_of(text, 'start', '')
            elif sees and kind == 'do' and text[:1] not in '`"\'/~' and not re.match(r'\S+/\S', text) and \
                    not re.match(r'stuck:', head, re.I):
                kind = kind_of(text, 'colon', kind)
            else:  # a colon that only goes on: the same piece
                pieces[-1] = (kind, head + text)
                continue
        else:
            kind = kind_of(text, why, kind)
        pieces.append((kind, text))
    if end < len(ask):
        pieces.append(('note', ask[end:]))
    return [p for p in pieces if p[1]]


def shown(piece: str) -> str:
    """A piece as a list's line: without its number, its 'then' and the mark that ended it."""
    s = ' '.join(piece.split())
    s = re.sub(r'^stuck:\s+|^- ', '', s, flags=re.I)
    s = re.sub(r'^(?:\(\d+\)|\d+[.)])\s+', '', s)
    s = re.sub(r'^(?:and\s+)?then,?\s+(?=\S)', '', s, flags=re.I)
    s = re.sub(r'(?:,?\s+and|[\s,;:]+)$', '', s)
    return s[:1].upper() + s[1:]


def place(ask: str) -> str:
    """The device or place the ask's start names ('iPhone, Safari'); '' for none."""
    out: list[str] = []
    for m in PLACE.finditer(ask[:160]):
        w = m[1]
        if not any(w.lower() in x.lower() or x.lower() in w.lower() for x in out):
            out.append(w)
    return ', '.join(out[:2])


def shot_file(src: str) -> Path | None:
    """The picture `src` ('uploads/a.png', 'asks/B160/1.png') names, under the notes dir; None unless it is an image
    really under <notes>/uploads or <notes>/asks (no way out by .. or a symlink)."""
    src = str(src or '').replace('\\', '/')
    top, _, rest = src.partition('/')
    if top not in SHOT_DIRS or not rest or '\0' in src:
        return None
    try:
        base = Path(os.path.realpath(S.C.notes(top, 'x').parent))
        f = Path(os.path.realpath(base / rest))
        if not f.is_relative_to(base) or not f.is_file() or Path(rest).suffix.lower() not in SHOT_TYPES or \
                f.suffix.lower() not in SHOT_TYPES or f.stat().st_size > SHOT_MAX:
            return None
        with f.open('rb') as h:
            return f if image_type(h.read(16)) else None
    except (OSError, ValueError, AttributeError):
        return None


def image_type(head: bytes) -> str:
    """The type of the image whose first 16 bytes are `head`; '' for anything else."""
    if head.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if head.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if head[:6] in (b'GIF87a', b'GIF89a'):
        return 'image/gif'
    return 'image/webp' if head[:4] == b'RIFF' and head[8:12] == b'WEBP' else ''


def _shot(file: str, caption: str) -> dict | None:
    """A picture's row from the file a task or an asks file names: relative to <notes>/asks, 'uploads/…', or the
    whole path; None when it cannot be shown."""
    file = file.replace('\\', '/')
    tries = [file] if file.split('/')[0] in SHOT_DIRS else [f'asks/{file}']
    if Path(file).is_absolute():
        try:
            notes = Path(os.path.realpath(S.C.notes('uploads', 'x').parent.parent))
            tries = [Path(os.path.realpath(file)).relative_to(notes).as_posix()]
        except (OSError, ValueError, AttributeError):
            return None
    for src in tries:
        if f := shot_file(src):
            return {'src': src, 'path': str(f), 'caption': caption}
    return None


def _strings(v) -> list[str]:
    return [' '.join(x.split()) for x in v if isinstance(x, str) and x.strip()] if isinstance(v, list) else []


def asks_file(tid: str) -> dict:
    """<notes>/asks/ID.json as {summary, where, steps, expect, shots}, only what is well formed; {} without one."""
    if not re.fullmatch(r'[\w.-]+', tid or ''):
        return {}
    try:
        f = S.C.notes('uploads', 'x').parent.parent / 'asks' / f'{tid}.json'
        if not f.is_file() or f.stat().st_size > FILE_MAX:
            return {}
        d = json.loads(f.read_text(encoding='utf-8'))
    except (OSError, ValueError, AttributeError, RecursionError):
        return {}
    if not isinstance(d, dict):
        return {}
    out: dict = {k: ' '.join(d[k].split()) for k in ('summary', 'where') if isinstance(d.get(k), str)}
    out.update(steps=_strings(d.get('steps')), expect=_strings(d.get('expect')))
    shots = d.get('shots') if isinstance(d.get('shots'), list) else []
    out['shots'] = [r for s in shots[:SHOTS_MAX] if isinstance(s, dict) and isinstance(s.get('file'), str) and
                    (r := _shot(s['file'], s['caption'] if isinstance(s.get('caption'), str) else ''))]
    return out


def task_lines() -> dict[str, str]:
    """{id: its whole text in TODO.md}, read once for a list of items; {} when it cannot be read."""
    try:
        ls = P.lines(S.C.todo)
        return {tid: '\n'.join(P._item_block(ls, i)) for _, _, tid, _, i in P.iter_tasks(ls)}
    except (OSError, SystemExit, AttributeError):
        return {}


def named_shots(text: str) -> list[dict]:
    """The pictures under <notes>/uploads that a task's text names."""
    return [r for n in dict.fromkeys(NAMED.findall(text)) if (r := _shot(f'uploads/{n}', 'Picture named in the task'))
            ][:SHOTS_MAX]


def detail(label: str, tid: str, ask: str, title: str, text: str, short) -> dict:
    """What the card and the popup of one item say: said, title, where, summary, lead, steps, expect, notes and shots.
    `text` is its task's text, `short` ui_model's ask_short."""
    d = asks_file(tid)
    pieces = split_ask(ask, label in ('CONFIRM', 'BLOCKED'))
    of = lambda kind: [s for k, p in pieces if k == kind and (s := shown(p))]  # noqa: E731
    steps, expect = d.get('steps') or of('do'), d.get('expect') or ([] if d.get('steps') else of('see'))
    shots = d.get('shots') or []
    shots = shots + [s for s in named_shots(text) if s['path'] not in {x['path'] for x in shots}]
    return {'said': SAID.get(label, label), 'title': P.short_title(title) if title else tid,
            'where': d.get('where') or place(ask), 'summary': d.get('summary') or short((steps or expect or [ask])[0]),
            'lead': [] if d.get('steps') else of('lead'), 'steps': steps, 'expect': expect, 'notes': of('note'),
            'shots': shots}
