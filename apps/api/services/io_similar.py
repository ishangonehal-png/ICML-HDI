"""Multimodal k-NN similar patient retrieval.

Feature vector (15-dim, all z-scored, L2-normalized for cosine similarity):
  Transcriptomics : GEP_z, CYT_z, -TIDE_z
  Pathology WSI   : TIL_z, tumor_z, necrosis_z
  Demographics    : age_z, gender_z, smoking_z, pack_years_z
  Clinical/staging: stage_z, T_z, N_z, M_z, ecog_z

Missing values are imputed with cohort mean (= 0 after z-scoring).
Clinical XML fields (T/N/M, ECOG, pack_years, smoking) are parsed from
TCGA BCR clinical XML files, keyed by case UUID from the cohort CSV.

Cohort matrix is built lazily on first request and cached as a module
singleton.
"""

from __future__ import annotations

import csv
import math
import os
import threading
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

from schemas.io_score import IOImmuneTier
from schemas.io_similar import IOSimilarCase, IOSimilarCasesResponse
from schemas.pathology import MethodMetadata
from services.pathology import get_tissue_composition
from services.pathology_id_resolution import derive_short_case_id
from services.transcriptomics import get_cyt_signature, get_gep_signature, get_tide_signature

# ---------------------------------------------------------------------------
# File paths
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_COHORT_CSV_DEFAULT = _PROJECT_ROOT / "data" / "manifests" / "cohort.csv"
_XML_DIR_DEFAULT = _PROJECT_ROOT / "data" / "clinical" / "full" / "xmls"

# ---------------------------------------------------------------------------
# Ordinal encodings
# ---------------------------------------------------------------------------

# TCGA tobacco_smoking_history codes:
# 1=Lifelong Non-Smoker, 2=Current smoker,
# 3=Current Reformed Smoker >15 yrs, 4=Current Reformed Smoker ≤15 yrs,
# 5=Smokeless Tobacco User
_SMOKING_ORD: dict[str, float] = {
    "1": 0.0,   # never
    "3": 1.0,   # reformed > 15 yr
    "5": 1.5,   # smokeless (treat as former-like)
    "4": 2.0,   # reformed ≤ 15 yr
    "2": 3.0,   # current
}

_STAGE_ORD: dict[str, float] = {"iv": 4.0, "iii": 3.0, "ii": 2.0, "i": 1.0}

# Pathologic T: extract numeric tier (T1→1, T2→2, T2b→2.5, T3→3, T4→4)
_T_ORD: dict[str, float] = {
    "t4": 4.0, "t3": 3.0,
    "t2b": 2.5, "t2a": 2.0, "t2": 2.0,
    "t1c": 1.5, "t1b": 1.0, "t1a": 1.0, "t1": 1.0,
}

_N_ORD: dict[str, float] = {"n3": 3.0, "n2": 2.0, "n1": 1.0, "n0": 0.0}
_M_ORD: dict[str, float] = {"m0": 0.0, "m1c": 1.0, "m1b": 1.0, "m1a": 1.0, "m1": 1.0}

# Human-readable smoking labels for rationale / schema
_SMOKING_LABEL: dict[str, str] = {
    "1": "Never smoker",
    "2": "Current smoker",
    "3": "Former smoker (>15yr)",
    "4": "Former smoker (≤15yr)",
    "5": "Smokeless tobacco",
}


# ---------------------------------------------------------------------------
# Cohort matrix container
# ---------------------------------------------------------------------------


