#!/usr/bin/env python3
"""Lightweight CI checks for data-contract scripts.

This script validates that the repository's core cohort/download scripts and
MVP50 detachable operator module remain:
- present,
- syntactically valid,
- callable with --help,
- pinned to expected dataset + delegation guardrail constants.
"""

from __future__ import annotations

import os
import py_compile
import signal
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

BUILD_SCRIPT = REPO_ROOT / "scripts" / "build_tcga_matched_cohort.py"
DOWNLOAD_SCRIPT = REPO_ROOT / "scripts" / "download_tcga_matched_data.sh"
MVP50_UNIFIED_SCRIPT = REPO_ROOT / "scripts" / "mvp50.py"
VALIDATE_WRAPPER_SCRIPT = REPO_ROOT / "scripts" / "validate_matched_cohort.py"
LOCK_WRAPPER_SCRIPT = REPO_ROOT / "scripts" / "lock_mvp50_manifest.py"

MVP50_MODULE_DIR = REPO_ROOT / "packages" / "mvp50"
MVP50_MODULE_FILES = [
    MVP50_MODULE_DIR / "__init__.py",
    MVP50_MODULE_DIR / "cli.py",
    MVP50_MODULE_DIR / "constants.py",
    MVP50_MODULE_DIR / "data_contract_utils.py",
    MVP50_MODULE_DIR / "validate.py",
    MVP50_MODULE_DIR / "lock.py",
]

CORE_DATA_CONTRACT_PATHS = [BUILD_SCRIPT, DOWNLOAD_SCRIPT]
MVP50_ENTRYPOINT_PATHS = [
    MVP50_UNIFIED_SCRIPT,
    VALIDATE_WRAPPER_SCRIPT,
    LOCK_WRAPPER_SCRIPT,
]

DEFAULT_COMMAND_TIMEOUT_SECONDS = 90

REQUIRED_DOWNLOAD_LITERALS = [
    'PROJECT="TCGA-LUAD"',
    "EXPECTED_COHORT_CASES=475",
    "EXPECTED_MANIFEST_ROWS=1901",
    "EXPECTED_MANIFEST_ROWS=1426",
    "EXPECTED_MANIFEST_ROWS=951",
    "EXPECTED_MANIFEST_ROWS=950",
    "EXPECTED_MANIFEST_ROWS=475",
    "EXPECTED_PDF_ROWS=475",
    "EXPECTED_XML_ROWS=475",
]

REQUIRED_BUILD_SYMBOLS = [
    "def build_matched_cohort",
    "def parse_args",
    "def main",
]

REQUIRED_WRAPPER_LITERALS: dict[Path, list[str]] = {
    MVP50_UNIFIED_SCRIPT: [
        "from packages.mvp50.cli import cli_entrypoint as module_cli_entrypoint",
        "return module_cli_entrypoint(argv)",
    ],
    VALIDATE_WRAPPER_SCRIPT: [
        "from packages.mvp50.validate import cli_entrypoint as validate_cli_entrypoint",
        "return validate_cli_entrypoint(argv)",
    ],
    LOCK_WRAPPER_SCRIPT: [
        "from packages.mvp50.lock import cli_entrypoint as lock_cli_entrypoint",
        "return lock_cli_entrypoint(argv)",
    ],
}

REQUIRED_MVP50_MODULE_SYMBOLS: dict[Path, list[str]] = {
    MVP50_MODULE_DIR / "cli.py": [
        "def build_parser",
        "def main",
        "def cli_entrypoint",
    ],
    MVP50_MODULE_DIR / "validate.py": [
        "def add_arguments",
        "def run",
        "def cli_entrypoint",
    ],
    MVP50_MODULE_DIR / "lock.py": [
        "def add_arguments",
        "def run",
        "def cli_entrypoint",
    ],
}


def _terminate_timed_out_process(
    process: subprocess.Popen[str], *, grace_seconds: float = 5.0
) -> None:
    if process.poll() is not None:
        return

    sent_group_term = False
    if hasattr(os, "killpg"):
        try:
            os.killpg(process.pid, signal.SIGTERM)
            sent_group_term = True
        except ProcessLookupError:
            return

    if not sent_group_term:
        process.terminate()

    try:
        process.wait(timeout=grace_seconds)
        return
    except subprocess.TimeoutExpired:
        pass

    if sent_group_term and hasattr(os, "killpg"):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
    else:
        process.kill()

    try:
        process.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        # Defensive fallback: process is still not reaped after SIGKILL.
        pass


