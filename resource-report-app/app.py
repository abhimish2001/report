"""
app.py
FastAPI application entrypoint for the Team Resource Utilization Reporting System.
Provides routes for multi-file upload, column mapping & normalization audit,
interactive dashboard, Excel export, and PDF download.
"""

from __future__ import annotations
import datetime
import os
import shutil
import uuid
import threading
from typing import Any, Dict, List, Optional
import fastapi
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import pandas as pd
import uvicorn

EXPORT_LOCK = threading.Lock()

from modules.excel_reader import load_uploaded_files, read_file_to_dataframe, extract_file_preview
from modules.column_mapper import detect_column_mappings, map_dataframe_to_schema
from modules.normalizer import run_normalization_pipeline
from modules.calculator import calculate_aggregates
from modules.variance_engine import analyze_variances
from modules.ai_insights import generate_ai_insights
from modules.excel_exporter import create_styled_workbook
from modules.pdf_exporter import generate_pdf_report
from modules.db import init_database, save_session_data, get_latest_report, get_report_by_id

# Directory setups
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
UPLOAD_TMP_DIR = os.path.join(DATA_DIR, "tmp_uploads")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(UPLOAD_TMP_DIR, exist_ok=True)

# In-memory session cache for multi-step wizard state
SESSION_CACHE: Dict[str, Dict[str, Any]] = {}

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_database()
    ensure_default_report()
    yield

app = FastAPI(title="Team Resource Utilization Reporting System", lifespan=lifespan)

# Mount static files & Jinja templates
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# Embedded SVG Favicon
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
    """Serves high-resolution application SVG favicon."""
    return Response(content=FAVICON_SVG, media_type="image/svg+xml")

@app.get("/health", tags=["Monitoring"])
def healthcheck():
    """Application health and database connectivity probe."""
    from modules.db import get_all_reports
    reports = get_all_reports()
    return {
        "status": "healthy",
        "service": "Team Resource Utilization Reporting System",
        "timestamp": datetime.datetime.now().isoformat(),
        "database": "connected (WAL mode)",
        "total_reports": len(reports)
    }

@app.exception_handler(404)
async def custom_404_handler(request: Request, exc):
    return templates.TemplateResponse(
        request=request,
        name="error.html",
        context={
            "active_page": "",
            "status_code": 404,
            "error_title": "Page or Report Not Found",
            "error_message": "The requested report, URL, or resource does not exist or has been relocated."
        },
        status_code=404
    )

@app.exception_handler(500)
async def custom_500_handler(request: Request, exc):
    return templates.TemplateResponse(
        request=request,
        name="error.html",
        context={
            "active_page": "",
            "status_code": 500,
            "error_title": "Internal Processing Error",
            "error_message": "A server-side error occurred. Please verify your file structure or reload the application."
        },
        status_code=500
    )


def ensure_default_report() -> Optional[Dict[str, Any]]:
    """Ensures at least one consolidated report exists in the database on launch."""
    latest = get_latest_report()
    if latest:
        return latest

    candidate_paths = [
        os.path.join(r"c:\Users\am273\Downloads\Report-20260911T164327Z-1-001\Report", "TaskStatus-202608(Input File).csv"),
        os.path.join(BASE_DIR, "TaskStatus-202608(Input File).csv"),
    ]
    demo_file = None
    for cp in candidate_paths:
        if os.path.exists(cp):
            demo_file = cp
            break

    if not demo_file:
        return None

    try:
        df_raw = read_file_to_dataframe(demo_file, "TaskStatus-202608(Input File).csv")
        preview = extract_file_preview(df_raw, "TaskStatus-202608(Input File).csv")
        mapped_df, _, _ = map_dataframe_to_schema(df_raw)
        normalized_df, norm_log, flagged_rows = run_normalization_pipeline(mapped_df)
        aggregates = calculate_aggregates(normalized_df)
        variance_data = analyze_variances(aggregates, overload_threshold_pct=110.0)
        ai_insights = generate_ai_insights(aggregates, variance_data)

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        excel_filename = f"Resource_Utilization_Report_{timestamp}.xlsx"
        pdf_filename = f"Resource_Utilization_Report_{timestamp}.pdf"
        excel_path = os.path.join(OUTPUT_DIR, excel_filename)
        pdf_path = os.path.join(OUTPUT_DIR, pdf_filename)
        create_styled_workbook(aggregates, variance_data, excel_path)
        generate_pdf_report(aggregates, variance_data, ai_insights, pdf_path)

        save_session_data(
            session_id=str(uuid.uuid4()),
            uploads_info=[preview],
            normalized_df=normalized_df,
            norm_log=norm_log,
            aggregates=aggregates,
            variance_data=variance_data,
            ai_insights=ai_insights,
            excel_path=excel_path,
            pdf_path=pdf_path
        )
        return get_latest_report()
    except Exception as e:
        print(f"Error initializing demo report: {e}")
        return None


