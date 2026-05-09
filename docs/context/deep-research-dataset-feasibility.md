# Public tri-modal datasets for a one-week hackathon demo

## Executive summary

For a one-week hackathon tri-modal demo (H&E whole-slide images + bulk RNA-seq + clinical metadata) with no controlled-access data, the most realistic path is to build on **TCGA cohorts hosted in the GDC**, and **treat an RNA-derived “immunotherapy readiness” score as the label** you predict from (a) pathology embeddings + (b) a small set of clinical covariates. This aligns with your time constraints (≈52 person-hours) and reduces the risk of access delays from permissions while still delivering a credible clinical narrative. fileciteturn0file0L1-L25 fileciteturn0file1L1-L24

Among candidates, a single TCGA cancer cohort is the most “join-clean” option because TCGA barcodes are consistent across modalities, and H&E slide images are available as SVS files and downloadable via the GDC API / Data Transfer Tool. citeturn15view1turn15view2turn20search4 The TCGA program itself spans tens of thousands of specimens across 33 cancer types, enabling you to choose a cohort that is both immunotherapy-relevant and roughly ≤500 cases. citeturn0search5

**Top recommendation:** **TCGA-LUAD** (lung adenocarcinoma) via GDC, with a **deliberate “quick subset” of ~50 cases** for download + embedding during the hackathon (the full cohort is too large for end-to-end WSI processing under tight time). LUAD is immunotherapy-relevant, has hundreds of RNA-seq cases and many available WSIs, and there is strong precedent for creating matched WSI–RNA subsets in this cohort. citeturn0search2turn0search20

## Constraints and evaluation rubric

The hard constraints you specified map to three practical success conditions:

First, **no controlled-access dependencies**: you want to avoid dbGaP gating. The GDC distinguishes open vs controlled data; open access data can be downloaded without a token, while controlled access requires authorization through entity["organization","dbGaP","nih controlled-access system"]. citeturn5search4turn15view2 In addition, for any GDC data (open or controlled), users agree not to attempt re-identification; for open access data, the GDC itself places no additional restrictions beyond that. citeturn15view4

Second, **tri-modal joinability**: you need unambiguous patient/case identifiers. TCGA uses standardized “submitter_id” barcodes (e.g., `TCGA-XX-YYYY`) that appear in file names and metadata fields, and the GDC API explicitly supports retrieving file IDs and case metadata together (enabling deterministic joins). citeturn20search4turn20search7turn15view2

Third, **download + inference feasibility**: WSIs are the dominant bottleneck. WSIs are commonly hundreds of MB to multiple GB each, and are often discussed as “a few hundred MBs to a few GBs” or even “3–4 GB” per slide depending on scanning and compression. citeturn3search2turn3search14turn3search22 This means you should plan around **subsampling cases** and **subsampling tiles per WSI** rather than attempting full-cohort, full-tile computation.

## Candidate datasets and comparison

The highest-confidence options are TCGA cancer-type cohorts hosted in the GDC (official TCGA distribution), because they provide all three modalities with consistent identifiers and immediate open-access downloads for the relevant file types (WSI SVS, RNA quant TSV, clinical XML/JSON). citeturn15view1turn18search9turn20search4

The table below compares practical candidates for a hackathon demo.

| Candidate cohort (open-access path) | Approx matched scale (WSI + RNA + clinical) | Where to get it | Typical file sizes (WSI vs RNA vs clinical) | Join key quality | Primary risks for a 1-week demo |
|---|---:|---|---|---|---|
| **TCGA-LUAD** | RNA-seq cases reported ~518; matched WSI+expression subsets reported ~462 after exclusions | GDC portal/API + (optional) GCS mirror | WSI examples 1.29–1.55 GB; RNA “STAR - Counts” examples ~2.7–4.3 MB; clinical XML example ~47 KB | Excellent (TCGA barcode) | WSI download volume + tiling/embedding time dominate; need strict subsampling |
| **TCGA-SKCM** | RNA-seq and tissue slide cases reported ~469 each (near-ideal scale) | GDC portal/API | WSI example ~1.83–1.97 GB; RNA similar pipeline outputs (MB-level typical in GDC) | Excellent (TCGA barcode) | Metastatic/primary mixture; still WSI-heavy |
| **TCGA-BLCA** | RNA-seq cases reported ~406; tissue slide cases ~412 (overlap ≤406) | GDC portal/API | WSI examples ~1.55–2.59 GB; RNA expected MB-level | Excellent (TCGA barcode) | Smaller cohort; WSI sizes can be larger; still needs subsampling |
| **CPTAC-CCRCC** imaging-heavy option | Imaging subjects reported 233 (but RNA linkage can be nontrivial without controlled-access genomics) | entity["organization","Imaging Data Commons","nci imaging repository"] + TCIA/IDC-linked resources | Tissue slide images reported ~190 GB for the collection | Medium (CPTAC IDs; mapping can be tricky) | Genomics in GDC for CPTAC-3 frequently involves controlled-access; join/missingness risk is high for hackathon |
| **HTAN** (open metadata + open imaging, mixed assay access) | Unknown matched bulk RNA + WSI publicly open at case level (varies by atlas) | entity["organization","Human Tumor Atlas Network","nci cancer moonshot program"] portal + IDC + (often) controlled sequencing | Imaging is open in IDC; sequencing level 1–2 access-controlled; some processed data open | Variable | Bulk RNA availability and manifests can be uneven; atlas-specific complexity can sink a 1-week demo |

