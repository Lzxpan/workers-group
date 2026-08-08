"""Shared dispatcher for project-scoped Workers Group lifecycle Hooks."""

from __future__ import annotations

import argparse
import json
import ntpath
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from create_task import create_task
from memory_retriever import MemoryRetriever
from memory_store import MemoryStore, atomic_write_text, file_lock
from state_store import StateStore, _persistence_guard, find_git_root
from validate_report import _command_errors, _evidence_errors, _test_errors, validate_document
from workers_group_paths import CODEX_HOME, STATIC_ROOT

PREFIX = "打工人集團｜"
DISPLAY = {
    "SessionStart": PREFIX + "載入任務與長期記憶",
    "UserPromptSubmit": PREFIX + "分析需求與啟動團隊",
    "SubagentStart": PREFIX + "注入子代理角色規範",
    "SubagentStop": PREFIX + "驗證子代理工作報告",
    "PreToolUse": PREFIX + "工具安全與範圍檢查",
    "PermissionRequest": PREFIX + "審查高風險操作",
    "PostToolUse": PREFIX + "收集測試與建置證據",
    "PreCompact": PREFIX + "保存壓縮前任務狀態",
    "PostCompact": PREFIX + "恢復壓縮後任務狀態",
    "Stop": PREFIX + "執行完成度與品質閘門",
    "SessionEnd": PREFIX + "封存工作經驗與記憶",
}
DESTRUCTIVE = re.compile(
    r"(?i)(?:\brm\s+-rf\s+(?:/|~|\$HOME)(?:\s|$)|"
    r"\b(?:del|rmdir)\b.*(?:/s|/q).*(?:[A-Z]:\\|\\Users\\)(?:\s|$))"
)
SECRET_ACCESS = re.compile(r"(?i)(?:\.env\b|id_rsa\b|credentials?|api[_-]?keys?|secrets?)")
CORE_BYPASS = re.compile(r"(?i)(?:Skill Doctor|skill_doctor).*(?:bypass|disable|skip)")
GOVERNANCE_TRIGGER = re.compile(
    r"(?ix)(?:"
    r"\$orchestrating-workers-group|"
    r"複雜(?:工作|任務|專案)|多階段|跨模組|跨系統|高風險|多代理|"
    r"獨立\s*(?:QA|品質驗證)|QA\s*獨立(?:驗證|審查)|"
    r"\bcomplex\s+(?:work|task|project|migration|implementation)\b|"
    r"\bmulti[-\s]?stage\b|\bcross[-\s]?module\b|"
    r"\bhigh[-\s]?risk\b|\bmulti[-\s]?agent\b|\bindependent\s+QA\b"
    r")"
)
POWERSHELL_REMOVE_ITEM = re.compile(r"(?i)\bRemove-Item\b")
POWERSHELL_RECURSE = re.compile(r"(?i)(?:^|\s)-Recurse(?=$|\s|[;|\"'])")
POWERSHELL_PATH_ARGUMENT = re.compile(
    r"""(?ix)(?:-LiteralPath|-Path)(?:\s*[:=]\s*|\s+)
    (?:"([^"]+)"|'([^']+)'|([^\s;|]+))"""
)
SHELL_TOKEN = re.compile(r""""[^"]*"|'[^']*'|[^\s;|]+""")
PATCH_FILE_HEADER = re.compile(
    r"^\*\*\*\s+(?:Update|Add|Delete)\s+File:\s*(.+?)\s*$|"
    r"^\*\*\*\s+Move\s+to:\s*(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
PROTECTED_FILES = {
    "agents.md",
    ".codex/config.toml",
    ".codex/hooks.json",
    ".agents/skills/orchestrating-workers-group/skill.md",
}
PROTECTED_PREFIXES = (
    ".codex/hooks/",
    ".codex/agents/",
    ".agents/skills/orchestrating-workers-group/scripts/",
    ".agents/skills/orchestrating-workers-group/references/",
    ".workers-group/config/",
    ".workers-group/schemas/",
)
GLOBAL_PROTECTED_FILES = {"config.toml", "hooks.json", "skills/orchestrating-workers-group/skill.md"}
GLOBAL_PROTECTED_PREFIXES = (
    "hooks/", "agents/", "skills/orchestrating-workers-group/scripts/",
    "skills/orchestrating-workers-group/references/",
)
GLOBAL_STATIC_PROTECTED_PREFIXES = ("config/", "schemas/")
EVIDENCE_COMMAND = re.compile(
    r"(?i)(?:\btest\b|pytest|unittest|lint|mypy|pyright|type.?check|build|compile|package|"
    r"validate|git\s+diff|git\s+status)"
)
ROLE_CONTRACTS = {
    "workers_boss": "Own the Task Charter, human authority boundary, and final evidence gate.",
    "workers_planner": "Define scope, feasibility-reviewed work items, acceptance criteria, and evidence.",
    "workers_pm": "Track dependencies, legal state transitions, blockers, and file ownership.",
    "workers_executor": "Modify only owned files; record commands, exit codes, failures, and evidence.",
    "workers_qa": "Remain independent and read-only; reproduce checks and issue a truthful verdict.",
}
SAFE_STATE_FIELDS = {
    "task_id", "title", "objective", "status", "work_items", "acceptance_criteria",
    "blockers", "remaining_work",
    "missing_evidence", "failed_tests", "qa_verdict", "overall_verdict", "boss_reviewed",
    "next_steps", "memory_ids", "file_claims", "updated_at", "last_session_ended_at",
}
GAP_STATUSES = {
    "INTAKE", "KICKOFF", "PLANNING", "AWAITING_HUMAN_APPROVAL", "EXECUTING",
    "EVIDENCE_REVIEW", "QA", "BOSS_REVIEW", "BLOCKED", "FAILED", "NOT_VERIFIED",
}
SENSITIVE_TEXT = re.compile(
    r"(?i)(?:(?<![A-Za-z0-9_-])sk-[A-Za-z0-9_-]{8,}|"
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|"
    r"(?:password|token|secret|api[_-]?key)\s*[=:]\s*\S+|-----BEGIN [A-Z ]*PRIVATE KEY-----)"
)
PENDING_MEMORY_LIMIT = 8
MEMORY_TOP_K = 8
MEMORY_BUDGET_CHARS = 4096
MAX_STDIN_BYTES = 1048576
COMPLETION_GAP_STATUSES = GAP_STATUSES
ROLE_COMPLETION_STATUSES = {
    "workers_boss": {"CLOSED"},
    "workers_planner": {"PLANNING"},
    "workers_pm": {"BOSS_REVIEW"},
    "workers_executor": {"EVIDENCE_REVIEW"},
}


def _command_text(payload: dict) -> str:
    """Flatten nested tool input without invoking arbitrary object representations."""
    strings: list[str] = []

    def collect(value: object, depth: int = 0) -> None:
        if depth > 8 or sum(map(len, strings)) >= 65536:
            return
        if isinstance(value, str):
            strings.append(value[:16384])
        elif isinstance(value, dict):
            for key, child in value.items():
                if isinstance(key, str):
                    collect(child, depth + 1)
        elif isinstance(value, list):
            for child in value[:100]:
                collect(child, depth + 1)

    for field in ("command", "tool_input", "toolInput"):
        collect(payload.get(field))
    return "\n".join(strings)[:65536]


def _strip_shell_quotes(value: str) -> str:
    candidate = value.strip()
    while len(candidate) >= 2 and candidate[0] == candidate[-1] and candidate[0] in {"'", '"'}:
        candidate = candidate[1:-1].strip()
    return candidate


def _normalized_windows_path(value: str, root: Path | None) -> str | None:
    candidate = _strip_shell_quotes(value).rstrip(",")
    if not candidate or "\x00" in candidate:
        return None
    candidate = candidate.replace("/", "\\")
    if not ntpath.isabs(candidate):
        if root is None:
            return None
        candidate = ntpath.join(str(root), candidate)
    return ntpath.normcase(ntpath.normpath(candidate))


def _is_same_or_parent(candidate: str, protected_root: str) -> bool:
    try:
        return ntpath.commonpath((candidate, protected_root)) == candidate
    except ValueError:
        return False


def _payload_workspace_roots(payload: dict, root: Path | None) -> set[str]:
    roots: set[str] = set()
    if root is not None:
        normalized = _normalized_windows_path(str(root), None)
        if normalized:
            roots.add(normalized)

    def collect(value: object, depth: int = 0) -> None:
        if depth > 6:
            return
        if isinstance(value, dict):
            for key, child in value.items():
                if key in {"workspaceRoot", "workspace_root", "repositoryRoot", "repository_root"}:
                    if isinstance(child, str):
                        normalized = _normalized_windows_path(child, root)
                        if normalized:
                            roots.add(normalized)
                else:
                    collect(child, depth + 1)
        elif isinstance(value, list):
            for child in value[:100]:
                collect(child, depth + 1)

    collect(payload)
    return roots


def _powershell_remove_targets(command: str) -> list[str]:
    targets: list[str] = []
    for invocation in POWERSHELL_REMOVE_ITEM.finditer(command):
        segment = re.split(r"[;\r\n|]", command[invocation.start():], maxsplit=1)[0]
        explicit_targets: list[str] = []
        for match in POWERSHELL_PATH_ARGUMENT.finditer(segment):
            target = next((group for group in match.groups() if group is not None), "")
            if target:
                explicit_targets.append(target)
        if explicit_targets:
            targets.extend(explicit_targets)
            continue

        # A positional path is legal PowerShell. Keep only non-option tokens and
        # let the broad-target check below decide whether one is protected.
        remove_seen = False
        for match in SHELL_TOKEN.finditer(segment):
            token = _strip_shell_quotes(match.group(0))
            if token.casefold() == "remove-item":
                remove_seen = True
                continue
            if remove_seen and token and not token.startswith("-"):
                targets.append(token)
    return targets


def _is_broad_recursive_remove(payload: dict, root: Path | None, command: str) -> bool:
    if not POWERSHELL_REMOVE_ITEM.search(command) or not POWERSHELL_RECURSE.search(command):
        return False
    protected_roots = _payload_workspace_roots(payload, root)
    for raw_target in _powershell_remove_targets(command):
        target = _strip_shell_quotes(raw_target)
        if re.fullmatch(r"(?i)(?:[A-Z]:[\\/]*|/|~|\$HOME|\$env:(?:USERPROFILE|HOME))", target):
            return True
        normalized = _normalized_windows_path(target, root)
        if normalized and any(_is_same_or_parent(normalized, protected) for protected in protected_roots):
            return True
    return False


def _tool_name(payload: dict) -> str:
    return str(payload.get("tool_name") or payload.get("toolName") or payload.get("tool") or "")


def _tool_input(payload: dict) -> object:
    if "tool_input" in payload:
        return payload["tool_input"]
    return payload.get("toolInput")


def _write_targets(payload: dict) -> list[str]:
    tool = _tool_name(payload).casefold()
    if tool not in {"apply_patch", "edit", "write"}:
        return []
    tool_input = _tool_input(payload)
    targets: list[str] = []
    if isinstance(tool_input, dict):
        for field in ("file_path", "filePath", "path"):
            value = tool_input.get(field)
            if isinstance(value, str):
                targets.append(value)
        patch = tool_input.get("patch")
    else:
        patch = tool_input
    if tool == "apply_patch" and isinstance(patch, str):
        for match in PATCH_FILE_HEADER.finditer(patch[:65536]):
            target = next((group for group in match.groups() if group is not None), "")
            if target:
                targets.append(target)
    return targets


def _repo_relative_path(value: str, root: Path | None) -> str | None:
    if root is None:
        return None
    normalized_root = _normalized_windows_path(str(root), None)
    normalized_target = _normalized_windows_path(value, root)
    if not normalized_root or not normalized_target:
        return None
    try:
        relative = ntpath.relpath(normalized_target, normalized_root)
    except ValueError:
        return None
    if relative == ntpath.pardir or relative.startswith(ntpath.pardir + "\\"):
        return None
    return relative.replace("\\", "/").casefold()


def _is_direct_core_write(payload: dict, root: Path | None) -> bool:
    # A real Skill Doctor apply is invoked through its controlled CLI. A caller
    # cannot authorize a direct write merely by placing "Skill Doctor" in text.
    for target in _write_targets(payload):
        relative = _repo_relative_path(target, root)
        if relative is not None and (
            relative in PROTECTED_FILES or any(relative.startswith(prefix) for prefix in PROTECTED_PREFIXES)
        ):
            return True
        absolute = _normalized_windows_path(target, root)
        codex_root = _normalized_windows_path(str(CODEX_HOME), None)
        sibling_agents_root = _normalized_windows_path(
            str(Path(CODEX_HOME).parent / ".agents"), None,
        )
        static_root = _normalized_windows_path(str(STATIC_ROOT), None)
        for protected_root, files, prefixes in (
            (codex_root, GLOBAL_PROTECTED_FILES, GLOBAL_PROTECTED_PREFIXES),
            (
                sibling_agents_root,
                {"skills/orchestrating-workers-group/skill.md"},
                (
                    "agents/",
                    "skills/orchestrating-workers-group/scripts/",
                    "skills/orchestrating-workers-group/references/",
                ),
            ),
            (static_root, set(), GLOBAL_STATIC_PROTECTED_PREFIXES),
        ):
            if not absolute or not protected_root:
                continue
            try:
                global_relative = ntpath.relpath(absolute, protected_root)
            except ValueError:
                continue
            if global_relative == ntpath.pardir or global_relative.startswith(ntpath.pardir + "\\"):
                continue
            global_relative = global_relative.replace("\\", "/").casefold()
            if global_relative in files or any(global_relative.startswith(prefix) for prefix in prefixes):
                return True
    return False


def _pre_tool_risk(payload: dict, root: Path | None) -> str | None:
    command = _command_text(payload)
    if _is_direct_core_write(payload, root):
        return "Direct modification of protected governance files requires controlled Skill Doctor apply."
    if _is_broad_recursive_remove(payload, root, command) or DESTRUCTIVE.search(command):
        return "Broad destructive filesystem operation denied."
    if SECRET_ACCESS.search(command):
        return "Secret access operation denied."
    if CORE_BYPASS.search(command):
        return "Governance-bypass operation denied."
    return None


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _repo_root() -> Path | None:
    try:
        return find_git_root(Path.cwd())
    except (OSError, FileNotFoundError):
        return None


def _runtime(root: Path) -> Path:
    return root / ".workers-group" / "runtime"


def _read_object(path: Path, *, max_bytes: int = 262144) -> dict:
    if not path.is_file():
        return {}
    if path.stat().st_size > max_bytes:
        return {"_state_error": "state file exceeds size limit"}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"state must be an object: {path.name}")
    return value


