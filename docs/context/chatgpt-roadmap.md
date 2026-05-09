Here’s the honest roadmap: **ship a tri-modal responder-copilot demo, not a new multimodal foundation model.**
For next week, the only version that is both credible and buildable is:

**H&E + clinical context predicts an RNA-derived immunotherapy-readiness score early; transcriptomics refines the score when available; an LLM explains the result through fixed tools.**

That is much more aligned with the hackathon’s public framing around building an AI scientist / drug discovery / bio-data product, and it matches your own notes that product/UI matters and that “reasoning directly over embeddings” is the risky, unproven piece for a one-week sprint. ([LinkedIn][1])  

## The scope I would freeze tonight

**Pick one disease, ontn is:

* **Disease:** TCGA-LUAD pilot.
* **Clinical use case:** early **immunotherapy prioritization / responder enrichment**.
* **Primary deliverable:** a retrospective dashboard that outputs:

  1. provisional score from **H&E + clinical**,
  2. refined score when **RNA** is present,
  3. natural-language rationale,
  4. similar-patient retrieval.

Why LUAD? GDC already exposes clinical data, RNA-seq, and slide images, and the TCGA-LUAD project page lists roughly **518 RNA-seq cases** and **514 tissue-slide cases**, which is enough for a convincing retrospective proof of concept without cross-cancer wrangling. ([GDC Portal][2])

## Why not “true treatment response from all three modalities” next week

Because the **dataset bottleneck** is the real blocker, not modeling.

* **Beat AML** is attractive if you are willing to drop pathology: its public descriptions emphasize **genomic, RNA-seq, clinical, and ex vivo drug-sensitivity** data. That is great for response prediction, but it does not solve your H&E-first story. ([Cancer.gov][3])
* **TransNEO-Breast** is much closer to your dream dataset: matched histology, RNA-seq, and treatment response. But the omics data are routed through **EGA-controlled access**, which is a terrible dependency for a one-week build. ([PMC][4])

So the realistic move is: **use a cohort you can get immediately**, and use a **surrogate immunotherapy-response signal** rather than waiting for a perfect tri-modal response dataset.

## The most realistic prediction task

Use **RNA-derived immunotherapy readiness** as the target for the early model.

A good choice is **TIDE / T-cell-inflamed style immune-response proxy** computed from tumor RNA. The original TIDE work explicitly argues that **treatment-naive tumor transcriptomes** can be used to derive surrogate biomarkers of immune-checkpoint response, and it reports that those signatures can predict ICB response from pre-treatment profiles. Also relevant: there is already precedent that **H&E carries anti-PD-1 response signal** in melanoma and lung cancer. One operational warning: the old **TIDE web server is retired**, so use **TIDEpy** or a local implementation instead of building around the server. ([PMC][5])

That gives you a clean product story:

* **Before RNA returns:** H&E + clinical produce a **provisional responder score**.
* **After RNA returns:** transcriptomics **refines** and explains the score.
* The UI shows **what changed** and **why**.

That is actually a strong clinical narrative, because it mirrors how data often arrive in practice.

## What to build technically

### 1) Pathology branch

Use a **frozen pathology foundation encoder**.
The safest choice is **Prov-GigaPath**, because it is open-weight and its public repo already describes the recommended flow: tile the WSI, compute tile embeddings, then aggregate to a slide representation. There is also a quick notebook in the repo. If one teammate already knows **UNI** or **CONCH**, those are acceptable substitutes, but do not burn time comparing pathology FMs. ([GitHub][6])

Implementation shortcut:

* sample a fixed number of informative tiles per slide,
* mean-pool or attention-pool tile embeddings,
* cache everything offline.

Do **not** fine-tune the pathology model.

### 2) Clinical / “EHR-lite” branch

For next week, your “EHR” is realistically **structured TCGA clinical metadata**, not a full longitudinal hospital chart. TCGA clinical data were collected through standardized forms, and TCGA includes clinical information like demographics, diagnosis/treatment fields, and follow-up. If you want note-like text for the LLM, there is also a public **TCGA-Reports** dataset of machine-readable pathology reports designed for text-based AI work and combinable with TCGA sequencing/image data. ([NCI Genomic Data Commons][7])

For the model:

* use simple tabular features: age, sex, smoking, stage, etc.
* optionally generate a short structured synopsis for display/query.

If you really want a clinical-text embedding in the deck, **Bio_ClinicalBERT** is a fine lightweight option; its model card says it was initialized from BioBERT and trained on MIMIC notes. ([Hugging Face][8])

### 3) Transcriptomics branch

This is where most teams waste time.

For **bulk TCGA RNA-seq**, do **not** spend the week trying to shoehorn in **Geneformer** or **scGPT** just because they are sexy. Public docs for both describe them as **single-cell** foundation models. That makes them a mismatch for a bulk-RNA v0 unless one of you already has working code and preprocessing. ([GitHub][9])

The realistic v0 is:

* compute **immune/pathway signatures** from bulk RNA,
* compute **TIDE/T-cell-inflamed** score locally,
* use those values as:

  * target / teacher signal for the early model,
  * refinement evidence when RNA is available,
  * explanation features in the UI.

