from __future__ import annotations

import json
from typing import Any

import pytest

from services import derive_case_id_from_slide_id
from services.pathology_assets import (
    EnsoProxyError,
    EnsoSlideResolution,
    ProxyBinaryPayload,
    proxy_enso_asset,
    resolve_enso_slide_id,
    resolve_enso_slide_status,
)
from services.pathology_id_resolution import (
    resolve_artifact_json_path,
    resolve_heatmap_file,
    resolve_wsi_file,
)

SLIDE_ID = "TCGA-05-4244-DX1"
CASE_ID = "TCGA-05-4244"
FULL_SLIDE_ID = "TCGA-05-4244-01Z-00-DX1"

ARTIFACT_METHOD_BY_SECTION = {
    "tissue_composition": "pathology-tissue-artifact-v1",
    "heatmap": "pathology-heatmap-artifact-v1",
    "evidence": "pathology-evidence-artifact-v1",
}

DETERMINISTIC_METHOD_BY_SECTION = {
    "tissue_composition": "pathology-tissue-v1",
    "heatmap": "pathology-heatmap-v1",
    "evidence": "pathology-evidence-v1",
}

SEGLUNG_METHOD_BY_SECTION = {
    "tissue_composition": "pathology-tissue-seglung-v1",
    "heatmap": "pathology-heatmap-seglung-v1",
    "evidence": "pathology-evidence-seglung-v1",
}


@pytest.fixture(autouse=True)
def clear_pathology_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for env_name in (
        "PATHOLOGY_SEGLUNG_DIR",
        "PATHOLOGY_TILE_ENCODER_MODEL",
    ):
        monkeypatch.delenv(env_name, raising=False)


def _request_pathology_section(
    client,
    *,
    slide_id: str,
    section_key: str,
    strict_missing: bool | None = None,
):
    query = ""
    if strict_missing is not None:
        query = f"?strict_missing={'true' if strict_missing else 'false'}"

    if section_key == "tissue_composition":
        return client.get(f"/v1/pathology/slides/{slide_id}/tissue-composition{query}")
    if section_key == "heatmap":
        return client.get(f"/v1/pathology/slides/{slide_id}/heatmap{query}")
    if section_key == "evidence":
        return client.post(f"/v1/pathology/slides/{slide_id}/evidence{query}")
    raise AssertionError(f"Unexpected section key: {section_key}")


def _artifact_section_payload(section_key: str) -> dict[str, Any]:
    if section_key == "tissue_composition":
        return {
            "fractions": [
                {"tissue": "Tumor", "fraction": 0.52},
                {"tissue": "Stroma", "fraction": 0.31},
                {"tissue": "Necrosis", "fraction": 0.1},
                {"tissue": "Lymphocyte-rich", "fraction": 0.07},
            ],
            "qc": {"coverage": 0.89, "artifact_warning": "None"},
        }
    if section_key == "heatmap":
        return {
            "heatmap_uri": "artifact://heatmap/tcga-05-4244",
            "viewport_hint": {"x": 0.21, "y": 0.18, "width": 0.4, "height": 0.35},
        }
    if section_key == "evidence":
        return {
            "top_tiles": [
                {"tile_id": "tile_001", "score": 0.93, "rationale": "Tumor-rich field"},
                {
                    "tile_id": "tile_002",
                    "score": 0.86,
                    "rationale": "Peri-tumoral immune cluster",
                },
            ]
        }
    raise AssertionError(f"Unexpected section key: {section_key}")


def _invalid_artifact_section_payload(section_key: str) -> dict[str, Any]:
    if section_key == "tissue_composition":
        return {"fractions": "not-a-list", "qc": {"coverage": 1.5, "artifact_warning": None}}
    if section_key == "heatmap":
        return {"heatmap_uri": 123, "viewport_hint": {"x": 0.2}}
    if section_key == "evidence":
        return {
            "top_tiles": [
                {"tile_id": "tile_bad", "score": 2.0, "rationale": "Invalid score outside range"}
            ]
        }
    raise AssertionError(f"Unexpected section key: {section_key}")


def _seglung_payload() -> dict[str, Any]:
    return {
        "segmentation": {
            "class_pixel_counts": {
                "tumor": 620,
                "stroma": 250,
                "necrosis": 80,
                "lymphocyte": 50,
            },
            "coverage": 0.94,
            "artifact_warning": "Minor blur in upper-left corner",
            "viewport_hint": {"x": 0.22, "y": 0.17, "width": 0.36, "height": 0.31},
            "hotspots": [
                {
                    "tile_id": "seglung_tile_001",
                    "score": 0.91,
                    "label": "tumor",
                    "bbox": {"x": 0.24, "y": 0.2, "width": 0.14, "height": 0.16},
                },
                {
                    "tile_id": "seglung_tile_002",
                    "score": 0.82,
                    "label": "lymphocyte",
                    "bbox": {"x": 0.48, "y": 0.26, "width": 0.14, "height": 0.16},
                },
            ],
            "model_id": "google/path-foundation",
            "run_id": "seglung-run-001",
        }
    }


