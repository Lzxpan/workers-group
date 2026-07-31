#!/usr/bin/env python3
"""Bounded maintenance for stale and superseded Workers Group memory."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from memory_guard import redact_and_validate
from memory_store import MemoryStore, utc_now


def consolidate(db_path: str | Path) -> dict:
    """Age expired ACTIVE records; never deletes memory or audit history."""
    store = MemoryStore(db_path)
    store.initialize()
    changed: list[str] = []
    with store._connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        rows = connection.execute(
            "SELECT id,content,expires_at FROM memories WHERE status='ACTIVE' AND expires_at IS NOT NULL"
        ).fetchall()
        now = datetime.now(UTC)
        for row in rows:
            guard = redact_and_validate(row["content"])
            if not guard["accepted"]:
                next_status = "QUARANTINED"
            else:
                try:
                    next_status = "STALE" if datetime.fromisoformat(row["expires_at"]) <= now else "ACTIVE"
                except ValueError:
                    next_status = "QUARANTINED"
            if next_status != "ACTIVE":
                connection.execute(
                    "UPDATE memories SET status=?,updated_at=? WHERE id=?",
                    (next_status, utc_now(), row["id"]),
                )
                connection.execute(
                    "INSERT INTO audit_log(event,memory_id,details_json,created_at) VALUES (?,?,?,?)",
                    ("MEMORY_AGED", row["id"], json.dumps({"status": next_status}), utc_now()),
                )
                changed.append(row["id"])
    return {"changed": changed, "deleted": 0}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=".workers-group/runtime/memory.sqlite3")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(consolidate(args.db), ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
