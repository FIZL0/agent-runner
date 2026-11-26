"""C44: the actions: plan add and change, drop, chat, answer, need_give, move.

Part of `ui_model`: `ui_model` runs this file in its own namespace (see its end), so these names are `ui_model`'s, and a
test that sets `ui_model.X` reaches the code here. Not imported on its own."""

# --- the actions ----------------------------------------------------------------------------------------------

def _run(argv: list[str]) -> tuple[int, str]:
    """Run the runner with `argv` in the main checkout: (exit code, what it printed)."""
    env = {k: v for k, v in os.environ.items() if k != 'AGENT_RUNNER_CONTROL'}  # F160: the person's, not the session's
    if argv[:1] and argv[0] in ('plan', 'pitch', 'sheet'):  # that started the run or the TUI
        env['AGENT_RUNNER_BY'] = 'the person in the run app'
    env['AGENT_RUNNER_ACT_OF'] = str(os.getpid())  # B827: `stop --force` asked by the run's own page
    r = sp.run(runner_cmd() + argv, cwd=S.ROOT, env=env, stdin=sp.DEVNULL, capture_output=True, text=True, encoding='utf-8',
               errors='replace')  # F402c2: no stdin, so nothing asks on (or reads keys from) the TUI's terminal
    return r.returncode, (r.stdout + r.stderr).strip()


RUN = [_run]  # what every action runs; a test or a wrapping UI swaps it


SLOW_S = 1.0  # F479: an action slower than this is logged with its time


def slow_log(what: str, argv, secs: float) -> None:
    """F479: write to the run log how long a run page `what` (its `argv`) took, when over SLOW_S."""
    if secs > SLOW_S:
        S.log(f'slow run page {what}: {" ".join(map(str, argv))} took {secs:.1f} s')


def call(argv: list[str]) -> dict:
    """One action's result: {'ok', 'code', 'out', 'argv'}."""
    t0 = time.monotonic()
    code, out = RUN[0](argv)
    slow_log('action', argv, time.monotonic() - t0)
    return {'ok': code == 0, 'code': code, 'out': out, 'argv': argv}


def _flags(files=None, after=None, pri: str = '', test: str = '', needs=None) -> list[str]:
    out = []
    if files:
        out += ['--files', ','.join(files) if isinstance(files, (list, tuple)) else files]
    if after:
        out += ['--after', ','.join(after) if isinstance(after, (list, tuple)) else after]
    if test:
        out += ['--test', test]
    if needs:
        out += ['--needs', ','.join(needs) if isinstance(needs, (list, tuple)) else needs]
    if pri:
        out += ['--pri', pri]
    return out


def plan_add(kind: str, text: str, files=None, after=None, pri: str = '', test: str = '', needs=None) -> dict:
    """Queue a task: `plan add KIND TEXT --files … --after … --pri …`."""
    r = call(['plan', 'add', kind, text, *_flags(files, after, pri, test, needs)])
    return said_waits(r) if r['ok'] else r


def said_waits(r: dict) -> dict:
    """F402c1: the result `r` of a `plan add`, which says (as `said` too) that its task waits for the run while none
    is up and nothing else keeps it."""
    try:
        m = re.search(r'^added (\w+)', r['out'], re.M)
        row = m and not S.run_up() and queue_row(m[1])
        if row and wait_for_run([row])[0].get('waits_run'):
            r['said'] = f'{m[0]}: {row["tool_wait"]}'
            r['out'] = r['out'].replace(m[0], r['said'], 1)
    except (Exception, SystemExit):  # noqa: BLE001 - the task is added all the same
        pass
    return r


def plan_change(tid: str, text: str = '', files=None, after=None, pri: str = '', test: str = '', needs=None) -> dict:
    """The page's direct edit of a queued task: `plan edit ID [TEXT] [--files …]`, rewritten in place (a slot
    running it is told)."""
    return call(['plan', 'edit', tid, *([text] if text else []), *_flags(files, after, pri, test, needs)])


def drop(tid: str, why: str) -> dict:
    """`plan drop ID WHY`: not wanted; a slot running it is stopped."""
    return call(['plan', 'drop', tid, why])


def to_new(text: str) -> dict:
    """F176: a prompt opens a chat of its own: a new control session with `text` as its first message, started
    without waiting for its link (`control --new --no-wait --ask`)."""
    return name_new(call(['control', '--new', '--no-wait', '--ask', text, '--no-feed']), text)  # F196e


