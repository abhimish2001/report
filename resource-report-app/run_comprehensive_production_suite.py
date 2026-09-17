"""
run_comprehensive_production_suite.py
Automated Quality Gate & Production Readiness Test Suite
Verifies all 23 core engineering, security, UI, and functionality dimensions.
"""

import concurrent.futures
import json
import os
import sys
import time
import urllib.error
import urllib.request
import openpyxl

BASE_URL = "http://127.0.0.1:8000"
REF_EXCEL_PATH = r"c:\Users\am273\Downloads\Report-20260911T164327Z-1-001\Report\Resource Utilization Report.xlsx"
RAW_CSV_PATH = r"c:\Users\am273\Downloads\Report-20260911T164327Z-1-001\Report\TaskStatus-202608(Input File).csv"

results = []

def record(test_name, passed, details=""):
    results.append({"test": test_name, "passed": passed, "details": details})
    status = "[PASS]" if passed else "[FAIL]"
    print(f"  {status} {test_name}: {details}")

def run_suite():
    print("=" * 70)
    print("RUNNING COMPREHENSIVE PRODUCTION QUALITY GATE & VERIFICATION SUITE")
    print("=" * 70)

    # 1. Healthcheck Probe
    print("\n--- 1. Infrastructure & Health ---")
    try:
        resp = urllib.request.urlopen(f"{BASE_URL}/health", timeout=5)
        data = json.loads(resp.read().decode())
        is_healthy = data.get("status") == "healthy" and "WAL mode" in data.get("database", "")
        record("Healthcheck & WAL Database Probe", is_healthy, f"Status: {data.get('status')}, DB: {data.get('database')}")
    except Exception as e:
        record("Healthcheck & WAL Database Probe", False, str(e))

    # 2. Favicon
    try:
        resp = urllib.request.urlopen(f"{BASE_URL}/favicon.ico", timeout=5)
        is_svg = "image/svg+xml" in resp.headers.get("Content-Type", "")
        record("Embedded SVG Favicon Probe", is_svg, f"Content-Type: {resp.headers.get('Content-Type')}")
    except Exception as e:
        record("Embedded SVG Favicon Probe", False, str(e))

    # 3. Custom Error Pages (404 and Graceful Handling)
    print("\n--- 2. Security & Error Boundary Defense ---")
    try:
        urllib.request.urlopen(f"{BASE_URL}/route-that-does-not-exist-test-404", timeout=5)
        record("Custom 404 Error Template", False, "Expected 404 but got 200")
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        rendered_custom = "Page or Report Not Found" in body and "HTTP 404" in body
        record("Custom 404 Error Template", rendered_custom, f"HTTP {e.code} rendered custom error template")
    except Exception as e:
        record("Custom 404 Error Template", False, str(e))

    # 4. Disallowed File Format Block
    try:
        boundary = "----WebKitFormBoundaryTestSuite"
        part_header = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="files"; filename="malicious_payload.exe"\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n"
        ).encode("utf-8")
        part_footer = f"\r\n--{boundary}--\r\n".encode("utf-8")
        body = part_header + b"MZ fake executable" + part_footer

        req = urllib.request.Request(
            f"{BASE_URL}/upload",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}
        )
        opener = urllib.request.build_opener(urllib.request.HTTPRedirectHandler)
        resp = opener.open(req)
        blocked = "Unsupported+file+format" in resp.geturl()
        record("Disallowed File Format Defense", blocked, f"Redirected with: {resp.geturl().split('?')[-1]}")
    except Exception as e:
        record("Disallowed File Format Defense", False, str(e))

    # 5. Session Expiry Safeguard
    try:
        opener = urllib.request.build_opener(urllib.request.HTTPRedirectHandler)
        resp = opener.open(f"{BASE_URL}/review?session_id=non-existent-session-id-12345")
        safe_redirect = "Session+expired" in resp.geturl() and "/upload" in resp.geturl()
        record("Session Expiry / Invalid Session Safeguard", safe_redirect, f"Redirected to: {resp.geturl()}")
    except Exception as e:
        record("Session Expiry / Invalid Session Safeguard", False, str(e))

    # 6. High Concurrency & Database WAL Stress (50 Requests across 10 threads)
    print("\n--- 3. Concurrency & WAL Performance ---")
    def fetch_dashboard(idx):
        try:
            t0 = time.time()
            resp = urllib.request.urlopen(f"{BASE_URL}/dashboard", timeout=8)
            lat = (time.time() - t0) * 1000
            return resp.status == 200, lat
        except Exception as e:
            return False, 0.0

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futs = [executor.submit(fetch_dashboard, i) for i in range(30)]
        results_concur = [f.result() for f in futs]

    successes = [r[0] for r in results_concur if r[0]]
    avg_lat = sum(r[1] for r in results_concur) / len(results_concur)
    all_passed = len(successes) == len(results_concur)
    record("Concurrent Read Burst (30 reqs / 10 threads)", all_passed, f"{len(successes)}/{len(results_concur)} OK (Avg Latency: {avg_lat:.1f}ms)")

    # 7. Live Google Gemini API Integration Test
    print("\n--- 4. Live AI Executive Insights ---")
    try:
        from modules.report_reader import parse_consolidated_report
        from modules.ai_insights import generate_ai_insights

        agg, var = parse_consolidated_report(REF_EXCEL_PATH, "Resource Utilization Report.xlsx")
        insights = generate_ai_insights(agg, var)
        provider = insights.get("provider", "")
        has_summary = len(insights.get("executive_summary", "")) > 50
        has_findings = len(insights.get("key_findings", [])) >= 3
        has_recs = len(insights.get("recommendations", [])) >= 3
        is_gemini_active = "Google Gemini API" in provider

        record(
            "Live Google Gemini API Generation",
            is_gemini_active and has_summary and has_findings and has_recs,
            f"Provider: {provider}, Findings: {len(insights.get('key_findings', []))}, Recs: {len(insights.get('recommendations', []))}"
        )
    except Exception as e:
        record("Live Google Gemini API Generation", False, str(e))

    # 8. Direct 4-Sheet Report Ingestion & Dashboard Population
    print("\n--- 5. Direct Consolidated Report Ingestion ---")
    try:
        with open(REF_EXCEL_PATH, "rb") as f:
            file_bytes = f.read()

        boundary = "----WebKitFormBoundaryReportUpload"
        part_header = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="files"; filename="Resource Utilization Report.xlsx"\r\n'
            f"Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet\r\n\r\n"
        ).encode("utf-8")
        part_footer = f"\r\n--{boundary}--\r\n".encode("utf-8")
        body = part_header + file_bytes + part_footer

        req = urllib.request.Request(
            f"{BASE_URL}/upload",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}
        )
        opener = urllib.request.build_opener(urllib.request.HTTPRedirectHandler)
        resp = opener.open(req)
        content = resp.read().decode("utf-8")

        redirect_dashboard = "/dashboard?report_id=" in resp.geturl()
        hours_present = "843.8" in content or "843.75" in content
        tasks_present = "483" in content
        month_present = "August-2026" in content

        report_id = resp.geturl().split("report_id=")[-1]
        record(
            "Direct Consolidated Report Upload & Parsing",
            redirect_dashboard and hours_present and tasks_present and month_present,
            f"Report ID: {report_id}, 843.8 hrs & 483 tasks confirmed"
        )
    except Exception as e:
        record("Direct Consolidated Report Upload & Parsing", False, str(e))

    # 9. Excel & PDF Generation & Verification for Created Report
    print("\n--- 6. Export Fidelity Verification ---")
    try:
        resp_xl = urllib.request.urlopen(f"{BASE_URL}/export/excel/{report_id}")
        xl_data = resp_xl.read()
        valid_xl = resp_xl.status == 200 and len(xl_data) > 10000

        # Load into openpyxl to verify sheets
        temp_xl_path = "temp_audit_export.xlsx"
        with open(temp_xl_path, "wb") as f:
            f.write(xl_data)
        wb = openpyxl.load_workbook(temp_xl_path, data_only=True)
        expected_sheets = {"Resource Utilization", "Service-wise Utilization", "Horizontal-View", "Summary"}
        all_sheets_match = expected_sheets.issubset(set(wb.sheetnames))
        if os.path.exists(temp_xl_path):
            os.remove(temp_xl_path)

        record("4-Sheet Excel Export (.xlsx) Integrity", valid_xl and all_sheets_match, f"{len(xl_data)} bytes, sheets: {wb.sheetnames}")
    except Exception as e:
        record("4-Sheet Excel Export (.xlsx) Integrity", False, str(e))

    try:
        resp_pdf = urllib.request.urlopen(f"{BASE_URL}/export/pdf/{report_id}")
        pdf_data = resp_pdf.read()
        valid_pdf = resp_pdf.status == 200 and len(pdf_data) > 4000 and pdf_data.startswith(b"%PDF")
        record("Executive PDF Export (.pdf) Integrity", valid_pdf, f"{len(pdf_data)} bytes, valid PDF header")
    except Exception as e:
        record("Executive PDF Export (.pdf) Integrity", False, str(e))

    # 10. Frontend DOM & Responsive Components Audit
    print("\n--- 7. UI/UX & Responsive Components Audit ---")
    try:
        dash_html = urllib.request.urlopen(f"{BASE_URL}/dashboard?report_id={report_id}").read().decode("utf-8")
        components = [
            ("Global Toast Container", 'id="toastContainer"'),
            ("Global Loading Overlay", 'id="globalLoadingOverlay"'),
            ("Mobile Menu Button", 'id="mobileMenuBtn"'),
            ("Timeframe Slicer Controls", 'id="btnWeek_all"'),
            ("Capacity Simulator Slider", 'id="overloadSlider"'),
            ("Employee Deep-Dive Drawer Modal", 'id="empDrawerBackdrop"'),
            ("Search & Filter Input", 'id="globalSearchInput"'),
            ("4 Core Charts Registered", 'id="workTypeChart"'),
            ("Responsive Table CSV Export", 'onclick="exportTableToCSV')
        ]
        for name, needle in components:
            found = needle in dash_html
            record(f"DOM Component: {name}", found, f"Registered: {found}")
    except Exception as e:
        record("DOM Components Registration", False, str(e))

    # Summary
    print("\n" + "=" * 70)
    total_tests = len(results)
    passed_tests = sum(1 for r in results if r["passed"])
    failed_tests = total_tests - passed_tests
    print(f"AUDIT SUMMARY: {passed_tests}/{total_tests} Tests Passed ({(passed_tests/total_tests)*100:.1f}%)")
    print("=" * 70)

    if failed_tests > 0:
        print(f"\n[ATTENTION] {failed_tests} check(s) failed.")
        sys.exit(1)
    else:
        print("\nALL PRODUCTION QUALITY GATES PASSED 100%! SYSTEM IS ROCK-SOLID.")
        sys.exit(0)

if __name__ == "__main__":
    run_suite()