def _active_task(root: Path | None) -> dict:
    if root is None:
        return {}
    try:
        return _read_object(_runtime(root) / "active-task.json")
    except (OSError, json.JSONDecodeError, ValueError):
        return {"_state_error": "active task is unreadable"}


def _sanitize(value: object) -> object:
    if isinstance(value, str):
        return SENSITIVE_TEXT.sub("[REDACTED]", value)[:1000]
    if isinstance(value, list):
        return [_sanitize(item) for item in value[:100]]
    if isinstance(value, dict):
        return {str(key)[:100]: _sanitize(child) for key, child in list(value.items())[:100]}
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return "[UNSUPPORTED]"


def _safe_task(state: dict) -> dict:
    return {field: _sanitize(state[field]) for field in SAFE_STATE_FIELDS if field in state}


def _repository_file(root: Path, value: object, label: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}: repository file path is required")
    candidate = Path(value)
    candidate = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"{label}: path must stay inside the repository") from exc
    if not candidate.is_file():
        raise ValueError(f"{label}: path must be a readable regular file")
    try:
        with candidate.open("rb") as stream:
            stream.read(1)
    except OSError as exc:
        raise ValueError(f"{label}: path must be a readable regular file") from exc
    return candidate


def _load_repo_json(root: Path, value: object, label: str) -> dict:
    path = _repository_file(root, value, label)
    if path.stat().st_size > 1048576:
        raise ValueError(f"{label}: file exceeds size limit")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label}: expected valid UTF-8 JSON") from exc
    if not isinstance(document, dict):
        raise ValueError(f"{label}: expected JSON object")
    return document


