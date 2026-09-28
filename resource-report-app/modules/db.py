"""
db.py
Code-First Microsoft SQL Server persistence manager using SQLAlchemy ORM.
Automatically creates the database on any new system and generates all tables
from models.py.
"""

from __future__ import annotations
import json
import logging
import os
import urllib.parse
from typing import Any, Dict, List, Optional
import pandas as pd
from sqlalchemy import create_engine, desc, text
from sqlalchemy.orm import sessionmaker, scoped_session

from modules.models import (
    Base,
    Upload,
    Task,
    NormalizationLog,
    Report,
    Setting
)

logger = logging.getLogger(__name__)

# ── Load .env ─────────────────────────────────────────────────────────────────
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
env_file = os.path.join(base_dir, ".env")
try:
    from dotenv import load_dotenv
    load_dotenv(env_file if os.path.exists(env_file) else None)
except ImportError:
    pass

try:
    import pyodbc
except ImportError:
    raise RuntimeError(
        "pyodbc is required for SQL Server. Install it with: pip install pyodbc"
    )


# ── Driver & Connection String Helpers ────────────────────────────────────────

def _get_driver() -> str:
    """Detects the best available ODBC driver for SQL Server."""
    configured = os.environ.get("SQL_SERVER_DRIVER", "").strip()
    if configured:
        return configured
    preferred = [
        "ODBC Driver 18 for SQL Server",
        "ODBC Driver 17 for SQL Server",
        "ODBC Driver 13 for SQL Server",
        "ODBC Driver 11 for SQL Server",
        "SQL Server Native Client 11.0",
        "SQL Server",
    ]
    try:
        installed = pyodbc.drivers()
        for p in preferred:
            if p in installed:
                return p
        for d in installed:
            if "SQL Server" in d:
                return d
    except Exception:
        pass
    return "ODBC Driver 18 for SQL Server"


def _get_connection_params(database_name: Optional[str] = None) -> str:
    """Builds standard ODBC connection string."""
    driver = _get_driver()
    host = os.environ.get("SQL_SERVER_HOST", "(localdb)\\MSSQLLocalDB").strip()
    port = os.environ.get("SQL_SERVER_PORT", "").strip()
    db = database_name if database_name else os.environ.get("SQL_SERVER_DATABASE", "ResourceUtilizationDB").strip()
    trusted = os.environ.get("SQL_SERVER_TRUSTED_CONNECTION", "yes").strip().lower()
    user = os.environ.get("SQL_SERVER_USER", "").strip()
    password = os.environ.get("SQL_SERVER_PASSWORD", "").strip()
    trust_cert = os.environ.get("SQL_SERVER_TRUST_CERTIFICATE", "yes").strip().lower()
    encrypt = os.environ.get("SQL_SERVER_ENCRYPT", "no").strip().lower()

    server = f"{host},{port}" if (port and port != "1433" and "\\" not in host) else host

    parts = [
        f"DRIVER={{{driver}}}",
        f"SERVER={server}",
        f"DATABASE={db}",
    ]
    if trusted in ("yes", "true", "1"):
        parts.append("Trusted_Connection=yes")
    else:
        if user:
            parts.append(f"UID={user}")
        if password:
            parts.append(f"PWD={password}")

    parts.append("TrustServerCertificate=yes" if trust_cert in ("yes", "true", "1") else "TrustServerCertificate=no")
    parts.append("Encrypt=yes" if encrypt in ("yes", "true", "1") else "Encrypt=no")

    return ";".join(parts) + ";"


# ── Auto-Create Database on Any System ────────────────────────────────────────

