import json
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

from test_support import ROOT, SCRIPTS, WorkersGroupTestCase


class MemoryRetrievalTests(WorkersGroupTestCase):
    def test_candidate_must_be_reviewed_before_active_and_duplicates_are_rejected(self):
        module = self.source_module("memory_store.py")
        with self.temp_dir() as directory:
            store = module.MemoryStore(Path(directory) / "memory.sqlite3")
            store.initialize()
            evidence = self._write_evidence(Path(directory))
            item = store.add_candidate(self._active_candidate("unique policy", evidence))
            self.assertEqual([], store.retrieve("policy"))
            self._review(
                store,
                item, "ACTIVE", actor="workers_qa",
                reviewer_artifact=self._reviewer_artifact("workers_qa", item, evidence),
            )
            self.assertEqual(1, len(store.retrieve("policy")))
            with self.assertRaises((ValueError, RuntimeError)):
                store.add_candidate(self._active_candidate("unique policy", evidence))

    def test_active_review_requires_authorized_actor_and_complete_provenance_gate(self):
        module = self.source_module("memory_store.py")
        with self.temp_dir() as directory:
            store = module.MemoryStore(Path(directory) / "memory.sqlite3")
            store.initialize()
            evidence = self._write_evidence(Path(directory))
            for actor in ("workers_planner", "workers_pm", "workers_executor"):
                with self.subTest(unauthorized_actor=actor):
                    item = store.add_candidate(self._active_candidate(f"unauthorized {actor}", evidence))
                    with self.assertRaises((ValueError, PermissionError, RuntimeError)):
                        self._review(
                            store,
                            item, "ACTIVE", actor=actor,
                            reviewer_artifact=self._reviewer_artifact(actor, item, evidence),
                        )

            required = ("source_task_id", "source_role", "evidence", "scope", "confidence")
            for field in required:
                with self.subTest(missing=field):
                    candidate = self._active_candidate(f"missing {field}", evidence)
                    candidate.pop(field)
                    candidate_id = store.add_candidate(candidate)
                    with self.assertRaises((ValueError, PermissionError, RuntimeError)):
                        self._review(
                            store,
                            candidate_id, "ACTIVE", actor="workers_boss",
                            reviewer_artifact=self._reviewer_artifact(
                                "workers_boss", candidate_id, evidence,
                            ),
                        )

            for evidence in ([], [""], [{"path": "evidence/not-a-string.txt"}]):
                with self.subTest(invalid_evidence=evidence):
                    candidate = self._active_candidate(f"invalid evidence {evidence!r}", evidence)
                    candidate_id = store.add_candidate(candidate)
                    with self.assertRaises((ValueError, PermissionError, RuntimeError)):
                        self._review(
                            store,
                            candidate_id, "ACTIVE", actor="workers_qa",
                            reviewer_artifact=self._reviewer_artifact(
                                "workers_qa", candidate_id, self._write_evidence(Path(directory)),
                            ),
                        )

    def test_active_requires_bound_reviewer_artifact_and_readable_evidence(self):
        module = self.source_module("memory_store.py")
        with self.temp_dir() as directory:
            root = Path(directory)
            store = module.MemoryStore(root / "memory.sqlite3")
            evidence = self._write_evidence(root)
            other_evidence = root / "other-review-evidence.txt"
            other_evidence.write_text("readable but not bound to candidate\n", encoding="utf-8")

            caller_only = store.add_candidate(self._active_candidate("caller label only", evidence))
            with self.subTest(case="caller-label-only"):
                with self.assertRaises((ValueError, PermissionError, RuntimeError)):
                    store.review(caller_only, "ACTIVE", actor="workers_qa")

            invalid_artifacts = (
                {"actor": "workers_boss"},
                {"memory_id": "different-memory"},
                {"verdict": "FAIL"},
                {"evidence": [str(root / "missing-review-evidence.txt")]},
                {"evidence": [str(other_evidence)]},
            )
            for override in invalid_artifacts:
                with self.subTest(override=override):
                    item = store.add_candidate(
                        self._active_candidate(f"invalid reviewer artifact {override!r}", evidence)
                    )
                    artifact = {
                        **self._reviewer_artifact("workers_qa", item, evidence),
                        **override,
                    }
                    with self.assertRaises((ValueError, PermissionError, RuntimeError, TypeError)):
                        self._review(
                            store,
                            item, "ACTIVE", actor="workers_qa",
                            reviewer_artifact=artifact,
                        )

            item = store.add_candidate(self._active_candidate("valid reviewer artifact", evidence))
            result = self._review(
                store,
                item, "ACTIVE", actor="workers_boss",
                reviewer_artifact=self._reviewer_artifact("workers_boss", item, evidence),
            )
            self.assertEqual("ACTIVE", result["status"])

    def test_memory_review_cli_requires_explicit_authorized_actor(self):
        module = self.source_module("memory_store.py")
        script = SCRIPTS / "memory_store.py"
        cases = ((None, False), ("workers_boss", True), ("workers_qa", True), ("workers_pm", False))
        for actor, should_succeed in cases:
            with self.subTest(actor=actor), self.temp_dir() as directory:
                db = Path(directory) / "memory.sqlite3"
                store = module.MemoryStore(db)
                evidence = self._write_evidence(Path(directory))
                item = store.add_candidate(self._active_candidate(f"CLI actor {actor!r}", evidence))
                command = [
                    sys.executable, str(script), "review", "--db", str(db),
                    "--memory-id", item, "--status", "ACTIVE",
                ]
                if actor is not None:
                    command.extend(("--actor", actor))
                artifact_actor = actor or "workers_qa"
                artifact_path = Path(directory) / "review-artifact.json"
                artifact_path.write_text(
                    json.dumps(self._reviewer_artifact(artifact_actor, item, evidence)),
                    encoding="utf-8",
                )
                command.extend(("--review-artifact", str(artifact_path)))
                result = subprocess.run(
                    command, cwd=ROOT, text=True, capture_output=True, timeout=15,
                )
                self.assertEqual(should_succeed, result.returncode == 0, result.stderr or result.stdout)

    @staticmethod
    def _active_candidate(content, evidence):
        return {
            "content": content,
            "source": "test",
            "source_task_id": "task-memory-red-control",
            "source_role": "workers_executor",
            "evidence": list(evidence) if isinstance(evidence, list) else [str(evidence)],
            "scope": "repository",
            "confidence": 0.9,
        }

    @staticmethod
    def _write_evidence(root):
        evidence = root / "memory-evidence.txt"
        evidence.write_text("obvious fake memory evidence\n", encoding="utf-8")
        return str(evidence)

    @staticmethod
    def _reviewer_artifact(actor, memory_id, evidence):
        return {
            "actor": actor,
            "memory_id": memory_id,
            "verdict": "PASS",
            "evidence": [str(evidence)],
        }

    def _review(self, store, memory_id, status, *, actor, reviewer_artifact):
        try:
            return store.review(
                memory_id, status, actor=actor, reviewer_artifact=reviewer_artifact,
            )
        except TypeError as exc:
            self.fail(f"MemoryStore.review must accept reviewer_artifact: {exc}")

    def test_ranking_budget_and_retrieval_ledger(self):
        module = self.source_module("memory_retriever.py")
        with self.temp_dir() as directory:
            retriever = module.MemoryRetriever(Path(directory) / "memory.sqlite3")
            result = retriever.retrieve("hooks governance", budget_tokens=8)
            self.assertLessEqual(sum(entry["tokenCount"] for entry in result["items"]), 8)
            self.assertTrue(result["ledger"])
            self.assertTrue(all("score" in entry for entry in result["items"]))

    def test_fts_fallback_and_superseded_or_stale_exclusion(self):
        module = self.source_module("memory_retriever.py")
        with self.temp_dir() as directory:
            retriever = module.MemoryRetriever(Path(directory) / "memory.sqlite3", force_fallback=True)
            result = retriever.retrieve("alpha token", budget_tokens=100)
            self.assertEqual("token-overlap", result["strategy"])
            self.assertFalse(any(x.get("status") in {"SUPERSEDED", "STALE"} for x in result["items"]))

    def test_feedback_updates_ledger_and_memory_counters_atomically(self):
        module = self.source_module("memory_retriever.py")
        with self.temp_dir() as directory:
            root = Path(directory)
            evidence = self._write_evidence(root)
            retriever = module.MemoryRetriever(
                root / "memory.sqlite3", force_fallback=True,
            )
            memory_id = retriever.store.add_candidate(
                self._active_candidate("feedback ranking control", evidence),
            )
            self._review(
                retriever.store,
                memory_id,
                "ACTIVE",
                actor="workers_qa",
                reviewer_artifact=self._reviewer_artifact(
                    "workers_qa", memory_id, evidence,
                ),
            )
            retrieval = retriever.retrieve("feedback ranking control")
            score_before_feedback = retrieval["items"][0]["score"]
            result = retriever.record_feedback(
                retrieval["ledger"],
                usage="USED",
                outcome="SUCCESS",
                helpful=True,
                evidence=[evidence],
            )
            self.assertTrue(result["recorded"], result)
            with closing(sqlite3.connect(retriever.store.db_path)) as connection:
                ledger = connection.execute(
                    "SELECT usage,outcome,helpful,evidence_json FROM retrieval_ledger WHERE id=?",
                    (retrieval["ledger"],),
                ).fetchone()
                counters = connection.execute(
                    "SELECT useful_count,harmful_count FROM memories WHERE id=?",
                    (memory_id,),
                ).fetchone()
            self.assertEqual(("USED", "SUCCESS", 1), ledger[:3])
            self.assertEqual([evidence], json.loads(ledger[3]))
            self.assertEqual((1, 0), counters)
            score_after_feedback = retriever.retrieve(
                "feedback ranking control",
            )["items"][0]["score"]
            self.assertGreater(score_after_feedback, score_before_feedback)
            with self.assertRaises((ValueError, RuntimeError)):
                retriever.record_feedback(
                    retrieval["ledger"],
                    usage="USED",
                    outcome="SUCCESS",
                    helpful=True,
                    evidence=[evidence],
                )

            unsafe = retriever.retrieve("feedback ranking control")
            with self.assertRaises((ValueError, RuntimeError)):
                retriever.record_feedback(
                    unsafe["ledger"],
                    usage="Bearer not-a-real-feedback-secret",
                    outcome="FAILURE",
                    helpful=False,
                    evidence=[evidence],
                )
            with closing(sqlite3.connect(retriever.store.db_path)) as connection:
                self.assertEqual(
                    (1, 0),
                    connection.execute(
                        "SELECT useful_count,harmful_count FROM memories WHERE id=?",
                        (memory_id,),
                    ).fetchone(),
                )

    def test_feedback_cli_and_conflict_staleness_history_weights_are_live(self):
        module = self.source_module("memory_retriever.py")
        with self.temp_dir() as directory:
            root = Path(directory)
            evidence = self._write_evidence(root)
            retriever = module.MemoryRetriever(
                root / "memory.sqlite3", force_fallback=True,
            )
            preferred = retriever.store.add_candidate({
                **self._active_candidate("policy ranking preferred", evidence),
                "id": "preferred-memory",
                "module": "memory",
                "tags": [
                    "language:python",
                    "framework:stdlib",
                    "error:database-corruption",
                    "tool:sqlite3",
                    "task-type:recovery",
                    "ac:preserve-data",
                    "role:workers_qa",
                ],
            })
            penalized = retriever.store.add_candidate({
                **self._active_candidate("policy ranking penalized", evidence),
                "id": "penalized-memory",
            })
            with retriever.store._connection() as connection:
                connection.execute(
                    """
                    UPDATE memories SET status='ACTIVE', useful_count=5,
                        success_count=3 WHERE id=?
                    """,
                    (preferred,),
                )
                connection.execute(
                    """
                    UPDATE memories SET status='ACTIVE', harmful_count=5,
                        failure_count=3, expires_at='2000-01-01T00:00:00+00:00'
                    WHERE id=?
                    """,
                    (penalized,),
                )
                connection.execute(
                    "INSERT INTO memory_relations(source_id,target_id,relation,created_at) VALUES (?,?,?,?)",
                    (
                        penalized, preferred, "CONFLICTS_WITH",
                        "2026-07-30T00:00:00+00:00",
                    ),
                )

            ranked = retriever.retrieve(
                "policy ranking",
                top_k=8,
                module="memory",
                role="workers_qa",
                language="python",
                framework="stdlib",
                error="database-corruption",
                tool="sqlite3",
                task_type="recovery",
                acceptance_criterion="preserve-data",
            )
            by_id = {item["id"]: item for item in ranked["items"]}
            self.assertGreater(
                by_id[preferred]["score"], by_id[penalized]["score"], by_id,
            )
            components = by_id[penalized]["scoreComponents"]
            self.assertGreater(components["conflictPenalty"], 0)
            self.assertGreater(components["stalenessPenalty"], 0)
            self.assertGreater(components["harmfulHistoryPenalty"], 0)
            self.assertGreater(
                by_id[preferred]["scoreComponents"]["helpfulHistory"],
                by_id[penalized]["scoreComponents"]["helpfulHistory"],
            )
            self.assertGreater(
                by_id[preferred]["scoreComponents"]["context"],
                by_id[penalized]["scoreComponents"]["context"],
            )

            cli_retrieval = retriever.retrieve("policy ranking preferred", top_k=1)
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "memory_retriever.py"),
                    "--db", str(retriever.store.db_path),
                    "--feedback-ledger", cli_retrieval["ledger"],
                    "--usage", "CITED",
                    "--outcome", "SUCCESS",
                    "--helpful", "true",
                    "--evidence", evidence,
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                timeout=15,
            )
            self.assertEqual(0, result.returncode, result.stderr or result.stdout)
            self.assertTrue(json.loads(result.stdout)["recorded"])
