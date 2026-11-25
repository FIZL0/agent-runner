"""B809c: under Needs you, a control session's filed question shows what explains it, on its card and in its popup.
F445a: an item plays its videos.

    python3 tests/test_needs_explained.py
"""
from __future__ import annotations

import http.client
import json
import os
import shutil
import subprocess
from pathlib import Path
from unittest import mock

from _check import check, eq, report
from _web import fake_repo, in_tmp, logic_js
from agent_runner import need_detail as N
from agent_runner import web as W
from test_tui import SNAP, page as tui_page
from test_web_home import NEED_DRIVER
from test_web_sheet import DOM

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
    check('<p>One<br>two</p>' in body('> One\n> two'), 'a quote without its marks')
    check('<a href="https://a.b/c.png"' in body('![Look](https://a.b/c.png)'), 'a picture on the web is a link')
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

    p = 'It goes on. ' * 70
    shut = body('## Head\n\n' + p)
    check('<h3>Head</h3><p>It goes' in shut and 'aria-expanded="false"' in shut, 'a heading has words under it', shut)
    for t in ('word ' * 200, '```\n' + 'code line\n' * 100 + '```', '| a |\n|---|\n' + '| row words |\n' * 80):
        shut, opened = body(t), body(t, True)
        check('aria-expanded="false"' in shut and len(shut) < len(opened) * .8, f'folded: {t[:12]!r}', shut)
        w = next(x for x in ('code line', 'row words', 'word') if x in t)
        eq(opened.count(w), t.count(w), f'all of it is there: {t[:12]!r}')


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


MP4 = b'\0\0\0\x20ftypisom' + bytes(range(256)) * 8
WEBM = b'\x1aE\xdf\xa3\x9fB\x86\x81\x01B\xf7\x81\x01B\xf2\x81\x04B\xf3\x81\x08B\x82\x84webm' + b'0' * 50


def ask_videos(repo: Path) -> Path:
    """Puts videos, and what is none, beside D3's ask file; the notes dir."""
    notes = repo / '.runner'
    for d in ('asks/D3', 'uploads'):
        (notes / d).mkdir(parents=True, exist_ok=True)
    for f, data in {'asks/D3/a.mp4': MP4, 'uploads/b.WEBM': WEBM, 'asks/D3/p.png': b'\x89PNG\r\n\x1a\nfake', 'secret.mp4': MP4,
                    'asks/D3/text.mp4': b'not a video at all', 'asks/D3/png.mp4': b'\x89PNG\r\n\x1a\nfake', 'asks/D3/mp4.png': MP4,
                    'asks/D3/a.mov': MP4, 'asks/D3/mp4.webm': MP4, 'asks/D3/mkv.webm': WEBM.replace(b'webm', b'mkv!')}.items():
        (notes / f).write_bytes(data)
    return notes


def test_video_types(tmp: Path) -> None:
    """F445a: an ask file's shots may be mp4 and webm videos, with a picture's folder and size checks."""
    notes = ask_videos(fake_repo(tmp))
    files = ['D3/a.mp4', 'D3/p.png', 'uploads/b.WEBM', str(notes / 'asks/D3/a.mp4'), 'D3/text.mp4', 'D3/png.mp4', 'D3/mp4.png', 'D3/a.mov',
             'D3/mkv.webm', 'D3/mp4.webm', '../secret.mp4', str(notes / 'secret.mp4'), 'D3/gone.mp4']
    (notes / 'asks' / 'D3.json').write_text(json.dumps({'shots': [{'file': f, 'caption': 'c'} for f in files]}), encoding='utf-8')
    eq([(s['src'], s.get('video')) for s in N.asks_file('D3')['shots']],
       [('asks/D3/a.mp4', True), ('asks/D3/p.png', None), ('uploads/b.WEBM', True), ('asks/D3/a.mp4', True)], 'only real ones, in the two folders')
    if os.name == 'posix':
        (notes / 'asks' / 'out.mp4').symlink_to(notes / 'secret.mp4')
        eq(N.shot_file('asks/out.mp4'), None, 'no way out by a link')
    with mock.patch.object(N, 'SHOT_MAX', len(MP4) - 1):
        eq(N.shot_file('asks/D3/a.mp4'), None, 'none over the size limit')
    eq(N.named_shots('see uploads/b.WEBM'), [], 'a task\'s text names pictures only')


