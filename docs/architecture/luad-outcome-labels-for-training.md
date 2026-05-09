# LUAD Outcome Labels for Training Predictions from Embeddings

This doc describes **outcome labels available in TCGA-LUAD** that are not known at presentation but can contextualize histology and transcriptomics embeddings for training predictive models (e.g. survival, recurrence-like outcomes).

---

## 1. Why these labels matter

At presentation, a clinician has:
- **Histology** (H&E slide) and optionally **transcriptomics** (RNA-seq).
- **Baseline clinical** (stage, age, smoking, etc.).

They do **not** know:
- **Overall survival** (time to death or censoring).
- **Recurrence / progression** (when/if disease recurs or progresses).

Training on these outcomes lets you:
- **Contextualize embeddings**: learn which slide/RNA patterns associate with better or worse outcomes.
- **Predict from embeddings**: at inference, predict survival probability or risk tier from new slide/RNA embeddings alone (or fused with clinical).

---

## 2. Outcome labels available in LUAD data

### 2.1 Overall survival (primary label)

| Field | Source | Description |
|-------|--------|-------------|
| **vital_status** | TCGA clinical XML / cohort | `Alive` or `Dead`. |
| **days_to_death** | TCGA clinical XML | Days from diagnosis to death (missing if alive). |
| **days_to_last_follow_up** | TCGA clinical XML | Days from diagnosis to last follow-up (used as censoring time when alive). |

**Derived for training:**
- **survival_time_days** = `days_to_death` if dead, else `days_to_last_follow_up` (or max follow-up).
- **event** = 1 if dead, 0 if censored (alive at last follow-up).
- **Binary outcomes** (optional): `survived_1yr`, `survived_2yr`, `survived_5yr` (1 if survival_time ≥ 365/730/1825 and not dead before that horizon; 0 if dead before; NaN if censored before horizon).

These are parsed today in `apps/api/services/clinical.py` from clinical XML (`days_to_death`, `days_to_last_followup` / `days_to_last_follow_up`) and used for the survival-baseline endpoint.

### 2.2 Recurrence / progression

TCGA clinical data are **not** standardized for recurrence or progression-free survival across all projects. LUAD XML may include:
- **new_tumor_event** or follow-up sections in some GDC releases.
- **Disease-free / progression-free** is not consistently defined in the same way as in trial data.

**Practical approach:**
- Use **overall survival** as the main training label (well populated, clearly defined).
- Optionally add **recurrence-like proxies** if you find and parse them (e.g. from GDC follow-up or supplemental files); otherwise treat "recurrence" as a future extension when such fields are curated.

---

## 3. Where labels come from in this repo

| Source | How to get labels |
|--------|--------------------|
| **Cohort CSV** | `scripts/build_tcga_matched_cohort.py` outputs a CSV with `case_id`, `patient_id`, plus demographics. It does **not** include survival fields; those come from GDC clinical XML. |
| **Clinical XML** | Per-case XML under `CLINICAL_XML_DIR` (or GDC download). Parsed by `apps/api/services/clinical.py`; tags: `vital_status`, `days_to_death`, `days_to_last_followup` / `days_to_last_follow_up`. |
| **Precomputed payloads** | If you have JSON/artifact payloads with `patient_summary.days_to_death`, `summary.vital_status`, etc., the same clinical service can consume them via `_extract_features_from_mapping`. |

A **labels table** can be built by:
1. Iterating over cohort `case_id`s.
2. For each case, reading clinical XML (or precomputed payload) and extracting vital_status, days_to_death, days_to_last_follow_up.
3. Computing survival_time_days, event, and optional 1/2/5-year binary flags.
4. Writing a table: `case_id, patient_id, survival_time_days, event, survived_1yr, survived_2yr, survived_5yr, vital_status, ...`.

---

## 4. How this contextualizes embeddings

- **Histology embeddings** (e.g. Prov-GigaPath tile embeddings → slide-level vector): train a head (Cox, XGBoost survival, or binary classifiers for 1/2/5-yr) so slide morphology is associated with observed survival.
- **Transcriptomics embeddings / features** (e.g. TIDE, GEP, CYT, subtype): same idea; these can be inputs alone or concatenated with slide embeddings.
- **Fusion**: concatenate slide_emb + rna_vec (+ optional clinical tabular), then train on survival/recurrence proxies. This matches the "embedding cache → fusion model" picture in `docs/architecture/predictive-tasks-data-flow.md`.

Outcomes are **not** known at presentation, so they are valid **supervision targets** for embedding-space models that will later be used at inference to contextualize new patients.

---

## 5. Other ways to contextualize embeddings

Besides **survival/recurrence** (above), you can contextualize histology and transcriptomics embeddings in these ways:

### 5.1 Cross-modal prediction targets (train embedding → biology)

Use **RNA-derived or histology-derived labels** as supervision so embeddings align with known biology:

