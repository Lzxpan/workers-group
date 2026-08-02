import base64
import json
import os
import subprocess
import sys
from pathlib import Path

from test_support import ROOT, SCRIPTS, WorkersGroupTestCase


EVENTS = {
    "SessionStart", "SessionEnd", "UserPromptSubmit", "PreToolUse", "PostToolUse",
    "PreCompact", "PostCompact", "SubagentStart", "SubagentStop", "Stop", "PermissionRequest",
}


class HookContractTests(WorkersGroupTestCase):
    def _run_hook(self, root, payload):
        return subprocess.run(
            [sys.executable, str(SCRIPTS / "workers_group_hook.py")],
            input=json.dumps(payload),
            text=True,
            encoding="utf-8",
            capture_output=True,
            cwd=root,
            timeout=10,
            env={**os.environ, "PYTHONUTF8": "1"},
        )

    @staticmethod
    def _role_report(task_id, role, status, evidence):
        return {
            "schema_version": "1.0",
            "task_id": task_id,
            "work_item_id": "WI-HOOK",
            "role": role,
            "agent_id": f"{role}-test",
            "status": status,
            "summary": "Hook completion report",
            "facts": ["Executed in a temporary repository."],
            "assumptions": [],
            "inferences": [],
            "unverified_items": [],
            "failed_results": [],
            "actions_taken": ["Produced completion evidence."],
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
            "timestamp": "2026-07-30T00:00:00+00:00",
        }

    @staticmethod
    def _qa_report(task_id, evidence, *, verdict="PASS"):
        return {
            "schema_version": "1.0",
            "task_id": task_id,
            "role": "workers_qa",
            "overall_verdict": verdict,
            "criteria_results": [{
                "acceptance_criterion_id": "AC-HOOK",
                "method": "Independent command execution",
                "expected_result": "Hook passes",
                "actual_result": "Hook passes",
                "evidence": evidence,
                "verdict": verdict,
                "severity": "NONE",
                "reproduction_steps": ["Run the hook test."],
                "regression_risk": "LOW",
                "recommended_action": "None",
                "memory_validation_result": "PASS",
            }],
            "design_findings": [],
            "regression_findings": [],
            "unverified_items": [],
            "memory_findings": [],
            "evidence": evidence,
            "timestamp": "2026-07-30T00:00:00+00:00",
        }

    def test_hooks_json_registers_exactly_the_eleven_lifecycle_events(self):
        config = self.load_json(".codex/hooks.json")
        registered = set(config.get("hooks", config).keys())
        self.assertEqual(EVENTS, registered)

    def test_additional_context_limits_only_use_context_capable_events(self):
        hooks = self.load_json(".codex/hooks.json")["hooks"]
        context_events = {
            "PreToolUse", "PostToolUse", "SessionStart", "UserPromptSubmit", "SubagentStart",
        }
        configured = {}
        for event, groups in hooks.items():
            for group in groups:
                for handler in group.get("hooks", []):
                    if "additionalContextLimit" in handler:
                        self.assertIn(event, context_events, event)
                        configured[event] = handler["additionalContextLimit"]
        self.assertEqual({
            "SessionStart": 4096,
            "UserPromptSubmit": 4096,
            "SubagentStart": 4096,
        }, configured)

    def test_post_compact_snapshot_does_not_emit_additional_context(self):
        with self.temp_dir() as directory:
            root = Path(directory)
            (root / ".git").mkdir()
            runtime = root / ".workers-group" / "runtime"
            runtime.mkdir(parents=True)
            (runtime / "compact-snapshot.json").write_text(
                json.dumps({"task_id": "WG-postcompact", "status": "EXECUTING"}),
                encoding="utf-8",
            )
            result = self._run_hook(root, {"event": "PostCompact", "trigger": "manual"})
            self.assertEqual(0, result.returncode, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["stateRestored"], payload)
            self.assertNotIn("additionalContext", payload["hookSpecificOutput"])

    def test_tool_hook_matchers_use_canonical_tool_names(self):
        hooks = self.load_json(".codex/hooks.json")["hooks"]
        expected = {"Bash", "Edit", "Write", "apply_patch", "Agent"}
        for event in ("PreToolUse", "PostToolUse", "PermissionRequest"):
            with self.subTest(event=event):
                matcher = "|".join(
                    entry.get("matcher", "") for entry in hooks[event]
                    if isinstance(entry, dict)
                )
                self.assertTrue(expected.issubset(set(matcher.split("|"))), matcher)

    def test_valid_hook_json_has_clean_json_stdout_role_and_status_message(self):
        with self.temp_dir() as directory:
            root = Path(directory)
            (root / ".git").mkdir()
            result = self._run_hook(root, {
                "event": "SessionStart",
                "sessionId": "test-1",
                "role": "workers_executor",
            })
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(1, len(result.stdout.strip().splitlines()), result.stdout)
            response = json.loads(result.stdout)
            self.assertIn("statusMessage", response)
            self.assertTrue(response["statusMessage"].startswith("打工人集團｜"))
            self.assertIn("workers_executor", json.dumps(response, ensure_ascii=False))

    def test_malformed_json_has_no_stdout_and_diagnostic_stderr(self):
        result = self.hook({}, malformed=True)
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("", result.stdout.strip())
        self.assertTrue(result.stderr.strip())

    def test_oversized_stdin_has_no_stdout_and_bounded_diagnostic(self):
        hook = ROOT / ".codex" / "hooks" / "workers_group_hook.py"
        result = subprocess.run(
            [sys.executable, str(hook)],
            input=json.dumps({"event": "SessionStart", "padding": "x" * 1048576}),
            text=True,
            encoding="utf-8",
            capture_output=True,
            cwd=ROOT,
            timeout=10,
        )
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("", result.stdout.strip())
        self.assertIn("size limit", result.stderr)

    def test_shared_hook_helper_preserves_repository_active_task_bytes(self):
        active_path = ROOT / ".workers-group" / "runtime" / "active-task.json"
        existed_before = active_path.exists()
        before = active_path.read_bytes() if existed_before else b""
        result = self.hook({
            "event": "UserPromptSubmit",
            "prompt": "請使用 $orchestrating-workers-group 驗證 test isolation",
        })
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(existed_before, active_path.exists())
        after = active_path.read_bytes() if active_path.exists() else b""
        self.assertEqual(before, after)

    def test_command_windows_and_continuation_limit_are_enforced(self):
        response = self.hook({"event": "Stop", "continuationCount": 3, "command": "powershell"})
        self.assertEqual(0, response.returncode, response.stderr)
        payload = json.loads(response.stdout)
        self.assertIn("commandWindows", payload)
        self.assertIsInstance(payload["commandWindows"], list)
        self.assertFalse(payload.get("continue", True), payload)

    def test_windows_command_from_registry_executes_and_returns_single_json_line(self):
        hooks = self.load_json(".codex/hooks.json")["hooks"]
        command = hooks["PermissionRequest"][0]["hooks"][0]["commandWindows"]
        encoded_command = base64.b64encode(command.encode("utf-8")).decode("ascii")
        launcher = (
            "$command=[Text.Encoding]::UTF8.GetString("
            f"[Convert]::FromBase64String('{encoded_command}'));"
            "& cmd.exe /d /s /c $command"
        )
        encoded_launcher = base64.b64encode(launcher.encode("utf-16le")).decode("ascii")
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-EncodedCommand", encoded_launcher],
            input=json.dumps({"event": "PermissionRequest", "command": "Get-Location"}),
            text=True,
            encoding="utf-8",
            capture_output=True,
            cwd=ROOT,
            timeout=15,
            env={**os.environ, "PYTHONUTF8": "1"},
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(1, len(result.stdout.strip().splitlines()), result.stdout)
        payload = json.loads(result.stdout)
        self.assertEqual("PermissionRequest", payload["hookSpecificOutput"]["hookEventName"])

    def test_stop_events_block_gaps_below_cap_and_refuse_at_cap(self):
        for event in ("Stop", "SubagentStop"):
            with self.subTest(event=event, state="gap-below-cap"):
                result = self.hook({"event": event, "hasGaps": True, "continuationCount": 1})
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual("block", json.loads(result.stdout).get("decision"))
            with self.subTest(event=event, state="complete"):
                with self.temp_dir() as directory:
                    root = Path(directory)
                    (root / ".git").mkdir()
                    result = subprocess.run(
                        [sys.executable, str(SCRIPTS / "workers_group_hook.py")],
                        input=json.dumps({
                            "event": event,
                            "hasGaps": False,
                            "continuationCount": 0,
                        }),
                        text=True,
                        encoding="utf-8",
                        capture_output=True,
                        cwd=root,
                        timeout=10,
                        env={**os.environ, "PYTHONUTF8": "1"},
                    )
                    self.assertEqual(0, result.returncode, result.stderr)
                    self.assertNotEqual("block", json.loads(result.stdout).get("decision"))
            with self.subTest(event=event, state="cap-reached"):
                result = self.hook({"event": event, "hasGaps": True, "continuationCount": 2})
                self.assertEqual(0, result.returncode, result.stderr)
                payload = json.loads(result.stdout)
                self.assertNotEqual("block", payload.get("decision"), payload)
                self.assertFalse(payload.get("continue", True), payload)

    def test_permission_request_uses_event_specific_decision_output(self):
        result = self.hook({
            "event": "PermissionRequest",
            "command": "Get-Content .env",
        })
        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        specific = payload.get("hookSpecificOutput", {})
        self.assertEqual("PermissionRequest", specific.get("hookEventName"))
        self.assertEqual("deny", specific.get("decision", {}).get("behavior"))
        self.assertTrue(specific.get("decision", {}).get("message"))
        self.assertNotIn("deny", payload)

    def test_pre_tool_use_uses_permission_decision_output(self):
        result = self.hook({
            "event": "PreToolUse",
            "command": "Get-Content .env",
        })
        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        specific = payload.get("hookSpecificOutput", {})
        self.assertEqual("PreToolUse", specific.get("hookEventName"))
        self.assertEqual("deny", specific.get("permissionDecision"))
        self.assertTrue(specific.get("permissionDecisionReason"))
        self.assertNotEqual("block", payload.get("decision"))

    def test_pre_tool_use_denies_quoted_reordered_recursive_root_delete(self):
        commands = [
            r"Remove-Item -LiteralPath 'C:\' -Force -Recurse",
        ]
        with self.temp_dir() as directory:
            fake_root = str(Path(directory).resolve())
            commands.append(
                f"Remove-Item -LiteralPath '{fake_root}' -Force -Recurse"
            )
            for command in commands:
                with self.subTest(command=command):
                    result = self.hook({
                        "event": "PreToolUse",
                        "tool_name": "Bash",
                        "command": command,
                        "workspaceRoot": fake_root,
                    })
                    self.assertEqual(0, result.returncode, result.stderr)
                    payload = json.loads(result.stdout)
                    specific = payload.get("hookSpecificOutput", {})
                    denied = (
                        payload.get("deny") is True
                        or specific.get("permissionDecision") == "deny"
                    )
                    self.assertTrue(denied, payload)
            self.assertTrue(Path(fake_root).is_dir(), "Hook test must never execute the delete command")

    def test_pre_tool_use_denies_direct_core_file_write_tools(self):
        core = ".agents/skills/orchestrating-workers-group/scripts/validate_transition.py"
        cases = (
            (
                "apply_patch",
                {"patch": f"*** Begin Patch\n*** Update File: {core}\n@@\n-old\n+new\n*** End Patch"},
            ),
            (
                "Edit",
                {"file_path": core, "old_string": "old", "new_string": "new"},
            ),
            (
                "Write",
                {"file_path": core, "content": "harmless red-control text"},
            ),
        )
        for tool_name, tool_input in cases:
            with self.subTest(tool_name=tool_name):
                result = self.hook({
                    "event": "PreToolUse",
                    "tool_name": tool_name,
                    "tool_input": tool_input,
                })
                self.assertEqual(0, result.returncode, result.stderr)
                payload = json.loads(result.stdout)
                specific = payload.get("hookSpecificOutput", {})
                denied = (
                    payload.get("deny") is True
                    or specific.get("permissionDecision") == "deny"
                )
                self.assertTrue(denied, payload)

    def test_pre_tool_use_denies_runtime_governance_file_writes(self):
        runtime_root = SCRIPTS.parents[2]
        for target in (
            SCRIPTS.parent / "SKILL.md",
            runtime_root / "agents" / "workers_qa.toml",
        ):
            with self.subTest(target=target):
                result = self.hook({
                    "event": "PreToolUse",
                    "tool_name": "Write",
                    "tool_input": {"file_path": str(target), "content": "red control"},
                })
                self.assertEqual(0, result.returncode, result.stderr)
                specific = json.loads(result.stdout).get("hookSpecificOutput", {})
                self.assertEqual("deny", specific.get("permissionDecision"), result.stdout)

    def test_runtime_active_task_gaps_are_probed_by_stop_gate(self):
        with self.temp_dir() as directory:
            root = Path(directory)
            (root / ".git").mkdir()
            runtime = root / ".workers-group" / "runtime"
            runtime.mkdir(parents=True)
            (runtime / "active-task.json").write_text(
                json.dumps({
                    "task_id": "WG-runtime-probe",
                    "status": "EXECUTING",
                    "missing_evidence": ["evidence/qa.txt"],
                }),
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(SCRIPTS / "workers_group_hook.py")],
                input=json.dumps({
                    "event": "Stop",
                    "sessionId": "runtime-probe",
                    "continuationCount": 0,
                }),
                text=True,
                encoding="utf-8",
                capture_output=True,
                cwd=root,
                timeout=10,
                env={**os.environ, "PYTHONUTF8": "1"},
            )
            self.assertEqual(0, result.returncode, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload.get("hasGaps"), payload)
            self.assertEqual("block", payload.get("decision"), payload)

    def test_subagent_stop_validates_schema_task_role_commands_tests_and_repo_evidence(self):
        with self.temp_dir() as directory:
            root = Path(directory)
            (root / ".git").mkdir()
            runtime = root / ".workers-group" / "runtime"
            runtime.mkdir(parents=True)
            task_id = "WG-hook-completion"
            (runtime / "active-task.json").write_text(
                json.dumps({"task_id": task_id, "status": "CLOSED"}),
                encoding="utf-8",
            )
            (root / "artifact.txt").write_text("verified", encoding="utf-8")
            valid = self._role_report(
                task_id, "workers_executor", "EVIDENCE_REVIEW", ["artifact.txt"],
            )
            result = self._run_hook(root, {
                "event": "SubagentStop",
                "agent_type": "workers_executor",
                "report": valid,
                "continuationCount": 0,
            })
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertFalse(json.loads(result.stdout)["hasGaps"], result.stdout)

            invalid = dict(valid)
            invalid["task_id"] = "WG-other-task"
            invalid["commands_run"] = [{"exit_code": 0}]
            invalid["tests"] = [{"command": "python -m unittest", "passed": 1, "failed": 0}]
            invalid["evidence"] = [str(root.parent / "outside.txt")]
            result = self._run_hook(root, {
                "event": "SubagentStop",
                "agent_type": "workers_executor",
                "report": invalid,
                "continuationCount": 0,
            })
            payload = json.loads(result.stdout)
            self.assertTrue(payload["hasGaps"], payload)
            self.assertEqual("block", payload["decision"])
            self.assertTrue(payload.get("reportValidationErrors"), payload)

    def test_qa_and_boss_completion_use_role_specific_reports_and_nested_evidence_gate(self):
        with self.temp_dir() as directory:
            root = Path(directory)
            (root / ".git").mkdir()
            runtime = root / ".workers-group" / "runtime"
            runtime.mkdir(parents=True)
            task_id = "WG-hook-role-gates"
            state_dir = root / ".workers-group" / "state"
            state_dir.mkdir(parents=True)
            (root / "artifact.txt").write_text("verified", encoding="utf-8")
            (state_dir / "AC-001.json").write_text(json.dumps({
                "id": "AC-001",
                "requirement": "Hook completion is verified.",
                "validation_method": "Run hook completion test.",
                "required_evidence": ["artifact.txt"],
                "owner": "workers_qa",
                "status": "PASS",
                "evidence": ["artifact.txt"],
                "verdict": "PASS",
            }), encoding="utf-8")
            (runtime / "active-task.json").write_text(
                json.dumps({
                    "task_id": task_id,
                    "status": "CLOSED",
                    "acceptance_criteria": [{
                        "task_id": task_id,
                        "path": ".workers-group/state/AC-001.json",
                    }],
                    "evidence": ["artifact.txt"],
                    "failed_tests": [],
                    "boss_reviewed": True,
                    "scope_drift_checked": True,
                    "scope_drift": [],
                    "limitations_disclosed": True,
                    "skill_migration_complete": True,
                    "pending_skill_migrations": [],
                    "self_improvement_verified": True,
                }),
                encoding="utf-8",
            )
            qa = self._qa_report(task_id, ["artifact.txt"])
            boss = self._role_report(task_id, "workers_boss", "CLOSED", ["artifact.txt"])

            qa_result = self._run_hook(root, {
                "event": "SubagentStop",
                "agent_type": "workers_qa",
                "report": qa,
                "continuationCount": 0,
            })
            self.assertFalse(json.loads(qa_result.stdout)["hasGaps"], qa_result.stdout)

            boss_result = self._run_hook(root, {
                "event": "Stop",
                "role": "workers_boss",
                "report": boss,
                "qaReport": qa,
                "continuationCount": 0,
            })
            self.assertFalse(json.loads(boss_result.stdout)["hasGaps"], boss_result.stdout)

            missing_qa = self._run_hook(root, {
                "event": "Stop",
                "role": "workers_boss",
                "report": boss,
                "continuationCount": 0,
            })
            self.assertTrue(json.loads(missing_qa.stdout)["hasGaps"], missing_qa.stdout)

            nested_outside = self._qa_report(task_id, ["artifact.txt"])
            nested_outside["criteria_results"][0]["evidence"] = [
                str(root.parent / "outside.txt"),
            ]
            bad_qa = self._run_hook(root, {
                "event": "SubagentStop",
                "agent_type": "workers_qa",
                "report": nested_outside,
                "continuationCount": 0,
            })
            self.assertTrue(json.loads(bad_qa.stdout)["hasGaps"], bad_qa.stdout)

    def test_planner_and_pm_completion_require_acceptance_validation_and_transition_record(self):
        with self.temp_dir() as directory:
            root = Path(directory)
            (root / ".git").mkdir()
            runtime = root / ".workers-group" / "runtime"
            state_dir = root / ".workers-group" / "state"
            runtime.mkdir(parents=True)
            state_dir.mkdir(parents=True)
            task_id = "WG-hook-role-specific"
            (root / "artifact.txt").write_text("verified", encoding="utf-8")
            (state_dir / "AC-001.json").write_text(json.dumps({
                "id": "AC-001",
                "requirement": "Role-specific completion is testable.",
                "validation_method": "Run role-specific Hook test.",
                "required_evidence": ["artifact.txt"],
                "owner": "workers_qa",
                "status": "NOT_VERIFIED",
                "evidence": [],
                "verdict": "NOT_VERIFIED",
            }), encoding="utf-8")
            active = {
                "task_id": task_id,
                "status": "CLOSED",
                "acceptance_criteria": [{
                    "task_id": task_id,
                    "path": ".workers-group/state/AC-001.json",
                }],
            }
            (runtime / "active-task.json").write_text(json.dumps(active), encoding="utf-8")
            planner = self._role_report(
                task_id, "workers_planner", "PLANNING", ["artifact.txt"],
            )
            pm = self._role_report(
                task_id, "workers_pm", "BOSS_REVIEW", ["artifact.txt"],
            )

            planner_result = self._run_hook(root, {
                "event": "SubagentStop",
                "agent_type": "workers_planner",
                "report": planner,
                "continuationCount": 0,
            })
            self.assertFalse(json.loads(planner_result.stdout)["hasGaps"], planner_result.stdout)

            pm_missing = self._run_hook(root, {
                "event": "SubagentStop",
                "agent_type": "workers_pm",
                "report": pm,
                "continuationCount": 0,
            })
            self.assertTrue(json.loads(pm_missing.stdout)["hasGaps"], pm_missing.stdout)
            pm_valid = self._run_hook(root, {
                "event": "SubagentStop",
                "agent_type": "workers_pm",
                "report": pm,
                "transitionRecord": {
                    "task_id": task_id,
                    "from_status": "QA",
                    "to_status": "BOSS_REVIEW",
                },
                "continuationCount": 0,
            })
            self.assertFalse(json.loads(pm_valid.stdout)["hasGaps"], pm_valid.stdout)
            transition_log = runtime / "transition-audit.jsonl"
            transition_log.write_text(
                "x" * 1100000 + "\n" + json.dumps({
                    "task_id": task_id,
                    "from_status": "QA",
                    "to_status": "BOSS_REVIEW",
                }) + "\n",
                encoding="utf-8",
            )
            bounded_log = self._run_hook(root, {
                "event": "SubagentStop",
                "agent_type": "workers_pm",
                "report": pm,
                "transitionRecord": ".workers-group/runtime/transition-audit.jsonl",
                "continuationCount": 0,
            })
            self.assertFalse(json.loads(bounded_log.stdout)["hasGaps"], bounded_log.stdout)

    def test_stop_reports_each_exact_completion_gap_deterministically(self):
        with self.temp_dir() as directory:
            root = Path(directory)
            (root / ".git").mkdir()
            runtime = root / ".workers-group" / "runtime"
            runtime.mkdir(parents=True)
            task_id = "WG-hook-exact-gaps"
            (root / "artifact.txt").write_text("verified", encoding="utf-8")
            (runtime / "active-task.json").write_text(json.dumps({
                "task_id": task_id,
                "status": "FAILED",
                "acceptance_criteria": [],
                "failed_tests": ["test_failure"],
                "evidence": [],
                "boss_reviewed": False,
                "scope_drift": ["unapproved-file.txt"],
                "pending_skill_migrations": ["schema-v4"],
            }), encoding="utf-8")
            boss = self._role_report(task_id, "workers_boss", "CLOSED", ["artifact.txt"])
            qa = self._qa_report(task_id, ["artifact.txt"])
            result = self._run_hook(root, {
                "event": "Stop",
                "role": "workers_boss",
                "report": boss,
                "qaReport": qa,
                "continuationCount": 0,
            })
            payload = json.loads(result.stdout)
            errors = "\n".join(payload["reportValidationErrors"])
            for fragment in (
                "FAILED", "acceptance_criteria", "failed_tests", "evidence",
                "boss_reviewed", "scope_drift_checked", "scope_drift",
                "limitations_disclosed", "skill_migration_complete",
                "self_improvement_verified",
            ):
                with self.subTest(fragment=fragment):
                    self.assertIn(fragment, errors)

    def test_session_start_integrity_bounded_queue_and_role_scoped_active_memory_retrieval(self):
        memory_module = self.source_module("memory_store.py")
        with self.temp_dir() as directory:
            root = Path(directory)
            (root / ".git").mkdir()
            runtime = root / ".workers-group" / "runtime"
            runtime.mkdir(parents=True)
            task_id = "WG-hook-memory"
            (runtime / "active-task.json").write_text(
                json.dumps({"task_id": task_id, "status": "CLOSED", "objective": "hook memory"}),
                encoding="utf-8",
            )
            evidence = root / "memory-evidence.txt"
            evidence.write_text("verified", encoding="utf-8")
            store = memory_module.MemoryStore(runtime / "memory.sqlite3")
            memory_id = store.add_candidate({
                "id": "WG-HOOK-ACTIVE-MEMORY",
                "title": "Hook memory",
                "summary": "Hook lifecycle retrieval",
                "content": "hook memory lifecycle context",
                "source": "test",
                "sourceTaskId": task_id,
                "sourceRole": "workers_boss",
                "memoryType": "SEMANTIC",
                "scope": "repository",
                "confidence": 1.0,
                "evidence": ["memory-evidence.txt"],
            })
            reviewer = {
                "reviewer": "workers_boss",
                "memory_id": memory_id,
                "verdict": "APPROVED",
                "evidence": ["memory-evidence.txt"],
            }
            store.review(memory_id, "ACTIVE", actor="workers_boss", reviewer_artifact=reviewer)
            queue = runtime / "pending-memory-queue.jsonl"
            queue.write_text("".join(
                json.dumps({
                    "id": f"WG-PENDING-{index}",
                    "content": f"pending lifecycle memory {index}",
                    "source": "test",
                }) + "\n"
                for index in range(10)
            ), encoding="utf-8")

            result = self._run_hook(root, {
                "event": "SessionStart",
                "sessionId": "hook-memory",
                "role": "workers_planner",
            })
            self.assertEqual(0, result.returncode, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["memoryIntegrity"]["ok"], payload)
            self.assertEqual(8, payload["pendingMemoryProcessed"], payload)
            self.assertEqual(2, len(queue.read_text(encoding="utf-8").splitlines()))
            retrieval = payload["memoryRetrieval"]
            self.assertEqual("workers_planner", retrieval["role"])
            self.assertEqual(task_id, retrieval["task_id"])
            self.assertIn(memory_id, [item["id"] for item in retrieval["items"]])

    def test_session_start_reports_corrupt_memory_without_polluting_stdout(self):
        with self.temp_dir() as directory:
            root = Path(directory)
            (root / ".git").mkdir()
            runtime = root / ".workers-group" / "runtime"
            runtime.mkdir(parents=True)
            database = runtime / "memory.sqlite3"
            database.write_bytes(b"not-a-sqlite-database")
            result = self._run_hook(root, {
                "event": "SessionStart",
                "sessionId": "corrupt-memory",
                "role": "workers_boss",
            })
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(1, len(result.stdout.strip().splitlines()), result.stdout)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["memoryIntegrity"]["ok"], payload)
            self.assertTrue(payload["persistenceError"], payload)
            self.assertTrue(list(runtime.glob("memory.sqlite3.corrupt.*.bak")))

    def test_prompt_registers_charter_and_subagent_start_retrieves_role_memory(self):
        with self.temp_dir() as directory:
            root = Path(directory)
            (root / ".git").mkdir()
            prompt = "請使用 $orchestrating-workers-group 實作 hook lifecycle memory"
            submitted = self._run_hook(root, {
                "event": "UserPromptSubmit",
                "prompt": prompt,
            })
            self.assertEqual(0, submitted.returncode, submitted.stderr)
            payload = json.loads(submitted.stdout)
            self.assertTrue(payload["governanceStarted"], payload)
            self.assertTrue(payload["taskCharterRegistered"], payload)
            task_id = payload["taskId"]
            self.assertTrue((root / ".workers-group" / "state" / f"{task_id}.task-charter.json").is_file())
            self.assertEqual(
                task_id,
                json.loads((root / ".workers-group" / "runtime" / "active-task.json").read_text(encoding="utf-8"))["task_id"],
            )
            self.assertEqual(task_id, payload["memoryRetrieval"]["task_id"])

            started = self._run_hook(root, {
                "event": "SubagentStart",
                "agent_type": "workers_executor",
            })
            context = json.loads(json.loads(started.stdout)["hookSpecificOutput"]["additionalContext"])
            self.assertEqual("workers_executor", context["memory_retrieval"]["role"])
            self.assertEqual(task_id, context["memory_retrieval"]["task_id"])

    def test_session_end_updates_active_metadata_and_queues_only_sanitized_doctor_trigger(self):
        with self.temp_dir() as directory:
            root = Path(directory)
            (root / ".git").mkdir()
            runtime = root / ".workers-group" / "runtime"
            runtime.mkdir(parents=True)
            task_id = "WG-hook-session-end"
            active_path = runtime / "active-task.json"
            active_path.write_text(
                json.dumps({"task_id": task_id, "status": "CLOSED"}),
                encoding="utf-8",
            )
            no_trigger = self._run_hook(root, {
                "event": "SessionEnd",
                "sessionId": "no-trigger",
            })
            self.assertEqual(0, no_trigger.returncode, no_trigger.stderr)
            self.assertFalse(json.loads(no_trigger.stdout).get("memoryCandidateQueued", False))
            self.assertFalse((runtime / "pending-memory-queue.jsonl").exists())
            updated = json.loads(active_path.read_text(encoding="utf-8"))
            self.assertTrue(updated.get("last_session_ended_at"), updated)

            triggered = self._run_hook(root, {
                "event": "SessionEnd",
                "sessionId": "doctor-trigger",
                "skillDoctorTrigger": "statusMessage mismatch token=FAKE_SECRET_VALUE",
            })
            self.assertEqual(0, triggered.returncode, triggered.stderr)
            payload = json.loads(triggered.stdout)
            self.assertTrue(payload.get("memoryCandidateQueued"), payload)
            candidate = json.loads((runtime / "pending-memory-queue.jsonl").read_text(encoding="utf-8"))
            self.assertEqual("SKILL_EVOLUTION", candidate["memoryType"])
            self.assertNotIn("FAKE_SECRET_VALUE", json.dumps(candidate))

    def test_session_end_is_lightweight_and_simple_work_does_not_start_all_roles(self):
        with self.temp_dir() as directory:
            root = Path(directory)
            (root / ".git").mkdir()
            simple = self._run_hook(root, {
                "event": "UserPromptSubmit",
                "prompt": "將 hello 翻譯成中文",
            })
            self.assertEqual(0, simple.returncode, simple.stderr)
            self.assertNotIn("workers_planner", json.dumps(json.loads(simple.stdout), ensure_ascii=False))
            end = self._run_hook(root, {"event": "SessionEnd", "sessionId": "test-1"})
            self.assertEqual(0, end.returncode, end.stderr)
            self.assertLessEqual(len(end.stdout), 2048)

    def test_explicit_invocation_starts_governance(self):
        with self.temp_dir() as directory:
            root = Path(directory)
            (root / ".git").mkdir()
            result = self._run_hook(root, {
                "event": "UserPromptSubmit",
                "prompt": "請使用 $orchestrating-workers-group 處理此工作",
            })
            self.assertEqual(0, result.returncode, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload.get("governanceStarted"), payload)

    def test_complex_multistage_prompt_starts_governance_without_literal_skill_token(self):
        prompt = (
            "請規劃並實作跨模組資料遷移：先盤點相依性與風險，分派獨立實作者，"
            "保存每步測試證據，再由獨立 QA 驗證與 Boss 審查後才能完成。"
        )
        self.assertNotIn("$orchestrating-workers-group", prompt)
        with self.temp_dir() as directory:
            root = Path(directory)
            (root / ".git").mkdir()
            result = self._run_hook(root, {"event": "UserPromptSubmit", "prompt": prompt})
            self.assertEqual(0, result.returncode, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload.get("governanceStarted"), payload)
            self.assertEqual(
                {"workers_boss", "workers_planner", "workers_pm", "workers_executor", "workers_qa"},
                set(payload.get("roles", [])),
            )