Key sources behind these comparisons: TCGA program scope citeturn0search5; GDC slide images downloadable as SVS via API citeturn15view1; LUAD case counts and matched-subset precedent citeturn0search2turn0search20; SKCM and BLCA case count snippets citeturn4search0turn4search4; WSI and RNA example file sizes from GDC file pages citeturn19search0turn18search5turn20search0; IDC “free/no access requests” positioning citeturn11search2turn11search31; HTAN access model citeturn11search0; CPTAC-CCRCC subject count and supporting-data framing citeturn7search8; TCIA wiki sizing/licensing snippet for CPTAC-CCRCC tissue slides citeturn7search0.

## Ranked recommendation

**Top pick: TCGA-LUAD (GDC), demo on a ~50-case subset.** LUAD has a large RNA-seq footprint (hundreds of cases) and abundant WSIs, and there is published precedent showing that after practical exclusions, on the order of ~462 LUAD cases can have both WSI and gene expression available for modeling (useful as a sanity check that a “tri-modal join” is feasible). citeturn0search2turn0search20 For a hackathon, you do not need to process all cases; downloading ~50 slides (≈1.3–1.6 GB each in typical examples) is already ~65–80 GB and is realistic on a standard connection while still enabling a compelling demo. citeturn19search0turn19search3

**Second pick: TCGA-SKCM (GDC), if you want the most immunotherapy-native story.** The SKCM cohort is strongly associated with immune checkpoint blockade narratives, and the project-level counts indicate ~469 cases with RNA-seq and ~469 with tissue slides, which is unusually “balanced” for tri-modal prototyping. citeturn4search0 A representative open-access SKCM slide is ~1.8–2.0 GB. citeturn19search1turn19search4

**Third pick: TCGA-BLCA (GDC), if you want a slightly smaller cohort (<~412 slide-available cases).** BLCA has ~406 RNA-seq cases and ~412 slide-available cases per project summaries, keeping you under the “~500 cases ideal” guideline while retaining immunotherapy relevance. citeturn4search4 Example BLCA SVS slide sizes commonly land in the ~1.5–2.6 GB range. citeturn19search2turn19search5

**Why not prioritize CPTAC/HTAN for this specific hackathon?** While entity["organization","Clinical Proteomic Tumor Analysis Consortium","nci proteogenomics program"] imaging collections exist and are substantial, CPTAC genomics in the GDC frequently involves controlled access via dbGaP, and mapping CPTAC slide filenames/IDs to omics can be more error-prone than TCGA barcode joins. citeturn1search12turn5search4turn7search8 HTAN has open metadata and open imaging in IDC, but assay files may be open or access-controlled depending on level and atlas, which tends to be a high-variance integration task for a one-week sprint. citeturn11search0turn11search26

## Minimal first-download manifest for the top pick

This section gives a “smallest viable” download plan that (1) proves tri-modal joins end-to-end and (2) keeps download and processing time bounded.

### Host URLs and download mechanics

TCGA slide images can be downloaded as SVS and are accessible via the GDC API. citeturn15view1 The GDC API’s `data` endpoint downloads files by UUID, and it can also generate a manifest for batch downloading using the Data Transfer Tool. citeturn15view2 The Data Transfer Tool (`gdc-client`) supports resuming interrupted downloads (partial files end with `.partial`). citeturn15view3

