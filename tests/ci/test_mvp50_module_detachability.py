from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
MVP50_SCRIPT = REPO_ROOT / "scripts" / "mvp50.py"
VALIDATE_WRAPPER = REPO_ROOT / "scripts" / "validate_matched_cohort.py"
LOCK_WRAPPER = REPO_ROOT / "scripts" / "lock_mvp50_manifest.py"
MODULE_CLI_SCRIPT = REPO_ROOT / "packages" / "mvp50" / "cli.py"


def _run(
    cmd: list[str],
    *,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=cwd or REPO_ROOT,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize(
    ("script_path", "expected_marker"),
    [
        (MVP50_SCRIPT, "validate"),
        (VALIDATE_WRAPPER, "--required-modalities"),
        (LOCK_WRAPPER, "--allow-incomplete"),
    ],
)
def test_cli_help_is_cwd_agnostic(
    script_path: Path,
    expected_marker: str,
    tmp_path: Path,
) -> None:
    result = _run([sys.executable, str(script_path), "--help"], cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    assert expected_marker in result.stdout


def test_unified_cli_help_lists_subcommands() -> None:
    result = _run([sys.executable, str(MVP50_SCRIPT), "--help"])

    assert result.returncode == 0, result.stderr
    assert "validate" in result.stdout
    assert "lock" in result.stdout


def test_validate_wrapper_help_preserves_legacy_flags() -> None:
    result = _run([sys.executable, str(VALIDATE_WRAPPER), "--help"])

    assert result.returncode == 0, result.stderr
    assert "--required-modalities" in result.stdout
    assert "--fail-on-missing" in result.stdout


def test_lock_wrapper_help_preserves_legacy_flags() -> None:
    result = _run([sys.executable, str(LOCK_WRAPPER), "--help"])

    assert result.returncode == 0, result.stderr
    assert "--allow-incomplete" in result.stdout
    assert "--subset-size" in result.stdout


def test_unified_cli_invalid_subcommand_returns_argparse_code() -> None:
    result = _run([sys.executable, str(MVP50_SCRIPT), "not-a-command"])

    assert result.returncode == 2
    assert "invalid choice" in result.stderr.lower()


def test_module_cli_script_executes_without_relative_import_errors() -> None:
    result = _run([sys.executable, str(MODULE_CLI_SCRIPT), "--help"])

    assert result.returncode == 0, result.stderr
    assert "validate" in result.stdout
    assert "lock" in result.stdout
    assert "attempted relative import" not in result.stderr.lower()


def test_module_cli_script_invalid_subcommand_matches_exit_code_2() -> None:
    result = _run([sys.executable, str(MODULE_CLI_SCRIPT), "nope"])

    assert result.returncode == 2
    assert "invalid choice" in result.stderr.lower()


def test_module_cli_dash_m_help_has_no_runtime_warning() -> None:
    result = _run([sys.executable, "-m", "packages.mvp50.cli", "--help"])

    assert result.returncode == 0, result.stderr
    assert "runtimewarning" not in result.stderr.lower()
    assert "validate" in result.stdout
    assert "lock" in result.stdout


def test_validate_wrapper_accepts_redundant_validate_token_in_subprocess(tmp_path: Path) -> None:
    missing_cohort = tmp_path / "missing-cohort.csv"

    result = _run(
        [
            sys.executable,
            str(VALIDATE_WRAPPER),
            "validate",
            "--cohort-csv",
            str(missing_cohort),
            "--dry-run",
        ]
    )

    assert result.returncode == 1
    assert "cohort csv not found" in result.stderr.lower()


def test_lock_wrapper_accepts_redundant_lock_token_in_subprocess(tmp_path: Path) -> None:
    missing_cohort = tmp_path / "missing-cohort.csv"
    missing_manifest = tmp_path / "missing-manifest.tsv"

    result = _run(
        [
            sys.executable,
            str(LOCK_WRAPPER),
            "lock",
            "--cohort-csv",
            str(missing_cohort),
            "--manifest-tsv",
            str(missing_manifest),
            "--dry-run",
        ]
    )

    assert result.returncode == 1
    assert "cohort csv not found" in result.stderr.lower()


def test_unified_wrapper_delegates_to_module_entrypoint(monkeypatch) -> None:
    wrapper = importlib.import_module("scripts.mvp50")
    calls: dict[str, object] = {}

    def fake_delegate(argv=None):
        calls["argv"] = argv
        return 5

    monkeypatch.setattr(wrapper, "module_cli_entrypoint", fake_delegate)

    assert wrapper.main(["validate", "--dry-run"]) == 5
    assert calls["argv"] == ["validate", "--dry-run"]


def test_validate_wrapper_delegates_to_module_entrypoint(monkeypatch) -> None:
    wrapper = importlib.import_module("scripts.validate_matched_cohort")
    calls: dict[str, object] = {}

    def fake_delegate(argv=None):
        calls["argv"] = argv
        return 7

    monkeypatch.setattr(wrapper, "validate_cli_entrypoint", fake_delegate)

    assert wrapper.main(["--dry-run"]) == 7
    assert calls["argv"] == ["--dry-run"]


def test_lock_wrapper_delegates_to_module_entrypoint(monkeypatch) -> None:
    wrapper = importlib.import_module("scripts.lock_mvp50_manifest")
    calls: dict[str, object] = {}

    def fake_delegate(argv=None):
        calls["argv"] = argv
        return 11

    monkeypatch.setattr(wrapper, "lock_cli_entrypoint", fake_delegate)

    assert wrapper.main(["--dry-run"]) == 11
    assert calls["argv"] == ["--dry-run"]


def test_validate_wrapper_strips_redundant_validate_token(monkeypatch) -> None:
    wrapper = importlib.import_module("scripts.validate_matched_cohort")
    calls: dict[str, object] = {}

    def fake_delegate(argv=None):
        calls["argv"] = argv
        return 19

    monkeypatch.setattr(wrapper, "validate_cli_entrypoint", fake_delegate)

    assert wrapper.main(["validate", "--dry-run"]) == 19
    assert calls["argv"] == ["--dry-run"]


def test_lock_wrapper_strips_redundant_lock_token(monkeypatch) -> None:
    wrapper = importlib.import_module("scripts.lock_mvp50_manifest")
    calls: dict[str, object] = {}

    def fake_delegate(argv=None):
        calls["argv"] = argv
        return 23

    monkeypatch.setattr(wrapper, "lock_cli_entrypoint", fake_delegate)

    assert wrapper.main(["lock", "--dry-run"]) == 23
    assert calls["argv"] == ["--dry-run"]


def test_script_wrappers_coerce_system_exit_from_delegates(monkeypatch) -> None:
    validate_wrapper = importlib.import_module("scripts.validate_matched_cohort")
    lock_wrapper = importlib.import_module("scripts.lock_mvp50_manifest")
    unified_wrapper = importlib.import_module("scripts.mvp50")

    def fake_parse_exit(_argv=None):
        raise SystemExit(2)

    monkeypatch.setattr(validate_wrapper, "validate_cli_entrypoint", fake_parse_exit)
    monkeypatch.setattr(lock_wrapper, "lock_cli_entrypoint", fake_parse_exit)
    monkeypatch.setattr(unified_wrapper, "module_cli_entrypoint", fake_parse_exit)

    assert validate_wrapper.main(["--unknown"]) == 2
    assert lock_wrapper.main(["--unknown"]) == 2
    assert unified_wrapper.main(["--unknown"]) == 2


def test_unified_cli_dispatches_to_module_core_functions(monkeypatch) -> None:
    cli_module = importlib.import_module("packages.mvp50.cli")
    validate_module = importlib.import_module("packages.mvp50.validate")
    lock_module = importlib.import_module("packages.mvp50.lock")

    validate_calls: dict[str, object] = {}
    lock_calls: dict[str, object] = {}

    def fake_validate_run(args):
        validate_calls["args"] = args
        return 13

    def fake_lock_run(args):
        lock_calls["args"] = args
        return 17

    monkeypatch.setattr(validate_module, "run", fake_validate_run)
    monkeypatch.setattr(lock_module, "run", fake_lock_run)

    assert cli_module.main(["validate"]) == 13
    assert cli_module.main(["lock"]) == 17

    assert getattr(validate_calls["args"], "cohort_csv", None) is not None
    assert getattr(lock_calls["args"], "manifest_tsv", None) is not None
