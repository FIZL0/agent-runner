"""`agent-runner speech`: run speech, Talk's replies made into sound on this machine and played by the run app (F158).

    speech                          what is installed, and where
    speech install [kokoro|piper]   install an engine and its voices; kokoro (the default) is the natural one,
                                    about 354 MB of files; piper (en_US-lessac-medium, 63 MB) is the light one
    speech install whisper          the engine that turns a recorded clip into words (recorded.py)

Nothing leaves the machine: the engines run here, on the CPU. They live in a folder of their own, one per machine
($AGENT_RUNNER_SPEECH, else $XDG_DATA_HOME/agent-runner/speech, ~/.local/share/agent-runner/speech, on Windows
%LOCALAPPDATA%/agent-runner/speech): `venv` (their Python packages), `kokoro` and `piper` (the voice files). With none
installed the run app reads with the browser's own voices. See docs/research/R15-talk-voice.md.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess as sp
import sys
import threading
import urllib.request
import zipfile
from pathlib import Path

WORKER = Path(__file__).with_name('speech_worker.py')
PIPER_VOICE = 'en_US-lessac-medium'
DEFAULT = 'kokoro:af_heart'  # the person's choice (2026-11-23)
LIGHT = f'piper:{PIPER_VOICE}'
LANGS = {'a': 'American English', 'b': 'British English', 'e': 'Spanish', 'f': 'French', 'h': 'Hindi', 'i': 'Italian',
         'j': 'Japanese', 'p': 'Portuguese', 'z': 'Chinese'}  # by a Kokoro voice's first letter
TEXT_MAX = 4000  # characters in one clip; the page asks for a few sentences at a time
MAKE_TIMEOUT = 45.0  # s for one clip, under Home's 60 s for a run's answer
IDLE = 600.0  # s with no clip asked for before the worker, and the memory its models take, goes
_KOKORO = 'https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/'
_PIPER = ('https://huggingface.co/rhasspy/piper-voices/resolve/e5349433ed883a32f893a434dc43a6c66b95ef7c/'
          'en/en_US/lessac/medium/')
# engine: its pip package, and its files as (name, address, sha256)
ENGINES = {
    'kokoro': ('kokoro-onnx==0.6.1', (
        ('kokoro-v1.0.onnx', _KOKORO + 'kokoro-v1.0.onnx',
         '7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5'),
        ('voices-v1.0.bin', _KOKORO + 'voices-v1.0.bin',
         'bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d'))),
    'piper': ('piper-tts==1.8.0', (
        (f'{PIPER_VOICE}.onnx', _PIPER + f'{PIPER_VOICE}.onnx',
         '5efe09e69902187827af646e1a6e9d269dee769f9877d17b16b1b46eeaaf019f'),
        (f'{PIPER_VOICE}.onnx.json', _PIPER + f'{PIPER_VOICE}.onnx.json',
         'efe19c417bed055f2d69908248c6ba650fa135bc868b0e6abb3da181dab690a0'))),
}
PYTHONS = ('3.13', '3.12', '3.11', '3.10')  # those kokoro-onnx 0.6.1 runs on


def speech_dir() -> Path:
    if d := os.environ.get('AGENT_RUNNER_SPEECH'):
        return Path(d).expanduser()
    base = os.environ.get('XDG_DATA_HOME') or (os.environ.get('LOCALAPPDATA') if os.name == 'nt' else '')
    return (Path(base) if base else Path.home() / '.local' / 'share') / 'agent-runner' / 'speech'


def venv_python(d: Path | None = None) -> Path:
    v = (d or speech_dir()) / 'venv'
    return v / 'Scripts' / 'python.exe' if os.name == 'nt' else v / 'bin' / 'python'


def installed(engine: str, d: Path | None = None) -> bool:
    """Its packages (the mark `install` leaves last) and every one of its files are there."""
    d = d or speech_dir()
    return (venv_python(d).exists() and (d / engine / 'installed').exists()
            and all((d / engine / name).exists() for name, _, _ in ENGINES[engine][1]))


def kokoro_names(d: Path | None = None) -> list[str]:
    """Every voice in Kokoro's voices file (an npz: a zip with one array per voice)."""
    try:
        with zipfile.ZipFile((d or speech_dir()) / 'kokoro' / 'voices-v1.0.bin') as z:
            return sorted(n.removesuffix('.npy') for n in z.namelist() if n.endswith('.npy'))
    except (OSError, zipfile.BadZipFile):
        return []