class _CohortMatrix:
    def __init__(
        self,
        case_ids: list[str],
        matrix: np.ndarray,
        stats: dict[str, float],
        # Raw per-case values for display / rationale
        raw_gep: list[float | None],
        raw_cyt: list[float | None],
        raw_tide: list[float | None],
        til_fractions: list[float | None],
        tumor_fractions: list[float | None],
        necrosis_fractions: list[float | None],
        ages: list[float | None],
        genders: list[float | None],
        smoking_ords: list[float | None],
        smoking_labels: list[str | None],
        pack_years: list[float | None],
        stages: list[str | None],
        stage_ords: list[float],
        T_ords: list[float | None],
        N_ords: list[float | None],
        M_bins: list[float | None],
        ecogs: list[float | None],
    ) -> None:
        self.case_ids = case_ids
        self.matrix = matrix
        self.stats = stats
        self.raw_gep = raw_gep
        self.raw_cyt = raw_cyt
        self.raw_tide = raw_tide
        self.til_fractions = til_fractions
        self.tumor_fractions = tumor_fractions
        self.necrosis_fractions = necrosis_fractions
        self.ages = ages
        self.genders = genders
        self.smoking_ords = smoking_ords
        self.smoking_labels = smoking_labels
        self.pack_years = pack_years
        self.stages = stages
        self.stage_ords = stage_ords
        self.T_ords = T_ords
        self.N_ords = N_ords
        self.M_bins = M_bins
        self.ecogs = ecogs


_cohort_singleton: _CohortMatrix | None = None
_cohort_cache_signature: tuple[str, int | None, str, int | None] | None = None
_cohort_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Ordinal parsers
# ---------------------------------------------------------------------------


def _parse_stage_ord(stage_raw: str) -> float:
    lower = stage_raw.lower()
    for key, val in _STAGE_ORD.items():
        if key in lower:
            return val
    return float("nan")


def _parse_stage_roman(stage_raw: str) -> str | None:
    lower = stage_raw.lower()
    for key in ("iv", "iii", "ii", "i"):
        if key in lower:
            return key.upper()
    return None


def _parse_T(t_raw: str) -> float | None:
    lower = t_raw.lower().strip()
    for key, val in _T_ORD.items():
        if lower.startswith(key):
            return val
    return None


def _parse_N(n_raw: str) -> float | None:
    lower = n_raw.lower().strip()
    for key, val in _N_ORD.items():
        if lower.startswith(key):
            return val
    return None


def _parse_M(m_raw: str) -> float | None:
    lower = m_raw.lower().strip()
    for key, val in _M_ORD.items():
        if lower.startswith(key):
            return val
    return None


def _identifier_matches(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False

    left_norm = left.strip().upper()
    right_norm = right.strip().upper()
    if left_norm == right_norm:
        return True

    return derive_short_case_id(left_norm) == derive_short_case_id(right_norm)


# ---------------------------------------------------------------------------
# Clinical XML parsing
# ---------------------------------------------------------------------------


def _xml_dir() -> Path:
    env = os.environ.get("CLINICAL_XML_DIR")
    return Path(env) if env else _XML_DIR_DEFAULT


def _parse_clinical_xml(xml_path: Path) -> dict[str, str]:
    """Return a flat dict of tag → text for relevant clinical fields."""
    wanted = {
        "pathologic_T",
        "pathologic_N",
        "pathologic_M",
        "tobacco_smoking_history",
        "number_pack_years_smoked",
        "eastern_cancer_oncology_group",
    }
    result: dict[str, str] = {}
    try:
        tree = ET.parse(xml_path)
        for elem in tree.getroot().iter():
            tag = elem.tag.split("}")[-1]
            if tag in wanted and tag not in result:
                text = (elem.text or "").strip()
                if text:
                    result[tag] = text
    except Exception:
        pass
    return result


# ---------------------------------------------------------------------------
# Statistics helpers
# ---------------------------------------------------------------------------


def _cohort_mean_std(values: list[float | None]) -> tuple[float, float]:
    finite = [v for v in values if v is not None and math.isfinite(v)]
    if len(finite) < 2:
        return 0.0, 1.0
    mean = sum(finite) / len(finite)
    var = sum((v - mean) ** 2 for v in finite) / len(finite)
    return mean, math.sqrt(var) if var > 0 else 1.0


def _zscore(value: float | None, mean: float, std: float) -> float:
    """Z-score; impute missing with cohort mean → 0."""
    if value is None or not math.isfinite(value):
        return 0.0
    if std == 0.0:
        return 0.0
    return (value - mean) / std


def _l2_normalize(vec: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vec))
    return vec / norm if norm > 1e-9 else vec