def _payload_document(
    payload: dict,
    root: Path,
    *,
    inline_keys: tuple[str, ...],
    path_keys: tuple[str, ...],
    label: str,
) -> dict | None:
    for key in inline_keys:
        value = payload.get(key)
        if isinstance(value, dict):
            return value
        if isinstance(value, str) and value.strip():
            return _load_repo_json(root, value, label)
    for key in path_keys:
        value = payload.get(key)
        if value:
            return _load_repo_json(root, value, label)
    return None


def _report_errors(
    report: dict | None,
    *,
    kind: str,
    root: Path,
    task_id: str,
    role: str,
    label: str,
) -> list[str]:
    if report is None:
        return [f"{label}: report is required"]
    result = validate_document(kind, report, repository_root=root)
    errors = [f"{label}: {error}" for error in result.get("errors", [])]
    if report.get("task_id") != task_id:
        errors.append(f"{label}: task_id must match active task")
    if report.get("role") != role:
        errors.append(f"{label}: role must be {role}")
    if kind == "role-report":
        errors.extend(
            f"{label}: {error}"
            for error in _command_errors(report.get("commands_run"), "$.commands_run")
        )
        errors.extend(
            f"{label}: {error}"
            for error in _test_errors(report.get("tests"), "$.tests")
        )
        if report.get("status") not in ROLE_COMPLETION_STATUSES.get(role, set()):
            errors.append(f"{label}: status is not a completion status for {role}")
    errors.extend(
        f"{label}: {error}"
        for error in _evidence_errors(
            report.get("evidence"),
            "$.evidence",
            root,
        )
    )
    if kind == "qa-report":
        for index, criterion in enumerate(report.get("criteria_results", [])):
            if isinstance(criterion, dict):
                errors.extend(
                    f"{label}: {error}"
                    for error in _evidence_errors(
                        criterion.get("evidence"),
                        f"$.criteria_results[{index}].evidence",
                        root,
                    )
                )
    errors = list(dict.fromkeys(errors))
    return errors


