"""B872: Manage releases switched off in Settings: the snapshot says so at once (no restart), and Work shows no New release."""
import json
import re
import shutil
import subprocess
from pathlib import Path

from _check import check, eq, report
from _web import fake_repo, in_tmp

from agent_runner import autorelease, state as S  # noqa: E402
from agent_runner import ui_model as U  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


@in_tmp
def test_saved_off_read_at_once(tmp: Path) -> None:
    """A save of [run] releases = false in runner.local.toml is seen by the next snapshot of the same process."""
    repo = fake_repo(tmp)
    check(autorelease.releases_on() and U.snapshot(up=False, links={})['manage_releases'], 'on before the save')
    (repo / 'runner.local.toml').write_text('[run]\nreleases = false\n', encoding='utf-8')
    s = U.snapshot(up=False, links={})
    eq((s['manage_releases'], s['release_acts'], s['releases']), (False, [], []), 'off at once, with nothing of releases')
    (repo / 'runner.local.toml').write_text('[run]\nreleases = true\n', encoding='utf-8')
    check(U.snapshot(up=False, links={})['manage_releases'], 'back on')


def test_work_no_new_release() -> None:
    """Work's New release card is empty with manage_releases false."""
    if not shutil.which('node'):
        print('  (no node here: not run)')
        return
    chats = (ROOT / 'agent_runner' / 'page' / '090-chats.js').read_text(encoding='utf-8')
    shared = (ROOT / 'agent_runner' / 'page' / '030-shared.logic.js').read_text(encoding='utf-8')
    fn = chats[chats.index('function newReleaseCard('):chats.index('/* F426f')]
    on = re.search(r'const releasesOn=.*?;\n', shared).group(0)
    js = ("const obCards=()=>'',obActs=()=>false,working_=()=>[],controlOf=k=>({key:k,label:k}),ctlBusy=()=>false,"
          "card=h=>h,esc=s=>s,S={snap:{manage_releases:false,release_acts:['release_now']}};" + on + fn +
          "const off=newReleaseCard();S.snap.manage_releases=true;console.log(JSON.stringify([off,newReleaseCard()]))")
    r = subprocess.run(['node', '-e', js], capture_output=True, text=True, timeout=60)
    off, onc = json.loads(r.stdout)
    eq(off, '', 'no New release with releases off')
    check('New release' in onc and 'release_now' in onc, 'there with releases on', onc)


if __name__ == '__main__':
    raise SystemExit(report([test_saved_off_read_at_once, test_work_no_new_release]))
