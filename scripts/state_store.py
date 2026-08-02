"""Atomic repository state and file-ownership storage."""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path
from runpy import run_path

redact_and_validate = run_path(str(Path(__file__).with_name("memory_guard.py")))["redact_and_validate"]
GENERATED_TASK_ID = re.compile(r"^WG-[a-z0-9-]+-[0-9a-f]{12}$")


def _persistence_guard(value: object, field: str | None = None) -> bool:
    if isinstance(value, str):
        if field == "task_id" and GENERATED_TASK_ID.fullmatch(value):
            return True
        return redact_and_validate(value)["accepted"]
    if isinstance(value, list):
        return all(_persistence_guard(item) for item in value)
    if isinstance(value, dict):
        return all(
            redact_and_validate(str(key))["accepted"] and _persistence_guard(child, str(key))
            for key, child in value.items()
        )
    return isinstance(value, (bool, int, float)) or value is None


def find_git_root(start: str | Path) -> Path:
    current = Path(start).resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    raise FileNotFoundError(f"Git root not found from {current}")


class StateStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")

    def read_state(self) -> dict:
        if not self.path.exists():
            return {}
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("state must be a JSON object")
        return value

    def write_state(self, state: dict) -> None:
        if not isinstance(state, dict):
            raise TypeError("state must be a dict")
        if not _persistence_guard(state):
            raise ValueError("state rejected by persistence security guard")
        serialized = json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as stream:
                stream.write(serialized)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def claim_files(self, role: str, files: list[str]) -> dict:
        if not role or not files or any(not item for item in files):
            raise ValueError("role and non-empty files are required")
        self._acquire_lock()
        try:
            state = self.read_state()
            claims = state.setdefault("fileClaims", {})
            conflicts = {item: claims[item] for item in files if item in claims and claims[item] != role}
            if conflicts:
                raise RuntimeError(f"file ownership conflict: {conflicts}")
            for item in files:
                claims[item] = role
            self.write_state(state)
            return claims
        finally:
            self.lock_path.unlink(missing_ok=True)

    def _acquire_lock(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(100):
            try:
                descriptor = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(descriptor)
                return
            except FileExistsError:
                time.sleep(0.01)
        raise TimeoutError(f"state lock timeout: {self.lock_path}")
