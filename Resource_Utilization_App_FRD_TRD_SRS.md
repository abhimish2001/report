# Team Resource Utilization Reporting System
## Functional Requirements Document (FRD) · Technical Requirements Document (TRD) · Software Requirements Specification (SRS)

**Version:** 1.0
**Date:** September 2026
**Scope:** Single-user, local desktop application for one manager to consolidate employee Excel/CSV task sheets into an automated, AI-narrated resource utilization report.

---

## 1. Purpose & Background

Currently, each employee maintains their own task-tracking Excel/CSV sheet (date, service/university, task, task type, expected vs. actual hours, status). At the end of the reporting period, the manager receives these individually and must manually consolidate them into a single Resource Utilization Report (as seen in the reference files: a 483-row task CSV rolled up into a 4-sheet Excel workbook and two HTML dashboards).

This manual consolidation is time-consuming and error-prone — most notably, the source data itself contains inconsistent casing and spacing in employee names, service/university names, and task-type labels (e.g., `JIWAJI` vs `Jiwaji`, `Amit Sondhiya` vs `amit Sondhiya`, `Support` vs `support`), which silently fragments totals if not corrected before aggregation.

**Goal:** Build a local application where the manager uploads one or more employee Excel/CSV files, and the system automatically reads, cleans, consolidates, calculates, and AI-narrates a complete report — with zero manual data entry and zero change to how employees currently work.

---

## 2. Objectives

- Eliminate manual Excel consolidation by the manager.
- Tolerate variation in employee file formats (different column names/order).
- Automatically detect and correct data-quality issues (casing, whitespace, near-duplicate labels).
- Calculate planned-vs-actual variance at the employee, service/university, and work-type levels.
- Automatically flag overloaded employees and over-consuming services.
- Generate a written executive summary and recommendations via an AI model, not just raw tables.
- Export the finished report as Excel and PDF, matching the structure of the existing reference report.
- Run entirely on the manager's own PC — no server, no external database, no ongoing hosting cost.

---

## 3. Out of Scope (v1)

- Employee-facing login, daily task entry, or task assignment features.
- Multi-user access control / roles / permissions.
- Cloud hosting, multi-department deployment.
- Real-time collaboration or notifications.
- Historical trend storage across many months (each run is treated as a standalone report unless explicitly extended later — see §9).

---

## 4. User Roles

| Role | Description |
|---|---|
| Manager (sole user) | Uploads employee files, triggers report generation, reviews dashboard, downloads Excel/PDF output. |

There is no employee-facing role in v1 — employees continue working exactly as they do today, outside the application.

---

## 5. Functional Requirements (FRD)

### FR-1: File Upload
- FR-1.1: The manager can upload one or more `.xlsx`, `.xls`, or `.csv` files in a single session.
- FR-1.2: The system accepts files with differing column names/order across employees (see FR-2).
- FR-1.3: The system displays a short preview (row count, detected employee name if present, date range) per uploaded file before processing.

### FR-2: Column Mapping ("Excel Intelligence")
- FR-2.1: The system maintains a configurable alias list mapping common column-name variants to a unified schema: `Date`, `Service`, `Employee`, `Task`, `Description`, `Status`, `Expected Hours`, `Actual Hours`, `Task Type`, `Stack`, `Priority`, `Start Date`, `End Date`.
- FR-2.2: If a required column cannot be confidently matched, the system prompts the manager to manually map it before proceeding (a one-time mapping per new file layout).
- FR-2.3: Once mapped, all uploaded files are merged into a single unified dataset.

### FR-3: Data Normalization
- FR-3.1: Employee names are normalized for case and whitespace (e.g., `amit Sondhiya` → `Amit Sondhiya`).
- FR-3.2: Service/university names are normalized for case and whitespace (e.g., `JIWAJI`, `Jiwaji` → `Jiwaji`).
- FR-3.3: Task Type values are normalized against a synonym table (e.g., `New`, `Development` → `New Development`).
- FR-3.4: The system produces a **Data Quality Report** listing every normalization it applied, so the manager can review/correct the mapping before final calculation.
- FR-3.5: Rows with missing Expected or Actual hours are flagged, not silently dropped or zero-filled.

