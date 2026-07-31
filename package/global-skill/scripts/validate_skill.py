"""Structural validator for the globally installed Workers Group Skill."""

from __future__ import annotations

import json
import runpy
import sys
import tomllib
from pathlib import Path

from workers_group_paths import CODEX_HOME, SKILL_ROOT, STATIC_ROOT, USER_HOME

EVENTS = {
    "SessionStart", "SessionEnd", "UserPromptSubmit", "PreToolUse", "PostToolUse",
    "PreCompact", "PostCompact", "SubagentStart", "SubagentStop", "Stop", "PermissionRequest",
}
MAIN_SEQUENCE = (
    "INTAKE", "CHARTERED", "PLANNING", "FEASIBILITY_REVIEW", "READY",
    "EXECUTING", "READY_FOR_QA", "QA_REVIEW", "READY_FOR_BOSS_REVIEW", "DONE",
)
EXCEPTIONS = {"BLOCKED", "NEEDS_REWORK", "QA_FAILED", "PARTIAL", "FAILED", "CANCELLED"}
DESCRIPTION = (
    "Use when complex work requires coordinated planning, staged execution, independent verification, "
    "evidence-based completion gates, durable project memory, or accountable delegation across multiple "
    "Codex subagents."
)
CANONICAL = "打工人集團｜執行完成度與品質閘門"
AGENTS = {
    "workers_boss": ("gpt-5.6-sol", "xhigh", "workspace-write"),
    "workers_planner": ("gpt-5.6-sol", "xhigh", "workspace-write"),
    "workers_pm": ("gpt-5.6-sol", "high", "workspace-write"),
    "workers_executor": ("gpt-5.6-terra", "high", "workspace-write"),
    "workers_qa": ("gpt-5.6-sol", "high", "read-only"),
}
TEMPLATE_KINDS = {
    "task-charter", "acceptance-criterion", "work-item", "role-report",
    "qa-report", "meeting", "memory", "improvement-proposal", "scorecard",
}
REQUIRED_FIELDS = {
    "task-charter": {"schema_version", "task_id", "title", "original_request", "objective", "scope",
                     "non_goals", "constraints", "assumptions", "deliverables", "acceptance_criteria",
                     "created_by", "status", "created_at", "updated_at"},
    "acceptance-criterion": {"id", "requirement", "validation_method", "required_evidence", "owner",
                             "status", "evidence", "verdict"},
    "work-item": {"id", "title", "description", "owner", "dependencies", "acceptance_criterion_ids",
                  "status", "blockers", "evidence"},
    "role-report": {"schema_version", "task_id", "work_item_id", "role", "agent_id", "status", "summary",
                    "facts", "assumptions", "actions_taken", "commands_run", "files_changed", "tests",
                    "evidence", "blockers", "risks", "remaining_work", "memories_used",
                    "memory_candidates", "confidence", "timestamp"},
    "qa-report": {"schema_version", "task_id", "role", "overall_verdict", "criteria_results",
                  "design_findings", "regression_findings", "unverified_items", "memory_findings",
                  "evidence", "timestamp"},
}


def _root() -> Path:
    return USER_HOME


def _walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _handler(hooks: dict, event: str, identifier: str) -> dict:
    groups = hooks["hooks"][event]
    handlers = [handler for group in groups for handler in group.get("hooks", [])]
    handlers = [handler for handler in handlers if f"--hook-id {identifier}" in str(handler.get("commandWindows", ""))]
    if len(handlers) != 1:
        raise ValueError(f"{event} must register exactly one Workers Group handler")
    return handlers[0]


def _validate_skill_file(root: Path, errors: list[str]) -> None:
    content = (root / ".codex/skills/orchestrating-workers-group/SKILL.md").read_text(encoding="utf-8")
    parts = content.split("---", 2)
    frontmatter = [line for line in parts[1].strip().splitlines() if line.strip()]
    expected = ["name: orchestrating-workers-group", f"description: {DESCRIPTION}"]
    if frontmatter != expected:
        errors.append("SKILL.md frontmatter must contain the exact name and description")
    for required in (
        CANONICAL, "不自動啟動", "規劃前檢索", "memory `CANDIDATE`", "Skill Doctor",
    ):
        if required not in content:
            errors.append(f"SKILL.md missing governance condition: {required}")


