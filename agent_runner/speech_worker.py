"""F158: the process that makes run speech, started by `speech.py` with the speech folder's own Python (the engines are
installed there, not beside agent-runner). Imports nothing of agent_runner.

    speech_worker.py FOLDER

One request per stdin line, {"text", "voice"} as JSON (voice: `kokoro:NAME` or `piper:NAME`). One answer per request
on stdout: a JSON line {"ok": true, "bytes": N} and then N bytes of WAV (16 bit, mono), or {"ok": false, "out": why}.
"""
import io
import json
import os
import sys
import wave
from pathlib import Path

LANGS = {'a': 'en-us', 'b': 'en-gb', 'e': 'es', 'f': 'fr-fr', 'h': 'hi', 'i': 'it', 'j': 'ja', 'p': 'pt-br', 'z': 'cmn'}
loaded = {}


def kokoro(folder: Path, name: str, text: str) -> bytes:
    import numpy as np
    if 'kokoro' not in loaded:
        from kokoro_onnx import Kokoro
        loaded['kokoro'] = Kokoro(str(folder / 'kokoro' / 'kokoro-v1.0.onnx'), str(folder / 'kokoro' / 'voices-v1.0.bin'))
    samples, rate = loaded['kokoro'].create(text, voice=name, speed=1.0, lang=LANGS.get(name[:1], 'en-us'))
    out = io.BytesIO()
    with wave.open(out, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.clip(samples, -1, 1) * 32767).astype('<i2').tobytes())
    return out.getvalue()


def piper(folder: Path, name: str, text: str) -> bytes:
    if name not in loaded:
        from piper import PiperVoice
        loaded[name] = PiperVoice.load(str(folder / 'piper' / f'{name}.onnx'))
    out = io.BytesIO()
    with wave.open(out, 'wb') as w:
        loaded[name].synthesize_wav(text, w)
    return out.getvalue()


def main() -> None:
    folder = Path(sys.argv[1])
    out = os.fdopen(os.dup(1), 'wb')
    os.dup2(2, 1)  # an engine's own prints never land among the answers
    for line in sys.stdin.buffer:
        try:
            req = json.loads(line)
            engine, _, name = req['voice'].partition(':')
            data = {'kokoro': kokoro, 'piper': piper}[engine](folder, name, req['text'])
            out.write(json.dumps({'ok': True, 'bytes': len(data)}).encode() + b'\n' + data)
        except Exception as e:  # noqa: BLE001 - the run says why, and the page reads with the browser's own voice
            out.write(json.dumps({'ok': False, 'out': f'{type(e).__name__}: {e}'}).encode() + b'\n')
        out.flush()


if __name__ == '__main__':
    main()
