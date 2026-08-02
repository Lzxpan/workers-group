import json
import subprocess
import sys
import tomllib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from test_support import ROOT, SCRIPTS, WorkersGroupTestCase


class MechanicalRoleGovernanceContractTests(WorkersGroupTestCase):
    def test_openai_yaml_uses_the_dependency_free_restricted_parser(self):
        validator = self.source_module("validate_skill.py")
        parsed = validator.parse_openai_yaml(
            "interface:\n  display_name: \"打工人集團\"\n  short_description: \"說明\"\n  default_prompt: \"prompt\"\n",
        )
        self.assertEqual("打工人集團", parsed["interface"]["display_name"])
        with self.assertRaisesRegex(ValueError, "openai.yaml"):
            validator.parse_openai_yaml("interface:\n  display_name: unquoted\n")

    def test_skill_seat_is_a_temporary_sponsor_bound_advisory_contract(self):
        schema_path = ROOT / ".workers-group/schemas/skill-seat.schema.json"
        template_path = ROOT / ".workers-group/templates/skill-seat.template.json"
        self.assertTrue(schema_path.is_file())
        self.assertTrue(template_path.is_file())
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        required = {
            "seat_id", "skill_path", "sponsor_role", "purpose", "scope", "permitted_inputs",
            "expected_output", "evidence", "expires_at",
        }
        self.assertEqual(required, set(schema["required"]))
        self.assertFalse(schema["additionalProperties"])

    def test_meeting_types_are_exactly_the_six_approved_types(self):
        schema = json.loads((ROOT / ".workers-group/schemas/meeting.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(
            {
                "kickoff", "design_review", "change_blocker",
                "implementation_handoff", "qa_gate", "retrospective",
            },
            set(schema["properties"]["meeting_type"]["enum"]),
        )

    ROLE_SCORE_KEYS = {
        "workers_boss": {
            "authorization_judgment", "decision_traceability", "conflict_resolution",
            "user_communication", "final_gate_integrity",
        },
        "workers_planner": {
            "requirement_clarity", "architecture_quality", "risk_analysis",
            "testability_design", "tradeoff_reasoning",
        },
        "workers_pm": {
            "dependency_control", "ownership_clarity", "state_integrity",
            "meeting_discipline", "handoff_continuity",
        },
        "workers_executor": {
            "implementation_quality", "reproducibility", "defect_prevention",
            "scope_execution", "evidence_packaging",
        },
        "workers_qa": {
            "independent_reproduction", "negative_testing", "defect_discovery",
            "verification_boundary", "verdict_integrity",
        },
    }
    SHARED_SCORE_KEYS = {
        "factual_accuracy", "evidence_completeness", "scope_discipline",
        "handoff_quality", "escalation_timeliness",
    }

    def test_every_role_has_a_machine_readable_governance_contract(self):
        required = {
            "canonical_role", "display_role", "model_tier", "personality", "capabilities",
            "authority", "prohibitions", "state_responsibilities", "report_required_fields",
            "meeting_responsibilities", "accountability_reviewer", "memory_rights",
            "training_candidate_rights",
        }
        report_fields = {"facts", "assumptions", "inferences", "unverified_items", "failed_results"}
        for role in self.ROLE_SCORE_KEYS:
            with self.subTest(role=role):
                config = tomllib.loads((ROOT / ".codex/agents" / f"{role}.toml").read_text(encoding="utf-8"))
                governance = config.get("governance", {})
                self.assertEqual(role, governance.get("canonical_role"))
                self.assertTrue(required.issubset(governance))
                self.assertTrue(str(governance.get("display_role", "")).strip())
                self.assertTrue(report_fields.issubset(set(governance.get("report_required_fields", []))))
                self.assertIn(governance.get("accountability_reviewer"), self.ROLE_SCORE_KEYS)
                self.assertNotEqual(role, governance.get("accountability_reviewer"))

    def test_role_report_and_meeting_schemas_define_governance_fields(self):
        role_schema = self.load_json(".workers-group/schemas/role-report.schema.json")
        meeting_schema = self.load_json(".workers-group/schemas/meeting.schema.json")
        self.assertTrue({"inferences", "unverified_items", "failed_results"}.issubset(role_schema["properties"]))
        self.assertTrue({"meeting_type", "chair", "quorum", "decision_records", "dissent_records", "pm_record"}.issubset(
            meeting_schema["properties"],
        ))

    def _scorecard(self, role="workers_executor", reviewer="workers_qa"):
        return {
            "schema_version": "2.0",
            "scorecard_id": "WG-SCORECARD-GOV-001",
            "task_id": "WG-GOV-001",
            "roles": [{
                "role": role,
                "reviewer_role": reviewer,
                "shared_scores": {key: 7 for key in self.SHARED_SCORE_KEYS},
                "role_scores": {key: 8 for key in self.ROLE_SCORE_KEYS[role]},
                "metric_evidence": {
                    key: [".agents/skills/orchestrating-workers-group/tests/test_governance_contracts.py"]
                    for key in self.SHARED_SCORE_KEYS | self.ROLE_SCORE_KEYS[role]
                },
                "evidence": [".agents/skills/orchestrating-workers-group/tests/test_governance_contracts.py"],
                "notes": [],
            }],
            "timestamp": "2026-08-02T00:00:00+00:00",
        }

    def test_scorecard_rejects_self_review_missing_metric_evidence_and_wrong_role_score_keys(self):
        validator = self.source_module("validate_skill.py")
        valid = self._scorecard()
        self.assertEqual([], validator.validate_scorecard_contract(valid))

        self_review = json.loads(json.dumps(valid))
        self_review["roles"][0]["reviewer_role"] = "workers_executor"
        self.assertTrue(validator.validate_scorecard_contract(self_review))

        missing_evidence = json.loads(json.dumps(valid))
        missing_evidence["roles"][0]["metric_evidence"].pop("factual_accuracy")
        self.assertTrue(validator.validate_scorecard_contract(missing_evidence))

        wrong_keys = json.loads(json.dumps(valid))
        wrong_keys["roles"][0]["role_scores"] = {key: 8 for key in self.ROLE_SCORE_KEYS["workers_pm"]}
        self.assertTrue(validator.validate_scorecard_contract(wrong_keys))

    def test_scorecard_appeal_requires_a_different_reviewer(self):
        validator = self.source_module("validate_skill.py")
        scorecard = self._scorecard()
        appeal = {
            "schema_version": "1.0",
            "scorecard_id": scorecard["scorecard_id"],
            "role": "workers_executor",
            "requesting_role": "workers_executor",
            "evidence": [".agents/skills/orchestrating-workers-group/tests/test_governance_contracts.py"],
            "requested_reviewer": "workers_planner",
        }
        self.assertEqual([], validator.validate_scorecard_appeal(appeal, scorecard))

        invalid = dict(appeal, requested_reviewer="workers_qa")
        self.assertTrue(validator.validate_scorecard_appeal(invalid, scorecard))

    def test_scorecard_appeal_resolution_requires_boss_assignment(self):
        schema = self.load_json(".workers-group/schemas/scorecard-appeal-resolution.schema.json")
        self.assertEqual("workers_boss", schema["properties"]["assigned_by"]["const"])
        self.assertEqual({"UPHELD", "ADJUSTED", "REJECTED"}, set(schema["properties"]["resolution"]["enum"]))

    def test_training_candidate_requires_three_matching_verified_tasks_and_no_operation_fields(self):
        validator = self.source_module("validate_skill.py")
        task = {
            "task_id": "WG-001", "verified": True, "qa_verdict": "PASS", "closed_status": "CLOSED",
            "timestamp": "2026-08-02T00:00:00+00:00",
            "evidence": [".agents/skills/orchestrating-workers-group/tests/test_governance_contracts.py"],
            "capability_gaps": ["boundary-coverage"],
        }
        candidate = {
            "schema_version": "1.0",
            "candidate_id": "WG-TRAIN-001",
            "role": "workers_qa",
            "capability_gap": "boundary-coverage",
            "recent_verified_tasks": [task, {**task, "task_id": "WG-002"}, {**task, "task_id": "WG-003"}],
            "status": "TRAINING_CANDIDATE",
        }
        self.assertEqual([], validator.validate_training_candidate(candidate))

        invalid = dict(candidate, training_job="forbidden")
        self.assertTrue(validator.validate_training_candidate(invalid))

        duplicate = dict(candidate, recent_verified_tasks=[task, task, {**task, "task_id": "WG-003"}])
        self.assertTrue(validator.validate_training_candidate(duplicate))

        unverified = json.loads(json.dumps(candidate))
        unverified["recent_verified_tasks"][2]["qa_verdict"] = "NOT_VERIFIED"
        self.assertTrue(validator.validate_training_candidate(unverified))


class SkillReferenceRoutingTests(WorkersGroupTestCase):
    def _routing_errors(self, content, *, missing_reference=None):
        module = self.source_module("validate_skill.py")
        with self.temp_dir() as directory:
            root = Path(directory)
            skill = root / ".agents/skills/orchestrating-workers-group/SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text(content, encoding="utf-8")
            for reference in module.REFERENCE_ROUTES:
                if reference != missing_reference:
                    path = skill.parent / reference
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("reference", encoding="utf-8")
            errors = []
            module._validate_skill_file(root, errors)
            return errors

    def test_skill_requires_every_phase_based_reference_route(self):
        skill_path = ROOT / ".agents/skills/orchestrating-workers-group/SKILL.md"
        content = skill_path.read_text(encoding="utf-8")
        module = self.source_module("validate_skill.py")

        self.assertEqual([], self._routing_errors(content))
        for reference in module.REFERENCE_ROUTES:
            with self.subTest(reference=reference):
                errors = self._routing_errors(content.replace(reference, "missing-reference.md"))
                self.assertIn(f"SKILL.md missing required reference route: {reference}", errors)

    def test_skill_requires_reference_target_files(self):
        skill_path = ROOT / ".agents/skills/orchestrating-workers-group/SKILL.md"
        content = skill_path.read_text(encoding="utf-8")
        module = self.source_module("validate_skill.py")

        for reference in module.REFERENCE_ROUTES:
            with self.subTest(reference=reference):
                errors = self._routing_errors(content, missing_reference=reference)
                self.assertIn(f"SKILL.md reference target is missing: {reference}", errors)

    def test_skill_requires_routing_anchor_and_current_governance_conditions(self):
        skill_path = ROOT / ".agents/skills/orchestrating-workers-group/SKILL.md"
        content = skill_path.read_text(encoding="utf-8")
        module = self.source_module("validate_skill.py")

        anchor_errors = self._routing_errors(content.replace(module.ROUTING_ANCHOR, "## Missing routing"))
        self.assertIn("SKILL.md missing phase-based reference routing anchor", anchor_errors)
        for condition in module.CURRENT_GOVERNANCE_CONDITIONS:
            with self.subTest(condition=condition):
                errors = self._routing_errors(content.replace(condition, "missing-governance-condition"))
                self.assertIn(f"SKILL.md missing governance condition: {condition}", errors)
        for condition in set(module.REFERENCE_ROUTES.values()):
            with self.subTest(routing_condition=condition):
                errors = self._routing_errors(content.replace(condition, "missing-routing-condition"))
                self.assertIn(f"SKILL.md missing reference routing condition: {condition}", errors)

    def test_skill_routes_detailed_role_governance_operating_references(self):
        skill_path = ROOT / ".agents/skills/orchestrating-workers-group/SKILL.md"
        content = skill_path.read_text(encoding="utf-8")
        module = self.source_module("validate_skill.py")

        for reference, routing_condition in module.DETAILED_GOVERNANCE_REFERENCES.items():
            with self.subTest(reference=reference):
                self.assertIn(reference, content)
                self.assertIn(routing_condition, content)
                self.assertTrue((skill_path.parent / reference).is_file())
        for marker in module.DETAILED_GOVERNANCE_MARKERS:
            with self.subTest(marker=marker):
                self.assertIn(marker, content)


class TransitionAuditTests(WorkersGroupTestCase):
    def test_cli_appends_accepted_and_rejected_events(self):
        script = ROOT / ".agents/skills/orchestrating-workers-group/scripts/validate_transition.py"
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
                [*common, "--from", "INTAKE", "--to", "KICKOFF"],
                cwd=ROOT, text=True, capture_output=True,
            )
            rejected = subprocess.run(
                [*common, "--from", "INTAKE", "--to", "CLOSED"],
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
                    "previous_status": "EVIDENCE_REVIEW",
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
                "previous_status": "EVIDENCE_REVIEW",
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
        script = ROOT / ".agents/skills/orchestrating-workers-group/scripts/validate_transition.py"
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
                    "--from", "INTAKE", "--to", "CLOSED", "--actor", "workers_pm",
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
    SHARED_METRICS = {
        "factual_accuracy": 8,
        "evidence_completeness": 8,
        "scope_discipline": 8,
        "handoff_quality": 8,
        "escalation_timeliness": 8,
    }
    EXECUTOR_METRICS = {
        "implementation_quality": 8,
        "reproducibility": 8,
        "defect_prevention": 8,
        "scope_execution": 8,
        "evidence_packaging": 8,
    }

    def _scorecard(self, evidence):
        return {
            "schema_version": "2.0",
            "scorecard_id": "WG-SCORECARD-001",
            "task_id": "WG-scorecard-contract",
            "roles": [{
                "role": "workers_executor",
                "reviewer_role": "workers_qa",
                "shared_scores": self.SHARED_METRICS,
                "role_scores": self.EXECUTOR_METRICS,
                "metric_evidence": {
                    metric: [str(evidence)]
                    for metric in (*self.SHARED_METRICS, *self.EXECUTOR_METRICS)
                },
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
        missing_metric["roles"][0]["shared_scores"].pop("factual_accuracy")
        self.assertFalse(validator.validate_document("scorecard", missing_metric)["valid"])

        missing_evidence = json.loads(json.dumps(valid))
        missing_evidence["roles"][0]["evidence"] = []
        self.assertFalse(validator.validate_document("scorecard", missing_evidence)["valid"])

        non_finite = json.loads(json.dumps(valid))
        non_finite["roles"][0]["role_scores"]["scope_execution"] = float("nan")
        self.assertFalse(validator.validate_document("scorecard", non_finite)["valid"])

    def test_scorecard_store_validates_before_atomic_write(self):
        script = ROOT / ".agents/skills/orchestrating-workers-group/scripts/scorecard_store.py"
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

    @staticmethod
    def _governance_kwargs():
        evidence = [str(Path(__file__).resolve())]
        return {
            "meeting_type": "kickoff",
            "chair": "workers_boss",
            "quorum": {"minimum_attendees": 2, "required_roles": ["workers_boss", "workers_pm"]},
            "decision_records": [{
                "decision": "Select A", "owner": "workers_executor",
                "rationale": "Evidence supports the selected alternative", "evidence": evidence,
            }],
            "dissent_records": [],
            "pm_record": {
                "role": "workers_pm", "recorded_actions": ["Implement A"],
                "blockers": [], "resume_condition": "Executor provides evidence",
            },
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
            "due_state": "EVIDENCE_REVIEW",
        }
        governance = self._governance_kwargs()
        with self.assertRaises(ValueError):
            module.build_record(
                ["workers_boss", "workers_pm"], "Choose implementation", ["Select A"], [],
                **governance,
                alternatives=[self._alternative("A")], actions=[action],
            )
        with self.assertRaises(ValueError):
            module.build_record(
                ["workers_boss", "workers_pm"], "Choose implementation", ["Select A"], [],
                **governance,
                alternatives=[self._alternative("A"), self._alternative("B")], actions=[],
            )
        missing_evidence = self._alternative("A")
        missing_evidence["evidence"] = ["missing-meeting-evidence.txt"]
        with self.assertRaises(ValueError):
            module.build_record(
                ["workers_boss", "workers_pm"], "Choose implementation", ["Select A"], [],
                **governance,
                alternatives=[missing_evidence, self._alternative("B")], actions=[action],
            )

        with self.assertRaises(ValueError):
            module.build_record(
                ["workers_boss", "workers_pm"], "Choose implementation", ["Select A"], [],
                **{**governance, "quorum": {"minimum_attendees": 3, "required_roles": ["workers_boss", "workers_qa"]}},
                alternatives=[self._alternative("A"), self._alternative("B")], actions=[action],
            )
        with self.assertRaises(ValueError):
            module.build_record(
                ["workers_boss", "workers_pm"], "Choose implementation", ["Select A"], [],
                **{**governance, "pm_record": {**governance["pm_record"], "role": "workers_boss"}},
                alternatives=[self._alternative("A"), self._alternative("B")], actions=[action],
            )
        with self.assertRaises(ValueError):
            module.build_record(
                ["workers_boss", "workers_pm"], "Choose implementation", ["Select A"], [],
                **{**governance, "decision_records": []},
                alternatives=[self._alternative("A"), self._alternative("B")], actions=[action],
            )
        with self.assertRaises(ValueError):
            module.build_record(
                ["workers_boss", "workers_pm"], "Choose implementation", ["Select A"], [],
                **{**governance, "dissent_records": [{"role": "workers_executor", "position": "Dissent"}]},
                alternatives=[self._alternative("A"), self._alternative("B")], actions=[action],
            )

        record = module.build_record(
            ["workers_boss", "workers_pm"], "Choose implementation", ["Select A"], [],
            **governance,
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
        script = ROOT / ".agents/skills/orchestrating-workers-group/scripts/meeting_record.py"
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
                "due_state": "EVIDENCE_REVIEW",
            }), encoding="utf-8")
            quorum = root / "quorum.json"
            quorum.write_text(json.dumps({"minimum_attendees": 2, "required_roles": ["workers_boss", "workers_pm"]}), encoding="utf-8")
            pm_record = root / "pm-record.json"
            pm_record.write_text(json.dumps({
                "role": "workers_pm", "recorded_actions": ["Implement A"],
                "blockers": [], "resume_condition": "Executor provides evidence",
            }), encoding="utf-8")
            decision_record = root / "decision-record.json"
            decision_record.write_text(json.dumps({
                "decision": "Select A", "owner": "workers_executor", "rationale": "Evidence supports A",
                "evidence": [str(Path(__file__).resolve())],
            }), encoding="utf-8")
            output = root / "meeting.json"

            result = subprocess.run(
                [
                    sys.executable, str(script), "--attendee", "workers_boss", "--attendee", "workers_pm",
                    "--agenda", "Choose implementation", "--decision", "Select A",
                    "--meeting-type", "kickoff", "--chair", "workers_boss",
                    "--quorum-file", str(quorum), "--pm-record-file", str(pm_record),
                    "--decision-record-file", str(decision_record),
                    *alternatives, "--action-file", str(action), "--output", str(output),
                ],
                cwd=ROOT, text=True, capture_output=True,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            record = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(2, len(record["alternatives"]))
            self.assertEqual("workers_executor", record["actions"][0]["owner"])
            self.assertEqual("EVIDENCE_REVIEW", record["actions"][0]["due_state"])
