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
    at = [body.index(s) for s in ("['now','Now'", "['upnext','Up next'", "['landed','Landed'", "['parked','Parked'")]
    eq('Run log' in body, False, 'no Run log section')
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
    check('S.workJump===k' in WORK and 'aria-current' in WORK, 'UX1: the pressed jump pill is marked')
    css = (Path(__file__).parent.parent / 'agent_runner' / 'page' / '040-plan.css').read_text()
    bar = re.search(r'\.workjump\{[^}]*\}', css).group(0)
    chip = re.search(r'\.workjump \.chip\{[^}]*\}', css).group(0)
    check('background:transparent' in bar and 'padding:0' in bar, 'F517: the jump bar paints no band')
    check('background:var(--bg)' in chip and 'border:1px solid' in chip, 'F517: each pill has its own solid background')


def test_releases_in_up_next_and_scroll_spy() -> None:
    """BUG3: no Releases section or chip; the marked chip follows scroll; a jump lands below the sticky bar."""
    body = WORK[WORK.index('function workHTML'):]
    eq("'Releases'" in body or 'pastrel' in WORK, False, 'no Releases section')
    check("document.addEventListener('scroll'" in WORK and 'function workSpy' in WORK, 'the marked chip follows scroll')
    check('workBarBottom(b,bar)' in WORK, 'a jump lands below the bar where it sticks')


if __name__ == '__main__':
    raise SystemExit(report([test_order, test_up_next, test_folds_and_jump, test_releases_in_up_next_and_scroll_spy]))
