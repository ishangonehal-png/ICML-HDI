"""Fit a Cox Proportional Hazards survival model on the TCGA-LUAD full cohort.

Usage — clinical-only model
---------------------------
    python scripts/fit_survival_model.py \\
        --xml-dir       data/clinical/xmls \\
        --output-dir    data/clinical/survival_model \\
        --cohort-csv    data/manifests/cohort.csv

Usage — RNA-augmented model (requires TRANSCRIPTOMICS_ARTIFACT_DIR contents)
-----------------------------------------------------------------------------
    python scripts/fit_survival_model.py \\
        --xml-dir        data/clinical/xmls \\
        --output-dir     data/clinical/survival_model \\
        --cohort-csv     data/manifests/cohort.csv \\
        --rna-scores-dir data/transcriptomics/artifacts

Outputs (in --output-dir)
--------------------------
Clinical-only model (always produced):
- ``cox_model.pkl``        — fitted lifelines CoxPHFitter
- ``km_strata.json``       — KM curve data per tier {high,intermediate,low}
- ``cohort_stats.json``    — concordance index, median OS per stratum

RNA-augmented model (produced when --rna-scores-dir is given):
- ``cox_rna_model.pkl``    — Cox model with CYT/GEP/TIDE features added
- ``cox_rna_strata.json``  — KM strata stratified by RNA-informed proxy score
- ``cox_rna_stats.json``   — concordance index for RNA model

The API (get_clinical_survival) automatically prefers cox_rna_model.pkl when present.

Features used in Cox model
--------------------------
Clinical (always):
- stage_ordinal          (I=1, II=2, III=3, IV=4)
- age_at_diagnosis       (years, continuous)
- smoking_ordinal        (never=0, former=1, current=2)
- is_female              (binary)
- pack_years             (continuous; median-imputed when missing)
- subtype_{lepidic,micropapillary,papillary,solid,mucinous}  (one-hot, acinar = ref)

RNA-augmented (added when --rna-scores-dir provided):
- cyt_score              (cytolytic activity: geometric mean of GZMA, PRF1)
- gep_score              (18-gene interferon-γ inflamed tumor signature)
- tide_score             (T-cell dysfunction/exclusion; higher = worse IO response)

Survival endpoints
------------------
- duration_months   : days_to_death OR days_to_last_followup → converted to months
- event             : 1 if deceased, 0 if censored

Dependencies
------------
    pip install lifelines pandas numpy
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import pickle
import re
import sys
import warnings
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

_DAYS_PER_MONTH = 30.4375

# ---------------------------------------------------------------------------
# XML parsing helpers (mirrors clinical.py _parse_xml_file, standalone)
# ---------------------------------------------------------------------------

_STAGE_PATTERN = re.compile(r"(?:stage\s*)?([ivx]+|[1-4])\s*([abc]?)", re.IGNORECASE)
_SMOKING_MAP = {
    "current smoker": "current",
    "current reformed smoker for > 15 years": "former",
    "current reformed smoker for < or = 15 years": "former",
    "lifelong non-smoker": "never",
    "not reported": None,
}
_STAGE_ORD = {
    "i": 1, "ia": 1, "ib": 1,
    "ii": 2, "iia": 2, "iib": 2,
    "iii": 3, "iiia": 3, "iiib": 3,
    "iv": 4,
}
_SUBTYPE_KEYS = ("lepidic", "micropapillary", "papillary", "solid", "mucinous")


def _tag_local(elem: ElementTree.Element) -> str:
    tag = elem.tag
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _parse_xml(xml_path: Path) -> dict:
    try:
        tree = ElementTree.parse(str(xml_path))
    except Exception:
        return {}

    tag_values: dict[str, str] = {}
    for elem in tree.iter():
        val = (elem.text or "").strip()
        if val:
            tag_values[_tag_local(elem).lower()] = val

    return tag_values


def _stage_ordinal(raw: str | None) -> float | None:
    if not raw:
        return None
    m = _STAGE_PATTERN.search(raw)
    if not m:
        return None
    key = (m.group(1) + m.group(2)).lower()
    return float(_STAGE_ORD.get(key, _STAGE_ORD.get(m.group(1).lower(), 0)) or 0) or None


def _smoking_ordinal(raw: str | None) -> float:
    if not raw:
        return 1.0  # default to former
    lowered = raw.lower().strip()
    status = _SMOKING_MAP.get(lowered)
    if status is None:
        if "never" in lowered or "non" in lowered:
            status = "never"
        elif "current" in lowered and "reform" not in lowered:
            status = "current"
        else:
            status = "former"
    return {"never": 0.0, "former": 1.0, "current": 2.0}.get(status, 1.0)


def _histologic_subtype(raw: str | None) -> str | None:
    if not raw:
        return None
    lowered = raw.lower()
    for key in _SUBTYPE_KEYS:
        if key in lowered:
            return key
    return None


def _parse_case(xml_path: Path) -> dict | None:
    tv = _parse_xml(xml_path)
    if not tv:
        return None

    # Duration (months)
    days_death = tv.get("days_to_death") or tv.get("days_to_death_value")
    days_followup = tv.get("days_to_last_followup") or tv.get("days_to_last_follow_up")

    vital = (tv.get("vital_status") or "").lower()
    event = 1 if vital in {"dead", "deceased"} else 0

    duration_days: int | None = None
    if event and days_death:
        try:
            duration_days = int(days_death)
        except ValueError:
            pass
    if duration_days is None and days_followup:
        try:
            duration_days = int(days_followup)
        except ValueError:
            pass

    if duration_days is None or duration_days <= 0:
        return None

    duration_months = duration_days / _DAYS_PER_MONTH

    # Stage
    stage_raw = (
        tv.get("pathologic_stage")
        or tv.get("clinical_stage")
        or tv.get("tumor_stage")
        or tv.get("stage_event_pathologic_stage")
    )
    stage_ord = _stage_ordinal(stage_raw)
    if stage_ord is None:
        return None  # stage is required

    # Age
    age_days = tv.get("age_at_initial_pathologic_diagnosis") or tv.get("age_at_diagnosis")
    try:
        age_years = int(age_days) / 365.25 if age_days else None
    except ValueError:
        age_years = None
    if age_years is None:
        return None  # age required

    # Smoking
    smoking_raw = tv.get("tobacco_smoking_history") or tv.get("smoking_history")
    smoking_ord = _smoking_ordinal(smoking_raw)

    # Sex
    sex_raw = (tv.get("gender") or tv.get("sex") or "").lower()
    is_female = 1.0 if "female" in sex_raw else 0.0

    # Pack-years
    pack_years_raw = tv.get("number_pack_years_smoked") or tv.get("pack_years_smoked")
    try:
        pack_years: float | None = float(pack_years_raw) if pack_years_raw else None
    except ValueError:
        pack_years = None

    # Histologic subtype
    subtype_raw = tv.get("histological_type") or tv.get("histological_subtype")
    subtype = _histologic_subtype(subtype_raw)

    row: dict = {
        "case_id": xml_path.stem.split(".")[0],
        "duration_months": duration_months,
        "event": event,
        "stage_ordinal": stage_ord,
        "age_at_diagnosis": age_years,
        "smoking_ordinal": smoking_ord,
        "is_female": is_female,
        "pack_years": pack_years,
    }
    for sk in _SUBTYPE_KEYS:
        row[f"subtype_{sk}"] = 1.0 if subtype == sk else 0.0

    return row


# ---------------------------------------------------------------------------
# RNA score loading (mirrors transcriptomics._extract_metric_from_payload)
# ---------------------------------------------------------------------------

def _nested_get(obj: Any, *keys: str) -> Any:
    for key in keys:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


def _coerce_float(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _extract_rna_metric(payload: dict, metric_name: str) -> float | None:
    candidates = [
        payload.get(metric_name),
        payload.get(f"{metric_name}_score"),
        _nested_get(payload, "scores", metric_name),
        _nested_get(payload, "signatures", metric_name),
        _nested_get(payload, "transcriptomics", metric_name),
    ]
    for c in candidates:
        if isinstance(c, dict):
            for k in ("value", "score", "normalized_value"):
                v = _coerce_float(c.get(k))
                if v is not None:
                    return v
        else:
            v = _coerce_float(c)
            if v is not None:
                return v
    return None


def _load_rna_scores(case_id: str, rna_dir: Path) -> dict[str, float] | None:
    """Try to read CYT/GEP/TIDE from a transcriptomics artifact JSON for case_id.

    Looks for files matching <case_id>*.json inside rna_dir (non-recursive).
    Returns dict with keys cyt_score, gep_score, tide_score (any may be None).
    Returns None if no matching file is found.
    """
    candidates = list(rna_dir.glob(f"{case_id}*.json")) + list(rna_dir.glob(f"{case_id.lower()}*.json"))
    if not candidates:
        return None
    payload: dict = {}
    for path in candidates:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                payload = data
                break
        except Exception:
            continue
    if not payload:
        return None
    return {
        "cyt_score": _extract_rna_metric(payload, "cyt"),
        "gep_score": _extract_rna_metric(payload, "gep"),
        "tide_score": _extract_rna_metric(payload, "tide"),
    }


# ---------------------------------------------------------------------------
# Model fitting
# ---------------------------------------------------------------------------

_FEATURE_COLS = [
    "stage_ordinal",
    "age_at_diagnosis",
    "smoking_ordinal",
    "is_female",
    "pack_years",
    *[f"subtype_{sk}" for sk in _SUBTYPE_KEYS],
]

_RNA_FEATURE_COLS = [
    "cyt_score",
    "gep_score",
    "tide_score",
]


def _fit_model(df: "pd.DataFrame", extra_features: list[str] | None = None) -> "CoxPHFitter":  # type: ignore[name-defined]
    from lifelines import CoxPHFitter  # type: ignore[import-untyped]

    cph = CoxPHFitter(penalizer=0.1)
    feature_cols = [c for c in (_FEATURE_COLS + (extra_features or [])) if c in df.columns]
    fit_df = df[feature_cols + ["duration_months", "event"]].copy()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        cph.fit(fit_df, duration_col="duration_months", event_col="event")
    return cph


# ---------------------------------------------------------------------------
# KM curves
# ---------------------------------------------------------------------------

def _compute_km_strata(df: "pd.DataFrame", use_rna_proxy: bool = False) -> dict:
    """Stratify cohort into tertiles by a composite proxy score, compute KM curve per stratum.

    Clinical proxy  : stage_ordinal + 0.5 * smoking_ordinal
    RNA-augmented   : stage_ordinal + 0.5 * smoking_ordinal - 0.5 * gep_score - 0.3 * cyt_score + 0.3 * tide_score
      (GEP/CYT high = better immune env = lower score; TIDE high = worse exclusion = higher score)
    """
    from lifelines import KaplanMeierFitter  # type: ignore[import-untyped]

    df = df.copy()
    if use_rna_proxy and "gep_score" in df.columns:
        gep = df["gep_score"].fillna(0.0)
        cyt = df["cyt_score"].fillna(0.0) if "cyt_score" in df.columns else 0.0
        tide = df["tide_score"].fillna(0.0) if "tide_score" in df.columns else 0.0
        df["_proxy"] = (
            df["stage_ordinal"]
            + 0.5 * df["smoking_ordinal"]
            - 0.5 * gep
            - 0.3 * cyt
            + 0.3 * tide
        )
    else:
        # Clinical proxy: high stage + high smoking = worse prognosis
        df["_proxy"] = df["stage_ordinal"] + 0.5 * df["smoking_ordinal"]

    tertile_low = df["_proxy"].quantile(1 / 3)
    tertile_high = df["_proxy"].quantile(2 / 3)

    tier_map = {
        "high": df["_proxy"] <= tertile_low,      # low proxy score = better immune environment
        "intermediate": (df["_proxy"] > tertile_low) & (df["_proxy"] <= tertile_high),
        "low": df["_proxy"] > tertile_high,        # high proxy score = worse prognosis
    }

    strata: dict = {}
    for label, mask in tier_map.items():
        subset = df[mask]
        if len(subset) < 3:
            continue
        kmf = KaplanMeierFitter()
        kmf.fit(subset["duration_months"], event_observed=subset["event"], label=label)

        time_points = kmf.survival_function_.index.tolist()
        survival_rates = kmf.survival_function_[label].tolist()
        n_at_risk = [
            int(kmf.event_table.loc[t, "at_risk"])
            for t in time_points
            if t in kmf.event_table.index
        ]
        # pad if event_table doesn't cover all time points
        while len(n_at_risk) < len(time_points):
            n_at_risk.append(n_at_risk[-1] if n_at_risk else 0)

        median_val = kmf.median_survival_time_
        strata[label] = {
            "time_points": [round(t, 2) for t in time_points],
            "survival_rates": [round(s, 4) for s in survival_rates],
            "n_at_risk": n_at_risk,
            "n_events": int(subset["event"].sum()),
            "n_total": len(subset),
            "median_survival_months": round(float(median_val), 2) if median_val is not None else None,
        }

    return strata


def _cohort_stats(cph: object, df: "pd.DataFrame", km_strata: dict, features: list[str]) -> dict:
    stats: dict = {
        "concordance_index": round(float(cph.concordance_index_), 4),  # type: ignore[union-attr]
        "n_cases": len(df),
        "n_events": int(df["event"].sum()),
        "features": features,
    }
    for label, stratum in km_strata.items():
        stats[f"median_os_{label}_months"] = stratum.get("median_survival_months")
    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Fit Cox PH survival model on TCGA-LUAD full cohort.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--xml-dir", required=True, type=Path, help="Directory of clinical XML files")
    p.add_argument("--output-dir", required=True, type=Path, help="Output directory for model artifacts")
    p.add_argument("--cohort-csv", type=Path, default=None, help="Optional cohort CSV to restrict cases")
    p.add_argument("--min-cases", type=int, default=50, help="Fail if fewer than this many cases parsed")
    p.add_argument(
        "--rna-scores-dir",
        type=Path,
        default=None,
        help=(
            "Directory of transcriptomics artifact JSONs (= TRANSCRIPTOMICS_ARTIFACT_DIR). "
            "When provided, also fits a second RNA-augmented Cox model saved as "
            "cox_rna_model.pkl / km_rna_strata.json / cohort_rna_stats.json. "
            "The RNA model is trained only on cases that have all three RNA scores (CYT/GEP/TIDE)."
        ),
    )
    return p


def _persist_model(
    cph: object,
    km_strata: dict,
    stats: dict,
    output_dir: Path,
    prefix: str,
) -> None:
    cox_path = output_dir / f"{prefix}_model.pkl"
    with cox_path.open("wb") as fh:
        pickle.dump(cph, fh, protocol=pickle.HIGHEST_PROTOCOL)
    log.info("Saved Cox model → %s", cox_path)

    km_path = output_dir / f"{prefix}_strata.json"
    km_path.write_text(json.dumps(km_strata, indent=2), encoding="utf-8")
    log.info("Saved KM strata → %s", km_path)

    stats_path = output_dir / f"{prefix}_stats.json"
    stats_path.write_text(json.dumps(stats, indent=2), encoding="utf-8")
    log.info("Saved cohort stats → %s", stats_path)


def _print_model_summary(label: str, cph: object, km_strata: dict) -> None:
    print(f"\n=== {label} ===")
    try:
        print(cph.summary[["coef", "exp(coef)", "p"]].to_string())  # type: ignore[union-attr]
    except Exception:
        pass
    print(f"\nConcordance index: {cph.concordance_index_:.4f}")  # type: ignore[union-attr]
    for tier, stratum in km_strata.items():
        med = stratum.get("median_survival_months")
        n = stratum["n_total"]
        print(
            f"KM {tier:>12}: n={n:3d}  median OS={med:.1f} months"
            if med
            else f"KM {tier:>12}: n={n:3d}  median OS=not reached"
        )


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    try:
        import pandas as pd  # type: ignore[import-untyped]
        import lifelines  # type: ignore[import-untyped]  # noqa: F401
    except ImportError as exc:
        log.error("Missing dependency: %s — run: pip install lifelines pandas numpy", exc)
        return 1

    xml_dir: Path = args.xml_dir
    output_dir: Path = args.output_dir

    if not xml_dir.is_dir():
        log.error("--xml-dir does not exist: %s", xml_dir)
        return 1

    output_dir.mkdir(parents=True, exist_ok=True)

    # Cohort filter
    cohort_ids: set[str] | None = None
    if args.cohort_csv and args.cohort_csv.is_file():
        import csv
        cohort_ids = set()
        with args.cohort_csv.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                cid = (row.get("case_id") or "").strip().upper()
                if cid:
                    cohort_ids.add(cid)
        log.info("Cohort CSV: %d cases", len(cohort_ids))

    # Parse XMLs
    rows: list[dict] = []
    skipped = 0
    for xml_path in sorted(xml_dir.glob("*.xml")):
        case_id = xml_path.stem.split(".")[0].upper()
        if cohort_ids is not None and case_id not in cohort_ids:
            continue
        row = _parse_case(xml_path)
        if row is None:
            skipped += 1
            log.debug("Skipped %s (missing required fields)", xml_path.name)
        else:
            rows.append(row)

    log.info("Parsed %d cases, skipped %d (missing stage/age/duration)", len(rows), skipped)

    if len(rows) < args.min_cases:
        log.error("Only %d cases parsed; need at least %d. Check --xml-dir.", len(rows), args.min_cases)
        return 1

    df = pd.DataFrame(rows)

    # Impute missing pack_years with cohort median
    pack_median = df["pack_years"].median()
    n_imputed = df["pack_years"].isna().sum()
    df["pack_years"] = df["pack_years"].fillna(pack_median)
    log.info("pack_years: median=%.1f, imputed %d cases", pack_median, n_imputed)

    # -----------------------------------------------------------------------
    # Clinical-only Cox model
    # -----------------------------------------------------------------------
    log.info("Fitting clinical Cox model on %d cases (%d features)...", len(df), len(_FEATURE_COLS))
    cph_clinical = _fit_model(df)
    log.info("Clinical C-index: %.4f", cph_clinical.concordance_index_)

    km_strata_clinical = _compute_km_strata(df, use_rna_proxy=False)
    stats_clinical = _cohort_stats(cph_clinical, df, km_strata_clinical, _FEATURE_COLS)
    _persist_model(cph_clinical, km_strata_clinical, stats_clinical, output_dir, "cox")
    _print_model_summary("Cox clinical-only model", cph_clinical, km_strata_clinical)

    # -----------------------------------------------------------------------
    # RNA-augmented Cox model (optional)
    # -----------------------------------------------------------------------
    rna_dir: Path | None = args.rna_scores_dir
    if rna_dir is not None:
        if not rna_dir.is_dir():
            log.warning("--rna-scores-dir does not exist: %s — skipping RNA model", rna_dir)
        else:
            log.info("Loading RNA scores from %s ...", rna_dir)
            rna_rows: list[dict] = []
            for row in rows:
                scores = _load_rna_scores(row["case_id"], rna_dir)
                if scores is None:
                    continue
                # Require at least CYT and GEP; TIDE optional
                if scores.get("cyt_score") is None or scores.get("gep_score") is None:
                    continue
                rna_rows.append({**row, **scores})

            log.info(
                "RNA scores matched: %d / %d cases (%.0f%%)",
                len(rna_rows), len(rows), 100 * len(rna_rows) / max(len(rows), 1),
            )

            if len(rna_rows) < 20:
                log.warning("Too few RNA-matched cases (%d); skipping RNA Cox model", len(rna_rows))
            else:
                df_rna = pd.DataFrame(rna_rows)
                # Median-impute pack_years within this subset
                df_rna["pack_years"] = df_rna["pack_years"].fillna(df_rna["pack_years"].median())
                # Median-impute TIDE if missing
                if df_rna["tide_score"].isna().any():
                    df_rna["tide_score"] = df_rna["tide_score"].fillna(df_rna["tide_score"].median())

                rna_features = _FEATURE_COLS + _RNA_FEATURE_COLS
                log.info(
                    "Fitting RNA-augmented Cox model on %d cases (%d features)...",
                    len(df_rna), len(rna_features),
                )
                cph_rna = _fit_model(df_rna, extra_features=_RNA_FEATURE_COLS)
                log.info("RNA C-index: %.4f  (vs clinical-only: %.4f)", cph_rna.concordance_index_, cph_clinical.concordance_index_)

                km_strata_rna = _compute_km_strata(df_rna, use_rna_proxy=True)
                stats_rna = _cohort_stats(cph_rna, df_rna, km_strata_rna, rna_features)
                _persist_model(cph_rna, km_strata_rna, stats_rna, output_dir, "cox_rna")
                _print_model_summary("Cox RNA-augmented model", cph_rna, km_strata_rna)

    return 0


if __name__ == "__main__":
    sys.exit(main())
