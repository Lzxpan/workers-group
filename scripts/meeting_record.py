"""Create an auditable Workers Group meeting record."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from runpy import run_path

from state_store import StateStore


validate_document = run_path(str(Path(__file__).with_name("validate_report.py")))["validate_document"]
FIXED_ROLES = {
    "workers_boss", "workers_planner", "workers_pm", "workers_executor", "workers_qa",
}


def _verify_quorum(attendees: list[str], quorum: dict) -> None:
    if not isinstance(quorum, dict):
        raise ValueError("quorum must be an object")
    required = quorum.get("required_roles")
    minimum = quorum.get("minimum_attendees")
    if not isinstance(required, list) or not isinstance(minimum, int):
        raise ValueError("quorum requires required_roles and minimum_attendees")
    present = set(attendees)
    missing = sorted(set(required) - present)
    if missing:
        raise ValueError("quorum missing required roles: " + ", ".join(missing))
    if len(present) < minimum:
        raise ValueError("quorum minimum attendees is not met")


def build_record(
    attendees: list[str],
    agenda: str,
    decisions: list[str],
    evidence: list[str],
    *,
    meeting_type: str,
    chair: str,
    quorum: dict,
    decision_records: list[dict],
    dissent_records: list[dict],
    pm_record: dict,
    alternatives: list[dict] | None = None,
    actions: list[dict] | None = None,
) -> dict:
    if not attendees or not agenda.strip():
        raise ValueError("attendees and agenda are required")
    if chair not in FIXED_ROLES:
        raise ValueError("chair must be a fixed role")
    if pm_record.get("role") != "workers_pm":
        raise ValueError("pm_record must be owned by workers_pm")
    if decisions and not decision_records:
        raise ValueError("decisions require decision_records")
    _verify_quorum(attendees, quorum)
    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    identifier = hashlib.sha256((timestamp + agenda).encode("utf-8")).hexdigest()[:12]
    record = {
        "schemaVersion": 1,
        "meetingId": f"WG-MEETING-{identifier}",
        "timestamp": timestamp,
        "meeting_type": meeting_type,
        "chair": chair,
        "attendees": attendees,
        "quorum": quorum,
        "agenda": agenda.strip(),
        "facts": [],
        "assumptions": [],
        "alternatives": alternatives or [],
        "decisions": decisions,
        "decision_records": decision_records,
        "dissent_records": dissent_records,
        "pm_record": pm_record,
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


def _load_object(path: Path, label: str) -> dict:
    return _load_objects([path], label)[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--attendee", action="append", required=True)
    parser.add_argument("--agenda", required=True)
    parser.add_argument("--meeting-type", required=True)
    parser.add_argument("--chair", required=True)
    parser.add_argument("--quorum-file", type=Path, required=True)
    parser.add_argument("--pm-record-file", type=Path, required=True)
    parser.add_argument("--decision", action="append", default=[])
    parser.add_argument("--decision-record-file", action="append", type=Path, default=[])
    parser.add_argument("--dissent-record-file", action="append", type=Path, default=[])
    parser.add_argument("--evidence", action="append", default=[])
    parser.add_argument("--alternative-file", action="append", type=Path, required=True)
    parser.add_argument("--action-file", action="append", type=Path, default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        record = build_record(
            args.attendee,
            args.agenda,
            args.decision,
            args.evidence,
            meeting_type=args.meeting_type,
            chair=args.chair,
            quorum=_load_object(args.quorum_file, "quorum"),
            decision_records=_load_objects(args.decision_record_file, "decision record"),
            dissent_records=_load_objects(args.dissent_record_file, "dissent record"),
            pm_record=_load_object(args.pm_record_file, "PM record"),
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
