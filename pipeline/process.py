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
import shutil
import subprocess
import sys
import wave
from dataclasses import dataclass
from pathlib import Path

import config

SUMMARY_PROMPT_TEMPLATE = """{context} Below (stdin) is the transcript of a meeting with two voices: "Me" (the user, captured by the microphone) and "Others" (the remote participants, captured from the system audio output). Speaker labels in the transcript may appear localized.

Write structured meeting notes in Markdown with exactly these sections, translating BOTH the section headings and the content into the dominant language of the transcript:

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


def summarize(transcript: str, context: str) -> str:
    result = subprocess.run(
        ["claude", "-p", SUMMARY_PROMPT_TEMPLATE.format(context=context)],
        input=transcript,
        capture_output=True,
        text=True,
        timeout=600,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude -p failed (exit {result.returncode}): {result.stderr[:500]}")
    return result.stdout.strip() + "\n"


def main() -> None:
    cfg = config.load()
    spool = Path(sys.argv[1]).resolve()
    meta = json.loads((spool / "meeting.json").read_text())

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

    print("Generating structured notes (claude -p)...")
    if segments:
        notes = summarize(transcript, cfg["summary_context"])
    else:
        notes = f"# {meta['name']}\n\nNo speech detected in the recording.\n"
    (spool / "meeting.md").write_text(notes)
    (spool / "meeting.json").write_text(json.dumps(meta, indent=2) + "\n")

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


if __name__ == "__main__":
    main()
