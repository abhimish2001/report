"""
normalizer.py
Dynamic, team-agnostic data normalization & cleaning engine.
- Auto-clusters similar text variants using string similarity (Levenshtein/token-sort).
- Reconciles casing, whitespace, and near-duplicates for any team domain (Engineering, Ops, Consulting, Marketing, etc.).
- Maintains extensible synonym dictionaries and logs all audit changes.
- Flags incomplete rows (missing hours or date) without silently dropping them.
"""

from __future__ import annotations
import re
from typing import Any, Dict, List, Optional, Set, Tuple
import pandas as pd
import numpy as np

try:
    from rapidfuzz import fuzz
    HAS_RAPIDFUZZ = True
except ImportError:
    import difflib
    HAS_RAPIDFUZZ = False


# Universal baseline task type synonyms (can be extended dynamically)
DEFAULT_TASK_TYPE_SYNONYMS: Dict[str, str] = {
    # Software & Tech
    "new": "New Development",
    "new dev": "New Development",
    "new development": "New Development",
    "dev": "New Development",
    "development": "New Development",
    "feature": "New Development",
    "enhancement": "Enhancement",
    "enhancements": "Enhancement",
    "support": "Support",
    "production support": "Support",
    "ops support": "Support",
    "issue": "Issue",
    "bug": "Issue",
    "bug fix": "Issue",
    "bugfix": "Issue",
    "defect": "Issue",
    "error": "Issue",
    "meeting": "Meeting",
    "client meeting": "Meeting",
    "internal meeting": "Meeting",
    "discussion": "Meeting",
    "other": "Other",
    "others": "Other",
    "misc": "Other",
    "documentation": "Other",
    "training": "Other",
    
    # Consulting & Professional Services
    "billable": "Billable Advisory",
    "advisory": "Billable Advisory",
    "consulting": "Consulting",
    "audit": "Audit & Review",
    "review": "Audit & Review",
    "discovery": "Discovery & Planning",
    "planning": "Discovery & Planning",
    
    # Operations & Support
    "incident": "Incident",
    "sev1": "Incident",
    "sev2": "Incident",
    "ticket": "Support Ticket",
    "service request": "Service Request",
    "change request": "Change Request",
    "cr": "Change Request",
    "change": "Change",
    
    # Marketing & Creative
    "campaign": "Campaign",
    "content": "Content Creation",
    "design": "Creative Design",
    "copywriting": "Content Creation",
    "seo": "SEO & Analytics"
}

# Known common institutional / project acronym mappings
COMMON_ACRONYM_MAP: Dict[str, str] = {
    "jiwaji": "JIWAJI",
    "bhoj": "BHOJ",
    "ralvv": "RALVV",
    "mgcgv": "MGCGV",
    "abvhv": "ABVHV",
    "aps": "APS",
    "kttv": "KTTV",
    "mcbu": "MCBU",
    "rble": "RBLE",
    "rblu": "RBLU",
    "comman": "Comman",
    "common": "Comman"
}


def normalize_text_clean(val: Any) -> str:
    """Strip whitespace and collapse multiple spaces."""
    if val is None or pd.isna(val):
        return ""
    s = str(val).strip()
    s = re.sub(r'[\r\n\t]+', ' ', s)
    s = re.sub(r'\s+', ' ', s)
    return s.strip()


def calculate_similarity(s1: str, s2: str) -> float:
    """Calculates string similarity ratio (0.0 to 1.0)."""
    c1 = s1.strip().lower()
    c2 = s2.strip().lower()
    if c1 == c2:
        return 1.0
    if not c1 or not c2:
        return 0.0
    if HAS_RAPIDFUZZ:
        return fuzz.token_sort_ratio(c1, c2) / 100.0
    else:
        import difflib
        return difflib.SequenceMatcher(None, c1, c2).ratio()


