from pathlib import Path

from test_support import WorkersGroupTestCase


class MemoryConflictTests(WorkersGroupTestCase):
    def test_conflicting_candidate_is_quarantined_and_not_retrieved(self):
        module = self.source_module("memory_store.py")
        with self.temp_dir() as directory:
            store = module.MemoryStore(Path(directory) / "memory.sqlite3")
            store.initialize()
            evidence = Path(directory) / "conflict-evidence.txt"
            evidence.write_text("obvious fake conflict evidence\n", encoding="utf-8")
            active = store.add_candidate({
                "key": "policy", "content": "allow", "source": "test",
                "source_task_id": "task-memory-conflict", "source_role": "workers_executor",
                "evidence": [str(evidence)],
                "scope": "repository", "confidence": 0.9,
            })
            try:
                store.review(
                    active, "ACTIVE", actor="workers_boss",
                    reviewer_artifact={
                        "actor": "workers_boss",
                        "memory_id": active,
                        "verdict": "PASS",
                        "evidence": [str(evidence)],
                    },
                )
            except TypeError as exc:
                self.fail(f"MemoryStore.review must accept reviewer_artifact: {exc}")
            conflict = store.add_candidate({"key": "policy", "content": "deny", "source": "test"})
            self.assertEqual("QUARANTINED", store.get(conflict)["status"])
            self.assertFalse(any(x["id"] == conflict for x in store.retrieve("policy")))
