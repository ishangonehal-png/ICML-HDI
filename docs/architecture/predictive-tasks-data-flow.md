# Multi-Modal Clinical AI Agent — Predictive Tasks & Data Flow

> **Disease focus:** TCGA-LUAD (Lung Adenocarcinoma) pilot cohort
> **Core clinical story:** Estimate immunotherapy readiness from H&E + clinical data early; transcriptomics refines the score when available; an LLM explains the result in natural language.
>
> **⚠️ Label caveat:** TCGA-LUAD lacks direct immunotherapy response labels. All "response" scores are proxy estimates derived from RNA expression signatures (TIDE, GEP, CYT) and survival data, not measured treatment outcomes. See § 4 "What to Cut" for explicit scope boundaries.

---

## 1. Predictive Tasks by Modality

The dashboard surfaces outputs from three modality-specific branches, a fusion layer, and an agent reasoning layer. Tasks are grouped by the data they consume and are ordered by priority for a hackathon build.

---

### 1.1 Pathology Branch — H&E Whole-Slide Images

These predictions are generated from tile embeddings (Google Path Foundation / UNI / VirChow) and slide-level attention pooling. They are the **earliest-available signal** — H&E is ordered before sequencing in the clinical workflow, making this branch the most clinically compelling for a provisional score.

