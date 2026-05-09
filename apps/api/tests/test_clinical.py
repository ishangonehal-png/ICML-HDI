from __future__ import annotations

import json
import textwrap

import httpx
import pytest

from models import AnalysisJob, Case, File, ModalityResult
from services.clinical import clear_clinical_trial_match_cache

CASE_ID = "TCGA-05-4244"


@pytest.fixture(autouse=True)
def clear_clinical_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "CLINICAL_ARTIFACT_DIR",
        "CLINICAL_XML_DIR",
        "CLINICAL_REPORTS_DIR",
        "CLINICAL_TRIAL_MATCH_CACHE_TTL_SECONDS",
        "CLINICAL_PATH_REPORT_FIELDS_DIR",
        "CLINICAL_SURVIVAL_MODEL_DIR",
    ):
        monkeypatch.delenv(key, raising=False)

    clear_clinical_trial_match_cache()


def _insert_clinical_modality_result(db, *, case_id: str, payload: dict) -> None:
    case = Case(case_id=case_id, cohort="mvp50", record_metadata={})
    job = AnalysisJob(
        case_id=case_id,
        status="completed",
        requested_modalities=["clinical"],
        record_metadata={"source": "pytest"},
    )

    db.add(case)
    db.add(job)
    db.flush()

    db.add(
        ModalityResult(
            job_id=job.id,
            case_id=case_id,
            modality="clinical",
            payload=payload,
            result_metadata={"source": "pytest"},
        )
    )
    db.commit()


class _FakeHttpxResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://clinicaltrials.gov/api/v2/studies")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("bad status", request=request, response=response)

    def json(self) -> dict:
        return self._payload


class _PickleableFakeCoxModel:
    def __init__(self) -> None:
        import pandas as pd

        self.params_ = pd.Series(
            [0.1, 0.1, 0.1, 0.1, 0.1],
            index=[
                "stage_ordinal",
                "age_at_diagnosis",
                "smoking_ordinal",
                "is_female",
                "pack_years",
            ],
        )

    def predict_survival_function(self, _patient_df):
        import pandas as pd

        return pd.DataFrame(
            {0: [0.90, 0.80, 0.60]},
            index=[12.0, 24.0, 60.0],
        )

    def predict_median(self, _patient_df):
        import pandas as pd

        return pd.Series([38.0])

    def predict_partial_hazard(self, _patient_df):
        import pandas as pd

        return pd.Series([0.7])


def test_clinical_endpoints_return_typed_unavailable_when_no_sources(client) -> None:
    summary = client.get(f"/v1/clinical/{CASE_ID}/patient-summary")
    eligibility = client.get(f"/v1/clinical/{CASE_ID}/eligibility")
    survival = client.get(f"/v1/clinical/{CASE_ID}/survival-baseline")

    assert summary.status_code == 200
    assert eligibility.status_code == 200
    assert survival.status_code == 200

    summary_payload = summary.json()
    assert summary_payload["case_id"] == CASE_ID
    assert summary_payload["available"] is False
    assert summary_payload["data_source"] == "unavailable"
    assert summary_payload["unavailable_reason"] is not None
    assert summary_payload["provenance"]["data_source"] == "unavailable"

    eligibility_payload = eligibility.json()
    assert eligibility_payload["available"] is False
    assert eligibility_payload["eligible_trials"] is None
    assert eligibility_payload["eligibility_label"] is None
    assert eligibility_payload["data_source"] == "unavailable"
    assert eligibility_payload["unavailable_reason"] is not None

    survival_payload = survival.json()
    assert survival_payload["available"] is False
    assert survival_payload["risk_group"] is None
    assert survival_payload["baseline_months"] is None
    assert survival_payload["confidence_interval"] is None
    assert survival_payload["data_source"] == "unavailable"
    assert survival_payload["unavailable_reason"] is not None


