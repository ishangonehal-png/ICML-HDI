# TCGA-LUAD Pathology MVP Deep Research (2026-03-03)

## Source

- ChatGPT Deep Research conversation: https://chatgpt.com/c/69a7d2b6-6b20-8324-86fc-594b8ff5f439
- Research run stats: **12 min**, **28 citations**, **370 searches**
- Research question: how to ship pathology MVP endpoints (tissue composition + heatmap + evidence) for our LUAD tri-modal hackathon dataset under one-week constraints.

---

## Executive takeaways

1. **Do not build tissue segmentation from scratch for hackathon MVP.**
2. Use a **two-path architecture**:
   - **Fast path (lowest risk, fastest):** reuse pre-segmented LUAD artifacts from **SegLungTCGA**.
   - **Fallback path (generalizable):** on-the-fly SVS tiling + embeddings + lightweight classifier trained on **LubLung**.
3. Keep outputs as **research-grade proxy signals** with uncertainty + QC, not clinical claims.
4. Expose auditable API endpoints for:
   - tissue composition,
   - spatial heatmap,
   - pathology evidence for LLM/tool layer.

---

## Recommended MVP architecture for LUAD tri-modal

### Path A — SegLungTCGA-backed (default demo path)

- Input slide mapped to SegLungTCGA segmented mosaic.
- Decode patch-class colors (tumor/stroma/necrosis/immune/etc.)
- Compute class fractions over non-background tissue.
- Render class heatmap overlay directly from patch grid.
- Return exemplar tiles and summary evidence.

**Why:** fastest route to robust demo behavior without model training risk.

### Path B — Inference fallback (for slides not in SegLungTCGA)

- Read SVS (OpenSlide/TIAToolbox).
- Tile at **87×87 µm** patch scale (same scale family as LubLung/SegLungTCGA).
- Apply tissue mask + empty patch filtering.
- Encode tiles with a modern pathology encoder (recommended: Prov-GigaPath tile encoder).
- Train lightweight classifier on LubLung embeddings (logreg/linear head/small MLP).
- Aggregate patch predictions to slide-level fractions (TIP-style prevalence).

**Why:** allows processing arbitrary LUAD slides while keeping model complexity low.

---

## Definitions for MVP outputs

For slide-level composition (over non-background tissue patches):

- `tumor_fraction`
- `stroma_fraction`
- `necrosis_fraction`

Optional extra outputs:

- `immune_fraction_proxy` (coarse patch-class prevalence, explicitly labeled as proxy)
- full 9-class distribution (tumor, stroma, necrosis, immune, lung, bronchi, vessel, mixed, background)

---

## Endpoint contracts (MVP)

### 1) Tissue composition endpoint

`GET /v1/pathology/slides/{slide_id}/tissue-composition`

Minimal response shape:

```json
{
  "slide_id": "...",
  "model": {
    "method": "seglungtcga_lookup | tile_encoder_linear_head",
    "model_name": "...",
    "model_version": "...",
    "patch_size_um": 87,
    "stride_um": 87
  },
  "results": {
    "mvp_fractions": {
      "tumor": 0.0,
      "stroma": 0.0,
      "necrosis": 0.0,
      "other": 0.0,
      "denominator": "non_background_tissue"
    },
    "full_fractions": {
      "tumor": 0.0,
      "stroma": 0.0,
      "necrosis": 0.0,
      "immune": 0.0,
      "lung": 0.0,
      "bronchi": 0.0,
      "vessel": 0.0,
      "mixed": 0.0,
      "background": 0.0
    },
    "counts": {
      "n_patches_total": 0,
      "n_patches_non_background": 0,
      "n_patches_qc_valid": 0
    }
  },
  "uncertainty": {
    "tile_entropy_mean": 0.0,
    "tile_entropy_p90": 0.0,
    "fraction_ci95": {
      "tumor": [0.0, 0.0],
      "stroma": [0.0, 0.0],
      "necrosis": [0.0, 0.0]
    }
  },
  "qc": {
    "background_fraction": 0.0,
    "artifact_fraction_est": 0.0,
    "warnings": []
  }
}
```

