"""
ai_copilot.py
Intelligent Conversational AI Copilot for Resource Utilization Timesheet Analysis.
Powered by Google Gemini API (or any OpenAI-compatible LLM endpoint).
Features:
- Multi-turn conversational Q&A over loaded timesheet metrics and granular tasks
- Natural language query handling in English, Hindi, and Hinglish
- Automatic anomaly and root-cause analysis
- Dynamic suggestions with drill-down actions
- Resilient deterministic fallback for offline / key-less operation
"""

from __future__ import annotations
import json
import os
import re
from typing import Any, Dict, List, Optional
import httpx
import pandas as pd

from modules.db import get_report_tasks

GEMINI_DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
GEMINI_DEFAULT_MODEL = "gemini-flash-lite-latest"


def build_system_context(report_summary: Dict[str, Any], report_id: int) -> str:
    """Builds a rich, compact context payload for the LLM."""
    exec_data = report_summary.get("executive", {})
    totals = report_summary.get("totals", {})
    by_work_type = report_summary.get("by_work_type", [])
    by_emp = report_summary.get("by_employee", [])
    by_svc = report_summary.get("by_service", [])
    hygiene = report_summary.get("hygiene", {})
    heatmap = report_summary.get("heatmap", {})
    ordered_weeks = report_summary.get("ordered_weeks", [])

    compact = {
        "period": report_summary.get("period_label", "August 2026"),
        "month": report_summary.get("month_label", "August 2026"),
        "kpis": {
            "total_tasks": exec_data.get("total_tasks") or totals.get("tasks", 0),
            "planned_expected_hrs": exec_data.get("expected_hrs") or totals.get("expected_hrs", 0),
            "actual_logged_hrs": exec_data.get("actual_hrs") or totals.get("actual_hrs", 0),
            "variance_hrs": totals.get("variance", 0),
            "capacity_utilization_pct": totals.get("utilization_pct", 0),
            "active_headcount": exec_data.get("total_headcount", len(by_emp)),
            "overloaded_count": exec_data.get("overloaded_count", 0)
        },
        "work_types": [
            {"type": wt.get("work_type"), "hours": wt.get("actual_hrs"), "share_pct": wt.get("share_pct")}
            for wt in by_work_type[:6]
        ],
        "top_employees": [
            {
                "name": e.get("employee"),
                "tasks": e.get("tasks"),
                "actual_hrs": e.get("actual_hrs"),
                "expected_hrs": e.get("expected_hrs"),
                "utilization_pct": e.get("utilization_pct"),
                "status": e.get("status_label") or ("Overloaded" if (e.get("utilization_pct") or 0) > 100 else "Optimal")
            }
            for e in by_emp[:10]
        ],
        "top_universities_services": [
            {
                "name": s.get("service"),
                "tasks": s.get("tasks"),
                "actual_hrs": s.get("actual_hrs"),
                "share_pct": s.get("share_pct")
            }
            for s in by_svc[:10]
        ],
        "hygiene_audit": {
            "hygiene_score": hygiene.get("score", 94),
            "grade": hygiene.get("grade", "A+"),
            "weekend_tasks_count": hygiene.get("weekend_tasks_count", 0),
            "overtime_spikes_count": hygiene.get("overtime_spikes_count", 0),
            "vague_tasks_count": hygiene.get("vague_tasks_count", 0),
            "missing_hours_count": hygiene.get("missing_hours_count", 0),
            "total_flagged": hygiene.get("total_flagged", 0)
        },
        "heatmap": {
            "total_logged_days": heatmap.get("total_logged_days", 0),
            "peak_day": heatmap.get("busiest_day"),
            "peak_day_hours": heatmap.get("busiest_day_hours", 0)
        },
        "active_weeks": ordered_weeks
    }

    return (
        "You are 'Antigravity AI Copilot', an expert executive AI resource management analyst and timesheet intelligence advisor. "
        "You help engineering managers, directors, and team leads understand team workload, burnout risks, client distribution, anomalies, and efficiency.\n\n"
        "Guidelines:\n"
        "1. Understand and respond fluently in English, Hindi, or Hinglish depending on what language the user uses.\n"
        "2. Ground ALL numbers strictly in the provided report context. Never hallucinate hours, names, or metrics.\n"
        "3. Keep responses structured, professional, executive-ready, and easy to read with emojis and bold key metrics.\n"
        "4. When discussing overloaded engineers or high-demand universities, offer practical management recommendations.\n"
        "5. If the user asks for an email or Slack digest, format it cleanly so they can copy and send it immediately.\n\n"
        f"TIMESHEET REPORT METRICS CONTEXT:\n{json.dumps(compact, indent=2)}"
    )