def _validate_hooks(root: Path, errors: list[str]) -> None:
    hooks = json.loads((root / ".codex/hooks.json").read_text(encoding="utf-8"))
    registry = json.loads((root / ".workers-group/config/hooks-registry.json").read_text(encoding="utf-8"))
    if set(hooks.get("hooks", {})) != EVENTS:
        errors.append("hooks.json event set mismatch")
    records = registry.get("hooks", [])
    if len(records) != 11 or {record.get("event") for record in records} != EVENTS:
        errors.append("Hook registry must contain the same eleven events")
    if len({record.get("id") for record in records}) != 11:
        errors.append("Hook registry IDs must be unique")
    if [record.get("id") for record in records] != [f"WG-HOOK-{index:03d}" for index in range(1, 12)]:
        errors.append("Hook registry IDs/order mismatch")
    for record in records:
        event, identifier, display = record.get("event"), record.get("id"), record.get("displayName")
        if event not in EVENTS:
            continue
        handler = _handler(hooks, event, identifier)
        command_blob = f"{handler.get('command', '')}\n{handler.get('commandWindows', '')}"
        if handler.get("statusMessage") != display:
            errors.append(f"{event} registry/statusMessage mismatch")
        if f"--hook-id {identifier}" not in command_blob or f"--event {event}" not in command_blob:
            errors.append(f"{event} command/registry mismatch")
    canonical_tools = {"Bash", "apply_patch", "Edit", "Write", "Agent"}
    for event in ("PreToolUse", "PostToolUse", "PermissionRequest"):
        matchers = "|".join(group.get("matcher", "") for group in hooks["hooks"][event])
        if not canonical_tools.issubset(set(matchers.split("|"))):
            errors.append(f"{event} canonical tool matcher coverage mismatch")
    if _handler(hooks, "Stop", "WG-HOOK-010").get("statusMessage") != CANONICAL:
        errors.append("WG-HOOK-010 canonical display mismatch")
    if _handler(hooks, "SessionEnd", "WG-HOOK-011").get("timeout") != 3:
        errors.append("SessionEnd timeout must be 3")
    hook_module = runpy.run_path(str(root / ".codex/skills/orchestrating-workers-group/scripts/workers_group_hook.py"))
    dispatch = hook_module["dispatch"]
    dangerous = {"tool_input": {"nested": {"command": "Get-Content .env"}}}
    pre = dispatch(dangerous, event="PreToolUse")
    permission = dispatch(dangerous, event="PermissionRequest")
    stop = dispatch({"hasGaps": True, "continuationCount": 1}, event="Stop")
    capped = dispatch({"hasGaps": True, "continuationCount": 2}, event="SubagentStop")
    if (
        pre.get("hookSpecificOutput", {}).get("permissionDecision") != "deny"
        or "decision" in pre
    ):
        errors.append("PreToolUse deny wire mismatch")
    permission_decision = permission.get("hookSpecificOutput", {}).get("decision", {})
    if (
        permission_decision.get("behavior") != "deny"
        or not permission_decision.get("message")
        or "decision" in permission
    ):
        errors.append("PermissionRequest nested decision wire mismatch")
    if stop.get("decision") != "block" or capped.get("decision") == "block":
        errors.append("Stop/SubagentStop continuation wire mismatch")


def _validate_agents_and_tiers(root: Path, errors: list[str]) -> None:
    config = tomllib.loads((root / ".codex/config.toml").read_text(encoding="utf-8"))
    if not config.get("features", {}).get("hooks") or not config.get("features", {}).get("multi_agent"):
        errors.append("global Codex feature configuration mismatch")
    if config.get("agents", {}).get("max_threads") != 4:
        errors.append("global Codex thread configuration mismatch")
    for agent, expected in AGENTS.items():
        parsed = tomllib.loads((root / ".codex/agents" / f"{agent}.toml").read_text(encoding="utf-8"))
        actual = (parsed.get("model"), parsed.get("model_reasoning_effort"), parsed.get("sandbox_mode"))
        if parsed.get("name") != agent or actual != expected:
            errors.append(f"agent mapping mismatch: {agent}")
    tiers = tomllib.loads((root / ".workers-group/config/intelligence-tiers.toml").read_text(encoding="utf-8"))
    expected_tiers = {
        "sol": ("gpt-5.6-sol", "xhigh", "gpt-5.6-terra", "high"),
        "luna": ("gpt-5.6-sol", "high", "gpt-5.6-terra", "high"),
        "terra": ("gpt-5.6-terra", "high", "gpt-5.6-sol", "medium"),
    }
    if tiers.get("schema_version") != "1.0":
        errors.append("intelligence tiers schema_version mismatch")
    for tier, expected in expected_tiers.items():
        section = tiers.get(tier, {})
        actual = tuple(section.get(key) for key in (
            "preferred_model", "preferred_reasoning_effort", "fallback_model", "fallback_reasoning_effort",
        ))
        if actual != expected:
            errors.append(f"intelligence tier mismatch: {tier}")
    verification = tiers.get("verification", {})
    if not all(verification.get(field) for field in ("codex_version", "verified_at", "verification_method")):
        errors.append("intelligence tier verification block is incomplete")


