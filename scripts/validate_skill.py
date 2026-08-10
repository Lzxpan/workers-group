"""Project-scoped structural validator for the Workers Group Skill."""

from __future__ import annotations

import json
import runpy
import sys
import ast
import tomllib
from pathlib import Path

EVENTS = {
    "SessionStart", "SessionEnd", "UserPromptSubmit", "PreToolUse", "PostToolUse",
    "PreCompact", "PostCompact", "SubagentStart", "SubagentStop", "Stop", "PermissionRequest",
}
MAIN_SEQUENCE = (
    "INTAKE", "KICKOFF", "PLANNING", "AWAITING_HUMAN_APPROVAL", "EXECUTING",
    "EVIDENCE_REVIEW", "QA", "BOSS_REVIEW", "CLOSED",
)
EXCEPTIONS = {"BLOCKED", "FAILED", "NOT_VERIFIED"}
DESCRIPTION = (
    "Use when complex work requires coordinated planning, staged execution, independent verification, "
    "evidence-based completion gates, durable project memory, or accountable delegation across multiple "
    "Codex subagents."
)
CANONICAL = "打工人集團｜執行完成度與品質閘門"
ROUTING_ANCHOR = "## Phase-based reference routing"
CURRENT_GOVERNANCE_CONDITIONS = (
    CANONICAL, "不自動啟動", "規劃前檢索", "memory `CANDIDATE`", "Skill Doctor",
    "Boss 首要責任是先釐清真人真正想完成的目標", "Boss 對使用者的每一則可見回覆都必須使用 `humanizer-zh`",
    "規劃前全面盤點這台 PC 已設定／可探索的 skill roots", "複雜任務，以及遇到實質問題、不確定或知識不足時，先開並記錄會議",
    "遵守所有適用的 system、developer、user、skill、project 規則", "任一工作停止或暫停時，Boss 必須在使用者可見回覆中說明具體原因",
    "已記錄的會議後，團隊可對本機、暫時、可復原、有證據的開發工作主動診斷", "若本機開發環境由團隊從零設計",
    "確認可重複的流程失敗或使用者修正時，Boss 主動建立已遮蔽的 Skill Doctor proposal", "使用者要求整理過往任務的經驗、修正或版本歷程時",
    "公開產品與推廣畫面不能放內部規則、驗收準則、修正紀錄或團隊對話", "QA 在實際 target repository 獨立重跑",
    "交付／完成宣稱只可涵蓋實際獨立重跑的 scope", "task_name 必須直接使用對應固定 role identifier",
)
REFERENCE_ROUTES = {
    "references/architecture.md": "啟動本 Skill 時必讀",
    "references/role-contracts.md": "啟動本 Skill 時必讀",
    "references/workflow-state-machine.md": "啟動本 Skill 時必讀",
    "references/acceptance-and-evidence.md": "啟動本 Skill 時必讀",
    "references/accountability-policy.md": "啟動本 Skill 時必讀",
    "references/meeting-protocol.md": "需要 `kickoff`、`design_review`、`change_blocker`、`implementation_handoff`、`qa_gate` 或 `retrospective` 時",
    "references/hooks-reference.md": "需要檢查 lifecycle guardrail、Hook ID、tool gate 或 runtime 限制時",
    "references/memory-architecture.md": "要檢索、寫入、review、修復或處理衝突 memory 時",
    "references/memory-retrieval.md": "要檢索、寫入、review、修復或處理衝突 memory 時",
    "references/memory-conflict-policy.md": "要檢索、寫入、review、修復或處理衝突 memory 時",
    "references/self-improvement-policy.md": "任何 Skill 自我變更、proposal、risk、rollback 或 human approval 時",
    "references/intelligence-tiers.md": "指派角色、選擇 model 或 fallback 前",
}
DETAILED_GOVERNANCE_REFERENCES = {
    "references/role-operating-model.md": "指派角色、選擇 model 或 fallback 前",
    "references/meeting-playbook.md": "需要 `kickoff`、`design_review`、`change_blocker`、`implementation_handoff`、`qa_gate` 或 `retrospective` 時",
    "references/accountability-and-growth.md": "評估 scorecard、badge、recognition、coaching、authority hold 或 appeal 時",
    "references/learning-and-skill-evolution.md": "要檢索、寫入、review、修復或處理衝突 memory 時",
}
DETAILED_GOVERNANCE_MARKERS = (
    "固定角色必須依專業人格、權限、能力、交接與 reflection 合約行事",
    "closure criteria",
    "分數只產生可追溯 recommendation；不能取代 QA verdict，不能自動改變 model、sandbox、檔案所有權、人類授權或已得徽章歷史",
    "不得自動上傳、建立 Hub 資產或啟動 Hugging Face model training",
)
REFERENCE_ROUTES.update(DETAILED_GOVERNANCE_REFERENCES)
AGENTS = {
    "workers_boss": ("gpt-5.6-sol", "xhigh", "workspace-write"),
    "workers_planner": ("gpt-5.6-sol", "xhigh", "workspace-write"),
    "workers_pm": ("gpt-5.6-sol", "high", "workspace-write"),
    "workers_executor": ("gpt-5.6-terra", "high", "workspace-write"),
    "workers_qa": ("gpt-5.6-sol", "high", "read-only"),
}
ROLE_NAMES = frozenset(AGENTS)
GOVERNANCE_ROLE_FIELDS = frozenset({
    "canonical_role", "display_role", "model_tier", "personality", "capabilities",
    "authority", "prohibitions", "state_responsibilities", "report_required_fields",
    "meeting_responsibilities", "accountability_reviewer", "memory_rights",
    "training_candidate_rights",
})
ROLE_SCORE_KEYS = {
    "workers_boss": frozenset({
        "authorization_judgment", "decision_traceability", "conflict_resolution",
        "user_communication", "final_gate_integrity",
    }),
    "workers_planner": frozenset({
        "requirement_clarity", "architecture_quality", "risk_analysis",
        "testability_design", "tradeoff_reasoning",
    }),
    "workers_pm": frozenset({
        "dependency_control", "ownership_clarity", "state_integrity",
        "meeting_discipline", "handoff_continuity",
    }),
    "workers_executor": frozenset({
        "implementation_quality", "reproducibility", "defect_prevention",
        "scope_execution", "evidence_packaging",
    }),
    "workers_qa": frozenset({
        "independent_reproduction", "negative_testing", "defect_discovery",
        "verification_boundary", "verdict_integrity",
    }),
}
SHARED_SCORE_KEYS = frozenset({
    "factual_accuracy", "evidence_completeness", "scope_discipline",
    "handoff_quality", "escalation_timeliness",
})
ROLE_REPORT_REASONING_FIELDS = frozenset({
    "facts", "assumptions", "inferences", "unverified_items", "failed_results",
})
V2_MEETING_STATES = frozenset({
    "INTAKE", "KICKOFF", "PLANNING", "AWAITING_HUMAN_APPROVAL", "EXECUTING",
    "EVIDENCE_REVIEW", "QA", "BOSS_REVIEW", "CLOSED", "BLOCKED", "FAILED",
    "NOT_VERIFIED",
})
GOVERNANCE_SCHEMA_KINDS = {"scorecard-appeal", "scorecard-appeal-resolution", "training-candidate"}
TEMPLATE_KINDS = {
    "task-charter", "acceptance-criterion", "work-item", "role-report",
    "qa-report", "meeting", "memory", "improvement-proposal", "scorecard", "skill-seat",
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
                    "facts", "assumptions", "inferences", "unverified_items", "failed_results", "actions_taken", "commands_run", "files_changed", "tests",
                    "evidence", "blockers", "risks", "remaining_work", "memories_used",
                    "memory_candidates", "confidence", "timestamp"},
    "qa-report": {"schema_version", "task_id", "role", "overall_verdict", "criteria_results",
                  "design_findings", "regression_findings", "unverified_items", "memory_findings",
                  "evidence", "timestamp"},
}


