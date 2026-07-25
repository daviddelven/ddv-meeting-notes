# ddv-meeting-notes

Local meeting capture for Linux (PipeWire): records your microphone and the system audio output as two separate tracks during an online meeting (Microsoft Teams, Google Meet, anything that plays through your speakers or headset), transcribes both tracks locally, and produces structured Markdown notes on disk.

Built because meeting notetakers that capture system audio on macOS and Windows generally do not exist or do not work on Linux desktops. No bots joining your calls, no audio leaving your machine for transcription.

## How it works

- `meeting start [name]` resolves your current default source (microphone) and the default sink's monitor (what you hear) at record time, and records them as two separate 16 kHz mono WAVs into a spool directory. Recording is detached and survives closing the terminal. If you don't pass a name, it looks for a Google Calendar event live right now on your primary calendar (via the `gws` CLI — npm package `@googleworkspace/cli` — if installed and authenticated) and uses its title; otherwise it falls back to "meeting". While either track is recording, sleep and idle are inhibited via `systemd-inhibit` (scoped to the recorder process itself, released automatically the moment it stops; skipped with no error if `systemd-inhibit` isn't available).
- `meeting toggle` starts a recording if idle, or stops the current one if recording. Meant to be bound to a keyboard shortcut (see Keyboard shortcut below).
- `meeting watch` runs in the foreground and sends a desktop notification when it looks like a meeting just started, without ever recording on its own (see Meeting-start notifications below).
- `meeting stop` ends both recorders and runs the pipeline: each track is transcribed separately with [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (CPU, int8), so the microphone track becomes "Me" and the system track becomes "Others" — two-speaker attribution without diarization, since conferencing apps never play your own voice back. The merged, timestamped transcript is summarized into structured notes by headless `claude -p` (Claude Code subscription; no API key), in the transcript's dominant language unless `[summary] language` overrides it. Everything is archived as:

```
archive/2026/07/25/1030-roadmap-planning-a1b2c3d4/
  meeting.json    # metadata: name, times, duration, devices
  transcript.md   # timestamped, speaker-labeled transcript
  meeting.md      # structured notes: summary, decisions, actions, open questions
  mic.wav
  system.wav
```

Set `[retention] delete_audio_after = true` to drop `mic.wav`/`system.wav` once transcription is done instead of archiving them — the archive then keeps only the three text files. `meeting cleanup` additionally deletes `transcript.md` (never `meeting.md`, never audio) from archived meetings older than `[retention] transcript_days` (0 = disabled); run it by hand or from cron.

If transcription or note-generation fails (auth expired, network blip, rate limit, whatever), the recording is left exactly as-is in the spool directory — nothing is deleted, nothing is archived — and you get a desktop notification plus the exact command to re-run processing by hand once the underlying problem is fixed: `python3 pipeline/process.py <spool-dir>`.

An optional mirror copies the three text files (never audio) to a second folder, e.g. a cloud-synced drive. A `[hooks] on_archive_change` command, if set, runs (best-effort, never blocking the archive) after each meeting is archived — see `config.example.toml` for the environment variables it receives.

The spool-then-archive lifecycle and the data model are borrowed from Andre Foeken's meeting-notes (see Credits).

## Requirements

- Linux with PipeWire (or PulseAudio) — uses `pactl` and `parecord`
- Python 3.11+
- `ffmpeg` (only for the audio checks described below), `notify-send` (optional, desktop notifications)
- [Claude Code](https://claude.com/claude-code) CLI, authenticated, for the notes step
- `gws` (optional — npm package `@googleworkspace/cli`, authenticated), for automatic meeting titling from your calendar. Without it, `meeting start` with no name just uses "meeting".
- `systemd-inhibit` (optional — part of systemd, present on most desktop distros), to hold off sleep/idle while recording. Without it, recording still works, just without the wake-lock.

Transcription is CPU-friendly: measured on an i7-8550U ultrabook (8 threads, no usable GPU), the `small` model at int8 does one minute of audio in about 15.5 seconds (RTF 0.26).

## Install

```bash
git clone https://github.com/daviddelven/ddv-meeting-notes
cd ddv-meeting-notes
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
ln -s "$PWD/bin/meeting" ~/.local/bin/meeting
```

Optional configuration (paths, whisper model size, notes persona/language, mic override, retention, hooks — see `config.example.toml` for the full list):

```bash
mkdir -p ~/.config/ddv-meeting-notes
cp config.example.toml ~/.config/ddv-meeting-notes/config.toml
```

## Use

```bash
meeting start client-roadmap   # before joining the call
meeting status
meeting stop                   # after hanging up; transcribes, summarizes, archives
```

Verify your setup once: record a short test while audio plays, then check both WAVs actually contain sound (`ffmpeg -i mic.wav -af astats -f null -` and look at `RMS level dB`; a silent track shows `-inf`). See LESSONS.md for why you should not trust file sizes.

## Keyboard shortcut (Cinnamon)

`meeting toggle` is meant to be bound to a key so you can start or stop recording without switching to a terminal. On Cinnamon, add a custom keybinding pointing at your `meeting` symlink. `custom-list` is shared with every other custom shortcut you already have, so append to it rather than overwriting it outright:

```bash
list="$(gsettings get org.cinnamon.desktop.keybindings custom-list)"
n=0
while [[ "$list" == *"'custom$n'"* ]]; do n=$((n+1)); done
slot="custom$n"
if [[ "$list" == "@as []" || "$list" == "[]" ]]; then new_list="['$slot']"; else new_list="${list%]}, '$slot']"; fi
gsettings set org.cinnamon.desktop.keybindings custom-list "$new_list"

schema="org.cinnamon.desktop.keybindings.custom-keybinding:/org/cinnamon/desktop/keybindings/custom-keybindings/$slot/"
gsettings set "$schema" name "Toggle meeting recording"
gsettings set "$schema" command "$HOME/.local/bin/meeting toggle"
gsettings set "$schema" binding "['<Super><Shift>r']"   # pick something free -- see below
```

Check for a collision before running it: `gsettings get org.cinnamon.desktop.keybindings.wm '<key>'` and the same for `.media-keys` and `.muffin.keybindings`, for every key you're about to bind — or just try the combination in Cinnamon's own Keyboard settings first. Cinnamon's built-in screen-recording toggle already uses `<Control><Shift><Alt>r`, so `<Super><Shift>r` above is deliberately a different combination. Takes effect immediately, no restart needed. For other desktop environments, bind the same command (`meeting toggle`, or the absolute path to the `meeting` script) through whatever custom-shortcut mechanism your DE provides.

## Meeting-start notifications

`meeting watch` runs in the foreground, listens for new PipeWire capture streams via `pactl subscribe`, and sends a desktop notification when a browser or the Teams `--app` window starts using the microphone — the strongest local signal that a call has actually begun. It never starts a recording by itself; it only suggests running `meeting start`. Recordings already in progress, and its own capture streams while one runs, are ignored.

Run it in a terminal to try it (`Ctrl+C` to stop), or keep it running in the background with a systemd user service:

```bash
mkdir -p ~/.config/systemd/user
cp systemd/ddv-meeting-watch.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now ddv-meeting-watch.service
```

`systemctl --user status ddv-meeting-watch.service` to check it, `systemctl --user stop ddv-meeting-watch.service` to stop it (this also stops its `pactl subscribe` child — systemd kills the whole service cgroup).

`meeting watch`'s pattern currently recognizes Chrome/Chromium, Firefox and Teams; broadening it to other conferencing apps needs their real PipeWire `application.name`/`application.process.binary` values captured during an actual call (see LESSONS.md), not assumed strings.

## Retention and cleanup

- `[retention] delete_audio_after = true` drops the WAVs right after transcription instead of archiving them.
- `[retention] transcript_days = N` plus `meeting cleanup` deletes `transcript.md` (never `meeting.md`, never audio) from archived meetings older than N days. Not run automatically — call it by hand, or from cron:

```
0 4 * * * /path/to/ddv-meeting-notes/bin/meeting cleanup
```

## Credits

The design of this tool — the spool/archive directory lifecycle, the per-meeting metadata file, and the separation of capture, transcription and enrichment — comes from [meeting-notes](https://github.com/foeken/meeting-notes) by **Andre Foeken**, a macOS menu-bar app that solves the same problem with ScreenCaptureKit and local models. This project is an independent Linux reimplementation inspired by that design; it is not a port and reuses none of its code.

## License

MIT — see [LICENSE](LICENSE).
