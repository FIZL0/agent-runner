"""F170: the look of a session the run starts: a Claude Code theme of its own (`<claude dir>/themes/agent-runner.json`)
whose colours are 256-colour slots, which each browser fills from the run page's own light or dark colours
(`LOOKS`, `session_frame`). Nothing else on the machine gets it: only the settings the run gives its sessions name it.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

NAME = 'agent-runner'
SETTING = f'custom:{NAME}'
# bashEditDiffEnabled (F188): no diff under a Bash command that changed a file; Edit's and Write's own stay
CALM = {'spinnerTipsEnabled': False, 'prefersReducedMotion': True, 'bashEditDiffEnabled': False}

# role: (slot for a dark terminal, slot for a light one, the page's dark colour, its light colour). A slot's own colour
# is close to the role's, so a terminal outside the page reads well too. No slot is in both columns for two roles.
ROLES = {
    'text': (255, 233, '#f3f1ea', '#141413'),
    'inverse': (234, 230, '#262624', '#faf9f5'),
    'muted': (247, 241, '#a3a199', '#6b6a64'),
    'subtle': (242, 246, '#8f8d85', '#73726c'),
    'accent': (173, 130, '#d97757', '#a8492c'),
    'accent2': (216, 166, '#e9a48c', '#b5573a'),
    'ok': (108, 64, '#8fb07c', '#47703c'),
    'warn': (179, 94, '#d9a54a', '#8a5a00'),
    'bad': (167, 124, '#e07a66', '#b0412e'),
    'link': (146, 61, '#a9b8d9', '#3f5b94'),
    'violet': (140, 97, '#b8a1d9', '#6d4d9c'),
    'pink': (175, 125, '#d99ab8', '#9c3f6c'),
    'mine': (237, 254, '#3a3936', '#f0eee6'),
    'mine2': (238, 253, '#464541', '#e8e6dc'),
    'empty': (239, 251, '#4a4945', '#dcd9cd'),
    'add': (22, 194, '#2f3d2a', '#dfead8'),
    'add2': (28, 151, '#46603b', '#bcd9ad'),
    'gone': (52, 224, '#4a2c27', '#f5dcd6'),
    'gone2': (88, 217, '#743d33', '#edb8ad'),
}
# F182: the code in a diff, which Claude Code (2.1.331) draws in colours of its own that no theme names, by the theme's
# base. Role: (slots with a dark base, with a light one, the page's dark colour, its light colour). Only the slots of the
# base in use are filled: with a dark base nothing else of Claude Code's is drawn in 231, with a light one 231 is only
# other programs' white, which stays white. With a dark base, other programs' white on
# a strong colour (231 on 160, 25 or 64) still shows light on a light page: minimumContrastRatio turns the dark text back
# (seen in Chromium). A slot `ROLES` has (125, 97, 242, 246) keeps its role's colour, and that ratio lifts it on a row.
CODE = {
    'plain': ((231,), (236,), '#f3f1ea', '#141413'),
    'keyword': ((197, 218), (), '#f7c6d6', '#8a2f5b'),
    'storage': ((81,), (), '#b4dfe4', '#0b5560'),
    'name': ((148,), (31,), '#c9e3a9', '#2c5526'),
    'number': ((141, 183), (), '#dccff2', '#5f3f8c'),
    'string': ((186,), (24,), '#e6cf8f', '#6b4500'),
    'param': ((208, 215), (), '#f5c8a8', '#7c3217'),
    'comment': ((250,), (), '#d2d0c8', '#4b4a46'),
}
# Claude Code's colour names, by role; one left out (its rainbow, its subagents') keeps its stock colour
USES = {
    'text': 'text', 'inverse': 'inverseText clawd_background', 'muted': 'inactive',
    'subtle': 'subtle promptBorder', 'accent': 'claude claudeBlue_FOR_SYSTEM_SPINNER clawd_body briefLabelClaude fastMode',
    'accent2': 'claudeShimmer claudeBlueShimmer_FOR_SYSTEM_SPINNER inactiveShimmer promptBorderShimmer fastModeShimmer',
    'ok': 'success', 'warn': 'warning warningShimmer', 'bad': 'error',
    'link': 'permission permissionShimmer suggestion remember ide background planMode rate_limit_fill briefLabelYou '
            'professionalBlue',
    'violet': 'autoAccept autoAcceptShimmer skill merged effortUltra', 'pink': 'bashBorder',
    'mine': 'userMessageBackground bashMessageBackgroundColor memoryBackgroundColor composerSidebarBackground',
    'mine2': 'userMessageBackgroundHover', 'empty': 'rate_limit_empty selectionBg',
    'add': 'diffAdded diffAddedDimmed', 'add2': 'diffAddedWord', 'gone': 'diffRemoved diffRemovedDimmed',
    'gone2': 'diffRemovedWord',
}
ANSI = {  # a terminal's own 16 colours, for what a session shows of other programs
    'dark': ['#1f1e1d', '#e07a66', '#8fb07c', '#d9a54a', '#a9b8d9', '#b8a1d9', '#7fb5b5', '#d5d3ca',
             '#8f8d85', '#e9a48c', '#a9c998', '#e6bf78', '#c3cee6', '#cfbfe6', '#a3cccc', '#f3f1ea'],
    'light': ['#141413', '#b0412e', '#47703c', '#8a5a00', '#3f5b94', '#6d4d9c', '#0b6e7a', '#73726c',
              '#6b6a64', '#b5573a', '#47703c', '#8a5a00', '#3f5b94', '#6d4d9c', '#0b6e7a', '#3b3a37'],
}
ANSI_NAMES = [p + c for p in ('', 'bright') for c in
              ('black', 'red', 'green', 'yellow', 'blue', 'magenta', 'cyan', 'white')]


def xterm256(n: int) -> str:
    """Slot `n`'s (16 to 255) own colour."""
    if n >= 232:
        return '#' + f'{8 + (n - 232) * 10:02x}' * 3
    steps = (0, 95, 135, 175, 215, 255)
    n -= 16
    return '#' + ''.join(f'{steps[i]:02x}' for i in (n // 36, n // 6 % 6, n % 6))


def theme(look: str) -> dict:
    """The theme file for a person whose terminals are `look`."""
    i = 1 if look == 'light' else 0
    return {'name': 'agent-runner', 'base': look,
            'overrides': {k: f'ansi256({ROLES[role][i]})' for role, keys in USES.items() for k in keys.split()}}


def page_look(look: str, base: str = '') -> dict:
    """What the page's terminal is set to while the page is `look` (an xterm.js theme): the page's own ground, and every
    slot of `ROLES`, and of `CODE` for the theme's `base` (the person's look unless given), in the page's colours."""
    if not base:  # imported here, as in settings
        from agent_runner.session_frame import session_look
        base = session_look()
    i = 2 if look == 'dark' else 3
    slots = [xterm256(n) for n in range(16, 256)]
    for role in ROLES.values():
        slots[role[0] - 16] = slots[role[1] - 16] = role[i]
    for code in CODE.values():
        for n in code[1 if base == 'light' else 0]:
            slots[n - 16] = code[i]
    at = {k: v[i] for k, v in ROLES.items()}
    ground = '#262624' if look == 'dark' else '#faf9f5'  # web_page.html's --bg
    return {'background': ground, 'foreground': at['text'], 'cursor': at['text'], 'cursorAccent': ground,
            'selectionBackground': at['empty'], 'extendedAnsi': slots, **dict(zip(
                [n[:6] + n[6:].capitalize() if n.startswith('bright') else n for n in ANSI_NAMES], ANSI[look]))}


def theme_file() -> Path:
    return Path(os.environ.get('CLAUDE_CONFIG_DIR') or Path.home() / '.claude') / 'themes' / f'{NAME}.json'


def settings(look: str = '') -> dict:
    """The settings a session the run starts gets for its look, the theme file written first; without it, only the
    calm ones."""
    if not look:  # imported here: session_frame takes the looks from this module
        from agent_runner.session_frame import session_look
        look = session_look()
    f, text = theme_file(), json.dumps(theme(look), indent=2) + '\n'
    try:
        if not f.is_file() or f.read_text(encoding='utf-8') != text:
            f.parent.mkdir(parents=True, exist_ok=True)
            tmp = f.with_name(f'{f.name}.{os.getpid()}.tmp')
            tmp.write_text(text, encoding='utf-8')
            os.replace(tmp, f)
    except OSError:
        return dict(CALM)
    return {'theme': SETTING, **CALM}
