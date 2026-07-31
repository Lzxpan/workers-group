import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from test_support import ROOT, SCRIPTS, WorkersGroupTestCase


class TransitionAuditTests(WorkersGroupTestCase):
    def test_cli_appends_accepted_and_rejected_events(self):
        script = SCRIPTS / "validate_transition.py"
        with self.temp_dir() as directory:
            root = Path(directory)
            state = root / "state.json"
            audit = root / "transitions.jsonl"
            state.write_text(json.dumps({
                "task_id": "WG-audit-contract",
                "evidence": ["evidence/transition.txt"],
                "related_acceptance_criteria": ["AC-001"],
            }), encoding="utf-8")
            common = [
                sys.executable, str(script), "--state", str(state),
                "--actor", "workers_pm", "--reason", "advance verified state",
                "--audit-path", str(audit),
            ]

            accepted = subprocess.run(
                [*common, "--from", "INTAKE", "--to", "CHARTERED"],
                cwd=ROOT, text=True, capture_output=True,
            )
            rejected = subprocess.run(
                [*common, "--from", "INTAKE", "--to", "DONE"],
                cwd=ROOT, text=True, capture_output=True,
            )

            self.assertEqual(0, accepted.returncode, accepted.stderr)
            self.assertEqual(2, rejected.returncode, rejected.stderr)
            events = [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([True, False], [event["accepted"] for event in events])
            self.assertIn("illegal transition", events[1]["error"])
            for event in events:
                self.assertEqual("workers_pm", event["actor"])
                self.assertEqual("INTAKE", event["previous_status"])
                self.assertEqual("WG-audit-contract", event["task_id"])
                self.assertEqual(["AC-001"], event["related_acceptance_criteria"])
                self.assertEqual(["evidence/transition.txt"], event["evidence"])
                self.assertTrue(event["timestamp"])
                self.assertTrue(event["reason"])

    def test_append_transition_audit_is_safe_under_parallel_writers(self):
        module = self.source_module("validate_transition.py")
        with self.temp_dir() as directory:
            audit = Path(directory) / "transitions.jsonl"

            def append(index):
                module.append_transition_audit(audit, {
                    "timestamp": f"2026-07-30T00:00:{index:02d}+00:00",
                    "actor": "workers_pm",
                    "previous_status": "READY",
                    "new_status": "EXECUTING",
                    "reason": f"work item {index}",
                    "evidence": [],
                    "related_acceptance_criteria": [f"AC-{index:03d}"],
                    "task_id": "WG-parallel-audit",
                    "accepted": True,
                    "error": "",
                })

            with ThreadPoolExecutor(max_workers=8) as executor:
                list(executor.map(append, range(24)))

            events = [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(24, len(events))
            self.assertEqual(24, len({event["reason"] for event in events}))
            self.assertFalse(audit.with_suffix(".jsonl.lock").exists())

    def test_transition_audit_rejects_secret_bearing_reason_without_persisting_it(self):
        module = self.source_module("validate_transition.py")
        with self.temp_dir() as directory:
            audit = Path(directory) / "transitions.jsonl"
            event = {
                "timestamp": "2026-07-30T00:00:00+00:00",
                "actor": "workers_pm",
                "previous_status": "READY",
                "new_status": "EXECUTING",
                "reason": "password=obvious-fake-secret",
                "evidence": [],
                "related_acceptance_criteria": [],
                "task_id": "WG-secret-audit",
                "accepted": True,
                "error": "",
            }
            with self.assertRaisesRegex(ValueError, "sensitive"):
                module.append_transition_audit(audit, event)
            self.assertFalse(audit.exists())

    def test_rejected_transition_audit_tolerates_malformed_optional_state_lists(self):
        script = SCRIPTS / "validate_transition.py"
        with self.temp_dir() as directory:
            root = Path(directory)
            state = root / "state.json"
            audit = root / "transitions.jsonl"
            state.write_text(json.dumps({
                "task_id": "WG-malformed-audit",
                "evidence": None,
                "acceptance_criteria": None,
            }), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable, str(script), "--state", str(state),
                    "--from", "INTAKE", "--to", "DONE", "--actor", "workers_pm",
                    "--reason", "reject malformed state", "--audit-path", str(audit),
                ],
                cwd=ROOT, text=True, capture_output=True,
            )
            self.assertEqual(2, result.returncode, result.stderr)
            self.assertFalse(json.loads(result.stdout)["valid"])
            event = json.loads(audit.read_text(encoding="utf-8"))
            self.assertFalse(event["accepted"])
            self.assertEqual([], event["evidence"])
            self.assertEqual([], event["related_acceptance_criteria"])


class AccountabilityScorecardTests(WorkersGroupTestCase):
    METRICS = {
        "evidence_accuracy": 5,
        "completeness": 4,
        "honesty": 5,
        "requirement_adherence": 4,
        "test_quality": 5,
        "risk_disclosure": 4,
        "collaboration": 4,
        "efficiency": 5,
        "memory_quality": 3,
        "memory_reuse_accuracy": 3,
    }

    def _scorecard(self, evidence):
        return {
            "schema_version": "1.0",
            "scorecard_id": "WG-SCORECARD-001",
            "task_id": "WG-scorecard-contract",
            "roles": [{
                "role": "workers_executor",
                "scores": self.METRICS,
                "evidence": [str(evidence)],
                "notes": ["Focused implementation evidence"],
            }],
            "timestamp": "2026-07-30T00:00:00+00:00",
        }

    def test_scorecard_requires_all_metrics_and_role_evidence(self):
        validator = self.source_module("validate_report.py")
        valid = self._scorecard(Path(__file__).resolve())
        self.assertTrue(validator.validate_document("scorecard", valid)["valid"])

        missing_metric = json.loads(json.dumps(valid))
        missing_metric["roles"][0]["scores"].pop("honesty")
        self.assertFalse(validator.validate_document("scorecard", missing_metric)["valid"])

        missing_evidence = json.loads(json.dumps(valid))
        missing_evidence["roles"][0]["evidence"] = []
        self.assertFalse(validator.validate_document("scorecard", missing_evidence)["valid"])

        non_finite = json.loads(json.dumps(valid))
        non_finite["roles"][0]["scores"]["efficiency"] = float("nan")
        self.assertFalse(validator.validate_document("scorecard", non_finite)["valid"])

    def test_scorecard_store_validates_before_atomic_write(self):
        script = SCRIPTS / "scorecard_store.py"
        with self.temp_dir() as directory:
            root = Path(directory)
            source = root / "source.json"
            output = root / "stored.json"
            evidence = Path(__file__).resolve()
            source.write_text(json.dumps(self._scorecard(evidence)), encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(script), "--file", str(source), "--output", str(output)],
                cwd=ROOT, text=True, capture_output=True,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(self._scorecard(evidence), json.loads(output.read_text(encoding="utf-8")))


class MeetingContractTests(WorkersGroupTestCase):
    @staticmethod
    def _alternative(identifier):
        return {
            "id": identifier,
            "description": f"Alternative {identifier}",
            "evidence": [str(Path(__file__).resolve())],
            "feasibility": "Feasible with stdlib",
            "implementation_impact": "One focused module",
            "validation_method": "Run focused unittest",
            "risks": ["Concurrent write contention"],
            "rollback": "Restore the previous file",
            "owner": "workers_executor",
            "affected_acceptance_criteria": ["AC-001"],
            "affected_memories": [],
            "affected_skill_rules": ["meeting-protocol"],
        }

    def test_meeting_requires_two_complete_alternatives_and_owned_action(self):
        sys.path.insert(0, str(SCRIPTS))
        try:
            module = self.source_module("meeting_record.py")
        finally:
            sys.path.remove(str(SCRIPTS))
        action = {
            "description": "Implement selected alternative",
            "owner": "workers_executor",
            "due_state": "READY_FOR_QA",
        }
        with self.assertRaises(ValueError):
            module.build_record(
                ["workers_boss"], "Choose implementation", ["Select A"], [],
                alternatives=[self._alternative("A")], actions=[action],
            )
        with self.assertRaises(ValueError):
            module.build_record(
                ["workers_boss"], "Choose implementation", ["Select A"], [],
                alternatives=[self._alternative("A"), self._alternative("B")], actions=[],
            )
        missing_evidence = self._alternative("A")
        missing_evidence["evidence"] = ["missing-meeting-evidence.txt"]
        with self.assertRaises(ValueError):
            module.build_record(
                ["workers_boss"], "Choose implementation", ["Select A"], [],
                alternatives=[missing_evidence, self._alternative("B")], actions=[action],
            )

        record = module.build_record(
            ["workers_boss"], "Choose implementation", ["Select A"], [],
            alternatives=[self._alternative("A"), self._alternative("B")], actions=[action],
        )
        validator = self.source_module("validate_report.py")
        self.assertTrue(validator.validate_document("meeting", record)["valid"])
        self.assertFalse(validator.validate_document("meeting", {
            **record,
            "alternatives": [
                self._alternative("A"), self._alternative("B"),
                self._alternative("C"), self._alternative("D"),
            ],
        })["valid"])
        required_option_fields = (
            "description", "evidence", "feasibility", "implementation_impact",
            "validation_method", "risks", "rollback", "owner",
            "affected_acceptance_criteria", "affected_memories", "affected_skill_rules",
        )
        for field in required_option_fields:
            incomplete = json.loads(json.dumps(record))
            incomplete["alternatives"][0].pop(field)
            with self.subTest(missing_option_field=field):
                self.assertFalse(validator.validate_document("meeting", incomplete)["valid"])

    def test_meeting_cli_accepts_structured_alternative_and_action_files(self):
        script = SCRIPTS / "meeting_record.py"
        with self.temp_dir() as directory:
            root = Path(directory)
            alternatives = []
            for identifier in ("A", "B"):
                path = root / f"alternative-{identifier}.json"
                path.write_text(json.dumps(self._alternative(identifier)), encoding="utf-8")
                alternatives.extend(["--alternative-file", str(path)])
            action = root / "action.json"
            action.write_text(json.dumps({
                "description": "Implement A",
                "owner": "workers_executor",
                "due_state": "READY_FOR_QA",
            }), encoding="utf-8")
            output = root / "meeting.json"

            result = subprocess.run(
                [
                    sys.executable, str(script), "--attendee", "workers_boss",
                    "--agenda", "Choose implementation", "--decision", "Select A",
                    *alternatives, "--action-file", str(action), "--output", str(output),
                ],
                cwd=ROOT, text=True, capture_output=True,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            record = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(2, len(record["alternatives"]))
            self.assertEqual("workers_executor", record["actions"][0]["owner"])
            self.assertEqual("READY_FOR_QA", record["actions"][0]["due_state"])
