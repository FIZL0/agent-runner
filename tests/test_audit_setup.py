"""F422: Settings has the switch, every N and the model.

    python3 tests/test_audit_setup.py        (no network; node draws the rows)
"""
from __future__ import annotations

import builtins
import contextlib
import io
import json
import re
import shutil
import subprocess
from pathlib import Path
from unittest import mock

from _check import check, eq, git, has, report
from _web import fake_repo, in_tmp, logic_js

from agent_runner import audit, config as CF, setting_words as SW, settings_live, setup as S, state, ui_model as U, web as W


ROW_DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const set = JSON.parse(require('fs').readFileSync(process.argv[3], 'utf8'));
const logic = page.split('<script id="logic">')[1].split('</script>')[0].replace(/if\(typeof module[^\n]*/, '');
const slice = (a, b) => page.slice(page.indexOf(a), page.indexOf(b));
const k = set.tables.find(t => t.table === 'run').keys.find(x => x.key === 'auto_audit');
const S = {f: {}, ob: [], setOpen: {}, set}, esc = t => String(t).replace(/"/g, '&quot;');
let drawn = 0, saved = [];
const document = {querySelectorAll: () => []}, render = () => { drawn++ }, draftSet = (id, side, d) => saved.push([id, side, d.text]);
eval(logic + slice('const settingId=', 'const resetBtn=') + `
const row = text => { S.f = {}; k.value = JSON.parse(text); k.has_project = k.value !== false; k.project = k.value; return settingRow({...k, table: 'run'}, {}) };
const out = {rows: {}};
for (const t of ['false', 'true', '{"every":50}', '{"every":30}']) out.rows[t] = row(t);
row('false');
const move = (part, x, now) => savePart({value: String(x), checked: x, dataset: {id: 'run.auto_audit', side: 'project', setpart: part, ...(now ? {now: ''} : {})}});
move('on', true, true); move('every', 100, true); move('on', false, true); out.saved = saved; saved = [];
row('true'); move('every', 25, true); out.fromTrue = saved; saved = []; drawn = 0;
row('false'); move('on', true, false); out.sheet = [saved.length, drawn, S.f['set:project:run.auto_audit']];
console.log(JSON.stringify(out));`);
"""


def test_settings(tmp: Path):
    print('Settings: the switch, every N and the model, together')
    on = SW.parts('run', 'auto_audit')
    eq(on['on']['every'], audit.EVERY, 'the switch turns on the default count')
    names = [SW.name(*at.split('.')) for at in SW.WORDS]
    i = names.index('Audit by itself')
    eq(names[i:i + 3], ['Audit by itself', 'Audit model', 'Token cap per audit'], 'in one place')
    eq({SW.group(*at) for at in (('run', 'auto_audit'), ('models', 'audit'), ('run', 'audit_tokens'))}, {'work'}, 'one group')
    eq({SW.home(*at) for at in (('run', 'auto_audit'), ('models', 'audit'))}, {SW.EVERYONE}, 'for everyone')
    eq(SW.parent('models', 'audit'), '', 'the model shows with the switch off: an audit added by hand uses it')
    repo = fake_repo(tmp)
    snap = CF.settings_snapshot(repo)
    rows = {(t['table'], k['key']): k for t in snap['tables'] for k in t['keys']}
    k = rows['run', 'auto_audit']
    eq((k['parts'], rows['models', 'audit']['value']), (on, 'opus'), 'the Settings route carries them')
    if not shutil.which('node'):
        return
    cases = [('false', 'Off', 0), ('true', 'Every 50 tasks', 50), ('{"every":30}', 'Every 30 tasks', 30)]
    for text, says, n in cases:
        eq(logic_js([['settingSays', k, text], ['partsNow', text, k]]), [says, {'every': n, 'idle': False}], says)
    eq(logic_js([['partOptions', k, '{"every":30}'], ['partSet', '{"every":30}', 'on', False, k], ['partSet', 'false', 'on', True, k],
                 ['partSet', 'true', 'every', 25, k]]),
       [[[25, '25 tasks'], [30, '30 tasks'], [50, '50 tasks'], [100, '100 tasks']], 'false', '{"every":50}', '{"every":25}'],
       'no Off in the list: the switch is that')
    (tmp / 'set.json').write_text(json.dumps(snap), encoding='utf-8')
    (tmp / 'row.js').write_text(ROW_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'row.js'), str(W.PAGE), str(tmp / 'set.json')], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node draws the row', r.stderr[-900:])
    if r.returncode:
        return
    o = json.loads(r.stdout)
    for text, n in (('false', 0), ('true', 50), ('{"every":50}', 50), ('{"every":30}', 30)):
        html = o['rows'][text]
        eq(bool(re.search(r'role="switch"[^>]*data-setpart="on"[^>]* checked>', html)), bool(n), f'{text}: the switch')
        eq(re.findall(r'<option value="(\d+)" selected', html), [str(n)] if n else [], f'{text}: every N shows while it is on')
        check('setpart="idle"' not in html, f'{text}: no When idle')
    at = ['run.auto_audit', 'project']
    eq(o['saved'], [[*at, '{"every":50}'], [*at, '{"every":100}'], [*at, 'false']], 'each change is in the draft')
    eq(o['fromTrue'], [[*at, '{"every":25}']], 'from true')
    eq(o['sheet'], [0, 1, '{"every":50}'], 'in More… it waits for the button, and the count shows at once')


def test_save(tmp: Path):
    print('Save writes the switch, the count and the model for everyone, as one commit')
    repo = fake_repo(tmp)
    (repo / 'runner.toml').write_text('[run]\nslots = 2\n\n[git]\npush = false\n', encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'settings')
    CF._cfg.cache_clear()
    state.init(repo)
    n = int(git(repo, 'rev-list', '--count', 'HEAD'))
    got = U.settings_save([{'table': 'run', 'key': 'auto_audit', 'side': 'project', 'value': {'every': 25}},
                           {'table': 'models', 'key': 'audit', 'side': 'project', 'value': 'sonnet'}])
    check(got['ok'], 'saved', got)
    c = CF.Config(repo)
    eq((c.run['auto_audit'], c.models['audit']), ({'every': 25}, 'sonnet'), 'both are in runner.toml')
    eq((int(git(repo, 'rev-list', '--count', 'HEAD')), git(repo, 'status', '--porcelain')), (n + 1, ''), 'one commit')


def test_live(tmp: Path):
    print('a run that is up takes the switch, the count and the model')
    repo = fake_repo(tmp)
    f = repo / 'runner.toml'
    f.write_text('[run]\nslots = 2\n', encoding='utf-8')
    CF._cfg.cache_clear()
    state.init(repo)
    settings_live.start()
    try:
        with mock.patch.object(settings_live, 'SETTINGS_STILL', 0):
            f.write_text('[run]\nslots = 2\nauto_audit = { every = 25 }\n\n[models]\naudit = "sonnet"\n', encoding='utf-8')
            eq(set(settings_live.read_settings()), {('run', 'auto_audit'), ('models', 'audit')}, 'taken')
            eq((audit.every_of(state.C.run['auto_audit']), audit.model('R1', ['- [ ] **R1** (audit) x'])), (25, 'sonnet'), 'in force')
            f.write_text('[run]\nslots = 2\n', encoding='utf-8')
            settings_live.read_settings()
            eq(audit.every_of(state.C.run['auto_audit']), 0, 'off again')
    finally:
        settings_live.SETTINGS_SEEN[:] = []


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(f) for f in (test_settings, test_save, test_live)]))