def test_get_tissue_composition_happy_path_structure_and_metadata(client) -> None:
    response = client.get(f"/v1/pathology/slides/{SLIDE_ID}/tissue-composition")

    assert response.status_code == 200
    payload = response.json()

    assert payload["case_id"] == CASE_ID
    assert payload["slide_id"] == SLIDE_ID
    assert payload["fractions"] == [
        {"tissue": "Tumor", "fraction": 0.61},
        {"tissue": "Stroma", "fraction": 0.24},
        {"tissue": "Necrosis", "fraction": 0.08},
        {"tissue": "Lymphocyte-rich", "fraction": 0.07},
    ]
    assert payload["qc"] == {
        "coverage": 0.93,
        "artifact_warning": "Mild pen-mark artifact at peripheral region",
    }
    assert payload["meta"] == {
        "method": "pathology-tissue-v1",
        "version": "hackathon-p0",
        "timestamp": "2026-03-01T00:00:00Z",
        "proxy_estimate": True,
    }
    assert payload["provenance"]["data_source"] == "deterministic_fallback"
    assert payload["provenance"]["resolver_strategy"] == "recursive-non-symlink-first-v1"
    assert payload["provenance"]["model_id"] == "pathology-proxy-deterministic-v1"
    assert payload["provenance"]["tile_encoder_model_id"] == "google/path-foundation"
    assert payload["provenance"]["run_id"] == f"deterministic:{CASE_ID}:{SLIDE_ID}"


def test_deterministic_pathology_provenance_surfaces_configured_tile_encoder_model(
    monkeypatch,
    client,
) -> None:
    monkeypatch.setenv("PATHOLOGY_TILE_ENCODER_MODEL", "google/path-foundation-v2")

    response = client.get(f"/v1/pathology/slides/{SLIDE_ID}/tissue-composition")
    payload = response.json()

    assert response.status_code == 200
    assert payload["provenance"]["data_source"] == "deterministic_fallback"
    assert payload["provenance"]["tile_encoder_model_id"] == "google/path-foundation-v2"


def test_get_heatmap_happy_path_structure(client) -> None:
    response = client.get(f"/v1/pathology/slides/{SLIDE_ID}/heatmap")

    assert response.status_code == 200
    payload = response.json()

    assert payload["case_id"] == CASE_ID
    assert payload["slide_id"] == SLIDE_ID
    assert payload["heatmap_uri"] == f"/v1/pathology/slides/{SLIDE_ID}/heatmap/image"
    assert payload["slide_preview_uri"] == f"/v1/pathology/slides/{SLIDE_ID}/preview/image"
    assert payload["viewport_hint"] == {
        "x": 0.12,
        "y": 0.19,
        "width": 0.42,
        "height": 0.33,
    }
    assert payload["meta"]["method"] == "pathology-heatmap-v1"
    assert payload["meta"]["version"] == "hackathon-p0"
    assert payload["meta"]["timestamp"] == "2026-03-01T00:00:00Z"
    assert payload["meta"]["proxy_estimate"] is True
    assert payload["provenance"]["data_source"] == "deterministic_fallback"
    assert payload["provenance"]["resolver_strategy"] == "recursive-non-symlink-first-v1"


def test_get_evidence_happy_path_structure(client) -> None:
    response = client.post(f"/v1/pathology/slides/{SLIDE_ID}/evidence")

    assert response.status_code == 200
    payload = response.json()

    assert payload["case_id"] == CASE_ID
    assert payload["slide_id"] == SLIDE_ID
    assert payload["top_tiles"] == [
        {
            "tile_id": "tile_183",
            "score": 0.87,
            "rationale": "Dense tumor-infiltrating lymphocyte cluster",
            "bbox": {"x": 0.18, "y": 0.21, "width": 0.16, "height": 0.18},
            "tile_coordinates": {"row": 0, "col": 0, "one_based_index": False},
        },
        {
            "tile_id": "tile_204",
            "score": 0.82,
            "rationale": "Immune-rich stroma adjacent to tumor",
            "bbox": {"x": 0.52, "y": 0.24, "width": 0.16, "height": 0.18},
            "tile_coordinates": {"row": 0, "col": 1, "one_based_index": False},
        },
        {
            "tile_id": "tile_097",
            "score": 0.74,
            "rationale": "Necrotic pocket with peri-necrotic inflammation",
            "bbox": {"x": 0.63, "y": 0.58, "width": 0.16, "height": 0.18},
            "tile_coordinates": {"row": 1, "col": 0, "one_based_index": False},
        },
    ]
    assert payload["meta"]["method"] == "pathology-evidence-v1"
    assert payload["meta"]["version"] == "hackathon-p0"
    assert payload["meta"]["timestamp"] == "2026-03-01T00:00:00Z"
    assert payload["meta"]["proxy_estimate"] is True
    assert payload["provenance"]["data_source"] == "deterministic_fallback"
    assert payload["provenance"]["resolver_strategy"] == "recursive-non-symlink-first-v1"


@pytest.mark.parametrize(
    ("slide_id", "expected_case_id"),
    [
        ("TCGA-05-4244-DX1", "TCGA-05-4244"),
        ("TCGA-05-4244-DXa", "TCGA-05-4244"),
        ("TCGA-05-4244-01Z-00-DX1", "TCGA-05-4244"),
        ("TCGA-05-4244", "TCGA-05-4244"),
        ("", ""),
    ],
)
def test_derive_case_id_from_slide_id(slide_id: str, expected_case_id: str) -> None:
    assert derive_case_id_from_slide_id(slide_id) == expected_case_id


@pytest.mark.parametrize("section_key", ["tissue_composition", "heatmap", "evidence"])
def test_pathology_section_uses_artifact_when_available(
    monkeypatch,
    tmp_path,
    client,
    section_key: str,
) -> None:
    artifact_payload = {section_key: _artifact_section_payload(section_key)}
    (tmp_path / f"{SLIDE_ID}.json").write_text(json.dumps(artifact_payload), encoding="utf-8")
    monkeypatch.setenv("PATHOLOGY_ARTIFACT_DIR", str(tmp_path))

    response = _request_pathology_section(client, slide_id=SLIDE_ID, section_key=section_key)

    assert response.status_code == 200
    payload = response.json()
    assert payload["case_id"] == CASE_ID
    assert payload["slide_id"] == SLIDE_ID
    assert payload["meta"]["method"] == ARTIFACT_METHOD_BY_SECTION[section_key]
    assert payload["provenance"]["data_source"] == "artifact"
    assert payload["provenance"]["artifact_path"].endswith(f"/{SLIDE_ID}.json")
    assert payload["provenance"]["artifact_sha256"]


