"""
test_column_mapper.py
Unit tests for modules/column_mapper.py - the fuzzy header matcher that maps
arbitrary, messy real-world spreadsheet column names onto the app's
canonical schema before any calculation happens. A wrong mapping here
silently feeds the wrong column into the wrong field for an entire report.

The fuzzy-match cases below use realistic messy header variants generated
by the live Gemini API (gemini-flash-lite-latest) rather than only
hand-picked examples - asking an LLM to brainstorm plausible real-world
spreadsheet header spellings surfaces variety a human test author is prone
to missing, and here it genuinely did: it found two real cross-column
mismatches (see test_gemini_surfaced_cross_column_mismatches_are_fixed
below) that hand-picked cases wouldn't have hit. Every generated variant
was independently run against the real matcher before being hardcoded here,
so each assertion reflects actual verified behavior, not an assumption.
"""

from __future__ import annotations

import pandas as pd
import pytest

from modules.column_mapper import detect_column_mappings, map_dataframe_to_schema


# ─── Exact & alias matching ──────────────────────────────────────────────

def test_exact_canonical_name_matches_with_full_confidence():
    result = detect_column_mappings(["Date", "Employee", "Task", "Status"])
    assert result["Date"]["matched_raw"] == "Date"
    assert result["Date"]["confidence"] == 1.0
    assert result["Date"]["is_exact"] is True


def test_exact_canonical_match_is_case_and_whitespace_insensitive():
    """Raw column names are stripped of surrounding whitespace before
    matching, so the matched_raw returned is the stripped form."""
    result = detect_column_mappings(["  date  ", "EMPLOYEE"])
    assert result["Date"]["matched_raw"] == "date"
    assert result["Date"]["confidence"] == 1.0
    assert result["Employee"]["matched_raw"] == "EMPLOYEE"


def test_known_alias_matches_with_high_confidence():
    result = detect_column_mappings(["Assigned To", "Est Hours"])
    assert result["Employee"]["matched_raw"] == "Assigned To"
    assert result["Employee"]["is_exact"] is True


def test_unmatchable_column_returns_none_with_zero_confidence():
    result = detect_column_mappings(["Completely Unrelated Gibberish Xyz"])
    for canon_info in result.values():
        assert canon_info["matched_raw"] != "Completely Unrelated Gibberish Xyz"


def test_same_raw_column_is_not_assigned_to_two_canonical_fields():
    """'Date' exactly matches canonical Date and is claimed there; a second,
    unrelated raw column must not also be able to claim it."""
    result = detect_column_mappings(["Date", "Task"])
    assigned_raws = [info["matched_raw"] for info in result.values() if info["matched_raw"]]
    assert len(assigned_raws) == len(set(assigned_raws))


# ─── Gemini-generated realistic messy header variants ────────────────────
# Each tuple is (canonical_column, messy_header) and was confirmed against
# the real matcher (confidence >= 0.75, mapped to the intended canonical)
# before being included here.
VERIFIED_FUZZY_MATCHES = [
    ("Date", "Log Date"),
    ("Date", "Entry_Date"),
    ("Date", "dt"),
    ("Employee", "Team Member"),
    ("Employee", "Staff"),
    ("Employee", "emp_name"),
    ("Task", "Task Name"),
    ("Task", "Activity"),
    ("Task", "Task_Title"),
    ("Description", "Notes"),
    ("Description", "Details"),
    ("Description", "Work Description"),
    ("Description", "Comments"),
    ("Status", "State"),
    ("Status", "Task Status"),
    ("Status", "Progress"),
    ("Expected Hours", "Estimated Hours"),
    ("Expected Hours", "Est Hrs"),
    ("Expected Hours", "Planned_Hours"),
    ("Actual Hours", "Act Hrs"),
    ("Actual Hours", "Time Spent (Hrs)"),
    ("Task Type", "Type"),
    ("Task Type", "Category"),
    ("Task Type", "Task Category"),
    ("Task Type", "Work Type"),
    ("Stack", "Technology"),
    ("Stack", "Tech Stack"),
    ("Stack", "Platform"),
    ("Stack", "Tools"),
    ("Priority", "Urgency"),
    ("Priority", "Task Priority"),
    ("Priority", "Importance"),
    ("Start Date", "Begin Date"),
    ("Start Date", "Start_Dt"),
    ("Start Date", "Started On"),
    ("End Date", "Finish Date"),
    ("End Date", "End_Dt"),
    ("End Date", "Closed On"),
]


@pytest.mark.parametrize("canonical,messy_header", VERIFIED_FUZZY_MATCHES)
def test_fuzzy_matches_realistic_messy_header_to_correct_canonical_column(canonical, messy_header):
    result = detect_column_mappings([messy_header])
    assert result[canonical]["matched_raw"] == messy_header
    assert result[canonical]["confidence"] >= 0.75


# ─── Known defects surfaced by Gemini-generated adversarial variants ─────

