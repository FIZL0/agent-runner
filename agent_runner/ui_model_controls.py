"""C44: the run controls, the row actions and `act`.

Part of `ui_model`: `ui_model` runs this file in its own namespace (see its end), so these names are `ui_model`'s, and a
test that sets `ui_model.X` reaches the code here. Not imported on its own."""

from agent_runner import cancel

# --- F82: the run controls ---------------------------------------------------------------------------------
#
# One list for the web page and agent-runner ui alike, so the two cannot drift apart: each control's key, its
# label, the runner command it runs ('{n}' the slot count typed, '{id}' the task), its key in agent-runner ui,
# where it shows ('run': the run's own; 'task': a slot's task), and what it asks before it runs ('' nothing).
# Do it here is the one that is no runner command of its own: a new chat is asked "do ID here".

# F124: `group` is the More… sheet's group ('' on the Run card itself), 'fix' where a Fix up control's choices come
# from (the snapshot's `fixups`; it shows only while there are some, and '{id}' is the one picked). A control with
# `up` False starts a run, so it shows only while none is up.
STOP_NOW_ASK = ('Stop now ends every agent session at once (each resumes in the next run); '
                'merges under way are ended too and made again by the next run. The run stops, its page stays. Stop now?')
SUSPEND_ASK = ('This computer suspends once the run stops or goes idle, and its sessions stop with it. Asked again, it '
               'is taken back. Suspend?')
SHUTDOWN_ASK = ('This computer shuts down once the run stops or goes idle, and every session on it ends. Asked again, it '
                'is taken back. Shut down?')
UPGRADE_ASK = 'The run restarts on the new version between merges. Running tasks keep going. Upgrade?'
RESTART_ASK = 'The run restarts between merges and takes the settings that wait for it. Running tasks keep going. Restart?'
WIP_DROP_ASK = 'These edits are deleted here and on the remote, and cannot be brought back. Drop them?'
def answer_of(row: dict, key: str) -> str:
    """F180: the fixed answer the answer action `key` stands for on a Needs you row ('' none): need_yes and need_no
    when its answers are Yes and No, else need_answerN its Nth."""
    if row.get('label') in ('TOOL', 'PR'):
        return ''
    xs = [a['value'] for a in (row['answers'] if 'answers' in row else need_answers(row))]
    keys = ['need_yes', 'need_no'] if xs == ['Yes', 'No'] else [f'need_answer{j}' for j in range(1, len(xs) + 1)]
    return dict(zip(keys, xs)).get(key, '')


def _answer_action(key: str, label: str, tui: str, **more) -> dict:
    """F180: one fixed answer's entry in RUN_CONTROLS; its TUI key works in the answer tab only."""
    return {'key': key, 'label': label, 'tui': tui, 'where': 'need', 'answer': True, 'tab': 'answer',
            'fits': lambda r: bool(answer_of(r, key)), 'label_of': lambda r: answer_of(r, key), **more}