def _root() -> Path:
    for candidate in (Path.cwd().resolve(), *Path.cwd().resolve().parents):
        if (candidate / ".git").exists():
            return candidate
    raise FileNotFoundError("Git root not found")


def _walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _handler(hooks: dict, event: str) -> dict:
    groups = hooks["hooks"][event]
    handlers = [handler for group in groups for handler in group.get("hooks", [])]
    if len(handlers) != 1:
        raise ValueError(f"{event} must register exactly one Workers Group handler")
    return handlers[0]


def _validate_skill_file(root: Path, errors: list[str]) -> None:
    content = (root / ".agents/skills/orchestrating-workers-group/SKILL.md").read_text(encoding="utf-8")
    parts = content.split("---", 2)
    frontmatter = [line for line in parts[1].strip().splitlines() if line.strip()]
    expected = ["name: orchestrating-workers-group", f"description: {DESCRIPTION}"]
    if frontmatter != expected:
        errors.append("SKILL.md frontmatter must contain the exact name and description")
    for required in CURRENT_GOVERNANCE_CONDITIONS:
        if required not in content:
            errors.append(f"SKILL.md missing governance condition: {required}")
    if ROUTING_ANCHOR not in content:
        errors.append("SKILL.md missing phase-based reference routing anchor")
    for reference, routing_condition in REFERENCE_ROUTES.items():
        if not (root / ".agents/skills/orchestrating-workers-group" / reference).is_file():
            errors.append(f"SKILL.md reference target is missing: {reference}")
        if reference not in content:
            errors.append(f"SKILL.md missing required reference route: {reference}")
        if routing_condition not in content:
            errors.append(f"SKILL.md missing reference routing condition: {routing_condition}")


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
    for node in _walk(hooks):
        if "name" in node:
            errors.append("hooks.json contains forbidden handler key: name")
        if "statusMessage" in node and not str(node["statusMessage"]).startswith("打工人集團｜"):
            errors.append("unprefixed Hook statusMessage")
    for record in records:
        event, identifier, display = record.get("event"), record.get("id"), record.get("displayName")
        if event not in EVENTS:
            continue
        handler = _handler(hooks, event)
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
    if _handler(hooks, "Stop").get("statusMessage") != CANONICAL:
        errors.append("WG-HOOK-010 canonical display mismatch")
    if _handler(hooks, "SessionEnd").get("timeout") != 3:
        errors.append("SessionEnd timeout must be 3")
    hook_module = runpy.run_path(str(root / ".agents/skills/orchestrating-workers-group/scripts/workers_group_hook.py"))
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
    if config.get("features") != {"hooks": True, "multi_agent": True}:
        errors.append("project Codex feature configuration mismatch")
    if config.get("agents") != {"max_threads": 4}:
        errors.append("project Codex thread configuration mismatch")
    for agent, expected in AGENTS.items():
        parsed = tomllib.loads((root / ".codex/agents" / f"{agent}.toml").read_text(encoding="utf-8"))
        actual = (parsed.get("model"), parsed.get("model_reasoning_effort"), parsed.get("sandbox_mode"))
        if parsed.get("name") != agent or actual != expected:
            errors.append(f"agent mapping mismatch: {agent}")
        governance = parsed.get("governance", {})
        if not isinstance(governance, dict) or not GOVERNANCE_ROLE_FIELDS.issubset(governance):
            errors.append(f"agent governance contract is incomplete: {agent}")
            continue
        if governance["canonical_role"] != agent or not str(governance["display_role"]).strip():
            errors.append(f"agent governance identity mismatch: {agent}")
        if governance["model_tier"] not in {"sol", "luna", "terra"}:
            errors.append(f"agent governance model tier mismatch: {agent}")
        for field in (
            "personality", "capabilities", "authority", "prohibitions", "state_responsibilities",
            "meeting_responsibilities", "memory_rights", "training_candidate_rights",
        ):
            value = governance[field]
            if not isinstance(value, list) or not value or not all(isinstance(item, str) and item.strip() for item in value):
                errors.append(f"agent governance {field} must be a non-empty string list: {agent}")
        if not ROLE_REPORT_REASONING_FIELDS.issubset(set(governance["report_required_fields"])):
            errors.append(f"agent governance report fields mismatch: {agent}")
        reviewer = governance["accountability_reviewer"]
        if reviewer not in ROLE_NAMES or reviewer == agent:
            errors.append(f"agent governance reviewer must be independent: {agent}")
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
    transition = runpy.run_path(str(root / ".agents/skills/orchestrating-workers-group/scripts/validate_transition.py"))
    if tuple(transition.get("MAIN_SEQUENCE", ())) != MAIN_SEQUENCE:
        errors.append("workflow main sequence mismatch")
    if "LEGACY_LEGAL" in transition:
        errors.append("legacy workflow aliases must not bypass the canonical state machine")
    if set(transition.get("EXCEPTION_STATES", set())) != EXCEPTIONS:
        errors.append("workflow exception states mismatch")
    workflow = (root / ".agents/skills/orchestrating-workers-group/references/workflow-state-machine.md").read_text(encoding="utf-8")
    if not all(state in workflow for state in MAIN_SEQUENCE + tuple(EXCEPTIONS)):
        errors.append("workflow reference is incomplete")
    validator = runpy.run_path(str(root / ".agents/skills/orchestrating-workers-group/scripts/validate_report.py"))
    validate_document = validator["validate_document"]
    schema_names = {path.name.removesuffix(".schema.json") for path in (root / ".workers-group/schemas").glob("*.schema.json")}
    template_names = {path.name.removesuffix(".template.json") for path in (root / ".workers-group/templates").glob("*.template.json")}
    if schema_names != TEMPLATE_KINDS | GOVERNANCE_SCHEMA_KINDS or template_names != TEMPLATE_KINDS:
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
            (root / ".agents/skills/orchestrating-workers-group/assets" / f"{kind}.template.json").read_text(encoding="utf-8")
        )
        if not validate_document(kind, asset, enforce_cross_fields=False)["valid"]:
            errors.append(f"invalid Skill asset template: {kind}")
    doctor = runpy.run_path(
        str(root / ".agents/skills/orchestrating-workers-group/scripts/skill_doctor.py"),
    )
    expected_low_operations = {
        "update_status_message", "retrieval_weights", "test_fixture", "diagnostics",
        "path_fix", "optional_schema_field", "text_clarification", "learned_skill_rule",
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
        str(root / ".agents/skills/orchestrating-workers-group/scripts/memory_retriever.py"),
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


def _validate_governance_schemas(root: Path, errors: list[str]) -> None:
    schemas = root / ".workers-group/schemas"
    for kind in ("task-charter", "work-item", "role-report"):
        document = json.loads((schemas / f"{kind}.schema.json").read_text(encoding="utf-8"))
        if set(document.get("properties", {}).get("status", {}).get("enum", [])) != V2_MEETING_STATES:
            errors.append(f"{kind} state contract mismatch")
    role_report = json.loads((schemas / "role-report.schema.json").read_text(encoding="utf-8"))
    if not ROLE_REPORT_REASONING_FIELDS.issubset(set(role_report.get("properties", {}))) or not ROLE_REPORT_REASONING_FIELDS.issubset(set(role_report.get("required", []))):
        errors.append("role report governance field set is incomplete")
    failed_results = role_report.get("properties", {}).get("failed_results", {}).get("items", {})
    if set(failed_results.get("required", [])) != {
        "command", "exit_code", "passed", "failed", "skipped", "artifact_path", "summary",
    }:
        errors.append("role report failed result contract mismatch")

    meeting = json.loads((schemas / "meeting.schema.json").read_text(encoding="utf-8"))
    meeting_properties = meeting.get("properties", {})
    required_meeting = {"meeting_type", "chair", "quorum", "decision_records", "dissent_records", "pm_record"}
    if not required_meeting.issubset(set(meeting.get("required", []))) or not required_meeting.issubset(meeting_properties):
        errors.append("meeting governance field set is incomplete")
    meeting_types = set(meeting_properties.get("meeting_type", {}).get("enum", []))
    if meeting_types != {"kickoff", "design_review", "change_blocker", "implementation_handoff", "qa_gate", "retrospective"}:
        errors.append("meeting type contract mismatch")
    action_states = set(
        meeting_properties.get("actions", {}).get("items", {}).get("properties", {}).get("due_state", {}).get("enum", []),
    )
    if action_states != V2_MEETING_STATES:
        errors.append("meeting action state contract mismatch")

    scorecard = json.loads((schemas / "scorecard.schema.json").read_text(encoding="utf-8"))
    role_item = scorecard.get("properties", {}).get("roles", {}).get("items", {})
    required_scorecard_role = {"role", "reviewer_role", "shared_scores", "role_scores", "metric_evidence", "evidence", "notes"}
    if set(role_item.get("required", [])) != required_scorecard_role:
        errors.append("scorecard role field contract mismatch")
    shared = role_item.get("properties", {}).get("shared_scores", {})
    if set(shared.get("required", [])) != SHARED_SCORE_KEYS or set(shared.get("properties", {})) != SHARED_SCORE_KEYS:
        errors.append("scorecard shared score contract mismatch")
    appeal = json.loads((schemas / "scorecard-appeal.schema.json").read_text(encoding="utf-8"))
    if set(appeal.get("required", [])) != {"schema_version", "scorecard_id", "role", "requesting_role", "evidence", "requested_reviewer"}:
        errors.append("scorecard appeal contract mismatch")
    appeal_resolution = json.loads((schemas / "scorecard-appeal-resolution.schema.json").read_text(encoding="utf-8"))
    if set(appeal_resolution.get("required", [])) != {
        "schema_version", "appeal_id", "scorecard_id", "role", "assigned_by", "reviewer_role",
        "resolution", "evidence", "timestamp",
    } or appeal_resolution.get("properties", {}).get("assigned_by", {}).get("const") != "workers_boss":
        errors.append("scorecard appeal resolution contract mismatch")
    training = json.loads((schemas / "training-candidate.schema.json").read_text(encoding="utf-8"))
    required_training = {
        "schema_version", "candidate_id", "role", "capability_gap", "recent_verified_tasks", "status",
    }
    if set(training.get("required", [])) != required_training or training.get("additionalProperties") is not False:
        errors.append("training candidate contract mismatch")


def _score_errors(values: object, expected_keys: frozenset[str], path: str) -> list[str]:
    if not isinstance(values, dict):
        return [f"{path}: expected object"]
    errors = []
    if set(values) != expected_keys:
        errors.append(f"{path}: key set mismatch")
    for key, value in values.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 10:
            errors.append(f"{path}.{key}: expected a 0..10 number")
    return errors


def validate_scorecard_contract(scorecard: object) -> list[str]:
    """Return contract errors; an empty list means an independently reviewable scorecard."""
    if not isinstance(scorecard, dict):
        return ["$: expected scorecard object"]
    roles = scorecard.get("roles")
    if not isinstance(roles, list) or not roles:
        return ["$.roles: expected a non-empty array"]
    errors = []
    required = {"role", "reviewer_role", "shared_scores", "role_scores", "metric_evidence", "evidence", "notes"}
    for index, item in enumerate(roles):
        path = f"$.roles[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{path}: expected object")
            continue
        if set(item) != required:
            errors.append(f"{path}: required field set mismatch")
        role = item.get("role")
        reviewer = item.get("reviewer_role")
        if role not in ROLE_NAMES:
            errors.append(f"{path}.role: unknown role")
            continue
        if reviewer not in ROLE_NAMES:
            errors.append(f"{path}.reviewer_role: unknown reviewer")
        elif reviewer == role:
            errors.append(f"{path}.reviewer_role: reviewer must be independent")
        errors.extend(_score_errors(item.get("shared_scores"), SHARED_SCORE_KEYS, f"{path}.shared_scores"))
        errors.extend(_score_errors(item.get("role_scores"), ROLE_SCORE_KEYS[role], f"{path}.role_scores"))
        metric_evidence = item.get("metric_evidence")
        expected_evidence_keys = SHARED_SCORE_KEYS | ROLE_SCORE_KEYS[role]
        if not isinstance(metric_evidence, dict) or set(metric_evidence) != expected_evidence_keys:
            errors.append(f"{path}.metric_evidence: key set mismatch")
        else:
            for metric, paths in metric_evidence.items():
                if not isinstance(paths, list) or not paths or not all(isinstance(value, str) and value.strip() for value in paths):
                    errors.append(f"{path}.metric_evidence.{metric}: expected a non-empty string array")
        evidence = item.get("evidence")
        if not isinstance(evidence, list) or not evidence or not all(isinstance(value, str) and value.strip() for value in evidence):
            errors.append(f"{path}.evidence: expected a non-empty string array")
        if not isinstance(item.get("notes"), list) or not all(isinstance(value, str) for value in item["notes"]):
            errors.append(f"{path}.notes: expected a string array")
    return errors


