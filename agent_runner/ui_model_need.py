"""C44: Needs you and concept details: options, answers, the chat about one, why it waits.

Part of `ui_model`: `ui_model` runs this file in its own namespace (see its end), so these names are `ui_model`'s, and a
test that sets `ui_model.X` reaches the code here. Not imported on its own."""

# --- F83: the combined run app rework: Needs you Drop and Chat, Rename, Settings, a task's whole text ----------

def pitch_no(pid: str, how: str = 'reopen', tid: str = '', confirm: bool = False, why: str = '') -> dict:
    """F98: Not this on a pitch, for all of it or the one change `tid`: the run undoes it here and reopens or drops
    its task, with the words `why`. After a confirm, as a run control's."""
    from agent_runner import pitch
    if not pitch.PITCH_ID.fullmatch(pid or '') or how not in ('reopen', 'drop') or \
            (tid and not P.TASK_ID.fullmatch(tid)):
        return {'ok': False, 'code': 2, 'out': f'pitch_no: a pitch, reopen or drop, and a task id; not {pid!r} '
                                               f'{how!r} {tid!r}', 'argv': []}
    ask = f'Undo {tid or "all of it"} here and {how} {"its task" if tid else "the tasks"}?'
    if confirm is not True:
        return {'ok': False, 'code': 3, 'out': ask, 'confirm': ask, 'argv': []}
    why = ' '.join((why or '').split())
    row = need_row(pid)  # F425a
    r = call((['pitch', 'no', pid, f'--{how}', tid] if tid else
              ['pitch', 'no', pid] + (['--drop', 'all'] if how == 'drop' else [])) + ([f'--why={why}'] if why else []))
    if r['ok']:
        r['said'] = f'{tid or pid}: the run undoes it'
        if not pitch.changes_of(pid, state='waiting'):  # the rest of it still waits otherwise
            r['gone'] = pid
            keep_response(pid, row, f'Not {tid or "this"}: {how}', why)
    return r


def need_answers(row: dict) -> list[dict]:
    """C33: the answers that fit a Needs you row, the one rule for the run page, the terminal UI and the chat
    text: [{'label', 'value'}], the first one the main button. Yes / No for a CONFIRM or a yes-or-no ask, a
    concept's options (A, B, C when its copy has none), a pitch's, a DECIDE's (F181c: {name, rec}, the value its bare
    name; F181b: its pick sheet's easy answers too), Done for a blocked item; [] when only a reply fits."""
    label, said = row.get('label', ''), f'{row.get("ask", "")} {row.get("what", "")}'
    if label == 'DECIDE' and any(isinstance(o, dict) for o in row.get('options') or []):
        return [{'label': o['name'] + (' (recommended)' if o.get('rec') else ''), 'value': o['name']}
                for o in row['options']]
    if row.get('options'):
        names = [str(o) for o in row['options']]
    elif label == 'CONFIRM' or re.search(r'\byes\s*(/|or)\s*no\b', said, re.I):
        names = ['Yes', 'No']
    elif label == 'CONCEPT':
        names = [o['name'] for o in concept_options(row.get('copy') or concept_copy(row.get('concept') or ''))] \
            or ['A', 'B', 'C']
    elif label == 'BLOCKED':
        names = ['Done']
    else:
        names = []
    return [{'label': n[:1].upper() + n[1:], 'value': n[:1].upper() + n[1:]} for n in names]


def need_options(row: dict) -> list[str]:
    """F143: the possible answers to a Needs you row for a chat's first message: its answers, else a pick sheet's
    questions with theirs; [] when only a reply fits."""
    if not row.get('picks') and (answers := row.get('answers') or need_answers(row)):  # F181b: a sheet's are its questions
        return [a['label'] for a in answers]
    label = row.get('label', '')
    if label == 'DECIDE':
        try:
            from agent_runner import sheet
            from agent_runner.brief import has_sheet
            if has_sheet(row.get('id', '')):
                spec = sheet.load(S.C.notes('sheets', f'{row["id"]}.json'))
                return [f'{q.get("q") or q.get("id", "")}: ' + ' / '.join(
                            str(o) + (' (recommended)' if j == q.get('recommended') else '')
                            for j, o in enumerate(q.get('answers') or []))
                        for q in sheet.questions(spec)]
        except Exception:  # noqa: BLE001 - a sheet that does not read: the ask says where it is
            pass
    return []


