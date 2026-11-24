"""F162: what a Needs you card and its popup say: what is wanted, where, the steps, what the person should see, and the
pictures.

They come from the optional file <notes>/asks/ID.json, {summary, where, steps: [...], expect: [...], shots: [{file,
caption}], inputs: [...]}, each field standing in for what the ask's own words give. Those are split by rule (`split_ask`), with no AI
and nothing lost: the pieces joined are the ask. A missing, broken or oversized file is never an error.
"""
from __future__ import annotations

import json
import os
import platform
import re
import shlex
from pathlib import Path

from agent_runner import plan as P
from agent_runner import state as S

SAID = {'CONFIRM': 'Check this', 'DECIDE': 'Choose', 'CONCEPT': 'Choose', 'PITCH': 'Choose', 'BLOCKED': 'Do this',
        'TOOL': 'Do this', P.STUCK: 'Stuck'}  # what is wanted, in everyday words
FILE_MAX = 64 * 1024        # an asks file larger than this is not read
LINK_MAX, CMD_MAX, MATCH_MAX, INPUTS_MAX = 1000, 2000, 200, 12  # F175
KINDS = {'text': 500, 'link': LINK_MAX, 'secret': 4096}  # an input's kinds, and the most characters of each
INPUT_LABELS = ('CONFIRM', 'DECIDE', 'BLOCKED', P.STUCK)  # the items inputs can answer
SHOT_MAX = 50 * 1024 * 1024
SHOTS_MAX = 20
SHOT_DIRS = ('uploads', 'asks')  # under the notes dir, the only folders pictures are shown from
SHOT_TYPES = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.gif': 'image/gif',
              '.webp': 'image/webp'}

PREP = re.compile(r'(?:and |then )?(?:on|in|at|after|before|once|with|when|while|for|from|using|if)\b', re.I)
SEE = re.compile(r'(?:the|it|its|they|each|all of|both|nothing|no|there|taps|you should|you see)\b', re.I)
STILL = re.compile(r'(?:an?|your|this|that|these|those|every|some)\b|[\w-]+ (?:is|are|has|have|does|do|stays?|shows?|opens?|'
                   r'closes?|returns?|goes|moves?|appears?|neither|never|still|also|no longer)\b', re.I)  # goes on saying what to see
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
        if why == 'semi' and was == 'see':  # classed again: a step ("tap Undo") or more to see ("and the list returns")
            s = re.sub(r'^(?:and|but)\s+', '', s, flags=re.I)
            if PREP.match(s):  # "on Home, the list returns"
                s = re.sub(r'^[^,]*,\s+', '', s)
            return 'see' if SEE.match(s) or STILL.match(s) else 'do'
        return 'see' if SEE.match(s) else 'do'

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


def is_link(v) -> bool:
    """Whether `v` is a web link a page may open: http or https, one word, no control characters."""
    return isinstance(v, str) and len(v) <= LINK_MAX and v.isprintable() and \
        bool(re.fullmatch(r'https?://[^\s/]\S*', v, re.I))


def _steps(v) -> tuple[list[str], list[dict]]:
    """F175: an asks file's steps, each words or {text, link, cmd, on}: (their words, one {link, cmd, on} each);
    the second is [] when no step has a link or a command. `on`, the machine a command is for, is this one when the
    file names none."""
    words, more = [], []
    for s in v if isinstance(v, list) else []:
        s = {'text': s} if isinstance(s, str) else s
        if not isinstance(s, dict):
            continue
        text = ' '.join(s['text'].split()) if isinstance(s.get('text'), str) else ''
        x = {}
        if is_link(s.get('link')):
            x['link'] = s['link']
        cmd = s['cmd'].strip() if isinstance(s.get('cmd'), str) else ''
        if cmd and len(cmd) <= CMD_MAX and cmd.replace('\n', '').isprintable():
            on = s.get('on')
            x.update(cmd=cmd, on=' '.join(on.split()) if isinstance(on, str) and on.strip() else platform.node())
        text = text or ('Run this' if 'cmd' in x else 'Open this' if x else '')
        if text:
            words.append(text)
            more.append(x)
    return words, more if any(more) else []


def _inputs(v) -> list[dict]:
    """F175: what an asks file wants the person to give, [{key, label, kind, hint, match, confirm, env}]; [] when one
    is malformed, as the rest alone would be half an answer (the item keeps its plain answers). `env` is a secret's name
    in <notes>/asks/ID.env ('' for the others)."""
    out: list[dict] = []
    if not isinstance(v, list) or len(v) > INPUTS_MAX:
        return []
    for x in v:
        if not isinstance(x, dict) or not isinstance(x.get('key'), str) or not re.fullmatch(r'[A-Za-z][\w-]{0,39}', x['key'], re.A):
            return []
        if not all(isinstance(x.get(k, ''), str) for k in ('label', 'hint', 'confirm')):
            return []  # a question that does not read must not go unasked
        say = {k: ' '.join(x.get(k, '').split())[:300] for k in ('label', 'hint', 'confirm')}
        # an env with no kind may be a secret, so it is not taken as text
        kind, match, env = x.get('kind', '' if x.get('env') else 'text'), x.get('match', ''), ''
        if not isinstance(kind, str) or kind not in KINDS:
            return []
        if kind == 'secret':
            env = x.get('env') or x['key'].replace('-', '_').upper()
            if not isinstance(env, str) or not re.fullmatch(r'[A-Za-z_]\w{0,79}', env, re.A):
                return []
        try:
            if not isinstance(match, str) or len(match) > MATCH_MAX:
                raise ValueError('match')
            re.compile(match)
        except (re.error, ValueError, OverflowError, RecursionError):
            return []  # its check cannot be made, so no value may pass it
        if x['key'] in {o['key'] for o in out} or env and env in {o['env'] for o in out}:
            return []
        out.append({'key': x['key'], **say, 'label': say['label'] or x['key'], 'kind': kind, 'match': match, 'env': env})
    return out


