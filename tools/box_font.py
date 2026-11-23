"""Make the box-drawing font of a session's frame (agent_runner/box_font.py): `uvx --with fonttools --with brotli python
tools/box_font.py > agent_runner/box_font.py`. Its lines and blocks reach past the cell on every side (a row clips them),
so they join at any line height; no other glyph is in it."""
import base64
import io
import sys

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

WIDE, MID_X, MID_Y, TOP, LOW, OVER = 600, 300, 340, 1250, -570, 12
#          left right up down, for light lines; heavy ones are thicker
LIGHT = {'─': 'lr', '│': 'ud', '┌': 'rd', '┐': 'ld', '└': 'ru', '┘': 'lu', '├': 'rud', '┤': 'lud', '┬': 'lrd', '┴': 'lru',
         '┼': 'lrud', '╭': 'rd', '╮': 'ld', '╰': 'ru', '╯': 'lu', '╴': 'l', '╵': 'u', '╶': 'r', '╷': 'd'}
HEAVY = {'━': 'lr', '┃': 'ud', '┏': 'rd', '┓': 'ld', '┗': 'ru', '┛': 'lu', '┣': 'rud', '┫': 'lud', '┳': 'lrd', '┻': 'lru', '╋': 'lrud'}
L, R = -OVER, WIDE + OVER
QUADS = {'ul': (L, MID_Y, MID_X, TOP), 'ur': (MID_X, MID_Y, R, TOP), 'll': (L, LOW, MID_X, MID_Y), 'lr': (MID_X, LOW, R, MID_Y)}
BLOCKS = {'█': 'ul ur ll lr', '▀': 'ul ur', '▄': 'll lr', '▌': 'ul ll', '▐': 'ur lr', '▖': 'll', '▗': 'lr', '▘': 'ul', '▝': 'ur',
          '▙': 'ul ll lr', '▚': 'ul lr', '▛': 'ul ur ll', '▜': 'ul ur lr', '▞': 'ur ll', '▟': 'ur ll lr'}


def rects(ch: str) -> list[tuple[int, int, int, int]]:
    if ch in BLOCKS:
        return [QUADS[q] for q in BLOCKS[ch].split()]
    h, dirs = (30, LIGHT[ch]) if ch in LIGHT else (65, HEAVY[ch])
    at = {'l': (L, MID_Y - h, MID_X + h, MID_Y + h), 'r': (MID_X - h, MID_Y - h, R, MID_Y + h),
          'u': (MID_X - h, MID_Y - h, MID_X + h, TOP), 'd': (MID_X - h, LOW, MID_X + h, MID_Y + h)}
    return [at[d] for d in dirs]


def main() -> None:
    chars = sorted({**LIGHT, **HEAVY, **BLOCKS})
    glyphs = {'.notdef': TTGlyphPen(None).glyph()}
    for ch in chars:
        pen = TTGlyphPen(None)
        for x0, y0, x1, y1 in rects(ch):
            pen.moveTo((x0, y0))
            for at in ((x0, y1), (x1, y1), (x1, y0)):
                pen.lineTo(at)
            pen.closePath()
        glyphs[f'u{ord(ch):04X}'] = pen.glyph()
    fb = FontBuilder(1000, isTTF=True)
    fb.setupGlyphOrder(list(glyphs))
    fb.setupCharacterMap({ord(c): f'u{ord(c):04X}' for c in chars})
    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics({g: (WIDE, getattr(x, 'xMin', 0)) for g, x in glyphs.items()})
    fb.setupHorizontalHeader(ascent=930, descent=-240)
    fb.setupNameTable({'familyName': 'ar-box', 'styleName': 'Regular'})
    fb.setupOS2(sTypoAscender=930, sTypoDescender=-240, usWinAscent=1250, usWinDescent=570)
    fb.setupPost(keepGlyphNames=False)
    fb.font.recalcTimestamp = False
    fb.font['head'].created = fb.font['head'].modified = 0
    fb.font.flavor = 'woff2'
    out = io.BytesIO()
    fb.font.save(out)
    text = base64.b64encode(out.getvalue()).decode()
    first, last = (f'{ord(c):X}' for c in (chars[0], chars[-1]))
    sys.stdout.write('"""F170: the box-drawing font of a session\'s frame. Made by tools/box_font.py: change that, not this."""\n'
                     f'RANGE = \'U+{first}-{last}\'\nWOFF2 = (\n' +
                     ''.join(f"    '{text[i:i + 110]}'\n" for i in range(0, len(text), 110)) + ')\n')


main()