ANSWER_MAX, ANSWER_KEYS = 12, 'abcdefg'  # F180: the most fixed answers a row draws, and the TUI keys of the first ones
RUN_CONTROLS = (
    {'key': 'slot_add', 'label': 'Slot +1', 'argv': ('slots', '+1'), 'tui': '+', 'where': 'run'},
    {'key': 'slot_remove', 'label': 'Slot -1', 'argv': ('slots', '-1'), 'tui': '-', 'where': 'run'},
    {'key': 'slots_set', 'label': 'Set slots', 'argv': ('slots', '{n}'), 'tui': '=', 'where': 'run', 'group': 'Run'},
    {'key': 'pause', 'label': 'Pause', 'argv': ('pause',), 'tui': 'P', 'where': 'run'},
    {'key': 'go_on', 'label': 'Go on', 'argv': ('pause', '--off'), 'tui': 'G', 'where': 'run'},
    {'key': 'force', 'label': 'Force past the caps', 'argv': ('force',), 'tui': 'F', 'where': 'run', 'group': 'Run'},
    {'key': 'caps_on', 'label': 'Caps back on', 'argv': ('force', '--off'), 'tui': 'C', 'where': 'run',
     'group': 'Run'},
    {'key': 'stop', 'label': 'Stop (running tasks finish)', 'argv': ('stop',), 'tui': 'S', 'where': 'run'},
    {'key': 'stop_now', 'label': 'Stop now', 'argv': ('stop', '--force'), 'tui': 'X', 'where': 'run',
     'group': 'Stop', 'confirm': STOP_NOW_ASK},
    {'key': 'stop_undo', 'label': 'Take the stop back', 'argv': ('stop', '--undo'), 'tui': 'U', 'where': 'run'},
    # C26: the run's u, z and x keys, posted as the run view posts them (`key`: they take themselves back when
    # sent again, as typed ones do)
    {'key': 'suspend', 'label': 'Suspend once stopped', 'argv': ('key', 'z'), 'tui': 'Z', 'where': 'run',
     'group': 'Stop', 'confirm': SUSPEND_ASK},
    {'key': 'shutdown', 'label': 'Shut down once stopped', 'argv': ('key', 'x'), 'tui': 'B', 'where': 'run',
     'group': 'Stop', 'confirm': SHUTDOWN_ASK},
    {'key': 'upgrade', 'label': 'Upgrade agent-runner', 'argv': ('key', 'u'), 'tui': 'V', 'where': 'run',
     'group': 'Run', 'confirm': UPGRADE_ASK},
    {'key': 'restart', 'label': 'Restart the run', 'argv': ('key', 'restart'), 'tui': 'Y', 'where': 'run',
     'group': 'Run', 'confirm': RESTART_ASK},
    {'key': 'start', 'label': 'Start the run', 'argv': (), 'tui': 'T', 'where': 'run', 'up': False},
    {'key': 'resume', 'label': 'Resume a cut-off task', 'argv': ('resume', '{id}'), 'tui': 'r', 'where': 'run',
     'group': 'Fix up', 'fix': 'resume'},
    {'key': 'unclaim', 'label': 'Release stale claims', 'argv': ('plan', 'unclaim', '{id}'), 'tui': 'L',
     'where': 'run', 'group': 'Fix up', 'fix': 'unclaim', 'each': True},
    {'key': 'wip_show', 'label': 'Show moved-aside edits', 'argv': ('wip', 'show', '{id}'), 'tui': 'W',
     'where': 'run', 'group': 'Fix up', 'fix': 'wip'},
    {'key': 'wip_restore', 'label': 'Restore moved-aside edits', 'argv': ('wip', 'restore', '{id}'), 'tui': 'E',
     'where': 'run', 'group': 'Fix up', 'fix': 'wip'},
    {'key': 'wip_drop', 'label': 'Drop moved-aside edits', 'argv': ('wip', 'drop', '{id}'), 'tui': 'O',
     'where': 'run', 'group': 'Fix up', 'fix': 'wip', 'confirm': WIP_DROP_ASK},
    # F426d: what it asks names the minutes worked (`confirm_of`; the page adds them itself, `cutsOff`)
    {'key': 'task_cancel', 'label': 'Cancel', 'argv': ('plan', 'cancel', '{id}', '--yes'), 'tui': 'C', 'where': 'task',
     'help': 'cancel: stop it, keep its work and park it', 'confirm': cancel.ASK + ' Cancel {id}?',
     'confirm_of': lambda r: cancel.question(r['task'], r.get('name', ''), r.get('minutes'))},
    {'key': 'task_drop', 'label': 'Drop', 'argv': ('plan', 'drop', '{id}', '{why}'), 'tui': 'D', 'tui_also': 'd',
     'where': 'task'},
    # C34: a Queue row's actions ('where' 'queue', '{id}' the row's task; `fits` says which rows it is allowed on, and
    # each snapshot row carries those keys as `acts`; '{pri}' the next level, `plan.next_pri`), and the release
    # tab's ('where' 'release'). 'tui_sure' False: the terminal UI runs it without asking (the page asks).
    # 'confirm_of' (F186): a row's own confirm ('' the entry's), asked by both; the snapshot row's `asks` carries it.
    {'key': 'queue_priority', 'label': 'Priority', 'argv': ('plan', 'edit', '{id}', '--pri', '{pri}'), 'tui': 'p',
     'where': 'queue', 'fits': lambda r: r.get('state') != 'parked'},
    {'key': 'queue_unpark', 'label': 'Unpark', 'argv': ('plan', 'edit', '{id}', '--pri', 'normal'), 'tui': 'U',
     'where': 'queue', 'help': 'unpark (a parked task: no J/K or p)', 'fits': lambda r: r.get('state') == 'parked'},
    {'key': 'queue_take', 'label': 'Do it here', 'ask': 'do {id} here', 'tui': 'H', 'where': 'queue'},
    {'key': 'queue_drop', 'label': 'Drop', 'argv': ('plan', 'drop', '{id}', '{why}'), 'tui': 'D', 'tui_also': 'd',
     'where': 'queue', 'why': 'dropped from the run app', 'tui_sure': False,
     'fits': lambda r: not r.get('started'),
     'confirm_of': lambda r: f'Drop {r["id"]}? It leaves the plan, and nothing is released.' if P.release(r['id']) and releases_on() else split_ask(r),
     'confirm': 'It leaves the plan, and a slot running it is stopped. Drop it?'},
    # F429b: the row menu of a Plan queue row (the page alone: no TUI key), on the row's `menu`; a running one has none.
    # Restore is Undo's: the row is out of the plan, so it fits none and has its place as `text` (`menu_restore`)
    {'key': 'menu_hold', 'label': "Hold: a run won't start it", 'argv': ('plan', 'hold', '{id}'), 'tui': '', 'where': 'queuemenu',
     'said': '{id} is held', 'fits': lambda r: menu_on(r) and not r.get('held') and not r.get('no_hold')},
    {'key': 'menu_unhold', 'label': 'End the hold', 'argv': ('plan', 'unhold', '{id}'), 'tui': '', 'where': 'queuemenu',
     'said': '{id} is no longer held', 'fits': lambda r: menu_on(r) and bool(r.get('held'))},
    {'key': 'menu_top', 'label': 'To the top', 'argv': ('plan', 'move', '{id}', 'top'), 'tui': '', 'where': 'queuemenu',
     'said': '{id} is at the top', 'fits': lambda r: menu_on(r)},
    {'key': 'menu_remove', 'label': 'Remove', 'argv': ('plan', 'drop', '{id}', '{why}'), 'tui': '', 'where': 'queuemenu',
     'why': 'removed from the Plan queue', 'said': '{id} is removed',
     'fits': lambda r: menu_on(r)},
    {'key': 'menu_restore', 'label': 'Put back', 'argv': ('plan', 'restore', '{id}'), 'tui': '', 'where': 'queuemenu',
     'said': '{id} is back', 'fits': lambda r: False},
    # F184: a shelved task's, in the Parked group; never Unpark, which would not reopen it
    {'key': 'shelved_back', 'label': 'Bring back', 'argv': ('plan', 'unshelve', '{id}'), 'tui': 'U', 'where': 'shelved',
     'help': 'bring back (a shelved task)', 'said': '{id} is under Needs you again',
     'fits': lambda r: bool(r.get('ask'))},
    {'key': 'shelved_drop', 'label': 'Drop', 'argv': ('plan', 'drop', '{id}', '{why}'), 'tui': 'D', 'tui_also': 'd',
     'where': 'shelved', 'why': 'dropped from Parked', 'said': '{id} dropped', 'help': 'drop (a shelved task)',
     'confirm': 'Drop {id}? It leaves the plan, and its work is not done.'},
    # C35: the other panels' row actions, the same shape: 'need' (a Needs you item), 'concept', 'session' (a control
    # session cN). 'fn' one of ROW_FNS run with the row's id (a new chat, a close); 'chat' it opens a chat; 'said' its
    # toast, and a Needs you item it is done with leaves the list. '{id}' in a confirm is the row's id.
    # F180: its fixed answers (`need_answers`), each labelled by its row ('label_of', the snapshot row's `labels`):
    # 'answer' runs `answer` with that label, 'tab' the TUI tab its key works in, 'help' '' not in the keys list
    _answer_action('need_yes', 'Yes', 'y', help='yes (answer tab)'),
    _answer_action('need_no', 'No', 'n', help='no (answer tab)'),
    *(_answer_action(f'need_answer{j}', f'Answer {j}', ANSWER_KEYS[j - 1:j], help="a pick's options" if j == 1 else '',
                     help_keys='a b c' if j == 1 else '') for j in range(1, ANSWER_MAX + 1)),
    {'key': 'need_later', 'label': 'Later', 'argv': ('plan', 'shelve', '{id}'), 'tui': 'L', 'where': 'need',
     'said': '{id} is set aside until you bring it back', 'fits': lambda r: r.get('label') not in ('PITCH', 'TOOL', 'PR')},
    {'key': 'need_chat', 'label': 'Chat', 'fn': 'need_chat', 'chat': True, 'tui': 'N', 'where': 'need',
     'fits': lambda r: r.get('label') not in ('TOOL', 'PR')},
    {'key': 'need_drop', 'label': 'Drop', 'argv': ('plan', 'drop', '{id}', '{why}'), 'tui': 'D', 'tui_also': 'd',
     'where': 'need', 'why': 'dropped from Needs you', 'said': '{id} dropped',
     'confirm': 'Drop {id}? It leaves the plan, and its work is not done.',
     'fits': lambda r: r.get('label') not in ('PITCH', 'TOOL', 'PR')},
    {'key': 'concept_chat', 'label': 'New chat', 'fn': 'concept_chat', 'chat': True, 'tui': 'N', 'where': 'concept',
     'help': 'chat about it'},
    {'key': 'concept_drop', 'label': 'Drop', 'argv': ('plan', 'drop', '{id}', '{why}'), 'tui': 'd',
     'where': 'concept', 'why': 'dropped from agent-runner ui', 'tui_sure': False, 'tui_main': False,
     'confirm': 'It leaves the plan. Drop it?'},
    {'key': 'session_close', 'label': 'Close', 'fn': 'close_session', 'tui': 'd', 'where': 'session',
     'tui_main': False,
     'help': 'close a control session (its transcript stays)',
     'fits': lambda r: bool(re.fullmatch(r'c\d+', str(r.get('name', ''))))},
    {'key': 'release_wait', 'label': 'Release when the running tasks land', 'argv': ('plan', 'add', 'V'), 'tui': '⏎',
     'where': 'release'},
    {'key': 'release_now', 'label': 'Release now, without them', 'argv': ('plan', 'add', 'V', '--now'), 'tui': 'f',
     'where': 'release'},
)
TASK_DROP_WHY = 'dropped from its slot from the run controls'
SLOT_COUNT = re.compile(r'[+-]?\d{1,3}')
TASK_ID = P.TASK_ID  # B199: the ids plan takes, parts of parts (F162a2) too


