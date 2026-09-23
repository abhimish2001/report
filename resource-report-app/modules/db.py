"""
db.py
Enterprise-grade persistence manager for the Team Resource Utilization Reporting System.
Supports Microsoft SQL Server as the primary database, with automatic resilient fallback
to SQLite so the application works seamlessly in any environment.

Manages:
- File Uploads & Ingestion Tracking
- Task Records & Normalization Logs
- Generated Reports & Historical Snapshots
- System Configuration Settings
"""

from __future__ import annotations
import json
import logging
import os
import sqlite3
from typing import Any, Dict, List, Optional
import pandas as pd

logger = logging.getLogger(__name__)

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
env_file = os.path.join(base_dir, ".env")
try:
    from dotenv import load_dotenv
    if os.path.exists(env_file):
        load_dotenv(env_file)
    else:
        load_dotenv()
except ImportError:
    pass

try:
    import pyodbc
except ImportError:
    pyodbc = None

SQLITE_DB_PATH = os.path.join(base_dir, "data", "resource_utilization.db")
os.makedirs(os.path.dirname(SQLITE_DB_PATH), exist_ok=True)


def get_available_driver() -> str:
    """Auto-detects the best installed Microsoft ODBC Driver for SQL Server."""
    configured_driver = os.environ.get("SQL_SERVER_DRIVER", "").strip()
    if configured_driver:
        return configured_driver

    if pyodbc is None:
        return "ODBC Driver 18 for SQL Server"

    try:
        installed = pyodbc.drivers()
        preferred_drivers = [
            "ODBC Driver 18 for SQL Server",
            "ODBC Driver 17 for SQL Server",
            "ODBC Driver 13 for SQL Server",
            "ODBC Driver 11 for SQL Server",
            "SQL Server Native Client 11.0",
            "SQL Server"
        ]
        for pref in preferred_drivers:
            if pref in installed:
                return pref
        for d in installed:
            if "SQL Server" in d:
                return d
    except Exception:
        pass

    return "ODBC Driver 18 for SQL Server"


def get_sql_server_connection_string() -> str:
    """Constructs ODBC connection string for Microsoft SQL Server."""
    conn_override = os.environ.get("SQL_SERVER_CONN_STRING", "").strip()
    if conn_override:
        return conn_override

    driver = get_available_driver()
    host = os.environ.get("SQL_SERVER_HOST", "localhost").strip()
    port = os.environ.get("SQL_SERVER_PORT", "1433").strip()
    database = os.environ.get("SQL_SERVER_DATABASE", "ResourceUtilizationDB").strip()
    trusted = os.environ.get("SQL_SERVER_TRUSTED_CONNECTION", "yes").strip().lower()
    user = os.environ.get("SQL_SERVER_USER", "").strip()
    password = os.environ.get("SQL_SERVER_PASSWORD", "").strip()
    trust_cert = os.environ.get("SQL_SERVER_TRUST_CERTIFICATE", "yes").strip().lower()
    encrypt = os.environ.get("SQL_SERVER_ENCRYPT", "no").strip().lower()

    server = f"{host},{port}" if (port and port != "1433" and "\\" not in host) else host

    parts = [
        f"DRIVER={{{driver}}}",
        f"SERVER={server}",
        f"DATABASE={database}"
    ]

    if trusted in ("yes", "true", "1"):
        parts.append("Trusted_Connection=yes")
    else:
        if user:
            parts.append(f"UID={user}")
        if password:
            parts.append(f"PWD={password}")

    if trust_cert in ("yes", "true", "1"):
        parts.append("TrustServerCertificate=yes")

    if encrypt in ("yes", "true", "1"):
        parts.append("Encrypt=yes")
    else:
        parts.append("Encrypt=no")

    return ";".join(parts) + ";"