@app.get("/", response_class=HTMLResponse)
def index_view(request: Request):
    """Directly loads the executive dashboard with analytics and KPIs."""
    return dashboard_view(request)


@app.get("/upload", response_class=HTMLResponse)
def upload_view(request: Request, error: Optional[str] = None):
    """Upload custom employee sheets."""
    return templates.TemplateResponse(
        request=request,
        name="upload.html",
        context={
            "active_page": "upload",
            "error_msg": error
        }
    )


@app.get("/load-demo")
def load_demo_dataset():
    """Quick one-click demo loader using the August 2026 reference file."""
    # Look for reference file in known paths
    candidate_paths = [
        os.path.join(r"c:\Users\am273\Downloads\Report-20260911T164327Z-1-001\Report", "TaskStatus-202608(Input File).csv"),
        os.path.join(BASE_DIR, "TaskStatus-202608(Input File).csv"),
    ]
    demo_file = None
    for cp in candidate_paths:
        if os.path.exists(cp):
            demo_file = cp
            break

    if not demo_file:
        return RedirectResponse("/?error=Reference+demo+file+not+found", status_code=303)

    session_id = str(uuid.uuid4())
    df_raw = read_file_to_dataframe(demo_file, "TaskStatus-202608(Input File).csv")
    preview = extract_file_preview(df_raw, "TaskStatus-202608(Input File).csv")

    col_mappings = detect_column_mappings(list(df_raw.columns))
    mapped_df, _, _ = map_dataframe_to_schema(df_raw)
    normalized_df, norm_log, flagged_rows = run_normalization_pipeline(mapped_df)

    SESSION_CACHE[session_id] = {
        "files_meta": [preview],
        "mapped_df": mapped_df,
        "normalized_df": normalized_df,
        "column_mappings": col_mappings,
        "normalization_log": norm_log,
        "flagged_rows": flagged_rows,
        "config": {
            "overload_threshold": 110.0,
            "nominal_capacity": None,
            "llm_api_key": "AIzaSyB0oFRGrHDg8fJgTwJIiavfialaSp7yMao",
            "llm_model": "gemini-3.6-flash",
            "llm_base_url": "https://generativelanguage.googleapis.com/v1beta/openai"
        }
    }

    return RedirectResponse(f"/review?session_id={session_id}", status_code=303)


