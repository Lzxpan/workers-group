import json
import subprocess
import sys
from pathlib import Path

from test_support import ROOT, SCRIPTS, WorkersGroupTestCase


class StateStoreTests(WorkersGroupTestCase):
    def test_atomic_write_and_missing_directory_creation(self):
        module = self.source_module("state_store.py")
        with self.temp_dir() as directory:
            path = Path(directory) / "missing" / "state.json"
            store = module.StateStore(path)
            store.write_state({"status": "PLANNED"})
            self.assertEqual({"status": "PLANNED"}, store.read_state())
            self.assertFalse(list(path.parent.glob("*.tmp")))

    def test_git_root_is_discovered_from_a_nested_directory(self):
        module = self.source_module("state_store.py")
        with self.temp_dir() as directory:
            root = Path(directory)
            (root / ".git").mkdir()
            nested = root / "a" / "b"
            nested.mkdir(parents=True)
            self.assertEqual(root, module.find_git_root(nested))

    def test_concurrent_file_ownership_is_rejected(self):
        module = self.source_module("state_store.py")
        with self.temp_dir() as directory:
            store = module.StateStore(Path(directory) / "state.json")
            store.claim_files("workers_executor", ["owned.py"])
            with self.assertRaises((ValueError, RuntimeError)):
                store.claim_files("workers_qa", ["owned.py"])

    def test_create_task_and_state_persistence_do_not_store_secret_or_pii_markers(self):
        module = self.source_module("state_store.py")
        markers = (
            "sk-test-not-a-real-secret",
            "worker-red-control@example.com",
        )
        for marker in markers:
            with self.subTest(component="state_store", marker=marker), self.temp_dir() as directory:
                path = Path(directory) / "state.json"
                store = module.StateStore(path)
                try:
                    store.write_state({"request": marker})
                except ValueError:
                    pass
                else:
                    self.assertNotIn(marker, path.read_text(encoding="utf-8"))

            with self.subTest(component="create_task", marker=marker), self.temp_dir() as directory:
                root = Path(directory)
                request = root / "request.txt"
                output = root / "task.json"
                request.write_text(f"Process this fake fixture: {marker}", encoding="utf-8")
                result = subprocess.run(
                    [
                        sys.executable, str(SCRIPTS / "create_task.py"),
                        "--title", "Security red control",
                        "--request-file", str(request),
                        "--output", str(output),
                    ],
                    cwd=ROOT,
                    text=True,
                    capture_output=True,
                    timeout=15,
                )
                if result.returncode == 0:
                    self.assertTrue(output.is_file(), result.stdout)
                    self.assertNotIn(marker, output.read_text(encoding="utf-8"))
                else:
                    diagnostic = json.loads(result.stdout)
                    self.assertFalse(diagnostic.get("valid", True), diagnostic)

    def test_create_task_registers_active_task_and_session_start_loads_same_task(self):
        with self.temp_dir() as directory:
            root = Path(directory)
            (root / ".git").mkdir()
            request = root / "request.txt"
            output = root / ".workers-group" / "state" / "task-charter.json"
            request.write_text(
                "Plan and verify a complex multi-stage fake repository migration.",
                encoding="utf-8",
            )
            create = subprocess.run(
                [
                    sys.executable, str(SCRIPTS / "create_task.py"),
                    "--title", "Active task registration red control",
                    "--request-file", str(request),
                    "--output", str(output),
                ],
                cwd=root,
                text=True,
                capture_output=True,
                timeout=15,
            )
            self.assertEqual(0, create.returncode, create.stderr or create.stdout)
            created = json.loads(create.stdout)
            active_path = root / ".workers-group" / "runtime" / "active-task.json"
            self.assertTrue(active_path.is_file(), created)
            active = json.loads(active_path.read_text(encoding="utf-8"))
            self.assertEqual(created["task_id"], active.get("task_id"), active)

            session = subprocess.run(
                [sys.executable, "-X", "utf8", str(SCRIPTS / "workers_group_hook.py")],
                input=json.dumps({"event": "SessionStart", "sessionId": "active-task-red-control"}),
                cwd=root,
                text=True,
                capture_output=True,
                timeout=15,
            )
            self.assertEqual(0, session.returncode, session.stderr)
            payload = json.loads(session.stdout)
            self.assertEqual(created["task_id"], payload.get("activeTask", {}).get("task_id"), payload)