### One-slide, one-RNA, one-clinical “smoke test” (TCGA-LUAD)

Below are **real open-access example files** from TCGA-LUAD that you can use to validate tooling immediately.

- **WSI (SVS) example (open, 1.29 GB):** UUID `94ea82ba-89a7-42d1-a778-c4093b79c580` (file name begins `TCGA-62-A46O-01Z-00-DX1...svs`). citeturn19search0  
- **RNA expression example (open, 4.25 MB):** UUID `cc1174cd-f902-46f0-9e69-b285b2b1317c` (file name `...rna_seq.augmented_star_gene_counts.tsv`). citeturn18search5  
- **Clinical example (open, 47.03 kB BCR XML):** UUID `99d98029-ff9c-422a-9456-a6518a1be303` (file name `nationwidechildrens.org_clinical.<barcode>.xml`). citeturn20search0

Use the GDC `data` endpoint pattern (UUID substituted) per GDC documentation. citeturn15view2

```bash
# 1) Download one WSI (SVS)
curl -L -O -J "https://api.gdc.cancer.gov/data/94ea82ba-89a7-42d1-a778-c4093b79c580"

# 2) Download one RNA STAR-counts TSV
curl -L -O -J "https://api.gdc.cancer.gov/data/cc1174cd-f902-46f0-9e69-b285b2b1317c"

# 3) Download one clinical XML
curl -L -O -J "https://api.gdc.cancer.gov/data/99d98029-ff9c-422a-9456-a6518a1be303"
```

### Minimal “first real subset” for the demo

A practical hackathon subset is **~50 cases**:

- **WSI volume:** if you assume ~1.8 GB/slide (consistent with typical LUAD/SKCM/BLCA SVS examples on GDC file summaries), 50 slides ≈ 90 GB total. citeturn19search0turn19search3turn19search1  
- **RNA volume:** STAR-count gene expression quantification TSVs are MB-scale (often ~3–5 MB per file), so 50 RNA files are only a few hundred MB. citeturn18search0turn18search5turn18search1  
- **Clinical volume:** clinical BCR XML is tens of KB per case. citeturn20search0

At **100 Mbps** (≈12.5 MB/s), **90 GB is ~2.0 hours** of ideal transfer time, and real-world wall clock is typically longer due to overhead/retries; this is why the WSI subset must remain small. citeturn15view3

### “Exact query” path to produce your own manifest (recommended)

The official approach is to use a **GDC API search** (POST recommended for complex filters) and then request a manifest for the returned file set. The GDC docs show the POST pattern and list fields that can include `file_id`, `file_name`, and `cases.submitter_id` for join mapping. citeturn20search4turn15view2

Conceptually, you will run two manifests:

1) **Slide images**: `data_type = "Slide Image"`, `data_format = "SVS"`, `access = "open"`, `cases.project.project_id = "TCGA-LUAD"`.
2) **RNA**: `data_type = "Gene Expression Quantification"`, `analysis.workflow_type = "STAR - Counts"`, `data_format = "TSV"`, `access = "open"`, `cases.project.project_id = "TCGA-LUAD"`.

The `STAR - Counts` workflow is the GDC RNA-seq harmonization quantification pipeline and outputs Gene Expression Quantification TSVs. citeturn18search9turn15view2

(You’ll typically add a filter for primary tumor sample type as well; the GDC API supports retrieving sample metadata alongside files. citeturn20search4turn20search7)

## Preprocessing, surrogate labels, compute risks, and timeline

### Immunotherapy-readiness proxy labels you can compute from RNA

You asked specifically for an “RNA-derived immunotherapy-readiness proxy.” For an open-data hackathon, the cleanest approach is to compute one or more transcriptomic scores and treat them as *surrogate labels*:

A practical default is **TIDE** (Tumor Immune Dysfunction and Exclusion), computed from expression profiles and designed to model immune escape; a maintained Python implementation exists (TIDEpy). citeturn3search7 Note that the legacy TIDE web server indicates it is retired and points users to a successor (“CIDE”), so local computation is preferable for reliability. citeturn3search3

Two additional common “readiness-like” signatures are easy to compute directly from RNA:

- **18-gene T cell–inflamed gene expression profile (GEP)** described as predictive of pembrolizumab response across tumor types. citeturn5search14turn5search6  
- **CYT (cytolytic activity)** defined as the geometric mean (log-average) of **GZMA** and **PRF1** expression per sample. citeturn5search11turn5search30  

