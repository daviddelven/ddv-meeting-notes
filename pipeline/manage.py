#!/usr/bin/env python3
"""`meeting rename` and `meeting regenerate`: act on one already-recorded meeting.

A meeting is addressed by the short id at the end of its directory name
(archive/2026/07/25/1030-roadmap-a1b2c3d4 -> "a1b2c3d4"); the full directory
name works too. Both the archive and the spool are searched, so a recording
whose notes step failed can be recovered without re-transcribing it.
"""
from __future__ import annotations

import datetime
import json
import re
import shutil
import sys
from pathlib import Path

import config
import process

# "1030-name-a1b2c3d4" (archive) or "20260725-1030-name-a1b2c3d4" (spool).
DIR_NAME_RE = re.compile(r"^(?P<ts>\d{8}-\d{4}|\d{4})-(?P<name>.*)-(?P<id>[^-]+)$")


def die(message: str) -> None:
    print(message, file=sys.stderr)
    sys.exit(1)


def sanitize_name(raw: str) -> str:
    """Same rule bin/meeting applies to names, so renaming can't produce a
    directory name that `meeting start` could never have created.

    Slightly stricter in one place: runs of dashes are collapsed and edge
    dashes trimmed, so a name made only of separators ("///") is rejected as
    empty instead of turning into a directory called "1030-----<id>".
    """
    name = re.sub(r"[ /]", "-", raw)
    name = re.sub(r"[^A-Za-z0-9\-_]", "", name)
    name = re.sub(r"-{2,}", "-", name).strip("-")
    return name[:60]


def find_meeting(cfg: dict, meeting_id: str) -> Path:
    matches: list[Path] = []
    for root in (cfg["archive_root"], cfg["spool_root"]):
        if not root.exists():
            continue
        for meta_path in sorted(root.rglob("meeting.json")):
            d = meta_path.parent
            if d.name == meeting_id or d.name.rsplit("-", 1)[-1] == meeting_id:
                matches.append(d)
    if not matches:
        die(
            f"No meeting found with id '{meeting_id}'.\n"
            f"Looked under {cfg['archive_root']} and {cfg['spool_root']}.\n"
            "The id is the last dash-separated part of the meeting's directory name."
        )
    if len(matches) > 1:
        listing = "\n".join(f"  {m}" for m in matches)
        die(f"Ambiguous id '{meeting_id}', matches several meetings:\n{listing}")
    return matches[0]


def cmd_rename(cfg: dict, meeting_id: str, new_name: str) -> None:
    d = find_meeting(cfg, meeting_id)
    parts = DIR_NAME_RE.match(d.name)
    if parts is None:
        die(f"Directory name not in the expected <timestamp>-<name>-<id> shape: {d}")

    name = sanitize_name(new_name)
    if not name:
        die(f"'{new_name}' contains no characters usable in a directory name.")

    dest = d.parent / f"{parts['ts']}-{name}-{parts['id']}"
    if dest == d:
        print(f"Already named '{name}': {d}")
        return
    if dest.exists():
        die(f"Target already exists: {dest}")

    meta_path = d / "meeting.json"
    meta = json.loads(meta_path.read_text())
    old_name = meta.get("name", "")
    meta["name"] = name
    meta_path.write_text(json.dumps(meta, indent=2) + "\n")

    # The transcript header carries the name too; the notes title is written by
    # the model from the transcript's content and is deliberately left alone.
    transcript_path = d / "transcript.md"
    if transcript_path.exists():
        text = transcript_path.read_text()
        if text.startswith(f"# Transcript: {old_name}"):
            transcript_path.write_text(
                text.replace(f"# Transcript: {old_name}", f"# Transcript: {name}", 1)
            )

    d.rename(dest)
    print(f"Renamed: {d.name} -> {dest.name}")
    print(f"  {dest}")

    # Keep the mirror (if any) in step: rename its directory, then refresh the
    # two files whose contents just changed.
    if cfg["mirror_root"] is not None:
        try:
            started = datetime.datetime.fromisoformat(meta["started_at"])
        except (KeyError, ValueError):
            return
        old_mirror = process.mirror_dir(d, started, cfg)
        new_mirror = process.mirror_dir(dest, started, cfg)
        if old_mirror is None or new_mirror is None or not old_mirror.exists():
            return
        if new_mirror.exists():
            print(f"  Mirror target already exists, left untouched: {new_mirror}", file=sys.stderr)
            return
        old_mirror.rename(new_mirror)
        for fname in ("meeting.json", "transcript.md"):
            if (dest / fname).exists():
                shutil.copy2(dest / fname, new_mirror / fname)
        print(f"  Mirror:     {new_mirror}")


def cmd_regenerate(cfg: dict, meeting_id: str) -> None:
    d = find_meeting(cfg, meeting_id)
    transcript_path = d / "transcript.md"
    if not transcript_path.exists():
        die(
            f"No transcript.md in {d}\n"
            "Nothing to regenerate from -- transcription itself has to be re-run:\n"
            f"  python3 {Path(process.__file__).resolve()} {d}"
        )

    meta_path = d / "meeting.json"
    meta = json.loads(meta_path.read_text())
    language = cfg["summary_language"] or "the dominant language of the transcript"

    print(f"Regenerating notes from the existing transcript: {d}")
    notes = process.summarize(transcript_path.read_text(), cfg["summary_context"], language)
    (d / "meeting.md").write_text(notes)

    in_spool = cfg["spool_root"] in d.parents
    if not in_spool:
        print(f"  Notes:      {d / 'meeting.md'}")
        # An archived meeting keeps its place; only the mirrored copy of the
        # file that just changed needs refreshing.
        if cfg["mirror_root"] is not None:
            try:
                started = datetime.datetime.fromisoformat(meta["started_at"])
            except (KeyError, ValueError):
                return
            mirror = process.mirror_dir(d, started, cfg)
            if mirror is not None and mirror.exists():
                shutil.copy2(d / "meeting.md", mirror / "meeting.md")
                print(f"  Mirror:     {mirror / 'meeting.md'}")
        return

    # Still in the spool: this is a recording whose notes step failed earlier,
    # so finish the pipeline where it left off instead of leaving it stuck.
    meta["processed_at"] = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    if "duration_seconds" not in meta and (d / "mic.wav").exists():
        meta["duration_seconds"] = round(process.wav_duration(d / "mic.wav"), 1)
    meta_path.write_text(json.dumps(meta, indent=2) + "\n")

    if cfg["delete_audio_after"]:
        (d / "mic.wav").unlink(missing_ok=True)
        (d / "system.wav").unlink(missing_ok=True)

    process.archive_meeting(d, meta, cfg)


def main() -> None:
    cfg = config.load()
    args = sys.argv[1:]
    if len(args) == 3 and args[0] == "rename":
        cmd_rename(cfg, args[1], args[2])
    elif len(args) == 2 and args[0] == "regenerate":
        cmd_regenerate(cfg, args[1])
    else:
        die("Usage: manage.py rename <id> <new-name> | manage.py regenerate <id>")


if __name__ == "__main__":
    main()