def cluster_similar_terms(
    values: List[str],
    similarity_threshold: float = 0.85
) -> Dict[str, str]:
    """
    Unsupervised clustering of near-duplicate text values across files.
    Identifies variations (e.g. 'Support Ops', 'support-ops', 'Support Operations')
    and clusters them to the most frequently occurring clean representation.
    """
    if not values:
        return {}

    # Count frequencies of cleaned non-empty values
    cleaned_counts: Dict[str, int] = {}
    for v in values:
        c = normalize_text_clean(v)
        if c and c.lower() not in ['nan', 'none', 'null', '']:
            cleaned_counts[c] = cleaned_counts.get(c, 0) + 1

    unique_terms = sorted(cleaned_counts.keys(), key=lambda x: cleaned_counts[x], reverse=True)
    cluster_map: Dict[str, str] = {}
    assigned: Set[str] = set()

    for term in unique_terms:
        if term in assigned:
            continue
        cluster_map[term] = term
        assigned.add(term)

        # Look for near-duplicates among lower frequency terms
        for other in unique_terms:
            if other in assigned:
                continue
            sim = calculate_similarity(term, other)
            if sim >= similarity_threshold:
                cluster_map[other] = term
                assigned.add(other)

    return cluster_map


def normalize_employee_name(raw_name: str) -> str:
    """
    Standardizes employee names to Title Case while handling special capitalizations.
    e.g. 'amit Sondhiya' -> 'Amit Sondhiya'
    """
    cleaned = normalize_text_clean(raw_name)
    if not cleaned or cleaned.lower() in ['nan', 'none', 'null', '']:
        return "Unassigned"

    parts = cleaned.split(' ')
    fixed_parts = [p.capitalize() for p in parts if p]
    return " ".join(fixed_parts)


def normalize_entity_name(raw_entity: str) -> str:
    """
    Standardizes entity (Service, Client, Project, Department, University).
    Preserves uppercase for acronyms (<= 6 chars or known acronyms), else Title Case.
    """
    cleaned = normalize_text_clean(raw_entity)
    if not cleaned or cleaned.lower() in ['nan', 'none', 'null', '']:
        return "Unspecified"

    key = cleaned.lower()
    if key in COMMON_ACRONYM_MAP:
        return COMMON_ACRONYM_MAP[key]

    # If short alphabetic string (e.g., NASA, AWS, CRM, HR, APS), preserve uppercase
    if len(cleaned) <= 6 and re.match(r'^[a-zA-Z0-9]+$', cleaned):
        return cleaned.upper()

    return cleaned.title()


def normalize_task_type(
    raw_type: str,
    synonym_table: Optional[Dict[str, str]] = None
) -> str:
    """
    Normalizes Task Type against synonym dictionary.
    """
    cleaned = normalize_text_clean(raw_type)
    if not cleaned or cleaned.lower() in ['nan', 'none', 'null', '']:
        return "Support"

    synonyms = synonym_table or DEFAULT_TASK_TYPE_SYNONYMS
    key = cleaned.lower()

    if key in synonyms:
        return synonyms[key]

    # Substring check for compound terms
    for syn_key, target in synonyms.items():
        if len(syn_key) > 3 and syn_key in key:
            return target

    return cleaned.title()


def normalize_status(raw_status: str) -> str:
    """Normalizes task status (Completed, In Progress, Pending)."""
    cleaned = normalize_text_clean(raw_status)
    if not cleaned or cleaned.lower() in ['nan', 'none', 'null', '']:
        return "In Progress"

    key = cleaned.lower()
    if any(k in key for k in ['done', 'complete', 'completed', 'finish', 'resolved', 'closed', 'passed']):
        return "Completed"
    if any(k in key for k in ['progress', 'wip', 'ongoing', 'working', 'in-progress', 'in progress', 'active']):
        return "In Progress"
    if any(k in key for k in ['pending', 'hold', 'blocked', 'waiting', 'open', 'backlog', 'todo', 'to do']):
        return "Pending"

    return cleaned.title()


def parse_numeric_hours(val: Any) -> Optional[float]:
    """Safely converts string / time representation to float hours."""
    if val is None or pd.isna(val):
        return None
    if isinstance(val, (int, float)):
        return float(val)

    s = str(val).strip()
    if not s or s.lower() in ['nan', 'none', 'null', '-', '']:
        return None

    # Handle HH:MM time format
    time_match = re.match(r'^(\d+):(\d{1,2})$', s)
    if time_match:
        hrs = float(time_match.group(1))
        mins = float(time_match.group(2))
        return round(hrs + (mins / 60.0), 2)

    # Extract first numeric float
    num_match = re.search(r'[-+]?\d*\.?\d+', s)
    if num_match:
        try:
            return float(num_match.group(0))
        except ValueError:
            return None
    return None


