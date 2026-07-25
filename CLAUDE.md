# ddv-meeting-notes

Linux (PipeWire) meeting capture: mic + system-output as two separate tracks, local faster-whisper transcription (small/int8/CPU, measured RTF 0.26 on an i7-8550U), structured notes via headless `claude -p` (subscription auth only — never the Anthropic API), spool → archive lifecycle. Design borrowed from foeken/meeting-notes (macOS); independent reimplementation, not a port.

- Entry point: `bin/meeting` (start/stop/status). Pipeline: `pipeline/process.py`, venv in `.venv/`.
- User configuration (paths, model, notes persona, optional text-only mirror) lives in `${XDG_CONFIG_HOME:-~/.config}/ddv-meeting-notes/config.toml` — git-ignored by design; the committed `config.example.toml` is the reference. Never hardcode personal paths or identity in tracked files.
- This repo is built as-if-public (MIT): never commit audio, transcripts, generated notes, secrets, or anything identifying a client or tenant. Test fixtures are synthesized, never real captures.
- Capture verification discipline: a WAV with plausible size proves nothing. Check `RMS level dB` via ffmpeg astats AND play an excerpt back before claiming capture works.
- Read LESSONS.md before touching audio capture; it encodes measured decisions (engine choice, device resolution, sample rate).
