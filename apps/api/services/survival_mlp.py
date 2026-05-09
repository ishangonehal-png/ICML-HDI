"""Survival MLP prediction from pathology + RNA embeddings + cohort metadata (trained by scripts/train_survival_rna_mlp.py). Pathology is required."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import numpy as np

from schemas.clinical import ClinicalSurvivalMlpResponse
from schemas.pathology import MethodMetadata

REPO_ROOT = Path(__file__).resolve().parents[3]
_repo_root_env = os.getenv("SURVIVAL_MLP_REPO_ROOT", "").strip()
if _repo_root_env:
    _root = Path(_repo_root_env).expanduser().resolve()
    if _root.is_dir():
        REPO_ROOT = _root
_DEFAULT_MODEL_DIR = REPO_ROOT / "models" / "survival_rna_mlp"
_DEFAULT_FUSED_MODEL_DIR = REPO_ROOT / "models" / "survival_fused_matched"
_DEFAULT_FUSED_CSV = REPO_ROOT / "data" / "luad" / "fused_pathology_rna_embeddings_with_metadata.csv"
_META = MethodMetadata(
    method="survival-mlp-rna-metadata",
    version="hackathon-p0",
    timestamp="2026-03-08T00:00:00Z",
    proxy_estimate=True,
)


def _normalize_case_id(s: str) -> str:
    s = (s or "").strip().upper()
    if not s or not s.startswith("TCGA-"):
        return s
    parts = s.split("-")
    if len(parts) >= 3:
        return "-".join(parts[:3])
    return s


def _case_to_slide_id(case_id: str) -> str:
    c = (case_id or "").strip()
    if not c:
        return ""
    if "-DX" in c.upper() or "-01Z-" in c.upper():
        return c
    return f"{c}-01Z-00-DX1"


def _find_pathology_embedding_path(embeddings_dir: Path, slide_id: str):
    if not embeddings_dir.is_dir() or not slide_id:
        return None
    slide_lower = slide_id.lower()
    for p in embeddings_dir.rglob("*.npy"):
        if p.name.startswith(".") or p.name.endswith("_coords.npy"):
            continue
        if slide_lower in p.stem.lower() or slide_lower in p.name.lower():
            return p
    return None


def _load_pathology_vector(embeddings_dir: Path, case_id: str):
    slide_id = _case_to_slide_id(case_id)
    path = _find_pathology_embedding_path(embeddings_dir, slide_id)
    if path is None:
        return None
    try:
        arr = np.load(path, allow_pickle=False)
        if arr.size == 0:
            return None
        if arr.ndim == 1:
            return arr.astype(np.float32)
        return np.asarray(arr.mean(axis=0), dtype=np.float32)
    except (OSError, ValueError):
        return None


def _load_model_artifacts(model_dir: Path) -> tuple[Any, Any, dict[str, list[str]], int, int, Any] | None:
    """Load mlp, scaler, encoder_state, horizon_years, n_pathology_dims, pca (or None). Returns None if any file missing."""
    global _last_model_load_error
    if not model_dir.is_dir():
        _last_model_load_error = f"Model directory not found: {model_dir}"
        return None
    pkl_path = model_dir / "mlp_survival.pkl"
    scaler_path = model_dir / "scaler.pkl"
    encoder_path = model_dir / "encoder_state.json"
    metrics_path = model_dir / "metrics.json"
    if not pkl_path.is_file() or not scaler_path.is_file() or not encoder_path.is_file():
        _last_model_load_error = "Required model artifacts missing (mlp_survival.pkl / scaler.pkl / encoder_state.json)."
        return None
    try:
        import pickle
        with pkl_path.open("rb") as f:
            mlp = pickle.load(f)
        with scaler_path.open("rb") as f:
            scaler = pickle.load(f)
        encoder_state = json.loads(encoder_path.read_text(encoding="utf-8"))
        horizon = 2
        n_pathology_dims = 0
        if metrics_path.is_file():
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
            horizon = int(metrics.get("horizon_years", 2))
            n_pathology_dims = int(metrics.get("n_pathology_dims", 0))
        pca = None
        if (model_dir / "pca.pkl").is_file():
            with (model_dir / "pca.pkl").open("rb") as f:
                pca = pickle.load(f)
        _last_model_load_error = None
        return mlp, scaler, encoder_state, horizon, n_pathology_dims, pca
    except (OSError, json.JSONDecodeError, TypeError, ModuleNotFoundError, ImportError, AttributeError) as exc:
        # Handle environments where optional training-time deps (e.g. sklearn)
        # are unavailable in the serving image; surface as unavailable instead of
        # crashing API routes.
        _last_model_load_error = f"Failed to load Survival MLP artifacts: {exc.__class__.__name__}: {exc}"
        return None


def _load_fused_embeddings_csv(path: Path, id_col: str = "tcga_id") -> dict[str, list[float]]:
    """Load fused CSV; return dict[normalized_case_id] -> feature vector (list[float]) in column order."""
    if not path.is_file():
        return {}
    import csv
    out: dict[str, list[float]] = {}
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    if not rows:
        return {}
    feature_cols = [k for k in fieldnames if (k or "").strip() and k != id_col]
    for row in rows:
        cid = (row.get(id_col) or "").strip()
        if not cid:
            continue
        try:
            vec = [float(row.get(k, 0)) for k in feature_cols]
        except (ValueError, TypeError):
            continue
        out[_normalize_case_id(cid)] = vec
    return out


def _load_embeddings_csv(path: Path) -> dict[str, list[float]]:
    if not path.is_file():
        return {}
    import csv
    out: dict[str, list[float]] = {}
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = list(reader.fieldnames or [])
    if not rows:
        return {}
    id_col = "case_id" if "case_id" in fieldnames else (fieldnames[0] if fieldnames else "")
    numeric_cols = [k for k in fieldnames if k != id_col and (k or "").strip()]
    if not numeric_cols:
        numeric_cols = list(rows[0].keys())
        if id_col:
            numeric_cols.remove(id_col)
    for row in rows:
        sid = (row.get(id_col) or (row.get(fieldnames[0]) if fieldnames else "") or "").strip()
        if not sid:
            continue
        try:
            vec = [float(row.get(k, 0)) for k in numeric_cols]
        except (ValueError, TypeError):
            continue
        out[sid] = vec
        out[_normalize_case_id(sid)] = vec
    return out


def _load_cohort_and_rna_key_mapping(cohort_path: Path) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Returns (case_id -> metadata dict, sample_id -> case_id)."""
    if not cohort_path.is_file():
        return {}, {}
    import csv
    by_case: dict[str, dict[str, Any]] = {}
    sample_to_case: dict[str, str] = {}
    with cohort_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            pid = _normalize_case_id(row.get("patient_id") or row.get("case_id") or "")
            if not pid:
                continue
            by_case[pid] = {
                "gender": (row.get("gender") or "").strip().lower() or "unknown",
                "race": (row.get("race") or "").strip().lower() or "unknown",
                "ethnicity": (row.get("ethnicity") or "").strip().lower() or "unknown",
                "tumor_stage": (row.get("tumor_stage") or "").strip().lower() or "unknown",
                "smoking_status": (row.get("smoking_status") or "").strip().lower() or "unknown",
                "age_at_diagnosis_years": (row.get("age_at_diagnosis_years") or "").strip(),
            }
            fname = (row.get("selected_rna_file_name") or "").strip().rstrip(".tsv")
            if fname:
                sample_to_case[fname] = pid
            fid = (row.get("selected_rna_file_id") or "").strip()
            if fid:
                sample_to_case[f"{fid}.rna_seq.augmented_star_gene_counts"] = pid
    return by_case, sample_to_case


