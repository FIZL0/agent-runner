#!/usr/bin/env python3
"""F473: lazyrunner, the run page's keyboard-first layout, and its UI settings (themes).

    python3 tests/test_lazy.py        (no network; under a second)

The hard rule: lazyrunner is only a CSS layout and a key layer over the page's own sidebar and views, so the
Standard and Lazyrunner layouts always show the same panels. These checks fail when they could differ.
"""
from __future__ import annotations

import json
import re
import subprocess
import shutil
from pathlib import Path

from _check import check, eq, has, report

from agent_runner import theme  # noqa: E402
from agent_runner import web as W  # noqa: E402

PAGE = Path(W.__file__).with_name('page')
JS = (PAGE / '189-lazy.js').read_text(encoding='utf-8')
CSS = (PAGE / '189-lazy.css').read_text(encoding='utf-8')


def nav_views() -> list[str]:
    text = (PAGE / '030-shared.logic.js').read_text(encoding='utf-8')
    m = re.search(r"const NAV=(\[.*?\]\]);", text)
    return [v for v, _ in json.loads(m.group(1).replace("'", '"'))]


def lazy_panels() -> list[tuple[str, str]]:
    m = re.search(r"const LAZY_PANELS=(\[.*?\]\]);", JS)
    return [(k, v) for k, v, _ in json.loads(m.group(1).replace("'", '"'))]


def test_panel_sets_match():
    nav, panels = nav_views(), lazy_panels()
    eq([k for k, _ in panels], ['1', '2', '3', '4', '5'], 'F473: five panels, keys 1 to 5')
    for _, v in panels:
        check(v == 'sessions' or v in nav, f'F473: panel {v} is a view the Standard sidebar has', f'NAV: {nav}')
    # the layout only places the sidebar's rows: it hides none of them, so both layouts have the same panels
    for rule in re.findall(r'([^{}]+)\{([^{}]*)\}', CSS):
        sel, body = rule
        if re.search(r'display:none|visibility:hidden', body):
            check('sidein' not in sel and '.ni' not in sel and 'data-view' not in sel and 'thread' not in sel,
                  f'F473: lazyrunner hides no panel ({sel.strip()})', body)
    for _, v in panels:
        if v != 'sessions':
            has(CSS, rf'\.ni\[data-view="{v}"\]', f'F473: the layout numbers panel {v}')
    # no view, panel or renderer of its own: no *HTML function, no new view, no body or sidebar drawn
    check(not re.search(r'function \w*HTML|S\.view=|\$\(\'(body|sidein|side)\'\)\.innerHTML|setHTML\(', JS),
          'F473: lazyrunner draws no view or panel of its own')


def test_themes_css():
    css = theme.page_css()
    for n in theme.NAMES:
        has(css, rf':root\[data-ui="{n}"\]\{{--bg:#[0-9a-fA-F]{{6}};', f'F473: theme {n} as the page\'s colours')
    has(css, r'data-ui="light"\][^}]*color-scheme:light', 'F473: the light theme says light')
    page = W.page_html().decode('utf-8')
    check('/*UI_THEMES*/' not in page and ':root[data-ui="ryha"]' in page, 'F473: the page is served with the themes')
    check('id="keybar"' in page, 'F473: the page has the key bar')
    for name, _ in re.findall(r"\['(\w*)','([^']*)'\]", JS.split('const UI_THEMES=')[1].split(';')[0]):
        check(name == '' or name in theme.NAMES, f'F473: the picker\'s theme {name!r} is theme.py\'s')


def test_js_parses():
    if not shutil.which('node'):
        return
    r = subprocess.run(['node', '--check', str(PAGE / '189-lazy.js')], capture_output=True, text=True)
    check(r.returncode == 0, 'F473: 189-lazy.js parses', r.stderr)


def main() -> int:
    return report([test_panel_sets_match, test_themes_css, test_js_parses])


if __name__ == '__main__':
    import sys
    sys.exit(main())