def validate_scorecard_appeal(appeal: object, scorecard: object) -> list[str]:
    """Return appeal errors and prevent self-review or a repeat of the original reviewer."""
    if not isinstance(appeal, dict):
        return ["$: expected appeal object"]
    required = {"schema_version", "scorecard_id", "role", "requesting_role", "evidence", "requested_reviewer"}
    errors = []
    if set(appeal) != required:
        errors.append("$: required field set mismatch")
    role = appeal.get("role")
    if appeal.get("schema_version") != "1.0":
        errors.append("$.schema_version: must equal '1.0'")
    requester = appeal.get("requesting_role")
    reviewer = appeal.get("requested_reviewer")
    if role not in ROLE_NAMES:
        errors.append("$.role: unknown role")
    if requester != role:
        errors.append("$.requesting_role: must equal role")
    if reviewer not in ROLE_NAMES:
        errors.append("$.requested_reviewer: unknown reviewer")
    elif reviewer == role:
        errors.append("$.requested_reviewer: must be independent")
    evidence = appeal.get("evidence")
    if not isinstance(evidence, list) or not evidence or not all(isinstance(value, str) and value.strip() for value in evidence):
        errors.append("$.evidence: expected a non-empty string array")
    if not isinstance(scorecard, dict) or appeal.get("scorecard_id") != scorecard.get("scorecard_id"):
        errors.append("$.scorecard_id: does not identify the supplied scorecard")
        return errors
    original = next((item for item in scorecard.get("roles", []) if isinstance(item, dict) and item.get("role") == role), None)
    if original is None:
        errors.append("$.role: does not identify a scorecard role")
    elif reviewer == original.get("reviewer_role"):
        errors.append("$.requested_reviewer: must differ from original reviewer")
    return errors


