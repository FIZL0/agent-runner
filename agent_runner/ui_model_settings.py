"""C44: the settings the page shows and saves.

Part of `ui_model`: `ui_model` runs this file in its own namespace (see its end), so these names are `ui_model`'s, and a
test that sets `ui_model.X` reaches the code here. Not imported on its own."""

def settings() -> dict:
    """F97: every setting, its value, source and default (`config.settings_snapshot`), read from the files now."""
    from agent_runner import agents_here
    from agent_runner import config as CF
    snap, was = CF.settings_snapshot(S.ROOT), SETTINGS_AT[0]
    now = _setting_values(snap)
    snap['waits'] = [f'{t}.{k}' for (t, k), v in now.items() if was and (t, k) in CF.SETTING_NEXT and was.get((t, k)) != v]
    row = lambda t, key: next(k for x in snap['tables'] if x['table'] == t for k in x['keys'] if k['key'] == key)  # noqa: E731
    agent = row('run', 'agent')  # F405: its picker, and the providers beside it
    agent['picks'] = agents_here.picks(S.ROOT, agent)
    from agent_runner import working_branch as WB
    wb = row('git', 'master_branch')  # F447b: its picks, the branch now, and the switch that waits
    try:
        wb.update(WB.show(S.ROOT, wb))
    except SystemExit:  # a settings file that cannot be taken: the rest of the page still shows
        pass
    if 'next' in wb and 'git.master_branch' not in snap['waits']:  # a start that could not switch
        snap['waits'].append('git.master_branch')
    from agent_runner import setting_checks
    for t in snap['tables']:  # F448a: why a row cannot be changed here now, '' when it can
        for k in t['keys']:
            try:
                k['locked'] = setting_checks.locked(S.ROOT, t['table'], k['key'])
            except SystemExit:  # as above
                k['locked'] = ''
    snap['providers'] = agents_here.providers(row('models', 'providers')['value'])
    return snap


SETTINGS_AT: list[dict] = [{}]  # F166: the settings as this process read them at its start: a SETTING_NEXT one that differs now waits


def _setting_values(snap: dict) -> dict:
    return {(t['table'], k['key']): k['value'] for t in snap['tables'] for k in t['keys']}


def settings_start() -> None:
    """F166: the run's web server starts: keep what its settings are now (`settings`' `waits`)."""
    from agent_runner import config as CF
    SETTINGS_AT[0] = _setting_values(CF.settings_snapshot(S.ROOT))


_SETTING_LOCK = threading.Lock()  # two pages saving at once: one read and write of the file at a time


def _setting_done(table: str, key: str, value=None, unset: bool = False) -> dict:
    from agent_runner import config as CF
    try:
        with _SETTING_LOCK:
            undo = _branch_begin('device', table, key, value, unset)
            try:
                f = CF.save_local_setting(S.ROOT, table, key, value, unset)
            except BaseException:
                undo()
                raise
    except (ValueError, OSError) as e:
        return {'ok': False, 'code': 2, 'out': str(e), 'argv': []}
    if bad := _setting_now(table, key, f.name):
        return bad
    _plan_moved(table, key)
    more = _branch_said(table, key)
    out = f'{_setting_said(table, key, value, unset)} in {f.name}' + (f' ({more})' if more else '')
    return {'ok': True, 'code': 0, 'out': out, 'argv': [], **({'note': more} if more else {})}


def _branch_begin(side: str, table: str, key: str, value, unset: bool):
    """F447b: a save of the working branch is about to be written: what takes that back when it fails."""
    from agent_runner import working_branch as WB
    if (table, key) != ('git', 'master_branch'):
        return lambda: None
    try:
        return WB.begin(S.ROOT, side, value, unset)
    except SystemExit as e:
        raise ValueError(str(e).removeprefix('agent-runner: ')) from None


def _branch_said(table: str, key: str) -> str:
    from agent_runner import working_branch as WB
    return WB.said(S.ROOT) if (table, key) == ('git', 'master_branch') else ''


def _setting_said(table: str, key: str, value, unset: bool) -> str:
    from agent_runner import config as CF
    return f'[{table}] {key} is reset' if unset else f'[{table}] {key} = {CF.toml_value(value)}'


def _setting_row(table: str, key: str) -> dict:
    from agent_runner import config as CF
    return next(k for t in CF.settings_snapshot(S.ROOT)['tables'] if t['table'] == table for k in t['keys'] if k['key'] == key)