class DatabaseManager:
    """
    Unified database manager that connects to Microsoft SQL Server if available,
    or falls back to SQLite seamlessly with identical table structures and operations.
    """
    def __init__(self):
        self.engine_type = "sqlite"
        self._test_connection()

    def _test_connection(self):
        if pyodbc is not None:
            try:
                conn_str = get_sql_server_connection_string()
                conn = pyodbc.connect(conn_str, timeout=3, autocommit=False)
                conn.close()
                self.engine_type = "sql_server"
                logger.info("DatabaseManager: connected to SQL Server.")
                return
            except Exception as e:
                logger.warning(
                    "DatabaseManager: SQL Server unreachable at startup (%s), falling back to SQLite.", e
                )
        else:
            logger.warning("DatabaseManager: pyodbc not installed, falling back to SQLite.")
        self.engine_type = "sqlite"

    def get_raw_connection(self):
        if self.engine_type == "sql_server":
            try:
                conn_str = get_sql_server_connection_string()
                return pyodbc.connect(conn_str, timeout=5, autocommit=False)
            except Exception as e:
                logger.warning(
                    "DatabaseManager: lost SQL Server connection mid-session (%s), "
                    "downgrading to SQLite for the rest of this process.", e
                )
                self.engine_type = "sqlite"
                return sqlite3.connect(SQLITE_DB_PATH, timeout=10)
        else:
            return sqlite3.connect(SQLITE_DB_PATH, timeout=10)

    def is_sql_server(self) -> bool:
        return self.engine_type == "sql_server"


db_mgr = DatabaseManager()


