"""
test_smoke.py
End-to-end smoke tests for every route in app.py.

These exercise the same paths that were manually verified during the
schema-drift bug investigation (report_id=1/2 500 errors from stale SQL
Server columns): health, dashboard zero-state, real file upload, the
demo pipeline, exports, AI regeneration, and reset. A future column
added to any table without a matching migration in modules/db.py would
have been caught immediately by test_load_demo_full_pipeline and
test_upload_real_file instead of requiring a manual click-through.
"""

from __future__ import annotations

from pathlib import Path

DEMO_CSV_PATH = Path(__file__).resolve().parent.parent / "TaskStatus-202608(Input File).csv"


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "healthy"
    assert "database" in body
    assert body["total_reports"] == 0


def test_dashboard_zero_state(client):
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    assert "Awaiting Timesheet" in resp.text or "No Data" in resp.text


def test_upload_page_loads(client):
    resp = client.get("/upload")
    assert resp.status_code == 200


def test_trends_page_loads_with_no_reports(client):
    resp = client.get("/trends")
    assert resp.status_code == 200


def test_favicon(client):
    resp = client.get("/favicon.ico")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/svg+xml")


def test_load_demo_full_pipeline(client, demo_report_id):
    """Exercises ingest -> normalize -> aggregate -> AI insights -> export -> DB save."""
    resp = client.get(f"/dashboard?report_id={demo_report_id}")
    assert resp.status_code == 200
    assert "Executive" in resp.text

    health = client.get("/health").json()
    assert health["total_reports"] == 1


def test_upload_real_file(client):
    assert DEMO_CSV_PATH.exists(), f"Fixture file missing: {DEMO_CSV_PATH}"
    with open(DEMO_CSV_PATH, "rb") as f:
        resp = client.post(
            "/upload",
            files={"files": (DEMO_CSV_PATH.name, f, "text/csv")},
            data={"cadence": "weekly"},
            follow_redirects=True,
        )
    assert resp.status_code == 200
    assert "report_id=" in str(resp.url)


def test_upload_empty_file_is_rejected_not_crashed(client):
    resp = client.post(
        "/upload",
        files={"files": ("empty.csv", b"", "text/csv")},
        data={"cadence": "weekly"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "error" in resp.headers["location"]


def test_upload_with_empty_filename_returns_422(client):
    """A file part with an empty filename is parsed by Starlette as a plain
    string, not an UploadFile, so FastAPI's own validation rejects it with a
    422 before app.py's friendly "Please select at least one valid file"
    handler ever runs - the valid_files filter in handle_upload is dead code
    for this input shape. Documenting the actual behavior here rather than
    the intended one so a regression (or a fix) shows up as a visible diff."""
    resp = client.post(
        "/upload",
        files={"files": ("", b"", "application/octet-stream")},
        data={"cadence": "weekly"},
        follow_redirects=False,
    )
    assert resp.status_code == 422


def test_export_excel(client, demo_report_id):
    resp = client.get(f"/export/excel/{demo_report_id}")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert len(resp.content) > 1000


def test_export_pdf(client, demo_report_id):
    resp = client.get(f"/export/pdf/{demo_report_id}")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert len(resp.content) > 1000


def test_export_excel_missing_report_404(client):
    resp = client.get("/export/excel/9999")
    assert resp.status_code == 404


def test_export_pdf_missing_report_404(client):
    resp = client.get("/export/pdf/9999")
    assert resp.status_code == 404


def test_export_excel_zero_id_400(client):
    resp = client.get("/export/excel/0")
    assert resp.status_code == 400


def test_regenerate_ai_with_bad_key_falls_back_gracefully(client, demo_report_id):
    """An invalid API key must degrade to the rule-based fallback, not crash the request."""
    resp = client.post(
        "/api/regenerate-ai",
        data={"report_id": demo_report_id, "gemini_api_key": "not-a-real-key"},
        follow_redirects=True,
    )
    assert resp.status_code == 200


def test_regenerate_ai_missing_report_404(client):
    resp = client.post(
        "/api/regenerate-ai",
        data={"report_id": 9999, "gemini_api_key": "irrelevant"},
        follow_redirects=False,
    )
    assert resp.status_code == 404


def test_reset_db_returns_to_zero_state(client, demo_report_id):
    resp = client.post("/reset-db", follow_redirects=True)
    assert resp.status_code == 200
    assert "Awaiting Timesheet" in resp.text or "No Data" in resp.text

    health = client.get("/health").json()
    assert health["total_reports"] == 0


def test_trends_page_after_demo_report(client, demo_report_id):
    resp = client.get("/trends")
    assert resp.status_code == 200
    assert f"report_id={demo_report_id}" in resp.text
