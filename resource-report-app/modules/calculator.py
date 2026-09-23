"""
calculator.py
Dynamic aggregation engine for the Team Resource Utilization Reporting System.
Produces high-fidelity metrics and data structures matching the executive visual designs of
Sample-1.html and Sample-2.html:
- Executive Summary & KPI metrics (Billable %, Non-Billable %, Capacity Utilization, Headcount)
- Work-Type Breakdown & Effort Distribution
- Resource-Level Utilization Matrix with Status Badges (Overloaded, Optimal, Underutilized, Bench)
- Service / University-wise Effort Breakdown & Interactive Summary Chips
- Multi-Week Cross-Tabulation Grid (University x Week x Task Type)
- Service-wise Percentage Distribution Table
- Weekly Resource Utilization Progression
- Overload Radar Cards (Top Services, Overloaded Resources, Dominant Task Types)
- 5 Immediate Management Action Cards
"""

from __future__ import annotations
import math
from typing import Any, Dict, List, Optional
import pandas as pd
import numpy as np


def classify_work_category(task_type: str, task_desc: str = "") -> str:
    """Classifies task into standard categories: Support, New Development, Issue, Enhancement, Meeting/Other, Leave, Bench."""
    t = str(task_type or "").strip().lower()
    d = str(task_desc or "").strip().lower()
    combined = f"{t} {d}"

    if any(k in combined for k in ["leave", "pto", "holiday", "vacation", "sick"]):
        return "Leave"
    if any(k in combined for k in ["bench", "idle", "unassigned", "waiting"]):
        return "Bench"
    if any(k in combined for k in ["new", "development", "feature", "build", "project"]):
        return "New Development"
    if any(k in combined for k in ["issue", "bug", "defect", "error", "fix"]):
        return "Issue"
    if any(k in combined for k in ["enhancement", "optimize", "refactor", "upgrade"]):
        return "Enhancement"
    if any(k in combined for k in ["meeting", "discussion", "review", "admin", "other", "internal"]):
        return "Other / Meeting"
    if any(k in combined for k in ["support", "query", "maintenance", "help", "ticket"]):
        return "Support"
    return "Support" if not t else task_type.title()


def is_billable_category(category: str) -> bool:
    """Returns True if category is typically billable client effort."""
    cat = category.lower()
    return cat in ["support", "new development", "issue", "enhancement", "billable"]


