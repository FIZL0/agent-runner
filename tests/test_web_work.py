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
    at = [body.index(s) for s in ('controlsCard()', "sec('Now'", "sec('Up next'", "histSec('Landed'", "workFold('parked'", "workFold('log'")]
    eq(at, sorted(at), 'in timeline order')
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


if __name__ == '__main__':
    raise SystemExit(report([test_order, test_up_next]))
