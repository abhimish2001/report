"""
variance_engine.py
Identifies overloaded resources, services, and work types against a configurable
threshold (default 110% of expected capacity/hours).
Surfaces top attention areas and generates governance highlights matching reference reports.
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional


def analyze_variances(
    aggregates: Dict[str, Any],
    overload_threshold_pct: float = 110.0,
    top_n: int = 5
) -> Dict[str, Any]:
    """
    Analyzes calculated aggregates to flag overruns and governance highlights.

    overload_threshold_pct: percentage threshold (e.g. 110.0%)
    top_n: number of top attention items to surface
    """
    by_emp = aggregates.get("by_employee", [])
    by_srv = aggregates.get("by_service", [])
    by_wt = aggregates.get("by_work_type", [])
    total_actual = aggregates.get("totals", {}).get("actual_hrs", 1.0) or 1.0

    overloaded_employees = []
    for emp in by_emp:
        util = emp.get("utilization_pct", 0.0)
        var = emp.get("variance", 0.0)
        exp = emp.get("expected_hrs", 0.0)
        act = emp.get("actual_hrs", 0.0)
        overrun_pct = round(((act - exp) / exp * 100), 1) if exp > 0 else (100.0 if act > 0 else 0.0)
        
        is_overloaded = (util >= overload_threshold_pct and var > 0)
        status = "Overloaded" if is_overloaded else ("At Capacity" if util >= 95.0 else "Within Baseline")

        record = {
            "name": emp["employee"],
            "tasks": emp["tasks"],
            "expected_hrs": exp,
            "actual_hrs": act,
            "variance": var,
            "utilization_pct": util,
            "overrun_pct": overrun_pct,
            "is_overloaded": is_overloaded,
            "status": status
        }
        if is_overloaded:
            overloaded_employees.append(record)

    overloaded_employees.sort(key=lambda x: x["variance"], reverse=True)

    overloaded_services = []
    for srv in by_srv:
        exp = srv.get("expected_hrs", 0.0)
        act = srv.get("actual_hrs", 0.0)
        var = srv.get("variance", 0.0)
        share = srv.get("share_pct", 0.0)
        ratio_pct = round((act / exp * 100), 1) if exp > 0 else 0.0
        
        is_overloaded = (ratio_pct >= overload_threshold_pct and var > 0) or share >= 20.0
        record = {
            "name": srv["service"],
            "tasks": srv["tasks"],
            "expected_hrs": exp,
            "actual_hrs": act,
            "variance": var,
            "share_pct": share,
            "ratio_pct": ratio_pct,
            "is_overloaded": is_overloaded
        }
        if is_overloaded:
            overloaded_services.append(record)

    overloaded_services.sort(key=lambda x: x["actual_hrs"], reverse=True)

    # Build "Most Overloaded Work" & Governance Highlight items
    # Modeled directly after Reference Report Summary sheet
    overloaded_work_table = []

    entity_label = aggregates.get("entity_label", "Service")

    # Top services by actual effort
    for srv in by_srv[:3]:
        act = srv["actual_hrs"]
        share = srv["share_pct"]
        name = srv["service"]
        
        if share >= 22.0:
            gov_note = f"Highest overall workload ({share}% of team effort); major demand footprint"
        elif share >= 15.0:
            gov_note = f"Substantial ongoing effort ({share}% share); major operational commitment"
        else:
            gov_note = f"Notable footprint ({act} hrs logged)"
            
        overloaded_work_table.append({
            "category": entity_label,
            "name": name,
            "actual_effort": f"{act} hrs",
            "utilization_share": f"{share}%",
            "governance_highlight": gov_note
        })

    # Top resources by variance and utilization
    for emp in by_emp:
        if emp["utilization_pct"] >= overload_threshold_pct or emp["variance"] > 20.0:
            act = emp["actual_hrs"]
            util = emp["utilization_pct"]
            var = emp["variance"]
            name = emp["employee"]
            overloaded_work_table.append({
                "category": "Resource",
                "name": name,
                "actual_effort": f"{act} hrs",
                "utilization_share": f"{util}%",
                "governance_highlight": f"Operating above nominal capacity (+{var} hrs variance); risk of burnout"
            })

    # Burnout Risk & Smart Workload Rebalancing Engine
    overloaded_for_burnout = []
    underutilized_for_burnout = []
    for emp in by_emp:
        act = emp.get("actual_hrs", 0.0)
        exp = emp.get("expected_hrs", 0.0)
        util = emp.get("utilization_pct", 0.0)
        var = emp.get("variance", 0.0)
        name = emp.get("employee", "")
        if util >= 115.0 or var >= 15.0:
            burnout_score = round(min(100.0, (util - 100.0) * 2.0 + (var * 1.5)), 1)
            overloaded_for_burnout.append({
                "name": name,
                "actual_hrs": act,
                "expected_hrs": exp,
                "utilization_pct": util,
                "variance": var,
                "burnout_score": burnout_score,
                "risk_level": "Critical" if burnout_score >= 65 else "High"
            })
        elif util <= 106.0:
            headroom = round(max(0.0, 140.0 - act), 1)
            underutilized_for_burnout.append({
                "name": name,
                "actual_hrs": act,
                "expected_hrs": exp,
                "utilization_pct": util,
                "variance": var,
                "headroom_hrs": headroom
            })

    overloaded_for_burnout.sort(key=lambda x: x["burnout_score"], reverse=True)
    underutilized_for_burnout.sort(key=lambda x: x["actual_hrs"])

    # Proactive Rebalancing recommendations
    rebalance_suggestions = []
    if overloaded_for_burnout and underutilized_for_burnout:
        for idx, over in enumerate(overloaded_for_burnout[:2]):
            target = underutilized_for_burnout[idx % len(underutilized_for_burnout)]
            rebalance_hrs = round(min(over["variance"], 15.0), 1)
            if rebalance_hrs > 0:
                rebalance_suggestions.append({
                    "from_resource": over["name"],
                    "to_resource": target["name"],
                    "hours_to_transfer": rebalance_hrs,
                    "from_current": over["actual_hrs"],
                    "from_after": round(over["actual_hrs"] - rebalance_hrs, 1),
                    "to_current": target["actual_hrs"],
                    "to_after": round(target["actual_hrs"] + rebalance_hrs, 1),
                    "impact": f"Transfer ~{rebalance_hrs}h from {over['name']} ({over['actual_hrs']}h, {over['utilization_pct']}%) to {target['name']} ({target['actual_hrs']}h, {target['utilization_pct']}%) to normalize loads."
                })

    burnout_analysis = {
        "overloaded_count": len(overloaded_for_burnout),
        "overloaded_resources": overloaded_for_burnout,
        "underutilized_resources": underutilized_for_burnout,
        "rebalance_suggestions": rebalance_suggestions
    }

    # Attention Points (List of actionable alerts)
    attention_points: List[Dict[str, str]] = []

    for emp in overloaded_employees[:3]:
        attention_points.append({
            "level": "warning" if emp["utilization_pct"] < 130 else "danger",
            "title": f"Resource Overload: {emp['name']}",
            "message": f"{emp['name']} recorded {emp['actual_hrs']} hrs vs {emp['expected_hrs']} planned ({emp['utilization_pct']}% utilization, +{emp['variance']} hrs variance)."
        })

    for srv in overloaded_services[:2]:
        attention_points.append({
            "level": "info",
            "title": f"High Effort {entity_label}: {srv['name']}",
            "message": f"{srv['name']} consumed {srv['actual_hrs']} hrs ({srv['share_pct']}% of entire team capacity)."
        })

    top_wt = by_wt[0] if by_wt else None
    if top_wt:
        attention_points.append({
            "level": "info",
            "title": f"Dominant Work Type: {top_wt['work_type']}",
            "message": f"{top_wt['work_type']} accounts for {top_wt['actual_hrs']} hrs ({top_wt['share_pct']}% of total logged effort across {top_wt['tasks']} tasks)."
        })

    return {
        "threshold_pct": overload_threshold_pct,
        "overloaded_employees": overloaded_employees[:top_n],
        "overloaded_services": overloaded_services[:top_n],
        "overloaded_work_table": overloaded_work_table[:8],
        "attention_points": attention_points,
        "burnout_analysis": burnout_analysis
    }

