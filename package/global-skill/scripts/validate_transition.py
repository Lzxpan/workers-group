"""Validate Workers Group workflow transitions and completion evidence gates."""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from runpy import run_path

from workers_group_paths import USER_HOME

ROOT = USER_HOME
validate_document = run_path(str(Path(__file__).with_name("validate_report.py")))["validate_document"]
redact_and_validate = run_path(str(Path(__file__).with_name("memory_guard.py")))["redact_and_validate"]
MAIN_SEQUENCE = (
    "INTAKE", "CHARTERED", "PLANNING", "FEASIBILITY_REVIEW", "READY",
    "EXECUTING", "READY_FOR_QA", "QA_REVIEW", "READY_FOR_BOSS_REVIEW", "DONE",
)
EXCEPTION_STATES = {"BLOCKED", "NEEDS_REWORK", "QA_FAILED", "PARTIAL", "FAILED", "CANCELLED"}
TERMINAL = {"DONE", "FAILED", "CANCELLED"}
LEGAL = {
    "INTAKE": {"CHARTERED", "BLOCKED", "FAILED", "CANCELLED"},
    "CHARTERED": {"PLANNING", "BLOCKED", "FAILED", "CANCELLED"},
    "PLANNING": {"FEASIBILITY_REVIEW", "BLOCKED", "FAILED", "CANCELLED"},
    "FEASIBILITY_REVIEW": {"READY", "NEEDS_REWORK", "BLOCKED", "FAILED", "CANCELLED"},
    "READY": {"EXECUTING", "BLOCKED", "FAILED", "CANCELLED"},
    "EXECUTING": {"READY_FOR_QA", "PARTIAL", "BLOCKED", "FAILED", "CANCELLED"},
    "READY_FOR_QA": {"QA_REVIEW", "NEEDS_REWORK", "BLOCKED", "FAILED", "CANCELLED"},
    "QA_REVIEW": {"READY_FOR_BOSS_REVIEW", "QA_FAILED", "BLOCKED", "FAILED", "CANCELLED"},
    "READY_FOR_BOSS_REVIEW": {"DONE", "PARTIAL", "NEEDS_REWORK", "BLOCKED", "FAILED", "CANCELLED"},
    "NEEDS_REWORK": {"PLANNING", "EXECUTING", "BLOCKED", "FAILED", "CANCELLED"},
    "QA_FAILED": {"NEEDS_REWORK", "EXECUTING", "PARTIAL", "BLOCKED", "FAILED", "CANCELLED"},
    "PARTIAL": {"PLANNING", "EXECUTING", "READY_FOR_QA", "BLOCKED", "FAILED", "CANCELLED"},
    "BLOCKED": {"PLANNING", "FEASIBILITY_REVIEW", "READY", "EXECUTING", "READY_FOR_QA",
                "QA_REVIEW", "PARTIAL", "FAILED", "CANCELLED"},
}
QA_VERDICTS = {"PASS", "FAIL", "PARTIAL", "NOT_VERIFIED", "BLOCKED"}
AUDIT_REQUIRED_FIELDS = {
    "timestamp", "actor", "previous_status", "new_status", "reason", "evidence",
    "related_acceptance_criteria", "task_id", "accepted", "error",
}


