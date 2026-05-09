"""Detachable MVP50 module for data-contract validation and deterministic lock tooling."""

from __future__ import annotations

from typing import Sequence


def cli_entrypoint(argv: Sequence[str] | None = None) -> int:
    """Run the unified MVP50 CLI entrypoint."""
    from .cli import cli_entrypoint as _cli_entrypoint

    return _cli_entrypoint(argv)


def lock_main(argv: Sequence[str] | None = None) -> int:
    """Run deterministic MVP lock generation CLI."""
    from .lock import main as _lock_main

    return _lock_main(argv)


def validate_main(argv: Sequence[str] | None = None) -> int:
    """Run matched cohort validation CLI."""
    from .validate import main as _validate_main

    return _validate_main(argv)


__all__ = ["cli_entrypoint", "lock_main", "validate_main"]
