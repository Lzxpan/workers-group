import sqlite3
import json
from contextlib import closing
from pathlib import Path

from test_support import WorkersGroupTestCase


class MemoryStoreTests(WorkersGroupTestCase):
    def test_initialization_transactions_concurrent_writes_and_integrity(self):
        module = self.source_module("memory_store.py")
        with self.temp_dir() as directory:
            db = Path(directory) / "memory.sqlite3"
            first, second = module.MemoryStore(db), module.MemoryStore(db)
            first.initialize()
            first.add_candidate({"content": "alpha", "source": "test"})
            second.add_candidate({"content": "beta", "source": "test"})
            with closing(sqlite3.connect(db)) as connection:
                self.assertEqual("ok", connection.execute("PRAGMA integrity_check").fetchone()[0])

    def test_migration_backup_and_jsonl_export(self):
        module = self.source_module("memory_store.py")
        with self.temp_dir() as directory:
            root = Path(directory)
            store = module.MemoryStore(root / "memory.sqlite3", export_path=root / "memory.jsonl")
            store.initialize()
            store.migrate()
            memory_id = store.add_candidate({
                "content": "export me",
                "source": "test",
                "memoryType": "PROCEDURAL",
            })
            backup = store.backup()
            export = store.export_jsonl()
            self.assertTrue(Path(backup).is_file())
            self.assertTrue(Path(export).is_file())
            exported = json.loads(Path(export).read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual("PROCEDURAL", exported["memoryType"])
            with closing(sqlite3.connect(store.db_path)) as connection:
                self.assertEqual(
                    ("PROCEDURAL",),
                    connection.execute(
                        "SELECT memory_type FROM memories WHERE id=?", (memory_id,),
                    ).fetchone(),
                )
                self.assertEqual(
                    (3,),
                    connection.execute(
                        "SELECT MAX(version) FROM schema_migrations",
                    ).fetchone(),
                )

            with self.assertRaisesRegex(ValueError, "memoryType"):
                store.add_candidate({
                    "content": "unsupported taxonomy",
                    "source": "test",
                    "memoryType": "PERSONAL_PROFILE",
                })