def _criterion_document(root: Path, entry: object, index: int) -> dict:
    if isinstance(entry, dict) and "path" in entry:
        return _load_repo_json(root, entry["path"], f"acceptance_criteria[{index}]")
    if isinstance(entry, dict) and "id" in entry:
        return entry
    if isinstance(entry, str):
        candidate = Path(entry)
        if not candidate.suffix:
            candidate = Path(".workers-group/state") / f"{entry}.json"
        return _load_repo_json(root, str(candidate), f"acceptance_criteria[{index}]")
    raise ValueError(f"acceptance_criteria[{index}]: criterion document is required")


def _acceptance_errors(
    root: Path,
    entries: object,
    *,
    task_id: str,
    require_pass: bool,
) -> list[str]:
    if not isinstance(entries, list) or not entries:
        return ["acceptance_criteria: at least one criterion document is required"]
    errors: list[str] = []
    if len(entries) > 100:
        errors.append("acceptance_criteria: exceeds bounded limit of 100")
    for index, entry in enumerate(entries[:100]):
        try:
            if isinstance(entry, dict) and "task_id" in entry and entry.get("task_id") != task_id:
                errors.append(f"acceptance_criteria[{index}]: task_id must match active task")
            document = _criterion_document(root, entry, index)
            result = validate_document(
                "acceptance-criterion",
                document,
                repository_root=root,
            )
            errors.extend(
                f"acceptance_criteria[{index}]: {error}"
                for error in result.get("errors", [])
            )
            if require_pass and (
                document.get("status") != "PASS" or document.get("verdict") != "PASS"
            ):
                errors.append(
                    f"acceptance_criteria[{index}]: status and verdict must both be PASS"
                )
        except (OSError, ValueError) as exc:
            errors.append(str(exc))
    return errors


def _transition_record_errors(root: Path, value: object, task_id: str) -> list[str]:
    if isinstance(value, dict):
        if value.get("task_id") != task_id:
            return ["transition_record: task_id must match active task"]
        if not value.get("from_status") or not value.get("to_status"):
            return ["transition_record: from_status and to_status are required"]
        return []
    if isinstance(value, str):
        try:
            path = _repository_file(root, value, "transition_record")
            with path.open("rb") as stream:
                size = stream.seek(0, os.SEEK_END)
                start = max(0, size - 1048576)
                stream.seek(start)
                tail = stream.read(1048576)
            if start:
                tail = tail.split(b"\n", 1)[-1]
            lines = tail.decode("utf-8").splitlines()
            records = [json.loads(line) for line in lines[-100:] if line.strip()]
            if any(
                isinstance(record, dict)
                and record.get("task_id") == task_id
                and record.get("from_status")
                and record.get("to_status")
                for record in records
            ):
                return []
            return ["transition_record: no bounded record matches active task"]
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            return [str(exc)]
    return ["transition_record: PM completion requires a transition record"]