def _non_empty_strings(value: object) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(item, str) and item.strip() for item in value)


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def append_transition_audit(path: str | Path, event: dict) -> None:
    """Append one complete JSON event while holding a sibling lockfile."""
    if not isinstance(event, dict) or set(event) != AUDIT_REQUIRED_FIELDS:
        raise ValueError("transition audit event fields mismatch")
    for field in ("timestamp", "actor", "previous_status", "new_status", "reason", "task_id", "error"):
        if not isinstance(event[field], str):
            raise ValueError(f"transition audit {field} must be a string")
    if not event["actor"].strip() or not event["reason"].strip():
        raise ValueError("transition audit requires actor and reason")
    if not isinstance(event["accepted"], bool):
        raise ValueError("transition audit accepted must be boolean")
    for field in ("evidence", "related_acceptance_criteria"):
        if not isinstance(event[field], list) or any(
            not isinstance(item, str) or not item.strip() for item in event[field]
        ):
            raise ValueError(f"transition audit {field} must contain non-empty strings")
    for field, value in event.items():
        values = value if isinstance(value, list) else [value]
        for item in values:
            if isinstance(item, str) and not redact_and_validate(item)["accepted"]:
                raise ValueError(f"transition audit contains sensitive text in {field}")

    audit_path = Path(path)
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = audit_path.with_suffix(audit_path.suffix + ".lock")
    for attempt in range(100):
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(descriptor)
            break
        except FileExistsError:
            if attempt == 99:
                raise TimeoutError(f"transition audit lock timeout: {lock_path}")
            time.sleep(0.01)
        except PermissionError:
            if not lock_path.exists():
                continue
            if attempt == 99:
                raise TimeoutError(f"transition audit lock timeout: {lock_path}")
            time.sleep(0.01)
    else:
        raise TimeoutError(f"transition audit lock timeout: {lock_path}")
    try:
        serialized = (json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        descriptor = os.open(audit_path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            remaining = memoryview(serialized)
            while remaining:
                written = os.write(descriptor, remaining)
                if not written:
                    raise OSError("transition audit append wrote zero bytes")
                remaining = remaining[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        lock_path.unlink(missing_ok=True)


def _related_acceptance_criteria(state: dict) -> list[str]:
    explicit = state.get("related_acceptance_criteria")
    if isinstance(explicit, list):
        return _string_list(explicit)
    related = []
    entries = state.get("acceptance_criteria", [])
    for item in entries if isinstance(entries, list) else []:
        if isinstance(item, str) and item.strip():
            related.append(item)
        elif isinstance(item, dict):
            value = item.get("id") or item.get("path")
            if isinstance(value, str) and value.strip():
                related.append(value)
    return related


def _readable_evidence(value: object) -> bool:
    try:
        _evidence_paths(value, "evidence")
        return True
    except (ValueError, PermissionError):
        return False


def _repository_file(value: object, label: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise PermissionError(f"DONE gate requires {label}")
    candidate = Path(value)
    candidate = candidate.resolve() if candidate.is_absolute() else (ROOT / candidate).resolve()
    try:
        candidate.relative_to(ROOT.resolve())
        with candidate.open("rb") as stream:
            stream.read(1)
    except (OSError, ValueError) as exc:
        raise PermissionError(f"DONE gate requires readable repository {label}") from exc
    return candidate


def _evidence_paths(value: object, label: str) -> set[str]:
    if not _non_empty_strings(value):
        raise PermissionError(f"{label} requires non-empty evidence paths")
    paths = set()
    for item in value:
        paths.add(os.path.normcase(str(_repository_file(item, f"{label} evidence"))))
    return paths


def _load_document(value: object, label: str) -> dict:
    path = _repository_file(value, label)
    try:
        if path.stat().st_size > 1048576:
            raise ValueError(f"{label} exceeds size limit")
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} must be valid UTF-8 JSON") from exc
    if not isinstance(document, dict):
        raise ValueError(f"{label} must be a JSON object")
    return document


def _require_valid_schema(kind: str, document: dict, label: str) -> None:
    result = validate_document(kind, document, enforce_cross_fields=False)
    if not result.get("valid"):
        raise ValueError(f"{label} schema validation failed")


def _valid_human_waiver(value: object) -> bool:
    return (
        isinstance(value, dict)
        and value.get("human_approved") is True
        and _non_empty_strings(value.get("unresolved_risks"))
        and _readable_evidence(value.get("evidence"))
    )


def _require_ready_for_qa(state: dict) -> None:
    required_truthy = ("executor_report", "required_tests_executed", "failures_disclosed")
    missing = [field for field in required_truthy if not state.get(field)]
    if not _non_empty_strings(state.get("files_changed")):
        missing.append("files_changed")
    if state.get("blockers"):
        missing.append("unresolved blockers")
    if missing:
        raise PermissionError(f"READY_FOR_QA gate missing: {', '.join(missing)}")


def _require_done(state: dict, qa_verdict: str | None, completion_evidence: object) -> None:
    required_truthy = (
        "boss_reviewed", "all_acceptance_criteria_passed", "failures_disclosed",
        "memory_candidate_decision_recorded", "skill_changes_resolved",
    )
    missing = [field for field in required_truthy if state.get(field) is not True]
    if state.get("undisclosed_failures"):
        missing.append("undisclosed failures")
    if missing:
        raise PermissionError(f"DONE gate missing: {', '.join(missing)}")

    task_id = state.get("task_id")
    if not isinstance(task_id, str) or not task_id.strip():
        raise PermissionError("DONE gate requires task_id")
    completion_paths = _evidence_paths(completion_evidence, "DONE")

    qa_report = _load_document(state.get("qa_report"), "qa_report")
    _require_valid_schema("qa-report", qa_report, "qa_report")
    if qa_report.get("task_id") != task_id or qa_report.get("role") != "workers_qa":
        raise PermissionError("qa_report is not bound to the active task and QA role")
    if qa_report.get("overall_verdict") != qa_verdict:
        raise PermissionError("qa_report verdict is not bound to the transition verdict")
    qa_paths = _evidence_paths(qa_report.get("evidence"), "qa_report")
    if not qa_paths & completion_paths:
        raise PermissionError("qa_report evidence is not bound to DONE evidence")
    if qa_verdict == "PASS":
        if qa_report.get("unverified_items"):
            raise PermissionError("PASS qa_report cannot contain unverified items")
        if not qa_report.get("criteria_results") or any(
            not isinstance(result, dict) or result.get("verdict") != "PASS"
            for result in qa_report.get("criteria_results", [])
        ):
            raise PermissionError("PASS qa_report requires every criterion to PASS")

    boss_report = _load_document(state.get("boss_report"), "boss_report")
    _require_valid_schema("role-report", boss_report, "boss_report")
    if (
        boss_report.get("task_id") != task_id
        or boss_report.get("role") != "workers_boss"
        or boss_report.get("status") != "DONE"
    ):
        raise PermissionError("boss_report is not bound to the active task and DONE Boss review")
    if boss_report.get("blockers") or boss_report.get("remaining_work"):
        raise PermissionError("DONE boss_report cannot contain blockers or remaining work")
    boss_paths = _evidence_paths(boss_report.get("evidence"), "boss_report")
    if not boss_paths & completion_paths:
        raise PermissionError("boss_report evidence is not bound to DONE evidence")

    acceptance_entries = state.get("acceptance_criteria")
    if not isinstance(acceptance_entries, list) or not acceptance_entries:
        raise PermissionError("DONE gate requires acceptance criterion documents")
    acceptance_documents: dict[str, tuple[dict, set[str]]] = {}
    for index, entry in enumerate(acceptance_entries):
        if not isinstance(entry, dict) or entry.get("task_id") != task_id:
            raise PermissionError(f"acceptance_criteria[{index}] is not bound to the active task")
        document = _load_document(entry.get("path"), f"acceptance_criteria[{index}]")
        _require_valid_schema("acceptance-criterion", document, f"acceptance_criteria[{index}]")
        criterion_id = document.get("id")
        if criterion_id in acceptance_documents:
            raise PermissionError(f"duplicate acceptance criterion document: {criterion_id}")
        if document.get("status") != "PASS" or document.get("verdict") != "PASS":
            raise PermissionError(f"acceptance criterion {criterion_id} is not PASS")
        criterion_paths = _evidence_paths(
            document.get("evidence"), f"acceptance criterion {criterion_id}",
        )
        if not criterion_paths & completion_paths:
            raise PermissionError(f"acceptance criterion {criterion_id} evidence is not bound to DONE")
        acceptance_documents[str(criterion_id)] = (document, criterion_paths)

    qa_results: dict[str, dict] = {}
    for result in qa_report.get("criteria_results", []):
        criterion_id = result.get("acceptance_criterion_id") if isinstance(result, dict) else None
        if not isinstance(criterion_id, str) or criterion_id in qa_results:
            raise PermissionError("qa_report contains missing or duplicate acceptance criterion IDs")
        qa_results[criterion_id] = result
    if set(qa_results) != set(acceptance_documents):
        raise PermissionError("qa_report criterion IDs do not match acceptance criterion documents")
    for criterion_id, (_, criterion_paths) in acceptance_documents.items():
        result_paths = _evidence_paths(
            qa_results[criterion_id].get("evidence"), f"qa_report criterion {criterion_id}",
        )
        if not result_paths & criterion_paths or not result_paths & qa_paths:
            raise PermissionError(f"criterion {criterion_id} evidence is not bound across QA and acceptance")


def validate_transition(from_status: str, to_status: str, *, qa_verdict: str | None = None,
                        evidence: list[str] | None = None, state: dict | None = None) -> bool:
    allowed = LEGAL.get(from_status, set())
    if to_status not in allowed:
        raise ValueError(f"illegal transition: {from_status} -> {to_status}")
    if to_status in {"READY_FOR_QA", "READY_FOR_BOSS_REVIEW", "DONE"} and not _readable_evidence(evidence):
        raise PermissionError(f"{to_status} requires existing readable repository evidence")
    if qa_verdict is not None and qa_verdict not in QA_VERDICTS:
        raise ValueError(f"invalid QA verdict: {qa_verdict}")
    if to_status in {"READY_FOR_BOSS_REVIEW", "DONE"} and qa_verdict != "PASS":
        waiver = (state or {}).get("human_waiver")
        if not _valid_human_waiver(waiver):
            raise PermissionError(f"{to_status} requires QA PASS or a structured approved human waiver")
    if to_status == "READY_FOR_QA":
        _require_ready_for_qa(state or {})
    if to_status == "DONE":
        _require_done(state or {}, qa_verdict, evidence)
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="from_status", required=True)
    parser.add_argument("--to", dest="to_status", required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--actor")
    parser.add_argument("--reason")
    parser.add_argument("--audit-path", type=Path)
    args = parser.parse_args()
    state: dict = {}
    try:
        state = json.loads(args.state.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            raise ValueError("state must be a JSON object")
        validate_transition(
            args.from_status, args.to_status,
            qa_verdict=state.get("qa_verdict", state.get("qaVerdict")),
            evidence=state.get("evidence"),
            state=state,
        )
        result = {"valid": True, "errors": []}
    except (OSError, json.JSONDecodeError, ValueError, PermissionError) as exc:
        result = {"valid": False, "errors": [str(exc)]}
    if args.audit_path:
        event = {
            "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "actor": args.actor or "",
            "previous_status": args.from_status,
            "new_status": args.to_status,
            "reason": args.reason or "",
            "evidence": _string_list(state.get("evidence")),
            "related_acceptance_criteria": _related_acceptance_criteria(state),
            "task_id": state.get("task_id", "") if isinstance(state.get("task_id", ""), str) else "",
            "accepted": result["valid"],
            "error": "" if result["valid"] else "; ".join(result["errors"]),
        }
        try:
            append_transition_audit(args.audit_path, event)
        except (OSError, TimeoutError, ValueError) as exc:
            result["valid"] = False
            result["errors"].append(f"transition audit failed: {exc}")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
