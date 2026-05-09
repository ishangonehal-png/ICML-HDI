from __future__ import annotations

import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

REQUIRED_DOC_PATHS = [
    "README.md",
    "docs/README.md",
    "docs/architecture/plan.md",
    "docs/architecture/ui-architecture.md",
    "docs/data-contract/p0-contract-and-mvp50-ops.md",
    "docs/execution/task-backlog.md",
]

REQUIRED_SCRIPT_PATHS = [
    "scripts/build_tcga_matched_cohort.py",
    "scripts/download_tcga_matched_data.sh",
    "scripts/mvp50.py",
    "scripts/validate_matched_cohort.py",
    "scripts/lock_mvp50_manifest.py",
    "scripts/ci/check_data_contract_tooling.py",
    "scripts/ci/check_architecture_coherence.py",
]

REQUIRED_MVP50_MODULE_PATHS = [
    "packages/mvp50/README.md",
    "packages/mvp50/__init__.py",
    "packages/mvp50/cli.py",
    "packages/mvp50/constants.py",
    "packages/mvp50/data_contract_utils.py",
    "packages/mvp50/validate.py",
    "packages/mvp50/lock.py",
]

LEGACY_ROOT_DOC_NAMES = {
    "PLAN.md",
    "TASK.md",
}

LEGACY_ROOT_DOC_GLOBS = [
    "PREDICTIVE_TASKS*",
]


def _tracked_files(*pathspecs: str) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "--", *pathspecs],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def test_required_docs_exist() -> None:
    missing = [path for path in REQUIRED_DOC_PATHS if not (REPO_ROOT / path).is_file()]
    assert not missing, (
        "Missing required documentation files:\n- "
        + "\n- ".join(sorted(missing))
    )


def test_workflow_and_docs_index_exist() -> None:
    required_paths = [
        ".github/workflows",
        ".github/workflows/ci.yml",
        "README.md",
        "docs/README.md",
    ]
    missing = [path for path in required_paths if not (REPO_ROOT / path).exists()]
    assert not missing, (
        "Missing required repo safety infrastructure files:\n- "
        + "\n- ".join(sorted(missing))
    )


def test_no_deprecated_root_docs_return() -> None:
    found = {
        name for name in LEGACY_ROOT_DOC_NAMES if (REPO_ROOT / name).exists()
    }

    for pattern in LEGACY_ROOT_DOC_GLOBS:
        for matched in REPO_ROOT.glob(pattern):
            if matched.is_file():
                found.add(matched.name)

    assert not found, (
        "Deprecated root-level docs are not allowed. Move/keep docs under docs/.\n"
        "Found:\n- "
        + "\n- ".join(sorted(found))
    )


def test_no_tracked_hansons_context_tree() -> None:
    tracked = _tracked_files("hansons-context", "docs/hansons-context")
    assert not tracked, (
        "Legacy hansons-context tree should not be tracked. "
        "Use docs/context instead.\nTracked paths:\n- "
        + "\n- ".join(sorted(tracked))
    )


def test_key_scripts_exist() -> None:
    missing = [path for path in REQUIRED_SCRIPT_PATHS if not (REPO_ROOT / path).is_file()]
    assert not missing, (
        "Missing key scripts required for data contracts / CI:\n- "
        + "\n- ".join(sorted(missing))
    )


def test_mvp50_detachable_module_files_exist() -> None:
    missing = [
        path for path in REQUIRED_MVP50_MODULE_PATHS if not (REPO_ROOT / path).is_file()
    ]
    assert not missing, (
        "Missing MVP50 detachable module files required for wrapper compatibility:\n- "
        + "\n- ".join(sorted(missing))
    )


def test_makefile_ci_includes_architecture_coherence_check() -> None:
    makefile_path = REPO_ROOT / "Makefile"
    assert makefile_path.is_file(), "Makefile is required for local CI-equivalent workflow"

    makefile_text = makefile_path.read_text(encoding="utf-8")
    assert "scripts/ci/check_architecture_coherence.py" in makefile_text, (
        "Makefile test-ci flow must run architecture coherence checks to stay aligned "
        "with CI guardrails."
    )