def _completion_report_gaps(
    payload: dict,
    state: dict,
    root: Path | None,
    event: str,
) -> list[str]:
    if root is None:
        return ["repository root is unavailable"] if payload.get("report") else []
    task_id = str(state.get("task_id") or payload.get("task_id") or payload.get("taskId") or "")
    role = str(
        payload.get("agent_type")
        or payload.get("agentType")
        or payload.get("role")
        or ""
    )
    has_report = any(payload.get(key) for key in (
        "report", "reportPath", "report_path", "qaReport", "qa_report",
        "bossReport", "boss_report",
    ))
    if event == "SubagentStop" and not role and not has_report:
        return []
    if event == "Stop" and not has_report and state.get("status") != "CLOSED":
        return []
    errors: list[str] = []
    if not task_id:
        return ["completion report: active task_id is required"]

    report = _payload_document(
        payload,
        root,
        inline_keys=("report",),
        path_keys=("reportPath", "report_path"),
        label="report",
    )
    if event == "SubagentStop":
        if role == "workers_qa":
            errors.extend(_report_errors(
                report,
                kind="qa-report",
                root=root,
                task_id=task_id,
                role=role,
                label="qa_report",
            ))
            if report is not None and report.get("overall_verdict") != "PASS":
                errors.append("qa_report: completion requires PASS verdict")
        else:
            errors.extend(_report_errors(
                report,
                kind="role-report",
                root=root,
                task_id=task_id,
                role=role,
                label="role_report",
            ))
            if role == "workers_planner":
                entries = payload.get("acceptanceCriteria", state.get("acceptance_criteria"))
                errors.extend(_acceptance_errors(
                    root, entries, task_id=task_id, require_pass=False,
                ))
            elif role == "workers_pm":
                record = payload.get(
                    "transitionRecord",
                    payload.get("transition_record", state.get("transition_record")),
                )
                errors.extend(_transition_record_errors(root, record, task_id))
        return errors

    boss_report = report or _payload_document(
        payload,
        root,
        inline_keys=("bossReport", "boss_report"),
        path_keys=("bossReportPath", "boss_report_path"),
        label="boss_report",
    )
    qa_report = _payload_document(
        payload,
        root,
        inline_keys=("qaReport", "qa_report"),
        path_keys=("qaReportPath", "qa_report_path"),
        label="qa_report",
    )
    if qa_report is None and state.get("qa_report"):
        qa_report = _load_repo_json(root, state["qa_report"], "qa_report")
    if boss_report is None and state.get("boss_report"):
        boss_report = _load_repo_json(root, state["boss_report"], "boss_report")
    errors.extend(_report_errors(
        boss_report,
        kind="role-report",
        root=root,
        task_id=task_id,
        role="workers_boss",
        label="boss_report",
    ))
    errors.extend(_report_errors(
        qa_report,
        kind="qa-report",
        root=root,
        task_id=task_id,
        role="workers_qa",
        label="qa_report",
    ))
    if boss_report is not None and boss_report.get("status") != "CLOSED":
        errors.append("boss_report: final review status must be CLOSED")
    if qa_report is not None and qa_report.get("overall_verdict") != "PASS":
        errors.append("qa_report: final completion requires PASS verdict")

    completion = payload.get("completionState", payload.get("completion_state"))
    closure = completion if isinstance(completion, dict) else state
    status = closure.get("status")
    if status in COMPLETION_GAP_STATUSES:
        errors.append(f"status: {status} cannot complete")
    elif status != "CLOSED":
        errors.append("status: final completion status must be CLOSED")
    errors.extend(_acceptance_errors(
        root,
        closure.get("acceptance_criteria"),
        task_id=task_id,
        require_pass=True,
    ))
    if "failed_tests" not in closure:
        errors.append("failed_tests: test failure disclosure is required")
    elif closure.get("failed_tests"):
        errors.append("failed_tests: unresolved failing tests remain")
    evidence = closure.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        errors.append("evidence: PASS completion evidence is required")
    else:
        if len(evidence) > 100:
            errors.append("evidence: exceeds bounded limit of 100")
        for index, value in enumerate(evidence[:100]):
            try:
                _repository_file(root, value, f"evidence[{index}]")
            except ValueError as exc:
                errors.append(str(exc))
    if closure.get("boss_reviewed") is not True:
        errors.append("boss_reviewed: Boss final review is required")
    if closure.get("scope_drift_checked") is not True:
        errors.append("scope_drift_checked: scope drift review is required")
    if closure.get("scope_drift"):
        errors.append("scope_drift: unresolved scope drift remains")
    if closure.get("limitations_disclosed") is not True:
        errors.append("limitations_disclosed: limitations must be explicitly disclosed")
    if closure.get("skill_migration_complete") is not True or closure.get("pending_skill_migrations"):
        errors.append("skill_migration_complete: Skill migration is incomplete")
    if closure.get("self_improvement_verified") is not True:
        errors.append("self_improvement_verified: self-improvement remains unverified")
    return errors


def _state_has_gaps(state: dict) -> bool:
    if not state:
        return False
    if state.get("_state_error"):
        return True
    if state.get("status") in GAP_STATUSES:
        return True
    for field in (
        "missing_evidence", "failed_tests", "blockers", "remaining_work", "unverified_items",
        "needs_rework", "qa_failed",
    ):
        if state.get(field):
            return True
    criteria = state.get("acceptance_criteria")
    if isinstance(criteria, list):
        for criterion in criteria:
            if (
                isinstance(criterion, dict)
                and ("verdict" in criterion or "status" in criterion)
                and criterion.get("verdict", criterion.get("status")) not in {"PASS", "WAIVED"}
            ):
                return True
    verdict = state.get("qa_verdict", state.get("overall_verdict"))
    if verdict and verdict != "PASS" and not state.get("human_waiver"):
        return True
    return False


def _extract_exit_code(payload: dict) -> int | None:
    candidates = [
        payload.get("exit_code"), payload.get("exitCode"),
        payload.get("tool_result"), payload.get("toolResult"), payload.get("tool_response"),
    ]
    for candidate in candidates:
        if isinstance(candidate, int) and not isinstance(candidate, bool):
            return candidate
        if isinstance(candidate, dict):
            value = candidate.get("exit_code", candidate.get("exitCode"))
            if isinstance(value, int) and not isinstance(value, bool):
                return value
    return None


def _record_evidence(root: Path, payload: dict, state: dict) -> bool:
    tool = str(payload.get("tool_name") or payload.get("toolName") or payload.get("tool") or "")
    command = _command_text(payload)
    valuable = tool in {"apply_patch", "Edit", "Write"} or (
        tool in {"Bash", "Agent"} and bool(EVIDENCE_COMMAND.search(command))
    )
    if not valuable:
        return False
    sensitive = any(pattern.search(command) for pattern in (SECRET_ACCESS, SENSITIVE_TEXT))
    event = {
        "timestamp": _now(),
        "tool": tool,
        "exit_code": _extract_exit_code(payload),
        "task_id": state.get("task_id"),
        "work_item_id": payload.get("work_item_id") or state.get("work_item_id"),
        "command_summary": "[REDACTED]" if sensitive else " ".join(command.split())[:500],
    }
    path = _runtime(root) / "evidence-events.json"
    store = StateStore(path)
    ledger = store.read_state()
    events = ledger.get("events", [])
    if not isinstance(events, list):
        events = []
    events.append(event)
    store.write_state({"events": events[-100:]})
    return True