These can be combined into a demo output such as: “Predicted TIDE (lower is better), T-cell–inflamed GEP (higher is better), CYT (higher suggests immune activity).”

### WSI preprocessing and embedding choices under hackathon constraints

TCGA WSIs are distributed as SVS (Aperio-derived TIFF variant), historically noted as the TCGA slide format. citeturn3search26turn15view1 Because WSIs are multi-GB, the bottleneck is (a) downloading and (b) extracting tiles.

If you use Prov-GigaPath-style embeddings, its published design is based on serializing a slide into **256×256 tiles**, embedding tiles, then aggregating to slide-level representations. citeturn3search0turn14view2 The reference implementation also notes that model access is gated through entity["company","Hugging Face","model hosting platform"] terms and requires an access token. citeturn14view2

For a one-week demo, the compute-risk-managed approach is:

- **Use only the tile encoder** (not the slide-level LongNet encoder) and mean-pool / attention-pool over a capped number of tissue tiles (e.g., 512–2048 per WSI). The Prov-GigaPath repo explicitly supports tile-level inference and recommends tiling first, then embedding tiles. citeturn14view2  
- **Cap the number of tiles per slide** to keep inference bounded. Even in benchmarks on modern GPUs, tile throughput varies widely across foundation models (tens to thousands of tiles per second on an H100, depending on architecture). citeturn14view0turn21view1  
- **Treat slide download + tile extraction as the critical path**, because WSI sizes are generally GB-scale. citeturn3search2turn3search22turn19search0  

### Mermaid timeline for the chosen dataset

Below is a timeline that respects “what blocks what” for a tri-modal demo on TCGA-LUAD, emphasizing the dominant bottlenecks (WSI download and WSI tiling/embedding).

```mermaid
gantt
dateFormat  YYYY-MM-DD
title TCGA-LUAD tri-modal demo pipeline (1-week hackathon)
excludes    weekends

section Data acquisition (blocking)
Download 50 LUAD WSIs (SVS)            :a1, 2026-03-02, 1d
Download RNA STAR-count TSVs + clinical:after a1, 2026-03-03, 0.3d
Build join table (case barcode ↔ file_id) :after a1, 2026-03-03, 0.3d

section Preprocessing (WSI is bottleneck)
WSI tissue detection + tiling (cap tiles) :b1, after a1, 2026-03-03, 1d
RNA normalization + signature labels (TIDE/GEP/CYT) :b2, 2026-03-03, 0.6d

section Embeddings and modeling
Tile-encoder embeddings (cache per WSI)   :c1, after b1, 2026-03-04, 1d
Train simple fusion model (clinical + WSI → RNA proxy) :c2, after b2, 2026-03-05, 0.7d

section Demo integration
Build clinician-style report + explanations :d1, 2026-03-05, 1d
End-to-end “one patient” inference latency tuning :d2, after c1, 2026-03-06, 0.5d
Final polish + contingency buffer          :d3, 2026-03-06, 1d
```

### Risk assessment and mitigations

The key risk categories are predictable:

**Data alignment risk (low for TCGA, higher elsewhere).** TCGA barcodes are directly retrievable alongside file IDs from the GDC API, and GDC docs explicitly support queries that return both file and case metadata for deterministic joins. citeturn20search4turn20search7 This is materially simpler than CPTAC/HTAN-style multi-repository mapping under hackathon time.

**Access delays (low if you stay strictly open-access).** GDC open-access data does not require a token, and the Data Analysis Policies clarify that the main restriction is no re-identification attempts. citeturn15view4 If you drift into controlled-access modalities (common in CPTAC genomics), you will hit dbGaP delays. citeturn5search4turn1search12

**Download time (high, dominated by WSIs).** Real file pages show LUAD/SKCM/BLCA SVS slides are often ~1–3 GB each, and general digital pathology references treat WSIs as GB-scale objects, which means cohort-level downloads can quickly become hundreds of GB. citeturn19search0turn19search1turn3search22 The mitigation is to keep a curated subset (~50 cases) and cache embeddings.

**Inference time (moderate, manageable with tile caps).** Prov-GigaPath-style workflows are tile-based, and tile throughput can vary but is measurable and often high for tile encoders on modern GPUs; limiting tile count is the main control knob. citeturn3search0turn14view2turn21view1