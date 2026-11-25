"""F162: what a Needs you card and its popup say: what is wanted, where, the steps, what the person should see, and the
pictures.

They come from the optional file <notes>/asks/ID.json, {summary, where, steps: [...], expect: [...], shots: [{file,
caption}], inputs: [...], options: [...], text, session, project}, each field standing in for what the ask's own words give. Those are split by rule (`split_ask`), with no AI
and nothing lost: the pieces joined are the ask. A missing, broken or oversized file is never an error.
"""
from __future__ import annotations

import json
import os
import platform
import re
import shlex
import sys
from pathlib import Path

from agent_runner import plan as P
from agent_runner import state as S

SAID = {'CONFIRM': 'Check this', 'DECIDE': 'Choose', 'CONCEPT': 'Choose', 'PITCH': 'Choose', 'BLOCKED': 'Do this',
        'TOOL': 'Do this', 'PR': 'Review this', P.STUCK: 'Stuck'}  # what is wanted, in everyday words
FILE_MAX = 64 * 1024        # an asks file larger than this is not read
LINK_MAX, CMD_MAX, MATCH_MAX, INPUTS_MAX = 1000, 2000, 200, 12  # F175
KINDS = {'text': 500, 'link': LINK_MAX, 'secret': 4096}  # an input's kinds, and the most characters of each
INPUT_LABELS = ('CONFIRM', 'DECIDE', 'BLOCKED', P.STUCK)  # the items inputs can answer
OPTIONS_MAX, OPTION_LEN = 12, 80  # F181c: a DECIDE's options (ui_model.ANSWER_MAX), and the most characters of one
SHOT_MAX = 50 * 1024 * 1024
SHOTS_MAX = 20
SHOT_DIRS = ('uploads', 'asks')  # under the notes dir, the only folders pictures are shown from
SHOT_TYPES = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.gif': 'image/gif',
              '.webp': 'image/webp'}
VIDEO_TYPES = {'.mp4': 'video/mp4', '.webm': 'video/webm'}  # F445a: what an ask file's shots may be too
HEAD = 64  # bytes `shot_type` reads

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
    """A piece as a list's line ('' for a 'Stuck:' alone, before numbered steps): without its number, its 'then' and the mark that ended it."""
    s = ' '.join(piece.split())
    s = re.sub(r'^stuck:(?:\s+|$)|^- ', '', s, flags=re.I)
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
    """The picture or video `src` ('uploads/a.png', 'asks/B160/1.mp4') names, under the notes dir; None unless it is
    one really under <notes>/uploads or <notes>/asks (no way out by .. or a symlink)."""
    src = str(src or '').replace('\\', '/')
    top, _, rest = src.partition('/')
    if top not in SHOT_DIRS or not rest or '\0' in src:
        return None
    try:
        base = Path(os.path.realpath(S.C.notes(top, 'x').parent))
        f = Path(os.path.realpath(base / rest))
        types = VIDEO_TYPES if f.suffix.lower() in VIDEO_TYPES else SHOT_TYPES
        if not f.is_relative_to(base) or not f.is_file() or Path(rest).suffix.lower() not in types or \
                f.suffix.lower() not in types or f.stat().st_size > SHOT_MAX:
            return None
        with f.open('rb') as h:
            return f if shot_type(h.read(HEAD)) in types.values() else None
    except (OSError, ValueError, AttributeError):
        return None


def shot_type(head: bytes) -> str:
    """The type of the picture or video whose first HEAD bytes are `head`; '' for anything else."""
    if head[4:8] == b'ftyp':
        return 'video/mp4'
    if head.startswith(b'\x1aE\xdf\xa3') and b'webm' in head[:HEAD]:
        return 'video/webm'
    return image_type(head)


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
    whole path; None when it cannot be shown. A video's has `video`."""
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
            return {'src': src, 'path': str(f), 'caption': caption,
                    **({'video': True} if f.suffix.lower() in VIDEO_TYPES else {})}
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


RECOMMENDED = re.compile(r'\s*\(recommended\)$', re.I)
BRACKET = re.compile(r'(\S.*?)\s+\[([^\[\]]+)\]\s*\.?$', re.S)


