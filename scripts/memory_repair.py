#!/usr/bin/env python3
"""Check memory integrity and recover only damaged JSONL tails."""

from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import time
import uuid
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from memory_guard import redact_and_validate
from memory_store import (
    SCHEMA_VERSION,
    VALID_MEMORY_TYPES,
    VALID_STATUSES,
    MemoryStore,
    atomic_write_text,
    content_hash,
    file_lock,
    utc_now,
)


def _safe_export_record(record: object) -> tuple[object, bool]:
    guard = redact_and_validate(json.dumps(record, ensure_ascii=False, sort_keys=True))
    safe = json.loads(guard["redacted"])
    if not guard["accepted"] and isinstance(safe, dict):
        if safe.get("recordType", "memory") == "memory":
            safe["status"] = "QUARANTINED"
            safe["contentHash"] = content_hash(str(safe.get("content", "")))
    return safe, guard["accepted"]


def repair_jsonl(path: str | Path) -> dict:
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(target)
    raw = target.read_text(encoding="utf-8")
    lines = raw.splitlines()
    records: list[object] = []
    discarded = 0
    redacted = 0
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            discarded = len([tail for tail in lines[index:] if tail.strip()])
            break
        safe, accepted = _safe_export_record(record)
        records.append(safe)
        redacted += int(not accepted)
    backup = ""
    if discarded or redacted:
        backup_path = target.with_name(f"{target.name}.damaged.{int(time.time())}.{uuid.uuid4().hex[:8]}.bak")
        shutil.copy2(target, backup_path)
        backup = str(backup_path)
    rendered = "".join(
        f"{json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(',', ':'))}\n"
        for record in records
    )
    with file_lock(target):
        atomic_write_text(target, rendered)
    return {
        "kept": len(records),
        "discardedTailLines": discarded,
        "redactedRecords": redacted,
        "backupPath": backup,
    }


def _record_hash(record: dict) -> str:
    return hashlib.sha256(str(record.get("content", "")).encode("utf-8")).hexdigest()


def _database_integrity(path: Path) -> str:
    if not path.is_file():
        return "missing"
    connection: sqlite3.Connection | None = None
    try:
        uri = f"file:{path.resolve().as_posix()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=2)
        return str(connection.execute("PRAGMA integrity_check").fetchone()[0])
    except sqlite3.DatabaseError as exc:
        return f"corrupt:{type(exc).__name__}"
    finally:
        if connection is not None:
            connection.close()


def _backup_corrupt_database(database: Path) -> str:
    if not database.is_file():
        return ""
    backup = database.with_name(
        f"{database.name}.corrupt.{int(time.time())}.{uuid.uuid4().hex[:8]}.bak",
    )
    shutil.copy2(database, backup)
    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{database}{suffix}")
        if sidecar.is_file():
            shutil.copy2(sidecar, Path(f"{backup}{suffix}"))
    return str(backup)


def _export_problems(export_records: list[dict]) -> tuple[list[str], list[str]]:
    hash_problems: list[str] = []
    sensitive_records: list[str] = []
    for record in export_records:
        if not isinstance(record, dict):
            sensitive_records.append("<non-object>")
            continue
        identifier = str(record.get("id") or record.get("memory_id") or "<unknown>")
        if record.get("recordType", "memory") == "memory":
            expected = record.get("contentHash") or record.get("content_hash")
            if expected is not None and expected != _record_hash(record):
                hash_problems.append(identifier)
        if not redact_and_validate(
            json.dumps(record, ensure_ascii=False, sort_keys=True),
        )["accepted"]:
            sensitive_records.append(identifier)
    return hash_problems, sensitive_records


def _required_string(record: dict, field: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"export field must be a non-empty string: {field}")
    return value


def _nonnegative_int(record: dict, field: str, default: int = 0) -> int:
    value = record.get(field, default)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"export field must be a non-negative integer: {field}")
    return value


def _active_export_is_bound(record: dict) -> bool:
    activation = record.get("activation")
    if not isinstance(activation, dict):
        return False
    artifact = activation.get("reviewerArtifact")
    if not isinstance(artifact, dict):
        return False
    reviewer = artifact.get("reviewer")
    evidence = record.get("evidence")
    return (
        reviewer in {"workers_boss", "workers_qa"}
        and reviewer != record.get("sourceRole")
        and artifact.get("memory_id") == record.get("id")
        and str(artifact.get("verdict", "")).upper() in {"APPROVED", "PASS"}
        and isinstance(evidence, list)
        and bool(evidence)
        and artifact.get("evidence") == evidence
    )