def _append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_suffix(path.suffix + ".lock")
    descriptor: int | None = None
    for _ in range(20):
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            time.sleep(0.005)
    if descriptor is None:
        raise TimeoutError(f"JSONL lock timeout: {path.name}")
    os.close(descriptor)
    try:
        with path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        lock.unlink(missing_ok=True)


def _memory_retrieval(root: Path, query: str, task_id: str, role: str) -> dict:
    result = MemoryRetriever(_runtime(root) / "memory.sqlite3").retrieve(
        query,
        task_id=task_id,
        role=role,
        top_k=MEMORY_TOP_K,
        budget_chars=MEMORY_BUDGET_CHARS,
    )
    return {
        "task_id": task_id,
        "role": role,
        "items": [
            {
                "id": item["id"],
                "title": item.get("title", ""),
                "summary": item.get("summary", ""),
                "content": item.get("content", ""),
                "score": item.get("score"),
            }
            for item in result["items"]
        ],
        "strategy": result["strategy"],
        "ledger": result["ledger"],
        "budget": result["budget"],
    }


def _process_pending_memories(root: Path, store: MemoryStore) -> dict:
    queue = _runtime(root) / "pending-memory-queue.jsonl"
    if not queue.is_file():
        return {"processed": 0, "remaining": 0, "errors": []}
    processed = 0
    errors: list[str] = []
    with file_lock(queue, timeout=0.5):
        if queue.stat().st_size > 1048576:
            return {"processed": 0, "remaining": -1, "errors": ["queue exceeds size limit"]}
        lines = queue.read_text(encoding="utf-8").splitlines()
        remaining: list[str] = []
        for index, line in enumerate(lines):
            if index >= PENDING_MEMORY_LIMIT:
                remaining.append(line)
                continue
            try:
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise ValueError("candidate must be an object")
                if record.pop("autoActivateVerifiedExperience", False):
                    store.add_verified_experience(record)
                else:
                    store.add_candidate(record)
                processed += 1
            except ValueError as exc:
                if "duplicate memory content" in str(exc):
                    processed += 1
                else:
                    remaining.append(line)
                    errors.append(f"line {index + 1}: {type(exc).__name__}")
            except (OSError, json.JSONDecodeError, TypeError) as exc:
                remaining.append(line)
                errors.append(f"line {index + 1}: {type(exc).__name__}")
        atomic_write_text(
            queue,
            "".join(f"{line}\n" for line in remaining),
        )
    return {"processed": processed, "remaining": len(remaining), "errors": errors}


def _retrieval_query(payload: dict, active: dict) -> str:
    prompt = str(payload.get("prompt") or "")
    if prompt.strip():
        return prompt[:2000]
    parts = [
        str(active.get(field) or "")
        for field in ("task_id", "title", "objective", "status")
    ]
    return " ".join(part for part in parts if part).strip() or "repository task context"


def _doctor_trigger(payload: dict) -> object | None:
    for field in (
        "skillDoctorTrigger", "skill_doctor_trigger",
        "improvementTrigger", "improvement_trigger",
    ):
        value = payload.get(field)
        if value not in (None, False, "", [], {}):
            return value
    return None


def _verified_memory_candidate(root: Path, active: dict, payload: dict, ended_at: str) -> dict | None:
    raw = payload.get("verifiedMemoryCandidate", payload.get("verified_memory_candidate"))
    if not isinstance(raw, dict) or str(active.get("status")) != "CLOSED":
        return None
    task_id = str(active.get("task_id") or "")
    qa_report = raw.get("qaReport", raw.get("qa_report"))
    if not task_id or not isinstance(qa_report, str) or not qa_report.strip():
        return None
    try:
        report_path = (root / qa_report).resolve()
        report_path.relative_to(root.resolve())
        if not report_path.is_file():
            return None
        report = json.loads(report_path.read_text(encoding="utf-8"))
        evidence = report.get("evidence")
        if (
            report.get("task_id") != task_id
            or report.get("role") != "workers_qa"
            or str(report.get("overall_verdict", "")).upper() != "PASS"
            or not isinstance(evidence, list)
            or not evidence
        ):
            return None
        resolved_evidence = []
        for item in evidence:
            if not isinstance(item, str) or not item.strip():
                return None
            path = (root / item).resolve()
            path.relative_to(root.resolve())
            if not path.is_file():
                return None
            resolved_evidence.append(item)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return None
    source_role = raw.get("sourceRole", raw.get("source_role"))
    memory_type = str(raw.get("memoryType", raw.get("memory_type", "PROCEDURAL"))).upper()
    if (
        not isinstance(source_role, str)
        or source_role not in {"workers_planner", "workers_pm", "workers_executor"}
        or memory_type not in {"EPISODIC", "SEMANTIC", "PROCEDURAL", "DECISION"}
    ):
        return None
    candidate = {
        "id": raw.get("id") or f"{task_id}-verified-experience",
        "title": str(raw.get("title") or "Verified working experience")[:160],
        "summary": str(raw.get("summary") or "QA-verified local success.")[:500],
        "content": str(raw.get("content") or "")[:8000],
        "source": "SessionEnd",
        "sourceTaskId": task_id,
        "sourceRole": source_role,
        "sourceType": "verified_execution",
        "closedStatus": "CLOSED",
        "memoryType": memory_type,
        "scope": "repository",
        "confidence": 0.9,
        "evidence": resolved_evidence,
        "autoActivateVerifiedExperience": True,
        "qaReport": qa_report,
        "endedAt": ended_at,
    }
    return candidate if candidate["content"].strip() and _persistence_guard(candidate) else None