def test_range(tmp: Path) -> None:
    eq([W.byte_range(r, 100) for r in ('bytes=0-1', 'bytes=10-', 'bytes=-5', 'bytes=-500', 'bytes=90-500', 'bytes=100-', 'bytes=100-200', 'bytes=-0')],
       [(0, 2), (10, 100), (95, 100), (0, 100), (90, 100), (0, 0), (0, 0), (0, 0)], 'a part, or none of it')
    eq([W.byte_range(r, 100) for r in ('', 'bytes=-', 'bytes=5-2', 'bytes=200-150', 'bytes=0-1,4-5', 'lines=0-1', 'bytes=0-' + '9' * 5000)], [None] * 7, 'the whole')
    ask_videos(fake_repo(tmp))
    token = W.web_token()
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {})
    conn = http.client.HTTPConnection('127.0.0.1', srv.server_address[1], timeout=10)  # one connection: a wrong length would spoil the next

    def ask(src: str, rng: str = '', t: str = token) -> tuple:
        conn.request('GET', f'/shot/{src}?t={t}', headers={'Range': rng} if rng else {})
        r = conn.getresponse()
        return r.status, r.read(), r.getheader('Content-Range'), r.getheader('Content-Type'), r.getheader('Accept-Ranges')
    try:
        n, mp4 = len(MP4), 'video/mp4'
        eq(ask('asks/D3/a.mp4'), (200, MP4, None, mp4, 'bytes'), 'the whole')
        eq(ask('asks/D3/a.mp4', 'bytes=0-1'), (206, MP4[:2], f'bytes 0-1/{n}', mp4, 'bytes'), 'as an iPhone asks first')
        eq(ask('asks/D3/a.mp4', 'bytes=500-')[:3], (206, MP4[500:], f'bytes 500-{n - 1}/{n}'), 'a seek')
        eq(ask('asks/D3/a.mp4', 'bytes=-7')[:3], (206, MP4[-7:], f'bytes {n - 7}-{n - 1}/{n}'), 'its end')
        eq(ask('asks/D3/a.mp4', f'bytes={n}-')[:3], (416, b'', f'bytes */{n}'), 'past it')
        eq(ask('asks/D3/a.mp4', 'bytes=0-1,5-6')[:2], (200, MP4), 'several parts: the whole')
        eq(ask('uploads/b.WEBM', 'bytes=0-3')[::3], (206, 'video/webm'), 'a webm')
        eq(ask('asks/D3/p.png')[::3], (200, 'image/png'), 'a picture as before')
        for f in ('secret.mp4', 'asks/..%2fsecret.mp4', 'asks/%2e%2e/secret.mp4', 'asks/D3/text.mp4', 'asks/D3/png.mp4', 'concepts/a.mp4'):
            eq(ask(f, 'bytes=0-1')[0], 404, f'{f} is refused')
        eq(ask('asks/D3/a.mp4', 'bytes=0-1', 'no')[0], 403, 'only with the token')
    finally:
        conn.close()
        srv.stop()


VIDEO = {'src': 'asks/D3/a.mp4', 'path': '/n/asks/D3/a.mp4', 'caption': 'The "band"', 'video': True}


def test_video_popup(tmp: Path) -> None:
    pic = {'src': 'asks/p.png', 'path': '/x', 'caption': 'Phone'}
    if not shutil.which('node'):
        print('  (no node here: the video script test is skipped)')
        return
    drive = NEED_DRIVER.split('const S = env.S, out')[0] + "press('[data-needopen]', {needopen: 'F435'}, false); console.log(JSON.stringify(el.h)); process.exit(0)"
    (tmp / 'driver.js').write_text(drive, encoding='utf-8')
    htmls = []
    for shots in ([VIDEO, pic], [VIDEO]):
        r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE), json.dumps([row('', shots=shots)]), '[]'], capture_output=True, text=True, timeout=60)
        check(r.returncode == 0, 'node draws the popup', r.stderr[-1500:])
        htmls.append(json.loads(r.stdout or '""'))
    both, only = htmls
    check('<h3>Video</h3><video class="shotvideo" data-video controls playsinline preload="metadata" src="shot/asks/D3/a.mp4?t=T#t=0.001"' in both and
          '</video><p class="small">The &quot;band&quot;</p>' in both, 'it plays in place, its caption under it', both)
    check('data-shot="1"' in both and 'data-shot="0"' not in both, 'a picture opens as its own place in the list', both)
    check('Pictures' not in only, 'no pictures, no heading', only)
    lines = [''.join(t for t, _ in x).strip() for x in tui_page(SNAP).need_lines(row('', shots=[VIDEO, pic]), 80)]
    at = lines.index('Videos')
    eq(lines[at + 1:at + 3], [VIDEO['path'], VIDEO['caption']], 'the terminal UI: where it is and its caption')
    check(lines.index('Pictures') > at and lines.count('/x') == 1, 'apart from the pictures', lines)


REDRAW_DRIVER = DOM + r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const slice = (a, b) => page.slice(page.indexOf(a), page.indexOf(b, page.indexOf(a)));
const S = {sheet: 'need'}, setHTML = (el, h) => { if (el._h === h) return false; el._h = h; el.innerHTML = h; return true };
const document = {activeElement: null, createElement: () => ({content: new Node(11, '#fragment'), set innerHTML(h) { this.content.innerHTML = h }})};
const sheetHTML = new Function('S', 'document', 'setHTML', slice('function sheetHTML(', '/* F189b: a press in the sheet') + 'return sheetHTML')(S, document, setHTML);
const draw = (age, note, src = 'a.mp4') => `<h2>T</h2><div class="small">${age}</div><div class="askbody"><p>${note}</p><section><h3>Video</h3><video data-video="" src="${src}"></video></section></div>`;
const text = n => n.childNodes.length ? n.childNodes.map(text).join('|') : n.data || '';
const out = [], el = root, video = () => el.querySelectorAll('[data-video]')[0];
sheetHTML(el, draw('1m', 'one')); const was = video(), gone = [];
was.remove = () => gone.push(1);
sheetHTML(el, draw('2m', 'one')); out.push(video() === was);
sheetHTML(el, draw('3m', 'two')); out.push(video() === was, gone.length, text(el), sheetHTML(el, draw('3m', 'two')));
delete was.remove; sheetHTML(el, draw('3m', 'two', 'b.mp4')); out.push(video().getAttribute('src'));
console.log(JSON.stringify(out));
"""


def test_video_redraw(tmp: Path) -> None:
    """A redraw leaves the video's element where it is: one drawn again would stop and start over."""
    if not shutil.which('node'):
        print('  (no node here: the video redraw test is skipped)')
        return
    (tmp / 'redraw.js').write_text(REDRAW_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'redraw.js'), str(W.PAGE)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node redraws the sheet', r.stderr[-1500:])
    if r.returncode == 0:
        eq(json.loads(r.stdout), [True, True, 0, 'T|3m|two|Video|', False, 'b.mp4'], 'the same element, in new words; another video is drawn')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(f) for f in (test_card, test_popup, test_fold, test_full_task, test_video_types, test_range, test_video_popup, test_video_redraw)]))