def ensure_database_exists() -> None:
    """
    Connects to the SQL Server 'master' database and automatically creates
    the target database if it does not yet exist.
    """
    target_db = os.environ.get("SQL_SERVER_DATABASE", "ResourceUtilizationDB").strip()
    master_conn_str = _get_connection_params(database_name="master")
    encoded_params = urllib.parse.quote_plus(master_conn_str)
    master_url = f"mssql+pyodbc:///?odbc_connect={encoded_params}"

    master_engine = create_engine(master_url, isolation_level="AUTOCOMMIT")
    try:
        with master_engine.connect() as conn:
            # Check if database exists
            chk = conn.execute(
                text("SELECT database_id FROM sys.databases WHERE name = :dbname"),
                {"dbname": target_db}
            ).scalar()
            if not chk:
                logger.info("Database '%s' does not exist. Creating it automatically...", target_db)
                # Escaping database name bracket safely
                safe_db_name = target_db.replace("]", "]]")
                conn.execute(text(f"CREATE DATABASE [{safe_db_name}]"))
                logger.info("Database '%s' created successfully.", target_db)
    except Exception as e:
        logger.warning("Could not auto-verify/create database via master: %s", e)
    finally:
        master_engine.dispose()


# ── SQLAlchemy Engine & Session Factory ────────────────────────────────────────

def _get_engine():
    db_conn_str = _get_connection_params()
    encoded_params = urllib.parse.quote_plus(db_conn_str)
    engine_url = f"mssql+pyodbc:///?odbc_connect={encoded_params}"
    return create_engine(
        engine_url,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
        fast_executemany=True
    )


_ENGINE = None
_SESSION_FACTORY = None


def get_engine():
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = _get_engine()
    return _ENGINE


def get_session():
    """Returns a new SQLAlchemy Session."""
    global _SESSION_FACTORY
    if _SESSION_FACTORY is None:
        engine = get_engine()
        _SESSION_FACTORY = scoped_session(sessionmaker(bind=engine, autoflush=False, autocommit=False))
    return _SESSION_FACTORY()


# ── Database Initialization (Code-First) ──────────────────────────────────────

def init_database() -> None:
    """
    Auto-creates the database if needed, then applies all SQLAlchemy models
    to create or update the tables in SQL Server.
    """
    ensure_database_exists()
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    logger.info("Database and tables initialized successfully via Code-First models.")


# ── Persistence API ───────────────────────────────────────────────────────────

def save_session_data(
    session_id: str,
    uploads_info: List[Dict[str, Any]],
    normalized_df: pd.DataFrame,
    norm_log: List[Dict[str, Any]],
    aggregates: Dict[str, Any],
    variance_data: Dict[str, Any],
    ai_insights: Dict[str, Any],
    cadence: str = "monthly"
) -> int:
    """
    Saves an uploaded timesheet session, raw task rows, normalization audit log,
    and compiled report summary into SQL Server using Code-First models.
    """
    session = get_session()
    try:
        period_label = aggregates.get("period_label", "August 2026")
        first_upload_id = None

        # 1. Save uploads metadata
        for u_info in uploads_info:
            u = Upload(
                session_id=session_id,
                filename=u_info.get("filename"),
                period_label=period_label,
                employee_hint=u_info.get("detected_employee"),
                row_count=u_info.get("row_count")
            )
            session.add(u)
            session.flush()
            if first_upload_id is None:
                first_upload_id = u.id

        # 2. Save individual task rows
        if not normalized_df.empty:
            task_records = []
            for _, r in normalized_df.iterrows():
                t = Task(
                    session_id=session_id,
                    upload_id=first_upload_id,
                    date=str(r.get("Date") or ""),
                    service=str(r.get("Service") or ""),
                    employee=str(r.get("Employee") or ""),
                    task=str(r.get("Task") or "")[:500],
                    description=str(r.get("Description") or "") if r.get("Description") is not None else None,
                    status=str(r.get("Status") or "")[:100],
                    expected_hrs=float(r.get("Expected Hours")) if pd.notnull(r.get("Expected Hours")) else 0.0,
                    actual_hrs=float(r.get("Actual Hours")) if pd.notnull(r.get("Actual Hours")) else 0.0,
                    task_type=str(r.get("Task Type") or "")[:255],
                    stack=str(r.get("Stack") or "")[:255] if pd.notnull(r.get("Stack")) else None,
                    priority=str(r.get("Priority") or "")[:100] if pd.notnull(r.get("Priority")) else None,
                    start_date=str(r.get("Start Date") or "")[:50] if pd.notnull(r.get("Start Date")) else None,
                    end_date=str(r.get("End Date") or "")[:50] if pd.notnull(r.get("End Date")) else None,
                    week=str(r.get("Week") or "")[:100] if pd.notnull(r.get("Week")) else None,
                    university=str(r.get("University") or "")[:255] if pd.notnull(r.get("University")) else None
                )
                task_records.append(t)
            session.bulk_save_objects(task_records)

        # 3. Save normalization audit log
        if norm_log:
            norm_records = []
            for n in norm_log:
                nl = NormalizationLog(
                    session_id=session_id,
                    field_name=n.get("field_name") or n.get("field"),
                    raw_value=str(n.get("raw_value") or "")[:500],
                    normalized_value=str(n.get("normalized_value") or "")[:500],
                    row_count_affected=n.get("row_count_affected", 1)
                )
                norm_records.append(nl)
            session.bulk_save_objects(norm_records)

        # 4. Save compiled report snapshot
        report = Report(
            session_id=session_id,
            period_label=period_label,
            cadence=cadence,
            summary_json=json.dumps(aggregates, default=str),
            variance_json=json.dumps(variance_data, default=str),
            ai_insights_json=json.dumps(ai_insights, default=str)
        )
        session.add(report)
        session.commit()
        return report.id
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_latest_report() -> Optional[Dict[str, Any]]:
    """Retrieves the most recently generated report."""
    session = get_session()
    try:
        report = session.query(Report).order_by(desc(Report.generated_at)).first()
        if not report:
            return None
        return _format_report(report)
    finally:
        session.close()