CONTROL_ROWS = (('start',), ('slot_add', 'slot_remove', 'slots_set'), ('pause', 'go_on'), ('force', 'caps_on'),
                ('stop', 'stop_now', 'stop_undo'), ('suspend', 'shutdown'), ('upgrade', 'restart'),
                ('resume', 'unclaim'), ('wip_show', 'wip_restore', 'wip_drop'))  # C33: the terminal UI's key rows


def task_controls_on(row) -> bool:
    """C33: a slot's task controls (Cancel, Drop) work while it works on a task, not while the task lands
    (merging); a control session has none."""
    return isinstance(row, dict) and bool(row.get('task')) and not re.fullmatch(r'c\d+', str(row.get('name', ''))) \
        and row.get('state') != 'merging'


def controls_shown(up: bool, run: dict, fixups: dict) -> dict:
    """C33: which run controls show now, for both pages: 'shown' the keys (all but Start the run while none is up,
    only a Fix up one then; Force or Caps back on by the run's state; a Fix up one while there is something to fix)
    and 'card' the everyday ones on the page's Run card."""
    shown = []
    for c in RUN_CONTROLS:
        if c['where'] != 'run' or (c['key'] == 'restart' and _plat().WINDOWS):
            continue
        if (c.get('fix') and not (fixups or {}).get(c['fix'])) or (c['key'] == 'force' and run.get('forced')) or \
                (c['key'] == 'caps_on' and not run.get('forced')):
            continue
        if c.get('up', True) == up or (not up and c.get('fix')):
            shown.append(c['key'])
    card = ['start'] if not up else ['slot_remove', 'slot_add', 'go_on' if run.get('paused') else 'pause',
                                      'stop_undo' if run.get('stopping') else 'stop']
    return {'shown': shown, 'card': card}


