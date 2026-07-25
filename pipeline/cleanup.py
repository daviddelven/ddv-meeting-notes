#!/usr/bin/env python3
"""Delete transcript.md from archived meetings older than [retention] transcript_days.

Never touches meeting.md (the notes), meeting.json or audio -- only the raw
timestamped transcript, which is the bulkiest and least reused artifact.
transcript_days = 0 (the default) disables this entirely. Run manually
(`meeting cleanup`) or from cron; safe to run repeatedly.
"""
from __future__ import annotations

import datetime
import json
import sys

import config


def main() -> None:
    cfg = config.load()
    days = cfg["transcript_retention_days"]
    if days <= 0:
        print("Transcript auto-expiry is disabled ([retention] transcript_days = 0). Nothing to do.")
        return

    archive_root = cfg["archive_root"]
    if not archive_root.exists():
        print(f"Archive root does not exist: {archive_root}")
        return

    cutoff = datetime.datetime.now().astimezone() - datetime.timedelta(days=days)
    removed = kept = 0
    for meta_path in sorted(archive_root.rglob("meeting.json")):
        meeting_dir = meta_path.parent
        transcript_path = meeting_dir / "transcript.md"
        if not transcript_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text())
            started = datetime.datetime.fromisoformat(meta["started_at"])
        except (OSError, ValueError, KeyError) as exc:
            print(f"  skip (unreadable meeting.json): {meeting_dir}: {exc}", file=sys.stderr)
            continue
        if started < cutoff:
            transcript_path.unlink()
            removed += 1
            print(f"  deleted transcript.md: {meeting_dir}")
        else:
            kept += 1

    print(f"Done: {removed} transcript(s) deleted, {kept} within the {days}-day retention window.")


if __name__ == "__main__":
    main()