SEND = [to_new]  # how chat and answers start a chat; a test swaps it


def chat(text: str) -> dict:
    """The page's chat box: the person's words, as they typed them, to a new chat."""
    return SEND[0](text)


SHEET_GO = ('go', 'recommended')  # a pick sheet's reply for its recommended picks
CHECK_FAILED = 'No: the check failed'  # B138: what a CONFIRM's No reopens the task with


def need_label(tid: str) -> str:
    """B138: the label of what `tid` asks (CONFIRM, DECIDE, BLOCKED, STUCK, CONCEPT); '' when nothing needs you
    about it."""
    from agent_runner import pitch
    if pitch.PITCH_ID.fullmatch(tid or ''):  # F98
        return pitch.LABEL if any(r[1] == tid for r in pitch.rows()) else ''
    if (tid or '').startswith('tool-'):  # F168
        from agent_runner import shared_tools
        return shared_tools.LABEL if any(r[1] == tid for r in shared_tools.asks()) else ''
    if (tid or '').startswith('pr-'):  # F420
        from agent_runner import pr_rows
        return pr_rows.LABEL if any(r[1] == tid for r in pr_rows.asks()) else ''
    from agent_runner import ready
    if ready.task_of(tid):  # F445b
        return ready.LABEL if any(r[1] == tid for r in ready.asks(all=True)) else ''
    try:
        return P._ask(tid, S.C.todo)[0]
    except (SystemExit, OSError, AttributeError):
        return ''


def answer_argv(tid: str, text: str, button: bool = False, note: str = '') -> tuple[list[str], str]:
    """B138: the runner command that settles a Needs you reply at once, and what to say once it did; ([], '')
    when the reply is a chat's to read. A button's Yes (or a pick, or done) is `plan confirm ID "<reply>"`, a
    CONFIRM's No is `plan change ID "No: the check failed"`; a pick sheet's go or Send line is `sheet ID
    --go|--picks`; a concept's option button is `plan approve ID "<option>"` (B149). F181a: words typed as the
    reply to a DECIDE are its answer, so they run the same command as a button's; typed for any other label they
    are a new chat's. F162: `note`, the words beside a button's answer, go with it: in the task's note,
    or a pitch no's --why; `answer` sends an approved pitch's to a new chat."""
    said, label, note = (text or '').strip(), need_label(tid), ' '.join((note or '').split())
    noted = f': {note}' if note else ''
    why = [f'--why={note}'] if note else []  # one word of the command line, so words that start with - stay words
    noting = [f'--note={note}'] if note else []
    if label == 'PITCH' and button:  # F98
        if said.lower() == 'approve':
            return ['pitch', 'approve', tid], f'{tid} approved'
        if m := re.fullmatch(r'not (\w+): (reopen|drop)', said, re.I):
            one, how = m[1], m[2].lower()
            argv = ([] if how == 'reopen' else ['--drop', 'all']) if one.lower() == 'this' else [f'--{how}', one]
            return ['pitch', 'no', tid, *argv, *why], f'{tid}: the run undoes it'
        return [], ''
    if label == 'READY' and button:  # F445b
        if said.lower() == 'looks good':
            return ['plan', 'confirm', tid], f'{tid} closed: it looks good'
        if said.lower() == 'not now':
            return ['plan', 'shelve', tid], f'{tid} shelved'
        if said.lower() == 'change it' and note:
            return ['plan', 'change', tid, note], f'{tid}: a follow-up is filed with your words'
        return [], ''
    if label == 'DECIDE':
        from agent_runner.brief import has_sheet
        if has_sheet(tid) and said.lower() in SHEET_GO:
            return ['sheet', tid, '--go', *noting], f'{tid} answered with the recommended picks'
        if has_sheet(tid) and said.startswith(f'{tid} picks:'):
            return ['sheet', tid, '--picks', said, *noting], f'{tid} answered with your picks'
    if label == 'CONCEPT' and button and said:  # B149: a concept's option button approves that option itself
        return ['plan', 'approve', tid, said + noted], f'{tid} approved ({said}): a run starts its build'
    if not said or label not in ('CONFIRM', 'DECIDE', 'BLOCKED', P.STUCK) or not (button or label == 'DECIDE'):
        return [], ''
    if label == 'CONFIRM' and said.lower() == 'no':
        return ['plan', 'change', tid, f'No{noted}' if note else CHECK_FAILED], f'{tid} reopened: the check failed'
    if label == 'CONFIRM':
        return ['plan', 'confirm', tid, said + noted], f'{tid} ticked'
    return ['plan', 'confirm', tid, said + noted], f'{tid} answered ({said}): a run starts it'