def _continuation_count(payload: dict, event: str) -> int:
    if "continuationCount" in payload:
        return max(0, int(payload["continuationCount"]))
    active = bool(payload.get("stop_hook_active") or payload.get("stopHookActive"))
    try:
        root = find_git_root(Path.cwd())
        store = StateStore(root / ".workers-group/runtime/hook-continuations.json")
        state = store.read_state()
        key = f"{payload.get('session_id') or payload.get('sessionId') or 'session'}:{event}"
        count = int(state.get(key, 0)) + 1 if active else 0
        state[key] = count
        store.write_state(state)
        return count
    except (OSError, ValueError, TypeError):
        return 1 if active else 0


def _has_report_gaps(payload: dict, state: dict) -> bool:
    explicit = payload.get("hasGaps", payload.get("has_gaps"))
    if explicit:
        return True
    for field in (
        "failedTests", "failed_tests", "missingEvidence", "missing_evidence",
        "reportGaps", "report_gaps", "blockers", "inProgress", "needsRework", "qaFailed",
    ):
        if payload.get(field):
            return True
    report = payload.get("report")
    if isinstance(report, dict):
        status = report.get("status")
        if status in {"EVIDENCE_REVIEW", "BOSS_REVIEW", "CLOSED"} and not report.get("evidence"):
            return True
        verdict = report.get("overall_verdict", report.get("verdict"))
        if report.get("role") == "workers_qa" and verdict not in {
            "PASS", "FAIL", "PARTIAL", "NOT_VERIFIED", "BLOCKED",
        }:
            return True
    return (
        _state_has_gaps(state)
        or bool(payload.get("stop_hook_active") or payload.get("stopHookActive"))
    )