@pytest.mark.parametrize("section_key", ["tissue_composition", "heatmap", "evidence"])
def test_pathology_section_uses_seglung_before_deterministic_fallback(
    monkeypatch,
    tmp_path,
    client,
    section_key: str,
) -> None:
    artifact_dir = tmp_path / "artifacts"
    seglung_dir = tmp_path / "seglung"
    artifact_dir.mkdir(parents=True)
    seglung_dir.mkdir(parents=True)

    (seglung_dir / f"{SLIDE_ID}.json").write_text(json.dumps(_seglung_payload()), encoding="utf-8")

    monkeypatch.setenv("PATHOLOGY_ARTIFACT_DIR", str(artifact_dir))
    monkeypatch.setenv("PATHOLOGY_SEGLUNG_DIR", str(seglung_dir))

    response = _request_pathology_section(client, slide_id=SLIDE_ID, section_key=section_key)

    assert response.status_code == 200
    payload = response.json()
    assert payload["meta"]["method"] == SEGLUNG_METHOD_BY_SECTION[section_key]
    assert payload["provenance"]["data_source"] == "seglung"
    assert payload["provenance"]["source_path"].endswith(f"/{SLIDE_ID}.json")


@pytest.mark.parametrize("section_key", ["tissue_composition", "heatmap", "evidence"])
def test_pathology_artifact_precedence_is_preserved_over_seglung(
    monkeypatch,
    tmp_path,
    client,
    section_key: str,
) -> None:
    artifact_dir = tmp_path / "artifacts"
    seglung_dir = tmp_path / "seglung"
    artifact_dir.mkdir(parents=True)
    seglung_dir.mkdir(parents=True)

    (artifact_dir / f"{SLIDE_ID}.json").write_text(
        json.dumps({section_key: _artifact_section_payload(section_key)}),
        encoding="utf-8",
    )
    (seglung_dir / f"{SLIDE_ID}.json").write_text(json.dumps(_seglung_payload()), encoding="utf-8")

    monkeypatch.setenv("PATHOLOGY_ARTIFACT_DIR", str(artifact_dir))
    monkeypatch.setenv("PATHOLOGY_SEGLUNG_DIR", str(seglung_dir))

    response = _request_pathology_section(client, slide_id=SLIDE_ID, section_key=section_key)

    assert response.status_code == 200
    payload = response.json()
    assert payload["meta"]["method"] == ARTIFACT_METHOD_BY_SECTION[section_key]
    assert payload["provenance"]["data_source"] == "artifact"


def test_pathology_artifact_provenance_fields_are_exposed(monkeypatch, tmp_path, client) -> None:
    artifact_payload = {
        "tissue_composition": {
            **_artifact_section_payload("tissue_composition"),
            "provenance": {
                "model_id": "pathology-foundation-v3",
                "checkpoint_sha256": "abc123",
                "run_id": "run-20260306-01",
                "embedding_source_id": "embeddings-v7",
            },
        }
    }
    (tmp_path / f"{SLIDE_ID}.json").write_text(json.dumps(artifact_payload), encoding="utf-8")
    monkeypatch.setenv("PATHOLOGY_ARTIFACT_DIR", str(tmp_path))

    response = client.get(f"/v1/pathology/slides/{SLIDE_ID}/tissue-composition")
    payload = response.json()

    assert response.status_code == 200
    assert payload["provenance"]["model_id"] == "pathology-foundation-v3"
    assert payload["provenance"]["checkpoint_sha256"] == "abc123"
    assert payload["provenance"]["run_id"] == "run-20260306-01"
    assert payload["provenance"]["embedding_source_id"] == "embeddings-v7"


@pytest.mark.parametrize("section_key", ["tissue_composition", "heatmap", "evidence"])
def test_pathology_section_falls_back_when_artifact_file_absent(
    monkeypatch,
    tmp_path,
    client,
    section_key: str,
) -> None:
    monkeypatch.setenv("PATHOLOGY_ARTIFACT_DIR", str(tmp_path))

    response = _request_pathology_section(client, slide_id=SLIDE_ID, section_key=section_key)

    assert response.status_code == 200
    payload = response.json()
    assert payload["meta"]["method"] == DETERMINISTIC_METHOD_BY_SECTION[section_key]


@pytest.mark.parametrize("section_key", ["tissue_composition", "heatmap", "evidence"])
def test_pathology_section_strict_missing_returns_404_when_artifact_absent(
    monkeypatch,
    tmp_path,
    client,
    section_key: str,
) -> None:
    monkeypatch.setenv("PATHOLOGY_ARTIFACT_DIR", str(tmp_path))

    response = _request_pathology_section(
        client,
        slide_id=SLIDE_ID,
        section_key=section_key,
        strict_missing=True,
    )

    assert response.status_code == 404
    assert "Strict missing-data mode" in response.json()["detail"]


