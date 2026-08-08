#!/usr/bin/env python3
"""Transactional SQLite memory store with guarded JSONL export."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from memory_guard import redact_and_validate


SCHEMA_VERSION = 3
VALID_STATUSES = {
    "CANDIDATE", "REVIEWED", "ACTIVE", "STALE", "DEPRECATED",
    "SUPERSEDED", "QUARANTINED", "REJECTED",
}
VALID_MEMORY_TYPES = {
    "EPISODIC", "SEMANTIC", "PROCEDURAL", "DECISION",
    "FAILURE", "PREFERENCE", "SKILL_EVOLUTION",
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


@contextlib.contextmanager
def file_lock(path: Path, timeout: float = 5.0):
    """Small cross-platform lockfile suitable for bounded local writes."""
    lock = Path(f"{path}.lock")
    deadline = time.monotonic() + timeout
    while True:
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(descriptor, str(os.getpid()).encode("ascii"))
            os.close(descriptor)
            break
        except FileExistsError:
            # ponytail: bounded local writes make a 30-second lock safely stale.
            if lock.exists() and time.time() - lock.stat().st_mtime > 30:
                lock.unlink(missing_ok=True)
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError(f"lock timeout: {lock}")
            time.sleep(0.05)
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class MemoryStore:
    def __init__(self, db_path: str | Path, export_path: str | Path | None = None):
        self.db_path = Path(db_path)
        self.export_path = Path(export_path) if export_path else self.db_path.with_suffix(".jsonl")
        self.fts5_available = False

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @contextlib.contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> dict:
        try:
            with self._connection() as connection:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS schema_migrations (
                        version INTEGER PRIMARY KEY,
                        applied_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS memories (
                        id TEXT PRIMARY KEY,
                        memory_key TEXT,
                        title TEXT NOT NULL DEFAULT '',
                        summary TEXT NOT NULL DEFAULT '',
                        content TEXT NOT NULL,
                        status TEXT NOT NULL,
                        source TEXT NOT NULL,
                        source_task_id TEXT NOT NULL DEFAULT '',
                        source_role TEXT NOT NULL DEFAULT '',
                        source_type TEXT NOT NULL DEFAULT 'verified_execution',
                        memory_type TEXT NOT NULL DEFAULT 'SEMANTIC',
                        scope TEXT NOT NULL DEFAULT 'repository',
                        module TEXT NOT NULL DEFAULT '',
                        evidence_json TEXT NOT NULL DEFAULT '[]',
                        tags_json TEXT NOT NULL DEFAULT '[]',
                        confidence REAL NOT NULL DEFAULT 0.5,
                        authority REAL NOT NULL DEFAULT 0.5,
                        success_count INTEGER NOT NULL DEFAULT 0,
                        failure_count INTEGER NOT NULL DEFAULT 0,
                        retrieval_count INTEGER NOT NULL DEFAULT 0,
                        useful_count INTEGER NOT NULL DEFAULT 0,
                        harmful_count INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        last_verified_at TEXT,
                        last_retrieved_at TEXT,
                        expires_at TEXT,
                        sensitivity TEXT NOT NULL DEFAULT 'INTERNAL',
                        content_hash TEXT NOT NULL UNIQUE,
                        activation_json TEXT NOT NULL DEFAULT '{}',
                        version INTEGER NOT NULL DEFAULT 1,
                        CHECK (status IN ('CANDIDATE','REVIEWED','ACTIVE','STALE','DEPRECATED','SUPERSEDED','QUARANTINED','REJECTED'))
                    );
                    CREATE TABLE IF NOT EXISTS memory_relations (
                        source_id TEXT NOT NULL REFERENCES memories(id),
                        target_id TEXT NOT NULL REFERENCES memories(id),
                        relation TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        PRIMARY KEY (source_id, target_id, relation)
                    );
                    CREATE TABLE IF NOT EXISTS retrieval_ledger (
                        id TEXT PRIMARY KEY,
                        task_id TEXT NOT NULL DEFAULT '',
                        memory_id TEXT REFERENCES memories(id),
                        query TEXT NOT NULL,
                        role TEXT NOT NULL DEFAULT '',
                        retrieved_at TEXT NOT NULL,
                        retrieval_score REAL NOT NULL DEFAULT 0,
                        strategy TEXT NOT NULL,
                        usage TEXT NOT NULL DEFAULT '',
                        outcome TEXT NOT NULL DEFAULT 'UNKNOWN',
                        helpful INTEGER,
                        evidence_json TEXT NOT NULL DEFAULT '[]'
                    );
                    CREATE TABLE IF NOT EXISTS audit_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        event TEXT NOT NULL,
                        memory_id TEXT,
                        actor TEXT NOT NULL DEFAULT 'system',
                        details_json TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS memories_status_idx ON memories(status);
                    CREATE INDEX IF NOT EXISTS memories_key_idx ON memories(memory_key);
                    """
                )
                columns = {row["name"] for row in connection.execute("PRAGMA table_info(memories)")}
                if "activation_json" not in columns:
                    connection.execute("ALTER TABLE memories ADD COLUMN activation_json TEXT NOT NULL DEFAULT '{}'")
                if "memory_type" not in columns:
                    connection.execute(
                        "ALTER TABLE memories ADD COLUMN memory_type TEXT NOT NULL DEFAULT 'SEMANTIC'"
                    )
                connection.executemany(
                    "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    ((version, utc_now()) for version in range(1, SCHEMA_VERSION + 1)),
                )
                try:
                    connection.execute(
                        "CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts "
                        "USING fts5(memory_id UNINDEXED, title, summary, content)"
                    )
                    connection.execute(
                        """
                        INSERT INTO memories_fts(memory_id,title,summary,content)
                        SELECT m.id,m.title,m.summary,m.content FROM memories m
                        WHERE NOT EXISTS (
                            SELECT 1 FROM memories_fts f WHERE f.memory_id=m.id
                        )
                        """
                    )
                    self.fts5_available = True
                except sqlite3.OperationalError:
                    self.fts5_available = False
                result = connection.execute("PRAGMA integrity_check").fetchone()[0]
                if result != "ok":
                    raise sqlite3.DatabaseError(result)
        except sqlite3.DatabaseError as exc:
            if "locked" in str(exc).casefold() or "busy" in str(exc).casefold():
                raise RuntimeError("database is busy; no corruption recovery attempted") from exc
            backup = self._backup_corrupt_file()
            raise RuntimeError(f"database integrity failure; writes refused; backup={backup}") from exc
        return {"initialized": True, "schemaVersion": SCHEMA_VERSION, "fts5": self.fts5_available}

    def _backup_corrupt_file(self) -> str:
        if not self.db_path.exists():
            return ""
        backup = self.db_path.with_name(f"{self.db_path.name}.corrupt.{int(time.time())}.{uuid.uuid4().hex[:8]}.bak")
        shutil.copy2(self.db_path, backup)
        return str(backup)

    def migrate(self) -> dict:
        return self.initialize()

    def _sanitized_record(self, record: dict) -> tuple[dict, list[str]]:
        serialized = json.dumps(record, ensure_ascii=False, sort_keys=True)
        guard = redact_and_validate(serialized)
        safe = json.loads(guard["redacted"])
        return safe, guard["findings"]

    def _repository_root(self) -> Path:
        start = self.db_path.resolve().parent
        for candidate in (start, *start.parents):
            if (candidate / ".git").exists():
                return candidate
        return start

    def _readable_repository_file(self, value: object, label: str) -> Path:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{label} must be a non-empty path")
        root = self._repository_root()
        raw = Path(value)
        candidate = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"{label} must stay inside the repository") from exc
        if not candidate.is_file():
            raise ValueError(f"{label} must reference an existing readable file")
        try:
            with candidate.open("rb") as stream:
                stream.read(1)
        except OSError as exc:
            raise ValueError(f"{label} must reference an existing readable file") from exc
        return candidate

    def _validated_reviewer_artifact(
        self,
        row: sqlite3.Row,
        memory_id: str,
        actor: str | None,
        reviewer_artifact: dict | None,
        reviewer_artifact_path: str | Path | None,
    ) -> dict:
        if actor not in {"workers_boss", "workers_qa"}:
            raise PermissionError("only workers_boss or workers_qa may activate memory")
        if row["source_role"] == actor:
            raise PermissionError("memory source role may not review its own activation")
        if not isinstance(reviewer_artifact, dict):
            raise ValueError("ACTIVE review requires a structured reviewer_artifact")
        allowed_fields = {"actor", "reviewer", "memory_id", "verdict", "evidence"}
        if reviewer_artifact.keys() - allowed_fields:
            raise ValueError("reviewer artifact contains unsupported fields")
        guarded = redact_and_validate(
            json.dumps(reviewer_artifact, ensure_ascii=False, sort_keys=True),
        )
        if not guarded["accepted"]:
            raise ValueError("reviewer artifact contains secret or unnecessary PII")

        reviewer = reviewer_artifact.get("reviewer", reviewer_artifact.get("actor"))
        if reviewer != actor:
            raise PermissionError("reviewer artifact identity must match the authorized actor")
        if reviewer_artifact.get("memory_id") != memory_id:
            raise ValueError("reviewer artifact memory_id binding mismatch")
        if str(reviewer_artifact.get("verdict", "")).upper() not in {"APPROVED", "PASS"}:
            raise ValueError("reviewer artifact verdict must be APPROVED or PASS")

        activation = json.loads(row["activation_json"] or "{}")
        memory_evidence = activation.get("evidence")
        artifact_evidence = reviewer_artifact.get("evidence")
        if not isinstance(memory_evidence, list) or not isinstance(artifact_evidence, list):
            raise ValueError("memory and reviewer artifact evidence must be arrays")
        if not memory_evidence or not artifact_evidence:
            raise ValueError("memory and reviewer artifact evidence must not be empty")
        memory_paths = [
            self._readable_repository_file(value, "memory evidence")
            for value in memory_evidence
        ]
        artifact_paths = [
            self._readable_repository_file(value, "reviewer artifact evidence")
            for value in artifact_evidence
        ]
        if set(memory_paths) != set(artifact_paths):
            raise ValueError("reviewer artifact evidence must exactly bind the memory evidence")

        canonical = json.dumps(
            reviewer_artifact, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        artifact_path = "<in-memory>"
        artifact_hash = hashlib.sha256(canonical).hexdigest()
        if reviewer_artifact_path is not None:
            resolved_artifact = self._readable_repository_file(
                str(reviewer_artifact_path), "reviewer artifact",
            )
            raw = resolved_artifact.read_bytes()
            try:
                loaded = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("reviewer artifact file must contain valid UTF-8 JSON") from exc
            if loaded != reviewer_artifact:
                raise ValueError("reviewer artifact file content binding mismatch")
            artifact_path = str(resolved_artifact)
            artifact_hash = hashlib.sha256(raw).hexdigest()
        return {
            "path": artifact_path,
            "sha256": artifact_hash,
            "memory_id": memory_id,
            "reviewer": reviewer,
            "verdict": str(reviewer_artifact["verdict"]).upper(),
            "evidence": [str(path) for path in artifact_paths],
        }

    def add_verified_experience(self, record: dict) -> dict:
        """Activate one local success only after a pre-existing QA PASS evidence set."""
        if not isinstance(record, dict):
            raise ValueError("verified experience must be an object")
        if record.get("source_type", record.get("sourceType")) != "verified_execution":
            raise ValueError("verified experience must use verified_execution")
        source_role = record.get("source_role", record.get("sourceRole"))
        if source_role not in {"workers_planner", "workers_pm", "workers_executor"}:
            raise PermissionError("verified experience source must be a non-QA fixed role")
        if str(record.get("closed_status", record.get("closedStatus", ""))) != "CLOSED":
            raise ValueError("verified experience requires a CLOSED task")
        if str(record.get("scope", "")) != "repository":
            raise ValueError("verified experience scope must be repository")
        if str(record.get("memoryType", record.get("memory_type", ""))).upper() not in {
            "EPISODIC", "SEMANTIC", "PROCEDURAL", "DECISION",
        }:
            raise ValueError("verified experience must use a reusable local memoryType")
        evidence = record.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise ValueError("verified experience requires evidence")
        evidence_paths = [
            self._readable_repository_file(item, "verified experience evidence")
            for item in evidence
        ]
        qa_report = record.get("qa_report", record.get("qaReport"))
        report_path = self._readable_repository_file(qa_report, "verified experience QA report")
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("verified experience QA report must be UTF-8 JSON") from exc
        task_id = record.get("source_task_id", record.get("sourceTaskId"))
        report_evidence = report.get("evidence")
        if (
            report.get("task_id") != task_id
            or report.get("role") != "workers_qa"
            or str(report.get("overall_verdict", "")).upper() != "PASS"
            or not isinstance(report_evidence, list)
        ):
            raise ValueError("verified experience requires a matching QA PASS report")
        report_paths = [
            self._readable_repository_file(item, "verified experience QA evidence")
            for item in report_evidence
        ]
        if set(report_paths) != set(evidence_paths):
            raise ValueError("verified experience QA evidence must exactly bind memory evidence")
        memory_id = self.add_candidate(record)
        current = self.get(memory_id)
        if current["status"] != "CANDIDATE":
            return {"id": memory_id, "status": current["status"]}
        reviewer = {
            "actor": "workers_qa",
            "memory_id": memory_id,
            "verdict": "PASS",
            "evidence": evidence,
        }
        return self.review(memory_id, "ACTIVE", actor="workers_qa", reviewer_artifact=reviewer)

    def add_candidate(self, record: dict) -> str:
        if not isinstance(record, dict) or not isinstance(record.get("content"), str) or not record["content"].strip():
            raise ValueError("memory content is required")
        self.initialize()
        safe, findings = self._sanitized_record(record)
        text = safe["content"].strip()
        digest = content_hash(text)
        memory_id = str(safe.get("id") or safe.get("memory_id") or uuid.uuid4())
        memory_key = safe.get("key") or safe.get("memory_key")
        now = utc_now()
        status = "QUARANTINED" if findings else "CANDIDATE"
        source_task_id = safe.get("source_task_id", safe.get("sourceTaskId", ""))
        source_role = safe.get("source_role", safe.get("sourceRole", ""))
        evidence = safe.get("evidence", [])
        memory_type = str(
            safe.get("memoryType", safe.get("memory_type", "SEMANTIC")),
        ).upper()
        if memory_type not in VALID_MEMORY_TYPES:
            raise ValueError(
                f"memoryType must be one of: {', '.join(sorted(VALID_MEMORY_TYPES))}"
            )
        scope = safe.get("scope")
        confidence = safe.get("confidence")
        activation = {
            "sourceTaskId": source_task_id,
            "sourceRole": source_role,
            "evidence": evidence,
            "scope": scope,
            "confidence": confidence,
        }
        relation_target: str | None = None
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute("SELECT 1 FROM memories WHERE content_hash=?", (digest,)).fetchone():
                raise ValueError("duplicate memory content")
            if memory_key:
                conflict = connection.execute(
                    "SELECT id FROM memories WHERE memory_key=? AND status='ACTIVE' AND content_hash<>? LIMIT 1",
                    (str(memory_key), digest),
                ).fetchone()
                if conflict:
                    status, relation_target = "QUARANTINED", conflict["id"]
            connection.execute(
                """
                INSERT INTO memories(
                    id, memory_key, title, summary, content, status, source,
                    source_task_id, source_role, source_type, memory_type, scope, module,
                    evidence_json, tags_json, confidence, authority, created_at,
                    updated_at, last_verified_at, expires_at, sensitivity,
                    content_hash, activation_json, version
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    memory_id, memory_key, safe.get("title", ""), safe.get("summary", ""),
                    text, status, str(safe.get("source", "unknown")),
                    str(source_task_id),
                    str(source_role),
                    str(safe.get("source_type", "verified_execution")),
                    memory_type, str(scope or "repository"), str(safe.get("module", "")),
                    json.dumps(evidence, ensure_ascii=False),
                    json.dumps(safe.get("tags", []), ensure_ascii=False),
                    float(confidence if confidence is not None else 0.5), float(safe.get("authority", 0.5)),
                    now, now, safe.get("last_verified_at"), safe.get("expires_at"),
                    str(safe.get("sensitivity", "INTERNAL")), digest,
                    json.dumps(activation, ensure_ascii=False), int(safe.get("version", 1)),
                ),
            )
            if relation_target:
                connection.execute(
                    "INSERT INTO memory_relations(source_id,target_id,relation,created_at) VALUES (?,?,?,?)",
                    (memory_id, relation_target, "CONFLICTS_WITH", now),
                )
            connection.execute(
                "INSERT INTO audit_log(event,memory_id,details_json,created_at) VALUES (?,?,?,?)",
                ("MEMORY_CANDIDATE_ADDED", memory_id, json.dumps({"status": status, "redactions": findings}), now),
            )
            self._sync_fts(connection, memory_id, safe.get("title", ""), safe.get("summary", ""), text)
        return memory_id

    def _sync_fts(self, connection: sqlite3.Connection, memory_id: str, title: str, summary: str, content: str) -> None:
        try:
            connection.execute("DELETE FROM memories_fts WHERE memory_id=?", (memory_id,))
            connection.execute(
                "INSERT INTO memories_fts(memory_id,title,summary,content) VALUES (?,?,?,?)",
                (memory_id, title, summary, content),
            )
            self.fts5_available = True
        except sqlite3.OperationalError:
            self.fts5_available = False

    def review(
        self,
        memory_id: str,
        status: str,
        actor: str | None = None,
        reviewer_artifact: dict | None = None,
        reviewer_artifact_path: str | Path | None = None,
    ) -> dict:
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid memory status: {status}")
        self.initialize()
        now = utc_now()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
            if not row:
                raise KeyError(memory_id)
            final_status = status
            artifact_audit: dict | None = None
            if status == "ACTIVE":
                errors = self._activation_errors(row)
                if errors:
                    raise ValueError(f"memory activation gate failed: {', '.join(errors)}")
                artifact_audit = self._validated_reviewer_artifact(
                    row, memory_id, actor, reviewer_artifact, reviewer_artifact_path,
                )
                if row["memory_key"]:
                    conflict = connection.execute(
                        "SELECT id FROM memories WHERE memory_key=? AND status='ACTIVE' AND id<>? AND content_hash<>? LIMIT 1",
                        (row["memory_key"], memory_id, row["content_hash"]),
                    ).fetchone()
                    if conflict:
                        final_status = "QUARANTINED"
                        connection.execute(
                            "INSERT OR IGNORE INTO memory_relations(source_id,target_id,relation,created_at) VALUES (?,?,?,?)",
                            (memory_id, conflict["id"], "CONFLICTS_WITH", now),
                        )
            connection.execute(
                "UPDATE memories SET status=?, updated_at=?, last_verified_at=?, activation_json=? WHERE id=?",
                (
                    final_status,
                    now,
                    now if final_status == "ACTIVE" else row["last_verified_at"],
                    json.dumps(
                        {
                            **json.loads(row["activation_json"] or "{}"),
                            **({"reviewerArtifact": artifact_audit} if artifact_audit else {}),
                        },
                        ensure_ascii=False,
                    ),
                    memory_id,
                ),
            )
            connection.execute(
                "INSERT INTO audit_log(event,memory_id,actor,details_json,created_at) VALUES (?,?,?,?,?)",
                (
                    "MEMORY_REVIEWED",
                    memory_id,
                    actor or "system",
                    json.dumps(
                        {"status": final_status, "reviewerArtifact": artifact_audit},
                        ensure_ascii=False,
                    ),
                    now,
                ),
            )
        return {"id": memory_id, "status": final_status}

    @staticmethod
    def _activation_errors(row: sqlite3.Row) -> list[str]:
        activation = json.loads(row["activation_json"] or "{}")
        confidence = activation.get("confidence")
        checks = {
            "source_task_id": isinstance(activation.get("sourceTaskId"), str) and bool(activation["sourceTaskId"].strip()),
            "source_role": isinstance(activation.get("sourceRole"), str) and bool(activation["sourceRole"].strip()),
            "evidence": (
                isinstance(activation.get("evidence"), list)
                and bool(activation["evidence"])
                and all(isinstance(item, str) and bool(item.strip()) for item in activation["evidence"])
            ),
            "scope": isinstance(activation.get("scope"), str) and bool(activation["scope"].strip()),
            "confidence": (
                isinstance(confidence, (int, float))
                and not isinstance(confidence, bool)
                and 0 <= float(confidence) <= 1
            ),
        }
        return [field for field, valid in checks.items() if not valid]

    def get(self, memory_id: str) -> dict:
        self.initialize()
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
            if not row:
                raise KeyError(memory_id)
            return self._row_to_dict(row)

    def retrieve(self, query: str, top_k: int = 8) -> list[dict]:
        self.initialize()
        tokens = [token.casefold() for token in query.split() if token]
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM memories WHERE status='ACTIVE' ORDER BY authority DESC, confidence DESC, updated_at DESC"
            ).fetchall()
            matches = [
                self._row_to_dict(row) for row in rows
                if not tokens or any(token in f"{row['memory_key'] or ''} {row['title']} {row['summary']} {row['content']}".casefold() for token in tokens)
            ][:max(0, min(int(top_k), 8))]
            for item in matches or [None]:
                connection.execute(
                    "INSERT INTO retrieval_ledger(id,memory_id,query,retrieved_at,retrieval_score,strategy) VALUES (?,?,?,?,?,?)",
                    (str(uuid.uuid4()), item["id"] if item else None, query, utc_now(), 0.0, "basic"),
                )
            if matches:
                placeholders = ",".join("?" for _ in matches)
                connection.execute(
                    f"UPDATE memories SET retrieval_count=retrieval_count+1,last_retrieved_at=? "
                    f"WHERE id IN ({placeholders})",
                    (utc_now(), *(item["id"] for item in matches)),
                )
        return matches

    def supersede(
        self,
        old_id: str,
        new_id: str,
        actor: str | None = None,
        reviewer_artifact: dict | None = None,
        reviewer_artifact_path: str | Path | None = None,
    ) -> dict:
        """Preserve both records while making only the reviewed replacement active."""
        self.initialize()
        now = utc_now()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            old = connection.execute("SELECT id FROM memories WHERE id=?", (old_id,)).fetchone()
            new = connection.execute("SELECT * FROM memories WHERE id=?", (new_id,)).fetchone()
            if not old or not new:
                raise KeyError(old_id if not old else new_id)
            if new["status"] in {"QUARANTINED", "REJECTED"}:
                raise ValueError("quarantined or rejected memory cannot supersede")
            errors = self._activation_errors(new)
            if errors:
                raise ValueError(f"memory activation gate failed: {', '.join(errors)}")
            artifact_audit = self._validated_reviewer_artifact(
                new, new_id, actor, reviewer_artifact, reviewer_artifact_path,
            )
            connection.execute("UPDATE memories SET status='SUPERSEDED',updated_at=? WHERE id=?", (now, old_id))
            connection.execute(
                "UPDATE memories SET status='ACTIVE',updated_at=?,last_verified_at=?,activation_json=? WHERE id=?",
                (
                    now,
                    now,
                    json.dumps(
                        {
                            **json.loads(new["activation_json"] or "{}"),
                            "reviewerArtifact": artifact_audit,
                        },
                        ensure_ascii=False,
                    ),
                    new_id,
                ),
            )
            connection.execute(
                "INSERT OR IGNORE INTO memory_relations(source_id,target_id,relation,created_at) VALUES (?,?,?,?)",
                (old_id, new_id, "SUPERSEDED_BY", now),
            )
            connection.execute(
                "INSERT INTO audit_log(event,memory_id,actor,details_json,created_at) VALUES (?,?,?,?,?)",
                (
                    "MEMORY_SUPERSEDED",
                    old_id,
                    actor or "system",
                    json.dumps(
                        {"replacement": new_id, "reviewerArtifact": artifact_audit},
                        ensure_ascii=False,
                    ),
                    now,
                ),
            )
        return {"superseded": old_id, "active": new_id}

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"], "key": row["memory_key"], "title": row["title"],
            "summary": row["summary"], "content": row["content"], "status": row["status"],
            "source": row["source"], "sourceTaskId": row["source_task_id"],
            "sourceRole": row["source_role"], "sourceType": row["source_type"],
            "memoryType": row["memory_type"],
            "scope": row["scope"], "module": row["module"],
            "evidence": json.loads(row["evidence_json"]), "tags": json.loads(row["tags_json"]),
            "confidence": row["confidence"], "authority": row["authority"],
            "successCount": row["success_count"], "failureCount": row["failure_count"],
            "retrievalCount": row["retrieval_count"], "usefulCount": row["useful_count"],
            "harmfulCount": row["harmful_count"],
            "contentHash": row["content_hash"], "createdAt": row["created_at"],
            "updatedAt": row["updated_at"], "lastVerifiedAt": row["last_verified_at"],
            "lastRetrievedAt": row["last_retrieved_at"], "expiresAt": row["expires_at"],
            "sensitivity": row["sensitivity"],
            "activation": json.loads(row["activation_json"] or "{}"),
            "version": row["version"],
        }

    def integrity(self) -> dict:
        self.initialize()
        with self._connection() as connection:
            result = connection.execute("PRAGMA integrity_check").fetchone()[0]
        return {"ok": result == "ok", "result": result}

    def backup(self, destination: str | Path | None = None) -> str:
        self.initialize()
        target = Path(destination) if destination else self.db_path.with_name(
            f"{self.db_path.stem}.{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}.{uuid.uuid4().hex[:8]}.backup.sqlite3"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        try:
            source = self._connect()
            backup_connection = sqlite3.connect(temporary)
            try:
                source.backup(backup_connection)
                backup_connection.commit()
            finally:
                backup_connection.close()
                source.close()
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        return str(target)

    def export_jsonl(self, destination: str | Path | None = None) -> str:
        self.initialize()
        target = Path(destination) if destination else self.export_path
        with self._connection() as connection:
            memory_rows = connection.execute(
                "SELECT * FROM memories ORDER BY created_at,id",
            ).fetchall()
            relation_rows = connection.execute(
                "SELECT * FROM memory_relations ORDER BY created_at,source_id,target_id,relation",
            ).fetchall()
            ledger_rows = connection.execute(
                "SELECT * FROM retrieval_ledger ORDER BY retrieved_at,id",
            ).fetchall()
            audit_rows = connection.execute(
                "SELECT * FROM audit_log ORDER BY id",
            ).fetchall()
            migration_rows = connection.execute(
                "SELECT * FROM schema_migrations ORDER BY version",
            ).fetchall()
        records: list[dict] = []
        records.extend(
            {"recordType": "memory", "schemaVersion": SCHEMA_VERSION, **self._row_to_dict(row)}
            for row in memory_rows
        )
        records.extend({
            "recordType": "memoryRelation",
            "sourceId": row["source_id"],
            "targetId": row["target_id"],
            "relation": row["relation"],
            "createdAt": row["created_at"],
        } for row in relation_rows)
        records.extend({
            "recordType": "retrievalLedger",
            "id": row["id"],
            "taskId": row["task_id"],
            "memoryId": row["memory_id"],
            "query": row["query"],
            "role": row["role"],
            "retrievedAt": row["retrieved_at"],
            "retrievalScore": row["retrieval_score"],
            "strategy": row["strategy"],
            "usage": row["usage"],
            "outcome": row["outcome"],
            "helpful": row["helpful"],
            "evidence": json.loads(row["evidence_json"]),
        } for row in ledger_rows)
        records.extend({
            "recordType": "auditLog",
            "id": row["id"],
            "event": row["event"],
            "memoryId": row["memory_id"],
            "actor": row["actor"],
            "details": json.loads(row["details_json"]),
            "createdAt": row["created_at"],
        } for row in audit_rows)
        records.extend({
            "recordType": "schemaMigration",
            "version": row["version"],
            "appliedAt": row["applied_at"],
        } for row in migration_rows)
        lines: list[str] = []
        for item in records:
            guard = redact_and_validate(json.dumps(item, ensure_ascii=False, sort_keys=True))
            if not guard["accepted"]:
                item = json.loads(guard["redacted"])
                if item.get("recordType") == "memory":
                    item["status"] = "QUARANTINED"
                    item["contentHash"] = content_hash(str(item.get("content", "")))
            lines.append(json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        with file_lock(target):
            atomic_write_text(target, "".join(f"{line}\n" for line in lines))
        return str(target)


def _load_record(path: str | None) -> dict:
    raw = Path(path).read_text(encoding="utf-8") if path else sys.stdin.read()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("record must be a JSON object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("init", "add", "review", "export", "integrity", "backup"))
    parser.add_argument("--db", default=".workers-group/runtime/memory.sqlite3")
    parser.add_argument("--export", dest="export_path", default=".workers-group/memory/exports/memories.jsonl")
    parser.add_argument("--file")
    parser.add_argument("--memory-id")
    parser.add_argument("--status", choices=sorted(VALID_STATUSES))
    parser.add_argument("--actor", choices=("workers_boss", "workers_qa"))
    parser.add_argument(
        "--reviewer-artifact",
        "--review-artifact",
        dest="reviewer_artifact",
        help="structured JSON artifact required for ACTIVE review",
    )
    args = parser.parse_args(argv)
    try:
        store = MemoryStore(args.db, args.export_path)
        if args.action == "init":
            result = store.initialize()
        elif args.action == "add":
            result = {"id": store.add_candidate(_load_record(args.file))}
        elif args.action == "review":
            if not args.memory_id or not args.status or not args.actor:
                raise ValueError("--memory-id, --status, and explicit --actor are required")
            if args.status == "ACTIVE" and not args.reviewer_artifact:
                raise ValueError("--reviewer-artifact is required for ACTIVE review")
            artifact = _load_record(args.reviewer_artifact) if args.reviewer_artifact else None
            result = store.review(
                args.memory_id,
                args.status,
                actor=args.actor,
                reviewer_artifact=artifact,
                reviewer_artifact_path=args.reviewer_artifact,
            )
        elif args.action == "export":
            result = {"path": store.export_jsonl()}
        elif args.action == "integrity":
            result = store.integrity()
        else:
            result = {"path": store.backup()}
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
