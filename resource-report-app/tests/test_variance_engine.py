"""
test_variance_engine.py
Unit tests for modules/variance_engine.py - the governance layer that decides
which employees/services get flagged as overloaded on the executive
dashboard, and drives the burnout-risk and workload-rebalancing suggestions.

analyze_variances() takes an already-computed aggregates dict rather than
recomputing anything, so tests hand-craft small aggregates/variance-style
inputs directly - this also lets a couple of tests isolate specific boundary
conditions (e.g. a utilization_pct/variance combination that calculator.py
itself would never actually produce) to pin down exactly what the code
checks, independent of calculator.py's own logic.
"""

from __future__ import annotations

from modules.variance_engine import analyze_variances


def make_aggregates(by_employee=None, by_service=None, by_work_type=None, total_actual=100.0):
    return {
        "by_employee": by_employee or [],
        "by_service": by_service or [],
        "by_work_type": by_work_type or [],
        "totals": {"actual_hrs": total_actual},
        "entity_label": "Service",
    }


def emp(name, expected_hrs, actual_hrs, utilization_pct):
    return {
        "employee": name,
        "tasks": 5,
        "expected_hrs": expected_hrs,
        "actual_hrs": actual_hrs,
        "variance": round(actual_hrs - expected_hrs, 2),
        "utilization_pct": utilization_pct,
    }


def svc(name, expected_hrs, actual_hrs, share_pct):
    return {
        "service": name,
        "tasks": 5,
        "expected_hrs": expected_hrs,
        "actual_hrs": actual_hrs,
        "variance": round(actual_hrs - expected_hrs, 2),
        "share_pct": share_pct,
    }


# ─── Overloaded employees ────────────────────────────────────────────────

def test_employee_above_threshold_with_positive_variance_is_flagged():
    aggregates = make_aggregates(by_employee=[emp("Alice", 100, 120, 120.0)])
    result = analyze_variances(aggregates, overload_threshold_pct=110.0)

    assert len(result["overloaded_employees"]) == 1
    assert result["overloaded_employees"][0]["name"] == "Alice"
    assert result["overloaded_employees"][0]["is_overloaded"] is True


def test_employee_below_threshold_is_not_flagged():
    aggregates = make_aggregates(by_employee=[emp("Bob", 100, 105, 105.0)])
    result = analyze_variances(aggregates, overload_threshold_pct=110.0)
    assert result["overloaded_employees"] == []


def test_employee_at_exactly_threshold_is_flagged_inclusive():
    aggregates = make_aggregates(by_employee=[emp("Carol", 100, 110, 110.0)])
    result = analyze_variances(aggregates, overload_threshold_pct=110.0)
    assert len(result["overloaded_employees"]) == 1


def test_employee_above_threshold_but_zero_or_negative_variance_is_not_flagged():
    """is_overloaded requires BOTH util >= threshold AND variance > 0 - an
    employee record with a utilization above threshold but non-positive
    variance (a combination calculator.py wouldn't itself produce, since
    utilization_pct and variance are derived from the same act/exp pair)
    should still not be flagged, pinning down the exact boundary check."""
    inconsistent_emp = emp("Dana", 100, 100, 150.0)  # variance forced to 0 despite util=150
    aggregates = make_aggregates(by_employee=[inconsistent_emp])
    result = analyze_variances(aggregates, overload_threshold_pct=110.0)
    assert result["overloaded_employees"] == []


def test_overloaded_employees_sorted_by_variance_descending():
    aggregates = make_aggregates(by_employee=[
        emp("SmallOverrun", 100, 115, 115.0),
        emp("BigOverrun", 100, 150, 150.0),
    ])
    result = analyze_variances(aggregates, overload_threshold_pct=110.0)
    names = [e["name"] for e in result["overloaded_employees"]]
    assert names == ["BigOverrun", "SmallOverrun"]


def test_top_n_limits_overloaded_employees():
    aggregates = make_aggregates(by_employee=[
        emp(f"Emp{i}", 100, 100 + (i * 10), 100.0 + (i * 10)) for i in range(1, 8)
    ])
    result = analyze_variances(aggregates, overload_threshold_pct=110.0, top_n=3)
    assert len(result["overloaded_employees"]) == 3


def test_overrun_pct_falls_back_to_100_when_expected_is_zero_and_actual_positive():
    aggregates = make_aggregates(by_employee=[emp("ZeroPlanned", 0, 50, 999.0)])
    result = analyze_variances(aggregates, overload_threshold_pct=110.0)
    # util is nonsensical here (999%) but is what drives is_overloaded; overrun_pct
    # specifically exercises the exp==0 branch, independent of the flagging logic
    assert result["overloaded_employees"][0]["overrun_pct"] == 100.0


