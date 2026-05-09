from __future__ import annotations

import glob
import re
from pathlib import Path
from typing import Iterable

_DX_SUFFIX_PATTERN = re.compile(r"-DX[^-_.]*$", re.IGNORECASE)
_DX_TOKEN_PATTERN = re.compile(r"(DX[^-_.]*)", re.IGNORECASE)
_TCGA_CASE_PATTERN = re.compile(r"^([A-Za-z0-9]+-[A-Za-z0-9]+-[A-Za-z0-9]+)")
_TCGA_CASE_EMBEDDED_PATTERN = re.compile(r"(TCGA-[A-Za-z0-9]+-[A-Za-z0-9]+)", re.IGNORECASE)

_ARTIFACT_SUFFIXES = (".json",)
_HEATMAP_SUFFIXES = (
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".tif",
    ".tiff",
)
_WSI_SUFFIXES = (
    ".svs",
    ".tif",
    ".tiff",
    ".ndpi",
    ".mrxs",
    ".scn",
    ".vms",
    ".vmu",
    ".bif",
    ".qptiff",
    ".isyntax",
)


def _normalize_identifier(identifier: str) -> str:
    return identifier.strip()


def _normalize_suffixes(suffixes: Iterable[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for suffix in suffixes:
        candidate = suffix.lower()
        if not candidate.startswith("."):
            candidate = f".{candidate}"
        if candidate in seen:
            continue
        seen.add(candidate)
        normalized.append(candidate)
    return tuple(normalized)


def _add_candidate(candidates: list[str], seen: set[str], value: str) -> None:
    normalized = value.strip()
    if not normalized or normalized in seen:
        return
    seen.add(normalized)
    candidates.append(normalized)


def derive_short_case_id(identifier: str) -> str:
    """Derive a stable short case identifier from potentially long slide/artifact ids."""
    normalized = _normalize_identifier(identifier)
    if not normalized:
        return normalized

    token = Path(normalized).name
    tcga_match = _TCGA_CASE_PATTERN.match(token)
    if tcga_match is not None:
        return tcga_match.group(1)

    token_stem = Path(token).stem
    embedded_tcga_match = _TCGA_CASE_EMBEDDED_PATTERN.search(token_stem)
    if embedded_tcga_match is not None:
        return embedded_tcga_match.group(1).upper()

    if "-" not in token:
        return _DX_SUFFIX_PATTERN.sub("", token)

    stem = _DX_SUFFIX_PATTERN.sub("", token)
    parts = stem.split("-")
    if len(parts) >= 3:
        return "-".join(parts[:3])
    return stem


def derive_short_slide_id(identifier: str) -> str:
    """Derive a short slide id like `TCGA-xx-xxxx-DX1` from longer ids when possible."""
    normalized = _normalize_identifier(identifier)
    if not normalized:
        return normalized

    token = Path(normalized).name
    case_id = derive_short_case_id(token)
    dx_match = _DX_TOKEN_PATTERN.search(token)
    if dx_match is None:
        return token

    dx_token = dx_match.group(1)
    if not case_id:
        return dx_token
    return f"{case_id}-{dx_token}"


def derive_case_id_from_slide_id(slide_id: str) -> str:
    """Resolve case_id from slide_id with support for full/short id variants."""
    normalized = _normalize_identifier(slide_id)
    if not normalized:
        return normalized

    short_case_id = derive_short_case_id(normalized)
    if short_case_id:
        return short_case_id
    return _DX_SUFFIX_PATTERN.sub("", normalized)


def enumerate_candidate_identifiers(identifier: str) -> list[str]:
    """Enumerate robust identifier candidates for exact and wildcard file resolution."""
    normalized = _normalize_identifier(identifier)
    if not normalized:
        return []

    candidates: list[str] = []
    seen: set[str] = set()

    _add_candidate(candidates, seen, normalized)

    token = Path(normalized).name
    if token != normalized:
        _add_candidate(candidates, seen, token)

    stem = Path(token).stem
    if stem and stem != token:
        _add_candidate(candidates, seen, stem)

    _add_candidate(candidates, seen, derive_short_slide_id(normalized))
    _add_candidate(candidates, seen, derive_short_case_id(normalized))
    _add_candidate(candidates, seen, _DX_SUFFIX_PATTERN.sub("", normalized))

    expanded = list(candidates)
    for candidate in expanded:
        _add_candidate(candidates, seen, candidate.upper())
        _add_candidate(candidates, seen, candidate.lower())

    return candidates


def _relative_posix(directory: Path, path: Path) -> str:
    try:
        return path.relative_to(directory).as_posix()
    except ValueError:
        return path.as_posix()


def _path_depth(directory: Path, path: Path) -> int:
    relative = _relative_posix(directory, path)
    return len(Path(relative).parts)


def _score_candidate(
    *,
    identifier_rank: int,
    case_match_rank: int,
    slide_match_rank: int,
    is_symlink: bool,
    pattern_rank: int,
    directory: Path,
    path: Path,
) -> tuple[int, int, int, int, int, int, int, str]:
    relative_path = _relative_posix(directory, path).lower()
    return (
        identifier_rank,
        case_match_rank,
        slide_match_rank,
        1 if is_symlink else 0,
        pattern_rank,
        _path_depth(directory, path),
        len(path.name),
        relative_path,
    )


def _iter_pattern_matches(directory: Path, pattern: str) -> Iterable[Path]:
    # Root-level and recursive lookup to avoid symlink-only flattening requirements.
    yield from directory.glob(pattern)
    yield from directory.glob(f"**/{pattern}")


def resolve_best_matching_file(
    directory: Path,
    identifiers: Iterable[str],
    *,
    suffixes: Iterable[str],
) -> Path | None:
    """
    Resolve the best available file for one or more identifiers.

    Resolution strategy:
      1) exact filename match (`{id}{suffix}`)
      2) wildcard prefix match (`{id}*{suffix}`)
      3) wildcard contains match (`*{id}*{suffix}`)

    Lookup is recursive within the configured directory, so real nested files are
    resolved without requiring alias symlinks in the root directory.

    For ties, case/slide short-id consistency is preferred first (when available),
    then non-symlink real files, then shallower paths and lexical path order.
    """
    if not directory.is_dir():
        return None

    normalized_suffixes = _normalize_suffixes(suffixes)
    if not normalized_suffixes:
        return None

    scored_matches: list[tuple[tuple[int, int, int, int, int, int, int, str], Path]] = []
    seen_paths: set[Path] = set()

    for identifier_rank, identifier in enumerate(identifiers):
        expected_short_case = derive_short_case_id(identifier).lower()
        expected_short_slide = derive_short_slide_id(identifier).lower()
        expected_has_dx = _DX_TOKEN_PATTERN.search(expected_short_slide) is not None
        candidates = enumerate_candidate_identifiers(identifier)
        for candidate in candidates:
            escaped_candidate = glob.escape(candidate)
            for suffix in normalized_suffixes:
                pattern_specs = (
                    (0, f"{escaped_candidate}{suffix}"),
                    (1, f"{escaped_candidate}*{suffix}"),
                    (2, f"*{escaped_candidate}*{suffix}"),
                )
                for pattern_rank, pattern in pattern_specs:
                    for matched_path in _iter_pattern_matches(directory, pattern):
                        if matched_path in seen_paths:
                            continue
                        if not matched_path.is_file():
                            continue
                        if matched_path.suffix.lower() not in normalized_suffixes and suffix not in {
                            ".tif",
                            ".tiff",
                        }:
                            continue
                        matched_short_case = derive_short_case_id(matched_path.name).lower()
                        matched_short_slide = derive_short_slide_id(matched_path.name).lower()
                        if (
                            expected_short_case
                            and matched_short_case
                            and matched_short_case != expected_short_case
                        ):
                            continue
                        matched_has_dx = _DX_TOKEN_PATTERN.search(matched_short_slide) is not None
                        if (
                            expected_has_dx
                            and matched_has_dx
                            and matched_short_slide != expected_short_slide
                        ):
                            continue
                        case_match_rank = 0
                        if expected_short_case:
                            case_match_rank = 0 if matched_short_case == expected_short_case else 1
                        slide_match_rank = 0
                        if expected_has_dx:
                            slide_match_rank = 0 if matched_short_slide == expected_short_slide else 1
                        seen_paths.add(matched_path)
                        scored_matches.append(
                            (
                                _score_candidate(
                                    identifier_rank=identifier_rank,
                                    case_match_rank=case_match_rank,
                                    slide_match_rank=slide_match_rank,
                                    is_symlink=matched_path.is_symlink(),
                                    pattern_rank=pattern_rank,
                                    directory=directory,
                                    path=matched_path,
                                ),
                                matched_path,
                            )
                        )

    if not scored_matches:
        return None

    scored_matches.sort(key=lambda item: item[0])
    return scored_matches[0][1]


def resolve_artifact_json_path(directory: Path, identifier: str) -> Path | None:
    return resolve_best_matching_file(directory, [identifier], suffixes=_ARTIFACT_SUFFIXES)


def resolve_heatmap_file(directory: Path, identifier: str) -> Path | None:
    return resolve_best_matching_file(directory, [identifier], suffixes=_HEATMAP_SUFFIXES)


def resolve_wsi_file(directory: Path, identifier: str) -> Path | None:
    return resolve_best_matching_file(directory, [identifier], suffixes=_WSI_SUFFIXES)


def iter_artifact_json_paths(directory: Path, identifiers: Iterable[str]) -> list[Path]:
    """Resolve at most one best match per identifier while preserving identifier priority."""
    resolved_paths: list[Path] = []
    seen_paths: set[Path] = set()

    for identifier in identifiers:
        resolved_path = resolve_artifact_json_path(directory, identifier)
        if resolved_path is None or resolved_path in seen_paths:
            continue
        seen_paths.add(resolved_path)
        resolved_paths.append(resolved_path)

    return resolved_paths
