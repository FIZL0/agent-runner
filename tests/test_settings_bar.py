"""F202b: the Settings page's bar: changes collect, Save writes them all, each to its home, and Undo puts the earlier
values back (`ui_model_settings.settings_save`, agent_runner/page/062-settings.logic.js and 122-settings.js).

    python3 tests/test_settings_bar.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tomllib
from pathlib import Path
from unittest import mock

from _check import check, eq, git, report
from _web import fake_repo, in_tmp, post

from agent_runner import config as CF  # noqa: E402
from agent_runner import state as S  # noqa: E402
from agent_runner import ui_model as U  # noqa: E402
from agent_runner import web as W  # noqa: E402

MINE = '# my laptop\n[run]\nweekly_max = 70  # mine\n'
PROJ = '# ours\n[run]\nslots = 4  # four\n'


def project(tmp: Path) -> tuple[Path, Path, Path]:
    repo = fake_repo(tmp)
    toml, local = repo / 'runner.toml', repo / 'runner.local.toml'
    toml.write_text(PROJ, encoding='utf-8')
    (repo / '.gitignore').write_text('.runner/\nrunner.local.toml\n', encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'settings')
    local.write_text(MINE, encoding='utf-8')
    return repo, toml, local


def put(table: str, key: str, side: str, value=None, **o) -> dict:
    return {'table': table, 'key': key, 'side': side, **({} if o.get('unset') else {'value': value}), **o}


def back(was: list[dict]) -> list[dict]:
    """The page's `undoChanges`."""
    return [put(x['table'], x['key'], x['side'], x['was']['value'], **({} if x['was']['has'] else {'unset': True}), expect=x['now'])
            for x in was]


def commits(repo: Path) -> int:
    return int(subprocess.run(['git', 'rev-list', '--count', 'HEAD'], cwd=repo, capture_output=True, text=True).stdout)


def test_save_and_undo(tmp: Path) -> None:
    repo, toml, local = project(tmp)
    before = commits(repo)
    mine, ours = local.read_text(encoding='utf-8'), toml.read_text(encoding='utf-8')
    r = U.settings_save([put('run', 'slots', 'project', 6), put('run', 'weekly_max', 'device', 80),
                         put('ui', 'chat_quiet', 'device', '2h'), put('git', 'land_edited', 'project', 'wip')])
    eq((r['ok'], r['bad'], r['out']), (True, [], '4 settings saved'), 'all are saved')
    got = lambda f: tomllib.loads(f.read_text(encoding='utf-8'))  # noqa: E731
    eq((got(toml)['run'], got(toml)['git']), ({'slots': 6}, {'land_edited': 'wip'}), 'those for everyone in runner.toml')
    eq((got(local)['run'], got(local)['ui']), ({'weekly_max': 80}, {'chat_quiet': '2h'}), 'those of this device in runner.local.toml')
    eq(commits(repo), before + 1, 'those for everyone are one commit')
    eq({(x['key'], x['was']['has'], x['was']['value'], x['now']['value']) for x in r['was']},
       {('slots', True, 4, 6), ('weekly_max', True, 70, 80), ('chat_quiet', False, None, '2h'), ('land_edited', False, None, 'wip')},
       'the earlier values come back, unset ones too')
    u = U.settings_save(json.loads(json.dumps(back(r['was']))))
    eq((u['ok'], u['bad']), (True, []), 'Undo')
    eq((got(toml)['run'], got(local)['run']), ({'slots': 4}, {'weekly_max': 70}), 'puts the earlier values back')
    check('land_edited' not in toml.read_text(encoding='utf-8') and 'chat_quiet' not in local.read_text(encoding='utf-8'),
          'and takes out those that were unset')
    check('# ours' in toml.read_text(encoding='utf-8') and '# mine' in local.read_text(encoding='utf-8'), 'comments stay', (mine, ours))
    one = U.settings_save([put('run', 'slots', 'project', 5)])
    check('slots = 5 in runner.toml' in one['out'], 'one alone says what it is', one)
    eq(one['say'], '', 'nothing more to say')
    with mock.patch.object(U, '_setting_push', lambda: 'saved here, not pushed: no'):
        check('not pushed: no' in U.settings_save([put('run', 'slots', 'project', 8)])['say'], 'a failed push is said')
    U.settings_save([put('run', 'slots', 'project', 5)])
    eq(U.settings_save([put('run', 'slots', 'project', 5)])['was'], [], 'a save that changes nothing has nothing to undo')


