#!/usr/bin/env python3
"""Apply only structured, allowlisted LOW-risk Skill improvements."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tomllib
import uuid
from datetime import UTC, datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from memory_guard import redact_and_validate
from memory_store import atomic_write_text


LOW_OPERATIONS = {
    "update_status_message", "retrieval_weights", "test_fixture", "diagnostics",
    "path_fix", "optional_schema_field", "text_clarification",
}
HIGH_OPERATIONS = {
    "change_qa_policy", "change_evidence_policy", "change_security_policy",
    "change_sandbox", "change_network_policy", "change_deletion_policy",
    "change_command_chain", "change_hook_policy", "change_self_improvement_policy",
}
FORBIDDEN_FIELDS = {"patch", "diff", "command", "shell", "code", "script"}
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
PROPOSAL_ID = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,126}[A-Za-z0-9_-])?$")
WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}
WEIGHT_FIELDS = {
    "relevance_weight", "scope_weight", "confidence_weight", "authority_weight",
    "recency_weight", "success_weight", "conflict_penalty", "staleness_penalty",
    "harmful_history_penalty",
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _semver(value: str) -> tuple[int, int, int]:
    match = SEMVER.fullmatch(value or "")
    if not match:
        raise ValueError("version must use MAJOR.MINOR.PATCH")
    return tuple(map(int, match.groups()))


class SkillDoctor:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.state = self.root / ".workers-group" / "self-improvement"
        self.proposals = self.state / "proposals"
        self.approved = self.state / "approved"
        self.rejected = self.state / "rejected"
        self.backups = self.state / "backups"
        self.version_file = self.state / "VERSION"
        self.changelog_file = self.state / "CHANGELOG.md"

    def assess(self, proposal: dict) -> dict:
        if not isinstance(proposal, dict):
            return {"allowed": False, "status": "REJECTED", "reason": "proposal must be an object"}
        operation = str(proposal.get("operation", ""))
        risk = str(proposal.get("risk", "")).upper()
        if FORBIDDEN_FIELDS & proposal.keys():
            return {"allowed": False, "status": "REJECTED", "reason": "arbitrary code, patch, and shell fields are forbidden"}
        if operation in HIGH_OPERATIONS or risk != "LOW":
            return {
                "allowed": False,
                "status": "AWAITING_HUMAN_APPROVAL" if operation in HIGH_OPERATIONS or risk in {"MEDIUM", "HIGH"} else "REJECTED",
                "reason": "only allowlisted LOW-risk operations may be automatic",
            }
        if operation not in LOW_OPERATIONS:
            return {"allowed": False, "status": "REJECTED", "reason": "operation is not allowlisted"}
        return {"allowed": True, "status": "LOW_RISK_APPROVED", "reason": "structured LOW-risk operation"}

    def _guard(self, proposal: dict) -> tuple[dict | None, str | None]:
        rendered = json.dumps(proposal, ensure_ascii=False, sort_keys=True)
        guard = redact_and_validate(rendered)
        if not guard["accepted"]:
            return None, "proposal contains secret or unnecessary PII"
        return json.loads(guard["redacted"]), None

    def _fingerprint(self, proposal: dict) -> str:
        if proposal.get("fingerprint"):
            payload = str(proposal["fingerprint"]).encode("utf-8")
        else:
            payload = json.dumps(proposal, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return _sha(payload)

    def _record_path(self, folder: Path, fingerprint: str) -> Path:
        return folder / f"{fingerprint}.json"

    def _seen(self, fingerprint: str) -> bool:
        return self._record_path(self.approved, fingerprint).exists() or self._record_path(self.rejected, fingerprint).exists()

    def _write_json(self, path: Path, value: dict) -> None:
        rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        if not redact_and_validate(rendered)["accepted"]:
            raise ValueError("refusing to persist unsafe proposal data")
        atomic_write_text(path, rendered)

    def propose(self, proposal: dict) -> dict:
        safe, error = self._guard(proposal)
        if error:
            return {"proposed": False, "status": "REJECTED", "reason": error}
        try:
            proposal_id = self._proposal_id(safe)
        except ValueError as exc:
            return {"proposed": False, "status": "REJECTED", "reason": str(exc)}
        assessment = self.assess(safe)
        fingerprint = self._fingerprint(safe)
        record = {
            **safe, "proposalId": proposal_id, "fingerprint": fingerprint,
            "status": "PROPOSED" if assessment["allowed"] else assessment["status"],
            "createdAt": datetime.now(UTC).isoformat(),
        }
        path = self.proposals / f"{proposal_id}.json"
        try:
            self._write_json(path, record)
        except Exception:
            return {
                "proposed": False,
                "allowed": False,
                "status": "REJECTED",
                "reason": "initial proposal persistence failed safety validation",
                "fingerprint": fingerprint,
            }
        return {
            "proposed": True, "allowed": assessment["allowed"], "status": record["status"],
            "proposalPath": str(path), "fingerprint": fingerprint,
        }

    def simulate(self, proposal: dict) -> dict:
        safe, error = self._guard(proposal)
        if error:
            return {"simulated": False, "status": "REJECTED", "reason": error}
        try:
            self._proposal_id(safe)
        except ValueError as exc:
            return {"simulated": False, "status": "REJECTED", "reason": str(exc)}
        assessment = self.assess(safe)
        try:
            target = str(self._target(safe)) if safe.get("target") else None
            if target:
                self._render_change(safe, Path(target).read_text(encoding="utf-8"))
        except Exception as exc:
            return {"simulated": False, "status": "REJECTED", "reason": str(exc)}
        return {
            "simulated": assessment["allowed"], "status": assessment["status"],
            "fingerprint": self._fingerprint(safe), "target": target,
        }

    def apply(self, proposal: dict) -> dict:
        safe, error = self._guard(proposal)
        if error:
            return {"applied": False, "status": "REJECTED", "reason": error}
        fingerprint = self._fingerprint(safe)
        if self._seen(fingerprint):
            return {"applied": False, "status": "DUPLICATE_REFUSED", "fingerprint": fingerprint}

        # Fixed apply order: proposal -> baseline -> risk classification -> backup
        # -> expected hash -> isolated render -> test/QA/Boss gates -> atomic apply.
        try:
            proposal_id = self._proposal_id(safe)
        except ValueError as exc:
            return {"applied": False, "status": "REJECTED", "reason": str(exc), "fingerprint": fingerprint}
        try:
            self._write_json(self.proposals / f"{proposal_id}.json", {
                **safe, "proposalId": proposal_id, "fingerprint": fingerprint,
                "status": "PROPOSED", "createdAt": datetime.now(UTC).isoformat(),
            })
        except Exception:
            return {
                "applied": False,
                "status": "REJECTED",
                "reason": "initial proposal persistence failed safety validation",
                "fingerprint": fingerprint,
            }
        baseline_valid = safe.get("failingTest") is True
        assessment = self.assess(safe)
        if not assessment["allowed"]:
            if assessment["status"] == "REJECTED":
                self._record_rejected(fingerprint, safe, assessment["reason"])
            return {"applied": False, **assessment, "fingerprint": fingerprint}
        if not baseline_valid:
            reason = "baseline failing test is required"
            self._record_rejected(fingerprint, safe, reason)
            return {"applied": False, "status": "REJECTED", "reason": reason, "fingerprint": fingerprint}

        target: Path | None = None
        patched: str | None = None
        backup_manifest: Path | None = None
        backup_manifest_hash: str | None = None
        try:
            if not safe.get("target"):
                raise ValueError("apply requires an operation target")
            target = self._target(safe)
            original_bytes = target.read_bytes()
            original = original_bytes.decode("utf-8")

            backup_manifest = self._create_backup(fingerprint, target, safe)
            backup_manifest_hash = _sha(backup_manifest.read_bytes())
            expected = str(safe.get("expectedSha256", "")).lower()
            if not expected or _sha(original_bytes) != expected:
                raise ValueError("expectedSha256 is required and must match target")
            patched = self._render_change(safe, original)
            if patched == original:
                raise ValueError("structured operation made no change")

            reason = self._validate_evidence(safe, require_files=True)
            if reason:
                raise ValueError(reason)
            atomic_write_text(target, patched)
            self._write_version_and_changelog(safe, fingerprint)
            record = {
                "fingerprint": fingerprint, "proposal": safe, "status": "APPLIED",
                "backupPath": str(backup_manifest),
                "backupManifestSha256": backup_manifest_hash,
                "isolatedSha256": _sha(patched.encode("utf-8")) if patched is not None else None,
                "appliedAt": datetime.now(UTC).isoformat(),
            }
            invariant_errors = self._internal_invariants(target, patched, safe)
            if invariant_errors:
                raise ValueError(f"internal invariant failure: {'; '.join(invariant_errors)}")
            self._write_json(self._record_path(self.approved, fingerprint), record)
            return {
                "applied": True, "status": "APPLIED", "fingerprint": fingerprint,
                "backupPath": str(backup_manifest), "version": safe["version"],
            }
        except Exception as exc:
            rollback_result = None
            if backup_manifest is not None:
                rollback_result = self._restore_unapproved_backup(
                    backup_manifest, fingerprint, safe, backup_manifest_hash,
                )
            self._record_rejected(fingerprint, safe, str(exc))
            return {
                "applied": False,
                "status": (
                    "ROLLED_BACK" if rollback_result and rollback_result["rolledBack"]
                    else "ROLLBACK_FAILED" if backup_manifest is not None
                    else "REJECTED"
                ),
                "reason": str(exc),
                "fingerprint": fingerprint,
                "rollback": rollback_result,
            }

    def _validate_evidence(self, proposal: dict, *, require_files: bool) -> str | None:
        if proposal.get("fullTestsPassed") is not True:
            return "fullTestsPassed=true is required"
        if (
            not isinstance(proposal.get("testEvidence"), list)
            or not proposal["testEvidence"]
            or not all(isinstance(item, str) and item.strip() for item in proposal["testEvidence"])
        ):
            return "non-empty testEvidence is required"
        if (
            not isinstance(proposal.get("qaEvidence"), list)
            or not proposal["qaEvidence"]
            or not all(isinstance(item, str) and item.strip() for item in proposal["qaEvidence"])
        ):
            return "non-empty qaEvidence is required"
        if str(proposal.get("qaVerdict", "")).upper() != "PASS":
            return "independent QA PASS is required"
        if str(proposal.get("bossReview", "")).upper() not in {"PASS", "APPROVED"}:
            return "Boss review is required"
        if require_files:
            for field in ("testEvidence", "qaEvidence"):
                try:
                    for path in proposal[field]:
                        self._repo_file(path, f"{field} entry")
                except (OSError, ValueError, TypeError) as exc:
                    return str(exc)
            for field in ("bossEvidence", "bossReviewEvidence"):
                if field in proposal:
                    values = proposal[field]
                    if not isinstance(values, list) or not values:
                        return f"non-empty {field} is required when provided"
                    try:
                        for path in values:
                            self._repo_file(path, f"{field} entry")
                    except (OSError, ValueError, TypeError) as exc:
                        return str(exc)
        try:
            requested = _semver(str(proposal.get("version", "")))
            current = _semver(self.version_file.read_text(encoding="utf-8").strip()) if self.version_file.exists() else (0, 0, 0)
        except ValueError as exc:
            return str(exc)
        if requested <= current:
            return "version must increase"
        if not isinstance(proposal.get("changelog"), str) or not proposal["changelog"].strip():
            return "changelog is required"
        return None

    def _target(self, proposal: dict) -> Path:
        target = self._repo_file(proposal["target"], "target")
        relative = target.relative_to(self.root).as_posix()
        operation = str(proposal.get("operation", ""))
        if not self._operation_target_allowed(operation, relative):
            raise ValueError(f"{operation} may not modify target class: {relative}")
        return target

    def _proposal_id(self, proposal: dict) -> str:
        identifier = str(proposal.get("proposalId") or proposal.get("proposal_id") or self._fingerprint(proposal)[:16])
        if (
            not PROPOSAL_ID.fullmatch(identifier)
            or identifier.split(".", 1)[0].upper() in WINDOWS_RESERVED
        ):
            raise ValueError("proposalId contains an unsafe filename")
        return identifier

    def _repo_file(self, value: object, label: str) -> Path:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{label} must be a non-empty repository-relative path")
        raw = Path(value)
        if raw.is_absolute() or ".." in raw.parts:
            raise ValueError(f"{label} must not escape the repository")
        try:
            resolved = (self.root / raw).resolve(strict=True)
        except OSError as exc:
            raise ValueError(f"{label} must reference an existing readable file") from exc
        if self.root not in resolved.parents or not resolved.is_file():
            raise ValueError(f"{label} must reference a regular file inside the repository")
        try:
            with resolved.open("rb") as stream:
                stream.read(1)
        except OSError as exc:
            raise ValueError(f"{label} must reference an existing readable file") from exc
        return resolved

    @staticmethod
    def _operation_target_allowed(operation: str, relative: str) -> bool:
        skill_roots = (
            ".codex/skills/orchestrating-workers-group/",
            ".agents/skills/orchestrating-workers-group/",
        )
        fixtures = tuple(prefix + "tests/" for prefix in skill_roots)
        schemas = ".workers-group/schemas/"
        reports = ".workers-group/reports/"
        allowed_references = {
            prefix + name for prefix in skill_roots
            for name in ("references/hooks-reference.md", "references/meeting-protocol.md")
        }
        if operation == "update_status_message":
            return relative == ".codex/hooks.json"
        if operation == "retrieval_weights":
            return relative == ".workers-group/config/retrieval-policy.toml"
        if operation in {"test_fixture", "path_fix"}:
            return (
                relative.startswith(fixtures)
                and ("/fixtures/" in relative or "/scenarios/" in relative)
            )
        if operation == "diagnostics":
            return relative.startswith(reports) and Path(relative).suffix in {".json", ".md", ".txt", ".log"}
        if operation == "optional_schema_field":
            return relative.startswith(schemas) and relative.endswith(".schema.json")
        if operation == "text_clarification":
            return relative in allowed_references
        return False

    def _internal_invariants(self, target: Path | None, patched: str | None, proposal: dict) -> list[str]:
        errors: list[str] = []
        if self.version_file.read_text(encoding="utf-8").strip() != proposal["version"]:
            errors.append("VERSION was not updated")
        changelog = self.changelog_file.read_text(encoding="utf-8")
        if proposal["version"] not in changelog or proposal["changelog"].strip() not in changelog:
            errors.append("CHANGELOG entry is incomplete")
        if target is not None and patched is not None:
            try:
                actual = target.read_bytes().decode("utf-8")
                if actual != patched:
                    errors.append("target content differs from isolated render")
                if target.name.endswith(".json"):
                    parsed = json.loads(actual)
                    if proposal["operation"] == "update_status_message":
                        statuses = [
                            node["statusMessage"] for node in self._walk_json(parsed)
                            if isinstance(node, dict) and "statusMessage" in node
                        ]
                        if not statuses or not all(
                            isinstance(value, str) and value.startswith("打工人集團｜")
                            for value in statuses
                        ):
                            errors.append("Hook statusMessage invariant failed")
                elif target.suffix == ".toml":
                    tomllib.loads(actual)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
                errors.append(f"target parse invariant failed: {exc}")

        global_skill = self.root / ".codex/skills/orchestrating-workers-group/SKILL.md"
        legacy_skill = self.root / ".agents/skills/orchestrating-workers-group/SKILL.md"
        skill = global_skill if global_skill.is_file() else legacy_skill
        hooks_path = self.root / ".codex/hooks.json"
        if skill.is_file() and hooks_path.is_file():
            try:
                skill_text = skill.read_text(encoding="utf-8")
                if not skill_text.startswith("---\n") or "name: orchestrating-workers-group" not in skill_text:
                    errors.append("Skill discovery metadata invariant failed")
                hooks = json.loads(hooks_path.read_text(encoding="utf-8"))
                expected_events = {
                    "SessionStart", "SessionEnd", "UserPromptSubmit", "PreToolUse",
                    "PostToolUse", "PreCompact", "PostCompact", "SubagentStart",
                    "SubagentStop", "Stop", "PermissionRequest",
                }
                if set(hooks.get("hooks", {})) != expected_events:
                    errors.append("Hook event set invariant failed")
                wg_handlers = [
                    node for node in self._walk_json(hooks)
                    if isinstance(node, dict) and "--hook-id WG-HOOK-" in str(node.get("commandWindows", ""))
                ]
                if len(wg_handlers) != 11:
                    errors.append("Workers Group Hook handler invariant failed")
                for node in wg_handlers:
                    if "name" in node:
                        errors.append("forbidden Hook handler name invariant failed")
                    if not str(node.get("statusMessage", "")).startswith("打工人集團｜"):
                        errors.append("Hook statusMessage prefix invariant failed")
                expected_agents = {
                    "workers_boss", "workers_planner", "workers_pm",
                    "workers_executor", "workers_qa",
                }
                agent_dir = self.root / ".codex/agents"
                parsed_agents = {
                    path.stem for path in agent_dir.glob("*.toml")
                    if tomllib.loads(path.read_text(encoding="utf-8"))
                }
                if parsed_agents != expected_agents:
                    errors.append("custom agent set invariant failed")
                for folder, suffix in (
                    (self.root / ".workers-group/schemas", "*.schema.json"),
                    (self.root / ".workers-group/templates", "*.template.json"),
                ):
                    for path in folder.glob(suffix):
                        json.loads(path.read_text(encoding="utf-8"))
                config = self.root / ".codex/config.toml"
                if config.is_file():
                    tomllib.loads(config.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
                errors.append(f"Repository invariant parse failed: {exc}")
        return errors

    @staticmethod
    def _walk_json(value: object):
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from SkillDoctor._walk_json(child)
        elif isinstance(value, list):
            for child in value:
                yield from SkillDoctor._walk_json(child)

    def _render_change(self, proposal: dict, original: str) -> str:
        operation = proposal["operation"]
        if operation == "update_status_message":
            old, new = proposal.get("oldValue"), proposal.get("newValue")
            if not isinstance(old, str) or not isinstance(new, str) or not new.startswith("打工人集團｜"):
                raise ValueError("statusMessage change requires oldValue and prefixed newValue")
            data = json.loads(original)
            changed = self._replace_json_status(data, old, new)
            if changed != 1:
                raise ValueError("exactly one matching statusMessage is required")
            return json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        if operation == "retrieval_weights":
            field, value = proposal.get("field"), proposal.get("value")
            if (
                field not in WEIGHT_FIELDS
                or not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not 0 <= float(value) <= 1
            ):
                raise ValueError("retrieval weight must be an allowlisted numeric field between 0 and 1")
            horizontal_space = r"[^\S\r\n]"
            pattern = re.compile(
                rf"(?m)^({re.escape(field)}{horizontal_space}*={horizontal_space}*)"
                rf"[-+]?\d+(?:\.\d+)?({horizontal_space}*)(\r?)$",
            )
            rendered, count = pattern.subn(
                rf"\g<1>{float(value):g}\g<2>\g<3>",
                original,
            )
            if count != 1:
                raise ValueError("retrieval weight field was not found exactly once")
            return rendered
        if operation in {"text_clarification", "test_fixture", "path_fix"}:
            old, new = proposal.get("oldValue"), proposal.get("newValue")
            if not isinstance(old, str) or not isinstance(new, str) or not old or original.count(old) != 1:
                raise ValueError("operation requires one exact oldValue match and a string newValue")
            return original.replace(old, new, 1)
        if operation == "optional_schema_field":
            field, schema = proposal.get("field"), proposal.get("schema")
            if not isinstance(field, str) or not field or not isinstance(schema, dict):
                raise ValueError("optional schema field and schema object are required")
            data = json.loads(original)
            properties = data.setdefault("properties", {})
            if field in properties or field in data.get("required", []):
                raise ValueError("field must be new and optional")
            properties[field] = schema
            return json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        if operation == "diagnostics":
            data = json.loads(original)
            field = proposal.get("field")
            if not isinstance(field, str) or not field.startswith("diagnostic_"):
                raise ValueError("diagnostics field must start with diagnostic_")
            data[field] = proposal.get("value")
            return json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        raise ValueError("operation has no structured file transformer")

    def _replace_json_status(self, value: object, old: str, new: str) -> int:
        changed = 0
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "statusMessage" and item == old:
                    value[key], changed = new, changed + 1
                else:
                    changed += self._replace_json_status(item, old, new)
        elif isinstance(value, list):
            changed += sum(self._replace_json_status(item, old, new) for item in value)
        return changed

    def _create_backup(self, fingerprint: str, target: Path | None, proposal: dict) -> Path:
        folder = self.backups / f"{fingerprint}-{uuid.uuid4().hex[:8]}"
        folder.mkdir(parents=True, exist_ok=False)
        entries = []
        for index, path in enumerate(filter(None, (target, self.version_file, self.changelog_file))):
            relative = path.relative_to(self.root).as_posix()
            exists = path.exists()
            backup_file = folder / f"{index}.bin"
            if exists:
                shutil.copy2(path, backup_file)
                digest = _sha(backup_file.read_bytes())
            else:
                digest = ""
            entries.append({"path": relative, "existed": exists, "backup": backup_file.name, "sha256": digest})
        manifest = folder / "manifest.json"
        self._write_json(manifest, {
            "fingerprint": fingerprint,
            "operation": proposal["operation"],
            "target": proposal.get("target"),
            "entries": entries,
            "rolledBack": False,
        })
        return manifest

    def rollback(self, backup_path: str | Path) -> dict:
        """Restore only a manifest bound to a real APPLIED approval record."""
        manifest = Path(backup_path).resolve()
        try:
            data = self._read_manifest(manifest)
            fingerprint = data["fingerprint"]
            approved = self._record_path(self.approved, fingerprint)
            approved_root = self.approved.resolve()
            if (
                self.root not in approved_root.parents
                or not approved.is_file()
                or approved_root not in approved.resolve().parents
            ):
                raise ValueError("rollback requires an approved fingerprint record")
            record = json.loads(approved.read_text(encoding="utf-8"))
            if record.get("status") != "APPLIED" or record.get("fingerprint") != fingerprint:
                raise ValueError("approved fingerprint binding mismatch")
            if Path(str(record.get("backupPath", ""))).resolve() != manifest:
                raise ValueError("approved backupPath binding mismatch")
            manifest_hash = record.get("backupManifestSha256")
            if not isinstance(manifest_hash, str) or _sha(manifest.read_bytes()) != manifest_hash:
                raise ValueError("backup manifest authenticity check failed")
            proposal = record.get("proposal")
            if not isinstance(proposal, dict):
                raise ValueError("approved proposal binding is missing")
            self._restore_validated(manifest, data, fingerprint, proposal, manifest_hash)
            rolled_back_at = datetime.now(UTC).isoformat()
            data["rolledBack"] = True
            data["rolledBackAt"] = rolled_back_at
            self._write_json(manifest, data)
            record["status"] = "ROLLED_BACK"
            record["rolledBackAt"] = rolled_back_at
            self._write_json(approved, record)
            return {"rolledBack": True, "backupPath": str(manifest)}
        except Exception as exc:
            return {"rolledBack": False, "reason": str(exc), "backupPath": str(manifest)}

    def _restore_unapproved_backup(
        self,
        manifest: Path,
        fingerprint: str,
        proposal: dict,
        manifest_hash: str | None,
    ) -> dict:
        """Private apply-failure restore; caller supplies the in-flight bindings."""
        try:
            data = self._read_manifest(manifest)
            if not manifest_hash:
                raise ValueError("in-flight backup hash is missing")
            self._restore_validated(manifest, data, fingerprint, proposal, manifest_hash)
            data["rolledBack"] = True
            data["rolledBackAt"] = datetime.now(UTC).isoformat()
            self._write_json(manifest, data)
            return {"rolledBack": True, "backupPath": str(manifest)}
        except Exception as exc:
            return {"rolledBack": False, "reason": str(exc), "backupPath": str(manifest)}

    def _read_manifest(self, manifest: Path) -> dict:
        backup_root = self.backups.resolve()
        if (
            self.root not in backup_root.parents
            or manifest.name != "manifest.json"
            or not manifest.is_file()
            or backup_root not in manifest.parents
            or manifest.parent.parent != backup_root
        ):
            raise ValueError("backup manifest is outside the Skill Doctor backup area")
        data = json.loads(manifest.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("rolledBack") is not False:
            raise ValueError("backup manifest is invalid or already used")
        fingerprint = data.get("fingerprint")
        if not isinstance(fingerprint, str) or not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
            raise ValueError("backup fingerprint is invalid")
        if not isinstance(data.get("entries"), list) or not data["entries"]:
            raise ValueError("backup manifest entries are invalid")
        return data

    def _restore_validated(
        self,
        manifest: Path,
        data: dict,
        fingerprint: str,
        proposal: dict,
        manifest_hash: str,
    ) -> None:
        if data.get("fingerprint") != fingerprint or _sha(manifest.read_bytes()) != manifest_hash:
            raise ValueError("backup fingerprint or manifest hash mismatch")
        operation = proposal.get("operation")
        if data.get("operation") != operation or data.get("target") != proposal.get("target"):
            raise ValueError("backup proposal binding mismatch")

        allowed: set[Path] = {
            self.version_file.resolve(strict=False),
            self.changelog_file.resolve(strict=False),
        }
        if proposal.get("target"):
            target = self._target(proposal)
            allowed.add(target)

        actions: list[tuple[Path, bool, str | None]] = []
        seen: set[Path] = set()
        for entry in data["entries"]:
            if not isinstance(entry, dict):
                raise ValueError("backup entry must be an object")
            raw_path = entry.get("path")
            if not isinstance(raw_path, str) or not raw_path or Path(raw_path).is_absolute() or ".." in Path(raw_path).parts:
                raise ValueError("backup entry path is unsafe")
            target = (self.root / raw_path).resolve(strict=False)
            if self.root not in target.parents or target not in allowed or target in seen:
                raise ValueError("backup entry is outside the approved operation target")
            seen.add(target)

            backup_name = entry.get("backup")
            if not isinstance(backup_name, str) or not re.fullmatch(r"\d+\.bin", backup_name):
                raise ValueError("backup filename is unsafe")
            backup_file = (manifest.parent / backup_name).resolve(strict=False)
            if backup_file.parent != manifest.parent:
                raise ValueError("backup filename escapes its manifest directory")
            existed = entry.get("existed")
            if not isinstance(existed, bool):
                raise ValueError("backup existed flag is invalid")
            if existed:
                if not backup_file.is_file():
                    raise ValueError("backup payload is missing")
                payload = backup_file.read_bytes()
                if not isinstance(entry.get("sha256"), str) or _sha(payload) != entry["sha256"]:
                    raise ValueError("backup hash mismatch")
                try:
                    text = payload.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise ValueError("backup payload must be UTF-8 text") from exc
                actions.append((target, True, text))
            else:
                if backup_file.exists() or entry.get("sha256") != "":
                    raise ValueError("nonexistent backup entry contains unexpected payload")
                actions.append((target, False, None))
        if seen != allowed:
            raise ValueError("backup entries do not exactly match the approved restore set")

        for target, existed, text in actions:
            if existed:
                assert text is not None
                atomic_write_text(target, text)
            elif target.exists():
                target.unlink()

    def _write_version_and_changelog(self, proposal: dict, fingerprint: str) -> None:
        atomic_write_text(self.version_file, f"{proposal['version']}\n")
        existing = self.changelog_file.read_text(encoding="utf-8") if self.changelog_file.exists() else "# Skill Doctor CHANGELOG\n\n"
        line = (
            f"## {proposal['version']} - {datetime.now(UTC).date().isoformat()}\n\n"
            f"- {proposal['changelog'].strip()} (`{fingerprint[:12]}`, QA: PASS)\n"
        )
        if not redact_and_validate(line)["accepted"]:
            raise ValueError("unsafe changelog")
        atomic_write_text(self.changelog_file, existing.rstrip("\n") + "\n\n" + line)

    def _record_rejected(self, fingerprint: str, proposal: dict, reason: str) -> None:
        self._write_json(self._record_path(self.rejected, fingerprint), {
            "fingerprint": fingerprint, "proposal": proposal, "status": "REJECTED",
            "reason": reason, "rejectedAt": datetime.now(UTC).isoformat(),
        })


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("propose", "apply", "rollback", "simulate"))
    parser.add_argument("--proposal", required=True)
    parser.add_argument("--root", default=".")
    args = parser.parse_args(argv)
    try:
        doctor = SkillDoctor(args.root)
        if args.action == "rollback":
            result = doctor.rollback(args.proposal)
        else:
            proposal = json.loads(Path(args.proposal).read_text(encoding="utf-8"))
            result = getattr(doctor, args.action)(proposal)
        print(json.dumps(result, ensure_ascii=False))
        success = result.get("applied") or result.get("proposed") or result.get("simulated") or result.get("rolledBack")
        return 0 if success else 2
    except Exception as exc:
        print(json.dumps({"ok": False, "error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