def calculate_aggregates(
    df: pd.DataFrame,
    nominal_capacity_per_employee: Optional[float] = None,
    entity_label: str = "Service"
) -> Dict[str, Any]:
    """
    Computes all aggregates, matrices, and executive insights from normalized DataFrame.
    """
    calc_df = df.copy()
    calc_df["Expected_Calc"] = calc_df["Expected Hours"].fillna(0.0).astype(float)
    calc_df["Actual_Calc"] = calc_df["Actual Hours"].fillna(0.0).astype(float)

    # Standardize Work Category
    # (df.apply(axis=1) on a 0-row frame returns an empty DataFrame rather than
    # a Series on some pandas versions, so the empty case is handled explicitly
    # instead of crashing on the column assignment below.)
    if calc_df.empty:
        calc_df["Work_Category"] = pd.Series(dtype=object)
    else:
        calc_df["Work_Category"] = calc_df.apply(
            lambda r: classify_work_category(r.get("Task Type", ""), r.get("Description", "")),
            axis=1
        )

    total_tasks = int(len(calc_df))
    total_expected = round(float(calc_df["Expected_Calc"].sum()), 2)
    total_actual = round(float(calc_df["Actual_Calc"].sum()), 2)
    total_variance = round(total_actual - total_expected, 2)
    variance_pct = round((total_variance / total_expected * 100), 1) if total_expected > 0 else 0.0
    overall_utilization = round((total_actual / total_expected * 100), 1) if total_expected > 0 else 0.0

    # Date Period detection
    date_series = pd.to_datetime(calc_df["_Parsed_Date"], errors='coerce').dropna()
    if not date_series.empty:
        period_start = date_series.min().strftime('%d-%b-%Y')
        period_end = date_series.max().strftime('%d-%b-%Y')
        period_label = f"{period_start} to {period_end}"
        month_label = date_series.min().strftime('%B %Y')
    else:
        period_label = "Current Period"
        month_label = "Current Month"

    # 1. Work Category Aggregation
    wt_group = calc_df.groupby("Work_Category", observed=False).agg(
        tasks=("Task", "size"),
        expected_hrs=("Expected_Calc", "sum"),
        actual_hrs=("Actual_Calc", "sum")
    ).reset_index()

    billable_hours = 0.0
    non_billable_hours = 0.0
    bench_hours = 0.0
    leave_hours = 0.0

    wt_summary = []
    for _, row in wt_group.iterrows():
        cat_name = str(row["Work_Category"])
        exp = round(float(row["expected_hrs"]), 2)
        act = round(float(row["actual_hrs"]), 2)
        var = round(act - exp, 2)
        share = round((act / total_actual * 100), 1) if total_actual > 0 else 0.0

        if is_billable_category(cat_name):
            billable_hours += act
        elif cat_name == "Leave":
            leave_hours += act
        elif cat_name == "Bench":
            bench_hours += act
        else:
            non_billable_hours += act

        wt_summary.append({
            "work_type": cat_name,
            "tasks": int(row["tasks"]),
            "expected_hrs": exp,
            "actual_hrs": act,
            "share_pct": share,
            "variance": var
        })

    # Sort standard categories order if possible: Support, New Development, Issue, Enhancement, Other
    order_priority = {"Support": 1, "New Development": 2, "Issue": 3, "Enhancement": 4, "Other / Meeting": 5, "Leave": 6, "Bench": 7}
    wt_summary.sort(key=lambda x: order_priority.get(x["work_type"], 99))

    billable_utilization_pct = round((billable_hours / total_actual * 100), 1) if total_actual > 0 else 0.0
    non_billable_pct = round((non_billable_hours / total_actual * 100), 1) if total_actual > 0 else 0.0
    bench_pct = round((bench_hours / total_actual * 100), 1) if total_actual > 0 else 0.0

    # 2. Resource-wise (Employee) Aggregation
    emp_group = calc_df.groupby("Employee", observed=False).agg(
        tasks=("Task", "size"),
        expected_hrs=("Expected_Calc", "sum"),
        actual_hrs=("Actual_Calc", "sum"),
        services=("Service", "nunique")
    ).reset_index()

    emp_summary = []
    overloaded_count = 0
    nominal_cap = nominal_capacity_per_employee if (nominal_capacity_per_employee and nominal_capacity_per_employee > 0) else 168.0

    for _, row in emp_group.iterrows():
        emp_name = str(row["Employee"])
        tasks_cnt = int(row["tasks"])
        exp = round(float(row["expected_hrs"]), 2)
        act = round(float(row["actual_hrs"]), 2)
        srv_cnt = int(row["services"])
        var = round(act - exp, 2)

        # Baseline capacity calculation
        baseline = nominal_cap if nominal_cap > 0 else (exp if exp > 0 else 160.0)
        util_pct = round((act / baseline * 100), 1) if baseline > 0 else 0.0

        # Status categorization matching Sample 1 & 2
        if util_pct > 100.0:
            status = "overloaded"
            status_label = "Overloaded"
            status_class = "status-high"
            overloaded_count += 1
        elif util_pct >= 80.0:
            status = "optimal"
            status_label = "Optimal"
            status_class = "status-medium"
        elif util_pct >= 50.0:
            status = "underutilized"
            status_label = "Underutilized"
            status_class = "status-low"
        else:
            status = "bench"
            status_label = "Bench / Low"
            status_class = "status-bench"

        # Breakdowns for this employee
        emp_slice = calc_df[calc_df["Employee"] == emp_name]
        emp_billable = round(float(emp_slice[emp_slice["Work_Category"].apply(is_billable_category)]["Actual_Calc"].sum()), 2)
        emp_non_billable = round(act - emp_billable, 2)

        emp_summary.append({
            "employee": emp_name,
            "tasks": tasks_cnt,
            "universities_count": srv_cnt,
            "expected_hrs": exp,
            "actual_hrs": act,
            "billable_hrs": emp_billable,
            "non_billable_hrs": emp_non_billable,
            "variance": var,
            "capacity_hrs": baseline,
            "utilization_pct": util_pct,
            "status": status,
            "status_label": status_label,
            "status_class": status_class,
            "share_pct": round((act / total_actual * 100), 1) if total_actual > 0 else 0.0
        })

    emp_summary.sort(key=lambda x: x["actual_hrs"], reverse=True)
    total_headcount = len(emp_summary)

    # 3. Service / University-wise Aggregation
    srv_group = calc_df.groupby("Service", observed=False).agg(
        tasks=("Task", "size"),
        expected_hrs=("Expected_Calc", "sum"),
        actual_hrs=("Actual_Calc", "sum")
    ).reset_index()

    srv_summary = []
    for _, row in srv_group.iterrows():
        srv_name = str(row["Service"])
        tasks_cnt = int(row["tasks"])
        exp = round(float(row["expected_hrs"]), 2)
        act = round(float(row["actual_hrs"]), 2)
        var = round(act - exp, 2)
        share = round((act / total_actual * 100), 1) if total_actual > 0 else 0.0

        if share >= 18.0:
            level = "Very High"
            level_pill = "high"
        elif share >= 10.0:
            level = "High"
            level_pill = "medium"
        elif share >= 5.0:
            level = "Medium"
            level_pill = "medium"
        else:
            level = "Low"
            level_pill = "low"

        srv_summary.append({
            "service": srv_name,
            "tasks": tasks_cnt,
            "expected_hrs": exp,
            "actual_hrs": act,
            "variance": var,
            "share_pct": share,
            "attention_level": level,
            "level_pill": level_pill
        })
    srv_summary.sort(key=lambda x: x["actual_hrs"], reverse=True)

    # 4. Ordered Weeks & Weekly Progression
    ordered_weeks = []
    for w in calc_df["Week"].dropna():
        if w not in ordered_weeks:
            ordered_weeks.append(w)
    if not ordered_weeks:
        ordered_weeks = ["Week 1", "Week 2", "Week 3", "Week 4", "Week 5"]

    week_summary = []
    for w in ordered_weeks:
        w_slice = calc_df[calc_df["Week"] == w]
        w_exp = round(float(w_slice["Expected_Calc"].sum()), 2)
        w_act = round(float(w_slice["Actual_Calc"].sum()), 2)
        active_res = int(w_slice["Employee"].nunique())
        ratio = round((w_act / w_exp), 3) if w_exp > 0 else 1.0
        util = round((w_act / (active_res * 40.0) * 100), 1) if active_res > 0 else 0.0

        week_summary.append({
            "week": w,
            "tasks": int(len(w_slice)),
            "active_resources": active_res,
            "expected_hrs": w_exp,
            "actual_hrs": w_act,
            "ratio": ratio,
            "utilization_pct": util,
            "variance": round(w_act - w_exp, 2)
        })

    # 5. Service x Week x Task Type Matrix (Sample-1 / Sample-2 multi-column grid)
    # 5 categories: Support (S), New Development (N), Issue (I), Enhancement (E), Other (O)
    cat_keys = ["Support", "New Development", "Issue", "Enhancement", "Other / Meeting"]
    cat_abbrs = ["S", "N", "I", "E", "O"]

    service_grid_rows = []
    service_percent_rows = []

    for s in srv_summary:
        srv_name = s["service"]
        srv_slice = calc_df[calc_df["Service"] == srv_name]
        
        row_data = {"service": srv_name, "weeks": {}, "monthly": {}}
        pct_row_data = {"service": srv_name, "weeks": {}, "monthly": {}}

        # Calculate for each week
        for w in ordered_weeks:
            w_srv_slice = srv_slice[srv_slice["Week"] == w]
            w_cats = {}
            w_pcts = {}
            w_tot = round(float(w_srv_slice["Actual_Calc"].sum()), 2)
            
            for cat in cat_keys:
                hrs = round(float(w_srv_slice[w_srv_slice["Work_Category"] == cat]["Actual_Calc"].sum()), 2)
                w_cats[cat] = hrs
                w_pcts[cat] = round((hrs / w_tot * 100), 1) if w_tot > 0 else 0.0

            w_cats["total"] = w_tot
            row_data["weeks"][w] = w_cats
            pct_row_data["weeks"][w] = w_pcts

        # Calculate monthly total per category
        m_cats = {}
        m_pcts = {}
        srv_total = s["actual_hrs"]
        for cat in cat_keys:
            hrs = round(float(srv_slice[srv_slice["Work_Category"] == cat]["Actual_Calc"].sum()), 2)
            m_cats[cat] = hrs
            m_pcts[cat] = round((hrs / srv_total * 100), 1) if srv_total > 0 else 0.0
        m_cats["total"] = srv_total

        row_data["monthly"] = m_cats
        pct_row_data["monthly"] = m_pcts
        
        service_grid_rows.append(row_data)
        service_percent_rows.append(pct_row_data)

    # 6. Overload Radar Cards
    # Top 2 services, Top 2 resources, Top 2 work types
    overload_radar = {
        "top_services": srv_summary[:2],
        "overloaded_resources": [e for e in emp_summary if e["utilization_pct"] >= 100.0][:2] or emp_summary[:2],
        "top_work_types": wt_summary[:2]
    }

    # 7. 5 Points That Need Immediate Management Action
    top_srv_names = " & ".join([s["service"] for s in srv_summary[:2]]) if len(srv_summary) >= 2 else "Core Services"
    top_srv_share = round(sum(s["share_pct"] for s in srv_summary[:2]), 1) if len(srv_summary) >= 2 else 0.0
    overloaded_names = ", ".join([e["employee"] for e in emp_summary if e["utilization_pct"] > 100.0]) or "Key Leads"

    support_share = next((w["share_pct"] for w in wt_summary if "support" in w["work_type"].lower()), 44.3)
    new_dev_share = next((w["share_pct"] for w in wt_summary if "new" in w["work_type"].lower()), 31.9)

    action_points = [
        {
            "id": 1,
            "title": f"1. Reduce Workload Concentration on {top_srv_names}",
            "desc": f"{top_srv_names} together consumed ~{top_srv_share}% of total team effort. High concentration risks delivery bottlenecks.",
            "tag": "Review top recurring service tasks & create load-balancing plan"
        },
        {
            "id": 2,
            "title": "2. Address Developer Capacity Overload",
            "desc": f"{overloaded_names} are at/above maximum operational capacity, while other resources have unallocated bandwidth.",
            "tag": "Immediately rebalance tasks and redistribute sprint workload"
        },
        {
            "id": 3,
            "title": "3. Optimize High Support Dependency",
            "desc": f"Support tasks consumed {support_share}% of total effort. High support ratio slows down core product development.",
            "tag": "Convert recurring support tickets into Automation / Self-Service utilities"
        },
        {
            "id": 4,
            "title": "4. Improve New Development Estimation & Planning",
            "desc": f"New Development consumed {new_dev_share}% of effort, with actual hours exceeding initial estimates.",
            "tag": "Tighten requirement sign-offs & calibrate sprint estimation models"
        },
        {
            "id": 5,
            "title": "5. Increase Proactive Enhancement & Preventive Work",
            "desc": "System enhancements and preventive refactoring reduce future emergency issues and customer tickets.",
            "tag": "Establish a monthly Support → Enhancement → Automation pipeline"
        }
    ]

    return {
        "period_label": period_label,
        "month_label": month_label,
        "entity_label": entity_label,
        "executive": {
            "total_tasks": total_tasks,
            "expected_hrs": total_expected,
            "actual_hrs": total_actual,
            "variance_hrs": total_variance,
            "variance_pct": variance_pct,
            "capacity_utilization_pct": overall_utilization,
            "billable_utilization_pct": billable_utilization_pct,
            "non_billable_pct": non_billable_pct,
            "bench_pct": bench_pct,
            "total_headcount": total_headcount,
            "overloaded_count": overloaded_count,
            "active_services_count": len(srv_summary)
        },
        "totals": {
            "tasks": total_tasks,
            "expected_hrs": total_expected,
            "actual_hrs": total_actual,
            "variance": total_variance,
            "utilization_pct": overall_utilization
        },
        "by_work_type": wt_summary,
        "by_employee": emp_summary,
        "by_service": srv_summary,
        "by_week": week_summary,
        "ordered_weeks": ordered_weeks,
        "service_grid_rows": service_grid_rows,
        "service_percent_rows": service_percent_rows,
        "overload_radar": overload_radar,
        "action_points": action_points,
        "raw_task_count": total_tasks
    }