@app.post("/upload")
async def handle_upload(
    request: Request,
    files: List[UploadFile] = File(...),
    team_preset: str = Form("universal"),
    entity_label: str = Form("Service"),
    overload_threshold: float = Form(110.0),
    nominal_capacity: Optional[str] = Form(None),
    llm_api_key: Optional[str] = Form("AIzaSyB0oFRGrHDg8fJgTwJIiavfialaSp7yMao"),
    llm_model: Optional[str] = Form("gemini-3.6-flash"),
    llm_base_url: Optional[str] = Form("https://generativelanguage.googleapis.com/v1beta/openai")
):
    """Processes uploaded files and builds pre-calculation state."""
    valid_files = [f for f in files if f.filename and f.filename.strip()]
    if not valid_files:
        return RedirectResponse("/upload?error=Please+select+at+least+one+valid+file", status_code=303)

    # Allowed extensions whitelist
    allowed_exts = {".xlsx", ".xls", ".csv"}
    for f in valid_files:
        _, ext = os.path.splitext(f.filename.lower())
        if ext not in allowed_exts:
            return RedirectResponse(
                f"/upload?error=Unsupported+file+format+for+'{f.filename}'.+Allowed+formats+are+.xlsx,+.xls,+and+.csv",
                status_code=303
            )

    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB limit
    session_id = str(uuid.uuid4())
    session_dir = os.path.join(UPLOAD_TMP_DIR, session_id)
    os.makedirs(session_dir, exist_ok=True)

    loaded_dfs: List[pd.DataFrame] = []
    files_meta: List[Dict[str, Any]] = []

    for f in valid_files:
        file_bytes = await f.read()
        if len(file_bytes) > MAX_FILE_SIZE:
            return RedirectResponse(
                f"/upload?error=File+'{f.filename}'+exceeds+the+maximum+allowed+upload+size+of+50MB",
                status_code=303
            )
        saved_path = os.path.join(session_dir, f.filename)
        with open(saved_path, "wb") as out_f:
            out_f.write(file_bytes)

    # Auto-detect if user uploaded an existing consolidated 4-sheet report
    if len(valid_files) == 1:
        first_f = valid_files[0]
        first_path = os.path.join(session_dir, first_f.filename)
        from modules.report_reader import is_consolidated_report_file, parse_consolidated_report
        if is_consolidated_report_file(first_path, first_f.filename):
            try:
                aggregates, variance_data = parse_consolidated_report(first_path, first_f.filename)
                ai_insights = generate_ai_insights(aggregates, variance_data)
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                excel_filename = f"Resource_Utilization_Report_{timestamp}.xlsx"
                pdf_filename = f"Resource_Utilization_Report_{timestamp}.pdf"
                excel_path = os.path.join(OUTPUT_DIR, excel_filename)
                pdf_path = os.path.join(OUTPUT_DIR, pdf_filename)
                create_styled_workbook(aggregates, variance_data, excel_path)
                generate_pdf_report(aggregates, variance_data, ai_insights, pdf_path)

                dummy_df = pd.DataFrame(aggregates.get("cross_tab", []))
                report_id = save_session_data(
                    session_id=session_id,
                    uploads_info=[{"filename": first_f.filename, "row_count": aggregates["totals"]["tasks"], "columns": []}],
                    normalized_df=dummy_df,
                    norm_log=[],
                    aggregates=aggregates,
                    variance_data=variance_data,
                    ai_insights=ai_insights,
                    excel_path=excel_path,
                    pdf_path=pdf_path
                )
                return RedirectResponse(f"/dashboard?report_id={report_id}", status_code=303)
            except Exception as e:
                import traceback
                print(f"[ERROR] Direct consolidated report parsing failed: {e}", flush=True)
                traceback.print_exc()

    for f in valid_files:
        saved_path = os.path.join(session_dir, f.filename)
        try:
            df = read_file_to_dataframe(saved_path, f.filename)
            preview = extract_file_preview(df, f.filename)
            files_meta.append(preview)

            # Map columns per file to canonical schema
            mapped_df, _, _ = map_dataframe_to_schema(df, default_employee=preview.get("detected_employee"))
            loaded_dfs.append(mapped_df)
        except Exception as e:
            return RedirectResponse(f"/?error=Error+reading+{f.filename}:+{str(e)}", status_code=303)

    # Consolidate all uploaded DataFrames into one unified dataset
    combined_df = pd.concat(loaded_dfs, ignore_index=True)

    # Initial normalization run
    normalized_df, norm_log, flagged_rows = run_normalization_pipeline(combined_df)

    # Global column mappings representation
    all_raw_cols = []
    for fm in files_meta:
        all_raw_cols.extend(fm.get("columns", []))
    col_mappings = detect_column_mappings(list(set(all_raw_cols)))

    nom_cap = float(nominal_capacity) if nominal_capacity and nominal_capacity.strip() else None

    # Determine clean entity label
    clean_entity_label = entity_label.strip() if entity_label and entity_label.strip() else "Service"

    SESSION_CACHE[session_id] = {
        "files_meta": files_meta,
        "mapped_df": combined_df,
        "normalized_df": normalized_df,
        "column_mappings": col_mappings,
        "normalization_log": norm_log,
        "flagged_rows": flagged_rows,
        "config": {
            "entity_label": clean_entity_label,
            "team_preset": team_preset,
            "overload_threshold": float(overload_threshold),
            "nominal_capacity": nom_cap,
            "llm_api_key": llm_api_key.strip() if llm_api_key else None,
            "llm_model": llm_model.strip() if llm_model else "gemini-3.6-flash",
            "llm_base_url": llm_base_url.strip() if llm_base_url else "https://generativelanguage.googleapis.com/v1beta/openai"
        }
    }

    return RedirectResponse(f"/review?session_id={session_id}", status_code=303)


@app.get("/review", response_class=HTMLResponse)
def review_view(request: Request, session_id: str):
    """Presents normalization diff and allows manager overrides."""
    if session_id not in SESSION_CACHE:
        return RedirectResponse("/upload?error=Session+expired+or+invalid.+Please+upload+your+files+again.", status_code=303)

    session_data = SESSION_CACHE[session_id]
    return templates.TemplateResponse(
        request=request,
        name="review.html",
        context={
            "active_page": "review",
            "session_id": session_id,
            "files_meta": session_data["files_meta"],
            "total_rows": len(session_data["mapped_df"]),
            "column_mappings": session_data["column_mappings"],
            "normalization_log": session_data["normalization_log"],
            "flagged_rows": session_data["flagged_rows"]
        }
    )


