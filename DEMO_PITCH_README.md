# Demo Pitch README

## One-Line Positioning
Community-oncology decision-support copilot for early-line lung, breast, and colon cancer care: one-screen patient synthesis, immunotherapy-readiness context, and trial prioritization.

## Why This Matters
Oncology decisions are time-sensitive, but patient information is fragmented across biopsy notes, imaging, pathology, genomics, and treatment records. Community oncologists often need fast, high-confidence synthesis without easy access to subspecialists in every tumor type.

From physician consultation feedback:
- Genomics is often the strongest decision driver in lung, breast, and colon.
- Clinical timeline context (biopsy/surgery/chemo/radiation sequence) is essential.
- A single consolidated screen is more useful than deep image-heavy views during routine visits.

## Target Niche (Demo Scope)
Focus cancers:
1. Lung
2. Breast
3. Colon

Why these:
- High likelihood that biomarker/genomic context influences treatment strategy.
- Strong fit for immunotherapy and trial-prioritization decision support.

Not primary focus in demo:
- Cancer types where treatment is more one-path and less genomics-dependent in routine community workflows.

## Current Product Capabilities
1. Clinical summary + multimodal workspace
- Consolidates pathology, transcriptomics, and clinical context into one workspace.

2. IO responsiveness score
- Research proxy score for immunotherapy readiness.
- Hot/Warm/Cold TME classification from WSI; refined with RNA when available.
- Transparent component breakdown (GEP, CYT, TIDE, TIL, PD-L1).

3. Survival analysis (Cox + Kaplan-Meier)
- RNA-augmented Cox proportional hazards model predicting 1-yr, 2-yr, and 5-yr overall survival.
- Kaplan-Meier population reference curves for Low / Intermediate / High risk strata.
- Patient's predicted risk tier highlighted on the KM chart.
- Falls back to clinical-only Cox model when RNA is unavailable.

4. Trial prioritization
- Surfaces potential trial-fit context from available case evidence.

5. Similar-patient retrieval
- Multimodal 15-dim k-NN (TME signals + staging + demographics) over the full TCGA-LUAD cohort.
- No text embeddings — pure structured feature similarity.

6. Agent chat + literature grounding
- Lets clinicians ask patient-specific questions with grounded evidence context.

## Expansion Roadmap (Post-Demo)
1. Similar-patient retrieval
- Now: multimodal 15-dim k-NN similarity over TCGA-LUAD cohort (TME signals + staging + demographics).
- Next: external networks/registries and specialist-routing suggestions ("who has managed similar patients").

2. IO score
- Now: immunotherapy-readiness proxy.
- Next: treatment sequencing assistant that includes chemo/radiation/surgery context and prior treatment journey.

3. Trial prioritization
- Now: patient-level trial-fit cues.
- Next: site-aware ranking (availability, location, operational feasibility) and referral acceleration.

4. Agent
- Now: patient-context Q&A + literature grounding.
- Next: guideline-aware recommendations with clearer confidence and missing-data warnings.

5. Workflow integration
- Now: standalone demo UI.
- Next: EHR-native embedding (e.g., SMART on FHIR style integration), audit trail, and clinician-in-the-loop deployment model.

## Clinical Framing for the Demo
Use this framing repeatedly:
- Decision support, not autonomous treatment recommendation.
- Built for community oncology workflow speed and clarity.
- Focused on cancers where molecular context is most likely to change care.

## 60-Second Pitch Script
"Cancer care decisions are often delayed by fragmented data spread across multiple systems and specialists. We built a community-oncology copilot focused on lung, breast, and colon cancer that compresses key patient context into one decision-ready workspace. Clinicians can quickly review the treatment timeline, molecular context, immunotherapy-readiness signal, trial-prioritization options, and similar-case evidence in one place. The goal is not to replace oncologists, but to help them make faster, better-informed early-line decisions, especially in community settings where subspecialty access is limited."

## Suggested Demo Flow (2-3 minutes)
1. Open a patient case and show one-screen summary.
2. Highlight timeline + genomics/transcriptomics context.
3. Show IO readiness signal and explainability.
4. Show trial prioritization and "why" signals.
5. Show similar-patient retrieval + agent Q&A for evidence-based follow-up.
6. Close with roadmap: from demo decision support to integrated clinical workflow tooling.

## What Not to Overclaim
1. Do not claim autonomous regimen selection.
2. Do not claim universal all-cancer applicability.
3. Do not imply production clinical validation from hackathon data.

## Slide-Friendly Tagline Options
1. "From fragmented oncology charts to one decision-ready screen."
2. "Genomics-first community oncology copilot."
3. "Faster, clearer early-line treatment planning for lung, breast, and colon cancer."