def test_refused(tmp: Path) -> None:
    repo, toml, local = project(tmp)
    r = U.settings_save([put('run', 'slots', 'project', 'four'), put('run', 'weekly_max', 'device', 80), put('run', 'nokey', 'device', 1),
                         put('run', 'web', 'nowhere', True), put('ui', 'theme', 'device', 'pink')])
    eq((r['ok'], [b['key'] for b in r['bad']]), (False, ['slots', 'nokey', 'web', 'theme']), 'what is not taken, each')
    check(all(b['why'] for b in r['bad']), 'with why', r['bad'])
    eq([x['key'] for x in r['was']], ['weekly_max'], 'the other one is saved, and can be undone')
    eq(toml.read_text(encoding='utf-8'), PROJ, 'a refused one changes nothing')
    for x in ([], {}, ['x'], None):
        eq(U.settings_save(x)['ok'], False, f'{x!r} is no list of changes')
    was = U.settings_save([put('run', 'slots', 'project', 6), put('run', 'weekly_max', 'device', 90)])['was']
    U.setting_device('run', 'weekly_max', 95)
    u = U.settings_save(back(was))
    eq([(b['key'], b['changed']) for b in u['bad']], [('weekly_max', True)], 'Undo leaves one that was changed since')
    eq(tomllib.loads(toml.read_text(encoding='utf-8'))['run'], {'slots': 4}, 'and puts the other back')
    S.LANDING.acquire()
    try:
        with mock.patch.object(U, 'SETTING_WAIT', 0.1):
            r = U.settings_save([put('run', 'slots', 'project', 7), put('run', 'weekly_max', 'device', 60)])
    finally:
        S.LANDING.release()
    eq(([b['key'] for b in r['bad']], [x['key'] for x in r['was']]), (['slots'], ['weekly_max']), 'a merge is landing: that one waits, the other is saved')


def test_together(tmp: Path) -> None:
    """Changes that need each other: a model of a provider that the same Save allows."""
    repo, toml, local = project(tmp)
    save = [put('models', 'code', 'device', 'ollama:llama3'), put('models', 'local', 'device', True)]
    r = U.settings_save(save)
    eq((r['ok'], len(r['was'])), (True, 2), 'a model and the switch that allows it, in any order')
    eq(U.settings_save(back(r['was']))['ok'], True, 'and both back')
    eq(local.read_text(encoding='utf-8').count('ollama'), 0, 'the model is gone')


def test_run_up(tmp: Path) -> None:
    """The run is told of a new slot count; a save it did not take is still a save, so Undo has it. Restart only for a
    key that needs the next run."""
    repo, toml, local = project(tmp)
    U.settings_start()
    ran = []
    with mock.patch.object(U, 'RUN', [lambda argv: (ran.append(argv), (0, 'ok'))[1]]), mock.patch.object(S, 'run_up', lambda: True):
        was = U.settings_save([put('run', 'slots', 'device', 2), put('run', 'weekly_max', 'device', 80)])['was']
        eq((ran, U.settings()['waits']), ([['slots', '2']], []), 'slots: told; nothing waits for a restart')
        r = U.settings_save([put('run', 'web_port', 'device', 8999)])
        eq(U.settings()['waits'], ['run.web_port'], 'a key of the next run waits')
        U.settings_save(back(r['was']))
        eq(U.settings()['waits'], [], 'and not once it is undone')
        U.settings_save(back(was))
        eq(ran[-1], ['slots', '4'], 'Undo tells the run too')
    with mock.patch.object(U, 'RUN', [lambda argv: (1, 'busy')]), mock.patch.object(S, 'run_up', lambda: True):
        r = U.settings_save([put('run', 'slots', 'device', 3)])
    eq((r['ok'], r['warn'], len(r['was'])), (True, True, 1), 'saved, but the run did not take it: said, and it can be undone')
    check('did not take it' in r['out'], 'in those words', r)