def _plat():
    from agent_runner import plat
    return plat


def menu_on(row: dict) -> bool:
    """F429b: can the Plan queue row `row` be moved: a run works on it in no way, and it is not parked?"""
    state = str(row.get('state') or '')
    return not (row.get('started') or row.get('under_way') or state == 'parked' or state.startswith('running'))


def menu_row(tid: str) -> dict | None:
    """F429b: the row whose menu `tid` names, the Next release row (`release_moves.NEXT`) too (None: there is none)."""
    from agent_runner import release_moves
    if tid != release_moves.NEXT:
        return queue_row(tid)
    ls, st = P.lines(S.C.todo), _state(S.run_up())
    return auto_release_row(ls, 0, release_tasks(ls, st)) if releases_on() else None


def menu_place(text: str) -> list[str]:
    """F429b: where `plan restore` puts a removed row: `text` is the page's JSON {'up': the ids above it in its section,
    'down': those below, 'in': the section}. The place with the fewest of them on the wrong side now, as others may have
    moved or landed; its section's end with none left, else the top. ValueError when it does not read."""
    at = json.loads(text)
    if not isinstance(at, dict) or not all(isinstance(at.get(k, []), list) for k in ('up', 'down')):
        raise ValueError('no place')
    up, down, sec = at.get('up', []), at.get('down', []), str(at.get('in') or '')
    ls = P.lines(S.C.todo)
    now = [tid for s, box, tid, _, _ in P.iter_tasks(ls) if box in ' ~' and s == sec]
    if any(t in up or t in down for t in now):
        wrong = [sum(t in down for t in now[:n]) + sum(t in up for t in now[n:]) for n in range(len(now) + 1)]
        n = wrong.index(min(wrong))
        return ['after', now[n - 1]] if n else ['before', now[0]]
    return ['in', sec] if sec and f'### {sec}' in (l.strip() for l in ls) else ['top']


