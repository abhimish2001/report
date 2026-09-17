"""
ai_insights.py
Generates Executive Summary, Key Findings, and Recommendations from calculated aggregates.
Sends ONLY aggregate metrics (never raw task rows) to an OpenAI-compatible LLM endpoint
(Groq, Gemini, Ollama, OpenAI, etc.).
Fails gracefully with deterministic rule-based narration if offline or API call fails.
"""

from __future__ import annotations
import json
import os
import re
from typing import Any, Dict, List, Optional
import httpx


def generate_fallback_insights(aggregates: Dict[str, Any], variance_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generates high quality, deterministic executive summary, findings,
    and recommendations when LLM API is not configured or fails.
    """
    period = aggregates.get("period_label", "the reporting period")
    totals = aggregates.get("totals", {})
    total_tasks = totals.get("tasks", 0)
    total_exp = totals.get("expected_hrs", 0.0)
    total_act = totals.get("actual_hrs", 0.0)
    total_var = totals.get("variance", 0.0)
    util_pct = totals.get("utilization_pct", 100.0)

    by_wt = aggregates.get("by_work_type", [])
    top_wt = by_wt[0] if by_wt else {"work_type": "Support", "share_pct": 0, "actual_hrs": 0}
    second_wt = by_wt[1] if len(by_wt) > 1 else None

    over_emps = variance_data.get("overloaded_employees", [])
    over_srvs = variance_data.get("overloaded_services", [])

    # Executive Summary Paragraph
    var_direction = "an overrun of" if total_var > 0 else "a savings of"
    exec_summary = (
        f"During {period}, the team delivered {total_tasks} completed and active tasks across all services. "
        f"A total of {total_act} hours was expended against a planned baseline of {total_exp} hours, "
        f"representing an overall resource utilization rate of {util_pct}% with {var_direction} {abs(total_var)} hours. "
        f"Operational work was dominated by {top_wt['work_type']} ({top_wt['actual_hrs']} hrs, {top_wt['share_pct']}% of team effort)"
    )
    if second_wt:
        exec_summary += f", followed by {second_wt['work_type']} ({second_wt['actual_hrs']} hrs, {second_wt['share_pct']}% share)."
    else:
        exec_summary += "."

    # Key Findings Bullets
    findings = []
    if over_emps:
        top_emp = over_emps[0]
        findings.append(
            f"Resource Capacity: {top_emp['name']} experienced the highest workload burden, logging {top_emp['actual_hrs']} hrs "
            f"against {top_emp['expected_hrs']} planned ({top_emp['utilization_pct']}% utilization, +{top_emp['variance']} hrs variance)."
        )
    if len(over_emps) > 1:
        names = ", ".join([e["name"] for e in over_emps[1:3]])
        findings.append(f"Additional Overload Flags: {names} exceeded standard expected capacity thresholds.")

    if over_srvs:
        top_srv = over_srvs[0]
        findings.append(
            f"Service Concentration: {top_srv['name']} required the greatest team allocation with {top_srv['actual_hrs']} hours "
            f"({top_srv['share_pct']}% of total department bandwidth)."
        )

    findings.append(
        f"Effort Distribution: {top_wt['work_type']} represents {top_wt['share_pct']}% of all engineering bandwidth, "
        f"indicating high ongoing operational and maintenance commitments relative to greenfield development."
    )

    # Recommendations Bullets
    recommendations = []
    if over_emps:
        recommendations.append(
            f"Rebalance Task Allocation: Redistribute upcoming sprint items away from {over_emps[0]['name']} "
            f"to mitigate burnout risk and maintain delivery quality."
        )
    if over_srvs:
        recommendations.append(
            f"Service SLA & Scope Alignment: Review support commitments and recurring issue root-causes for {over_srvs[0]['name']} "
            f"to streamline ticket turnaround and prevent scope creep."
        )
    recommendations.append(
        "Standardize Estimation Buffers: Adjust baseline task estimation models for complex support and bug fixes, "
        "as actual hours routinely outpace initial planning."
    )

    return {
        "executive_summary": exec_summary,
        "key_findings": findings,
        "recommendations": recommendations,
        "provider": "Rule-Based Engine (Fallback / Offline)"
    }


GEMINI_DEFAULT_API_KEY = "AIzaSyB0oFRGrHDg8fJgTwJIiavfialaSp7yMao"
GEMINI_DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
GEMINI_DEFAULT_MODEL = "gemini-3.6-flash"


def generate_ai_insights(
    aggregates: Dict[str, Any],
    variance_data: Dict[str, Any],
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    model_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Calls Google Gemini (or any OpenAI-compatible API) to generate executive narrative sections.
    Pre-configured to use the free Google Gemini API key.
    If network is unavailable, falls back gracefully to deterministic rule-based output.
    """
    key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("LLM_API_KEY") or GEMINI_DEFAULT_API_KEY
    url = base_url or os.environ.get("LLM_BASE_URL") or GEMINI_DEFAULT_BASE_URL
    model = model_name or os.environ.get("LLM_MODEL") or GEMINI_DEFAULT_MODEL

    if not key:
        return generate_fallback_insights(aggregates, variance_data)

    # Clean endpoints
    endpoint = url.rstrip('/') + "/chat/completions"

    # Compact payload containing ONLY aggregate summaries
    compact_payload = {
        "period": aggregates.get("period_label"),
        "totals": aggregates.get("totals"),
        "by_work_type": aggregates.get("by_work_type", [])[:6],
        "by_employee": [
            {
                "name": e["employee"],
                "tasks": e["tasks"],
                "expected": e["expected_hrs"],
                "actual": e["actual_hrs"],
                "variance": e["variance"],
                "utilization_pct": e["utilization_pct"]
            } for e in aggregates.get("by_employee", [])[:10]
        ],
        "by_service": [
            {
                "name": s["service"],
                "tasks": s["tasks"],
                "actual": s["actual_hrs"],
                "share_pct": s["share_pct"]
            } for s in aggregates.get("by_service", [])[:10]
        ],
        "attention_flags": [
            {
                "name": e["name"],
                "overrun_pct": e["overrun_pct"],
                "variance": e["variance"]
            } for e in variance_data.get("overloaded_employees", [])[:5]
        ]
    }

    entity_label = aggregates.get("entity_label", "Project / Service")
    system_prompt = (
        f"You are an expert executive resource management and governance analyst for a professional team delivering work across {entity_label}s. "
        "Analyze the provided aggregate team metrics and produce an executive-ready report in JSON format. "
        "Do not hallucinate names or figures. Be concise, professional, and actionable.\n"
        "Required JSON schema:\n"
        "{\n"
        '  "executive_summary": "1-2 paragraphs of executive summary",\n'
        '  "key_findings": ["3 to 5 clear bullet points highlighting key trends, overruns, and resource load"],\n'
        '  "recommendations": ["3 to 4 actionable management recommendations"]\n'
        "}"
    )

    user_prompt = f"Team Aggregates:\n{json.dumps(compact_payload, indent=2)}"

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json"
    }

    # Check if calling Google Gemini native API
    is_gemini_native = "generativelanguage.googleapis.com" in url or key.startswith("AIzaSy")

    try:
        with httpx.Client(timeout=18.0) as client:
            if is_gemini_native:
                # Direct Google Gemini REST endpoint with native JSON schema enforcement
                clean_model = model.replace("models/", "")
                gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/{clean_model}:generateContent?key={key}"
                gemini_payload = {
                    "systemInstruction": {"parts": [{"text": system_prompt}]},
                    "contents": [{"parts": [{"text": user_prompt}]}],
                    "generationConfig": {
                        "responseMimeType": "application/json",
                        "temperature": 0.2
                    }
                }
                resp = client.post(gemini_url, json=gemini_payload)
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates and "content" in candidates[0]:
                        text = candidates[0]["content"]["parts"][0]["text"]
                        parsed = json.loads(text)
                        if "executive_summary" in parsed and "key_findings" in parsed:
                            parsed["provider"] = f"Google Gemini API ({clean_model})"
                            return parsed
            else:
                # Standard OpenAI-compatible proxy or local LLM (Ollama, Groq, vLLM)
                endpoint = url.rstrip('/') + "/chat/completions"
                headers = {
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json"
                }
                payload = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.3
                }
                resp = client.post(endpoint, headers=headers, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"]
                    parsed = json.loads(content)
                    if "executive_summary" in parsed and "key_findings" in parsed:
                        parsed["provider"] = f"LLM ({model})"
                        return parsed
    except Exception as e:
        print(f"[AI Insights] Gemini API exception: {e}", flush=True)

    fallback = generate_fallback_insights(aggregates, variance_data)
    fallback["provider"] += " (LLM call was skipped or encountered a timeout)"
    return fallback
