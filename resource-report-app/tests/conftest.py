"""
conftest.py
Shared pytest fixtures for the SQL Server-only test suite.

There is no SQLite fallback anywhere in this application, so the suite cannot
isolate itself with a throwaway file database. Instead every test run is
pointed at a dedicated, disposable database (default
`ResourceUtilizationDB_test`) on the same Microsoft SQL Server configured in
`resource-report-app/.env`, created on demand. The schema is rebuilt and the
transactional tables are wiped before and after every test, so tests never
leave state behind and never touch the real `ResourceUtilizationDB`.

Safety rails:
- `TEST_SQL_SERVER_DATABASE` must contain the word "test", so the suite can
  never be accidentally pointed at a production database.
- If SQL Server is unreachable, only the tests that need a database are
  skipped; the pure unit tests (calculator, column_mapper, variance_engine,
  ai_insights) still run.
- `GEMINI_API_KEY` is forced blank so the route-level suite stays
  deterministic and network-free (test_ai_insights_live.py reads the key
  straight from .env instead).
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_ROOT))

DEMO_CSV_PATH = APP_ROOT / "TaskStatus-202608(Input File).csv"

TEST_DB_NAME = os.environ.get("TEST_SQL_SERVER_DATABASE", "ResourceUtilizationDB_test").strip()
if "test" not in TEST_DB_NAME.lower():
    raise RuntimeError(
        "TEST_SQL_SERVER_DATABASE must contain the word 'test' so the suite "
        f"can never wipe a production database (got {TEST_DB_NAME!r})."
    )

# Must be set before anything imports modules.db / app, because those call
# load_dotenv() and an already-present key wins (override=False).
os.environ["SQL_SERVER_DATABASE"] = TEST_DB_NAME
os.environ["GEMINI_API_KEY"] = ""
os.environ["LLM_API_KEY"] = ""

import pytest  # noqa: E402

TEST_EMAIL = "qa.tl@example.com"
TEST_PASSWORD = "qa-TL-password-123"

_IDENT_RE = re.compile(r"^[A-Za-z0-9_]+$")


def _connect_to(database: str):
    """Opens a raw connection to `database`, temporarily overriding the env var."""
    from modules import db as db_module

    previous = os.environ.get("SQL_SERVER_DATABASE")
    os.environ["SQL_SERVER_DATABASE"] = database
    try:
        return db_module.get_connection()
    finally:
        if previous is None:
            os.environ.pop("SQL_SERVER_DATABASE", None)
        else:
            os.environ["SQL_SERVER_DATABASE"] = previous


def _ensure_test_database() -> None:
    """Creates the disposable test database if it does not exist yet.

    Raises if SQL Server itself is unreachable, which the fixture converts into
    a skip for the database-backed tests only.
    """
    target = os.environ["SQL_SERVER_DATABASE"]
    if not _IDENT_RE.match(target):
        raise RuntimeError(f"Unsafe TEST_SQL_SERVER_DATABASE name: {target!r}")

    # Fast path: the database already exists and we can reach it.
    try:
        conn = _connect_to(target)
        conn.close()
        return
    except Exception:
        pass

    # Slow path: create it through the `master` catalog.
    # get_connection() opens with autocommit=False, which puts SQL Server into
    # implicit-transaction mode - CREATE DATABASE is illegal there (error 226),
    # so flip autocommit on for this DDL-only connection.
    conn = _connect_to("master")
    try:
        conn.autocommit = True
        conn.cursor().execute(f"IF DB_ID(N'{target}') IS NULL CREATE DATABASE [{target}]")
    finally:
        conn.close()

    conn = _connect_to(target)
    conn.close()


def _reset_schema() -> None:
    from modules import db as db_module

    os.environ["SQL_SERVER_DATABASE"] = TEST_DB_NAME
    db_module.init_database()
    db_module.clear_all_data()


@pytest.fixture()
def db_state(tmp_path, monkeypatch):
    """Builds a clean, empty test database and redirects all file output into tmp.

    Requested by every fixture that talks to the database, so pure unit tests
    that never ask for a database still run even when SQL Server is offline.
    """
    import app as app_module

    try:
        _ensure_test_database()
    except Exception as exc:
        pytest.skip(f"SQL Server unavailable, skipping database-backed test: {exc}")

    _reset_schema()

    output_root = tmp_path / "output"
    data_root = tmp_path / "data"
    directories = {
        "OUTPUT_DIR": output_root,
        "EXCEL_DIR": output_root / "excel",
        "PDF_DIR": output_root / "pdf",
        "UPLOADS_DIR": data_root / "uploads",
        "UPLOAD_TMP_DIR": data_root / "tmp_uploads",
    }
    for attr, path in directories.items():
        path.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(app_module, attr, str(path))

    yield

    try:
        _reset_schema()
    except Exception:
        pass


def _delete_user(email: str) -> None:
    """Removes a user and their sessions so auth tests are repeatable."""
    from modules import db as db_module

    conn = _connect_to(TEST_DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM user_sessions WHERE user_id IN (SELECT id FROM users WHERE email = ?)",
            (email,),
        )
        cursor.execute("DELETE FROM users WHERE email = ?", (email,))
        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def delete_user(db_state):
    """Callable fixture: delete_user('someone@example.com')."""
    return _delete_user


@pytest.fixture()
def client(db_state):
    """Authenticated TestClient logged in as a TL, via the real /login route."""
    from fastapi.testclient import TestClient
    from modules import auth
    import app as app_module

    _delete_user(TEST_EMAIL)
    auth.create_user(TEST_EMAIL, "QA Team Lead", TEST_PASSWORD, "TL")

    with TestClient(app_module.app) as c:
        resp = c.post(
            "/login",
            data={"email": TEST_EMAIL, "password": TEST_PASSWORD},
            follow_redirects=False,
        )
        assert resp.status_code == 303, f"login failed: {resp.status_code} {resp.text[:300]}"
        assert c.cookies.get("session_id"), "login response did not set session_id"
        yield c


@pytest.fixture()
def anon_client(db_state):
    """Unauthenticated TestClient, for asserting the auth guards."""
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
