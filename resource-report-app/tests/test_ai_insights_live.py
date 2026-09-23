"""
test_ai_insights_live.py
Exercises the real Gemini API end-to-end using the key configured in .env,
instead of only ever testing the deterministic rule-based fallback path
(which is what tests/conftest.py forces for the route-level smoke suite).

This is the one place the live model is actually asked to reason over sample
aggregates and produce an executive summary, so it also sanity-checks that
the model's output is grounded in the data it was given rather than being
generic filler - a cheap guardrail against prompt or schema drift silently
degrading report quality.

Reads GEMINI_API_KEY directly from .env via dotenv_values() rather than
os.environ, since tests/conftest.py deliberately locks GEMINI_API_KEY to ""
for every other test to keep the route-level smoke suite deterministic and
network-free. Skips (never fails the suite) when no key is configured or the
live call doesn't succeed, since CI environments and contributors without a
personal key must still be able to run `pytest` cleanly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = APP_ROOT / ".env"


def _load_live_gemini_key() -> str:
    if not ENV_PATH.exists():
        return ""
    from dotenv import dotenv_values
    return (dotenv_values(ENV_PATH).get("GEMINI_API_KEY") or "").strip()


LIVE_GEMINI_KEY = _load_live_gemini_key()

pytestmark = pytest.mark.skipif(
    not LIVE_GEMINI_KEY,
    reason="No GEMINI_API_KEY configured in .env - skipping live Gemini API test",
)


def _sample_aggregates() -> dict:
    return {
        "period_label": "01-Jan-2026 to 31-Jan-2026",
        "entity_label": "Service",
        "totals": {
            "tasks": 12,
            "expected_hrs": 320.0,
            "actual_hrs": 365.0,
            "variance": 45.0,
            "utilization_pct": 114.1,
        },
        "by_work_type": [
            {"work_type": "Support", "tasks": 6, "expected_hrs": 150.0, "actual_hrs": 180.0, "share_pct": 49.3, "variance": 30.0},
            {"work_type": "New Development", "tasks": 6, "expected_hrs": 170.0, "actual_hrs": 185.0, "share_pct": 50.7, "variance": 15.0},
        ],
        "by_employee": [
            {"employee": "Alice", "tasks": 8, "expected_hrs": 200.0, "actual_hrs": 240.0, "variance": 40.0, "utilization_pct": 120.0},
            {"employee": "Bob", "tasks": 4, "expected_hrs": 120.0, "actual_hrs": 125.0, "variance": 5.0, "utilization_pct": 104.2},
        ],
        "by_service": [
            {"service": "Alpha", "tasks": 9, "actual_hrs": 260.0, "share_pct": 71.2},
            {"service": "Beta", "tasks": 3, "actual_hrs": 105.0, "share_pct": 28.8},
        ],
    }


def _sample_variance() -> dict:
    # Matches the full record shape modules/variance_engine.py.analyze_variances()
    # actually produces for overloaded_employees - generate_fallback_insights()
    # reads expected_hrs/actual_hrs/utilization_pct off these records directly,
    # not the trimmed shape ai_insights.py sends to the LLM as "attention_flags".
    return {
        "overloaded_employees": [
            {
                "name": "Alice",
                "expected_hrs": 200.0,
                "actual_hrs": 240.0,
                "variance": 40.0,
                "utilization_pct": 120.0,
                "overrun_pct": 20.0,
            },
        ]
    }


def test_live_gemini_returns_well_formed_executive_insights():
    from modules.ai_insights import generate_ai_insights

    result = generate_ai_insights(_sample_aggregates(), _sample_variance(), api_key=LIVE_GEMINI_KEY)

    if "Rule-Based" in result.get("provider", ""):
        pytest.skip(f"Live Gemini call did not succeed, fell back to rule-based engine: {result.get('provider')}")

    assert isinstance(result.get("executive_summary"), str)
    assert len(result["executive_summary"]) > 20

    assert isinstance(result.get("key_findings"), list)
    assert len(result["key_findings"]) >= 1
    assert all(isinstance(item, str) for item in result["key_findings"])

    assert isinstance(result.get("recommendations"), list)
    assert len(result["recommendations"]) >= 1
    assert all(isinstance(item, str) for item in result["recommendations"])

    assert "Gemini" in result["provider"]


def test_live_gemini_grounds_its_answer_in_the_supplied_data():
    """Guards against the model ignoring the payload and returning generic
    boilerplate: the real employee/service names we sent it should show up
    somewhere in its narrative."""
    from modules.ai_insights import generate_ai_insights

    result = generate_ai_insights(_sample_aggregates(), _sample_variance(), api_key=LIVE_GEMINI_KEY)
    if "Rule-Based" in result.get("provider", ""):
        pytest.skip("Live Gemini call did not succeed; nothing to validate")

    combined_text = result["executive_summary"] + " ".join(result["key_findings"]) + " ".join(result["recommendations"])
    assert any(term in combined_text for term in ("Alice", "Alpha", "Support", "Beta", "Bob"))


def test_live_gemini_invalid_key_falls_back_to_rule_based_engine():
    """An invalid key must degrade gracefully to the deterministic engine
    rather than raising - this is the failure path production traffic hits
    whenever the configured key is revoked or rate-limited."""
    from modules.ai_insights import generate_ai_insights

    result = generate_ai_insights(_sample_aggregates(), _sample_variance(), api_key="AIzaSyINVALID_KEY_FOR_TESTING_0000000")

    assert "executive_summary" in result
    assert "Rule-Based" in result["provider"]
