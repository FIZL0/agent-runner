"""F114: the real session in a chat or slot of the run app: ttyd's page (`attach NAME`), served under the run page's
own address, /t/TOKEN/NAME/, so it works over https and through Runner Home, and the app may reach into it (its keys,
its scrolling, its focus). ttyd itself listens on 127.0.0.1. `frame` answers one request; `tunnel` carries a WebSocket
(Runner Home's too).
"""
from __future__ import annotations

import gzip
import hashlib
import html
import http.client
import json
import re
import socket
import threading
from pathlib import Path

from agent_runner import box_font, plat, session_theme

# Goes into ttyd's page, ahead of its own script. Focus: only a press in the frame with a mouse gives the terminal the
# keyboard, never ttyd's own focus() on connect; on a touch device nothing does, so no keyboard opens. It tells the app
# when its socket opens and closes, and hands it files dropped on it. F170: arLook(look) sets its colours (a themed
# session's follow the page, light or dark), and a wheel step is the page's first (feedTake: its bars go and come). B190:
# so are a key and a paste (feedTyped: they go to its message box while the agent CLI's input is hidden).
# F206: one page for every chat: ttyd gets a socket that never closes (Line), and arLine changes the connection behind it:
# dial(name, look), hang(), keep() (a copy of the screen, a node of this page), show(node) (over the terminal until its
# first whole draw, words near its bottom, or null), heard() (when its connection last brought something). So ttyd never draws its Reconnect words, and nothing is loaded again. The next chat's first
# output starts with ESC c, so what was written before ends there. It says 'up', 'drawn' and 'down'; the app dials again.
# The login's keeps ttyd's own socket.
# B845: a mouse over a session that tracks it (Claude Code's full screen): a drag selects words as Shift+drag (Option on a
# Mac) does, so a press is held back until it is a drag or a click, and a click is sent then; a right click is the browser's
# menu; while words are selected a bare move is not sent (it would drop them), and Ctrl+C or Cmd+C copies them (a held key
# once) and is no interrupt. Not the login's.
# The box font is loaded before xterm.js measures its glyphs (and, when it was late, they are measured again).
# B883: and the terminal is fitted again then, and whenever its box changes size (a frame shown after it was hidden), so
# the session (Copilot CLI's prompt) draws for the columns the box shows, not those of a first, wrong measure.
HEAD = '''<meta name="referrer" content="no-referrer"><style>
__FONT__:root{--ar-bg:__BG__} html,body{overscroll-behavior:none;touch-action:none;background:var(--ar-bg)!important}
#terminal-container{margin:0!important} #terminal-container .terminal{padding:__PAD__!important;height:100%!important;box-sizing:border-box}
#terminal-container{position:relative} #ar-kept{position:absolute!important;inset:0;z-index:9;overflow:hidden;pointer-events:none;background:var(--ar-bg)} #ar-kept .xterm-rows{opacity:.75}
.xterm .xterm-viewport{background:var(--ar-bg)!important;scrollbar-width:none} .xterm-viewport::-webkit-scrollbar{display:none}
</style><script>(function(){
var pressed=false, touch=matchMedia('(pointer:coarse)').matches, focus=HTMLElement.prototype.focus;
HTMLElement.prototype.focus=function(o){if(pressed&&!touch)focus.call(this,o)};
addEventListener('pointerdown',function(){pressed=true},true);
addEventListener('blur',function(){pressed=false});
var name=__NAME__, own=name==='login'||name.indexOf('login-')===0;
function tell(m){parent.postMessage(Object.assign({session:name},m),location.origin)}
var W=window.WebSocket;
var LOOKS=__LOOKS__, look=__LOOK__;
window.arLook=function(to){if(to)look=to;var t=window.term, c=LOOKS[look];if(!c)return;
document.documentElement.style.setProperty('--ar-bg',c.background);if(t)t.options.theme=c};
if(look==='page'){try{look='page-'+parent.feedLook()}catch(e){look='page-'+(matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light')}window.arLook()}
var line=null, url='', sock=null, turn=0, heard=0, opened=false, set=false, drew=false;
function Own(u,p){var s=new W(u,p);s.addEventListener('open',function(){tell({state:'up'})});s.addEventListener('close',function(e){tell({state:'down',code:e.code})});return s}
Own.OPEN=W.OPEN;
class Line extends EventTarget{constructor(u){super();url=u;line=this;this.binaryType='arraybuffer';var want=name;try{if(parent.feedWant){want=parent.feedWant();look=parent.feedWantLook()||look}}catch(e){}if(want)dial(want)}
get readyState(){return sock?sock.readyState:W.CLOSED}
send(d){if(sock&&sock.readyState===W.OPEN)sock.send(d)}
close(){hang()}}
Line.OPEN=W.OPEN;
window.WebSocket=own?Own:Line;
function hang(){turn++;var s=sock;sock=null;if(s)s.close()}
function dial(to){hang();var other=to!==name;name=to;if(!line)return;
if(other&&drew){window.term.write('\\x1bc');drew=false}
var me=turn, at=0, out=0, quiet=0, done=false;
var s=sock=new W(url.replace(/[^/]+[/]ws(?=[?]|$)/,encodeURIComponent(to)+'/ws'),['tty']);s.binaryType='arraybuffer';
s.onopen=function(){if(me!==turn)return;at=Date.now();
if(!opened){opened=true;line.dispatchEvent(new Event('open'))}
else{var t=window.term;if(t.fit)t.fit();s.send(new TextEncoder().encode(JSON.stringify({AuthToken:'',columns:t.cols,rows:t.rows})))}
tell({state:'up'})};
s.onclose=function(e){if(me!==turn)return;clearTimeout(quiet);sock=null;tell({state:'down',code:e.code})};
s.onmessage=function(e){if(me!==turn)return;heard=Date.now();
var what=new Uint8Array(e.data)[0];
if(what===48){if(!out){out=Date.now();if(drew)window.term.write('\\x1bc');drew=true}
clearTimeout(quiet);if(!done)quiet=setTimeout(look4,out&&Date.now()-out>700?0:Math.max(150,250-(Date.now()-at)))}
else if(set)return;
else if(what===50){set=true;setTimeout(window.arLook,0)}
line.dispatchEvent(new MessageEvent('message',{data:e.data}))};
function look4(){var t=window.term;if(me!==turn||!t)return;
t.write('',function(){if(me!==turn||done)return;var b=t.buffer.active, y=t.rows, low=Date.now()-out>1500?0:y-8, text=false;
while(y--){var l=b.getLine(b.baseY+y);if(l&&l.translateToString(true).trim()){text=true;if(y<low)break;done=true;requestAnimationFrame(function(){if(me===turn)tell({state:'drawn'})});return}}
if(text)quiet=setTimeout(look4,200)})}
}
window.arLine={dial:function(to,l){if(l)window.arLook(l);dial(to)},hang:hang,heard:function(){return heard},
keep:function(){var t=window.term, rows=t&&t.element&&t.element.querySelector('.xterm-rows');if(!rows||!rows.textContent.trim())return null;
var k=document.createElement('div'), s=document.createElement('div');k.id='ar-kept';k.setAttribute('aria-hidden','true');k.className=t.element.className;
s.className='xterm-screen';s.style.cssText=rows.parentNode.style.cssText;s.appendChild(rows.cloneNode(true));k.appendChild(s);return k},
show:function(k){var o=document.getElementById('ar-kept'), c=document.getElementById('terminal-container');if(o===k)return;if(o)o.remove();if(k&&c)c.appendChild(k)}};
function refit(){var t=window.term;if(t&&t.fit&&t.element&&t.element.offsetWidth)t.fit()}
document.fonts.load('13px ar-box','\\u2500').then(function(){var t=window.term;if(t){t.options.fontFamily+=',monospace';requestAnimationFrame(refit)}});
var fitting=0;addEventListener('load',function(){var c=document.getElementById('terminal-container');
if(c&&window.ResizeObserver)new ResizeObserver(function(){clearTimeout(fitting);fitting=setTimeout(refit,60)}).observe(c)});
addEventListener('wheel',function(e){var px=e.deltaY*(e.deltaMode===1?16:e.deltaMode===2?innerHeight:1);
if(!own&&!e.ctrlKey&&e.isTrusted&&parent.feedTake&&parent.feedTake(px)){e.preventDefault();e.stopImmediatePropagation()}},{capture:true,passive:false});
function ours(e,paste){try{if(parent.feedTyped&&parent.feedTyped(e,paste)){e.preventDefault();e.stopImmediatePropagation()}}catch(x){}}
addEventListener('keydown',function(e){ours(e)},true);
addEventListener('paste',function(e){var s=e.clipboardData&&e.clipboardData.getData('text/plain');if(s)ours(e,s)},true);
var mac=/^Mac/.test(navigator.platform), mouse=false, press=null, copied=false;
function onScreen(e){var t=window.term;return !own&&mouse&&e.isTrusted&&t&&t.element&&t.element.contains(e.target)&&t.modes.mouseTrackingMode!=='none'}
function picked(){var t=window.term;return !own&&t&&t.hasSelection()?t.getSelection():''}
function eat(e){e.preventDefault();e.stopImmediatePropagation()}
function again(type,e,pick){var s=window.term.element.querySelector('.xterm-screen');
s.dispatchEvent(new MouseEvent(type,{bubbles:true,cancelable:true,view:window,detail:e.detail,screenX:e.screenX,screenY:e.screenY,clientX:e.clientX,clientY:e.clientY,
button:0,buttons:type==='mousedown'?1:0,ctrlKey:e.ctrlKey,metaKey:e.metaKey,shiftKey:e.shiftKey||!!pick&&!mac,altKey:e.altKey||!!pick&&mac}))}
function sendClick(p,e){again('mousedown',p.e);again('mouseup',e)}
addEventListener('pointerdown',function(e){mouse=e.pointerType==='mouse'},true);
addEventListener('mousedown',function(e){if(!onScreen(e))return;
if(e.button===2)Object.defineProperty(e,mac?'altKey':'shiftKey',{value:true});
else if(e.button===0&&mac&&e.ctrlKey){eat(e);window.term.focus()}
else if(e.button===0&&!(mac?e.altKey:e.shiftKey)){press={e:e,on:false};eat(e);window.term.focus()}},true);
addEventListener('mousemove',function(e){
if(press&&!(e.buttons&1))press=null;
if(press){if(!press.on&&Math.hypot(e.clientX-press.e.clientX,e.clientY-press.e.clientY)>4){press.on=true;again('mousedown',press.e,true)}
if(!press.on)e.stopImmediatePropagation()}
else if(!e.buttons&&onScreen(e)&&picked())e.stopImmediatePropagation()},true);
addEventListener('mouseup',function(e){if(!press||e.button)return;var p=press;press=null;
if(!p.on){eat(e);sendClick(p,e)}else if(!window.term.hasSelection())setTimeout(sendClick,0,p,e)},true);
addEventListener('blur',function(){press=null});
addEventListener('keydown',function(e){if(own||e.keyCode!==67||e.altKey||e.shiftKey||!(e.ctrlKey||e.metaKey))return;
if(e.repeat&&copied)return eat(e);
var s=picked(), t=window.term;copied=!!s;if(!s)return;eat(e);
var ok=false;function put(c){eat(c);c.clipboardData.setData('text/plain',s);ok=true}
t.textarea.value=s;t.textarea.select();addEventListener('copy',put,true);
try{document.execCommand('copy')}catch(x){}
removeEventListener('copy',put,true);t.textarea.value='';if(ok)t.clearSelection()},true);
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
    looks = {**THEMES, **{f'page-{k}': session_theme.page_look(k) for k in THEMES}}  # the page outlives one chat
    ground = looks['page-dark' if look == 'page' else look]['background']
    for at, what in (('__FONT__', BOX_FONT), ('__BG__', ground), ('__PAD__', PAD), ('__NAME__', json.dumps(name)),
                     ('__LOOKS__', json.dumps(looks, separators=(',', ':'))), ('__LOOK__', json.dumps(look))):
        head = head.replace(at, what)
    i = page.find(b'<head>')
    at = i + len(b'<head>') if i >= 0 else 0
    return page[:at] + head.encode() + page[at:]


_gz: dict[str, bytes] = {}  # ETag -> the page compressed


_gz_app: dict[str, bytes] = {}  # B769a: the same for the run app's page, so ttyd's pages (one per chat) never push it out
_gz_lock = threading.Lock()


def takes_gzip(accept: str) -> bool:
    """Whether an Accept-Encoding header takes gzip ('gzip;q=0' does not)."""
    return bool(re.search(r'(?:^|,)\s*gzip\s*(?:;\s*q=(?!0(?:\.0*)?\s*(?:,|$))[0-9.]+\s*)?(?:,|$)', accept, re.I))


def send_app(handler, data: bytes) -> None:
    """B769a: answer with the run app's page (456 KB, 151 KB compressed), compressed once per version of it. The caller
    has checked the key."""
    send_page(handler, data, 'text/html; charset=utf-8', _gz_app)


def send_page(handler, data: bytes, ctype: str, kept: dict = _gz) -> None:
    """Answer with ttyd's page: compressed for a browser that takes it (740 KB, 194 KB compressed), and not at all for one
    that kept this very page: it asks each time, so only the key opens it."""
    tag = '"' + hashlib.sha256(data).hexdigest()[:24] + '"'
    same = tag in [t.strip().removeprefix('W/') for t in handler.headers.get('If-None-Match', '').split(',')]
    zipped = takes_gzip(handler.headers.get('Accept-Encoding', ''))
    if zipped and not same:
        with _gz_lock:
            if not (got := kept.get(tag)):
                if len(kept) > 8:
                    kept.clear()
                got = kept[tag] = gzip.compress(data, 6)
        data = got
    handler.send_response(304 if same else 200)
    handler.send_header('ETag', tag)
    handler.send_header('Vary', 'Accept-Encoding')
    handler.send_header('Cache-Control', 'private, no-cache')
    handler.send_header('Referrer-Policy', 'no-referrer')
    if not same:
        handler.send_header('Content-Type', ctype)
        handler.send_header('Content-Length', str(len(data)))
        if zipped:
            handler.send_header('Content-Encoding', 'gzip')
    handler.end_headers()
    if not same:
        handler.wfile.write(data)


LOGIN = 'login'  # F126b: the terminal that runs watch.LOGIN_CMD and nothing else


def login_argv() -> list[str]:
    """F126b: what the login's ttyd runs: the fixed command, never a word of a request. The terminal ends with it."""
    from agent_runner.watch import LOGIN_CMD
    cmd, *rest = LOGIN_CMD.split()
    return ['-t', 'disableReconnect=true', plat.exe(cmd), *rest]


def login_frame(handler, terms, path: str, name: str = LOGIN) -> None:
    """F126b: answer `handler`'s request for the login's terminal of `terms` (web.Terminals), at `path` under it.
    F406a: `name` may be a provider's login (provider_login)."""
    got = terms.ttyd(name)
    if not got['ok']:
        return handler.send(502, f'<pre>{html.escape(got["out"])}</pre>', 'text/html; charset=utf-8')
    target = f'/t/{terms.token}/{name}/{path}'
    if 'websocket' in handler.headers.get('Upgrade', '').lower():
        return terms.hold(name).serve(handler, got['port'], target)
    frame(handler, got['port'], target, name, session_look())


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
        return send_page(handler, with_head(data, name, look), 'text/html; charset=utf-8')
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
