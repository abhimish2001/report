"""
conftest.py
Shared pytest fixtures for the smoke test suite.

Forces every test run onto an isolated, throwaway SQLite database and
throwaway output/upload directories, so tests never touch the real
SQL Server database or the real data/output folders on disk - no matter
whether a live SQL Server happens to be reachable in the environment.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_ROOT))

# Point at a deliberately unreachable SQL Server before any app/db module is
# imported, so DatabaseManager's startup probe fails fast and falls back to
# SQLite - tests must never depend on (or write into) a live SQL Server.
os.environ.setdefault("SQL_SERVER_HOST", "127.0.0.1")
os.environ.setdefault("SQL_SERVER_PORT", "1")
os.environ.setdefault("GEMINI_API_KEY", "")
os.environ.setdefault("LLM_API_KEY", "")

import pytest

DEMO_CSV_PATH = APP_ROOT / "TaskStatus-202608(Input File).csv"


@pytest.fixture(autouse=True)
def isolated_app_state(tmp_path, monkeypatch):
    """Redirects the database, exports, and upload temp dirs to a throwaway
    location for every test, and resets them so tests don't leak state into
    each other."""
    from modules import db as db_module
    import app as app_module

    sqlite_path = tmp_path / "test_resource_utilization.db"
    monkeypatch.setattr(db_module, "SQLITE_DB_PATH", str(sqlite_path))
    monkeypatch.setattr(db_module.db_mgr, "engine_type", "sqlite")

    output_dir = tmp_path / "output"
    upload_dir = tmp_path / "tmp_uploads"
    output_dir.mkdir()
    upload_dir.mkdir()
    monkeypatch.setattr(app_module, "OUTPUT_DIR", str(output_dir))
    monkeypatch.setattr(app_module, "UPLOAD_TMP_DIR", str(upload_dir))

    db_module.init_database()
    yield


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    import app as app_module

    with TestClient(app_module.app) as c:
        yield c


@pytest.fixture()
def demo_report_id(client) -> int:
    """Runs the /load-demo pipeline and returns the freshly created report id."""
    resp = client.get("/load-demo", follow_redirects=True)
    assert resp.status_code == 200
    assert "report_id=" in str(resp.url)
    return int(str(resp.url).split("report_id=")[-1])