def init_database() -> None:
    """Initializes schema tables in SQL Server or SQLite."""
    conn = db_mgr.get_raw_connection()
    is_ms = db_mgr.is_sql_server()
    cursor = conn.cursor()

    try:
        if is_ms:
            # SQL Server DDL
            cursor.execute("""
                IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[uploads]') AND type in (N'U'))
                BEGIN
                    CREATE TABLE [dbo].[uploads] (
                        [id] INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
                        [session_id] NVARCHAR(100) NOT NULL,
                        [filename] NVARCHAR(500) NULL,
                        [period_label] NVARCHAR(255) NULL,
                        [uploaded_at] DATETIME2 DEFAULT SYSUTCDATETIME() NOT NULL,
                        [employee_hint] NVARCHAR(255) NULL,
                        [row_count] INT NULL
                    );
                END
            """)

            cursor.execute("""
                IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[tasks]') AND type in (N'U'))
                BEGIN
                    CREATE TABLE [dbo].[tasks] (
                        [id] INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
                        [session_id] NVARCHAR(100) NOT NULL,
                        [upload_id] INT NULL,
                        [date] NVARCHAR(50) NULL,
                        [service] NVARCHAR(255) NULL,
                        [employee] NVARCHAR(255) NULL,
                        [task] NVARCHAR(500) NULL,
                        [description] NVARCHAR(MAX) NULL,
                        [status] NVARCHAR(100) NULL,
                        [expected_hrs] FLOAT NULL,
                        [actual_hrs] FLOAT NULL,
                        [task_type] NVARCHAR(255) NULL,
                        [stack] NVARCHAR(255) NULL,
                        [priority] NVARCHAR(100) NULL,
                        [start_date] NVARCHAR(50) NULL,
                        [end_date] NVARCHAR(50) NULL,
                        [week] NVARCHAR(100) NULL,
                        [university] NVARCHAR(255) NULL,
                        [created_at] DATETIME2 DEFAULT SYSUTCDATETIME() NOT NULL
                    );
                END
            """)

            cursor.execute("""
                IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[normalization_log]') AND type in (N'U'))
                BEGIN
                    CREATE TABLE [dbo].[normalization_log] (
                        [id] INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
                        [session_id] NVARCHAR(100) NOT NULL,
                        [field_name] NVARCHAR(100) NULL,
                        [raw_value] NVARCHAR(500) NULL,
                        [normalized_value] NVARCHAR(500) NULL,
                        [row_count_affected] INT NULL,
                        [logged_at] DATETIME2 DEFAULT SYSUTCDATETIME() NOT NULL
                    );
                END
            """)

            cursor.execute("""
                IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[reports]') AND type in (N'U'))
                BEGIN
                    CREATE TABLE [dbo].[reports] (
                        [id] INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
                        [session_id] NVARCHAR(100) NOT NULL,
                        [period_label] NVARCHAR(255) NULL,
                        [cadence] NVARCHAR(50) DEFAULT 'monthly' NULL,
                        [summary_json] NVARCHAR(MAX) NULL,
                        [variance_json] NVARCHAR(MAX) NULL,
                        [ai_insights_json] NVARCHAR(MAX) NULL,
                        [excel_path] NVARCHAR(1000) NULL,
                        [pdf_path] NVARCHAR(1000) NULL,
                        [generated_at] DATETIME2 DEFAULT SYSUTCDATETIME() NOT NULL
                    );
                END
            """)

            cursor.execute("""
                IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[settings]') AND type in (N'U'))
                BEGIN
                    CREATE TABLE [dbo].[settings] (
                        [key] NVARCHAR(100) NOT NULL PRIMARY KEY,
                        [value] NVARCHAR(MAX) NULL,
                        [updated_at] DATETIME2 DEFAULT SYSUTCDATETIME() NOT NULL
                    );
                END
            """)

            # Indexes
            cursor.execute("IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'IX_reports_gen' AND object_id = OBJECT_ID('[dbo].[reports]')) CREATE NONCLUSTERED INDEX [IX_reports_gen] ON [dbo].[reports]([generated_at] DESC);")
            cursor.execute("IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'IX_tasks_session' AND object_id = OBJECT_ID('[dbo].[tasks]')) CREATE NONCLUSTERED INDEX [IX_tasks_session] ON [dbo].[tasks]([session_id]);")
            cursor.execute("IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'IX_tasks_emp' AND object_id = OBJECT_ID('[dbo].[tasks]')) CREATE NONCLUSTERED INDEX [IX_tasks_emp] ON [dbo].[tasks]([employee]);")

        else:
            # SQLite DDL
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS uploads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    filename TEXT,
                    period_label TEXT,
                    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
                    employee_hint TEXT,
                    row_count INTEGER
                );
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
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
                    week TEXT,
                    university TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
                );
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS normalization_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    field_name TEXT,
                    raw_value TEXT,
                    normalized_value TEXT,
                    row_count_affected INTEGER,
                    logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
                );
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    period_label TEXT,
                    cadence TEXT DEFAULT 'monthly',
                    summary_json TEXT,
                    variance_json TEXT,
                    ai_insights_json TEXT,
                    excel_path TEXT,
                    pdf_path TEXT,
                    generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
                );
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
                );
            """)

        # Migrations: add columns that were introduced after older deployments
        # already created these tables (CREATE TABLE IF NOT EXISTS never alters them).
        column_migrations = [
            ("reports", "cadence", "NVARCHAR(50) DEFAULT 'monthly' NULL", "TEXT DEFAULT 'monthly'"),
            ("uploads", "period_label", "NVARCHAR(255) NULL", "TEXT"),
            ("tasks", "university", "NVARCHAR(255) NULL", "TEXT"),
        ]
        for table, column, ms_type, sqlite_type in column_migrations:
            if is_ms:
                cursor.execute(f"""
                    IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID(N'[dbo].[{table}]') AND name = '{column}')
                    ALTER TABLE [dbo].[{table}] ADD [{column}] {ms_type};
                """)
            else:
                cursor.execute(f"PRAGMA table_info({table})")
                existing_cols = {row[1] for row in cursor.fetchall()}
                if column not in existing_cols:
                    cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {sqlite_type}")

        conn.commit()
    finally:
        conn.close()


# ─── DATA PERSISTENCE & REPORTS ─────────────────────────────────────

def save_session_data(
    session_id: str,
    uploads_info: List[Dict[str, Any]],
    normalized_df: pd.DataFrame,
    norm_log: List[Dict[str, Any]],
    aggregates: Dict[str, Any],
    variance_data: Dict[str, Any],
    ai_insights: Dict[str, Any],
    excel_path: str,
    pdf_path: str,
    cadence: str = "consolidated"
) -> int:
    """Persists uploaded tasks, normalization audit, and calculated report."""
    init_database()
    conn = db_mgr.get_raw_connection()
    is_ms = db_mgr.is_sql_server()

    try:
        cursor = conn.cursor()

        # 1. Save Uploads
        for up in uploads_info:
            cursor.execute("""
                INSERT INTO uploads (session_id, filename, period_label, employee_hint, row_count)
                VALUES (?, ?, ?, ?, ?)
            """, (
                session_id,
                up.get("filename"),
                aggregates.get("period_label", ""),
                up.get("detected_employee"),
                up.get("row_count")
            ))

        # 2. Save Tasks
        task_rows = []
        for _, row in normalized_df.iterrows():
            def _clean_num(val):
                if pd.isna(val):
                    return None
                try:
                    return float(val)
                except (ValueError, TypeError):
                    return None

            task_rows.append((
                session_id,
                None,
                str(row.get("Date", "") or ""),
                str(row.get("Service", "") or ""),
                str(row.get("Employee", "") or ""),
                str(row.get("Task", "") or ""),
                str(row.get("Description", "") or ""),
                str(row.get("Status", "") or ""),
                _clean_num(row.get("Expected Hours")),
                _clean_num(row.get("Actual Hours")),
                str(row.get("Task Type", "") or ""),
                str(row.get("Stack", "") or ""),
                str(row.get("Priority", "") or ""),
                str(row.get("Start Date", "") or ""),
                str(row.get("End Date", "") or ""),
                str(row.get("Week", "") or ""),
                str(row.get("Service", "") or "")
            ))

        if task_rows:
            insert_tasks_sql = """
                INSERT INTO tasks (
                    session_id, upload_id, date, service, employee, task, description,
                    status, expected_hrs, actual_hrs, task_type, stack, priority,
                    start_date, end_date, week, university
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            cursor.executemany(insert_tasks_sql, task_rows)

        # 3. Save Normalization Log
        log_rows = []
        for entry in norm_log:
            log_rows.append((
                session_id,
                entry.get("field_name"),
                str(entry.get("raw_value", "") or ""),
                str(entry.get("normalized_value", "") or ""),
                int(entry.get("row_count_affected", 0) or 0)
            ))

        if log_rows:
            cursor.executemany("""
                INSERT INTO normalization_log (
                    session_id, field_name, raw_value, normalized_value, row_count_affected
                ) VALUES (?, ?, ?, ?, ?)
            """, log_rows)

        # 4. Save Report
        if is_ms:
            cursor.execute("""
                INSERT INTO reports (
                    session_id, period_label, cadence, summary_json, variance_json,
                    ai_insights_json, excel_path, pdf_path
                )
                OUTPUT INSERTED.id
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                session_id,
                aggregates.get("period_label", ""),
                cadence,
                json.dumps(aggregates),
                json.dumps(variance_data),
                json.dumps(ai_insights),
                excel_path,
                pdf_path
            ))
            report_id = cursor.fetchone()[0]
        else:
            cursor.execute("""
                INSERT INTO reports (
                    session_id, period_label, cadence, summary_json, variance_json,
                    ai_insights_json, excel_path, pdf_path
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                session_id,
                aggregates.get("period_label", ""),
                cadence,
                json.dumps(aggregates),
                json.dumps(variance_data),
                json.dumps(ai_insights),
                excel_path,
                pdf_path
            ))
            report_id = cursor.lastrowid

        conn.commit()
        return int(report_id)
    finally:
        conn.close()


def get_latest_report() -> Optional[Dict[str, Any]]:
    """Retrieves the latest generated report."""
    init_database()
    conn = db_mgr.get_raw_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, session_id, generated_at, period_label, summary_json, variance_json, ai_insights_json, excel_path, pdf_path, cadence
            FROM reports
            ORDER BY id DESC
        """)
        row = cursor.fetchone()
        if not row:
            return None

        return {
            "id": row[0],
            "session_id": row[1],
            "generated_at": str(row[2]),
            "period_label": row[3],
            "summary": json.loads(row[4]) if row[4] else {},
            "variance": json.loads(row[5]) if row[5] else {},
            "ai_insights": json.loads(row[6]) if row[6] else {},
            "excel_path": row[7],
            "pdf_path": row[8],
            "cadence": row[9]
        }
    finally:
        conn.close()


def get_report_by_id(report_id: int) -> Optional[Dict[str, Any]]:
    """Retrieves report by ID."""
    init_database()
    conn = db_mgr.get_raw_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, session_id, generated_at, period_label, summary_json, variance_json, ai_insights_json, excel_path, pdf_path, cadence
            FROM reports
            WHERE id = ?
        """, (report_id,))
        row = cursor.fetchone()
        if not row:
            return None

        return {
            "id": row[0],
            "session_id": row[1],
            "generated_at": str(row[2]),
            "period_label": row[3],
            "summary": json.loads(row[4]) if row[4] else {},
            "variance": json.loads(row[5]) if row[5] else {},
            "ai_insights": json.loads(row[6]) if row[6] else {},
            "excel_path": row[7],
            "pdf_path": row[8],
            "cadence": row[9]
        }
    finally:
        conn.close()