def voices(d: Path | None = None) -> dict:
    """The voices this machine can read with, for the run app: {'voices': [{'id', 'name', 'lang', 'engine'}], 'default': id}
    (no voices and '' with no engine installed)."""
    out = []
    if installed('kokoro', d):
        out += [{'id': f'kokoro:{n}', 'name': n, 'lang': LANGS.get(n[:1], ''), 'engine': 'Kokoro'} for n in kokoro_names(d)]
    if installed('piper', d):
        out.append({'id': LIGHT, 'name': PIPER_VOICE, 'lang': LANGS['a'], 'engine': 'Piper'})
    ids = [v['id'] for v in out]
    return {'ok': True, 'voices': out, 'default': next((x for x in (DEFAULT, LIGHT, *ids) if x in ids), '')}


class SpeechError(Exception):
    """Why no clip was made, in words."""


class Speaker:
    """One worker process for the run, started by the first clip asked for and ended after IDLE seconds without one.
    One clip is made at a time."""

    def __init__(self, argv=None, timeout: float = MAKE_TIMEOUT, idle: float = IDLE):
        self.argv = argv or (lambda: [str(venv_python()), str(WORKER), str(speech_dir())])
        self.timeout, self.idle = timeout, idle
        self.lock, self.proc, self.timer, self.closed = threading.Lock(), None, None, False

    def make(self, text: str, voice: str = '') -> bytes:
        """`text` as a WAV clip in `voice` (an id from `voices()`; unknown or '': the default)."""
        got = voices()
        ids = [v['id'] for v in got['voices']]
        if not ids:
            raise SpeechError('no voice is installed on the run\'s machine')
        text = ' '.join(text.split())
        if not text or len(text) > TEXT_MAX:
            raise SpeechError(f'a clip is 1 to {TEXT_MAX} characters')
        with self.lock:
            return self._ask({'text': text, 'voice': voice if voice in ids else got['default']})

    def _ask(self, req: dict) -> bytes:
        if self.closed:
            raise SpeechError('the run is stopping')
        if self.timer:
            self.timer.cancel()
        p = self.proc
        watch = None
        try:
            if p is None or p.poll() is not None:
                p = self.proc = sp.Popen(self.argv(), stdin=sp.PIPE, stdout=sp.PIPE, stderr=sp.DEVNULL,
                                         creationflags=getattr(sp, 'CREATE_NO_WINDOW', 0))
            watch = threading.Timer(self.timeout, p.kill)  # a stuck engine: the read below then ends
            watch.daemon = True
            watch.start()
            p.stdin.write(json.dumps(req).encode() + b'\n')
            p.stdin.flush()
            head = json.loads(p.stdout.readline() or b'{}')
            if head.get('out'):
                raise SpeechError(str(head['out']))
            size = int(head.get('bytes') or 0)
            data = p.stdout.read(size)
            if not size or len(data) != size:
                raise ValueError('it ended')
            return data
        except (OSError, ValueError) as e:
            self._end()
            raise SpeechError(f'the speech engine did not answer: {e}') from e
        finally:
            if watch:
                watch.cancel()
            if not self.closed:
                self.timer = threading.Timer(self.idle, self.rest)
                self.timer.daemon = True
                self.timer.start()

    def _end(self) -> None:
        p, self.proc = self.proc, None
        if p:
            p.kill()
            for f in (p.stdin, p.stdout):
                try:
                    f.close()
                except OSError:
                    pass
            p.wait()

    def rest(self) -> None:
        """Nothing asked for in a while: the worker goes; the next clip starts it again."""
        if self.lock.acquire(blocking=False):  # else a clip is being made, which sets the timer again
            try:
                self._end()
            finally:
                self.lock.release()

    def close(self) -> None:
        self.closed = True
        if self.timer:
            self.timer.cancel()
        if p := self.proc:
            p.kill()  # a clip being made ends with it, and lets the lock go
        with self.lock:
            self._end()


