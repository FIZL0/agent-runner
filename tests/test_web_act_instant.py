#!/usr/bin/env python3
"""F508: a person's own act shows on the run page at once, before the run answers; a refused one goes back; the
snapshot after an act comes within 1 s of its answer.

    python3 tests/test_web_act_instant.py
"""
from __future__ import annotations

import json
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _check import check, eq, report  # noqa: E402

from agent_runner import state as S  # noqa: E402
from agent_runner import ui_model as U  # noqa: E402
from agent_runner import web as W  # noqa: E402

# the page's act path in small: outbox() lays the act's change over the snapshot (instAdd), a slow run answers after
# 200 ms, each draw (obHide) asks instKeep what stands. Each act is looked at before the answer and after it.
DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8');
const logic = page.split('<script id="logic">')[1].split('</script>')[0];
const m = new Function(logic.replace(/if\(typeof module[^\n]*/g, '') + ';return {instShow, instKeep, instFx}')();
const base = () => ({queue: [{id: 'F1'}, {id: 'B2'}], needs: [{id: 'F3'}], shelved: [{id: 'F4'}], concepts: [{id: 'K5'}],
  sessions: [{name: 'c1', title: 'Old'}]});
const acts = {
  drop: ['run_control', {key: 'queue_drop', tid: 'B2'}, s => !s.queue.some(q => q.id === 'B2')],
  cancel: ['run_control', {key: 'task_cancel', tid: 'F1'}, s => !s.queue.some(q => q.id === 'F1')],
  park: ['run_control', {key: 'need_drop', tid: 'F3'}, s => !s.needs.length],
  delete: ['run_control', {key: 'shelved_drop', tid: 'F4'}, s => !s.shelved.length],
  quiet: ['run_control', {key: 'concept_drop', tid: 'K5'}, s => !s.concepts.length],
  rename: ['rename_chat', {chat: 'c1', title: 'New'}, s => s.sessions[0].title === 'New'],
  answer: ['answer', {tid: 'F3', text: 'yes'}, s => !s.needs.length && s.queue.length === 2],
};
const wait = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  const out = {};
  for (const [k, [name, args, shows]] of Object.entries(acts)) {
    out[k] = {};
    for (const ok of [true, false]) {
      let raw = base(), snap = raw, inst = [], box = [], snapAt = 0;
      const draw = () => { const r = m.instKeep(inst, box, snapAt, Date.now()); inst = r.keep;
        if (r.failed.length) snap = {...raw}; snap = m.instShow(snap, inst); };
      const fx = m.instFx(name, args); const it = {cid: 'c' + k, state: 'sending'};
      box.push(it); inst.push({cid: it.cid, fx}); snap = m.instShow(snap, [{fx}]);
      const t0 = Date.now();
      const answer = wait(200).then(() => ({ok}));  // the slow run
      draw(); const before = shows(snap) && Date.now() - t0 < 50;
      const j = await answer;
      if (j.ok) box = box.filter(x => x !== it); else it.state = 'failed';
      draw(); const after = shows(snap);
      raw = base(); snapAt = Date.now() - 1; draw();  // a snapshot taken before the act landed: the change stands
      const old = shows(snap);
      out[k][ok ? 'ok' : 'failed'] = {before, after, old, raw: shows(raw)};
    }
  }
  console.log(JSON.stringify(out));
})();
"""


def test_each_act_shows_at_once() -> None:
    if not shutil.which('node'):
        print('  (no node here: the act test is skipped)')
        return
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / 'page.html').write_text(W.PAGE.read_text(encoding='utf-8'), encoding='utf-8')
        (Path(d) / 'd.js').write_text(DRIVER, encoding='utf-8')
        r = subprocess.run(['node', str(Path(d) / 'd.js'), str(Path(d) / 'page.html')], capture_output=True, text=True,
                           timeout=60)
    check(r.returncode == 0, 'node runs', r.stderr[-800:])
    o = json.loads(r.stdout)
    for k, v in o.items():
        eq(v['ok'], {'before': True, 'after': True, 'old': True, 'raw': False}, f'{k}: shows before the answer, stays')
        eq(v['failed'], {'before': True, 'after': False, 'old': False, 'raw': False}, f'{k}: refused, it goes back')


def test_wired() -> None:
    page = W.PAGE.read_text(encoding='utf-8')
    check('instAdd(it.cid,fx||instFx(name,it.args))' in page, 'every outbox act gives its change at once')
    check('function obHide(){\n  if(typeof instNow===\'function\')instNow();' in page, 'each draw lays the standing changes over the snapshot')
    check('S.snapRaw={...S.snap}' in page, 'the snapshot as sent is kept for a refused act')


def test_snapshot_within_1s() -> None:
    count = [0]

    def snap():
        count[0] += 1
        return {'n': count[0]}

    def slow(name, **a):
        time.sleep(0.4)
        return {'ok': True, 'code': 0, 'out': '', 'argv': []}

    with tempfile.TemporaryDirectory() as d, mock.patch.object(S, 'C', mock.Mock(notes=lambda *p: Path(d, *p))), \
            mock.patch.object(W, 'TICK', 30.0), mock.patch.object(U, 'act', slow):
        srv = W.WebServer('tok', 0, '127.0.0.1', snap=snap)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        port = srv.server_address[1]
        got: queue.Queue = queue.Queue()

        def listen():
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/events?t=tok', timeout=20) as r:
                for line in r:
                    if line.startswith(b'data: '):
                        got.put(json.loads(line[6:]))

        threading.Thread(target=listen, daemon=True).start()
        got.get(timeout=5)
        req = urllib.request.Request(f'http://127.0.0.1:{port}/act?t=tok', data=json.dumps({'name': 'x'}).encode(),
                                     headers={'Content-Type': 'application/json'}, method='POST')
        urllib.request.urlopen(req, timeout=10).read()
        try:
            got.get(timeout=1.0)
            check(True, 'a snapshot within 1 s of the act landing')
        except queue.Empty:
            check(False, 'a snapshot within 1 s of the act landing')
        srv.stopped.set()
        srv.shutdown()


if __name__ == '__main__':
    raise SystemExit(report([test_each_act_shows_at_once, test_wired, test_snapshot_within_1s]))