def get_report_by_id(report_id: int) -> Optional[Dict[str, Any]]:
    """Retrieves a specific report by primary key."""
    session = get_session()
    try:
        report = session.query(Report).filter(Report.id == report_id).first()
        if not report:
            return None
        return _format_report(report)
    finally:
        session.close()


def get_all_reports() -> List[Dict[str, Any]]:
    """Retrieves all historical reports for trends."""
    session = get_session()
    try:
        reports = session.query(Report).order_by(desc(Report.generated_at)).all()
        return [_format_report(r) for r in reports]
    finally:
        session.close()


def update_report_ai_insights(report_id: int, ai_insights: Dict[str, Any]) -> None:
    """Updates AI insights payload for an existing report."""
    session = get_session()
    try:
        report = session.query(Report).filter(Report.id == report_id).first()
        if report:
            report.ai_insights_json = json.dumps(ai_insights, default=str)
            session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def clear_all_data() -> None:
    """Truncates/clears all uploaded tasks, files, audit logs, and reports."""
    session = get_session()
    try:
        session.query(Task).delete()
        session.query(Upload).delete()
        session.query(NormalizationLog).delete()
        session.query(Report).delete()
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def check_db_health() -> Dict[str, Any]:
    """Health check for SQL Server connection."""
    try:
        engine = get_engine()
        with engine.connect() as conn:
            ver = conn.execute(text("SELECT @@VERSION")).scalar()
            cnt = conn.execute(text("SELECT COUNT(*) FROM reports")).scalar()
            tasks_cnt = conn.execute(text("SELECT COUNT(*) FROM tasks")).scalar()
            return {
                "connected": True,
                "version": str(ver).split("\n")[0],
                "reports_count": cnt,
                "tasks_count": tasks_cnt,
            }
    except Exception as e:
        return {"connected": False, "error": str(e)}


def _format_report(report: Report) -> Dict[str, Any]:
    """Helper to deserialize report model into dict."""
    summary = json.loads(report.summary_json) if report.summary_json else {}
    return {
        "id": report.id,
        "session_id": report.session_id,
        "period_label": report.period_label,
        "cadence": report.cadence,
        "generated_at": report.generated_at.strftime("%d-%b-%Y %H:%M") if report.generated_at else "",
        "summary": summary,
        "totals": summary.get("totals", {}),
        "variance": json.loads(report.variance_json) if report.variance_json else {},
        "ai_insights": json.loads(report.ai_insights_json) if report.ai_insights_json else {}
    }


