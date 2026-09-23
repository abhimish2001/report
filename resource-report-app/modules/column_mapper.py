"""
column_mapper.py
Fuzzy-matches varying column headers from different employee sheets to a unified schema:
['Date', 'Service', 'Employee', 'Task', 'Description', 'Status',
 'Expected Hours', 'Actual Hours', 'Task Type', 'Stack', 'Priority',
 'Start Date', 'End Date']
"""

from __future__ import annotations
import re
from typing import Any, Dict, List, Optional, Tuple
import pandas as pd

try:
    from rapidfuzz import fuzz
    HAS_RAPIDFUZZ = True
except ImportError:
    import difflib
    HAS_RAPIDFUZZ = False

# Canonical Target Schema
CANONICAL_COLUMNS = [
    "Date",
    "Service",
    "Employee",
    "Task",
    "Description",
    "Status",
    "Expected Hours",
    "Actual Hours",
    "Task Type",
    "Stack",
    "Priority",
    "Start Date",
    "End Date"
]

# Required columns without which resource calculation cannot properly happen
REQUIRED_COLUMNS = [
    "Date",
    "Employee",
    "Task",
    "Status"
]

# High priority columns (one or both hours, and service/task type)
CORE_NUMERIC_COLUMNS = [
    "Expected Hours",
    "Actual Hours"
]

# Team Profile Presets
TEAM_PRESETS: Dict[str, Dict[str, Any]] = {
    "universal": {
        "name": "Universal (Auto-Detect)",
        "entity_label": "Project / Client",
        "description": "Adaptive matching for any general business, tech, or operations team."
    },
    "education": {
        "name": "Higher Education & Services",
        "entity_label": "University",
        "description": "Optimized for university exam/admission services (Reference August 2026 format)."
    },
    "software": {
        "name": "Software & Product Development",
        "entity_label": "Project",
        "description": "Optimized for software engineering sprints, repos, and issue tracking."
    },
    "consulting": {
        "name": "Consulting & Client Agencies",
        "entity_label": "Client Account",
        "description": "Optimized for client accounts, billable work, and project deliverables."
    },
    "it_ops": {
        "name": "IT Operations & Helpdesk",
        "entity_label": "Service Queue",
        "description": "Optimized for IT support desks, incident response, and service requests."
    }
}


def get_team_presets() -> Dict[str, Dict[str, Any]]:
    """Returns catalog of team profile presets."""
    return TEAM_PRESETS


# Extensive alias catalog based on empirical team tracking formats
COLUMN_ALIASES: Dict[str, List[str]] = {
    "Date": [
        "date", "task date", "entry date", "work date", "dt", "day", "log date", "dated",
        "activity date"
    ],
    "Service": [
        "service", "university", "service / university", "service/university",
        "client", "project", "dept", "department", "account", "uni", "inst", "institution",
        "repo", "repository", "module", "engagement", "queue", "system"
    ],
    "Employee": [
        "employee", "assign to", "assigned to", "resource", "developer",
        "engineer", "owner", "team member", "emp name", "assignee", "user", "name", "staff"
    ],
    "Task": [
        "task", "task name", "task title", "work item", "ticket", "activity",
        "subject", "headline", "module", "item"
    ],
    "Description": [
        "description", "task description", "details", "work description",
        "summary", "remarks", "remark", "notes", "comments", "work detail"
    ],
    "Status": [
        "status", "task status", "state", "stage", "completion status", "progress"
    ],
    "Expected Hours": [
        "expected hours", "expected time", "est hours", "estimated hours",
        "planned hours", "exp hrs", "exp time", "expected hrs", "est time",
        "planned time", "estimate", "expected_hours", "expected_hrs"
    ],
    "Actual Hours": [
        "actual hours", "actual time", "spent hours", "time spent", "act hours",
        "act time", "actual hrs", "hours spent", "actuals", "duration",
        "actual_hours", "actual_hrs", "hrs", "time"
    ],
    "Task Type": [
        "task type", "work type", "type", "category", "task category",
        "activity type", "nature of work", "type of work", "work_type"
    ],
    "Stack": [
        "stack", "tech stack", "technology", "technologies", "tool", "tools",
        "skills", "platform", "language"
    ],
    "Priority": [
        "priority", "urgency", "severity", "importance", "prio"
    ],
    "Start Date": [
        "start date", "start", "start time", "started on", "begin date", "commenced"
    ],
    "End Date": [
        "end date", "end", "end time", "completed on", "finish date", "closed on",
        "completion date"
    ]
}


def _clean_str(s: str) -> str:
    """Normalize string for fuzzy comparison."""
    s = str(s).strip().lower()
    s = re.sub(r'[\s_\-\.\/\\]+', ' ', s)
    return s.strip()


def _match_similarity(a: str, b: str) -> float:
    """Returns a score between 0.0 and 1.0."""
    a_clean = _clean_str(a)
    b_clean = _clean_str(b)

    if a_clean == b_clean:
        return 1.0

    if HAS_RAPIDFUZZ:
        # Ratio of token sort
        return fuzz.token_sort_ratio(a_clean, b_clean) / 100.0
    else:
        matcher = difflib.SequenceMatcher(None, a_clean, b_clean)
        return matcher.ratio()


