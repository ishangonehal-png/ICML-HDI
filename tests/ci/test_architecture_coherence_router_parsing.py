from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CHECK_SCRIPT_PATH = REPO_ROOT / "scripts" / "ci" / "check_architecture_coherence.py"


def _load_check_architecture_coherence_module():
    spec = importlib.util.spec_from_file_location(
        "_check_architecture_coherence_module",
        CHECK_SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_backend_endpoint_parser_supports_multiple_router_variables(tmp_path: Path) -> None:
    check_architecture_coherence = _load_check_architecture_coherence_module()

    routers_dir = tmp_path / "routers"
    routers_dir.mkdir(parents=True, exist_ok=True)
    (routers_dir / "multi.py").write_text(
        "\n".join(
            [
                "from fastapi import APIRouter",
                "",
                'uploads_router = APIRouter(prefix="/uploads")',
                'analysis_router = APIRouter(prefix="/analysis")',
                "",
                '@uploads_router.post("/files")',
                "def upload_files() -> dict[str, str]:",
                '    return {"status": "ok"}',
                "",
                '@analysis_router.get("/jobs/{job_id}")',
                "def get_job(job_id: str) -> dict[str, str]:",
                '    return {"job_id": job_id}',
                "",
            ]
        ),
        encoding="utf-8",
    )

    check_architecture_coherence.API_ROUTERS_DIR = routers_dir
    endpoints = check_architecture_coherence._extract_backend_route_endpoints()

    assert ("POST", "/v1/uploads/files") in endpoints
    assert ("GET", "/v1/analysis/jobs/{job_id}") in endpoints