def _setting_now(table: str, key: str, name: str) -> dict | None:
    """The slot count: the run that is up is told (a key may have set another); its result when it did not take it.
    Every other setting it reads by itself (F202a)."""
    if (table, key) != ('run', 'slots') or not S.run_up():
        return None
    r = call(['slots', str(_setting_row(table, key)['value'])])
    return None if r['ok'] else {**r, 'saved': True, 'out': f'saved in {name}, but the run did not take it: {r["out"]}'}


def setting_device(table: str, key: str, value=None) -> dict:
    """F97: save a This device value: one key of runner.local.toml, in place, at once."""
    return _setting_done(table, key, value)


def setting_reset(table: str, key: str) -> dict:
    """F97: clear a device override: the key leaves runner.local.toml."""
    return _setting_done(table, key, unset=True)


SETTING_SETTLE = 0.4  # s a save for everyone waits for others, so that rapid ones are one commit
SETTING_WAIT = 60.0  # s it waits for a merge that is landing
_SETTING_QUEUE: list[dict] = []  # the saves not written yet, oldest first
_SETTING_WRITE = threading.Lock()  # one batch of them at a time


def setting_project(table: str, key: str, value=None, unset: bool = False) -> dict:
    """F173: save a value for everyone (`unset`: take it out): one key of runner.toml, in place, committed alone and
    pushed at once (`_save_project`). Saves that come together are one commit."""
    from agent_runner import config as CF
    if unset and key not in CF.DEFAULTS.get(table, {}):
        return {'ok': False, 'code': 2, 'out': f'[{table}] {key} is not a setting', 'argv': []}
    if problem := _value_problem('project', table, key, value, unset):
        return {'ok': False, 'code': 2, 'out': problem, 'argv': []}
    return _project_saves([{'table': table, 'key': key, 'value': value, 'unset': unset}])[0]['got']


def _project_saves(mine: list[dict]) -> list[dict]:
    """Write these checked saves for everyone as one commit, with what else waits; each has its result as `got`."""
    for x in mine:
        x['got'] = None
    with _SETTING_LOCK:
        _SETTING_QUEUE.extend(mine)
    with _SETTING_WRITE:
        if any(x['got'] is None for x in mine):  # not taken along by the save before it
            time.sleep(SETTING_SETTLE)
            batch: list[dict] = []
            try:
                _save_project(batch)
            except Exception as e:  # noqa: BLE001 - every save of the batch hears of it
                for x in batch:
                    x['got'] = x['got'] or {'ok': False, 'code': 1, 'out': f'not saved: {e}', 'argv': []}
    for x in mine:
        x['got'] = x['got'] or {'ok': False, 'code': 1, 'out': 'not saved', 'argv': []}
    return mine


def _setting_has(row: dict, side: str) -> dict:
    """What `side`'s file holds for a setting: {'has', 'value'}, as JSON carries it."""
    return {'has': row[f'has_{side}'], 'value': json.loads(json.dumps(row.get(side), default=str))}


def _change_problem(c: dict, rows: dict) -> dict:
    """Why a change of `settings_save` is not taken ({'why', 'changed'}), {} when it is."""
    table, key, side = str(c.get('table')), str(c.get('key')), c.get('side')
    row = rows.get((table, key))
    if row is None or side not in ('device', 'project'):
        return {'why': f'[{table}] {key} is not a setting' if row is None else f'{side!r} is not a place of a setting'}
    want = c.get('expect')
    if isinstance(want, dict) and _setting_has(row, side) != {'has': want.get('has'), 'value': want.get('value')}:
        return {'why': f'[{table}] {key} was changed since, so it stays as it is', 'changed': True}
    why = _value_problem(side, table, key, c.get('value'), bool(c.get('unset')))
    return {'why': why} if why else {}


def _value_problem(side: str, table: str, key: str, value, unset: bool) -> str:
    """Why this value, or the reset (`unset`), is not saved in `side`'s file; '' when it is."""
    from agent_runner import config as CF, setting_checks
    return setting_checks.reset_problem(S.ROOT, side, table, key) if unset else \
        CF.setting_check(S.ROOT, table, key, value, **({'device': True} if side == 'device' else {}))


