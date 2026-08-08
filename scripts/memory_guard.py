#!/usr/bin/env python3
"""Redact secrets and unnecessary PII before Workers Group persistence."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter


_PATTERNS = (
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)", re.I | re.S)),
    ("connection_uri", re.compile(r"\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis)://[^\s\"']+", re.I)),
    ("email", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)),
    ("bearer_token", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}", re.I)),
    ("api_key", re.compile(r"\b(?:sk|pk|rk)-(?:test-)?[A-Za-z0-9_-]{8,}\b", re.I)),
    ("credential", re.compile(r"\b(?:password|passwd|pwd|access[_-]?token|api[_-]?key|cookie|credential)\s*[:=]\s*[^\s,;\"}]+", re.I)),
    ("taiwan_id", re.compile(r"\b[A-Z][12]\d{8}\b", re.I)),
    ("phone", re.compile(r"(?<![A-Za-z0-9])(?:\+?886[- ]?)?0?9\d{2}[- ]?\d{3}[- ]?\d{3}(?![A-Za-z0-9])")),
)
_TOKEN = re.compile(r"\b[A-Za-z0-9+/_=-]{32,}\b")
_SHA256 = re.compile(r"^[0-9a-f]{64}$", re.I)
_GENERATED_TASK_ID = re.compile(
    r"^WG-(?P<slug>[a-z0-9]+(?:-[a-z0-9]+)*)-[0-9a-f]{12}$",
)


def _entropy(value: str) -> float:
    counts = Counter(value)
    return -sum((count / len(value)) * math.log2(count / len(value)) for count in counts.values())


def _looks_high_entropy(value: str) -> bool:
    classes = sum(bool(re.search(pattern, value)) for pattern in (r"[a-z]", r"[A-Z]", r"\d"))
    return classes >= 3 and _entropy(value) >= 4.15


def _is_generated_task_id(value: str) -> bool:
    match = _GENERATED_TASK_ID.fullmatch(value)
    return bool(match and len(match.group("slug")) <= 40)


def redact_and_validate(text: str) -> dict:
    """Return a safe rendering and findings; original sensitive values are never returned."""
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    redacted = text
    findings: list[str] = []
    for kind, pattern in _PATTERNS:
        redacted, count = pattern.subn(f"[REDACTED:{kind}]", redacted)
        if count:
            findings.extend([kind] * count)

    def redact_entropy(match: re.Match[str]) -> str:
        value = match.group(0)
        if _is_generated_task_id(value) or _SHA256.fullmatch(value):
            return value
        if not _looks_high_entropy(value):
            return value
        findings.append("high_entropy")
        return "[REDACTED:high_entropy]"

    redacted = _TOKEN.sub(redact_entropy, redacted)
    return {"accepted": not findings, "redacted": redacted, "findings": sorted(set(findings))}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text")
    args = parser.parse_args(argv)
    result = redact_and_validate(args.text if args.text is not None else sys.stdin.read())
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