def agent_said(tid: str) -> str:
    """F162a2: the last message of the agent that worked on task `tid` (its latest session's transcript), or ''."""
    try:
        from agent_runner.slots import transcript
        from agent_runner.watch import last_session
        if (last := last_session(tid)) and (path := transcript(last[1])):
            if says := [e['text'] for e in feed_entries(tail_rows(path)) if e['kind'] == 'say']:
                return says[-1]
    except Exception:  # noqa: BLE001 - no slot logs, or a transcript that does not read
        pass
    return ''


def agent_last_words(tid: str) -> str:
    """F143: the agent's last message (`agent_said`), else the task's own lines in TODO.md, uncut (what it blocked
    with); '' for neither."""
    if said := agent_said(tid):
        return said
    ls = P.lines(S.C.todo)
    return next(('\n'.join(P._item_block(ls, i)).strip() for _, _, t, _, i in P.iter_tasks(ls) if t == tid), '')


def need_chat_text(row: dict) -> str:
    """F143: the first message of a new control session about one Needs you row: its id and title, the agent's full
    last message (what it put to the person) and the possible answers."""
    ask, what, opts = row.get('ask') or '', row.get('what') or '', need_options(row)
    out = [f"This chat is about {row.get('id', '')} '{row.get('title') or ''}', which needs me. What was put to me:",
           ask]
    if what and what.strip(' .') not in ask:
        out.append(what)
    if (last := agent_last_words(row.get('id', ''))) and last not in out:
        out.append(f"The agent's last message:\n{last}")
    if opts:
        out.append('Possible answers:\n' + '\n'.join(f'- {o}' for o in opts))
    if row.get('url'):
        out.append(f'Its page: {row["url"]}')
    out.append('Say the question and its possible answers in a few plain words, then wait for my reply. Settle it as '
               'guide needs says once I answer; do nothing before that.')
    return '\n\n'.join(x for x in out if x)


def need_chat(tid: str, wait: bool = True) -> dict:
    """F143: Chat on a Needs you item: a new control session (`control --new --ask`) whose first message is
    `need_chat_text` of it. An id that is none, or no longer needs the person, is refused."""
    if not TASK_ID.fullmatch(tid or '') and need_label(tid) not in ('PITCH', 'TOOL'):
        return {'ok': False, 'code': 2, 'out': f'need_chat: a task id (F83), not {tid!r}', 'argv': []}
    from agent_runner.status import waiting_ok
    rows, _ = needs_rows(waiting_ok(), dt.datetime.now())
    row = next((r for r in rows if r['id'] == tid), None)
    if row is None:
        return {'ok': False, 'code': 1, 'out': f'{tid} no longer needs you (answered already?)', 'argv': []}
    return new_control(need_chat_text(row), wait)


def question_answer(chat: str, id: str, text: str) -> dict:
    """F192a3: the option `text` picked on the question card of `chat` (c6) for its question `id`, which waits under
    Needs you: settles that item as its answer button does (`answer`). The chat is told as of any item it is about
    (`control_settled`), not typed the option too: whoever takes the item carries the answer out."""
    from agent_runner import chat_question
    if not re.fullmatch(r'c\d+', chat or '') or not isinstance(text, str) or not text.strip():
        return {'ok': False, 'code': 2, 'out': f'question_answer: a chat and an option; not {chat!r} {text!r}', 'argv': []}
    if not (tid := chat_question.need_of(chat, id, session_sid(chat))):
        return {'ok': False, 'code': 1, 'out': 'That question no longer needs you (answered already?)', 'argv': []}
    return answer(tid, text, button=True)


ACTIONS['question_answer'] = question_answer
ACTIONS['until_check'] = until_check  # F427d: ui_model_snapshot.py


def item_state(tid: str) -> str:
    """F425a: where item `tid` stands now, in words, for the chat about a sent response."""
    try:
        from agent_runner import control_settled, pitch
        if row := row_of('need', tid):
            return f'it needs me again: {row["ask"]}'
        if pitch.PITCH_ID.fullmatch(tid):
            return ', '.join(f'{x["id"]} {x["state"]}' for x in pitch.changes_of(tid)) or 'the pitch is settled'
        if q := queue_row(tid):
            return 'blocked in the plan' if q['blocked'] else f'open in the plan ({q["state"]})'
        return control_settled.outcome(tid)[0]
    except (Exception, SystemExit):  # noqa: BLE001 - the session can read it itself
        return 'not known'