def detect_column_mappings(df_columns: List[str], threshold: float = 0.75) -> Dict[str, Dict]:
    """
    Analyzes raw DataFrame column names and produces best candidate mappings
    for each CANONICAL_COLUMN.

    Returns dict keyed by canonical_column:
    {
        "matched_raw": "Assign to" or None,
        "confidence": 0.95,
        "is_exact": False,
        "candidates": [("Assign to", 0.95), ...]
    }
    """
    raw_cols = [str(c).strip() for c in df_columns if c and not str(c).startswith("Unnamed")]
    assigned_raw: Dict[str, str] = {}
    mapping_results: Dict[str, Dict] = {}

    # 1. Exact canonical matches first
    for canon in CANONICAL_COLUMNS:
        canon_clean = _clean_str(canon)
        for raw in raw_cols:
            if _clean_str(raw) == canon_clean and raw not in assigned_raw.values():
                assigned_raw[canon] = raw
                mapping_results[canon] = {
                    "matched_raw": raw,
                    "confidence": 1.0,
                    "is_exact": True,
                    "candidates": [(raw, 1.0)]
                }
                break

    # 2. Exact alias matches
    for canon in CANONICAL_COLUMNS:
        if canon in assigned_raw:
            continue
        aliases = [_clean_str(a) for a in COLUMN_ALIASES.get(canon, [])]
        for raw in raw_cols:
            if raw in assigned_raw.values():
                continue
            raw_c = _clean_str(raw)
            if raw_c in aliases:
                assigned_raw[canon] = raw
                mapping_results[canon] = {
                    "matched_raw": raw,
                    "confidence": 0.95,
                    "is_exact": True,
                    "candidates": [(raw, 0.95)]
                }
                break

    # 3. Fuzzy matches for remaining columns
    for canon in CANONICAL_COLUMNS:
        if canon in assigned_raw:
            continue

        aliases = [_clean_str(a) for a in COLUMN_ALIASES.get(canon, [])]
        canon_clean = _clean_str(canon)
        all_targets = [canon_clean] + aliases

        scores: List[Tuple[str, float]] = []
        for raw in raw_cols:
            if raw in assigned_raw.values():
                continue
            raw_c = _clean_str(raw)
            best_score = max(_match_similarity(raw_c, target) for target in all_targets)
            if best_score >= threshold:
                scores.append((raw, round(best_score, 3)))

        scores.sort(key=lambda x: x[1], reverse=True)
        if scores:
            best_raw, best_conf = scores[0]
            assigned_raw[canon] = best_raw
            mapping_results[canon] = {
                "matched_raw": best_raw,
                "confidence": best_conf,
                "is_exact": False,
                "candidates": scores
            }
        else:
            mapping_results[canon] = {
                "matched_raw": None,
                "confidence": 0.0,
                "is_exact": False,
                "candidates": []
            }

    return mapping_results


def map_dataframe_to_schema(
    df: pd.DataFrame,
    explicit_mapping: Optional[Dict[str, str]] = None,
    default_employee: Optional[str] = None
) -> Tuple[pd.DataFrame, Dict[str, Optional[str]], List[str]]:
    """
    Transforms raw DataFrame into standard CANONICAL_COLUMNS format.

    - explicit_mapping: optional dict of {canonical_name: raw_column_name}
    - default_employee: fallback if employee column is missing from individual sheet
    
    Returns:
    - unified_df: DataFrame with all CANONICAL_COLUMNS present
    - final_mapping: {canonical_col: raw_col}
    - warnings: list of any missing critical fields or notices
    """
    df = df.copy()
    warnings: List[str] = []

    # Strip column strings
    df.columns = [str(c).strip() for c in df.columns]

    if explicit_mapping is not None:
        final_mapping = explicit_mapping
    else:
        detected = detect_column_mappings(list(df.columns))
        final_mapping = {canon: detected[canon]["matched_raw"] for canon in CANONICAL_COLUMNS}

    unified_data = {}

    for canon in CANONICAL_COLUMNS:
        raw_col = final_mapping.get(canon)
        if raw_col and raw_col in df.columns:
            unified_data[canon] = df[raw_col]
        else:
            # Fallback for Employee if provided externally (e.g. from filename)
            if canon == "Employee" and default_employee:
                unified_data[canon] = default_employee
                warnings.append(f"Field '{canon}' populated from file metadata ('{default_employee}').")
            else:
                unified_data[canon] = pd.Series([None] * len(df), index=df.index)
                if canon in REQUIRED_COLUMNS:
                    warnings.append(f"Required field '{canon}' could not be matched to any source column.")

    result_df = pd.DataFrame(unified_data, columns=CANONICAL_COLUMNS)

    # Preserve any source columns that didn't map to the canonical schema
    # instead of silently dropping them. Downstream code only ever reads
    # columns by their canonical name, so an extra column just rides along
    # unused unless something later wants it - but the data isn't lost.
    consumed_raws = {raw for raw in final_mapping.values() if raw}
    extra_columns = [c for c in df.columns if c not in consumed_raws]
    if extra_columns:
        for raw_col in extra_columns:
            # Guard against a leftover raw column sharing a name with a
            # canonical field (e.g. an explicit_mapping override left the
            # raw "Priority" column unconsumed) - never overwrite it.
            out_name = raw_col if raw_col not in result_df.columns else f"{raw_col} (unmapped)"
            result_df[out_name] = df[raw_col].values
        warnings.append(
            f"{len(extra_columns)} unmatched source column(s) preserved as-is: "
            f"{', '.join(extra_columns)}."
        )

    return result_df, final_mapping, warnings
