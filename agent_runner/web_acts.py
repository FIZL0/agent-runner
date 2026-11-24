"""C45: the run page's web.py, ActsOnce (an action sent twice runs once) and Talk's words.

Part of `web`: `web` runs this file in its own namespace (see its PARTS), so these names are `web`'s, and a test that sets
`web.X` reaches the code here. Not imported on its own."""

WEB_REFUSED = {'keys'}  # C24: actions the web does not take (typing into a pane went with the built-in view)


class ActsOnce:
    """F137: the page's outbox sends each action with a client id (`cid`) and sends it again after a drop or a
    reload, so an action whose id the server has run already answers with its first result instead of running
    twice (a `new_control` sent twice would start two chats). A copy that comes while the first still runs waits
    for it (None, a 503, when it waited WAIT s in vain). The last KEEP finished ids are kept, and B161: in `kept`
    (<notes>/acts-once.jsonl) too, so a run page that restarted still knows them."""
    KEEP = 500
    WAIT = 300.0  # s a copy waits for the first to finish

    def __init__(self, kept: Path | None = None):
        self.lock = threading.Lock()
        self.seen: dict[str, list] = {}  # cid -> [done Event, result]
        self.kept, self.lines = kept, 0  # the file, and how many lines it has
        try:
            text = kept.read_text(encoding='utf-8') if kept else ''
        except (OSError, ValueError):
            text = ''
        rows = text.splitlines()
        for row in rows:
            try:
                cid, result = json.loads(row)
                if isinstance(cid, str) and isinstance(result, dict):
                    self.seen[cid] = [threading.Event(), result]
                    self.seen[cid][0].set()
            except (ValueError, TypeError):  # a line cut off
                pass
        self.lines = len(rows) if not text or text.endswith('\n') else 2 * self.KEEP  # cut off: written anew first

    def keep(self, cid: str, result: dict) -> None:
        if not self.kept:
            return
        try:
            with self.lock:
                if self.lines >= 2 * self.KEEP:
                    done = [json.dumps([k, v[1]]) + '\n' for k, v in self.seen.items() if v[0].is_set() and v[1]]
                    part = self.kept.with_suffix('.part')
                    part.write_text(''.join(done[-self.KEEP:]), encoding='utf-8')
                    os.chmod(part, 0o600)
                    part.replace(self.kept)
                    self.lines = min(len(done), self.KEEP)
                with open(os.open(self.kept, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600), 'a', encoding='utf-8') as f:
                    f.write(json.dumps([cid, result]) + '\n')
                self.lines += 1
        except (OSError, TypeError, ValueError):  # it is only not kept over a restart
            pass

    def run(self, cid: str, fn) -> dict | None:
        if not cid:
            return fn()
        with self.lock:
            got = self.seen.get(cid)
            first = got is None
            if first:
                got = self.seen[cid] = [threading.Event(), None]
                done = [k for k, v in self.seen.items() if v[0].is_set()]  # the oldest finished ones go
                for k in done[:max(0, len(self.seen) - self.KEEP)]:
                    self.seen.pop(k)
        if not first:
            if not got[0].wait(self.WAIT):
                return None  # still running: the page sends this copy again later (503)
            if got[1] is None:  # the first did not finish: this copy runs it
                return self.run(cid, fn)
            return {**got[1], 'again': True}
        try:
            got[1] = fn()
            if got[1].get('hold'):  # B158: nothing was done yet: the outbox's next try runs it
                with self.lock:
                    self.seen.pop(cid, None)
            else:
                self.keep(cid, got[1])
        except BaseException:
            with self.lock:  # it did not finish: a later copy runs it
                self.seen.pop(cid, None)
            raise
        finally:
            got[0].set()
        return got[1]

CONTROL_N = re.compile(r'\bcontrol (\d+)\b')  # F93: the number `control --new` prints for the session it opened


def talk(text: str, to: str = '') -> dict:
    """F93: the Talk view's words (heard or typed) to its control session: to `to` (cN, its live Talk session)
    with the spoken-reply reminder (`talk_message`), else a new control session titled Talk whose first message
    says how to answer (`talk_ask`). The result's 'session' is where they went ('' when it cannot tell)."""
    from agent_runner.control import talk_ask, talk_message
    text = str(text or '').strip()
    if not text:
        return {'ok': False, 'code': 2, 'out': 'talk: nothing was said', 'argv': [], 'session': ''}
    if re.fullmatch(r'c\d+', to or ''):
        r = U.chat_to(talk_message(text), to)
        if r.get('ok'):
            return {**r, 'session': to}
    r = U.new_control(talk_ask(text))
    m = CONTROL_N.search(r.get('out') or '')
    return {**r, 'session': f'c{m[1]}' if r.get('ok') and m else ''}


U.ACTIONS['talk'] = talk  # F93: the run page's Talk view