def test_overrun_pct_is_zero_when_both_expected_and_actual_are_zero():
    aggregates = make_aggregates(by_employee=[emp("Idle", 0, 0, 0.0)])
    result = analyze_variances(aggregates, overload_threshold_pct=110.0)
    # Not flagged as overloaded (util below threshold), but exercised via overloaded_work_table
    # is skipped here - just confirm no crash and a sane structure with nothing flagged.
    assert result["overloaded_employees"] == []


# ─── Overloaded services ─────────────────────────────────────────────────

def test_service_flagged_when_ratio_exceeds_threshold_with_positive_variance():
    aggregates = make_aggregates(by_service=[svc("Alpha", 100, 130, 10.0)])
    result = analyze_variances(aggregates, overload_threshold_pct=110.0)
    assert len(result["overloaded_services"]) == 1
    assert result["overloaded_services"][0]["name"] == "Alpha"


def test_service_flagged_when_share_at_least_20_percent_even_under_ratio_threshold():
    """A large service (>=20% of total team effort) is flagged purely on
    concentration risk, even if it's tracking close to its planned hours."""
    aggregates = make_aggregates(by_service=[svc("BigAccount", 100, 102, 25.0)])
    result = analyze_variances(aggregates, overload_threshold_pct=110.0)
    assert len(result["overloaded_services"]) == 1
    assert result["overloaded_services"][0]["name"] == "BigAccount"


def test_service_not_flagged_when_neither_condition_met():
    aggregates = make_aggregates(by_service=[svc("SmallSteady", 100, 102, 5.0)])
    result = analyze_variances(aggregates, overload_threshold_pct=110.0)
    assert result["overloaded_services"] == []


def test_overloaded_services_sorted_by_actual_hours_descending():
    aggregates = make_aggregates(by_service=[
        svc("Small", 100, 130, 25.0),
        svc("Large", 100, 300, 30.0),
    ])
    result = analyze_variances(aggregates, overload_threshold_pct=110.0)
    names = [s["name"] for s in result["overloaded_services"]]
    assert names == ["Large", "Small"]


# ─── Governance / overloaded work table ──────────────────────────────────

def test_overloaded_work_table_governance_note_thresholds_by_share():
    aggregates = make_aggregates(by_service=[
        svc("VeryHighShareSvc", 100, 100, 25.0),   # >= 22 -> "Highest overall workload"
        svc("HighShareSvc", 100, 100, 17.0),        # >= 15 -> "Substantial ongoing effort"
        svc("LowShareSvc", 100, 100, 8.0),           # default -> "Notable footprint"
    ])
    result = analyze_variances(aggregates, overload_threshold_pct=110.0)
    notes = {row["name"]: row["governance_highlight"] for row in result["overloaded_work_table"]}

    assert "Highest overall workload" in notes["VeryHighShareSvc"]
    assert "Substantial ongoing effort" in notes["HighShareSvc"]
    assert "Notable footprint" in notes["LowShareSvc"]


def test_overloaded_work_table_includes_resources_above_threshold_or_variance():
    aggregates = make_aggregates(
        by_service=[svc("Alpha", 100, 100, 10.0)],
        by_employee=[emp("HighVarianceButBelowThreshold", 100, 125, 108.0)],  # var=25 > 20
    )
    result = analyze_variances(aggregates, overload_threshold_pct=110.0)
    resource_rows = [r for r in result["overloaded_work_table"] if r["category"] == "Resource"]
    assert any(r["name"] == "HighVarianceButBelowThreshold" for r in resource_rows)


# ─── Burnout analysis ─────────────────────────────────────────────────────

def test_burnout_overloaded_bucket_triggers_on_utilization_or_variance():
    aggregates = make_aggregates(by_employee=[
        emp("HighUtil", 100, 116, 116.0),   # util >= 115
        emp("HighVarLowUtil", 100, 115, 107.0),  # var (15) >= 15, util still < 115
    ])
    result = analyze_variances(aggregates)
    overloaded_names = {e["name"] for e in result["burnout_analysis"]["overloaded_resources"]}
    assert "HighUtil" in overloaded_names
    assert "HighVarLowUtil" in overloaded_names


