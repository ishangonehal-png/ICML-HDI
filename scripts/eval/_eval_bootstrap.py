"""
Bootstrap module: sets up sys.path and mocks heavy dependencies (DB, Redis, psycopg)
so the API services can be imported and called without a live Postgres/Redis instance.

Import this module FIRST in every eval script before any API service imports.
"""
from __future__ import annotations

import os
import sys
import types
import unittest.mock as mock

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def setup(repo_root: str = _REPO_ROOT) -> None:
    """Call once at the top of each eval script."""
    # ── sys.path ──────────────────────────────────────────────────────────────
    api_path = os.path.join(repo_root, "apps", "api")
    schemas_path = os.path.join(repo_root, "packages", "schemas")
    for p in (api_path, schemas_path):
        if p not in sys.path:
            sys.path.insert(0, p)

    # ── Redis mock ────────────────────────────────────────────────────────────
    if "redis" not in sys.modules:
        redis_mod = types.ModuleType("redis")
        redis_mod.Redis = mock.MagicMock()
        redis_ex = types.ModuleType("redis.exceptions")
        redis_ex.RedisError = Exception
        redis_ex.ConnectionError = Exception
        redis_ex.TimeoutError = Exception
        redis_mod.exceptions = redis_ex
        sys.modules["redis"] = redis_mod
        sys.modules["redis.exceptions"] = redis_ex

    # ── psycopg mock ──────────────────────────────────────────────────────────
    if "psycopg" not in sys.modules:
        sys.modules["psycopg"] = mock.MagicMock()

    # ── DB mock ───────────────────────────────────────────────────────────────
    if "db" not in sys.modules:
        db_mod = types.ModuleType("db")
        db_session_mod = types.ModuleType("db.session")
        db_session_mod.SessionLocal = mock.MagicMock()
        db_session_mod.engine = mock.MagicMock()
        db_session_mod.get_db = mock.MagicMock()
        db_session_mod.init_db = mock.MagicMock()
        db_base_mod = types.ModuleType("db.base")
        db_base_mod.Base = mock.MagicMock()
        sys.modules["db"] = db_mod
        sys.modules["db.session"] = db_session_mod
        sys.modules["db.base"] = db_base_mod

    # ── models mock ───────────────────────────────────────────────────────────
    if "models" not in sys.modules:
        models_mod = types.ModuleType("models")
        for attr in ("Case", "File", "ModalityResult", "UploadSession", "AnalysisJob", "JobEvent"):
            setattr(models_mod, attr, mock.MagicMock())
        sys.modules["models"] = models_mod
        sys.modules["models.core"] = mock.MagicMock()

    # ── working directory ─────────────────────────────────────────────────────
    os.chdir(repo_root)