def _build_meta_vector(meta: dict[str, Any], encoder_state: dict[str, list[str]], age_median: float) -> list[float]:
    row: list[float] = []
    try:
        age = float(meta.get("age_at_diagnosis_years") or 0)
    except (ValueError, TypeError):
        age = age_median
    row.append(age if age > 0 else age_median)
    for k in ("gender", "race", "ethnicity", "tumor_stage", "smoking_status"):
        opts = encoder_state.get(k, ["unknown"])
        v = (meta.get(k) or "").strip() or "unknown"
        for opt in opts:
            row.append(1.0 if opt == v else 0.0)
    return row


# Lazy-loaded singleton: mlp, scaler, encoder_state, horizon, n_pathology_dims, embeddings, cohort_meta, sample_to_case, age_median, pathology_dir
_cached: tuple[Any, Any, dict, int, int, dict[str, list[float]], dict[str, dict], dict[str, str], float, Path] | None = None
_last_model_load_error: str | None = None


def _get_cached_artifacts() -> tuple[Any, Any, dict, int, int, dict[str, list[float]], dict[str, dict], dict[str, str], float, Path] | None:
    global _cached, _last_model_load_error
    if _cached is not None:
        return _cached
    model_dir_raw = os.getenv("SURVIVAL_MLP_MODEL_DIR", "").strip()
    model_dir = Path(model_dir_raw).expanduser().resolve() if model_dir_raw else _DEFAULT_MODEL_DIR
    if not model_dir.is_absolute():
        model_dir = model_dir.resolve()
    loaded = _load_model_artifacts(model_dir)
    if loaded is None and not model_dir_raw and _DEFAULT_FUSED_MODEL_DIR.is_dir():
        model_dir = _DEFAULT_FUSED_MODEL_DIR.resolve()
        loaded = _load_model_artifacts(model_dir)
    if loaded is None:
        return None
    mlp, scaler, encoder_state, horizon, n_pathology_dims, pca = loaded
    fused_csv_raw = os.getenv("SURVIVAL_MLP_FUSED_CSV", "").strip()
    fused_path = Path(fused_csv_raw).expanduser().resolve() if fused_csv_raw else _DEFAULT_FUSED_CSV
    if pca is not None and fused_path.is_file():
        fused_embeddings = _load_fused_embeddings_csv(fused_path, id_col="tcga_id")
        if fused_embeddings:
            _cached = (mlp, scaler, encoder_state, horizon, n_pathology_dims, {}, {}, {}, 0.0, None, pca, fused_embeddings)
            return _cached
    pathology_dir_raw = os.getenv("SURVIVAL_MLP_PATHOLOGY_EMBEDDINGS_DIR", "").strip()
    pathology_dir = Path(pathology_dir_raw).expanduser().resolve() if pathology_dir_raw else None
    if not pathology_dir or not pathology_dir.is_dir():
        return None
    emb_path_raw = os.getenv("SURVIVAL_MLP_EMBEDDINGS_CSV", "").strip()
    cohort_path_raw = os.getenv("SURVIVAL_MLP_COHORT_CSV", "").strip()
    emb_path = Path(emb_path_raw).expanduser() if emb_path_raw else (REPO_ROOT / "data" / "luad" / "bulkformer_sample_embeddings.csv")
    cohort_path = Path(cohort_path_raw).expanduser() if cohort_path_raw else (REPO_ROOT / "data" / "luad" / "tcga_matched_cohort.csv")
    if not emb_path.is_file():
        _cached = (mlp, scaler, encoder_state, horizon, n_pathology_dims, {}, {}, {}, 0.0, pathology_dir, None, None)
        return _cached
    embeddings = _load_embeddings_csv(emb_path)
    cohort_meta, sample_to_case = _load_cohort_and_rna_key_mapping(cohort_path)
    ages = [float(m.get("age_at_diagnosis_years") or 0) for m in cohort_meta.values() if m.get("age_at_diagnosis_years")]
    try:
        age_median = float(np.nanmedian(ages)) if ages else 62.0
    except Exception:
        age_median = 62.0
    _cached = (mlp, scaler, encoder_state, horizon, n_pathology_dims, embeddings, cohort_meta, sample_to_case, age_median, pathology_dir, None, None)
    return _cached


