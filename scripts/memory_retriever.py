#!/usr/bin/env python3
"""Rank reviewed Workers Group memories within a bounded context budget."""

from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import sys
import tomllib
import uuid
from datetime import UTC, datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from memory_guard import redact_and_validate
from memory_store import MemoryStore, utc_now
from workers_group_paths import STATIC_ROOT


TOKEN_RE = re.compile(r"\w+", re.UNICODE)
POLICY_PATH = STATIC_ROOT / "config" / "retrieval-policy.toml"
WEIGHT_FIELDS = {
    "relevance_weight", "scope_weight", "confidence_weight", "authority_weight",
    "recency_weight", "success_weight", "conflict_penalty", "staleness_penalty",
    "harmful_history_penalty",
}
FEEDBACK_USAGES = {"USED", "CITED", "APPLIED", "IGNORED"}
FEEDBACK_OUTCOMES = {"SUCCESS", "FAILURE", "PARTIAL", "UNKNOWN"}


def _tokens(text: str) -> set[str]:
    return {token.casefold() for token in TOKEN_RE.findall(text)}


def _token_count(text: str) -> int:
    return max(1, len(TOKEN_RE.findall(text)))


class MemoryRetriever:
    def __init__(
        self,
        db_path: str | Path,
        force_fallback: bool = False,
        policy_path: str | Path | None = None,
    ):
        self.store = MemoryStore(db_path)
        state = self.store.initialize()
        self.force_fallback = force_fallback
        self.fts5_available = bool(state["fts5"]) and not force_fallback
        self.policy_path = Path(policy_path) if policy_path is not None else POLICY_PATH
        self.weights = self._load_weights(self.policy_path)

    @staticmethod
    def _load_weights(policy_path: Path) -> dict[str, float]:
        try:
            policy = tomllib.loads(policy_path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ValueError(f"invalid retrieval policy: {policy_path}") from exc
        missing = WEIGHT_FIELDS - policy.keys()
        if missing:
            raise ValueError(f"retrieval policy missing weights: {sorted(missing)}")
        weights: dict[str, float] = {}
        for field in WEIGHT_FIELDS:
            value = policy[field]
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not 0 <= float(value) <= 1
            ):
                raise ValueError(f"retrieval policy weight must be numeric from 0 to 1: {field}")
            weights[field] = float(value)
        return weights

    def retrieve(
        self,
        query: str,
        *,
        task_id: str = "",
        role: str = "",
        top_k: int = 8,
        budget_tokens: int = 1200,
        budget_chars: int | None = None,
        scope: str = "repository",
        module: str = "",
        language: str = "",
        framework: str = "",
        error: str = "",
        tool: str = "",
        task_type: str = "",
        acceptance_criterion: str = "",
    ) -> dict:
        if not isinstance(query, str):
            raise TypeError("query must be a string")
        if budget_tokens < 0 or (budget_chars is not None and budget_chars < 0):
            raise ValueError("context budgets must be non-negative")
        safe = redact_and_validate(json.dumps({
            "query": query,
            "taskId": task_id,
            "role": role,
            "scope": scope,
            "module": module,
            "language": language,
            "framework": framework,
            "error": error,
            "tool": tool,
            "taskType": task_type,
            "acceptanceCriterion": acceptance_criterion,
        }, ensure_ascii=False))
        guarded = json.loads(safe["redacted"])
        safe_query = guarded["query"]
        rows, strategy, relevance = self._candidates(safe_query)
        now = datetime.now(UTC)
        ranked: list[dict] = []
        query_tokens = _tokens(safe_query)
        for row in rows:
            item = self.store._row_to_dict(row)
            text = f"{item['key'] or ''} {item['title']} {item['summary']} {item['content']}"
            overlap = len(query_tokens & _tokens(text)) / max(1, len(query_tokens))
            verified = row["last_verified_at"] or row["updated_at"]
            try:
                days = max(0.0, (now - datetime.fromisoformat(verified)).total_seconds() / 86400)
            except (TypeError, ValueError):
                days = 3650
            recency = math.exp(-days / 365)
            tags = {
                str(tag).casefold()
                for tag in json.loads(row["tags_json"])
                if isinstance(tag, str)
            }
            context_checks: list[bool] = []
            if guarded["scope"]:
                context_checks.append(
                    str(row["scope"]).casefold() == guarded["scope"].casefold()
                )
            if guarded["module"]:
                context_checks.append(
                    str(row["module"]).casefold() == guarded["module"].casefold()
                )
            if guarded["role"]:
                context_checks.append(
                    str(row["source_role"]).casefold() == guarded["role"].casefold()
                    or f"role:{guarded['role']}".casefold() in tags
                )
            structured_context = {
                ("language", "programming_language", "programming-language"):
                    guarded["language"],
                ("framework",): guarded["framework"],
                ("error", "error_type", "error-type"): guarded["error"],
                ("tool",): guarded["tool"],
                ("task_type", "task-type", "tasktype"): guarded["taskType"],
                ("acceptance_criterion", "acceptance-criterion", "ac"):
                    guarded["acceptanceCriterion"],
            }
            for aliases, value in structured_context.items():
                if value:
                    folded = value.casefold()
                    context_checks.append(
                        folded in tags
                        or any(f"{field}:{folded}" in tags for field in aliases)
                    )
            context_signal = (
                sum(context_checks) / len(context_checks) if context_checks else 0.0
            )
            helpful_signal = min(
                1.0,
                max(
                    0.0,
                    float(row["success_count"] + row["useful_count"]) / 10,
                ),
            )
            harmful_signal = min(
                1.0,
                max(
                    0.0,
                    float(row["failure_count"] + row["harmful_count"]) / 10,
                ),
            )
            conflict_signal = min(1.0, max(0.0, float(row["conflict_count"])))
            staleness_signal = 0.0
            if row["expires_at"]:
                try:
                    staleness_signal = float(
                        datetime.fromisoformat(row["expires_at"]) <= now
                    )
                except (TypeError, ValueError):
                    staleness_signal = 1.0
            relevance_score = (
                relevance.get(row["id"], overlap)
                * self.weights["relevance_weight"]
            )
            confidence_score = (
                float(row["confidence"]) * self.weights["confidence_weight"]
            )
            authority_score = (
                float(row["authority"]) * self.weights["authority_weight"]
            )
            recency_score = recency * self.weights["recency_weight"]
            context_score = context_signal * self.weights["scope_weight"]
            helpful_score = helpful_signal * self.weights["success_weight"]
            conflict_penalty = conflict_signal * self.weights["conflict_penalty"]
            staleness_penalty = (
                staleness_signal * self.weights["staleness_penalty"]
            )
            harmful_penalty = (
                harmful_signal * self.weights["harmful_history_penalty"]
            )
            score = (
                relevance_score + confidence_score + authority_score
                + recency_score + context_score + helpful_score
                - conflict_penalty - staleness_penalty - harmful_penalty
            )
            item["score"] = round(score, 6)
            item["scoreComponents"] = {
                "relevance": round(relevance_score, 6),
                "confidence": round(confidence_score, 6),
                "authority": round(authority_score, 6),
                "recency": round(recency_score, 6),
                "context": round(context_score, 6),
                "helpfulHistory": round(helpful_score, 6),
                "conflictPenalty": round(conflict_penalty, 6),
                "stalenessPenalty": round(staleness_penalty, 6),
                "harmfulHistoryPenalty": round(harmful_penalty, 6),
            }
            item["tokenCount"] = _token_count(f"{item['summary']} {item['content']}")
            ranked.append(item)
        ranked.sort(key=lambda item: (-item["score"], item["id"]))

        selected: list[dict] = []
        used_tokens = used_chars = 0
        for item in ranked[:max(0, min(int(top_k), 8))]:
            item_chars = len(item["summary"]) + len(item["content"])
            if used_tokens + item["tokenCount"] > budget_tokens:
                continue
            if budget_chars is not None and used_chars + item_chars > budget_chars:
                continue
            selected.append(item)
            used_tokens += item["tokenCount"]
            used_chars += item_chars

        ledger_id = str(uuid.uuid4())
        with self.store._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            entries = selected or [None]
            for item in entries:
                connection.execute(
                    """
                    INSERT INTO retrieval_ledger(
                        id,task_id,memory_id,query,role,retrieved_at,retrieval_score,strategy
                    ) VALUES (?,?,?,?,?,?,?,?)
                    """,
                    (
                        ledger_id if item is None or item is selected[0] else str(uuid.uuid4()),
                        guarded["taskId"], item["id"] if item else None, safe_query,
                        guarded["role"], utc_now(), item["score"] if item else 0.0, strategy,
                    ),
                )
            if selected:
                placeholders = ",".join("?" for _ in selected)
                connection.execute(
                    f"UPDATE memories SET retrieval_count=retrieval_count+1,last_retrieved_at=? "
                    f"WHERE id IN ({placeholders})",
                    (utc_now(), *(item["id"] for item in selected)),
                )
        return {
            "items": selected,
            "strategy": strategy,
            "ledger": ledger_id,
            "budget": {"tokens": used_tokens, "characters": used_chars},
            "queryRedacted": not safe["accepted"],
        }

    def record_feedback(
        self,
        ledger_id: str,
        *,
        usage: str,
        outcome: str,
        helpful: bool,
        evidence: list[str],
        qa_verdict: str = "",
    ) -> dict:
        if not isinstance(ledger_id, str) or not ledger_id:
            raise ValueError("ledger_id is required")
        normalized_usage = str(usage).upper()
        normalized_outcome = str(outcome).upper()
        if normalized_usage not in FEEDBACK_USAGES:
            raise ValueError(f"invalid feedback usage: {usage}")
        if normalized_outcome not in FEEDBACK_OUTCOMES:
            raise ValueError(f"invalid feedback outcome: {outcome}")
        if not isinstance(helpful, bool):
            raise TypeError("helpful must be boolean")
        if normalized_outcome == "SUCCESS" and str(qa_verdict).upper() != "PASS":
            raise ValueError("SUCCESS feedback requires an independent QA PASS verdict")
        if (
            not isinstance(evidence, list)
            or not evidence
            or not all(isinstance(item, str) and item for item in evidence)
        ):
            raise ValueError("feedback evidence must be a non-empty path array")
        payload = {
            "ledgerId": ledger_id,
            "usage": normalized_usage,
            "outcome": normalized_outcome,
            "helpful": helpful,
            "evidence": evidence,
            "qaVerdict": str(qa_verdict).upper(),
        }
        guard = redact_and_validate(
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
        )
        if not guard["accepted"]:
            raise ValueError("feedback contains secret or unnecessary PII")
        evidence_paths: list[str] = []
        for value in evidence:
            path = self.store._readable_repository_file(value, "feedback evidence")
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                raise ValueError("feedback evidence must be readable UTF-8 text") from exc
            if not redact_and_validate(content)["accepted"]:
                raise ValueError("feedback evidence contains secret or unnecessary PII")
            evidence_paths.append(str(path))

        with self.store._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            ledger = connection.execute(
                "SELECT memory_id,helpful FROM retrieval_ledger WHERE id=?",
                (ledger_id,),
            ).fetchone()
            if not ledger:
                raise KeyError(ledger_id)
            if not ledger["memory_id"]:
                raise ValueError("feedback ledger is not bound to a memory")
            if ledger["helpful"] is not None:
                raise ValueError("feedback has already been recorded for this ledger")
            memory = connection.execute(
                "SELECT useful_count,harmful_count FROM memories WHERE id=?",
                (ledger["memory_id"],),
            ).fetchone()
            if not memory:
                raise ValueError("feedback memory binding is missing")
            connection.execute(
                """
                UPDATE retrieval_ledger
                SET usage=?,outcome=?,helpful=?,evidence_json=?
                WHERE id=?
                """,
                (
                    normalized_usage, normalized_outcome, int(helpful),
                    json.dumps(evidence_paths, ensure_ascii=False), ledger_id,
                ),
            )
            counter = "useful_count" if helpful else "harmful_count"
            connection.execute(
                f"UPDATE memories SET {counter}={counter}+1,updated_at=? WHERE id=?",
                (utc_now(), ledger["memory_id"]),
            )
            connection.execute(
                """
                INSERT INTO audit_log(event,memory_id,actor,details_json,created_at)
                VALUES (?,?,?,?,?)
                """,
                (
                    "RETRIEVAL_FEEDBACK_RECORDED",
                    ledger["memory_id"],
                    "system",
                    json.dumps({
                        "ledgerId": ledger_id,
                        "usage": normalized_usage,
                        "outcome": normalized_outcome,
                        "helpful": helpful,
                        "evidence": evidence_paths,
                        "qaVerdict": str(qa_verdict).upper(),
                    }, ensure_ascii=False),
                    utc_now(),
                ),
            )
            counters = connection.execute(
                "SELECT useful_count,harmful_count FROM memories WHERE id=?",
                (ledger["memory_id"],),
            ).fetchone()
        return {
            "recorded": True,
            "ledger": ledger_id,
            "memoryId": ledger["memory_id"],
            "usefulCount": counters["useful_count"],
            "harmfulCount": counters["harmful_count"],
        }

    def _candidates(self, query: str):
        query_tokens = sorted(_tokens(query))
        with self.store._connection() as connection:
            if self.fts5_available and query_tokens:
                expression = " OR ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in query_tokens)
                try:
                    rows = connection.execute(
                        """
                        SELECT m.*, bm25(memories_fts) AS fts_rank,
                            (
                                SELECT COUNT(*) FROM memory_relations r
                                WHERE r.relation='CONFLICTS_WITH'
                                  AND (r.source_id=m.id OR r.target_id=m.id)
                            ) AS conflict_count
                        FROM memories_fts JOIN memories m ON m.id=memories_fts.memory_id
                        WHERE memories_fts MATCH ? AND m.status='ACTIVE'
                        """,
                        (expression,),
                    ).fetchall()
                    return rows, "fts5", {
                        row["id"]: 1.0 / (1.0 + abs(float(row["fts_rank"]))) for row in rows
                    }
                except sqlite3.OperationalError as exc:
                    if "no such table" not in str(exc).casefold():
                        raise
                    self.fts5_available = False
            rows = connection.execute(
                """
                SELECT m.*,
                    (
                        SELECT COUNT(*) FROM memory_relations r
                        WHERE r.relation='CONFLICTS_WITH'
                          AND (r.source_id=m.id OR r.target_id=m.id)
                    ) AS conflict_count
                FROM memories m WHERE m.status='ACTIVE'
                """
            ).fetchall()
        query_set = set(query_tokens)
        relevance = {}
        for row in rows:
            text = f"{row['memory_key'] or ''} {row['title']} {row['summary']} {row['content']}"
            relevance[row["id"]] = len(query_set & _tokens(text)) / max(1, len(query_set))
        return rows, "token-overlap", relevance


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query")
    parser.add_argument("--db", default=".workers-group/runtime/memory.sqlite3")
    parser.add_argument("--task-id", default="")
    parser.add_argument("--role", default="")
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--budget-chars", type=int, default=12000)
    parser.add_argument("--force-fallback", action="store_true")
    parser.add_argument("--policy", default=str(POLICY_PATH))
    parser.add_argument("--module", default="")
    parser.add_argument("--language", default="")
    parser.add_argument("--framework", default="")
    parser.add_argument("--error", default="")
    parser.add_argument("--tool", default="")
    parser.add_argument("--task-type", default="")
    parser.add_argument("--acceptance-criterion", default="")
    parser.add_argument("--feedback-ledger")
    parser.add_argument("--usage")
    parser.add_argument("--outcome")
    parser.add_argument("--helpful", choices=("true", "false"))
    parser.add_argument("--qa-verdict", default="")
    parser.add_argument("--evidence", action="append", default=[])
    args = parser.parse_args(argv)
    try:
        retriever = MemoryRetriever(
            args.db, args.force_fallback, policy_path=args.policy,
        )
        if args.feedback_ledger:
            if args.usage is None or args.outcome is None or args.helpful is None:
                raise ValueError(
                    "--usage, --outcome, and --helpful are required with --feedback-ledger",
                )
            result = retriever.record_feedback(
                args.feedback_ledger,
                usage=args.usage,
                outcome=args.outcome,
                helpful=args.helpful == "true",
                evidence=args.evidence,
                qa_verdict=args.qa_verdict,
            )
        else:
            if args.query is None:
                raise ValueError("--query is required unless recording feedback")
            result = retriever.retrieve(
                args.query, task_id=args.task_id, role=args.role,
                top_k=args.top_k, budget_chars=args.budget_chars,
                module=args.module, language=args.language,
                framework=args.framework, error=args.error, tool=args.tool,
                task_type=args.task_type,
                acceptance_criterion=args.acceptance_criterion,
            )
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
