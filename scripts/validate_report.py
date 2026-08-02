"""Minimal stdlib validation for role and QA reports."""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

from workers_group_paths import STATIC_ROOT, USER_HOME

ROOT = USER_HOME
SCHEMAS = STATIC_ROOT / "schemas"


def _evidence_errors(
    values: object,
    path: str = "$.evidence",
    repository_root: Path = ROOT,
) -> list[str]:
    if not isinstance(values, list) or not values:
        return [f"{path}: at least one evidence path is required"]
    errors = []
    for index, value in enumerate(values):
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{path}[{index}]: evidence path must be a non-empty string")
            continue
        candidate = Path(value)
        root = repository_root.resolve()
        candidate = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            errors.append(f"{path}[{index}]: evidence must stay inside the repository")
            continue
        try:
            with candidate.open("rb") as stream:
                stream.read(1)
        except OSError:
            errors.append(f"{path}[{index}]: evidence path is not an existing readable file")
    return errors


def _command_errors(commands: object, path: str) -> list[str]:
    errors = []
    if not isinstance(commands, list):
        return [f"{path}: expected array"]
    for index, command in enumerate(commands):
        if not isinstance(command, dict):
            errors.append(f"{path}[{index}]: expected object")
            continue
        if not isinstance(command.get("command"), str) or not command["command"].strip():
            errors.append(f"{path}[{index}].command: non-empty string required")
        if not isinstance(command.get("exit_code"), int) or isinstance(command.get("exit_code"), bool):
            errors.append(f"{path}[{index}].exit_code: integer required")
    return errors


def _test_errors(tests: object, path: str) -> list[str]:
    errors = []
    if not isinstance(tests, list):
        return [f"{path}: expected array"]
    for index, test in enumerate(tests):
        if not isinstance(test, dict):
            errors.append(f"{path}[{index}]: expected object")
            continue
        if not isinstance(test.get("command"), str) or not test["command"].strip():
            errors.append(f"{path}[{index}].command: non-empty string required")
        for field in ("passed", "failed", "skipped"):
            value = test.get(field)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                errors.append(f"{path}[{index}].{field}: non-negative integer required")
    return errors