def _build_vec(
    *,
    gep: float | None,
    cyt: float | None,
    tide: float | None,
    til: float | None,
    tumor: float | None,
    necrosis: float | None,
    age: float | None,
    gender: float | None,
    smoking_ord: float | None,
    pack_years: float | None,
    stage_ord: float,
    T_ord: float | None,
    N_ord: float | None,
    M_bin: float | None,
    ecog: float | None,
    stats: dict[str, float],
) -> np.ndarray:
    stage_val: float | None = stage_ord if math.isfinite(stage_ord) else None
    vec = np.array(
        [
            # Transcriptomics
            _zscore(gep, stats["mean_gep"], stats["std_gep"]),
            _zscore(cyt, stats["mean_cyt"], stats["std_cyt"]),
            -_zscore(tide, stats["mean_tide"], stats["std_tide"]),   # invert TIDE
            # WSI composition
            _zscore(til, stats["mean_til"], stats["std_til"]),
            _zscore(tumor, stats["mean_tumor"], stats["std_tumor"]),
            _zscore(necrosis, stats["mean_necrosis"], stats["std_necrosis"]),
            # Demographics
            _zscore(age, stats["mean_age"], stats["std_age"]),
            _zscore(gender, stats["mean_gender"], stats["std_gender"]),
            _zscore(smoking_ord, stats["mean_smoking"], stats["std_smoking"]),
            _zscore(pack_years, stats["mean_pack_years"], stats["std_pack_years"]),
            # Clinical staging
            _zscore(stage_val, stats["mean_stage"], stats["std_stage"]),
            _zscore(T_ord, stats["mean_T"], stats["std_T"]),
            _zscore(N_ord, stats["mean_N"], stats["std_N"]),
            _zscore(M_bin, stats["mean_M"], stats["std_M"]),
            _zscore(ecog, stats["mean_ecog"], stats["std_ecog"]),
        ],
        dtype=float,
    )
    return _l2_normalize(vec)


# ---------------------------------------------------------------------------
# Cohort CSV loading
# ---------------------------------------------------------------------------


def _load_csv_rows() -> list[dict[str, str]]:
    """Load all rows from cohort CSV. Returns list of raw dicts."""
    env_path = os.environ.get("TRANSCRIPTOMICS_COVERAGE_COHORT_CSV")
    csv_path = Path(env_path) if env_path else _COHORT_CSV_DEFAULT
    if not csv_path.exists():
        return []
    rows: list[dict[str, str]] = []
    with csv_path.open(newline="") as fh:
        for row in csv.DictReader(fh):
            pid = row.get("patient_id", "").strip()
            if pid:
                rows.append(dict(row))
    return rows


# ---------------------------------------------------------------------------
# Cohort matrix build
# ---------------------------------------------------------------------------


