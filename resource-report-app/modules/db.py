"""
db.py
SQL Server persistence manager for the Team Resource Utilization Reporting System.
Uses Microsoft SQL Server exclusively via pyodbc.
All tables use SQL Server DDL. No SQLite fallback.

Tables:
- uploads         : Uploaded file metadata
- tasks           : Individual task rows from uploaded sheets
- normalization_log: Audit log of data normalization steps
- reports         : Generated report snapshots (JSON summary + file paths)
- settings        : Key-value system configuration
- users           : Registered users (TL / PM / MEMBER)
- user_sessions   : Active login session tokens
"""

from __future__ import annotations
import json
import logging
import os
from typing import Any, Dict, List, Optional
import pandas as pd

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


# ── Connection helpers ─────────────────────────────────────────────────────────

def _get_driver() -> str:
    """Picks the best installed ODBC driver for SQL Server."""
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


def _build_connection_string() -> str:
    """Builds the ODBC connection string from environment variables."""
    override = os.environ.get("SQL_SERVER_CONN_STRING", "").strip()
    if override:
        return override

    driver   = _get_driver()
    host     = os.environ.get("SQL_SERVER_HOST", "localhost").strip()
    port     = os.environ.get("SQL_SERVER_PORT", "1433").strip()
    database = os.environ.get("SQL_SERVER_DATABASE", "ResourceUtilizationDB").strip()
    trusted  = os.environ.get("SQL_SERVER_TRUSTED_CONNECTION", "yes").strip().lower()
    user     = os.environ.get("SQL_SERVER_USER", "").strip()
    password = os.environ.get("SQL_SERVER_PASSWORD", "").strip()
    trust_cert = os.environ.get("SQL_SERVER_TRUST_CERTIFICATE", "yes").strip().lower()
    encrypt    = os.environ.get("SQL_SERVER_ENCRYPT", "no").strip().lower()

    server = f"{host},{port}" if (port and port != "1433" and "\\" not in host) else host

    parts = [
        f"DRIVER={{{driver}}}",
        f"SERVER={server}",
        f"DATABASE={database}",
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


def get_connection():
    """Opens and returns a fresh pyodbc connection to SQL Server."""
    conn_str = _build_connection_string()
    try:
        return pyodbc.connect(conn_str, timeout=10, autocommit=False)
    except pyodbc.Error as e:
        logger.error("SQL Server connection failed: %s", e)
        raise RuntimeError(
            f"Cannot connect to SQL Server. Check your .env configuration.\nDetails: {e}"
        ) from e


# Keep a thin manager shim so app.py / auth.py imports continue to work
class _DbManager:
    def get_raw_connection(self):
        return get_connection()

    @staticmethod
    def is_sql_server() -> bool:
        return True


db_mgr = _DbManager()


# ── Schema Init ───────────────────────────────────────────────────────────────

_DDL_STATEMENTS = [
    # uploads
    """
    IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[uploads]') AND type = N'U')
    CREATE TABLE [dbo].[uploads] (
        [id]           INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        [session_id]   NVARCHAR(100)     NOT NULL,
        [filename]     NVARCHAR(500)     NULL,
        [period_label] NVARCHAR(255)     NULL,
        [uploaded_at]  DATETIME2         DEFAULT SYSUTCDATETIME() NOT NULL,
        [employee_hint]NVARCHAR(255)     NULL,
        [row_count]    INT               NULL
    );
    """,
    # tasks
    """
    IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[tasks]') AND type = N'U')
    CREATE TABLE [dbo].[tasks] (
        [id]          INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        [session_id]  NVARCHAR(100)     NOT NULL,
        [upload_id]   INT               NULL,
        [date]        NVARCHAR(50)      NULL,
        [service]     NVARCHAR(255)     NULL,
        [employee]    NVARCHAR(255)     NULL,
        [task]        NVARCHAR(500)     NULL,
        [description] NVARCHAR(MAX)     NULL,
        [status]      NVARCHAR(100)     NULL,
        [expected_hrs]FLOAT             NULL,
        [actual_hrs]  FLOAT             NULL,
        [task_type]   NVARCHAR(255)     NULL,
        [stack]       NVARCHAR(255)     NULL,
        [priority]    NVARCHAR(100)     NULL,
        [start_date]  NVARCHAR(50)      NULL,
        [end_date]    NVARCHAR(50)      NULL,
        [week]        NVARCHAR(100)     NULL,
        [university]  NVARCHAR(255)     NULL,
        [created_at]  DATETIME2         DEFAULT SYSUTCDATETIME() NOT NULL
    );
    """,
    # normalization_log
    """
    IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[normalization_log]') AND type = N'U')
    CREATE TABLE [dbo].[normalization_log] (
        [id]                INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        [session_id]        NVARCHAR(100)     NOT NULL,
        [field_name]        NVARCHAR(100)     NULL,
        [raw_value]         NVARCHAR(500)     NULL,
        [normalized_value]  NVARCHAR(500)     NULL,
        [row_count_affected]INT               NULL,
        [logged_at]         DATETIME2         DEFAULT SYSUTCDATETIME() NOT NULL
    );
    """,
    # reports
    """
    IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[reports]') AND type = N'U')
    CREATE TABLE [dbo].[reports] (
        [id]               INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        [session_id]       NVARCHAR(100)     NOT NULL,
        [period_label]     NVARCHAR(255)     NULL,
        [cadence]          NVARCHAR(50)      DEFAULT 'monthly' NULL,
        [summary_json]     NVARCHAR(MAX)     NULL,
        [variance_json]    NVARCHAR(MAX)     NULL,
        [ai_insights_json] NVARCHAR(MAX)     NULL,
        [excel_path]       NVARCHAR(1000)    NULL,
        [pdf_path]         NVARCHAR(1000)    NULL,
        [generated_at]     DATETIME2         DEFAULT SYSUTCDATETIME() NOT NULL
    );
    """,
    # settings
    """
    IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[settings]') AND type = N'U')
    CREATE TABLE [dbo].[settings] (
        [key]        NVARCHAR(100) NOT NULL PRIMARY KEY,
        [value]      NVARCHAR(MAX) NULL,
        [updated_at] DATETIME2     DEFAULT SYSUTCDATETIME() NOT NULL
    );
    """,
    # users
    """
    IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[users]') AND type = N'U')
    CREATE TABLE [dbo].[users] (
        [id]            INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        [email]         NVARCHAR(255)     NOT NULL UNIQUE,
        [name]          NVARCHAR(255)     NULL,
        [password_hash] NVARCHAR(255)     NOT NULL,
        [role]          NVARCHAR(50)      NOT NULL,
        [manager_id]    INT               NULL,
        [created_at]    DATETIME2         DEFAULT SYSUTCDATETIME() NOT NULL
    );
    """,
    # user_sessions
    """
    IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[user_sessions]') AND type = N'U')
    CREATE TABLE [dbo].[user_sessions] (
        [session_token] NVARCHAR(100) NOT NULL PRIMARY KEY,
        [user_id]       INT           NOT NULL,
        [expires_at]    DATETIME2     NOT NULL,
        [created_at]    DATETIME2     DEFAULT SYSUTCDATETIME() NOT NULL
    );
    """,
    # indexes
    "IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'IX_reports_gen'   AND object_id = OBJECT_ID('[dbo].[reports]')) CREATE NONCLUSTERED INDEX [IX_reports_gen]   ON [dbo].[reports]([generated_at] DESC);",
    "IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'IX_tasks_session' AND object_id = OBJECT_ID('[dbo].[tasks]'))   CREATE NONCLUSTERED INDEX [IX_tasks_session] ON [dbo].[tasks]([session_id]);",
    "IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'IX_tasks_emp'     AND object_id = OBJECT_ID('[dbo].[tasks]'))   CREATE NONCLUSTERED INDEX [IX_tasks_emp]     ON [dbo].[tasks]([employee]);",
]

# Column migrations for tables that may already exist from older deployments
_COLUMN_MIGRATIONS = [
    ("reports", "cadence",    "NVARCHAR(50) DEFAULT 'monthly' NULL"),
    ("uploads",  "period_label", "NVARCHAR(255) NULL"),
    ("tasks",    "university", "NVARCHAR(255) NULL"),
]


def init_database() -> None:
    """Creates all SQL Server tables and runs column migrations if needed."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        for ddl in _DDL_STATEMENTS:
            cursor.execute(ddl)
        for table, column, col_type in _COLUMN_MIGRATIONS:
            cursor.execute(f"""
                IF NOT EXISTS (
                    SELECT * FROM sys.columns
                    WHERE object_id = OBJECT_ID(N'[dbo].[{table}]') AND name = '{column}'
                )
                ALTER TABLE [dbo].[{table}] ADD [{column}] {col_type};
            """)
        conn.commit()
        logger.info("Database schema initialised successfully.")
    except Exception as e:
        logger.error("init_database failed: %s", e)
        raise
    finally:
        conn.close()


# ── Data persistence ──────────────────────────────────────────────────────────

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
    cadence: str = "consolidated",
) -> int:
    """Persists uploaded tasks, normalization audit, and calculated report to SQL Server."""
    conn = get_connection()
    try:
        cursor = conn.cursor()

        # 1. Uploads
        for up in uploads_info:
            cursor.execute("""
                INSERT INTO uploads (session_id, filename, period_label, employee_hint, row_count)
                VALUES (?, ?, ?, ?, ?)
            """, (
                session_id,
                up.get("filename"),
                aggregates.get("period_label", ""),
                up.get("detected_employee"),
                up.get("row_count"),
            ))

        # 2. Tasks
        def _num(val):
            if pd.isna(val):
                return None
            try:
                return float(val)
            except (ValueError, TypeError):
                return None

        task_rows = [
            (
                session_id, None,
                str(row.get("Date", "") or ""),
                str(row.get("Service", "") or ""),
                str(row.get("Employee", "") or ""),
                str(row.get("Task", "") or ""),
                str(row.get("Description", "") or ""),
                str(row.get("Status", "") or ""),
                _num(row.get("Expected Hours")),
                _num(row.get("Actual Hours")),
                str(row.get("Task Type", "") or ""),
                str(row.get("Stack", "") or ""),
                str(row.get("Priority", "") or ""),
                str(row.get("Start Date", "") or ""),
                str(row.get("End Date", "") or ""),
                str(row.get("Week", "") or ""),
                str(row.get("Service", "") or ""),
            )
            for _, row in normalized_df.iterrows()
        ]
        if task_rows:
            cursor.executemany("""
                INSERT INTO tasks (
                    session_id, upload_id, date, service, employee, task, description,
                    status, expected_hrs, actual_hrs, task_type, stack, priority,
                    start_date, end_date, week, university
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, task_rows)

        # 3. Normalization log
        log_rows = [
            (
                session_id,
                entry.get("field_name"),
                str(entry.get("raw_value", "") or ""),
                str(entry.get("normalized_value", "") or ""),
                int(entry.get("row_count_affected", 0) or 0),
            )
            for entry in norm_log
        ]
        if log_rows:
            cursor.executemany("""
                INSERT INTO normalization_log (session_id, field_name, raw_value, normalized_value, row_count_affected)
                VALUES (?, ?, ?, ?, ?)
            """, log_rows)

        # 4. Report (SQL Server OUTPUT clause returns the new ID)
        cursor.execute("""
            INSERT INTO reports (session_id, period_label, cadence, summary_json, variance_json, ai_insights_json, excel_path, pdf_path)
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
            pdf_path,
        ))
        report_id = cursor.fetchone()[0]
        conn.commit()
        return int(report_id)
    finally:
        conn.close()


def _row_to_report(row) -> Dict[str, Any]:
    return {
        "id":           row[0],
        "session_id":   row[1],
        "generated_at": str(row[2]),
        "period_label": row[3],
        "summary":      json.loads(row[4]) if row[4] else {},
        "variance":     json.loads(row[5]) if row[5] else {},
        "ai_insights":  json.loads(row[6]) if row[6] else {},
        "excel_path":   row[7],
        "pdf_path":     row[8],
        "cadence":      row[9] or "consolidated",
    }


def get_latest_report() -> Optional[Dict[str, Any]]:
    """Returns the most recently generated report."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT TOP 1 id, session_id, generated_at, period_label,
                   summary_json, variance_json, ai_insights_json, excel_path, pdf_path, cadence
            FROM reports
            ORDER BY id DESC
        """)
        row = cursor.fetchone()
        return _row_to_report(row) if row else None
    finally:
        conn.close()


def get_report_by_id(report_id: int) -> Optional[Dict[str, Any]]:
    """Returns a specific report by primary key."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, session_id, generated_at, period_label,
                   summary_json, variance_json, ai_insights_json, excel_path, pdf_path, cadence
            FROM reports
            WHERE id = ?
        """, (report_id,))
        row = cursor.fetchone()
        return _row_to_report(row) if row else None
    finally:
        conn.close()


def get_all_reports() -> List[Dict[str, Any]]:
    """Returns all reports ordered newest first."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, session_id, generated_at, period_label,
                   summary_json, excel_path, pdf_path, cadence
            FROM reports
            ORDER BY id DESC
        """)
        rows = cursor.fetchall()
        result = []
        for r in rows:
            summary = json.loads(r[4]) if r[4] else {}
            result.append({
                "id":           r[0],
                "session_id":   r[1],
                "generated_at": str(r[2]),
                "period_label": r[3],
                "totals":       summary.get("totals", {}),
                "entity_label": summary.get("entity_label", "Service"),
                "month_label":  summary.get("month_label", ""),
                "excel_path":   r[5],
                "pdf_path":     r[6],
                "cadence":      r[7] or "consolidated",
            })
        return result
    finally:
        conn.close()


def check_db_health() -> Dict[str, Any]:
    """Returns SQL Server health information."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT @@VERSION, DB_NAME(), @@SERVERNAME")
        row = cursor.fetchone()
        conn.close()
        return {
            "status": "healthy",
            "database_engine": "Microsoft SQL Server",
            "is_sql_server": True,
            "details": {
                "server":   str(row[2]),
                "database": str(row[1]),
                "version":  str(row[0]).split("\n")[0],
                "driver":   _get_driver(),
            },
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "database_engine": "Microsoft SQL Server",
            "is_sql_server": True,
            "details": {"error": str(e)},
        }


def clear_all_data() -> None:
    """Wipes all task and report data (preserves users and sessions)."""
    conn = get_connection()
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


# ── Legacy compat shim ────────────────────────────────────────────────────────
def get_sql_server_connection_string() -> str:
    """Compat alias — returns the active connection string."""
    return _build_connection_string()
