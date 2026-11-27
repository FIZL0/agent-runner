"""F462: Settings' two tabs, Project (runner.toml) and This device (runner.local.toml), and the marker of an override.

    python3 tests/test_settings_tabs.py
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _check import check, eq, report  # noqa: E402
from agent_runner import config as CF  # noqa: E402
from agent_runner import web as W  # noqa: E402
from _web import fake_repo, in_tmp  # noqa: E402

DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const set = JSON.parse(require('fs').readFileSync(process.argv[3], 'utf8'));
const logic = page.split('<script id="logic">')[1].split('</script>')[0].replace(/if\(typeof module[^\n]*/, '');
const slice = (a, b) => page.slice(page.indexOf(a), page.indexOf(b));
const S = {f: {}, ob: [], setOpen: {}, set, snap: {}}, esc = t => String(t).replace(/&/g, '&amp;').replace(/"/g, '&quot;'), I = {chev: '', x: ''};
const card = t => `<div>${t}</div>`, emptyCard = card, obCards = () => '', controlOf = () => null, foldIn = (k, t) => t, SHEETS = {};
const document = {querySelector: () => null, querySelectorAll: () => []}, render = () => {};
let saved = [];
const draftSet = (id, side, d) => saved.push([side, id, d.text]);
eval(logic + slice('const settingId=', 'function saveSetting(') + slice('/* the stepper:', 'NOPE').split('\n}\n')[0] + '\n}\n' + `
const out = {};
const draw = (tab, changed) => { S.setTab = tab; S.setChanged = changed; return settingsHTML() };
out.project = draw('project', false); out.device = draw('device', false);
out.pc = draw('project', true); out.dc = draw('device', true);
S.setTab = 'project'; stepSetting('run.slots', 1); S.setTab = 'device'; stepSetting('run.slots', 1); out.saved = saved;
out.sides = [draftSides({a: {side: 'project'}, b: {side: 'device'}}), draftSides({a: {side: 'device'}})];
console.log(JSON.stringify(out));`);
"""


def test_tabs(tmp: Path) -> None:
    repo = fake_repo(tmp)
    (repo / 'runner.toml').write_text('[run]\nslots = 4\nweekly_max = 70\n', encoding='utf-8')
    (repo / 'runner.local.toml').write_text('[run]\nslots = 6\n', encoding='utf-8')
    page = W.PAGE.read_text(encoding='utf-8')
    for part in ('data-settab', '.settabs', '.setover', "q('[data-settab]')"):
        check(part in page, f'the page has {part}')
    if not shutil.which('node'):
        return
    (tmp / 'set.json').write_text(json.dumps(CF.settings_snapshot(repo)), encoding='utf-8')
    (tmp / 'tabs.js').write_text(DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'tabs.js'), str(W.PAGE), str(tmp / 'set.json')], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node draws Settings', r.stderr[-1500:])
    if r.returncode:
        return
    o = json.loads(r.stdout)
    slots = lambda h: re.search(r'data-k="set:run\.slots".*?<b>(\d+)</b>', h, re.S)[1]  # noqa: E731
    check('This device · 1' in o['project'] and 'aria-pressed="true">Project' in o['project'], 'Project is in view; This device counts its own')
    eq(slots(o['project']), '4', 'Project shows runner.toml’s value')
    check('This device: 6' in o['project'] and 'data-settab="device" data-id="run.slots"' in o['project'], 'with the marker of this device’s')
    eq(slots(o['device']), '6', 'This device shows its own')
    check('the project has 4' in o['device'] and 'data-setreset="device" data-id="run.slots"' in o['device'], 'with what the project has, and Reset')
    check("Same as the project" in o['device'], 'a row without its own says so')
    check('data-setopen="#file"' in o['project'] and 'data-setopen="#file"' not in o['device'], 'Project file is under Project only')
    eq(re.search(r'Changed (\d+)', o['pc'])[1], '2', 'Changed on Project: what runner.toml sets')
    eq(re.search(r'Changed (\d+)', o['dc'])[1], '1', 'Changed on This device: its own values')
    check('set:run.weekly_max' in o['pc'] and 'set:run.weekly_max' not in o['dc'], 'each tab lists its own file’s')
    eq(o['saved'], [['project', 'run.slots', '5'], ['device', 'run.slots', '7']], 'a row edits the file of the tab in view')
    eq(o['sides'], ['1 project, 1 this device', ''], 'the bar names both files only when both have changes')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_tabs)]))
