"""Shared, lazy-loading helpers for Workers Group governance tests."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
CODEX_HOME = ROOT / ".codex"
SCRIPTS = CODEX_HOME / "skills" / "orchestrating-workers-group" / "scripts"


class WorkersGroupTestCase(unittest.TestCase):
    """Keep production imports inside tests so discovery remains reliable."""

    def source_module(self, filename: str):
        path = SCRIPTS / filename
        self.assertTrue(path.is_file(), f"missing production module: {path.relative_to(ROOT)}")
        module_name = f"workers_group_test_{filename.replace('.', '_')}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        self.assertIsNotNone(spec, f"unable to load module spec: {path}")
        module = importlib.util.module_from_spec(spec)
        sys.path.insert(0, str(SCRIPTS))
        try:
            assert spec.loader is not None
            spec.loader.exec_module(module)
        except Exception as exc:  # reported as a test assertion, never discovery error
            self.fail(f"cannot import {path.relative_to(ROOT)}: {exc}")
        finally:
            sys.path.remove(str(SCRIPTS))
        return module

    def temp_dir(self):
        return tempfile.TemporaryDirectory(prefix="workers-group-test-")

    def hook(self, payload, *, malformed: bool = False):
        hook = CODEX_HOME / "hooks" / "workers_group_hook.py"
        self.assertTrue(hook.is_file(), f"missing hook entrypoint: {hook.relative_to(ROOT)}")
        raw = "{not-json" if malformed else json.dumps(payload)
        with self.temp_dir() as directory:
            root = Path(directory)
            (root / ".git").mkdir()
            return subprocess.run(
                [sys.executable, str(hook)],
                input=raw,
                text=True,
                encoding="utf-8",
                capture_output=True,
                cwd=root,
                timeout=10,
                env={**os.environ, "PYTHONUTF8": "1"},
            )

    def load_json(self, relative_path: str):
        path = ROOT / relative_path
        self.assertTrue(path.is_file(), f"missing file: {relative_path}")
        return json.loads(path.read_text(encoding="utf-8"))
