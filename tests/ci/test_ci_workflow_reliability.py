from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def _job_block(job_name: str) -> str:
    text = _workflow_text()
    match = re.search(
        rf"(?ms)^  {re.escape(job_name)}:\n(.*?)(?=^  [a-z0-9-]+:\n|\Z)",
        text,
    )
    assert match is not None, f"Job '{job_name}' not found in {WORKFLOW_PATH}"
    return match.group(1)


def test_ci_jobs_define_timeouts() -> None:
    for job_name in (
        "detect-layout",
        "repo-guardrails",
        "backend-checks",
        "frontend-checks",
    ):
        block = _job_block(job_name)
        assert re.search(r"^\s{4}timeout-minutes:\s*\d+\s*$", block, re.MULTILINE), (
            f"Job '{job_name}' must define timeout-minutes to avoid hung CI runs."
        )


def test_repo_guardrails_not_serialized_on_layout_detection() -> None:
    block = _job_block("repo-guardrails")
    assert "needs: detect-layout" not in block, (
        "repo-guardrails should run independently (always-on) instead of waiting on "
        "layout detection."
    )


def test_ci_workflow_enables_dependency_caching() -> None:
    repo_guardrails = _job_block("repo-guardrails")
    backend_checks = _job_block("backend-checks")
    frontend_checks = _job_block("frontend-checks")

    assert re.search(r"cache:\s*['\"]?pip['\"]?", repo_guardrails), (
        "repo-guardrails should enable pip cache in setup-python."
    )
    assert re.search(r"cache:\s*['\"]?pip['\"]?", backend_checks), (
        "backend-checks should enable pip cache in setup-python."
    )
    assert re.search(r"cache:\s*['\"]?npm['\"]?", frontend_checks), (
        "frontend-checks should enable npm cache in setup-node."
    )


def test_ci_step_summaries_use_runtime_step_outcomes() -> None:
    text = _workflow_text()
    expected_markers = [
        "steps.guardrail_pytest.outcome",
        "steps.architecture_coherence.outcome",
        "steps.data_contract_tooling.outcome",
        "steps.backend_smoke.outcome",
        "steps.frontend_checks.outcome",
    ]

    missing = [marker for marker in expected_markers if marker not in text]
    assert not missing, (
        "CI summaries should read real step outcomes (avoid always-✅ summaries). "
        "Missing markers:\n- "
        + "\n- ".join(missing)
    )
