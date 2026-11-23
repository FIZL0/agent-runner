"""F114: the real session in a chat or slot of the run app: ttyd's page (`attach NAME`), served under the run page's
own address, /t/TOKEN/NAME/, so it works over https and through Runner Home, and the app may reach into it (its keys,
its scrolling, its focus). ttyd itself listens on 127.0.0.1. `frame` answers one request; `tunnel` carries a WebSocket
(Runner Home's too).
"""
from __future__ import annotations

import http.client
import json
import socket
import threading
from pathlib import Path

from agent_runner import box_font, session_theme

# Goes into ttyd's page, ahead of its own script. Focus: only a press in the frame with a mouse gives the terminal the
# keyboard, never ttyd's own focus() on connect; on a touch device nothing does, so no keyboard opens. It tells the app
# when its socket opens and closes, and hands it files dropped on it. F170: arLook(look) sets its colours (a themed
# session's follow the page, light or dark), and a wheel step is the page's first (feedTake: its bars go and come).
# The box font is loaded before xterm.js measures its glyphs (and, when it was late, they are measured again).
HEAD = '''<meta name="referrer" content="no-referrer"><style>
__FONT__:root{--ar-bg:__BG__} html,body{overscroll-behavior:none;touch-action:none;background:var(--ar-bg)!important}
#terminal-container{margin:0!important} #terminal-container .terminal{padding:__PAD__!important;height:100%!important;box-sizing:border-box}
.xterm .xterm-viewport{background:var(--ar-bg)!important;scrollbar-width:none} .xterm-viewport::-webkit-scrollbar{display:none}
</style><script>(function(){
var pressed=false, touch=matchMedia('(pointer:coarse)').matches, focus=HTMLElement.prototype.focus;
HTMLElement.prototype.focus=function(o){if(pressed&&!touch)focus.call(this,o)};
addEventListener('pointerdown',function(){pressed=true},true);
addEventListener('blur',function(){pressed=false});
function tell(m){parent.postMessage(Object.assign({session:__NAME__},m),location.origin)}
var W=window.WebSocket;
window.WebSocket=class extends W{constructor(u,p){super(u,p);
this.addEventListener('open',function(){tell({state:'up'})});this.addEventListener('close',function(){tell({state:'down'})});
var n=0;this.addEventListener('message',function(){if(n++<4)setTimeout(window.arLook,0)})}};
var LOOKS=__LOOKS__, look=__LOOK__;
window.arLook=function(to){if(to)look=to;var t=window.term, c=LOOKS[look];if(!c)return;
document.documentElement.style.setProperty('--ar-bg',c.background);if(t)t.options.theme=c};
if(LOOKS.light){try{look=parent.feedLook()}catch(e){look=matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light'}window.arLook()}
document.fonts.load('13px ar-box','\\u2500').then(function(){var t=window.term;if(t)t.options.fontFamily+=',monospace'});
addEventListener('wheel',function(e){var px=e.deltaY*(e.deltaMode===1?16:e.deltaMode===2?innerHeight:1);
if(!e.ctrlKey&&e.isTrusted&&parent.feedTake&&parent.feedTake(px)){e.preventDefault();e.stopImmediatePropagation()}},{capture:true,passive:false});
addEventListener('dragover',function(e){e.preventDefault()});
addEventListener('drop',function(e){e.preventDefault();var f=e.dataTransfer?Array.from(e.dataTransfer.files):[];if(f.length)tell({files:f})});
})()</script>'''

LINE_HEIGHT, PAD = '1.3', '12px 14px'
BOX_FONT = (f"@font-face{{font-family:ar-box;src:url(data:font/woff2;base64,{box_font.WOFF2}) format('woff2');"
            f'unicode-range:{box_font.RANGE}}}\n')  # its lines join at any line height

THEMES = {  # the 16 colours a session draws its own with
    'dark': {'background': '#1f1e1d', 'foreground': '#e8e6dc', 'cursor': '#e8e6dc', 'selectionBackground': '#4a4945'},
    'light': {'background': '#ffffff', 'foreground': '#141413', 'cursor': '#141413', 'selectionBackground': '#dcd9cd',
              'black': '#141413', 'white': '#73726c', 'brightBlack': '#73726c', 'brightWhite': '#3b3a37',
              'yellow': '#8a5a00', 'brightYellow': '#8a5a00', 'green': '#3f6b34', 'brightGreen': '#3f6b34',
              'cyan': '#0b6e7a', 'brightCyan': '#0b6e7a'},
}


