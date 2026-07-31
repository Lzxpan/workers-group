from test_support import WorkersGroupTestCase


class ReportValidationTests(WorkersGroupTestCase):
    EXISTING_EVIDENCE = ".codex/skills/orchestrating-workers-group/tests/test_report_validation.py"

    def test_role_report_requires_role_status_summary_and_evidence(self):
        module = self.source_module("validate_report.py")
        invalid = {"role": "workers_executor", "status": "DONE", "summary": "finished"}
        self.assertFalse(module.validate_role_report(invalid)["valid"])
        valid = {**invalid, "evidence": [self.EXISTING_EVIDENCE]}
        self.assertTrue(module.validate_role_report(valid)["valid"])

    def test_completion_requires_evidence_and_qa_verdict_is_legal(self):
        module = self.source_module("validate_report.py")
        no_evidence = {"role": "workers_qa", "status": "DONE", "summary": "ok", "verdict": "PASS", "evidence": []}
        self.assertFalse(module.validate_qa_report(no_evidence)["valid"])
        illegal = {**no_evidence, "evidence": [self.EXISTING_EVIDENCE], "verdict": "MAYBE"}
        self.assertFalse(module.validate_qa_report(illegal)["valid"])
        legal = {**no_evidence, "evidence": [self.EXISTING_EVIDENCE], "verdict": "PASS"}
        self.assertTrue(module.validate_qa_report(legal)["valid"])

    def test_executor_ready_for_qa_rejects_empty_command_and_test_objects(self):
        module = self.source_module("validate_report.py")
        valid = self._role_report(
            role="workers_executor",
            status="READY_FOR_QA",
            evidence=[self.EXISTING_EVIDENCE],
        )
        self.assertTrue(module.validate_role_report(valid)["valid"])
        for field in ("commands_run", "tests"):
            with self.subTest(field=field):
                invalid = {**valid, field: [{}]}
                self.assertFalse(module.validate_role_report(invalid)["valid"])

    def test_completion_rejects_nonexistent_evidence_paths(self):
        module = self.source_module("validate_report.py")
        report = self._role_report(
            role="workers_executor",
            status="READY_FOR_QA",
            evidence=[".workers-group/evidence/definitely-missing-red-control.txt"],
        )
        self.assertFalse(module.validate_role_report(report)["valid"])

    def test_planner_feasibility_review_requires_concrete_api_evidence(self):
        module = self.source_module("validate_report.py")
        report = self._role_report(
            role="workers_planner",
            status="FEASIBILITY_REVIEW",
            evidence=[],
        )
        report["commands_run"] = []
        report["tests"] = []
        report["facts"] = []
        report["assumptions"] = ["Assume an unverified API exists"]
        self.assertFalse(module.validate_role_report(report)["valid"])

    @staticmethod
    def _role_report(*, role, status, evidence):
        return {
            "schema_version": "1.0",
            "task_id": "WG-report-red-control",
            "work_item_id": "WG-WORK-001",
            "role": role,
            "agent_id": role,
            "status": status,
            "summary": "Concrete verification report",
            "facts": ["Test command completed"],
            "assumptions": [],
            "actions_taken": ["Ran verification"],
            "commands_run": [{"command": "python -m unittest", "exit_code": 0}],
            "files_changed": ["tests/test_report_validation.py"],
            "tests": [{"command": "python -m unittest", "passed": 1, "failed": 0, "skipped": 0}],
            "evidence": evidence,
            "blockers": [],
            "risks": [],
            "remaining_work": [],
            "memories_used": [],
            "memory_candidates": [],
            "confidence": 0.9,
            "timestamp": "2026-07-30T00:00:00Z",
        }