def get_all_reports() -> List[Dict[str, Any]]:
    """Fetches all past reports ordered by ID descending."""
    init_database()
    conn = db_mgr.get_raw_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, session_id, generated_at, period_label, summary_json, excel_path, pdf_path, cadence
            FROM reports
            ORDER BY id DESC
        """)
        rows = cursor.fetchall()
        reports = []
        for r in rows:
            summary_raw = r[4]
            summary = json.loads(summary_raw) if summary_raw else {}
            reports.append({
                "id": r[0],
                "session_id": r[1],
                "generated_at": str(r[2]),
                "period_label": r[3],
                "totals": summary.get("totals", {}),
                "entity_label": summary.get("entity_label", "Service"),
                "month_label": summary.get("month_label", ""),
                "excel_path": r[5],
                "pdf_path": r[6],
                "cadence": r[7] or "consolidated"
            })
        return reports
    finally:
        conn.close()


def check_db_health() -> Dict[str, Any]:
    """Returns status of database and current connection engine."""
    engine = "Microsoft SQL Server" if db_mgr.is_sql_server() else "SQLite"
    status = "healthy"
    details = {}

    try:
        conn = db_mgr.get_raw_connection()
        cursor = conn.cursor()
        if db_mgr.is_sql_server():
            cursor.execute("SELECT @@VERSION, DB_NAME(), @@SERVERNAME")
            row = cursor.fetchone()
            details = {
                "server": str(row[2]),
                "database": str(row[1]),
                "version": str(row[0]).split("\n")[0],
                "driver": get_available_driver()
            }
        else:
            cursor.execute("SELECT sqlite_version()")
            row = cursor.fetchone()
            details = {
                "database_path": SQLITE_DB_PATH,
                "sqlite_version": str(row[0]),
                "note": "Active local SQLite persistence (SQL Server fallback)"
            }
        conn.close()
    except Exception as e:
        status = "degraded"
        details["error"] = str(e)

    return {
        "status": status,
        "database_engine": engine,
        "is_sql_server": db_mgr.is_sql_server(),
        "details": details
    }


def clear_all_data() -> None:
    """Wipes all records and resets tables to a completely clean slate."""
    init_database()
    conn = db_mgr.get_raw_connection()
    try:
        cursor = conn.cursor()
        for t in ["tasks", "normalization_log", "reports", "uploads", "settings"]:
            try:
                cursor.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        conn.commit()
    finally:
        conn.close()
