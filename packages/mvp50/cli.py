#!/usr/bin/env python3
"""Unified operator CLI for MVP50 data-contract workflows."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable, Sequence

if __package__:
    from . import lock, validate
else:  # pragma: no cover - direct-file execution path (python packages/mvp50/cli.py ...)
    REPO_ROOT = Path(__file__).resolve().parents[2]
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from packages.mvp50 import lock, validate


Handler = Callable[[argparse.Namespace], int]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "MVP50 operator tooling for deterministic cohort validation and lock generation."
        )
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate cohort completeness against the canonical contract.",
        description=(
            "Validate that each case in a matched TCGA cohort has all required modalities "
            "defined by the canonical data contract."
        ),
    )
    validate.add_arguments(validate_parser)
    validate_parser.set_defaults(_handler=validate.run)

    lock_parser = subparsers.add_parser(
        "lock",
        help="Deterministically lock MVP subset and emit provenance/checksum artifacts.",
        description=(
            "Lock a deterministic MVP subset (default 50 cases) from a matched TCGA cohort "
            "and generate reproducibility artifacts."
        ),
    )
    lock.add_arguments(lock_parser)
    lock_parser.set_defaults(_handler=lock.run)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    handler: Handler | None = getattr(args, "_handler", None)
    if handler is None:
        parser.error("No command handler was configured.")

    delattr(args, "_handler")
    return handler(args)


def _coerce_system_exit_code(exc: SystemExit) -> int:
    code = exc.code
    if isinstance(code, int):
        return code
    return 0 if code is None else 1


def cli_entrypoint(argv: Sequence[str] | None = None) -> int:
    try:
        return main(argv)
    except SystemExit as exc:
        return _coerce_system_exit_code(exc)
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(cli_entrypoint())