def _options(v) -> list[dict]:
    """F181c: the options `v`, each {name, rec}, as a DECIDE's buttons: bare names, the recommended one first. [] when
    one is malformed: fewer than two or too many, a name that is empty, too long or there twice, two recommended."""
    out: list[dict] = []
    for x in v if isinstance(v, list) else []:
        if not isinstance(x, dict) or not isinstance(x.get('name'), str) or not isinstance(x.get('rec', False), bool):
            return []
        said = ' '.join(x['name'].split())
        name = RECOMMENDED.sub('', said)
        if not re.search(r'[^\W_]', name) or name.startswith('-') or len(name) > OPTION_LEN or not name.isprintable() or \
                name.casefold() in {o['name'].casefold() for o in out}:
            return []
        out.append({'name': name, 'rec': x.get('rec', False) or name != said})
    if not 2 <= len(out) <= OPTIONS_MAX or sum(o['rec'] for o in out) > 1:
        return []
    return sorted(out, key=lambda o: not o['rec'])


def decide_options(tid: str, what: str, text: str = '') -> tuple[list[dict], str]:
    """F181c: a DECIDE's options, and its question `what` (its first link already off) without them: the ask file's
    `options`, else the bracket that ends the question, 'Which look? [Full (recommended) / Small / No change]'. Never
    from its prose; a malformed bracket, or one after a link (`text`, its task's
    text, has the order), stays in the question. An item with inputs has none: Done is its answer."""
    d = asks_file(tid)
    if d.get('inputs'):
        return [], what
    more = re.search(r'(?:\s+https?://\S+)*\s*$', what)  # a second link
    m = BRACKET.fullmatch(what[:more.start()].strip())
    said = ' '.join(text.rsplit('DECIDE: ', 1)[-1].split())
    if m and text and 'http' in said.split(f'[{" ".join(m[2].split())}]')[0]:  # a link before it, or inside it
        m = None
    found = _options([{'name': n} for n in re.split(r'\s+/\s+', f' {m[2]} ')]) if m else []
    return d.get('options') or found, m[1] + more[0].rstrip() if m and found else what


def asks_file(tid: str) -> dict:
    """<notes>/asks/ID.json as {summary, where, steps, step_more, expect, inputs, options, shots, text, session,
    project}, only what is well formed; {}
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
    out: dict = {k: ' '.join(d[k].split()) for k in ('summary', 'where', 'session', 'project') if isinstance(d.get(k), str)}
    if isinstance(d.get('text'), str):  # B809b: its lines are kept
        out['text'] = ''.join(x for x in d['text'].strip() if x in '\n\t' or x.isprintable() or x == '\u200d')
    steps, more = _steps(d.get('steps'))
    out.update(steps=steps, step_more=more, expect=_strings(d.get('expect')), inputs=_inputs(d.get('inputs')),
               options=_options(d.get('options')))
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


ASKS = re.compile(r'(?!\().*\?[*`"\'”’)]*', re.S)  # how a question's sentence ends


def _sentences(ask: str) -> list[list[tuple[str, str]]]:
    """B223a: `ask`'s pieces (`split_ask`, as a question) by sentence, without the reply hint (always a note)."""
    out: list[list[tuple[str, str]]] = []
    going = False
    for kind, text in split_ask(ask, False):
        if kind == 'note' and HINT.match(text):
            out.append([(kind, text)])
            going = False
            continue
        m = re.fullmatch(r'([^?]*(?:\?.*)?\?)(\s+[^\s?][^?]*)', text, re.S)  # words that go on in lower case, a link or a list
        cut = m and m[1].count('(') <= m[1].count(')') and not m[1].count('`') % 2 and not m[1].count('"') % 2
        for part in [m[1], m[2]] if cut else [text]:
            if going:
                out[-1].append((kind, part))
            else:
                out.append([(kind, part)])
            going = not re.search(r'[.?!][*`"\'”’)\]]*\s*$|\n\s*\n\s*$', part)
    return out


def _said(sentence: list[tuple[str, str]]) -> str:
    s = re.sub(r'[\s,;:]+$', '', ' '.join(''.join(t for _, t in sentence).split()))
    return s if is_link(s.split(' ')[0]) else s[:1].upper() + s[1:]


def _asked(sentences: list[list[tuple[str, str]]]) -> int:
    """Which of `sentences` is the question: the last that ends in a question mark; -1 for none."""
    return next((i for i in range(len(sentences) - 1, -1, -1) if ASKS.fullmatch(_said(sentences[i]))), -1)


def question_of(ask: str) -> str:
    """B223a: the question in a DECIDE's words, the sentence that ends in a question mark; '' for none."""
    ss = _sentences(ask)
    return _said(ss[at]) if (at := _asked(ss)) >= 0 else ''


