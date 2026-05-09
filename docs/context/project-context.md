# YC AIxBio Hackathon — Context (Living)

Last updated: 2026-03-05

## 1) Product intent
Build a **tri-modal clinical decision-support demo** for LUAD that:
1. gives a **provisional immunotherapy-readiness score** from H&E + clinical context,
2. gives a **refined score** when RNA arrives,
3. explains the score with an LLM grounded in structured evidence,
4. shows similar historical patients.

## 2) Constraints carried from meeting context

- Dataset must be practical under hackathon time limits.
- Team converged on **TCGA-LUAD** as the operational dataset.
- No “agent over raw embeddings”; use tool-returned JSON evidence.
- Product/demo quality matters as much as model quality.
- Keep architecture modular: per-modality specialists + fusion + agent.

## 3) Confirmed data strategy

- **Pathology:** TCGA LUAD H&E SVS, tile embeddings + heatmaps
- **Transcriptomics:** STAR-counts TSV (TPM-based signatures)
- **Clinical/EHR-lite:** TCGA clinical XML + pathology report text

## 4) Feature scope from meetings + planning docs

### MVP (must ship)
- Pathology: immune infiltration proxy, tumor/stroma/necrosis fractions, heatmap
- Transcriptomics: CYT, 18-gene GEP proxy, TIDE (experimental/local)
- Clinical: stage + immunotherapy eligibility summary + survival baseline
- Fusion: responder score + provisional vs refined + modality attribution
- Agent: explanation + Q&A over tool outputs

### V1 (if time)
- Histologic subtype
- RNA deconvolution + pathway scores
- Similar patient retrieval + treatment ranking
- Better clinical narrative synthesis

### V2 (post-hackathon)
- Adverse event risk modeling
- Pathologic stage proxy from image-only branch
- Multi-cancer generalization

## 5) Team split signal (from synced memory)

> ⚠️ These are signals from early meetings. Confirm and update with real assignments in [`../execution/task-backlog.md`](../execution/task-backlog.md) § "Suggested owner split".

- Hanson: RNA plots + agent-input visualization
- Teammate A: agent mechanism
- Teammate B: EHR + spatial inference setup
- Teammate C: MLP/data processing planning

## 6) Truthfulness policy for demo

- Research-only prototype.
- Outputs are proxy scores/signatures, not clinical decisions.
- Surface uncertainty/QC/provenance in every endpoint.

## 7) UI priorities from YC BioxAI iMessage chat (read 2026-03-05)

- The team explicitly frames **architecture first, UI second in the same flow** ("top is architecture, bottom is UI").
- A visible **H&E heatmap feature is mandatory** for the demo flow.
- UI should combine **seq plots + H&E heatmap + model values/confidence** in one patient workspace.
- The agent should consume those outputs and support **interactive Q&A** (chat panel is core, not optional).
- Team intent is to get a **quick, integrated UI shell early**, then iterate model quality.
- Product expectation now includes: **display + upload + analysis run + chat interaction**.
