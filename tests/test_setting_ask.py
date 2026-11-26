"""C55b: an unset setting asked on Settings (run.auto_audit): shown, answered On, answered Off, gone after.

    python3 tests/test_setting_ask.py
"""
from __future__ import annotations

import json
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
const S = {f: {}, ob: [], setOpen: {}, set, snap: {}, draft: {}}, esc = t => String(t).replace(/&/g, '&amp;').replace(/"/g, '&quot;');
let saved = [];
const draftSet = (id, side, d) => { saved.push(['draft', side, id, d.text]); S.draft[`set:${side}:${id}`] = d };
const settingsSave = () => saved.push(['save']), render = () => {};
eval(logic + slice('const settingId=', 'function saveSetting(').split('/* C55b')[0] + slice('/* C55b: the unset', 'function settingsHTML(') + `
const out = {}, all = settingsAll(S.set);
out.shown = askHTML(all);
answerAsk('run.auto_audit', 'on'); out.on = saved.splice(0);
out.drafted = askHTML(all);
S.draft = {}; answerAsk('run.auto_audit', 'off'); out.off = saved.splice(0);
const k = settingOf('run.auto_audit'); k.has_project = true; k.project = false;
out.saved = askHTML(all);
console.log(JSON.stringify(out));`);
"""


def test_ask(tmp: Path) -> None:
    repo = fake_repo(tmp)
    page = W.PAGE.read_text(encoding='utf-8')
    check('data-setask' in page and '.setask' in page, 'the page has the question')
    if not shutil.which('node'):
        return
    (tmp / 'set.json').write_text(json.dumps(CF.settings_snapshot(repo)), encoding='utf-8')
    (tmp / 'ask.js').write_text(DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'ask.js'), str(W.PAGE), str(tmp / 'set.json')], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node draws the question', r.stderr[-1500:])
    if r.returncode:
        return
    o = json.loads(r.stdout)
    check('Audit by itself' in o['shown'] and 'data-setask="on"' in o['shown'] and 'data-setask="off"' in o['shown'], 'shown while unset')
    eq(o['on'], [['draft', 'project', 'run.auto_audit', '{"every":50}'], ['save']], 'On is saved by the usual Save')
    eq(o['off'], [['draft', 'project', 'run.auto_audit', 'false'], ['save']], 'Off is saved by the usual Save')
    eq(o['drafted'], '', 'gone once answered')
    eq(o['saved'], '', 'gone once saved')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_ask)]))
