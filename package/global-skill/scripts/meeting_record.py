"""Create an auditable, minimal meeting record."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from runpy import run_path

from state_store import StateStore

validate_document = run_path(str(Path(__file__).with_name("validate_report.py")))["validate_document"]


def build_record(attendees: list[str], agenda: str, decisions: list[str], evidence: list[str],
                 *, alternatives: list[dict] | None = None,
                 actions: list[dict] | None = None) -> dict:
    if not attendees or not agenda.strip():
        raise ValueError("attendees and agenda are required")
    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    identifier = hashlib.sha256((timestamp + agenda).encode("utf-8")).hexdigest()[:12]
    record = {
        "schemaVersion": 1,
        "meetingId": f"WG-MEETING-{identifier}",
        "timestamp": timestamp,
        "attendees": attendees,
        "agenda": agenda.strip(),
        "facts": [],
        "assumptions": [],
        "alternatives": alternatives or [],
        "decisions": decisions,
        "actions": actions or [],
        "evidence": evidence,
    }
    result = validate_document("meeting", record)
    if not result["valid"]:
        raise ValueError("; ".join(result["errors"]))
    return record


def _load_objects(paths: list[Path], label: str) -> list[dict]:
    values = []
    for path in paths:
        if path.stat().st_size > 1048576:
            raise ValueError(f"{label} file exceeds size limit: {path}")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError(f"{label} file must contain a JSON object: {path}")
        values.append(value)
    return values


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--attendee", action="append", required=True)
    parser.add_argument("--agenda", required=True)
    parser.add_argument("--decision", action="append", default=[])
    parser.add_argument("--evidence", action="append", default=[])
    parser.add_argument("--alternative-file", action="append", type=Path, required=True)
    parser.add_argument("--action-file", action="append", type=Path, default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        record = build_record(
            args.attendee, args.agenda, args.decision, args.evidence,
            alternatives=_load_objects(args.alternative_file, "alternative"),
            actions=_load_objects(args.action_file, "action"),
        )
        StateStore(args.output).write_state(record)
        result = {"valid": True, "meetingId": record["meetingId"], "output": str(args.output)}
    except (OSError, ValueError) as exc:
        result = {"valid": False, "errors": [str(exc)]}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