@pytest.mark.parametrize("section_key", ["tissue_composition", "heatmap", "evidence"])
def test_pathology_section_strict_missing_ignores_seglung_fallback(
    monkeypatch,
    tmp_path,
    client,
    section_key: str,
) -> None:
    artifact_dir = tmp_path / "artifacts"
    seglung_dir = tmp_path / "seglung"
    artifact_dir.mkdir(parents=True)
    seglung_dir.mkdir(parents=True)

    (seglung_dir / f"{SLIDE_ID}.json").write_text(json.dumps(_seglung_payload()), encoding="utf-8")

    monkeypatch.setenv("PATHOLOGY_ARTIFACT_DIR", str(artifact_dir))
    monkeypatch.setenv("PATHOLOGY_SEGLUNG_DIR", str(seglung_dir))

    strict_response = _request_pathology_section(
        client,
        slide_id=SLIDE_ID,
        section_key=section_key,
        strict_missing=True,
    )
    assert strict_response.status_code == 404

    fallback_response = _request_pathology_section(
        client,
        slide_id=SLIDE_ID,
        section_key=section_key,
        strict_missing=False,
    )
    assert fallback_response.status_code == 200
    assert fallback_response.json()["meta"]["method"] == SEGLUNG_METHOD_BY_SECTION[section_key]


@pytest.mark.parametrize("section_key", ["tissue_composition", "heatmap", "evidence"])
def test_pathology_section_strict_missing_env_default_can_be_overridden(
    monkeypatch,
    tmp_path,
    client,
    section_key: str,
) -> None:
    monkeypatch.setenv("PATHOLOGY_ARTIFACT_DIR", str(tmp_path))
    monkeypatch.setenv("PATHOLOGY_STRICT_MISSING_DATA", "true")

    strict_response = _request_pathology_section(client, slide_id=SLIDE_ID, section_key=section_key)
    assert strict_response.status_code == 404

    non_strict_response = _request_pathology_section(
        client,
        slide_id=SLIDE_ID,
        section_key=section_key,
        strict_missing=False,
    )
    assert non_strict_response.status_code == 200
    assert non_strict_response.json()["meta"]["method"] == DETERMINISTIC_METHOD_BY_SECTION[section_key]


@pytest.mark.parametrize("section_key", ["tissue_composition", "heatmap", "evidence"])
def test_pathology_section_falls_back_when_artifact_section_shape_invalid(
    monkeypatch,
    tmp_path,
    client,
    section_key: str,
) -> None:
    artifact_payload = {section_key: _invalid_artifact_section_payload(section_key)}
    (tmp_path / f"{SLIDE_ID}.json").write_text(json.dumps(artifact_payload), encoding="utf-8")
    monkeypatch.setenv("PATHOLOGY_ARTIFACT_DIR", str(tmp_path))

    response = _request_pathology_section(client, slide_id=SLIDE_ID, section_key=section_key)

    assert response.status_code == 200
    payload = response.json()
    assert payload["meta"]["method"] == DETERMINISTIC_METHOD_BY_SECTION[section_key]


@pytest.mark.parametrize("section_key", ["tissue_composition", "heatmap", "evidence"])
def test_pathology_section_strict_missing_rejects_invalid_artifact_shape(
    monkeypatch,
    tmp_path,
    client,
    section_key: str,
) -> None:
    artifact_payload = {section_key: _invalid_artifact_section_payload(section_key)}
    (tmp_path / f"{SLIDE_ID}.json").write_text(json.dumps(artifact_payload), encoding="utf-8")
    monkeypatch.setenv("PATHOLOGY_ARTIFACT_DIR", str(tmp_path))

    response = _request_pathology_section(
        client,
        slide_id=SLIDE_ID,
        section_key=section_key,
        strict_missing=True,
    )

    assert response.status_code == 404
    assert section_key in response.json()["detail"]


@pytest.mark.parametrize("section_key", ["tissue_composition", "heatmap", "evidence"])
def test_pathology_section_uses_case_artifact_after_invalid_slide_section(
    monkeypatch,
    tmp_path,
    client,
    section_key: str,
) -> None:
    slide_payload = {section_key: _invalid_artifact_section_payload(section_key)}
    case_payload = {section_key: _artifact_section_payload(section_key)}
    (tmp_path / f"{SLIDE_ID}.json").write_text(json.dumps(slide_payload), encoding="utf-8")
    (tmp_path / f"{CASE_ID}.json").write_text(json.dumps(case_payload), encoding="utf-8")
    monkeypatch.setenv("PATHOLOGY_ARTIFACT_DIR", str(tmp_path))

    response = _request_pathology_section(client, slide_id=SLIDE_ID, section_key=section_key)

    assert response.status_code == 200
    payload = response.json()
    assert payload["meta"]["method"] == ARTIFACT_METHOD_BY_SECTION[section_key]


@pytest.mark.parametrize("section_key", ["tissue_composition", "heatmap", "evidence"])
def test_pathology_section_resolves_short_slide_id_with_only_full_id_artifact(
    monkeypatch,
    tmp_path,
    client,
    section_key: str,
) -> None:
    artifact_payload = {section_key: _artifact_section_payload(section_key)}
    (tmp_path / f"{FULL_SLIDE_ID}.json").write_text(json.dumps(artifact_payload), encoding="utf-8")
    monkeypatch.setenv("PATHOLOGY_ARTIFACT_DIR", str(tmp_path))

    response = _request_pathology_section(client, slide_id=SLIDE_ID, section_key=section_key)

    assert response.status_code == 200
    payload = response.json()
    assert payload["meta"]["method"] == ARTIFACT_METHOD_BY_SECTION[section_key]


