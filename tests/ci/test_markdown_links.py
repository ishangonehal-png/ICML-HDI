from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlparse


REPO_ROOT = Path(__file__).resolve().parents[2]
MARKDOWN_LINK_PATTERN = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")

SKIP_SCHEMES = {
    "http",
    "https",
    "mailto",
    "tel",
    "data",
}

SKIP_DIR_NAMES = {
    ".git",
    "node_modules",
    ".venv",
    ".venv-ci",
    "__pycache__",
    ".next",
}


def _strip_fenced_code_blocks(text: str) -> str:
    return re.sub(r"```.*?```", "", text, flags=re.DOTALL)


def _markdown_files() -> list[Path]:
    files: list[Path] = []
    for path in REPO_ROOT.rglob("*.md"):
        if any(part in SKIP_DIR_NAMES for part in path.parts):
            continue
        files.append(path)
    return sorted(files)


def _clean_target(raw_target: str) -> str:
    target = raw_target.strip()

    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1].strip()

    # Handle optional markdown title syntax: (path "title")
    if " " in target and not target.startswith(("http://", "https://")):
        first, rest = target.split(" ", 1)
        if rest.lstrip().startswith(("\"", "'")):
            target = first

    return target


def _resolve_local_link(source_file: Path, target: str) -> Path | None:
    parsed = urlparse(target)
    if parsed.scheme in SKIP_SCHEMES:
        return None

    if target.startswith("#"):
        return None

    path_part = unquote(parsed.path)
    if not path_part:
        return None

    if path_part.startswith("/"):
        return (REPO_ROOT / path_part.lstrip("/")).resolve()

    return (source_file.parent / path_part).resolve()


def test_markdown_local_links_resolve() -> None:
    failures: list[str] = []

    for source_file in _markdown_files():
        text = _strip_fenced_code_blocks(source_file.read_text(encoding="utf-8"))

        for match in MARKDOWN_LINK_PATTERN.finditer(text):
            raw_target = match.group(1)
            target = _clean_target(raw_target)
            resolved = _resolve_local_link(source_file, target)
            if resolved is None:
                continue

            if not resolved.exists():
                failures.append(
                    f"{source_file.relative_to(REPO_ROOT)} -> {raw_target} "
                    f"(resolved: {resolved})"
                )

    assert not failures, (
        "Found broken markdown local links:\n- "
        + "\n- ".join(failures)
    )
