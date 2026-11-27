"""F476: the run page's Work page (agent_runner/page/145-work.js): Status, Plan and History as one timeline."""
import json
import re
import shutil
import subprocess
from pathlib import Path

from _check import check, eq, report

ROOT = Path(__file__).resolve().parent.parent
WORK = (ROOT / 'agent_runner' / 'page' / '145-work.js').read_text(encoding='utf-8')
NAVJS = (ROOT / 'agent_runner' / 'page' / '030-shared.logic.js').read_text(encoding='utf-8')


def test_order() -> None:
    """The sections stand in timeline order: the run, Now, Up next, Landed, then Parked and Run log folded."""
    body = WORK[WORK.index('function workHTML'):]
    at = [body.index(s) for s in ("['now','Now'", "['upnext','Up next'", "['landed','Landed'", "['parked','Parked'", "['log','Run log'")]
    eq(at, sorted(at), 'in timeline order')
    check(body.index('controlsCard()') < body.index('<div class="worksecs">'), 'the run first')
    check("['plan','Work']" in NAVJS and "['status','Status']" not in NAVJS and "['history','History']" not in NAVJS, 'one NAV item, Work')


def test_up_next() -> None:
    """Up next leaves out what Now shows; a release and the Next release row stay."""
    if not shutil.which('node'):
        print('  (no node here: not run)')
        return
    fn = re.search(r'const workUpNext=.*?;\n', WORK).group(0)
    js = fn + "console.log(JSON.stringify(workUpNext([{id:'F1'},{id:'B2'},{id:'V3',release:{}},{id:'next',placeholder:true}],new Set(['F1','V3','next']))))"
    r = subprocess.run(['node', '-e', js], capture_output=True, text=True, timeout=60)
    eq([q['id'] for q in json.loads(r.stdout)], ['B2', 'V3', 'next'], 'a running task is under Now only')


def test_folds_and_jump() -> None:
    """F487: every section folds (Parked and Run log closed by default) and a jump button opens its section."""
    if not shutil.which('node'):
        print('  (no node here: not run)')
        return
    m = re.search(r'const WORK_OPEN=.*?;\nconst workIsOpen=.*?;\n', WORK, re.S).group(0)
    js = 'const S={workOpen:{now:false}};' + m + "console.log(JSON.stringify(['now','upnext','landed','parked','log'].map(workIsOpen)))"
    r = subprocess.run(['node', '-e', js], capture_output=True, text=True, timeout=60)
    eq(json.loads(r.stdout), [False, True, True, False, False], 'open by default but Parked and Run log; a fold kept')
    check('data-workjump' in WORK and 'class="workjump"' in WORK, 'a jump bar of buttons')


if __name__ == '__main__':
    raise SystemExit(report([test_order, test_up_next, test_folds_and_jump]))
