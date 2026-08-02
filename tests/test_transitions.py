import json
from pathlib import Path
from unittest import mock

from test_support import WorkersGroupTestCase


class TransitionTests(WorkersGroupTestCase):
    def test_invalid_transition_is_rejected(self):
        module = self.source_module("validate_transition.py")
        with self.assertRaises(ValueError):
            module.validate_transition("INTAKE", "CLOSED", qa_verdict="PASS", evidence=["x"])

    def test_closed_requires_pass_qa_and_readable_evidence(self):
        module = self.source_module("validate_transition.py")
        evidence = [str(Path(__file__).resolve())]
        with self.assertRaises((ValueError, PermissionError)):
            module.validate_transition(
                "BOSS_REVIEW", "CLOSED", qa_verdict="FAIL", evidence=evidence,
            )
        with self.assertRaises((ValueError, PermissionError)):
            module.validate_transition(
                "BOSS_REVIEW", "CLOSED", qa_verdict="PASS", evidence=[],
            )

    def test_human_waiver_must_be_structured_approved_and_have_readable_evidence(self):
        module = self.source_module("validate_transition.py")
        evidence = [str(Path(__file__).resolve())]

        with self.assertRaises((ValueError, PermissionError)):
            module.validate_transition(
                "QA", "BOSS_REVIEW",
                qa_verdict="FAIL", evidence=evidence, state={"human_waiver": True},
            )

        valid_waiver = {
            "human_approved": True,
            "unresolved_risks": ["QA verdict remains FAIL"],
            "evidence": evidence,
        }
        invalid_waivers = (
            {**valid_waiver, "human_approved": False},
            {**valid_waiver, "unresolved_risks": []},
            {**valid_waiver, "evidence": []},
            {**valid_waiver, "evidence": ["definitely-missing-waiver-evidence.txt"]},
        )
        for waiver in invalid_waivers:
            with self.subTest(waiver=waiver), self.assertRaises((ValueError, PermissionError)):
                module.validate_transition(
                    "QA", "BOSS_REVIEW",
                    qa_verdict="FAIL", evidence=evidence, state={"human_waiver": waiver},
                )

        with self.assertRaises((ValueError, PermissionError)):
            module.validate_transition(
                "QA", "BOSS_REVIEW",
                qa_verdict="FAIL", evidence=evidence, state={"human_waiver": valid_waiver},
            )

    def test_closed_requires_bound_valid_qa_boss_and_pass_acceptance_documents(self):
        module = self.source_module("validate_transition.py")
        flags = {
            "boss_reviewed": True,
            "all_acceptance_criteria_passed": True,
            "failures_disclosed": True,
            "memory_candidate_decision_recorded": True,
            "skill_changes_resolved": True,
        }
        evidence = [str(Path(__file__).resolve())]
        with self.subTest(case="truthy-flags-without-documents"):
            with self.assertRaises((ValueError, PermissionError)):
                module.validate_transition(
                    "BOSS_REVIEW", "CLOSED",
                    qa_verdict="PASS", evidence=evidence, state=flags,
                )

        invalid_cases = (
            {"qa_task_id": "WG-other-task"},
            {"boss_task_id": "WG-other-task"},
            {"acceptance_status": "FAIL", "acceptance_verdict": "FAIL"},
            {"acceptance_evidence": []},
            {"acceptance_evidence": ["missing-acceptance-evidence.txt"]},
        )
        for overrides in invalid_cases:
            with self.subTest(overrides=overrides), self.temp_dir() as directory:
                root = Path(directory)
                state, completion_evidence = self._completion_bundle(root, **overrides)
                with mock.patch.object(module, "ROOT", root):
                    with self.assertRaises((ValueError, PermissionError)):
                        module.validate_transition(
                            "BOSS_REVIEW", "CLOSED",
                            qa_verdict="PASS", evidence=[completion_evidence], state=state,
                        )

        with self.temp_dir() as directory:
            root = Path(directory)
            state, completion_evidence = self._completion_bundle(root)
            with mock.patch.object(module, "ROOT", root):
                self.assertTrue(module.validate_transition(
                    "BOSS_REVIEW", "CLOSED",
                    qa_verdict="PASS", evidence=[completion_evidence], state=state,
                ))

    @staticmethod
    def _completion_bundle(
        root, *, qa_task_id=None, boss_task_id=None,
        acceptance_status="PASS", acceptance_verdict="PASS",
        acceptance_evidence=None,
    ):
        task_id = "WG-done-document-red-control"
        evidence = root / "completion-evidence.txt"
        evidence.write_text("obvious fake completion evidence\n", encoding="utf-8")
        evidence_path = str(evidence)
        if acceptance_evidence is None:
            acceptance_evidence = [evidence_path]

        qa = {
            "schema_version": "1.0",
            "task_id": qa_task_id or task_id,
            "role": "workers_qa",
            "overall_verdict": "PASS",
            "criteria_results": [{
                "acceptance_criterion_id": "AC-001",
                "method": "Focused fake test",
                "expected_result": "PASS",
                "actual_result": "PASS",
                "evidence": [evidence_path],
                "verdict": "PASS",
                "severity": "HIGH",
                "reproduction_steps": ["Run fake test"],
                "regression_risk": "low",
                "recommended_action": "accept",
                "memory_validation_result": "not applicable",
            }],
            "design_findings": [],
            "regression_findings": [],
            "unverified_items": [],
            "memory_findings": [],
            "evidence": [evidence_path],
            "timestamp": "2026-07-30T00:00:00Z",
        }
        boss = {
            "schema_version": "1.0",
            "task_id": boss_task_id or task_id,
            "work_item_id": "WG-WORK-BOSS-001",
            "role": "workers_boss",
            "agent_id": "workers_boss",
            "status": "CLOSED",
            "summary": "Bound fake Boss review",
            "facts": ["QA report reviewed"],
            "assumptions": [],
            "inferences": [],
            "unverified_items": [],
            "failed_results": [],
            "actions_taken": ["Reviewed completion bundle"],
            "commands_run": [{"command": "fake-review", "exit_code": 0}],
            "files_changed": [],
            "tests": [{"command": "fake-review", "passed": 1, "failed": 0, "skipped": 0}],
            "evidence": [evidence_path],
            "blockers": [],
            "risks": [],
            "remaining_work": [],
            "memories_used": [],
            "memory_candidates": [],
            "confidence": 1.0,
            "timestamp": "2026-07-30T00:00:00Z",
        }
        acceptance = {
            "id": "AC-001",
            "requirement": "Fake acceptance criterion",
            "validation_method": "Focused fake test",
            "required_evidence": ["readable evidence"],
            "owner": "workers_qa",
            "status": acceptance_status,
            "evidence": acceptance_evidence,
            "verdict": acceptance_verdict,
        }
        paths = {}
        for name, document in (("qa", qa), ("boss", boss), ("acceptance", acceptance)):
            path = root / f"{name}.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            paths[name] = str(path)
        state = {
            "task_id": task_id,
            "boss_reviewed": True,
            "all_acceptance_criteria_passed": True,
            "failures_disclosed": True,
            "memory_candidate_decision_recorded": True,
            "skill_changes_resolved": True,
            "qa_report": paths["qa"],
            "boss_report": paths["boss"],
            "acceptance_criteria": [{"task_id": task_id, "path": paths["acceptance"]}],
        }
        return state, evidence_path