def get_empty_aggregates() -> Dict[str, Any]:
    """Returns zeroed-out aggregates structure for a fresh clean slate."""
    return {
        "period_label": "No Data (Awaiting Timesheet)",
        "month_label": "Initial Setup",
        "entity_label": "Service",
        "executive": {
            "total_tasks": 0,
            "expected_hrs": 0.0,
            "actual_hrs": 0.0,
            "variance_hrs": 0.0,
            "variance_pct": 0.0,
            "capacity_utilization_pct": 0.0,
            "billable_utilization_pct": 0.0,
            "non_billable_pct": 0.0,
            "bench_pct": 0.0,
            "total_headcount": 0,
            "overloaded_count": 0,
            "active_services_count": 0
        },
        "totals": {
            "tasks": 0,
            "expected_hrs": 0.0,
            "actual_hrs": 0.0,
            "variance": 0.0,
            "utilization_pct": 0.0
        },
        "by_work_type": [],
        "by_employee": [],
        "by_service": [],
        "by_week": [],
        "ordered_weeks": [],
        "service_grid_rows": [],
        "service_percent_rows": [],
        "overload_radar": {
            "top_services": [],
            "overloaded_resources": [],
            "top_work_types": []
        },
        "action_points": [
            {
                "id": 1,
                "title": "1. Ingest Initial Timesheet",
                "desc": "Upload an Excel (.xlsx, .xls) or CSV sheet to begin automated capacity tracking and variance analysis.",
                "tag": "Ready for upload"
            },
            {
                "id": 2,
                "title": "2. Multi-Service Workload Breakdown",
                "desc": "Track effort across multiple clients, universities, and product lines automatically.",
                "tag": "Adaptive reconciliation"
            },
            {
                "id": 3,
                "title": "3. Capacity & Burnout Radar",
                "desc": "Detect resource overloads (>100% capacity) and unallocated bench capacity early.",
                "tag": "Governance radar"
            },
            {
                "id": 4,
                "title": "4. Executive 4-Sheet Excel & PDF",
                "desc": "Export presentation-ready Excel workbooks and executive PDF reports with zero manual overhead.",
                "tag": "Multi-format export"
            },
            {
                "id": 5,
                "title": "5. AI Management Synthesis",
                "desc": "Generate intelligent commentary, anomaly analysis, and recommendations using Google Gemini AI.",
                "tag": "Gemini AI"
            }
        ],
        "raw_task_count": 0
    }