@pytest.mark.parametrize("section_key", ["tissue_composition", "heatmap", "evidence"])
def test_pathology_section_uses_nested_artifact_without_symlink(
    monkeypatch,
    tmp_path,
    client,
    section_key: str,
) -> None:
    artifact_payload = {section_key: _artifact_section_payload(section_key)}
    nested_dir = tmp_path / "nested" / "case"
    nested_dir.mkdir(parents=True)
    (nested_dir / f"{FULL_SLIDE_ID}.json").write_text(json.dumps(artifact_payload), encoding="utf-8")
    monkeypatch.setenv("PATHOLOGY_ARTIFACT_DIR", str(tmp_path))

    response = _request_pathology_section(client, slide_id=SLIDE_ID, section_key=section_key)

    assert response.status_code == 200
    payload = response.json()
    assert payload["meta"]["method"] == ARTIFACT_METHOD_BY_SECTION[section_key]


@pytest.mark.parametrize("section_key", ["tissue_composition", "heatmap", "evidence"])
def test_pathology_section_resolves_case_id_with_only_slide_artifact(
    monkeypatch,
    tmp_path,
    client,
    section_key: str,
) -> None:
    artifact_payload = {section_key: _artifact_section_payload(section_key)}
    (tmp_path / f"{SLIDE_ID}.json").write_text(json.dumps(artifact_payload), encoding="utf-8")
    monkeypatch.setenv("PATHOLOGY_ARTIFACT_DIR", str(tmp_path))

    response = _request_pathology_section(client, slide_id=CASE_ID, section_key=section_key)

    assert response.status_code == 200
    payload = response.json()
    assert payload["meta"]["method"] == ARTIFACT_METHOD_BY_SECTION[section_key]


def test_artifact_path_resolution_supports_nested_real_file_without_symlink(tmp_path) -> None:
    nested_dir = tmp_path / "nested" / "case"
    nested_dir.mkdir(parents=True)
    real_artifact = nested_dir / f"{FULL_SLIDE_ID}.json"
    real_artifact.write_text("{}", encoding="utf-8")

    resolved_path = resolve_artifact_json_path(tmp_path, SLIDE_ID)

    assert resolved_path == real_artifact


def test_artifact_path_resolution_prefers_exact_slide_file_over_case_alias(tmp_path) -> None:
    slide_artifact = tmp_path / f"{SLIDE_ID}.json"
    case_artifact = tmp_path / f"{CASE_ID}.json"
    slide_artifact.write_text("{}", encoding="utf-8")
    case_artifact.write_text("{}", encoding="utf-8")

    resolved_path = resolve_artifact_json_path(tmp_path, SLIDE_ID)

    assert resolved_path == slide_artifact


def test_artifact_path_resolution_prefers_nested_real_file_over_root_symlink(tmp_path) -> None:
    nested_dir = tmp_path / "real"
    nested_dir.mkdir(parents=True)
    real_artifact = nested_dir / f"{FULL_SLIDE_ID}.json"
    real_artifact.write_text("{}", encoding="utf-8")

    symlink_artifact = tmp_path / f"{SLIDE_ID}.json"
    try:
        symlink_artifact.symlink_to(real_artifact)
    except OSError:
        pytest.skip("symlink not supported in this environment")

    resolved_path = resolve_artifact_json_path(tmp_path, SLIDE_ID)

    assert resolved_path == real_artifact


def test_heatmap_and_wsi_resolvers_support_short_case_ids_in_nested_layout(tmp_path) -> None:
    heatmap_dir = tmp_path / "heatmaps"
    slide_dir = tmp_path / "slides"
    heatmap_dir.mkdir(parents=True)
    slide_dir.mkdir(parents=True)

    heatmap_path = heatmap_dir / f"{FULL_SLIDE_ID}_attention.png"
    heatmap_path.write_bytes(b"png")

    slide_path = slide_dir / f"{FULL_SLIDE_ID}.svs"
    slide_path.write_bytes(b"svs")

    resolved_heatmap = resolve_heatmap_file(tmp_path, CASE_ID)
    resolved_slide = resolve_wsi_file(tmp_path, CASE_ID)

    assert resolved_heatmap == heatmap_path
    assert resolved_slide == slide_path


def test_heatmap_image_route_returns_image_bytes(monkeypatch, tmp_path, client) -> None:
    heatmap_path = tmp_path / f"{SLIDE_ID}_attention.png"
    expected_bytes = b"\x89PNG\r\n\x1a\nheatmap"
    heatmap_path.write_bytes(expected_bytes)
    monkeypatch.setenv("PATHOLOGY_HEATMAP_DIR", str(tmp_path))

    response = client.get(f"/v1/pathology/slides/{SLIDE_ID}/heatmap/image")

    assert response.status_code == 200
    assert response.content == expected_bytes
    assert response.headers["content-type"].startswith("image/png")


def test_heatmap_image_route_prefers_exact_slide_asset_over_case_alias(
    monkeypatch,
    tmp_path,
    client,
) -> None:
    slide_bytes = b"\x89PNG\r\n\x1a\nslide-heatmap"
    case_bytes = b"\x89PNG\r\n\x1a\ncase-heatmap"
    (tmp_path / f"{SLIDE_ID}_attention.png").write_bytes(slide_bytes)
    (tmp_path / f"{CASE_ID}_attention.png").write_bytes(case_bytes)
    monkeypatch.setenv("PATHOLOGY_HEATMAP_DIR", str(tmp_path))

    response = client.get(f"/v1/pathology/slides/{SLIDE_ID}/heatmap/image")

    assert response.status_code == 200
    assert response.content == slide_bytes
    assert response.headers["content-type"].startswith("image/png")


def test_preview_image_route_falls_back_to_heatmap_bytes(monkeypatch, tmp_path, client) -> None:
    heatmap_path = tmp_path / f"{SLIDE_ID}_attention.jpg"
    expected_bytes = b"\xff\xd8\xffpreview"
    heatmap_path.write_bytes(expected_bytes)
    monkeypatch.setenv("PATHOLOGY_HEATMAP_DIR", str(tmp_path))

    response = client.get(f"/v1/pathology/slides/{SLIDE_ID}/preview/image")

    assert response.status_code == 200
    assert response.content == expected_bytes
    assert response.headers["content-type"].startswith("image/jpeg")


