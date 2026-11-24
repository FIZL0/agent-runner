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
            f = CF.save_local_setting(S.ROOT, table, key, value, unset)
    except (ValueError, OSError) as e:
        return {'ok': False, 'code': 2, 'out': str(e), 'argv': []}
    if bad := _setting_now(table, key, f.name):
        return bad
    return {'ok': True, 'code': 0, 'out': f'{_setting_said(table, key, value, unset)} in {f.name}', 'argv': []}


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
    return None if r['ok'] else {**r, 'out': f'saved in {name}, but the run did not take it: {r["out"]}'}


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
    if problem := '' if unset else CF.setting_check(S.ROOT, table, key, value):
        return {'ok': False, 'code': 2, 'out': problem, 'argv': []}
    mine = {'table': table, 'key': key, 'value': value, 'unset': unset, 'got': None}
    with _SETTING_LOCK:
        _SETTING_QUEUE.append(mine)
    with _SETTING_WRITE:
        if mine['got'] is None:  # not taken along by the save before it
            time.sleep(SETTING_SETTLE)
            batch: list[dict] = []
            try:
                _save_project(batch)
            except Exception as e:  # noqa: BLE001 - every save of the batch hears of it
                for x in batch:
                    x['got'] = x['got'] or {'ok': False, 'code': 1, 'out': f'not saved: {e}', 'argv': []}
    return mine['got'] or {'ok': False, 'code': 1, 'out': 'not saved', 'argv': []}


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

    def edit(data: bytes) -> tuple[bytes, str]:
        done = []
        for x in last.values():
            try:
                data = CF.setting_edit(data, x['table'], x['key'], x['value'], x['unset'], f.name)
            except ValueError as e:
                bad(x, str(e))
                continue
            done.append(x)
        said = '; '.join(_setting_said(x['table'], x['key'], x['value'], x['unset']) for x in done)
        short = said if len(said) <= 100 else ', '.join(f'[{x["table"]}] {x["key"]}' for x in done)
        return data, f'settings: {short}'
    try:
        ok, note = plansync.commit_file(S.ROOT, f, edit, S.default_branch())
        if ok and not note:  # committed; the push in LANDING too: it may rebase the main checkout when no run is up
            note = _setting_push()
    except SystemExit as e:  # [git] master_branch is not out in the main checkout
        ok, note = False, f'{e}. Nothing was changed'
    finally:
        S.LANDING.release()
    if not ok:
        for x in last.values():
            if x['got'] is None:
                bad(x, note)
    else:
        if note == 'nothing to change':
            note = ''
        for x in last.values():
            if x['got'] is None:
                row = _setting_row(x['table'], x['key'])
                out = f'{_setting_said(x["table"], x["key"], x["value"], x["unset"])} in {f.name}'
                if note:
                    out += f' ({note})'
                if row['has_device']:
                    out += f'. This device keeps its own ({CF.toml_value(row["device"])})'
                x['got'] = (None if row['has_device'] else _setting_now(x['table'], x['key'], f.name)) or \
                    {'ok': True, 'code': 0, 'out': out, 'argv': []}
    for x in batch:
        x['got'] = x['got'] or last[(x['table'], x['key'])]['got']


ACTIONS.update({'pitch_no': pitch_no, 'need_chat': need_chat, 'rename_chat': rename_chat,
                'setting_device': setting_device, 'setting_reset': setting_reset, 'setting_project': setting_project})