def validate_training_candidate(candidate: object) -> list[str]:
    """Return errors for a reviewed candidate; this never starts a training job."""
    if not isinstance(candidate, dict):
        return ["$: expected training candidate object"]
    required = {"schema_version", "candidate_id", "role", "capability_gap", "recent_verified_tasks", "status"}
    errors = []
    if set(candidate) != required:
        errors.append("$: required field set mismatch or forbidden training operation")
    if candidate.get("schema_version") != "1.0":
        errors.append("$.schema_version: must equal '1.0'")
    if candidate.get("status") != "TRAINING_CANDIDATE":
        errors.append("$.status: must equal 'TRAINING_CANDIDATE'")
    if candidate.get("role") not in ROLE_NAMES:
        errors.append("$.role: unknown role")
    gap = candidate.get("capability_gap")
    if not isinstance(gap, str) or not gap.strip():
        errors.append("$.capability_gap: expected non-empty string")
    tasks = candidate.get("recent_verified_tasks")
    if not isinstance(tasks, list) or not 3 <= len(tasks) <= 10:
        errors.append("$.recent_verified_tasks: expected 3..10 items")
    else:
        matching_gaps = 0
        for index, task in enumerate(tasks):
            path = f"$.recent_verified_tasks[{index}]"
            if not isinstance(task, dict) or set(task) != {
                "task_id", "verified", "qa_verdict", "closed_status", "timestamp", "evidence", "capability_gaps",
            }:
                errors.append(f"{path}: required field set mismatch")
                continue
            if not isinstance(task["task_id"], str) or not task["task_id"].strip():
                errors.append(f"{path}.task_id: expected non-empty string")
            if task["verified"] is not True:
                errors.append(f"{path}.verified: must be true")
            if task.get("qa_verdict") != "PASS":
                errors.append(f"{path}.qa_verdict: must equal 'PASS'")
            if task.get("closed_status") != "CLOSED":
                errors.append(f"{path}.closed_status: must equal 'CLOSED'")
            if not isinstance(task.get("timestamp"), str) or not task["timestamp"].strip():
                errors.append(f"{path}.timestamp: expected non-empty string")
            if not isinstance(task.get("evidence"), list) or not task["evidence"] or not all(isinstance(value, str) and value.strip() for value in task["evidence"]):
                errors.append(f"{path}.evidence: expected a non-empty string array")
            gaps = task["capability_gaps"]
            if not isinstance(gaps, list) or not gaps or not all(isinstance(value, str) and value.strip() for value in gaps):
                errors.append(f"{path}.capability_gaps: expected non-empty string array")
            elif gap in gaps:
                matching_gaps += 1
        if matching_gaps < 3:
            errors.append("$.capability_gap: must occur in at least three verified tasks")
        task_ids = [task.get("task_id") for task in tasks if isinstance(task, dict)]
        if len(task_ids) != len(set(task_ids)):
            errors.append("$.recent_verified_tasks: task IDs must be unique")
    return errors