def _build_cohort_matrix(db: "Session | None") -> _CohortMatrix:
    csv_rows = _load_csv_rows()
    if not csv_rows:
        empty = np.zeros((0, 15), dtype=float)
        return _CohortMatrix(
            [], empty, {},
            [], [], [], [], [], [], [], [], [], [], [], [],
            [], [], [], [], [],
        )

    xml_dir = _xml_dir()

    case_ids: list[str] = []
    stage_ords: list[float] = []
    stage_raws: list[str | None] = []
    raw_gep: list[float | None] = []
    raw_cyt: list[float | None] = []
    raw_tide: list[float | None] = []
    til_fractions: list[float | None] = []
    tumor_fractions: list[float | None] = []
    necrosis_fractions: list[float | None] = []
    ages: list[float | None] = []
    genders: list[float | None] = []         # 1.0 = male, 0.0 = female
    smoking_ords: list[float | None] = []
    smoking_labels: list[str | None] = []
    pack_years_list: list[float | None] = []
    T_ords: list[float | None] = []
    N_ords: list[float | None] = []
    M_bins: list[float | None] = []
    ecogs: list[float | None] = []

    for row in csv_rows:
        patient_id = row["patient_id"].strip()
        case_uuid = row.get("case_id", "").strip()
        case_ids.append(patient_id)

        # --- Stage from CSV ---
        stage_raw = row.get("tumor_stage", "").strip()
        stage_raws.append(stage_raw or None)
        stage_ords.append(_parse_stage_ord(stage_raw))

        # --- Age / gender from CSV ---
        try:
            ages.append(float(row.get("age_at_diagnosis_years", "")))
        except (ValueError, TypeError):
            ages.append(None)

        gender_str = row.get("gender", "").strip().lower()
        genders.append(1.0 if gender_str == "male" else (0.0 if gender_str == "female" else None))

        # --- Clinical XML (T/N/M, ECOG, pack-years, smoking) ---
        xml_fields: dict[str, str] = {}
        if case_uuid:
            xml_path = xml_dir / f"{case_uuid}.xml"
            if xml_path.exists():
                xml_fields = _parse_clinical_xml(xml_path)

        smoking_code = xml_fields.get("tobacco_smoking_history", "")
        smoking_ords.append(_SMOKING_ORD.get(smoking_code))
        smoking_labels.append(_SMOKING_LABEL.get(smoking_code))

        raw_pack = xml_fields.get("number_pack_years_smoked", "")
        try:
            pack_years_list.append(float(raw_pack) if raw_pack else None)
        except ValueError:
            pack_years_list.append(None)

        T_ords.append(_parse_T(xml_fields.get("pathologic_T", "")))
        N_ords.append(_parse_N(xml_fields.get("pathologic_N", "")))
        M_bins.append(_parse_M(xml_fields.get("pathologic_M", "")))

        raw_ecog = xml_fields.get("eastern_cancer_oncology_group", "")
        try:
            ecogs.append(float(raw_ecog) if raw_ecog else None)
        except ValueError:
            ecogs.append(None)

        # --- RNA signatures ---
        try:
            cyt_resp = get_cyt_signature(patient_id, db=db)
            raw_cyt.append(cyt_resp.value if cyt_resp.available else None)
        except Exception:
            raw_cyt.append(None)

        try:
            gep_resp = get_gep_signature(patient_id, db=db)
            raw_gep.append(gep_resp.value if gep_resp.available else None)
        except Exception:
            raw_gep.append(None)

        try:
            tide_resp = get_tide_signature(patient_id, db=db)
            raw_tide.append(tide_resp.value if tide_resp.available else None)
        except Exception:
            raw_tide.append(None)

        # --- Pathology tissue fractions ---
        try:
            slide_id = f"{derive_short_case_id(patient_id)}-DX1"
            tissue = get_tissue_composition(slide_id)
            fracs = {f.tissue.lower(): f.fraction for f in tissue.fractions}
            til_fractions.append(next((v for k, v in fracs.items() if "lymphocyte" in k), None))
            tumor_fractions.append(next((v for k, v in fracs.items() if "tumor" in k), None))
            necrosis_fractions.append(next((v for k, v in fracs.items() if "necrosis" in k), None))
        except Exception:
            til_fractions.append(None)
            tumor_fractions.append(None)
            necrosis_fractions.append(None)

    # --- Cohort-level stats for z-scoring ---
    stats: dict[str, float] = {}
    feature_lists: list[tuple[str, list[float | None]]] = [
        ("gep", raw_gep),
        ("cyt", raw_cyt),
        ("tide", raw_tide),
        ("til", til_fractions),
        ("tumor", tumor_fractions),
        ("necrosis", necrosis_fractions),
        ("age", ages),
        ("gender", genders),
        ("smoking", smoking_ords),
        ("pack_years", pack_years_list),
        ("stage", [s if math.isfinite(s) else None for s in stage_ords]),
        ("T", T_ords),
        ("N", N_ords),
        ("M", M_bins),
        ("ecog", ecogs),
    ]
    for name, values in feature_lists:
        mean, std = _cohort_mean_std(values)
        stats[f"mean_{name}"] = mean
        stats[f"std_{name}"] = std

    # --- Build L2-normalized feature matrix ---
    vectors = [
        _build_vec(
            gep=raw_gep[i],
            cyt=raw_cyt[i],
            tide=raw_tide[i],
            til=til_fractions[i],
            tumor=tumor_fractions[i],
            necrosis=necrosis_fractions[i],
            age=ages[i],
            gender=genders[i],
            smoking_ord=smoking_ords[i],
            pack_years=pack_years_list[i],
            stage_ord=stage_ords[i],
            T_ord=T_ords[i],
            N_ord=N_ords[i],
            M_bin=M_bins[i],
            ecog=ecogs[i],
            stats=stats,
        )
        for i in range(len(case_ids))
    ]
    matrix = np.stack(vectors) if vectors else np.zeros((0, 15), dtype=float)

    return _CohortMatrix(
        case_ids=case_ids,
        matrix=matrix,
        stats=stats,
        raw_gep=raw_gep,
        raw_cyt=raw_cyt,
        raw_tide=raw_tide,
        til_fractions=til_fractions,
        tumor_fractions=tumor_fractions,
        necrosis_fractions=necrosis_fractions,
        ages=ages,
        genders=genders,
        smoking_ords=smoking_ords,
        smoking_labels=smoking_labels,
        pack_years=pack_years_list,
        stages=stage_raws,
        stage_ords=stage_ords,
        T_ords=T_ords,
        N_ords=N_ords,
        M_bins=M_bins,
        ecogs=ecogs,
    )