def response_chat(rid: str, text: str = '', wait: bool = True) -> dict:
    """F425a: the person's words about the sent response `rid`: a new control session (`new_control`, `wait` as there)
    whose first message is `sent_responses.first_message`. Only with words. The response goes as its chat starts, and
    comes back if the chat does not."""
    from agent_runner import sent_responses
    if not isinstance(text, str) or not text.strip():
        return {'ok': False, 'code': 2, 'out': 'response_chat: words, please', 'argv': []}
    d = sent_responses.take(rid)
    if d is None:
        return {'ok': False, 'code': 1, 'out': 'That response is gone (a chat about it was started already?)', 'argv': []}
    started = False
    try:
        r = new_control(sent_responses.first_message(d, item_state(d['item']), text), wait)
        started = r['ok']
        return r
    finally:
        if not started:
            sent_responses.put_back(d)


ACTIONS['response_chat'] = response_chat


def close_session(tid: str, wait: bool = True) -> dict:
    """C35: close control session `tid` (c6): its process goes, its transcript stays (`control.close_from_tui`)."""
    from agent_runner import control as K
    return K.close_from_tui(int(tid[1:]))


# what a run control with an 'fn' runs, given the row's id and `wait` (C35)
ROW_FNS = {'need_chat': need_chat, 'concept_chat': lambda tid, wait: concept_chat(tid, wait=wait),
           'close_session': close_session}


def rename_chat(chat: str, title: str) -> dict:
    """F129: the person's own name for control session `chat` (c6): `control --rename N NAME`."""
    title = ' '.join(str(title or '').split())
    if not re.fullmatch(r'c\d+', chat or ''):
        return {'ok': False, 'code': 2, 'out': f'rename_chat: not a chat: {chat!r}', 'argv': []}
    if not title:
        return {'ok': False, 'code': 2, 'out': 'rename_chat: a name, please', 'argv': []}
    return call(['control', '--rename', chat[1:], title])


def task_text(tid: str) -> dict:
    """F85: a task's whole text, as `plan ID` prints it: {'ok', 'id', 'text'}."""
    if not TASK_ID.fullmatch(tid or ''):
        return {'ok': False, 'id': tid, 'out': f'a task id (F83), not {tid!r}'}
    r = call(['plan', tid])
    return {'ok': r['ok'], 'id': tid, 'text': r['out'] if r['ok'] else '', 'out': '' if r['ok'] else r['out']}


def need_why(tid: str) -> dict:
    """F162: why a Needs you item waits, for its popup: the agent's last words (`agent_said`), '' when it left no session."""
    if not TASK_ID.fullmatch(tid or ''):
        return {'ok': False, 'id': tid, 'out': f'a task id (F83), not {tid!r}'}
    return {'ok': True, 'id': tid, 'text': agent_said(tid)}


ITEM_KEYS = ('label', 'what', 'age', 'answers', 'acts')


def concept_item(row: dict, need: dict | None = None) -> dict:
    """F197b1: the Needs you item a Concepts row carries, the same shape whether a Needs you entry waits for it
    (`need`) or not (a past or kept page): {label, what, age, answers, acts, news, news_words}."""
    if need:
        item = {k: need.get(k, '') for k in ITEM_KEYS}
    else:
        item = {'label': 'CONCEPT', 'what': row.get('title', ''), 'age': '',
                'answers': [] if row.get('history') or row.get('page') else need_answers(
                    {'label': 'CONCEPT', 'concept': row.get('concept', ''), 'copy': row.get('copy', '')}),
                'acts': []}
    item['acts'] = row_acts('need', need) if need else row_acts('concept', row)
    item.update(news=row.get('news', ''), news_words=row.get('news_words', ''))
    return item


def open_chats(ids: set[str]) -> dict[str, int]:
    """F209c: {an item of `ids`: the number of the open chat about it} (`control_settled.live`: its title, what it
    was opened from, what it filed); the latest begun when several. Nothing is started."""
    if not ids:
        return {}
    from agent_runner import control_settled
    try:
        live = control_settled.live()
    except Exception:  # noqa: BLE001 - no sessions readable: no chat named
        return {}
    out: dict[str, tuple[float, int]] = {}
    for n, _sid, f, about in live:
        for x in about & ids:
            if x not in out or (f.get('begun') or 0.0, n) > out[x]:
                out[x] = (f.get('begun') or 0.0, n)
    return {x: n for x, (_b, n) in out.items()}


def name_chats(needs: list[dict], concepts: list[dict]) -> None:
    """F209c: each Needs you and Concepts row (and a row's item) gets 'chat', the open chat about it (`open_chats`)."""
    got = open_chats({r['id'] for r in needs + concepts if r.get('id')} | {r['concept'] for r in needs + concepts
                                                                          if r.get('concept')})
    for r in needs + concepts:
        if n := got.get(r.get('id', '')) or got.get(r.get('concept') or ''):
            r['chat'] = n
            if isinstance(r.get('item'), dict):
                r['item']['chat'] = n