def session_look(home: Path | None = None) -> str:
    """'light' when the person set their agent's terminal look to a light one (the `theme` in ~/.claude/settings.json
    or ~/.claude.json), else 'dark': a session's colours are made for that ground."""
    home = home or Path.home()
    for f in (home / '.claude' / 'settings.json', home / '.claude.json'):
        try:
            theme = json.loads(f.read_text(encoding='utf-8')).get('theme')
        except (OSError, ValueError, AttributeError):
            continue
        if isinstance(theme, str) and theme:
            return 'light' if theme.startswith('light') else 'dark'
    return 'dark'


def ttyd_options(look: str) -> list[str]:
    """What the session's page is set to: no leave question, no size shown, its colours and font. F170: room between its
    lines, and text at 4.5:1 on whatever it stands on (Claude Code's own code colours are made for one ground)."""
    opts = {'disableLeaveAlert': 'true', 'disableResizeOverlay': 'true', 'rendererType': 'dom', 'fontSize': '13',
            'fontFamily': 'ar-box,ui-monospace,SFMono-Regular,Menlo,Consolas,monospace', 'macOptionClickForcesSelection': 'true',
            'lineHeight': LINE_HEIGHT, 'minimumContrastRatio': '4.5',
            'theme': json.dumps(THEMES[look], separators=(',', ':'))}
    return [x for k, v in opts.items() for x in ('-t', f'{k}={v}')]


def with_head(page: bytes, name: str, look: str) -> bytes:
    """ttyd's page with HEAD in it; `look` 'page' (a session with the run's theme), 'dark' or 'light'."""
    head = HEAD
    looks = {k: session_theme.page_look(k) for k in THEMES} if look == 'page' else {}
    ground = looks['dark']['background'] if looks else THEMES[look]['background']
    for at, what in (('__FONT__', BOX_FONT), ('__BG__', ground), ('__PAD__', PAD), ('__NAME__', json.dumps(name)),
                     ('__LOOKS__', json.dumps(looks, separators=(',', ':'))), ('__LOOK__', json.dumps(look))):
        head = head.replace(at, what)
    i = page.find(b'<head>')
    at = i + len(b'<head>') if i >= 0 else 0
    return page[:at] + head.encode() + page[at:]


def frame(handler, port: int, target: str, name: str, look: str) -> None:
    """Answer `handler`'s request from the ttyd on `port` at `target`: its WebSocket, or its page with HEAD in it."""
    if 'websocket' in handler.headers.get('Upgrade', '').lower():
        return tunnel(handler, port, target)
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
    try:
        conn.request('GET', target)  # no Accept-Encoding: the page comes plain
        r = conn.getresponse()
        code, data, ctype = r.status, r.read(), r.getheader('Content-Type') or 'text/plain'
    except (OSError, http.client.HTTPException) as e:
        return handler.send(502, json.dumps({'ok': False, 'out': f"{name}'s ttyd did not answer: {e}"}))
    finally:
        conn.close()
    if code == 200 and ctype.startswith('text/html'):
        data, ctype = with_head(data, name, look), 'text/html; charset=utf-8'
    handler.send(code, data, ctype)


def tunnel(handler, port: int, target: str, who: str = 'the session') -> None:
    """A WebSocket upgrade: the request goes on as it came (its path swapped) to 127.0.0.1:`port`, then bytes flow
    both ways until either side ends."""
    try:
        up = socket.create_connection(('127.0.0.1', port), timeout=10)
    except OSError as e:
        return handler.send(502, json.dumps({'ok': False, 'out': f"{who}'s terminal did not answer: {e}"}))
    head = [f'{handler.command} {target} HTTP/1.1', f'Host: 127.0.0.1:{port}',
            *(f'{k}: {v}' for k, v in handler.headers.items() if k.lower() not in ('host', 'x-token'))]
    handler.close_connection = True
    try:
        up.sendall(('\r\n'.join(head) + '\r\n\r\n').encode('latin-1'))
        up.settimeout(None)
    except OSError:
        up.close()
        return

    def browser_to_run() -> None:
        try:
            while data := handler.rfile.read1(65536):
                up.sendall(data)
        except (OSError, ValueError):
            pass
        try:
            up.shutdown(socket.SHUT_WR)
        except OSError:
            pass

    pump = threading.Thread(target=browser_to_run, name='session-ws', daemon=True)
    pump.start()
    try:
        while data := up.recv(65536):
            handler.wfile.write(data)
    except OSError:
        pass
    finally:
        up.close()
        try:
            handler.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        pump.join(timeout=5)