def _plan_moved(table: str, key: str) -> None:
    """F448a: where the plan or the worktrees are was saved, so no run is up: this page goes by it at once."""
    from agent_runner import config as CF, setting_checks
    if (table, key) in setting_checks.PLAN_AT and not S.run_up():
        CF._cfg.cache_clear()
        S.init(S.ROOT)


def _setting_rows() -> dict:
    from agent_runner import config as CF
    return {(t['table'], k['key']): k for t in CF.settings_snapshot(S.ROOT)['tables'] for k in t['keys']}


def _save_round(changes: list[dict]) -> tuple[list, list, list]:
    """Check and write `changes`: (change, its save, what its file had, what it has) of those saved, and (change, why)
    of those whose write failed, then of those refused."""
    from agent_runner.setting_checks import PLAN_AT
    before, take, refused = _setting_rows(), [], []
    for c in changes:
        why = _change_problem(c, before)
        at = c.get('table'), c.get('key')
        if not why and at in PLAN_AT and any((x['table'], x['key']) in PLAN_AT for x in take):  # each was checked alone
            why = {'why': f'[{at[0]}] {at[1]}: where the plan and the worktrees are is changed one setting at a time'}
        refused.append((c, why)) if why else take.append(c)
    project = [c for c in take if c['side'] == 'project']
    mine = [{'table': c['table'], 'key': c['key'], 'value': c.get('value'), 'unset': bool(c.get('unset'))} for c in project]
    got = list(zip(project, _project_saves(mine))) if mine else []
    for c in take:
        if c['side'] == 'device':
            r = _setting_done(c['table'], c['key'], c.get('value'), bool(c.get('unset')))
            got.append((c, {'got': r, 'note': r.get('note', '')}))
    after, saved, failed = _setting_rows(), [], []
    for c, x in got:
        at = c['table'], c['key']
        if x['got']['ok'] or x['got'].get('saved'):
            saved.append((c, x, _setting_has(before[at], c['side']), _setting_has(after[at], c['side'])))
        else:
            failed.append((c, {'why': x['got']['out']}))
    return saved, failed, refused


def settings_save(changes: list) -> dict:
    """F202b: the Settings page's Save: every change ({'table', 'key', 'side': 'device' or 'project', 'value' or
    'unset'}), each to its home; those for everyone are one commit. A change that is not taken leaves the others alone.
    `was`: what each saved one had before and has `now`, in its file (the page's Undo); `bad`: those not taken, with
    `why`; `say`: what there is to say of the saved ones (not pushed, the run did not take it). With `expect` (a `now` of an earlier save) a change is taken only while the file still holds that."""
    if not isinstance(changes, list) or not changes or not all(isinstance(c, dict) for c in changes):
        return {'ok': False, 'code': 2, 'out': 'no changes to save', 'argv': []}
    saved, failed, refused = _save_round(changes)
    if refused and any(c['table'] == 'models' for c, *_ in saved):
        more, fails, refused = _save_round([c for c, _ in refused])  # the models they name are there by now, or none names the one that goes
        saved, failed = saved + more, failed + fails
    bad = [{'table': c.get('table'), 'key': c.get('key'), 'side': c.get('side'), **why} for c, why in failed + refused]
    warn = [x['got']['out'] for _, x, _, _ in saved if not x['got']['ok']]
    notes = list(dict.fromkeys(x['note'] for _, x, _, _ in saved if x.get('note')))
    out = bad[0]['why'] if bad else warn[0] if warn else saved[0][1]['got']['out'] if len(saved) == 1 else \
        f'{len(saved)} settings saved' + ''.join(f' ({n})' for n in notes)
    return {'ok': not bad, 'code': 1 if bad else 0, 'out': out, 'argv': [], 'bad': bad, 'warn': bool(warn),
            'say': out if warn or notes else '',
            'was': [{'table': c['table'], 'key': c['key'], 'side': c['side'], 'was': had, 'now': has}
                    for c, _, had, has in saved if had != has]}


def _setting_push() -> str:
    """Push the commit as a plan edit is: what there is to say of it, '' when pushed (or nowhere to push)."""
    try:
        why = P._push(S.ROOT)
    except (Exception, SystemExit) as e:  # noqa: BLE001 - it is committed: never 'not saved'
        why = f'{type(e).__name__}: {e}'
    if why:
        return f'saved here, not pushed: {why}'
    return 'saved here; it is pushed with the next change you approve' if S.C.approve and S.C.push_remote else ''