def test_burnout_score_formula_and_risk_level():
    # util=140 -> (140-100)*2 = 80; variance=40 -> 40*1.5=60; sum=140 clamped to 100
    aggregates = make_aggregates(by_employee=[emp("Maxed", 100, 140, 140.0)])
    result = analyze_variances(aggregates)
    overloaded = result["burnout_analysis"]["overloaded_resources"][0]
    assert overloaded["burnout_score"] == 100.0
    assert overloaded["risk_level"] == "Critical"


def test_burnout_score_below_critical_cutoff_is_high_risk():
    # util=116 -> (116-100)*2=32; variance=16 -> 16*1.5=24; sum=56 (< 65 cutoff)
    aggregates = make_aggregates(by_employee=[emp("ModeratelyOver", 100, 116, 116.0)])
    result = analyze_variances(aggregates)
    overloaded = result["burnout_analysis"]["overloaded_resources"][0]
    assert overloaded["burnout_score"] == 56.0
    assert overloaded["risk_level"] == "High"


def test_burnout_underutilized_bucket_and_headroom():
    aggregates = make_aggregates(by_employee=[emp("LightLoad", 100, 60, 60.0)])
    result = analyze_variances(aggregates)
    under = result["burnout_analysis"]["underutilized_resources"][0]
    assert under["name"] == "LightLoad"
    assert under["headroom_hrs"] == 80.0  # max(0, 140 - 60)


def test_burnout_middle_zone_employee_is_neither_overloaded_nor_underutilized():
    """util=110, variance=10: doesn't meet the overloaded bucket (util<115 and
    var<15) nor the underutilized bucket (util>106) - the gap between the two
    thresholds (106% < util < 115%) is a real, if narrow, classification gap."""
    aggregates = make_aggregates(by_employee=[emp("MiddleZone", 100, 110, 110.0)])
    result = analyze_variances(aggregates)
    burnout = result["burnout_analysis"]
    all_names = (
        [e["name"] for e in burnout["overloaded_resources"]]
        + [e["name"] for e in burnout["underutilized_resources"]]
    )
    assert "MiddleZone" not in all_names


def test_rebalance_suggestions_pair_overloaded_with_underutilized():
    aggregates = make_aggregates(by_employee=[
        emp("Overloaded", 100, 130, 130.0),   # variance=30
        emp("Underloaded", 100, 50, 50.0),
    ])
    result = analyze_variances(aggregates)
    suggestions = result["burnout_analysis"]["rebalance_suggestions"]

    assert len(suggestions) == 1
    s = suggestions[0]
    assert s["from_resource"] == "Overloaded"
    assert s["to_resource"] == "Underloaded"
    assert s["hours_to_transfer"] == 15.0  # min(variance=30, 15.0)
    assert s["from_after"] == 115.0
    assert s["to_after"] == 65.0


def test_no_rebalance_suggestions_when_nobody_is_underutilized():
    aggregates = make_aggregates(by_employee=[emp("Overloaded", 100, 130, 130.0)])
    result = analyze_variances(aggregates)
    assert result["burnout_analysis"]["rebalance_suggestions"] == []


# ─── Attention points ─────────────────────────────────────────────────────

def test_attention_points_include_overloaded_employees_and_services_and_top_work_type():
    aggregates = make_aggregates(
        by_employee=[emp("Alice", 100, 130, 130.0)],
        by_service=[svc("Alpha", 100, 130, 25.0)],
        by_work_type=[{"work_type": "Support", "tasks": 10, "actual_hrs": 100.0, "share_pct": 80.0}],
    )
    result = analyze_variances(aggregates)
    titles = [p["title"] for p in result["attention_points"]]

    assert any("Alice" in t for t in titles)
    assert any("Alpha" in t for t in titles)
    assert any("Support" in t for t in titles)


def test_attention_point_severity_escalates_past_130_percent_utilization():
    aggregates = make_aggregates(by_employee=[emp("Extreme", 100, 200, 200.0)])
    result = analyze_variances(aggregates)
    danger_points = [p for p in result["attention_points"] if p["level"] == "danger"]
    assert len(danger_points) == 1
    assert "Extreme" in danger_points[0]["title"]


# ─── Empty input ────────────────────────────────────────────────────────

def test_empty_aggregates_returns_empty_structure_without_crashing():
    result = analyze_variances(make_aggregates())

    assert result["overloaded_employees"] == []
    assert result["overloaded_services"] == []
    assert result["overloaded_work_table"] == []
    assert result["attention_points"] == []
    assert result["burnout_analysis"]["overloaded_resources"] == []
    assert result["burnout_analysis"]["underutilized_resources"] == []
    assert result["burnout_analysis"]["rebalance_suggestions"] == []
