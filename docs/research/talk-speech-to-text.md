# R16: local speech to text for Talk

Question: Safari's recognition keeps cutting off the first word on the person's iPhone. Can the page record the
sound, post it to the run's machine, and get the words from a local engine, with Safari's recognition kept as the other option?
No product code changed; research only. Feeds F161.

## Verdict

1. **Engine: whisper.cpp** (MIT, a single `whisper-cli` / `whisper-server` binary, no account, no Python).
   **Model: `ggml-large-v3-turbo-q5_0` (574 MB) when the machine has a GPU, `ggml-base.en` (148 MB) on CPU only.**
   On this machine's RX 9070 XT (Vulkan) the turbo model took **0.5-0.7 s** from clip end to words for 2.4, 9.4 and 23.8 s clips,
   with 0.4 % word error. On CPU, `base.en` took 0.3-0.6 s with 2.2 % error (0.4 % with a prompt).
2. **A prompt of project words (task ids) fixes the small models' misses**: on whisper.cpp `base.en` 2.2 % -> 0.4 %, `small.en` 9.7 % -> 1.4 %
   (mean over six clips). Always send it. `large-v3-turbo` was already at 0.4 % and the prompt does not change it.
3. **Do not use `small.en`**: slower than `base.en`, no better, and it wrote "taskr16" (task id fused to the word) in the 3 s clip.
4. **The engine does not lose first words** on clean audio (first word right in every no-prompt lead-in-free run: 9 of 9 for each of the 9 engine and model rows).
   If a word is lost it is lost before the engine: cut the clip's front by 0.3 s and the engine returns "check why task…" for
   "Please check why task…" (below). So the fix for the person's complaint is the page's **pre-roll** (section 4), not the engine.
5. **iPhone Safari records audio as AAC in MP4** (and, since Safari 18.4, WebM/Opus). `ffmpeg` and faster-whisper decode both;
   whisper.cpp itself reads only WAV/MP3/FLAC/OGG, so the run decodes to 16 kHz mono WAV with `ffmpeg` first. Better still: the
   page sends raw PCM (WAV) from its pre-roll buffer and no codec is involved.
6. **Default: keep Safari's recognition as the default until the phone check (section 6) shows Recorded gets first words;
   then make Recorded the default on iPhone.** Both stay selectable, as the person asked.

Not tried: anything on a real iPhone (Safari recording, the pre-roll buffer, playback with the mic open, the Allow prompt), except the timings in section 4 (F161c3).
Audio here is the Kokoro voice only, clean and with no room noise, so word accuracy is a best case; real phone-mic speech
will be worse and the ranking between models may move.

## 1. Machine and what was installed

Ryzen 7 9800X3D (8 cores, 16 threads), 30 GB RAM, RX 9070 XT (RADV GFX1201, Vulkan, `KHR_coopmat`), Linux, other agents running
at the same time (times are a little pessimistic). Everything in a scratch directory, nothing installed system-wide.

| Engine | How installed | Licence | Size |
|---|---|---|---|
| whisper.cpp (`96ec4d9`, 2026-11-23) | `git clone https://github.com/ggml-org/whisper.cpp`; `cmake -B bcpu -DCMAKE_BUILD_TYPE=Release && cmake --build bcpu -j12 --target whisper-cli` | MIT | binary only |
| whisper.cpp + Vulkan | same with `-DGGML_VULKAN=1`; needs Vulkan and SPIRV headers (see below) | MIT | binary only |
| faster-whisper 1.2.1 (CTranslate2 4.9.1) | `uv venv --python 3.12 v; uv pip install faster-whisper` | MIT | Python venv, models below |

Models (all MIT, Whisper weights): whisper.cpp `ggml-base.en.bin` 148 MB, `ggml-small.en.bin` 488 MB,
`ggml-large-v3-turbo-q5_0.bin` 574 MB, from `https://huggingface.co/ggerganov/whisper.cpp`. faster-whisper: `base.en` 141 MB,
`small.en` 464 MB, `large-v3-turbo` 1.6 GB (fp16 on disk, run as int8 on CPU).

