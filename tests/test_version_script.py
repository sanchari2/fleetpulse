"""Runs the bash suite for the versioning script, so `pytest` covers it too."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent / "test_next_version.sh"


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is not available")
def test_version_script_behaviour():
    # Run from the script's own directory and pass only the file name. On
    # Windows, Git Bash receives a "C:\\Users\\..." argument with the
    # backslashes consumed, and then cannot find the file at all.
    result = subprocess.run(
        ["bash", SCRIPT.name],
        cwd=SCRIPT.parent,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert "checks passed" in result.stdout