def test_clinical_artifact_payload_is_preferred_and_exposes_provenance(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    client,
) -> None:
    artifact_payload = {
        "patient_summary": {
            "stage": "Stage IIIB",
            "smoking_status": "Current smoker",
            "age_at_diagnosis": 67,
            "diagnosis": "Lung adenocarcinoma",
            "report_highlights": [
                "Clinical artifact summary line one.",
                "Clinical artifact summary line two.",
            ],
        },
        "eligibility": {
            "eligible_trials": 2,
            "eligibility_label": "eligible",
            "rationale": ["Precomputed eligibility rationale."],
            "criteria": [
                {
                    "criterion": "advanced_stage",
                    "status": "met",
                    "observed_value": "Stage IIIB",
                    "rationale": "Precomputed from curated artifact.",
                }
            ],
        },
        "survival_baseline": {
            "risk_group": "intermediate",
            "baseline_months": 24,
            "confidence_interval": [18, 30],
            "prognostic_factors": ["Precomputed from curated artifact."],
        },
    }

    (tmp_path / f"{CASE_ID}.json").write_text(json.dumps(artifact_payload), encoding="utf-8")
    monkeypatch.setenv("CLINICAL_ARTIFACT_DIR", str(tmp_path))

    summary = client.get(f"/v1/clinical/{CASE_ID}/patient-summary").json()
    eligibility = client.get(f"/v1/clinical/{CASE_ID}/eligibility").json()
    survival = client.get(f"/v1/clinical/{CASE_ID}/survival-baseline").json()

    assert summary["available"] is True
    assert summary["data_source"] == "artifact"
    assert summary["stage"] == "Stage IIIB"
    assert summary["smoking_status"] == "Current smoker"
    assert summary["age_at_diagnosis"] == 67
    assert summary["diagnosis"] == "Lung adenocarcinoma"
    assert summary["report_highlights"] == [
        "Clinical artifact summary line one.",
        "Clinical artifact summary line two.",
    ]
    assert summary["provenance"]["source_paths"] == [f"{tmp_path}/{CASE_ID}.json"]

    assert eligibility["available"] is True
    assert eligibility["data_source"] == "artifact"
    assert eligibility["eligible_trials"] == 2
    assert eligibility["eligibility_label"] == "eligible"
    assert eligibility["criteria"][0]["criterion"] == "advanced_stage"

    assert survival["available"] is True
    assert survival["data_source"] == "artifact"
    assert survival["risk_group"] == "intermediate"
    assert survival["baseline_months"] == 24
    assert survival["confidence_interval"] == [18, 30]