def menu_restore(tid: str, text: str) -> dict:
    """F429b: Undo of a Remove: the row is back where it stood (the Next release row's place is its count's)."""
    from agent_runner import release_moves
    argv = ['plan', 'restore', tid]
    if tid != release_moves.NEXT:
        try:
            if not TASK_ID.fullmatch(tid or ''):
                raise ValueError('no task id')
            argv += menu_place(text)
        except ValueError as e:
            return {'ok': False, 'code': 2, 'out': f'menu_restore: {e}', 'argv': []}
    return menu_said(run_control_of('menu_restore'), tid, call(argv))


def menu_said(c: dict, tid: str, r: dict) -> dict:
    """F429b: the result `r` of the row menu's control `c`, in the page's words once it is done."""
    from agent_runner import release_moves
    return r if not r['ok'] else {**r, 'out': c['said'].replace('{id}', 'Next release' if tid == release_moves.NEXT else tid)}


def row_acts(where: str, row: dict) -> list[str]:
    """C34: the keys of the actions of panel `where` ('queue') allowed on `row` now, in the list's order."""
    return [c['key'] for c in RUN_CONTROLS if c['where'] == where and c.get('fits', lambda r: True)(row)]


def row_labels(where: str, row: dict) -> dict[str, str]:
    """F180: {key: label} of the actions allowed on `row` whose label is the row's own."""
    return {c['key']: c['label_of'](row) for c in RUN_CONTROLS
            if c['where'] == where and 'label_of' in c and c['fits'](row)}