def dispatch(payload: dict, hook_id: str | None = None, event: str | None = None,
             display_name: str | None = None) -> dict:
    event = event or payload.get("hook_event_name") or payload.get("event")
    if event not in DISPLAY:
        raise ValueError(f"unsupported hook event: {event!r}")
    status = display_name or DISPLAY[event]
    response = {
        "statusMessage": status,
        "commandWindows": ["py", "-3"],
        "hookSpecificOutput": {"hookEventName": event},
    }
    if hook_id:
        response["hookId"] = hook_id
    root = _repo_root()
    active = _active_task(root)

    if event == "SessionStart":
        role = str(payload.get("role") or "workers_boss")
        response["role"] = role
        safe_active = _safe_task(active)
        retrieval: dict = {
            "task_id": str(active.get("task_id") or ""),
            "role": role,
            "items": [],
        }
        if root:
            try:
                store = MemoryStore(_runtime(root) / "memory.sqlite3")
                response["memoryIntegrity"] = store.integrity()
                queue = _process_pending_memories(root, store)
                response["pendingMemoryProcessed"] = queue["processed"]
                response["pendingMemoryRemaining"] = queue["remaining"]
                if queue["errors"]:
                    response["pendingMemoryErrors"] = queue["errors"]
                retrieval = _memory_retrieval(
                    root,
                    _retrieval_query(payload, active),
                    str(active.get("task_id") or ""),
                    role,
                )
                response["memoryRetrieval"] = retrieval
            except (OSError, ValueError, RuntimeError, TimeoutError):
                response["persistenceError"] = True
                response.setdefault("memoryIntegrity", {"ok": False, "result": "unavailable"})
                response.setdefault("pendingMemoryProcessed", 0)
                response.setdefault("memoryRetrieval", retrieval)
        context = {
            "role": role,
            "active_task": safe_active,
            "memory_retrieval": retrieval,
        }
        response["hookSpecificOutput"]["additionalContext"] = json.dumps(context, ensure_ascii=False, separators=(",", ":"))[:4096]
        response["stateLoaded"] = bool(active)
        response["activeTask"] = safe_active
    elif event == "UserPromptSubmit":
        prompt = str(payload.get("prompt") or "")
        started = bool(GOVERNANCE_TRIGGER.search(prompt))
        response["governanceStarted"] = started
        if started:
            response["roles"] = ["workers_boss", "workers_planner", "workers_pm", "workers_executor", "workers_qa"]
            if root:
                try:
                    charter = create_task(
                        " ".join(prompt.split())[:120] or "Workers Group task",
                        prompt,
                    )
                    StateStore(
                        root / ".workers-group" / "state"
                        / f"{charter['task_id']}.task-charter.json"
                    ).write_state(charter)
                    StateStore(_runtime(root) / "active-task.json").write_state(charter)
                    active = charter
                    response["taskCharterRegistered"] = True
                    response["taskId"] = charter["task_id"]
                    retrieval = _memory_retrieval(
                        root, prompt, charter["task_id"], "workers_boss",
                    )
                    response["memoryRetrieval"] = retrieval
                    response["hookSpecificOutput"]["additionalContext"] = json.dumps(
                        {
                            "instruction": "Start planning from the registered Task Charter.",
                            "task_id": charter["task_id"],
                            "memory_retrieval": retrieval,
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )[:4096]
                except (OSError, ValueError, RuntimeError, TimeoutError):
                    response["taskCharterRegistered"] = False
                    response["persistenceError"] = True
            else:
                response["taskCharterRegistered"] = False
                response["hookSpecificOutput"]["additionalContext"] = "Start Task Charter before delegation."
    elif event == "SubagentStart":
        role = str(payload.get("agent_type") or payload.get("agentType") or payload.get("role") or "")
        retrieval: dict = {
            "task_id": str(active.get("task_id") or ""),
            "role": role,
            "items": [],
        }
        if root:
            try:
                retrieval = _memory_retrieval(
                    root,
                    _retrieval_query(payload, active),
                    str(active.get("task_id") or ""),
                    role,
                )
                response["memoryRetrieval"] = retrieval
            except (OSError, ValueError, RuntimeError, TimeoutError):
                response["persistenceError"] = True
        context = {
            "role": role,
            "role_contract": ROLE_CONTRACTS.get(role, "Follow the assigned work item and evidence contract."),
            "active_task": _safe_task(active),
            "memory_retrieval": retrieval,
        }
        response["hookSpecificOutput"]["additionalContext"] = json.dumps(context, ensure_ascii=False, separators=(",", ":"))[:4096]
        response["roleInjected"] = bool(role)
    elif event in {"PreToolUse", "PermissionRequest"}:
        reason = _pre_tool_risk(payload, root)
        if reason:
            if event == "PreToolUse":
                response["hookSpecificOutput"]["permissionDecision"] = "deny"
                response["hookSpecificOutput"]["permissionDecisionReason"] = reason
            else:
                response["hookSpecificOutput"]["decision"] = {
                    "behavior": "deny",
                    "message": reason,
                }
    elif event == "PostToolUse":
        try:
            response["evidenceRecorded"] = bool(root and _record_evidence(root, payload, active))
        except (OSError, ValueError, TimeoutError):
            response["evidenceRecorded"] = False
            response["persistenceError"] = True
    elif event == "PreCompact":
        if root:
            try:
                snapshot = _safe_task(active)
                snapshot["saved_at"] = _now()
                StateStore(_runtime(root) / "compact-snapshot.json").write_state(snapshot)
                response["stateSaved"] = True
            except (OSError, ValueError):
                response["stateSaved"] = False
                response["persistenceError"] = True
        else:
            response["stateSaved"] = False
    elif event == "PostCompact":
        try:
            snapshot = _read_object(_runtime(root) / "compact-snapshot.json") if root else {}
        except (OSError, json.JSONDecodeError, ValueError):
            snapshot = {}
            response["persistenceError"] = True
        response["stateRestored"] = bool(snapshot)
    elif event in {"SubagentStop", "Stop"}:
        count = _continuation_count(payload, event)
        try:
            report_errors = _completion_report_gaps(payload, active, root, event)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            report_errors = [f"report validation failed: {type(exc).__name__}"]
        has_gaps = bool(report_errors) or _has_report_gaps(payload, active)
        if report_errors:
            response["reportValidationErrors"] = report_errors[:100]
        response["continue"] = has_gaps and count < 2
        response["hasGaps"] = has_gaps
        if has_gaps and count < 2:
            response["decision"] = "block"
            response["reason"] = "Completion gaps remain; continue with the reported missing evidence or work."
        if has_gaps and count >= 2:
            response["outcomeRequired"] = ["PARTIAL", "BLOCKED", "FAILED"]
            response["reason"] = "Continuation limit reached; Boss must report remaining gaps."
    elif event == "SessionEnd":
        ended_at = _now()
        session_id = str(_sanitize(str(payload.get("session_id") or payload.get("sessionId") or "UNKNOWN")))[:128]
        task_id = _sanitize(active.get("task_id")) if active.get("task_id") else None
        task_status = _sanitize(active.get("status")) if active.get("status") else None
        summary = {
            "session_id": session_id,
            "ended_at": ended_at,
            "task_id": task_id,
            "status": task_status,
            "raw_transcript_retained": False,
        }
        if root:
            try:
                StateStore(_runtime(root) / "session-summary.json").write_state(summary)
                if active:
                    active["last_session_ended_at"] = ended_at
                    active["updated_at"] = ended_at
                    StateStore(_runtime(root) / "active-task.json").write_state(active)
                    response["activeTaskUpdated"] = True
                trigger = _doctor_trigger(payload)
                if task_id and trigger is not None:
                    safe_trigger = _sanitize(trigger)
                    candidate = {
                        "title": "Skill Doctor trigger candidate",
                        "summary": "A bounded lifecycle trigger requires Boss or QA review.",
                        "source": "SessionEnd",
                        "sourceTaskId": task_id,
                        "sourceRole": "workers_boss",
                        "memoryType": "SKILL_EVOLUTION",
                        "scope": "repository",
                        "confidence": 0.5,
                        "content": json.dumps(
                            {"trigger": safe_trigger, "ended_at": ended_at},
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    }
                    if _persistence_guard(candidate):
                        _append_jsonl(_runtime(root) / "pending-memory-queue.jsonl", candidate)
                        response["memoryCandidateQueued"] = True
                verified = _verified_memory_candidate(root, active, payload, ended_at)
                if verified is not None:
                    _append_jsonl(_runtime(root) / "pending-memory-queue.jsonl", verified)
                    response["verifiedMemoryQueued"] = True
            except (OSError, ValueError, TimeoutError):
                response["persistenceError"] = True
        response["summary"] = "Session metadata saved; raw transcript was not retained."
    return response


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hook-id")
    parser.add_argument("--event")
    parser.add_argument("--display-name")
    args = parser.parse_args(argv)
    try:
        raw = sys.stdin.read(MAX_STDIN_BYTES + 1)
        if len(raw.encode("utf-8")) > MAX_STDIN_BYTES:
            raise ValueError("stdin JSON exceeds size limit")
        payload = json.loads(raw or "{}")
        if not isinstance(payload, dict):
            raise ValueError("stdin JSON must be an object")
        result = dispatch(payload, args.hook_id, args.event, args.display_name)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        print(f"workers-group hook error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
