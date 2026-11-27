"""C56: concept details: the options page of a concept item, read for its options and framed on its card.

Part of `ui_model`: `ui_model` runs this file in its own namespace (see its end). Not imported on its own."""

class _Copy(HTMLParser):
    """A K copy's page as blocks: (level, text), level 1-4 for a heading (an element of class t, ttl or title
    counts as a level 3 one), 0 for a paragraph; scripts and styles left out."""
    HEADS = {'h1': 1, 'h2': 2, 'h3': 3, 'h4': 4}
    BLOCKS = {'p', 'li', 'div', 'section', 'pre', 'td', 'th', 'blockquote', 'tr', 'br', 'ul', 'ol', 'table',
              'article', 'header', 'footer', 'main'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks: list[tuple[int, str]] = []
        self.buf: list[str] = []
        self.stack: list[tuple[str, int]] = []  # open elements that make a heading
        self.skip = 0

    def flush(self):
        text = ' '.join(''.join(self.buf).split())
        self.buf = []
        if text:
            self.blocks.append((self.stack[-1][1] if self.stack else 0, text))

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'title', 'head'):
            self.skip += 1
            return
        cls = set((dict(attrs).get('class') or '').split())
        level = self.HEADS.get(tag) or (3 if cls & {'t', 'ttl', 'title'} else 0)
        if level or tag in self.BLOCKS:
            self.flush()
        if level:
            self.stack.append((tag, level))

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'title', 'head'):
            self.skip = max(0, self.skip - 1)
            return
        if tag in self.HEADS or tag in self.BLOCKS:
            self.flush()
        if self.stack and self.stack[-1][0] == tag:
            self.stack.pop()

    def handle_data(self, data):
        if not self.skip:
            self.buf.append(data)


def concept_page(html: str) -> dict:
    """F76 (C33: here, the one place the terminal UI and the run page both read): a concept's K copy as {'title',
    'intro': [paragraphs], 'options': [{'name', 'body': [...], 'rec'}]}: the options are its headings one level
    below the title's (the first heading), each with what follows it; 'rec' marks the one whose heading says it
    is recommended."""
    p = _Copy()
    try:
        p.feed(html or '')
        p.close()
    except Exception:  # noqa: BLE001 - a broken page shows what parsed
        pass
    p.flush()
    blocks = p.blocks
    heads = [i for i, (lv, _) in enumerate(blocks) if lv]
    title, start = '', 0
    if heads and blocks[heads[0]][0] == min(blocks[i][0] for i in heads):
        title, start = blocks[heads[0]][1], heads[0] + 1
    rest = blocks[start:]
    levels = sorted({lv for lv, _ in rest if lv})
    opt_level = levels[0] if levels else 0
    intro, options = [], []
    for lv, text in rest:
        if opt_level and lv == opt_level:
            options.append({'name': text, 'body': [], 'rec': 'recommend' in text.lower()})
        elif options:
            options[-1]['body'].append(text)
        else:
            intro.append(text)
    return {'title': title, 'intro': intro, 'options': options}


_OPTIONS: dict[str, tuple[float, list]] = {}  # a concept copy's path: (its mtime, its options)


def concept_options(path: str) -> list[dict]:
    """F79: a concept's options, from its local page copy (`concept_page`): [{'name', 'rec'}]; [] for no copy."""
    if not path:
        return []
    try:
        mt = os.path.getmtime(path)
        if (hit := _OPTIONS.get(path)) and hit[0] == mt:
            return hit[1]
        opts = [{'name': o['name'], 'rec': o['rec']}
                for o in concept_page(Path(path).read_text(encoding='utf-8', errors='replace'))['options']]
    except OSError:
        return []
    _OPTIONS[path] = (mt, opts)
    return opts


def concept_frame(row: dict) -> str:
    """F463: the run page's own copy of a concept item's options page ('concept/<K id>', served by web.py), for
    its Needs you card to show framed; '' for no concept, or a concept with no local copy."""
    if row.get('label') != 'CONCEPT':
        return ''
    k = row.get('concept') or row.get('id') or ''
    return f'concept/{k}' if k and (row.get('copy') or concept_copy(k)) else ''



def concept_opened(concept: str = '', version: str = '') -> dict:
    """F197a: concept `concept`'s details popup was opened showing `version` (its row's): New and Updated clear for
    every device, up to that version (`concept_news.opened`)."""
    if not S.C or not CONCEPT_ID.fullmatch(concept or '') or not isinstance(version, str) or len(version) > 80:
        return {'ok': False, 'code': 2, 'out': f'concept_opened: a concept and its version; not {concept!r}', 'argv': []}
    from agent_runner import concept_news
    concept_news.opened(S.C, concept, version)
    return {'ok': True, 'code': 0, 'out': '', 'argv': []}


ACTIONS['concept_opened'] = concept_opened
