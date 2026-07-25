# Lessons

One lesson per section, one-line summary up front. Technical only; anything tied to a specific person, organization or meeting stays out of this file.

## A "verified" recording can be absolute silence: always check RMS, then play it back

An early test produced a system-output WAV with plausible size and correct duration whose content was pure silence (RMS −inf): nothing had been playing through the sink while it recorded, and the session that created it still reported capture as "confirmed". File existence, size and duration prove nothing about content. Valid check: `ffmpeg -i f.wav -af astats -f null -` and read `RMS level dB` (a track with speech sits around −20 to −35 dB), then actually play an excerpt. Why it matters: without this check the whole pipeline "works" and silently delivers half a meeting (your voice, no far side).

## openai-whisper and faster-whisper are not "the same local Whisper": 5x apart on the same CPU

Measured on an i7-8550U ultrabook (8 threads, CPU only, no usable GPU), same real 221.8 s recording, same `small` model:

- openai-whisper (reference Python implementation, fp32): more than 300 s, RTF > 1.35. Unusable.
- faster-whisper 1.2.1 (CTranslate2, int8): 57.5 s, RTF 0.26, i.e. 15.5 s of compute per minute of audio. A one-hour meeting transcribes in about 16 minutes.

"Local Whisper is too slow on this machine" was true only for the first implementation, and nearly forced an unnecessary cloud dependency and API key. Measure the engine, not the model family.

## Check what model weights already exist on disk before downloading more

Whisper weights accumulate: dictation apps leave ggml files (whisper.cpp format), other tools populate `~/.cache/huggingface/hub` (CTranslate2 format for faster-whisper). The two formats are not interchangeable, but the Hugging Face cache is shared across venvs, so a new virtualenv re-downloads nothing if another tool already fetched the model.

## Resolve PipeWire devices at record time, never pin them

Use `pactl get-default-source` and `$(pactl get-default-sink).monitor` at the moment recording starts. Pinning a device name (or grabbing "the first .monitor" in the list) records the wrong device the day a Bluetooth headset or HDMI output is connected. Observed live: the default sink switched to a Bluetooth device between two recordings minutes apart, and the monitor followed correctly because it was resolved late. The default sink's monitor is where the meeting actually sounds.

## Whisper hallucinates language and text on degraded speech-like audio

A mic track that contained only muffled speaker bleed (nobody talking at the mic) got autodetected as Farsi with an invented segment in Arabic script; a system track holding only meeting join/leave chimes produced hallucinated "you" tokens when VAD was disabled. Known Whisper behavior on degraded or non-speech audio, not a pipeline bug: with real direct voice both effects disappear. A single bizarre orphan segment in an otherwise silent track is a test artifact, not something to patch with heuristics.

## Record straight to 16 kHz mono s16le: same transcription, 12x less disk

Whisper resamples everything to 16 kHz mono internally. `parecord --rate=16000 --channels=1 --format=s16le` skips a conversion step and keeps one hour of meeting at ~115 MB per track instead of ~1.3 GB (stereo 48 kHz s32).

## Conferencing echo suppression gives you free speaker attribution

Meeting apps never play your own voice back to you, so the microphone track contains only you and the sink-monitor track contains only the far side. Transcribing the two tracks separately and merging by timestamp yields a two-speaker labeled transcript with no diarization at all. (If you talk near two joined devices at once, the same sentence legitimately appears on both tracks: that is the meeting's real audio, not a bug.)
