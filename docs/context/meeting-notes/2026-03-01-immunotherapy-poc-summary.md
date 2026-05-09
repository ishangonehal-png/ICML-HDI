# 03-01 Meeting: Immunotherapy Response Prediction POC with Multimodal EHR and H&E Embeddings

## Meeting Information
> Date: 2026-03-01 12:39:25
> Location: [Insert Location]
> Participants: [Speaker 1] [Speaker 2] [Speaker 3] [Speaker 4] [Speaker 5]
## Meeting Notes
- Topic Title: Project focus on immunotherapy response prediction
  - The team agreed to target immunotherapy response prediction.
  - The approach is a multimodal method combining EHR data with features derived from H&E pathology slides.
  - The goal is a proof-of-concept demonstrating multimodal reasoning for clinical prediction.
- Topic Title: Data modalities and embeddings plan (EHR and H&E)
  - EHR: Condense EHR data into embeddings and generate a parallel natural language representation of the same records.
  - H&E: Avoid processing raw gigapixel slides; use existing models to derive clinically interpretable values and embeddings.
  - Maintain separate embeddings per modality (no joint embedding) to enable flexible cross-modality reasoning.
  - Spatial transcriptomics/data was discussed but deemed unavailable/inappropriate for this scope.
- Topic Title: Model architecture and reasoning approach
  - Use a small model trained on embeddings for the prediction task.
  - Consider an “agent” that reasons over multimodal embeddings and natural language inputs, inspired by a bio reasoning paper (Ego/Devo2-like embeddings referenced).
  - Open questions remain on whether the agent can natively reason over numeric embeddings or requires additional training.
  - Preference to keep two separate models for modality processing, then reason over both sets of embeddings.
- Topic Title: Feasibility, scope, and POC strategy
  - The team believes a demo is achievable quickly (hours to a few days) if scope is contained.
  - For the POC, assume availability of both EHR and H&E-derived features to maximize the chance of a compelling demo.
  - Recognized limitations: existing H&E → clinical value models have modest performance (noted for ovarian and lung cancer) but are acceptable for a demo.
- Topic Title: UI and team split
  - Plan to split into two teams: front-end/UI and model/ML.
  - The UI is considered straightforward; multiple members can handle it.
- Topic Title: Proposal drafting and submission
  - Agreement to write and submit a short proposal by tonight.
  - Action to read and reference the bio reasoning paper before finalizing the proposal.
  - Intention to draft in a shared Google Document; one member will reach out to a friend regarding the opportunity/acceptance process.
  - Discussion on sponsorship/acceptance control was inconclusive; licensing and example sponsors were mentioned.
- Topic Title: Target outputs and evaluation signals
  - Possible outputs include survival time prediction, treatment sensitivity, staging/classification, and confidence scores.
  - Immunotherapy response remains the primary outcome of interest for the demo.
## Next Arrangements
- [ ] Draft and submit the proposal in the shared Google Document by tonight
- [ ] Read the bio reasoning paper referenced by Speaker 2 and extract applicable methods
- [ ] Decide on the method for reasoning over embeddings (agent vs. trained small model)
- [ ] Curate EHR datasets; generate embeddings and natural language representations
- [ ] Select an H&E model to produce clinically interpretable values and embeddings
- [ ] Split the team into front-end and model groups; assign owners
- [ ] Reach out to the friend/contact about program acceptance details
- [ ] Define the primary demo metric (e.g., immunotherapy response classification) and success criteria
## AI Suggestions
> AI Suggestions
> AI has identified the following issues that were not concluded in the meeting or lack clear action items; please pay attention:
> 1. Clarify the exact “bio reasoning” paper (title, method, code availability) and confirm whether it supports reasoning over numeric embeddings without additional training.
> 2. Determine data availability: specific EHR dataset, H&E sources, and whether de-identified samples are accessible for a rapid POC.
> 3. Specify the embedding models for EHR and H&E (model names, versions) and confirm licensing/usage constraints.
> 4. Finalize the model pipeline: how embeddings and natural language representations are combined, and what inference stack orchestrates them.
> 5. Define the evaluation protocol: target labels (immunotherapy response), metrics, baseline comparisons, and minimal dataset size for a meaningful demo.