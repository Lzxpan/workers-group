import json
import sqlite3
from contextlib import closing
from pathlib import Path
from unittest import mock

from test_support import WorkersGroupTestCase


class MemoryRepairTests(WorkersGroupTestCase):
    def test_damaged_jsonl_tail_is_recovered_without_losing_valid_records(self):
        module = self.source_module("memory_repair.py")
        with self.temp_dir() as directory:
            path = Path(directory) / "memory.jsonl"
            path.write_text('{"id":"one"}\n{"id":', encoding="utf-8")
            result = module.repair_jsonl(path)
            self.assertEqual(1, result["kept"])
            self.assertEqual(1, result["discardedTailLines"])
            self.assertEqual('{"id":"one"}\n', path.read_text(encoding="utf-8"))

    def test_db_corruption_refuses_write_creates_backup_and_detects_orphans(self):
        module = self.source_module("memory_repair.py")
        with self.temp_dir() as directory:
            root = Path(directory)
            db = root / "memory.sqlite3"
            db.write_bytes(b"not a sqlite database")
            result = module.recover_database(db, [{"id": "orphan", "contentHash": "wrong"}])
            self.assertFalse(result["writeAllowed"])
            self.assertTrue(Path(result["backupPath"]).is_file())
            self.assertIn("orphan", result["contentHashProblems"])

    def test_corrupt_database_is_rebuilt_atomically_from_complete_guarded_export(self):
        repair_module = self.source_module("memory_repair.py")
        store_module = self.source_module("memory_store.py")
        with self.temp_dir() as directory:
            root = Path(directory)
            db = root / "memory.sqlite3"
            export = root / "memory.jsonl"
            store = store_module.MemoryStore(db, export)
            first = store.add_candidate({
                "id": "memory-one",
                "key": "recovery",
                "content": "complete recovery provenance",
                "source": "test",
                "source_task_id": "WG-recovery-control-0123456789ab",
                "source_role": "workers_executor",
                "memoryType": "PROCEDURAL",
                "evidence": ["evidence/recovery.txt"],
                "scope": "repository",
                "confidence": 0.8,
            })
            second = store.add_candidate({
                "id": "memory-two",
                "content": "related recovery record",
                "source": "test",
            })
            with store._connection() as connection:
                connection.execute(
                    """
                    UPDATE memories SET status='ACTIVE', success_count=3, failure_count=1,
                        retrieval_count=4, useful_count=2, harmful_count=1,
                        last_verified_at='2026-07-29T00:00:00+00:00',
                        last_retrieved_at='2026-07-30T00:00:00+00:00',
                        expires_at='2027-07-30T00:00:00+00:00',
                        sensitivity='INTERNAL',
                        activation_json='{"reviewed":true}', version=7
                    WHERE id=?
                    """,
                    (first,),
                )
                connection.execute(
                    "INSERT INTO memory_relations(source_id,target_id,relation,created_at) VALUES (?,?,?,?)",
                    (first, second, "SUPPORTS", "2026-07-30T00:00:00+00:00"),
                )
                connection.execute(
                    """
                    INSERT INTO retrieval_ledger(
                        id,task_id,memory_id,query,role,retrieved_at,retrieval_score,
                        strategy,usage,outcome,helpful,evidence_json
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        "ledger-one", "WG-recovery-control-0123456789ab", first,
                        "recovery", "workers_planner", "2026-07-30T00:00:00+00:00",
                        0.9, "token-overlap", "USED", "SUCCESS", 1,
                        '["evidence/recovery.txt"]',
                    ),
                )
                connection.execute(
                    "INSERT INTO audit_log(event,memory_id,actor,details_json,created_at) VALUES (?,?,?,?,?)",
                    (
                        "RECOVERY_CONTROL", first, "workers_qa",
                        '{"evidence":["evidence/recovery.txt"]}',
                        "2026-07-30T00:00:00+00:00",
                    ),
                )

            store.export_jsonl()
            records = repair_module._load_jsonl(export)
            memory_record = next(record for record in records if record.get("id") == first)
            for field in (
                "sourceTaskId", "sourceRole", "sourceType", "memoryType",
                "successCount", "failureCount", "retrievalCount", "usefulCount",
                "harmfulCount", "lastVerifiedAt", "lastRetrievedAt", "expiresAt",
                "sensitivity", "activation", "version",
            ):
                self.assertIn(field, memory_record)

            corrupt_bytes = b"not a sqlite database - recovery control"
            db.write_bytes(corrupt_bytes)
            result = repair_module.recover_database(db, records, repair=True)
            self.assertTrue(result["writeAllowed"], result)
            self.assertTrue(result["databaseReplaced"], result)
            self.assertEqual("export", result["recoverySource"])
            self.assertEqual(corrupt_bytes, Path(result["backupPath"]).read_bytes())

            with closing(sqlite3.connect(db)) as connection:
                connection.row_factory = sqlite3.Row
                self.assertEqual("ok", connection.execute("PRAGMA integrity_check").fetchone()[0])
                restored = connection.execute(
                    "SELECT * FROM memories WHERE id=?", (first,),
                ).fetchone()
                self.assertEqual(
                    (3, 1, 4, 2, 1, 7, "PROCEDURAL"),
                    (
                        restored["success_count"], restored["failure_count"],
                        restored["retrieval_count"], restored["useful_count"],
                        restored["harmful_count"], restored["version"],
                        restored["memory_type"],
                    ),
                )
                self.assertEqual(
                    1, connection.execute("SELECT COUNT(*) FROM memory_relations").fetchone()[0],
                )
                self.assertEqual(
                    1, connection.execute("SELECT COUNT(*) FROM retrieval_ledger").fetchone()[0],
                )
                self.assertGreaterEqual(
                    connection.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0], 1,
                )

    def test_failed_export_recovery_never_replaces_corrupt_database_and_backup_wins(self):
        repair_module = self.source_module("memory_repair.py")
        store_module = self.source_module("memory_store.py")
        with self.temp_dir() as directory:
            root = Path(directory)
            db = root / "memory.sqlite3"
            store = store_module.MemoryStore(db)
            store.add_candidate({"id": "backup-memory", "content": "backup source", "source": "test"})
            explicit_backup = Path(store.backup(root / "known-good.sqlite3"))
            corrupt_bytes = b"original corrupt bytes must survive failed recovery"
            db.write_bytes(corrupt_bytes)
            invalid_export = [{
                "recordType": "memory",
                "id": "bad-export",
                "content": "tampered",
                "contentHash": "0" * 64,
                "source": "test",
                "status": "CANDIDATE",
                "createdAt": "2026-07-30T00:00:00+00:00",
                "updatedAt": "2026-07-30T00:00:00+00:00",
            }]

            failed = repair_module.recover_database(db, invalid_export, repair=True)
            self.assertFalse(failed["databaseReplaced"], failed)
            self.assertEqual(corrupt_bytes, db.read_bytes())
            self.assertTrue(Path(failed["backupPath"]).is_file())

            restored = repair_module.recover_database(
                db, invalid_export, backup_path=explicit_backup, repair=True,
            )
            self.assertTrue(restored["databaseReplaced"], restored)
            self.assertEqual("backup", restored["recoverySource"])
            with closing(sqlite3.connect(db)) as connection:
                self.assertEqual("ok", connection.execute("PRAGMA integrity_check").fetchone()[0])
                self.assertEqual(
                    1, connection.execute(
                        "SELECT COUNT(*) FROM memories WHERE id='backup-memory'",
                    ).fetchone()[0],
                )

    def test_locked_stale_sidecar_aborts_before_database_replacement(self):
        repair_module = self.source_module("memory_repair.py")
        store_module = self.source_module("memory_store.py")
        with self.temp_dir() as directory:
            root = Path(directory)
            db = root / "memory.sqlite3"
            export = root / "memory.jsonl"
            store = store_module.MemoryStore(db, export)
            store.add_candidate({
                "id": "sidecar-memory",
                "content": "sidecar replacement control",
                "source": "test",
            })
            store.export_jsonl()
            records = repair_module._load_jsonl(export)
            corrupt_bytes = b"corrupt database with stale sidecar"
            stale_wal = Path(f"{db}-wal")
            stale_bytes = b"stale wal must not attach to rebuilt database"
            db.write_bytes(corrupt_bytes)
            stale_wal.write_bytes(stale_bytes)

            real_replace = repair_module.os.replace

            def deny_sidecar_move(source, destination):
                if Path(source) == stale_wal:
                    raise PermissionError("simulated locked WAL")
                return real_replace(source, destination)

            with mock.patch.object(
                repair_module.os,
                "replace",
                side_effect=deny_sidecar_move,
            ):
                result = repair_module.recover_database(
                    db,
                    records,
                    repair=True,
                )

            self.assertFalse(result["databaseReplaced"], result)
            self.assertIn("PermissionError", result["recoveryError"])
            self.assertEqual(corrupt_bytes, db.read_bytes())
            self.assertEqual(stale_bytes, stale_wal.read_bytes())
