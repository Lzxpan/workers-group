import json
import subprocess
import sys
import tempfile
from pathlib import Path

from test_support import ROOT, WorkersGroupTestCase


class AccountabilityEvaluatorTests(WorkersGroupTestCase):
    SHARED = {
        "factual_accuracy": 10,
        "evidence_completeness": 10,
        "scope_discipline": 10,
        "handoff_quality": 10,
        "escalation_timeliness": 10,
    }
    EXECUTOR = {
        "implementation_quality": 10,
        "reproducibility": 10,
        "defect_prevention": 10,
        "scope_execution": 10,
        "evidence_packaging": 10,
    }

    def setUp(self):
        self.module = self.source_module("evaluate_scorecard.py")
        self.policy = self.module.load_policy(
            ROOT / ".workers-group/config/performance-policy.toml"
        )

    def _scorecard(self):
        return {
            "schema_version": "2.0",
            "scorecard_id": "WG-SCORECARD-V2-001",
            "task_id": "WG-accountability-v2",
            "roles": [{
                "role": "workers_executor",
                "reviewer_role": "workers_qa",
                "shared_scores": dict(self.SHARED),
                "role_scores": dict(self.EXECUTOR),
                "metric_evidence": {
                    key: [str(Path(__file__).resolve())]
                    for key in self.SHARED | self.EXECUTOR
                },
                "evidence": [str(Path(__file__).resolve())],
                "notes": ["Independent QA review evidence"],
            }],
            "timestamp": "2026-08-02T00:00:00+00:00",
        }

    def test_100_point_score_only_recommends_role_badge(self):
        result = self.module.evaluate_scorecard(self._scorecard(), self.policy)
        role = result["roles"][0]

        self.assertEqual(100, role["total_points"])
        self.assertEqual("EXCELLENCE", role["score_band"])
        self.assertEqual("RECOGNITION_RECOMMENDED", role["outcome"])
        self.assertEqual(["implementation-craft"], role["badge_recommendations"])
        self.assertTrue(role["requires_independent_review"])
        self.assertIn("never changes authority automatically", role["authority_boundary"])

    def test_critical_shared_score_below_six_requires_authority_hold_and_boss_review(self):
        scorecard = self._scorecard()
        scorecard["roles"][0]["shared_scores"]["evidence_completeness"] = 5

        role = self.module.evaluate_scorecard(scorecard, self.policy)["roles"][0]

        self.assertEqual("AUTHORITY_HOLD", role["outcome"])
        self.assertEqual(["evidence_completeness"], role["reasons"])
        self.assertTrue(role["requires_boss_review"])

    def test_60_to_69_points_requires_coaching_with_next_task_evidence(self):
        scorecard = self._scorecard()
        scorecard["roles"][0]["shared_scores"] = {
            key: 7 for key in self.SHARED
        }
        scorecard["roles"][0]["role_scores"] = {
            key: 6 for key in self.EXECUTOR
        }

        role = self.module.evaluate_scorecard(scorecard, self.policy)["roles"][0]

        self.assertEqual(65, role["total_points"])
        self.assertEqual("COACHING_REQUIRED", role["outcome"])
        self.assertIn("next_similar_task_improvement_evidence", role["coaching_requirements"])

    def test_appeal_rejects_self_review_and_original_reviewer(self):
        scorecard = self._scorecard()
        appeal = {
            "schema_version": "1.0",
            "scorecard_id": "WG-SCORECARD-V2-001",
            "role": "workers_executor",
            "requesting_role": "workers_executor",
            "requested_reviewer": "workers_planner",
            "evidence": [str(Path(__file__).resolve())],
        }

        self.assertTrue(self.module.validate_appeal(appeal, scorecard))
        appeal["requested_reviewer"] = "workers_qa"
        with self.assertRaisesRegex(ValueError, "original reviewer"):
            self.module.validate_appeal(appeal, scorecard)
        appeal["requested_reviewer"] = "workers_executor"
        with self.assertRaisesRegex(ValueError, "independent"):
            self.module.validate_appeal(appeal, scorecard)

    def test_cli_writes_utf8_lf_json_atomically(self):
        script = ROOT / ".agents/skills/orchestrating-workers-group/scripts/evaluate_scorecard.py"
        reports = ROOT / ".workers-group/reports"
        with tempfile.TemporaryDirectory(dir=reports) as directory:
            source = Path(directory) / "scorecard.json"
            output = Path(directory) / "outcome.json"
            source.write_text(json.dumps(self._scorecard()), encoding="utf-8", newline="\n")
            result = subprocess.run(
                [sys.executable, str(script), "--file", str(source), "--output", str(output)],
                cwd=ROOT,
                text=True,
                encoding="utf-8",
                capture_output=True,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            raw = output.read_bytes()
            self.assertNotIn(b"\r\n", raw)
            self.assertEqual(100, json.loads(raw.decode("utf-8"))["roles"][0]["total_points"])

    def test_cli_rejects_output_outside_repository(self):
        script = ROOT / ".agents/skills/orchestrating-workers-group/scripts/evaluate_scorecard.py"
        with self.temp_dir() as directory:
            source = Path(directory) / "scorecard.json"
            outside = Path(directory) / "outside.json"
            source.write_text(json.dumps(self._scorecard()), encoding="utf-8", newline="\n")
            result = subprocess.run(
                [sys.executable, str(script), "--file", str(source), "--output", str(outside)],
                cwd=ROOT,
                text=True,
                encoding="utf-8",
                capture_output=True,
            )

            self.assertEqual(2, result.returncode)
            self.assertFalse(outside.exists())

    def test_verified_profile_is_hash_chained_append_only_and_limited_to_ten_tasks(self):
        reports = ROOT / ".workers-group/reports"
        with tempfile.TemporaryDirectory(dir=reports) as directory:
            ledger = Path(directory) / "accountability.jsonl"
            for index in range(11):
                scorecard = self._scorecard()
                scorecard["scorecard_id"] = f"WG-SCORECARD-{index:02d}"
                scorecard["task_id"] = f"WG-VERIFIED-{index:02d}"
                self.module.append_scorecard_evaluation(
                    ledger,
                    scorecard,
                    self.module.evaluate_scorecard(scorecard, self.policy),
                    qa_verdict="PASS",
                    closed_status="CLOSED",
                )

            profile = self.module.verified_profile(ledger, "workers_executor")
            self.assertEqual(10, len(profile["recent_verified_tasks"]))
            self.assertEqual("WG-VERIFIED-10", profile["recent_verified_tasks"][0]["task_id"])
            self.assertEqual("WG-VERIFIED-01", profile["recent_verified_tasks"][-1]["task_id"])
            self.assertEqual(11, len(ledger.read_text(encoding="utf-8").splitlines()))

            ledger.write_text(ledger.read_text(encoding="utf-8").replace("WG-VERIFIED-00", "TAMPERED", 1), encoding="utf-8", newline="\n")
            with self.assertRaisesRegex(ValueError, "hash chain"):
                self.module.verified_profile(ledger, "workers_executor")

    def test_appeal_resolution_is_independent_and_append_only(self):
        reports = ROOT / ".workers-group/reports"
        scorecard = self._scorecard()
        appeal = {
            "schema_version": "1.0",
            "scorecard_id": scorecard["scorecard_id"],
            "role": "workers_executor",
            "requesting_role": "workers_executor",
            "requested_reviewer": "workers_planner",
            "evidence": [str(Path(__file__).resolve())],
        }
        resolution = {
            "schema_version": "1.0",
            "appeal_id": "WG-APPEAL-001",
            "scorecard_id": scorecard["scorecard_id"],
            "role": "workers_executor",
            "assigned_by": "workers_boss",
            "reviewer_role": "workers_planner",
            "resolution": "UPHELD",
            "evidence": [str(Path(__file__).resolve())],
            "timestamp": "2026-08-02T00:00:00+00:00",
        }
        with tempfile.TemporaryDirectory(dir=reports) as directory:
            ledger = Path(directory) / "appeals.jsonl"
            self.module.append_appeal_resolution(ledger, appeal, resolution, scorecard)
            self.assertEqual("APPEAL_RESOLUTION", self.module.read_accountability_ledger(ledger)[0]["record_type"])
            resolution["reviewer_role"] = "workers_qa"
            with self.assertRaisesRegex(ValueError, "requested reviewer"):
                self.module.append_appeal_resolution(ledger, appeal, resolution, scorecard)
