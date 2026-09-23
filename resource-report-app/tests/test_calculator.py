"""
test_calculator.py
Unit tests for modules/calculator.py - the aggregation engine that produces
every number shown on the executive dashboard (totals, per-employee
utilization %, per-service share %, work-type billable split).

These build small hand-computed DataFrames so each assertion can be checked
by arithmetic instead of "the route returned 200" - a wrong formula or a
shifted threshold here would silently ship a wrong number to an executive
report without any of the route-level smoke tests noticing.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from modules.calculator import (
    calculate_aggregates,
    classify_work_category,
    get_empty_aggregates,
    is_billable_category,
)


def make_row(
    employee: str,
    service: str,
    task_type: str,
    expected_hrs: float,
    actual_hrs: float,
    date: str = "2026-01-05",
    week: str = "Week 1",
    task: str = "Task",
    description: str = "",
) -> dict:
    return {
        "Date": date,
        "Service": service,
        "Employee": employee,
        "Task": task,
        "Description": description,
        "Status": "Completed",
        "Expected Hours": expected_hrs,
        "Actual Hours": actual_hrs,
        "Task Type": task_type,
        "Stack": "",
        "Priority": "Medium",
        "Start Date": date,
        "End Date": date,
        "_Parsed_Date": pd.Timestamp(date) if date else pd.NaT,
        "Week": week,
    }


def make_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


# ─── classify_work_category ─────────────────────────────────────────────

@pytest.mark.parametrize(
    "task_type,description,expected",
    [
        ("Leave", "", "Leave"),
        ("PTO", "", "Leave"),
        ("Bench", "", "Bench"),
        ("Unassigned", "", "Bench"),
        ("New Development", "", "New Development"),
        ("Feature Build", "", "New Development"),
        ("Bug Fix", "", "Issue"),
        ("Defect", "", "Issue"),
        ("Enhancement", "", "Enhancement"),
        ("Refactor", "", "Enhancement"),
        ("Meeting", "", "Other / Meeting"),
        ("Internal Discussion", "", "Other / Meeting"),
        ("Support", "", "Support"),
        ("Production Ticket", "", "Support"),
    ],
)
def test_classify_work_category_keyword_matches(task_type, description, expected):
    assert classify_work_category(task_type, description) == expected


def test_classify_work_category_falls_back_to_support_when_blank():
    assert classify_work_category("", "") == "Support"


def test_classify_work_category_falls_back_to_title_cased_custom_type():
    """An unrecognized task type with no matching keywords is preserved
    (title-cased) instead of being coerced into a bucket that misrepresents it."""
    assert classify_work_category("Marketing Campaign", "") == "Marketing Campaign"


# ─── is_billable_category ───────────────────────────────────────────────

@pytest.mark.parametrize(
    "category,expected",
    [
        ("Support", True),
        ("New Development", True),
        ("Issue", True),
        ("Enhancement", True),
        ("Billable", True),
        ("Leave", False),
        ("Bench", False),
        ("Other / Meeting", False),
    ],
)
def test_is_billable_category(category, expected):
    assert is_billable_category(category) is expected


# ─── calculate_aggregates: totals ───────────────────────────────────────

def test_totals_are_summed_and_rounded_correctly():
    df = make_df([
        make_row("Alice", "Alpha", "New Development", 20, 25),
        make_row("Alice", "Alpha", "Support", 10, 8),
        make_row("Bob", "Beta", "Issue", 15, 15),
    ])

    aggregates = calculate_aggregates(df)

    assert aggregates["totals"]["tasks"] == 3
    assert aggregates["totals"]["expected_hrs"] == 45.0
    assert aggregates["totals"]["actual_hrs"] == 48.0
    assert aggregates["totals"]["variance"] == 3.0
    assert aggregates["totals"]["utilization_pct"] == round(48 / 45 * 100, 1)

    assert aggregates["executive"]["total_headcount"] == 2
    assert aggregates["executive"]["active_services_count"] == 2


def test_totals_guard_against_division_by_zero_when_expected_hours_is_zero():
    df = make_df([make_row("Alice", "Alpha", "Support", 0, 10)])
    aggregates = calculate_aggregates(df)

    assert aggregates["totals"]["expected_hrs"] == 0.0
    assert aggregates["totals"]["utilization_pct"] == 0.0
    assert aggregates["executive"]["variance_pct"] == 0.0


def test_empty_dataframe_does_not_crash_and_zeroes_out():
    """A 0-row DataFrame that still has every column present - the realistic
    shape produced by map_dataframe_to_schema() for an uploaded file with
    headers but no data rows - must not crash the aggregator."""
    columns = list(make_row("x", "x", "x", 0, 0).keys())
    df = pd.DataFrame(columns=columns)
    aggregates = calculate_aggregates(df)

    assert aggregates["totals"]["tasks"] == 0
    assert aggregates["totals"]["expected_hrs"] == 0.0
    assert aggregates["totals"]["utilization_pct"] == 0.0
    assert aggregates["by_employee"] == []
    assert aggregates["by_service"] == []
    assert aggregates["by_work_type"] == []
    # No weeks detected in the data -> falls back to a default 5-week scaffold
    assert aggregates["ordered_weeks"] == ["Week 1", "Week 2", "Week 3", "Week 4", "Week 5"]


# ─── calculate_aggregates: employee status classification ──────────────

def test_employee_status_thresholds_classify_correctly():
    """Overloaded (>100%), Optimal (80-100%), Underutilized (50-80%), Bench (<50%)
    against a fixed 100hr nominal capacity, so utilization_pct == actual_hrs."""
    df = make_df([
        make_row("Overloaded Owen", "Alpha", "New Development", 100, 120),
        make_row("Optimal Olivia", "Alpha", "New Development", 100, 90),
        make_row("Under Uma", "Alpha", "New Development", 100, 60),
        make_row("Bench Ben", "Alpha", "New Development", 100, 20),
    ])

    aggregates = calculate_aggregates(df, nominal_capacity_per_employee=100.0)
    by_name = {e["employee"]: e for e in aggregates["by_employee"]}

    assert by_name["Overloaded Owen"]["utilization_pct"] == 120.0
    assert by_name["Overloaded Owen"]["status"] == "overloaded"
    assert by_name["Overloaded Owen"]["status_class"] == "status-high"

    assert by_name["Optimal Olivia"]["utilization_pct"] == 90.0
    assert by_name["Optimal Olivia"]["status"] == "optimal"

    assert by_name["Under Uma"]["utilization_pct"] == 60.0
    assert by_name["Under Uma"]["status"] == "underutilized"

    assert by_name["Bench Ben"]["utilization_pct"] == 20.0
    assert by_name["Bench Ben"]["status"] == "bench"

    # Only the >100% employee counts as overloaded, not the 90% one
    assert aggregates["executive"]["overloaded_count"] == 1
    assert aggregates["executive"]["total_headcount"] == 4


def test_employee_boundary_exactly_100_percent_is_not_overloaded():
    """Status check is strictly '> 100.0', so exactly-at-capacity must read Optimal."""
    df = make_df([make_row("Edge Emma", "Alpha", "Support", 100, 100)])
    aggregates = calculate_aggregates(df, nominal_capacity_per_employee=100.0)

    emma = aggregates["by_employee"][0]
    assert emma["utilization_pct"] == 100.0
    assert emma["status"] == "optimal"
    assert aggregates["executive"]["overloaded_count"] == 0


# ─── calculate_aggregates: work-type billable/non-billable split ───────

def test_billable_and_non_billable_hours_split_correctly():
    df = make_df([
        make_row("Alice", "Alpha", "New Development", 20, 25),  # billable
        make_row("Alice", "Alpha", "Support", 10, 8),            # billable
        make_row("Alice", "Alpha", "Meeting", 5, 5),              # non-billable
        make_row("Alice", "Alpha", "Leave", 8, 8),                # leave
        make_row("Alice", "Alpha", "Bench", 0, 4),                # bench
    ])

    aggregates = calculate_aggregates(df)
    total_actual = 25 + 8 + 5 + 8 + 4  # 50

    assert aggregates["executive"]["billable_utilization_pct"] == round((25 + 8) / total_actual * 100, 1)
    assert aggregates["executive"]["non_billable_pct"] == round(5 / total_actual * 100, 1)
    assert aggregates["executive"]["bench_pct"] == round(4 / total_actual * 100, 1)


def test_per_employee_billable_vs_non_billable_hours():
    df = make_df([
        make_row("Alice", "Alpha", "New Development", 20, 25),
        make_row("Alice", "Alpha", "Meeting", 5, 5),
    ])
    aggregates = calculate_aggregates(df)
    alice = aggregates["by_employee"][0]

    assert alice["billable_hrs"] == 25.0
    assert alice["non_billable_hrs"] == 5.0
    assert alice["actual_hrs"] == 30.0


# ─── calculate_aggregates: service share & attention level ─────────────

def test_service_share_pct_and_attention_level_thresholds():
    df = make_df([
        make_row("E1", "VeryHighSvc", "Support", 20, 20),
        make_row("E2", "HighSvc", "Support", 12, 12),
        make_row("E3", "MediumSvc", "Support", 7, 7),
        make_row("E4", "LowSvc", "Support", 3, 3),
        make_row("E5", "FillerSvc", "Support", 58, 58),
    ])
    # total_actual == 100, so each service's share_pct equals its raw actual hours
    aggregates = calculate_aggregates(df)
    by_name = {s["service"]: s for s in aggregates["by_service"]}

    assert by_name["VeryHighSvc"]["share_pct"] == 20.0
    assert by_name["VeryHighSvc"]["attention_level"] == "Very High"
    assert by_name["VeryHighSvc"]["level_pill"] == "high"

    assert by_name["HighSvc"]["share_pct"] == 12.0
    assert by_name["HighSvc"]["attention_level"] == "High"
    assert by_name["HighSvc"]["level_pill"] == "medium"

    assert by_name["MediumSvc"]["share_pct"] == 7.0
    assert by_name["MediumSvc"]["attention_level"] == "Medium"
    assert by_name["MediumSvc"]["level_pill"] == "medium"

    assert by_name["LowSvc"]["share_pct"] == 3.0
    assert by_name["LowSvc"]["attention_level"] == "Low"
    assert by_name["LowSvc"]["level_pill"] == "low"


# ─── calculate_aggregates: period label derivation ──────────────────────

def test_period_label_derived_from_min_and_max_dates():
    df = make_df([
        make_row("Alice", "Alpha", "Support", 5, 5, date="2026-01-05", week="Week 1"),
        make_row("Alice", "Alpha", "Support", 5, 5, date="2026-01-20", week="Week 3"),
    ])
    aggregates = calculate_aggregates(df)

    assert aggregates["period_label"] == "05-Jan-2026 to 20-Jan-2026"
    assert aggregates["month_label"] == "January 2026"


def test_period_label_falls_back_when_no_valid_dates():
    rows = [make_row("Alice", "Alpha", "Support", 5, 5)]
    rows[0]["_Parsed_Date"] = pd.NaT
    df = make_df(rows)

    aggregates = calculate_aggregates(df)
    assert aggregates["period_label"] == "Current Period"
    assert aggregates["month_label"] == "Current Month"


# ─── get_empty_aggregates: zero-baseline dashboard state ────────────────

def test_get_empty_aggregates_zero_state_structure():
    aggregates = get_empty_aggregates()

    assert aggregates["totals"]["tasks"] == 0
    assert aggregates["by_employee"] == []
    assert aggregates["by_service"] == []
    assert aggregates["by_work_type"] == []
    assert aggregates["period_label"] == "No Data (Awaiting Timesheet)"
    assert len(aggregates["action_points"]) == 5
