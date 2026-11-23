"""B179: the run app on a phone's Home Screen: its web app manifest and its icon, for Runner Home (home.py) and a
run's own address (web.py). Both serve them behind the page's token and no-store: the manifest's start_url carries
the token, as the address the person added the app from does."""

from __future__ import annotations

import functools
import json
import math
import re
import struct
import zlib
from urllib.parse import quote, urlencode

MANIFEST = 'manifest.webmanifest'
MANIFEST_TYPE = 'application/manifest+json; charset=utf-8'
ICON_SIZES = (180, 192, 512)  # 180: iOS's apple-touch-icon; 192 and 512: the manifest's
BACK, MARK = (0xc9, 0x64, 0x42), (0xfa, 0xf9, 0xf5)  # web_page.html's light --accent and --bg
BARS = ((0.30, 0.24, 0.76), (0.50, 0.24, 0.62), (0.70, 0.24, 0.70))  # (y, from x, to x), of the icon's side


def manifest(name: str, token: str, key: str = '', base: str = './') -> str:
    """The manifest of the app called `name`: its scope is `base` (Runner Home's root, or the run's own), so a move
    between projects stays in it; it opens on project `key`'s run app (Home: its All projects without one). No
    colours: the page's own theme-color follows the theme and the view."""
    t = urlencode({'t': token})
    return json.dumps({
        'name': name, 'short_name': key or name, 'display': 'standalone', 'scope': base,
        'start_url': f'{base}p/{quote(key, safe="")}/?{t}' if key else f'{base}?{t}',
        'icons': [{'src': f'{base}icon-{n}.png?{t}', 'sizes': f'{n}x{n}', 'type': 'image/png'} for n in ICON_SIZES[1:]],
    }, ensure_ascii=False)


def icon_at(path: str) -> bytes | None:
    """The icon served at /icon-N.png, None for another path."""
    m = re.fullmatch(r'/icon-(\d{3})\.png', path)
    return icon(int(m[1])) if m and int(m[1]) in ICON_SIZES else None


@functools.lru_cache(maxsize=len(ICON_SIZES))
def icon(size: int) -> bytes:
    """The app's icon as a PNG: three rounded bars on the accent, to the edges (the phone rounds the corners)."""
    half = size * 0.055
    rows = [bytearray(bytes(BACK) * size) for _ in range(size)]
    for cy, x0, x1 in BARS:
        cy, x0, x1 = cy * size, x0 * size + half, x1 * size - half
        for y in range(int(cy - half) - 1, int(cy + half) + 2):
            for x in range(int(x0 - half) - 1, int(x1 + half) + 2):
                px, py = x + 0.5, y + 0.5
                d = math.hypot(px - min(max(px, x0), x1), py - cy)
                if (cover := min(1.0, half - d + 0.5)) > 0:
                    rows[y][x * 3:x * 3 + 3] = bytes(round(b + (m - b) * cover) for b, m in zip(BACK, MARK))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))

    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(b''.join(b'\0' + bytes(r) for r in rows), 9)) + chunk(b'IEND', b''))