def validate_skill_seat(seat: object) -> list[str]:
    """Return errors unless a temporary advisory seat is fully sponsored and bounded."""
    required = {
        "seat_id", "skill_path", "sponsor_role", "purpose", "scope", "permitted_inputs",
        "expected_output", "evidence", "expires_at",
    }
    if not isinstance(seat, dict):
        return ["$: expected skill seat object"]
    errors = []
    if set(seat) != required:
        errors.append("$: field set mismatch or forbidden authority field")
    if not isinstance(seat.get("seat_id"), str) or not seat["seat_id"].startswith("WG-SEAT-"):
        errors.append("$.seat_id: expected WG-SEAT identifier")
    if seat.get("sponsor_role") not in ROLE_NAMES:
        errors.append("$.sponsor_role: unknown fixed role")
    for field in ("skill_path", "purpose", "scope", "expected_output", "expires_at"):
        if not isinstance(seat.get(field), str) or not seat[field].strip():
            errors.append(f"$.{field}: expected non-empty string")
    for field in ("permitted_inputs", "evidence"):
        values = seat.get(field)
        if not isinstance(values, list) or not values or not all(isinstance(value, str) and value.strip() for value in values):
            errors.append(f"$.{field}: expected non-empty string array")
    return errors


def parse_openai_yaml(text: str) -> dict[str, dict[str, str]]:
    """Parse the repository's deliberately small openai.yaml mapping without a dependency."""
    expected = {"display_name", "short_description", "default_prompt"}
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines or lines[0] != "interface:":
        raise ValueError("openai.yaml: expected interface mapping")
    interface: dict[str, str] = {}
    for line in lines[1:]:
        if not line.startswith("  ") or line.startswith("   "):
            raise ValueError("openai.yaml: expected two-space interface field")
        key, separator, scalar = line[2:].partition(": ")
        if not separator or key not in expected or key in interface:
            raise ValueError("openai.yaml: invalid or duplicate interface field")
        try:
            value = json.loads(scalar)
        except json.JSONDecodeError as exc:
            raise ValueError("openai.yaml: expected JSON-quoted scalar") from exc
        if not isinstance(value, str) or not value:
            raise ValueError("openai.yaml: interface values must be non-empty strings")
        interface[key] = value
    if set(interface) != expected:
        raise ValueError("openai.yaml: required interface fields are incomplete")
    return {"interface": interface}


