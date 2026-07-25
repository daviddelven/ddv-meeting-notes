#!/usr/bin/env python3
"""Process a recorded meeting: transcribe both tracks, merge, summarize, archive.

Input: a spool directory containing meeting.json, mic.wav and system.wav.
Output: an archive directory YYYY/MM/DD/HHMM-name-id/ with transcript.md,
meeting.md (structured notes via headless `claude -p`), meeting.json and the WAVs,
plus an optional mirror of the three text files to a configured folder.
"""
from __future__ import annotations

import datetime
import json
import os
import shutil
import subprocess
import sys
import wave
from dataclasses import dataclass
from pathlib import Path

import config

SUMMARY_PROMPT_TEMPLATE = """{context} Below (stdin) is the transcript of a meeting with two voices: "Me" (the user, captured by the microphone) and "Others" (the remote participants, captured from the system audio output). Speaker labels in the transcript may appear localized.

Write structured meeting notes in Markdown with exactly these sections, translating BOTH the section headings and the content into {language}:

# [short descriptive meeting title]
## Summary
## Decisions
## Actions
## Open questions
## Topics discussed

Rules: be concrete and factual; never invent anything that is not in the transcript; under Actions state who does what when it can be inferred; write "None" (in the transcript's language) for empty sections. Reply ONLY with the Markdown notes, no preamble or closing.

Do not ask for clarification or confirmation. If a step is ambiguous, pick the most conservative interpretation and execute it. Complete all steps sequentially and terminate."""


@dataclass
class Segment:
    start: float
    end: float
    speaker: str
    text: str


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate()


def transcribe(model: "WhisperModel", path: Path, speaker: str) -> list[Segment]:
    raw_segments, info = model.transcribe(str(path), vad_filter=True)
    out = [
        Segment(s.start, s.end, speaker, s.text.strip())
        for s in raw_segments
        if s.text.strip()
    ]
    print(f"  {path.name}: {len(out)} segments, language={info.language}")
    return out


def fmt_ts(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"


def build_transcript(meta: dict, segments: list[Segment], duration: float) -> str:
    lines = [
        f"# Transcript: {meta['name']}",
        "",
        f"- Date: {meta['started_at']}",
        f"- Duration: {fmt_ts(duration)}",
        "",
    ]
    for seg in sorted(segments, key=lambda s: s.start):
        lines.append(f"**[{fmt_ts(seg.start)}] {seg.speaker}:** {seg.text}")
        lines.append("")
    return "\n".join(lines)


def summarize(transcript: str, context: str, language: str) -> str:
    result = subprocess.run(
        ["claude", "-p", SUMMARY_PROMPT_TEMPLATE.format(context=context, language=language)],
        input=transcript,
        capture_output=True,
        text=True,
        timeout=600,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude -p failed (exit {result.returncode}): {result.stderr[:500]}")
    return result.stdout.strip() + "\n"


def notify_processing_failed(spool: Path, exc: Exception) -> None:
    rerun_cmd = f"python3 {Path(__file__).resolve()} {spool}"
    print(f"Processing failed: {exc}", file=sys.stderr)
    print(f"The recording is untouched in: {spool}", file=sys.stderr)
    print(f"Re-run manually once fixed: {rerun_cmd}", file=sys.stderr)
    subprocess.run(
        [
            "notify-send",
            "-u",
            "critical",
            "Meeting notes: processing failed",
            f"Recording kept in {spool}. Re-run: {rerun_cmd}",
        ],
        check=False,
    )


def main() -> None:
    cfg = config.load()
    spool = Path(sys.argv[1]).resolve()
    meta = json.loads((spool / "meeting.json").read_text())
    language = cfg["summary_language"] or "the dominant language of the transcript"

    # Everything here touches an external engine (local Whisper model load/
    # inference, the `claude -p` subprocess) that can fail for reasons outside
    # this script's control (auth expired, network blip, rate limit, OOM). On
    # failure the spool directory is left exactly as `meeting stop` produced
    # it (nothing archived, nothing deleted) so the printed command re-runs
    # processing from scratch without losing the recording.
    try:
        duration = wav_duration(spool / "mic.wav")
        meta["duration_seconds"] = round(duration, 1)
        meta["processed_at"] = datetime.datetime.now().astimezone().isoformat(timespec="seconds")

        print("Transcribing both tracks (local Whisper, CPU)...")
        from faster_whisper import WhisperModel

        model = WhisperModel(cfg["model"], device="cpu", compute_type="int8")
        segments = transcribe(model, spool / "mic.wav", "Me") + transcribe(
            model, spool / "system.wav", "Others"
        )
        transcript = build_transcript(meta, segments, duration)
        (spool / "transcript.md").write_text(transcript)

        if cfg["delete_audio_after"]:
            (spool / "mic.wav").unlink(missing_ok=True)
            (spool / "system.wav").unlink(missing_ok=True)

        print("Generating structured notes (claude -p)...")
        if segments:
            notes = summarize(transcript, cfg["summary_context"], language)
        else:
            notes = f"# {meta['name']}\n\nNo speech detected in the recording.\n"
        (spool / "meeting.md").write_text(notes)
        (spool / "meeting.json").write_text(json.dumps(meta, indent=2) + "\n")
    except Exception as exc:  # noqa: BLE001 -- deliberately broad, see comment above
        notify_processing_failed(spool, exc)
        sys.exit(1)

    started = datetime.datetime.fromisoformat(meta["started_at"])
    # spool "20260725-1030-name-a1b2c3d4" -> archive "2026/07/25/1030-name-a1b2c3d4"
    dest = cfg["archive_root"] / started.strftime("%Y/%m/%d") / spool.name.split("-", 1)[1]
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(spool), str(dest))

    print(f"Archived: {dest}")
    print(f"  Notes:      {dest / 'meeting.md'}")
    print(f"  Transcript: {dest / 'transcript.md'}")

    # Optional mirror: text files only (audio can be hundreds of MB per hour).
    if cfg["mirror_root"] is not None:
        mirror = cfg["mirror_root"] / started.strftime("%Y/%m/%d") / dest.name
        mirror.mkdir(parents=True, exist_ok=True)
        for fname in ("meeting.md", "transcript.md", "meeting.json"):
            shutil.copy2(dest / fname, mirror / fname)
        print(f"  Mirror:     {mirror}")

    subprocess.run(
        ["notify-send", "Meeting notes", f"Notes ready: {dest / 'meeting.md'}"],
        check=False,
    )

    # Best-effort: a broken or slow hook must never undo an already-successful
    # archive, so this runs after archiving and never raises.
    if cfg["on_archive_change"]:
        hook_env = {
            **os.environ,
            "MEETING_ARCHIVE_DIR": str(dest),
            "MEETING_NAME": meta["name"],
            "MEETING_NOTES_PATH": str(dest / "meeting.md"),
            "MEETING_TRANSCRIPT_PATH": str(dest / "transcript.md"),
        }
        try:
            result = subprocess.run(cfg["on_archive_change"], shell=True, env=hook_env, timeout=120)
            if result.returncode != 0:
                print(f"Archive-change hook exited {result.returncode} (ignored)", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001 -- best-effort by design
            print(f"Archive-change hook failed (ignored): {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