@app.post("/finalize")
async def finalize_report(request: Request):
    """Applies manager overrides, calculates aggregates, generates exports and persists."""
    form_data = await request.form()
    session_id = form_data.get("session_id")
    if not session_id or session_id not in SESSION_CACHE:
        return RedirectResponse("/upload?error=Session+expired+or+invalid.+Please+upload+your+files+again.", status_code=303)

    session_data = SESSION_CACHE[session_id]
    config = session_data["config"]

    # Parse manager overrides from form fields
    overrides: Dict[str, Dict[str, str]] = {}
    for key, val in form_data.items():
        if key.startswith("override__"):
            parts = key.split("__", 2)
            if len(parts) == 3:
                field_name = parts[1]
                raw_val = parts[2]
                new_val = str(val).strip()
                if field_name not in overrides:
                    overrides[field_name] = {}
                overrides[field_name][raw_val] = new_val

    # Re-run normalization with custom overrides applied
    mapped_df = session_data["mapped_df"]
    normalized_df, final_log, flagged_rows = run_normalization_pipeline(mapped_df, manager_overrides=overrides)

    # Run calculation engine
    aggregates = calculate_aggregates(
        normalized_df,
        nominal_capacity_per_employee=config.get("nominal_capacity"),
        entity_label=config.get("entity_label", "Service")
    )

    # Run variance & overload engine
    variance_data = analyze_variances(
        aggregates,
        overload_threshold_pct=config.get("overload_threshold", 110.0)
    )

    # Run AI insights module
    ai_insights = generate_ai_insights(
        aggregates,
        variance_data,
        api_key=config.get("llm_api_key"),
        base_url=config.get("llm_base_url"),
        model_name=config.get("llm_model")
    )

    # Date-stamped export filenames
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    excel_filename = f"Resource_Utilization_Report_{timestamp}.xlsx"
    pdf_filename = f"Resource_Utilization_Report_{timestamp}.pdf"

    excel_path = os.path.join(OUTPUT_DIR, excel_filename)
    pdf_path = os.path.join(OUTPUT_DIR, pdf_filename)

    # Generate 4-sheet Excel workbook & PDF report
    create_styled_workbook(aggregates, variance_data, excel_path)
    generate_pdf_report(aggregates, variance_data, ai_insights, pdf_path)

    # Save session and report to SQLite database
    report_id = save_session_data(
        session_id=session_id,
        uploads_info=session_data["files_meta"],
        normalized_df=normalized_df,
        norm_log=final_log,
        aggregates=aggregates,
        variance_data=variance_data,
        ai_insights=ai_insights,
        excel_path=excel_path,
        pdf_path=pdf_path
    )

    return RedirectResponse(f"/dashboard?report_id={report_id}", status_code=303)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard_view(request: Request, report_id: Optional[int] = None):
    """Displays the executive report dashboard."""
    if report_id:
        report = get_report_by_id(report_id)
    else:
        report = get_latest_report()

    if not report:
        report = ensure_default_report()

    if not report:
        return RedirectResponse("/upload?error=No+report+data+available.+Please+upload+a+sheet.", status_code=303)

    summary_data = report["summary"]
    variance_data = report["variance"]
    if "burnout_analysis" not in variance_data:
        from modules.variance_engine import analyze_variances
        variance_data = analyze_variances(summary_data)

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "active_page": "dashboard",
            "report_id": report["id"],
            "aggregates": summary_data,
            "variance_data": variance_data,
            "ai_insights": report["ai_insights"],
            "files_count": len(summary_data.get("by_employee", [])) or 1
        }
    )


@app.get("/trends", response_class=HTMLResponse)
def trends_view(request: Request):
    """Displays historical archive and multi-period reporting trends."""
    from modules.db import get_all_reports
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
    """Wipes all database records to clean slate (zero)."""
    from modules.db import clear_all_data
    clear_all_data()
    return RedirectResponse("/trends", status_code=303)


@app.get("/export/excel/{report_id}")
def export_excel_download(report_id: int):
    """Downloads the generated 4-sheet Excel workbook."""
    report = get_report_by_id(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Excel export not found.")

    excel_path = report.get("excel_path")
    if not excel_path:
        excel_path = os.path.join(OUTPUT_DIR, f"Resource_Utilization_Report_{report_id}.xlsx")

    with EXPORT_LOCK:
        if not os.path.exists(excel_path) or os.path.getsize(excel_path) < 10000:
            from modules.excel_exporter import create_styled_workbook
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
    """Downloads the generated executive PDF report."""
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


if __name__ == "__main__":
    print("Starting Team Resource Utilization Reporting System...")
    print("Open your browser and navigate to: http://localhost:8000")
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=False)