def _cohort_cache_inputs() -> tuple[str, int | None, str, int | None]:
    env_path = os.environ.get("TRANSCRIPTOMICS_COVERAGE_COHORT_CSV")
    csv_path = (Path(env_path) if env_path else _COHORT_CSV_DEFAULT).resolve()
    xml_dir = _xml_dir().resolve()

    csv_mtime_ns = csv_path.stat().st_mtime_ns if csv_path.exists() else None
    xml_mtime_ns = xml_dir.stat().st_mtime_ns if xml_dir.exists() else None

    return (str(csv_path), csv_mtime_ns, str(xml_dir), xml_mtime_ns)


def _get_cohort_matrix(db: "Session | None") -> _CohortMatrix:
    global _cohort_singleton, _cohort_cache_signature
    cache_signature = _cohort_cache_inputs()

    if _cohort_singleton is not None and _cohort_cache_signature == cache_signature:
        return _cohort_singleton

    with _cohort_lock:
        if _cohort_singleton is None or _cohort_cache_signature != cache_signature:
            _cohort_singleton = _build_cohort_matrix(db)
            _cohort_cache_signature = cache_signature

    return _cohort_singleton


# ---------------------------------------------------------------------------
# Feature space inference
# ---------------------------------------------------------------------------


def _infer_feature_space(cohort: _CohortMatrix) -> list[str]:
    space: list[str] = []
    checks: list[tuple[str, list[float | None]]] = [
        ("GEP", cohort.raw_gep),
        ("CYT", cohort.raw_cyt),
        ("TIDE", cohort.raw_tide),
        ("TIL", cohort.til_fractions),
        ("Tumor%", cohort.tumor_fractions),
        ("Necrosis%", cohort.necrosis_fractions),
        ("Age", cohort.ages),
        ("Gender", cohort.genders),
        ("Smoking", cohort.smoking_ords),
        ("Pack-years", cohort.pack_years),
        ("Stage", [s if math.isfinite(s) else None for s in cohort.stage_ords]),
        ("T", cohort.T_ords),
        ("N", cohort.N_ords),
        ("M", cohort.M_bins),
        ("ECOG", cohort.ecogs),
    ]
    for name, vals in checks:
        if any(v is not None for v in vals):
            space.append(name)
    return space


# ---------------------------------------------------------------------------
# Rationale formatting
# ---------------------------------------------------------------------------