def handle_offline_copilot_query(user_query: str, report_summary: Dict[str, Any], report_id: int) -> str:
    """Deterministic, intelligent rule-based answers when Gemini API key is not yet set."""
    q = user_query.lower().strip()
    exec_data = report_summary.get("executive", {})
    totals = report_summary.get("totals", {})
    by_emp = report_summary.get("by_employee", [])
    by_svc = report_summary.get("by_service", [])
    hygiene = report_summary.get("hygiene", {})

    # Overload / Burnout query
    if any(k in q for k in ["overload", "burnout", "kaun", "who", "zyada", "excess", "100%"]):
        overloaded = [e for e in by_emp if (e.get("utilization_pct") or 0) > 100]
        if overloaded:
            names_list = "\n".join([
                f"- **{e['employee']}**: {e['actual_hrs']} hrs logged vs {e['expected_hrs']} planned ({e['utilization_pct']}% capacity, **+{e['variance']} hrs** overrun)"
                for e in overloaded
            ])
            return (
                f"🚨 **Overload & Burnout Alert**:\n\n"
                f"Currently **{len(overloaded)} active engineer(s)** exceed 100% baseline capacity:\n"
                f"{names_list}\n\n"
                f"💡 *Recommendation:* Consider redistributing upcoming support tickets to avoid burnout and quality degradation."
            )
        else:
            return "✅ **Good News:** Currently no engineers are operating above 100% overload capacity. The team is within safe bandwidth limits."

    # Weekend work query
    if any(k in q for k in ["weekend", "saturday", "sunday", "sat", "sun"]):
        w_cnt = hygiene.get("weekend_tasks_count", 0)
        return (
            f"🗓️ **Weekend Work Audit**:\n\n"
            f"- **{w_cnt} task(s)** were logged on Saturdays or Sundays during this period.\n"
            f"- You can inspect these exact records by clicking on the **'🗓️ Weekend Logs'** chip on the Timesheet Hygiene Radar."
        )

    # Overtime spikes query
    if any(k in q for k in ["overtime", "spike", "surge", "10h", "10 hour", "ghante"]):
        ot_cnt = hygiene.get("overtime_spikes_count", 0)
        return (
            f"⚡ **Overtime Spikes Analysis**:\n\n"
            f"- There were **{ot_cnt} employee-day(s)** where an engineer logged **>10.0 hours** in a single working day.\n"
            f"- This signals potential crunch days or sprint delivery deadlines."
        )

    # University / Client query
    if any(k in q for k in ["university", "client", "service", "ralvv", "jiwaji", "bhoj", "top"]):
        if by_svc:
            top_3 = by_svc[:3]
            top_list = "\n".join([
                f"{i+1}. **{s['service']}**: {s['actual_hrs']} hrs ({s['share_pct']}% of total bandwidth) across {s['tasks']} tasks"
                for i, s in enumerate(top_3)
            ])
            return (
                f"🏛️ **Top Client & University Allocation**:\n\n"
                f"{top_list}\n\n"
                f"Total active clients tracked: **{len(by_svc)}** institutions."
            )

    # General Executive Summary
    tot_tasks = exec_data.get("total_tasks") or totals.get("tasks", 0)
    tot_act = exec_data.get("actual_hrs") or totals.get("actual_hrs", 0)
    tot_exp = exec_data.get("expected_hrs") or totals.get("expected_hrs", 0)
    util = totals.get("utilization_pct", 0)
    hc = exec_data.get("total_headcount", len(by_emp))

    return (
        f"📊 **Timesheet Executive Overview**:\n\n"
        f"- **Active Engineers:** {hc}\n"
        f"- **Total Tasks Delivered:** {tot_tasks}\n"
        f"- **Total Actual Effort:** {tot_act} hrs (vs {tot_exp} hrs baseline, **{util}% utilization**)\n"
        f"- **Timesheet Hygiene Score:** {hygiene.get('score', 94)}/100 (Grade {hygiene.get('grade', 'A+')})\n\n"
        f"💬 *Tip: Enter your Gemini API Key using the ⚙️ Settings button to unlock deep reasoning, custom queries, and automatic memo drafting!*"
    )


async def ask_gemini_copilot(
    user_query: str,
    report_summary: Dict[str, Any],
    report_id: int,
    api_key: Optional[str] = None,
    history: Optional[List[Dict[str, str]]] = None,
    base_url: Optional[str] = None,
    model_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Main entrypoint for the AI Chatbot Copilot.
    Uses Gemini API if key is present; otherwise falls back gracefully to deterministic analysis.
    """
    key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("LLM_API_KEY")

    if not key or not key.strip():
        # Clean offline response
        reply = handle_offline_copilot_query(user_query, report_summary, report_id)
        return {
            "reply": reply,
            "provider": "Deterministic Engine (No API Key)",
            "has_api_key": False
        }

    url = base_url or os.environ.get("LLM_BASE_URL") or GEMINI_DEFAULT_BASE_URL
    model = model_name or os.environ.get("LLM_MODEL") or GEMINI_DEFAULT_MODEL
    endpoint = url.rstrip('/') + "/chat/completions"

    system_prompt = build_system_context(report_summary, report_id)

    messages = [{"role": "system", "content": system_prompt}]

    # Include recent history (up to last 6 turns)
    if history:
        for h in history[-6:]:
            if h.get("role") in ["user", "assistant"] and h.get("content"):
                messages.append({"role": h["role"], "content": h["content"]})

    messages.append({"role": "user", "content": user_query})

    headers = {
        "Authorization": f"Bearer {key.strip()}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.4,
        "max_tokens": 1200
    }

    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.post(endpoint, headers=headers, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                return {
                    "reply": content,
                    "provider": f"Google Gemini ({model})",
                    "has_api_key": True
                }
            else:
                fallback_msg = handle_offline_copilot_query(user_query, report_summary, report_id)
                return {
                    "reply": f"{fallback_msg}\n\n*(Note: Gemini API returned HTTP {resp.status_code}. Using local analytics engine.)*",
                    "provider": "Fallback Engine",
                    "has_api_key": False
                }
    except Exception as e:
        fallback_msg = handle_offline_copilot_query(user_query, report_summary, report_id)
        return {
            "reply": f"{fallback_msg}\n\n*(Note: Could not reach Gemini network ({str(e)[:60]}). Using local analytics engine.)*",
            "provider": "Fallback Engine",
            "has_api_key": False
        }