def run_normalization_pipeline(
    df: pd.DataFrame,
    manager_overrides: Optional[Dict[str, Dict[str, str]]] = None,
    custom_synonyms: Optional[Dict[str, str]] = None,
    enable_auto_clustering: bool = True
) -> Tuple[pd.DataFrame, List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Executes full normalization pipeline:
    1. Employee names -> Clean Title Case + override mapping
    2. Entity (Service / Project / Client) -> Smart acronym/Title case + auto-clustering
    3. Task Types -> Synonyms table + auto-clustering
    4. Statuses -> Standard 3-state mapping
    5. Hours -> Float conversion
    6. Dates -> Flexible parsing & multi-cadence weekly bucketing
    7. Flagged Rows -> Preserves and flags rows with missing critical data
    """
    normalized_df = df.copy()
    overrides = manager_overrides or {}
    synonyms = {**DEFAULT_TASK_TYPE_SYNONYMS, **(custom_synonyms or {})}

    raw_transformations: Dict[str, Dict[Tuple[str, str], int]] = {
        "Employee": {},
        "Service": {},
        "Task Type": {},
        "Status": {}
    }

    # Pre-compute fuzzy clusters across entities and task types if enabled
    entity_clusters = {}
    task_type_clusters = {}
    if enable_auto_clustering:
        raw_entities = [str(x) for x in normalized_df["Service"].dropna() if str(x).strip()]
        entity_clusters = cluster_similar_terms(raw_entities, similarity_threshold=0.88)

        raw_tts = [str(x) for x in normalized_df["Task Type"].dropna() if str(x).strip()]
        task_type_clusters = cluster_similar_terms(raw_tts, similarity_threshold=0.86)

    # 1. Normalize Employee
    emp_overrides = overrides.get("Employee", {})
    norm_employees = []
    for raw in normalized_df["Employee"]:
        raw_str = "" if pd.isna(raw) else str(raw).strip()
        if raw_str in emp_overrides:
            norm = emp_overrides[raw_str]
        else:
            norm = normalize_employee_name(raw_str)
        norm_employees.append(norm)
        if raw_str != norm:
            pair = (raw_str, norm)
            raw_transformations["Employee"][pair] = raw_transformations["Employee"].get(pair, 0) + 1
    normalized_df["Employee"] = norm_employees

    # 2. Normalize Entity (Service / Client / Project)
    srv_overrides = overrides.get("Service", {})
    norm_services = []
    for raw in normalized_df["Service"]:
        raw_str = "" if pd.isna(raw) else str(raw).strip()
        if raw_str in srv_overrides:
            norm = srv_overrides[raw_str]
        else:
            # Check cluster representative first
            clustered = entity_clusters.get(raw_str, raw_str)
            norm = normalize_entity_name(clustered)
        norm_services.append(norm)
        if raw_str != norm:
            pair = (raw_str, norm)
            raw_transformations["Service"][pair] = raw_transformations["Service"].get(pair, 0) + 1
    normalized_df["Service"] = norm_services

    # 3. Normalize Task Type
    tt_overrides = overrides.get("Task Type", {})
    norm_types = []
    for raw in normalized_df["Task Type"]:
        raw_str = "" if pd.isna(raw) else str(raw).strip()
        if raw_str in tt_overrides:
            norm = tt_overrides[raw_str]
        else:
            clustered = task_type_clusters.get(raw_str, raw_str)
            norm = normalize_task_type(clustered, synonym_table=synonyms)
        norm_types.append(norm)
        if raw_str != norm:
            pair = (raw_str, norm)
            raw_transformations["Task Type"][pair] = raw_transformations["Task Type"].get(pair, 0) + 1
    normalized_df["Task Type"] = norm_types

    # 4. Normalize Status
    st_overrides = overrides.get("Status", {})
    norm_statuses = []
    for raw in normalized_df["Status"]:
        raw_str = "" if pd.isna(raw) else str(raw).strip()
        if raw_str in st_overrides:
            norm = st_overrides[raw_str]
        else:
            norm = normalize_status(raw_str)
        norm_statuses.append(norm)
        if raw_str != norm:
            pair = (raw_str, norm)
            raw_transformations["Status"][pair] = raw_transformations["Status"].get(pair, 0) + 1
    normalized_df["Status"] = norm_statuses

    # 5. Clean & Parse Hours
    normalized_df["Expected Hours"] = [parse_numeric_hours(v) for v in normalized_df["Expected Hours"]]
    normalized_df["Actual Hours"] = [parse_numeric_hours(v) for v in normalized_df["Actual Hours"]]

    # 6. Parse Dates & Dynamic Multi-Cadence Weekly Grouping
    parsed_dates = pd.to_datetime(normalized_df["Date"], errors='coerce', dayfirst=True)
    normalized_df["_Parsed_Date"] = parsed_dates

    # Check date span to determine best weekly/cadence labels
    valid_dates = parsed_dates.dropna()
    is_single_month = True
    if not valid_dates.empty:
        month_set = set(valid_dates.dt.to_period('M'))
        is_single_month = (len(month_set) <= 1)

    def compute_cadence_label(dt):
        if pd.isna(dt):
            return "Unspecified Period"
        day = dt.day
        month_abbr = dt.strftime('%b')
        if is_single_month:
            if 1 <= day <= 7:
                return f"Week 1 (1–7 {month_abbr})"
            elif 8 <= day <= 14:
                return f"Week 2 (8–14 {month_abbr})"
            elif 15 <= day <= 21:
                return f"Week 3 (15–21 {month_abbr})"
            elif 22 <= day <= 28:
                return f"Week 4 (22–28 {month_abbr})"
            else:
                return f"Week 5 (29–31 {month_abbr})"
        else:
            # Multi-month: use ISO calendar week format
            iso_year, iso_week, _ = dt.isocalendar()
            week_start = dt - pd.Timedelta(days=dt.weekday())
            week_end = week_start + pd.Timedelta(days=6)
            return f"W{iso_week} ({week_start.strftime('%d %b')}–{week_end.strftime('%d %b')})"

    normalized_df["Week"] = normalized_df["_Parsed_Date"].apply(compute_cadence_label)

    # 7. Flagged Rows Inspector
    flagged_rows = []
    for idx, row in normalized_df.iterrows():
        missing_reasons = []
        if row["Expected Hours"] is None:
            missing_reasons.append("Missing Expected Hours")
        if row["Actual Hours"] is None:
            missing_reasons.append("Missing Actual Hours")
        if pd.isna(row["_Parsed_Date"]):
            missing_reasons.append("Invalid or Missing Date")

        if missing_reasons:
            flagged_rows.append({
                "row_index": int(idx) + 1,
                "date": str(row.get("Date", "")),
                "employee": str(row.get("Employee", "")),
                "service": str(row.get("Service", "")),
                "task": str(row.get("Task", "")),
                "reasons": missing_reasons
            })

    # Build Normalization Audit Log
    normalization_log = []
    for field_name, pair_counts in raw_transformations.items():
        for (raw_v, norm_v), count in pair_counts.items():
            normalization_log.append({
                "field_name": field_name,
                "raw_value": raw_v if raw_v != "" else "[Empty/Null]",
                "normalized_value": norm_v,
                "row_count_affected": count
            })

    normalization_log.sort(key=lambda x: (x["field_name"], -x["row_count_affected"]))
    return normalized_df, normalization_log, flagged_rows


def normalize_employee_name(name: Any) -> str:
    """Convenience helper to normalize a single employee name."""
    clean = normalize_text_clean(name)
    if not clean:
        return "Unknown"
    # Title-case each word preserving initials
    words = clean.split()
    return " ".join([w.capitalize() if not w.isupper() else w for w in words])


def normalize_service_name(service: Any) -> str:
    """Convenience helper to normalize a single entity/service name."""
    clean = normalize_text_clean(service)
    if not clean:
        return "General"
    low = clean.lower()
    for acr_raw, acr_norm in COMMON_ACRONYM_MAP.items():
        if acr_raw in low:
            return acr_norm
    return clean.title()


def normalize_work_type(task_type: Any) -> str:
    """Convenience helper to normalize a work type against synonyms."""
    clean = normalize_text_clean(task_type)
    if not clean:
        return "Other"
    return DEFAULT_TASK_TYPE_SYNONYMS.get(clean.lower(), clean.title())