def _run(
    cmd: list[str],
    *,
    timeout_seconds: int = DEFAULT_COMMAND_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[str]:
    process: subprocess.Popen[str] | None = None
    try:
        process = subprocess.Popen(
            cmd,
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        if process is not None:
            _terminate_timed_out_process(process)
        raise RuntimeError(
            f"Command timed out after {timeout_seconds}s: {' '.join(cmd)}"
        ) from exc
    except OSError as exc:
        raise RuntimeError(f"Failed to start command: {' '.join(cmd)}") from exc

    result = subprocess.CompletedProcess(
        cmd,
        process.returncode,
        stdout,
        stderr,
    )

    if result.returncode != 0:
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()
        detail_parts = [part for part in (stderr, stdout) if part]
        detail = "\n".join(detail_parts) if detail_parts else "(no output)"
        raise RuntimeError(
            f"Command failed ({' '.join(cmd)}) with exit code {result.returncode}:\n{detail}"
        )

    return result


def _assert_exists(path: Path) -> None:
    if not path.is_file():
        raise RuntimeError(
            f"Required file is missing: {path.relative_to(REPO_ROOT)}"
        )


def _assert_help_contains(
    result: subprocess.CompletedProcess[str],
    *,
    snippets: list[str],
    context: str,
) -> None:
    missing = [snippet for snippet in snippets if snippet not in result.stdout]
    if missing:
        bullet_list = "\n- ".join(missing)
        raise RuntimeError(
            f"Help output for {context} is missing expected snippets:\n- {bullet_list}\n"
            f"Observed help output:\n{result.stdout.strip() or '(empty)'}"
        )


def _check_core_scripts() -> None:
    py_compile.compile(str(BUILD_SCRIPT), doraise=True)
    _run([sys.executable, str(BUILD_SCRIPT), "--help"], timeout_seconds=30)

    _run(["bash", "-n", str(DOWNLOAD_SCRIPT)], timeout_seconds=30)
    _run(["bash", str(DOWNLOAD_SCRIPT), "--help"], timeout_seconds=30)



def _check_mvp50_entrypoints() -> None:
    for path in [*MVP50_ENTRYPOINT_PATHS, *MVP50_MODULE_FILES]:
        if path.suffix == ".py":
            py_compile.compile(str(path), doraise=True)

    unified_help = _run(
        [sys.executable, str(MVP50_UNIFIED_SCRIPT), "--help"],
        timeout_seconds=30,
    )
    _assert_help_contains(
        unified_help,
        snippets=["validate", "lock"],
        context="scripts/mvp50.py --help",
    )

    validate_help = _run(
        [sys.executable, str(VALIDATE_WRAPPER_SCRIPT), "--help"],
        timeout_seconds=30,
    )
    _assert_help_contains(
        validate_help,
        snippets=["--required-modalities", "--fail-on-missing"],
        context="scripts/validate_matched_cohort.py --help",
    )

    lock_help = _run(
        [sys.executable, str(LOCK_WRAPPER_SCRIPT), "--help"],
        timeout_seconds=30,
    )
    _assert_help_contains(
        lock_help,
        snippets=["--allow-incomplete", "--subset-size"],
        context="scripts/lock_mvp50_manifest.py --help",
    )

    _run(
        [
            sys.executable,
            "-c",
            (
                "import packages.mvp50.cli; "
                "import packages.mvp50.validate; "
                "import packages.mvp50.lock"
            ),
        ],
        timeout_seconds=30,
    )



def _check_script_contract_literals() -> None:
    download_text = DOWNLOAD_SCRIPT.read_text(encoding="utf-8")
    missing_literals = [
        literal for literal in REQUIRED_DOWNLOAD_LITERALS if literal not in download_text
    ]
    if missing_literals:
        bullet_list = "\n- ".join(missing_literals)
        raise RuntimeError(
            "download_tcga_matched_data.sh lost required locked constants:\n"
            f"- {bullet_list}"
        )

    build_text = BUILD_SCRIPT.read_text(encoding="utf-8")
    missing_symbols = [
        symbol for symbol in REQUIRED_BUILD_SYMBOLS if symbol not in build_text
    ]
    if missing_symbols:
        bullet_list = "\n- ".join(missing_symbols)
        raise RuntimeError(
            "build_tcga_matched_cohort.py is missing expected callable symbols:\n"
            f"- {bullet_list}"
        )

    for wrapper_path, snippets in REQUIRED_WRAPPER_LITERALS.items():
        wrapper_text = wrapper_path.read_text(encoding="utf-8")
        missing_wrapper_snippets = [
            snippet for snippet in snippets if snippet not in wrapper_text
        ]
        if missing_wrapper_snippets:
            bullet_list = "\n- ".join(missing_wrapper_snippets)
            raise RuntimeError(
                f"{wrapper_path.relative_to(REPO_ROOT)} lost required MVP50 delegation snippets:\n"
                f"- {bullet_list}"
            )



def _check_module_symbol_contracts() -> None:
    for module_path, required_symbols in REQUIRED_MVP50_MODULE_SYMBOLS.items():
        module_text = module_path.read_text(encoding="utf-8")
        missing_symbols = [
            symbol for symbol in required_symbols if symbol not in module_text
        ]
        if missing_symbols:
            bullet_list = "\n- ".join(missing_symbols)
            raise RuntimeError(
                f"{module_path.relative_to(REPO_ROOT)} is missing expected public symbols:\n"
                f"- {bullet_list}"
            )



def main() -> int:
    for path in [*CORE_DATA_CONTRACT_PATHS, *MVP50_ENTRYPOINT_PATHS, *MVP50_MODULE_FILES]:
        _assert_exists(path)
    print("✅ Data-contract core + MVP50 module files exist")

    _check_core_scripts()
    print("✅ Core cohort/download scripts are callable and syntax-valid")

    _check_mvp50_entrypoints()
    print("✅ MVP50 detachable module entrypoints are callable")

    _check_script_contract_literals()
    print("✅ Dataset constants and wrapper delegation contracts are intact")

    _check_module_symbol_contracts()
    print("✅ MVP50 module public symbol contracts are intact")

    print("✅ Data-contract tooling checks passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover - explicit user-facing failure
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