def decide_words(ask: str, summary: str) -> tuple[str, list[str], list[str]]:
    """B223a: a DECIDE's (question, background as paragraphs, notes). Without a question mark the question is
    `summary`, else the first sentence, whole (B793b); what it says is not in the background."""
    ss = _sentences(ask)
    at = _asked(ss)
    if at >= 0:
        question = _said(ss[at])
    else:
        first = _said(next((s for s in ss if s[0][0] != 'note'), ss[0] if ss else [('do', ask)]))
        question = summary or first
        at = next((i for i, s in enumerate(ss) if _said(s).rstrip('.') == question.rstrip('.')), -1)
    paras, notes = [''], []
    for i, s in enumerate(ss):
        if i == at:
            paras.append('')
            continue
        for kind, text in s:
            if kind == 'note':
                notes.append(shown(text))
            else:
                paras[-1] += text
                if re.search(r'\n\s*\n\s*$', text):
                    paras.append('')
    return question, [p for x in paras if (p := _said([('do', x)]))], [n for n in notes if n]


# B794: a BLOCKED's own words. A statement is why it stopped, an order is a step, and what a run does next is neither.
BACK = re.compile(r'\s+— back for you: [^—]*?(?:landed|passed)(?=\s+—|\s+- |[;.]|\s*$)')
ORDER = re.compile(r"(?:please\s+|just\s+|also\s+|you\s+(?:need to|should|can|must)\s+)?(?:add|allow|answer|approve|ask|attach|be|bring|"
                   r'build|buy|change|charge|check|choose|clear|click|close|come|confirm|connect|copy|create|crop|delete|do|download|drop|'
                   r'enable|disable|ensure|enter|fill|find|finish|fix|free|get|give|go|grant|hold|install|keep|let|link|log|login|look|'
                   r'make|merge|move|open|paste|pay|pick|plan|plug|post|press|publish|pull|push|put|re-?run|read|rebuild|release|reload|'
                   r'remove|rename|renew|repeat|reply|reset|restart|restore|retry|review|revoke|rotate|run|save|say|scan|see|select|'
                   r'send|set|share|shut|sign|start|stop|swipe|switch|take|tap|tell|test|top|trust|try|turn|type|uninstall|unlock|'
                   r'update|upgrade|upload|use|verify|visit|wait|wake|watch|wire|write)\b', re.I)
STATES = (r"(?:is|are|was|were|has|had|does|did|isn't|aren't|wasn't|doesn't|didn't|cannot|can't|could not|couldn't|may not|"
          r'failed|fails|needs|gets?|gives|got|holds|left|lacks|returned|returns|said|says|shows?|ran|found|ended|hangs|hung|refused|'
          r'refuses|denied|expired|timed out|times out|offline|missing|not found|not \w+ed|full(?=\s*(?:[;:.,(]|$))|still|only \w+s)\b')
STATE = re.compile(r'(?!(?:if|when|once|after|before)\b)(?:(?!\b(?:that|which|who|what|when|if|where|whether|once|until|while|so|because|'
                   r'after|before|as|it|you|they)\b)[^,;:])*?[^\s,;:]\s+' + STATES, re.I)
ABOUT = re.compile(r"(?:the|it|its|they|each|both|nothing|no|none|there|an?|your|this|that|these|those|every|some|we|I|needs?|"
                   r"today's)\b(?!\s+(?:needs? (?:you|your)\s+to)\b)", re.I)
THING = re.compile(r"(?:release|run|test|build|update|upgrade|install|sign|login|plan|push|merge)\s+(?:[A-Z0-9`][\w.`-]*\s+)?(?:is|are|was|"
                   r'were|has|had|failed|fails|cannot|could not)\b', re.I)  # "upgrade failed", no order
WENT_WRONG = re.compile(r"\b(?:fail(?:s|ed)?|not|no|none|nothing|cannot|can't|timed out|offline|missing|expired|refused|denied|errors?|still)\b", re.I)
_GO = r're-?runs?|reopens?|resumes?|restarts?|retries|retry|continues?|goes on|go on|carries on|carry on|follows?|picks? (?:this|it) up'
_DO = _GO + r'|can|will|does|do|runs?|checks?|opens?|finish(?:es)?|takes?|tests?|builds?|publish(?:es)?|merges?|starts?|installs?'
_AGENT = r'(?:I|(?i:the agent|an agent)|[A-Z]{1,2}\d+[a-z0-9]*)'
_IT = r'(?i:this|it|the (?:task|run|slot|check))(?: task| run)?'
_AFTER = r'(?:(?i:and|so|then|after that|afterwards),?\s+)'
NEXT = re.compile(rf"{_AFTER}*(?:(?i:after|once|when)\s[^,;:]*,\s+)?(?:{_IT}(?: then| will| can)* (?:{_GO})\b|"
                  rf"{_AGENT}(?: then| also| will| can)* (?:{_DO})\b(?! not\b)|{_AGENT} then\s|"
                  r'(?i:re-?(?:opens?|runs?))(?: (?:this|it|the task|[A-Z]{1,2}\d+[a-z0-9]*))? (?:when|after|once|as soon as)\b)')
