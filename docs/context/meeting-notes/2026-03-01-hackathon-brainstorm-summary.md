# 03-01 Meeting: Hackathon Brainstorming, Clinical Prediction Agent, Data Strategy

> Date: 2026-03-01 11:08:54
> Location: [Insert Location]
> Participants: [Speaker 1] [Speaker 2] [Speaker 3] [Speaker 4]
## Meeting Notes
### Hackathon Project Brainstorming and Refinement
The team brainstormed project ideas for an upcoming hackathon, initially considering infrastructure, data visualization, drug discovery, and AI scientists. They quickly narrowed their focus to AI in drug discovery, deeming infrastructure too technical and data visualization too difficult for a novel approach. The discussion explored training a reasoning model on biological sequences, drug repurposing, and using an AI agent for spatial data analysis. However, concerns about data availability, particularly for protein-protein interaction (PPI) data, and the complexity of fine-tuning models steered the conversation toward a more defined clinical application. A key point of discussion was whether to target a research tool, which was seen as competitive, or a clinical application, which was viewed as having a clearer use case and a more direct path to a product, especially given a recent supportive FDA policy change. The team ultimately decided to focus on a clinical prediction application for the hackathon.
### Project Focus: Clinical Prediction Agent for Treatment Response
The team converged on the idea of building a clinical prediction agent to predict patient drug responses, particularly for selecting treatments in early-stage disease or identifying likely responders in clinical trials. The plan is to create a reasoning agent that integrates multiple data modalities, such as imaging data (histology), sequencing data, and Electronic Health Records (EHR), to predict patient outcomes. The agent would not be trained from scratch but would instead call existing, pre-trained open-source models and reason over their combined outputs to generate a prediction. A proposed workflow involves a doctor or researcher uploading patient data to a web application, which would then predict optimal drug choices or response likelihood.
### Data and Model Selection
The team identified a rich dataset, BEAT-AML, which contains single-cell sequencing, clinical notes, and patient outcomes, as a strong candidate. Another key dataset identified was "The Cancer Genome Atlas" (TCGA), which is ideal as it contains both H&E (histology) slide images and clinical metadata. For the models, the team plans to leverage existing open-source H&E models and an EHR model from Stanford ("500 TBS"). The small size of some datasets (e.g., 800 patients) was noted as a potential risk for overfitting but was considered acceptable for a proof-of-concept aimed at a product-focused hackathon.
### Productization and Hackathon Strategy
The team agreed that a pure model submission would be insufficient for the hackathon, which is product-focused and seen as a potential path to a YC interview. Therefore, the final deliverable will be a web application with a user interface (UI). The plan is to build the core model before the event and focus on developing the UI during the hackathon itself. For the application submission, the team agreed to draft a 2-3 sentence proposal outlining their plan to build a clinical prediction agent, with the submission to be completed by the end of the day. It was noted that a team member has a contact at "Origin" who might be able to assist with their application.
## Next Arrangements
- [ ] Prepare and submit the hackathon application proposal today.
- [ ] [Speaker 1] to research better definitions of the data for the proposal.
- [ ] [Speaker 3] to look at the "bioreason paper" sent by [Speaker 1].
- [ ] [Speaker 1] to look more into the biology of drug repurposing.
- [ ] [Speaker 1] to share the ARC proposal with the team.
- [ ] After submission, each team member will complete their own application via the email invitation.
- [ ] The team plans to start building the model before the hackathon and build the UI during the event.
- [ ] Decide on the specific data modalities and disease area to focus on.
- [ ] Finalize the selection of open-source models for H&E and EHR data.
## AI Suggestions
> AI has identified the following issues that were not concluded in the meeting or lack clear action items; please pay attention:
> 1. **Data Access and Feasibility:** The team identified the BEAT-AML dataset, which requires an application for access, but it is unclear if this process has been initiated. The challenge of acquiring and integrating suitable multi-modal datasets (genomics, radiology, clinical notes) within the hackathon's timeframe has not been fully resolved or planned for.
> 2. **Final Project Scope:** While leaning heavily toward a clinical application, the team has not definitively chosen a specific disease area to focus on for the prediction agent.
> 3. **Undefined Roles:** Specific roles and responsibilities for each team member in developing the model and UI for the hackathon have not been defined.