def _validate_states_and_templates(root: Path, errors: list[str]) -> None:
    transition = runpy.run_path(str(root / ".codex/skills/orchestrating-workers-group/scripts/validate_transition.py"))
    if tuple(transition.get("MAIN_SEQUENCE", ())) != MAIN_SEQUENCE:
        errors.append("workflow main sequence mismatch")
    if "LEGACY_LEGAL" in transition:
        errors.append("legacy workflow aliases must not bypass the canonical state machine")
    if set(transition.get("EXCEPTION_STATES", set())) != EXCEPTIONS:
        errors.append("workflow exception states mismatch")
    workflow = (root / ".codex/skills/orchestrating-workers-group/references/workflow-state-machine.md").read_text(encoding="utf-8")
    if not all(state in workflow for state in MAIN_SEQUENCE + tuple(EXCEPTIONS)):
        errors.append("workflow reference is incomplete")
    validator = runpy.run_path(str(root / ".codex/skills/orchestrating-workers-group/scripts/validate_report.py"))
    validate_document = validator["validate_document"]
    schema_names = {path.name.removesuffix(".schema.json") for path in (root / ".workers-group/schemas").glob("*.schema.json")}
    template_names = {path.name.removesuffix(".template.json") for path in (root / ".workers-group/templates").glob("*.template.json")}
    if schema_names != TEMPLATE_KINDS or template_names != TEMPLATE_KINDS:
        errors.append("schema/template set mismatch")
    for kind in sorted(TEMPLATE_KINDS):
        schema = root / ".workers-group/schemas" / f"{kind}.schema.json"
        template = root / ".workers-group/templates" / f"{kind}.template.json"
        parsed_schema = json.loads(schema.read_text(encoding="utf-8"))
        if kind in REQUIRED_FIELDS and set(parsed_schema.get("required", [])) != REQUIRED_FIELDS[kind]:
            errors.append(f"{kind} schema required fields mismatch")
        document = json.loads(template.read_text(encoding="utf-8"))
        result = validate_document(kind, document, enforce_cross_fields=False)
        if not result["valid"]:
            errors.append(f"invalid {kind} template: {result['errors']}")
    qa_schema = json.loads((root / ".workers-group/schemas/qa-report.schema.json").read_text(encoding="utf-8"))
    expected_verdicts = {"PASS", "FAIL", "PARTIAL", "NOT_VERIFIED", "BLOCKED"}
    if set(qa_schema["properties"]["overall_verdict"].get("enum", [])) != expected_verdicts:
        errors.append("QA verdict enum mismatch")
    for kind in ("task-charter", "role-report", "qa-report", "meeting", "scorecard"):
        asset = json.loads(
            (root / ".codex/skills/orchestrating-workers-group/assets" / f"{kind}.template.json").read_text(encoding="utf-8")
        )
        if not validate_document(kind, asset, enforce_cross_fields=False)["valid"]:
            errors.append(f"invalid Skill asset template: {kind}")
    doctor = runpy.run_path(
        str(root / ".codex/skills/orchestrating-workers-group/scripts/skill_doctor.py"),
    )
    expected_low_operations = {
        "update_status_message", "retrieval_weights", "test_fixture", "diagnostics",
        "path_fix", "optional_schema_field", "text_clarification",
    }
    if set(doctor.get("LOW_OPERATIONS", set())) != expected_low_operations:
        errors.append("Skill Doctor LOW operation allowlist mismatch")
    proposal_schema = json.loads(
        (root / ".workers-group/schemas/improvement-proposal.schema.json").read_text(encoding="utf-8"),
    )
    schema_operations = set(
        proposal_schema.get("properties", {}).get("operation", {}).get("enum", []),
    )
    if schema_operations != expected_low_operations:
        errors.append("improvement proposal operation schema mismatch")
    retriever = runpy.run_path(
        str(root / ".codex/skills/orchestrating-workers-group/scripts/memory_retriever.py"),
    )
    expected_weights = set(doctor.get("WEIGHT_FIELDS", set()))
    if set(retriever.get("WEIGHT_FIELDS", set())) != expected_weights:
        errors.append("retrieval policy weight allowlists are inconsistent")
    policy = tomllib.loads(
        (root / ".workers-group/config/retrieval-policy.toml").read_text(encoding="utf-8"),
    )
    if expected_weights - policy.keys():
        errors.append("retrieval policy is missing allowlisted weights")
    for field in expected_weights & policy.keys():
        value = policy[field]
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not 0 <= float(value) <= 1
        ):
            errors.append(f"retrieval policy weight is outside 0..1: {field}")


def validate(root: Path) -> dict:
    errors: list[str] = []
    checks = (_validate_skill_file, _validate_hooks, _validate_agents_and_tiers, _validate_states_and_templates)
    for check in checks:
        try:
            check(root, errors)
        except (OSError, ValueError, KeyError, TypeError, IndexError, json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
            errors.append(f"{check.__name__}: {exc}")
    return {"valid": not errors, "errors": errors}


def main() -> int:
    try:
        result = validate(_root())
    except OSError as exc:
        result = {"valid": False, "errors": [str(exc)]}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["valid"] else 2


if __name__ == "__main__":
    sys.exit(main())