NEXT_WHO = re.compile(rf'(?:^|[,;.]\s+|\band\s+)(?:{_IT}|{_AGENT})(?: will| can)?\s+$')  # 'the run will', before its 'then'
NEXT_THEN = re.compile(rf'(?:and\s+)?then,?\s+(?:this|the|{_AGENT})\s', re.I)
NEXT_AT = re.compile(rf'(,?\s+)({_AFTER})?')
ERROR = re.compile(r'\b(?:fail(?:s|ed)?|errors?|says|said|gets|got|ended)(?: \S+)?:\s*$', re.I)  # its colon is followed by the error


def _outside(text: str, at: int) -> bool:
    """Whether `at` in `text` is in no bracket and no `code`."""
    head = text[:at]
    return not head.count('`') % 2 and head.count('(') <= head.count(')') and head.count('[') <= head.count(']')


def _blocked_kind(text: str, kind: str) -> str:
    """What a BLOCKED's piece `text` is: 'next' (what the run does after), 'why' or 'do'; else `kind`, the plain one."""
    s = re.sub(r'^(?:\(\d+\)|\d+[.)])\s+|^—\s+', '', ' '.join(text.split()))
    if NEXT_THEN.match(s) or NEXT.match(s):
        return 'next'
    if kind in ('note', 'lead'):
        return kind
    s = re.sub(r'^(?:(?:and|or|then|so|but)\b,?\s+|stuck:\s+)+', '', s, flags=re.I)
    if PREP.match(s) and ',' in s:  # "when you are there, reply"
        s = re.sub(r'^[^,]*,\s+', '', s)
    if ORDER.match(s) and not THING.match(s):
        return 'do'
    if kind == 'see' or ABOUT.match(s) or STATE.match(s):
        return 'why'
    return kind


def blocked_pieces(ask: str) -> list[tuple[str, str]]:
    """B794: a BLOCKED's `ask` in pieces (`split_ask`'s), with 'why' (the reason it stopped), 'next' (what the run or an
    agent does afterwards) and 'back' (what it waited for has landed) too. A 'see' is only what follows a step and its
    colon. The pieces joined are `ask`."""
    if m := BACK.search(ask):
        return blocked_pieces(ask[:m.start()]) + [('back', m[0])] + blocked_pieces(ask[m.end():])
    parts: list[tuple[str, str]] = []
    whole: list[tuple[str, str]] = []
    for kind, text in split_ask(ask):
        if whole and NEXT_WHO.search(whole[-1][1]) and THEN.match(text):  # 'the agent then checks' is one
            whole[-1] = (whole[-1][0], whole[-1][1] + text)
        else:
            whole.append((kind, text))
    for kind, text in whole:  # cut again before a reason after a dash or that starts in lower case, and before what the run does
        at = [0]
        if _blocked_kind(text, kind) not in ('note', 'next'):
            for c in re.finditer(r'\s+(?=— )|(?<=[^\s.]\.)\s+(?=[a-z])', text):
                if _outside(text, c.start()) and _blocked_kind(text[c.end():], '') in ('why', 'next'):
                    at.append(c.end())
            for c in NEXT_AT.finditer(text):
                if c.start() and (c[1][0] == ',' or c[2]) and _outside(text, c.start()) and NEXT.match(text[c.end(1):]):
                    at.append(c.end(1))
        at = sorted(set(at))
        parts += [(kind, text[a:b]) for a, b in zip(at, [*at[1:], len(text)])]
    out: list[tuple[str, str]] = []
    for kind, text in parts:
        was, before = out[-1] if out else ('', '')
        ended = not before or bool(re.search(r'[.?!;]["\'”’)]*\s*$', before))
        colon = before.rstrip().endswith(':')
        new = _blocked_kind(text, kind)
        if was == 'why' and ERROR.search(before):
            new = 'why'
        elif colon and was in ('why', 'next') and new not in ('do', 'note'):
            new = was
        elif kind == 'see' and new == 'why' and (colon and was == 'do' or was == 'see' and not re.search(r'[.?!]\s*$', before)):
            new = 'why' if WENT_WRONG.search(text) else 'see'
        elif was == 'next' and not ended and new not in ('do', 'note'):
            new = 'next'
        elif not out and new == 'why' and PREP.match(text) and text.rstrip().endswith(':'):  # "on the phone, the app is open:"
            new = 'lead'
        if new == 'next' and was == 'next' and not ended or new == 'do' and was == 'do' and colon and PREP.match(before.strip()):
            out[-1] = (new, before + text)  # "then the check runs: pair, install", "after the restart: run the test"
        else:
            out.append((new, text))
    return out