def _validated_records(export_records: list[dict]) -> dict[str, list[dict]]:
    grouped = {
        "memory": [],
        "memoryRelation": [],
        "retrievalLedger": [],
        "auditLog": [],
        "schemaMigration": [],
    }
    for record in export_records:
        if not isinstance(record, dict):
            raise ValueError("each export record must be an object")
        record_type = str(record.get("recordType", "memory"))
        if record_type not in grouped:
            raise ValueError(f"unsupported export recordType: {record_type}")
        guard = redact_and_validate(
            json.dumps(record, ensure_ascii=False, sort_keys=True),
        )
        if not guard["accepted"]:
            raise ValueError(f"unsafe export record refused: {record_type}")
        if record_type == "memory":
            complete_fields = {
                "id", "key", "title", "summary", "content", "status", "source",
                "sourceTaskId", "sourceRole", "sourceType", "memoryType", "scope",
                "module", "evidence", "tags", "confidence", "authority",
                "successCount", "failureCount", "retrievalCount", "usefulCount",
                "harmfulCount", "contentHash", "createdAt", "updatedAt",
                "lastVerifiedAt", "lastRetrievedAt", "expiresAt", "sensitivity",
                "activation", "version",
            }
            missing = sorted(complete_fields - record.keys())
            if missing:
                raise ValueError(
                    f"incomplete memory recovery record: {', '.join(missing)}",
                )
            _required_string(record, "id")
            content = _required_string(record, "content")
            _required_string(record, "source")
            _required_string(record, "sourceType")
            _required_string(record, "scope")
            _required_string(record, "sensitivity")
            _required_string(record, "createdAt")
            _required_string(record, "updatedAt")
            status = str(record.get("status", "CANDIDATE"))
            if status not in VALID_STATUSES:
                raise ValueError(f"invalid memory status in export: {status}")
            memory_type = str(record.get("memoryType", "SEMANTIC")).upper()
            if memory_type not in VALID_MEMORY_TYPES:
                raise ValueError(f"invalid memoryType in export: {memory_type}")
            expected_hash = _required_string(record, "contentHash")
            if expected_hash != content_hash(content):
                raise ValueError(f"contentHash mismatch in export: {record['id']}")
            for field in (
                "successCount", "failureCount", "retrievalCount",
                "usefulCount", "harmfulCount", "version",
            ):
                _nonnegative_int(record, field, 1 if field == "version" else 0)
            for field in ("evidence", "tags"):
                value = record.get(field, [])
                if not isinstance(value, list):
                    raise ValueError(f"export field must be an array: {field}")
            if not isinstance(record.get("activation", {}), dict):
                raise ValueError("export activation must be an object")
            if status == "ACTIVE" and not _active_export_is_bound(record):
                record = {**record, "status": "QUARANTINED"}
            for field in ("confidence", "authority"):
                value = record.get(field, 0.5)
                if (
                    not isinstance(value, (int, float))
                    or isinstance(value, bool)
                    or not 0 <= float(value) <= 1
                ):
                    raise ValueError(f"export field must be numeric from 0 to 1: {field}")
        grouped[record_type].append(record)
    return grouped