### 2) Spatial heatmap endpoint

`GET /v1/pathology/slides/{slide_id}/heatmap?roi=x,y,w,h&level=8&format=png`

Two practical return options:

- **Option A (recommended):** PNG overlay + class legend (fastest UI integration)
- **Option B:** sparse patch grid with per-cell class/probability/entropy

### 3) Pathology evidence endpoint (for LLM tool layer)

`POST /v1/pathology/slides/{slide_id}/evidence`

Returns:

- slide-level summary (`tumor/stroma/necrosis` + optional immune proxy)
- top-k evidence tiles per class with confidence + coords
- limitations/warnings list
- optional report-text spans / optional RNA-supporting features

---

## Minimal evaluation plan (hackathon-feasible)

- Use **10–15 LUAD slides** with varied morphology/quality.
- Quick human check via QuPath point sampling:
  - ~200 random tissue points per slide,
  - label as tumor/stroma/necrosis/other.
- Metrics:
  - point-level macro-F1 / confusion matrix,
  - slide-level MAE on fractions,
  - optional Spearman sanity-check with RNA immune/stromal scores.

---

## Risk controls and anti-overclaim policy

Use explicit wording across UI/API/pitch:

- “Research-only prototype.”
- “Patch-grid prevalence estimate at ~87 µm resolution.”
- “Not a clinical tumor-purity assay.”
- “Immune value is a coarse proxy, not validated immune-cell density.”

Hard gates:

- If low tissue coverage or high artifact burden, return `answerable=false` or strong warning.
- Always return method + model version + patch size/stride + label set + uncertainty fields.

---

## 6-day implementation plan (4-person team)

### Day 1
- SegLungTCGA loader + mapping + composition calculation.
- Basic `/tissue-composition` + `/heatmap` endpoints.
- Viewer overlay prototype.

### Day 2
- QC fields and evidence tiles.
- `/evidence` endpoint and JSON schema stabilization.
- Build curated hero-slide set.

### Day 3
- Fallback inference spike: SVS tiler at 87 µm + tile embedding cache.
- Train lightweight LubLung classifier.

### Day 4
- Minimal evaluation pass (point sampling + MAE/F1).
- Add uncertainty thresholds and warning logic.

### Day 5
- UI polish + LLM tool integration + provenance logging.

### Day 6
- Freeze dependencies, demo hardening, fallback-safe mode.

---

## Primary references from the Deep Research report

- SegLungTCGA: https://github.com/animgoeth/SegLungTCGA
- LubLung: https://github.com/animgoeth/LubLung
- LUAD segmentation paper (Rączkowska et al., 2022): https://doi.org/10.1186/s12885-022-10081-w
- ARA-CNN code (legacy TF1/Keras risk): https://github.com/animgoeth/ARA-CNN
- Prov-GigaPath paper: https://doi.org/10.1038/s41586-024-07441-w
- Prov-GigaPath repo: https://github.com/prov-gigapath/prov-gigapath
- OpenSlide: https://pubmed.ncbi.nlm.nih.gov/24244884/
- TIAToolbox: https://doi.org/10.1038/s43856-022-00186-5
- QuPath: https://doi.org/10.1038/s41598-017-17204-5
- HistoQC: https://doi.org/10.1200/CCI.18.00157
- ESTIMATE: https://doi.org/10.1038/ncomms3612
- MCP-counter: https://pmc.ncbi.nlm.nih.gov/articles/PMC5073889/
- TCGA-Reports resource: https://doi.org/10.1016/j.patter.2024.100933

---

## Adoption decision recorded

For this repo’s pathology MVP, the current default strategy is:

- **Primary:** SegLungTCGA lookup + composition + heatmap
- **Secondary:** LubLung-trained lightweight head on modern tile embeddings for non-covered slides
- **Positioning:** research-only estimates with explicit uncertainty and QC