def _format_rationale(
    *,
    n_gep: float | None,
    n_cyt: float | None,
    n_til: float | None,
    n_age: float | None,
    n_smoking_label: str | None,
    n_stage: str | None,
    n_T_ord: float | None,
    n_N_ord: float | None,
    n_M_bin: float | None,
    q_gep_z: float,
    q_cyt_z: float,
    stats: dict[str, float],
) -> str:
    parts: list[str] = []

    if n_gep is not None:
        delta = _zscore(n_gep, stats["mean_gep"], stats["std_gep"]) - q_gep_z
        parts.append(f"GEP {'+' if delta >= 0 else ''}{delta:.1f}σ")

    if n_cyt is not None:
        delta = _zscore(n_cyt, stats["mean_cyt"], stats["std_cyt"]) - q_cyt_z
        parts.append(f"CYT {'+' if delta >= 0 else ''}{delta:.1f}σ")

    if n_til is not None:
        parts.append(f"TIL {round(n_til * 100)}%")

    if n_age is not None:
        parts.append(f"Age {round(n_age)}y")

    if n_smoking_label:
        # Shorten for display
        label = n_smoking_label.replace(" smoker", "").replace("Former (", "Former ").rstrip(")")
        parts.append(label)

    if n_T_ord is not None and n_N_ord is not None and n_M_bin is not None:
        t_str = f"T{n_T_ord:.0f}" if n_T_ord == int(n_T_ord) else f"T{n_T_ord}"
        n_str = f"N{int(n_N_ord)}"
        m_str = f"M{int(n_M_bin)}"
        parts.append(f"{t_str}{n_str}{m_str}")
    elif n_stage:
        roman = _parse_stage_roman(n_stage)
        if roman:
            parts.append(f"Stage {roman}")

    return " · ".join(parts) if parts else "Similar immune + clinical profile"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_io_similar_cases(
    case_id: str,
    *,
    db: "Session | None" = None,
    limit: int = 5,
) -> IOSimilarCasesResponse:
    """Return the k most similar patients based on multimodal IO feature space."""
    cohort = _get_cohort_matrix(db)
    n = len(cohort.case_ids)

    # --- Resolve query case features ---
    try:
        q_gep: float | None = get_gep_signature(case_id, db=db).value
    except Exception:
        q_gep = None

    try:
        q_cyt: float | None = get_cyt_signature(case_id, db=db).value
    except Exception:
        q_cyt = None

    try:
        q_tide: float | None = get_tide_signature(case_id, db=db).value
    except Exception:
        q_tide = None

    # Pathology fractions for query case
    q_til: float | None = None
    q_tumor: float | None = None
    q_necrosis: float | None = None
    try:
        slide_id = f"{derive_short_case_id(case_id)}-DX1"
        tissue = get_tissue_composition(slide_id)
        fracs = {f.tissue.lower(): f.fraction for f in tissue.fractions}
        q_til = next((v for k, v in fracs.items() if "lymphocyte" in k), None)
        q_tumor = next((v for k, v in fracs.items() if "tumor" in k), None)
        q_necrosis = next((v for k, v in fracs.items() if "necrosis" in k), None)
    except Exception:
        pass

    # Demographics / staging from cohort matrix (matched by patient_id)
    q_age: float | None = None
    q_gender: float | None = None
    q_smoking_ord: float | None = None
    q_pack_years: float | None = None
    q_stage_ord: float = float("nan")
    q_T_ord: float | None = None
    q_N_ord: float | None = None
    q_M_bin: float | None = None
    q_ecog: float | None = None
    for i, cid in enumerate(cohort.case_ids):
        if _identifier_matches(cid, case_id):
            q_age = cohort.ages[i]
            q_gender = cohort.genders[i]
            q_smoking_ord = cohort.smoking_ords[i]
            q_pack_years = cohort.pack_years[i]
            q_stage_ord = cohort.stage_ords[i]
            q_T_ord = cohort.T_ords[i]
            q_N_ord = cohort.N_ords[i]
            q_M_bin = cohort.M_bins[i]
            q_ecog = cohort.ecogs[i]
            break

    q_rna_available = any(v is not None for v in [q_gep, q_cyt, q_tide])

    if n == 0 or cohort.matrix.shape[0] == 0:
        return IOSimilarCasesResponse(
            case_id=case_id,
            neighbors=[],
            feature_space=[],
            rna_available=q_rna_available,
            cohort_size=0,
            meta=_build_meta(),
        )

    q_vec = _build_vec(
        gep=q_gep, cyt=q_cyt, tide=q_tide,
        til=q_til, tumor=q_tumor, necrosis=q_necrosis,
        age=q_age, gender=q_gender,
        smoking_ord=q_smoking_ord, pack_years=q_pack_years,
        stage_ord=q_stage_ord,
        T_ord=q_T_ord, N_ord=q_N_ord, M_bin=q_M_bin, ecog=q_ecog,
        stats=cohort.stats,
    )

    # Cosine similarities (both sides L2-normalized)
    sims: np.ndarray = cohort.matrix @ q_vec

    # Suppress self
    for i, cid in enumerate(cohort.case_ids):
        if _identifier_matches(cid, case_id):
            sims[i] = -2.0

    top_k_indices = np.argsort(-sims)[:limit]

    stats = cohort.stats
    q_gep_z = _zscore(q_gep, stats["mean_gep"], stats["std_gep"])
    q_cyt_z = _zscore(q_cyt, stats["mean_cyt"], stats["std_cyt"])

    neighbors: list[IOSimilarCase] = []
    for idx in top_k_indices:
        i = int(idx)
        g = cohort.raw_gep[i]
        c = cohort.raw_cyt[i]
        t = cohort.raw_tide[i]
        til = cohort.til_fractions[i]

        # Compute IO score/tier for this neighbor on demand
        from services.io_score import get_io_immune_score

        io_resp = get_io_immune_score(
            cohort.case_ids[i],
            til_fraction=til,
            cyt_value=c,
            gep_value=g,
            tide_value=t,
        )

        gep_z = _zscore(g, stats["mean_gep"], stats["std_gep"])
        cyt_z = _zscore(c, stats["mean_cyt"], stats["std_cyt"])
        tide_z_inv = -_zscore(t, stats["mean_tide"], stats["std_tide"])

        rationale = _format_rationale(
            n_gep=g,
            n_cyt=c,
            n_til=til,
            n_age=cohort.ages[i],
            n_smoking_label=cohort.smoking_labels[i],
            n_stage=cohort.stages[i],
            n_T_ord=cohort.T_ords[i],
            n_N_ord=cohort.N_ords[i],
            n_M_bin=cohort.M_bins[i],
            q_gep_z=q_gep_z,
            q_cyt_z=q_cyt_z,
            stats=stats,
        )

        neighbors.append(
            IOSimilarCase(
                case_id=cohort.case_ids[i],
                similarity=float(np.clip(sims[i], 0.0, 1.0)),
                tier=io_resp.tier,
                score=io_resp.score,
                gep_z=round(gep_z, 2) if g is not None else None,
                cyt_z=round(cyt_z, 2) if c is not None else None,
                tide_z=round(tide_z_inv, 2) if t is not None else None,
                til_fraction=til,
                age_at_diagnosis=cohort.ages[i],
                smoking=cohort.smoking_labels[i],
                stage=cohort.stages[i],
                rationale=rationale,
            )
        )

    return IOSimilarCasesResponse(
        case_id=case_id,
        neighbors=neighbors,
        feature_space=_infer_feature_space(cohort),
        rna_available=q_rna_available,
        cohort_size=n,
        meta=_build_meta(),
    )


def invalidate_cohort_cache() -> None:
    """Force cohort matrix rebuild on next request."""
    global _cohort_singleton, _cohort_cache_signature
    with _cohort_lock:
        _cohort_singleton = None
        _cohort_cache_signature = None


def _build_meta() -> MethodMetadata:
    return MethodMetadata(
        method="io-knn-v1",
        version="hackathon-p2",
        timestamp=datetime.now(timezone.utc).isoformat(),
        proxy_estimate=True,
    )