def need_row(tid: str) -> dict:
    """F425a: the Needs you row of `tid` as the person sees it, read before its answer takes it off; {} for none."""
    try:
        return row_of('need', tid) or row_of('concept', tid) or {}
    except (Exception, SystemExit):  # noqa: BLE001 - it is only for the record
        return {}


def pitch_waits(pid: str) -> bool:
    """F425a: whether a change of pitch `pid` still waits for the person."""
    try:
        from agent_runner import pitch
        return bool(pitch.changes_of(pid, state='waiting'))
    except Exception:  # noqa: BLE001 - never fails the answer
        return False


def keep_response(tid: str, row: dict, said: str, note: str = '') -> str:
    """F425a: keep the sent response to the item `tid` (`row`: `need_row`, read before), which opened no chat: its id,
    '' when it could not be kept. Never fails the answer."""
    try:
        from agent_runner import sent_responses
        return sent_responses.keep(*response_of(tid, row), said, note)
    except (Exception, SystemExit):  # noqa: BLE001
        return ''


def response_of(tid: str, row: dict) -> tuple[str, str, str, str]:
    """F425a: the item `tid` (`row`: `need_row`) as a sent response has it: its id, title, question and whole ask."""
    ask = row.get('ask') or ''
    return (row.get('id') or tid, row.get('title') or P.titles(S.C.done, S.C.todo).get(tid, ''),
            (row.get('detail') or {}).get('summary') or ask, ask)


CLOSED = re.compile(r'^confirmed and ticked ', re.M)  # F452: what `plan.confirm` prints when the answer closed the task
NOTE_CHAT_WAIT = 3.0  # s the answer's result waits to hear whether the chat about its note started


def answer_chat(sent: dict) -> str:
    """F465: the name (cN) of the chat an answer's words started (`sent`: what SEND gave), '' when it cannot tell."""
    m = re.search(r'\bcontrol (\d+)\b', (sent or {}).get('out') or '') if (sent or {}).get('ok') else None
    return f'c{m[1]}' if m else ''


def note_chat(tid: str, row: dict, said: str, note: str, named: list | None = None) -> str:
    """F452: a new chat with the `note` of the answer `said`, which closed `tid` (`row`: `need_row`, read before), and
    what to say of it. Never fails the answer, nor holds it longer than NOTE_CHAT_WAIT: it starts in a thread. The
    sent response is kept first and goes once the chat starts, so a run that ends meanwhile loses no note."""
    rid, send, over = keep_response(tid, row, said, note), SEND[0], []  # over: why it did not start, '' when it did

    def go() -> None:
        why = 'it failed'
        try:
            from agent_runner import sent_responses
            sent = send(sent_responses.note_message(*response_of(tid, row), said, note))
            why = '' if sent['ok'] else ((sent.get('out') or '').splitlines() or [why])[0]
            if named is not None and (c := answer_chat(sent)):  # F465
                named.append(c)
        except (Exception, SystemExit) as e:  # noqa: BLE001
            why = str(e) or type(e).__name__
        try:
            if why:
                S.log(f'{tid}: closed; the chat with its note did not start ({why})')
            else:
                sent_responses.take(rid)
        finally:
            over.append(why)

    try:
        t = threading.Thread(target=go, daemon=True)
        t.start()
    except RuntimeError as e:  # no thread to be had
        over.append(str(e) or 'no thread')
        S.log(f'{tid}: closed; the chat with its note did not start ({over[0]})')
    else:
        t.join(NOTE_CHAT_WAIT)
    if not over:
        return 'A chat with your note is starting'
    return f'The chat with your note did not start ({over[0]}); find your answer under Quiet in Chats' if over[0] else \
        'Your note opened a chat'