### 4) Fusion model

Keep this embarrassingly simple:

* pathology embedding
* clinical tabular vector
* optional transcriptomic score vector
* missingness flags

Then train:

* **logistic regression** baseline,
* **XGBoost** or **LightGBM** as main model,
* maybe a tiny **2-layer MLP** only if everything else already works.

No cross-attention. No joint pretraining. No “reasoning over raw embeddings.”

### 5) Reasoning layer

This should **not** be an agent interpreting dense vectors.

Build a thin tool layer:

* `get_patient_summary`
* `get_pathology_evidence`
* `get_transcriptomic_evidence`
* `get_model_score`
* `get_similar_cases`
* `compare_with_without_rna`

Each returns **structured JSON**.
Then the LLM writes the explanation from those tool outputs.

That gives you natural-language queries like:

* “Why is this patient likely to respond?”
* “Which slide regions drove the score?”
* “What transcriptomic programs changed the recommendation?”
* “How much lower is confidence without RNA?”
* “Show similar retrospective patients.”

This is the only realistic way to deliver a “multimodal reasoning layer” next week without hallucinating.

## How I would spend the 52 human-hours

### Builder 1 — Pathology (13h)

* 1h: cohort manifest + case-ID matching
* 5h: WSI loader, tissue mask, tile sampling
* 4h: Prov-GigaPath embedding + slide aggregation
* 3h: thumbnails / heatmaps / top tiles for demo

### Builder 2 — Clinical + transcriptomics (13h)

* 3h: clean TCGA clinical fields
* 3h: RNA preprocessing + TIDEpy / immune signatures
* 4h: train/val split + baselines
* 3h: ablations + SHAP/feature importance

### Builder 3 — Backend + fusion (13h)

* 4h: fusion model + nearest-neighbor retrieval
* 4h: Python API / inference layer
* 2h: evidence JSON schema + confidence handling
* 3h: integration / debugging

### Builder 4 — Frontend + demo (13h)

* 4h: Streamlit shell or minimal Next.js app
* 4h: patient dashboard
* 3h: NL query widget + result cards
* 2h: demo deck + backup screenshots / short video

## The build order for the week

**Day 1:**
Freeze disease, label, and UI wireframe. Decide what counts as success:

* one cohort,
* one label,
* one polished demo flow.

**Day 2:**
Clinical/RNA preprocessing + case alignment.
Start slide embedding jobs overnight.

**Day 3:**
Pathology-only and clinical-only baselines.
Get one patient page rendering end to end.

**Day 4:**
Pathology + clinical fusion model.
Add transcriptomic refinement and “with RNA / without RNA” comparison.

**Day 5:**
Natural-language layer, similar-patient retrieval, heatmaps.

**Day 6:**
Polish the demo around **3 preselected patients**.
Record a backup walkthrough.

**Day 7:**
Pitch only:

* problem,
* why data arrives in stages,
* provisional vs refined score,
* why this reduces trial-and-error.

## What to cut immediately

Cut these with zero regret:

* true adverse-event prediction
* multi-cancer generalization
* full EHR ingestion
* end-to-end WSI training
* joint multimodal transformer
* “agent reasons directly over embeddings”
* literature-searching autonomous agent

Your own meeting notes were already circling this conclusion: split model/UI, use pretrained pieces, and make the product story carry the demo.  

## The one-line version I’d pitch

**“We built an early-response copilot that estimates immunotherapy readiness from routine H&E and clinical context, then refines the recommendation when transcriptomics become available, with a transparent natural-language explanation of what changed.”**

Next step: turn this into a 1-page buu90-second demo script.

[1]: https://www.linkedin.com/posts/ankitvgupta_bio-x-ai-hackathon-activity-7433310752033386496-vGi3?utm_source=chatgpt.com "Ankit Gupta's Post - Bio x AI Hackathon"
[2]: https://portal.gdc.cancer.gov/?utm_source=chatgpt.com "GDC Data Portal Homepage"
[3]: https://www.cancer.gov/ccg/blog/2019/beataml?utm_source=chatgpt.com "Beat AML Functional Genomic Study - NCI"
[4]: https://pmc.ncbi.nlm.nih.gov/articles/PMC12704547/ "https://pmc.ncbi.nlm.nih.gov/articles/PMC12704547/"
[5]: https://pmc.ncbi.nlm.nih.gov/articles/PMC6487502/?utm_source=chatgpt.com "Signatures of T cell dysfunction and exclusion predict cancer ..."
[6]: https://github.com/prov-gigapath/prov-gigapath?utm_source=chatgpt.com "Prov-GigaPath: A whole-slide foundation model ..."
[7]: https://gdc.cancer.gov/resources-tcga-users/tcga-clinical-data-forms "https://gdc.cancer.gov/resources-tcga-users/tcga-clinical-data-forms"
[8]: https://huggingface.co/emilyalsentzer/Bio_ClinicalBERT?utm_source=chatgpt.com "emilyalsentzer/Bio_ClinicalBERT"
[9]: https://github.com/lcrawlab/Geneformer?utm_source=chatgpt.com "lcrawlab/Geneformer"


