# R15: a good read-aloud voice for Talk on an iPhone

Question: Talk's spoken replies on an iPhone sound bad and are not the Siri voice. How can Talk have a good voice there?
No product code changed; this is research only.

## Verdict

1. **The real Siri voice cannot be used by a web page.** Safari gives a page only the system voices that
   `AVSpeechSynthesisVoice.speechVoices…` returns, and Siri's own voices are not among the voices Apple hands to apps.
   Nothing a page does changes that.
2. **Talk today asks for no voice at all**, so it gets the iPhone's default voice for the page language, which is
   the low-quality one. `pickVoice` never chooses: it only looks up a name the person saved in Settings, so with none saved
   every better listed voice is passed over (not by a rule, by there being none) (`agent_runner/web_page.html:575`, `speak()` at `:1758`).
3. **Best fix: speech made on the run's machine and played by the page as audio.** Kokoro and Piper both run
   on this machine's CPU with no GPU, far faster than real time, and sound much better than an iOS default voice
   (play them: sample page below).
   They also give the same voice on every device, and an audio element is a better start for B166 than speechSynthesis.
   Recommendation: **Piper `en_US-lessac-medium` or `en_GB-alba-medium` first** (fast, small, free), **Kokoro
   `af_heart` if the person wants the most natural voice** (about 5-8x slower, 354 MB, still fine for a reply).
4. A paid service is not needed, and would send every reply's text off the machine.

## 1. What iOS Safari gives a page (from sources, not measured on a phone)

