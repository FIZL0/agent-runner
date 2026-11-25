"""F161a: Recorded, the run's side: a clip of the person's speech made into words on this machine, by whisper.cpp.

Optional, as run speech is: `agent-runner speech install whisper` puts it in the speech folder's `whisper` (a
`whisper-cli` already on PATH is used as it is). The page sends 16 kHz mono 16-bit WAV, so nothing needs decoding
first. Every clip is read with a prompt of project words. The clip is a file only while the engine reads it, and its words go
to the page alone: never to a log, an error or a file. See docs/research/talk-speech-to-text.md (R16).
"""
from __future__ import annotations

import array
import io
import os
import re
import shutil
import subprocess as sp
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path

from agent_runner import speech
from agent_runner import state as S

RATE = 16000
SECONDS_MAX = 120  # the longest clip
BYTES_MAX = SECONDS_MAX * RATE * 2 + 4096  # with room for the header
SECONDS_MIN = 0.1
QUIET = 150  # of 32767: a clip never louder holds no speech, and the engine would make some up
READ_TIMEOUT = 45.0  # s for one clip, its wait for another included, under Home's 60 s for a run's answer
GPU_MODEL, CPU_MODEL = 'ggml-large-v3-turbo-q5_0.bin', 'ggml-base.en.bin'
_HF = 'https://huggingface.co/ggerganov/whisper.cpp/resolve/5359861c739e955e79d9a303bcbc70fb988958b1/'
MODELS = {  # file: sha256
    GPU_MODEL: '394221709cd5ad1f40c46e6031ca61bce88931e6e088c188294c6d5a55ffa7e2',
    CPU_MODEL: 'a03779c86df3323075f5e796cb2ce5029f00ec8869eee3fdfb897afe36c6d002'}
REPO, TAG = 'https://github.com/ggml-org/whisper.cpp', 'v1.9.6'
COMMIT = '96ec4d9823e9d0211944172da35f9f29134af990'
EXE = 'whisper-cli.exe' if os.name == 'nt' else 'whisper-cli'
WORDS = 'Talk, Kokoro, Piper, iPhone, agent-runner, Hold'
IDS_MAX, TERMS_MAX = 25, 15  # whisper keeps the last 224 tokens of a prompt, so the ids come last
CLIP_OLD = 600  # s: no clip is read for that long
NO_WINDOW = getattr(sp, 'CREATE_NO_WINDOW', 0)


class BadClip(ValueError):
    """Why a clip is refused, in words."""


def folder() -> Path:
    return speech.speech_dir() / 'whisper'


def program() -> str:
    own = folder() / EXE
    return str(own) if own.exists() else shutil.which('whisper-cli') or ''


def model() -> str:
    """The best model here: the large one is only installed on a machine whose GPU runs it."""
    return next((m for m in MODELS if (folder() / m).exists()), '')


def engine() -> dict:
    """For the page: {'ok', 'engine': is one here, 'why': why not, 'model', 'seconds': the longest clip}."""
    why = ''
    if not program():
        why = "no speech recognition is installed on the run's machine"
    elif not model():
        why = "the speech recognition on the run's machine has no model"
    return {'ok': True, 'engine': not why, 'why': why, 'model': '' if why else model(), 'seconds': SECONDS_MAX}


def prompt() -> str:
    """The project's words, so the engine spells them: the open tasks' ids, the project's name, its glossary's terms."""
    ids, terms, name = [], [], ''
    try:
        from agent_runner import glossary, plan
        name = S.project()
        ids = [tid for _, box, tid, _, _ in plan.iter_tasks(plan.lines(S.C.todo)) if box in ' ~'][:IDS_MAX]
        f = glossary.path(S.C)
        if f and f.exists():
            terms = list(glossary.parse(f.read_text(encoding='utf-8')))[:TERMS_MAX]
    except Exception:  # noqa: BLE001 - no project, or a plan that cannot be read: the fixed words still help
        pass
    words = ', '.join(dict.fromkeys(w for w in (*terms, name, *WORDS.split(', ')) if w))
    return f'Words: {words}. Task ids like {", ".join(ids or ["R16", "B162", "T19"])}.'


