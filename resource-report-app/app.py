"""
app.py
FastAPI application entrypoint for the Team Resource Utilization Reporting System.
Key Features:
- Direct open access: No login friction, instant dashboard and report workflow
- Code-First Microsoft SQL Server persistence (auto-creates database and schema)
- Upload and analyze Excel (.xlsx, .xls) and CSV task timesheets
- Zero disk footprint: In-memory processing and direct streaming for Excel/PDF exports
- Supports single-employee and multi-employee sheets
- Dynamic KPIs, Work-type analysis, Resource utilization, and AI Governance insights
"""

from __future__ import annotations
import datetime
import io
import os
import uuid
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional
import pandas as pd
from pydantic import BaseModel
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from modules.ai_copilot import ask_gemini_copilot

from modules.excel_reader import read_file_to_dataframe, extract_file_preview
from modules.column_mapper import map_dataframe_to_schema
from modules.normalizer import run_normalization_pipeline
from modules.calculator import (
    calculate_aggregates,
    get_empty_aggregates,
    compute_hygiene_and_anomalies,
    compute_workload_heatmap
)
from modules.variance_engine import analyze_variances
from modules.ai_insights import generate_ai_insights
from modules.excel_exporter import create_styled_workbook
from modules.pdf_exporter import generate_pdf_report
from modules.report_reader import is_consolidated_report_file, parse_consolidated_report
from modules.db import (
    init_database,
    save_session_data,
    get_latest_report,
    get_report_by_id,
    get_all_reports,
    update_report_ai_insights,
    check_db_health,
    clear_all_data,
    get_report_tasks
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Auto-creates the database if not present and initializes tables from Code-First models
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
def dashboard_view(
    request: Request,
    report_id: Optional[int] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    week: Optional[str] = None,
    service: Optional[str] = None,
    task_type: Optional[str] = None,
    employee: Optional[str] = None,
    status: Optional[str] = None,
    anomaly_type: Optional[str] = None
):
    """
    Renders executive dashboard with dynamic filtering by date, week,
    service, task type, employee, status, or anomaly.
    """
    report = None
    if report_id:
        report = get_report_by_id(report_id)
    else:
        report = get_latest_report()

    clean_from = from_date.strip() if from_date and from_date.strip() else None
    clean_to = to_date.strip() if to_date and to_date.strip() else None
    clean_week = week.strip() if week and week.strip() else None
    clean_svc = service.strip() if service and service.strip() else None
    clean_type = task_type.strip() if task_type and task_type.strip() else None
    clean_emp = employee.strip() if employee and employee.strip() else None
    clean_status = status.strip() if status and status.strip() else None
    clean_anomaly = anomaly_type.strip() if anomaly_type and anomaly_type.strip() else None

    has_active_filter = any([clean_from, clean_to, clean_week, clean_svc, clean_type, clean_emp, clean_status, clean_anomaly])

    active_filters = {
        "from_date": clean_from or "",
        "to_date": clean_to or "",
        "week": clean_week or "",
        "service": clean_svc or "",
        "task_type": clean_type or "",
        "employee": clean_emp or "",
        "status": clean_status or "",
        "anomaly_type": clean_anomaly or "",
        "is_active": has_active_filter
    }

    if report:
        active_report_id = report["id"]
        baseline_summary = report["summary"]
        variance_data = report["variance"]
        ai_insights = report.get("ai_insights", {})
        files_count = len(baseline_summary.get("by_employee", [])) or 1

        if has_active_filter and active_report_id > 0:
            filtered_tasks = get_report_tasks(
                report_id=active_report_id,
                employee=clean_emp,
                service=clean_svc,
                task_type=clean_type,
                week=clean_week,
                status=clean_status,
                from_date=clean_from,
                to_date=clean_to,
                anomaly_type=clean_anomaly,
                limit=5000
            )
            if filtered_tasks:
                df_f = pd.DataFrame(filtered_tasks)
                df_standard = df_f.rename(columns={
                    'date': 'Date',
                    'service': 'Service',
                    'employee': 'Employee',
                    'task': 'Task',
                    'description': 'Description',
                    'status': 'Status',
                    'expected_hrs': 'Expected Hours',
                    'actual_hrs': 'Actual Hours',
                    'task_type': 'Task Type',
                    'week': 'Week'
                })
                df_standard['_Parsed_Date'] = pd.to_datetime(df_standard['Date'], dayfirst=True, errors='coerce')
                summary_data = calculate_aggregates(df_standard)
                # Keep full catalog for filter controls
                summary_data["ordered_weeks"] = baseline_summary.get("ordered_weeks", [])
                summary_data["all_services"] = baseline_summary.get("by_service", [])
                summary_data["all_employees"] = baseline_summary.get("by_employee", [])
                summary_data["hygiene"] = compute_hygiene_and_anomalies(df_standard)
                summary_data["heatmap"] = compute_workload_heatmap(df_standard)
            else:
                summary_data = get_empty_aggregates()
                summary_data["ordered_weeks"] = baseline_summary.get("ordered_weeks", [])
                summary_data["all_services"] = baseline_summary.get("by_service", [])
                summary_data["all_employees"] = baseline_summary.get("by_employee", [])
        else:
            summary_data = baseline_summary
            summary_data["all_services"] = baseline_summary.get("by_service", [])
            summary_data["all_employees"] = baseline_summary.get("by_employee", [])
            # Dynamic fallback: compute hygiene and heatmap for historical reports if not yet present
            if active_report_id > 0 and ("hygiene" not in summary_data or "heatmap" not in summary_data):
                db_tasks = get_report_tasks(active_report_id, limit=5000)
                if db_tasks:
                    df_tasks = pd.DataFrame(db_tasks)
                    summary_data["hygiene"] = compute_hygiene_and_anomalies(df_tasks)
                    summary_data["heatmap"] = compute_workload_heatmap(df_tasks)
    else:
        summary_data = get_empty_aggregates()
        summary_data["all_services"] = []
        summary_data["all_employees"] = []
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
            "files_count": files_count,
            "active_filters": active_filters
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
    """Processes uploaded Excel/CSV sheet(s) and automatically compiles utilization report."""
    valid_files = [f for f in files if f.filename and f.filename.strip()]
    if not valid_files:
        return RedirectResponse("/upload?error=Please+select+at+least+one+valid+file", status_code=303)

    session_id = str(uuid.uuid4())
    loaded_dfs: List[pd.DataFrame] = []
    files_meta: List[Dict[str, Any]] = []

    for f in valid_files:
        file_bytes = await f.read()

        # Check if pre-consolidated 4-sheet report workbook was uploaded
        if is_consolidated_report_file(file_bytes, f.filename):
            try:
                aggregates, variance_data = parse_consolidated_report(file_bytes, f.filename)
                ai_insights = generate_ai_insights(aggregates, variance_data)
                meta = {
                    "filename": f.filename,
                    "row_count": aggregates.get("total_tasks", 0),
                    "detected_employee": "Consolidated Report",
                    "date_range": aggregates.get("period_label", "August 2026"),
                    "columns": ["Consolidated Workbook"]
                }
                report_id = save_session_data(
                    session_id=session_id,
                    uploads_info=[meta],
                    normalized_df=pd.DataFrame(),
                    norm_log=[],
                    aggregates=aggregates,
                    variance_data=variance_data,
                    ai_insights=ai_insights,
                    cadence=cadence
                )
                return RedirectResponse(f"/dashboard?report_id={report_id}", status_code=303)
            except Exception as e:
                return RedirectResponse(f"/upload?error=Error+parsing+report+{f.filename}:+{str(e)}", status_code=303)

        # Standard raw task timesheet processing (single or multiple employees)
        try:
            df = read_file_to_dataframe(file_bytes, f.filename)
            preview = extract_file_preview(df, f.filename)
            files_meta.append(preview)

            mapped_df, _, _ = map_dataframe_to_schema(
                df,
                default_employee=preview.get("detected_employee")
            )
            loaded_dfs.append(mapped_df)
        except Exception as e:
            return RedirectResponse(f"/upload?error=Error+reading+{f.filename}:+{str(e)}", status_code=303)

    if not loaded_dfs:
        return RedirectResponse("/upload?error=No+valid+data+could+be+read", status_code=303)

    combined_df = pd.concat(loaded_dfs, ignore_index=True)
    normalized_df, norm_log, _ = run_normalization_pipeline(combined_df)

    aggregates = calculate_aggregates(normalized_df)
    variance_data = analyze_variances(aggregates, overload_threshold_pct=100.0)
    ai_insights = generate_ai_insights(aggregates, variance_data)

    report_id = save_session_data(
        session_id=session_id,
        uploads_info=files_meta,
        normalized_df=normalized_df,
        norm_log=norm_log,
        aggregates=aggregates,
        variance_data=variance_data,
        ai_insights=ai_insights,
        cadence=cadence
    )

    return RedirectResponse(f"/dashboard?report_id={report_id}", status_code=303)


@app.get("/load-demo")
def load_demo_dataset(request: Request):
    """Manual one-click demo loader using the August 2026 reference file."""
    demo_file = os.path.join(BASE_DIR, "TaskStatus-202608(Input File).xlsx")
    if not os.path.exists(demo_file):
        demo_file = os.path.join(BASE_DIR, "TaskStatus-202608(Input File).csv")
    if not os.path.exists(demo_file):
        return RedirectResponse("/upload?error=Demo+file+not+found", status_code=303)

    session_id = str(uuid.uuid4())
    filename = os.path.basename(demo_file)
    with open(demo_file, "rb") as f:
        file_bytes = f.read()

    df_raw = read_file_to_dataframe(file_bytes, filename)
    preview = extract_file_preview(df_raw, filename)
    mapped_df, _, _ = map_dataframe_to_schema(df_raw)
    normalized_df, norm_log, _ = run_normalization_pipeline(mapped_df)
    aggregates = calculate_aggregates(normalized_df)
    variance_data = analyze_variances(aggregates, overload_threshold_pct=100.0)
    ai_insights = generate_ai_insights(aggregates, variance_data)

    report_id = save_session_data(
        session_id=session_id,
        uploads_info=[preview],
        normalized_df=normalized_df,
        norm_log=norm_log,
        aggregates=aggregates,
        variance_data=variance_data,
        ai_insights=ai_insights,
        cadence="consolidated"
    )

    return RedirectResponse(f"/dashboard?report_id={report_id}", status_code=303)



@app.get("/api/tasks")
def get_tasks_endpoint(
    report_id: int,
    employee: Optional[str] = None,
    service: Optional[str] = None,
    task_type: Optional[str] = None,
    week: Optional[str] = None,
    status: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    search: Optional[str] = None,
    anomaly_type: Optional[str] = None,
    limit: int = 5000
):
    """Granular task drill-down API for interactive dashboard inspection."""
    tasks = get_report_tasks(
        report_id=report_id,
        employee=employee,
        service=service,
        task_type=task_type,
        week=week,
        status=status,
        from_date=from_date,
        to_date=to_date,
        search=search,
        anomaly_type=anomaly_type,
        limit=limit
    )
    total_expected = round(sum(t.get("expected_hrs", 0.0) for t in tasks), 2)
    total_actual = round(sum(t.get("actual_hrs", 0.0) for t in tasks), 2)
    total_variance = round(total_actual - total_expected, 2)
    return {
        "report_id": report_id,
        "count": len(tasks),
        "total_expected_hrs": total_expected,
        "total_actual_hrs": total_actual,
        "total_variance": total_variance,
        "tasks": tasks
    }

@app.post("/api/regenerate-ai")
def regenerate_ai_endpoint(request: Request, report_id: int = Form(...), gemini_api_key: str = Form(...)):
    """Regenerates AI insights using provided Gemini API Key."""
    report = get_report_by_id(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found.")

    aggregates = report["summary"]
    variance_data = report["variance"]
    ai_insights = generate_ai_insights(aggregates, variance_data, api_key=gemini_api_key.strip())

    update_report_ai_insights(report_id, ai_insights)

    return RedirectResponse(f"/dashboard?report_id={report_id}", status_code=303)


# ─── AI COPILOT CHATBOT ENDPOINTS ──────────────────────────────────

class ChatRequest(BaseModel):
    report_id: int
    message: str
    api_key: Optional[str] = None
    history: Optional[List[Dict[str, str]]] = None


@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    """Processes conversational natural language questions about timesheet data."""
    report = None
    if req.report_id > 0:
        report = get_report_by_id(req.report_id)
    if not report:
        report = get_latest_report()

    summary = report["summary"] if report else get_empty_aggregates()
    result = await ask_gemini_copilot(
        user_query=req.message,
        report_summary=summary,
        report_id=req.report_id,
        api_key=req.api_key,
        history=req.history
    )
    return result


class SaveKeyRequest(BaseModel):
    api_key: str


@app.post("/api/save-gemini-key")
def save_gemini_key_endpoint(req: SaveKeyRequest):
    """Saves user's Gemini API Key in runtime environment and persists to .env."""
    clean_key = req.api_key.strip()
    if clean_key:
        os.environ["GEMINI_API_KEY"] = clean_key
        env_path = os.path.join(BASE_DIR, ".env")
        try:
            lines = []
            if os.path.exists(env_path):
                with open(env_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
            updated = False
            new_lines = []
            for line in lines:
                if line.startswith("GEMINI_API_KEY="):
                    new_lines.append(f"GEMINI_API_KEY={clean_key}\n")
                    updated = True
                else:
                    new_lines.append(line)
            if not updated:
                new_lines.append(f"GEMINI_API_KEY={clean_key}\n")
            with open(env_path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
        except Exception:
            pass
        return {"status": "ok", "message": "Gemini API Key successfully saved and active!"}
    return {"status": "error", "message": "API Key cannot be blank."}


# ─── TRENDS & REPORTS ──────────────────────────────────────────────

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
def reset_db_endpoint(request: Request):
    """Fully clears database and returns to zero-state dashboard."""
    clear_all_data()
    return RedirectResponse("/dashboard", status_code=303)


@app.get("/export/excel/{report_id}")
def export_excel_download(request: Request, report_id: int):
    """Generates the 4-sheet Excel report entirely in memory and streams it directly."""
    if report_id <= 0:
        raise HTTPException(status_code=400, detail="No active report available to export. Please upload a timesheet first.")
    report = get_report_by_id(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Excel export not found.")

    file_bytes = create_styled_workbook(report["summary"], report["variance"], output_path=None)
    filename = f"Resource_Utilization_Report_{report_id}.xlsx"

    return Response(
        content=file_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@app.get("/export/pdf/{report_id}")
def export_pdf_download(request: Request, report_id: int):
    """Generates the executive PDF report entirely in memory and streams it directly."""
    if report_id <= 0:
        raise HTTPException(status_code=400, detail="No active report available to export. Please upload a timesheet first.")
    report = get_report_by_id(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="PDF export not found.")

    pdf_bytes = generate_pdf_report(
        report["summary"],
        report["variance"],
        report.get("ai_insights", {}),
        output_path=None
    )
    filename = f"Resource_Utilization_Report_{report_id}.pdf"

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
    print("Open your browser and navigate to: http://localhost:8001")
    uvicorn.run("app:app", host="127.0.0.1", port=8001, reload=True)
