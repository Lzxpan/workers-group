import shutil
import subprocess
import tomllib

from test_support import ROOT, SCRIPTS, WorkersGroupTestCase


class SelfImprovementStructureTests(WorkersGroupTestCase):
    def test_project_codex_config_uses_supported_feature_and_thread_keys(self):
        config = tomllib.loads((ROOT / ".codex" / "config.toml").read_text(encoding="utf-8"))
        self.assertIs(config.get("features", {}).get("hooks"), True)
        self.assertIs(config.get("features", {}).get("multi_agent"), True)
        self.assertEqual(4, config.get("agents", {}).get("max_threads"))

    def test_codex_features_list_accepts_project_config_when_cli_exists(self):
        executable = shutil.which("codex")
        if executable is None:
            self.skipTest("codex CLI is not installed")
        result = subprocess.run(
            [executable, "features", "list"], cwd=ROOT, text=True,
            capture_output=True, timeout=30,
        )
        self.assertEqual(0, result.returncode, result.stderr or result.stdout)

    def test_skill_has_frontmatter_and_exact_hook_canonical_display_name(self):
        skill = SCRIPTS.parent / "SKILL.md"
        self.assertTrue(skill.is_file())
        content = skill.read_text(encoding="utf-8")
        self.assertTrue(content.startswith("---\n"))
        self.assertIn("name: orchestrating-workers-group", content)
        self.assertIn("WG-HOOK-010", content)
        self.assertIn("打工人集團｜執行完成度與品質閘門", content)

    def test_improvement_proposal_schema_matches_cli_contract_and_real_template(self):
        module = self.source_module("validate_report.py")
        base = {
            "proposalId": "WG-PROPOSAL-RED-CONTROL",
            "risk": "LOW",
            "operation": "update_status_message",
            "status": "PROPOSED",
            "target": ".codex/hooks.json",
            "expectedSha256": "0" * 64,
            "failingTest": True,
            "fullTestsPassed": True,
            "testEvidence": [".codex/skills/orchestrating-workers-group/tests/test_skill_doctor.py"],
            "qaEvidence": [".codex/skills/orchestrating-workers-group/tests/test_self_improvement.py"],
            "qaVerdict": "PASS",
            "bossReview": "APPROVED",
            "version": "1.0.1",
            "changelog": "Validate the CLI proposal contract.",
        }
        operations = {
            "update_status_message": {
                "oldValue": "打工人集團｜舊", "newValue": "打工人集團｜新",
            },
            "retrieval_weights": {"field": "relevance_weight", "value": 2},
            "test_fixture": {"oldValue": "old fixture", "newValue": "new fixture"},
            "diagnostics": {"field": "diagnostic_note", "value": "verified"},
            "path_fix": {"oldValue": "old/path", "newValue": "new/path"},
            "optional_schema_field": {"field": "optional_note", "schema": {"type": "string"}},
            "text_clarification": {"oldValue": "old text", "newValue": "new text"},
        }
        for operation, fields in operations.items():
            with self.subTest(operation=operation):
                proposal = {**base, "operation": operation, **fields}
                self.assertTrue(module.validate_document("improvement-proposal", proposal)["valid"])

        template = self.load_json(".workers-group/templates/improvement-proposal.template.json")
        required = set(base) | {"oldValue", "newValue"}
        self.assertTrue(required.issubset(template), required - set(template))
        self.assertTrue(module.validate_document("improvement-proposal", template)["valid"])

    def test_five_agent_tomls_parse_with_hook_prefix_and_no_handler_level_name(self):
        agents = ["workers_boss", "workers_planner", "workers_pm", "workers_executor", "workers_qa"]
        for agent in agents:
            with self.subTest(agent=agent):
                path = ROOT / ".codex" / "agents" / f"{agent}.toml"
                self.assertTrue(path.is_file(), f"missing agent: {path.relative_to(ROOT)}")
                parsed = tomllib.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(agent, parsed.get("name"))
        hooks = self.load_json(".codex/hooks.json")
        self.assertFalse(self._contains_handler_name(hooks))
        self.assertTrue(self._all_workers_group_status_messages_prefixed(hooks))

    def _contains_handler_name(self, value):
        if isinstance(value, dict):
            return "name" in value or any(self._contains_handler_name(v) for v in value.values())
        if isinstance(value, list):
            return any(self._contains_handler_name(v) for v in value)
        return False

    def _all_workers_group_status_messages_prefixed(self, value):
        if isinstance(value, dict):
            command = str(value.get("commandWindows", ""))
            if "--hook-id WG-HOOK-" in command and not str(value.get("statusMessage", "")).startswith("打工人集團｜"):
                return False
            return all(self._all_workers_group_status_messages_prefixed(v) for v in value.values())
        if isinstance(value, list):
            return all(self._all_workers_group_status_messages_prefixed(v) for v in value)
        return True
