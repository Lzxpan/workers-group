"""Validate and atomically store one accountability scorecard."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from runpy import run_path

from state_store import StateStore

validate_document = run_path(str(Path(__file__).with_name("validate_report.py")))["validate_document"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        scorecard = json.loads(args.file.read_text(encoding="utf-8"))
        result = validate_document("scorecard", scorecard)
        if result["valid"]:
            StateStore(args.output).write_state(scorecard)
            result["output"] = str(args.output)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        result = {"valid": False, "errors": [str(exc)]}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