def test_heatmap_artifact_response_includes_stable_image_endpoints(monkeypatch, tmp_path, client) -> None:
    artifact_payload = {"heatmap": _artifact_section_payload("heatmap")}
    (tmp_path / f"{SLIDE_ID}.json").write_text(json.dumps(artifact_payload), encoding="utf-8")
    monkeypatch.setenv("PATHOLOGY_ARTIFACT_DIR", str(tmp_path))

    response = client.get(f"/v1/pathology/slides/{SLIDE_ID}/heatmap")
    payload = response.json()

    assert response.status_code == 200
    assert payload["heatmap_uri"] == f"/v1/pathology/slides/{SLIDE_ID}/heatmap/image"
    assert payload["slide_preview_uri"] == f"/v1/pathology/slides/{SLIDE_ID}/preview/image"


def test_evidence_artifact_infers_bbox_from_tile_coordinate_id(monkeypatch, tmp_path, client) -> None:
    artifact_payload = {
        "evidence": {
            "top_tiles": [
                {"tile_id": "tile_r02_c03", "score": 0.91, "rationale": "Tile with coordinate format"},
                {"tile_id": "tile_r04_c01", "score": 0.73, "rationale": "Second tile for grid estimation"},
            ]
        }
    }
    (tmp_path / f"{SLIDE_ID}.json").write_text(json.dumps(artifact_payload), encoding="utf-8")
    monkeypatch.setenv("PATHOLOGY_ARTIFACT_DIR", str(tmp_path))

    response = client.post(f"/v1/pathology/slides/{SLIDE_ID}/evidence")
    payload = response.json()

    assert response.status_code == 200
    assert payload["top_tiles"][0]["bbox"] is not None
    assert payload["top_tiles"][1]["bbox"] is not None
    assert payload["top_tiles"][0]["tile_coordinates"] == {"row": 2, "col": 3, "one_based_index": True}
    assert payload["top_tiles"][1]["tile_coordinates"] == {"row": 4, "col": 1, "one_based_index": True}
    for tile in payload["top_tiles"]:
        bbox = tile["bbox"]
        assert 0.0 <= bbox["x"] <= 1.0
        assert 0.0 <= bbox["y"] <= 1.0
        assert 0.0 <= bbox["width"] <= 1.0
        assert 0.0 <= bbox["height"] <= 1.0


def test_evidence_artifact_infers_bbox_when_tile_id_unparseable(monkeypatch, tmp_path, client) -> None:
    artifact_payload = {
        "evidence": {
            "top_tiles": [
                {"tile_id": "tile_no_grid_info", "score": 0.84, "rationale": "No coordinate token present"}
            ]
        }
    }
    (tmp_path / f"{SLIDE_ID}.json").write_text(json.dumps(artifact_payload), encoding="utf-8")
    monkeypatch.setenv("PATHOLOGY_ARTIFACT_DIR", str(tmp_path))

    response = client.post(f"/v1/pathology/slides/{SLIDE_ID}/evidence")
    payload = response.json()

    assert response.status_code == 200
    bbox = payload["top_tiles"][0]["bbox"]
    assert bbox is not None
    assert payload["top_tiles"][0]["tile_coordinates"] == {
        "row": 0,
        "col": 0,
        "one_based_index": False,
    }
    assert 0.0 <= bbox["x"] <= 1.0
    assert 0.0 <= bbox["y"] <= 1.0
    assert 0.0 <= bbox["width"] <= 1.0
    assert 0.0 <= bbox["height"] <= 1.0


def test_resolve_enso_slide_id_prefers_dx1_then_lexicographic(monkeypatch, tmp_path) -> None:
    (tmp_path / "TCGA-05-4244-01Z-00-DX2.zzz.npy").write_bytes(b"")
    (tmp_path / "TCGA-05-4244-01Z-00-DX1.zzz.npy").write_bytes(b"")
    (tmp_path / "TCGA-05-4244-01Z-00-DX1.aaa.npy").write_bytes(b"")
    (tmp_path / "TCGA-05-4244-01Z-00-DX1.aaa_coords.npy").write_bytes(b"")

    monkeypatch.setenv("ENSO_EMBEDDINGS_DIR", str(tmp_path))

    resolved_slide_id = resolve_enso_slide_id(SLIDE_ID)

    assert resolved_slide_id == "TCGA-05-4244-01Z-00-DX1.aaa"


def test_resolve_enso_slide_id_prefers_non_symlink_nested_file_over_short_symlink_alias(
    monkeypatch,
    tmp_path,
) -> None:
    nested_dir = tmp_path / "real"
    nested_dir.mkdir(parents=True)
    real_path = nested_dir / "TCGA-05-4244-01Z-00-DX1.full.npy"
    real_path.write_bytes(b"")

    symlink_path = tmp_path / f"{SLIDE_ID}.npy"
    try:
        symlink_path.symlink_to(real_path)
    except OSError:
        pytest.skip("symlink not supported in this environment")

    monkeypatch.setenv("ENSO_EMBEDDINGS_DIR", str(tmp_path))

    resolved_slide_id = resolve_enso_slide_id(SLIDE_ID)

    assert resolved_slide_id == "TCGA-05-4244-01Z-00-DX1.full"