def test_clinical_artifact_is_enriched_by_xml_when_summary_fields_are_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    client,
) -> None:
    artifact_dir = tmp_path / "artifacts"
    xml_dir = tmp_path / "xml"
    artifact_dir.mkdir(parents=True)
    xml_dir.mkdir(parents=True)

    (artifact_dir / f"{CASE_ID}.json").write_text(
        json.dumps(
            {
                "patient_summary": {
                    "stage": None,
                    "smoking_status": "current smoker",
                    "age_at_diagnosis": 67,
                    "diagnosis": "lung adenocarcinoma",
                }
            }
        ),
        encoding="utf-8",
    )

    (xml_dir / f"nationwidechildrens.org_clinical.{CASE_ID}.xml").write_text(
        textwrap.dedent(
            """
            <clinical_patient>
              <tumor_stage>stage iia</tumor_stage>
              <days_to_last_followup>700</days_to_last_followup>
              <gender>male</gender>
              <vital_status>alive</vital_status>
            </clinical_patient>
            """
        ).strip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("CLINICAL_ARTIFACT_DIR", str(artifact_dir))
    monkeypatch.setenv("CLINICAL_XML_DIR", str(xml_dir))

    summary = client.get(f"/v1/clinical/{CASE_ID}/patient-summary").json()
    survival = client.get(f"/v1/clinical/{CASE_ID}/survival-baseline").json()

    assert summary["available"] is True
    assert summary["data_source"] == "artifact"
    # Stage is missing in artifact but available in XML.
    assert summary["stage"] == "Stage IIA"
    assert summary["smoking_status"] == "Current smoker"
    assert summary["vital_status"] == "Alive"
    assert any("Enriched missing clinical fields" in note for note in summary["provenance"]["notes"])

    # Survival should no longer be unavailable once XML stage/follow-up can enrich artifact.
    assert survival["available"] is True
    assert survival["data_source"] == "artifact"
    assert survival["risk_group"] in {"low", "intermediate", "high"}
    assert survival["baseline_months"] is not None


def test_clinical_modality_result_fallback_when_artifact_missing(db, client) -> None:
    payload = {
        "patient_summary": {
            "stage": "stage iiia",
            "smoking_status": "former smoker",
            "age_at_diagnosis": 65,
            "diagnosis": "lung adenocarcinoma",
        }
    }
    _insert_clinical_modality_result(db, case_id=CASE_ID, payload=payload)

    summary = client.get(f"/v1/clinical/{CASE_ID}/patient-summary").json()
    eligibility = client.get(f"/v1/clinical/{CASE_ID}/eligibility").json()

    assert summary["available"] is True
    assert summary["data_source"] == "modality_result"
    assert summary["stage"] == "Stage IIIA"
    assert summary["smoking_status"] == "Former smoker"
    assert summary["diagnosis"] == "Lung adenocarcinoma"

    assert eligibility["available"] is True
    assert eligibility["data_source"] == "modality_result"
    assert eligibility["eligibility_label"] == "eligible"
    assert eligibility["eligible_trials"] == 2


def test_clinical_xml_and_report_text_are_parsed_when_available(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    client,
) -> None:
    xml_dir = tmp_path / "xml"
    report_dir = tmp_path / "reports"
    xml_dir.mkdir(parents=True)
    report_dir.mkdir(parents=True)

    xml_path = xml_dir / f"nationwidechildrens.org_clinical.{CASE_ID}.xml"
    xml_path.write_text(
        textwrap.dedent(
            """
            <clinical_patient>
              <tumor_stage>stage iia</tumor_stage>
              <tobacco_smoking_status>former smoker</tobacco_smoking_status>
              <age_at_initial_pathologic_diagnosis>66</age_at_initial_pathologic_diagnosis>
              <primary_diagnosis>lung adenocarcinoma</primary_diagnosis>
              <gender>male</gender>
              <vital_status>alive</vital_status>
              <days_to_last_followup>700</days_to_last_followup>
            </clinical_patient>
            """
        ).strip(),
        encoding="utf-8",
    )

    report_path = report_dir / f"{CASE_ID}.txt"
    report_path.write_text(
        textwrap.dedent(
            """
            Lung adenocarcinoma noted in pathology report.
            Stage IIA disease with nodal involvement.
            ECOG 1 at intake.
            Former smoker, quit 8 years prior.
            """
        ).strip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("CLINICAL_XML_DIR", str(xml_dir))
    monkeypatch.setenv("CLINICAL_REPORTS_DIR", str(report_dir))

    summary = client.get(f"/v1/clinical/{CASE_ID}/patient-summary").json()
    eligibility = client.get(f"/v1/clinical/{CASE_ID}/eligibility").json()
    survival = client.get(f"/v1/clinical/{CASE_ID}/survival-baseline").json()

    assert summary["available"] is True
    assert summary["data_source"] == "clinical_xml"
    assert summary["stage"] == "Stage IIA"
    assert summary["smoking_status"] == "Former smoker"
    assert summary["age_at_diagnosis"] == 66
    assert summary["diagnosis"] == "Lung adenocarcinoma"
    assert summary["sex"] == "Male"
    assert summary["vital_status"] == "Alive"
    assert summary["report_highlights"]

    assert eligibility["available"] is True
    assert eligibility["eligibility_label"] == "eligible"
    assert eligibility["eligible_trials"] == 2
    assert len(eligibility["criteria"]) == 4

    assert survival["available"] is True
    assert survival["risk_group"] == "intermediate"
    assert survival["baseline_months"] == 36
    assert survival["confidence_interval"] == [29, 43]


def test_clinical_case_metadata_fallback(db, client) -> None:
    db.add(
        Case(
            case_id=CASE_ID,
            cohort="mvp50",
            record_metadata={
                "stage": "stage ib",
                "smoking_status": "never smoker",
                "age_at_diagnosis": 59,
                "diagnosis": "lung adenocarcinoma",
            },
        )
    )
    db.add(
        File(
            case_id=CASE_ID,
            upload_session_id=None,
            gdc_file_id=None,
            file_name="clinical_patient.txt",
            file_type="Clinical Supplement",
            storage_uri="s3://bucket/clinical_patient.txt",
            checksum=None,
            record_metadata={
                "report_highlights": ["Case metadata highlight line."],
                "ecog_score": 2,
            },
        )
    )
    db.commit()

    summary = client.get(f"/v1/clinical/{CASE_ID}/patient-summary").json()
    eligibility = client.get(f"/v1/clinical/{CASE_ID}/eligibility").json()

    assert summary["available"] is True
    assert summary["data_source"] == "case_metadata"
    assert summary["stage"] == "Stage IB"
    assert summary["smoking_status"] == "Never smoker"
    assert summary["report_highlights"] == ["Case metadata highlight line."]
    assert summary["provenance"]["source_records"]

    assert eligibility["available"] is True
    assert eligibility["eligibility_label"] == "ineligible"
    assert eligibility["eligible_trials"] == 0


def test_survival_endpoint_returns_unavailable_when_model_dir_not_configured(client) -> None:
    response = client.get(f"/v1/clinical/{CASE_ID}/survival")
    assert response.status_code == 200
    payload = response.json()
    assert payload["case_id"] == CASE_ID
    assert payload["available"] is False
    assert payload["survival_prob_1yr"] is None
    assert payload["km_strata"] == []
    assert payload["unavailable_reason"] is not None


def test_survival_endpoint_returns_unavailable_when_model_artifacts_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    client,
) -> None:
    monkeypatch.setenv("CLINICAL_SURVIVAL_MODEL_DIR", str(tmp_path))
    response = client.get(f"/v1/clinical/{CASE_ID}/survival")
    assert response.status_code == 200
    payload = response.json()
    assert payload["available"] is False
    assert "artifacts not found" in payload["unavailable_reason"].lower()


def test_survival_endpoint_serves_km_strata_when_model_present(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    client,
) -> None:
    import pickle

    cox_path = tmp_path / "cox_model.pkl"
    with cox_path.open("wb") as fh:
        pickle.dump(_PickleableFakeCoxModel(), fh)

    km_data = {
        "high": {
            "time_points": [0.0, 12.0, 24.0, 60.0],
            "survival_rates": [1.0, 0.90, 0.80, 0.60],
            "n_at_risk": [50, 45, 40, 20],
            "n_events": 12,
            "n_total": 50,
            "median_survival_months": 48.0,
        },
        "low": {
            "time_points": [0.0, 12.0, 24.0],
            "survival_rates": [1.0, 0.60, 0.35],
            "n_at_risk": [50, 38, 22],
            "n_events": 32,
            "n_total": 50,
            "median_survival_months": 18.0,
        },
    }
    (tmp_path / "km_strata.json").write_text(json.dumps(km_data), encoding="utf-8")
    (tmp_path / "cohort_stats.json").write_text(
        json.dumps({"concordance_index": 0.65}), encoding="utf-8"
    )
    monkeypatch.setenv("CLINICAL_SURVIVAL_MODEL_DIR", str(tmp_path))

    # Need some clinical data so Cox patient row can be built
    import textwrap

    xml_dir = tmp_path / "xml"
    xml_dir.mkdir()
    (xml_dir / f"{CASE_ID}.xml").write_text(
        textwrap.dedent(
            """
            <clinical_patient>
              <tumor_stage>stage iiia</tumor_stage>
              <age_at_initial_pathologic_diagnosis>65</age_at_initial_pathologic_diagnosis>
              <tobacco_smoking_status>current smoker</tobacco_smoking_status>
              <gender>male</gender>
              <vital_status>alive</vital_status>
              <days_to_last_followup>900</days_to_last_followup>
            </clinical_patient>
            """
        ).strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("CLINICAL_XML_DIR", str(xml_dir))

    response = client.get(f"/v1/clinical/{CASE_ID}/survival")
    assert response.status_code == 200
    payload = response.json()
    assert payload["available"] is True
    assert payload["model_version"] == "cox-ph-clinical-v1"
    assert payload["concordance_index"] == pytest.approx(0.65)
    assert len(payload["km_strata"]) == 2
    labels = {s["label"] for s in payload["km_strata"]}
    assert labels == {"high", "low"}
    assert payload["survival_prob_1yr"] == pytest.approx(0.90)
    assert payload["survival_prob_2yr"] == pytest.approx(0.80)
    assert payload["survival_prob_5yr"] == pytest.approx(0.60)
    assert payload["patient_score_tier"] == "high"
    assert payload["median_survival_months"] == pytest.approx(38.0)


def test_enriched_xml_fields_exposed_in_patient_summary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    client,
) -> None:
    xml_dir = tmp_path / "xml"
    xml_dir.mkdir()
    xml_path = xml_dir / f"{CASE_ID}.xml"
    xml_path.write_text(
        textwrap.dedent(
            """
            <clinical_patient>
              <tumor_stage>stage iia</tumor_stage>
              <tobacco_smoking_status>current smoker</tobacco_smoking_status>
              <age_at_initial_pathologic_diagnosis>60</age_at_initial_pathologic_diagnosis>
              <primary_diagnosis>lung adenocarcinoma</primary_diagnosis>
              <gender>female</gender>
              <vital_status>alive</vital_status>
              <days_to_last_followup>500</days_to_last_followup>
              <number_pack_years_smoked>25</number_pack_years_smoked>
              <pathologic_t>T2a</pathologic_t>
              <pathologic_n>N1</pathologic_n>
              <pathologic_m>M0</pathologic_m>
              <histological_type>Lung Adenocarcinoma- Acinar</histological_type>
            </clinical_patient>
            """
        ).strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("CLINICAL_XML_DIR", str(xml_dir))

    summary = client.get(f"/v1/clinical/{CASE_ID}/patient-summary").json()

    assert summary["available"] is True
    assert summary["pack_years"] == pytest.approx(25.0)
    assert summary["tnm_t"] == "T2a"
    assert summary["tnm_n"] == "N1"
    assert summary["tnm_m"] == "M0"
    assert summary["histologic_subtype"] == "acinar"


def test_path_report_fields_loaded_from_cache(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    client,
) -> None:
    xml_dir = tmp_path / "xml"
    xml_dir.mkdir()
    (xml_dir / f"{CASE_ID}.xml").write_text(
        textwrap.dedent(
            """
            <clinical_patient>
              <tumor_stage>stage iib</tumor_stage>
              <age_at_initial_pathologic_diagnosis>63</age_at_initial_pathologic_diagnosis>
              <gender>female</gender>
              <vital_status>alive</vital_status>
              <days_to_last_followup>400</days_to_last_followup>
            </clinical_patient>
            """
        ).strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("CLINICAL_XML_DIR", str(xml_dir))

    cache_dir = tmp_path / "path_report_fields"
    cache_dir.mkdir()
    cache_data = {
        "grade": "moderately differentiated",
        "margins": "negative",
        "lymph_nodes_positive": 2,
        "lymph_nodes_total": 18,
        "lvi": "absent",
        "tumor_size_cm": 3.2,
        "histologic_pattern": "acinar predominant",
        "ihc_pdl1_tps": None,
        "til_comment": None,
        "raw_highlights": ["Moderately differentiated adenocarcinoma."],
    }
    (cache_dir / f"{CASE_ID}.json").write_text(json.dumps(cache_data), encoding="utf-8")
    monkeypatch.setenv("CLINICAL_PATH_REPORT_FIELDS_DIR", str(cache_dir))

    summary = client.get(f"/v1/clinical/{CASE_ID}/patient-summary").json()

    assert summary["available"] is True
    assert summary["path_report_fields"] is not None
    prf = summary["path_report_fields"]
    assert prf["grade"] == "moderately differentiated"
    assert prf["margins"] == "negative"
    assert prf["lymph_nodes_positive"] == 2
    assert prf["lymph_nodes_total"] == 18
    assert prf["lvi"] == "absent"
    assert prf["tumor_size_cm"] == pytest.approx(3.2)


def test_clinical_summary_available_but_rules_unavailable_when_only_diagnosis_present(db, client) -> None:
    db.add(
        Case(
            case_id=CASE_ID,
            cohort="mvp50",
            record_metadata={"diagnosis": "lung adenocarcinoma"},
        )
    )
    db.commit()

    summary = client.get(f"/v1/clinical/{CASE_ID}/patient-summary").json()
    eligibility = client.get(f"/v1/clinical/{CASE_ID}/eligibility").json()
    survival = client.get(f"/v1/clinical/{CASE_ID}/survival-baseline").json()

    assert summary["available"] is True
    assert summary["data_source"] == "case_metadata"
    assert summary["diagnosis"] == "Lung adenocarcinoma"

    assert eligibility["available"] is False
    assert eligibility["data_source"] == "case_metadata"
    assert eligibility["unavailable_reason"] == "No clinical eligibility features available."

    assert survival["available"] is False
    assert survival["data_source"] == "case_metadata"
    assert survival["unavailable_reason"] == "No stage or follow-up survival fields available."


def test_clinical_trial_matches_happy_path_parse(monkeypatch: pytest.MonkeyPatch, db, client) -> None:
    case_id = "TCGA-TRIAL-HAPPY"
    _insert_clinical_modality_result(
        db,
        case_id=case_id,
        payload={
            "patient_summary": {
                "diagnosis": "Lung adenocarcinoma",
                "stage": "Stage IIIB",
                "smoking_status": "Former smoker",
            }
        },
    )

    payload = {
        "studies": [
            {
                "protocolSection": {
                    "identificationModule": {
                        "nctId": "NCT00000001",
                        "briefTitle": "Stage IIIB Lung Adenocarcinoma Immunotherapy Trial",
                    },
                    "statusModule": {"overallStatus": "RECRUITING"},
                    "designModule": {"phases": ["PHASE2"]},
                    "conditionsModule": {"conditions": ["Non-small Cell Lung Cancer"]},
                    "eligibilityModule": {
                        "eligibilityCriteria": "Inclusion: stage iiib disease, former smoker cohort allowed"
                    },
                }
            }
        ]
    }

    def _fake_get(*args, **kwargs):
        return _FakeHttpxResponse(payload)

    monkeypatch.setattr("services.clinical.httpx.get", _fake_get)

    response = client.get(f"/v1/clinical/{case_id}/trial-matches?limit=20&recruiting_only=true")
    assert response.status_code == 200

    body = response.json()
    assert body["available"] is True
    assert body["data_source"] == "modality_result"
    assert body["query_terms"] == ["lung cancer", "stage iiib", "former smoker"]
    assert len(body["trials"]) == 1

    trial = body["trials"][0]
    assert trial["nct_id"] == "NCT00000001"
    assert trial["status"] == "RECRUITING"
    assert trial["phase"] == "Phase 2"
    assert trial["study_url"] == "https://clinicaltrials.gov/study/NCT00000001"
    assert trial["match_score"] > 0
    assert trial["match_reasons"]


def test_clinical_trial_matches_external_api_failure_fallback(
    monkeypatch: pytest.MonkeyPatch,
    db,
    client,
) -> None:
    case_id = "TCGA-TRIAL-FAIL"
    _insert_clinical_modality_result(
        db,
        case_id=case_id,
        payload={
            "patient_summary": {
                "diagnosis": "Lung adenocarcinoma",
                "stage": "Stage IV",
                "smoking_status": "Current smoker",
            }
        },
    )

    def _fake_get(*args, **kwargs):
        raise httpx.TimeoutException("timeout")

    monkeypatch.setattr("services.clinical.httpx.get", _fake_get)

    response = client.get(f"/v1/clinical/{case_id}/trial-matches")
    assert response.status_code == 200

    body = response.json()
    assert body["available"] is False
    assert body["trials"] == []
    assert body["query_terms"] == ["lung cancer", "stage iv", "current smoker"]
    assert "ClinicalTrials.gov unavailable" in body["unavailable_reason"]




def test_clinical_trial_matches_refresh_bypasses_cache(
    monkeypatch: pytest.MonkeyPatch,
    db,
    client,
) -> None:
    case_id = "TCGA-TRIAL-REFRESH"
    _insert_clinical_modality_result(
        db,
        case_id=case_id,
        payload={
            "patient_summary": {
                "diagnosis": "Lung adenocarcinoma",
                "stage": "Stage IIIA",
                "smoking_status": "Former smoker",
            }
        },
    )

    payloads = [
        {
            "studies": [
                {
                    "protocolSection": {
                        "identificationModule": {
                            "nctId": "NCT11111111",
                            "briefTitle": "First payload trial",
                        },
                        "statusModule": {"overallStatus": "RECRUITING"},
                        "designModule": {"phases": ["PHASE2"]},
                        "conditionsModule": {"conditions": ["Lung Cancer"]},
                        "eligibilityModule": {"eligibilityCriteria": "stage iiia former smoker"},
                    }
                }
            ]
        },
        {
            "studies": [
                {
                    "protocolSection": {
                        "identificationModule": {
                            "nctId": "NCT22222222",
                            "briefTitle": "Refreshed payload trial",
                        },
                        "statusModule": {"overallStatus": "RECRUITING"},
                        "designModule": {"phases": ["PHASE3"]},
                        "conditionsModule": {"conditions": ["Lung Adenocarcinoma"]},
                        "eligibilityModule": {"eligibilityCriteria": "stage iiia former smoker"},
                    }
                }
            ]
        },
    ]

    call_count = {"value": 0}

    def _fake_get(*args, **kwargs):
        idx = min(call_count["value"], len(payloads) - 1)
        call_count["value"] += 1
        return _FakeHttpxResponse(payloads[idx])

    monkeypatch.setattr("services.clinical.httpx.get", _fake_get)

    first = client.get(f"/v1/clinical/{case_id}/trial-matches?limit=5")
    assert first.status_code == 200
    assert first.json()["trials"][0]["nct_id"] == "NCT11111111"

    second = client.get(f"/v1/clinical/{case_id}/trial-matches?limit=5")
    assert second.status_code == 200
    assert second.json()["trials"][0]["nct_id"] == "NCT11111111"
    assert call_count["value"] == 1

    refreshed = client.get(f"/v1/clinical/{case_id}/trial-matches?limit=5&refresh=true")
    assert refreshed.status_code == 200
    assert refreshed.json()["trials"][0]["nct_id"] == "NCT22222222"
    assert call_count["value"] == 2

def test_clinical_trial_matches_scoring_ranking_is_deterministic(
    monkeypatch: pytest.MonkeyPatch,
    db,
    client,
) -> None:
    case_id = "TCGA-TRIAL-RANK"
    _insert_clinical_modality_result(
        db,
        case_id=case_id,
        payload={
            "patient_summary": {
                "diagnosis": "Lung adenocarcinoma",
                "stage": "Stage IV",
                "smoking_status": "Current smoker",
            }
        },
    )

    payload = {
        "studies": [
            {
                "protocolSection": {
                    "identificationModule": {
                        "nctId": "NCT00000020",
                        "briefTitle": "General NSCLC trial",
                    },
                    "statusModule": {"overallStatus": "RECRUITING"},
                    "designModule": {"phases": ["PHASE1"]},
                    "conditionsModule": {"conditions": ["Lung Cancer"]},
                    "eligibilityModule": {
                        "eligibilityCriteria": "Metastatic or stage iv disease; current smoker allowed"
                    },
                }
            },
            {
                "protocolSection": {
                    "identificationModule": {
                        "nctId": "NCT00000010",
                        "briefTitle": "Stage IV Lung Adenocarcinoma Smokers Study",
                    },
                    "statusModule": {"overallStatus": "RECRUITING"},
                    "designModule": {"phases": ["PHASE3"]},
                    "conditionsModule": {"conditions": ["Lung Adenocarcinoma"]},
                    "eligibilityModule": {
                        "eligibilityCriteria": "Inclusion requires stage iv adenocarcinoma and current smoker status"
                    },
                }
            },
            {
                "protocolSection": {
                    "identificationModule": {
                        "nctId": "NCT00000030",
                        "briefTitle": "Breast cancer comparator",
                    },
                    "statusModule": {"overallStatus": "NOT_YET_RECRUITING"},
                    "designModule": {"phases": ["PHASE2"]},
                    "conditionsModule": {"conditions": ["Breast Cancer"]},
                    "eligibilityModule": {"eligibilityCriteria": "No smoking requirement"},
                }
            },
        ]
    }

    def _fake_get(*args, **kwargs):
        return _FakeHttpxResponse(payload)

    monkeypatch.setattr("services.clinical.httpx.get", _fake_get)

    response = client.get(f"/v1/clinical/{case_id}/trial-matches?limit=3")
    assert response.status_code == 200

    trials = response.json()["trials"]
    assert [trial["nct_id"] for trial in trials] == ["NCT00000010", "NCT00000020", "NCT00000030"]
    assert trials[0]["match_score"] >= trials[1]["match_score"] >= trials[2]["match_score"]