Install snags worth knowing for F161:
- **Vulkan build failed on this machine** until Vulkan-Headers and SPIRV-Headers were put in the include path (Arch here has
  `shaderc` and the loader but not `vulkan-headers`/`spirv-headers`). I cloned both from `KhronosGroup`'s GitHub, `cmake --install`ed
  them to a prefix, and built with `-DCMAKE_PREFIX_PATH=<prefix> -DCMAKE_CXX_FLAGS=-I<prefix>/include`. The packages
  `vulkan-headers spirv-headers` would do the same in one step.
- **faster-whisper 1.2.1 broke with the newest `av` (19.0.2)**: `TypeError: open() got an unexpected keyword argument 'metadata_errors'`
  on any file input. Pinning `av<16` (15.1.0) fixed it. A second reason to prefer whisper.cpp: fewer moving parts.
- ROCm/HIP (`/opt/rocm` is present) was **not** tried; Vulkan was enough.
- An AMD GPU is the person's machine, not a given: CPU-only must work (it does, section 3).

## 2. Clips

Made with the Kokoro `af_heart` voice from the models R15 already downloaded (`~/.local/share/agent-runner/speech/kokoro/`),
no private audio. Three texts with task ids, each as: `lead0` (leading and trailing silence trimmed, so speech starts at sample 0)
and `lead500` (0.5 s of silence first). Lengths: **2.4 s, 9.4 s and 23.8 s** (the "30 s" clip is 24 s; the engines' cost barely
changes between 10 and 30 s so this does not hide anything). Each also encoded as `m4a` (AAC 64 kb/s, 48 kHz, what iPhone Safari
makes) and `webm` (Opus 32 kb/s, what Chrome and Safari 18.4+ can make).

Texts (written reference): "Open task R16 and run the tests." / "Please check why task B162 heard nothing on the iPhone. Then file
a follow up for T19 and merge the branch when the gate passes." / a 4-sentence one with F106, R15, Piper, Kokoro, Talk.
Word error is `jiwer` word error rate after lower-casing, removing punctuation and joining "r 16" -> "r16".

## 3. Results

Times are the engine's own decode time for the clip, **model already loaded** (as a long-running `whisper-server` or a warm
faster-whisper would have it; whisper.cpp's load time was 0.06-0.19 s anyway, from the file cache). 8 threads on CPU.
Time is from the end of the clip to the words, because the whole clip is posted after the press ends. Word error is the mean
over the six WAV clips (3 lengths x lead0/lead500), without and with the prompt.

| Engine | Model | s3 / m10 / l30 time (no prompt) | Word error: no prompt | with prompt |
|---|---|---|---|---|
| whisper.cpp CPU | base.en | 0.29 / 0.35 / 0.59 s | 2.2 % | 0.4 % |
| whisper.cpp CPU | small.en | 0.81 / 1.03 / 1.59 s | 9.7 % | 1.4 % |
| whisper.cpp CPU | large-v3-turbo-q5_0 | 5.0 / 5.4 / 5.3 s | 0.4 % | 0.4 % |
| whisper.cpp Vulkan (RX 9070 XT) | base.en | 0.51 / 0.37 / 0.35 s | 2.2 % | 0.4 % |
| whisper.cpp Vulkan | small.en | 0.26 / 0.36 / 0.62 s | 9.7 % | 1.4 % |
| whisper.cpp Vulkan | large-v3-turbo-q5_0 | 0.67 / 0.51 / 0.62 s | 0.4 % | 0.4 % |
| faster-whisper CPU int8 | base.en | 0.18 / 0.22 / 0.38 s | 5.9 % | 0.4 % |
| faster-whisper CPU int8 | small.en | 0.46 / 0.60 / 1.55 s | 10.0 % | 1.4 % |
| faster-whisper CPU int8 | large-v3-turbo | 2.1 / 1.9 / 2.3 s | 0.4 % | 0.4 % |

