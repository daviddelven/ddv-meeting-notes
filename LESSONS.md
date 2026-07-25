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

## `pactl` output is locale-dependent: force `LC_ALL=C` before parsing it

`pactl subscribe` and `pactl list` translate their output into the user's configured locale (`Event 'new' on source-output #807` becomes `Esdeveniment 'nou' en source-output #807` under a Catalan locale, for example). Any script that greps or pattern-matches `pactl` text output will silently stop matching on a differently-configured machine. Fix: prefix the invocation with `LC_ALL=C` (`LC_ALL=C pactl subscribe`, `LC_ALL=C pactl -f json list source-outputs`) to force English output regardless of the user's locale. `pactl -f json ...` sidesteps the problem entirely for structured queries, but `subscribe` has no JSON mode, so its event lines still need the `LC_ALL=C` treatment.

## `setsid cmd &` forks and returns immediately: `$!` is not the detached process's PID

By default `setsid(1)` calls `fork()` and the wrapper process exits as soon as the child is spawned, unless invoked with `-w`/`--wait`. So `setsid long_running_cmd & pid=$!; sleep 2; kill -0 "$pid"` reports the process as dead almost immediately, even though the actual detached command is alive and well in its new session under a different PID. This is by design (it is what lets the parent shell's job control show the job as "Done" right away while the payload keeps running detached), but it means `$!` right after `setsid cmd &` is useless for tracking or killing the real process; use `pgrep -f` against the command, or don't detach through `setsid` at all if you need to hold a live PID.

## PipeWire capture-stream properties tell you which app just grabbed the microphone

`pactl -f json list source-outputs` exposes, per active capture stream, `properties["application.name"]` and `properties["application.process.binary"]` — e.g. a browser tab requesting `getUserMedia` audio shows up with `application.name` like "Google Chrome". Combined with `pactl subscribe` reporting `Event 'new' on source-output #N` the instant such a stream appears, this is a reliable, local, zero-network signal that some application just started listening to the microphone — a good proxy for "a call just started" without hooking into any specific conferencing app's API.

## A `pactl subscribe | while read` loop can't be cleanly killed; process substitution can

Piping a long-running producer into `while read; do ...; done` runs the loop body in a subshell (bash forks one to service the pipe), so a `trap ... EXIT` set in the enclosing function is invisible to it, and killing the function's own PID leaves the piped producer (and the subshelled loop) as orphaned background processes. Using process substitution instead — `exec {fd}< <(producer); pid=$!; trap 'kill "$pid"' EXIT INT TERM; while read -r line <&"$fd"; do ...; done` — keeps the loop in the *same* shell (so accumulated state like a cooldown timestamp survives across iterations) and gives a real PID to `$!` immediately after starting the substitution, which the trap can then reliably kill on any exit path. (Under `systemd --user`, `systemctl stop` kills the whole service cgroup regardless, so this only matters for processes started and killed manually.)

## `systemd-inhibit` forks its argument as a child; killing the wrapper kills the child too

`systemd-inhibit --what=sleep:idle -- CMD` does not `exec()` into `CMD`, replacing itself; it forks a child, execs `CMD` in the child, holds the inhibitor lock in the parent, and waits. This matters when a script tracks and later kills the wrapper's PID (as opposed to the payload's own PID) to stop a detached recorder: verified empirically (`ps --ppid` showing `systemd-inhibit` as the direct parent of the wrapped command, then `kill -TERM` on the `systemd-inhibit` PID killing both processes) that a plain `SIGTERM` to the wrapper propagates to and terminates the child, releasing the inhibitor lock in the same step. Wrapping an existing `setsid CMD &` launch with `systemd-inhibit` (`setsid systemd-inhibit --what=... -- CMD &`) is therefore safe to bolt onto code that already tracks and kills that PID: no separate lock-release step is needed, and the existing kill logic keeps working unchanged.

## A chat/conferencing app must actually open a mic capture stream before `pactl` shows its `application.name`

Launching an Electron-based chat app (tested with a fresh, logged-out Discord Flatpak install) produces zero PipeWire clients and zero source-outputs until the app actually requests microphone access — which for most of these apps only happens once you join a call/huddle from inside a logged-in session, not merely by starting the app or reaching its login screen. `pactl -f json list clients` stayed limited to system services (PipeWire itself, WirePlumber, the desktop shell) the entire time the app sat on its splash/login screen. Consequence for any app-detection pattern keyed on `application.name`/`application.process.binary` (like `meeting watch`'s `MEETING_APP_PATTERN`): the only reliable way to learn the real string is to capture `pactl -f json list source-outputs` (or `pactl subscribe` for the live event) while a real call/huddle is active in that app, not by inspecting the installed binary, its `.desktop` file, or its idle process list.

## A Calendar `events.list` window just needs to contain "now" to catch what's live right now

The Google Calendar API's `timeMin`/`timeMax` filter matches events by overlap with the query window (`event.end > timeMin AND event.start < timeMax`), not by requiring the event's start to fall inside the window. So to find whatever event is happening at this exact moment, the window's exact width barely matters — any window that contains the current instant (even ±1 minute) will surface an in-progress event of any duration, because an event containing "now" trivially satisfies both bounds. A wider window (e.g. ±30 minutes) is only useful defensively, against clock skew between client and server.