def check_clip(data: bytes) -> bool:
    """Whether there is any sound in a clip; BadClip when it is not one the engine may be given."""
    try:
        with wave.open(io.BytesIO(data)) as w:
            form = (w.getframerate(), w.getnchannels(), w.getsampwidth())
            frames = w.readframes(BYTES_MAX)
    except (wave.Error, EOFError, ValueError, RuntimeError) as e:
        raise BadClip('the clip is not a WAV') from e
    if form != (RATE, 1, 2):
        raise BadClip('the clip is not 16 kHz mono 16-bit WAV')
    if len(frames) > SECONDS_MAX * RATE * 2:
        raise BadClip(f'a clip is at most {SECONDS_MAX} seconds')
    if len(frames) < SECONDS_MIN * RATE * 2:
        raise BadClip('the clip is too short')
    a = array.array('h', frames[:len(frames) // 2 * 2])
    if sys.byteorder == 'big':
        a.byteswap()
    return max(max(a), -min(a)) > QUIET


def clean(text: str) -> str:
    """The engine's answer on one line, without its marks for what is not speech ([BLANK_AUDIO], (buzzing))."""
    text = ' '.join(re.sub(r'\[[^\]]*\]|\([^)]*\)|♪', ' ', text).split())
    return text if re.search(r'\w', text) else ''


def sweep() -> None:
    """Clips a run left behind when it was killed while one was read."""
    for d in Path(tempfile.gettempdir()).glob('agent-runner-clip-*'):
        try:
            if time.time() - d.stat().st_mtime > CLIP_OLD:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass


class Listener:
    """A run's engine: one clip is read at a time, each by a process of its own (a model loads in 0.1 to 0.2 s)."""

    def __init__(self, argv=None, timeout: float = READ_TIMEOUT):
        self.argv = argv or (lambda clip: [
            program(), '-m', str(folder() / model()), '-f', clip, '-nt', '-np', '-l', 'en',
            '-t', str(min(8, os.cpu_count() or 4)), '--prompt', prompt()])
        self.timeout = timeout
        self.lock, self.proc, self.closed = threading.Lock(), None, False

    def read(self, data: bytes) -> str:
        """The words in a WAV clip, '' when nobody speaks in it."""
        sound = check_clip(data)
        if why := engine()['why']:
            raise speech.SpeechError(why)
        if not sound:
            return ''
        end = time.monotonic() + self.timeout
        if not self.lock.acquire(timeout=self.timeout):
            raise speech.SpeechError('the speech recognition is busy')
        try:
            return clean(self._run(data, end))
        finally:
            self.lock.release()

    def _run(self, data: bytes, end: float) -> str:
        sweep()
        # no error below holds the engine's own output: it may be the words
        try:
            with tempfile.TemporaryDirectory(prefix='agent-runner-clip-', ignore_cleanup_errors=True) as d:
                clip = Path(d) / 'clip.wav'  # the folder is the person's own (0700)
                clip.write_bytes(data)
                try:
                    out = self._words(str(clip), end)
                finally:
                    clip.unlink(missing_ok=True)
        except OSError as e:
            raise speech.SpeechError(f'the speech recognition did not run ({type(e).__name__})') from None
        return out

    def _words(self, clip: str, end: float) -> str:
        if self.closed:
            raise speech.SpeechError('the run is stopping')
        p = self.proc = sp.Popen(self.argv(clip), stdin=sp.DEVNULL, stdout=sp.PIPE, stderr=sp.DEVNULL,
                                 creationflags=NO_WINDOW)
        try:
            if self.closed:  # between the check and the start
                p.kill()
            out = p.communicate(timeout=max(0.1, end - time.monotonic()))[0]
        except sp.TimeoutExpired:
            raise speech.SpeechError('the speech recognition took too long') from None
        finally:
            self.proc = None
            if p.poll() is None:
                p.kill()
            p.wait()
            p.stdout.close()
        if p.returncode:
            raise speech.SpeechError(f'the speech recognition failed (exit {p.returncode})')
        return out.decode('utf-8', 'replace')

    def close(self) -> None:
        self.closed = True
        if p := self.proc:
            p.kill()


# --- install ----------------------------------------------------------------------------------------------------

def build(out=print, which=shutil.which) -> None:
    """whisper.cpp's whisper-cli, built here: for the GPU when this machine has what that needs (Vulkan's headers and glslc),
    else for the CPU."""
    if gone := [t for t in ('git', 'cmake') if not which(t)]:
        raise speech.SpeechError(f'it needs {" and ".join(gone)} and a C++ compiler, or a whisper-cli on PATH')
    with tempfile.TemporaryDirectory(prefix='agent-runner-whisper-', ignore_cleanup_errors=True) as d:
        src = Path(d) / 'src'
        out(f'building whisper.cpp {TAG}')
        sp.run(['git', 'clone', '-q', '--depth', '1', '--branch', TAG, '-c', 'advice.detachedHead=false', REPO, str(src)],
               check=True)
        head = sp.run(['git', '-C', str(src), 'rev-parse', 'HEAD'], check=True, capture_output=True, text=True).stdout
        if head.strip() != COMMIT:
            raise speech.SpeechError('whisper.cpp: the download is not the expected version')
        for flags in (['-DGGML_VULKAN=1'], []):
            b = Path(d) / ('gpu' if flags else 'cpu')
            steps = (['cmake', '-S', str(src), '-B', str(b), '-DCMAKE_BUILD_TYPE=Release', '-DBUILD_SHARED_LIBS=OFF', *flags],
                     ['cmake', '--build', str(b), '--config', 'Release', '--target', 'whisper-cli',
                      '-j', str(os.cpu_count() or 2)])
            if all(sp.run(s, stdout=sp.DEVNULL, stderr=sp.DEVNULL).returncode == 0 for s in steps):
                made = next(f for f in (b / 'bin').rglob(EXE))
                part = folder() / (EXE + '.part')
                shutil.copy2(made, part)
                part.replace(folder() / EXE)
                return
    raise speech.SpeechError('whisper.cpp did not build (it needs a C++ compiler)')


def uses_gpu() -> bool:
    """Whether the engine here runs on a GPU, as it says itself when it reads a silent second."""
    with tempfile.TemporaryDirectory(prefix='agent-runner-clip-', ignore_cleanup_errors=True) as d:
        clip = Path(d) / 'silent.wav'
        with wave.open(str(clip), 'wb') as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(b'\0' * RATE * 2)
        r = sp.run([program(), '-m', str(folder() / CPU_MODEL), '-f', str(clip), '-nt', '-l', 'en'], timeout=120,
                   stdin=sp.DEVNULL, capture_output=True, encoding='utf-8', errors='replace', creationflags=NO_WINDOW)
    if r.returncode:
        raise speech.SpeechError(f'whisper-cli does not run here (exit {r.returncode})')
    return bool(re.search(r'whisper_backend_init_gpu: using \S+ backend', r.stderr))


def install(out=print) -> None:
    folder().mkdir(parents=True, exist_ok=True)
    if fresh := not program():
        build(out)

    def get(name: str) -> None:
        if not (folder() / name).exists():
            speech.fetch(_HF + name, folder() / name, MODELS[name], out)
    get(CPU_MODEL)
    gpu = uses_gpu()
    if not gpu and not fresh and program() == str(folder() / EXE) and shutil.which('glslc'):
        build(out)  # built for the CPU once: the Vulkan headers may be here by now
        gpu = uses_gpu()
    if gpu:
        get(GPU_MODEL)
    else:
        (folder() / GPU_MODEL).unlink(missing_ok=True)  # 5 s a clip on a CPU
        out('It runs on the CPU here. With a GPU, install the Vulkan and SPIR-V headers and glslc, then run this again '
            'for the better model.')
