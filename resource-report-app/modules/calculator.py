"""
calculator.py
Dynamic aggregation engine for any team domain.
- Computes hours, variances, share of effort, and utilization rates.
- Supports customizable primary entity labels (Project, Client, Department, Service, Account).
- Dynamically derives active work types from the ingested data rather than hardcoding them.
- Supports cross-tabulations and multi-cadence period pivots.
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional
import pandas as pd
import numpy as np


def calculate_aggregates(
    df: pd.DataFrame,
    nominal_capacity_per_employee: Optional[float] = None,
    entity_label: str = "Service"
) -> Dict[str, Any]:
    """
    Computes all aggregates and breakdowns from the normalized DataFrame.
    
    entity_label: The display name for the grouping entity (e.g. 'Project', 'Client', 'Service', 'Department').
    """
    calc_df = df.copy()
    calc_df["Expected_Calc"] = calc_df["Expected Hours"].fillna(0.0).astype(float)
    calc_df["Actual_Calc"] = calc_df["Actual Hours"].fillna(0.0).astype(float)

    total_tasks = int(len(calc_df))
    total_expected = round(float(calc_df["Expected_Calc"].sum()), 2)
    total_actual = round(float(calc_df["Actual_Calc"].sum()), 2)
    total_variance = round(total_actual - total_expected, 2)
    overall_utilization = round((total_actual / total_expected * 100), 1) if total_expected > 0 else 0.0

    # Determine reporting period string
    date_series = pd.to_datetime(calc_df["_Parsed_Date"], errors='coerce').dropna()
    if not date_series.empty:
        period_start = date_series.min().strftime('%d-%b-%Y')
        period_end = date_series.max().strftime('%d-%b-%Y')
        period_label = f"{period_start} to {period_end}"
        month_label = date_series.min().strftime('%B %Y')
    else:
        period_label = "Current Period"
        month_label = "Current Month"

    # 1. Work Type Aggregations (Dynamic)
    wt_group = calc_df.groupby("Task Type", observed=False).agg(
        tasks=("Task", "size"),
        expected_hrs=("Expected_Calc", "sum"),
        actual_hrs=("Actual_Calc", "sum")
    ).reset_index()

    wt_summary = []
    for _, row in wt_group.iterrows():
        exp = round(float(row["expected_hrs"]), 2)
        act = round(float(row["actual_hrs"]), 2)
        var = round(act - exp, 2)
        share = round((act / total_actual * 100), 2) if total_actual > 0 else 0.0
        wt_summary.append({
            "work_type": str(row["Task Type"]),
            "tasks": int(row["tasks"]),
            "expected_hrs": exp,
            "actual_hrs": act,
            "share_pct": share,
            "variance": var
        })
    wt_summary.sort(key=lambda x: x["actual_hrs"], reverse=True)

    # Dynamic active task types from data
    active_task_types = [w["work_type"] for w in wt_summary]

    # 2. Resource-wise (Employee) Aggregations
    emp_group = calc_df.groupby("Employee", observed=False).agg(
        tasks=("Task", "size"),
        expected_hrs=("Expected_Calc", "sum"),
        actual_hrs=("Actual_Calc", "sum")
    ).reset_index()

    emp_status_df = calc_df.groupby(["Employee", "Status"], observed=False).size().unstack(fill_value=0)

    emp_summary = []
    for _, row in emp_group.iterrows():
        emp_name = str(row["Employee"])
        exp = round(float(row["expected_hrs"]), 2)
        act = round(float(row["actual_hrs"]), 2)
        var = round(act - exp, 2)
        
        baseline = nominal_capacity_per_employee if (nominal_capacity_per_employee and nominal_capacity_per_employee > 0) else exp
        util_pct = round((act / baseline * 100), 1) if baseline > 0 else (100.0 if act > 0 else 0.0)
        
        statuses = {}
        if emp_name in emp_status_df.index:
            for col in emp_status_df.columns:
                statuses[str(col)] = int(emp_status_df.loc[emp_name, col])

        share = round((act / total_actual * 100), 2) if total_actual > 0 else 0.0
        services_handled = int(calc_df[calc_df["Employee"] == emp_name]["Service"].nunique())

        emp_summary.append({
            "employee": emp_name,
            "tasks": int(row["tasks"]),
            "expected_hrs": exp,
            "actual_hrs": act,
            "variance": var,
            "utilization_pct": util_pct,
            "share_pct": share,
            "services_handled": services_handled,
            "status_counts": statuses
        })
    emp_summary.sort(key=lambda x: x["actual_hrs"], reverse=True)

    # 3. Entity (Service / Project / Client / Department) Aggregations
    srv_group = calc_df.groupby("Service", observed=False).agg(
        tasks=("Task", "size"),
        expected_hrs=("Expected_Calc", "sum"),
        actual_hrs=("Actual_Calc", "sum")
    ).reset_index()

    srv_summary = []
    for _, row in srv_group.iterrows():
        srv_name = str(row["Service"])
        exp = round(float(row["expected_hrs"]), 2)
        act = round(float(row["actual_hrs"]), 2)
        var = round(act - exp, 2)
        share = round((act / total_actual * 100), 2) if total_actual > 0 else 0.0
        
        level = "Very High" if share >= 18.0 else ("High" if share >= 10.0 else ("Medium" if share >= 5.0 else "Low"))

        srv_summary.append({
            "service": srv_name,
            "tasks": int(row["tasks"]),
            "expected_hrs": exp,
            "actual_hrs": act,
            "variance": var,
            "share_pct": share,
            "attention_level": level
        })
    srv_summary.sort(key=lambda x: x["actual_hrs"], reverse=True)

    # 4. Weekly / Cadence Utilization Breakdown
    # Preserve order of appearance of weeks
    ordered_weeks = []
    for w in calc_df["Week"].dropna():
        if w not in ordered_weeks:
            ordered_weeks.append(w)

    week_summary = []
    for w in ordered_weeks:
        w_slice = calc_df[calc_df["Week"] == w]
        w_exp = round(float(w_slice["Expected_Calc"].sum()), 2)
        w_act = round(float(w_slice["Actual_Calc"].sum()), 2)
        active_res = int(w_slice["Employee"].nunique())
        week_summary.append({
            "week": w,
            "tasks": int(len(w_slice)),
            "active_resources": active_res,
            "expected_hrs": w_exp,
            "actual_hrs": w_act,
            "variance": round(w_act - w_exp, 2)
        })

    # Entity-wise weekly pivot: [Entity, Week, Task Type] -> Actual hours
    service_week_pivot = {}
    distinct_entities = [s["service"] for s in srv_summary]
    top_task_types = active_task_types[:5] if active_task_types else ["Support", "New Development", "Other"]

    for srv in distinct_entities:
        service_week_pivot[srv] = {"weeks": {}, "total_actual": 0.0}
        srv_slice = calc_df[calc_df["Service"] == srv]
        service_week_pivot[srv]["total_actual"] = round(float(srv_slice["Actual_Calc"].sum()), 2)
        
        for w in ordered_weeks:
            w_srv_slice = srv_slice[srv_slice["Week"] == w]
            by_type = {}
            for tt in top_task_types:
                val = round(float(w_srv_slice[w_srv_slice["Task Type"] == tt]["Actual_Calc"].sum()), 2)
                by_type[tt] = val
            by_type["Total"] = round(float(w_srv_slice["Actual_Calc"].sum()), 2)
            service_week_pivot[srv]["weeks"][w] = by_type

    # 7. Week-by-week aggregated slices for dynamic time-slicing
    by_week_breakdown = {}
    for w in ordered_weeks:
        w_df = calc_df[calc_df["Week"] == w]
        w_tot_tasks = int(len(w_df))
        w_tot_exp = round(float(w_df["Expected_Calc"].sum()), 2)
        w_tot_act = round(float(w_df["Actual_Calc"].sum()), 2)
        w_tot_var = round(w_tot_act - w_tot_exp, 2)
        w_tot_util = round((w_tot_act / w_tot_exp * 100), 1) if w_tot_exp > 0 else 0.0

        w_wt = []
        for tt, grp in w_df.groupby("Task Type", observed=False):
            exp_ = round(float(grp["Expected_Calc"].sum()), 2)
            act_ = round(float(grp["Actual_Calc"].sum()), 2)
            share_ = round((act_ / w_tot_act * 100), 2) if w_tot_act > 0 else 0.0
            w_wt.append({
                "work_type": str(tt),
                "tasks": int(len(grp)),
                "expected_hrs": exp_,
                "actual_hrs": act_,
                "variance": round(act_ - exp_, 2),
                "share_pct": share_
            })
        w_wt.sort(key=lambda x: x["actual_hrs"], reverse=True)

        w_emp = []
        for emp, grp in w_df.groupby("Employee", observed=False):
            exp_ = round(float(grp["Expected_Calc"].sum()), 2)
            act_ = round(float(grp["Actual_Calc"].sum()), 2)
            share_ = round((act_ / w_tot_act * 100), 2) if w_tot_act > 0 else 0.0
            util_ = round((act_ / exp_ * 100), 1) if exp_ > 0 else (100.0 if act_ > 0 else 0.0)
            w_emp.append({
                "employee": str(emp),
                "tasks": int(len(grp)),
                "expected_hrs": exp_,
                "actual_hrs": act_,
                "variance": round(act_ - exp_, 2),
                "utilization_pct": util_,
                "share_pct": share_
            })
        w_emp.sort(key=lambda x: x["actual_hrs"], reverse=True)

        w_srv = []
        for srv, grp in w_df.groupby("Service", observed=False):
            exp_ = round(float(grp["Expected_Calc"].sum()), 2)
            act_ = round(float(grp["Actual_Calc"].sum()), 2)
            share_ = round((act_ / w_tot_act * 100), 2) if w_tot_act > 0 else 0.0
            w_srv.append({
                "service": str(srv),
                "tasks": int(len(grp)),
                "expected_hrs": exp_,
                "actual_hrs": act_,
                "variance": round(act_ - exp_, 2),
                "share_pct": share_
            })
        w_srv.sort(key=lambda x: x["actual_hrs"], reverse=True)

        by_week_breakdown[w] = {
            "totals": {
                "tasks": w_tot_tasks,
                "expected_hrs": w_tot_exp,
                "actual_hrs": w_tot_act,
                "variance": w_tot_var,
                "utilization_pct": w_tot_util,
                "active_resources": int(w_df["Employee"].nunique()),
                "active_services": int(w_df["Service"].nunique())
            },
            "by_work_type": w_wt,
            "by_employee": w_emp,
            "by_service": w_srv
        }

    # 8. Data Anomaly & Audit Radar Detection
    # Unbudgeted / Scope Creep (Expected == 0 or severe ratio overrun >= 150%)
    unbudgeted_df = calc_df[(calc_df["Expected_Calc"] == 0) & (calc_df["Actual_Calc"] > 0)]
    if unbudgeted_df.empty:
        unbudgeted_df = calc_df[(calc_df["Actual_Calc"] >= 1.5 * calc_df["Expected_Calc"]) & (calc_df["Actual_Calc"] - calc_df["Expected_Calc"] >= 1.5)]

    unbudgeted_tasks = []
    for _, r in unbudgeted_df.iterrows():
        unbudgeted_tasks.append({
            "task": str(r.get("Task", "Unnamed Deliverable")),
            "employee": str(r.get("Employee", "Unknown")),
            "service": str(r.get("Service", "General")),
            "actual_hrs": round(float(r["Actual_Calc"]), 2),
            "expected_hrs": round(float(r["Expected_Calc"]), 2),
            "week": str(r.get("Week", "N/A"))
        })
    unbudgeted_tasks.sort(key=lambda x: x["actual_hrs"], reverse=True)

    # High Duration Single Tasks (Actual >= 7 hrs)
    marathon_df = calc_df[calc_df["Actual_Calc"] >= 7.0]
    marathon_tasks = []
    for _, r in marathon_df.iterrows():
        marathon_tasks.append({
            "task": str(r.get("Task", "Unnamed Task")),
            "employee": str(r.get("Employee", "Unknown")),
            "service": str(r.get("Service", "General")),
            "expected_hrs": round(float(r["Expected_Calc"]), 2),
            "actual_hrs": round(float(r["Actual_Calc"]), 2),
            "variance": round(float(r["Actual_Calc"]) - float(r["Expected_Calc"]), 2)
        })
    marathon_tasks.sort(key=lambda x: x["actual_hrs"], reverse=True)

    # University / Service SLA Delivery Efficiency Index
    service_efficiency = []
    for s in srv_summary:
        exp = s["expected_hrs"]
        act = s["actual_hrs"]
        ratio = round((act / exp * 100), 1) if exp > 0 else (100.0 if act > 0 else 0.0)
        health = "On Track" if ratio <= 105.0 else ("Moderate Overrun" if ratio <= 120.0 else "Critical Overrun")
        service_efficiency.append({
            "service": s["service"],
            "expected_hrs": exp,
            "actual_hrs": act,
            "variance": s["variance"],
            "ratio_pct": ratio,
            "health": health
        })
    service_efficiency.sort(key=lambda x: x["ratio_pct"], reverse=True)

    # 9. Status Summary Overall & Cross Tab
    status_counts_overall = calc_df["Status"].value_counts().to_dict()

    cross_group = calc_df.groupby(["Employee", "Service", "Task Type"], observed=False).agg(
        tasks=("Task", "size"),
        actual_hrs=("Actual_Calc", "sum")
    ).reset_index()
    cross_list = []
    for _, r in cross_group.iterrows():
        cross_list.append({
            "employee": str(r["Employee"]),
            "service": str(r["Service"]),
            "task_type": str(r["Task Type"]),
            "tasks": int(r["tasks"]),
            "actual_hrs": round(float(r["actual_hrs"]), 2)
        })
    cross_list.sort(key=lambda x: x["actual_hrs"], reverse=True)

    anomaly_radar = {
        "unbudgeted_count": len(unbudgeted_tasks),
        "unbudgeted_hours": round(sum(t["actual_hrs"] for t in unbudgeted_tasks), 2),
        "unbudgeted_tasks": unbudgeted_tasks[:10],
        "marathon_count": len(marathon_tasks),
        "marathon_tasks": marathon_tasks[:10],
        "service_efficiency": service_efficiency
    }

    return {
        "period_label": period_label,
        "month_label": month_label,
        "entity_label": entity_label,
        "totals": {
            "tasks": total_tasks,
            "expected_hrs": total_expected,
            "actual_hrs": total_actual,
            "variance": total_variance,
            "utilization_pct": overall_utilization
        },
        "by_work_type": wt_summary,
        "active_task_types": active_task_types,
        "by_employee": emp_summary,
        "by_service": srv_summary,
        "by_week": week_summary,
        "ordered_weeks": ordered_weeks,
        "by_week_breakdown": by_week_breakdown,
        "anomaly_radar": anomaly_radar,
        "service_week_pivot": service_week_pivot,
        "status_counts": status_counts_overall,
        "cross_tab": cross_list[:50]
    }

