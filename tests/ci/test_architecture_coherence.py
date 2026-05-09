from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CHECK_SCRIPT = REPO_ROOT / "scripts" / "ci" / "check_architecture_coherence.py"


def test_architecture_coherence_script_passes() -> None:
    result = subprocess.run(
        [sys.executable, str(CHECK_SCRIPT)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, (
        "Architecture coherence check failed.\n"
        f"STDOUT:\n{result.stdout}\n"
        f"STDERR:\n{result.stderr}"
    )

    assert "Architecture coherence guardrails passed" in result.stdout


def test_architecture_coherence_script_reports_expected_domains() -> None:
    result = subprocess.run(
        [sys.executable, str(CHECK_SCRIPT)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    expected_markers = [
        "Core docs-first files exist",
        "required-docs index resolves",
        "API route groups are coherent",
        "required API endpoints are represented",
        "UI core workflow routes",
    ]

    missing = [marker for marker in expected_markers if marker not in result.stdout]
    assert not missing, (
        "Architecture coherence script output is missing expected status markers:\n- "
        + "\n- ".join(missing)
    )
