"""Create a validated Task Charter from a request file."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from state_store import StateStore, find_git_root


def create_task(title: str, request: str, *, verification_mode: str = "basic") -> dict:
    if not title.strip() or not request.strip():
        raise ValueError("title and request must be non-empty")
    if verification_mode not in {"basic", "strict"}:
        raise ValueError("verification_mode must be basic or strict")
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or "task"
    digest = hashlib.sha256((title + "\0" + request).encode("utf-8")).hexdigest()[:12]
    constraints = (
        ["Basic Boss verification with readable evidence and disclosed limitations"]
        if verification_mode == "basic"
        else ["No CLOSED without independent QA PASS and readable evidence"]
    )
    return {
        "schema_version": "1.0",
        "task_id": f"WG-{slug}-{digest}",
        "title": title.strip(),
        "original_request": request.strip(),
        "objective": title.strip(),
        "scope": ["Repository-scoped work described by original_request"],
        "non_goals": [],
        "verification_mode": verification_mode,
        "constraints": constraints,
        "assumptions": [],
        "deliverables": ["Implementation artifacts", "Verification evidence"],
        "acceptance_criteria": [],
        "created_by": "workers_boss",
        "status": "INTAKE",
        "created_at": now,
        "updated_at": now,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", required=True)
    parser.add_argument("--request-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verification-mode", choices=("basic", "strict"), default="basic")
    args = parser.parse_args()
    try:
        charter = create_task(
            args.title,
            args.request_file.read_text(encoding="utf-8"),
            verification_mode=args.verification_mode,
        )
        StateStore(args.output).write_state(charter)
        try:
            root = find_git_root(Path.cwd())
        except (FileNotFoundError, OSError):
            root = None
        if root is not None:
            active_path = root / ".workers-group" / "runtime" / "active-task.json"
            StateStore(active_path).write_state(charter)
        result = {
            "valid": True,
            "task_id": charter["task_id"],
            "output": str(args.output),
            "active_task_registered": root is not None,
        }
    except (OSError, ValueError):
        result = {"valid": False, "errors": ["task input or persistence validation failed"]}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