For the MVP **Immune Infiltration Score**, anchor methodology to TCIA’s published TIL computational-stain resource:
- Dataset page: [TIL-WSI-TCGA (TCIA)](https://www.cancerimagingarchive.net/analysis-result/til-wsi-tcga/)
- Data DOI: [10.7937/K9/TCIA.2018.Y75F9W1](https://doi.org/10.7937/K9/TCIA.2018.Y75F9W1)
- Methods paper: [Saltz et al., Cell Reports 2018](https://doi.org/10.1016/j.celrep.2018.03.086)
- Method/tool references: [QuIP Software Stack](https://sbu-bmi.github.io/quip_distro/) and [TIL Classification Software](https://github.com/SBU-BMI/u24_lymphocyte)

| Task | Output | Clinical Relevance | Priority |
|---|---|---|---|
| **Immune Infiltration Score** | Continuous score (0–1) + phenotype label (Inflamed / Excluded / Desert) | Primary histologic predictor of checkpoint response; TIL density and spatial pattern are established pan-cancer biomarkers | 🔴 MVP |
| **Tumor vs. Stroma vs. Necrosis Fraction** | Three continuous fractions summing to 1 | Tumor purity affects downstream signature scores; necrosis fraction is prognostic | 🔴 MVP |
| **Histological Subtype Classification** | Discrete label (Lepidic / Acinar / Papillary / Micropapillary / Solid for LUAD) | Subtypes carry different prognoses and PD-L1 expression distributions; solid/micropapillary are highest-risk | 🟡 V1 |
| **Mitotic Index / Proliferation Proxy** | Low / Intermediate / High | Proliferating tumors may respond differently to checkpoint blockade vs. chemotherapy | 🟡 V1 |
| **PD-L1 Morphologic Proxy** | Low / High (inferred) | Directly linked to pembrolizumab eligibility criteria (TPS ≥ 1% or ≥ 50%); an H&E proxy avoids IHC turnaround time | 🟡 V1 |
| **Spatial Attention Heatmap** | Tile-level saliency overlay on WSI thumbnail | Explainability layer — shows clinician which slide regions drove the score | 🔴 MVP |
| **Pathologic Stage Proxy** | Stage I–IV (inferred from slide features) | Cross-validate against reported clinical stage; discordance flags edge cases | 🟢 V2 |

**Implementation note:** All outputs above derive from the same tile embedding pass — compute once, cache, then run lightweight heads per task. Do not re-tile or re-embed per task.

**MVP integration path for immune infiltration (hackathon-feasible):**
1. Reuse existing LUAD tile pipeline (no new WSI extraction stack).
2. Compute slide-level infiltration proxy from either:
   - direct TCIA TIL map overlap (when slide IDs can be matched), or
   - a lightweight patch head weakly supervised by TCIA-style labels/signals.
3. Expose as `immune_infiltration_proxy_score` (not a clinical-grade endpoint) and show contributing heatmap regions.


---

### 1.2 EHR Branch — Clinical Metadata, Pathology Reports, Lab Data

For TCGA-LUAD, "EHR" resolves to: structured clinical supplement XML (demographics, TNM stage, smoking history, vital status, days-to-death/progression) + machine-readable pathology report text.

> **Implementation note (2026-03-08):** Bio_ClinicalBERT text embedding was originally planned but not implemented. The actual implementation uses structured XML parsing only — age, sex, TNM stage, smoking, ECOG, pack-years are extracted directly from TCGA BCR XMLs and used as tabular features. No text embedding layer exists.

| Task | Output | Clinical Relevance | Priority |
|---|---|---|---|
| **Immunotherapy Eligibility Summary** | Synthesized flag (Eligible / Borderline / Contraindicated) + rationale | Consolidates stage, ECOG proxy, comorbidities, and prior therapy into a clinical-guideline-aligned flag | 🔴 MVP |
| **Overall Survival Prediction** | Survival probability at 1 / 2 / 5 years | Primary long-horizon outcome; derived from Cox-style head or XGBoost on clinical features | 🔴 MVP |
| **Progression Risk Score** | Continuous score + risk tier (Low / Intermediate / High) | Identifies patients likely to progress on current therapy, flagging need for early escalation | 🟡 V1 |
| **Pathologic Stage Classification** | Stage I–IV (TNM-derived) | Direct read from structured TCGA clinical XML; used as a feature and a display value | 🔴 MVP |
| **Treatment History Summary** | NL paragraph | Agent-generated synthesis of prior procedures, chemo, radiation from TCGA clinical fields | 🟡 V1 |
| **Comorbidity & Performance Status** | Charlson index approximation + ECOG proxy | Weights survival predictions and adverse event risk; derived from diagnosis codes and labs | 🟢 V2 |
| **Adverse Event Risk Flag** | Risk tiers per toxicity category (hematologic, hepatic, renal, immune-related) | Immunotherapy-specific: flags patients at elevated risk for irAEs based on baseline labs and autoimmune history | 🟢 V2 |

**Implementation note:** TCGA pathology report text is the best available proxy for clinical notes in this cohort. Structured fields (age, sex, smoking, TNM stage) are passed as raw tabular features — no embedding needed. *(Bio_ClinicalBERT was originally considered for report text embedding but was not implemented; structured XML parsing was sufficient for the MVP.)*

---

### 1.3 Transcriptomics Branch — Bulk RNA-seq (STAR Counts)

These are **surrogate labels** computed from bulk TCGA RNA-seq. They serve two roles: (1) the prediction target for training the early model (H&E + clinical → RNA proxy) and (2) a refinement signal shown in the dashboard when RNA data is available. Use local implementations — the legacy TIDE web server is retired.

| Task | Output | Clinical Relevance | Priority |
|---|---|---|---|
| **TIDE Score** (Tumor Immune Dysfunction & Exclusion) | Continuous score; lower = better ICB candidate | Mechanistic model of immune escape; validated as a predictor of checkpoint response across cancer types | 🔴 MVP |
| **T-cell–Inflamed GEP** (18-gene signature) | Continuous score | FDA-recognized companion diagnostic context for pembrolizumab; pan-cancer validity | 🔴 MVP |
| **CYT Score** (Cytolytic Activity) | Geometric mean of GZMA + PRF1 expression | Simple, interpretable proxy for active cytotoxic immune response | 🔴 MVP |
| **Molecular Subtype Classification** | Discrete label (Classical / Secretory / Proximal-Inflammatory / Proximal-Proliferative for LUAD) | Subtypes predict differential sensitivity to chemotherapy, targeted agents, and immunotherapy | 🟡 V1 |
| **Immune Cell Deconvolution** | Estimated fractions: CD8+ T cells, CD4+ T cells, Tregs, NK cells, M1/M2 macrophages, B cells | Complements H&E TIL scoring with cell-type resolution; CIBERSORT or similar | 🟡 V1 |
| **Oncogenic Pathway Activity Scores** | Scores per pathway (KRAS, EGFR, MYC, PI3K, p53, WNT) | Identifies likely targetable drivers; pathway activity shapes immunotherapy response | 🟡 V1 |
| **Proliferation Index** | Cell cycle gene expression score (e.g., MKI67, TOP2A, PCNA-based) | High proliferation can indicate sensitivity to chemo but variable ICB response | 🟢 V2 |
| **Drug Sensitivity Prediction** | Predicted IC50 proxies for top LUAD drugs (cisplatin, pemetrexed, docetaxel, osimertinib) | Expression-based drug response models from GDSC; useful for chemotherapy fallback if ICB not appropriate | 🟢 V2 |

**Implementation note:** Compute TIDE, GEP, and CYT scores first — they require only summing/averaging over gene lists from normalized expression. Deconvolution and pathway scores come next (pre-built packages: `pydeseq2`, `gsva`-style Python ports). Drug sensitivity is lower priority and can be a V2 display-only feature.

---

### 1.4 Multi-Modal Fusion Layer

Fusion combines cached modality embeddings + missingness flags into a joint prediction. Keep this architecturally simple — the priority is a reliable, explainable score, not a novel architecture.

| Task | Output | Description | Priority |
|---|---|---|---|
| **Composite Immunotherapy Responder Score** | Continuous score (0–100) + confidence interval | Primary dashboard output; fuses H&E embedding + clinical tabular + optional RNA signature vector via XGBoost / LightGBM | 🔴 MVP |
| **Provisional vs. Refined Score** | Score pair + delta + direction arrow | Core product narrative: show score before RNA arrives (H&E + clinical only) and after RNA is added; delta explains RNA's marginal contribution | 🔴 MVP |
| **Modality Contribution Attribution** | Per-modality SHAP bar chart | Tells the clinician whether the slide, the labs, or the expression drove the recommendation | 🔴 MVP |
| **Similar Patient Retrieval** | Top-5 historical patients with outcomes | Nearest-neighbor in fused embedding space; each result card shows: disease course, response outcome, key differentiating features | 🟡 V1 |
| **Treatment Prioritization Ranking** | Ordered therapy list (immunotherapy first / chemo first / targeted first) with confidence | Derived from fusion score + pathway activity + clinical flags | 🟡 V1 |

---

### 1.5 Agent Reasoning Layer (LLM + Tool Calls)

The agent **does not reason over raw embeddings**. It calls structured tool endpoints that return JSON, then synthesizes a natural-language explanation. This is the only approach that is both reliable and buildable in a week.

| Tool | Returns | Enables |
|---|---|---|
| `get_patient_summary` | Demographics, stage, diagnosis, smoking history, performance status | Patient context card |
| `get_pathology_evidence` | Immune infiltration score, subtype, heatmap tile refs, top driving tiles | Slide interpretation paragraph |
| `get_transcriptomic_evidence` | TIDE, GEP, CYT, subtype, deconvolution fractions | RNA interpretation paragraph |
| `get_model_score` | Fusion score, confidence, SHAP values, provisional vs. refined delta | Score explanation paragraph |
| `get_similar_cases` | Top-k patient records with outcomes and key feature deltas | "Patients like this one" retrieval |
| `compare_with_without_rna` | Score A (H&E + clinical), Score B (all three), delta, direction, driver features | Explains RNA's marginal contribution |
| `query_clinical_guidelines` | Relevant NCCN / ESMO guideline snippets for the patient's stage/subtype | Grounds recommendations in published evidence |

**Agent-answerable natural language queries:**
- *"Why is this patient likely to respond to pembrolizumab?"*
- *"What slide regions drove the immunotherapy score?"*
- *"How much did the RNA data change the recommendation?"*
- *"How confident are you without the transcriptomics?"*
- *"Show me 5 similar patients who responded well."*
- *"What would change the recommendation to chemo-first?"*
- *"Is this patient high-risk for immune-related adverse events?"*

---

## 2. Data Flow Schema

```
╔══════════════════════════════════════════════════════════════════════════════╗
║                          RAW DATA INPUTS                                    ║
║                                                                              ║
║  ┌─────────────────┐  ┌──────────────────────┐  ┌───────────────────────┐  ║
║  │  H&E WSI (SVS)  │  │  RNA-seq STAR Counts  │  │  EHR / Clinical XML   │  ║
║  │  ~1.3–1.8 GB    │  │  TSV, ~3–5 MB/case    │  │  + Pathology Reports  │  ║
║  │  per slide      │  │                       │  │  ~47 KB + text        │  ║
║  └────────┬────────┘  └──────────┬────────────┘  └────────────┬──────────┘  ║
╚═══════════╪═══════════════════════╪════════════════════════════╪════════════╝
            │                      │                            │
            ▼                      ▼                            ▼
╔═══════════════════════╗ ╔═════════════════════════╗ ╔════════════════════════╗
║  PATHOLOGY PIPELINE   ║ ║  TRANSCRIPTOMICS PIPELINE║ ║   EHR/CLINICAL PIPELINE║
║                       ║ ║                         ║ ║                        ║
║  1. Tissue masking    ║ ║  1. TPM/CPM             ║ ║  1. Parse XML fields   ║
║     (OTSU / gradient) ║ ║     normalization       ║ ║     (age, sex, stage,  ║
║                       ║ ║                         ║ ║     smoking, vitals)   ║
║  2. Tile extraction   ║ ║  2. Compute surrogate   ║ ║                        ║
║     256×256 px @      ║ ║     labels:             ║ ║  2. Bio_ClinicalBERT   ║
║     20× magnification ║ ║     • TIDE score        ║ ║     on pathology note  ║
║     (cap: 512–2048    ║ ║     • T-cell GEP        ║ ║     text → 768-d       ║
║     tissue tiles/WSI) ║ ║     • CYT score         ║ ║     embedding          ║
║                       ║ ║                         ║ ║                        ║
║  3. Path Foundation / ║ ║  3. Molecular subtype   ║ ║  3. Structured tabular ║
║     UNI tile encoder  ║ ║     (Consensus NMF)     ║ ║     vector:            ║
║     → 1536-d tile     ║ ║                         ║ ║     [age, TNM, PS,     ║
║     embeddings        ║ ║  4. Immune deconvolution ║ ║     smoking, labs]     ║
║                       ║ ║     (CIBERSORT / nnls)  ║ ║                        ║
║  4. Attention pooling ║ ║                         ║ ║  4. Concatenate:       ║
║     (ABMIL) across    ║ ║  5. Pathway activity    ║ ║     [tabular ‖ text    ║
║     tiles →           ║ ║     scores (GSVA/ssGSEA) ║ ║     embedding]        ║
║     1536-d slide      ║ ║     KRAS, EGFR, MYC,   ║ ║     → clinical vector  ║
║     embedding         ║ ║     PI3K, TP53          ║ ║                        ║
║                       ║ ║                         ║ ║                        ║
║  5. Tile saliency     ║ ║  6. RNA feature vector  ║ ║  5. Survival labels    ║
║     scores cached     ║ ║     [TIDE, GEP, CYT,   ║ ║     (vital_status,     ║
║     for heatmap       ║ ║     subtype OHE,        ║ ║     days_to_death,     ║
║                       ║ ║     deconv fractions,   ║ ║     days_to_prog.)     ║
║  OUTPUT:              ║ ║     pathway scores]     ║ ║                        ║
║  slide_emb [1536-d]   ║ ║                         ║ ║  OUTPUT:               ║
║  tile_scores [N]      ║ ║  OUTPUT:                ║ ║  clin_emb [768+k -d]   ║
║                       ║ ║  rna_vec [~30-d]        ║ ║  tabular_vec [k-d]     ║
║                       ║ ║  surrogate_labels       ║ ║  survival_labels       ║
╚═══════════╤═══════════╝ ╚══════════╤══════════════╝ ╚═══════════╤════════════╝
            │                        │                            │
            └────────────────────────┼────────────────────────────┘
                                     │
                                     ▼
╔════════════════════════════════════════════════════════════════════════════════╗
║                        EMBEDDING CACHE (per-patient)                          ║
║                                                                                ║
║   {patient_id: {slide_emb, tile_scores, rna_vec, clin_emb, tabular_vec,      ║
║                  surrogate_labels, survival_labels, modality_flags}}           ║
╚═══════════════════════════════════╤════════════════════════════════════════════╝
                                    │
                                    ▼
╔════════════════════════════════════════════════════════════════════════════════╗
║                           FUSION MODEL LAYER                                   ║
║                                                                                ║
║  Input: [slide_emb ‖ clin_emb ‖ rna_vec* ‖ missingness_flags]               ║
║         (* rna_vec zeroed + flag=0 when RNA not available)                    ║
║                                                                                ║
║  Models (in order of build priority):                                          ║
║  ┌─────────────────────────────────────────────────────────────────────────┐   ║
║  │ 1. Logistic Regression baseline (interpretable, fast to train)          │   ║
║  │ 2. XGBoost / LightGBM (main model — handles missingness natively)       │   ║
║  │ 3. 2-layer MLP (optional — only if baselines are already stable)        │   ║
║  └─────────────────────────────────────────────────────────────────────────┘   ║
║                                                                                ║
║  Outputs per patient:                                                          ║
║  ┌─────────────────────────────────────────────────────────────────────────┐   ║
║  │ • immunotherapy_score_provisional  (H&E + clinical only)                │   ║
║  │ • immunotherapy_score_refined      (all three modalities)               │   ║
║  │ • survival_prob_1yr / 2yr / 5yr                                         │   ║
║  │ • progression_risk_score                                                 │   ║
║  │ • shap_values [per modality + per feature]                              │   ║
║  │ • confidence_interval                                                    │   ║
║  └─────────────────────────────────────────────────────────────────────────┘   ║
╚═══════════════════════════════════╤════════════════════════════════════════════╝
                                    │
                                    ▼
╔════════════════════════════════════════════════════════════════════════════════╗
║                      SIMILARITY INDEX (k-NN Retrieval)                         ║
║                                                                                ║
║  • FAISS index over fused patient embeddings                                   ║
║  • At query time: retrieve top-k similar patients with known outcomes          ║
║  • Returns: outcome label, key feature deltas, days-to-event                   ║
╚═══════════════════════════════════╤════════════════════════════════════════════╝
                                    │
                                    ▼
╔════════════════════════════════════════════════════════════════════════════════╗
║                        EVIDENCE JSON TOOL LAYER                                ║
║                                                                                ║
║  Each tool returns a structured JSON blob. The agent never touches             ║
║  raw embeddings or model internals.                                            ║
║                                                                                ║
║  get_patient_summary()          → demographics, stage, smoking, PS proxy      ║
║  get_pathology_evidence()       → TIL score, subtype, tile saliency refs      ║
║  get_transcriptomic_evidence()  → TIDE, GEP, CYT, subtype, deconv           ║
║  get_model_score()              → provisional score, refined score, SHAP      ║
║  get_similar_cases(k=5)         → top-k patients + outcomes + feature deltas  ║
║  compare_with_without_rna()     → score A, score B, delta, driver features    ║
║  query_clinical_guidelines()    → NCCN/ESMO snippet for stage/subtype         ║
╚═══════════════════════════════════╤════════════════════════════════════════════╝
                                    │
                                    ▼
╔════════════════════════════════════════════════════════════════════════════════╗
║              MULTI-MODAL REASONING AGENT (Claude / GPT-4o)                     ║
║                                                                                ║
║  System prompt: oncology-domain context + tool descriptions + output format   ║
║                                                                                ║
║  Agent loop:                                                                   ║
║  1. Clinician submits query or patient is loaded                               ║
║  2. Agent selects tools to call based on query intent                          ║
║  3. Tools return structured JSON evidence                                       ║
║  4. Agent synthesizes JSON → natural language clinical narrative               ║
║  5. Agent returns:                                                             ║
║     a. Structured report (score + confidence + modality breakdown)            ║
║     b. NL explanation ("Why does this patient score 74/100?")                 ║
║     c. Therapy prioritization rationale                                        ║
║     d. Answered free-text query                                                ║
║     e. Similar-patient card references                                         ║
╚═══════════════════════════════════╤════════════════════════════════════════════╝
                                    │
                                    ▼
╔════════════════════════════════════════════════════════════════════════════════╗
║                          CLINICAL DASHBOARD (UI)                               ║
║                                                                                ║
║  ┌─────────────────────────────────────────────────────────────────────────┐  ║
║  │  PATIENT HEADER                                                         │  ║
║  │  Name / ID | Stage IIIA | LUAD-Acinar | 67y, Male, Ex-smoker           │  ║
║  └─────────────────────────────────────────────────────────────────────────┘  ║
║                                                                                ║
║  ┌──────────────────────┐  ┌───────────────────────────────────────────────┐  ║
║  │  RESPONDER SCORE     │  │  MODALITY BREAKDOWN (SHAP bars)               │  ║
║  │                      │  │                                               │  ║
║  │  Provisional: 61/100 │  │  H&E Slide     ████████░░  +32%              │  ║
║  │  Refined:     74/100 │  │  Clinical      █████░░░░░  +21%              │  ║
║  │  ▲ RNA adds +13 pts  │  │  Transcriptomics ███░░░░░░  +13%             │  ║
║  │  CI: [68, 80]        │  │                                               │  ║
║  └──────────────────────┘  └───────────────────────────────────────────────┘  ║
║                                                                                ║
║  ┌──────────────────────────────┐  ┌────────────────────────────────────────┐ ║
║  │  H&E HEATMAP                 │  │  TRANSCRIPTOMIC PANEL                  │ ║
║  │                              │  │                                        │ ║
║  │  [WSI thumbnail with         │  │  TIDE:    0.31 (Low exclusion ✓)      │ ║
║  │   attention overlay]         │  │  GEP:     0.68 (Inflamed ✓)           │ ║
║  │                              │  │  CYT:     2.14 (Active ✓)             │ ║
║  │  TIL Score: 0.71 (Inflamed)  │  │  Subtype: Prox-Inflammatory           │ ║
║  │  Subtype:   Acinar           │  │  CD8+ T:  28% | Tregs: 6%            │ ║
║  │  Necrosis:  3%               │  │  KRAS:    Low | EGFR: Low            │ ║
║  └──────────────────────────────┘  └────────────────────────────────────────┘ ║
║                                                                                ║
║  ┌─────────────────────────────────────────────────────────────────────────┐  ║
║  │  SURVIVAL CURVES                                                        │  ║
║  │  1-yr OS: 82%  |  2-yr OS: 61%  |  5-yr OS: 34%                       │  ║
║  │  Progression Risk: Intermediate (score: 0.44)                           │  ║
║  └─────────────────────────────────────────────────────────────────────────┘  ║
║                                                                                ║
║  ┌─────────────────────────────────────────────────────────────────────────┐  ║
║  │  SIMILAR PATIENTS (k-NN retrieval)                                      │  ║
║  │  #1 TCGA-05-4244 | Score 76 | Stage IIIA | OS 38mo                     │  ║
║  │  #2 TCGA-05-4249 | Score 71 | Stage IIB  | OS 22mo                     │  ║
║  │  #3 TCGA-05-4390 | Score 68 | Stage IIIB | OS 14mo                     │  ║
║  │  ⚠ TCGA lacks direct ICB response labels; outcomes are OS/vital status  │  ║
║  └─────────────────────────────────────────────────────────────────────────┘  ║
║                                                                                ║
║  ┌─────────────────────────────────────────────────────────────────────────┐  ║
║  │  AGENT EXPLANATION                                                      │  ║
║  │                                                                         │  ║
║  │  "This patient shows strong indicators of immune-hot tumor biology.     │  ║
║  │   The H&E slide reveals dense peritumoral TIL infiltration (score       │  ║
║  │   0.71), consistent with an inflamed TME. TIDE analysis confirms low    │  ║
║  │   immune exclusion (0.31), and the 18-gene T-cell inflamed GEP (0.68)  │  ║
║  │   supports pembrolizumab eligibility. RNA data raised confidence from   │  ║
║  │   61 to 74. Recommend immunotherapy-first approach."                    │  ║
║  │                                                                         │  ║
║  │  [Natural language query box]                                           │  ║
║  │  > "Why did the RNA increase the score?"  [ Ask ]                      │  ║
║  └─────────────────────────────────────────────────────────────────────────┘  ║
╚════════════════════════════════════════════════════════════════════════════════╝
```

---

### 2.1 TIL Methodology & Implementation References

> TIL methodology citations are in § 1.1 above. Not repeated here.

Companion implementation notes (endpoints, QC policy, and 6-day build plan):
- [`../context/deep-research-pathology-mvp.md`](../context/deep-research-pathology-mvp.md)

## 3. Task Priority Matrix

This table consolidates all tasks across modalities into a single build priority view. Tasks tagged 🔴 MVP are the minimum needed for a compelling demo; 🟡 V1 are additions that strengthen the product story; 🟢 V2 are future-facing features.

| Modality | Task | Output Type | Priority | Notes |
|---|---|---|---|---|
| H&E | Immune Infiltration Score | Score + phenotype | 🔴 MVP | Core immunotherapy biomarker |
| H&E | Attention Heatmap | Tile saliency overlay | 🔴 MVP | Explainability — critical for demo |
| H&E | Tumor/Stroma/Necrosis Fraction | Three fractions | 🔴 MVP | Needed for clinical credibility |
| H&E | Histological Subtype | Discrete label | 🟡 V1 | LUAD-specific, differentiates cases |
| H&E | PD-L1 Morphologic Proxy | Low/High flag | 🟡 V1 | Links directly to drug eligibility |
| H&E | Mitotic Index | Low/Mid/High | 🟢 V2 | Adds prognostic depth |
| H&E | Pathologic Stage Proxy | Stage I–IV | 🟢 V2 | Cross-validate with clinical |
| Transcriptomics | TIDE Score | Continuous | 🔴 MVP | Primary label for early model training |
| Transcriptomics | T-cell Inflamed GEP | Continuous | 🔴 MVP | FDA-adjacent checkpoint biomarker |
| Transcriptomics | CYT Score | Continuous | 🔴 MVP | Simplest to compute; highly interpretable |
| Transcriptomics | Molecular Subtype | Discrete label | 🟡 V1 | Differentiates treatment paths |
| Transcriptomics | Immune Deconvolution | Cell-type fractions | 🟡 V1 | Visualizable, clinician-friendly |
| Transcriptomics | Pathway Activity Scores | Per-pathway scores | 🟡 V1 | Grounds targeted therapy discussion |
| Transcriptomics | Proliferation Index | Score | 🟢 V2 | Chemo vs. ICB decision input |
| Transcriptomics | Drug Sensitivity Proxy | IC50 proxies | 🟢 V2 | Display-only for V2 |
| EHR | Pathologic Stage | Stage I–IV | 🔴 MVP | Direct from XML, used as feature |
| EHR | Immunotherapy Eligibility Flag | Flag + rationale | 🔴 MVP | Highest-impact clinical summary |
| EHR | Overall Survival Prediction | 1/2/5-yr probability | 🔴 MVP | Key prognostic output |
| EHR | Treatment History Summary | NL paragraph | 🟡 V1 | Agent-generated from clinical fields |
| EHR | Progression Risk Score | Score + tier | 🟡 V1 | Complements survival prediction |
| EHR | Comorbidity/Performance Status | Charlson + ECOG proxy | 🟢 V2 | Improves adverse event prediction |
| EHR | Adverse Event Risk | Per-category tiers | 🟢 V2 | irAE risk is high value for IO |
| Fusion | Composite Responder Score | 0–100 + CI | 🔴 MVP | Central dashboard output |
| Fusion | Provisional vs. Refined Score | Score pair + delta | 🔴 MVP | Core product narrative |
| Fusion | Modality Attribution (SHAP) | Per-modality bars | 🔴 MVP | Explainability for clinicians |
| Fusion | Similar Patient Retrieval | Top-k cases | 🟡 V1 | Retroactive validation of predictions |
| Fusion | Treatment Prioritization Ranking | Ordered therapy list | 🟡 V1 | Actionable output for clinicians |
| Agent | NL Explanation Generation | Paragraph | 🔴 MVP | Converts JSON evidence to prose |
| Agent | Free-Text Clinical Query | NL answer | 🟡 V1 | Chatbot-style query interface |
| Agent | Guideline Grounding | Snippet | 🟢 V2 | Links to NCCN/ESMO evidence |

---

## 4. What to Cut (and Why)

Based on the meeting notes and feasibility analysis, the following are explicitly out of scope for the hackathon build:

| Cut | Reason |
|---|---|
| Spatial transcriptomics | No matched spatial Tx data in TCGA-LUAD; controlled-access elsewhere |
| True treatment-response labels | TCGA lacks direct ICB response records; use RNA surrogates instead |
| Joint multimodal transformer / cross-attention | Too complex, no training data for joint pretraining in one week |
| Agent reasoning directly over raw embeddings | Hallucination-prone; use tool layer returning structured JSON instead |
| End-to-end WSI training | Requires large GPU cluster and weeks; use frozen foundational encoders |
| Training a brand-new TIL detector from scratch | Not needed for hackathon; bootstrap with TCIA TIL methodology/resource and treat output as proxy |
| Multi-cancer generalization | Increases data complexity; lock to TCGA-LUAD for demo |
| Full longitudinal EHR ingestion | TCGA clinical XML is the realistic substitute for this build |
| Literature-searching autonomous agent | Out of scope; guideline snippets are sufficient |
| Adverse event prediction (detailed) | Insufficient TCGA adverse event annotations; flag as V2 |

---

## 5. Key Model Choices (Reference)

| Modality | Component | Recommended Model | Notes |
|---|---|---|---|
| H&E | Tile encoder | **Google Path Foundation** | Open-weight HuggingFace model family for pathology tile embeddings |
| H&E | Alternatives | **UNI** (Harvard), **VirChow** (Paige) | Acceptable substitutes if Path Foundation access is constrained |
| H&E | Slide aggregation | **ABMIL** (attention pooling) | 2-layer attention head; lightweight; interpretable tile weights |
| H&E | Immune infiltration prior | **TCIA TIL-WSI-TCGA** + Saltz et al. 2018 | Use published computational-stain methodology as weak supervision / calibration source; links: [TCIA page](https://www.cancerimagingarchive.net/analysis-result/til-wsi-tcga/), [Data DOI](https://doi.org/10.7937/K9/TCIA.2018.Y75F9W1), [Paper DOI](https://doi.org/10.1016/j.celrep.2018.03.086) |
| EHR text | Note embedding | **Bio_ClinicalBERT** *(not implemented)* | Originally planned; actual implementation uses structured XML field extraction only |
| RNA | Surrogate labels | **TIDEpy** (local) | TIDE web server is retired; use local Python port |
| RNA | Deconvolution | **nnls / CIBERSORT-style** | Linear constrained deconvolution; fast; no GPU needed |
| Fusion | Primary model | **XGBoost / LightGBM** | Handles missing modalities natively via missingness flags |
| Agent | LLM | **Claude 3.5 Sonnet / GPT-4o** | Tool-call support; low hallucination rate on structured JSON input |
| Retrieval | Similarity index | **Structured 15-dim k-NN** *(replaces FAISS)* | FAISS was originally planned; actual implementation uses L2-normalized cosine similarity over a 15-dim z-scored feature vector (TME signals + staging + demographics) — see `apps/api/services/io_similar.py` |

---

**Outcome labels for training:** To train predictions from histology and transcriptomics embeddings using LUAD survival (and optional recurrence) labels, see [`../architecture/luad-outcome-labels-for-training.md`](../architecture/luad-outcome-labels-for-training.md) and scripts `scripts/build_outcome_labels_table.py` and `scripts/train_survival_from_embeddings.py`.

---

*Generated: 2026-03-03 | Disease: TCGA-LUAD | Cohort: ~50 matched cases (MVP), 475 full (V1)*