def _validate_openai_yaml(root: Path, errors: list[str]) -> None:
    source = root / ".agents/skills/orchestrating-workers-group/agents/openai.yaml"
    parsed = parse_openai_yaml(source.read_text(encoding="utf-8"))
    if parsed["interface"]["display_name"] != "打工人集團":
        errors.append("openai.yaml display name mismatch")


def _validate_public_source(root: Path, errors: list[str]) -> None:
    """Validate a root-level public clone without pretending it is a host install."""
    skill = root / "SKILL.md"
    content = skill.read_text(encoding="utf-8")
    parts = content.split("---", 2)
    if len(parts) < 3:
        errors.append("SKILL.md frontmatter is incomplete")
    else:
        frontmatter = [line for line in parts[1].strip().splitlines() if line.strip()]
        expected = ["name: orchestrating-workers-group", f"description: {DESCRIPTION}"]
        if frontmatter != expected:
            errors.append("SKILL.md frontmatter must contain the exact name and description")
    for required in CURRENT_GOVERNANCE_CONDITIONS + (
        "verification_mode", "basic", "strict", "boss_verification",
    ):
        if required not in content:
            errors.append(f"SKILL.md missing governance condition: {required}")
    for reference in REFERENCE_ROUTES | DETAILED_GOVERNANCE_REFERENCES:
        if not (root / reference).is_file():
            errors.append(f"public reference target is missing: {reference}")
    for asset in (root / "assets").glob("*.json"):
        try:
            json.loads(asset.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            errors.append(f"invalid public asset {asset.name}: {exc}")
    for script in (root / "scripts").glob("*.py"):
        try:
            ast.parse(script.read_text(encoding="utf-8"), filename=str(script))
        except (OSError, UnicodeError, SyntaxError) as exc:
            errors.append(f"invalid public script {script.name}: {exc}")
    readme_path = root / "README.md"
    if readme_path.is_file() and "V0.5.0" not in readme_path.read_text(encoding="utf-8"):
        errors.append("README.md version must be V0.5.0")
    scripts = root / "scripts"
    sys.path.insert(0, str(scripts))
    try:
        hook = runpy.run_path(str(scripts / "workers_group_hook.py"))
        mode = hook["verification_mode_for_prompt"]
        if mode("$orchestrating-workers-group 一般修改") != "basic":
            errors.append("public Hook basic mode classification failed")
        if mode("$orchestrating-workers-group 請做完整 QA") != "strict":
            errors.append("public Hook strict mode classification failed")
    except (OSError, ImportError, KeyError, RuntimeError, ValueError) as exc:
        errors.append(f"public Hook smoke failed: {exc}")
    finally:
        sys.path.remove(str(scripts))


def validate(root: Path) -> dict:
    errors: list[str] = []
    if (root / "SKILL.md").is_file() and (root / "scripts").is_dir() and (root / "references").is_dir():
        _validate_public_source(root, errors)
        return {"valid": not errors, "errors": errors}
    checks = (
        _validate_skill_file, _validate_hooks, _validate_agents_and_tiers,
        _validate_states_and_templates, _validate_governance_schemas, _validate_openai_yaml,
    )
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
