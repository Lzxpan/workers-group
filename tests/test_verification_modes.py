"""Focused regression tests for basic Boss verification and strict QA mode."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
from create_task import create_task  # noqa: E402
from validate_report import validate_basic_verification  # noqa: E402
from workers_group_paths import STATIC_ROOT  # noqa: E402
from workers_group_hook import verification_mode_for_prompt  # noqa: E402
sys.path.pop(0)


class VerificationModeTests(unittest.TestCase):
    @staticmethod
    def _run_hook(root: Path, payload: dict) -> dict:
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "workers_group_hook.py")],
            input=json.dumps(payload, ensure_ascii=False),
            text=True,
            encoding="utf-8",
            capture_output=True,
            cwd=root,
            timeout=10,
            env={**os.environ, "PYTHONUTF8": "1"},
        )
        if result.returncode != 0:
            raise AssertionError(result.stderr)
        return json.loads(result.stdout)

    @staticmethod
    def _role_report(task_id: str, evidence: list[str]) -> dict:
        return {
            "schema_version": "1.0",
            "task_id": task_id,
            "work_item_id": "WI-MODE",
            "role": "workers_boss",
            "agent_id": "workers_boss-mode-test",
            "status": "CLOSED",
            "summary": "Basic verification smoke report",
            "facts": ["Focused checks completed."],
            "assumptions": [],
            "inferences": [],
            "unverified_items": ["Browser and production runtime were not exercised."],
            "failed_results": [],
            "actions_taken": ["Reviewed the changed scope and recorded focused checks."],
            "commands_run": [{"command": "python -m unittest", "exit_code": 0}],
            "files_changed": ["artifact.txt"],
            "tests": [{"command": "python -m unittest", "passed": 1, "failed": 0, "skipped": 0}],
            "evidence": evidence,
            "blockers": [],
            "risks": [],
            "remaining_work": [],
            "memories_used": [],
            "memory_candidates": [],
            "confidence": 1.0,
            "timestamp": "2026-08-10T00:00:00+00:00",
        }

    @staticmethod
    def _completion_bundle(root: Path, *, mode: str) -> tuple[dict, dict]:
        task_id = "WG-MODE-SMOKE"
        (root / "artifact.txt").write_text("focused smoke passed\n", encoding="utf-8")
        criterion = {
            "id": "AC-1",
            "requirement": "The changed scope remains valid.",
            "validation_method": "Run focused smoke check.",
            "required_evidence": ["artifact.txt"],
            "owner": "workers_boss",
            "status": "PASS",
            "evidence": ["artifact.txt"],
            "verdict": "PASS",
        }
        (root / "acceptance.json").write_text(json.dumps(criterion), encoding="utf-8")
        verification = {
            "verdict": "PASS",
            "changed_scope_review": "PASS",
            "focused_checks": [{"name": "focused smoke", "verdict": "PASS"}],
            "evidence": ["artifact.txt"],
            "limitations": ["NOT VERIFIED: browser, hardware, provider and production runtime"],
        }
        state = {
            "task_id": task_id,
            "status": "CLOSED",
            "verification_mode": mode,
            "acceptance_criteria": [{"task_id": task_id, "path": "acceptance.json"}],
            "evidence": ["artifact.txt"],
            "failed_tests": [],
            "boss_reviewed": True,
            "scope_drift_checked": True,
            "limitations_disclosed": True,
            "skill_migration_complete": True,
            "self_improvement_verified": True,
            "boss_verification": verification,
            "boss_report": "boss-report.json",
        }
        (root / "boss-report.json").write_text(
            json.dumps(VerificationModeTests._role_report(task_id, ["artifact.txt"])),
            encoding="utf-8",
        )
        runtime = root / ".workers-group" / "runtime"
        runtime.mkdir(parents=True, exist_ok=True)
        (runtime / "active-task.json").write_text(json.dumps(state), encoding="utf-8")
        return state, {
            "event": "Stop",
            "report": VerificationModeTests._role_report(task_id, ["artifact.txt"]),
            "completionState": state,
            "continuationCount": 0,
        }

    def test_prompt_defaults_to_basic_and_explicit_deep_checks_select_strict(self):
        self.assertEqual("basic", verification_mode_for_prompt("請規劃並完成跨模組修改"))
        self.assertEqual(
            "strict",
            verification_mode_for_prompt("請做完整 QA，並執行 browser 實測"),
        )

    def test_create_task_persists_mode_specific_contract(self):
        basic = create_task("Basic task", "普通治理任務")
        strict = create_task("Strict task", "請做獨立 QA", verification_mode="strict")
        self.assertEqual("basic", basic["verification_mode"])
        self.assertIn("Boss verification", basic["constraints"][0])
        self.assertEqual("strict", strict["verification_mode"])
        self.assertIn("independent QA PASS", strict["constraints"][0])

    def test_basic_verification_requires_scope_checks_evidence_and_limitations(self):
        with tempfile.TemporaryDirectory(prefix="workers-group-basic-") as directory:
            root = Path(directory)
            evidence = root / "basic-check.txt"
            evidence.write_text("focused smoke passed\n", encoding="utf-8")
            valid = {
                "verdict": "PASS",
                "changed_scope_review": "PASS",
                "focused_checks": [{"name": "focused smoke", "verdict": "PASS"}],
                "evidence": ["basic-check.txt"],
                "limitations": ["NOT VERIFIED: browser and production runtime"],
            }
            self.assertTrue(validate_basic_verification(valid, repository_root=root)["valid"])
            invalid = dict(valid)
            invalid.pop("limitations")
            self.assertFalse(validate_basic_verification(invalid, repository_root=root)["valid"])

    def test_user_prompt_submit_dispatches_four_or_five_roles(self):
        with tempfile.TemporaryDirectory(prefix="workers-group-dispatch-") as directory:
            root = Path(directory)
            (root / ".git").mkdir()
            basic = self._run_hook(root, {
                "event": "UserPromptSubmit",
                "prompt": "$orchestrating-workers-group 請完成一般跨模組修改",
            })
            self.assertEqual("basic", basic["verificationMode"])
            self.assertEqual(
                {"workers_boss", "workers_planner", "workers_pm", "workers_executor"},
                set(basic["roles"]),
            )
            strict = self._run_hook(root, {
                "event": "UserPromptSubmit",
                "prompt": "$orchestrating-workers-group 請做獨立 QA",
            })
            self.assertEqual("strict", strict["verificationMode"])
            self.assertEqual(
                {"workers_boss", "workers_planner", "workers_pm", "workers_executor", "workers_qa"},
                set(strict["roles"]),
            )

    @unittest.skipUnless((STATIC_ROOT / "schemas").is_dir(), "requires installed static runtime")
    def test_basic_stop_does_not_require_qa_report_but_strict_stop_does(self):
        with tempfile.TemporaryDirectory(prefix="workers-group-stop-") as directory:
            root = Path(directory)
            (root / ".git").mkdir()
            _, basic_payload = self._completion_bundle(root, mode="basic")
            basic = self._run_hook(root, basic_payload)
            self.assertFalse(basic.get("hasGaps"), basic)
            self.assertNotIn("qa_report", json.dumps(basic, ensure_ascii=False))

            _, strict_payload = self._completion_bundle(root, mode="strict")
            strict = self._run_hook(root, strict_payload)
            self.assertEqual("block", strict.get("decision"), strict)
            self.assertTrue(any("qa_report" in error for error in strict.get("reportValidationErrors", [])))

    @unittest.skipUnless((STATIC_ROOT / "schemas").is_dir(), "requires installed static runtime")
    def test_transition_validator_accepts_basic_boss_review_and_rejects_strict_without_qa(self):
        import importlib.util
        from unittest import mock

        module_path = SCRIPTS / "validate_transition.py"
        spec = importlib.util.spec_from_file_location("validate_transition_mode_test", module_path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory(prefix="workers-group-transition-") as directory:
            root = Path(directory)
            evidence = root / "artifact.txt"
            evidence.write_text("focused smoke passed\n", encoding="utf-8")
            verification = {
                "verdict": "PASS",
                "changed_scope_review": "PASS",
                "focused_checks": [{"name": "focused smoke", "verdict": "PASS"}],
                "evidence": ["artifact.txt"],
                "limitations": ["NOT VERIFIED: production runtime"],
            }
            with mock.patch.object(module, "ROOT", root):
                self.assertTrue(module.validate_transition(
                    "EVIDENCE_REVIEW", "BOSS_REVIEW",
                    evidence=["artifact.txt"],
                    state={"verification_mode": "basic", "boss_verification": verification},
                ))
                with self.assertRaises(PermissionError):
                    module.validate_transition(
                        "EVIDENCE_REVIEW", "BOSS_REVIEW",
                        evidence=["artifact.txt"],
                        state={"verification_mode": "strict"},
                    )


if __name__ == "__main__":
    unittest.main()
