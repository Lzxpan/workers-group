"""Direct regression checks for the installed global Skill."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def load(name: str):
    path = SCRIPTS / name
    spec = importlib.util.spec_from_file_location(f"global_{name.replace('.', '_')}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(SCRIPTS))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(SCRIPTS))
    return module


class AutoLearningGlobalTests(unittest.TestCase):
    def test_skill_has_fixed_child_names_and_auto_rule_markers(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        for name in ("task_name", "workers_planner", "workers_pm", "workers_executor", "workers_qa"):
            self.assertIn(name, skill)
        self.assertEqual(1, skill.count("<!-- WG_AUTO_LEARNING_RULES_START -->"))
        self.assertEqual(1, skill.count("<!-- WG_AUTO_LEARNING_RULES_END -->"))

    def test_doctor_appends_only_one_bounded_rule(self):
        doctor_module = load("skill_doctor.py")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "SKILL.md"
            target.write_text(
                "---\nname: orchestrating-workers-group\n---\n"
                "<!-- WG_AUTO_LEARNING_RULES_START -->\n"
                "<!-- WG_AUTO_LEARNING_RULES_END -->\n",
                encoding="utf-8",
            )
            (root / "test.txt").write_text("baseline fixed\n", encoding="utf-8")
            (root / "qa.txt").write_text("independent QA PASS\n", encoding="utf-8")
            proposal = {
                "proposalId": "WG-AUTO-RULE-TEST-20260802",
                "risk": "LOW",
                "operation": "learned_skill_rule",
                "target": "SKILL.md",
                "expectedSha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                "failingTest": True,
                "fullTestsPassed": True,
                "testEvidence": ["test.txt"],
                "qaEvidence": ["qa.txt"],
                "qaVerdict": "PASS",
                "bossReview": "APPROVED",
                "version": "1.0.0",
                "changelog": "Append a bounded learned rule.",
                "rule": "- 建立子代理時 task_name 使用固定 role identifier。",
            }
            result = doctor_module.SkillDoctor(root).apply(proposal)
            self.assertTrue(result["applied"], result)
            self.assertIn(proposal["rule"], target.read_text(encoding="utf-8"))
            bad = dict(proposal, proposalId="WG-AUTO-RULE-BAD-20260802", rule="- first\n- second")
            self.assertFalse(doctor_module.SkillDoctor(root).simulate(bad)["simulated"])

    def test_guard_accepts_integrity_hashes_without_weakening_secret_redaction(self):
        guard = load("memory_guard.py")
        self.assertTrue(guard.redact_and_validate("sha256=" + "a" * 64)["accepted"])
        self.assertFalse(guard.redact_and_validate("Bearer " + "aB3/" * 12)["accepted"])

    def test_doctor_allows_structural_hash_and_evidence_paths_but_scans_rule_text(self):
        doctor = load("skill_doctor.py").SkillDoctor(Path(tempfile.gettempdir()))
        safe, error = doctor._guard({
            "target": "SKILL.md", "expectedSha256": "a" * 64,
            "testEvidence": [".workers-group/reports/WG-AUTOLEARNING-QA-20260802.md"],
            "rule": "- 正常規則。",
        })
        self.assertIsNone(error)
        self.assertIsNotNone(safe)
        unsafe, error = doctor._guard({"rule": "Bearer " + "aB3/" * 12})
        self.assertIsNone(unsafe)
        self.assertIsNotNone(error)

    def test_qa_verified_local_experience_activates_but_self_review_does_not(self):
        store_module = load("memory_store.py")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".git").mkdir()
            evidence = root / "evidence.txt"
            evidence.write_text("QA PASS evidence\n", encoding="utf-8")
            (root / "qa.json").write_text(json.dumps({
                "task_id": "WG-verified-memory", "role": "workers_qa",
                "overall_verdict": "PASS", "evidence": ["evidence.txt"],
            }), encoding="utf-8")
            store = store_module.MemoryStore(root / ".workers-group" / "runtime" / "memory.sqlite3")
            result = store.add_verified_experience({
                "id": "verified-memory",
                "content": "A focused repair with independent QA is reusable.",
                "source": "test",
                "source_task_id": "WG-verified-memory",
                "source_role": "workers_executor",
                "source_type": "verified_execution",
                "closed_status": "CLOSED",
                "memoryType": "PROCEDURAL",
                "scope": "repository",
                "confidence": 0.9,
                "evidence": ["evidence.txt"],
                "qaReport": "qa.json",
            })
            self.assertEqual("ACTIVE", result["status"])
            self.assertEqual(1, len(store.retrieve("focused repair")))
            with self.assertRaisesRegex(ValueError, "CLOSED"):
                store.add_verified_experience({
                    "id": "open-memory", "content": "An open task cannot earn active memory.",
                    "source": "test", "source_task_id": "WG-verified-memory",
                    "source_role": "workers_executor", "source_type": "verified_execution",
                    "memoryType": "PROCEDURAL", "scope": "repository", "confidence": 0.9,
                    "evidence": ["evidence.txt"], "qaReport": "qa.json",
                })
            with self.assertRaises(PermissionError):
                store.add_verified_experience({
                    "id": "boss-source-memory", "content": "Only fixed implementation roles are eligible.",
                    "source": "test", "source_task_id": "WG-verified-memory",
                    "source_role": "workers_boss", "source_type": "verified_execution",
                    "closed_status": "CLOSED", "memoryType": "PROCEDURAL", "scope": "repository",
                    "confidence": 0.9, "evidence": ["evidence.txt"], "qaReport": "qa.json",
                })
            with self.assertRaises(PermissionError):
                store.add_verified_experience({
                    "id": "self-review-memory",
                    "content": "QA cannot self activate its own memory.",
                    "source": "test",
                    "source_task_id": "WG-self-review",
                    "source_role": "workers_qa",
                    "source_type": "verified_execution",
                    "closed_status": "CLOSED",
                    "memoryType": "PROCEDURAL",
                    "scope": "repository",
                    "confidence": 0.9,
                    "evidence": ["evidence.txt"],
                    "qaReport": "qa.json",
                })

    def test_hook_requires_closed_task_qa_pass_and_local_evidence(self):
        hook = load("workers_group_hook.py")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".git").mkdir()
            (root / "evidence.txt").write_text("verified\n", encoding="utf-8")
            report = {
                "task_id": "WG-auto-memory",
                "role": "workers_qa",
                "overall_verdict": "PASS",
                "evidence": ["evidence.txt"],
            }
            (root / "qa.json").write_text(json.dumps(report), encoding="utf-8")
            candidate = hook._verified_memory_candidate(root, {"task_id": "WG-auto-memory", "status": "CLOSED"}, {
                "verifiedMemoryCandidate": {
                    "id": "auto-hook-memory",
                    "content": "A verified hook can retain local success.",
                    "sourceRole": "workers_executor",
                    "memoryType": "PROCEDURAL",
                    "qaReport": "qa.json",
                },
            }, "2026-08-02T00:00:00+00:00")
            self.assertIsNotNone(candidate)
            report["overall_verdict"] = "NOT VERIFIED"
            (root / "qa.json").write_text(json.dumps(report), encoding="utf-8")
            self.assertIsNone(hook._verified_memory_candidate(root, {"task_id": "WG-auto-memory", "status": "CLOSED"}, {
                "verifiedMemoryCandidate": {
                    "content": "This must not activate.", "sourceRole": "workers_executor", "qaReport": "qa.json",
                },
            }, "2026-08-02T00:00:00+00:00"))

    def test_repair_and_feedback_reject_unverified_success(self):
        repair = load("memory_repair.py")
        retriever = load("memory_retriever.py")
        self.assertFalse(repair._active_export_is_bound({"id": "forged", "sourceRole": "workers_executor", "evidence": ["e.txt"], "activation": {}}))
        self.assertTrue(repair._active_export_is_bound({
            "id": "bound", "sourceRole": "workers_executor", "evidence": ["e.txt"],
            "activation": {"reviewerArtifact": {"reviewer": "workers_qa", "memory_id": "bound", "verdict": "PASS", "evidence": ["e.txt"]}},
        }))
        instance = object.__new__(retriever.MemoryRetriever)
        with self.assertRaisesRegex(ValueError, "QA PASS"):
            instance.record_feedback("ledger", usage="APPLIED", outcome="SUCCESS", helpful=True, evidence=["e.txt"])


if __name__ == "__main__":
    unittest.main()