def row_asks(where: str, row: dict) -> dict[str, str]:
    """F186: {key: question} of the actions allowed on `row` whose confirm is the row's own."""
    return {c['key']: q for c in RUN_CONTROLS if c['where'] == where and 'confirm_of' in c
            and c.get('fits', lambda r: True)(row) and (q := c['confirm_of'](row))}


def split_ask(row: dict, short: bool = False) -> str:
    """B811b: what Drop asks on a split task's queue row: which of its parts stay open ('' for any other); `short`: by
    id alone, for the terminal UI's one line."""
    parts = (row.get('split') or {}).get('open') or []
    if not parts:
        return ''
    stops = ' A slot running it is stopped.' if str(row.get('state') or '').startswith('running') else ''
    if short:
        return f'Drop {row["id"]}?{stops} {", ".join(p["id"] for p in parts)} {"stays" if len(parts) == 1 else "stay"} open.'
    n, names = len(parts), ', '.join(f'{p["id"]} {p["title"]}'.rstrip() for p in parts)
    return f'Drop {row["id"]}?{stops} ' + ('Its open part stays' if n == 1 else f'Its {n} open parts stay') + f' in the plan: {names}.'


def queue_row(tid: str) -> dict | None:
    """C34: the queue's row of task `tid` as TODO.md has it now (None: not queued)."""
    return next((q for q in queue_rows(P.lines(S.C.todo), _state(S.run_up())) if q['id'] == tid), None)


ROW_WORDS = {'queue': 'a queued task', 'queuemenu': 'a queued task or release', 'shelved': 'a shelved task', 'need': 'something that needs you', 'concept': 'a concept waiting',
             'session': 'a control session'}


def row_of(where: str, tid: str) -> dict | None:
    """C35: the row of panel `where` that `tid` names as the plan has it now (None: it is not there)."""
    if where == 'queue':
        return queue_row(tid)
    if where == 'queuemenu':
        return menu_row(tid)
    if where == 'session':
        return {'name': tid} if re.fullmatch(r'c\d+', tid or '') else None
    from agent_runner.status import waiting_ok
    if where == 'shelved':
        return next((r for r in shelved_rows(P.lines(S.C.todo), waiting_ok()) if r['id'] == tid), None)
    needs, concepts = needs_rows(waiting_ok(), dt.datetime.now())
    return next((r for r in (needs if where == 'need' else concepts)
                 if tid == r['id'] or (where == 'concept' and tid == r['concept'])), None)


def task_row(tid: str) -> dict | None:
    """F426d: the slot's row that works on task `tid`, as the run's STATE has it now."""
    st = _state(S.run_up())
    return next((r for r in session_rows(st, [], {}, time.time(), {}, windows={}) if tid and r['task'] == tid), None)


def run_control_of(key: str) -> dict | None:
    return next((c for c in RUN_CONTROLS if c['key'] == key), None)


