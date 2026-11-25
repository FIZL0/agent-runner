"""B809c: under Needs you, a control session's filed question shows what explains it, on its card and in its popup.

    python3 tests/test_needs_explained.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from _check import check, eq, report
from _web import in_tmp, logic_js
from agent_runner import web as W
from test_web_home import NEED_DRIVER

NONE: dict = {k: [] for k in ('lead', 'steps', 'expect', 'notes', 'shots')}
TEXT = ('## The concept\n\nThe page is **ready**, see `a.py`. It has two parts:\n1. Install, as [the page](https://claude.ai/artifact/a_b_c) says\n'
        '2. Close\n   on its own\n\nMore at https://example.com/x_(y).')
TITLE = 'Control session 23 asked the person: "Build it?"'


def row(text: str = TEXT, **detail) -> dict:
    return {'id': 'F435', 'label': 'DECIDE', 'age': '5m', 'ask': 'Build it?', 'title': TITLE,
            'detail': {**NONE, 'said': 'Choose', 'where': '', 'title': TITLE, 'summary': 'Build it?', 'question': 'Build it?',
                       'text': text, 'session': 'Cells', 'project': 'proj', **detail}}


def body(text: str, on: bool = False) -> str:
    return logic_js([['needBody', row(text), '', '', on]])[0]


def test_card(tmp: Path) -> None:
    card, plain, bare, project = logic_js([['needTap', r] for r in (
        row(), row(''), {**row(), 'detail': {**NONE, **{k: v for k, v in row()['detail'].items() if k not in ('text', 'session', 'project')}}},
        row(session=''))])
    check('</b><span class="small">Cells · proj</span><span class="askdo">The page is ready, see <code>a.py</code>.</span><span class="small">Press' in card,
          'the session and project, then the first sentence', card)
    check('asked the person' not in card, 'not the task\'s words', card)
    check('<span class="small">proj</span>' in project, 'a session with no name: the project', project)
    for h in (plain, bare):
        check('<span class="small">Control session 23 asked the person: &quot;Build it?&quot;</span><span class="small">Press' in h, 'without a text: as it was', h)
    firsts = {'Use e.g. Redis here. Then go.': 'Use e.g. Redis here.', 'Do [this](https://a.b/c.d) now. Next.': 'Do this now.',
              '- **One:** it opens. Two.\n- b': 'One: it opens.', 'Version 1.2 is out\n\nMore': 'Version 1.2 is out', '## Only this': 'Only this',
              '| a | b |\n|---|---|\n\nAfter it.': 'After it.', 'See <b> first. Then': 'See &lt;b&gt; first.'}
    for (t, want), got in zip(firsts.items(), logic_js([['needTap', row(t)] for t in firsts])):
        check(f'<span class="askdo">{want}</span>' in got, f'the first sentence of {t!r}', got)


def test_popup(tmp: Path) -> None:
    h = body(TEXT)
    check(h.startswith('<div class="explain"><h3>The concept</h3><p>The page is <b>ready</b>, see <code>a.py</code>. It has two parts:</p><ol><li value="1">'),
          'formatted, at the top', h)
    check('<a href="https://claude.ai/artifact/a_b_c" target="_blank" rel="noopener noreferrer">the page</a>' in h, 'a link opens', h)
    check('<li value="2">Close on its own</li></ol>' in h, 'an item\'s second line is its own', h)
    check('>https://example.com/x_(y)</a>.</p>' in h, 'a bare address too, without the full stop', h)
    check('data-askfold' not in h, 'a short one has no fold', h)
    check('<script' not in body('<script>x</script> [a](javascript:alert(1)) `<b>`'), 'no markup of its own')
    check('href="javascript' not in body('[a](javascript:alert(1))'), 'only web links')
    check('onx=' not in body('[a](https://x/"onx="1) https://x/"onx="1').replace('&quot;onx=', ''), 'an address stays in its quotes')
    check('<code>**a** https://x.y</code>' in body('`**a** https://x.y`'), 'code is not read again')
    check('<pre><code>a &lt; b\n\n- c</code></pre>' in body('```js\na < b\n\n- c\n```'), 'a code block as it is')
    check('<table><tr><th>a</th><th>b</th></tr><tr><td>1</td><td><b>2</b></td></tr></table>' in body('| a | b |\n|---|:-:|\n| 1 | **2** |'), 'a table')
    check('<li value="1">a</li><li value="2">b</li></ol>' in body('1. a\n\n2. b'), 'one list over an empty line')
    check('<p>The look</p>' in body('![The look](shots/a.png)'), 'a picture is its caption: it is under Pictures')
    eq(logic_js([['needBody', {**row(''), 'detail': {**row('')['detail'], 'text': t}}, ''] for t in ('', None)]), ['', ''], 'none: as it was')
    shots = logic_js([['needBody', row(shots=[]), '']])[0]
    check('Pictures' not in shots, 'no pictures, no heading', shots)


def test_fold(tmp: Path) -> None:
    long = 'First words here. ' + 'It goes on and on. ' * 60 + '\n\nThe **last** words.'
    shut, opened = body(long), body(long, True)
    check('First words' in shut and 'aria-expanded="false"' in shut and 'last' not in shut, 'a long one is folded', shut)
    check('aria-expanded="true"' in opened and 'data-k="fold:ask:text"' in opened and '<b>last</b>' in opened, 'and opens', opened)
    words = logic_js([['needBody', row(long.replace('**', '')), '', '', True]])[0]
    eq(words.count('It goes on and on.'), 60, 'nothing is lost or said twice')
    listed = body('Intro words.\n\n' + '\n'.join(f'{i}. ' + 'word ' * 20 for i in range(1, 21)), True)
    eq([f'<li value="{i}">' in listed for i in range(1, 21)], [True] * 20, 'a list cut by the fold keeps its numbers')


def test_full_task(tmp: Path) -> None:
    """The popup's real code: no Full task where the explanation is, and the fold's press opens the rest."""
    if not shutil.which('node'):
        print('  (no node here: the popup script test is skipped)')
        return
    shot = {'src': 'asks/F435/explained-1.png', 'path': '/x', 'caption': 'Phone'}
    needs = [row('A start. ' + 'More words. ' * 80, shots=[shot]), {**row(''), 'id': 'F436'}]
    drive = NEED_DRIVER.split('const S = env.S, out')[0] + r"""
(async () => {
  const wait = () => new Promise(r => setTimeout(r, 10)), out = {};
  press('[data-needopen]', {needopen: 'F435'}, false); await wait(); out.shut = el.h;
  press('[data-askfold]', {askfold: 'text'}); out.open = el.h;
  press('[data-needopen]', {needopen: 'F436'}, false); await wait(); out.plain = el.h;
  console.log(JSON.stringify(out)); process.exit(0);
})();
"""
    (tmp / 'driver.js').write_text(drive, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE), json.dumps(needs), '[]'], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node draws the popup', r.stderr[-1500:])
    if r.returncode:
        return
    out = json.loads(r.stdout)
    check('Cells · proj' in out['shut'] and 'asked the person' not in out['shut'], 'the subtitle', out['shut'])
    check('Full task' not in out['shut'] and 'data-shot="0"' in out['shut'], 'no Full task; its pictures', out['shut'])
    check(out['open'].count('More words.') == 80 > out['shut'].count('More words.'), 'the fold opens the rest', out['open'])
    check('Full task' in out['plain'] and 'asked the person' in out['plain'] and 'class="explain"' not in out['plain'], 'without a text: as it was', out['plain'])


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(f) for f in (test_card, test_popup, test_fold, test_full_task)]))