# --- install ----------------------------------------------------------------------------------------------------

def fetch(url: str, to: Path, sha: str = '', out=print) -> None:
    """Download `url` to `to` (kept only whole, and with `sha` as its sha256)."""
    part, h = to.with_name(to.name + '.part'), hashlib.sha256()
    out(f'downloading {to.name}')
    with urllib.request.urlopen(url, timeout=60) as r, part.open('wb') as f:
        want = int(r.headers.get('Content-Length') or 0)
        while chunk := r.read(1 << 20):
            h.update(chunk)
            f.write(chunk)
    if (want and part.stat().st_size != want) or (sha and h.hexdigest() != sha):
        part.unlink()
        raise SpeechError(f'{to.name}: the download is not the expected file')
    part.replace(to)


def make_venv(d: Path, which=shutil.which) -> list[str]:
    """The speech folder's own Python, made when it is not there; how to install packages into it."""
    py, uv = venv_python(d), which('uv')
    if not py.exists():
        if uv:
            argv = [uv, 'venv', '--python', PYTHONS[0], str(d / 'venv')]
        else:
            host = next((p for v in PYTHONS if (p := which(f'python{v}'))), '')
            if not host and f'{sys.version_info[0]}.{sys.version_info[1]}' in PYTHONS:
                host = sys.executable
            if not host:
                raise SpeechError(f'it needs uv, or Python {PYTHONS[-1]} to {PYTHONS[0]}; install one of them first')
            argv = [host, '-m', 'venv', str(d / 'venv')]
        sp.run(argv, check=True)
    return [uv, 'pip', 'install', '--python', str(py)] if uv else [str(py), '-m', 'pip', 'install']


def install(engine: str, out=print) -> None:
    package, files = ENGINES[engine]
    d = speech_dir()
    (d / engine).mkdir(parents=True, exist_ok=True)
    sp.run([*make_venv(d), package], check=True)
    for name, url, sha in files:
        if not (d / engine / name).exists():
            fetch(url, d / engine / name, sha, out)
    (d / engine / 'installed').write_text(package + '\n', encoding='utf-8')


def main(argv: list[str]) -> int:
    if argv and argv[0] == 'install' and len(argv) < 3:
        engine = argv[1] if len(argv) > 1 else 'kokoro'
        if engine not in (*ENGINES, 'whisper'):
            print(f'speech install: no such engine: {engine} (kokoro, piper or whisper)', file=sys.stderr)
            return 2
        try:
            if engine == 'whisper':  # F161a
                from agent_runner import recorded
                recorded.install()
                print(f'whisper is installed in {recorded.folder()}, with {recorded.model()}.')
                return 0
            install(engine)
        except (SpeechError, OSError, sp.SubprocessError) as e:
            print(f'speech install: {e}', file=sys.stderr)
            return 1
        print(f'{engine} is installed in {speech_dir()}. Talk uses it from the next message on.')
        return 0
    if argv and argv != ['status']:
        print(__doc__.split('\n\nNothing')[0])
        return 0 if argv[0] in ('-h', '--help', 'help') else 2
    got = voices()
    print(f'{speech_dir()}: ' + (f'{len(got["voices"])} voices, {got["default"]} by default' if got['voices'] else
                                 'no voice installed, so Talk reads with the browser\'s own '
                                 '(`agent-runner speech install`)'))
    from agent_runner import recorded
    words = recorded.engine()
    print('Recorded: ' + (words['model'] if words['engine'] else f"{words['why']} (`agent-runner speech install whisper`)"))
    return 0