def controls(rel_ask: dict | None = None) -> list[dict]:
    """The run controls as a page shows them: key, label, TUI key, where, what it needs typed ('n': a slot
    count, 'id': a task) and its confirm question ('' none). F186: with a release open (`rel_ask`:
    `release_ask`), New release's actions ask, and carry the open ones as `seen`."""
    from agent_runner import plat

    def needs(c):
        if c.get('fix'):
            return 'pick'
        words = c.get('argv') or (c.get('ask') or '',)
        if c.get('fn') or c.get('answer'):
            return 'id'
        return 'n' if any('{n}' in w for w in words) else 'id' if any('{id}' in w for w in words) else ''
    return [{'key': c['key'], 'label': c['label'], 'tui': c['tui'], 'where': c['where'], 'needs': needs(c),
             'confirm': rel_ask['ask'] if rel_ask and c['where'] == 'release' else c.get('confirm', ''),
             'seen': rel_ask['seen'] if rel_ask and c['where'] == 'release' else '', 'group': c.get('group', ''), 'fix': c.get('fix', ''),
             'each': bool(c.get('each')), 'up': c.get('up', True), 'tui_also': c.get('tui_also', ''),
             'tui_sure': c.get('tui_sure', True), 'chat': bool(c.get('ask') or c.get('chat')), 'fn': bool(c.get('fn')),
             'tui_main': c.get('tui_main', True), 'answer': bool(c.get('answer')),
             'tab': c.get('tab', '')} for c in RUN_CONTROLS
            if not (plat.WINDOWS and c['key'] == 'restart')]  # no re-exec there


def _next_row() -> str:
    from agent_runner import release_moves
    return release_moves.NEXT


def control_argv(key: str, n='', tid: str = '', why: str = '', pri: str = '') -> list[str]:
    """The runner command control `key` runs, filled in; ValueError says what is missing or wrong."""
    c = run_control_of(key)
    if c is None:
        raise ValueError(f'no such run control: {key!r}')
    words = list(c.get('argv') or ())
    n = str(n).strip()
    if any('{n}' in w for w in words) and not (SLOT_COUNT.fullmatch(n) and (key != 'slots_set' or n.isdigit())):
        raise ValueError(f'{key}: the slot count is a number, not {n!r}')
    if c.get('fix') == 'wip':
        if not re.fullmatch(r'main-checkout-[\w.-]+', tid or ''):
            raise ValueError(f'{key}: which moved-aside edits? not {tid!r}')
    elif any('{id}' in w for w in words + [c.get('ask') or '']) and not TASK_ID.fullmatch(tid or '') and \
            not (c['where'] == 'queuemenu' and tid == _next_row()):
        raise ValueError(f'{key}: a task id (F82), not {tid!r}')
    return [w.replace('{n}', n).replace('{id}', tid).replace('{why}', why or c.get('why') or TASK_DROP_WHY)
            .replace('{pri}', pri) for w in words]


