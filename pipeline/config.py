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
    return {
        "spool_root": _expand(paths.get("spool_root", "~/Recordings/meetings/spool")),
        "archive_root": _expand(paths.get("archive_root", "~/Recordings/meetings/archive")),
        "mirror_root": _expand(mirror) if mirror else None,
        "model": raw.get("transcription", {}).get("model", "small"),
        "summary_context": raw.get("summary", {}).get(
            "context", "You are a meeting-notes assistant."
        ),
    }


if __name__ == "__main__":
    print(load()[sys.argv[1]])
