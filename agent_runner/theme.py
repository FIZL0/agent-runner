"""F69: the Run page's themes, one table for the terminal page (tui.py) and the web page (web.py).

`[ui] theme` picks one:
    ryha      black ground, red #ef4444 accent, the ryha-omarchy palette (the default)
    omarchy   the current Omarchy theme's colors.toml (~/.config/omarchy/current/theme/colors.toml), any key it
              lacks taken from ryha; ryha whole when the file is missing
    terminal  the terminal's own 16 ANSI colours and background, so it follows any terminal theme. The web page
              cannot read a terminal's colours, so there it draws the Omarchy theme's 16 colours (what Omarchy
              sets the terminal to), else ryha's
    light     a white ground for daylight

A theme is a dict of tokens: colour name -> '#rrggbb' (the terminal theme: an ANSI index 0-15, -1 the
terminal's own foreground or background), plus 'mode' ('dark' or 'light'). `resolve(name)` gives the hex form
both pages draw with; `curses_colour` maps a token onto what a terminal can show.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

NAMES = ('ryha', 'omarchy', 'terminal', 'light')
DEFAULT = 'ryha'
TOKENS = ('bg', 'fg', 'dim', 'line', 'sel', 'selfg', 'raise', 'cur', 'accent', 'red', 'green', 'yellow', 'blue',
          'bblue', 'magenta', 'cyan', 'key')

# ryha-omarchy's ANSI 0-15
RYHA_ANSI = ['#000000', '#ef4444', '#22c55e', '#f59e0b', '#3b82f6', '#a855f7', '#06b6d4', '#e5e5e5',
             '#737373', '#f87171', '#4ade80', '#fbbf24', '#60a5fa', '#c084fc', '#22d3ee', '#ffffff']

THEMES: dict[str, dict] = {
    # sel: the focused row; cur: the selected row of a panel that isn't focused (terminal); raise: a raised
    # surface on the web (an input, that row there); key: a key on the hint line
    'ryha': {'mode': 'dark', 'bg': '#000000', 'fg': '#e5e5e5', 'dim': '#737373', 'line': '#3a3a3a',
             'sel': '#7f1d1d', 'selfg': '#f5f5f5', 'raise': '#0d0d0d', 'cur': '#262626', 'accent': '#ef4444',
             'red': '#ef4444', 'green': '#22c55e', 'yellow': '#f59e0b', 'blue': '#3b82f6', 'bblue': '#60a5fa',
             'magenta': '#a855f7', 'cyan': '#06b6d4', 'key': '#ffffff'},
    'light': {'mode': 'light', 'bg': '#ffffff', 'fg': '#171717', 'dim': '#737373', 'line': '#d4d4d4',
              'sel': '#fee2e2', 'selfg': '#171717', 'raise': '#f5f5f5', 'cur': '#e5e5e5', 'accent': '#dc2626',
              'red': '#dc2626', 'green': '#16a34a', 'yellow': '#b45309', 'blue': '#2563eb', 'bblue': '#2563eb',
              'magenta': '#9333ea', 'cyan': '#0891b2', 'key': '#000000'},
    # ANSI indices: -1 is the terminal's own foreground / background
    'terminal': {'mode': 'dark', 'bg': -1, 'fg': -1, 'dim': 8, 'line': 8, 'sel': 1, 'selfg': 15, 'raise': 0,
                 'cur': 8, 'accent': 1, 'red': 1, 'green': 2, 'yellow': 3, 'blue': 4, 'bblue': 12, 'magenta': 5,
                 'cyan': 6, 'key': 15},
}

HEX = re.compile(r'^#[0-9a-fA-F]{6}$')
# an omarchy colors.toml's names for each ANSI colour, old style (red, bright_red) and new (color1, color9)
ANSI_NAMES = ['black', 'red', 'green', 'yellow', 'blue', 'magenta', 'cyan', 'white']


def omarchy_file() -> Path:
    """The current Omarchy theme's colours (OMARCHY_COLORS names another file, for a test or another layout)."""
    return Path(os.environ.get('OMARCHY_COLORS') or Path.home() / '.config/omarchy/current/theme/colors.toml')


def read_colors(path: Path | None = None) -> dict[str, str]:
    """colors.toml as {key: '#rrggbb'} (lower case); {} when it is missing or unreadable."""
    import tomllib
    try:
        with open(path or omarchy_file(), 'rb') as fh:
            raw = tomllib.load(fh)
    except (OSError, ValueError):
        return {}
    out = {k: v.lower() for k, v in raw.items() if isinstance(v, str) and HEX.match(v)}
    if isinstance(raw.get('mode'), str):
        out['mode'] = raw['mode']
    return out


def rgb(h: str) -> tuple[int, int, int]:
    return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)


def mix(a: str, b: str, t: float) -> str:
    """`t` of the way from colour a to colour b."""
    return '#' + ''.join(f'{round(x + (y - x) * t):02x}' for x, y in zip(rgb(a), rgb(b)))


def ansi_palette(c: dict[str, str]) -> list[str]:
    """The 16 ANSI colours a colors.toml gives (color0…color15, or red/bright_red…), ryha's where it is silent."""
    out = []
    for i in range(16):
        base = ANSI_NAMES[i % 8]
        named = c.get(f'bright_{base}') if i >= 8 else c.get(base)
        out.append(c.get(f'color{i}') or named or RYHA_ANSI[i])
    return out