def test_resolve_enso_slide_id_returns_original_when_embeddings_dir_missing(monkeypatch) -> None:
    monkeypatch.setenv("ENSO_EMBEDDINGS_DIR", "/tmp/path-that-does-not-exist")

    assert resolve_enso_slide_id(SLIDE_ID) == SLIDE_ID


def test_resolve_enso_slide_status_marks_deepzoom_unavailable_when_slide_not_indexed(
    monkeypatch,
    tmp_path,
) -> None:
    embeddings_dir = tmp_path / "embeddings"
    embeddings_dir.mkdir(parents=True)
    (embeddings_dir / "TCGA-99-9999-01Z-00-DX1.alt.npy").write_bytes(b"")

    slide_dir = tmp_path / "slides"
    slide_dir.mkdir(parents=True)
    (slide_dir / f"{SLIDE_ID}.svs").write_bytes(b"svs")

    monkeypatch.setenv("ENSO_EMBEDDINGS_DIR", str(embeddings_dir))
    monkeypatch.setenv("PATHOLOGY_WSI_DIR", str(slide_dir))

    status = resolve_enso_slide_status(SLIDE_ID)

    assert status.requested_slide_id == SLIDE_ID
    assert status.resolved_slide_id == SLIDE_ID
    assert status.deepzoom_available is False
    assert "not indexed" in (status.unavailable_reason or "").lower()


def test_resolve_enso_slide_id_uses_tcga_root_default_when_embeddings_env_absent(
    monkeypatch,
    tmp_path,
) -> None:
    tcga_root = tmp_path / "tcga-full475"
    embeddings_dir = tcga_root / "embeddings" / "level0"
    embeddings_dir.mkdir(parents=True)
    (embeddings_dir / "TCGA-05-4244-01Z-00-DX1.alt.npy").write_bytes(b"")

    monkeypatch.delenv("ENSO_EMBEDDINGS_DIR", raising=False)
    monkeypatch.setenv("TCGA_FULL475_ROOT", str(tcga_root))

    resolved_slide_id = resolve_enso_slide_id(SLIDE_ID)

    assert resolved_slide_id == "TCGA-05-4244-01Z-00-DX1.alt"


def test_dzi_route_proxies_using_resolved_enso_id(monkeypatch, client) -> None:
    observed: dict[str, object] = {}

    def fake_proxy_enso_asset(*, path, query_params=None, forward_headers=()):
        observed["path"] = path
        observed["query_params"] = query_params
        observed["forward_headers"] = tuple(forward_headers)
        return ProxyBinaryPayload(
            content=b"<Image />",
            media_type="application/xml",
            headers={"Cache-Control": "public, max-age=3600"},
        )

    monkeypatch.setattr("routers.pathology.resolve_enso_slide_id", lambda _: "resolved-slide-id")
    monkeypatch.setattr("routers.pathology.proxy_enso_asset", fake_proxy_enso_asset)

    response = client.get(f"/v1/pathology/slides/{SLIDE_ID}/dzi")

    assert response.status_code == 200
    assert response.content == b"<Image />"
    assert response.headers["content-type"].startswith("application/xml")
    assert response.headers["cache-control"] == "no-store"
    assert observed["path"] == "/api/slides/resolved-slide-id/dzi"
    assert observed["query_params"] is None


def test_attention_heatmap_route_forwards_query_params(monkeypatch, client) -> None:
    observed: dict[str, object] = {}

    def fake_proxy_enso_asset(*, path, query_params=None, forward_headers=()):
        observed["path"] = path
        observed["query_params"] = query_params
        observed["forward_headers"] = tuple(forward_headers)
        return ProxyBinaryPayload(
            content=b"heatmap-bytes",
            media_type="image/png",
            headers={"X-Coverage-Width": "4096"},
        )

    monkeypatch.setattr("routers.pathology.resolve_enso_slide_id", lambda _: "resolved-slide-id")
    monkeypatch.setattr("routers.pathology.proxy_enso_asset", fake_proxy_enso_asset)

    response = client.get(
        f"/v1/pathology/slides/{SLIDE_ID}/attention-heatmap"
        "?model_id=immune_signature&level=3&smooth=false&alpha_power=0.95"
    )

    assert response.status_code == 200
    assert response.content == b"heatmap-bytes"
    assert response.headers["content-type"].startswith("image/png")
    assert response.headers["x-coverage-width"] == "4096"
    assert observed["path"] == "/api/heatmap/resolved-slide-id/immune_signature"
    assert observed["query_params"] == {"level": 3, "smooth": False, "alpha_power": 0.95}


def test_proxy_routes_propagate_upstream_errors(monkeypatch, client) -> None:
    def failing_proxy(*, path, query_params=None, forward_headers=()):
        raise EnsoProxyError(status_code=503, detail="Upstream unavailable")

    monkeypatch.setattr("routers.pathology.resolve_enso_slide_id", lambda _: "resolved-slide-id")
    monkeypatch.setattr("routers.pathology.proxy_enso_asset", failing_proxy)

    response = client.get(f"/v1/pathology/slides/{SLIDE_ID}/tile/2/10_12.jpeg")

    assert response.status_code == 503
    assert response.json() == {"detail": "Upstream unavailable"}


def test_proxy_enso_asset_avoids_double_api_prefix_when_base_url_includes_api(monkeypatch) -> None:
    observed: dict[str, Any] = {}

    class DummyResponse:
        status_code = 200
        headers = {"content-type": "application/xml"}
        content = b"<Image />"
        text = ""

    class DummyClient:
        def __init__(self, *args, **kwargs):
            observed["timeout"] = kwargs.get("timeout")

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def get(self, url, params=None):
            observed["url"] = url
            observed["params"] = params
            return DummyResponse()

    monkeypatch.setenv("ENSO_API_BASE_URL", "http://127.0.0.1:8003/api")
    monkeypatch.setattr("services.pathology_assets.httpx.Client", DummyClient)

    payload = proxy_enso_asset(path="/api/slides/resolved-slide-id/dzi")

    assert payload.content == b"<Image />"
    assert payload.media_type.startswith("application/xml")
    assert observed["url"] == "http://127.0.0.1:8003/api/slides/resolved-slide-id/dzi"
    assert observed["params"] == {}