def sheet_said(tid: str, said: str) -> str:
    """F425a: a pick sheet's reply (go, or its Send line) in words: each question and its answer."""
    try:
        from agent_runner import sheet
        spec = sheet.load(S.C.notes('sheets', f'{tid}.json'))
        return sheet.picks_note(spec, sheet.parse_picks(spec, said)).split(': ', 1)[1]
    except (Exception, SystemExit):  # noqa: BLE001 - a sheet that does not read: the reply as sent
        return said


def answer(tid: str, text: str, button: bool = False, note: str = '') -> dict:
    """A reply to a Needs you item. B138: a button's answer, and the words typed for a DECIDE (F181a), run the
    plan command itself (`answer_argv`), with no AI session, and an ok result carries 'said' (what was done, for
    the toast) and 'gone' (the item, off Needs you); the words typed for any other label go to a new chat to
    settle as its needs guide says. F425a: one that opened no chat is kept (`keep_response`). F452: one with
    a note that closed its task starts a chat with it (`note_chat`)."""
    argv, done = answer_argv(tid, text, button, note)
    if button and not argv and not need_label(tid):  # answered already, or never asked: say so, no AI session
        return {'ok': False, 'code': 1, 'out': f'{tid} no longer needs you (answered already?)', 'argv': []}
    if argv:
        row, to_chat = need_row(tid), False
        r = call(argv)
        if r['ok']:
            if argv[0] == 'pitch':
                done = r['out'].splitlines()[0] if r['out'] else done  # F98: pushed, or what it waits for
                words = ' '.join((note or '').split())
                if words and argv[1] == 'approve':  # F162a: its tasks are done, so the words go where a reply does
                    sent = SEND[0](f'{tid}: approved. {words}')
                    to_chat = sent['ok']
                    if c := answer_chat(sent):  # F465
                        r['chat'] = c
                    if not sent['ok']:
                        why = (sent['out'].splitlines() or [''])[0]
                        S.log(f'{tid}: approved; the words with it went to no chat ({why}): {words}')
                        done += f'. Your words were not sent ({why}): {words}'
            r.update(said=done, gone=tid)
            words = ' '.join((note or '').split())
            if words and argv[:2] == ['plan', 'confirm'] and CLOSED.search(r['out'] or ''):  # F452: no agent gets it
                named: list = []
                r['said'], to_chat = f'{done}. {note_chat(tid, row, (text or "").strip(), note.strip(), named)}', True
                if named:  # F465
                    r['chat'] = named[0]
            if not to_chat and not (argv[0] == 'pitch' and pitch_waits(tid)):  # a part of a pitch settles nothing yet
                said = (text or '').strip()
                keep_response(tid, row, sheet_said(tid, said) if argv[0] == 'sheet' else said, note)
        return r
    title = P.titles(S.C.todo).get(tid, '')
    sent = SEND[0](f'{tid}{f" ({title})" if title else ""}: {text}')
    if c := answer_chat(sent):  # F465: the page lists it under Quiet, new
        sent = {**sent, 'chat': c}
    return sent


def as_data(value: str) -> str:
    """F175: `value` as a JSON string that holds no plan markup: what could start a field, a note, a block or a tag on
    a task line is a \\u escape, which reads back as it was."""
    return re.sub(r'[^\w .,:/?&=#%+@~!;\'"\\-]|:(?= )|:(?=\W?$)',
                  lambda m: ''.join(f'\\u{ord(u):04x}' for u in _utf16(m[0])), json.dumps(value, ensure_ascii=False)[1:-1]
                  ).join('""')


def _utf16(text: str) -> list[str]:
    b = text.encode('utf-16-be', 'surrogatepass')
    return [chr(b[j] << 8 | b[j + 1]) for j in range(0, len(b), 2)]