- WebKit lists voices in `PlatformSpeechSynthesizer::initializeVoiceList()`: it calls
  `speechVoicesIncludingSuperCompact` and `appendVoices` keeps a voice only `if (voice.isSystemVoice)`.
  Source: WebKit `Source/WebCore/platform/cocoa/PlatformSpeechSynthesizerCocoa.mm` (lines 341-375, fetched 2026-11-23,
  https://github.com/WebKit/WebKit/blob/main/Source/WebCore/platform/cocoa/PlatformSpeechSynthesizerCocoa.mm).
- Apple's API behind it, `AVSpeechSynthesisVoice.speechVoices()`, is documented as "all available voices on the device",
  each with a language, locale and a quality (default, enhanced, premium)
  (https://developer.apple.com/documentation/avfaudio/avspeechsynthesisvoice). So Enhanced and Premium voices a person
  downloaded under Settings > Accessibility > Spoken Content > Voices are *in principle* listed; the page sees one
  entry per voice with a `name` and `lang` but **no quality field** (WebKit passes only identifier, name, language).
  Whether a given downloaded voice shows up, and which name it has, depends on the iOS version: only the person's
  phone can say, which is why the sample page below lists the phone's own voices.
- Siri's voices (the ones Siri itself speaks with) and Personal Voice are separate system voices that Apple does not
  include in that list. This is Apple's design, not a WebKit gap I could find a switch for. I could not read a
  sentence from Apple saying so in one place, so treat "Siri cannot be used" (also point 1 of the verdict) as established by absence in the API
  and by the WebKit code above, and confirm it on the phone with the page below (Siri's name is not in the list).
- With no voice set, WebKit speaks with `voiceWithLanguage:` for `utterance.lang` (same file, lines 151-168): Apple's
  default for that language, which on a phone is usually the compact voice. That is what Talk does today, and it is
  the "really bad" voice. Choosing a better listed voice by name in Talk's Settings (the Voice picker, `TS.voice`) is
  already possible and costs nothing; Talk just never picks one by itself. A cheap partial fix is to pick the best
  English voice (names with "Enhanced", "Premium", Samantha, Daniel, Ava…) automatically. It can not match the
  samples below, and can not be checked here, only on a phone.

## 2. Speech made on the run's machine, played in an `<audio>` element

Measured on this machine (Linux, 16 threads, CPU only, other agents running, so times are a bit pessimistic), Python
3.14 with `piper-tts` 1.8.0 and `kokoro-onnx` 0.6.1. Text: a 3-sentence Talk reply. "Opening" is the time to make the first two sentences (about 7-9 s of audio) in one
call, the time-to-first-sound if the page asks for the opening first; "reply" is the time for the whole reply of
the given audio length. Piper's first chunk (one sentence) alone came after 0.05-0.21 s. Model load: 0.15-0.32 s (once).

| Voice | Size on disk | Opening | Whole reply | Audio length | Licence |
|---|---|---|---|---|---|
| Piper en_US-lessac-medium | 63 MB | 0.22 s | 0.33 s | 13.6 s | voice data: Blizzard 2013 licence (Edinburgh CSTR) |
| Piper en_US-amy-medium | 63 MB | 0.30 s | 0.40 s | 17.3 s | voice data: Mimic3 voices, Mimic3 voices repo, licence not checked |
| Piper en_GB-alba-medium | 63 MB | 0.17 s | 0.33 s | 15.3 s | CC BY 4.0 (credit needed) |
| Piper en_US-ryan-high | 121 MB | 0.80 s | 1.33 s | 12.5 s | **CC BY-NC-SA 4.0: not for commercial use** |
| Kokoro af_heart | 326 MB model + 28 MB voices (all voices) | 1.5 s | 1.9 s | 14.9 s | Apache 2.0 weights |
| Kokoro af_bella / bm_george / am_michael | same files | 1.5-1.7 s | 2.1-3.1 s | 15-17 s | Apache 2.0 weights |

- Piper speaks about 40x faster than real time here, Kokoro about 7x. Both are well under the time a Talk reply
  already takes to arrive. Even Kokoro's whole reply (1.9 s) is made in less time than its opening takes to play (7 s), so
  playing in two parts would sound continuous.
- Install per platform: the python packages are pure pip installs (`pip install piper-tts` 46 MB, plus
  `onnxruntime` 73 MB; the venv came to 205 MB). Voice files are plain downloads (Piper from
  https://huggingface.co/rhasspy/piper-voices, Kokoro from
  https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.0). Both ship for Linux, macOS (including
  Apple silicon) and Windows via onnxruntime; I only ran Linux. Neither needs a GPU, an account or the network after
  the download.
- Licence notes: `piper-tts` 1.8.0 is **GPL-3.0-or-later** (its metadata; it bundles espeak-ng). Run as a separate
  program on the person's own machine this is fine; it matters only if the project is shipped linked with it.
  `kokoro-onnx` is MIT and the Kokoro weights are Apache 2.0 (https://huggingface.co/hexgrad/Kokoro-82M), the
  cleanest licence of the set.
- Quality: judged by ear, so it is the person's call: play the 8 clips on the phone. My expectation, from the
  clips: Kokoro `af_heart` is the most natural; Piper `lessac` and `alba` are clear and plain, clearly better than
  iOS compact voices and they never change with the phone.
- Paid services (not measured, no text was sent anywhere): cloud engines (OpenAI, ElevenLabs, Google, Azure) give
  the best voices but every reply's text leaves the machine, need a key and cost per character (their prices were not looked up); Kokoro itself is
  priced by hosts at under $1 per million characters (Hexgrad's model card, April 2025, which also says on average
  1000 characters are about one minute of audio). A Talk reply is a few hundred characters, so the cost would be
  small, but a local engine is as good for this and keeps the text at home. Only with the person's OK.

### How the page would play it

The run page asks the run for a clip (`POST text`, get an mp3/wav) and plays it in one reused `<audio>` element,
one sentence at a time, so the first sound comes after one short request. No hosted service: the same run that
serves the page makes the sound.

## 3. Is an audio element easier to start by itself on iOS (B166)?

Yes, and for a stated reason in WebKit:

- For speech, WebKit requires a user gesture for the first utterance when the document requires one for audio
  (`SpeechSynthesis.cpp` lines 66-69: `RequireUserGestureForSpeechStart`), and drops that restriction once a
  gesture-time `speak()` happens (lines 166-168). That is the unlock `unlockSpeech()` does, and B166 suspects it is
  called outside a tap.
- For an `<audio>` element, WebKit removes the user-gesture restrictions **on that element** after the first
  `play()` or `load()` made inside a gesture (`HTMLMediaElement::removeBehaviorRestrictionsAfterFirstUserGesture`,
  `Source/WebCore/html/HTMLMediaElement.cpp` ~lines 1125, 1743, 9525:
  https://github.com/WebKit/WebKit/blob/main/Source/WebCore/html/HTMLMediaElement.cpp). The element can then be given
  a new `src` and `play()`ed later with no tap, for example when the next reply arrives. So: one tap on the speaker
  button plays a silent clip in a single long-lived `<audio>` and every later reply is played by that same element.
  The same trick is the widely used workaround, and the code above shows why it works.
- Not proven on a phone: the iPhone's silent switch, an audio session left in capture by the mic (B132/B166) and
  lock-screen behaviour still apply to media, so the check on the person's iPhone has to include "a reply arrives
  by itself after the mic turned off". I did not test on iOS (no device here).
- Side benefits: `onended` gives a real end event (speechSynthesis often gives none on iOS), and one voice means
  no per-phone voice list to handle.

## Sample page (play on a phone)

Page with all clips and the phone-voice buttons: https://claude.ai/artifact/SPykufB1YF46QQjzJj4uDz (private; open it signed in).

- Eight clips of the same text, mono mp3, 56 kbit/s (Piper) or 64 kbit/s (Kokoro), in `docs/research/R15-samples/`
  (`en_US-lessac-medium`, `en_US-amy-medium`, `en_GB-alba-medium`, `en_US-ryan-high`, `kokoro_af_heart`,
  `kokoro_af_bella`, `kokoro_am_michael`, `kokoro_bm_george`). Total 850 KB.
- The page published with them also has buttons that speak the same text with each voice **the phone's own Safari
  lists**, and shows how many: this is the measurement of section 1 that only a phone can give.

## Round two (2026-11-23): the person chose Kokoro `af_heart` as default; are there better ones?

Decision from the person: use our options, with Kokoro `af_heart` as the default. So the Recommendation section below
(written before) is **superseded where it says Piper first**: default `kokoro af_heart`, with Piper `lessac` as the
light option.

Measured again on this machine (CPU only, one run each, a new 3-sentence text, 8.6 s of audio for `af_heart`; after one warm-up call):

| Voice | Time for the whole reply | Audio length | Size | Licence |
|---|---|---|---|---|
| Kokoro af_heart | 1.0 s | 8.6 s | 354 MB (all 54 voices included) | Apache 2.0 |
| Kokoro af_bella / af_sarah / af_sky / af_aoede / af_kore | 1.3-1.5 s | 8.2-9.4 s | same files | Apache 2.0 |
| Kokoro af_nicole | 2.2 s | 13.8 s (speaks slower) | same files | Apache 2.0 |
| Kokoro bf_emma / bf_isabella / am_fenrir / am_puck / bm_fable | 1.1-1.5 s | 8.0-8.9 s | same files | Apache 2.0 |
| Kokoro blend (mean of af_heart and af_bella style vectors) | 1.0 s | 8.6 s | same files | Apache 2.0 |
| Supertonic 3 `F1`/`F2`/`M1` (`supertonic` 1.3.1, ONNX) | 1.4-1.7 s | 9.7-10.3 s | 165 MB | OpenRAIL (model card `Supertone/supertonic-3`; use restrictions, check before shipping) |

Playable clips: https://claude.ai/artifact/3zyUeY4M7MAbq1xvTaWnGP (same text for all; files `docs/research/R15-samples/r2_*.mp3`).

What I could and could not establish:

- **Within Kokoro, nothing in this table is a speed or size reason to leave `af_heart`.** Every Kokoro voice costs the
  same; which one sounds best is purely by ear, so the page above lets the person pick. The Kokoro voice list ranks
  voices by quality grade and puts `af_heart` first (https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md,
  not re-checked in this run); `af_bella` and `af_nicole` are next. I did not rank by ear.
- **Supertonic 3 is the one other engine I got running.** It is smaller than Kokoro (165 MB), as fast, and has its own
  voices; whether it sounds better is the person's call (clips above). Its licence is OpenRAIL, not Apache.
- **Kitten TTS** (tiny, ~15-80 MB models): `pip install kittentts` worked but it needs a system `espeak` library that
  is not on this machine, so it was **not run**. It is tiny and likely below Kokoro in quality; not measured.
- **Not measured, judged from size and not tried**: Orpheus (3B), Chatterbox, F5-TTS, XTTS-v2, Sesame CSM, Dia. They
  are the "more expressive" open voices, but they are large (hundreds of millions to billions of parameters) and made
  for a GPU; on this CPU-only machine they would very probably take longer than the audio they make, which breaks the
  "first sound quickly" need. I did not install them, so this is an expectation, not a number.
- Paid cloud voices (OpenAI, ElevenLabs, Google, Azure) are the only clearly better-than-Kokoro class I know of, and
  they send each reply's text off the machine; not used, only with the person's OK.
- **Answer**: yes, a few others exist, but none I could run here is clearly better than `af_heart` for its cost.
  Build with `af_heart` as default and let Settings choose any other Kokoro voice (same files, no extra download),
  with an optional per-reply speed. Revisit Supertonic only if the clips above beat `af_heart` for the person.

## Recommendation

(Superseded by round two above where it names the default: the default is Kokoro `af_heart`.)

Build a local voice: **Piper `en_US-lessac-medium` (or `en_GB-alba-medium`) as the default** (0.2 s to first sound,
63 MB, no GPU), with **Kokoro `af_heart` as an option** for the person who wants the most natural one (about 1.5 s
to first sound, 354 MB). Played in one reused `<audio>` element, unlocked by the speaker-button tap. Keep
speechSynthesis as the fallback when the run has no engine installed. Avoid `en_US-ryan-high` (non-commercial
licence, and no faster than the others). A small follow-up, independent of the above, is for Talk to pick the best
installed iOS voice by itself.

## How this was measured

A scratch venv (`uv venv`; `uv pip install piper-tts kokoro-onnx soundfile`), voices downloaded with
`python -m piper.download_voices`, Kokoro files from the release above, one warm-up call each, then timed
`synthesize()` (Piper: time to the first chunk, it yields per sentence) and `create()` (Kokoro: one call per text)
on the 1-sentence and 3-sentence text. One run each: the figures are indicative, not a benchmark.