| Target | Source | Use case |
|--------|--------|----------|
| **TIDE / GEP / CYT** | Transcriptomics pipeline (this repo) | Train H&E slide embedding → RNA surrogate; “what would RNA say?” from morphology alone. |
| **Molecular subtype** | RNA (Consensus LUAD subtypes: Classical, Secretory, Proximal-Inflammatory, Proximal-Proliferative) | Classify subtype from slide or fused embedding; contextualizes by treatment-relevant biology. |
| **Tissue composition** | Pathology artifacts (Tumor / Stroma / Necrosis / Lymphocyte-rich fractions) or TCIA TIL | Regress or classify from slide embedding; contextualizes by morphologic composition. |
| **Immune infiltration proxy** | TCIA TIL-WSI-TCGA or artifact immune score | Train slide → inflamed/excluded/desert; aligns embedding with immune phenotype. |
| **Pathologic stage** | Clinical XML (`tumor_stage`, TNM) | Predict stage from slide (or fuse with clinical); cross-validate against reported stage. |

These are **known at or after** workup; they contextualize embeddings by tying them to interpretable, clinically relevant quantities.

### 5.2 Similar-case retrieval (contextualize by neighborhood)

- Build a **FAISS (or k-NN) index** over fused embeddings (slide + optional RNA + clinical).
- For a new patient, retrieve **top-k similar cases** with known outcomes (survival, stage, subtype).
- Embeddings are contextualized by **“who is like this patient?”** and by the outcomes of those neighbors.

Already envisioned in this repo: `get_similar_cases`, fusion panel, FAISS in `docs/architecture/predictive-tasks-data-flow.md`.

### 5.3 Natural language (ground or generate from embeddings)

- **Ground embeddings with text:** Embed pathology report or clinical notes (e.g. Bio_ClinicalBERT); align or retrieve by similarity so slide/RNA embeddings are contextualized by narrative.
- **Generate from embeddings:** Train a vision–language or captioning head so embeddings produce short summaries (e.g. “Acinar-predominant LUAD with moderate TILs”); contextualizes by language.

### 5.4 Clinical and stage as labels

- **Stage (I–IV)** from XML: train classifier or use as a conditioning input so embeddings are contextualized by stage.
- **Smoking, age, sex**: use as tabular features in fusion or as auxiliary prediction targets to encourage embeddings to capture demographically relevant structure.

### 5.5 Unsupervised structure (no labels)

- **Clustering** (e.g. k-means, HDBSCAN) on slide or fused embeddings → contextualize by cluster (e.g. “cluster 3: high stroma, low TIDE”).
- **Visualization** (UMAP, t-SNE) of embedding space → contextualize by manifold position and nearby cases.

### 5.6 Summary

| Mechanism | Labels / signal | Resulting context |
|-----------|------------------|-------------------|
| Survival / recurrence | OS, event, 1/2/5-yr | Prognosis, risk |
| RNA surrogates (TIDE, GEP, CYT, subtype) | Transcriptomics pipeline | Biology, treatment proxy |
| Tissue composition / TIL | Artifacts, TCIA | Morphology, immune context |
| Similar-case retrieval | Index + outcomes | “Patients like this one” |
| Natural language | Reports, captions | Narrative, explainability |
| Stage / clinical | XML, tabular | Demographics, staging |
| Clustering / visualization | None | Group structure, discovery |

You can combine several: e.g. train on survival **and** subtype, then use the same embeddings for similar-case retrieval and for generating a short narrative.

---

You can combine several: e.g. train on survival **and** subtype, then use the same embeddings for similar-case retrieval and for short narrative generation.

---

## 6. Feeding contextualized embeddings into the agent

To **feed contextualized embedding-derived context into the agent** (for chat or an external LLM):

1. **GET `/v1/agent/context/{case_id}`** — Returns a structured payload built from fusion, pathology, transcriptomics, clinical, survival baseline, and similar-case retrieval. The field **`context_for_llm`** is a single formatted text blob of all these signals, suitable for inclusion in an agent or LLM system/user prompt.
2. **POST `/v1/agent/query`** — Accepts `case_id` and `question`. The backend builds context via `build_agent_context` (one fetch for both context and query), passes `context_for_llm` into the LLM along with structured metrics, and returns an answer grounded in that context.

The agent never receives raw embedding vectors; it receives **derived context** (scores, tissue summary, clinical summary, survival summary, similar cases, etc.). To use an external LLM, call GET `/v1/agent/context/{case_id}`, pass `context_for_llm` (and optionally the structured fields) into your prompt, and send the user’s question.

- **Backend:** `apps/api/routers/agent.py` (GET context, POST query), `apps/api/services/agent_context.py` (`build_agent_context`), `apps/api/schemas/agent.py` (`AgentContextResponse`).
- **Frontend:** `apiClient.getAgentContext(caseId)` and `apiClient.queryAgent({ case_id, query })` in `apps/web/lib/api-client/client.ts`.

---

## 7. References in this repo

- **Predictive data flow** (embedding cache, survival labels, fusion): `docs/architecture/predictive-tasks-data-flow.md`.
- **Clinical parsing** (vital_status, days_to_death, days_to_last_follow_up): `apps/api/services/clinical.py` (`_ClinicalFeatures`, `_parse_xml_file`, `_compute_survival_baseline`).
- **Cohort + manifest**: `scripts/build_tcga_matched_cohort.py`, `data/manifests/README.md`.
- **Pathology embeddings**: `ENSO_EMBEDDINGS_DIR`, `scripts/audit_luad_embedding_coverage.py`, `apps/api/services/pathology_assets.py`.

---

*Generated for training predictions from embeddings using LUAD survival (and optional recurrence) labels.*