def blocked_words(ask: str) -> dict[str, list[str]]:
    """B794: what a BLOCKED's `ask` says: {why, lead, steps, expect, notes}, each piece in one of them."""
    out: dict[str, list[str]] = {k: [] for k in ('why', 'lead', 'steps', 'expect', 'notes')}
    pieces: list[tuple[str, str]] = []
    for kind, text in blocked_pieces(ask):
        if kind == 'why' and pieces and pieces[-1][0] == 'why':  # one paragraph
            text = pieces.pop()[1] + text
        pieces.append((kind, text))
    for kind, text in pieces:
        s = re.sub(r'^—\s+', '', shown(text))
        if not re.search(r'\w', s):
            continue
        if kind == 'back':
            s = re.sub(r'^.*?back for you: ', '', s, flags=re.I)
            s = re.sub(r'\s(landed|passed)$', lambda m: f' {"have" if ", " in s else "has"} {m[1]}', s)
        elif kind == 'next':
            s = re.sub(rf'^{_AFTER}+', '', s)
            s = re.sub(r'^(re-?(?:open|run))s?\s', lambda m: f'it {m[1].lower()}s ', s, flags=re.I)  # no order to the person
            s = 'After that: ' + (s if re.match(r'I\b', s) else P._lower_first(s))
        s = s[:1].upper() + s[1:]
        out[{'do': 'steps', 'see': 'expect', 'why': 'why', 'lead': 'lead'}.get(kind, 'notes')].append(s)
    return out


def detail(label: str, tid: str, ask: str, title: str, text: str) -> dict:
    """What the card and the popup of one item say: said, title, where, summary, lead, steps, expect, notes and shots;
    B794: `why`, the reason a BLOCKED without its ask file's steps stopped ([] for the others);
    B223a: `question`, what a DECIDE asks ('' for the others), which is its summary too; it has steps only from its ask file.
    F175: `step_more` (each step's link, cmd and on) and `inputs` (what the person gives, `ui_model.need_give`). `text` is its task's text. B809b: 'text', the message that explains a control session's
    question, and that session's name and project ('' for the others). B793b: the title and the summary are whole; a view with one line shortens them itself."""
    d = asks_file(tid)
    pieces = split_ask(ask, label in ('CONFIRM', 'BLOCKED'))
    of = lambda kind: [s for k, p in pieces if k == kind and (s := shown(p))]  # noqa: E731
    old = old_script_steps(tid) if label == 'BLOCKED' and not d.get('steps') else ([], [])
    if old[0]:
        d = {**d, 'steps': old[0], 'step_more': old[1]}
    steps, expect = d.get('steps') or of('do'), d.get('expect') or ([] if d.get('steps') else of('see'))
    summary, lead = d.get('summary') or (steps or expect or [ask])[0], [] if d.get('steps') else of('lead')
    notes, question = of('note'), ''
    if label == 'DECIDE':
        question, lead, notes = decide_words(ask, d.get('summary') or '')
        summary, steps = question, d.get('steps') or []
        lead = [] if steps else lead
    why: list[str] = []
    if label == 'BLOCKED' and not d.get('steps'):
        w = blocked_words(ask)
        why, lead, steps, expect, notes = w['why'], w['lead'], w['steps'], d.get('expect') or w['expect'], w['notes']
        summary = d.get('summary') or (steps or why or expect or [ask])[0]
    shots = d.get('shots') or []
    shots = shots + [s for s in named_shots(text) if s['path'] not in {x['path'] for x in shots}]
    return {'said': SAID.get(label, label), 'title': P.short_title(title, sys.maxsize) if title else tid,
            'where': d.get('where') or place(ask), 'summary': summary, 'question': question,
            'why': why, 'lead': lead, 'steps': steps, 'expect': expect, 'notes': notes,
            'text': d.get('text') or '', 'session': d.get('session') or '', 'project': d.get('project') or '',
            'shots': shots, 'step_more': d.get('step_more') or [],
            'inputs': (d.get('inputs') or []) if label in INPUT_LABELS else []}