def from_colors(c: dict[str, str]) -> dict:
    """An Omarchy colors.toml as a theme; whatever it lacks comes from ryha."""
    if not c:
        return dict(THEMES['ryha'])
    r, p = THEMES['ryha'], ansi_palette(c)
    bg, fg = c.get('background', p[0]), c.get('foreground', p[7])
    mode = c.get('mode') if c.get('mode') in ('dark', 'light') else \
        ('light' if sum(rgb(bg)) > 3 * 128 else 'dark')
    accent = c.get('accent') or c.get('color1') or c.get('red') or r['accent']
    return {
        'mode': mode, 'bg': bg, 'fg': fg,
        'dim': c.get('muted') or c.get('dark_foreground') or c.get('color8') or mix(bg, fg, 0.45),
        'line': c.get('lighter_background') or mix(bg, fg, 0.2),
        'sel': c.get('selection_background') or c.get('selection') or mix(bg, accent, 0.45),
        'selfg': c.get('selection_foreground') or c.get('bright_foreground') or fg,
        'raise': mix(bg, fg, 0.05), 'cur': mix(bg, fg, 0.15), 'accent': accent,
        'red': p[1], 'green': p[2], 'yellow': p[3], 'blue': p[4], 'bblue': p[12], 'magenta': p[5], 'cyan': p[6],
        'key': c.get('bright_foreground') or c.get('color15') or fg,
    }


def terminal_hex(c: dict[str, str]) -> dict:
    """The terminal theme drawn in hex (the web page): its ANSI indices on the Omarchy palette, else ryha's."""
    p = ansi_palette(c)
    own = {'bg': c.get('background', p[0]), 'fg': c.get('foreground', p[7])}
    return {'mode': 'dark', **{k: (own[k] if v == -1 else p[v]) for k, v in THEMES['terminal'].items()
                               if k != 'mode'}}


def checked(name) -> str:
    """`name` when it is a theme, else the default."""
    return name if name in NAMES else DEFAULT


def configured() -> str:
    """The `[ui] theme` of the project the run reads ('ryha' when there is none)."""
    try:
        from agent_runner import state as S
        return checked(S.C.raw.get('ui', {}).get('theme', DEFAULT))
    except Exception:  # noqa: BLE001 - no project initialised: the default
        return DEFAULT


def get(name: str, colors: Path | None = None) -> dict:
    """Theme `name` as tokens: hex, or for 'terminal' ANSI indices (what a terminal draws)."""
    name = checked(name)
    if name == 'omarchy':
        return from_colors(read_colors(colors))
    return dict(THEMES[name])


def resolve(name: str, colors: Path | None = None) -> dict:
    """Theme `name` in hex, as the web page draws it."""
    name = checked(name)
    if name == 'terminal':
        return terminal_hex(read_colors(colors))
    return get(name, colors)


def all_resolved(colors: Path | None = None) -> dict[str, dict]:
    """Every theme in hex (the web page's picker)."""
    return {n: resolve(n, colors) for n in NAMES}


# --- terminal colours ----------------------------------------------------------------------------------------

CUBE = (0, 95, 135, 175, 215, 255)
BASIC8 = [(0, 0, 0), (205, 0, 0), (0, 205, 0), (205, 205, 0), (0, 0, 238), (205, 0, 205), (0, 205, 205),
          (229, 229, 229)]
NEUTRAL = ('bg', 'fg', 'dim', 'line', 'selfg', 'raise', 'cur', 'key')


def xterm256(h: str) -> int:
    """The nearest of the xterm 256 colours (the 6x6x6 cube or the grey ramp) to `h`."""
    c = rgb(h)
    near = lambda v: min(range(6), key=lambda i: abs(CUBE[i] - v))  # noqa: E731
    idx = [near(v) for v in c]
    cube = tuple(CUBE[i] for i in idx)
    g = min(23, max(0, round((sum(c) / 3 - 8) / 10)))
    grey = (8 + 10 * g,) * 3
    dist = lambda a: sum((x - y) ** 2 for x, y in zip(a, c))  # noqa: E731
    return 16 + 36 * idx[0] + 6 * idx[1] + idx[2] if dist(cube) <= dist(grey) else 232 + g


def basic8(token: str, h: str, mode: str) -> int:
    """One of the 8 basic colours for `token`: neutral tokens by the theme's mode (white on black, or black on
    white), every other the basic colour nearest it."""
    if token in NEUTRAL:
        dark = {'bg': 0, 'raise': 0, 'cur': 0}
        return (dark.get(token, 7)) if mode != 'light' else (7 if token in dark else 0)
    name = 'blue' if token == 'bblue' else token
    if name in ANSI_NAMES:  # red, green, …: the basic colour of that name
        return ANSI_NAMES.index(name)
    c = rgb(h)
    return min(range(8), key=lambda i: sum((x - y) ** 2 for x, y in zip(BASIC8[i], c)))


def curses_colour(theme: dict, token: str, colours: int) -> int:
    """`token` of `theme` as a curses colour number on a terminal with `colours` colours. ANSI indices (the
    terminal theme) are the terminal's own; 8 colours take index 8-15 down to 0-7."""
    v = theme[token]
    if isinstance(v, int):
        return v if v < colours or v < 0 else v % 8
    return xterm256(v) if colours >= 256 else basic8(token, v, theme.get('mode', 'dark'))
