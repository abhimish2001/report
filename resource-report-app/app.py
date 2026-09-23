"""
app.py
FastAPI application entrypoint for the Team Resource Utilization Reporting System.
Key Features:
- Direct, open access without login/admin barriers
- Multi-cadence timesheet ingestion (Daily, Weekly, Monthly, Consolidated)
- Zero-baseline initial static dashboard KPIs (0 tasks, 0.0 hrs, 0.0% util)
- Automated report generation styled after Sample-1.html and Sample-2.html
- Gemini AI executive insights and management action synthesis
- Microsoft SQL Server primary database with resilient SQLite fallback
- 4-Sheet Excel and Executive PDF exports
"""

from __future__ import annotations
import datetime
import os
import shutil
import uuid
import threading
from typing import Any, Dict, List, Optional
import fastapi
from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import pandas as pd
import uvicorn

EXPORT_LOCK = threading.Lock()

from modules.excel_reader import load_uploaded_files, read_file_to_dataframe, extract_file_preview
from modules.column_mapper import detect_column_mappings, map_dataframe_to_schema
from modules.normalizer import run_normalization_pipeline
from modules.calculator import calculate_aggregates, get_empty_aggregates
from modules.variance_engine import analyze_variances
from modules.ai_insights import generate_ai_insights
from modules.excel_exporter import create_styled_workbook
from modules.pdf_exporter import generate_pdf_report
from modules.db import (
    init_database,
    save_session_data,
    get_latest_report,
    get_report_by_id,
    get_all_reports,
    check_db_health,
    clear_all_data
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
UPLOAD_TMP_DIR = os.path.join(DATA_DIR, "tmp_uploads")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(UPLOAD_TMP_DIR, exist_ok=True)

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize database tables cleanly without auto-seeding demo data
    init_database()
    yield

app = FastAPI(title="Team Resource Utilization Reporting System", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

FAVICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="32" height="32">
  <defs>
    <linearGradient id="grad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#2563eb"/>
      <stop offset="100%" stop-color="#1e3a8a"/>
    </linearGradient>
  </defs>
  <rect width="32" height="32" rx="7" fill="url(#grad)"/>
  <path d="M7 21V11a2 2 0 0 1 1-1.73l7-4a2 2 0 0 1 2 0l7 4A2 2 0 0 1 25 11v10a2 2 0 0 1-1 1.73l-7 4a2 2 0 0 1-2 0l-7-4A2 2 0 0 1 7 21z" fill="none" stroke="#ffffff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>
  <polyline points="7.27 10.96 16 16.01 24.73 10.96" fill="none" stroke="#ffffff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>
  <line x1="16" y1="26.08" x2="16" y2="16" stroke="#ffffff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>
</svg>"""

@app.get("/favicon.ico", include_in_schema=False)
def favicon_endpoint():
    return Response(content=FAVICON_SVG, media_type="image/svg+xml")


# ─── CORE VIEWS & REPORT DASHBOARD ─────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def index_view(request: Request):
    return dashboard_view(request)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard_view(request: Request, report_id: Optional[int] = None):
    """
    Renders executive dashboard. If no report is found or database was reset,
    renders static zeroed-out KPIs and empty breakdown states.
    """
    report = None
    if report_id:
        report = get_report_by_id(report_id)
    else:
        report = get_latest_report()

    if report:
        summary_data = report["summary"]
        variance_data = report["variance"]
        ai_insights = report.get("ai_insights", {})
        active_report_id = report["id"]
        files_count = len(summary_data.get("by_employee", [])) or 1
    else:
        # Zero baseline initial state
        summary_data = get_empty_aggregates()
        variance_data = {
            "top_overutilized": [],
            "top_underutilized": [],
            "distribution": {},
            "overload_threshold_pct": 100.0
        }
        ai_insights = {}
        active_report_id = 0
        files_count = 0

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "active_page": "dashboard",
            "report_id": active_report_id,
            "aggregates": summary_data,
            "variance_data": variance_data,
            "ai_insights": ai_insights,
            "files_count": files_count
        }
    )


@app.get("/upload", response_class=HTMLResponse)
def upload_view(request: Request, error: Optional[str] = None):
    return templates.TemplateResponse(
        request=request,
        name="upload.html",
        context={
            "active_page": "upload",
            "error_msg": error
        }
    )


@app.post("/upload")
async def handle_upload(
    request: Request,
    files: List[UploadFile] = File(...),
    cadence: str = Form("weekly")
):
    """Processes uploaded sheet(s) and automatically compiles utilization report."""
    valid_files = [f for f in files if f.filename and f.filename.strip()]

    if not valid_files:
        return RedirectResponse("/upload?error=Please+select+at+least+one+valid+file", status_code=303)

    session_id = str(uuid.uuid4())
    session_dir = os.path.join(UPLOAD_TMP_DIR, session_id)
    os.makedirs(session_dir, exist_ok=True)

    loaded_dfs: List[pd.DataFrame] = []
    files_meta: List[Dict[str, Any]] = []

    for f in valid_files:
        saved_path = os.path.join(session_dir, f.filename)
        file_bytes = await f.read()
        with open(saved_path, "wb") as out_f:
            out_f.write(file_bytes)

        try:
            df = read_file_to_dataframe(saved_path, f.filename)
            preview = extract_file_preview(df, f.filename)
            files_meta.append(preview)

            mapped_df, _, _ = map_dataframe_to_schema(
                df,
                default_employee=preview.get("detected_employee")
            )
            loaded_dfs.append(mapped_df)
        except Exception as e:
            return RedirectResponse(f"/upload?error=Error+reading+{f.filename}:+{str(e)}", status_code=303)

    combined_df = pd.concat(loaded_dfs, ignore_index=True)
    normalized_df, norm_log, _ = run_normalization_pipeline(combined_df)

    aggregates = calculate_aggregates(normalized_df)
    variance_data = analyze_variances(aggregates, overload_threshold_pct=100.0)
    ai_insights = generate_ai_insights(aggregates, variance_data)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    excel_filename = f"Resource_Utilization_Report_{timestamp}.xlsx"
    pdf_filename = f"Resource_Utilization_Report_{timestamp}.pdf"
    excel_path = os.path.join(OUTPUT_DIR, excel_filename)
    pdf_path = os.path.join(OUTPUT_DIR, pdf_filename)

    create_styled_workbook(aggregates, variance_data, excel_path)
    generate_pdf_report(aggregates, variance_data, ai_insights, pdf_path)

    report_id = save_session_data(
        session_id=session_id,
        uploads_info=files_meta,
        normalized_df=normalized_df,
        norm_log=norm_log,
        aggregates=aggregates,
        variance_data=variance_data,
        ai_insights=ai_insights,
        excel_path=excel_path,
        pdf_path=pdf_path,
        cadence=cadence
    )

    return RedirectResponse(f"/dashboard?report_id={report_id}", status_code=303)


@app.get("/load-demo")
def load_demo_dataset():
    """Manual one-click demo loader using the August 2026 reference file."""
    demo_file = os.path.join(BASE_DIR, "TaskStatus-202608(Input File).csv")
    if not os.path.exists(demo_file):
        return RedirectResponse("/upload?error=Demo+file+not+found", status_code=303)

    session_id = str(uuid.uuid4())
    df_raw = read_file_to_dataframe(demo_file, "TaskStatus-202608(Input File).csv")
    preview = extract_file_preview(df_raw, "TaskStatus-202608(Input File).csv")
    mapped_df, _, _ = map_dataframe_to_schema(df_raw)
    normalized_df, norm_log, _ = run_normalization_pipeline(mapped_df)
    aggregates = calculate_aggregates(normalized_df)
    variance_data = analyze_variances(aggregates, overload_threshold_pct=100.0)
    ai_insights = generate_ai_insights(aggregates, variance_data)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    excel_filename = f"Resource_Utilization_Report_{timestamp}.xlsx"
    pdf_filename = f"Resource_Utilization_Report_{timestamp}.pdf"
    excel_path = os.path.join(OUTPUT_DIR, excel_filename)
    pdf_path = os.path.join(OUTPUT_DIR, pdf_filename)

    create_styled_workbook(aggregates, variance_data, excel_path)
    generate_pdf_report(aggregates, variance_data, ai_insights, pdf_path)

    report_id = save_session_data(
        session_id=session_id,
        uploads_info=[preview],
        normalized_df=normalized_df,
        norm_log=norm_log,
        aggregates=aggregates,
        variance_data=variance_data,
        ai_insights=ai_insights,
        excel_path=excel_path,
        pdf_path=pdf_path,
        cadence="consolidated"
    )

    return RedirectResponse(f"/dashboard?report_id={report_id}", status_code=303)


@app.post("/api/regenerate-ai")
def regenerate_ai_endpoint(report_id: int = Form(...), gemini_api_key: str = Form(...)):
    """Regenerates AI insights using provided Gemini API Key."""
    report = get_report_by_id(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found.")

    aggregates = report["summary"]
    variance_data = report["variance"]
    ai_insights = generate_ai_insights(aggregates, variance_data, api_key=gemini_api_key.strip())

    from modules.db import db_mgr
    conn = db_mgr.get_raw_connection()
    try:
        import json
        cursor = conn.cursor()
        cursor.execute("UPDATE reports SET ai_insights_json = ? WHERE id = ?", (json.dumps(ai_insights), report_id))
        conn.commit()
    finally:
        conn.close()

    return RedirectResponse(f"/dashboard?report_id={report_id}", status_code=303)


@app.get("/trends", response_class=HTMLResponse)
def trends_view(request: Request):
    reports = get_all_reports()
    return templates.TemplateResponse(
        request=request,
        name="trends.html",
        context={
            "active_page": "trends",
            "reports": reports
        }
    )


@app.post("/reset-db")
def reset_db_endpoint():
    """Fully clears database and returns to zero-state dashboard."""
    clear_all_data()
    return RedirectResponse("/dashboard", status_code=303)


@app.get("/export/excel/{report_id}")
def export_excel_download(report_id: int):
    if report_id <= 0:
        raise HTTPException(status_code=400, detail="No active report available to export. Please upload a timesheet first.")
    report = get_report_by_id(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Excel export not found.")

    excel_path = report.get("excel_path")
    if not excel_path:
        excel_path = os.path.join(OUTPUT_DIR, f"Resource_Utilization_Report_{report_id}.xlsx")

    with EXPORT_LOCK:
        if not os.path.exists(excel_path) or os.path.getsize(excel_path) < 10000:
            create_styled_workbook(report["summary"], report["variance"], excel_path)

        with open(excel_path, "rb") as f:
            file_bytes = f.read()

    filename = os.path.basename(excel_path)
    return Response(
        content=file_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@app.get("/export/pdf/{report_id}")
def export_pdf_download(report_id: int):
    if report_id <= 0:
        raise HTTPException(status_code=400, detail="No active report available to export. Please upload a timesheet first.")
    report = get_report_by_id(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="PDF export not found.")

    pdf_path = report.get("pdf_path")
    if not pdf_path or not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail="PDF export not found.")

    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()

    filename = os.path.basename(pdf_path)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@app.get("/health", tags=["Monitoring"])
def healthcheck():
    db_status = check_db_health()
    reports = get_all_reports()
    return {
        "status": "healthy",
        "service": "Team Resource Utilization Reporting System",
        "timestamp": datetime.datetime.now().isoformat(),
        "database": db_status,
        "total_reports": len(reports)
    }


if __name__ == "__main__":
    print("Starting Team Resource Utilization Reporting System...")
    print("Open your browser and navigate to: http://localhost:8000")
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