def get_survival_mlp_prediction(case_id: str) -> ClinicalSurvivalMlpResponse:
    """
    Run the survival MLP for a case: look up RNA embedding and cohort metadata,
    concatenate, scale, predict. Returns response with probability and predicted class.
    """
    case_id = (case_id or "").strip()
    normalized = _normalize_case_id(case_id)
    cached = _get_cached_artifacts()
    if cached is None:
        return ClinicalSurvivalMlpResponse(
            case_id=case_id,
            available=False,
            horizon_years=None,
            probability=None,
            predicted_class=None,
            data_source="survival_mlp",
            unavailable_reason=_last_model_load_error or "Survival MLP not loaded: set SURVIVAL_MLP_MODEL_DIR and SURVIVAL_MLP_PATHOLOGY_EMBEDDINGS_DIR.",
            meta=_META,
        )
    mlp, scaler, encoder_state, horizon, _n_pathology_dims, embeddings, cohort_meta, sample_to_case, age_median, pathology_dir, pca, fused_embeddings = cached
    if pca is not None and fused_embeddings is not None:
        vec = fused_embeddings.get(normalized)
        if vec is None:
            return ClinicalSurvivalMlpResponse(
                case_id=case_id,
                available=False,
                horizon_years=horizon,
                probability=None,
                predicted_class=None,
                data_source="survival_mlp",
                unavailable_reason="No fused embeddings found for this case.",
                meta=_META,
            )
        try:
            X = np.array(vec, dtype=np.float32).reshape(1, -1)
            X_pca = pca.transform(X)
            X_scaled = scaler.transform(X_pca)
            proba = mlp.predict_proba(X_scaled)[0]
            prob_survived = float(proba[1]) if len(proba) == 2 else float(proba[0])
            pred_class = int(mlp.predict(X_scaled)[0])
            return ClinicalSurvivalMlpResponse(
                case_id=case_id,
                available=True,
                horizon_years=horizon,
                probability=round(prob_survived, 4),
                predicted_class=pred_class,
                data_source="survival_mlp",
                unavailable_reason=None,
                meta=_META,
            )
        except Exception as e:
            return ClinicalSurvivalMlpResponse(
                case_id=case_id,
                available=False,
                horizon_years=horizon,
                probability=None,
                predicted_class=None,
                data_source="survival_mlp",
                unavailable_reason=f"Prediction failed: {e!s}",
                meta=_META,
            )
    pathology_vec = _load_pathology_vector(pathology_dir, normalized)
    if pathology_vec is None:
        return ClinicalSurvivalMlpResponse(
            case_id=case_id,
            available=False,
            horizon_years=horizon,
            probability=None,
            predicted_class=None,
            data_source="survival_mlp",
            unavailable_reason="No pathology embedding found for this case (required).",
            meta=_META,
        )
    rna_vec = embeddings.get(normalized)
    if rna_vec is None:
        for sid, cid in sample_to_case.items():
            if cid == normalized:
                rna_vec = embeddings.get(sid)
                break
    if rna_vec is None:
        return ClinicalSurvivalMlpResponse(
            case_id=case_id,
            available=False,
            horizon_years=horizon,
            probability=None,
            predicted_class=None,
            data_source="survival_mlp",
            unavailable_reason="No RNA embedding found for this case.",
            meta=_META,
        )
    meta = cohort_meta.get(normalized, {})
    meta_vec = _build_meta_vector(meta, encoder_state, age_median)
    try:
        X = np.concatenate([
            np.asarray(pathology_vec, dtype=np.float32).ravel(),
            np.array(rna_vec, dtype=np.float32),
            np.array(meta_vec, dtype=np.float32),
        ]).reshape(1, -1)
        X_scaled = scaler.transform(X)
        proba = mlp.predict_proba(X_scaled)[0]
        if len(proba) == 2:
            prob_survived = float(proba[1])
        else:
            prob_survived = float(proba[0])
        pred_class = int(mlp.predict(X_scaled)[0])
        return ClinicalSurvivalMlpResponse(
            case_id=case_id,
            available=True,
            horizon_years=horizon,
            probability=round(prob_survived, 4),
            predicted_class=pred_class,
            data_source="survival_mlp",
            unavailable_reason=None,
            meta=_META,
        )
    except Exception as e:
        return ClinicalSurvivalMlpResponse(
            case_id=case_id,
            available=False,
            horizon_years=horizon,
            probability=None,
            predicted_class=None,
            data_source="survival_mlp",
            unavailable_reason=f"Prediction failed: {e!s}",
            meta=_META,
        )
