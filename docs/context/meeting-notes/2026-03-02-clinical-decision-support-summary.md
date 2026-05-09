# 03-02 Meeting: AI Clinical Decision Support Tool for Hackathon

> **Date:** 2026-03-02 21:13:11
> **Location:** [Insert Location]
> **Participants:** [Speaker 1] [Speaker 2] [Speaker 3] [Speaker 4] [Speaker 5]
## Meeting Notes
### Project Concept and Scope Definition
- The team's core project idea is to build an AI-powered clinical decision support tool for a hackathon. The system aims to integrate multiple patient data types to assist clinicians.
- The project evolved from an initial concept of an "immunotherapy readiness score" to a broader tool that generates a pathology report from multimodal data, and finally to a suite of predictive models overseen by a central reasoning agent.
- A key product value identified is the integration of sequencing data (transcriptomics) with imaging data (H&E slides) and clinical/EHR data.
- The project was framed as "Bio ML" and an "AI-powered clinical decision support system." Despite concerns that it was more clinical than research-focused, the team decided to proceed since the proposal was accepted for the hackathon.
- The hackathon strategy is to demonstrate a compelling vision and technical prototype, not a fully functional or highly accurate product. A minimally functional framework can be used to showcase a larger vision.
### Data Source Identification and Strategy
- The project requires a dataset combining three data types: transcriptome (RNA-seq), H&E slides (spatial), and EHR/clinical data with outcome labels.
- Finding a single, publicly available dataset with all three matched components was identified as a major challenge.
- The Cancer Genome Atlas (TCGA), specifically the LUAD (Lung Adenocarcinoma) project, was identified as the most promising data source. It contains whole slide images, transcriptomics, and clinical labels (e.g., vital status, days to progression).
- The team clarified that TCGA's "pathology reports" contain crucial text-based tumor information that can serve as a proxy for EHR data, resolving initial confusion.
- The MIMIC EHR dataset was also mentioned as a potential source for a separate EHR model, but access needs to be requested.
### Technical Architecture and Model Strategy
- The proposed architecture involves an agent-based system. A central agent will reason over the outputs from various models to provide insights to a clinician.
- The plan is to build multiple Multi-Layer Perceptrons (MLPs), each trained on a specific data modality (e.g., transcriptomics, imaging) to predict different clinical outcomes (e.g., disease response, vital status).
- The outputs from these MLPs will then be fed into the central agent.
- The agent could be enhanced to query external bioinformatic databases or retrieve medical literature for additional context.
- The team discussed leveraging existing open-source models (e.g., "MedSeg-Lip", "Titan", "Uni", "VirChow") to avoid building everything from scratch, prioritizing models with fast inference times for the hackathon.
- A significant technical challenge identified is translating model embeddings, particularly from spatial (H&E) and transcriptome data, into coherent, natural language for reports or a queryable interface (RAG).
### User Interface and Output
- The system's output will be a report and a dashboard displaying predicted values, such as the likelihood of response to immunotherapy.
- A proposed user interface (UI) would display an attention map or heatmap on the H&E slide image alongside the generated natural language description (pathology report).
- The team also debated the feasibility of a "chatbot" feature to allow clinicians to query the data, potentially built using a RAG framework with a knowledge base for a specific cancer type.
## Next Arrangements
- [ ] Create a shared drive folder for brainstorming features.
- [ ] Verify that a suitable dataset with transcriptome, H&E slides, and clinical outcome data exists and is accessible. Finalize the specific dataset from TCGA.
- [ ] Sketch out the architecture/flowchart for the data flow and agent framework.
- [ ] [Speaker 3] to sketch out a UI framework for the project.
- [ ] [Speaker 1] to research existing open-source models that can be used.
- [ ] Determine the specific clinical outcomes (labels) from the dataset (e.g., vital status, patient outcomes) to use for training the MLP models.
- [ ] Define a plan for processing and using the pathology reports from the TCGA dataset.
- [ ] Determine how to decode model output embeddings into natural language.
- [ ] The team will meet again to refine the project diagram and divide the work.
- [ ] Update Eshan on the project plan.
## AI Suggestions
> **AI Suggestions**
> AI has identified the following issues that were not concluded in the meeting or lack clear action items; please pay attention:
> 1. **Data Availability is a Critical Blocker:** The team has not confirmed a single, accessible dataset containing all three required data types (transcriptome, H&E slides, and matched clinical/EHR outcomes). While TCGA is the primary candidate, a concrete plan for data extraction, integration, and processing is still needed.
> 2. **Unsolved Technical Challenge:** The central problem of how to convert model embeddings from multimodal data into a coherent natural language pathology report or queryable insights remains unsolved. No clear technical solution was decided upon.
> 3. **Undefined Training Labels:** The team has not finalized the specific labels from the chosen dataset (e.g., TCGA's LUAD) that will be used to train the predictive models. This decision is crucial for starting any modeling work.
> 4. **Vague Integration Plan for External Models:** While the use of open-source models (especially for EHR data) was discussed, the team has not identified specific models or defined how they would be integrated into the central agent architecture.