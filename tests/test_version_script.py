"""Runs the bash suite for the versioning script, so `pytest` covers it too."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent / "test_next_version.sh"


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is not available")
def test_version_script_behaviour():
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert "checks passed" in result.stdout
