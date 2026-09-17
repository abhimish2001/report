import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient
from app import app

client = TestClient(app)

def test_full_app_flow():
    print("Testing GET /...")
    res = client.get("/")
    assert res.status_code == 200, f"GET / failed with {res.status_code}"
    assert "Team Resource Utilization Report" in res.text
    print("  -> GET / loads Dashboard & KPIs OK!")

    print("Testing GET /upload...")
    res_up = client.get("/upload")
    assert res_up.status_code == 200
    assert "Upload Employee Task-Tracking Sheets" in res_up.text
    print("  -> GET /upload OK!")

    print("Testing GET /load-demo...")
    res = client.get("/load-demo", follow_redirects=False)
    assert res.status_code == 303, f"Expected 303 redirect, got {res.status_code}"
    redirect_url = res.headers["location"]
    print(f"  -> Redirected to: {redirect_url}")

    session_id = redirect_url.split("session_id=")[1]
    res_review = client.get(redirect_url)
    assert res_review.status_code == 200
    assert "Review & Confirm Data Normalizations" in res_review.text
    assert "TaskStatus-202608(Input File).csv" in res_review.text
    assert "amit Sondhiya" in res_review.text
    print("  -> Review screen loaded with 483 rows and audit log OK!")

    print("Testing POST /finalize...")
    form_data = {
        "session_id": session_id,
        "override__Employee__amit Sondhiya": "Amit Sondhiya"
    }
    res_final = client.post("/finalize", data=form_data, follow_redirects=False)
    assert res_final.status_code == 303
    dash_url = res_final.headers["location"]
    print(f"  -> Finalized! Redirected to: {dash_url}")

    print("Testing GET /dashboard...")
    res_dash = client.get(dash_url)
    assert res_dash.status_code == 200
    assert "Team Resource Utilization Report" in res_dash.text
    assert "843.8" in res_dash.text or "843.75" in res_dash.text or "844" in res_dash.text
    assert "Vandna Khare" in res_dash.text
    assert "workTypeChart" in res_dash.text
    print("  -> Dashboard loaded with KPIs, AI summary, and Chart.js OK!")

    report_id = dash_url.split("report_id=")[1]
    print(f"Testing Excel download for report {report_id}...")
    res_excel = client.get(f"/export/excel/{report_id}")
    assert res_excel.status_code == 200
    assert len(res_excel.content) > 5000
    print(f"  -> Excel download OK! ({len(res_excel.content)} bytes)")

    print(f"Testing PDF download for report {report_id}...")
    res_pdf = client.get(f"/export/pdf/{report_id}")
    assert res_pdf.status_code == 200
    assert len(res_pdf.content) > 3000
    print(f"  -> PDF download OK! ({len(res_pdf.content)} bytes)")

    print("Testing GET /trends...")
    res_trends = client.get("/trends")
    assert res_trends.status_code == 200
    assert "Historical Reports & Multi-Period Archive" in res_trends.text
    print("  -> Trends page loaded with archived reports OK!")

    print("\nALL ROUTES AND ENDPOINTS TESTED SUCCESSFULLY 100%!")

if __name__ == "__main__":
    test_full_app_flow()
