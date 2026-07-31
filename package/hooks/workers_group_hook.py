"""User-scoped entrypoint for Workers Group lifecycle Hooks."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


CODEX_HOME = Path(__file__).resolve().parents[1]
SCRIPTS = CODEX_HOME / "skills" / "orchestrating-workers-group" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from workers_group_hook import main  # noqa: E402


def _has_project_workers_group_hooks() -> bool:
    """Avoid a second dispatch when a legacy project hook source is present."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            check=False,
            text=True,
            timeout=2,
        )
        root = Path(result.stdout.strip()) if result.returncode == 0 else None
        config = root / ".codex" / "hooks.json" if root else None
        text = config.read_text(encoding="utf-8") if config and config.is_file() else ""
        return "WG-HOOK-001" in text and "WG-HOOK-011" in text
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return False


if __name__ == "__main__":
    if _has_project_workers_group_hooks():
        print(json.dumps({"statusMessage": "打工人集團｜使用專案 Hook，略過全域重複執行"}, ensure_ascii=False))
        raise SystemExit(0)
    raise SystemExit(main())
