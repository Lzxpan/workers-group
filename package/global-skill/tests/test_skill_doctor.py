import hashlib
import json
import tomllib
from pathlib import Path

from test_support import ROOT, WorkersGroupTestCase


class SkillDoctorTests(WorkersGroupTestCase):
    def test_low_allowlist_is_allowed_and_high_risk_needs_human_approval(self):
        module = self.source_module("skill_doctor.py")
        with self.temp_dir() as directory:
            doctor = module.SkillDoctor(Path(directory))
            low_operations = {
                "update_status_message", "retrieval_weights", "test_fixture", "diagnostics",
                "path_fix", "optional_schema_field", "text_clarification",
            }
            for operation in low_operations:
                with self.subTest(operation=operation):
                    self.assertTrue(doctor.assess({"risk": "LOW", "operation": operation})["allowed"])
            self.assertFalse(doctor.assess({"risk": "LOW", "operation": "format_frontmatter"})["allowed"])
            self.assertFalse(doctor.assess({"risk": "HIGH", "operation": "change_hook_policy"})["allowed"])

    def test_requires_failing_test_qa_and_version_changelog(self):
        module = self.source_module("skill_doctor.py")
        with self.temp_dir() as directory:
            root = Path(directory)
            doctor = module.SkillDoctor(root)
            target = self._write_hook_fixture(root)
            complete = self._valid_file_request(
                root, target, operation="update_status_message",
                oldValue="打工人集團｜舊", newValue="打工人集團｜新",
            )
            incomplete = {**complete, "failingTest": False}
            self.assertFalse(doctor.apply(incomplete)["applied"])
            self.assertTrue(doctor.apply(complete)["applied"])
            changelog = doctor.changelog_file.read_text(encoding="utf-8")
            self.assertIn("\n\n## 1.0.1", changelog)
            self.assertFalse(changelog.endswith("\n\n"))

    def test_targetless_apply_requires_full_tests_and_boss_approval(self):
        module = self.source_module("skill_doctor.py")
        with self.temp_dir() as directory:
            root = Path(directory)
            doctor = module.SkillDoctor(root)
            evidence = root / "evidence.txt"
            evidence.write_text("obvious fake full-suite and QA evidence\n", encoding="utf-8")
            targetless = {
                **self._valid_apply_request(),
                "testEvidence": [str(evidence)],
                "qaEvidence": [str(evidence)],
            }
            self.assertFalse(doctor.apply(targetless)["applied"])
            for key, value in (("fullTestsPassed", False), ("bossReview", "FAIL")):
                with self.subTest(missing_or_invalid=key):
                    request = {**targetless, key: value}
                    self.assertFalse(doctor.apply(request)["applied"])

    def test_backup_rollback_and_repeated_patch_fingerprint_refusal(self):
        module = self.source_module("skill_doctor.py")
        with self.temp_dir() as directory:
            root = Path(directory)
            doctor = module.SkillDoctor(root)
            target = self._write_hook_fixture(root)
            request = {
                **self._valid_file_request(
                    root, target, operation="update_status_message",
                    oldValue="打工人集團｜舊", newValue="打工人集團｜新",
                ),
                "fingerprint": "same",
            }
            first = doctor.apply(request)
            self.assertTrue(Path(first["backupPath"]).exists())
            self.assertTrue(doctor.rollback(first["backupPath"])["rolledBack"])
            self.assertFalse(doctor.apply(request)["applied"])

    def test_rollback_rejects_forged_or_unapproved_manifests(self):
        module = self.source_module("skill_doctor.py")
        cases = (
            {
                "name": "no-approved-fingerprint",
                "entry": ".codex/hooks.json",
                "approved_target": None,
                "approved_fingerprint": None,
            },
            {
                "name": "approved-record-fingerprint-mismatch",
                "entry": ".codex/hooks.json",
                "approved_target": ".codex/hooks.json",
                "approved_fingerprint": "different-fingerprint",
            },
            {
                "name": "entry-outside-original-operation-target",
                "entry": ".workers-group/config/other.json",
                "approved_target": ".codex/hooks.json",
                "approved_fingerprint": "rollback-red-control",
            },
            {
                "name": "forbidden-entry-target-class",
                "entry": ".agents/skills/orchestrating-workers-group/scripts/validate_transition.py",
                "approved_target": ".agents/skills/orchestrating-workers-group/scripts/validate_transition.py",
                "approved_fingerprint": "rollback-red-control",
            },
            {
                "name": "forbidden-agents-entry",
                "entry": "AGENTS.md",
                "approved_target": "AGENTS.md",
                "approved_fingerprint": "rollback-red-control",
            },
        )
        for case in cases:
            with self.subTest(case=case["name"]), self.temp_dir() as directory:
                root = Path(directory)
                doctor = module.SkillDoctor(root)
                target, manifest = self._write_forged_rollback_case(
                    doctor,
                    entry=case["entry"],
                    approved_target=case["approved_target"],
                    approved_fingerprint=case["approved_fingerprint"],
                )
                result = doctor.rollback(manifest)
                self.assertEqual(
                    (False, "original protected content\n"),
                    (result["rolledBack"], target.read_text(encoding="utf-8")),
                    result,
                )

    def test_proposal_id_and_target_path_traversal_are_rejected(self):
        module = self.source_module("skill_doctor.py")
        with self.temp_dir() as directory:
            root = Path(directory)
            doctor = module.SkillDoctor(root)
            unsafe_id = doctor.propose({
                "proposalId": "../escape",
                "risk": "LOW",
                "operation": "text_clarification",
            })
            self.assertFalse(unsafe_id.get("proposed"), unsafe_id)
            self.assertFalse((doctor.state / "escape.json").exists())

            outside = root.parent / "outside-do-not-touch.txt"
            result = doctor.simulate({
                "risk": "LOW",
                "operation": "text_clarification",
                "target": "../outside-do-not-touch.txt",
                "oldValue": "old",
                "newValue": "new",
            })
            self.assertFalse(result.get("simulated"), result)
            self.assertFalse(outside.exists())

    def test_low_risk_operations_cannot_target_core_governance_files(self):
        module = self.source_module("skill_doctor.py")
        core_targets = (
            ".agents/skills/orchestrating-workers-group/scripts/validate_transition.py",
            ".agents/skills/orchestrating-workers-group/scripts/validate_report.py",
            ".agents/skills/orchestrating-workers-group/scripts/validate_skill.py",
            ".agents/skills/orchestrating-workers-group/scripts/workers_group_hook.py",
            "AGENTS.md",
        )
        for relative in core_targets:
            with self.subTest(target=relative), self.temp_dir() as directory:
                root = Path(directory)
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("old core policy\n", encoding="utf-8")
                doctor = module.SkillDoctor(root)
                request = self._valid_file_request(
                    root, target, operation="text_clarification",
                    oldValue="old core policy", newValue="changed core policy",
                )
                result = doctor.apply(request)
                self.assertFalse(result["applied"], result)
                self.assertEqual("old core policy\n", target.read_text(encoding="utf-8"))

    def test_operations_are_restricted_to_their_target_classes(self):
        module = self.source_module("skill_doctor.py")
        cases = (
            ("update_status_message", ".workers-group/config/not-hooks.json",
             '{"statusMessage":"打工人集團｜舊"}\n',
             {"oldValue": "打工人集團｜舊", "newValue": "打工人集團｜新"}),
            ("retrieval_weights", ".codex/hooks.json", "relevance_weight = 1\n",
             {"field": "relevance_weight", "value": 2}),
            ("text_clarification", ".codex/hooks.json", '{"note":"old"}\n',
             {"oldValue": "old", "newValue": "new"}),
        )
        for operation, relative, content, fields in cases:
            with self.subTest(operation=operation, target=relative), self.temp_dir() as directory:
                root = Path(directory)
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
                doctor = module.SkillDoctor(root)
                result = doctor.apply(self._valid_file_request(root, target, operation=operation, **fields))
                self.assertFalse(result["applied"], result)
                self.assertEqual(content, target.read_text(encoding="utf-8"))

    def test_file_apply_requires_existing_repo_evidence_and_allows_hooks_status_update(self):
        module = self.source_module("skill_doctor.py")
        for invalid_evidence in (["evidence/missing.txt"], ["../outside-evidence.txt"]):
            with self.subTest(invalid_evidence=invalid_evidence), self.temp_dir() as directory:
                root = Path(directory)
                target = self._write_hook_fixture(root)
                doctor = module.SkillDoctor(root)
                request = self._valid_file_request(
                    root, target, operation="update_status_message",
                    evidence_paths=invalid_evidence,
                    oldValue="打工人集團｜舊", newValue="打工人集團｜新",
                )
                self.assertFalse(doctor.apply(request)["applied"])

        with self.temp_dir() as directory:
            root = Path(directory)
            target = self._write_hook_fixture(root)
            doctor = module.SkillDoctor(root)
            request = self._valid_file_request(
                root, target, operation="update_status_message",
                oldValue="打工人集團｜舊", newValue="打工人集團｜新",
            )
            result = doctor.apply(request)
            self.assertTrue(result["applied"], result)
            self.assertIn("打工人集團｜新", target.read_text(encoding="utf-8"))

    def test_retrieval_weights_applies_to_repository_policy(self):
        doctor_module = self.source_module("skill_doctor.py")
        retriever_module = self.source_module("memory_retriever.py")
        weights = {
            "relevance_weight": 0.55,
            "scope_weight": 0.10,
            "confidence_weight": 0.10,
            "authority_weight": 0.10,
            "recency_weight": 0.05,
            "success_weight": 0.05,
            "conflict_penalty": 0.10,
            "staleness_penalty": 0.05,
            "harmful_history_penalty": 0.10,
        }
        policy_text = "".join(f"{field} = {value:.2f}\n" for field, value in weights.items())

        with self.subTest(control="doctor-apply"), self.temp_dir() as directory:
            root = Path(directory)
            policy = root / ".workers-group" / "config" / "retrieval-policy.toml"
            policy.parent.mkdir(parents=True)
            policy.write_text(policy_text, encoding="utf-8")
            doctor = doctor_module.SkillDoctor(root)
            request = self._valid_file_request(
                root, policy, operation="retrieval_weights",
                field="relevance_weight", value=0.65,
            )
            request["changelog"] = "Raise relevance weight from 0.55 to 0.65."
            result = doctor.apply(request)
            self.assertTrue(result["applied"], result)
            updated = tomllib.loads(policy.read_text(encoding="utf-8"))
            self.assertEqual(0.65, updated["relevance_weight"])
            self.assertEqual("1.0.1", doctor.version_file.read_text(encoding="utf-8").strip())
            self.assertIn(request["changelog"], doctor.changelog_file.read_text(encoding="utf-8"))

        with self.subTest(control="production-policy"):
            production_policy = ROOT / ".workers-group" / "config" / "retrieval-policy.toml"
            parsed = tomllib.loads(production_policy.read_text(encoding="utf-8"))
            missing = doctor_module.WEIGHT_FIELDS - parsed.keys()
            self.assertFalse(missing, f"missing Doctor allowlisted weights: {sorted(missing)}")
            for field in doctor_module.WEIGHT_FIELDS:
                self.assertIsInstance(parsed[field], (int, float), field)
                self.assertTrue(0 <= float(parsed[field]) <= 1, f"{field}={parsed[field]}")

        with self.subTest(control="retriever-live-policy"), self.temp_dir() as directory:
            root = Path(directory)
            policy = root / ".workers-group" / "config" / "retrieval-policy.toml"
            policy.parent.mkdir(parents=True)
            policy.write_text(policy_text, encoding="utf-8")
            db = root / ".workers-group" / "runtime" / "memory.sqlite3"
            try:
                retriever = retriever_module.MemoryRetriever(db, policy_path=policy)
            except TypeError as exc:
                self.fail(f"MemoryRetriever must accept and load policy_path: {exc}")
            required_live = {
                "relevance_weight", "confidence_weight", "authority_weight",
                "recency_weight", "scope_weight", "success_weight",
            }
            self.assertTrue(required_live.issubset(retriever.weights), retriever.weights)
            for field in required_live:
                self.assertEqual(weights[field], retriever.weights[field], field)

    def test_apply_returns_structured_result_for_internal_sha256_fingerprint(self):
        module = self.source_module("skill_doctor.py")
        fingerprint = "c1e221d17510ff992def0989830376c42c43d599d54e2f76b35c0d8710c9795c"
        with self.temp_dir() as directory:
            root = Path(directory)
            target = self._write_hook_fixture(root)
            doctor = module.SkillDoctor(root)
            doctor._fingerprint = lambda _proposal: fingerprint
            request = self._valid_file_request(
                root, target, operation="update_status_message",
                oldValue="打工人集團｜舊", newValue="打工人集團｜新",
            )
            result = doctor.apply(request)
            self.assertIsInstance(result, dict)
            self.assertTrue(result.get("applied"), result)

    @staticmethod
    def _valid_apply_request():
        # Deliberately targetless: apply must reject even when all other labels are truthy.
        return {
            "risk": "LOW",
            "operation": "update_status_message",
            "failingTest": True,
            "fullTestsPassed": True,
            "testEvidence": ["evidence/full-suite.txt"],
            "qaEvidence": ["evidence/qa-report.md"],
            "qaVerdict": "PASS",
            "bossReview": "APPROVED",
            "version": "1.0.1",
            "changelog": "fix format",
        }

    @classmethod
    def _valid_file_request(cls, root, target, *, operation, evidence_paths=None, **fields):
        if evidence_paths is None:
            evidence_paths = ["evidence/full-suite.txt", "evidence/qa-report.md"]
            for relative in evidence_paths:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("verified test evidence\n", encoding="utf-8")
        request = {
            **cls._valid_apply_request(),
            "operation": operation,
            "target": target.relative_to(root).as_posix(),
            "expectedSha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "testEvidence": [evidence_paths[0]],
            "qaEvidence": [evidence_paths[-1]],
            **fields,
        }
        return request

    @staticmethod
    def _write_hook_fixture(root):
        target = root / ".codex" / "hooks.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps({"hooks": [{"statusMessage": "打工人集團｜舊"}]}, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return target

    @staticmethod
    def _write_forged_rollback_case(
        doctor, *, entry, approved_target, approved_fingerprint,
    ):
        fingerprint = "rollback-red-control"
        target = doctor.root / entry
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("original protected content\n", encoding="utf-8")

        backup_folder = doctor.backups / f"{fingerprint}-forged"
        backup_folder.mkdir(parents=True, exist_ok=True)
        backup_file = backup_folder / "0.bin"
        backup_file.write_text("forged overwrite\n", encoding="utf-8")
        manifest = backup_folder / "manifest.json"
        manifest.write_text(
            json.dumps({
                "fingerprint": fingerprint,
                "entries": [{
                    "path": entry,
                    "existed": True,
                    "backup": backup_file.name,
                    "sha256": hashlib.sha256(backup_file.read_bytes()).hexdigest(),
                }],
                "rolledBack": False,
            }),
            encoding="utf-8",
        )

        if approved_target is not None:
            doctor.approved.mkdir(parents=True, exist_ok=True)
            approved_key = fingerprint
            approved_record = doctor.approved / f"{approved_key}.json"
            approved_record.write_text(
                json.dumps({
                    "fingerprint": approved_fingerprint,
                    "status": "APPLIED",
                    "backupPath": str(manifest),
                    "proposal": {
                        "operation": "update_status_message",
                        "target": approved_target,
                    },
                }),
                encoding="utf-8",
            )
        return target, manifest
