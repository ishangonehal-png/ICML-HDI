"""IO Immune Score service.

Computes a tumor microenvironment (TME) immune hotness score for a LUAD case.

Provisional (WSI-only):
  score = clip(til_fraction)
  Tier: Hot >= 0.65, Warm >= 0.40, Cold < 0.40

Refined (with RNA):
  Renormalized weighted average of available components:
    GEP     weight 0.35   sigmoid(gep_value)
    CYT     weight 0.25   sigmoid(cyt_value)
    TIDE    weight 0.20   sigmoid(-tide_value)   (high TIDE -> immune exclusion)
    TIL     weight 0.15   til_fraction
    PD-L1   weight 0.05   pdl1_fraction (if available)
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from schemas.io_score import IOImmuneScoreResponse, IOImmuneTier, IOScoreComponent
from schemas.pathology import MethodMetadata

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_HOT_THRESHOLD = 0.65
_WARM_THRESHOLD = 0.40


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _clip(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _tier(score: float) -> IOImmuneTier:
    if score >= _HOT_THRESHOLD:
        return "Hot"
    if score >= _WARM_THRESHOLD:
        return "Warm"
    return "Cold"


def _renormalized_weighted_avg(
    values: list[tuple[float, float]],  # list of (value, weight)
) -> float:
    """Weighted average with renormalization over available components."""
    total_weight = sum(w for _, w in values)
    if total_weight == 0.0:
        return 0.5
    return sum(v * w for v, w in values) / total_weight


def _sigmoid_or_none(value: float | None) -> float | None:
    return _sigmoid(value) if value is not None else None


def _finite_or_none(value: float | None) -> float | None:
    if value is None:
        return None
    if not math.isfinite(value):
        return None
    return value


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_io_immune_score(
    case_id: str,
    *,
    til_fraction: float | None,
    cyt_value: float | None,
    gep_value: float | None,
    tide_value: float | None,
    pdl1_fraction: float | None = None,
) -> IOImmuneScoreResponse:
    """Compute the IO Immune Score from available signals."""
    missing: list[str] = []

    # Guard against NaN/Inf in upstream artifact payloads.
    til_fraction = _finite_or_none(til_fraction)
    cyt_value = _finite_or_none(cyt_value)
    gep_value = _finite_or_none(gep_value)
    tide_value = _finite_or_none(tide_value)
    pdl1_fraction = _finite_or_none(pdl1_fraction)

    til_fraction_clipped = _clip(til_fraction) if til_fraction is not None else None
    pdl1_fraction_clipped = _clip(pdl1_fraction) if pdl1_fraction is not None else None

    # --- Provisional (WSI) ---
    if til_fraction_clipped is not None:
        provisional = til_fraction_clipped
    else:
        provisional = 0.5
        missing.append("til_fraction")

    rna_available = any(v is not None for v in [cyt_value, gep_value, tide_value])

    # --- Components ---
    components: list[IOScoreComponent] = [
        IOScoreComponent(
            name="TIL fraction",
            value=til_fraction_clipped,
            weight=0.15,
            available=til_fraction_clipped is not None,
            description="Lymphocyte-rich fraction from WSI tissue segmentation",
        ),
        IOScoreComponent(
            name="GEP",
            value=_sigmoid_or_none(gep_value),
            weight=0.35,
            available=gep_value is not None,
            description="18-gene IFNg gene expression profile (sigmoid-normalized)",
        ),
        IOScoreComponent(
            name="CYT",
            value=_sigmoid_or_none(cyt_value),
            weight=0.25,
            available=cyt_value is not None,
            description="Cytolytic activity score: GZMA x PRF1 (sigmoid-normalized)",
        ),
        IOScoreComponent(
            name="TIDE",
            value=_sigmoid_or_none(-tide_value) if tide_value is not None else None,
            weight=0.20,
            available=tide_value is not None,
            description="Inverse TIDE: higher = less immune exclusion (sigmoid-normalized)",
        ),
        IOScoreComponent(
            name="PD-L1",
            value=pdl1_fraction_clipped,
            weight=0.05,
            available=pdl1_fraction_clipped is not None,
            description="PD-L1 TPS fraction (from IHC or proxy)",
        ),
    ]

    # --- Refined ---
    if not rna_available:
        if gep_value is None:
            missing.append("gep")
        if cyt_value is None:
            missing.append("cyt")
        if tide_value is None:
            missing.append("tide")
        refined: float | None = None
        active_score = provisional
    else:
        pairs: list[tuple[float, float]] = []

        if gep_value is not None:
            pairs.append((_sigmoid(gep_value), 0.35))
        else:
            missing.append("gep")

        if cyt_value is not None:
            pairs.append((_sigmoid(cyt_value), 0.25))
        else:
            missing.append("cyt")

        if tide_value is not None:
            pairs.append((_sigmoid(-tide_value), 0.20))
        else:
            missing.append("tide")

        if til_fraction_clipped is not None:
            pairs.append((til_fraction_clipped, 0.15))

        if pdl1_fraction_clipped is not None:
            pairs.append((pdl1_fraction_clipped, 0.05))

        refined = _clip(_renormalized_weighted_avg(pairs))
        active_score = refined

    return IOImmuneScoreResponse(
        case_id=case_id,
        score=active_score,
        tier=_tier(active_score),
        provisional_score=provisional,
        refined_score=refined,
        components=components,
        rna_available=rna_available,
        missing_components=list(dict.fromkeys(missing)),  # deduplicated, ordered
        meta=build_io_score_metadata(),
    )


def build_io_score_metadata() -> MethodMetadata:
    return MethodMetadata(
        method="io-immune-score-v1",
        version="hackathon-p1",
        timestamp=datetime.now(timezone.utc).isoformat(),
        proxy_estimate=True,
    )