def input_wrong(x: dict, value) -> str:
    """F175: why `value` is not taken for the input `x` ('' when it is); never says the value itself."""
    if not isinstance(value, str) or not value:
        return f'{x["label"]}: nothing is entered'
    if len(value) > KINDS[x['kind']]:
        return f'{x["label"]}: at most {KINDS[x["kind"]]} characters'
    if not value.isprintable():
        return f'{x["label"]}: one line, with no control characters'
    if x['kind'] == 'link' and not is_link(value):
        return f'{x["label"]}: {x["hint"] or "a link that starts with https://"}'
    if x['match'] and not re.fullmatch(x['match'], value):
        return f'{x["label"]}: {x["hint"] or "this is not what is asked for"}'
    return ''


def asks_file(tid: str) -> dict:
    """<notes>/asks/ID.json as {summary, where, steps, step_more, expect, inputs, shots}, only what is well formed; {}
    without one."""
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
    steps, more = _steps(d.get('steps'))
    out.update(steps=steps, step_more=more, expect=_strings(d.get('expect')), inputs=_inputs(d.get('inputs')))
    shots = d.get('shots') if isinstance(d.get('shots'), list) else []
    out['shots'] = [r for s in shots[:SHOTS_MAX] if isinstance(s, dict) and isinstance(s.get('file'), str) and
                    (r := _shot(s['file'], s['caption'] if isinstance(s.get('caption'), str) else ''))]
    return out


def old_script_steps(tid: str) -> tuple[list[str], list[dict]]:
    """C37a: the steps of an old <notes>/wizards/ID.sh (C37 removed the command that ran it), read as text and never
    run: each `stage`, `say` and `step` line is a step, each address on it (or after `open_url`) its link. Only this
    reader says 'wizard'. ([], []) without a readable script."""
    if not re.fullmatch(r'[\w.-]+', tid or ''):
        return [], []
    try:
        f = S.C.notes('wizards', f'{tid}.sh')
        if not f.is_file() or f.stat().st_size > FILE_MAX:
            return [], []
        lines = f.read_text(encoding='utf-8').splitlines()
    except (OSError, ValueError, AttributeError):
        return [], []
    start = next((i for i, x in enumerate(lines) if re.match(r'#\s*STAGES\b', x.lstrip())), -1)
    steps = []
    for x in lines[start + 1:]:
        m = re.match(r'\s*(stage|say|step|open_url)\s+(.*)$', x)
        if not m:
            continue
        try:
            arg = shlex.split(m[2], comments=False)
        except ValueError:
            continue
        text = ' '.join(arg[0].split()) if arg else ''
        link = next((u for u in re.findall(r'https?://[^\s"\'<>)]+', text if m[1] != 'open_url' else m[2]) if is_link(u)), None)
        if m[1] == 'open_url':
            steps.append({'text': 'Open this', 'link': link} if link else None)
        elif text:
            steps.append({'text': text, **({'link': link} if link else {})})
    return _steps([x for x in steps if x])


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
    """What the card and the popup of one item say: said, title, where, summary, lead, steps, expect, notes and shots;
    F175: `step_more` (each step's link, cmd and on) and `inputs` (what the person gives, `ui_model.need_give`). `text` is its task's text, `short` ui_model's ask_short."""
    d = asks_file(tid)
    pieces = split_ask(ask, label in ('CONFIRM', 'BLOCKED'))
    of = lambda kind: [s for k, p in pieces if k == kind and (s := shown(p))]  # noqa: E731
    old = old_script_steps(tid) if label == 'BLOCKED' and not d.get('steps') else ([], [])
    if old[0]:
        d = {**d, 'steps': old[0], 'step_more': old[1]}
    steps, expect = d.get('steps') or of('do'), d.get('expect') or ([] if d.get('steps') else of('see'))
    shots = d.get('shots') or []
    shots = shots + [s for s in named_shots(text) if s['path'] not in {x['path'] for x in shots}]
    return {'said': SAID.get(label, label), 'title': P.short_title(title) if title else tid,
            'where': d.get('where') or place(ask), 'summary': d.get('summary') or short((steps or expect or [ask])[0]),
            'lead': [] if d.get('steps') else of('lead'), 'steps': steps, 'expect': expect, 'notes': of('note'),
            'shots': shots, 'step_more': d.get('step_more') or [],
            'inputs': (d.get('inputs') or []) if label in INPUT_LABELS else []}