def get_report_tasks(
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
) -> List[Dict[str, Any]]:
    """Fetches granular task records for a report session, with optional drill-down filters."""
    session = get_session()
    try:
        report = session.query(Report).filter(Report.id == report_id).first()
        if not report:
            return []
        query = session.query(Task).filter(Task.session_id == report.session_id)
        if employee and employee.strip() and employee != "All":
            query = query.filter(Task.employee == employee.strip())
        if service and service.strip() and service != "All":
            s_val = service.strip()
            query = query.filter((Task.service == s_val) | (Task.university == s_val))
        if task_type and task_type.strip() and task_type != "All":
            query = query.filter(Task.task_type.ilike(f"%{task_type.strip()}%"))
        if week and week.strip() and week != "All":
            query = query.filter(Task.week.ilike(f"%{week.strip()}%"))
        if status and status.strip() and status != "All":
            query = query.filter(Task.status.ilike(f"%{status.strip()}%"))
        if search and search.strip():
            s = f"%{search.strip()}%"
            query = query.filter(
                (Task.task.ilike(s)) |
                (Task.description.ilike(s)) |
                (Task.service.ilike(s)) |
                (Task.employee.ilike(s))
            )

        tasks = query.order_by(Task.date.desc(), Task.id.asc()).limit(limit).all()

        clean_from = from_date.strip() if from_date and from_date.strip() else None
        clean_to = to_date.strip() if to_date and to_date.strip() else None
        clean_anomaly = anomaly_type.strip().lower() if anomaly_type and anomaly_type.strip() else None

        overtime_keys = set()
        if clean_anomaly in ["overtime", "all"]:
            daily_sums = {}
            for t in tasks:
                dt = pd.to_datetime(t.date, dayfirst=True, errors='coerce')
                dt_k = dt.strftime('%Y-%m-%d') if pd.notnull(dt) else ""
                emp_k = t.employee or ""
                daily_sums[(dt_k, emp_k)] = daily_sums.get((dt_k, emp_k), 0.0) + (t.actual_hrs or 0.0)
            overtime_keys = {pair for pair, total in daily_sums.items() if total > 10.0}

        vague_keywords = {'work', 'meeting', 'support', 'test', 'testing', 'daily', 'status', 'other', 'none', 'general', 'misc', 'issue', 'fix', 'task'}
        results = []

        for t in tasks:
            dt = pd.to_datetime(t.date, dayfirst=True, errors='coerce')
            iso_date = dt.strftime('%Y-%m-%d') if pd.notnull(dt) else ""

            if clean_from and iso_date and iso_date < clean_from:
                continue
            if clean_to and iso_date and iso_date > clean_to:
                continue

            if clean_anomaly:
                is_weekend = dt.weekday() in [5, 6] if pd.notnull(dt) else False
                task_text = (t.task or "").lower().strip()
                is_vague = task_text in vague_keywords or len(task_text) <= 4
                is_overtime = (iso_date, t.employee or "") in overtime_keys
                is_missing = (t.actual_hrs or 0.0) == 0.0 or (t.expected_hrs or 0.0) == 0.0

                if clean_anomaly == "weekend" and not is_weekend:
                    continue
                elif clean_anomaly == "vague" and not is_vague:
                    continue
                elif clean_anomaly == "overtime" and not is_overtime:
                    continue
                elif clean_anomaly == "missing" and not is_missing:
                    continue
                elif clean_anomaly == "all" and not (is_weekend or is_vague or is_overtime or is_missing):
                    continue

            results.append({
                "id": t.id,
                "date": t.date or "N/A",
                "iso_date": iso_date,
                "service": t.service or t.university or "N/A",
                "university": t.university or t.service or "N/A",
                "employee": t.employee or "N/A",
                "task": t.task or "Untitled Task",
                "description": t.description or "",
                "status": t.status or "Completed",
                "expected_hrs": round(t.expected_hrs or 0.0, 2),
                "actual_hrs": round(t.actual_hrs or 0.0, 2),
                "variance": round((t.actual_hrs or 0.0) - (t.expected_hrs or 0.0), 2),
                "task_type": t.task_type or "Support",
                "stack": t.stack or "",
                "priority": t.priority or "",
                "week": t.week or ""
            })

        return results
    finally:
        session.close()