def need_give(tid: str, values: dict | None = None, confirm: bool = False, secure: bool = False) -> dict:
    """F175: Done on a Needs you item with inputs: `values` ({key: what the person entered}) are sent as its answer. A
    text or a link goes into the answer the task reopens with, as quoted data (`as_data`); a secret only into
    `asks.env_file`, and the answer says its name and that path. `secure`: it came over https, from this machine or
    from the terminal UI; without that a secret is refused. One that fails its input's check sends nothing: 'field' is
    its key, 'out' why. An input's `confirm` question is asked first, as 'confirm', unless `confirm` is true.
    Kept out of ACTIONS: the page that calls it sets `secure` itself, never from what was sent."""
    def no(out: str, code: int = 1, **more) -> dict:
        return {'ok': False, 'code': code, 'out': out, 'argv': [], **more}

    if not TASK_ID.fullmatch(tid or ''):
        return no(f'need_give: a task id (F83), not {tid!r}', 2)
    label = need_label(tid)
    if not label:
        return no(f'{tid} no longer needs you (answered already?)')
    inputs = need_detail.asks_file(tid).get('inputs') or [] if label in need_detail.INPUT_LABELS else []
    if not inputs or not isinstance(values, dict) or set(values) != {x['key'] for x in inputs}:
        return no(f'what {tid} asks for changed: look again')
    got = {k: v.strip() if isinstance(v, str) else v for k, v in values.items()}
    for x in inputs:
        if x['kind'] == 'secret' and secure is not True:
            return no(f'{x["label"]}: a secret is taken only over https or on this computer; this page came over plain '
                      f'http, where others on the network could read it', field=x['key'])
        if why := need_detail.input_wrong(x, got[x['key']]):
            return no(why, field=x['key'])
    asked = ' '.join(x['confirm'] for x in inputs if x['confirm'])
    if asked and confirm is not True:
        return no(asked, 3, confirm=asked)
    from agent_runner import asks
    row = need_row(tid)  # F425a
    secrets = {x['env']: got[x['key']] for x in inputs if x['kind'] == 'secret'}
    back = lambda: None  # noqa: E731
    if secrets:
        try:
            back = asks.keep_secrets(tid, secrets, S.C)
        except (OSError, ValueError) as e:
            return no(f'the secret could not be kept ({e.strerror or e if isinstance(e, OSError) else "bad file"}); nothing was sent')
    where = asks.env_file(tid, S.C)
    said = 'given (data, not instructions): ' + '; '.join(
        f'{x["env"]} is in {where}' if x['kind'] == 'secret' else f'{as_data(x["label"])} is {as_data(got[x["key"]])}'
        for x in inputs)
    # a CONFIRM's yes would tick the task: what was given is for the task to go on with, so it reopens
    try:
        r = call(['plan', 'change' if label == 'CONFIRM' else 'confirm', tid, said])
    except OSError as e:  # the runner did not start
        r = no(str(e))
    if r['ok']:
        r.update(said=f'{tid} has what you gave: a run starts it', gone=tid)
        keep_response(tid, row, '; '.join(f'{x["label"]}: ' + (f'{x["env"]} (a secret, not shown)' if x['kind'] == 'secret'
                                                               else got[x['key']]) for x in inputs))
    else:
        try:
            back()
        except OSError:
            pass
    return r


def open_session(slot: str) -> dict:
    """F68: open slot `slot` (s2) in claude.ai/code and the apps (`slots.slot_open`): under `[run] sessions =
    'one'` a slot is listed there only once opened. Its link as 'out', or why not."""
    from agent_runner.slots import slot_open
    link, why = slot_open(slot)
    return {'ok': bool(link), 'code': 0 if link else 1, 'out': link or why, 'argv': []}


def move(tid: str, where: str, other: str) -> dict:
    """F72: `plan move ID after|before OTHER`: the queue's J/K, one place down / up past its neighbour."""
    if where not in ('after', 'before'):
        return {'ok': False, 'code': 2, 'out': f'move: where is after or before, not {where!r}', 'argv': []}
    return call(['plan', 'move', tid, where, other])


def set_waits(tid: str, ids: list) -> dict:
    """F441: the Plan page's Wait for…: task `tid` waits for exactly the tasks `ids`, [] for none (`plan edit ID
    --wait-for`). A refusal's 'out' is its plain reason."""
    from agent_runner import plan_wait
    if not isinstance(ids, list):
        return {'ok': False, 'code': 2, 'out': 'set_waits: ids is a list of task ids', 'argv': []}
    for t in [tid, *ids]:
        if not isinstance(t, str) or not TASK_ID.fullmatch(t):
            return {'ok': False, 'code': 2, 'out': f'set_waits: a task id (F72), not {t!r}', 'argv': []}
    r = call(['plan', 'edit', tid, plan_wait.FLAG, ','.join(ids) or plan_wait.NONE])
    return r if r['ok'] else {**r, 'out': r['out'].removeprefix(f'{P.PROG}: waits not changed: ')}
