"""Regression checks for bootstrap import order."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_bootstrap_can_be_imported_without_importing_main_first() -> None:
    """Service/report imports must not depend on FastAPI's import side effects."""
    backend_root = Path(__file__).resolve().parents[1]
    environment = {**os.environ, "DEBUG": "false"}

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.bootstrap import container; print('bootstrap import ok')",
        ],
        cwd=backend_root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip().endswith("bootstrap import ok")
