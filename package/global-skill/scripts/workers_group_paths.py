"""Stable locations for the globally installed Workers Group runtime."""

from __future__ import annotations

from pathlib import Path


SCRIPT_FILE = Path(__file__).resolve()
SKILL_ROOT = SCRIPT_FILE.parents[1]
CODEX_HOME = SCRIPT_FILE.parents[3]
USER_HOME = CODEX_HOME.parent
STATIC_ROOT = USER_HOME / ".workers-group"