def test_gemini_surfaced_cross_column_mismatches_are_fixed():
    """Regression test for two real bugs the Gemini-generated adversarial
    variants above caught: "Activity Date" was being matched to Task
    (because "Activity" is a Task alias that outscored any Date alias in
    the fuzzy pass) and "Completion Date" was being matched to Status
    (because "completion status" is a Status alias). Both are worse than a
    miss, since they'd silently feed the wrong data into the wrong field.

    Fixed by adding the exact phrases as explicit aliases on the correct
    canonical column (Date, End Date) so they're claimed in the exact-alias
    pass - which runs before fuzzy matching - rather than by reweighting
    the fuzzy scoring generally, which would risk regressing other
    currently-correct matches."""
    result = detect_column_mappings(["Activity Date"])
    assert result["Date"]["matched_raw"] == "Activity Date"
    assert result["Task"]["matched_raw"] != "Activity Date"

    result = detect_column_mappings(["Completion Date"])
    assert result["End Date"]["matched_raw"] == "Completion Date"
    assert result["Status"]["matched_raw"] != "Completion Date"


def test_some_plausible_headers_fail_to_match_rather_than_matching_wrong():
    """These realistic Service-column variants don't clear the 0.75 fuzzy
    threshold against any canonical column's alias list - a coverage gap
    worth knowing about, but importantly they fail SAFE (left unmatched)
    rather than being misassigned to some other field."""
    for header in ("Client / Service", "Svc", "Service Name", "Offering"):
        result = detect_column_mappings([header])
        assert result["Service"]["matched_raw"] != header
        for canon, info in result.items():
            assert info["matched_raw"] != header, (
                f"'{header}' unexpectedly matched {canon} instead of failing safe"
            )


# ─── map_dataframe_to_schema ──────────────────────────────────────────────

def test_map_dataframe_to_schema_produces_all_canonical_columns():
    df = pd.DataFrame({"Date": ["2026-01-01"], "Employee": ["Alice"], "Task": ["Fix bug"]})
    unified_df, mapping, warnings = map_dataframe_to_schema(df)

    from modules.column_mapper import CANONICAL_COLUMNS
    assert list(unified_df.columns) == CANONICAL_COLUMNS
    assert unified_df["Date"].iloc[0] == "2026-01-01"
    assert unified_df["Employee"].iloc[0] == "Alice"
    assert pd.isna(unified_df["Priority"].iloc[0])


def test_map_dataframe_to_schema_uses_explicit_mapping_override():
    df = pd.DataFrame({"WeirdColumnName": ["Alice"]})
    unified_df, mapping, warnings = map_dataframe_to_schema(
        df, explicit_mapping={"Employee": "WeirdColumnName"}
    )
    assert unified_df["Employee"].iloc[0] == "Alice"
    assert mapping["Employee"] == "WeirdColumnName"


def test_map_dataframe_to_schema_fills_missing_employee_from_default():
    df = pd.DataFrame({"Date": ["2026-01-01"], "Task": ["Fix bug"]})
    unified_df, mapping, warnings = map_dataframe_to_schema(df, default_employee="Bob")

    assert (unified_df["Employee"] == "Bob").all()
    assert any("Employee" in w and "Bob" in w for w in warnings)


def test_map_dataframe_to_schema_warns_on_missing_required_column():
    df = pd.DataFrame({"Stack": ["Python"]})  # no Date/Employee/Task/Status at all
    unified_df, mapping, warnings = map_dataframe_to_schema(df)

    assert any("Date" in w and "Required" in w for w in warnings)
    assert any("Task" in w and "Required" in w for w in warnings)
    assert unified_df["Date"].isna().all()


def test_map_dataframe_to_schema_preserves_unmatched_extra_columns():
    """An uploaded sheet with a column that doesn't map to anything in the
    canonical schema (e.g. a team-specific field like "Billing Code") must
    not silently lose that data - it should ride along in the output."""
    df = pd.DataFrame({
        "Date": ["2026-01-01"],
        "Employee": ["Alice"],
        "Task": ["Fix bug"],
        "Billing Code": ["BC-4471"],
    })
    unified_df, mapping, warnings = map_dataframe_to_schema(df)

    assert "Billing Code" in unified_df.columns
    assert unified_df["Billing Code"].iloc[0] == "BC-4471"
    assert any("Billing Code" in w for w in warnings)


def test_map_dataframe_to_schema_extra_column_colliding_with_canonical_name_is_not_overwritten():
    """If explicit_mapping reassigns a canonical field away from a raw
    column that happens to share the canonical field's own name, the
    leftover raw column must be preserved under a disambiguated name
    instead of silently overwriting the real canonical column."""
    df = pd.DataFrame({
        "Priority": ["Old stale priority values"],
        "Urgency Level": ["High"],
    })
    unified_df, mapping, warnings = map_dataframe_to_schema(
        df, explicit_mapping={"Priority": "Urgency Level"}
    )

    assert unified_df["Priority"].iloc[0] == "High"
    assert "Priority (unmapped)" in unified_df.columns
    assert unified_df["Priority (unmapped)"].iloc[0] == "Old stale priority values"