### FR-4: Calculation Engine
- FR-4.1: Total tasks, expected hours, actual hours, and variance (actual − expected) computed overall and broken down by:
  - Employee
  - Service/University
  - Task Type
  - Week (derived from Date)
  - Employee × Service × Task Type (cross-tab)
- FR-4.2: Status counts (Completed / In Progress / Pending) computed overall and per employee/service.
- FR-4.3: Utilization % per employee = Actual Hours ÷ configurable expected-capacity baseline (default: sum of that employee's own Expected Hours, or a fixed weekly capacity if supplied).

### FR-5: Attention / Overload Detection
- FR-5.1: The system flags any employee or service whose Actual Hours exceed Expected Hours by more than a configurable threshold (default 110%).
- FR-5.2: The system surfaces the top N (default 5) "attention areas" across employees, services, and task types.

### FR-6: AI-Generated Insights
- FR-6.1: The calculated aggregates (not raw task rows) are sent to an LLM API as structured JSON.
- FR-6.2: The AI returns: an Executive Summary paragraph, a bulleted Key Findings list, and a Recommendations list.
- FR-6.3: The AI provider is configurable/swappable (see TRD §3) and the feature must degrade gracefully — if no AI key is configured or the call fails, the report still generates with all calculated tables, just without the narrative section.

### FR-7: Report Output
- FR-7.1: The system renders an in-app dashboard view of all calculated sections (mirroring the structure of the reference HTML dashboards: Work-Type Utilization, Resource-wise Utilization, Service-wise Utilization, Weekly Utilization, Most Overloaded Work, Attention Points).
- FR-7.2: The system exports an Excel workbook with sheets equivalent to the reference report (Resource Utilization, Service-wise Utilization, Horizontal-View, Summary).
- FR-7.3: The system exports a PDF version of the dashboard suitable for sharing/printing.
- FR-7.4: All exports are saved locally to a designated output folder with a date-stamped filename.

### FR-8: Data Quality Transparency
- FR-8.1: Before finalizing, the manager can review a diff-style summary of every raw value that was normalized (e.g., "6 variants of employee names merged into 6 people; `amit Sondhiya` (11 rows) merged into `Amit Sondhiya`").
- FR-8.2: The manager can manually override any auto-normalization before final calculation.

---

## 6. Technical Requirements (TRD)

### 6.1 Architecture Overview

```
Manager's Browser (localhost)
        │
        ▼
FastAPI app (Python, runs locally)
        │
  ┌─────┼──────────────┬────────────────┐
  ▼     ▼               ▼                ▼
Excel   Normalization   Calculation      AI Insights
Reader  Engine          Engine           (LLM API call)
  │     │               │                │
  └─────┴───────────────┴────────────────┘
                │
                ▼
        SQLite (local file)
                │
                ▼
     Excel / PDF / Dashboard Output
```

### 6.2 Technology Stack

| Layer | Technology | Rationale |
|---|---|---|
| Runtime | Python 3.11+ | Best-in-class for Excel/CSV wrangling |
| Web framework | FastAPI (+ Uvicorn) | Lightweight local server, minimal setup |
| Data processing | pandas | Core aggregation and normalization engine |
| Excel I/O | openpyxl | Read varied employee formats; write final workbook |
| Fuzzy header matching | `rapidfuzz` or `difflib` (stdlib) | Column-name alias detection |
| Database | SQLite (via `sqlite3` or SQLAlchemy) | Zero-install, single-file, sufficient for one user |
| PDF export | WeasyPrint or ReportLab | Render dashboard/report to PDF |
| Frontend | Jinja2-rendered HTML/CSS/JS (or lightweight React if a richer UI is wanted later) | No SPA complexity needed for one user |
| Charts | Chart.js (client-side) or matplotlib (server-rendered for PDF) | Matches dashboard visuals in reference HTML files |
| AI integration | Pluggable LLM client module — supports any OpenAI-compatible free-tier API (e.g., Groq, Google Gemini free tier) or a local model via Ollama | Avoids vendor lock-in; "free AI" requirement |
| Packaging (optional) | PyInstaller | Package as a double-clickable local app if needed |

### 6.3 Data Model (SQLite)

| Table | Key Fields |
|---|---|
| `uploads` | id, filename, uploaded_at, employee_hint, row_count |
| `tasks` | id, upload_id, date, service, employee, task, description, status, expected_hrs, actual_hrs, task_type, stack, priority, start_date, end_date |
| `normalization_log` | id, field_name, raw_value, normalized_value, row_count_affected |
| `reports` | id, generated_at, period_start, period_end, summary_json |
| `ai_insights` | id, report_id, executive_summary, key_findings_json, recommendations_json |

### 6.4 Non-Functional Requirements

- **Performance:** Must process at least 5,000 task rows across multiple files in under 10 seconds on a standard office PC.
- **Reliability:** Report generation must not fail outright if the AI call errors — falls back to calculated tables only (per FR-6.3).
- **Portability:** No external server dependency; runs via `python app.py` or a packaged executable.
- **Data integrity:** Original uploaded files are preserved unmodified on disk; all normalization happens on a copy in the processing pipeline.
- **Auditability:** Every normalization decision is logged and reviewable (FR-8).

### 6.5 AI Integration Contract

Example payload sent to the LLM API (structured, not raw rows):

```json
{
  "period": "01-Aug-2026 to 31-Aug-2026",
  "totals": {"tasks": 483, "expected_hrs": 779, "actual_hrs": 843.75},
  "by_work_type": [
    {"type": "Support", "tasks": 266, "expected": 357.5, "actual": 373.75}
  ],
  "by_employee": [
    {"name": "Vandna Khare", "tasks": 87, "expected": 130.5, "actual": 187.0}
  ],
  "by_service": [
    {"name": "Jiwaji", "tasks": 87, "expected": 184.0, "actual": 204.0}
  ],
  "attention_flags": [
    {"type": "employee", "name": "Vandna Khare", "overrun_pct": 43.3}
  ]
}
```

Expected response shape: `{ "executive_summary": "...", "key_findings": ["..."], "recommendations": ["..."] }`

---

## 7. Software Requirements Specification (SRS) Summary

| # | Requirement | Priority |
|---|---|---|
| SRS-1 | Accept multiple Excel/CSV uploads with varying column layouts | Must |
| SRS-2 | Map differing headers to a unified schema, with manual override | Must |
| SRS-3 | Normalize employee, service, and task-type text values | Must |
| SRS-4 | Present a data-quality/normalization report before finalizing | Must |
| SRS-5 | Calculate hours/variance by employee, service, task type, week | Must |
| SRS-6 | Flag overloaded employees/services against a configurable threshold | Must |
| SRS-7 | Generate AI executive summary and recommendations | Should |
| SRS-8 | Export Excel (4-sheet) and PDF reports | Must |
| SRS-9 | In-app dashboard view | Must |
| SRS-10 | Run fully locally with no external server dependency | Must |
| SRS-11 | Degrade gracefully if AI API is unavailable | Should |
| SRS-12 | Support historical multi-period storage | Could (future) |

---

## 8. Assumptions

- Files always contain, at minimum, Date, Employee, Task, Status, and either Expected or Actual hours — Service and Task Type may occasionally be blank and should be handled as "Unspecified" rather than failing the row.
- The manager is the sole judge of correct normalization; the system suggests, the manager confirms.
- "Free AI" means a no-cost or low-cost LLM API tier; the exact provider is a runtime configuration choice, not hardcoded.

## 9. Future Enhancements (Post-v1)

- Multi-period trend storage and month-over-month comparison.
- Multi-user manager accounts if the tool is shared across departments.
- Automatic weekly scheduled report generation.
- Direct email delivery of the generated PDF.

---
*Reference source for requirements: `TaskStatus-202608(Input File).csv` (483 rows, Aug 2026) and `Resource Utilization Report.xlsx` (4 sheets: Resource Utilization, Service-wise Utilization, Horizontal-View, Summary).*
