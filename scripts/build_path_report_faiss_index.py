"""Build a Bio_ClinicalBERT FAISS index over TCGA-LUAD pathology report text.

Can run locally (small cohort) or on Modal (full 462-case cohort with GPU).

Usage — local
-------------
    python scripts/build_path_report_faiss_index.py local \\
        --reports-dir data/clinical/reports \\
        --output-dir  data/clinical \\
        --device      cpu

Usage — Modal (GPU)
-------------------
    python scripts/build_path_report_faiss_index.py modal \\
        --reports-dir data/clinical/reports \\
        --output-dir  data/clinical

Outputs (in --output-dir)
--------------------------
- ``path_report_faiss.index``    — FAISS flat IP index (cosine after L2-norm)
- ``path_report_case_ids.json``  — ordered list of case_ids matching index rows
- ``faiss_build_stats.json``     — build metadata

The API service reads CLINICAL_PATH_REPORT_FAISS_INDEX env var to locate the
``.index`` file and the sibling ``path_report_case_ids.json``.

Dependencies
------------
    pip install faiss-cpu transformers torch pymupdf
    # Or for GPU: pip install faiss-gpu
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

_MODEL_NAME = "emilyalsentzer/Bio_ClinicalBERT"
_EMBED_DIM = 768
_MAX_TEXT_CHARS = 4096  # ~1024 tokens; BERT max is 512 tokens, truncated by tokenizer
_PDF_SUFFIXES = {".pdf", ".PDF"}
_CASE_ID_PATTERN = re.compile(r"(TCGA-[A-Z0-9]+-[A-Z0-9]+)", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Text extraction (shared with extract_path_report_fields.py)
# ---------------------------------------------------------------------------

def _extract_pdf_text(pdf_path: Path) -> str | None:
    try:
        import fitz  # type: ignore[import-untyped]
    except ImportError:
        log.error("pymupdf not installed. Run: pip install pymupdf")
        return None

    try:
        doc = fitz.open(str(pdf_path))
    except Exception as exc:
        log.warning("Could not open %s: %s", pdf_path, exc)
        return None

    text = "\n".join(page.get_text() for page in doc).strip()
    doc.close()
    return text[:_MAX_TEXT_CHARS] if text else None


def _discover_cases(reports_dir: Path) -> dict[str, Path]:
    cases: dict[str, Path] = {}
    for path in sorted(reports_dir.iterdir()):
        if path.suffix not in _PDF_SUFFIXES:
            continue
        match = _CASE_ID_PATTERN.search(path.stem)
        if match:
            cases[match.group(1).upper()] = path
    return cases


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------

def _load_model(device: str) -> tuple:
    from transformers import AutoModel, AutoTokenizer  # type: ignore[import-untyped]

    log.info("Loading %s...", _MODEL_NAME)
    tokenizer = AutoTokenizer.from_pretrained(_MODEL_NAME)
    model = AutoModel.from_pretrained(_MODEL_NAME)
    model.eval()
    model.to(device)
    return tokenizer, model


def _embed_texts(
    texts: list[str],
    tokenizer: object,
    model: object,
    device: str,
    batch_size: int = 16,
) -> "np.ndarray":  # type: ignore[name-defined]
    import numpy as np
    import torch  # type: ignore[import-untyped]

    all_embeddings: list = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        encoded = tokenizer(  # type: ignore[operator]
            batch,
            padding=True,
            truncation=True,
            max_length=512,
            return_tensors="pt",
        )
        encoded = {k: v.to(device) for k, v in encoded.items()}

        with torch.no_grad():
            out = model(**encoded)  # type: ignore[operator]

        # CLS token embedding
        cls = out.last_hidden_state[:, 0, :].cpu().numpy()  # (batch, 768)
        all_embeddings.append(cls)

        log.debug("Embedded batch %d/%d", min(i + batch_size, len(texts)), len(texts))

    matrix = np.concatenate(all_embeddings, axis=0)
    # L2-normalise for cosine similarity via inner product
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    return (matrix / norms).astype("float32")


# ---------------------------------------------------------------------------
# FAISS index build
# ---------------------------------------------------------------------------

def _build_faiss_index(embeddings: "np.ndarray") -> object:
    import faiss  # type: ignore[import-untyped]

    n, d = embeddings.shape
    log.info("Building FAISS flat IP index: %d vectors × %d dims", n, d)
    index = faiss.IndexFlatIP(d)
    index.add(embeddings)
    return index


def _run_local(
    reports_dir: Path,
    output_dir: Path,
    device: str,
    cohort_csv: Path | None,
) -> int:
    try:
        import faiss  # type: ignore[import-untyped]  # noqa: F401
        import torch  # type: ignore[import-untyped]  # noqa: F401
        import transformers  # type: ignore[import-untyped]  # noqa: F401
        import numpy as np  # type: ignore[import-untyped]  # noqa: F401
    except ImportError as exc:
        log.error("Missing dependency: %s — run: pip install faiss-cpu transformers torch pymupdf", exc)
        return 1

    if not reports_dir.is_dir():
        log.error("--reports-dir does not exist: %s", reports_dir)
        return 1

    output_dir.mkdir(parents=True, exist_ok=True)

    # Cohort filter
    cohort_ids: set[str] | None = None
    if cohort_csv and cohort_csv.is_file():
        import csv
        cohort_ids = set()
        with cohort_csv.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                cid = (row.get("case_id") or "").strip().upper()
                if cid:
                    cohort_ids.add(cid)

    cases = _discover_cases(reports_dir)
    if cohort_ids is not None:
        cases = {cid: p for cid, p in cases.items() if cid in cohort_ids}

    log.info("Embedding %d cases on device=%s", len(cases), device)

    t0 = time.monotonic()
    texts: list[str] = []
    case_ids: list[str] = []
    skipped: list[str] = []

    for cid, pdf_path in sorted(cases.items()):
        text = _extract_pdf_text(pdf_path)
        if text:
            texts.append(text)
            case_ids.append(cid)
        else:
            skipped.append(cid)

    if not texts:
        log.error("No text extracted from any PDF")
        return 1

    log.info("Extracted text from %d/%d PDFs (%d skipped)", len(texts), len(cases), len(skipped))

    tokenizer, model = _load_model(device)
    embeddings = _embed_texts(texts, tokenizer, model, device)

    index = _build_faiss_index(embeddings)

    import faiss  # type: ignore[import-untyped]

    index_path = output_dir / "path_report_faiss.index"
    faiss.write_index(index, str(index_path))
    log.info("Saved FAISS index → %s", index_path)

    ids_path = output_dir / "path_report_case_ids.json"
    ids_path.write_text(json.dumps(case_ids, indent=2), encoding="utf-8")
    log.info("Saved case ID list → %s", ids_path)

    elapsed = time.monotonic() - t0
    stats = {
        "model": _MODEL_NAME,
        "n_cases": len(case_ids),
        "n_skipped": len(skipped),
        "skipped_case_ids": skipped,
        "embed_dim": _EMBED_DIM,
        "device": device,
        "elapsed_seconds": round(elapsed, 1),
    }
    stats_path = output_dir / "faiss_build_stats.json"
    stats_path.write_text(json.dumps(stats, indent=2), encoding="utf-8")
    log.info("Built index in %.1fs — %d cases embedded", elapsed, len(case_ids))
    return 0


# ---------------------------------------------------------------------------
# Modal GPU runner
# ---------------------------------------------------------------------------

def _run_modal(reports_dir: Path, output_dir: Path, cohort_csv: Path | None) -> int:
    """Launch the embedding + index build as a Modal function with GPU."""
    try:
        import modal  # type: ignore[import-untyped]
    except ImportError:
        log.error("modal not installed. Run: pip install modal")
        return 1

    app = modal.App("bio-clinicalbert-faiss-build")

    image = (
        modal.Image.debian_slim(python_version="3.11")
        .pip_install(
            "faiss-cpu",
            "transformers",
            "torch",
            "pymupdf",
            "numpy",
        )
    )

    @app.function(
        image=image,
        gpu="A10G",
        timeout=3600,
        mounts=[
            modal.Mount.from_local_dir(str(reports_dir), remote_path="/reports"),
            *(
                [modal.Mount.from_local_file(str(cohort_csv), remote_path="/cohort.csv")]
                if cohort_csv and cohort_csv.is_file()
                else []
            ),
        ],
    )
    def build_index_remote() -> bytes:
        import io
        import zipfile
        from pathlib import Path as _Path

        from build_path_report_faiss_index import _discover_cases, _embed_texts, _load_model

        remote_reports = _Path("/reports")
        remote_cohort = _Path("/cohort.csv") if cohort_csv else None

        local_cases = _discover_cases(remote_reports)
        if remote_cohort and remote_cohort.is_file():
            import csv
            ids: set[str] = set()
            with remote_cohort.open(newline="", encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    cid = (row.get("case_id") or "").strip().upper()
                    if cid:
                        ids.add(cid)
            local_cases = {c: p for c, p in local_cases.items() if c in ids}

        texts, case_ids = [], []
        for cid, pdf_path in sorted(local_cases.items()):
            text = _extract_pdf_text(pdf_path)
            if text:
                texts.append(text)
                case_ids.append(cid)

        tokenizer, model = _load_model("cuda")
        embeddings = _embed_texts(texts, tokenizer, model, "cuda")

        import faiss  # type: ignore[import-untyped]
        import numpy as np  # type: ignore[import-untyped]

        index = faiss.IndexFlatIP(embeddings.shape[1])
        index.add(embeddings)

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            idx_buf = io.BytesIO()
            faiss.write_index(index, faiss.BufferedIOWriter(idx_buf))
            zf.writestr("path_report_faiss.index", idx_buf.getvalue())
            zf.writestr("path_report_case_ids.json", json.dumps(case_ids))
        return buf.getvalue()

    log.info("Launching Modal build function (GPU=A10G)...")
    with app.run():
        zip_bytes: bytes = build_index_remote.remote()

    import io
    import zipfile

    output_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for name in zf.namelist():
            (output_dir / name).write_bytes(zf.read(name))
    log.info("Downloaded artifacts to %s", output_dir)
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Build Bio_ClinicalBERT FAISS index over pathology reports.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    sub = p.add_subparsers(dest="runner", required=True)

    for runner in ("local", "modal"):
        sp = sub.add_parser(runner, help=f"Run {runner}")
        sp.add_argument("--reports-dir", required=True, type=Path)
        sp.add_argument("--output-dir", required=True, type=Path)
        sp.add_argument("--cohort-csv", type=Path, default=None)
        if runner == "local":
            sp.add_argument("--device", default="cpu", help="torch device (cpu/cuda/mps)")

    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.runner == "local":
        return _run_local(
            reports_dir=args.reports_dir,
            output_dir=args.output_dir,
            device=args.device,
            cohort_csv=args.cohort_csv,
        )
    return _run_modal(
        reports_dir=args.reports_dir,
        output_dir=args.output_dir,
        cohort_csv=args.cohort_csv,
    )


if __name__ == "__main__":
    sys.exit(main())
