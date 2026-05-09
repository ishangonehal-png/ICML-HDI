#!/usr/bin/env python3
"""Backward-compatible wrapper for MVP50 cohort validation tooling."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Sequence


def _bootstrap_repo_root() -> Path:
    script_path = Path(__file__).resolve()
    candidates = [script_path.parents[1], *script_path.parents, Path.cwd().resolve()]
    seen: set[Path] = set()

    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if (candidate / "packages" / "mvp50" / "__init__.py").exists():
            if str(candidate) not in sys.path:
                sys.path.insert(0, str(candidate))
            return candidate

    fallback = script_path.parents[1]
    if str(fallback) not in sys.path:
        sys.path.insert(0, str(fallback))
    return fallback


def _normalize_argv(argv: Sequence[str] | None) -> list[str] | None:
    if argv is None:
        return None

    args = list(argv)
    if not args:
        return args

    first_token_name = Path(args[0]).name
    wrapper_aliases = {Path(__file__).name, "validate"}
    if first_token_name in wrapper_aliases:
        return args[1:]
    return args


def _coerce_system_exit_code(exc: SystemExit) -> int:
    code = exc.code
    if isinstance(code, int):
        return code
    return 0 if code is None else 1


_bootstrap_repo_root()

try:
    from packages.mvp50.validate import cli_entrypoint as validate_cli_entrypoint
except ModuleNotFoundError as exc:  # pragma: no cover - defensive bootstrap path
    validate_cli_entrypoint = None
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


def main(argv: Sequence[str] | None = None) -> int:
    if validate_cli_entrypoint is None:
        print(
            "ERROR: Could not import packages.mvp50.validate. "
            "Run this script from a repository checkout containing packages/mvp50/.",
            file=sys.stderr,
        )
        if _IMPORT_ERROR is not None:
            print(f"DETAIL: {_IMPORT_ERROR}", file=sys.stderr)
        return 1

    effective_argv = list(sys.argv[1:]) if argv is None else list(argv)
    argv = _normalize_argv(effective_argv)
    try:
        return validate_cli_entrypoint(argv)
    except SystemExit as exc:
        return _coerce_system_exit_code(exc)


if __name__ == "__main__":
    raise SystemExit(main())