def test_proxy_enso_asset_keeps_api_prefix_when_base_url_has_no_path(monkeypatch) -> None:
    observed: dict[str, Any] = {}

    class DummyResponse:
        status_code = 200
        headers = {"content-type": "application/xml"}
        content = b"<Image />"
        text = ""

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def get(self, url, params=None):
            observed["url"] = url
            observed["params"] = params
            return DummyResponse()

    monkeypatch.setenv("ENSO_API_BASE_URL", "http://127.0.0.1:8003")
    monkeypatch.setattr("services.pathology_assets.httpx.Client", DummyClient)

    payload = proxy_enso_asset(path="/api/slides/resolved-slide-id/dzi")

    assert payload.content == b"<Image />"
    assert payload.media_type.startswith("application/xml")
    assert observed["url"] == "http://127.0.0.1:8003/api/slides/resolved-slide-id/dzi"
    assert observed["params"] == {}


def test_viewer_config_route_returns_resolved_urls(monkeypatch, client) -> None:
    monkeypatch.setattr(
        "routers.pathology.resolve_enso_slide_status",
        lambda _: EnsoSlideResolution(
            requested_slide_id=SLIDE_ID,
            resolved_slide_id="resolved-slide-id",
            deepzoom_available=True,
            unavailable_reason=None,
        ),
    )

    response = client.get(
        f"/v1/pathology/slides/{SLIDE_ID}/viewer-config"
        "?model_id=lung_stage&level=2&smooth=true&alpha_power=0.7"
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["slide_id"] == SLIDE_ID
    assert payload["enso_slide_id"] == "resolved-slide-id"
    assert payload["deepzoom_available"] is True
    assert payload["deepzoom_unavailable_reason"] is None
    assert payload["dzi_url"] == f"/v1/pathology/slides/{SLIDE_ID}/dzi"
    assert payload["tile_url_template"] == f"/v1/pathology/slides/{SLIDE_ID}/tile/{{level}}/{{tile_name}}"
    assert payload["attention_heatmap_url"] == f"/v1/pathology/slides/{SLIDE_ID}/attention-heatmap"
    assert payload["fallback_preview_url"] == f"/v1/pathology/slides/{SLIDE_ID}/preview/image"
    assert payload["fallback_heatmap_url"] == f"/v1/pathology/slides/{SLIDE_ID}/heatmap/image"
    assert payload["defaults"] == {
        "model_id": "lung_stage",
        "level": 2,
        "smooth": True,
        "alpha_power": 0.7,
    }


def test_viewer_config_route_marks_deepzoom_unavailable_when_enso_missing(
    monkeypatch,
    tmp_path,
    client,
) -> None:
    embeddings_dir = tmp_path / "embeddings"
    slide_dir = tmp_path / "slides"
    embeddings_dir.mkdir(parents=True)
    slide_dir.mkdir(parents=True)

    # local slide exists
    (slide_dir / f"{SLIDE_ID}.svs").write_bytes(b"svs")

    # unrelated embedding; requested slide is absent in Enso index
    (embeddings_dir / "TCGA-55-1234-01Z-00-DX1.alt.npy").write_bytes(b"")

    monkeypatch.setenv("PATHOLOGY_WSI_DIR", str(slide_dir))
    monkeypatch.setenv("ENSO_EMBEDDINGS_DIR", str(embeddings_dir))

    response = client.get(f"/v1/pathology/slides/{SLIDE_ID}/viewer-config")
    payload = response.json()

    assert response.status_code == 200
    assert payload["slide_id"] == SLIDE_ID
    assert payload["enso_slide_id"] == SLIDE_ID
    assert payload["deepzoom_available"] is False
    assert "not indexed" in (payload["deepzoom_unavailable_reason"] or "").lower()
    assert payload["fallback_preview_url"] is None
    assert payload["fallback_heatmap_url"] is None


def test_viewer_config_route_exposes_static_fallback_urls_when_heatmap_asset_exists(
    monkeypatch,
    tmp_path,
    client,
) -> None:
    embeddings_dir = tmp_path / "embeddings"
    heatmap_dir = tmp_path / "heatmaps"
    embeddings_dir.mkdir(parents=True)
    heatmap_dir.mkdir(parents=True)

    # unrelated embedding; requested slide is absent in Enso index
    (embeddings_dir / "TCGA-55-1234-01Z-00-DX1.alt.npy").write_bytes(b"")

    # local heatmap asset is available for static fallback mode
    (heatmap_dir / f"{SLIDE_ID}.png").write_bytes(b"fake-png")

    monkeypatch.setenv("ENSO_EMBEDDINGS_DIR", str(embeddings_dir))
    monkeypatch.setenv("PATHOLOGY_HEATMAP_DIR", str(heatmap_dir))

    response = client.get(f"/v1/pathology/slides/{SLIDE_ID}/viewer-config")
    payload = response.json()

    assert response.status_code == 200
    assert payload["deepzoom_available"] is False
    assert payload["fallback_preview_url"] == f"/v1/pathology/slides/{SLIDE_ID}/preview/image"
    assert payload["fallback_heatmap_url"] == f"/v1/pathology/slides/{SLIDE_ID}/heatmap/image"