What the numbers say:
- **Turbo's time is flat** (5 s CPU, 0.5-0.7 s GPU) whatever the clip length, because Whisper encodes a padded 30 s window
  every time. So turbo is "fast enough" for 3 s, 10 s and 24 s clips equally; short clips on the smaller models are quicker.
  On CPU, turbo through whisper.cpp q5_0 is 5 s, faster-whisper int8 is 2 s (a different quantisation), a long wait after every phrase.
- **GPU makes turbo usable** (about 8x faster than the CPU run, near `base.en`'s CPU time) and is the only case where the best
  model is also quick. A single run of the first clip on GPU includes some warm-up (0.5 s for `base.en` 3 s clip vs 0.15 s when repeated).
- **Misses without a prompt are task ids and a fused word**: `base.en` "ytask b162" for "why task B162"; `small.en` "taskr16";
  with the prompt `Task ids like R16, B162, T19, F106, R15. Words: Talk, Kokoro, Piper, iPhone, agent-runner, Hold.` both are
  correct. The prompt cost no real time (with-prompt times are within about 0.1 s on CPU, and on GPU `sum.py` prints them). One counter-case: `small.en` m10 went 0 % -> 8.3 % with the prompt (a single word) on
  both engines, so a prompt is not free of risk on every model, which is another reason not to use `small.en`.
- **Hallucination on a longer clip**: faster-whisper `base.en` on the 24 s clip with 0.5 s lead added a made-up sentence
  ("if you have any questions or comments please contact us at …": 32.9 % error); the same clip with the prompt was clean.
  A known Whisper habit on short or quiet tails: whisper.cpp's output was clean in every run here, but F161 should still trim
  silence and cap the length, and drop a transcript when there was no speech.
- **Container and codec do not matter to accuracy**: for turbo the AAC and Opus copies scored the same 0.4 % as WAV; for `base.en`
  3.6 % against 2.2 % WAV without prompt (one word on one clip), so no real effect. All of `ffmpeg -i x.m4a|x.webm -ar 16000 -ac 1 x.wav`
  worked. A fragmented MP4 (`-movflags frag_keyframe+empty_moov+default_base_moof`, what a timesliced MediaRecorder writes) also decoded, whole, 9.40 s.

First-word check: in the 9 no-prompt clips per row where the speech starts at the first sample (3 texts x WAV, AAC, Opus), every engine and model got the first word. The same 9.4 s phrase
with its front cut off, on `base.en` and turbo (whisper.cpp Vulkan): cut 0.15 s: complete; cut 0.3 s: "check why task…" (loses "Please");
cut 0.5 s: "YTask B162…" with `base.en`, "why task B162…" with turbo. So **the engine reads what it is given; the loss happens
before the engine** if the page starts recording late.

### Recommendation

| Machine | Engine and model | Prompt | Timing |
|---|---|---|---|
| has a GPU whisper.cpp can use (Vulkan) | whisper.cpp, `ggml-large-v3-turbo-q5_0` | yes | 0.5-0.7 s |
| CPU only | whisper.cpp, `ggml-base.en` | yes | 0.3-0.6 s; 0.4 % with the prompt on clean clips, probably worse than turbo on real phone speech (not measured) |

Run `whisper-server` (it ships in the same build, loads the model once, `POST /inference`) as the run's optional engine,
as F158's engine is optional, and have the run say plainly when it is missing. Configuration: model path and prompt in the run's
config; the prompt is built from the run's open task ids plus a fixed word list. Where the person's machine has no GPU, offer `base.en`
only; where it has one, offer turbo. Not measured: `whisper-server` itself (HTTP overhead, keeping the model resident), ROCm/HIP,
memory use, many clips at once, and `distil-whisper`, `Moonshine`, `Vosk`, `Parakeet` (not tried: Whisper already hits 0.4 %, the
open question is the phone's audio, not the engine).

## 4. iPhone Safari: recording, and keeping the sound before the press

From sources, **not verified on a phone**:
- **MediaRecorder on iOS Safari** has existed since iOS 14.3 (MDN compat data: `safari_ios` version_added 14) and produces
  `audio/mp4` (AAC-LC) by default; `isTypeSupported('audio/webm')` is false before Safari 18.4. Since Safari 18.4 it also
  writes WebM with Opus and fragmented MP4, and ALAC/PCM
  (https://webkit.org/blog/16574/webkit-features-in-safari-18-4/, fetched 2026-11-23). The person's Safari is 27.0.1 (from B178), so
  both exist. Ask `MediaRecorder.isTypeSupported` and take the first of `audio/mp4`, `audio/webm;codecs=opus`.
  The run decodes whatever arrives with `ffmpeg` (tested above for AAC/MP4, Opus/WebM, and fragmented MP4).
- **Pre-roll**: a MediaRecorder cannot give sound from before `start()`. The page needs the mic stream open (the F161 text:
  only while Talk shows, released when it hides) and a ring buffer. Two ways: (a) an `AudioContext` with an `AudioWorklet` writing
  mono Float32 into a ring of about 1.0-1.5 s, and on Tap/Hold the page takes the ring contents and keeps appending until
  release, then sends 16 kHz 16-bit WAV (about 32 KB/s, 30 s is under 1 MB, and no codec to guess); (b) MediaRecorder running all the
  time with `start(250)` timeslices and the page keeping only the last few chunks. (b) is worse: a fragmented-MP4 chunk is not decodable
  without the first (init) chunk, so each clip must be built from the init segment plus the recent chunks and has codec priming at
  its start. **Recommend (a).** Resample to 16 kHz in the worklet or on the run (`ffmpeg`).
- **iOS audio session** (from memory of how WebKit behaves, not checked here): an open `getUserMedia` capture puts the page's audio
  session into play-and-record, which on iPhone can lower the output volume or move it to the quiet receiver speaker instead of the loudspeaker,
  can switch Bluetooth earbuds from the high-quality profile to the low-quality hands-free one (their audio goes thin and mono) and keeps
  the orange mic indicator on while Talk shows. This is likely related to **B178** (earbuds disconnecting, speech playing in bits), and
  must be checked before F161 holds the mic open. Opening the mic only on press (as today) avoids the long indicator but loses the
  pre-roll, so there is a real trade: **either a pre-roll with the mic open, or a clean audio session**. Option in between: open the
  mic when Talk shows and the person is *not* playing speech, close it while a reply plays.
- **Allow prompts**: iOS Safari asks for the mic per page load unless the stream stays open; a page that keeps the stream is
  asked once. I did not touch the test iPhone's Allow prompts (nothing here was tried on a phone), and F161 must not re-request
  the stream more than once per Talk opening.
- AudioContext on iOS starts `suspended` and must be `resume()`d in a tap handler; it runs at the hardware rate (48 kHz or 44.1 kHz),
  not 16 kHz.

### Measured on an iPhone 15 (F161c3)

A standalone test page over https with the same stream and worklet setup (not the run app itself): iPhone 15 Pro, Safari 27.0.1, 2026-11-25.
Real taps by WebDriverAgent, speaker, reply = a 4 s clip. Time = press to the first non-silent 2048-sample piece.

- Fresh open, page already allowed: 377-434 ms; second press on the open stream: 42-46 ms.
- After a reply: closed, then reopened by the press: 461 ms (1 run). Closed, then reopened when the reply ended: the reopening takes about 0.5 s, then the press 46-49 ms (2 runs).
- Kept (track off, AudioContext running, audio session playback): 47, 51, 48 ms. Track off, session play-and-record: 47, 46, 45. Stream untouched, session playback: 48, 47.
- Cutting a reply off: closed 1133-1141 ms (3 runs, 2 of them of the reopen variant; all reopened in the press); kept 77-80 ms.
- Context suspended (the old rest): first piece after 822-1009 ms (one 122 ms, with the track left on), and only silence (exact zeros for 4 s) in 6 of 8 presses, in all 4 with the track off too (the old rest). Two fresh opens just after a load were as silent, so what causes the silence is not known; none of the 9 presses whose context kept running, after a reply, and none of the 9 that cut one off, were silent.
- Reply start delay: 64-81 ms kept; 87-316 ms closed; 745-821 ms suspended.

Not measured: loudness of replies while the stream rests, earbuds (hands-free profile), and a person speaking. The 1.57 s report is not reproduced by these numbers; the closest is 1.14 s for a cut. An early run whose taps hit the wrong buttons was discarded.

## 5. Why Safari's own recognition misses the first word (not a finding about the engine)

`webkitSpeechRecognition.start()` takes some time before it listens, and nothing is kept from before it. Pre-roll in the page only helps
Recorded; Safari's recognition cannot be given earlier sound. Not measured here (no phone).

## 6. Check for the person's phone: the same phrases both ways

(for F161's CONFIRM, nothing to run now)

1. In Talk, with Recorded set, say each phrase starting the instant you press and without a pause. Then the same phrase with the
   browser's recognition. Write down which words each shows.
2. Phrases, with the first word marked: **Open** task R16. / **Please** check why task B162 heard nothing. / **Merge** the branch when the
   gate passes. / **Start** with the plan list. / **Hold** on, say that again. (a one-word clip) / a 20 s phrase of three sentences.
3. For each way and each phrase, note: first word there (yes/no), words right (all / some), seconds from letting go to words.
4. While a reply is read aloud, say a phrase (mic open at the same time): is the reply still heard, at the same volume, and do earbuds
   switch to the thin hands-free sound?
5. With earbuds connected, open Talk and wait 10 s without speaking: does the audio sound change? (checks the open-mic cost, B178)

## 7. Commands and files

`docs/research/R16-samples/`: `mk.py` (the clips, from the Kokoro files), `bench.py` (`python bench.py bcpu|bvk|fw`), `sum.py` (the tables above
from the three result files). Run in a scratch venv with `kokoro-onnx soundfile jiwer faster-whisper "av<16"`:

```
# the copies (run in clips/): AAC as iPhone Safari makes, Opus, and a fragmented MP4 as a timesliced MediaRecorder writes
ffmpeg -i x.wav -ar 48000 -c:a aac -b:a 64k x.m4a
ffmpeg -i x.wav -ar 48000 -c:a libopus -b:a 32k x.webm
ffmpeg -i x.wav -ar 48000 -c:a aac -b:a 64k -movflags frag_keyframe+empty_moov+default_base_moof -f mp4 x_frag.mp4
ffmpeg -i in.m4a -ar 16000 -ac 1 out.wav
whisper-cli -m ggml-large-v3-turbo-q5_0.bin -f out.wav -nt -np -t 8 -l en --prompt "Task ids like R16, B162, T19, F106, R15. Words: Talk, Kokoro, Piper, iPhone, agent-runner, Hold."
```

Caveats: for m4a/webm, whisper.cpp times in `bench.py` exclude the `ffmpeg` decode (about 0.1 s) and process start; faster-whisper was
CPU only (its pip CTranslate2 has no AMD GPU build); the "30 s" clip is 23.8 s. `bench.py` expects `clips/` beside it and the models in `models/`,
`whisper.cpp` built in `wcpp/bcpu` and `wcpp/bvk`; `mk.py` writes into the current directory (run it inside `clips/`).
The scripts hold absolute scratch paths from this run's directory; change `S` and the clips directory to reuse them. Raw
results are not committed (58 KB of JSON): rerun `bench.py`.