def _save_project(batch: list[dict]) -> None:
    """Write the waiting saves (into `batch`) to runner.toml as one commit on the shared branch and push it as a plan
    edit is; each gets its result as `got`. It holds LANDING, which every merge takes to move the main checkout, and not
    MERGE: that one is held through a whole test gate, and a save must not wait an hour. A merge that is testing takes
    the commit in as it does any other the branch gets meanwhile."""
    from agent_runner import config as CF
    if not (free := S.LANDING.acquire(timeout=SETTING_WAIT)):
        why = 'a merge is landing and has not finished. Nothing was changed'
    with _SETTING_LOCK:
        batch[:] = _SETTING_QUEUE
        _SETTING_QUEUE.clear()
    bad = lambda x, why: x.update(got={'ok': False, 'code': 1, 'out': why, 'argv': []})  # noqa: E731
    try:
        f = CF.config_file(S.ROOT) or CF.main_checkout(S.ROOT) / 'runner.toml'
    except SystemExit as e:  # AGENT_RUNNER_CONFIG names a file that is gone
        why = f'{e}. Nothing was changed'
        if free:
            S.LANDING.release()
        free = False
    if not free:
        for x in batch:
            bad(x, why)
        return
    last = {(x['table'], x['key']): x for x in batch}  # the newest save of a key wins
    undo: list = []  # F447b

    def edit(data: bytes) -> tuple[bytes, str]:
        done = []
        for x in last.values():
            try:
                new = CF.setting_edit(data, x['table'], x['key'], x['value'], x['unset'], f.name)
                undo.append(_branch_begin('project', x['table'], x['key'], x['value'], x['unset']))
                data = new
            except ValueError as e:
                bad(x, str(e))
                continue
            done.append(x)
        said = '; '.join(_setting_said(x['table'], x['key'], x['value'], x['unset']) for x in done)
        short = said if len(said) <= 100 else ', '.join(f'[{x["table"]}] {x["key"]}' for x in done)
        return data, f'settings: {short}'
    ok = False
    try:
        ok, note = plansync.commit_file(S.ROOT, f, edit, S.default_branch())
        if ok and not note:  # committed; the push in LANDING too: it may rebase the main checkout when no run is up
            note = _setting_push()
    except SystemExit as e:  # the working branch is not out in the main checkout
        ok, note = False, f'{e}. Nothing was changed'
    finally:
        S.LANDING.release()
        if not ok:
            for back in undo:
                back()
    if not ok:
        for x in last.values():
            if x['got'] is None:
                bad(x, note)
    else:
        if note == 'nothing to change':
            note = ''
        for x in last.values():
            if x['got'] is None:
                _plan_moved(x['table'], x['key'])
                row = _setting_row(x['table'], x['key'])
                out = f'{_setting_said(x["table"], x["key"], x["value"], x["unset"])} in {f.name}'
                x['note'] = '; '.join(filter(None, (note, _branch_said(x['table'], x['key']))))
                if x['note']:
                    out += f' ({x["note"]})'
                if row['has_device']:
                    out += f'. This device keeps its own ({CF.toml_value(row["device"])})'
                x['got'] = (None if row['has_device'] else _setting_now(x['table'], x['key'], f.name)) or \
                    {'ok': True, 'code': 0, 'out': out, 'argv': []}
    for x in batch:
        x['got'] = x['got'] or last[(x['table'], x['key'])]['got']


ACTIONS.update({'pitch_no': pitch_no, 'need_chat': need_chat, 'rename_chat': rename_chat,
                'setting_device': setting_device, 'setting_reset': setting_reset, 'setting_project': setting_project,
                'settings_save': settings_save})


def plan_repo_setup(target: str = '') -> dict:
    """F460: Settings > Plan's "Share the plan between machines": `plan repo-setup [target]` for this project.
    {'ok', 'lines'}: the lines it says (the last one is what the other machine runs), or the reason it cannot."""
    from agent_runner import config as CF
    from agent_runner import plan_repo_setup as PRS
    try:
        with _SETTING_LOCK:
            return {'ok': True, 'lines': PRS.setup(CF.Config(S.ROOT), target.strip() or None)}
    except SystemExit as e:
        return {'ok': False, 'lines': [str(e.code or 'repo-setup failed')]}