def run_control(key: str, n='', tid: str = '', why: str = '', confirm: bool = False, wait: bool = True,
                text: str = '', note: str = '') -> dict:
    """F82: run one run control (RUN_CONTROLS) for the web page or agent-runner ui. One with a confirm question
    runs only with `confirm` true; without it the result is not ok and carries the question as 'confirm'. B139:
    one with an 'ask' starts a new control session with it (`new_control`, `wait` as there). F180: an answer takes `text`, the label the
    person pressed (refused when the row's answers have changed since), and `note`, the words beside it. F186: a New release takes
    the open releases the person said Yes to (`seen`) as `text`."""
    c = run_control_of(key)
    if c and c.get('each') and not tid:  # every one there is: 'Release stale claims (2)'
        ids = [x['id'] for x in fixups(_state(S.run_up()), P.lines(S.C.todo)).get(c['fix']) or []]
        if not ids:
            return {'ok': False, 'code': 1, 'out': f'{c["label"]}: there is nothing to do', 'argv': []}
        rs = [run_control(key, tid=i) for i in ids]
        bad = next((r for r in rs if not r['ok']), None)
        return bad or {**rs[-1], 'out': ', '.join(r['out'] for r in rs)}
    if key == 'menu_restore':  # F429b
        return menu_restore(tid, text)
    pri, row = '', {}
    if c and c['where'] in ROW_WORDS:  # C34, C35: allowed on this row now (the snapshot's `acts`, checked again)
        row = row_of(c['where'], tid)
        if c.get('answer') and row is None:
            return {'ok': False, 'code': 1, 'out': f'{tid} no longer needs you (answered already?)', 'argv': []}
        if row and row.get('started') and key == 'queue_drop':  # F186
            return {'ok': False, 'code': 1, 'out': f'{tid} has started: a running release cannot be dropped', 'argv': []}
        if row is None or key not in row_acts(c['where'], row):
            return {'ok': False, 'code': 1, 'out': f'{c["label"]}: {tid or "none"} is not {ROW_WORDS[c["where"]]} it '
                                                   f'fits', 'argv': []}
        if key == 'menu_remove' and tid != _next_row():  # F429b: as `plan move` and `plan hold` refuse it themselves
            from agent_runner import row_hold
            if why := row_hold.under_way(S.C, tid):
                return {'ok': False, 'code': 1, 'out': f'{tid} cannot be removed: {why}', 'argv': []}
        pri = P.next_pri(row.get('pri'))  # F438
        if c.get('answer'):
            said = answer_of(row, key)
            if text != said:
                return {'ok': False, 'code': 1, 'out': f"{tid}'s answers changed: look again", 'argv': []}
            return answer(tid, (row.get('picks') or {}).get(said, said), button=True, note=note)  # F181b: a pick sheet's
    if key == 'task_cancel':  # F426d
        row = task_row(tid) or {}
        if row and not task_controls_on(row):
            return {'ok': False, 'code': 1, 'out': f'{tid} is landing, so it cannot be cancelled', 'argv': []}
    if c and c.get('fn'):
        return ROW_FNS[c['fn']](tid, wait)
    if c and c['where'] == 'release' and not releases_on():  # F193: a page from before it was turned off
        return {'ok': False, 'code': 1, 'out': 'Manage releases is off in Settings: no release was queued', 'argv': []}
    try:
        argv = control_argv(key, n, tid, why, pri)
    except ValueError as e:
        return {'ok': False, 'code': 2, 'out': str(e), 'argv': []}
    if c.get('confirm') and confirm is not True:
        ask = (row_asks(c['where'], row).get(key) if row else '') or c['confirm'].replace('{id}', tid)
        return {'ok': False, 'code': 3, 'out': ask, 'confirm': ask, 'argv': argv}
    if c.get('ask'):
        return new_control(c['ask'].replace('{id}', tid), wait)
    if c['where'] == 'release':  # F186
        return new_release(argv, text, confirm)
    r = call(argv)
    if c['where'] == 'queuemenu':
        return menu_said(c, tid, r)
    FIXUPS[0] = float('-inf')  # what there is to fix is looked up anew
    if r['ok'] and c.get('said'):  # C35
        r.update(said=c['said'].replace('{id}', tid), **({'gone': tid} if c['where'] == 'need' else {}))
    return r


ACTIONS = {'plan_add': plan_add, 'plan_change': plan_change, 'chat': chat, 'answer': answer, 'drop': drop,
           'open_session': open_session, 'move': move,
           'run_control': run_control}


def act(name: str, **args) -> dict:
    """Run the action `name` with `args` (a page's POST body): an unknown name is an error result, not a raise."""
    if name not in ACTIONS:
        return {'ok': False, 'code': 2, 'out': f'no such action: {name}', 'argv': []}
    try:
        return ACTIONS[name](**args)
    except TypeError as e:
        return {'ok': False, 'code': 2, 'out': f'{name}: {e}', 'argv': []}
