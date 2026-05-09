#!/usr/bin/env python3
"""Compile/import smoke checks for optional apps/api backend."""

from __future__ import annotations

import compileall
import importlib.util
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
API_DIR = REPO_ROOT / "apps" / "api"
API_TESTS_DIR = API_DIR / "tests"
ENTRYPOINT_CANDIDATES = [
    API_DIR / "main.py",
    API_DIR / "app" / "main.py",
]
DEFAULT_BACKEND_PYTEST_TIMEOUT_SECONDS = 1200


def _read_backend_pytest_timeout_seconds() -> int:
    raw_value = os.getenv(
        "CI_BACKEND_PYTEST_TIMEOUT_SECONDS",
        str(DEFAULT_BACKEND_PYTEST_TIMEOUT_SECONDS),
    ).strip()

    try:
        timeout_seconds = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(
            "CI_BACKEND_PYTEST_TIMEOUT_SECONDS must be an integer "
            f"(got: {raw_value!r})"
        ) from exc

    if timeout_seconds <= 0:
        raise RuntimeError(
            "CI_BACKEND_PYTEST_TIMEOUT_SECONDS must be > 0 "
            f"(got: {timeout_seconds})"
        )

    return timeout_seconds


def _import_file(path: Path) -> None:
    module_name = f"_ci_backend_smoke_{path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not build import spec for {path}")

    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)  # type: ignore[union-attr]
    except Exception as exc:
        rel_path = path.relative_to(REPO_ROOT)
        raise RuntimeError(f"Import smoke failed for {rel_path}: {exc}") from exc


def _run_backend_pytest() -> None:
    if not API_TESTS_DIR.exists():
        print("apps/api/tests not present; skipping backend pytest checks.")
        return

    env = os.environ.copy()
    pythonpath_entries = [str(API_DIR), str(REPO_ROOT)]
    existing_pythonpath = env.get("PYTHONPATH")
    if existing_pythonpath:
        pythonpath_entries.append(existing_pythonpath)
    env["PYTHONPATH"] = os.pathsep.join(pythonpath_entries)

    timeout_seconds = _read_backend_pytest_timeout_seconds()
    print(
        "Running backend pytest suite "
        f"({API_TESTS_DIR.relative_to(REPO_ROOT)}, timeout={timeout_seconds}s)..."
    )

    try:
        subprocess.run(
            [sys.executable, "-m", "pytest", str(API_TESTS_DIR), "-q"],
            cwd=REPO_ROOT,
            env=env,
            check=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            "Backend pytest timed out after "
            f"{timeout_seconds}s for {API_TESTS_DIR.relative_to(REPO_ROOT)}"
        ) from exc



def main() -> int:
    if not API_DIR.exists():
        print("apps/api not present; skipping backend smoke checks.")
        return 0

    if not API_DIR.is_dir():
        raise RuntimeError("apps/api exists but is not a directory")

    print("Running Python compile smoke under apps/api ...")
    compiled_ok = compileall.compile_dir(str(API_DIR), quiet=1)
    if not compiled_ok:
        raise RuntimeError("Python compile smoke failed for apps/api")

    sys.path.insert(0, str(REPO_ROOT))
    sys.path.insert(0, str(API_DIR))

    imported_paths: list[str] = []
    for entrypoint in ENTRYPOINT_CANDIDATES:
        if entrypoint.is_file():
            rel_path = entrypoint.relative_to(REPO_ROOT)
            print(f"Running import smoke for {rel_path} ...")
            _import_file(entrypoint)
            imported_paths.append(str(rel_path))

    if imported_paths:
        print(
            "apps/api compile + import smoke checks passed for entrypoints: "
            + ", ".join(imported_paths)
        )
    else:
        print(
            "apps/api compile smoke passed; no conventional entrypoint "
            "(main.py or app/main.py) was found for import smoke."
        )

    _run_backend_pytest()

    if API_TESTS_DIR.exists():
        print("apps/api pytest suite passed.")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover - explicit user-facing failure
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