def test_route(tmp: Path) -> None:
    repo, toml, local = project(tmp)
    token = W.web_token()
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {})
    try:
        r = post(f'http://127.0.0.1:{srv.server_address[1]}/act?t={token}',
                 {'name': 'settings_save', 'args': {'changes': [put('run', 'weekly_max', 'device', 81)]}})[1]
        eq((r['ok'], r['was'][0]['was']['value']), (True, 70), 'the page saves through /act')
    finally:
        srv.stop()


DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const set = JSON.parse(require('fs').readFileSync(process.argv[3], 'utf8'));
const logic = page.split('<script id="logic">')[1].split('</script>')[0].replace(/if\(typeof module[^\n]*/, '');
const slice = (a, b) => page.slice(page.indexOf(a), page.indexOf(b, page.indexOf(a)));
const kept = {}, store = {get: k => kept[k] || '', set: (k, v) => { kept[k] = v }}, HKEY = '', HOME_PAGE = false;
const S = {f: {}, ob: [], setOpen: {}, set, snap: {}, view: 'settings', setTab: 'device'}, esc = t => String(t).replace(/&/g, '&amp;').replace(/"/g, '&quot;');  // F462: rows edit this device's file
const I = {chev: '', x: 'x'}, card = t => `<div>${t}</div>`, emptyCard = card, obCards = () => '', controlOf = () => null, foldIn = (k, t) => t, SHEETS = {};
const bar = {}, $ = () => bar, setHTML = (el, h) => { el.h = h }, loopsInStep = () => {}, obState = x => x.state, obBtns = () => '[btns]', OB = {};
const document = {activeElement: null, querySelector: () => null, querySelectorAll: () => [], addEventListener: () => {}}, ears = {}, addEventListener = (k, f) => { ears[k] = f };
let said = [], sent = [], draws = 0;
const render = () => { draws++ }, toast = (t, bad) => said.push([t, !!bad]), closeSheet = () => { S.sheet = '' };
const obChange = f => { S.ob = f(S.ob) }, outbox = (name, args, more) => { const it = {cid: 'c' + sent.length, name, args, state: 'sending', ...more}; sent.push(it); S.ob.push(it) };
const loadSettings = () => Promise.resolve().then(draftTidy), settle = () => new Promise(r => setTimeout(r, 5));
eval(logic + slice('const settingId=', '/* --- F202b') + slice('/* --- F202b', '</script>').split('\n/* --- ')[0] + `
const K = id => { const [t, k] = id.split('.'); return set.tables.find(x => x.table === t).keys.find(x => x.key === k) };
const text = h => h.replace(/<[^>]*>/g, ' ').replace(/ +/g, ' ').trim(), now = () => { setBarDraw(); return bar.hidden ? '' : text(bar.h) };
const type = (f, value) => { S.f[f] = value; draftType({dataset: {f, now: ''}, value}) };
const out = {};
(async () => {
  out.start = now();
  stepSetting('run.slots', 1); out.one = [now(), sent.length, settingNow(settingOf('run.slots'), 'device', true)];
  type('set:device:run.weekly_max', '85'); out.two = [now(), bar.h.includes('data-setall'), bar.h.includes('data-setdrop')];
  out.row = text(settingRow(settingOf('run.slots'), {}));
  stepSetting('run.slots', -1); out.backed = now();          // what it was: no change
  stepSetting('run.slots', 2);
  out.keptText = kept['ar-setbar'];
  // leaving the page keeps them: another page of this browser
  S.draft = {}; S.f = {}; draftLoad(); draftFields(); out.reload = [now(), S.f['set:device:run.weekly_max']];
  S.view = 'home'; out.away = now(); S.view = 'settings';
  settingsUndrop(); out.dropped = [now(), kept['ar-setbar'], {...S.f}, sent.length];
  // Save
  stepSetting('run.slots', 2); type('set:device:run.web_port', 'x'); settingsSave(); out.badWord = [said.pop(), sent.length, now()];
  draftDrop('set:device:run.web_port'); type('set:device:run.weekly_max', '85'); resetSetting('run.slots', 'project'); out.reset = [now(), text(settingRow(settingOf('run.slots'), {}))];
  draftDrop('set:project:run.slots');
  settingsSave(); out.sent = [sent[0].name, sent[0].args, now(), settingNow(settingOf('run.slots'), 'device', true)];
  stepSetting('run.slots', -2); out.during = [now(), S.draft['set:device:run.slots'].text]; draftTidy(); out.during.push(now()); settingsUndrop();
  S.f = {}; out.going = settingNow(settingOf('run.slots'), 'device', true);  // a reload while it goes
  const was = [{table: 'run', key: 'slots', side: 'device', was: {has: true, value: 4}, now: {has: true, value: 6}}, {table: 'run', key: 'weekly_max', side: 'device', was: {has: false, value: null}, now: {has: true, value: 85}}];
  S.ob = []; Object.assign(K('run.slots'), {has_device: true, device: 6, value: 6});
  const heard = said.length; settingsDone(sent[0], {ok: true, out: '2 settings saved', was, bad: []}); await settle();
  out.saved = [now(), said.length - heard, bar.h.includes('data-setundo"') || bar.h.includes('data-setundo>'), bar.h.includes('data-setundox')];
  stepSetting('run.slots', 1); out.over = now(); settingsUndrop(); out.offer = now();
  settingsUndo(); out.undo = [sent[1].args.changes, now()];
  S.ob = [];
  settingsDone(sent[1], {ok: false, out: 'a merge is landing', bad: [{table: 'run', key: 'slots', side: 'device', why: 'a merge is landing'}, {table: 'run', key: 'weekly_max', side: 'device', why: 'changed', changed: true}]}); await settle();
  out.undoLeft = [now(), said.pop()]; setUndoClose(); out.closed = [now(), kept['ar-setbar']];
  S.setUndo = was; kept['ar-setbar'] = JSON.stringify({draft: {}, undo: was});  // an older offer
  // what Save did not take is in the bar again, with why
  stepSetting('run.slots', 2); settingsSave(); S.ob = [{...sent[2], state: 'failed'}];
  settingsDone(sent[2], {ok: false, out: 'HTTP'}); await settle();
  out.failed = [now(), S.ob.length, text(settingRow(settingOf('run.slots'), {}))];
  S.ob = [{setbar: 'save', n: 1, state: 'failed', args: {changes: []}}]; out.both = now(); S.ob = [];
  settingsUndrop(); out.noOld = now();
  // an older run: the outbox keeps it
  S.ob = [{setbar: 'save', n: 1, state: 'failed', args: {changes: []}}]; out.old = now(); S.ob = [];
  // two controls of one key, the kinds rows
  saveKinds('build', 'haiku'); out.kinds = now(); saveKinds('light', 'haiku'); out.kinds2 = [now(), Object.keys(S.draft)];
  out.kindsRow = settingsHTML().split('Not saved yet').length - 1; settingsUndrop();
  // More…: the other home, and a dependent row
  S.sheet = 'setting'; S.f['set:project:run.slots'] = '7'; saveSetting('run.slots', 'project'); out.more = [now(), S.sheet, text(settingRow(settingOf('run.slots'), {}))]; settingsUndrop();
  const hid = settingsHTML().includes('set:run.approve_wait'); draftSet('run.approve', settingSide(K('run.approve')), {text: 'true'}); out.parent = [hid, settingsHTML().includes('set:run.approve_wait')];
  // another tab saved them
  S.draft = {}; ears.storage({key: 'ar-setbar'}); kept['ar-setbar'] = ''; ears.storage({key: 'ar-setbar'}); await settle(); out.tab = now();
  console.log(JSON.stringify(out));
})();`);
"""


def test_bar(tmp: Path) -> None:
    page = W.page_html().decode()
    for part in ('id="setbar"', 'setBarDraw();  // F202b', 'data-setall', 'data-setundox', "outbox('settings_save'"):
        check(part in page, f'the page has {part}')
    check("outbox(side==='device'?'setting_device'" not in page, 'no row saves by itself')
    if not shutil.which('node'):
        return
    repo, toml, local = project(tmp)
    local.write_text('', encoding='utf-8')
    (tmp / 'set.json').write_text(json.dumps(CF.settings_snapshot(repo)), encoding='utf-8')
    (tmp / 'bar.js').write_text(DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'bar.js'), str(W.PAGE), str(tmp / 'set.json')], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node changes settings', r.stderr[-1500:])
    if r.returncode:
        return
    o = json.loads(r.stdout)
    eq(o['start'], '', 'no change: no bar')
    eq(o['one'], ['1 change not saved Undo Save', 0, '5'], 'a change is counted, shown on its row, and nothing is sent')
    eq(o['two'], ['2 changes not saved Undo Save', True, True], 'a typed one too')
    check('Not saved yet' in o['row'], 'its row says so', o['row'])
    eq(o['backed'], '1 change not saved Undo Save', 'set to what it was: not a change')
    eq(o['reload'], ['2 changes not saved Undo Save', '85'], 'leaving the page keeps them')
    eq(o['away'], '', 'the bar is in Settings only')
    eq(o['dropped'], ['', '', {}, 0], 'Undo drops them, and sends nothing')
    eq((o['badWord'][0][1], o['badWord'][1], o['badWord'][2]), (True, 0, '2 changes not saved Undo Save'), 'words that are no value: said, nothing is sent')
    check('Not saved yet: reset for everyone' in o['reset'][1] and o['reset'][0].startswith('3 '), 'a Reset is a change too', o['reset'])
    eq(o['sent'][:2], ['settings_save', {'changes': [{'table': 'run', 'key': 'slots', 'side': 'device', 'value': 6},
                                                     {'table': 'run', 'key': 'weekly_max', 'side': 'device', 'value': 85}]}], 'Save sends them all at once')
    eq(o['sent'][2:], ['Saving 2 changes: sending', '6'], 'and the bar and the row show it')
    eq(o['during'], ['1 change not saved Undo Save', '4', '1 change not saved Undo Save'], 'set back while the Save goes: a change of its own')
    eq((o['both'], o['noOld']), ('Saving 1 change: failed [btns] 1 change not saved Undo Save', ''), 'a Save an older run refused stays beside new changes; a failed Save brings no older Undo back')
    eq(o['going'], '6', 'over a reload too')
    eq(o['saved'], ['2 changes saved Undo x', 0, True, True], 'then it offers Undo, with no toast over it')
    eq((o['over'], o['offer']), ('1 change not saved Undo Save', '2 changes saved Undo x'), 'a new change comes first; Undo drops it and the offer is there again')
    eq(o['undo'], [[{'table': 'run', 'key': 'slots', 'side': 'device', 'value': 4, 'expect': {'has': True, 'value': 6}},
                    {'table': 'run', 'key': 'weekly_max', 'side': 'device', 'unset': True, 'expect': {'has': True, 'value': 85}}],
                   'Undoing 2 changes: sending'], 'Undo sends the earlier values, unset ones included')
    eq(o['undoLeft'], ['1 change saved Undo x', ['a merge is landing', True]], 'one that was not put back can be tried again, not one changed since')
    eq(o['closed'], ['', ''], 'the offer closes')
    eq(o['failed'][:2], ['1 change not saved Undo Save', 0], 'a Save that failed is in the bar again')
    check('Not saved yet. HTTP' in o['failed'][2], 'with why, on its row', o['failed'])
    check('[btns]' in o['old'], "one an older run refused has the outbox's buttons", o['old'])
    eq((o['kinds'], o['kinds2']), ('1 change not saved Undo Save', ['2 changes not saved Undo Save', ['set:device:models.kinds']]), 'the kinds rows count as rows, one key, in the file of the tab in view')
    eq(o['kindsRow'], 2, 'both rows say so')
    check(o['more'][0].startswith('1 change') and not o['more'][1] and 'Not saved yet: 7 for everyone' in o['more'][2], "More…'s other home goes to the bar", o['more'])
    eq(o['parent'], [False, True], 'a row that depends on a changed one shows')
    eq(o['tab'], '', 'another tab that saved them empties the bar here')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_save_and_undo), in_tmp(test_refused), in_tmp(test_together), in_tmp(test_run_up),
                             in_tmp(test_route), in_tmp(test_bar)]))
