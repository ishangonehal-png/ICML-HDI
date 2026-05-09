from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCHEMA = REPO_ROOT / "packages/schemas/tcga_luad_data_contract_v1.json"
DEFAULT_COHORT = REPO_ROOT / "hansons-context/tcga_downloads/tcga_luad_exact_matched_cohort.csv"
DEFAULT_MANIFEST = REPO_ROOT / "hansons-context/tcga_downloads/tcga_luad_exact_matched_manifest.tsv"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "data/manifests"
