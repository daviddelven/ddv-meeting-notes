#!/usr/bin/env python3
"""Load user configuration from ${XDG_CONFIG_HOME:-~/.config}/ddv-meeting-notes/config.toml.

Every key is optional; see config.example.toml for the shape and defaults.
Also runnable as a CLI for shell scripts: `config.py spool_root` prints the value.
"""
from __future__ import annotations

import os
import sys
import tomllib
from pathlib import Path


def _config_path() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(xdg) / "ddv-meeting-notes" / "config.toml"


def _expand(value: str) -> Path:
    return Path(os.path.expanduser(value))


def load() -> dict:
    raw: dict = {}
    path = _config_path()
    if path.exists():
        with open(path, "rb") as f:
            raw = tomllib.load(f)

    paths = raw.get("paths", {})
    mirror = paths.get("mirror_root")
    audio = raw.get("audio", {})
    transcription = raw.get("transcription", {})
    retention = raw.get("retention", {})
    summary = raw.get("summary", {})
    hooks = raw.get("hooks", {})

    # Accept either a list of terms or one ready-made string, so a long
    # vocabulary stays readable in TOML without forcing a particular style.
    vocabulary = transcription.get("vocabulary") or None
    if isinstance(vocabulary, list):
        vocabulary = ", ".join(str(v).strip() for v in vocabulary if str(v).strip()) or None

    return {
        "spool_root": _expand(paths.get("spool_root", "~/Recordings/meetings/spool")),
        "archive_root": _expand(paths.get("archive_root", "~/Recordings/meetings/archive")),
        "mirror_root": _expand(mirror) if mirror else None,
        "model": transcription.get("model", "small"),
        "vocabulary": vocabulary,
        "filler_words": [str(w).strip() for w in transcription.get("filler_words", []) if str(w).strip()],
        "summary_context": summary.get("context", "You are a meeting-notes assistant."),
        "summary_language": summary.get("language") or None,
        "mic_source": audio.get("mic_source") or None,
        "delete_audio_after": bool(retention.get("delete_audio_after", False)),
        "transcript_retention_days": int(retention.get("transcript_days", 0) or 0),
        "on_archive_change": hooks.get("on_archive_change") or None,
    }


if __name__ == "__main__":
    # Print "" rather than the literal string "None" for unset keys, so shell
    # callers can test with a plain [[ -z "$(...)" ]] instead of string-matching.
    value = load()[sys.argv[1]]
    print("" if value is None else value)