def _insert_export_records(database: Path, export_records: list[dict]) -> None:
    grouped = _validated_records(export_records)
    if not grouped["memory"]:
        raise ValueError("recovery export must contain at least one memory")
    store = MemoryStore(database)
    store.initialize()
    with store._connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        for table in ("memory_relations", "retrieval_ledger", "audit_log", "memories"):
            connection.execute(f"DELETE FROM {table}")
        try:
            connection.execute("DELETE FROM memories_fts")
        except sqlite3.OperationalError:
            pass
        memory_columns = (
            "id", "memory_key", "title", "summary", "content", "status", "source",
            "source_task_id", "source_role", "source_type", "memory_type", "scope",
            "module", "evidence_json", "tags_json", "confidence", "authority",
            "success_count", "failure_count", "retrieval_count", "useful_count",
            "harmful_count", "created_at", "updated_at", "last_verified_at",
            "last_retrieved_at", "expires_at", "sensitivity", "content_hash",
            "activation_json", "version",
        )
        placeholders = ",".join("?" for _ in memory_columns)
        for record in grouped["memory"]:
            now = utc_now()
            values = (
                record["id"], record.get("key"), record.get("title", ""),
                record.get("summary", ""), record["content"],
                record.get("status", "CANDIDATE"), record["source"],
                record.get("sourceTaskId", ""), record.get("sourceRole", ""),
                record.get("sourceType", "verified_execution"),
                str(record.get("memoryType", "SEMANTIC")).upper(),
                record.get("scope", "repository"), record.get("module", ""),
                json.dumps(record.get("evidence", []), ensure_ascii=False),
                json.dumps(record.get("tags", []), ensure_ascii=False),
                float(record.get("confidence", 0.5)),
                float(record.get("authority", 0.5)),
                _nonnegative_int(record, "successCount"),
                _nonnegative_int(record, "failureCount"),
                _nonnegative_int(record, "retrievalCount"),
                _nonnegative_int(record, "usefulCount"),
                _nonnegative_int(record, "harmfulCount"),
                record.get("createdAt", now), record.get("updatedAt", now),
                record.get("lastVerifiedAt"), record.get("lastRetrievedAt"),
                record.get("expiresAt"), record.get("sensitivity", "INTERNAL"),
                record["contentHash"],
                json.dumps(record.get("activation", {}), ensure_ascii=False),
                _nonnegative_int(record, "version", 1),
            )
            connection.execute(
                f"INSERT INTO memories({','.join(memory_columns)}) VALUES ({placeholders})",
                values,
            )
            try:
                connection.execute(
                    "INSERT INTO memories_fts(memory_id,title,summary,content) VALUES (?,?,?,?)",
                    (
                        record["id"], record.get("title", ""),
                        record.get("summary", ""), record["content"],
                    ),
                )
            except sqlite3.OperationalError:
                pass
        for record in grouped["memoryRelation"]:
            connection.execute(
                "INSERT INTO memory_relations(source_id,target_id,relation,created_at) VALUES (?,?,?,?)",
                (
                    _required_string(record, "sourceId"),
                    _required_string(record, "targetId"),
                    _required_string(record, "relation"),
                    _required_string(record, "createdAt"),
                ),
            )
        for record in grouped["retrievalLedger"]:
            helpful = record.get("helpful")
            if helpful not in {None, 0, 1, False, True}:
                raise ValueError("ledger helpful must be null or boolean")
            evidence = record.get("evidence", [])
            if not isinstance(evidence, list):
                raise ValueError("ledger evidence must be an array")
            connection.execute(
                """
                INSERT INTO retrieval_ledger(
                    id,task_id,memory_id,query,role,retrieved_at,retrieval_score,
                    strategy,usage,outcome,helpful,evidence_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    _required_string(record, "id"), record.get("taskId", ""),
                    record.get("memoryId"), record.get("query", ""),
                    record.get("role", ""), _required_string(record, "retrievedAt"),
                    float(record.get("retrievalScore", 0)),
                    _required_string(record, "strategy"), record.get("usage", ""),
                    record.get("outcome", "UNKNOWN"),
                    None if helpful is None else int(bool(helpful)),
                    json.dumps(evidence, ensure_ascii=False),
                ),
            )
        for record in grouped["auditLog"]:
            details = record.get("details", {})
            if not isinstance(details, dict):
                raise ValueError("audit details must be an object")
            connection.execute(
                """
                INSERT INTO audit_log(id,event,memory_id,actor,details_json,created_at)
                VALUES (?,?,?,?,?,?)
                """,
                (
                    _nonnegative_int(record, "id"),
                    _required_string(record, "event"), record.get("memoryId"),
                    record.get("actor", "system"),
                    json.dumps(details, ensure_ascii=False),
                    _required_string(record, "createdAt"),
                ),
            )
        for record in grouped["schemaMigration"]:
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version,applied_at) VALUES (?,?)",
                (
                    _nonnegative_int(record, "version"),
                    _required_string(record, "appliedAt"),
                ),
            )
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise sqlite3.DatabaseError(integrity)


def _validate_backup_database(path: Path) -> None:
    if _database_integrity(path) != "ok":
        raise ValueError("explicit backup failed integrity_check")
    required_tables = {
        "memories", "memory_relations", "retrieval_ledger",
        "audit_log", "schema_migrations",
    }
    with closing(sqlite3.connect(path)) as connection:
        connection.row_factory = sqlite3.Row
        actual = {
            row["name"] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'",
            )
        }
        if not required_tables.issubset(actual):
            raise ValueError("explicit backup is missing required memory tables")
        for row in connection.execute("SELECT * FROM memories"):
            if row["content_hash"] != content_hash(row["content"]):
                raise ValueError(f"explicit backup contentHash mismatch: {row['id']}")
            if not redact_and_validate(
                json.dumps(dict(row), ensure_ascii=False, sort_keys=True),
            )["accepted"]:
                raise ValueError(f"explicit backup contains unsafe memory: {row['id']}")
        for table in (
            "memory_relations", "retrieval_ledger", "audit_log",
            "schema_migrations",
        ):
            for row in connection.execute(f"SELECT * FROM {table}"):
                if not redact_and_validate(
                    json.dumps(dict(row), ensure_ascii=False, sort_keys=True),
                )["accepted"]:
                    raise ValueError(f"explicit backup contains unsafe {table} record")


def _replace_database(database: Path, candidate: Path) -> None:
    moved_sidecars: list[tuple[Path, Path]] = []
    try:
        for suffix in ("-wal", "-shm"):
            sidecar = Path(f"{database}{suffix}")
            if sidecar.is_file():
                parked = sidecar.with_name(
                    f".{sidecar.name}.{uuid.uuid4().hex}.recovery-old",
                )
                os.replace(sidecar, parked)
                moved_sidecars.append((sidecar, parked))
        os.replace(candidate, database)
    except Exception:
        for sidecar, parked in reversed(moved_sidecars):
            if parked.is_file():
                os.replace(parked, sidecar)
        raise
    for _, parked in moved_sidecars:
        try:
            parked.unlink(missing_ok=True)
        except OSError:
            # The parked sidecar no longer has SQLite's active WAL/SHM name.
            pass


def recover_database(
    db_path: str | Path,
    export_records: list[dict],
    *,
    backup_path: str | Path | None = None,
    repair: bool = False,
) -> dict:
    """Audit and optionally recover a corrupt database without destructive fallback."""
    database = Path(db_path)
    database.parent.mkdir(parents=True, exist_ok=True)
    integrity = _database_integrity(database)
    corrupt_backup = _backup_corrupt_database(database) if integrity != "ok" else ""
    hash_problems, sensitive_records = _export_problems(export_records)
    result = {
        "writeAllowed": integrity == "ok" and not hash_problems and not sensitive_records,
        "integrity": integrity,
        "backupPath": corrupt_backup,
        "contentHashProblems": hash_problems,
        "sensitiveRecords": sensitive_records,
        "databaseReplaced": False,
        "recoverySource": None,
    }
    if not repair or integrity == "ok":
        return result

    candidate = database.with_name(f".{database.name}.{uuid.uuid4().hex}.recovery.tmp")
    try:
        if backup_path is not None:
            source = Path(backup_path)
            if not source.is_file():
                raise FileNotFoundError(source)
            shutil.copy2(source, candidate)
            _validate_backup_database(candidate)
            recovery_source = "backup"
        else:
            if hash_problems or sensitive_records:
                return result
            _insert_export_records(candidate, export_records)
            if _database_integrity(candidate) != "ok":
                raise sqlite3.DatabaseError("rebuilt database failed integrity_check")
            recovery_source = "export"
        _replace_database(database, candidate)
        result.update({
            "writeAllowed": True,
            "integrity": "ok",
            "databaseReplaced": True,
            "recoverySource": recovery_source,
        })
        return result
    except Exception as exc:
        result["recoveryError"] = f"{type(exc).__name__}: {exc}"
        return result
    finally:
        candidate.unlink(missing_ok=True)
        for suffix in ("-wal", "-shm"):
            Path(f"{candidate}{suffix}").unlink(missing_ok=True)


def _load_jsonl(path: Path) -> list[dict]:
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError("each export line must be an object")
            records.append(value)
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "repair"))
    parser.add_argument("--db", required=True)
    parser.add_argument("--export")
    parser.add_argument("--backup")
    args = parser.parse_args(argv)
    try:
        export_path = Path(args.export) if args.export else None
        if export_path is None and not args.backup:
            raise ValueError("--export or --backup is required")
        repaired = (
            repair_jsonl(export_path)
            if args.action == "repair" and export_path is not None
            else None
        )
        records = _load_jsonl(export_path) if export_path is not None else []
        result = recover_database(
            args.db,
            records,
            backup_path=args.backup,
            repair=args.action == "repair",
        )
        if repaired is not None:
            result["jsonl"] = repaired
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["writeAllowed"] else 2
    except Exception as exc:
        print(json.dumps({"ok": False, "error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
