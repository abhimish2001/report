"""
db.py
SQLite local persistence manager for uploads, task records, normalization logs, and generated reports.
Zero setup, auto-creates tables on first run.
"""

from __future__ import annotations
import json
import os
import sqlite3
from typing import Any, Dict, List, Optional
import pandas as pd


def get_db_path() -> str:
    """Returns absolute path to SQLite database file."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(base_dir, "data")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "reports.db")


def get_connection() -> sqlite3.Connection:
    """
    Returns an optimized SQLite connection with Write-Ahead Logging (WAL)
    and safe busy timeouts to handle concurrent read/write operations cleanly.
    """
    db_path = get_db_path()
    conn = sqlite3.connect(db_path, timeout=15.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_database() -> None:
    """Creates schema tables and performance indexes if they do not exist."""
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Uploads table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS uploads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                filename TEXT,
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                employee_hint TEXT,
                row_count INTEGER
            )
        """)

        # Tasks table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                upload_id INTEGER,
                date TEXT,
                service TEXT,
                employee TEXT,
                task TEXT,
                description TEXT,
                status TEXT,
                expected_hrs REAL,
                actual_hrs REAL,
                task_type TEXT,
                stack TEXT,
                priority TEXT,
                start_date TEXT,
                end_date TEXT,
                week TEXT
            )
        """)

        # Normalization Log table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS normalization_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                field_name TEXT,
                raw_value TEXT,
                normalized_value TEXT,
                row_count_affected INTEGER
            )
        """)

        # Reports table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                period_label TEXT,
                summary_json TEXT,
                variance_json TEXT,
                ai_insights_json TEXT,
                excel_path TEXT,
                pdf_path TEXT
            )
        """)

        # High performance indexes for quick lookups and trend aggregations
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_reports_generated ON reports(generated_at DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tasks_session ON tasks(session_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tasks_employee ON tasks(employee)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tasks_service ON tasks(service)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_norm_session ON normalization_log(session_id)")
        conn.commit()


def save_session_data(
    session_id: str,
    uploads_info: List[Dict[str, Any]],
    normalized_df: pd.DataFrame,
    norm_log: List[Dict[str, Any]],
    aggregates: Dict[str, Any],
    variance_data: Dict[str, Any],
    ai_insights: Dict[str, Any],
    excel_path: str,
    pdf_path: str
) -> int:
    """
    Persists full report session and its tasks into SQLite.
    Returns report_id.
    """
    init_database()
    with get_connection() as conn:
        cursor = conn.cursor()

        # Save uploads
        upload_id_map = {}
        for up in uploads_info:
            cursor.execute(
                "INSERT INTO uploads (session_id, filename, employee_hint, row_count) VALUES (?, ?, ?, ?)",
                (session_id, up.get("filename"), up.get("detected_employee"), up.get("row_count"))
            )
            upload_id_map[up.get("filename")] = cursor.lastrowid

        # Save tasks
        task_rows = []
        for _, row in normalized_df.iterrows():
            task_rows.append((
                session_id,
                None,
                str(row.get("Date", "")),
                str(row.get("Service", "")),
                str(row.get("Employee", "")),
                str(row.get("Task", "")),
                str(row.get("Description", "")),
                str(row.get("Status", "")),
                row.get("Expected Hours"),
                row.get("Actual Hours"),
                str(row.get("Task Type", "")),
                str(row.get("Stack", "")),
                str(row.get("Priority", "")),
                str(row.get("Start Date", "")),
                str(row.get("End Date", "")),
                str(row.get("Week", ""))
            ))
        cursor.executemany("""
            INSERT INTO tasks (
                session_id, upload_id, date, service, employee, task, description,
                status, expected_hrs, actual_hrs, task_type, stack, priority,
                start_date, end_date, week
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, task_rows)

        # Save Normalization Log
        log_rows = []
        for entry in norm_log:
            log_rows.append((
                session_id,
                entry.get("field_name"),
                entry.get("raw_value"),
                entry.get("normalized_value"),
                entry.get("row_count_affected")
            ))
        cursor.executemany("""
            INSERT INTO normalization_log (
                session_id, field_name, raw_value, normalized_value, row_count_affected
            ) VALUES (?, ?, ?, ?, ?)
        """, log_rows)

        # Save Report
        cursor.execute("""
            INSERT INTO reports (
                session_id, period_label, summary_json, variance_json,
                ai_insights_json, excel_path, pdf_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            session_id,
            aggregates.get("period_label", ""),
            json.dumps(aggregates),
            json.dumps(variance_data),
            json.dumps(ai_insights),
            excel_path,
            pdf_path
        ))
        report_id = cursor.lastrowid
        conn.commit()

        return report_id


def get_latest_report() -> Optional[Dict[str, Any]]:
    """Fetches the most recently generated report."""
    init_database()
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM reports ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "session_id": row["session_id"],
            "generated_at": row["generated_at"],
            "period_label": row["period_label"],
            "summary": json.loads(row["summary_json"]),
            "variance": json.loads(row["variance_json"]),
            "ai_insights": json.loads(row["ai_insights_json"]),
            "excel_path": row["excel_path"],
            "pdf_path": row["pdf_path"]
        }


def get_report_by_id(report_id: int) -> Optional[Dict[str, Any]]:
    """Fetches a specific report by id."""
    init_database()
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM reports WHERE id = ?", (report_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "session_id": row["session_id"],
            "generated_at": row["generated_at"],
            "period_label": row["period_label"],
            "summary": json.loads(row["summary_json"]),
            "variance": json.loads(row["variance_json"]),
            "ai_insights": json.loads(row["ai_insights_json"]),
            "excel_path": row["excel_path"],
            "pdf_path": row["pdf_path"]
        }


def get_all_reports() -> List[Dict[str, Any]]:
    """Fetches all past reports ordered by id descending."""
    init_database()
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT id, session_id, generated_at, period_label, summary_json, excel_path, pdf_path FROM reports ORDER BY id DESC")
        rows = cursor.fetchall()
        reports = []
        for r in rows:
            summary = json.loads(r["summary_json"]) if r["summary_json"] else {}
            reports.append({
                "id": r["id"],
                "session_id": r["session_id"],
                "generated_at": r["generated_at"],
                "period_label": r["period_label"],
                "totals": summary.get("totals", {}),
                "entity_label": summary.get("entity_label", "Service"),
                "month_label": summary.get("month_label", ""),
                "excel_path": r["excel_path"],
                "pdf_path": r["pdf_path"]
            })
        return reports


def clear_all_data() -> None:
    """Clears all records from the SQLite database tables."""
    init_database()
    with get_connection() as conn:
        cursor = conn.cursor()
        for t in ["uploads", "tasks", "normalization_log", "reports"]:
            cursor.execute(f"DELETE FROM {t}")
            try:
                cursor.execute(f"DELETE FROM sqlite_sequence WHERE name='{t}'")
            except sqlite3.OperationalError:
                pass
        conn.commit()
        conn.execute("VACUUM")