def _schema_errors(value: object, schema: dict, path: str = "$") -> list[str]:
    errors = []
    expected = schema.get("type")
    types = {
        "object": dict, "array": list, "string": str, "integer": int,
        "number": (int, float), "boolean": bool, "null": type(None),
    }
    if expected and (not isinstance(value, types[expected]) or expected in {"integer", "number"} and isinstance(value, bool)):
        return [f"{path}: expected {expected}"]
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: must equal {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: value is not in enum")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{path}: string is too short")
        if "pattern" in schema and not re.fullmatch(schema["pattern"], value):
            errors.append(f"{path}: pattern mismatch")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{path}: array is too short")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: array is too long")
        if "items" in schema:
            for index, item in enumerate(value):
                errors.extend(_schema_errors(item, schema["items"], f"{path}[{index}]"))
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and not math.isfinite(value):
            errors.append(f"{path}: number must be finite")
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: value is below minimum")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: value is above maximum")
    if isinstance(value, dict):
        for field in schema.get("required", []):
            if field not in value:
                errors.append(f"{path}: missing required field {field}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for field in value.keys() - properties.keys():
                errors.append(f"{path}: unexpected field {field}")
        for field, child in value.items():
            if field in properties:
                errors.extend(_schema_errors(child, properties[field], f"{path}.{field}"))
    return errors


def _cross_field_errors(
    kind: str,
    report: object,
    repository_root: Path = ROOT,
) -> list[str]:
    if not isinstance(report, dict):
        return []
    errors = []
    evidence = report.get("evidence")
    completion = report.get("status") in {"EVIDENCE_REVIEW", "BOSS_REVIEW", "CLOSED"}
    if kind == "role-report" and completion:
        errors.extend(_evidence_errors(evidence, repository_root=repository_root))
        errors.extend(_command_errors(report.get("commands_run"), "$.commands_run"))
        errors.extend(_test_errors(report.get("tests"), "$.tests"))
    if kind == "role-report" and report.get("role") == "workers_executor" and report.get("status") == "EVIDENCE_REVIEW":
        for field in ("commands_run", "files_changed", "tests"):
            if not report.get(field):
                errors.append(f"$.{field}: Executor EVIDENCE_REVIEW requires recorded {field}")
        if report.get("blockers"):
            errors.append("$.blockers: Executor EVIDENCE_REVIEW cannot contain unresolved blockers")
    if kind == "role-report" and report.get("status") == "CLOSED":
        if report.get("blockers") or report.get("remaining_work"):
            errors.append("$: CLOSED role report cannot contain blockers or remaining work")
    if kind == "role-report" and report.get("role") == "workers_planner" and report.get("status") == "PLANNING":
        errors.extend(_evidence_errors(evidence, repository_root=repository_root))
        if not report.get("facts"):
            errors.append("$.facts: feasibility review requires concrete verified facts")
        if not report.get("commands_run"):
            errors.append("$.commands_run: feasibility review requires a concrete verification command")
    if kind == "qa-report" and report.get("overall_verdict") == "PASS":
        errors.extend(_evidence_errors(evidence, repository_root=repository_root))
        for index, criterion in enumerate(report.get("criteria_results", [])):
            if isinstance(criterion, dict):
                errors.extend(_evidence_errors(
                    criterion.get("evidence"),
                    f"$.criteria_results[{index}].evidence",
                    repository_root,
                ))
        if not report.get("criteria_results"):
            errors.append("$.criteria_results: QA PASS requires independently verified criteria")
        if report.get("unverified_items"):
            errors.append("$.unverified_items: QA PASS cannot contain unverified items")
        if any(item.get("verdict") != "PASS" for item in report.get("criteria_results", []) if isinstance(item, dict)):
            errors.append("$.criteria_results: QA PASS requires every criterion to PASS")
    if kind == "acceptance-criterion" and report.get("status") == "PASS":
        if report.get("verdict") != "PASS" or not evidence:
            errors.append("$: PASS acceptance criterion requires PASS verdict and evidence")
        else:
            errors.extend(_evidence_errors(evidence, repository_root=repository_root))
    if kind == "acceptance-criterion" and report.get("verdict") not in {None, report.get("status")}:
        errors.append("$: acceptance criterion verdict must match status")
    if kind == "work-item" and report.get("status") == "CLOSED" and not evidence:
        errors.append("$.evidence: CLOSED work item requires evidence")
    elif kind == "work-item" and report.get("status") == "CLOSED":
        errors.extend(_evidence_errors(evidence, repository_root=repository_root))
    if kind == "work-item" and report.get("status") == "CLOSED" and report.get("blockers"):
        errors.append("$.blockers: CLOSED work item cannot contain blockers")
    if kind == "task-charter" and report.get("status") == "CLOSED" and not report.get("acceptance_criteria"):
        errors.append("$.acceptance_criteria: CLOSED Task Charter requires acceptance criteria")
    if kind == "scorecard":
        roles = report.get("roles", [])
        role_names = [item.get("role") for item in roles if isinstance(item, dict)]
        if len(role_names) != len(set(role_names)):
            errors.append("$.roles: each role may appear only once")
        for index, role in enumerate(roles):
            if isinstance(role, dict):
                errors.extend(_evidence_errors(
                    role.get("evidence"),
                    f"$.roles[{index}].evidence",
                    repository_root,
                ))
    if kind == "meeting":
        for index, alternative in enumerate(report.get("alternatives", [])):
            if isinstance(alternative, dict):
                errors.extend(_evidence_errors(
                    alternative.get("evidence"),
                    f"$.alternatives[{index}].evidence",
                    repository_root,
                ))
        if report.get("decisions") and not report.get("actions"):
            errors.append("$.actions: a completed decision requires at least one owned action")
    return errors


def validate_document(
    kind: str,
    report: object,
    *,
    enforce_cross_fields: bool = True,
    repository_root: str | Path | None = None,
) -> dict:
    if kind not in {"task-charter", "acceptance-criterion", "work-item", "role-report",
                    "qa-report", "meeting", "memory", "improvement-proposal", "scorecard",
                    "scorecard-appeal", "training-candidate", "skill-seat"}:
        return {"valid": False, "errors": [f"unsupported schema kind: {kind}"]}
    try:
        schema = json.loads((SCHEMAS / f"{kind}.schema.json").read_text(encoding="utf-8"))
        errors = _schema_errors(report, schema)
        if enforce_cross_fields:
            errors.extend(_cross_field_errors(
                kind,
                report,
                Path(repository_root) if repository_root is not None else ROOT,
            ))
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        errors = [str(exc)]
    return {"valid": not errors, "errors": errors}


def validate_role_report(report: object) -> dict:
    if isinstance(report, dict) and "schema_version" not in report:
        normalized = {
            "schema_version": "1.0",
            "task_id": "legacy-test",
            "work_item_id": "legacy-test",
            "role": report.get("role"),
            "agent_id": report.get("role") or "legacy-test",
            "status": report.get("status"),
            "summary": report.get("summary"),
            "facts": [], "assumptions": [], "actions_taken": [], "commands_run": [],
            "files_changed": [], "tests": [], "evidence": report.get("evidence", []),
            "blockers": [], "risks": [], "remaining_work": [], "memories_used": [],
            "memory_candidates": [], "confidence": 0.0, "timestamp": "legacy-test",
        }
        result = validate_document("role-report", normalized, enforce_cross_fields=False)
        evidence_errors = _evidence_errors(normalized["evidence"])
        if evidence_errors:
            result["errors"].extend(evidence_errors)
            result["valid"] = False
        return result
    return validate_document("role-report", report)


def validate_qa_report(report: object) -> dict:
    if isinstance(report, dict) and "schema_version" not in report:
        normalized = {
            "schema_version": "1.0",
            "task_id": "legacy-test",
            "role": report.get("role"),
            "overall_verdict": report.get("verdict"),
            "criteria_results": [], "design_findings": [], "regression_findings": [],
            "unverified_items": [], "memory_findings": [], "evidence": report.get("evidence", []),
            "timestamp": "legacy-test",
        }
        result = validate_document("qa-report", normalized, enforce_cross_fields=False)
        evidence_errors = _evidence_errors(normalized["evidence"])
        if evidence_errors:
            result["errors"].extend(evidence_errors)
            result["valid"] = False
        return result
    return validate_document("qa-report", report)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=("role", "qa", "scorecard"), required=True)
    parser.add_argument("--file", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = json.loads(args.file.read_text(encoding="utf-8"))
        kind = {"role": "role-report", "qa": "qa-report", "scorecard": "scorecard"}[args.kind]
        result = validate_document(kind, report)
    except (OSError, json.JSONDecodeError) as exc:
        result = {"valid": False, "errors": [str(exc)]}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
