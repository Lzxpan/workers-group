"""Evaluate 0-100 Workers Group scorecards without changing authority."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import tomllib
from pathlib import Path


SCRIPT_ROOT = Path(__file__).resolve().parent
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from validate_report import validate_document
from validate_skill import validate_scorecard_appeal, validate_scorecard_contract


REQUIRED_THRESHOLDS = {
    "recognition_at_or_above",
    "reliable_at_or_above",
    "meets_standard_at_or_above",
    "coaching_at_or_above",
    "critical_minimum",
    "critical_metrics",
}
ROLE_IDS = {
    "workers_boss",
    "workers_planner",
    "workers_pm",
    "workers_executor",
    "workers_qa",
}
REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
OUTPUT_ROOTS = (
    REPOSITORY_ROOT / ".workers-group/reports",
    REPOSITORY_ROOT / ".workers-group/evidence",
)


def load_policy(path: Path) -> dict:
    policy = tomllib.loads(path.read_text(encoding="utf-8"))
    thresholds = policy.get("thresholds")
    badges = policy.get("badges")
    coaching = policy.get("coaching")
    if policy.get("schema_version") != "2.0" or not isinstance(thresholds, dict):
        raise ValueError("invalid performance policy")
    if set(thresholds) != REQUIRED_THRESHOLDS:
        raise ValueError("performance policy threshold set mismatch")
    numeric = REQUIRED_THRESHOLDS - {"critical_metrics"}
    for key in numeric:
        value = thresholds[key]
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 100:
            raise ValueError(f"performance policy {key} must be an integer from 0 to 100")
    if not (
        thresholds["recognition_at_or_above"] >= thresholds["reliable_at_or_above"]
        >= thresholds["meets_standard_at_or_above"] >= thresholds["coaching_at_or_above"]
    ):
        raise ValueError("performance policy score bands are not descending")
    if not isinstance(thresholds["critical_metrics"], list) or not thresholds["critical_metrics"]:
        raise ValueError("performance policy critical_metrics must be a non-empty list")
    if not isinstance(badges, dict) or set(badges) != ROLE_IDS:
        raise ValueError("performance policy badges must cover every fixed role")
    if not isinstance(coaching, dict) or not isinstance(coaching.get("next_task_requirement"), str):
        raise ValueError("performance policy coaching requirement is missing")
    return policy


def _role_scores(role: dict) -> dict:
    return {**role["shared_scores"], **role["role_scores"]}


def evaluate_role(role: dict, policy: dict) -> dict:
    thresholds = policy["thresholds"]
    scores = _role_scores(role)
    total_points = sum(scores.values())
    critical = sorted(
        metric for metric in thresholds["critical_metrics"]
        if role["shared_scores"].get(metric, 0) < thresholds["critical_minimum"]
    )
    if critical or total_points < thresholds["coaching_at_or_above"]:
        outcome = "AUTHORITY_HOLD"
        score_band = "AUTHORITY_HOLD"
        reasons = critical or ["total_points_below_60"]
    elif total_points < thresholds["meets_standard_at_or_above"]:
        outcome = "COACHING_REQUIRED"
        score_band = "COACHING"
        reasons = ["total_points_60_to_69"]
    elif total_points < thresholds["reliable_at_or_above"]:
        outcome = "STEADY_STATE"
        score_band = "MEETS_STANDARD"
        reasons = []
    elif total_points < thresholds["recognition_at_or_above"]:
        outcome = "STEADY_STATE"
        score_band = "RELIABLE"
        reasons = []
    else:
        outcome = "RECOGNITION_RECOMMENDED"
        score_band = "EXCELLENCE"
        reasons = []
    badges = [policy["badges"][role["role"]]] if outcome == "RECOGNITION_RECOMMENDED" else []
    coaching = [policy["coaching"]["next_task_requirement"]] if outcome == "COACHING_REQUIRED" else []
    return {
        "role": role["role"],
        "reviewer_role": role["reviewer_role"],
        "total_points": total_points,
        "score_band": score_band,
        "outcome": outcome,
        "reasons": reasons,
        "badge_recommendations": badges,
        "coaching_requirements": coaching,
        "requires_independent_review": True,
        "requires_boss_review": outcome == "AUTHORITY_HOLD",
        "authority_boundary": "boss approval required; this recommendation never changes authority automatically",
    }


def evaluate_scorecard(scorecard: dict, policy: dict) -> dict:
    validation = validate_document("scorecard", scorecard)
    errors = list(validation["errors"]) if not validation["valid"] else []
    errors.extend(validate_scorecard_contract(scorecard))
    if errors:
        raise ValueError("invalid scorecard: " + "; ".join(errors))
    return {
        "schema_version": "2.0",
        "scorecard_id": scorecard["scorecard_id"],
        "task_id": scorecard["task_id"],
        "roles": [evaluate_role(role, policy) for role in scorecard["roles"]],
    }


def validate_appeal(appeal: dict, scorecard: dict) -> bool:
    errors = validate_scorecard_appeal(appeal, scorecard)
    if errors:
        raise ValueError("; ".join(errors))
    return True


def _canonical_sha256(value: dict) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def read_accountability_ledger(path: Path) -> list[dict]:
    """Read a tamper-evident local JSONL history; records are never rewritten."""
    ledger = require_managed_output(path)
    if not ledger.exists():
        return []
    records = []
    previous_sha256 = None
    for line_number, line in enumerate(ledger.read_text(encoding="utf-8").splitlines(), start=1):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"accountability ledger line {line_number} is not JSON") from exc
        if not isinstance(record, dict) or record.get("previous_sha256") != previous_sha256:
            raise ValueError("accountability ledger hash chain is invalid")
        actual = record.get("sha256")
        unsigned = {key: value for key, value in record.items() if key != "sha256"}
        if not isinstance(actual, str) or actual != _canonical_sha256(unsigned):
            raise ValueError("accountability ledger hash chain is invalid")
        records.append(record)
        previous_sha256 = actual
    return records


def _append_ledger_record(path: Path, record: dict) -> dict:
    ledger = require_managed_output(path)
    records = read_accountability_ledger(ledger)
    stored = {**record, "previous_sha256": records[-1]["sha256"] if records else None}
    stored["sha256"] = _canonical_sha256(stored)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(stored, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        stream.write("\n")
    return stored


def append_scorecard_evaluation(
    ledger: Path,
    scorecard: dict,
    evaluation: dict,
    *,
    qa_verdict: str,
    closed_status: str,
) -> list[dict]:
    """Persist eligible scorecard outcomes as immutable local history records."""
    if qa_verdict != "PASS" or closed_status != "CLOSED":
        raise ValueError("verified profile requires QA PASS and CLOSED")
    if evaluation.get("scorecard_id") != scorecard.get("scorecard_id") or evaluation.get("task_id") != scorecard.get("task_id"):
        raise ValueError("evaluation does not identify the supplied scorecard")
    outcomes = evaluation.get("roles")
    if not isinstance(outcomes, list) or {item.get("role") for item in outcomes if isinstance(item, dict)} != {
        item.get("role") for item in scorecard.get("roles", []) if isinstance(item, dict)
    }:
        raise ValueError("evaluation role set does not match scorecard")
    return [
        _append_ledger_record(ledger, {
            "record_type": "SCORECARD_EVALUATION",
            "scorecard_id": scorecard["scorecard_id"],
            "task_id": scorecard["task_id"],
            "role": outcome["role"],
            "reviewer_role": outcome["reviewer_role"],
            "qa_verdict": qa_verdict,
            "closed_status": closed_status,
            "timestamp": scorecard["timestamp"],
            "scorecard_sha256": _canonical_sha256(scorecard),
            "scorecard_role": next(item for item in scorecard["roles"] if item["role"] == outcome["role"]),
            "evaluation": outcome,
        })
        for outcome in outcomes
    ]


def append_appeal_resolution(ledger: Path, appeal: dict, resolution: dict, scorecard: dict) -> dict:
    """Append an independently assigned appeal decision without modifying prior history."""
    validate_appeal(appeal, scorecard)
    required = {
        "schema_version", "appeal_id", "scorecard_id", "role", "assigned_by", "reviewer_role",
        "resolution", "evidence", "timestamp",
    }
    if set(resolution) != required or resolution.get("schema_version") != "1.0":
        raise ValueError("appeal resolution field set is invalid")
    if resolution.get("scorecard_id") != appeal.get("scorecard_id") or resolution.get("role") != appeal.get("role"):
        raise ValueError("appeal resolution does not identify the appeal")
    if resolution.get("assigned_by") != "workers_boss":
        raise ValueError("appeal resolution must be assigned by workers_boss")
    if resolution.get("reviewer_role") != appeal.get("requested_reviewer"):
        raise ValueError("appeal resolution reviewer must be the requested reviewer")
    if resolution.get("resolution") not in {"UPHELD", "ADJUSTED", "REJECTED"}:
        raise ValueError("appeal resolution outcome is invalid")
    evidence = resolution.get("evidence")
    if not isinstance(evidence, list) or not evidence or not all(isinstance(item, str) and item.strip() for item in evidence):
        raise ValueError("appeal resolution evidence is invalid")
    if not isinstance(resolution.get("timestamp"), str) or not resolution["timestamp"].strip():
        raise ValueError("appeal resolution timestamp is invalid")
    return _append_ledger_record(ledger, {
        "record_type": "APPEAL_RESOLUTION",
        "appeal": appeal,
        "resolution": resolution,
        "scorecard": scorecard,
        "scorecard_sha256": _canonical_sha256(scorecard),
    })


def verified_profile(ledger: Path, role: str) -> dict:
    """Return only the most recent ten independently verified task outcomes for one role."""
    if role not in ROLE_IDS:
        raise ValueError("unknown role")
    tasks = [
        {
            "task_id": record["task_id"],
            "scorecard_id": record["scorecard_id"],
            "timestamp": record["timestamp"],
            "reviewer_role": record["reviewer_role"],
            "evaluation": record["evaluation"],
        }
        for record in reversed(read_accountability_ledger(ledger))
        if record.get("record_type") == "SCORECARD_EVALUATION"
        and record.get("role") == role
        and record.get("qa_verdict") == "PASS"
        and record.get("closed_status") == "CLOSED"
    ][:10]
    return {"role": role, "recent_verified_tasks": tasks}


def write_json_atomically(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def require_managed_output(path: Path) -> Path:
    target = path.resolve()
    if not any(target.is_relative_to(root.resolve()) for root in OUTPUT_ROOTS):
        raise ValueError("output must stay inside .workers-group/reports or .workers-group/evidence")
    return target


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--policy",
        type=Path,
        default=Path(__file__).resolve().parents[4] / ".workers-group/config/performance-policy.toml",
    )
    args = parser.parse_args()
    try:
        scorecard = json.loads(args.file.read_text(encoding="utf-8"))
        result = evaluate_scorecard(scorecard, load_policy(args.policy))
        output = require_managed_output(args.output)
        write_json_atomically(output, result)
        print(json.dumps({"valid": True, "output": str(output)}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, TypeError, json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
        print(json.dumps({"valid": False, "errors": [str(exc)]}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
